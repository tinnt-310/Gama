"""Scoped calibration import, execution binding and representative workload tests."""
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
import json
import sys
import os
import subprocess
import hashlib
import tempfile
import unittest
from unittest.mock import patch

from ranr.gama.calibration_import import SCOPE,source_changes,native_scope,verify_calibration_import
from ranr.gama.execution import assert_checkout_modules,verify_recorded_python
from ranr.gama.headless import RunConfig,validate_calibration_binding,provenance
from ranr.gama.benchmarking import concurrency_config


class ImportRejectionTests(unittest.TestCase):
    def test_algorithm_scope_rejects_population_and_accuracy_threshold_changes(self):
        import ranr.gama.calibration_import as adoption
        from ranr.paths import ROOT
        with tempfile.TemporaryDirectory() as temp:
            before=Path(temp)/'reference';current=Path(temp)/'current';hashes={}
            for name in ['training.py','benchmarking.py','headless.py','design.py']:
                relative='src/ranr/gama/'+name
                text=(ROOT/relative).read_text()
                for base in [before,current]:
                    p=base/relative;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
                if name=='training.py':
                    p=before/relative
                    p.write_text(text.replace('    from .execution import assert_checkout_modules\n    assert_checkout_modules()\n','',1))
                hashes[relative]=hashlib.sha256((before/relative).read_bytes()).hexdigest()
            registration=dict(source_checkout=str(before),source=dict(orchestrator=hashes))
            with patch.object(adoption,'ROOT',current):
                adoption.verify_algorithm_scope(registration)
                p=current/'src/ranr/gama/training.py';original=p.read_text()
                p.write_text(original.replace("'popsize':16","'popsize':8"))
                with self.assertRaisesRegex(ValueError,'Optimizer'):
                    adoption.verify_algorithm_scope(registration)
                p.write_text(original)
                p=current/'src/ranr/gama/benchmarking.py';p.write_text(p.read_text().replace('"mean": 1.0','"mean": 2.0',1))
                with self.assertRaisesRegex(ValueError,'scientific protocol'):
                    adoption.verify_algorithm_scope(registration)

    def test_old_physical_compatibility_rule_still_rejects_physics_delta(self):
        from ranr.gama.evidence import validate_compatibility_sources
        with self.assertRaisesRegex(ValueError,'Physical GAML'):
            validate_compatibility_sources({'gaml':{'models/ranr/Math.gaml':'old'}},
                {'gaml':{'models/ranr/Math.gaml':'new'}},{})

    def test_new_import_cannot_change_runtime_gis_or_scientific_inputs(self):
        for category in ['gis','configuration_fixtures','launcher','gama_config','python_version','dependencies','gama_bundles']:
            with self.subTest(category=category),self.assertRaises(ValueError):
                source_changes({category:{'value':'old'}},{category:{'value':'new'}})

    def test_finite_scope_checks_every_non_orchestration_category(self):
        source=provenance()
        native_scope(dict(passed=True,source=source),source)
        for category in source:
            if category=='orchestrator':continue
            changed={**source,category:'different'}
            with self.subTest(category=category),self.assertRaises(ValueError):
                native_scope(dict(passed=True,source=changed),source)

    def test_other_physics_or_optimizer_module_is_not_eligible(self):
        for category,path in [('gaml','models/ranr/Policy.gaml'),('orchestrator','src/ranr/gama/pipeline.py')]:
            with self.subTest(path=path),self.assertRaises(ValueError):
                source_changes({category:{path:'old'}},{category:{path:'new'}})

    def test_global_equivalence_or_gate_transfer_cannot_be_added_to_certificate(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'certificate.json'
            for field in ['global_source_equivalence','downstream_gate_transfer']:
                scope={**SCOPE,field:True}
                path.write_text(json.dumps(dict(kind='physics_calibration_import',passed=True,
                    source=provenance(),scope=scope)))
                with self.subTest(field=field),self.assertRaisesRegex(ValueError,'scope/seed'):
                    verify_calibration_import(path)

    def test_missing_certificate_never_adopts_old_calibration_or_rewrites_it(self):
        from ranr.gama.contracts import OBJECTIVE_CONFIG_HASH,OBJECTIVE_VERSION,OBSERVATION_VERSION
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'calibration.json'
            original=json.dumps(dict(source={'historical':True},environment_version=RunConfig(development=True).environment_version,
                objective_config_hash=OBJECTIVE_CONFIG_HASH,objective_version=OBJECTIVE_VERSION,
                observation_version=OBSERVATION_VERSION))
            path.write_text(original)
            with self.assertRaisesRegex(ValueError,'certificate required'):
                validate_calibration_binding(RunConfig(development=True,calibration=str(path)))
            self.assertEqual(path.read_text(),original)

    def test_certificate_without_calibration_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'requires its original calibration'):
            RunConfig(development=True,calibration_import_certificate='some.json')


class ActualExecutionTests(unittest.TestCase):
    def test_current_modules_bind_to_checkout(self):
        loaded=assert_checkout_modules()
        self.assertIn('ranr.gama.headless',loaded)

    def test_installed_module_outside_checkout_is_rejected(self):
        foreign=SimpleNamespace(__file__='/tmp/other-editable-install/ranr/physics.py')
        with patch.dict(sys.modules,{'ranr.foreign':foreign}):
            with self.assertRaisesRegex(ValueError,'checkout mismatch'):
                assert_checkout_modules()

    def test_recorded_identity_rejects_missing_or_stale_actual_modules(self):
        import ranr.gama.validation
        loaded=assert_checkout_modules();source=provenance()
        verify_recorded_python(loaded,source)
        with self.assertRaisesRegex(ValueError,'lacks actual Python'):
            verify_recorded_python({},source)
        stale={**loaded,'ranr.gama.validation':{**loaded['ranr.gama.validation'],'sha256':'stale'}}
        with self.assertRaisesRegex(ValueError,'identity changed'):
            verify_recorded_python(stale,source)

    def test_checked_bootstrap_overrides_editable_install_and_inherited_root(self):
        from ranr.paths import ROOT
        script=ROOT/'scripts/ranr_checked.py'
        code='''import sys,runpy
sys.argv=[sys.argv[1],"--help"]
try:runpy.run_path(sys.argv[0],run_name="__main__")
except SystemExit as e:
 if e.code not in (None,0):raise
import ranr.gama.cli
print("ACTUAL_CLI="+ranr.gama.cli.__file__)
'''
        env={**os.environ,'PYTHONPATH':'/tmp/foreign-editable-install','RANR_WORKSPACE':'/tmp/foreign-root'}
        result=subprocess.run([sys.executable,'-B','-c',code,str(script)],env=env,
            stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,check=True)
        self.assertIn('ACTUAL_CLI='+str(ROOT/'src/ranr/gama/cli.py'),result.stdout)


class RepresentativeWorkloadTests(unittest.TestCase):
    def test_complete_calibrated_profile_is_preserved_for_all_methods_and_scenarios(self):
        config=RunConfig(calibration='/registered/original/calibration.json',trace=True,samples=256)
        rows=[concurrency_config(config,i) for i in range(24)]
        self.assertEqual(len({(r.method,r.case) for r in rows}),24)
        for row in rows:
            for field,value in asdict(config).items():
                if field not in {'method','case','seed'}:
                    self.assertEqual(getattr(row,field),value)
            self.assertFalse(row.development)
            self.assertEqual((row.warmup_minutes,row.measure_minutes,row.deadline_minutes),(360,3600,360))


if __name__=='__main__':unittest.main()
