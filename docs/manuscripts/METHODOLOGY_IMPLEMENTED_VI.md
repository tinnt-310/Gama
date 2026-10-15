# Mô tả methodology đã triển khai

Đây là phần bổ sung triển khai, không phải kết quả hiệu quả thực nghiệm và không thay thế PDF lịch sử.

Hệ thống dùng GAMA native driving với GIS Nha Trang và11 trạm125 cổng7195kW danh định. Fleet3000 conventional/1000 privateEV/700 taxi tồn tại độc lập charging opportunities. Tần suất0.2/0.8 là giả định development; activation kiểm tra SOC<30%, availability của EV và không chồng phiên. Inbound tối đa30% từng loại vào dần qua gates có tuyến kiểm chứng.

Một trạm ra quyết định từ trạng thái cục bộ, packet đã nhận, exposure đã biết và prior calibration. Peer state có timestamp/version/TTL. Heartbeat và event-triggered updates dùng chung transport có delay/loss/duplicate/partition. Token do EV trình tại arrival cho phép đối soát; phần không định danh dùng conditional probabilistic approximation đã công bố.

Policy sử dụng5 tiêu chí travel+charge, mean waiting, P95 waiting, marginal externality và uncertainty. Weights softmax có20 tham số độc lập; Fixed-Weights4. No-Prediction dùng snapshot và H=0, không forecast tương lai; No-P2P không giao tiếp giữa trạm. Recommendation không tạo reservation hoặc assignment; EV tự quyết định.

CMA-ES fitness được tính trong GAMA từ objective opportunity-normalized có thành phần thời gian phục vụ, tail waiting, peak queue và explicit failure/unmet-energy penalties. Training qua Headless, validation dài độc lập và source/config provenance. Các công thức đầy đủ và assumptions nằm tại [hồ sơ khoa học](../GAMA_RANR_SCIENTIFIC_CHANGES_VI.md).

Chưa có tuyên bố giảm chờ, giảm congestion, hội tụ hay hiệu quả so với baseline cho môi trường này. Cần calibration, accuracy gate, benchmark, design freeze, training và held-out evaluation trước các kết luận đó.
