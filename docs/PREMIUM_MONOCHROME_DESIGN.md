# Quy ước giao diện · Dark premium + vibrant gradient

Nguồn hiện hành: `frontend/styles.css`, `app.js`, `renderers.js` và `index.html`. Giao diện dùng nền đen tím nhiều lớp, gradient tím–hồng cho hành động chính, cyan/vàng cho điểm nhấn. Trang chào, workspace, hộp thoại và tài liệu dùng chung token. Màu trạng thái luôn đi cùng nhãn; font tự host.

| Thành phần | Giá trị |
| --- | --- |
| Nền / surface / nền phụ | #090a12 / #121420 / #1b1e30 |
| Chữ / chữ phụ | #f4f3ff / #afb2c9 |
| Border / input border | #2b2d42 / #555b78 |
| Gradient chính | #7040de → #9b38ce → #c33788; chữ nút trắng |
| Điểm nhấn | Tím #b9a0ff, hồng #f197d9, cyan #5de4ed, vàng #f3d377 |
| Trạng thái | Xanh #73e4b5; chờ #f3d377; lỗi #ff95aa, kèm nhãn/icon |
| Font | Inter Variable cho UI/headline; system monospace cho code |
| Radius | Control 12px, panel 22px, hero/dialog 28px |
| Ánh sáng | Radial gradient nền; glow nhẹ cho logo, CTA và điểm nhấn số liệu |
| Sidebar desktop | 240px |
| Motion | 140/200ms; tắt với prefers-reduced-motion |

Dưới 1024px, sidebar thành drawer có focus trap, Escape/backdrop, trả focus và khóa nền. Dưới 768px, form một cột và input 16px; bảng/code/nhánh đấu cuộn trong vùng riêng.

Canvas Robot Battle, OTT v2 và Battlecode dùng nền tối, Player A cyan / Player B hồng khớp HUD. Ký hiệu A/B, hình quân và độ sáng thân quân giúp phân biệt cả khi không nhận biết màu. Thay đổi hình thức không thay đổi tọa độ, luật hoặc dữ liệu replay. Focus dùng cyan; chế độ forced-colors giữ tiêu đề gradient đọc được. Không thêm thư viện hoặc tài nguyên ngoài cho hiệu ứng nền.

Asset URL có fingerprint nội dung. Sau khi đổi CSS/JS/font chạy `python scripts/version_frontend.py`; kiểm tra bằng `--check`. Giấy phép font tại [frontend/fonts](../frontend/fonts/README.md). Source Serif 4 còn là asset có license, không phải font headline hiện tại.

Kiểm tra Player/Admin ở desktop/mobile, keyboard focus, pending/error/empty states và replay theo [QA](QA.md).
