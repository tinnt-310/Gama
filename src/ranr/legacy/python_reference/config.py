"""Validated configurations; all time values are elapsed minutes."""

from __future__ import annotations
from dataclasses import asdict, dataclass, replace
import json
import math
from pathlib import Path

METHODS = ("RANR-AW", "No-P2P", "No-Prediction", "Fixed-Weights")
CASES = ("normal", "high", "burst", "low_compliance", "delayed", "combined")


@dataclass(frozen=True)
class PolicySettings:
    """Public/frozen algorithm settings; excludes true load and driver reaction."""

    method: str
    seed: int
    assumed_compliance: float
    defer_probability: float
    efficiency: float
    deadline_minutes: float
    forecast_horizon_minutes: float
    exposure_ttl_minutes: float
    max_travel_minutes: float
    scenarios: int
    temperature: float
    feature_scales: tuple[float, ...]
    demand_closes_at: float = math.inf


@dataclass(frozen=True)
class Config:
    method: str = "RANR-AW"
    case: str = "normal"
    seed: int = 1001
    warmup_minutes: float = 1440.0
    measure_minutes: float = 2880.0
    deadline_minutes: float = 360.0
    load: float = 0.6
    background_fraction: float = 0.2
    compliance: float = 0.8
    assumed_compliance: float = 0.6
    assumed_defer_probability: float = 0.05
    defer_probability: float = 0.05
    speed_kmh: float = 30.0
    efficiency: float = 0.9
    energy_mean_kwh: float = 20.0
    energy_sd_kwh: float = 8.0
    battery_kwh: float = 60.0
    consumption_kwh_km: float = 0.2
    reserve_kwh: float = 3.0
    packet_interval_minutes: float = 5.0
    delay_minutes: float = 0.5
    packet_loss: float = 0.0
    snapshot_width_minutes: float = 5.0
    queue_energy_width_kwh: float = 5.0
    forecast_horizon_minutes: float = 120.0
    exposure_ttl_minutes: float = 180.0
    max_travel_minutes: float = 120.0
    scenarios: int = 32
    temperature: float = 0.2
    feature_scales: tuple[float, ...] = (30.0, 60.0, 120.0, 120.0, 60.0)
    capacity_factor: float = 1.0
    burst_requests: int = 100
    trace: bool = True

    def __post_init__(self) -> None:
        if self.method not in METHODS or self.case not in CASES:
            raise ValueError("Unknown method or scenario")
        for name in (
            "load",
            "speed_kmh",
            "deadline_minutes",
            "measure_minutes",
            "efficiency",
            "energy_mean_kwh",
            "battery_kwh",
            "packet_interval_minutes",
            "forecast_horizon_minutes",
            "exposure_ttl_minutes",
            "temperature",
            "capacity_factor",
        ):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        for name in (
            "background_fraction",
            "compliance",
            "assumed_compliance",
            "assumed_defer_probability",
            "defer_probability",
            "packet_loss",
        ):
            if not 0 <= getattr(self, name) <= 1:
                raise ValueError(f"{name} outside [0,1]")
        for name in (
            "warmup_minutes",
            "delay_minutes",
            "snapshot_width_minutes",
            "queue_energy_width_kwh",
            "energy_sd_kwh",
            "reserve_kwh",
            "consumption_kwh_km",
        ):
            if not math.isfinite(getattr(self, name)) or getattr(self, name) < 0:
                raise ValueError(f"{name} must be nonnegative")
        if (
            self.efficiency > 1
            or self.scenarios < 1
            or self.burst_requests < 0
            or self.exposure_ttl_minutes < self.max_travel_minutes
        ):
            raise ValueError("Invalid efficiency, scenario count, or exposure TTL")
        if len(self.feature_scales) != 5 or any(
            x <= 0 or not math.isfinite(x) for x in self.feature_scales
        ):
            raise ValueError("Five positive criterion scales required")
        if any(
            not isinstance(x, int) or isinstance(x, bool)
            for x in (self.seed, self.scenarios, self.burst_requests)
        ):
            raise ValueError("Seed, scenarios and burst count must be integers")
        if self.battery_kwh <= max(self.reserve_kwh, 5.0) + 2.0:
            raise ValueError("Battery capacity is too small for the demand model")

    def for_case(self, case: str) -> Config:
        changes = {
            "case": case,
            "load": 0.6,
            "compliance": 0.8,
            "delay_minutes": 0.5,
            "packet_loss": 0.0,
        }
        if case == "high":
            changes["load"] = 0.9
        if case in ("low_compliance", "combined"):
            changes["compliance"] = 0.2
        if case in ("delayed", "combined"):
            changes["delay_minutes"] = 5.0
        if case == "combined":
            changes.update(load=0.9, packet_loss=0.1)
        return replace(self, **changes)

    @classmethod
    def read(cls, path: Path) -> Config:
        values = json.loads(path.read_text())
        if "feature_scales" in values:
            values["feature_scales"] = tuple(values["feature_scales"])
        return cls(**values)

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def policy_settings(self) -> PolicySettings:
        return PolicySettings(
            self.method,
            self.seed,
            self.assumed_compliance,
            self.assumed_defer_probability,
            self.efficiency,
            self.deadline_minutes,
            self.forecast_horizon_minutes,
            self.exposure_ttl_minutes,
            self.max_travel_minutes,
            self.scenarios,
            self.temperature,
            self.feature_scales,
            self.warmup_minutes + self.measure_minutes,
        )
