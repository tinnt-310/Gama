"""Registered development comparisons and evidence-backed design freeze."""
from dataclasses import asdict, replace
from pathlib import Path
import json
import time
from ..paths import write_json, digest
from .headless import RunConfig, METHODS, CASES, OUTPUT, provenance, checked_result, parameter_record
from .pipeline import jobs
from .contracts import OBJECTIVE_VERSION, OBJECTIVE_CONFIG_HASH, validate_paired_results
from .evidence import reference, read_reference, read_evidence

SEEDS = (24001, 24002, 24003)
DEFAULT_DESIGN = {"temperature": .2, "p2p_interval": 5., "stabilization": "off"}


def variants(config):
    base = replace(config, development=True, calibrating=False, warmup_minutes=360,
                   measure_minutes=3600, deadline_minutes=360, trace=True)
    result = {"control": base}
    for value in (.1,.2,.3,.5): result[f"temperature_{value}"] = replace(base, temperature=value)
    for value in (1.,2.,5.): result[f"heartbeat_{value}"] = replace(base, p2p_interval=value)
    for value in ("smoothing","smoothing_hysteresis"): result[value] = replace(base, stabilization=value)
    for value in ("high","moderate","low","contextual","misspecified"): result[f"behavior_{value}"] = replace(base, behavior_case=value)
    return result


def unique_variants(settings):
    unique, aliases = {}, {}
    for name, setting in settings.items():
        canonical = next((key for key,value in unique.items() if value == setting), name)
        aliases[name] = canonical
        if canonical == name: unique[name] = setting
    return unique, aliases


def checked_grid(target, setting, source):
    data = json.loads((target / "results.json").read_text())
    expected = {(case,seed,method) for case in CASES for seed in SEEDS for method in METHODS}
    keys = [(r["case"],r["seed"],r["method"]) for r in data]
    if len(keys) != len(set(keys)) or set(keys) != expected:
        raise ValueError("Incomplete/duplicate six-scenario, four-method paired design")
    result = []
    for case,seed,method in sorted(expected):
        folder = target / "runs" / case / str(seed) / method
        config = replace(setting,case=case,seed=seed,method=method)
        row = checked_result(folder,{"source":source,"config":asdict(config),
            "parameters":parameter_record(method,[0.]*(4 if method=="Fixed-Weights" else 20)),
            "calibration_sha256":digest(Path(config.calibration))})
        exported = data[keys.index((case,seed,method))]
        if any(exported.get(k) != row.get(k) for k in ("fitness_vector","exogenous_hash","planned_ev_days")):
            raise ValueError("Design export differs from sealed physical results")
        result.append({**row,"case":case,"seed":seed,"method":method})
    for case in CASES:
        for seed in SEEDS:
            selected = [[r] for r in result if r["case"]==case and r["seed"]==seed]
            validate_paired_results(selected)
    return result


def checked_design(folder):
    registration = json.loads((folder/"registration.json").read_text())
    if registration.get("status") != "complete" or registration.get("source") != provenance():
        raise ValueError("Current complete design registration required")
    base = RunConfig(**registration["base_config"])
    if registration["calibration_sha256"] != digest(Path(base.calibration)):
        raise ValueError("Design calibration changed")
    settings = variants(base)
    unique, aliases = unique_variants(settings)
    if registration["variants"] != {k:asdict(v) for k,v in settings.items()} or registration["aliases"] != aliases:
        raise ValueError("Registered design grid changed")
    rows = {name:checked_grid(folder/name,setting,registration["source"]) for name,setting in unique.items()}
    return registration, rows, aliases


def validate_design(config, folder, workers=1, collect_only=False):
    if not config.calibration: raise ValueError("Design validation needs train-only GAMA calibration")
    if any(getattr(config,k)!=v for k,v in DEFAULT_DESIGN.items()):
        raise ValueError("Registered primary design changed")
    source = provenance()
    settings = variants(config)
    unique, aliases = unique_variants(settings)
    registration = {"profile":"development_design","source":source,"seeds":list(SEEDS),
        "calibration_sha256":digest(Path(config.calibration)),"base_config":asdict(config),
        "variants":{k:asdict(v) for k,v in settings.items()},"aliases":aliases}
    path = folder/"registration.json"
    previous = json.loads(path.read_text()) if path.exists() else {}
    if previous and any(previous.get(k)!=v for k,v in registration.items()):
        raise ValueError("Design registration changed")
    active = float(previous.get("active_seconds",0))
    started = time.monotonic()
    write_json(path,{**registration,"status":"running","active_seconds":active})
    try:
        rows = {}
        parameters = {m:[0.]*(4 if m=="Fixed-Weights" else 20) for m in METHODS}
        for name,setting in unique.items():
            target = folder/name
            if not collect_only:
                write_json(target/"results.json",jobs(setting,parameters,target,list(SEEDS),workers))
            rows[name] = checked_grid(target,setting,source)
        if provenance()!=source: raise ValueError("Source changed during design validation")
        baseline = {(r["case"],r["seed"],r["method"]):r for r in rows["control"]}
        contrasts = []
        for name,canonical in aliases.items():
            for row in rows[canonical]:
                ref = baseline[row["case"],row["seed"],row["method"]]
                contrasts.append({"variant":name,"canonical":canonical,"case":row["case"],"seed":row["seed"],"method":row["method"],
                    "fitness_vector_difference":[a-b for a,b in zip(row["fitness_vector"],ref["fitness_vector"])],
                    "lexicographic_relation":(-1 if tuple(row["fitness_vector"])<tuple(ref["fitness_vector"]) else int(tuple(row["fitness_vector"])>tuple(ref["fitness_vector"]))),
                    **{k:row[k]-ref[k] for k in ("operational_objective","unserved_kwh","peak_queue","wall_seconds")}})
        write_json(folder/"contrasts.json",contrasts)
        elapsed = active+time.monotonic()-started
        result = {"complete":True,"source":source,"objective_version":OBJECTIVE_VERSION,
            "objective_config_hash":OBJECTIVE_CONFIG_HASH,"design_wall_seconds":elapsed,
            "rollout_wall_seconds":sum(r["wall_seconds"] for data in rows.values() for r in data),
            "cpu_seconds":sum(r.get("cpu_seconds",0) for data in rows.values() for r in data),
            "unique_variants":len(unique),"rollouts":sum(map(len,rows.values())),
            "design_validation_passed":False,"selection_required":True,"selected_config":DEFAULT_DESIGN,
            "selection_rule":"preregistered defaults; variants are sensitivity evidence"}
        write_json(path,{**registration,"status":"complete","active_seconds":elapsed})
        write_json(folder/"review.json",result)
        return result
    except BaseException:
        write_json(path,{**registration,"status":"interrupted","active_seconds":active+time.monotonic()-started})
        raise


def freeze_design(folder, decision):
    report = json.loads((folder/"review.json").read_text())
    selected = json.loads(decision.read_text())
    if not report.get("complete") or report.get("source")!=provenance():
        raise ValueError("Incomplete development review")
    if selected.get("selected_config")!=DEFAULT_DESIGN or selected.get("objective_config_hash")!=OBJECTIVE_CONFIG_HASH:
        raise ValueError("Registered design/objective changed")
    if selected.get("review_sha256")!=digest(folder/"review.json"):
        raise ValueError("Decision is not linked to current development evidence")
    registration, rows, aliases = checked_design(folder)
    native_path = OUTPUT/"validation.json"
    from .evidence import verify_native
    native = verify_native(native_path)
    for name in ("compile_checked","unified_fleet_checked","distributed_information_checked","objective_checked",
                 "energy_safety_checked","soc_activity_demand_checked","paired_exogenous_traits_checked"):
        if native.get(name) is not True: raise ValueError("Native gate missing: "+name)
    development_path = OUTPUT/"development_validation.json"
    from .development import verify_development
    verify_development(development_path,RunConfig(**registration["base_config"]))
    calibration = Path(registration["base_config"]["calibration"])
    cal = json.loads(calibration.read_text())
    from .headless import validate_calibration_binding
    validate_calibration_binding(RunConfig(**registration['base_config']))
    if cal.get("split")!="train" or cal.get("objective_config_hash")!=OBJECTIVE_CONFIG_HASH:
        raise ValueError("Current train calibration required")
    from .evidence import validate_collection
    imported = registration['base_config'].get('calibration_import_certificate')
    compatibility = Path(imported) if imported else (Path(cal["compatibility"]["path"]) if cal.get("compatibility") else None)
    if compatibility and not imported and digest(compatibility)!=cal["compatibility"]["sha256"]: raise ValueError("Compatibility changed")
    if len(cal["runs"])!=3: raise ValueError("Three calibration seeds required")
    seeds = set()
    for path,sha in cal["runs"].items():
        run_folder = Path(path)
        if digest(run_folder/"manifest.json")!=sha: raise ValueError("Calibration input changed")
        validate_collection(run_folder,compatibility)
        seeds.add(json.loads((run_folder/"manifest.json").read_text())["config"]["seed"])
    if seeds!={800001,800002,800003}: raise ValueError("Calibration seed protocol changed")
    dependencies = [reference(p) for p in (folder/"review.json",folder/"registration.json",decision,native_path,development_path,calibration)]
    if imported:
        dependencies.append(reference(Path(imported)))
    for name in rows:
        dependencies.append(reference(folder/name/"results.json"))
        for case in CASES:
            for seed in SEEDS:
                for method in METHODS:
                    dependencies.append(reference(folder/name/"runs"/case/str(seed)/method/"manifest.json"))
    record = {"source":provenance(),"objective_version":OBJECTIVE_VERSION,"objective_config_hash":OBJECTIVE_CONFIG_HASH,
        "passed":True,"selected_config":DEFAULT_DESIGN,"design_wall_seconds":report["design_wall_seconds"],
        "calibration_passed":True,"information_passed":True,"exposure_passed":True,
        "objective_sensitivity_passed":True,"design_validation_passed":True,
        "review_sha256":digest(folder/"review.json"),"design_folder":str(folder.resolve()),
        "calibration_sha256":digest(calibration),
        "calibration_import_sha256":digest(Path(imported)) if imported else None,"dependencies":dependencies}
    write_json(OUTPUT/"design_freeze.json",record)
    return record


def validate_freeze(path, config):
    record = read_evidence(path)
    from .headless import validate_calibration_binding
    validate_calibration_binding(config)
    if record.get('calibration_import_sha256') != (digest(Path(config.calibration_import_certificate)) if config.calibration_import_certificate else None):
        raise ValueError('Design freeze calibration import changed')
    if record.get("objective_config_hash")!=OBJECTIVE_CONFIG_HASH or record.get("calibration_sha256")!=digest(Path(config.calibration)):
        raise ValueError("Design freeze calibration/objective changed")
    if any(getattr(config,k)!=v for k,v in record["selected_config"].items()):
        raise ValueError("Configuration differs from frozen design")
    if not record.get("dependencies") or not record.get("design_folder"):
        raise ValueError("Design freeze has no linked evidence")
    checked_design(Path(record["design_folder"]))
    return record
