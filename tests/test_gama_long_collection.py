"""Long-run failure tests; no synthetic fixture is published as physical data."""

from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from ranr.paths import ROOT, digest
from ranr.gama.headless import RunConfig, last_simulation_minute
from ranr.gama.long_collection import retryable, validate_days, require_source, execute, collection_lock
from ranr.gama.monitoring import MEMORY_WARNING, ProgressStalled, classify_console, wait_for_gama


class LongCollection(unittest.TestCase):
    def test_profile_is_72_hours_with_original_physics(self):
        original = RunConfig.load(ROOT / "configs/gama/calibration.json")
        long = RunConfig.load(ROOT / "configs/gama/calibration.json")
        self.assertEqual(long.warmup_minutes + long.measure_minutes + long.deadline_minutes, 4320)
        self.assertEqual(long.step_seconds, 60)
        for key, value in asdict(original).items():
            if key not in {"seed", "measure_minutes", "timeout_seconds"}:
                self.assertEqual(getattr(long, key), value, key)

    def test_exact_background_warning_does_not_hide_errors(self):
        errors, report = classify_console(MEMORY_WARNING + "\n")
        self.assertFalse(errors)
        self.assertEqual(report["known_background_memory_warning_count"], 1)
        for error in ("Runtime error: unknown", "java.lang.OutOfMemoryError: Java heap space",
                      "Assert failed: SOC", MEMORY_WARNING + " corrupted",
                      "java.lang.IllegalArgumentException"):
            with self.subTest(error=error):
                errors, _ = classify_console(MEMORY_WARNING + "\n" + error)
                self.assertEqual(errors, [error])

    def test_stream_hash_and_progress_ignore_unfinished_numeric_row(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            data = b"scientific evidence\n" * 100000
            path = folder / "trace.csv"
            path.write_bytes(data)
            self.assertEqual(digest(path), hashlib.sha256(data).hexdigest())
            (folder / "population_population.csv").write_bytes(
                b"time_min,total\n" + b"1,4700\n" * 20000 + b"40319,4700\n4032")
            self.assertEqual(last_simulation_minute(folder), 40319)

    def test_daily_export_requires_every_station_on_day_3_once(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            rows = ["Day,Station_Name\n"] + [f"{day},cs_{sid}\n" for day in range(1,4) for sid in range(11)]
            path = folder / "daily_statistics.csv"
            path.write_text("".join(rows))
            self.assertEqual(validate_days(folder)["station_day_rows"], 33)
            for bad in (rows[:-1], rows + [rows[-1]]):
                path.write_text("".join(bad))
                with self.assertRaises(ValueError):
                    validate_days(folder)

    def test_only_recoverable_failures_are_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            self.assertTrue(retryable(ProgressStalled("stalled"), folder))
            self.assertTrue(retryable(TimeoutError("limit"), folder))
            self.assertFalse(retryable(ValueError("SOC invalid"), folder))
            self.assertFalse(retryable(RuntimeError("Runtime error: physics failed"), folder))
            self.assertTrue(retryable(RuntimeError("OutOfMemoryError"), folder))

    def test_source_change_blocks_collection(self):
        with patch("ranr.gama.long_collection.provenance", return_value={"source": "changed"}):
            with self.assertRaisesRegex(ValueError, "refusing to mix"):
                require_source({"source": {"source": "registered"}})

    def test_restart_keeps_completed_seed_and_restarts_interrupted_seed_from_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            config = RunConfig(development=True, calibrating=True, trace=True)
            registration = {"source": {"fixture": "unit"}, "config": asdict(config),
                            "seeds": [800001, 800002]}
            (folder / "registration.json").write_text(json.dumps(registration))
            for seed, state in ((800001, "complete"), (800002, "running")):
                target = folder / "runs" / str(seed) / "attempt_1"
                target.mkdir(parents=True)
                (target / "manifest.json").write_text(json.dumps({"status": state}))
            with patch("ranr.gama.long_collection.provenance", return_value=registration["source"]), \
                 patch("ranr.gama.long_collection.preflight"), \
                 patch("ranr.gama.long_collection.validate_days"), \
                 patch("ranr.gama.long_collection.checked_result") as cached, \
                 patch.dict(os.environ), \
                 patch("ranr.gama.long_collection.run", side_effect=ValueError("contract error")) as runner:
                with self.assertRaisesRegex(ValueError, "contract error"):
                    execute(folder)
            cached.assert_called_once()
            runner.assert_called_once()
            self.assertEqual(runner.call_args.args[0].seed, 800002)
            self.assertEqual(runner.call_args.args[2], folder / "runs/800002/attempt_2")
            previous = json.loads((folder / "runs/800002/attempt_1/manifest.json").read_text())
            self.assertEqual(previous["error_type"], "interrupted")
            self.assertEqual(previous["status"], "failed")

    def test_duplicate_collections_cannot_allocate_two_jvms(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch("ranr.gama.long_collection.COLLECTION_ROOT", Path(directory)):
            with collection_lock():
                with self.assertRaisesRegex(RuntimeError, "Another long collection"):
                    collection_lock()
            with collection_lock():
                pass

    def test_kill_between_mkdir_and_registration_is_preserved_and_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            config = RunConfig(development=True, calibrating=True, trace=True)
            registration = {"source": {"fixture": "unit"}, "config": asdict(config), "seeds": [800001]}
            (folder / "registration.json").write_text(json.dumps(registration))
            orphan = folder / "runs/800001/attempt_1"
            orphan.mkdir(parents=True)
            (orphan / "evidence.txt").write_text("retained")
            with patch("ranr.gama.long_collection.provenance", return_value=registration["source"]), \
                 patch("ranr.gama.long_collection.preflight"), patch.dict(os.environ), \
                 patch("ranr.gama.long_collection.run", side_effect=ValueError("unit stop")) as runner:
                with self.assertRaisesRegex(ValueError, "unit stop"):
                    execute(folder)
            self.assertEqual(runner.call_args.args[2], folder / "runs/800001/attempt_2")
            self.assertEqual((orphan / "evidence.txt").read_text(), "retained")
            self.assertEqual(json.loads((orphan / "manifest.json").read_text())["error_type"], "interrupted")

    def test_real_stalled_child_produces_diagnostics_before_shutdown(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            log = folder / "launch.log"
            log.touch()
            # A real child that makes one progress write and then stalls. This
            # exercises ownership and watchdog timing without launching GAMA.
            script = "from pathlib import Path; import time; Path('population_population.csv').write_text('time_min,total\\n305,4700\\n'); time.sleep(20)"
            child = subprocess.Popen([sys.executable, "-c", script], cwd=folder, start_new_session=True)
            try:
                with self.assertRaises(ProgressStalled):
                    wait_for_gama(child, log, 5, {"RANR_STALL_SECONDS": "0.15",
                                                "RANR_STARTUP_SECONDS": "2", "RANR_POLL_SECONDS": "0.04"})
                self.assertEqual(last_simulation_minute(folder), 305)
                diagnostics = list((folder / "diagnostics").glob("*/processes.json"))
                self.assertEqual(len(diagnostics), 1)
                record = json.loads(diagnostics[0].read_text())
                self.assertEqual(record["pgid"], child.pid)
                self.assertIn(child.pid, [row["pid"] for row in record["processes"]])
            finally:
                os.killpg(child.pid, signal.SIGTERM)
                child.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
