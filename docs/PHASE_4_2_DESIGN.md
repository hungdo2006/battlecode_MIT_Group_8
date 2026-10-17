# Phase 4.2 — Account, Team, RBAC và quyết định thiết kế

Tài liệu quyết định cho nhánh `feature/player-auth-rbac`, trên Security Foundation
đã merge (`cb47898`). Quyết định sản phẩm trong yêu cầu B.1 của chủ dự án là nguồn
chính; các đề xuất kỹ thuật bên dưới không có nghĩa API tương ứng đã tồn tại.

## 1. Trạng thái và phạm vi

| Nội dung | Trạng thái |
| --- | --- |
| Official Team vs Team, mỗi Team một bot đại diện | Thiết kế sản phẩm đã duyệt; chưa triển khai |
| Captain/Member, Team sở hữu bot, User là uploader | Thiết kế đã duyệt; B.1 chỉ tạo schema |
| Active Bot theo Team/Game, thay đổi giữa các trận | Thiết kế đã duyệt; chưa thay Active Bot legacy |
| Deadline khóa bot riêng từng Official Match | Thiết kế đã duyệt; chưa có scheduler hoặc bảng match_requests |
| Official không cần Captain online/Accept | Thiết kế đã duyệt; chưa thay workflow invitation |
| Scrimmage tự phục vụ, không cần hai bên online | Định hướng Phase 5; chưa triển khai |
| SQLite version 1, migration có kiểm tra | Đã triển khai B.1, chỉ khởi chạy offline có chủ đích |
| Hash/verify Argon2id, bootstrap Admin offline | Đã triển khai B.1 |
| Account invitation/activation, credential verify, opaque sessions | Đã triển khai B.2 ở service Python độc lập; xem mục 12 |
| SQLite migration v2: idle timeout lưu theo session | Đã triển khai B.2; v1 giữ nguyên, chỉ migrate offline |
| Login/logout HTTP, cookies, authorization REST/WebSocket | Chỉ thiết kế; B.3 trở đi |
| Public HTTPS, private Admin qua Tailscale | Chỉ thiết kế; gateway Phase 4.3 |

B.1 **không** tích hợp database vào lifespan FastAPI, không tự tạo Admin khi
khởi động, không đổi `ARENA_ADMIN_CODE`, legacy sessions, upload, lobby, invitation,
Game Adapter, runner, WebSocket, Replay hoặc giao diện. Database mới không cấp
quyền Organizer trong ứng dụng hiện tại. Không được coi B.1 là bản cho phép public
Internet. Giữ nguyên bảo vệ LAN/public-host đang có.

## 2. Hiện trạng có thể tái sử dụng

- `backend/main.py:create_app/lifespan` giữ `WriterLock` trước Store/Sessions và
  Controller claim. Tiếp tục một backend writer/worker cho mỗi data volume.
- `backend/sessions.py:Sessions` lưu participant và hash cookie trong
  `sessions.json`; không phải tài khoản đã xác minh. Organizer hiện dùng mã chung
  `ARENA_ADMIN_CODE` và grant trong bộ nhớ.
- `backend/storage.py:Store` quản lý `bots.json`, `matches.json`, `rules.json`,
  `data/replays`; `uploads` là thư mục ngang cấp `data`. Metadata bot vẫn dùng
  legacy participant trong `owner`.
- `backend/lobby.py:Lobby` dùng `players.json`/`invitations.json`, Active Bot theo
  Player và cần hai Player online/Accept. Đây là workflow legacy, chưa phải Official.
- `backend/matches.py:MatchManager` chạy Bot A/B, lưu snapshot bot, luật và replay.
  Team chỉ là lớp tổ chức phía trên, không đổi luật hoặc JSON Lines của bot.
- Artifacts/image pinning thuộc Controller và volume `arena_artifacts`; account
  database không được chứa runner token, Docker socket hoặc thay quyền Controller.

Không suy luận account/team ownership từ nickname, địa chỉ IP, cookie hoặc tên bot.

## 3. Mô hình dữ liệu B.1 đã triển khai

Database: `<data-dir>/arena.sqlite3`, tương ứng `data/arena.sqlite3` native và
`/app/data/arena.sqlite3` trong volume `arena_data` của Compose. Dùng sqlite3 chuẩn,
không ORM/server. ID entity là text opaque do server tạo; ID Admin dùng UUID ngẫu
nhiên. Timestamps UTC Unix seconds. Không lưu plaintext password hoặc raw token.
Yêu cầu SQLite >= 3.38 (STRICT tables và JSON built-in); từ chối runtime cũ trước
khi tạo database. STRICT cùng CHECK ngăn chuỗi không phải số lọt vào timestamp/
version do quy tắc type affinity của SQLite. Không thay thư viện SQLite trên host.

| Bảng | Khóa và quan hệ chính | Ý nghĩa/constraints đã có |
| --- | --- | --- |
| `schema_migrations` | PK version, UNIQUE name | Checksum SQL, fingerprint schema sau migration, applied_at |
| `users` | PK id, UNIQUE username | Username canonical ASCII 3–32; display name 1–64; ADMIN/PLAYER; INVITED/ACTIVE/DISABLED; ACTIVE cần hash `$argon2id$`; auth_version >= 1 |
| `auth_sessions` | PK id; UNIQUE token_hash; FK user_id | Hash SHA-256 dạng hex 64; audience PLAYER/ADMIN; auth_version, hạn dùng, last_seen, revoked_at |
| `account_tokens` | PK id; UNIQUE token_hash; FK user_id/created_by | ACCOUNT_INVITE/PASSWORD_RESET/LEGACY_CLAIM; hết hạn, consumed/revoked; reset/claim cần target User |
| `teams` | PK id; UNIQUE slug; FK created_by | Slug canonical ASCII 3–48; DRAFT/ACTIVE/ARCHIVED; display name và timestamps |
| `team_memberships` | PK id; FK team_id/user_id | CAPTAIN/MEMBER; joined_at/left_at; UNIQUE active Team/User; tối đa một Captain còn hoạt động mỗi Team |
| `team_invitations` | PK id; FK Team/User/inviter | Invitation thành viên, khác match invitation legacy; một PENDING/Team/User; kết thúc cần responded_at |
| `submission_ownership` | PK bot_id; FK Team/uploader; UNIQUE (team_id, game_id, bot_id) | NEW cần uploader; LEGACY_VERIFIED cho phép uploader không xác định sau xác minh thủ công |
| `team_game_bots` | PK (team_id, game_id); composite FK ownership; FK selected_by | Chỉ tham chiếu bot thuộc đúng Team và Game; selected_at, revision >= 1 |
| `audit_events` | PK integer id; FK actor nullable | action, target, occurred_at và details_json hợp lệ; bootstrap ghi một sự kiện cùng transaction |

FK dùng `ON DELETE RESTRICT`: không cascade xóa tài khoản/đội/bot hoặc làm mất
chứng cứ. Dùng disable/archive/revoke trong các service tương lai. Index trên
sessions theo User/expiry, invitations PENDING và audit theo thời gian.

Trigger chặn ADMIN tham gia Team đang hoạt động và chặn nâng User đang có active
membership lên ADMIN. Muốn đổi system role phải kết thúc membership có kiểm soát.
ADMIN không tự động trở thành Captain hoặc sở hữu bot của các Team.

### Những ràng buộc không thể thay thế domain service

- SQL bảo đảm **tối đa một** active Captain. Điều kiện **đúng một Captain** khi
  Team đủ điều kiện thi đấu, chuyển Captain nguyên tử, cấm mất Captain cuối cùng
  phải được service B.2/C thực thi trong transaction trước khi có Team endpoints.
- B.1 chưa chốt một User được thuộc bao nhiêu Team trên toàn hệ thống. Schema
  chỉ cấm hai membership đang hoạt động trùng Team/User; eligibility theo giải
  sẽ được chốt trước khi mở Team APIs.
- FK uploader/selected_by chứng minh User tồn tại; chưa chứng minh đang thuộc
  Team hoặc là Captain. SQL audience không thay thế kiểm tra system role khi login.
- `bot_id` trỏ vào JSON bên ngoài, `game_id` trỏ GameRegistry: không có FK giả
  sang file JSON. Composite FK chỉ bảo đảm **binding SQL** đúng Team/Game. Ready
  compile status, source/artifact digest, membership và registry cần service kiểm tra.
- B.1 chưa có auto claim legacy, CRUD Team, session/token issuer hay public serializer.
  `audit_events` không phải sổ chống sửa bởi operator có quyền ghi database.

## 4. Migration và single writer đã triển khai

`backend/account_schema.py` chứa migration 1 bất biến sau khi release.
`backend/account_database.py:AccountDatabase` chỉ tính đường dẫn trong constructor;
import hoặc chạy backend hiện tại không tạo database.

`maintenance()` lấy `WriterLock(data_dir)` **trước cả mở/tạo SQLite**, giữ đến khi
connection đóng. Đây chính là `data/.writer.lock` mà backend giữ suốt lifespan:
bootstrap và backend không thể ghi đồng thời. Không xóa lock file để thử lại;
OS nhả lock khi process thoát. Chỉ hỗ trợ local filesystem/Docker named volume,
không dùng NFS/SMB hay nhiều backend replicas.

Mỗi connection bật `foreign_keys=ON`, busy timeout 5 giây, `synchronous=FULL`.
B.1 dùng DELETE journal mặc định, từ chối WAL để không tự thay đổi journal mode.
Database mới được tạo với mode 0600 trên POSIX; Windows kế thừa ACL của data dir.
Không tự chmod file có sẵn hoặc thay ACL/secret trên máy operator.

Migration chạy `BEGIN IMMEDIATE`, từng SQL statement, version ledger,
`PRAGMA user_version` và `application_id` trong cùng transaction; lỗi rollback
cả DDL và version. Không dùng `executescript()` gây implicit commit.

Kiểm tra version/identity, checksum migration, fingerprint catalog tables/indexes/
triggers và `integrity_check` **cùng** `foreign_key_check`. Từ chối DB lạ không có
version nhưng đã có bảng, version mới hơn, ledger lệch, schema bị sửa hoặc dữ liệu
FK hỏng. Không reset/xóa/import dữ liệu để sửa lỗi. `check` mở mode=ro, không tự
khởi tạo DB thiếu. Fingerprint là phát hiện thay đổi/incompatibility, không phải
chữ ký chống operator ác ý.

Thêm migration mới, không chỉnh lại migration đã dùng. B.3 khi tích hợp FastAPI
phải tái sử dụng lifespan WriterLock đã giữ; **không** gọi `maintenance()` lồng
trong lifespan vì đó là một writer thứ hai. Không auto migrate production ngầm.

## 5. Admin bootstrap offline B.1

Dependency mới duy nhất: `argon2-cffi>=25.1,<26`. Hash Argon2id v19 với 64 MiB,
3 iterations, 4 lanes, salt 16 bytes ngẫu nhiên, output 32 bytes. Đây là profile
RFC 9106 low-memory của [argon2-cffi](https://argon2-cffi.readthedocs.io/en/stable/api.html).
Password mới tối thiểu 15 ký tự, tối đa 1024 UTF-8 bytes; không ép mẫu ký tự,
không cắt hoặc strip password. Hash và verify trong `backend/passwords.py`; có
`needs_rehash` cho luồng login tương lai.

CLI `python -m backend.admin_cli` bắt buộc `--data-dir` rõ ràng, không có password
argument/default/env fallback. `create-admin` chỉ đọc hai lần bằng `getpass` trong
terminal tương tác, từ chối pipe và fallback echo. WriterLock được giữ trước prompt.
Không log/return hash hoặc password. Python không bảo đảm xóa mọi bản sao password
trong RAM; terminal/host/operator vẫn phải đáng tin cậy.

Username normalize lowercase; nếu trùng bất kỳ User nào thì từ chối, không reset
password, promote Player hoặc tạo thêm bản ghi trùng. Cho phép nhiều Admin **khác
username** nếu operator chủ động tạo; không ép cả hệ thống chỉ một Admin. Insert
User ACTIVE/ADMIN và audit `OFFLINE_ADMIN_CREATED` cùng transaction; lỗi audit
rollback User. Không tạo auth_session/cấp quyền web.

### Chạy native sau khi review (không tự chạy trên dữ liệu thật)

Dừng backend dùng đúng data directory trước. Không có password trong các lệnh:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m backend.admin_cli --data-dir .\data migrate
.\.venv\Scripts\python.exe -m backend.admin_cli --data-dir .\data create-admin --username arena.admin --display-name "Arena Admin"
.\.venv\Scripts\python.exe -m backend.admin_cli --data-dir .\data check
```

Linux thay executable bằng `python3`. Có thể thử trên thư mục QA riêng bằng cách
thay `--data-dir` (không mount dataset production). `migrate` không tạo tài khoản;
`check` không đòi password. Exit code 0 thành công; 1 bị từ chối/lỗi; argparse 2
cho tham số sai. Nếu backend đang chạy, bootstrap bị chặn chứ không can thiệp trận.

Image backend đã COPY toàn bộ `backend/` và cài `requirements.txt`; không cần đổi
Dockerfile hoặc sandbox. Sau này operator có thể rebuild và chạy CLI one-off với
service backend đã stop, cùng volume `/app/data`. Chưa chạy Docker QA B.1; không
coi các hướng dẫn này là chứng nhận đã bootstrap trên Docker hoặc AWS.

## 6. Target HTTP authentication/session — B.3 trở đi

Service core B.2 đã triển khai phần dữ liệu/credential/session được mô tả cụ thể
ở mục 12. Các bảo vệ HTTP/WS/gateway sau đây vẫn là thiết kế, chưa thay runtime.

- Tài khoản cá nhân ADMIN/PLAYER. Không đăng ký tự do; Admin cấp account invitation
  một lần, server chỉ lưu hash token; expiry, consumed_at/revoked_at được kiểm tra
  và consume nguyên tử. Không gửi password qua invitation.
- Admin ban đầu bằng CLI; thêm/reset/disable Admin về sau là hành động riêng có
  audit. Chuyển khỏi `ARENA_ADMIN_CODE` có giai đoạn rõ ràng, không cấp hai cơ chế
  quyền song song trên deployment public cuối cùng.
- Session opaque CSPRNG, chỉ SHA-256 hash lưu DB; rotate khi login/nâng quyền,
  expiration tuyệt đối và idle timeout, logout revoke. Đổi password/disable User
  tăng auth_version và revoke sessions; so sánh version mỗi request.
- Player/Admin dùng session audience tách biệt; Admin chỉ qua private gateway và
  phải có system_role ADMIN. Public gateway không được mở Admin action kể cả khi
  cookie ADMIN hợp lệ. Phase 4.3 enforce host/path/method allowlist và proxy trust.
- Cookie Secure/HttpOnly/SameSite, host-only; tên cookie tách biệt public/private.
  Origin exact allowlist + CSRF token cho mutating requests; WS xác thực cookie,
  Origin, audience và quyền trước accept; kiểm tra expiry/revocation khi reconnect
  và khi đang kết nối. Không đặt session/token trong URL hoặc localStorage.
- Rate limit login theo account + nguồn tin cậy, giới hạn hash concurrency vì
  mỗi Argon2 dùng 64 MiB. Generic authentication errors, không log password/hash,
  không lộ có/không username qua public endpoints.

TTL service đã có mặc định đề xuất, xem mục 12; cookie policy, rate-limit cụ thể
và recovery cần chốt ở B.3. Hiện **chưa có** các biện pháp HTTP mới này.

## 7. Team/Bot ownership và RBAC dự kiến

Các quyền dưới đây là **target design**, chưa được gắn vào REST/WS trong B.1.

| Hành động | ADMIN | CAPTAIN (PLAYER) | MEMBER (PLAYER) |
| --- | --- | --- | --- |
| Mời/disable account, quản lý cuộc thi/luật | Có qua private gateway | Không | Không |
| Tạo/quản lý Team | Điều phối/can thiệp có audit | Team của mình, theo chính sách đăng ký | Không quản trị |
| Mời/loại Member, chuyển Captain | Can thiệp có audit | Chỉ Team của mình; không làm mất Captain | Không |
| Nộp phiên bản bot/xem source, compile log | Chỉ khi được quyền vận hành có audit | Team của mình | Team của mình |
| Chọn Active Bot theo Team/Game | Không tự coi Admin là Captain | Có, bot ready của Team | Không |
| Lên lịch/khóa/hủy Official Match | Có | Không | Không |
| Live/Replay/metadata public được cho phép | Có | Có | Có |
| Scrimmage tự phục vụ | Chính sách Phase 5 | Tương lai | Tương lai, cần chốt quyền |

Mọi kiểm tra ownership dựa User/session -> membership server -> Team -> binding,
không tin team_id/uploader/role do client gửi. Source/compile logs chỉ Team đó
hoặc Admin được ủy quyền; replay public không mang execution path/token/hash auth.

Upload tương lai có bước staging immutable source/artifact, compile như hiện tại,
đăng ký ownership và publish metadata có recovery idempotent. Không thể transaction
nguyên tử giữa SQLite và JSON: cần submission operation ID/trạng thái pending trong
migration tiếp theo hoặc journal reconciliation trước khi mở API. Bot chưa hoàn
tất publish hoặc compile lỗi không thể Active/Official. B.1 chưa làm flow này.

## 8. Official Match/per-match locking — chỉ thiết kế

**Không có bảng/scheduler Official Match trong migration 1.** Đề xuất migration sau:

| Entity | Metadata dự kiến |
| --- | --- |
| `match_requests` | id, kind=OFFICIAL (SCRIMMAGE về sau), created_by Admin, team_a_id/team_b_id khác nhau, game_id, rules_snapshot, bot_lock_at UTC, scheduled_at, status, revision, deterministic match_id, created_at/locked_at, failure_code |
| `match_request_slots` | PK (request_id, side A/B), Team ID và snapshot tên Team, frozen_submission_id, uploader snapshot nếu cần, bot name/language, source/artifact digest, pinned image ID, locked_at, active_bot_revision |
| `match_execution_link` (nếu cần) | request_id UNIQUE -> existing match_id UNIQUE, trạng thái dispatch/recovery; không đưa credential runner vào public data |

Tên bảng/field cụ thể được review trước migration thực tế. Rules snapshot theo
request được chốt khi Admin lên lịch từ cấu hình hợp lệ; bot snapshot chốt ở
deadline riêng. Không dùng rules/game đang chọn hiện tại để ghi đè trận đã tạo.

### Deadline và tính đúng đắn

1. Admin chọn Team A/B, game, luật, lịch chạy và **bot_lock_at riêng từng trận**.
   Kiểm tra deadline không sau thời điểm bắt đầu. Lưu request revision/idempotency;
   chưa cần Captain online và không sinh lời mời bắt buộc Accept.
2. Trước deadline, Captain được đổi Active Bot của Team/Game cho các trận chưa khóa.
   Mỗi lần đổi tăng revision. Bản source/artifact đã publish là immutable, không
   cho sửa byte dưới cùng submission ID để né deadline.
3. Tại deadline, server transaction chọn bot ready của mỗi Team từ Active Bot,
   ghi snapshot đầy đủ cả hai slot và chuyển request LOCKED bằng compare-and-set
   revision/status. Không lấy bot_id do frontend gửi tại lúc chạy.
4. Để chống tick chậm/restart: **xử lý mọi deadline đã đến trước khi nhận thay đổi
   Active Bot**, cả trong startup recovery và transaction chọn bot. Single backend
   không nhận mutation khi offline; snapshot dùng lựa chọn trước deadline, không
   lấy lựa chọn mới sau deadline. Server UTC là nguồn thời gian; monitor clock.
5. Thiếu bot/compile lỗi/artifact thiếu khi khóa => BLOCKED rõ lý do, không tự xử
   thua hoặc chọn bot nộp sau deadline. Admin review/cancel/reschedule request mới
   có audit. Chính sách xử thua/no-show cần duyệt riêng trước vận hành Official.
6. Thay Active Bot sau deadline ảnh hưởng các trận tương lai, không sửa slot LOCKED.
   Không unlock và ghi đè lịch sử âm thầm. Team rename/membership change cũng không
   đổi snapshot trận đã khóa.

Deadline được xử lý không phụ thuộc presence/Accept. Scheduler cần recovery bền
vững và kiểm tra deadline dưới cùng serialized transaction với việc chọn bot;
không dựa timer frontend. Đây là yêu cầu cho D/E, **chưa được chứng minh bởi B.1**.

### Tương thích MatchManager và JSON Replay

Lớp điều phối mới nạp hai frozen submissions, truyền Bot A/B và rules snapshot vào
MatchManager hiện tại, kèm Team metadata ở lớp lịch sử/serializer. GameAdapter vẫn
nhận A/B, không biết account/Team/tournament. Runtime container suốt trận và JSON
Lines giữ nguyên; kết quả bot/hạ tầng vẫn phân biệt như hiện tại.

Persist deterministic match_id/link trước dispatch, đối chiếu JSON khi recovery;
crash giữa SQLite và JSON không được tạo trận thứ hai. Chưa có distributed queue
hoặc replica. Replay dùng game_id/rules của chính trận, bảo toàn mọi JSON/JSONL cũ.
Workflow legacy invitation giữ nguyên trong B.1; bước chuyển đổi sẽ có compatibility
flag/endpoint rõ ràng, không biến invitation cũ thành Official ngầm.

Scrimmage Phase 5 dùng bot đại diện được snapshot khi request, kiểm tra quyền/quota,
không đòi hai bên online. Không tái sử dụng điều kiện hai Accept của lobby legacy.
Tournament/Season là lớp tổ chức tương lai, không thêm bảng rỗng trong B.1.

## 9. Legacy migration, backup và rollback

B.1 không đọc `sessions.json` để tạo users/teams/bindings. Database mới có các bảng
trống trừ Admin được operator tạo rõ ràng và audit đi kèm. Bots, artifacts,
invitations, luật, match history và replay không bị đổi tên/xóa/ghi lại.

Migration ownership tương lai phải backup trước, inventory read-only, lập manifest
legacy participant -> account/Team **đã xác minh**. Bot không xác minh giữ unclaimed,
không chọn thi đấu Official. Lưu uploader không xác định là NULL với origin
LEGACY_VERIFIED khi có quyết định xác minh; không bịa attribution. Claim có audit,
dry-run, checksum, resumable mapping và không sửa frame replay. Không bao giờ fallback
sang legacy owner khi binding account thiếu.

Runbook cold backup Security Foundation vẫn dừng backend/Controller, đồng bộ ba
volumes `arena_data`, `arena_uploads`, `arena_artifacts` cùng exact images/digests.
Snapshot generic tự bao gồm `arena.sqlite3` trong data; operator phải dừng cả CLI
maintenance, để mọi SQLite connection đóng và không bỏ journal có giao dịch đang
phục hồi. Không copy riêng database đang ghi hoặc dùng SQLite backup đơn lẻ để
coi JSON/artifacts đã đồng bộ. Không xóa journal/WAL để "sửa" DB.

B.1 kiểm thử cold snapshot/restore **thư mục tạm** chứa SQLite bằng helper hiện
có, không chạy Docker volumes thật. Trước deployment authentication cần nâng manifest lưu DB schema/version,
kiểm tra integrity/FK và cross-store reconciliation sau restore, cùng policy revoke
sessions/tokens sau phục hồi trước khi mở login. Chưa tự thêm các bước đó vào
production backup script trong B.1. Nếu chuyển WAL sau này phải cập nhật runbook
và kiểm thử checkpoint/sidecar, không chỉ đổi pragma.

Rollback B.1: stop writers, backup cả ba volumes; chạy image/code cũ (không đọc
SQLite) vẫn dùng nguyên JSON/replay, giữ nguyên DB mới để review hoặc upgrade lại.
Không drop bảng/xóa database để rollback; không chạy down -v. Khi B.2 bắt đầu ghi
ownership/session thực tế, rollback phải review mapping và authorization; không
coi rollback code đơn thuần là phục hồi quan hệ đã thay đổi.

## 10. Thứ tự B.2–E và tiêu chí review

1. **B.1 (đã hoàn thành):** schema/migration, password primitives, offline Admin và test
   cách ly; review code và doc trước mọi tích hợp runtime.
2. **B.2 (lượt này):** Account/Invitation/Authentication/Session core độc lập,
   connection DI, Argon2 concurrency và contract rate limiting; chưa HTTP integration.
   **B.3 (chưa làm):** dependency HTTP authentication, cookies/CSRF/Origin,
   limiter thực tế, API/WS revocation; explicit offline migration và dùng lại
   WriterLock backend; chưa public Internet.
3. **C:** Team lifecycle/RBAC, bảo đảm Captain, Team invitation, immutable submission
   ownership và active bot theo game; cross-store recovery + IDOR/role tests.
4. **D:** match_requests/deadline/frozen slots, Official điều phối qua MatchManager,
   deterministic dispatch/restart, bot-lock race tests, legacy invitation transition.
5. **E:** frontend integration/WS auth/revocation, legacy verified migration runbook,
   backup/restore SQLite + JSON + artifacts, regression hai game/ba ngôn ngữ; rồi
   mới Phase 4.3 private/public gateway và security acceptance Internet.
6. **Phase 5:** self-service offline Scrimmage, quota, Tournament/Season theo nhu cầu.

Test B.1 dùng `tmp_path`, không tác động data/volumes thật:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_account_database.py tests/test_admin_bootstrap.py -ra --tb=short
.\.venv\Scripts\python.exe -m pytest tests controller_tests -ra --tb=short
```

Kiểm tra schema mới, migration idempotent/reject/rollback, FK/uniqueness, session/
token constraints, Argon2id/random salt, bootstrap duplicate/atomic audit/hidden
prompt, cross-process lock, reopen/persistence/integrity và bảo toàn JSON/Replay.
Kết quả thực thi được báo riêng; không suy ra Docker/AWS hoặc HTTP login đã PASS.

Các quyết định còn lại trước API: eligibility một User/nhiều Team, ai được tạo
Team, account invitation lifetime, recovery/reset policy, TTL sessions, Captain
transfer, no-bot tại deadline và quyền Scrimmage. Các quyết định đã duyệt ở đầu
tài liệu không cần xin duyệt lại.

## 11. Kết quả kiểm chứng B.1 trên local

Môi trường thực chạy: Windows, Python 3.13.12, SQLite 3.51.1, argon2-cffi 25.1.0.
Tất cả account tests sử dụng thư mục tạm; không tạo `data/arena.sqlite3` hoặc Admin
trong dataset thực của repository.

| Lệnh/nhóm kiểm tra | Kết quả thực tế |
| --- | --- |
| `python -m pytest tests/test_account_database.py tests/test_admin_bootstrap.py -ra --tb=short` | **44 PASS**, 0 FAIL, 0 SKIP |
| `python -m pytest tests controller_tests -ra --tb=short` (lần cuối sau STRICT) | **245 PASS**, 0 FAIL, 0 SKIP, 65.07 giây |
| `python -m pip check` | PASS, không có dependency hỏng |
| `python -m backend.admin_cli --help` | PASS, có migrate/check/create-admin; không có password option |

Suite đầy đủ bao gồm regression cũ của Robot Battle/OTT v2, Python/C++/Java native,
invitation/lobby/WebSocket/Replay, writer lock, controller protocol/lifecycle và
backup helper. Controller tests dùng môi trường test/doubles hiện có; không phải
kiểm chứng Docker Engine thật ở lượt B.1. Có một StarletteDeprecationWarning về
httpx/TestClient; không thay dependency ngoài phạm vi để xử lý cảnh báo này.

Đã thực chạy cold snapshot/restore qua helper hiện có trên **thư mục tạm**, kiểm
tra byte database/replay, verify hash sau reopen, integrity và foreign keys. Prompt
ẩn được test tự động bằng terminal/getpass doubles; chưa tạo Admin bằng cách gõ
password thật trong terminal. Chưa chạy Docker/Linux QA hoặc tác động AWS/volumes.

Chưa chứng nhận HTTP authentication/RBAC, Team lifecycle, scheduler/deadline thực
tế hoặc public access: những chức năng đó chưa được triển khai trong B.1.

## 12. B.2 — Authentication Service Core đã triển khai

B.2 dựa commit B.1 `580dd6ef0187e662859ecaa5509ecc52db9a95e9`. Chỉ thêm service
Python và tests, không tạo HTTP endpoints, middleware, frontend Login, Team CRUD,
password reset HTTP hoặc public gateway. `backend/main.py`, `sessions.py`,
NetworkSettings, ARENA_ADMIN_CODE, MatchManager, GameAdapter và Sandbox giữ nguyên.
DB tại data directory thật không được khởi tạo/migrate trong lượt kiểm thử này.

### 12.1 Account và invitation lifecycle

`backend/auth_service.py:AuthService` làm việc trên schema đã migrate:

- `get_account(id)` / `get_account_by_username(username)` trả Account whitelist
  gồm id, username, display_name, system_role, status, auth_version; không trả hash.
  Đây là internal API, không phải public account lookup/enumeration endpoint.
- `issue_invitation(admin_actor, username, name?, ttl_seconds?)` kiểm tra Admin
  session còn hợp lệ **trong transaction**, reserve username canonical và tạo
  User **PLAYER/INVITED** với ID ngẫu nhiên do server sinh. Không có role/status/
  acting-user-ID argument cho người đăng ký. Username đã tồn tại, kể cả INVITED,
  bị từ chối; không promote hoặc overwrite User cũ.
- Token 32 random bytes CSPRNG, encode base64url 43 ký tự; chỉ hash SHA-256 lưu
  `account_tokens`. Token chỉ trả khi cấp mới trong InvitationGrant; repr ẩn token.
  Invitation được bind sẵn vào User/username, không phải vé self-registration tự do.
- `activate(token, password)` chỉ nhận bearer invitation và password. Kiểm tra
  purpose ACCOUNT_INVITE, thời hạn, consumed/revoked và target PLAYER/INVITED trước
  hash, rồi kiểm tra lại sau hash trong `BEGIN IMMEDIATE`. Consume token, đổi User
  sang ACTIVE, ghi Argon2id, tăng auth_version và audit **cùng transaction**. Không
  cấp session tự động. Hai activation cùng token chỉ một bên thắng.
- `revoke_invitation(admin_actor, invitation_id)` revoke idempotent, không xóa
  lịch sử. `reissue_invitation(admin_actor, invited_user_id)` chỉ cho PLAYER đang
  INVITED; thu hồi mọi invitation cũ chưa dùng và cấp token mới nguyên tử, giữ
  nguyên ID/username. ACTIVE/DISABLED/Admin không được dùng flow này.
- `disable_account(admin_actor, target_user_id)` chuyển INVITED/ACTIVE -> DISABLED,
  tăng auth_version, revoke sessions và các account tokens chưa consume, ghi audit
  cùng transaction. Lặp disable trả false, không tạo bản ghi User mới.

Account lifecycle B.2: INVITED -> ACTIVE qua activation, INVITED/ACTIVE -> DISABLED
qua Admin. Không có tự đăng ký, Admin registration, re-enable, đổi system role,
reset password hoặc ownership migration. Admin vẫn bootstrap offline bằng CLI.
Invitation expired được xác định bằng expires_at, không cần scheduler cập nhật
status. Reissue là cách cấp lại cho User INVITED khi token cũ hết hạn/bị revoke.

### 12.2 Contract actor và authorization

Admin mutations nhận **Principal đã được server tạo từ login/validate_session**.
Principal là context nội bộ frozen, có marker trong process, không deserialize
từ JSON, không serialize nguyên object ra HTTP và không giữ qua restart. Marker
không phải chữ ký mật mã hay security boundary chống code Python trong backend;
backend process/SQLite writer là thành phần đáng tin cậy.

Service không tin claimed role/status/user ID: mỗi mutation query lại session và
User trong transaction, kiểm tra audience, ACTIVE, role thực, auth_version,
revocation, absolute/idle expiry và User ID khớp. Đổi role trong DTO, truyền dict
`{"role":"ADMIN"}` hoặc dựng Principal từ field client không cấp quyền. Principal
đã revoke/expire cũng không thể tiếp tục quản trị. Quyền Admin không vượt qua
Team RBAC, vì Team APIs chưa được triển khai.

`revoke_all(actor, user_id?)` cho phép User thu hồi tất cả sessions của chính mình,
Admin được thu hồi User khác. Thao tác tăng auth_version và revoke các hàng session
chưa revoke cùng audit; principal đang dùng cũng mất hiệu lực khi revoke chính nó.

### 12.3 Credential verification và giới hạn password work

`login(username, password, audience, source_key)` chuẩn hóa username, gọi limiter,
verify qua `backend/passwords.py`. Unknown username, sai password, INVITED,
DISABLED và sai audience đều là `AuthenticationFailed("Invalid credentials")`.
Account không đủ điều kiện dùng dummy Argon2 hash để giảm khác biệt thời gian;
không tuyên bố constant-time tuyệt đối. Hash malformed trả authentication failure;
lỗi SQLite/capacity là lỗi hạ tầng, không giả làm password sai.

Argon2 chạy **ngoài transaction**. Sau verify, transaction đọc lại status, role,
password_hash và auth_version so với snapshot; disable/revoke-all/credential update
trong lúc hash khiến login bị từ chối, không sinh session dựa dữ liệu cũ.
Activation cũng recheck token/status/version và expiry sau hash. Hash/verify không
ghi/log plaintext password và không thêm dependency ngoài B.1.

`PasswordWorkLimiter` dùng semaphore dùng chung toàn process, mặc định tối đa **1**
Argon2 work cùng lúc; không tạo hàng đợi không giới hạn. Quá capacity trả
AuthenticationBusy. Có thể inject limiter dùng chung khác khi operator review
RAM/CPU; không tạo limiter riêng cho từng request để lách giới hạn. Dummy hash
khởi tạo lazy một lần ngoài transaction; import module không tính hash/khởi tạo DB.
Chưa tự rehash/đổi password sau login; `needs_rehash` B.1 vẫn sẵn cho flow sau này.

**Rate-limit contract, chưa phải HTTP rate limiter:** constructor bắt buộc inject
LoginLimiter, không có allow-all default. `check(LoginAttempt)` trước verify có thể
từ chối bằng AuthenticationBusy; `record(attempt, succeeded=...)` nhận kết quả,
không được raise. Attempt chỉ có hash username canonical, audience và source key;
không có password/raw token/token hash. Source key do trusted server/proxy adapter
ở B.3 xác định, không lấy X-Forwarded-For không tin cậy hoặc field client tự nhận.
Rate-limit cụ thể theo account + source, bảo vệ activation và mapping HTTP errors
còn phải triển khai B.3. Test dùng limiter double được chỉ định rõ ràng.

Generic errors, session expiration và server-side invalidation được đối chiếu
với [OWASP Authentication](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html)
và [OWASP Session Management](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html).
Các nguồn này không phải bằng chứng ứng dụng đã public an toàn.

### 12.4 Opaque session, TTL và revocation

Session token độc lập mỗi login: 32 random bytes, không JWT. SQLite chỉ lưu SHA-256
token hash và ID User ổn định. SessionGrant chỉ trả raw token ở thời điểm tạo;
repr ẩn token. Không log grant bằng asdict hoặc đưa token/hash vào audit. HTTP B.3
phải chuyển token vào cookie bảo vệ, không URL/localStorage/response logging.

| Audience | System role bắt buộc | Absolute TTL đề xuất | Idle TTL đề xuất |
| --- | --- | --- | --- |
| PLAYER | PLAYER | 8 giờ | 60 phút |
| ADMIN | ADMIN | 4 giờ | 15 phút |

Đây là **mặc định để review**, không phải cấu hình production được nghiệm thu.
AuthPolicy/SessionTTL inject được, TTL nguyên dương và idle không quá absolute.
Mỗi TTL được giới hạn từ 1 giây đến 365 ngày để từ chối cấu hình vô hạn/sai kiểu.
Invitation TTL mặc định đề xuất 24 giờ, có override khi Admin cấp, cũng cần review.

Absolute expiry và idle_timeout_seconds được lưu theo **từng session**. Đổi cấu
hình/reopen không tự kéo dài session cũ. `validate_session(token, audience, touch)`
kiểm tra session/User/audience/auth_version/revoked_at, `now < expires_at` và
`now < last_seen_at + idle_timeout_seconds`; fallback last_seen là created_at.
Đúng boundary là hết hạn. Touch mặc định cập nhật last_seen; touch=false không
kéo dài idle, không có sliding absolute expiry. Mutation có actor hợp lệ cũng
ghi nhận hoạt động trong cùng transaction. Đồng hồ quay ngược trước created/last
seen bị từ chối; vận hành cần server UTC ổn định.

`logout(token, audience)` revoke đúng token/audience trong DB và audit nguyên tử,
idempotent; token không tồn tại/đã revoke trả false. Token hết hạn vẫn có thể được
thu hồi, không cấp lại quyền. `revoke_all` và `disable_account` làm session cũ
mất hiệu lực cả khi caller còn giữ Principal snapshot. B.3/password reset tương
lai bắt buộc tăng auth_version và revoke sessions trong cùng credential-change
transaction; B.2 không cung cấp raw update password endpoint.

### 12.5 Append-only migration v2

Không sửa SQL/checksum migration v1 `account_foundation` đã commit. Migration 2
`auth_service_core` thêm `auth_sessions.idle_timeout_seconds` NOT NULL > 0. Default
1 giây chỉ là fallback an toàn cho raw/manual insert; service luôn ghi TTL cụ thể.

B.1 chưa có session issuer; các hàng SQL tạo thủ công trước service không có idle
policy được phê duyệt nên v2 **đánh dấu revoke**, giữ nguyên hàng, và điền last_seen
thiếu bằng created_at. Không revoke/xóa `sessions.json` của browser legacy, không
sửa User/password/ownership/Team/JSON/Replay/artifacts. Migration dùng cơ chế atomic
version/checksum/fingerprint/integrity/FK B.1; chỉ chạy offline có chủ đích.

Runtime service từ chối DB v1 hoặc DB thiếu, không tự migrate/create. Chưa chạy
migration trên dataset thật/volumes/AWS. CLI migrate/check hiện hỗ trợ v2. Trước
triển khai sau review phải cold backup đầy đủ, dừng writer, migrate offline đúng
volume rồi check; không dùng down -v hoặc downgrade user_version thủ công. Code
B.1 cũ sẽ từ chối DB v2; rollback DB cần bản backup, còn backend legacy chưa đọc
SQLite vẫn hoạt động như cũ và không được xóa DB để giả làm rollback.

### 12.6 SQLite ownership, transaction và boundary B.3

`AccountDatabase.writer_connection(writer_lock)` mượn lock đã giữ, mở mode=rw với
DB **đã tồn tại**, validate version/FK/journal/synchronous/integrity rồi yield
connection. Không lấy WriterLock thứ hai, không gọi maintenance, không tự migrate.
AuthService nhận connection + writer_lock; constructor kiểm tra đúng data dir,
active lock, explicit transactions, schema/version và pragmas. Mỗi operation
kiểm tra lock còn giữ, không cho caller bọc transaction bên ngoài; FK phải bật.

Connection do caller sở hữu: service không đóng connection, không giữ lease riêng.
Mỗi connection được tạo/dùng/đóng trong cùng thread. Nhiều connection **trong cùng
backend đang sở hữu một WriterLock** có thể dùng BEGIN IMMEDIATE để serialize
transaction ngắn; không phải cho phép nhiều process writer. Không dùng chung
connection qua concurrent threads hoặc `check_same_thread=False` rồi bỏ khóa.

Ví dụ boundary cho B.3, **chưa gắn vào FastAPI hiện tại**:

```python
# Schema phải được migrate offline trước; code dưới không tự khởi tạo.
with WriterLock(data_dir) as writer:  # backend lifespan đã có lock này
    # Trong synchronous worker, toàn bộ open/use/close cùng thread:
    with AccountDatabase(data_dir).writer_connection(writer) as connection:
        auth = AuthService(connection, writer, login_limiter=server_limiter)
        # Principal lấy từ auth.validate_session(cookie_token, audience=...)
        # rồi chuyển trực tiếp cho mutation; không parse Principal từ request.
```

B.3 cần truyền outer writer từ lifespan, tạo/đóng connection trong worker sở hữu
nó, đợi công việc hoàn tất trước khi nhả lock. Giữ shared password limiter toàn
process và dùng limiter HTTP thực. DB/schema lỗi phải fail closed, không fallback
về legacy để cấp account permission. Những thao tác lõi không đổi JSON storage;
chưa có transaction xuyên SQLite/JSON hoặc Team ownership migration.

### 12.7 Kiểm thử và phần còn lại

Tests mới ở `tests/test_auth_service.py` chỉ dùng tmp_path, clock inject và các
limiter double rõ ràng. Expiration/race dùng clock/barrier, không sleep để chờ TTL.
Kiểm tra activate cạnh tranh trên hai connection, actor giả/stale, audience,
idle/absolute expiry, revoke/disable/version, không lưu/log raw secrets, rollback
audit lỗi, migration v1 -> v2 giữ User/ledger v1 và bảo toàn JSON/replay. Có test
import/construct app không mở SQLite và service không tạo DB thiếu, không dùng
được sau unlock hoặc lồng transaction của caller.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_auth_service.py -ra --tb=short
.\.venv\Scripts\python.exe -m pytest tests/test_account_database.py tests/test_admin_bootstrap.py -ra --tb=short
.\.venv\Scripts\python.exe -m pytest tests controller_tests -ra --tb=short
.\.venv\Scripts\python.exe -m pip check
```

Giới hạn B.2: chưa có HTTP/cookie/CSRF/Origin/WS auth, limiter HTTP thực, account
recovery/reset/re-enable, Team RBAC, xử lý session restore sau backup hoặc gateway.
Không được đưa service ra Internet chỉ vì unit tests PASS. Không thay bảo vệ
LAN/public-host hiện có. B.3 đề xuất chỉ tích hợp HTTP authentication có kiểm soát,
cookie/CSRF/Origin, real rate limiting, dependency session và tests REST/WS, cùng
review chuyển đổi legacy quyền rõ ràng; chưa Team/Official/Scrimmage hoặc public
deployment. Dừng review B.2 trước khi triển khai B.3.

### 12.8 Kết quả kiểm chứng B.2 thực tế

Chạy native Windows, Python 3.13.12/SQLite 3.51.1/argon2-cffi 25.1.0, dữ liệu tạm:

| Lệnh/kiểm tra | Kết quả |
| --- | --- |
| `python -m pytest tests/test_account_database.py tests/test_admin_bootstrap.py -ra --tb=short` | **44 PASS**, 0 FAIL, 0 SKIP, sau migration v2 |
| Nhóm account + bootstrap + auth service trong lượt kiểm thử liên quan | **98 PASS** (54 test mới B.2 + 44 B.1) |
| `python -m pytest tests controller_tests -ra --tb=short` trên code cuối | **299 PASS**, 0 FAIL, 0 SKIP; 74.75 giây |
| `python -m pip check` | PASS; không có dependency hỏng, không thêm dependency B.2 |
| So sánh AST/literal FOUNDATION với commit B.1 `580dd6e` | PASS; SQL migration v1 giữ nguyên |
| `git diff --check`, syntax/whitespace của file Python mới | PASS |

Suite đầy đủ chạy lại các tests hai game, Python/C++/Java native, lobby/invitation,
WebSocket/Replay, writer lock và controller hiện có, bên cạnh service mới. Có một
StarletteDeprecationWarning về httpx/TestClient như trước; không đổi dependency
ngoài phạm vi. Controller tests dùng test doubles hiện có, không thay cho Docker QA.

Đã kiểm tra activation cạnh tranh bằng hai thread/connection và barrier; clock
fake cho TTL/race, không sleep chờ expiry. Đã kiểm tra import/construct app trong
process riêng không mở SQLite, dữ liệu legacy giữ nguyên và không tạo DB thiếu.
Chưa kiểm thử Docker/Linux, trình duyệt authentication, Internet hoặc AWS trong
lượt này; không bootstrap/migrate trên dữ liệu hoặc Docker volumes thật.
