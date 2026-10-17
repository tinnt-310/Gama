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
from .contracts import rescore_components


def sensitivity(config: RunConfig, folder: Path, models: Path, workers: int) -> None:
    """The registered lexicographic design cannot be rescored with scalar betas."""
    raise ValueError("Scalar penalty/deadline sensitivity is obsolete. Use registered objective dominance regression and paired design validation.")


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
        "fitness_vector",
        "generation_rank",
        "operational_objective",
        "validation_fitness_vector",
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
                and r.get("validation_fitness_vector") is not None
            ]
            if selected:
                ax.plot(
                    [r["evaluations"] for r in selected],
                    [r["validation_fitness_vector"][4] for r in selected],
                    label=f"{method} / {seed}",
                    marker=".",
                )
    ax.set_xlabel("Candidate evaluations / optimizer seed")
    ax.set_ylabel("Operational component on fixed validation set (service priorities reported in CSV)")
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
