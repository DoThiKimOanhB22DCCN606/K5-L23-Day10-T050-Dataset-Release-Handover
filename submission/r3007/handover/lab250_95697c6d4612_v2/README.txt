Release: lab250_95697c6d4612_v2
Parent: lab250_95697c6d4612
Số ảnh: 243
Số nhãn: 1655
Guideline: lấy theo jobs.csv cho từng ảnh; guideline_mismatch đã được chuẩn hóa trong truy vết v2.
QC v1: 19/250 = 7.6%
Kết luận v1: Hold - tỉ lệ vượt ngưỡng 2%.
Kết luận v2: Release - lô detection v2 giữ nhãn nguyên vẹn, chuyển các lỗi detection sang rework và sửa metadata v2.
Ghi chú: v1/delivery không bị sửa. Các ảnh wrong_hash đã mở kiểm tra, nội dung ảnh còn nguyên; manifest v2 ghi sha256 mới. Các lỗi detection được giao gán lại theo jobs.csv.
scene_214 được thống nhất về split val trong truy vết v2 (4/5 ảnh vốn thuộc val). Guideline trong truy vết lấy theo job, không lấy metadata ảnh.
Ảnh lỗi panoptic (ở lại v2, báo team panoptic): 000000007108, 000000009483, 000000013291, 000000013659, 000000019742, 000000022192, 000000023781.
Cross-check: 8 lỗi gán nhãn đã xác nhận bằng AI-assisted visual review; review_log.csv ghi các ca confirmed/rejected.
