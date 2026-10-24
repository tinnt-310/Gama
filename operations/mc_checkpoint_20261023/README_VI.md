# Vận hành Monte Carlo có checkpoint — 23/10/2026

Bộ chạy bổ sung tái sử dụng **cùng release và systemd service**. Mã mô phỏng GAMA, Python core, calibration, objective, seed, số mẫu và ngưỡng đạt được giữ nguyên. Source core và mã bộ chạy được ghi/hash riêng trong runtime_registration.json và deployment.json.

Benchmark mẫu lớn trước đây chỉ xuất CSV sau 165 probe, nên một lần máy bị ngắt có thể mất nhiều giờ đang tính. Bộ chạy này dùng đúng estimator GAMA với toàn bộ N mẫu/seed 900001 cho từng probe, ba worker giới hạn heap riêng 3072 MiB. Mỗi probe complete được kiểm tra marker/hữu hạn/key, lưu CSV/resource/log và seal hash. Chỉ khi đủ grid duy nhất mới ghép CSV nguyên tử. Không dùng partial CSV làm PASS.

Fixture được sinh cơ học từ benchmark gốc: chỉ thêm bộ chọn probe và tắt scenario cache trong benchmark. Cache không được dùng lại qua các request key riêng biệt của 165 probe; các sample draw, thuật toán service, phân phối và phép tính mean/P95/H giữ nguyên. Bằng chứng GAMA gốc-vs-bản chia trên đủ 165 probe và cùng 32 mẫu nằm trong equivalence.json. queue_calls là bộ đếm chẩn đoán theo tiến trình, nên không phải metric khoa học để so giữa các tiến trình riêng.

Ở cặp reference tối đa đã đăng ký 8192/16384, nếu có ba probe không đạt của cùng phương pháp trong 55 probe, nhiều nhất còn 52/55 = 94,545% đạt ngay cả nếu mọi probe chưa chạy đều đạt. Có thể dừng sớm với **FAIL có chứng minh**, giữ các kết quả và không tạo bảng đầy đủ hoặc artifact PASS giả. Không tự tăng sample cap hay thay ngưỡng để cứu gate.

Nhật ký elapsed_journal.json ghi thời gian active training mỗi 5 giây. Khi phục hồi sau mất điện, consumed budget bằng giá trị lớn hơn của checkpoint/journal, cộng một chu kỳ dự phòng nếu kết thúc không sạch. Chỉ tăng active_seconds trong bản sao checkpoint đã lưu bản gốc; RNG, population, generation và identity không đổi. Ngân sách vẫn tối đa 72 giờ riêng training. Đã thử SIGKILL trên fixture riêng, không ngắt training sản xuất để thử.

Từ thư mục dự án:

```bash
.venv/bin/python -B -m ranr.gama.release status
.venv/bin/python -B operations/mc_checkpoint_20261023/status.py
.venv/bin/python -B -m ranr.gama.release stop
.venv/bin/python -B -m ranr.gama.release resume
```

Resume tái sử dụng service override đang đăng ký; không chạy thêm worker bằng tay. Các thông báo scientific gate failed cần phân tích và quyết định giao thức phiên bản mới, không tự retry để chọn kết quả thuận lợi. Không sửa core hoặc operations trong lúc release chạy; nếu source/hash đổi, bộ chạy từ chối trộn kết quả.

Sau khi release dừng hoặc hoàn thành, research_audit.py kiểm tra và tạo thư mục mới trong outputs/gama_ranr/final_research_package. Báo cáo ghi rõ dữ liệu thiếu; chỉ trạng thái research_complete=true cùng đầy đủ bằng chứng mới xác nhận hoàn tất kỹ thuật. Điều đó vẫn không thay thế kiểm chứng các giả định bằng dữ liệu Nha Trang thực tế hoặc phản biện khoa học.
