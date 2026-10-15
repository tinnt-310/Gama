"""FIFO physical station and pure queue counterfactuals share allocation semantics."""

from __future__ import annotations
from dataclasses import dataclass
from collections import deque
import math
import numpy as np
from .records import Interval, QueueJob, StationSnapshot


def dispatch(
    free: np.ndarray,
    powers: np.ndarray,
    arrival: float,
    energy: float,
    max_kw: float,
    efficiency: float,
    fifo_start: float = 0.0,
) -> tuple[int, float, float]:
    starts = np.maximum(free, max(arrival, fifo_start))
    start = float(starts.min())
    # At equal availability use fastest usable rate, then stable port index.
    possible = np.flatnonzero(starts <= start + 1e-10)
    port = int(possible[np.argmax(np.minimum(powers[possible], max_kw))])
    end = start + 60 * energy / (efficiency * min(float(powers[port]), max_kw))
    free[port] = end
    return port, start, end


def queue_trajectory(
    free: np.ndarray,
    powers: np.ndarray,
    jobs: list[tuple[float, float, float]],
    efficiency: float,
) -> tuple[np.ndarray, float]:
    """Jobs in stable FIFO arrival order; return starts and sum of other waits."""
    starts = np.empty(len(jobs))
    last = 0.0
    for index, (arrival, energy, maximum) in enumerate(jobs):
        _, begin, _ = dispatch(free, powers, arrival, energy, maximum, efficiency, last)
        starts[index] = begin
        last = begin
    return starts, float(sum(starts[i] - job[0] for i, job in enumerate(jobs)))


@dataclass
class Active:
    request_id: str
    start: float
    finish: float
    energy: float
    rate: float
    generation: int


class ChargingStation:
    def __init__(self, station: int, powers: tuple[float, ...], efficiency: float):
        self.station = station
        self.powers = powers
        self.efficiency = efficiency
        self.active: list[Active | None] = [None] * len(powers)
        self.queue: deque[tuple[str, float, float, float]] = deque()
        self.seen: set[str] = set()
        self.peak = 0
        self.generation = 0
        self.busy_minutes = 0.0
        self.available_port_minutes = 0.0
        self.last_account = 0.0

    def account(self, at: float) -> None:
        if at < self.last_account - 1e-9:
            raise ValueError("Time reversed")
        self.busy_minutes += (at - self.last_account) * sum(
            x is not None for x in self.active
        )
        self.available_port_minutes += (at - self.last_account) * len(self.powers)
        self.last_account = at

    def enqueue(self, rid: str, at: float, energy: float, max_kw: float) -> None:
        if rid in self.seen:
            raise ValueError("Duplicate physical arrival")
        self.seen.add(rid)
        self.queue.append((rid, at, energy, max_kw))

    def start_ready(self, at: float) -> list[tuple[int, Active, float]]:
        self.account(at)
        result = []
        while self.queue:
            free = [i for i, x in enumerate(self.active) if x is None]
            if not free:
                break
            rid, arrival, energy, maximum = self.queue.popleft()
            port = max(free, key=lambda i: (min(self.powers[i], maximum), -i))
            rate = min(self.powers[port], maximum)
            self.generation += 1
            job = Active(
                rid,
                at,
                at + 60 * energy / (self.efficiency * rate),
                energy,
                rate,
                self.generation,
            )
            self.active[port] = job
            result.append((port, job, at - arrival))
        self.peak = max(self.peak, len(self.queue))
        return result

    def finish(self, port: int, generation: int, at: float) -> Active | None:
        self.account(at)
        job = self.active[port]
        if job is None or job.generation != generation:
            return None
        self.active[port] = None
        return job

    def cancel(self, rid: str, at: float) -> float:
        self.account(at)
        self.queue = deque(x for x in self.queue if x[0] != rid)
        for port, job in enumerate(self.active):
            if job is not None and job.request_id == rid:
                self.active[port] = None
                return min(
                    job.energy,
                    max(0.0, at - job.start) * self.efficiency * job.rate / 60,
                )
        return 0.0

    def snapshot(
        self, at: float, width: float = 0.0, energy_width: float = 0.0
    ) -> StationSnapshot:
        def interval(value: float, bin_width: float) -> Interval:
            if value <= 1e-10 or bin_width == 0:
                return Interval(max(0.0, value), max(0.0, value))
            lower = math.floor(value / bin_width) * bin_width
            return Interval(lower, lower + bin_width)

        release = tuple(
            interval(max(0.0, x.finish - at) if x else 0.0, width) for x in self.active
        )
        queue = tuple(
            QueueJob(interval(e, energy_width), m) for _, _, e, m in self.queue
        )
        return StationSnapshot(
            self.station,
            at,
            self.powers,
            release,
            queue,
            "local" if width == 0 else "peer",
        )
