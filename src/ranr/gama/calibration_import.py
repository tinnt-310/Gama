"""Explicit, user-authorized import of unchanged empirical v5 calibration.

This is not the validation-only source migration mechanism. It authorizes only
the original calibration bytes for the registered L01/L02 repair and requires
new-source downstream gates. Historical sources and artifacts are never edited.
"""
from pathlib import Path
import csv
import ast
import json
from ranr.paths import ROOT, digest, write_json

KIND = 'physics_calibration_import'
SCOPE = dict(calibration_import_only=True, historical_bytes_unchanged=True,
    global_source_equivalence=False, downstream_gate_transfer=False,
    calibration_cases=['normal'], calibration_seeds=[800001,800002,800003],
    requires_new_native_accuracy_predictive_model_smoke=True)
PHYSICS_FILES = {'models/ChargingService.gaml','models/ranr/Math.gaml','models/ranr/Runtime.gaml'}
ORCHESTRATOR_FILES = {
    'src/ranr/gama/headless.py','src/ranr/gama/contracts.py','src/ranr/gama/evidence.py',
    'src/ranr/gama/design.py','src/ranr/gama/calibration_import.py','src/ranr/gama/execution.py',
    'src/ranr/gama/cli.py','src/ranr/gama/validation.py','src/ranr/gama/training.py',
    'src/ranr/gama/benchmarking.py',
}


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def source_changes(old, new):
    changed = {}
    for category in old.keys() | new.keys():
        a,b = old.get(category),new.get(category)
        if a == b:
            continue
        require(category in {'gaml','orchestrator'} and isinstance(a,dict) and isinstance(b,dict),
                'Calibration import cannot change runtime/GIS/scientific inputs: '+category)
        for path in a.keys() | b.keys():
            if a.get(path) == b.get(path):
                continue
            if category == 'gaml':
                require(path in PHYSICS_FILES or path == 'models/tests/RanrChronologyZeroTests.gaml',
                        'Physics repair scope exceeded: '+path)
            else:
                require(path in ORCHESTRATOR_FILES,'Orchestration repair scope exceeded: '+path)
            changed[path] = dict(category=category,old=a.get(path),new=b.get(path))
    require(PHYSICS_FILES <= changed.keys(),'Expected exact L01/L02 physical source transition')
    return changed


def native_scope(record, current):
    """Retain execution identity while checking unchanged compiled dependencies."""
    require(record.get('passed') is True,'Supporting native evidence did not pass')
    executed = record.get('source',{})
    for category in current.keys() | executed.keys():
        if category == 'orchestrator':
            continue
        require(executed.get(category) == current.get(category),
                'Supporting native dependency changed: '+category)


def verify_algorithm_scope(registration):
    """No optimizer, selection, MC threshold or physical comparison changes."""
    before=Path(registration['source_checkout'])
    def tree(relative, original=False):
        path=(before if original else ROOT)/relative
        if original:
            require(digest(path) == registration['source']['orchestrator'][relative],
                    'Reference algorithm source changed: '+relative)
        return ast.parse(path.read_text())
    relative='src/ranr/gama/training.py'
    a,b=tree(relative,True),tree(relative)
    train=next(node for node in b.body if isinstance(node,ast.FunctionDef) and node.name=='train')
    require(isinstance(train.body[0],ast.ImportFrom) and train.body[0].module=='execution'
            and isinstance(train.body[1],ast.Expr) and isinstance(train.body[1].value,ast.Call)
            and isinstance(train.body[1].value.func,ast.Name)
            and train.body[1].value.func.id=='assert_checkout_modules','Expected execution guard only')
    train.body=train.body[2:]
    require(ast.dump(a,include_attributes=False)==ast.dump(b,include_attributes=False),
            'Optimizer, RNG, checkpoint or model selection algorithm changed')
    relative='src/ranr/gama/benchmarking.py'
    def selected(root):
        keep={'_probes','probe_errors','estimator_accuracy','physical_comparison','physical_accuracy'}
        nodes=[]
        for node in root.body:
            if isinstance(node,ast.FunctionDef) and node.name in keep:
                nodes.append(node)
            elif isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and
                t.id in {'THRESHOLDS','PROBE_KEYS','FITNESS_TOLERANCES'} for t in node.targets):
                nodes.append(node)
        return ast.dump(ast.Module(body=nodes,type_ignores=[]),include_attributes=False)
    require(selected(tree(relative,True))==selected(tree(relative)),
            'MC or physical accuracy scientific protocol changed')
    for relative,names in [('src/ranr/gama/headless.py',{'parameter_record','load_model'}),
                           ('src/ranr/gama/design.py',{'variants','unique_variants','checked_grid','checked_design','validate_design'})]:
        def functions(root):
            return {n.name:ast.dump(n,include_attributes=False) for n in root.body
                    if isinstance(n,ast.FunctionDef) and n.name in names}
        old,new=functions(tree(relative,True)),functions(tree(relative))
        require(set(old)==names and old==new,
                'Registered parameter/design semantics changed: '+relative)


def verify_record(proof, calibration_path=None):
    from .headless import provenance
    from .evidence import read_reference, verify_reference, verify_native
    from .contracts import validate_objective_identity
    current = provenance()
    require(proof.get('kind') == KIND and proof.get('passed') is True
            and proof.get('source') == current,'Current-source scoped calibration certificate required')
    require(proof.get('scope') == SCOPE,'Calibration import scope/seed/protocol changed')
    for ref in proof['dependencies']:
        verify_reference(ref)
    repair=read_reference(proof['repair_reference'])
    verify_algorithm_scope(repair)
    authorization = read_reference(proof['authorization'])
    require(authorization.get('kind') == 'scientific_calibration_import_authorization'
            and authorization.get('approved') is True
            and authorization.get('raw_and_calibration_bytes_immutable') is True
            and authorization.get('historical_provenance_immutable') is True
            and authorization.get('global_source_equivalence_authorized') is False
            and authorization.get('no_Collect') is True
            and authorization.get('no_threshold_change') is True,
            'Explicit limited scientific adoption authorization required')
    calibration_file = verify_reference(proof['calibration'])
    if calibration_path is not None:
        require(Path(calibration_path).resolve() == calibration_file.resolve(),
                'Certificate does not cover this calibration path')
    calibration = json.loads(calibration_file.read_text())
    validate_objective_identity(calibration)
    require(calibration.get('backend') == 'GAMA' and calibration.get('split') == 'train',
            'Original train-only GAMA calibration required')
    require(calibration.get('source') == proof['execution_source'],
            'Historical calibration execution provenance changed')
    data = read_reference(proof['data_acceptance'])
    require(data.get('kind') == 'data_v5_acceptance' and data.get('passed') is True
            and data.get('source') == proof['execution_source']
            and data.get('input_contract_accepted') is True,
            'Accepted original v5 observations required')
    for ref in data['dependencies']:
        verify_reference(ref)
    require(data['calibration']['sha256'] == proof['calibration']['sha256'],
            'Calibration numerical values or historical bytes changed')
    # Strict F04 is integrated, not replaced by an older validator.
    require(current['orchestrator']['src/ranr/gama/contracts.py'] ==
            data['validator_source']['orchestrator']['src/ranr/gama/contracts.py'],
            'Strict F04 validator differs from accepted data review')
    expected = source_changes(proof['execution_source'],current)
    reviewed = proof.get('reviewed_changes',{})
    require(set(reviewed) == set(expected),'Every source delta requires exact review')
    for path,item in expected.items():
        require(all(reviewed[path].get(k) == v for k,v in item.items())
                and reviewed[path].get('rationale'),'Unreviewed source delta: '+path)
    require(proof['runs'] == calibration['runs'],'Imported Collect set changed')
    seeds=set()
    for folder,sha in proof['runs'].items():
        folder=Path(folder)
        require(digest(folder/'manifest.json') == sha,'Historical Collect manifest changed')
        manifest=json.loads((folder/'manifest.json').read_text())
        require(manifest['source'] == proof['execution_source'] and not manifest['config']['station_events']
                and manifest['config']['case'] == 'normal','Collect physics/calibration domain changed')
        seeds.add(manifest['config']['seed'])
    require(len(proof['runs']) == 3 and seeds == {800001,800002,800003},'Calibration seeds changed')
    native=verify_native(verify_reference(proof['native_validation']))
    require(native.get('compile_checked') is True and len(native['dependencies']) == 51,
            'Complete current-source compiled 51-fixture suite required')
    binding=read_reference(proof['binding_validation'])
    require(binding.get('kind') == 'original_calibration_native_runtime_binding'
            and binding.get('passed') is True and binding.get('source') == current
            and binding['calibration'] == proof['calibration']
            and binding.get('optimizer_created') is False and binding.get('data_collected') is False,
            'Native original-calibration Runtime binding required')
    require({r['method'] for r in binding['rows']} == {'RANR-AW','No-P2P','No-Prediction','Fixed-Weights'}
            and len(binding['rows']) == 4 and all(r['passed'] for r in binding['rows']),
            'All four native calibration binding methods required')
    verify_reference(binding['fixture'])
    for row in binding['rows']:
        for field in ('configuration','resources','console'):
            verify_reference(row[field])
        config=read_reference(row['configuration'])
        require(Path(config['calibration_file']).resolve() == calibration_file.resolve(),
                'Native Runtime loaded a different calibration')
        resources=read_reference(row['resources'])
        from .execution import verify_recorded_python
        verify_recorded_python(resources.get('python_execution',{}),current)
    edge=read_reference(proof['edge_validation'])
    require(repair['source'] == edge['source'],'Physics/algorithm repair reference mismatch')
    native_scope(edge,current)
    required={'outage_sorted','outage_unsorted','tied_restore','tied_shutdown','zero_front',
        'zero_middle','all_zero','tiny_front','tiny_last','tiny_middle','tiny_chain',
        'tiny_unpowered','tiny_partial','zero_busy','clock_guard'}
    require({r['mode'] for r in edge['results']} == required
            and all(r['passed'] for r in edge['results']),'Expanded native fix regressions required')
    edge_root=Path(proof['edge_validation']['path']).parent/'native_edges'
    for row in edge['results']:
        require(digest(edge_root/row['mode']/'console.txt') == row['console_sha256'],
                'Native edge console changed')
    domain=read_reference(proof['domain_comparison'])
    native_scope(domain,current)
    require(domain.get('kind') == 'finite_calibration_domain_native_equivalence'
            and domain.get('global_source_equivalence_certified') is False,
            'Finite native calibration comparison required')
    root=Path(proof['domain_comparison']['path']).parent
    require(domain['inputs'].get(str(calibration_file.resolve())) == proof['calibration']['sha256'],
            'Finite domain comparison used different calibration bytes')
    require({r['step_seconds'] for r in domain['results']} == {1,60},'Both registered step scopes required')
    for row in domain['results']:
        step=row['step_seconds'];a=root/f'original_{step}/observations.json';b=root/f'repair_{step}/observations.json'
        require(digest(a) == row['original_sha256'] and digest(b) == row['repair_sha256'],
                'Finite comparison outputs changed')
        left,right=json.loads(a.read_text()),json.loads(b.read_text())
        require(left == right and len(left) == 7883 and row['passed'] is True,
                'Calibration-domain physics changed; stop for data applicability review')
    mc=read_reference(proof['mc32_comparison'])
    native_scope(mc,current)
    require(mc.get('kind') == 'bounded_native_prediction_equivalence' and mc.get('samples') == 32
            and mc.get('seed') == 900001 and mc.get('calibration_sha256') == proof['calibration']['sha256'],
            'Registered bounded native MC32 evidence required')
    old_csv=Path(mc['original_csv']);new_csv=Path(proof['mc32_comparison']['path']).parent/'probes_32.csv'
    require(digest(old_csv) == mc['original_csv_sha256'] and digest(new_csv) == mc['new_csv_sha256'],
            'MC32 output changed')
    with old_csv.open() as a,new_csv.open() as b:
        left,right=list(csv.DictReader(a)),list(csv.DictReader(b))
    require(left == right and len(left) == 165,'Bounded MC32 comparison failed')
    impact=read_reference(proof['data_impact'])
    native_scope(dict(passed=True,source=impact['repair_source']),current)
    require(impact.get('raw_recollected') is False and impact.get('raw_or_calibration_modified') is False,
            'Historical data modification is not authorized')
    require(all(not r['station_events'] for r in impact['collections']),
            'Historical outage domain invalidates this import scope')
    require(all(v['nonpositive'] == 0 for v in impact['trigger_domain'].values()),
            'Affected zero-energy historical calibration requires separate review')
    return proof


def verify_calibration_import(path, calibration_path=None):
    return verify_record(json.loads(Path(path).read_text()),calibration_path)


def certify(*, authorization, calibration, data_acceptance, native_validation,
            edge_validation, domain_comparison, mc32_comparison, data_impact, binding_validation,
            repair_reference, target):
    from .headless import provenance,checked_result
    from .evidence import reference
    target=Path(target)
    require(not target.exists(),'Refusing to overwrite a calibration import certificate')
    calibration=Path(calibration)
    original=json.loads(calibration.read_text())
    # Rehash sealed original inputs once at certification. Never rerun Collect
    # or change a historical ledger/manifest during this integrity check.
    for folder in original['runs']:
        checked_result(Path(folder),{'source':original['source']})
    paths=dict(authorization=authorization,calibration=calibration,data_acceptance=data_acceptance,
        native_validation=native_validation,edge_validation=edge_validation,
        domain_comparison=domain_comparison,mc32_comparison=mc32_comparison,data_impact=data_impact,
        binding_validation=binding_validation,repair_reference=repair_reference)
    current=provenance()
    changes=source_changes(original['source'],current)
    changes={name:{**item,'rationale':
        ('L01/L02 implementation repair; finite empirical applicability only, not source equivalence'
         if item['category']=='gaml' else
         'Explicit scoped calibration/provenance integration, strict F04 and actual Python execution binding; objective/optimizer protocol unchanged')}
        for name,item in changes.items()}
    proof=dict(kind=KIND,passed=True,source=current,execution_source=original['source'],
        scope=SCOPE,reviewed_changes=changes,runs=original['runs'],
        **{name:reference(Path(p)) for name,p in paths.items()},
        dependencies=[reference(Path(p)) for p in paths.values()])
    verify_record(proof,calibration)
    write_json(target,proof)
    verify_calibration_import(target,calibration)
    return proof
