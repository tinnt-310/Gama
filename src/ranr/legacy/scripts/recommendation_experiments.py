"""Reproducible GAMA recommendation experiments and causal offline development.

No Python is called from GAMA. Development seeds are disjoint from test seeds.
Results are conditional on synthetic FOLLOW_RECOMMENDATION behavior.
"""

import argparse
import csv
import json
import math
from pathlib import Path
import sys
import time
import numpy as np

from ranr.paths import ROOT
from ranr.legacy.scripts.check_gama import run_model
from ranr.legacy.verification.recommendation import (
    LocalForecast,
    RidgeCorrection,
    shadow_wait,
)

OUT = ROOT / "outputs/recommendation_validation"


from ranr.legacy.evaluation import rows, evaluate


def launch(
    mode,
    seed,
    hours=48,
    threshold=-1,
    case="feedback_shift",
    policy="minimax",
    normalization="feasible",
    delay=0,
    penalty=1.0,
    correction=True,
    extra=None,
):
    pattern = (
        f"recommendation_{case}_{mode}_{policy}_{seed}_*/run_recommendation_config.csv"
    )
    before = set((ROOT / "outputs").glob(pattern))
    parameters = {
        "run_hours": ("FLOAT", str(hours)),
        "waiting_forecast_mode": ("STRING", mode),
        "replay_similarity_threshold": ("FLOAT", str(threshold)),
        "benchmark_case": ("STRING", case),
        "recommendation_method": ("STRING", policy),
        "normalization_mode": ("STRING", normalization),
        "neighbor_delay_minutes": ("FLOAT", str(delay)),
        "ridge_penalty": ("FLOAT", str(penalty)),
        "neighbor_correction_enabled": ("BOOLEAN", str(correction).lower()),
    }
    parameters.update(extra or {})
    console = run_model(
        "models/RecommendationBenchmark.gaml",
        "recommendation_benchmark",
        int(hours * 60) + 2,
        "RECOMMENDATION_BENCHMARK_PASS",
        parameters,
        seed=seed,
    )
    files = set((ROOT / "outputs").glob(pattern)) - before
    if len(files) != 1:
        raise RuntimeError(f"Ambiguous outputs {files}")
    prefix = Path(str(files.pop()).removesuffix("_recommendation_config.csv"))
    OUT.mkdir(exist_ok=True, parents=True)
    (OUT / f"{mode}_{case}_{policy}_{seed}_{normalization}_{delay}.log").write_text(
        console
    )
    return prefix


def calibrate(prefixes):
    """Select replay threshold on dev-only physical probe waiting, not future train labels.

    Compare the same physical snapshots/probe ETAs for every candidate threshold.
    Neighbor ridge is NOT selected by workload-only error; separate held-out waiting
    evaluation below reports whether it actually transfers through accepted replay.
    """
    thresholds = [0.25, 0.5, 1.0, 2.0, 4.0]
    losses = {x: [] for x in thresholds}
    coverage = {x: 0 for x in thresholds}
    nearest = []
    total = 0
    baseline = []
    for prefix in prefixes:
        events = rows(str(prefix) + "_events.csv")
        for station in sorted(
            {r["station"] for r in events if r["event"] == "arrival"}
        ):
            arrivals = sorted(
                (float(r["time_min"]), float(r["requested_kwh"]))
                for r in events
                if r["event"] == "arrival" and r["station"] == station
            )
            model = LocalForecast()
            for t, e in arrivals:
                model.observe(t, e)
            end = max((t for t, e in arrivals), default=0)
            for issued in np.arange(120, end - 20, 20):
                release = 0.0
                for t, e in arrivals:
                    if t >= issued:
                        break
                    release = max(release, t) + max(1, math.ceil(60 * e / 54 - 1e-10))
                free = [max(0.0, release - issued)]
                for eta in (1.0, 2.0, 5.0, 10.0, 20.0):
                    truth = shadow_wait(
                        [60.0],
                        free,
                        [
                            (t - issued, e)
                            for t, e in arrivals
                            if issued <= t <= issued + eta
                        ],
                        eta,
                        tick=1.0,
                    )
                    physical = shadow_wait([60.0], free, [], eta, tick=1.0)
                    baseline.append(abs(physical - truth))
                    total += 1
                    forecast = model.predict(issued, max(1, int(math.ceil(eta / 5))))
                    for threshold in thresholds:
                        scenarios, status = model.scenarios(
                            issued, forecast, threshold=threshold
                        )
                        pred = (
                            float(
                                np.mean(
                                    [
                                        shadow_wait([60.0], free, s, eta, tick=1.0)
                                        for s in scenarios
                                    ]
                                )
                            )
                            if scenarios
                            else physical
                        )
                        losses[threshold].append(abs(pred - truth))
                        coverage[threshold] += int(bool(scenarios))
                        if threshold == thresholds[0] and status["error"] is not None:
                            nearest.append(status["error"])
    candidates = [x for x in thresholds if coverage[x] / max(1, total) >= 0.05]
    selected = (
        min(candidates, key=lambda x: (np.mean(losses[x]), x)) if candidates else -1
    )
    result = {
        "selected_threshold": selected,
        "probe_cases": total,
        "development_prefixes": [str(p) for p in prefixes],
        "physical_mae": float(np.mean(baseline)) if baseline else None,
        "thresholds": {
            str(x): {
                "waiting_mae": float(np.mean(losses[x])) if losses[x] else None,
                "coverage": coverage[x] / max(1, total),
            }
            for x in thresholds
        },
        "selection": "minimum dev probe waiting MAE among >=5% replay coverage; no test tuning",
        "synthetic": True,
        "behavior": "FOLLOW_RECOMMENDATION",
        "not_empirically_calibrated": True,
    }
    (OUT / "development_calibration.json").write_text(
        json.dumps(result, indent=2) + "\n"
    )
    return selected


def select_neighbor_penalty(prefixes, threshold):
    """Same archived arrival trace for local/neighbor; only matured labels train ridge.

    Every forecast is issued before its bin is observed. Physical probe outcomes
    are available only to development evaluator, not model features.
    """
    candidates = [None, 0.1, 1.0, 10.0]
    results = []
    for penalty in candidates:
        workload_errors = []
        wait_errors = []
        coverage = 0
        cases = 0
        for prefix in prefixes:
            events = rows(str(prefix) + "_events.csv")
            names = sorted({r["station"] for r in events if r["event"] == "arrival"})
            local = {name: LocalForecast() for name in names}
            arrivals = {
                name: sorted(
                    (float(r["time_min"]), float(r["requested_kwh"]))
                    for r in events
                    if r["event"] == "arrival" and r["station"] == name
                )
                for name in names
            }
            for name in names:
                for t, e in arrivals[name]:
                    local[name].observe(t, e)
            end = max(t for data in arrivals.values() for t, e in data)
            models = {
                (name, h): RidgeCorrection(6, penalty=penalty or 1)
                for name in names
                for h in range(24)
            }
            pending = []
            for issued in np.arange(0, end - 20, 5):
                closed = int(issued / 5)
                for item in list(pending):
                    name, target, h, feature, base = item
                    if target >= closed:
                        continue
                    # bins(issued) excludes current and every future bin.
                    actual = local[name].bins(issued)[target]
                    models[name, h].observe(feature, (actual - base) / 30)
                    pending.remove(item)
                forecasts = {}
                for name in names:
                    base = float(local[name].predict(issued, 1)[0])
                    values = []
                    neighbors = [n for n in names if n != name]
                    received = (
                        [
                            float(local[n].predict(max(0, issued - 5), 1)[0])
                            for n in neighbors
                        ]
                        if issued >= 5
                        else []
                    )
                    mean_neighbor = float(np.mean(received)) if received else 0.0
                    for h in range(24):
                        feature = [
                            1.0,
                            mean_neighbor / 30,
                            (mean_neighbor - base) / 30,
                            1.0 if received else 0.0,
                            0.0 if received else 1.0,
                            h / 24,
                        ]
                        corrected = max(
                            0.0,
                            base
                            + (
                                models[name, h].predict(feature) * 30
                                if penalty is not None
                                else 0.0
                            ),
                        )
                        values.append(corrected)
                        pending.append((name, closed + h, h, feature, base))
                        if issued >= 120 and closed + h < int(end / 5):
                            # Evaluation oracle only, never used to fit before label maturity.
                            actual = sum(
                                60 * e / 54
                                for t, e in arrivals[name]
                                if (closed + h) * 5 <= t < (closed + h + 1) * 5
                            )
                            workload_errors.append(corrected - actual)
                    forecasts[name] = values
                if issued < 120 or int(issued) % 20:
                    continue
                for name in names:
                    release = 0.0
                    for t, e in arrivals[name]:
                        if t >= issued:
                            break
                        release = max(release, t) + max(
                            1, math.ceil(60 * e / 54 - 1e-10)
                        )
                    free = [max(0.0, release - issued)]
                    for eta in (1.0, 2.0, 5.0, 10.0, 20.0):
                        truth = shadow_wait(
                            [60.0],
                            free,
                            [
                                (t - issued, e)
                                for t, e in arrivals[name]
                                if issued <= t <= issued + eta
                            ],
                            eta,
                            tick=1.0,
                        )
                        scenarios, status = local[name].scenarios(
                            issued,
                            np.array(
                                forecasts[name][: max(1, int(math.ceil(eta / 5)))]
                            ),
                            threshold=threshold,
                        )
                        pred = (
                            np.mean(
                                [
                                    shadow_wait([60.0], free, s, eta, tick=1.0)
                                    for s in scenarios
                                ]
                            )
                            if scenarios
                            else shadow_wait([60.0], free, [], eta, tick=1.0)
                        )
                        wait_errors.append(pred - truth)
                        coverage += bool(scenarios)
                        cases += 1
        results.append(
            {
                "ridge_penalty": penalty,
                "workload_mae": float(np.mean(np.abs(workload_errors))),
                "workload_rmse": float(np.sqrt(np.mean(np.square(workload_errors)))),
                "waiting_mae": float(np.mean(np.abs(wait_errors))),
                "waiting_rmse": float(np.sqrt(np.mean(np.square(wait_errors)))),
                "replay_coverage": coverage / max(1, cases),
            }
        )
    baseline = results[0]
    valid = [
        r
        for r in results[1:]
        if r["workload_mae"] <= baseline["workload_mae"] + 1e-9
        and r["waiting_mae"] < baseline["waiting_mae"] - 1e-9
    ]
    selected = min(valid, key=lambda r: r["waiting_mae"]) if valid else baseline
    report = {
        "candidates": results,
        "selected": selected,
        "correction_supported": selected["ridge_penalty"] is not None,
        "selection": "both workload MAE no worse AND waiting MAE lower on development; fallback local otherwise",
        "same_trace": True,
        "development_prefixes": [str(p) for p in prefixes],
        "features": "previous-bin neighbor forecasts, fixed scaling, no future features; per-horizon ridge",
        "physical_reference": "one 60kW port, 60s tick, controlled benchmark only",
    }
    (OUT / "neighbor_development.json").write_text(json.dumps(report, indent=2) + "\n")
    return selected["ridge_penalty"]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--seeds", type=int, default=10)
    p.add_argument("--hours", type=float, default=48)
    p.add_argument("--development-hours", type=float, default=24)
    p.add_argument("--summarize-only", nargs="*")
    args = p.parse_args()
    OUT.mkdir(exist_ok=True, parents=True)
    if args.summarize_only is not None:
        for prefix in args.summarize_only:
            print(json.dumps(evaluate(Path(prefix))))
        return
    dev = [launch("B3", seed, args.development_hours) for seed in (101, 102)]
    threshold = calibrate(dev)
    selected_penalty = select_neighbor_penalty(dev, threshold)
    results = []
    for seed in range(1, args.seeds + 1):
        demand_hashes = []
        for mode in ("B3", "B4", "B4-N"):
            prefix = launch(
                mode,
                seed,
                args.hours,
                threshold,
                penalty=selected_penalty or 1.0,
                correction=selected_penalty is not None,
            )
            result = evaluate(prefix)
            result.update(mode=mode, seed=seed, hours=args.hours)
            results.append(result)
            import hashlib

            demand_hashes.append(
                hashlib.sha256(
                    Path(str(prefix) + "_demand.csv").read_bytes()
                ).hexdigest()
            )
            (OUT / "closed_loop_results.json").write_text(
                json.dumps(results, indent=2) + "\n"
            )
        if len(set(demand_hashes)) != 1:
            raise AssertionError("Policy changed exogenous demand stream")
    (OUT / "experiment_manifest.json").write_text(
        json.dumps(
            {
                "seeds": list(range(1, args.seeds + 1)),
                "development_seeds": [101, 102],
                "hours": args.hours,
                "threshold": threshold,
                "selected_neighbor_penalty": selected_penalty,
                "same_exogenous_demand_verified": True,
                "behavior": "FOLLOW_RECOMMENDATION controlled assumption",
                "clock_step_seconds": 60,
                "synthetic_network": True,
                "physical_step_limitation": "coarse timing; not detailed city-scale evidence",
            },
            indent=2,
        )
        + "\n"
    )
    print("RECOMMENDATION_EXPERIMENTS_PASS")


if __name__ == "__main__":
    main()
