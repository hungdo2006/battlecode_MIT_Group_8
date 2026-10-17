# Phase 3.1 — Premium Liquid Glass

Đây là báo cáo baseline Phase 3.1. Xem [Final visual refinement](FINAL_GLASS_REFINEMENT.md)
cho vật liệu và ảnh mới nhất; các thông số/ảnh bên dưới ghi lại bản trước refinement.

Triển khai trên `feature/product-polish`, tinh chỉnh frontend Liquid Light hiện có.
Không commit, push hoặc merge. Không đổi backend, HTTP/WebSocket protocol,
Game Adapter, Canvas renderer, runner/controller, Compose hoặc dữ liệu ứng dụng.
Dockerfile chỉ thêm bước tạo phiên bản asset khi build.

## Nguồn thiết kế và giới hạn

Nguồn sử dụng trong phiên Codex này là toàn bộ
[NEON_ARENA_FIGMA_LIQUID_GLASS_BRIEF.md](NEON_ARENA_FIGMA_LIQUID_GLASS_BRIEF.md).
Không gọi Figma MCP và không khẳng định đã trực tiếp đọc file Figma.

Theo tài liệu do chủ dự án cung cấp, ChatGPT đã đọc metadata trang `0:1`, cover
`1:637` (1920×1080), nhóm tiêu đề `3:6`, hai image layer `1:700`/`1:701`, và xem
screenshot cover của file `QLGOIP3ncS6kWTQt0LImTL`. Variable definitions trả `{}`.
Đây là bằng chứng được tài liệu ghi lại; Codex không xác minh độc lập dữ liệu đó.

Các đặc điểm được tài liệu mô tả là quan sát từ Figma: nền xám sáng, geometry bo
tròn, media surface tối trong suốt trên nền ảnh, thanh navigation dạng pill mờ và
các lớp nội dung có chiều sâu. Không có bộ dashboard desktop hay token đo đạc.

Các giá trị dưới đây là **đề xuất/thích nghi cho NEON ARENA**, không phải token Figma:

| Thành phần | Giá trị triển khai |
|---|---|
| Nền / text / secondary | `#f4f7fc` / `#172238` / `#596b85` |
| Accent giữ từ Liquid Light | `#2868d8`, xanh/amber cho hai phía |
| Kính standard | trắng 68%, blur 18px, saturation 145% |
| Kính subtle | trắng 80%, blur 10px |
| Kính elevated | trắng 84%, blur 22px |
| Viền / viền dưới phía trong | trắng 88% / xanh xám 10% |
| Radius control / card / floating | 13 / 22 / 26px |
| Motion | 160 / 240ms, giữ reduced-motion |

Không sao chép bố cục iPhone, wallpaper, biểu tượng hoặc font độc quyền của Apple.
Giữ sidebar desktop, Canvas lớn, các form và danh sách có cấu trúc như trước.

## Thay đổi UI

- `.glass-surface`, `.glass-subtle`, `.glass-elevated` dùng chung token và reflection
  dạng CSS gradient. Không thêm lớp phủ chặn thao tác, tracking con trỏ hoặc shader.
- Sidebar và header nổi trên nền pastel tiết chế; nav đang chọn có viền sáng và bóng nhẹ.
  Ở chiều rộng không quá 900px, navigation chuyển lên đầu trang để dành chỗ cho nội dung;
  các viewport desktop 1366/1440/1920px giữ sidebar bên trái.
- Overview: các thẻ thống kê và tile minh họa trong suốt, có depth; số liệu vẫn từ API.
- Submission và Organizer: outer frame kính, phần nhập liệu bên trong đặc. Compiler
  output, hướng dẫn và lịch sử vẫn là bề mặt chắc để đọc được văn bản dài.
- Lobby: player rows nổi nhẹ; invitation/confirmation giữ native dialog và keyboard flow.
- SETUP, OPEN, DRAINING có nhãn chữ cùng màu trạng thái; readonly/disabled do logic cũ quyết định.
- Arena: hai thẻ đấu thủ tách nền nhẹ. Canvas không blur, không thay thuật toán vẽ.
  Replay transport có kính và khoảng cách với bàn chơi, không đè lên nội dung game.
- Không lồng các phần tử blur. Browser thiếu backdrop-filter dùng nền trắng;
  `prefers-reduced-transparency: reduce` cũng chọn nền đặc và tắt blur.

## File của Phase 3.1

| File | Mục đích |
|---|---|
| `frontend/styles.css` | Token vật liệu, reflection, depth, floating surfaces và breakpoint hẹp |
| `frontend/index.html` | Gắn class vật liệu vào UI hiện có, giữ ID và binding |
| `frontend/app.js` | Toast giữ lại class vật liệu khi cập nhật success/error |
| `frontend/lan.html`, `frontend/protocol.html` | URL stylesheet/favicon có fingerprint |
| `scripts/version_frontend.py` | Tạo/kiểm tra phiên bản asset bằng nội dung |
| `Dockerfile` | Chạy bước fingerprint khi build image |
| `scripts/check_liquid_glass.py` | Tái dùng regression cũ, thêm kiểm tra material/cache/viewport |
| `README.md`, tài liệu này và thư mục ảnh | Hướng dẫn, provenance và bằng chứng thực tế |

Các thay đổi Phase 3 đã có trước trong working tree được giữ nguyên. Phase 3.1
không chỉnh thêm `frontend/renderers.js`, `favicon.svg` hoặc các checker cũ.

## Cache và Docker

`scripts/version_frontend.py` tính 12 ký tự đầu SHA-256 của CSS, hai JS và favicon,
gắn `?v=HASH` cho các URL trong cả ba trang HTML. Dockerfile chạy script sau khi
copy frontend, nên mỗi image tham chiếu đúng asset của nó. Native development
chạy script sau khi sửa asset. Không thay đổi cache headers toàn ứng dụng; giữ
ETag/Last-Modified và khả năng trả 304 của StaticFiles.

```powershell
# Dùng cấu hình .env đã có; không cần sinh lại token hoặc đổi credentials.
docker compose up --build -d --wait
docker compose logs --tail 50 arena
Invoke-RestMethod http://localhost:8000/api/health
```

Mở `http://localhost:8000`, hoặc địa chỉ LAN của server. Tab đã mở cần reload bình
thường để lấy HTML mới; trang đang mở không tự thay stylesheet giữa phiên.
Nếu đổi port bằng cấu hình hiện có, dùng port đó. Linux dùng `python3` cho các lệnh Python.

```powershell
# Sau khi sửa CSS/JS/SVG trong chế độ native:
.\.venv\Scripts\python.exe scripts/version_frontend.py
.\.venv\Scripts\python.exe scripts/version_frontend.py --check

# Kiểm tra real Docker sandbox + Chrome; dữ liệu/volume/project riêng:
.\.venv\Scripts\python.exe scripts/check_liquid_glass.py
# Chỉ dùng --no-build khi image khớp source hiện tại.
```

## Ảnh trước/sau và kiểm thử

Ảnh baseline được chụp trong lượt này từ Docker image có CSS trùng source trước
chỉnh sửa; 1440×900, session và dữ liệu QA riêng. Ảnh sau cũng từ ứng dụng/Docker
thật, không dùng ảnh thiết kế để giả UI hoặc thay response API. Dữ liệu giữa hai
lần chụp có thể khác vì checker tạo submission/trận thực.

| Màn hình | Trước | Sau |
|---|---|---|
| Overview | [Ảnh trước](screenshots/liquid-glass/before/overview.png) | [Ảnh sau](screenshots/liquid-glass/after/overview.png) |
| Submission | [Ảnh trước](screenshots/liquid-glass/before/submission.png) | [Ảnh sau](screenshots/liquid-glass/after/submission.png) |
| Lobby | [Ảnh trước](screenshots/liquid-glass/before/lobby.png) | [Ảnh sau](screenshots/liquid-glass/after/lobby.png) |
| Organizer | [Ảnh trước](screenshots/liquid-glass/before/organizer.png) | [Ảnh sau](screenshots/liquid-glass/after/organizer.png) |
| Access dialog | [Ảnh trước](screenshots/liquid-glass/before/organizer-dialog.png) | [Ảnh sau](screenshots/liquid-glass/after/organizer-dialog.png) |

Arena/replay: [Robot Battle 1440](screenshots/liquid-glass/after/arena-robot_battle-1440.png),
[OTT v2 1440](screenshots/liquid-glass/after/arena-ott_v2-1440.png),
[Robot Battle 1366](screenshots/liquid-glass/after/arena-robot_battle-1366.png).
Ảnh Arena trước nằm trong [bằng chứng Phase 3](LIQUID_LIGHT_VERIFICATION.md),
không phải cặp chụp cùng dữ liệu/viewport với lượt Phase 3.1.

Kết quả QA máy đọc được: [verification.json](screenshots/liquid-glass/verification.json).
Ảnh [submission với Active Bot và compiler diagnostics thật](screenshots/liquid-glass/after/submission-ready.png)
được giữ riêng với ảnh submission của session mới dùng cho so sánh trước/sau.

## Kết quả thực tế ngày 15/10/2026

Đã chạy:

```powershell
.\.venv\Scripts\python.exe -m pytest -o addopts='' -q
node --check frontend/app.js
node --check frontend/renderers.js
.\.venv\Scripts\python.exe scripts/version_frontend.py --check
.\.venv\Scripts\python.exe scripts/check_docker.py
.\.venv\Scripts\python.exe scripts/check_liquid_glass.py
git diff --check
```

- Pytest: **159 passed**, 1 warning có sẵn của Starlette/httpx, 83.26 giây.
  Baseline trước khi chỉnh frontend cũng chạy hết không có failure/skip.
- Node syntax và asset fingerprint check: PASS. `git diff --check` không có lỗi;
  chỉ có thông báo Git chuyển LF sang CRLF cho hai file đã sửa từ Phase 3.
- Docker regression project `neon-arena-qa-db78c81a51`: 6 trận hoàn thành, không bot
  fault, mỗi trận kiểm tra ba WebSocket với replay. Python/C++/Java dùng sandbox thật.

| Game | A / B | Match ID | Frames |
|---|---|---|---:|
| Robot | Python / C++ | `4723bfa5b27a434a` | 10 |
| Robot | C++ / Java | `d0b57d38ef884727` | 11 |
| Robot | Python / Java | `15bc700c7a934bf5` | 10 |
| OTT | Python / C++ | `9a778be11e414445` | 28 |
| OTT | C++ / Java | `77a68438623c40f7` | 28 |
| OTT | Python / Java | `9edc01ee0a6441db` | 28 |

- Restart backend/controller và down/up giữ sessions, settings, invitations,
  history, replay, source và artifacts. Artifact reuse PASS, backup tar mở kiểm
  tra được (247568 byte). QA thu hồi đúng project/volume riêng sau khi kết thúc.

Browser QA cuối: project `neon-arena-qa-bc031bab91`, ảnh `after/` và
`verification.json` khớp bản CSS cuối `75cb05420f39`:

- Build và health/non-root/named-volume checks: PASS.
- Ba Chrome session/cookie độc lập, C++ vs Python qua UI: Robot `e35ccf9fa82b408f`
  (10 frames), OTT `bd12c274c72a49a2` (28 frames). Cả ba client nhận dữ liệu
  trùng replay, kết quả không có bot fault; Pause của một client độc lập.
- 13 nhóm regression Liquid Light cũ: PASS, gồm Organizer/session, dynamic rules,
  unsaved changes/Game Lock, upload thật, compiler lỗi thật, Active Bot,
  Accept/Decline, DRAINING, reconnect, replay seek/reset/speed/download và reduced motion.
- 4 nhóm material/cache bổ sung: PASS. Có transparency, reflection, blur đúng
  lớp; không có nested filter hoặc blur trên Canvas/input/diagnostics. Reduced
  transparency chọn nền trắng và tắt filter thực sự trong Chrome.
- 35 route/viewport Player checks cũ + 44 Organizer/Player/replay checks mới =
  **79 lượt không tràn ngang**. Bao gồm 1920×1080, 1440×900, 1366×768, 768×1024;
  checker cũ còn kiểm tra 1440×1000, 1024×768, 390×844 và 320×740.
- HTML của `/`, `/lan`, `/static/protocol.html` tham chiếu đúng hash; CSS/JS/SVG
  trong container trùng byte source; conditional request trả 304, không ép no-store.
- **0 JavaScript errors**. Node syntax và `git diff --check`: PASS.
- Đã xem ảnh thực tế Overview, Organizer, Submission, access dialog, OTT Arena
  và layout 768px. Sau lần review đầu, breakpoint chuyển navigation lên đầu ở
  768px; browser suite được build/chạy lại toàn bộ cho bản cuối.

Chỉ browser QA và Docker regression thay dữ liệu QA; không restart hay chạy bài
test ghi dữ liệu vào server chính ở port 8000. Các resource QA đã được dọn riêng.

## Giới hạn

Thiết kế theo brief, chưa đối chiếu trực tiếp screenshot Figma trong Codex; không
tuyên bố pixel-perfect. Kiểm tra browser dùng Chrome trên Windows và Linux Docker
Desktop, không phải Safari hoặc hai laptop vật lý. Fallback/reduced-transparency
không tạo hiệu ứng khúc xạ quang học: đây là material CSS nhẹ, phù hợp đồ án.
Không có đánh giá bảo mật sandbox mới trong một thay đổi frontend.
