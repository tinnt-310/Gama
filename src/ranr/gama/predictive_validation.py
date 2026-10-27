"""Score registered native forecast validation; no physics or fake fitness."""
from pathlib import Path
from collections import defaultdict,Counter
import csv
import hashlib
import json
import math
import numpy as np

BASE=Path(__file__).resolve().parent

def extract(folder):
    folder=Path(folder);manifest=json.loads((folder/'manifest.json').read_text());config=manifest['config']
    with (folder/'events.csv').open() as stream:events=list(csv.DictReader(stream))
    arrivals={};starts={};completions={}
    for event in events:
        kind=event['terminal_record'];key=(event['request_id'],event['token'])
        destination=arrivals if kind=='arrival' else starts if kind=='service_started' else completions if kind=='service_completed' else None
        if destination is not None:
            if key in destination:raise ValueError('Duplicate token/leg event')
            destination[key]=event
    with (folder/'recommendations.csv').open() as stream:recommendations=list(csv.DictReader(stream))
    rows=[];counts=Counter();seen=set()
    for record in recommendations:
        at=float(record['issued_min'])
        if not config['warmup_minutes']<=at<config['warmup_minutes']+config['measure_minutes']:continue
        key=(record['request_id'],record['token'])
        if key in seen:raise ValueError('Duplicate forecast token')
        seen.add(key);counts['measured_forecasts']+=1
        sid=int(record['actual'])
        if sid<0:counts['outside']+=1;continue
        if key not in arrivals:counts['no_arrival']+=1;continue
        arrival=arrivals[key]
        if int(arrival['station_sid'])!=sid:raise ValueError('Forecast and physical arrival destination differ')
        if key not in starts:counts['censored_wait']+=1;continue
        start=starts[key]
        if int(start['leg'])!=int(arrival['leg']) or int(start['station_sid'])!=sid:
            raise ValueError('Service-start token/leg/station differs from physical arrival')
        if key not in completions:counts['started_without_observed_completion']+=1
        elif int(completions[key]['leg'])!=int(arrival['leg']):
            raise ValueError('Completion token/leg differs from physical arrival')
        else:counts['observed_charging_completions']+=1
        waiting=float(start['time_min'])-float(arrival['time_min'])
        if waiting<-.000001:raise ValueError('Service precedes physical arrival')
        estimates=json.loads(record['estimates']);estimate=estimates[sid]
        state=json.loads(record['state']);features=json.loads(record['raw_features'])
        values=[float(estimate[k]) for k in ['mean','p95','externality']]+[waiting,float(state[1])]
        if not all(math.isfinite(v) for v in values) or min(values[:2])<0 or len(state)!=5:raise ValueError('Invalid forecast/state')
        travels=[max(0.,float(features[i][0])-float(x['charge'])) for i,x in enumerate(estimates) if 'charge' in x]
        if not travels:raise ValueError('Forecast lacks declared travel horizon inputs')
        hour=(config['initial_hour']+at/60.)%24
        load=float(state[1]);load_bin=min(3,int(load*4))
        rows.append(dict(seed=config['seed'],case=config['case'],method=config['method'],request_id=record['request_id'],
            token=record['token'],leg=int(arrival['leg']),sid=sid,issued_min=at,arrival_min=float(arrival['time_min']),
            physical_wait=max(0.,waiting),predicted_mean=values[0],predicted_p95=values[1],predicted_H=values[2],
            load=load,load_bin=load_bin,hour=hour,time_bin=int(hour//6),horizon_end=at+max(travels)+120.))
        rows[-1]['observation_end']=sum(config[k] for k in ['warmup_minutes','measure_minutes','deadline_minutes'])
        counts['complete_waits']+=1
    return rows,dict(counts)

def select_counterfactuals(rows,seed,case,method):
    pools=defaultdict(list)
    for row in rows:
        if row['arrival_min']>row['horizon_end'] or row['horizon_end']>row['observation_end']:continue
        key=f'{seed},{case},{method},{row["request_id"]},{row["leg"]}'
        pools[row['sid']].append((hashlib.sha256(key.encode()).hexdigest(),row))
    return [row for sid in sorted(pools) for _,row in sorted(pools[sid],key=lambda pair:pair[0])[:20]]

def metrics(rows):
    if not rows:return {}
    physical=np.array([r['physical_wait'] for r in rows]);means=np.array([r['predicted_mean'] for r in rows]);p95=np.array([r['predicted_p95'] for r in rows]);error=physical-p95
    hs=[r for r in rows if 'physical_H' in r]
    result=dict(count=len(rows),seeds=len({r['seed'] for r in rows}),mean_physical_wait=float(physical.mean()),
        mean_bias=float((means-physical).mean()),mean_absolute_wait_error=float(abs(means-physical).mean()),
        p95_coverage=float((physical<=p95+1e-9).mean()),p95_pinball_loss=float(np.maximum(.95*error,-.05*error).mean()),
        H_count=len(hs),H_seeds=len({r['seed'] for r in hs}))
    result['mean_bias_limit']=max(3.,.15*result['mean_physical_wait'])
    if hs:
        result['H_MAE']=float(np.mean([abs(r['predicted_H']-r['physical_H']) for r in hs]))
        result['mean_absolute_physical_H']=float(np.mean([abs(r['physical_H']) for r in hs]))
        result['H_MAE_limit']=max(10.,.2*result['mean_absolute_physical_H'])
    return result

def bootstrap(rows,iterations=2000,seed=920100):
    clusters=defaultdict(list)
    for row in rows:clusters[row['seed']].append(row)
    keys=sorted(clusters)
    if len(keys)<3:return dict(status='INSUFFICIENT EVIDENCE',clusters=len(keys))
    rng=np.random.RandomState(seed);samples=defaultdict(list)
    for _ in range(iterations):
        draw=rng.choice(keys,len(keys),replace=True)
        values=metrics([r for k in draw for r in clusters[k]])
        for name in ['mean_bias','mean_physical_wait','p95_coverage','p95_pinball_loss','H_MAE','mean_absolute_physical_H']:
            if name in values:samples[name].append(values[name])
    return {name:np.quantile(values,[.025,.975]).tolist() for name,values in samples.items()}

def assess(rows,overall=False):
    values=metrics(rows)
    if not values:return dict(status='INSUFFICIENT EVIDENCE',count=0)
    enough=values['seeds']>=3
    checks=dict(mean_wait='INSUFFICIENT EVIDENCE',p95='INSUFFICIENT EVIDENCE',externality='INSUFFICIENT EVIDENCE')
    if enough and values['count']>=30:checks['mean_wait']='PASS' if abs(values['mean_bias'])<=values['mean_bias_limit'] else 'FAIL'
    if enough and values['count']>=100:checks['p95']='PASS' if .90<=values['p95_coverage']<=.99 else 'FAIL'
    if values['H_seeds']>=3 and values['H_count']>=30:
        checks['externality']='PASS' if values['H_MAE']<=values['H_MAE_limit'] else 'FAIL'
    status='FAIL' if 'FAIL' in checks.values() else 'INSUFFICIENT EVIDENCE' if 'INSUFFICIENT EVIDENCE' in checks.values() else 'PASS'
    result=dict(status=status,metrics=values,checks=checks,CI95=bootstrap(rows))
    result['note']='Point criteria are user thresholds; episode-bootstrap confidence intervals are reported, not substituted for another acceptance rule.'
    return result

def paired_comparison(primary, baseline, iterations=2000, seed=920100):
    """Report the registered paired-seed comparison; no acceptance-rule change."""
    a=defaultdict(list);b=defaultdict(list)
    for row in primary:a[row['seed']].append(row)
    for row in baseline:b[row['seed']].append(row)
    keys=sorted(set(a)&set(b))
    if set(a)!=set(b) or len(keys)<3:
        return dict(status='INSUFFICIENT EVIDENCE',paired_seed_count=len(keys))
    rng=np.random.RandomState(seed);differences=[]
    for _ in range(iterations):
        draw=rng.choice(keys,len(keys),replace=True)
        ma=metrics([r for key in draw for r in a[key]])
        mb=metrics([r for key in draw for r in b[key]])
        differences.append(ma['p95_pinball_loss']-mb['p95_pinball_loss'])
    return dict(paired_seed_count=len(keys),confidence_unit='paired episode/seed clusters',
        statistic='RANR-AW minus No-Prediction pooled P95 pinball loss',
        difference=metrics(primary)['p95_pinball_loss']-metrics(baseline)['p95_pinball_loss'],
        CI95=np.quantile(differences,[.025,.975]).tolist(),resamples=iterations,rng_seed=seed)

def summarize(rows,counts):
    result={}
    for case in ['normal','high','burst']:
        result[case]={}
        for method in ['RANR-AW','No-Prediction']:
            selected=[r for r in rows if r['case']==case and r['method']==method]
            strata={}
            for name,field,keys in [('station','sid',range(11)),('load','load_bin',range(4)),('time','time_bin',range(4))]:
                strata[name]={str(k):assess([r for r in selected if r[field]==k]) for k in keys}
            result[case][method]=dict(overall=assess(selected,overall=True),strata=strata,
                role='primary predictive model' if method=='RANR-AW' else 'comparison baseline; no requirement to pass forecast validity')
            censored=sum(r['counts'].get('censored_wait',0) for r in counts if r['case']==case and r['method']==method)
            result[case][method]['censored_wait_count']=censored
            if censored and result[case][method]['overall']['status']!='FAIL':
                result[case][method]['overall']['status']='INSUFFICIENT EVIDENCE'
                result[case][method]['overall']['censoring_note']='Reliability of complete waits is conditional; unconditional P95 has not been established.'
        if all(result[case][m]['overall'].get('metrics') for m in ['RANR-AW','No-Prediction']):
            result[case]['pinball_comparison']=dict(
                RANR_AW=result[case]['RANR-AW']['overall']['metrics']['p95_pinball_loss'],
                No_Prediction=result[case]['No-Prediction']['overall']['metrics']['p95_pinball_loss'],
                paired_episode_comparison=paired_comparison(
                    [r for r in rows if r['case']==case and r['method']=='RANR-AW'],
                    [r for r in rows if r['case']==case and r['method']=='No-Prediction']),
                note='Comparative score; no post-hoc improvement threshold.')
    def case_status(case):
        primary=result[case]['RANR-AW']
        statuses=[primary['overall']['status']]+[r['status'] for values in primary['strata'].values() for r in values.values()]
        comparison=result[case].get('pinball_comparison',{}).get('paired_episode_comparison',{})
        reporting=('PASS' if comparison.get('paired_seed_count',0)>=3 and 'CI95' in comparison else 'INSUFFICIENT EVIDENCE')
        result[case]['comparative_reporting_status']=reporting
        statuses.append(reporting)
        return 'FAIL' if 'FAIL' in statuses else 'INSUFFICIENT EVIDENCE' if 'INSUFFICIENT EVIDENCE' in statuses else 'PASS'
    normal=case_status('normal')
    ood={case:case_status(case) for case in ['high','burst']}
    # Any OOD deviation is surfaced for scientific review; severity is not silently
    # invented here. This cannot grant readiness across all three scenarios.
    model='PASS' if normal=='PASS' and all(v=='PASS' for v in ood.values()) else 'SCIENTIFIC_REVIEW_REQUIRED' if normal=='PASS' else normal
    return dict(kind='physical_predictive_validation',passed=model=='PASS',status=model,normal_status=normal,ood_status=ood,
                results=result,counts=counts,confidence_unit='episode/seed clusters',official_training=False,held_out_720=False)
