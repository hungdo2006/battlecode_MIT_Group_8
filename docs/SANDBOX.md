# NEON ARENA v4.0 — Phase 2 Docker Bot Sandbox

## Khởi chạy trên Windows Docker Desktop

Dùng Docker Desktop **Linux containers**, WSL2. `docker version` phải có Server;
`docker compose version` phải chạy được. Trong PowerShell ở thư mục dự án:

```powershell
py -3 scripts/configure_sandbox.py
docker compose up --build -d --wait
docker compose ps
Invoke-RestMethod http://localhost:8000/api/health
```

Script cấu hình tạo mã ngẫu nhiên trong `.env`, không in mã và không thay giá trị
đã cấu hình. Mở `.env` trên máy để lấy `ARENA_ADMIN_CODE`; không commit/chia sẻ file.
Nếu `.env` cũ có mã Organizer yếu, tự thay mã đó. `ARENA_RUNNER_TOKEN` phải ngẫu nhiên,
ít nhất 32 ký tự, khác mã Organizer. Không gửi token cho Player.

Website: `http://localhost:8000`. Máy khác cùng LAN dùng `http://<IPv4-laptop>:8000`.
`ARENA_BIND_IP=0.0.0.0` cho LAN; firewall chỉ cần cho phép TCP8000 trên mạng Private.
Không mở TCP9000, Docker API2375/2376 hoặc chuyển tiếp cổng router. Chỉ backend
publish cổng8000. Frontend tiếp tục lấy HTTP/WS hostname từ website.

Linux dùng `python3 scripts/configure_sandbox.py` rồi các lệnh Compose trên. Socket
group được script dò từ `/var/run/docker.sock`; nếu dùng `.env` đã có group, kiểm tra:
`stat -c %g /var/run/docker.sock`. Không `chmod 666` socket và không chuyển controller
sang root để bỏ qua lỗi permission. Rootless/remote Engine chưa được xác nhận.

```powershell
docker compose logs -f arena controller
docker compose restart arena
docker compose stop
docker compose start
docker compose down       # giữ named volumes; không thêm -v
docker compose up -d --wait
```

## Kiến trúc thực tế

- `arena`: FastAPI, một worker, Game Adapters, Lobby, HTTP/WebSocket và replay.
  Không có socket, Docker SDK hoặc artifact volume của controller.
- `controller`: API chỉ trên network `runner_private` có `internal: true`, không
  publish cổng; mọi thao tác quản lý yêu cầu bearer token. Không dùng cookie/CORS,
  không có API nhận Docker command/image/mount tùy ý. Body tối đa1MiB.
- `bot-image`: bước build image toolchain, chạy `/bin/true` rồi thoát; không chạy bot.
- Mỗi submission có compile container tạm. Mỗi bot có runtime container riêng tồn tại
  suốt trận, gồm các ván OTT. Không tạo container mỗi lượt. Compiler không chạy trong
  backend/controller. Python được syntax-check trong compile container.
- Source/artifact đi qua exec pipes của Docker API và helper cố định, không dùng
  host bind paths. Helper kiểm tra tên file, `O_NOFOLLOW`, file thường, không hardlink.
  Controller kiểm tra lại tar entry, đường dẫn, kích thước, ELF/JVM magic và SHA256.
  Không dùng `extractall`. Java hỗ trợ `Main` ở default package như protocol cũ,
  gồm inner classes; không hỗ trợ cấu trúc package/thư viện ngoài.
- Controller pin image ID khi khởi động. Đổi toolchain image cần nộp lại source nếu
  artifact không tương thích. Không tự chạy artifact legacy trong backend.

Controller là thành phần **đặc quyền cao**: Docker socket có thể cho phép quản lý
toàn daemon/host; trên Desktop là daemon trong Linux VM và các tài nguyên host được
chia sẻ. Socket chỉ mount ở controller. LAN không có cổng truy cập controller;
host administrator/Docker administrator vẫn thuộc vùng tin cậy và có thể tiếp cận
container. Nếu không chấp nhận rủi ro này, dùng Linux VM/máy riêng cho đồ án.

## Policy container cố định

| Thuộc tính | Compile | Runtime mỗi bot |
|---|---:|---:|
| CPU | 1 | 1 |
| RAM và memory+swap | 512MiB | 256MiB |
| PID, gồm JVM threads | 128 | 64 |
| `/work` tmpfs | 128MiB, exec | 32MiB, exec |
| `/tmp` tmpfs | 16MiB, noexec | 16MiB, noexec |
| `/dev/shm` | 1MiB, private IPC | 1MiB, private IPC |
| Một file | 16MiB | 16MiB |
| Open files | 128 | 128 |

UID/GID10001; rootfs read-only; drop ALL capabilities; no-new-privileges; Docker
default seccomp; `network_mode: none`; không host PID/IPC/network, privileged,
device hoặc persistent/host mount. Network none còn loopback riêng; không có mạng
ra ngoài. Bot vẫn đọc được file hệ điều hành trong image, **không** có backend,
secrets, upload khác hoặc Docker socket. Không tuyên bố mọi file đều bị che giấu.

Giữ protocol JSON Lines UTF-8: một observation stdin, một action stdout. Phản hồi
đầu 3s, sau đó1s; compile30s. Startup/transfer Docker có timeout riêng. Stdout4KiB/dòng,
256KiB/trận, stderr64KiB/trận; compiler diagnostics32KiB. Java17 runtime dùng
heap64MiB, SerialGC và ActiveProcessorCount1; đã thử trong budget256MiB/64PID.
Mỗi controller tối đa1 compile +4 runtime (2 trận). Artifact tối đa16MiB/256 files;
kho artifact tối đa512MiB, hết quota từ chối nộp mới và yêu cầu operator xử lý,
không tự xóa bài nộp cũ. Docker log driver của bot là `none`; application/controller
logs quay vòng5MiB ×2. Metadata/replay vẫn cần operator theo dõi dung lượng ổ đĩa.

## Restart, cancellation và lỗi hạ tầng

Backend heartbeat5s; lease hết hạn20s; reaper quét2s. Backend mới không được chiếm
lease còn sống; shutdown bình thường release lease, crash phải đợi hết hạn.
Controller restart thu hồi container đúng namespace, đổi epoch và cấp lease mới;
runtime cũ không được tiếp tục. Tombstone giữ120s tính từ closed_at; ledger compact
chặn tái sử dụng ID suốt epoch. Xem [Security Foundation](SECURITY_FOUNDATION.md).
Observation có sequence/hash: duplicate trả cache, không đưa lại vào stdin. Client
không tự retry action khi mất response. Các request lệch thứ tự bị từ chối.

Close idempotent; lỗi close được retry, controller giữ handle để dọn khi Engine phục
hồi. Runtime bị thu hồi tối đa sau1 giờ để tránh giữ tài nguyên vô hạn (phù hợp giới
hạn lượt hiện tại). Mất Engine có thể làm cleanup chậm; không thể bảo đảm dọn ngay
trong lúc daemon không phản hồi. Không dùng namespace chung cho hai deployment.

Bot JSON lỗi/timeout/crash/vượt output gây bot fault. Mất controller/Engine/lease
gây `interrupted`, reason `runner_unavailable`, không tính thắng cho đối thủ.
Sandbox không có fallback legacy. `/api/health` trả503 khi controller chưa sẵn sàng.

## Kiểm tra sandbox thật

`/api/health` phải có `runner.mode = sandbox`, `runner.ready = true`. Đây chỉ là
readiness; kiểm tra tiếp khi một trận đang chạy:

```powershell
docker ps --filter label=io.neonarena.sandbox=neon-arena
docker inspect <BOT_CONTAINER_ID> --format '{{json .HostConfig}}'
docker inspect <BOT_CONTAINER_ID> --format '{{json .Mounts}}'
docker inspect <BOT_CONTAINER_ID> --format '{{.Config.User}}'
```

Xác minh `NetworkMode=none`, `ReadonlyRootfs=true`, `Privileged=false`,
`Memory=268435456`, `MemorySwap=268435456`, `PidsLimit=64`,
`NanoCpus=1000000000`, CapDrop ALL, no-new-privileges, LogConfig none,
User10001:10001 và không host/volume mounts. Sau trận không còn job container.
Kiểm tra `.HostConfig` backend không có Docker socket; controller không có
published ports và chỉ nối `runner_private`.

## Kiểm thử có thể chạy lại

Host cần Python dependencies/requirements-dev; `--browser` cần Playwright + Chrome.
Acceptance checker dùng tags image QA riêng, mặc định chỉ publish loopback;
`--build` tạo đủ ba QA images mà không thay tags của ứng dụng thật:

```powershell
py -3 -m pytest -o addopts="" -q
py -3 scripts/check_docker.py --build --browser
py -3 scripts/check_sandbox_lifecycle.py
```

Acceptance checker tạo project/volume ngẫu nhiên, token/namespace riêng, chạy sáu
cặp ngôn ngữ/hai game/ba WebSocket, invitation/decline, replay, restart controller,
restart backend, down/up, artifact reuse và backup. Chỉ dọn tài nguyên QA của nó.

Controller unit tests chạy riêng, không cần Docker socket trong test container:

```powershell
docker build -f Dockerfile.controller --target tests -t neon-arena-controller:tests .
docker run --rm --network none --read-only --memory 256m --pids-limit 64 --cap-drop ALL --security-opt no-new-privileges:true --tmpfs /tmp:rw,nosuid,nodev,size=32m,uid=10001,gid=10001 neon-arena-controller:tests
```

Probe lỗi/tài nguyên **chỉ chạy trên stack bỏ đi**, namespace kết thúc bằng `-test`.
Tạo file riêng `.env.sandbox-test` theo `.env.example`, đổi port18020,
SANDBOX_NAMESPACE=neon-sandbox-test và dùng token/code ngẫu nhiên riêng:

```powershell
docker compose --env-file .env.sandbox-test -p neon-sandbox-test up --build -d --wait
docker compose --env-file .env.sandbox-test -p neon-sandbox-test stop arena
Get-Content scripts/probe_sandbox.py -Raw | docker compose --env-file .env.sandbox-test -p neon-sandbox-test exec -T -e SANDBOX_TEST_ACK=1 controller python - all
docker compose --env-file .env.sandbox-test -p neon-sandbox-test up -d --wait
docker compose --env-file .env.sandbox-test -p neon-sandbox-test down
```

Probe không thực thi fixture trong controller: tất cả code được nộp qua compile API
và chạy trong bot container. Probe có Docker SDK chỉ để kiểm tra policy/cleanup;
từ chối namespace production. Không copy/chạy fixture lỗi bằng Python host.

## Dữ liệu và rollback về Phase1

Giữ nguyên `arena_data`, `arena_uploads`; thêm `arena_artifacts`, chỉ controller
mount volume này. Không migrate/xóa source, submission, history hoặc replay cũ.
Submission legacy vẫn hiển thị nhưng cần nộp lại để có sandbox artifact. Cache sample
phân biệt runner. Mỗi trận giữ game_id/rules_snapshot và replay riêng như trước.

Sao lưu khi đã đóng cuộc thi và không còn job; script không chứa `.env`:

```powershell
docker compose stop arena
docker compose stop controller
py -3 scripts/backup_docker.py --output backups/neon-arena-phase2.tar.gz
docker compose up -d --no-build --wait
```

Archive có data/, uploads/, artifacts/ và manifest hash; image archive + receipt
đi kèm giữ exact toolchain IDs. Chỉ restore vào volumes mới theo
[runbook](SECURITY_FOUNDATION.md). Cất `.env` riêng ở nơi an toàn.
Rollback có chủ đích, chỉ bot đáng tin cậy:

```powershell
# Đóng cuộc thi, chờ/hủy trận, xác nhận không còn bot container và sao lưu trước.
docker compose down
docker compose -f compose.legacy.yaml up --build -d --wait
```

Compose legacy dùng cùng project/volumes data/uploads, đặt `ARENA_RUNNER=legacy`,
không có controller/socket. Artifact volume vẫn tồn tại. Bot sandbox cần nộp lại
source trong legacy; không tự chuyển runner hoặc command. Trở lại sandbox:

```powershell
docker compose -f compose.legacy.yaml down
docker compose up --build -d --wait
```

`start.bat` vẫn là legacy native cho nhóm tin cậy; không phải sandbox. Không triển
khai tính năng chạy code công khai lên Internet. Container chia sẻ kernel và không
ngăn được mọi kernel/Engine escape, side channel hoặc tấn công vào controller.

Nguồn: [Docker security](https://docs.docker.com/engine/security/),
[resource limits](https://docs.docker.com/engine/containers/resource_constraints/),
[network none](https://docs.docker.com/engine/network/drivers/none/),
[Docker SDK exec](https://docker-py.readthedocs.io/en/stable/api.html).
