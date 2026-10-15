"""Physical metrics from unique lifecycle events, separate from optimization costs."""

import csv
from pathlib import Path
import numpy as np
from ranr.legacy.event_io import rows, event_ledger


def event_metrics(prefix, request_ids=None):
    sessions = event_ledger(rows(str(prefix) + "_events.csv"), request_ids)
    travel, waiting, total, eta_errors, travel_energy, travel_money = (
        [],
        [],
        [],
        [],
        [],
        [],
    )
    for rid, events in sessions.items():
        arrival = events.get("arrival")
        start = events.get("service_started")
        commit = events.get("assigned")
        if arrival and commit:
            value = float(arrival["time_min"]) - float(commit["time_min"])
            if value < -1e-9:
                raise ValueError(f"Arrival before commit: {rid}")
            travel.append(max(0.0, value))
            if arrival.get("travel_kwh"):
                travel_energy.append(float(arrival["travel_kwh"]))
            if arrival.get("extra_electricity_vnd"):
                travel_money.append(float(arrival["extra_electricity_vnd"]))
            predicted = float(commit.get("eta_min") or -1.0)
            if predicted >= 0.0:
                eta_errors.append(float(arrival["time_min"]) - predicted)
        if start:
            if not arrival:
                raise ValueError(f"Service before arrival: {rid}")
            value = float(start["time_min"]) - float(arrival["time_min"])
            if value < -1e-9 or abs(value - float(start["waiting_min"])) > 1e-6:
                raise ValueError(f"Inconsistent waiting: {rid}")
            waiting.append(max(0.0, value))
            if commit:
                total.append(float(start["time_min"]) - float(commit["time_min"]))
        if "service_completed" in events:
            if (
                not start
                or float(events["service_completed"]["time_min"])
                < float(start["time_min"]) - 1e-9
            ):
                raise ValueError(f"Inconsistent completion: {rid}")

    def average(values):
        return float(np.mean(values)) if values else None

    terminals = {"service_completed", "cancelled", "stranded"}
    return dict(
        requests=len(sessions),
        travel_sessions=len(travel),
        started=len(waiting),
        total_sessions=len(total),
        completed=sum("service_completed" in e for e in sessions.values()),
        cancelled=sum("cancelled" in e for e in sessions.values()),
        stranded=sum("stranded" in e for e in sessions.values()),
        deferred=sum("deferred" in e for e in sessions.values()),
        unfinished=sum(not (terminals & set(e)) for e in sessions.values()),
        unstarted=sum(
            "service_started" not in e and not (terminals & set(e))
            for e in sessions.values()
        ),
        zero_wait_sessions=sum(v <= 1e-9 for v in waiting),
        mean_travel_min=average(travel),
        mean_wait_min=average(waiting),
        p95_wait_min=float(np.percentile(waiting, 95)) if waiting else None,
        mean_total_min=average(total),
        eta_sessions=len(eta_errors),
        eta_bias_min=average(eta_errors),
        eta_mae_min=average([abs(v) for v in eta_errors]),
        travel_energy_sessions=len(travel_energy),
        mean_travel_kwh=average(travel_energy),
        mean_extra_electricity_vnd=average(travel_money),
        evaluation="fixed-port lifecycle events; F and d*pi are congestion surrogates",
    )
