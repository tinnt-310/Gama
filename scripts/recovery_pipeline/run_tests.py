"""Bounded synthetic engineering checks. Never invokes GAMA or production train."""
import os
from pathlib import Path
import resource
import signal
import shutil
import sys
import time

SOURCE = Path(__file__).resolve().parents[2]
HERE = SOURCE.parent/'engineering_tests'
BASE = SOURCE.parent.parent
os.environ['RECOVERY_TEST_OUTPUT']=str(HERE/'results')
os.environ.update(RANR_WORKSPACE=str(SOURCE), PYTHONDONTWRITEBYTECODE='1',
    OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1',
    MPLCONFIGDIR=str(HERE/'cache/mpl'), TMPDIR=str(HERE/'tmp'))
for directory in ['tmp','cache/mpl','results']:(HERE/directory).mkdir(parents=True,exist_ok=True)
resource.setrlimit(resource.RLIMIT_AS,(1536*1024**2,1536*1024**2))
resource.setrlimit(resource.RLIMIT_CPU,(290,295))
os.sched_setaffinity(0,{min(os.sched_getaffinity(0))})
os.nice(10)
signal.signal(signal.SIGALRM,lambda *_: (_ for _ in ()).throw(TimeoutError('Preparation batch wall limit300s')))
signal.alarm(300)
sys.dont_write_bytecode = True
sys.path[:0] = [str(SOURCE/'tests/recovery_integration'),str(SOURCE/'src'),str(SOURCE/'scripts/recovery_pipeline')]

def writable(value):
    if isinstance(value,int):return
    path = Path(os.fsdecode(value)).resolve()
    if path==Path('/dev/null'):return
    if path != HERE and HERE not in path.parents:
        raise PermissionError('Preparation refuses write outside isolated workspace: '+str(path))

def audit(event,args):
    if event == 'open':
        path,mode,flags = args
        if flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND):writable(path)
    elif event in {'os.remove','os.rmdir','os.mkdir','os.chmod','os.utime','os.truncate'}:writable(args[0])
    elif event in {'os.rename','os.link'}:writable(args[0]);writable(args[1])
    elif event=='subprocess.Popen':
        executable=Path(shutil.which(os.fsdecode(args[0])) or os.fsdecode(args[0])).resolve()
        if executable not in {Path(sys.executable).resolve(),Path('/usr/bin/ps').resolve()}:
            raise PermissionError('Only bounded owned Python fixtures/read-only ps allowed; no GAMA')
    elif event in {'os.system','os.exec','os.posix_spawn','os.fork'}:
        raise PermissionError('No unregistered execution allowed inside integration tests')
    elif event in {'os.kill','os.killpg'}:
        pid=int(args[0])
        try:fields=(Path('/proc')/str(pid)/'stat').read_text().rsplit(')',1)[1].split()
        except OSError:raise PermissionError('Signal target is not a live owned fixture')
        if int(fields[1])!=os.getpid():raise PermissionError('Signal target is not a direct owned test child')
sys.addaudithook(audit)

import json
import hashlib
import importlib
import unittest
import ranr.gama.training as training
from ranr.gama.execution import assert_checkout_modules
assert_checkout_modules()
from ranr.gama import long_collection
long_collection.COLLECTION_ROOT=HERE/'tmp/isolated_collection_locks'
tested_source=training.provenance()
runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
rng_files=[Path(importlib.import_module(n).__file__) for n in ['cma.evolution_strategy','cma.sampler','numpy.random.mtrand','numpy.random._mt19937','numpy.random._pickle']]
rng_hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in rng_files}
started = time.monotonic()
suite_name = sys.argv[1]
suite = (unittest.defaultTestLoader.discover(str(SOURCE/'tests'),pattern='test_*.py') if suite_name=='regression' else unittest.defaultTestLoader.loadTestsFromName(suite_name))
result = unittest.TextTestRunner(verbosity=2).run(suite)
test_module=sys.modules.get(suite_name)
effective=getattr(test_module,'tr',None) or getattr(test_module,'pv',None)
if training.provenance()!=tested_source:raise ValueError('Source changed during integrated tests')
if runner_sha256!=hashlib.sha256(Path(__file__).read_bytes()).hexdigest():raise ValueError('Test harness changed during execution')
if any(hashlib.sha256(Path(p).read_bytes()).hexdigest()!=h for p,h in rng_hashes.items()):raise ValueError('RNG dependency changed during tests')
record = dict(kind='integrated_engineering_tests',source=tested_source,runner_sha256=runner_sha256,rng_files=rng_hashes,suite=suite_name,tests=result.testsRun,
    patched_candidate=os.environ.get('PREPARATION_PATCHED')=='1',
    failures=[(str(t),s) for t,s in result.failures],errors=[(str(t),s) for t,s in result.errors],
    expected_failures=[str(t) for t,_ in result.expectedFailures],
    unexpected_successes=[str(t) for t in result.unexpectedSuccesses],
    elapsed_seconds=time.monotonic()-started,peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    affinity=sorted(os.sched_getaffinity(0)),address_space_limit_bytes=1536*1024**2,wall_limit_seconds=300,
    module_origin=training.__file__,native_gama_invoked=False,native_smoke_passed=False,
    effective_code_origin=getattr(effective,'__file__',None),
    execution_scope='Isolated synthetic engine/F04 fixtures; candidate code is not accepted execution provenance',
    scientific_acceptance_created=False,all_unexpected_checks_pass=result.wasSuccessful())
suffix='_candidate' if record['patched_candidate'] else ''
(HERE/'results'/f'{suite_name}{suffix}.json').write_text(json.dumps(record,indent=2)+'\n')
sys.exit(0 if result.wasSuccessful() else 1)
