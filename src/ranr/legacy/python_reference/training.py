"""CMA-ES with matched rollout budgets, held-out selection and exact resume."""

from __future__ import annotations
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass, replace
import json
from pathlib import Path
import pickle
import fcntl
from time import perf_counter
import numpy as np
from .config import Config, CASES, METHODS
from .experiments import initialize_worker, rollout_job, manifest
from .paths import OUTPUTS, digest, source_manifest, write_json
from .policies import parameter_count


@dataclass(frozen=True)
class TrainingConfig:
    optimizer_seeds: tuple[int, ...] = (41001, 41002, 41003)
    population: int = 16
    validation_every: int = 256
    min_evaluations: int = 1024
    max_evaluations: int = 4096
    patience: int = 3
    relative_improvement: float = 0.01
    workers: int = 8
    # Episodes are distinct from 72-hour final evaluation.
    warmup_minutes: float = 10.0
    measure_minutes: float = 20.0
    train_seed: int = 11001
    validation_seed: int = 21001
    profile: str = "research"

    def __post_init__(self) -> None:
        if not self.optimizer_seeds or len(set(self.optimizer_seeds)) != len(
            self.optimizer_seeds
        ):
            raise ValueError("Distinct optimizer seeds required")
        if (
            self.population < 2
            or self.workers < 1
            or self.min_evaluations < self.population
            or self.max_evaluations < self.min_evaluations
            or self.validation_every % self.population
            or self.min_evaluations % self.population
            or self.max_evaluations % self.population
        ):
            raise ValueError("Invalid optimizer/validation budgets")
        if (
            self.train_seed == self.validation_seed
            or self.patience < 1
            or not 0 <= self.relative_improvement < 1
        ):
            raise ValueError("Invalid split or patience")


def _jobs(
    config: Config,
    settings: TrainingConfig,
    method: str,
    parameters: list,
    validation: bool,
) -> list[tuple]:
    seed = settings.validation_seed if validation else settings.train_seed
    result = []
    for i, case in enumerate(CASES):
        c = config.for_case(case)
        # Train capacity variation is public infrastructure, shared across methods.
        factor = (1.0, 0.8, 1.2)[i % 3]
        c = replace(
            c,
            method=method,
            seed=seed + i,
            warmup_minutes=settings.warmup_minutes,
            measure_minutes=settings.measure_minutes,
            capacity_factor=factor,
            trace=False,
        )
        result.append((c.to_dict(), parameters, None))
    return result


def _atomic_pickle(path: Path, value: object) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL))
    temporary.replace(path)


def train(
    config: Config,
    settings: TrainingConfig,
    folder: Path,
    methods: tuple[str, ...] = METHODS,
    resume: bool = False,
) -> dict:
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / ".lock").open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("Training directory is already active") from error
        return _train(config, settings, folder, methods, resume)


def _train(
    config: Config,
    settings: TrainingConfig,
    folder: Path,
    methods: tuple[str, ...] = METHODS,
    resume: bool = False,
) -> dict:
    """Every checkpoint is after a completed generation; unfinished batches replay."""
    import os

    os.environ.setdefault("MPLCONFIGDIR", str(OUTPUTS / ".cache/matplotlib"))
    import cma

    benchmark = OUTPUTS / "benchmark/selection.json"
    if settings.profile == "research":
        if not benchmark.exists():
            raise ValueError(
                "Run benchmark and estimator accuracy gate before research training"
            )
        selection = json.loads(benchmark.read_text())
        if (
            not selection.get("passed")
            or config.scenarios != selection["scenarios"]
            or selection["source"] != source_manifest()
        ):
            raise ValueError(
                "Benchmark gate not passed or source/scenario count changed; benchmark again"
            )
    folder.mkdir(parents=True, exist_ok=True)
    registration = {
        "simulation": config.to_dict(),
        "training": asdict(settings),
        "methods": list(methods),
        "source": source_manifest(),
        "calibration": digest(OUTPUTS / "data/calibration.json"),
        "splits": {
            "train": [settings.train_seed + i for i in range(6)],
            "validation": [settings.validation_seed + i for i in range(6)],
            "test": [31001 + i for i in range(30)],
        },
        "status": "running",
    }
    record = folder / "registration.json"
    if record.exists():
        old = json.loads(record.read_text())

        def comparable(x):
            value = json.loads(json.dumps(x))
            value.pop("status", None)
            value["training"].pop("workers", None)
            return value

        if comparable(old) != json.loads(json.dumps(comparable(registration))):
            raise ValueError("Training registration differs; use a new folder")
        if not resume:
            raise ValueError("Training folder exists; use --resume")
    write_json(record, registration)
    frozen_source = registration["source"]
    winners = {}
    with ProcessPoolExecutor(
        max_workers=settings.workers, initializer=initialize_worker
    ) as pool:
        for method in methods:
            method_folder = folder / method
            method_folder.mkdir(exist_ok=True)
            candidates = []
            for optimizer_seed in settings.optimizer_seeds:
                checkpoint = method_folder / f"checkpoint_{optimizer_seed}.pkl"
                if checkpoint.exists():
                    state = pickle.loads(checkpoint.read_bytes())
                    es = state["optimizer"]
                    np.random.set_state(state["numpy_state"])
                    evaluations = state["evaluations"]
                    history = state["history"]
                    best = state["best"]
                    stale = state["stale"]
                    last_validation = state["last_validation"]
                    rollouts = state["rollouts"]
                    done = state["done"]
                    cpu_seconds = state.get("cpu_seconds", 0.0)
                    wall_seconds = state.get("wall_seconds", 0.0)
                else:
                    es = cma.CMAEvolutionStrategy(
                        np.zeros(parameter_count(method)),
                        1.0,
                        {
                            "seed": optimizer_seed,
                            "popsize": settings.population,
                            "verbose": -9,
                            "verb_log": 0,
                            "bounds": [-8.0, 8.0],
                        },
                    )
                    evaluations = 0
                    history = []
                    best = {
                        "validation": float("inf"),
                        "parameters": None,
                        "evaluations": 0,
                    }
                    stale = 0
                    last_validation = float("inf")
                    rollouts = 0
                    done = False
                    cpu_seconds = 0.0
                    wall_seconds = 0.0
                while not done and evaluations < settings.max_evaluations:
                    generation_start = perf_counter()
                    if source_manifest() != frozen_source:
                        raise ValueError(
                            "Source changed during training; start a new registered run"
                        )
                    population = es.ask()
                    tasks = [
                        job
                        for parameters in population
                        for job in _jobs(
                            config, settings, method, parameters.tolist(), False
                        )
                    ]
                    metrics = list(pool.map(rollout_job, tasks, chunksize=1))
                    cpu_seconds += sum(row["runtime_seconds"] for row in metrics)
                    rollouts += len(tasks)
                    fitness = [
                        float(
                            np.mean(
                                [r["objective"] for r in metrics[i * 6 : (i + 1) * 6]]
                            )
                        )
                        for i in range(len(population))
                    ]
                    if not np.isfinite(fitness).all():
                        raise ValueError("Empty/nonfinite training objective")
                    es.tell(population, fitness)
                    evaluations += len(population)
                    history.append(
                        {
                            "evaluations": evaluations,
                            "generation_min": min(fitness),
                            "generation_mean": float(np.mean(fitness)),
                            "validation": None,
                            "rollouts": rollouts,
                        }
                    )
                    if (
                        evaluations % settings.validation_every == 0
                        or evaluations >= settings.max_evaluations
                    ):
                        proposed = es.result.xbest.tolist()
                        tasks = _jobs(config, settings, method, proposed, True)
                        scores = list(pool.map(rollout_job, tasks))
                        cpu_seconds += sum(row["runtime_seconds"] for row in scores)
                        rollouts += len(tasks)
                        validation = float(np.mean([r["objective"] for r in scores]))
                        history[-1].update(validation=validation, rollouts=rollouts)
                        old_best = best["validation"]
                        if validation < old_best:
                            best = {
                                "validation": validation,
                                "parameters": proposed,
                                "evaluations": evaluations,
                            }
                        improved = not np.isfinite(last_validation) or (
                            last_validation - best["validation"]
                        ) > settings.relative_improvement * max(
                            abs(last_validation), 1e-9
                        )
                        stale = 0 if improved else stale + 1
                        last_validation = best["validation"]
                        history[-1].update(
                            validation_parameters=proposed,
                            best_parameters=best["parameters"],
                            best_validation=best["validation"],
                        )
                        done = (
                            evaluations >= settings.min_evaluations
                            and stale >= settings.patience
                        )
                        print(
                            json.dumps(
                                {
                                    "method": method,
                                    "optimizer_seed": optimizer_seed,
                                    "evaluations": evaluations,
                                    "validation": validation,
                                    "best_validation": best["validation"],
                                    "stale": stale,
                                    "rollouts": rollouts,
                                }
                            ),
                            flush=True,
                        )
                    done = done or evaluations >= settings.max_evaluations
                    wall_seconds += perf_counter() - generation_start
                    history[-1].update(
                        cpu_seconds=cpu_seconds, wall_seconds=wall_seconds
                    )
                    if evaluations % (4 * settings.population) == 0:
                        print(
                            json.dumps(
                                {
                                    "phase": "training",
                                    "method": method,
                                    "optimizer_seed": optimizer_seed,
                                    "evaluations": evaluations,
                                    "cpu_seconds": cpu_seconds,
                                    "wall_seconds": wall_seconds,
                                }
                            ),
                            flush=True,
                        )
                    state = {
                        "optimizer": es,
                        "numpy_state": np.random.get_state(),
                        "evaluations": evaluations,
                        "history": history,
                        "best": best,
                        "stale": stale,
                        "last_validation": last_validation,
                        "rollouts": rollouts,
                        "done": done,
                        "cpu_seconds": cpu_seconds,
                        "wall_seconds": wall_seconds,
                    }
                    _atomic_pickle(checkpoint, state)
                    write_json(
                        method_folder / f"history_{optimizer_seed}.json", history
                    )
                if best["parameters"] is None:
                    raise ValueError("No validation checkpoint")
                candidates.append(
                    {
                        **best,
                        "optimizer_seed": optimizer_seed,
                        "actual_evaluations": evaluations,
                        "actual_rollouts": rollouts,
                        "cpu_seconds": cpu_seconds,
                        "wall_seconds": wall_seconds,
                    }
                )
            winner = min(candidates, key=lambda x: x["validation"])
            if source_manifest() != frozen_source:
                raise ValueError("Source changed during training")
            output = {
                **winner,
                "method": method,
                "profile": settings.profile,
                "training_completed": True,
                "source": frozen_source,
                "calibration": digest(OUTPUTS / "data/calibration.json"),
                "config": config.to_dict(),
                "restarts": candidates,
            }
            write_json(method_folder / "parameters.json", output)
            winners[method] = output
    registration["status"] = "complete"
    write_json(record, registration)
    write_json(
        folder / "summary.json",
        {
            m: {
                k: v
                for k, v in x.items()
                if k not in ("source", "parameters", "config")
            }
            for m, x in winners.items()
        },
    )
    return winners
