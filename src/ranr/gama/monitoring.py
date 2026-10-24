"""Progress watchdog for a single owned GAMA process group."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import time
import threading

from ..paths import write_json

TRAINING_CANCEL = threading.Event()


def check_training_cancelled():
    if TRAINING_CANCEL.is_set():
        raise InterruptedError('Training termination requested; pending generation retained')


MEMORY_WARNING = (
    "Runtime error: Memory is low (0 megabytes). You should close the experiment, "
    "exit GAMA and give it more memory"
)
ERROR_MARKERS = ("Runtime error", "Assert failed", "Error in", "Exception",
                 "No parameter named", "RANR_ERROR", "OutOfMemoryError",
                 "GC overhead limit exceeded", "A fatal error has been detected")


class ProgressStalled(TimeoutError):
    error_type = "stalled"


def classify_console(console: str) -> tuple[list[str], dict]:
    """Only the installed 1.9.3 background memory timer's exact warning is exempt.

    This never establishes success: the completion marker, physical contracts and
    hashes are still mandatory in headless.run(). Unknown errors remain fatal.
    """
    failures, warnings = [], []
    for line in console.splitlines():
        clean = line.strip()
        if clean == MEMORY_WARNING:
            warnings.append(clean)
        elif any(marker in line for marker in ERROR_MARKERS):
            failures.append(line)
    return failures, {
        "known_background_memory_warning_count": len(warnings),
        "warning": MEMORY_WARNING if warnings else None,
        "classification": "GAMA 1.9.3 PlatformAgent memory timer warning; not model completion",
        "acceptance_requires": "full completion, energy/movement/charging validation and provenance",
    }


def tail(path: Path, limit: int = 32768) -> str:
    if not path.exists():
        return ""
    with path.open("rb") as stream:
        size = stream.seek(0, 2)
        stream.seek(max(0, size - limit))
        return stream.read().decode(errors="replace")


def process_group(pgid: int) -> list[dict]:
    result = subprocess.run(
        ["ps", "-eo", "pid=,ppid=,pgid=,pcpu=,rss=,stat=,etimes=,args="],
        text=True, capture_output=True, timeout=10, check=True,
    )
    rows = []
    for line in result.stdout.splitlines():
        parts = line.split(None, 7)
        if len(parts) == 8 and int(parts[2]) == pgid:
            rows.append(dict(pid=int(parts[0]), ppid=int(parts[1]),
                             cpu_percent=float(parts[3]), rss_kib=int(parts[4]),
                             state=parts[5], elapsed_seconds=int(parts[6]), command=parts[7]))
    return rows


def diagnose(folder: Path, pgid: int, reason: str) -> Path:
    target = folder / "diagnostics" / str(time.time_ns())
    target.mkdir(parents=True)
    processes = process_group(pgid)
    write_json(target / "processes.json", {"reason": reason, "at": time.time(),
                                          "pgid": pgid, "processes": processes})
    (target / "meminfo.txt").write_text(Path("/proc/meminfo").read_text())
    for p in [folder / "launch.log", *(folder / "headless").glob("console*.txt")]:
        (target / p.name).write_text(tail(p))
    installation = Path(os.environ.get("GAMA_HOME", "/opt/gama-platform"))
    for row in processes:
        if row["command"].startswith(str(installation / "jdk/bin/java") + " "):
            try:
                stack = subprocess.run([str(installation / "jdk/bin/jcmd"), str(row["pid"]),
                                        "Thread.print", "-l"],
                                       capture_output=True, text=True, timeout=25)
                (target / f"java_{row['pid']}_threads.txt").write_text(stack.stdout + stack.stderr)
            except (OSError, subprocess.TimeoutExpired) as error:
                (target / "thread_dump_error.txt").write_text(str(error))
    return target


def wait_for_gama(process, log: Path, timeout: float, environment: dict) -> int:
    stall_seconds = float(environment.get("RANR_STALL_SECONDS", "0"))
    if log.name != "launch.log" or stall_seconds <= 0:
        started = time.monotonic()
        while True:
            check_training_cancelled()
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                raise subprocess.TimeoutExpired(process.args, timeout)
            try:
                return process.wait(timeout=min(1.0, remaining))
            except subprocess.TimeoutExpired:
                pass
    from .headless import last_simulation_minute

    startup = float(environment.get("RANR_STARTUP_SECONDS", "900"))
    poll_seconds = float(environment.get("RANR_POLL_SECONDS", "30"))
    if min(startup, poll_seconds, stall_seconds) <= 0:
        raise ValueError("Watchdog durations must be positive")
    folder = log.parent
    started = last_change = time.monotonic()
    last = None
    while True:
        check_training_cancelled()
        now = time.monotonic()
        progress = last_simulation_minute(folder)
        if progress is not None and (last is None or progress > last):
            last, last_change = progress, now
        processes = process_group(process.pid)
        write_json(folder / "heartbeat.json", {
            "updated_at": time.time(), "process_group": process.pid,
            "simulated_minutes": last, "wall_seconds": now - started,
            "seconds_without_progress": now - last_change,
            "rss_kib": sum(p["rss_kib"] for p in processes),
            "processes": processes,
        })
        # Only complete lines are examined while a producer may still be writing.
        live_logs = [log, *(folder / "headless").glob("console*.txt")]
        failures = []
        for path in live_logs:
            contents = tail(path)
            failures.extend(classify_console(contents.rsplit("\n", 1)[0])[0])
        if failures:
            diagnose(folder, process.pid, "runtime error")
            raise RuntimeError("GAMA runtime error: " + "\n".join(failures)[-3000:])
        if now - last_change > (startup if last is None else stall_seconds):
            diagnostic = diagnose(folder, process.pid, "no simulation progress")
            raise ProgressStalled(f"No physical progress for {now-last_change:.0f}s; "
                                  f"last minute {last}; diagnostics: {diagnostic}")
        remaining = timeout - (now - started)
        if remaining <= 0:
            diagnose(folder, process.pid, "wall timeout")
            raise subprocess.TimeoutExpired(process.args, timeout)
        try:
            return process.wait(timeout=min(poll_seconds, remaining))
        except subprocess.TimeoutExpired:
            pass
