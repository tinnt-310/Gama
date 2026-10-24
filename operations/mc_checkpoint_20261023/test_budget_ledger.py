from pathlib import Path
import json
import pickle
import tempfile
import unittest
from unittest.mock import patch
import sys
sys.path.insert(0,str(Path(__file__).parent))
import mc_runtime
import budget_ledger as ledger
from ranr.paths import write_json

class ElapsedBudgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.identity={'source':{'fixture':True},'budget_sha256':'unit','maximum_seconds':259200,'ledger_schema':1}

    def test_recovery_does_not_reset_elapsed_even_after_power_loss(self):
        write_json(self.root/'elapsed_journal.json',{'identity':self.identity,'owner':{'pid':0},'active':True,'consumed_seconds':800.})
        with patch.object(ledger,'still_alive',return_value=False):
            journal=ledger.ElapsedJournal(self.root,self.identity,100.,clock=lambda:10.)
        self.assertEqual(journal.initial,805.)
        journal.pulse(False)
        self.assertEqual(json.loads((self.root/'elapsed_journal.json').read_text())['consumed_seconds'],805.)

    def test_closed_journal_and_checkpoint_use_larger_consumed_time(self):
        write_json(self.root/'elapsed_journal.json',{'identity':self.identity,'owner':{'pid':0},'active':False,'consumed_seconds':800.})
        journal=ledger.ElapsedJournal(self.root,self.identity,900.,clock=lambda:10.)
        self.assertEqual(journal.initial,900.)
        journal.pulse(False)

    def test_alive_owner_or_changed_registration_prevents_reset(self):
        write_json(self.root/'elapsed_journal.json',{'identity':self.identity,'owner':{'pid':0},'active':True,'consumed_seconds':800.})
        with patch.object(ledger,'still_alive',return_value=True):
            with self.assertRaisesRegex(ValueError,'live owner'):ledger.ElapsedJournal(self.root,self.identity,0.)
        with self.assertRaisesRegex(ValueError,'registration changed'):ledger.ElapsedJournal(self.root,{'changed':True},0.)

    def test_only_elapsed_changes_in_checkpoint_and_original_is_saved(self):
        checkpoint={'registration':{'source':{'fixture':True},'budget_sha256':'unit'},'active_seconds':100.,
            'slots':[{'pending':[1,2,3],'rng':'unchanged','generation':4}],'paired_reference':{'a':[1,2]}}
        path=self.root/'checkpoint.pkl';path.write_bytes(pickle.dumps(checkpoint))
        write_json(self.root/'elapsed_journal.json',{'identity':self.identity,'owner':{'pid':0},'active':False,'consumed_seconds':800.})
        ledger.reconcile_checkpoint(self.root,self.identity)
        result=pickle.loads(path.read_bytes());self.assertEqual(result['active_seconds'],800.)
        for key in set(result)-{'active_seconds'}:self.assertEqual(result[key],checkpoint[key])
        archives=list((self.root/'elapsed_recovery').glob('*/checkpoint_before.pkl'))
        self.assertEqual(len(archives),1);self.assertEqual(pickle.loads(archives[0].read_bytes()),checkpoint)

    def test_elapsed_counts_current_attempt_and_never_excludes_restart_debt(self):
        now=[10.]
        journal=ledger.ElapsedJournal(self.root,self.identity,70.,clock=lambda:now[0]);journal.pulse()
        now[0]=15.;self.assertEqual(journal.pulse(False),75.)

if __name__=='__main__':unittest.main()
