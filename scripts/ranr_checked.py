"""Unambiguous CLI for this checkout, even with an older editable venv install."""
from pathlib import Path
import os
import runpy
import sys

root=Path(__file__).resolve().parents[1]
os.environ['RANR_WORKSPACE']=str(root)
os.environ['PYTHONPATH']=str(root/'src')
sys.path.insert(0,str(root/'src'))
from ranr.gama.execution import assert_checkout_modules
assert_checkout_modules()
runpy.run_module('ranr',run_name='__main__')
