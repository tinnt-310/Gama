"""Read-only runtime/input snapshot; writes only this preparation workspace."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parents[2].parent
BASE = HERE.parent
SOURCE = BASE / 'calibration_source'
UNITS = ['gama-ranr-heap8-revalidation-20261027.service',
         'gama-ranr-mc-parallel-prefetch-20261027.service',
         'gama-ranr-autonomous-integration-20261027.service']

def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()

def capture(label):
    value = dict(kind='preparation_runtime_snapshot', epoch=time.time(), label=label,
                 units={}, processes={}, inputs=[], states={}, preparation_signals_sent=False)
    for unit in UNITS:
        result = subprocess.run(['systemctl','--user','show',unit,'--no-pager',
            '--property=Id,ActiveState,SubState,MainPID,ControlGroup,MemoryCurrent,MemoryMax,CPUUsageNSec,Restart,KillMode'],
            capture_output=True,text=True)
        props = dict(line.split('=',1) for line in result.stdout.splitlines() if '=' in line)
        if not props:props=dict(MainPID='0',ActiveState='inactive',SubState='not-found')
        value['units'][unit] = props
        cg = Path('/sys/fs/cgroup') / props.get('ControlGroup','').lstrip('/')
        pids = set()
        if props.get('MainPID','0') != '0': pids.add(int(props['MainPID']))
        if props.get('ControlGroup') not in (None,'','/') and cg.is_dir():
            for file in cg.rglob('cgroup.procs'):
                try: pids.update(map(int,file.read_text().split()))
                except OSError: pass
        for pid in sorted(pids):
            try:
                root = Path('/proc') / str(pid)
                fields = (root/'stat').read_text().rsplit(')',1)[1].split()
                value['processes'][str(pid)] = dict(start_ticks=fields[19], state=fields[0],
                    cpu_ticks=int(fields[11])+int(fields[12]),
                    command=(root/'cmdline').read_bytes().replace(b'\0',b' ').decode(errors='replace'),
                    cgroup=(root/'cgroup').read_text())
            except OSError: pass
    for name in ['heap8_revalidation_20261027','mc_parallel_prefetch_20261027','autonomous_integration_20261027']:
        regfile = BASE/name/'registration.json'
        if not regfile.exists():continue
        reg = json.loads(regfile.read_text())
        items = [dict(path=str(regfile),sha256=sha(regfile)), *reg['dependencies']]
        if name.startswith('heap8') or name.startswith('autonomous'):
            for category in ['gaml','orchestrator','gis','configuration_fixtures','launcher']:
                execution=(HERE/'source') if name.startswith('autonomous') else SOURCE
                items += [dict(path=str(execution/rel),sha256=digest) for rel,digest in reg['source'][category].items()]
        for item in items:
            p = Path(item['path']); actual = sha(p) if p.is_file() else None
            value['inputs'].append(dict(owner=name,**item,actual=actual,matches=actual==item['sha256']))
        value['states'][name] = json.loads((BASE/name/'state.json').read_text())
    for name in ['TRAINING_LAUNCH_HOLD.json','accepted_data_v5/calibration.json']:
        p = BASE/name
        value['inputs'].append(dict(path=str(p),actual=sha(p),scope='protected reference'))
    mem = dict(line.split(':',1) for line in Path('/proc/meminfo').read_text().splitlines())
    value['memory_kib'] = {k:int(mem[k].split()[0]) for k in ['MemTotal','MemAvailable','SwapTotal','SwapFree']}
    value['disk'] = dict(zip(['total','used','free'],shutil.disk_usage(BASE)))
    value['all_registered_hashes_match'] = all(i.get('matches',True) for i in value['inputs'])
    value['official_artifacts_exist'] = {name:(BASE/'official_training/optimizer'/name).exists()
        for name in ['checkpoint.pkl','training_time.json','registration.json']}
    (HERE/f'runtime_{label}.json').write_text(json.dumps(value,indent=2)+'\n')
    print(json.dumps(dict(label=label,hashes_match=value['all_registered_hashes_match'],
                         units=value['units'],process_count=len(value['processes']))))

if __name__ == '__main__': capture(sys.argv[1])
