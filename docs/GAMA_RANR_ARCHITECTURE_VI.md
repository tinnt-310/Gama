# Kiến trúc nghiên cứu GAMA RANR-AW

Môi trường `persistent-controlled-distributed-3`. GAMA thực thi vật lý, nhu cầu và recommendation; Python điều phối GAMA, kiểm chứng và phân tích. Không có simulator Python trong nguồn hiện hành. Checkpoint trước sửa: Git `5800181`; mã legacy và dữ liệu nghiên cứu lịch sử có thể đối chiếu tại checkpoint, không thuộc pipeline hiện tại.

```text
models/
  main.gaml                    GIS, khởi tạo, Run me và Collect training data
  Mobility.gaml                native driving, hoạt động và xe thường trực
  ChargingService.gaml         cổng có ID, FIFO, SOC/energy, lifecycle sạc
  ranr/
    Math.gaml                  cấu hình, record helpers, RNG, weights, shadow queue
    Prediction.gaml            snapshot/ETA Monte Carlo, externality ghép cặp
    Policy.gaml                observation từng trạm, exposure, recommendation
    Fleet.gaml                 opportunities, eligibility, inbound/outbound
    Evaluation.gaml            outcome và objective phân rã
    Runtime.gaml               thứ tự sự kiện, transport, behavior, logs
  tests/                       fixtures GAML nhỏ, không phải kết quả nghiên cứu
src/ranr/
  gama/
    contracts.py               kiểm chứng ledger/schema và phân tích objective
    headless.py                config, provenance, GAMA execution, completion
    launcher.py                JVM/GAMA portable launcher
    validation.py              compiler và native fixture harness
    gui_collection.py          đăng ký/kiểm chứng/build calibration GUI
    pipeline.py                paired runs, calibration và CI/Holm/report
    benchmarking.py            accuracy/performance gates
    development.py             kiểm chứng vật lý/demand theo ngày
    design.py                  design comparisons và evidence-linked freeze
    training.py                CMA-ES, checkpoint, resume, validation dài
    analysis.py                sensitivity và training reporting
    cli.py                     các lệnh chính thức
configs/gama/                  cấu hình môi trường và các profile
scripts/                       entry point mỏng và Java compiler helper
includes/                      GIS và icon gốc, bảo toàn
outputs/gama_ranr/              run riêng, manifests, checkpoints, báo cáo
```

Chiều import GAML là một DAG: Runtime → Evaluation → Fleet → ChargingService → Policy → Prediction → Math → Mobility. Không còn import Recommendation, Coordination, ConvexAssignment hoặc StationForecast lịch sử.

Observation và request là các record số được sao chép. Policy không nhận agent, global fleet hoặc opportunity manifest. PhysicalState tồn tại trong GAMA; evaluator được phép đọc truth để ghi kết quả. Bộ vận chuyển truy cập địa chỉ agent nhằm giao packet, không cung cấp trạng thái peer cho policy.

Một tick xử lý service và các terminal events, deadline, arrival, packet đã đến từ tick trước, exceptional replanning, opportunities, request có thứ tự ID, capture/broadcast và logging. Packet phát trong tick này chỉ nhận từ tick sau kể cả delay=0; local exposure cập nhật ngay. Đây là thứ tự scheduler xác định, không có barrier chờ quyết định toàn mạng hay central dispatcher.

Output từng run gồm configuration, initial fleet, opportunity/traffic manifests, opportunity_results, opportunity_outcomes, demand, recommendations, messages, events, vehicles, queue_history, outcomes, metrics và completion. GUI calibration bổ sung registration/provenance từ đầu và artifact hashes khi hoàn tất. Model/calibration/schema cũ bị từ chối; không sửa nhãn nguồn cũ.
