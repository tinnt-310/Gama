"""Register and validate calibration produced by the interactive GAMA experiment."""

from __future__ import annotations
from .contracts import TERMINAL, validate_ledger, finite_tree, rescore_components, validate_configuration
from dataclasses import asdict, replace
from pathlib import Path
import csv
import hashlib
import json
import math
import sys
import time

from ..paths import ROOT, digest, write_json
from .headless import RunConfig, ENVIRONMENT_VERSION, provenance, checked_result
from .pipeline import collect_calibration

SEEDS = (800001, 800002, 800003)
GUI_ROOT = ROOT / "outputs/gama_ranr/gui_calibration"


def prepare(folder: Path) -> dict:
    if (folder / "manifest.json").exists():
        raise FileExistsError("Refusing to overwrite an existing collection")
    config = replace(
        RunConfig.load(ROOT / "configs/gama/calibration.json"),
        seed=int(folder.name.split("_")[1]),
        render=True,
    )
    if config.seed not in SEEDS:
        raise ValueError("Unregistered calibration seed")
    record = {
        "status": "running",
        "backend": "GAMA",
        "origin": "GAMA_GUI",
        "run_id": folder.name,
        "config": asdict(config),
        "source": provenance(),
        "started_at": time.time(),
    }
    write_json(folder / "manifest.json", record)
    return record


def complete(folder: Path) -> dict:
    record = json.loads((folder / "manifest.json").read_text())
    if record["status"] != "running" or record["source"] != provenance():
        raise ValueError("Collection source changed or episode was already finalized")
    config = record["config"]
    actual = json.loads((folder / "configuration.json").read_text())
    mapping = {
        "background_cars": "initial_private_cars",
        "private_evs": "initial_private_evs",
        "electric_taxis": "initial_electric_taxis",
        "samples": "scenarios",
    }
    for key in (
        "seed",
        "environment_version",
        "warmup_minutes",
        "measure_minutes",
        "deadline_minutes",
        "initial_hour",
        "step_seconds",
        "consumption_kwh_km",
        "charge_efficiency",
        "private_frequency",
        "taxi_frequency",
        "soc_threshold",
        "target_soc",
        "rush_enabled",
        "rush_extra_percent",
        "ev_speed_kmh",
        "car_speed_kmh",
        "compliance",
        "defer_probability",
        "burst_size",
        "background_cars",
        "private_evs",
        "electric_taxis",
        "samples",
        "calibrating", "method", "objective_version", "observation_version", "temperature", "p2p_interval", "min_send_seconds", "stabilization", "behavior_case", "failure_beta", "energy_beta", "decline_probability", "abandon_after_minutes",
    ):
        if actual.get(mapping.get(key, key)) != config[key]:
            raise ValueError(f"Collection configuration mismatch: {key}")
    if (
        actual["environment_version"] != ENVIRONMENT_VERSION
        or not actual["calibrating"]
    ):
        raise ValueError("Wrong calibration environment")
    marker = json.loads((folder / "completion.json").read_text())
    metrics = json.loads((folder / "metrics.json").read_text())
    outcomes = json.loads((folder / "outcomes.json").read_text())
    if marker.get("status") != "complete" or any(
        x.get("run_id") != record["run_id"] for x in (marker, metrics, actual)
    ):
        raise ValueError("Missing or stale completion")
    expected_end = (
        config["warmup_minutes"]
        + config["measure_minutes"]
        + config["deadline_minutes"]
    )
    if marker["finished_min"] + 1e-8 < expected_end:
        raise ValueError("Episode stopped before settlement")
    with (folder / "demand.csv").open() as stream:
        requests = [row["request_id"] for row in csv.DictReader(stream)]
    ids = [row["request_id"] for row in outcomes]
    if (
        len(ids) != len(set(ids))
        or set(ids) != set(requests)
        or len(ids) != metrics["all_demand_count"]
        or len(ids) != marker["outcome_count"]
        or len(ids) != metrics["all_outcome_count"]
    ):
        raise ValueError("Missing or duplicate demand outcomes")
    terminal = TERMINAL
    for row in outcomes:
        if row["status"] not in terminal or any(
            isinstance(v, (int, float)) and not math.isfinite(v) for v in row.values()
        ):
            raise ValueError("Invalid outcome")
        if not 0 <= row["delivered_kwh"] <= row["requested_kwh"] + 1e-7:
            raise ValueError("Invalid energy conservation")
    if any(
        isinstance(v, (int, float)) and not math.isfinite(v) for v in metrics.values()
    ):
        raise ValueError("Nonfinite metrics")
    validate_ledger(json.loads((folder / "opportunities.json").read_text()), json.loads((folder / "opportunity_outcomes.json").read_text()), outcomes)
    if abs(rescore_components(metrics["objective_components"])-metrics["objective"])>1e-6:
        raise ValueError("Objective mismatch")
    metrics["wall_seconds"] = time.time() - record["started_at"]
    metrics["exogenous_hash"] = hashlib.sha256(
        "".join(
            digest(folder / name)
            for name in (
                "opportunities.json",
                "traffic_plan.json",
                "initial_fleet.json",
            )
        ).encode()
    ).hexdigest()
    write_json(folder / "metrics.json", metrics)
    record.update(
        status="complete",
        finished_at=time.time(),
        artifact_hashes={
            str(p.relative_to(folder)): digest(p)
            for p in folder.rglob("*")
            if p.is_file() and p.name not in ("manifest.json", "bridge_status.json")
        },
    )
    write_json(folder / "manifest.json", record)
    return record


def build(root: Path = GUI_ROOT) -> dict:
    folders = []
    for seed in SEEDS:
        candidates = sorted(
            (root / "runs").glob(f"collect_{seed}_*"),
            key=lambda p: p.stat().st_mtime_ns,
        )
        if not candidates:
            raise ValueError(f"Missing complete collection for seed {seed}")
        folder = candidates[-1]
        checked_result(folder, {"source": provenance()})
        folders.append(folder)
    configs = [json.loads((p / "manifest.json").read_text())["config"] for p in folders]
    common = [{k: v for k, v in c.items() if k != "seed"} for c in configs]
    if any(c != common[0] for c in common):
        raise ValueError("Calibration configurations differ between seeds")
    # Every build is immutable and separately traceable; historical calibrations stay intact.
    target = root / "builds" / str(time.time_ns()) / "calibration.json"
    result = collect_calibration(folders, target)
    write_json(
        root / "latest.json", {"calibration": str(target), "sha256": digest(target)}
    )
    return {
        "status": "ready",
        "calibration": str(target),
        "snapshots": len(result["prior_snapshots"]),
    }


def validate_candidate(folder: Path):
    record=json.loads((folder/"manifest.json").read_text())
    candidate=json.loads((folder/"candidate.json").read_text())
    if record.get("status")!="running" or record.get("source")!=provenance() or candidate!=record.get("parameters"):
        raise ValueError("Candidate registration/provenance mismatch")
    if record.get("backend")!="GAMA" or candidate.get("schema")!="gama-ranr-v3" or candidate.get("environment_version")!=ENVIRONMENT_VERSION:
        raise ValueError("Invalid GAMA candidate")
    config=RunConfig(**record["config"])
    if candidate.get("method")!=config.method or candidate.get("objective_version")!=config.objective_version:
        raise ValueError("Candidate configuration mismatch")
    return True


def main() -> None:
    operation, path = sys.argv[1:]
    folder = Path(path).resolve()
    try:
        if operation == "prepare":
            prepare(folder)
            message = "COLLECTION REGISTERED: Play to collect the full episode."
        elif operation == "complete":
            complete(folder)
            message = "COLLECTION COMPLETE: valid episode; collect all three seeds, then Validate and build calibration."
        elif operation == "candidate":
            validate_candidate(folder)
            print("CANDIDATE VALID",flush=True)
            return
        elif operation == "model":
            from .headless import load_model

            model = json.loads(folder.read_text())
            config = RunConfig(**model["config"])
            if config.development or config.calibrating:
                raise ValueError("Published models require completed research training")
            load_model(folder, model["method"], config)
            print("MODEL VALID", flush=True)
            return
        elif operation == "build":
            result = build()
            message = "CALIBRATION READY: " + result["calibration"]
        else:
            raise ValueError("Unknown collection operation")
        write_json(folder / "bridge_status.json", {"status": "ok", "message": message})
    except Exception as error:
        message = "CALIBRATION NOT READY: " + str(error)
        if operation != "model":
            write_json(
                folder / "bridge_status.json", {"status": "error", "message": message}
            )
    print(message, flush=True)
