# LAN và chế độ legacy

Mặc định `compose.yaml` chạy demo LAN, không yêu cầu tài khoản. Đây là luồng khác với [Account-Only](SANDBOX.md) dùng Team, Season và Official Match.

1. Máy host chạy Docker, đặt `ARENA_BIND_IP=0.0.0.0`.
2. Các máy cùng mạng mở `http://<IPv4-host>:8000`; đổi cổng theo `ARENA_PORT`.
3. Nếu cần, chỉ cho phép cổng web trên firewall mạng Private. Không mở cổng controller 9000, Docker API hoặc port-forward router.

## Demo legacy

Organizer nhập mã riêng từ `.env`, chọn game/luật và mở cuộc thi. Hai Player dùng hai phiên trình duyệt riêng, nộp bot, chọn Active Bot và giữ website mở. Organizer gửi lời mời; cả hai chấp nhận để chốt bot và bắt đầu trận.

Presence/WebSocket ảnh hưởng việc nhận lời mời legacy. Với trận Official/Scrimmage Account-Only đã được gửi hợp lệ, bot tiếp tục chạy khi người chơi offline.

## Account-Only qua LAN

Thêm đúng origin LAN, gồm scheme và cổng, vào `ARENA_AUTH_ORIGINS`; thêm IP host không kèm cổng vào `ARENA_ALLOWED_HOSTS`. Bật `ARENA_AUTH_ALLOW_HTTP=1` chỉ cho local/LAN. Không dùng cấu hình HTTP này cho Internet.

Frontend gọi API tương đối và tự chọn `ws`/`wss` theo website. Đổi Host, Origin, reverse proxy hoặc cookie sai có thể gây 403; không sửa bằng cách tắt kiểm tra quyền.

Public Account-Only dùng Caddy trong `compose.public.yaml`; mẫu Nginx `deploy/nginx.conf.example` dành cho cấu hình legacy read-only, không thay thế gateway tài khoản. Xem [vận hành](OPERATIONS.md).
