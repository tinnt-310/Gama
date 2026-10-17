# Sửa lỗi runtime GAMA — 15/10/2026

Báo cáo lịch sử của checkpoint trước refactor SOC/activity. Cơ chế RNG native hiện tại chỉ seed lúc khởi tạo; không còn reset seed trong movement/inbound. Xem [thiết kế hiện hành](GAMA_ENERGY_CHARGING_VI.md).

Đã sửa năm mục được chọn từ [báo cáo rà soát](GAMA_AUDIT_20261015_VI.md).

| Mục | Hành vi sau sửa |
|---|---|
| RNG | Bỏ toàn bộ gán lại `rng_usage` tại native driving của car/EV và tạo xe inbound. Stream native được khởi tạo lại bằng seed theo xe/tương tác; các quyết định theo khóa dùng master seed cố định. Dùng generator `mersenne` và tắt parallel trên species vehicle. |
| Khóa cấu hình | So sánh giá trị thực của các tham số đầu vào với snapshot sau khởi tạo; sao chép các list để phát hiện sửa tại chỗ. Bao gồm scenario, compliance, defer, collection seed, trace, parameter vector, các trọng số giờ và chế độ bật/tắt. Thay đổi hiển thị được phép. |
| Khởi tạo collection | Khi bridge trả kết quả đăng ký thất bại, chuyển sang trạng thái failed, ghi lỗi gốc và chặn runtime chạy trên thế giới chưa có trạm. Lưu `failure.json` khi thư mục run đã tồn tại. |
| Thống kê ngày cuối | Hook trước khi hoàn tất episode chốt các ngày đã kết thúc. Dùng chung action với reflex thống kê ngày, chống ghi trùng bằng bộ đếm ngày. Giữ các cột lũy kế hiện hành. |
| So sánh số thực | GUI dùng chung `validate_configuration` với headless, chấp nhận sai số làm tròn JSON của float. Boolean và các giá trị integer được kiểm tra chính xác; seed `800001.0` vẫn khớp integer `800001`. |

Khi guard phát hiện thay đổi, thông báo chứa tên tham số: `Configuration changed: <setting>; restart required`. Lý do được ghi trong `failure.json` của thư mục run đã khóa, kể cả khi tham số bị thay đổi là output directory.

## Kiểm chứng

Kết quả cuối: **33 kiểm thử Python đạt**, **27 file GAML biên dịch thành công**, **29 lượt fixture GAMA trong `ranr validate --compile` đạt**, và hai lượt fixture bổ sung cho sạc/native driving đạt. `outputs/gama_ranr/validation.json` ghi passed với source hashes khớp mã hiện hành. Log phiên kiểm chứng nằm tại `/tmp/ranr-five-fixes-validation.log` và `/tmp/ranr-five-fixes-python.log`.

Các fixture hồi quy mới được tích hợp vào `.venv/bin/python -m ranr validate --compile`:

- `RanrStartupFailureTests.gaml`: giữ nguyên lỗi đăng ký, không chạy bước runtime và không sinh completion giả.
- `RanrLifecycleTests.gaml`: chạy đến phút 4320 với step 60 và 0 xe để kiểm tra vòng đời ba ngày; xác nhận chốt ngày cuối không ghi trùng. Kiểm tra đổi scenario, compliance, defer, trace, sửa parameter vector/hour weights tại chỗ, collection seed và bật/tắt; kiểm tra thay đổi hiển thị vẫn chạy được.
- Python: trường hợp `1/3` được GAMA làm tròn thành `0.33333333` được chấp nhận; thay đổi thật về xác suất, count, boolean, scenario và packet loss vẫn bị từ chối.

Hai lượt **Collect training data** cùng seed **800001**, step **60 giây**, chạy giới hạn **400 cycle**, có fleet nền **4700 xe** và inbound theo cấu hình, trên bản sao riêng trong `/tmp`:

| Lượt | Thời gian thực, gồm khởi tạo/launcher | Phút mô phỏng ghi cuối | Xe di chuyển | Tổng xe hiện diện |
|---|---|---|---|---|
| 1 | 114,19 giây | 399 | 1344 | 5510 |
| 2 | 100,78 giây | 399 | 1344 | 5510 |

Các hash của `initial_fleet.json`, `opportunities.json`, `traffic_plan.json`, `vehicles.csv`, `population_population.csv`, `traffic.csv`, `opportunity_results.csv` khớp hoàn toàn giữa hai lượt. Chi tiết tại [benchmark.json](../outputs/gama_ranr/runtime_fixes_20261015/benchmark.json).

Phép đo chạy headless, tắt hiển thị; tốc độ GUI khi vẽ bản đồ có thể khác. Đây là kiểm tra qua thời điểm bắt đầu di chuyển và inbound, chưa phải nghiệm thu đủ ba ngày với 4700 xe. Các lượt giới hạn 400 cycle là dữ liệu kiểm thử dừng sớm, không dùng để build calibration.

Kiểm thử sạc đã hoàn tất và kiểm thử native driving tới trạm (`RanrEpisodeTests.gaml`, cả hai chế độ fixture) đều đạt. CSV của fixture ba ngày có đúng **33 dòng duy nhất = 11 trạm × 3 ngày**.

## Chạy lại trên GUI

1. Đóng experiment cũ và Refresh dự án trong GAMA.
2. Mở lại **Run me** hoặc **Collect training data**. Mặc định vẫn là **1 phút/cycle**, tổng **3 ngày mô phỏng**.
3. Với collection, thu lại đủ seed **800001**, **800002**, **800003** trên cùng mã mới rồi build calibration. Các nguồn và hash đã thay đổi; không tiếp tục lượt cũ để nghiệm thu dữ liệu cho mã mới.

Vấn đề về cách hiểu **Target SOC** trong mục 4 của báo cáo rà soát vẫn còn mở và được giữ nguyên trong lần sửa này.
