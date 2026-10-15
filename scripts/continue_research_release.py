"""Operational supervisor: finish the authorized research run without manual handoff.

This script does not implement simulation/research logic. It invokes the canonical
CLI, waits for an existing trainer lock and records honest completion/failure.
"""
from __future__ import annotations
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ranr.paths import ROOT, OUTPUTS, source_manifest, write_json, digest


def main() -> None:
    training=OUTPUTS/'training/research_release'
    evaluation=OUTPUTS/'evaluation/research_release'
    state=OUTPUTS/'research_pipeline.json'
    environment=os.environ.copy()
    environment.update(OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MPLCONFIGDIR=str(OUTPUTS/'.cache/matplotlib'))
    frozen=source_manifest()

    def update(phase: str, **details) -> None:
        write_json(state,{'phase':phase,'updated_at':datetime.now(ZoneInfo('Asia/Bangkok')).isoformat(),'source':frozen,'supervisor_sha256':digest(Path(__file__)),'training':str(training),'evaluation':str(evaluation),**details})

    def command(arguments: list[str], log: str) -> None:
        if source_manifest()!=frozen: raise RuntimeError('Source changed; pipeline cannot continue this registration')
        with (OUTPUTS/log).open('a') as handle:
            subprocess.run([sys.executable,'-m','ranr',*arguments],cwd=ROOT,env=environment,stdout=handle,stderr=subprocess.STDOUT,check=True)

    with (OUTPUTS/'.pipeline.lock').open('a') as handle:
        fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        try:
            update('waiting_for_training')
            training.mkdir(parents=True,exist_ok=True)
            while True:
                record=training/'registration.json'
                if record.exists() and json.loads(record.read_text()).get('status')=='complete':break
                with (training/'.lock').open('a') as trainer:
                    try:
                        fcntl.flock(trainer,fcntl.LOCK_EX|fcntl.LOCK_NB)
                        inactive=True
                    except BlockingIOError:
                        inactive=False
                if inactive:
                    update('resuming_training')
                    command(['train','--output',str(training),'--resume'],'research_training.log')
                else:
                    time.sleep(30)
            update('evaluation_running')
            command(['evaluate','--models',str(training),'--output',str(evaluation),'--profile','research','--workers','16','--seeds','30'],'research_evaluation.log')
            update('report_validation')
            registration=json.loads((evaluation/'registration.json').read_text())
            if registration['status']!='complete':raise RuntimeError('Evaluation not complete')
            runs=list(evaluation.glob('runs/*/*/*/manifest.json'))
            if len(runs)!=720:raise RuntimeError(f'Expected 720 completed runs; found {len(runs)}')
            for path in runs:
                record=json.loads(path.read_text())
                if record['status']!='complete' or any(digest(path.parent/name)!=sha for name,sha in record['artifact_hashes'].items()):
                    raise RuntimeError(f'Artifact integrity failed: {path}')
            update('complete',completed_runs=len(runs),report=str(evaluation/'report/REPORT_VI.md'))
            status=ROOT/'docs/RANR_STATUS_VI.md'
            with status.open('a') as handle:
                handle.write('\n## Kết thúc pipeline tự động\n\nTraining research và 720 lượt evaluation đã hoàn tất; artifact hashes đã kiểm tra. Báo cáo tại outputs/ranr/evaluation/research_release/report/REPORT_VI.md. CI và kết luận phải đọc từ dữ liệu, không mặc định Proposed thắng.\n')
        except BaseException as error:
            update('failed',error=str(error))
            raise


if __name__=='__main__':
    raise SystemExit('Historical Python supervisor retired. Use python -m ranr for the official GAMA pipeline.')
