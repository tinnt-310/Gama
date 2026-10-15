# Giờ cao điểm, đồng hồ và smoke — 2026-10-08

Theo cấu hình người dùng: B3 trên GIS Nha Trang, 7 ngày, cycle 60 giây, 3.000 xe thường và 1.732 EV nền. Cao điểm vừa tăng hoạt động của xe đang có, vừa bổ sung tối đa 30% mỗi loại.

Dân số bổ sung tính riêng từ cars, taxis, privates và làm tròn xuống: 900 xe thường, 341 taxi EV, 178 private EV. Chỉ bổ sung một lần mỗi cửa sổ cao điểm; xe bổ sung còn sống từ đợt trước được trừ khỏi số cần tạo. Cleanup thu hồi toàn bộ xe bổ sung chưa có yêu cầu sạc trong một tick, thay cho một xe mỗi cycle. Những EV có yêu cầu sạc giữ nguyên request, route và state; sau khi hoàn thành hoặc huỷ mới thu hồi. Không thay GIS, vị trí trạm, số cổng hoặc backend FIFO.

Xe nền đủ điều kiện và đang nghỉ được tạo chuyến đi theo lịch cá nhân đã có trong khung cao điểm. Xe đang đi hoặc có yêu cầu sạc không bị chuyển đích. Đây là giả định hoạt động synthetic, chưa được hiệu chỉnh theo dữ liệu giao thông thực tế.

Monitor elapsed dùng tổng giờ:phút: `05:36`, `100:00`, `168:00`. Phút 00–59, giờ không quay về 0 qua ngày. Start hour chỉ đổi lịch hoạt động, không cộng vào elapsed. Theo yêu cầu giữ ô GAMA nguyên bản, đã bỏ reflex ghi `status` mỗi cycle. Trong GAMA 1.9.3, `StatusControlContribution.updateWith` đặt `inUserStatus` về false sau khi cập nhật, nên thông báo clock native có thể thay thông báo custom ở lần sau. Không tiếp tục dùng cách ghi đè này.

Assertion `time < 120 + step` trong smoke verification thất bại khi bật Small GIS scenario giữa run. Mode hiện được chốt tại init; kiểm thử smoke chỉ chạy khi setup đã dùng mode đó. Mốc upper-time không còn là assertion production; fixture riêng vẫn kiểm clock và timing.

Các bản snapshot `.gaml` trong output thiếu imports gây lỗi IDE. Snapshot hiện lưu `.gaml.txt`, không làm thay đổi model thực thi `models/main.gaml`.

Kiểm chứng gồm RushActivityRegression (0% extras, chuyến đi xe nền và bảo vệ EV sạc), RushCohortRegression (30%, cleanup, EV còn request, cap đợt tiếp theo), LateSmokeRegression (bật muộn), ElapsedClockRegression (qua 100 giờ và 1.000 giờ), cùng toàn bộ regression GAMA/Python. Log red và green được lưu trong outputs.

Kết quả kiểm chứng trước run dài: `outputs/rush_smoke_full_gama_suite.log` kết thúc exit 0, tất cả compile/runtime/GIS fixtures PASS; `outputs/rush_smoke_python_suite.log` ghi 32 tests OK. Run dài dùng config, source/input manifests và source snapshots tại `outputs/b3_gis_7days_rush30_seed42_20261008_201436/`. Kết quả dài hạn cần đọc `status.json` và `REPORT.md` sau khi run hoàn tất.
