"""Read official release state plus sealed native Monte Carlo progress."""
from pathlib import Path
import json,time
ROOT=Path('/home/tinnt/Gama_Workspace/Nha Trang CSs planning')
o=ROOT/'outputs/gama_ranr';release=Path(json.loads((o/'release_latest.json').read_text())['output'])
s=json.loads((release/'state.json').read_text());registration=json.loads((release/'registration.json').read_text())
result={'release':release.name,'service':registration['service'],'status':s.get('status'),'stage':s.get('current_stage'),
 'state':str(release/'state.json'),'log':str(release/(str(s.get('current_stage'))+'.log')),
 'state_age_seconds':round(time.time()-s['updated_at'],1),'stages':{k:v['status'] for k,v in s['stages'].items()},'monte_carlo':[]}
for path in sorted((release/'benchmark/native_shards').glob('*/progress.json')):
 p=json.loads(path.read_text());active=[]
 for heartbeat in path.parent.glob('*/*/*/heartbeat.json'):
  m=heartbeat.parent/'manifest.json';state=json.loads(m.read_text()) if m.exists() else {}
  if state.get('status')=='running':
   record=json.loads(heartbeat.read_text());record['age_seconds']=round(time.time()-record['updated_at'],1);active.append(record)
 result['monte_carlo'].append({**p,'progress_path':str(path),'active_probes':active})
failure=release/'benchmark/conclusive_reference_failure.json'
if failure.exists():result['scientific_gate_failure']=json.loads(failure.read_text())
for name in ('training','optimizer_smoke'):
 path=release/name/'elapsed_journal.json'
 if path.exists():result[name+'_elapsed_journal']=json.loads(path.read_text())
print(json.dumps(result,ensure_ascii=False,indent=2))
