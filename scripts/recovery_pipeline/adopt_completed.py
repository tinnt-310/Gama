"""Scoped review of sealed predecessor simulation results after ownership handoff.

No original manifest is edited. Reviewed manifests explicitly carry original
execution source/path; optimizer/smoke/checkpoints/models are never adopted.
"""
from dataclasses import asdict
import json
from pathlib import Path
import shutil
from ranr.paths import ROOT as SOURCE,write_json,digest
from ranr.gama.headless import provenance,RunConfig,checked_result
from ranr.gama.evidence import reference,verify_reference
from ranr.gama.recovery_transition import verify_certificate,projected_config,require

ROOT=SOURCE.parent
BASE=ROOT.parent
PARENT=BASE/'heap8_revalidation_20261027'

def review_result(original,target,certificate):
    original=Path(original);target=Path(target)
    manifest=json.loads((original/'manifest.json').read_text())
    proof=verify_certificate(json.loads(Path(certificate).read_text()))
    require(manifest.get('status')=='complete' and manifest.get('source')==proof['parent_source'],
            'Only complete registered parent native runs may be reviewed')
    require(manifest.get('backend')=='GAMA' and manifest.get('calibration_sha256')==proof['calibration']['sha256'],
            'Original sealed GAMA/calibration identity missing')
    relative=original.relative_to(PARENT)
    require(relative.parts[0] in ('benchmark','predictive','development','design'),
            'Optimizer/checkpoint/model/smoke transfer forbidden')
    if (target/'manifest.json').exists():
        existing=json.loads((target/'manifest.json').read_text())
        require(existing.get('original_manifest')==reference(original/'manifest.json')
            and existing.get('source_transition')==reference(certificate),'Existing adoption identity differs')
        checked_result(target,dict(source=provenance()))
        return target/'manifest.json'
    if target.exists():
        import time
        archive=ROOT/'adoption_incomplete'/str(time.time_ns())/target.relative_to(ROOT)
        archive.parent.mkdir(parents=True,exist_ok=True);target.rename(archive)
    for name,sha in manifest['artifact_hashes'].items():
        require(digest(original/name)==sha,'Original sealed artifact changed')
    target.mkdir(parents=True)
    for path in original.iterdir():
        if path.is_file() and path.name!='manifest.json':(target/path.name).symlink_to(path.resolve())
    config={**manifest['config'],'calibration_import_certificate':str(Path(certificate).resolve())}
    reviewed={**manifest,'kind':'scoped_native_result_review','source':provenance(),
        'execution_source':proof['parent_source'],'original_manifest':reference(original/'manifest.json'),
        'source_transition':reference(certificate),'adoption_scope':'pretraining_simulation_only',
        'config':config,'calibration_import_sha256':digest(Path(certificate))}
    write_json(target/'manifest.json',reviewed)
    checked_result(target,dict(source=provenance(),config=config))
    return target/'manifest.json'

def execute():
    certificate=ROOT/'certificate.json';proof=verify_certificate(json.loads(certificate.read_text()))
    parent_state=json.loads((PARENT/'state.json').read_text())
    require('accuracy' in parent_state.get('completed',{}),'Predecessor accuracy has not completed')
    gate_path=PARENT/'benchmark/accuracy_gate.json';gate=json.loads(gate_path.read_text())
    require(gate.get('passed') is True and gate['source']==proof['parent_source'],
            'Original current-physics accuracy did not pass')
    for item in gate['dependencies']:verify_reference(item)
    require(gate['thresholds']=={'mean':1.,'p95':5.,'externality':5.},'Accuracy thresholds changed')
    stability=json.loads((PARENT/'benchmark/reference_stability.json').read_text())
    require(stability['passed'] and all(x['pass_fraction']>=.95 for x in stability['methods'].values()),
            'Parent native MC convergence failed')
    require(json.loads((PARENT/'benchmark/physical_steps.json').read_text())['60']['passed'],
            'Parent production physical timestep did not pass')
    target=ROOT/'benchmark';target.mkdir(parents=True,exist_ok=True)
    for path in (PARENT/'benchmark').glob('probes_*.csv'):
        destination=target/path.name
        if destination.exists():require(destination.resolve()==path.resolve(),'Existing MC review points elsewhere')
        else:destination.symlink_to(path.resolve())
    for name in ['reference_stability.json','accuracy.json','physical_steps.json']:
        destination=target/name
        if destination.exists():require(destination.resolve()==(PARENT/'benchmark'/name).resolve(),'Review output changed')
        else:destination.symlink_to(PARENT/'benchmark'/name)
    config={**gate['locked_config'],'calibration_import_certificate':str(certificate)}
    require(projected_config(config)==projected_config(gate['locked_config']),'Physical accuracy config changed')
    reviewed={**gate,'kind':'scoped_accuracy_review','source':provenance(),
        'execution_source':proof['parent_source'],'original_accuracy':reference(gate_path),
        'source_transition':reference(certificate),'locked_config':config,
        'scope':'Same native physics/predictor/runtime/inputs; optimizer/scorer changed; no old optimizer acceptance',
        'dependencies':[reference(certificate),reference(gate_path),*gate['dependencies']]}
    write_json(target/'accuracy_gate.json',reviewed)
    for name in ['accuracy_config.json','locked_config.json']:write_json(target/name,config)
    adopted=[]
    for phase in ['benchmark','predictive','development','design']:
        for manifest in sorted((PARENT/phase).rglob('manifest.json')):
            # Accuracy+predictive+development+design native outputs only. No
            # performance adoption: representative runtime timing must be fresh.
            relative=manifest.parent.relative_to(PARENT)
            if phase=='benchmark' and relative.parts[1] not in ('physical_reference','physical_steps'):continue
            record=json.loads(manifest.read_text())
            if record.get('status')!='complete':continue
            destination=ROOT/relative
            adopted.append(review_result(manifest.parent,destination,certificate))
    # Counterfactual output values and original execution receipts remain intact;
    # a new review receipt records exactly why their native engine is unchanged.
    from physical_counterfactual import MODEL
    for old in sorted((PARENT/'predictive/counterfactual').rglob('evidence.json')):
        record=json.loads(old.read_text())
        require(record.get('passed') is True and record['source']==proof['parent_source']
                and record['model_sha256']==digest(MODEL),'Invalid parent paired physical evidence')
        require(record['input_sha256']==digest(old.parent/'input.json')
                and record['output_sha256']==digest(old.parent/'output.json'),'Paired replay data changed')
        verify_reference(record['resources'])
        destination=ROOT/old.relative_to(PARENT);destination.parent.mkdir(parents=True,exist_ok=True)
        for name in ['input.json','output.json']:
            link=destination.parent/name
            if link.exists():require(link.resolve()==(old.parent/name).resolve(),'Paired review input path changed')
            else:link.symlink_to(old.parent/name)
        write_json(destination,{**record,'source':provenance(),'execution_source':proof['parent_source'],
            'kind':'scoped_paired_physical_review','original_evidence':reference(old),
            'source_transition':reference(certificate)})
    receipt=dict(kind='completed_pretraining_native_adoption',passed=True,source=provenance(),
        execution_source=proof['parent_source'],optimizer_smoke_adopted=False,original_manifests_modified=False,
        native_results=len(adopted),dependencies=[reference(certificate),reference(gate_path),
            *[reference(p) for p in adopted]])
    write_json(ROOT/'adoption.json',receipt)
    # A reboot can leave the auxiliary administrative marker behind, even
    # though canonical parent accuracy has since completed from complete CSVs.
    # Resolve only after that current-physics gate and every recorded cache hash
    # have been checked, under the successor's inherited legacy ownership locks.
    marker=BASE/'official_training/optimizer/MC_PARALLEL_PREFETCH_PENDING.json'
    if marker.exists():
        import csv,math
        for path in (PARENT/'benchmark').glob('probes_*.csv'):
            with path.open() as f:rows=list(csv.DictReader(f))
            n=int(path.stem.split('_')[-1])
            keys={(r['method'],r['station'],r['probe']) for r in rows}
            expected={(m,str(s),str(p)) for m in ('RANR-AW','No-P2P','No-Prediction') for s in range(11) for p in range(5)}
            require(len(rows)==165 and keys==expected and int(rows[-1]['queue_calls'])==275*n
                and all(math.isfinite(float(r[k])) for r in rows for k in ['mean','p95','externality']),
                'Pending helper cache not structurally complete')
        archive=ROOT/'resolved_helper_reservation.json'
        require(not archive.exists(),'Helper reservation was already reconciled')
        write_json(ROOT/'helper_reservation_resolution.json',dict(kind='completed_MC_cache_reservation_review',
            passed=True,source=provenance(),parent_accuracy=reference(gate_path),marker=reference(marker),
            scope='Canonical parent accuracy PASS; complete immutable referenced native MC cache; no helper restart'))
        marker.rename(archive)
    return receipt
