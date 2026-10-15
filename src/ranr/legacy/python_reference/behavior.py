"""Reaction kernels: the assumed model and private driver choices are distinct."""

from __future__ import annotations
import numpy as np
from functools import lru_cache
from .config import Config
from .randomness import rng
from .records import Request


def base_probabilities(
    travel: tuple[float, ...] | np.ndarray, preferences: np.ndarray | None = None
) -> np.ndarray:
    travel = np.asarray(travel, dtype=float)
    valid = np.isfinite(travel) & (travel >= 0)
    logits = -np.where(valid, travel, 0.0) / 15.0
    if preferences is not None:
        logits = logits + preferences
    values = np.zeros(len(travel))
    if valid.any():
        values[valid] = np.exp(logits[valid] - logits[valid].max())
        values /= values.sum()
    return values


@lru_cache(maxsize=4096)
def reaction_kernel(
    travel: tuple[float, ...], compliance: float, defer: float
) -> np.ndarray:
    """Rows are recommendations; last column is action 0 (outside/deferred)."""
    base = base_probabilities(travel)
    n = len(base)
    kernel = np.tile(np.r_[(1 - defer) * (1 - compliance) * base, defer], (n, 1))
    for r in range(n):
        kernel[r, r] += (1 - defer) * compliance
    kernel.flags.writeable = False
    return kernel


def driver_choice(
    request: Request, recommended: int | None, config: Config, feasible: np.ndarray
) -> int | None:
    random = rng(config.seed, "driver", request.request_id)
    # These private preference draws never enter StationObservation/Request.
    preferences = random.normal(0.0, 0.5, len(feasible))
    uniform = random.random(3)
    if uniform[0] < config.defer_probability:
        return None
    if recommended is not None and uniform[1] < config.compliance:
        return recommended
    probabilities = base_probabilities(
        np.where(feasible, request.travel, -1.0), preferences
    )
    if probabilities.sum() == 0:
        return None
    return int(np.searchsorted(np.cumsum(probabilities), uniform[2], side="right"))
