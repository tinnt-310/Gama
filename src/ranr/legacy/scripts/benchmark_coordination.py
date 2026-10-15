"""Identical exogenous demand: nearest versus fixed-port-aware coordination."""

import csv
import json
import re
from pathlib import Path

from ranr.legacy.scripts.check_gama import run_model
from ranr.legacy.scripts.input_manifest import build_manifest, write_manifest
from ranr.legacy.verification.events import event_metrics
from ranr.legacy.verification.io import load_snapshot
from ranr.legacy.verification.model import objective
from ranr.legacy.verification.run import compare

from ranr.paths import ROOT


def benchmark():
    write_manifest()
    inputs_before = build_manifest()
    results = []
    for case in ("near_busy", "burst", "light", "gis_near_busy"):
        traces = []
        for policy in ("nearest", "proposed"):
            parameters = {"assignment_policy": ("STRING", policy)}
            if case == "gis_near_busy":
                console = run_model(
                    "models/GISCoordinationBenchmark.gaml",
                    "controlled_gis",
                    4802,
                    "GIS_COORDINATION_BENCHMARK_PASS",
                    parameters,
                )
            else:
                parameters["benchmark_case"] = ("STRING", case)
                console = run_model(
                    "models/CoordinationBenchmark.gaml",
                    "controlled",
                    9602,
                    "COORDINATION_BENCHMARK_PASS",
                    parameters,
                )
            match = re.search(r"^RUN_OUTPUT_PREFIX (.+)$", console, re.MULTILINE)
            if not match:
                raise AssertionError("Missing output directory")
            prefix = Path(match.group(1).strip()).resolve()
            trace_path = Path(str(prefix) + "_demand.csv")
            with trace_path.open() as source:
                trace = list(csv.DictReader(source))
            traces.append(trace)
            request_ids = {row["request_id"] for row in trace}
            metrics = event_metrics(prefix, request_ids)
            assert metrics["requests"] == len(trace) == metrics["completed"]
            assert (
                metrics["unfinished"]
                == metrics["cancelled"]
                == metrics["stranded"]
                == 0
            )
            snapshot = Path(str(prefix) + "_batch_1")
            s, x, z, solver_metrics = load_snapshot(snapshot)
            assert abs(objective(s, z) - float(solver_metrics["UB"])) <= 1e-6
            verification = compare(snapshot) if policy == "proposed" else None
            results.append(
                dict(
                    case=case,
                    policy=policy,
                    prefix=str(prefix),
                    events=metrics,
                    solver=solver_metrics,
                    reference=verification,
                )
            )
            print(
                case,
                policy,
                "mean Travel+Waiting:",
                metrics["mean_total_min"],
                flush=True,
            )
        assert traces[0] == traces[1], "Demand differs across policies"
        nearest, proposed = results[-2:]
        if case != "light":
            assert (
                proposed["events"]["mean_total_min"]
                < nearest["events"]["mean_total_min"] - 1e-6
            )
        else:
            assert (
                abs(
                    proposed["events"]["mean_total_min"]
                    - nearest["events"]["mean_total_min"]
                )
                <= 1e-6
            )
    assert build_manifest() == inputs_before, "GIS inputs changed during benchmarking"
    report = {
        "scope": "Synthetic fixed-port demand, including unchanged supplied GIS; no robot-awareness or calibrated city-traffic claim",
        "units": {
            "C,d,H_vir,q": "equivalent_reference_service_minutes",
            "travel,waiting,total": "minutes",
        },
        "input_manifest": inputs_before,
        "paired": results,
    }
    destination = ROOT / "outputs" / "coordination_benchmark.json"
    destination.write_text(json.dumps(report, indent=2) + "\n")
    print("COORDINATION_BENCHMARK_VERIFIED", flush=True)
    return report


if __name__ == "__main__":
    benchmark()
