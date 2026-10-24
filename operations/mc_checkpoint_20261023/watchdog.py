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
import mc_runtime
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


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--release',type=Path,required=True);parser.add_argument('--workers',type=int,default=3)
    args=parser.parse_args();output=Path(__file__).parent/'runtime_monitor';output.mkdir(exist_ok=True)
    cmd=[sys.executable,'-B',str(Path(__file__).parent/'mc_runtime.py'),'release','--output',str(args.release),'--workers',str(args.workers)]
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
