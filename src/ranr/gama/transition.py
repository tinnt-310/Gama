"""Audited adoption of compiled headless calibration after a validation-only fix.

Original execution sources, manifests, logs and calibration remain immutable.
The new certificate authorizes calibration import only. Native results explicitly
retain their execution source and record the new reviewer source separately.
"""
from pathlib import Path
import argparse
import ast
import json
import shutil
from ..paths import ROOT, digest, write_json
from .headless import provenance, checked_result, OUTPUT
from .evidence import reference, read_reference, verify_reference, validate_compatibility_sources

ALLOWED = {'src/ranr/gama/evidence.py', 'src/ranr/gama/release.py', 'src/ranr/gama/transition.py'}


def transition_changes(old,new):
    changed = {}
    for category in old.keys() | new.keys():
        a,b = old.get(category),new.get(category)
        if a==b:continue
        if category!='orchestrator' or not isinstance(a,dict) or not isinstance(b,dict):
            raise ValueError('Simulation/runtime/input changed: '+category)
        for name in a.keys() | b.keys():
            if a.get(name)==b.get(name):continue
            if name not in ALLOWED:raise ValueError('Not a validation-only transition: '+name)
            changed[name]={'old':a.get(name),'new':b.get(name),
                'rationale':'Reviewed native-log recognition and scheduler adoption only; compiled simulation, launcher, calibration sampler, ledger contracts and all inputs unchanged.'}
    if not changed:raise ValueError('No source transition to review')
    return changed


def check_function_scope(before):
    """Limit this repair to the expected validation and scheduler entry points."""
    permitted={'evidence.py':{'validate_collection','verify_native'},'release.py':{'initialize','execute','main'}}
    for name,allowed in permitted.items():
        relative=Path('src/ranr/gama')/name
        def nodes(path):
            tree=ast.parse(path.read_text())
            return {node.name:ast.dump(node,include_attributes=False) for node in tree.body if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef))}
        a,b=nodes(before/relative),nodes(ROOT/relative)
        if any(a.get(key)!=b.get(key) and key not in allowed for key in a.keys() | b.keys()):
            raise ValueError('Repair exceeded reviewed function scope: '+name)


def verify_transition(path):
    proof=json.loads(Path(path).read_text())
    current=provenance()
    if proof.get('kind')!='headless_calibration_transition' or proof.get('source')!=current or proof.get('passed') is not True:
        raise ValueError('Current headless transition certificate required')
    changes=transition_changes(proof['execution_source'],current)
    if proof.get('reviewed_changes')!=changes:raise ValueError('Reviewed source delta changed')
    validate_compatibility_sources(proof['execution_source'],current,changes)
    for item in proof['dependencies']:verify_reference(item)
    native=read_reference(proof['native_validation'])
    if native.get('passed') is not True or native['source']!=proof['execution_source']:
        raise ValueError('Original native validation invalid')
    for item in native['dependencies']:
        fixture=read_reference(item)
        if fixture.get('source')!=proof['execution_source']:raise ValueError('Mixed native execution sources')
    comparison=read_reference(proof['headless_reproduction'])
    if comparison.get('source')!=proof['execution_source'] or comparison.get('passed') is not True or len(comparison.get('comparisons',[]))!=2 or not all(x.get('passed') is True for x in comparison['comparisons']):
        raise ValueError('Three reproducible headless executions required')
    if len(comparison.get('dependencies',[]))!=3 or len({x['path'] for x in comparison['dependencies']})!=3:
        raise ValueError('Three distinct headless replay manifests required')
    seeds=set()
    for folder,sha in proof['runs'].items():
        folder=Path(folder)
        if digest(folder/'manifest.json')!=sha:raise ValueError('Adopted manifest changed')
        manifest=json.loads((folder/'manifest.json').read_text())
        if manifest.get('origin')=='GAMA_GUI' or manifest.get('backend')!='GAMA' or 'parameters' not in manifest:
            raise ValueError('Only registered compiled headless runs can be adopted')
        checked_result(folder,{'source':proof['execution_source']})
        seeds.add(manifest['config']['seed'])
    if seeds!={800001,800002,800003} or len(proof['runs'])!=3:
        raise ValueError('Adoption must cover the complete calibration seed set')
    for item in comparison['dependencies']:
        manifest=read_reference(item)
        checked_result(Path(item['path']).parent,{'source':proof['execution_source']})
        if manifest['config']['seed']!=800001:raise ValueError('Headless repeat seed changed')
    return proof


def certify(previous,before,target):
    previous,before,target=Path(previous).resolve(),Path(before).resolve(),Path(target).resolve()
    old_registration=json.loads((previous/'registration.json').read_text())
    state=json.loads((previous/'state.json').read_text())
    if 'training' in state['stages'] or state.get('current_stage')!='accuracy':
        raise ValueError('This repair can only adopt a pre-training accuracy failure')
    for stage in ('native_validation','replay_0','replay_1','replay_2','calibration_800002','calibration_800003'):
        entry=state['stages'].get(stage,{})
        if entry.get('status')!='complete':raise ValueError('Incomplete predecessor stage: '+stage)
        for item in entry['artifacts']:verify_reference(item)
    old=old_registration['source'];new=provenance();changes=transition_changes(old,new)
    for name,sha in old['orchestrator'].items():
        if digest(before/name)!=sha:raise ValueError('Original source snapshot changed: '+name)
    check_function_scope(before)
    selection=json.loads((previous/'calibration_selection.json').read_text())
    if digest(Path(selection['calibration']))!=selection['sha256']:raise ValueError('Previous calibration changed')
    runs=[Path(p) for p in selection['selected']]
    # Recompute comparisons from sealed physical records, not from pass booleans.
    from .replay import compare_runs
    replay_paths=[previous/'replay'/str(i) for i in range(3)]
    compared=[compare_runs(replay_paths[0],p) for p in replay_paths[1:]]
    if not all(x['passed'] for x in compared):raise ValueError('Headless repeat results diverge')
    target.mkdir(parents=True,exist_ok=False)
    native=OUTPUT/'validation.json'
    original=json.loads(native.read_text())
    if original['source']!=old or original.get('passed') is not True:raise ValueError('Expected original native report')
    if not any(x['sha256']==digest(native) for x in state['stages']['native_validation']['artifacts']):
        raise ValueError('Native report differs from completed predecessor evidence')
    archived=target/'native_execution.json';shutil.copy2(native,archived)
    reproduction=target/'headless_reproduction.json'
    write_json(reproduction,{'source':old,'passed':True,'comparisons':compared,
        'dependencies':[reference(p/'manifest.json') for p in replay_paths]})
    proof={'kind':'headless_calibration_transition','passed':True,'source':new,'execution_source':old,
        'reviewed_changes':changes,'previous_release':str(previous),
        'runs':{str(p.resolve()):digest(p/'manifest.json') for p in runs},
        'native_validation':reference(archived),'headless_reproduction':reference(reproduction),
        'dependencies':[reference(archived),reference(reproduction),reference(previous/'registration.json'),
            reference(previous/'state.json'),reference(previous/'calibration_selection.json'),reference(Path(selection['calibration'])),
            *[reference(p/'manifest.json') for p in runs],
            *[reference(before/name) for name in old['orchestrator']]]}
    path=target/'compatibility.json';write_json(path,proof)
    verify_transition(path)
    # A separate review record; original execution source and raw reports retained.
    reviewed={**original,'source':new,'execution_source':old,'source_transition':reference(path)}
    reviewed_path=target/'native_review.json';write_json(reviewed_path,reviewed)
    from .evidence import verify_native, validate_collection
    verify_native(reviewed_path)
    for folder in runs:validate_collection(folder,path)
    return path


def review_native(path):
    proof=verify_transition(path)
    original=read_reference(proof['native_validation'])
    record={**original,'source':provenance(),'execution_source':proof['execution_source'],'source_transition':reference(path)}
    from .evidence import verify_native
    temporary=Path(path).parent/'native_review.json';write_json(temporary,record)
    verify_native(temporary)
    write_json(OUTPUT/'validation.json',record)
    return record


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--certificate',type=Path,required=True)
    args=parser.parse_args()
    review_native(args.certificate)
    print('NATIVE_EVIDENCE_REVIEW_PASS: unchanged compiled tests; execution source preserved')


if __name__=='__main__':main()
