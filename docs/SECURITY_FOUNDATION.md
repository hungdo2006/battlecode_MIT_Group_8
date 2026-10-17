# Security Foundation — trước Phase 4.2

Phạm vi: single-writer, controller lease/job lifecycle và cold backup/restore.
Không bổ sung tài khoản, RBAC, gateway, public access hoặc thay luật/game/UI.
Không chạy lệnh nào dưới đây trên AWS trong lượt triển khai local này.

## Một writer trên mỗi data volume

Backend lấy OS lock `data/.writer.lock` trước khi khởi tạo Store, Sessions hoặc
runner. Compose sandbox và legacy cùng mount `/app/data`, nên dù khác process,
container hoặc đường dẫn project, các backend chia sẻ volume đều tranh cùng inode.
Windows dùng `msvcrt.locking`; Linux dùng `fcntl.flock`. Không có dependency mới
trong backend runtime. Process thứ hai fail ngay, không chạy startup recovery JSON
và không gọi Controller. Lock giữ đến khi lobby, matches và runner shutdown xong;
OS nhả lock khi process crash. Không xóa `.writer.lock`, kể cả lúc nó đang tồn tại
nhưng server đã dừng. File tồn tại không có nghĩa là lock còn được giữ.

Chỉ hỗ trợ một backend worker/replica và một Controller trên một namespace. Các
script sửa dữ liệu bên ngoài phải dừng writer hoặc tuân thủ cùng lock. Không dùng
NFS/SMB để chia data giữa nhiều host: đồ án chỉ hỗ trợ local filesystem/Docker
named volumes. Không dùng `--reload`, rolling replicas hoặc hai controller cùng
namespace để thay thế cơ chế này.

## Lease fencing và idempotency

- Controller sinh `epoch` ngẫu nhiên sau mỗi restart và sweep namespace như trước.
- Backend đọc epoch từ health, claim bằng owner ngẫu nhiên. Claim trùng owner còn
  sống trả cùng lease; owner khác nhận 409, không đóng job đang chạy.
- Mọi compile/open/request/close/heartbeat/release bắt buộc mang lease token.
  Request cũ bị chặn dù có runner token đúng. Không ghi lease vào submission/replay.
- Heartbeat 5 giây; lease hết hạn sau 20 giây. Kiểm tra hết hạn ngay khi có request,
  không cần đợi reaper. Owner đã nghỉ/hết hạn không thể tự claim lại trong epoch đó.
- Shutdown bình thường release sau khi dọn trận. Sau SIGKILL, backend thay thế có
  thể phải đợi tối đa khoảng 20 giây; restart policy có thể thử startup lại. Không
  cho phép force-takeover từ backend mới khi lease cũ còn sống.
- Khi Controller restart, backend chỉ tự claim lại nếu epoch đã đổi. Runtime cũ
  giữ lease ban đầu, bị từ chối thay vì tiếp tục trận hay gửi observation lần nữa.
  Nếu chỉ mất heartbeat quá 20 giây trong cùng epoch, cần restart backend sau khi
  kiểm tra sự cố; không tự chiếm lại lease.
- `closed_at` chỉ đặt một lần khi đóng, không đổi khi cleanup retry. Job/result
  được giữ ít nhất 120 giây sau đóng; container chưa dọn xong vẫn giữ handle/capacity.
- Ledger compact giữ mọi job ID đã dùng suốt epoch: xóa bản ghi lớn không cho phép
  mở lại ID đó. Close không có open trước cũng ghi nhận ID để chặn startup đến muộn.
- Ledger tối đa 65.536 ID/epoch và 4.096 retired owners; đầy thì fail closed, cần
  drain rồi restart Controller có kiểm soát. Không tự xóa dữ liệu artifacts/replay.
- Duplicate compile/open/action không chạy lần hai. Observation lỗi hạ tầng không
  được trả nhầm cache action trước. Cancel/lease failure không thành bot fault.

Private Controller protocol đã đổi; phải triển khai backend và Controller cùng
phiên bản. Không thay bot stdin/stdout JSON Lines hoặc WebSocket protocol.

## Cold backup ba volumes

Thực hiện trên máy local/bản sao trước. Kiểm tra Docker context trỏ đúng Engine;
đảm bảo còn dung lượng cho dữ liệu nén **và toàn bộ image archive**. Đóng cuộc thi,
đợi/cancel trận hợp lệ, đợi upload/compile hoàn tất, không deploy/restart song song.

PowerShell, tại repository; Linux thay `py -3` bằng `python3`:

```powershell
docker compose stop arena
docker compose stop controller
py -3 scripts/backup_docker.py --output backups/foundation-local.tar.gz
docker compose up -d --no-build --wait
```

Nếu dùng `-p`, thêm cùng project vào các lệnh Compose và `--project <name>` cho
script. Không dùng `down` trước khi backup vì script cần inspect stopped containers.
Không dùng `down -v`. Script không tự stop/start dịch vụ hoặc xóa volumes.

Ba file tạo mới (không ghi đè file sẵn có):

1. `foundation-local.tar.gz`: data/, uploads/, artifacts/, manifest.json; hash từng
   file. `.writer.lock` được bỏ qua vì là coordination inode, không phải dữ liệu.
2. `foundation-local.tar.gz.images.tar`: arena/controller, sandbox image hiện tại
   và mọi image ID được artifacts tham chiếu, kể cả image cũ khác tag hiện tại.
3. `foundation-local.tar.gz.receipt.json`: checksum archive/images, image ID,
   RepoDigests nếu có, OS/architecture và manifest. Không lưu container Config.Env.

Chỉ coi backup hoàn tất khi có receipt hợp lệ. Lỗi để lại file chưa hoàn tất cho
operator kiểm tra; chạy lại bằng tên mới. `--metadata-only` vẫn backup ba volumes
nhưng không export image: không đủ để khôi phục độc lập nếu mất exact images.
Nếu image cũ đã bị prune khỏi Engine, full backup thất bại rõ ràng; không âm thầm
bỏ qua artifacts đó hoặc tuyên bố chúng vẫn chạy được.

Helper không có network/socket/host mounts, dùng image ID cố định với `--pull never`.
Nó giữ Linux flock xuyên suốt snapshot; data mount RW chỉ để tạo/mở lock file,
không sửa JSON/source/replay. uploads/artifacts read-only. Script từ chối nếu một
container khác còn chạy và mount volume RW; kiểm tra lại sau snapshot. Operator
vẫn phải giữ cửa sổ bảo trì, không khởi động Controller/writer mới giữa backup.

Backups có source, session hashes và metadata người chơi: lưu ngoài repository,
mã hóa/phân quyền phù hợp, sao chép ra nơi khác. `.env`, runner token và mã Admin
quản lý riêng; không đưa lên Git hoặc vào receipt. Giữ cả ba file cùng nhau.

## Restore chỉ vào bộ volume mới

```powershell
py -3 scripts/restore_docker.py --backup backups/foundation-local.tar.gz --project neon-arena-restore-local01 --load-images
```

Script kiểm tra checksum/manifest trước khi gọi Docker; project phải bắt đầu bằng
`neon-arena-restore-`. Ba volume đích phải chưa tồn tại. Script không ghi vào volume
gốc, không tự start app và không tự xóa volume khi lỗi. Restore lỗi để lại volume
mới, có thể chưa đủ dữ liệu; chọn project mới khi thử lại. Không dùng chúng để chạy
ứng dụng trước khi restore thành công. Không chạy đồng thời hai restore cùng tên.

Helper restore chỉ mount ba volume mới, network none, root filesystem read-only,
drop toàn bộ capabilities rồi chỉ thêm CHOWN để đặt UID/GID 10001. Đây là helper
operator ngắn hạn, không phải bot container. Không extractall; từ chối traversal,
symlink, hardlink, device và file trùng. File được tạo exclusive, kiểm tra hash.
Quyền executable artifact được giữ, setuid/setgid bị loại bỏ.

`--load-images` import image archive vào **Engine local được chọn**. Không có cờ
này thì exact image IDs phải tồn tại sẵn. Script kiểm tra Linux/architecture;
không thể chuyển artifact C++ từ amd64 sang arm64 chỉ bằng restore.

Để chạy thử bản phục hồi, xem receipt rồi tạo Compose override ở ngoài Git:

```yaml
services:
  arena:
    image: "sha256:<service_images.arena trong manifest>"
  controller:
    image: "sha256:<service_images.controller trong manifest>"
    environment:
      SANDBOX_IMAGE: "sha256:<sandbox_image_id trong manifest>"
  bot-image:
    image: "sha256:<sandbox_image_id trong manifest>"
```

Dùng đúng `-p neon-arena-restore-local01`, `--no-build`, `ARENA_BIND_IP=127.0.0.1`
và cổng local còn trống; cấu hình secrets riêng cho bản thử nghiệm. Compose sẽ dùng
ba volume đã tạo có cùng tên project. Không dùng build làm tag trỏ sang toolchain
mới trước khi kiểm tra artifact compatibility. Nếu artifacts chứa nhiều image ID
qua nhiều đời toolchain, inventory giữ đủ image nhưng Controller vẫn chỉ chạy một
image: chọn image phù hợp hoặc nộp/compile lại những source không tương thích.

Kiểm tra danh sách bot, game/rules snapshot, invitation metadata, replay JSON và
JSONL; so checksum source/replay với manifest. Trận đang chạy khi bị dừng đột ngột
được startup recovery đánh dấu interrupted như trước. Backup chuẩn nên drain trước.

Rollback: đóng admission, drain và dừng writers; phục hồi snapshot/image đồng bộ
vào volume mới rồi kiểm tra trước khi đổi cấu hình. Giữ volume cũ nguyên vẹn.
Phiên bản cũ chưa có Authentication chỉ chạy LAN hoặc public read-only.

## Kiểm thử local và trước Phase 4.2

```powershell
py -3 -m pip install -r requirements-dev.txt
py -3 -m pytest tests controller_tests -ra --tb=short
py -3 -B -m unittest discover -s tests -p test_writer_lock_os.py -v
# Ubuntu WSL local, không cần FastAPI/pytest:
wsl -d Ubuntu-24.04 --cd /mnt/d/LTM -- python3 -B -m unittest discover -s tests -p test_writer_lock_os.py -v
```

Các tests tự tạo thư mục tạm: subprocess writer collision/crash, lease/epoch,
duplicate/cancel, client→ASGI Controller, archive/restore ba thư mục, checksum,
legacy replay API và chống overwrite/path escape. Controller tests dùng fake
Engine; không chứng minh được cgroup/network isolation hay Docker volume ownership.

Khi Docker Engine local sẵn sàng, build và chạy các kiểm thử trên project QA riêng:

```powershell
docker compose build
docker build --target tests -t neon-arena:foundation-tests .
docker run --rm --network none neon-arena:foundation-tests
docker build -f Dockerfile.controller --target tests -t neon-arena-controller:foundation-tests .
docker run --rm --network none neon-arena-controller:foundation-tests
py -3 scripts/check_docker.py
py -3 scripts/check_sandbox_lifecycle.py
```

Acceptance checker dùng project/volumes ngẫu nhiên; không chạy trên project thật.
Cần diễn tập thêm backup/restore CLI với ba volumes QA, kiểm tra checksum/images,
writer lock qua Docker shared volume, cancel/restart và ba WebSocket trên sandbox
thật trước triển khai. Kết quả local hiện tại ở
[SECURITY_FOUNDATION_VERIFICATION.md](SECURITY_FOUNDATION_VERIFICATION.md).
AWS vẫn dừng đến khi chủ dự án duyệt. Docker Sandbox không bảo đảm an toàn tuyệt đối;
chưa triển khai Authentication/RBAC hay public gateway trong bước nền tảng này.
