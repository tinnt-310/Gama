"""Scenario queue estimates from observations only, with paired externality."""

from __future__ import annotations
from dataclasses import replace
from time import perf_counter
import numpy as np
from .behavior import base_probabilities, reaction_kernel
from .calibration import Calibration
from .config import Config, PolicySettings
from .randomness import rng
from .native import run_queue
from .records import QueueEstimate, Request, StationObservation, StationSnapshot


def _dispatch_batch(
    free: np.ndarray,
    powers: np.ndarray,
    arrival: np.ndarray,
    energy: np.ndarray,
    max_kw: np.ndarray,
    last: np.ndarray,
    efficiency: float,
) -> np.ndarray:
    starts = np.maximum(free, np.maximum(arrival, last)[:, None])
    begin = starts.min(axis=1)
    rates = np.minimum(powers[None, :], max_kw[:, None])
    priority = np.where(
        starts <= begin[:, None] + 1e-10, rates - np.arange(len(powers)) * 1e-9, -1.0
    )
    selected = priority.argmax(axis=1)
    rows = np.arange(len(free))
    free[rows, selected] = begin + 60.0 * energy / (efficiency * rates[rows, selected])
    return begin


def batch_queue(
    free: np.ndarray,
    powers: np.ndarray,
    arrivals: np.ndarray,
    energies: np.ndarray,
    maximum: np.ndarray,
    efficiency: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Row scenarios, column jobs. Infinite arrival denotes absence, not a job."""
    native = run_queue(free, powers, arrivals, energies, maximum, efficiency)
    if native is not None:
        return native
    starts = np.zeros_like(arrivals)
    last = np.zeros(len(free))
    wait = np.zeros(len(free))
    for column in range(arrivals.shape[1]):
        present = np.isfinite(arrivals[:, column])
        rows = np.flatnonzero(present)
        if not len(rows):
            continue
        part = free[rows].copy()
        begin = _dispatch_batch(
            part,
            powers,
            arrivals[rows, column],
            energies[rows, column],
            maximum[rows, column],
            last[rows],
            efficiency,
        )
        free[rows] = part
        last[rows] = begin
        starts[rows, column] = begin
        wait[rows] += begin - arrivals[rows, column]
    return starts, wait


class QueuePredictor:
    def __init__(self, config: Config | PolicySettings, calibration: Calibration):
        self.config = config.policy_settings if isinstance(config, Config) else config
        self.calibration = calibration
        self.release_fractions = np.asarray(calibration.release_fractions)
        self.energy_fractions = np.asarray(calibration.energy_fractions)
        self.energy_samples = np.asarray(calibration.energy_samples)
        self.destination_cache = {}
        self.travel_priors = tuple(
            np.asarray(group) for group in calibration.travel_priors
        )
        self.prior_arrays = []
        for pool in calibration.prior_snapshots:
            lower = np.array([[r.low for r in snap.release] for snap in pool])
            width = np.array([[r.high - r.low for r in snap.release] for snap in pool])
            columns = max(len(snap.queue) for snap in pool)
            arrivals = np.full((len(pool), columns), np.inf)
            energy = np.zeros_like(arrivals)
            energy_width = np.zeros_like(arrivals)
            maximum = np.full_like(arrivals, 120.0)
            for i, snap in enumerate(pool):
                for j, job in enumerate(snap.queue):
                    arrivals[i, j] = 0.0
                    energy[i, j] = job.energy.low
                    energy_width[i, j] = job.energy.high - job.energy.low
                    maximum[i, j] = job.max_kw
            self.prior_arrays.append(
                (lower, width, arrivals, energy, energy_width, maximum)
            )
        self.calls = 0
        self.seconds = 0.0
        self.scenario_events = 0

    def _prior_initial(
        self,
        station: int,
        selected: np.ndarray,
        random: np.random.Generator,
        powers: np.ndarray,
    ) -> np.ndarray:
        lower, width, arrivals, energy, energy_width, maximum = self.prior_arrays[
            station
        ]
        free = lower[selected] + width[selected] * random.choice(
            self.release_fractions, size=(len(selected), len(powers))
        )
        if arrivals.shape[1]:
            values = energy[selected] + energy_width[selected] * random.choice(
                self.energy_fractions, size=(len(selected), arrivals.shape[1])
            )
            batch_queue(
                free,
                powers,
                arrivals[selected],
                values,
                maximum[selected],
                self.config.efficiency,
            )
        return free

    def _initial(
        self, snapshots: list[StationSnapshot], random: np.random.Generator
    ) -> np.ndarray:
        s = len(snapshots)
        p = len(snapshots[0].powers)
        free = np.empty((s, p))
        if all(x is snapshots[0] for x in snapshots):
            lower = np.array([x.low for x in snapshots[0].release])
            width = np.array([x.high - x.low for x in snapshots[0].release])
            free = lower[None, :] + width[None, :] * random.choice(
                self.release_fractions, size=(s, p)
            )
            if snapshots[0].queue:
                queue = snapshots[0].queue
                lower = np.array([job.energy.low for job in queue])
                width = np.array([job.energy.high - job.energy.low for job in queue])
                energy = lower[None, :] + width[None, :] * random.choice(
                    self.energy_fractions, size=(s, len(queue))
                )
                maximum = np.tile([job.max_kw for job in queue], (s, 1))
                batch_queue(
                    free,
                    np.asarray(snapshots[0].powers),
                    np.zeros_like(energy),
                    energy,
                    maximum,
                    self.config.efficiency,
                )
            return free
        else:
            for row, snap in enumerate(snapshots):
                quantile = random.choice(self.release_fractions, size=p)
                free[row] = [
                    x.low + (x.high - x.low) * q for x, q in zip(snap.release, quantile)
                ]
        n = max(len(x.queue) for x in snapshots)
        if n:
            arrivals = np.full((s, n), np.inf)
            energy = np.zeros((s, n))
            maximum = np.full((s, n), 120.0)
            for row, snap in enumerate(snapshots):
                for j, job in enumerate(snap.queue):
                    arrivals[row, j] = 0.0
                    energy[row, j] = job.energy.low + (
                        job.energy.high - job.energy.low
                    ) * random.choice(self.energy_fractions)
                    maximum[row, j] = job.max_kw
            batch_queue(
                free,
                np.asarray(snapshots[0].powers),
                arrivals,
                energy,
                maximum,
                self.config.efficiency,
            )
        return free

    def _append_requests(
        self,
        observation,
        request,
        samples,
        issuer,
        rate,
        begin,
        end,
        namespace,
        participating,
        times,
        energies,
        maximum,
    ):
        config = self.config
        n = len(observation.snapshots)
        if end <= begin or rate <= 0:
            return
        capacities = tuple(sum(snap.powers) for snap in observation.snapshots)
        key = (issuer, participating, capacities)
        if key not in self.destination_cache:
            if self.travel_priors and len(self.travel_priors[issuer]):
                bank = self.travel_priors[issuer]
                prior = np.where(
                    bank <= config.max_travel_minutes,
                    np.asarray(capacities) / (1 + bank / 30.0),
                    0.0,
                )
                prior = np.divide(
                    prior,
                    prior.sum(axis=1, keepdims=True),
                    out=np.zeros_like(prior),
                    where=prior.sum(axis=1, keepdims=True) > 0,
                )
                personal = np.where(
                    bank <= config.max_travel_minutes, np.exp(-bank / 15.0), 0.0
                )
                personal = np.divide(
                    personal,
                    personal.sum(axis=1, keepdims=True),
                    out=np.zeros_like(personal),
                    where=personal.sum(axis=1, keepdims=True) > 0,
                )
                compliance = config.assumed_compliance if participating else 0.0
                actual = (1 - config.defer_probability) * (
                    compliance * prior + (1 - compliance) * personal
                )
                mass = actual.mean(axis=0)
                conditional = []
                for m in range(n):
                    weights = actual[:, m]
                    cdf = (
                        np.cumsum(weights / weights.sum())
                        if weights.sum() > 0
                        else np.array([])
                    )
                    if len(cdf):
                        cdf[-1] = 1.0
                    conditional.append(cdf)
                self.destination_cache[key] = (mass, conditional)
            else:
                self.destination_cache[key] = (np.full(n, 1 / n), None)
        mass, conditional = self.destination_cache[key]
        # Exact marked-Poisson splitting: destination counts are independent,
        # conditional origin marks retain their original law. Known fixed-size
        # exposure cohorts deliberately do not use this optimization.
        for m in range(n):
            random = rng(
                config.seed,
                "forecast_" + namespace + "_split",
                request.request_id,
                issuer,
                m,
            )
            count = random.poisson(rate * (end - begin) * mass[m], size=samples)
            columns = int(count.max(initial=0))
            if not columns:
                continue
            mask = np.arange(columns)[None, :] < count[:, None]
            issue = random.uniform(begin, end, (samples, columns))
            if conditional is not None:
                origin = np.searchsorted(
                    conditional[m], random.random((samples, columns)), side="right"
                )
                travel = self.travel_priors[issuer][origin, m] * random.uniform(
                    0.85, 1.15, (samples, columns)
                )
            else:
                travel = random.uniform(
                    0.0, config.max_travel_minutes, (samples, columns)
                )
            energy = random.choice(self.energy_samples, (samples, columns))
            times[m].append(np.where(mask, issue + travel, np.inf))
            energies[m].append(energy)
            maximum[m].append(np.full_like(energy, 120.0))

    def _future(
        self, observation: StationObservation, request: Request, samples: int
    ) -> tuple[list[np.ndarray], list[np.ndarray], list[np.ndarray]]:
        """One sampled destination per cohort member in every scenario."""
        config = self.config
        n = len(observation.snapshots)
        times = [[] for _ in range(n)]
        energies = [[] for _ in range(n)]
        maximum = [[] for _ in range(n)]
        for exposure in observation.exposure:
            earliest_epoch = min(
                observation.at if x.source == "prior" else x.issued_at
                for x in observation.snapshots
            )
            if exposure.issued_at + max(exposure.travel) * 1.15 < earliest_epoch:
                continue  # every modeled arrival predates every physical snapshot
            random = rng(
                config.seed, "forecast_exposure", request.request_id, exposure.key
            )
            kernel = reaction_kernel(
                exposure.travel, config.assumed_compliance, config.defer_probability
            )[exposure.recommended]
            choices = np.searchsorted(
                np.cumsum(kernel),
                random.random((samples, exposure.count)),
                side="right",
            )
            jitter = random.uniform(0.85, 1.15, (samples, exposure.count))
            for m in range(n):
                if exposure.travel[m] < 0:
                    continue
                at = exposure.issued_at + exposure.travel[m] * jitter
                times[m].append(np.where(choices == m, at, np.inf))
                energies[m].append(np.full_like(at, exposure.energy))
                maximum[m].append(np.full_like(at, exposure.max_kw))
        horizon = (
            observation.at
            + 1.15 * max(request.travel)
            + config.forecast_horizon_minutes
        )
        for issuer, rate in enumerate(observation.request_rates):
            # Past unreceived exposures and future unissued recommendations have
            # disjoint issuance intervals, and never reuse an observed cohort.
            begin = max(
                observation.watermarks[issuer],
                observation.at - config.exposure_ttl_minutes,
            )
            self._append_requests(
                observation,
                request,
                samples,
                issuer,
                rate,
                begin,
                observation.at,
                "unseen",
                True,
                times,
                energies,
                maximum,
            )
            self._append_requests(
                observation,
                request,
                samples,
                issuer,
                rate,
                observation.at,
                min(horizon, config.demand_closes_at),
                "unissued",
                True,
                times,
                energies,
                maximum,
            )
        if self.travel_priors:
            epoch = min(
                observation.at if snap.source == "prior" else snap.issued_at
                for snap in observation.snapshots
            )
            for issuer, rate in enumerate(self.calibration.request_rates):
                # Non-participants are an independent stream; account for travel
                # from already-issued background demand without physical IDs.
                self._append_requests(
                    observation,
                    request,
                    samples,
                    issuer,
                    rate * 0.25,
                    max(0.0, epoch - 1.15 * config.max_travel_minutes),
                    min(horizon, config.demand_closes_at),
                    "background",
                    False,
                    times,
                    energies,
                    maximum,
                )
        else:
            for m, snapshot in enumerate(observation.snapshots):
                epoch = (
                    observation.at if snapshot.source == "prior" else snapshot.issued_at
                )
                random = rng(config.seed, "forecast_background", request.request_id, m)
                count = random.poisson(
                    self.calibration.background_rates[m]
                    * max(0.0, min(horizon, config.demand_closes_at) - epoch),
                    size=samples,
                )
                columns = int(count.max(initial=0))
                if not columns:
                    continue
                at = random.uniform(
                    epoch, min(horizon, config.demand_closes_at), (samples, columns)
                )
                mask = np.arange(columns)[None, :] < count[:, None]
                times[m].append(np.where(mask, at, np.inf))
                energies[m].append(
                    random.choice(self.energy_samples, (samples, columns))
                )
                maximum[m].append(np.full_like(at, 120.0))
        result_t = []
        result_e = []
        result_m = []
        for m, snapshot in enumerate(observation.snapshots):
            epoch = observation.at if snapshot.source == "prior" else snapshot.issued_at
            if not times[m]:
                result_t.append(np.empty((samples, 0)))
                result_e.append(np.empty((samples, 0)))
                result_m.append(np.empty((samples, 0)))
                continue
            t = np.concatenate(times[m], axis=1)
            e = np.concatenate(energies[m], axis=1)
            power = np.concatenate(maximum[m], axis=1)
            t = np.where((t >= epoch) & (t <= horizon), t - epoch, np.inf)
            # Remove universally absent columns before sorting, without dropping real jobs.
            columns = np.isfinite(t).any(axis=0)
            t = t[:, columns]
            e = e[:, columns]
            power = power[:, columns]
            order = np.argsort(t, axis=1, kind="stable")
            # After row sorting, all real jobs occupy a finite prefix. Cutting
            # universal infinity suffixes retains every event in every scenario.
            width = int(np.isfinite(t).sum(axis=1).max(initial=0))
            order = order[:, :width]
            result_t.append(np.take_along_axis(t, order, axis=1))
            result_e.append(np.take_along_axis(e, order, axis=1))
            result_m.append(np.take_along_axis(power, order, axis=1))
        return result_t, result_e, result_m

    def estimate(
        self, observation: StationObservation, request: Request
    ) -> tuple[QueueEstimate, ...]:
        begin = perf_counter()
        config = self.config
        s = config.scenarios
        prediction = config.method != "No-Prediction"
        n = len(observation.snapshots)
        future = self._future(observation, request, s) if prediction else None
        output = []
        for m, snapshot in enumerate(observation.snapshots):
            random = rng(config.seed, "forecast_snapshot", request.request_id, m)
            powers = np.asarray(snapshot.powers)
            if snapshot.source == "prior":
                pool = self.calibration.prior_snapshots[m]
                free = self._prior_initial(
                    m, random.integers(0, len(pool), s), random, powers
                )
            else:
                free = self._initial([snapshot] * s, random)
            if not prediction:
                waits = free.min(axis=1)
                externality = None
            else:
                t, e, maximum = (x[m] for x in future)
                epoch = (
                    observation.at if snapshot.source == "prior" else snapshot.issued_at
                )
                eta = (
                    observation.at
                    + request.travel[m]
                    * rng(config.seed, "forecast_probe", request.request_id).uniform(
                        0.85, 1.15, s
                    )
                    - epoch
                )
                # Existing/future arrivals at the same timestamp precede probe.
                before = np.where(t <= eta[:, None], t, np.inf)
                after = np.where(t > eta[:, None], t, np.inf)
                columns = np.isfinite(before).any(axis=0)
                batch_queue(
                    free,
                    powers,
                    before[:, columns],
                    e[:, columns],
                    maximum[:, columns],
                    config.efficiency,
                )
                waits = np.maximum(0.0, free.min(axis=1) - eta)
                baseline = free.copy()
                inserted = free.copy()
                _dispatch_batch(
                    inserted,
                    powers,
                    eta,
                    np.full(s, request.energy_kwh),
                    np.full(s, request.max_kw),
                    np.zeros(s),
                    config.efficiency,
                )
                columns = np.isfinite(after).any(axis=0)
                _, paired = batch_queue(
                    np.vstack((baseline, inserted)),
                    powers,
                    np.vstack((after[:, columns], after[:, columns])),
                    np.vstack((e[:, columns], e[:, columns])),
                    np.vstack((maximum[:, columns], maximum[:, columns])),
                    config.efficiency,
                )
                without, with_probe = paired[:s], paired[s:]
                externality = float(np.mean(with_probe - without))
                self.scenario_events += int(np.isfinite(t).sum())
            age = (
                max(0.0, observation.at - snapshot.issued_at)
                if snapshot.source != "prior"
                else config.exposure_ttl_minutes
            )
            # Spread + an explicit age surcharge; age alone never fabricates jobs.
            uncertainty = float(np.std(waits)) + min(age, config.exposure_ttl_minutes)
            output.append(
                QueueEstimate(
                    float(waits.mean()),
                    float(np.quantile(waits, 0.95)),
                    externality,
                    uncertainty,
                    snapshot.source,
                )
            )
        self.calls += 1
        self.seconds += perf_counter() - begin
        return tuple(output)
