# Báo cáo nhóm Oanh–Huyền

## 1. Số liệu luyện tập
- F1 theo seed (rule / cross_check / overall): seed 3007: 1.0 / 0.7 / 0.8 sau review; seed 42: rule 1.0, cross-check chưa review.
- Số ứng viên trên lô sạch (`--no-faults`): 0/50 ảnh; seed 3007 có 12 ảnh ứng viên, 8 lỗi gán nhãn confirmed và 5 ứng viên rejected.
- Ngưỡng đã chọn và cách chọn (không dùng `_private`): đo false positives trên lô sạch riêng 50 ảnh, rồi siết ghép theo mask. Lệch lớp cần điểm ghép ≥0.55 và hơn ghép cùng lớp ≥0.15; drift cần segment ≥1024 pixel, coverage <0.55, IoU <0.5 và ≥128 pixel giao; missing box cần segment ≥1024 pixel và không có ghép cùng lớp đạt 0.2; merge cần một segment phủ đáng kể hai box cùng lớp, mỗi box có ≥45% pixel thuộc segment, mỗi phần giao ≥20% segment, và IoU hai box <0.5. Các ngưỡng chỉ sinh ứng viên, không thay thế review ảnh. Mọi ứng viên seed 3007 vẫn cần người xem và ghi verdict.

## 2. Vì sao báo hết ứng viên làm F1 giảm?
Điểm là F1 của cặp `(type, target)`. Nếu báo ứng viên tự nhiên hoặc gán sai hướng lỗi, số FP tăng và precision giảm; F1 là trung bình điều hoà của precision và recall nên giảm. Ở seed 3007, 12 ảnh ứng viên được review thành 8 lỗi confirmed và 5 verdict rejected (một ảnh bbox_drift được phân loại lại thành missing_box), và F1 cross-check đo được là 0.7. Lô sạch 50 ảnh có 0 ứng viên với ngưỡng cuối.

## 3. Quyết định và lineage
Release v1 `lab250_95697c6d4612` có 19 finding trong `errors.json` trên 250 ảnh = 7.6% (scene_leak tính là một finding/ảnh theo quy tắc lab). Ngưỡng là trên 2%, nên quyết định `HOLD` đã ghi trong `runs/lineage.jsonl`. Truy vấn impact xác nhận `R-021: affected=True action=review_or_retrain`: đổi dataset không sửa được model đã train, vì vậy run cần được đánh giá lại hoặc train lại.

## 4. Hash chứng minh gì, không chứng minh gì?
Hash chứng minh bytes của file hiện tại khớp giá trị đã ghi trong manifest tại thời điểm tính; nó giúp phát hiện file bị đổi hoặc hỏng sau đó. Hash không chứng minh ảnh/nhãn đúng ngữ nghĩa, ảnh có nguồn gốc đáng tin cậy, hay nhãn khớp với nội dung.

## 5. Truy vết
Changelog v1.3 đổi quy tắc `bottle`: vật bị che trên 50% hoặc cắt ở mép ảnh vẫn phải có box; v1.2 cho phép bỏ qua. Ticket của team AI nêu `scene_197` và `scene_309`. Đối chiếu các box lớp `bottle` (class 39) trong nhãn YOLO với scene và job của từng ảnh; chỉ tính job có guideline `v1.2` theo `jobs.csv`, không dùng phiên bản trong metadata ảnh. Kết quả: `tier_a` có 000000002685 (scene_309, J02) và 000000009590 (scene_197, J04); `tier_b` có 000000005193, 000000006471 (J03), 000000007574 và 000000008021 (J04). Các ảnh tier_b thuộc scene khác nhưng đáp ứng cùng điều kiện. `notify` gồm annotator/reviewer của các job liên quan: A02, A04, A05, Q01, Q03. `python scripts/score_findings.py --run runs/r3007` cho F1 truy vết làm tròn 1.0 ở cả `tier_a`, `tier_b` và `notify`.

## 6. Bug hoặc điểm chưa rõ trong lab (nếu có)
Ghép detection với panoptic chỉ tạo ứng viên, không chứng minh hai nhãn mô tả cùng một vật. Trong các bộ đề đã xử lý, box rộng, vật bị che, vật nhỏ ở mép ảnh và nhiều vật cùng lớp đứng sát nhau tạo ra ứng viên nhiễu; một số ảnh còn có lỗi luật trùng với ứng viên đối chiếu. Vì mỗi ảnh chỉ tính tối đa một lỗi, các trường hợp trùng đã giữ lỗi luật và loại ứng viên ngữ nghĩa khỏi `errors.json`. Đây là giới hạn của phép ghép, không phải bằng chứng rằng các nguồn nhãn còn lại luôn đúng.

## 7. Đề ẩn và giới hạn xác nhận
Đã tạo bốn artifact (`errors.json`, `candidates.json`, `review_log.csv`, `trace.json`) riêng cho đề 05; không chép `delivery/` vào submission. Bản phẳng `submission/de_an/` dùng đề 05 làm lựa chọn làm việc theo số finding thấp nhất trong các file đã lập, không phải kết quả xếp hạng từ hidden scorer. Các verdict đều được ghi nhận là AI-assisted và chưa được con người xác minh độc lập; nhóm cần mở ảnh gốc/overlay và cập nhật review trước khi nộp cuối.
