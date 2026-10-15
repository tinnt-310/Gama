# Hồ sơ thay đổi khoa học — persistent-controlled-v2

Ngày 15/10/2026. Nguồn/tài liệu trước refactor được giữ trong `outputs/gama_ranr/unified_fleet_v2_20261015/source_before.tar.gz`, kèm SHA-256. Dữ liệu GIS và kết quả lịch sử không được chuyển thành bằng chứng cho môi trường mới.

| Vấn đề / công thức trước | Quyết định hiện tại | Giả định, ảnh hưởng và kiểm chứng |
|---|---|---|
| GUI và Headless chọn hai cơ chế fleet khác nhau qua cấu hình hoặc Run ID | Một vòng đời xe và một controlled opportunity mechanism | Run ID chỉ định danh output; kiểm tra cùng manifest và fixture bốn phương pháp |
| Fleet GUI 3000/594/1138; controlled không có EV cơ bản | Fleet 3000/1000/700, tổng 4700, tồn tại cả khi đỗ/sạc | Cấu hình nghiên cứu tạm thời; startup GAMA kiểm tra số thực tế |
| Request tạo private_ev; terminal demand xóa EV | Cơ hội gắn ID có sẵn; terminal giải phóng phiên, giữ agent | Không tạo xe theo request, kể cả burst; fixture duplicate opportunity và persistent count |
| SOC khởi tạo suy từ năng lượng demand | SOC ban đầu keyed uniform [40,100]; giảm theo quãng đường, tăng từ năng lượng trạm | Không đặt lại pin khi activation; log lifetime distance/charging energy để kiểm tra bảo toàn |
| Xe hết pin bị xóa | Giữ stranded, không tự hồi pin, không nhận cơ hội tiếp | Không loại xe khó khỏi population; báo stranded và thiếu năng lượng riêng |
| Sạc tại nhà song song với request SOC | Chỉ sạc công cộng trong mô hình nghiên cứu | Phạm vi điều phối 11 trạm; nhánh reference lịch sử không được kích hoạt từ GUI nghiên cứu |
| Tốc độ demand từ tải danh định: 0,6×7195×0,9/(60×20)=3,23775/phút | Tần suất cơ hội 0,2/private/ngày và 0,8/taxi/ngày; tổng 760/1440/phút | 760 yêu cầu/ngày là mục tiêu calibration, số thực còn chịu eligibility. Không tự tăng demand để đạt mục tiêu |
| Arrivals cơ bản đồng nhất theo giờ | NHPP theo bảng 24 giờ riêng từng loại; bảng được chuẩn hóa khi lấy mẫu | Bảng dựa khoảng hoạt động của mô hình, chưa hiệu chỉnh thực địa; lưu trong environment.json |
| SOC <30 tự phát sinh yêu cầu ngoài lịch | Chỉ xét cơ hội đã lên lịch; SOC <30 là một điều kiện bắt buộc | SOC đúng 30 không kích hoạt; không chồng phiên, không đổi ID để bù |
| Rush tắt trong controlled; cohort sinh cùng lúc trong thành phố | Traffic plan độc lập demand, nhập dần qua cửa ngõ cả trong settlement | Cap đang hiện diện 900/300/210; giữ xe chưa rời từ đợt trước |
| Hết rush xóa ngay xe không đang sạc | Hoàn thành hành trình/phiên hiện tại, chờ tới giờ dự kiến rồi chạy ra exit | Chỉ xóa xe vãng lai tại exit; stranded có thể lưu lại và chiếm cap |
| Burst tạo EV theo số request | Burst cơ hội trên các ID khác nhau có mặt theo kế hoạch, activation qua eligibility | Ghi thiếu hụt nếu absent/busy/SOC chưa thấp/đang ra; không tạo EV hoặc ép pin |
| Common random numbers theo manifest request đã tạo | Manifest cơ hội, initial fleet và traffic plan cùng seed giữa các phương pháp | Activation là nội sinh, có thể khác. Báo opportunity count, activation, unmet/served và objective cùng nhau |
| Checkbox GUI chỉ ghi raw calibration | Experiment collection đăng ký source/config từ đầu, bridge kiểm chứng và tổng hợp | Ba seed train tách biệt development/test; thiếu mẫu/seed/completion hoặc sai hash bị từ chối |
| Model/calibration schema cũ | Schema v2 + environment version + source/config/artifact hashes | Cần thu lại calibration và retrain; không sửa provenance artifact lịch sử |

## Những hợp đồng được giữ

Bốn phương pháp cùng physics, FIFO, giới hạn EV/port, native driving, snapshot observation và packet đã giao. Python không mô phỏng xe/hàng đợi để thay kết quả GAMA.

Vector chi phí vẫn `[T,W_mean,W_P95,H,U]`. No-Prediction lấy phân phối tại snapshot, không tiến tới ETA, không sinh future arrivals. Với probe cuối FIFO, ngoại tác lên các xe có sẵn H=0; giữ đủ năm trọng số. `w_H` vẫn ảnh hưởng độ phân tán khuyến nghị qua softmax. Snapshot uncertainty chỉ dùng reconstruction từ train/development; snapshot chính xác có thể cho phân phối suy biến. Các phương pháp prediction giữ ngoại tác ghép cặp, loại waiting của probe.

P2P/exposure tiếp tục dùng packet đã nhận, version replacement và TTL. No-P2P phát/nhận 0 packet giữa trạm; prior chỉ từ train. K_true và K_hat tách biệt. Policy không đọc manifest cơ hội hoặc trạng thái thật trạm xa. Các stream được khóa theo ID xe/sự kiện, không theo thứ tự gọi.

Deadline D=360 phút mặc định; với tỷ lệ năng lượng thiếu u và chỉ báo chưa hoàn thành I: `P=D(I+u)`, `W*=waiting/deferral+P`, `T*=travel+W*`. Objective chung: `0,5 mean(T*/D)+0,3 P95(W*/D)+0,2 peak_queue/installed_ports`. Nhu cầu đã kích hoạt có terminal outcome một lần. Cơ hội không kích hoạt được báo riêng, không giả thành request đã chờ. Run không có demand trả metrics hữu hạn và nhãn empty_demand_run; candidate research không được lấy run rỗng làm fitness tốt.

CMA-ES vẫn population 16, ba optimizer seed, ngân sách chung theo benchmark và tối đa 72 giờ training/validation chính; checkpoint và chọn model bằng long validation. Thêm gate development dài của môi trường mới trước training. Không đổi tiêu chuẩn accuracy để vừa máy. Test chính chưa được mở để tuning.

## Giới hạn GIS và bằng chứng

Cửa ngõ là bốn cực ngoài lõi của mạng đường có tuyến hai chiều tới các building trung tâm; tối đa 16 điểm đích được kiểm chứng. Đây là ranh giới nghiên cứu tạm thời, không phải cửa ngõ hành chính đã khảo sát. gateway_validation.json và manifest nguồn ghi provenance, tọa độ và khoảng cách tuyến. Không thêm cạnh giả hoặc sửa GIS gốc.

Native driving là mô hình giao thông GAMA, chưa hiệu chỉnh để tuyên bố tái tạo giao thông thực Nha Trang. Kiểm thử cưỡng bức trạng thái pin/vị trí trong fixture chỉ dùng xác nhận invariant; không nhập vào calibration nghiên cứu. Smoke ngắn và unit fixtures không chứng minh tần suất sạc/ngày hoặc mức nghẽn 125 cổng. Các kết luận đó chờ development dài và benchmark thực.
