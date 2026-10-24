import copy,json,math,tempfile,unittest
from pathlib import Path
import chunk_models
import chunk_runtime as cr


class AbsoluteSampleIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.parts=[json.loads((Path(__file__).parent/'first_native_check'/f'raw_{begin}.json').read_text())[0] for begin in (0,16)]
        self.key=('RANR-AW','7','4')
    def test_registered_16384_samples_are_covered_exactly_once(self):
        pairs=cr.ranges(16384,1024)
        self.assertEqual(len(pairs),16)
        self.assertEqual([i for begin,end in pairs for i in range(begin,end)],list(range(16384)))
    def test_native_raw_values_are_concatenated_without_python_statistics(self):
        result=cr.aggregation_input(self.parts,32,self.key)
        self.assertEqual(result['chunks'],self.parts)
        self.assertEqual([x for part in result['chunks'] for x in part['waits']],self.parts[0]['waits']+self.parts[1]['waits'])
    def test_missing_duplicate_overlapping_or_reordered_ranges_cannot_aggregate(self):
        bad=[self.parts[:1],self.parts[::-1],[self.parts[0],self.parts[0]]]
        overlap=copy.deepcopy(self.parts);overlap[1]['sample_begin']=15;bad.append(overlap)
        for parts in bad:
            with self.subTest(parts=parts),self.assertRaises(ValueError):cr.aggregation_input(parts,32,self.key)
    def test_mixed_probe_and_sample_count_rejected(self):
        for field,value in [('station',8),('configured_samples',16)]:
            parts=copy.deepcopy(self.parts);parts[1][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):cr.aggregation_input(parts,32,self.key)
    def test_raw_missing_nan_boolean_and_wrong_sample_range_rejected(self):
        expected={'range':[0,16],'samples':32,'key':list(self.key)}
        for mutation in ('short','nan','bool','range'):
            row=copy.deepcopy(self.parts[0])
            if mutation=='short':row['waits'].pop()
            if mutation=='nan':row['externalities'][0]=float('nan')
            if mutation=='bool':row['waits'][0]=True
            if mutation=='range':row['sample_end']=32
            with tempfile.TemporaryDirectory(prefix='chunk-schema-test-') as tmp:
                path=Path(tmp)/'raw.json';path.write_text(json.dumps([row]))
                with self.subTest(mutation=mutation),self.assertRaises(ValueError):cr.read_raw(path,expected)
    def test_cache_tamper_and_identity_changes_rejected(self):
        with tempfile.TemporaryDirectory(prefix='chunk-cache-test-') as tmp:
            folder=Path(tmp);raw=folder/'raw.json';raw.write_text(json.dumps([self.parts[0]]))
            expected={'samples':32,'range':[0,16]}
            cr.write_json(folder/'manifest.json',{'identity':expected,'status':'complete','artifacts':[cr.reference(raw)]})
            with self.assertRaises(ValueError):cr.cached(folder,{'samples':16384,'range':[0,16]})
            raw.write_text('changed')
            with self.assertRaises(ValueError):cr.cached(folder,expected)
    def test_interrupted_chunk_is_never_cached_as_a_completion(self):
        with tempfile.TemporaryDirectory(prefix='chunk-interrupted-test-') as tmp:
            folder=Path(tmp);expected={'samples':16384,'range':[0,1024]}
            cr.write_json(folder/'manifest.json',{'identity':expected,'status':'interrupted'})
            self.assertIsNone(cr.cached(folder,expected))
    def test_only_three_reviewed_estimator_edits_are_allowed(self):
        body=chunk_models.estimator_source()
        expected=body.replace('ranr_estimate(','ranr_estimate_chunk(',1).replace('loop sample from: 0 to: ranr_samples-1 {','loop sample from: sample_begin to: sample_end-1 {',1).replace('return ["mean"::mean_wait,','return ["sample_waits"::waits,"sample_externalities"::externalities,"mean"::mean_wait,',1)
        self.assertIn(expected,chunk_models.chunk_model())
        chunk_models.verify(Path(__file__).parent)


if __name__=='__main__':unittest.main()
