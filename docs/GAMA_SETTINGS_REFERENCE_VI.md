# Cài đặt GAMA hiện hành

Môi trường `persistent-controlled-distributed-3`. Run me có **49 điều khiển**. Collect training data kế thừa giao diện và thêm seed/collection flag; cấu hình thu được nạp từ profile đăng ký trước khi khởi tạo.

Nguồn: [main.gaml](../models/main.gaml), [environment.json](../configs/gama/environment.json), [RunConfig](../src/ranr/gama/headless.py). Thiết lập trước khi khởi tạo; thay tham số nghiên cứu giữa episode bị từ chối.

| Điều khiển | Biến | Mặc định | Lựa chọn/giới hạn |
|---|---|---|---|
| Auto GUI preview when no trained model (restart required) | `ranr_gui_preview` | true | <- true |
| Method (restart required) | `ranr_method` | ranr-aw | among:["RANR-AW","No-P2P","No-Prediction","Fixed-Weights"] |
| Scenario (restart required) | `ranr_case` | normal | among:["normal","high","burst","low_compliance","delayed","combined"] |
| GAMA trained parameter file | `ranr_parameter_file` | rỗng | nhập giá trị |
| Train calibration file | `ranr_calibration_file` | rỗng | nhập giá trị |
| Development mode (untrained) | `ranr_development` | false | nhập giá trị |
| Run ID | `ranr_run_id` | gui | nhập giá trị |
| Output directory | `ranr_output` | ../outputs/gama_ranr/gui | nhập giá trị |
| Warmup minutes | `ranr_warmup` | 360 | nhập giá trị |
| Measurement minutes | `ranr_measure` | 360 | nhập giá trị |
| Deadline minutes | `ranr_deadline` | 360 | nhập giá trị |
| EV nominal speed (km/h) | `ranr_ev_speed` | 30 | nhập giá trị |
| Background nominal speed (km/h) | `ranr_car_speed` | 50 | nhập giá trị |
| Monte Carlo samples | `ranr_samples` | 32 | nhập giá trị |
| Private EV opportunities/day | `ranr_private_frequency` | 0.2 | min:0.0 |
| Taxi opportunities/day | `ranr_taxi_frequency` | 0.8 | min:0.0 |
| Public charging SOC threshold (%) | `ranr_soc_threshold` | 30.0 | min:0.0 max:100.0 |
| True compliance (environment only) | `ranr_true_compliance` | 0.8 | nhập giá trị |
| Outside/deferred probability | `ranr_true_defer` | 0.05 | nhập giá trị |
| Mean P2P delay (minutes) | `ranr_delay` | 0.5 | nhập giá trị |
| Packet loss | `ranr_loss` | 0.0 | nhập giá trị |
| Burst requests | `ranr_burst_size` | 100 | nhập giá trị |
| Render displays | `ranr_render` | true | nhập giá trị |
| Record full trace | `ranr_trace` | true | nhập giá trị |
| Calibration collection | `ranr_calibrating` | false | nhập giá trị |
| Recommendation temperature (restart required) | `ranr_temperature` | 0.2 | nhập giá trị |
| P2P heartbeat minutes (restart required) | `ranr_broadcast_period` | 5.0 | nhập giá trị |
| Minimum P2P interval minutes (restart required) | `ranr_min_send` | 0.16666666666666666 | nhập giá trị |
| Duplicate packet probability (restart required) | `ranr_duplicate_probability` | 0 | nhập giá trị |
| Partition begin minutes (-1 disabled) (restart required) | `ranr_partition_begin` | -1 | nhập giá trị |
| Partition end minutes (-1 disabled) (restart required) | `ranr_partition_end` | -1 | nhập giá trị |
| Driver behavior (restart required) | `ranr_behavior_case` | moderate | among:["high","moderate","low","contextual","misspecified"] |
| Forecast stabilization (restart required) | `ranr_stabilization` | off | among:["off","smoothing","smoothing_hysteresis"] |
| Failure coefficient (development) (restart required) | `ranr_failure_beta` | 1.0 | nhập giá trị |
| Unmet energy coefficient (development) (restart required) | `ranr_energy_beta` | 1.0 | nhập giá trị |
| Station event JSON file (restart required) | `ranr_station_events_file` | rỗng | nhập giá trị |
| Decline probability (restart required) | `ranr_true_decline` | 0.0 | min:0.0 max:1.0 |
| Queue abandonment minutes (-1 disabled) | `ranr_abandon_after` | -1.0 | nhập giá trị |
| Target SOC (%) | `target_soc` | 80.0 | min: 1.0 max: 100.0 |
| Start hour (restart required) | `initial_hour` | 0 | min: 0.0 max: 23.0 |
| Seconds per cycle (1 detailed / 60 fast / 3600 coarse) | `step` | 1 | <- 1.0 among: [1.0,5.0,10.0,30.0,60.0,3600.0] |
| Vehicle icon size (px) | `vehicle_icon_size_px` | 40 | min: 16.0 max: 80.0 slider: true |
| Cars (restart required) | `cars` | 3000 | min:0 max:5000 |
| Private EVs (restart required) | `privates` | 1000 | min:0 max:5000 |
| Electric taxis (restart required) | `taxis` | 700 | min:0 max:5000 |
| EV consumption (kWh/km) | `consumption_kwh_km` | 0.18 | min: 0.0 max: 1.0 |
| Charging efficiency | `charge_efficiency` | 0.9 | min: 0.01 max: 1.0 |
| Rush Activity | `have_rush` | true | nhập giá trị |
| Extra vehicles per type during rush (%) | `rush_extra_percent` | 30 | min: 0.0 max: 30.0 |

## Một môi trường và bốn phương pháp

| Nhóm | Giá trị |
|---|---|
| Fleet cơ bản | 3000 car +1000 private EV +700 taxi =4700 |
| Inbound đang hiện diện tối đa | 900/300/210 =1410; tổng6110 |
| Cửa sổ nhập thành phố | 05:30–07:30;17:00–20:00 |
| Cơ hội sạc | 0.2/private/day;0.8/taxi/day;760/day trước eligibility |
| Eligibility | SOC<30%, không stranded/departing/busy |
| Charging | public-only, target80%, pin60kWh |
| Infrastructure | 11 trạm,125 cổng,7195kW danh định |
| Reserve | 5% dung lượng pin cho travel feasibility |
| Forecast horizon / TTL | 120/180 phút |
| Smoothing / hysteresis | off; chỉ bật cho thí nghiệm development |
| Thời gian episode mặc định | 360 warmup +360 measure +360 settlement phút |

| Method | P2P | Queue estimator | Weights |
|---|---|---|---|
| RANR-AW | Có | ETA + paired externality | 20 tham số |
| No-P2P | Không | Local/prior train, ETA | 20 |
| No-Prediction | Có | Snapshot, H=0 | 20 |
| Fixed-Weights | Có | ETA + paired externality | 4 |

Cả bốn có5 criteria và cùng vật lý. Peer offline/stale không tự chứng minh trạm hỏng; prior và uncertainty thay thế thông tin đã hết hạn. Connector generic-public là giả định nghiên cứu chưa khảo sát.

## Scenario và hành vi

Sáu scenario: normal; high nhân opportunity frequency1.8; burst thêm cơ hội tại phút60/120; low_compliance đặt true compliance0.2; delayed đặt delay5phút; combined=burst+low compliance+delay5+loss0.1. Không tạo EV theo tăng demand. Burst20/50/100/200 chọn EV khác nhau, ghi shortage thay vì bù xe.

Driver behavior high/moderate/low/contextual/misspecified là tham số development, không thêm phương pháp chính. Scenario low_compliance/combined ưu tiên compliance0.2. K_true không truyền vào policy; K_hat đến từ train calibration. Decline mặc định0, queue abandonment mặc định-1 (tắt).

Event-triggered updates và heartbeat dùng chung transport; minimum interval10giây, threshold queue-workload5phút hoặc5 exposure tokens, capacity/state change đánh dấu critical. Packet cùng tick không được nhìn thấy tại peer. No-P2P luôn0 thông điệp CS–CS.

Station event JSON là danh sách `{at,sid,operational,factor,failed_ports}`; `at` tính phút elapsed, `sid` theo thứ tự tên trạm, factor trong[0,1], failed_ports là ID cổng cục bộ, danh sách rỗng khôi phục. Sự cố chỉ trở thành thông tin policy sau quan sát/giao packet.

## Thu dữ liệu và research gates

Chọn Collect training data → seed800001/2/3 → Play đến completion → Validate and build calibration. Mỗi run có thư mục và hashes riêng. Bộ seed chưa đủ mẫu sẽ bị từ chối; không ép SOC để tạo eligibility.

GUI mặc định seed42. GUI/Headless dùng cùng GAML; so sánh kết quả phải cùng seed, config và tham số. Preview chỉ bật development/render khi thiếu model, không đổi fleet, clock hoặc samples. Auto preview không phải model đã học.

Training cần calibration mới, correctness, long development, benchmark/accuracy, objective sensitivity và design freeze. CMA-ES population16,3 optimizer seeds; ngân sách chính+validation tối đa72h. Final held-out evaluation720 runs chưa tự chạy. Xem [run guide](GAMA_RANR_RUN_GUIDE_VI.md) và [thay đổi khoa học](GAMA_RANR_SCIENTIFIC_CHANGES_VI.md).
