# Organizer Game Lock — NEON ARENA v2.3

Ngày **12/10/2026**, Windows, Asia/Saigon. Nâng cấp source hiện tại, giữ FastAPI/REST/WebSocket, subprocess, JSONL replay, registry/adapters, hai game và giao diện Cyberpunk. Không thêm dependency runtime, Docker hoặc hệ thống nhiều giải.

## Cơ chế thực tế

| Phase | Tạo trận mới | Đổi game/luật | Submission |
| --- | --- | --- | --- |
| SETUP | Chặn | Chỉ Organizer | Chỉ game đang được ban tổ chức chọn |
| OPEN (`competition_locked=true`) | Đúng game khóa, hai bot tương thích, dùng snapshot server | Chặn cả Organizer | Chỉ game khóa |
| DRAINING (đã close nhưng còn task) | Chặn ngay | Chặn đến khi các task/bot cleanup kết thúc hoặc bị cancel hợp lệ | Chỉ game hiện tại |

Đây là một cuộc thi duy nhất. Organizer chọn game, Save rules rồi LOCK GAME / OPEN COMPETITION. Server không lấy luật chưa Save trên browser và không nhận per-match override, kể cả Organizer. CLOSE COMPETITION / UNLOCK đóng admission ngay; không tự hủy trận đang chạy. Khi hết task, controller phát SETUP để Organizer có thể sửa và mở lại.

Organizer có thể cancel riêng trận qua POST `/api/matches/{id}/cancel`; runner được thu hồi, metadata lưu interrupted/organizer_cancelled và replay đã có được giữ. Player không được cancel. Trường hợp task còn queued cũng có metadata terminal hợp lệ trước khi cấu hình được mở lại.

## Kiến trúc và persistence

- `backend/competition.py`: controller chung, một asyncio admission lock, condition/revision/server_id cho latest-state broadcast. Không có luật Robot/OTT trong controller.
- `data/rules.json` version 3 lưu `selected_game_id`, `competition_locked`, `active_rules_snapshot` cùng cấu hình game. V1/v2 chuyển sang SETUP, giữ submission/replay. Restart giữ khóa/snapshot; các trận đang chạy vẫn chuyển interrupted như trước.
- Store không tự chuyển sang game khác nếu game khóa không còn cài; missing/corrupt snapshot không được silently mở cuộc thi. Thay cấu hình lỗi ghi disk không làm open/game state trong RAM lệch với phần chưa commit.
- Chọn/reset/save/open/close/create-match dùng cùng admission lock. Một request start được reserve trước close thì tiếp tục với snapshot cũ; start đến sau close bị chặn.
- Submission validate game trước compile và revalidate khi commit: đổi game trong lúc compile trả 409, không lưu bot sai game; chỉ dọn folder mới do request đó tạo dưới uploads.
- Manager lấy game và luật từ competition snapshot, kiểm tra cả hai bot. GameAdapter interface và engine logic không đổi; test game thứ ba CounterAdapter vẫn qua.
- Metadata trận có `game_id`, `rules`, `rules_snapshot`; frame giữ rules/game ID như trước. Đổi cuộc thi không sửa snapshot/replay cũ. API replay giữ nguyên, vẫn append-only JSONL và đọc `.json` cũ.

## WebSocket và UI

`GET /api/competition` và `/ws/competition` cung cấp full state: selected game, lock, snapshot, rules đang hiển thị, phase, pending_matches, can_edit, revision/server_id. Client mới nhận state hiện tại; disconnect/restart tự reconnect. Broadcast gửi latest state, không tạo event-history giải đấu. Role grant vẫn cần backend kiểm tra; can_edit chỉ biểu thị phase, không tự cấp quyền.

Frontend dùng server selection cho mọi Player; bỏ preference localStorage v2.2. Organizer chỉ chọn game/lưu rules khi SETUP. OPEN thì game/rules readonly; Player thấy snapshot và chỉ có Start khi mở. Upload form vẫn gửi game đúng dù selector bị disabled (FormData mặc định bỏ disabled field). Banner phân biệt OPEN, WAITING và CLOSING. State cập nhật không reload; viewer dùng game ID của trận nên vẫn vẽ OTT khi cuộc thi mới là Robot, hoặc ngược lại.

## Test suite

**122 test Python pass**, không skip. **8/8 Node test luật OTT gốc pass**. Python compileall và node --check app.js/renderers.js pass. Warning duy nhất là Starlette TestClient deprecation của dependency httpx.

Không xóa/skip test engine/runner cũ. Các scenario integration cũ đã thay setup: mở cuộc thi trước start, lưu luật trước lock và kiểm tra chỉnh luật đang khóa trả 409. Việc v2.2 cho browser chọn game riêng/override luật đã được thay bằng yêu cầu mới; assertions snapshot/engine/replay/compile vẫn được giữ.

13 test competition mới kiểm tra:

1. Mặc định closed; Player không open/close/select, chưa mở thì start 409.
2. Direct API game_id/game alias khác bị chặn; Player rules override 403, Organizer override 409.
3. Locked rules/default/reset trên mọi game đều bị chặn, snapshot thật được dùng trong match.
4. Upload/sample-submit đúng game, cả sample cache/legacy alias; không xóa submission game cũ.
5. Close → DRAINING, chặn start/config/open lại; cancel chỉ Organizer, thu hồi trước SETUP.
6. Hai WebSocket spectator nhận cùng lock, client đến sau và restart đọc cùng snapshot.
7. Trận kết thúc tự phát SETUP sau close.
8. Replay/game/rules_snapshot cũ không đổi sau chuyển game; bot cũ còn trong thư viện.
9. Compile race với đổi game không commit submission không tương thích.
10. Concurrent create-match/close serialize admission, không lọt start sau close.
11. Cancel queued task lưu interrupted hợp lệ và mở được cấu hình sau cleanup.
12. Game khóa bị thiếu không tự chọn game khác; disk-write failure rollback state, kể cả snapshot closed trước đó.
13. Trận đã completed nhưng còn bot cleanup không được cancel lại hoặc đổi cấu hình; kết quả/replay hoàn tất giữ nguyên, chỉ chuyển SETUP sau cleanup thật.

## Trận thực tế qua LAN

Server bind `0.0.0.0:8000`, client dùng `http://192.168.2.16:8000`. Script cấu hình/open bằng Organizer trước mỗi game; trận không gửi rules override. Cả sáu match không bot_error và WS khớp replay API:

| Game | Bot | Match ID | Kết quả | Frames |
| --- | --- | --- | --- | --- |
| Robot | Python/C++ | `6ff8abb104484dfc` | A knockout | 10 |
| Robot | C++/Java | `9225a6f9bf43411d` | B knockout | 11 |
| Robot | Python/Java | `1142d9efbace431a` | A knockout | 10 |
| OTT | Python/C++ | `49e63792d47c426d` | A goal | 14 |
| OTT | C++/Java | `85903b222f1c490d` | A goal | 14 |
| OTT | Python/Java | `603a4a4f68fc45d8` | A goal | 14 |

`check_lan.py`: hai cookie jar, mỗi bên multipart upload, tìm match chung, hai WS match = replay và reconnect đúng sequence. Robot `6fe1685f8a4e4898`; OTT PY/Java `8d8f3c3ff616429d`.

## Browser và restart thật

- Hai Chrome Player + Organizer fixture riêng: config/open gửi state không reload; selectors/rules khóa; direct start khác game, Player close/rule PUT, Organizer locked edit đều bị từ chối. Close lúc trận còn chạy làm cả hai chuyển DRAINING và khóa Start. Trận vẫn chạy/vẽ, Pause độc lập; sau cleanup tự SETUP. Organizer chuyển game mới, cả hai cập nhật nhưng replay cũ giữ nguyên. Robot `e97d4bf6e43d42d7`, OTT 2 ván `b7b279f99c2f4db5`.
- UI Organizer thật: nhập code, chọn/save rules, Lock bằng nút. Sau khi Save HP=90, sửa draft HP=91 rồi Lock: server snapshot vẫn HP=90, readonly form được cập nhật về 90. Dynamic schema, compiler upload, hai game live/replay, Pause/Reset/Start/Victory, defaults và 390px pass. Robot `951cd32851fe4b45`, OTT `8063817a37e04d0c`.
- Restart server thật trên cùng port, dữ liệu tạm cô lập, giữ browser mở: websocket reconnect **không reload**, lock/snapshot không đổi, cookie/nickname vẫn giữ và Organizer role trở lại Player. Start vẫn dùng cuộc thi đã khóa.
- HTTPS/WSS certificate local được xác thực: **28 replay frame**, competition WSS state = REST, Secure cookie ổn định, read-only upload bị chặn. Không triển khai VPS/Nginx public.

QA khôi phục game/rules/trạng thái ban đầu, không xóa archive và dừng các server sở hữu. Ảnh: [Rules](screenshots/v2/rules-robot.png), [Mobile](screenshots/v2/mobile-rules.png), [Player đang xem OTT khi game tổ chức đã chuyển sang Robot](screenshots/network/client-b-live.png).

## Cách chạy/demo

```powershell
$env:ARENA_ADMIN_CODE = Read-Host 'Nhap ma Organizer'
.\start.bat
```

Mở website, nhập code để có Organizer; chọn Robot/OTT, Save rules, LOCK GAME. Player nộp bot tương thích và Start. CLOSE chặn trận mới; đợi/cancel qua Swagger `/docs`, đổi game rồi mở lại. Script CLI `--open-competition` hoặc `--max-turns/--rounds` cần cùng biến admin để cấu hình trước demo. Script không cấu hình yêu cầu cuộc thi đúng game đã mở.

## Giới hạn

Chỉ một competition, một worker; không bracket hoặc marketplace. Grant Organizer cần xác minh lại sau restart. Snapshot/lock ghi atomic JSON; không bảo đảm chống mất điện/ổ đĩa hỏng. Client chậm có thể chỉ nhận trạng thái mới nhất, không từng event trung gian. Bot/library/replay vẫn giữ lâu dài, không tự dọn lịch sử. Chỉ code tin cậy: subprocess không phải sandbox, credential/Host/Origin không tạo isolation hệ điều hành.

Các client/browser chạy độc lập trên host qua IP LAN thực. Người dùng trước đó cho biết chưa có laptop thứ hai; **chưa nghiệm thu toàn bộ workflow trên hai laptop vật lý**. Không báo automation cùng máy là hai thiết bị.
