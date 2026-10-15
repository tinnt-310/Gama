"""Seed-level paired inference and reproducible IEEE-sized static figures."""

from __future__ import annotations
import csv
import json
from pathlib import Path
import numpy as np
from scipy.stats import t as student_t, ttest_1samp
from .config import CASES, METHODS
from .paths import write_json


def paired_interval(values: list[float]) -> dict:
    a = np.asarray(values, dtype=float)
    n = len(a)
    if n < 2:
        return {
            "n": n,
            "mean": float(a.mean()) if n else None,
            "low": None,
            "high": None,
            "p": None,
        }
    mean = float(a.mean())
    se = float(a.std(ddof=1) / np.sqrt(n))
    width = float(student_t.ppf(0.975, n - 1)) * se
    p = (
        1.0
        if np.all(a == 0)
        else (0.0 if se == 0 else float(ttest_1samp(a, 0.0).pvalue))
    )
    return {"n": n, "mean": mean, "low": mean - width, "high": mean + width, "p": p}


def holm(pvalues: list[float]) -> list[float]:
    order = np.argsort(pvalues)
    adjusted = np.empty(len(pvalues))
    previous = 0.0
    for rank, index in enumerate(order):
        previous = max(previous, min(1.0, (len(pvalues) - rank) * pvalues[index]))
        adjusted[index] = previous
    return adjusted.tolist()


def report(folder: Path) -> dict:
    registration = json.loads((folder / "registration.json").read_text())
    if registration.get("status") != "complete":
        raise ValueError("Evaluation incomplete; no final scientific report")
    results = [
        json.loads(p.read_text())
        for p in sorted(folder.glob("runs/*/*/*/metrics.json"))
    ]
    index = {(r["case"], r["method"], r["seed"]): r for r in results}
    comparisons = []
    summary = []
    fields = (
        "objective",
        "mean_travel_min",
        "mean_wait_min",
        "p95_wait_min",
        "mean_travel_wait_min",
        "completion_rate",
        "peak_queue",
        "communication_bytes",
        "recommendation_mean_ms",
    )
    for case in registration["cases"]:
        seeds = registration["seeds"]
        for seed in seeds:
            hashes = {index[(case, m, seed)]["exogenous_hash"] for m in METHODS}
            if len(hashes) != 1:
                raise ValueError("Unmatched exogenous evaluation")
        for method in METHODS:
            row = {"case": case, "method": method, "runs": len(seeds)}
            for field in fields:
                values = [
                    index[(case, method, s)][field]
                    for s in seeds
                    if index[(case, method, s)][field] is not None
                ]
                row[field] = float(np.mean(values)) if values else None
            summary.append(row)
        for field in fields:
            group = []
            for baseline in METHODS[1:]:
                differences = [
                    index[(case, METHODS[0], s)][field]
                    - index[(case, baseline, s)][field]
                    for s in seeds
                    if index[(case, METHODS[0], s)][field] is not None
                    and index[(case, baseline, s)][field] is not None
                ]
                group.append(
                    {
                        "case": case,
                        "metric": field,
                        "baseline": baseline,
                        **paired_interval(differences),
                    }
                )
            corrected = holm([x["p"] if x["p"] is not None else 1.0 for x in group])
            for row, p in zip(group, corrected):
                row["holm_p"] = p
            comparisons.extend(group)
    target = folder / "report"
    target.mkdir(exist_ok=True)
    for name, rows in (("summary", summary), ("paired_comparisons", comparisons)):
        with (target / (name + ".csv")).open("w") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        write_json(target / (name + ".json"), rows)
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update(
        {
            "font.size": 8,
            "axes.labelsize": 8,
            "legend.fontsize": 7,
            "pdf.fonttype": 42,
            "svg.fonttype": "none",
        }
    )
    for field, label in (
        ("objective", "Penalized objective"),
        ("mean_wait_min", "Mean physical waiting (min)"),
        ("p95_wait_min", "P95 physical waiting (min)"),
    ):
        figure, axis = plt.subplots(figsize=(7.16, 2.7))
        x = np.arange(len(registration["cases"]))
        width = 0.2
        for i, method in enumerate(METHODS):
            y = []
            err = []
            for case in registration["cases"]:
                values = [
                    index[(case, method, s)][field]
                    for s in registration["seeds"]
                    if index[(case, method, s)][field] is not None
                ]
                ci = paired_interval(values)
                y.append(np.nan if ci["mean"] is None else ci["mean"])
                err.append(0.0 if ci["low"] is None else ci["mean"] - ci["low"])
            axis.bar(x + (i - 1.5) * width, y, width, yerr=err, label=method, capsize=2)
        axis.set_xticks(x, registration["cases"], rotation=15)
        axis.set_ylabel(label)
        axis.legend(ncol=4, loc="upper center", bbox_to_anchor=(0.5, 1.2))
        axis.grid(axis="y", alpha=0.2)
        figure.tight_layout()
        for suffix in ("pdf", "svg", "png"):
            figure.savefig(target / f"{field}.{suffix}", dpi=300)
        plt.close(figure)
    title = (
        "Kết quả smoke/development — không dùng làm kết luận nghiên cứu"
        if registration["profile"] != "research"
        else "So sánh RANR trên GIS Nha Trang"
    )
    lines = [
        f"# {title}",
        "",
        f"Số seed mỗi nhóm: {len(registration['seeds'])}. Chênh lệch = Proposed − baseline; CI và kiểm định theo seed.",
        "",
        "Ba kiểm định baseline được hiệu chỉnh Holm riêng cho từng metric/nhóm. Không suy ra ý nghĩa thực tiễn chỉ từ p-value.",
        "",
        "| Nhóm | Phương pháp | Mục tiêu phạt | Chờ TB (phút) | P95 chờ (phút) | Hoàn thành |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for row in summary:

        def fmt(key):
            return "NA" if row[key] is None else f"{row[key]:.3f}"

        lines.append(
            f"| {row['case']} | {row['method']} | {fmt('objective')} | {fmt('mean_wait_min')} | {fmt('p95_wait_min')} | {fmt('completion_rate')} |"
        )
    lines += [
        "",
        "Kết quả dựa trên nhu cầu và hành vi mô phỏng, chưa hiệu chỉnh bằng dữ liệu tài xế thực tế.",
        "Snapshot No-Prediction không được tiến tới ETA; ngoại tác FIFO hiện tại bị loại khỏi chi phí.",
        "Mốc chuẩn hóa, deadline và phạt được lưu trong registration/manifest; xem hồ sơ thay đổi khoa học.",
    ]
    (target / "REPORT_VI.md").write_text("\n".join(lines) + "\n")
    return {"summary": summary, "comparisons": comparisons, "report": str(target)}
