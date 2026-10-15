"""Random streams keyed by exogenous identity, invariant to call/worker ordering."""

import hashlib
import numpy as np


def rng(seed: int, *keys: object) -> np.random.Generator:
    message = repr((int(seed), keys)).encode()
    words = np.frombuffer(
        hashlib.blake2b(message, digest_size=16).digest(), dtype="<u4"
    )
    return np.random.default_rng(np.random.SeedSequence(words.tolist()))
