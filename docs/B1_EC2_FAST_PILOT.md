# B1.4 — Pilot nhanh: EC2 hiện tại + laptop chạy bot

**Đối tượng:** NEON ARENA đang chạy tại `traitimcodon.duckdns.org` trên EC2;
dữ liệu là test và chủ dự án cho phép website tạm gián đoạn.

Đây là **pilot thay toàn bộ website bằng project thử nghiệm mới** trên **cùng EC2**,
không phải nút switch nóng của B1.3. Dữ liệu và tài khoản mới hoàn toàn độc lập.
Hệ thống cũ / 5 volumes / Caddy certificates cũ được giữ nguyên để khởi động lại.
**Không sử dụng** `compose.ec2-pilot.yaml` với `compose.yaml` hoặc các override
của project gốc.

## Trạng thái và điều kiện

- PR B1.3 (#32) đã merge. B1.4 chỉ được chạy sau khi PR B1.4 được review/merge.
- Checkout gốc: `~/battlecode_MIT_Group_8`, SHA đã ghi nhận
  `b4bcc1edb8cb4bf0285aa4450cf66b9f26ce69e3`, project `neon-arena`.
  Giữ nguyên `.env`, `compose.override.yaml`, tất cả Docker volumes và images.
- Checkout mới: `~/neon-arena-b1-pilot`, project `neon-b1-ec2-pilot`;
  service cloud **chỉ** `arena` và `gateway`; dữ liệu/volumes mới.
- Cloud pilot cho Admin và Player đăng nhập bằng username + password, không yêu cầu TOTP; sử dụng token/mật khẩu
  **mới**, không dùng secret từ EC2 cũ. Windows Worker kết nối HTTPS outbound,
  không expose inbound/Docker Controller port.
- Bạn **không cần** full backup dữ liệu thử nghiệm trước bước này vì không migrate,
  nhưng giữ nguyên 5 volume cũ. Nếu muốn bảo toàn dữ liệu khỏi cả sự cố ổ đĩa,
  vẫn phải có backup ngoài máy: giữ volume không thay thế được bản sao lưu.
- Không còn 17 GB trống? Xác nhận đủ tối thiểu 3 GiB khi prepare; tuyệt đối
  không dùng `docker system prune` hay `down -v` để giải phóng dung lượng.
- Domain DuckDNS phải tiếp tục trỏ đúng EC2. Gateway mới sẽ xin chứng chỉ công khai
  cho **cùng domain** trên 80/443 sau khi gateway cũ đã dừng; cần chờ cấp TLS.
  Có thể bị giới hạn ACME; nếu lỗi, dùng rollback về gateway cũ.
- Những lệnh dưới đây **chưa được thực hiện trên AWS**. Chạy trong cửa sổ bảo trì;
  ưu tiên có bản sao cấu hình riêng của bạn ở nơi an toàn.

## 1. Chuẩn bị pilot (Ubuntu EC2; website cũ vẫn chạy)

Từ terminal EC2, tạo **checkout mới riêng** và checkout mã phiên bản đã review:

```bash
cd ~
git clone https://github.com/hungdo2006/battlecode_MIT_Group_8.git neon-arena-b1-pilot
cd ~/neon-arena-b1-pilot
git checkout <FULL_B1.4_MERGED_SHA>
mkdir -p .b1-pilot
chmod 700 .b1-pilot
cp deploy/b1-ec2-pilot-cloud.env.example .b1-pilot/cloud.env
chmod 600 .b1-pilot/cloud.env
```

Điền riêng vào `.b1-pilot/cloud.env` bằng trình chỉnh sửa:
`ARENA_REMOTE_RUNNER_KEY` (32+ byte ngẫu nhiên) và
`ARENA_PROXY_SECRET` (48+ ký tự ngẫu nhiên, khác machine key).
Domain đã có sẵn trong template. **Không gửi secret vào chat/GitHub hoặc output
lệnh docker compose config.** Giữ machine key an toàn để điền sang laptop.

Tại checkout pilot mới, chạy lệnh chuẩn bị (sẽ build image và tạo Admin bằng mật khẩu,
**không dừng website cũ**):

```bash
sudo python3 scripts/b1_ec2_pilot.py prepare \
  --old-root ~/battlecode_MIT_Group_8 \
  --old-sha b4bcc1edb8cb4bf0285aa4450cf66b9f26ce69e3
```

Nhập mật khẩu mạnh mới cho Admin `b1.operator` qua terminal riêng tư. Không cần
Authenticator hay mã TOTP. Đây là tài khoản pilot, không phải Admin cũ.
Đăng nhập Admin trên HTTPS bằng username + password; bảo vệ mật khẩu vì chế độ
password-only không có lớp xác thực thứ hai.

Lệnh `prepare` chỉ build `arena`, tạo database/volume pilot riêng và chạy
Admin CLI bên trong container dùng `--no-deps` (không mở public port).

## 2. Windows laptop — chuẩn bị Worker

Trên laptop Windows, checkout **cùng mã đã review** và bật Docker Desktop Linux:

```powershell
cd "$HOME"
git clone https://github.com/hungdo2006/battlecode_MIT_Group_8.git neon-arena-b1-worker
cd "$HOME\neon-arena-b1-worker"
git checkout <FULL_B1.4_MERGED_SHA>
New-Item -ItemType Directory -Force .b1-pilot | Out-Null
Copy-Item deploy/b1-ec2-pilot-worker.env.example .b1-pilot/worker.env
```

Điền vào `.b1-pilot/worker.env`: **cùng** `ARENA_REMOTE_RUNNER_KEY` bên
Cloud và `ARENA_RUNNER_TOKEN` riêng, ngẫu nhiên >=32 ký tự; không đặt
Controller token trên AWS. Giới hạn quyền đọc file này. Không cần mở router port.

Có thể build trước khi chuyển website:

```powershell
docker compose --env-file .b1-pilot/worker.env -f compose.remote-worker.yaml -p neon-b1-worker build
```

## 3. Chuyển website từ hệ thống cũ sang pilot (Ubuntu EC2)

**Chỉ thực hiện khi chuẩn bị hoàn tất và bạn chấp nhận downtime.**

```bash
cd ~/neon-arena-b1-pilot
sudo python3 scripts/b1_ec2_pilot.py cutover \
  --old-root ~/battlecode_MIT_Group_8 \
  --old-sha b4bcc1edb8cb4bf0285aa4450cf66b9f26ce69e3 \
  --confirm-downtime
```

Script từ chối Docker Engine remote, project/volume không đúng, config/xác thực mật khẩu/
domain/secret sai, image chưa build, pilot chưa chuẩn bị hoặc dịch vụ khác chiếm
cổng. Chỉ dừng `gateway, arena, controller` của project gốc; **không xóa**
container/volume, không pull/rebuild project gốc. Sau đó chạy Cloud pilot.
Nếu không khởi động được ngay, thử khởi động lại project gốc tự động.

Trên Windows, khởi động Worker:

```powershell
docker compose --env-file .b1-pilot/worker.env -f compose.remote-worker.yaml -p neon-b1-worker up -d --no-build --wait
curl.exe -sS -o NUL -w "HTTP=%{http_code} TLS=%{ssl_verify_result}\n" https://traitimcodon.duckdns.org/api/health
```

**Mong đợi:** trước khi Worker sẵn sàng, health có thể 503; sau khi kết nối,
`HTTP=200`, `TLS=0`. Trên browser, đăng nhập pilot Admin bằng username + password,
tạo Player/Team thử nghiệm, nộp bot Python/C++/Java, chạy Official, xác nhận
replay/bảng điểm và 2 trận đồng thời + trận thứ 3 chờ. Dừng rồi khởi động lại
**chỉ agent của project worker** để kiểm tra fail-closed/reconnect:

```powershell
docker compose --env-file .b1-pilot/worker.env -f compose.remote-worker.yaml -p neon-b1-worker stop agent
docker compose --env-file .b1-pilot/worker.env -f compose.remote-worker.yaml -p neon-b1-worker start agent
```

Không ngắt Docker Desktop/Wi-Fi đang phục vụ công việc khác. Không tự động
xử thua bot khi máy chạy bot mất kết nối.

## 4. Rollback về NEON ARENA cũ (Ubuntu EC2)

Khi cần trở về website/tài khoản/kết quả cũ:

```bash
cd ~/neon-arena-b1-pilot
sudo python3 scripts/b1_ec2_pilot.py rollback \
  --old-root ~/battlecode_MIT_Group_8 \
  --old-sha b4bcc1edb8cb4bf0285aa4450cf66b9f26ce69e3 \
  --confirm-rollback
```

Sau đó dừng Worker bằng `docker compose ... stop` với **đúng** project và file
Worker trên laptop. Các volumes thử nghiệm vẫn được giữ lại; script chỉ dừng
pilot rồi dùng `up -d --no-build --wait` để bật project gốc với **thứ tự file
Compose gốc**. Kiểm tra HTTPS và tài khoản cũ; không rollback bằng `git reset`,
`down -v`, `docker system prune` hay xoá volume.

## Giới hạn rõ ràng

- Chạy trên cùng EC2 với **hai project luân phiên**, không có hai website phục
  vụ cổng 443 cùng lúc. Không cần server/IP/domain thứ hai.
- Nghiệm thu WAN thật chưa PASS chỉ từ GitHub Actions; phải chạy Official/replay
  giữa hai máy và kiểm tra reconnect thực tế.
- Dữ liệu test tạo trong pilot **không tự chuyển** về database cũ khi rollback.
- Đây là pilot nhanh, **không phải** chuyển chế độ B1.3 trên cùng dữ liệu;
  khi có người dùng thật cần backup, review bảo mật MFA, giám sát và quy trình
  B1.3 riêng.
