# Pipeline Python lịch sử — không dùng cho nghiên cứu GAMA

Mã đã chuyển vào `ranr.legacy.python_reference`. Các kết quả `outputs/ranr/` được bảo toàn.

# RANR: nghiên cứu khuyến nghị trạm sạc EV

Dự án so sánh **RANR-AW, No-P2P, No-Prediction và Fixed-Weights** bằng một mô phỏng sự kiện Python chung trên GIS Nha Trang: **11 trạm, 125 cổng, 7.195 kW**. Mọi phương pháp được huấn luyện CMA-ES riêng; EV tự chọn, exposure không phải reservation.

Đây là traffic/hành vi tổng hợp trên GIS thật. Không diễn giải kết quả smoke hoặc việc tests đạt thành bằng chứng cải thiện RANR-AW.

## Cài đặt và chạy

Yêu cầu Python 3.10+, Linux/POSIX và compiler C++17 cho kernel tối ưu. Dependency được khóa trong `pyproject.toml`; extra `legacy` giữ các reference CVXPY/Clarabel.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[legacy]'
.venv/bin/python -m ranr.legacy.python_reference.cli prepare
.venv/bin/python -m ranr.legacy.python_reference.cli validate
.venv/bin/python -m ranr.legacy.python_reference.cli benchmark
```

Benchmark kiểm tra sai số Monte Carlo so với 1.024 scenario, riêng cho Proposed/No-P2P/No-Prediction. Đây là độ chính xác tính toán của cùng mô hình, không chứng minh mô hình dự báo đúng thực tế. Chọn scenario count thấp nhất vượt gate cho tất cả estimator; cập nhật `configs/research.json` theo `outputs/ranr/benchmark/selection.json` trước training.

```bash
.venv/bin/python -m ranr.legacy.python_reference.cli train
# Tiếp tục sau gián đoạn, giữ nguyên source/config/calibration:
.venv/bin/python -m ranr.legacy.python_reference.cli train --resume
.venv/bin/python -m ranr.legacy.python_reference.cli evaluate --workers 16
.venv/bin/python -m ranr.legacy.python_reference.cli report outputs/ranr/evaluation/research
```

Để nối tiếp tự động training đang chạy sang evaluation/report, dùng `.venv/bin/python scripts/continue_research_release.py`; trạng thái nằm trong `outputs/ranr/research_pipeline.json`. Supervisor không đổi phương pháp hoặc mã và không đánh dấu complete trước khi đủ 720 runs.

Training chính dùng 3 optimizer seeds, population16, min1024/max4096 evaluations mỗi seed, validation256, cùng quy tắc convergence. Sáu episode GIS ngắn được ghép cặp giữa phương pháp; test chính có 30 seeds/nhóm, 24h khởi động và 48h đo. Chi phí, ngân sách đã dùng và trọng số tại validation checkpoints nằm trong histories. Không chuyển budget tiết kiệm của baseline sang Proposed.

Smoke có namespace seed development riêng, không tiêu thụ test seeds nghiên cứu:

```bash
.venv/bin/python -m ranr.legacy.python_reference.cli --config configs/smoke.json train --settings configs/training_smoke.json --output outputs/ranr/training/smoke
.venv/bin/python -m ranr.legacy.python_reference.cli --config configs/smoke.json evaluate --profile smoke --seeds 2 --models outputs/ranr/training/smoke --output outputs/ranr/evaluation/smoke
```

Một output directory chỉ chứa một registration. Source thay đổi cần directory/version mới; pipeline không ghi đè kết quả khác. Model smoke bị từ chối khi dùng cho evaluation research. Checkpoint pickle chỉ đọc từ run tin cậy do chính pipeline tạo.

## Tài liệu và artifacts

- [Hợp đồng phương pháp](docs/RANR_METHODS_VI.md): observation, exposure, uncertainty, externality và penalties.
- [Kiến trúc và di chuyển](docs/RANR_ARCHITECTURE_VI.md): module responsibilities, directory tree, compatibility và provenance.
- [Hồ sơ thay đổi khoa học](docs/RANR_SCIENTIFIC_CHANGES_VI.md): quyết định khác bản thảo và giới hạn.
- [Bản thảo nguồn](docs/manuscripts/RANR_AW_IEEE_Tieng_Viet.pdf).
- [Hướng dẫn GAMA được bảo toàn](README_GAMA.md).

`outputs/ranr/` tách dữ liệu dẫn xuất, benchmark, training và evaluation. Run có cấu hình, hash nguồn/GIS/calibration, raw log nén, outcomes, metrics và manifest. Báo cáo sinh CSV, CI theo seed, Holm cho ba baseline, PDF/SVG/PNG. Raw packet bodies được lưu riêng với delivery metadata; log nén được ghi trong lúc chạy để giới hạn bộ nhớ.

Để xem raw events:

```bash
.venv/bin/python -c "import gzip; print(gzip.open('PATH/events.jsonl.gz', 'rt').readline())"
```

Đặt `RANR_DISABLE_NATIVE=1` để dùng FIFO NumPy reference. Numerical tests đối chiếu scalar/NumPy/C++; compiler không thay RNG, thông tin hay policy. `RANR_WORKSPACE` hỗ trợ đường dẫn workspace explicit khi cần.

## GAMA và dữ liệu cũ

`models/main.gaml`, GIS gốc và kết quả nghiên cứu cũ được giữ. Script/verification cũ chuyển tiếp tới canonical namespace `ranr.legacy`; các lệnh đã ghi trong tài liệu vẫn hoạt động.

```bash
.venv/bin/python scripts/check_gama.py --compile
.venv/bin/python scripts/check_gama.py --suite --skip-compile
```

Không chạy `--skip-compile` trước khi đã có compile pass trên source tương ứng. Archive/mapping/backup nằm trong `outputs/restructuring_20261013/` và `outputs/archive/`. Link `models/outputs` chỉ là compatibility; dữ liệu mới nằm dưới `outputs/legacy/`.

Các tài liệu SYSTEM_ALGORITHM/B3/B4/minimax mô tả hệ thống GAMA lịch sử. Chúng không phải đặc tả RANR Python mới. Trạng thái nghiệm thu hiện tại được ghi tại [RANR_STATUS_VI.md](docs/RANR_STATUS_VI.md).
