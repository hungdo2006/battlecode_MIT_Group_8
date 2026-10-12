# NEON ARENA v3 — báo cáo triển khai và kiểm thử

Ngày kiểm tra: 12/10/2026. Nâng cấp source tại `D:\LTM`, không dựng lại dự án. Báo cáo này thay quy trình tạo trận trực tiếp của các báo cáo v1/v2/v2.3; các báo cáo cũ giữ làm lịch sử.

## Những vấn đề xác nhận từ audit

- POST `/api/matches` trước đây cho mọi Player chọn hai bot rồi chạy trận; Organizer cũng nộp source/mẫu như Player. Backend chưa thực thi quy trình điều hành mới.
- Có cookie/nickname/owner nhưng chưa có online presence, Active Bot, reservation hoặc lời mời hai người.
- Chỉ browser bấm Start tự mở match; hai client khác phải tự tìm trận.
- UI/history/result chỉ dùng tên bot, thiếu participant snapshot riêng.
- Game Lock/registry/adapters, hai renderer, runner compile một lần và replay JSONL đã hoạt động; bộ test trước sửa pass. Các phần này được tái sử dụng.

## File và chức năng

| File/nhóm | Thay đổi |
| --- | --- |
| `backend/lobby.py` mới | Presence nhiều tab/heartbeat, Active Bot theo owner/game, reservation, state machine invitation, expiry, auto start, cleanup/finish, persist/restart |
| `backend/main.py` | API Player/invitation, chặn Organizer upload/mẫu/Active Bot, chặn POST matches cho mọi role, role switch kiểm tra busy; mở rộng WS cuộc thi theo người nhận |
| `backend/competition.py` | Close hủy pending, can_edit chờ cả match cleanup và pending chưa đóng hợp lệ; chung admission lock |
| `backend/matches.py` | Participant + submission snapshot, invitation_id/winner; engine/runner giữ cách chạy cũ |
| `backend/models.py` | Payload strict cho Active Bot và invitation, từ chối trường thừa |
| `frontend/app.js`, `index.html`, `styles.css` | Quick Deploy đổi thành ghép hai Player, roster/status/Active Bot riêng, popup/countdown/Accept/Decline, auto Live, participant name/language, UI role, Cyberpunk giữ palette/panels/renderers |
| `frontend/lan.html`, `README.md`, `docs/NETWORKING.md`, `ADAPTERS.md`, `MULTIPLAYER.md` | Demo ba laptop, protocol, quyền, LAN/firewall, restart và giới hạn |
| `scripts/check_multiplayer_ui.py`, `check_multiplayer_network.py` mới | QA ba Chrome contexts và sáu cặp ngôn ngữ qua listener LAN, data tạm, tự dừng |
| `scripts/check_lan.py`, `demo_match.py`, `check_ui.py`, `check_multiclient_ui.py`, `check_https.py` | Dùng invitation/presence thay Start trực tiếp; HTTPS bỏ revision thay đổi do presence khi so snapshot |
| `tests/test_lobby.py` mới, `tests/workflow.py`, test regression liên quan | Kiểm tra API/WS/runner thật; setup test cũ chuyển sang lời mời hai Player, cập nhật status theo phân quyền v3 |

Không đổi công nghệ, không thêm dependency runtime, Docker hay dịch vụ. Source Game Adapter/runner/replay storage không viết lại. GET replay giữ shape; metadata chỉ bổ sung trường, UI có fallback dữ liệu cũ. Không xóa data/submission/replay đang có; QA server dùng thư mục tạm riêng.

API mới: GET players/me, PUT active-bot, GET/POST invitations, POST accept/decline/cancel. Không thêm WS trùng chức năng: `/ws/competition` gửi full state cùng `role/lobby`, có trạng thái online, invitation STARTED/finished và match_id/result; `/ws/matches` giữ seq/frame/complete. Protocol chi tiết ở [MULTIPLAYER.md](MULTIPLAYER.md).

## Kiểm thử đã thực sự chạy

- Python trước sửa: 122 test pass. Sau nâng cấp: toàn bộ regression và 21 test lobby mới, **143 test pass, không skip**. Có một cảnh báo deprecation từ Starlette/httpx; không phải lỗi test.
- JavaScript reference: **8/8 pass** bằng `node --test docs/reference/ottv2/tests/rules.test.js`; syntax app.js/renderers.js và compileall Python pass.
- Permission/identity: Organizer upload/sample/Active Bot bị403; Player config/open/pairing/direct-match bị403; chỉ cookie của người được mời Accept được; payload player_id bị422; stranger không nhận invitation người khác.
- Invitation: Accept A hoặc B riêng chưa start, hai Accept tự start; bốn Accept cạnh tranh/lặp chỉ một match; Decline/Cancel/Expiry/Close không chạy; READY/distinct/owner/game/busy kiểm tra thật; Active Bot freeze và đổi trước Accept cập nhật popup data.
- Presence: hai session, tên trùng phân biệt bằng ID, nhiều tab, disconnect, timeout heartbeat, heartbeat phục hồi, reconnect pending không tự Accept, reconnect active match đúng ID, Player offline không làm bot crash.
- Persistence/cleanup: restart hủy pending, không online giả; giữ identity/Active Bot/lock/replay. Match infrastructure error/cancel giải phóng Player. Lỗi ghi invitation sau khi đã tạo match cũng không tạo trận thứ hai khi retry/restart, nhờ match metadata liên kết invitation_id.
- Rules/compatibility: rule snapshot ảnh hưởng lượt/ván thật, không sửa khi khóa/draining, game cũ replay sau đổi game, adapter thứ ba chạy qua lời mời không sửa Tournament Core. Runner/fault/timeout/output và replay tăng tuyến tính vẫn có regression pass.

### Sáu cặp ngôn ngữ — HTTP/WS qua IP Wi-Fi thật

Chạy `scripts/check_multiplayer_network.py --lan-ip 192.168.2.16`; Uvicorn bind0.0.0.0, cổng QA52940, data tạm. Mỗi lần có một Organizer và hai Player với cookie riêng, active submissions riêng, invitation và hai Accept. Ba WS streams bằng nhau và bằng replay; không bot_error.

| Game | Bot A / B | Match ID | Frame | Kết quả |
| --- | --- | --- | --- | --- |
| Robot Battle | Python / C++ | 77dc7761080243f4 | 10 | A, knockout |
| Robot Battle | C++ / Java | cb39007965a3471e | 11 | B, knockout |
| Robot Battle | Python / Java | 1e1ac79008804b70 | 10 | A, knockout |
| OTT v2, 2 ván | Python / C++ | f5c63270e5864023 | 28 | A, 2–0 |
| OTT v2, 2 ván | C++ / Java | 88f32a5ac0a3477e | 28 | A, 2–0 |
| OTT v2, 2 ván | Python / Java | 9b744239c99b4461 | 28 | A, 2–0 |

Kịch bản thứ7 `check_lan.py`: hai Player upload source Python/Java qua multipart, chọn active, nhận/mời/Accept, tìm cùng trận `f4e45a600ac14083`, ba WS nhận28frame bằng replay, reconnect sau seq14 nhận đúng phần còn lại. Server QA đã dừng, dữ liệu tạm được thu hồi; ID này là chứng cứ test, không phải link live còn chạy.

### Chrome ba phiên và giao diện

Đã chạy `scripts/check_multiplayer_ui.py --lan-ip 192.168.2.16`, Chrome headless3contexts, ba cookie khác nhau, serverQA0.0.0.0:8015. Kịch bản Robot C++/Python (10frames), OTT C++/Python2ván (28frames): upload qua form, SET AS ACTIVE BOT, Organizer selector/Invite, popup ở cả hai Player, Accept1 chưa start, Accept2 auto mở cùngmatch_id ở ba trang, đúng Hoang/C++ vs Minh/Python. WS frames/result trùng replay, Pause riêng, reconnect, READY sau cleanup, replay OTT sau đổi currentgame, viewport390px không overflow. **Không có JavaScript page error.**

Ảnh thật ở [screenshots/multiplayer](screenshots/multiplayer/): Organizer roster, popup invitation, result Robot/OTT, mobile lobby. Không dùng API mock.

### HTTPS/WSS

`scripts/check_https.py --match-id 8d8f3c3ff616429d`: TLS thật với certificate validation, Secure cookie ổn định,14frame replay cũ qua WSS bằng REST, snapshot cuộc thi đúng (revision có thể đổi vì presence), read-only upload bị403. Server TLS riêng đã dừng; không triển khai VPS/reverse proxy thực tế.

## Hạn chế còn lại

- Chưa có ba laptop vật lý để nghiệm thu toàn bộ quy trình. Đã chứng minh ba phiên/trình duyệt và listener IP Wi-Fi trên cùng host; chưa chứng minh router/AP/firewall của thiết bị thứ2/3. Làm theo [demo](MULTIPLAYER.md) để kiểm tra tại lớp.
- Một process/worker, JSON file + RAM lock; phù hợp nhóm nhỏ, không thiết kế cho nhiều server hoặc production scale. Lời mời/history lưu bền vững; snapshot lobby hiển thị100lời mời mới nhất, UI20; data không bị xóa.
- Subprocess không sandbox; chỉ dùng source đáng tin cậy trong LAN. HTTP LAN không mã hóa code Organizer; cookie là phiên browser, không hệ thống tài khoản đầy đủ. Player không cần compiler; host phải có Python/G++/JDK.
- Pending/partial invitation bị cancel khi restart; bot match đang chạy bị interrupted theo cơ chế cũ, không resume execution. User phải xác minh Organizer lại, mời trận mới nếu cần.
- Playback có thể khác lượt giữa các browser do Pause/speed, nhưng dữ liệu cùng sequence/result. Không đồng bộ animation theo từng mili-giây.
- Disk đầy/hỏng liên tục vẫn cần người chạy server khắc phục; maintenance retry không thay thế lưu trữ đáng tin cậy.
