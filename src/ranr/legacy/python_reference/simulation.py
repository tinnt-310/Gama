"""Discrete-event ground truth; algorithms receive immutable station observations."""

from __future__ import annotations
from dataclasses import asdict, replace
import hashlib
import heapq
import json
from pathlib import Path
from time import perf_counter
import numpy as np
from .behavior import driver_choice
from .calibration import Calibration
from .charging import ChargingStation
from .config import Config
from .evaluation import summarize
from .geography import Geography
from .information import InformationStore
from .logging import RecordLog
from .policies import RecommendationPolicy, parameter_count
from .prediction import QueuePredictor
from .randomness import rng
from .records import DemandOutcome, Packet, Request


def generate_requests(
    geo: Geography, config: Config
) -> tuple[tuple[Request, bool], ...]:
    random = rng(config.seed, "exogenous_demand")
    rate = (
        config.load
        * config.efficiency
        * sum(min(p, 120.0) for station in geo.stations for p in station.powers)
        / config.energy_mean_kwh
        / 60.0
    )
    horizon = config.warmup_minutes + config.measure_minutes
    at = 0.0
    output = []
    index = 0
    sd = np.sqrt(np.log(1 + (config.energy_sd_kwh / config.energy_mean_kwh) ** 2))
    while True:
        # Thinning provides the same base process with explicit burst intervals.
        at += float(random.exponential(1 / (2 * rate)))
        if at >= horizon:
            break
        phase = (at - config.warmup_minutes) % 1440.0
        burst = config.case in ("burst", "combined") and (
            330 <= phase < 360 or 1020 <= phase < 1050
        )
        if random.random() > (1.0 if burst else 0.5):
            continue
        origin = int(random.integers(len(geo.origin_nodes)))
        energy = float(
            np.clip(
                random.lognormal(np.log(config.energy_mean_kwh) - 0.5 * sd * sd, sd),
                2.0,
                50.0,
            )
        )
        battery = float(
            random.uniform(max(config.reserve_kwh, 5.0), config.battery_kwh - 2.0)
        )
        energy = min(energy, config.battery_kwh - battery)
        maximum = float(random.choice([60.0, 120.0, 250.0], p=[0.3, 0.5, 0.2]))
        distance = tuple(float(x) for x in geo.distance_km[origin])
        travel = tuple(60 * x / config.speed_kmh for x in distance)
        request = Request(
            f"{config.seed}-{index}",
            at,
            origin,
            energy,
            maximum,
            battery,
            travel,
            distance,
        )
        output.append((request, bool(random.random() < config.background_fraction)))
        index += 1
    if config.case in ("burst", "combined") and config.burst_requests:
        burst_random = rng(config.seed, "exogenous_simultaneous_burst")
        for day in range(max(1, int(np.ceil(config.measure_minutes / 1440.0)))):
            width = min(1440.0, config.measure_minutes - 1440.0 * day)
            for wave, fraction in enumerate((0.25, 0.75)):
                issued = config.warmup_minutes + 1440.0 * day + fraction * width
                for j in range(config.burst_requests):
                    origin = int(burst_random.integers(len(geo.origin_nodes)))
                    energy = float(
                        np.clip(
                            burst_random.lognormal(
                                np.log(config.energy_mean_kwh) - 0.5 * sd * sd, sd
                            ),
                            2.0,
                            50.0,
                        )
                    )
                    battery = float(
                        burst_random.uniform(
                            max(config.reserve_kwh, 5.0), config.battery_kwh - 2.0
                        )
                    )
                    distance = tuple(float(x) for x in geo.distance_km[origin])
                    travel = tuple(60 * x / config.speed_kmh for x in distance)
                    req = Request(
                        f"{config.seed}-burst-{day}-{wave}-{j}",
                        issued,
                        origin,
                        min(energy, config.battery_kwh - battery),
                        float(burst_random.choice([60.0, 120.0, 250.0])),
                        battery,
                        travel,
                        distance,
                    )
                    output.append(
                        (req, bool(burst_random.random() < config.background_fraction))
                    )
    return tuple(sorted(output, key=lambda x: (x[0].issued_at, x[0].request_id)))


def exogenous_hash(requests: tuple[tuple[Request, bool], ...]) -> str:
    return hashlib.sha256(
        json.dumps([(asdict(r), b) for r, b in requests], sort_keys=True).encode()
    ).hexdigest()


class Simulation:
    def __init__(
        self,
        geo: Geography,
        calibration: Calibration,
        config: Config,
        parameters: np.ndarray | None = None,
        trace_directory: Path | None = None,
    ):
        self.geo = geo
        self.calibration = calibration
        self.config = config
        self.physical = [
            ChargingStation(
                i,
                tuple(p * config.capacity_factor for p in x.powers),
                config.efficiency,
            )
            for i, x in enumerate(geo.stations)
        ]
        priors = tuple(
            replace(x, powers=self.physical[i].powers)
            for i, x in enumerate(calibration.priors)
        )
        self.stores = [
            InformationStore(
                i, priors, calibration.request_rates, config.method != "No-P2P"
            )
            for i in range(len(geo.stations))
        ]
        self.predictor = QueuePredictor(config, calibration)
        self.policy = RecommendationPolicy(
            config,
            self.predictor,
            (
                np.zeros(parameter_count(config.method))
                if parameters is None
                else parameters
            ),
        )
        self.events = []
        self.counter = 0
        self.outcomes: dict[str, DemandOutcome] = {}
        self.trace = []
        self.recommendations = []
        self.message_trace = []
        self.packet_trace = []
        self.record_logs = []
        if trace_directory is not None:
            for attribute, name in (
                ("trace", "events"),
                ("recommendations", "recommendations"),
                ("message_trace", "messages"),
                ("packet_trace", "packets"),
            ):
                stream = RecordLog(trace_directory / (name + ".jsonl.gz"))
                setattr(self, attribute, stream)
                self.record_logs.append(stream)
        self.requests = {}
        self.seconds = 0.0
        self.recommendation_times = []
        self.messages = 0
        self.delivered_messages = 0
        self.lost = 0
        self.bytes = 0
        self.event_count = 0
        self.measured_peaks = [0] * len(geo.stations)
        self.busy = [0.0] * len(geo.stations)

    def close_logs(self) -> None:
        for stream in self.record_logs:
            stream.close()

    def schedule(self, at: float, priority: int, kind: str, data: object) -> None:
        self.counter += 1
        heapq.heappush(self.events, (at, priority, self.counter, kind, data))

    def log(self, kind: str, at: float, rid: str, **fields) -> None:
        if self.config.trace:
            self.trace.append({"event": kind, "at": at, "request_id": rid, **fields})

    def send(self, sender: int, at: float) -> None:
        if self.config.method == "No-P2P":
            return
        config = self.config
        packet = self.stores[sender].packet(
            self.physical[sender].snapshot(
                at, config.snapshot_width_minutes, config.queue_energy_width_kwh
            ),
            at,
        )
        if config.trace:
            self.packet_trace.append(asdict(packet))
        payload_bytes = len(json.dumps(asdict(packet), separators=(",", ":")).encode())
        for receiver in range(len(self.stores)):
            if receiver == sender:
                continue
            random = rng(config.seed, "network", sender, packet.sequence, receiver)
            delay = (
                float(random.exponential(config.delay_minutes))
                if config.delay_minutes
                else 0.0
            )
            lost = bool(random.random() < config.packet_loss)
            self.messages += 1
            self.bytes += payload_bytes
            if lost:
                self.lost += 1
            else:
                self.schedule(at + delay, 1, "delivery", (receiver, packet))
            if config.trace:
                self.message_trace.append(
                    {
                        "sender": sender,
                        "receiver": receiver,
                        "sequence": packet.sequence,
                        "issued_at": at,
                        "deliver_at": None if lost else at + delay,
                        "bytes": payload_bytes,
                        "lost": lost,
                    }
                )

    def _start(self, station: int, at: float) -> None:
        physical = self.physical[station]
        for port, job, wait in physical.start_ready(at):
            outcome = self.outcomes[job.request_id]
            outcome.start_at = at
            self.schedule(job.finish, 0, "finish", (station, port, job.generation))
            self.log(
                "service_started", at, job.request_id, station=station, waiting_min=wait
            )
        if at >= self.config.warmup_minutes:
            self.measured_peaks[station] = max(
                self.measured_peaks[station], len(physical.queue)
            )

    def _busy(self, station: int, start: float, end: float) -> None:
        lower = self.config.warmup_minutes
        upper = lower + self.config.measure_minutes
        self.busy[station] += max(0.0, min(end, upper) - max(start, lower))

    def _request(self, request: Request, background: bool) -> None:
        config = self.config
        at = request.issued_at
        if request.request_id in self.outcomes:
            if (
                replace(request, issued_at=self.requests[request.request_id].issued_at)
                != self.requests[request.request_id]
            ):
                raise ValueError("Retry changed immutable demand context")
            self.log("retry", at, request.request_id)
            return
        self.requests[request.request_id] = request
        outcome = DemandOutcome(
            request.request_id,
            at,
            request.energy_kwh,
            at + config.deadline_minutes,
            config.warmup_minutes
            <= at
            < config.warmup_minutes + config.measure_minutes,
            background,
        )
        self.outcomes[request.request_id] = outcome
        feasible = np.array(
            [
                np.isfinite(t)
                and t <= config.max_travel_minutes
                and request.battery_available_kwh - config.consumption_kwh_km * d
                >= config.reserve_kwh
                for t, d in zip(request.travel, request.distance_km)
            ]
        )
        self.log(
            "request",
            at,
            request.request_id,
            energy_kwh=request.energy_kwh,
            background=background,
            origin=request.origin,
            battery_available_kwh=request.battery_available_kwh,
            max_kw=request.max_kw,
            travel=request.travel,
            distance_km=request.distance_km,
        )
        self.schedule(outcome.deadline, 4, "deadline", request.request_id)
        if not feasible.any():
            outcome.status = "failed"
            outcome.end_at = at
            self.log("failed", at, request.request_id)
            return
        issuer = int(np.argmin(np.where(feasible, request.distance_km, np.inf)))
        recommendation = None
        if not background:
            store = self.stores[issuer]
            store.record_request(at)
            observation = store.observe(
                self.physical[issuer].snapshot(at), at, config.exposure_ttl_minutes
            )
            begin = perf_counter()
            recommendation = self.policy.recommend(observation, request, feasible)
            if outcome.measured:
                self.recommendation_times.append(perf_counter() - begin)
            outcome.recommended = recommendation.station
            if recommendation.station is not None:
                store.record_exposure(
                    request,
                    recommendation.station,
                    tuple(
                        t if feasible[i] else -1.0 for i, t in enumerate(request.travel)
                    ),
                    config.exposure_ttl_minutes,
                )
                self.send(issuer, at)
            if config.trace:
                self.recommendations.append(
                    {
                        "request_id": request.request_id,
                        "issued_at": at,
                        "issuer": issuer,
                        **asdict(recommendation),
                    }
                )
            self.log(
                "recommendation", at, request.request_id, station=recommendation.station
            )
        choice = driver_choice(request, outcome.recommended, config, feasible)
        if choice is None:
            outcome.status = "deferred"
            outcome.end_at = at
            self.log("deferred", at, request.request_id)
            return
        outcome.station = choice
        noise = float(
            rng(config.seed, "travel", request.request_id).uniform(0.85, 1.15)
        )
        outcome.travel_minutes = request.travel[choice] * noise
        if recommendation is not None:
            outcome.predicted_wait = recommendation.forecasts[choice].mean
        self.log(
            "choice",
            at,
            request.request_id,
            station=choice,
            travel_minutes=outcome.travel_minutes,
        )
        self.schedule(at + outcome.travel_minutes, 3, "arrival", request.request_id)

    def run(self) -> dict:
        begin = perf_counter()
        config = self.config
        requests = generate_requests(self.geo, config)
        for request, background in requests:
            self.schedule(request.issued_at, 2, "request", (request, background))
        end = config.warmup_minutes + config.measure_minutes + config.deadline_minutes
        if config.method != "No-P2P":
            for sid in range(len(self.physical)):
                self.schedule(0.0, 5, "publish", sid)
        while self.events:
            at, _, _, kind, data = heapq.heappop(self.events)
            if at > end + 1e-9:
                break
            self.event_count += 1
            if kind == "request":
                self._request(*data)
            elif kind == "delivery":
                receiver, packet = data
                accepted = self.stores[receiver].receive(packet, at)
                if accepted:
                    self.delivered_messages += 1
            elif kind == "publish":
                self.send(data, at)
                if at + config.packet_interval_minutes <= end:
                    self.schedule(
                        at + config.packet_interval_minutes, 5, "publish", data
                    )
            elif kind == "arrival":
                outcome = self.outcomes[data]
                if outcome.status != "pending":
                    continue
                request = self.requests[data]
                outcome.travel_energy_kwh = (
                    config.consumption_kwh_km * request.distance_km[outcome.station]
                )
                outcome.arrival_battery_kwh = (
                    request.battery_available_kwh - outcome.travel_energy_kwh
                )
                if outcome.arrival_battery_kwh < 0:
                    outcome.status = "stranded"
                    outcome.end_at = at
                    outcome.final_battery_kwh = 0.0
                    self.log("stranded", at, data, station=outcome.station)
                    continue
                outcome.arrival_at = at
                self.physical[outcome.station].enqueue(
                    data, at, request.energy_kwh, request.max_kw
                )
                self.log("arrival", at, data, station=outcome.station)
                self._start(outcome.station, at)
            elif kind == "finish":
                sid, port, generation = data
                job = self.physical[sid].finish(port, generation, at)
                if job is None:
                    continue
                outcome = self.outcomes[job.request_id]
                if outcome.status != "pending":
                    raise ValueError("Terminal outcome resurrected")
                outcome.status = "completed"
                outcome.delivered_kwh = job.energy
                outcome.final_battery_kwh = outcome.arrival_battery_kwh + job.energy
                outcome.end_at = at
                self._busy(sid, job.start, at)
                self.log(
                    "service_completed",
                    at,
                    job.request_id,
                    station=sid,
                    energy_kwh=job.energy,
                )
                self._start(sid, at)
            elif kind == "deadline":
                outcome = self.outcomes[data]
                if outcome.status != "pending":
                    continue
                if outcome.arrival_at is None and outcome.station is not None:
                    request = self.requests[data]
                    fraction = min(
                        1.0,
                        max(0.0, at - outcome.issued_at)
                        / max(1e-12, outcome.travel_minutes),
                    )
                    outcome.travel_energy_kwh = (
                        fraction
                        * config.consumption_kwh_km
                        * request.distance_km[outcome.station]
                    )
                    outcome.travel_minutes = min(
                        outcome.travel_minutes, at - outcome.issued_at
                    )
                    outcome.final_battery_kwh = (
                        request.battery_available_kwh - outcome.travel_energy_kwh
                    )
                if outcome.station is not None:
                    physical = self.physical[outcome.station]
                    active = next(
                        (
                            j
                            for j in physical.active
                            if j is not None and j.request_id == data
                        ),
                        None,
                    )
                    if active is not None:
                        self._busy(outcome.station, active.start, at)
                    outcome.delivered_kwh = physical.cancel(data, at)
                    if outcome.arrival_battery_kwh is not None:
                        outcome.final_battery_kwh = (
                            outcome.arrival_battery_kwh + outcome.delivered_kwh
                        )
                    self._start(outcome.station, at)
                outcome.status = "unserved"
                outcome.end_at = at
                self.log("unserved", at, data, delivered_kwh=outcome.delivered_kwh)
        if any(x.status == "pending" for x in self.outcomes.values()):
            raise ValueError("Run ended before settlement")
        self.seconds = perf_counter() - begin
        utilization = [
            self.busy[i] / (len(s.powers) * config.measure_minutes)
            for i, s in enumerate(self.physical)
        ]
        result = summarize(
            list(self.outcomes.values()),
            config.deadline_minutes,
            max(self.measured_peaks, default=0),
            sum(len(s.powers) for s in self.physical),
            utilization,
            self.seconds,
            {
                "method": config.method,
                "case": config.case,
                "seed": config.seed,
                "exogenous_hash": exogenous_hash(requests),
                "messages_sent": self.messages,
                "messages_received": self.delivered_messages,
                "messages_lost": self.lost,
                "communication_bytes": self.bytes,
                "duplicates_or_out_of_order": sum(s.duplicates for s in self.stores),
                "events": self.event_count,
                "events_per_second": self.event_count / max(1e-9, self.seconds),
                "prediction_calls": (
                    self.predictor.calls if config.method != "No-Prediction" else 0
                ),
                "waiting_estimator_calls": self.predictor.calls,
                "prediction_seconds": self.predictor.seconds,
                "scenario_jobs": self.predictor.scenario_events,
                "recommendation_mean_ms": (
                    float(np.mean(self.recommendation_times)) * 1000
                    if self.recommendation_times
                    else None
                ),
                "recommendation_p95_ms": (
                    float(np.quantile(self.recommendation_times, 0.95)) * 1000
                    if self.recommendation_times
                    else None
                ),
            },
        )
        return result
