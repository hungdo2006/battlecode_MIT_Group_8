> Tài liệu Phase1 được lưu để tham khảo. Compose mặc định hiện dùng Phase2; xem [SANDBOX.md](SANDBOX.md). Để chạy kiến trúc trong tài liệu này, dùng `docker compose -f compose.legacy.yaml ...`.

# NEON ARENA v4.0 — Phase 1 Docker infrastructure

Giữ FastAPI, frontend Cyberpunk, GameRegistry/adapters, lobby và runner subprocess v3. Một Compose service `arena`, một Uvicorn worker. Không có database server, Docker socket, privileged mode hay container riêng cho bot. Phase2 sandbox không nằm trong thay đổi này.

## Khởi động

Windows: Docker Desktop đang chạy, WSL2/Linux containers. Linux: Docker Engine và Compose plugin. `docker version` phải hiện Server OS/Arch linux. Không dùng Windows containers. Kiểm tra `docker compose version`.

1. Copy `.env.example` sang `.env` (PowerShell: `Copy-Item .env.example .env`; Linux: `cp .env.example .env`). Không ghi đè `.env` đã có.
2. Sửa `ARENA_ADMIN_CODE=` thành mã riêng của nhóm. File example cố ý không có mật khẩu mẫu. Mã trống vẫn cho server chạy nhưng không mở quyền Organizer. `.env` được Git và Docker build context bỏ qua; mã chỉ truyền vào container ở runtime. Shell environment có thể override `.env`; tránh để biến cũ trong shell gây nhầm cấu hình.
3. Chạy `docker compose up --build`. Host mở `http://localhost:8000`. Có thể chạy nền bằng `docker compose up -d --build --wait`.
4. Mở Organizer, chọn game/lưu luật/Open; hai Player nộp bot/Active Bot, nhận invitation/Accept như [demo ba laptop](MULTIPLAYER.md). Python, G++ và Java chỉ cần trong image; máy Player chỉ cần browser.

Dockerfile dùng `python:3.13-slim-bookworm`, apt `g++` và `openjdk-17-jdk-headless`. JDK compiler/runtime lấy cùng cặp từ PATH bằng runner hiện có, không hardcode JAVA_HOME theo kiến trúc CPU. Source Python compile bằng interpreter container, C++ `-std=c++17 -O2`, Java `javac -encoding UTF-8` và heap64MiB như v3.

Runtime cuối không có Node/pytest/test data; target `tests` tùy chọn thêm chúng để chạy regression Linux. Không thay dependencies ứng dụng hay tạo `.venv` Windows trong image. Image copy rõ backend/frontend/samples/run.py/healthcheck và hai script demo; không COPY toàn bộ workspace. `.dockerignore` loại Git, môi trường local, secrets, uploads/data, archives và screenshots.

User runtime `arena:arena`, UID/GID10001; hai folder volume được tạo đúng owner trong image để volume mới có quyền ghi. Code/image đọc được, dữ liệu ghi vào volumes; không có entrypoint chown toàn bộ dữ liệu hoặc migration tự động. `cap_drop: ALL`, `no-new-privileges`, `init:true`, stop grace30s; Uvicorn giới hạn chờ shutdown20s. Không scale thêm worker/replica vì state/lock/JSON vẫn một process.

## Cấu hình và LAN

| Biến trong .env | Mặc định | Ý nghĩa |
| --- | --- | --- |
| ARENA_ADMIN_CODE | trống | Mã backend xác minh Organizer; không build ARG/ENV trong image |
| ARENA_BIND_IP | 0.0.0.0 | Host publish interface; 127.0.0.1 chỉ host |
| ARENA_PORT | 8000 | Port trên host, container luôn8000 |
| ARENA_READ_ONLY | 0 | Giữ LAN demo; 1 chặn API mutation như v3 |
| ARENA_ALLOWED_HOSTS | trống | Hostname bổ sung theo chính sách network hiện tại; named/public hosts cần read-only |

Compose `.env` không tự áp dụng cho `start.bat`; native đọc environment shell. CMD trong image bind0.0.0.0:8000 độc lập port host; không dùng ARENA_PORT runtime để vô tình lệch publish/healthcheck. Nếu sửa biến môi trường, dùng `docker compose up -d` để recreate; `restart` đơn thuần không cập nhật environment.

LAN dùng IPv4 Wi-Fi/Ethernet **của host**, ví dụ `http://192.168.2.16:8000`; không phải container bridge172.x hay `0.0.0.0`. Docker Desktop publish port qua host. PowerShell `ipconfig`, Linux `ip addr`. Các gợi ý `/api/network` trong container có thể là bridge IP; không dùng chúng trên laptop khác. Frontend không sửa: HTTP tương đối, WebSocket theo location.host và ws/wss.

Kiểm tra Windows firewall Private/TCP8000/LocalSubnet và AP isolation theo [NETWORKING.md](NETWORKING.md). Linux nếu dùng firewall, chỉ cho subnet LAN tin cậy; Docker có cơ chế NAT/iptables riêng, không mặc định coi luật UFW là đã chặn mọi published port. Không mở port-forward router/tunnel/public Internet cho runner. Docker hóa chưa thay thế sandbox.

## Logs, health và vận hành

```text
docker compose ps
docker compose logs -f --tail=100 arena
docker compose exec -T arena python deploy/healthcheck.py
docker compose stop arena
docker compose start arena
docker compose restart arena
docker compose down
docker compose up -d
```

Healthcheck stdlib Python gọi loopback `/api/health`, xác nhận status và đường dẫn Python/G++/javac/java; không cần curl trong image hoặc mã quản trị. Docker kiểm tra mỗi15s, timeout5s, startup20s, retry3. Nó là readiness/liveness cơ bản; không compile bot mỗi15s. Health unhealthy không tự restart service chỉ vì unhealthy; `restart:unless-stopped` áp dụng khi process thoát, operator xem logs để xử lý lỗi.

`docker compose down` thông thường giữ named volumes. Không chạy `docker compose down -v`, `docker volume prune` hay Docker Desktop reset nếu cần giữ dữ liệu. Start sau restart giữ cookie/Active Bot/game lock; quyền Organizer cần nhập lại mã. Pending/partially accepted invitations bị CANCELLED/server_restart; match đang chạy bị interrupted theo logic v3, không tự resume bot execution. Replay/history vẫn giữ.

## Dữ liệu bền vững

| Volume mặc định | Container path | Nội dung |
| --- | --- | --- |
| neon-arena_arena_data | /app/data | bots.json, sessions.json, players.json, rules.json, invitations.json, matches.json và replays/*.jsonl/*.json |
| neon-arena_arena_uploads | /app/uploads | Source bot, Python compile cache, C++ executable, Java classes |

Compose project mặc định cố định `neon-arena`, không phụ thuộc tên folder checkout. Nếu dùng `-p demo2`, volumes là `demo2_arena_data`/`demo2_arena_uploads`; dùng lại cùng project để thấy dữ liệu cũ. Không attach cùng hai volume vào hai server đang chạy.

`data/` và `uploads/` có sẵn trên laptop không bị copy/mount/sửa bởi Compose. Docker mặc định bắt đầu phòng mới với volumes riêng. Không mount nguyên folder Windows vào `/app` hoặc `.venv` vào image. Bot metadata chứa absolute command/folder; executable C++ Windows không chạy được trên Linux, class/architecture/runtime cũng có thể khác. Không dùng trực tiếp volume/metadata native để giả lập bot READY trong Docker. Giữ bản native làm archive, nộp lại source dưới phiên Docker; muốn chuyển lịch sử giữa môi trường hãy sao lưu và thực hiện migration riêng có kiểm tra. Phase1 không tự migrate hoặc xóa dữ liệu.

Restart/recreate cùng image và hai volume: absolute paths trong container vẫn `/app/uploads/...`; artifacts compile một lần được dùng lại. Đổi CPU architecture hoặc nâng runtime/ABI đáng kể có thể cần nộp/compile lại; không tự xóa submission cũ.

## Sao lưu

Đợi match kết thúc hoặc Organizer cancel hợp lệ, dừng service để JSON/JSONL đồng nhất. Backup **cả hai** volume cùng lúc. Mã `.env` không nằm trong archive; lưu cấu hình đó riêng theo cách quản lý của nhóm.

PowerShell:

```powershell
docker compose stop arena
# Script backup_docker.py hiện dành cho Phase2 ba volumes; với Phase1 dùng
# phương án Docker tar bên dưới. Với Phase2 đọc SECURITY_FOUNDATION.md.
docker compose start arena
```

`scripts/backup_docker.py` hiện yêu cầu stopped arena/controller và đủ ba named
volumes của Phase2; không dùng cho stack legacy chỉ có hai volumes. Quy trình mới
có checksum, pinned image archive và restore vào volumes mới ở
[Security Foundation](SECURITY_FOUNDATION.md). Phần tar dưới đây chỉ là hướng dẫn
Phase1 cũ, không bao gồm sandbox artifacts.

Cách chỉ dùng Docker, không cần Python trên host (chọn tên backup/container chưa tồn tại):

```text
docker compose stop arena
docker compose run --name neon-arena-backup --no-deps --entrypoint tar arena -czf /tmp/neon-arena.tar.gz -C /app data uploads
docker cp neon-arena-backup:/tmp/neon-arena.tar.gz ./neon-arena-backup.tar.gz
docker rm neon-arena-backup
docker compose start arena
```

Lệnh rm chỉ xóa container utility đã đặt tên, không xóa named volumes. Đưa archive ra ổ đĩa khác; `docker cp` không đi qua text pipeline. Khi khôi phục, thử trên project/volume mới và không ghi đè volume đang có dữ liệu. UID/GID runtime10001 cần quyền đọc/ghi khi dùng bind mount Linux tùy chỉnh; named volumes mặc định tránh vấn đề owner host. Không chạy app bằng root để chữa lỗi quyền chung.

## Kiểm chứng

```text
docker compose --env-file .env.example config --quiet
docker compose build arena
docker build --target tests -t neon-arena:4.0-tests .
docker run --rm --init neon-arena:4.0-tests
docker run --rm --init neon-arena:4.0-tests node --test docs/reference/ottv2/tests/rules.test.js
```

Acceptance trên host có Python và requirements ứng dụng:

```text
python scripts/check_docker.py --lan-ip IP-WIFI-CUA-HOST
python scripts/check_docker.py --lan-ip IP-WIFI-CUA-HOST --browser
```

Bỏ --lan-ip thì dùng loopback. Bật --browser cần Playwright/Chrome như QA v3. Checker dùng random project `neon-arena-qa-*`, random code runtime, port publish ngẫu nhiên, hai volume riêng. Thực thi upload/compile sáu cặp ngôn ngữ, hai game, invitation/Accept/Decline, ba WS/replay, restart, ordinary down/up tạo container mới, hash source/artifacts giữ nguyên và chạy lại bot không compile. Backup tar được mở kiểm tra đầy đủ records. Cleanup chỉ xóa QA volumes sau xác minh label/project, không đụng `neon-arena_*` hoặc data/uploads native. Không mount Docker socket vào app: Docker CLI chỉ chạy trên host trong checker.

Docker test target chạy toàn bộ tests cũ bên trong Linux cùng compiler/runtime thật; Node chỉ trong target tests để test luật OTT tham chiếu. Script checker là integration test môi trường thật, không mock Docker/API/bot.

Nguồn chính thức: [Compose](https://docs.docker.com/compose/intro/compose-application-model/), [named volumes](https://docs.docker.com/engine/storage/volumes/), [down và tùy chọn volumes](https://docs.docker.com/reference/cli/docker/compose/down/), [.env interpolation](https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/), [Docker và firewall Linux](https://docs.docker.com/engine/network/packet-filtering-firewalls/).
