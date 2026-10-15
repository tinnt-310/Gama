"""Render the documented GAML flow into SVG, PNG, PDF and editable Mermaid.

Run from the project root: .venv/bin/python docs/flowcharts/build_flowcharts.py
Only documentation artifacts are written. No simulation is started.
"""

from pathlib import Path
import hashlib
import json
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET

from graphviz import Digraph
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
DIAGRAMS = []
COLORS = {
    "process": ("box", "#EAF2FF", "#4367AA"),
    "station": ("box", "#E6F5EF", "#31816A"),
    "decision": ("diamond", "#FFF4D6", "#A77822"),
    "data": ("note", "#F0EBFA", "#77609D"),
    "end": ("ellipse", "#FCE9E9", "#A85555"),
    "start": ("ellipse", "#EAF2FF", "#4367AA"),
    "note": ("note", "#F1F3F6", "#7A8291"),
    "ideal": ("box", "#FFF0E5", "#AA7143"),
}


def diagram(key, title, description, sources, nodes, edges):
    DIAGRAMS.append(dict(key=key, title=title, description=description,
                         sources=sources, nodes=nodes, edges=edges))


def chain(*ids):
    return [(a, b, "") for a, b in zip(ids, ids[1:])]


diagram("01_overview", "01 · Toàn bộ vòng đời hệ thống",
    "Luồng logic tổng thể. Các reflex GAMA chạy theo lịch của simulator; sơ đồ không áp đặt một thứ tự mới cho mọi reflex trong một tick.",
    ["models/main.gaml", "models/Mobility.gaml", "models/Recommendation.gaml", "models/ChargingService.gaml", "models/Coordination.gaml"], [
    ("boot", "Bắt đầu experiment", "start"),
    ("init", "Nạp cấu hình, seed, step và giờ bắt đầu\nNạp GIS; tạo graph, access nodes, 11 trạm và xe", "process"),
    ("out", "Tạo thư mục output riêng\nGhi config / input manifest nếu có", "data"),
    ("tick", "Thời gian mô phỏng tiến theo step\nCập nhật lịch xe, rush, giao thông và SOC", "process"),
    ("need", "EV idle/completed, SOC < 30%\nvà chưa có nhu cầu / chưa sạc?", "decision"),
    ("req", "begin_request: tạo request_id\nState=requested; tắt home charging; reset session", "process"),
    ("due", "Tới coordination epoch\nvà coordination_enabled?", "decision"),
    ("mode", "runtime_mode?", "decision"),
    ("rec", "RECOMMENDATION_RUNTIME\nForecast → candidate → query → ranking\nSơ đồ 02–06", "process"),
    ("choice", "EVChoice chọn hành động / trạm\nSơ đồ 07", "process"),
    ("picked", "Đã chọn trạm hợp lệ?", "decision"),
    ("pending", "Giữ requested/deferred\nThử lại ở epoch tiếp theo", "process"),
    ("ideal", "IDEAL_COORDINATED_ASSIGNMENT\nSnapshot → PDHG → GKPS → repair → hard commit\nSơ đồ 10", "ideal"),
    ("travel", "Di chuyển thực tế tới access node trạm\nTrừ SOC theo quãng đường thực tế", "process"),
    ("alive", "Xe tới trạm hợp lệ\nvà chưa terminal?", "decision"),
    ("arrival", "Actual arrival: xác nhận đúng trạm, đúng thời điểm\nTính lại energy demand; ghi observation local", "station"),
    ("fifo", "Enqueue FIFO → cấp cổng → tích phân sạc\nChỉ arrival mới thêm physical workload\nSơ đồ 08", "station"),
    ("done", "Session completed\nGiải phóng cổng; EV tiếp tục lịch hoạt động", "end"),
    ("failure", "Cancelled / stranded / agent bị xóa\nGhi terminal một lần; cleanup ledger, queue, cổng", "end"),
    ("logs", "Xuất events, recommendation, forecast, communication\nSnapshot station/status; population; thống kê cumulative", "data"),
    ("feedback", "Actual arrivals → history tại từng trạm\nClosed bins / nhãn trưởng thành → forecast tương lai", "station"),
    ("limits", "Recommendation không phải reservation\nKhông re-recommend xe en_route\nKhông optimizer choices toàn thành phố", "note"),
    ("offline", "Đánh giá offline: actual T, W, T+W, energy\nCompleted/unfinished; prediction error; herding", "data"),
], chain("boot", "init", "out", "tick", "need") + [
    ("need", "req", "Có"), ("need", "due", "Không"), ("req", "due", ""),
    ("due", "tick", "Chưa"), ("due", "mode", "Có"),
    ("mode", "rec", "Recommendation"), ("mode", "ideal", "Ideal benchmark"),
    ("rec", "choice", ""), ("choice", "picked", ""),
    ("picked", "pending", "Chưa"), ("pending", "tick", ""),
    ("picked", "travel", "Có"), ("ideal", "travel", "Sau hard commit"),
    ("travel", "alive", ""), ("alive", "travel", "Chưa đến; còn hợp lệ"),
    ("alive", "failure", "Hủy / hết pin / bị xóa"), ("alive", "arrival", "Đúng arrival"),
    ("arrival", "fifo", ""), ("fifo", "done", "Hoàn tất"), ("fifo", "failure", "Hủy / bị xóa"),
    ("arrival", "feedback", "Dữ liệu quan sát"), ("feedback", "rec", "Epoch tương lai"),
    ("done", "tick", "Nhu cầu mới có thể phát sinh"),
    ("rec", "limits", "Chú thích"), ("done", "logs", ""), ("failure", "logs", ""),
    ("logs", "offline", ""),
])

diagram("02_epoch", "02 · Barrier của một đợt recommendation",
    "Batch mặc định 60 giây. Tất cả recommendations được tạo trước vòng EVChoice; không phân bổ quota hoặc matching giữa các xe.",
    ["models/Recommendation.gaml"], [
    ("begin", "recommendation_epoch tới hạn", "start"),
    ("init", "Đã initialize_recommendation?", "decision"),
    ("setup", "Kiểm tra mode / backend / weights / trace\nTạo neighbor graph; xuất config", "process"),
    ("at", "epoch_min = time / 60\nBắt đầu đo runtime máy", "process"),
    ("receive", "Mọi trạm: nhận packet đã tới hạn giao\nreceive_available_forecasts", "station"),
    ("issue", "Trạm tới next_forecast_min:\nmature labels → issue_station_forecast\nĐặt lần phát tiếp sau một bin", "station"),
    ("pending", "Lấy pending EVs: requested hoặc deferred\nKhông lấy en_route, waiting, charging", "process"),
    ("more", "Còn EV chưa tạo recommendation?", "decision"),
    ("generate", "generate_recommendation(EV)\nCandidate → station query → rank → lưu result", "process"),
    ("barrier", "BARRIER: đã tạo xong recommendations\ncho toàn bộ pending EVs", "process"),
    ("morechoice", "Còn EV chưa xử lý EVChoice?", "decision"),
    ("choice", "execute_ev_choice(EV)\nCó thể chọn, trì hoãn hoặc dùng trace", "process"),
    ("export", "Cộng runtime; export_recommendations\nXuất candidate, unavailable, forecast / comm diagnostics", "data"),
    ("end", "Hẹn recommendation epoch tiếp theo", "end"),
    ("warning", "Xe trước chọn trạm không sửa forecast cho xe sau\nNhiều xe giống nhau vẫn có thể cùng chọn một trạm", "note"),
], [("begin", "init", ""), ("init", "setup", "Chưa"), ("init", "at", "Rồi"), ("setup", "at", "")] +
    chain("at", "receive", "issue", "pending", "more") + [
    ("more", "generate", "Có"), ("generate", "more", "EV tiếp"),
    ("more", "barrier", "Không"), ("barrier", "morechoice", ""),
    ("morechoice", "choice", "Có"), ("choice", "morechoice", "EV tiếp"),
    ("morechoice", "export", "Không"), ("export", "end", ""),
    ("barrier", "warning", "Hệ quả"),
])

diagram("03_candidates", "03 · Feasible candidates và thông tin tại ETA",
    "Feasible về route, hardware và reserve khác với available về waiting information. TOP_K giữ K trạm theo ETA trước khi ranking.",
    ["models/Coordination.gaml", "models/Recommendation.gaml"], [
    ("start", "build_candidates(EV) tại vị trí / SOC hiện tại", "start"),
    ("clear", "Reset candidate arrays\nDuyệt station theo index", "process"),
    ("more", "Còn station?", "decision"),
    ("hardware", "Compatible và có installed ports?", "decision"),
    ("route", "route_forecast trên road graph\nD_mét, T_phút; ETA = epoch + T\nSnapshot hoặc nominal speed", "process"),
    ("path", "Có route hợp lệ?", "decision"),
    ("reserve", "E_current − c × D_km ≥ B × reserve_SOC / 100?", "decision"),
    ("add", "Giữ station, route distance và ETA", "process"),
    ("sort", "Sort candidates theo ETA\nALL_FEASIBLE: giữ tất cả\nTOP_K: giữ tối đa max_candidates", "process"),
    ("any", "Có feasible candidate?", "decision"),
    ("defer", "State=deferred nếu chưa deferred\nUnavailable: no_feasible_candidate", "end"),
    ("energy", "E_travel = c × D_km\nE_arrival = E_current − E_travel\nTarget SOC: E_req = max(0, B × target/100 − E_arrival)\nd_nm = 60 × E_req / (eta_ref × P_ref)", "process"),
    ("options", "Reset received_station_options\nDuyệt từng candidate", "process"),
    ("next", "Còn candidate chưa query?", "decision"),
    ("info", "information_mode?", "decision"),
    ("live", "LIVE: station.predict_waiting(epoch, ETA − epoch)\nDùng state vật lý hiện tại tại trạm", "station"),
    ("limited", "LIMITED: đọc advertised_waiting snapshot\nslot = ceil(age + ETA_offset − epsilon)\nKhông đọc lại queue thật", "station"),
    ("valid", "Packet / slot / waiting hợp lệ\nvà waiting ≥ 0?", "decision"),
    ("keep", "Giữ option: [T, D_km, E_travel, W_pred]\nETA, E_req, d_nm, status, snapshot age\nReplay error / count / spread", "data"),
    ("available", "Có option available?", "decision"),
    ("unknown", "Unavailable: no_valid_station_information\nKhông gán unknown waiting thành 0", "end"),
    ("rank", "Gửi options hợp lệ tới ranking\nSơ đồ 04", "end"),
], chain("start", "clear", "more") + [
    ("more", "hardware", "Có"), ("hardware", "more", "Không: bỏ trạm"),
    ("hardware", "route", "Có"), ("route", "path", ""), ("path", "more", "Không"),
    ("path", "reserve", "Có"), ("reserve", "more", "Không"), ("reserve", "add", "Có"),
    ("add", "more", "Trạm tiếp"), ("more", "sort", "Hết"), ("sort", "any", ""),
    ("any", "defer", "Không"), ("any", "energy", "Có"),
    ("energy", "options", ""), ("options", "next", ""), ("next", "info", "Có"),
    ("info", "live", "LIVE"), ("info", "limited", "LIMITED"),
    ("live", "valid", ""), ("limited", "valid", ""),
    ("valid", "next", "Không: bỏ option"), ("valid", "keep", "Có"), ("keep", "next", ""),
    ("next", "available", "Hết"), ("available", "unknown", "Không"), ("available", "rank", "Có"),
])

diagram("04_ranking", "04 · Pareto và minimax normalized regret",
    "Quy tắc chính không học alpha. Nhánh đối chứng nearest/eta chọn trên toàn bộ options hợp lệ, các policy còn lại chọn trên Pareto set.",
    ["models/StationForecast.gaml", "models/Recommendation.gaml"], [
    ("start", "Options hợp lệ: f_m = [T, D, E_travel, W_pred]\nMọi tiêu chí đều tối thiểu hóa", "start"),
    ("check", "Kiểm tra criteria không âm, normalization / method\nWeighted / monetary: 4 weights ≥ 0, tổng > 0", "process"),
    ("pareto", "So sánh từng option với tất cả competitors\nDominated khi competitor không tệ hơn mọi tiêu chí\nvà tốt hơn ít nhất một; có numeric tolerance", "process"),
    ("flags", "Đánh dấu pareto=true/false\nGiữ cả options dominated để audit", "data"),
    ("norm", "normalization_mode?", "decision"),
    ("feasible", "feasible (mặc định): min/max\ntrên mọi options có thông tin hợp lệ", "process"),
    ("front", "pareto (ablation): min/max\nchỉ trên Pareto set", "process"),
    ("regret", "l_j = min f_j; u_j = max f_j\nRange ≤ epsilon: r_mj = 0\nNgược lại: r_mj = (f_mj − l_j) / (u_j − l_j)", "process"),
    ("method", "recommendation_method?", "decision"),
    ("minimax", "minimax: R_m = max_j r_mj\nEligible = Pareto set", "process"),
    ("nearest", "nearest: score = D_km\neta: score = T_phút\nEligible = mọi valid options", "process"),
    ("other", "time_wait: score = T + W\nweighted_sum: score = sum alpha_j × r_mj\nmonetary: score = sum alpha_j × f_mj\nEligible = Pareto set", "process"),
    ("best", "Chọn score nhỏ nhất\nTolerance score = 1e−10", "process"),
    ("tie", "Nếu hòa: minimax / weighted / time_wait / monetary\nchọn T+W nhỏ nhất, rồi station.index nhỏ nhất\nNearest / eta: hòa thì station.index nhỏ nhất", "process"),
    ("result", "Đánh dấu winner, alternative ranks\nLưu Pareto flags, regrets, score_method", "data"),
    ("record", "Tăng recommendation_version\nLưu recommendation và candidate rows\nChưa đổi destination / queue / inbound", "end"),
    ("note", "Min/max thay đổi theo candidate set\nKhông phải weights được train\nMinimax từng EV không tối ưu tổng waiting thành phố", "note"),
], chain("start", "check", "pareto", "flags", "norm") + [
    ("norm", "feasible", "feasible"), ("norm", "front", "pareto"),
    ("feasible", "regret", ""), ("front", "regret", ""), ("regret", "method", ""),
    ("method", "minimax", "Chính"), ("method", "nearest", "B1 / B2"), ("method", "other", "Đối chứng khác"),
    ("minimax", "best", ""), ("nearest", "best", ""), ("other", "best", ""),
    ("regret", "note", "Ý nghĩa"),
] + chain("best", "tie", "result", "record"))

diagram("05_waiting", "05 · Waiting prediction: B3, B4, B4-N và fallback",
    "Tất cả modes bắt đầu từ physical shadow. B4/B4-N chọn historical scenarios đại diện rồi replay, không tạo reservation hay thêm choices vào tải vật lý.",
    ["models/ChargingService.gaml", "models/StationForecast.gaml"], [
    ("start", "predict_waiting(issued, ETA_offset ≥ 0)", "start"),
    ("cached", "Waiting cache có đúng key?\nIssued, ETA_offset, forecast, estimator, fallback", "decision"),
    ("returncache", "Trả cached result; tăng cache_hits", "end"),
    ("shadow", "shadow_port_state: rates và free_at\nCổng rảnh + phiên đang sạc + physical FIFO\nKhông cộng inbound / intention / recommendations", "station"),
    ("b3", "Discrete shadow không thêm future arrivals\nW_physical = max(0, min free_at − ETA_offset)\nKhông có cổng: −1", "station"),
    ("mode", "waiting_forecast_mode = B3?", "decision"),
    ("physical", "Result: W_physical; status=physical_only", "data"),
    ("horizon", "B4 / B4-N: H = max(1, ceil(ETA_offset / 5))\nreplay_windows(issued, H)", "station"),
    ("history", "Đủ closed bins, observed arrivals\nvà history cho H?", "decision"),
    ("cold", "Giữ W_physical\nstatus=cold_start / insufficient_horizon", "data"),
    ("forecast", "B4: local moving average\nB4-N: workload forecast đã issue, nếu còn coverage\nHorizon thiếu coverage dùng local value", "station"),
    ("scan", "Duyệt history windows đã hoàn tất trước query\nTính normalized RMS mismatch với forecast\nScale = max(1, local_value)", "station"),
    ("calibrated", "Replay similarity threshold ≥ 0?", "decision"),
    ("unconfigured", "Giữ W_physical\nstatus=ood_threshold_not_calibrated", "data"),
    ("accepted", "Có window mismatch ≤ threshold?", "decision"),
    ("ood", "Giữ W_physical\nstatus=out_of_distribution", "data"),
    ("scenarios", "Chọn tối đa replay_scenarios windows tốt nhất\nGiữ arrival offsets và energy từng session\nKhông scale energy / sinh thêm xe", "station"),
    ("replay", "Mỗi scenario: chạy discrete shadow trên bản copy\nArrivals ≤ ETA được xử lý trước probe\nFIFO; tick rounding; earliest port, hòa chọn power cao", "station"),
    ("mean", "W_pred = mean(W_s); status=replay\nscenario_count; spread = max(W_s) − min(W_s)", "data"),
    ("fluidgate", "Mode khác B3 và:\nestimator=fluid HOẶC\n(status=OOD và fallback=fluid)?", "decision"),
    ("fluid", "fluid_waiting từ LOCAL baseline\nResidual capacity và causal backlog\nKhông dùng corrected workload của B4-N", "station"),
    ("fluidvalid", "Fluid đủ horizon: W_fluid ≥ 0?", "decision"),
    ("fluidok", "W = max(W_physical, W_fluid)\nstatus=fluid_approximation / ood_fluid_fallback", "data"),
    ("fluidfail", "W = −1; status=fluid_horizon_exhausted\nOption sẽ unavailable", "data"),
    ("save", "Lưu cache / last_wait_result; cập nhật counters\nTrả W, status, issued_at, replay error / count / spread", "end"),
], [("start", "cached", ""), ("cached", "returncache", "Có"), ("cached", "shadow", "Không")] +
    chain("shadow", "b3", "mode") + [
    ("mode", "physical", "Có"), ("physical", "save", ""), ("mode", "horizon", "Không"),
    ("horizon", "history", ""), ("history", "cold", "Không"), ("cold", "fluidgate", ""),
    ("history", "forecast", "Có"), ("forecast", "scan", ""), ("scan", "calibrated", ""),
    ("calibrated", "unconfigured", "Không"), ("unconfigured", "fluidgate", ""),
    ("calibrated", "accepted", "Có"), ("accepted", "ood", "Không"), ("ood", "fluidgate", ""),
    ("accepted", "scenarios", "Có"), ("scenarios", "replay", ""), ("replay", "mean", ""),
    ("mean", "fluidgate", ""), ("fluidgate", "save", "Không"), ("fluidgate", "fluid", "Có"),
    ("fluid", "fluidvalid", ""), ("fluidvalid", "fluidok", "Có"), ("fluidvalid", "fluidfail", "Không"),
    ("fluidok", "save", ""), ("fluidfail", "save", ""),
])

diagram("06_learning", "06 · Station-local history, phát forecast và ridge online",
    "B4 cập nhật thống kê, B4-N có thể học correction theo horizon. Các nhãn chỉ dùng sau khi target bin đóng; features được giữ từ thời điểm phát dự báo.",
    ["models/ChargingService.gaml", "models/StationForecast.gaml", "models/Recommendation.gaml"], [
    ("obs", "Actual arrival tại station\nobserve_arrival(at, E_req_actual)", "start"),
    ("bin", "Lưu (at, energy)\nY_bin += 60 × energy / (eta_ref × P_ref)\nBin vắng có workload = 0", "station"),
    ("epoch", "Station tới kỳ phát forecast (bin 5 phút)\nPacket cũ đã được delivery barrier xử lý", "start"),
    ("mature", "mature_forecasts: chọn labels\ncó target_bin < closed bin index", "station"),
    ("score", "Lấy actual workload đã quan sát\nScore local / corrected forecasts đã phát trước đó", "data"),
    ("train", "B4-N và correction_enabled?", "decision"),
    ("update", "Mỗi horizon: khởi tạo A=lambda I, b=0 nếu cần\nDùng phi và baseline đã lưu lúc issue\ny = (actual − baseline) / 30\nA += phi phiᵀ; b += phi y; count += 1", "station"),
    ("remove", "Bỏ labels đã trưởng thành khỏi pending list", "station"),
    ("prune", "Cắt observation history theo retention\n576 bins × 5 phút ≈ 48 giờ", "station"),
    ("local", "local_value = mean của tối đa 12 closed bins\nChưa có bin đóng: 0\nV1 dùng cùng mean cho các horizons", "station"),
    ("h", "Duyệt horizon h = 0 ... 23", "station"),
    ("features", "phi = [1, neighbor_mean/30, (neighbor−local)/30,\nmean_packet_age_bins, missing_fraction, h/24]\nChỉ đọc packets đã nhận và còn phủ horizon", "station"),
    ("gate", "B4-N, enabled, có model\nvà count ≥ max(50, 5p), p=6?", "decision"),
    ("baseline", "corrected = local_value", "station"),
    ("ridge", "Giải A w = b bằng Gaussian elimination\ncorrected = max(0, local_value + 30 × wᵀphi)", "station"),
    ("label", "Lưu issued forecast và pending label\nIssued_at, target bin, horizon, phi, local, corrected", "data"),
    ("more", "Còn horizon?", "decision"),
    ("cache", "Clear waiting_cache và replay_cache", "station"),
    ("neighbor", "Forecast mode B4-N?", "decision"),
    ("packet", "Gửi neighbor packet: LOCAL workload vector\nResidual capacity, unit, issued/deliver timestamps\nDegree=3 trước đối xứng; không raw EV queue", "station"),
    ("limited", "Information mode LIMITED?", "decision"),
    ("curve", "Tính waiting curve offsets 0 ... 120 phút\nQua predict_waiting; giữ statuses và issued_at", "station"),
    ("end", "Forecast sẵn cho queries / epochs tiếp theo\nGhi forecast và communication diagnostics", "end"),
    ("note", "Capacity có trong packet nhưng chưa vào phi\nRidge học workload correction, không học weights cost\nCorrection mặc định tắt; B4 replay threshold mặc định −1", "note"),
], [("obs", "bin", ""), ("bin", "mature", "Dữ liệu tại kỳ phát sau")] +
    chain("epoch", "mature", "score", "train") + [
    ("train", "update", "Có"), ("train", "remove", "Không"), ("update", "remove", ""),
] + chain("remove", "prune", "local", "h", "features", "gate") + [
    ("gate", "baseline", "Không"), ("gate", "ridge", "Có"),
    ("baseline", "label", ""), ("ridge", "label", ""), ("label", "more", ""),
    ("more", "h", "Có"), ("more", "cache", "Không"), ("cache", "neighbor", ""),
    ("neighbor", "packet", "Có"), ("neighbor", "limited", "Không"), ("packet", "limited", ""),
    ("limited", "curve", "Có"), ("limited", "end", "Không"), ("curve", "end", ""),
    ("features", "note", "Giới hạn cài đặt"),
])

diagram("07_choice_arrival", "07 · EVChoice, hành trình và actual arrival",
    "Chỉ apply_station_choice mới đổi destination trong recommendation runtime. Trace thiếu là lỗi hợp đồng; trace chưa đến thời điểm hoặc không chọn thì tiếp tục chờ.",
    ["models/Recommendation.gaml", "models/ChargingService.gaml"], [
    ("start", "execute_ev_choice(EV)", "start"),
    ("valid", "Có options và state requested/deferred?", "decision"),
    ("wait", "Chưa áp destination\nGiữ pending cho epoch tiếp theo", "end"),
    ("mode", "ev_choice_mode?", "decision"),
    ("follow", "FOLLOW: lấy recommended option", "process"),
    ("self", "SELF_INTERESTED: rank lại options\nTheo personal_choice_method / personal_weights", "process"),
    ("trace", "TRACE: yêu cầu trace cho request\nLấy record mới nhất có time ≤ epoch", "process"),
    ("tracestatus", "Trace record hợp lệ và chọn station\ntrong options hiện có?", "decision"),
    ("traceerror", "Trace thiếu: CHOICE_TRACE_MISSING\nAssertion; không tạo trace giả", "end"),
    ("intention", "Nếu publish_intention: gửi intention audit\nKhông giữ cổng / thêm queue / cộng vào forecast", "data"),
    ("apply", "apply_station_choice: đặt current/chosen_station\nChoice time, ETA, predicted energy / wait\nReset distance; state=en_route; ghi choice / en_route", "process"),
    ("path", "Native compute_path tới station access node\nKhông giữ candidate path object bất biến", "process"),
    ("drive", "Drive theo road graph và congestion thực tế\nD = max(0, remaining_before − remaining_after)\nSOC -= 100 × c × D_m / (1000 × B)", "process"),
    ("terminal", "Hủy / agent bị xóa / hết pin?", "decision"),
    ("cleanup", "Terminal event một lần; cleanup\nQueue, cổng, intention, pending metadata\nStranded: unregister và die", "end"),
    ("reached", "Đã tới access node đúng trạm\nvà final_target=nil?", "decision"),
    ("due", "Nếu vừa đi tới: station_arrival_due=(time+step)/60\nMaterialize arrival khi clock đạt boundary", "process"),
    ("enqueue", "enqueue_arrival kiểm live EV, đúng current_station\nState hợp lệ, distance < 2m, chưa arrival lần trước", "station"),
    ("demand", "Xóa intention / inbound nếu có; clear waiting cache\nTarget SOC: tính lại E_req từ SOC thực tế tại arrival", "station"),
    ("observe", "Ghi arrival time và local observation\nState=waiting; arrived_customer += 1\nThêm cuối FIFO; ghi arrival event", "station"),
    ("fifo", "process_queue; cập nhật peak_queue\nSơ đồ 08", "end"),
    ("noroute", "EV en_route không tự được re-recommend\nQueue tăng giữa hành trình không tự đổi destination", "note"),
], [("start", "valid", ""), ("valid", "wait", "Không"), ("valid", "mode", "Có"),
    ("mode", "wait", "DEFER"), ("mode", "follow", "FOLLOW"), ("mode", "self", "SELF"),
    ("mode", "trace", "TRACE"), ("trace", "tracestatus", ""),
    ("tracestatus", "traceerror", "Thiếu trace"), ("tracestatus", "wait", "Chưa tới giờ / trạm rỗng / ngoài options"),
    ("tracestatus", "intention", "Có"), ("follow", "intention", ""), ("self", "intention", ""),
] + chain("intention", "apply", "path") + [
    ("path", "enqueue", "Đã ở đúng access node"), ("path", "drive", "Cần di chuyển"),
    ("drive", "terminal", ""), ("terminal", "cleanup", "Có"), ("terminal", "reached", "Không"),
    ("reached", "drive", "Chưa đến"), ("reached", "due", "Tới cuối path"), ("due", "enqueue", "Clock đạt arrival_due"),
    ("drive", "noroute", "Behavior hiện tại"),
] + chain("enqueue", "demand", "observe", "fifo"))

diagram("08_physical", "08 · Physical FIFO, cấp cổng và tích phân năng lượng",
    "Arrival có thể gọi process_queue ngay. Service tick cũng reconcile, hoàn tất phiên cũ, dispatch rồi tích phân; completion_pending ngăn giải phóng cổng trước finish time.",
    ["models/ChargingService.gaml"], [
    ("arrival", "Arrival hợp lệ → gọi process_queue", "start"),
    ("tick", "service_tick → advance_service", "start"),
    ("reconcile", "Clear waiting cache; reconcile_sessions\nDọn dead sessions, terminal events và cổng", "station"),
    ("pending", "Phiên completion_pending\nvà clock ≥ service_finish?", "decision"),
    ("finish", "stop_charging: completed event một lần\nGiải phóng cổng; served_customer += 1\nneeds_charging=false; current_station=nil", "station"),
    ("queue", "process_queue: reconcile và lọc FIFO hợp lệ", "station"),
    ("free", "Queue còn xe và có cổng rảnh?", "decision"),
    ("dispatch", "Lấy EV đầu FIFO\nChọn cổng rảnh mạnh nhất: 250,180,150,60,30,11\nOccupy port; state=charging; service_start=clock", "station"),
    ("waitmetric", "W_actual = service_start − arrival_time\nTăng started; ghi service_started event", "data"),
    ("waiters", "EV còn waiting: cập nhật elapsed waiting\nChưa start thì waiting cuối cùng chưa biết", "station"),
    ("integrate", "Với mỗi EV charging chưa completion_pending:\nE_remaining = min(E_req − E_delivered, battery headroom)\nDelta_E = min(max(0,E_remaining), eta × P × step/3600)", "station"),
    ("soc", "E_delivered += Delta_E\nSOC += 100 × Delta_E / B; cap 100%\nGrid_kWh += Delta_E / eta\nCharging_min += 60 × Delta_E / (eta × P)", "station"),
    ("complete", "Đủ requested energy\nhoặc SOC đạt 100%?", "decision"),
    ("mark", "service_finish = clock + charge_seconds/60\ncompletion_pending=true\nChưa release port trong integration interval này", "station"),
    ("next", "Lưu physical session snapshot\nChờ service tick tiếp theo", "end"),
    ("rates", "B=60 kWh, eta=0.9: SOC tăng mỗi phút\n11 kW: 0.275 điểm %; 30: 0.75; 60: 1.5\n150: 3.75; 180: 4.5; 250: 6.25\nCuối phiên cap theo demand; chưa có taper", "note"),
], [("tick", "reconcile", ""), ("reconcile", "pending", ""),
    ("pending", "finish", "Có"), ("finish", "queue", ""), ("pending", "queue", "Không"),
    ("arrival", "queue", ""), ("queue", "free", ""), ("free", "dispatch", "Có"),
    ("dispatch", "waitmetric", ""), ("waitmetric", "free", "EV tiếp"),
    ("free", "waiters", "Không; khi trong service tick"),
] + chain("waiters", "integrate", "soc", "complete") + [
    ("complete", "mark", "Có"), ("mark", "next", ""), ("complete", "next", "Không"),
    ("next", "tick", "Tick sau"), ("soc", "rates", "Ví dụ default"),
])

diagram("09_rush", "09 · Giờ cao điểm: tăng hoạt động và thêm 30% xe",
    "Đây là demand generation của simulator, không phải một bước tối ưu của recommendation. Xe nền và xe bổ sung có quy tắc khác nhau khi hết rush.",
    ["models/main.gaml"], [
    ("clock", "Đồng hồ lịch: start_hour + elapsed / 3600\nCửa sổ sáng 05:30–07:30; chiều 17:00–20:00\nReflex dùng các điều kiện clock và cờ ngày", "start"),
    ("rush", "rush và have_rush?", "decision"),
    ("new", "Chưa spawn trong window_id hiện tại?", "decision"),
    ("budget", "Mỗi loại: extra_cap=floor(base × rush_extra_percent/100)\nnew_count=max(0,extra_cap − extras còn sống)\nSpawn phần thiếu một lần / window", "process"),
    ("numbers", "30% default: +900 car, +341 taxi EV, +178 private EV\nTổng thêm 1,419 xe, gồm 519 EV\nTối đa cohort: 6,151 xe, gồm 2,251 EV", "data"),
    ("base", "Xe nền đang nghỉ, không request / charging\nChưa được kích hoạt trong window\nĐủ điều kiện giờ departure / home / destination?", "decision"),
    ("depart", "Tái dùng lịch cá nhân để phát chuyến\nSáng tới work; chiều tới home\nKhông thay destination EV đang đi sạc", "process"),
    ("active", "Di chuyển / SOC / request theo lifecycle chung\nGhi population và rush_departures", "process"),
    ("end", "Ngoài rush hoặc have_rush=false\nDuyệt toàn bộ extras", "process"),
    ("protected", "Extra EV còn needs_charging\nhoặc is_charging?", "decision"),
    ("retire", "Unregister và die trong tick cleanup\nXe nền không bị xóa bởi bước này", "end"),
    ("hold", "Giữ EV; thêm vào charge_rush_vehi\nCho hoàn thành hoặc hủy session", "process"),
    ("completed", "EV đã chết hoặc không còn needs_charging?", "decision"),
    ("later", "Retire EV còn sống; bỏ khỏi tracking list\nSurvivors ở window sau đã được trừ khỏi extra_cap", "end"),
], [("clock", "rush", ""), ("rush", "new", "Có"), ("new", "budget", "Có"),
    ("budget", "numbers", ""), ("numbers", "base", ""), ("new", "base", "Không"),
    ("base", "depart", "Có"), ("depart", "active", ""), ("base", "active", "Không"),
    ("active", "clock", "Tick tiếp"), ("rush", "end", "Không"), ("end", "protected", ""),
    ("protected", "retire", "Không"), ("protected", "hold", "Có"), ("hold", "completed", ""),
    ("completed", "hold", "Chưa"), ("completed", "later", "Có"),
])

diagram("10_ideal", "10 · Ideal coordinated assignment — benchmark riêng",
    "Nhánh này phối hợp nhiều EV rồi hard commit. LB/UB chỉ thuộc surrogate của snapshot đóng băng; không chứng nhận actual FIFO waiting hoặc recommendation tối ưu.",
    ["models/Coordination.gaml", "models/ConvexAssignment.gaml"], [
    ("start", "coordinate_batch\nAssert runtime=IDEAL_COORDINATED_ASSIGNMENT", "start"),
    ("refresh", "refresh_inbound: ETA từ remaining committed route\nLấy requested/deferred EVs; build feasible candidates", "ideal"),
    ("batch", "Batch có EV với candidate hợp lệ?", "decision"),
    ("empty", "Không solve; chờ epoch sau", "end"),
    ("snapshot", "Đóng băng snapshot edges, station capacity, inbound\nHorizon phủ max ETA + 120 phút tail\nDemand d_nm / reference units; cost T hoặc time_energy", "ideal"),
    ("objective", "A_mh = inbound + sum d_nm × x_nm\nq_mh = A_mh + max(0,q_prev − C_mh)\nJ_theta = sum c_nm x_nm + (Delta/d_ref)sum q\n+ theta sum x_nm ln x_nm; row sum x=1", "ideal"),
    ("policy", "assignment_policy?", "decision"),
    ("nearest", "nearest hard-assignment baseline\nĐặt x theo road distance; evaluate / project; z=xp\nBỏ qua proposed PDHG / rounding / repair", "ideal"),
    ("prepare", "proposed: prepare_solver\nEpigraph Q, inequality duals, equality dual copies\ntau=sigma=0.99 / norm estimate", "ideal"),
    ("iter", "Một iteration đồng bộ:\nTrao đổi xbar → update duals → entropy prox x\nClamp Q → extrapolate bar=2new−old", "ideal"),
    ("check", "Tới kỳ check (20 iterations)?", "decision"),
    ("evaluate", "Project row simplex để lấy xp khả thi\nRecompute causal profile; objective / LB / gap\nPrimal residual và consensus residual", "ideal"),
    ("converged", "Residual ≤ 1e−6; consensus ≤ 1e−6\nrelative gap ≤ 1e−7?", "decision"),
    ("yes", "solver_status=converged", "ideal"),
    ("budget", "Còn iteration budget?\nDefault 20,000", "decision"),
    ("timeout", "solver_status=timeout\nVẫn recovery từ projected xp; không gọi tối ưu", "ideal"),
    ("project", "recover_integer: project_assignment\nTạo components theo shared candidate graph\nĐại diện component = station index nhỏ nhất", "ideal"),
    ("round", "GKPS dependent rounding, RNG riêng\nEven cycle / forest path, alternating +/-\nMỗi bước giảm fractional edges; mỗi EV chọn một trạm", "ideal"),
    ("repair", "Exact repair: xét one-EV relocation\nTop five trước, rồi mọi moves còn lại\nExact delta < −1e−6 thì accept; lặp đến hết improving move", "ideal"),
    ("audit", "Integer UB không tăng sau repair; LB ≤ UB\nLưu status, bounds, residual, x/xp/z và RNG audit", "data"),
    ("commit", "commit_assignment chỉ dùng final z=1\nGhi inbound workload / ETA / EV metadata\nState assigned → en_route; đặt destination / path", "ideal"),
    ("physical", "Actual arrival xóa inbound trước enqueue\nDùng chung physical FIFO và charging\nSơ đồ 07–08", "end"),
    ("limit", "Certificate: frozen surrogate snapshot\nRepair: one-exchange local optimum, không global optimum\nKhông dùng benchmark này chứng nhận recommendation", "note"),
], chain("start", "refresh", "batch") + [
    ("batch", "empty", "Không"), ("batch", "snapshot", "Có"),
] + chain("snapshot", "objective", "policy") + [
    ("policy", "nearest", "nearest"), ("nearest", "audit", ""),
    ("policy", "prepare", "proposed"), ("prepare", "iter", ""), ("iter", "check", ""),
    ("check", "evaluate", "Có"), ("check", "budget", "Chưa"), ("evaluate", "converged", ""),
    ("converged", "yes", "Có"), ("converged", "budget", "Không"),
    ("budget", "iter", "Có"), ("budget", "timeout", "Không"),
    ("yes", "project", ""), ("timeout", "project", ""),
] + chain("project", "round", "repair", "audit", "commit", "physical") + [
    ("audit", "limit", "Phạm vi kết luận"),
])


def mermaid(spec):
    lines = ["flowchart TD"]
    notes = {n[0] for n in spec["nodes"] if n[2] == "note"}
    for key, label, kind in spec["nodes"]:
        label = label.replace("\n", "<br/>").replace('"', "#quot;")
        body = f'{{"{label}"}}' if kind == "decision" else f'["{label}"]'
        if kind in {"start", "end"}:
            body = f'(["{label}"])'
        lines.append(f"    n_{key}{body}")
    for a, b, label in spec["edges"]:
        arrow = "-.->" if b in notes else "-->"
        lines.append(f'    n_{a} {arrow}|"{label}"| n_{b}' if label else f"    n_{a} {arrow} n_{b}")
    for kind, (_, fill, stroke) in COLORS.items():
        lines.append(f"    classDef {kind} fill:{fill},stroke:{stroke},color:#17263C;")
        keys = [n[0] for n in spec["nodes"] if n[2] == kind]
        if keys:
            lines.append(f"    class {','.join('n_' + key for key in keys)} {kind};")
    return "\n".join(lines) + "\n"


def verify_graph(spec):
    nodes = {n[0] for n in spec["nodes"]}
    assert len(nodes) == len(spec["nodes"]), spec["key"]
    assert all(a in nodes and b in nodes for a, b, _ in spec["edges"])
    assert all((ROOT / src).is_file() for src in spec["sources"])
    # All nodes must be reachable from at least one entry node.
    reached = {n[0] for n in spec["nodes"] if n[2] == "start"}
    while True:
        updated = reached | {b for a, b, _ in spec["edges"] if a in reached}
        if updated == reached:
            break
        reached = updated
    assert reached == nodes, (spec["key"], nodes - reached)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    sources = sorted({src for spec in DIAGRAMS for src in spec["sources"]})
    fingerprints = {src: hashlib.sha256((ROOT / src).read_bytes()).hexdigest() for src in sources}
    manifest = {"checked_date": "2026-10-09", "source_sha256": fingerprints,
                "renderer": "Graphviz dot", "diagrams": []}
    doc = ["# Flowchart chi tiết hệ thống và thuật toán hiện tại", "",
           "**Đối chiếu mã: 09/10/2026.** Kiến trúc Distributed Observation-Driven Charging Recommendation. "
           "Các sơ đồ diễn tả implementation hiện có, không thay đổi model hoặc đề xuất một policy mới.", "",
           "[Mở PDF toàn bộ 10 sơ đồ](flowcharts/SYSTEM_FLOWCHART_VI.pdf). "
           "Mỗi phần có ảnh để xem ngay, SVG để phóng to và Mermaid/DOT để chỉnh sửa.", "",
           "Luồng chính: **Request → feasible candidates → station-local waiting tại ETA → "
           "Pareto/minimax → recommendation → EVChoice → actual arrival → FIFO charging → local history.**", "",
           "**Cách đọc:** hộp xanh dương là xử lý EV/orchestration; xanh lá là xử lý tại trạm; "
           "hình thoi vàng là điều kiện; tím là dữ liệu/log; cam là benchmark ideal; xám là chú thích. "
           "Nét đứt nối tới chú thích. Đường quay lại thể hiện vòng lặp logic qua iteration, tick hoặc epoch, không gọi đệ quy GAML.", "",
           "## Mục lục", ""]
    for i, spec in enumerate(DIAGRAMS, 1):
        doc.append(f'{i}. [{spec["title"]}](#{spec["key"].replace("_", "-")})')
    doc += ["", "## Các điểm phải giữ khi diễn giải", "",
            "- Recommendation, choice và intention chưa thêm physical queue; actual arrival mới enqueue.",
            "- Cùng đợt: tạo mọi recommendations trước mọi choices. Đây không phải matching hoặc quota capacity.",
            "- B3 loại inbound/intention; B4 dùng history actual arrivals; B4-N correction có gate và mặc định tắt.",
            "- B4 mặc định threshold −1: replay chưa hiệu chỉnh và giữ physical fallback với nhãn rõ ràng.",
            "- Xe en_route chưa được tự động đổi trạm khi queue tăng; herding vẫn có thể xảy ra.",
            "- FIFO/tích phân sạc là physical outcome. Ideal solver dùng surrogate và có pipeline riêng.", ""]
    with tempfile.TemporaryDirectory(prefix="ev-flowcharts-") as temp_dir:
        pdfs = []
        for spec in DIAGRAMS:
            verify_graph(spec)
            graph = Digraph(name=spec["key"], engine="dot")
            graph.attr(rankdir="TB", bgcolor="white", pad="0.3", nodesep="0.34", ranksep="0.46",
                       splines="polyline", fontname="DejaVu Sans", fontsize="18", labelloc="t",
                       label=spec["title"], dpi="130")
            graph.attr("node", fontname="DejaVu Sans", fontsize="12", margin="0.16,0.10",
                       penwidth="1.15", fontcolor="#17263C", style="filled,rounded")
            graph.attr("edge", fontname="DejaVu Sans", fontsize="10", color="#697990",
                       fontcolor="#334762", arrowsize="0.65", penwidth="1.0")
            for key, label, kind in spec["nodes"]:
                shape, fill, stroke = COLORS[kind]
                graph.node(key, label, shape=shape, fillcolor=fill, color=stroke)
            entries = [n[0] for n in spec["nodes"] if n[2] == "start"]
            if len(entries) > 1:
                with graph.subgraph() as entry_row:
                    entry_row.attr(rank="same")
                    for entry in entries:
                        entry_row.node(entry)
            notes = {n[0] for n in spec["nodes"] if n[2] == "note"}
            for a, b, label in spec["edges"]:
                graph.edge(a, b, label=label, style="dashed" if b in notes else "solid")
            dot_path = OUT / (spec["key"] + ".dot")
            dot_path.write_text(graph.source, encoding="utf-8")
            for fmt in ("svg", "png", "pdf"):
                target = (Path(temp_dir) if fmt == "pdf" else OUT) / (spec["key"] + "." + fmt)
                result = subprocess.run(["dot", "-T" + fmt, str(dot_path), "-o", str(target)],
                                        capture_output=True, text=True, check=True)
                if result.stderr.strip():
                    raise RuntimeError(result.stderr)
                if fmt == "pdf":
                    pdfs.append(str(target))
                elif fmt == "svg":
                    tree = ET.parse(target)
                    texts = [element.text for element in tree.iter() if element.tag.endswith("}text")]
                    assert all(label.split("\n")[0] in texts for _, label, _ in spec["nodes"])
            mmd = mermaid(spec)
            (OUT / (spec["key"] + ".mmd")).write_text(mmd, encoding="utf-8")
            with Image.open(OUT / (spec["key"] + ".png")) as preview:
                dimensions = list(preview.size)
                preview.verify()
            manifest["diagrams"].append({"key": spec["key"], "title": spec["title"],
                                         "nodes": len(spec["nodes"]), "edges": len(spec["edges"]),
                                         "png_dimensions": dimensions, "sources": spec["sources"]})
            doc += [f'<a id="{spec["key"].replace("_", "-")}"></a>', "",
                    f'## {spec["title"]}', "", spec["description"], "",
                    f'![{spec["title"]}](flowcharts/{spec["key"]}.png)', "",
                    f'[SVG phóng to](flowcharts/{spec["key"]}.svg) · '
                    f'[Mermaid](flowcharts/{spec["key"]}.mmd) · [Graphviz DOT](flowcharts/{spec["key"]}.dot)', "",
                    "**Nguồn:** " + ", ".join(f'[{Path(src).name}](../{src})' for src in spec["sources"]) + ".", "",
                    "<details>", "<summary>Mã Mermaid để chỉnh sửa</summary>", "", "```mermaid", mmd.rstrip(), "```", "", "</details>", ""]
        subprocess.run(["pdfunite", *pdfs, str(OUT / "SYSTEM_FLOWCHART_VI.pdf")], check=True)
    doc += ["## Phạm vi kiểm tra và cập nhật", "",
            "Đã đối chiếu các nhánh chính với actions/reflex hiện tại: recommendation_batch, build_candidates, "
            "rank_station_options, predict_waiting, issue_station_forecast, execute_ev_choice, "
            "enqueue_arrival, advance_service, rush_hour và coordinate_batch.", "",
            "Sơ đồ 08 gộp các trường hợp dispatch vào một quy trình chung. Arrival gọi process_queue, "
            "còn tích phân năng lượng thuộc service_tick. Sơ đồ 07 thể hiện movement boundary: "
            "arrival không được materialize trước khi movement interval đã kết thúc.", "",
            "Thứ tự các vòng trong sơ đồ 02 là barrier thật trong recommendation_batch. Các sơ đồ còn lại "
            "mô tả dependencies/lifecycle, không thay thế scheduler của GAMA.", "",
            "Bộ ảnh/PDF được render từ cùng graph definitions trong "
            "[build_flowcharts.py](flowcharts/build_flowcharts.py); Mermaid cũng sinh từ cùng nodes/edges. "
            "[Manifest](flowcharts/manifest.json) lưu số nodes/edges và SHA256 của mã được đối chiếu. "
            "Khi source thay đổi, cần cập nhật graph definitions rồi render lại:", "",
            "```bash", ".venv/bin/python docs/flowcharts/build_flowcharts.py", "```", "",
            "Tài liệu đầy đủ về công thức, defaults, metrics và giới hạn: "
            "[SYSTEM_ALGORITHM_FULL_VI.md](SYSTEM_ALGORITHM_FULL_VI.md).", ""]
    document = ROOT / "docs/SYSTEM_FLOWCHART_VI.md"
    document.write_text("\n".join(doc), encoding="utf-8")
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    assert fingerprints == {src: hashlib.sha256((ROOT / src).read_bytes()).hexdigest() for src in sources}
    for ref in re.findall(r"\]\(([^)]+)\)", document.read_text(encoding="utf-8")):
        if ref.startswith("#"):
            assert f'id="{ref[1:]}"' in document.read_text(encoding="utf-8")
        else:
            assert (document.parent / ref).is_file(), ref
    print(json.dumps({"diagrams": len(DIAGRAMS), "nodes": sum(len(d["nodes"]) for d in DIAGRAMS),
                      "edges": sum(len(d["edges"]) for d in DIAGRAMS), "source_files_unchanged": len(sources),
                      "document": str(document), "pdf": str(OUT / "SYSTEM_FLOWCHART_VI.pdf")},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
