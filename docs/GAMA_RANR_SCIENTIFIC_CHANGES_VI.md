# Hồ sơ thay đổi khoa học RANR-AW

Phiên bản môi trường `persistent-controlled-distributed-3`; observation `station-observation-3`, packet `peer-packet-3`, objective `opportunity-service-3`, model `gama-ranr-v3`, calibration `gama-calibration-v3`. Đây là thay đổi tại chỗ; checkpoint `5800181` bảo toàn công thức và triển khai trước.

| Thành phần | Trước / vấn đề | Quyết định hiện hành / giả định | Bằng chứng cần đọc |
|---|---|---|---|
| Physical model | Hai hệ thuật toán cùng import, nhiều công tắc legacy | Một fleet 3000 car +1000 private EV +700 taxi; opportunities hiện hữu; inbound tối đa 900/300/210 | Fleet, physical, burst fixtures; development dài còn chờ |
| Observation | Local/peer dùng snapshot có cùng độ rộng cố định | Local chính xác của chính trạm; packet sao chép timestamp/version; độ chính xác peer công bố như nhau giữa phương pháp | Protocol, decision và network fixtures |
| Exposure | Cohort theo bucket, thiếu feedback/acknowledgement | Mỗi cohort một token request-leg, count=1; version, context, bucket, ETA, energy, expiry; resolution có nguồn | Retry, cancellation, expiry; chưa khẳng định độ chính xác ngoài thực nghiệm |
| Reconciliation | Survival ETA đơn thuần | Arrival trình token được ghép theo giao thức; arrival không token dùng Bayes với mô hình other arrivals Poisson | Pure posterior tests; xấp xỉ mean-field cần development validation |
| Arrivals dự báo | Background và unseen có khoảng issuance chồng nhau | Exposure đã biết; unseen issuance trong khoảng thiếu tin trước t; background issuance sau t | Scenario fixtures, audit khoảng thời gian |
| Cost T | Travel đơn thuần | Travel + expected charging duration, không cộng waiting | Decision fixture với cổng 60/120 kW |
| Feasibility | Tuyến và 3 kWh hard-code | GIS route, energy +5% battery reserve, connector, operating/capacity đã biết | Decision và physical fixtures |
| No-Prediction | Snapshot estimator giữ 5 criteria | Giữ nguyên 5 logits; H=0 theo FIFO và independent ports; không thêm arrivals/tiến ETA | Scientific fixture; future_calls=0 |
| Behavior | 20% bypass hard-code, calibration không có offers | Mọi activation có offer; EV tự chọn. Calibration thăm dò xác suất đã đăng ký; K_hat từ observable response classes | Protocol, collection unit tests; dữ liệu thực dài còn thiếu |
| P2P | Periodic + phát sau mọi offer | Heartbeat + event triggers cùng transport; batching/min interval, duplicate/reorder/partition/recovery | Network fixture; overhead logs |
| Stability | Chưa có experiment có kiểm soát | Off mặc định; forecast-only smoothing/hysteresis, invalidation khi critical/expired/escalation | Decision fixture; hiệu quả vận hành chưa đo |
| Outcome | Failed/deferred/unserved gộp | Terminal loại trừ nhau; ineligible no-need tách khỏi failure; ledger opportunity đầy đủ | Objective/contract fixtures |
| Objective | T*/W* với D(I+u), không có charging duration | Công thức phân rã dưới đây; bỏ phạt gộp cũ | Objective fixture và analysis checks |
| Training | Chỉ gate benchmark/physical | Thêm design freeze, objective sensitivity và distributed evidence; tối đa72h gồm design-validation allowance | Orchestration tests; chưa training |

## Công thức cost và weights

`f=[T_travel+T_charge, W_mean, W_P95, H, U]`. Mốc phút cố định `[60,60,120,120,60]`; normalized features được giới hạn [0,5], H trong [-5,5] để giữ ngoại tác có dấu. Cost là dot product weights với normalized features, không phải completion time.

`phi=[1, observable_load, recent_request_intensity, exposure_response_uncertainty, information_age]`, từng feature không-bias trong [0,1]. Bốn hàng Theta độc lập, hàng thứ năm zero:20 tham số; Fixed-Weights4 logits, logit cuối zero. Với No-Prediction, w_H vẫn ảnh hưởng tổng mass dành cho các tiêu chí khác và entropy, dù w_H×H=0.

Softmax dùng trừ max-logit, `P(r)∝a(r) exp(-E_Khat[C|offer r]/tau)`. Prior `a(r)=published_power/(1+travel/30)` dương trên candidate khả thi; mặc định tau0.2. Uncertainty phụ thuộc spread từng candidate và tuổi nguồn. No-P2P chỉ dùng local và prior train cho peer.

## Reconciliation và giới hạn thông tin

EV cung cấp token khi đến trạm; đây là thông tin giao thức, không dùng hidden vehicle ID để truy tìm lựa chọn thật. Peer chỉ biết resolution sau modeled delivery. Resolution nhận sau thời điểm snapshot cũ được replay như arrival đã quan sát, không biến thành future ground truth.

Với arrival không token, giả định `B~Bernoulli(p)`, `O~Poisson(lambda)`, `A=B+O`. Khi A=n: `P(B=1|A=n)=p*n/(p*n+(1-p)*lambda)`; A=0 cho0. Chỉ cohort không có token/được khai báo anonymous mới dùng phép cập nhật này; cohort có token được đối soát qua resolution. ETA samples điều kiện hóa theo việc rơi trong/ngoài observation window. Mô hình Poisson cho phần không liên kết là xấp xỉ mean-field; không tuyên bố đối soát định danh hoàn hảo. Đây là mục cần kiểm chứng accuracy gate, không phải bằng chứng từ smoke.

D_background gồm issuance tương lai chưa phát sinh; D_unseen gồm issuance quá khứ sau watermark chưa nhận; D_exposure gồm offer đã nhận còn outstanding. Một exposure sample chỉ chọn một đích hoặc outside. Không đọc opportunity manifest trong predictor.

## Objective chính thức và development coefficients

`L = .5*sum(service_time)/(N_opp*D) + .3*P95(wait)/D + .2*peak_station_queue/125 + beta*sum(N_failure)/N_opp + beta_E*unmet_kWh/requested_kWh`.

Service time = travel + waiting + charging elapsed; hoàn thành bằng completion time vật lý, terminal chưa hoàn thành dùng phần thời gian đã phát sinh. Outage pause trong charging được tính vào elapsed; active charging/energy vẫn theo công suất vật lý. Mean và P95 waiting conditional trên activated/completed được báo riêng. Queue peak chỉ đo trong cửa sổ chính; outcomes tiếp tục settle tới deadline.

N_opp là manifest opportunity trong cửa sổ đo, không phụ thuộc policy. Các terminal failure là no_feasible_station, voluntary_deferred, declined, abandoned, deadline_missed và stranded. Mỗi request chỉ một terminal. Stranded trước activation được ghi tại opportunity mà không tạo request giả. No-need/busy/absent/departing là ineligibility, không tự tính thành thất bại dịch vụ.

Mặc định development beta=beta_E=1. Hai phần failure và energy thể hiện hai ưu tiên khác nhau, không cộng D(I+u) lần nữa. Phân tích0.5/1/2 và review tỷ trọng phải hoàn tất trước freeze; chưa được coi đây là hệ số đã validation. Không có request: conditional waiting/energy ratio0; không có opportunity: fitness_invalid. Dừng sớm là incomplete/censored, không được nhận làm fitness.

## Giả định và phần chưa được xác nhận

Tần suất0.2/0.8 cơ hội/EV/ngày cho760 cơ hội cơ bản, không ép760 activations. SOC<30, target80, pin60kWh, public-only; không đổi SOC để đạt quota. Native driving, GIS/gates và hourly profiles là mô hình phát triển, chưa hiệu chỉnh giao thông Nha Trang thực. Connector generic-public là giả định tương thích chưa khảo sát. Mất thông tin không đồng nghĩa station outage; outage chưa nhận có thể gây failure thực tế.

Không diễn giải các khác biệt activation nội sinh là tự động cải thiện. Báo cả opportunity, eligibility, failure, unmet energy, SOC, stranded và thời gian phục vụ. Phần methodology triển khai nằm tại [bản mô tả](manuscripts/METHODOLOGY_IMPLEMENTED_VI.md); PDF lịch sử được giữ nguyên.

ETA calibration dùng tất cả arrival legs quan sát được, không chỉ phiên sạc hoàn tất. Nhu cầu đã chọn đích nhưng không đến trước terminal được thống kê riêng; xác suất đến trước terminal dùng Beta(1,1) train prior. Phân phối ETA điều kiện trên arrival và arrival probability là hai thành phần riêng. Không gán nhãn latent compliance từ arrival tổng hợp.

Stabilization không tác động No-Prediction: baseline này luôn đánh giá snapshot thô đã nhận. Các phương pháp có prediction có thể dùng cùng forecast filter nếu design validation chọn; mặc định mọi phương pháp đều off.
