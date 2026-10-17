"""Register and validate calibration produced by the interactive GAMA experiment."""

from __future__ import annotations
from .contracts import TERMINAL, validate_charging_files, validate_physical_records, finite_tree, rescore_components, OBJECTIVE_CONFIG_HASH, validate_objective_identity, validate_fitness, validate_configuration
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
    validate_configuration(actual, config)
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
    validate_fitness(metrics)
    validate_charging_files(folder)
    write_json(folder / "physical_validation.json", validate_physical_records(folder, config))
    if abs(rescore_components(metrics["objective_components"])-metrics["operational_objective"])>1e-6:
        raise ValueError("Objective mismatch")
    validate_fitness(metrics)
    metrics.update(case=config["case"], seed=config["seed"])
    metrics["wall_seconds"] = time.time() - record["started_at"]
    metrics["exogenous_hash"] = hashlib.sha256(
        "".join(
            digest(folder / name)
            for name in (
                "activity_plan.json",
                    "vehicle_traits.json",
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


def select_collections(root: Path = GUI_ROOT, runs=None, compatibility=None):
    """Select by registered time, never directory mtime; validate after selection."""
    from .evidence import read_evidence, validate_collection
    source = provenance()
    proof = read_evidence(compatibility) if compatibility else None
    explicit = runs is not None
    candidates = [Path(p).resolve() for p in runs] if explicit else sorted((root / "runs").glob("collect_*"))
    eligible, skipped = {}, []
    for folder in candidates:
        record = json.loads((folder / "manifest.json").read_text())
        seed = record.get("config", {}).get("seed")
        reason = None
        if seed not in SEEDS: reason = "unregistered_seed"
        elif record.get("status") != "complete": reason = "status_" + str(record.get("status"))
        elif record.get("source") != source and (not proof or proof.get("runs", {}).get(str(folder.resolve())) != digest(folder / "manifest.json")):
            reason = "incompatible_source"
        else:
            try:
                RunConfig(**record["config"])
                if not record["config"]["calibrating"] or not record["config"]["trace"]:
                    reason = "not_calibration"
            except (ValueError, TypeError) as error:
                reason = "incompatible_config: " + str(error)
        if reason:
            skipped.append({"run": str(folder), "reason": reason})
            if explicit: raise ValueError(f"Explicit Collect rejected: {folder}: {reason}")
            continue
        if explicit and seed in eligible:
            raise ValueError(f"Duplicate explicit seed {seed}")
        stamp = record.get("finished_at", record.get("started_at"))
        if not isinstance(stamp, (int, float)) or not math.isfinite(stamp):
            raise ValueError(f"Missing/invalid registered Collect time: {folder}")
        eligible.setdefault(seed, []).append((stamp, str(folder.resolve()), folder))
    folders = []
    for seed in SEEDS:
        choices = sorted(eligible.get(seed, []))
        if not choices: raise ValueError(f"Missing complete compatible collection for seed {seed}; skipped={skipped}")
        folders.append(choices[-1][2])
        skipped.extend({"run": str(item[2]), "reason": "older_complete"} for item in choices[:-1])
    configs = [json.loads((p / "manifest.json").read_text())["config"] for p in folders]
    common = [{k:v for k,v in c.items() if k not in ("seed", "render", "timeout_seconds")} for c in configs]
    if any(c != common[0] for c in common):
        raise ValueError("Calibration configurations differ between seeds")
    for folder in folders:
        validate_collection(folder, compatibility)
    return folders, {"selected": [str(p.resolve()) for p in folders], "skipped": skipped}


def build(root: Path = GUI_ROOT, runs=None, compatibility=None) -> dict:
    from .evidence import validate_collection
    folders, selection = select_collections(root, runs, compatibility)
    target = root / "builds" / str(time.time_ns()) / "calibration.json"
    result = collect_calibration(folders, target, compatibility)
    write_json(target.parent / "selection.json", selection)
    # Validate every input again immediately before publishing the atomic pointer.
    for folder in folders: validate_collection(folder, compatibility)
    if (root / "latest.json").exists():
        write_json(target.parent / "previous_pointer.json", json.loads((root / "latest.json").read_text()))
    write_json(root / "latest.json", {"calibration": str(target), "sha256": digest(target)})
    return {"status": "ready", "calibration": str(target), "snapshots": len(result["prior_snapshots"]), **selection}


def validate_candidate(folder: Path):
    record=json.loads((folder/"manifest.json").read_text())
    candidate=json.loads((folder/"candidate.json").read_text())
    if record.get("status")!="running" or record.get("source")!=provenance() or candidate!=record.get("parameters"):
        raise ValueError("Candidate registration/provenance mismatch")
    if record.get("backend")!="GAMA" or candidate.get("schema")!="gama-ranr-v4" or candidate.get("environment_version")!=ENVIRONMENT_VERSION:
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
            if operation == "complete" and (folder/"manifest.json").exists():
                record=json.loads((folder/"manifest.json").read_text())
                record.update(status="failed",fitness_valid=False,fitness_vector=None,failure_reason=str(error))
                write_json(folder/"manifest.json",record)
            write_json(
                folder / "bridge_status.json", {"status": "error", "message": message}
            )
    print(message, flush=True)
