# Phase 2 — Kết quả kiểm chứng thực tế

Kiểm chứng ngày 15/10/2026 trên Windows + Docker Desktop, Linux/amd64,
Engine29.8.2, cgroupsv2, seccomp builtin. Nhánh `feature/docker-bot-sandbox`.
Không commit/push/merge; không dùng volume dữ liệu thực của ứng dụng để chạy QA.

## File đã tạo/sửa

- Runner: thêm `backend/execution.py`, `backend/sandbox_client.py`; sửa
  `backend/main.py`, `backend/matches.py`, `backend/runner.py`.
- Controller: thêm `sandbox_controller/{__init__,service,engine,artifacts,transfer}.py`.
- Docker: thêm `Dockerfile.controller`, `Dockerfile.sandbox`, `compose.legacy.yaml`;
  sửa `Dockerfile`, `compose.yaml`, `.env.example`, `.gitignore`.
- Vận hành/QA: thêm `scripts/configure_sandbox.py`, `scripts/probe_sandbox.py`,
  `scripts/check_sandbox_lifecycle.py`; sửa `scripts/check_docker.py`,
  `scripts/backup_docker.py`.
- Tests: thêm `tests/test_execution.py`, `tests/test_sandbox_client.py`,
  `tests/test_match_runner_failures.py`, `controller_tests/test_controller.py`;
  sửa `tests/conftest.py` để regression suite luôn chọn legacy có chủ đích.
- Tài liệu: cập nhật `README.md`, `docs/DOCKER.md`; thêm `docs/SANDBOX.md`,
  `docs/SANDBOX_VERIFICATION.md`.

Game Adapters, frontend và các file dữ liệu hiện có không bị chỉnh sửa.

## Kết quả cuối

| Kiểm tra đã chạy | Kết quả |
|---|---|
| Build backend, controller, bot image | PASS |
| Compose sandbox up/health | PASS, `runner.mode=sandbox`, `ready=true` |
| Regression Windows native | **159 passed**, không skip |
| Regression trong Linux test container | **159 passed**, không skip |
| Controller unit tests, không socket/network | **5 passed** |
| JavaScript OTT rules tham chiếu | **8 passed** |
| Private sandbox probes | **16 nhóm kiểm tra pass**, 0 job còn lại |
| Sáu cặp ngôn ngữ trên hai game | PASS |
| Ba WebSocket spectator so với replay | PASS, frames và sequence khớp |
| Ba phiên Chrome độc lập | PASS, 0 JavaScript errors |
| Pause riêng từng client, viewport390px | PASS |
| Invitation/Accept/Decline, Organizer/Player | PASS |
| Restart backend/controller và artifact reuse | PASS |
| Down/up, metadata/source/replay/artifact volume | PASS |
| Backup binary-safe gồm data/uploads/artifacts | PASS |
| Hủy trận, mất controller, kill/restart đột ngột | PASS |
| Backend ngừng hoạt động: lease tự thu hồi bot | PASS |
| Controller không publish cổng, chỉ internal network | PASS, Docker inspect |
| Kết nối tới controller từ external bridge của stack | Bị chặn |

Python suites có một Starlette/httpx deprecation warning hiện có. Node18 có
ExperimentalWarning về JSON modules; không có test thất bại.

## Trận thực tế của lượt acceptance cuối

Project QA `neon-arena-qa-ae20110141`, token/volume/namespace riêng:

| Game | Bot A / B | Match ID | Frames | Kết quả |
|---|---|---|---:|---|
| Robot | Python / C++ | afd52d2e364b48d5 | 10 | A, knockout |
| Robot | C++ / Java | 3faa122d6dc34e93 | 11 | B, knockout |
| Robot | Python / Java | c20b6b0e733b406d | 10 | A, knockout |
| OTT | Python / C++ | 69228b38f4ca45d4 | 28 | A, series_complete |
| OTT | C++ / Java | 806939ad789a4666 | 28 | A, series_complete |
| OTT | Python / Java | 5f245cbc9c804718 | 28 | A, series_complete |

Các trận đều completed, không bot fault. OTT chạy2 ván, process bot tồn tại qua
các ván. Ba client nhận cùng frames như replay API. Artifact được chạy lại sau
restart backend và controller; sau down/up kiểm tra source hash, metadata, replay
và archive backup chứa artifact. QA project/volumes đã được dọn sau khi xác minh label.

Chrome tiếp tục tạo trận Robot `f3c73c1dba9d4835` và OTT `061750366a2848a8`,
cùng hoàn thành trên ba phiên độc lập. Không chỉnh sửa frontend hoặc game adapters.

## Nội dung16 probe sandbox

1. Python compile/runtime; giữ PID và file qua lượt; duplicate observation không
   làm counter tăng; inspect giới hạn Docker thực tế.
2. Close trước startup tạo tombstone, không thể khởi động lại job đã đóng.
3. C++17 compile/runtime giữ process qua lượt.
4. Java17 compile/runtime trong256MiB/64PID, giữ process qua lượt.
5. Syntax lỗi cả ba ngôn ngữ trả compile error; retry không compile lại; cleanup.
6. JSON lỗi.
7. Vòng lặp vô hạn bị timeout.
8. Bot crash.
9. Stdout vượt mức.
10. Stderr vượt mức.
11. Cấp phát400MiB trong container256MiB bị bot fault và cleanup.
12. Bot không kết nối được controller đang lắng nghe thật; không thấy socket,
    backend metadata, artifacts hoặc secrets; rootfs read-only; UID10001,
    Seccomp2 và NoNewPrivs1 trong `/proc/self/status`.
13. Tạo process con chạm PID cap, sau cleanup không còn container/process con.
14. Ghi nhiều file chạm tmpfs/file cap.
15. Hai runtime bot hoạt động đồng thời, trạng thái riêng.
16. Thiếu bearer token bị401; tham số Docker tùy ý bị422.

Toàn bộ fixture mới đi qua API controller, compile container và runtime container
giới hạn. Không chạy fixture gây quá tải trực tiếp bằng Python trên host/controller.

Controller unit tests bổ sung cancellation race khi Docker đang create, capacity
vẫn được giữ nếu cleanup chưa thành công, sequence/idempotency, token/body limit,
strict request schema và tombstone. Tests backend phân biệt BotError với lỗi
hạ tầng ở cả startup/request; lỗi hạ tầng không trở thành chiến thắng của đối thủ.

## Lỗi phát hiện và đã xử lý trong quá trình triển khai

- Runner cũ chạy chung filesystem/quyền với backend, cleanup chỉ kill process trực
  tiếp: sandbox chuyển cả compile/runtime sang container riêng, force remove toàn
  container, heartbeat/reaper và orphan sweep.
- C++ không chạy được trên tmpfs noexec: chỉ `/work` cần thực thi được bật exec.
- Docker archive API trên Engine kiểm thử không truy cập được thư mục con tmpfs:
  chuyển sang helper cố định qua exec pipes, không bỏ read-only và không thêm host bind.
- Controller restart mất lease: heartbeat chỉ nối lại owner khi controller vừa
  khởi động, không cho backend cũ ghi đè lease của backend mới.
- Close gặp lỗi transport có thể để lại job: backend giữ danh sách retry;
  controller giữ container handle và capacity đến khi remove thành công.
- Lỗi runner bất ngờ trước đây có thể bị quy thành bot fault: chỉ BotError được
  xử theo luật thua do bot; lỗi hạ tầng dẫn đến interrupted, winner null.
- `.env.example` chứa mã Organizer cố định: để trống, thêm script sinh cấu hình riêng.

## Phạm vi chưa kiểm chứng

- Chưa thử hai laptop vật lý; ba phiên browser và các WebSocket client chạy trên
  cùng host. Không coi đây là bằng chứng kiểm thử Wi-Fi/firewall trên máy thứ hai.
- Chưa triển khai trên Linux host độc lập, rootless/remote Engine, VPS hoặc Internet.
  Đã chạy image và bộ test Linux trong Docker Desktop.
- Chưa restart toàn bộ Docker daemon/Desktop giữa trận. Đã kiểm tra controller
  outage, controller/backend SIGKILL, lease expiry và down/up của stack.
- Không phải penetration test đầy đủ, không chứng minh chống kernel/container
  escape. Controller có Docker socket vẫn là thành phần đặc quyền cao.
- Metadata/replay và source cũ vẫn cần theo dõi dung lượng ổ đĩa; quota mới áp dụng
  cho workspace bot và artifact store, không tự xóa dữ liệu lịch sử.

Xem [SANDBOX.md](SANDBOX.md) để chạy lại, kiểm tra isolation và rollback.
