from ranr.paths import ROOT

"""Same PDHG equations, explicit larger budget for the two timed-out physical fixtures."""
import json
import re
import argparse
import csv
from pathlib import Path

from ranr.legacy.scripts.check_gama import run_model
from ranr.legacy.verification.run import compare


def verify_extended(snapshots=None):
    records = []
    cases = [
        (
            "burst",
            "models/CoordinationBenchmark.gaml",
            "controlled",
            9602,
            "COORDINATION_BENCHMARK_PASS",
        ),
        (
            "gis_near_busy",
            "models/GISCoordinationBenchmark.gaml",
            "controlled_gis",
            4802,
            "GIS_COORDINATION_BENCHMARK_PASS",
        ),
    ]
    for index, (case, model, experiment, steps, marker) in enumerate(cases):
        if snapshots:
            snapshot = Path(snapshots[index]).resolve()
        else:
            parameters = {
                "assignment_policy": ("STRING", "proposed"),
                "solver_limit": ("INT", "200000"),
            }
            if case == "burst":
                parameters["benchmark_case"] = ("STRING", case)
            console = run_model(model, experiment, steps, marker, parameters)
            match = re.search(r"^RUN_OUTPUT_PREFIX (.+)$", console, re.MULTILINE)
            if not match:
                raise AssertionError("Missing run prefix")
            prefix = Path(match.group(1).strip()).resolve()
            snapshot = Path(str(prefix) + "_batch_1")
        with Path(str(snapshot) + "_config.csv").open() as source:
            config = next(csv.DictReader(source))
        assert int(config["solver_limit"]) == 200000
        result = compare(snapshot)
        # The approved solver contract reports budget exhaustion as non-convergence.
        assert result["status"] in ("converged", "timeout"), result
        if result["status"] == "converged":
            assert result["relative_reference_gap"] <= 1e-5, result
        else:
            assert result["iterations"] == 200000, result
        records.append(
            dict(case=case, explicit_iteration_budget=200000, verification=result)
        )
        print(case, result, flush=True)
    destination = ROOT / "outputs" / "coordination_extended_solver.json"
    report = dict(
        all_converged=all(r["verification"]["status"] == "converged" for r in records),
        scope="Cross-language replay and reference/certificate checks; timeout is not convergence",
        cases=records,
    )
    destination.write_text(json.dumps(report, indent=2) + "\n")
    print("EXTENDED_SOLVER_ALL_CONVERGED", report["all_converged"], flush=True)
    print("EXTENDED_SOLVER_REPLAY_PASS", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--snapshots",
        nargs=2,
        help="Replay existing 200k burst and GIS snapshot prefixes without rerunning physics",
    )
    verify_extended(parser.parse_args().snapshots)
