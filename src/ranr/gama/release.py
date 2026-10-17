"""Durable, sequential research release: replay -> gates -> train -> held-out test.

Usage: python -m ranr.gama.release start|run|status|stop|resume --output PATH
Only start/resume executes work. A failed gate never starts its successors.
"""
from dataclasses import asdict, replace
from pathlib import Path
import argparse
import fcntl
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import traceback
from ..paths import ROOT, write_json, digest
from .headless import RunConfig, OUTPUT, provenance, checked_result
from .evidence import reference

SEEDS = (800001,800002,800003)
SELECTED = ('collect_800001_1.792142817036E12','collect_800002_1.7921382848E12','collect_800003_1.792145034622E12')
OUTLIER = 'collect_800001_1.792133049812E12'


def require_source(registration):
    if registration['source'] != provenance(): raise ValueError('Release source changed; preserve this registration and start a new release')


def initialize(folder, gui=None, resolution=None, review=None, fresh_fallback=True):
    if (folder/'registration.json').exists(): raise FileExistsError('Release already registered: use resume')
    config = RunConfig.load(ROOT/'configs/gama/calibration.json')
    if sum(getattr(config,k) for k in ('warmup_minutes','measure_minutes','deadline_minutes'))!=4320:
        raise ValueError('Registered three-day calibration required')
    if shutil.disk_usage(ROOT).free < 40*1024**3: raise ValueError('Need at least 40 GiB free')
    runs = [OUTPUT/'gui_calibration/runs'/name for name in SELECTED]
    for run in runs:
        manifest = json.loads((run/'manifest.json').read_text())
        checked_result(run,{'source':manifest['source']})
    folder.mkdir(parents=True,exist_ok=True)
    from .long_collection import collection_lock
    # Fail before publishing a release pointer if another collector owns memory.
    with collection_lock():
        pass
    pointer = OUTPUT/'gui_calibration/latest.json'
    if pointer.exists():shutil.copy2(pointer,folder/'previous_calibration_pointer.json')
    registration = {'source':provenance(),'created_at':time.time(),'hours_training_only':72,
        'calibration_config':asdict(config),'selected':[str(p) for p in runs],
        'selected_manifests':[reference(p/'manifest.json') for p in runs],
        'gui':str(Path(gui).resolve()) if gui else None,'resolution':str(Path(resolution).resolve()) if resolution else None,
        'compatibility_review':str(Path(review).resolve()) if review else None,
        'fresh_fallback':fresh_fallback,'service':f'ranr-release-{time.time_ns()}.service'}
    write_json(folder/'registration.json',registration)
    write_json(folder/'state.json',{'status':'registered','stages':{},'updated_at':time.time()})
    write_json(OUTPUT/'release_latest.json',{'output':str(folder.resolve())})
    return registration


def execute(folder):
    registration = json.loads((folder/'registration.json').read_text())
    require_source(registration)
    state = json.loads((folder/'state.json').read_text())
    def save():
        state['updated_at']=time.time();write_json(folder/'state.json',state)
    def stage(name,command,artifacts):
        require_source(registration)
        previous = state['stages'].get(name,{})
        if previous.get('status')=='complete':
            for item in previous['artifacts']:
                if digest(Path(item['path']))!=item['sha256']: raise ValueError('Completed stage evidence changed: '+name)
            return
        started=time.monotonic();active=previous.get('active_seconds',0)
        state.update(status='running',current_stage=name)
        state['stages'][name]={'status':'running','started_at':time.time(),'active_seconds':active,'command':command}
        save();print('STAGE',name,flush=True)
        with (folder/(name+'.log')).open('a') as log:
            child=subprocess.Popen(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,env=os.environ.copy())
            try:
                while True:
                    try:code=child.wait(timeout=30);break
                    except subprocess.TimeoutExpired:
                        state['stages'][name]['active_seconds']=active+time.monotonic()-started;save()
            finally:
                if child.poll() is None:
                    child.terminate()
                    try:child.wait(timeout=30)
                    except subprocess.TimeoutExpired:child.kill();child.wait()
        state['stages'][name]['active_seconds']=active+time.monotonic()-started
        if code:
            state['stages'][name].update(status='failed',exit_code=code)
            save();raise RuntimeError(f'Stage {name} failed ({code}); see {folder/(name+".log")}')
        require_source(registration)
        state['stages'][name].update(status='complete',artifacts=[reference(p) for p in artifacts],finished_at=time.time())
        save()
    python=[sys.executable,'-B','-m','ranr']
    try:
        # Every release rechecks its own source. Successful stages resume by hash.
        stage('python_tests',[sys.executable,'-B','-m','unittest','discover','-s','tests'],[])
        stage('native_validation',python+['validate','--compile'],[OUTPUT/'validation.json'])
        config=replace(RunConfig(**registration['calibration_config']),seed=800001,render=False)
        replays=[]
        for i in range(3):
            config_path=folder/'configs'/f'replay_{i}.json';write_json(config_path,asdict(config))
            target=folder/'replay'/str(i)
            stage(f'replay_{i}',python+['--config',str(config_path),'run','--output',str(target),'--resume'],[target/'manifest.json'])
            replays.append(target)
        from .replay import compare_runs, replay_report
        comparisons=[compare_runs(replays[0],p) for p in replays[1:]]
        write_json(folder/'native_reproducibility.json',{'source':provenance(),'passed':all(r['passed'] for r in comparisons),
            'comparisons':comparisons,'dependencies':[reference(p/'manifest.json') for p in replays]})
        if not all(r['passed'] for r in comparisons): raise ValueError('Fresh headless replay diverged; first divergent event recorded. Calibration/training blocked.')
        legacy=replay_report(registration['selected'],replays,registration['gui'],folder/'legacy_reproducibility.json',
            OUTPUT/'gui_calibration/runs'/OUTLIER,registration['resolution'])
        compatibility=None
        if legacy['passed'] and registration['compatibility_review']:
            from .evidence import certify_compatibility
            compatibility=folder/'compatibility.json'
            certify_compatibility(registration['selected'],registration['compatibility_review'],folder/'legacy_reproducibility.json',compatibility)
            selected=[Path(p) for p in registration['selected']]
        elif registration['fresh_fallback']:
            state['calibration_strategy']='fresh_after_unverified_legacy_replay';save()
            selected=[replays[0]]
            for seed in SEEDS[1:]:
                config_path=folder/'configs'/f'calibration_{seed}.json'
                write_json(config_path,asdict(replace(config,seed=seed)))
                target=folder/'fresh_calibration'/str(seed)
                stage(f'calibration_{seed}',python+['--config',str(config_path),'run','--output',str(target),'--resume'],[target/'manifest.json'])
                selected.append(target)
        else: raise ValueError('Historical reuse blocked: fresh GUI replay/causal diagnosis or compatibility review missing; original data retained')
        from .gui_collection import build
        # Do not change a successfully published calibration on resume.
        built=folder/'calibration_selection.json'
        if built.exists():
            result=json.loads(built.read_text())
            if digest(Path(result['calibration']))!=result['sha256']:raise ValueError('Release calibration changed')
        else:
            result=build(OUTPUT/'gui_calibration',selected,compatibility)
            result['sha256']=digest(Path(result['calibration']));write_json(built,result)
        research=json.loads((ROOT/'configs/gama/research.json').read_text())
        research['calibration']=result['calibration']
        research_path=folder/'configs/research.json';write_json(research_path,research)
        RunConfig.load(research_path)
        benchmark=folder/'benchmark'
        stage('accuracy',python+['--config',str(research_path),'benchmark','--stage','accuracy','--output',str(benchmark)],
              [benchmark/'accuracy_gate.json',benchmark/'accuracy_config.json'])
        locked=benchmark/'accuracy_config.json'
        stage('development',python+['--config',str(locked),'development-validation','--output',str(folder/'development')],
              [OUTPUT/'development_validation.json'])
        stage('design',python+['--config',str(locked),'design-validation','--output',str(folder/'design')],
              [folder/'design/review.json'])
        from .design import DEFAULT_DESIGN
        from .contracts import OBJECTIVE_CONFIG_HASH
        decision=folder/'design/decision.json'
        write_json(decision,{'selected_config':DEFAULT_DESIGN,'objective_config_hash':OBJECTIVE_CONFIG_HASH,
            'review_sha256':digest(folder/'design/review.json'),'rule':'preregistered defaults'})
        stage('freeze',python+['freeze-design',str(folder/'design'),str(decision)],[OUTPUT/'design_freeze.json'])
        stage('performance',python+['--config',str(locked),'benchmark','--stage','performance','--output',str(benchmark),'--hours','72'],
              [benchmark/'budget.json',benchmark/'locked_config.json'])
        budget=json.loads((benchmark/'budget.json').read_text())
        if budget.get('passed') is not True:raise ValueError('Benchmark cannot fit registered minimum in 72 training hours')
        # Real GAMA optimizer smoke uses the validated physical model, with a
        # small explicit development fleet/horizon; never publish its weights.
        smoke_config=replace(RunConfig.load(locked),development=True,calibrating=False,
            warmup_minutes=0,measure_minutes=3,background_cars=0,private_evs=2,electric_taxis=2,
            samples=1,trace=True,rush_enabled=False)
        smoke_path=folder/'configs/optimizer_smoke.json';write_json(smoke_path,asdict(smoke_config))
        smoke_budget=folder/'optimizer_smoke_budget.json'
        write_json(smoke_budget,{'hours':6,'workers':1,'optimizer_seeds':[49001],
            'budget':{'max_evaluations':16,'min_evaluations':16,'validation_every':16}})
        smoke=folder/'optimizer_smoke'
        smoke_command=python+['--config',str(smoke_path),'train','--smoke','--budget',str(smoke_budget),'--output',str(smoke)]
        if (smoke/'checkpoint.pkl').exists():smoke_command+=['--resume']
        stage('optimizer_smoke',smoke_command,[smoke/'registration.json'])
        if json.loads((smoke/'registration.json').read_text())['status']!='complete':raise ValueError('Native optimizer smoke incomplete')
        train_folder=folder/'training'
        command=python+['--config',str(benchmark/'locked_config.json'),'train','--budget',str(benchmark/'budget.json'),'--output',str(train_folder)]
        if (train_folder/'checkpoint.pkl').exists():command+=['--resume']
        stage('training',command,[train_folder/'registration.json'])
        if json.loads((train_folder/'registration.json').read_text())['status']!='complete':
            state['status']='budget_limited';save();return
        stage('evaluation',python+['--config',str(benchmark/'locked_config.json'),'evaluate','--models',str(train_folder),
            '--output',str(folder/'evaluation'),'--workers',str(budget['workers'])],[folder/'evaluation/registration.json'])
        stage('training_report',python+['report-training',str(train_folder)],[train_folder/'report/histories.json'])
        state.update(status='complete',current_stage=None,training_complete=True,evaluation_complete=True);save()
    except BaseException as error:
        state.update(status='interrupted' if isinstance(error,(KeyboardInterrupt,SystemExit)) else 'needs_attention',error=str(error))
        save();write_json(folder/'diagnostic.json',{'error':str(error),'traceback':traceback.format_exc(),'source':provenance()})
        raise


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('start','run','status','stop','resume'))
    parser.add_argument('--output',type=Path)
    parser.add_argument('--gui-run',type=Path)
    parser.add_argument('--outlier-resolution',type=Path)
    parser.add_argument('--compatibility-review',type=Path)
    parser.add_argument('--no-fresh-fallback',action='store_true')
    args=parser.parse_args()
    folder=args.output
    if folder is None:
        if args.command=='start':folder=OUTPUT/'releases'/str(time.time_ns())
        else:folder=Path(json.loads((OUTPUT/'release_latest.json').read_text())['output'])
    folder=folder.resolve()
    if args.command=='start':
        reg=initialize(folder,args.gui_run,args.outlier_resolution,args.compatibility_review,not args.no_fresh_fallback)
        def quote(value):return '"'+str(value).replace('\\','\\\\').replace('"','\\"').replace('%','%%')+'"'
        unit=folder/reg['service']
        unit.write_text('[Unit]\nDescription=GAMA RANR scientific release\n\n[Service]\nType=simple\n'
            +f'WorkingDirectory={str(ROOT).replace("%","%%")}\nExecStart={quote(sys.executable)} -B -m ranr.gama.release run --output {quote(folder)}\n'
            +'KillMode=control-group\nTimeoutStopSec=45\nRestart=no\n'
            +'Environment=OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 RANR_JAVA_HEAP_MIB=12288 RANR_STALL_SECONDS=1200 RANR_STARTUP_SECONDS=900 RANR_POLL_SECONDS=30\n'
            +f'Environment={quote("RANR_WORKSPACE="+str(ROOT))} {quote("PYTHONPATH="+str(ROOT/"src"))} {quote("MPLCONFIGDIR="+str(folder/"matplotlib_cache"))} {quote("GAMA_HOME="+os.environ.get("GAMA_HOME","/opt/gama-platform"))}\n'
            +f'StandardOutput=append:{folder}/supervisor.log\nStandardError=inherit\n\n[Install]\nWantedBy=default.target\n')
        subprocess.run(['systemd-analyze','--user','verify',str(unit)],check=True)
        subprocess.run(['systemctl','--user','link',str(unit)],check=True)
        subprocess.run(['systemctl','--user','enable','--now',reg['service']],check=True)
        print(folder);return
    if args.command=='status':
        state=json.loads((folder/'state.json').read_text())
        reg=json.loads((folder/'registration.json').read_text())
        service=subprocess.run(['systemctl','--user','is-active',reg['service']],capture_output=True,text=True)
        print(json.dumps({'output':str(folder),'service':reg['service'],'service_state':service.stdout.strip(),**state},indent=2));return
    reg=json.loads((folder/'registration.json').read_text())
    if args.command in ('stop','resume'):
        require_source(reg)
        subprocess.run(['systemctl','--user','stop' if args.command=='stop' else 'start',reg['service']],check=True);return
    # One release may own the global calibration/freeze/model pointers at a time.
    OUTPUT.mkdir(parents=True,exist_ok=True)
    with (OUTPUT/'.release.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        from .long_collection import collection_lock
        def interrupted(signum,frame):raise KeyboardInterrupt(f'Signal {signum}')
        signal.signal(signal.SIGTERM,interrupted)
        for name in ('_JAVA_OPTIONS','JAVA_TOOL_OPTIONS','JDK_JAVA_OPTIONS'):
            os.environ.pop(name,None)
        with collection_lock():
            execute(folder)


if __name__=='__main__':main()
