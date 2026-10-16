# NEON ARENA v4.0 — Phase 3 Liquid Light

Phase 3 thay ngôn ngữ hình ảnh Cyberpunk bằng giao diện sáng, nhẹ và nhất quán.
Giữ HTML/CSS/JavaScript thuần, không thêm framework, font/CDN hoặc thư viện UI.
Các icon/SVG là artwork của dự án, không sử dụng nhận diện Apple.

## Design system

Các token ở đầu `frontend/styles.css`:

| Nhóm | Giá trị/chủ đích |
|---|---|
| Nền | `--bg: #f6f8fc`, gradient pastel rất nhẹ |
| Nội dung | `--surface: #fff`, `--surface-soft: #f8fafc` |
| Chữ | `--text: #172033`, `--muted: #606f85`, `--subtle: #637187` |
| Action chính | `--accent: #2868d8`, hover `#1f55b7` |
| Hai bên thi đấu | A xanh `#2867cc`, B amber `#a66125`, luôn có nhãn A/B |
| Semantic | Success `#227552`, warning `#956020`, error `#b4404e` |
| Typography | System stack: Apple system/BlinkMacSystemFont/Segoe UI/sans-serif |
| Code | ui-monospace/Cascadia Code/Consolas/monospace |
| Radius | 10/18/24/30px |
| Spacing | 4/8/12/16/24/32px |
| Elevation | Shadow nhẹ cho card, shadow nổi cho sidebar/dialog/toast |
| Motion | 160/240ms, `prefers-reduced-motion` |

Bốn mức bề mặt:

1. Background: sáng, gradient tĩnh; không scanline/glitch.
2. Glass: sidebar trong mờ với viền trắng và phản chiếu nhẹ.
3. Elevated: dialog/toast nổi, backdrop mờ có chọn lọc.
4. Solid: form, code, danh sách và Canvas, không blur lên quân hoặc ô quan trọng.

Mặc định sidebar/dialog/toast có nền đặc. `@supports` mới bật backdrop-filter;
không yêu cầu trình duyệt hỗ trợ blur để đọc và thao tác. Không áp blur lên mọi card.

## Các khu vực đã làm mới

- Shell: sidebar nổi, icon cùng hệ, breadcrumb, role/identity, focus rõ, skip link,
  điều hướng ngang trên màn hình nhỏ; giữ các URL hash và đường dẫn LAN/API/docs.
- Overview: hero artwork SVG mới, typography thoáng, thống kê từ API và trạng thái
  cuộc thi. Khi xem trận, hero/statistics thu gọn để ưu tiên Arena.
- Organizer: game cards, dynamic rules, thông báo SETUP/OPEN/DRAINING. Luật đã sửa
  nhưng chưa lưu chặn nút mở cuộc thi ở UI và giải thích lý do. Backend vẫn xác minh
  quyền/khóa độc lập như Phase 2.
- Submission: drag-and-drop File thật, nhãn ngôn ngữ/kích thước, pending state khi
  HTTP upload/compile chưa xong, kết quả thật và compiler diagnostics có thể mở rộng.
- Lobby: trạng thái bằng chữ + biểu tượng, Active Bot, online/ready, lời mời và dialog
  Accept/Decline; hai phía xanh/amber thống nhất với bàn chơi.
- Arena/replay: nền bàn đặc sáng, font tọa độ rõ hơn, bỏ neon/scanline; giữ nguyên
  geometry, nội suy di chuyển, animation ăn quân/tấn công, renderer registry và HUD
  từ frame. Giữ Play/Pause/Reset, seek, speed, share và download JSON.
- History, toast, feedback, confirm dialog, trang LAN và protocol dùng cùng palette.

## Các lỗi UX được xử lý

- Polling có thể bật lại nút upload/seed/active trong lúc request còn chờ: dùng busy
  state riêng và guard handler. Không mô phỏng phần trăm hoặc giai đoạn compile mà
  server chưa cung cấp.
- Polling làm mất focus ở danh sách và đóng compiler diagnostics: giữ focus key và
  trạng thái details khi cập nhật DOM.
- Không có xác nhận trước khi đóng cuộc thi/reset luật/hủy lời mời: dùng native
  dialog, Escape/Quay lại không gửi mutation.
- Nhãn Pause cũ luôn nói backend tiếp tục, kể cả replay đã xong: phân biệt live và
  replay theo metadata thật.
- Mất WebSocket không có trạng thái rõ: hiển thị reconnect notice và nút thử lại,
  giữ các frames đã nhận. Không đổi protocol, sequence hoặc endpoint.
- Tránh gán lại nội dung aria-live khi status không đổi để giảm thông báo lặp.

## Phạm vi file

- `frontend/index.html`: cấu trúc shell, nội dung, icon sprite và confirm dialog.
- `frontend/styles.css`: thay style cũ bằng design system Liquid Light.
- `frontend/app.js`: trạng thái hiển thị/busy, validation, confirm, focus/reconnect UX.
- `frontend/renderers.js`: palette, font, bỏ hiệu ứng nền Cyberpunk; không đổi luật.
- `frontend/favicon.svg`, `frontend/lan.html`, `frontend/protocol.html`: đồng bộ giao diện.
- `scripts/check_multiplayer_ui.py`: theo navigation/labels mới và confirmation.
- `scripts/check_liquid_ui.py`: QA bổ sung trên Docker sandbox thật.
- `README.md`, tài liệu này và ảnh thực tế trong `docs/screenshots/liquid-light/`.

Không sửa backend, Game Adapter/Engine, controller, Dockerfiles, Compose, protocol
bot, replay format hoặc persistent storage.

## Chạy ứng dụng

Windows Docker Desktop: Linux containers/WSL2, trong thư mục repository:

```powershell
py -3 scripts/configure_sandbox.py
docker compose up --build -d --wait
Invoke-RestMethod http://localhost:8000/api/health
```

Mở `http://localhost:8000`, các máy LAN dùng IPv4 của server. `.env` vẫn riêng tư,
không đổi token/code hiện có. Health phải là sandbox/ready như Phase 2. Chờ trận
kết thúc trước khi cập nhật container đang phục vụ demo. Nếu còn CSS cũ, dùng Ctrl+F5.
`start.bat` vẫn là legacy dành cho code tin cậy, không phải Docker sandbox.

## Chạy kiểm thử UI

Host cần requirements-dev, Playwright và Chrome; không thêm dependency cho người
dùng ứng dụng. Script QA tạo token/project/volume riêng, không dùng dữ liệu thật:

```powershell
py -3 -m pytest -o addopts="" -q
node --check frontend/app.js
node --check frontend/renderers.js
py -3 scripts/check_liquid_ui.py
```

`--no-build` chỉ dùng khi image đã build từ source hiện tại. QA chạy ba cookie
session, compile trong Docker, hai game và WebSocket/replay thật. Một upload được
trì hoãn ở lớp vận chuyển3s để kiểm tra chống gửi trùng qua polling; response vẫn
là kết quả thật từ server. Không thay game state hoặc trả API giả.

Kiểm tra mở rộng gồm contrast quan trọng, keyboard/dialog, game lock, hai schema,
reset cancellation, file sai, compile lỗi, drag-drop, Active Bot, Decline,
DRAINING từ trận đang chạy thật, replay download/seek/reset/speed, offline/reconnect,
reduced motion và35 tổ hợp route/viewport từ320 đến1920px. Tài nguyên QA được dọn
sau kiểm thử; screenshots được giữ lại để xem.

## Hạn chế

Chrome desktop được ưu tiên. Chưa xác nhận Safari/Firefox, thiết bị điện thoại thật,
screen reader hoặc máy chiếu vật lý. Các kiểm tra contrast quan trọng không thay
thế audit WCAG đầy đủ. Fallback blur có trong CSS; chưa có máy GPU yếu để đo FPS
hoặc kiểm thử phần cứng không hỗ trợ backdrop-filter. Canvas là trình mô phỏng bot,
không phải bàn chơi điều khiển bằng bàn phím; có nhật ký văn bản đi kèm.

An toàn thực thi code vẫn theo [Phase 2](SANDBOX.md): controller có Docker Engine
access rất mạnh, container không phải ranh giới an toàn tuyệt đối; chỉ demo trong
mạng tin cậy. Phase 3 không thay đổi hoặc nâng mức bảo đảm sandbox.
