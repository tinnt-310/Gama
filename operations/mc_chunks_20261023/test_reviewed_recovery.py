from pathlib import Path
from unittest.mock import patch
import tempfile,unittest,importlib.util
spec=importlib.util.spec_from_file_location('recovery_watchdog',Path(__file__).with_name('watchdog_recovery_guard.py'))
watchdog=importlib.util.module_from_spec(spec);spec.loader.exec_module(watchdog)
from ranr.paths import write_json
class ReviewedRecoveryTests(unittest.TestCase):
 def fixture(self,root):
  write_json(root/'state.json',{'status':'needs_attention','current_stage':'accuracy','error':'fixture infrastructure failure'})
  proof=root/'diagnostic.log';proof.write_text('fixture: reviewed temporary infrastructure failure')
  return {'kind':'temporary_infrastructure_recovery','source':{'fixture':True},'state_sha256':watchdog.mc_runtime.digest(root/'state.json'),'reason':'unit fixture review','dependencies':[watchdog.mc_runtime.reference(proof)]}
 def test_unreviewed_failure_does_not_restart_on_login(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);self.fixture(root)
   self.assertIn('Unreviewed',watchdog.scientific_block(root))
 def test_bound_infrastructure_review_is_consumed_once(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);review=self.fixture(root);write_json(root/'infra_retry_review.json',review)
   with patch.object(watchdog.mc_runtime,'provenance',return_value={'fixture':True}):self.assertIsNone(watchdog.scientific_block(root))
   self.assertFalse((root/'infra_retry_review.json').exists());self.assertEqual(len(list((root/'infra_retry_history').glob('*.json'))),1)
   self.assertIn('Unreviewed',watchdog.scientific_block(root))
 def test_changed_state_or_checkpoint_proof_is_rejected(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);review=self.fixture(root);write_json(root/'infra_retry_review.json',review)
   (root/'diagnostic.log').write_text('changed')
   with patch.object(watchdog.mc_runtime,'provenance',return_value={'fixture':True}),self.assertRaises(ValueError):watchdog.scientific_block(root)
 def test_maximum_candidate_accuracy_cannot_be_overridden_by_infrastructure_review(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);review=self.fixture(root);write_json(root/'infra_retry_review.json',review)
   write_json(root/'benchmark/accuracy.json',[{'samples':4096,'methods':{method:{'pass_fraction':.9} for method in watchdog.mc_runtime.benchmarking.METHODS[:3]}}])
   self.assertIn('Maximum registered',watchdog.scientific_block(root));self.assertTrue((root/'infra_retry_review.json').exists())
 def test_training_recovery_requires_the_exact_checkpoint_and_elapsed_journal(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);review=self.fixture(root)
   write_json(root/'state.json',{'status':'needs_attention','current_stage':'training','error':'fixture infrastructure failure'})
   review['state_sha256']=watchdog.mc_runtime.digest(root/'state.json')
   review['training_files']={}
   for name in ('checkpoint.pkl','elapsed_journal.json'):
    path=root/'training'/name;path.parent.mkdir(exist_ok=True);path.write_text('fixture only')
    review['training_files'][name]=watchdog.mc_runtime.digest(path)
   write_json(root/'infra_retry_review.json',review)
   (root/'training/elapsed_journal.json').write_text('changed after review')
   with patch.object(watchdog.mc_runtime,'provenance',return_value={'fixture':True}),self.assertRaises(ValueError):watchdog.scientific_block(root)
if __name__=='__main__':unittest.main()
