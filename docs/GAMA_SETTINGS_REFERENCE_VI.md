# Toàn bộ cài đặt GAMA hiện hành

Môi trường **persistent-controlled-v2**, ngày 15/10/2026: **một mô hình vật lý, một cơ chế controlled opportunities, bốn phương pháp**. GAMA GUI và Headless chạy cùng GAML. Bản cài đặt cũ đã lưu trong source_before.tar.gz; bảng này thay thế hướng dẫn trước refactor.

Nguồn chuẩn: [environment.json](../configs/gama/environment.json), [main.gaml](../models/main.gaml), [RunConfig](../src/ranr/gama/headless.py). Có **36 điều khiển Run me**, thêm hai điều khiển trong Collect training data. Không có lựa chọn workload hay sạc tại nhà trong GUI nghiên cứu.

## Các điều khiển Run me

Đặt cấu hình trước khi khởi tạo. Thay fleet, tần suất, SOC, step, tốc độ hoặc vật lý giữa episode bị từ chối; cần đóng và khởi tạo lại.

| Tên GUI / biến | Mặc định | Ý nghĩa |
|---|---|---|
| Auto GUI preview when no trained model (restart required)<br>`ranr_gui_preview` | true | Cho phép development weights và nhãn UNTRAINED khi thiếu model; không đổi vật lý, demand, samples hoặc giờ. |
| Method (restart required)<br>`ranr_method` | RANR-AW | RANR-AW / No-P2P / No-Prediction / Fixed-Weights. |
| Scenario (restart required)<br>`ranr_case` | normal | normal / high / burst / low_compliance / delayed / combined. |
| GAMA trained parameter file<br>`ranr_parameter_file` | Rỗng | Model GAMA v2; sai môi trường hoặc cấu hình bị từ chối. Tự tìm published model nếu có. |
| Train calibration file<br>`ranr_calibration_file` | Rỗng | Calibration train v2. GUI sau training lấy đường dẫn đã khóa trong model. |
| Development mode (untrained)<br>`ranr_development` | false → true nếu auto preview thiếu model | Trọng số/prior development; không gọi là kết quả đã huấn luyện. |
| Run ID<br>`ranr_run_id` | gui | Định danh; mặc định sinh tên riêng. Không chọn mô hình vật lý qua tên. |
| Output directory<br>`ranr_output` | ../outputs/gama_ranr/gui | Không dùng chung thư mục cho các lượt chạy. Với Run ID gui, tự tạo thư mục con. |
| Warmup minutes<br>`ranr_warmup` | 360 phút | Thời gian khởi động trước cửa sổ đo. |
| Measurement minutes<br>`ranr_measure` | 360 phút | Cửa sổ cơ hội/yêu cầu đo chính. |
| Deadline minutes<br>`ranr_deadline` | 360 phút | Deadline từng nhu cầu đã kích hoạt; tiếp tục settlement sau cửa sổ đo. |
| EV nominal speed (km/h)<br>`ranr_ev_speed` | 30 km/h | Tốc độ danh định EV; native driving còn chịu giao thông. |
| Background nominal speed (km/h)<br>`ranr_car_speed` | 50 km/h | Tốc độ danh định ô tô thường. |
| Monte Carlo samples<br>`ranr_samples` | 32 | Số scenario predictor, không tự giảm khi preview. Research cần accuracy gate. |
| Private EV opportunities/day<br>`ranr_private_frequency` | 0,2 cơ hội/xe/ngày | Cơ hội theo loại xe và bảng giờ; không đảm bảo mọi cơ hội kích hoạt. |
| Taxi opportunities/day<br>`ranr_taxi_frequency` | 0,8 cơ hội/xe/ngày | Như trên, áp dụng taxi. |
| Public charging SOC threshold (%)<br>`ranr_soc_threshold` | 30% | Chỉ SOC thấp hơn ngưỡng mới đủ điều kiện; SOC đúng 30% bị bỏ qua. |
| True compliance (environment only)<br>`ranr_true_compliance` | 0,8 | K_true của môi trường; policy không đọc giá trị này. |
| Outside/deferred probability<br>`ranr_true_defer` | 0,05 | Xác suất outside/defer; terminal demand được phạt, xe vẫn tồn tại. |
| Mean P2P delay (minutes)<br>`ranr_delay` | 0,5 phút | Mean delay packet; delayed/combined đặt 5 phút. |
| Packet loss<br>`ranr_loss` | 0 | Xác suất mất packet; combined đặt 0,1. |
| Burst requests<br>`ranr_burst_size` | 100 | Có thể nhập 20/50/100/200 hoặc số nguyên không âm. Không đủ xe/eligibility thì báo thiếu hụt. |
| Render displays<br>`ranr_render` | true | Computer, biểu đồ và monitor. Headless thường tắt. |
| Record full trace<br>`ranr_trace` | true | Trace đầy đủ, ghi theo buffer. |
| Calibration collection<br>`ranr_calibrating` | false | Thu calibration và dùng hành vi chọn trạm nền. Thu chính thức qua Collect training data để có registration. |
| Target SOC (%)<br>`target_soc` | 80% | Mức pin đích; năng lượng yêu cầu chốt tại activation, không sửa giữa phiên. |
| Start hour (restart required)<br>`initial_hour` | 0 (00:00) | Giờ đồng hồ lúc bắt đầu; khác thời gian đã trôi qua. |
| Seconds per cycle (1 detailed / 60 fast / 3600 coarse)<br>`step` | 1 giây | 1/5/10/30/60/3600 trên GUI; nghiên cứu giữ 1 giây đến khi có kiểm chứng sai số. |
| Vehicle icon size (px)<br>`vehicle_icon_size_px` | 40 px | 16–80 px; chỉ đổi hiển thị. |
| Cars (restart required)<br>`cars` | 3000 | Ô tô thường cơ bản, cần restart; không tạo/xóa qua callback khi chạy. |
| Private EVs (restart required)<br>`privates` | 1000 | EV cá nhân cơ bản, cần restart. |
| Electric taxis (restart required)<br>`taxis` | 700 | Taxi điện cơ bản, cần restart. elecars = privates+taxis là giá trị suy ra. |
| EV consumption (kWh/km)<br>`consumption_kwh_km` | 0,18 kWh/km | Tiêu hao theo quãng đường native driving thực. |
| Charging efficiency<br>`charge_efficiency` | 0,9 | Hiệu suất từ điện lưới vào pin. |
| Rush Activity<br>`have_rush` | true | Bật lịch xe nhập từ ngoài; độc lập với cơ hội sạc. |
| Extra vehicles per type during rush (%)<br>`rush_extra_percent` | 30% | 0–30%; hạn mức xe bổ sung đang hiện diện, tính riêng từng loại. |

## Thu calibration trực tiếp trong GAMA

Chọn **Collect training data**. `ranr_collection_seed`: 800001 / 800002 / 800003; `ranr_collect_gui`: true. Experiment nạp profile [calibration.json](../configs/gama/calibration.json) trước khởi tạo để giữ cấu hình đồng nhất. Chạy từng seed hết episode, rồi bấm **Validate and build calibration** trong Commands. Monitor Calibration status và bridge_status.json báo kết quả. Xem [hướng dẫn từng bước](GAMA_RANR_RUN_GUIDE_VI.md).

Run me có thể ghi raw calibration nếu bật checkbox, nhưng lượt khám phá này không tự thay thế ba seed collection đã đăng ký. Build chỉ nhận các lượt hoàn chỉnh, đúng nguồn/cấu hình và đủ mẫu; không tự bắt đầu CMA-ES.

## Fleet và giao thông

| Nhóm | Xe cơ bản | Extra tối đa 30% | Tổng khi đủ hạn mức |
|---|---:|---:|---:|
| Ô tô thường | 3000 | 900 | 3900 |
| EV cá nhân | 1000 | 300 | 1300 |
| Taxi điện | 700 | 210 | 910 |
| Tổng | 4700 | 1410 | 6110 |

Xe đỗ, di chuyển, chờ, sạc và stranded đều còn trong thành phố. Nhu cầu sạc không tạo xe; hoàn thành không xóa xe cơ bản. Xe hết pin không tự hồi pin. Cao điểm 05:30–07:30 và 17:00–20:00; xe nhập dần tại cửa ngõ đã kiểm chứng tuyến, đỗ tại các điểm đích trung tâm, rồi đi ra cửa ngõ khi đủ điều kiện. Xe lưu lại chiếm hạn mức của đợt sau.

Cửa ngõ/vùng trung tâm là dữ liệu dẫn xuất từ mạng đường và cụm trạm; không phải ranh giới hành chính được hiệu chỉnh thực địa. gateway_validation.json ghi giả định, vị trí và tuyến. GIS gốc được bảo toàn.

## Controlled opportunities và sáu scenario

Bảng 24 giờ riêng cho private/taxi nằm trong environment.json, được chuẩn hóa tổng ngày khi lấy mẫu. Tần suất và bảng giờ là giả định development. Tổng cơ bản kỳ vọng 760 **cơ hội**/ngày = 760/1440 phút, khoảng 0,528/phút; 760 **yêu cầu**/ngày là mục tiêu calibration cần đo thực tế. Không có ô rate độc lập để tạo cấu hình mâu thuẫn.

Mỗi cơ hội gắn ID xe và xét một lần: SOC <30%, xe hiện diện, không stranded/đang ra khỏi thành phố và không có phiên đang xử lý. Năng lượng mục tiêu = dung lượng pin × (80% − SOC hiện tại). Không gán SOC mới hoặc đổi sang xe khác để đạt số lượng.

| Scenario | Tác động |
|---|---|
| normal | Tần suất/bảng giờ cơ bản |
| high | Tần suất cơ hội ×1,8; không tạo thêm EV ngoài traffic plan |
| burst | Thêm cơ hội đồng thời tại phút 60/120 sau đầu cửa sổ đo, lặp theo ngày; các ID khác nhau trong mỗi burst |
| low_compliance | K_true=0,2 |
| delayed | Mean delay=5 phút |
| combined | Burst + K_true=0,2 + delay=5 phút + loss=0,1; không tự nhân rate ×1,8 |

Burst ghi số cơ hội yêu cầu, activation và thiếu hụt khi không đủ xe/eligibility. Manifest cơ hội/lịch giao thông/SOC ban đầu giống nhau giữa phương pháp cùng seed. Activation và quỹ đạo được phép khác do trạng thái nội sinh; báo cáo cả số cơ hội lẫn nhu cầu thực.

## Bốn phương pháp

| Phương pháp | P2P | Waiting | Trọng số |
|---|---|---|---|
| RANR-AW | Có | Tại ETA, ngoại tác ghép cặp | Adaptive, 20 tham số |
| No-P2P | Không | Tại ETA, prior train cho trạm xa | Adaptive, 20 |
| No-Prediction | Có | Snapshot, H=0 theo FIFO | Adaptive, 20 |
| Fixed-Weights | Có | Như Proposed | Fixed, 4 |

Cùng năm tiêu chí [T, W_mean, W_P95, H, U], cùng physics và policy interfaces. No-Prediction không gọi future predictor. No-P2P không phát/nhận thông điệp giữa trạm.

## Profile, thời gian và dữ liệu

| Profile | Warmup / đo / deadline (phút) | Fleet cơ bản | Samples | Start hour |
|---|---|---|---:|---:|
| Run me / research | 360 / 360 / 360 | 3000 / 1000 / 700 | 32 trước accuracy gate | 0 |
| Calibration | 360 / 360 / 360 | 3000 / 1000 / 700 | 4 | 0 |
| Smoke CLI | 0 / 3 / 30 | 2 / 3 / 2 | 4 | 6 |

Timeout research 21.600 giây thực/run, calibration 28.800, smoke 180. 18 giờ mô phỏng không đồng nghĩa 18 giờ thực. Muốn đo 12 giờ, đặt Measurement minutes=720; giữ warmup/deadline 360/360 thì tổng tối đa 24 giờ mô phỏng.

Outputs tách theo run, có input/provenance, initial_fleet.json, opportunities.json, traffic_plan.json, opportunity_results.csv, traffic.csv, vehicles.csv, snapshots, outcomes/metrics/completion. Các file tổng kết chỉ hợp lệ khi chạy hết. Seed GUI thông thường 42; seed calibration được chọn riêng. Trong CLI, tham số tương ứng là background_cars/private_evs/electric_taxis/private_frequency/taxi_frequency; demand_rate là property suy ra, không nhận từ JSON.

GAMA model schema gama-ranr-v2 và environment_version phải khớp. Calibration source/hash, model source và cấu hình khóa được kiểm tra; artifact cũ cần recalibration/retraining. Giữ nguyên GIS 11 trạm, 125 cổng, 7.195 kW; pin 60 kWh, chỉ sạc công cộng. Training chính vẫn chờ development dài, correctness/accuracy gate và benchmark; chưa chạy trong đợt refactor.
