# Security Foundation — final review và Docker QA

Ngày 2026-10-17; branch `feature/player-admin-access`; HEAD đầu lượt `875a07c`.
Không commit/push/merge, không truy cập hoặc khởi động AWS, không đổi Game Engine,
frontend, authentication/RBAC. `.vscode/` có sẵn và được giữ nguyên.

## Hai phát hiện review

### QA bind all interfaces: lỗi đã xác nhận và sửa

DockerCheck trước đây đặt ARENA_BIND_IP=0.0.0.0 ngay cả khi không có --lan-ip.
Đã đổi sang 127.0.0.1 mặc định, ghi đè cả giá trị không an toàn kế thừa từ shell.
--lan-ip phải là địa chỉ IPv4 local/private cụ thể; không chấp nhận 0.0.0.0,
multicast hoặc địa chỉ Internet. Khi chọn LAN, bind đúng interface đó.
Inspect container xác nhận HostIp đúng interface, không chỉ kiểm tra biến env.

Builds dùng QA image tags riêng; không ghi đè neon-arena:4.0,
neon-arena-controller:4.0 hoặc neon-arena-bot:4.0. Checker tạo Compose override
tạm, project và namespace ngẫu nhiên, ports ephemeral. Chỉ cleanup volume đúng
project label và prefix đã tạo; không sử dụng down -v.

### Cached action sau close: giữ semantics idempotent, không sửa runtime logic

Kết quả đã hoàn tất là receipt bất biến cho đúng owner/lease + seq + payload hash.
Duplicate đúng các giá trị đó có thể nhận lại cached action sau close trong thời
gian giữ job; không ghi vào stdin, không tạo/mở lại container, không cập nhật game.
Đây không phải lệnh cho phép tiếp tục runtime.

Các điều kiện còn lại vẫn bắt buộc:

- Owner/lease phải hợp lệ, được kiểm tra trước khi đọc cache.
- Observation mới hoặc payload khác sau close bị từ chối.
- Action bị cancel trước khi hoàn tất không được cache.
- Lỗi hạ tầng không trả cache action trước đó; seq không được thực thi lại.
- Runtime đã compact không được tạo lại từ job ID cũ; stale owner/epoch bị fence.

Đã bổ sung regression tests và comment giải thích trong service.py; không đổi
thứ tự/cache logic. Kiểm chứng thêm bằng private HTTP với runtime container thật:
duplicate sau close trả đúng receipt, không còn container; lượt mới trả 503.

## Môi trường và lệnh thực tế

Docker Desktop: Engine 29.8.2, linux/amd64, context desktop-linux, Compose v5.6.0.
Engine có 20 CPU và khoảng 11.5 GiB RAM. Kiểm tra ban đầu trong tool sandbox bị
permission denied; kiểm tra lại được cấp quyền xác nhận Engine hoạt động. Không
đánh dấu BLOCKED dựa trên lỗi quyền của tool khi Engine thực tế đang hoạt động.

```powershell
.\.venv\Scripts\python.exe -m pytest tests controller_tests -ra --tb=short
docker build --target runtime -t neon-arena-qa-arena:local .
docker build --target tests -t neon-arena-qa-arena:tests .
docker build -f Dockerfile.controller --target runtime -t neon-arena-qa-controller:local .
docker build -f Dockerfile.controller --target tests -t neon-arena-qa-controller:tests .
docker build -f Dockerfile.sandbox -t neon-arena-qa-bot-image:local .
docker run --rm --network none --label io.neonarena.qa=foundation-tests neon-arena-qa-arena:tests
docker run --rm --network none --read-only --tmpfs /tmp:rw,nosuid,nodev,size=64m,uid=10001,gid=10001 --label io.neonarena.qa=foundation-tests neon-arena-qa-controller:tests
.\.venv\Scripts\python.exe scripts/check_docker.py
.\.venv\Scripts\python.exe scripts/check_sandbox_lifecycle.py
.\.venv\Scripts\python.exe -m pytest tests/test_docker_qa_config.py controller_tests -ra --tb=short
git diff --check
```

Probe bổ sung chạy với DockerCheck project mới, dừng arena rồi exec controller:
SANDBOX_TEST_ACK=1, python -B -c <nội dung scripts/probe_sandbox.py> languages.
Probe này hiện cũng được ghép vào cuối check_sandbox_lifecycle.py để chạy lại.
Trong lượt này, core lifecycle và probe mới chạy thành hai lượt QA riêng; không
gộp chúng thành tuyên bố đã chạy lại một invocation sau sửa cuối.

## Kết quả

| Nhóm | Kết quả thực tế |
|---|---|
| Windows pytest: backend + controller | 201 PASS, 1 warning, 65.50s |
| Backend tests trong Linux image | 180 PASS, 1 warning, 52.19s |
| Controller tests trong Linux image, không socket | 21 PASS, 1 warning, 0.48s |
| Regression review/config tập trung | 23 PASS, 1 warning |
| Build backend/controller/bot và hai test images | PASS |
| HTTP/static/sandbox health + bind loopback | PASS |
| Python/C++/Java trên Robot Battle và OTT v2 | PASS: sáu cặp, không bot fault |
| Ba WebSocket + replay cùng frames | PASS |
| Invitation Accept/Decline và persistence | PASS |
| Writer thứ hai trên shared Docker data volume | PASS: chặn trước Store/runner |
| Backend restart, Controller restart, down/up | PASS: sessions/rules/bots/history/replay/artifacts giữ nguyên |
| Cancel, Controller outage/restart, backend SIGKILL | PASS: không xử thắng/thua oan; giữ replay; không orphan |
| Live owner và stale lease qua private HTTP thật | PASS |
| Backup ba volumes + pinned image archive | PASS |
| Restore vào ba volumes mới và load exact images | PASS |
| Hash/size mọi file + UID 10001 sau restore | PASS |
| Trận mới dùng artifacts đã restore + ba WebSocket | PASS |
| Protocol/limits inspection/languages probe | 5 nhóm PASS, 0 jobs remaining |
| Diff whitespace | PASS |

Warning duy nhất là Starlette TestClient/httpx deprecation có sẵn. Không đổi
dependency để che warning. Không có test FAIL còn lại trong các lượt trên.

Sáu trận chính trên project neon-arena-qa-ef81860d9f:

| Game | Cặp | Match ID | Frames |
|---|---|---|---|
| Robot Battle | Python/C++ | 3787076944c64195 | 10 |
| Robot Battle | C++/Java | 06c27d7d8a83426d | 11 |
| Robot Battle | Python/Java | 8c9d0c0d76aa4659 | 10 |
| OTT v2 | Python/C++ | 1e7601a0f36d448a | 28 |
| OTT v2 | C++/Java | cc9181e389ba4bb1 | 28 |
| OTT v2 | Python/Java | 004519dd75fd4f3e | 28 |

Có thêm các trận reuse sau restart và sau restore. Không suy diễn sáu cặp này
thành kiểm thử mọi thứ tự A/B hoặc mọi input bot có thể có.

## Backup/restore thật

Snapshot nén 251.045 bytes, kèm image archive và receipt SHA-256. Không có .env;
không serialize Config.Env. Trước snapshot dừng cả arena/controller.
Restore project: neon-arena-restore-qa-2b83e5f456, namespace độc lập.

- Import image archive, xác minh exact image IDs và architecture.
- Restore vào volume chưa tồn tại; không ghi đè nguồn.
- Trước khi start backend, so hash/size toàn bộ data/uploads/artifacts với manifest.
- Đọc dữ liệu bằng uid/gid 10001 trong container read-only.
- Start bằng pinned images, kiểm tra lại writer lock, session identities, Active
  Bot, rules snapshot, invitation/history và replay cũ.
- Chạy trận mới bằng compiled artifacts đã restore; ba client nhận cùng frames.
- Dọn riêng volumes/containers QA sau kiểm tra. Không prune images.

QA image IDs:

```text
arena:      sha256:f24a14718c6f631a8ff82a57b076ba798f8824da15dcd238e955bc0aa8cfa0db
controller: sha256:d5f32b059f8023e1c4516f09e5bc7e9720ec5078ce0393a3a90f7838dbbbb01d
bot-image:  sha256:6ad3b466547a65307a9c8c620c64d7276ea5abefc4b6fb0328e3faa4a43fce2d
```

Probe protocol bổ sung dùng project neon-arena-qa-883f0e1e52. Project lifecycle
cũng được tạo ngẫu nhiên và cleanup theo label. Sau QA không còn container nào;
danh sách volumes trở về đúng sáu volumes sẵn có trước lượt. Không mount/đọc nội
dung sáu volumes đó. Các image tags thật được kiểm tra giữ nguyên.

## Giới hạn và kết luận

**Security Foundation: PASS trong môi trường local Docker QA.** Chờ chủ dự án và
ChatGPT review trước Phase 4.2. Không coi kết quả là duyệt mở Internet.

Chưa kiểm thử trên EC2, qua hai laptop vật lý/LAN, HTTPS/WSS hoặc public gateway;
không triển khai Authentication/RBAC. Chưa chạy full adversarial probe stage all
trong lượt này; stage languages kiểm tra policy Docker thực tế và giao thức.
Images có dependency ranges, nên các lần rebuild tương lai có thể đổi phiên bản;
giữ exact image IDs cho backup/rollback. Docker Sandbox vẫn dùng chung kernel và
Controller có Docker Engine access. Các giới hạn single-writer/lease/ledger trong
SECURITY_FOUNDATION.md vẫn áp dụng. QA images/build cache được giữ để review;
không tự xóa cache hoặc images khác.
