> Tài liệu lịch sử, không mô tả trạng thái hiện hành.

# Trạng thái RANR-AW hiện hành

**Chế độ đang chọn: thu trong GAMA GUI.** Theo yêu cầu chuyển sang vừa quan sát vừa thu, dịch vụ headless của đợt `four_weeks_1792122221158286815` đã dừng và tắt tự khởi động. **Collect training data** hiện cùng dùng `calibration_4weeks.json` ở GAML và Python bridge; đã kiểm tra khởi tạo thực experiment này với 4.700 xe, 28 ngày, bước 60 giây và rendering bật. Đã biên dịch 29 model, qua 57 kiểm thử Python và hai fixture thuật toán/cache dự báo sau thay đổi lời gọi hàm. Lượt khởi tạo thử 2 cycle được đánh dấu loại khỏi calibration, không phải dữ liệu hoàn tất. Xem [hướng dẫn GUI](../README_LENH.md) để chạy ba seed trong GAMA; chưa có bộ dữ liệu 4 tuần mới được công bố.

Đợt thu **4 tuần/seed** được chạy và giám sát theo [README_LENH.md](../README_LENH.md), dùng profile `configs/gama/calibration_4weeks.json`. Lệnh `status` trong hướng dẫn là nguồn trạng thái hiện tại. Bộ chạy tự kiểm chứng cả ba seed trước khi công bố calibration mới.

**Cập nhật 16/10/2026:** đợt `four_weeks_1792070842001322642` đã hoàn tất hai seed 800001/800002, nhưng seed 800003 bị validator chặn vì 6 lần taxi tính lại tuyến khi chưa rời đoạn đường sau khi yêu cầu sạc hết hạn. Dịch chuyển 64–68 m không được ghi vào quãng đường và SOC. Chưa công bố calibration 4 tuần. Dữ liệu gốc được giữ nguyên; báo cáo ở `audit_cancel_midroad_20261016/` trong thư mục đợt cũ.

Đã sửa hoạt động cá nhân để chờ `ranr_road_clear_pending`/`ranr_replan_pending` kết thúc trước khi tính tuyến mới. Kiểm thử hồi quy tái hiện thất bại trước bản sửa và đạt sau bản sửa; 56 kiểm thử Python đạt. Đợt mới `four_weeks_1792122221158286815` đang chạy lại preflight (44 lượt GAMA và lượt thử lịch 28 ngày) rồi tự thu lại cả ba seed trên cùng bản nguồn. Kết quả kiểm tra hiện tại xem qua lệnh `status`; dữ liệu mới chưa sẵn sàng training.

Preflight của đợt cũ đã đạt **56 kiểm thử Python, 29 model biên dịch và 43 lượt GAMA native**. Lượt thử riêng 28 ngày với 6 xe ở bước 1 phút đã được kiểm chứng: 308 dòng thống kê trạm/ngày, 2.692 dòng SOC, 38 lần bắt đầu sạc, 42 request, 0 xe hết pin. Kiểm thử nhóm xe nhỏ này chưa bao phủ lỗi hủy yêu cầu giữa đường trong fleet lớn; kiểm thử hồi quy mới đã bổ sung trường hợp đó. Artifact preflight cũ: `outputs/gama_ranr/long_collection/four_weeks_1792070842001322642/preflight/`.

Các kết quả 3 ngày bên dưới thuộc checkpoint `5cc7ffeeeab910f1877ed00ba5a0a17a86fc7614`. Nguồn hiện tại đã thêm bộ giám sát và sửa tra cứu map lịch sử; kiểm tra provenance yêu cầu thu lại calibration trước khi training với bản nguồn mới. Dữ liệu lịch sử vẫn được giữ nguyên.

Đã hoàn tất thay lịch sạc ngẫu nhiên/quota bằng SOC và lịch hoạt động, dùng chung `Run me`, `Collect training data` và Headless. Môi trường **persistent-soc-activity-5**, objective **intent-service-4**.

- **46 kiểm thử Python đạt; 28 GAML roots biên dịch thành công; 42 lượt GAMA native đạt.** Validation có cùng hash nguồn với ba dataset mới.
- Đã kiểm tra pin thấp, target100%, chuyến dài đủ/thiếu năng lượng, hoạt động cá nhân, taxi chở khách/trước ca, retry cùng intent, chống request trùng, drain, cấp/trả cổng, replan và xe thường không đổi tuyến giữa đường.
- **Ba seed mới đã hoàn tất đủ72 giờ**, kiểm chứng SOC/quãng đường/cổng sạc/fleet/inbound và CSV ngày cuối đều đạt. Đây là dữ liệu calibration, chưa phải huấn luyện CMA-ES.

| Seed | Phút mô phỏng | Intent toàn lượt | Hoàn tất | Chưa giải quyết | Lần yêu cầu | Retry | Xe hết pin |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 800001 | 4320.0 | 2195 | 2194 | 1 | 2346 | 151 | 0 |
| 800002 | 4320.0 | 2290 | 2290 | 0 | 2435 | 145 | 0 |
| 800003 | 4320.0 | 2144 | 2144 | 0 | 2272 | 128 | 0 |

Calibration của checkpoint 3 ngày: [calibration.json](../outputs/gama_ranr/gui_calibration/builds/soc_activity_1792066421667216968_validated/calibration.json). Báo cáo đầy đủ: [nghiệm thu20 test](GAMA_SOC_ACTIVITY_ACCEPTANCE_VI.md), [artifact tổng hợp](../outputs/gama_ranr/soc_activity_recollection/1792066421667216968/collection.json).

Checkpoint trước refactor: `e8f70f35cf67ea7ec565ff07ea5037ab0ec36153`. Checkpoint nguồn cuối đã kiểm chứng: `5cc7ffeeeab910f1877ed00ba5a0a17a86fc7614`. Nhánh và staging area của người dùng được giữ nguyên. Output lịch sử và các lượt bị loại không bị xóa và không trộn vào calibration mới.

**Có cảnh báo bộ nhớ nền trong cả ba lượt.** Wrapper ban đầu từ chối các log; dữ liệu hoàn tất đã được kiểm chứng lại bằng validator hiện có, giữ nguyên artifact vật lý và giữ cả manifest failed gốc. Chi tiết/cảnh báo trong báo cáo nghiệm thu.

**Chưa chạy full CMA-ES.** Phân phối tài xế, booking, ca và traffic là giả định nghiên cứu chưa hiệu chỉnh theo khảo sát Nha Trang. Mô hình sạc hiện chưa có taper theo SOC. Các gate thiết kế, accuracy, budget và sensitivity vẫn áp dụng trước training/evaluation chính; kiểm thử chức năng không chứng minh ưu thế nghiên cứu.

Đóng experiment cũ và Refresh dự án trước khi chạy lại. Xem [Run Guide](GAMA_RANR_RUN_GUIDE_VI.md), [thiết kế sạc](GAMA_ENERGY_CHARGING_VI.md).
