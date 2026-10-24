"""Current scientific release and both generations of native checkpoints."""
from pathlib import Path
import json,time
ROOT=Path('/home/tinnt/Gama_Workspace/Nha Trang CSs planning')
release=Path(json.loads((ROOT/'outputs/gama_ranr/release_latest.json').read_text())['output'])
state=json.loads((release/'state.json').read_text());reg=json.loads((release/'registration.json').read_text())
result={'release':release.name,'service':reg['service'],'status':state['status'],'stage':state.get('current_stage'),
    'state_path':str(release/'state.json'),'log':str(release/(str(state.get('current_stage'))+'.log')),'checkpoints':[]}
for layout in ('native_shards','native_chunks'):
    for path in sorted((release/'benchmark'/layout).glob('*/progress.json')):
        data=json.loads(path.read_text());data['layout']=layout;data['progress_path']=str(path)
        data['progress_age_seconds']=round(time.time()-data['updated_at'],1);data['active_jobs']=[]
        for heartbeat in path.parent.rglob('heartbeat.json'):
            manifest=heartbeat.with_name('manifest.json')
            if manifest.exists() and json.loads(manifest.read_text())['status']=='running':
                row=json.loads(heartbeat.read_text());row['age_seconds']=round(time.time()-row['updated_at'],1);data['active_jobs'].append(row)
        result['checkpoints'].append(data)
monitor=Path(__file__).parent/'runtime_monitor/watchdog.json'
if monitor.exists():result['owned_runtime']=json.loads(monitor.read_text())
certificate=release/'benchmark/conclusive_reference_failure.json'
if certificate.exists():
    proof=json.loads(certificate.read_text());result['scientific_failure']={k:proof[k] for k in ('method','maximum_pass_fraction','required_fraction','failed_probes','observed_probes')}
for name in ('training','optimizer_smoke'):
    path=release/name/'elapsed_journal.json'
    if path.exists():result[name+'_elapsed_journal']=json.loads(path.read_text())
print(json.dumps(result,ensure_ascii=False,indent=2))
