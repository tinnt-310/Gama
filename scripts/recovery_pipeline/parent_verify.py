"""Read-only parent verification in the genuine source35b Python checkout."""
import hashlib
import json
import os
from pathlib import Path
import sys

BASE=Path(__file__).resolve().parents[4]
SOURCE=BASE/'calibration_source'
sys.dont_write_bytecode=True
os.environ['RANR_WORKSPACE']=str(SOURCE)
sys.path.insert(0,str(SOURCE/'src'))
from ranr.gama.execution import assert_checkout_modules
from ranr.gama.headless import provenance
from ranr.gama.calibration_import import verify_calibration_import
from ranr.gama.evidence import verify_native
assert_checkout_modules()
path=BASE/'calibration_import_20261026/certificate.json'
verify_calibration_import(path,BASE/'accepted_data_v5/calibration.json')
verify_native(SOURCE/'outputs/gama_ranr/validation.json')
print(json.dumps(dict(passed=True,kind='read_only_parent_verification',source=provenance(),
    certificate_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),native_jobs_started=False)))
