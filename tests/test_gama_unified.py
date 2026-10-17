"""Unified environment and GUI collection contracts; synthetic data are unit fixtures."""

from dataclasses import asdict
from pathlib import Path
import csv
import json
import tempfile
import unittest
from unittest.mock import patch

from ranr.paths import write_json, digest
from ranr.gama.headless import (
    RunConfig,
    parameter_record,
    load_model,
    ENVIRONMENT_VERSION,
)
from ranr.gama import gui_collection as gui
from gama_ledger_fixture import ledger_fixture, fitness_fixture
from ranr.gama.contracts import OBJECTIVE_CONFIG_HASH


class UnifiedEnvironment(unittest.TestCase):
    def test_fleet_and_invalid_configuration(self):
        config = RunConfig(development=True)
        self.assertEqual(
            config.background_cars + config.private_evs + config.electric_taxis, 4700
        )
        self.assertEqual(config.step_seconds, 60)
        self.assertEqual(config.warmup_minutes + config.measure_minutes + config.deadline_minutes, 4320)
        for kwargs in (
            {"private_evs": -1},
            {"electric_taxis": 2.5},
            {"rush_extra_percent": 31},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                RunConfig(development=True, **kwargs)

    def test_old_model_is_rejected_including_development(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / "old.json"
            model = parameter_record("RANR-AW", [0.0] * 20)
            model["environment_version"] = "retired"
            write_json(p, model)
            with self.assertRaisesRegex(ValueError, "environment_version"):
                load_model(p, "RANR-AW", RunConfig(development=True))


class GuiCollection(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name) / "runs/collect_800001_fixture"
        self.folder.mkdir(parents=True)
        self.source_patch = patch.object(
            gui, "provenance", return_value={"fixture": "unit-only"}
        )
        self.source_patch.start()
        self.addCleanup(self.source_patch.stop)
        self.physical_patch = patch.object(gui, "validate_physical_records", return_value={"unit_fixture": True})
        self.physical_patch.start()
        self.addCleanup(self.physical_patch.stop)
        for target,value in [("ranr.gama.evidence.provenance", {"fixture":"unit-only"}),
                             ("ranr.gama.evidence.validate_physical_records", {"unit_fixture":True})]:
            mock = patch(target,return_value=value)
            mock.start()
            self.addCleanup(mock.stop)
        self.record = gui.prepare(self.folder)

    def finish_files(self):
        config = self.record["config"]
        (self.folder/'daily_statistics.csv').write_text('Day,Station_Name\n'+''.join(f'{day},cs_{sid}\n' for day in range(1,4) for sid in range(11)))
        for name,header in [('calibration_snapshots.csv','snapshot'),('calibration_contexts.csv','context'),('calibration_fractions.csv','release_fraction,energy_fraction')]:
            (self.folder/name).write_text(header+'\n')
        actual = dict(
            config,
            run_id=self.folder.name,
            scenarios=config["samples"],
            initial_private_cars=config["background_cars"],
            initial_private_evs=config["private_evs"],
            initial_electric_taxis=config["electric_taxis"],
        )
        write_json(self.folder / "configuration.json", actual)
        write_json(
            self.folder / "completion.json",
            {
                "run_id": self.folder.name,
                "status": "complete",
                "outcome_count": 1,
                "finished_min": config["warmup_minutes"] + config["measure_minutes"] + config["deadline_minutes"],
            },
        )
        write_json(
            self.folder / "metrics.json",
            {
                "run_id": self.folder.name,
                "all_demand_count": 1,
                "all_outcome_count": 1,
                "objective": 0.0,
                "objective_components": {"version":"intent-service-5","time_component":0.0,"tail_component":0.0,"queue_component":0.0,"failure_component":0.0,"energy_component":0.0},
            },
        )
        write_json(
            self.folder / "outcomes.json",
            [
                {
                    "request_id": "r1", "intent_id": "intent_10000_1",
                    "key":1,"vehicle_id":10000,"travel_min":5.0,"waiting_min":0.0,"charging_min":20.0,"service_time_min":25.0,
                    "status": "completed",
                    "requested_kwh": 20,
                    "delivered_kwh": 20,
                }
            ],
        )
        (self.folder / "events.csv").write_text("request_id,terminal_record,time_min,leg\nr1,arrival,5.0,0\n")
        (self.folder / "demand.csv").write_text("request_id\nr1\n")
        for name in ("activity_plan.json", "vehicle_traits.json", "traffic_plan.json", "initial_fleet.json"):
            write_json(self.folder / name, [])
        intents, attempts, outcomes, resolutions = ledger_fixture(created=0.,finished=25.)
        outcomes[0].update(travel_min=5.,waiting_min=0.,charging_min=20.,service_time_min=25.)
        resolutions[0].update(travel_min=5.,waiting_min=0.,charging_min=20.,other_elapsed_min=0.)
        for name,rows in [('charging_intents.json',intents),('request_attempts.json',attempts),('outcomes.json',outcomes),('intent_outcomes.json',resolutions)]:
            write_json(self.folder/name,rows)
        write_json(self.folder/'initial_fleet.json',[dict(id=10000,kind='private')])
        write_json(self.folder/'mobility_outcomes.json',[])
        write_json(self.folder/'stranded_ev_ids.json',[])
        write_json(self.folder/'charging_needs.json',[dict(intent_id='i1',vehicle_id=10000,at=0.)])
        write_json(self.folder/'intent_time_intervals.json',[
            dict(intent_id='i1',state='travel',begin=0.,end=5.),
            dict(intent_id='i1',state='charging',begin=5.,end=25.)])
        metrics=json.loads((self.folder/'metrics.json').read_text())
        metrics.update(fitness_fixture(seed=config['seed']),planned_ev_days=config['measure_minutes']/1440.)
        metrics['objective_components']=dict(version='intent-service-5',objective_config_hash=OBJECTIVE_CONFIG_HASH,
            fitness_valid=True,time_component=0.,tail_component=0.,queue_component=0.)
        write_json(self.folder/'metrics.json',metrics)


    def test_removing_whole_intent_does_not_hide_physical_need(self):
        self.finish_files()
        for name in ('charging_intents.json','request_attempts.json','outcomes.json','intent_outcomes.json'):
            write_json(self.folder/name,[])
        metrics=json.loads((self.folder/'metrics.json').read_text());metrics.update(all_demand_count=0,all_outcome_count=0)
        write_json(self.folder/'metrics.json',metrics)
        marker=json.loads((self.folder/'completion.json').read_text());marker['outcome_count']=0
        write_json(self.folder/'completion.json',marker)
        (self.folder/'demand.csv').write_text('request_id\n')
        with self.assertRaisesRegex(ValueError,'physical charging need'):
            gui.complete(self.folder)

    def test_missing_active_interval_is_invalid(self):
        self.finish_files()
        write_json(self.folder/'intent_time_intervals.json',[])
        with self.assertRaisesRegex(ValueError,'time accounting'):
            gui.complete(self.folder)

    def test_registration_refuses_overwrite(self):
        with self.assertRaises(FileExistsError):
            gui.prepare(self.folder)

    def test_gui_collection_registers_72_hours_with_display(self):
        config = self.record["config"]
        self.assertEqual(config["warmup_minutes"] + config["measure_minutes"] + config["deadline_minutes"], 4320)
        self.assertEqual(config["step_seconds"], 60)
        self.assertTrue(config["render"] and config["trace"] and config["calibrating"])

    def test_stopped_episode_and_missing_seed_are_rejected(self):
        with self.assertRaises(FileNotFoundError):
            gui.complete(self.folder)
        with self.assertRaises(ValueError):
            gui.build(Path(self.tmp.name))

    def test_completion_seals_hashes_and_rejects_tampering(self):
        from ranr.gama.headless import checked_result

        self.finish_files()
        record = gui.complete(self.folder)
        self.assertEqual(record["status"], "complete")
        checked_result(self.folder, {"source": {"fixture": "unit-only"}})
        (self.folder / "demand.csv").write_text("modified")
        with self.assertRaisesRegex(ValueError, "artifact changed"):
            checked_result(self.folder, {})

    def test_gama_float_rounding_is_accepted(self):
        self.record["config"]["compliance"] = 1 / 3
        write_json(self.folder / "manifest.json", self.record)
        self.finish_files()
        path = self.folder / "configuration.json"
        actual = json.loads(path.read_text())
        actual["compliance"] = 0.33333333
        write_json(path, actual)
        self.assertEqual(gui.complete(self.folder)["status"], "complete")

    def test_energy_intent_is_validated_and_sealed(self):
        self.finish_files()
        record = gui.complete(self.folder)
        self.assertIn("charging_intents.json", record["artifact_hashes"])
        self.assertIn("request_attempts.json", record["artifact_hashes"])
        self.assertNotIn("opportunities.json", record["artifact_hashes"])

    def test_missing_or_duplicate_energy_intent_is_rejected(self):
        self.finish_files()
        path = self.folder / "charging_intents.json"
        intents = json.loads(path.read_text())
        write_json(path, intents * 2)
        with self.assertRaisesRegex(ValueError, "Duplicate intent"):
            gui.complete(self.folder)
        write_json(path, [])
        with self.assertRaisesRegex(ValueError, "Missing intent"):
            gui.complete(self.folder)

    def test_real_configuration_changes_are_rejected(self):
        for field, value in (
            ("compliance", 0.7),
            ("initial_private_evs", self.record["config"]["private_evs"] + 1e-6),
            ("rush_enabled", 1),
            ("case", "high"),
            ("packet_loss", 0.1),
        ):
            with self.subTest(field=field):
                self.finish_files()
                path = self.folder / "configuration.json"
                actual = json.loads(path.read_text())
                actual[field] = value
                write_json(path, actual)
                with self.assertRaisesRegex(ValueError, "configuration mismatch"):
                    gui.complete(self.folder)

    def test_wrong_source_or_physical_configuration_is_rejected(self):
        self.finish_files()
        with patch.object(gui, "provenance", return_value={"changed": True}):
            with self.assertRaisesRegex(ValueError, "source changed"):
                gui.complete(self.folder)
        p = self.folder / "configuration.json"
        data = json.loads(p.read_text())
        data["initial_private_evs"] = 0
        write_json(p, data)
        with self.assertRaisesRegex(ValueError, "private_evs"):
            gui.complete(self.folder)

    def test_missing_outcome_or_short_settlement_is_rejected(self):
        self.finish_files()
        write_json(self.folder / "outcomes.json", [])
        with self.assertRaisesRegex(ValueError, "outcomes"):
            gui.complete(self.folder)
        self.finish_files()
        p = self.folder / "completion.json"
        d = json.loads(p.read_text())
        d["finished_min"] = 5
        write_json(p, d)
        with self.assertRaisesRegex(ValueError, "settlement"):
            gui.complete(self.folder)

    def test_insufficient_calibration_does_not_write_result(self):
        from ranr.gama.pipeline import collect_calibration

        self.finish_files()
        gui.complete(self.folder)
        for filename, header in [
            ("calibration_snapshots.csv", "snapshot"),
            ("calibration_contexts.csv", "context"),
            ("calibration_fractions.csv", "release_fraction,energy_fraction"),
        ]:
            (self.folder / filename).write_text(header + "\n")
        # Seal again only as a synthetic test fixture, not a research run.
        record = json.loads((self.folder / "manifest.json").read_text())
        record["artifact_hashes"] = {
            p.name: digest(p)
            for p in self.folder.iterdir()
            if p.name != "manifest.json"
        }
        write_json(self.folder / "manifest.json", record)
        target = self.folder / "calibration.json"
        with patch(
            "ranr.gama.pipeline.provenance", return_value={"fixture": "unit-only"}
        ):
            with self.assertRaisesRegex(ValueError, "Insufficient"):
                collect_calibration([self.folder], target)
        self.assertFalse(target.exists())

    def test_three_complete_seed_collections_build_calibration(self):
        root = Path(self.tmp.name)
        for seed in gui.SEEDS:
            if seed != 800001:
                self.folder = root / f"runs/collect_{seed}_fixture"
                self.folder.mkdir(parents=True)
                self.record = gui.prepare(self.folder)
            self.finish_files()
            outcomes = json.loads((self.folder / "outcomes.json").read_text())
            outcomes[0]["travel_min"] = 5.0
            write_json(self.folder / "outcomes.json", outcomes)
            with (self.folder / "calibration_snapshots.csv").open("w") as f:
                writer = csv.DictWriter(f, fieldnames=["snapshot"])
                writer.writeheader()
                for sid in range(11):
                    writer.writerow(
                        {
                            "snapshot": json.dumps(
                                {
                                    "sid": sid,
                                    "powers": [60.0],
                                    "release_lo": [0.0],
                                    "release_hi": [0.0],
                                    "queue": [],
                                }
                            )
                        }
                    )
            with (self.folder / "calibration_contexts.csv").open("w") as f:
                writer = csv.DictWriter(f, fieldnames=["context"])
                writer.writeheader()
                writer.writerow(
                    {
                        "context": json.dumps(
                            {
                                "request_id": "r1", "intent_id": "intent_10000_1",
                                "issuer": 0,
                                "chosen": 0,
                                "travel": [5.0] * 11,
                                "energy": 20.0,
                                "max_kw": 60.0,
                                "participating": True,
                            }
                        )
                    }
                )
            (self.folder / "calibration_fractions.csv").write_text(
                "release_fraction,energy_fraction\n0.5,0.5\n"
            )
            gui.complete(self.folder)
        with patch(
            "ranr.gama.pipeline.provenance", return_value={"fixture": "unit-only"}
        ):
            result = gui.build(root)
        self.assertEqual(result["status"], "ready")
        calibration = json.loads(Path(result["calibration"]).read_text())
        self.assertEqual(calibration["environment_version"], ENVIRONMENT_VERSION)
        self.assertEqual(len(calibration["runs"]), 3)
        self.assertEqual(len(calibration["prior_snapshots"]), 33)

    def test_model_validation_error_preserves_parameter_file(self):
        from contextlib import redirect_stdout
        import io

        model = self.folder / "invalid_model.json"
        model.write_text('{"invalid":true}')
        before = model.read_bytes()
        output = io.StringIO()
        with patch(
            "sys.argv", ["gui_calibration", "model", str(model)]
        ), redirect_stdout(output):
            gui.main()
        self.assertIn("NOT READY", output.getvalue())
        self.assertEqual(model.read_bytes(), before)
