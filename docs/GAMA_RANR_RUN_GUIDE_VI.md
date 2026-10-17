> Objective hiện hành: `intent-service-5`, fitness lexicographic. Xem [báo cáo refactor](GAMA_EVALUATION_REFACTOR_VI.md) để biết kiểm chứng và điều kiện thu lại dữ liệu.

# Chạy GAMA và thu calibration

Mở `models/main.gaml`, chọn **Run me** để quan sát hoặc **Collect training data** để thu dữ liệu. GUI và Headless dùng chung mã GAML, cùng hành vi sạc `persistent-soc-activity-6`.

**Run me** mặc định **1 phút/cycle**, **72 giờ** = 6 giờ warm-up +60 giờ measurement +6 giờ drain. **Collect training data** nạp profile **72 giờ/seed**, cũng 1 phút/cycle (360 phút warmup +3.600 phút measurement +360 phút drain). Fleet thường trực: **3000 ô tô +1000 EV cá nhân +700 taxi**; tối đa 1410 xe inbound đang hiện diện, tổng tối đa 6110. Có 11 trạm công cộng và 125 cổng. Xe thường trực giữ identity và SOC qua các ngày, không bị xóa sau sạc.

## Quyết định sạc hiện tại

Không còn lịch sạc ngẫu nhiên hoặc quota yêu cầu/ngày. Mỗi EV có ngưỡng pin và mức sạc đích ưu tiên riêng, lấy mẫu một lần theo seed. EV xét sạc khi xuống ngưỡng, chuẩn bị chuyến thiếu năng lượng, đến nơi hoặc đến điều kiện xét lại. Taxi xét thêm ca làm việc, booking đã biết và kỳ nghỉ; không bỏ hành khách giữa chuyến.

Các phân phối, reserve và cooldown nằm trong [environment.json](../configs/gama/environment.json). Mô tả đầy đủ, state machine và giới hạn mô hình ở [Sạc theo SOC và hoạt động](GAMA_ENERGY_CHARGING_VI.md). Có thể xem `soc_request_threshold`, `soc_preferred_target`, `soc_session_target`, `charging_intent_id`, `current_activity` khi inspect EV.

Xe đỗ/đợi hoạt động vẫn được vẽ. `energy_hold` nghĩa là xe đang giữ chuyến để xử lý năng lượng; `stranded` nghĩa là thực sự hết pin. Theo dõi **Charging intents**, **Charging requests (cumulative)**, **Charging retries**, **Waiting EVs**, **Charging EVs**, **Stranded EVs** và **Moving vehicles** để phân biệt các tình trạng.

## Thu dữ liệu bằng giao diện

1. Đóng experiment cũ, Refresh dự án, mở **Collect training data**.
2. Trong **Collection → Calibration seed**, chọn **800001** trước khi khởi tạo. Nếu experiment đã tự khởi tạo, đổi seed rồi bấm **Reload/khởi tạo lại** vì tham số yêu cầu restart. Giữ **Render displays = true** để xem xe trên bản đồ, rồi Play. Monitor **Collection duration (days)** phải là **3**.
3. Đợi **COLLECTION COMPLETE**. Khởi tạo lại và làm tương tự với **800002**, rồi **800003**.
4. Chọn **Validate and build calibration** trong User commands khi đủ ba lượt hoàn tất cùng nguồn/cấu hình.

Collection tự nạp [calibration.json](../configs/gama/calibration.json) trước khi khởi tạo. Muốn đổi cấu hình collection phải chỉnh profile trước khi mở experiment; ô GUI bị profile ghi đè khi chuẩn bị lượt thu. Ba seed phải cùng mã và cùng cấu hình vật lý/hành vi. Không sửa mã hoặc profile giữa lượt. Dữ liệu từ lịch sạc cũ không dùng cho môi trường mới; các thư mục lịch sử được giữ lại. Hướng dẫn chuyển giữa GUI và chạy nền: [README_LENH.md](../README_LENH.md).

Mỗi lượt có thư mục riêng `outputs/gama_ranr/gui_calibration/runs/collect_<seed>_<timestamp>/`. Builder tạo calibration bất biến ở builds/ và con trỏ latest.json. Headless cũng có thể ghi những lượt mới vào cây thư mục này, với manifest/provenance của chính nó.

Thu calibration dùng recommendation thăm dò có xác suất đã đăng ký, cùng phản ứng tự quyết của EV. Không ép SOC, không thêm EV để tạo mẫu và không bảo đảm đủ mẫu chỉ vì đã chạy ba seed. Đây là calibration vật lý/response, chưa phải huấn luyện CMA-ES hoặc kết quả đánh giá model đã học.

## Thời gian và kết thúc

`step=60` nghĩa là 60 giây **mô phỏng**, không phải 60 giây máy tính. Tổng thời lượng là `warmup_minutes + measure_minutes + deadline_minutes`: **Run me** mặc định 4320 phút; **Collect training data** là **360 +3.600 +360 =4.320 phút**. GAMA bắt đầu cycle từ 0, nên số cycle hiển thị có thể là 4.321 khi collection hoàn tất. Xác nhận kết thúc bằng monitor **COLLECTION COMPLETE**.

Trong drain, intent cũ vẫn được xử lý và thử lại dưới ID gốc; không tạo intent mới cho dân số đo. Phiên chưa xong cuối drain được ghi nhận chưa giải quyết, không ép sạc hoàn tất. CSV thống kê trạm chốt đủ các ngày, gồm ngày cuối (collection 72 giờ: ngày 1–3), và dùng các cột lũy kế.

Cấu hình nghiên cứu và calibration chính thức phải giữ 72 giờ và bước 60 giây. Chỉ trong thử nghiệm development riêng, để thử tổng N ngày, đặt `measure_minutes = N ×1440 − warmup_minutes − deadline_minutes`, giữ giá trị dương. Trong Run me chỉnh các ô thời lượng trước khi khởi tạo. Trong collection chỉnh profile, rồi thu lại cả ba seed. Các bước 600 giây hoặc 3600 giây vẫn có thể dùng cho thử nghiệm thô; cần kiểm chứng sai lệch trước khi dùng cho nghiên cứu. Cấu hình chuẩn hiện tại vẫn là 60 giây.

## Kiểm chứng và chạy Headless

```bash
.venv/bin/python -m unittest discover -s tests
.venv/bin/python -m ranr.gama.cli validate --compile
.venv/bin/python -m ranr.gama.cli --config configs/gama/calibration.json calibrate --output outputs/gama_ranr/calibration/intent_service_5
```

Lệnh calibrate chạy lần lượt ba seed 800001/800002/800003 và build calibration từ các lượt đã kiểm chứng; không chạy CMA-ES. Lệnh `run` với research.json dùng cùng 72 giờ và bước 60 giây. Smoke và các fixture có horizon riêng nhằm kiểm tra nhỏ.

Đọc [trạng thái nghiệm thu](GAMA_RANR_STATUS_VI.md) để biết các bộ dữ liệu đã thu thật và kết quả kiểm thử. Training chính vẫn cần correctness, long development validation, benchmark/accuracy, sensitivity và design freeze mới, tương ứng nguồn hiện tại.

## Lỗi và dữ liệu đầu ra

Nếu đăng ký collection thất bại, **RANR error**, **Calibration status** và failure.json giữ nguyên lý do gốc; không chạy runtime trên thế giới chưa khởi tạo. Đổi tham số vật lý/hành vi giữa lượt báo `Configuration changed: <setting>; restart required`. Rendering và kích thước biểu tượng xe được phép điều chỉnh.

Mỗi lượt hoàn tất có completion.json, configuration.json, manifest.json, physical_validation.json, charging_intents.json, request_attempts.json, intent_outcomes.json, outcomes.json và các CSV diễn biến. Không nhận lượt dừng sớm, thiếu outcome, trùng request, sai nguồn/cấu hình, vi phạm SOC hoặc cấp/trả cổng. Lượt lỗi được giữ riêng để điều tra; không ghép thành lượt hoàn tất.

## Release có lưu trạng thái

Dùng `python -m ranr.gama.release start/status/stop/resume` theo [README_LENH](../README_LENH.md). Mỗi stage ghi log, hash và trạng thái; dừng ở gate lỗi. Calibration lịch sử cần compatibility + replay, không thay source hash. Pipeline có thể thu lại ba seed trên nguồn hiện hành nếu không chứng minh được tái sử dụng. Accuracy trước development/design; performance sau freeze. Ngân sách 72 giờ dành riêng training, cộng qua resume; evaluation dùng 30 seed chưa dùng để chọn model.
