# Chỉ mục phương pháp hiện hành — 24/10/2026

Source đang kiểm thử trên branch `audit/end-to-end-20261024`. Môi trường
`persistent-soc-activity-6`, objective `intent-service-5`, observation
`station-observation-5`. Không thay objective, fleet, grid, seed hay ngân sách.

| Phạm vi | Nguồn chính |
|---|---|
| Công thức và giới hạn thông tin | [Hồ sơ khoa học](GAMA_RANR_SCIENTIFIC_CHANGES_VI.md) |
| Objective, cohort, tolerance | `configs/gama/objective.json`; `models/ranr/Evaluation.gaml` |
| EV, SOC và hoạt động | `models/ranr/Fleet.gaml`; `models/Mobility.gaml` |
| Physical FIFO/power/taper | `models/ChargingService.gaml`; `models/ranr/Math.gaml` |
| Observation/policy | `models/ranr/Policy.gaml`; `models/ranr/Prediction.gaml` |
| CLI, provenance và raw contracts | `src/ranr/gama/cli.py`, `headless.py`, `contracts.py` |
| Release và budget | `release.py`, `training.py`, `training_time.py` |
| Methodology manuscript hiện hành | [Methodology](manuscripts/METHODOLOGY_IMPLEMENTED_VI.md) |
| Kiểm toán và bằng chứng mới | [Kết quả end-to-end](../../00_EXECUTIVE_SUMMARY_VI.md) |

Observation v5 bổ sung busy battery energy, EV cap, SOC, snapshot port index và
physical port identity. Các method nhận cùng schema, theo cùng delivery/TTL.
Queued jobs giữ SOC. Python giữ toàn bộ vector `energy_by_station` trong prior.
Calibration v4 về tên container được giữ để tránh đổi không cần thiết; trường
`observation_version` và source hash bắt buộc phân biệt các dữ liệu bên trong.
Không được đổi manifest cũ thành v5. Collect cũ còn giá trị lịch sử, cần thu mới
để kiểm chứng thay đổi GAML; chưa có chứng chỉ compatibility cho bản vá này.

Fresh release mặc định không nhập Collect cũ. Chỉ dùng `--historical-run` ba lần
cho import có chủ đích; hash/seed/source compatibility vẫn bắt buộc. Không chạy
release cũ bằng source mới hoặc sửa source của worker đang chạy.

Training chính thức còn yêu cầu `outputs/gama_ranr/pre_training_acceptance.json`
với các gate tham chiếu bằng hash; chỉ có boolean `passed` không đủ. Smoke có
profile development riêng. SIGTERM giữ pending population/RNG và dừng GAMA;
SIGKILL dùng time journal với dự phòng bảo thủ đến lúc recovery, có thể tính
thừa downtime, không được quảng cáo là đo chính xác active time bị mất.

Các tài liệu có banner lịch sử, `docs/history/`, flowcharts cũ và PDF manuscript
là bằng chứng các phiên bản trước. PDF không phải mô tả canonical v5 hoặc kết
quả training/evaluation mới. Không có kết luận vượt baseline hay Nash equilibrium.
