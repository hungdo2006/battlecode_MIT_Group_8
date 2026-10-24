# NEON ARENA — Nghiệm thu Giai đoạn A

**Kết luận: BLOCKED — chưa đủ điều kiện merge hoặc deploy.** Kiểm thử phần mềm native và browser đã thực hiện; Docker Engine không hoạt động, chưa có staging online độc lập và chưa kiểm chứng LAN cách ly thực tế. Không dùng kết quả unit/fixture để chứng nhận các release gate này.

Ngày kiểm thử: **23/10/2026, Asia/Saigon (UTC+07)**. Repository: `hungdo2006/battlecode_MIT_Group_8`, [PR #24](https://github.com/hungdo2006/battlecode_MIT_Group_8/pull/24), nhánh `feature/offline-results-portability-20261023`.

| Phiên bản | SHA / bằng chứng |
| --- | --- |
| PR head khi bắt đầu | `839afa6ed917d9fc59a1a0e85298710025a36248` |
| Sửa portability, UI và regression | [`ca2acb3e48fe17167366d60145989ccfdc579b91`](https://github.com/hungdo2006/battlecode_MIT_Group_8/commit/ca2acb3e48fe17167366d60145989ccfdc579b91) |
| Chặn signing key trong bot/compiler native | [`fbb33b1e2db4c558f6b817b30fbfd7e99e0a8b0b`](https://github.com/hungdo2006/battlecode_MIT_Group_8/commit/fbb33b1e2db4c558f6b817b30fbfd7e99e0a8b0b) |
| Runtime head cuối được nghiệm thu | [`060a412e09ea4be5d45fbde37a3ca30c62dd31c7`](https://github.com/hungdo2006/battlecode_MIT_Group_8/commit/060a412e09ea4be5d45fbde37a3ca30c62dd31c7) — sửa kiểu điểm Buchholz Swiss |
| CI của runtime head cuối | [GitHub Actions 39988981149](https://github.com/hungdo2006/battlecode_MIT_Group_8/actions/runs/39988981149) — xem trạng thái cuối trong `ci.json` |
| PR merge ref mà Actions checkout ở lượt cuối | `0c4183b6db84390de46034b3c97d9488ee4dd553` (`060a412` vào base `2f1cdd92251d986dca44c28a331c8edc4a280d3a`) |
| Commit chứa báo cáo | Commit chứa file này; chỉ bổ sung báo cáo và bằng chứng, không thay đổi runtime so với SHA sửa lỗi ở trên |

## Môi trường và giới hạn an toàn

- Checkout riêng: `D:\LTM\.qa-phase-a-20261023\repo`; working tree ban đầu ở `D:\LTM` trên `main` không được đổi nhánh, sửa dữ liệu hay đưa vào commit.
- Windows 11 `10.0.26300`, Python 3.13.12, Node 24.21.0, SQLite 3.51.1, GCC 13.2.0, javac 21.0.8 (JDK được runner tự tìm tại IntelliJ JBR); Chrome 157.0.8103.15 / Playwright 1.63.0. Dependency versions chi tiết: [environment.json](docs/qa/phase-a-20261023/environment.json).
- Dùng interpreter/dependency đã cài ở virtualenv cục bộ; `pip check` PASS. Tất cả app được test nhận `base_dir` tạm riêng; không đọc `.env` hoặc data/uploads của working tree ban đầu. Native suite chủ động dùng runner legacy; Controller unit tests dùng test doubles.
- Browser server bind `127.0.0.1`, port ngẫu nhiên, tài khoản Admin/Player giả. HTTP được phép **chỉ trong harness localhost**, không đổi cấu hình HTTPS của public/Exam.
- Test portability dùng hai app stores với SQLite/writer lock riêng. Đích đã có Admin, Player, Team và Tournament giả; so sánh nguyên vẹn các hàng users/teams/tournaments/Official trước/sau import. Đây là kiểm thử integration native, **không phải staging online độc lập**.
- Docker CLI 29.8.2, Compose 5.6.0. Dùng Docker config QA riêng để tìm Compose plugin, không dùng credential Docker cá nhân. Cả `docker_engine` và `dockerDesktopLinuxEngine` đều không có named pipe; kiểm tra chỉ đọc ngoài sandbox cũng xác nhận điều này.
- Hai checker Docker đã được gọi bằng namespace/project QA ngẫu nhiên (`neon-arena-qa-369bbbc818` cho lần chạy build cuối). Dừng tại kết nối daemon; không tạo image/container/volume. Cleanup cũng không kết nối được daemon. Không xóa volume nào, không thao tác với project đang sử dụng.
- Không SSH, truy cập/cập nhật AWS, sử dụng dữ liệu thật, push `main`, merge PR hoặc sửa giới hạn bảo mật. Giới hạn hai trận và cấu hình isolation của Sandbox được giữ nguyên.
- Bộ browser layout/retest cũ có ngân sách request riêng cho harness; không thay đổi các giá trị đó trong lần QA này. Kết quả của chúng không chứng nhận khả năng chịu tải với rate limit production.

## Tài liệu và mã nguồn đã đọc trước kiểm thử

README; `docs/EXAM_MODE.md`, `docs/OFFLINE_RESULTS_TRANSFER.md`, `docs/QA.md`, `docs/OPERATIONS.md`; workflow CI và requirements. Đã đối chiếu thêm các phần liên quan: `backend/offline_results.py`, `team_tournament_http.py`, `team_tournament_service.py`, `official_service.py`, `official_dispatcher.py`, `auth_http.py`, `storage.py`, `sandbox_controller/engine.py`, `frontend/results.html`, các handler import/export trong `frontend/app.js`, `compose.yaml`, `compose.exam.yaml`, `deploy/Caddyfile.exam`, checker Docker/lifecycle và snapshot/backup/restore.

## Phát hiện và sửa lỗi

| ID | Trước sửa | Thay đổi và regression | Trạng thái |
| --- | --- | --- | --- |
| A-01 | Double Elimination hoàn tất khi đội nhánh thắng thắng grand final: reset được lưu nội bộ là BYE/SKIPPED, có winner nhưng chưa có hai participant; export trả HTTP 422 `Đội thắng không thuộc cặp đấu.` | Project reset không thi đấu thành `SKIPPED`, không gán participant/winner giả. Chặn bracket còn PENDING, kể cả payload được ký hợp lệ. Không nới kiểm tra winner thuộc cặp đấu. Test tạo giải 2 Team, schedule Official và gọi chính logic advancement với terminal rows **synthetic**; sau sửa export/import PASS. | FIXED |
| A-02 | `/results` bỏ qua bracket đã nhập; giải phân thắng thua bởi Admin chỉ hiện kết quả trận hòa, không thấy quyết định nhánh đấu | Hiện nhánh đấu, đội thắng, BYE và reset SKIPPED; giữ lịch sử kết quả trận riêng. Node functional check chạy JS thực, kiểm tra draw + adjudicated winner và tên dạng HTML được render bằng text. Browser localhost kiểm chứng giao diện. | FIXED |
| A-03 | Hai browser checker cũ tìm form Scrimmage không còn tồn tại và text trạng thái `ready` đã Việt hóa | Đối chiếu UI hiện tại: kiểm tra hướng dẫn tạo/tham gia Team, không có nút đối thủ khả dụng khi thiếu Team, và trạng thái `Sẵn sàng`. Không sửa product hay limit để làm test PASS. | FIXED |
| A-04 | Runner native còn kế thừa `ARENA_OFFLINE_RESULTS_KEY` vào process bot/compiler; test bot xác nhận biến này tồn tại | Loại signing key khỏi môi trường con dùng chung bởi compiler và bot. Regression chạy process bot thật, chỉ quan sát boolean, không in key. Khóa test sinh ngẫu nhiên trong memory. Sandbox Engine vốn dùng environment allowlist riêng. | FIXED |
| A-05 | CI Windows ở commit `ca2acb3` FAIL 1 ca Lobby khi compile C++ vượt 30 giây; 583 ca còn lại PASS | Không tăng timeout, thêm retry vào test, bỏ language hay skip ca lỗi. Chạy lại toàn bộ CI trên runtime head cuối; giữ lịch sử failure và rủi ro hosted-compiler timing trong báo cáo dù lượt sau có xanh. Chưa xác định nguyên nhân hạ tầng. | FAIL gián đoạn / rủi ro chưa đóng |
| A-06 | `_swiss_standings` tính Buchholz bằng chia hai (float), nhưng offline schema coi đó là integer counter, khiến export Swiss bị từ chối | Phân loại Buchholz là điểm số như `points`; giữ yêu cầu finite/nonnegative và từ chối bool/string. Thêm 1 roundtrip score test và 4 negative cases. Không thay đổi giới hạn Sandbox, request hoặc compiler. | FIXED |

Regression cho A-01 tái hiện lỗi trước sửa tại [reproduction.txt](docs/qa/phase-a-20261023/reproduction.txt). Source regression: [test_offline_results_http.py](tests/test_offline_results_http.py), [test_offline_results.py](tests/test_offline_results.py), [test_public_results_rendering.py](tests/test_public_results_rendering.py).

Provenance: native/browser portability đã chạy trên `ca2acb3` (584 local PASS); sau A-04 toàn bộ local `fbb33b1` có 585 PASS. Sau A-06 nhóm runner/offline/frontend có 41 PASS và chạy lại toàn bộ ở `060a412`. Screenshots được chụp ở `ca2acb3`; frontend không đổi trong hai commit sau.

## Ma trận nghiệm thu

PASS chỉ áp dụng cho phạm vi ghi trong từng dòng. FAIL là lỗi đã quan sát; các lỗi ở trên đã được sửa và kiểm tra lại. SKIP là ngoài phạm vi v1/engine tùy chọn. BLOCKED là thiếu hạ tầng để thực hiện, không được xem là PASS.

| Hạng mục | Kết quả | Bằng chứng / phạm vi thực tế |
| --- | --- | --- |
| Python + Controller toàn bộ tại baseline | PASS | 578 tests, 0 failed/skipped, 1 Starlette/httpx deprecation warning; [baseline.txt](docs/qa/phase-a-20261023/baseline.txt) |
| Python + Controller toàn bộ sau sửa cuối | PASS | 590 tests, 0 failed/skipped; [pytest.xml](docs/qa/phase-a-20261023/pytest.xml), [regression.txt](docs/qa/phase-a-20261023/regression.txt) |
| CI Windows + Ubuntu của SHA sửa lỗi cuối | PASS | Mỗi OS 590 PASS / 0 failed/skipped, 1 warning; [ci.json](docs/qa/phase-a-20261023/ci.json). Giữ failure Windows ở lần trước trong lịch sử, không coi risk timing đã đóng |
| Frontend validation | PASS | Năm file JS syntax, routing/CSRF checker, asset fingerprints, public-results functional rendering, `git diff --check`; [verification.txt](docs/qa/phase-a-20261023/verification.txt) |
| Admin/Player signup, login, logout, session restore/revocation | PASS (native) | Account browser checker và HTTP/auth regression; tài khoản giả, không SMTP/MFA/TLS vật lý |
| Team Management: tạo/kích hoạt, Captain/member, invite/join, bot/Active Bot | PASS (native) | Browser layout 120 tổ hợp role/view/width; upload/sample Python compile native; regression ownership/IDOR/capacity/archive. [workspace-measurements.json](docs/qa/phase-a-20261023/workspace-measurements.json) |
| Tournament creation, round rules, Official scheduling | PASS (native/API) | Schedule thực vào SQLite, bot lock/round rules/visibility regression; browser schedule đặt trong tương lai |
| Compile và Official chạy Docker thật, hoàn tất giải tại offline host | **BLOCKED** | Không có Engine; terminal Official trong test export là synthetic, không phải kết quả Sandbox |
| Scrimmage hồi quy | PASS (unit/native UI); **BLOCKED** (Docker) | Team eligibility, quyền truy cập, queue/dispatcher hồi quy; chưa thực thi Docker Scrimmage khi logout trong lượt này |
| Replay hồi quy | PASS (native/fixture); **BLOCKED** (Docker) | Legacy native regression + browser retest R01–R12: điều hướng/reload/deep link/focus/slider và chống late response; không chứng nhận replay của trận Docker mới |
| Export HMAC-SHA256, allowlist dữ liệu công khai | PASS (unit/API) | Từ completed Tournament/Official SQLite synthetic; loại Team UUID, source/artifact, private match/replay IDs; incomplete event và unresolved bracket bị từ chối |
| Preview trước publish | PASS (API/browser localhost) | Chưa tạo archive sau preview; public API vẫn rỗng; chọn file khác vô hiệu nút confirm; [verified-preview.png](docs/qa/phase-a-20261023/verified-preview.png) |
| Import vào online staging trên host độc lập | **BLOCKED** | Chưa có deployment staging online riêng được cấu hình/khả dụng; hai app stores native không thay thế gate này |
| Chữ ký sai/key sai/missing key, file bị sửa, payload sai schema | PASS (unit/API) | Nhóm offline tests + browser tamper rejection; khóa browser ngẫu nhiên chỉ nằm trong bộ nhớ, không đưa vào bằng chứng |
| Signing key không truyền vào bot/compiler | PASS (process regression) | Native bot thật xác nhận biến không tồn tại; kiểm tra môi trường compiler từ cùng launch helper; không đổi deadline compile 30 giây |
| CSRF, quyền Admin/Player, xác nhận công bố | PASS (HTTP boundary) | Missing CSRF 403, non-admin/anonymous bị từ chối; thiếu xác nhận 422; auth/origin/IDOR suite cũng PASS |
| Nhập trùng / nhập xung đột | PASS (API/browser) | Nhập lại báo already-imported, số publication không tăng; signed conflict 422, kết quả gốc không đổi |
| `/results`, scoreboard, lịch sử trận và bracket | PASS (API/browser synthetic) | Anonymous GET, bảng điểm qua HTTP regression; bracket/adjudicated winner/history trên desktop 1440 và mobile 390; [desktop](docs/qa/phase-a-20261023/public-results-desktop.png), [mobile](docs/qa/phase-a-20261023/public-results-mobile.png) |
| Bảo toàn dữ liệu online | PASS (native integration) | Hai SQLite/store độc lập; users/teams/tournament/Official rows không đổi; archive chỉ ở đích |
| Restart/persistence | PASS (native app lifespan); **BLOCKED** (container/host) | Đóng writer, mở app mới cùng data; public payload và archive SHA256 giữ nguyên; chưa reboot/power-loss container/host |
| Backup/restore | PASS (cold directory + helper unit); **BLOCKED** (Docker rehearsal) | Copy chỉ sau khi writer đóng, restore vào thư mục mới; PRAGMA integrity_check = ok, publication hash/data giữ nguyên. Docker CLI helper regression dùng FakeDocker; chưa có image receipt/three-volume restore thực |
| LAN Exam Compose config và source isolation | PASS (config review) | `config -q` thành công; TLS internal, Arena ports reset, Controller không publish port, bot `network_mode=none`, seccomp/cgroups/read-only/cap-drop trong source; [docker-lan.txt](docs/qa/phase-a-20261023/docker-lan.txt) |
| TLS CA trust/DNS/TOTP offline trên client thi thật | **BLOCKED** | Không có client LAN/CA enrollment/HTTPS handshake thực; browser route mô phỏng HTTPS trong checker cũ không được tính PASS TLS |
| Cách ly WAN, IPv6/DNS/proxy/VPN/hotspot; port exposure; bot HTTP/DNS egress | **BLOCKED** | Không có VLAN/client thi/Engine để đo thực tế; không thay đổi mạng host nhằm giả lập LAN cách ly |
| Replay transfer, optional Battlecode runtime, SMTP/OAuth delivery | SKIP | Replay transfer chưa thuộc v1; Battlecode runtime tùy chọn và dịch vụ Internet ngoài phạm vi nghiệm thu Phase A này. Unit Controller/Battlecode vẫn nằm trong regression toàn bộ |

## Lệnh đã chạy và bằng chứng

PowerShell chạy ở checkout QA; `python` dưới đây là `D:\LTM\.venv\Scripts\python.exe`, đặt `PYTHONUTF8=1` và `PYTHONUNBUFFERED=1`. Không chứa giá trị credential/signing key trong các lệnh lưu báo cáo.

```text
python -m pip check
python -m pytest tests controller_tests -v -ra --tb=short --durations=20 -o faulthandler_timeout=60 --junitxml=qa-ci/pytest.xml
python -m pytest tests/test_offline_results.py tests/test_offline_results_http.py -ra --tb=short
python -m pytest tests/test_offline_results_http.py::test_independent_import_restart_and_cold_directory_restore tests/test_public_results_rendering.py -ra --tb=short
node --check frontend/app.js
node --check frontend/renderers.js
node --check frontend/ui.js
node --check frontend/protocol.js
node --check frontend/lan.js
node scripts/check_account_frontend_routing.cjs
node scripts/check_public_results_rendering.cjs
python scripts/version_frontend.py --check
python scripts/check_account_ui.py
python scripts/check_ui_ux_report.py
python scripts/check_workspace_layout.py
python scripts/check_retest_regressions.py
python scripts/check_offline_results_ui.py
git diff --check
```

Docker: đặt `DOCKER_CONFIG` đến thư mục config QA và `DOCKER_HOST=npipe:////./pipe/dockerDesktopLinuxEngine`. Chạy `docker version` cho cả hai named pipes (kể cả ngoài sandbox), `docker compose version`, `python scripts/check_docker.py --build`, `python scripts/check_sandbox_lifecycle.py`. Hai checker Docker exit 1 do không kết nối daemon. Compose lần đầu không tìm được plugin khi dùng config QA rỗng; bổ sung **chỉ đường dẫn cliPluginsExtraDirs của bản cài Docker hiện có** vào config QA, rồi chạy lại: plugin hoạt động, lỗi Engine vẫn tồn tại.

```text
docker compose --env-file .env.example -p neon-arena-qa-phase-a-config -f compose.yaml -f compose.exam.yaml config -q
```

Lệnh này PASS với domain `arena.qa.test`, bind loopback và token tạm được tạo trong process; không in Compose nội suy. Đây chỉ là parse/merge cấu hình, không start gateway hoặc chứng nhận LAN.

Bằng chứng được chọn lọc tại [docs/qa/phase-a-20261023](docs/qa/phase-a-20261023). Không commit raw trace, cookie, token, signing key, `.env`, SQLite, backup hoặc dữ liệu người dùng. Screenshot chỉ chứa tài khoản/sự kiện giả; checksums của bằng chứng nằm trong `SHA256SUMS.txt`. Text logs được chuẩn hóa LF và bỏ khoảng trắng cuối dòng; `.gitattributes` giữ bytes ổn định khi checkout trên Windows/Linux.

## CI và các gate còn lại

CI của SHA sửa lỗi được kích hoạt tự động bằng push nhánh PR, giữ nguyên workflow Windows/Ubuntu. Lượt `39986808290` ở `ca2acb3`: Ubuntu 584 PASS; Windows 583 PASS / 1 FAIL do compile sample C++ vượt 30 giây, có [job log](https://github.com/hungdo2006/battlecode_MIT_Group_8/actions/runs/39986808290/job/120527990503). Lượt `39988308393` ở `fbb33b1`: Ubuntu PASS, Windows bị workflow concurrency tự hủy khi push bản sửa Swiss; không tính là Windows PASS. Lượt cuối `39988981149` ở `060a412` **SUCCESS**: Ubuntu 590 PASS (165.82s), Windows 590 PASS (310.53s), frontend validation PASS trên cả hai OS. Kết quả được ghi cùng URL/run/job IDs trong `ci.json`; các test CI này không thực thi Docker hay browser. Một lượt xanh không chứng minh lỗi timing A-05 đã hết.

**Không phê duyệt merge/deploy Giai đoạn A** cho tới khi có đủ bằng chứng mới, gắn với đúng SHA:

1. Offline host QA có Linux Docker Engine chạy thực, đủ fake Admin/Player/Team, compile bot, Official hoàn tất giải và kiểm chứng replay; ghi image IDs và CPU/RAM, giữ cap hai trận.
2. Chuyển file xuất từ chính giải đó đến deployment online staging độc lập; preview, negatives, publish, anonymous `/results`; chứng minh dữ liệu online không đổi.
3. Restart container/host và diễn tập cold backup đủ ba volume + images/receipt; restore vào project mới `neon-arena-restore-*`, invalidate-restored-auth, kiểm chứng publication/bot/replay và một trận mới. Sao lưu Caddy data/config (CA nội bộ) và secret qua kênh riêng; helper core không bao gồm hai volume Caddy hoặc `.env`.
4. Client thi thật tin CA/DNS/clock nội bộ, đăng nhập/nộp bot/replay khi ngắt WAN; đo chặn Internet, IPv6/DNS/proxy/VPN/hotspot, host ports và bot egress. Chỉ review Compose không đóng gate này.

Rủi ro còn lại: native C++ compile có failure timing gián đoạn trên hosted Windows; chưa có số đo tải/tài nguyên hoặc power-loss durability; HMAC dùng shared secret và cần quy trình rotation giữa sự kiện; archive local phụ thuộc bảo vệ filesystem/backup. Lịch sử v1 là snapshot mỗi fixture đang được project, không phải gói toàn bộ tiebreak attempts/replay. Optional engine và email delivery không được chứng nhận bởi báo cáo này.

PR vẫn Draft/open. Không merge, không deploy, không tác động AWS.
