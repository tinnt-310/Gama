"""Checkpointed CMA-ES, ranked lexicographically from validated native GAMA results."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from pathlib import Path
import fcntl
import json
import pickle
import time
import shutil
import numpy as np
import cma
from ..paths import write_json, digest
from .headless import RunConfig, METHODS, CASES, OUTPUT, provenance, parameter_record, run
from .contracts import (OBJECTIVE_VERSION, OBJECTIVE_CONFIG_HASH, OBJECTIVE_SPEC,
                        aggregate_fitness, rank_fitness_vectors, validate_paired_results)
from .training_time import durable_replace, TrainingClock, elapsed_guard


def _save(path: Path, value: object) -> None:
    durable_replace(path, pickle.dumps(value,pickle.HIGHEST_PROTOCOL))


def validation_improved(candidate, incumbent):
    if incumbent is None: return True
    if tuple(candidate[:4]) != tuple(incumbent[:4]):
        return tuple(candidate[:4]) < tuple(incumbent[:4])
    return incumbent[4]-candidate[4] > OBJECTIVE_SPEC['validation_relative_improvement']*max(abs(incumbent[4]),1e-9)


def generation_fitness(groups, design):
    """Validate the complete generation BEFORE tell; preserve candidate order."""
    vectors=[aggregate_fitness(rows,design) for rows in groups]
    validate_paired_results(groups)
    return vectors,rank_fitness_vectors(vectors)


def _evaluate(config,method,theta,folder,seed,workers,remaining=None):
    design=[(case,seed+i) for i,case in enumerate(CASES)]
    expires=time.monotonic()+remaining if remaining is not None else None
    def execute(item):
        from .monitoring import check_training_cancelled
        check_training_cancelled()
        case,episode_seed=item
        target=folder/case
        row=run(replace(config,method=method,case=case,seed=episode_seed),theta,target,
                resume=target.exists(),wall_limit=max(.001,expires-time.monotonic()) if expires else None)
        return {**row,'case':case,'seed':episode_seed}
    with ThreadPoolExecutor(max_workers=workers) as pool: rows=list(pool.map(execute,design))
    return aggregate_fitness(rows,design),rows


def train(config:RunConfig,folder:Path,budget_file:Path,*,resume=False,smoke=False,workers_override=None):
    from .execution import assert_checkout_modules
    assert_checkout_modules()
    specification=json.loads(budget_file.read_text())
    if smoke and not config.development: raise ValueError('Optimizer smoke requires development configuration')
    if not smoke:
        if config.development or config.calibrating: raise ValueError('Official training requires calibrated configuration')
        if not all(specification.get(k) for k in ('passed','accuracy_passed','validation_passed')):
            raise ValueError('Validated GAMA benchmark required')
        freeze=json.loads((OUTPUT/'design_freeze.json').read_text())
        from .design import validate_freeze
        validate_freeze(OUTPUT/'design_freeze.json',config)
        if (freeze.get('source')!=provenance() or freeze.get('objective_version')!=OBJECTIVE_VERSION
            or freeze.get('objective_config_hash')!=OBJECTIVE_CONFIG_HASH
            or not all(freeze.get(k) is True for k in ('passed','calibration_passed','information_passed','exposure_passed','objective_sensitivity_passed','design_validation_passed'))):
            raise ValueError('Current-source scientific design freeze required')
        for name in ('temperature','p2p_interval','stabilization'):
            if freeze.get('selected_config',{}).get(name)!=getattr(config,name): raise ValueError('Configuration differs from frozen design: '+name)
        physical=json.loads((OUTPUT/'development_validation.json').read_text())
        from .development import verify_development
        verify_development(OUTPUT/'development_validation.json',config)
        if physical.get('passed') is not True or physical.get('source')!=provenance(): raise ValueError('Current physical validation required')
        if specification.get('source')!=provenance() or specification.get('locked_config')!=asdict(config): raise ValueError('Benchmark configuration/source changed')
        if specification.get('training_only') is not True or specification.get('budget_schema') != 2:
            raise ValueError('Benchmark must register a separate training-only budget')
        from .evidence import read_reference, read_evidence
        read_evidence(budget_file)
        read_reference(specification['accuracy_evidence'])
        read_evidence(specification['accuracy_evidence']['path'])
        if specification['hours']>72 or specification['optimizer_seeds']!=[41001,41002,41003]: raise ValueError('Registered training allowance/seed protocol changed')
        from .evidence import verify_training_acceptance
        verify_training_acceptance(OUTPUT/'pre_training_acceptance.json')
    maximum=specification['budget']['max_evaluations']; minimum=specification['budget']['min_evaluations']
    interval=specification['budget']['validation_every']; workers=workers_override or specification['workers']
    if workers<1 or (not smoke and workers>specification['workers']): raise ValueError('Invalid worker count')
    identity={'source':provenance(),'config':asdict(config),'budget_sha256':digest(budget_file),
              'profile':'smoke' if smoke else 'research','objective_version':OBJECTIVE_VERSION,
              'objective_config_hash':OBJECTIVE_CONFIG_HASH,'checkpoint_schema':6,
              'calibration_sha256':digest(Path(config.calibration)) if config.calibration else None,
              'candidate_design':[(case,11001+i) for i,case in enumerate(CASES)],
              'validation_design':[(case,21001+i) for i,case in enumerate(CASES)]}
    folder.mkdir(parents=True,exist_ok=True)
    with (folder/'.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        checkpoint=folder/'checkpoint.pkl'
        if checkpoint.exists():
            if not resume: raise ValueError('Existing training: use --resume')
            if not (folder/'training_time.json').is_file():
                raise ValueError('Missing durable training journal; reconcile before resume')
            state=pickle.loads(checkpoint.read_bytes())
            if state.get('registration')!=identity: raise ValueError('Training registration changed; incompatible checkpoint')
            # Pickle copies bound RandomState.randn; restore the registered
            # global generator controlled by each slot's saved rng state.
            for slot in state['slots']:
                optimizer=slot['optimizer']
                for generator in (optimizer.opts['randn'],optimizer.sm.randn):
                    if (getattr(generator,'__name__',None)!='randn' or
                            not isinstance(getattr(generator,'__self__',None),np.random.RandomState)):
                        raise ValueError('Unsupported checkpoint sampler RNG; explicit migration required')
                optimizer.opts['randn']=np.random.randn
                optimizer.sm.randn=np.random.randn
        else:
            if resume: raise ValueError('No checkpoint to resume')
            slots=[]
            for optimizer_seed in specification['optimizer_seeds']:
                for method in METHODS:
                    optimizer=cma.CMAEvolutionStrategy(np.zeros(4 if method=='Fixed-Weights' else 20),1.,
                        {'seed':optimizer_seed,'popsize':16,'verbose':-9,'CMA_elitist':False})
                    slots.append(dict(method=method,seed=optimizer_seed,optimizer=optimizer,rng=np.random.get_state(),
                        evaluations=0,generation=0,pending=None,pending_validation=None,history=[],
                        best_vector=None,best_parameters=None,stale=0,done=False))
            state={'registration':identity,'slots':slots,'active_seconds':0.,'status':'running','paired_reference':{}}
            _save(checkpoint,state)
        limit=training_limit(specification)
        clock=TrainingClock(folder,identity,state['active_seconds'],limit)
        with elapsed_guard(clock):
            def account(): state['active_seconds']=clock.consumed()
            def remaining():
                account();return limit-state['active_seconds']
            def save(status=None):
                account()
                if status:state['status']=status
                _save(checkpoint,state)
                write_json(folder/'registration.json',{**identity,'status':state['status'],'active_seconds':state['active_seconds']})
            def paired(rows,stage):
                for row in rows:
                    key=f'{stage}:{row["case"]}:{row["seed"]}'
                    value=[row['exogenous_hash'],row['planned_ev_days']]
                    if key in state['paired_reference'] and state['paired_reference'][key]!=value:
                        raise ValueError('Cross-method/candidate exogenous pairing mismatch: '+key)
                    state['paired_reference'][key]=value
            try:
                save('running')
                while any(not slot['done'] for slot in state['slots']):
                    for slot in state['slots']:
                        if slot['done']:continue
                        from .monitoring import check_training_cancelled
                        check_training_cancelled()
                        if remaining()<=0:save('budget_limited');return {'status':'budget_limited'}
                        root=folder/slot['method']/str(slot['seed'])
                        if slot['pending_validation'] is not None:
                            pending=slot['pending_validation'];theta=pending['parameters']
                            vector,rows=_evaluate(config,slot['method'],theta,root/'validation'/str(slot['evaluations']),21001,workers,remaining())
                            paired(rows,'validation')
                            improved=validation_improved(vector,slot['best_vector'])
                            slot['stale']=0 if improved else slot['stale']+1
                            if slot['best_vector'] is None or tuple(vector)<tuple(slot['best_vector']):
                                slot['best_vector']=vector;slot['best_parameters']=theta
                            pending['row'].update(validation_fitness_vector=vector,validation_parameters=theta)
                            slot['history'].append(pending['row']);slot['pending_validation']=None
                            slot['done']=slot['evaluations']>=maximum or (slot['evaluations']>=minimum and slot['stale']>=3)
                            write_json(root/'history.json',slot['history']);save();continue
                        if slot['pending'] is None:
                            np.random.set_state(slot['rng']);slot['pending']=slot['optimizer'].ask();slot['rng']=np.random.get_state();save()
                        population=len(slot['pending']);work=[]
                        expires=time.monotonic()+remaining()
                        for index,theta in enumerate(slot['pending']):
                            for case,seed in identity['candidate_design']:
                                work.append((replace(config,method=slot['method'],case=case,seed=seed),list(theta),root/'candidates'/str(slot['generation'])/str(index)/case))
                        def execute(job):
                            from .monitoring import check_training_cancelled
                            check_training_cancelled()
                            setting,theta,target=job
                            result=run(setting,theta,target,resume=target.exists(),wall_limit=max(.001,expires-time.monotonic()))
                            return {**result,'case':setting.case,'seed':setting.seed}
                        with ThreadPoolExecutor(max_workers=workers) as pool: results=list(pool.map(execute,work))
                        groups=[results[i*len(CASES):(i+1)*len(CASES)] for i in range(population)]
                        vectors,ranks=generation_fitness(groups,identity['candidate_design'])
                        for rows in groups:paired(rows,'candidate')
                        winner=min(range(population),key=lambda i:tuple(vectors[i]));theta=list(slot['pending'][winner])
                        records=[dict(candidate=i,parameters=list(slot['pending'][i]),fitness_vector=vectors[i],
                                      generation_rank=ranks[i],operational_objective=vectors[i][4],
                                      objective_version=OBJECTIVE_VERSION,objective_config_hash=OBJECTIVE_CONFIG_HASH) for i in range(population)]
                        write_json(root/'generations'/f'{slot["generation"]}.json',records)
                        np.random.set_state(slot['rng']);slot['optimizer'].tell(slot['pending'],ranks);slot['rng']=np.random.get_state()
                        slot['pending']=None;slot['evaluations']+=population;slot['generation']+=1
                        row=dict(evaluations=slot['evaluations'],generation=slot['generation'],fitness_vector=vectors[winner],
                                 operational_objective=vectors[winner][4],generation_rank=0.,rollouts=len(results),
                                 cpu_seconds=sum(r.get('cpu_seconds',0) for r in results))
                        if slot['evaluations']%interval==0 or slot['evaluations']>=maximum:
                            slot['pending_validation']={'parameters':theta,'row':row}
                        else:slot['history'].append(row)
                        write_json(root/'history.json',slot['history']);save()
                # Fixed validation vectors, never generation-local ranks, select publication.
                for method in METHODS:
                    options=[s for s in state['slots'] if s['method']==method and s['best_vector'] is not None]
                    if not options:raise ValueError('No validated candidate')
                    winner=min(options,key=lambda s:tuple(s['best_vector']))
                    result=parameter_record(method,winner['best_parameters'],trained=not smoke,profile=identity['profile'],
                        source=identity['source'],validation_fitness_vector=winner['best_vector'],
                        operational_objective=winner['best_vector'][4],optimizer_seed=winner['seed'],
                        config=asdict(config),calibration_sha256=identity['calibration_sha256'],budget_sha256=identity['budget_sha256'])
                    write_json(folder/method/'parameters.json',result)
                if not smoke:
                    for method in METHODS:
                        target=OUTPUT/'models'/method;target.mkdir(parents=True,exist_ok=True)
                        if (target/'parameters.json').exists():shutil.copy2(target/'parameters.json',target/f'parameters_{time.time_ns()}.json')
                        shutil.copy2(folder/method/'parameters.json',target/'parameters.json')
                save('complete');return {'status':'complete','active_seconds':state['active_seconds']}
            except BaseException as error:
                if isinstance(error, TimeoutError) and remaining() <= 0:
                    save('budget_limited')
                    return {'status':'budget_limited','active_seconds':state['active_seconds']}
                state['error']=str(error);save('invalid_evaluation' if isinstance(error,ValueError) else 'interrupted')
                write_json(folder/'diagnostic.json',{'error':str(error),'objective_version':OBJECTIVE_VERSION,'objective_config_hash':OBJECTIVE_CONFIG_HASH})
                raise


def training_limit(specification):
    """Elapsed active training only; design/benchmark/evaluation have separate accounts."""
    hours = specification['hours']
    if not np.isfinite(hours) or not 0 < hours <= 72:
        raise ValueError('Training allowance must be finite and at most 72 hours')
    return hours * 3600
