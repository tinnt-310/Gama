# Full project audit — 8 October 2026

Scope: runtime GAML modules, GIS initialization and display, charging/request lifecycle, coordination, mathematical solver/recovery, offline Python references, launchers, tests and handoff documents. Robot→EV remains deferred.

## Current fixed-port follow-up

The newer detailed audit is [COORDINATION_VALIDATION.md](COORDINATION_VALIDATION.md), covering causal fixed-port forecast, separate reference efficiency, ALL_FEASIBLE candidates, source-vertex road noding, all-station reachability, event-based paired comparisons, isolated outputs and exported-budget Python replay. Main defaults to a one-second detailed step for waiting evaluation and still offers 60/3,600-second modes. Robot integration remains deferred. The findings/results below describe the earlier mock/GUI work.

## Findings and corrections

| Area | Proven issue | Correction and evidence |
|---|---|---|
| GIS/world | Multi-file envelope produced a world 322 × 1,383 km; roads/buildings/stations were partly outside it. A headless map render was almost blank. | Establish projection/world through the single road shapefile, whose extent covers all supplied data. MapRegression verifies complete layer envelopes are contained and world is within 5% of the road extent. Correct world is approximately 26 × 38 km. |
| Display | Perspective and default intersection symbols obscured the map with yellow polyhedra. The initial gray palette and subpixel vehicle images were subsequently corrected at the user's request. | Computer is a 2D display with coral roads, blue/green/purple building types and named orange stations. Original vehicle images are drawn on top, with configurable screen dimensions and preserved aspect ratio. No default intersection layer. Actual GAMA render inspected: `outputs/map_preview.png`. |
| Request lifecycle | A delayed start/arrival could resurrect a cancelled request. | Arrival requires a live EV, matching station and active request state. AuditRegression reproduces cancellation followed by start and verifies no port/arrival change. |
| Pending requests | Externally deleting an unassigned request left its event history unfinished. | Pending audit metadata is retained until ownership transfers to a station; removed requests receive cancellation exactly once. Station-owned cleanup keeps its existing owner. Empty request IDs are excluded from session events. AuditRegression and DeadLifecycleTests cover both sides. |
| Workload units | Reference workload hardcoded efficiency=.9 instead of configured efficiency. | Workload uses configured efficiency/reference power; exported config agrees. A .6-kWh request with efficiency=.5 yields 1.2 reference service minutes. |
| Daily schedule | Day-two departure and entertainment times remained on day one. | Reset per-vehicle schedules once when day_counter changes, including entertainment windows. ScheduleRegression checks day-two hour ranges. Midnight resets rush flags while preserving active sessions. |
| Population controls | Changing total EV did not recompute private/rush populations. | Refresh derived targets, clamp taxis to total EV and update physical populations. ConfigurationRegression checks 7 EV → 5 taxi/2 private and reduction to 2 EV. |
| GUI configuration | Port/night/old SOC controls did not affect implemented service/energy. Default cars exceeded the slider range. | Remove inactive controls; expose actual kWh/km and charging efficiency; widen population ranges. Speeds must be positive, and car speed changes reach the movement step. |
| Rush retirement | Vehicles retained after a rush to finish charging remained in the city after completion; a later rush discarded their retirement references. | Preserve the retirement list across rushes and remove finished/cancelled vehicles after unregistering them. ConfigurationRegression checks retirement. |
| Solver input domains | Invalid dimensions, demand shape, NaN/infinite values, nonpositive reference/bin sizes and zero iteration budget were accepted. | Explicit Python validation; GAML checks dimensions, nonnegative workload/capacity, candidates, temperatures and solve limits. Audit tests reject malformed snapshots/budgets. |
| GKPS benchmark | Recursive Python DFS raised RecursionError on a 600-EV candidate chain. | Iterative DFS retains traversal order. Long-chain regression checks binary decisions and one station per EV. |
| Verification acceptance | For >10 EV, exported all-zero assignments could be accepted with LB > UB. | Always check binary z, one station per EV, finite metrics, certificate ordering and complete one-exchange neighborhood. Real CSV regression reproduces the former acceptance hole. GAML recovery also asserts feasibility, objective decrease and LB≤UB. |
| Structure/labels | Large blocks of obsolete commented code, inconsistent indentation and unit-free chart/CSV labels made reading misleading. | Remove obsolete code blocks, normalize indentation, state minutes/metres/kWh and mark daily CSV values cumulative. Module imports remain acyclic. |

## Mathematical review

An independent read-only reviewer examined GAML solver/recovery, Python references and validation. The causal recurrence, backward subgradient, scaled epigraph constraints, Frobenius step bound, entropy prox, feasible objective projection, boxed Lagrangian LB and full-neighborhood repair were found consistent. The three Python issues above were independently reproduced; the reviewer rechecked their fixes and found no important regression.

No algorithm switch was made. Positive-entropy uniqueness concerns the assignment; the epigraph representation does not imply unique auxiliary iterates. Solver timeouts remain separate from convergence. The recovery local optimum is within the stated 1e-6-minute tolerance.

## Verification

New regressions were run against the old behavior first: invalid GIS bounds, cancelled arrival/workload configuration, stale day-two schedule, missing rush retirement, unassigned external deletion, Python recursion/input domains and invalid exported assignments. Existing lifecycle tests caught a duplicate cleanup during development; pending ownership was corrected and those tests were rerun.

Final command set:

```bash
python3 scripts/check_gama.py --suite --gis --phase-a
OPENBLAS_NUM_THREADS=1 .venv/bin/python -m unittest discover -s tests
OPENBLAS_NUM_THREADS=1 .venv/bin/python -m verification.run --phase-a
```

Results are recorded in `outputs/audit_gama_validation.log`, `outputs/audit_python_validation.log`, `outputs/audit_physical_regressions.log`, `outputs/map_bounds_validation.log`, `outputs/audit_offline_validation.log` and `outputs/verification.json`.

Final results: **18 standalone GAML compilations, 11 GAMA runtime/GIS checks, 15 Python tests and all 11 independent snapshot comparisons pass.** The eight Phase A cases and paired-capacity run pass their prescribed checks (`outputs/audit_phase_a_validation.log`); the same two N=30 cases remain explicitly timed out at 20,000 iterations. Their returned integer assignments are feasible and independently checked for certificate ordering and one-exchange optimality.

Standalone compilation still emits informational notices for intentional inherited overrides (shape, seed, driving attributes and overridden behaviors). No reported implicit-cast/shadowing warnings remain in main or ChargingService. End-to-end event metrics are unchanged: five completed sessions, one cancellation and one stranded request, mean wait 1.22 minutes. GIS smoke's long charging session remains correctly reported unfinished.

## Remaining limits

- Historical GUI change: Run me previously defaulted to 60-second cycles. The current physical-evaluation default is one second, with 60/3,600-second modes available. Fast-mode arrival/port dispatch is sampled at minute boundaries; use the detailed mode for sub-minute waiting comparisons. Updated clock/dashboard validation is in `docs/VALIDATION.md` and `outputs/fast_cycle_suite_validation.log` (21 compiles, 16 runtime/GIS checks).
- Robot service/state/oracle require the actual scheduler at Gate 8. Mock capacity and fixed-port events remain a forecast-mismatch testbed.
- Communication is synchronous in-process exchange, without real network latency/failure validation.
- Phase A measures micro-batches, not validated city-scale solver performance. Large cases can hit the 20,000-iteration budget.
- ETA uses route length and a fixed speed forecast; it does not predict all traffic delays. Physical travel and waiting are measured separately.
- Legacy traffic demand/commute behavior is synthetic and not calibrated to observed Nha Trang trips. The map is a schematic GIS display, with no satellite/OSM background.
- Numerical objectives/certificates use the active candidate stations in a frozen batch snapshot. Congestion at stations outside that snapshot is a constant omitted from that batch objective.

After changing the code, stop the previous GUI experiment and launch Run me again; existing display instances do not adopt a new layer definition. The Small GIS scenario option provides a ten-vehicle check before a larger run.
