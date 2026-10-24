"""Conservative elapsed-time journal around the existing CMA-ES implementation.

No optimizer, objective or checkpoint registration fields change. On recovery,
only active_seconds may increase to account for time since its last checkpoint.
An unclean loss reserves one journal interval; no consumed budget is reset.
"""
from pathlib import Path
import json
import math
import os
import pickle
import signal
import sys
import threading
import time
from contextlib import contextmanager
from ranr.paths import digest
from ranr.gama.headless import provenance

INTERVAL=5.0

def sync_directory(path):
    descriptor=os.open(path,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(descriptor)
    finally:os.close(descriptor)


def durable_replace(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix(path.suffix+'.durable.tmp')
    with temporary.open('wb') as stream:
        stream.write(data);stream.flush();os.fsync(stream.fileno())
    os.replace(temporary,path)
    sync_directory(path.parent)
    sync_directory(path.parent.parent)


def fail_elapsed_journal(error):
    print("RANR_FATAL_ELAPSED_JOURNAL: "+str(error),file=sys.stderr,flush=True)
    os.kill(os.getpid(),signal.SIGKILL)


def write_json(path,value):
    durable_replace(path,(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+'\n').encode())


def durable_checkpoint(path,value):
    durable_replace(path,pickle.dumps(value,pickle.HIGHEST_PROTOCOL))



def owner_token(pid=None):
    pid=os.getpid() if pid is None else pid
    text=(Path('/proc')/str(pid)/'stat').read_text()
    tail=text[text.rfind(')')+2:].split()
    return {'pid':pid,'start_ticks':tail[19],'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip()}


def still_alive(owner):
    try:
        text=(Path('/proc')/str(owner['pid'])/'stat').read_text()
        state=text[text.rfind(')')+2:].split()[0]
        return state not in {'Z','X'} and owner_token(owner['pid'])==owner
    except (OSError,ProcessLookupError):return False


class ElapsedJournal:
    def __init__(self,folder,identity,base_seconds,clock=time.monotonic):
        self.folder=folder;self.path=folder/'elapsed_journal.json';self.identity=identity;self.clock=clock
        self.started=None;self.initial=base_seconds;self.owner=owner_token()
        if self.path.exists():
            prior=json.loads(self.path.read_text())
            if prior['identity']!=identity:raise ValueError('Training elapsed journal registration changed')
            if prior.get('active') and still_alive(prior['owner']):raise ValueError('Training elapsed journal still has a live owner')
            consumed=prior['consumed_seconds']+(INTERVAL if prior.get('active') else 0.0)
            self.initial=max(base_seconds,consumed)
        if self.initial<0 or not math.isfinite(self.initial):raise ValueError('Invalid consumed training budget')

    def pulse(self,active=True):
        now=self.clock()
        if self.started is None:self.started=now
        self.used=self.initial+max(0.,now-self.started)
        write_json(self.path,{'identity':self.identity,'owner':self.owner,'active':active,
            'consumed_seconds':self.used,'updated_at':time.time(),'interval_seconds':INTERVAL,
            'unclean_recovery_policy':'reserve one journal interval; consumed budget only increases'})
        return self.used


def reconcile_checkpoint(folder,identity):
    path=folder/'checkpoint.pkl'
    state=pickle.loads(path.read_bytes()) if path.exists() else None
    if state is not None:
        registration=state['registration']
        if registration.get('source')!=identity['source'] or registration.get('budget_sha256')!=identity['budget_sha256']:
            raise ValueError('Checkpoint source/budget differs from elapsed journal')
    journal=ElapsedJournal(folder,identity,state.get('active_seconds',0.) if state else 0.)
    if state is None and journal.initial>0:
        raise ValueError('Consumed training time exists but optimizer checkpoint is missing; refusing a reset')
    if state is not None and journal.initial>state.get('active_seconds',0.):
        archive=folder/'elapsed_recovery'/str(time.time_ns());archive.mkdir(parents=True)
        old=path.read_bytes();durable_replace(archive/'checkpoint_before.pkl',old)
        sync_directory(folder)
        previous=state['active_seconds'];state['active_seconds']=journal.initial
        durable_checkpoint(path,state)
        write_json(archive/'recovery.json',{'source':identity['source'],'before_active_seconds':previous,
            'after_active_seconds':journal.initial,'before_checkpoint_sha256':digest(archive/'checkpoint_before.pkl'),
            'after_checkpoint_sha256':digest(path),'rule':'account elapsed time omitted by interrupted generation; preserve all optimizer state'})
    return journal


@contextmanager
def guard(folder,budget):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    specification=json.loads(Path(budget).read_text())
    if not 0<float(specification['hours'])<=72:raise ValueError('Invalid registered training hours')
    identity={'source':provenance(),'budget_sha256':digest(Path(budget)),
        'maximum_seconds':float(specification['hours'])*3600,'ledger_schema':1}
    journal=reconcile_checkpoint(folder,identity)
    journal.pulse()
    from ranr.gama import training
    original_save=training._save
    training._save=durable_checkpoint
    stopped=threading.Event()
    def heartbeat():
        while not stopped.wait(INTERVAL):
            try:journal.pulse()
            except Exception as error:
                fail_elapsed_journal(error);return
    thread=threading.Thread(target=heartbeat,daemon=True);thread.start()
    try:yield journal
    finally:
        stopped.set();thread.join(timeout=INTERVAL+1)
        if thread.is_alive():fail_elapsed_journal("Elapsed journal I/O did not finish during shutdown")
        try:journal.pulse(active=False)
        finally:training._save=original_save
