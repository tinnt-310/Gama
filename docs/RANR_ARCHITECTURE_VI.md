> Tài liệu lịch sử: mô tả nguồn trước nâng cấp. Đối chiếu tại Git checkpoint `5800181`; hướng dẫn hiện hành ở [GAMA Run Guide](GAMA_RANR_RUN_GUIDE_VI.md).

> **Tài liệu lịch sử của simulator Python.** Từ 14/10/2026, nghiên cứu chính chuyển sang GAMA. Mã tương ứng nằm trong `src/ranr/legacy/python_reference/`; xem [trạng thái GAMA](GAMA_RANR_STATUS_VI.md).

# Kiến trúc và tái cấu trúc RANR

## Cây thư mục

```text
src/ranr/                  package canonical, CLI và mô hình nghiên cứu
  config.py, records.py    cấu hình đã kiểm tra và kiểu observation bất biến
  geography.py             GIS, noding, routing và kiểm chứng GAMA
  charging.py              physical FIFO và reference scalar
  simulation.py            lịch sự kiện, ground truth và vòng đời demand
  behavior.py              kernel giả định và driver riêng biệt
  information.py           peer packets, exposure và watermarks
  prediction.py            scenario waiting và ngoại tác ghép cặp
  policies.py              bốn phương pháp bằng cấu hình chung
  native.py, _queue.cpp     kernel FIFO số học; NumPy reference giữ độc lập
  training.py              CMA-ES, selection và checkpoint
  experiments.py           rollout, provenance và artifacts
  evaluation.py            physical metrics và penalties
  reporting.py             CI, Holm, bảng và hình khoa học
  logging.py, paths.py      log nén và đường dẫn/JSON atomic
  legacy/                  numerical references và workflow GAMA cũ
configs/                   source configuration, không chứa trained weights
tests/                     kiểm chứng bất biến, thông tin và compatibility
models/, includes/         GAMA/GIS gốc
scripts/, verification/    compatibility entry points cho lệnh cũ
docs/                      phương pháp, kiến trúc, hồ sơ sửa đổi và hướng dẫn
outputs/                   cache, dữ liệu dẫn xuất, model, log và kết quả
```

Các wrapper ở scripts/verification chỉ bootstrap src và chuyển tiếp đến canonical implementation. Launcher GAMA và các reference số học giữ trách nhiệm độc lập. Legacy recommendation evaluation được tách khỏi launcher/calibration; cùng dùng ledger reader chống duplicate physical events với evaluator assignment.

Dependency runtime RANR: NumPy, SciPy, pyproj, pyshp, pycma, Matplotlib. CVXPY/Clarabel chỉ thuộc extra `legacy`; Black chỉ dùng để định dạng khi phát triển. Compiler C++17 dùng cho kernel tối ưu, với `RANR_DISABLE_NATIVE=1` để chạy reference NumPy. Compiler không điều khiển RNG, thông tin hoặc policy.

Các imports đi từ CLI/training/experiments xuống environment/policy và cuối cùng records/config/paths. Simulator không import training hoặc reporting. `PolicySettings` loại ground-truth parameters khỏi giao diện thuật toán.

## Di chuyển an toàn

Inventory 6.990 files và backup nguồn nằm trong `outputs/restructuring_20261013/`. Hash từng file được lưu trước thay đổi; GIS gốc và các kết quả nghiên cứu cũ được giữ.

`models/outputs` cũ chuyển nguyên trạng vào `outputs/archive/gama_models_outputs_20261013`, có kiểm tra hash trước/sau. Artifacts regression mới cũng được archive. Link tương thích `models/outputs → ../outputs/legacy` đưa các lần chạy legacy tương lai ra ngoài source. Các mapping chi tiết nằm cạnh inventory.

README gốc được giữ tại `README_GAMA.md`. Các tài liệu B3/B4/minimax mô tả implementation GAMA lịch sử, không được dùng như mô tả RANR mới. Source snapshots `.gaml.txt` trong artifacts không phải module cần compile.

## Artifact contract

Mỗi evaluation run có manifest, outcomes, metrics và raw `events/recommendations/messages/packets.jsonl.gz`. Packet body ghi một lần theo sender/sequence; delivery metadata giữ thông tin từng link. Gzip chỉ nén lưu trữ, communication bytes vẫn tính payload JSON trên mô hình mạng.

Log được ghi append trong lúc chạy để giới hạn bộ nhớ. Manifest chuyển sang complete sau settlement và kiểm tra source chưa thay đổi; artifacts có SHA256. Run khác cấu hình hoặc source không được ghi đè. Checkpoint chỉ dùng pickle do chính pipeline tạo trong workspace.

Source/config/calibration được khóa trước training. Code thay đổi giữa run làm run không đủ điều kiện nghiệm thu; smoke cũ trong quá trình phát triển không dùng làm bằng chứng nghiên cứu.
