> Tài liệu lịch sử: mô tả nguồn trước nâng cấp. Đối chiếu tại Git checkpoint `5800181`; hướng dẫn hiện hành ở [GAMA Run Guide](GAMA_RANR_RUN_GUIDE_VI.md).

# Recommendation service interface, current runtime

Recommendation queries call station-local `predict_waiting(epoch_min, eta_offset_min)`
and receive waiting minutes, forecast status, snapshot time, replay mismatch and
scenario count. No physical queue or raw robot state leaves the station. LIMITED
uses a previously advertised aggregate curve with `stale_*` metadata.

`report_intention(request_id, eta_min, workload_service_min)` and
`withdraw_intention(request_id)` are audit-only in v1. Only actual arrival can call
physical enqueue; arrival checks the real station access location and is idempotent.
Pre-arrival external EV deletion is reconciled by an audit ledger, never forecast
inbound. Recommendation runtime cannot call `commit_assignment()`.

Local arrival histories contain observed timestamp/energy only. Replay OOD and
cold start use labelled fallbacks. B4-N packets contain aggregate workload/capacity
and timestamps; models learn only matured labels. See ALGORITHM_CURRENT.md.

The following existing contract describes the ideal assignment oracle and future
robot integration. Its inbound ledger belongs only to ideal assignment.

# Service/oracle boundary

`service_backend = fixed_port` is implemented. Both `oracle_backend = fixed_port` and `mock` are implemented; Run me defaults to fixed_port. Selecting robot service/oracle reports `NOT_IMPLEMENTED` and fails initialization. There is no synthetic robot species, assumed robot state schema or Robot→EV optimization.

Future adapter contracts (logical contracts, not a dependency on robot field names):

| Contract | Requirements |
|---|---|
| forecast_service(epoch_seconds, bin_edges_seconds) → interval workload C | Nonnegative equivalent robot-service minutes, snapshot only; no mutations of physical scheduler. Derive from residual cumulative S by adjacent differences. Physical jobs/queue accounted once. |
| enqueue_arrival(request_id, ev, requested_energy_kwh) | Idempotent arrival. Atomically remove the matching inbound record and enqueue physical job. |
| cancel_session(request_id) | Remove inbound/physical job, release resources once, preserve existing scheduling policy. |
| service_started(request_id, absolute_time_seconds) | Unique timestamp; waiting minutes=(start−arrival)/60 including zero. |
| service_completed(request_id, absolute_time_seconds, delivered_energy_kwh) | Unique completion and delivered-energy record. |

Station-owned session metadata survives external EV deletion. Every physical tick reconciles dead inbound, waiting and charging references, releases reservations exactly once and logs cancellation without reading dead-agent fields. Normal cancellations clean up synchronously. Final energy integration marks completion pending; the EV remains charging and retains its port until the clock reaches the recorded finish. This prevents same-cycle arrival/service overlap.

GUI Run me defaults to 60 seconds for fast GIS exploration and offers 1-second detailed and 3,600-second coarse steps; verification fixtures retain 1 second unless explicitly testing coarse steps. An hourly tick is unsuitable for waiting-quality conclusions. Native drive may cross several curved segments per tick, so EV energy uses the decrease in remaining road-route length, not displacement between endpoints. A moving EV's station arrival is held until the end of its movement interval, then materialized before the following station service tick. An assigned EV already at its station arrives immediately during commit. Inbound remains owned until this physical arrival. Minute-step arrivals/port dispatch are sampled at minute boundaries; this is a coarse physical approximation, not second-resolution waiting ground truth. Session/ETA timestamps remain elapsed minutes even when daily schedules start at a nonzero clock hour. Actual start hour and step are exported in config; run exports follow elapsed-minute boundaries.

Before assignment, `pending_session_data` retains only request audit metadata and reconciles external deletion. Assignment/arrival transfers ownership to the station and removes the pending audit entry. Cleanup checks station ownership to avoid duplicate cancellation. A stranded vehicle without a charging request does not create a session with an empty request ID.

Current GAML fixed-port methods accept the EV reference (which carries request_id and energy) and record these events. Mock `charging_station.forecast_service(epoch, count)` accepts epoch **minutes** and a uniform-bin count, equivalent to the logical bin_edges contract under `bin_minutes`. It returns prescribed residual capacities and does not inspect or change the fixed-port queue. This is a forecast-mismatch testbed when mock capacity differs from physical service. Physical waiting must come from session events, never from F.

Arrival requires a live EV with a current request at its assigned station. Cancelled, stranded and completed sessions cannot be resurrected by a delayed arrival/start callback. Workload is `60 × requested_energy_kwh / (reference_efficiency × reference_power_kw)`; reference efficiency is separate from physical charge efficiency and both are exported in config. Configuration domains are checked before coordination starts.

An explicitly cancelled session does not automatically recreate a request on the next tick; a new request must be initiated explicitly. Completed/idle EVs can automatically request again when battery falls below the threshold.

Inbound is local maps keyed by request_id: workload, absolute ETA in minutes, EV reference. Valid assigned/en-route requests have reliability one. The ledger is re-binned from absolute ETA each epoch, not exponentially decayed. ETA uses the remaining directed road route plus current-edge remainder. Arrival transfers exactly once, cancellation removes immediately. No robot adapter will be implemented until the actual scheduler is provided.

ETA defaults to `snapshot_speed`: each remaining road length is divided by the same current `road_speed_factor` used in physical movement. Committed inbound uses its existing current_path; a new shortest path does not silently replace it. Nominal speed remains an ablation. Future congestion/acceleration is still unknown. Event metadata retains assigned ETA for prediction error separately from actual travel/waiting. Events are exported by incremental append with a prefix-local cursor; repeated flush without new events does not rewrite event history. In-memory audit history remains retained.

## Implemented fixed-port forecast

`charging_station.forecast_fixed_port(epoch_minutes, bin_count, bin_width_minutes)` returns interval **equivalent reference-service minutes**. It reads actual free port counts, active physical sessions, remaining energy/headroom, completion-pending timestamps and FIFO waiting jobs. It uses local shadow lists of rates and earliest availability. It never reads inbound workload or mutates physical state, energy, events or RNG.

Active jobs and FIFO jobs reserve actual port time, rounded upward to the physical dispatch tick. At tied availability the fastest port is selected, matching `find_available_port`. Each bin receives only residual port time within that bin multiplied by `power * physical_efficiency / (reference_power * reference_efficiency)`. Unused residual service is not stored across bins; the causal backlog model separately injects arrivals at the bin end. This fluid service abstraction is not an exact individual waiting forecast.

Only final repaired z adds inbound. Arrival removes inbound before adding the physical session. Physical commitments appear only in the oracle and inbound only in H_vir. FixedPortForecastTests verifies unchanged queue/ports/session state, `[3,5]` versus `[0,3]` for the same queue with different active-session durations, mixed power rates, pending release, zero ports, efficiency conversion and repeated arrival/cancellation.
