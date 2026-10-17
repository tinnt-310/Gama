"""Semantic replay comparisons; never change historical manifests."""
from pathlib import Path
import csv
import itertools
import json
import math
from ..paths import write_json, digest
from .headless import checked_result, provenance
from .contracts import OBJECTIVE_SPEC
from .evidence import reference, read_reference

FILES = ("initial_fleet.json","vehicle_traits.json","activity_plan.json","traffic_plan.json",
         "events.csv","intent_outcomes.json","mobility_outcomes.json","vehicles.csv")
IGNORED = {"run_id","wall_seconds","cpu_seconds","max_rss_kib","started_at","finished_at"}


def mismatch(a,b,path=""):
    if isinstance(a,dict) and isinstance(b,dict):
        ka = {k for k in a if k not in IGNORED and not k.endswith('_ms')}
        kb = {k for k in b if k not in IGNORED and not k.endswith('_ms')}
        if ka != kb: return {"path":path,"reason":"keys","left":sorted(ka),"right":sorted(kb)}
        for k in sorted(ka):
            diff = mismatch(a[k],b[k],path+"/"+str(k))
            if diff: return diff
        return None
    if isinstance(a,list) and isinstance(b,list):
        if len(a)!=len(b): return {"path":path,"reason":"length","left":len(a),"right":len(b)}
        for i,(x,y) in enumerate(zip(a,b)):
            diff = mismatch(x,y,path+"/"+str(i))
            if diff: return diff
        return None
    if isinstance(a,bool) or isinstance(b,bool) or a is None or b is None:
        return None if type(a)==type(b) and a==b else {"path":path,"left":a,"right":b}
    # CSV numbers and JSON floats share the registered dimensional tolerances.
    try:
        x,y = float(a),float(b)
    except (ValueError,TypeError):
        return None if a==b else {"path":path,"left":a,"right":b}
    key = path.rsplit('/',1)[-1]
    tolerance = OBJECTIVE_SPEC['time_tol_min']
    if any(word in key for word in ('energy','kwh','battery')):
        tolerance = max(OBJECTIVE_SPEC['energy_abs_tol_kwh'],OBJECTIVE_SPEC['energy_rel_tol']*max(abs(x),abs(y)))
    elif 'soc' in key: tolerance = OBJECTIVE_SPEC['soc_tol_percent']
    if not math.isfinite(x) or not math.isfinite(y) or abs(x-y)>tolerance:
        return {"path":path,"left":a,"right":b,"tolerance":tolerance}
    return None


def compare_runs(left,right):
    left,right = Path(left),Path(right)
    # Immutable input/ledger hashes are always checked before semantic comparison.
    for folder in (left,right):
        manifest = json.loads((folder/'manifest.json').read_text())
        checked_result(folder,{"source":manifest['source']})
    for name in FILES:
        if name.endswith('.json'):
            a,b = [json.loads((p/name).read_text()) for p in (left,right)]
            diff = mismatch(a,b,name)
        else:
            diff = None
            with (left/name).open() as fa,(right/name).open() as fb:
                ra,rb = csv.DictReader(fa),csv.DictReader(fb)
                if ra.fieldnames!=rb.fieldnames: diff = {"path":name,"reason":"CSV columns"}
                else:
                    for i,(a,b) in enumerate(itertools.zip_longest(ra,rb)):
                        diff = mismatch(a,b,f'{name}/{i}')
                        if diff: break
        if diff: return {"passed":False,"first_divergence":diff}
    a,b = [json.loads((p/'metrics.json').read_text()) for p in (left,right)]
    # Compare authoritative fitness and registered components, not machine timing.
    for key in ('fitness_vector','objective_components','exogenous_hash'):
        diff = mismatch(a[key],b[key],"metrics/"+key)
        if diff: return {"passed":False,"first_divergence":diff}
    return {"passed":True,"first_divergence":None}


def replay_report(selected,replays,gui,target,outlier=None,resolution=None):
    selected = [Path(p).resolve() for p in selected]
    replays = [Path(p).resolve() for p in replays]
    if len(replays)!=3 or len(set(replays))!=3: raise ValueError('Three distinct fresh headless replays required')
    if len(selected)!=3: raise ValueError('Three selected calibration Collects required')
    by_seed = {json.loads((p/'manifest.json').read_text())['config']['seed']:p for p in selected}
    if set(by_seed)!={800001,800002,800003}: raise ValueError('Selected calibration seeds changed')
    baseline = by_seed[800001]
    dependencies = [reference(p/'manifest.json') for p in (*selected,*replays)]
    common = json.loads((baseline/'manifest.json').read_text())['config']
    keys = set(common)-{'render','timeout_seconds'}
    def fresh(folder,origin=None):
        m = json.loads((folder/'manifest.json').read_text())
        if m['source']!=provenance() or (origin and m.get('origin')!=origin):
            raise ValueError('Replay needs current source/fresh GUI origin')
        if {k:m['config'].get(k) for k in keys}!={k:common[k] for k in keys}:
            raise ValueError('Replay configuration changed')
    for folder in replays: fresh(folder)
    comparisons = [{"run":str(p),**compare_runs(baseline,p)} for p in replays]
    gui_checked = False
    if gui:
        gui = Path(gui).resolve()
        if gui in selected or gui in replays: raise ValueError('GUI replay must be a fresh distinct run')
        fresh(gui,'GAMA_GUI')
        comparison = compare_runs(baseline,gui)
        comparisons.append({"run":str(gui),**comparison})
        gui_checked = comparison['passed']
        dependencies.append(reference(gui/'manifest.json'))
    outlier_resolved = False
    if outlier:
        outlier = Path(outlier).resolve()
        outlier_comparison = compare_runs(baseline,outlier)
        dependencies.append(reference(outlier/'manifest.json'))
        if outlier_comparison['passed']: outlier_resolved = True
        elif resolution:
            data = json.loads(Path(resolution).read_text())
            # A diagnosis must name the divergent run, supported experiments and
            # causal explanation; a standalone passed=true is not evidence.
            if data.get('outlier_manifest_sha256')!=digest(outlier/'manifest.json') or not data.get('cause') or not data.get('experiments'):
                raise ValueError('Hash-linked causal diagnosis with experiments required')
            for ref in data['experiments']:
                experiment = read_reference(ref)
                if experiment.get('source')!=provenance() or experiment.get('passed') is not True or not experiment.get('observations'):
                    raise ValueError('Causal diagnosis needs current observed experiment results')
            dependencies.extend([reference(resolution),*data['experiments']])
            outlier_resolved = True
    else:
        outlier_comparison = None
    passed = all(row['passed'] for row in comparisons) and gui_checked and outlier_resolved
    record = {'kind':'collection_reproducibility','source':provenance(),'passed':passed,
        'gui_checked':gui_checked,'outlier_resolved':outlier_resolved,
        'selected_runs':{str(p):digest(p/'manifest.json') for p in selected},
        'comparisons':comparisons,'outlier_comparison':outlier_comparison,
        'dependencies':dependencies,'replays':[str(p) for p in replays],
        'gui':str(gui) if gui else None,'outlier':str(outlier) if outlier else None,
        'resolution':str(Path(resolution).resolve()) if resolution else None}
    write_json(target,record)
    return record
