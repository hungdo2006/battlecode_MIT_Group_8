# NEON ARENA v3 — demo ba laptop và giao thức

Một FastAPI worker, một cuộc thi, các bot chạy trên laptop server. Không cần thêm dịch vụ. Giữ GameRegistry/GameAdapter, runner Python/C++/Java và API replay `{match,version:1,frames}`.

## Chuẩn bị và demo

1. Laptop 1 cài Python/dependencies, G++ và JDK theo README. Trong PowerShell: `$env:ARENA_ADMIN_CODE = Read-Host 'Ma Organizer'`, rồi `.\start.bat`. Server mặc định `0.0.0.0:8000`. Chạy `ipconfig` lấy IPv4 của Wi-Fi đang dùng.
2. Cả ba laptop mở `http://IP-LAPTOP-1:8000`. Hai Player chỉ cần browser; không phải chạy server/compiler hay mở cổng. Dùng ba browser profiles/contexts riêng để thử trên một máy; không dùng ba tab cùng cookie như ba người.
3. Laptop 1 nhấn Mở quyền Organizer, xác minh mã. Chọn Robot Battle, lưu luật (ví dụ map 12, HP100, damage20, max_turns100), LOCK GAME / OPEN COMPETITION. Form game/luật khóa; Organizer không có upload/Active Bot.
4. Laptop 2 đặt Hoang, upload `samples/hunter.cpp`, SET AS ACTIVE BOT. Laptop 3 đặt Minh, upload `samples/hunter.py`, SET AS ACTIVE BOT. Hai Player thấy luật chốt, không được thay game. Có thể dùng bot mẫu hoặc source của nhóm.
5. Organizer vào Phòng thi đấu. Bảng có nickname + ID ngắn (phân biệt tên trùng), Active Bot, language, ONLINE/READY/INVITED/IN_MATCH/OFFLINE. Chọn Hoang và Minh READY, INVITE TO MATCH.
6. Cả hai Player nhận popup game/đối thủ/bot/ngôn ngữ/countdown60s. Hoang ACCEPT: chỉ PARTIALLY_ACCEPTED, WAITING FOR OPPONENT, chưa chạy bot. Minh ACCEPT: server tạo đúng một match, cả ba tự đến cùng Live Arena. Không bấm Start lần nữa.
7. So sánh match_id, số lượt/sequence và kết quả. Pause/tua trên laptop2 không ảnh hưởng laptop1/3. Cả ba hiển thị Hoang / C++ VS Minh / Python cùng tên bot. Mở history/replay hoặc tải JSON.
8. Kết thúc và cleanup trả hai Player về READY nếu còn online. Mời tiếp. Để thử OTT: Close, đợi SETUP, chọn OTT v2, lưu `rounds/max_turns`, Open, hai Player nộp source ở `samples/ott_v2/` và chọn Active Bot mới. Replay Robot vẫn xem đúng game/luật.

Đóng tab sau khi trận bắt đầu không hủy trận: bot ở server tiếp tục. Mở lại cùng hostname/browser/cookie để khôi phục trạng thái; có nút MỞ LẠI TRẬN. Reconnect lời mời chưa tự Accept. Đóng cuộc thi hủy lời mời đang chờ (`competition_closed`); trận đã chạy giữ snapshot và tiếp tục hoặc Organizer cancel có kiểm soát. Chỉ chỉnh game/luật sau cleanup.

Nếu máy khách không vào được: xem [NETWORKING.md](NETWORKING.md) hoặc `/lan`. Kiểm tra IPv4 Wi-Fi, Private firewall TCP8000/LocalSubnet, không AP isolation/VPN sai route. Không sửa firewall tự động. Không mở runner ra Internet.

## REST

Identity luôn lấy từ cookie `arena_session` đã có; không tin player_id ở payload phản hồi. Organizer code chỉ xác minh ở backend từ environment; grant RAM mất sau restart. Promote Player đang có invitation/match bị từ chối.

| Endpoint | Quyền và dữ liệu |
| --- | --- |
| GET `/api/players` | Roster public tối thiểu: player_id, nickname/display_name, online/status, Active Bot, invitation/current match |
| GET `/api/players/me` | Profile của cookie hiện tại; gọi GET `/api/session` trước để nhận cookie |
| PUT `/api/players/active-bot` | Player gửi `{bot_id}`; owner phải là mình, READY, đúng game hiện tại |
| POST `/api/invitations` | Organizer gửi `{player_a_id,player_b_id}`; OPEN, hai ID khác nhau, cả hai online/READY, chưa bị giữ bởi lời mời/trận khác |
| GET `/api/invitations` | Organizer xem tất cả; Player chỉ lời mời của mình |
| POST `/api/invitations/{id}/accept` | Player được mời, body trống; lặp Accept idempotent, STARTED trả match_id cũ |
| POST `/api/invitations/{id}/decline` | Player được mời, body trống; kết thúc lời mời chưa bắt đầu |
| POST `/api/invitations/{id}/cancel` | Chỉ Organizer, chưa STARTED; cancel lặp trả record đã cancelled |
| POST `/api/matches` | Route cũ luôn 403 cho cả hai role; không còn đường tắt tạo trận |
| POST `/api/bots`, sample submit | Chỉ Player; GET source mẫu vẫn đọc được |

Status invitation: PENDING → PARTIALLY_ACCEPTED → STARTED (match_id). DECLINED/EXPIRED/CANCELLED kết thúc mà không chạy. ACCEPTED được hợp nhất với STARTED trong một critical section, không lưu bước trung gian để tự chạy lại. `finished:true` đánh dấu STARTED đã sử dụng và trận đã cleanup; không thể dùng invitation đó tạo trận khác.

Active Bot được đổi trước Accept, lời mời cập nhật bot hiển thị tương ứng. Sau Accept hoặc trong match, Active Bot đóng băng. Trước lượt Accept thứ hai, server kiểm tra lại OPEN/game, online và hai ID submission đã chốt. Đối thủ đã offline: CANCELLED/player_unavailable. Lỗi start/capacity: CANCELLED/match_start_failed; hai Player được giải phóng.

## WebSocket và tính nhất quán

Tận dụng `/ws/competition`, không tạo WS lobby song song. Envelope:

```json
{
  "type": "competition",
  "state": {"selected_game_id":"robot_battle","phase":"open","competition_locked":true,"rules":{},"revision":12,"server_id":"..."},
  "role": "player",
  "lobby": {"players":[],"me":{},"invitations":[],"server_time":0}
}
```

Đây là full snapshot mới nhất, tương đương PLAYER_ONLINE/OFFLINE/READY_CHANGED, INVITATION_CREATED/UPDATED/EXPIRED, MATCH_STARTED/FINISHED. `status:STARTED + match_id` điều khiển tự mở Live; `finished:true + result` báo finish. UI nhớ invitation_id đã mở, không mở lại khi chỉ đổi nickname hoặc nhận snapshot lặp. Client mới/reconnect đọc state mới nhất, có current_match_id; không replay các lệnh Accept. Player chỉ nhận invitation của mình. Không phát token cookie/admin code.

Browser gửi `{"type":"heartbeat"}` mỗi10s. Server timeout35s hoặc disconnect loại connection; một Player có nhiều tab vẫn online nếu còn một connection sống. Presence hoàn toàn RAM, không khôi phục online giả khi restart. Client tạo session qua REST trước WS; WS không cookie chỉ xem cuộc thi, không tính là Player online.

Frame game vẫn dùng `/ws/matches/{id}?after=N`: hello, state(seq), complete. N=-1 từ frame0; reconnect từ N+1. Replay REST tải frame đã có; browser gán theo seq để không nhân đôi. Send ngoài condition engine, timeout client chậm; mỗi spectator riêng, một match chạy duy nhất. Playback430ms/frame có speed, độc lập server tick/logic.

Mọi Accept/create invitation/active selection/config/close dùng chung `Competition.lock` trong một event loop. Khi Accept đồng thời, lượt thứ hai tạo một task MatchManager và lưu match_id trước khi thả lock. Lặp Accept thấy STARTED và trả cùng ID. Shield bảo vệ phần Accept đang thực hiện khỏi request disconnect. Không hỗ trợ nhiều Uvicorn worker; JSON và RAM lock thiết kế cho một process demo.

## Persistence và lịch sử

- `sessions.json`: identity và hash cookie, không lưu quyền Organizer.
- `players.json`: Active Bot ID, last_match_id. Submission immutable, compile một lần.
- `invitations.json`: người gửi, hai Player, bots, responses, game/rules snapshot, expiry, match_id, finish/result. Pending/partially accepted/accepted cũ được CANCELLED/server_restart, tuyệt đối không tự chạy.
- `matches.json`: thêm invitation_id, participants, player_a/b_id/name_snapshot, bot_a/b_id/name_snapshot/language, winner; giữ game_id/rules_snapshot/result/status cũ.
- Replay JSONL và `.json` cũ giữ nguyên. Match không có metadata Player dùng owner/name bot làm fallback, không cần migrate replay.

Bot lỗi/timeouts vẫn bị xử thua theo engine. Lỗi hạ tầng/cancel giải phóng reservation sau runner cleanup. Maintenance retry khi disk lỗi tạm thời; disk hỏng liên tục vẫn cần người chạy server xử lý.

Chỉ dùng source tin cậy: subprocess không phải sandbox; HTTP LAN không mã hóa mã Organizer. HTTPS/WSS/reverse proxy chế độ xem giữ như trước.
