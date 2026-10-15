"""Common expected-reaction cost, trained weights and stochastic recommendation."""

from __future__ import annotations
import numpy as np
from scipy.special import softmax
from .behavior import reaction_kernel
from .config import Config, PolicySettings
from .prediction import QueuePredictor
from .randomness import rng
from .records import RecommendationResult, Request, StationObservation


def active_features(method: str) -> tuple[int, ...]:
    return (0, 1, 2, 4) if method == "No-Prediction" else (0, 1, 2, 3, 4)


def parameter_count(method: str) -> int:
    k = len(active_features(method))
    return k - 1 if method == "Fixed-Weights" else (k - 1) * 5


def trained_weights(
    method: str, parameters: np.ndarray, state: np.ndarray
) -> np.ndarray:
    k = len(active_features(method))
    parameters = np.asarray(parameters, dtype=float)
    if (
        parameters.shape != (parameter_count(method),)
        or not np.isfinite(parameters).all()
    ):
        raise ValueError("Invalid trained parameter shape/domain")
    logits = (
        np.r_[parameters, 0.0]
        if method == "Fixed-Weights"
        else np.vstack((parameters.reshape(k - 1, 5), np.zeros(5))) @ state
    )
    return softmax(logits)


class RecommendationPolicy:
    def __init__(
        self, config: Config, predictor: QueuePredictor, parameters: np.ndarray
    ):
        self.config = config.policy_settings if isinstance(config, Config) else config
        self.predictor = predictor
        self.parameters = np.asarray(parameters)

    def recommend(
        self, observation: StationObservation, request: Request, feasible: np.ndarray
    ) -> RecommendationResult:
        config = self.config
        if config.method == "No-P2P" and any(
            x
            for i, x in enumerate(observation.information_available)
            if i != observation.station
        ):
            raise ValueError("No-P2P received privileged peer state")
        n = len(request.travel)
        if not feasible.any():
            return RecommendationResult(
                None, tuple(0.0 for _ in range(n)), (), (), (), ()
            )
        # All state features depend only on received snapshots and local requests.
        loads = []
        ages = []
        for snap in observation.snapshots:
            load = sum((x.low + x.high) / 2 for x in snap.release) / max(
                1, len(snap.powers)
            )
            load += (
                sum((j.energy.low + j.energy.high) / 2 for j in snap.queue)
                * 60.0
                / (config.efficiency * max(1, sum(snap.powers)))
            )
            loads.append(load / 60.0)
            ages.append(
                config.exposure_ttl_minutes
                if snap.source == "prior"
                else observation.at - snap.issued_at
            )
        # State-only variance of outstanding categorical workload; independent of
        # the current EV's ETA and of the private true compliance parameter.
        variance = 0.0
        for exposure in observation.exposure:
            probabilities = reaction_kernel(
                exposure.travel, config.assumed_compliance, config.defer_probability
            )[exposure.recommended, :n]
            travel = np.asarray(exposure.travel)
            survival = np.divide(
                exposure.issued_at + 1.15 * travel - observation.at,
                0.3 * travel,
                out=np.where(exposure.issued_at + travel >= observation.at, 1.0, 0.0),
                where=travel > 0,
            )
            remaining = probabilities * np.clip(survival, 0.0, 1.0)
            workload = 60 * exposure.energy / (config.efficiency * 120.0)
            variance += (
                exposure.count
                * workload**2
                * max(0.0, remaining.sum() - np.square(remaining).sum())
            )
        unseen = sum(
            rate * min(config.exposure_ttl_minutes, max(0.0, observation.at - mark))
            for rate, mark in zip(observation.request_rates, observation.watermarks)
        )
        workload_squared = np.mean(
            np.square(self.predictor.energy_samples * 60 / (config.efficiency * 120.0))
        )
        variance += unseen * workload_squared
        behavior_uncertainty = min(
            1.0,
            np.sqrt(variance)
            / (
                config.feature_scales[4]
                * np.sqrt(sum(len(snap.powers) for snap in observation.snapshots))
            ),
        )
        state = np.r_[
            1.0,
            np.clip(np.mean(loads), 0.0, 1.0),
            min(1.0, observation.recent_requests / 10.0),
            behavior_uncertainty,
            min(1.0, np.mean(ages) / 15.0),
        ]
        weights = trained_weights(config.method, self.parameters, state)
        estimates = self.predictor.estimate(observation, request)
        features = np.array(
            [
                [
                    request.travel[m],
                    x.mean,
                    x.p95,
                    0.0 if x.externality is None else x.externality,
                    x.uncertainty,
                ]
                for m, x in enumerate(estimates)
            ]
        )
        if not np.isfinite(features).all():
            raise ValueError("Nonfinite prediction")
        features = np.clip(features / np.asarray(config.feature_scales), 0.0, 5.0)
        scores = features[:, active_features(config.method)] @ weights
        public_travel = tuple(
            t if feasible[m] else -1.0 for m, t in enumerate(request.travel)
        )
        kernel = reaction_kernel(
            public_travel, config.assumed_compliance, config.defer_probability
        )
        # J0 = 2D, normalized by the same minute scale as waiting.
        expected = kernel[:, :n] @ scores + kernel[:, -1] * (
            2 * config.deadline_minutes / config.feature_scales[1]
        )
        capacities = np.array([sum(snap.powers) for snap in observation.snapshots])
        prior = capacities / (1 + np.asarray(request.travel) / 30.0)
        logits = np.log(prior) - expected / config.temperature
        probabilities = np.zeros(n)
        probabilities[feasible] = softmax(logits[feasible])
        random = rng(config.seed, "recommendation", request.request_id)
        selected = int(random.choice(n, p=probabilities))
        return RecommendationResult(
            selected,
            tuple(float(x) for x in probabilities),
            tuple(float(x) for x in weights),
            tuple(tuple(float(v) for v in x) for x in features),
            estimates,
            tuple(float(x) for x in state),
        )
