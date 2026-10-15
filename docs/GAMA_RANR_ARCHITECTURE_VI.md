# Kiến trúc môi trường thống nhất v2

GAMA thực thi một mô hình: đội xe thường trực, controlled charging opportunities và xe nhập thành phố giờ cao điểm. GUI và Headless cùng gọi `models/main.gaml`; khác cách khởi chạy và hiển thị. Run ID chỉ định danh đầu ra.

```text
configs/gama/
    environment.json       # Nguồn chuẩn: fleet, tần suất, bảng giờ, SOC, inbound
    research.json           # Profile nghiên cứu
    calibration.json        # Profile calibration dùng cho GUI và Headless
    smoke.json              # Fixture nhỏ có nhãn development
models/
    main.gaml               # GIS initialization, GUI chung
    Mobility.gaml           # Native driving, trạng thái xe, quãng đường
    ChargingService.gaml    # Cổng, FIFO, năng lượng, vòng đời phiên sạc
    ranr/
        Fleet.gaml          # ID xe, cửa ngõ, traffic plan, cơ hội sạc, collection GUI
        Runtime.gaml        # Observation → recommendation → EV choice → metrics
        Math.gaml           # Tham số và hợp đồng model
        Prediction.gaml     # Snapshot và dự báo ETA, ngoại tác ghép cặp
        Policy.gaml         # Bốn phương pháp, cùng 5 tiêu chí
    tests/                  # Fixture vật lý, thông tin, prediction, fleet và compatibility
src/ranr/gama/
    headless.py             # RunConfig, launcher, provenance, completion checking
    gui_collection.py       # Registration, kiểm chứng và tổng hợp calibration GUI
    pipeline.py             # Calibration, paired jobs, CI/Holm/reporting
    development.py          # Kiểm chứng development dài và báo cáo tính khả thi
    benchmarking.py         # Accuracy gate và benchmark GAMA
    training.py             # CMA-ES/checkpoint/long validation qua Headless
    analysis.py             # Phân tích kết quả GAMA
    cli.py                  # CLI chính thức
scripts/
    gama.py                 # Compatibility launcher
    gui_calibration.py      # Bridge được gọi từ nút trong GAMA
    java/CheckModel.java    # Compile nhiều GAML root trong một JVM
outputs/gama_ranr/
    gui/                    # GUI exploration
    gui_calibration/        # Runs, immutable builds và latest pointer
    development/            # Long development validation
    benchmark/, training/, evaluation/
    unified_fleet_v2_20261015/  # Backup, smoke và hồ sơ refactor
includes/                   # GIS gốc giữ nguyên
src/ranr/legacy/             # Python reference/launcher lịch sử được tách namespace
```

Snapshot, packet và exposure nằm trong ChargingService, Math/Policy và Runtime; thuật toán được import theo chuỗi GAML, không nhân bản cho GUI. Không có simulator Python trong pipeline chính thức.

Vòng đời xe và vòng đời demand độc lập: terminal outcome giải phóng nhu cầu, không giải phóng agent. Xe vãng lai chỉ được tạo bởi traffic plan và chỉ chết tại exit; xe thường trực stranded được giữ lại. Profile test có thể tạo trạng thái nhân tạo để kiểm chứng invariant nhưng không được dùng làm dữ liệu calibration nghiên cứu.

Compatibility: bỏ các experiment GUI lịch sử khỏi main nghiên cứu; bản nguồn và tài liệu đầy đủ nằm trong source_before.tar.gz cùng manifest hash. Các regression tham chiếu số EV tổng cũ được chuyển sang số private/taxi và total suy ra. Fixture rush/configuration cũ chuyển sang regression fleet mới. Mã reference độc lập được giữ để kiểm chứng thuật toán, không dùng để mô phỏng thay GAMA.
