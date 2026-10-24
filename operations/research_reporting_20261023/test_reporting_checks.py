from pathlib import Path
import csv,json,tempfile,unittest
from unittest.mock import patch
import reporting_checks as rc
from ranr.gama.evidence import reference
from ranr.paths import write_json

class ReportingIntegrityTests(unittest.TestCase):
    def test_failed_and_budget_limited_are_never_reported_pass_or_pending(self):
        self.assertEqual(rc.stage_status({'status':'needs_attention','stages':{'accuracy':{'status':'failed'}}},'accuracy'),'FAIL')
        self.assertEqual(rc.stage_status({'status':'budget_limited','stages':{'training':{'status':'complete'}}},'training'),'BUDGET_LIMITED')
        self.assertEqual(rc.stage_status({'status':'interrupted','stages':{'accuracy':{'status':'running'}}},'accuracy'),'INTERRUPTED')
    def build(self,p,count):
        source={'fixture':'synthetic test only'};low=p/'low.csv';fields=['method','station','probe',*rc.THRESHOLDS]
        with low.open('w') as f:
            writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
            for key in sorted(rc.PROBE_KEYS):writer.writerow(dict(zip(fields,[*key,0,0,0])))
        proof=p/'equivalence.json';write_json(proof,{'passed':True,'source':source})
        refs=[];keys=[('No-P2P','7',str(i)) for i in range(count)]
        for key in keys:
            folder=p.joinpath(*key);folder.mkdir(parents=True);output=folder/'probe.csv'
            with output.open('w') as f:
                writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerow(dict(zip(fields,[*key,1,0,0])))
            write_json(folder/'manifest.json',{'status':'complete','identity':{'samples':16384,'seed':900001,'source':source,'key':list(key),'full_sample_count_per_probe':True},'artifacts':[reference(output)]})
            refs.append(reference(folder/'manifest.json'))
        path=p/'certificate.json';write_json(path,{'source':source,'status':'scientific_gate_failed','pair':[8192,16384],'full_grid_completed':False,'low_reference':reference(low),'equivalence':reference(proof),'native_shards':refs,'observed_probes':count,'method':'No-P2P','maximum_pass_fraction':(55-count)/55,'total_registered_probes':55,'failed_probes':[{'key':list(k)} for k in keys]})
        return source,path,keys
    def test_three_sealed_failures_prove_failure_without_inventing_full_grid(self):
        with tempfile.TemporaryDirectory(prefix='synthetic-report-only-') as tmp:
            source,path,_=self.build(Path(tmp),3)
            with patch.object(rc,'provenance',return_value=source):proof=rc.failure_certificate(path)
            self.assertEqual(proof['observed_probes'],3);self.assertLess(proof['maximum_possible_pass_fraction'],.95)
    def test_two_sealed_failures_do_not_prove_failure(self):
        with tempfile.TemporaryDirectory(prefix='synthetic-report-only-') as tmp:
            source,path,_=self.build(Path(tmp),2)
            with patch.object(rc,'provenance',return_value=source),self.assertRaises(ValueError):rc.failure_certificate(path)
    def test_modified_raw_csv_is_rejected_even_if_certificate_unchanged(self):
        with tempfile.TemporaryDirectory(prefix='synthetic-report-only-') as tmp:
            source,path,keys=self.build(Path(tmp),3)
            Path(tmp).joinpath(*keys[0],'probe.csv').write_text('changed')
            with patch.object(rc,'provenance',return_value=source),self.assertRaises(ValueError):rc.failure_certificate(path)
    def test_wrong_sample_count_cannot_be_resealed_into_failure_proof(self):
        with tempfile.TemporaryDirectory(prefix='synthetic-report-only-') as tmp:
            source,path,keys=self.build(Path(tmp),3);manifest=Path(tmp).joinpath(*keys[0],'manifest.json')
            data=json.loads(manifest.read_text());data['identity']['samples']=32;write_json(manifest,data)
            cert=json.loads(path.read_text());cert['native_shards'][0]=reference(manifest);write_json(path,cert)
            with patch.object(rc,'provenance',return_value=source),self.assertRaises(ValueError):rc.failure_certificate(path)

if __name__=='__main__':unittest.main()
