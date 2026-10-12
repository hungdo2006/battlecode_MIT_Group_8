# Kiểm chứng NEON ARENA

Đây là báo cáo **v1 ngày 08/10/2026**. Kết quả mới của nền tảng đa game nằm trong [MULTIGAME_VERIFICATION.md](MULTIGAME_VERIFICATION.md).

Thực hiện trên Windows ngày **08/10/2026** (Asia/Saigon), với source trong `D:\LTM`.

## Môi trường đã dùng

| Thành phần | Phiên bản |
| --- | --- |
| Python | 3.13.12, `.venv` riêng |
| FastAPI | 0.143.0 |
| Uvicorn | 0.54.0 |
| Pydantic | 2.13.5 |
| G++ | GCC 13.2.0, C++17 |
| JDK | 21.0.8, JBR đi kèm IntelliJ |
| pytest | 9.1.1 |
| Playwright | 1.63.0, dùng Chrome đã cài |

Không thay PATH hệ thống hoặc cài compiler mới. Backend có thể tự tìm JDK đang có trên máy. Python packages được cài trong `.venv`.

## Test tự động

```text
44 passed in 6.17s
```

Không có test skip; cả compiler C++ và Java đều đã được chạy. Các nhóm kiểm tra:

- Luật tùy chỉnh tác động tới map, HP, sát thương và số lượt.
- Di chuyển đồng thời, biên bản đồ, va chạm, đổi chỗ, tấn công trượt, tấn công sau di chuyển.
- Hết HP, knockout đồng thời, so HP khi hết lượt, hòa, hành động không hợp lệ.
- Bot Python tồn tại qua nhiều request; C++/Java biên dịch rồi phục vụ nhiều request bằng cùng một PID.
- Timeout, crash, JSON lỗi, NaN, stdout quá dài, stderr quá giới hạn, lỗi cú pháp/loại file/kích thước source.
- Trên Windows `.venv`: PID Popen bằng PID bot thực, đồng thời môi trường `sys.prefix` vẫn được giữ.
- REST upload/match/rules, WebSocket từ trạng thái đầu đến kết quả, reconnect theo sequence.
- Replay trên đĩa khớp với frame live; app mới đọc lại replay mà không gọi bot.
- Luật được chụp riêng cho trận, sample submission idempotent, origin/host khác bị từ chối.

Có một `StarletteDeprecationWarning` từ TestClient về chuyển đổi tương lai từ `httpx` sang `httpx2`. Đây là cảnh báo của dependency dành cho test; không có test thất bại hoặc lỗi runtime.

## Trận thật qua server HTTP + WebSocket

| A | B | Kết quả | Lượt | HP cuối A / B |
| --- | --- | --- | --- | --- |
| Python / HUNTER | C++ / SENTINEL | A thắng, knockout | 9 | 40 / 0 |
| C++ / SENTINEL | Java / PHANTOM | B thắng, knockout | 10 | 0 / 20 |
| Java / PHANTOM | C++ / SENTINEL | A thắng, knockout | 10 | 20 / 0 |

Các trận dùng luật mặc định. `scripts/demo_match.py` nhận toàn bộ frame từ WebSocket rồi so sánh với JSON replay lấy qua HTTP: **khớp hoàn toàn**, gồm cả lượt 0 và lượt kết thúc. Đã chạy lại trận Python/C++ sau khi cập nhật runner để quản lý đúng PID trên Windows.

## Giao diện trên Chrome

`scripts/check_ui.py` chạy thao tác thật, không mock API. Đã qua:

- Trang chủ kết nối server và hiển thị dữ liệu bot/trận thật.
- Thêm bot mẫu, chọn bot, Start Match.
- Pause giữ nguyên lượt hiển thị trong khi trận backend tiếp tục và hoàn thành.
- Reset về lượt 0, Start phát lại, màn hình Victory.
- Frame trong browser khớp JSON replay.
- Lưu thông số qua form và xác nhận bằng HTTP; trả lại luật ban đầu sau kiểm tra.
- Mở replay từ lịch sử; tải file Python qua form upload và kiểm tra trạng thái compile thành công.
- Cả 5 mục điều hướng không tràn ngang ở viewport 390 × 844.
- Không có JavaScript page error sau khi sửa lỗi timestamp của hoạt ảnh tấn công.
- `node --check frontend/app.js` qua.
- `start.bat` đã khởi động được server trên `127.0.0.1:8000`.

Ảnh kiểm chứng:

- [Trang chủ](screenshots/home.png)
- [Đấu trường và log](screenshots/arena.png)
- [Victory](screenshots/victory.png)
- [Nộp bot](screenshots/upload.png)
- [Bố cục mobile](screenshots/mobile.png)

Đây là kiểm chứng cho demo local với code tin cậy, không phải đánh giá sandbox hoặc khả năng triển khai Internet. Các bot mẫu và lịch sử trận thử còn trong thư mục runtime để có thể mở lại khi thuyết trình.
