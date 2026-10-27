"""Exclusive new-source revalidation, then conditionally authorized training.

No Collect or held-out command. Existing scientific workers retain ownership
until every original service and its recorded children have stopped.
"""
from pathlib import Path
from dataclasses import asdict
from contextlib import contextmanager, ExitStack
import argparse
import fcntl
import json
import math
import os
import pickle
import signal
import subprocess
import sys
import time
import traceback

SOURCE = Path(__file__).resolve().parents[2]
ROOT = SOURCE.parent
BASE = ROOT.parent
HERE = Path(__file__).resolve().parent
PARENT = BASE / 'heap8_revalidation_20261027'
sys.path.insert(0,str(HERE))
OUTPUT = SOURCE / 'outputs/gama_ranr'
UNIT = 'gama-ranr-autonomous-integration-20261027.service'
HEAP_MIB = 8192
WORKER_OPTIONS = [1,2]
ORIGINAL_UNITS = ('gama-ranr-heap8-revalidation-20261027.service', 'gama-ranr-mc-parallel-prefetch-20261027.service')
os.environ['RANR_WORKSPACE'] = str(SOURCE)
os.environ['PYTHONPATH'] = str(SOURCE / 'src')
sys.path.insert(0, str(SOURCE / 'src'))
from ranr.paths import write_json, digest
from ranr.gama.headless import provenance, RunConfig, METHODS, CASES
from ranr.gama.evidence import (reference, verify_reference, read_evidence,
    verify_native, verify_training_acceptance, PRE_TRAINING_GATES)
from ranr.gama.execution import assert_checkout_modules
from ranr.gama.calibration_import import verify_calibration_import
from ranr.gama.contracts import OBJECTIVE_VERSION, OBJECTIVE_CONFIG_HASH


def load(path):
    return json.loads(Path(path).read_text())


def require(value, message):
    if not value:
        raise ValueError(message)


def status(stage, **fields):
    previous = load(ROOT / 'state.json') if (ROOT / 'state.json').exists() else {}
    previous.update(stage=stage, updated_at=time.time(), pid=os.getpid(), **fields)
    write_json(ROOT / 'state.json', previous)
    render(previous)
    print(json.dumps(dict(stage=stage,status=previous.get('status'),updated_at=previous['updated_at'],
        official_training=previous.get('official_training'),reason=previous.get('reason',''))),flush=True)


def render(state):
    reg=load(ROOT/'registration.json') if (ROOT/'registration.json').exists() else {}
    done=state.get('completed',{})
    parent=load(PARENT/'state.json')
    parent_done=parent.get('completed',{})
    accuracy='PASS — reviewed unchanged native physics' if 'adopt' in done else ('PASS predecessor; integration review PENDING' if 'accuracy' in parent_done else ('RUNNING source35b' if parent.get('status')=='running' else 'PENDING / inspect predecessor failure'))
    progress=ROOT/'predictive/progress.json'
    count=load(progress)['completed_episodes'] if progress.exists() else 0
    journal=BASE/'official_training/optimizer/training_time.json'
    consumed=load(journal)['consumed_seconds'] if journal.exists() else 0.
    rows=[('Five findings fixed','PASS engineering; native optimizer acceptance PENDING' if 'smoke' not in done else 'PASS'),('RNG reproducibility','PASS engineering3seeds×4methods×2generations; native PENDING' if 'smoke' not in done else 'PASS native-fitness paired comparison'),('Source integration','PASS — committed separate worktree'),('Calibration compatibility','PASS — typed scoped import; execution identities preserved'),('Monte Carlo accuracy',accuracy),('36 predictive episodes',f'{count}/36; '+('PASS' if 'predictive' in done else 'PENDING')),('Model validation','PASS' if 'model' in done else 'PENDING'),('Native CMA-ES smoke','PASS' if 'smoke' in done else 'PENDING'),('13 pre-training gates','PASS' if 'readiness' in done else 'PENDING'),('Training feasibility','PASS' if 'performance' in done else 'PENDING'),('Official training',state.get('official_training','BLOCKED'))]
    text='# Autonomous integration PR01–PR05 → validation → training có điều kiện\n\n'
    text+='Updated epoch '+str(state['updated_at'])+'; controller PID'+str(state['pid'])+'; stage `'+state['stage']+'`; status `'+state.get('status','')+'`.\n\n'
    text+='| Milestone | Status |\n|---|---|\n'+''.join('| '+a+' | '+b+' |\n' for a,b in rows)
    text+='\nIntegrated source commit: `'+reg.get('source_commit','pending commit')+'`. Current native predecessor source35b stays frozen; integrated controller is observation-only until ownership handoff.\n'
    text+='\nReason: '+state.get('reason','')+'\nOfficial budget consumed '+str(consumed)+'s /259200s; no checkpoint before real optimizer initialization.\n'
    text+='\n[Runbook](AUTONOMOUS_INTEGRATION_RUNBOOK_VI.md), [registration](autonomous_integration_20261027/registration.json), [state](autonomous_integration_20261027/state.json), [log](autonomous_integration_20261027/worker.log). No Collect or720held-out.\n'
    (BASE/'AUTONOMOUS_INTEGRATION_STATUS_VI.md').write_text(text)


def check(reg, require_hold=True):
    assert_checkout_modules()
    require(int(os.environ.get('RANR_JAVA_HEAP_MIB','2048')) == reg['heap_mib'],
            'Launcher heap differs from registered performance/training runtime')
    require(not any(os.environ.get(k) for k in ('JAVA_TOOL_OPTIONS','_JAVA_OPTIONS','JDK_JAVA_OPTIONS')),
            'Unregistered JVM option injection could override heap8 runtime')
    require(provenance() == reg['source'], 'Frozen consumer source changed')
    for item in reg['dependencies']:
        verify_reference(item)
    if require_hold:
        hold = load(BASE / 'TRAINING_LAUNCH_HOLD.json')
        guard = Path(hold['guard_path'])
        require(hold.get('active') is True and guard.is_dir()
                and guard.stat().st_ino == reg['hold_inode'], 'Official training launch hold changed')


def unit_properties(name):
    result=subprocess.run(['systemctl','--user','show',name,'-p','ActiveState','-p','SubState','-p','MainPID','-p','MemoryMax'],text=True,capture_output=True)
    if result.returncode:return dict(ActiveState='inactive',SubState='not-found',MainPID='0')
    return dict(line.split('=',1) for line in result.stdout.splitlines() if '=' in line)


def living_owned_processes():
    from ranr.gama.training_time import still_alive
    roots = [PARENT, BASE/'mc_parallel_prefetch_20261027', BASE/'official_training']
    owners = []
    for root in roots:
        for path in root.rglob('owned_processes.json'):
            for owner in load(path):
                if still_alive(owner):
                    owners.append(dict(record=str(path), owner=owner))
    return owners


def competing_jobs():
    """Read only command lines; never environment values or credentials."""
    matches = []
    for folder in Path('/proc').iterdir():
        if not folder.name.isdigit() or int(folder.name) == os.getpid():
            continue
        try:
            arguments = (folder / 'cmdline').read_bytes().split(b'\0')
            args = [a.decode(errors='replace') for a in arguments if a]
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        if any(Path(a).name in ('official_training_entry.py','strict_optimizer_entry.py') for a in args) or (
                '-m' in args and 'ranr' in args and any(a in ('train','evaluate','release') for a in args)):
            matches.append(dict(pid=int(folder.name), arguments=args))
    return matches


def ownership_snapshot():
    return dict(services={name:unit_properties(name) for name in ORIGINAL_UNITS},
        live_owned_processes=living_owned_processes(),competing=competing_jobs(),parent=load(PARENT/'state.json'))


def original_busy(snapshot):
    return (any(p.get('ActiveState') in ('active','activating','deactivating','reloading')
                or int(p.get('MainPID','0')) for p in snapshot['services'].values())
            or bool(snapshot['live_owned_processes']) or bool(snapshot['competing']))


def check_scientific_stop(snapshot):
    for path in (PARENT/'predictive/acceptance.json', PARENT/'model_acceptance.json'):
        if path.exists() and load(path).get('passed') is not True:
            raise ValueError('Predecessor scientific FAIL/INSUFFICIENT/OOD review; unchanged physics cannot retry: '+str(path))
    state=snapshot['parent']
    if state.get('status')=='failed':
        reason=state.get('reason','')
        require(reason=='Reserved guard contains data; cannot release',
            'Predecessor failure requires diagnosis; no blind retry: '+reason)


def verify_original_boundary(snapshot):
    require(not original_busy(snapshot),'Predecessor service or owned child still active')
    check_scientific_stop(snapshot)
    state=snapshot['parent']
    require(state.get('status')=='failed' and state.get('reason')=='Reserved guard contains data; cannot release',
        'No sealed ownership boundary; predecessor/reboot recovery must be reconciled')
    require(all(name in state.get('completed',{}) for name in ('accuracy','predictive','model','smoke','development','design','freeze','performance','readiness')),
        'Predecessor prerequisite incomplete at guarded boundary')
    for item in state['completed']['accuracy']['evidence']:verify_reference(item)
    require(not (BASE/'official_training/inputs_frozen.json').exists(),'Unexpected official optimizer state')


@contextmanager
def legacy_locks():
    with ExitStack() as stack:
        streams = [stack.enter_context(p.open('a')) for p in
                   (BASE / '.end_to_end.lock', BASE / 'release/.worker.lock')]
        for stream in streams:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield streams


def capacity(workers=1, disk_gib=40):
    available = next(int(line.split()[1]) for line in Path('/proc/meminfo').read_text().splitlines()
                     if line.startswith('MemAvailable:'))
    free = os.statvfs(BASE).f_bavail * os.statvfs(BASE).f_frsize
    required = workers*HEAP_MIB*1024 + 4*1024**2
    require(available >= required, 'Insufficient available RAM for selected workers plus overhead')
    require(free >= disk_gib*1024**3, 'Insufficient disk space for registered native output/checkpoints')
    unit = unit_properties(UNIT)
    require(unit['MemoryMax'] == 'infinity' or int(unit['MemoryMax']) >= required*1024,
            'Service memory limit below workload requirement')
    return dict(available_memory_kib=available, free_disk_bytes=free, workers=workers,
                heap_mib=HEAP_MIB, cpu_count=os.cpu_count(), load_average=os.getloadavg(), service=unit)


def cli(config, *arguments):
    return [sys.executable,'-B',str(SOURCE / 'scripts/ranr_checked.py'),
            '--config',str(config),*map(str,arguments)]


def run_child(name, command, reg, *, timeout=7*86400, lock_files=(), hold=True):
    check(reg, require_hold=hold)
    with (ROOT / (name+'.log')).open('ab') as log:
        child = subprocess.Popen(command, cwd=SOURCE, env=os.environ.copy(),
            stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
            pass_fds=tuple(f.fileno() for f in lock_files))
        from ranr.gama.training_time import owner_token
        write_json(ROOT / 'active_process.json', dict(owner=owner_token(child.pid), command=command,
                    stage=name, started_at=time.time(), timeout_seconds=timeout))
        started = time.monotonic()
        try:
            while child.poll() is None:
                check(reg, require_hold=hold)
                require(time.monotonic()-started < timeout,
                        'Technical wall-time limit reached; no automatic scientific retry')
                fields = dict(status='running', active_child_pid=child.pid,
                    active_stage_wall_seconds=time.monotonic()-started,
                    reason='Native computation; wall time is not percentage scientific progress')
                if not hold:
                    checkpoint = BASE / 'official_training/optimizer/checkpoint.pkl'
                    fields.update(official_training='RUNNING' if checkpoint.exists() else 'STARTING', training_ready=True)
                predictive = ROOT/'predictive/progress.json'
                if name == 'predictive' and predictive.exists():
                    fields['predictive_progress'] = load(predictive)
                status(name, **fields)
                time.sleep(30)
            if child.returncode:
                raise RuntimeError(name+' failed; see '+str(ROOT / (name+'.log')))
        finally:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
                try:
                    child.wait(timeout=60)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()


def gui_scope():
    """Reuse GUI rendering/reload scope only; new physics is native evidence."""
    path = BASE / 'evidence/gui_final_validation.json'
    gui = load(path)
    require(gui.get('passed') is True, 'GUI acceptance missing')
    paths = [path]
    for item in [*gui['dependencies'],*gui['screenshots']]:
        paths.append(verify_reference(item))
    totals = set()
    for row in gui['runs']:
        require(row['configured'] == row['instantiated'] and sum(row['instantiated'].values()) == row['total'],
                'Historical GUI configured/instantiated mismatch')
        totals.add(row['total'])
        paths.extend(verify_reference(row[k]) for k in ('configuration','initial_fleet'))
    require(totals == {4700,2523}, 'GUI default/reload coverage incomplete')
    unchanged = ['models/main.gaml','models/Mobility.gaml','models/ranr/Fleet.gaml']
    for name in unchanged:
        require(digest(SOURCE/name) == digest(BASE/'source'/name), 'GUI/fleet implementation changed: '+name)
        paths.extend([SOURCE/name,BASE/'source'/name])
    native = verify_native(OUTPUT/'validation.json')
    require(all(native.get(k) is True for k in ('unified_fleet_checked','compile_checked',
                'energy_safety_checked','soc_activity_demand_checked')), 'New native backend/fleet evidence missing')
    record = dict(kind='scoped_gui_headless_acceptance', passed=True, source=provenance(),
        scope='Reuse exact unchanged GUI rendering/population/reload; repaired physics independently revalidated natively',
        fresh_desktop_replay=False, global_source_equivalence=False,
        dependencies=[reference(p) for p in [*paths,OUTPUT/'validation.json',ROOT/'certificate.json']])
    write_json(ROOT/'gui_scope.json',record)
    return record


def verify_accuracy(config):
    folder = ROOT/'benchmark'
    proof = read_evidence(folder/'accuracy_gate.json')
    require(proof['locked_config'] == asdict(config) and proof['calibration_sha256'] == digest(Path(config.calibration)),
            'Accuracy config/calibration changed')
    require(proof['thresholds'] == {'mean':1.,'p95':5.,'externality':5.}, 'MC thresholds changed')
    stability = load(folder/'reference_stability.json')
    require(stability['passed'] and all(r['pass_fraction'] >= .95 for r in stability['methods'].values()),
            'MC reference unstable')
    chosen = [r for r in load(folder/'accuracy.json') if r['samples'] == config.samples]
    require(len(chosen) == 1 and all(r['pass_fraction'] >= .95 for r in chosen[0]['methods'].values()),
            'Selected MC candidate did not pass')
    require(load(folder/'physical_steps.json')['60']['passed'], 'Production physical timestep gate failed')
    return proof


def model_acceptance(config):
    native = verify_native(OUTPUT/'validation.json')
    for flag in ('compile_checked','unified_fleet_checked','distributed_information_checked','objective_checked',
                 'energy_safety_checked','soc_activity_demand_checked','paired_exogenous_traits_checked'):
        require(native.get(flag) is True,'Native gate missing: '+flag)
    verify_calibration_import(ROOT/'certificate.json',Path(config.calibration))
    verify_accuracy(config)
    predictive = read_evidence(ROOT/'predictive/acceptance.json')
    require(predictive['protocol'] == reference(BASE/'R01_R03_PREREGISTRATION.json')
            and predictive['execution_design'] == reference(BASE/'R01_EXECUTION_DESIGN.json'), 'Scientific protocol changed')
    require(predictive['normal_status'] == 'PASS' and predictive['ood_status'] == {'high':'PASS','burst':'PASS'},
            'Predictive normal/OOD needs scientific review')
    registration = load(verify_reference(predictive['registration']))
    expected = {(c,s,m) for c in ('normal','high','burst') for s in range(920001,920007)
                for m in ('RANR-AW','No-Prediction')}
    require(len(registration['configs']) == 36 and
        {(r['case'],r['seed'],r['method']) for r in registration['configs']} == expected,
        'Predictive registered split/grid changed')
    gui_scope()
    record = dict(kind='model_validation_acceptance', passed=True, source=provenance(),
        no_remaining_training_affecting_physics_P1=True, normal_and_OOD='PASS',
        No_P2P_identifiability_limitation='Retain registered20 dimensions; age/bias redundant in this ablation',
        dependencies=[reference(p) for p in (OUTPUT/'validation.json',ROOT/'compatibility_acceptance.json',
            ROOT/'certificate.json',ROOT/'compatibility_acceptance.json',ROOT/'benchmark/accuracy_gate.json',ROOT/'predictive/acceptance.json',ROOT/'gui_scope.json')])
    write_json(ROOT/'model_acceptance.json',record)
    return record


def action(name):
    reg = load(ROOT/'registration.json')
    check(reg)
    config_path = ROOT/'benchmark/accuracy_config.json'
    config = RunConfig.load(config_path) if config_path.exists() else RunConfig.load(ROOT/'base_config.json')
    if name == 'adopt':
        from adopt_completed import execute
        execute()
    elif name == 'predictive':
        from predictive_stage import execute
        execute(config,ROOT/'predictive',lambda stage,**fields: print(json.dumps(dict(stage=stage,**fields)),flush=True),lambda:check(reg))
    elif name == 'model':
        model_acceptance(config)
    elif name == 'smoke':
        from native_smoke_runner import execute
        execute(config,ROOT/'native_smoke',ROOT/'model_acceptance.json',
                lambda stage,**fields: print(json.dumps(dict(stage=stage,**fields)),flush=True))
    elif name == 'development':
        from ranr.gama.development import development,verify_development
        record = development(config,ROOT/'development',workers=1)
        require(record['passed'],'Development failed')
        verify_development(OUTPUT/'development_validation.json',config)
    elif name == 'design':
        from ranr.gama.design import validate_design
        validate_design(config,ROOT/'design',workers=1)
    elif name == 'freeze':
        from ranr.gama.design import DEFAULT_DESIGN,freeze_design,validate_freeze
        decision = dict(selected_config=DEFAULT_DESIGN,objective_config_hash=OBJECTIVE_CONFIG_HASH,
            review_sha256=digest(ROOT/'design/review.json'),
            selection_rule='preregistered defaults; variants are sensitivity evidence; no post-hoc model selection')
        path = ROOT/'design_decision.json'
        if path.exists():require(load(path) == decision,'Scientific decision changed')
        else:write_json(path,decision)
        freeze_design(ROOT/'design',path)
        validate_freeze(OUTPUT/'design_freeze.json',config)
    elif name == 'performance':
        from ranr.gama import benchmarking
        from performance_boundary import MeasuredRunner
        original = benchmarking.run
        benchmarking.run = MeasuredRunner(original,ROOT/'benchmark',provenance())
        try:
            budget = benchmarking.benchmark(config,ROOT/'benchmark',WORKER_OPTIONS,72,stage='performance')
            require(budget['passed'],'Representative native performance does not fit72h')
        finally:
            benchmarking.run = original
    else:
        raise ValueError('Unknown stage '+name)


def verify_smoke():
    from strict_optimizer_entry import verify_model
    verify_model(ROOT/'model_acceptance.json')
    smoke = read_evidence(ROOT/'native_smoke/acceptance.json')
    rng=read_evidence(verify_reference(smoke['native_rng_comparison']))
    require(rng['kind']=='native_fitness_continuous_resume_comparison' and rng['native_fitness_only'] and rng['combined_smoke_active_seconds']<=6*3600, 'Native RNG reference incomplete')
    require(smoke['kind'] == 'native_optimizer_smoke' and smoke['native_rollouts'] == 408
            and smoke['strict_F04_before_fitness'] and smoke['strict_F04_native_results'] == 408,
            'Complete strict native optimizer smoke required')
    require(smoke['identity']['model_proof_sha256'] == digest(ROOT/'model_acceptance.json'), 'Smoke model proof changed')
    require(smoke['completed_results_preserved'] and smoke['RNG_pending_preserved'], 'Smoke duplicate/RNG evidence missing')
    require({s['method'] for s in smoke['slots']} == set(METHODS) and
            all(s['generation'] == 1 and s['evaluations'] == 16 and s['optimizer_iterations'] == 1
                and len(s['fitness_vector']) == 5 and all(math.isfinite(v) for v in s['fitness_vector']) for s in smoke['slots']),
            'Smoke ask/evaluate/tell incomplete')
    interrupted = load(verify_reference(smoke['interruption_proof']))
    verify_reference(interrupted['interrupted_checkpoint'])
    require(interrupted['passed'] and interrupted['graceful_signal'] == 'SIGTERM', 'SIGTERM recovery missing')
    final = pickle.loads(verify_reference(smoke['checkpoint']).read_bytes())
    require(final['status'] == 'complete' and
        0 < interrupted['active_seconds'] <= final['active_seconds'] <= smoke['clock_consumed_seconds'] <= 6*3600,
        'Smoke checkpoint/durable clock invalid')
    for ref in interrupted['sealed_completed_manifests']:verify_reference(ref)
    return smoke


def checkpoint_cost(budget):
    """Measure canonical save/load and durable I/O using actual smoke state."""
    from ranr.gama.training_time import durable_replace
    from ranr.gama.training import _save
    path = ROOT/'checkpoint_io_estimate.json'
    if path.exists():
        proof = load(path)
        require(proof['budget'] == reference(ROOT/'benchmark/budget.json'), 'Checkpoint estimate budget changed')
        verify_reference(proof['smoke_checkpoint'])
        return proof
    native_checkpoint = ROOT/'native_smoke/optimizer/checkpoint.pkl'
    raw = native_checkpoint.read_bytes()
    state = pickle.loads(raw)
    require(state['status'] == 'complete','Real completed smoke checkpoint required for I/O estimate')
    maximum = budget['budget']['max_evaluations']
    generations = math.ceil(maximum/16)
    # Three optimizer seeds instead of one, history up to every generation.
    # Replicated bytes are I/O payload only, never unpickled as a new result.
    scale = 3*(generations+2)
    payload = raw*scale
    trial = ROOT/'checkpoint_io_probe.bin'
    timings = []
    for _ in range(5):
        start = time.perf_counter();durable_replace(trial,payload);timings.append(time.perf_counter()-start)
    # Run the actual canonical serializer/fsync/rename and load the result.
    # The unchanged smoke object is never presented as a new optimizer result.
    canonical_save=[];canonical_load=[];serialization=[]
    probe=ROOT/'actual_smoke_save_load_probe.pkl'
    for _ in range(5):
        start=time.perf_counter();pickle.dumps(state,pickle.HIGHEST_PROTOCOL);serialization.append(time.perf_counter()-start)
        start=time.perf_counter();_save(probe,state);canonical_save.append(time.perf_counter()-start)
        start=time.perf_counter();loaded=pickle.loads(probe.read_bytes());canonical_load.append(time.perf_counter()-start)
        require(loaded['registration'] == state['registration'] and loaded['status'] == 'complete',
                'Canonical smoke checkpoint save/load changed identity')
    save_count = 12*(2*generations+math.ceil(maximum/budget['budget']['validation_every'])+2)+2
    heartbeat_count = math.ceil(72*3600/5)
    journal = (ROOT/'native_smoke/optimizer/training_time.json').read_bytes()
    journal_timings=[]
    for _ in range(5):
        start=time.perf_counter();durable_replace(ROOT/'journal_io_probe.bin',journal);journal_timings.append(time.perf_counter()-start)
    # Sum separate serialization and I/O estimates, retaining full canonical
    # save time as an additional floor. Reserve15% remains unchanged.
    save_estimate=max(max(timings)+scale*max(serialization),scale*max(canonical_save))
    load_estimate=scale*max(canonical_load)
    estimate = save_count*save_estimate+load_estimate+heartbeat_count*max(journal_timings)
    proof = dict(kind='checkpoint_journal_io_cost_estimate',budget=reference(ROOT/'benchmark/budget.json'),
        smoke_checkpoint=reference(native_checkpoint),measured_payload_bytes=len(payload),
        payload_scope='Conservative replication of actual smoke bytes for durable I/O; not a training checkpoint or scientific result',
        sample_seconds=timings,journal_sample_seconds=journal_timings,save_count=save_count,
        canonical_save_seconds=canonical_save,canonical_load_seconds=canonical_load,
        serialization_seconds=serialization,structural_scale=scale,
        estimated_save_seconds=save_estimate,estimated_load_seconds=load_estimate,
        heartbeat_count=heartbeat_count,estimated_seconds=estimate)
    write_json(path,proof)
    return proof


def readiness(reg):
    check(reg)
    config = RunConfig.load(ROOT/'benchmark/locked_config.json')
    require(not config.development and not config.calibrating and config.step_seconds == 60
            and (config.background_cars,config.private_evs,config.electric_taxis) == (3000,1000,700), 'Official profile changed')
    verify_calibration_import(ROOT/'certificate.json',Path(config.calibration))
    model_acceptance(config)
    smoke = verify_smoke()
    from ranr.gama.development import verify_development
    from ranr.gama.design import validate_freeze
    verify_development(OUTPUT/'development_validation.json',config)
    freeze = validate_freeze(OUTPUT/'design_freeze.json',config)
    require(all(freeze.get(k) is True for k in ('passed','calibration_passed','information_passed','exposure_passed',
        'objective_sensitivity_passed','design_validation_passed')), 'Scientific design freeze incomplete')
    budget = read_evidence(ROOT/'benchmark/budget.json')
    require(budget['hours'] == 72 and budget['population'] == 16 and budget['optimizer_seeds'] == [41001,41002,41003]
        and budget['locked_config'] == asdict(config) and budget['training_only'] and budget['budget_schema'] == 2,
        'Official training protocol changed')
    from ranr.gama.pipeline import benchmark_budget
    recomputed = benchmark_budget(budget['candidate_seconds'],budget['long_validation_seconds'],budget['workers'],72,budget['parallel_speedup'])
    require(recomputed['passed'] and recomputed['budget'] == budget['budget'], 'Canonical measured budget no longer fits')
    timing_files = sorted((ROOT/'performance_timings').rglob('timing.json'))
    require(len(timing_files) >= 72,'Strict full-workload performance timing missing')
    for path in timing_files:
        timing = load(path)
        require(timing['fresh_native_timing'] and timing['identity']['source'] == reg['source'], 'Wrong-source strict benchmark')
        for key in ('manifest','boundary','reviewer'):verify_reference(timing['identity'][key])
    require(all(row.get('profile') == 'complete_registered_training_workload' and row['jobs'] >= 24
                for row in budget['concurrency']), 'Unrepresentative concurrency workload')
    overhead = checkpoint_cost(budget)
    require(budget['budget']['estimated_seconds']+overhead['estimated_seconds'] <= 72*3600*.85,
        'Strict native/F04 plus durable checkpoint estimate does not fit72h with15% reserve')
    paths = {
        'scientific_formulation':[SOURCE/'configs/gama/objective.json',BASE/'R01_R03_PREREGISTRATION.json',
            BASE/'R01_EXECUTION_DESIGN.json',ROOT/'model_acceptance.json',ROOT/'authorization.json'],
        'gui_headless':[ROOT/'gui_scope.json',OUTPUT/'validation.json'],
        'configuration':[ROOT/'benchmark/locked_config.json',ROOT/'benchmark/accuracy_gate.json',ROOT/'gui_scope.json'],
        'data_complete':[BASE/'accepted_data_v5/acceptance.json',ROOT/'certificate.json'],
        'calibration':[ROOT/'certificate.json',Path(config.calibration),ROOT/'compatibility_acceptance.json'],
        'predictive_validity':[ROOT/'model_acceptance.json',ROOT/'predictive/acceptance.json'],
        'accuracy_mc':[ROOT/'benchmark/accuracy_gate.json'],
        'development':[OUTPUT/'development_validation.json'],
        'design_freeze':[OUTPUT/'design_freeze.json',ROOT/'design_decision.json'],
        'performance_budget':[ROOT/'benchmark/budget.json',ROOT/'checkpoint_io_estimate.json',*timing_files],
        'optimizer_smoke':[ROOT/'native_smoke/acceptance.json'],
        'checkpoint_resume':[ROOT/'native_smoke/acceptance.json',Path(smoke['interruption_proof']['path']),Path(smoke['checkpoint']['path'])]}
    gates = {'model_native':reference(OUTPUT/'validation.json')}
    for name,items in paths.items():
        path = ROOT/'gates'/(name+'.json')
        write_json(path,dict(kind=name,passed=True,source=reg['source'],objective_version=OBJECTIVE_VERSION,
            objective_config_hash=OBJECTIVE_CONFIG_HASH,dependencies=[reference(ROOT/'registration.json'),
                reference(ROOT/'engineering_acceptance.json'),*[reference(p) for p in items]]))
        gates[name]=reference(path)
    require(set(gates) == PRE_TRAINING_GATES,'Incomplete canonical gates')
    proof = dict(kind='pre_training_acceptance',passed=True,source=reg['source'],gates=gates,
                 held_out_720=False,dependencies=[reference(ROOT/'registration.json'),reference(ROOT/'checkpoint_io_estimate.json')])
    path = OUTPUT/'pre_training_acceptance.json'
    require(not path.exists(),'Existing official proof needs compatible resume; never overwrite')
    write_json(path,proof)
    rng=ROOT/'native_smoke/native_rng_comparison.json'
    write_json(OUTPUT/'blocker_acceptance.json',dict(kind='integrated_training_blocker_acceptance',passed=True,source=reg['source'],resolved_findings=['PR01','PR02','PR03','PR04','PR05'],compatibility=reference(ROOT/'certificate.json'),native_rng=reference(rng),dependencies=[reference(ROOT/'engineering_acceptance.json'),reference(ROOT/'certificate.json'),reference(rng),reference(path),reference(ROOT/'model_acceptance.json')]))
    verify_training_acceptance(path)
    return proof


def release_hold(reg):
    check(reg)
    proof = verify_training_acceptance(OUTPUT/'pre_training_acceptance.json')
    require(proof['source'] == reg['source'],'Wrong source readiness')
    require(not original_busy(ownership_snapshot()),'Original worker/process remains active')
    capacity(load(ROOT/'benchmark/budget.json')['workers'])
    hold = load(BASE/'TRAINING_LAUNCH_HOLD.json')
    guard = Path(hold['guard_path'])
    marker=guard/'PR01_PR05_INTEGRATION_PENDING.json'
    require(guard.stat().st_ino == reg['hold_inode'] and marker.exists() and set(guard.iterdir())=={marker},'Foreign/pending reservation data; cannot release')
    owned=load(marker)
    require(owned['owner']==str(ROOT),'Integration blocker ownership mismatch')
    from ranr.gama.recovery_transition import verify_blocker_acceptance
    verify_blocker_acceptance()
    marker.rename(ROOT/'integration_blocker_released.json')
    require(not list(guard.iterdir()),'Reservation not empty after scoped blocker release')
    require(not (BASE/'official_training/inputs_frozen.json').exists(), 'Official inputs already exist; resume required')
    write_json(ROOT/'hold_release_acceptance.json',dict(kind='official_launch_release',passed=True,source=reg['source'],
        dependencies=[reference(OUTPUT/'pre_training_acceptance.json'),reference(ROOT/'registration.json')]))
    archive = BASE/'official_training'/'administrative_reservation_20261027'
    require(not archive.exists(),'Launch reservation archive already exists')
    # Rename the EMPTY reservation under exclusive inherited legacy locks.
    guard.rename(archive)
    hold.update(active=False,released_at=time.time(),release_acceptance=reference(ROOT/'hold_release_acceptance.json'),
                archived_reservation=str(archive))
    write_json(BASE/'TRAINING_LAUNCH_HOLD.json',hold)


def official(reg, locks, resume=False):
    from ranr.gama.training_time import still_alive
    optimizer = BASE/'official_training/optimizer'
    frozen = BASE/'official_training/inputs_frozen.json'
    if resume:
        require(frozen.exists() and optimizer.exists(),'No official checkpoint to resume')
        entry=load(frozen)
        require(entry['source'] == reg['source'],'Official frozen source changed')
        for ref in entry['dependencies']:verify_reference(ref)
        checkpoint=pickle.loads((optimizer/'checkpoint.pkl').read_bytes())
        journal=load(optimizer/'training_time.json');marker=load(optimizer/'registration.json')
        require(checkpoint['registration']['source'] == reg['source'] and
            checkpoint['registration']['budget_sha256'] == digest(ROOT/'benchmark/budget.json') and
            checkpoint['registration']['config'] == asdict(RunConfig.load(ROOT/'benchmark/locked_config.json')),
            'Resume checkpoint identity changed')
        require(checkpoint['status'] in ('running','interrupted') and marker['status'] in ('running','interrupted')
            and not still_alive(journal['owner']) and 0 <= journal['consumed_seconds'] < 72*3600
            and 0 <= checkpoint['active_seconds'] < 72*3600, 'Resume owner/status/budget invalid')
        if marker['status'] == 'interrupted':
            require('Training termination requested' in load(optimizer/'diagnostic.json').get('error',''),
                    'Unknown official error requires review; no automatic retry')
        for path in optimizer.rglob('owned_processes.json'):
            require(not any(still_alive(owner) for owner in load(path)),'Native child survives; no duplicate resume')
        for path in optimizer.rglob('manifest.json'):
            record=load(path)
            require(record.get('status') != 'failed' or 'Training termination requested' in record.get('failure_reason',''),
                    'Invalid native result needs review before resume')
        verify_training_acceptance(OUTPUT/'pre_training_acceptance.json')
    else:
        require(not frozen.exists(),'Existing official input freeze; fresh budget forbidden')
        release_hold(reg)
        write_json(frozen,dict(source=reg['source'],hours=72,methods=list(METHODS),population=16,
            optimizer_seeds=[41001,41002,41003],held_out_720=False,reset_budget=False,
            candidate_design=[[case,11001+i] for i,case in enumerate(CASES)],
            validation_design=[[case,21001+i] for i,case in enumerate(CASES)],
            dependencies=[reference(ROOT/'registration.json'),reference(OUTPUT/'pre_training_acceptance.json'),
                reference(ROOT/'benchmark/locked_config.json'),reference(ROOT/'benchmark/budget.json'),
                reference(ROOT/'certificate.json'),reference(Path(load(ROOT/'benchmark/locked_config.json')['calibration'])),
                reference(HERE/'strict_optimizer_entry.py'),reference(HERE/'strict_fitness_boundary.py')]))
    require(not competing_jobs(),'Another official optimizer/evaluation is active')
    command=[sys.executable,'-B',str(HERE/'strict_optimizer_entry.py'),
        '--config',str(ROOT/'benchmark/locked_config.json'),'--budget',str(ROOT/'benchmark/budget.json'),
        '--output',str(optimizer)]+(['--resume'] if resume else [])
    write_json(ROOT/'official_command.json',dict(command=command,resume=resume,held_out_720=False,
        cumulative_hours=72,legacy_locks_inherited=True))
    run_child('official_training',command,reg,timeout=72*3600+180,lock_files=locks,hold=False)
    marker=load(optimizer/'registration.json')
    require(marker['status'] in ('complete','budget_limited'),'Official training did not finish cleanly')
    write_json(BASE/'official_training/lineage.json',dict(source=reg['source'],status=marker['status'],
        completed_model=marker['status']=='complete',held_out_720=False,
        dependencies=[reference(frozen),reference(optimizer/'registration.json'),
            reference(optimizer/'checkpoint.pkl'),reference(optimizer/'training_time.json')]))
    status('official_training',status=marker['status'],official_training=marker['status'].upper(),training_ready=True)


def register():
    require(not (ROOT/'registration.json').exists(),'Registration already exists')
    hold=load(BASE/'TRAINING_LAUNCH_HOLD.json')
    paths=[ROOT/'authorization.json',ROOT/'engineering_acceptance.json',ROOT/'certificate.json',ROOT/'compatibility_acceptance.json',ROOT/'base_config.json',BASE/'R01_R03_PREREGISTRATION.json',BASE/'R01_EXECUTION_DESIGN.json',PARENT/'registration.json',BASE/'mc_parallel_prefetch_20261027/registration.json']
    paths+=sorted(HERE.glob('*.py'))
    paths += [SOURCE/'tests/native_reviews/RanrPairedPhysicalReplay.gaml',ROOT/'service_unit.service',ROOT/'service_command.json']
    record=dict(kind='exclusive_integrated_optimizer_recovery_pipeline',source=provenance(),source_commit=subprocess.check_output(['git','-C',str(SOURCE),'rev-parse','HEAD'],text=True).strip(),service=UNIT,created_at=time.time(),heap_mib=8192,hours=72,worker_options=[1,2],hold_inode=Path(hold['guard_path']).stat().st_ino,automatic_retry=False,predecessor_observation_only=True,registered_boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),dependencies=[reference(p) for p in paths])
    write_json(ROOT/'registration.json',record)
    status('waiting_existing_workers',status='running',training_ready=False,official_training='BLOCKED',completed={},reason='Predecessor MC/helper retain ownership; integrated source waits without launching GAMA')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('register','run','resume','action'))
    parser.add_argument('stage',nargs='?')
    args=parser.parse_args()
    if args.command == 'register':register();return
    if args.command == 'action':action(args.stage);return
    with (ROOT/'.worker.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        reg=load(ROOT/'registration.json');previous=load(ROOT/'state.json')
        require(previous['status'] not in ('failed','blocked','complete','budget_limited'),
                'Failed/finished pipeline cannot retry automatically; inspect scientific/technical diagnostic')
        if args.command == 'resume':
            require((BASE/'official_training/inputs_frozen.json').exists(),'Resume only for existing official checkpoint')
        else:
            require(not (BASE/'official_training/inputs_frozen.json').exists(),'Existing official state requires resume; never create a new72h budget')
        completed=previous.get('completed',{})
        try:
            while True:
                check(reg,require_hold=args.command != 'resume')
                snapshot=ownership_snapshot();write_json(ROOT/'upstream_snapshot.json',snapshot)
                check_scientific_stop(snapshot)
                if not original_busy(snapshot):
                    if snapshot['parent'].get('status')=='running':
                        from reboot_recovery import recover
                        if recover(ROOT,reg,snapshot):
                            time.sleep(30)
                            continue
                    verify_original_boundary(snapshot)
                    break
                status('waiting_existing_workers',status='running',training_ready=False,official_training='BLOCKED',
                    reason='Original validation workers still own the pipeline; no competing simulation launched')
                time.sleep(30)
            with legacy_locks() as streams:
                verify_original_boundary(ownership_snapshot())
                write_json(ROOT/'ownership.json',dict(pid=os.getpid(),legacy_locks=True,
                    snapshot=ownership_snapshot(),acquired_at=time.time()))
                if args.command == 'resume':official(reg,streams,resume=True);return
                stages=[('adopt',[sys.executable,'-B',str(Path(__file__)),'action','adopt'])]
                stages += [(name,[sys.executable,'-B',str(Path(__file__)),'action',name]) for name in
                    ('predictive','model','smoke','development','design','freeze','performance')]
                for name,command in stages:
                    check(reg);capacity(1)
                    if name in completed:
                        for ref in completed[name]['evidence']:verify_reference(ref)
                        continue
                    run_child(name,command,reg,lock_files=streams)
                    evidence={
                        'adopt':[ROOT/'adoption.json'],
                        'accuracy':[ROOT/'benchmark/accuracy_gate.json',ROOT/'benchmark/accuracy_config.json'],
                        'predictive':[ROOT/'predictive/acceptance.json'], 'model':[ROOT/'model_acceptance.json'],
                        'smoke':[ROOT/'native_smoke/acceptance.json'], 'development':[OUTPUT/'development_validation.json'],
                        'design':[ROOT/'design/review.json'],'freeze':[OUTPUT/'design_freeze.json'],
                        'performance':[ROOT/'benchmark/budget.json']}[name]
                    completed[name]=dict(finished_at=time.time(),evidence=[reference(p) for p in evidence])
                    status(name,status='running',completed=completed)
                capacity(load(ROOT/'benchmark/budget.json')['workers'])
                readiness(reg)
                completed['readiness']=dict(evidence=[reference(OUTPUT/'pre_training_acceptance.json')])
                status('training_ready',status='running',completed=completed,training_ready=True,
                    reason='All thirteen gates verified; conditional official launch authorized')
                official(reg,streams)
        except BaseException as error:
            diagnostic=dict(error=str(error),traceback=traceback.format_exc(),at=time.time(),automatic_retry=False)
            write_json(ROOT/'diagnostic.json',diagnostic)
            status('fail_stop',status='failed',training_ready=False,official_training='BLOCKED',
                   reason=str(error),automatic_retry=False)
            raise


if __name__ == '__main__':main()
