# Final visual refinement — Liquid Glass

Nhánh `feature/product-polish`. Tinh chỉnh tiếp từ Phase 3.1; không đổi cấu trúc
điều hướng, dữ liệu, backend, WebSocket, Game Adapter, renderer hoặc Docker sandbox.
Không commit, push hoặc merge.

## Audit và thay đổi

Hai nguyên nhân khiến bản trước còn đặc/phẳng: lớp reflection phủ thêm lượng
trắng lớn trên vật liệu vốn đã có opacity 68–84%; phần lớn form/list bên trong
lại dùng toàn bộ nền trắng. Session chưa có lớp vật liệu riêng, Arena có ít
khoảng tách giữa stage và frame.

Lượt này thay đổi chủ yếu CSS, không đổi event handler hoặc binding:

- Standard glass trắng **42%**, blur **24px**, saturation **150%**. Header dùng
  16px, competition banner 20px, replay transport 18px.
- Subtle sheet trắng **54%**, **không dùng backdrop-filter**. Stats, session,
  outer form, thông tin game và các tile dùng lớp này thay vì thêm blur toàn trang.
- Elevated glass trắng **70%**, shadow lớn hơn cho native dialog và toast.
- Reflection nhẹ hơn ở giữa bề mặt; viền trên/phía trái sáng, viền dưới xanh xám
  rất nhẹ tạo cảm giác cạnh kính. Không có shader, pointer tracking hoặc animation
  nền liên tục; không mô phỏng khúc xạ vật lý.
- Background có các vùng sáng blue/lavender/mint và một dải sáng chéo rất mềm,
  trải theo chiều dài trang để màu nền thực sự hiện qua surface và ảnh full-page
  không có mép ngắt ở cuối viewport.
- Session thành floating sheet riêng. Navigation và active state rõ hơn.
  Competition giữ nhãn SETUP/OPEN/DRAINING bằng chữ cùng nền màu riêng.
- Form frame, upload zone, player/game cards và selection cards cho nền xuyên qua
  nhiều hơn. Input, compiler log và các vùng dữ liệu dài vẫn có nền đọc ổn định.
- Arena có frame kính và inset 8px; stage Canvas giữ nền đặc, không blur, không
  lớp kính phủ lên quân/robot. Thanh replay nằm dưới stage.
- History, submission library và event log có lớp đọc trắng 86% phía trong frame;
  không dùng blur trên từng dòng dữ liệu.
- Text phụ được đậm hơn (`#50627c` / `#566982`), giữ màu primary và blue/amber.
  Focus, reduced motion, responsive breakpoint và workflow giữ nguyên.

Đây là các thông số thiết kế thích nghi cho NEON ARENA. Không đọc Figma MCP trong
phiên này, không khẳng định thông số được đo từ Figma. Nguồn định hướng tiếp nối
[brief của chủ dự án](NEON_ARENA_FIGMA_LIQUID_GLASS_BRIEF.md).

## File thay đổi trong lượt refinement

| File | Thay đổi |
|---|---|
| `frontend/styles.css` | Token vật liệu, reflection, shadow, background và surface các màn hình |
| `frontend/index.html` | Gắn material vào session; header có blur riêng, hero tile dùng sheet không blur; URL CSS mới |
| `frontend/lan.html`, `frontend/protocol.html` | Cập nhật fingerprint CSS |
| `scripts/check_liquid_glass.py` | Output directory riêng; kiểm tra contrast bằng pixel ảnh thật, giới hạn số lớp blur |
| `README.md`, tài liệu này, `docs/LIQUID_GLASS.md` | Hướng dẫn và liên kết bằng chứng |

Các file đang modified từ các phase trước được giữ nguyên; không có sửa thêm
`app.js`, `renderers.js`, Dockerfile/Compose, dependency hoặc credentials trong lượt này.

## Chạy và kiểm tra cache

```powershell
docker compose up --build -d --wait
```

Mở `http://localhost:8000` hoặc URL LAN/port đã cấu hình, reload trang bình thường.
Giữ cơ chế SHA-256 asset versioning của Phase 3.1; không tắt cache hoặc yêu cầu
xóa cache Chrome. Tab đang mở không tự thay CSS cho tới khi reload.

```powershell
.\.venv\Scripts\python.exe scripts/version_frontend.py --check
.\.venv\Scripts\python.exe -m pytest -o addopts='' -q
.\.venv\Scripts\python.exe scripts/check_liquid_glass.py --output-dir docs/screenshots/glass-refinement/after
```

Checker dùng project/volume/token/session QA riêng, không ghi dữ liệu server chính.
Sau khi kết thúc, thu hồi đúng resource QA. Server chính không được tự restart
trong lượt visual QA này.

## Ảnh trước/sau

Ảnh trước giữ từ browser QA Phase 3.1, không tạo bằng mockup. Trước khi copy,
đã xác minh CSS hiện tại có hash `75cb05420f39`, trùng bản tạo các ảnh đó.
Ảnh sau được tạo từ Docker và Chrome thực trong lượt refinement này. Dữ liệu
trận/bot có thể khác do hai lần QA độc lập.

| Màn hình | Trước | Sau |
|---|---|---|
| Overview | [Trước](screenshots/glass-refinement/before/overview.png) | [Sau](screenshots/glass-refinement/after/overview.png) |
| Submission/Active Bot | [Trước](screenshots/glass-refinement/before/submission-ready.png) | [Sau](screenshots/glass-refinement/after/submission-ready.png) |
| Lobby | [Trước](screenshots/glass-refinement/before/lobby.png) | [Sau](screenshots/glass-refinement/after/lobby.png) |
| Organizer | [Trước](screenshots/glass-refinement/before/organizer.png) | [Sau](screenshots/glass-refinement/after/organizer.png) |
| Arena/Replay | [Trước](screenshots/glass-refinement/before/arena-ott_v2-1440.png) | [Sau](screenshots/glass-refinement/after/arena-ott_v2-1440.png) |
| History | [Trước](screenshots/glass-refinement/before/history.png) | [Sau](screenshots/glass-refinement/after/history.png) |
| Dialog | [Trước](screenshots/glass-refinement/before/organizer-dialog.png) | [Sau](screenshots/glass-refinement/after/organizer-dialog.png) |

Bằng chứng máy đọc được: [verification.json](screenshots/glass-refinement/verification.json).

## Kết quả kiểm thử thực tế

Ngày 15/10/2026, Windows + Chrome headless + Docker Desktop Linux containers:

| Lệnh/kiểm tra | Kết quả |
|---|---|
| `python -m pytest -o addopts='' -q` | **159 passed**, 1 warning Starlette/httpx có sẵn, 71.88s |
| `node --check frontend/app.js` và `renderers.js` | PASS |
| `python scripts/version_frontend.py --check` | PASS |
| `python -m py_compile scripts/check_liquid_glass.py` | PASS |
| Build + real Docker browser QA | PASS |
| `git diff --check` | PASS; cảnh báo LF/CRLF của favicon có sẵn |

Browser QA cuối chạy project `neon-arena-qa-5a2c9b91e2`, CSS hash
`24fe06cdf1f3`. Có hai trận C++/Python thật qua UI, ba cookie session độc lập:

- Robot Battle `0f9847898a2a45db`: 10 frames, B thắng knockout, không bot fault.
- OTT v2 `71e44a0eb7064f09`: 28 frames, A thắng series 2–0, không bot fault.
- Ba WebSocket stream trùng replay; Pause của một client không dừng client khác.
- 13 nhóm regression cũ PASS: Organizer/session, luật động, Game Lock, upload và
  lỗi compiler thật, Active Bot, invitation/Accept/Decline, DRAINING, reconnect,
  replay seek/reset/speed/download, reduced motion và responsive.
- 6 nhóm bổ sung PASS: asset/cache, material, contrast, reduced transparency,
  viewport Organizer/Player/replay và số lớp blur.
- **79 lượt kiểm tra route/viewport** không tràn ngang. Có 1920×1080, 1440×900,
  1366×768, 768×1024, thêm 1440×1000, 1024×768, 390×844, 320×740 từ checker cũ.
- **0 JavaScript errors**. Asset CSS/JS/SVG đang phục vụ trong container trùng byte
  source; HTML ba trang tham chiếu đúng hash; conditional request trả **304**.
- Contrast ba mẫu chữ phụ đo với pixel nền thực: stat label **5.84:1**, session ID
  **5.28:1**, competition message **5.71:1**. Không tuyên bố đây là audit WCAG toàn app.
- Tối đa **4 surface dùng backdrop-filter** nằm trong viewport trên các route
  được kiểm tra khi không mở modal. Sheet subtle không blur, Canvas/input/log không blur.
- Đã xem ảnh Overview, Submission, Lobby, Organizer, cả hai board/replay, history,
  dialog và layout 768px; sửa nền sau lần review đầu, build/chạy lại browser suite.

Một trận hai bot `wait` được hủy chủ đích để kiểm tra DRAINING và giải phóng QA;
nhãn Gián đoạn trong ảnh lịch sử thuộc kịch bản đó. Không có dữ liệu game giả.
Resource QA được dọn sau khi chạy; không thay `.env` hay dữ liệu server chính.
Java không có trận Docker mới trong lượt CSS này; regression đa ngôn ngữ Docker
đầy đủ của Phase 3.1 được giữ trong [báo cáo trước](LIQUID_GLASS.md).

## Giới hạn

Hiệu ứng là vật liệu CSS, không phải khúc xạ vật lý. Giới hạn blur theo lớp và
không thêm animation nền giúp giữ chi phí vừa phải, nhưng không thay thế benchmark
FPS trên laptop yếu. Kiểm chứng browser bằng Chrome; không tuyên bố đã kiểm tra
Safari hoặc hai laptop vật lý. Reduced transparency dùng nền đặc; không đo được
mọi tổ hợp text/background chỉ bằng vài mẫu contrast.
