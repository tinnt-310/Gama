"""Real CMA/checkpoint orchestration with explicitly SYNTHETIC result ledgers."""
from contextlib import ExitStack
from dataclasses import asdict
import hashlib
import fcntl
import json
from pathlib import Path
import pickle
import signal
import tempfile
import unittest
import os
import importlib.util
from unittest.mock import patch
import numpy as np
import cma
from ranr.gama import training as tr,training_time as tt,headless as hd,monitoring as mon
from ranr.gama.contracts import OBJECTIVE_VERSION,OBJECTIVE_CONFIG_HASH
from ranr.paths import write_json,digest
import strict_fitness_boundary as f04

SOURCE={'synthetic_engineering_fixture':True}
PATCHED=True
def fp(value):return hashlib.sha256(pickle.dumps(value,protocol=5)).hexdigest()

class OptimizerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.out=self.base/'optimizer';self.budget=self.base/'budget.json'
        self.budget.write_text(json.dumps(dict(hours=.1,workers=1,optimizer_seeds=[49001],
            budget=dict(max_evaluations=16,min_evaluations=16,validation_every=16))))
        self.config=hd.RunConfig(development=True)
        self.events=[];self.new=[];self.reused=[];self.interrupt_at=None;self.reject_stage=None
        self.interrupt_validation=False
        stack=ExitStack();self.addCleanup(stack.close)
        stack.enter_context(patch.object(tr,'provenance',return_value=SOURCE))
        stack.enter_context(patch.object(f04,'provenance',return_value=SOURCE))
        stack.enter_context(patch.object(f04,'validate_charging_files',side_effect=self.validate))
        stack.enter_context(patch.object(f04,'validate_physical_records',return_value={'synthetic_fixture':True}))
        stack.enter_context(patch.object(tr,'run',f04.StrictNativeRunner(self.native,self.out,SOURCE)))
        original=cma.CMAEvolutionStrategy.tell
        def tell(opt,*a,**kw):
            self.events.append('tell');return original(opt,*a,**kw)
        stack.enter_context(patch.object(cma.CMAEvolutionStrategy,'tell',tell))
        mon.TRAINING_CANCEL.clear()

    def validate(self,path):
        self.events.append('F04:'+('validation' if 'validation' in Path(path).parts else 'candidate'))
        if self.reject_stage and self.reject_stage in Path(path).parts:raise ValueError('Synthetic F04 rejection')

    def native(self,config,theta,folder,**kw):
        folder=Path(folder)
        expected=dict(source=SOURCE,config=asdict(config),parameters=hd.parameter_record(config.method,theta))
        if folder.exists():
            self.reused.append(folder);return hd.checked_result(folder,expected)
        if self.interrupt_at is not None and len(self.new)==self.interrupt_at:
            raise InterruptedError('Synthetic interruption boundary')
        if self.interrupt_validation and 'validation' in folder.parts and any('validation' in p.parts for p in self.new):
            raise InterruptedError('Synthetic partial fixed-validation interruption')
        folder.mkdir(parents=True)
        objective=float(np.mean(np.square(theta)))+.1
        metrics=dict(objective_version=OBJECTIVE_VERSION,objective_config_hash=OBJECTIVE_CONFIG_HASH,
            fitness_valid=True,fitness_vector=[0.,0.,0.,0.,objective],operational_objective=objective,
            planned_ev_days=1.,stranded_vehicle_count=0,mobility_unserved_count=0,not_on_time_count=0,
            unmet_kwh=0.,exogenous_hash=f'{config.case}:{config.seed}',synthetic_engineering_fixture=True)
        write_json(folder/'metrics.json',metrics)
        write_json(folder/'manifest.json',dict(**expected,status='complete',
            artifact_hashes={'metrics.json':digest(folder/'metrics.json')},synthetic_engineering_fixture=True))
        self.new.append(folder);self.events.append('native');return metrics

    def run_train(self,resume=False):return tr.train(self.config,self.out,self.budget,resume=resume,smoke=True)
    def checkpoint(self):return pickle.loads((self.out/'checkpoint.pkl').read_bytes())

    def test_full_real_cma_ask_evaluate_tell_and_fixed_validation(self):
        self.assertEqual(self.run_train()['status'],'complete')
        state=self.checkpoint();self.assertEqual(len(self.new),408)
        self.assertEqual(self.events.count('tell'),4)
        self.assertEqual(sum(e=='F04:candidate' for e in self.events),384)
        self.assertEqual(sum(e=='F04:validation' for e in self.events),24)
        self.assertGreater(self.events.index('tell'),self.events.index('F04:candidate'))
        for slot in state['slots']:
            self.assertEqual(slot['evaluations'],16);self.assertEqual(slot['generation'],1)
            self.assertIsNone(slot['pending']);self.assertIsNone(slot['pending_validation'])
            self.assertEqual(slot['optimizer'].countiter,1)
            self.assertEqual(len(slot['history']),1)
        for method in hd.METHODS:
            p=json.loads((self.out/method/'parameters.json').read_text())
            self.assertEqual(p['profile'],'smoke');self.assertFalse(p['training_completed'])

    def test_candidate_f04_reject_never_reaches_tell(self):
        self.reject_stage='candidates'
        with self.assertRaisesRegex(ValueError,'F04 rejection'):self.run_train()
        state=self.checkpoint();self.assertEqual(state['status'],'invalid_evaluation')
        self.assertNotIn('tell',self.events);self.assertIsNotNone(state['slots'][0]['pending'])

    def test_fixed_validation_f04_reject_cannot_publish(self):
        self.reject_stage='validation'
        with self.assertRaisesRegex(ValueError,'F04 rejection'):self.run_train()
        state=self.checkpoint();self.assertEqual(state['status'],'invalid_evaluation')
        # Canonical loop evaluates one generation for each method before it
        # returns to the first slot's fixed validation.
        self.assertEqual(self.events.count('tell'),4)
        self.assertIsNotNone(state['slots'][0]['pending_validation'])
        self.assertFalse((self.out/'RANR-AW/parameters.json').exists())

    def test_interruption_pending_rng_and_completed_hash_reuse(self):
        self.interrupt_at=1
        with self.assertRaises(InterruptedError):self.run_train()
        state=self.checkpoint();slot=state['slots'][0]
        pending=fp(slot['pending']);rng=fp(slot['rng'])
        self.assertEqual(slot['evaluations'],0);self.assertEqual(slot['generation'],0)
        first=self.new[0]/'manifest.json';sealed=digest(first)
        journal=json.loads((self.out/'training_time.json').read_text())
        self.assertFalse(journal['active']);self.assertGreaterEqual(journal['consumed_seconds'],state['active_seconds'])
        self.interrupt_at=1
        with self.assertRaises(InterruptedError):self.run_train(resume=True)
        again=self.checkpoint()['slots'][0]
        self.assertEqual(fp(again['pending']),pending);self.assertEqual(fp(again['rng']),rng)
        self.assertEqual(digest(first),sealed);self.assertEqual(len(self.new),1)
        self.assertGreaterEqual(self.checkpoint()['active_seconds'],state['active_seconds'])
        self.interrupt_at=None;self.assertEqual(self.run_train(resume=True)['status'],'complete')
        self.assertEqual(len(self.new),408);self.assertEqual(digest(first),sealed)
        self.assertGreaterEqual(len(self.reused),2)

    @unittest.expectedFailure if not PATCHED else (lambda fn:fn)
    def test_resume_matches_uninterrupted_parameters_and_rng_for_all_methods(self):
        self.interrupt_at=1
        with self.assertRaises(InterruptedError):self.run_train()
        self.interrupt_at=None;self.run_train(resume=True)
        resumed=self.checkpoint()
        self.out=self.base/'uninterrupted_reference'/'optimizer'
        with patch.object(tr,'run',f04.StrictNativeRunner(self.native,self.out,SOURCE)):
            self.run_train()
        uninterrupted=self.checkpoint()
        comparison=[dict(method=a['method'],parameters_equal=a['best_parameters']==b['best_parameters'],
            best_vector_equal=a['best_vector']==b['best_vector'],rng_equal=fp(a['rng'])==fp(b['rng']),
            optimizer_mean_equal=bool(np.array_equal(a['optimizer'].mean,b['optimizer'].mean)))
            for a,b in zip(resumed['slots'],uninterrupted['slots'])]
        suffix='_candidate' if PATCHED else ''
        (Path(os.environ['RECOVERY_TEST_OUTPUT'])/('rng_comparison'+suffix+'.json')).write_text(json.dumps(comparison,indent=2)+'\n')
        self.assertTrue(all(all(v for k,v in row.items() if k!='method') for row in comparison),comparison)

    def test_existing_optimizer_lock_refuses_duplicate_trainer(self):
        self.out.mkdir()
        with (self.out/'.lock').open('a') as owner:
            fcntl.flock(owner,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):self.run_train()
        self.assertFalse((self.out/'checkpoint.pkl').exists())

    def test_registered_three_seeds_two_generations_candidate_and_validation_resume(self):
        spec=json.loads(self.budget.read_text())
        spec.update(optimizer_seeds=[41001,41002,41003])
        spec['budget'].update(max_evaluations=32,min_evaluations=32,validation_every=16)
        self.budget.write_text(json.dumps(spec));self.interrupt_at=386
        with self.assertRaises(InterruptedError):self.run_train()
        first=self.checkpoint()
        self.assertEqual(len(first['slots']),12)
        self.assertTrue(any(s['pending_validation'] is not None for s in first['slots']))
        self.assertTrue(any(s['pending'] is not None for s in first['slots']))
        sealed={str(p/'manifest.json'):digest(p/'manifest.json') for p in self.new}
        self.interrupt_at=None;self.interrupt_validation=True
        with self.assertRaisesRegex(InterruptedError,'fixed-validation'):self.run_train(resume=True)
        mid=self.checkpoint()
        self.assertIsNotNone(mid['slots'][0]['pending_validation'])
        self.assertGreaterEqual(mid['active_seconds'],first['active_seconds'])
        self.interrupt_validation=False;self.run_train(resume=True)
        resumed=self.checkpoint()
        self.assertEqual(len(self.new),2448)
        for p,h in sealed.items():self.assertEqual(digest(Path(p)),h)
        self.out=self.base/'multi_seed_uninterrupted'/'optimizer'
        with patch.object(tr,'run',f04.StrictNativeRunner(self.native,self.out,SOURCE)):self.run_train()
        continuous=self.checkpoint()
        comparisons=[]
        for a,b in zip(resumed['slots'],continuous['slots']):
            same=(a['best_parameters']==b['best_parameters'] and a['best_vector']==b['best_vector']
                and fp(a['rng'])==fp(b['rng']) and np.array_equal(a['optimizer'].mean,b['optimizer'].mean))
            self.assertTrue(same,(a['method'],a['seed']))
            self.assertEqual(a['generation'],2);self.assertEqual(a['evaluations'],32)
            comparisons.append(dict(method=a['method'],seed=a['seed'],generations=2,
                continuous_resume_equal=bool(same),candidate_and_validation_interruption=True))
        (Path(os.environ['RECOVERY_TEST_OUTPUT'])/'multi_seed_rng.json').write_text(json.dumps(comparisons,indent=2)+'\n')

    def test_completed_config_identity_tamper_blocks_resume(self):
        self.interrupt_at=1
        with self.assertRaises(InterruptedError):self.run_train()
        path=self.new[0]/'manifest.json';record=json.loads(path.read_text())
        record['config']['seed']+=1;path.write_text(json.dumps(record))
        self.interrupt_at=None
        with self.assertRaisesRegex(ValueError,'registration changed'):self.run_train(resume=True)
        self.assertNotIn('tell',self.events)

    def test_completed_metric_tamper_blocks_resume_before_tell(self):
        self.interrupt_at=1
        with self.assertRaises(InterruptedError):self.run_train()
        (self.new[0]/'metrics.json').write_text('{}')
        self.interrupt_at=None
        with self.assertRaisesRegex(ValueError,'artifact changed'):self.run_train(resume=True)
        self.assertNotIn('tell',self.events)

    def test_corrupted_budget_identity_cannot_resume(self):
        self.interrupt_at=0
        with self.assertRaises(InterruptedError):self.run_train()
        d=json.loads(self.budget.read_text());d['hours']=.2;self.budget.write_text(json.dumps(d))
        with self.assertRaisesRegex(ValueError,'registration changed'):self.run_train(resume=True)

    @unittest.expectedFailure if not PATCHED else (lambda fn:fn)
    def test_missing_durable_journal_must_not_resume_from_checkpoint_alone(self):
        self.interrupt_at=0
        with self.assertRaises(InterruptedError):self.run_train()
        (self.out/'training_time.json').unlink();self.interrupt_at=None
        with self.assertRaisesRegex(ValueError,'journal'):self.run_train(resume=True)

class ClockTests(unittest.TestCase):
    def folder(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);return Path(t.name)

    def test_real_sigterm_handler_only_targets_this_isolated_test(self):
        p=self.folder();clock=tt.TrainingClock(p,{'synthetic':True},0,10)
        with tt.elapsed_guard(clock):
            signal.raise_signal(signal.SIGTERM)
            with self.assertRaises(InterruptedError):mon.check_training_cancelled()
        self.assertFalse(json.loads((p/'training_time.json').read_text())['active'])
        self.assertFalse(mon.TRAINING_CANCEL.is_set())

    def test_stale_checkpoint_clock_floor_and_live_owner_rejected(self):
        p=self.folder();clock=tt.TrainingClock(p,{'synthetic':True},10,100);clock.pulse(active=False)
        resumed=tt.TrainingClock(p,{'synthetic':True},0,100)
        self.assertGreaterEqual(resumed.initial,10)
        resumed.pulse(active=True)
        with self.assertRaisesRegex(ValueError,'live owner'):tt.TrainingClock(p,{'synthetic':True},0,100)

    def test_unclean_death_reserve_and_reboot_exhaustion(self):
        p=self.folder();clock=tt.TrainingClock(p,{'synthetic':True},10,100);clock.pulse()
        with patch.object(tt,'still_alive',return_value=False):
            same=tt.TrainingClock(p,{'synthetic':True},0,100)
        self.assertGreaterEqual(same.initial,10)
        d=json.loads((p/'training_time.json').read_text());d['owner']['boot_id']='other-boot'
        (p/'training_time.json').write_text(json.dumps(d))
        with patch.object(tt,'still_alive',return_value=False):
            reboot=tt.TrainingClock(p,{'synthetic':True},0,100)
        self.assertGreaterEqual(reboot.initial,100)

    def test_atomic_checkpoint_failure_leaves_previous_loadable(self):
        p=self.folder()/'checkpoint.pkl';tr._save(p,{'old':True})
        with patch.object(tt.os,'replace',side_effect=OSError('synthetic crash before rename')):
            with self.assertRaises(OSError):tr._save(p,{'new':True})
        self.assertEqual(pickle.loads(p.read_bytes()),{'old':True})

