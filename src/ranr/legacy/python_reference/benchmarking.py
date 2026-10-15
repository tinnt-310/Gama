"""Performance and Monte Carlo accuracy gate, run before research optimization."""

from __future__ import annotations
from dataclasses import replace
import json
from pathlib import Path
import resource
from time import perf_counter
import numpy as np
from .calibration import from_dict
from .config import Config, METHODS
from .experiments import resources
from .paths import OUTPUTS, source_manifest, write_json
from .prediction import QueuePredictor
from .records import (
    Exposure,
    Interval,
    QueueJob,
    Request,
    StationObservation,
    StationSnapshot,
)
from .simulation import Simulation


def benchmark(
    config: Config,
    probes: int = 12,
    reference_samples: int = 1024,
    directory: Path = OUTPUTS / "benchmark",
) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    frozen_source = source_manifest()
    start = perf_counter()
    geo, cal = resources()
    load_seconds = perf_counter() - start
    performance = []
    for method in METHODS:
        for case in ("normal", "high", "burst", "delayed"):
            c = replace(
                config.for_case(case),
                method=method,
                warmup_minutes=10.0,
                measure_minutes=20.0,
                trace=False,
                seed=900001,
            )
            r = Simulation(geo, cal, c).run()
            performance.append(r)
            print(
                json.dumps(
                    {
                        "benchmark": method,
                        "case": case,
                        "seconds": r["runtime_seconds"],
                        "requests": r["requests"],
                        "prediction_seconds": r["prediction_seconds"],
                    }
                ),
                flush=True,
            )
    probe_records = []
    for i in range(probes):
        at = 60.0 + i
        sid = i % 11
        # Exact local state, coarse peer state, queue tails and aged snapshots.
        snapshots = []
        for m, station in enumerate(geo.stations):
            level = (i % 4) * 10.0
            width = 0.0 if m == sid else config.snapshot_width_minutes
            release = tuple(
                Interval(level, level + width) if i % 4 else Interval(0.0, 0.0)
                for _ in station.powers
            )
            queue = tuple(
                QueueJob(Interval(15.0, 15.0 + config.queue_energy_width_kwh), 120.0)
                for _ in range((i % 3) * len(station.powers))
            )
            snapshots.append(
                StationSnapshot(
                    m,
                    at if m == sid else at - (i % 3) * 5.0,
                    station.powers,
                    release,
                    queue,
                    "local" if m == sid else "peer",
                )
            )
        travel = tuple(
            float(x) * 60 / config.speed_kmh
            for x in geo.distance_km[i * 37 % len(geo.origin_nodes)]
        )
        req = Request(
            f"probe-{i}",
            at,
            i,
            20.0,
            120.0,
            50.0,
            travel,
            tuple(x * config.speed_kmh / 60 for x in travel),
        )
        exposures = ()
        if i % 3 == 2:
            exposures = (
                Exposure(
                    sid,
                    sid,
                    "benchmark",
                    0,
                    1,
                    at - 2,
                    at + 180,
                    10,
                    travel,
                    20.0,
                    120.0,
                ),
            )
        obs = StationObservation(
            sid,
            at,
            tuple(snapshots),
            exposures,
            tuple(at - 5 if m != sid else at for m in range(11)),
            cal.request_rates,
            10,
            tuple(True for _ in range(11)),
        )
        for method in ("RANR-AW", "No-P2P", "No-Prediction"):
            observed = obs
            if method == "No-P2P":
                observed = replace(
                    obs,
                    snapshots=tuple(
                        snapshots[m] if m == sid else cal.priors[m] for m in range(11)
                    ),
                    watermarks=tuple(at if m == sid else 0.0 for m in range(11)),
                    information_available=tuple(m == sid for m in range(11)),
                )
            reference = QueuePredictor(
                replace(config, method=method, scenarios=reference_samples), cal
            ).estimate(observed, req)
            probe_records.append((method, observed, req, reference))
    accuracies = []
    selected = None
    for samples in (32, 64, 128, 256, 512, 1024):
        if samples > reference_samples:
            continue
        mean_error = []
        tail_error = []
        external_error = []
        times = []
        by_method = {
            method: [[], []] for method in ("RANR-AW", "No-P2P", "No-Prediction")
        }
        for method, obs, req, reference in probe_records:
            predictor = QueuePredictor(
                replace(config, method=method, scenarios=samples), cal
            )
            t = perf_counter()
            estimates = predictor.estimate(obs, req)
            times.append(perf_counter() - t)
            means = [abs(a.mean - b.mean) for a, b in zip(estimates, reference)]
            tails = [abs(a.p95 - b.p95) for a, b in zip(estimates, reference)]
            mean_error.extend(means)
            tail_error.extend(tails)
            by_method[method][0].extend(means)
            by_method[method][1].extend(tails)
            external_error.extend(
                abs(a.externality - b.externality)
                for a, b in zip(estimates, reference)
                if a.externality is not None
            )
        joint = np.mean(
            (np.asarray(mean_error) <= 1.0) & (np.asarray(tail_error) <= 5.0)
        )
        row = {
            "scenarios": samples,
            "probe_station_pairs": len(mean_error),
            "within_tolerance_fraction": float(joint),
            "mean_abs_error_min": float(np.mean(mean_error)),
            "p95_abs_error_min": float(np.mean(tail_error)),
            "externality_abs_error_min": float(np.mean(external_error)),
            "runtime_median_seconds": float(np.median(times)),
            "runtime_p95_seconds": float(np.quantile(times, 0.95)),
            "within_tolerance_by_method": {
                m: float(np.mean((np.asarray(e[0]) <= 1.0) & (np.asarray(e[1]) <= 5.0)))
                for m, e in by_method.items()
            },
        }
        accuracies.append(row)
        print(json.dumps({"accuracy": row}), flush=True)
        if (
            all(x >= 0.95 for x in row["within_tolerance_by_method"].values())
            and selected is None
        ):
            selected = samples
    output = {
        "passed": selected is not None,
        "scenarios": selected,
        "source": frozen_source,
        "reference_samples": reference_samples,
        "development_seed": 900001,
        "accuracy_seed": config.seed,
        "load_seconds": load_seconds,
        "performance": performance,
        "accuracy": accuracies,
        "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "cache_hits": 0,
        "cache_policy": "No prediction cache until invalidation can be proven; shared scenario and vectorized paired trajectories.",
    }
    # A 1024-vs-1024 pass alone does not establish independent MC accuracy.
    if selected == reference_samples:
        output["limitation"] = (
            "Matched-reference identity only; increase independent reference before claiming Monte Carlo precision."
        )
        output["passed"] = False
    if source_manifest() != frozen_source:
        raise ValueError("Source changed during benchmark; run again before training")
    write_json(directory / "selection.json", output)
    return output
