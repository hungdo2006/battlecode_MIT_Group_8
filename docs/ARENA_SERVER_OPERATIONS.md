# NEON ARENA — vận hành Arena Server và chuyển Local ↔ Remote Worker

Đây là hướng dẫn vận hành **Arena Server** (AWS EC2) và **Arena Worker** (PC chạy bot). `scripts.arena_operator` là lệnh ổn định, dùng lại đúng cơ chế chuyển Runner đã nghiệm thu; các định danh Docker và thư mục cũ được giữ nguyên để bảo vệ dữ liệu.

Phạm vi: website hiện đang chạy trên EC2 qua
`https://traitimcodon.duckdns.org`, Docker project `neon-b1-ec2-pilot`.

**Trạng thái đã xác minh (26/10/2026):** Giao diện Retro Pixel (Git merge `81d91ee`, image tag `neon-arena-ui:retro-pixel-81d91ee`) đã phát hành bằng `scripts.arena_ui_release`. Backup tương thích với image hiện tại là `.runner-switch/arena-backup-retro-81d91ee-20261026`, đã trả về `verified_cold_restore_drill`, `original_mode_restored: true` và `PASS: verify`. Sau sao lưu, Runner ở `local`, `ready: true`, `admission_closed: false`, `active_matches: 0`. Các trạng thái có thể thay đổi; luôn kiểm tra lại trước khi thao tác.

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
  --backup-directory .runner-switch/arena-backup-initial --approve-downtime
```

Lệnh drain, stop đúng các service, backup **5 volume** và image/config,
phục hồi thử vào **5 volume mới** để kiểm tra SQLite/schema và toàn vẹn,
sau đó khởi động lại chính mode ban đầu. Nếu đang bận, từ chối trước khi stop.
Nếu readiness/restart bị lỗi, admission tiếp tục closed cho operator xử lý.
Bản backup chứa mật khẩu/secret, không commit/chia sẻ; giữ thêm bản sao an toàn
ngoài EC2. Bản này không chứa compiled artifact đang nằm ở máy Windows.

## Đổi tên bản sao lưu cũ

`b15-backup-002` là tên thư mục của bản backup đã kiểm thử trong giai đoạn phát triển. Tên này **không bắt buộc**: công cụ kiểm tra nội dung backup và cấu hình đã pin, không phụ thuộc tên thư mục. Có thể đổi thành `arena-backup-verified` để các lệnh dễ đọc hơn.

Trên **EC2 hiện tại**, khi không có thao tác backup/đổi Runner đang chạy:

```bash
cd ~/neon-arena-b1-pilot
# Chỉ đổi nếu đường dẫn đích chưa tồn tại; không xóa/ghi đè bản backup khác.
sudo test -d .runner-switch/b15-backup-002 && \
sudo test ! -e .runner-switch/arena-backup-verified && \
sudo test ! -L .runner-switch/arena-backup-verified && \
sudo mv -T -- .runner-switch/b15-backup-002 .runner-switch/arena-backup-verified

# Kiểm tra đầy đủ manifest, checksum và biên nhận phục hồi thử:
sudo python3 -m scripts.runner_site_backup verify \
  --directory .runner-switch/b15-pilot/site \
  --backup-directory .runner-switch/arena-backup-verified
```

Chỉ sử dụng đường dẫn mới cho các lệnh `arena_operator switch` sau khi nhận `PASS: verify`. Nếu chưa đổi tên, **tiếp tục dùng đường dẫn cũ**. Tuyệt đối không đổi `.runner-switch/b15-pilot/` (đó là trạng thái chuyển Runner đã pin), Docker project hay tên volume.

Lưu ý: đổi tên **không biến backup cũ thành backup mới**. Khi thay đổi image/cấu hình, phải tạo và xác minh một bản sao lưu mới trong thư mục chưa tồn tại. Phần đổi tên ở trên chỉ còn mang tính lịch sử đối với các image trước khi cập nhật giao diện.

## Dùng backup nào khi chuyển Local ↔ Remote?

Các lệnh chuyển Runner phải dùng **bản backup đã kiểm thử phục hồi và tương thích với image/cấu hình đang chạy**. Sau đợt nâng cấp Retro Pixel ngày 26/10/2026, bản đã xác minh trên EC2 là `.runner-switch/arena-backup-retro-81d91ee-20261026` (`verified_cold_restore_drill`, `original_mode_restored: true`, `PASS: verify`). Đây là đường dẫn dùng cho **image Retro Pixel hiện tại**, không phải tên cố định cho mọi lần phát hành.

Tên backup **không cố định**. Mỗi lần cập nhật image hay kế hoạch Runner, phải tạo một backup mới rồi dùng đường dẫn mới đó cho các lệnh `switch`. Bản `.runner-switch/arena-backup-post-ui-20261026` và các bản cũ hơn chỉ để lưu trữ/khôi phục theo kế hoạch tương ứng; **không** dùng chúng để chuyển Runner sau khi đã phát hành image Retro Pixel. Không đổi tên/xóa các thư mục backup để "cập nhật" tính tương thích.

## 3. Chuyển bot sang chạy ngay trên EC2

```bash
sudo python3 -m scripts.arena_operator switch \
  --target local --backup-directory .runner-switch/arena-backup-retro-81d91ee-20261026
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
  --target remote --backup-directory .runner-switch/arena-backup-retro-81d91ee-20261026
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
sudo python3 -m scripts.arena_operator backup --backup-directory .runner-switch/arena-backup-verified --approve-downtime
sudo python3 -m scripts.arena_operator switch --target local --backup-directory .runner-switch/arena-backup-verified
```

GID có thể đổi khi Docker/socket khởi tạo lại; nếu có, cần điều tra
chứ không bỏ qua bước kiểm tra pinned model.

## Cập nhật giao diện bền vững trên EC2 (không đổi database)

**Lưu ý: Các lệnh `season-nav-20261026` bên dưới là ví dụ lịch sử của đợt phát hành trước; không chạy lại nguyên xi trên hệ thống Retro Pixel hiện tại.** Ngày 26/10/2026 đã phát hành `neon-arena-ui:retro-pixel-81d91ee` với checkpoint `.runner-switch/release-retro-pixel-81d91ee` và tạo backup mới `.runner-switch/arena-backup-retro-81d91ee-20261026`. Lần cập nhật tiếp theo phải xác minh trạng thái hiện hành, tạo image từ **image đang pinned**, dùng tag/checkpoint/backup mới và sao lưu lạnh sau phát hành.

Sau khi code frontend được merge vào `main`, `git pull` và `docker cp` **chưa phải** một bản phát hành bền vững. Arena image và hai mô hình Local/Remote đã được cố định bằng SHA256. Không tự sửa `local.json`, `remote.json`, `plan.json`; không chạy `docker compose up --build` hoặc `down -v`.

Khi **Runner đang Local**, không có trận, upload hoặc lượt biên dịch, và đã có **backup lạnh đã xác minh**, đội kỹ thuật có thể thực hiện bảo trì giao diện như sau.

**1. Cập nhật mã và kiểm tra hệ thống** (EC2 Ubuntu):

```bash
cd ~/neon-arena-b1-pilot
git pull --ff-only origin main
sudo python3 -m scripts.arena_operator status
```

Phải thấy `mode: local`, `ready: true`, `active_matches: 0`. Chọn đường dẫn backup đã được xác minh (ví dụ bản bạn vừa tạo: `.runner-switch/arena-backup-before-ui-20261026`).

**2. Tạo image mới từ image gốc đang pinned.** Thao tác này **chưa dừng website**, chỉ thêm layer frontend, không build lại backend hay Controller:

```bash
sudo docker build --pull=false -t neon-arena-ui:season-nav-20261026 -f - . <<'EOF'
FROM neon-b1-ec2-pilot-arena:1.0
COPY --chown=10001:10001 frontend/ /app/frontend/
EOF
```

Image mới phải dùng toàn bộ thư mục frontend **đã được merge mới nhất**, bao gồm CSS, UI script, SVG và font tự host; không chỉ chép `app.js`/`index.html`. Bộ kiểm tra checksum cũng xác minh các asset landing này. Không dùng lại tag `neon-arena-ui:20261026` từng build trước lúc sửa menu Season.

**3. Phát hành có kiểm soát** (sẽ tạm gián đoạn website). Tool kiểm tra backup cũ, xác nhận image mới chỉ thêm một COPY layer, đối chiếu checksum frontend với mã Git, cập nhật **đồng thời** image pin ở Local/Remote, tạo checkpoint chứa các model cũ, drain công việc, thay **chỉ** container Arena, xác minh readiness rồi mới mở nhận trận:

```bash
sudo python3 -m scripts.arena_ui_release \
  --image neon-arena-ui:season-nav-20261026 \
  --backup-directory .runner-switch/arena-backup-before-ui-20261026 \
  --checkpoint .runner-switch/release-season-nav-20261026 \
  --approve-downtime
sudo python3 -m scripts.arena_operator status
```

Chỉ tiếp tục nếu nhận `"release": "applied"`, `mode: local`, `ready: true`, `admission_closed: false`. Nếu công cụ trả `BLOCKED`, **dừng lại và kiểm tra trạng thái; không tự chạy lại lệnh, đổi JSON hoặc xóa checkpoint**. Checkpoint có chứa khóa bí mật, chỉ giữ trong thư mục riêng tư.

**4. Backup mới bắt buộc sau cập nhật.** Backup trước đó gắn với image/model cũ nên **không dùng để chuyển Local ↔ Remote** sau khi phát hành:

```bash
sudo python3 -m scripts.arena_operator backup \
  --backup-directory .runner-switch/arena-backup-post-ui-20261026 \
  --approve-downtime
sudo python3 -m scripts.arena_operator status
```

Xác minh `verified_cold_restore_drill`, `ready: true` và lưu bản backup ngoài EC2. Dùng **backup mới** cho những lần chuyển Runner tiếp theo. Cuối cùng, trên website kiểm tra Admin/Player, đăng ký Season, tạo giải, nộp bot, đấu luyện, Official, kết quả và replay. Diễn tập chuyển Local → Remote → Local khi không còn job nếu sắp cần PC trường.

Lưu ý an toàn: nếu máy mất điện đúng lúc đang ghi lại ba model pinned, checkpoint `release-season-nav-20261026/old-*.json` còn giữ model cũ nhưng **cần người vận hành phục hồi có kiểm soát**; không tự thử tiếp lệnh khi `status` không đạt. Công cụ không tự thực hiện AWS SSH hoặc cập nhật website thay cho operator.
