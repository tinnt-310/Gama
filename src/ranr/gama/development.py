"""Long development validation, kept separate from smoke and official test results."""

from dataclasses import replace, asdict
from pathlib import Path
import csv
import json
import math
from collections import Counter, defaultdict

from ..paths import ROOT, write_json, digest
from .headless import (
    RunConfig,
    METHODS,
    OUTPUT,
    ENVIRONMENT,
    provenance,
    checked_result,
)
from .pipeline import jobs, report
from .contracts import validate_charging_files


def summarize_run(folder: Path) -> dict:
    metrics = checked_result(folder, {"source": provenance()})
    manifest = json.loads((folder / "manifest.json").read_text())
    config = manifest["config"]
    actual_configuration = json.loads((folder / "configuration.json").read_text())
    initial = json.loads((folder / "initial_fleet.json").read_text())
    originals = {x["id"]: x for x in initial}
    if (
        len(originals)
        != config["background_cars"] + config["private_evs"] + config["electric_taxis"]
    ):
        raise ValueError("Initial fleet mismatch")
    if metrics["persistent_vehicle_count"] != len(originals):
        raise ValueError("Persistent fleet changed")
    gateways = json.loads((folder / "gateway_validation.json").read_text())["gateways"]
    present = {}
    traffic_initial = {}
    with (folder / "traffic.csv").open() as f:
        for event in csv.DictReader(f):
            if event["event"] == "capacity_blocked":
                continue
            id = int(event["vehicle_id"])
            kind = event["kind"]
            gate = gateways[int(event["gateway"])]
            if (
                math.hypot(float(event["x"]) - gate["x"], float(event["y"]) - gate["y"])
                >= 2.0001
            ):
                raise ValueError("Traffic entry/exit away from gateway")
            if event["event"] == "entered":
                if id in originals or id in present:
                    raise ValueError("Duplicate vehicle entry")
                present[id] = kind
                traffic_initial[id] = {"soc": float(event["soc"])}
            elif event["event"] == "exited":
                if id not in present:
                    raise ValueError("Vehicle exited without entering")
                del present[id]
            for k, base in (
                ("car", config["background_cars"]),
                ("private", config["private_evs"]),
                ("taxi", config["electric_taxis"]),
            ):
                if sum(v == k for v in present.values()) > math.floor(
                    base * config["rush_extra_percent"] / 100
                ):
                    raise ValueError("Inbound population cap exceeded")
    validate_charging_files(folder)
    outcomes = json.loads((folder / "intent_outcomes.json").read_text())
    counts = Counter((x["kind"], x["status"]) for x in outcomes if x["measured"])
    distances = defaultdict(float)
    daily_metres = defaultdict(float)
    with (folder / "vehicles.csv").open() as f:
        for row in csv.DictReader(f):
            id = int(row["vehicle_id"])
            if id not in originals:
                continue
            metres = float(row["total_metres"])
            if metres + 1e-7 < distances[id]:
                raise ValueError("Vehicle distance decreased")
            day = max(
                0, int((config["initial_hour"] * 60 + float(row["at"]) - 1e-7) // 1440)
            )
            daily_metres[(day, row["kind"])] += metres - distances[id]
            distances[id] = metres
            if row["kind"] != "car":
                soc = float(row["soc"])
                expected = (
                    originals[id]["soc"]
                    + 100
                    * (
                        float(row["total_charged_kwh"])
                        - metres * config["consumption_kwh_km"] / 1000
                    )
                    / actual_configuration["battery_capacity_kwh"]
                )
                if not 0 <= soc <= 100 or abs(max(0, min(100, expected)) - soc) > 1e-4:
                    raise ValueError("SOC/energy conservation failed")
    return {
        "intent_status_counts": {f"{k[0]}/{k[1]}": v for k, v in counts.items()},
        "recommendation_attempts_per_day": metrics["demand_count"]
        * 1440
        / config["measure_minutes"],
        "mean_distance_km_by_kind": {
            kind: sum(distances[x["id"]] for x in initial if x["kind"] == kind)
            / max(1, sum(x["kind"] == kind for x in initial))
            / 1000
            for kind in ("car", "private", "taxi")
        },
        "daily_mean_distance_km_by_kind": {
            f"day_{day}/{kind}": metres
            / max(1, sum(x["kind"] == kind for x in initial))
            / 1000
            for (day, kind), metres in daily_metres.items()
        },
        "peak_queue": metrics["peak_queue"],
        "utilization": metrics["utilization"],
        "waiting_p95_min": metrics["p95_wait_min"],
        "inbound_created": metrics["inbound_created"],
        "inbound_exited": metrics["inbound_exited"],
        "stranded": metrics["stranded_vehicle_count"],
    }


def development(
    config: RunConfig, folder: Path, workers: int = 1, collect_only: bool = False
) -> dict:
    source = provenance()
    config = replace(
        config,
        development=True,
        calibrating=False,
        warmup_minutes=360,
        measure_minutes=3600,
        deadline_minutes=360,
        trace=True,
    )
    if not config.calibration:
        raise ValueError("Long development validation requires train-only calibration")
    seeds, cases = [700001, 700002, 700003], ("normal", "high", "burst")
    if not collect_only:
        jobs(
            config,
            {m: [0.0] * (4 if m == "Fixed-Weights" else 20) for m in METHODS},
            folder,
            seeds,
            workers,
            cases,
        )
    summaries = []
    for case in cases:
        for seed in seeds:
            hashes = set()
            for method in METHODS:
                run_folder = folder / "runs" / case / str(seed) / method
                metrics = checked_result(run_folder, {"source": source})
                record = json.loads((run_folder / "manifest.json").read_text())
                actual = RunConfig(**record["config"])
                if actual != replace(config, case=case, seed=seed, method=method):
                    raise ValueError("Development registration differs")
                hashes.add(metrics["exogenous_hash"])
                summaries.append(
                    {
                        "case": case,
                        "seed": seed,
                        "method": method,
                        **summarize_run(run_folder),
                    }
                )
            if len(hashes) != 1:
                raise ValueError("Exogenous conditions differ between methods")
    if provenance() != source:
        raise ValueError("Source changed during development validation")
    record = {
        "passed": all(x["recommendation_attempts_per_day"] > 0 for x in summaries),
        "source": source,
        "config": config.__dict__,
        "folder": str(folder.resolve()),
        "dependencies": [
            {"path": str((folder / "runs" / case / str(seed) / method / "manifest.json").resolve()),
             "sha256": digest(folder / "runs" / case / str(seed) / method / "manifest.json")}
            for case in cases for seed in seeds for method in METHODS
        ],
        "rollouts": len(summaries),
        "summaries": summaries,
        "congestion_observed": any(x["peak_queue"] > 0 for x in summaries),
        "note": "Low demand/congestion is reported as observed; no automatic demand inflation.",
    }
    write_json(folder / "development_validation.json", record)
    write_json(OUTPUT / "development_validation.json", record)
    return record


def verify_development(path, config):
    from .evidence import read_evidence
    record = read_evidence(path)
    expected = replace(config, development=True, calibrating=False, warmup_minutes=360,
                       measure_minutes=3600, deadline_minutes=360, trace=True)
    if record.get("config") != asdict(expected) or record.get("rollouts") != 36 or not record.get("dependencies"):
        raise ValueError("Development configuration/grid changed or evidence missing")
    folder = Path(record["folder"])
    from .contracts import validate_paired_results
    for case in ("normal", "high", "burst"):
        for seed in (700001,700002,700003):
            groups = []
            for method in METHODS:
                row = checked_result(folder/"runs"/case/str(seed)/method,
                    {"source":provenance(),"config":asdict(replace(expected,case=case,seed=seed,method=method)),
                     "calibration_sha256":digest(Path(config.calibration))})
                if row["demand_count"] <= 0: raise ValueError("Development has no recommendation observations")
                groups.append([{**row,"case":case,"seed":seed}])
            validate_paired_results(groups)
    return record
