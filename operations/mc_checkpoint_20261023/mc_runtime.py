"""Checkpoint official Monte Carlo probes without modifying the research model.

The selector fixture is a mechanically derived copy of the registered benchmark.
Each native call evaluates the original estimator with the full sample count and
seed. No samples or criteria change. Python only schedules and assembles rows.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
import fcntl
import hashlib
import io
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

ROOT=Path(os.environ.get('RANR_WORKSPACE','/home/tinnt/Gama_Workspace/Nha Trang CSs planning')).resolve()
sys.path.insert(0,str(ROOT/'src'))
from ranr.paths import digest,write_json
from ranr.gama.headless import provenance,OUTPUT
from ranr.gama.evidence import reference,verify_reference
from ranr.gama import benchmarking

HERE=Path(__file__).resolve().parent
SEED=900001
FIELDS=('method','station','probe','mean','p95','externality','queue_calls')
NUMERIC=('mean','p95','externality')
_CHILDREN={}
_CHILD_LOCK=threading.Lock()
_STOP=threading.Event()


def selected_model(original,root):
    """Only skip selectors/path relocation; estimator and input body unchanged."""
    edits=[('model ranr_prediction_benchmark','model ranr_prediction_benchmark_sharded'),
      ('import "../ranr/Policy.gaml"','import "'+str(root/'models/ranr/Policy.gaml')+'"'),
      ('    init {','    bool ranr_reuse_scenarios <- false;\n    string ranr_project_prefix <- '+json.dumps(str(root)+'/')+';\n    string selected_method <- "";\n    int selected_station <- -1;\n    int selected_probe <- -1;\n    init {'),
      ('            ranr_method <- method;','            if selected_method!="" and selected_method!=method { continue; }\n            ranr_method <- method;'),
      ('            loop sid from: 0 to: 10 {','            loop sid from: 0 to: 10 {\n                if selected_station>=0 and selected_station!=sid { continue; }'),
      ('                loop probe from: 0 to: 4 {','                loop probe from: 0 to: 4 {\n                    if selected_probe>=0 and selected_probe!=probe { continue; }'),
      ('    parameter "Samples" var:ranr_samples;','    parameter "Samples" var:ranr_samples;\n    parameter "Selected method" var:selected_method;\n    parameter "Selected station" var:selected_station;\n    parameter "Selected probe" var:selected_probe;')]
    result=original
    for a,b in edits:
        if result.count(a)!=1:raise ValueError('Benchmark template changed; review derivation: '+a)
        result=result.replace(a,b,1)
    return result


def ensure_model():
    expected=selected_model((ROOT/'models/tests/RanrPredictionBenchmark.gaml').read_text(),ROOT)
    path=HERE/'PredictionShard.gaml'
    if not path.exists() or path.read_text()!=expected:
        raise ValueError('Shard model differs from mechanically derived original')
    return path


def read_table(path,expected=None):
    with Path(path).open() as stream:rows=list(csv.DictReader(stream))
    keys=[tuple(row[k] for k in FIELDS[:3]) for row in rows]
    if len(keys)!=len(set(keys)) or (expected is not None and set(keys)!=set(expected)):
        raise ValueError('Missing/duplicate/unexpected native probe keys: '+str(path))
    for row in rows:
        if any(not math.isfinite(float(row[k])) for k in NUMERIC):
            raise ValueError('Nonfinite native probe: '+str(path))
    return dict(zip(keys,rows))


def semantic_equal(left,right):
    if set(left)!=set(right):return False
    return all(abs(float(left[k][f])-float(right[k][f]))<=1e-7 for k in left for f in NUMERIC)


def shard_identity(calibration,samples,key):
    return {'source':provenance(),'calibration_sha256':digest(Path(calibration)),
        'samples':samples,'key':list(key),'seed':SEED,'model_sha256':digest(ensure_model()),
        'runtime_sha256':digest(Path(__file__)),'full_sample_count_per_probe':True}


def cached_job(folder,identity):
    path=folder/'manifest.json'
    if not path.exists():return None
    manifest=json.loads(path.read_text())
    if manifest.get('identity')!=identity:raise ValueError('Native shard registration changed: '+str(folder))
    if manifest.get('status')!='complete':return None
    for ref in manifest['artifacts']:verify_reference(ref)
    result=read_table(folder/'probe.csv',{tuple(identity['key'])})
    return next(iter(result.values()))


def terminate_owned():
    _STOP.set()
    with _CHILD_LOCK:children=list(_CHILDREN.values())
    for child in children:
        if child.poll() is None:
            try:os.killpg(child.pid,signal.SIGTERM)
            except ProcessLookupError:pass


def compute_job(calibration,samples,key,folder):
    if _STOP.is_set():raise InterruptedError('Supervisor stopping')
    identity=shard_identity(calibration,samples,key)
    cached=cached_job(folder,identity)
    if cached is not None:return cached
    attempt=folder/'attempts'/str(time.time_ns());attempt.mkdir(parents=True)
    output=attempt/'probe.csv';resources=attempt/'resources.json'
    command=[sys.executable,'-B',str(Path(__file__)),'single','--calibration',str(calibration),
        '--samples',str(samples),'--method',key[0],'--station',key[1],'--probe',key[2],
        '--output',str(output),'--resources',str(resources)]
    write_json(folder/'manifest.json',{'identity':identity,'status':'running','attempt':str(attempt),'started_at':time.time()})
    start=time.monotonic()
    env=os.environ.copy();env.update(RANR_JAVA_HEAP_MIB='3072',OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',PYTHONDONTWRITEBYTECODE='1')
    for name in ('JAVA_TOOL_OPTIONS','JDK_JAVA_OPTIONS','_JAVA_OPTIONS'):env.pop(name,None)
    with (attempt/'launch.log').open('w') as log:
        child=subprocess.Popen(command,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        with _CHILD_LOCK:_CHILDREN[child.pid]=child
        try:
            while True:
                if _STOP.is_set():raise InterruptedError('Supervisor stopping')
                try:code=child.wait(timeout=15);break
                except subprocess.TimeoutExpired:
                    write_json(folder/'heartbeat.json',{'pid':child.pid,'updated_at':time.time(),'elapsed_seconds':time.monotonic()-start,'key':list(key),'samples':samples})
            if code:raise RuntimeError(f'Native probe failed exit={code}: {attempt}/launch.log')
            result=read_table(output,{key});row=next(iter(result.values()))
            data=json.loads(resources.read_text())
            if data.get('marker')!='RANR_PREDICTION_BENCHMARK_PASS':raise ValueError('Missing native completion evidence')
            if provenance()!=identity['source']:raise ValueError('Source changed during native probe')
            destination=folder/'probe.csv'
            destination.write_bytes(output.read_bytes())
            write_json(folder/'manifest.json',{'identity':identity,'status':'complete','attempt':str(attempt),
                'elapsed_seconds':time.monotonic()-start,'finished_at':time.time(),
                'artifacts':[reference(destination),reference(output),reference(resources),reference(attempt/'launch.log')]})
            return row
        except BaseException as error:
            write_json(folder/'manifest.json',{'identity':identity,'status':'interrupted' if isinstance(error,(KeyboardInterrupt,InterruptedError)) else 'failed',
                'attempt':str(attempt),'error':str(error),'elapsed_seconds':time.monotonic()-start})
            raise
        finally:
            if child.poll() is None:
                try:os.killpg(child.pid,signal.SIGTERM)
                except ProcessLookupError:pass
                try:child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    try:os.killpg(child.pid,signal.SIGKILL)
                    except ProcessLookupError:pass
                    child.wait()
            with _CHILD_LOCK:_CHILDREN.pop(child.pid,None)


class ScientificReferenceFailure(RuntimeError):
    pass


def conclusive_reference_failure(rows, low):
    """Short-circuit only a mathematically impossible 95% reference pass.

    No incomplete table can pass. At the registered maximum pair 8192/16384,
    three failures among the fixed 55 probes of one method imply at most 52/55.
    """
    failed={method:[] for method in benchmarking.METHODS[:3]}
    for key,row in rows.items():
        errors=[abs(float(row[name])-float(low[key][name])) for name in NUMERIC]
        if any(value>benchmarking.THRESHOLDS[name]*.5 for value,name in zip(errors,NUMERIC)):
            failed[key[0]].append({'key':list(key),'absolute_errors':dict(zip(NUMERIC,errors))})
    for method,failures in failed.items():
        total=sum(key[0]==method for key in benchmarking.PROBE_KEYS)
        upper=(total-len(failures))/total
        if upper<.95:
            return {'method':method,'failed_probes':failures,'maximum_pass_fraction':upper,
                'required_fraction':.95,'total_registered_probes':total,
                'proof':'Every unobserved probe counted as passing; upper bound still below registered threshold'}
    return None


def collect(calibration,samples,folder,workers=3,keys=None,publish=True):
    keys=sorted(benchmarking.PROBE_KEYS if keys is None else keys)
    # Execution order may prioritize known hard probes. The registered grid and
    # estimator never change; only conclusive failures may stop before full grid.
    if samples==16384 and (folder/'reference_stability.json').exists():
        previous=json.loads((folder/'reference_stability.json').read_text())
        priority={tuple(row['key']) for method in previous.get('methods',{}).values() for row in method.get('failed_probes',[])}
        keys.sort(key=lambda key:(key not in priority,key))
    target=folder/f'probes_{samples}.csv'
    if publish and target.exists():return read_table(target,set(keys))
    work=folder/'native_shards'/str(samples);work.mkdir(parents=True,exist_ok=True)
    context={'source':provenance(),'calibration_sha256':digest(Path(calibration)),'samples':samples,
        'keys':[list(k) for k in keys],'workers':workers,'model_sha256':digest(ensure_model()),'runtime_sha256':digest(Path(__file__))}
    registration=work/'registration.json'
    if registration.exists():
        prior=json.loads(registration.read_text())
        if prior!=context:raise ValueError('Shard context changed')
    else:write_json(registration,context)
    rows={};pending=[]
    for key in keys:
        path=work/key[0]/key[1]/key[2]
        cached=cached_job(path,shard_identity(calibration,samples,key))
        if cached is not None:rows[key]=cached
        else:pending.append((key,path))
    prior_time=sum(json.loads(p.read_text()).get('elapsed_seconds',0) for p in work.glob('*/*/*/manifest.json') if json.loads(p.read_text()).get('status')=='complete')
    low = read_table(folder/'probes_8192.csv',benchmarking.PROBE_KEYS) if publish and samples==16384 and (folder/'probes_8192.csv').exists() else None
    start=time.monotonic()
    def progress(status='running',error=None):
        durations=[json.loads((work/k[0]/k[1]/k[2]/'manifest.json').read_text()).get('elapsed_seconds',0) for k in rows]
        average=sum(durations)/len(durations) if durations else None
        write_json(work/'progress.json',{'status':status,'samples':samples,'completed_probes':len(rows),'total_probes':len(keys),
            'updated_at':time.time(),'active_attempt_seconds':time.monotonic()-start,'prior_completed_job_seconds':prior_time,
            'mean_probe_seconds':average,'estimated_remaining_seconds':average*(len(keys)-len(rows))/workers if average else None,
            'error':error,'workers':workers})
    progress()
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures={pool.submit(compute_job,calibration,samples,key,path):key for key,path in pending}
            try:
                for future in as_completed(futures):
                    key=futures[future];rows[key]=future.result();progress()
                    failure=conclusive_reference_failure(rows,low) if low else None
                    if failure:
                        write_json(folder/'conclusive_reference_failure.json',{'source':provenance(),
                            'status':'scientific_gate_failed','pair':[8192,16384],**failure,
                            'observed_probes':len(rows),'full_grid_completed':False,
                            'low_reference':reference(folder/'probes_8192.csv'),
                            'native_shards':[reference(work/k[0]/k[1]/k[2]/'manifest.json') for k in rows],
                            'equivalence':reference(HERE/'equivalence.json')})
                        raise ScientificReferenceFailure('Registered maximum Monte Carlo reference is conclusively unstable: '+str(failure))
            except BaseException:
                terminate_owned()
                for future in futures:future.cancel()
                raise
    except BaseException as error:
        terminate_owned();progress('interrupted' if isinstance(error,(KeyboardInterrupt,InterruptedError)) else 'failed',str(error));raise
    if set(rows)!=set(keys):raise ValueError('Incomplete native shard grid')
    if publish:
        proof=json.loads((HERE/'equivalence.json').read_text())
        if not proof.get('passed') or proof.get('source')!=provenance() or proof.get('runtime_sha256')!=digest(Path(__file__)) or proof.get('model_sha256')!=digest(ensure_model()):
            raise ValueError('Current native sharding equivalence evidence required')
        for ref in proof['dependencies']:verify_reference(ref)
        temporary=target.with_suffix('.csv.partial')
        with temporary.open('w') as stream:
            writer=csv.DictWriter(stream,fieldnames=FIELDS);writer.writeheader();writer.writerows(rows[k] for k in keys)
        read_table(temporary,set(keys))
        write_json(work/'assembly.json',{'source':provenance(),'samples':samples,'equivalence':reference(HERE/'equivalence.json'),
            'rows':[reference(work/k[0]/k[1]/k[2]/'manifest.json') for k in keys],'table_sha256':digest(temporary)})
        temporary.replace(target)
        print(f'NATIVE_SHARDS_COMPLETE samples={samples} probes={len(rows)}',flush=True)
    progress('complete')
    return rows


def single(args):
    from ranr.gama.validation import run_model
    run_model(str(ensure_model()),'ranr_prediction_benchmark',1,'RANR_PREDICTION_BENCHMARK_PASS',{
        'probe_output':('STRING',str(args.output.resolve())),
        'ranr_calibration_file':('STRING',str(args.calibration.resolve())),
        'ranr_samples':('INT',args.samples),'selected_method':('STRING',args.method),
        'selected_station':('INT',args.station),'selected_probe':('INT',args.probe)},seed=SEED,resource_output=args.resources)


def original(calibration,samples,output):
    from ranr.gama.validation import run_model
    run_model('models/tests/RanrPredictionBenchmark.gaml','ranr_prediction_benchmark',1,'RANR_PREDICTION_BENCHMARK_PASS',{
        'probe_output':('STRING',str(output.resolve())),'ranr_calibration_file':('STRING',str(calibration.resolve())),
        'ranr_samples':('INT',samples)},seed=SEED,resource_output=output.with_suffix('.resources.json'))


def oracle(args):
    root=args.output;root.mkdir(parents=True,exist_ok=True)
    table=root/'original_32.csv'
    if not table.exists():original(args.calibration,32,table)
    comparison=collect(args.calibration,32,root,args.workers,publish=False)
    exact=read_table(table,benchmarking.PROBE_KEYS)
    differences=[{'key':list(k),'metric':field,'delta':abs(float(exact[k][field])-float(comparison[k][field]))} for k in exact for field in NUMERIC if abs(float(exact[k][field])-float(comparison[k][field]))>1e-7]
    proof={'passed':not differences,'source':provenance(),'samples':32,'keys':165,'seed':SEED,
        'runtime_sha256':digest(Path(__file__)),'model_sha256':digest(ensure_model()),
        'calibration_sha256':digest(args.calibration),'differences':differences,
        'dependencies':[reference(table),reference(table.with_suffix('.resources.json')),
            *[reference(p) for p in sorted((root/'native_shards/32').glob('*/*/*/manifest.json'))]]}
    write_json(HERE/'equivalence.json',proof)
    if differences:raise ValueError('Sharding changed estimator output; do not deploy')
    print('NATIVE_SHARD_EQUIVALENCE_PASS all 165 probes at fixed seed and 32 samples',flush=True)


def release(args):
    from ranr.gama import release as official
    from ranr.gama.long_collection import collection_lock
    context_path=HERE/'runtime_registration.json'
    identity={'source':provenance(),'model':reference(ensure_model()),'runtime':reference(Path(__file__)),
        'equivalence':reference(HERE/'equivalence.json'),'budget_ledger':reference(HERE/'budget_ledger.py'),'release':str(args.output.resolve()),'workers':args.workers}
    if context_path.exists() and json.loads(context_path.read_text())!=identity:
        raise ValueError('Frozen runtime registration changed')
    write_json(context_path,identity)
    def checkpointed(calibration,folder,samples):
        rows=collect(calibration,samples,folder,args.workers)
        return {k:{field:float(row[field]) for field in NUMERIC} for k,row in rows.items()}
    # Only replace the probe runner. Acceptance, sample grid, fitness,
    # development, training and evaluation use the registered implementation.
    benchmarking._probes=checkpointed
    import ranr.gama.cli as cli
    # Preserve old operational failures, then let current state describe this
    # resumed attempt. The immutable reports and historical logs stay unchanged.
    state_path=args.output/'state.json'
    state=json.loads(state_path.read_text())
    if state.get('error'):
        write_json(HERE/'resume_history'/f'{time.time_ns()}.json',state)
        state.pop('error',None);write_json(state_path,state)
    original_popen=official.subprocess.Popen
    # Accuracy runs as a CLI subprocess, so give it an explicit shim entrypoint;
    # other phases keep the project's CLI unchanged.
    def launch(command,**kwargs):
        if '-m' in command and command[command.index('-m')+1]=='ranr' and 'benchmark' in command:
            idx=command.index('-m');command=command[:idx]+[str(Path(__file__)),'benchmark-shim','--workers',str(args.workers),'--']+command[idx+2:]
        elif '-m' in command and command[command.index('-m')+1]=='ranr' and 'train' in command:
            idx=command.index('-m');command=command[:idx]+[str(Path(__file__)),'training-shim','--']+command[idx+2:]
        return original_popen(command,**kwargs)
    official.subprocess.Popen=launch
    with (OUTPUT/'.release.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with collection_lock():
            try:official.execute(args.output.resolve())
            finally:
                try:
                    from research_audit import audit
                    package,report=audit(args.output.resolve())
                    print('RESEARCH_PACKAGE',package,'research_complete='+str(report['research_complete']),flush=True)
                except Exception as error:
                    write_json(HERE/'audit_failure.json',{'error':str(error),'at':time.time()})


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['single','oracle','release','benchmark-shim','training-shim'])
    parser.add_argument('--calibration',type=Path);parser.add_argument('--samples',type=int)
    parser.add_argument('--method');parser.add_argument('--station',type=int);parser.add_argument('--probe',type=int)
    parser.add_argument('--output',type=Path);parser.add_argument('--resources',type=Path)
    parser.add_argument('--workers',type=int,default=3)
    args,extra=parser.parse_known_args()
    def stop(signum,frame):terminate_owned();raise KeyboardInterrupt('Signal '+str(signum))
    signal.signal(signal.SIGTERM,stop)
    if args.command=='single':single(args)
    elif args.command=='oracle':oracle(args)
    elif args.command=='release':release(args)
    elif args.command=='training-shim':
        from ranr.gama import training
        from budget_ledger import guard
        original_train=training.train
        def protected(config,folder,budget_file,**kwargs):
            with guard(folder,budget_file):return original_train(config,folder,budget_file,**kwargs)
        training.train=protected
        from ranr.gama.cli import main as cli
        sys.argv=['ranr',*(extra[1:] if extra and extra[0]=='--' else extra)]
        cli()
    else:
        def checkpointed(calibration,folder,samples):
            rows=collect(calibration,samples,folder,args.workers)
            return {k:{field:float(row[field]) for field in NUMERIC} for k,row in rows.items()}
        benchmarking._probes=checkpointed
        from ranr.gama.cli import main as cli
        sys.argv=['ranr',*(extra[1:] if extra and extra[0]=='--' else extra)]
        cli()


if __name__=='__main__':main()
