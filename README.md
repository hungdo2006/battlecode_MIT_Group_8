# NEON ARENA

**NEON ARENA** là nền tảng tổ chức giải đấu lập trình bot. Người chơi tạo đội, nộp chương trình; ban tổ chức tạo giải, xếp lịch thi đấu và xem kết quả, bảng điểm, replay ngay trên website.

Dự án sử dụng **Python, FastAPI, Docker** và hỗ trợ Robot Battle, OTT cùng một số trò chơi mở rộng. Bot được chạy trong môi trường Docker tách biệt.

## Nên tổ chức theo cách nào?

| Hình thức | Website chạy ở đâu? | Bot chạy ở đâu? |
| --- | --- | --- |
| **Offline** (thi tại phòng máy, không có Internet) | PC/server trong mạng LAN của trường | Chính PC/server đó |
| **Online** (thi qua Internet) | AWS EC2 | Trên AWS hoặc PC/server riêng |

Hệ thống Online hiện tại: **[traitimcodon.duckdns.org](https://traitimcodon.duckdns.org)**. Phiên bản B1.5 đã thử thành công việc chuyển nơi chạy bot giữa AWS và laptop. **Hiện chỉ chạy tối đa 2 trận cùng lúc, chưa hỗ trợ nhiều PC chạy bot song song.**

## 1. Tổ chức giải Offline

Phù hợp khi thí sinh tập trung trong phòng máy và ban tổ chức muốn mạng thi **không kết nối Internet**.

### Bước 1 — Chuẩn bị máy chủ

Chọn một PC/server trong trường, nối cùng mạng LAN với các máy thi. Cài **Git, Python 3 và Docker** (Windows dùng Docker Desktop ở chế độ Linux Containers; Linux dùng Docker Engine + Compose).

Khi máy vẫn có Internet, mở Terminal/PowerShell và chạy:

~~~bash
git clone https://github.com/hungdo2006/battlecode_MIT_Group_8.git
cd battlecode_MIT_Group_8
python scripts/configure_sandbox.py
~~~

Mở file `.env` mới được tạo và bổ sung/chỉnh các dòng sau:

~~~dotenv
ARENA_PUBLIC_DOMAIN=arena.exam.test
ARENA_LAN_BIND_IP=192.168.10.10
ARENA_PROXY_SECRET=<khoa_ngau_nhien_dai_it_nhat_48_ky_tu>
~~~

Đổi IP thành **địa chỉ LAN thật** của máy chủ; tạo tên miền nội bộ `arena.exam.test` trỏ về IP đó. Script phía trên đã sinh khóa chạy bot. Trên Linux, bảo đảm `DOCKER_SOCKET_GID` khớp với kết quả `stat -c '%g' /var/run/docker.sock`.

### Bước 2 — Khởi động hệ thống và tạo Admin

Chạy lần lượt **trên máy chủ LAN mới, khi chưa có Arena đang hoạt động**:

~~~bash
docker compose -f compose.yaml -f compose.exam.yaml config -q
docker compose -f compose.yaml -f compose.exam.yaml build
docker compose -f compose.yaml -f compose.exam.yaml run --rm --no-deps arena python -m backend.admin_cli --data-dir /app/data migrate
docker compose -f compose.yaml -f compose.exam.yaml run --rm --no-deps arena python -m backend.admin_cli --data-dir /app/data create-admin --username organizer
docker compose -f compose.yaml -f compose.exam.yaml run --rm --no-deps arena python -m backend.admin_cli --data-dir /app/data enroll-admin-totp --username organizer
docker compose -f compose.yaml -f compose.exam.yaml up -d --no-build --wait
~~~

Hệ thống hỏi mật khẩu Admin ngay trong Terminal. **Chế độ phòng thi hiện yêu cầu thêm mã xác thực TOTP cho Admin và không mở tự đăng ký**: Admin cần mời/cấp tài khoản cho thí sinh trước ngày thi.

Website phòng thi sử dụng HTTPS với chứng chỉ nội bộ. Ban tổ chức cần cài **chứng chỉ CA của Caddy** trên các máy thi và cấu hình DNS LAN trước khi truy cập `https://arena.exam.test`. Hướng dẫn cụ thể: **[Thi Offline trong phòng máy](docs/EXAM_MODE.md)**.

### Bước 3 — Diễn tập và tổ chức thi

Trước khi ngắt Internet, thử trên **máy thí sinh thật**: đăng nhập, nộp bot, chạy một trận đấu và mở replay. Sau đó đội kỹ thuật **ngắt kết nối Internet của mạng phòng thi nhưng vẫn giữ LAN/DNS**; Docker không tự làm việc này.

Trong ngày thi, Admin tạo giải và luật, chốt các đội, đặt giờ khóa bot và giờ thi đấu. Người chơi nộp bot và chọn bot đại diện trước hạn. Hệ thống sẽ chạy các trận Official theo lịch và lưu kết quả, replay. Khi kết thúc, kiểm tra bảng điểm rồi sao lưu dữ liệu ra thiết bị khác.

Nếu muốn công bố **kết quả** giải Offline lên website Online, xem [Hướng dẫn chuyển kết quả](docs/OFFLINE_RESULTS_TRANSFER.md). Việc này cần cấu hình/kiểm thử riêng và **chưa chuyển replay**.

## 2. Tổ chức giải Online

Phù hợp khi người chơi tham gia từ nhiều nơi qua Internet. Website, tài khoản, kết quả và replay được lưu trên **AWS EC2**; người chơi chỉ cần trình duyệt web.

### Bước 1 — Kiểm tra website

Với hệ thống B1.5 **đang được triển khai**, mở Terminal Ubuntu trên EC2:

~~~bash
cd ~/neon-arena-b1-pilot
sudo python3 -m scripts.b15_pilot_runner status
~~~

Nếu thấy `ready: true` và `admission_closed: false` thì có thể bắt đầu kiểm thử. Nếu chạy bot bằng PC bên ngoài (`mode: remote`), PC đó phải đang kết nối.

**Lưu ý:** Đây là lệnh kiểm tra **server đã cài B1.5**, không phải lệnh cài một AWS mới. Nếu chưa có server, xem [quy trình thiết lập AWS](docs/B1_EC2_FAST_PILOT.md) và [vận hành B1.5](docs/B15_SHARED_PILOT_RUNNER_SWITCH.md).

### Bước 2 — Mở giải trên website

1. **Ban tổ chức:** đăng nhập Admin, tạo Season/Tournament, chọn trò chơi và công bố luật.
2. **Người chơi:** đăng ký tài khoản, tạo/tham gia Team, tải bot lên và chọn **Active Bot**.
3. **Ban tổ chức:** chốt danh sách đội, tạo lịch thi đấu, đặt giờ khóa bot.
4. **Trong giải:** theo dõi trận Official, hàng chờ và các trận lỗi; không khởi động lại hoặc chuyển máy chạy bot giữa trận.
5. **Sau giải:** kiểm tra kết quả/replay, công bố bảng điểm và sao lưu dữ liệu.

Xem thêm [Quản lý giải và Team](docs/TEAM_TOURNAMENTS.md). Trước một giải thật, cần sao lưu và diễn tập khôi phục dữ liệu theo [hướng dẫn B1.5](docs/B15_SHARED_PILOT_RUNNER_SWITCH.md).

## 3. Dùng PC/server mạnh của trường để chạy bot Online

Cách này giúp **AWS chỉ phục vụ website và lưu kết quả**, còn PC mạnh của trường làm việc nặng là biên dịch/chạy bot. **Không cần chuyển database hoặc website sang PC.**

### Bước 1 — Cài Remote Worker trên PC

Trên PC Windows, cài **Git và Docker Desktop (Linux Containers/WSL2)**, dùng mạng dây nếu có. Mở PowerShell:

~~~powershell
git clone https://github.com/hungdo2006/battlecode_MIT_Group_8.git neon-arena-worker
cd neon-arena-worker
New-Item -ItemType Directory -Force .b1-pilot | Out-Null
Copy-Item deploy/b1-ec2-pilot-worker.env.example .b1-pilot/worker.env
~~~

Mở `.b1-pilot/worker.env` và điền:

~~~dotenv
ARENA_REMOTE_SERVER_URL=https://traitimcodon.duckdns.org
ARENA_REMOTE_RUNNER_KEY=<khoa_giong_tren_AWS>
ARENA_RUNNER_TOKEN=<khoa_rieng_cua_PC_it_nhat_32_ky_tu>
SANDBOX_NAMESPACE=neon-school-worker
DOCKER_SOCKET_GID=0
~~~

**Hai khóa có nhiệm vụ khác nhau:** `ARENA_REMOTE_RUNNER_KEY` phải trùng khóa Worker của AWS; `ARENA_RUNNER_TOKEN` tạo mới riêng cho PC. Giữ bí mật cả hai. Chọn mã nguồn Worker tương thích với phiên bản Arena trên EC2.

Khởi động Docker Desktop, rồi chạy:

~~~powershell
docker compose --env-file .b1-pilot/worker.env -p neon-b1-worker -f compose.remote-worker.yaml up -d --build --wait
~~~

Nếu PC dùng **Ubuntu Server**, dùng Docker Engine + Compose, lấy `DOCKER_SOCKET_GID` bằng `stat -c '%g' /var/run/docker.sock` rồi chạy lệnh Docker Compose tương ứng bằng Bash (có thể cần `sudo`). PC chỉ cần kết nối HTTPS **đi ra** AWS; **không** mở port 9000/Docker API ra Internet.

### Bước 2 — Chuyển bot từ AWS sang PC

Đảm bảo **không còn trận hoặc lượt biên dịch đang chạy**, và không có laptop cũ nào tiếp tục chạy Agent cùng khóa. Trên EC2, tại `~/neon-arena-b1-pilot`, chạy:

~~~bash
sudo python3 -m scripts.b15_pilot_runner switch --target remote --backup-directory .runner-switch/b15-backup-002
sudo python3 -m scripts.b15_pilot_runner status
~~~

`b15-backup-002` là **bản backup được xác minh của hệ thống hiện tại**; với máy chủ khác phải thay bằng đường dẫn backup hợp lệ đã chuẩn bị. Nếu đang ở Remote, không chạy chuyển mode lần nữa. Khi `mode: remote` và `ready: true`, hãy đấu thử một trận rồi kiểm tra replay.

### Bước 3 — Chuyển bot về AWS khi cần

Sau khi chờ hết các công việc đang chạy, trên EC2:

~~~bash
sudo python3 -m scripts.b15_pilot_runner switch --target local --backup-directory .runner-switch/b15-backup-002
sudo python3 -m scripts.b15_pilot_runner status
~~~

Khi Local đã sẵn sàng, có thể dừng Agent trên PC. Nếu PC mất mạng/điện giữa trận, **không tự cho bot thua hoặc chạy lại trận chưa rõ trạng thái**; xử lý theo [runbook B1.5](docs/B15_SHARED_PILOT_RUNNER_SWITCH.md).

> **Giới hạn:** PC mạnh hơn không tự tăng số trận chạy cùng lúc. B1.5 chỉ có **một Remote Worker và tối đa 2 trận đồng thời**. Giải lớn cần kiểm thử tải; muốn nhiều Worker phải phát triển thêm bộ phân phối trận.

---

**Đọc thêm:** [Thi Offline](docs/EXAM_MODE.md) · [Vận hành server](docs/OPERATIONS.md) · [Giải Team](docs/TEAM_TOURNAMENTS.md) · [Chuyển Runner](docs/B15_SHARED_PILOT_RUNNER_SWITCH.md).

**An toàn:** Không đăng `.env`, token hay backup lên GitHub. Không dùng `docker compose down -v` hoặc `docker system prune --volumes` để dọn máy vì có thể mất dữ liệu.
