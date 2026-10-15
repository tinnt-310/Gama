"""Isolated GAMA 1.9.3 runs with strict completion and provenance checks."""

from __future__ import annotations
from dataclasses import asdict, dataclass, replace
from pathlib import Path
import hashlib
import json
import math
import os
import shutil
import platform
import importlib.metadata
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from ..paths import ROOT, GAMA_OUTPUTS, digest, write_json

ENVIRONMENT = json.loads((ROOT / "configs/gama/environment.json").read_text())
ENVIRONMENT_VERSION = ENVIRONMENT["environment_version"]
OUTPUT = GAMA_OUTPUTS
METHODS = ("RANR-AW", "No-P2P", "No-Prediction", "Fixed-Weights")
CASES = ("normal", "high", "burst", "low_compliance", "delayed", "combined")


@dataclass(frozen=True)
class RunConfig:
    method: str = "RANR-AW"
    case: str = "normal"
    seed: int = 91001
    warmup_minutes: float = 360
    measure_minutes: float = 360
    deadline_minutes: float = 360
    initial_hour: float = 0
    ev_speed_kmh: float = 30
    car_speed_kmh: float = 50
    step_seconds: float = 1
    samples: int = 32
    background_cars: int = ENVIRONMENT["cars"]
    burst_size: int = 100
    compliance: float = 0.8
    defer_probability: float = 0.05
    render: bool = False
    trace: bool = False
    development: bool = False
    calibrating: bool = False
    consumption_kwh_km: float = ENVIRONMENT["consumption_kwh_km"]
    charge_efficiency: float = ENVIRONMENT["charge_efficiency"]
    environment_version: str = ENVIRONMENT_VERSION
    private_evs: int = ENVIRONMENT["private_evs"]
    electric_taxis: int = ENVIRONMENT["electric_taxis"]
    private_frequency: float = ENVIRONMENT["private_opportunities_per_day"]
    taxi_frequency: float = ENVIRONMENT["taxi_opportunities_per_day"]
    soc_threshold: float = ENVIRONMENT["eligibility_soc"]
    target_soc: float = ENVIRONMENT["target_soc"]
    rush_enabled: bool = True
    rush_extra_percent: float = ENVIRONMENT["rush_extra_percent"]
    calibration: str = ""
    timeout_seconds: float = 21600

    def __post_init__(self):
        if self.method not in METHODS or self.case not in CASES:
            raise ValueError("Unknown GAMA method/scenario")
        if self.environment_version != ENVIRONMENT_VERSION:
            raise ValueError("Environment changed: recalibrate and retrain")
        for name in ("private_frequency", "taxi_frequency"):
            if not math.isfinite(getattr(self, name)) or getattr(self, name) < 0:
                raise ValueError(f"Invalid {name}")
        if (
            not math.isfinite(self.consumption_kwh_km)
            or self.consumption_kwh_km < 0
            or not 0 < self.charge_efficiency <= 1
        ):
            raise ValueError("Invalid physical energy configuration")
        if not 0 < self.soc_threshold <= self.target_soc <= 100:
            raise ValueError("Invalid charging SOC thresholds")
        if (
            not math.isfinite(self.rush_extra_percent)
            or not 0 <= self.rush_extra_percent <= 30
        ):
            raise ValueError("Rush population cap must be between 0 and 30 percent")
        if type(self.rush_enabled) is not bool:
            raise ValueError("rush_enabled must be a boolean")
        for name in (
            "measure_minutes",
            "deadline_minutes",
            "step_seconds",
            "ev_speed_kmh",
            "car_speed_kmh",
            "timeout_seconds",
        ):
            if not math.isfinite(getattr(self, name)) or getattr(self, name) <= 0:
                raise ValueError(f"Invalid {name}")
        if not 0 <= self.compliance <= 1 or not 0 <= self.defer_probability <= 1:
            raise ValueError("Invalid driver probabilities")
        if (
            self.samples < 1
            or self.background_cars < 0
            or self.burst_size < 0
            or self.warmup_minutes < 0
        ):
            raise ValueError("Invalid nonnegative count/duration")
        if not math.isfinite(self.initial_hour) or not 0 <= self.initial_hour < 24:
            raise ValueError("Invalid initial clock hour")
        if not math.isfinite(self.warmup_minutes):
            raise ValueError("Nonfinite warmup")
        for name in (
            "seed",
            "samples",
            "background_cars",
            "private_evs",
            "electric_taxis",
            "burst_size",
        ):
            if type(getattr(self, name)) is not int or getattr(self, name) < 0:
                raise ValueError(f"{name} must be an integer")
        if not self.development and not self.calibration:
            raise ValueError("Official runs require train-only GAMA calibration")

    @property
    def demand_rate(self) -> float:
        return (
            self.private_evs * self.private_frequency
            + self.electric_taxis * self.taxi_frequency
        ) / 1440

    @classmethod
    def load(cls, path: Path) -> RunConfig:
        data = json.loads(path.read_text())
        if not data.get("development", False) and not data.get("calibration"):
            pointer = OUTPUT / "gui_calibration/latest.json"
            canonical = OUTPUT / "calibration/calibration.json"
            if pointer.exists():
                item = json.loads(pointer.read_text())
                candidate = Path(item["calibration"])
                if digest(candidate) != item["sha256"]:
                    raise ValueError("GUI calibration was modified")
                data["calibration"] = str(candidate)
            elif canonical.exists():
                data["calibration"] = str(canonical)
        if data.get("calibration"):
            calibration = json.loads(Path(data["calibration"]).read_text())
            if (
                calibration.get("environment_version") != ENVIRONMENT_VERSION
                or calibration.get("source") != provenance()
            ):
                raise ValueError(
                    "Calibration environment/source changed; recollect calibration"
                )
        return cls(**data)


def provenance() -> dict[str, Any]:
    installation = Path(os.environ.get("GAMA_HOME", "/opt/gama-platform"))
    return {
        "gaml": {
            str(p.relative_to(ROOT)): digest(p)
            for p in sorted((ROOT / "models").rglob("*.gaml"))
        },
        "orchestrator": {
            str(p.relative_to(ROOT)): digest(p)
            for p in sorted((ROOT / "src/ranr").rglob("*.py"))
        },
        "gis": {
            str(p.relative_to(ROOT)): digest(p)
            for p in sorted((ROOT / "includes").iterdir())
            if p.suffix.lower() in (".shp", ".shx", ".dbf", ".prj")
        },
        "configuration_fixtures": {
            str(p.relative_to(ROOT)): digest(p)
            for directory in [ROOT / "configs/gama", ROOT / "tests/fixtures"]
            for p in sorted(directory.rglob("*.json"))
        },
        "launcher": {
            str(p.relative_to(ROOT)): digest(p)
            for p in [
                ROOT / "scripts/gama.py",
                ROOT / "scripts/gui_calibration.py",
                ROOT / "scripts/java/CheckModel.java",
                ROOT / "pyproject.toml",
            ]
        },
        "python_version": platform.python_version(),
        "dependencies": {
            name: importlib.metadata.version(name)
            for name in ["numpy", "scipy", "cma", "matplotlib"]
        },
        "gama_config": digest(installation / "configuration/config.ini"),
        "gama_bundles": {
            p.name: digest(p)
            for p in sorted((installation / "plugins").glob("msi.gama.*_*.jar"))
        },
    }


def parameter_record(
    method: str, parameters: list[float], *, trained: bool = False, **metadata
) -> dict:
    expected = 4 if method == "Fixed-Weights" else 20
    if (
        method not in METHODS
        or len(parameters) != expected
        or not all(math.isfinite(x) for x in parameters)
    ):
        raise ValueError(f"{method} needs {expected} finite GAMA parameters")
    return {
        "schema": "gama-ranr-v2",
        "environment_version": ENVIRONMENT_VERSION,
        "backend": "GAMA",
        "method": method,
        "parameters": parameters,
        "features": ["T", "W_mean", "W_P95", "H", "U"],
        "state_features": ["bias", "load", "burst", "exposure_uncertainty", "age"],
        "training_completed": trained,
        **metadata,
    }


def load_model(path: Path, method: str, config: RunConfig) -> list[float]:
    """Validate a supplied model before forwarding its vector to GAMA."""
    record = json.loads(path.read_text())
    canonical = parameter_record(method, record["parameters"])
    for key in (
        "schema",
        "backend",
        "method",
        "features",
        "state_features",
        "environment_version",
    ):
        if record.get(key) != canonical[key]:
            raise ValueError(f"Invalid model {key}: {path}")
    if not config.development:
        if not record.get("training_completed") or record.get("profile") != "research":
            raise ValueError("Official runs require completed GAMA research training")
        if record.get("source") != provenance():
            raise ValueError("Model provenance does not match current implementation")
        if record.get("calibration_sha256") != digest(Path(config.calibration)):
            raise ValueError("Model calibration does not match run configuration")
        locked = record.get("config", {})
        for key in (
            "step_seconds",
            "ev_speed_kmh",
            "car_speed_kmh",
            "initial_hour",
            "samples",
            "deadline_minutes",
            "background_cars",
            "burst_size",
            "private_evs",
            "electric_taxis",
            "private_frequency",
            "taxi_frequency",
            "consumption_kwh_km",
            "charge_efficiency",
            "soc_threshold",
            "target_soc",
            "rush_enabled",
            "rush_extra_percent",
            "environment_version",
            "compliance",
            "defer_probability",
        ):
            if locked.get(key) != getattr(config, key):
                raise ValueError(f"Model and run configuration differ: {key}")
    return record["parameters"]


def _launch(
    arguments: list[str], log: Path, timeout: float, environment: dict[str, str]
) -> None:
    with log.open("w") as stream:
        process = subprocess.Popen(
            [
                "/usr/bin/time",
                "-f",
                '{"user_seconds":%U,"system_seconds":%S,"max_rss_kib":%M}',
                "-o",
                str(log.with_suffix(".resources.json")),
                sys.executable,
                str(ROOT / "scripts/gama.py"),
                *arguments,
            ],
            cwd=ROOT,
            env=environment,
            stdout=stream,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            code = process.wait(timeout=timeout)
        except (subprocess.TimeoutExpired, BaseException):
            import signal

            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            raise
    if code:
        raise RuntimeError(f"GAMA launcher exited {code}: {log}")


def checked_result(folder: Path, expected: dict) -> dict:
    manifest = json.loads((folder / "manifest.json").read_text())
    if manifest.get("status") != "complete" or any(
        manifest.get(k) != v for k, v in expected.items()
    ):
        raise ValueError(f"Run not complete or registration changed: {folder}")
    if any(
        not (folder / name).is_file() or digest(folder / name) != sha
        for name, sha in manifest["artifact_hashes"].items()
    ):
        raise ValueError(f"Run artifact changed: {folder}")
    return json.loads((folder / "metrics.json").read_text())


def archive_failed_run(folder: Path) -> Path:
    """Preserve a failed episode before an explicitly requested fresh attempt."""
    record = json.loads((folder / "manifest.json").read_text())
    if record.get("status") != "failed":
        raise ValueError(f"Only failed runs can be restarted: {folder}")
    destination = folder.parent / "_incomplete" / f"{folder.name}_{time.time_ns()}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    folder.rename(destination)
    return destination


def last_simulation_minute(folder: Path) -> float | None:
    """Read physical progress, independently of a possibly stale running marker."""
    import csv

    path = folder / "legacy_population.csv"
    if not path.is_file():
        return None
    last = None
    with path.open() as stream:
        for row in csv.DictReader(stream):
            try:
                value = float(row.get("time_min", ""))
            except (ValueError, TypeError):
                continue
            if math.isfinite(value) and value >= 0:
                last = value
    return last


def run(
    config: RunConfig,
    parameters: list[float],
    folder: Path,
    *,
    resume: bool = False,
    wall_limit: float | None = None,
) -> dict:
    folder = folder.resolve()
    record = parameter_record(config.method, parameters)
    config_record = asdict(config)
    if config.calibration:
        config_record["calibration"] = str(Path(config.calibration).resolve())
    inputs = {
        "config": config_record,
        "parameters": record,
        "source": provenance(),
        "calibration_sha256": (
            digest(Path(config.calibration)) if config.calibration else None
        ),
    }
    run_id = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()[
        :20
    ]
    if folder.exists():
        if not resume:
            raise FileExistsError(f"Refusing to overwrite GAMA run: {folder}")
        previous = json.loads((folder / "manifest.json").read_text())
        if previous.get("status") == "complete":
            return checked_result(folder, inputs)
        if any(previous.get(k) != v for k, v in inputs.items()):
            raise ValueError("Incomplete run inputs changed")
        archive = folder.parent / "_incomplete" / f"{folder.name}_{time.time_ns()}"
        archive.parent.mkdir(parents=True, exist_ok=True)
        folder.rename(archive)
    folder.mkdir(parents=True)
    manifest = {
        **inputs,
        "run_id": run_id,
        "backend": "GAMA",
        "status": "running",
        "started_at": time.time(),
    }
    write_json(folder / "manifest.json", manifest)
    write_json(folder / "candidate.json", record)
    if config.calibration:
        shutil.copy2(config.calibration, folder / "calibration.json")
    started = time.perf_counter()
    env = os.environ.copy()
    env.update(OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1")
    try:
        remaining = lambda: (
            max(0.001, wall_limit - (time.perf_counter() - started))
            if wall_limit is not None
            else config.timeout_seconds
        )
        _launch(
            [
                "-xml",
                "Run me",
                str(ROOT / "models/main.gaml"),
                str(folder / "plan.xml"),
            ],
            folder / "xml.log",
            min(120, remaining()),
            env,
        )
        tree = ET.parse(folder / "plan.xml")
        simulations = tree.findall("Simulation")
        if len(simulations) != 1:
            raise ValueError("Expected one Run me simulation")
        sim = simulations[0]
        sim.set("id", run_id)
        sim.set("seed", str(config.seed))
        sim.set("sourcePath", str(ROOT / "models/main.gaml"))
        sim.set(
            "finalStep",
            str(
                math.ceil(
                    (
                        config.warmup_minutes
                        + config.measure_minutes
                        + config.deadline_minutes
                    )
                    * 60
                    / config.step_seconds
                )
                + 3
            ),
        )
        sim.set("until", "ranr_done")
        sim.find("Outputs").clear()
        p = sim.find("Parameters")
        p.clear()
        values = {
            "ranr_gui_preview": False,
            "ranr_method": config.method,
            "ranr_case": config.case,
            "ranr_run_id": run_id,
            "ranr_output": str(folder),
            "ranr_parameter_file": str(folder / "candidate.json"),
            "ranr_calibration_file": (
                str(folder / "calibration.json") if config.calibration else ""
            ),
            "ranr_development": config.development,
            "ranr_trace": config.trace,
            "ranr_render": config.render,
            "ranr_true_compliance": config.compliance,
            "ranr_true_defer": config.defer_probability,
            "ranr_calibrating": config.calibrating,
            "ranr_samples": config.samples,
            "ranr_warmup": config.warmup_minutes,
            "ranr_measure": config.measure_minutes,
            "ranr_deadline": config.deadline_minutes,
            "cars": config.background_cars,
            "privates": config.private_evs,
            "taxis": config.electric_taxis,
            "ranr_private_frequency": config.private_frequency,
            "ranr_taxi_frequency": config.taxi_frequency,
            "ranr_soc_threshold": config.soc_threshold,
            "target_soc": config.target_soc,
            "consumption_kwh_km": config.consumption_kwh_km,
            "charge_efficiency": config.charge_efficiency,
            "have_rush": config.rush_enabled,
            "rush_extra_percent": config.rush_extra_percent,
            "ranr_burst_size": config.burst_size,
            "step": config.step_seconds,
            "initial_hour": config.initial_hour,
            "ranr_ev_speed": config.ev_speed_kmh,
            "ranr_car_speed": config.car_speed_kmh,
        }
        for name, value in values.items():
            kind = (
                "BOOLEAN"
                if isinstance(value, bool)
                else (
                    "INT"
                    if isinstance(value, int)
                    else "FLOAT" if isinstance(value, float) else "STRING"
                )
            )
            ET.SubElement(
                p,
                "Parameter",
                name=name,
                var=name,
                type=kind,
                value=str(value).lower() if isinstance(value, bool) else str(value),
            )
        tree.write(folder / "plan.xml", encoding="utf-8", xml_declaration=True)
        _launch(
            [str(folder / "plan.xml"), str(folder / "headless")],
            folder / "launch.log",
            min(config.timeout_seconds, remaining()),
            env,
        )
        console = (
            "\n".join(
                p.read_text(errors="replace")
                for p in (folder / "headless").glob("console*.txt")
            )
            + "\n"
            + (folder / "launch.log").read_text(errors="replace")
        )
        failures = (
            "Runtime error",
            "Assert failed",
            "Error in",
            "Exception",
            "No parameter named",
            "RANR_ERROR",
        )
        if (
            any(x in console for x in failures)
            or f"RANR_COMPLETE {run_id}" not in console
        ):
            raise RuntimeError(
                f"GAMA simulation failed/incomplete: {folder}; {console[-2500:]}"
            )
        completion = json.loads((folder / "completion.json").read_text())
        metrics = json.loads((folder / "metrics.json").read_text())
        outcomes = json.loads((folder / "outcomes.json").read_text())
        if (
            completion.get("run_id") != run_id
            or completion.get("status") != "complete"
            or metrics.get("run_id") != run_id
        ):
            raise ValueError("Stale or invalid completion")
        if (
            metrics["all_outcome_count"] != metrics["all_demand_count"]
            or len(outcomes) != metrics["all_demand_count"]
        ):
            raise ValueError("Missing demand outcomes")
        import csv

        with (folder / "demand.csv").open() as stream:
            demand_ids = [row["request_id"] for row in csv.DictReader(stream)]
        outcome_ids = [row["request_id"] for row in outcomes]
        if len(set(outcome_ids)) != len(outcome_ids) or set(demand_ids) != set(
            outcome_ids
        ):
            raise ValueError("Duplicate or mismatched demand outcomes")
        terminal = {"completed", "failed", "stranded", "deferred", "unserved"}
        for outcome in outcomes:
            if outcome["status"] not in terminal or not all(
                math.isfinite(value)
                for value in outcome.values()
                if isinstance(value, (float, int))
            ):
                raise ValueError("Invalid terminal demand outcome")
            if not 0 <= outcome["delivered_kwh"] <= outcome["requested_kwh"] + 1e-7:
                raise ValueError("Invalid delivered energy")
        if not all(
            math.isfinite(x) for x in metrics.values() if isinstance(x, (int, float))
        ):
            raise ValueError("Nonfinite GAMA metrics")
        if config.method == "No-P2P" and metrics["messages"] != 0:
            raise ValueError("No-P2P leaked communication")
        if config.method == "No-Prediction" and metrics["future_calls"] != 0:
            raise ValueError("No-Prediction called future predictor")
        if json.loads((folder / "candidate.json").read_text()) != record:
            raise ValueError("Candidate parameters changed during GAMA run")
        if (
            config.calibration
            and digest(folder / "calibration.json") != inputs["calibration_sha256"]
        ):
            raise ValueError("Calibration changed during GAMA run")
        if provenance() != inputs["source"]:
            raise ValueError("Source changed during GAMA run")
        if (
            not config.development
            and not config.calibrating
            and metrics["demand_count"] == 0
        ):
            raise ValueError(
                "No activated charging demand: revise development feasibility before candidate evaluation"
            )
        metrics["wall_seconds"] = time.perf_counter() - started
        resources = [json.loads(p.read_text()) for p in folder.glob("*.resources.json")]
        metrics["cpu_seconds"] = sum(
            x["user_seconds"] + x["system_seconds"] for x in resources
        )
        metrics["max_rss_kib"] = max(x["max_rss_kib"] for x in resources)
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
        manifest.update(status="complete", finished_at=time.time())
        manifest["artifact_hashes"] = {
            str(p.relative_to(folder)): digest(p)
            for p in folder.rglob("*")
            if p.is_file() and p.name != "manifest.json"
        }
        write_json(folder / "manifest.json", manifest)
        return metrics
    except BaseException as error:
        if isinstance(error, subprocess.TimeoutExpired):
            last = last_simulation_minute(folder)
            target = (
                config.warmup_minutes + config.measure_minutes + config.deadline_minutes
            )
            progress = (
                f" Last recorded progress: {last:g}/{target:g} simulated minutes."
                if last is not None
                else " No simulation progress recorded yet."
            )
            manifest["last_simulated_minutes"] = last
            manifest["error_type"] = "timeout"
            message = (
                f"GAMA exceeded {error.timeout:g} seconds of wall time.{progress} "
                f"Partial files are preserved in {folder}. "
                "This episode has no simulation checkpoint; a retry starts from the beginning."
            )
            manifest.update(status="failed", error=message, finished_at=time.time())
            write_json(folder / "manifest.json", manifest)
            raise TimeoutError(message) from error
        manifest.update(status="failed", error=str(error), finished_at=time.time())
        write_json(folder / "manifest.json", manifest)
        raise
