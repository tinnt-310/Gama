> Tài liệu lịch sử: mô tả nguồn trước nâng cấp. Đối chiếu tại Git checkpoint `5800181`; hướng dẫn hiện hành ở [GAMA Run Guide](GAMA_RANR_RUN_GUIDE_VI.md).

# Nghiệm thu Observation-Driven Charging Recommendation

Ngày 08/10/2026. Runtime GAMA 1.9.3 / Java 17. Python chỉ chạy kiểm chứng và
đánh giá offline. Thuật toán đang chạy được mô tả tại
[ALGORITHM_CURRENT.md](ALGORITHM_CURRENT.md); benchmark assignment cũ tại
[ALGORITHM_IDEAL_ASSIGNMENT.md](ALGORITHM_IDEAL_ASSIGNMENT.md).

## 1. Kết quả triển khai

Đã có đường chạy từ request → candidate → station-local waiting → Pareto/minimax
→ recommendation → EVChoice → actual arrival → FIFO → charging completion →
event evaluation. Recommendation không giữ cổng, không tạo hard inbound. Có
LIVE/LIMITED, lựa chọn khác khuyến nghị, trace CSV, defer, intention audit,
cancellation/stranded/removal và cleanup một lần.

B3, B4 và B4-N có module/runtime/tests riêng. Historical replay kiểm tra độ đại
diện, không thay đổi năng lượng hoặc số session lịch sử. Thiếu history, chưa hiệu
chỉnh ngưỡng hoặc out-of-distribution đều có fallback được ghi nhãn. B4-N học
online từ nhãn đã quan sát và packet đã nhận; chưa có bằng chứng cải thiện thì
không tự bật correction.

GIS, road graph, sprites, màu bản đồ, vị trí và phần cứng 11 trạm được giữ.
Robot→EV vẫn `NOT_IMPLEMENTED`. Giao tiếp liên trạm là logical simulation.

## 2. Mã thay đổi và các lỗi đã sửa

| Thành phần | Kết quả |
|---|---|
| `models/Recommendation.gaml` | Barrier recommendation/choice, station queries, LIVE/LIMITED, trace, export |
| `models/StationForecast.gaml` | Pure Pareto/minimax, independent discrete shadow, ridge linear algebra |
| `models/ChargingService.gaml` | Local history, replay/OOD/cache, online labels, physical lifecycle và callbacks |
| `models/Coordination.gaml` | Hard commit chỉ chạy trong ideal; append event output và đo travel từ choice/commit |
| `models/main.gaml` | Recommendation mặc định, tham số forecast/choice/replay và monitors |
| `models/RecommendationBenchmark.gaml` | Controlled demand, burst, shift, physical events, RNG demand riêng |
| `verification/recommendation.py` | Python reference độc lập cho ranking, shadow, replay và correction |
| `scripts/recommendation_experiments.py` | Development tách test, same-trace selection, closed-loop evaluator |
| `scripts/recommendation_sensitivity.py` | Baselines và sensitivity fixtures |
| `scripts/report_recommendation.py` | Audit artifacts, demand hashes, aggregate và paired intervals |

Các lỗi phát hiện và sửa khi chạy thực:

* Map literal GAML chứa list và scalar có thể ép kiểu count sai. Ridge sufficient
  statistics được tạo bằng assignment riêng; test xác nhận đủ 60 nhãn thay vì
  count giả bằng 2.
* Moving average đầu tiên đã trả sai 0 do cách truy cập helper/bin. Tính lại từ
  closed-bin keys; regression xác nhận workload 20 và không đọc future bins.
* Tên local `physical` xung đột với tên experiment/species; đổi thành
  `physical_wait`.
* Cleanup audit và inbound cũ có thể ghi cancellation hai lần. Terminal-session
  guard làm callback idempotent; legacy DeadLifecycle và test removal mới đều đạt.
* Đo distance từ trước lựa chọn làm lệch travel metric. Reset tại choice/final
  commit, vẫn giữ route-distance accounting khi chờ và đi sạc.
* RNG demand dùng phép `mod` có ép kiểu không phù hợp với số lớn. Dùng floating
  remainder qua `value − floor(value/modulus) × modulus`, giữ cùng trace giữa policy.
* Shadow với heterogeneous ports từng chọn cổng có release sớm nhất ngay cả khi
  nhiều cổng đều đã rảnh lúc arrival. Sửa chọn earliest feasible start, hòa chọn
  công suất cao nhất như physical FIFO; regression hai arrivals đồng thời trên
  cổng 11/60 kW được kiểm tra trong cả GAML và Python. Main experiment một cổng
  mỗi trạm không bị thay đổi kết quả bởi sửa lỗi này.
* Xuất sự kiện theo cursor/append, không viết lại toàn bộ event history sau mỗi
  micro-batch. Candidate exports giữ regrets từng tiêu chí, alternative rank,
  score method, received time và replay spread. Tiền tệ không được suy ra từ minimax.

PDHG/prox/GKPS/repair được giữ trong benchmark riêng; regression bảo vệ miền biến,
rounding termination, entropy bounds và full-neighborhood repair vẫn chạy qua.

## 3. Kiểm chứng phần mềm

| Kiểm tra | Trạng thái | Bằng chứng |
|---|---|---|
| Baseline trước refactor | PASS: main compile, 23 Python tests | [compile](../outputs/recommendation_validation/baseline_compile.log), [tests](../outputs/recommendation_validation/baseline_python.log) |
| Python sau refactor | PASS: 32 tests | [python_tests.log](../outputs/recommendation_validation/python_tests.log) |
| Standalone GAML compile | PASS: 38 roots | [gama_suite_final.log](../outputs/recommendation_validation/gama_suite_final.log) |
| GAMA regression suite | PASS: 28 runtime/export PASS markers | [gama_suite_final.log](../outputs/recommendation_validation/gama_suite_final.log) |
| Phase A / paired capacity / GIS | PASS: hai numerical fixtures và hai GIS smoke | [ideal_and_gis.log](../outputs/recommendation_validation/ideal_and_gis.log) |
| Export bổ sung / recommendation / GIS cuối | PASS được kiểm tra riêng sau bổ sung metadata | [export_final.log](../outputs/recommendation_validation/export_final.log) |
| Artifacts 80 runs | PASS: chronology, terminal uniqueness, SOC, distance/energy, same demand | [artifact_audit.json](../outputs/recommendation_validation/artifact_audit.json) |

Các fixture mới nằm trong `models/tests/RecommendationTests.gaml`,
`ObservationForecastTests.gaml`, `WaitingPredictionTests.gaml`,
`RecommendationLifecycleTests.gaml` và `RecommendationInformationTests.gaml`.

Chúng kiểm tra ví dụ A/B/C, redundant Energy, dominated outlier, reserve/target
SOC, engine không commit, EV chọn khác recommendation, 100 recommendation đồng
thời không sinh phantom inbound, wrong-station/duplicate arrival, trace/removal,
FIFO shadow và read-only state, cold-start/OOD/future exclusion, matured labels,
stale/missing packets và fluid fallback có nhãn. Cùng queue length nhưng khác
active session tạo waiting/capacity khác. Physical waiting fixture khớp discrete
reference trong một bước backend.

Không lấy các log chạy thất bại trong quá trình debug làm kết quả cuối.
`gama_suite.log` cũ chứa lỗi duplicate cancellation đã sửa; dùng
`gama_suite_final.log`. Final source/GIS checksums:
[source_manifest.json](../outputs/recommendation_validation/source_manifest.json).

## 4. Thiết kế thí nghiệm đã chạy

Development seeds **101/102**, mỗi trace 24 giờ; test seeds **1–10**, mỗi run
48 giờ. Main controlled network có hai trạm, mỗi trạm một cổng 60 kW, efficiency
0,9, EV 60 kWh, consumption 0,18 kWh/km, target SOC 80%, bước vật lý 60 giây.
Demand burst theo chu kỳ; origin chuyển sau 24 giờ. Tất cả dùng
`FOLLOW_RECOMMENDATION`, một giả định thí nghiệm, không phải dữ liệu hành vi thực.

Đã chạy **30 primary runs + 49 supplementary runs + 1 ideal-architecture run**.
Manifest của các prefix chính xác nằm trong
[closed_loop_results.json](../outputs/recommendation_validation/closed_loop_results.json),
[supplementary_results.json](../outputs/recommendation_validation/supplementary_results.json)
và [ideal_closed_loop.json](../outputs/recommendation_validation/ideal_closed_loop.json).
Không gom nhầm các run development/debug cũ theo glob toàn thư mục.

Audit xác nhận SHA256 demand giống nhau theo từng seed giữa B1/B2/B3/B4/B4-N;
ideal seed 1 dùng cùng demand. Actual arrivals được phép khác theo policy.

Supplementary gồm light load, burst, feasible/Pareto normalization, replay count
5/10/20/50, window 6/12/24, cold-start, LIVE/LIMITED, delay 0/5/15 phút, graph
degree, TOP_K, fluid comparator và functional stress 100 trạm. Đây là các lượt
thăm dò một seed, không phải nghiên cứu sensitivity nhiều seed hoàn chỉnh.

## 5. Kết quả closed-loop

Trung bình của **10 kết quả theo seed**, mỗi run 512 requests. Waiting chỉ lấy
sessions đã bắt đầu phục vụ; travel lấy sessions đã arrival. Unfinished không bị
đổi thành waiting = 0. P95 bên dưới là trung bình P95 từng run, không phải P95
gộp toàn bộ sessions.

| Policy | Mean waiting, phút | Mean P95 waiting, phút | Mean travel, phút | Mean T+W, phút | Completed/run | Unfinished/run |
|---|---:|---:|---:|---:|---:|---:|
| B1 nearest | 638,69 | 1.488,67 | 3,00 | 641,69 | 348,7 | 163,3 |
| B2 ETA | 638,69 | 1.488,67 | 3,00 | 641,69 | 348,7 | 163,3 |
| B3 physical-only | 174,32 | 306,63 | 3,99 | 178,31 | 453,2 | 58,8 |
| B4 local/replay | 174,15 | 305,63 | 3,99 | 178,15 | 453,3 | 58,7 |
| B4-N, correction tắt bởi development gate | 174,15 | 305,63 | 3,99 | 178,15 | 453,3 | 58,7 |

B1 và B2 trùng nhau vì tuyến/tốc độ trong fixture này tạo cùng thứ tự distance
và ETA; Python test riêng xác nhận hai policy khác nhau khi road time khác nhau.
Mean T+W chỉ trên sessions có cả arrival và service start; vì mẫu khác nhau,
không được lấy mean travel + mean waiting để thay cho chỉ số này.

Mean T+W của **completed sessions**: B1 638,44; B3 177,74; B4 177,57 phút.
Ngay cả chỉ số completed này vẫn chịu censoring; phải đọc cùng unfinished count.
Peak physical queue trung bình: B1 141,9; B3 34,5; B4 34,2.

Paired B4−B3 mean waiting = **−0,163 phút**; khoảng t 95% theo 10 seed
**[−0,744; +0,417] phút**. Chưa có bằng chứng về cải thiện waiting tăng thêm của
B4 so với B3 trên fixture này. Kết quả nearest thấp chất lượng hơn chỉ có giá trị
trong mạng tổng hợp, demand quá tải và giả định tuân theo khuyến nghị này.

Feedback vẫn tồn tại: recommendation HHI = 1 tại các đợt phát hành của fixture;
arrival dominant-station switch rate B3 ≈0,923 và B4 ≈0,913. Các request đồng
thời có cùng trạng thái vẫn thường chọn cùng trạm. Local history/replay **không
được chứng minh ngăn herding hoặc dao động**. Light-load control có waiting 0
cho cả B3/B4/B4-N, phù hợp với việc lợi ích congestion giảm khi hệ thống rảnh.

## 6. Forecast validity và giá trị thông tin láng giềng

Development replay grid: threshold 0,25/0,5/1/2/4. Chọn **0,5** bằng waiting MAE
nhỏ nhất trong các cấu hình có replay coverage ≥5%, trước khi chạy test seeds.
1.285 physical probe cases. Selected coverage = 5,37%.

**Kết quả không thuận lợi cần giữ:** physical-only development MAE = 8,836 phút;
selected replay MAE = 9,211 phút. Quy tắc coverage chọn được threshold khả dụng
nhưng không chứng minh replay chính xác hơn physical-only. GUI giữ threshold
−1, không tự áp ngưỡng tổng hợp 0,5 lên Nha Trang. Primary B4 dùng replay ở
15,74% recommendation, phần còn lại fallback có nhãn.

Ridge penalties 0,1/1/10 được đánh giá trên cùng development traces, chỉ học khi
target bin đã đóng. Điều kiện chọn là workload MAE không tăng **và** waiting MAE
giảm. Không penalty nào đạt:

| Correction | Workload MAE, service-min | Waiting MAE, phút |
|---|---:|---:|
| Local, tắt correction | 9,220 | 9,140 |
| Ridge 0,1 | 9,331 | 9,159 |
| Ridge 1 | 9,356 | 9,269 |
| Ridge 10 | 9,328 | 9,233 |

Do đó primary B4-N giữ correction tắt và bằng B4 về quyết định; vẫn đo overhead
message. Supplementary bật correction rõ ràng để kiểm tra latency/graph.
Không dùng các lượt này để đổi penalty sau khi xem test results. Chi tiết:
[development_calibration.json](../outputs/recommendation_validation/development_calibration.json),
[neighbor_development.json](../outputs/recommendation_validation/neighbor_development.json).

## 7. Ideal benchmark và giới hạn chưa kiểm chứng

Một run ideal architecture 48 giờ seed 1, budget **2.000 iterations/batch**:
460 completed, 52 unfinished, mean started-session waiting 162,74 phút và P95
401,90 phút. **Cả 192 batch timeout**; relative gap trung bình 0,653.
Đây chỉ là finite-budget coordinated policy, tuyệt đối không gọi là relaxed
optimum hoặc bound cho actual waiting của recommendation. LB≤UB và repair
không tăng UB được audit trên từng snapshot.

Lượt thử 20.000/batch đã bị dừng do thời gian chạy, không được tính là benchmark
hoàn tất; có record riêng `ideal_20000_aborted.json`. Default solver vẫn 20.000,
không đổi thuật toán hay âm thầm nâng/hạ budget để nhận convergence.

Các giới hạn cụ thể:

* Chưa có 48 giờ Nha Trang full-population, step 1 giây. GIS hiện được kiểm chứng
  compile/smoke và bảo toàn dữ liệu/display; primary results là synthetic.
* B4/B4-N chưa chứng minh lợi ích nghiên cứu vượt B3. Không có empirical arrivals,
  compliance, tariff hoặc speed-dependent consumption calibration.
* Degree 1 và 3 cho cùng graph trong fixture hai trạm; TOP_K=3 không loại trạm
  nào. Replay-count fixture seed 13 không có scenario được chấp nhận. Các lượt
  này kiểm tra cấu hình nhưng không đủ thông tin để kết luận sensitivity.
* Chưa chạy degree 5/candidate-overlap communication ablation, multi-station
  normalization study, EWMA hoặc full N/M/demand scalability sweep. Mạng 100
  trạm chỉ có 8 requests/800 queries: functional stress, không phải city-scale proof.
* LIMITED dùng waiting curve một phút, xấp xỉ bảo thủ từ snapshot cũ. Route được
  tính lại bằng cùng graph/policy, chưa khóa path object bất biến; tie/congestion
  có thể gây ETA error. Chưa có energy-constrained fastest-path solver.
* Payload bytes là logical GAMA string length; payload ASCII benchmark tương
  ứng UTF-8 nhưng không phải JSON/network wire bytes. Không có network deployment.
* Spread giữa replay scenarios không phải calibrated confidence interval. Replay
  không tạo được demand shapes chưa từng có trong history.
* Economic comparators có interface cấu hình; chưa có hệ số nên chưa chạy study
  tiền điện. Một số artifacts trước lần làm sạch exporter còn cột legacy
  `extra_electricity_vnd`; cột này không dùng để ranking/evaluation. Exporter cuối
  để trống ở recommendation; tiền chỉ có ý nghĩa khi cấu hình monetary rõ ràng.
* Chưa có Robot→EV và không có chứng nhận global optimum cho actual waiting.

## 8. Chạy và đọc kết quả

Trong GAMA mở `models/main.gaml` → **Run me**. Mặc định recommendation/B4/LIVE,
step 60 giây (1 phút/cycle), ALL_FEASIBLE, FOLLOW_RECOMMENDATION. Threshold chưa hiệu chỉnh thì
fallback physical-only có nhãn. Monitor **Results directory** chỉ thư mục run.

```bash
.venv/bin/python -m unittest discover -s tests -v
python3 scripts/check_gama.py --suite
python3 scripts/check_gama.py --phase-a --gis
.venv/bin/python scripts/recommendation_experiments.py --seeds 10 --hours 48
.venv/bin/python scripts/recommendation_sensitivity.py
.venv/bin/python scripts/report_recommendation.py
```

Mỗi prefix lưu `_recommendation_config.csv`, `_recommendations.csv`,
`_recommendation_candidates.csv`, `_recommendation_unavailable.csv`, `_events.csv`,
`_forecasts.csv`, `_forecast_errors.csv`, `_communication.csv`,
`_recommendation_metrics.csv`, `_physical_summary.csv`, `_demand.csv`.
Evaluator thêm `_session_evaluation.csv` và `_evaluation.json`. Đọc prefix từ
manifest để không trộn run cũ/mới. Final metadata exporter bổ sung các cột giải
thích; evaluator vẫn đọc được các CSV schema 2 trước bổ sung.
