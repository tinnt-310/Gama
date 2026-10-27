"""Create a new scoped certificate; never edits/relabels parent evidence."""
import json
import os
from pathlib import Path
import resource
import sys
import time

SOURCE=Path(__file__).resolve().parents[2]
ROOT=SOURCE.parent
BASE=ROOT.parent
os.environ.update(RANR_WORKSPACE=str(SOURCE),PYTHONDONTWRITEBYTECODE='1',OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1')
sys.path.insert(0,str(SOURCE/'src'))
from ranr.paths import write_json,digest
from ranr.gama.headless import provenance
from ranr.gama.evidence import reference,verify_native
from ranr.gama.recovery_transition import KIND,SCOPE,source_scope,verify_certificate

def execute():
    resource.setrlimit(resource.RLIMIT_AS,(1536*1024**2,1536*1024**2))
    os.sched_setaffinity(0,{min(os.sched_getaffinity(0))})
    current=provenance()
    tests=[]
    for name in ['test_optimizer','test_statistics','test_integration','regression']:
        path=ROOT/'engineering_tests/results'/(name+'.json');record=json.loads(path.read_text())
        if record.get('source')!=current or not record['all_unexpected_checks_pass'] or record['expected_failures'] or record['errors'] or record['failures']:
            raise ValueError('Integrated regression did not pass: '+name)
        if record.get('runner_sha256')!=digest(SOURCE/'scripts/recovery_pipeline/run_tests.py'):raise ValueError('Stale test harness identity')
        for file,sha in record['rng_files'].items():
            if digest(Path(file))!=sha:raise ValueError('RNG runtime dependency changed')
        tests.append(reference(path))
    engineering=dict(kind='integrated_finding_regressions',passed=True,source=current,
        fixed_findings=['PR01','PR02','PR03','PR04','PR05'],native_smoke_passed=False,
        paired_optimizer_scope='3 registered seeds,4 methods,2 generations; candidate and fixed-validation interruption; deterministic sealed synthetic fitness',
        dependencies=[*tests,*[reference(p) for p in sorted((SOURCE/'tests/recovery_integration').glob('*.py'))],
            reference(SOURCE/'scripts/recovery_pipeline/run_tests.py'),
            reference(ROOT/'engineering_tests/results/multi_seed_rng.json'),
            *[reference(Path(file)) for file in record['rng_files']]])
    output=ROOT/'engineering_acceptance.json'
    if output.exists() and json.loads(output.read_text())!=engineering:raise ValueError('Existing engineering evidence changed; version the build')
    write_json(output,engineering)
    parent_path=BASE/'calibration_import_20261026/certificate.json'
    parent=json.loads(parent_path.read_text())
    changes=source_scope(parent['source'],current,BASE/'calibration_source')
    native=BASE/'calibration_source/outputs/gama_ranr/validation.json'
    model=SOURCE/'tests/native_reviews/RanrPairedPhysicalReplay.gaml'
    parent_model=BASE/'calibration_source/tests/native_reviews/RanrPairedPhysicalReplay.gaml'
    paths=dict(authorization=ROOT/'authorization.json',engineering=output,parent_certificate=parent_path,
        native_validation=native,parent_verifier=Path(__file__).with_name('parent_verify.py'),
        paired_physical_model=model,parent_paired_physical_model=parent_model)
    proof=dict(kind=KIND,passed=True,source=current,parent_source=parent['source'],
        execution_source=parent['execution_source'],parent_checkout=str(BASE/'calibration_source'),
        scope=SCOPE,reviewed_changes=changes,calibration=parent['calibration'],runs=parent['runs'],
        **{key:reference(path) for key,path in paths.items()},
        dependencies=[*[reference(path) for path in paths.values()],
            *[reference(p) for p in sorted(Path(__file__).parent.glob('*.py'))]])
    build=ROOT/'compatibility_builds'/str(time.time_ns());build.mkdir(parents=True)
    candidate=build/'certificate.json';write_json(candidate,proof)
    verify_certificate(proof,BASE/'accepted_data_v5/calibration.json')
    certificate=ROOT/'certificate.json'
    if certificate.exists():raise ValueError('Refusing to overwrite an accepted recovery certificate')
    certificate.write_bytes(candidate.read_bytes())
    original=json.loads(native.read_text())
    review={**original,'kind':'scoped_recovery_native_review','source':current,
        'execution_source':parent['source'],'source_transition':reference(certificate),
        'original_native_validation':reference(native)}
    native_review=SOURCE/'outputs/gama_ranr/validation.json';write_json(native_review,review)
    verify_native(native_review)
    config=json.loads((BASE/'calibration_import_20261026/research_imported.json').read_text())
    config['calibration_import_certificate']=str(certificate)
    write_json(ROOT/'base_config.json',config)
    write_json(ROOT/'compatibility_acceptance.json',dict(kind='scoped_optimizer_recovery_calibration_acceptance',
        passed=True,source=current,certificate=reference(certificate),native_review=reference(native_review),
        historical_bytes_modified=False,global_source_equivalence=False,native_optimizer_accepted=False,
        dependencies=[reference(certificate),reference(native_review),reference(output),reference(ROOT/'base_config.json')]))
    print(json.dumps(dict(scoped_compatibility='PASS',native_physics='SCOPED_INHERITANCE',
        optimizer_native='PENDING',raw_calibration_unchanged=True,certificate=str(certificate))))

if __name__=='__main__':execute()
