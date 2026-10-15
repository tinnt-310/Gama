import csv
from pathlib import Path
import numpy as np
from .model import Snapshot


def load_snapshot(prefix):
    prefix = Path(prefix)
    with Path(str(prefix) + "_edges.csv").open() as f:
        rows = list(csv.DictReader(f))
    with Path(str(prefix) + "_bins.csv").open() as f:
        bins = list(csv.DictReader(f))
    with Path(str(prefix) + "_metrics.csv").open() as f:
        metrics = next(csv.DictReader(f))
    n = max(int(r["n"]) for r in rows) + 1
    m = max(int(r["station"]) for r in bins) + 1
    h = max(int(r["bin"]) for r in bins) + 1
    capacity = np.zeros((m, h))
    inbound = capacity.copy()
    d = np.zeros(n)
    edges = []
    for r in bins:
        t = int(r["station"]), int(r["bin"])
        capacity[t] = float(r["capacity"])
        inbound[t] = float(r["inbound"])
    for r in rows:
        nn = int(r["n"])
        d[nn] = float(r["workload"])
        edges.append((nn, int(r["station"]), int(r["bin"]), float(r["travel_min"])))
    s = Snapshot(
        n,
        m,
        h,
        edges,
        d,
        capacity,
        inbound,
        float(metrics["delta"]),
        float(metrics["d_ref"]),
        float(metrics["theta"]),
        edge_demand=np.array([float(r["workload"]) for r in rows]),
    )
    return (
        s,
        np.array([float(r["x"]) for r in rows]),
        np.array([float(r["z"]) for r in rows]),
        metrics,
    )
