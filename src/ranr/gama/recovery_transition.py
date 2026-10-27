"""Typed PR01–PR05 adoption: unchanged physical execution, new reviewed optimizer.

Historical artifacts are immutable. This authorizes a precise orchestration
repair, never old optimizer checkpoints/models/smoke or global source equivalence.
"""
import ast
import json
from pathlib import Path
import subprocess
import sys
import threading
from ranr.paths import ROOT, digest

KIND='optimizer_recovery_calibration_import'
SCOPE=dict(calibration_values_unchanged=True,physical_execution_unchanged=True,
    global_source_equivalence=False,optimizer_checkpoint_transfer=False,
    optimizer_model_transfer=False,native_smoke_transfer=False,
    pretraining_native_results_review_only=True,requires_new_native_optimizer_smoke=True)
ALLOWED={'training.py','predictive_validation.py','calibration_import.py',
         'evidence.py','headless.py','recovery_transition.py'}
REVIEWED_TRAINING='79f2bff5aceb361d365f44685499ed770c7f3c0fe4e49ec26a7782db98f39550'
REVIEWED_SCORER='ebf253ac7f403238e8bd5b3b4fb485cf134fea4abf458554a123e468e6d297db'
_PARENT_CACHE=set()
_LOCK=threading.Lock()

def require(value,reason):
    if not value:raise ValueError(reason)

def checked_ref(item):
    path=Path(item['path'])
    require(path.is_file() and digest(path)==item['sha256'],'Recovery evidence changed: '+str(path))
    return path

def read_ref(item):return json.loads(checked_ref(item).read_text())

def _strip_dispatch(tree,name,index,tag):
    fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
    node=fn.body[index]
    require(isinstance(node,ast.If) and tag in ast.unparse(node.test),'Missing typed dispatch: '+name)
    del fn.body[index]

def source_scope(parent,current,parent_root):
    """Every physical/runtime/input bit stays exact; Python edits are restricted."""
    require(set(parent)==set(current),'Recovery source categories changed')
    for category in parent:
        if category!='orchestrator':
            require(parent[category]==current[category],'Recovery cannot change '+category)
    a,b=parent['orchestrator'],current['orchestrator']
    changed={p for p in set(a)|set(b) if a.get(p)!=b.get(p)}
    allowed={'src/ranr/gama/'+p for p in ALLOWED}
    require(changed==allowed,'Unreviewed recovery source change: '+str(changed^allowed))
    for path,sha in a.items():require(digest(parent_root/path)==sha,'Parent source changed: '+path)
    require(digest(ROOT/'src/ranr/gama/training.py')==REVIEWED_TRAINING,'Optimizer repair exceeds reviewed PR01/PR02 patch')
    require(digest(ROOT/'src/ranr/gama/predictive_validation.py')==REVIEWED_SCORER,'Scorer exceeds reviewed PR03–PR05 patch')
    # Apart from typed delegation and final launch blocking, preserve the entire
    # original module AST, not just a subset of scientific function names.
    for filename in ['headless.py','evidence.py','calibration_import.py']:
        original=ast.parse((parent_root/'src/ranr/gama'/filename).read_text())
        reviewed=ast.parse((ROOT/'src/ranr/gama'/filename).read_text())
        if filename=='headless.py':
            _strip_dispatch(reviewed,'checked_result',1,'scoped_native_result_review')
        elif filename=='calibration_import.py':
            _strip_dispatch(reviewed,'verify_record',0,KIND)
        else:
            _strip_dispatch(reviewed,'verify_native',1,'scoped_recovery_native_review')
            fn=next(n for n in reviewed.body if isinstance(n,ast.FunctionDef) and n.name=='verify_training_acceptance')
            require('verify_blocker_acceptance' in ast.unparse(fn.body[-2]),'Mandatory recovery launch guard missing')
            del fn.body[-3:-1]
            class RestoreCollectionDispatch(ast.NodeTransformer):
                def visit_Compare(self,node):
                    if KIND in ast.unparse(node) and 'physics_calibration_import' in ast.unparse(node):
                        return ast.parse("proof.get('kind') == 'physics_calibration_import'",mode='eval').body
                    return self.generic_visit(node)
            reviewed=RestoreCollectionDispatch().visit(reviewed)
        require(ast.dump(original,include_attributes=False)==ast.dump(reviewed,include_attributes=False),
                'Recovery exceeded typed delegation scope: '+filename)
    return sorted(changed)

def verify_certificate(proof,calibration_path=None):
    from .headless import provenance
    current=provenance()
    require(proof.get('kind')==KIND and proof.get('passed') is True and proof.get('source')==current,
            'Current-source optimizer recovery certificate required')
    require(proof.get('scope')==SCOPE,'Recovery certificate scope changed')
    parent_root=ROOT.parent.parent/'calibration_source'
    require(Path(proof['parent_checkout']).resolve()==parent_root.resolve(),'Unregistered parent checkout')
    for item in proof['dependencies']:checked_ref(item)
    require(digest(checked_ref(proof['paired_physical_model']))==digest(checked_ref(proof['parent_paired_physical_model'])),
            'Paired physical replay model changed outside recovery scope')
    parent=read_ref(proof['parent_certificate'])
    require(parent.get('kind')=='physics_calibration_import' and parent.get('passed') is True,
            'Accepted parent physics calibration import required')
    require(parent['source']==proof['parent_source'],'Parent source identity changed')
    changes=source_scope(proof['parent_source'],current,parent_root)
    require(changes==proof['reviewed_changes'],'Recovery change inventory differs')
    require(proof['calibration']==parent['calibration'] and proof['runs']==parent['runs']
            and proof['execution_source']==parent['execution_source'],'Historical calibration provenance changed')
    calibration=checked_ref(proof['calibration'])
    if calibration_path is not None:require(Path(calibration_path).resolve()==calibration.resolve(),'Wrong calibration path')
    engineering=read_ref(proof['engineering'])
    require(engineering.get('kind')=='integrated_finding_regressions' and engineering.get('passed') is True
            and engineering['source']==current and engineering['fixed_findings']==['PR01','PR02','PR03','PR04','PR05'],
            'Integrated current-source finding regressions required')
    for item in engineering['dependencies']:checked_ref(item)
    authority=read_ref(proof['authorization'])
    require(authority.get('automatic_conditional_official_training') is True
            and authority.get('protocol_changes_authorized') is False,'Current integration authorization missing')
    # Run the original verifier in its real original checkout. Never monkeypatch
    # provenance or silently remove its optimizer-AST compatibility check.
    for item in parent['dependencies']:checked_ref(item)
    verifier=checked_ref(proof['parent_verifier'])
    key=(digest(checked_ref(proof['parent_certificate'])),digest(verifier),json.dumps(current,sort_keys=True))
    with _LOCK:
        if key not in _PARENT_CACHE:
            result=subprocess.run([sys.executable,'-B',str(verifier)],capture_output=True,text=True,timeout=120,check=True)
            receipt=json.loads(result.stdout.splitlines()[-1])
            require(receipt.get('passed') is True and receipt['source']==proof['parent_source']
                    and receipt['certificate_sha256']==proof['parent_certificate']['sha256'],
                    'Actual parent verifier identity did not match')
            _PARENT_CACHE.add(key)
    return proof

def verify_native_review(record):
    proof=verify_certificate(read_ref(record['source_transition']))
    original=read_ref(record['original_native_validation'])
    require(record['original_native_validation']==proof['native_validation'] and
            original.get('source')==proof['parent_source'] and record['execution_source']==proof['parent_source'],
            'Native inheritance execution identity changed')
    expected={**original,'kind':'scoped_recovery_native_review','source':proof['source'],
        'execution_source':proof['parent_source'],'source_transition':record['source_transition'],
        'original_native_validation':record['original_native_validation']}
    require(record==expected,'Native inheritance changed observed results/flags')
    return record

def projected_config(config):
    return {k:v for k,v in config.items() if k!='calibration_import_certificate'}

def checked_adopted_result(folder,expected,record):
    """Explicit review manifest; the original execution manifest is immutable."""
    from .contracts import validate_fitness
    proof=verify_certificate(read_ref(record['source_transition']))
    require(record.get('status')=='complete' and record.get('adoption_scope')=='pretraining_simulation_only',
            'Not an accepted pretraining native result review')
    require(all(record.get(k)==v for k,v in expected.items()),'Adopted result inputs changed')
    require(record['source']==proof['source'] and record['execution_source']==proof['parent_source'],
            'Wrong adopted result execution/reviewer source')
    original_path=checked_ref(record['original_manifest']);original=json.loads(original_path.read_text())
    require(original.get('status')=='complete' and original.get('source')==proof['parent_source'],
            'Parent native result incomplete or wrong source')
    parent_runs=ROOT.parent.parent/'heap8_revalidation_20261027'
    try:relative=original_path.resolve().relative_to(parent_runs.resolve())
    except ValueError:raise ValueError('Adoption is outside registered predecessor results')
    require(relative.parts[0] in ('benchmark','predictive','development','design')
        and (relative.parts[0]!='benchmark' or relative.parts[1] in ('physical_reference','physical_steps')),
        'Optimizer/smoke/performance result transfer forbidden')
    require(original.get('backend')=='GAMA' and not original.get('synthetic_engineering_fixture'),
            'Actual sealed native predecessor execution required')
    require(Path(record['config']['calibration_import_certificate']).resolve()==checked_ref(record['source_transition']).resolve()
        and record['calibration_import_sha256']==record['source_transition']['sha256'],
        'Adopted configuration must use this exact recovery certificate')
    require(projected_config(original['config'])==projected_config(record['config'])
            and original['parameters']==record['parameters'],'Physical inputs or candidate parameters changed')
    require(record['calibration_sha256']==original['calibration_sha256']==proof['calibration']['sha256'],
            'Adoption changed calibration values')
    require(record['artifact_hashes']==original['artifact_hashes'],'Adoption changed sealed native artifacts')
    original_folder=original_path.parent
    for name,sha in original['artifact_hashes'].items():
        require(digest(original_folder/name)==sha and digest(Path(folder)/name)==sha,'Adopted native artifact changed: '+name)
    metrics=json.loads((original_folder/'metrics.json').read_text());validate_fitness(metrics)
    return metrics

def verify_blocker_acceptance():
    """Mandatory final guard even if a caller supplies a thirteen-gate bundle."""
    from .headless import provenance,OUTPUT
    path=OUTPUT/'blocker_acceptance.json'
    require(path.is_file(),'PR01–PR05 acceptance missing; official training BLOCKED')
    proof=json.loads(path.read_text())
    require(proof.get('kind')=='integrated_training_blocker_acceptance' and proof.get('passed') is True
            and proof.get('source')==provenance(),'Stale/wrong-source blocker acceptance')
    require(proof.get('resolved_findings')==['PR01','PR02','PR03','PR04','PR05'],'Unresolved registered finding')
    for item in proof['dependencies']:checked_ref(item)
    verify_certificate(read_ref(proof['compatibility']))
    rng=read_ref(proof['native_rng'])
    require(rng.get('kind')=='native_fitness_continuous_resume_comparison' and rng.get('passed') is True
            and rng.get('source')==provenance() and rng.get('native_fitness_only') is True
            and rng.get('methods')==['RANR-AW','No-P2P','No-Prediction','Fixed-Weights'],
            'Real native-fitness continuous/resumed RNG comparison missing')
    for item in rng['dependencies']:checked_ref(item)
    return proof
