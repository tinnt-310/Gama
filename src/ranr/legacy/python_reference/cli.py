"""Single CLI for preparation, validation, performance, training and reporting."""

from __future__ import annotations
import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, replace
import json
from pathlib import Path
import subprocess
import sys
from .benchmarking import benchmark
from .calibration import prepare_calibration
from .config import CASES, Config, METHODS
from .experiments import initialize_worker, rollout_job
from .geography import prepare
from .paths import ROOT, OUTPUTS, digest, source_manifest, write_json
from .reporting import report
from .training import TrainingConfig, train


def evaluate(
    config: Config, models: Path, folder: Path, profile: str, workers: int, seeds: int
) -> dict:
    parameters = {
        m: json.loads((models / m / "parameters.json").read_text()) for m in METHODS
    }
    if profile == "research" and any(
        p["profile"] != "research" or not p["training_completed"]
        for p in parameters.values()
    ):
        raise ValueError(
            "Research evaluation requires completed research training for all methods"
        )
    for m, p in parameters.items():
        if p["source"] != source_manifest() or p["calibration"] != digest(
            OUTPUTS / "data/calibration.json"
        ):
            raise ValueError(f"Model/source/calibration mismatch: {m}")
        if p["config"]["scenarios"] != config.scenarios or p["config"][
            "feature_scales"
        ] != list(config.feature_scales):
            raise ValueError("Estimator/normalization changed after training")
    registration = {
        "profile": profile,
        "cases": list(CASES),
        "seeds": list(
            range(
                31001 if profile == "research" else 91001,
                (31001 if profile == "research" else 91001) + seeds,
            )
        ),
        "methods": list(METHODS),
        "config": config.to_dict(),
        "source": source_manifest(),
        "models": {m: digest(models / m / "parameters.json") for m in METHODS},
        "status": "running",
    }
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "registration.json"
    if path.exists():
        previous = json.loads(path.read_text())
        if {k: v for k, v in previous.items() if k != "status"} != json.loads(
            json.dumps({k: v for k, v in registration.items() if k != "status"})
        ):
            raise ValueError("Evaluation registration changed; use another folder")
    write_json(path, registration)
    tasks = []
    for case in CASES:
        for method in METHODS:
            for seed in registration["seeds"]:
                c = replace(
                    config.for_case(case),
                    method=method,
                    seed=seed,
                    trace=True,
                    capacity_factor=1.0,
                )
                tasks.append(
                    (
                        c.to_dict(),
                        parameters[method]["parameters"],
                        str(folder / "runs" / case / method / str(seed)),
                    )
                )
    with ProcessPoolExecutor(
        max_workers=workers, initializer=initialize_worker
    ) as pool:
        results = []
        for result in pool.map(rollout_job, tasks, chunksize=1):
            results.append(result)
            print(
                json.dumps(
                    {
                        "evaluation": len(results),
                        "total": len(tasks),
                        "method": result["method"],
                        "case": result["case"],
                        "seed": result["seed"],
                        "objective": result["objective"],
                    }
                ),
                flush=True,
            )
    registration["status"] = "complete"
    write_json(path, registration)
    return report(folder)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "configs/research.json")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("prepare")
    sub.add_parser("validate")
    bench = sub.add_parser("benchmark")
    bench.add_argument("--probes", type=int, default=12)
    training = sub.add_parser("train")
    training.add_argument(
        "--settings", type=Path, default=ROOT / "configs/training_research.json"
    )
    training.add_argument("--output", type=Path, default=OUTPUTS / "training/research")
    training.add_argument("--method", choices=METHODS)
    training.add_argument("--resume", action="store_true")
    evaluation = sub.add_parser("evaluate")
    evaluation.add_argument(
        "--models", type=Path, default=OUTPUTS / "training/research"
    )
    evaluation.add_argument(
        "--output", type=Path, default=OUTPUTS / "evaluation/research"
    )
    evaluation.add_argument(
        "--profile", choices=("smoke", "research"), default="research"
    )
    evaluation.add_argument("--workers", type=int, default=8)
    evaluation.add_argument("--seeds", type=int, default=30)
    reporting = sub.add_parser("report")
    reporting.add_argument("folder", type=Path)
    args = parser.parse_args()
    if args.command == "report":
        print(report(args.folder)["report"])
        return
    config = Config.read(args.config)
    if args.command == "prepare":
        legacy = ROOT / "models/outputs"
        if not legacy.exists() and not legacy.is_symlink():
            (ROOT / "outputs/legacy").mkdir(parents=True, exist_ok=True)
            legacy.symlink_to("../outputs/legacy", target_is_directory=True)
        geo = prepare()
        cal = prepare_calibration(geo)
        print(
            json.dumps(
                {
                    "GIS": geo.validation["checks"],
                    "calibration_release_samples": len(cal.release_fractions),
                    "calibration_energy_samples": len(cal.energy_fractions),
                },
                ensure_ascii=False,
            )
        )
    elif args.command == "validate":
        prepare()
        result = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
            cwd=ROOT,
        )
        if result.returncode:
            raise SystemExit(result.returncode)
    elif args.command == "benchmark":
        result = benchmark(config, args.probes)
        print(
            json.dumps({"passed": result["passed"], "scenarios": result["scenarios"]})
        )
        if not result["passed"]:
            raise SystemExit(1)
    elif args.command == "train":
        values = json.loads(args.settings.read_text())
        values["optimizer_seeds"] = tuple(values["optimizer_seeds"])
        settings = TrainingConfig(**values)
        train(
            config,
            settings,
            args.output,
            (args.method,) if args.method else METHODS,
            args.resume,
        )
    elif args.command == "evaluate":
        if args.profile == "research" and (
            args.seeds < 30
            or config.warmup_minutes < 1440
            or config.measure_minutes < 2880
        ):
            raise ValueError(
                "Research evaluation requires 30 seeds, 24h warmup and 48h measurement"
            )
        evaluate(
            config, args.models, args.output, args.profile, args.workers, args.seeds
        )


if __name__ == "__main__":
    main()
