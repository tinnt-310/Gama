# Hồ sơ thay đổi khoa học RANR-AW

Phiên bản môi trường `persistent-soc-activity-6`; observation `station-observation-4`, packet `peer-packet-3`, objective `intent-service-5`, model `gama-ranr-v4`, calibration `gama-calibration-v4`. Đây là thay đổi tại chỗ; checkpoint `5800181` bảo toàn công thức và triển khai trước.

| Thành phần | Trước / vấn đề | Quyết định hiện hành / giả định | Bằng chứng cần đọc |
|---|---|---|---|
| Physical model | Hai hệ thuật toán cùng import, nhiều công tắc legacy | Một fleet 3000 car +1000 private EV +700 taxi; intent phát sinh từ SOC/lịch hoạt động; inbound tối đa 900/300/210 | Fleet, physical, SOC/activity fixtures; development dài còn chờ |
| Observation | Local/peer dùng snapshot có cùng độ rộng cố định | Local chính xác của chính trạm; packet sao chép timestamp/version; độ chính xác peer công bố như nhau giữa phương pháp | Protocol, decision và network fixtures |
| Exposure | Cohort theo bucket, thiếu feedback/acknowledgement | Mỗi cohort một token request-leg, count=1; version, context, bucket, ETA, energy, expiry; resolution có nguồn | Retry, cancellation, expiry; chưa khẳng định độ chính xác ngoài thực nghiệm |
| Reconciliation | Survival ETA đơn thuần | Arrival trình token được ghép theo giao thức; arrival không token dùng Bayes với mô hình other arrivals Poisson | Pure posterior tests; xấp xỉ mean-field cần development validation |
| Arrivals dự báo | Background và unseen có khoảng issuance chồng nhau | Exposure đã biết; unseen issuance trong khoảng thiếu tin trước t; background issuance sau t | Scenario fixtures, audit khoảng thời gian |
| Cost T | Travel đơn thuần | Travel + expected charging duration, không cộng waiting | Decision fixture với cổng 60/120 kW |
| Feasibility | Tuyến và 3 kWh hard-code | GIS route, energy +5% battery reserve, connector, operating/capacity đã biết | Decision và physical fixtures |
| No-Prediction | Snapshot estimator giữ 5 criteria | Giữ nguyên 5 logits; H=0 theo định nghĩa ablation; vật lý vẫn xét giới hạn công suất trạm; không thêm arrivals/tiến ETA | Scientific fixture; future_calls=0 |
| Behavior | 20% bypass hard-code, calibration không có offers | Mọi request hợp lệ có offer; EV tự chọn. Calibration thăm dò xác suất đã đăng ký; K_hat từ observable response classes | Protocol, collection unit tests; dữ liệu thực dài còn thiếu |
| P2P | Periodic + phát sau mọi offer | Heartbeat + event triggers cùng transport; batching/min interval, duplicate/reorder/partition/recovery | Network fixture; overhead logs |
| Stability | Chưa có experiment có kiểm soát | Off mặc định; forecast-only smoothing/hysteresis, invalidation khi critical/expired/escalation | Decision fixture; hiệu quả vận hành chưa đo |
| Outcome | Failed/deferred/unserved gộp | Terminal loại trừ nhau; ineligible no-need tách khỏi failure; ledger opportunity đầy đủ | Objective/contract fixtures |
| Objective | T*/W* với D(I+u), không có charging duration | Công thức phân rã dưới đây; bỏ phạt gộp cũ | Objective fixture và analysis checks |
| Training | Chỉ gate benchmark/physical | Thêm design freeze, objective sensitivity và distributed evidence; tối đa 72 giờ riêng training; các giai đoạn khác tính riêng | Orchestration tests; chưa training |

## Công thức cost và weights

`f=[T_travel+T_charge, W_mean, W_P95, H, U]`. Mốc phút cố định `[60,60,120,120,60]`; normalized features được giới hạn [0,5], H trong [-5,5] để giữ ngoại tác có dấu. Cost là dot product weights với normalized features, không phải completion time.

`phi=[1, observable_load, recent_request_intensity, exposure_response_uncertainty, information_age]`, từng feature không-bias trong [0,1]. Bốn hàng Theta độc lập, hàng thứ năm zero:20 tham số; Fixed-Weights4 logits, logit cuối zero. Với No-Prediction, w_H vẫn ảnh hưởng tổng mass dành cho các tiêu chí khác và entropy, dù w_H×H=0.

Softmax dùng trừ max-logit, `P(r)∝a(r) exp(-E_Khat[C|offer r]/tau)`. Prior `a(r)=published_power/(1+travel/30)` dương trên candidate khả thi; mặc định tau0.2. Uncertainty phụ thuộc spread từng candidate và tuổi nguồn. No-P2P chỉ dùng local và prior train cho peer.

## Reconciliation và giới hạn thông tin

EV cung cấp token khi đến trạm; đây là thông tin giao thức, không dùng hidden vehicle ID để truy tìm lựa chọn thật. Peer chỉ biết resolution sau modeled delivery. Resolution nhận sau thời điểm snapshot cũ được replay như arrival đã quan sát, không biến thành future ground truth.

Với arrival không token, giả định `B~Bernoulli(p)`, `O~Poisson(lambda)`, `A=B+O`. Khi A=n: `P(B=1|A=n)=p*n/(p*n+(1-p)*lambda)`; A=0 cho0. Chỉ cohort không có token/được khai báo anonymous mới dùng phép cập nhật này; cohort có token được đối soát qua resolution. ETA samples điều kiện hóa theo việc rơi trong/ngoài observation window. Mô hình Poisson cho phần không liên kết là xấp xỉ mean-field; không tuyên bố đối soát định danh hoàn hảo. Đây là mục cần kiểm chứng accuracy gate, không phải bằng chứng từ smoke.

D_background gồm issuance tương lai chưa phát sinh; D_unseen gồm issuance quá khứ sau watermark chưa nhận; D_exposure gồm offer đã nhận còn outstanding. Một exposure sample chỉ chọn một đích hoặc outside. Không đọc opportunity manifest trong predictor.

## Objective chính thức: intent-service-5

GAMA trả fitness vector theo thứ tự ưu tiên lexicographic:

`[unique_stranded / E, mobility_unserved / E, not_on_time / E, unmet_kWh / E, operational]`.

`E` là planned electric-vehicle days trong Measurement, bao gồm kế hoạch inbound bị chặn; không dùng số intent nội sinh làm mẫu số. Mỗi intent có một ID qua retry và deadline cố định 360 phút từ lúc tạo. Cohort gồm intent được tạo trong `[warmup, warmup + measurement)`, quan sát đến hết Drain. GAMA tính vector; Python kiểm tra ledger và xếp hạng vector trước CMA-ES tell.

`operational = 0.5 * mean_completion / 360 + 0.3 * P95_wait / 360 + 0.2 * queue_pressure`.

Mean completion chỉ trên intent completed. Waiting cộng các khoảng chờ vật lý duy nhất của intent đã đến hàng đợi; giữ phần quan sát được của mẫu censored. Cohort điều kiện rỗng được báo `null`, cỡ mẫu 0; component tương ứng bằng 0. Các thành phần failure đứng trước operational ngăn việc đổi thất bại lấy điểm thời gian thấp. Observation kết thúc sớm làm fitness không hợp lệ.

Queue pressure lấy cực đại trong Measurement + Drain của `E_wait / (E_wait + 6 * P_eff)`, trong đó P_eff từ lịch FIFO giải phóng toàn bộ backlog vật lý, gồm phiên bận và tải ngoài cohort. Khi có backlog mà năng lực bằng 0, pressure bằng 1. Đây không phải queue length chia 125 cổng. Đặc tả và tolerance nằm trong `configs/gama/objective.json`.

## Accuracy và giao thức lựa chọn

Mean waiting ≤ 1 phút; P95 waiting ≤ 5 phút; externality ≤ 5 vehicle-minutes so với Monte Carlo reference. Ít nhất 95% probe đạt đồng thời ba ngưỡng, riêng từng phương pháp. Reference dùng một nửa ngưỡng. Ngưỡng H là lựa chọn kỹ thuật đăng ký trước (5/120 trên thang H), chưa phải chuẩn thực nghiệm. Phải kiểm tra đủ/duy nhất/hữu hạn 165 probe.

Kiểm tra timestep dùng reference 1 giây, các bước 5/10/30/60 giây; ưu tiên 1–4 của fitness có sai số tuyệt đối tối đa `[0, 0.01, 0.01, 0.1]` theo đơn vị đã chuẩn hóa, chênh lệch conditional intent-success ≤ 0.01, operational tương đối ≤ 1%. Thiếu mẫu quan sát không được tự nhận đạt.

Accuracy chạy trước development/design. Design mặc định đăng ký temperature 0.2, heartbeat 5 phút, stabilization off. Có 15 tên biến thể, 12 cấu hình duy nhất; phân tích độ nhạy không tự thay cấu hình chính. Freeze phải liên kết đủ ma trận run, native validation, development và calibration bằng hash.

CMA-ES có population 16, ba optimizer seed 41001–41003. Candidate dùng 11001–11006, validation 21001–21006. Ngân sách tối đa 72 giờ active training cộng dồn qua resume, dự trù 15%. Model được chọn bằng validation vector; evaluation 31001–31030 gồm 720 rollout và không tham gia lựa chọn model.

## Giả định và phần chưa được xác nhận

Không còn tần suất opportunity sạc/ngày trong môi trường hiện hành. Ngưỡng và preferred target lấy mẫu riêng một lần cho mỗi EV; quyết định còn xét hoạt động, ca taxi, chuyến đã biết và reserve5%. Nhu cầu kWh được cập nhật theo SOC tại trạm. Xem [phân phối và retry](GAMA_ENERGY_CHARGING_VI.md). Native driving, GIS/gates, lịch hoạt động và hành vi vẫn là giả định phát triển, chưa hiệu chỉnh bằng dữ liệu Nha Trang thực. Connector generic-public là giả định tương thích chưa khảo sát.

Không diễn giải các khác biệt activation nội sinh là tự động cải thiện. Báo cả opportunity, eligibility, failure, unmet energy, SOC, stranded và thời gian phục vụ. Phần methodology triển khai nằm tại [bản mô tả](manuscripts/METHODOLOGY_IMPLEMENTED_VI.md); PDF lịch sử được giữ nguyên.

ETA calibration dùng tất cả arrival legs quan sát được, không chỉ phiên sạc hoàn tất. Nhu cầu đã chọn đích nhưng không đến trước terminal được thống kê riêng; xác suất đến trước terminal dùng Beta(1,1) train prior. Phân phối ETA điều kiện trên arrival và arrival probability là hai thành phần riêng. Không gán nhãn latent compliance từ arrival tổng hợp.

Stabilization không tác động No-Prediction: baseline này luôn đánh giá snapshot thô đã nhận. Các phương pháp có prediction có thể dùng cùng forecast filter nếu design validation chọn; mặc định mọi phương pháp đều off.
