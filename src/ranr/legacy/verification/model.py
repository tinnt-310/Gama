"""Convex causal workload model, certified box-epigraph PDHG and offline references."""

from dataclasses import dataclass
from itertools import product
import numpy as np
from scipy.sparse import csr_matrix


@dataclass
class Snapshot:
    n: int
    m: int
    h: int
    edges: list  # (EV index, station index, end-of-bin ETA index, travel minutes)
    d: np.ndarray
    capacity: np.ndarray
    inbound: np.ndarray
    delta: float = 5.0
    d_ref: float = 30.0
    theta: float = 0.25
    edge_demand: np.ndarray | None = (
        None  # Fixed per-candidate workload, in service-minutes.
    )

    def __post_init__(self):
        self.d = np.asarray(self.d, float)
        self.capacity = np.asarray(self.capacity, float)
        self.inbound = np.asarray(self.inbound, float)
        if any(
            not isinstance(v, (int, np.integer)) or isinstance(v, bool) or v <= 0
            for v in (self.n, self.m, self.h)
        ):
            raise ValueError("Snapshot dimensions must be positive integers")
        if (
            not np.isfinite(self.delta)
            or self.delta <= 0
            or not np.isfinite(self.d_ref)
            or self.d_ref <= 0
        ):
            raise ValueError(
                "Bin duration and reference workload must be finite and positive"
            )
        if not np.isfinite(self.theta) or self.theta < 0:
            raise ValueError("Temperature must be finite and nonnegative")
        if any(
            not np.all(np.isfinite(v)) or np.any(v < 0)
            for v in (self.d, self.capacity, self.inbound)
        ):
            raise ValueError(
                "Workload, capacity and inbound must be finite and nonnegative"
            )
        if self.d.shape != (self.n,):
            raise ValueError("Invalid EV demand shape")
        if self.capacity.shape != (self.m, self.h) or self.inbound.shape != (
            self.m,
            self.h,
        ):
            raise ValueError("Invalid station/bin shape")
        seen = set()
        for edge in self.edges:
            if len(edge) != 4:
                raise ValueError("Edges require EV, station, bin and travel cost")
            n, m, h, c = edge
            if any(
                not isinstance(v, (int, np.integer)) or isinstance(v, bool)
                for v in (n, m, h)
            ) or not (0 <= n < self.n and 0 <= m < self.m and 0 <= h < self.h):
                raise ValueError("Invalid edge index")
            if not np.isfinite(c) or c < 0:
                raise ValueError("Travel cost must be finite and nonnegative")
            if (n, m) in seen:
                raise ValueError("Duplicate EV/station candidate")
            seen.add((n, m))
        if any(not any(e[0] == n for e in self.edges) for n in range(self.n)):
            raise ValueError("Empty candidate: defer before snapshot")
        self.edge_demand = np.asarray(
            (
                [self.d[e[0]] for e in self.edges]
                if self.edge_demand is None
                else self.edge_demand
            ),
            float,
        )
        if (
            self.edge_demand.shape != (len(self.edges),)
            or not np.all(np.isfinite(self.edge_demand))
            or np.any(self.edge_demand < 0)
        ):
            raise ValueError("Invalid candidate workload")

    @property
    def cost(self):
        return np.array([e[3] for e in self.edges])

    @property
    def upper(self):
        return float((self.inbound.sum() + self.edge_demand.sum()) / self.d_ref)


def eta_bin(eta_min, epoch_min, delta, h):
    """(left,right] bins, current-time arrivals belong to first bin."""
    return min(h - 1, max(0, int(np.ceil(max(0, eta_min - epoch_min) / delta)) - 1))


def backlog(a, c):
    a = np.asarray(a, float)
    c = np.asarray(c, float)
    q = np.zeros_like(a)
    prev = 0.0
    for h in range(len(a)):
        q[h] = a[h] + max(0.0, prev - c[h])
        prev = q[h]
    return q


def prices(a, c, delta=5.0, d_ref=30.0):
    q = backlog(a, c)
    p = np.full(len(q), delta / d_ref)
    for h in range(len(q) - 2, -1, -1):
        if q[h] > c[h + 1]:
            p[h] += p[h + 1]  # choose inactive branch exactly at a kink
    return p


def arrivals(s, x):
    a = s.inbound.copy()
    for i, (n, m, h, _) in enumerate(s.edges):
        a[m, h] += s.edge_demand[i] * x[i]
    return a


def objective(s, x, entropy=False):
    a = arrivals(s, x)
    f = sum(sum(backlog(a[m], s.capacity[m])) for m in range(s.m)) * s.delta / s.d_ref
    val = float(s.cost @ x + f)
    if entropy:
        val += s.theta * float(
            np.sum(np.where(x > 0, x * np.log(np.maximum(x, 1e-300)), 0))
        )
    return val


def entropy_prox(v, tau, theta):
    v = np.asarray(v, float)
    if theta == 0:
        return np.maximum(v, 0)
    lo = np.full_like(v, -745.0)
    hi = np.log(np.maximum(1.0, v))
    # log-coordinate monotone solve: exp(l)+tau*theta*(1+l)=v
    for _ in range(52):
        mid = (lo + hi) / 2
        below = np.exp(mid) + tau * theta * (1 + mid) < v
        lo = np.where(below, mid, lo)
        hi = np.where(below, hi, mid)
    return np.exp((lo + hi) / 2)


def simplex(v):
    u = np.sort(v)[::-1]
    css = np.cumsum(u) - 1
    valid = u - css / np.arange(1, len(u) + 1) > 0
    rho = np.flatnonzero(valid)[-1]
    return np.maximum(v - css[rho] / (rho + 1), 0)


def project_rows(s, x):
    out = np.array(x, copy=True)
    for n in range(s.n):
        idx = [i for i, e in enumerate(s.edges) if e[0] == n]
        out[idx] = simplex(out[idx])
    return out


def build_operator(s):
    e = len(s.edges)
    mh = s.m * s.h
    k = np.zeros((2 * mh + s.n, e + mh))
    b = np.concatenate(
        (
            -s.inbound.ravel() / s.d_ref,
            (s.capacity - s.inbound).ravel() / s.d_ref,
            np.ones(s.n),
        )
    )
    for i, (n, m, h, c) in enumerate(s.edges):
        t = m * s.h + h
        k[t, i] = s.edge_demand[i] / s.d_ref
        k[mh + t, i] = s.edge_demand[i] / s.d_ref
        k[2 * mh + n, i] = 1
    for t in range(mh):
        k[t, e + t] = -1
        k[mh + t, e + t] = -1
        if t % s.h > 0:
            k[mh + t, e + t - 1] = 1
    return csr_matrix(k), b


def dual_bound(s, k, b, y):
    """Infimum of L over x in [0,1], Q in [0,U]. Valid even before convergence."""
    e = len(s.edges)
    v = np.asarray(k.T @ y)
    g = s.cost + v[:e]
    if s.theta:
        z = np.exp(np.clip(-1 - g / s.theta, -745, 0))
        term = np.sum(g * z + s.theta * z * np.log(np.maximum(z, 1e-300)))
    else:
        term = np.minimum(g, 0).sum()
    return float(term + s.upper * np.minimum(s.delta + v[e:], 0).sum() - b @ y)


def pdhg(s, max_iterations=20000, residual_tolerance=1e-6, gap_tolerance=1e-7):
    if (
        not isinstance(max_iterations, (int, np.integer))
        or isinstance(max_iterations, bool)
        or max_iterations <= 0
    ):
        raise ValueError("Iteration budget must be a positive integer")
    if any(not np.isfinite(v) or v <= 0 for v in (residual_tolerance, gap_tolerance)):
        raise ValueError("Solver tolerances must be finite and positive")
    k, b = build_operator(s)
    e = len(s.edges)
    mh = s.m * s.h
    tau = 0.99 / np.sqrt(np.sum(k.data**2))
    sigma = tau
    x = np.array([1 / sum(ee[0] == n for ee in s.edges) for n, m, h, c in s.edges])
    p = np.r_[x, np.zeros(mh)]
    bar = p.copy()
    y = np.zeros(len(b))
    status = "timeout"
    lb = -np.inf
    res = np.inf
    for iteration in range(1, max_iterations + 1):
        y += sigma * (k @ bar - b)
        y[: 2 * mh] = np.maximum(y[: 2 * mh], 0)
        v = p - tau * (k.T @ y)
        new = np.r_[
            entropy_prox(v[:e] - tau * s.cost, tau, s.theta),
            np.clip(v[e:] - tau * s.delta, 0, s.upper),
        ]
        bar = 2 * new - p
        p = new
        if iteration % 20 == 0 or iteration == max_iterations:
            r = k @ p - b
            res = max(
                float(np.max(np.maximum(r[: 2 * mh], 0))),
                float(np.max(abs(r[2 * mh :]))),
            )
            feasible = project_rows(s, p[:e])
            val = objective(s, feasible, True)
            lb = dual_bound(s, k, b, y)
            gap = max(0, val - lb) / max(1, abs(val))
            if res <= residual_tolerance and gap <= gap_tolerance:
                status = "converged"
                break
    return dict(
        x=feasible,
        raw_x=p[:e],
        objective=val,
        lower_bound=lb,
        residual=res,
        gap=gap,
        iterations=iteration,
        status=status,
        tau=tau,
        dual=y,
    )


def reference(s):
    import cvxpy as cp

    e = len(s.edges)
    mh = s.m * s.h
    k, b = build_operator(s)
    x = cp.Variable(e)
    q = cp.Variable(mh)
    p = cp.hstack([x, q])
    v = k @ p
    constraints = [
        x >= 0,
        x <= 1,
        q >= 0,
        q <= s.upper,
        v[: 2 * mh] <= b[: 2 * mh],
        v[2 * mh :] == 1,
    ]
    fun = s.cost @ x + s.delta * cp.sum(q)
    if s.theta:
        fun -= s.theta * cp.sum(cp.entr(x))
    problem = cp.Problem(cp.Minimize(fun), constraints)
    problem.solve(
        solver="CLARABEL",
        tol_gap_abs=1e-10,
        tol_feas=1e-10,
        tol_gap_rel=1e-10,
        max_iter=500,
    )
    if problem.status not in ["optimal", "optimal_inaccurate"]:
        raise RuntimeError(problem.status)
    xx = project_rows(s, x.value)
    return dict(
        x=xx,
        objective=objective(s, xx, True),
        epigraph_objective=float(
            s.cost @ x.value
            + s.delta * sum(q.value)
            + s.theta
            * np.sum(np.maximum(x.value, 0) * np.log(np.maximum(x.value, 1e-300)))
        ),
        status=problem.status,
    )


def integer_reference(s):
    from scipy.optimize import milp, Bounds, LinearConstraint

    k, b = build_operator(s)
    e = len(s.edges)
    mh = s.m * s.h
    lo = np.r_[np.full(2 * mh, -np.inf), np.ones(s.n)]
    result = milp(
        np.r_[s.cost, np.full(mh, s.delta)],
        integrality=np.r_[np.ones(e), np.zeros(mh)],
        bounds=Bounds(np.zeros(e + mh), np.r_[np.ones(e), np.full(mh, s.upper)]),
        constraints=LinearConstraint(k, lo, b),
        options={"mip_rel_gap": 0.0},
    )
    if not result.success:
        raise RuntimeError(result.message)
    z = np.rint(result.x[:e])
    return dict(
        z=z, objective=objective(s, z), lower_bound=float(result.mip_dual_bound)
    )


def enumerate_integer(s):
    groups = [[i for i, e in enumerate(s.edges) if e[0] == n] for n in range(s.n)]
    best = np.inf
    zz = None
    for choices in product(*groups):
        z = np.zeros(len(s.edges))
        z[list(choices)] = 1
        val = objective(s, z)
        if val < best:
            best = val
            zz = z
    return dict(z=zz, objective=best)
