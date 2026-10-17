# Security Foundation — kết quả kiểm thử local

Ngày: 2026-10-17. Branch `feature/player-admin-access`, baseline `4614e32`.
Chưa commit/push/merge; chưa truy cập, khởi động hoặc thay đổi AWS. Không chạy app
với dữ liệu mặc định của repository. Tests dùng tmp_path/TemporaryDirectory.
Thư mục `.vscode/` chưa theo dõi đã có từ đầu và được giữ nguyên.

## Kết quả thực tế

| Lệnh/nhóm | Kết quả |
|---|---|
| `.\.venv\Scripts\python.exe -m pytest -ra --tb=short` trước sửa | 159 PASS, 1 warning |
| `.\.venv\Scripts\python.exe -m pytest tests controller_tests -ra --tb=short` sau sửa restart tests | 195 PASS, 1 warning; 64,05 giây |
| `.\.venv\Scripts\python.exe -B -m unittest discover -s tests -p test_writer_lock_os.py -v` | 2 PASS trên Windows/Python 3.13.12 |
| `wsl -d Ubuntu-24.04 --cd /mnt/d/LTM -- python3 -B -m unittest discover -s tests -p test_writer_lock_os.py -v` | 2 PASS trên Ubuntu 24.04/Python 3.12.3; lock files trong Linux /tmp |
| CLI backup/restore `--help` | PASS |
| `.\.venv\Scripts\python.exe -m pytest tests/test_backup_restore.py tests/test_writer_lock_os.py -ra --tb=short` sau bổ sung fsync/log-driver | 13 PASS, 1 warning |
| `git diff --check` | PASS; chỉ có thông báo Git về LF/CRLF |
| Docker build, real Engine, named-volume restore, cgroup/security probes | Chưa chạy: local Docker Desktop Linux Engine không kết nối được |

Hai unittest OS được thêm sau lượt full suite 195 và chạy riêng trên cả hai OS.
Không cộng lượt test chạy lặp vào số test của full suite. Cảnh báo có sẵn:
Starlette TestClient khuyến cáo chuyển từ httpx sang httpx2; chưa đổi dependency
ngoài phạm vi. Docker SDK 7.1.0 được cài trong .venv và requirements-dev để chạy
Controller policy tests; không thêm Docker SDK vào backend runtime dependencies.

## Những điều đã chứng minh

- Process thứ hai bị chặn trước Store và configured_runner; sentinel JSON/replay
  không đổi. Exception startup và crash đều nhả OS lock; inode không bị xóa.
- Live lease không bị owner khác chiếm; stale owner/lease/epoch bị từ chối. Claim
  trùng idempotent, hai claim song song chỉ có một winner.
- Duplicate compile/open/observation không chạy lại bằng fake Engine/Pipe. Runtime
  cancel trong lúc create được thu hồi; lease/cancel không bị quy thành bot fault.
- Closed retention tính từ closed_at; cleanup retry không kéo dài mốc. Sau compact,
  used-ID ledger vẫn từ chối open; ledger đầy trả lỗi, không tự xóa ID để tái dùng.
- Action lỗi hạ tầng không trả nhầm response của observation trước.
- SandboxRunner serialization qua ASGI Controller thật, cùng artifact IO thật,
  chạy được prepare/open/request/close/release. Fake Engine không kiểm chứng Docker.
- Controller restart đổi epoch: client lấy lease mới cho job mới, runtime cũ không
  tiếp tục; artifact trên thư mục tạm vẫn dùng lại được.
- Backup/restore ba thư mục local khớp byte/checksum; CLI được kiểm tra bằng Docker
  double, có inventory cả image cũ trong artifacts, không xuất Config.Env. Không
  overwrite output/volume, không restore vào project production, chặn traversal/link.
- Replay JSON cũ và JSONL phục hồi đọc được qua API sau backend restart.
- Suite regression chạy compiler/runtime Python/C++/Java native thật, hai game,
  invitation/Accept/Decline, lobby, live WebSocket và replay. Toolchains local:
  Python .venv, MinGW g++, JDK trong IntelliJ JBR; không yêu cầu chúng có trên Player.

## Failures đã xử lý

Lượt full regression đầu sau lock: 5 FAIL, 190 PASS. Năm test restart cũ mở hai
backend cùng data_dir khi backend đầu còn sống; lock từ chối đúng. Tests đã sửa
để đóng WebSocket/lifespan đầu trước khi restart, không tắt/bypass lock. Năm test
đó chạy lại 5 PASS, rồi toàn suite 195 PASS.

Trong quá trình viết test backup, assertion của Docker double nhầm metadata JSON
với mount options: 2 FAIL; đã sửa assertion kiểm tra các đối số --mount thực tế.
Nhóm tập trung sau đó 40 PASS (trước khi thêm 2 OS unittest).

## Chưa được kiểm chứng và điều kiện trước Phase 4.2

Docker daemon local trả lỗi thiếu pipe dockerDesktopLinuxEngine; không khởi động
Docker Desktop/AWS để tự biến một kiểm tra thành PASS. Chưa build hai test images,
chưa kiểm tra ownership của restored volumes bằng container, SIGKILL/orphan cleanup,
network/cgroup thật hoặc load test. Không tuyên bố ứng dụng đã sẵn sàng public.

Trước triển khai cần: review thay đổi; chạy Linux Docker QA trên volumes riêng;
diễn tập full image+volume backup/restore, kiểm tra source/replay checksum; chạy
check_docker và check_sandbox_lifecycle; triển khai backend/controller cùng phiên
bản. Sau khi chủ dự án duyệt mới bắt đầu Authentication/RBAC Phase 4.2.

Giới hạn còn lại: một writer/host, một Controller/namespace; filesystem hỗ trợ
OS advisory locks. Ledger có giới hạn và mất sau restart nhưng epoch mới fence
request cũ. Lease hết hạn cùng epoch yêu cầu restart backend; không force takeover.
Checksum phát hiện hỏng dữ liệu, không thay thế chữ ký/chống sửa có chủ đích hay
mã hóa backup. Controller vẫn có quyền Docker Engine rất mạnh, shared-kernel
sandbox không bảo đảm an toàn tuyệt đối.
