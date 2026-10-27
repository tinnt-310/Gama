"""Persistent service entry; choose official resume without a fresh budget."""
import json
import os
from pathlib import Path
import sys

SOURCE=Path(__file__).resolve().parents[2]
ROOT=SOURCE.parent
BASE=ROOT.parent
state=json.loads((ROOT/'state.json').read_text())
if state.get('status') in ('failed','blocked','complete','budget_limited'):
    raise SystemExit('Terminal/failure state needs evidence-based reconciliation; no automatic retry')
mode='resume' if (BASE/'official_training/inputs_frozen.json').exists() else 'run'
os.execv(sys.executable,[sys.executable,'-B',str(Path(__file__).with_name('controller.py')),mode])
