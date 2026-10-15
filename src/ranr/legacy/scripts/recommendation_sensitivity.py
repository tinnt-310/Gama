"""Declared supplementary experiments; no tuning on these held-out runs."""

from pathlib import Path
import json
import sys
from ranr.paths import ROOT
from ranr.legacy.scripts.recommendation_experiments import launch, evaluate, OUT


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--reuse-baselines", action="store_true")
    args = parser.parse_args()
    threshold = json.loads((OUT / "development_calibration.json").read_text())[
        "selected_threshold"
    ]
    results = []
    if args.reuse_baselines and (OUT / "supplementary_results.json").exists():
        for old in json.loads((OUT / "supplementary_results.json").read_text()):
            if old["experiment"] in ("B1_nearest", "B2_ETA"):
                result = evaluate(Path(old["prefix"]))
                result.update(
                    experiment=old["experiment"],
                    settings=old["settings"],
                    extra=old.get("extra"),
                )
                results.append(result)

    def run(label, **kwargs):
        extra = kwargs.pop("extra", None)
        prefix = launch(threshold=threshold, extra=extra, **kwargs)
        result = evaluate(prefix)
        result["experiment"] = label
        result["settings"] = kwargs
        result["extra"] = extra
        results.append(result)
        (OUT / "supplementary_results.json").write_text(
            json.dumps(results, indent=2) + "\n"
        )

    # Physical nearest and shortest-ETA baselines, same 10 test seeds/demand stream.
    for seed in [] if args.reuse_baselines else range(1, 11):
        for policy in ("nearest", "eta"):
            run(
                "B1_nearest" if policy == "nearest" else "B2_ETA",
                mode="B3",
                seed=seed,
                hours=48,
                policy=policy,
            )
    for case in ("light", "burst"):
        for mode in ("B3", "B4", "B4-N"):
            run(case, mode=mode, seed=11, hours=12, case=case, correction=True)
    for normalization in ("feasible", "pareto"):
        run("normalization", mode="B4", seed=12, hours=12, normalization=normalization)
    for count in (5, 10, 20, 50):
        run(
            "replay_count",
            mode="B4",
            seed=13,
            hours=12,
            extra={"replay_scenarios": ("INT", str(count))},
        )
    for window in (6, 12, 24):
        run(
            "history_window",
            mode="B4",
            seed=14,
            hours=12,
            extra={"observation_window": ("INT", str(window))},
        )
    for mode in ("B3", "B4"):
        run(
            "limited_information",
            mode=mode,
            seed=15,
            hours=6,
            extra={"information_mode": ("STRING", "LIMITED_INFORMATION")},
        )
    for delay in (0, 5, 15):
        run(
            "neighbor_delay",
            mode="B4-N",
            seed=16,
            hours=12,
            delay=delay,
            correction=True,
        )
    for degree in (0, 1, 3):
        run(
            "neighbor_degree",
            mode="B4-N",
            seed=17,
            hours=12,
            correction=True,
            extra={"communication_degree": ("INT", str(degree))},
        )
    for bins in (0, 24, 48):
        run(
            "cold_start",
            mode="B4",
            seed=18,
            hours=12,
            extra={"observation_min_bins": ("INT", str(bins))},
        )
    run(
        "top_k",
        mode="B4",
        seed=19,
        hours=12,
        extra={"candidate_mode": ("STRING", "TOP_K")},
    )
    run(
        "fluid_comparator",
        mode="B4",
        seed=20,
        hours=12,
        extra={"waiting_estimator_mode": ("STRING", "fluid")},
    )
    run(
        "scalability_100_stations",
        mode="B3",
        seed=21,
        hours=2,
        case="light",
        extra={"benchmark_stations": ("INT", "100")},
    )
    print("RECOMMENDATION_SENSITIVITY_PASS")


if __name__ == "__main__":
    main()
