"""Immutable wire/observation types; no physical-agent references cross this boundary."""

from __future__ import annotations
from dataclasses import dataclass
from typing import Literal
import math


@dataclass(frozen=True)
class Interval:
    low: float
    high: float

    def __post_init__(self) -> None:
        import math

        if (
            not math.isfinite(self.low)
            or not math.isfinite(self.high)
            or self.low < 0
            or self.high < self.low
        ):
            raise ValueError("Invalid nonnegative observation interval")


@dataclass(frozen=True)
class QueueJob:
    energy: Interval
    max_kw: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.max_kw) or self.max_kw <= 0:
            raise ValueError("Queue job maximum power must be positive")


@dataclass(frozen=True)
class StationSnapshot:
    station: int
    issued_at: float
    powers: tuple[float, ...]
    release: tuple[Interval, ...]
    queue: tuple[QueueJob, ...]
    source: str = "local"

    def __post_init__(self) -> None:
        if (
            not self.powers
            or len(self.powers) != len(self.release)
            or any(not math.isfinite(p) or p <= 0 for p in self.powers)
        ):
            raise ValueError("Invalid snapshot port state")
        if (
            not math.isfinite(self.issued_at)
            or self.issued_at < 0
            or self.source not in ("local", "peer", "prior")
        ):
            raise ValueError("Invalid snapshot timestamp/source")


@dataclass(frozen=True)
class Exposure:
    issuer: int
    recommended: int
    context: str
    bin_index: int
    version: int
    issued_at: float
    expires_at: float
    count: int
    # Public cohort context; no IDs, actual outcomes or private preferences.
    travel: tuple[float, ...]
    energy: float
    max_kw: float

    @property
    def key(self) -> tuple:
        return self.issuer, self.recommended, self.context, self.bin_index


@dataclass(frozen=True)
class Packet:
    sender: int
    sequence: int
    issued_at: float
    snapshot: StationSnapshot
    exposure: tuple[Exposure, ...]
    request_rate: float

    def __post_init__(self) -> None:
        if (
            self.sender != self.snapshot.station
            or self.sequence < 1
            or self.request_rate < 0
            or not math.isfinite(self.request_rate)
        ):
            raise ValueError("Invalid peer packet")


@dataclass(frozen=True)
class Request:
    request_id: str
    issued_at: float
    origin: int
    energy_kwh: float
    max_kw: float
    battery_available_kwh: float
    travel: tuple[float, ...]
    distance_km: tuple[float, ...]


@dataclass(frozen=True)
class StationObservation:
    station: int
    at: float
    snapshots: tuple[StationSnapshot, ...]
    exposure: tuple[Exposure, ...]
    watermarks: tuple[float, ...]
    request_rates: tuple[float, ...]
    recent_requests: int
    information_available: tuple[bool, ...]


@dataclass(frozen=True)
class QueueEstimate:
    mean: float
    p95: float
    externality: float | None
    uncertainty: float
    source: str


@dataclass(frozen=True)
class RecommendationResult:
    station: int | None
    probabilities: tuple[float, ...]
    weights: tuple[float, ...]
    criteria: tuple[tuple[float, ...], ...]
    forecasts: tuple[QueueEstimate, ...]
    state_features: tuple[float, ...]


@dataclass
class DemandOutcome:
    request_id: str
    issued_at: float
    energy_kwh: float
    deadline: float
    measured: bool
    background: bool = False
    station: int | None = None
    recommended: int | None = None
    arrival_at: float | None = None
    start_at: float | None = None
    end_at: float | None = None
    delivered_kwh: float = 0.0
    travel_minutes: float = 0.0
    predicted_wait: float | None = None
    travel_energy_kwh: float = 0.0
    arrival_battery_kwh: float | None = None
    final_battery_kwh: float | None = None
    status: Literal[
        "pending", "completed", "failed", "stranded", "deferred", "unserved"
    ] = "pending"
