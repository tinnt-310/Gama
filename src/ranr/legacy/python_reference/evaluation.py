"""Actual physical metrics and all-demand penalties; no completion-only objective."""

from __future__ import annotations
from collections import Counter
from dataclasses import asdict
import numpy as np
from .records import DemandOutcome


def penalty(
    outcome: DemandOutcome, deadline_minutes: float
) -> tuple[float, float, float]:
    deficit = max(0.0, min(1.0, 1 - outcome.delivered_kwh / outcome.energy_kwh))
    incomplete = float(outcome.status != "completed")
    amount = deadline_minutes * (incomplete + deficit)
    if outcome.arrival_at is None:
        waiting = 0.0
    else:
        waiting = max(
            0.0,
            (outcome.start_at if outcome.start_at is not None else outcome.end_at)
            - outcome.arrival_at,
        )
    return amount, outcome.travel_minutes + waiting + amount, waiting + amount


def summarize(
    outcomes: list[DemandOutcome],
    deadline: float,
    peak_queue: int,
    port_count: int,
    utilization: list[float],
    seconds: float,
    extra: dict,
) -> dict:
    measured = [x for x in outcomes if x.measured]
    if any(
        x.energy_kwh <= 0
        or x.delivered_kwh < 0
        or x.delivered_kwh > x.energy_kwh + 1e-8
        for x in measured
    ):
        raise ValueError("Energy conservation violated")
    if any(x.status == "pending" for x in measured):
        raise ValueError("Unsettled demand outcome")
    waits = [x.start_at - x.arrival_at for x in measured if x.start_at is not None]
    travel = [x.travel_minutes for x in measured if x.arrival_at is not None]
    tw = [
        x.travel_minutes + x.start_at - x.arrival_at
        for x in measured
        if x.start_at is not None
    ]
    costs = [penalty(x, deadline) for x in measured]
    total = np.array([x[1] / deadline for x in costs])
    wstar = np.array([x[2] / deadline for x in costs])
    states = Counter(x.status for x in measured)
    followed = [
        x.station == x.recommended for x in measured if x.recommended is not None
    ]
    arrivals = Counter(x.station for x in measured if x.arrival_at is not None)
    counts = np.array(list(arrivals.values()), dtype=float)
    objective = (
        0.5 * float(total.mean())
        + 0.3 * float(np.quantile(wstar, 0.95))
        + 0.2 * peak_queue / port_count
        if len(measured)
        else None
    )
    errors = [
        x.predicted_wait - (x.start_at - x.arrival_at)
        for x in measured
        if x.predicted_wait is not None and x.start_at is not None
    ]

    def mean(values):
        return float(np.mean(values)) if len(values) else None

    return {
        "requests": len(measured),
        "outcomes": dict(states),
        "completed": states["completed"],
        "objective": objective,
        "mean_travel_min": mean(travel),
        "mean_wait_min": mean(waits),
        "p95_wait_min": float(np.quantile(waits, 0.95)) if waits else None,
        "mean_travel_wait_min": mean(tw),
        "mean_penalized_travel_wait_min": mean([x[1] for x in costs]),
        "p95_penalized_wait_min": (
            float(np.quantile([x[2] for x in costs], 0.95)) if costs else None
        ),
        "peak_queue": peak_queue,
        "utilization_by_station": utilization,
        "arrival_counts": {str(key): value for key, value in arrivals.items()},
        "arrival_hhi": (
            float(np.square(counts / counts.sum()).sum()) if counts.size else None
        ),
        "completion_rate": states["completed"] / len(measured) if measured else None,
        "requested_kwh": sum(x.energy_kwh for x in measured),
        "delivered_kwh": sum(x.delivered_kwh for x in measured),
        "compliance": mean(followed),
        "prediction_mae_min": mean(np.abs(errors)),
        "runtime_seconds": seconds,
        **extra,
    }
