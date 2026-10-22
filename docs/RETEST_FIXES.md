# Khắc phục báo cáo kiểm thử lại NEON ARENA · 22/10/2026

Triển khai theo `kiem-thu-lai-neon-arena-sau-codex.md`. Thay đổi trong repository và kiểm tra trên server localhost với dữ liệu tạm; chưa triển khai production.

## Đối chiếu yêu cầu

| Mục | Thay đổi và bằng chứng |
| --- | --- |
| R01 | Logout, hết hạn phiên và đổi danh tính dọn match, frames, log, canvas, kết quả, playback, socket và timer; hủy request cũ. Mỗi request kiểm tra thế hệ phiên trước khi dùng response, kể cả response 401 cũ. Kiểm thử Admin mở replay → logout → Player trong cùng tab và response cũ trả về sau login mới. |
| R02–R03 | Replay có màn hình `#replay`, H1, breadcrumb, thông tin trận và hai liên kết quay lại. Tổng quan xóa replay đang xem. Dùng History API để Back/Forward hoạt động; link cũ có query replay và `#home` vẫn được nhận diện. Focus và cuộn đến H1 sau khi tải, có bù header. Gộp sự kiện popstate/hashchange để không làm mới dữ liệu hai lần. |
| R04 | Danh sách bot luôn ở ngoài disclosure nộp code/bot mẫu. CTA trên Tổng quan mở đúng đích và focus vào danh sách, không chọn bot. |
| R05–R06 | Trận tương lai, trận đang chạy và trận cần xử lý được phân loại riêng. Không có trận tương lai thì hiển thị thông báo rõ. CTA cảnh báo mở ngay danh sách có bộ lọc cần xử lý, nằm trước form tạo lịch; form đóng mặc định. |
| R07 | Trạng thái và lý do chặn được giải thích bằng tiếng Việt ở Official và chi tiết giải đấu. Mã kỹ thuật nằm trong disclosure. Không đoán đội thiếu bot khi response không cung cấp thông tin đó. Hướng dẫn đúng cơ chế hiện có: lịch BLOCKED không tự thử lại; Admin kiểm tra rồi hủy/xếp lịch mới. |
| R08 | Đối chiếu `OfficialSchedule.create`: `now <= bot_lock_at <= scheduled_at <= now + 365 ngày`. Form chưa chỉnh sửa nhận thời gian mới khi mở; giữ nguyên giá trị đã nhập. Kiểm tra khi nhập, khi thời gian trôi và khi gửi; lỗi nằm cạnh trường. Server tiếp tục kiểm tra cuối cùng. |
| R09 | Danh sách Admin có đội, người nộp, thời gian và ID rút gọn; tìm theo tên đội/người nộp/ID. Bot không có liên kết sở hữu được ghi rõ, không đoán theo tên. |
| R10 | Captain thiếu Active Bot có liên kết tới danh sách bot từ Thách đấu. Member được hướng dẫn liên hệ Captain và không có CTA chọn bot. Empty state lịch chính thức có liên kết phù hợp. |
| R11 | Chính sách hiện tại trong `TeamTournaments.list`: Player chỉ xem các giải có đội mình tham gia với membership còn hiệu lực. Empty state giải và bảng điểm nói rõ phạm vi đó; không mở rộng quyền. |
| R12 | Tổng lượt hiển thị lấy từ lượt cuối đã nhận; miền slider tiếp tục là số frame thực tế. Giới hạn luật hiển thị riêng. Đã kiểm tra fixture Robot và OTT kết thúc ở lượt 18 với giới hạn 100. |

Các giải đấu hiển thị bằng thẻ thu gọn; mở chi tiết vẫn có đầy đủ bảng điểm, nhánh và lịch. Trạng thái mở của từng giải được giữ khi làm mới. Bỏ dòng lời mời rỗng và câu chỉ vị trí dư thừa trong Team & Bot.

## Phạm vi thay đổi API

Chỉ mở rộng response **Admin đã có quyền** của `GET /api/admin/submissions` với `team_id`, `team_name`, `uploader_name`. Metadata lấy từ `submission_ownership` nối với `teams`/`users`, giới hạn theo 200 bot của danh sách hiện tại. Không đọc source để lấy metadata, không trả source/log/command. Test HTTP xác minh bot trùng tên của hai đội và việc Player không được truy cập endpoint này.

Không thay luật, tính điểm, vòng đời trận, sandbox hoặc phân quyền replay. Test server hiện có `test_d3_replay_scoped_to_participating_team_and_admin` tiếp tục kiểm tra quyền Admin, đội tham gia và đội ngoài cuộc.

## Tệp thay đổi

- Giao diện và state/router: `frontend/app.js`, `frontend/index.html`, `frontend/renderers.js`, `frontend/styles.css`. `frontend/lan.html` và `frontend/protocol.html` cập nhật fingerprint stylesheet dùng chung.
- Metadata Admin: `backend/workspace_http.py`.
- Kiểm thử: thêm `scripts/check_retest_regressions.py`; cập nhật `scripts/check_account_frontend_routing.cjs`, `scripts/check_account_ui.py`, `scripts/check_ui_ux_report.py`, `scripts/check_workspace_layout.py`, `tests/test_api.py`, `tests/test_frontend_logout.py`, `tests/test_workspace_http.py`.
- Tài liệu: `docs/QA.md` và báo cáo này.

## Kiểm chứng

Lệnh chạy từ repository bằng Python virtualenv và Node:

```text
.venv/Scripts/python -m pytest tests controller_tests -ra --tb=short
node scripts/check_account_frontend_routing.cjs
node --check frontend/app.js
node --check frontend/renderers.js
node --check frontend/ui.js
node --check frontend/protocol.js
node --check frontend/lan.js
.venv/Scripts/python scripts/version_frontend.py --check
git diff --check
.venv/Scripts/python scripts/check_retest_regressions.py
.venv/Scripts/python scripts/check_workspace_layout.py
.venv/Scripts/python scripts/check_account_ui.py
.venv/Scripts/python scripts/check_ui_ux_report.py
```

R01–R04 đã được chạy trước khi sửa bằng `check_retest_regressions.py --reproduce`; cả bốn kiểm tra thất bại. Kết quả trước/sau tại [before.json](../.qa-evidence/retest/before.json) và [after.json](../.qa-evidence/retest/after.json).

Kết quả cuối: **501 test Python/Controller đạt**; Node routing/CSRF và các kiểm tra cú pháp đạt; fingerprint và `git diff --check` đạt. Cả bốn browser checker trong danh sách trên đạt, gồm 14 nhóm kiểm tra hồi quy trong checker mới và 120 tổ hợp workspace. Bộ Python có một cảnh báo deprecation của Starlette/httpx đã có trong môi trường.

Chrome headless kiểm tra replay và lịch đấu ở 1366×900, 1440×900, 360×900, 390×900, 768×900. Ma trận workspace bổ sung 120 tổ hợp Admin, Player chưa có đội, Captain, Member, trang và chiều rộng; có chuyển trạng thái thật từ chưa có đội tới đội hoạt động, bot ready, Active Bot. Hai bot Python trùng tên được nộp trên server local. Kiểm tra grants, menu avatar/Escape, tab quản trị, lỗi mạng và logout vẫn nằm trong các checker cũ.

Ảnh local: [replay mobile](../.qa-evidence/retest/replay-390.png), [lịch mobile](../.qa-evidence/retest/official-390.png), [tiến độ OTT](../.qa-evidence/retest/ott-progress.png), [giải đấu mobile](../.qa-evidence/retest/tournament-mobile.png). Bằng chứng `.qa-evidence/` được Git ignore.

## Giới hạn

- Các kiểm tra replay trong checker mới dùng response fixture trong trình duyệt để kiểm soát số lượt và response trả chậm. Authentication/logout dùng backend local thật; quyền replay được kiểm tra riêng bằng HTTP tests.
- Lịch BLOCKED/quá hạn và giải có trận BLOCKED trong checker mới là fixture giao diện. Chưa chạy bot hoặc dispatcher Docker thật cho lượt sửa này, chưa kiểm tra engine Battlecode và mọi thể thức giải end-to-end.
- Responsive kiểm tra bằng viewport Chrome, chưa kiểm tra thiết bị thật hoặc trình đọc màn hình thật; đã xác minh focus bàn phím và tên truy cập.
- Validation thời gian dựa trên đồng hồ trình duyệt; server vẫn là nơi quyết định cuối cùng. Không thay đổi chính sách xếp lịch hồi tố hay cơ chế thử lại.
- Dự án dùng HTML/CSS/JS trực tiếp, không có bước npm bundle/build hoặc cấu hình lint riêng. Kiểm tra cú pháp Node và fingerprint asset là các kiểm tra frontend hiện có.
- Không tạo/hủy trận, đổi Active Bot hoặc sửa dữ liệu trên production.
