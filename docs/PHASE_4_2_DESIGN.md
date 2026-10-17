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
| Login/logout, cookies, authorization REST/WebSocket | Chỉ thiết kế; B.2 trở đi |
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

Thêm migration mới, không chỉnh lại migration đã dùng. B.2 khi tích hợp FastAPI
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

## 6. Authentication/session được thiết kế cho B.2, chưa triển khai

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

TTL cookie/token, rate-limit cụ thể và chính sách recovery cần chốt ở B.2; schema
chỉ cung cấp trường dữ liệu. Hiện **chưa có** các biện pháp HTTP mới này.

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
có, không chạy Docker volumes thật. B.2 cần nâng manifest lưu DB schema/version,
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

1. **B.1 (lượt này):** schema/migration, password primitives, offline Admin và test
   cách ly; review code và doc trước mọi tích hợp runtime.
2. **B.2:** service accounts, invitation registration/login/logout/revoke,
   dependency authentication, sessions và rate limits/CSRF/Origin; explicit migration
   trong cửa sổ maintenance, tái sử dụng WriterLock backend; chưa public Internet.
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
