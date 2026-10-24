"""Durable elapsed training journal; interrupted work never resets the allowance."""
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import signal
import threading
import time

INTERVAL = 5.0


def durable_replace(path, data):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.durable.tmp')
    with temporary.open('wb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def owner_token(pid=None):
    pid = os.getpid() if pid is None else pid
    fields = (Path('/proc') / str(pid) / 'stat').read_text().rsplit(')', 1)[1].split()
    return dict(pid=pid, start_ticks=fields[19],
                boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip())


def still_alive(owner):
    try:
        fields = (Path('/proc') / str(owner['pid']) / 'stat').read_text().rsplit(')', 1)[1].split()
        return fields[0] not in ('Z', 'X') and owner_token(owner['pid']) == owner
    except (OSError, KeyError):
        return False


class TrainingClock:
    def __init__(self, folder, identity, base_seconds, limit):
        self.path = Path(folder) / 'training_time.json'
        self.identity = json.loads(json.dumps(identity, allow_nan=False))
        self.owner = owner_token()
        self.initial = base_seconds
        self.recovery_reserve = 0.0
        if self.path.exists():
            previous = json.loads(self.path.read_text())
            if previous['identity'] != self.identity:
                raise ValueError('Training time registration changed')
            if previous['active']:
                if still_alive(previous['owner']):
                    raise ValueError('Training time journal has a live owner')
                # Death time is unknown after SIGKILL/power loss. Charge an upper
                # bound through recovery, recording uncertainty rather than refunding
                # real work. Across a reboot exhaust the remaining allowance.
                self.recovery_reserve = (max(0.0, time.monotonic() - previous['monotonic_at'])
                    if previous['owner']['boot_id'] == self.owner['boot_id'] else limit)
            self.initial = max(self.initial, previous['consumed_seconds'] + self.recovery_reserve)
        if not math.isfinite(self.initial) or self.initial < 0:
            raise ValueError('Invalid consumed training time')
        self.started = time.monotonic()

    def consumed(self):
        return self.initial + max(0.0, time.monotonic() - self.started)

    def pulse(self, active=True):
        value = dict(schema=1, identity=self.identity, owner=self.owner, active=active,
                     consumed_seconds=self.consumed(), monotonic_at=time.monotonic(),
                     updated_at=time.time(), recovery_reserve_seconds=self.recovery_reserve,
                     recovery_policy='unclean death: conservative upper bound through recovery; reboot: exhaust allowance')
        durable_replace(self.path, (json.dumps(value, allow_nan=False, indent=2) + '\n').encode())


@contextmanager
def elapsed_guard(clock):
    from .monitoring import TRAINING_CANCEL
    TRAINING_CANCEL.clear()
    stopped = threading.Event()
    previous = None
    if threading.current_thread() is threading.main_thread():
        previous = signal.getsignal(signal.SIGTERM)
        signal.signal(signal.SIGTERM, lambda *_: TRAINING_CANCEL.set())
    clock.pulse()
    def heartbeat():
        while not stopped.wait(INTERVAL):
            try:
                clock.pulse()
            except OSError:
                # Keep the last active journal, which forces conservative recovery.
                TRAINING_CANCEL.set()
                return
    worker = threading.Thread(target=heartbeat, daemon=True)
    worker.start()
    try:
        yield clock
    finally:
        stopped.set()
        worker.join()
        try:
            clock.pulse(active=False)
        finally:
            if previous is not None:
                signal.signal(signal.SIGTERM, previous)
            TRAINING_CANCEL.clear()
