"""GAMA-only calibration, paired experiments, performance gates and reporting."""

from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
import csv
import json
import math
import time
import numpy as np
from scipy import stats
from ..paths import ROOT, write_json, digest
from .headless import (
    RunConfig,
    METHODS,
    CASES,
    OUTPUT,
    ENVIRONMENT_VERSION,
    provenance,
    run,
)


def jobs(
    config: RunConfig,
    parameters: dict[str, list[float]],
    folder: Path,
    seeds: list[int],
    workers: int = 1,
    cases: tuple[str, ...] = CASES,
) -> list[dict]:
    if (
        workers < 1
        or not seeds
        or not cases
        or any(case not in CASES for case in cases)
    ):
        raise ValueError("Positive workers, seeds and registered scenarios required")
    work = []
    for case in cases:
        for seed in seeds:
            for method in parameters:
                c = replace(config, case=case, seed=seed, method=method)
                target = folder / "runs" / case / str(seed) / method
                work.append((c, parameters[method], target))

    def execute(job):
        c, theta, target = job
        return {
            **run(c, theta, target, resume=target.exists()),
            "case": c.case,
            "seed": c.seed,
        }

    with ThreadPoolExecutor(max_workers=workers) as pool:
        result = list(pool.map(execute, work))
    for case in cases:
        for seed in seeds:
            hashes = {
                x["exogenous_hash"]
                for x in result
                if x["case"] == case and x["seed"] == seed
            }
            if len(hashes) != 1:
                raise ValueError(f"Exogenous demand changed: {case}/{seed}")
    return result


def collect_calibration(folders: list[Path], target: Path) -> dict:
    seen_runs = set()
    snapshots = []
    contexts = []
    release = []
    energy = []
    rates = []
    background_rates = []
    eta_factors = []
    arrival_trials = 0
    observed_arrivals = 0
    deadline_nonarrivals = []
    context_tokens = set()
    configurations = []
    for folder in folders:
        folder = folder.resolve()
        if folder in seen_runs: raise ValueError("Duplicate calibration run")
        seen_runs.add(folder)
        record = json.loads((folder / "manifest.json").read_text())
        config = record["config"]
        if (
            record["status"] != "complete"
            or not config["calibrating"]
            or config.get("environment_version") != ENVIRONMENT_VERSION
        ):
            raise ValueError("Calibration requires complete GAMA calibration runs")
        from .headless import checked_result

        checked_result(folder, {"source": provenance()})
        shared={k:v for k,v in config.items() if k not in ("seed","render","timeout_seconds")}
        if configurations and configurations[0]!=shared:raise ValueError("Inconsistent calibration configurations")
        configurations.append(shared)
        previous_snapshots = len(snapshots)
        previous_contexts = len(contexts)
        for p, key, destination in [
            ("calibration_snapshots.csv", "snapshot", snapshots),
            ("calibration_contexts.csv", "context", contexts),
        ]:
            with (folder / p).open() as f:
                for row in csv.DictReader(f):
                    if row.get(key):
                        destination.append(json.loads(row[key]))
        for snapshot in snapshots[previous_snapshots:]:
            powers = snapshot.get("powers", [])
            lo = snapshot.get("release_lo", [])
            hi = snapshot.get("release_hi", [])
            if (
                not 0 <= snapshot["sid"] < 11
                or not powers
                or len(lo) != len(powers)
                or len(hi) != len(powers)
            ):
                raise ValueError("Invalid calibration snapshot dimensions")
            if any(not math.isfinite(x) or x < 0 for x in powers) or any(
                not math.isfinite(a) or not math.isfinite(b) or a < 0 or b < a
                for a, b in zip(lo, hi)
            ):
                raise ValueError("Invalid calibration snapshot values")
        for context in contexts[previous_contexts:]:
            token=(str(folder),context.get("token",context.get("request_id")))
            if token in context_tokens:raise ValueError("Duplicate calibration context")
            context_tokens.add(token)
            if (
                len(context.get("travel", [])) != 11
                or not all(math.isfinite(x) and x >= -1 for x in context["travel"])
                or not 0 <= context["issuer"] < 11
                or not -1 <= context["chosen"] < 11
                or not math.isfinite(context["energy"])
                or context["energy"] <= 0
                or context["max_kw"] <= 0
            ):
                raise ValueError("Invalid calibration request context")
        with (folder / "calibration_fractions.csv").open() as f:
            for row in csv.DictReader(f):
                if row.get("release_fraction") and float(row["release_fraction"]) >= 0:
                    value = float(row["release_fraction"])
                    if not math.isfinite(value) or value > 1:
                        raise ValueError("Invalid release reconstruction fraction")
                    release.append(value)
                if row.get("energy_fraction") and float(row["energy_fraction"]) >= 0:
                    value = float(row["energy_fraction"])
                    if not math.isfinite(value) or value > 1:
                        raise ValueError("Invalid energy reconstruction fraction")
                    energy.append(value)
        outcomes = {
            x["request_id"]: x
            for x in json.loads((folder / "outcomes.json").read_text())
        }
        with (folder / "events.csv").open() as stream:
            arrivals={}
            for event in csv.DictReader(stream):
                if event["terminal_record"]=="arrival":
                    event_key=(event["request_id"],int(event.get("leg",0)))
                    if event_key in arrivals:raise ValueError("Duplicate calibration arrival for request leg")
                    arrivals[event_key]=float(event["time_min"])
        for context in contexts[previous_contexts:]:
            chosen=context.get("chosen",-1)
            if chosen<0 or context["travel"][chosen]<=1e-9:continue
            arrival_trials+=1
            event_key=(context.get("request_id",""),int(context.get("leg",0)))
            issued=float(context.get("at",0.0))
            if event_key in arrivals:
                observed_arrivals+=1
                eta_factors.append(max(1e-9,arrivals[event_key]-issued)/context["travel"][chosen])
            else:
                deadline_nonarrivals.append({"run":str(folder),"token":context.get("token",event_key[0]),"request_id":event_key[0],"leg":event_key[1]})
        rates.append(
            sum(x.get("participating", True) for x in contexts[previous_contexts:])
            / max(1, config["measure_minutes"])
            / 11
        )
        background_rates.append(
            sum(not x.get("participating", True) for x in contexts[previous_contexts:])
            / max(1, config["measure_minutes"])
            / 11
        )
    if not snapshots or not contexts or not release or not energy or not eta_factors:
        raise ValueError(
            "Insufficient GAMA train snapshots/contexts/reconstruction samples; extend calibration"
        )
    priors = []
    for sid in range(11):
        pool = [
            {**x, "issued": 0.0, "source": "prior"}
            for x in snapshots
            if x["sid"] == sid
        ]
        if not pool:
            raise ValueError(f"Missing GAMA station prior {sid}")
        # Deterministic stratified retention, never collapse to a single arbitrary state.
        chosen = np.linspace(0, len(pool) - 1, min(128, len(pool)), dtype=int)
        priors.extend(pool[i] for i in chosen)
    response_prior = {}
    for category in ("private", "taxi", "default"):
        subset = [c for c in contexts if category == "default" or c.get("context") == category]
        counts = np.array([1., 1., 1.])  # Declared Dirichlet smoothing, observable outcomes only.
        for c in subset:
            if c.get("chosen", -1) < 0: counts[2] += 1
            elif c.get("chosen") == c.get("recommended"): counts[0] += 1
            else: counts[1] += 1
        values = counts / counts.sum()
        response_prior[category] = dict(zip(("match", "other", "outside"), values.tolist()))
    result = {
        "schema": "gama-calibration-v3",
        "objective_version": "opportunity-service-3",
        "observation_version": "station-observation-3",
        "response_prior": response_prior,
        "response_identification": "P(observed destination class | offer, category), not latent compliance; Dirichlet(1,1,1)",
        "environment_version": ENVIRONMENT_VERSION,
        "backend": "GAMA",
        "split": "train",
        "source": provenance(),
        "runs": {str(p.resolve()): digest(p / "manifest.json") for p in folders},
        "release_fractions": release,
        "energy_fractions": energy,
        "energy_samples": [x["energy"] for x in contexts],
        "prior_snapshots": priors,
        "arrival_prior": [
            {k: c.get(k, "default" if k == "context" else None) for k in ["issuer", "travel", "energy", "max_kw", "context"]}
            for c in contexts
        ],
        "eta_factors": eta_factors,
        "eta_population": "all observed arrival legs, independent of charging completion",
        "arrival_probability": (observed_arrivals+1)/(arrival_trials+2),
        "arrival_probability_prior": "Beta(1,1), arrival before request termination conditional on a declared destination",
        "deadline_nonarrivals": deadline_nonarrivals,
        "request_rate": float(np.mean(rates)),
        "background_rate": float(np.mean(background_rates)),
    }
    write_json(target, result)
    return result


def report(rows: list[dict], folder: Path, profile: str) -> None:
    if not rows:
        raise ValueError("No GAMA results to report")
    cases = tuple(case for case in CASES if any(r["case"] == case for r in rows))
    identities = [(r["case"], r["seed"], r["method"]) for r in rows]
    if len(set(identities)) != len(identities):
        raise ValueError("Duplicate runs would inflate the statistical sample")
    folder.mkdir(parents=True, exist_ok=True)
    metrics = [
        "objective",
        "mean_travel_min",
        "mean_wait_min",
        "p95_wait_min",
        "peak_queue",
        "utilization",
        "served_count",
        "delivered_kwh",
        "wall_seconds",
        "communication_bytes",
    ]
    # Flatten numerical GAMA objective components for seed-level confidence intervals.
    for row in rows:
        for name,value in row.get("objective_components",{}).items():
            if isinstance(value,(int,float)) and not isinstance(value,bool): row["objective_"+name]=value
    metrics.extend(sorted({key for row in rows for key in row if key.startswith("objective_") and isinstance(row[key],(int,float))}))
    metrics += [
        name
        for name in (
            "mean_completed_time_min", "mean_time_per_opportunity_min", "measurement_opportunity_count",
            "mean_charging_min", "recommendation_latency_mean_ms", "recommendation_latency_p95_ms", "recommendation_latency_max_ms", "event_broadcasts", "periodic_broadcasts", "duplicate_packets", "received_information_age_min", "prediction_service_start_mae_min", "prediction_p95_coverage",
            "unserved_kwh",
            "served_energy_fraction",
            "load_balance_cv",
            "recommendation_match_rate",
            "prediction_completed_mae_min",
            "mean_weight_H",
            "mean_active_weight_mass",
            "mean_recommendation_entropy",
            "cpu_seconds",
            "max_rss_kib",
            "opportunity_count",
            "activated_count",
            "burst_shortfall",
            "persistent_vehicle_count",
            "stranded_vehicle_count",
            "inbound_created",
            "inbound_exited",
        )
        if all(name in row for row in rows)
    ]
    summaries = []
    comparisons = []
    for case in cases:
        for metric in metrics:
            for method in METHODS:
                values = np.array(
                    [
                        r[metric]
                        for r in rows
                        if r["case"] == case and r["method"] == method
                    ],
                    dtype=float,
                )
                if not len(values):
                    continue
                margin = (
                    float(stats.t.ppf(0.975, len(values) - 1) * stats.sem(values))
                    if len(values) > 1
                    else None
                )
                summaries.append(
                    {
                        "case": case,
                        "method": method,
                        "metric": metric,
                        "n": len(values),
                        "mean": float(values.mean()),
                        "ci_low": (
                            float(values.mean() - margin)
                            if margin is not None
                            else None
                        ),
                        "ci_high": (
                            float(values.mean() + margin)
                            if margin is not None
                            else None
                        ),
                    }
                )
            paired = []
            for baseline in METHODS[1:]:
                a = {
                    r["seed"]: r[metric]
                    for r in rows
                    if r["case"] == case and r["method"] == "RANR-AW"
                }
                b = {
                    r["seed"]: r[metric]
                    for r in rows
                    if r["case"] == case and r["method"] == baseline
                }
                if a.keys() != b.keys():
                    raise ValueError("Incomplete paired comparison")
                keys = sorted(a)
                difference = np.array([a[k] - b[k] for k in keys], dtype=float)
                mean = float(difference.mean())
                sd = float(difference.std(ddof=1)) if len(keys) > 1 else 0
                p = (
                    float(stats.ttest_1samp(difference, 0).pvalue)
                    if sd > 0
                    else ((1.0 if mean == 0 else 0.0) if len(keys) > 1 else None)
                )
                margin = (
                    float(stats.t.ppf(0.975, len(keys) - 1) * sd / math.sqrt(len(keys)))
                    if len(keys) > 1
                    else None
                )
                denom = float(np.mean(list(b.values())))
                paired.append(
                    {
                        "case": case,
                        "metric": metric,
                        "baseline": baseline,
                        "n": len(keys),
                        "difference": mean,
                        "ci_low": mean - margin if margin is not None else None,
                        "ci_high": mean + margin if margin is not None else None,
                        "paired_effect_size": mean / sd if sd > 0 else None,
                        "percent_change": 100 * mean / denom if denom else None,
                        "p": p,
                    }
                )
            adjusted = 0.0
            for rank, index in enumerate(
                sorted(
                    (i for i in range(len(paired)) if paired[i]["p"] is not None),
                    key=lambda i: paired[i]["p"],
                )
            ):
                adjusted = max(
                    adjusted, min(1, (len(paired) - rank) * paired[index]["p"])
                )
                paired[index]["p_holm"] = adjusted
            for comparison in paired:
                comparison.setdefault("p_holm", None)
            comparisons.extend(paired)
    for name, data in [("summary", summaries), ("comparisons", comparisons)]:
        write_json(folder / (name + ".json"), data)
        with (folder / (name + ".csv")).open("w") as f:
            writer = csv.DictWriter(f, fieldnames=list(data[0]) if data else [])
            writer.writeheader()
            writer.writerows(data)
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    for metric in ["objective", "mean_wait_min", "p95_wait_min"]:
        fig, ax = plt.subplots(figsize=(8, 3.5))
        for j, method in enumerate(METHODS):
            entries = [
                next(
                    x
                    for x in summaries
                    if x["case"] == case
                    and x["method"] == method
                    and x["metric"] == metric
                )
                for case in cases
            ]
            ax.bar(
                np.arange(len(cases)) + (j - 1.5) * 0.2,
                [x["mean"] for x in entries],
                width=0.2,
                label=method,
            )
        ax.set_xticks(range(len(cases)), cases, rotation=15)
        ax.set_ylabel(metric)
        ax.legend(fontsize=7)
        fig.tight_layout()
        for extension in ["pdf", "svg"]:
            fig.savefig(folder / (metric + "." + extension))
        plt.close(fig)
    (folder / "REPORT_VI.md").write_text(
        f"# Báo cáo RANR GAMA — {profile}\n\nNguồn: {len(rows)} run GAMA. "
        + (
            "Smoke chỉ kiểm chứng pipeline; không phải kết luận nghiên cứu.\n"
            if profile == "smoke"
            else "CI theo seed ghép cặp; Holm cho ba baseline trên từng metric/scenario.\n"
        )
        + "\nXem summary.csv và comparisons.csv. Không mặc định Proposed tốt hơn baseline.\n"
    )


def benchmark_budget(
    candidate_seconds: dict[str, float],
    long_seconds: dict[str, float],
    workers: int,
    hours: float = 72,
    parallel_speedup: float | None = None,
) -> dict:
    if workers < 1 or not math.isfinite(hours) or not 0 < hours <= 72:
        raise ValueError(
            "Positive worker count and a budget of at most 72 hours required"
        )
    speedup = workers if parallel_speedup is None else min(workers, parallel_speedup)
    if not math.isfinite(speedup) or speedup <= 0:
        raise ValueError("Invalid measured parallel speedup")
    if set(candidate_seconds) != set(METHODS) or set(long_seconds) != set(METHODS):
        raise ValueError("Benchmark all four methods first")
    if any(
        not math.isfinite(x) or x <= 0
        for x in [*candidate_seconds.values(), *long_seconds.values()]
    ):
        raise ValueError("Invalid timings")
    selected = None
    for maximum in range(256, 4097, 256):
        minimum = min(1024, maximum)
        interval = min(256, minimum // 4)
        # Three optimizer seeds; every checkpoint long validation; 3 finalists x 3 new long-validation replicates.
        serial = 3 * maximum * sum(candidate_seconds.values()) + (
            3 * math.ceil(maximum / interval) + 9
        ) * sum(long_seconds.values())
        estimated = serial / speedup
        if estimated <= hours * 3600 * 0.85:
            selected = {
                "max_evaluations": maximum,
                "min_evaluations": minimum,
                "validation_every": interval,
                "estimated_seconds": estimated,
            }
    return {
        "passed": selected is not None,
        "hours": hours,
        "reserve_fraction": 0.15,
        "workers": workers,
        "parallel_speedup": speedup,
        "population": 16,
        "optimizer_seeds": [41001, 41002, 41003],
        "budget": selected,
        "candidate_seconds": candidate_seconds,
        "long_validation_seconds": long_seconds,
    }
