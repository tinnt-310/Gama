"""Frozen train-only empirical reconstruction of quantized queue snapshots."""

from __future__ import annotations
from dataclasses import asdict, dataclass
import heapq
from pathlib import Path
import numpy as np
from .charging import ChargingStation
from .geography import Geography
from .paths import OUTPUTS, write_json
from .records import Interval, QueueJob, StationSnapshot
from .randomness import rng
from .behavior import base_probabilities


@dataclass(frozen=True)
class Calibration:
    release_fractions: tuple[float, ...]
    energy_fractions: tuple[float, ...]
    prior_snapshots: tuple[tuple[StationSnapshot, ...], ...]
    request_rates: tuple[float, ...]
    background_rates: tuple[float, ...]
    energy_samples: tuple[float, ...]
    feature_scales: tuple[float, ...] = (30.0, 60.0, 120.0, 120.0, 60.0)
    travel_priors: tuple[tuple[tuple[float, ...], ...], ...] = ()

    @property
    def priors(self) -> tuple[StationSnapshot, ...]:
        # Observable state summaries use expectations, not an arbitrary first draw.
        # The estimator separately samples complete, correlated training snapshots.
        result = []
        for i, pool in enumerate(self.prior_snapshots):
            release = tuple(
                Interval(
                    float(np.mean([s.release[j].low for s in pool])),
                    float(np.mean([s.release[j].high for s in pool])),
                )
                for j in range(len(pool[0].powers))
            )
            count = max(len(s.queue) for s in pool)
            queue = tuple(
                QueueJob(
                    Interval(
                        float(
                            np.mean(
                                [
                                    s.queue[j].energy.low if j < len(s.queue) else 0.0
                                    for s in pool
                                ]
                            )
                        ),
                        float(
                            np.mean(
                                [
                                    s.queue[j].energy.high if j < len(s.queue) else 0.0
                                    for s in pool
                                ]
                            )
                        ),
                    ),
                    120.0,
                )
                for j in range(count)
            )
            result.append(
                StationSnapshot(i, 0.0, pool[0].powers, release, queue, "prior")
            )
        return tuple(result)


def from_dict(value: dict) -> Calibration:
    snapshots = []
    for group in value["prior_snapshots"]:
        snapshots.append(
            tuple(
                StationSnapshot(
                    x["station"],
                    x["issued_at"],
                    tuple(x["powers"]),
                    tuple(Interval(**b) for b in x["release"]),
                    tuple(
                        QueueJob(Interval(**j["energy"]), j["max_kw"])
                        for j in x["queue"]
                    ),
                    x["source"],
                )
                for x in group
            )
        )
    return Calibration(
        tuple(value["release_fractions"]),
        tuple(value["energy_fractions"]),
        tuple(snapshots),
        tuple(value["request_rates"]),
        tuple(value["background_rates"]),
        tuple(value["energy_samples"]),
        tuple(value["feature_scales"]),
        tuple(
            tuple(tuple(t) for t in group) for group in value.get("travel_priors", ())
        ),
    )


def prepare_calibration(
    geo: Geography, path: Path = OUTPUTS / "data/calibration.json"
) -> Calibration:
    """24-hour independent train workload, 6-hour warmup; no evaluation seeds."""
    fractions = []
    energies = []
    samples = []
    priors = []
    rates = []
    random = rng(800001, "offline_calibration")
    for sid, station in enumerate(geo.stations):
        physical = ChargingStation(sid, station.powers, 0.9)
        events = []
        sequence = 0
        rate = 0.6 * 0.9 * sum(min(p, 120.0) for p in station.powers) / 20.0 / 60.0
        rates.append(rate)
        at = 0.0
        while at < 1440:
            at += float(random.exponential(1 / rate))
            energy = float(
                np.clip(
                    random.lognormal(
                        np.log(20) - 0.5 * np.log(1 + 0.4**2),
                        np.sqrt(np.log(1 + 0.4**2)),
                    ),
                    2.0,
                    50.0,
                )
            )
            heapq.heappush(
                events, (at, sequence, "arrival", (f"{sid}-{sequence}", energy))
            )
            sequence += 1
            samples.append(energy)
        for at in range(360, 1440, 15):
            heapq.heappush(events, (float(at), sequence, "snapshot", ()))
            sequence += 1
        group = []
        while events:
            at, _, kind, data = heapq.heappop(events)
            if kind == "arrival":
                physical.enqueue(data[0], at, data[1], 120.0)
            elif kind == "finish":
                physical.finish(data[0], data[1], at)
            else:
                exact = physical.snapshot(at)
                coarse = physical.snapshot(at, 5.0, 5.0)
                for a, b in zip(exact.release, coarse.release):
                    if b.high > b.low:
                        fractions.append((a.low - b.low) / (b.high - b.low))
                for a, b in zip(exact.queue, coarse.queue):
                    if b.energy.high > b.energy.low:
                        energies.append(
                            (a.energy.low - b.energy.low)
                            / (b.energy.high - b.energy.low)
                        )
                group.append(
                    StationSnapshot(
                        sid, 0.0, coarse.powers, coarse.release, coarse.queue, "prior"
                    )
                )
            for port, job, _ in physical.start_ready(at):
                heapq.heappush(
                    events, (job.finish, sequence, "finish", (port, job.generation))
                )
                sequence += 1
        priors.append(tuple(group))
    if not fractions or not energies:
        raise ValueError(
            "Calibration did not observe sufficient quantized service/queue states"
        )
    travel = geo.distance_km * 2.0  # declared nominal 30 km/h, minutes
    issuers = travel.argmin(axis=1)
    groups = tuple(
        tuple(tuple(float(t) for t in row) for row in travel[issuers == i])
        for i in range(len(geo.stations))
    )
    source_rates = tuple(
        0.8 * sum(rates) * float(np.mean(issuers == i))
        for i in range(len(geo.stations))
    )
    background_share = np.mean([base_probabilities(row) for row in travel], axis=0)
    model = Calibration(
        tuple(fractions),
        tuple(energies),
        tuple(priors),
        source_rates,
        tuple(0.2 * sum(rates) * 0.95 * background_share),
        tuple(samples),
        (30.0, 60.0, 120.0, 120.0, 60.0),
        groups,
    )
    write_json(path, asdict(model))
    write_json(
        path.with_name("calibration_manifest.json"),
        {
            "split": "train",
            "seed": 800001,
            "minutes": 1440,
            "warmup_minutes": 360,
            "nominal_load": 0.6,
            "release_samples": len(fractions),
            "queue_energy_samples": len(energies),
            "assumptions": "Independent Poisson station workloads, 120 kW acceptance, lognormal energy; empirical bin residuals pooled across stations. Priors are assumptions, not measured driver behavior.",
        },
    )
    return model
