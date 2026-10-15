"""Independent outcome/provenance/analysis contracts, with synthetic unit records."""
import copy
import unittest
from dataclasses import replace
from ranr.gama.headless import RunConfig, parameter_record
from ranr.gama.contracts import validate_ledger, rescore_components, finite_tree

class Contracts(unittest.TestCase):
    def setUp(self):
        self.opps = [dict(key=1,vehicle_id=10000,at=5.,cause="scheduled"),dict(key=2,vehicle_id=10001,at=5.,cause="scheduled")]
        self.ledger = [{**self.opps[0],"status":"activated"},{**self.opps[1],"status":"soc_not_low"}]
        self.outcomes = [dict(key=1,vehicle_id=10000,request_id="r1",status="completed",requested_kwh=10.,delivered_kwh=10.,travel_min=3.,waiting_min=4.,charging_min=10.,service_time_min=17.)]

    def test_legitimate_no_need_is_not_failure(self):
        self.assertTrue(validate_ledger(self.opps,self.ledger,self.outcomes))

    def test_missing_duplicate_and_unactivated_requests(self):
        for ledger, outcomes in [(self.ledger[:1],self.outcomes),(self.ledger+self.ledger,self.outcomes),(self.ledger,[]),(self.ledger,self.outcomes+self.outcomes)]:
            with self.subTest(ledger=ledger), self.assertRaises(ValueError): validate_ledger(self.opps,ledger,outcomes)
        ledger=copy.deepcopy(self.ledger);ledger[0]["status"]="busy"
        with self.assertRaisesRegex(ValueError,"Ineligible"):validate_ledger(self.opps,ledger,self.outcomes)

    def test_terminal_categories_and_partial_energy(self):
        from ranr.gama.contracts import TERMINAL
        for category in TERMINAL:
            row=copy.deepcopy(self.outcomes);row[0]["status"]=category
            if category!="completed":row[0]["delivered_kwh"]=3.
            self.assertTrue(validate_ledger(self.opps,self.ledger,row))
        row=copy.deepcopy(self.outcomes);row[0]["delivered_kwh"]=3.
        with self.assertRaisesRegex(ValueError,"Incomplete energy"):validate_ledger(self.opps,self.ledger,row)

    def test_duration_and_nested_nonfinite_rejected(self):
        row=copy.deepcopy(self.outcomes);row[0]["charging_min"]=100.
        with self.assertRaisesRegex(ValueError,"completion-time"):validate_ledger(self.opps,self.ledger,row)
        self.assertFalse(finite_tree({"a":[{"hidden":float("nan")}]}))

    def test_objective_decomposition_and_sensitivity(self):
        c=dict(version="opportunity-service-3",time_component=.175,tail_component=.1725,queue_component=.008,failure_component=.25,energy_component=.25)
        self.assertAlmostEqual(rescore_components(c),.8555)
        self.assertAlmostEqual(rescore_components(c,.5,.5),.6055)

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
