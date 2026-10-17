# Refactor objective intent-service-5

Trạng thái: **IMPLEMENTED BUT NOT FULLY VALIDATED**. Refactor và các regression dưới đây đã thực thi; scientific design freeze chưa đạt.

## Đường thực thi có thẩm quyền

- `ChargingService.gaml`: sự kiện đến trạm, xếp hàng, cấp cổng, sạc, kết thúc attempt và hủy vật lý.
- `Mobility.gaml`: driving, chiều dài tuyến và bộ đếm quãng đường; EV bổ sung tiêu hao trong `ChargingService.gaml`.
- `ranr/Fleet.gaml`: đặc tính EV/lịch ngoại sinh, nhu cầu SOC, intent, retry, deadline snapshot, thời gian trạng thái, exposure và nghĩa vụ di chuyển.
- `ranr/Runtime.gaml`: khởi tạo, xử lý request, đổi trạm, trao đổi bản tin, Measurement/Drain và xuất kết quả.
- `ranr/Math.gaml`: phân bổ công suất dùng chung, tích phân dịch vụ FIFO, RNG keyed và normalization của chính sách.
- `ranr/Prediction.gaml` và `ranr/Policy.gaml`: ETA Monte Carlo, thông tin P2P cục bộ và lựa chọn không ràng buộc.
- `ranr/Evaluation.gaml`: duy nhất hàm chấm fitness nghiên cứu.
- Python `headless`, `gui_collection`, `contracts`: chạy cùng GAMA, kiểm chứng ledger và tương thích artifact.
- Python `training`: duy nhất CMA-ES; rank lexicographic trong thế hệ, chọn incumbent theo validation vector gốc.
- Python `pipeline`, `benchmarking`, `design`, `analysis`, `development`: calibration, ghép cặp và báo cáo; không có simulator Python thay GAMA.

## Định nghĩa mới

Bản trước gắn deadline intent với giới hạn episode, đặt hạn attempt theo thời điểm retry, hủy vật lý khi quá hạn và cắt timestamp kết thúc về deadline. Bản refactor bỏ các liên kết này.

Deadline bất biến: thời điểm tạo intent + 360 phút. Deadline là tiêu chí đánh giá, không hủy phiên sạc. Retry giữ cùng intent và deadline. Thiếu năng lượng trước deadline không được gọi là trễ deadline. Phiên hoàn tất muộn giữ `energy_complete=true`, `deadline_missed=true`, `on_time=false`.

Intent terminal chỉ gồm completed/failed/unresolved. Deferred và retry thuộc lịch sử attempt. Cuối quan sát, unresolved được giữ là censored và ghi đầy đủ hoạt động đã xảy ra.

Fitness vector lần lượt là stranded EV / planned EV-days; nghĩa vụ di chuyển chưa phục vụ / planned EV-days; intent không hoàn tất đúng hạn / planned EV-days; kWh thiếu tại cuối quan sát / planned EV-days; operational objective.

Operational objective = 0.5 × mean completion time/360 + 0.3 × observed physical wait P95/360 + 0.2 × workload pressure. Conditional metric không có mẫu được ghi null cùng sample count bằng 0. Rank của một thế hệ không phải fitness để so với thế hệ khác.

Công thức thực thi với Measurement `[360,3960)`:

```text
EVdays = ((N_private + N_taxi) * 3600
          + sum(max(0, min(planned_depart,3960) - max(planned_arrival,360))
                for each planned inbound EV)) / 1440
F = [N_stranded/EVdays, N_mobility_unserved/EVdays,
     N_intent_not_on_time/EVdays, unmet_kWh_at_observation_end/EVdays, J_op]
Q = max_station,time E_wait / (E_wait + 6 * P_eff)
P_eff = all_physical_backlog_battery_kWh / frozen_FIFO_clearance_hours
```

Xe thường không thuộc EVdays. Hàng chờ rỗng cho Q=0; hàng chờ dương không thể phục vụ cho Q=1 và zero-capacity flag. Tử số pressure chỉ gồm xe chờ; clearance giữ cả xe đang sạc và xe ngoài cohort. Intent hoàn tất có unmet=0 trong tolerance; hoàn tất muộn vẫn tính not-on-time.

Exposure EV-ngày giữ cả xe vào mạng theo lịch nhưng bị chặn. Hoạt động dự kiến giữ nguyên nếu xe đứng yên hoặc stranded. Báo cáo nguyên nhân quan sát được; không suy diễn quan hệ nhân quả của chính sách.

Áp lực: năng lượng hàng chờ / (năng lượng hàng chờ + công suất hữu hiệu × 6 giờ), cực đại qua Measurement và Drain. Công suất hữu hiệu được tính bằng giải phóng backlog vật lý FIFO, gồm các cổng đang bận và xe Warm-up. Không dùng công suất đang rảnh làm mẫu số. Default taper phẳng và tổng giới hạn trạm bằng tổng cổng; đây không phải đường cong taper hay giới hạn điện lưới đã khảo sát tại Nha Trang.

## Kiểm tra

Các lệnh nền:

```bash
MPLCONFIGDIR=/tmp/ranr-mpl .venv/bin/python -m unittest discover -s tests -v
MPLCONFIGDIR=/tmp/ranr-mpl .venv/bin/python -m ranr.gama.cli validate --compile
```

Kết quả thực thi và giới hạn nằm ở phần bàn giao bên dưới. Biên dịch hoặc fixture nhỏ không chứng minh đã kiểm chứng toàn bộ fleet 4700 xe trong 72 giờ.

## Thu lại calibration

Cấu hình chính thức: `configs/gama/calibration.json`, Warm-up 360 phút, Measurement 3600 phút, Drain 360 phút, bước 60 giây. Ba seed 800001, 800002, 800003 phải dùng cùng phiên bản nguồn và objective hash.

GUI: mở `models/main.gaml`, chọn Collect training data, đặt Calibration seed trong nhóm Collection trước Initialize, Play đến khi trạng thái collection complete. Nếu experiment đã tự khởi tạo, đổi seed rồi Reload/khởi tạo lại; không chỉ sửa seed ở giữa lượt. Đóng experiment, lặp lại cho hai seed còn lại; sau đó chọn Validate and build calibration. Không sửa nguồn/cấu hình trong lúc thu.

Headless (chỉ thực hiện khi bắt đầu thu mới):

```bash
.venv/bin/python -m ranr.gama.cli --config configs/gama/calibration.json calibrate --output outputs/gama_ranr/calibration/intent_service_5
```

Không khởi chạy CMA-ES chính thức trước khi calibration, physical consistency, pairing và scientific design freeze có bằng chứng. Dữ liệu objective cũ chỉ dùng lịch sử; không trộn hoặc resume checkpoint cũ.

## Thay đổi CMA-ES và tính hợp lệ

`generation_fitness` kiểm tra đủ sáu cặp scenario/seed và exposure/hash giống nhau trước `tell`. Vector được sắp thứ tự tuple; các tuple bằng nhau nhận cùng dense rank hữu hạn. Mảng rank trả về giữ thứ tự ứng viên đầu vào. Không dùng huge penalty hoặc `optimizer.result.xbest`.

Winner của thế hệ được đánh giá tại các mốc validation trên sáu seed cố định `21001+i`; candidate design dùng `11001+i`. Incumbent và model xuất bản được chọn bằng vector validation gốc. Cải thiện một tầng ưu tiên cao hơn luôn được chấp nhận; khi bốn tầng đầu bằng nhau, ngưỡng early stopping vận hành là 1% đã ghi trong đặc tả. Checkpoint schema 5 giữ pending population, pending validation, RNG và incumbent. Sai ledger dừng trước `tell`, lưu checkpoint/diagnostic; không tạo điểm thay thế.

Trường chính thức: `fitness_vector`, `operational_objective`, `generation_rank`, `objective_version`, `objective_config_hash`. Các thống kê request/attempt phục vụ chẩn đoán không phải mẫu số hay nhu cầu năng lượng chính thức; dùng `intent_requested_kwh`/`intent_delivered_kwh` và ledger intent cho năng lượng duy nhất.

Phép kiểm chứng Python độc lập đối chiếu identity, need–intent–attempt–outcome, interval, pin/tiêu hao/điện/tổn hao, lịch dự kiến và thời gian kết thúc quan sát. Đây là kiểm chứng kết quả GAMA, không phải evaluator/simulator song song.

## Tính tương thích và lưu dữ liệu

Collect cũ được người dùng xác nhận đã Stop trước khi chỉnh sửa. Không đóng ứng dụng GAMA. Snapshot trước sửa và mọi CSV vật lý cũ được giữ nguyên. Danh mục `historical_outputs.json` ghi các run cũ; `incompatible_artifacts.json` ghi calibration, validation và model/checkpoint không còn được dùng. Metadata dùng `HISTORICAL_ONLY` và `NOT_VALID_FOR_NEW_TRAINING`; không chuyển đổi fitness cũ sang định nghĩa mới.

Objective `intent-service-5`, lifecycle/outcome schema 5, environment `persistent-soc-activity-6`, observation `station-observation-4`. Loader/cache/checkpoint/model/calibration kiểm tra phiên bản và hash đặc tả; provenance còn khóa mã nguồn và cấu hình. Hash JSON chuẩn hóa của đặc tả:

```
0b32b80393e5e0304be5fc512f2ae6f36208ab0817954c697fb804ffd5f0fea8
```

## Danh mục file thay đổi

So với snapshot ngay trước refactor (bao gồm các chỉnh sửa người dùng đã có), có 42 file thêm/sửa/xóa. `Mobility.gaml` đã được đọc và giữ nguyên. Không sửa GIS số cổng.

| File | Mục đích |
| --- | --- |
| `README_GAMA.md` (modified) | Cập nhật objective, thời lượng và ranh giới dữ liệu lịch sử. |
| `README_LENH.md` (modified) | Lệnh kiểm tra và thu calibration 72 giờ với ba seed. |
| `configs/gama/calibration.json` (modified) | Đăng ký calibration 6h/60h/6h, bước 60 giây và phiên bản mới. |
| `configs/gama/calibration_4weeks.json` (deleted) | Loại profile 28 ngày khỏi cấu hình calibration đang hoạt động; bản cũ trong snapshot. |
| `configs/gama/environment.json` (modified) | Nâng phiên bản môi trường/observation, khóa objective hash và cấu hình công suất. |
| `configs/gama/objective.json` (added) | Đặc tả objective chuẩn hóa, tolerance, censoring và normalization để băm tương thích. |
| `configs/gama/research.json` (modified) | Đăng ký research 72 giờ và objective mới. |
| `configs/gama/smoke.json` (modified) | Fixture development giữ bước vật lý một phút và đủ Drain. |
| `docs/GAMA_ENERGY_CHARGING_VI.md` (modified) | Giải thích deadline không hủy sạc, năng lượng và trạng thái intent. |
| `docs/GAMA_EVALUATION_REFACTOR_VI.md` (added) | Bản đồ phụ thuộc, thay đổi, bằng chứng kiểm thử và giới hạn bàn giao. |
| `docs/GAMA_RANR_RUN_GUIDE_VI.md` (modified) | Hướng dẫn chạy/Collect với profile chính thức mới. |
| `docs/GAMA_SETTINGS_REFERENCE_VI.md` (modified) | Bỏ beta scalar cũ, cập nhật tham số và phiên bản. |
| `models/ChargingService.gaml` (modified) | Cấp công suất vật lý có ràng buộc; hạch toán pin/điện/tổn hao; sự kiện interval và tiếp tục sạc quá hạn. |
| `models/main.gaml` (modified) | Run me và Collect dùng cấu hình, phiên bản và hiển thị mới. |
| `models/ranr/Evaluation.gaml` (modified) | Thay evaluator cũ bằng vector lexicographic và operational metric có điều kiện. |
| `models/ranr/Fleet.gaml` (modified) | Lifecycle intent/attempt, deadline bất biến, snapshot, energy/time ledger, exposure và hoạt động dự kiến. |
| `models/ranr/Math.gaml` (modified) | Kernel cấp công suất và FIFO dùng chung; taper; thời hạn hỗ trợ ETA độc lập deadline đánh giá. |
| `models/ranr/Policy.gaml` (modified) | Giữ lựa chọn phi ràng buộc; tách thông tin arrival/exposure khỏi deadline dịch vụ. |
| `models/ranr/Prediction.gaml` (modified) | Dự báo dùng kernel dịch vụ chung; giữ phiên muộn và quan sát ETA hợp lệ. |
| `models/ranr/Runtime.gaml` (modified) | Measurement/Drain, chốt ledger và pressure, xuất fitness/vector và metric riêng theo loại EV. |
| `models/tests/RanrEnergyTests.gaml` (modified) | Regression deadline 360, sạc liên tục qua deadline và hoàn tất trong Drain. |
| `models/tests/RanrObjectiveTests.gaml` (modified) | Evaluator đối kháng, P95 vật lý, thiếu outcome/Drain và kernel công suất/taper. |
| `src/ranr/gama/analysis.py` (modified) | Không còn phân tích scalar failure/energy beta lỗi thời. |
| `src/ranr/gama/benchmarking.py` (modified) | Giữ bước một phút trong benchmark và đọc operational objective mới. |
| `src/ranr/gama/cli.py` (modified) | Đăng ký regression deadline/Drain và định danh validation mới. |
| `src/ranr/gama/contracts.py` (modified) | Kiểm chứng ledger, bảo toàn, exposure, phiên bản/hash, ghép cặp và rank lexicographic. |
| `src/ranr/gama/design.py` (modified) | Gate scientific freeze và selection bắt buộc có bằng chứng objective mới. |
| `src/ranr/gama/gui_collection.py` (modified) | GUI Collect kiểm chứng cùng ledger/configuration và từ chối kết quả không tương thích. |
| `src/ranr/gama/headless.py` (modified) | Đăng ký nguồn/cấu hình, chặn invalid fitness, khóa loader/cache và định danh model/calibration mới. |
| `src/ranr/gama/long_collection.py` (modified) | Supervisor dùng profile calibration 72 giờ; không resume tập 28 ngày cũ. |
| `src/ranr/gama/pipeline.py` (modified) | Calibration/publishing/report đọc phiên bản mới; null/n=0 được bảo toàn trong báo cáo. |
| `src/ranr/gama/training.py` (modified) | Rank trong thế hệ; incumbent validation vector; checkpoint/resume schema 5; invalid chặn trước tell. |
| `src/ranr/gama/validation.py` (modified) | Giữ assertion/runtime checks, loại đúng cảnh báo bộ nhớ 0MB giả đã biết của GAMA 1.9.3. |
| `tests/fixtures/gama_parameters.json` (modified) | Fixture parameter record dùng phiên bản/hash mới. |
| `tests/gama_ledger_fixture.py` (added) | Dữ liệu tổng hợp nhất quán cho kiểm chứng, không phải simulator. |
| `tests/gama_queue_pressure.gaml` (added) | Regression station pressure và physical allocation, ETA lookback vượt 360 phút. |
| `tests/test_gama_backend.py` (modified) | Tương thích backend, optimizer và nguồn mới. |
| `tests/test_gama_contracts.py` (modified) | Kiểm chứng decomposition và schema mới. |
| `tests/test_gama_evaluation.py` (added) | Đối kháng drop/retry/deadline/energy; rank, pairing, invalid-before-tell và chọn vector validation. |
| `tests/test_gama_long_collection.py` (modified) | Supervisor 72 giờ và registration mới. |
| `tests/test_gama_physical_records.py` (modified) | Fixture physical ledger và phát hiện dữ liệu vật lý sai. |
| `tests/test_gama_unified.py` (modified) | GUI/shared contracts, thiếu need/interval, model cũ, resume và null report. |

## Kết quả thực thi và phạm vi bằng chứng

Artifact kiểm chứng nằm tại:

```
outputs/gama_ranr/audits/evaluation_refactor_1792128000353633783/
```

- `source_before.tar.gz`, `before.json`: trạng thái trước sửa, không reset các chỉnh sửa đã có.
- `modified_files.json`: mục đích và SHA trước/sau của 42 file.
- `final_source.json`: provenance dùng cho kiểm tra cuối.
- `python_tests.log`, `queue_pressure.log`, `paired_72h.log`, `gui_initialization.log`: log thực thi.
- `paired_72h_final_source/*`: dữ liệu GAMA, ledger và physical validation của bốn phương pháp.
- `gui_initialization_final_review.json`, `.resources.json`: cấu hình, fleet/cổng và tài nguyên khởi tạo Collect.
- `historical_outputs.json`: 94 thư mục output cũ được đánh dấu lịch sử.
- `incompatible_artifacts.json`: 13 artifact cũ không tương thích, vẫn được bảo toàn.

Các lệnh thực tế của đợt kiểm chứng cuối:

```bash
MPLCONFIGDIR=/tmp/ranr-mpl .venv/bin/python -m unittest discover -s tests -v
MPLCONFIGDIR=/tmp/ranr-mpl RANR_JAVA_HEAP_MIB=6144 .venv/bin/python -m ranr.gama.cli validate --compile
MPLCONFIGDIR=/tmp/ranr-mpl RANR_JAVA_HEAP_MIB=4096 .venv/bin/python /tmp/ranr_final_pairing.py
MPLCONFIGDIR=/tmp/ranr-mpl RANR_JAVA_HEAP_MIB=12288 .venv/bin/python /tmp/ranr_gui_collect_init.py
MPLCONFIGDIR=/tmp/ranr-mpl RANR_JAVA_HEAP_MIB=4096 .venv/bin/python /tmp/ranr_unresolved_integration.py
MPLCONFIGDIR=/tmp/ranr-mpl .venv/bin/python -c "from ranr.gama.validation import run_model; run_model('tests/gama_queue_pressure.gaml','ranr_queue_pressure',1,'RANR_QUEUE_PRESSURE_PASS')"
```

Các helper `/tmp` được lưu bản sao trong thư mục audit (`paired_72h_command.py`, `gui_initialization_command.py`, `unresolved_72h_command.py`). Chúng gọi pipeline GAMA hiện hữu, không triển khai simulator hay evaluator thay thế.

Đã qua trên nguồn cuối:

- 84/84 test Python, gồm rank/tie, invalid-before-tell, checkpoint/resume, worker invariance, chọn incumbent qua hai thế hệ, kiểm tra tell không được gọi khi invalid, từ chối model/calibration cũ và các phép biến đổi ledger đối kháng.
- Biên dịch 29/29 root GAML; fixture queue pressure riêng cũng biên dịch và chạy qua marker.
- Bốn phương pháp: mỗi lượt đủ phút 4320, đội xe development 6 xe (2 thường/2 private EV/2 taxi), 11 trạm/125 cổng, MC=1, không inbound. Mỗi lượt có cùng 10 planned EV-days, 5 Measurement intent, 126/126 nghĩa vụ Measurement hoàn tất; mọi physical validation qua. Đây là kiểm tra tích hợp, không phải so sánh hiệu năng chính thức.
- GUI Collect entry point được chạy một cycle qua headless launcher: 4700 xe, 11 trạm, 125 cổng; planned exposure 4432.91214526 EV-ngày; cấu hình 360/3600/360 phút và bước 60 giây. Đánh dấu `TEST_ONLY`, không nhận là calibration. Simulation phase khoảng 153 giây, RSS đỉnh khoảng 2.48 GiB trong lượt này; không suy ra runtime 72 giờ từ phép đo khởi tạo.

Lượt đối kháng luôn hoãn sạc cũng đã đủ 72 giờ và qua physical validation: cùng 10 EV-ngày; 269 recommendation attempt vẫn chỉ thuộc 3 intent, không nhân nhu cầu theo retry. Số Measurement intent là 3 so với 5 ở baseline, 88/126 nghĩa vụ chưa phục vụ, 3 intent không đúng hạn và 89.317573 kWh thiếu. Fitness `[0,8.8,0.3,8.9317573,0]` kém baseline dù operational objective bằng 0. Ở baseline, 5 xe vào sạc ngay vẫn tạo 5 mẫu chờ bằng 0; lượt luôn hoãn chưa từng tới trạm có 0 mẫu chờ và P95=null. Không có mẫu hoàn tất hay tới hàng chờ thì metric là null/n=0. Thử xóa một outcome unresolved bị từ chối. Đây là bằng chứng tích hợp về nhu cầu SOC nội sinh và việc không thể lợi dụng mẫu vận hành rỗng để bù thất bại phục vụ.

Bộ `validate --compile` đã kết thúc exit 0 trên cùng provenance: **29/29 compile và 45/45 lượt fixture GAMA qua**, cộng fixture queue pressure riêng. Có regression lifecycle/ngày cuối, khóa cấu hình, ghép cặp bốn phương pháp, 12 tình huống SOC/hoạt động, SOC ba ngày, full-fleet trait distributions và charging episode. Ca deadline có deadline=360, hoàn tất thực tại phút **813.33333333** trong Drain; vẫn `energy_complete=true`, `deadline_missed=true`, `on_time=false` và chỉ một attempt.

Lượt kiểm chứng cuối không có test fail hoặc skip. Trong quá trình bổ sung test hai thế hệ, helper ban đầu đọc sai cấp thư mục validation; helper đã được sửa và chạy lại toàn bộ 84 test qua. Các lượt trước bị dừng khi sửa nguồn chỉ là chẩn đoán, không dùng làm bằng chứng cuối. Chi tiết máy đọc được ở `final_validation_review.json`; đây không phải chứng nhận full-scale/scientific freeze.

## Giới hạn và điều kiện trước huấn luyện chính thức

Chưa chạy bộ 72 giờ với toàn bộ fleet 4700 xe và inbound, chưa thu lại đủ ba seed calibration, chưa làm estimator-accuracy/design benchmark chính thức cho sáu scenario, chưa thao tác desktop GUI để so sánh hai lượt đầy đủ GUI/Headless. Full-fleet initialization và fixture nhỏ không thay thế các bằng chứng đó.

Giới hạn công suất tổng mặc định bằng tổng công suất cổng và taper mặc định phẳng là giả định mô hình hiện hành, chưa được xác nhận bằng dữ liệu thực địa. Kernel dịch vụ và pressure đã có regression công suất/taper; độ chính xác dự báo với cấu hình aggregate bị giới hạn cùng taper tùy chỉnh vẫn cần benchmark hiệu chỉnh. Chỉ số workload pressure không được diễn giải là thời gian chờ chính xác.

Không có CMA-ES chính thức, 720 lượt đánh giá hay publication experiment nào được tự khởi chạy trong refactor. Objective specification đã có phiên bản/hash cố định; scientific design freeze chưa đạt. Gate training vẫn yêu cầu calibration, physical validation, benchmark và freeze tương thích nguồn hiện tại.

Trạng thái bàn giao: **IMPLEMENTED BUT NOT FULLY VALIDATED**. Cần đọc kết quả kiểm chứng cuối bên trên và `final_validation_review.json`; không diễn giải trạng thái này thành xác nhận mô hình thực địa hoặc cho phép huấn luyện chính thức.
