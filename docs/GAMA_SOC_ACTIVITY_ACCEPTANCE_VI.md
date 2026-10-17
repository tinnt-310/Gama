# Nghiệm thu cơ chế sạc theo SOC và hoạt động

Nguồn hiện hành dùng `persistent-soc-activity-5`, objective `intent-service-4`. Checkpoint khôi phục trước refactor: `e8f70f35cf67ea7ec565ff07ea5037ab0ec36153`, tại nhánh `checkpoints/before-soc-activity-1792059251970807156`. Nhánh làm việc và các output lịch sử được giữ nguyên.

## Cách kiểm tra

```bash
.venv/bin/python -m unittest discover -s tests
.venv/bin/python -m ranr validate --compile
```

46 kiểm thử Python, biên dịch28 GAML roots và42 lượt GAMA native đã đạt. Marker validation trùng hash nguồn cuối, bao gồm ba ca chống đổi tuyến xe thường giữa đường. Chạy native ba ngày với 6 xe còn qua validator độc lập: 292 bản ghi SOC, 6 intent/6 request, 6 phiên sạc, đủ125 cổng và không có legacy artifact. Các can thiệp SOC và sự cố có chủ ý trong fixture chỉ là thiết lập kiểm thử, không có trong profile thu dữ liệu.

| Test trong yêu cầu | Bằng chứng kiểm tra |
| --- | --- |
| 1. Pin thấp tự yêu cầu sạc | `RanrEnergyTests`, mode `low`: không opportunity, một intent, nhận điện, xe còn sống. |
| 2. SOC trên 30% vẫn thiếu pin cho chuyến dài | Mode `long_insufficient`: SOC35%, threshold15%, pin60kWh, đường thực trên20km và mức tiêu thụ stress-test1,0kWh/km, chặn khởi hành, tạo `trip_energy`, sạc rồi tiếp tục. |
| 3. Chuyến dài đủ pin được thực hiện | Mode `long_feasible`: cùng mức tiêu thụ stress-test, SOC95%, hoàn tất trên20km mà không tạo request sạc. |
| 4. Hoạt động cá nhân | Mode `activity`: hoàn tất chuyến đã nhận, giữ intent đang hoãn, yêu cầu khi hoạt động cho phép. |
| 5. Ca taxi và hành khách | Mode `passenger` không gửi request khi có khách; mode `shift` phát hiện thiếu năng lượng trước ca dù SOC cao hơn threshold. |
| 6. Retry hợp lệ | Mode `retry`, `unavailable`, `drain`: cùng intent, cooldown dương, có thể xử lý sau khi trạm hoạt động trở lại và trong drain. |
| 7. Không request trùng | Gọi lại `ranr_start_attempt` khi đã có request không tăng số attempt; contract kiểm tra ID duy nhất. |
| 8. Không vòng lặp vô hạn | Mode `retry`: số attempt bị chặn bởi thời gian/cooldown; contract kiểm tra thời điểm tăng nghiêm ngặt và deadline. |
| 9. SOC giảm theo đường thực | Fixture kiểm tra đẳng thức SOC = SOC đầu + điện nhận − điện tiêu thụ theo tổng mét đường. |
| 10. SOC tăng nhờ sạc vật lý | `RanrPhysicalTests` và validator độc lập đối chiếu năng lượng, cổng, công suất, thời gian; kiểm thử âm bắt SOC tự tăng. |
| 11. Xe còn sống sau sạc | Các energy mode và episode kiểm tra agent; chạy ba ngày kiểm tra quần thể nền còn đủ. |
| 12. Cấp/trả cổng | Physical/port-outage/episode tests; validator bắt dùng trùng cổng, kiểm tra giải phóng cuối lượt. |
| 13. Không scheduler sạc ngẫu nhiên | Kiểm tra mã/config loại bỏ API cũ; validator từ chối artifact opportunity. |
| 14. Không quota request | Không còn frequency/quota/burst-size trong RunConfig và GUI; scenario burst chỉ đồng bộ giờ khởi hành. |
| 15. Phân phối riêng và tái lập | `RanrActivityTests`: 1000 private +700 taxi, kiểm tra từng bin/target và thuộc tính không đổi. Bốn phương pháp có hash kế hoạch/traits giống nhau với cùng seed. |
| 16. GUI/Collect cùng hành vi | Collect kế thừa `Run me`; Headless nạp chính `models/main.gaml`, cùng Fleet/ChargingService. |
| 17. Không khôi phục RNG trong move | Kiểm tra mã không gán lại seed/rng_usage trong Mobility/ChargingService; native RNG được seed một lần lúc khởi tạo. |
| 18. Ba dataset mới đúng seed | Đạt sau kiểm chứng artifact: ba manifest complete, đủ4320 phút, đúng800001/800002/800003, nguồn mới và vật lý đạt; cảnh báo nền được ghi riêng, xem bảng/artifact bên dưới. |
| 19. Không giá điện | Architecture test kiểm tra mã charging/policy; không thêm tariff, giá điện hoặc home charging. |
| 20. RANR-AW và vật lý | Scientific/protocol/network/decision/behavior tests kiểm tra FIFO, P2P, exposure, ETA, năm cost/weight, softmax và non-binding; `replan` tái hiện sự cố giữa đường và kiểm tra không teleport. |

## Dữ liệu calibration

**Ba dataset mới đã thu đủ và qua kiểm chứng.** Mỗi lượt60 giây/cycle, 360 phút warm-up +3600 phút measurement +360 phút drain, kết thúc4320 phút; fleet nền3000/1000/700, inbound cap1410, 11 trạm/125 cổng. Cả ba CSV có33 dòng trạm-ngày, đủ ngày1/2/3. Mã nguồn/cấu hình giữ nguyên từ validation tới khi seal manifest.

| Seed | Phút mô phỏng | Intent toàn lượt | Hoàn tất | Chưa giải quyết | Lần yêu cầu | Retry | Xe hết pin |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 800001 | 4320.0 | 2195 | 2194 | 1 | 2346 | 151 | 0 |
| 800002 | 4320.0 | 2290 | 2290 | 0 | 2435 | 145 | 0 |
| 800003 | 4320.0 | 2144 | 2144 | 0 | 2272 | 128 | 0 |

Bảng dùng toàn bộ intent/attempt của mỗi lượt, gồm warm-up và retry hợp lệ trong drain. Số intent trong cửa sổ đo bằng `metrics.objective_components.intent_denominator`, được ghi riêng trong collection.json; retry không làm tăng mẫu số objective.

- Seed800001: [collect_800001_soc_activity_1792066421667216968_validated](../outputs/gama_ranr/gui_calibration/runs/collect_800001_soc_activity_1792066421667216968_validated/manifest.json), kiểm chứng [vật lý](../outputs/gama_ranr/gui_calibration/runs/collect_800001_soc_activity_1792066421667216968_validated/physical_validation.json).
- Seed800002: [collect_800002_soc_activity_1792066421667216968_validated](../outputs/gama_ranr/gui_calibration/runs/collect_800002_soc_activity_1792066421667216968_validated/manifest.json), kiểm chứng [vật lý](../outputs/gama_ranr/gui_calibration/runs/collect_800002_soc_activity_1792066421667216968_validated/physical_validation.json).
- Seed800003: [collect_800003_soc_activity_1792066421667216968_validated](../outputs/gama_ranr/gui_calibration/runs/collect_800003_soc_activity_1792066421667216968_validated/manifest.json), kiểm chứng [vật lý](../outputs/gama_ranr/gui_calibration/runs/collect_800003_soc_activity_1792066421667216968_validated/physical_validation.json).
- Báo cáo tổng hợp và hash: [collection.json](../outputs/gama_ranr/soc_activity_recollection/1792066421667216968/collection.json).
- Bằng chứng validation: [42 lượt native và28 compile roots](../outputs/gama_ranr/soc_activity_recollection/1792066421667216968/ranr-soc-validation.log), [46 kiểm thử Python](../outputs/gama_ranr/soc_activity_recollection/1792066421667216968/ranr-soc-python-tests.log).
- Calibration mới: [calibration.json](../outputs/gama_ranr/gui_calibration/builds/soc_activity_1792066421667216968_validated/calibration.json); chứa1408 prior snapshots và tham chiếu đúng3 manifest mới. Con trỏ `outputs/gama_ranr/gui_calibration/latest.json` đã cập nhật; không lấy mẫu từ output cũ.
- Checkpoint nguồn cuối: `5cc7ffeeeab910f1877ed00ba5a0a17a86fc7614`; fingerprint runtime/traffic plugin và phiên bản nguồn nằm trong từng dataset và báo cáo. Mỗi JVM tối đa4096MiB heap; ba seed chạy ở ba tiến trình độc lập.

Lượt thu thử `1792064512998785854` đã bị dừng và loại khỏi calibration sau khi phát hiện xe thường2817 của seed800002 đổi tuyến khi chưa tới đích ở phút1500. Output và bằng chứng trước/sau sửa được giữ nguyên. Ba fixture `RanrMobilityTests` và đối chiếu bản ghi mới đã kiểm tra lại lỗi này; validator không bị nới để chấp nhận dữ liệu sai.

**Cảnh báo tài nguyên thực tế:** GAMA phát63/23/6 cảnh báo bộ nhớ tương ứng ba seed. Wrapper Headless ban đầu đánh dấu failed do quét chuỗi `Runtime error`. Cả ba mô phỏng vẫn ghi marker hoàn tất4320 phút. Bytecode GAMA xác nhận đây là warning trên timer nền, không ném lỗi vào bước agent; cách hiển thị đơn vị bộ nhớ còn làm thông báo hiện0MB. Không có `OutOfMemoryError` hoặc lỗi runtime khác trong các log đã duyệt.

Các thư mục gốc/manifest failed được giữ nguyên. Bản `_validated` là bản sao artifact của chính ba lượt đã chạy, không chạy lại mô hình và không sửa dữ liệu vật lý. Dùng `ranr.gama.gui_collection.complete` và `checked_result` hiện có để kiểm chứng lại cấu hình, outcome, SOC/quãng đường/cổng, objective và seal manifest;92 giá trị metric GAMA gốc mỗi lượt vẫn giữ nguyên. Chi tiết: [review cảnh báo](../outputs/gama_ranr/soc_activity_recollection/1792066421667216968/runtime_warning_reviews.json), [log kiểm chứng lại](../outputs/gama_ranr/soc_activity_recollection/1792066421667216968/revalidation.log), `original_launcher_manifest.json` và `runtime_warning_review.json` trong từng dataset. Wrapper chuẩn vẫn nghiêm ngặt với runtime warnings; báo cáo này không coi log là không có cảnh báo.

Intent duy nhất chưa hoàn tất là taxi20115 của seed800001: phát sinh phút3951, hết hạn phút4320, SOC cuối88,667% so với target100%; đã nhận40,95kWh, có261 phút chờ. Không ép hoàn tất phiên để làm đẹp kết quả.

**Chưa chạy full CMA-ES.** Calibration mới không phải bộ trọng số đã huấn luyện.

## Giới hạn diễn giải

Phân phối threshold/target, lịch hoạt động/booking, vận tốc, ca và reserve là giả định nghiên cứu có thể cấu hình, chưa phải số liệu khảo sát Nha Trang. Mô hình sạc hiện dùng công suất hằng có giới hạn cổng/EV và hiệu suất; chưa có taper theo SOC. Kiểm thử chức năng và calibration không chứng minh phương pháp đạt ưu thế thực nghiệm; các gate thiết kế, độ chính xác và ngân sách vẫn áp dụng trước training/evaluation chính.

Nguồn cuối đã kiểm thử: `5cc7ffeeeab910f1877ed00ba5a0a17a86fc7614`, ref `checkpoints/soc-activity-validated-1792066437371948573`. Toàn bộ56 tệp nguồn/cấu hình của provenance đã được đối chiếu với checkpoint; mỗi dataset ghi `code_version.json` và `runtime_version.json` trước khi seal manifest.
