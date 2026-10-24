"""Checkpoint absolute Monte Carlo sample ranges; GAMA computes final statistics.

Every configured probe still has N samples. Python verifies ranges/identities,
schedules native jobs and concatenates raw numbers. NativeAggregate.gaml runs
the original GAMA mean/quantile on the ordered full sample set.
"""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
from collections import deque
import argparse,csv,fcntl,json,math,os,signal,subprocess,sys,time
import chunk_models
ROOT=chunk_models.ROOT;LEGACY=chunk_models.LEGACY;HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'src'))
import mc_runtime as old
from ranr.paths import write_json,digest
from ranr.gama.headless import provenance,OUTPUT
from ranr.gama.evidence import reference,verify_reference
from ranr.gama import benchmarking
FIELDS=old.FIELDS;NUMERIC=old.NUMERIC;SEED=old.SEED


def code_identity():
    chunk_models.verify(HERE)
    return {name:digest(HERE/name) for name in ('chunk_runtime.py','chunk_models.py','PredictionChunk.gaml','NativeAggregate.gaml')}


def ranges(samples,size):
    if samples<=0 or size<=0:raise ValueError('Positive sample counts required')
    return [(begin,min(samples,begin+size)) for begin in range(0,samples,size)]


def identity(calibration,samples,key):
    return {'source':provenance(),'calibration_sha256':digest(Path(calibration)),'samples':samples,'key':list(key),
            'seed':SEED,'code':code_identity(),'full_sample_count_per_probe':True}


def cached(folder,expected):
    path=folder/'manifest.json'
    if not path.exists():return None
    data=json.loads(path.read_text())
    if data['identity']!=expected:raise ValueError('Native chunk identity changed: '+str(folder))
    if data['status']!='complete':return None
    for ref in data['artifacts']:verify_reference(ref)
    return data


def run_job(task,expected,folder):
    result=cached(folder,expected)
    if result is not None:return result
    if old._STOP.is_set():raise InterruptedError('Supervisor stopping')
    prior=folder/'manifest.json'
    if prior.exists():
        history=folder/'manifest_history'/f'{time.time_ns()}.json';history.parent.mkdir(parents=True,exist_ok=True);history.write_bytes(prior.read_bytes())
    attempt=folder/'attempts'/str(time.time_ns());attempt.mkdir(parents=True)
    task={**task,'attempt':str(attempt)};write_json(attempt/'task.json',task)
    write_json(folder/'manifest.json',{'identity':expected,'status':'running','attempt':str(attempt),'started_at':time.time()})
    started=time.monotonic()
    env=os.environ.copy();env.update(RANR_JAVA_HEAP_MIB='1536',OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',PYTHONDONTWRITEBYTECODE='1')
    for name in ('JAVA_TOOL_OPTIONS','JDK_JAVA_OPTIONS','_JAVA_OPTIONS'):env.pop(name,None)
    child=None
    try:
        with (attempt/'launch.log').open('w') as log:
            child=subprocess.Popen([sys.executable,'-B',str(Path(__file__)),'native-job','--task',str(attempt/'task.json')],
                cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            with old._CHILD_LOCK:old._CHILDREN[child.pid]=child
            while True:
                if old._STOP.is_set():raise InterruptedError('Supervisor stopping')
                try:code=child.wait(timeout=15);break
                except subprocess.TimeoutExpired:write_json(folder/'heartbeat.json',{'pid':child.pid,'updated_at':time.time(),'elapsed_seconds':time.monotonic()-started,'key':expected['key'],'samples':expected['samples'],'range':expected.get('range')})
        if code:raise RuntimeError(f'Native chunk failed ({code}): {attempt}/launch.log')
        resource=json.loads((attempt/'resources.json').read_text())
        marker='RANR_PREDICTION_BENCHMARK_PASS' if task['kind']=='chunk' else 'RANR_NATIVE_AGGREGATION_PASS'
        if resource.get('marker')!=marker:raise ValueError('Missing native completion marker')
        if provenance()!=expected['source'] or code_identity()!=expected['code']:raise ValueError('Source changed during native chunk')
        filename='raw.json' if task['kind']=='chunk' else 'probe.csv'
        (folder/filename).write_bytes((attempt/filename).read_bytes())
        if task['kind']=='chunk':read_raw(folder/'raw.json',expected)
        else:old.read_table(folder/'probe.csv',{tuple(expected['key'])})
        artifacts=[reference(p) for p in sorted(attempt.iterdir()) if p.is_file()]+[reference(folder/filename)]
        data={'identity':expected,'status':'complete','attempt':str(attempt),'elapsed_seconds':time.monotonic()-started,
              'finished_at':time.time(),'artifacts':artifacts}
        write_json(folder/'manifest.json',data);return data
    except BaseException as error:
        write_json(folder/'manifest.json',{'identity':expected,'status':'interrupted' if isinstance(error,(KeyboardInterrupt,InterruptedError)) else 'failed',
            'attempt':str(attempt),'elapsed_seconds':time.monotonic()-started,'error':str(error)})
        raise
    finally:
        if child is not None:
            if child.poll() is None:
                try:os.killpg(child.pid,signal.SIGTERM)
                except ProcessLookupError:pass
                try:child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    try:os.killpg(child.pid,signal.SIGKILL)
                    except ProcessLookupError:pass
                    child.wait()
            with old._CHILD_LOCK:old._CHILDREN.pop(child.pid,None)


def read_raw(path,expected):
    rows=json.loads(Path(path).read_text())
    if len(rows)!=1:raise ValueError('Exactly one native raw probe expected')
    row=rows[0];key=(str(row['method']),str(row['station']),str(row['probe']))
    begin,end=expected['range']
    if key!=tuple(expected['key']) or row['sample_begin']!=begin or row['sample_end']!=end or row['configured_samples']!=expected['samples']:
        raise ValueError('Raw native sample range/configuration mismatch')
    if begin<0 or end<=begin or end>expected['samples']:raise ValueError('Invalid sample index range')
    for name in ('waits','externalities'):
        if len(row[name])!=end-begin or not all(isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x) for x in row[name]):
            raise ValueError('Missing or nonfinite native sample values')
    return row


def aggregation_input(parts,samples,key):
    cursor=0
    for part in parts:
        if part['sample_begin']!=cursor or part['sample_end']<=cursor or part['configured_samples']!=samples:
            raise ValueError('Missing, overlapping or reordered absolute sample ranges')
        if (str(part['method']),str(part['station']),str(part['probe']))!=tuple(key):raise ValueError('Mixed probe keys')
        cursor=part['sample_end']
    if cursor!=samples:raise ValueError('Incomplete full sample count')
    return {'samples':samples,'method':key[0],'station':int(key[1]),'probe':int(key[2]),'chunks':parts}


def finish_probe(base,expected,parts):
    cached_manifest=cached(base/'aggregate',expected)
    if cached_manifest is None:
        payload=aggregation_input(parts,expected['samples'],expected['key'])
        cached_manifest=run_job({'kind':'aggregate','payload':payload},expected,base/'aggregate')
    row=next(iter(old.read_table(base/'aggregate/probe.csv',{tuple(expected['key'])}).values()))
    (base/'probe.csv').write_bytes((base/'aggregate/probe.csv').read_bytes())
    artifacts=[reference(base/'probe.csv'),reference(base/'aggregate/manifest.json'),*cached_manifest['artifacts']]
    for path in sorted((base/'chunks').glob('*/manifest.json')):
        manifest=json.loads(path.read_text());artifacts.extend([reference(path),*manifest['artifacts']])
    write_json(base/'manifest.json',{'identity':expected,'status':'complete','artifacts':artifacts,'origin':'native_absolute_chunks_and_native_full_aggregation','finished_at':time.time()})
    return row


def adopt_legacy(calibration,samples,key,base,expected,folder):
    native=folder/'native_shards'/str(samples)/key[0]/key[1]/key[2]
    data=old.cached_job(native,old.shard_identity(calibration,samples,key))
    if data is None:return None
    proof=json.loads((LEGACY/'equivalence.json').read_text())
    if not proof.get('passed') or proof['source']!=expected['source'] or proof['runtime_sha256']!=digest(LEGACY/'mc_runtime.py'):
        raise ValueError('Legacy native equivalence changed')
    for ref in proof['dependencies']:verify_reference(ref)
    original=json.loads((native/'manifest.json').read_text());base.mkdir(parents=True,exist_ok=True)
    (base/'probe.csv').write_bytes((native/'probe.csv').read_bytes())
    write_json(base/'manifest.json',{'identity':expected,'status':'complete','origin':'verified_full_count_native_v1',
        'artifacts':[reference(base/'probe.csv'),reference(native/'manifest.json'),reference(LEGACY/'equivalence.json'),*original['artifacts']]})
    return data


def collect(calibration,samples,folder,workers=6,keys=None,publish=True,chunk_size=None,adopt=True):
    calibration=Path(calibration);folder=Path(folder);keys=sorted(benchmarking.PROBE_KEYS if keys is None else keys)
    if publish and (folder/f'probes_{samples}.csv').exists():return old.read_table(folder/f'probes_{samples}.csv',set(keys))
    if samples==16384 and (folder/'reference_stability.json').exists():
        record=json.loads((folder/'reference_stability.json').read_text());priority={tuple(row['key']) for method in record['methods'].values() for row in method['failed_probes']}
        keys.sort(key=lambda key:(key not in priority,key))
    work=folder/'native_chunks'/str(samples);work.mkdir(parents=True,exist_ok=True)
    context={'source':provenance(),'calibration_sha256':digest(calibration),'samples':samples,'keys':[list(k) for k in keys],'code':code_identity(),'chunk_size_override':chunk_size}
    registration=work/'registration.json'
    if registration.exists() and json.loads(registration.read_text())!=context:raise ValueError('Native chunk context changed')
    write_json(registration,context)
    rows={};todo=deque();parts={};identities={};pending={};chunk_counts={};completed_chunks=0;started=time.monotonic()
    for key in keys:
        base=work/key[0]/key[1]/key[2];expected=identity(calibration,samples,key);identities[key]=expected
        existing=cached(base,expected)
        if existing:
            path=base/'probe.csv'
            rows[key]=next(iter(old.read_table(path,{key}).values()));continue
        inherited=adopt_legacy(calibration,samples,key,base,expected,folder) if adopt else None
        if inherited is not None:rows[key]=inherited;continue
        size=chunk_size or (samples if key[0]=='No-Prediction' or (key[0]=='No-P2P' and int(key[2])<3) else min(samples,1024))
        parts[key]={};pending_ranges=[]
        for begin,end in ranges(samples,size):
            path=base/'chunks'/f'{begin}_{end}';item={**expected,'range':[begin,end],'full_sample_count_per_probe':False}
            if cached(path,item):parts[key][begin]=read_raw(path/'raw.json',item);completed_chunks+=1
            else:pending_ranges.append(('chunk',key,begin,end,path,item))
        chunk_counts[key]=len(pending_ranges)
        if pending_ranges:todo.extend(pending_ranges)
        else:todo.append(('aggregate',key))
    low=old.read_table(folder/'probes_8192.csv',benchmarking.PROBE_KEYS) if publish and samples==16384 and (folder/'probes_8192.csv').exists() else None
    def progress(status='running',error=None):
        write_json(work/'progress.json',{'status':status,'samples':samples,'completed_probes':len(rows),'total_probes':len(keys),
            'completed_chunks':completed_chunks,'pending_tasks':len(todo)+len(pending),'workers':workers,'updated_at':time.time(),
            'active_attempt_seconds':time.monotonic()-started,'error':error,'statistics_backend':'GAMA native full ordered sample aggregation'})
    progress()
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            try:
                while todo or pending:
                    while todo and len(pending)<workers:
                        task=todo.popleft();key=task[1];base=work/key[0]/key[1]/key[2]
                        if task[0]=='chunk':
                            _,_,begin,end,path,item=task
                            future=pool.submit(run_job,{'kind':'chunk','calibration':str(calibration),'samples':samples,'key':list(key),'begin':begin,'end':end},item,path)
                        else:future=pool.submit(finish_probe,base,identities[key],[parts[key][begin] for begin in sorted(parts[key])])
                        pending[future]=task
                    done,_=wait(pending,timeout=30,return_when=FIRST_COMPLETED)
                    for future in done:
                        task=pending.pop(future);key=task[1];value=future.result()
                        if task[0]=='chunk':
                            _,_,begin,end,path,item=task;parts[key][begin]=read_raw(path/'raw.json',item)
                            chunk_counts[key]-=1;completed_chunks+=1
                            if chunk_counts[key]==0:todo.appendleft(('aggregate',key))
                        else:rows[key]=value
                        progress()
                        failure=old.conclusive_reference_failure(rows,low) if low else None
                        if failure:
                            write_json(folder/'conclusive_reference_failure.json',{'source':provenance(),'status':'scientific_gate_failed','pair':[8192,16384],**failure,
                                'observed_probes':len(rows),'full_grid_completed':False,'low_reference':reference(folder/'probes_8192.csv'),
                                'native_shards':[reference(work/k[0]/k[1]/k[2]/'manifest.json') for k in rows],'equivalence':reference(HERE/'equivalence.json')})
                            raise old.ScientificReferenceFailure('Registered maximum reference conclusively failed: '+str(failure))
                    if not done:progress()
            except BaseException:
                old.terminate_owned()
                for future in pending:future.cancel()
                raise
        if set(rows)!=set(keys):raise ValueError('Incomplete native probe grid')
        if publish:
            proof=verify_equivalence()
            if proof['calibration_sha256']!=digest(calibration):raise ValueError('Equivalence calibration changed')
            target=folder/f'probes_{samples}.csv';temporary=target.with_suffix('.csv.partial')
            with temporary.open('w') as stream:
                writer=csv.DictWriter(stream,fieldnames=FIELDS);writer.writeheader();writer.writerows(rows[k] for k in sorted(keys))
            old.read_table(temporary,set(keys))
            write_json(work/'assembly.json',{'source':provenance(),'samples':samples,'equivalence':reference(HERE/'equivalence.json'),'table_sha256':digest(temporary),
                'native_probes':[reference(work/k[0]/k[1]/k[2]/'manifest.json') for k in keys]})
            temporary.replace(target)
        progress('complete');return rows
    except BaseException as error:
        old.terminate_owned();progress('interrupted' if isinstance(error,(KeyboardInterrupt,InterruptedError)) else 'failed',str(error));raise


def verify_equivalence():
    proof=json.loads((HERE/'equivalence.json').read_text())
    if not proof.get('passed') or proof['source']!=provenance() or proof['code']!=code_identity() or proof['keys']!=165:
        raise ValueError('Current full-grid native chunk equivalence required')
    for ref in proof['dependencies']:verify_reference(ref)
    return proof


def native_job(task):
    from ranr.gama.validation import run_model
    attempt=Path(task['attempt'])
    if task['kind']=='chunk':
        key=task['key']
        parameters={'probe_output':('STRING',str(attempt/'diagnostic.csv')),'raw_output':('STRING',str(attempt/'raw.json')),
            'ranr_calibration_file':('STRING',task['calibration']),'ranr_samples':('INT',task['samples']),
            'selected_method':('STRING',key[0]),'selected_station':('INT',int(key[1])),'selected_probe':('INT',int(key[2])),
            'sample_begin':('INT',task['begin']),'sample_end':('INT',task['end'])}
        run_model(str(HERE/'PredictionChunk.gaml'),'ranr_prediction_benchmark',1,'RANR_PREDICTION_BENCHMARK_PASS',parameters,seed=SEED,resource_output=attempt/'resources.json')
    else:
        write_json(attempt/'input.json',task['payload'])
        run_model(str(HERE/'NativeAggregate.gaml'),'ranr_native_aggregation',1,'RANR_NATIVE_AGGREGATION_PASS',{
            'aggregate_input':('STRING',str(attempt/'input.json')),'aggregate_output':('STRING',str(attempt/'probe.csv'))},seed=SEED,resource_output=attempt/'resources.json')


def oracle(args):
    baseline=ROOT/'outputs/gama_ranr/autonomous_20261023/equivalence_execution/original_32.csv'
    original=old.read_table(baseline,benchmarking.PROBE_KEYS)
    observed=collect(args.calibration,32,args.output,args.workers,publish=False,chunk_size=16,adopt=False)
    differences=[{'key':list(k),'metric':name,'delta':abs(float(observed[k][name])-float(original[k][name]))} for k in original for name in NUMERIC if abs(float(observed[k][name])-float(original[k][name]))>1e-7]
    dependencies=[reference(baseline),reference(LEGACY/'equivalence.json'),*[reference(p) for p in sorted((args.output/'native_chunks/32').rglob('*')) if p.is_file()]]
    proof={'passed':not differences,'source':provenance(),'samples':32,'keys':165,'seed':SEED,'ranges':[[0,16],[16,32]],'code':code_identity(),
        'runtime_sha256':digest(Path(__file__)),'model_sha256':digest(HERE/'PredictionChunk.gaml'),'calibration_sha256':digest(args.calibration),
        'differences':differences,'dependencies':dependencies,'statistics_backend':'GAMA original mean/quantile on full absolute ordered samples'}
    write_json(HERE/'equivalence.json',proof)
    if differences:raise ValueError('Native sample chunks differ from original estimator')
    print('NATIVE_CHUNK_FULL_GRID_EQUIVALENCE_PASS 165/165',flush=True)


def release(args):
    from ranr.gama import release as official
    from ranr.gama.long_collection import collection_lock
    verify_equivalence()
    registration={'source':provenance(),'code':code_identity(),'equivalence':reference(HERE/'equivalence.json'),'legacy_runtime':reference(LEGACY/'mc_runtime.py'),
                  'budget_ledger':reference(LEGACY/'budget_ledger.py'),'release':str(args.output.resolve()),'workers':args.workers}
    path=HERE/'runtime_registration.json'
    if path.exists() and json.loads(path.read_text())!=registration:raise ValueError('Frozen native chunk runtime changed')
    write_json(path,registration)
    state_path=args.output/'state.json';state=json.loads(state_path.read_text())
    if state.get('error'):
        write_json(HERE/'resume_history'/f'{time.time_ns()}.json',state);state.pop('error');write_json(state_path,state)
    original=official.subprocess.Popen
    def launch(command,**kwargs):
        if '-m' in command and command[command.index('-m')+1]=='ranr':
            index=command.index('-m')
            if 'benchmark' in command:command=command[:index]+[str(Path(__file__)),'benchmark-shim','--workers',str(args.workers),'--']+command[index+2:]
            elif 'train' in command:command=command[:index]+[str(LEGACY/'mc_runtime.py'),'training-shim','--']+command[index+2:]
        return original(command,**kwargs)
    official.subprocess.Popen=launch
    with (OUTPUT/'.release.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with collection_lock():
            try:official.execute(args.output.resolve())
            finally:
                try:
                    sys.path.insert(0,str(ROOT/'operations/research_reporting_20261023'))
                    from finalize_report import finalize
                    finalize(args.output.resolve())
                except Exception as error:write_json(HERE/'audit_failure.json',{'error':str(error),'at':time.time()})


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=['native-job','oracle','release','benchmark-shim'])
    parser.add_argument('--task',type=Path);parser.add_argument('--output',type=Path);parser.add_argument('--calibration',type=Path);parser.add_argument('--workers',type=int,default=6)
    args,extra=parser.parse_known_args()
    def stop(signum,frame):old.terminate_owned();raise KeyboardInterrupt('Signal '+str(signum))
    signal.signal(signal.SIGTERM,stop)
    if args.command=='native-job':native_job(json.loads(args.task.read_text()))
    elif args.command=='oracle':oracle(args)
    elif args.command=='release':release(args)
    else:
        verify_equivalence()
        def probes(calibration,folder,samples):
            rows=collect(calibration,samples,folder,args.workers)
            return {key:{name:float(row[name]) for name in NUMERIC} for key,row in rows.items()}
        benchmarking._probes=probes
        from ranr.gama.cli import main as cli
        sys.argv=['ranr',*(extra[1:] if extra and extra[0]=='--' else extra)];cli()


if __name__=='__main__':main()
