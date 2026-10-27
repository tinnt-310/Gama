"""Synthetic statistics/trace tests, separate from physical validation."""
import copy
import csv
import json
from pathlib import Path
import tempfile
import unittest
import os
import importlib.util
from unittest.mock import patch
import numpy as np
from ranr.gama import predictive_validation as pv
import physical_counterfactual as cf
PATCHED=True

def rows(n=120):
    return [dict(seed=920001+i%6,case='normal',method='RANR-AW',sid=i%11,
        load_bin=i%4,time_bin=i%4,physical_wait=10.,predicted_mean=10.,
        predicted_p95=10. if i%20 else 9.,predicted_H=4.,physical_H=4.) for i in range(n)]

class StatisticalTests(unittest.TestCase):
    def fixture(self,events,recommendations):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);p=Path(tmp.name)
        config=dict(warmup_minutes=10,measure_minutes=60,deadline_minutes=30,initial_hour=6,
                    seed=920001,case='normal',method='RANR-AW')
        (p/'manifest.json').write_text(json.dumps(dict(config=config)))
        for name,data in [('events.csv',events),('recommendations.csv',recommendations)]:
            with (p/name).open('w') as f:
                w=csv.DictWriter(f,fieldnames=sorted(set().union(*(r.keys() for r in data))))
                w.writeheader();w.writerows(data)
        return p

    def event(self,kind,at,leg='1',station='0'):
        return dict(terminal_record=kind,time_min=str(at),request_id='ev1',token='t1',leg=leg,station_sid=station)

    def rec(self,at=20):
        return dict(issued_min=str(at),request_id='ev1',token='t1',actual='0',
            estimates=json.dumps([dict(mean=0,p95=1,externality=2,charge=1)]),
            state=json.dumps([1,.25,0,0,1]),raw_features=json.dumps([[11]]))

    def test_mean_p95_pinball_and_signed_externality(self):
        data=rows();m=pv.metrics(data)
        self.assertEqual(m['mean_bias'],0);self.assertEqual(m['p95_coverage'],.95)
        self.assertAlmostEqual(m['p95_pinball_loss'],.0475);self.assertEqual(m['H_MAE'],0)
        data[0].update(predicted_H=-4.,physical_H=-5.)
        self.assertAlmostEqual(pv.metrics(data)['H_MAE'],1/120)

    def test_threshold_edges_are_inclusive_and_unchanged(self):
        data=rows()
        for r in data:r['predicted_mean']=13.;r['predicted_H']=14.
        self.assertEqual(pv.assess(data)['status'],'PASS')
        data[0]['predicted_mean']+=.01
        self.assertEqual(pv.assess(data)['checks']['mean_wait'],'FAIL')

    def test_empty_zero_wait_and_insufficient_seeds(self):
        self.assertEqual(pv.assess([])['status'],'INSUFFICIENT EVIDENCE')
        data=rows()
        for r in data:r.update(physical_wait=0.,predicted_mean=0.,predicted_p95=0.)
        # Coverage1.0 fails the registered upper limit; do not change it to PASS.
        self.assertEqual(pv.assess(data)['checks']['p95'],'FAIL')
        for r in data:r['seed']=920001
        self.assertEqual(pv.assess(data)['status'],'INSUFFICIENT EVIDENCE')

    def test_bootstrap_resamples_seed_clusters_and_is_repeatable(self):
        data=rows(6)
        for i,r in enumerate(data):r.update(physical_wait=float(i),predicted_mean=0.)
        a=pv.bootstrap(data);b=pv.bootstrap(data)
        self.assertEqual(a,b)
        # Duplicating every EV inside each cluster must not shrink uncertainty.
        repeated=pv.bootstrap(data*20)
        for key in a:np.testing.assert_allclose(a[key],repeated[key],rtol=1e-14,atol=1e-14)
        self.assertNotEqual(a['mean_bias'][0],a['mean_bias'][1])

    def test_empty_mandatory_strata_propagate_insufficient(self):
        data=rows(120)
        for r in data:r.update(sid=0,load_bin=0,time_bin=0)
        result=pv.summarize(data,[])
        self.assertEqual(result['results']['normal']['RANR-AW']['overall']['status'],'PASS')
        self.assertEqual(result['normal_status'],'INSUFFICIENT EVIDENCE')
        self.assertFalse(result['passed'])

    def test_censored_wait_invalidates_unconditional_p95(self):
        data=rows();result=pv.summarize(data,[dict(case='normal',method='RANR-AW',counts=dict(censored_wait=1))])
        self.assertEqual(result['results']['normal']['RANR-AW']['overall']['status'],'INSUFFICIENT EVIDENCE')

    def test_zero_wait_and_missing_observations_are_not_imputed(self):
        p=self.fixture([self.event('arrival',25),self.event('service_started',25)],[self.rec()])
        data,count=pv.extract(p);self.assertEqual(data[0]['physical_wait'],0);self.assertEqual(count['complete_waits'],1)
        p=self.fixture([self.event('arrival',25)],[self.rec()])
        data,count=pv.extract(p);self.assertFalse(data);self.assertEqual(count['censored_wait'],1)
        p=self.fixture([self.event('other',25)],[self.rec()])
        data,count=pv.extract(p);self.assertFalse(data);self.assertEqual(count['no_arrival'],1)

    def test_duplicate_station_mismatch_and_negative_wait_rejected(self):
        for events in [[self.event('arrival',25),self.event('arrival',25)],
                       [self.event('arrival',25,station='1'),self.event('service_started',25)],
                       [self.event('arrival',25),self.event('service_started',24)]]:
            with self.subTest(events=events):
                p=self.fixture(events,[self.rec()])
                with self.assertRaises(ValueError):pv.extract(p)

    def test_selection_is_deterministic_error_independent_and_horizon_bounded(self):
        data=[dict(request_id=str(i),leg=1,sid=i%2,arrival_min=10,horizon_end=50,observation_end=100,predicted_H=i) for i in range(100)]
        a=pv.select_counterfactuals(data,920001,'normal','RANR-AW')
        other=copy.deepcopy(data)
        for r in other:r['predicted_H']=-1e10
        b=pv.select_counterfactuals(list(reversed(other)),920001,'normal','RANR-AW')
        self.assertEqual([(r['request_id'],r['sid']) for r in a],[(r['request_id'],r['sid']) for r in b])
        self.assertEqual(len(a),40)
        for r in other:r['horizon_end']=101
        self.assertEqual(pv.select_counterfactuals(other,920001,'normal','RANR-AW'),[])

    def test_mean_aggregation_is_pooled_as_registered(self):
        data=rows(30)
        for r in data:r.update(seed=920001,predicted_mean=20.)
        data+= [dict(rows(1)[0],seed=920002,predicted_mean=0.)]
        self.assertAlmostEqual(pv.metrics(data)['mean_bias'],290/31)

    @unittest.expectedFailure if not PATCHED else (lambda fn:fn)
    def test_cross_leg_event_must_not_be_joined_by_token_only(self):
        p=self.fixture([self.event('arrival',25,leg='1'),self.event('service_started',30,leg='2')],[self.rec()])
        with self.assertRaises(ValueError):pv.extract(p)

    @unittest.expectedFailure if not PATCHED else (lambda fn:fn)
    def test_paired_method_pinball_comparison_reports_cluster_ci(self):
        data=rows()+[dict(r,method='No-Prediction',predicted_p95=8.) for r in rows()]
        comparison=pv.summarize(data,[])['results']['normal']['pinball_comparison']
        self.assertIn('paired_episode_comparison',comparison)
        self.assertEqual(comparison['paired_episode_comparison']['paired_seed_count'],6)
        self.assertIn('CI95',comparison['paired_episode_comparison'])

    def test_missing_comparison_ci_cannot_grant_complete_predictive_pass(self):
        # Isolate the reporting prerequisite from point/stratum criteria.
        # A missing baseline must stay insufficient even if all those pass.
        with patch.object(pv,'assess',return_value=dict(status='PASS',metrics=dict(p95_pinball_loss=.1))):
            result=pv.summarize(rows(6),[])
        self.assertEqual(result['normal_status'],'INSUFFICIENT EVIDENCE')
        self.assertEqual(result['results']['normal']['comparative_reporting_status'],'INSUFFICIENT EVIDENCE')
        self.assertFalse(result['passed'])

    @unittest.expectedFailure if not PATCHED else (lambda fn:fn)
    def test_incomplete_charging_is_reported_separately_from_observed_wait(self):
        p=self.fixture([self.event('arrival',25),self.event('service_started',30)],[self.rec()])
        data,count=pv.extract(p)
        self.assertEqual(len(data),1)
        self.assertEqual(count['started_without_observed_completion'],1)

    def test_no_p2p_bias_age_null_directions(self):
        self.assertGreater((10*180/11)/15,1)
        rng=np.random.RandomState(42);theta=rng.randn(4,5)
        states=rng.rand(50,5);states[:,0]=1.;states[:,-1]=1.
        changed=theta.copy();changed[:,0]+=.7;changed[:,-1]-=.7
        np.testing.assert_allclose(states@theta.T,states@changed.T,atol=1e-14)

class PhysicalPayloadTests(unittest.TestCase):
    def fake_replay(self,waits,expected=None):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);p=Path(tmp.name)
        payload=dict(input_identity='synthetic',last_operation_min=10,seed=920001,
            operations=[dict(operation='arrival',identity=k) for k in ['probe','inserted_other','control_other']],
            expected_waits=expected or {'inserted_other':8.},comparisons=[dict(request_id='x',leg=1,
                branches={'0':['inserted_other'],'1':['control_other']})])
        (p/'input.json').write_text(json.dumps(payload))
        def engine(*args,**kwargs):
            (p/'output.json').write_text(json.dumps(dict(input_identity='synthetic',waits=waits)))
            Path(kwargs['resource_output']).write_text('{"synthetic_engineering_fixture":true}')
            return 'SYNTHETIC ENGINEERING ONLY; no GAMA execution'
        return p,engine

    def test_H_aggregation_excludes_probe_wait_and_keeps_signed_difference(self):
        p,engine=self.fake_replay({'probe':999.,'inserted_other':8.,'control_other':3.})
        with patch('ranr.gama.validation.run_model',side_effect=engine):
            proof=cf.execute(p/'input.json',p/'output.json',p/'proof.json')
        self.assertEqual(proof['rows'][0]['physical_H'],5.)
        self.assertEqual(proof['rows'][0]['inserted_others_wait'],8.)
        self.assertEqual(proof['compared_observed_jobs'],1)

    def test_fidelity_failure_rejects_H_before_acceptance(self):
        p,engine=self.fake_replay({'probe':0.,'inserted_other':18.,'control_other':3.})
        with patch('ranr.gama.validation.run_model',side_effect=engine):
            with self.assertRaisesRegex(ValueError,'fidelity'):cf.execute(p/'input.json',p/'output.json',p/'proof.json')
        self.assertFalse(json.loads((p/'proof.json').read_text())['passed'])

    def test_missing_replay_wait_is_rejected(self):
        p,engine=self.fake_replay({'probe':0.,'inserted_other':8.})
        with patch('ranr.gama.validation.run_model',side_effect=engine):
            with self.assertRaisesRegex(ValueError,'missing'):cf.execute(p/'input.json',p/'output.json',p/'proof.json')

    def test_payload_pairing_removes_only_probe_and_preserves_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);jobs={('a',1):dict(key='a:1',request_id='a',leg=1,token='ta',station=0,at=5.,order=1,energy=2.,soc=20.,max_kw=60.,expected_wait=0.,cancel=None),
                ('b',1):dict(key='b:1',request_id='b',leg=1,token='tb',station=0,at=6.,order=2,energy=3.,soc=30.,max_kw=60.,expected_wait=2.,cancel=dict(at=10.,order=3))}
            (p/'manifest.json').write_text('{}')
            loaded=(dict(config=dict(seed=920001,case='normal',method='RANR-AW',station_events='')),
                    dict(station_events='',charge_efficiency=.9,battery_capacity_kwh=60),jobs,
                    {0:dict(name='test',ports={'p':60})})
            probe=dict(request_id='a',leg=1,horizon_end=20.)
            with patch.object(cf,'load_episode',return_value=loaded):payload=cf.prepare(p,[probe],p/'input.json')
            arrivals=[r for r in payload['operations'] if r['operation']=='arrival']
            self.assertEqual(len(arrivals),3)
            self.assertEqual([r['energy'] for r in arrivals if r['station_index']==1],[3.])
            self.assertEqual(len(payload['comparisons'][0]['branches']['0']),1)
            self.assertEqual(len(payload['comparisons'][0]['branches']['1']),1)
            self.assertEqual(len(payload['expected_waits']),2)
            self.assertEqual([r['at'] for r in payload['operations']],sorted(r['at'] for r in payload['operations']))

