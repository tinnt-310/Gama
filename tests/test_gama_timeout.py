"""Failure recovery preserves GAMA evidence and never fabricates a completed run."""

import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from ranr.gama.headless import (
    RunConfig,
    archive_failed_run,
    last_simulation_minute,
    run,
)


class TimeoutRecovery(unittest.TestCase):
    def test_progress_ignores_partial_csv_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            self.assertIsNone(last_simulation_minute(folder))
            (folder / "legacy_population.csv").write_text(
                "time_min,total_cars\n\n0,3000\n1062,3000\nnan,3000\nunfinished"
            )
            self.assertEqual(last_simulation_minute(folder), 1062)

    def test_timeout_retains_partial_files_without_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory) / "run"

            def timeout(arguments, log, limit, environment):
                (folder / "legacy_population.csv").write_text(
                    "time_min,total_cars\n1062,3000\n"
                )
                (folder / "events.csv").write_text("preserved evidence\n")
                raise subprocess.TimeoutExpired(["test-launcher"], limit)

            with patch("ranr.gama.headless._launch", side_effect=timeout):
                with self.assertRaisesRegex(TimeoutError, "1062/1080"):
                    run(RunConfig(development=True), [0.0] * 20, folder)
            record = json.loads((folder / "manifest.json").read_text())
            self.assertEqual(record["status"], "failed")
            self.assertEqual(record["error_type"], "timeout")
            self.assertEqual(record["last_simulated_minutes"], 1062)
            self.assertEqual(
                (folder / "events.csv").read_text(), "preserved evidence\n"
            )
            self.assertFalse((folder / "completion.json").exists())

    def test_archive_preserves_failed_run_and_rejects_running_or_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory) / "800001"
            folder.mkdir()
            for status in ["running", "complete"]:
                (folder / "manifest.json").write_text(json.dumps({"status": status}))
                with self.assertRaises(ValueError):
                    archive_failed_run(folder)
                self.assertTrue(folder.exists())
            (folder / "manifest.json").write_text(json.dumps({"status": "failed"}))
            (folder / "raw.csv").write_bytes(b"scientific evidence\x00\n")
            destination = archive_failed_run(folder)
            self.assertFalse(folder.exists())
            self.assertEqual(
                (destination / "raw.csv").read_bytes(), b"scientific evidence\x00\n"
            )
            self.assertEqual(
                json.loads((destination / "manifest.json").read_text())["status"],
                "failed",
            )

    def test_calibration_restart_archives_old_inputs_before_fresh_attempt(self):
        from ranr.gama.cli import main

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            output = base / "calibration"
            folder = output / "runs/800001"
            folder.mkdir(parents=True)
            (folder / "manifest.json").write_text(
                json.dumps({"status": "failed", "config": {"timeout_seconds": 1}})
            )
            config = base / "config.json"
            config.write_text(
                json.dumps({"development": True, "timeout_seconds": 28800})
            )

            def fresh_attempt(config, parameters, folder, *, resume):
                self.assertFalse(folder.exists())
                self.assertFalse(resume)
                self.assertEqual(config.timeout_seconds, 28800)

            argv = [
                "ranr",
                "--config",
                str(config),
                "calibrate",
                "--output",
                str(output),
                "--restart-incomplete",
            ]
            with patch("sys.argv", argv), patch(
                "ranr.gama.cli.run", side_effect=fresh_attempt
            ) as runner, patch("ranr.gama.cli.collect_calibration") as collect:
                main()
            self.assertEqual(runner.call_count, 3)
            collect.assert_called_once()
            archives = list((output / "runs/_incomplete").glob("800001_*"))
            self.assertEqual(len(archives), 1)
            self.assertEqual(
                json.loads((archives[0] / "manifest.json").read_text())["config"][
                    "timeout_seconds"
                ],
                1,
            )


if __name__ == "__main__":
    unittest.main()
