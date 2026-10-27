"""One guarded predecessor recovery after an actual boot change; no gate retry."""
import csv
import json
import math
import os
from pathlib import Path
import subprocess
import time

def eligible(reg,snapshot,boot):
    parent=snapshot['parent']
    return (boot!=reg['registered_boot_id'] and parent.get('status')=='running'
        and parent.get('stage')=='accuracy' and not snapshot['live_owned_processes']
        and not snapshot['competing'] and all(int(p.get('MainPID','0'))==0
        and p.get('ActiveState') not in ('active','activating','deactivating','reloading')
        for p in snapshot['services'].values()))

def recover(root,reg,snapshot):
    from ranr.gama.evidence import verify_reference
    from ranr.paths import write_json,digest
    root=Path(root);base=root.parent;parent=base/'heap8_revalidation_20261027'
    boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    if not eligible(reg,snapshot,boot):return False
    marker=root/('reboot_resume_'+boot+'.json')
    if marker.exists():raise ValueError('Reboot recovery already attempted this boot; unknown failure is not retried')
    if (parent/'benchmark/accuracy_gate.json').exists():raise ValueError('Completed predecessor requires ownership review, not MC restart')
    if (base/'official_training/inputs_frozen.json').exists():raise ValueError('Official state cannot use predecessor recovery')
    original=json.loads((parent/'registration.json').read_text())
    for item in original['dependencies']:verify_reference(item)
    source=base/'calibration_source'
    for category in ['gaml','orchestrator','gis','configuration_fixtures','launcher']:
        for name,sha in original['source'][category].items():
            if digest(source/name)!=sha:raise ValueError('Predecessor input/source drift before reboot recovery')
    archived=[]
    # A power-loss-truncated write is not a completed cache. Keep every valid
    # complete CSV unchanged; archive only structurally invalid pre-gate output.
    for file in (parent/'benchmark').glob('probes_*.csv'):
        n=int(file.stem.split('_')[-1])
        with file.open() as f:rows=list(csv.DictReader(f))
        keys={(r.get('method'),r.get('station'),r.get('probe')) for r in rows}
        expected={(m,str(s),str(p)) for m in ('RANR-AW','No-P2P','No-Prediction') for s in range(11) for p in range(5)}
        try:complete=(len(rows)==165 and keys==expected and all(math.isfinite(float(r[k])) for r in rows for k in ['mean','p95','externality']) and int(rows[-1]['queue_calls'])==275*n)
        except (KeyError,ValueError):complete=False
        if not complete:
            target=root/'reboot_incomplete_cache'/boot/file.name;target.parent.mkdir(parents=True,exist_ok=True)
            archived.append(dict(original=str(file),sha256=digest(file),archived=str(target)))
            file.rename(target)
    command=json.loads((parent/'service_command.json').read_text())['command']
    if command[:4]!=['systemd-run','--user','--unit','gama-ranr-heap8-revalidation-20261027.service']:
        raise ValueError('Unexpected predecessor recovery command')
    write_json(marker,dict(kind='single_boot_predecessor_recovery',boot_id=boot,at=time.time(),
        command=command,archived_incomplete_csv=archived,helper_restarted=False,
        source_changed=False,official_budget_reset=False,scientific_retry=False))
    result=subprocess.run(command,capture_output=True,text=True,timeout=30)
    write_json(root/'reboot_recovery_result.json',dict(returncode=result.returncode,
        stdout=result.stdout,stderr=result.stderr,boot_id=boot))
    if result.returncode:raise RuntimeError('Predecessor reboot recovery command failed; no automatic retry')
    return True
