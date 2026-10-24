"""Actual GAMA performance/accuracy gates; no surrogate candidate evaluation."""

from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
import csv
import math
import json
import time
import numpy as np
from ..paths import ROOT, write_json, digest
from .headless import RunConfig, METHODS, CASES, provenance, run
from .pipeline import benchmark_budget


def _probes(calibration: str, folder: Path, samples: int) -> dict:
    from .validation import run_model

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
        rows = list(csv.DictReader(f))
    keys = [(r["method"],r["station"],r["probe"]) for r in rows]
    if len(keys) != len(set(keys)) or set(keys) != PROBE_KEYS:
        raise ValueError("Missing/duplicate/unexpected prediction probe rows")
    result = {key:{k:float(r[k]) for k in THRESHOLDS} for key,r in zip(keys,rows)}
    if not all(math.isfinite(v) for row in result.values() for v in row.values()):
        raise ValueError("Nonfinite prediction probe")
    return result



THRESHOLDS = {"mean": 1.0, "p95": 5.0, "externality": 5.0}
PROBE_KEYS = {(method, str(sid), str(probe)) for method in METHODS[:3] for sid in range(11) for probe in range(5)}
FITNESS_TOLERANCES = [0.0, 0.01, 0.01, 0.1]


def probe_errors(observed, reference, factor=1.0):
    if set(observed) != PROBE_KEYS or set(reference) != PROBE_KEYS:
        raise ValueError("Missing, duplicate or unexpected prediction probe")
    by_method = {}
    for method in METHODS[:3]:
        keys = sorted(k for k in reference if k[0] == method)
        errors = []
        failed = []
        for key in keys:
            values = [observed[key][name] for name in THRESHOLDS] + [reference[key][name] for name in THRESHOLDS]
            if not all(math.isfinite(value) for value in values):
                raise ValueError("Nonfinite prediction probe")
            error = [abs(observed[key][name] - reference[key][name]) for name in THRESHOLDS]
            errors.append(error)
            if not all(value <= factor * tolerance for value, tolerance in zip(error, THRESHOLDS.values())):
                failed.append({"key": list(key), "absolute_errors": error})
        by_method[method] = {"pass_fraction": (len(keys)-len(failed))/len(keys),
                             "mean_absolute_errors": np.mean(errors, axis=0).tolist(),
                             "max_absolute_errors": np.max(errors, axis=0).tolist(),
                             "failed_probes": failed}
    return by_method


def estimator_accuracy(config, folder):
    reference_samples = 1024
    while reference_samples <= 8192:
        low = _probes(config.calibration, folder, reference_samples)
        high = _probes(config.calibration, folder, reference_samples * 2)
        stability = probe_errors(low, high, 0.5)
        stable = all(row["pass_fraction"] >= .95 for row in stability.values())
        write_json(folder / "reference_stability.json", {"samples": reference_samples,
            "check_samples": reference_samples*2, "passed": stable, "methods": stability,
            "thresholds": {k:v/2 for k,v in THRESHOLDS.items()}})
        if stable: break
        reference_samples *= 2
    else:
        raise ValueError("GAMA Monte Carlo reference remains unstable")
    reference_samples *= 2
    reference_data = high
    accuracy = []
    for samples in [n for n in (32,64,128,256,512,1024,2048,4096) if n < reference_samples]:
        by_method = probe_errors(_probes(config.calibration, folder, samples), reference_data)
        accuracy.append({"samples": samples, "methods": by_method})
        write_json(folder / "accuracy.json", accuracy)
        if all(row["pass_fraction"] >= .95 for row in by_method.values()):
            return {"selected_samples": samples, "reference_samples": reference_samples}
    raise ValueError("GAMA estimator accuracy gate failed; extend samples/reference")


def physical_comparison(result, ref):
    reasons = []
    for name, tolerance in (("mean_travel_min",1), ("mean_wait_min",1), ("p95_wait_min",5)):
        a, b = result.get(name), ref.get(name)
        if a is None or b is None:
            reasons.append(name + ": insufficient observations")
        elif not math.isfinite(a) or not math.isfinite(b) or abs(a-b) > tolerance:
            reasons.append(name + ": accuracy tolerance exceeded")
    for name in ("waiting_sample_count", "measurement_intent_count"):
        if min(result.get(name,0),ref.get(name,0)) <= 0:
            reasons.append(name + ": insufficient observations")
    if min(result.get("measurement_intent_count",0),ref.get("measurement_intent_count",0)) > 0:
        a = result["objective_components"]["conditional_success_rate"]
        b = ref["objective_components"]["conditional_success_rate"]
        if a is None or b is None or abs(a-b) > .01: reasons.append("intent success fraction")
    for i, tolerance in enumerate(FITNESS_TOLERANCES):
        if abs(result["fitness_vector"][i]-ref["fitness_vector"][i]) > tolerance:
            reasons.append("fitness priority " + str(i+1))
    if abs(result["operational_objective"]-ref["operational_objective"]) > .01*max(abs(ref["operational_objective"]),1e-9):
        reasons.append("operational objective")
    return {"passed": not reasons, "reasons": reasons}


def physical_accuracy(config, folder):
    # The default midnight clock ends Measurement before daily departures.
    # Observe the real morning schedule; retain fleet, SOC and physical behavior.
    probe = replace(config, development=True, initial_hour=6.0, warmup_minutes=10, measure_minutes=180, trace=False)
    refs, physical = {}, {}
    for method in METHODS:
        target = folder / "physical_reference" / method
        refs[method] = run(replace(probe, method=method, seed=900101, case="burst", step_seconds=1),
            [0.]*(4 if method=="Fixed-Weights" else 20), target, resume=target.exists())
    for step in (5,10,30,60):
        details = {}
        for method in METHODS:
            target = folder / "physical_steps" / str(step) / method
            result = run(replace(probe, method=method, seed=900101, case="burst", step_seconds=step),
                [0.]*(4 if method=="Fixed-Weights" else 20), target, resume=target.exists())
            details[method] = {**physical_comparison(result,refs[method]), "metrics": result}
        physical[str(step)] = {"passed": all(x["passed"] for x in details.values()), "methods": details}
        write_json(folder / "physical_steps.json", physical)
    if not physical["60"]["passed"]:
        raise ValueError("Registered 60-second physical step failed or probe lacks observations")


def benchmark(config: RunConfig, folder: Path, worker_options: list[int], hours: float, stage="all"):
    from .evidence import read_evidence, reference
    if stage not in {"all","accuracy","performance"}: raise ValueError("Unknown benchmark stage")
    if not worker_options or any(w < 1 for w in worker_options) or not math.isfinite(hours) or not 0 < hours <= 72:
        raise ValueError("Positive workers and a training allowance of at most 72 hours required")
    if config.development: raise ValueError("Official benchmark needs GAMA train calibration")
    from .evidence import verify_native
    validation = verify_native(ROOT / "outputs/gama_ranr/validation.json")
    if not validation.get("compile_checked") or not validation.get("unified_fleet_checked"):
        raise ValueError("Validate frozen GAMA source before benchmark")
    source = provenance()
    folder.mkdir(parents=True, exist_ok=True)
    registration = {"source": source, "calibration_sha256": digest(Path(config.calibration)),
                    "config": config.__dict__, "hours": hours, "worker_options": worker_options}
    # Each stage has its own immutable registration: accuracy chooses samples;
    # performance accepts exactly that locked configuration after design freeze.
    reg_path = folder / ("accuracy_registration.json" if stage != "performance" else "performance_registration.json")
    if reg_path.exists():
        previous = json.loads(reg_path.read_text())
        if any(previous.get(k) != v for k,v in registration.items()): raise ValueError("Existing benchmark registration changed")
    write_json(reg_path, {**registration, "status": "running"})
    if stage in {"all","accuracy"}:
        accuracy = estimator_accuracy(config, folder)
        locked = replace(config,samples=accuracy["selected_samples"])
        physical_accuracy(locked,folder)
        gate = {"passed":True,"source":source,**accuracy,"locked_config":locked.__dict__,
                "calibration_sha256":digest(Path(config.calibration)), "thresholds":THRESHOLDS,
                "fitness_tolerances":FITNESS_TOLERANCES,
                "dependencies":[reference(folder/name) for name in ("accuracy.json","reference_stability.json","physical_steps.json")]
                    + [reference(path) for path in sorted(folder.glob("probes_*.csv"))]
                    + [reference(path) for directory in ("physical_reference","physical_steps")
                       for path in sorted((folder/directory).rglob("manifest.json"))]}
        if provenance()!=source: raise ValueError("Source changed during accuracy benchmark")
        write_json(folder/"accuracy_gate.json",gate)
        write_json(folder/"accuracy_config.json",locked.__dict__)
        write_json(reg_path,{**registration,"status":"complete","passed":True})
        if stage=="accuracy": return gate
    else:
        accuracy = read_evidence(folder/"accuracy_gate.json")
        if accuracy["locked_config"]!=config.__dict__ or accuracy["calibration_sha256"]!=digest(Path(config.calibration)):
            raise ValueError("Performance differs from accuracy-locked configuration")
        locked = config
    from .design import validate_freeze
    validate_freeze(ROOT / "outputs/gama_ranr/design_freeze.json", locked)
    probe = replace(locked,development=True,warmup_minutes=10,measure_minutes=180,trace=False)
    candidate = {}
    long = {}
    performance = []
    for method in METHODS:
        theta = [0.0] * (4 if method == "Fixed-Weights" else 20)
        for horizon in ["registered"]:
            timings = []
            for case in CASES:
                repetitions = []
                for replicate in range(3):
                    c = replace(
                        locked, method=method, case=case, seed=900201 + replicate
                    )
                    if horizon == "long":
                        c = replace(c, warmup_minutes=360, measure_minutes=3600)
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
            candidate[method] = long[method] = sum(timings)
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
                step_seconds=60,
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
        scenarios=locked.samples,
        step_seconds=60,
        concurrency=concurrency,
        reference_samples=accuracy["reference_samples"],
        locked_config=locked.__dict__,
    )
    if provenance() != source:
        raise ValueError("GAMA source changed during benchmark")
    write_json(reg_path, {**registration, "status": "complete", "passed": budget["passed"]})
    budget.update(training_only=True, accuracy_evidence=reference(folder / "accuracy_gate.json"), budget_schema=2,
        dependencies=[reference(reg_path), reference(folder/"accuracy_gate.json"),
                      reference(ROOT/"outputs/gama_ranr/design_freeze.json"),
                      *[reference(p) for p in sorted((folder/"performance").rglob("manifest.json"))],
                      *[reference(folder/"concurrency"/str(row["workers"])/"measurement.json") for row in concurrency]])
    write_json(folder / "budget.json", budget)
    write_json(
        folder / "registration.json",
        {**registration, "status": "complete", "passed": budget["passed"]},
    )
    write_json(folder / "locked_config.json", locked.__dict__)
    return budget
