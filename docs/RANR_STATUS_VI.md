> Tài liệu lịch sử. Mô hình hiện hành: persistent-soc-activity-6 / intent-service-5; xem [hồ sơ khoa học](GAMA_RANR_SCIENTIFIC_CHANGES_VI.md).

> Tài liệu lịch sử: mô tả nguồn trước nâng cấp. Đối chiếu tại Git checkpoint `5800181`; hướng dẫn hiện hành ở [GAMA Run Guide](GAMA_RANR_RUN_GUIDE_VI.md).

> **Tài liệu lịch sử của simulator Python.** Từ 14/10/2026, nghiên cứu chính chuyển sang GAMA. Mã tương ứng nằm trong `src/ranr/legacy/python_reference/`; xem [trạng thái GAMA](GAMA_RANR_STATUS_VI.md).

# Trạng thái nghiệm thu RANR

Ngày bắt đầu: 13/10/2026, Asia/Bangkok. Đây là trạng thái tiến độ, chưa phải báo cáo hiệu năng nghiên cứu.

## Đã hoàn thành

- Tái cấu trúc Python canonical/legacy, entry points tương thích và backup/inventory.
- GIS đủ 11 trạm, 125 cổng, 7.195 kW; 121 route pairs đối chiếu GAMA sai số tối đa ~1.7e-7 m.
- Simulator, bốn phương pháp, observation/P2P/exposure, penalties và SOC/energy outcomes.
- CMA-ES, checkpoint/resume, source guard, raw logging nén, CI/Holm và report CLI.
- 42 module GAML cũ compile PASS; 32 runtime/contract regression checks PASS; GISReferenceExport PASS.

## Đang kiểm chứng / chưa hoàn thành

- Bộ tests Python cuối: **53 tests PASS**; benchmark release PASS, **256 scenario** đạt gate riêng cho mọi estimator.
- Smoke training bốn phương pháp hoàn tất; **48 evaluation runs** (6 nhóm × 2 development seeds × 4 methods) hoàn tất, báo cáo/hình đã sinh. Đây chỉ là end-to-end validation.
- **Training research đang chạy**: 3 optimizer seeds, min1024/max4096 mỗi phương pháp; log/checkpoint tại outputs/ranr/training/research_release.
- Evaluation research 6 nhóm × 30 seeds × 4 phương pháp, 24h warmup và 48h measurement.
- Báo cáo kết quả research và phân tích sensitivity đầy đủ.

Không dùng outputs/training/smoke_v1 của giai đoạn sửa code để suy ra hiệu năng. Artifact smoke có profile riêng và không được dùng cho research evaluation. Kết quả mới chỉ được nghiệm thu sau khi manifest complete và tests/benchmark nguồn tương ứng đạt.

Logs hiện tại: outputs/ranr/python_validation_final.log, benchmark_release.log, smoke_release_training.log, research_training.log.

Smoke report: outputs/ranr/evaluation/smoke_release/report/REPORT_VI.md. Trained smoke parameters không phải trained research parameters.

Supervisor đã khởi chạy: scripts/continue_research_release.py. Khi training hoàn tất, nó tự chạy research evaluation/report và kiểm tra 720 manifest/artifact hashes. Trạng thái chính xác: outputs/ranr/research_pipeline.json.

## Kiểm tra tiến độ ngày 14/10/2026

Trainer và supervisor trước đó đã dừng; nhãn `running` trong registration chưa phản ánh việc tiến trình kết thúc. Checkpoint cuối của RANR-AW, optimizer seed 41001, ghi 1.264 candidate evaluations. Chưa có bộ tham số research cuối và chưa có research evaluation run. Source manifest vẫn khớp registration; supervisor đã được khởi động lại để resume checkpoint. Cần kiểm tra lock tiến trình cùng manifest, không suy ra tiến độ chỉ từ nhãn `running`.

Các hạng mục nghiệm thu còn thiếu: hoàn tất training cả bốn phương pháp với ba optimizer seeds; 720 research evaluation runs; báo cáo research với CI/Holm, đường chất lượng theo ngân sách và chi phí tính toán; phân tích sensitivity deadline/penalty trên development; rà soát kiến trúc và hồ sơ tái lập sau khi toàn bộ thực nghiệm hoàn tất.
