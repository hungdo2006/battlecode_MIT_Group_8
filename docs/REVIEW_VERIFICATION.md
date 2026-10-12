# Review và kiểm chứng NEON ARENA v2.2

Ngày **12/10/2026**, Windows, Asia/Saigon. Sửa repository hiện có, giữ kiến trúc FastAPI/JS/Canvas, không viết lại game, không thêm runtime dependency. Cyberpunk giữ nguyên; UI chỉ bổ sung nhãn role, hộp nhập mã và nút đặt game mặc định cần thiết cho phân quyền.

## Vấn đề đã xác nhận và sửa

| Vấn đề | Bằng chứng trước sửa | Cách sửa |
| --- | --- | --- |
| API cấu hình không có kiểm tra quyền | Một phiên Player PUT luật Robot trả HTTP 200; rule/default/reset đều không có auth dependency | Backend xác minh mã từ ARENA_ADMIN_CODE, cấp quyền cho cookie phiên; các mutation cấu hình cần Organizer |
| Override luật qua tạo trận có thể vượt trang Rules | `/api/matches` nhận `rules` tùy ý từ mọi phiên | Player gửi rules trả 403; Organizer có thể override, Player dùng cấu hình đã lưu |
| Chọn game thông thường thay default chung | Trước: A đọc default Robot; B chọn OTT qua API selection; A đọc lại thấy OTT. Reload A dùng default mới | Chọn game lưu localStorage của browser; API default chỉ dùng qua nút Organizer riêng. Match không ghi game_id suy từ bot A, không bị default chuyển hướng |
| Replay ghi lại toàn lịch sử mỗi lượt | Store.save_replay serialize mảng frames đầy đủ trong mỗi publish; 100 frame 1 KiB tạo khoảng 5,18 MB dữ liệu ghi | Append một frame/dòng vào `.jsonl`; reader trả cùng JSON API, giữ hỗ trợ `.json` cũ |

Việc chọn game trước đây **không tự đổi state game của trận đã chạy hoặc repaint replay đang xem**. Ảnh hưởng xác nhận là default chung/browser mới hoặc reload và implicit API start dựa vào default. Báo cáo không coi đây là lỗi đổi trận đang diễn ra.

## Phân quyền đơn giản

- Mọi người bắt đầu Player, kể cả loopback. Player upload bot, chọn game, tạo trận theo luật đã lưu, xem live/replay.
- Organizer xác minh bằng POST `/api/session/organizer {code}`, backend đọc environment lúc startup, compare digest constant-time. Không có mã dự phòng hardcode trong frontend hay tự cấp quyền theo IP/nickname.
- Rule PUT, alias PUT /api/rules, reset và default game PUT đều kiểm tra quyền. Match override cũng được bảo vệ; đổi nickname/giả role trong payload không cấp quyền.
- Grant chỉ lưu trong RAM theo phiên; logout/server restart thu hồi. Profile/cookie vẫn giữ; thiếu mã tắt unlock (503), các thay đổi cấu hình vẫn 403.
- Compiler/bot không được kế thừa ARENA_ADMIN_CODE. Test dùng subprocess Python thật kiểm tra credential không có trong environment, biến bình thường và venv vẫn hoạt động.
- Chỉ là phân quyền cho nhóm tin cậy. HTTP LAN chưa mã hóa code; không có tài khoản phức tạp, rate limiter Internet hoặc sandbox. Public mode vẫn read-only, không được bật runner public nhờ nhập mã.

## Replay và lượng ghi

`start_replay` tạo exclusive file `.jsonl`, ghi frame đầu; mỗi publish serialize/append đúng frame mới, sau đó mới cập nhật dữ liệu spectator. API vẫn `{match,version:1,frames:[...]}`; WebSocket sequence và nút download không đổi. Archive `.json` cũ đọc nguyên trạng, không có migration phá hủy.

File close flush vào OS mỗi lượt. Reader bỏ qua dòng cuối thiếu newline khi process dừng giữa chừng, kể cả tail UTF-8/JSON ghi dở. Test mô phỏng disk-write failure cho thấy không broadcast một frame chưa được ghi, match chuyển interrupted và replay chỉ có phần hoàn tất. Không hứa chịu mất điện/ổ đĩa hỏng. Frames live vẫn ở RAM, đọc replay vẫn O(n); metadata nhỏ vẫn dùng atomic JSON replacement để giữ dự án đơn giản.

Đo với cùng các frame `{"turn":i,"payload":"x"*1000}`; lượng cũ tính bằng đúng thuật toán serialization theo từng prefix, lượng mới là kích thước file ghi append:

| Số frame | Thuật toán cũ: tổng byte ghi replay | Append: tổng byte | Giảm |
| --- | --- | --- | --- |
| 100 | 5.177.695 | 102.490 | 50,52 lần |
| 200 | 20.610.395 | 205.090 | 100,49 lần |

Đây là benchmark lượng byte replay, **không phải** benchmark tốc độ ổ cứng hay tổng traffic HTTP. Lượng mới tuyến tính theo tổng kích thước frame; frame OTT lớn hơn Robot nên không giả định mọi lượt đều 1 KiB.

## Tests

- Full suite cuối: **109 passed**, không skip; warning duy nhất là Starlette TestClient deprecation của httpx.
- **8/8 test JavaScript nguồn OTT pass**; node --check cho app.js/renderers.js, Python compileall pass.
- Test mới bảo vệ role/default/override, grant riêng từng phiên, revoke/restart, thiếu mã, game fallback không bị đổi default, tăng trưởng byte tuyến tính, prefix cũ không bị ghi lại, replay cũ, tail ghi dở, long match 121 frames qua WS/REST/restart và IO-failure không phát frame ảo.
- Giữ và chạy tests runner: compiler errors, timeout/crash/invalid JSON/action/output limits, process PID/venv Windows, UTF-8, PY/C++/Java và engine cả hai game.

## Trận thật qua HTTP/WebSocket LAN

Server bind `0.0.0.0:8000`, client dùng `http://192.168.2.16:8000`. Cả sáu trận không bot_error; mỗi stream được so với replay API và khớp đầy đủ.

| Game | Ngôn ngữ | Match ID | Kết quả | Frames |
| --- | --- | --- | --- | --- |
| Robot Battle | Python / C++ | `48f07468b68b41e9` | A knockout | 10 |
| Robot Battle | C++ / Java | `957d038ab3214d22` | B knockout | 11 |
| Robot Battle | Python / Java | `63fa7b9c1a914f9a` | A knockout | 10 |
| OTT v2 | Python / C++ | `fd3df4b7371449a9` | A tới goal | 14 |
| OTT v2 | C++ / Java | `28ffb5d093574bb0` | A tới goal | 14 |
| OTT v2 | Python / Java | `7d8b3f9c498e4ef3` | A tới goal | 14 |

Compiler chỉ chạy khi submission chuẩn bị; không có compiler trong vòng lặp lượt. Các sample runners giữ process và cùng giao thức stdin/stdout. Đã xác nhận G++ và JDK có trên máy, không skip checks.

## Browser, LAN và HTTPS

- `check_lan.py`: hai Player có cookie riêng, mỗi bên upload bot, tìm trận chung, hai WS khớp replay/reconnect. Robot `ec90f354bf024706`, OTT PY/Java `0f3ef6e995d14287`.
- `check_multiclient_ui.py`: Organizer fixture riêng và hai Chrome Player. A chọn game khác; B giữ lựa chọn. Reload cả hai giữ game riêng. Organizer đổi default rồi reload B vẫn giữ game; Player gọi API rule PUT bị 403. Mỗi người upload qua form, auto-discovery, B tìm trận và bấm Live, hai WS và Pause độc lập, replay khớp. Robot `8d25235aa24544e4`; OTT 2 ván `5aa53539442f44a2`.
- `check_ui.py`: nhập mã bằng dialog thật, fields được mở cho Organizer, code input được xóa, luật tác động trận, dynamic schema, defaults, old replay đúng renderer, Start/Pause/Reset/Victory; Organizer logout khóa lại fields. 390px không tràn ngang. Robot `dbe5374ded8f4fb6`, OTT `3f73bad68caa44c4`.
- Test Chrome nhỏ riêng: Organizer dùng nút **Đặt game mặc định** thật; server trả default OTT; cấu hình được khôi phục.
- `check_https.py --match-id 5aa53539442f44a2`: đọc replay JSONL mới, HTTPS certificate local được xác thực, Secure cookie giữ phiên, **28 WSS frame khớp replay**, upload read-only bị chặn.

Các QA trả luật/game default về giá trị ban đầu và dừng server sở hữu sau kiểm thử. Ảnh hiện tại ở [Rules Organizer](screenshots/v2/rules-ott.png), [Rules mobile](screenshots/v2/mobile-rules.png), [Player B cùng trận](screenshots/network/client-b-live.png).

Người dùng đã cho biết **chưa có laptop thứ hai** cho checklist mới. Hai browser/client độc lập qua IP LAN là automation trên host, không báo cáo thành nghiệm thu hai laptop vật lý. Chưa triển khai VPS hoặc chạy Nginx public thật; các giới hạn mạng/sandbox của bản demo giữ nguyên.

## Demo trước giảng viên

Đặt ARENA_ADMIN_CODE trong PowerShell, chạy start.bat. Mở hai browser/ẩn danh, đặt nickname; nhập mã ở một browser để làm Organizer. Chứng minh Player không chỉnh luật được, Organizer sửa max_turns/HP hoặc rounds. Chọn Robot ở A và OTT ở B rồi reload; mỗi browser giữ lựa chọn. Upload bot cùng game, chạy một trận khác ngôn ngữ, xem WS và download replay JSON. Chỉ source tin cậy trong nhóm.
