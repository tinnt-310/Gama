# Mô tả methodology đã triển khai

Đây là phần bổ sung triển khai, không phải kết quả hiệu quả thực nghiệm và không thay thế PDF lịch sử.

Hệ thống `persistent-soc-activity-6` dùng GAMA native driving với GIS Nha Trang và11 trạm125 cổng7195kW danh định. Fleet3000 conventional/1000 privateEV/700 taxi tồn tại độc lập nhu cầu sạc. Mỗi EV có ngưỡng pin/mục tiêu riêng, lịch cá nhân hoặc ca taxi. Nhu cầu phát sinh từ SOC, route năng lượng của chuyến đã biết và hoạt động; không có scheduler cơ hội sạc/ngày. Inbound tối đa30% từng loại vào dần qua gates có tuyến kiểm chứng.

Một trạm ra quyết định từ trạng thái cục bộ, packet đã nhận, exposure đã biết và prior calibration. Peer state có timestamp/version/TTL. Heartbeat và event-triggered updates dùng chung transport có delay/loss/duplicate/partition. Token do EV trình tại arrival cho phép đối soát; phần không định danh dùng conditional probabilistic approximation đã công bố.

Policy sử dụng5 tiêu chí travel+charge, mean waiting, P95 waiting, marginal externality và uncertainty. Weights softmax có20 tham số độc lập; Fixed-Weights4. No-Prediction dùng snapshot và H=0, không forecast tương lai; No-P2P không giao tiếp giữa trạm. Recommendation không tạo reservation hoặc assignment; EV tự quyết định.

CMA-ES dùng vector lexicographic: stranded/EV-day, unserved planned activity/EV-day, intent trễ/EV-day, unmet kWh/EV-day, rồi operational objective. Operational gồm 0.5 mean completion/360 + 0.3 P95 waiting/360 + 0.2 physical queue pressure. Cohort, EV-day và tolerance theo `configs/gama/objective.json`; thống kê điều kiện rỗng giữ null và cỡ mẫu. Intent giữ ID/deadline qua retry; năng lượng và thời gian được kiểm chứng độc lập từ ledger.

Accuracy kiểm tra cả mean waiting, P95 và externality trước development/design; model chính giữ temperature 0.2, heartbeat 5 phút, stabilization off. Training có 72 giờ riêng, population 16, optimizer seed 41001–41003; tập candidate, validation và test tách seed. Chỉ 4 model đã hoàn tất và vượt gate mới được dùng cho 720 lượt held-out evaluation. CI/so sánh ghép cặp theo seed, Holm trên ba baseline mỗi metric/scenario; các candidate/xe không phải mẫu độc lập. Công thức và assumptions tại [hồ sơ khoa học](../GAMA_RANR_SCIENTIFIC_CHANGES_VI.md).

Chưa có tuyên bố giảm chờ, giảm congestion, hội tụ hay hiệu quả so với baseline cho môi trường này. Cần calibration, accuracy gate, benchmark, design freeze, training và held-out evaluation trước các kết luận đó.


Các phân phối ngưỡng/mục tiêu và lịch hoạt động là giả định có cấu hình, chưa được xác nhận bằng khảo sát Nha Trang. Chi tiết và bằng chứng nghiệm thu nằm ở [thiết kế sạc theo SOC](../GAMA_ENERGY_CHARGING_VI.md) và [trạng thái hiện hành](../GAMA_RANR_STATUS_VI.md).
