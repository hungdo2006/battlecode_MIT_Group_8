# NEON ARENA

**Nền tảng tự host để tổ chức giải đấu lập trình bot**, từ thi trực tiếp trong phòng máy (LAN offline) tới giải đấu qua Internet. Người chơi quản lý Team và bot; ban tổ chức quản lý Season/Tournament, luật, lịch Official Match, bảng điểm và replay.

**Công nghệ:** Python/FastAPI · HTML/CSS/JavaScript · SQLite/JSONL · Docker Sandbox · Caddy HTTPS.

**Game:** Robot Battle, OTT v2, OTT Advanced; Battlecode 2026 là tích hợp tùy chọn.

**Trạng thái B1.5:** website và database đặt trên AWS EC2; bot có thể chạy trên EC2 (**Local Runner**) hoặc trên PC riêng kết nối HTTPS (**Remote Runner**). Đã thử thành công chuyển đổi hai chiều, đấu luyện và replay trên EC2/laptop Windows. **Chưa nghiệm thu tải giải quy mô lớn; hiện giới hạn 2 trận đồng thời, 1 Runner mỗi thời điểm.**

## Chọn phương án triển khai

| Mô hình | Website và dữ liệu | Máy chạy bot | Kết nối |
| --- | --- | --- | --- |
| **Offline — phòng máy** | Máy chủ LAN riêng của trường | Máy chủ LAN | LAN, không cần WAN trong giờ thi |
| **Online — Local** | AWS EC2 | AWS EC2 | Internet |
| **Online — Remote** | AWS EC2 | PC/server của trường | Internet + HTTPS outbound từ PC tới AWS |

Offline dùng **database/volumes độc lập**. Online B1.5 giữ **một database AWS** cho cả Local và Remote. Không chuyển giữa hai Docker project AWS khác nhau để đổi nơi chạy bot.

## 1. Hướng dẫn tổ chức giải Offline (LAN không Internet)

### 1.1. Chuẩn bị máy chủ và mạng

Máy chủ **riêng tại trường** cần Git, Python 3, Docker Engine + Compose (Linux) hoặc Docker Desktop chế độ Linux Containers (Windows). Docker Compose phải hỗ trợ YAML `!reset`. Nên sử dụng Ethernet, VLAN phòng thi và UPS. Chuẩn bị image, trình biên dịch và các tài nguyên cần thiết **trước khi ngắt Internet**.

~~~bash
git clone https://github.com/hungdo2006/battlecode_MIT_Group_8.git
cd battlecode_MIT_Group_8
python scripts/configure_sandbox.py
~~~

Chỉnh file bí mật `.env` do helper tạo; ví dụ **phải đổi IP/host và thay placeholder bằng khóa ngẫu nhiên riêng**:

~~~dotenv
ARENA_PUBLIC_DOMAIN=arena.exam.test
ARENA_LAN_BIND_IP=192.168.10.10
ARENA_RUNNER_TOKEN=<RANDOM_32_PLUS_CHARACTERS>
ARENA_PROXY_SECRET=<RANDOM_48_PLUS_CHARACTERS>
~~~

Cấu hình DNS **nội bộ** để `arena.exam.test` trỏ tới IP host. Không dùng `0.0.0.0` làm `ARENA_LAN_BIND_IP`. Trên Linux, chạy `stat -c '%g' /var/run/docker.sock` và điền đúng kết quả vào `DOCKER_SOCKET_GID` trong `.env`; không mặc định socket thuộc group 0, không `chmod 666`.

**Chính sách Offline hiện tại:** `compose.exam.yaml` bật HTTPS Caddy nội bộ, Account-Only, bắt buộc **Admin TOTP**, tắt tự đăng ký Player và không dùng SMTP. Ban tổ chức phải chuẩn bị tài khoản người chơi và Authenticator của Admin **trước ngày thi**. Đây là cấu hình khác với pilot online chỉ dùng username/password.

### 1.2. Khởi tạo database, Admin và dịch vụ LAN

Trên máy chủ LAN riêng (không chạy các lệnh này trên EC2 đang phục vụ website online):

~~~bash
docker compose -f compose.yaml -f compose.exam.yaml config -q
docker compose -f compose.yaml -f compose.exam.yaml build

# Chỉ trên database mới, khi Arena chưa chạy:
docker compose -f compose.yaml -f compose.exam.yaml run --rm --no-deps arena python -m backend.admin_cli --data-dir /app/data migrate
docker compose -f compose.yaml -f compose.exam.yaml run --rm --no-deps arena python -m backend.admin_cli --data-dir /app/data create-admin --username organizer
docker compose -f compose.yaml -f compose.exam.yaml run --rm --no-deps arena python -m backend.admin_cli --data-dir /app/data enroll-admin-totp --username organizer

docker compose -f compose.yaml -f compose.exam.yaml up -d --no-build --wait
docker compose -f compose.yaml -f compose.exam.yaml ps
~~~

Mật khẩu và secret MFA được nhập qua terminal tương tác, không ghi vào command history. Nếu đã có dữ liệu, **dừng writer, sao lưu và thử phục hồi trước khi migrate**.

Caddy dùng CA nội bộ (không cần Let's Encrypt). Khi Gateway đã chạy, lấy **chỉ chứng chỉ CA công khai** để cài vào kho tin cậy trên các máy thi được quản lý:

~~~bash
docker compose -f compose.yaml -f compose.exam.yaml cp gateway:/data/caddy/pki/authorities/local/root.crt ./arena-exam-root.crt
~~~

Giữ DNS nội bộ và đồng hồ máy đúng; mở `https://arena.exam.test` trên máy thí sinh mà **không** có cảnh báo TLS. Không sao chép private key CA hoặc vô hiệu kiểm tra HTTPS.

### 1.3. Quy trình vận hành ngày thi

1. **Diễn tập:** Trước khi ngắt WAN, thử đăng nhập Admin/Player, nộp bot Python/C++/Java, một trận Official, kết quả và replay trên **máy thí sinh thật**.
2. **Cách ly mạng:** Đội mạng ngắt Internet của VLAN/phòng thi nhưng **giữ LAN và DNS**; kiểm tra IPv4/IPv6, proxy/VPN, Wi-Fi phụ, hotspot. File Compose **không tự cách ly Internet vật lý**. Không mở SSH, Docker API hoặc port 8000/9000 cho máy thi.
3. **Tổ chức:** Admin cấu hình game/luật, Season/Tournament và fixture. Captain chọn Active Bot trước `bot_lock_at`. Lịch `scheduled_at` quyết định khi nào chạy Official; giám sát kết quả, bảng điểm và replay.
4. **Giám sát:** Theo dõi Arena/Controller, hàng chờ, tài nguyên, nguồn điện và mạng. Không sửa luật đã công bố hoặc bảo trì Docker giữa trận.
5. **Kết thúc:** Xác minh trận hoàn tất, công bố kết quả, sao lưu dữ liệu ra thiết bị độc lập. Nếu restart khi offline, dùng `up -d --no-build --wait` với **cùng hai file Compose**, không tải lại image từ Internet.

**Công bố kết quả Offline lên Online (tùy chọn):** Admin có thể xuất gói JSON có chữ ký HMAC, Admin online kiểm tra và công bố kết quả theo danh mục riêng. **Không chuyển account, bot hay replay.** Cần `ARENA_OFFLINE_RESULTS_KEY` chung và kiểm thử import end-to-end trên staging trước. **Compose B1.5 hiện tại chưa đưa khóa này vào Arena mặc định**; không sửa cấu hình pilot đã pin để nhập trực tiếp vào production. Xem [Exam LAN](docs/EXAM_MODE.md) và [Offline → Online](docs/OFFLINE_RESULTS_TRANSFER.md).

## 2. Hướng dẫn tổ chức giải Online (AWS EC2)

### 2.1. Kiến trúc hiện tại

- **Public website:** [NEON ARENA](https://traitimcodon.duckdns.org); người chơi đăng ký/đăng nhập, lập Team, nộp bot và theo dõi giải.
- **AWS EC2:** Arena + Caddy, database, source uploads, kết quả và replay; Docker project `neon-b1-ec2-pilot`.
- **Local:** Controller xử lý bot ngay trên EC2.
- **Remote:** một PC xử lý bot bằng Controller + Agent kết nối **HTTPS outbound** tới AWS; không mở Docker socket/port 9000 qua Internet.

Các lệnh tiếp theo chỉ để **vận hành B1.5 đã chuẩn bị**, không phải tạo AWS production từ đầu. Khi dựng mới, cần quy trình DNS/TLS, tài khoản Admin, backup và cấu hình riêng; xem [B1.4](docs/B1_EC2_FAST_PILOT.md), [B1.5](docs/B15_SHARED_PILOT_RUNNER_SWITCH.md). **Không chạy Docker Compose build/up trực tiếp trên pilot đang hoạt động.**

### 2.2. Trước giờ mở giải

Trên terminal **Ubuntu EC2**:

~~~bash
cd ~/neon-arena-b1-pilot
sudo python3 -m scripts.b15_pilot_runner status
~~~

Kỳ vọng `ready: true`, `admission_closed: false` và `mode: local` hoặc `mode: remote` đúng kế hoạch. Nếu Remote thì Worker PC phải online. Kiểm tra HTTPS, Admin, Player và chạy một trận luyện + replay.

Trước giải thật, chọn **đường dẫn backup chưa tồn tại**, chạy lúc không có job (website có thể gián đoạn):

~~~bash
sudo python3 -m scripts.b15_pilot_runner backup --backup-directory .runner-switch/b15-backup-event01 --approve-downtime
~~~

Chỉ sử dụng sau khi nhận `verified_cold_restore_drill`; lưu thêm bản sao **ngoài EC2** an toàn (backup chứa cả khóa). Bản sao lưu được ràng buộc với **plan/image đã pin**; thay đổi runtime/cấu hình cần chuẩn bị và xác minh lại.

### 2.3. Quy trình Admin và Player

1. Admin chọn game, công bố luật, tạo Season/Tournament. Player đăng ký, tạo/tham gia Team, nộp bot; Captain chọn Active Bot hợp lệ.
2. Captain đăng ký Team khi mở; Admin chốt Team, tạo bracket/fixture.
3. Admin đặt giờ khóa bot (`bot_lock_at`), giờ đấu (`scheduled_at`) và luật theo vòng; hệ thống chốt bot/source/artifact phù hợp.
4. Theo dõi Runner, hàng chờ, trận `BLOCKED`/`INTERRUPTED`; không đổi máy chạy bot khi có trận, compile hoặc upload đang chạy. Scrimmage không tính điểm giải.
5. Kiểm tra replay và bảng điểm trước khi công bố. Sao lưu trước khi nâng cấp hoặc thay máy.

Xem [Team/Season](docs/TEAM_TOURNAMENTS.md), [Round Rules](docs/ROUND_RULES.md), [Operations](docs/OPERATIONS.md).

### 2.4. Đổi nơi chạy bot (B1.5)

Trên EC2 tại `~/neon-arena-b1-pilot`, **chỉ chọn một** lệnh switch phù hợp với mode hiện tại:

~~~bash
# Chạy bot trên AWS EC2:
sudo python3 -m scripts.b15_pilot_runner switch --target local --backup-directory .runner-switch/b15-backup-event01

# Chạy bot trên PC đã bật Worker ở mục 3:
sudo python3 -m scripts.b15_pilot_runner switch --target remote --backup-directory .runner-switch/b15-backup-event01

# Kiểm tra sau lần chuyển:
sudo python3 -m scripts.b15_pilot_runner status
~~~

`b15-backup-event01` là **ví dụ**, chỉ dùng nếu đã tạo/kiểm thử bản backup đó; máy hiện tại có thể đang dùng bản hợp lệ khác như `b15-backup-002`. **Không chạy cả hai lệnh chuyển liên tiếp**. Nếu trả `BLOCKED`, xem status/runbook, không chạy lại vô điều kiện hay tự sửa JSON đã pin. Website/database AWS không đổi; artifact biên dịch của EC2 và PC là hai kho riêng, có thể cần nộp hoặc biên dịch lại bot.

## 3. Thiết lập PC/server mạnh làm Remote Runner cho giải Online

PC trường **chỉ xử lý bot**; website, tài khoản và kết quả vẫn trên AWS. **Một PC mạnh không đồng nghĩa với nhiều Runner hoặc nhiều trận đồng thời.**

### 3.1. Cài đặt lần đầu trên Windows

Chuẩn bị Git, Docker Desktop ở chế độ **Linux Containers + WSL2**, Ethernet ổn định, nguồn/UPS và đủ CPU/RAM/dung lượng. Chọn revision/protocol Worker **tương thích với Arena đang triển khai**; không tự cập nhật giữa giải.

Trong **PowerShell**:

~~~powershell
git clone https://github.com/hungdo2006/battlecode_MIT_Group_8.git neon-arena-school-worker
cd neon-arena-school-worker
New-Item -ItemType Directory -Force .b1-pilot | Out-Null
Copy-Item deploy/b1-ec2-pilot-worker.env.example .b1-pilot/worker.env
~~~

Chỉnh file riêng tư `.b1-pilot/worker.env`:

~~~dotenv
ARENA_REMOTE_SERVER_URL=https://traitimcodon.duckdns.org
ARENA_REMOTE_RUNNER_KEY=<SHARED_MACHINE_KEY_TRUNG_AWS>
ARENA_RUNNER_TOKEN=<TOKEN_RIENG_NGAU_NHIEN_32_PLUS_CHARACTERS>
SANDBOX_NAMESPACE=neon-school-worker
DOCKER_SOCKET_GID=0
~~~

- `ARENA_REMOTE_RUNNER_KEY`: **cùng machine key Cloud đang dùng**, chuyển từ người vận hành AWS bằng kênh an toàn. Không gửi lên GitHub/chat/log.
- `ARENA_RUNNER_TOKEN`: khóa **khác** machine key, ngẫu nhiên ít nhất 32 ký tự, chỉ tồn tại trên PC; không phải mật khẩu Admin.
- `DOCKER_SOCKET_GID=0` phù hợp Docker Desktop đã thử nghiệm. Với PC **Ubuntu**, chạy `stat -c '%g' /var/run/docker.sock` và điền **GID thực** trước khi chạy Compose, nếu không Controller có thể `PermissionError(13)`. Trên Linux dùng Docker Engine/Compose và `sudo` nếu cần.
- Không chuyển/copy database AWS sang PC; máy PC có volume artifact riêng.

Khởi động (Docker Desktop đã chạy):

~~~powershell
docker compose --env-file .b1-pilot/worker.env -p neon-b1-worker -f compose.remote-worker.yaml up -d --build --wait
docker compose --env-file .b1-pilot/worker.env -p neon-b1-worker -f compose.remote-worker.yaml ps
~~~

`agent` và `controller` chạy/healthy; `bot-image` build xong thoát là bình thường. PC chỉ kết nối **outbound HTTPS 443** tới AWS; **không port-forward** router, không expose Controller 9000 hoặc Docker API.

### 3.2. Đổi từ laptop cũ sang PC của trường

Làm **trong cửa sổ bảo trì, không có job đang chạy**:

1. Nếu AWS đang ở **Remote laptop**, trên EC2 `switch --target local` theo mục 2.4 và xác nhận `ready: true`. Nếu đã Local thì bỏ qua bước này.
2. Trên **laptop cũ**, dừng riêng agent để tránh hai Worker cùng dùng machine key:

   ~~~powershell
   docker compose --env-file .b1-pilot/worker.env -p neon-b1-worker -f compose.remote-worker.yaml stop agent
   ~~~

3. Trên **PC trường**, giữ Worker mục 3.1 chạy; nếu agent đã tạo nhưng đang dừng, bật lại:

   ~~~powershell
   docker compose --env-file .b1-pilot/worker.env -p neon-b1-worker -f compose.remote-worker.yaml start agent
   ~~~

4. Trên **EC2** `switch --target remote` dùng **cùng backup hợp lệ**; kiểm tra `mode: remote`, `ready: true`, `transport: remote-outbound`, `admission_closed: false`.
5. Trên website chạy trận thử và replay; nghiệm thu xong mới mở giải.

**Không bật đồng thời hai agent dùng chung machine key; không hoán đổi PC giữa trận đang xử lý.**

### 3.3. Chuyển về EC2 hoặc xử lý sự cố

Đợi không còn trận/compile/upload, trên EC2 `switch --target local` rồi kiểm tra status. Sau khi Local sẵn sàng có thể dừng agent PC. Muốn chuyển trở lại PC, bật agent và `switch --target remote`, kiểm tra readiness.

Nếu PC mất mạng/điện giữa trận, **không tự cho bot thua, không phát lại trận không chắc trạng thái, không ép switch khi drain thất bại**. Ban tổ chức xác minh job/lease và xử lý `INTERRUPTED`/`BLOCKED` theo [B1.5 runbook](docs/B15_SHARED_PILOT_RUNNER_SWITCH.md).

### 3.4. Giới hạn mở rộng

B1.5 hiện **1 Remote Worker, 2 trận đồng thời**, cùng các giới hạn CPU/RAM/PID của sandbox. Máy mạnh hơn tăng khả năng đáp ứng tài nguyên nhưng **không tự mở rộng scheduler**. Chạy nhiều PC hoặc tăng số trận cần nâng cấp phân phối job, quota, giám sát và kiểm thử tải riêng. Trước giải thật hãy diễn tập với số đội dự kiến, Python/C++/Java, Official/Scrimmage, queue, gián đoạn PC và backup ngoài EC2.

## Tài liệu tham khảo

| Mục đích | Tài liệu |
| --- | --- |
| Mạng LAN, TLS nội bộ | [Exam Mode](docs/EXAM_MODE.md) |
| Xuất/nhập kết quả offline | [Offline Results Transfer](docs/OFFLINE_RESULTS_TRANSFER.md) |
| Chuyển Runner B1.5, backup/rollback | [B1.5 Runner Switch](docs/B15_SHARED_PILOT_RUNNER_SWITCH.md) |
| Bối cảnh pilot AWS | [B1.4 EC2 Pilot](docs/B1_EC2_FAST_PILOT.md) |
| Team, Season và Tournament | [Team Tournaments](docs/TEAM_TOURNAMENTS.md) |
| Vận hành/migration | [Operations](docs/OPERATIONS.md) |
| Luật thi đấu | [Round Rules](docs/ROUND_RULES.md) |
| Regression/giới hạn QA | [QA](docs/QA.md) |

**An toàn:** Không commit `.env`, `.b1-pilot/`, `.runner-switch/`, khóa hoặc backup. Không chạy `docker compose down -v`, `docker system prune --volumes` hoặc trộn `compose.exam.yaml` với `compose.public.yaml`. Khi đổi runtime/cấu hình trên EC2 phải có backup, review và kiểm thử riêng.
