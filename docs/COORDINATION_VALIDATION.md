> Tài liệu lịch sử: mô tả nguồn trước nâng cấp. Đối chiếu tại Git checkpoint `5800181`; hướng dẫn hiện hành ở [GAMA Run Guide](GAMA_RANR_RUN_GUIDE_VI.md).

# Rà soát và triển khai điều phối EV→Station — 08/10/2026

Đã triển khai điều phối trên bản đồ và 11 trạm hiện có, với forecast từ trạng thái fixed-port. GAML chạy mô phỏng, PDHG, GKPS và exact repair; Python chỉ kiểm chứng offline. Robot→EV vẫn `NOT_IMPLEMENTED`, chờ scheduler thật. Báo cáo này cập nhật trạng thái hiện tại; các kết quả mock và thay đổi GUI trước đây được giữ trong VALIDATION.md/PROGRESS.md như lịch sử.

Follow-up mới: [REVIEW_FINDINGS.md](REVIEW_FINDINGS.md) đối chiếu bảy nhận xét, thêm guards cho rounding/projected domain, ETA snapshot/committed path, giữ nearest theo distance và incremental event export. Số lượt kiểm chứng mới nằm ở báo cáo đó; các số liệu dưới đây là bằng chứng của lượt trước.

## Các lỗi và điểm logic đã xử lý

| Vấn đề | Thay đổi và kiểm chứng |
|---|---|
| Nhiều trạm không có đường đến trong graph cũ | Chia source polylines tại shared vertices nằm giữa đường. Không nối crossing thiếu shared vertex. Kiểm tra giữ nguyên tổng chiều dài, hình học GIS và tọa độ trạm; all 110 directed station pairs có path. |
| Điểm tiếp cận có thể nằm trong component đường cô lập | Chọn access node của building/station trên component lớn nhất; giữ station shape/location. Offset trạm ≤300 m được assert và xuất CSV. Đây là giả định access, không thêm đường hay dời trạm. |
| Cắt candidate chỉ còn ba trạm có thể bỏ trạm khả thi ít congestion | ALL_FEASIBLE mặc định cho 11 trạm; TOP_K giữ làm ablation. Candidate vẫn phải có path, tương thích, đủ reserve; fixed-port loại trạm không có hardware phục vụ. |
| Mock capacity không nhìn trạng thái phiên sạc vật lý | Thêm `forecast_fixed_port`: shadow FIFO đọc port power/free count, remaining energy, headroom và pending completion. Không mutate state, không đọc inbound. |
| Workload thay đơn vị khi đổi hiệu suất vật lý | Tách reference_efficiency khỏi charge_efficiency; chuyển capacity theo tỷ lệ power/efficiency tương ứng. Kiểm tra 0,9 kWh = một reference service-minute ngay cả khi đổi physical efficiency. |
| Nguy cơ đếm inbound hai lần | Chỉ repaired integer z commit vào ledger. Arrival remove ledger trước physical enqueue; repeated arrival/cancel/dead cleanup đã có regression. |
| Convenience score trộn phút và mét | Bỏ phép tính và sliders không dùng; giữ travel/congestion objective và waiting từ events. Không gọi F hoặc d*pi là predicted waiting. |
| Python replay không theo ngân sách GAML | Replay đọc iteration budget và tolerances từ batch config. Regression tái hiện một snapshot chỉ chạy 20 vòng; kiểm chứng thêm ngân sách 200.000 vòng. |
| Output của các run ghi đè nhau; checker có thể đọc CSV GIS cũ | Main/benchmark có thư mục riêng. Offline checker tìm event file của isolated GIS run mới nhất. Xuất config, commit timestamp, physical station mapping, đơn vị và input manifest. |

## Năm yêu cầu đã khóa

1. `C,d,H_vir,A,q,d_ref` cùng đơn vị equivalent reference-service minutes. `d=60*E_req/(eta_ref*P_ref)`, E_req giữ cố định từ request. Energy vật lý vẫn kWh. `Q=q/d_ref` dimensionless, không phải physical queue.
2. Inbound chỉ vào H_vir. Forecast chỉ đọc active sessions/waiting queue/free ports. Final-only commit và atomic arrival giữ một request không đồng thời là full inbound và full physical job.
3. Capacity interval h chỉ xử lý backlog có trước arrival cuối bin: `q_h=A_h+max(0,q_prev−C_h)`. Ví dụ C=[50,10], A=[20,0] cho q=[20,10]. Không tích trữ unused port-time.
4. Solver/recovery tối ưu `Travel + F`; entropy chỉ trong relaxed solve. Đánh giá từ events: `Travel=arrival−commit`, `Waiting=start−arrival`, `Total=start−commit`. Có zero-wait sessions, denominator và unfinished/unstarted counts riêng.
5. Cùng waiting queue, active job còn một phút cho C=[3,5]; còn sáu phút cho C=[0,3]. Test kiểm tra forecast không đổi queue/port/session/SOC/events; thêm pending release, mixed-rate FIFO, không có port và inbound lớn không đổi C.

## Rà soát thuật toán

Giữ causal recurrence, backward subgradient với nhánh inactive tại equality, `gamma=d*pi[ETA_bin]`, scaled epigraph PDHG, log-domain entropy prox, Frobenius step và boxed Lagrangian LB. Không đổi solver để né lỗi. Dừng cần raw feasibility ≤1e−6, dual-copy disagreement ≤1e−6 và certified relative gap ≤1e−7. Criterion đối chiếu centralized reference là relative objective gap ≤1e−5; conditioned positive-entropy fixtures kiểm tra x error ≤1e−3.

Entropy có dấu đúng: `J0*−theta*sum(log K) ≤ Jtheta* ≤ J0*`. LB được tính từ dual hợp lệ; approximate primal không phải certificate. UB là integer assignment trên cùng snapshot. GKPS bảo toàn marginals trước repair và EV degree một; không bảo đảm heterogeneous workload cân bằng chính xác. Proxy chỉ xếp relocation; accept cần exact improvement >1e−6 phút. Quét phần còn lại nếu top-5 không cải thiện, rồi mới kết luận one-exchange local optimum trong tolerance.

Timeout không phải convergence. Assignment vẫn được chiếu simplex, recovery và kiểm tra certificate/local optimum. Driver chỉ điều khiển synchronous barriers; local station blocks tính primal/dual updates. Message/byte counters là trao đổi logic in-process, chưa có network transport/delay/failure.

## Benchmark vật lý có cùng demand

Bốn cặp policy chạy với seed 42, bước một giây, cùng request trace/E_req/initial service state trong mỗi cặp. Ba cặp dùng graph synthetic; cặp cuối dùng GIS nguồn không đổi, đủ 11 candidates, các cổng cs1 bận 30 phút. Các physical blockers bị loại khỏi cohort đánh giá request mới. Các kết quả sau dùng giới hạn solver mặc định 20.000 vòng.

| Kịch bản | Policy | Mean Travel | Mean Waiting | Mean Travel+Waiting |
|---|---|---:|---:|---:|
| Trạm gần bận, một request | nearest | 0,95 | 29,05 | 30,00 |
| Trạm gần bận, một request | proposed | 1,97 | 0,00 | 1,97 |
| Burst bốn requests | nearest | 1,02 | 73,98 | 75,00 |
| Burst bốn requests | proposed | 1,50 | 29,48 | 30,98 |
| Tải nhẹ, một request | nearest | 0,95 | 0,00 | 0,95 |
| Tải nhẹ, một request | proposed | 0,95 | 0,00 | 0,95 |
| GIS: cs1 bận, một request | nearest | 0,00 | 30,00 | 30,00 |
| GIS: cs1 bận, một request | proposed | 2,53 | 0,00 | 2,53 |

Đơn vị bảng: phút. Tất cả requests trong cohort hoàn thành; không cancelled/stranded/unfinished. P95 Waiting trong burst giảm từ 114,42 xuống 54,62 phút. Tải nhẹ là negative control: hai policy cùng kết quả. Input checksums trước/sau benchmark giống nhau.

Hai proposed snapshots near_busy/light hội tụ ở ngân sách mặc định. Burst và GIS chạm 20.000 vòng, có relative reference gaps lần lượt khoảng 3,24e−4 và 2,53e−3; các quyết định integer khả thi và kiểm tra local optimum/LB/UB vẫn đạt. Không gọi hai relaxed iterates đó là optimum. Trong tiny enumeration/MILP, UB sau repair của cả bốn proposed cases bằng integer optimum của surrogate; đây không phải guarantee chung cho bài toán integer hoặc actual waiting.

Artifact đầy đủ: `outputs/coordination_benchmark.json` ghi cohort, mean/P95, config, references, iterations, certificates, logical messages/bytes và directory mỗi run. `outputs/coordination_extended_solver.json` ghi kiểm chứng ngân sách lớn riêng, không thay thế kết quả mặc định.

Kiểm chứng thêm với 200.000 vòng, giữ nguyên equations/initialization/tolerances: burst hội tụ sau **94.340** vòng, relative reference gap **4,34e−9**, x error so với Python bằng 0. Case GIS 11 candidates vẫn **timeout ở 200.000**, raw residual **4,11e−5**, relative reference gap **2,23e−4**, x error với Python khoảng 1,01e−17. Kết quả này xác nhận hai implementations khớp nhưng cho thấy ngân sách hiện tại chưa đủ cho tolerance trên fixture GIS đó. Báo cáo ghi `all_converged=false`; không đổi default budget, không tuyên bố relaxed optimum. Cần cải thiện điều kiện số/solver runtime ở một đợt thuật toán được kiểm chứng riêng trước kết luận scalability/near-optimality cho mọi GIS batch.

Lượt rà soát cuối: **28 standalone GAML compilations**, **23 runtime checks** của suite/GIS/Phase A cộng **một Run me smoke check** với fixed_port/ALL_FEASIBLE/Start hour=6 đều PASS. **19 Python tests** đạt, gồm regression cho exported solver budget và event metrics. **11 mock snapshots** được tái tạo độc lập; bốn proposed fixed-port snapshots và hai extended snapshots được đối chiếu riêng. Tám physical policy runs đạt; hai Phase A lớn và các timeout nêu trên vẫn được báo không hội tụ. Các checks này kiểm tra tính đúng của outputs/certificates/replay, không biến timeout thành convergence.

## Chạy và kiểm chứng

Trong GAMA: đóng experiment cũ, mở `models/main.gaml` → Run me; chọn `proposed`, `fixed_port`, `ALL_FEASIBLE`. Dùng step=1 cho waiting benchmark. Để quan sát sớm, chọn Start hour=6 hoặc Small GIS scenario rồi restart. Monitor Results directory và console RUN_OUTPUT_PREFIX chỉ đúng thư mục output. `00:46:00` của native GAMA vẫn là 46 phút; không đổi đơn vị của clock để làm chart có hoạt động.

```bash
python3 scripts/check_gama.py --suite --gis --phase-a
OPENBLAS_NUM_THREADS=1 .venv/bin/python -m unittest discover -s tests
OPENBLAS_NUM_THREADS=1 .venv/bin/python -m verification.run --phase-a
OPENBLAS_NUM_THREADS=1 .venv/bin/python -m scripts.benchmark_coordination
OPENBLAS_NUM_THREADS=1 .venv/bin/python -m scripts.verify_extended_coordination
```

Logs: `coordination_final_gama_validation.log`, `coordination_gui_smoke_validation.log`, `coordination_python_validation.log`, `coordination_offline_validation.log`, `coordination_benchmark_validation.log`, `coordination_extended_solver_validation.log` trong outputs. Các compile checks trực tiếp của main/ChargingService ở `coordination_main_diagnostics.log`/`coordination_service_diagnostics.log` không có cast/shadow/type diagnostics. Python không chạy trong mô phỏng. Manifest được tạo offline và sao chép khi main khởi tạo; tạo lại bằng `python3 -m scripts.input_manifest` nếu đổi GIS. Để replay extended snapshots đã xuất mà không chạy lại physics, dùng `scripts.verify_extended_coordination --snapshots <burst_prefix> <gis_prefix>` qua Python module như các lệnh trên.

## Giới hạn còn lại

- Đây là synthetic demand với fixed-port, chưa phải dữ liệu traffic Nha Trang đã hiệu chỉnh hay bằng chứng lợi ích robot-aware.
- ETA hiện dùng remaining committed route/current speed factors; nominal speed giữ làm ablation. Chưa dự báo đầy đủ native driving acceleration/congestion tương lai; actual travel được đo độc lập.
- Đường hiện được giả định hai chiều. Graph chỉ nối shared source vertices; access là nearest largest-component node, không mô phỏng đường vào từ node đến station shape. Giả định và access distance được xuất.
- Interval fluid congestion bỏ đặc tính job không chia nhỏ của từng port. F không bằng actual waiting; finite horizon có terminal backlog được xuất.
- Step=60 là chạy thử nhanh; step=3.600 không phù hợp kết luận waiting. Benchmark vật lý hiện dùng một giây.
- Chưa chạy/hiệu chỉnh toàn bộ thí nghiệm đô thị 48 giờ với 24 giờ warm-up hoặc đánh giá city-scale/network thực. Scalability hiện là các micro-batch đã ghi trong Phase A.
- Mục tiêu là giảm travel/congestion, không buộc chia tải đều cho mọi trạm. Sau khi sửa reachability, một trạm vẫn có thể ít hoặc không có requests nếu chi phí hoặc vị trí không thuận lợi trong demand cụ thể.
- Mock luôn giữ nhãn forecast-mismatch khi so với service fixed-port. Grid energy được theo dõi; objective hiện không có thành phần tối ưu nguồn năng lượng riêng.
- Robot adapter/shadow robot forecast và các thử nghiệm SOC/recharge/failure đợi scheduler người dùng cung cấp; không tự tạo scheduler thay thế.
