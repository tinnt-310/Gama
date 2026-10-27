"""Reconstruct exogenous station traces; GAMA EV agents compute both H branches.

No queue/charging simulation is implemented here. Every numerical H result must
come from native paired replay and pass insertion-branch fidelity first.
"""
from pathlib import Path
from collections import Counter, defaultdict
import csv
import hashlib
import json
import math

BASE=Path(__file__).resolve().parent
MODEL=Path(__file__).resolve().parents[2]/'tests/native_reviews/RanrPairedPhysicalReplay.gaml'

def load_episode(folder):
    folder=Path(folder)
    manifest=json.loads((folder/'manifest.json').read_text())
    configuration=json.loads((folder/'configuration.json').read_text())
    with (folder/'events.csv').open() as stream:events=list(csv.DictReader(stream))
    # Physical arrival SOC and immutable target are the exact battery demand at
    # this leg's arrival. This is independently checked by F04 before invocation.
    jobs={};latest={}
    for order,event in enumerate(events):
        key=(event['request_id'],int(event['leg']))
        kind=event['terminal_record'];at=float(event['time_min'])
        if kind=='arrival':
            if key in jobs:raise ValueError('Duplicate physical arrival')
            energy=max(0.,(float(event['target_soc'])-float(event['soc']))*configuration['battery_capacity_kwh']/100.)
            jobs[key]=dict(key=f'{key[0]}:{key[1]}',request_id=key[0],leg=key[1],token=event['token'],
                station=int(event['station_sid']),at=at,order=order,energy=energy,soc=float(event['soc']),
                max_kw=float(event['ev_limit_kw']),expected_wait=None,cancel=None)
            latest[event['request_id']]=key
        elif kind=='service_started' and key in jobs:
            jobs[key]['expected_wait']=at-jobs[key]['at']
        elif kind in {'abandoned','stranded','unresolved','cancelled','replan'} and key in jobs:
            jobs[key]['cancel']=dict(at=at,order=order)
    for job in jobs.values():
        if (not all(math.isfinite(job[k]) for k in ['at','energy','soc','max_kw']) or
            job['at']<0 or abs(job['at']-round(job['at']))>1e-7 or job['max_kw']<=0 or not 0<=job['soc']<=100):
            raise ValueError('Invalid/non-minute physical replay job')
    inventory={s['sid']:s for s in json.loads((folder/'station_inventory.json').read_text())}
    return manifest,configuration,jobs,inventory

def prepare(folder,probes,target):
    """Probes carry key, prediction and fixed model horizon; selection is external."""
    from ranr.paths import digest,write_json
    from ranr.gama.headless import ENVIRONMENT
    manifest,config,jobs,inventory=load_episode(folder)
    if manifest['config']['station_events'] or config['station_events']:
        raise ValueError('Counterfactual requires explicit replay of station events; none registered here')
    environment=json.loads(ENVIRONMENT.read_text()) if isinstance(ENVIRONMENT,Path) else ENVIRONMENT
    stations=[];operations=[];comparisons=[];expected={};last=0.
    for index,probe in enumerate(probes):
        key=(probe['request_id'],int(probe['leg']))
        if key not in jobs:raise ValueError('Selected counterfactual probe has no arrival')
        subject=jobs[key];sid=subject['station'];cutoff=float(probe['horizon_end'])
        if subject['at']>cutoff:raise ValueError('Probe arrives beyond registered forecast horizon')
        cohort=[j for j in jobs.values() if j['station']==sid and j['at']<=cutoff+1e-9]
        powers=list(inventory[sid]['ports'].values());counts=Counter(int(p) for p in powers)
        name=inventory[sid]['name'];limits=environment['station_aggregate_power_kw']
        aggregate=float(limits.get(name,sum(powers)))
        branch_keys={}
        for branch in [0,1]:
            station_index=index*2+branch
            stations.append(dict(index=station_index,port_counts={str(r):counts[r] for r in [250,180,150,60,30,11]},aggregate_kw=aggregate))
            others=[]
            for job in cohort:
                if branch==1 and job is subject:continue
                identity=f'{index}:{branch}:{job["key"]}'
                operations.append(dict(operation='arrival',identity=identity,at=job['at'],order=job['order'],
                    station_index=station_index,energy=job['energy'],soc=job['soc'],max_kw=job['max_kw']))
                last=max(last,job['at'])
                if job['cancel'] is not None:
                    operations.append(dict(operation='cancel',identity=identity,**job['cancel']))
                    last=max(last,job['cancel']['at'])
                if job is not subject:others.append(identity)
                if branch==0 and job['expected_wait'] is not None:expected[identity]=job['expected_wait']
            branch_keys[str(branch)]=others
        comparisons.append(dict(**probe,probe_identity=f'{index}:0:{subject["key"]}',branches=branch_keys,
                                original_station=sid,cohort_jobs=len(cohort)))
    operations.sort(key=lambda x:(x['at'],x['order'],x['identity']))
    identity=hashlib.sha256(json.dumps(dict(manifest=digest(Path(folder)/'manifest.json'),probes=probes),sort_keys=True).encode()).hexdigest()
    payload=dict(input_identity=identity,seed=manifest['config']['seed'],case=manifest['config']['case'],
                 method=manifest['config']['method'],stations=stations,operations=operations,expected_waits=expected,
                 comparisons=comparisons,last_operation_min=last,charge_efficiency=config['charge_efficiency'],
                 battery_capacity_kwh=config['battery_capacity_kwh'],taper_soc=environment['taper_soc'],taper_factors=environment['taper_factors'])
    write_json(target,payload)
    return payload

def execute(input_path,output_path,evidence_path):
    from ranr.gama.validation import run_model
    from ranr.gama.headless import provenance
    from ranr.gama.contracts import OBJECTIVE_SPEC
    from ranr.paths import digest,write_json
    input_path,output_path,evidence_path=map(Path,[input_path,output_path,evidence_path])
    payload=json.loads(input_path.read_text());steps=int(math.ceil(payload['last_operation_min']))+6001
    resources=evidence_path.with_suffix('.resources.json')
    console=run_model(str(MODEL),'paired_physical_replay',steps,'RANR_PAIRED_PHYSICAL_REPLAY_PASS',
        parameters=dict(replay_input=('STRING',str(input_path.resolve())),replay_output=('STRING',str(output_path.resolve()))),
        seed=payload['seed'],resource_output=resources)
    result=json.loads(output_path.read_text())
    if result.get('input_identity')!=payload['input_identity']:raise ValueError('Paired physical replay input changed')
    waits=result['waits'];errors=[]
    identities={item['identity'] for item in payload['operations'] if item['operation']=='arrival'}
    if set(waits)!=identities or any(not math.isfinite(v) or v<0 for v in waits.values()):
        raise ValueError('Paired native replay has missing/nonfinite/negative waits')
    for key,expected in payload['expected_waits'].items():
        if key not in waits or not math.isfinite(waits[key]):raise ValueError('Physical replay missing observed job')
        errors.append(abs(waits[key]-expected))
    maximum=max(errors,default=0.)
    if maximum>OBJECTIVE_SPEC['time_tol_min']:
        write_json(evidence_path,dict(passed=False,kind='paired_physical_replay',max_fidelity_error_min=maximum,
                  input_sha256=digest(input_path),output_sha256=digest(output_path),console=console))
        raise ValueError(f'Physical replay failed insertion fidelity: {maximum} minutes')
    rows=[]
    for comparison in payload['comparisons']:
        branches=comparison['branches'];groups=[[waits[k] for k in branches[str(i)]] for i in [0,1]]
        if len(groups[0])!=len(groups[1]):raise ValueError('Counterfactual exogenous cohorts differ')
        h=sum(groups[0])-sum(groups[1])
        if not math.isfinite(h):raise ValueError('Nonfinite physical H')
        rows.append({k:v for k,v in comparison.items() if k!='branches'}|dict(physical_H=h,
                    inserted_others_wait=sum(groups[0]),control_others_wait=sum(groups[1])))
    evidence=dict(passed=True,kind='paired_physical_replay',source=provenance(),model=str(MODEL),model_sha256=digest(MODEL),
        input_sha256=digest(input_path),output_sha256=digest(output_path),max_fidelity_error_min=maximum,
        compared_observed_jobs=len(errors),rows=rows,console=console,
        resources=dict(path=str(resources),sha256=digest(resources)))
    write_json(evidence_path,evidence)
    return evidence
