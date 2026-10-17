> Tài liệu lịch sử. Mô hình hiện hành: persistent-soc-activity-6 / intent-service-5; xem [hồ sơ khoa học](GAMA_RANR_SCIENTIFIC_CHANGES_VI.md).

> Tài liệu lịch sử: mô tả nguồn trước nâng cấp. Đối chiếu tại Git checkpoint `5800181`; hướng dẫn hiện hành ở [GAMA Run Guide](GAMA_RANR_RUN_GUIDE_VI.md).

# Kế hoạch chuyển sang Distributed Observation-Driven Charging Recommendation

## 1. Mục tiêu và kiến trúc đã chốt

Chuyển project hiện tại từ **phân công EV bắt buộc đến trạm** sang **khuyến nghị trạm, EV tự quyết định**, giữ nguyên bản đồ, vị trí và phần cứng của 11 trạm.

Phương pháp chính không dùng trọng số kinh tế khi chưa có dữ liệu hiệu chỉnh. EV lựa chọn khuyến nghị bằng **Pareto filtering và minimax normalized regret**, xét:

- Thời gian di chuyển.
- Quãng đường.
- Năng lượng di chuyển.
- Thời gian chờ dự báo tại ETA.

Triển khai ba mức thông tin:

| Phương pháp | Thông tin dự báo |
|---|---|
| **B3 — Physical-only** | Trạng thái cổng, phiên đang sạc, hàng đợi thực |
| **B4 — Local observation-driven** | B3 + forecast từ arrivals/workload đã quan sát tại trạm |
| **B4-N — Neighbor-assisted** | B4 + hiệu chỉnh học từ forecast tổng hợp của láng giềng |

**B4 là phương pháp chính.** B4-N chỉ được xem là cải tiến nếu kết quả ngoài mẫu chứng minh được lợi ích.

Giữ riêng chế độ **IDEAL_COORDINATED_ASSIGNMENT** chứa PDHG → GKPS → exact repair → hard assignment. Không dùng kết quả hoặc chứng nhận tối ưu của chế độ này để chứng nhận recommendation.

Luồng mới:

```text
EV phát sinh nhu cầu
→ lọc trạm khả thi
→ tính route, ETA, distance, energy
→ hỏi thông tin dự báo từ từng trạm
→ station-local waiting prediction
→ Pareto filtering
→ minimax normalized regret
→ recommendation
→ EVChoice
→ di chuyển thực tế
→ actual arrival
→ physical FIFO charging
→ đo kết quả và cập nhật lịch sử local
```

Không có central training server hoặc world-level recommendation optimizer. GAMA world chỉ quản lý thời gian, cấu hình, vận chuyển thông điệp logic và đánh giá offline.

---

## 2. Audit và bảo toàn nền hiện tại

Trước khi refactor, lập baseline có thể chạy lại.

### 2.1. Rà soát dependency

Đánh dấu mọi chỗ đang mặc định:

```text
recommendation = assignment = destination = inbound
```

Đặc biệt kiểm tra:

- `coordinate_batch()` và `commit_assignment()`.
- Việc tạo request và chuyển trạng thái EV.
- Xây candidate, tính đường, ETA và energy.
- Ghi inbound khi solver trả nghiệm.
- Arrival, cancellation, stranded và cleanup.
- Các metric đang gọi surrogate là waiting.
- Các experiment GUI/headless có cấu hình backend khác nhau.

Phân loại từng thành phần: giữ nguyên, dùng chung, chỉ thuộc benchmark, hoặc cần thay đổi.

### 2.2. Khóa baseline

Lưu cấu hình, checksum dữ liệu, phiên bản runtime và kết quả kiểm thử trước thay đổi.

Giữ nguyên:

- GIS, road graph và station access points.
- Tọa độ và số cổng của 11 trạm.
- Hình ảnh xe, màu bản đồ và display.
- Fixed-port FIFO và energy integration.
- Các kiểm thử causal capacity, PDHG, rounding và repair.

Kiểm tra riêng các thay đổi gần đây về `target_soc` và `d_nm`; không coi kết quả kiểm thử cũ là bằng chứng cho chức năng mới.

**Điều kiện hoàn thành:** có baseline compile/runtime, danh sách dependency và các lỗi hiện hữu được phân biệt với lỗi do refactor.

---

## 3. Hợp đồng dữ liệu và vòng đời mới

### 3.1. Tách bốn loại dữ liệu

| Loại | Ý nghĩa | Có làm thay đổi physical queue? |
|---|---|---|
| Recommendation | Hệ thống đề xuất một trạm | Không |
| Choice | EV quyết định hành động | Không |
| Intention | EV chủ động thông báo ý định | Không |
| Actual arrival | EV thực sự đến đúng trạm | Có |

V1 lưu intention để kiểm tra và phân tích nhưng **không đưa intention vào waiting forecast**. Vì B4 đã học từ actual arrivals, cách này tránh cộng đôi arrivals forecast và intention.

Hard inbound hiện tại chỉ tồn tại trong ideal assignment benchmark.

### 3.2. Recommendation result

Mỗi kết quả lưu:

```text
request_id, recommendation_version
issued_at, valid_snapshot_time
recommended_station
candidate stations và route references
predicted travel time, distance, energy, ETA
predicted waiting
forecast method và fallback reason
station snapshot timestamp và received_at
Pareto membership
normalized regrets, maximum regret
ranked alternatives
```

Không dùng một trường `generalized_cost` không rõ đơn vị để chứa lẫn tiền và regret. Dùng:

- `recommendation_score`: không đơn vị.
- `score_method`: minimax, monetary hoặc weighted-sum.
- `monetary_cost_vnd`: chỉ khi chạy đối chứng có đủ hệ số.

### 3.3. EVChoice

Ba chế độ:

1. **FOLLOW_RECOMMENDATION:** giả định có kiểm soát để benchmark.
2. **SELF_INTERESTED_CHOICE:** EV dùng cấu hình sở thích cá nhân xác định trước.
3. **EXOGENOUS_CHOICE_TRACE:** đọc lựa chọn từ trace được cung cấp.

SELF_INTERESTED mặc định dùng cùng tiêu chí với engine nên có thể chọn giống recommendation. Chỉ tạo khác biệt khi fixture hoặc dữ liệu cấu hình cung cấp sở thích khác; không tự sinh phân bố hành vi.

Cho phép EV không chọn trạm hoặc trì hoãn. Không có trace thì chế độ trace dừng với thông báo thiếu dữ liệu, không tạo trace giả.

Chỉ EVChoice mới được yêu cầu mobility đổi destination. Engine recommendation không gọi hard commit.

### 3.4. Arrival và cleanup

- Arrival kiểm tra trạm EV thực sự đến.
- Xử lý arrival một lần cho mỗi session.
- Xóa intention tương ứng trước hoặc cùng thao tác enqueue.
- Tại arrival, tính lại nhu cầu sạc từ SOC thực tế đến target.
- Cancellation, stranded và vehicle removal cleanup đúng state.
- Thông tin lựa chọn chỉ có trong evaluator không được tự động truyền ngược về engine.

---

## 4. Formulation lựa chọn trạm

### 4.1. Candidate và route

Mặc định `ALL_FEASIBLE`.

Với cùng một route \(r_{nm}\), tính:

\[
T_{nm},\quad D_{nm},\quad E_{nm}.
\]

Giữ mô hình hiện tại:

\[
E_{nm}=c_{\mathrm{kWh/km}}D_{nm}.
\]

Điều kiện năng lượng:

\[
E_n^{current}-E_{nm}\ge E_n^{reserve}.
\]

Candidate còn phải có route, tương thích và phần cứng phục vụ.

Giữ routing policy hiện tại trong lần refactor này. Tính ETA theo congestion trên chính route được đánh giá; khi EV chọn, mobility dùng route đó hoặc ghi rõ sự kiện replan và cập nhật prediction. Không gọi route hiện tại là fastest path nếu chưa triển khai và kiểm chứng điều đó.

### 4.2. Nhu cầu sạc phụ thuộc trạm

\[
E_{nm}^{arrival}=E_n^{current}-E_{nm},
\]

\[
E_{nm}^{req}=\max(0,E_n^{target}-E_{nm}^{arrival}),
\]

\[
d_{nm}=
\frac{60E_{nm}^{req}}{\eta_{ref}P_{ref}}.
\]

`E_req` dùng kWh. `d_nm`, capacity và backlog của benchmark dùng equivalent reference service-minutes. Không trộn hai đơn vị.

### 4.3. Pareto filtering

Đặt:

\[
f_{nm}=(T_{nm},D_{nm},E_{nm},W_{nm}).
\]

Trạm \(a\) dominates \(b\) nếu không tệ hơn ở mọi tiêu chí và tốt hơn ở ít nhất một tiêu chí.

Dùng tolerance số học theo từng tiêu chí; không dùng tolerance lớn như một preference ẩn. Lưu cả tập feasible ban đầu và Pareto set để giải thích quyết định.

### 4.4. Normalized regret

Tính min/max trên **toàn bộ tập feasible trước Pareto filtering**:

\[
l_{nj}=\min_{m\in M_n}f_{nmj},\qquad
u_{nj}=\max_{m\in M_n}f_{nmj}.
\]

\[
r_{nmj}=
\begin{cases}
0,&u_{nj}-l_{nj}\le\epsilon_j,\\
\dfrac{f_{nmj}-l_{nj}}{u_{nj}-l_{nj}},&\text{ngược lại}.
\end{cases}
\]

Score:

\[
R_{nm}=\max_j r_{nmj}.
\]

Chọn trong Pareto set theo thứ tự:

1. \(R_{nm}\) nhỏ nhất.
2. \(T_{nm}+W_{nm}\) nhỏ nhất.
3. Station ID nhỏ nhất để tái lập.

Không cộng các regret để phá hòa.

Với \(E=cD\), normalized regret của Energy và Distance giống nhau. Phép maximum không tăng trọng số vì tiêu chí bị lặp. Phải có unit test chứng minh việc thêm/bỏ Energy trong trường hợp này không đổi kết quả.

### 4.5. Ví dụ nghiệm thu

Giả sử ba trạm đều khả thi:

| Trạm | Travel phút | Distance km | Energy kWh | Waiting phút |
|---|---:|---:|---:|---:|
| A | 20 | 3 | 0,6 | 10 |
| B | 10 | 9 | 1,8 | 3 |
| C | 14 | 6 | 1,2 | 6 |

Maximum regret lần lượt:

\[
R_A=1,\qquad R_B=1,\qquad R_C=0.5.
\]

Thuật toán chọn C. Đây là lựa chọn cân bằng theo quy tắc minimax, **không phải chứng minh C có tiền điện hoặc tổng thời gian thấp nhất**.

Thêm một trạm dominated nhưng có giá trị cực đại lớn có thể thay đổi chuẩn hóa. Phải kiểm tra và báo cáo tính nhạy này, không âm thầm đổi sang chuẩn hóa chỉ trên Pareto set.

---

## 5. Dự báo arrivals local — B4

### 5.1. Dữ liệu được phép dùng

Mỗi trạm lưu các arrival sessions đã xảy ra:

```text
arrival timestamp
requested energy tại arrival
equivalent workload
service compatibility cần cho shadow
```

Không dùng completion trong tương lai để suy ngược workload cho forecast ở quá khứ.

Forecast tại \(t\) chỉ dùng dữ liệu và thông điệp đã được nhận trước \(t\).

### 5.2. Baseline moving average

Dùng bin 5 phút. Với workload quan sát trong bin \(b\):

\[
Y_{mb}=\sum_{n:\,arrival(n)\in b}d_n^{arrival}.
\]

Baseline dự báo mỗi bin tương lai:

\[
\widehat Y_{m,b+h}
=\frac{1}{L}\sum_{i=1}^{L}Y_{m,b-i}.
\]

Mặc định phát triển \(L=12\), tương đương 60 phút. Tính cả bin không có arrival.

EWMA là đối chứng:

\[
\mu_{mb}=(1-\alpha)\mu_{m,b-1}+\alpha Y_{mb}.
\]

Các lựa chọn cửa sổ hoặc \(\alpha\) là tham số forecast cần sensitivity, không phải xác suất tuân thủ.

### 5.3. Cold-start và đánh giá

Mặc định chỉ bật replay forecast sau khi có:

- Ít nhất 24 bin hoàn tất.
- Ít nhất 20 arrival sessions.
- Đủ đoạn lịch sử hoàn chỉnh cho horizon cần dự báo.

Nếu chưa đạt, B4 = B3 và ghi nguyên nhân.

Thứ tự prequential:

```text
phát hành forecast
→ lưu forecast cùng feature snapshot
→ quan sát bin thực tế
→ tính sai số
→ cập nhật mô hình
```

Không tune tham số bằng chính đoạn thời gian đang báo cáo kết quả kiểm tra.

---

## 6. Giao tiếp và B4-N

### 6.1. Graph cố định

Tạo graph từ travel time giữa các station access points trên road network ở cấu hình tham chiếu đầu experiment.

Mặc định mỗi trạm chọn tối đa ba trạm reachable có travel time nhỏ nhất; hòa theo station ID. Đối xứng hóa các cạnh và giữ graph cố định suốt run. Không tự ép nối các road component không reachable.

Graph thông tin không hạn chế candidate của EV: candidate vẫn `ALL_FEASIBLE`.

### 6.2. Payload

Trao đổi mỗi bin 5 phút:

```text
sender, sequence, issued_at
bin edges và đơn vị
residual capacity vector
observed-arrival workload forecast
forecast method, history coverage
uncertainty nếu đã có cách ước lượng
```

Receiver lưu thêm `received_at`. Không gửi raw queue, EV identity hoặc robot state.

Đo message count, bytes theo payload serialized, snapshot age và thời gian trễ mô phỏng. Mặc định logical delivery không có trễ mạng; thêm ablation trễ một và ba bin. Không gọi đây là triển khai network thật.

### 6.3. Online correction

Mỗi trạm học hiệu chỉnh riêng theo horizon:

\[
\widehat Y^{N}_{m,b+h}
=
\max\left(0,\widehat Y^{local}_{m,b+h}
+w_{mh}^{\mathsf T}\phi_{mbh}\right).
\]

Feature gồm forecast láng giềng đã nhận, tuổi snapshot và cờ thiếu dữ liệu. Không lấy state hiện tại trực tiếp từ agent láng giềng để bù snapshot cũ.

Target học:

\[
Y_{m,b+h}-\widehat Y^{local}_{m,b+h}.
\]

Dùng ridge regression cập nhật online từ sufficient statistics, chuẩn hóa feature bằng thống kê quá khứ. Chỉ cập nhật sau khi nhãn tương ứng đã quan sát.

Khởi tạo correction bằng 0. Chưa đủ \(\max(50,5p)\) mẫu có nhãn, với \(p\) là số feature, thì B4-N = B4.

Regularization kiểm tra trên tập phát triển rồi khóa trước test. Không đặt hệ số tương quan hoặc dịch chuyển demand bằng tay.

Residual capacity được trao đổi để mô tả service snapshot và đo overhead; không tuyên bố nó cải thiện arrival forecast nếu chưa có ablation đưa nó vào mô hình.

---

## 7. Forecast workload thành individual waiting

### 7.1. B3 physical-only

Shadow simulation sao chép:

- Cổng và công suất.
- Phiên đang sạc cùng remaining energy.
- FIFO queue thực.
- Quy tắc cấp cổng và độ phân giải thời gian của physical backend.

Chèn một probe EV tại ETA và lấy:

\[
W_{nm}^{pred}=t_{start}^{shadow}-ETA_{nm}.
\]

Không mutate physical agents hoặc tiêu thụ RNG của mobility/service.

### 7.2. Replay cho B4/B4-N

Archive các cửa sổ lịch sử đã hoàn tất, chứa arrival offsets và năng lượng từng phiên.

Với horizon của truy vấn:

1. Lấy các đoạn quá khứ đủ dài.
2. Tính vector workload theo bin của từng đoạn.
3. So sánh với vector forecast bằng khoảng cách đã chuẩn hóa từ dữ liệu quá khứ.
4. Chọn tối đa 20 đoạn gần nhất.
5. Dịch thời gian đoạn đó về thời điểm forecast.
6. Giữ nguyên số phiên, offset và năng lượng từng phiên.
7. Chạy shadow cùng probe trên từng kịch bản.

Dự báo waiting là trung bình waiting qua các kịch bản. Báo thêm độ phân tán giữa kịch bản nhưng không gọi đó là confidence interval đã hiệu chỉnh.

Không co giãn năng lượng từng phiên để ép tổng workload khớp forecast. Ghi riêng độ lệch giữa workload replay và forecast; nếu lịch sử không đại diện được burst mới, phải thấy được hạn chế này trong output.

Các đoạn kết thúc trước thời điểm forecast mới được sử dụng. Việc chọn scenario deterministic giúp không ảnh hưởng RNG vật lý.

### 7.3. Fallback

- Thiếu lịch sử: physical-only.
- Vượt giới hạn số scenario: dùng subset deterministic, ghi số scenario.
- Fluid approximation: chế độ đối chứng riêng; chỉ dùng làm computational fallback khi bật rõ trong config, ghi mỗi lần sử dụng.

Không âm thầm trộn fluid waiting với replay waiting trong cùng báo cáo.

---

## 8. LIVE, LIMITED và quyết định đồng thời

**LIVE:** EV hỏi candidate stations và nhận prediction từ snapshot hiện hành.

**LIMITED:** chỉ dùng packet đã có trong cache, lưu tuổi thông tin. Không đọc queue mới để “làm mới” kết quả cũ. Nếu packet không phủ ETA hoặc không có waiting prediction hợp lệ, đánh dấu unavailable; không gán waiting bằng 0.

Nếu không còn candidate có đủ dữ liệu để xếp hạng, engine trả `recommendation_unavailable`; EVChoice có thể trì hoãn hoặc hành động theo cấu hình riêng.

Để tránh lợi thế giả do thứ tự agent:

```text
chốt request và snapshot tại thời điểm t
→ tạo toàn bộ recommendation của thời điểm t
→ xử lý EVChoice
→ áp dụng hành vi vật lý
```

Không ghi lựa chọn của EV trước vào forecast của EV sau trong cùng đợt khi thông tin đó chưa được truyền.

Recommendation pressure chỉ là metric quan sát được. V1 không chuyển pressure thành arrivals hoặc waiting bằng hệ số tự đặt.

---

## 9. Phạm vi chỉnh sửa mã

| Thành phần | Thay đổi |
|---|---|
| `Coordination.gaml` | Tách đường chạy ideal assignment và recommendation; giữ hard commit chỉ trong benchmark |
| `ChargingService.gaml` | Thêm station-local history, shadow waiting query, intention logging; giữ physical FIFO |
| `Mobility.gaml` | Chỉ nhận destination từ EVChoice; thống nhất route prediction với route thực thi |
| `ConvexAssignment.gaml` | Giữ solver; chỉ sửa lỗi có test tái hiện |
| `CoordinationBenchmark.gaml` | Giữ fixture cũ, thêm wrapper đối chiếu với recommendation |
| `main.gaml` | Thêm runtime mode, forecast mode, information mode và EVChoice |
| Module recommendation mới | Chứa Pareto, regret, recommendation result và EVChoice interface |
| Module station forecast mới | Chứa online forecast, replay và neighbor correction |
| Python verification | Reference độc lập cho ranking, forecast, replay và metric |

Không nhét toàn bộ forecasting vào solver cũ; chỉ thêm hai module có trách nhiệm rõ.

Chuẩn hóa output schema có version. Sửa các trường hiện mang tên travel nhưng thực tế chứa combined cost. Đo distance/energy/travel trên cùng đoạn **từ khi chọn destination đến actual arrival**, tách phần di chuyển trước lựa chọn.

---

## 10. Kiểm thử và gate triển khai

| Gate | Deliverable | Điều kiện qua |
|---|---|---|
| **0** | Audit và baseline | Compile, runtime logs và input manifest |
| **1** | Formulation + Python reference | Ví dụ số, Pareto/regret và forecast tests đạt trước khi port |
| **2** | Recommendation/Choice separation | Recommendation không đổi destination, queue hoặc inbound |
| **3** | B3 physical waiting | Khớp independent discrete-event reference trên fixture xác định |
| **4** | B4 local forecast + replay | Không future leakage; cold-start, replay và prequential đúng |
| **5** | B4-N + communication | Timestamp, missing/stale messages và online learning đúng |
| **6** | GAMA integration | GUI/headless và 11-station GIS smoke chạy được |
| **7** | Experiments + documentation | Kết quả tái lập, giới hạn và PASS/FAIL có log |

Các nhóm regression bắt buộc:

- EV chọn khác recommendation; không đến không tạo phantom workload.
- Arrival trùng, đến trạm khác, hủy và stranded.
- Một candidate, zero-range criterion, Pareto dominance và hòa điểm.
- Duplicated Distance/Energy không đổi minimax.
- Dominated outlier và thay đổi candidate set làm đổi chuẩn hóa.
- Route T/D/E nhất quán, reserve feasibility, target SOC và `d_nm`.
- Cùng queue length nhưng active sessions khác → waiting/capacity khác.
- Heterogeneous ports, FIFO, simultaneous arrivals và probe tại ranh giới thời gian.
- Replay chỉ dùng historical completed windows và không đổi session sizes.
- Forecast-before-observe-before-update; feature timestamp không vượt thời điểm phát hành.
- Missing/stale neighbor information; correction cold-start bằng 0.
- B4-N tắt correction cho kết quả B4.
- Shadow không đổi physical state hoặc RNG streams.
- Existing PDHG/GKPS/repair và LB/UB regression.
- Metric chưa hoàn thành không bị biến thành waiting bằng 0.

Với fixture không có arrivals bất ngờ, waiting shadow phải khớp reference trong độ phân giải một bước vật lý. Với forecast ngoài mẫu, báo sai số thay vì đặt tiêu chí “luôn tốt hơn B3”.

---

## 11. Thí nghiệm và phương pháp đối chứng

Các policy:

- B1: nearest road distance.
- B2: minimum predicted travel time.
- B3: physical-only + Pareto/minimax.
- B4: local observed-arrival forecast + Pareto/minimax.
- B4-N: neighbor correction + Pareto/minimax.
- Ideal coordinated assignment: benchmark riêng.

Giữ Monetary Weighted Cost và Normalized Weighted Sum làm đối chứng cấu hình được. Khi chưa được cung cấp hệ số, đánh dấu `NOT_CONFIGURED`, không tự đặt bộ trọng số mặc định.

Thí nghiệm chính dùng cùng demand generation, EV initial states, traffic, routing, physical backend và EVChoice. Arrivals có thể khác do policy; đây là kết quả cần đo, không ép giống nhau.

Dùng hai lớp đánh giá:

1. **Forecast offline/prequential trên cùng trace quá khứ** để so sánh predictor công bằng.
2. **Closed-loop GAMA** để đo tác động recommendation lên arrivals, queue và waiting.

Kịch bản:

- Light load và homogeneous stations.
- Cùng physical queue, khác future availability.
- Burst demand và nhiều EV quyết định đồng thời.
- Distribution shift.
- Cold-start và các mức history coverage.
- Snapshot cũ và communication delay.
- Intention có/không nhưng chưa dùng trong predictor.
- EVChoice đồng nhất và sở thích cá nhân xác định trước.
- ALL_FEASIBLE so với TOP_K.
- Số replay scenarios: 5, 10, 20, 50.
- Moving-average window: 6, 12, 24 bin.
- Local-only so với neighbor correction.
- Graph degree 1, 3, 5; candidate-overlap là ablation riêng.
- Sensitivity của min/max normalization và Pareto ranking.

Mặc định chạy 10 seeds cho experiment chính, 48 giờ mỗi run; báo riêng cold-start, 24 giờ đầu và 24 giờ sau. Stress test dùng synthetic network riêng, không thay GIS chính để giả tạo khả năng mở rộng.

---

## 12. Metrics, bàn giao và giới hạn

Mỗi run xuất:

- Config, seed, input checksums và schema version.
- Recommendation records và candidate scores.
- Choice/arrival/session events.
- Forecast đã phát hành và outcome khi quan sát.
- Replay scenario coverage và fallback.
- Communication messages, bytes, age và latency.
- Mean/P95 actual travel, waiting và travel + waiting.
- Actual distance, energy, throughput, queue peak.
- Deferred, no-choice, cancelled, stranded và unfinished.
- Forecast MAE/RMSE, waiting MAE/RMSE và P95 absolute error.
- Recommendation concentration và ranking stability.
- Runtime theo forecast, shadow và recommendation.

Regret là score theo tập lựa chọn tại thời điểm ra quyết định, không phải chi phí vật lý có thể cộng tùy ý giữa mọi request. Báo score cùng các metric vật lý, không chỉ một số tổng hợp.

Bàn giao cuối:

1. Mã GAML và Python reference.
2. Formulation và ví dụ số đã kiểm thử.
3. Danh sách thay đổi theo module/action.
4. Before/after regression và benchmark.
5. Báo cáo PASS/FAIL có log và đường dẫn.
6. Cập nhật tài liệu thuật toán, service interface và implementation plan.
7. Danh sách phần chưa được kiểm chứng.

Giới hạn phải ghi rõ: dữ liệu synthetic; consumption hiện tỷ lệ với distance; dự báo không kiểm soát lựa chọn người lái; replay có thể thiếu các trạng thái demand mới; giao tiếp là logical simulation; chưa có Robot→EV; recommendation không được chứng nhận tối ưu global actual waiting.
# Đánh giá kế hoạch Distributed Observation-Driven Charging Recommendation

Tôi đã rà soát bản kế hoạch mới. **Hướng kiến trúc phù hợp với yêu cầu của anh và có thể bắt đầu triển khai, nhưng tôi chưa khuyến nghị coding agent thực hiện toàn bộ 7 gate ngay.** Có một số vấn đề cần sửa trước, chủ yếu liên quan đến dự báo waiting, hiệu quả trao đổi liên trạm và tính đúng đắn của các thí nghiệm.

## 1. Những thành phần nên giữ

Kế hoạch đã giải quyết được các điểm bất hợp lý của mô hình hard assignment trước đây:

| Thành phần | Đánh giá |
|---|---|
| Recommendation tách khỏi EVChoice | Đúng, cần giữ |
| Không mặc định EV tuân theo khuyến nghị | Đúng |
| Không có server điều phối trung tâm | Phù hợp với phạm vi |
| Giữ nguyên GIS và 11 trạm | Đúng |
| B3: Physical-only | Baseline cần thiết |
| B4: Dự báo từ arrivals thực tế | Hướng chính hợp lý |
| B4-N: Hiệu chỉnh từ thông tin láng giềng | Có tiềm năng, cần chứng minh |
| Pareto + Minimax Regret | Hợp lý làm quy tắc lựa chọn ban đầu |
| Historical Replay | Hợp lý để mô phỏng waiting rời rạc |
| Giữ PDHG/GKPS làm benchmark lý tưởng | Đúng, không nên xóa |

Đặc biệt, việc tách `recommendation`, `choice`, `intention` và `actual arrival` là thay đổi cần thiết. Kế hoạch cũng đã quy định intention không tham gia waiting forecast trong V1, nhờ đó tránh một nguồn đếm trùng nhu cầu. Pasted text

Tuy nhiên, **điểm còn thiếu không nằm ở công thức lựa chọn trạm, mà ở cách bảo đảm forecast thực sự có ích đối với quyết định của nhiều EV**.

## 2. Sáu vấn đề cần sửa trước khi triển khai

| Mức độ | Vấn đề | Đề xuất |
|---|---|---|
| **P0** | Historical Replay có thể không phản ánh forecast workload mới | Kiểm tra mức khớp giữa kịch bản replay và forecast trước khi sử dụng waiting |
| **P0** | EVChoice chưa mô tả được mức không chắc chắn của người lái trong thực tế | Tách rõ các giả định hành vi và giới hạn kết luận |
| **P0** | B4-N có thể cải thiện arrival MAE nhưng làm waiting prediction tệ hơn | Chọn và đánh giá correction theo cả chất lượng waiting |
| **P1** | Dự báo arrivals có thể thay đổi khi chính recommendation policy thay đổi | Kiểm chứng cả offline và closed-loop |
| **P1** | Minimax normalization nhạy với trạm ứng viên không liên quan | Bổ sung đối chứng với chuẩn hóa trên Pareto set hoặc mốc cố định |
| **P1** | Historical Replay có thể quá nặng trong GAMA | Benchmark runtime, cache dự báo và quy định fallback |

### Vấn đề 1 — Forecast workload không khớp Historical Replay

Kế hoạch hiện tại lấy tối đa 20 cửa sổ lịch sử gần forecast nhất, giữ nguyên các phiên sạc rồi tính trung bình waiting. Pasted text

Cách này có một hạn chế.

Giả sử:

- B4 dự báo nhu cầu tương lai là 100 service-minutes.
- B4-N dự báo 180 service-minutes.
- Toàn bộ cửa sổ lịch sử chỉ chứa 80–110 service-minutes.

Khi đó, cả hai phương pháp có thể lựa chọn gần như cùng một nhóm kịch bản.

Hệ quả:

\[
\widehat W^{B4}\approx\widehat W^{B4-N}
\]

dù forecast workload khác nhau đáng kể.

Như vậy, **thông tin cải thiện từ Neighbor Correction không được chuyển thành waiting prediction một cách hiệu quả**.

Tôi đề xuất thêm bước kiểm tra độ đại diện:

\[
e_s=
\left\|
L_s^{historical}
-
\widehat L^{forecast}
\right\|
\]

Chỉ sử dụng replay khi có những kịch bản đủ tương đồng với forecast theo tiêu chí đã được hiệu chỉnh.

Nếu không có lịch sử phù hợp, phải đánh dấu *out-of-distribution* và chuyển sang phương pháp dự phòng được khai báo, thay vì vẫn tính trung bình các kịch bản thiếu đại diện rồi coi kết quả đáng tin cậy.

Có thể bổ sung weighted historical replay, nhưng trọng số và ngưỡng tương đồng phải được chọn trên dữ liệu phát triển, không phải dữ liệu kiểm tra.

### Vấn đề 2 — EVChoice chưa đủ để nghiên cứu hành vi không cam kết

Kế hoạch đã có ba chế độ:

`FOLLOW_RECOMMENDATION`, `SELF_INTERESTED_CHOICE` và `EXOGENOUS_CHOICE_TRACE`. Pasted text

Đây là thiết kế phần mềm tốt, nhưng có một vấn đề khi nghiên cứu hiệu quả recommendation.

Nếu tất cả EV dùng `FOLLOW_RECOMMENDATION`, ta đang kiểm tra trường hợp tuân thủ hoàn toàn.

Nếu tất cả EV dùng `SELF_INTERESTED_CHOICE` với cùng thông tin và quy tắc lựa chọn, kết quả thường vẫn giống recommendation.

Nếu EV dùng một trace lựa chọn độc lập hoàn toàn với khuyến nghị, hệ thống recommendation có thể không làm thay đổi hành vi của EV.

Vì vậy, **ba chế độ này chưa đủ để kết luận thuật toán có thể giảm waiting ngoài thực tế khi người lái có quyền từ chối khuyến nghị**.

Tôi không đề nghị thêm xác suất 80% hoặc 60%.

Thay vào đó, giữ ba chế độ làm các kịch bản có điều kiện, công bố rõ từng giả định và không suy rộng kết quả sang tỷ lệ tuân thủ thực tế khi chưa có dữ liệu.

### Vấn đề 3 — B4-N nên tối ưu lỗi forecast nào?

Hiện tại, Neighbor Correction được học theo sai số arrival workload:

\[
Y_{m,b+h}-\widehat Y_{m,b+h}^{local}
\]

Đây là một lựa chọn hợp lý để bắt đầu. Pasted text

Nhưng mục đích cuối cùng không phải chỉ dự báo workload tốt hơn.

Mục đích là:

\[
\boxed{
\text{Forecast}
\rightarrow
\text{Waiting Prediction}
\rightarrow
\text{Recommendation}
}
\]

Ví dụ:

- Model A dự báo tổng workload khá chính xác, nhưng bỏ lỡ các đợt 10 EV đến cùng lúc.
- Model B có sai số tổng workload lớn hơn một chút, nhưng dự báo được các thời điểm arrivals tập trung.

Model B có thể tạo waiting prediction hữu ích hơn.

Do đó, tôi đề xuất:

**V1 vẫn huấn luyện B4-N theo workload residual**, nhưng chọn mô hình dựa trên cả arrival forecast error và waiting forecast error trong dữ liệu phát triển.

Không nên chỉ chọn B4-N vì workload MAE giảm.

---

## 3. Vấn đề quan trọng nhất đối với đóng góp Q1

Tôi muốn nhấn mạnh một điểm mà kế hoạch hiện tại chưa giải quyết hoàn toàn.

**Nhu cầu arrivals không độc lập với thuật toán recommendation.**

Giả sử lúc đầu trạm A có ít khách.

B4 dự báo A sẽ tiếp tục ít khách và khuyến nghị nhiều EV đến A.

Người lái thực hiện các khuyến nghị đó.

Một thời gian sau, A trở nên đông khách.

B4 học được rằng A đang có nhiều arrivals và bắt đầu khuyến nghị EV sang B.

Nếu nhiều EV lại chuyển sang B, tình trạng tương tự có thể xuất hiện ở B.

Đây là vòng phản hồi:

\[
\boxed{
\text{Recommendation}
\rightarrow
\text{Driver Choice}
\rightarrow
\text{Actual Arrivals}
\rightarrow
\text{Forecast Update}
\rightarrow
\text{Recommendation}
}
\]

Vòng phản hồi này có thể tạo dao động nhu cầu giữa các trạm.

Điều đó khác với một bài toán dự báo chuỗi thời gian thông thường, bởi **quyết định khuyến nghị có thể làm thay đổi chính dữ liệu mà mô hình sử dụng để học**.

Tôi đề nghị bổ sung một thí nghiệm bắt buộc:

**Recommendation-Induced Demand Shift**

Trong đó cần đánh giá liệu B4-N có thực sự giúp giảm sự tập trung và dao động arrivals giữa các trạm so với B3/B4, hay chỉ làm dịch chuyển tắc nghẽn từ trạm này sang trạm khác.

Các kết quả cần đo gồm peak queue, waiting P95, mức tập trung khuyến nghị, biến động arrivals và tổng chi phí vật lý của những EV đã hoàn thành, đồng thời báo riêng các EV chưa hoàn thành.

Tôi đánh giá đây là vấn đề nghiên cứu quan trọng hơn việc thay Moving Average bằng một mô hình AI phức tạp.

---

## 4. Một điểm cần xem lại trong Pareto–Minimax

Kế hoạch chuẩn hóa min/max trên toàn bộ tập feasible trước Pareto filtering. Pasted text

Nhược điểm: một trạm có kết quả rất tệ, dù chắc chắn bị loại bởi Pareto filtering, vẫn có thể thay đổi thang chuẩn hóa của tất cả trạm khác.

Điều này có thể khiến khuyến nghị thay đổi chỉ vì bổ sung một lựa chọn kém chất lượng.

Tôi đề nghị giữ công thức hiện tại làm baseline, nhưng bổ sung đối chứng sử dụng min/max trên **Pareto set**.

Nếu hai cách cho kết quả khác nhau nhiều, cần xem lại quy tắc chuẩn hóa trước khi chốt phương pháp chính.

Ngoài ra, vì hiện tại:

\[
E_{nm}=k_nD_{nm}
\]

distance và energy vẫn có thông tin phụ thuộc nhau. Minimax tránh cộng lặp chúng theo trọng số, nhưng chưa tạo được một mô hình năng lượng phản ánh giao thông thực tế.

---

## 5. Có cần thay đổi toàn bộ kế hoạch không?

**Không. Tôi đề nghị giữ kiến trúc hiện tại và sửa những điều kiện nghiệm thu trước khi coding.**

Pipeline vẫn là:

\[
\boxed{
\text{Station Local Forecast}
\rightarrow
\text{Neighbor Correction}
\rightarrow
\text{Waiting Prediction}
\rightarrow
\text{Pareto–Minimax Recommendation}
\rightarrow
\text{EVChoice}
}
\]

Nhưng cần ba điều kiện nghiệm thu bổ sung:

**Điều kiện A — Forecast validity**

Historical Replay phải báo mức độ đại diện của các kịch bản đối với workload forecast. Không có lịch sử phù hợp thì không được báo waiting như thể dự báo đáng tin cậy.

**Điều kiện B — Real contribution of inter-station information**

B4-N phải được so sánh với B4 trên cùng dữ liệu quá khứ để tách giá trị dự báo, sau đó đánh giá trong closed-loop GAMA để đo ảnh hưởng thực tế tới hệ thống.

**Điều kiện C — Closed-loop stability**

Đánh giá các tình huống nhiều EV nhận khuyến nghị gần như đồng thời, thay đổi nhu cầu đột ngột và sự dịch chuyển tải giữa các trạm. Không mặc định local forecast hoặc neighbor correction sẽ ngăn được herding.

---

## 6. Đoạn bổ sung gửi coding agent

Anh có thể gửi đoạn này để bổ sung vào kế hoạch hiện tại:

> Tôi đồng ý với kiến trúc Distributed Observation-Driven Charging Recommendation hiện tại, nhưng yêu cầu bổ sung ba nhóm kiểm chứng trước khi triển khai toàn bộ.
>
> **1. Forecast-to-Waiting Consistency:** Kiểm tra Historical Replay có đủ kịch bản đại diện cho workload forecast của B4/B4-N hay không. Nếu không, báo out-of-distribution và sử dụng fallback có nhãn. Không được mặc định 20 historical windows gần nhất luôn đại diện cho forecast.
>
> **2. Neighbor Correction Evaluation:** Không chỉ đánh giá arrival workload MAE/RMSE. Phải đánh giá cả waiting prediction MAE/RMSE, chất lượng recommendation và độ ổn định qua các demand scenarios. Chỉ sử dụng dữ liệu quá khứ và khóa tham số trước giai đoạn test.
>
> **3. Recommendation Feedback:** Bổ sung thí nghiệm recommendation-induced demand shift để đánh giá vòng phản hồi giữa recommendation, EVChoice, actual arrivals và online forecast. Đo herding, peak physical queue, waiting P95, mức tập trung arrivals và mức dao động nhu cầu giữa các trạm.
>
> Giữ B3, B4, B4-N và ideal coordinated assignment benchmark riêng biệt. Không tạo xác suất tuân thủ tùy ý, không có central coordinator, không biến recommendation thành commitment.
>
> Bổ sung ablation chuẩn hóa Minimax trên toàn bộ feasible set so với Pareto set. Không thay đổi quy tắc chính khi chưa có kết quả kiểm chứng.
>
> Ưu tiên hoàn thành B3 và B4, kiểm chứng forecast-to-waiting trước, sau đó mới tích hợp B4-N và trao đổi liên trạm.

### Kết luận

**Kế hoạch hiện tại đủ cụ thể để bắt đầu refactor GAMA, nhưng chưa đủ để kết luận phương pháp B4-N sẽ cải thiện tối ưu nhiều EV.**

Tôi khuyên chốt **B4 làm nền tảng chính, B4-N là đóng góp cần chứng minh**, đồng thời tập trung nghiên cứu vòng phản hồi giữa recommendation và future arrivals.

Nếu hướng tới paper Q1, đây là điểm cần làm rõ về mặt toán học và thực nghiệm: **các trạm có thể cải thiện quyết định khuyến nghị bằng thông tin phân tán như thế nào khi chính những khuyến nghị đó có thể làm thay đổi tải tương lai, nhưng hệ thống không kiểm soát hành vi người lái?**