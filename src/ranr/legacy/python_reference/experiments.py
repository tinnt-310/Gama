"""Reproducible rollout jobs, raw records and atomic manifests."""

from __future__ import annotations
from dataclasses import asdict, replace
import importlib.metadata
import json
from pathlib import Path
import pickle
import platform
import fcntl
import time
from .calibration import from_dict, Calibration
from .config import Config
from .geography import Geography, prepare
from .paths import ROOT, OUTPUTS, digest, source_manifest, write_json
from .simulation import Simulation

_GEOGRAPHY: Geography | None = None
_CALIBRATION: Calibration | None = None


def initialize_worker() -> None:
    global _GEOGRAPHY, _CALIBRATION
    from .geography import load_geography

    _GEOGRAPHY = load_geography()
    if not _GEOGRAPHY.validation["passed"]:
        raise ValueError("Invalid GIS")
    _CALIBRATION = from_dict(
        json.loads((OUTPUTS / "data/calibration.json").read_text())
    )


def resources() -> tuple[Geography, Calibration]:
    if _GEOGRAPHY is None:
        initialize_worker()
    return _GEOGRAPHY, _CALIBRATION


def manifest(config: Config, parameters: list | None = None) -> dict:
    return {
        "schema_version": 1,
        "config": config.to_dict(),
        "parameters": parameters,
        "source": source_manifest(),
        "data": {
            str(p.relative_to(ROOT)): digest(p)
            for stem in ("line", "Middle", "final", "Part1", "Part2", "temporary_cs")
            for p in (ROOT / "includes").glob(stem + ".*")
        },
        "calibration_sha256": digest(OUTPUTS / "data/calibration.json"),
        "python": platform.python_version(),
        "dependencies": {
            p: importlib.metadata.version(p)
            for p in ("numpy", "scipy", "cma", "pyshp", "pyproj", "matplotlib")
        },
        "information_model": "station-local, no hidden truth or future events",
        "status": "running",
    }


def rollout_job(job: tuple[dict, list, str | None]) -> dict:
    values, parameters, destination = job
    if not destination:
        return _rollout_job(job)
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_name(path.name + ".lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError(f"Run already active: {path}") from error
        if (path / "manifest.json").exists():
            old = json.loads((path / "manifest.json").read_text())
            same = (
                old.get("config") == json.loads(json.dumps(values))
                and old.get("parameters") == parameters
                and old.get("source") == source_manifest()
            )
            if same and old.get("status") in ("running", "failed"):
                archive = path.parent / "_incomplete" / f"{path.name}_{time.time_ns()}"
                archive.parent.mkdir(parents=True, exist_ok=True)
                path.rename(archive)
        return _rollout_job(job)


def _rollout_job(job: tuple[dict, list, str | None]) -> dict:
    values, parameters, destination = job
    config = Config(**{**values, "feature_scales": tuple(values["feature_scales"])})
    geo, cal = resources()
    if destination:
        path = Path(destination)
        if path.exists():
            old = (
                json.loads((path / "manifest.json").read_text())
                if (path / "manifest.json").exists()
                else {}
            )
            if (
                old.get("status") == "complete"
                and old.get("config") == json.loads(json.dumps(config.to_dict()))
                and old.get("parameters") == parameters
                and old.get("source") == source_manifest()
            ):
                if any(
                    not (path / name).exists() or digest(path / name) != sha
                    for name, sha in old["artifact_hashes"].items()
                ):
                    raise ValueError("Cached run artifacts changed")
                return json.loads((path / "metrics.json").read_text())
            raise ValueError(
                f"Refusing to overwrite a different/incomplete run: {path}"
            )
        path.mkdir(parents=True)
        metadata = manifest(config, parameters)
        write_json(path / "manifest.json", metadata)
    simulation = Simulation(
        geo, cal, config, parameters, Path(destination) if destination else None
    )
    try:
        result = simulation.run()
    except Exception as error:
        if destination:
            metadata.update(status="failed", error=str(error))
            write_json(path / "manifest.json", metadata)
        raise
    finally:
        simulation.close_logs()
    if destination:
        if source_manifest() != metadata["source"]:
            raise ValueError("Source changed during rollout; run is not complete")
        write_json(path / "metrics.json", result)
        write_json(
            path / "outcomes.json", [asdict(x) for x in simulation.outcomes.values()]
        )
        metadata.update(status="complete", exogenous_hash=result["exogenous_hash"])
        metadata["artifact_hashes"] = {
            p.name: digest(p)
            for p in path.iterdir()
            if p.is_file() and p.name != "manifest.json"
        }
        write_json(path / "manifest.json", metadata)
    return result
