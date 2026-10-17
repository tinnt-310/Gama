> Tài liệu lịch sử. Mô hình hiện hành: persistent-soc-activity-6 / intent-service-5; xem [hồ sơ khoa học](GAMA_RANR_SCIENTIFIC_CHANGES_VI.md).

> Tài liệu lịch sử: mô tả nguồn trước nâng cấp. Đối chiếu tại Git checkpoint `5800181`; hướng dẫn hiện hành ở [GAMA Run Guide](GAMA_RANR_RUN_GUIDE_VI.md).

# Execution ledger — plan: docs/IMPLEMENTATION_PLAN.md

Current runtime is observation-driven recommendation. End-to-end implementation,
final tests and measured limits are in [RECOMMENDATION_VALIDATION.md](RECOMMENDATION_VALIDATION.md).

Latest user preference: Run me defaults to 60 seconds/cycle (one simulated minute).
Detailed fixture and Smoke GIS experiments retain their independently specified steps.
Clock/route-energy/service validation: `outputs/minute_cycle_validation.log`.

The assignment gate history below is preserved for the separate ideal benchmark;
its optimality certificates do not apply to recommendation or actual waiting.

User-approved scope is Gates 0–7. Robot→EV integration is Gate 8, deferred.

## Follow-up specification: fixed-port coordination (8 October 2026)

User clarified the current objective: keep GIS/station locations fixed and compare nearest assignment against coordination using travel plus causal congestion, evaluated through real travel/waiting events. Before coding the fixed-port forecast, the user locked five requirements in IMPLEMENTATION_PLAN: equivalent reference-service-minute units for all backlog inputs; final-only inbound excluded from physical forecasting and atomically transferred on arrival; interval causal capacity without storing unused service; separate optimization and event metrics; and a same-waiting-queue/different-active-session-availability acceptance fixture (`C=[3,5]` versus `[0,3]`). ALL_FEASIBLE is the approved candidate mode for 11 stations; TOP_K is an ablation, adaptive screening is deferred.

Status: implementation completed for the fixed-port extension. Forecast tests, source-vertex noding/geometry tests and full station reachability/candidate tests pass. Run me accepts fixed_port, defaults to ALL_FEASIBLE and uses a one-second physical step for waiting evaluation; 60/3,600-second modes remain available for exploratory/coarse runs. All original GIS inputs are unchanged. Each main/benchmark run has its own output directory with input checksums and commit timestamps. Paired controlled physical comparisons and their independent numerical reproductions are in COORDINATION_VALIDATION.md and outputs/coordination_benchmark.json. The historical gates below describe the preceding mock implementation; the new report supersedes their old counts/defaults. Robot integration remains deferred.

Final follow-up evidence: 28 independent root compilations; 23 full-suite/GIS/Phase A runtime checks plus fixed-port Run me smoke; 19 Python tests; 11 mock snapshot replays; eight controlled policy runs and four proposed fixed-port snapshot comparisons. Same-input GIS Travel+Waiting is 30 versus 2.53 minutes. Extended budget: burst converges at 94,340 iterations; the 11-candidate GIS fixture remains timed out at 200,000, although GAML and Python agree. This is an explicit numerical/runtime limitation, not a convergence acceptance. Reports retain all timeout statuses. No solver replacement or default-budget increase was made.

## Rulings

- Ruling: work in place, original models backed up in `/tmp/evstation-original` — this workspace has no Git repository; no branch/worktree/commit can be created — cost if wrong: manual diff/rollback rather than Git history.
- Ruling: Python dependencies installed in local `.venv`, runtime stays GAML — independent numerical verification requires Clarabel/CVXPY; no Python call in any model — cost if wrong: offline environment setup is required.
- Ruling: nonnegative entropy prox has no artificial x≤1 saturation — simplex equality implies that upper bound at feasibility, so the same primal/PDHG is preserved; the valid LB still uses the feasible [0,1] box — cost if wrong: cross-language/Clarabel regression fails.
- Ruling: retain 20,000 default iterations, allow explicit 200,000 for zero-entropy verification — initial zero-entropy fixtures timed out; same equations converge at 80,180–122,620 iterations — cost: zero-entropy runs can be slow; timeout is never marked converged.
- Ruling: GAMA communication measures logical in-process optimization messages/canonical payload bytes — stations execute locally under synchronous barriers; no network transport is implemented — cost: these metrics do not measure network latency or serialized socket overhead.

## Final gate state

| Gate | State | Evidence |
|---|---|---|
| 0 | Complete | GAMA 1.9.3 compile and seed-42 GIS smoke, writable launcher |
| 1 | Complete | PhysicalTests, DeadLifecycleTests, PortCausalityTests; clock/energy/FIFO/idempotence/resource/causality |
| 2 | Complete | EndToEndTests and GIS; reachable assignment, deferred/stranded/cancelled paths |
| 3 | Complete | Phantom/subgradient, committed inbound, no-double-count tests |
| 4 | Complete | Python reference/PDHG/prox/HiGHS/enumeration; positive and zero entropy verified before GAML port |
| 5 | Complete | GAML/Python/Clarabel snapshots agree; raw feasibility, certified gap and dual-copy residual exported |
| 6 | Complete | GKPS marginals and 51/49, integer certificate, exact repair/full-scan counterexample |
| 7 | Complete | Eight Phase A cases, GAML/Python paired capacities, event ground truth, bounds/messages/runtime/config reports |
| 8 | Deferred | NOT_IMPLEMENTED pending actual Robot→EV scheduler |

Final commands and outputs: `outputs/python_validation.log` — 11 tests OK; `outputs/gama_validation.log` — seven GAMA checks PASS; `outputs/phase_a_run.log` and `outputs/paired_run.log` — PASS; `outputs/offline_validation.log` — all eleven snapshot comparisons and OFFLINE_VERIFICATION_PASS. Numerical/physical details in `docs/VALIDATION.md`, `outputs/verification.json` and `outputs/phase_a_summary.csv`.

Commands retained for handoff: `python3 scripts/check_gama.py --suite --gis --phase-a`; `OPENBLAS_NUM_THREADS=1 .venv/bin/python -m unittest tests.test_model`; `OPENBLAS_NUM_THREADS=1 .venv/bin/python -m verification.run --phase-a`.

## Final review and fix pass

Fresh reviewer: `/root/final_review`, gpt-6-astra, read-only; no implementer delegation. Verdict 'With fixes', three Important findings, no Critical/Minor findings.

- Final: fixed external agent-death resource leak — DeadLifecycleTests RED (no PASS, blocked port) → GREEN; station-owned physical/inbound metadata, idempotent per-tick reconciliation, cancellation events without dead-agent dereference. Covers death in inbound, waiting, charging.
- Final: fixed same-tick service overlap — PortCausalityTests RED (arrival starts before fractional completion) → GREEN; completion stays pending until physical clock reaches finish; port retained. Covers fractional final interval and subsequent arrival.
- Final: fixed missing paired capacity comparison — Python paired test RED (missing experiment) → GREEN; added both Python controlled pair and GAMA PairedCapacity, varying only C, verifying identical noncapacity inputs. Independent benchmark checks both GAML snapshots.
- Final: fixed cancelled-session automatic re-request — EndToEndTests RED (8 request events instead of 7) → GREEN; automatic requests only from idle/completed. Explicit new begin_request still supported.

Reviewer 'Declined to judge' rulings:

- Ruling: Robot scheduling/SOC/recharge/failure remains Gate 8 — explicitly excluded by user until scheduler delivery — cost: no robot-aware performance evidence yet.
- Ruling: no network/asynchronous theorem or actual wire bytes — approved synchronous in-process runtime only — cost: transport behavior remains untested.
- Ruling: scalability conclusions cover measured micro-batches (N=10/20/30, M=3/5, K=2/3, H=4/8), no city-scale or real-world waiting claim — controlled Phase A only — cost: broader performance evidence remains future work.
- Ruling: retain legacy commute policy/calibration outside clock/energy/lifecycle fixes — no new traffic dataset supplied and this research isolates assignment — cost: existing traffic calibration is not independently validated.
- Ruling: final aggregate validation is judged by fresh recorded reruns, not reviewer inference — reviewer avoided shared-output GAMA commands — cost: final verification is author-run.

Final complete suite GREEN: 11/11 Python tests, 7/7 GAMA fixture/GIS checks, Phase A + paired GAMA runs, and 11 independent snapshot comparisons. All three review fixes were verified RED→GREEN. No deferred minors. Finishing workflow: no Git repository, so changes and durable ledger/artifacts are retained in-place; no merge/push/worktree cleanup applies.

## IDE compilation fix after handoff

The reported ChargingService type/action errors were reproduced by compiling that file independently. It relied on EV/vehicle/intersection types and globals from its importer Traffic, so successful main-model compilation had hidden the invalid standalone module. The new `check_models()` regression failed with the reported unknown `elecar`/`CHARGING_RATES` errors before the fix.

Moved road/building/base-vehicle declarations into Mobility, moved EV declarations alongside the mutually dependent station lifecycle in ChargingService, and retained Traffic as the public import entry point. Declarations and action bodies were compared with `/tmp/evstation-ide-before` and preserved verbatim; no solver or scheduling policy was rewritten. Updated README and the Gate 0 compile acceptance criterion.

Fresh checks: all 14 GAML files compile independently (`outputs/ide_compile_validation.log`); the full GAMA suite, GIS smoke, Phase A and paired-capacity runs pass (`outputs/gama_validation.log`); all 11 Python tests pass (`outputs/python_validation.log`); all 11 exported snapshots pass offline reproduction/reference checks (`outputs/offline_validation.log`). The same two large Phase A cases retain their explicit 20,000-iteration timeout status. Standalone compilation now runs automatically with `--suite`, and can also be invoked with `python3 scripts/check_gama.py --compile`.

## Explicit types and local charging-time name

Reproduced the seven distinct IDE warnings with standalone GAMA compilation of main, ChargingService and ConvexAssignment. Population counts now use explicit `int(...)`, preserving the existing integer conversion; the solver norm initializer uses explicit `float(...)`, preserving its numerical value. The local charging interval is named `charge_seconds` instead of `duration`, avoiding shadowing GAMA's model attribute while retaining the same energy/time equations.

Direct compiler checks contain none of the reported implicit-cast/shadowing warnings (`outputs/main_warning_check.log`, `outputs/service_warning_check.log`, `outputs/solver_warning_check.log`). Fresh verification: 14 standalone GAML compilations and all seven fixture/GIS checks pass (`outputs/gama_type_warning_validation.log`); all 11 Python tests pass (`outputs/python_type_warning_validation.log`). No new test cases were needed for these declaration-only changes.

## Full audit and map repair

User requested a complete review of logic, syntax/types, organization and the broken map. Proven GIS failure: multi-file envelope yielded a 322×1,383-km world and road/building/station layers outside its bounds. Switched to the encompassing road-file envelope, verified all complete layer envelopes lie inside the resulting 26×38-km world, and inspected an actual GAMA 2D render (`outputs/map_preview.png`). Removed the display's default intersection symbols that created yellow polyhedra.

Corrected cancelled arrival resurrection, workload's hardcoded efficiency, day-two schedule times, stale EV/population controls, low-speed ETA denominator, rush retirement and unassigned external-deletion auditing. Removed inactive GUI controls and obsolete commented code; made units/cumulative CSV labels explicit. A lifecycle regression caught duplicate cancellation during pending cleanup; ownership was corrected and existing death/end-to-end tests passed again.

Independent mathematical audit `/root/math_audit`: three concrete Python findings, all fixed and rechecked by the same reviewer without an important regression. Added finite/domain validation, iterative GKPS DFS and universal exported integer/certificate/local-optimum checks. Core formulation/PDHG/entropy/LB/repair equations were found consistent; no solver was switched.

Final evidence: `outputs/audit_gama_validation.log` — 18 standalone compile checks and 11 runtime/GIS checks pass; `outputs/audit_python_validation.log` — 15 tests OK; `outputs/audit_phase_a_validation.log` — Phase A and paired-capacity runs pass; `outputs/audit_offline_validation.log` — all 11 comparisons and OFFLINE_VERIFICATION_PASS. Same two large Phase A cases retain explicit timeouts. Full findings, remaining limits and restart instructions are in `docs/AUDIT_REPORT.md`.

## Workspace diagnostic export: random-duration overload

The supplied IDE export contains 1,598 diagnostic rows across the workspace, including 91 rows for this project. Project notices concern intentional inherited overrides/reflex ordering except for one confirmed truncation warning in Mobility: `rnd(0.5, 1)` selects the integer overload, truncating the lower bound to zero. Changed the upper bound to `1.0` so the end-of-day outing duration is sampled as a float between 0.5 and 1 hour.

Standalone Mobility compilation reproduces the warning before the change and no longer reports truncation afterward (`outputs/ide_mobility_warning_check.log`). Recompile evidence for all project models is in `outputs/ide_workspace_compile_validation.log`; schedule and GIS smoke evidence is in `outputs/ide_mobility_runtime_validation.log`. Intentional overrides remain in place; model-library diagnostics in other workspace projects were not changed.

## Restore map colors and visible vehicle images

User requested colored map layers and the missing vehicle images. Existing RGBA files and paths were valid; the old 20-metre icon frame became subpixel at city-wide scale, and buildings were drawn above vehicles. Restored coral road strokes, existing building-type colors (blue/green/purple), named orange stations and vehicles as the top layer. Vehicle image frames default to 40 pixels wide, configurable through the Display parameter; conversion uses each display axis separately to preserve the original 16:9 asset ratio across window shapes. Assets and physical vehicle dimensions are unchanged. No random styling or mobility/assignment change was introduced.

Checks: main and Mobility compile (`outputs/map_color_compile.log`, `outputs/map_icon_compile.log`); map containment and GIS smoke pass (`outputs/map_color_validation.log`). Inspected actual GAMA renders at 1400×1000 (`outputs/map_preview.png`) and 700×1000 (`outputs/map_portrait_preview_run/snapshot/Computer4785-0.png`), with original vehicle images visible. Verified all four road/building palette colors occur in the rendered image. README and audit report reflect the restored display.

## Historical simulation clock, live metrics and user-selected minute steps

Initial zero charts were expected at midnight with one-second cycles: 1,548 cycles cover only 25m48s, while departures are scheduled at 05:00–07:00; completed/service-average charts update only after relevant events. Added live monitors, current charging/waiting histograms, simulation-minute energy x-axis and integer count axes. Added a frozen start-hour offset for daily schedules, preserving elapsed session/ETA times and midnight behavior. Config records the actual starting hour.

At that earlier stage the user selected **one minute per cycle**, overriding the original one-second GUI default. The current approved waiting-evaluation plan restores one second and retains minute/hour options. Run me then defaulted to 60 seconds through its experiment parameter and offers 1/60 seconds; all independent fixture/default simulation declarations still use one second. Do not reinterpret `00:24:00` as 24 hours: a minute-step day is 1,440 cycles with actual elapsed time `24:00:00`. Export and chart refresh periods use physical elapsed time instead of a fixed number of cycles.

Necessary coarse-step fixes: EV consumption uses remaining route-length decrease, including curved/multiple segments; movement arrivals materialize after their interval, before station service, with inbound retained until arrival. Zero-travel assignment can materialize immediately during commit. Completion-pending/port-release causality remains enforced. No robot scheduler or assignment equations were changed. Minute-step physical waiting/arrival is coarse and must be compared against one-second mode when sub-minute precision matters.

Fresh evidence: 21 standalone compiles and 16 runtime/GIS checks (`outputs/fast_cycle_suite_validation.log`); final chart compile (`outputs/fast_cycle_compile.log`); all 11 existing snapshot comparisons (`outputs/fast_cycle_offline_validation.log`). Coarse regression verifies curved-route distance/SOC, arrival/service energy/released port and 1,440-cycle day. Actual fast GUI chart/monitor snapshots show completed sessions 0→1 and grid energy 1→34 kWh (`outputs/live_fast_preview_run`). The previously recorded two large Phase A timeout cases remain explicit. Reference one-second physical metrics are retained separately in `outputs/fast_cycle_reference_physical_metrics.json`; README, implementation plan and service boundary explain both modes.
