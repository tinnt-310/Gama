from pathlib import Path
import csv
import importlib.util
import json
import tempfile
import unittest
from unittest.mock import patch
import sys
sys.path.insert(0,str(Path(__file__).parent))
import mc_runtime as mc
from ranr.paths import write_json


class NativeShardTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        mc._STOP.clear()

    def table(self,path,rows):
        with path.open('w') as f:
            w=csv.DictWriter(f,fieldnames=mc.FIELDS);w.writeheader();w.writerows(rows)
    def row(self,**kwargs):
        return dict(method='No-P2P',station='7',probe='2',mean='0',p95='0',externality='0',queue_calls='1',**kwargs)

    def test_model_mechanical_derivation_changes_only_selectors(self):
        root=mc.ROOT
        original=(root/'models/tests/RanrPredictionBenchmark.gaml').read_text()
        selected=mc.selected_model(original,root)
        self.assertEqual(selected,mc.ensure_model().read_text())
        # Scientific inputs are preserved verbatim, including request key, full
        # sample variable, exposure loops, call to the native estimator and seed.
        for line in original.splitlines():
            if any(word in line for word in ['ranr_estimate(', '"key"::', '"exposure"', '"rates"', '"mean"]', '"p95"]', '"externality"]']):
                self.assertIn(line,selected)
        with self.assertRaises(ValueError):mc.selected_model(original.replace('    init {','    init CHANGED {'),root)

    def test_duplicate_and_missing_and_nan_rejected(self):
        p=self.root/'data.csv';key=('No-P2P','7','2')
        row=self.row();self.table(p,[row,row])
        with self.assertRaises(ValueError):mc.read_table(p,{key})
        self.table(p,[row])
        with self.assertRaises(ValueError):mc.read_table(p,{('No-P2P','7','3')})
        row['mean']='nan';self.table(p,[row])
        with self.assertRaises(ValueError):mc.read_table(p,{key})

    def test_metric_equivalence_excludes_diagnostic_counter_only(self):
        a={('No-P2P','7','2'):self.row()};b={k:dict(v) for k,v in a.items()}
        b[next(iter(b))]['queue_calls']='1000000'
        self.assertTrue(mc.semantic_equal(a,b))
        b[next(iter(b))]['mean']='0.01'
        self.assertFalse(mc.semantic_equal(a,b))

    def test_resume_checks_every_artifact_hash_and_identity(self):
        identity={'key':['No-P2P','7','2']};p=self.root/'probe.csv';self.table(p,[self.row()])
        write_json(self.root/'manifest.json',{'status':'complete','identity':identity,'artifacts':[mc.reference(p)]})
        self.assertEqual(mc.cached_job(self.root,identity)['method'],'No-P2P')
        with self.assertRaises(ValueError):mc.cached_job(self.root,{'key':['No-P2P','7','3']})
        p.write_text('corrupt')
        with self.assertRaises(ValueError):mc.cached_job(self.root,identity)

    def test_interrupted_probe_is_not_a_cached_completion(self):
        identity={'key':['No-P2P','7','2']}
        write_json(self.root/'manifest.json',{'status':'interrupted','identity':identity})
        self.assertIsNone(mc.cached_job(self.root,identity))

    def test_full_16384_count_and_seed_are_in_registration(self):
        with patch.object(mc,'provenance',return_value={'unit':True}),patch.object(mc,'digest',return_value='hash'),patch.object(mc,'ensure_model',return_value=self.root/'model'):
            identity=mc.shard_identity(self.root/'calibration',16384,('No-P2P','7','2'))
        self.assertEqual(identity['samples'],16384)
        self.assertEqual(identity['seed'],900001)
        self.assertTrue(identity['full_sample_count_per_probe'])

    def test_probe_failure_never_publishes_a_full_table(self):
        key=('No-P2P','7','2')
        with patch.object(mc,'provenance',return_value={}),patch.object(mc,'digest',return_value='unit'),patch.object(mc,'ensure_model',return_value=self.root/'model'),patch.object(mc,'shard_identity',return_value={'key':list(key)}),patch.object(mc,'cached_job',return_value=None),patch.object(mc,'compute_job',side_effect=RuntimeError('native failure')):
            with self.assertRaisesRegex(RuntimeError,'native failure'):
                mc.collect(self.root/'calibration',16384,self.root,1,[key])
        self.assertFalse((self.root/'probes_16384.csv').exists())
        state=json.loads((self.root/'native_shards/16384/progress.json').read_text())
        self.assertEqual(state['status'],'failed');self.assertEqual(state['completed_probes'],0)

if __name__=='__main__':unittest.main()

class ReferenceFailureProofTests(unittest.TestCase):
    def test_two_failures_cannot_short_circuit_three_can(self):
        keys=sorted(k for k in mc.benchmarking.PROBE_KEYS if k[0]=='No-P2P')[:3]
        low={key:dict(mean=0.,p95=0.,externality=0.) for key in mc.benchmarking.PROBE_KEYS}
        rows={key:dict(mean=1.,p95=0.,externality=0.) for key in keys[:2]}
        self.assertIsNone(mc.conclusive_reference_failure(rows,low))
        rows[keys[2]]=dict(mean=1.,p95=0.,externality=0.)
        proof=mc.conclusive_reference_failure(rows,low)
        self.assertEqual(proof['method'],'No-P2P')
        self.assertEqual(proof['maximum_pass_fraction'],52/55)
        self.assertLess(proof['maximum_pass_fraction'],.95)

    def test_reference_boundary_and_other_methods_do_not_inflate_failure_count(self):
        low={key:dict(mean=0.,p95=0.,externality=0.) for key in mc.benchmarking.PROBE_KEYS}
        rows={key:dict(mean=.5,p95=2.5,externality=2.5) for key in low}
        self.assertIsNone(mc.conclusive_reference_failure(rows,low))
        for method in mc.benchmarking.METHODS[:3]:
            key=next(k for k in low if k[0]==method);rows[key]['externality']=3.
        self.assertIsNone(mc.conclusive_reference_failure(rows,low))
