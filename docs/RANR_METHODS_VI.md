> Tài liệu lịch sử: mô tả nguồn trước nâng cấp. Đối chiếu tại Git checkpoint `5800181`; hướng dẫn hiện hành ở [GAMA Run Guide](GAMA_RANR_RUN_GUIDE_VI.md).

> **Tài liệu lịch sử của simulator Python.** Từ 14/10/2026, nghiên cứu chính chuyển sang GAMA. Mã tương ứng nằm trong `src/ranr/legacy/python_reference/`; xem [trạng thái GAMA](GAMA_RANR_STATUS_VI.md).

# Phương pháp RANR: hợp đồng khoa học đã cài đặt

Tài liệu này mô tả pipeline Python mới. Các tài liệu B1–B4-N/PDHG cũ thuộc GAMA lịch sử và được giữ để đối chiếu.

## Bốn phương pháp

| Phương pháp | P2P | Waiting | Tiêu chí chi phí | Tham số độc lập |
|---|---|---|---|---:|
| RANR-AW | Có | Phân phối tại ETA | T, W, P95, H, U | 20 |
| No-P2P | Không | Tại ETA; trạm xa dùng prior train | T, W, P95, H, U | 20 |
| No-Prediction | Có | Probe tại thời điểm snapshot | T, W, P95, U | 15 |
| Fixed-Weights | Có | Giống Proposed | T, W, P95, H, U | 4 |

Các trọng số đều được CMA-ES tìm riêng. State features được chặn [0,1] bằng các mốc cố định trước test; cost features chặn [0,5]. Logit cuối cố định bằng 0 loại bất định cộng cùng hằng số của softmax, giữ nguyên lớp hàm. AW dùng năm đầu vào `[1, tải, burst, độ lệch workload outstanding, tuổi thông tin]`; FW chỉ có bias. Uncertainty là căn trace variance của workload categorical còn outstanding và Poisson unseen, chuẩn hóa theo port count và mốc phút. Nó chỉ phụ thuộc state/exposure, không phụ thuộc ETA của EV đang hỏi hoặc compliance thật. Không dùng minimax, Pareto hay assignment trong nghiên cứu mới.

Trạm phát đúng một khuyến nghị theo `p(r) ∝ a(r) exp(-C(r)/temperature)`. `a` dùng công suất công khai và thời gian tiếp cận. Chi phí `C` lấy kỳ vọng qua kernel phản ứng giả định, gồm hành động hoãn/ngoài mạng. Kernel thật, sở thích riêng và sự kiện tương lai chỉ thuộc môi trường.

## Observation và uncertainty

Trạm sở hữu FIFO và cổng của mình. Trạm khác chỉ được biết qua packet đã nhận hoặc prior offline. `PolicySettings` không chứa tải thật, compliance thật hay nhãn scenario. Các đối tượng observation là immutable và không chứa tham chiếu physical agent.

Snapshot local có thông tin phục vụ chính xác. Packet P2P lượng tử hóa thời gian còn lại và năng lượng FIFO thành các khoảng 5 phút/5 kWh, giống nhau cho mọi phương pháp có P2P. Phân phối residual trong khoảng được lấy từ một ngày workload train độc lập, bỏ 6 giờ khởi động. Nó là mô hình hiệu chỉnh trong mô phỏng, không phải nhận dạng tài xế từ dữ liệu thực.

No-Prediction lấy mẫu các trạng thái tương thích snapshot, tính probe đến ngay tại snapshot, rồi lấy mean/P95. Nó không tiến snapshot tới hiện tại/ETA và không sinh future arrivals. Snapshot chính xác có thể cho phân phối suy biến; snapshot thô có thể cho P95 lớn hơn mean.

State uncertainty chung vẫn có thể dùng sự chưa xác định của các exposure đã quan sát; No-Prediction không biến thống kê đó thành shadow arrivals hoặc dự báo queue tại ETA. Chi phí W/P95 của baseline chỉ đến từ snapshot.

U gồm độ lệch chuẩn chờ trong scenario và tuổi thông tin tính bằng phút, chặn tuổi tại TTL. Đây là chỉ báo rủi ro có quy ước, không phải chặn trên được chứng minh cho sai số waiting. Tuổi thông tin không tạo xe giả. Cần kiểm tra nhạy cảm của quy ước này trong nghiên cứu tiếp theo.

## Exposure và ngoại tác

Exposure khóa theo issuer, recommendation destination, nhóm ETA/năng lượng/công suất và bin phát. Các packet mang snapshot đầy đủ exposure còn hiệu lực của nguồn; sequence mới thay thế packet cũ. Retransmission và packet đến sai thứ tự không cộng lượt đến. Packet quá cũ được thay bằng prior có nhãn.

Khi thiếu ngữ cảnh request chưa nhận, prior origin/ETA được bootstrap từ building GIS theo issuer gần nhất; prior recommendation dùng cùng capacity/access preference công khai, rồi đi qua kernel giả định. Issuance/background rates lấy từ phân phối train/public GIS, không từ actual future demand. Fixture tổng hợp không có GIS prior dùng fallback được ghi rõ.

Các stream scenario tách: exposure đã phát, recommendation quá khứ chưa nhận sau watermark, recommendation chưa phát ở tương lai, và background không tham gia. Foreground tương lai dùng rate đã quan sát/prior và cùng generative context; không đọc actual scheduled requests. Rate có smoothing 50% với prior train để tránh coi một bin vắng là rate bằng 0. Mốc kết thúc phát sinh demand là lịch thí nghiệm công khai dùng chung, không phải future event information.

ETA của probe cũng được lấy mẫu trong khoảng ±15% giống giả định movement; cùng latent travel factor dùng giữa các candidate để ghép scenario. No-Prediction không dùng bước này.

Mỗi phần tử cohort chỉ lấy mẫu một đích hoặc ngoài mạng cho mỗi scenario. Phần đã đến trước snapshot không được cộng vào future arrivals. Background độc lập chỉ mô tả các nhu cầu không tham gia recommendation. Unseen issuance được mô hình hóa sau watermark nguồn, trong cửa sổ hữu hạn TTL; GIS-conditioned destination/ETA là prior rõ ràng khi thiếu ngữ cảnh, không phải dữ liệu toàn mạng thật.

Không có liên kết cá nhân giữa physical arrival và exposure aggregate. Vì vậy outstanding exposure chỉ là ước lượng xác suất; không khẳng định reconciliation chính xác từng xe. Sai số do cohort averaging, kernel không khớp và outage kéo dài là giới hạn của mô hình.

H tính bằng tổng chờ của các xe khác có probe trừ không có probe, sử dụng cùng future scenario. Chân trời chung kết thúc sau ETA lớn nhất cộng 120 phút. Không đếm chờ của probe trong H. Giá trị âm có thể xuất hiện do cổng không đồng nhất; chi phí congestion chỉ phạt phần không âm, raw H vẫn được lưu.

Với No-Prediction, probe vào cuối FIFO hiện tại không làm chậm xe phía trước. H bằng 0 về cấu trúc và bị bỏ khỏi chi phí; bốn trọng số còn lại được chuẩn hóa lại. Không dùng queue length hoặc utilization thay thế H.

## Mục tiêu và penalties

Deadline D = 360 phút tính từ lúc phát sinh nhu cầu. Năng lượng đích cố định, không tạo lại demand sau thất bại/hoãn để loại nó khỏi mẫu. Retry giữ cùng ID và deadline.

Với tỷ lệ thiếu năng lượng u và chỉ báo chưa hoàn thành I:

`P = D (I + u)`; `W* = waiting_observed + P`; `T* = travel_observed + W*`.

Mục tiêu chung: `0.5 mean(T*/D) + 0.3 P95(W*/D) + 0.2 peak_station_queue/installed_ports`.

Phạt áp dụng một lần cho mỗi demand. Hoãn/ngoài mạng là chưa được phục vụ trong mạng nghiên cứu, không có nghĩa EV ngoài đời không sạc ở nơi khác. Các chỉ số physical waiting, completion và thiếu năng lượng được báo riêng; W* không được gọi là chờ thực tế.

Peak queue bao gồm giai đoạn giải phóng demand đo sau cửa sổ phát sinh nhu cầu. Utilization là tích phân busy-port time trong cửa sổ đo, chia port-time được lắp. Hiện chưa có station-wide power sharing, taper hay mạng điện; công suất thực giới hạn bởi cổng và EV, hiệu suất 0.9.

## Phạm vi GIS và ngẫu nhiên

GIS gốc có 11 trạm, 125 cổng và 7.195 kW. Dùng hình học shapefile như GAMA; tọa độ DBF là metadata. `cs_7` và `cs_8` có lệch geometry–metadata khoảng 35.6 m và 29.9 m, được lưu trong validation, không sửa dữ liệu nguồn.

Road graph noding tại vertex nguồn chung, bidirectional, UTM 49N. Không nối giao cắt không có vertex chung. Routing station–station đã đối chiếu đủ 121 cặp với GAMA; phép tính heap độc lập kiểm tra thêm origin–station.

Nhu cầu là Poisson/thinning có lognormal energy, sở thích và ETA có nhiễu; burst gồm hai đợt 100 request cùng timestamp mỗi ngày đo. Đây là traffic tổng hợp trên GIS thật, không tái tạo native driving hoặc fleet GAMA, không phải traffic Nha Trang đã hiệu chỉnh.

RNG được khóa theo seed, demand ID và loại sự kiện. Thay recommendation không làm trượt RNG của nhu cầu, driver hay movement. Trạng thái runtime có thể khác do policy tạo ra quỹ đạo khác; điều kiện ngoại sinh vẫn ghép cặp.
