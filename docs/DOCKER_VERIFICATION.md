# NEON ARENA v4.0 Phase 1 — kết quả Docker thực tế

Ngày kiểm tra: **15/10/2026**. Host Windows, Docker Desktop4.95.0, Docker Engine29.8.2 Linux/amd64, Compose5.6.0. Đây là Docker hóa ứng dụng hiện có, không triển khai Docker Bot Sandbox.

## Audit và quyết định

- Không có AGENTS.md áp dụng trong repository/parent đã kiểm tra. Đã đọc README, requirements, start.bat, run.py, network, Store và runner.
- `PROJECT` là thư mục gốc source; Store lưu `PROJECT/data` và `PROJECT/uploads`. Session/players/rules/invitations/matches/bots và replays nằm trong data; source/cache/executable/classes nằm trong uploads.
- Runner đã dùng `Path`, `sys.executable`, toolchain PATH, C++17 và matching java/javac; nhánh Windows chỉ cho launcher/process flags. Không cần sửa runner, Game Adapter hoặc Tournament Core để chạy Linux.
- Một service Compose `arena`, một worker. Image application gồm Python3.13 + G++ + JDK17, user UID/GID10001. Hai named volumes đúng đường dẫn `/app/data`, `/app/uploads`, giữ command paths/artifacts qua recreate.
- Data/uploads Windows, .venv, Git, ZIP, .env và private-key files bị loại khỏi context; Dockerfile copy source có chọn lọc. Không mount Docker socket/privileged. Env code chỉ runtime.

## File thêm/sửa

| File | Nội dung |
| --- | --- |
| Dockerfile | application/runtime và target tests tùy chọn; non-root, toolchains, healthcheck, exec-form single-worker CMD |
| compose.yaml | Một service, port8000/LAN, environment .env, health kế thừa, unless-stopped, named volumes, init/grace/capabilities |
| .dockerignore / .env.example / .gitignore | Loại runtime/private data và secrets; example mã trống, Git ignore env/backups |
| deploy/healthcheck.py | Stdlib HTTP health + kiểm tra bốn đường dẫn toolchain |
| scripts/backup_docker.py | Backup tar binary-safe Windows/Linux, từ chối service running/archive trùng |
| scripts/check_docker.py | Acceptance thật bằng project/volumes QA riêng; sáu cặp bot, three WS, lifecycle/persistence/artifact reuse/backup/Chrome |
| scripts/check_multiplayer_ui.py | Thêm output_dir tùy chọn để ảnh Docker không ghi đè bộ ảnh v3; mặc định cũ giữ nguyên |
| README.md / docs/DOCKER.md | Lệnh Windows/Linux, logs, lifecycle, health, .env, storage/backup/LAN, giới hạn |
| docs/screenshots/docker/ | Ảnh Chrome thật của backend Docker: Organizer/invitation/result/mobile |

**Không sửa backend, frontend, samples, dependencies, start.bat hoặc run.py.** Không migration/xóa dữ liệu native. Không thêm database hay service ngoài `arena`; target tests và utility backup không phải service production.

## Kết quả đã chạy

| Hạng mục | Kết quả thực tế |
| --- | --- |
| Baseline Windows | `143 passed`, không skip,75.65s; một Starlette/httpx deprecation warning có sẵn |
| Compose config | `docker compose --env-file .env.example config --quiet` pass |
| Runtime build | `docker compose --env-file .env.example build arena` thành công |
| Test build | `docker build --target tests -t neon-arena:4.0-tests .` thành công |
| Toàn bộ regression Linux | `docker run --rm --init neon-arena:4.0-tests`: **143 passed**, không skip,49.71s |
| JavaScript trong Linux | `node --test docs/reference/ottv2/tests/rules.test.js`: **8/8 pass** |
| Compose mặc định | `up --build -d --wait` trong project QA, **http://localhost:8000** website và `/api/health` hoạt động |
| UID/image contents | Runtime UID10001, data/uploads ghi được; không chứa host data/.env/admin ENV/Docker socket/Node |
| Compile/run | Upload Python/C++/Java thực, cả hai game, six language pairs, không bot_error |
| Lobby/WS | Organizer-only pairing, Player không direct-start; invitation, partial accept, Decline, hai Accept auto start, ba streams bằng replay |
| Restart | Identity cookie, Active Bot, lock/rules, metadata, replay, source và compiled artifacts còn nguyên; grant Organizer bị thu hồi; pending bị cancel |
| Down/up | Ordinary down không xóa volume; container mới dùng lại cùng volume, replay/bots/settings đúng |
| Artifact reuse | Cùng submission chạy lại sau restart, không compile; hash toàn bộ source/executable/classes/bytecode không đổi |
| Backup | Tar.gz245702bytes mở đọc được, đủ metadata/replay/source/artifacts, không .env; ghi binary qua Python, không redirect PowerShell text |
| Chrome | Ba contexts/cookie riêng qua IP Wi-Fi, upload/Active Bot/Invite/popup/Accept/auto Live, hai game, Pause/reconnect/replay,390px; không JavaScript page error |

Runtime thực: Python3.13-slim-bookworm, GCC/G++ từ Debian Bookworm, JDK17 headless; image Linux/amd64, Docker báo998224371bytes. Node chỉ có ở target test. Runtime pip resolve requirements hiện có, không đổi constraints dự án. Starlette/httpx warning vẫn còn; test Node18 có experimental JSON-module warning, không có test thất bại.

## Match evidence trong Compose

Checker thành công dùng project riêng `neon-arena-qa-44b4bfba08`, publish lên host Wi-Fi `192.168.2.16`. Cổng QA cấp ngẫu nhiên, có thể thay sau restart/recreate; checker đọc lại bằng `compose port`.

| Game | Bot A/B | Match ID | Frames | Kết quả |
| --- | --- | --- | --- | --- |
| Robot | Python/C++ | f91e0e12fd4d459c | 10 | A knockout |
| Robot | C++/Java | ffadb4e75a5c481d | 11 | B knockout |
| Robot | Python/Java | 93fb3b9241e74783 | 10 | A knockout |
| OTT2ván | Python/C++ | a0fe61b8a51b4106 | 28 | A2–0 |
| OTT2ván | C++/Java | 47c7a69090624fc0 | 28 | A2–0 |
| OTT2ván | Python/Java | 8ec9e890c0d84a83 | 28 | A2–0 |

Sau restart, match `59c0257ab00a4b0e` dùng lại hai bot Python/Java đã compile của OTT; ba streams/result nhất quán, hashes uploads không đổi.

Chrome chạy trên backend Docker sau persistence checks, URL `http://192.168.2.16:32773`: Robot C++/Python `dbaf7d2811264772`10frames, OTT2ván C++/Python `807db83ae4ba4993`28frames. Cả ba tự mở cùng ID, Hoang/C++ và Minh/Python, cùng frame/result; [ảnh thật](screenshots/docker/).

QA container/network và chỉ các volumes có label/project ngẫu nhiên tương ứng đã được dọn sau test. Các ID/URL trên là chứng cứ lịch sử, không phải server QA còn chạy. Image runtime/tests được giữ để người dùng có thể chạy lại; service mặc định không được để chạy nền sau kiểm thử.

## Lỗi tìm thấy và đã sửa trong hạ tầng QA

- Pytest cache trên `/app` root-owned sinh permission warning khi chạy non-root. Target tests tạo riêng `/app/.pytest_cache` owner arena; chạy lại143test pass, warning quyền ghi đã hết. Runtime không cần cache test.
- Docker có thể cấp cổng host mới khi restart với published port0. Checker ban đầu giữ URL cũ và chờ sai cổng; đã dừng checker đó, dọn đúng project QA, sửa refresh URL rồi chạy lại toàn bộ thành công. Đây là lỗi checker; port cố định8000 của cấu hình mặc định đã kiểm tra riêng và hoạt động.

## Giới hạn

- Phase1 vẫn chạy subprocess trong cùng container/UID với server. Bot tin cậy có quyền đọc/ghi state container, không được xem Docker này là sandbox cho untrusted code. Không mở runner ra Internet.
- Chưa có ba laptop vật lý hoặc một Linux host độc lập để nghiệm thu. Đã kiểm tra Linux containers trên Docker Desktop và ba browser contexts/WS qua IP Wi-Fi của host; router/firewall/máy khác cần demo thực địa.
- Docker Engine/build cần quyền truy cập và Internet khi pull/install lần đầu. Image chứa compiler/JDK nên gần1GB theo Docker inspect, không nhỏ như Python-only image.
- Một worker/service duy nhất. Restart giữ dữ liệu nhưng không resume bot/match execution; semantics v3 giữ nguyên. Named volume không chống Docker Desktop reset, `down -v` hay volume prune; phải backup.
- Không tự import native Windows metadata/artifacts, không destructive migration. Chuyển môi trường/CPU/runtime đáng kể cần kiểm tra và nộp/compile lại source. Snapshot/replay native hiện có được giữ nguyên ngoài Docker.
- Backup tar đã được đọc kiểm tra nhưng chưa diễn tập restore toàn bộ sang máy khác trong Phase1. Quyền/đường dẫn khi restore cần đúng `/app` và UID10001.

Lệnh vận hành và backup đầy đủ: [DOCKER.md](DOCKER.md). Cơ chế named volumes/ordinary down theo [Docker volumes](https://docs.docker.com/engine/storage/volumes/) và [compose down](https://docs.docker.com/reference/cli/docker/compose/down/).
