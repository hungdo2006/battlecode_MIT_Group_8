# NEON ARENA: demo LAN nhiều client

Một máy chủ Python/FastAPI, nhiều trình duyệt. HTTP REST nhận submission/tạo trận/lấy danh sách; một WebSocket riêng cho mỗi spectator gửi sequence trạng thái. Một process, một worker; không cần Docker, dịch vụ cloud hay compiler trên máy người chơi.

## Khởi động và địa chỉ

Trên Windows, trong folder LTM:

```powershell
start.bat
# Hoặc sau khi đã cài dependencies:
.\.venv\Scripts\python.exe run.py --host 0.0.0.0 --port 8000
```

`0.0.0.0` là bind address, không phải địa chỉ để mở website. Chạy `ipconfig`, chọn IPv4 của adapter Wi-Fi đang dùng (không chọn VPN/WSL). Hai laptop mở `http://IP-MAY-CHU:8000`, cùng port. Trong app mở `/lan`, source [frontend/lan.html](../frontend/lan.html); trang gọi `/api/network` để hiện origin và các địa chỉ IPv4 LAN gợi ý.

Frontend gọi `/api/...` bằng relative paths và mở `ws(s)://location.host/ws/...`; HTTPS tự dùng WSS. Không có API URL hardcode localhost. Website/proxy phải phục vụ ở **gốc domain `/`**; template chưa hỗ trợ prefix như `/arena/`.

`ARENA_HOST` / `ARENA_PORT` thiết lập mặc định cho run.py; flags `--host` / `--port` ưu tiên hơn. Không có file .env tự động, đặt biến môi trường trong shell trước khi chạy. Dùng `--host 127.0.0.1` nếu chỉ cần một máy.

## Hai laptop cùng Wi-Fi

1. A chạy server, A/B đều mở URL LAN. Mỗi người nhập nickname khác nhau ở YOUR PLAYER SESSION.
2. Organizer chọn game, lưu luật và LOCK GAME / OPEN COMPETITION. Hai Player tự nhận game/luật qua /ws/competition, không được đổi game. Mỗi máy upload source phù hợp bằng phiên riêng; compiler chỉ cần trên host.
3. Thư viện chung tự cập nhật mỗi 2 giây, hiển thị owner nickname và mã phiên ngắn. Bot không bị khóa theo owner: mọi thành viên tin cậy có thể chọn bot của nhau để demo.
4. A chọn bot A/B rồi Start Match. B vào Xem trận đấu; danh sách chung tự cập nhật, có ID/người tạo và Live/Replay. Có thể gửi deep-link `/?match=ID#home` bằng nút ↗. Nên mở website bằng URL LAN trước khi chia sẻ; link localhost chỉ có ý nghĩa trên máy chủ.
5. Cả hai máy nhận cùng frame sequence/result. Playback là riêng từng máy, nên Canvas có thể đang ở các lượt khác nhau nếu Pause/tốc độ khác nhau. So sánh theo cùng sequence/timeline, không so theo đồng hồ.
6. Đóng/mất mạng rồi mở lại cùng trận: frontend tải replay hiện có, WebSocket reconnect dùng `after=last_seq`, nhận các frame còn thiếu. Trận hoàn tất xem lại không chạy code.

## Phiên đơn giản

`GET /api/session` nhận cookie `arena_session` HttpOnly, SameSite=Lax, Secure khi HTTPS; `PUT /api/session {"name":"Laptop A"}` đổi nickname. Cookie là token ngẫu nhiên 256 bit, không gửi trong payload public; server chỉ lưu SHA-256 của token cùng profile vào `data/sessions.json`. ID public khác token; nickname 1–32 ký tự, từ chối control characters. Phiên hết hạn sau 30 ngày, giữ sau khi server restart. Mở browser khác/ẩn danh/xóa cookie sẽ tạo người chơi mới.

Bot lưu `owner={id,name}`; trận lưu `created_by` và owner của hai bot. Đó là snapshot tên tại thời điểm upload/tạo trận: đổi nickname không đổi lịch sử. Sample compilation cache theo **phiên + game + ngôn ngữ + hash source**: cùng người nộp lại cùng mẫu dùng executable sẵn; hai người nộp cùng mẫu vẫn có submission/owner riêng. Dữ liệu v1/v2 cũ không có owner vẫn xem được, UI ghi rõ là submission/trận cũ.

Nickname/cookie nhận diện browser, không phải tài khoản Internet hay sandbox. Organizer xác minh ARENA_ADMIN_CODE bằng POST /api/session/organizer, DELETE để thu hồi. Quyền mất khi restart; mã không lưu JSON/frontend hoặc chuyển vào compiler/bot. Chỉ Organizer mở/đóng cuộc thi. Mọi trận dùng snapshot đã khóa; không nhận rules override từ Player hay Organizer.

Một cuộc thi chung: Organizer chọn game khi SETUP, lưu luật rồi POST /api/competition/open. Game/luật khóa read-only, mọi Player cùng game. POST /api/competition/close chặn trận mới ngay; nếu còn task thì DRAINING, không đổi game/luật cho đến khi hoàn tất hoặc Organizer cancel hợp lệ. Snapshot/lock ở data/rules.json giữ qua restart; /ws/competition initial/latest state cho client mới/reconnect, có revision/server_id. Frontend không dùng preference localStorage cũ để chọn game. Trận/replay dùng game ID/snapshot riêng, không bị chuyển game theo cuộc thi.

Cookie là host-scoped (các port cùng host dùng chung vùng cookie); đổi hostname/IP tạo vùng khác. Bootstrap thiết lập phiên trước khi fetch song song để tránh nhiều identity. Hai client có thể đang ở lượt playback khác nhau; competition state thống nhất do server quyết định.

## IP và Windows Firewall

- Hai máy phải cùng subnet có route tới nhau. Guest Wi-Fi/AP isolation có thể chặn kết nối dù SSID giống nhau. VPN có thể đổi route; kiểm tra IP của Wi-Fi thực tế.
- IP DHCP có thể đổi khi kết nối lại; xem `ipconfig` hoặc thiết lập DHCP reservation trên router theo MAC Wi-Fi. Nếu đặt IP tĩnh, dùng IP chưa được cấp, đúng subnet mask/gateway, tránh trùng IP.
- Trên Wi-Fi riêng đáng tin cậy, chọn Windows network profile Private. Nếu Python hỏi quyền, chỉ cho phép Private networks. Không tắt cả firewall.
- Nếu cần, **người dùng** chạy PowerShell Administrator trên máy chủ:

```powershell
New-NetFirewallRule -DisplayName "NEON ARENA LAN 8000" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8000 -Profile Private -RemoteAddress LocalSubnet
Get-NetFirewallRule -DisplayName "NEON ARENA LAN 8000"
# Xóa sau khi demo:
Remove-NetFirewallRule -DisplayName "NEON ARENA LAN 8000"
```

Script/app không tự sửa firewall. Đổi port thì thay đúng LocalPort. Không mở profile Public, port-forward router hoặc dùng tunnel Internet cho runner.

Trên laptop B:

```powershell
Test-NetConnection IP-MAY-CHU -Port 8000
Invoke-RestMethod http://IP-MAY-CHU:8000/api/health
```

`TcpTestSucceeded=False` thường do bind/port/IP/firewall/isolation. HTTP được nhưng WS lỗi: xem DevTools → Network → WS, origin phải cùng host/port; proxy cần Upgrade/Connection. Bot lỗi compiler/timeout xem Compiler log, không phải lỗi Wi-Fi.

## HTTPS/WSS và VPS: chuẩn bị chế độ xem

Giữ origin thống nhất, TLS kết thúc tại Nginx, proxy HTTP/WS vào Uvicorn loopback; backend chỉ tin forwarded headers từ IP proxy. Có mẫu `deploy/nginx.conf.example` với Host, X-Forwarded-Proto/For, Upgrade, Connection và timeout. Replace domain/certificate paths bằng cấu hình thật; không có Docker và chưa triển khai VPS trong task này.

```powershell
$env:ARENA_READ_ONLY = '1'
$env:ARENA_ALLOWED_HOSTS = 'arena.example.com'
.\.venv\Scripts\python.exe run.py --host 127.0.0.1 --proxy-headers --forwarded-allow-ips 127.0.0.1
```

Linux dùng `ARENA_READ_ONLY=1 ARENA_ALLOWED_HOSTS=arena.example.com python run.py --host 127.0.0.1 --proxy-headers --forwarded-allow-ips 127.0.0.1`. Nginx và backend trên cùng máy; không expose cổng 8000 ra Internet. Chỉ cho proxy IP thực tế, không dùng `*` nếu listener còn nhận client trực tiếp. Proxy phải giữ Host của website, không đổi thành upstream localhost.

Domain/public hosts chỉ được thêm khi **ARENA_READ_ONLY=1**; cấu hình sai fail ngay lúc startup. Không dùng wildcard. Chế độ này chặn mọi API mutation trừ đổi nickname: upload, sample-submit, tạo trận, đổi game/luật/reset đều HTTP 403; frontend cũng khóa nút. Mẫu Nginx còn chặn non-GET tại proxy, vì vậy nickname không đổi được qua template public này. Live stream nếu có trận do tiến trình demo đang chạy; replay đã lưu luôn xem được. Hiện chưa có cơ chế scheduler/admin chạy trận từ xa trong read-only.

Để triển khai thi đấu với code không tin cậy sau này cần sandbox thực sự, xác thực/phân quyền, quota và storage phù hợp. Cookie/Host/Origin/timeouts hiện tại không thay thế các phần đó. App giữ một worker vì match/event nằm trong RAM; nhiều worker cần thiết kế shared coordinator trước.

Cấu hình proxy dựa trên [FastAPI Behind a Proxy](https://fastapi.tiangolo.com/advanced/behind-a-proxy/), [Uvicorn Settings](https://www.uvicorn.org/settings/) và [Nginx WebSocket proxying](https://nginx.org/en/docs/http/websocket.html).

## Kiểm thử có thể lặp lại

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe scripts/check_lan.py --url http://IP-MAY-CHU:8000 --game robot_battle
.\.venv\Scripts\python.exe scripts/check_lan.py --url http://IP-MAY-CHU:8000 --game ott_v2
# Tùy chọn Chrome/Playwright để kiểm thử UI hai browser độc lập:
.\.venv\Scripts\python.exe scripts/check_multiclient_ui.py --url http://IP-MAY-CHU:8000
# Tùy chọn OpenSSL: HTTPS/WSS thật trên loopback, dữ liệu tạm, dùng một ID trận đã hoàn tất:
.\.venv\Scripts\python.exe scripts/check_https.py --match-id ID-TRAN
```

check_lan dùng **hai cookie jar**, đổi nickname, mỗi client upload một file bot (Python/C++), client B tìm trận A tạo, hai socket nhận trạng thái, reconnect và so với replay. Check UI dùng hai browser context độc lập: nickname/upload thực tế, tự thấy bot/trận, hai WebSocket, Pause riêng, same saved result. Test tự động trên host không chứng minh hai laptop vật lý; theo checklist trên để nghiệm thu hai thiết bị thật và ghi lại ID trận.

check_lan chạy theo cuộc thi đã mở; nếu dùng --open-competition/--max-turns thì A cần ARENA_ADMIN_CODE để cấu hình/lưu snapshot trước demo. Các QA browser dùng cùng biến trong shell; check_multiclient_ui có Organizer fixture riêng và hai Player, kiểm tra cập nhật khóa và trạng thái chờ qua WS không reload. Replay append-only JSONL, API vẫn xuất JSON/read archive `.json` cũ.

check_https cần OpenSSL trên PATH, tự tạo certificate self-signed tạm và xác thực bằng CA đó (không tắt certificate verification); kiểm tra cookie Secure giữ phiên, WSS replay và read-only. Không sửa trust store hệ thống, không chạy lại bot, xóa dữ liệu/cert tạm và dừng listener sau test. OpenSSL không phải dependency để chạy demo LAN.
