# Chạy mô hình và thu dữ liệu training trong GAMA

Môi trường `persistent-controlled-v2`, ngày 15/10/2026. GAMA là simulator chính thức; GUI và Headless dùng chung GAML. Thông số đầy đủ: [GAMA_SETTINGS_REFERENCE_VI.md](GAMA_SETTINGS_REFERENCE_VI.md).

## Xem mô phỏng

Mở `models/main.gaml` → **Run me**. Chọn Method và các tham số trước khi khởi tạo, sau đó Play. Computer có bản đồ GIS, 11 trạm, ô tô thường màu đỏ, EV cá nhân VinFast xám và taxi Xanh SM xanh ngọc.

Có ngay 3.000 ô tô thường, 1.000 EV cá nhân và 700 taxi điện. Lúc 00:00 phần lớn xe đỗ; icon chồng nhau không biểu thị số lượng thật. Xem các monitor số xe. Xe được thêm dần trong giờ cao điểm tại cửa ngõ; phát sinh yêu cầu sạc không thêm xe.

Nếu chưa có model, Auto GUI preview bật development weights và nhãn UNTRAINED. Samples, số xe, nhu cầu và giờ bắt đầu vẫn giữ giá trị đã chọn. Khi nạp model đã học, cấu hình vật lý phải khớp; không tự lấy cấu hình cũ để thay môi trường mới.

## Thu calibration không cần terminal

1. Đóng simulation đang mở, chọn **Collect training data** trong `models/main.gaml`.
2. Chọn **Calibration seed (restart required)** = **800001**. Giữ **Collection experiment=true**.
3. Play. Experiment nạp cấu hình calibration chuẩn: 6 giờ warmup + 6 giờ đo + tối đa 6 giờ settlement, bước 1 giây; đây là giờ mô phỏng. Có Computer và monitor **Calibration status**.
4. Chờ `COLLECTION COMPLETE`. Không coi Pause/Stop giữa chừng là một lượt hoàn chỉnh.
5. Đóng simulation, lặp lại với **800002**, rồi **800003**.
6. Trong simulation collection, mở bảng **Commands** của experiment và bấm **Validate and build calibration**. Chờ thông báo `CALIBRATION READY: <đường dẫn>`.

Mỗi seed tạo thư mục mới trong `outputs/gama_ranr/gui_calibration/runs/collect_<seed>_<timestamp>/`. Không ghi đè lượt cũ. Nút kiểm chứng dùng lượt mới nhất của mỗi seed; nếu lượt mới nhất dở dang, cần chạy lại đầy đủ. Không tự chọn dữ liệu cũ để bỏ qua lỗi.

File thành công nằm dưới `outputs/gama_ranr/gui_calibration/builds/<timestamp>/calibration.json`; `latest.json` trỏ tới file và hash. Python đọc cấu hình research sẽ tự tìm calibration đã xây và kiểm tra phiên bản/nguồn. Nếu nguồn hoặc môi trường thay đổi, cần thu lại; kết quả cũ vẫn được giữ.

`CALIBRATION NOT READY` có thể do thiếu seed, chạy chưa hết, sai cấu hình/nguồn, thiếu outcomes, file bị sửa hoặc chưa đủ snapshots, energy/release fractions và ETA samples. Xem `bridge_status.json` của lượt chạy. Không có yêu cầu sạc vì SOC chưa thấp cũng là dữ liệu thực; không ép pin hoặc sinh xe để đủ mẫu.

**Thu calibration chưa phải CMA-ES.** Bật Calibration collection dùng lựa chọn trạm theo hành vi nền để thu prior; các phiên bản chưa huấn luyện không được gọi là model research.

## Cơ hội sạc và giờ cao điểm

- Mặc định private EV 0,2 cơ hội/ngày, taxi 0,8 cơ hội/ngày; tổng cơ bản kỳ vọng 760 cơ hội/ngày, xấp xỉ 0,528/phút. Số yêu cầu kích hoạt còn phụ thuộc SOC <30%, trạng thái xe và lịch hoạt động.
- Mỗi cơ hội gắn với một ID xe, được xét một lần. Bỏ qua với lý do cụ thể khi không đủ điều kiện; không đổi sang xe khác.
- Mục tiêu sạc 80%; năng lượng yêu cầu chốt từ SOC tại lúc kích hoạt. Chỉ sạc công cộng, không tự sạc tại nhà.
- Rush 05:30–07:30 và 17:00–20:00. Xe nhập dần; xe đang di chuyển/sạc không bị xóa khi hết rush. Xe lưu lại chiếm hạn mức của đợt sau.
- Cửa ngõ là các điểm ngoài lõi theo bốn hướng trên mạng đường, được kiểm chứng tuyến hai chiều; đây là ranh giới nghiên cứu tạm thời, chưa được xác nhận là ranh giới hành chính. Xem `gateway_validation.json`.

## Dữ liệu mỗi lượt

`configuration.json`, `initial_fleet.json`, `opportunities.json`, `traffic_plan.json` mô tả đầu vào và điều kiện ngoại sinh. `opportunity_results.csv` ghi activation/lý do bỏ qua. `traffic.csv` ghi nhập/xuất, `vehicles.csv` ghi trạng thái/SOC/quãng đường/năng lượng tích lũy theo giờ mô phỏng. Các trace, snapshots và sự kiện được ghi theo buffer. `outcomes.json`, `metrics.json`, `completion.json` chỉ hoàn chỉnh khi episode kết thúc.

Ba file manifest ngoại sinh phải giống nhau giữa phương pháp cùng seed. Số yêu cầu kích hoạt và kết quả sạc có thể khác do trạng thái nội sinh; báo cáo cả hai.

## Pipeline sau calibration

Correctness validation → development dài → benchmark GAMA/accuracy gate → CMA-ES và long validation → test ghép cặp → báo cáo. Training + validation chính tối đa 72 giờ theo ngân sách đo được. Model/calibration phiên bản trước bị từ chối.

Đợt refactor chỉ chạy smoke và kiểm thử nhỏ. Chưa có benchmark dài, calibration đủ ba seed, model đã học hoặc test research cho môi trường mới. CLI chi tiết tại [README](../README.md); không cần dùng CLI để thu calibration bằng GUI.
