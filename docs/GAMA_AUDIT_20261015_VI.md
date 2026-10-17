# Rà soát lỗi GAMA — 15/10/2026

## Cập nhật sau yêu cầu sửa

Đã triển khai bản sửa cho các mục **1, 2, 3, 5 và 6** theo yêu cầu người dùng: bỏ replay RNG tại cả ba vị trí, đóng băng đầy đủ cấu hình, chặn runtime sau lỗi đăng ký collection, chốt thống kê ngày cuối trước completion và dùng chung validator số thực. Mục **4 — ngữ nghĩa Target SOC** sau đó đã được sửa trong refactor [sạc theo SOC và hoạt động](GAMA_ENERGY_CHARGING_VI.md): tính lại năng lượng tại SOC đến trạm. Phần bằng chứng phía dưới là lịch sử trước sửa.

Đã bổ sung hai fixture GAMA `RanrLifecycleTests.gaml`, `RanrStartupFailureTests.gaml` vào lệnh `ranr validate`, cùng kiểm thử Python cho làm tròn số và thay đổi cấu hình thật. Chi tiết cách chạy sau cập nhật nằm trong [run guide](GAMA_RANR_RUN_GUIDE_VI.md). Phần dưới giữ bằng chứng của lần rà soát trước khi sửa.

Kết quả nghiệm thu bản sửa và phép đo hai lượt 400 cycle cùng seed nằm trong [báo cáo sửa runtime](GAMA_RUNTIME_FIXES_VI.md): 33 kiểm thử Python, 27 file GAML compile và 29 lượt fixture GAMA đều đạt; dữ liệu hai lượt native driving đối chiếu khớp hoàn toàn.

Phạm vi: mã hiện có trong workspace, luồng collection GUI, RNG, cập nhật cấu hình, sạc và kết thúc episode nhiều ngày. Đây là danh sách phát hiện đã kiểm chứng, không phải cam kết đã tìm hết mọi lỗi. Các bản sửa ở những lượt trước vẫn có trong workspace; các mục bên dưới còn tồn tại tại thời điểm rà soát.

Các phép thử bổ sung chạy trên bản sao trong `/tmp/ranr-audit-l647zxc4`. Mã mô phỏng và cấu hình của lượt GUI hiện hành không được thay đổi trong lần rà soát này. Báo cáo này nằm ngoài danh sách nguồn được băm cho calibration.

## 1. P1 — Khôi phục RNG lặp lại lịch sử, gây chậm nghiêm trọng

Vị trí: [Mobility.gaml:286](../models/Mobility.gaml#L286), [ChargingService.gaml:374](../models/ChargingService.gaml#L374), [Fleet.gaml:211](../models/ranr/Fleet.gaml#L211).

Mã lưu `seed` và `rng_usage`, thay seed để thực hiện `drive` hoặc tạo xe inbound, rồi khôi phục seed và usage. Trong GAMA 1.9.3 đang cài, `IGamaRNG.setUsage(n)` gọi `nextInt()` n lần. Khôi phục usage có chi phí tuyến tính theo số lượt RNG phải sinh lại, lặp cho từng xe.

Bằng chứng trực tiếp từ JVM đang chạy: hai bản ghi luồng cách nhau khoảng 33,5 giây đều dừng trong `Random.nextInt → IGamaRNG.setUsage → RandomUtils.setUsage`. Cùng một luồng tăng CPU từ 510543 ms lên 544057 ms. Các bản ghi nằm tại `/tmp/ranr-live-threads.txt` và `/tmp/ranr-live-threads-2.txt`.

Xử lý: thay cơ chế cô lập RNG để tránh phát lại lịch sử, giữ tính tái lập theo seed; kiểm tra cả ba vị trí, bao gồm tạo xe inbound. Đo lại tốc độ khi xe bắt đầu di chuyển và đối chiếu kết quả lặp cùng seed. Các mẫu trên xác nhận việc tính toán tốn CPU; không chứng minh có deadlock hoặc race condition.

## 2. P1 — Khóa cấu hình giữa episode chưa đầy đủ

Vị trí: [Runtime.gaml:519](../models/ranr/Runtime.gaml#L519).

Guard kiểm tra method, step, fleet và nhiều tham số thiết kế, nhưng bỏ sót `ranr_case`, `ranr_true_compliance`, `ranr_true_defer` cùng các tham số khác có ảnh hưởng hành vi. Người dùng đổi các ô này giữa lượt có thể làm hành vi thực khác bản cấu hình được lưu lúc khởi tạo.

Tái hiện trong `AuditGuard.gaml`: đổi các tham số ở cycle 1. Mô phỏng hoàn tất, `ranr_error` rỗng:

| Tham số | configuration.json | Giá trị cuối lượt |
|---|---|---|
| case | normal | low_compliance |
| compliance | 0.8 | 0.123 |
| defer_probability | 0.05 | 0.7 |

Xử lý: khóa toàn bộ tham số tác động mô phỏng và provenance; kiểm tra cùng một bộ cấu hình chuẩn hóa ở GUI, runtime và Python. Các điều khiển chỉ ảnh hưởng hiển thị có thể thay đổi độc lập.

## 3. P2 — Khởi tạo collection thất bại vẫn có thể chạy reflex runtime

Vị trí: [main.gaml:80](../models/main.gaml#L80), [Runtime.gaml:519](../models/ranr/Runtime.gaml#L519).

Khi bridge không trả `COLLECTION REGISTERED`, init gán `ranr_error`, pause rồi return, nhưng chưa đánh dấu episode hỏng hoặc `ranr_done`. Khi tiếp tục step, `ranr_tick` có thể gọi `ranr_initialize` trên thế giới chưa tạo đường, trạm và xe.

Tái hiện bằng bridge giả lập trả `CALIBRATION NOT READY: AUDIT_REGISTRATION_FAILURE` trong bản sao: runtime báo `Assert failed: length(ranr_stations) = 11`. Nội dung lỗi đăng ký ban đầu không xuất hiện trong console của phép thử. Đây là lỗi phụ che nguyên nhân ban đầu.

Xử lý: chặn runtime khi init thất bại, ghi rõ lỗi gốc và trạng thái failed; tiếp tục chạy phải yêu cầu khởi tạo lại thành công.

## 4. P2 — SOC hoàn tất có thể thấp hơn Target SOC

Vị trí: [Fleet.gaml:261](../models/ranr/Fleet.gaml#L261), [ChargingService.gaml:281](../models/ChargingService.gaml#L281), [ChargingService.gaml:212](../models/ChargingService.gaml#L212).

Năng lượng yêu cầu được tính từ SOC lúc phát sinh nhu cầu. Năng lượng hao trên đường tới trạm làm SOC giảm, nhưng lượng cần sạc không được tính lại để bù phần này. Phiên được đánh dấu completed khi đã cấp đủ lượng kWh yêu cầu ban đầu.

Tái hiện trong fixture vật lý có kiểm soát: pin 60 kWh, SOC ban đầu 29%, target 80%, yêu cầu 30,6 kWh. Giả lập tiêu hao 0,6 kWh trước khi tới trạm bằng cách giảm SOC xuống 28%. Sau khi sạc đủ 30,6 kWh, trạng thái completed nhưng SOC chỉ 79%.

Xử lý: làm rõ và thống nhất ý nghĩa Target SOC. Nếu đây là SOC phải đạt khi rời trạm, phải tính phần thiếu từ SOC lúc đến, đồng thời cập nhật dự báo, demand/outcomes và kiểm tra bảo toàn năng lượng. Nếu chủ đích là cấp lượng kWh cố định từ lúc yêu cầu, giao diện và tài liệu cần mô tả đúng hành vi đó.

## 5. P2 — Thiếu thống kê ngày cuối khi kết thúc đúng nửa đêm

Vị trí: [main.gaml:173](../models/main.gaml#L173), [Runtime.gaml:570](../models/ranr/Runtime.gaml#L570).

Runtime kết thúc episode và đặt `ranr_done` trước khi reflex `export_daily_statistics` được thực hiện. Điều kiện `!ranr_done` khiến reflex bỏ qua ngày cuối.

Tái hiện trong `AuditDays.gaml`: episode kết thúc đúng phút 4320, completion báo complete, nhưng `daily_statistics.csv` chỉ có ngày 1 và 2; ngày 3 không được ghi. Fixture dùng 0 xe và bước 3600 giây để kiểm tra thứ tự kết thúc; đây không phải đánh giá độ chính xác giao thông với bước lớn.

Xử lý: chốt bản ghi thống kê cuối trước khi hoàn tất episode, bảo đảm không ghi trùng nếu thời điểm cuối cũng là ranh giới ngày. Việc thiếu CSV này không tự chứng minh metrics.json cũng sai; metrics dùng đường tính riêng.

## 6. P2 — GUI có thể từ chối nhầm cấu hình vì làm tròn JSON

Vị trí: [gui_collection.py:84](../src/ranr/gama/gui_collection.py#L84), đối chiếu [contracts.py](../src/ranr/gama/contracts.py).

GUI complete so sánh số bằng `!=` chính xác. GAMA hiện xuất giá trị `1/3` thành `0.33333333`, trong khi manifest Python lưu `0.3333333333333333`.

Tái hiện gồm hai phần: `AuditPrecision.gaml` xác nhận giá trị JSON do GAMA ghi; fixture Python đặt compliance tương ứng. `validate_configuration` hiện có chấp nhận sai số này, nhưng `gui.complete` báo `Collection configuration mismatch: compliance`.

Xử lý: dùng chung validator cấu hình với dung sai số thực đã quy định; giữ so sánh chính xác cho chuỗi, boolean và số nguyên. Trường hợp này là lỗi có điều kiện khi dùng các giá trị cần làm tròn, không phải bằng chứng bộ tham số mặc định hiện tại sẽ bị từ chối.

## Kiểm tra đã chạy

- 31 kiểm thử Python hiện có: đạt.
- GAMA protocol, physical và network fixtures: đạt.
- Các probe bổ sung đã tái hiện ranh giới ngày cuối, SOC mục tiêu, lỗi đăng ký, độ chính xác JSON và guard cấu hình.
- Các probe ba ngày dùng thế giới 0 xe và bước lớn để kiểm tra điều khiển; chưa chạy nghiệm thu 3 ngày với toàn bộ 4700 xe.

Những kiểm thử cơ bản đạt không bao phủ các lỗi nêu trên. Ưu tiên sửa RNG và khóa cấu hình, sau đó xử lý init, ngữ nghĩa Target SOC, chốt thống kê và validator số thực; thu calibration mới sau khi kiểm chứng bản sửa.
