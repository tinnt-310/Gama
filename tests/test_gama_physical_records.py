"""Synthetic artifact fixtures for independent validation, not simulation results."""
import csv
import json
from pathlib import Path
import tempfile
import unittest
from ranr.gama.contracts import validate_physical_records


class PhysicalRecords(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        self.config = dict(background_cars=1, private_evs=1, electric_taxis=0, warmup_minutes=0,
                           measure_minutes=30, deadline_minutes=30, consumption_kwh_km=.18,
                           charge_efficiency=.9, rush_extra_percent=30)
        self.save('initial_fleet.json', [dict(id=1000,kind='car'),dict(id=10000,kind='private')])
        self.save('vehicle_traits.json', [dict(id=10000,kind='private',initial_soc=40.,soc_request_threshold=30.,soc_preferred_target=80.,battery_capacity_kwh=60.)])
        self.save('station_inventory.json', [dict(sid=sid,ports={str(i):60. for i in range(15 if sid==0 else 11)}) for sid in range(11)])
        self.save('request_attempts.json', [])
        self.save('outcomes.json', [])
        self.save('charging_intents.json', [])
        self.save('traffic_plan.json', [])
        self.save('stranded_ev_ids.json', [])
        self.save('gateway_validation.json',dict(gateways=[dict(x=0.,y=0.)]*4))
        (self.folder/'events.csv').write_text('request_id,terminal_record,time_min,energy_kwh,station_sid,port_id,port_kw,ev_limit_kw,soc,target_soc\n')
        (self.folder/'traffic.csv').write_text('at,vehicle_id,kind,event,gateway,x,y,soc\n')
        (self.folder/'calibration_contexts.csv').write_text('context\n')
        self.rows=[dict(at=at,vehicle_id=id,kind=kind,total_metres=0.,total_charged_kwh=0.,soc=soc,threshold=threshold,x=0.,y=0.)
                   for at in (0.,60.) for id,kind,soc,threshold in ((1000,'car',-1.,-1.),(10000,'private',40.,30.))]
        self.write_vehicles()

    def save(self,name,value):
        (self.folder/name).write_text(json.dumps(value))

    def write_vehicles(self):
        with (self.folder/'vehicles.csv').open('w') as stream:
            writer=csv.DictWriter(stream,fieldnames=self.rows[0].keys());writer.writeheader();writer.writerows(self.rows)

    def test_valid_uncharged_fleet_retains_physical_identity(self):
        result=validate_physical_records(self.folder,self.config)
        self.assertEqual(result['soc_rows_checked'],2)
        self.assertEqual(result['port_inventory'],125)
        self.assertFalse(result['legacy_schedule_present'])

    def test_soc_cannot_increase_without_charged_energy(self):
        self.rows[-1]['soc']=50.
        self.write_vehicles()
        with self.assertRaisesRegex(ValueError,'conserve physical energy'):
            validate_physical_records(self.folder,self.config)

    def test_vehicle_cannot_teleport(self):
        self.rows[-1]['x']=100.
        self.write_vehicles()
        with self.assertRaisesRegex(ValueError,'without recording travel'):
            validate_physical_records(self.folder,self.config)

    def test_individual_threshold_must_remain_persistent(self):
        self.rows[-1]['threshold']=31.
        self.write_vehicles()
        with self.assertRaisesRegex(ValueError,'threshold changed'):
            validate_physical_records(self.folder,self.config)

    def test_duplicate_port_allocation_is_rejected(self):
        self.save('request_attempts.json',[dict(request_id='a',vehicle_id=10000,at=0.),dict(request_id='b',vehicle_id=10000,at=0.)])
        with (self.folder/'events.csv').open('a') as stream:
            stream.write('a,arrival,0,0,0,0,60,120,40,80\n')
            stream.write('b,arrival,0,0,0,0,60,120,40,80\n')
            stream.write('a,service_started,0,0,0,0,60,120,40,80\n')
            stream.write('b,service_started,0,0,0,0,60,120,40,80\n')
        with self.assertRaisesRegex(ValueError,'port allocation'):
            validate_physical_records(self.folder,self.config)

    def test_legacy_schedule_or_out_of_window_context_is_rejected(self):
        self.save('opportunities.json',[])
        with self.assertRaisesRegex(ValueError,'Legacy charging'):
            validate_physical_records(self.folder,self.config)
        (self.folder/'opportunities.json').unlink()
        with (self.folder/'calibration_contexts.csv').open('w') as stream:
            writer=csv.DictWriter(stream,fieldnames=['context']);writer.writeheader();writer.writerow(dict(context=json.dumps(dict(at=40.))))
        with self.assertRaisesRegex(ValueError,'outside measurement'):
            validate_physical_records(self.folder,self.config)
