"""Audit completed experiment artifacts and summarize paired, seed-level results.

Does not rerun experiments or change recorded observations. Confidence intervals
describe these synthetic seeds, not real driver compliance or city performance.
"""

from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
from scipy.stats import t as student_t

from ranr.paths import ROOT
from ranr.legacy.scripts.recommendation_experiments import OUT, evaluate, rows
from ranr.legacy.scripts.input_manifest import build_manifest


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def audit_run(result, ideal=False):
    prefix = result["prefix"]
    events = rows(prefix + "_events.csv")
    counts = Counter((e["request_id"], e["event"]) for e in events)
    for (rid, event), count in counts.items():
        if event in (
            "arrival",
            "service_started",
            "service_completed",
            "cancelled",
            "stranded",
        ):
            assert count == 1, (prefix, rid, event, count)
    sessions = defaultdict(dict)
    for event in events:
        sessions[event["request_id"]][event["event"]] = event
    for rid, session in sessions.items():
        order = [
            "request",
            "assigned" if ideal else "choice",
            "arrival",
            "service_started",
            "service_completed",
        ]
        observed = [float(session[key]["time_min"]) for key in order if key in session]
        assert observed == sorted(observed), (prefix, rid, "timestamp order")
        assert (
            sum(
                key in session for key in ("service_completed", "cancelled", "stranded")
            )
            <= 1
        )
        if "arrival" in session:
            arrival = session["arrival"]
            choice = session[order[1]]
            assert arrival["station"] == choice["station"], (
                prefix,
                rid,
                "wrong station",
            )
            assert (
                abs(
                    float(arrival["travel_kwh"])
                    - 0.18 * float(arrival["travel_m"]) / 1000
                )
                < 1e-7
            )
        if "service_started" in session:
            assert "arrival" in session
            wait = float(session["service_started"]["time_min"]) - float(
                session["arrival"]["time_min"]
            )
            assert wait >= 0
            assert abs(wait - float(session["service_started"]["waiting_min"])) < 1e-7
        if "service_completed" in session:
            assert "service_started" in session
            assert abs(float(session["service_completed"]["soc_pct"]) - 80) < 1e-6
    if not ideal:
        assert all(e["event"] != "assigned" for e in events), (
            prefix,
            "hard assignment leaked",
        )
        config = rows(prefix + "_recommendation_config.csv")[0]
        assert config["hard_inbound"] == "false"
        assert config["runtime"] == "RECOMMENDATION_RUNTIME"
        assert config["behavior_calibrated"] == "false"
    return {
        "prefix": prefix,
        "requests": result["requests"],
        "event_rows": len(events),
        "status": "PASS",
    }


def mean(values):
    available = [v for v in values if v is not None]
    return float(np.mean(available)) if available else None


def main():
    primary = json.loads((OUT / "closed_loop_results.json").read_text())
    supplement = json.loads((OUT / "supplementary_results.json").read_text())
    ideal = json.loads((OUT / "ideal_closed_loop.json").read_text())
    groups = defaultdict(list)
    audit = []
    for result in primary + supplement:
        audit.append(audit_run(result))
        # Recompute evaluation from immutable event artifacts with current evaluator.
        fresh = evaluate(Path(result["prefix"]))
        result.update(fresh)
        if result in primary:
            groups[result["mode"]].append(result)
        elif result["experiment"] in ("B1_nearest", "B2_ETA"):
            groups[result["experiment"]].append(result)
    audit.append(audit_run(ideal, ideal=True))
    seeds = sorted({r["seed"] for r in primary})
    same_demand = {}
    for seed in seeds:
        selected = [r for r in primary if r["seed"] == seed]
        selected += [
            r
            for r in supplement
            if r["experiment"] in ("B1_nearest", "B2_ETA")
            and r["settings"]["seed"] == seed
        ]
        hashes = {digest(r["prefix"] + "_demand.csv") for r in selected}
        assert len(hashes) == 1, ("demand mismatch", seed)
        same_demand[str(seed)] = hashes.pop()
    assert digest(ideal["prefix"] + "_demand.csv") == same_demand[str(ideal["seed"])]
    fields = (
        "mean_wait_min",
        "p95_wait_min",
        "mean_travel_min",
        "mean_travel_wait_min",
        "completed_mean_travel_wait_min",
        "completed",
        "unresolved",
        "unstarted",
        "peak_queue",
        "waiting_mae_min",
        "replay_fraction",
        "arrival_switch_rate",
        "arrival_total_variation",
        "recommendation_concentration_hhi",
    )
    aggregate = {
        name: {
            "runs": len(runs),
            **{field: mean([r[field] for r in runs]) for field in fields},
        }
        for name, runs in groups.items()
    }
    indexed = {
        name: {r["seed"]: r for r in runs}
        for name, runs in groups.items()
        if name in ("B3", "B4", "B4-N")
    }
    paired = {}
    for name, reference in [("B4", "B3"), ("B4-N", "B4")]:
        delta = np.array(
            [
                indexed[name][seed]["mean_wait_min"]
                - indexed[reference][seed]["mean_wait_min"]
                for seed in seeds
            ]
        )
        halfwidth = float(
            student_t.ppf(0.975, len(delta) - 1)
            * np.std(delta, ddof=1)
            / np.sqrt(len(delta))
        )
        paired[name + "_minus_" + reference] = {
            "seed_deltas_min": delta.tolist(),
            "mean_min": float(delta.mean()),
            "t_interval_95": [
                float(delta.mean() - halfwidth),
                float(delta.mean() + halfwidth),
            ],
            "interpretation": "paired synthetic seed means; censoring remains reported separately",
        }
    ideal_batches = [
        row
        for file in Path(ideal["prefix"]).parent.glob("run_batch_*_metrics.csv")
        for row in rows(file)
    ]
    for batch in ideal_batches:
        assert float(batch["LB"]) <= float(batch["UB"]) + 1e-6
        assert float(batch["UB"]) <= float(batch["pre_repair"]) + 1e-6
    report = {
        "schema_version": 2,
        "status": "PASS",
        "audited_runs": len(audit),
        "runs": audit,
        "aggregate": aggregate,
        "paired": paired,
        "same_exogenous_demand_sha256": same_demand,
        "ideal_same_seed_demand": True,
        "ideal_batch_status": dict(Counter(r["status"] for r in ideal_batches)),
        "ideal_mean_relative_gap": mean(
            [float(r["relative_gap"]) for r in ideal_batches]
        ),
        "compile_roots": (OUT / "gama_suite_final.log")
        .read_text()
        .count("COMPILE_PASS"),
        "gama_runtime_pass_markers": sum(
            "PASS" in line and "COMPILE_PASS" not in line
            for line in (OUT / "gama_suite_final.log").read_text().splitlines()
        ),
        "limits": [
            "synthetic FOLLOW behavior",
            "60-second experiment step",
            "two-station main fixture",
            "unfinished sessions are censored, never replaced by zero waiting",
            "no global actual-waiting optimality certificate",
        ],
    }
    # Check explanation columns on the final fixture, without rewriting old evidence.
    explanation_prefix = str(OUT / "contracts")
    recommendations = rows(explanation_prefix + "_recommendations.csv")
    candidates = rows(explanation_prefix + "_recommendation_candidates.csv")
    assert recommendations and candidates
    assert all(
        r["score_method"] == "minimax" and r["monetary_cost_vnd"] == ""
        for r in recommendations
    )
    for candidate in candidates:
        if candidate["recommended"] == "true":
            assert int(candidate["alternative_rank"]) == 1
        assert abs(float(candidate["regret_D"]) - float(candidate["regret_E"])) < 1e-8
        assert float(candidate["received_at"]) >= float(candidate["snapshot_time"])
        assert float(candidate["scenario_spread"]) >= -1.0
    report["final_explanation_export"] = "PASS"
    (OUT / "artifact_audit.json").write_text(json.dumps(report, indent=2) + "\n")
    source_files = sorted(
        [
            *ROOT.glob("models/**/*.gaml"),
            *ROOT.glob("verification/*.py"),
            *ROOT.glob("scripts/*.py"),
            *ROOT.glob("scripts/java/*.java"),
            *ROOT.glob("tests/*.py"),
        ]
    )
    source_manifest = {
        "sources": {str(p.relative_to(ROOT)): digest(p) for p in source_files},
        "inputs": build_manifest(),
        "runtime": "GAMA 1.9.3 / Java 17",
        "note": "Final handoff source hashes; individual run configs record their own settings.",
    }
    (OUT / "source_manifest.json").write_text(
        json.dumps(source_manifest, indent=2) + "\n"
    )
    print("RECOMMENDATION_ARTIFACT_AUDIT_PASS", len(audit), "runs")
    print(
        json.dumps(
            {
                "aggregate": aggregate,
                "paired": paired,
                "ideal_status": report["ideal_batch_status"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
