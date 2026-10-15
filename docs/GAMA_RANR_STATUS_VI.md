# Trạng thái RANR-AW hiện hành

Môi trường **persistent-controlled-distributed-3**. Triển khai tại chỗ và các kiểm tra nhỏ đã đạt; **chưa nghiệm thu hoàn chỉnh thực nghiệm nghiên cứu**.

- 31 unit tests Python đạt;25 GAML roots compile đạt.
- Native fixtures kiểm tra vật lý, FIFO, energy, cổng hỏng/khôi phục và power phân số, information, exposure, softmax/cost, objective và bốn phương pháp đạt.
- Burst kích hoạt đồng thời20/50/100/200 request trên EV hiện hữu đạt trong fixture có deferral được điều khiển; không phải bằng chứng giảm congestion.
- Episode fixture sạc xong30.6kWh trong17 phút service time; EV vẫn tồn tại. Native driving fixture tới trạm và bắt đầu nhận năng lượng.
- Paired smoke4 phương pháp có cùng exogenous hash và7 xe thường trực. Horizon cực ngắn không có activation, nên không dùng đo recommendation quality.
- Startup Run me4700 xe và Collect training data registration đã kiểm tra. Builder3seed được thử bằng unit fixtures; chưa thu3episode dài.
- Microbenchmark GAML đã có; chưa có full GIS accuracy/runtime benchmark.
- GIS và9.117 tệp output lịch sử giữ nguyên hash. Git checkpoint trước sửa:`5800181`.

Nguồn hiện tại có một mô hình fleet/opportunities/inbound và một pipeline GAMA. Source history/algorithms cũ được giữ bằng Git; historical outputs không phải kết quả hiện hành.

Có thể bắt đầu thu calibration trong **Collect training data**. Training chính vẫn khóa cho tới khi có calibration đầy đủ, long development validation, full benchmark/accuracy, sensitivity và reviewed design freeze. Chưa chạy CMA-ES chính, validation model dài hoặc720 test runs.

Chưa có bằng chứng hiệu quả ngoài thực nghiệm; chưa hiệu chỉnh gates, demand/activity/driver assumptions trên dữ liệu Nha Trang thực; chưa chạy automated Workbench clicks/long GUI–Headless equivalence. Các giới hạn và microbenchmark scope được ghi rõ trong [báo cáo](GAMA_RANR_IMPLEMENTATION_REPORT_VI.md).

Bằng chứng máy đọc:`outputs/gama_ranr/distributed_upgrade_20261015/acceptance.json`. Hướng dẫn:[GAMA Run Guide](GAMA_RANR_RUN_GUIDE_VI.md). Kiến trúc/cây thư mục:[architecture](GAMA_RANR_ARCHITECTURE_VI.md).
