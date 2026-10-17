# NEON ARENA

## Phase 4.2D — Official Match Scheduling (D1–D3 QA candidate)

**D1 source attestation:** A ready bot uploaded after this feature is installed
receives a SHA-256 attestation of the original submitted source in SQLite as part
of the submission-ownership transaction. An Official Match only locks a bot if
its current source matches this original recorded digest. Existing C2/C3
submissions without an attestation remain accessible/selectable for ordinary
Team workflows, but cannot enter Official Match until re-submitted and compiled.
When source is changed, unreadable or missing, only the affected Official request
becomes BLOCKED; other due requests continue. The v5 migration definition was
updated while PR #7 was still unmerged; QA must use **fresh disposable data**
rather than reusing an earlier v5 test database with a different checksum.


**Nhánh phát triển:** `feature/official-match-scheduling`. Code D1–D3 đã được thêm vào PR #7, **chưa merge và chưa có QA end-to-end độc lập cho D2/D3**.

D1 bổ sung migration SQLite v5 (append-only), `official_match_requests` và `official_match_slots`, API Admin lên lịch/cancel, lịch đọc chỉ cho Admin hoặc Player thuộc Team liên quan, bot deadline UTC Unix seconds, snapshot luật khi xếp lịch, và source checksum cùng Active Bot revision khi khóa bot. Khi bot thiếu/sai game/chưa ready hoặc Team bị archive lúc khóa, trạng thái `BLOCKED` rõ nguyên nhân (không xử thua, không lựa chọn bot mới sau deadline). Tick nền xử lý deadline và thao tác Captain chọn Active Bot cũng xử lý deadline quá hạn **trước khi** thay lựa chọn trong cùng SQLite transaction.

**D2 — Dispatch & recovery:** Worker kiểm tra deadline mỗi giây, chỉ khởi chạy Official Match khi `ARENA_RUNNER=sandbox` và controller báo ready. SQLite claim chuyển `LOCKED → DISPATCHING` **trước** mọi side effect; mỗi request có match ID cố định. Những claim không có kết quả rõ ràng khi restart được đánh dấu `INTERRUPTED` và **không tự chạy lại**. Kết quả hoàn thành chỉ được công bố `COMPLETED` sau khi JSON match và replay hợp lệ; không suy diễn thắng/thua do lỗi hạ tầng. Artifact ID/digest đã chốt ngay lúc lock được đối chiếu tại dispatch và ngay trước khi MatchManager khởi tạo session. Tối đa hai trận đồng thời. Trận Official được tạo bằng snapshot game/rules riêng của request, độc lập với việc Player online hoặc trạng thái cuộc thi legacy.

**D3 — API & UI:** Account-Only Admin có trang Official Match để chọn 2 Team ACTIVE, game, deadline khóa và giờ đấu. Player chỉ đọc những trận có liên quan đến Team mình đang tham gia. Replay lấy qua `/api/{admin|player}/official-matches/{request_id}/replay` với cookie audience/CSRF/IDOR policy, và frontend dùng polling đọc replay đang chạy (không mở WebSocket legacy). Kết quả Official Team không bị tính nhầm sang standings dành cho Player legacy.

**Chính sách vận hành:** chưa có tự động retry một claim đã dispatch hoặc trận interrupted, vì có thể gây chạy trùng. Admin cần lên lịch yêu cầu mới sau khi kiểm tra nguyên nhân. Bot cũ thiếu attestation phải nộp lại, bot legacy không đủ điều kiện thực thi Official. Không chuyển runner về subprocess để tránh yêu cầu Sandbox. Scheduler không thể bảo đảm chính xác thời điểm tick đến từng mili-giây; deadline bot được bảo vệ bằng transaction cùng Active Bot update. Cần migrate offline trên **fresh disposable database** bằng `python -m backend.admin_cli --data-dir <disposable-data-dir> migrate`; không được dùng lại v5 từ commit D1 trước đó hoặc migrate AWS/volume vận hành chỉ để thử.

**QA trước merge:** Chạy `python -m pytest tests controller_tests -ra --tb=short`, browser Chrome Account-Only và Legacy, `python scripts/check_account_ui.py`, Docker sandbox, fingerprint CRLF/LF, restart/kill sau claim, side-effect fault injection, CSRF/Origin/IDOR, artifact replacement, replay isolation và đồng bộ rank/match mới trên main. PR #7 vẫn Draft đến khi QA độc lập PASS.


Nền tảng thi đấu bot đa game dành cho bài tập nhóm môn Lập trình mạng. Hiện hỗ trợ **Robot Battle** và **OTT v2**, đăng ký qua **GameRegistry + GameAdapter**. Backend **Python FastAPI**, frontend **HTML/CSS/JavaScript thuần + Canvas**, giao tiếp **HTTP REST + WebSocket**, bot **legacy subprocess hoặc Docker sandbox**, dữ liệu **JSON**. Chế độ native không cần Docker, Node.js hoặc database server.

**v3.0: Organizer điều hành, Player nộp bot và Accept/Decline lời mời.** Presence qua WebSocket/heartbeat, một Active Bot riêng cho mỗi Player, tự chạy đúng một trận khi cả hai Accept và tự mở cùng Live Arena trên ba trình duyệt. Game Lock, Game Adapter, runner đa ngôn ngữ và replay JSONL được giữ. Xem [demo ba laptop](docs/MULTIPLAYER.md), [báo cáo kiểm thử v3](docs/MULTIPLAYER_VERIFICATION.md), [networking](docs/NETWORKING.md); hướng dẫn trong app ở `/lan`.

> **Chỉ dùng local/LAN riêng.** Legacy runner (`start.bat`/Phase1) chỉ dành cho code tin cậy: subprocess có quyền của tài khoản server, không phải sandbox. Phase2 bổ sung cách ly Docker nhưng không bảo đảm an toàn tuyệt đối. Không công khai tính năng thực thi code lên Internet.
## Phase 4.2C — Team Management, Bot Ownership & Active Bot (merged)

Phase 4.2C1–C3 đã qua QA độc lập và merge qua PR #5: Team Lifecycle, Bot Ownership, Captain Active Bot và giao diện Team cơ bản. Phase 4.2D đang được triển khai và QA trong PR #7; AWS Internet public Phase 4.3 chưa triển khai. Không migrate volume đang dùng chỉ để kiểm thử.

## Phase 4.2C1 — Team Lifecycle, Membership & RBAC

Chế độ Account-Only đã được mở rộng hỗ trợ quản lý Team, tư cách thành viên, hệ thống lời mời và RBAC. Mỗi Player chỉ được tham gia tối đa 1 Team active toàn hệ thống (DRAFT hoặc ACTIVE); Player tạo Team sẽ tự động trở thành Captain đầu tiên một cách nguyên tử. Captain có quyền quản lý thông tin Team, kích hoạt (DRAFT -> ACTIVE), gửi/thu hồi lời mời, xóa thành viên, chuyển giao quyền Captain, hoặc lưu trữ Team (ARCHIVED giải tán thành viên và hủy lời mời pending). Admin có quyền kiểm tra và phục hồi Captain nếu Captain cũ bị vô hiệu hóa mà không nhận quyền thành viên.

Migration v3 (`team_lifecycle_membership`) bổ sung ràng buộc toàn cục `membership_active_user_global` qua partial UNIQUE index trên SQLite. API mới được tích hợp dưới `/api/player/team*` và `/api/admin/teams*` với xác thực audience và CSRF. Các endpoint nộp bot của Team (Phase C2) và Active Bot (Phase C3) tiếp tục giữ mã bảo vệ 403. Xem [đặc tả, quy tắc vòng đời và hợp đồng API](docs/PHASE_4_2_DESIGN.md#15-phase-42c1--team-lifecycle-membership--rbac).

## Phase 4.2B.3.2 — Account-Only cutover

Chế độ Account-Only đã có Player/Admin login, activation, logout, CSRF, REST và
WebSocket theo audience. Cookie host-only được tách ở `Path=/api/player` và
`Path=/api/admin`; legacy `arena_session`, Organizer code, upload/Active Bot và
match invitation không cấp quyền khi `ARENA_ACCOUNT_ONLY=1`. Admin có thể quản lý
game/rules/competition và xem history/replay qua serializer an toàn. Player được
xem game/rules/competition và tải sample; history legacy mặc định Admin-only.

Ba chế độ cấu hình:

| Chế độ | Cấu hình |
| --- | --- |
| Legacy | `ARENA_ACCOUNT_AUTH=0`, `ARENA_ACCOUNT_ONLY=0` |
| Coexistence QA B.3.1 | `ARENA_ACCOUNT_AUTH=1`, `ARENA_ACCOUNT_ONLY=0` |
| Account-Only | `ARENA_ACCOUNT_AUTH=1`, `ARENA_ACCOUNT_ONLY=1` |

Account-Only vẫn chỉ hỗ trợ local/LAN và exact origins. HTTP chỉ dành cho QA có
chủ đích với `ARENA_AUTH_ALLOW_HTTP=1`; không mở ra Internet. Team CRUD, Team bot
ownership, Official Match và Scrimmage chưa có, nên submission/Active Bot tạm khóa.
Xem [thiết kế, endpoint và runbook](docs/PHASE_4_2_DESIGN.md#14-b32--full-account-only-cutover).

QA Docker phải dùng project/volumes mới và bind loopback. Chuẩn bị `.env` QA riêng
với runner token ngẫu nhiên, `ARENA_BIND_IP=127.0.0.1`, exact origin
`http://127.0.0.1:8000`, rồi migrate/bootstrap khi backend đang dừng:

```powershell
docker compose -p neon-arena-auth-qa build
docker compose -p neon-arena-auth-qa run --rm --no-deps arena python -m backend.admin_cli --data-dir /app/data migrate
docker compose -p neon-arena-auth-qa run --rm --no-deps arena python -m backend.admin_cli --data-dir /app/data create-admin --username qa.admin --display-name "QA Admin"
docker compose -p neon-arena-auth-qa up -d --wait
```

Không dùng `docker compose down -v`. Sau restore, trước startup đầu tiên, chạy CLI
offline `invalidate-restored-auth` trên volume mới để revoke toàn bộ session và
one-time token có trong snapshot. Tài khoản, bot, replay và ownership không bị xóa.

## Phase 4.2B.3.1 — HTTP authentication foundation (opt-in)

Đã có activation, Player/Admin login/logout/me, Admin account invitations và HTTP
security tests. `ARENA_ACCOUNT_AUTH` mặc định **OFF**; bật chỉ cho QA local/LAN với
DB đã migrate offline và exact origin allowlist. **Login mới chỉ bảo vệ `/api/auth/*`**,
chưa bảo vệ bot/match hoặc WebSocket legacy, chưa thay Organizer code và chưa cho
phép public Internet. Xem [gate, endpoints, cookie/CSRF, rate limits và ma trận legacy](docs/PHASE_4_2_DESIGN.md#13-b31--http-authentication-foundation).

## Phase 4.2B.1 — Account foundation (offline)

SQLite schema, Argon2id và CLI tạo Admin offline đã có; **chưa bật web login/RBAC**
và chưa thay legacy sessions/Organizer code. Xem [thiết kế đã chốt, phạm vi B.1,
lệnh bootstrap, migration và rollback](docs/PHASE_4_2_DESIGN.md). CLI bắt buộc
`--data-dir`, giữ cùng WriterLock với backend và chỉ hỏi password qua terminal;
không tự khởi tạo database/Admin khi server chạy. B.1 không cho phép mở Internet.

## Security Foundation — trước Phase 4.2

Backend giữ OS lock trên data volume trước khi đọc/ghi Store và claim Controller.
Controller dùng epoch/lease fencing, không cho owner mới chiếm lease còn sống,
không tái dùng job ID sau cleanup. Cold backup kiểm tra cả ba volumes và lưu exact
image IDs/images để khôi phục vào bộ volume mới. Không thay đổi game/UI và chưa
triển khai Authentication/RBAC hoặc public gateway.

Xem [runbook, giới hạn và lệnh kiểm thử](docs/SECURITY_FOUNDATION.md).
Lượt [final review và Docker QA](docs/SECURITY_FOUNDATION_DOCKER_QA.md) đã kiểm
chứng shared-volume lock, lifecycle và backup/restore bằng pinned images trên local.

## v4.0 Phase 3.1 — Premium Liquid Glass

Tinh chỉnh trên Liquid Light theo [đặc tả được chủ dự án cung cấp](docs/NEON_ARENA_FIGMA_LIQUID_GLASS_BRIEF.md):
sidebar/header nổi, ba mức kính, phản sáng mềm, dialog và thanh replay có chiều sâu.
Form, compiler diagnostics, danh sách dữ liệu và bàn Canvas vẫn dễ đọc trên nền chắc.
Không sửa backend, luật game, WebSocket hoặc sandbox. Phiên Codex này **không trực tiếp
truy cập Figma MCP**; màu/blur/radius là thông số thiết kế cho dự án.

```powershell
docker compose up --build -d --wait
# QA cô lập, cần Docker Desktop Linux containers, Playwright và Chrome:
.\.venv\Scripts\python.exe scripts/check_liquid_glass.py
```

Docker tự gắn phiên bản theo SHA-256 vào URL CSS/JS/SVG khi build. Sau cập nhật,
tải lại trang bình thường để nhận HTML mới; không cần xóa cache Chrome. Khi sửa
frontend và chạy native, chạy `py -3 scripts/version_frontend.py` trước khi reload.
Xem [thay đổi, kiểm thử và ảnh trước/sau](docs/LIQUID_GLASS.md).

Lượt [Final visual refinement](docs/FINAL_GLASS_REFINEMENT.md) tăng độ trong suốt,
reflection và chiều sâu; session có floating sheet riêng, Arena có frame kính và
stage đặc. Các sheet nội dung không dùng blur để giảm chi phí trên laptop.
QA và ảnh của lượt này được lưu riêng:

```powershell
.\.venv\Scripts\python.exe scripts/check_liquid_glass.py --output-dir docs/screenshots/glass-refinement/after
```

## v4.0 Phase 3 — Liquid Light workspace

Giao diện sáng với sidebar kính nổi, typography hệ thống, form/card mềm mại và
Arena xanh/amber dễ theo dõi. Organizer, Player, submission, lobby, invitation,
history và replay cùng dùng design system mới. Không thêm framework hoặc sửa
backend/Docker sandbox. Có busy state chống gửi trùng, xác nhận thao tác và phản hồi
khi mất kết nối. Xem [thiết kế và hướng dẫn](docs/LIQUID_LIGHT.md),
[kiểm chứng Phase 3](docs/LIQUID_LIGHT_VERIFICATION.md) và
[ảnh giao diện thật](docs/screenshots/liquid-light/overview.png).

```powershell
docker compose up --build -d --wait
# QA trên project/volume riêng, cần Playwright + Chrome:
py -3 scripts/check_liquid_ui.py
```

## v4.0 Phase 2 — Docker Bot Sandbox

Compose mặc định chạy **sandbox runner**: backend phục vụ website, controller nội bộ có
xác thực, compile container riêng và runtime container riêng cho mỗi bot suốt trận.
Backend/bot không có Docker socket. Giữ nguyên giao diện, hai game, lobby và replay.

Windows Docker Desktop dùng **Linux containers/WSL2**:

```powershell
py -3 scripts/configure_sandbox.py
docker compose up --build -d --wait
Invoke-RestMethod http://localhost:8000/api/health
```

Mở http://localhost:8000; LAN dùng IPv4 của máy server. Health phải trả
`runner.mode=sandbox`, `runner.ready=true`. Mã Organizer và token riêng ở `.env`,
không hardcode vào frontend hoặc commit. Linux dùng `python3` thay `py -3` và group
socket phù hợp. `start.bat` vẫn chạy legacy cho bot tin cậy.

- [Cài đặt, kiến trúc, resource limits, kiểm tra sandbox, backup và rollback](docs/SANDBOX.md)
- [Kết quả kiểm chứng Phase 2](docs/SANDBOX_VERIFICATION.md)
- Phase1 được giữ trong `compose.legacy.yaml`; chuyển đổi có chủ đích sau khi đóng cuộc thi.
- Không có fallback từ sandbox sang legacy khi lỗi. Submission cũ được giữ, cần nộp lại source khi đổi runner.
- Controller có quyền Docker Engine rất mạnh; chỉ dùng trong mạng tin cậy. Container không bảo đảm cách ly tuyệt đối.

```powershell
docker compose logs -f arena controller
docker compose restart arena
docker compose down                 # giữ dữ liệu, không thêm -v
docker compose up -d --wait
py -3 scripts/check_docker.py --build --browser
```

## Chạy nhanh trên Windows

Nếu Python đã cài, chạy **`start.bat`**, rồi mở **http://127.0.0.1:8000**. Script tạo `.venv` và cài thư viện khi cần; lần đầu cần Internet. Để mở cuộc thi mới, đặt `ARENA_ADMIN_CODE` trước khi chạy server theo mục Organizer bên dưới. Trạng thái ban đầu là đang cấu hình, chưa cho tạo trận.

Hoặc mở PowerShell trong thư mục dự án:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe run.py
```

Nếu chỉ có lệnh `python`, dùng `python -m venv .venv` ở bước đầu. Không cần activate nên không phải thay Execution Policy của PowerShell. Bấm **Ctrl+C** để dừng server. Server dùng một process, mặc định bind **`0.0.0.0:8000`** để máy khác trong LAN truy cập. Console in URL local và các IPv4 LAN.

Chỉ dùng trên một laptop: `.\.venv\Scripts\python.exe run.py --host 127.0.0.1`. Đổi cổng: `run.py --port 8001`. `start.bat` cũng nhận các tham số này. Khi chuyển project sang máy khác, tạo `.venv` mới và nộp lại bot; `.venv`/executable/đường dẫn runtime của máy cũ không bảo đảm dùng được.

## Ba laptop cùng LAN

1. Laptop 1 đặt `ARENA_ADMIN_CODE`, chạy `start.bat`, xem IPv4 Wi-Fi bằng `ipconfig`. Mở quyền Organizer, chọn game, lưu luật rồi **LOCK GAME / OPEN COMPETITION**.
2. Laptop 2 và 3 mở `http://IP-MAY-CHU:8000`, đặt nickname Hoang/Minh. Không cần Python/JDK/G++ trên hai máy này.
3. Mỗi Player upload một source `.py`/`.cpp`/`.java` cho game hiện tại; trong **MY SUBMISSIONS** nhấn **SET AS ACTIVE BOT**. Giữ website mở để trạng thái READY.
4. Organizer vào **Phòng thi đấu**, thấy hai Player READY và Active Bot/ngôn ngữ, chọn hai người rồi **INVITE TO MATCH**.
5. Hoang và Minh nhận popup; mỗi người nhấn ACCEPT hoặc DECLINE. Một Accept chưa tạo trận. Hai Accept tự tạo một trận; cả ba trình duyệt tự mở cùng Live Arena.
6. Kết quả/replay hiển thị **Hoang / C++ VS Minh / Python** và tên bot. Pause/Reset/tua chỉ ảnh hưởng playback của từng máy. Kết thúc/cleanup trả Player về READY hoặc OFFLINE.

Frontend dùng REST tương đối và `location.host` cho WS/WSS. Kiểm tra firewall TCP 8000 trên mạng Private/LocalSubnet, Wi-Fi không bật client isolation. Không dùng `0.0.0.0` hoặc localhost trên máy khách. Xem [hướng dẫn chi tiết](docs/MULTIPLAYER.md).

Cookie giữ 30 ngày, nickname không phải định danh bảo mật. Các tên trùng được phân biệt bằng ID ngắn trên dashboard/popup. Online chỉ tính từ WebSocket thực; mở nhiều tab không offline khi chỉ đóng một tab. Heartbeat mỗi 10 giây, timeout 35 giây. Reconnect không tự Accept; có thể mở lại trận đang chạy. Restart giữ identity/Active Bot/history, hủy lời mời đang chờ và không giả lập các kết nối cũ thành online.

Kiểm thử tự động ba browser (cần Playwright và Chrome, mặc định dùng server/data tạm riêng và tự dừng):

```powershell
.\.venv\Scripts\python.exe scripts/check_multiplayer_ui.py --lan-ip IP-MAY-CHU
```

Kiểm tra HTTP/WS trên server QA đang chạy, cần cùng `ARENA_ADMIN_CODE` trong shell của script; script tạo ba phiên demo và tự Accept cho hai Player mô phỏng:

```powershell
.\.venv\Scripts\python.exe scripts/check_lan.py --url http://IP-MAY-CHU:8000 --game ott_v2 --language-b java --open-competition
```

Automation trên một host không thay thế kiểm chứng ba laptop vật lý. Không cần Internet sau khi cài dependency/compiler.

## Organizer và Player

Mọi browser bắt đầu **Player**, kể cả máy chủ. Player nộp bot của mình, chọn Active Bot, trả lời lời mời và xem live/replay. **Organizer** chọn game, cấu hình luật, mở/đóng cuộc thi và mời hai Player READY; Organizer không được nộp/chọn bot hoặc tham gia với tư cách Player. Không ai tạo trận trực tiếp qua API cũ; chỉ hai lượt Accept mới khởi chạy. Backend kiểm tra mọi đường API; không tin game/luật do client tự khai để vượt khóa.

Trước khi chạy server, trong PowerShell:

```powershell
$env:ARENA_ADMIN_CODE = Read-Host 'Nhap ma Organizer cho nhom'
.\start.bat
```

Dùng mã đủ dài, chỉ chia sẻ với ban tổ chức. Nhấn **Mở quyền Organizer**, nhập mã rồi xác minh. Mã đọc từ environment lúc startup, không hardcode frontend, không lưu vào JSON/localStorage và không chuyển vào compiler/bot. Rời Organizer hoặc restart thu hồi quyền; nickname/cookie và **trạng thái cuộc thi đã lưu** được giữ. Đổi mã cần restart. Thiếu mã: không có quyền Organizer để mở cuộc thi/gửi lời mời mới; vẫn xem được history/replay.

**Một cuộc thi, ba trạng thái:**

1. **SETUP / chờ ban tổ chức:** Organizer chọn game ở dropdown/card, lưu/reset luật. Mọi client theo game server chọn; không dùng lựa chọn localStorage cũ. Chưa tạo trận được. Có thể chuẩn bị/nộp bot, nhưng chỉ cho game hiện tại.
2. **LOCK GAME / OPEN COMPETITION:** server chốt `active_rules_snapshot` từ luật đã lưu, lưu khóa vào disk và phát WebSocket. Chỉ game đã khóa được nộp bot/tạo trận; cả hai bot phải tương thích. Không nhận `rules` override từ ai, kể cả Organizer. Form luật/game read-only. Giá trị chưa Save trên browser không đi vào snapshot.
3. **CLOSE COMPETITION / UNLOCK:** hủy lời mời chưa bắt đầu với reason `competition_closed`, chặn trận mới ngay. Nếu còn trận/chờ/cleanup bot thì trạng thái **DRAINING**, chưa đổi game/luật hoặc mở lại được. Khi hết task, WebSocket tự báo SETUP. Có thể chờ kết thúc hoặc Organizer hủy hợp lệ qua `POST /api/matches/{id}/cancel`; cancel thu hồi bot, lưu interrupted/replay đã có rồi mới cho cấu hình lại.

Server giữ `selected_game_id`, `competition_locked`, `active_rules_snapshot` trong `data/rules.json` version 3. V1/v2 tự chuyển sang **chưa mở**, không xóa bot/replay. Restart giữ khóa/snapshot; trận đang chạy bị interrupted như trước. Mỗi trận lưu riêng `game_id`, `rules` và `rules_snapshot`; đổi cuộc thi không sửa lịch sử. Renderer luôn dùng game của frame/trận.

`/ws/competition` gửi state đầy đủ cùng revision/server_id, initial state cho client mới, tự reconnect khi mất mạng. Đây là trạng thái mới nhất của một cuộc thi, không phải log lịch sử các lần mở/đóng. FastAPI dùng một admission lock cho cấu hình/open/close/create-match; submission kiểm tra game trước compile và kiểm tra lại trước commit nếu game đổi trong lúc compile.

Đây là phân quyền đơn giản cho nhóm tin cậy. Demo HTTP LAN không mã hóa mã Organizer; HTTPS dùng khi có reverse proxy phù hợp. Không xem cơ chế này là sandbox hay hệ thống tài khoản Internet.

Khi chuẩn bị VPS, dùng **ARENA_READ_ONLY=1**, **ARENA_ALLOWED_HOSTS=arena.example.com** và backend loopback sau proxy TLS. Domain public chỉ được thêm trong chế độ chỉ xem; upload/tạo trận/chỉnh luật bị chặn. Frontend tự dùng HTTPS/WSS. Xem `deploy/nginx.conf.example`; chưa công khai runner lên Internet. Biến `ARENA_HOST`, `ARENA_PORT` và cờ `--proxy-headers --forwarded-allow-ips 127.0.0.1` được mô tả trong [NETWORKING.md](docs/NETWORKING.md), theo [FastAPI Behind a Proxy](https://fastapi.tiangolo.com/advanced/behind-a-proxy/).

### Cài Python

1. Cài **Python 3.11 trở lên, 64-bit** từ [python.org](https://www.python.org/downloads/windows/). Dự án đã kiểm tra với Python 3.13.
2. Với bộ cài truyền thống, chọn **Add python.exe to PATH** và thành phần pip. Với Python Install Manager, cài runtime rồi kiểm tra `py -3 --version`. Tham khảo [hướng dẫn Windows chính thức](https://docs.python.org/3/using/windows.html).
3. Mở lại PowerShell và kiểm tra:

```powershell
py -3 --version
python --version
```

Chỉ cần một trong hai lệnh hoạt động. Nếu `python` mở Microsoft Store hoặc báo không truy cập được, kiểm tra App execution aliases trong Windows Settings; dùng `py -3` hoặc đường dẫn đầy đủ tới Python đã cài.

### Cài G++ cho C++

Nếu `g++ --version` đã chạy được thì bỏ qua phần này.

1. Cài [MSYS2](https://www.msys2.org/).
2. Mở terminal **MSYS2 UCRT64** từ Start menu và chạy:

```sh
pacman -S --needed mingw-w64-ucrt-x86_64-gcc
```

3. Thêm `C:\msys64\ucrt64\bin` vào **User PATH** trong Environment Variables; điều chỉnh nếu cài MSYS2 ở vị trí khác. Đây là compiler native Windows, theo [hướng dẫn MinGW-w64](https://www.mingw-w64.org/getting-started/msys2/).
4. Mở lại PowerShell:

```powershell
g++ --version
```

Backend biên dịch bằng `g++ -std=c++17 -O2`. Không dùng thư viện JSON bên ngoài trong bot mẫu.

### Cài JDK cho Java

1. Cài **JDK 17 hoặc 21, 64-bit**, chẳng hạn [Eclipse Temurin](https://adoptium.net/temurin/releases/). Cần JDK có **javac**, chỉ cài JRE thì không biên dịch được.
2. Chọn thêm Java vào PATH và thiết lập `JAVA_HOME` trong bộ cài; xem [hướng dẫn cài Windows của Adoptium](https://adoptium.net/installation/windows).
3. Mở lại PowerShell và kiểm tra:

```powershell
javac -version
java -version
```

Nếu PATH đang trỏ tới JRE cũ, đặt `JAVA_HOME` tới **thư mục JDK, không phải thư mục bin**, trước khi khởi động server:

```powershell
# Thay đường dẫn dưới đây bằng thư mục JDK thực tế trên máy bạn.
$env:JAVA_HOME = 'C:\Program Files\Eclipse Adoptium\jdk-21.0.8.9-hotspot'
.\.venv\Scripts\python.exe run.py
```

Backend ưu tiên một cặp `java`/`javac` trong cùng JDK: `JAVA_HOME`, `javac` trong PATH, rồi một vài vị trí cài đặt Windows thông dụng, gồm JDK đi kèm IntelliJ. `/api/health` cho biết công cụ thực tế được chọn. Ứng dụng vẫn chạy bot Python khi máy thiếu compiler; nộp C++/Java sẽ báo lỗi rõ ràng.

## Thử một trận trong giao diện

Làm theo [demo ba laptop](docs/MULTIPLAYER.md). Một laptop có thể dùng ba browser profiles/contexts độc lập để thử: một Organizer, hai Player. Organizer không dùng Quick Deploy cũ để nộp hay tự chơi. Player có thể tải/nộp mẫu nhưng phải chọn Active Bot của mình; không được chọn submission của người khác.

Robot có HP/tia tấn công; OTT có bàn cờ, nước đi/capture, số ván và điểm. Pause dừng playback, backend vẫn chạy. Reset về lượt 0 và tạm dừng; ▶ phát tiếp hoặc phát lại khi đã kết thúc. Tốc độ 0.5×–4×, ⇩ tải JSON, ↗ chia sẻ trận. Trận/replay dùng game và luật snapshot riêng; đổi game không đổi renderer lịch sử.

Đóng cuộc thi trước khi thay game/luật; chờ bot cleanup hoặc Organizer hủy trận hợp lệ. Lời mời hết hạn sau 60 giây, Decline/Cancel/Close giải phóng hai Player. Đã Accept thì Active Bot đóng băng đến khi lời mời kết thúc hoặc trận cleanup xong. Hai phía chính thức phải là hai player_id khác nhau.

## Luật Robot Battle

| Thông số | Mặc định | Khoảng cho phép |
| --- | --- | --- |
| Bản đồ vuông | 12 × 12 | 5–24 ô mỗi cạnh |
| HP ban đầu | 100 | 10–1000 |
| Sát thương | 20 | 1–500 |
| Số lượt tối đa | 100 | 1–1000 |

- Tọa độ `(0, 0)` ở góc trên trái; `x` sang phải, `y` đi xuống. A xuất phát `(1, n//2)`, B ở `(n-2, n//2)`.
- Mỗi lượt, cả hai bot nhận trạng thái trước lượt và chọn một hành động: **move**, **attack**, **wait**.
- Di chuyển được xử lý đồng thời trước. Ra ngoài bản đồ thì đứng yên. Cùng đi vào một ô hoặc đổi chỗ xuyên qua nhau thì cả hai đứng yên. Có thể đi vào ô vừa được đối thủ rời đi nếu không đổi chỗ.
- Tấn công không cần hướng. Chỉ trúng đối thủ ở ô kề trên/dưới/trái/phải **sau khi xử lý di chuyển**, tức khoảng cách Manhattan bằng 1. Tấn công từ xa là hành động hợp lệ nhưng trượt.
- Sát thương tính đồng thời. Cả hai chết cùng lượt: hòa; một robot hết HP: robot còn lại thắng. HP không xuống dưới 0.
- Hết lượt: robot có HP cao hơn thắng, HP bằng nhau thì hòa.
- Timeout/crash/JSON lỗi/hành động không hợp lệ: bot lỗi bị xử thua ngay. Cả hai lỗi cùng lượt: hòa. Replay lưu lý do và event lỗi.

Bot Python tấn công liên tục; C++ nghỉ một lượt trong bốn; Java nghỉ một lượt trong năm. Các chiến thuật mẫu nhường đường ở khoảng cách 2 để tránh cùng lao vào một ô rồi bị chặn liên tục. Đây là điểm dễ mở rộng khi nhóm viết thuật toán riêng.

## Luật OTT v2

Logic được tái triển khai trên Python từ [repository OTT v2](https://github.com/hungdo2006/ottv2-playhtml), đọc cả các file `js/rules.js`, `js/state.js`, `js/constants.js`, `js/ui.js` và các module `src/engine` mà chúng chuyển tiếp tới. Giữ cấu hình **standard-9x9**: 9 quân mỗi bên, 3 Búa/3 Bao/3 Kéo; đội hình, hai góc đích và lượt đầu giống nguồn.

- **A = P1**, **B = P2**. A đi trước; hai bot đi luân phiên. Core chỉ gửi observation cho bot đang đến lượt.
- Tọa độ `row`, `col` từ 0 đến 8. **Row 0 ở dưới cùng**; cột a–i, hàng 1–9 như nguồn. A nhắm **i9 `(8,8)`**, B nhắm **a1 `(0,0)`**.
- Mỗi nước đi một ô theo 8 hướng. Không nhảy ô hoặc đứng yên.
- Búa (`rock`) ăn Kéo (`scissors`); Kéo ăn Bao (`paper`); Bao ăn Búa. Quân cùng đội hoặc cùng loại cản nhau; không được bước vào quân mạnh hơn.
- Thắng khi đến góc đích hoặc ăn hết **một loại** quân đối thủ. Xét góc đích trước, rồi điều kiện loại quân như nguồn.
- Bàn 9×9, đội hình, luật ăn và hướng di chuyển là luật cố định. UI không cung cấp các điều khiển mà engine chưa hỗ trợ; backend cũng từ chối chúng.

Các mở rộng cho bot tournament:

| Cấu hình | Mặc định | Khoảng | Tác dụng thực tế |
| --- | --- | --- | --- |
| `max_turns` | 100 | 1–500 | Số nước của cả hai bot trong một ván; chạm giới hạn thì hòa ván |
| `rounds` | 1 | 1–5 | Chơi đủ số ván; thắng 1 điểm, hòa 0 điểm; cuối trận so điểm |

Không còn nước hợp lệ: hòa ván, để trận tự động không treo. Đây và giới hạn lượt/hòa là **mở rộng tournament**, không gán cho luật thắng nguyên bản. Khi chuyển ván, server phát một frame `round_start`, đặt lại bàn/A đi trước, giữ điểm và giữ nguyên subprocess bot. `turn` là sequence toàn trận, `round_turn` là số nước trong ván. Replay giữ cả ván thắng, ván mới và điểm.

## Giao thức bot v1: JSON Lines trên stdin/stdout

Một bot là một chương trình console **chạy liên tục suốt trận**, đọc stdin tới EOF. Mỗi request nhận đúng **một JSON object trên một dòng UTF-8**, trả đúng **một hành động JSON trên một dòng**, kết thúc bằng newline và **flush**. Robot hỏi hai bot cùng lượt; OTT chỉ hỏi bot đến lượt. Server không khởi chạy lại bot mỗi lượt/ván. Runner giữ UTF-8 cho Python trên Windows.

Ví dụ trạng thái gửi tới bot A trước lượt đầu:

```json
{"protocol":1,"game_id":"robot_battle","game":"robot_battle","player":"A","turn":0,"rules":{"map_size":12,"initial_hp":100,"damage":20,"max_turns":100},"you":{"x":1,"y":6,"hp":100},"enemy":{"x":10,"y":6,"hp":100}}
```

Ba dạng hành động hợp lệ:

```json
{"type":"move","direction":"right"}
{"type":"attack"}
{"type":"wait"}
```

`direction` chỉ nhận `up`, `down`, `left`, `right`. Trường thiếu, trường thừa, kiểu dữ liệu sai và action lạ đều không hợp lệ. Không ghi log, banner hay thông tin debug vào stdout; dùng **stderr**. Không gọi input với lời nhắc hoặc in nhiều hành động trước cho các lượt tương lai.

| Ngôn ngữ | Yêu cầu | Flush |
| --- | --- | --- |
| Python | Đọc từng dòng bằng `for line in sys.stdin`, parse bằng `json.loads` | `print(..., flush=True)` |
| C++17 | Có `int main()`, đọc bằng `std::getline(std::cin, line)` | `std::endl` hoặc `std::flush` |
| Java | `public class Main`, có `public static void main`, không khai báo package | `System.out.flush()` |

Python được kiểm tra cú pháp bằng `py_compile`. C++ và Java biên dịch **một lần cho mỗi lần nộp**; executable/class file lưu trong `uploads/<id>/`. Các trận dùng lại kết quả đó. Java source được lưu thành `Main.java` bất kể tên file tải lên. Bot mẫu C++/Java dùng bộ đọc trường nhỏ cho schema cố định của giao thức, không phải parser JSON tổng quát.

OTT observation có `protocol`, `game_id`, `game`, `player`, `turn`, `round`, `round_turn`, `current_player`, `rules`, `board_size`, `board`, `goals`, `counts`, `scores`, `last_move`, `legal_actions`. Board là ma trận null hoặc `{id, owner, type}`; owner A/B, type rock/paper/scissors. `legal_actions` giúp viết bot mẫu không cần tự tái triển khai luật, nhưng server vẫn xác thực mọi nước trả về. Bot được phép tự tính action thay vì dùng danh sách này. Ví dụ:

```json
{"action":"move","from":{"row":1,"col":3},"to":{"row":2,"col":4}}
```

Không có attack/wait trong OTT; không được gửi board/winner/score. Tham khảo **`samples/ott_v2/`**, [tài liệu protocol](docs/ADAPTERS.md) hoặc `/static/protocol.html` trên server. Các bản observation là bản sao; bot không được sửa state server qua action.

## Cấu trúc

```text
LTM/
├── backend/
│   ├── main.py           # FastAPI REST, upload, static frontend, WebSocket
│   ├── models.py         # Kiểm tra thông số và request
│   ├── matches.py        # Vòng lặp trận, gọi bot, phát trạng thái
│   ├── competition.py    # Một cuộc thi, admission lock và broadcast state
│   ├── lobby.py          # Presence, Active Bot, invitation và auto match
│   ├── runner.py         # Toolchain, compile, subprocess, IO giới hạn
│   ├── storage.py        # JSON atomic + khóa thread
│   └── engine/
│       ├── base.py       # Interface GameAdapter; robot engine cũ được bọc lại
│       ├── robot.py      # Luật Robot Battle độc lập HTTP/subprocess
│       ├── ott.py        # OTT v2 9×9, lượt, capture, nhiều ván
│       ├── registry.py   # GameRegistry
│       └── __init__.py   # Điểm đăng ký game đã cài đặt
├── frontend/             # HTML/CSS/app.js/renderers.js/protocol.html
├── samples/              # Robot bot mẫu + ott_v2/ cho 3 ngôn ngữ
├── tests/                # Luật game, runner, API + WebSocket + replay
├── scripts/
│   ├── demo_match.py     # Kiểm chứng trận đa ngôn ngữ qua HTTP/WS thật
│   ├── check_lan.py      # Organizer + hai Player upload/invite/WS/reconnect
│   ├── check_multiplayer_ui.py # Ba Chrome contexts, server/data QA tạm
│   ├── check_multiplayer_network.py # Sáu cặp ngôn ngữ, HTTP/WS LAN thật
│   ├── check_multiclient_ui.py # Chrome: hai người chơi dùng giao diện thật
│   └── check_ui.py       # QA tùy chọn với Chrome/Playwright
├── docs/                 # Ghi nhận kiểm chứng và ảnh giao diện
├── deploy/               # Mẫu Nginx HTTPS/WSS cho chế độ chỉ xem
├── data/                 # Tự tạo: bots/matches/rules/sessions/players/invitations.json, replays/
├── uploads/              # Tự tạo: source và executable/class của submission
├── requirements.txt
├── requirements-dev.txt
├── run.py
└── start.bat
```

`data/`, `uploads/` và `.venv/` không đưa vào Git. Khi chuyển source sang máy khác, cài compiler và **nộp lại bot**; executable và các đường dẫn runtime đã lưu không đảm bảo dùng được ở máy mới.

Tournament Core (`backend/matches.py`) chỉ dùng `GameAdapter`: `get_metadata`, `get_rules_schema`, `validate_rules`, `create_initial_state`, `get_observation`, `validate_action`, `apply_action`, `is_game_over`, `get_result`, `serialize_state`. `get_players_to_act` quyết định cần hỏi A/B/cả hai/không bot trong pha tự động; `forfeit` dùng chung cho lỗi bot. Core, DTO request và store không chứa luật Robot/OTT.

Muốn thêm game: triển khai adapter, đăng ký trong `create_registry()` ở `backend/engine/__init__.py`, thêm bot mẫu/tài liệu và renderer nếu cần hình ảnh riêng. Rules UI đọc JSON Schema của adapter, không cần hardcode thêm các trường luật. Có renderer JSON chung cho game mới. **Không sửa Tournament Core**; test `CounterAdapter` đã chứng minh game thứ ba tạo trận, chạy bot và hoàn thành qua cùng API/WS. Xem [hướng dẫn adapter](docs/ADAPTERS.md).

Storage tự nâng dữ liệu v1: bot cũ gắn game đã cài đầu tiên (Robot trong registry chuẩn), luật phẳng đổi thành cấu hình riêng cho từng game, giữ ID submission và replay cũ. Trận mới lưu `game_id`, tên/phiên bản game và snapshot luật. Frame cũ chưa có `game_id` dùng game từ metadata trận để chọn renderer.

## API và luồng mạng

| Method | Endpoint | Công dụng |
| --- | --- | --- |
| GET | `/api/health` | Trạng thái, toolchain, protocol, read_only |
| GET / PUT | `/api/session` | Cookie phiên / đổi nickname `{name}` |
| POST / DELETE | `/api/session/organizer` | Xác minh `{code}` bằng backend / trả phiên về Player |
| GET | `/api/players` / `/api/players/me` | Roster / trạng thái Player của cookie hiện tại |
| PUT | `/api/players/active-bot` | `{bot_id}`, chỉ Player, kiểm tra owner/game/ready/frozen |
| GET / POST | `/api/invitations` | Player chỉ đọc lời mời của mình; Organizer đọc/gửi `{player_a_id,player_b_id}` |
| POST | `/api/invitations/{id}/accept` / `decline` | Player được mời; không nhận player_id; accept idempotent |
| POST | `/api/invitations/{id}/cancel` | Chỉ Organizer; chỉ lời mời chưa bắt đầu |
| GET | `/api/network` | Origin hiện tại, mode, URL IPv4 LAN gợi ý |
| GET | `/lan` | Trang hướng dẫn LAN/firewall/HTTPS |
| GET | `/api/games` | Registry: metadata, schema, luật đã lưu, preview thật và game đang chọn |
| PUT | `/api/games/selected` | Organizer chọn game tổ chức `{game_id}`, chỉ khi SETUP |
| GET | `/api/competition` | State đầy đủ: game, khóa, snapshot, phase, pending_matches |
| POST | `/api/competition/open` | Organizer khóa game và luật đã lưu, mở nhận trận |
| POST | `/api/competition/close` | Organizer chặn trận mới, chờ các task trước khi cho cấu hình |
| WS | `/ws/competition` | State cuộc thi + lobby theo người nhận; client gửi heartbeat |
| GET | `/api/games/{game_id}` | Thông tin đầy đủ của một game |
| GET / PUT | `/api/games/{game_id}/rules` | Mọi người đọc; Organizer lưu chỉ khi SETUP |
| POST | `/api/games/{game_id}/rules/reset` | Organizer reset chỉ khi SETUP |
| GET / PUT | `/api/rules` | Alias luật của game đang tổ chức; PUT cần Organizer và SETUP |
| GET / POST | `/api/bots` | Danh sách / Player nộp multipart `file`, `name`, `game_id`; Organizer bị chặn |
| GET | `/api/bots?game_id=ott_v2` | Lọc submission theo game |
| GET / POST | `/api/games/{game_id}/samples/{language}` / `.../submit` | Tải/nộp mẫu của game, language python/cpp/java |
| GET | `/api/samples/{python\|cpp\|java}` | Tải source bot mẫu |
| POST | `/api/samples/{language}/submit` | Nộp bot mẫu có sẵn |
| GET | `/api/matches` | Lịch sử chung; POST cũ luôn trả 403, không bỏ qua invitation |
| POST | `/api/matches/{id}/cancel` | Organizer hủy task đang chạy/chờ; thu hồi bot, giữ replay/history |
| GET | `/api/matches/{id}` | Metadata, luật, trạng thái, kết quả |
| GET | `/api/matches/{id}/replay` | Metadata + mảng `frames` JSON |
| WS | `/ws/matches/{id}?after=-1` | Subscribe từ sequence kế tiếp |

POST submission trả `201`, gồm ready/error và compiler logs; source lỗi vẫn lưu để xem. `403` khi thiếu quyền; `409` khi chưa mở, sai game khóa, sửa cấu hình khóa/còn task, hoặc override snapshot. Active Bot/ghép cặp không tương thích hoặc Player bận/offline trả `409`; thiếu/sai schema `422`; ID không có `404`. Swagger ở `/docs`.

```text
Browser -- HTTP upload --> FastAPI -- compiler --> uploads/<id>
Organizer -- HTTP invite --> Lobby
Players -- HTTP accept (both) --> MatchManager
                             | JSON Lines stdin/stdout
                             +-- subprocess bot A
                             +-- subprocess bot B
                             | hành động
                             v
                          GameEngine --> lưu JSON replay từng lượt
                             |
Browser Canvas <--------- WebSocket state
Browser Replay <--------- HTTP đọc JSON đã lưu
```

WebSocket gửi `hello` (metadata), `state` (`seq`, `state`), `complete` (kết quả); `ping` khi chờ lâu. `seq=0` là trạng thái ban đầu. Kết nối lại với `after=<seq cuối>` nhận các trạng thái còn thiếu. UI tự reconnect và lấy lại replay khi mất kết nối. Pause không gửi lệnh dừng backend.

Giao thức lobby, các trạng thái lời mời, snapshot participants và reconnect được mô tả trong [MULTIPLAYER.md](docs/MULTIPLAYER.md). Các lệnh QA cũ `check_ui.py` / `check_multiclient_ui.py` chuyển sang checker ba browser v3; dùng server QA riêng vì chúng thay cấu hình và nộp bot thật.

## Giới hạn và xử lý lỗi

| Giới hạn | Giá trị |
| --- | --- |
| Source submission | 256 KiB |
| Thời gian compiler | 30 giây |
| Compiler diagnostics | 32 KiB |
| Lượt đầu (gồm startup, JDK warm-up) | 3 giây |
| Các lượt sau | 1 giây / bot |
| stdout | 4 KiB / dòng, 256 KiB / bot / trận |
| stderr | 64 KiB / bot / trận |
| Trận đồng thời | 2 |
| Java heap | `-Xmx64m` |

stdin được ghi bằng thread riêng; stdout/stderr được đọc liên tục bằng thread với buffer giới hạn. Vì vậy bot không đọc stdin hoặc spam stderr không khóa vòng lặp HTTP/WebSocket. Hai bot tính hành động song song bằng thread; engine xử lý khi cả hai trả kết quả. Kết thúc trận, lỗi hoặc shutdown sẽ thu hồi hai tiến trình bot trực tiếp. Không bảo đảm thu hồi tiến trình con do bot tự tạo; bot nhóm phải tránh tạo subprocess khác.

Trên Windows, runner gọi trực tiếp interpreter nền của `.venv` và giữ môi trường bằng `__PYVENV_LAUNCHER__`, theo [cách CPython khởi tạo process](https://github.com/python/cpython/blob/main/Lib/multiprocessing/popen_spawn_win32.py). Điều này tránh dừng nhầm launcher trung gian khi bot timeout; có test xác nhận PID được quản lý là PID thực của bot và `sys.prefix` vẫn là `.venv`.

Metadata JSON được thay thế atomic. Replay mới ở `data/replays/ID.jsonl`: trạng thái ban đầu và mỗi frame mới ghi một dòng JSON, không ghi lại lịch sử mỗi lượt; lượng ghi replay tăng tuyến tính theo tổng kích thước các frame. Record được ghi trước khi phát qua WebSocket. Dòng cuối thiếu newline do process dừng giữa chừng được bỏ qua, giữ các frame đã ghi đầy đủ. Replay `.json` cũ vẫn đọc được, không bị chuyển/xóa; API và nút tải JSON vẫn trả `{match,version:1,frames}` như trước.

Khi khởi động lại server, trận đang chạy được đánh dấu `interrupted` và vẫn xem được phần replay đã ghi. File close flush vào OS, không hứa chịu được mất điện/ổ đĩa hỏng. Mọi frame live vẫn giữ trong RAM và API đọc toàn bộ replay theo yêu cầu; chưa có streaming/pagination để giữ demo đơn giản. **Không chạy nhiều Uvicorn workers** dùng chung thư mục dữ liệu.

Không có sandbox filesystem/network, không giới hạn RAM/CPU tổng quát cho Python/C++, không có đăng nhập hoặc hạ tầng phục vụ người dùng không tin cậy. Bind `0.0.0.0` để demo trong LAN riêng; không tunnel, port-forward hoặc công khai runner lên Internet. HTTP/WS dùng cùng origin, mặc định chỉ chấp nhận host local/IP riêng, không mở CORS wildcard. Public domain cấu hình riêng bắt buộc chế độ chỉ xem. Host/Origin guard và cookie không thay thế sandbox hay firewall.

## Kiểm thử

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest
```

Test compiler C++/Java tự skip nếu công cụ không có; các test khác vẫn chạy. Test dùng thư mục tạm riêng, không sửa bot/luật/lịch sử của ứng dụng. Bộ test kiểm tra va chạm, di chuyển, sát thương đồng thời, hòa, giới hạn lượt, invalid action, timeout, crash, JSON lỗi, giới hạn output, lỗi cú pháp, WebSocket, luật thực tế và replay đọc lại từ đĩa.

Khi server đang chạy, thử trận **qua HTTP và WebSocket thật**:

```powershell
.\.venv\Scripts\python.exe scripts/demo_match.py --game robot_battle --a python --b cpp
.\.venv\Scripts\python.exe scripts/demo_match.py --game robot_battle --a cpp --b java
.\.venv\Scripts\python.exe scripts/demo_match.py --game ott_v2 --a python --b cpp --rounds 2
```

Các lệnh không cấu hình cần cuộc thi tương ứng đã mở. Dùng `--open-competition`, `--max-turns` hoặc `--rounds` để script xác minh Organizer bằng ARENA_ADMIN_CODE, đóng → chọn/lưu luật → khóa mở trước demo; không gửi per-match override nữa. Nếu còn trận chạy thì không đổi cấu hình. Script tạo Organizer và hai Player mô phỏng, thực hiện invitation/Accept, so ba stream với replay. Luôn cần ARENA_ADMIN_CODE để gửi lời mời, kể cả cuộc thi đã OPEN.

Kiểm thử gồm cả hai game, adapter thứ ba, hiệu lực cấu hình, snapshot/replay, nộp bot theo game, các trận khác ngôn ngữ và hai spectator. Có test đối chiếu engine Python với module luật JavaScript đã lưu từ repository OTT. Node chỉ dùng cho test đối chiếu; không cần để chạy ứng dụng. Xem [báo cáo v2 cùng ảnh giao diện](docs/MULTIGAME_VERIFICATION.md); [báo cáo v1](docs/VERIFICATION.md) được giữ làm lịch sử.

QA giao diện tùy chọn, cần Chrome đã cài:

```powershell
.\.venv\Scripts\python.exe -m pip install playwright
.\.venv\Scripts\python.exe scripts/check_multiplayer_ui.py --lan-ip IP-HOST
.\.venv\Scripts\python.exe scripts/check_multiplayer_network.py --lan-ip IP-HOST
```

Không cần `playwright install`: dùng Chrome có sẵn/headless. Hai checker mặc định dùng server/data tạm riêng và tự dừng, giữ dữ liệu dự án. `check_multiplayer_ui.py --url http://IP:PORT` (và alias cũ check_ui/check_multiclient_ui) dùng server QA do bạn chạy với ARENA_ADMIN_CODE; chúng chỉnh cấu hình/nộp bot thật, không tự khôi phục cấu hình. Checker network chạy sáu cặp PY/C++/Java trên hai game và thêm kịch bản upload/LAN/reconnect.

## Gợi ý thuyết trình 5 phút

1. Giới thiệu REST cho upload/cấu hình/invitation/Accept, WebSocket cho presence/lobby và trạng thái game.
2. Hai Player nộp bot và chọn Active Bot; chỉ ra compile một lần và JSON stdin/stdout thống nhất.
3. Organizer gửi invitation, hai Player Accept; cả ba tự xem Python vs C++, Pause chứng minh playback độc lập.
4. Chỉnh sát thương hoặc số lượt, chạy trận mới để minh họa engine dùng luật thực tế.
5. Chọn OTT v2 để thấy form/board/action đổi theo registry; mở cùng trận trên máy LAN thứ hai, rồi replay. Giới thiệu adapter và giới hạn subprocess.

## Khắc phục nhanh

- **Thiếu g++/javac:** kiểm tra `Get-Command g++,javac,java`, `JAVA_HOME`, PATH rồi khởi động lại server; nộp lại submission đã lỗi.
- **Java lỗi public class:** dùng `public class Main`, không có `package`; xem `samples/Main.java`.
- **Bot timeout:** bỏ prompt stdout, trả một dòng JSON + newline và flush; không chờ input bổ sung trong cùng lượt.
- **Bot bị chặn mãi:** hai bot cùng đi vào ô giữa thì bị chặn; viết chiến thuật nhường lượt hoặc chọn hướng khác.
- **Port 8000 đã dùng:** dừng server đang chạy hoặc dùng `.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8001`, rồi mở URL tương ứng; frontend dùng cùng origin nên tự theo port.
- **Không có cập nhật Canvas:** kiểm tra server còn chạy và Console của browser; reload trang, chọn lại trận trong lịch sử.
- **Đổi vị trí project/máy:** giữ source, cài môi trường và nộp lại bot thay vì mang executable cũ sang.

Tham khảo kỹ thuật: [FastAPI WebSocket](https://fastapi.tiangolo.com/advanced/websockets/), [FastAPI UploadFile](https://fastapi.tiangolo.com/tutorial/request-files/), [Python subprocess](https://docs.python.org/3/library/subprocess.html).
