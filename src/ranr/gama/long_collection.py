"""Durable, supervised collection; physical simulation remains entirely in GAMA."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, replace
import fcntl
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
import traceback

from ..paths import ROOT, digest, write_json
from .headless import OUTPUT, RunConfig, checked_result, provenance, run
from .monitoring import tail


SEEDS = (800001, 800002, 800003)
PROFILE = ROOT / "configs/gama/calibration.json"
COLLECTION_ROOT = OUTPUT / "long_collection"
LATEST = COLLECTION_ROOT / "latest.json"
HEAPS = (12288, 16384, 16384)


def collection_lock():
    COLLECTION_ROOT.mkdir(parents=True, exist_ok=True)
    lock = (COLLECTION_ROOT / ".active.lock").open("a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        raise RuntimeError("Another long collection is active; use status/resume instead of starting a duplicate")
    return lock


def validate_days(folder: Path, days: int = 3) -> dict:
    import csv

    with (folder / "daily_statistics.csv").open() as stream:
        counts = Counter((int(row["Day"]), row["Station_Name"]) for row in csv.DictReader(stream))
    stations = {station for _, station in counts}
    if len(stations) != 11 or counts != Counter({(d, s): 1 for d in range(1, days + 1) for s in stations}):
        raise ValueError(f"Incomplete/duplicate station-day statistics: expected {11*days} rows")
    return {"days": days, "station_day_rows": sum(counts.values()), "stations": len(stations)}


def require_source(registration: dict) -> None:
    if registration["source"] != provenance():
        raise ValueError("Source/configuration changed since registration; refusing to mix datasets")


def retryable(error: BaseException, folder: Path) -> bool:
    if isinstance(error, TimeoutError):
        return True
    logs = tail(folder / "launch.log") + "\n" + str(error)
    # Contract failures, unknown runtime errors and assertion failures require a fix.
    return isinstance(error, RuntimeError) and any(
        marker in logs for marker in ("OutOfMemoryError", "GC overhead limit exceeded",
                                     "GAMA launcher exited -9", "GAMA launcher exited 137",
                                     "GAMA launcher exited 143", "GAMA launcher exited -15")
    )


def selected_output(value: Path | None) -> Path:
    if value is not None:
        return value.resolve()
    return Path(json.loads(LATEST.read_text())["output"])


def prepare(output: Path | None = None) -> Path:
    # Check before changing latest.json; a duplicate launch must not hide the
    # active dataset or allocate a second large JVM heap.
    with collection_lock():
        return _prepare(output)


def _prepare(output: Path | None = None) -> Path:
    config = RunConfig.load(PROFILE)
    total = config.warmup_minutes + config.measure_minutes + config.deadline_minutes
    if total != 4320 or config.step_seconds != 60 or not config.calibrating or not config.trace:
        raise ValueError("72-hour calibration must use 4320 minutes, 60s steps and physical traces")
    output = (output or COLLECTION_ROOT / f"three_days_{time.time_ns()}").resolve()
    output.mkdir(parents=True, exist_ok=False)
    unit = f"ranr-three-days-{time.time_ns()}.service"
    registration = {
        "status": "registered", "created_at": time.time(), "output": str(output),
        "service": unit, "source": provenance(), "config": asdict(config),
        "seeds": list(SEEDS), "total_days_per_seed": int(total / 1440),
        "sequential": True, "heap_mib_per_attempt": list(HEAPS),
        "restart_policy": "restart interrupted/stalled/resource-failed seed from minute zero; retain evidence",
        "stall_seconds": 1200, "startup_seconds": 900, "training_started": False,
    }
    write_json(output / "registration.json", registration)
    write_json(output / "state.json", {"status": "registered", "updated_at": time.time()})
    # systemctl link+enable installs this concrete workspace-owned unit. No shell
    # interpolation, nohup processes, or dependency on the assistant's lifetime.
    def quote(value):
        return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'

    unit_text = (
        "[Unit]\nDescription=Supervised 3-day GAMA calibration collection\n"
        "StartLimitIntervalSec=3600\nStartLimitBurst=4\n\n[Service]\nType=simple\n"
        f"WorkingDirectory={str(ROOT).replace('%', '%%')}\n"
        f"ExecStart={quote(ROOT / '.venv/bin/python')} -u -m ranr.gama.long_collection run --output {quote(output)}\n"
        "Restart=on-failure\nRestartSec=30\nRestartPreventExitStatus=2\n"
        "KillMode=control-group\nTimeoutStopSec=45\nOOMPolicy=stop\n"
        "Environment=OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONUNBUFFERED=1\n"
        f"StandardOutput=append:{output / 'supervisor.log'}\nStandardError=inherit\n"
        "\n[Install]\nWantedBy=default.target\n"
    )
    (output / unit).write_text(unit_text)
    write_json(LATEST, {"output": str(output), "service": unit})
    return output


def preflight(output: Path, registration: dict) -> None:
    folder = output / "preflight"
    folder.mkdir(exist_ok=True)
    marker = folder / "passed.json"
    if marker.exists():
        if json.loads(marker.read_text())["source"] != registration["source"]:
            raise ValueError("Preflight source mismatch")
        return
    if shutil.disk_usage(output).free < 40 * 1024**3:
        raise ValueError("Need at least 40 GiB free for collection and failed-attempt evidence")
    mem = {line.split(":")[0]: int(line.split()[1]) for line in Path("/proc/meminfo").read_text().splitlines()}
    if mem["MemAvailable"] < (HEAPS[0] + 2048) * 1024:
        raise RuntimeError("Insufficient available RAM for the registered 12 GiB GAMA heap")
    for name, command, limit in (
        ("python_tests", [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], 900),
        ("native_validation", [sys.executable, "-m", "ranr", "validate", "--compile"], 3600),
    ):
        print(f"PREFLIGHT {name}", flush=True)
        write_json(output / "state.json", {"status": "preflight", "check": name, "updated_at": time.time()})
        with (folder / f"{name}.log").open("a") as stream:
            subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                           timeout=limit, check=True)
        require_source(registration)
    # Actual registered calendar, one-minute physical episode, small fleet. This
    # checks calendar rollover, final day, SOC persistence and GAMA end conditions.
    print("PREFLIGHT 3-day physical calendar (6 vehicles)", flush=True)
    write_json(output / "state.json", {"status": "preflight", "check": "3_day_physical_calendar", "updated_at": time.time()})
    config = replace(RunConfig(**registration["config"]), seed=SEEDS[0],
                     background_cars=2, private_evs=2, electric_taxis=2,
                     rush_enabled=False, samples=1, timeout_seconds=7200)
    calendar = folder / "calendar_3days"
    if calendar.exists() and not (calendar / "manifest.json").exists():
        calendar.rename(folder / f"calendar_unregistered_interrupted_{time.time_ns()}")
    run(config, [0.0] * 20, calendar, resume=calendar.exists())
    days = validate_days(calendar)
    require_source(registration)
    write_json(marker, {"passed": True, "at": time.time(), "source": registration["source"],
                        "calendar": days, "production_step_seconds": 60})


def execute(output: Path) -> None:
    registration = json.loads((output / "registration.json").read_text())
    require_source(registration)
    os.environ.update(RANR_JAVA_HEAP_MIB=str(HEAPS[0]), RANR_STALL_SECONDS="1200",
                      RANR_STARTUP_SECONDS="900", RANR_POLL_SECONDS="30")
    # JVM option injection can silently override -Xmx; use the registered heap.
    for name in ("_JAVA_OPTIONS", "JAVA_TOOL_OPTIONS", "JDK_JAVA_OPTIONS"):
        os.environ.pop(name, None)
    preflight(output, registration)
    completed = []
    for seed in registration["seeds"]:
        config = replace(RunConfig(**registration["config"]), seed=seed)
        folder = output / "runs" / str(seed)
        folder.mkdir(parents=True, exist_ok=True)
        accepted = None
        for attempt, heap in enumerate(HEAPS, 1):
            target = folder / f"attempt_{attempt}"
            require_source(registration)
            if target.exists() and not (target / "manifest.json").exists():
                # mkdir and the first atomic manifest write are separate system
                # calls; an OS kill between them must also be recoverable.
                write_json(target / "manifest.json", {"status": "failed", "error_type": "interrupted",
                           "error": "Interrupted before atomic run registration", "finished_at": time.time()})
            if (target / "manifest.json").exists():
                previous = json.loads((target / "manifest.json").read_text())
                if previous.get("status") == "complete":
                    checked_result(target, {"source": registration["source"], "config": asdict(config)})
                    validate_days(target)
                    accepted = target
                    break
                if previous.get("status") == "running":
                    # A service restart always kills its old cgroup first. Preserve
                    # the unfinished seed and consume an attempt, never splice it.
                    previous.update(status="failed", error_type="interrupted", finished_at=time.time(),
                                    error="Supervisor/service interrupted before physical completion")
                    write_json(target / "manifest.json", previous)
                elif previous.get("error_type") not in {"timeout", "stalled", "interrupted", "resource"}:
                    raise ValueError(f"Previous attempt needs a code/data fix: {target}")
                continue
            os.environ["RANR_JAVA_HEAP_MIB"] = str(heap)
            print(f"COLLECT seed={seed} attempt={attempt} heap={heap}MiB total=4320min folder={target}", flush=True)
            write_json(output / "state.json", {"status": "collecting", "seed": seed,
                       "attempt": attempt, "heap_mib": heap, "run": str(target),
                       "completed_runs": [str(p) for p in completed], "updated_at": time.time()})
            try:
                run(config, [0.0] * 20, target)
                validate_days(target)
                accepted = target
                break
            except Exception as error:
                recoverable = retryable(error, target)
                write_json(target / "supervisor_failure.json", {
                    "at": time.time(), "error": str(error), "traceback": traceback.format_exc(),
                    "retryable": recoverable, "attempt": attempt,
                })
                if not recoverable:
                    raise
                manifest = json.loads((target / "manifest.json").read_text())
                if manifest.get("error_type") not in {"timeout", "stalled"}:
                    manifest["error_type"] = "resource"
                    write_json(target / "manifest.json", manifest)
                print(f"RETRYABLE FAILURE seed={seed} attempt={attempt}: {error}", flush=True)
        if accepted is None:
            raise RuntimeError(f"Exhausted {len(HEAPS)} attempts for seed {seed}; evidence retained")
        completed.append(accepted)
        print(f"ACCEPTED seed={seed} {accepted}", flush=True)
    require_source(registration)
    write_json(output / "state.json", {"status": "building_calibration", "updated_at": time.time(),
                                       "completed_runs": [str(p) for p in completed]})
    from .pipeline import collect_calibration
    target = output / "calibration.json"
    result = collect_calibration(completed, target)
    # Recheck immediately before publication, including every sealed artifact.
    require_source(registration)
    for folder in completed:
        checked_result(folder, {"source": registration["source"]})
        validate_days(folder)
    pointer = OUTPUT / "gui_calibration/latest.json"
    if pointer.exists() and not (output / "previous_calibration_pointer.json").exists():
        shutil.copy2(pointer, output / "previous_calibration_pointer.json")
    write_json(pointer, {"calibration": str(target), "sha256": digest(target)})
    write_json(output / "state.json", {"status": "complete", "training_data_ready": True,
               "training_started": False, "updated_at": time.time(), "calibration": str(target),
               "prior_snapshots": len(result["prior_snapshots"]), "seeds": list(SEEDS),
               "total_days_per_seed": registration["total_days_per_seed"], "completed_runs": [str(p) for p in completed]})
    print(f"CALIBRATION READY {target}", flush=True)


def status(output: Path) -> dict:
    registration = json.loads((output / "registration.json").read_text())
    state = json.loads((output / "state.json").read_text())
    result = {"output": str(output), "service": registration["service"], **state}
    if state.get("run"):
        heartbeat = Path(state["run"]) / "heartbeat.json"
        if heartbeat.exists():
            progress = json.loads(heartbeat.read_text())
            minute = progress.get("simulated_minutes")
            total = sum(registration["config"][key] for key in ("warmup_minutes", "measure_minutes", "deadline_minutes"))
            result["progress"] = {"simulated_minutes": minute, "total_minutes": total,
                                   "percent": 100 * minute / total if minute is not None else None,
                                   "heartbeat_age_seconds": time.time() - progress["updated_at"],
                                   "seconds_without_progress": progress["seconds_without_progress"],
                                   "rss_mib": progress["rss_kib"] / 1024}
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "start", "run", "status", "stop", "resume"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.command in {"prepare", "start"}:
        output = prepare(args.output)
        registration = json.loads((output / "registration.json").read_text())
        unit = output / registration["service"]
        subprocess.run(["systemd-analyze", "--user", "verify", str(unit)], check=True)
        print(output, flush=True)
        if args.command == "start":
            subprocess.run(["systemctl", "--user", "link", str(unit)], check=True)
            subprocess.run(["systemctl", "--user", "enable", "--now", registration["service"]], check=True)
        return
    output = selected_output(args.output)
    if args.command == "status":
        result = status(output)
        service = subprocess.run(["systemctl", "--user", "is-active", result["service"]],
                                 capture_output=True, text=True)
        result["service_state"] = service.stdout.strip() or service.stderr.strip()
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.command in {"stop", "resume"}:
        unit = json.loads((output / "registration.json").read_text())["service"]
        if args.command == "resume":
            subprocess.run(["systemctl", "--user", "reset-failed", unit], check=True)
        subprocess.run(["systemctl", "--user", "stop" if args.command == "stop" else "start", unit], check=True)
    else:
        def interrupted(signum, frame):
            raise KeyboardInterrupt(f"Service interrupted by signal {signum}")

        signal.signal(signal.SIGTERM, interrupted)
        try:
            lock = collection_lock()
        except RuntimeError as error:
            print(error, file=sys.stderr)
            raise SystemExit(2)
        with lock:
            try:
                execute(output)
            except KeyboardInterrupt as error:
                write_json(output / "state.json", {"status": "interrupted", "error": str(error), "updated_at": time.time()})
                raise SystemExit(1)
            except Exception as error:
                write_json(output / "state.json", {"status": "needs_attention", "error": str(error),
                           "traceback": traceback.format_exc(), "updated_at": time.time(), "training_data_ready": False})
                traceback.print_exc()
                # Deterministic or contract errors must not loop forever.
                raise SystemExit(2)


if __name__ == "__main__":
    main()
