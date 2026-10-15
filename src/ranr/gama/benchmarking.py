"""Actual GAMA performance/accuracy gates; no surrogate candidate evaluation."""

from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
import csv
import json
import time
import numpy as np
from ..paths import ROOT, write_json, digest
from .headless import RunConfig, METHODS, CASES, provenance, run
from .pipeline import benchmark_budget


def _probes(calibration: str, folder: Path, samples: int) -> dict:
    from ..legacy.scripts.check_gama import run_model

    target = folder / f"probes_{samples}.csv"
    if not target.exists():
        run_model(
            "models/tests/RanrPredictionBenchmark.gaml",
            "ranr_prediction_benchmark",
            1,
            "RANR_PREDICTION_BENCHMARK_PASS",
            {
                "probe_output": ("STRING", str(target.resolve())),
                "ranr_calibration_file": ("STRING", str(Path(calibration).resolve())),
                "ranr_samples": ("INT", samples),
            },
            seed=900001,
        )
    with target.open() as f:
        return {
            (r["method"], r["station"], r["probe"]): {
                k: float(r[k]) for k in ["mean", "p95", "externality"]
            }
            for r in csv.DictReader(f)
        }


def benchmark(
    config: RunConfig, folder: Path, worker_options: list[int], hours: float
) -> dict:
    if not worker_options or any(w < 1 for w in worker_options) or not 0 < hours <= 72:
        raise ValueError(
            "Positive workers and a training allowance of at most 72 hours required"
        )
    if config.development:
        raise ValueError("Official benchmark needs GAMA train calibration")
    validation = json.loads((ROOT / "outputs/gama_ranr/validation.json").read_text())
    source = provenance()
    if (
        not validation.get("passed")
        or not validation.get("compile_checked")
        or not validation.get("unified_fleet_checked")
        or validation["source"] != source
    ):
        raise ValueError("Validate frozen GAMA source before benchmark")
    folder.mkdir(parents=True, exist_ok=True)
    registration = {
        "source": source,
        "calibration_sha256": digest(Path(config.calibration)),
        "config": config.__dict__,
        "hours": hours,
        "worker_options": worker_options,
    }
    if (folder / "registration.json").exists():
        previous = json.loads((folder / "registration.json").read_text())
        if any(previous.get(k) != v for k, v in registration.items()):
            raise ValueError("Existing benchmark registration changed")
    write_json(folder / "registration.json", {**registration, "status": "running"})
    reference_samples = 1024
    while True:
        reference = _probes(config.calibration, folder, reference_samples)
        check = _probes(config.calibration, folder, reference_samples * 2)
        stable = all(
            np.mean(
                [
                    abs(reference[k]["mean"] - check[k]["mean"]) <= 0.5
                    and abs(reference[k]["p95"] - check[k]["p95"]) <= 2.5
                    for k in reference
                    if k[0] == method
                ]
            )
            >= 0.95
            for method in METHODS[:3]
        )
        write_json(
            folder / "reference_stability.json",
            {
                "samples": reference_samples,
                "check_samples": reference_samples * 2,
                "passed": bool(stable),
            },
        )
        if stable:
            break
        reference_samples *= 2
        if reference_samples > 8192:
            raise ValueError("GAMA Monte Carlo reference remains unstable")
    reference = _probes(config.calibration, folder, reference_samples * 2)
    reference_samples *= 2
    accuracy = []
    selected_samples = None
    for samples in [
        n for n in [32, 64, 128, 256, 512, 1024, 2048, 4096] if n < reference_samples
    ]:
        observed = _probes(config.calibration, folder, samples)
        if observed.keys() != reference.keys():
            raise ValueError("Probe mismatch")
        by_method = {}
        for method in METHODS[:3]:
            keys = [k for k in reference if k[0] == method]
            errors = [
                (
                    abs(observed[k]["mean"] - reference[k]["mean"]),
                    abs(observed[k]["p95"] - reference[k]["p95"]),
                    abs(observed[k]["externality"] - reference[k]["externality"]),
                )
                for k in keys
            ]
            fraction = float(np.mean([a <= 1 and b <= 5 for a, b, _ in errors]))
            by_method[method] = {
                "pass_fraction": fraction,
                "mean_absolute_errors": np.mean(errors, axis=0).tolist(),
            }
        accuracy.append({"samples": samples, "methods": by_method})
        write_json(folder / "accuracy.json", accuracy)
        if min(v["pass_fraction"] for v in by_method.values()) >= 0.95:
            selected_samples = samples
            break
    if selected_samples is None:
        raise ValueError(
            "GAMA estimator accuracy gate failed; extend samples/reference"
        )
    locked = replace(config, samples=selected_samples)
    # Timesteps are verified against 1-second GAMA physical runs before any speedup.
    probe = replace(
        locked,
        warmup_minutes=10,
        measure_minutes=180,
        background_cars=config.background_cars,
        trace=False,
    )
    physical = {}
    reference_physical = {}
    for method in METHODS:
        reference_physical[method] = run(
            replace(probe, method=method, seed=900101, case="burst", step_seconds=1),
            [0.0] * (4 if method == "Fixed-Weights" else 20),
            folder / "physical_reference" / method,
            resume=(folder / "physical_reference" / method).exists(),
        )
    physical["1"] = {"passed": True}
    selected_step = 1
    for step in [5, 10, 30, 60]:
        passed = True
        details = {}
        for method in METHODS:
            result = run(
                replace(
                    probe, method=method, seed=900101, case="burst", step_seconds=step
                ),
                [0.0] * (4 if method == "Fixed-Weights" else 20),
                folder / "physical_steps" / str(step) / method,
                resume=(folder / "physical_steps" / str(step) / method).exists(),
            )
            ref = reference_physical[method]
            passed &= (
                abs(result["mean_travel_min"] - ref["mean_travel_min"]) <= 1
                and abs(result["mean_wait_min"] - ref["mean_wait_min"]) <= 1
                and abs(result["p95_wait_min"] - ref["p95_wait_min"]) <= 5
            )
            passed &= abs(
                result["served_count"] / result["demand_count"]
                - ref["served_count"] / ref["demand_count"]
            ) <= 0.01 and abs(result["objective"] - ref["objective"]) <= 0.01 * max(
                abs(ref["objective"]), 1e-9
            )
            details[method] = result
        physical[str(step)] = {"passed": bool(passed), "metrics": details}
        if passed:
            selected_step = step
        write_json(folder / "physical_steps.json", physical)
    locked = replace(locked, step_seconds=selected_step)
    candidate = {}
    long = {}
    performance = []
    for method in METHODS:
        theta = [0.0] * (4 if method == "Fixed-Weights" else 20)
        for horizon in ["short", "long"]:
            timings = []
            for case in CASES:
                repetitions = []
                for replicate in range(3):
                    c = replace(
                        locked, method=method, case=case, seed=900201 + replicate
                    )
                    if horizon == "long":
                        c = replace(c, warmup_minutes=1440, measure_minutes=2880)
                    target = (
                        folder
                        / "performance"
                        / horizon
                        / method
                        / case
                        / str(replicate)
                    )
                    metrics = run(c, theta, target, resume=target.exists())
                    repetitions.append(metrics["wall_seconds"])
                    performance.append(
                        {
                            "method": method,
                            "horizon": horizon,
                            "case": case,
                            "replicate": replicate,
                            **metrics,
                        }
                    )
                    write_json(folder / "performance.json", performance)
                timings.append(float(np.percentile(repetitions, 95)))
            # Sum observed scenario P95 values, including JVM launches and settlement.
            (candidate if horizon == "short" else long)[method] = sum(timings)
    available_kib = next(
        int(line.split()[1])
        for line in Path("/proc/meminfo").read_text().splitlines()
        if line.startswith("MemAvailable:")
    )
    peak = max(r["max_rss_kib"] for r in performance)
    concurrency = []
    batch_size = max(8, max(worker_options))
    for workers in sorted(set([1, *worker_options])):
        if workers < 1 or workers * peak > available_kib * 0.7:
            continue
        measurement = folder / "concurrency" / str(workers) / "measurement.json"
        if measurement.exists():
            concurrency.append(json.loads(measurement.read_text()))
            continue
        # An interrupted batch without a timing record starts a fresh attempt.
        # Cached results must never count as fresh GAMA throughput.
        attempt = folder / "concurrency" / str(workers) / str(time.time_ns())
        start = time.perf_counter()

        def work(i):
            c = replace(
                probe,
                step_seconds=selected_step,
                seed=900301 + i,
                method=METHODS[i % 4],
            )
            return run(
                c, [0.0] * (4 if c.method == "Fixed-Weights" else 20), attempt / str(i)
            )

        with ThreadPoolExecutor(max_workers=workers) as pool:
            rows = list(pool.map(work, range(batch_size)))
        elapsed = time.perf_counter() - start
        record = {
            "workers": workers,
            "jobs": batch_size,
            "wall_seconds": elapsed,
            "throughput": batch_size / elapsed,
            "max_rss_kib": workers * max(r["max_rss_kib"] for r in rows),
            "attempt": str(attempt.resolve()),
        }
        write_json(measurement, record)
        concurrency.append(record)
    if not concurrency or not any(r["workers"] == 1 for r in concurrency):
        raise ValueError("No feasible GAMA worker configuration")
    best = max(concurrency, key=lambda x: x["throughput"])
    workers = best["workers"]
    baseline = next(r["throughput"] for r in concurrency if r["workers"] == 1)
    speedup = min(workers, best["throughput"] / baseline)
    budget = benchmark_budget(candidate, long, workers, hours, parallel_speedup=speedup)
    budget.update(
        source=source,
        accuracy_passed=True,
        validation_passed=True,
        scenarios=selected_samples,
        step_seconds=selected_step,
        concurrency=concurrency,
        reference_samples=reference_samples,
        locked_config=locked.__dict__,
    )
    if provenance() != source:
        raise ValueError("GAMA source changed during benchmark")
    write_json(folder / "budget.json", budget)
    write_json(
        folder / "registration.json",
        {**registration, "status": "complete", "passed": budget["passed"]},
    )
    write_json(folder / "locked_config.json", locked.__dict__)
    return budget
