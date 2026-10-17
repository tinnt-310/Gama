# Trạng thái RANR-AW — 17/10/2026

Môi trường `persistent-soc-activity-6`, objective `intent-service-5`, observation `station-observation-4`. Mỗi episode chuẩn 4320 phút: 6h warmup + 60h measurement + 6h drain, bước 60s. Training tối đa 72 giờ máy riêng, cộng dồn qua resume.

Ba Collect 800001/800002/800003 hoàn tất trên phiên bản trước sửa pipeline được giữ nguyên. Chọn seed theo manifest, không dùng directory mtime. Dữ liệu cũ chỉ được nhận qua kiểm tra tương thích và replay; không sửa provenance trong manifest. Khác biệt một lượt 800001 lịch sử vẫn cần truy nguyên. Nếu không chứng minh được tương thích, pipeline thu mới trên nguồn đóng băng.

Đã bổ sung bộ chọn Collect, kiểm tra 33 station-day, evidence-linked freeze, externality accuracy gate, dedup design, training-only budget, replay diagnostics và supervisor release. Không suy ra các gate dài đã đạt từ việc đã có code hoặc test nhỏ.

Trạng thái thực của đợt hiện tại đọc từ `outputs/gama_ranr/release_latest.json`, sau đó `state.json` trong thư mục output; dùng lệnh release status trong [README_LENH](../README_LENH.md). Mỗi stage có log, thời gian active và hash artifact. Chỉ trạng thái complete của training/evaluation là bằng chứng hoàn thành tương ứng. needs_attention/budget_limited không được coi là model chính thức.

[Lịch sử trước đợt hoàn thiện](history/GAMA_STATUS_BEFORE_RELEASE_20261017.md) được bảo toàn; các số liệu 28 ngày trong đó không áp dụng cho protocol 3 ngày hiện tại.
