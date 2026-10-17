"""Independent outcome/provenance/analysis contracts, with synthetic unit records."""
import copy
import unittest
from dataclasses import replace
from ranr.gama.headless import RunConfig, parameter_record
from gama_ledger_fixture import ledger_fixture
from ranr.gama.contracts import OBJECTIVE_CONFIG_HASH, validate_charging_ledger, rescore_components, finite_tree, validate_behavior_config

class Contracts(unittest.TestCase):
    def setUp(self):
        self.intents, self.attempts, self.outcomes, self.final = ledger_fixture()

    def check(self, attempts=None, outcomes=None, final=None):
        return validate_charging_ledger(self.intents, self.attempts if attempts is None else attempts, self.outcomes if outcomes is None else outcomes, self.final if final is None else final)

    def test_one_need_one_request_and_final_resolution(self):
        self.assertTrue(self.check())

    def test_missing_duplicate_and_unrelated_requests(self):
        for attempts, outcomes in [(self.attempts*2,self.outcomes),(self.attempts,[]),(self.attempts,self.outcomes*2)]:
            with self.subTest(attempts=attempts), self.assertRaises(ValueError): self.check(attempts,outcomes)
        attempts=copy.deepcopy(self.attempts);attempts[0]["intent_id"]="other"
        with self.assertRaises(ValueError):self.check(attempts)

    def test_terminal_categories_and_partial_energy(self):
        for status in ('completed','failed','unresolved'):
            self.assertTrue(validate_charging_ledger(*ledger_fixture(status=status,delivered=10. if status=='completed' else 3.)))
        rows=ledger_fixture();rows[3][0]['delivered_kwh']=3.
        with self.assertRaises(ValueError):validate_charging_ledger(*rows)

    def test_duration_and_nested_nonfinite_rejected(self):
        row=copy.deepcopy(self.outcomes);row[0]["charging_min"]=100.
        with self.assertRaisesRegex(ValueError,"duration"):self.check(outcomes=row)
        self.assertFalse(finite_tree({"a":[{"hidden":float("nan")}]}))

    def test_passenger_and_impossible_threshold_request_rejected(self):
        requests=copy.deepcopy(self.attempts);requests[0]["passenger"]=True
        with self.assertRaisesRegex(ValueError,"physical gate"):self.check(attempts=requests)
        self.intents[0]["soc_at_need"]=50.
        with self.assertRaisesRegex(ValueError,"threshold"):self.check()

    def test_personal_distributions_are_distinct_configurable_assumptions(self):
        from ranr.gama.headless import ENVIRONMENT
        self.assertTrue(validate_behavior_config(ENVIRONMENT))
        self.assertNotEqual(ENVIRONMENT["private_threshold_probabilities"], ENVIRONMENT["taxi_threshold_probabilities"])
        bad=copy.deepcopy(ENVIRONMENT);bad["private_threshold_probabilities"][0]=.9
        with self.assertRaisesRegex(ValueError,"distribution"):validate_behavior_config(bad)

    def test_objective_decomposition_and_sensitivity(self):
        c=dict(version="intent-service-5",objective_config_hash=OBJECTIVE_CONFIG_HASH,fitness_valid=True,
               time_component=.35,tail_component=.1725,queue_component=.008)
        self.assertAlmostEqual(rescore_components(c),.5305)
        with self.assertRaises(TypeError):rescore_components(c,.5,.5)

    def test_design_configuration_and_independent_parameters(self):
        config=RunConfig(development=True)
        self.assertEqual(config.stabilization,"off")
        for method in ("RANR-AW","No-P2P","No-Prediction"):
            self.assertEqual(len(parameter_record(method,[0.]*20)["parameters"]),20)
        self.assertEqual(len(parameter_record("Fixed-Weights",[0.]*4)["parameters"]),4)
        for kw in ({"temperature":0},{"packet_loss":2},{"partition_begin":2,"partition_end":1},{"objective_version":"old"},{"stabilization":"unknown"}):
            with self.subTest(kw=kw),self.assertRaises(ValueError):replace(config,**kw)

if __name__=="__main__":unittest.main()

class ExecutionContracts(unittest.TestCase):
    def test_candidate_requires_registered_matching_source_and_vector(self):
        import tempfile,json
        from pathlib import Path
        from unittest.mock import patch
        from dataclasses import asdict
        from ranr.paths import write_json
        from ranr.gama.gui_collection import validate_candidate
        config=RunConfig(development=True)
        candidate=parameter_record("RANR-AW",[0.]*20)
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            record=dict(status="running",backend="GAMA",source={"unit_fixture":True},parameters=candidate,config=asdict(config))
            write_json(folder/"manifest.json",record);write_json(folder/"candidate.json",candidate)
            with patch("ranr.gama.gui_collection.provenance",return_value={"unit_fixture":True}):
                self.assertTrue(validate_candidate(folder))
                candidate["parameters"][0]=1.
                write_json(folder/"candidate.json",candidate)
                with self.assertRaisesRegex(ValueError,"mismatch"):validate_candidate(folder)

    def test_scenario_overrides_are_checked_without_privileged_policy_inputs(self):
        from dataclasses import asdict
        from ranr.gama.contracts import validate_configuration
        c=asdict(RunConfig(development=True,case="combined"))
        actual=dict(c,initial_private_cars=c["background_cars"],initial_private_evs=c["private_evs"],initial_electric_taxis=c["electric_taxis"],scenarios=c["samples"],compliance=.2,delay_minutes=5.,packet_loss=.1)
        self.assertTrue(validate_configuration(actual,c))
        actual["temperature"]=.5
        with self.assertRaisesRegex(ValueError,"temperature"):validate_configuration(actual,c)


class SocActivityArchitecture(unittest.TestCase):
    def test_legacy_request_schedulers_and_controls_are_removed(self):
        from pathlib import Path
        from ranr.paths import ROOT
        active = "\n".join(p.read_text() for p in (ROOT / "models").rglob("*.gaml") if "tests" not in p.parts)
        for token in ("ranr_plan_opportunity", "ranr_plan_vehicle_opportunities", "ranr_plan_burst", "ranr_private_frequency", "ranr_taxi_frequency", "ranr_soc_threshold", "ranr_burst_size"):
            self.assertNotIn(token, active)
        for retired in ("private_frequency", "taxi_frequency", "soc_threshold", "target_soc", "burst_size"):
            with self.subTest(retired=retired), self.assertRaises(TypeError):
                RunConfig(development=True, **{retired: 1})
        import json
        for path in (ROOT / "configs/gama").glob("*.json"):
            data = json.loads(path.read_text())
            self.assertFalse(set(data) & {"private_opportunities_per_day", "taxi_opportunities_per_day", "private_frequency", "taxi_frequency"})

    def test_movement_and_inbound_creation_do_not_reseed_or_restore_rng(self):
        import re
        from ranr.paths import ROOT
        for name in ("Mobility.gaml", "ChargingService.gaml"):
            self.assertIsNone(re.search(r"\b(?:seed|rng_usage)\s*<-", (ROOT / "models" / name).read_text()))
        fleet = (ROOT / "models/ranr/Fleet.gaml").read_text()
        creation = fleet[fleet.index("action ranr_spawn_inbound"):fleet.index("intersection ranr_activity_destination")]
        self.assertIsNone(re.search(r"\b(?:seed|rng_usage)\s*<-", creation))

    def test_gui_collection_and_headless_use_one_physical_model_without_prices(self):
        from ranr.paths import ROOT
        main = (ROOT / "models/main.gaml").read_text()
        self.assertIn('experiment "Collect training data" type:gui parent:"Run me"', main)
        for name in ("ChargingService.gaml", "ranr/Fleet.gaml", "ranr/Policy.gaml", "ranr/Runtime.gaml"):
            self.assertNotIn("price", (ROOT / "models" / name).read_text().lower())
        self.assertIn('str(ROOT / "models/main.gaml")', (ROOT / "src/ranr/gama/headless.py").read_text())
