"""Checkpointed CMA-ES; every fitness and validation comes from GAMA."""

from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from pathlib import Path
import fcntl
import json
import math
import pickle
import time
import numpy as np
import cma
from ..paths import write_json, digest
from .headless import (
    RunConfig,
    METHODS,
    CASES,
    OUTPUT,
    provenance,
    parameter_record,
    run,
)


def _save(path: Path, value: object) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(pickle.dumps(value, pickle.HIGHEST_PROTOCOL))
    temporary.replace(path)


def _evaluate(
    config: RunConfig,
    method: str,
    theta: list[float],
    folder: Path,
    seed: int,
    workers: int,
    remaining: float | None = None,
) -> tuple[float, list[dict]]:
    work = [
        (replace(config, method=method, case=case, seed=seed + i), theta, folder / case)
        for i, case in enumerate(CASES)
    ]
    end_at = time.monotonic() + remaining if remaining is not None else None

    def execute(job):
        allowance = (
            max(0.001, end_at - time.monotonic()) if end_at is not None else None
        )
        return run(job[0], job[1], job[2], resume=job[2].exists(), wall_limit=allowance)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        rows = list(pool.map(execute, work))
    return float(np.mean([x["objective"] for x in rows])), rows


def train(
    config: RunConfig,
    folder: Path,
    budget_file: Path,
    *,
    resume: bool = False,
    smoke: bool = False,
    workers_override: int | None = None,
) -> dict:
    specification = json.loads(budget_file.read_text())
    if smoke and not config.development:
        raise ValueError("Optimizer smoke requires explicit development configuration")
    if not smoke and (config.development or config.calibrating):
        raise ValueError("Official training requires calibrated controlled demand")
    if not smoke and (
        not specification.get("passed")
        or not specification.get("accuracy_passed")
        or not specification.get("validation_passed")
    ):
        raise ValueError(
            "Training requires actual GAMA benchmark, estimator gate and correctness validation"
        )
    if not smoke:
        freeze = json.loads((OUTPUT / "design_freeze.json").read_text())
        if (freeze.get("source") != provenance() or freeze.get("objective_version") != "opportunity-service-3"
            or not all(freeze.get(k) for k in ("passed", "calibration_passed", "information_passed", "exposure_passed", "objective_sensitivity_passed", "design_validation_passed"))):
            raise ValueError("Official training requires current-source calibration, distributed correctness, objective sensitivity and design freeze")
        selected = freeze.get("selected_config",{})
        for name in ("temperature","p2p_interval","stabilization","failure_beta","energy_beta"):
            if selected.get(name)!=getattr(config,name):
                raise ValueError(f"Config differs from frozen design: {name}")
        physical = json.loads((OUTPUT / "development_validation.json").read_text())
        if not physical.get("passed") or physical.get("source") != provenance():
            raise ValueError(
                "Unified environment requires long development validation before training"
            )
    if not smoke and specification.get("source") != provenance():
        raise ValueError("Benchmark source does not match GAMA implementation")
    if not smoke and specification.get("locked_config") != asdict(config):
        raise ValueError(
            "Use the GAMA benchmark locked_config.json for official training"
        )
    if not smoke and (
        specification["hours"] > 72
        or specification["optimizer_seeds"] != [41001, 41002, 41003]
    ):
        raise ValueError(
            "Official training must respect the registered 72h and three-seed protocol"
        )
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        maximum = specification["budget"]["max_evaluations"]
        minimum = specification["budget"]["min_evaluations"]
        interval = specification["budget"]["validation_every"]
        population = 16
        seeds = specification["optimizer_seeds"]
        workers = workers_override or specification["workers"]
        if not smoke and workers > specification["workers"]:
            raise ValueError("Worker count exceeds measured benchmark configuration")
        if workers < 1:
            raise ValueError("Workers must be positive")
        identity = {
            "source": provenance(),
            "config": asdict(config),
            "budget_sha256": digest(budget_file),
            "profile": "smoke" if smoke else "research",
            "calibration_sha256": (
                digest(Path(config.calibration)) if config.calibration else None
            ),
        }
        checkpoint = folder / "checkpoint.pkl"
        if checkpoint.exists():
            if not resume:
                raise ValueError("Existing training: use --resume")
            state = pickle.loads(checkpoint.read_bytes())
            if state["registration"] != identity:
                raise ValueError("Training registration changed")
        else:
            if resume:
                raise ValueError("No checkpoint to resume")
            slots = []
            for seed in seeds:
                for method in METHODS:
                    es = cma.CMAEvolutionStrategy(
                        np.zeros(4 if method == "Fixed-Weights" else 20),
                        1.0,
                        {"seed": seed, "popsize": population, "verbose": -9},
                    )
                    slots.append(
                        {
                            "method": method,
                            "seed": seed,
                            "optimizer": es,
                            "rng": np.random.get_state(),
                            "evaluations": 0,
                            "generation": 0,
                            "history": [],
                            "best_long": math.inf,
                            "best_parameters": None,
                            "stale": 0,
                            "done": False,
                            "pending": None,
                            "pending_validation": None,
                        }
                    )
            state = {
                "registration": identity,
                "slots": slots,
                "active_seconds": 0.0,
                "status": "running",
            }
            _save(checkpoint, state)
        write_json(folder / "registration.json", {**identity, "status": "running"})
        long_config = replace(
            config, warmup_minutes=1440, measure_minutes=2880, trace=True
        )
        if smoke:
            long_config = config
        design_seconds = 0.0 if smoke else float(freeze.get("design_wall_seconds",0.0))
        limit = min(specification["hours"]*3600,72*3600-design_seconds)
        if limit<=0: raise ValueError("Training/validation allowance exhausted by development design validation")
        start = time.monotonic()
        previous_active = state["active_seconds"]

        def account():
            state["active_seconds"] = previous_active + time.monotonic() - start

        def within_budget():
            account()
            return state["active_seconds"] < limit

        try:
            while any(not s["done"] for s in state["slots"]):
                for slot in state["slots"]:
                    if slot["done"]:
                        continue
                    if not within_budget():
                        state["status"] = "budget_limited"
                        _save(checkpoint, state)
                        write_json(
                            folder / "registration.json",
                            {
                                **identity,
                                "status": "budget_limited",
                                "active_seconds": state["active_seconds"],
                            },
                        )
                        return {"status": "budget_limited"}
                    method = slot["method"]
                    seed = slot["seed"]
                    root = folder / method / str(seed)
                    if slot.get("pending_validation") is not None:
                        pending = slot["pending_validation"]
                        candidate = pending["parameters"]
                        row = pending["row"]
                        score, results = _evaluate(
                            long_config,
                            method,
                            candidate,
                            root / "long_validation" / str(slot["evaluations"]),
                            21001,
                            workers,
                            remaining=max(
                                0.001,
                                limit - previous_active - time.monotonic() + start,
                            ),
                        )
                        row.update(
                            long_validation=score,
                            validation_parameters=candidate,
                            validation_rollouts=len(results),
                            validation_cpu_seconds=sum(
                                r.get("cpu_seconds", 0) for r in results
                            ),
                        )
                        previous = slot["best_long"]
                        improved = not math.isfinite(previous) or (
                            previous - score
                        ) > 0.01 * max(abs(previous), 1e-9)
                        slot["stale"] = 0 if improved else slot["stale"] + 1
                        if score < slot["best_long"]:
                            slot["best_long"] = score
                            slot["best_parameters"] = candidate
                        slot["history"].append(row)
                        slot["pending_validation"] = None
                        slot["done"] = slot["evaluations"] >= maximum or (
                            slot["evaluations"] >= minimum and slot["stale"] >= 3
                        )
                        account()
                        _save(checkpoint, state)
                        write_json(root / "history.json", slot["history"])
                        print(
                            json.dumps(
                                {
                                    "method": method,
                                    "optimizer_seed": seed,
                                    **row,
                                    "active_seconds": state["active_seconds"],
                                }
                            ),
                            flush=True,
                        )
                        continue
                    if slot["pending"] is None:
                        np.random.set_state(slot["rng"])
                        slot["pending"] = slot["optimizer"].ask()
                        slot["rng"] = np.random.get_state()
                        _save(checkpoint, state)
                    work = []
                    deadline_at = time.monotonic() + max(
                        0.001, limit - previous_active - time.monotonic() + start
                    )
                    for candidate, vector in enumerate(slot["pending"]):
                        for i, case in enumerate(CASES):
                            c = replace(
                                config, method=method, case=case, seed=11001 + i
                            )
                            target = (
                                root
                                / "candidates"
                                / str(slot["generation"])
                                / str(candidate)
                                / case
                            )
                            work.append((c, list(vector), target))

                    def evaluate_job(job):
                        return run(
                            job[0],
                            job[1],
                            job[2],
                            resume=job[2].exists(),
                            wall_limit=max(0.001, deadline_at - time.monotonic()),
                        )

                    with ThreadPoolExecutor(max_workers=workers) as pool:
                        results = list(pool.map(evaluate_job, work))
                    fitness = (
                        np.array([r["objective"] for r in results])
                        .reshape(population, len(CASES))
                        .mean(axis=1)
                        .tolist()
                    )
                    rollouts = len(results)
                    cpu = sum(r.get("cpu_seconds", 0) for r in results)
                    np.random.set_state(slot["rng"])
                    slot["optimizer"].tell(slot["pending"], fitness)
                    slot["pending"] = None
                    slot["rng"] = np.random.get_state()
                    slot["evaluations"] += population
                    slot["generation"] += 1
                    row = {
                        "evaluations": slot["evaluations"],
                        "short_best": float(min(fitness)),
                        "short_mean": float(np.mean(fitness)),
                        "rollouts": rollouts,
                        "cpu_seconds": cpu,
                        "long_validation": None,
                    }
                    if (
                        slot["evaluations"] % interval == 0
                        or slot["evaluations"] >= maximum
                    ):
                        slot["pending_validation"] = {
                            "parameters": slot["optimizer"].result.xbest.tolist(),
                            "row": row,
                        }
                        account()
                        _save(checkpoint, state)
                        continue
                    slot["history"].append(row)
                    slot["done"] = slot["evaluations"] >= maximum or (
                        slot["evaluations"] >= minimum and slot["stale"] >= 3
                    )
                    account()
                    _save(checkpoint, state)
                    write_json(root / "history.json", slot["history"])
                    print(
                        json.dumps(
                            {
                                "method": method,
                                "optimizer_seed": seed,
                                **row,
                                "active_seconds": state["active_seconds"],
                            }
                        ),
                        flush=True,
                    )
            # Separate long-validation selection; no test seeds are read.
            for method in METHODS:
                options = [s for s in state["slots"] if s["method"] == method]
                selected = []
                for slot in options:
                    if slot["best_parameters"] is None:
                        raise ValueError("No validated candidate")
                    scores = []
                    for replicate in range(3 if not smoke else 1):
                        if not within_budget():
                            state["status"] = "budget_limited"
                            _save(checkpoint, state)
                            write_json(
                                folder / "registration.json",
                                {
                                    **identity,
                                    "status": "budget_limited",
                                    "active_seconds": state["active_seconds"],
                                },
                            )
                            return {"status": "budget_limited"}
                        score, _ = _evaluate(
                            long_config,
                            method,
                            slot["best_parameters"],
                            folder
                            / "selection"
                            / method
                            / str(slot["seed"])
                            / str(replicate),
                            22001 + 100 * replicate,
                            workers,
                            remaining=limit - state["active_seconds"],
                        )
                        scores.append(score)
                    selected.append((float(np.mean(scores)), slot))
                score, winner = min(selected, key=lambda x: x[0])
                result = parameter_record(
                    method,
                    winner["best_parameters"],
                    trained=not smoke,
                    profile="smoke" if smoke else "research",
                    source=identity["source"],
                    validation_objective=score,
                    optimizer_seed=winner["seed"],
                    calibration_sha256=identity.get("calibration_sha256"),
                    config={
                        **asdict(config),
                        "calibration": (
                            str(Path(config.calibration).resolve())
                            if config.calibration
                            else ""
                        ),
                    },
                    budget_sha256=identity["budget_sha256"],
                )
                write_json(folder / method / "parameters.json", result)
            if not smoke:
                import shutil

                for method in METHODS:
                    published = OUTPUT / "models" / method
                    published.mkdir(parents=True, exist_ok=True)
                    if (published / "parameters.json").exists():
                        shutil.copy2(
                            published / "parameters.json",
                            published / f"parameters_{time.time_ns()}.json",
                        )
                    shutil.copy2(
                        folder / method / "parameters.json",
                        published / "parameters.json",
                    )
            account()
            state["status"] = "complete"
            _save(checkpoint, state)
            write_json(
                folder / "registration.json",
                {
                    **identity,
                    "status": "complete",
                    "active_seconds": state["active_seconds"],
                },
            )
            return {"status": "complete", "active_seconds": state["active_seconds"]}
        except BaseException as error:
            account()
            state["status"] = (
                "budget_limited" if state["active_seconds"] >= limit else "interrupted"
            )
            _save(checkpoint, state)
            write_json(
                folder / "registration.json",
                {
                    **identity,
                    "status": state["status"],
                    "error": str(error),
                    "active_seconds": state["active_seconds"],
                },
            )
            raise
