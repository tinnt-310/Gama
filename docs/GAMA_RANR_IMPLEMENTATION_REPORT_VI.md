# Báo cáo nâng cấp RANR-AW tại chỗ

Ngày 15/10/2026. Git checkpoint trước thay đổi: `5800181`. Môi trường `persistent-controlled-distributed-3`. Trạng thái: triển khai và kiểm tra nhỏ hoàn tất; nghiệm thu thực nghiệm nghiên cứu còn chờ.

## Audit và bảo toàn

Nguồn trước nâng cấp chưa có Git; import GAML kéo theo Recommendation/Coordination/StationForecast và Python launcher nằm trong legacy. Cost thiếu charging duration; phạt gộp chưa theo opportunity denominator; P2P thiếu event batching; calibration chưa có phản ứng theo offer. Đã tạo checkpoint Git, inventory và manifest hash trước sửa. GIS gốc không đổi;9.117 tệp output lịch sử kiểm tra hash còn nguyên. Không sao chép cây GAML cũ vào thư mục active.

## Thành phần giữ lại

GIS Nha Trang, native driving, cơ sở11 trạm125 cổng7195kW, cơ chế xe thường trực/opportunities/inbound, fixed-port energy integration, keyed randomness, softmax20/4 tham số, CMA-ES/resume/long-validation, paired evaluation và seed-level reporting được giữ và cập nhật. Mã vật lý đã kiểm chứng được tách khỏi dependencies của thuật toán cũ.

## Chức năng và thay đổi toán học

| Yêu cầu | Triển khai / kiểm chứng nhỏ |
|---|---|
| 1 Observation | Local numeric copies; peer chỉ từ packet đã nhận; prior fallback, immutable exposure views |
| 2 Exposure | Request-leg token, owner, count/version/context/ETA profile, immediate local update, arrival/cancellation resolution; conditional anonymous model |
| 3 Future prediction | ETA stochastic shadow queue; background/unseen/exposure không chồng issuance; arrival probability và ETA train; paired externality |
| 4 Simultaneous | Scheduler theo ID; gửi/nhận riêng tick; burst20/50/100/200 có activation thực trong fixture |
| 5 EV autonomy | Follow/alternative/defer/decline/abandon; K_true và K_hat tách; high/moderate/low/contextual/misspecified |
| 6 Cost/feasibility | Travel+charge; mean/P95/H/U; route/energy reserve/connector/observed capacity; busy không tự loại |
| 7 Outcomes | Opportunity ledger đầy đủ; terminal loại trừ nhau; deadline/settlement; ineligible không tự thành failure |
| 8 Weights | 5 weights,20 adaptive degrees,4 fixed; observable normalized phi |
| 9 Reliability | Delay/loss/duplicate/reorder/TTL/partition/recovery; no peer truth fallback |
| 10 One-shot | Stable softmax, prior, dedup; chỉ replan khi có sự kiện, tối đa2, giữ request/deadline |
| 11 Training | Actual GAMA fitness, independent splits, design freeze, fair CMA-ES budgets,72h limit |
| 12 Performance | Scenario/route cache, latency diagnostics và microbenchmark GAML; full benchmark còn chờ |
| 13 Stability | Off mặc định; forecast-only smoothing/hysteresis; invalidation theo critical events; No-Prediction giữ raw snapshot |
| 14 Event P2P | Heartbeat+event cùng transport; coalescing/min interval; capacity/workload/exposure triggers |
| 15 Objective | Opportunity-normalized service/time/tail/queue và explicit exclusive failure+unmet-energy components |

Công thức và assumptions đầy đủ: [hồ sơ khoa học](GAMA_RANR_SCIENTIFIC_CHANGES_VI.md). Không có tuyên bố giảm waiting/congestion hay tốt hơn baseline từ các kiểm tra này.

## Mã cũ đã loại bỏ

Đã bỏ các GAML entry point benchmark/assignment cũ, imports tới central coordination và StationForecast, Python simulator/reference executable, compatibility wrappers/verification và config/test tương ứng. Home charging, autonomous SOC-triggered demand và population-deletion callbacks không còn trong mô hình nghiên cứu. Nguồn cũ có trong Git checkpoint; historical outputs giữ nguyên.

Không còn alternative Python simulator, workload selector hoặc auto workload switch trong nguồn hiện hành. GUI và Headless cùng GAML. Launcher/compiler hiện ở `ranr.gama`.

## Kiến trúc và cấu hình

Cây thư mục thực tế và trách nhiệm: [kiến trúc](GAMA_RANR_ARCHITECTURE_VI.md). Bảng49 điều khiển Run me và2 điều khiển bổ sung collection: [cài đặt](GAMA_SETTINGS_REFERENCE_VI.md).

Defaults:3000 conventional/1000 privateEV/700 taxi; inbound cap900/300/210; frequency0.2/0.8; SOC<30%; target80%; reserve5%; step1s; temperature0.2; heartbeat5min; min-send10s; smoothingoff; beta=beta_energy=1 ở development. Coefficients và approximation chưa được gắn nhãn đã validation/frozen.

## Kiểm thử đã thực thi

- 31 Python unit tests đạt. Optimizer trong unit tests dùng oracle giả để kiểm tra orchestration/resume; không phải training GAMA.
- 25 GAML roots compile đạt; không có import hỏng.
- Native scientific/protocol/physical/parameter/cache/behavior/port-outage/decision/objective/network fixtures đạt. Port test có công suất phân số82.5kW và giữ đúng energy/elapsed qua outage.
- Fleet fixture cho cả4 phương pháp đạt; No-P2P messages=0, No-Prediction future_calls=0.
- Burst activation20/50/100/200 đạt, mỗi request trỏ EV đã tồn tại. Fixture này cố ý cho EV defer để kiểm tra bất đồng bộ và quyền từ chối; không chứng minh khả năng giảm queue trong burst thực.
- Episode fixture có7 xe,1 request30.6kWh, sạc hoàn tất trong17 phút service time, EV còn tồn tại. Fixture dùng step60s, có can thiệp SOC/feasibility rõ ràng để tạo case kiểm tra; không phải calibration hoặc timestep accuracy gate.
- Native driving fixture step1s: EV đi theo GIS tới trạm, bắt đầu sạc và đã nhận năng lượng.
- Headless paired smoke4 phương pháp cùng exogenous hash, cả7 xe được giữ. Có0 request kích hoạt trong horizon cực ngắn này; chỉ chứng minh pipeline/provenance, không đo recommendation quality.
- Run me startup đúng4700 xe; Collect training data startup đăng ký seed/config/provenance. Partial collection smoke được chuyển hash-preserving vào vùng bằng chứng, không đưa vào builder3seed.
- GUI collection builder được thử dữ liệu synthetic: thiếu seed, thiếu outcome, dừng sớm, sai config/source, tampering, thiếu mẫu và đủ3seed. Chưa chạy end-to-end3episode dài.

## Microbenchmark đã chạy

Numeric input fixture,1 candidate station,8 MC samples,8 requests mỗi code path. Bypasses observation assembly/transport; không phải benchmark bốn policy trên GIS/phân quyền thông tin. Thứ tự chạy cố định có JIT warmup effect, không dùng bảng này kết luận thứ hạng tốc độ.

| Code path | Mean ms | P95 ms | Max ms |
|---|---:|---:|---:|
| RANR-AW | 5.875 | 10.55 | 13.0 |
| No-P2P | 2.25 | 3.0 | 3.0 |
| No-Prediction | 1.125 | 1.65 | 2.0 |
| Fixed-Weights | 1.375 | 2.0 | 2.0 |

Pha simulation gồm khởi động JVM: wall 2.867s; CPU user 16.34s + system 0.70s; peak RSS 639304KiB. CPU có thể lớn hơn wall do nhiều thread JVM. Chưa ngoại suy throughput/candidate budget từ microbenchmark.

## Readiness và giới hạn

**Calibration:** có thể bắt đầu thu từ Collect training data. Chưa có bộ3seed đầy đủ được chấp nhận cho môi trường này;760 là cơ hội kỳ vọng, activation phụ thuộc SOC và activity thực.

**CMA-ES:** code điều phối đã chuẩn bị nhưng chưa sẵn sàng training chính. Còn cần calibration, long development/demand validation, full forecast accuracy/performance benchmark, sensitivity và reviewed design freeze. Không tự khởi động72h optimization.720 held-out runs cũng chưa chạy.

Gates/core là study boundary dẫn xuất từ mạng, chưa xác minh ranh giới hành chính; connector generic và hourly profiles là assumptions development. Anonymous reconciliation dùng mean-field approximation; response model chưa được kiểm chứng nhận dạng/khái quát trên dữ liệu dài. Không suy ra causal policy failure từ terminal status đơn lẻ.

GUI rendering/startup đã chạy native Headless và có ảnh Computer ở hồ sơ; chưa tự động hóa click Workbench hoặc so sánh outcome3episode GUI/Headless dài. Optional smoothing, temperature và communication intervals có runner development nhưng chưa chọn bằng experiments.

## Hồ sơ bàn giao

Bằng chứng máy đọc được: `outputs/gama_ranr/distributed_upgrade_20261015/acceptance.json`. `verified/` chứa các run/measurements khớp source hiện hành; các attempt trước giữ riêng theo thư mục của chúng. `historical_manifest.json` kiểm tra dữ liệu đã có trước thay đổi. `files_changed.txt` là inventory Git.

Files modified (54):

- `README.md`
- `README_GAMA.md`
- `README_PYTHON_REFERENCE.md`
- `configs/gama/calibration.json`
- `configs/gama/environment.json`
- `configs/gama/research.json`
- `configs/gama/smoke.json`
- `docs/ALGORITHM_CURRENT.md`
- `docs/ALGORITHM_IDEAL_ASSIGNMENT.md`
- `docs/AUDIT_REPORT.md`
- `docs/COORDINATION_VALIDATION.md`
- `docs/GAMA_RANR_ARCHITECTURE_VI.md`
- `docs/GAMA_RANR_RUN_GUIDE_VI.md`
- `docs/GAMA_RANR_SCIENTIFIC_CHANGES_VI.md`
- `docs/GAMA_RANR_STATUS_VI.md`
- `docs/GAMA_SETTINGS_REFERENCE_VI.md`
- `docs/IMPLEMENTATION_PLAN.md`
- `docs/NUMERICS.md`
- `docs/PROGRESS.md`
- `docs/RANR_ARCHITECTURE_VI.md`
- `docs/RANR_METHODS_VI.md`
- `docs/RANR_SCIENTIFIC_CHANGES_VI.md`
- `docs/RANR_STATUS_VI.md`
- `docs/RECOMMENDATION_VALIDATION.md`
- `docs/REVIEW_CONTEXT.md`
- `docs/REVIEW_FINDINGS.md`
- `docs/RUSH_AND_CLOCK_FIX.md`
- `docs/SERVICE_INTERFACE.md`
- `docs/SYSTEM_ALGORITHM_FULL_VI.md`
- `docs/SYSTEM_FLOWCHART_VI.md`
- `docs/VALIDATION.md`
- `models/ChargingService.gaml`
- `models/Mobility.gaml`
- `models/main.gaml`
- `models/ranr/Fleet.gaml`
- `models/ranr/Math.gaml`
- `models/ranr/Policy.gaml`
- `models/ranr/Prediction.gaml`
- `models/ranr/Runtime.gaml`
- `models/tests/RanrPredictionBenchmark.gaml`
- `pyproject.toml`
- `scripts/check_gama.py`
- `scripts/gama.py`
- `src/ranr/__init__.py`
- `src/ranr/gama/analysis.py`
- `src/ranr/gama/benchmarking.py`
- `src/ranr/gama/cli.py`
- `src/ranr/gama/gui_collection.py`
- `src/ranr/gama/headless.py`
- `src/ranr/gama/pipeline.py`
- `src/ranr/gama/training.py`
- `tests/fixtures/gama_parameters.json`
- `tests/test_gama_timeout.py`
- `tests/test_gama_unified.py`

Files added (18):

- `docs/GAMA_RANR_IMPLEMENTATION_REPORT_VI.md`
- `docs/manuscripts/METHODOLOGY_IMPLEMENTED_VI.md`
- `models/ranr/Evaluation.gaml`
- `models/tests/RanrBehaviorTests.gaml`
- `models/tests/RanrBurstActivationTests.gaml`
- `models/tests/RanrBurstTests.gaml`
- `models/tests/RanrDecisionTests.gaml`
- `models/tests/RanrEpisodeTests.gaml`
- `models/tests/RanrMicrobenchmark.gaml`
- `models/tests/RanrNetworkTests.gaml`
- `models/tests/RanrObjectiveTests.gaml`
- `models/tests/RanrPortOutageTests.gaml`
- `models/tests/RanrProtocolTests.gaml`
- `src/ranr/gama/contracts.py`
- `src/ranr/gama/design.py`
- `src/ranr/gama/launcher.py`
- `src/ranr/gama/validation.py`
- `tests/test_gama_contracts.py`

Files removed from active tree; recoverable at5800181 (108):

- `configs/research.json`
- `configs/smoke.json`
- `configs/training_research.json`
- `configs/training_smoke.json`
- `models/ConvexAssignment.gaml`
- `models/Coordination.gaml`
- `models/CoordinationBenchmark.gaml`
- `models/GISCoordinationBenchmark.gaml`
- `models/PairedCapacity.gaml`
- `models/PhaseA.gaml`
- `models/Recommendation.gaml`
- `models/RecommendationBenchmark.gaml`
- `models/StationForecast.gaml`
- `models/Traffic.gaml`
- `models/tests/AssignmentTests.gaml`
- `models/tests/AuditRegression.gaml`
- `models/tests/ClockOffsetRegression.gaml`
- `models/tests/CoarseStepRegression.gaml`
- `models/tests/ConfigurationRegression.gaml`
- `models/tests/CoordinationContractTests.gaml`
- `models/tests/DashboardRegression.gaml`
- `models/tests/DeadLifecycleTests.gaml`
- `models/tests/ElapsedClockRegression.gaml`
- `models/tests/EndToEndTests.gaml`
- `models/tests/FixedPortForecastTests.gaml`
- `models/tests/GISReferenceExport.gaml`
- `models/tests/HourlyGISRegression.gaml`
- `models/tests/HourlyStepRegression.gaml`
- `models/tests/LateSmokeRegression.gaml`
- `models/tests/MapRegression.gaml`
- `models/tests/MathRegression.gaml`
- `models/tests/ObservationForecastTests.gaml`
- `models/tests/PhysicalTests.gaml`
- `models/tests/PortCausalityTests.gaml`
- `models/tests/RanrInformationTests.gaml`
- `models/tests/RecommendationInformationTests.gaml`
- `models/tests/RecommendationLifecycleTests.gaml`
- `models/tests/RecommendationTests.gaml`
- `models/tests/RoadNodingTests.gaml`
- `models/tests/RushActivityRegression.gaml`
- `models/tests/RushCohortRegression.gaml`
- `models/tests/ScheduleRegression.gaml`
- `models/tests/SolverSafetyRegression.gaml`
- `models/tests/StationAccessTests.gaml`
- `models/tests/WaitingPredictionTests.gaml`
- `requirements-verification.txt`
- `scripts/benchmark_coordination.py`
- `scripts/continue_research_release.py`
- `scripts/input_manifest.py`
- `scripts/recommendation_experiments.py`
- `scripts/recommendation_sensitivity.py`
- `scripts/report_recommendation.py`
- `scripts/verify_extended_coordination.py`
- `src/ranr/legacy/__init__.py`
- `src/ranr/legacy/evaluation.py`
- `src/ranr/legacy/event_io.py`
- `src/ranr/legacy/python_reference/__init__.py`
- `src/ranr/legacy/python_reference/_queue.cpp`
- `src/ranr/legacy/python_reference/behavior.py`
- `src/ranr/legacy/python_reference/benchmarking.py`
- `src/ranr/legacy/python_reference/calibration.py`
- `src/ranr/legacy/python_reference/charging.py`
- `src/ranr/legacy/python_reference/cli.py`
- `src/ranr/legacy/python_reference/config.py`
- `src/ranr/legacy/python_reference/evaluation.py`
- `src/ranr/legacy/python_reference/experiments.py`
- `src/ranr/legacy/python_reference/geography.py`
- `src/ranr/legacy/python_reference/information.py`
- `src/ranr/legacy/python_reference/logging.py`
- `src/ranr/legacy/python_reference/native.py`
- `src/ranr/legacy/python_reference/paths.py`
- `src/ranr/legacy/python_reference/policies.py`
- `src/ranr/legacy/python_reference/prediction.py`
- `src/ranr/legacy/python_reference/randomness.py`
- `src/ranr/legacy/python_reference/records.py`
- `src/ranr/legacy/python_reference/reporting.py`
- `src/ranr/legacy/python_reference/simulation.py`
- `src/ranr/legacy/python_reference/training.py`
- `src/ranr/legacy/scripts/__init__.py`
- `src/ranr/legacy/scripts/benchmark_coordination.py`
- `src/ranr/legacy/scripts/check_gama.py`
- `src/ranr/legacy/scripts/gama.py`
- `src/ranr/legacy/scripts/input_manifest.py`
- `src/ranr/legacy/scripts/recommendation_experiments.py`
- `src/ranr/legacy/scripts/recommendation_sensitivity.py`
- `src/ranr/legacy/scripts/report_recommendation.py`
- `src/ranr/legacy/scripts/verify_extended_coordination.py`
- `src/ranr/legacy/verification/__init__.py`
- `src/ranr/legacy/verification/events.py`
- `src/ranr/legacy/verification/io.py`
- `src/ranr/legacy/verification/model.py`
- `src/ranr/legacy/verification/recommendation.py`
- `src/ranr/legacy/verification/recovery.py`
- `src/ranr/legacy/verification/run.py`
- `tests/proxy_miss.json`
- `tests/test_audit.py`
- `tests/test_events.py`
- `tests/test_model.py`
- `tests/test_ranr.py`
- `tests/test_recommendation.py`
- `tests/test_rounding_safety.py`
- `verification/__init__.py`
- `verification/events.py`
- `verification/io.py`
- `verification/model.py`
- `verification/recommendation.py`
- `verification/recovery.py`
- `verification/run.py`

