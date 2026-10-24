"""Monitor only descendants of the owned research runtime; never restart a gate."""
from pathlib import Path
import argparse
import json
import os
import signal
import subprocess
import sys
import time
sys.path.insert(0,str(Path(__file__).parent))
import chunk_runtime as mc_runtime
from ranr.paths import write_json


class ActivityTracker:
    def __init__(self,limit=1200):self.limit=limit;self.samples={}
    def update(self,pid,start,cpu,io,now):
        token=(pid,start);previous=self.samples.get(token)
        change=now if previous is None or previous['cpu']!=cpu or previous['io']!=io else previous['last_change']
        self.samples[token]={'cpu':cpu,'io':io,'last_change':change}
        return {'pid':pid,'start_ticks':start,'seconds_without_activity':max(0.,now-change),
                'cpu_ticks':cpu,'io_bytes':io,'stalled':now-change>self.limit}


def descendants(root):
    rows={}
    for path in Path('/proc').iterdir():
        if not path.name.isdigit():continue
        try:
            text=(path/'stat').read_text();tail=text[text.rfind(')')+2:].split()
            rows[int(path.name)]={'ppid':int(tail[1]),'state':tail[0],'start':tail[19],
                'cpu':int(tail[11])+int(tail[12]),'rss_kib':int(tail[21])*os.sysconf('SC_PAGE_SIZE')//1024,'path':path}
        except (OSError,ValueError,IndexError):continue
    owned={root};changed=True
    while changed:
        added={pid for pid,row in rows.items() if row['ppid'] in owned}-owned
        changed=bool(added);owned|=added
    result=[]
    for pid in owned:
        row=rows.get(pid)
        if row is None:continue
        path=row.pop('path')
        try:
            command=(path/'cmdline').read_bytes().replace(b'\0',b' ').decode(errors='replace')
            if '/jdk/bin/java ' not in command:continue
            io={k:int(v.strip()) for k,v in (line.split(':',1) for line in (path/'io').read_text().splitlines())}
            result.append({'pid':pid,**row,'io':io.get('read_bytes',0)+io.get('write_bytes',0),'command':command})
        except (OSError,ValueError):continue
    return result



def scientific_block(release):
    state=json.loads((release/'state.json').read_text())
    if state.get('status') in {'complete','budget_limited'}:
        return 'Release already '+state['status']+'; preserve its final state'
    certificate=release/'benchmark/conclusive_reference_failure.json'
    if certificate.exists():
        sys.path.insert(0,str(mc_runtime.ROOT/'operations/research_reporting_20261023'))
        from reporting_checks import failure_certificate
        failure_certificate(certificate)
        return 'Registered maximum Monte Carlo reference failed; a new research protocol needs review'
    stability=release/'benchmark/reference_stability.json'
    if state.get('status')=='needs_attention' and stability.exists():
        record=json.loads(stability.read_text())
        high=release/'benchmark/probes_16384.csv';low=release/'benchmark/probes_8192.csv'
        if record.get('samples')==8192 and record.get('check_samples')==16384 and record.get('passed') is False and high.exists() and low.exists():
            keys=mc_runtime.benchmarking.PROBE_KEYS
            a=mc_runtime.old.read_table(low,keys);b=mc_runtime.old.read_table(high,keys)
            data=lambda rows:{key:{name:float(row[name]) for name in mc_runtime.NUMERIC} for key,row in rows.items()}
            errors=mc_runtime.benchmarking.probe_errors(data(a),data(b),.5)
            if any(row['pass_fraction']<.95 for row in errors.values()):return 'Full maximum reference failed; do not automatically retry a scientific gate'
    accuracy=release/'benchmark/accuracy.json'
    if state.get('status')=='needs_attention' and accuracy.exists():
        records=json.loads(accuracy.read_text())
        if records and records[-1].get('samples')==4096:
            methods=records[-1].get('methods',{})
            if set(methods)==set(mc_runtime.benchmarking.METHODS[:3]) and any(row['pass_fraction']<.95 for row in methods.values()):
                return 'Maximum registered candidate samples failed estimator accuracy; a research-protocol decision is required'
    budget=release/'benchmark/budget.json'
    if state.get('status')=='needs_attention' and budget.exists():
        record=json.loads(budget.read_text())
        if record.get('passed') is False:return 'Measured 72-hour training budget is infeasible; resources/protocol decision required'
    physical=release/'benchmark/physical_steps.json'
    if state.get('status')=='needs_attention' and physical.exists():
        record=json.loads(physical.read_text())
        if record.get('60',{}).get('passed') is False:return 'Registered 60-second physical step failed; do not automatically retry a scientific gate'
    if state.get('status')=='needs_attention':
        review_path=release/'infra_retry_review.json'
        if not review_path.exists():return 'Unreviewed failed stage: inspect diagnostics before a one-time infrastructure retry; scientific failures are never automatically retried'
        review=json.loads(review_path.read_text())
        if review.get('kind')!='temporary_infrastructure_recovery' or review.get('source')!=mc_runtime.provenance() or review.get('state_sha256')!=mc_runtime.digest(release/'state.json') or not review.get('reason','').strip() or not review.get('dependencies'):
            raise ValueError('Infrastructure retry review does not cover this exact state/source')
        for item in review['dependencies']:mc_runtime.verify_reference(item)
        if state.get('current_stage')=='training':
            for name in ('checkpoint.pkl','elapsed_journal.json'):
                if review.get('training_files',{}).get(name)!=mc_runtime.digest(release/'training'/name):raise ValueError('Training recovery checkpoint/time journal changed after review')
        history=release/'infra_retry_history'/f'{time.time_ns()}.json';history.parent.mkdir(parents=True,exist_ok=True)
        os.replace(review_path,history)
    return None


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--release',type=Path,required=True);parser.add_argument('--workers',type=int,default=3)
    args=parser.parse_args();output=Path(__file__).parent/'runtime_monitor';output.mkdir(exist_ok=True)
    block=scientific_block(args.release)
    if block:
        write_json(output/'scientific_block.json',{'reason':block,'release':str(args.release),'at':time.time(),'automatic_retry':False})
        print(block,flush=True);return 0 if block.startswith('Release already ') else 42
    cmd=[sys.executable,'-B',str(Path(__file__).parent/'chunk_runtime.py'),'release','--output',str(args.release),'--workers',str(args.workers)]
    child=subprocess.Popen(cmd,cwd=mc_runtime.ROOT)
    def stop(signum,frame):
        if child.poll() is None:child.send_signal(signal.SIGTERM)
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    tracker=ActivityTracker()
    try:
        while child.poll() is None:
            now=time.monotonic();rows=descendants(child.pid);activity=[]
            for row in rows:
                item=tracker.update(row['pid'],row['start'],row['cpu'],row['io'],now);activity.append(item)
                if item['stalled']:
                    # Capture evidence before terminating this exact owned Java.
                    diagnostic=output/f"stall_{row['pid']}_{time.time_ns()}";diagnostic.mkdir()
                    write_json(diagnostic/'process.json',row)
                    try:
                        result=subprocess.run(['/opt/gama-platform/jdk/bin/jcmd',str(row['pid']),'Thread.print','-l'],capture_output=True,text=True,timeout=25)
                        (diagnostic/'threads.txt').write_text(result.stdout+result.stderr)
                    except (OSError,subprocess.TimeoutExpired) as error:(diagnostic/'dump_error.txt').write_text(str(error))
                    refreshed={r['pid']:r for r in descendants(child.pid)}
                    if row['pid'] in refreshed and refreshed[row['pid']]['start']==row['start']:
                        os.kill(row['pid'],signal.SIGTERM)
                    write_json(diagnostic/'action.json',{'action':'terminate_stalled_owned_java','automatic_retry':False,'at':time.time()})
            write_json(output/'watchdog.json',{'updated_at':time.time(),'runtime_pid':child.pid,'java_processes':activity,
                'rss_kib':sum(row['rss_kib'] for row in rows),'policy':'20 min without Java CPU or disk-I/O activity; diagnose and fail, never restart scientific gates'})
            try:child.wait(timeout=30)
            except subprocess.TimeoutExpired:pass
        return child.returncode
    finally:
        if child.poll() is None:
            child.terminate()
            try:child.wait(timeout=30)
            except subprocess.TimeoutExpired:child.kill();child.wait()


if __name__=='__main__':sys.exit(main())
