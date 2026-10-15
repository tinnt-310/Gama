"""Offline certificates, cross-language comparison and Phase A research summaries."""

import argparse
import csv
import json
import importlib.metadata
from pathlib import Path
from time import perf_counter
import numpy as np
from .model import Snapshot, reference, pdhg, objective, integer_reference
from .recovery import round_gkps, repair
from .io import load_snapshot

from ranr.paths import ROOT


def compare(prefix):
    s, x, z, metrics = load_snapshot(prefix)
    start = perf_counter()
    assert x.shape == z.shape == (len(s.edges),)
    assert np.all(np.isfinite(x)) and np.all(np.isfinite(z))
    assert np.all(x >= -1e-9) and np.all(x <= 1 + 1e-9)
    assert np.all((z == 0) | (z == 1)), (prefix, "Nonbinary physical assignment")
    for n in range(s.n):
        assert sum(z[i] for i, e in enumerate(s.edges) if e[0] == n) == 1, (
            prefix,
            n,
            "EV must select one station",
        )
    assert all(
        np.isfinite(float(metrics[key]))
        for key in ("LB", "UB", "relaxed", "pre_repair", "residual")
    )
    assert float(metrics["LB"]) <= float(metrics["UB"]) + 1e-6, (
        prefix,
        "Invalid certificate ordering",
    )
    # Replay the exported budget/tolerances; a 20k timeout is not comparable to a 200k run.
    settings = {}
    config_path = Path(str(prefix) + "_config.csv")
    if config_path.exists():
        with config_path.open() as source:
            config = next(csv.DictReader(source))
        settings = dict(
            max_iterations=int(config["solver_limit"]),
            residual_tolerance=float(config["residual_tolerance"]),
            gap_tolerance=float(config["gap_tolerance"]),
        )
    ref = reference(s)
    py = pdhg(s, **settings)
    residual = max(
        abs(sum(x[i] for i, e in enumerate(s.edges) if e[0] == n) - 1)
        for n in range(s.n)
    )
    gap = abs(objective(s, x, True) - ref["objective"]) / max(1, abs(ref["objective"]))
    dx = float(np.max(abs(x - ref["x"])))
    dp = float(np.max(abs(x - py["x"])))
    assert residual <= 1e-6
    assert float(metrics["LB"]) <= ref["objective"] + 1e-6
    assert abs(float(metrics["UB"]) - objective(s, z)) <= 1e-6
    assert abs(float(metrics["relaxed"]) - objective(s, x, True)) <= 1e-6
    assert float(metrics["UB"]) <= float(metrics["pre_repair"]) + 1e-6
    value = objective(s, z)
    for n in range(s.n):
        row = [i for i, e in enumerate(s.edges) if e[0] == n]
        old = next(i for i in row if z[i] == 1)
        for new in row:
            if new == old:
                continue
            moved = z.copy()
            moved[old] = 0
            moved[new] = 1
            assert objective(s, moved) >= value - 1e-6 - 1e-9, (
                prefix,
                n,
                "Improving relocation remains",
            )
    assert dp < 1e-8, (prefix, dp)
    if metrics["status"] == "converged":
        assert gap <= 1e-5, (prefix, gap)
        if s.theta > 0:
            assert dx <= 1e-3, (prefix, dx)
        assert float(metrics["residual"]) <= 1e-6
    integer = integer_reference(s)["objective"] if s.n <= 10 else None
    if integer is not None:
        assert float(metrics["LB"]) <= integer + 1e-6 <= float(metrics["UB"]) + 2e-6
    return dict(
        prefix=str(prefix.relative_to(ROOT)),
        n=s.n,
        m=s.m,
        h=s.h,
        edges=len(s.edges),
        status=metrics["status"],
        iterations=int(metrics["iterations"]),
        reference=ref["objective"],
        integer_optimum=integer,
        relative_reference_gap=gap,
        assignment_reference_error=dx,
        assignment_python_error=dp,
        LB=float(metrics["LB"]),
        UB=float(metrics["UB"]),
        repair_improvement=float(metrics["pre_repair"]) - float(metrics["UB"]),
        repair_checks=int(metrics["repair_checks"]),
        fallback_checks=int(metrics["fallback_checks"]),
        messages=int(metrics["messages"]),
        logical_bytes=float(metrics["bytes"]),
        consensus_residual=(
            float(metrics["consensus_residual"])
            if "consensus_residual" in metrics
            else None
        ),
        gaml_runtime_ms=float(metrics["runtime_ms"]),
        offline_seconds=perf_counter() - start,
    )


def paired_capacity_experiment():
    """Identical physical queue/inbound, demand and candidates; only C changes."""
    n = 10
    m = 2
    h = 4
    edges = [(i, j, 0, 1.0) for i in range(n) for j in range(m)]
    d = np.full(n, 10.0)
    inbound = np.zeros((m, h))
    inbound[:, 0] = 10.0
    base = Snapshot(n, m, h, edges, d, np.full((m, h), 20.0), inbound, 5, 30, 0.25)
    changed = Snapshot(
        n,
        m,
        h,
        list(edges),
        d.copy(),
        np.array([[0.0] * h, [40.0] * h]),
        inbound.copy(),
        5,
        30,
        0.25,
    )
    same = (
        base.edges == changed.edges
        and np.array_equal(base.d, changed.d)
        and np.array_equal(base.inbound, changed.inbound)
    )
    assert same
    one = pdhg(base)
    two = pdhg(changed)
    out = []
    for label, s, sol in [
        ("balanced_capacity", base, one),
        ("unequal_capacity", changed, two),
    ]:
        ref = reference(s)
        integer = repair(s, round_gkps(s, sol["x"], 42))
        out.append(
            dict(
                case=label,
                capacity=s.capacity.tolist(),
                solver_status=sol["status"],
                iterations=sol["iterations"],
                relaxed_objective=sol["objective"],
                centralized_reference=ref["objective"],
                LB=sol["lower_bound"],
                UB=integer["objective"],
                new_workload=[
                    sum(
                        s.d[e[0]] * sol["x"][i]
                        for i, e in enumerate(s.edges)
                        if e[1] == j
                    )
                    for j in range(m)
                ],
            )
        )
    return dict(
        same_noncapacity_inputs=bool(same),
        inbound=base.inbound.tolist(),
        assignment_l1_difference=float(sum(abs(one["x"] - two["x"]))),
        cases=out,
        ground_truth="paired prescribed-capacity surrogate, not actual waiting",
    )


def controlled_experiments():
    n = 10
    m = 2
    h = 4
    edges = [(i, j, 0, 1.0 + j) for i in range(n) for j in range(m)]
    s = Snapshot(
        n,
        m,
        h,
        edges,
        np.full(n, 10.0),
        np.full((m, h), 20.0),
        np.zeros((m, h)),
        5,
        30,
        0.05,
    )
    sol = pdhg(s)
    z = round_gkps(s, sol["x"], 42)
    fixed = repair(s, z)
    argmax = np.zeros(len(edges))
    for i in range(n):
        argmax[2 * i + int(np.argmax(sol["x"][2 * i : 2 * i + 2]))] = 1
    herding = dict(
        solver_status=sol["status"],
        iterations=sol["iterations"],
        LB=sol["lower_bound"],
        argmax_load=[sum(argmax[j::2]) * 10 for j in range(m)],
        rounded_load=[sum(z[j::2]) * 10 for j in range(m)],
        argmax_objective=objective(s, argmax),
        rounded_objective=objective(s, z),
        repaired_objective=fixed["objective"],
    )
    # A previous committed batch (restricted to station zero) is still travelling.
    true_inbound = np.zeros((m, h))
    true_inbound[0, 0] = 80.0
    with_memory = Snapshot(n, m, h, edges, s.d, s.capacity, true_inbound, 5, 30, 0.05)
    mem = pdhg(with_memory)
    zm = repair(with_memory, round_gkps(with_memory, mem["x"], 42))["z"]
    no_memory_z = fixed["z"]
    memory = dict(
        solver_status=mem["status"],
        iterations=mem["iterations"],
        LB=mem["lower_bound"],
        previous_inbound=80.0,
        no_memory_true_snapshot_objective=objective(with_memory, no_memory_z),
        with_memory_true_snapshot_objective=objective(with_memory, zm),
        no_memory_new_load=[sum(no_memory_z[j::2]) * 10 for j in range(m)],
        with_memory_new_load=[sum(zm[j::2]) * 10 for j in range(m)],
        ground_truth="prescribed-capacity workload surrogate; not physical waiting",
    )
    return dict(
        herding=herding,
        cross_batch=memory,
        paired_capacity=paired_capacity_experiment(),
    )


def physical_metrics(prefix):
    with Path(str(prefix) + "_events.csv").open() as f:
        events = list(csv.DictReader(f))
    grouped = {}
    for e in events:
        grouped.setdefault(e["request_id"], {}).setdefault(e["event"], []).append(e)
    waits = []
    durations = []
    for rid, history in grouped.items():
        for name in ["arrival", "service_started", "service_completed"]:
            assert len(history.get(name, [])) <= 1, (rid, name)
        if "service_started" in history:
            assert "arrival" in history
            w = float(history["service_started"][0]["time_min"]) - float(
                history["arrival"][0]["time_min"]
            )
            assert w >= -1e-9
            waits.append(w)
            assert abs(w - float(history["service_started"][0]["waiting_min"])) <= 1e-9
        if "service_completed" in history:
            start = float(history["service_started"][0]["time_min"])
            finish = float(history["service_completed"][0]["time_min"])
            durations.append(finish - start)
            assert finish >= start
    unfinished = sum(
        not any(k in history for k in ["service_completed", "cancelled", "stranded"])
        for history in grouped.values()
    )
    unstarted = sum(
        "service_started" not in history
        and not any(k in history for k in ["cancelled", "stranded"])
        for history in grouped.values()
    )
    mismatch = True
    config_path = Path(str(prefix) + "_config.csv")
    if config_path.exists():
        with config_path.open() as source:
            config = next(csv.DictReader(source))
        mismatch = config.get("oracle", "mock") == "mock"
    return dict(
        prefix=str(prefix.relative_to(ROOT)),
        sessions=len(grouped),
        started=len(waits),
        completed=len(durations),
        mean_wait_min=float(np.mean(waits)) if waits else None,
        p95_wait_min=float(np.percentile(waits, 95)) if waits else None,
        mean_service_min=float(np.mean(durations)) if durations else None,
        unfinished=unfinished,
        unstarted=unstarted,
        forecast_mismatch=mismatch,
        ground_truth="fixed-port session events",
    )


def physical_prefix(name):
    """Follow isolated main outputs rather than accidentally reading a stale legacy CSV."""
    candidates = list((ROOT / "outputs").glob(name + "_*/run_events.csv"))
    if candidates:
        latest = max(candidates, key=lambda path: path.stat().st_mtime_ns)
        return latest.parent / "run"
    legacy = ROOT / "outputs" / name
    return legacy if Path(str(legacy) + "_events.csv").exists() else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase-a", action="store_true")
    args = parser.parse_args()
    prefixes = [ROOT / "outputs/assignment"]
    if args.phase_a:
        prefixes += [ROOT / f"outputs/phase_a_{i}" for i in range(8)] + [
            ROOT / "outputs/paired_base",
            ROOT / "outputs/paired_changed",
        ]
    records = []
    for prefix in prefixes:
        record = compare(prefix)
        records.append(record)
        print(
            prefix.name,
            record["status"],
            "gap",
            record["relative_reference_gap"],
            flush=True,
        )
    paired_gaml = None
    if args.phase_a:
        base, xb, zb, _ = load_snapshot(ROOT / "outputs/paired_base")
        changed, xc, zc, _ = load_snapshot(ROOT / "outputs/paired_changed")
        assert base.edges == changed.edges
        np.testing.assert_array_equal(base.d, changed.d)
        np.testing.assert_array_equal(base.inbound, changed.inbound)
        assert not np.array_equal(base.capacity, changed.capacity)
        paired_gaml = dict(
            same_noncapacity_inputs=True,
            assignment_l1_difference=float(sum(abs(xb - xc))),
            base_objective=objective(base, xb, True),
            changed_objective=objective(changed, xc, True),
        )
    report = dict(
        paired_gaml=paired_gaml,
        versions={
            name: importlib.metadata.version(name)
            for name in ["numpy", "scipy", "cvxpy", "clarabel"]
        },
        scope="Phase A prescribed mock capacities only. No Robot→EV adapter or robot-awareness claims.",
        comparisons=records,
        controlled=controlled_experiments(),
        physical={
            name: physical_metrics(prefix)
            for name in ["end_to_end", "gis_smoke"]
            if (prefix := physical_prefix(name)) is not None
        },
    )
    (ROOT / "outputs/verification.json").write_text(json.dumps(report, indent=2))
    with (ROOT / "outputs/phase_a_summary.csv").open("w") as f:
        writer = csv.DictWriter(f, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    print("OFFLINE_VERIFICATION_PASS")


if __name__ == "__main__":
    main()
