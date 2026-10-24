"""Read-only checks for operational states and conclusive native reference failure.

This does not select samples or change any official gate. A FAIL certificate is
recomputed from sealed per-probe CSVs before it is described as a scientific block.
"""
from pathlib import Path
import csv
import json
import math
import sys
import hashlib
ROOT=Path('/home/tinnt/Gama_Workspace/Nha Trang CSs planning')
sys.path.insert(0,str(ROOT/'src'))
from ranr.gama.benchmarking import PROBE_KEYS,THRESHOLDS
from ranr.gama.headless import provenance
from ranr.gama.evidence import verify_reference


def stage_status(state,name):
    row=state.get('stages',{}).get(name)
    if not row:return 'PENDING'
    if row['status']=='failed':return 'FAIL'
    if row['status']=='complete':
        if name=='training' and state.get('status')=='budget_limited':return 'BUDGET_LIMITED'
        return 'PASS'
    if row['status']=='running':
        return 'RUNNING' if state.get('status')=='running' else 'INTERRUPTED'
    return str(row['status']).upper()


def table(path,expected):
    with Path(path).open() as stream:rows=list(csv.DictReader(stream))
    keys=[(r['method'],r['station'],r['probe']) for r in rows]
    if len(set(keys))!=len(keys) or set(keys)!=set(expected):raise ValueError('Incomplete or duplicate native grid')
    if not all(math.isfinite(float(r[k])) for r in rows for k in THRESHOLDS):raise ValueError('Nonfinite probe')
    return dict(zip(keys,rows))


def failure_certificate(path):
    record=json.loads(Path(path).read_text())
    if record['source']!=provenance() or record['pair']!=[8192,16384] or record['status']!='scientific_gate_failed':raise ValueError('Wrong reference failure registration')
    if record.get('full_grid_completed') is not False:raise ValueError('Partial proof must not impersonate a full grid')
    low=table(verify_reference(record['low_reference']),PROBE_KEYS)
    proof=json.loads(verify_reference(record['equivalence']).read_text())
    if proof.get('passed') is not True or proof['source']!=record['source']:raise ValueError('Missing sharding equivalence')
    rows={}
    for ref in record['native_shards']:
        manifest_path=verify_reference(ref);manifest=json.loads(manifest_path.read_text());identity=manifest['identity']
        if manifest.get('status')!='complete' or identity['samples']!=16384 or identity['seed']!=900001 or identity['source']!=record['source'] or not identity.get('full_sample_count_per_probe'):
            raise ValueError('Invalid full-count native completion')
        key=tuple(identity['key'])
        if key in rows or key not in PROBE_KEYS:raise ValueError('Duplicate or unregistered sealed probe')
        for artifact in manifest['artifacts']:verify_reference(artifact)
        rows[key]=table(manifest_path.parent/'probe.csv',{key})[key]
    if len(rows)!=record['observed_probes']:raise ValueError('Observed count mismatch')
    method=record['method'];failures=[]
    for key,row in rows.items():
        if key[0]!=method:continue
        errors={k:abs(float(row[k])-float(low[key][k])) for k in THRESHOLDS}
        if any(errors[k]>THRESHOLDS[k]/2 for k in errors):failures.append({'key':list(key),'absolute_errors':errors})
    total=sum(key[0]==method for key in PROBE_KEYS);upper=(total-len(failures))/total
    if upper>=.95 or len(failures)<3 or record['maximum_pass_fraction']!=upper or record['total_registered_probes']!=total:
        raise ValueError('Evidence does not conclusively fail the registered criterion')
    if {tuple(x['key']) for x in failures}!={tuple(x['key']) for x in record['failed_probes']}:raise ValueError('Failed key list mismatch')
    return {'passed_verification':True,'method':method,'pair':[8192,16384],'failed_probes':failures,
            'observed_probes':len(rows),'maximum_possible_pass_fraction':upper,'required_fraction':.95,
            'thresholds':{k:v/2 for k,v in THRESHOLDS.items()},'source_certificate':str(path)}
