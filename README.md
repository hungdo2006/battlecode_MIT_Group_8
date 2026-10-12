# NEON ARENA

Nền tảng thi đấu bot đa game dành cho bài tập nhóm môn Lập trình mạng. Hiện hỗ trợ **Robot Battle** và **OTT v2**, đăng ký qua **GameRegistry + GameAdapter**. Backend **Python FastAPI**, frontend **HTML/CSS/JavaScript thuần + Canvas**, giao tiếp **HTTP REST + WebSocket**, bot **subprocess**, dữ liệu **JSON**. Không cần Docker, Node.js hoặc database server để chạy ứng dụng.

Hỗ trợ nhiều người chơi LAN với **cookie phiên/nickname**, owner cho submission, người tạo trận và danh sách chung tự cập nhật. **Organizer chọn và khóa một game cùng snapshot luật cho cuộc thi duy nhất**; mọi Player nhận cập nhật qua WebSocket. Replay ghi nối từng frame. Xem [kiểm chứng Game Lock v2.3](docs/COMPETITION_VERIFICATION.md), [hướng dẫn networking](docs/NETWORKING.md); trang hướng dẫn trong app ở `/lan`.

> **Chỉ dùng local/LAN riêng với code tin cậy của nhóm.** Subprocess không phải sandbox. Bot có quyền của tài khoản chạy server, có thể đọc/ghi file, truy cập mạng hoặc tạo tiến trình khác. Giới hạn timeout/output không ngăn được các hành vi đó. Không công khai tính năng thực thi code lên Internet.

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

## Hai máy cùng LAN

1. Laptop host chạy `start.bat`, giữ server hoạt động và tránh sleep.
2. Xem URL LAN trong console hoặc dùng `ipconfig` để tìm IPv4 của adapter Wi-Fi/Ethernet. Ví dụ **`http://192.168.2.16:8000`**; dùng IP thực của host, không dùng `0.0.0.0` hoặc `127.0.0.1` trên máy khách.
3. Máy/điện thoại khác cùng Wi-Fi mở URL LAN đó. Nếu Windows hỏi quyền mạng, cho phép Python trên mạng **Private**. Kiểm tra firewall TCP 8000 và Wi-Fi không bật client isolation nếu kết nối bị chặn.
4. Mỗi máy đặt nickname ở **YOUR PLAYER SESSION**. Organizer chọn game, lưu luật và **LOCK GAME / OPEN COMPETITION**; mọi Player tự nhận game/luật đã chốt. Mỗi người nộp source phù hợp. Thư viện chung tự cập nhật mỗi 2 giây.
5. Một người tạo trận. Người còn lại tìm ID/tên bot trong **Xem trận đấu** rồi nhấn Live, hoặc mở URL `http://IP-HOST:8000/?match=ID#home`. Mỗi browser subscribe riêng tới cùng WebSocket; Pause chỉ ảnh hưởng playback của browser đó.
6. Khi dùng nút chia sẻ, mở tab bằng URL LAN trước để link được sao chép dùng địa chỉ LAN. Trong app có **Hướng dẫn LAN** gồm IPv4, firewall Private/LocalSubnet và xử lý Wi-Fi isolation.

Frontend dùng đường dẫn HTTP tương đối và `location.host` cho WebSocket, không cố định địa chỉ server. Không cần Internet khi chạy LAN sau khi đã cài dependency. Kiểm chứng tự động hai spectator:

```powershell
.\.venv\Scripts\python.exe scripts/check_lan.py --url http://IP-HOST:8000 --game ott_v2
```

Script dùng hai cookie jar/nickname riêng, mỗi client upload một source Python/C++ (có thể `--language-b java`), B tìm trận A tạo, so hai stream với replay và reconnect. Có thể chạy từ laptop khác hoặc host; hai client trên một máy không thay thế nghiệm thu hai thiết bị vật lý. Kiểm thử Chrome hai người nộp bot: `scripts/check_multiclient_ui.py --url http://IP-HOST:8000 --game robot_battle` (cần Playwright/Chrome).

Phiên tồn tại 30 ngày, được giữ qua restart; nickname là nhận diện trong nhóm, không phải tài khoản đăng nhập. Owner/name được lưu như snapshot tại thời điểm nộp/tạo trận. Mỗi người có cache sample riêng, vẫn compile một lần cho mỗi submission.

## Organizer và Player

Mọi browser bắt đầu **Player**, kể cả máy chủ. Player nộp bot cho game ban tổ chức chọn, tạo trận khi cuộc thi mở, xem live/replay. Chỉ **Organizer** chọn game, cấu hình luật và mở/đóng cuộc thi. Backend kiểm tra mọi đường API; không tin game/luật do client tự khai để vượt khóa.

Trước khi chạy server, trong PowerShell:

```powershell
$env:ARENA_ADMIN_CODE = Read-Host 'Nhap ma Organizer cho nhom'
.\start.bat
```

Dùng mã đủ dài, chỉ chia sẻ với ban tổ chức. Nhấn **Mở quyền Organizer**, nhập mã rồi xác minh. Mã đọc từ environment lúc startup, không hardcode frontend, không lưu vào JSON/localStorage và không chuyển vào compiler/bot. Rời Organizer hoặc restart thu hồi quyền; nickname/cookie và **trạng thái cuộc thi đã lưu** được giữ. Đổi mã cần restart. Thiếu mã: không mở được cuộc thi mới; nếu đã có cuộc thi khóa từ trước, Player vẫn đấu theo snapshot đó.

**Một cuộc thi, ba trạng thái:**

1. **SETUP / chờ ban tổ chức:** Organizer chọn game ở dropdown/card, lưu/reset luật. Mọi client theo game server chọn; không dùng lựa chọn localStorage cũ. Chưa tạo trận được. Có thể chuẩn bị/nộp bot, nhưng chỉ cho game hiện tại.
2. **LOCK GAME / OPEN COMPETITION:** server chốt `active_rules_snapshot` từ luật đã lưu, lưu khóa vào disk và phát WebSocket. Chỉ game đã khóa được nộp bot/tạo trận; cả hai bot phải tương thích. Không nhận `rules` override từ ai, kể cả Organizer. Form luật/game read-only. Giá trị chưa Save trên browser không đi vào snapshot.
3. **CLOSE COMPETITION / UNLOCK:** chặn trận mới ngay. Nếu còn trận/chờ/cleanup bot thì trạng thái **DRAINING**, chưa đổi game/luật hoặc mở lại được. Khi hết task, WebSocket tự báo SETUP. Có thể chờ kết thúc hoặc Organizer hủy hợp lệ qua `POST /api/matches/{id}/cancel`; cancel thu hồi bot, lưu interrupted/replay đã có rồi mới cho cấu hình lại.

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

1. Mở quyền Organizer, chọn Robot Battle hoặc OTT v2 ở thanh trên/Rules, lưu luật rồi nhấn **LOCK GAME / OPEN COMPETITION**. Player xem cùng game và luật đã chốt.
2. Trang chủ → **Thêm bot mẫu**. Server nộp/chuẩn bị Python, C++, Java cho game đó. Cùng source mẫu được dùng lại; khi source thay đổi, hash mới tạo submission mới, không âm thầm dùng executable cũ.
3. **Quick Deploy** hoặc **Tạo trận đấu** → chọn bot A/B → **Start Match**. Game lấy từ cuộc thi đang mở; dropdown chỉ hiển thị bot ready đúng game. Server từ chối request khác game hoặc override luật.
4. Quan sát renderer và **Combat Log**: Robot có HP/tia tấn công; OTT có bàn cờ, loại quân, nước đi, capture, ván và điểm. Trạng thái thật được server gửi qua WebSocket.
5. **Pause** chỉ dừng playback. Backend tiếp tục chạy và trạng thái mới tiếp tục được nhận/lưu. **Reset** về lượt 0 và tạm dừng; **Start (▶)** phát tiếp. Start ở cuối trận hoàn tất sẽ phát lại từ đầu.
6. Dùng thanh tua và tốc độ 0.5×–4×. **⇩** tải replay JSON; **↗** sao chép link. **Xem trận đấu** mở live hoặc phát replay không chạy lại bot.
7. Để thay luật/game: đóng cuộc thi, chờ trận và bot cleanup hoàn tất, sửa rồi khóa mở lại. Replay cũ giữ snapshot.
8. **Nộp bot** tự theo game ban tổ chức chọn, nhận `.py`, `.cpp`, `.java`, hiện lỗi biên dịch và chỉ dùng submission ready. Thư viện vẫn giữ bot các game trước.

Bot có thể đấu với chính submission đó: backend vẫn khởi chạy **hai tiến trình riêng biệt**.

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
│   ├── check_lan.py      # Hai phiên upload/discover/WS/reconnect qua LAN
│   ├── check_multiclient_ui.py # Chrome: hai người chơi dùng giao diện thật
│   └── check_ui.py       # QA tùy chọn với Chrome/Playwright
├── docs/                 # Ghi nhận kiểm chứng và ảnh giao diện
├── deploy/               # Mẫu Nginx HTTPS/WSS cho chế độ chỉ xem
├── data/                 # Tự tạo: bots.json, matches.json, rules.json, sessions.json, replays/
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
| GET | `/api/network` | Origin hiện tại, mode, URL IPv4 LAN gợi ý |
| GET | `/lan` | Trang hướng dẫn LAN/firewall/HTTPS |
| GET | `/api/games` | Registry: metadata, schema, luật đã lưu, preview thật và game đang chọn |
| PUT | `/api/games/selected` | Organizer chọn game tổ chức `{game_id}`, chỉ khi SETUP |
| GET | `/api/competition` | State đầy đủ: game, khóa, snapshot, phase, pending_matches |
| POST | `/api/competition/open` | Organizer khóa game và luật đã lưu, mở nhận trận |
| POST | `/api/competition/close` | Organizer chặn trận mới, chờ các task trước khi cho cấu hình |
| WS | `/ws/competition` | Initial/latest state, revision và heartbeat cho mọi client |
| GET | `/api/games/{game_id}` | Thông tin đầy đủ của một game |
| GET / PUT | `/api/games/{game_id}/rules` | Mọi người đọc; Organizer lưu chỉ khi SETUP |
| POST | `/api/games/{game_id}/rules/reset` | Organizer reset chỉ khi SETUP |
| GET / PUT | `/api/rules` | Alias luật của game đang tổ chức; PUT cần Organizer và SETUP |
| GET / POST | `/api/bots` | Danh sách / multipart `file`, `name`, `game_id` bắt buộc |
| GET | `/api/bots?game_id=ott_v2` | Lọc submission theo game |
| GET / POST | `/api/games/{game_id}/samples/{language}` / `.../submit` | Tải/nộp mẫu của game, language python/cpp/java |
| GET | `/api/samples/{python\|cpp\|java}` | Tải source bot mẫu |
| POST | `/api/samples/{language}/submit` | Nộp bot mẫu có sẵn |
| GET / POST | `/api/matches` | Lịch sử / tạo trận khi OPEN, đúng game; dùng snapshot server, không override rules |
| POST | `/api/matches/{id}/cancel` | Organizer hủy task đang chạy/chờ; thu hồi bot, giữ replay/history |
| GET | `/api/matches/{id}` | Metadata, luật, trạng thái, kết quả |
| GET | `/api/matches/{id}/replay` | Metadata + mảng `frames` JSON |
| WS | `/ws/matches/{id}?after=-1` | Subscribe từ sequence kế tiếp |

POST submission trả `201`, gồm ready/error và compiler logs; source lỗi vẫn lưu để xem. `403` khi thiếu quyền; `409` khi chưa mở, sai game khóa, sửa cấu hình khóa/còn task, hoặc override snapshot. Bot pair không tương thích trả `400`; thiếu/sai schema `422`; ID không có `404`. Swagger ở `/docs`.

```text
Browser -- HTTP upload --> FastAPI -- compiler --> uploads/<id>
Browser -- HTTP Start --> MatchManager
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

Các lệnh không cấu hình cần cuộc thi tương ứng đã mở. Dùng `--open-competition`, `--max-turns` hoặc `--rounds` để script xác minh Organizer bằng ARENA_ADMIN_CODE, đóng → chọn/lưu luật → khóa mở trước demo; không gửi per-match override nữa. Nếu còn trận chạy thì không đổi cấu hình. Script in action/kết quả và xác nhận WS khớp replay. Chạy theo cuộc thi đã mở không cần mã.

Kiểm thử gồm cả hai game, adapter thứ ba, hiệu lực cấu hình, snapshot/replay, nộp bot theo game, các trận khác ngôn ngữ và hai spectator. Có test đối chiếu engine Python với module luật JavaScript đã lưu từ repository OTT. Node chỉ dùng cho test đối chiếu; không cần để chạy ứng dụng. Xem [báo cáo v2 cùng ảnh giao diện](docs/MULTIGAME_VERIFICATION.md); [báo cáo v1](docs/VERIFICATION.md) được giữ làm lịch sử.

QA giao diện tùy chọn, cần Chrome đã cài:

```powershell
.\.venv\Scripts\python.exe -m pip install playwright
.\.venv\Scripts\python.exe scripts/check_ui.py
.\.venv\Scripts\python.exe scripts/check_ui.py --spectator-url http://IP-HOST:8000
```

Không cần `playwright install`: dùng Chrome có sẵn/headless. QA chỉnh luật cần đúng ARENA_ADMIN_CODE trong environment, không truyền mã trong CLI. check_ui kiểm tra Organizer unlock/logout, schema, luật thật, khóa read-only, bỏ draft chưa Save, hai game/upload/live/replay, defaults, hai contexts, 390px. check_multiclient_ui dùng Organizer fixture riêng và hai Player, kiểm tra open/close/draining/setup qua WS không reload, API bypass, tiếp tục xem replay sau đổi game. QA khôi phục cấu hình ban đầu; không phải dependency runtime.

## Gợi ý thuyết trình 5 phút

1. Giới thiệu REST cho upload/cấu hình/tạo trận, WebSocket cho trạng thái liên tục.
2. Nộp ba bot mẫu, chỉ ra giai đoạn biên dịch C++/Java và JSON stdin/stdout thống nhất.
3. Chạy Python vs C++, quan sát di chuyển/tấn công/HP; Pause chứng minh playback và backend độc lập.
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
