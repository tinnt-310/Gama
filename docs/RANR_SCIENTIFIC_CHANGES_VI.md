> **Tài liệu lịch sử của simulator Python.** Từ 14/10/2026, nghiên cứu chính chuyển sang GAMA. Mã tương ứng nằm trong `src/ranr/legacy/python_reference/`; xem [trạng thái GAMA](GAMA_RANR_STATUS_VI.md).

# Hồ sơ thay đổi so với bản thảo RANR-AW

Nguồn: `manuscripts/RANR_AW_IEEE_Tieng_Viet.pdf`. Bản thảo là mô tả phương pháp chưa có kết quả. Bảng dưới ghi quyết định đã cài đặt, không khẳng định hiệu năng tốt hơn.

| Gốc / vấn đề | Quyết định | Lý do và hệ quả | Bằng chứng / giới hạn |
|---|---|---|---|
| Một proposed; user yêu cầu ba baseline | AW, No-P2P, No-Prediction, FW dùng chung pipeline và train riêng | Tách tác động thông tin, prediction và weight adaptation | Kiểm tra cùng exogenous hash và invariant compliance=0 |
| Snapshot uncertainty chưa xác định | Empirical reconstruction residual từ train; mean/P95 qua scenario | Không tự gán P95=mean; không tiến No-Prediction tới ETA | Tests snapshot thô/exact; calibration samples được lưu |
| Giữ năm tiêu chí khi không có future arrivals dễ tạo H giả | No-Prediction bỏ H, chuẩn hóa lại bốn trọng số | FIFO tail insertion không ảnh hưởng các xe đã ở trước | Scalar/batch counterfactual tests |
| Θ 5×5 có gauge dư | Cố định logit cuối, AW20/FW4/No-Prediction15 tham số | Giảm optimizer dimensions nhưng giữ lớp hàm | Test AW chỉ có bias bằng FW |
| Exposure aggregate không nhận dạng individual arrivals | Cohort categorical choice, survival theo thời gian; không dùng ID ẩn | Tối đa một scenario arrival mỗi thành viên, không giả reservation | Test conservation; averaging/K mismatch vẫn là xấp xỉ |
| Chỉ cộng exposure/background sẽ bỏ sót request recommendation chưa phát | Thêm stream future-unissued, tách khoảng issuance khỏi past-unreceived | Bao phủ future demand không trùng exposure; rate/context từ public train prior | Không đọc actual future requests; off-policy prior vẫn có sai số |
| ETA probe không chắc chắn | Lấy mẫu travel factor ±15%, ghép giữa candidate | Chờ/P95 tích hợp bất định ETA của EV hiện tại | No-Prediction giữ probe tại snapshot |
| State feature có thang khác nhau | Đưa rho/burst/uncertainty/age về [0,1] bằng mốc vật lý cố định | Tránh logit saturation do tuổi missing lớn, không tune bằng test | Bounds/gauge giống nhau cho mọi policy |
| Dữ liệu không nhận có thể thiếu | Prior từ train và unseen issuance sau watermark, TTL hữu hạn | Không lấy queue global hoặc gán missing=0 | No-P2P packet count=0; tests unreceived/stale |
| U chưa có công thức vận hành duy nhất | Scenario spread + age surcharge, quy đổi phút | Gọn và minh bạch; không có sai số-bound lý thuyết | Cần sensitivity; chưa nhận dạng hành vi thực |
| Phi uncertainty không thể lấy compliance thật | Dùng variance workload categorical/Poisson từ state và exposure | State uncertainty thay đổi theo observations, không nhận nhãn hành vi ẩn hoặc ETA của request hiện tại | PolicySettings không chứa true compliance/load |
| H có thể âm do heterogeneous scheduling | Lưu raw net H, chỉ phạt phần dương trong cost | Congestion penalty không thưởng negative artifact | Chưa chứng minh ngoại tác toàn thành phố |
| Softmax/cost có nhiều đơn vị | Mốc vật lý cố định T30/W60/R120/H120/U60 phút, clip [0,5] | Không dùng test để chia thang; các phương pháp dùng cùng mốc | Đây là quy ước public, không phải normalizer learned |
| Objective có communication khi protocol fixed | Objective T* mean, W* P95 và peak queue; communication báo riêng | Không ưu ái No-P2P trong training vì bytes=0 | Penalty tests, same optimizer objective |
| Bỏ unserved khỏi metrics gây selection bias | D360; P=D(I+missing_fraction); mọi demand vào objective | Hoãn/failure không thoát mẫu; physical metrics vẫn riêng | Tests full/partial/no-service; deadline sensitivity chưa chạy đủ |
| Training duration/computational budget chưa đặc tả | 6 short GIS episodes: 10m warmup, 20m measurement + settlement; validation độc lập cùng protocol | Giảm cost per evaluation trước CMA-ES; train có burst100 và capacity variation | Short-episode generalization sang 72h là giới hạn phải đo trên test |
| Ngân sách cố định có thể lãng phí | Mỗi optimizer seed min1024/max4096; validation256; patience3 và 1% | Cùng rule/opportunity cho bốn phương pháp, không chuyển budget | Histories ghi budget thực; smoke32 không phải research |
| Queue simulation tốn CPU | Native FIFO C++17, không fast-math; prefix pruning giữ mọi real event | Tối ưu số học, không thay estimator | Randomized NumPy/scalar equivalence tests |
| Sampling request marks tạo nhiều ma trận rỗng | Splitting chính xác của marked Poisson cho request mới; origin lấy từ luật conditional theo destination | Giữ joint distribution của mô hình Poisson; không dùng splitting cho cohort có count cố định | Test mean/variance/covariance và conservation cohort |
| GIS metadata và geometry lệch | Dùng shapefile như GAMA, giữ metadata và báo offsets | Không sửa source; giữ công bằng môi trường | 121 GAMA route pairs sai số max ~1.7e-7m |

Mọi thay đổi sau khi xem test phải tạo version và test set mới. Không tune normalizer, kernel, penalties hoặc scenario count theo test outcomes. Không gọi các weights zero/equal của benchmark là trained model.

Cơ sở splitting: [Gallager, MIT OCW — Poisson combining and splitting](https://ocw.mit.edu/courses/6-262-discrete-stochastic-processes-spring-2011/resources/lecture-5-poisson-combining-and-splitting/). Áp dụng cho marked process của mô hình hiện tại bằng conditional origin sampling; đây là biến đổi phân phối, không phải giả định EV thật là Poisson.
