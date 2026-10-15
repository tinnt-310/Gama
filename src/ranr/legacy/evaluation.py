"""Historical recommendation metrics, separate from launch and calibration."""

import csv
import json
import math
from pathlib import Path
import numpy as np
from .event_io import rows, event_ledger


def evaluate(prefix):
    events = rows(str(prefix) + "_events.csv")
    by = event_ledger(events)
    recs = (
        rows(str(prefix) + "_recommendations.csv")
        if Path(str(prefix) + "_recommendations.csv").exists()
        else []
    )
    rec_by = {e["request_id"]: e for e in recs}
    waits = []
    travel = []
    total = []
    energies = []
    distances = []
    errors = []
    eta_errors = []
    followed = 0
    output = []
    for rid, e in by.items():
        if "request" not in e:
            continue
        rec = rec_by.get(rid, {})
        choice = e.get("choice", e.get("assigned", {}))
        arrival = e.get("arrival", {})
        start = e.get("service_started", {})
        finish = e.get("service_completed", {})
        row = {
            "request_id": rid,
            "recommended_station": rec.get("recommended_station", ""),
            "chosen_station": choice.get("station", ""),
            "arrival_station": arrival.get("station", ""),
            "recommendation_followed": bool(
                rec and choice and rec["recommended_station"] == choice["station"]
            ),
            "unresolved": not bool(finish),
            "completed": bool(finish),
            "deferred": "deferred" in e,
            "cancelled": "cancelled" in e,
            "stranded": "stranded" in e,
            "travel_min": None,
            "waiting_min": None,
            "travel_wait_min": None,
            "service_min": None,
            "distance_km": None,
            "energy_kwh": None,
            "waiting_error_min": None,
            "forecast_status": rec.get("forecast_status", ""),
            "request_min": float(e["request"]["time_min"]),
            "recommendation_min": float(rec["issued_at"]) if rec else None,
            "choice_min": float(choice["time_min"]) if choice else None,
            "predicted_eta_min": float(choice["eta_min"]) if choice else None,
            "actual_arrival_min": float(arrival["time_min"]) if arrival else None,
            "service_start_min": float(start["time_min"]) if start else None,
            "service_finish_min": float(finish["time_min"]) if finish else None,
            "predicted_wait_min": (
                float(choice.get("choice_wait_min", -1)) if choice else None
            ),
            "score_method": rec.get("score_method", "legacy_see_run_config"),
            "recommendation_score": float(rec["score"]) if rec else None,
            "snapshot_time": float(rec["snapshot_time"]) if rec else None,
        }
        if arrival and choice:
            row["travel_min"] = float(arrival["time_min"]) - float(choice["time_min"])
            row["distance_km"] = float(arrival["travel_m"]) / 1000
            row["energy_kwh"] = float(arrival["travel_kwh"])
            travel.append(row["travel_min"])
            distances.append(row["distance_km"])
            energies.append(row["energy_kwh"])
            eta_errors.append(float(arrival["time_min"]) - float(choice["eta_min"]))
        if start and arrival:
            row["waiting_min"] = float(start["time_min"]) - float(arrival["time_min"])
            waits.append(row["waiting_min"])
            if choice:
                row["travel_wait_min"] = row["travel_min"] + row["waiting_min"]
                total.append(row["travel_wait_min"])
            # Compare prediction for chosen station, not recommendation if the driver rejected it.
            if choice and float(choice.get("choice_wait_min", -1) or -1) >= 0:
                row["waiting_error_min"] = (
                    float(choice["choice_wait_min"]) - row["waiting_min"]
                )
                errors.append(row["waiting_error_min"])
            elif rec and row["recommendation_followed"]:
                row["waiting_error_min"] = (
                    float(rec["predicted_wait_min"]) - row["waiting_min"]
                )
                errors.append(row["waiting_error_min"])
        if finish and start:
            row["service_min"] = float(finish["time_min"]) - float(start["time_min"])
        followed += int(row["recommendation_followed"])
        output.append(row)

    def mean(x):
        return float(np.mean(x)) if len(x) else None

    def p95(x):
        return float(np.quantile(x, 0.95)) if len(x) else None

    arr = {}
    for e in events:
        if e["event"] == "arrival":
            key = int(float(e["time_min"]) // 5)
            arr.setdefault(key, {})[e["station"]] = (
                arr.setdefault(key, {}).get(e["station"], 0) + 1
            )
    stations = sorted({e["station"] for e in events if e["station"]})
    vectors = np.array(
        [
            [arr.get(b, {}).get(s, 0) for s in stations]
            for b in range(max(arr, default=0) + 1)
        ],
        dtype=float,
    )
    shares = np.divide(
        vectors,
        vectors.sum(axis=1, keepdims=True),
        out=np.zeros_like(vectors),
        where=vectors.sum(axis=1, keepdims=True) > 0,
    )
    occupied = vectors.sum(axis=1) > 0
    physical = (
        rows(str(prefix) + "_physical_summary.csv")
        if Path(str(prefix) + "_physical_summary.csv").exists()
        else []
    )
    summary = {
        "prefix": str(prefix),
        "requests": len(output),
        "arrived_sessions": len(travel),
        "started_sessions": len(waits),
        "completion_rate": sum(r["completed"] for r in output) / max(1, len(output)),
        "completed": sum(r["completed"] for r in output),
        "unresolved": sum(r["unresolved"] for r in output),
        "unstarted": sum(r["waiting_min"] is None for r in output),
        "cancelled": sum(r["cancelled"] for r in output),
        "stranded": sum(r["stranded"] for r in output),
        "deferred": sum(r["deferred"] for r in output),
        "followed": followed,
        "mean_wait_min": mean(waits),
        "p95_wait_min": p95(waits),
        "mean_travel_min": mean(travel),
        "p95_travel_min": p95(travel),
        "mean_travel_wait_min": mean(total),
        "completed_mean_travel_wait_min": mean(
            [
                r["travel_wait_min"]
                for r in output
                if r["completed"] and r["travel_wait_min"] is not None
            ]
        ),
        "total_distance_km": sum(distances),
        "total_travel_kwh": sum(energies),
        "waiting_mae_min": mean(np.abs(errors)),
        "waiting_rmse_min": math.sqrt(mean(np.square(errors))) if errors else None,
        "waiting_p95_abs_error_min": p95(np.abs(errors)),
        "eta_mae_min": mean(np.abs(eta_errors)),
        "peak_queue": max((int(r["peak_queue"]) for r in physical), default=None),
        "arrival_concentration_hhi": (
            mean((shares[occupied] ** 2).sum(axis=1)) if occupied.any() else None
        ),
        "arrival_total_variation": (
            mean(np.abs(np.diff(shares[occupied], axis=0)).sum(axis=1))
            if occupied.sum() > 1
            else None
        ),
        "arrival_count_std": float(np.std(vectors)) if vectors.size else 0,
        "replay_fraction": sum(r.get("forecast_status") == "replay" for r in recs)
        / max(1, len(recs)),
        "fallbacks": {
            status: sum(r.get("forecast_status") == status for r in recs)
            for status in sorted({r.get("forecast_status", "") for r in recs})
        },
    }
    rec_bins = {}
    for rec in recs:
        b = int(float(rec["issued_at"]) // 5)
        station = rec["recommended_station"]
        rec_bins.setdefault(b, {})[station] = (
            rec_bins.setdefault(b, {}).get(station, 0) + 1
        )
    summary["recommendation_concentration_hhi"] = mean(
        [
            sum((v / sum(hist.values())) ** 2 for v in hist.values())
            for hist in rec_bins.values()
        ]
    )
    if len(stations) > 0 and occupied.sum() > 1:
        dominant = np.argmax(shares[occupied], axis=1)
        summary["arrival_switch_rate"] = float(np.mean(dominant[1:] != dominant[:-1]))
    summary["cohorts"] = {}
    for name, predicate in [
        ("first_24h", lambda r: r["request_min"] < 1440),
        ("after_24h", lambda r: r["request_min"] >= 1440),
    ]:
        cohort = [r for r in output if predicate(r)]
        observed = [r["waiting_min"] for r in cohort if r["waiting_min"] is not None]
        summary["cohorts"][name] = {
            "requests": len(cohort),
            "completed": sum(r["completed"] for r in cohort),
            "unresolved": sum(r["unresolved"] for r in cohort),
            "started": len(observed),
            "mean_wait_min": mean(observed),
            "p95_wait_min": p95(observed),
        }
    metrics_path = Path(str(prefix) + "_recommendation_metrics.csv")
    if metrics_path.exists():
        summary["runtime_and_communication"] = rows(metrics_path)[0]
    errors_path = Path(str(prefix) + "_forecast_errors.csv")
    if errors_path.exists():
        data = rows(errors_path)
        for field in ("local_workload", "corrected_workload"):
            residual = [float(r[field]) - float(r["actual_workload"]) for r in data]
            summary[field + "_mae"] = mean(np.abs(residual))
            summary[field + "_rmse"] = (
                math.sqrt(mean(np.square(residual))) if residual else None
            )
    with Path(str(prefix) + "_session_evaluation.csv").open("w") as f:
        if output:
            w = csv.DictWriter(f, fieldnames=list(output[0]))
            w.writeheader()
            w.writerows(output)
    Path(str(prefix) + "_evaluation.json").write_text(
        json.dumps(summary, indent=2) + "\n"
    )
    return summary
