# Nha Trang GAMA RANR-AW

Một mô hình GAMA: **4700 xe thường trực + controlled public-charging opportunities + inbound rush traffic + recommendation phi tập trung**. Bốn phương pháp RANR-AW, No-P2P, No-Prediction và Fixed-Weights dùng chung vật lý GAML. Python điều phối CMA-ES qua GAMA Headless và phân tích kết quả.

Mở `models/main.gaml` → **Run me** → Play để xem mô phỏng. Để thu calibration hoàn toàn từ giao diện, chọn **Collect training data**, chạy đủ seed800001/800002/800003 đến completion, sau đó **Validate and build calibration**. Hướng dẫn chi tiết: [GAMA run guide](docs/GAMA_RANR_RUN_GUIDE_VI.md).

- [Tất cả cài đặt](docs/GAMA_SETTINGS_REFERENCE_VI.md)
- [Kiến trúc và cây thư mục](docs/GAMA_RANR_ARCHITECTURE_VI.md)
- [Thay đổi khoa học, công thức và giới hạn](docs/GAMA_RANR_SCIENTIFIC_CHANGES_VI.md)
- [Trạng thái và bằng chứng đã chạy](docs/GAMA_RANR_STATUS_VI.md)
- [Báo cáo refactor](docs/GAMA_RANR_IMPLEMENTATION_REPORT_VI.md)

```bash
.venv/bin/python -m unittest discover -s tests
.venv/bin/python -m ranr validate --compile
```

Nguồn trước nâng cấp được bảo toàn tại Git checkpoint `5800181`. GIS gốc và outputs lịch sử được giữ nguyên; artifacts lịch sử không phải kết quả môi trường hiện tại. Không còn đường thực thi simulator Python/central assignment trong nguồn nghiên cứu.

Các kiểm tra nhỏ không thay thế calibration dài, accuracy/performance benchmark, design validation, training hoặc720 run test. Những bước dài phải chạy riêng sau kiểm chứng.
