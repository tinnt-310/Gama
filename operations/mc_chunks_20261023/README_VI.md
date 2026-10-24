# Monte Carlo có checkpoint theo chỉ số mẫu — 23/10/2026

Phiên bản bổ sung dùng cùng release/service; không sửa GAML core, objective, cấu hình vật lý hoặc provenance của training/checkpoint/model. Giữ nguyên N mẫu cho mỗi probe, seed 900001, 165 probe và các ngưỡng đã đăng ký.

Một bản sao hàm ranr_estimate được sinh cơ học: đổi tên hàm; vòng lặp đi qua một khoảng chỉ số mẫu tuyệt đối thay cho toàn bộ 0..N-1; trả thêm các sample wait/externality. Mọi câu lệnh tính từng mẫu giữ nguyên. ranr_samples vẫn bằng N. Không dùng seed mới cho từng khối.

Python kiểm tra các khoảng liên tiếp, không thiếu/trùng/chồng lặp và giữ nguyên thứ tự. Sau đó GAMA đọc lại toàn bộ N giá trị và dùng chính mean/ranr_quantile để tính mean wait, P95 và externality. Không lấy trung bình các P95 của từng khối. Không dùng thống kê Python thay fitness/estimator native.

Khối mặc định tối đa 1024 mẫu cho RANR-AW và No-P2P có exposure. No-Prediction và No-P2P probe 0–2 có thể chạy toàn bộ N trong một khối. Sáu worker riêng, heap 1536 MiB mỗi JVM. Chỉ nhận khối/aggregate sau marker native, kiểm tra số lượng/hữu hạn/source và seal hash. Lưu từng attempt bị ngắt. Checkpoint complete của bộ chạy theo probe trước đó được nhập bằng đối chiếu đầy đủ source/calibration/seed/N/hash/bằng chứng tương đương; không ghi lại manifest gốc.

Bằng chứng trước triển khai gồm đối chiếu đủ 165 probe: hai khối 16+16 mẫu so với benchmark gốc 32 mẫu; probe tải nặng 1024 mẫu được chia thành 8 khối 128 và đối chiếu trực tiếp bảng gốc; fixture âm từ chối mẫu thiếu/chồng lặp; regression test kiểm tra range, cache và nguồn. Xem equivalence.json và archive đợt triển khai. Không dùng phép đo một probe để thay budget benchmark chính thức.

Cùng tiêu chí 95% từng phương pháp/55 probe. Nếu ba probe cùng phương pháp không đạt ở cặp reference tối đa 8192/16384, nhiều nhất 52/55 = 94.545% đạt, đủ bằng chứng FAIL. Giữ mọi dữ liệu, không tạo bảng đầy đủ hay PASS từ partial. Watchdog không tự retry scientific gate đã thất bại, kể cả khi user service được mở lại sau đăng nhập. Gate thất bại cần quyết định giao thức/tài nguyên; không nới ngưỡng hay đổi seed.

Từ thư mục dự án:

```bash
.venv/bin/python -B operations/mc_chunks_20261023/status.py
.venv/bin/python -B -m ranr.gama.release status
.venv/bin/python -B -m ranr.gama.release stop
.venv/bin/python -B -m ranr.gama.release resume
```

Checkpoint: benchmark/native_chunks/<N>/<method>/<station>/<probe>/chunks/<begin>_<end>/; kết quả đầy đủ của probe: probe.csv và manifest.json ở thư mục probe. Chỉ khi đủ 165 probe mới công bố probes_N.csv. Các checkpoint native_shards của phiên bản trước vẫn giữ nguyên.

Bộ đếm thời gian training dùng journal 5 giây đã kiểm thử trước đó tại operations/mc_checkpoint_20261023/budget_ledger.py. Ngân sách vẫn 72 giờ riêng training, cộng dồn qua resume; chưa chạy training khi accuracy/design/performance chưa hợp lệ. Development, design, training và evaluation dùng CLI/implementation chính thức. Không chạy worker thứ hai cạnh tranh trên cùng release.

Sau khi pipeline dừng hoặc hoàn tất, công cụ báo cáo kiểm tra hash/ledger và tạo package mới. Trạng thái research_complete=false nghĩa là vẫn thiếu bằng chứng; không thể suy ra RANR vượt baseline hoặc sẵn sàng công bố IEEE chỉ từ code/test đạt.

Đã kiểm tra user manager ngày 23/10: Linger=no. Service độc lập với phiên Codex khi desktop vẫn đăng nhập. Nếu tắt máy hoặc kết thúc toàn bộ phiên đăng nhập, lần mở lại dùng các khối complete đã seal; khối đang dở chạy lại. Không ghép hai đoạn trạng thái mô phỏng GAMA của một episode. Journal training giữ ngân sách đã tiêu thụ qua gián đoạn.

Journal và checkpoint được nâng cấp ghi bền vững: đồng bộ dữ liệu bằng fsync trước atomic rename, rồi fsync thư mục. Giữ cùng pickle protocol và trạng thái optimizer. Đã thử 9 test I/O/budget, 3 integration CMA và SIGKILL trên tiến trình fixture riêng. Nếu ghi journal thất bại, chính job training dừng để bảo toàn checkpoint đã ghi và không tiếp tục tiêu ngân sách không được ghi nhận. Bản ledger trước nâng cấp được lưu kèm hash trong archive; không reset ngân sách.

Scientific failure không được retry. Trạng thái needs_attention chưa phân loại phải được kiểm tra log/checkpoint; một lần retry lỗi hạ tầng cần hồ sơ infra_retry_review.json gắn đúng hash state/source/bằng chứng. Với training phải khóa cả checkpoint và elapsed journal. Hồ sơ được tiêu thụ một lần và lưu lịch sử; không dùng hồ sơ hạ tầng để vượt gate reference/accuracy/physical/budget đã thất bại. Agent có thể lập hồ sơ sau kiểm chứng lỗi kỹ thuật trong quyền đã được giao, không cần hỏi lại từng bước.
