# B1.2 — Pilot Windows laptop ↔ Cloud staging qua Internet

Theo [Issue #29](https://github.com/hungdo2006/battlecode_MIT_Group_8/issues/29).
Đây là hướng dẫn **operator**, không phải lệnh tự triển khai. Đợt chuẩn bị chỉ
chạy unit test, kiểm tra cấu hình và đọc metadata local. Chưa có staging/WAN PASS.

## 0. Chốt phạm vi trước mọi thao tác hạ tầng

1. Chủ account xác nhận [chi phí/Free Tier](B1_WAN_COST_REVIEW.md), ngân sách tối
   đa, thời gian chạy và thời điểm dừng. Không coi VM mới là miễn phí.
2. Có phê duyệt riêng cho **VM staging mới/độc lập**, FQDN/DNS mới và storage mới.
   Ghi account/region/instance ID, IP và tag pilot vào ghi chú private. Không dùng
   VM, volume, gateway, cert, key hay project `neon-arena` của production.
3. Staging Linux amd64 có Docker Engine/Compose, Git và Python; đủ RAM/disk cho
   build image và Arena/Caddy. Không chọn instance chỉ vì nhãn Free Tier: cloud
   Arena giới hạn 512 MiB nhưng OS, Docker, gateway và build cần tài nguyên riêng.
4. Operator cấu hình mạng **chỉ staging**: DNS tới đúng VM; TCP 80/443 cho Caddy,
   UDP 443 nếu dùng HTTP/3; quản trị VM chỉ từ nguồn được phép. Không expose
   Arena 8000, Controller 9000 hay Docker API. Laptop không cần inbound port.
5. Chuẩn bị [checklist](B1_WAN_ACCEPTANCE_CHECKLIST.md). Mọi hành động start/stop,
   DB maintenance, backup/restore hoặc xóa dưới đây chỉ dành cho staging đã duyệt.

Không SSH hoặc chạy AWS CLI vào production trong quy trình này. Việc tạo VM,
DNS, security group, Budget/alert hoặc snapshot có thể phát sinh phí: owner thực
hiện sau khi duyệt, công cụ preflight không làm những việc đó.

## 1. Chuẩn bị hai checkout và các file private

Pin **cùng full 40-character commit SHA đã được review** ở laptop và staging;
không dùng `git pull` tùy ý trong lúc pilot. Sau checkout, tracked working tree
phải sạch. Mỗi host chạy Docker local; không dùng context SSH/TCP trỏ host khác.

Trên laptop, từ repo root:

```powershell
$B1Pilot = "pilot01"
$B1Revision = "<approved-full-40-character-sha>"
$B1WorkerProject = "neon-b1-worker-staging-$B1Pilot"
New-Item -ItemType Directory -Path .b1-pilot -Force | Out-Null
if ((Test-Path -LiteralPath .b1-pilot/worker.env) -or (Test-Path -LiteralPath .b1-pilot/plan.json)) { throw "Private pilot files already exist" }
Copy-Item -LiteralPath deploy/b1-worker.env.example -Destination .b1-pilot/worker.env
Copy-Item -LiteralPath deploy/b1-pilot-plan.example.json -Destination .b1-pilot/plan.json
```

Trên terminal **của VM staging riêng**, từ repo root:

```sh
B1_PILOT=pilot01
B1_REVISION='<approved-full-40-character-sha>'
B1_CLOUD_PROJECT="neon-b1-cloud-staging-$B1_PILOT"
umask 077
mkdir -p .b1-pilot
test ! -e .b1-pilot/cloud.env || exit 1
cp deploy/b1-cloud.env.example .b1-pilot/cloud.env
chmod 600 .b1-pilot/cloud.env
```

Điền bằng editor/password manager riêng, không log/transcript/dán vào chat:

| Cloud `.b1-pilot/cloud.env` | Laptop `.b1-pilot/worker.env` |
| --- | --- |
| `ARENA_PUBLIC_DOMAIN`: FQDN staging | `ARENA_REMOTE_SERVER_URL=https://<FQDN>`; origin không path/port lạ |
| `ARENA_REMOTE_RUNNER_KEY`: random ≥32 byte | Cùng machine key, chuyển qua kênh kín |
| `ARENA_PROXY_SECRET`: random ≥48 ký tự, riêng biệt | `ARENA_RUNNER_TOKEN`: random ≥32 ký tự, **PC-only**, khác machine key |
| Không chứa Controller token/URL/Docker credentials | `SANDBOX_NAMESPACE=neon-b1-worker-staging-pilot01-bots` |

Không copy toàn bộ `.env.example` hoặc `.env` đang dùng sang Cloud. Nếu đổi
pilot ID, đổi cả project và namespace tương ứng. Hai bộ env có mục đích khác
nhau; không cần gửi bất kỳ key, password, TOTP secret hoặc SSH key cho Codex.
Trên Windows, owner giới hạn ACL của `.b1-pilot` cho operator/administrators
được duyệt trước khi điền key; không đặt file private trong thư mục chia sẻ.

Trong `.b1-pilot/plan.json`, điền revision, FQDN staging và production, các IP
**đã xác nhận độc lập** của hai bên. Lấy staging IP từ inventory VM staging đã
duyệt, production IP từ ghi chú vận hành hiện có; không truy cập website/VM
production để kiểm tra. IP staging phải public và không trùng production.
Chỉ đặt `staging_is_independent`/`network_probe_approved` thành `true` sau khi
operator xác nhận quyền kiểm tra endpoint staging. File plan không chứa secret.

Windows cần Docker Desktop Linux containers, Python/dev dependencies, nguồn
điện ổn định. Owner kiểm tra sleep/lid/Windows Update; preflight không đổi power
policy. B1 mất kết nối khi laptop ngủ hoặc mất outbound Internet.

## 2. Kiểm tra cấu hình trước khi khởi động

Có thể chạy **ngay, không cần staging/secret/Engine đang chạy**:

```powershell
.\.venv\Scripts\python.exe scripts/check_b1_wan_preflight.py config --role cloud
.\.venv\Scripts\python.exe scripts/check_b1_wan_preflight.py config --role worker
.\.venv\Scripts\python.exe scripts/check_b1_wan_preflight.py cost --plan deploy/b1-pilot-plan.example.json
```

Hai lệnh config dùng secret giả sinh trong bộ nhớ; PASS chỉ xác nhận cấu trúc
Compose. Lệnh cost với mẫu chưa điền phải **BLOCKED**, không phải giá $0.

Sau khi điền env private, chạy **trên đúng host** tương ứng:

```powershell
.\.venv\Scripts\python.exe scripts/check_b1_wan_preflight.py config --role worker --pilot-id pilot01 --env-file .b1-pilot/worker.env
```

```sh
python scripts/check_b1_wan_preflight.py config --role cloud --pilot-id pilot01 --env-file .b1-pilot/cloud.env
```

Tool chỉ nhận private env trong `.b1-pilot/<role>.env`, không tự đọc `.env` repo.
Không chia sẻ raw `docker compose config`/`docker inspect` vì có secret; dùng
preflight đã redacted hoặc `config -q`.

## 3. Operator khởi động Cloud staging và Admin MFA

Chỉ làm sau bước 0. Bash array giữ chính xác file/env/project, không thêm overlay:

```sh
B1C=(docker compose --env-file .b1-pilot/cloud.env -f compose.remote-cloud.staging.yaml -p "$B1_CLOUD_PROJECT")
"${B1C[@]}" config -q
"${B1C[@]}" build arena
# Chỉ với volume staging mới; Arena writer chưa chạy.
"${B1C[@]}" run --rm --no-deps arena python -m backend.admin_cli --data-dir /app/data migrate
"${B1C[@]}" run --rm --no-deps arena python -m backend.admin_cli --data-dir /app/data check
"${B1C[@]}" run --rm --no-deps arena python -m backend.admin_cli --data-dir /app/data create-admin --username b1.operator
"${B1C[@]}" run --rm --no-deps arena python -m backend.admin_cli --data-dir /app/data enroll-admin-totp --username b1.operator
"${B1C[@]}" up -d --no-build
```

Admin CLI cần terminal tương tác riêng; không pipe password, không ghi TOTP
secret vào evidence. Nhập secret vào Authenticator, bảo quản recovery riêng.
Giữ `ARENA_ADMIN_TOTP_REQUIRED=1`; không bật password-only/HTTP để làm test dễ hơn.

Không dùng `up --wait` cho Cloud ở bước này: thiếu Worker khiến health 503 là
đúng thiết kế. Caddy phải có public certificate hợp lệ. Dùng browser sạch để
review issuer/public CA và hostname; không cài CA QA hay dùng `-k`/TLS bypass.

Từ laptop, sau khi plan đã được operator phê duyệt:

```powershell
.\.venv\Scripts\python.exe scripts/check_b1_wan_preflight.py https --plan .b1-pilot/plan.json --expect offline --ack-staging-only
```

Tool chỉ DNS staging và GET HTTPS; pin IP vào allowlist, giữ SNI/hostname/TLS
verification, không proxy/redirect/custom CA, không gửi key/cookie hay tạo
worker session. Trước Worker cần health **503**, route machine không auth **401**.
PASS probe này chưa chứng minh hai host hoặc trận đấu thực tế.

## 4. Operator khởi động Worker laptop

```powershell
$B1W = @("compose", "--env-file", ".b1-pilot/worker.env", "-f", "compose.remote-worker.yaml", "-p", $B1WorkerProject)
& docker @B1W config -q
& docker @B1W up -d --build --wait
.\.venv\Scripts\python.exe scripts/check_b1_wan_preflight.py https --plan .b1-pilot/plan.json --expect online --ack-staging-only
.\.venv\Scripts\python.exe scripts/check_b1_wan_preflight.py host --role worker --pilot-id $B1Pilot --revision $B1Revision
```

Trên Cloud chạy inventory tương ứng:

```sh
python scripts/check_b1_wan_preflight.py host --role cloud --pilot-id "$B1_PILOT" --revision "$B1_REVISION"
```

Online health cần HTTP 200, `transport=remote-outbound`, sandbox ready,
Account-Only và Admin TOTP bật. Compose `--wait` chỉ cho biết container/Controller
sống; không chứng minh agent đã xác thực và kết nối Cloud.

Ghi SHA và image IDs mỗi service trên **cả hai host**. Host tool xác minh SHA
checkout, không tự chứng minh image được build từ SHA đó: operator phải lưu
ánh xạ build/image trước khi chạy. Lưu thêm bot toolchain image ID trên PC:

```powershell
docker image inspect neon-b1-bot:4.0 --format '{{.Id}}'
```

Các image khác vai trò không có cùng ID; so từng image với inventory của bản
build đã duyệt. Có thể ghi inventory riêng với tên mới:

```powershell
$B1Stamp = Get-Date -Format "yyyyMMddTHHmmss"
.\.venv\Scripts\python.exe scripts/check_b1_wan_preflight.py host --role worker --pilot-id $B1Pilot --revision $B1Revision --output ".qa-evidence/b1-wan/worker-host-$B1Stamp.json"
```

Tool không overwrite file có sẵn. Không commit output thực tế.

## 5. Operator thực hiện nghiệm thu WAN

Điền từng dòng [checklist](B1_WAN_ACCEPTANCE_CHECKLIST.md), không lấy PASS từ local QA:

1. Login Admin với TOTP; tạo Player/Team giả và upload Python/C++/Java từ `samples/`
   (Robot Battle dùng `hunter.py`, `hunter.cpp`, `Main.java`). Xác nhận compile
   thực sự chạy ở Controller PC; test bot lỗi cú pháp/crash/timeout riêng.
2. Chuẩn bị bốn Team, chọn Active Bot trước lock. Lên lịch hai Official độc lập
   cùng thời điểm và lịch thứ ba; quan sát hai active, lịch thứ ba chờ. Chọn
   luật đủ dài để quan sát, snapshot nguồn không đổi. Bot sample có thể hòa:
   kiểm tra draw/tiebreak đúng quy tắc, không bịa winner để coi là PASS.
3. Đối chiếu Official outcome, replay terminal/frames và standings tournament.
   Lưu replay hash riêng. Đo thời gian compile/trận/roundtrip, CPU/RAM/disk hai
   host bằng công cụ chỉ đọc; `docker stats --no-stream` chỉ chọn ID từ project
   staging, không gom container ngoài pilot.
4. Khi hai trận đã có frame, operator dừng **agent của project Worker staging**:
   `& docker @B1W stop agent`. Không tắt Wi-Fi/Engine/máy người dùng. Sau timeout
   có giới hạn, health phải 503, không dispatch mới, trận INTERRUPTED và không
   winner giả. Ghi độ trễ quan sát, frame giữ lại, trạng thái hàng chờ.
5. `& docker @B1W start agent`; chờ online preflight PASS và chạy **Official mới**.
   Trận INTERRUPTED không tự chạy lại. Xác minh không còn orphan bot container
   trong namespace pilot. Đây là dừng agent có kiểm soát; mất link WAN thật/packet
   loss vẫn là test riêng cần owner phê duyệt và không làm mất kết nối production.
6. Sai machine key/competing PC/stale reply: chỉ đổi credential/session trong
   pilot riêng khi đã dừng worker hiện tại và xác nhận không có trận thật.
   Không gửi secret vào argv, chat, ảnh hoặc ghi HAR/cookie. Hai lần connect
   tranh nhau phải 409; key sai phải 401; reply trễ không được công bố kết quả.

## 6. Cold backup, restore và restart — gate bắt buộc

Trên hai host riêng, đóng admission, đợi hoặc interrupt các trận theo policy;
chụp inventory/hash của kết quả, replay, standings và image IDs. Operator dừng
writer Cloud và agent/Controller PC bằng **đúng array/project phía trên**.

- Cloud phải bảo vệ `staging_data`, `staging_uploads`, `staging_caddy_data`,
  `staging_caddy_config`; data bao gồm SQLite/replays. Worker giữ `remote_artifacts`
  và các image/toolchain đúng ID. Env/keys/TOTP recovery đi qua kênh backup kín.
- Resolve volume theo nhãn `com.docker.compose.project=<project>` và prefix
  `<project>_`; owner xác nhận từng volume/resource trước khi backup. Không đọc
  hoặc mount volume ngoài pilot. Dùng phương thức cold backup đã review của
  operator, source mount read-only, archive mã hóa ngoài repo và checksum.
- Restore vào **hai project/volume mới**, namespace khác, DNS/private keys phù
  hợp; không overwrite nguồn. Trước startup Cloud restore, chạy offline
  `invalidate-restored-auth` trên **data restore** để fence phiên/token cũ, rồi
  check schema/integrity và Admin MFA. Không chạy hai writer trên cùng volume.
- Giữ image IDs phù hợp artifacts; chạy lại replay/hash/standings rồi Official
  mới. Đổi toolchain có thể cần reupload nguồn; không coi artifacts mất là bot thua.

Các helper `backup_docker.py`/`restore_docker.py` cũ giả định stack ba volume có
Controller local. Không dùng nguyên xi cho B1 Cloud/Worker tách host. Công cụ
preflight **không backup/restore hoặc xóa**; gate này BLOCKED cho tới khi phương
thức operator được review và drill thật PASS. Restart cùng volume không thay thế
restore drill. Xem nguyên tắc writer/MFA trong [OPERATIONS](OPERATIONS.md).

## 7. Kết thúc phiên và kiểm soát chi phí

Ghi kết quả trước khi dọn. Operator stop hai project staging bằng array đã chốt;
không `down -v`, không prune, không đụng project/volume production. Chỉ xóa
staging/volume khi owner duyệt retention và đã xác minh backup.

Owner đối chiếu resource ID/tag pilot trong AWS Console, rồi stop/terminate VM
và release tài nguyên **staging** theo kế hoạch đã duyệt. Stop container không
stop EC2; stop EC2 vẫn có thể còn EBS/IP/snapshot/DNS tính phí. Kiểm tra Billing
sau phiên và ghi các tài nguyên còn giữ, chủ sở hữu, hạn xóa. Không thêm dịch vụ
automation/alert trả phí chỉ để dọn pilot. Xem [cost review](B1_WAN_COST_REVIEW.md).
