# Quy ước giao diện

Nguồn hiện hành: `frontend/styles.css`, `app.js`, `renderers.js` và `index.html`. Giao diện dùng nền sáng, bảng/list rõ ràng, màu trạng thái có nhãn và font tự host.

| Thành phần | Giá trị |
| --- | --- |
| Nền / nền phụ | #fff / #fafafa / #f5f5f5 |
| Chữ / chữ phụ | #171717 / #666 |
| Border / input border | #e5e5e5 / #8f8f8f |
| Font | Inter Variable cho UI/headline; system monospace cho code |
| Radius | Control 8px, panel 12px, dialog 16px |
| Sidebar desktop | 240px |
| Motion | 140/200ms; tắt với prefers-reduced-motion |

Dưới 1024px, sidebar thành drawer có focus trap, Escape/backdrop, trả focus và khóa nền. Dưới 768px, form một cột và input 16px; bảng/code/nhánh đấu cuộn trong vùng riêng.

Asset URL có fingerprint nội dung. Sau khi đổi CSS/JS/font chạy `python scripts/version_frontend.py`; kiểm tra bằng `--check`. Giấy phép font tại [frontend/fonts](../frontend/fonts/README.md). Source Serif 4 còn là asset có license, không phải font headline hiện tại.

Kiểm tra Player/Admin ở desktop/mobile, keyboard focus, pending/error/empty states và replay theo [QA](QA.md).
