> Tài liệu lịch sử: mô tả nguồn trước nâng cấp. Đối chiếu tại Git checkpoint `5800181`; hướng dẫn hiện hành ở [GAMA Run Guide](GAMA_RANR_RUN_GUIDE_VI.md).

# Validation — Gates 0–7, Phase A only

Current recommendation implementation supersedes the runtime defaults below:
see [RECOMMENDATION_VALIDATION.md](RECOMMENDATION_VALIDATION.md) for 38 root
compilations, 32 Python tests, recommendation/choice regression and 80 controlled
experiment artifacts. The following sections retain historical assignment results.

Current fixed-port extension and graph/candidate audit: see [COORDINATION_VALIDATION.md](COORDINATION_VALIDATION.md). Run me now defaults to fixed_port / ALL_FEASIBLE / one-second physical steps. The sections below retain the preceding mock/GUI validation history; old default-step descriptions are historical. New results are in outputs/coordination_*validation.log and outputs/coordination_benchmark.json.

GAMA 1.9.3 / JDK 17; Python offline: numpy 2.2.6, scipy 1.15.3, cvxpy 1.7.5, clarabel 0.11.1.

Historical GUI clock/activity change: **21 standalone GAML compilations and 16 runtime/GIS checks pass** (`outputs/fast_cycle_suite_validation.log`), plus final chart compilation (`outputs/fast_cycle_compile.log`). Offline reproduction of all 11 existing assignment/Phase A/paired snapshots passes (`outputs/fast_cycle_offline_validation.log`); Phase A cases 6/7 retain their recorded timeout status. Python solver code was not changed in this update.

New fixtures cover dashboard activity at initial hours 0/6 with a 1-second step, the dashboard at a 60-second step, clock offset across midnight without changing elapsed timestamps, and a coarse-step curved route. The latter verifies 400 metres of route travel (rather than straight displacement), corresponding SOC loss, arrival at the next minute boundary, correct clipped 0.6-kWh charging energy/port release and **1,440 cycles = 86,400 seconds = 24 hours**. Fixture defaults stay at 1 second; GUI Run me defaults to 60 seconds at the user's request. Fast-mode arrival/dispatch statistics have minute resolution.

Actual Run me fast-mode rendering also confirms the live monitors and charts: a small seeded charging session completes once, grid energy rises to 34 kWh, and elapsed time is 35 minutes at cycle 35 (`outputs/live_fast_preview_run/simulation-outputs4900.xml`, `outputs/live_fast_preview_run/snapshot/Chart4900-35.png`). Reference one-second session metrics from the fresh suite are retained in `outputs/fast_cycle_reference_physical_metrics.json`.

```bash
python3 scripts/check_gama.py --suite --gis --phase-a
OPENBLAS_NUM_THREADS=1 .venv/bin/python -m unittest discover -s tests
OPENBLAS_NUM_THREADS=1 .venv/bin/python -m verification.run --phase-a
```

Historical full-audit results: **15 Python tests, 18 standalone GAML compilations, 11 GAMA checks (including GIS), eight Phase A cases and the GAMA paired-capacity run passed their prescribed checks.** All 11 independent numerical snapshot comparisons pass. See `docs/AUDIT_REPORT.md` and `outputs/audit_*validation.log` for the current audit. The two disclosed Phase A timeouts remain unchanged.

GAMA checks cover FIFO/clock/kWh/port restoration; duplicate arrival and cancellation; external deletion during inbound/waiting/charging; no same-tick service overlap including a fractional final interval; phantom capacity/prices; 100 EV .51/.49 → 51/49; disconnected/zero-capacity and zero-entropy cases; cross-batch inbound; actual road travel; deferred/stranded cleanup; seeded GIS.

## IDE standalone compilation regression

The IDE error report exposed a missing check: ChargingService used species and globals declared by its importer Traffic. Compiling main as a root had resolved those names, but opening ChargingService independently failed. `python3 scripts/check_gama.py --compile` reproduced that failure before the fix.

Shared road, building and base-vehicle declarations now live in Mobility; ChargingService imports Mobility and owns both EV and station species, which reference each other. Traffic remains the public import entry point. Existing declarations and action bodies were preserved. All 14 GAML files now compile independently; results are in `outputs/ide_compile_validation.log`. `--suite` includes this check before simulation tests so an invalid imported module cannot be hidden by successful compilation through main.

Standard Python 3-station/10-EV/4-bin fixtures, seeds 7/11/19: theta=.25 converged in 7,520–17,860 iterations; theta=0 initially timed out at 20,000, then the same equations converged in 80,180–122,620 with an explicit 200,000 verification budget. Scalar prox, epigraph/recursion, subgradient, HiGHS/enumeration certificates, rounding marginals, ETA boundaries and proxy full-scan counterexample passed.

## Independent GAML snapshot reproduction

| Case | N/M/H | Status | Iterations | Reference relative gap | Python x error | LB / UB | Repair improvement |
|---|---|---|---|---|---|---|---|
| assignment | 10/3/4 | converged | 9160 | 9.51e-08 | 2.66e-15 | 44.8233 / 45.3449 | 0.0139 |
| phase_a_0 | 10/3/4 | converged | 9380 | 9.52e-08 | 9.94e-14 | 44.9983 / 45.5331 | 0.2625 |
| phase_a_1 | 10/3/4 | converged | 4960 | 2.14e-09 | 3.23e-14 | 64.0096 / 64.8266 | 0.6813 |
| phase_a_2 | 10/3/4 | converged | 5200 | 1.05e-08 | 9.65e-14 | 57.5573 / 58.4880 | 0.5232 |
| phase_a_3 | 10/3/4 | converged | 16020 | 9.86e-08 | 9.71e-15 | 40.9767 / 41.1432 | 0.3392 |
| phase_a_4 | 20/3/8 | converged | 18020 | 9.04e-08 | 1.39e-13 | 89.2049 / 90.8419 | 0.2981 |
| phase_a_5 | 20/3/8 | converged | 7400 | 8.56e-08 | 2.55e-13 | 93.6800 / 95.0173 | 1.6196 |
| phase_a_6 | 30/5/8 | timeout | 20000 | 0.000348 | 1.1e-13 | 166.1871 / 173.1706 | 7.2688 |
| phase_a_7 | 30/5/8 | timeout | 20000 | 0.00223 | 8.26e-14 | 209.3645 / 217.3868 | 0.8433 |
| paired_base | 10/3/4 | converged | 9160 | 9.51e-08 | 2.66e-15 | 44.8233 / 45.3449 | 0.0139 |
| paired_changed | 10/3/4 | converged | 9000 | 9.45e-08 | 2.78e-15 | 50.4690 / 51.0294 | 0.0926 |

Returned assignments are feasible. LB is checked against the centralized reference; UB is recomputed from final integer z on the identical frozen snapshot. N≤10 has HiGHS integer benchmarks; tiny enumeration is a separate regression. Converged cases satisfy residual≤1e−6, reference gap≤1e−5 and positive-entropy x error≤1e−3. The two N=30 Phase A timeouts remain explicit, with feasible recovery and valid bounds; they are not claimed optima.

## Controlled workload comparisons

GAMA paired experiment: `{"same_noncapacity_inputs": true, "assignment_l1_difference": 1.9224078566754939, "base_objective": 44.82333497582766, "changed_objective": 50.468962588396046}`. Exact assertions verify unchanged edge candidates, ETA bins, workloads, direct costs and inbound arrays; only C differs.

Python `herding`: `{"solver_status": "converged", "iterations": 2940, "LB": 43.66349118068242, "argmax_load": [100.0, 0.0], "rounded_load": [60.0, 40.0], "argmax_objective": 56.666666666666664, "rounded_objective": 44.0, "repaired_objective": 44.0}`

Python `cross_batch`: `{"solver_status": "converged", "iterations": 7820, "LB": 95.66349364159818, "previous_inbound": 80.0, "no_memory_true_snapshot_objective": 97.33333333333333, "with_memory_true_snapshot_objective": 96.0, "no_memory_new_load": [60.0, 40.0], "with_memory_new_load": [40.0, 60.0], "ground_truth": "prescribed-capacity workload surrogate; not physical waiting"}`

Python `paired_capacity`: `{"same_noncapacity_inputs": true, "inbound": [[10.0, 0.0, 0.0, 0.0], [10.0, 0.0, 0.0, 0.0]], "assignment_l1_difference": 9.974578026264023, "cases": [{"case": "balanced_capacity", "capacity": [[20.0, 20.0, 20.0, 20.0], [20.0, 20.0, 20.0, 20.0]], "solver_status": "converged", "iterations": 2180, "relaxed_objective": 48.26713204860014, "centralized_reference": 48.2671320486003, "LB": 48.267128323225286, "UB": 50.0, "new_workload": [50.0, 50.0]}, {"case": "unequal_capacity", "capacity": [[0.0, 0.0, 0.0, 0.0], [40.0, 40.0, 40.0, 40.0]], "solver_status": "converged", "iterations": 5620, "relaxed_objective": 51.66348710495002, "centralized_reference": 51.66348710535865, "LB": 51.663482054896, "UB": 51.666666666666664, "new_workload": [0.1271098686798829, 99.87289013132013]}], "ground_truth": "paired prescribed-capacity surrogate, not actual waiting"}`

These comparisons concern prescribed-capacity surrogates, not actual waiting improvement.

## Physical ground truth

`end_to_end`: `{"sessions": 7, "started": 5, "completed": 5, "mean_wait_min": 1.22, "p95_wait_min": 2.266666666666666, "mean_service_min": 0.6666666666666662, "unfinished": 0, "unstarted": 0, "forecast_mismatch": true, "ground_truth": "fixed-port session events"}`

`gis_smoke`: `{"sessions": 1, "started": 1, "completed": 0, "mean_wait_min": 0.0, "p95_wait_min": 0.0, "mean_service_min": null, "unfinished": 1, "unstarted": 0, "forecast_mismatch": true, "ground_truth": "fixed-port session events"}`

Waiting includes zero-wait sessions; unfinished/unstarted are separate. End-to-end has five completed, one cancelled and one stranded session with no unfinished request. GIS smoke has one ongoing long charge, reported unfinished. The actual GIS contains 3,018 buildings loaded once and a combined data envelope; smoke uses ten vehicles and seed 42.

All mock/fixed-port runs are forecast-mismatch experiments. `*_bins.csv` backlog/prices describe final integer recovery. `phase_a_summary.csv` has communication/runtime data; `verification.json` has full results; raw edges/bins/metrics/config/event CSVs and logs are retained in `outputs/`. Communication is logical in-process messages and canonical payload bytes.

## Independent review

One fresh read-only reviewer found three Important issues: external-death reservation leak, same-cycle service overlap and absent paired capacity control. All three were reproduced RED then fixed GREEN; the full suite passed after the single fix pass. No Critical or Minor findings remained. Cancelled automatic re-request was also reproduced and fixed.

Robot→EV, robot oracle/state, real network transport, city-scale and real-world waiting improvements remain outside current evidence. Gate 8 is deferred until the actual scheduler is supplied.
