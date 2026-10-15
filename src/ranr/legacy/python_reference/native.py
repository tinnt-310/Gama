"""Optional compiled numerical kernel, fingerprinted and reference-testable."""

from __future__ import annotations
import ctypes
import hashlib
import os
from pathlib import Path
import subprocess
import numpy as np
from .paths import OUTPUTS

_KERNEL = None


def kernel():
    global _KERNEL
    if os.environ.get("RANR_DISABLE_NATIVE") == "1":
        return None
    if _KERNEL is None:
        source = Path(__file__).with_name("_queue.cpp")
        identity = hashlib.sha256(
            source.read_bytes() + b"c++-O3-no-fast-math-v1"
        ).hexdigest()[:16]
        binary = OUTPUTS / ".cache" / f"fifo_{identity}.so"
        binary.parent.mkdir(parents=True, exist_ok=True)
        if not binary.exists():
            temporary = binary.with_name(binary.name + f".{os.getpid()}.tmp")
            subprocess.run(
                [
                    "c++",
                    "-O3",
                    "-std=c++17",
                    "-shared",
                    "-fPIC",
                    str(source),
                    "-o",
                    str(temporary),
                ],
                check=True,
                capture_output=True,
            )
            temporary.replace(binary)
        library = ctypes.CDLL(str(binary))
        function = library.fifo
        vector = np.ctypeslib.ndpointer(dtype=np.float64, flags="C_CONTIGUOUS")
        function.argtypes = [vector] * 7 + [ctypes.c_size_t] * 3 + [ctypes.c_double]
        function.restype = None
        _KERNEL = function
    return _KERNEL


def run_queue(
    free: np.ndarray,
    powers: np.ndarray,
    arrivals: np.ndarray,
    energy: np.ndarray,
    maximum: np.ndarray,
    efficiency: float,
):
    if (
        free.ndim != 2
        or powers.shape != (free.shape[1],)
        or arrivals.ndim != 2
        or arrivals.shape[0] != free.shape[0]
        or energy.shape != arrivals.shape
        or maximum.shape != arrivals.shape
    ):
        raise ValueError("Incompatible FIFO kernel array shapes")
    function = kernel()
    if function is None:
        return None
    work = np.ascontiguousarray(free, dtype=np.float64)
    t = np.ascontiguousarray(arrivals, dtype=np.float64)
    e = np.ascontiguousarray(energy, dtype=np.float64)
    m = np.ascontiguousarray(maximum, dtype=np.float64)
    p = np.ascontiguousarray(powers, dtype=np.float64)
    starts = np.zeros_like(t)
    waiting = np.zeros(len(work))
    function(
        work, p, t, e, m, starts, waiting, len(work), len(p), t.shape[1], efficiency
    )
    free[:] = work
    return starts, waiting
