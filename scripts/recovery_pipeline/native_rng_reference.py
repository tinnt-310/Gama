"""Continuous CMA reference scored exclusively from sealed real-GAMA smoke runs.

Never launches a simulator or invents fitness. A changed candidate/config is a
failure, not a request to evaluate additional rollouts. Physical results are used
once and reused read-only for the paired optimizer trajectory comparison.
"""
from dataclasses import asdict
import json
import pickle
from pathlib import Path
import time
import numpy as np

def completed_grid(training):
    training=Path(training)
    return (sorted(training.glob('*/49001/candidates/*/*/*/manifest.json'))
        +sorted(training.glob('*/49001/validation/*/*/manifest.json')))

def execute(config,folder,training,budget,model_proof):
    from ranr.gama import training as canonical
    from ranr.gama.headless import provenance,METHODS,checked_result,parameter_record
    from ranr.gama.evidence import reference
    from ranr.paths import write_json,digest
    from strict_fitness_boundary import StrictNativeRunner
    source=provenance();folder=Path(folder);training=Path(training).resolve()
    final=pickle.loads((training/'checkpoint.pkl').read_bytes())
    if final['status']!='complete' or final['registration']['source']!=source:
        raise ValueError('Completed current-source native smoke required for RNG reference')
    original_clock=json.loads((training/'training_time.json').read_text())
    remaining=6*3600-original_clock['consumed_seconds']
    if remaining<=0:raise ValueError('No isolated smoke allowance remains for RNG comparison')
    destination=folder/'continuous_reference'/'optimizer'
    setting=folder/'continuous_reference_budget.json'
    if destination.exists():raise ValueError('Continuous reference exists; reconcile its spent budget before any retry')
    spec=json.loads(Path(budget).read_text());spec['hours']=remaining/3600
    write_json(setting,spec)
    sealed={str(p):digest(p) for p in completed_grid(training)}
    if len(sealed)!=408:raise ValueError('Complete native smoke grid required before RNG reference')
    for path in sealed:
        manifest=json.loads(Path(path).read_text())
        if (manifest.get('backend')!='GAMA' or manifest.get('synthetic_engineering_fixture')
                or manifest.get('source')!=source or manifest.get('kind')=='scoped_native_result_review'):
            raise ValueError('RNG reference refuses synthetic/historical fitness')
    strict=StrictNativeRunner(lambda c,t,p,**kw:checked_result(p,dict(source=source,
        config=asdict(c),parameters=parameter_record(c.method,t))),training,source)
    reused=[]
    def existing_only(c,theta,target,**kwargs):
        relative=Path(target).relative_to(destination)
        if len(relative.parts)<5 or relative.parts[2] not in ('candidates','validation'):
            raise ValueError('Unexpected continuous reference result request')
        native=training/relative
        manifest=json.loads((native/'manifest.json').read_text())
        if (manifest.get('backend')!='GAMA' or manifest.get('synthetic_engineering_fixture')
                or manifest.get('source')!=source or manifest.get('kind')=='scoped_native_result_review'):
            raise ValueError('RNG reference requires actual current-source real-GAMA smoke results')
        # The genuine sealed-result identity checks exact candidate theta, not
        # generation-local ranks or a surrogate score.
        result=strict(c,theta,native,**kwargs)
        reused.append(native/'manifest.json')
        return result
    previous=canonical.run;canonical.run=existing_only
    try:canonical.train(config,destination,setting,smoke=True)
    finally:canonical.run=previous
    continuous=pickle.loads((destination/'checkpoint.pkl').read_bytes())
    if continuous['status']!='complete' or len(reused)!=408:raise ValueError('Continuous native-fitness reference incomplete')
    comparisons=[]
    for a,b in zip(final['slots'],continuous['slots']):
        same=(a['method']==b['method'] and a['seed']==b['seed'] and a['generation']==b['generation']
            and a['evaluations']==b['evaluations'] and a['best_parameters']==b['best_parameters']
            and a['best_vector']==b['best_vector'] and np.array_equal(a['optimizer'].mean,b['optimizer'].mean)
            and np.array_equal(a['optimizer'].sm.C,b['optimizer'].sm.C)
            and a['optimizer'].sigma==b['optimizer'].sigma
            and pickle.dumps(a['rng'],protocol=5)==pickle.dumps(b['rng'],protocol=5))
        if not same:raise ValueError('Native-fitness continuous/resumed trajectory differs: '+a['method'])
        comparisons.append(dict(method=a['method'],seed=a['seed'],generation=a['generation'],equal=True))
    if len(comparisons)!=4 or [r['method'] for r in comparisons]!=list(METHODS):
        raise ValueError('Native RNG comparison lacks all four methods')
    for p,h in sealed.items():
        if digest(Path(p))!=h:raise ValueError('RNG reference modified/reran completed native result')
    replay_clock=json.loads((destination/'training_time.json').read_text())
    total=original_clock['consumed_seconds']+replay_clock['consumed_seconds']
    if replay_clock['active'] or total>6*3600:raise ValueError('Combined native smoke/reference exceeds isolated6h')
    proof=dict(kind='native_fitness_continuous_resume_comparison',passed=True,source=source,
        methods=list(METHODS),comparisons=comparisons,native_fitness_only=True,
        completed_physical_rollouts=408,additional_physical_rollouts=0,completed_results_preserved=True,
        reference_scope='Uninterrupted real CMA ask/tell using the exact sealed real-GAMA candidate/fixed-validation fitness',
        combined_smoke_active_seconds=total,official_training=False,
        dependencies=[reference(model_proof),reference(training/'checkpoint.pkl'),reference(training/'training_time.json'),
            reference(destination/'checkpoint.pkl'),reference(destination/'training_time.json'),reference(setting),
            *[reference(p) for p in reused]])
    path=folder/'native_rng_comparison.json';write_json(path,proof)
    return proof
