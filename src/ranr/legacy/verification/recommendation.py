"""Independent physical-event reference for recommendation, never called by GAMA.

Times are minutes, energy kWh, workload equivalent reference service-minutes.
Forecasts use ONLY closed historical bins; scenarios retain individual sessions.
"""

from dataclasses import dataclass
import math
import numpy as np


@dataclass(frozen=True)
class Alternative:
    station: int
    travel: float
    distance: float
    energy: float
    waiting: float


def recommend(alternatives, normalization="feasible", method="minimax", weights=None):
    if not alternatives:
        return None, {}
    values = np.array(
        [[a.travel, a.distance, a.energy, a.waiting] for a in alternatives], dtype=float
    )
    if not np.isfinite(values).all() or (values < 0).any():
        raise ValueError("Criteria must be finite and nonnegative")
    # Physical-unit tolerances, only to absorb floating-point noise.
    eps = np.array([1e-9, 1e-9, 1e-10, 1e-9])
    pareto = np.array(
        [
            not any(
                np.all(values[j] <= v + eps) and np.any(values[j] < v - eps)
                for j in range(len(values))
                if j != i
            )
            for i, v in enumerate(values)
        ]
    )
    base = values if normalization == "feasible" else values[pareto]
    if normalization not in ("feasible", "pareto"):
        raise ValueError("Unknown normalization")
    width = np.ptp(base, axis=0)
    regrets = np.divide(
        values - base.min(axis=0), width, out=np.zeros_like(values), where=width > eps
    )
    if method == "minimax":
        scores = regrets.max(axis=1)
    elif method in ("nearest", "eta", "time_wait"):
        scores = (
            values[:, 1]
            if method == "nearest"
            else (values[:, 0] if method == "eta" else values[:, 0] + values[:, 3])
        )
    elif method in ("weighted_sum", "monetary"):
        if (
            weights is None
            or len(weights) != 4
            or min(weights) < 0
            or sum(weights) <= 0
        ):
            raise ValueError("Explicit nonnegative four-component weights required")
        scores = (regrets if method == "weighted_sum" else values) @ np.array(weights)
    else:
        raise ValueError("Unknown score method")
    indices = (
        np.arange(len(values))
        if method in ("nearest", "eta")
        else np.flatnonzero(pareto)
    )
    best_score = min(scores[indices])
    tied = [i for i in indices if scores[i] <= best_score + 1e-10]
    best = min(
        tied,
        key=lambda i: (
            0 if method in ("nearest", "eta") else values[i, 0] + values[i, 3],
            alternatives[i].station,
        ),
    )
    return alternatives[best].station, {
        "pareto": pareto.tolist(),
        "regrets": regrets.tolist(),
        "scores": scores.tolist(),
    }


def shadow_wait(rates, free_at, arrivals, eta, efficiency=0.9, tick=1 / 60):
    """Independent heap event simulation; probe follows existing arrivals at equal ETA.

    Initial free_at already includes physical FIFO jobs. Arrivals: (offset, kWh).
    Probe requires no service allocation: only its start is queried.
    """
    import heapq

    if not rates:
        return math.inf
    servers = [(float(t), -float(p), i) for i, (p, t) in enumerate(zip(rates, free_at))]
    heapq.heapify(servers)
    ready = []
    for at, energy in sorted(arrivals, key=lambda a: a[0]):
        if at > eta + 1e-10:
            break
        arrival_tick = tick * math.ceil(at / tick - 1e-10)
        while servers and servers[0][0] <= arrival_tick + 1e-10:
            _, negative_power, i = heapq.heappop(servers)
            heapq.heappush(ready, (negative_power, i))
        if ready:
            negative_power, i = heapq.heappop(ready)
            release = arrival_tick
        else:
            release, negative_power, i = heapq.heappop(servers)
        begin = max(release, arrival_tick)
        duration = tick * max(
            1, math.ceil((60 * energy / (efficiency * -negative_power)) / tick - 1e-10)
        )
        heapq.heappush(servers, (begin + duration, negative_power, i))
    return 0.0 if ready else max(0.0, servers[0][0] - eta)


class LocalForecast:
    def __init__(self, width=5.0, window=12, min_bins=24, min_sessions=20):
        self.width, self.window = width, window
        self.min_bins, self.min_sessions = min_bins, min_sessions
        self.events = []

    def observe(self, at, energy):
        if at < 0 or energy < 0:
            raise ValueError("Invalid arrival")
        self.events.append((at, energy))

    def bins(self, issued):
        count = int(math.floor(issued / self.width + 1e-10))
        result = np.zeros(count)
        for at, energy in self.events:
            index = int(at / self.width)
            if at < issued and index < count:
                result[index] += 60 * energy / (0.9 * 60)
        return result

    def predict(self, issued, horizon):
        past = self.bins(issued)
        return np.full(horizon, np.mean(past[-self.window :]) if len(past) else 0.0)

    def scenarios(self, issued, forecast, count=20, threshold=None):
        bins = self.bins(issued)
        historical = [(t, e) for t, e in self.events if t < len(bins) * self.width]
        if len(bins) < self.min_bins or len(historical) < self.min_sessions:
            return [], {"status": "cold_start", "error": None}
        h = len(forecast)
        windows = []
        for start in range(max(0, len(bins) - 576), len(bins) - h + 1):
            loads = bins[start : start + h]
            scale = max(1.0, float(np.mean(bins[-self.window :])))
            error = float(np.sqrt(np.mean(((loads - forecast) / scale) ** 2)))
            begin, end = start * self.width, (start + h) * self.width
            sessions = [(t - begin, e) for t, e in historical if begin <= t < end]
            windows.append((error, start, sessions))
        if not windows:
            return [], {"status": "insufficient_horizon", "error": None}
        if threshold is None:
            return [], {
                "status": "ood_threshold_not_calibrated",
                "error": windows[0][0],
            }
        windows.sort(key=lambda w: (w[0], w[1]))
        accepted = [w for w in windows if w[0] <= threshold][:count]
        return [w[2] for w in accepted], {
            "status": "replay" if accepted else "out_of_distribution",
            "error": windows[0][0],
            "count": len(accepted),
        }


class RidgeCorrection:
    """Online ridge on stored, issued features; caller closes labels before observe.

    Feature scaling is frozen from development config, not recomputed inconsistently
    over sufficient statistics. No current neighbor state is read here.
    """

    def __init__(self, features, penalty=1.0, min_samples=None):
        self.p = features
        self.a = np.eye(features) * penalty
        self.b = np.zeros(features)
        self.samples = 0
        self.min_samples = max(50, 5 * features) if min_samples is None else min_samples

    def predict(self, features):
        return (
            float(np.asarray(features) @ np.linalg.solve(self.a, self.b))
            if self.samples >= self.min_samples
            else 0.0
        )

    def observe(self, features, residual):
        features = np.asarray(features)
        self.a += np.outer(features, features)
        self.b += features * residual
        self.samples += 1
