"""Official CLI. All simulation results and trained models originate in GAMA."""

from __future__ import annotations
import argparse
from dataclasses import replace
from pathlib import Path
import json
import time
from ..paths import ROOT, write_json
from .headless import (
    RunConfig,
    METHODS,
    CASES,
    OUTPUT,
    provenance,
    run,
    load_model,
    archive_failed_run,
)
from .pipeline import jobs, collect_calibration, report, benchmark_budget


def main() -> None:
    p = argparse.ArgumentParser(description="RANR GAMA-native research")
    p.add_argument("--config", type=Path, default=ROOT / "configs/gama/research.json")
    sub = p.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate")
    validate.add_argument("--compile", action="store_true")
    smoke = sub.add_parser("smoke")
    smoke.add_argument("--output", type=Path, default=OUTPUT / "smoke/release")
    smoke.add_argument("--workers", type=int, default=1)
    single = sub.add_parser("run")
    single.add_argument("--method", choices=METHODS, default="RANR-AW")
    single.add_argument("--parameters", type=Path)
    single.add_argument("--output", type=Path, required=True)
    single.add_argument("--resume", action="store_true")
    calibration = sub.add_parser("calibrate")
    calibration.add_argument("--output", type=Path, default=OUTPUT / "calibration")
    calibration.add_argument("--collect-only", action="store_true")
    calibration.add_argument(
        "--restart-incomplete",
        action="store_true",
        help="Archive failed episodes and restart them with the current configuration; never resumes GAMA state",
    )
    dev = sub.add_parser("development-validation")
    dev.add_argument("--output", type=Path, default=OUTPUT / "development/release")
    dev.add_argument("--workers", type=int, default=1)
    dev.add_argument("--collect-only", action="store_true")
    bench = sub.add_parser("benchmark")
    bench.add_argument("--output", type=Path, default=OUTPUT / "benchmark/release")
    bench.add_argument("--workers", type=int, nargs="+", default=[1, 2, 4])
    bench.add_argument("--hours", type=float, default=72)
    training = sub.add_parser("train")
    training.add_argument("--output", type=Path, default=OUTPUT / "training/release")
    training.add_argument(
        "--budget", type=Path, default=OUTPUT / "benchmark/release/budget.json"
    )
    training.add_argument("--resume", action="store_true")
    training.add_argument("--smoke", action="store_true")
    training.add_argument("--workers", type=int)
    evaluate = sub.add_parser("evaluate")
    evaluate.add_argument("--models", type=Path, default=OUTPUT / "training/release")
    evaluate.add_argument("--output", type=Path, default=OUTPUT / "evaluation/release")
    evaluate.add_argument("--workers", type=int, default=1)
    reporting = sub.add_parser("report")
    reporting.add_argument("folder", type=Path)
    history = sub.add_parser("report-training")
    history.add_argument(
        "folder", type=Path, default=OUTPUT / "training/release", nargs="?"
    )
    development = sub.add_parser("sensitivity")
    development.add_argument("--models", type=Path, default=OUTPUT / "training/release")
    development.add_argument(
        "--output", type=Path, default=OUTPUT / "sensitivity/release"
    )
    development.add_argument("--workers", type=int, default=1)
    args = p.parse_args()
    if args.command == "validate":
        from ..legacy.scripts.check_gama import check_models, run_model

        frozen = provenance()
        if args.compile:
            check_models()
        run_model(
            "models/tests/RanrScientificTests.gaml",
            "ranr_scientific",
            1,
            "RANR_SCIENTIFIC_PASS",
        )
        run_model(
            "models/tests/RanrInformationTests.gaml",
            "ranr_information",
            1,
            "RANR_INFORMATION_PASS",
        )
        run_model(
            "models/tests/RanrPhysicalTests.gaml",
            "ranr_physical",
            16,
            "RANR_PHYSICAL_PASS",
        )
        run_model(
            "models/tests/RanrParameterTests.gaml",
            "ranr_parameters",
            1,
            "RANR_PARAMETER_PASS",
        )
        run_model(
            "models/tests/RanrScenarioCacheTests.gaml",
            "ranr_scenario_cache",
            1,
            "RANR_SCENARIO_CACHE_PASS",
        )
        for method in METHODS:
            run_model(
                "models/tests/RanrFleetTests.gaml",
                "unified_fleet_test",
                4,
                "RANR_UNIFIED_FLEET_PASS",
                {
                    "ranr_method": ("STRING", method),
                    "ranr_output": (
                        "STRING",
                        str(OUTPUT / "validation_runs" / f"{time.time_ns()}_{method}"),
                    ),
                },
            )
        if provenance() != frozen:
            raise ValueError("GAMA source changed during validation; rerun validation")
        write_json(
            OUTPUT / "validation.json",
            {
                "passed": True,
                "source": frozen,
                "reference_fixtures_checked": True,
                "compile_checked": args.compile,
                "unified_fleet_checked": True,
                "development_validation_passed": False,
            },
        )
        return
    if args.command == "report":
        registration = json.loads((args.folder / "registration.json").read_text())
        rows = json.loads((args.folder / "results.json").read_text())
        if registration["status"] != "complete":
            raise ValueError("Incomplete experiments")
        report(rows, args.folder / "report", registration["profile"])
        return
    if args.command == "report-training":
        from .analysis import training_report

        training_report(args.folder)
        return
    config = RunConfig.load(args.config)
    if args.command == "development-validation":
        from .development import development

        development(config, args.output, args.workers, args.collect_only)
        return
    if args.command == "sensitivity":
        from .analysis import sensitivity

        sensitivity(config, args.output, args.models, args.workers)
        return
    if args.command == "run":
        theta = (
            load_model(args.parameters, args.method, config)
            if args.parameters
            else [0.0] * (4 if args.method == "Fixed-Weights" else 20)
        )
        if not args.parameters and not config.development:
            raise ValueError("Official run needs GAMA parameters")
        print(
            json.dumps(
                run(
                    replace(config, method=args.method),
                    theta,
                    args.output,
                    resume=args.resume,
                )
            )
        )
        return
    if args.command == "smoke":
        if not config.development:
            raise ValueError("Use explicit development smoke configuration")
        parameters = {
            method: [0.0] * (4 if method == "Fixed-Weights" else 20)
            for method in METHODS
        }
        registration = {"status": "running", "profile": "smoke", "source": provenance()}
        args.output.mkdir(parents=True, exist_ok=True)
        write_json(args.output / "registration.json", registration)
        rows = jobs(
            config, parameters, args.output, [91001], args.workers, cases=("normal",)
        )
        if len(rows) != 4:
            raise ValueError("Small smoke requires exactly four GAMA runs")
        write_json(args.output / "results.json", rows)
        registration["status"] = "complete"
        write_json(args.output / "registration.json", registration)
        report(rows, args.output / "report", "smoke")
        return
    if args.command == "calibrate":
        if args.collect_only and args.restart_incomplete:
            p.error("--collect-only cannot be combined with --restart-incomplete")
        args.output.mkdir(parents=True, exist_ok=True)
        folders = [
            args.output / "runs" / str(seed) for seed in [800001, 800002, 800003]
        ]
        if not args.collect_only:
            cal = replace(
                config, development=True, calibrating=True, calibration="", trace=True
            )
            for seed, folder in zip([800001, 800002, 800003], folders):
                if args.restart_incomplete and folder.exists():
                    record = json.loads((folder / "manifest.json").read_text())
                    if record.get("status") == "failed":
                        archived = archive_failed_run(folder)
                        print(f"Preserved failed episode: {archived}", flush=True)
                print(f"Calibration seed {seed}: {folder}", flush=True)
                try:
                    run(
                        replace(cal, seed=seed),
                        [0.0] * 20,
                        folder,
                        resume=folder.exists(),
                    )
                except TimeoutError as error:
                    p.exit(
                        1,
                        f"Calibration incomplete: {error}\nIncrease timeout_seconds if needed, then retry with --restart-incomplete.\n",
                    )
        collect_calibration(folders, args.output / "calibration.json")
        return
    if args.command == "benchmark":
        from .benchmarking import benchmark

        print(json.dumps(benchmark(config, args.output, args.workers, args.hours)))
        return
    if args.command == "train":
        from .training import train

        if args.smoke and args.output == OUTPUT / "training/release":
            args.output = OUTPUT / "training/development_smoke"

        print(
            json.dumps(
                train(
                    config,
                    args.output,
                    args.budget,
                    resume=args.resume,
                    smoke=args.smoke,
                    workers_override=args.workers,
                )
            )
        )
        return
    if args.command == "evaluate":
        if config.development or config.calibrating:
            raise ValueError(
                "Primary evaluation requires a locked, calibrated controlled-demand research configuration"
            )
        parameters = {}
        registration = json.loads((args.models / "registration.json").read_text())
        if (
            registration["status"] != "complete"
            or registration["profile"] != "research"
            or registration["source"] != provenance()
        ):
            raise ValueError("Complete matching GAMA research training required")
        for method in METHODS:
            parameters[method] = load_model(
                args.models / method / "parameters.json", method, config
            )
        config = replace(config, warmup_minutes=1440, measure_minutes=2880, trace=True)
        args.output.mkdir(parents=True, exist_ok=True)
        state = {
            "status": "running",
            "profile": "research",
            "source": provenance(),
            "models": str(args.models.resolve()),
        }
        write_json(args.output / "registration.json", state)
        rows = jobs(
            config, parameters, args.output, list(range(31001, 31031)), args.workers
        )
        if len(rows) != 720:
            raise ValueError("Expected 720 GAMA evaluation runs")
        write_json(args.output / "results.json", rows)
        state["status"] = "complete"
        write_json(args.output / "registration.json", state)
        report(rows, args.output / "report", "research")


if __name__ == "__main__":
    main()
