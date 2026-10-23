# NEON ARENA — Chế độ thi tại phòng máy (LAN không Internet)

**Phạm vi:** bản triển khai độc lập trên máy chủ/PC của trường. Không chạy overlay này trên EC2 hiện đang phục vụ Internet. Đây là cấu hình mẫu cần kiểm thử trước sự kiện, **không phải bằng chứng phòng thi đã được cách ly**.

## Mô hình

Máy thí sinh → switch/VLAN phòng thi → máy chủ NEON ARENA LAN. Không có cổng Internet trên router/VLAN thi (không default gateway ra WAN); chặn mạng di động theo nội quy; kiểm tra không có Wi-Fi phụ, VPN/proxy, hotspot hoặc phần mềm AI cục bộ mà đề thi không cho phép. Quản trị viên dùng VLAN quản trị tách biệt. Các container chấm bot có `network_mode=none` và không có Docker socket; controller riêng mới dùng socket. Mạng LAN của sinh viên **không được phép** truy cập Docker API/SSH/hệ điều hành.

Không có phần mềm nào có thể đảm bảo học sinh không dùng AI khi họ có thiết bị di động hoặc mô hình offline. Cần giám thị và chính sách thi.

## Chuẩn bị trước ngày thi (có Internet, do kỹ thuật viên)

1. Sử dụng một máy chủ riêng ở trường, không mount volume AWS. Cài Docker Engine + Compose hỗ trợ `!reset`; build/pull trước toàn bộ image (Arena, Controller, Sandbox, Caddy); kiểm tra nguồn điện, đồng hồ hệ thống, dung lượng và UPS.
2. Tạo tài khoản và thiết lập MFA cho Admin trước giờ thi; không dựa vào SMTP/Google OAuth hay dịch vụ Internet. Giữ backup + ảnh image phục hồi trên thiết bị ngoại tuyến.
3. Cấu hình tên DNS nội bộ, ví dụ `arena.exam.test`, trỏ đến IP LAN máy chủ. Đặt cấu hình bảo mật trong file `.env` **không commit**, gồm:
   - `ARENA_PUBLIC_DOMAIN=arena.exam.test`
   - `ARENA_LAN_BIND_IP=192.168.10.10` (đổi theo server thật, không dùng `0.0.0.0`)
   - `ARENA_PROXY_SECRET` ngẫu nhiên ít nhất 48 ký tự
   - `ARENA_RUNNER_TOKEN` ngẫu nhiên ít nhất 32 ký tự
4. Caddyfile.exam dùng `tls internal` không gọi Let's Encrypt. Trước khi thi, lấy chứng chỉ CA root từ Caddy và đưa vào kho tin cậy trên **các máy thí sinh được quản lý**. Không tắt kiểm tra HTTPS và không chấp nhận cảnh báo chứng chỉ.
5. Khai báo đồng hồ nội bộ đồng bộ cho server/clients để TLS và Admin TOTP làm việc khi offline. Làm thử một Official Match và replay end-to-end với máy thật và Docker.

## Khởi động máy chủ LAN

Chỉ trên máy chủ riêng của trường, trước khi tách Internet:

```bash
docker compose -f compose.yaml -f compose.exam.yaml config -q
docker compose -f compose.yaml -f compose.exam.yaml up -d --build --wait
```

Sau khi **các image đã được lưu tại máy**, ngắt WAN nhưng **giữ mạng LAN**. Nếu phải restart offline: dùng `up -d --no-build --wait`, không tự pull/build từ Internet.

## Kiểm chứng bắt buộc trước khi phát đề

- Máy thi truy cập `https://arena.exam.test`, đăng nhập, nộp bot, biên dịch, chạy thử, mở replay.
- Máy thi **không** truy cập được `https://api.openai.com`, `https://generativelanguage.googleapis.com` hay Internet nói chung, bằng mọi DNS và đường đi IP; kiểm tra riêng IPv6, DNS, proxy, VPN, hotspot.
- Bot cố truy cập HTTP/DNS từ Sandbox phải thất bại; bot bình thường vẫn chạy, Controller/Docker luôn healthy.
- Chỉ port HTTPS của máy chủ LAN được mở cho máy thí sinh. Không mở port 22, 2375/2376, 8000, 9000 hoặc giao diện host.
- Kiểm chứng mỗi vòng: công bố luật → 15/20 phút chỉnh code → khóa bot → Official Match → điểm/replay.
- Diễn tập mất điện, restore, phát lại trận và phương án tổ chức thi khi máy chủ bị lỗi.

**Không dùng lệnh Stop/Start EC2 để thử offline:** máy đặt trên AWS cần đường Internet/đường riêng để thí sinh vào. `compose.exam.yaml` không tự chặn Internet vật lý; bộ phận mạng phải thực hiện. Không kết hợp `compose.exam.yaml` và `compose.public.yaml`.
