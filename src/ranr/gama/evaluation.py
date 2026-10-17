"""Locked held-out evaluation, separate from calibration and model selection."""
from dataclasses import asdict, replace
from pathlib import Path
import json
from ..paths import write_json, digest
from .headless import METHODS, CASES, provenance, load_model
from .pipeline import jobs, report
from .contracts import validate_fitness, validate_paired_results

EVALUATION_SEEDS = tuple(range(31001,31031))


def check_evaluation_grid(rows):
    expected = {(case,seed,method) for case in CASES for seed in EVALUATION_SEEDS for method in METHODS}
    keys = [(r['case'],r['seed'],r['method']) for r in rows]
    if len(keys)!=len(set(keys)) or set(keys)!=expected:
        raise ValueError('Expected exactly 720 unique held-out case/seed/method runs')
    by_key = dict(zip(keys,rows))
    for row in rows:validate_fitness(row)
    for case in CASES:
        for seed in EVALUATION_SEEDS:
            validate_paired_results([[by_key[case,seed,method]] for method in METHODS])
    return True


def evaluate_models(config, models, folder, workers=1):
    if config.development or config.calibrating:
        raise ValueError('Primary evaluation requires locked calibrated research configuration')
    source = provenance()
    training = json.loads((models/'registration.json').read_text())
    if training.get('status')!='complete' or training.get('profile')!='research' or training.get('source')!=source:
        raise ValueError('Complete matching GAMA research training required')
    parameters = {method:load_model(models/method/'parameters.json',method,config) for method in METHODS}
    config = replace(config,warmup_minutes=360,measure_minutes=3600,trace=True)
    identity = {'profile':'research','source':source,'models':str(models.resolve()),
        'models_sha256':{method:digest(models/method/'parameters.json') for method in METHODS},
        'training_registration_sha256':digest(models/'registration.json'),
        'config':asdict(config),'seeds':list(EVALUATION_SEEDS),'cases':list(CASES),
        'calibration_sha256':digest(Path(config.calibration))}
    path = folder/'registration.json'
    if path.exists():
        previous = json.loads(path.read_text())
        if any(previous.get(k)!=v for k,v in identity.items()):
            raise ValueError('Evaluation models/configuration/source changed')
    write_json(path,{**identity,'status':'running'})
    try:
        rows = jobs(config,parameters,folder,list(EVALUATION_SEEDS),workers)
        check_evaluation_grid(rows)
        if provenance()!=source or any(digest(models/method/'parameters.json')!=sha for method,sha in identity['models_sha256'].items()):
            raise ValueError('Model/source changed during held-out evaluation')
        write_json(folder/'results.json',rows)
        report(rows,folder/'report','research')
        write_json(path,{**identity,'status':'complete','rollouts':720,
            'results_sha256':digest(folder/'results.json')})
        return rows
    except BaseException as error:
        write_json(path,{**identity,'status':'interrupted' if isinstance(error,KeyboardInterrupt) else 'failed','error':str(error)})
        raise
