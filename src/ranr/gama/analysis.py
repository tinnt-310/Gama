"""Development sensitivity and optimizer reporting from GAMA artifacts only."""

from __future__ import annotations
from dataclasses import replace, asdict
from pathlib import Path
import csv
import json
import numpy as np
from ..paths import write_json, digest
from .headless import METHODS, RunConfig, provenance, load_model
from .pipeline import jobs, report


def sensitivity(config: RunConfig, folder: Path, models: Path, workers: int) -> None:
    """Vary deadlines in GAMA; re-score unchanged outcomes for penalty factors."""
    parameters = {
        method: load_model(models / method / "parameters.json", method, config)
        for method in METHODS
    }
    identity = {
        "source": provenance(),
        "config": asdict(config),
        "models": {
            method: digest(models / method / "parameters.json") for method in METHODS
        },
        "profile": "development_sensitivity",
        "deadlines": [180, 360, 720],
        "penalty_factors": [0.5, 1.0, 2.0],
        "seeds": [23001, 23002, 23003],
    }
    registration = folder / "registration.json"
    if registration.exists():
        old = json.loads(registration.read_text())
        if any(old.get(k) != v for k, v in identity.items()):
            raise ValueError("Sensitivity inputs changed; use a new output directory")
    write_json(registration, {**identity, "status": "running"})
    rescored = []
    for deadline in identity["deadlines"]:
        c = replace(
            config,
            development=True,
            deadline_minutes=deadline,
            warmup_minutes=1440,
            measure_minutes=2880,
            trace=True,
        )
        target = folder / str(deadline)
        rows = jobs(
            c, parameters, target, identity["seeds"], workers, cases=("normal", "high")
        )
        write_json(target / "results.json", rows)
        for row in rows:
            source = target / "runs" / row["case"] / str(row["seed"]) / row["method"]
            outcomes = [
                x
                for x in json.loads((source / "outcomes.json").read_text())
                if x["measured"]
            ]
            waiting = np.array([x["waiting_min"] for x in outcomes])
            travel = np.array([x["travel_min"] for x in outcomes])
            penalty = np.array([x["penalty_min"] for x in outcomes])
            for factor in identity["penalty_factors"]:
                w_star = (waiting + factor * penalty) / deadline
                objective = float(
                    0.5 * np.mean(travel / deadline + w_star)
                    + 0.3 * np.percentile(w_star, 95)
                    + 0.2 * row["peak_queue"] / 125
                )
                if factor == 1 and abs(objective - row["objective"]) > 1e-8:
                    raise ValueError(
                        "Sensitivity re-scoring differs from GAMA objective"
                    )
                rescored.append(
                    {
                        **row,
                        "deadline_minutes": deadline,
                        "penalty_factor": factor,
                        "objective": objective,
                    }
                )
    write_json(folder / "results.json", rescored)
    for deadline in identity["deadlines"]:
        for factor in identity["penalty_factors"]:
            report(
                [
                    r
                    for r in rescored
                    if r["deadline_minutes"] == deadline
                    and r["penalty_factor"] == factor
                ],
                folder / "report" / str(deadline) / str(factor),
                "development_sensitivity",
            )
    write_json(registration, {**identity, "status": "complete"})


def training_report(folder: Path) -> None:
    registration = json.loads((folder / "registration.json").read_text())
    rows = []
    for method in METHODS:
        for path in sorted((folder / method).glob("*/history.json")):
            for row in json.loads(path.read_text()):
                rows.append(
                    {"method": method, "optimizer_seed": int(path.parent.name), **row}
                )
    if not rows:
        raise ValueError("No completed optimizer generations")
    target = folder / "report"
    write_json(target / "histories.json", rows)
    fields = [
        "method",
        "optimizer_seed",
        "evaluations",
        "short_best",
        "short_mean",
        "long_validation",
        "rollouts",
        "validation_rollouts",
        "cpu_seconds",
        "validation_cpu_seconds",
    ]
    with (target / "histories.csv").open("w") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 4))
    for method in METHODS:
        seeds = sorted({r["optimizer_seed"] for r in rows if r["method"] == method})
        for i, seed in enumerate(seeds):
            selected = [
                r
                for r in rows
                if r["method"] == method
                and r["optimizer_seed"] == seed
                and r["long_validation"] is not None
            ]
            if selected:
                ax.plot(
                    [r["evaluations"] for r in selected],
                    [r["long_validation"] for r in selected],
                    label=f"{method} / {seed}",
                    marker=".",
                )
    ax.set_xlabel("Candidate evaluations / optimizer seed")
    ax.set_ylabel("Long-validation objective")
    ax.legend(fontsize=6)
    fig.tight_layout()
    for extension in ("pdf", "svg"):
        fig.savefig(target / f"validation_by_budget.{extension}")
    plt.close(fig)
    (target / "REPORT_VI.md").write_text(
        f"# CMA-ES qua GAMA\n\nTrạng thái: {registration['status']}.\n\n"
        "histories.csv ghi ngân sách từng seed, fitness ngắn, validation dài và chi phí CPU. "
        "So sánh ở mốc ngân sách chung trước; không coi các candidate là mẫu độc lập. "
        "Các điểm validation dọc đường được dùng chọn model, không phải kết quả test.\n"
    )
