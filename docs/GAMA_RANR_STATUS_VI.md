# Trạng thái triển khai môi trường thống nhất

Phiên bản **persistent-controlled-v2**, ngày 15/10/2026. Hồ sơ chi tiết: `outputs/gama_ranr/unified_fleet_v2_20261015/validation.json` sau audit cuối.

## Đã triển khai

- Một mô hình: 3.000 ô tô thường, 1.000 EV cá nhân, 700 taxi điện; SOC vật lý, xe thường trực được giữ khi đỗ, sạc xong hoặc stranded.
- Controlled opportunities gắn ID xe; threshold SOC <30%, public-only, target 80%, lịch theo giờ/loại và burst có báo thiếu hụt.
- Traffic plan nhập dần qua cửa ngõ GIS, cap 30% từng loại, xuất tại exit; không xóa ngay khi hết rush. Traffic độc lập demand và còn hoạt động trong settlement.
- GUI/Headless chung GAML; preview không đổi vật lý. Cấu hình tổng EV là giá trị suy ra. Model/calibration v2 kiểm tra môi trường và nguồn; artifacts cũ được giữ nguyên.
- Collect training data: chọn ba seed trên GUI, registration/provenance, trạng thái tiến độ, nút Validate and build calibration; Python chỉ kiểm chứng/tổng hợp.
- Source backup, cập nhật GUI/CLI/docs, compile nhiều GAML root trong một JVM; output mỗi run riêng, kể cả daily statistics.

## Bằng chứng kiểm tra nhỏ

- Startup Run me native GAMA một bước: đúng **4700** xe, **00:00**, **32 samples** không bị preview giảm, Computer xuất ảnh.
- Fixture bốn phương pháp: SOC đúng ngưỡng, duplicate opportunity, stranded giữ agent, thiếu hụt burst, nhập tại gateway, không xóa khi đang chạy và xuất tại exit. No-P2P thông điệp bằng 0; No-Prediction future_calls=0.
- Fixture physics FIFO/cổng/EV power/energy, scientific, information, parameter loader và scenario cache đạt.
- Smoke ghép cặp bốn phương pháp với fleet 2/3/2 và horizon rất ngắn hoàn tất; cùng initial/opportunity/traffic hash. Có 0 request kích hoạt trong smoke tự nhiên này; không coi đó là đo chất lượng recommendation. Fixture riêng kiểm tra activation thực và vật lý sạc.
- 23 unit tests kiểm tra cấu hình, model cũ, registration, thiếu seed, dừng sớm, sai source/config, thiếu outcome, tampering, thiếu calibration samples và build đủ ba seed. Dữ liệu synthetic của unit tests không phải kết quả nghiên cứu.
- Collection startup native một bước đăng ký đúng cấu hình và hiển thị Computer/Calibration status. Lượt smoke bị dừng sớm được lưu riêng, không nhận làm calibration hoàn chỉnh.

## Còn chờ thực nghiệm

Chưa có ba episode calibration hoàn chỉnh, kiểm chứng development dài theo ngày, hiệu chỉnh cửa ngõ/thời gian hoạt động ngoài thực địa, benchmark đầy đủ, accuracy gate mới, training CMA-ES, long model validation hoặc 720 test runs cho môi trường này. Training chính bị khóa cho tới khi các gate tương ứng đạt.

Chưa tự động hóa thao tác click trong GAMA Workbench; compile, rendering, user-command registration và startup đã kiểm tra bằng native Headless. Build/validator được kiểm thử bằng unit fixtures; chưa có bằng chứng end-to-end ba lượt GUI nhiều giờ. Không trình bày smoke hoặc kết quả Python lịch sử thành bằng chứng hoàn tất nghiên cứu.

Cách thu dữ liệu bằng giao diện: [hướng dẫn](GAMA_RANR_RUN_GUIDE_VI.md). Cây thư mục và trách nhiệm: [kiến trúc](GAMA_RANR_ARCHITECTURE_VI.md). Các giả định/công thức: [hồ sơ khoa học](GAMA_RANR_SCIENTIFIC_CHANGES_VI.md).
