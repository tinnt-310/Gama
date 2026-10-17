> Objective hiện hành: `intent-service-5`, fitness lexicographic. Xem [báo cáo refactor](docs/GAMA_EVALUATION_REFACTOR_VI.md) để biết kiểm chứng và điều kiện thu lại dữ liệu.

# GAMA research entry point

Mở `models/main.gaml`, chọn **Run me** hoặc **Collect training data**. GUI và Headless dùng chung mô hình **persistent-soc-activity-6**: ngưỡng pin/mục tiêu sạc riêng cho từng EV, lịch cá nhân và ca taxi; không còn lịch sạc ngẫu nhiên hoặc quota request/ngày.

**Run me** mặc định **1 phút/cycle, 72 giờ mô phỏng**; **Collect training data** dùng **72 giờ/seed, 1 phút/cycle**, vừa hiển thị xe vừa thu dữ liệu. Fleet thường trực 4700 xe, tối đa 1410 inbound đồng thời, 11 trạm và 125 cổng. Xem [Run Guide](docs/GAMA_RANR_RUN_GUIDE_VI.md), [Settings](docs/GAMA_SETTINGS_REFERENCE_VI.md), [thiết kế sạc](docs/GAMA_ENERGY_CHARGING_VI.md) và [trạng thái nghiệm thu/bộ dữ liệu](docs/GAMA_RANR_STATUS_VI.md).

Thu dữ liệu **72 giờ/seed**, chạy nền và tự giám sát: xem [README_LENH.md](README_LENH.md), dùng profile `configs/gama/calibration.json`. Lệnh `status` trong hướng dẫn cho biết đang kiểm tra, đang thu hay dữ liệu đã được kiểm chứng đầy đủ.

Checkpoint trước thay đổi SOC/activity: `e8f70f35`. Nguồn legacy trước tái cấu trúc ban đầu nằm trong Git `5800181`. Output và calibration lịch sử được giữ nguyên, nhưng không dùng làm dữ liệu cho môi trường mới.
