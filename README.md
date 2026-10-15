# RANR-AW — GAMA, đội xe thường trực và nhu cầu sạc có kiểm soát

GAMA 1.9.3 thực thi mô phỏng vật lý và bốn thuật toán RANR-AW, No-P2P, No-Prediction, Fixed-Weights. Python điều phối GAMA Headless, CMA-ES và phân tích dữ liệu GAMA.

Môi trường `persistent-controlled-v2` khởi tạo **3.000 ô tô thường, 1.000 EV cá nhân, 700 taxi điện**. Xe đỗ vẫn tồn tại; cơ hội sạc không tạo xe. Chỉ sạc công cộng tại 11 trạm, 125 cổng, 7.195 kW. Chỉ xe có SOC dưới 30% và không có phiên đang xử lý mới kích hoạt yêu cầu. Đội xe và tần suất là giả định nghiên cứu, chưa phải thống kê thực tế Nha Trang.

Giờ cao điểm 05:30–07:30 và 17:00–20:00: xe nhập dần từ cửa ngõ mạng đường, tối đa 900/300/210 xe bổ sung đang hiện diện. Chỉ xe vãng lai được xóa khi tới cửa ngõ ra. Tổng tối đa 6.110 xe.

**Thu dữ liệu không cần terminal:** mở `models/main.gaml` → **Collect training data** → chọn seed 800001, 800002, 800003 lần lượt → Play tới khi `COLLECTION COMPLETE`. Sau ba lượt, chọn **Validate and build calibration** trong bảng Commands. Dữ liệu thiếu hoặc chưa đủ mẫu bị từ chối. [Hướng dẫn chi tiết](docs/GAMA_RANR_RUN_GUIDE_VI.md).

**Run me** dùng cùng GAML và cùng mô hình; Computer hiển thị bản đồ, xe và trạm. Nếu chưa có model, Auto GUI preview chỉ cho phép trọng số development và hiển thị nhãn UNTRAINED; không thay fleet, giờ hay demand.

- [Toàn bộ cài đặt GUI](docs/GAMA_SETTINGS_REFERENCE_VI.md)
- [Kiến trúc và cây thư mục](docs/GAMA_RANR_ARCHITECTURE_VI.md)
- [Quyết định khoa học](docs/GAMA_RANR_SCIENTIFIC_CHANGES_VI.md)
- [Bằng chứng và phần chưa nghiệm thu](docs/GAMA_RANR_STATUS_VI.md)

Các lệnh CLI vẫn dùng cùng mô hình:

```bash
.venv/bin/python -m unittest tests.test_gama_unified tests.test_gama_backend tests.test_gama_timeout
.venv/bin/python -m ranr --config configs/gama/smoke.json smoke --output outputs/gama_ranr/my_smoke
.venv/bin/python -m ranr --config configs/gama/calibration.json calibrate
.venv/bin/python -m ranr validate --compile
.venv/bin/python -m ranr development-validation --workers 1
.venv/bin/python -m ranr benchmark --workers 1 2 4 --hours 72
.venv/bin/python -m ranr --config outputs/gama_ranr/benchmark/release/locked_config.json train
```

Các lệnh development/calibration/benchmark/training có thể chạy dài và không tự khởi động khi mở GUI. Lệnh development kiểm chứng 36 rollout dài (ba scenario vật lý, ba seed development, bốn phương pháp). Training còn bị khóa bởi validation nguồn, calibration, accuracy gate và benchmark hiện hành. Chưa có kết quả nghiên cứu chính thức cho môi trường mới.

GIS gốc và kết quả lịch sử được bảo toàn. Bản nguồn trước refactor: `outputs/gama_ranr/unified_fleet_v2_20261015/source_before.tar.gz` và manifest SHA-256. Các module/reference lịch sử không phải simulator thay thế trong pipeline chính thức; [Python reference lịch sử](README_PYTHON_REFERENCE.md).
