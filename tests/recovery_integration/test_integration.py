"""Compatibility, actual legacy launch guard and passive ownership tests."""
import ast
import copy
import importlib.util
import json
from pathlib import Path
import pickle
import tempfile
import unittest
from unittest.mock import patch,Mock
from ranr.gama import recovery_transition as rt,evidence,headless
from ranr.paths import ROOT,write_json,digest
from reboot_recovery import eligible
import native_rng_reference

PIPELINE=ROOT/'scripts/recovery_pipeline'
BASE=ROOT.parent.parent
spec=importlib.util.spec_from_file_location('recovery_controller',PIPELINE/'controller.py')
controller=importlib.util.module_from_spec(spec);spec.loader.exec_module(controller)

class IntegrationTests(unittest.TestCase):
    def temp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);return Path(t.name)

    def test_exact_scoped_source_delta_is_accepted(self):
        parent=json.loads((BASE/'heap8_revalidation_20261027/registration.json').read_text())['source']
        changed=rt.source_scope(parent,headless.provenance(),BASE/'calibration_source')
        self.assertEqual(set(Path(p).name for p in changed),rt.ALLOWED)

    def test_changed_physics_runtime_or_objective_cannot_be_inherited(self):
        parent=json.loads((BASE/'heap8_revalidation_20261027/registration.json').read_text())['source']
        for category in ['gaml','gis','configuration_fixtures','launcher','gama_bundles']:
            current=copy.deepcopy(headless.provenance());current[category]['unexpected']='changed'
            with self.subTest(category=category),self.assertRaisesRegex(ValueError,'cannot change'):
                rt.source_scope(parent,current,BASE/'calibration_source')

    def test_old_calibration_certificate_does_not_silently_cover_new_optimizer(self):
        from ranr.gama.calibration_import import verify_record
        original=json.loads((BASE/'calibration_import_20261026/certificate.json').read_text())
        with self.assertRaisesRegex(ValueError,'Current-source'):verify_record(original)

    def test_thirteen_nominal_gates_cannot_bypass_recovery_blocker(self):
        source=headless.provenance()
        gate_refs={k:dict(path=k,sha256='synthetic') for k in evidence.PRE_TRAINING_GATES}
        proof=dict(kind='pre_training_acceptance',passed=True,source=source,gates=gate_refs)
        def read(path):
            return proof if str(path)=='synthetic_pretraining' else dict(kind=str(path),passed=True,source=source)
        with patch.object(evidence,'read_evidence',side_effect=read),patch.object(evidence,'verify_reference',side_effect=lambda p:p['path']),patch.object(evidence,'verify_native'):
            with self.assertRaisesRegex(ValueError,'official training BLOCKED'):
                evidence.verify_training_acceptance('synthetic_pretraining')

    def test_current_legacy_release_function_rejects_actual_marker_mechanism(self):
        original=BASE/'heap8_revalidation_20261027/controller.py'
        tree=ast.parse(original.read_text());fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='release_hold')
        temp=self.temp();guard=temp/'reserved';guard.mkdir()
        marker=guard/'PR01_PR05_INTEGRATION_PENDING.json';marker.write_text('{}')
        write_json(temp/'TRAINING_LAUNCH_HOLD.json',dict(guard_path=str(guard)))
        write_json(temp/'benchmark/budget.json',dict(workers=1))
        write=Mock(side_effect=AssertionError('Occupied reservation must not reach release write'))
        def require(value,message):
            if not value:raise ValueError(message)
        ns=dict(ROOT=temp,BASE=temp,OUTPUT=temp,check=lambda r:None,
            verify_training_acceptance=lambda p:dict(source='fixture'),original_busy=lambda s:False,
            ownership_snapshot=lambda:{},capacity=lambda n:None,load=lambda p:json.loads(Path(p).read_text()),
            require=require,Path=Path,write_json=write)
        exec(compile(ast.Module(body=[fn],type_ignores=[]),str(original),'exec'),ns)
        inode=guard.stat().st_ino
        with self.assertRaisesRegex(ValueError,'Reserved guard contains data'):
            ns['release_hold'](dict(source='fixture',hold_inode=inode))
        self.assertTrue(marker.exists());self.assertEqual(guard.stat().st_ino,inode);write.assert_not_called()

    def test_active_parent_or_children_prevents_successor_ownership(self):
        for services,owners in [({'main':dict(ActiveState='active',MainPID='1')},[]),
                                ({'main':dict(ActiveState='inactive',MainPID='0')},[dict(pid=1)])]:
            snapshot=dict(services=services,live_owned_processes=owners,competing=[])
            self.assertTrue(controller.original_busy(snapshot))
            with self.assertRaisesRegex(ValueError,'still active'):controller.verify_original_boundary(snapshot)

    def test_intermediate_mc_instability_is_not_a_final_scientific_failure(self):
        temp=self.temp()
        with patch.object(controller,'PARENT',temp):
            self.assertIsNone(controller.check_scientific_stop(dict(parent=dict(status='running',stage='accuracy'))))

    def test_scientific_failure_cannot_be_retried_as_source_adoption(self):
        temp=self.temp();write_json(temp/'predictive/acceptance.json',dict(passed=False,status='INSUFFICIENT EVIDENCE'))
        with patch.object(controller,'PARENT',temp):
            with self.assertRaisesRegex(ValueError,'cannot retry'):
                controller.check_scientific_stop(dict(parent=dict(status='failed')))

    def test_reboot_recovery_requires_boot_change_accuracy_and_no_live_owner(self):
        reg=dict(registered_boot_id='old');snapshot=dict(parent=dict(status='running',stage='accuracy'),
            live_owned_processes=[],competing=[],services={'main':dict(MainPID='0',ActiveState='inactive')})
        self.assertTrue(eligible(reg,snapshot,'new'));self.assertFalse(eligible(reg,snapshot,'old'))
        bad=copy.deepcopy(snapshot);bad['parent']['status']='failed';self.assertFalse(eligible(reg,bad,'new'))
        bad=copy.deepcopy(snapshot);bad['live_owned_processes']=[{'pid':1}];self.assertFalse(eligible(reg,bad,'new'))
        bad=copy.deepcopy(snapshot);bad['parent']['stage']='smoke';self.assertFalse(eligible(reg,bad,'new'))

    def test_native_rng_proof_refuses_synthetic_native_looking_fitness(self):
        temp=self.temp();native=temp/'optimizer';native.mkdir()
        source=headless.provenance()
        (native/'checkpoint.pkl').write_bytes(pickle.dumps(dict(status='complete',registration=dict(source=source))))
        write_json(native/'training_time.json',dict(consumed_seconds=1.,active=False))
        for method in headless.METHODS:
            for candidate in range(16):
                for case in headless.CASES:write_json(native/method/'49001/candidates/0'/str(candidate)/case/'manifest.json',dict(source=source,backend='GAMA',synthetic_engineering_fixture=True))
            for case in headless.CASES:write_json(native/method/'49001/validation/16'/case/'manifest.json',dict(source=source,backend='GAMA',synthetic_engineering_fixture=True))
        budget=temp/'budget.json';write_json(budget,dict(hours=6))
        with patch('ranr.gama.training.train',side_effect=AssertionError('Synthetic result must be refused before optimizer reference')):
            with self.assertRaisesRegex(ValueError,'synthetic/historical'):
                native_rng_reference.execute(headless.RunConfig(development=True),temp,native,budget,temp/'unused_model')

    def test_native_reference_grid_excludes_archived_interrupted_rollouts(self):
        temp=self.temp()
        valid=temp/'RANR-AW/49001/candidates/0/0/normal/manifest.json'
        archived=temp/'RANR-AW/49001/candidates/0/0/_incomplete/normal_123/manifest.json'
        validation=temp/'RANR-AW/49001/validation/16/normal/manifest.json'
        for path in [valid,archived,validation]:write_json(path,{'synthetic_selector_fixture':True})
        self.assertEqual(native_rng_reference.completed_grid(temp),[valid,validation])

    def adoption_fixture(self,phase='predictive'):
        temp=self.temp();source=temp/'reviewer/source'
        original=temp/'heap8_revalidation_20261027'/phase/'runs/case/1/method'
        target=temp/'reviewer/predictive/runs/case/1/method'
        original.mkdir(parents=True);target.mkdir(parents=True)
        cert=temp/'reviewer/certificate.json';cert.write_text('{"synthetic_scope_test":true}')
        config=dict(seed=1,case='normal',calibration_import_certificate='old_certificate')
        write_json(original/'metrics.json',dict(mock_metrics=True))
        manifest=dict(status='complete',source={'old':True},backend='GAMA',config=config,
            parameters={'theta':[0]},calibration_sha256='calibration',artifact_hashes={'metrics.json':digest(original/'metrics.json')})
        write_json(original/'manifest.json',manifest)
        (target/'metrics.json').symlink_to(original/'metrics.json')
        record={**manifest,'kind':'scoped_native_result_review','source':{'new':True},
            'execution_source':{'old':True},'adoption_scope':'pretraining_simulation_only',
            'config':{**config,'calibration_import_certificate':str(cert)},
            'source_transition':dict(path=str(cert),sha256=digest(cert)),
            'calibration_import_sha256':digest(cert),
            'original_manifest':dict(path=str(original/'manifest.json'),sha256=digest(original/'manifest.json'))}
        proof=dict(source={'new':True},parent_source={'old':True},calibration=dict(sha256='calibration'))
        return source,original,target,record,proof

    def test_scoped_adoption_preserves_old_execution_and_metrics(self):
        source,old,target,record,proof=self.adoption_fixture()
        original=(old/'manifest.json').read_bytes()
        with patch.object(rt,'ROOT',source),patch.object(rt,'verify_certificate',return_value=proof),patch('ranr.gama.contracts.validate_fitness') as check:
            result=rt.checked_adopted_result(target,{'source':{'new':True}},record)
        self.assertEqual(result,{'mock_metrics':True});check.assert_called_once()
        self.assertEqual((old/'manifest.json').read_bytes(),original)

    def test_adoption_rejects_changed_seed_and_artifact(self):
        source,old,target,record,proof=self.adoption_fixture()
        with patch.object(rt,'ROOT',source),patch.object(rt,'verify_certificate',return_value=proof):
            changed=copy.deepcopy(record);changed['config']['seed']=2
            with self.assertRaisesRegex(ValueError,'Physical inputs'):rt.checked_adopted_result(target,{},changed)
            (old/'metrics.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'artifact changed'):rt.checked_adopted_result(target,{},record)

    def test_adoption_never_transfers_optimizer_smoke_or_benchmark_timings(self):
        for phase in ['native_smoke','official_training','benchmark/performance']:
            source,old,target,record,proof=self.adoption_fixture(phase)
            with patch.object(rt,'ROOT',source),patch.object(rt,'verify_certificate',return_value=proof):
                with self.assertRaisesRegex(ValueError,'transfer forbidden'):rt.checked_adopted_result(target,{},record)

