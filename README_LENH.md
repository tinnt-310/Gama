# Chạy và theo dõi RANR GAMA

Dùng terminal tại thư mục dự án:

```bash
cd "/home/tinnt/Gama_Workspace/Nha Trang CSs planning"
.venv/bin/python -B -m unittest discover -s tests -v
.venv/bin/python -B -m ranr validate --compile
```

Môi trường `persistent-soc-activity-6`, objective `intent-service-5`. Một episode chuẩn dài **3 ngày mô phỏng**, tương ứng 4320 cycle 1 phút. Hoàn thành episode sẽ xuất dữ liệu và pause. Ngân sách **72 giờ máy riêng training** khác với 72 giờ mô phỏng của từng episode.

## Pipeline đến training và đánh giá

```bash
.venv/bin/python -B -m ranr.gama.release start
.venv/bin/python -B -m ranr.gama.release status
.venv/bin/python -B -m ranr.gama.release stop
.venv/bin/python -B -m ranr.gama.release resume
```

`start` tạo registration mới và dịch vụ systemd user có log/trạng thái. Để tiếp tục đợt cũ dùng resume. Một đợt lần lượt chạy Python/native validation, ba replay 800001, nhận calibration, accuracy, 36 development, 864 design, freeze, performance benchmark, optimizer smoke GAMA thật, training và 720 evaluation. Nếu một gate không đạt, dịch vụ dừng ở needs_attention và lưu diagnostic; không chạy bước kế tiếp. budget_limited chưa có model chính thức.

Pipeline giữ nguyên Collect lịch sử. Dùng lại chúng cần GUI replay mới, giải thích có bằng chứng cho lượt 800001 bất thường và review từng file nguồn thay đổi; các tùy chọn start là `--gui-run`, `--outlier-resolution`, `--compatibility-review`. Nếu thiếu bằng chứng, mặc định thu mới ba seed sau khi headless replay tái lập đạt; có thể dùng `--no-fresh-fallback` để dừng tại gate tái sử dụng. Không tự sửa manifest cũ hoặc xóa lượt dở.

Status cho biết thư mục output, stage hiện tại, thời gian đã chạy và trạng thái dịch vụ. Logs ở `OUTPUT/<stage>.log`, `supervisor.log`; diagnostic ở `diagnostic.json`. Không sửa nguồn khi dịch vụ đang chạy. Stop giữ artifact; resume tái sử dụng episode đã complete/đúng hash và chạy lại episode bị ngắt từ đầu. CMA-ES có checkpoint riêng, giữ population/RNG và ngân sách đã dùng.

## Thu bằng GUI

Mở `models/main.gaml` → **Collect training data**. Chọn seed 800001 trước Initialize, Play đến collection complete; lặp với 800002 và 800003. Đổi seed sau Initialize cần Reload. Sau ba lượt hợp lệ dùng **Validate and build calibration**. Builder báo selected/skipped; lượt mới còn running không che lượt hoàn thành. Lượt complete hỏng hash bị từ chối.

Chỉ định ba thư mục Collect tường minh qua CLI:

```bash
.venv/bin/python -B -m ranr calibrate --runs /path/seed800001 /path/seed800002 /path/seed800003
```

Với dữ liệu khác nguồn, cần thêm `--compatibility /path/verified_compatibility.json`. Chỉ cập nhật latest calibration sau khi cả ba đầu vào đạt kiểm chứng. Con trỏ trước đó được lưu cùng build để có thể khôi phục.

## Các stage riêng

Sau khi có calibration hiện hành và native validation:

```bash
.venv/bin/python -B -m ranr --config configs/gama/research.json benchmark --stage accuracy --output outputs/gama_ranr/benchmark/release
.venv/bin/python -B -m ranr --config outputs/gama_ranr/benchmark/release/accuracy_config.json development-validation
.venv/bin/python -B -m ranr --config outputs/gama_ranr/benchmark/release/accuracy_config.json design-validation
```

Sau evidence-backed freeze, chạy benchmark `--stage performance` với accuracy_config.json, rồi train bằng locked_config.json và budget.json của cùng benchmark. Giữ 15% dự phòng trong training; nếu ngân sách không đủ thì dừng và báo, không tự giảm protocol. Bốn model phải hoàn tất trước evaluate. Tất cả kiểm chứng dài và kết luận hiệu quả được theo dõi riêng với kiểm thử nhỏ.

## Monte Carlo có checkpoint — 23/10/2026

Benchmark giữ nguyên seed/số mẫu/ngưỡng, lưu riêng từng native probe và seal hash. Xem [vận hành và bằng chứng](operations/mc_checkpoint_20261023/README_VI.md). Lệnh `python -B operations/mc_checkpoint_20261023/status.py` trong thư mục dự án hiển thị tiến độ từng probe. Cùng release/service được dùng tiếp; không mở worker cạnh tranh.

## Checkpoint theo chỉ số mẫu — 23/10/2026

Bộ chạy mới giữ đủ N mẫu, dùng GAMA ghép/tính thống kê và tái sử dụng các probe hoàn thành đã kiểm chứng. Trạng thái hiện hành: `.venv/bin/python -B operations/mc_chunks_20261023/status.py`. Xem [bằng chứng và vận hành](operations/mc_chunks_20261023/README_VI.md). Các checkpoint native_shards cũ vẫn được giữ nguyên.
