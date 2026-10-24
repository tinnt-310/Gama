"""Hash-linked evidence for calibration migration and scientific release gates.

Historical manifests are immutable. Compatibility is deliberately limited to
calibration import; headless runs, checkpoints and published models stay strict.
"""
from pathlib import Path
import json
import math
import re
from ..paths import digest, write_json
from .headless import provenance, checked_result, RunConfig, ENVIRONMENT_VERSION
from .contracts import (OBJECTIVE_CONFIG_HASH, validate_configuration,
                        validate_charging_files, validate_physical_records,
                        validate_objective_identity)


def reference(path):
    path = Path(path).resolve()
    return {"path": str(path), "sha256": digest(path)}


def read_reference(item):
    path = verify_reference(item)
    return json.loads(path.read_text())


def verify_reference(item):
    path = Path(item["path"])
    if digest(path) != item["sha256"]:
        raise ValueError(f"Evidence changed: {path}")
    return path


def read_evidence(path):
    record = json.loads(Path(path).read_text())
    if record.get("passed") is not True or record.get("source") != provenance():
        raise ValueError(f"Missing/past-source evidence: {path}")
    for item in record.get("dependencies", []):
        verify_reference(item)
    return record


PRE_TRAINING_GATES = frozenset({
    'scientific_formulation', 'model_native', 'gui_headless', 'configuration',
    'data_complete', 'calibration', 'predictive_validity', 'accuracy_mc',
    'development', 'design_freeze', 'performance_budget', 'optimizer_smoke',
    'checkpoint_resume',
})


def verify_training_acceptance(path):
    """User acceptance contract: each prerequisite needs current hash-linked evidence."""
    proof = read_evidence(path)
    if proof.get('kind') != 'pre_training_acceptance' or set(proof.get('gates', {})) != PRE_TRAINING_GATES:
        raise ValueError('Complete pre-training gate evidence required; training NOT READY')
    for gate, item in proof['gates'].items():
        record = read_evidence(verify_reference(item))
        if gate == 'model_native':
            verify_native(item['path'])
        elif record.get('kind') != gate:
            raise ValueError('Wrong pre-training evidence kind: ' + gate)
    return proof


def validate_collection(folder, compatibility=None):
    folder = Path(folder).resolve()
    manifest = json.loads((folder / "manifest.json").read_text())
    source = manifest["source"]
    if source != provenance():
        if compatibility is None:
            raise ValueError(f"Historical calibration needs verified compatibility: {folder}")
        proof = read_evidence(compatibility)
        if proof.get("kind") == "headless_calibration_transition":
            from .transition import verify_transition
            verify_transition(compatibility)
            if proof.get("runs", {}).get(str(folder)) != digest(folder / "manifest.json"):
                raise ValueError("Collection not covered by headless transition")
        else:
            if proof.get("kind") != "calibration_compatibility":
                raise ValueError("Wrong compatibility evidence kind")
            validate_compatibility_sources(source, provenance(), proof["reviewed_changes"])
            if proof.get("runs", {}).get(str(folder)) != digest(folder / "manifest.json"):
                raise ValueError("Collection not covered by compatibility evidence")
            replay = read_reference(proof["reproducibility"])
            if replay.get("passed") is not True or replay.get("source") != provenance():
                raise ValueError("Current reproducibility evidence required")
            # Re-read the linked original manifests and replay inputs, not just booleans.
            for item in replay.get("dependencies", []):
                verify_reference(item)
            for path in [*replay.get("replays", []), replay.get("gui")]:
                if not path:
                    raise ValueError("Replay lacks its physical runs")
                checked_result(Path(path), {"source": provenance()})
    metrics = checked_result(folder, {"source": source})
    config = manifest["config"]
    RunConfig(**config)
    if not config["calibrating"] or not config["trace"] or config["environment_version"] != ENVIRONMENT_VERSION:
        raise ValueError("Not a physical calibration collection")
    required = {"configuration.json", "completion.json", "metrics.json", "intent_outcomes.json",
                "initial_fleet.json", "activity_plan.json", "traffic_plan.json", "vehicle_traits.json",
                "calibration_snapshots.csv", "calibration_contexts.csv", "calibration_fractions.csv"}
    if not required <= manifest["artifact_hashes"].keys():
        raise ValueError("Calibration artifacts were not sealed")
    actual = json.loads((folder / "configuration.json").read_text())
    validate_configuration(actual, config)
    validate_objective_identity(metrics)
    end = sum(config[k] for k in ("warmup_minutes", "measure_minutes", "deadline_minutes"))
    marker = json.loads((folder / "completion.json").read_text())
    if marker.get("status") != "complete" or not math.isfinite(marker.get("finished_min", float('nan'))) or marker["finished_min"] + 1e-7 < end:
        raise ValueError("Incomplete physical episode")
    if any(x.get("run_id") != manifest["run_id"] for x in (marker, actual, metrics)):
        raise ValueError("Collection identity mismatch")
    validate_charging_files(folder)
    validate_physical_records(folder, config)
    from .long_collection import validate_days
    validate_days(folder, int(end / 1440))
    return metrics


def validate_compatibility_sources(old, new, reviewed):
    """Require exact per-file review, protecting physics, input configs and runtime."""
    if old == new:
        return
    changed = {}
    for category in old.keys() | new.keys():
        a, b = old.get(category), new.get(category)
        if a == b:
            continue
        if category not in {"gaml", "orchestrator"} or not isinstance(a, dict) or not isinstance(b, dict):
            raise ValueError(f"Calibration semantics/runtime changed: {category}")
        for name in a.keys() | b.keys():
            if a.get(name) == b.get(name):
                continue
            if category == "gaml" and not name.startswith("models/tests/"):
                raise ValueError(f"Physical GAML changed: {name}")
            # headless launcher/config projection, contracts and paths are not eligible.
            if category == "orchestrator" and name in {"src/ranr/gama/headless.py", "src/ranr/gama/contracts.py", "src/ranr/paths.py"}:
                raise ValueError(f"Simulation/ledger boundary changed: {name}")
            changed[name] = {"old": a.get(name), "new": b.get(name)}
    if set(reviewed) != set(changed):
        raise ValueError("Every changed source file needs an exact compatibility review")
    for name, change in changed.items():
        item = reviewed[name]
        if any(item.get(k) != v for k, v in change.items()) or not item.get("rationale", "").strip():
            raise ValueError(f"Missing hash-linked change rationale: {name}")


def certify_compatibility(folders, review, replay, target):
    source = provenance()
    review = Path(review)
    reviewed = json.loads(review.read_text())["reviewed_changes"]
    reproduction = read_evidence(replay)
    if reproduction.get("kind") != "collection_reproducibility" or not reproduction.get("gui_checked") or not reproduction.get("outlier_resolved"):
        raise ValueError("Fresh GUI replay and resolved historical divergence required")
    from .replay import replay_report
    import tempfile
    with tempfile.TemporaryDirectory(prefix="ranr-compatibility-") as temporary:
        verified = replay_report(folders, reproduction["replays"], reproduction["gui"],
                                 Path(temporary)/"verified.json", reproduction["outlier"], reproduction["resolution"])
    if verified["passed"] is not True:
        raise ValueError("Reproducibility evidence does not match its physical runs")
    runs = {}
    for folder in folders:
        folder = Path(folder).resolve()
        manifest = json.loads((folder / "manifest.json").read_text())
        validate_compatibility_sources(manifest["source"], source, reviewed)
        checked_result(folder, {"source": manifest["source"]})
        if reproduction.get("selected_runs", {}).get(str(folder)) != digest(folder / "manifest.json"):
            raise ValueError("Replay evidence does not cover selected Collect set")
        runs[str(folder)] = digest(folder / "manifest.json")
    record = {"kind": "calibration_compatibility", "passed": True, "source": source,
              "objective_config_hash": OBJECTIVE_CONFIG_HASH, "runs": runs,
              "reviewed_changes": reviewed, "reproducibility": reference(replay),
              "dependencies": [reference(review), reference(replay),
                               *[reference(Path(p) / "manifest.json") for p in runs]]}
    write_json(target, record)
    for folder in folders:
        validate_collection(folder, target)
    return record


def verify_native(path):
    record = read_evidence(path)
    if not record.get("dependencies"):
        raise ValueError("Native validation has no fixture evidence")
    execution_source = record.get("execution_source", provenance())
    if "execution_source" in record:
        from .transition import verify_transition
        proof = verify_transition(record["source_transition"]["path"])
        verify_reference(record["source_transition"])
        original = read_reference(proof["native_validation"])
        if original["source"] != execution_source or execution_source != proof["execution_source"]:
            raise ValueError("Native execution provenance changed")
        if any(record.get(k) != v for k,v in original.items() if k != "source"):
            raise ValueError("Reviewed native results differ from original execution")
    markers = set()
    from .monitoring import classify_console
    for item in record["dependencies"]:
        fixture = read_reference(item)
        marker = fixture.get("marker")
        console = fixture.get("console", "")
        failures = classify_console(console)[0]
        # These fixtures deliberately call ranr_abort and assert the exact guard
        # reason before emitting PASS. Unknown runtime/assertion/JVM errors remain
        # fatal, including in a negative fixture.
        allowed_errors = set()
        if fixture.get("model") == "models/tests/RanrStartupFailureTests.gaml" and marker == "RANR_STARTUP_FAILURE_PASS":
            allowed_errors.add("RANR_ERROR: CALIBRATION NOT READY: fixture registration failure")
        guard = "RANR_CONFIGURATION_GUARD_PASS"
        if fixture.get("model") == "models/tests/RanrLifecycleTests.gaml" and (marker == guard or str(marker).startswith(guard + " ")):
            fields = {"case":"case", "compliance":"compliance", "defer":"defer_probability", "trace":"trace",
                      "parameters":"parameters", "retry":"energy_retry_minutes", "collection":"collection_seed", "enabled":"enabled"}
            tags = set(re.findall(r"(?m)^RANR_CONFIGURATION_GUARD_PASS (\w+)\s*$", console))
            if len(tags) == 1 and next(iter(tags)) in fields:
                field = fields[next(iter(tags))]
                allowed_errors.add(f"RANR_ERROR: Configuration changed: {field}; restart required")
        failures = [line for line in failures if line.strip() not in allowed_errors]
        if fixture.get("source") != execution_source or not marker or marker not in console or failures:
            raise ValueError(f"Invalid native fixture evidence: {item['path']}; marker={marker!r}; failures={failures}")
        markers.add(marker)
    required = {"RANR_OBJECTIVE_PASS", "RANR_PHYSICAL_PASS", "RANR_DECISION_PASS", "RANR_PROTOCOL_PASS",
                "RANR_PORT_CAPACITY_PASS", "RANR_LAST_DAY_PASS", "RANR_BUSY_STATE_PASS"}
    if not required <= markers:
        raise ValueError("Native validation lacks required fixture coverage")
    return record
