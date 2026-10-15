"""Registered development-only design comparisons; executions require an explicit CLI command."""
from dataclasses import asdict, replace
from pathlib import Path
import json
from ..paths import write_json, digest
from .headless import RunConfig, METHODS, OUTPUT, provenance, checked_result
from .pipeline import jobs
from .contracts import rescore_components, OBJECTIVE_VERSION

SEEDS = (24001, 24002, 24003)


def variants(config):
    base = replace(config, development=True, calibrating=False, warmup_minutes=1440, measure_minutes=2880, trace=True)
    result = {"control": base}
    for temperature in (.1,.2,.3,.5): result[f"temperature_{temperature}"] = replace(base, temperature=temperature)
    for period in (1.,2.,5.): result[f"heartbeat_{period}"] = replace(base,p2p_interval=period)
    for stability in ("smoothing", "smoothing_hysteresis"): result[stability] = replace(base,stabilization=stability)
    for behavior in ("high","moderate","low","contextual","misspecified"): result[f"behavior_{behavior}"] = replace(base,behavior_case=behavior)
    return result


def validate_design(config:RunConfig, folder:Path, workers:int=1, collect_only:bool=False):
    if not config.calibration: raise ValueError("Design validation needs train-only GAMA calibration")
    source=provenance()
    settings=variants(config)
    registration={"profile":"development_design","source":source,"seeds":list(SEEDS),"calibration_sha256":digest(Path(config.calibration)),"variants":{k:asdict(v) for k,v in settings.items()}}
    p=folder/"registration.json"
    if p.exists() and any(json.loads(p.read_text()).get(k)!=v for k,v in registration.items()):
        raise ValueError("Design registration changed")
    write_json(p,{**registration,"status":"running"})
    rows={}
    for name, setting in settings.items():
        target=folder/name
        if collect_only:
            data=json.loads((target/"results.json").read_text())
            if len(data)!=72:raise ValueError("Incomplete six-scenario, four-method paired design")
            for item in data:
                checked_result(target/"runs"/item["case"]/str(item["seed"])/item["method"], {"source":source})
        else:
            parameters={m:[0.]*(4 if m=="Fixed-Weights" else 20) for m in METHODS}
            data=jobs(setting,parameters,target,list(SEEDS),workers)
            write_json(target/"results.json",data)
        rows[name]=data
    # Report all operational effects. Selected defaults are not changed automatically.
    contrasts=[]
    baseline={(r["case"],r["seed"],r["method"]):r for r in rows["control"]}
    for name,data in rows.items():
        for row in data:
            ref=baseline[row["case"],row["seed"],row["method"]]
            contrasts.append({"variant":name,"case":row["case"],"seed":row["seed"],"method":row["method"], **{k:row[k]-ref[k] for k in ("objective","mean_wait_min","unserved_kwh","peak_queue","wall_seconds")}})
    sensitivity=[]
    for factor in (.5,1.,2.):
        for row in rows["control"]:
            sensitivity.append({"factor":factor,"case":row["case"],"seed":row["seed"],"method":row["method"],"objective":rescore_components(row["objective_components"],factor,factor)})
    write_json(folder/"contrasts.json",contrasts)
    write_json(folder/"objective_sensitivity.json",sensitivity)
    # Data collection alone does not authorize algorithm selection or a design freeze.
    result={"complete":True,"source":source,"objective_version":OBJECTIVE_VERSION,"design_wall_seconds":sum(r["wall_seconds"] for data in rows.values() for r in data),"design_validation_passed":False,"selection_required":True,"default_stabilization":"off","profile":"development_design"}
    write_json(folder/"review.json",result)
    write_json(p,{**registration,"status":"complete"})
    return result


def freeze_design(folder:Path, decision:Path):
    """Freeze only reviewed, provenance-linked development evidence, never a smoke."""
    report=json.loads((folder/"review.json").read_text())
    selected=json.loads(decision.read_text())
    if not isinstance(selected.get("selected_config"),dict) or not all(k in selected["selected_config"] for k in ("temperature","p2p_interval","stabilization","failure_beta","energy_beta")):
        raise ValueError("Missing explicit selected design configuration")
    required=("calibration_passed","information_passed","exposure_passed","objective_sensitivity_passed","design_validation_passed")
    if not report.get("complete") or report["source"]!=provenance() or not all(selected.get(k) is True for k in required):
        raise ValueError("Incomplete development review")
    if selected.get("review_sha256")!=digest(folder/"review.json"):
        raise ValueError("Decision is not linked to current development evidence")
    if selected["selected_config"]["stabilization"]!="off":
        name=selected["selected_config"]["stabilization"]
        if name not in {"smoothing","smoothing_hysteresis"}:raise ValueError("Unknown stabilization selection")
        contrasts=json.loads((folder/"contrasts.json").read_text())
        relevant=[r for r in contrasts if r["variant"]==name and r["method"]=="RANR-AW"]
        if not relevant or any(sum(r[k] for r in relevant)>1e-8 for k in ("objective","mean_wait_min","unserved_kwh","peak_queue")):
            raise ValueError("Stabilization worsens operational performance")
    record={**selected,"source":provenance(),"objective_version":OBJECTIVE_VERSION,"passed":True,"design_wall_seconds":report["design_wall_seconds"],"review_sha256":digest(folder/"review.json")}
    write_json(OUTPUT/"design_freeze.json",record)
    return record
