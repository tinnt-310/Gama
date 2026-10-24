from pathlib import Path
import tempfile,unittest
from unittest.mock import patch
import importlib.util
spec=importlib.util.spec_from_file_location("chunk_watchdog",Path(__file__).with_name("watchdog.py"))
watchdog=importlib.util.module_from_spec(spec);spec.loader.exec_module(watchdog)
from ranr.paths import write_json

class ScientificRestartTests(unittest.TestCase):
    def test_completed_and_budget_limited_releases_are_not_restarted(self):
        for status in ('complete','budget_limited'):
            with tempfile.TemporaryDirectory(prefix='watchdog-test-') as tmp:
                root=Path(tmp);write_json(root/'state.json',{'status':status})
                self.assertIsNotNone(watchdog.scientific_block(root))
    def test_infeasible_72_hour_budget_is_not_automatically_retried(self):
        with tempfile.TemporaryDirectory(prefix='watchdog-test-') as tmp:
            root=Path(tmp);write_json(root/'state.json',{'status':'needs_attention'});write_json(root/'benchmark/budget.json',{'passed':False})
            self.assertIn('infeasible',watchdog.scientific_block(root))
    def test_registered_failed_physical_step_is_not_automatically_retried(self):
        with tempfile.TemporaryDirectory(prefix='watchdog-test-') as tmp:
            root=Path(tmp);write_json(root/'state.json',{'status':'needs_attention'});write_json(root/'benchmark/physical_steps.json',{'60':{'passed':False}})
            self.assertIn('physical',watchdog.scientific_block(root))
    def test_running_or_infrastructure_interruption_can_resume(self):
        for status in ('running','interrupted'):
            with tempfile.TemporaryDirectory(prefix='watchdog-test-') as tmp:
                root=Path(tmp);write_json(root/'state.json',{'status':status})
                self.assertIsNone(watchdog.scientific_block(root))

if __name__=='__main__':unittest.main()
