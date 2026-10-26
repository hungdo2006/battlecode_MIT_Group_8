# NEON ARENA — vận hành Arena Server và chuyển Local ↔ Remote Worker

Đây là hướng dẫn vận hành **Arena Server** (AWS EC2) và **Arena Worker** (PC chạy bot). `scripts.arena_operator` là lệnh ổn định, dùng lại đúng cơ chế chuyển Runner đã nghiệm thu; các định danh Docker và thư mục cũ được giữ nguyên để bảo vệ dữ liệu.

Phạm vi: website hiện đang chạy trên EC2 qua
`https://traitimcodon.duckdns.org`, Docker project `neon-b1-ec2-pilot`.

**Đây là chuyển nơi chạy bot, không phải chuyển website hoặc merge database.**
Giữ nguyên các volume `pilot_data`, `pilot_uploads`, `pilot_caddy_data` và
`pilot_caddy_config`, cùng domain/certificate Caddy, tài khoản và replay.
Thêm `local_artifacts` chỉ để chạy bot trong Docker trên EC2; artifact của PC
vẫn nằm tại Worker Windows và có thể cần nộp/biên dịch lại khi đổi Runner.
Không tăng giới hạn hai trận, không thay cơ chế username/password đã thống nhất.

B1.4 tách biệt hoàn toàn với website `neon-arena` cũ. Không dùng
`compose.ec2-pilot.yaml` như overlay cho `compose.yaml`, không dùng rollback
B1.4 để đổi runner: đó là đổi sang **database khác**.

## 1. Chuẩn bị (một lần, EC2)

Trong checkout `~/neon-arena-b1-pilot` đã cập nhật mã mới (bao gồm `scripts.arena_operator`),
và website B1.4 hiện vẫn chạy:

```bash
cd ~/neon-arena-b1-pilot
sudo python3 -m scripts.arena_operator prepare
sudo python3 -m scripts.arena_operator status
```

`prepare` dùng private `.b1-pilot/cloud.env` của pilot hiện tại, tự tạo
EC2-only Controller token và lưu trong thư mục `.runner-switch/b15-pilot/`
(gitignored), **không in secret**; build image tên riêng cho Controller/bot
trên EC2 và chỉ **create** Controller ở trạng thái stopped. Nó không khởi động
hoặc restart Arena/Gateway, không tạo database mới, không dừng Worker PC.
Model local/remote đều pinned tới cùng image Arena pilot hiện chạy; từ chối
nếu project, volume, secret, config, running image khác dự kiến.

Không tự sửa các file JSON/env đã generated; thay code/image/config cần bộ
prepare và backup mới trong cửa sổ nâng cấp riêng.

## 2. Sao lưu lạnh + thử phục hồi (một lần, EC2)

Chờ hết các trận/compile/upload đang chạy và bảo đảm Worker có thể kết nối lại.
Cần chấp nhận thời gian website gián đoạn. Chọn đường dẫn backup **chưa tồn tại**, bảo vệ ACL; ví dụ dưới đây đặt trong
`.runner-switch/` vốn được tạo khi prepare (sao chép backup ra nơi an toàn
ngoài EC2 ngay sau đó):

```bash
sudo python3 -m scripts.arena_operator backup \
  --backup-directory .runner-switch/b15-backup-001 --approve-downtime
```

Lệnh drain, stop đúng các service, backup **5 volume** và image/config,
phục hồi thử vào **5 volume mới** để kiểm tra SQLite/schema và toàn vẹn,
sau đó khởi động lại chính mode ban đầu. Nếu đang bận, từ chối trước khi stop.
Nếu readiness/restart bị lỗi, admission tiếp tục closed cho operator xử lý.
Bản backup chứa mật khẩu/secret, không commit/chia sẻ; giữ thêm bản sao an toàn
ngoài EC2. Bản này không chứa compiled artifact đang nằm ở máy Windows.

## 3. Chuyển bot sang chạy ngay trên EC2

```bash
sudo python3 -m scripts.arena_operator switch \
  --target local --backup-directory .runner-switch/b15-backup-001
sudo python3 -m scripts.arena_operator status
```

Website/tài khoản/bảng điểm/replay AWS không đổi. EC2 bật private Docker
Controller, không public port 9000. Sau khi thành công, có thể dừng riêng
agent PC (giữ volume/artifacts) trong checkout Worker Windows:

```powershell
python scripts/arena_worker.py stop-agent
```

## 4. Chuyển bot về Windows Worker

Bật lại agent trên Windows trước khi chạy switch; nó sẽ thử kết nối trong
lúc Cloud đang ở local và tự đăng ký sau khi mode remote khởi động:

```powershell
python scripts/arena_worker.py start-agent
```

Trên EC2:

```bash
sudo python3 -m scripts.arena_operator switch \
  --target remote --backup-directory .runner-switch/b15-backup-001
sudo python3 -m scripts.arena_operator status
```

Phải kiểm tra hostname/TLS chuẩn, drain công việc, bảo toàn pinned models,
chờ PC lease & readiness, rồi mới resume. Remote ngắt kết nối thì fail closed;
không có tự fallback chạy bot trên EC2. Nếu chuyển thất bại trước khi resume,
B1.3 thử rollback về mode gốc; nếu không chắc admission đã mở, tuyệt đối không
tự rollback trùng công việc.

## Nghiệm thu thực tế

CI kiểm tra full Python tests và hai cấu hình Compose với secret giả; **không**
khẳng định đã SSH AWS hay chạy test WAN trên hai máy. Khi thao tác trên EC2,
kiểm tra đăng nhập trước/sau, kết quả và replay cũ, nộp Python/C++/Java,
Official, hai trận đồng thời, ngắt/nối Worker giữa trận, chặn switch khi bận,
sau đó lại đăng nhập và xem replay. Không dùng `docker compose down -v`,
`docker system prune` hay copy database qua máy PC.

Cơ chế này chỉ áp dụng cho **pilot B1.4 hiện còn hoạt động**. Nếu đã rollback
pilot, chạy schema migration hoặc đổi image, phải kiểm tra lại hiện trạng
trước khi dùng, không chạy các lệnh trên một project khác.

## Sửa quyền Docker socket của EC2 sau lần chuyển thử bị rollback

Nếu log Controller có `PermissionError(13, 'Permission denied')` tại
`/var/run/docker.sock` và B1.5 đã chuẩn bị/pinned model với GID 0,
**không** chmod 666 socket, không sửa thủ công JSON và không xóa volume.
Sau khi xác nhận trạng thái đang Remote, chạy:

```bash
sudo python3 -m scripts.arena_operator repair-socket-gid
sudo python3 -m scripts.arena_operator status
```

Lệnh chỉ sửa `group_add` của Controller ngừng chạy để trùng GID thật
của socket, lưu bản `.pre-gid` riêng tư và tính lại mã kiểm tra model.
**Backup B1.5 cũ không còn phù hợp với plan đã sửa**. Tạo backup lạnh
mới ở một thư mục chưa tồn tại rồi mới chuyển, ví dụ:

```bash
sudo python3 -m scripts.arena_operator backup --backup-directory .runner-switch/b15-backup-002 --approve-downtime
sudo python3 -m scripts.arena_operator switch --target local --backup-directory .runner-switch/b15-backup-002
```

GID có thể đổi khi Docker/socket khởi tạo lại; nếu có, cần điều tra
chứ không bỏ qua bước kiểm tra pinned model.
