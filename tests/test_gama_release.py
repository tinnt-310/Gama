"""Release failures: selection, evidence, accuracy and budget boundaries."""
from dataclasses import asdict, replace
from pathlib import Path
import csv
import json
import os
import tempfile
import unittest
from unittest.mock import patch
from ranr.paths import write_json, digest
from ranr.gama.headless import RunConfig, METHODS
from ranr.gama.gui_collection import select_collections
from ranr.gama.benchmarking import PROBE_KEYS, probe_errors, _probes, physical_comparison
from ranr.gama.evidence import validate_compatibility_sources, read_evidence, reference
from ranr.gama.design import variants, unique_variants, freeze_design, checked_grid
from ranr.gama.training import train, training_limit
from ranr.gama.contracts import OBJECTIVE_CONFIG_HASH
from ranr.gama.replay import mismatch


class ReleaseContracts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def collection(self,seed,suffix,status='complete',finished=1):
        folder = self.root/'runs'/f'collect_{seed}_{suffix}'
        config = RunConfig(development=True,calibrating=True,trace=True,seed=seed)
        write_json(folder/'manifest.json',{'status':status,'source':{'unit':True},'config':asdict(config),'finished_at':finished})
        return folder

    def test_running_latest_and_mtime_cannot_hide_complete_run(self):
        expected = [self.collection(seed,'complete') for seed in (800001,800002,800003)]
        old = self.collection(800001,'old',finished=0)
        os.utime(old,(2000000000,2000000000))
        unfinished = self.collection(800001,'running',status='running',finished=99)
        with patch('ranr.gama.gui_collection.provenance',return_value={'unit':True}), patch('ranr.gama.evidence.validate_collection'):
            selected,report = select_collections(self.root)
        self.assertEqual(selected,expected)
        self.assertIn({'run':str(unfinished),'reason':'status_running'},report['skipped'])

    def test_corrupt_chosen_complete_run_never_falls_back(self):
        for seed in (800001,800002,800003): self.collection(seed,'older')
        latest = self.collection(800001,'newer',finished=2)
        with patch('ranr.gama.gui_collection.provenance',return_value={'unit':True}), patch('ranr.gama.evidence.validate_collection',side_effect=ValueError('artifact changed')) as check:
            with self.assertRaisesRegex(ValueError,'artifact changed'): select_collections(self.root)
        self.assertEqual(check.call_args.args[0],latest)
        self.assertEqual(check.call_count,1)

    def test_explicit_selection_requires_unique_registered_seeds(self):
        a = self.collection(800001,'one')
        with patch('ranr.gama.gui_collection.provenance',return_value={'unit':True}):
            with self.assertRaisesRegex(ValueError,'Duplicate'): select_collections(self.root,[a,a,a])
            with self.assertRaisesRegex(ValueError,'Missing'): select_collections(self.root,[a])

    def test_configuration_mismatch_across_collect_seeds_is_rejected(self):
        paths = [self.collection(seed,'one') for seed in (800001,800002,800003)]
        p = paths[-1]/'manifest.json';record=json.loads(p.read_text());record['config']['compliance']=.7;write_json(p,record)
        with patch('ranr.gama.gui_collection.provenance',return_value={'unit':True}):
            with self.assertRaisesRegex(ValueError,'configurations differ'): select_collections(self.root)

    def test_externality_error_alone_fails_accuracy_and_reference(self):
        exact = {k:dict(mean=0.,p95=0.,externality=0.) for k in PROBE_KEYS}
        wrong = {k:dict(mean=0.,p95=0.,externality=6.) for k in PROBE_KEYS}
        self.assertTrue(all(x['pass_fraction']==0 for x in probe_errors(wrong,exact).values()))
        borderline = {k:dict(mean=1.,p95=5.,externality=5.) for k in PROBE_KEYS}
        self.assertTrue(all(x['pass_fraction']==1 for x in probe_errors(borderline,exact).values()))
        self.assertTrue(all(x['pass_fraction']==0 for x in probe_errors(borderline,exact,.5).values()))

    def test_missing_or_nonfinite_probe_rejected(self):
        exact = {k:dict(mean=0.,p95=0.,externality=0.) for k in PROBE_KEYS}
        missing = dict(exact);missing.pop(next(iter(missing)))
        with self.assertRaises(ValueError):probe_errors(missing,exact)
        bad = {k:dict(mean=0.,p95=float('nan'),externality=0.) for k in PROBE_KEYS}
        with self.assertRaisesRegex(ValueError,'Nonfinite'):probe_errors(bad,exact)

    def test_duplicate_csv_probe_cannot_be_hidden_by_dict(self):
        path=self.root/'probes_32.csv'
        with path.open('w') as stream:
            writer=csv.writer(stream);writer.writerow(['method','station','probe','mean','p95','externality'])
            for key in sorted(PROBE_KEYS):writer.writerow([*key,0,0,0])
            writer.writerow([*next(iter(PROBE_KEYS)),0,0,0])
        with self.assertRaisesRegex(ValueError,'duplicate'):_probes('',self.root,32)

    def test_empty_physical_probe_is_informative_failure(self):
        row=dict(mean_travel_min=0.,mean_wait_min=None,p95_wait_min=None,intent_count=0,waiting_sample_count=0,
                 fitness_vector=[0.]*5,operational_objective=0.)
        result=physical_comparison(row,row)
        self.assertFalse(result['passed'])
        self.assertTrue(any('insufficient' in r for r in result['reasons']))

    def test_compatibility_cannot_change_physics_or_runtime(self):
        for category,name in [('gaml','models/main.gaml'),('orchestrator','src/ranr/gama/headless.py'),('orchestrator','src/ranr/gama/contracts.py')]:
            old={category:{name:'old'}};new={category:{name:'new'}}
            with self.assertRaises(ValueError):validate_compatibility_sources(old,new,{name:dict(old='old',new='new',rationale='cannot allow')})
        with self.assertRaises(ValueError):validate_compatibility_sources({'dependencies':{'cma':'old'}},{'dependencies':{'cma':'new'}},{})

    def test_compatibility_review_covers_exact_hashes(self):
        name='src/ranr/gama/gui_collection.py';old={'orchestrator':{name:'old'}};new={'orchestrator':{name:'new'}}
        with self.assertRaises(ValueError):validate_compatibility_sources(old,new,{})
        validate_compatibility_sources(old,new,{name:dict(old='old',new='new',rationale='Only selection; physical projection unchanged')})
        with self.assertRaises(ValueError):validate_compatibility_sources(old,new,{name:dict(old='wrong',new='new',rationale='changed')})

    def test_changed_linked_evidence_is_rejected(self):
        child=self.root/'child.json';write_json(child,{'passed':True})
        parent=self.root/'parent.json';write_json(parent,{'passed':True,'source':{'unit':True},'dependencies':[reference(child)]})
        with patch('ranr.gama.evidence.provenance',return_value={'unit':True}):
            read_evidence(parent)
            write_json(child,{'passed':False})
            with self.assertRaisesRegex(ValueError,'Evidence changed'):read_evidence(parent)

    def test_design_deduplicates_15_names_into_12_physical_configs(self):
        settings=variants(RunConfig(development=True))
        unique,aliases=unique_variants(settings)
        self.assertEqual((len(settings),len(unique)),(15,12))
        for name in ('temperature_0.2','heartbeat_5.0','behavior_moderate'):self.assertEqual(aliases[name],'control')

    def test_boolean_only_freeze_has_no_evidence(self):
        write_json(self.root/'review.json',{'complete':True,'source':{'unit':True},'design_wall_seconds':0})
        decision=self.root/'decision.json';write_json(decision,{'selected_config':dict(temperature=.2,p2p_interval=5.,stabilization='off'),
            'objective_config_hash':OBJECTIVE_CONFIG_HASH,'review_sha256':digest(self.root/'review.json'),
            **{key:True for key in ('calibration_passed','information_passed','exposure_passed','objective_sensitivity_passed','design_validation_passed')}})
        with patch('ranr.gama.design.provenance',return_value={'unit':True}):
            with self.assertRaises((ValueError,FileNotFoundError)):freeze_design(self.root,decision)

    def test_duplicate_design_rows_cannot_replace_missing_runs(self):
        row=dict(case='normal',seed=24001,method='RANR-AW')
        write_json(self.root/'results.json',[row]*72)
        with self.assertRaisesRegex(ValueError,'duplicate'):checked_grid(self.root,RunConfig(development=True),{})

    def test_training_budget_is_separate_and_finite(self):
        self.assertEqual(training_limit({'hours':72,'design_wall_seconds':99999999}),72*3600)
        for hours in (0,73,float('nan'),float('inf')):
            with self.assertRaises(ValueError):training_limit({'hours':hours})

    def test_timeout_retains_pending_population_without_tell(self):
        budget=self.root/'budget.json'
        write_json(budget,dict(hours=1,workers=1,optimizer_seeds=[49001],budget=dict(max_evaluations=16,min_evaluations=16,validation_every=16)))
        now=[0.]
        def expired(*args,**kwargs):
            now[0]=3601.
            raise TimeoutError('budget ended')
        with patch('ranr.gama.training.time.monotonic',side_effect=lambda:now[0]), patch('ranr.gama.training.run',side_effect=expired), patch('ranr.gama.training.cma.CMAEvolutionStrategy.tell',autospec=True) as tell:
            result=train(RunConfig(development=True),self.root/'train',budget,smoke=True)
        self.assertEqual(result['status'],'budget_limited');tell.assert_not_called()
        import pickle
        state=pickle.loads((self.root/'train/checkpoint.pkl').read_bytes())
        self.assertIsNotNone(state['slots'][0]['pending'])
        self.assertEqual(state['slots'][0]['evaluations'],0)

    def test_replay_ignores_machine_time_but_detects_changed_port(self):
        self.assertIsNone(mismatch({'run_id':'one','cost_ms':1,'port_id':2},{'run_id':'two','cost_ms':99,'port_id':2}))
        self.assertIsNotNone(mismatch({'port_id':2},{'port_id':3}))
        self.assertIsNotNone(mismatch({'soc':50.},{'soc':50.1}))

    def test_failed_release_stage_never_starts_replay_or_training(self):
        from ranr.gama import release
        write_json(self.root/'registration.json',{'source':{'unit':True}})
        write_json(self.root/'state.json',{'stages':{}})
        class Failed:
            def wait(self,timeout=None):return 2
            def poll(self):return 2
        with patch.object(release,'ROOT',self.root), patch.object(release,'provenance',return_value={'unit':True}), patch.object(release.subprocess,'Popen',return_value=Failed()) as launch:
            with self.assertRaisesRegex(RuntimeError,'python_tests'):release.execute(self.root)
        self.assertEqual(launch.call_count,1)
        state=json.loads((self.root/'state.json').read_text())
        self.assertEqual(state['status'],'needs_attention')
        self.assertNotIn('training',state['stages'])

    def test_completed_release_stage_with_changed_artifact_is_rejected(self):
        from ranr.gama import release
        p=self.root/'sealed.json';write_json(p,{'passed':True})
        write_json(self.root/'registration.json',{'source':{'unit':True}})
        write_json(self.root/'state.json',{'stages':{'python_tests':{'status':'complete','artifacts':[reference(p)]}}})
        write_json(p,{'passed':False})
        with patch.object(release,'provenance',return_value={'unit':True}), patch.object(release.subprocess,'Popen') as launch:
            with self.assertRaisesRegex(ValueError,'evidence changed'):release.execute(self.root)
        launch.assert_not_called()

    def test_evaluation_requires_720_unique_paired_runs(self):
        from ranr.gama.evaluation import check_evaluation_grid, EVALUATION_SEEDS
        from ranr.gama.headless import CASES
        from gama_ledger_fixture import fitness_fixture
        rows=[fitness_fixture(case=case,seed=seed,method=method) for case in CASES for seed in EVALUATION_SEEDS for method in METHODS]
        check_evaluation_grid(rows)
        for invalid in (rows[:-1],rows[:-1]+[rows[0]]):
            with self.assertRaisesRegex(ValueError,'720 unique'):check_evaluation_grid(invalid)
        rows[0]['planned_ev_days']*=2
        rows[0]['fitness_vector']=[0.]*5
        with self.assertRaises(ValueError):check_evaluation_grid(rows)

    def test_model_or_config_change_cannot_overwrite_evaluation_registration(self):
        from ranr.gama.evaluation import evaluate_models
        models=self.root/'models';folder=self.root/'evaluation'
        calibration=self.root/'calibration.json';write_json(calibration,{})
        config=RunConfig(calibration=str(calibration))
        write_json(models/'registration.json',{'status':'complete','profile':'research','source':{'unit':True}})
        for method in METHODS:write_json(models/method/'parameters.json',{'unit':True})
        write_json(folder/'registration.json',{'source':{'previous':True},'status':'complete'})
        before=(folder/'registration.json').read_bytes()
        with patch('ranr.gama.evaluation.provenance',return_value={'unit':True}), patch('ranr.gama.evaluation.load_model',return_value=[0.]*20), patch('ranr.gama.evaluation.jobs') as jobs:
            with self.assertRaisesRegex(ValueError,'changed'):evaluate_models(config,models,folder)
        jobs.assert_not_called()
        self.assertEqual(before,(folder/'registration.json').read_bytes())
