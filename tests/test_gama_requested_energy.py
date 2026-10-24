"""Cross-file requested-energy mutation tests using explicit synthetic records."""
import csv
from pathlib import Path
import tempfile
import unittest
from gama_ledger_fixture import ledger_fixture
from ranr.gama.contracts import validate_charging_ledger, validate_request_energy_files, validate_event_identity, recompute_intent_metrics


class RequestedEnergy(unittest.TestCase):
    def test_metric_arithmetic_preserves_censored_waits_and_empty_cohorts(self):
        rows=ledger_fixture()[3]
        metrics=recompute_intent_metrics(rows,0.,30.,.5)
        self.assertEqual(metrics['measurement_intent_count'],1)
        self.assertEqual(metrics['mean_wait_min'],4.)
        self.assertEqual(metrics['p95_wait_min'],4.)
        self.assertAlmostEqual(metrics['operational_objective'],.5*17/360.+.3*4/360.+.1)
        rows=ledger_fixture(status='unresolved',delivered=3.)[3]
        self.assertEqual(recompute_intent_metrics(rows,0.,30.,0.)['waiting_sample_count'],1)
        empty=recompute_intent_metrics([],0.,30.,0.)
        self.assertIsNone(empty['mean_wait_min'])
        self.assertIsNone(empty['mean_completed_time_min'])

    def test_event_identity_and_target_cannot_disagree_with_intent(self):
        attempt=dict(vehicle_id=10000,intent_id='i1')
        intent=dict(target_soc=90.)
        valid=dict(vehicle_id='10000',intent_id='i1',target_soc='90')
        self.assertTrue(validate_event_identity(valid,attempt,intent))
        for key,value in (('vehicle_id','10001'),('intent_id','other'),('target_soc','80'),('target_soc','nan')):
            with self.subTest(key=key),self.assertRaises(ValueError):
                validate_event_identity(dict(valid,**{key:value}),attempt,intent)

    def test_attempt_cannot_inflate_total_requested_energy(self):
        rows = ledger_fixture(status='unresolved', delivered=3.)
        rows[2][0]['requested_kwh'] = 1000.
        with self.assertRaisesRegex(ValueError, 'exceeds complete intent'):
            validate_charging_ledger(*rows)

    def test_all_initial_identity_and_energy_fields_remain_immutable(self):
        for field,value in (('kind','taxi'),('cause','trip_energy'),('key',9),('at',6.),
                            ('initial_required_kwh',11.),('initial_battery_kwh',18.4),('battery_capacity_kwh',61.)):
            rows=ledger_fixture()
            rows[3][0][field]=value
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'Immutable'):
                validate_charging_ledger(*rows)

    def test_outcome_attempt_total_and_completion_flag_cannot_disagree(self):
        rows=ledger_fixture();rows[0][0]['status']='open'
        with self.assertRaisesRegex(ValueError,'closure state'):
            validate_charging_ledger(*rows)
        rows=ledger_fixture();rows[3][0]['attempts']=2
        with self.assertRaisesRegex(ValueError,'attempt total'):
            validate_charging_ledger(*rows)
        rows=ledger_fixture(status='unresolved',delivered=3.)
        rows[2][0]['energy_complete']=True
        with self.assertRaisesRegex(ValueError,'completion flag'):
            validate_charging_ledger(*rows)

    def fixture(self, folder, requested=10., updates=()):
        rows=ledger_fixture(status='unresolved',delivered=3.)
        rows[2][0]['requested_kwh']=requested
        target=rows[0][0]['target_soc']
        (folder/'demand.csv').write_text(f'request_id,issued_min,energy_kwh,initial_soc,intent_id,target_soc\nr1,5,10,29,i1,{target}\n')
        with (folder/'demand_energy_updates.csv').open('w') as stream:
            writer=csv.DictWriter(stream,fieldnames=['request_id','at','reason','required_kwh','target_soc','soc'])
            writer.writeheader()
            for update in updates:
                writer.writerow(dict(request_id='r1',at=6.,reason='arrival',required_kwh=12.,target_soc=target,soc=25.,**update))
        return rows

    def test_dynamic_requested_energy_is_rebuilt_from_ordered_updates(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary)
            rows=self.fixture(folder,requested=12.,updates=[{}])
            self.assertTrue(validate_request_energy_files(folder,*rows[:3]))
            rows[2][0]['requested_kwh']=10.
            with self.assertRaisesRegex(ValueError,'update ledger'):
                validate_request_energy_files(folder,*rows[:3])

    def test_missing_and_orphan_demands_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary);rows=self.fixture(folder)
            (folder/'demand.csv').write_text('request_id\n')
            with self.assertRaisesRegex(ValueError,'identities differ'):
                validate_request_energy_files(folder,*rows[:3])

    def test_updates_must_have_valid_target_time_energy_and_request(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary)
            for field,value in (('target_soc',95.),('at',30.),('required_kwh',float('nan')),('request_id','orphan')):
                rows=self.fixture(folder,requested=12.)
                target=rows[0][0]['target_soc']
                row=dict(request_id='r1',at=6.,reason='arrival',required_kwh=12.,target_soc=target,soc=25.)
                row[field]=value
                with (folder/'demand_energy_updates.csv').open('w') as stream:
                    writer=csv.DictWriter(stream,fieldnames=row.keys());writer.writeheader();writer.writerow(row)
                with self.subTest(field=field),self.assertRaises(ValueError):
                    validate_request_energy_files(folder,*rows[:3])
