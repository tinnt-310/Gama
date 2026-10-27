"""Registered new-source R01/R03 and paired native H; no fitting or held-out."""
from pathlib import Path
from dataclasses import asdict,replace
import json
import time

from ranr.paths import write_json,digest
from ranr.gama.headless import provenance,run
from ranr.gama.evidence import reference,verify_reference
from strict_fitness_boundary import StrictNativeRunner
from ranr.gama.predictive_validation import extract,select_counterfactuals,summarize
from physical_counterfactual import prepare,execute as replay,MODEL

HERE=Path(__file__).resolve().parent
BASE=HERE.parents[3]


def execute(config,folder,status,check):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    protocol_path=BASE/'R01_R03_PREREGISTRATION.json'
    design_path=BASE/'R01_EXECUTION_DESIGN.json'
    protocol=json.loads(protocol_path.read_text())
    if (protocol['validation_seeds']!=list(range(920001,920007)) or protocol['cases']!=['normal','high','burst']
            or protocol['methods']!=['RANR-AW','No-Prediction']):
        raise ValueError('Registered predictive split/methods/scenarios changed')
    settings=[replace(config,seed=seed,case=case,method=method,trace=True,development=True,calibrating=False)
        for case in protocol['cases'] for seed in protocol['validation_seeds'] for method in protocol['methods']]
    registration=dict(source=provenance(),protocol=reference(protocol_path),execution_design=reference(design_path),
        configs=[asdict(c) for c in settings],parameter_policy='zero 20-dimensional pre-training vector; no fitting',
        calibration_sha256=digest(Path(config.calibration)),calibration_import=reference(Path(config.calibration_import_certificate)))
    registered=folder/'registration.json'
    if registered.exists() and json.loads(registered.read_text())!=registration:
        raise ValueError('New-source predictive registration changed')
    if not registered.exists():write_json(registered,registration)
    runner=StrictNativeRunner(run,folder/'runs',provenance())
    rows=[];counts=[];dependencies=[reference(registered)];paired={}
    for setting in settings:
        check();target=folder/'runs'/setting.case/str(setting.seed)/setting.method
        status('native_predictive_episode',case=setting.case,seed=setting.seed,method=setting.method,output=str(target))
        metrics=runner(setting,[0.]*20,target,resume=target.exists())
        key=(setting.case,setting.seed);exog=[metrics['exogenous_hash'],metrics['planned_ev_days']]
        if key in paired and paired[key]!=exog:
            raise ValueError('Predictive methods do not share exogenous conditions')
        paired[key]=exog
        extracted,cohort=extract(target)
        selected=select_counterfactuals(extracted,setting.seed,setting.case,setting.method)
        cohort.update(counterfactual_selected=len(selected),counterfactual_ineligible=sum(
            r['arrival_min']>r['horizon_end'] or r['horizon_end']>r['observation_end'] for r in extracted))
        counts.append(dict(seed=setting.seed,case=setting.case,method=setting.method,counts=cohort))
        physical={}
        for index in range(0,len(selected),8):
            check();batch=folder/'counterfactual'/setting.case/str(setting.seed)/setting.method/f'{index:04d}'
            batch.mkdir(parents=True,exist_ok=True)
            input_path=batch/'input.json';output_path=batch/'output.json';proof_path=batch/'evidence.json'
            status('native_paired_counterfactual',case=setting.case,seed=setting.seed,method=setting.method,batch=index//8)
            if proof_path.exists():
                proof=json.loads(proof_path.read_text())
                if (proof.get('passed') is not True or proof['source']!=provenance()
                        or proof['input_sha256']!=digest(input_path) or proof['output_sha256']!=digest(output_path)
                        or proof['model_sha256']!=digest(MODEL)):
                    raise ValueError('Paired native evidence changed')
                verify_reference(proof['resources'])
            else:
                if input_path.exists() or output_path.exists():
                    archive=batch.parent/'_incomplete'/f'{batch.name}_{time.time_ns()}'
                    archive.parent.mkdir(parents=True,exist_ok=True);batch.rename(archive);batch.mkdir()
                prepare(target,selected[index:index+8],input_path)
                proof=replay(input_path,output_path,proof_path)
            dependencies.append(reference(proof_path))
            for row in proof['rows']:physical[(row['request_id'],row['leg'])]=row['physical_H']
        for row in extracted:
            key=(row['request_id'],row['leg'])
            if key in physical:row['physical_H']=physical[key]
        rows.extend(extracted)
        summary=folder/'extracted'/setting.case/str(setting.seed)/(setting.method+'.json')
        write_json(summary,dict(rows=extracted,counts=cohort,source=provenance(),manifest=reference(target/'manifest.json')))
        review=folder/'f04_results'/setting.case/str(setting.seed)/setting.method/'review.json'
        dependencies.extend([reference(target/'manifest.json'),reference(review),reference(summary)])
        write_json(folder/'progress.json',dict(completed_episodes=len(counts),registered_episodes=36,
            last=dict(case=setting.case,seed=setting.seed,method=setting.method),updated_at=time.time()))
    result=summarize(rows,counts)
    result.update(source=provenance(),protocol=reference(protocol_path),execution_design=reference(design_path),
                  registration=reference(registered),dependencies=dependencies)
    write_json(folder/'acceptance.json',result)
    if not result['passed']:
        raise ValueError('Scientific R01/R03 gate '+result['status']+'; see '+str(folder/'acceptance.json'))
    return result
