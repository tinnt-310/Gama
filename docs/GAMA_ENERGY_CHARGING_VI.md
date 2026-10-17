# Sạc theo SOC và lịch hoạt động

Môi trường hiện hành: `persistent-soc-activity-5`. Đặc tả nghiệm thu: [yêu cầu gốc](GAMA_SOC_ACTIVITY_REQUIREMENTS.md). Checkpoint khôi phục trước refactor: `e8f70f35cf67ea7ec565ff07ea5037ab0ec36153`, nhánh `checkpoints/before-soc-activity-1792059251970807156`; working tree và staging area không bị thay thế.

## Nhu cầu phát sinh từ xe

Đã bỏ bộ tạo opportunity sạc ngẫu nhiên, tần suất sạc/ngày và burst ép request. Lịch cá nhân, ca taxi, giờ cao điểm và xe vào/ra vẫn là đầu vào di chuyển. RANR-AW nhận yêu cầu hợp lệ từ EV; không tạo nhu cầu. Con số 760 opportunity/ngày chỉ thuộc mô hình lịch sử.

Mỗi EV lấy mẫu ngưỡng yêu cầu sạc và mức sạc đích ưu tiên một lần theo seed + stable vehicle ID. Hai thuộc tính `soc_request_threshold`, `soc_preferred_target` giữ nguyên qua các ngày. Phân phối trong environment.json là giả định nghiên cứu có thể cấu hình, chưa phải thống kê thực nghiệm.

| Ngưỡng SOC | EV cá nhân | Taxi điện |
|---|---:|---:|
| 10–20% | 5% | 5% |
| 20–30% | 20% | 10% |
| 30–40% | 35% | 20% |
| 40–50% | 25% | 35% |
| 50–60% | 10% | 20% |
| 60–70% | 5% | 10% |

Trong khoảng đã chọn, ngưỡng được lấy mẫu đều. Mức sạc đích EV cá nhân: 80/85/90/95/100%, xác suất 30/25/25/10/10%. Taxi: 70/80/90/95/100%, xác suất 10/25/35/15/15%. Session target có thể nâng lên khi cần năng lượng cho hoạt động đã biết, tối đa 100%; không nâng SOC bằng phép gán.

## Hoạt động và an toàn chuyến đi

Lịch EV cá nhân gồm đi làm, về nhà, ăn trưa, mua sắm và việc riêng. Taxi có giờ bắt đầu/kết thúc ca, booking hành khách và các kỳ nghỉ. Các lịch được tạo theo seed, ngày và stable ID; không lấy mẫu lại theo cycle để tạo nhu cầu sạc. Scenario high tăng mật độ booking; burst/combined đồng bộ giờ xuất phát trong lịch đi lại, không ép phát request.

Khi SOC vượt xuống ngưỡng, khi chuẩn bị chuyến, khi đến nơi và khi điều kiện thử lại thay đổi, EV xét nhu cầu sạc. Xe đang thực hiện chuyến đã chấp nhận sẽ đi hết chuyến; taxi không bỏ khách để sạc. Trước chuyến, kiểm tra route đường bộ, pin cần cho hành trình, khả năng đến trạm sau hành trình và reserve 5%. Thiếu năng lượng thì giữ chuyến lại, sạc rồi tiếp tục đúng hoạt động chưa hoàn tất. Chuyến đủ pin vẫn được phép đi dù dài. Chuyến vượt khả năng pin đầy được ghi rõ `trip_exceeds_battery_capacity` và bỏ qua theo lịch hoạt động, không được giả vờ chấp nhận.

Taxi có thể xét sạc trước ca/booking và giữa các chuyến. Ước lượng năng lượng tới kỳ nghỉ tiếp theo dùng thời gian vận hành còn lại và giả định 20 km/giờ vận hành. Chỉ route của booking đã biết trước 15 phút được dùng; không đọc các đích hành khách chưa được công bố để dự báo nhu cầu. Hai giá trị trên là giả định cấu hình được.

GAMA native compute_path có thể đặt xe về source node. Luồng mới đặt source trên mạng công cộng đã kết nối; exceptional replan hoặc hủy giữa đường phải hoàn tất đoạn đường hiện tại tới nút trước khi đổi route. Chuyển vị trí và tiêu hao trên đoạn đó vẫn được hạch toán, không dịch chuyển miễn phí tới trạm. Xe thường cũng phải hoàn tất tuyến hiện tại trước khi lịch đi làm/ăn trưa/về nhà được phép tính tuyến thay thế; không snap xe đang chạy về nút gần nhất.

## Need, intent, request và session

- Need: xe muốn/cần sạc do `low_soc`, `trip_energy` hoặc `shift_energy`.
- Intent: quyết định tìm sạc, ID `intent_<vehicle_id>_<sequence>`, tồn tại xuyên qua việc chờ hoạt động và các lần thử lại.
- Request attempt: một lần gửi yêu cầu recommendation, có ID/key riêng và cùng intent ID khi retry.
- Session: xe đã đến trạm, xếp hàng rồi chiếm cổng vật lý. Dùng chung ChargingService cho EV cá nhân và taxi.

`session_state` hiện hữu biểu diễn requested/en_route/waiting/charging/completed và terminal của từng attempt. `needs_charging` chỉ biểu thị attempt đang hoạt động; intent chưa giải quyết vẫn được giữ khi xe chưa gửi được request hoặc đã hoãn. Không tạo request mới mỗi cycle của một need.

Hoãn vì hoạt động/hành khách, tài xế từ chối, chưa có trạm hoặc service bị gián đoạn đều giữ intent gốc. Cooldown có backoff 5, 10, 20, tối đa 30 phút; thay đổi hoạt động/khả dụng và mức khẩn cấp có thể làm xét lại sớm. Thời điểm các attempt tăng thực, không có vòng lặp recommendation trong cùng cycle. Không dùng một lần hoãn để khóa vĩnh viễn xe. Intent chưa giải quyết tiếp tục được xét cho tới cuối episode; từng attempt vẫn có deadline tối đa 6 giờ.

Trong 6 giờ drain không tạo intent mới. Intent cũ có thể retry bằng ID gốc; các phiên còn lại được xử lý theo vật lý. Cuối drain, trường hợp chưa giải quyết ghi deadline_missed/stranded phù hợp; không ép sạc xong hoặc bơm pin.

## Sạc và hạch toán năng lượng

Sau khi chọn trạm, dùng năng lượng đi đường dự kiến để dự báo nhu cầu khi đến trạm; queue prediction nhận năng lượng theo từng candidate. Khi đến thật, tính lại `battery_capacity × max(0, target_soc − arrival_soc) / 100`. Ghi cập nhật trong demand_energy_updates.csv và cập nhật demand/outcome tương ứng.

Chỉ sau khi được cấp cổng tương thích, SOC mới tăng theo công suất cổng, giới hạn EV, hệ số khả dụng trạm và hiệu suất. Mô hình hiện hữu chưa có taper theo SOC; bản sửa giữ mô hình công suất này. Khi đạt target, giải phóng cổng, giữ EV sống và tiếp tục lịch. Không có sạc tại nhà hoặc giá điện.

## Dữ liệu và kiểm chứng

- initial_fleet.json, vehicle_traits.json, activity_plan.json, traffic_plan.json là dữ liệu ngoại sinh. Paired seeds phải giữ các dữ liệu này giống nhau giữa policy.
- charging_intents.json lưu need/intent; request_attempts.json đếm các lần yêu cầu thật; outcomes.json lưu outcome từng attempt; intent_outcomes.json lưu một outcome cuối cho mỗi intent.
- activity_events.csv, intent_events.csv, events.csv và vehicles.csv ghi diễn biến thực. events.csv có trạm/cổng/SOC/target; vehicles.csv có threshold, target, activity, passenger và tọa độ.
- physical_validation.json kiểm chứng SOC theo quãng đường và năng lượng đã nạp, trait bất biến, cấp/trả 125 cổng, tồn tại fleet gốc, entry/exit tại gateway, giới hạn inbound và nguồn gốc nhu cầu.

Yêu cầu thực có thể khác giữa policy vì di chuyển/sạc làm SOC khác nhau. Exogenous hash gồm fleet/traits/lịch đi lại/traffic, không gồm yêu cầu đã phát sinh. Objective `intent-service-5` dùng EV-ngày theo kế hoạch làm mẫu số mạng, giữ metric điều kiện theo intent và gộp thời gian/năng lượng qua attempt; retry không tăng nhu cầu năng lượng. Ưu tiên lexicographic: stranded, nghĩa vụ di chuyển chưa phục vụ, intent không đúng hạn, kWh thiếu, rồi thời gian/hàng chờ. Deadline bất biến 360 phút từ lúc tạo, không tự hủy sạc. Năm tiêu chí, năm adaptive weights, softmax, P2P, exposure, ETA prediction và framework CMA-ES được giữ. Các gate nghiên cứu phải được thực hiện lại; chưa chạy full CMA-ES.

Xem [trạng thái kiểm chứng và bộ dữ liệu](GAMA_RANR_STATUS_VI.md) để biết kết quả thực tế. Output cũ được giữ nguyên, nhưng calibration/model cũ bị từ chối theo environment version và provenance.
