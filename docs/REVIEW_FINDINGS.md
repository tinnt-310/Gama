> Tài liệu lịch sử: mô tả nguồn trước nâng cấp. Đối chiếu tại Git checkpoint `5800181`; hướng dẫn hiện hành ở [GAMA Run Guide](GAMA_RANR_RUN_GUIDE_VI.md).

# Đối chiếu bảy nhận xét và sửa mã — 08/10/2026

Phạm vi: xác minh nhận xét trên source GAML/Python và runtime GAMA 1.9.3, gia cố rounding, cập nhật ETA và event export. Giữ primal, PDHG equations, entropy prox, step sizes, rounding probabilities và exact repair. Không thêm robot scheduler hoặc network backend.

| Nhận xét | Kết luận sau khi kiểm tra | Xử lý |
|---|---|---|
| Entropy prox có thể cho x>1, nên vi phạm miền primal | x>1 có thể xuất hiện ở **raw iterate**. Splitting hiện dùng prox trên x≥0, coupling sum(x)=1 qua dual. Giao của các ràng buộc vẫn là simplex nên feasible optimum có x≤1. Đây không tự động là lỗi primal; raw iterates cũng chưa cần thỏa equality/epigraph. | Ghi rõ domain trong code và batch config. Thêm kiểm tra projected xp∈[0,1], sum(xp)=1 và tests phân biệt raw prox với assignment khả thi. Physical commit chỉ nhận binary z sau recovery. Không clip prox tùy ý rồi gọi đó là cùng numerical implementation. |
| Rounding thiếu bảo vệ traversal/termination | Đúng về thiếu guard; chưa tái hiện một cycle sai trên input hợp lệ. Tuy vậy parent chain/path cần fail-fast khi invariant bị phá. | Cả GAML/Python chỉ nhận back-edge tới ancestor đang active; bảo vệ parent chain, path không lặp, cycle chẵn, trail không trùng, alpha/beta dương. Mỗi step phải giảm số fractional edges nên số steps ≤ số cạnh ban đầu. Kiểm tra station IDs duy nhất, shape/finite input Python và degree sau rounding. |
| ETA gần cố định, khác tốc độ vận hành | Đúng là giới hạn ETA cũ. | Default ETA `snapshot_speed` dùng cùng `road_speed_factor=max(.1,min(1,speed_coeff))` với physical move. Cộng thời gian theo từng road segment/current-edge remainder. Inbound dùng committed path, không thay bằng shortest path mới. `nominal_speed` giữ làm ablation. |
| Fixed-port C là fluid capacity, không exact discrete waiting | Đúng; đây là abstraction được chọn, không phải ground-truth waiting model. | Giữ causal workload recurrence. F/d*pi chỉ mang nhãn congestion surrogate. Actual Waiting lấy start−arrival; đánh giá actual Travel+Waiting từ events. |
| Logical messages không phải network thực | Đúng, đúng với phạm vi synchronous in-process đã chọn. | Config giữ `logical_in_process`; không thêm latency, packet loss, socket bytes hoặc claim network performance. |
| Export toàn bộ event log mỗi batch có I/O lớn | Đúng: cũ serialize rồi rewrite toàn bộ history mỗi lần. | Header chỉ tạo khi mở output prefix; append từ exported-event cursor; flush không có event mới không ghi event file. Giữ format CSV và order. IO counters xuất vào `_io.csv`; station/status vẫn là snapshot nhỏ. |
| Chưa xác nhận compile/runtime | Nhận xét này không phản ánh bằng chứng đã có ở lượt trước. | Chạy lại independent root compilation, GAMA regressions, physical paired benchmarks và Python/reference replay sau lần sửa này. Logs/artifacts bên dưới là bằng chứng trực tiếp; không dựa vào launcher exit code đơn lẻ. |

## Các thay đổi cần lưu ý khi đọc kết quả

ETA snapshot chỉ giả định hệ số tốc độ tại epoch giữ nguyên dọc tuyến dự báo. Nó chưa dự báo acceleration, intersection conflicts, congestion tương lai hoặc độ trễ do native drive; không gọi là exact travel. Routing vẫn theo graph policy hiện có, không biến bài toán thành robot/road-routing optimization. Remaining committed path được dùng khi cập nhật inbound để không giả định EV tự đi theo một shortcut vừa xuất hiện.

`nearest` tiếp tục chọn trạm theo **road distance**, không đổi thành fastest ETA baseline. Candidate list của proposed/TOP_K vẫn được sắp theo ETA; nearest flag trong candidates CSV được tính riêng. ALL_FEASIBLE là mặc định cho đối chứng nearest. Với TOP_K, nearest chỉ xét candidate subset đó.

Assigned ETA được lưu ở events/config. `verification.events` xuất ETA bias/MAE trên sessions đã arrival và có ETA lúc commit. Đây là lỗi forecast ban đầu, không phải waiting hoặc lỗi rolling inbound ETA. Zero-wait/unfinished denominators được giữ nguyên.

Incremental export giảm tổng event serialization/writing từ việc lặp toàn bộ history thành mỗi event được ghi một lần cho một prefix. Event history vẫn được giữ trong RAM phục vụ audit/tests; status aggregation còn quét history và station/status/IO snapshots vẫn rewrite. Đây chưa phải giới hạn bộ nhớ cho run rất dài. Khi đổi prefix hoặc mất file, exporter khởi tạo lại và ghi history vào file đích mới.

## Regression và bằng chứng

- `SolverSafetyRegression.gaml`: raw prox có thể >1; projection/physical recovery hợp lệ; 30 seeded cycle/branching fixtures; chain 60 EV–61 stations; binary assignment, EV degree một và station floor/ceil trước repair; bound số steps.
- `CoordinationContractTests.gaml`: near=600 m nhưng factor=.25 có ETA 4 phút, far=1.200 m factor=1 có ETA 2 phút; nearest baseline vẫn chọn near. Nominal ablation cho near ETA một phút. Route đã commit giữ chiều dài 2.400 m dù graph có shortcut mới.
- Export regression: repeated flush giữ đúng năm events theo order `request,assigned,en_route,request,cancelled`, một header, ba event-file writes (header + hai delta chunks); không mất hoặc ghi trùng events.
- Python: 100 candidate graphs với cycles/branching/disconnected components kiểm tra EV/station degree; nonfinite/wrong-shape inputs bị reject; ETA MAE/bias được kiểm tra độc lập với waiting. Existing herding 51/49, marginals, long-chain, certificates và repair tests vẫn giữ.

Lệnh kiểm chứng:

```bash
python3 scripts/check_gama.py --suite --gis --phase-a
OPENBLAS_NUM_THREADS=1 .venv/bin/python -m unittest discover -s tests
OPENBLAS_NUM_THREADS=1 .venv/bin/python -m verification.run --phase-a
OPENBLAS_NUM_THREADS=1 .venv/bin/python -m scripts.benchmark_coordination
```

Artifacts trong outputs: `review_full_gama.log`, `review_python.log`, `review_offline.log`, `review_physical_benchmark.log`; `coordination_benchmark.json` giữ cohort/reference/current run prefixes. `_config.csv` có ETA/export model; `_io.csv` có event rows/write calls; `_events.csv` thêm assigned ETA. Lượt compile trong development phát hiện truy cập `perimeter` trực tiếp trên typed road; sửa thành `road.shape.perimeter` và kiểm chứng lại.

Giới hạn hội tụ vẫn giữ: default 20.000 iterations; timeout không là optimum. Kiểm chứng 200.000 ở lượt trước cho burst hội tụ tại 94.340, còn GIS 11 candidates timeout, như COORDINATION_VALIDATION.md. Lần này không thay entropy/PDHG để che giới hạn đó. Fixed-port physical comparisons và mock numerical comparisons được báo riêng; chưa có Robot→EV hoặc network transport thực.

Kết quả chạy lại: **30 roots compile độc lập, 26 runtime checks GAMA và kiểm tra CSV append đều PASS; 23 Python tests OK; 11 snapshots offline PASS; tám paired physical runs PASS**. Gia cố cuối cùng cho station không có cạnh được kiểm tra lại bằng SolverSafetyRegression, AssignmentTests và MathRegression, tất cả PASS (`review_rounding_final.log`). Các physical benchmark giữ kết quả đã báo ở COORDINATION_VALIDATION, bao gồm các trạng thái solver timeout đã công khai. Không suy diễn từ các fixture này thành bảo đảm cho toàn bộ demand đô thị.
