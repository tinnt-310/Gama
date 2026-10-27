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
from .contracts import TERMINAL, OBJECTIVE_VERSION, OBSERVATION_VERSION, validate_charging_files, validate_physical_records, finite_tree, rescore_components, OBJECTIVE_CONFIG_HASH, validate_objective_identity, validate_fitness, validate_configuration, validate_behavior_config

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
    measure_minutes: float = 3600
    deadline_minutes: float = 360
    initial_hour: float = 0
    ev_speed_kmh: float = 30
    car_speed_kmh: float = 50
    step_seconds: float = 60
    samples: int = 32
    background_cars: int = ENVIRONMENT["cars"]
    compliance: float = 0.8
    defer_probability: float = 0.05
    decline_probability: float = 0.0
    abandon_after_minutes: float = -1.0
    render: bool = False
    trace: bool = False
    development: bool = False
    calibrating: bool = False
    consumption_kwh_km: float = ENVIRONMENT["consumption_kwh_km"]
    charge_efficiency: float = ENVIRONMENT["charge_efficiency"]
    environment_version: str = ENVIRONMENT_VERSION
    private_evs: int = ENVIRONMENT["private_evs"]
    electric_taxis: int = ENVIRONMENT["electric_taxis"]
    rush_enabled: bool = True
    rush_extra_percent: float = ENVIRONMENT["rush_extra_percent"]
    objective_version: str = OBJECTIVE_VERSION
    observation_version: str = OBSERVATION_VERSION
    temperature: float = ENVIRONMENT["temperature"]
    p2p_interval: float = ENVIRONMENT["broadcast_minutes"]
    min_send_seconds: float = ENVIRONMENT["min_send_seconds"]
    delay_minutes: float = 0.5
    packet_loss: float = 0.0
    duplicate_probability: float = 0.0
    partition_begin: float = -1.0
    partition_end: float = -1.0
    behavior_case: str = "moderate"
    stabilization: str = "off"
    objective_config_hash: str = OBJECTIVE_CONFIG_HASH
    station_events: str = ""
    calibration: str = ""
    calibration_import_certificate: str = ""
    timeout_seconds: float = 21600

    def __post_init__(self):
        if self.calibration_import_certificate and not self.calibration:
            raise ValueError('A calibration import certificate requires its original calibration')
        if self.objective_config_hash != OBJECTIVE_CONFIG_HASH or ENVIRONMENT["objective_config_hash"] != OBJECTIVE_CONFIG_HASH:
            raise ValueError("Objective configuration hash mismatch")
        if self.objective_version != OBJECTIVE_VERSION or self.observation_version != OBSERVATION_VERSION:
            raise ValueError("Objective/observation schema changed")
        if self.stabilization not in {"off", "smoothing", "smoothing_hysteresis"} or self.behavior_case not in {"high", "moderate", "low", "contextual", "misspecified"}:
            raise ValueError("Unknown design configuration")
        for field in ("temperature", "p2p_interval", "min_send_seconds"):
            if not math.isfinite(getattr(self, field)) or getattr(self, field) <= 0:
                raise ValueError(f"Invalid {field}")
        if not 0 <= self.packet_loss <= 1 or not 0 <= self.duplicate_probability <= 1 or not math.isfinite(self.delay_minutes) or self.delay_minutes < 0:
            raise ValueError("Invalid communication configuration")
        if not math.isfinite(self.partition_begin) or not math.isfinite(self.partition_end) or (self.partition_begin >= 0 and self.partition_end <= self.partition_begin):
            raise ValueError("Invalid partition interval")
        if self.station_events:
            events=json.loads(Path(self.station_events).read_text())
            if not isinstance(events,list):raise ValueError("Station events must be a list")
            previous_event_at = -1.0
            for event in events:
                if (not finite_tree(event) or not isinstance(event.get("operational"),bool)
                    or type(event.get("sid")) is not int or not 0<=event["sid"]<11
                    or event.get("at",-1)<0 or not 0<=event.get("factor",-1)<=1
                    or any(type(x)is not int or x<0 for x in event.get("failed_ports",[]))):
                    raise ValueError("Invalid station event")
                # File order is the deterministic tie-break for equal timestamps.
                # Do not silently rewrite the registered input file or its hash.
                if event['at'] < previous_event_at:
                    raise ValueError('Station events must be ordered by time; equal timestamps retain file order')
                previous_event_at = event['at']
        if self.method not in METHODS or self.case not in CASES:
            raise ValueError("Unknown GAMA method/scenario")
        if self.environment_version != ENVIRONMENT_VERSION:
            raise ValueError("Environment changed: recalibrate and retrain")
        validate_behavior_config(ENVIRONMENT)
        if (
            not math.isfinite(self.consumption_kwh_km)
            or self.consumption_kwh_km < 0
            or not 0 < self.charge_efficiency <= 1
        ):
            raise ValueError("Invalid physical energy configuration")
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
        if not math.isfinite(self.abandon_after_minutes) or not 0<=self.decline_probability<=1 or self.decline_probability+self.defer_probability>1 or not 0 <= self.compliance <= 1 or not 0 <= self.defer_probability <= 1:
            raise ValueError("Invalid driver probabilities")
        if (
            self.samples < 1
            or self.background_cars < 0
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
        ):
            if type(getattr(self, name)) is not int or getattr(self, name) < 0:
                raise ValueError(f"{name} must be an integer")
        if not self.development and (self.warmup_minutes,self.measure_minutes,self.deadline_minutes,self.step_seconds)!=(360,3600,360,60):
            raise ValueError("Official protocol requires 6h/60h/6h and 60-second steps")
        if not self.development and not self.calibration:
            raise ValueError("Official runs require train-only GAMA calibration")

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
        config = cls(**data)
        validate_calibration_binding(config)
        return config


def validate_calibration_binding(config):
    """Keep historical calibration bytes/source; require an explicit scoped import."""
    if not config.calibration:
        return
    calibration = json.loads(Path(config.calibration).read_text())
    validate_objective_identity(calibration)
    if calibration.get('environment_version') != ENVIRONMENT_VERSION:
        raise ValueError('Calibration environment changed')
    if config.calibration_import_certificate:
        from .calibration_import import verify_calibration_import
        verify_calibration_import(Path(config.calibration_import_certificate), Path(config.calibration))
    elif calibration.get('source') != provenance():
        raise ValueError('Calibration source changed; verified scoped import certificate required')


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
                ROOT / "tests/gama_queue_pressure.gaml",
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
        "schema": "gama-ranr-v4",
        "environment_version": ENVIRONMENT_VERSION,
        "backend": "GAMA",
        "method": method,
        "parameters": parameters,
        "objective_version": OBJECTIVE_VERSION,
        "objective_config_hash": OBJECTIVE_CONFIG_HASH,
        "observation_version": OBSERVATION_VERSION,
        "features": ["T_travel_charge", "W_mean", "W_P95", "H", "U"],
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
        "objective_version",
        "observation_version",
        "environment_version",
        "objective_config_hash",
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
            "private_evs",
            "electric_taxis",
            "consumption_kwh_km",
            "charge_efficiency",
            "rush_enabled",
            "rush_extra_percent",
            "environment_version",
            "compliance",
            "defer_probability",
            "decline_probability", "abandon_after_minutes", "temperature", "p2p_interval", "min_send_seconds", "stabilization", "behavior_case", "objective_version", "observation_version",
        ):
            if locked.get(key) != getattr(config, key):
                raise ValueError(f"Model and run configuration differ: {key}")
    return record["parameters"]


def _launch(
    arguments: list[str], log: Path, timeout: float, environment: dict[str, str]
) -> None:
    from .monitoring import check_training_cancelled
    check_training_cancelled()
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
            from .training_time import owner_token
            ownership = log.parent / 'owned_processes.json'
            owners = json.loads(ownership.read_text()) if ownership.exists() else []
            owners.append(owner_token(process.pid))
            write_json(ownership, owners)
            from .monitoring import wait_for_gama

            code = wait_for_gama(process, log, timeout, environment)
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
    if manifest.get('kind') == 'scoped_native_result_review':
        from .recovery_transition import checked_adopted_result
        return checked_adopted_result(folder, expected, manifest)
    if manifest.get("status") != "complete" or any(
        manifest.get(k) != v for k, v in expected.items()
    ):
        raise ValueError(f"Run not complete or registration changed: {folder}")
    if any(
        not (folder / name).is_file() or digest(folder / name) != sha
        for name, sha in manifest["artifact_hashes"].items()
    ):
        raise ValueError(f"Run artifact changed: {folder}")
    metrics = json.loads((folder / "metrics.json").read_text())
    validate_fitness(metrics)
    return metrics


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
    path = folder / "population_population.csv"
    if not path.is_file():
        return None
    with path.open("rb") as stream:
        size = stream.seek(0, 2)
        stream.seek(max(0, size - 65536))
        rows = stream.read().split(b"\n")
    # Ignore both a truncated first line and an unfinished final write.
    if size > 65536:
        rows = rows[1:]
    for row in reversed(rows[:-1]):
        try:
            value = float(row.split(b",", 1)[0])
        except ValueError:
            continue
        if math.isfinite(value) and value >= 0:
            return value
    return None


def run(
    config: RunConfig,
    parameters: list[float],
    folder: Path,
    *,
    resume: bool = False,
    wall_limit: float | None = None,
) -> dict:
    started = time.perf_counter()
    from .execution import assert_checkout_modules
    actual_python = assert_checkout_modules()
    validate_calibration_binding(config)
    if wall_limit is not None and time.perf_counter()-started >= wall_limit:
        raise TimeoutError('Native allowance expired during execution/calibration preflight')
    folder = folder.resolve()
    record = parameter_record(config.method, parameters)
    config_record = asdict(config)
    if config.calibration:
        config_record["calibration"] = str(Path(config.calibration).resolve())
    inputs = {
        "config": config_record,
        "parameters": record,
        "source": provenance(),
        "calibration_import_sha256": (digest(Path(config.calibration_import_certificate))
            if config.calibration_import_certificate else None),
        "station_events_sha256": digest(Path(config.station_events)) if config.station_events else None,
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
        ownership = folder / 'owned_processes.json'
        if ownership.exists():
            from .training_time import still_alive, owner_token
            from .monitoring import process_group
            for owner in json.loads(ownership.read_text()):
                if still_alive(owner):
                    raise ValueError('Incomplete run still has a live owned process; refusing duplicate work')
                try:
                    reused = owner_token(owner['pid']) != owner
                except OSError:
                    reused = False
                if not reused and process_group(owner['pid']):
                    raise ValueError('Incomplete run has surviving process-group members; stop/reconcile before resume')
        archive = folder.parent / "_incomplete" / f"{folder.name}_{time.time_ns()}"
        archive.parent.mkdir(parents=True, exist_ok=True)
        folder.rename(archive)
    folder.mkdir(parents=True)
    manifest = {
        **inputs,
        "python_execution": actual_python,
        "run_id": run_id,
        "backend": "GAMA",
        "status": "running",
        "started_at": time.time(),
    }
    write_json(folder / "manifest.json", manifest)
    write_json(folder / "candidate.json", record)
    if config.calibration:
        shutil.copy2(config.calibration, folder / "calibration.json")
    if config.station_events:
        shutil.copy2(config.station_events,folder/"station_events.json")
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
            "ranr_temperature": config.temperature,
            "ranr_broadcast_period": config.p2p_interval,
            "ranr_min_send": config.min_send_seconds/60.0,
            "ranr_delay": config.delay_minutes,
            "ranr_loss": config.packet_loss,
            "ranr_duplicate_probability": config.duplicate_probability,
            "ranr_partition_begin": config.partition_begin,
            "ranr_partition_end": config.partition_end,
            "ranr_behavior_case": config.behavior_case,
            "ranr_stabilization": config.stabilization,
            "ranr_objective_config_hash": config.objective_config_hash,
            "ranr_station_events_file": str(folder/"station_events.json") if config.station_events else "",
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
            "ranr_true_decline": config.decline_probability,
            "ranr_abandon_after": config.abandon_after_minutes,
            "ranr_calibrating": config.calibrating,
            "ranr_samples": config.samples,
            "ranr_warmup": config.warmup_minutes,
            "ranr_measure": config.measure_minutes,
            "ranr_deadline": config.deadline_minutes,
            "cars": config.background_cars,
            "privates": config.private_evs,
            "taxis": config.electric_taxis,
            "consumption_kwh_km": config.consumption_kwh_km,
            "charge_efficiency": config.charge_efficiency,
            "have_rush": config.rush_enabled,
            "rush_extra_percent": config.rush_extra_percent,
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
        from .monitoring import classify_console
        failures, warnings = classify_console(console)
        write_json(folder / "runtime_warnings.json", warnings)
        if (
            failures
            or f"RANR_COMPLETE {run_id}" not in console
        ):
            raise RuntimeError(
                f"GAMA simulation failed/incomplete: {folder}; {console[-2500:]}"
            )
        completion = json.loads((folder / "completion.json").read_text())
        validate_configuration(json.loads((folder/"configuration.json").read_text()),asdict(config))
        metrics = json.loads((folder / "metrics.json").read_text())
        outcomes = json.loads((folder / "outcomes.json").read_text())
        if (
            completion.get("run_id") != run_id
            or completion.get("status") != "complete"
            or metrics.get("run_id") != run_id
            or completion.get("finished_min", -1) + 1e-8
            < config.warmup_minutes + config.measure_minutes + config.deadline_minutes
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
        terminal = TERMINAL
        for outcome in outcomes:
            if outcome["status"] not in terminal or not all(
                math.isfinite(value)
                for value in outcome.values()
                if isinstance(value, (float, int))
            ):
                raise ValueError("Invalid terminal demand outcome")
            if not 0 <= outcome["delivered_kwh"] <= outcome["requested_kwh"] + 1e-7:
                raise ValueError("Invalid delivered energy")
        if not finite_tree(metrics):
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
        if config.station_events and digest(Path(config.station_events))!=inputs["station_events_sha256"]:
            raise ValueError("Station event scenario changed during execution")
        if provenance() != inputs["source"]:
            raise ValueError("Source changed during GAMA run")
        validate_fitness(metrics)
        validate_charging_files(folder)
        write_json(folder / "physical_validation.json", validate_physical_records(folder, asdict(config)))
        if abs(rescore_components(metrics["objective_components"]) - metrics["operational_objective"]) > 1e-6:
            raise ValueError("Objective decomposition mismatch")
        validate_fitness(metrics)
        metrics.update(case=config.case, seed=config.seed)
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
                    "activity_plan.json",
                    "vehicle_traits.json",
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
        manifest.update(fitness_valid=False,fitness_vector=None,failure_reason=str(error))
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
        manifest.update(status="failed", error=str(error),
                        error_type=("interrupted" if isinstance(error, (KeyboardInterrupt, SystemExit))
                                    else getattr(error, "error_type", type(error).__name__)),
                        last_simulated_minutes=last_simulation_minute(folder),
                        finished_at=time.time())
        write_json(folder / "manifest.json", manifest)
        raise
