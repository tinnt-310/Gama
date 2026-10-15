"""Bipartite dependent rounding and proxy-screened, exactly verified relocation."""

import numpy as np
from .model import arrivals, prices, objective, project_rows


class RoundingRNG:
    def __init__(self, seed):
        self.state = int(seed) % 4294967296

    def random(self):
        self.state = (1664525 * self.state + 1013904223) % 4294967296
        return self.state / 4294967296


def fractional_trail(s, x):
    adj = {}
    for i, (n, m, h, c) in enumerate(s.edges):
        if 1e-10 < x[i] < 1 - 1e-10:
            u = n
            v = s.n + m
            adj.setdefault(u, []).append((v, i))
            adj.setdefault(v, []).append((u, i))
    if not adj:
        return []
    visited = set()
    active = set()
    parent = {}
    depth = {}
    for root in adj:
        if root in visited:
            continue
        depth[root] = 0
        visited.add(root)
        active.add(root)
        stack = [(root, -1, iter(adj[root]))]
        while stack:
            u, p, neighbors = stack[-1]
            try:
                v, e = next(neighbors)
            except StopIteration:
                active.remove(u)
                stack.pop()
                continue
            if v == p:
                continue
            if v not in visited:
                parent[v] = (u, e)
                depth[v] = depth[u] + 1
                visited.add(v)
                active.add(v)
                stack.append((v, u, iter(adj[v])))
            elif v in active and depth[v] < depth[u]:
                trail = [e]
                w = u
                ancestry = set()
                while w != v:
                    if w not in parent or w in ancestry or len(ancestry) >= len(adj):
                        raise ArithmeticError("Invalid rounding parent chain")
                    ancestry.add(w)
                    w, ee = parent[w]
                    trail.append(ee)
                if len(trail) % 2 or len(set(trail)) != len(trail):
                    raise ArithmeticError("Invalid bipartite rounding cycle")
                return trail
    # Forest: grow a maximal simple path from a leaf. Endpoints have degree one.
    leaf = next((u for u in adj if len(adj[u]) == 1), None)
    if leaf is None:
        raise ArithmeticError("No cycle or leaf in fractional graph")
    path = []
    u = leaf
    prev = -1
    path_nodes = set()
    while True:
        if u in path_nodes or len(path_nodes) >= len(adj):
            raise ArithmeticError("Rounding path revisited a node")
        path_nodes.add(u)
        options = [(v, e) for v, e in adj[u] if v != prev]
        if not options:
            return path
        v, e = options[0]
        path.append(e)
        prev, u = u, v


def round_gkps(s, x, seed=42):
    x = np.asarray(x, float)
    if x.shape != (len(s.edges),) or not np.all(np.isfinite(x)):
        raise ValueError("Rounding needs one finite value per candidate edge")
    x = project_rows(s, x)
    rng = RoundingRNG(seed)
    while True:
        fractional_before = int(np.count_nonzero((x > 1e-10) & (x < 1 - 1e-10)))
        trail = fractional_trail(s, x)
        if not trail:
            if fractional_before:
                raise ArithmeticError("Missing fractional rounding trail")
            break
        if len(set(trail)) != len(trail) or len(trail) > fractional_before:
            raise ArithmeticError("Invalid fractional rounding trail")
        plus = trail[::2]
        minus = trail[1::2]
        alpha = min([1 - x[i] for i in plus] + [x[i] for i in minus])
        beta = min([x[i] for i in plus] + [1 - x[i] for i in minus])
        if not np.isfinite(alpha + beta) or min(alpha, beta) <= 0:
            raise ArithmeticError("Rounding step has no positive progress")
        sign = alpha if rng.random() < beta / (alpha + beta) else -beta
        x[plus] += sign
        x[minus] -= sign
        x[x < 1e-10] = 0
        x[x > 1 - 1e-10] = 1
        if np.count_nonzero((x > 1e-10) & (x < 1 - 1e-10)) >= fractional_before:
            raise ArithmeticError("Rounding did not eliminate a fractional edge")
    z = np.rint(x)
    for n in range(s.n):
        if sum(z[i] for i, e in enumerate(s.edges) if e[0] == n) != 1:
            raise ArithmeticError("GKPS lost EV degree")
    return z


def repair(s, z, top_l=5, tolerance=1e-6):
    z = np.asarray(z, float).copy()
    value = objective(s, z)
    history = [value]
    checks = 0
    fallback_checks = 0
    while True:
        a = arrivals(s, z)
        pi = np.array(
            [prices(a[m], s.capacity[m], s.delta, s.d_ref) for m in range(s.m)]
        )
        moves = []
        for n in range(s.n):
            old = next(i for i, e in enumerate(s.edges) if e[0] == n and z[i] > 0.5)
            _, m, h, c = s.edges[old]
            for new, (nn, j, hh, cc) in enumerate(s.edges):
                if nn == n and new != old:
                    proxy = (
                        cc
                        - c
                        + s.edge_demand[new] * pi[j, hh]
                        - s.edge_demand[old] * pi[m, h]
                    )
                    moves.append((proxy, old, new))
        moves.sort()
        accepted = False
        for index, (_, old, new) in enumerate(moves):
            zz = z.copy()
            zz[old] = 0
            zz[new] = 1
            # Exact objective; GAML updates only the two affected station profiles.
            candidate = objective(s, zz)
            checks += 1
            fallback_checks += int(index >= top_l)
            if candidate < value - tolerance:
                z = zz
                value = candidate
                history.append(value)
                accepted = True
                break
        if not accepted:
            break  # all relocations scanned, not only top-L
    return dict(
        z=z,
        objective=value,
        history=history,
        checks=checks,
        fallback_checks=fallback_checks,
        local_optimum=True,
    )
