# OẲN TÙ TÌ — Tournament Board Game

Nền tảng thi đấu nhẹ bằng HTML/CSS/JavaScript thuần, Node.js, Express và Socket.IO. Giữ giao diện, SVG và test của prototype; thay multiplayer playhtml bằng server tự host, kiểm tra luật và quyền ở server.

## Cài đặt và chạy

Cần **Node.js 22 trở lên** và npm.

```bash
npm install
npm start
```

Mở `http://localhost:3000`. Console in địa chỉ local và các IPv4 LAN của laptop, ví dụ:

```text
Local: http://localhost:3000
LAN:   http://192.168.1.10:3000
```

Trên Windows nếu PowerShell chặn `npm.ps1`, dùng `npm.cmd install`, `npm.cmd start`, `npm.cmd test`; không cần đổi Execution Policy. Lần cài dependency cần Internet; lúc chơi local hoặc LAN, mọi JS/CSS/SVG và Socket.IO được phục vụ từ laptop, không gọi CDN.

## Ba chế độ triển khai

### A. Hai người chung thiết bị

Chọn RuleSet ở trang chủ → **Local 2-player**. Hai người đi luân phiên; có điểm, vòng, reset và vòng mới sau khi thắng. Local dùng engine ngay trong browser, không mở Socket.IO.

Local cũng chạy trên HTTP host tĩnh, chẳng hạn VS Code Live Server hoặc:

```bash
python -m http.server 5500
```

Mở `http://localhost:5500`. Không cần backend realtime hay Internet. Không mở HTML bằng `file://` vì JavaScript modules và fetch cần HTTP. Trên host tĩnh, `js/config.js` dùng `config/rules/index.json` làm danh mục; Create Room và Admin cần Node server.

### B. Laptop làm host LAN

1. Laptop chạy `npm start` (mặc định bind `0.0.0.0:3000`).
2. Điện thoại/máy khác cùng Wi-Fi mở URL **LAN** được in ở console.
3. Nếu không truy cập được, cho phép Node.js/cổng TCP 3000 trong firewall của mạng riêng; kiểm tra Wi-Fi không bật cô lập thiết bị và dùng đúng IPv4 của laptop.
4. Không cần Internet khi chơi. Giữ laptop chạy server và tránh chế độ sleep trong buổi demo.

Có thể tạo nhiều room độc lập. Mỗi room chọn RuleSet riêng.

### C. VPS/Internet

Cùng code và lệnh `npm start` chạy trên VPS. Đặt `HOST`, `PORT`, `ADMIN_PASSWORD` qua biến môi trường; dùng reverse proxy HTTPS cho website và Socket.IO. Proxy cần chuyển tiếp WebSocket trên `/socket.io/`. Dùng trình quản lý tiến trình của máy chủ để chạy lâu dài.

V1 chạy **một tiến trình Node**; đổi laptop sang VPS không cần viết lại engine. Nếu sau này cần nhiều tiến trình/máy, phải bổ sung shared persistence và adapter Socket.IO. GitHub Pages chỉ phục vụ local; multiplayer mới cần Node host.

## Tạo/join room

1. Nhập tên, chọn RuleSet, bấm **Create online room**.
2. Server tạo mã sáu ký tự; bấm **Copy link** hoặc gửi mã cho người chơi.
3. Người khác nhập mã ở trang chủ, không phân biệt hoa/thường.
4. Hai người claim P1/P2; những người còn lại là spectator.
5. Khi cả hai ghế có kết nối, server bắt đầu cho đi theo lượt.

Client chỉ gửi `from`, `to`, `revision`. Server lấy actor từ socket, kiểm tra ghế/lượt/bounds/luật, cập nhật board/điểm/kết quả và broadcast snapshot. Client không thể gửi board hoặc winner để thay kết quả. Request dựa trên revision cũ bị từ chối; chọn lại quân trên trạng thái mới.

Spectator không được đi, reset hoặc tạo vòng mới. Người đã ngồi ghế có thể reset; vòng mới chỉ được mở sau khi kết thúc vòng hiện tại. **Leave player seat** chuyển thành spectator và giải phóng ghế ngay.

Khi mất kết nối, server giữ ghế **20 giây**, tạm dừng nước đi và phục hồi qua token do server cấp. Browser lưu token riêng cho tab/room trong `sessionStorage`, nên refresh cùng tab có thể giữ ghế và bàn cờ. Sau timeout ghế được mở lại; server restart hoặc tab mới không bảo đảm phục hồi ghế. Link room thông thường không chứa reconnect token.

## Tournament / Admin

Mở `http://localhost:3000/admin` hoặc nút **Tournament / Admin** trên trang chủ.

- Xem room, RuleSet, P1/P2, trạng thái, winner và điểm; tạo/reset room.
- Tạo giải, thêm người chơi, chọn hai người khác nhau và RuleSet để tạo match.
- Gửi **P1 invitation** cho người P1 và **P2 invitation** cho người P2. Mỗi link có token riêng; link Spectate chỉ để xem. Ghế được bảo vệ bằng token và tên lấy từ đăng ký của giải.
- Sau khi server xác nhận thắng, bảng Round results hiển thị người thắng và lý do. New round giữ điểm/kết quả trước; reset match xóa điểm và kết quả của match đó.
- Panel tự làm mới mỗi 5 giây hoặc bấm Refresh.

Mặc định admin không có mật khẩu cho demo trên LAN tin cậy. Để bật mật khẩu, đặt **chỉ ở server**, rồi nhập vào ô Organizer password:

```powershell
$env:ADMIN_PASSWORD = 'your-organizer-password'
npm.cmd start
```

Linux/macOS:

```bash
ADMIN_PASSWORD='your-organizer-password' npm start
```

Có thể đặt `PORT=3001` hoặc `HOST=127.0.0.1` tương tự. Không thêm password vào HTML, JS, RuleSet, room state hay URL. API admin dùng bearer password; khi triển khai Internet dùng HTTPS và đặt mật khẩu. Không có OAuth, tài khoản hoặc bracket tự động trong V1.

## RuleSet

Các luật demo:

| RuleSet | Board | Quân mỗi người | Di chuyển | Thắng |
| --- | --- | --- | --- | --- |
| `standard-9x9` | 9×9 | 9: 3 Rock, 3 Paper, 3 Scissors | 1 bước, 8 hướng | P1 tới i9 / P2 tới a1; hoặc loại hết một loại |
| `demo-5x5` | 5×5 | 3: mỗi loại một quân, đội hình khác | 1 bước, 8 hướng | P1 tới e5 / P2 tới a1; hoặc loại hết một loại |

Engine và renderer nhận `config.board.rows`/`columns`. Cấu hình có thể dùng board chữ nhật, 7×7, 10×10, first player khác, số quân khác và loại quân mới. `config.beats` là danh sách loại có thể ăn; cùng loại luôn cản nhau. Quân mới không có SVG sẽ hiển thị symbol/tên rút gọn.

### Thêm hoặc sửa RuleSet

1. Copy một file trong `config/rules/`, sửa `id` (duy nhất), `name` và các trường cấu hình.
2. Sửa kích thước board, turn, movement, pieceTypes, beats, goals và startingPieces; không sửa engine.
3. Restart `npm start`; server tự nạp tất cả file `.json` trừ `index.json`.
4. Chọn luật mới ở trang chủ hoặc Admin. Room đã có giữ config lúc tạo; thay file chỉ áp dụng cho trận mới sau restart.
5. Nếu dùng HTTP host tĩnh, thêm tên file vào `config/rules/index.json` và reload trang.

```json
{
  "movement": {
    "maxSteps": 2,
    "directions": [[-1,0], [1,0], [0,-1], [0,1]]
  }
}
```

Đây là phần cấu hình để thay trong RuleSet đầy đủ: tối đa hai bước, chỉ bốn hướng. Không cần sửa code. Quân không nhảy qua quân khác; chỉ ăn quân tại ô đích.

Validator chung kiểm tra rows/columns, first player, direction, số bước, loại quân, combat, goal, chủ quân, bounds và ô trùng. File lỗi được bỏ qua; console và Admin ghi rõ nguyên nhân, server vẫn chạy với config hợp lệ còn lại. Nếu tất cả file lỗi, không thể tạo trận cho đến khi sửa/restart.

### Các giả định và giới hạn V1

- Có hai vai trò cố định P1/P2. RuleSet thay đổi luật của trận hai người.
- Tọa độ JSON bắt đầu từ 0; hàng 0 hiển thị phía dưới (rank 1). Cột sau z tiếp tục aa, ab…
- Hướng là unit vector [-1, 0, 1], không phải luật nhảy kiểu quân mã. `maxSteps` điều khiển khoảng cách trên hướng đó.
- Conditions được xét theo thứ tự `winConditions`; nếu cùng nước thỏa nhiều điều kiện, điều kiện đầu quyết định lý do thắng.
- Khi bật `eliminatePieceType`, mỗi người phải có ít nhất một quân của từng loại lúc bắt đầu. Khi bật `reachGoal`, mỗi người cần goal hợp lệ và không được bắt đầu trên goal của chính mình.
- Board giới hạn 1–100 hàng/cột, 1–32 loại quân, maxSteps 1–100 để tránh cấu hình quá lớn. Hai JSON demo giữ luật và đội hình rõ ràng cho thuyết trình.
- V1 chưa xử lý hòa, timeout lượt hay hết nước hợp lệ. Người chơi/người tổ chức có thể reset trong trường hợp bế tắc.
- Room/trận/kết quả dùng bộ nhớ; **restart server sẽ mất dữ liệu**. Room không có thành viên hết hạn sau 1 giờ; tối đa 500 room và 100 thành viên/room. Tournament Manager có store được inject để thay storage sau này.
- Người có invitation link có thể nhận ghế được phân công; đây là quyền theo link, chưa phải xác thực danh tính bằng tài khoản.

## Kiểm thử

```bash
npm test
npm run check
```

`npm test` dùng Node test runner: giữ nguyên tám test prototype, thêm config/engine/local/loader/room, HTTP admin và integration Socket.IO ba client. Các test chạy với port ngẫu nhiên, không cần Internet hoặc dịch vụ ngoài.

Kiểm tra browser tùy chọn cần Google Chrome cài sẵn; `playwright-core` chỉ là dev dependency, không tải browser:

```bash
npm run test:browser
```

Có thể dùng Chrome/Edge tương thích khác qua `BROWSER_PATH`. Windows:

```powershell
$env:BROWSER_PATH = 'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
npm.cmd run test:browser
```

Browser smoke kiểm tra local khi chặn mọi backend API và request Internet; board 5×5/9×9 và 7×7/10×10 trên viewport 390px; multiplayer ba context; reconnect; winner/round/reset; tạo giải và nhận kết quả. Screenshot nằm trong `test-results/` (không commit). Kiểm thử cùng laptop không thay thế việc mở URL LAN trên một thiết bị khác trong Wi-Fi thực tế.

## Kiến trúc và cấu trúc thư mục

```text
Frontend → LocalController → GameEngine ← RuleSet
Frontend → SocketController → Socket.IO → RoomManager → GameEngine
Organizer UI → Admin API → TournamentManager ← RoomManager results
```

```text
index.html / game.html / admin.html
css/                       Giao diện responsive kế thừa prototype
assets/pieces/             Sáu SVG cũ
js/                        UI, local/socket controllers, config loader, admin
config/rules/              JSON luật và danh mục cho host tĩnh
src/engine/                Engine thuần: state, rules, coordinates, GameEngine
src/engine/winConditions/  Các module thắng
src/config/                Validator dùng chung và Node rule loader
src/server/                Express app, room/socket/tournament/admin managers
scripts/                   Syntax check và browser smoke
tests/                     Node unit/integration tests
server.js                  Startup, host/port, in URL local/LAN
```

Frontend giữ ở vị trí cũ để giảm migration. Express chỉ serve các thư mục cho phép; không serve repo root, backend, `.git` hoặc `.env`. Engine không biết DOM, Socket.IO, filesystem hay database. Local và server gọi cùng một implementation luật. `js/state.js`, `js/rules.js`, `js/constants.js` giữ API/default chuẩn cho test/caller cũ; frontend mới dùng config trực tiếp.

Audit A/B/C, quyết định giữ/refactor từng file và kiểm tra mỗi phase ở [docs/MIGRATION.md](docs/MIGRATION.md).

Tài liệu nền: [Socket.IO với Express](https://socket.io/docs/v4/server-initialization/), [phục vụ file tĩnh bằng Express](https://expressjs.com/en/starter/static-files/).

## Demo thuyết trình

1. Ngon bổ rẻ: `npm start`, dùng URL LAN trên hai thiết bị cùng Wi-Fi, mở thêm spectator.
2. Linh hoạt: tạo local/room với `standard-9x9`, rồi `demo-5x5`; board và đội hình đổi mà engine không sửa.
3. Tournament: thêm hai người ở Admin, mở các invitation và cho thấy kết quả server cập nhật.
4. Mở rộng: giải thích laptop và VPS dùng cùng server; chỉ thêm persistence/adapter khi thực sự cần nhiều tiến trình.

MIT — xem [LICENSE](LICENSE).
