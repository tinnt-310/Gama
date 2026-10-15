# Chạy GAMA và thu calibration

Mở `models/main.gaml` trong GAMA. Chọn **Run me**, rồi Play để xem bản đồ, xe và trạm sạc. Tất cả xe thường trực tồn tại từ đầu:3000 ô tô thường,1000 EV cá nhân,700 taxi. Xe đỗ vẫn thuộc thành phố; visitor chỉ được thêm dần qua gates trong giờ cao điểm. Giờ bắt đầu00:00.

Khi chưa có model đã học, Auto GUI preview gắn nhãn untrained và cho phép development weights; không đổi fleet, samples, demand, giờ hoặc vật lý. Không trình bày kết quả preview thành trained research.

## Thu dữ liệu bằng giao diện, không cần gõ terminal

1. Chọn experiment **Collect training data**.
2. Chọn Calibration seed800001 rồi Play. Experiment đăng ký cấu hình chuẩn từ đầu; theo dõi bản đồ và Calibration status.
3. Đợi episode hoàn tất, có completion và trạng thái collection complete. Chạy lại tương tự với800002 và800003.
4. Trong bảng User commands của GAMA chọn **Validate and build calibration**. Kết quả kiểm chứng và đường dẫn hiện trong status/console.

Mỗi lượt có thư mục `outputs/gama_ranr/gui_calibration/runs/collect_<seed>_<timestamp>/`. Build tạo calibration bất biến dưới `gui_calibration/builds/` và con trỏ latest.json. Pipeline Python tự nhận con trỏ khi config calibration để trống.

Collection thực thi controlled opportunities trên fleet hiện hữu và recommendation thăm dò có xác suất đã đăng ký. EV vẫn chọn độc lập. Mục đích là thu thống kê response quan sát được, snapshot reconstruction, ETA và priors; không phải đánh giá model đã học.

Không nhận lượt dừng sớm, thiếu ledger/outcomes, duplicate, sai source/config/hash hoặc không đủ dữ liệu. Nếu episode không tạo đủ phiên sạc tự nhiên, báo thiếu dữ liệu; không ép SOC hay thêm xe. Chạy đủ ba seed không tự bảo đảm đủ mẫu. Không sửa mã trong khi collection đang chạy vì source hashes phải giữ nguyên.

## Lệnh cho điều phối và kiểm chứng

```bash
.venv/bin/python -m unittest discover -s tests
.venv/bin/python -m ranr validate --compile
.venv/bin/python -m ranr --config configs/gama/smoke.json smoke --output outputs/gama_ranr/smoke/my_run
```

Các bước dài chỉ chạy khi chủ động yêu cầu:

```bash
.venv/bin/python -m ranr --config configs/gama/calibration.json calibrate
.venv/bin/python -m ranr development-validation
.venv/bin/python -m ranr benchmark
.venv/bin/python -m ranr design-validation
.venv/bin/python -m ranr freeze-design outputs/gama_ranr/design/release decision.json
.venv/bin/python -m ranr --config outputs/gama_ranr/benchmark/release/locked_config.json train
```

Design validation dùng seed development24001/2/3, không dùng30 seed test. So sánh temperature0.1/0.2/0.3/0.5, heartbeat1/2/5, stabilityoff/smoothing/hysteresis và responsehigh/moderate/low/contextual/misspecified. Các lượt này có thể tốn đáng kể; không tự chạy khi mở GUI hay build calibration.

Freeze yêu cầu review có hash và selected_config explicit; training kiểm tra current source, calibration, development, benchmark/accuracy và freeze. Training+validation tối đa72 giờ, không tự mở khi thu dữ liệu. Resume chỉ dùng artifacts đúng nguồn. Test cuối6×4×30=720 GAMA runs là held-out, không dùng chọn thiết kế.

Output Run me nằm riêng dưới `outputs/gama_ranr/gui/gui_<timestamp>_<seed>/`. Các CSV flush trong lúc chạy; metrics/outcomes/opportunity_outcomes/completion đầy đủ sau settlement. Thời gian mô phỏng khác thời gian thực; chỉ benchmark thực mới cho dự toán đáng tin.
