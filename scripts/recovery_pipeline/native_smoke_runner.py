"""Isolated real-GAMA CMA-ES smoke and controlled SIGTERM/resume acceptance."""
from pathlib import Path
from dataclasses import asdict,replace
import fcntl
import hashlib
import json
import os
import pickle
import signal
import shutil
import subprocess
import sys
import time
import numpy as np

BASE=Path(__file__).resolve().parent
SOURCE=Path(__file__).resolve().parents[2]

def fingerprint(value):return hashlib.sha256(pickle.dumps(value,protocol=5)).hexdigest()

def execute(config,folder,model_proof,status):
    from ranr.gama.headless import provenance,METHODS,load_model
    from ranr.paths import write_json,digest
    proof=json.loads(Path(model_proof).read_text())
    if proof.get('passed') is not True or proof.get('kind')!='model_validation_acceptance' or proof.get('source')!=provenance():
        raise ValueError('Model validation must pass before native optimizer smoke')
    folder=Path(folder);folder.mkdir(exist_ok=True,parents=True)
    smoke=replace(config,development=True,calibrating=False,initial_hour=6.,warmup_minutes=10,
        measure_minutes=180,deadline_minutes=360,background_cars=0,private_evs=2,electric_taxis=2,
        samples=1,trace=True,rush_enabled=False)
    setting=folder/'config.json';budget=folder/'budget.json';training=folder/'optimizer'
    expected=dict(hours=6,workers=1,optimizer_seeds=[49001],
                  budget=dict(max_evaluations=16,min_evaluations=16,validation_every=16))
    for path,record in [(setting,asdict(smoke)),(budget,expected)]:
        if path.exists() and json.loads(path.read_text())!=record:raise ValueError('Smoke registration changed')
        if not path.exists():write_json(path,record)
    identity=dict(source=provenance(),config_sha256=digest(setting),budget_sha256=digest(budget),
        calibration_sha256=digest(Path(smoke.calibration)),model_proof_sha256=digest(Path(model_proof)),
        official_training=False,allowance='isolated 6h development smoke; no official budget',
        smoke_native_profile='explicit morning integration fixture, not production performance',
        boundary_sha256=digest(BASE/'strict_fitness_boundary.py'),entry_sha256=digest(BASE/'strict_optimizer_entry.py'))
    registration=folder/'smoke_registration.json'
    if registration.exists() and json.loads(registration.read_text())!=identity:raise ValueError('Existing smoke identity differs')
    if not registration.exists():write_json(registration,identity)
    checkpoint=training/'checkpoint.pkl'
    command=[sys.executable,'-B',str(BASE/'strict_optimizer_entry.py'),'--config',str(setting),'--smoke','--model-proof',str(model_proof),'--budget',str(budget),'--output',str(training)]
    def spawn(resume):
        status('optimizer_smoke',phase='resume' if resume else 'first_native_evaluation',output=str(training))
        log=(folder/('resume.log' if resume else 'initial.log')).open('ab')
        child=subprocess.Popen(command+(['--resume'] if resume else []),cwd=SOURCE,env=os.environ.copy(),stdout=log,stderr=subprocess.STDOUT)
        write_json(folder/'active_process.json',dict(pid=child.pid,command=command+(['--resume'] if resume else [])))
        return child,log
    def read_checkpoint():return pickle.loads(checkpoint.read_bytes())
    interruption=folder/'interruption_proof.json'
    if not interruption.exists():
        child,log=spawn(checkpoint.exists())
        try:
            start=time.monotonic()
            while True:
                if child.poll() is not None:raise RuntimeError('Smoke exited before controlled interruption')
                complete=[]
                for path in training.glob('*/49001/candidates/0/*/*/manifest.json'):
                    record=json.loads(path.read_text())
                    if record.get('status')=='complete':complete.append(path)
                if checkpoint.exists() and complete:
                    before=read_checkpoint();slot=before['slots'][0]
                    if slot['pending'] is None or slot['generation']!=0:raise ValueError('Smoke interruption missed pending first generation')
                    with (training/'.lock').open() as lock:
                        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                        except BlockingIOError:pass
                        else:raise ValueError('Smoke trainer does not own exclusive lock')
                    pending=fingerprint(slot['pending']);rng=fingerprint(slot['rng'])
                    sealed=[dict(path=str(p),sha256=digest(p)) for p in complete]
                    journal=json.loads((training/'training_time.json').read_text())
                    child.send_signal(signal.SIGTERM)
                    try:child.wait(timeout=60)
                    except subprocess.TimeoutExpired:raise RuntimeError('Smoke SIGTERM did not stop gracefully; inspect owned child groups')
                    after=read_checkpoint();stopped=after['slots'][0]
                    if after['status']!='interrupted' or fingerprint(stopped['pending'])!=pending or fingerprint(stopped['rng'])!=rng:
                        raise ValueError('Interruption lost pending candidates/RNG')
                    if stopped['generation']!=0 or stopped['evaluations']!=0:raise ValueError('Incomplete generation reached tell')
                    if after['active_seconds']<journal['consumed_seconds']:raise ValueError('Consumed time decreased on interruption')
                    if json.loads((training/'training_time.json').read_text())['active']:raise ValueError('Interrupted smoke clock remains active')
                    archived=folder/'interrupted_checkpoint.pkl';shutil.copy2(checkpoint,archived)
                    shutil.copy2(training/'training_time.json',folder/'interrupted_training_time.json')
                    write_json(interruption,dict(passed=True,source=provenance(),pending_sha256=pending,rng_sha256=rng,
                        generation=0,evaluations=0,active_seconds=after['active_seconds'],sealed_completed_manifests=sealed,
                        interrupted_checkpoint=dict(path=str(archived),sha256=digest(archived)),graceful_signal='SIGTERM',native_completed_rollouts=len(sealed)))
                    break
                if time.monotonic()-start>3600:raise RuntimeError('No native candidate completed within isolated smoke interruption setup')
                time.sleep(2)
        finally:
            log.close()
            if child.poll() is None:
                child.send_signal(signal.SIGTERM)
                try:child.wait(timeout=60)
                except subprocess.TimeoutExpired:raise RuntimeError('Smoke child remains alive; no duplicate resume permitted')
    before=json.loads(interruption.read_text());state=read_checkpoint()
    if state['status']!='complete':
        slot=state['slots'][0]
        if slot['generation']==0 and (fingerprint(slot['pending'])!=before['pending_sha256'] or fingerprint(slot['rng'])!=before['rng_sha256']):
            raise ValueError('Pending/RNG changed before resume')
        if state['active_seconds']<before['active_seconds']:raise ValueError('Smoke time reset before resume')
        child,log=spawn(True)
        try:
            while child.poll() is None:
                status('optimizer_smoke',phase='resumed_native_evaluations',output=str(training))
                time.sleep(15)
            if child.returncode:raise RuntimeError('Native smoke resume failed; see resume.log')
        finally:
            log.close()
            if child.poll() is None:child.send_signal(signal.SIGTERM);child.wait(timeout=60)
    final=read_checkpoint()
    if final['status']!='complete' or final['active_seconds']<before['active_seconds']:raise ValueError('Smoke did not complete or lost consumed time')
    if not 0<final['active_seconds']<=6*3600:raise ValueError('Isolated smoke accounting exceeds its allowance')
    for item in before['sealed_completed_manifests']:
        if digest(Path(item['path']))!=item['sha256']:raise ValueError('Completed native evaluation was rerun/changed across resume')
    slots=[]
    for slot in final['slots']:
        if slot['generation']!=1 or slot['evaluations']!=16 or slot['pending'] is not None or slot['pending_validation'] is not None:
            raise ValueError('Unexpected CMA-ES ask/evaluate/tell state')
        if slot['optimizer'].countiter!=1 or len(slot['history'])!=1:raise ValueError('Generation/validation was lost or duplicated')
        vectors=slot['history'][0]['fitness_vector']
        if len(vectors)!=5 or not np.isfinite(vectors).all():raise ValueError('Invalid native smoke fitness')
        slots.append(dict(method=slot['method'],generation=slot['generation'],evaluations=slot['evaluations'],fitness_vector=vectors,
                          optimizer_iterations=slot['optimizer'].countiter))
    models=[]
    for method in METHODS:
        path=training/method/'parameters.json';parameters=load_model(path,method,smoke)
        if len(parameters)!=(4 if method=='Fixed-Weights' else 20) or not np.isfinite(parameters).all():raise ValueError('Model serialization invalid')
        record=json.loads(path.read_text())
        if (record.get('source')!=provenance() or record.get('calibration_sha256')!=identity['calibration_sha256']
            or record.get('budget_sha256')!=identity['budget_sha256'] or record.get('profile')!='smoke'
            or record.get('training_completed') is not False):raise ValueError('Smoke model lineage/profile invalid')
        models.append(dict(method=method,path=str(path),sha256=digest(path)))
    manifests=sorted(training.glob('*/49001/candidates/*/*/*/manifest.json'))+sorted(training.glob('*/49001/validation/*/*/manifest.json'))
    if len(manifests)!=408:raise ValueError('Smoke candidate/validation rollout grid incomplete')
    strict_proofs=[]
    for manifest in manifests:
        native=manifest.parent.resolve()
        review=training.parent/'f04_results'/native.relative_to(training.resolve())/'review.json'
        record=json.loads(review.read_text())
        result_identity=record.get('identity',{})
        if (record.get('kind')!='strict_native_fitness_boundary' or record.get('passed') is not True
            or record.get('before_fitness') is not True
            or result_identity!=dict(path=str(native),manifest_sha256=digest(manifest),
                execution_source=provenance(),validator_source=provenance(),
                boundary_sha256=digest(BASE/'strict_fitness_boundary.py'))):
            raise ValueError('Strict per-result smoke proof is missing/stale/mismatched')
        strict_proofs.append(review)
    clock=json.loads((training/'training_time.json').read_text())
    if clock['active'] or clock['consumed_seconds']<final['active_seconds']:raise ValueError('Smoke clock did not close conservatively')
    result=dict(kind='native_optimizer_smoke',passed=True,source=provenance(),identity=identity,slots=slots,models=models,
        interruption_proof=dict(path=str(interruption),sha256=digest(interruption)),checkpoint=dict(path=str(checkpoint),sha256=digest(checkpoint)),
        active_seconds=final['active_seconds'],clock_consumed_seconds=clock['consumed_seconds'],native_rollouts=len(manifests),
        completed_results_preserved=True,RNG_pending_preserved=True,official_training_started=False,
        strict_F04_before_fitness=True,strict_F04_native_results=len(strict_proofs),
        dependencies=[dict(path=str(p),sha256=digest(p)) for p in [registration,setting,budget,*manifests,*strict_proofs]])
    from native_rng_reference import execute as compare_native_rng
    rng=compare_native_rng(smoke,folder,training,budget,Path(model_proof))
    result['native_rng_comparison']=dict(path=str(folder/'native_rng_comparison.json'),sha256=digest(folder/'native_rng_comparison.json'))
    result['total_smoke_active_seconds']=rng['combined_smoke_active_seconds']
    write_json(folder/'acceptance.json',result)
    return result
