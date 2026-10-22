# Cải tổ bố cục NEON ARENA · 22/10/2026

Đã triển khai trong repository, kiểm tra bằng Chrome với dữ liệu tạm. Không thay đổi API, quyền backend, model mùa/giải, compiler, sandbox hoặc cách tính kết quả. Không triển khai lên production.

## Thay đổi chính

- Tài khoản, vai trò, Hồ sơ và Đăng xuất nằm trong menu avatar. Menu dùng được với Enter, Tab, Escape; Escape trả focus về avatar. Sidebar giữ các tác vụ theo vai trò và bỏ slogan thường trực.
- Thanh ngữ cảnh chung chỉ giữ game hiện tại và trạng thái cuộc thi; Hồ sơ, Tài khoản & đội, Giám sát hệ thống bỏ thanh này. Chọn game, mở/đóng cuộc thi nằm tại Game & Luật chơi.
- Tổng quan đưa việc cần làm lên trước thống kê. Admin thấy cấu hình, chuẩn bị đội/bot hoặc trận cần xử lý theo dữ liệu; Player được dẫn qua tham gia đội, kích hoạt, nộp bot, chọn Active Bot và lịch/thách đấu. Thành viên được hướng dẫn nhờ Captain khi cần. Lịch tiếp theo chỉ xuất hiện khi có dữ liệu; bỏ CTA lịch lặp trong trạng thái rỗng.
- Team & Bot ưu tiên tạo/tham gia đội. Phần nộp code chưa khả dụng mặc định thu gọn; tài liệu và bot mẫu vẫn truy cập được. Hướng dẫn mã đội ở sát trường nhập; giới hạn dữ liệu giữ nguyên. Khi đã có đội, bot và biểu mẫu nộp ở cùng vùng; quản lý thành viên mở theo nhu cầu. Drop zone bị khóa không nhận file hoặc phản hồi kéo/thả như vùng đang dùng được.
- Quản trị chia tab Tài khoản / Đội / Bot & biên dịch, có tìm kiếm tương ứng. Giữ phân trang tài khoản và xác nhận thao tác. Mời Player và khôi phục chỉ mở khi cần; mở UI không cấp token.
- Mùa thi đấu và Giải đấu giữ nguyên nghiệp vụ riêng, ưu tiên danh sách; biểu mẫu tạo nằm trong vùng mở rộng có đường đóng và Escape trả focus.
- Game & Luật chơi có một ô chọn, mô tả ngắn và cấu hình liền nhau. Player đọc danh sách luật; Admin có trạng thái chưa lưu/đã lưu/đã khóa. Cách chơi và luật cố định nằm trong vùng mở rộng.

## File quan trọng

| File | Vai trò |
| --- | --- |
| [frontend/index.html](../frontend/index.html) | Cấu trúc menu, trang, tab và biểu mẫu mở theo nhu cầu |
| [frontend/app.js](../frontend/app.js) | Hiển thị theo trạng thái và quyền, luật chỉ đọc, tìm kiếm, cập nhật sau nộp bot, mở replay |
| [frontend/styles.css](../frontend/styles.css) | Spacing, khung gọn, mobile, trạng thái disabled và nhóm nội dung |
| [frontend/ui.js](../frontend/ui.js) | Tab bàn phím, menu avatar, đóng vùng mở rộng và khôi phục focus |
| [scripts/check_workspace_layout.py](../scripts/check_workspace_layout.py) | Kiểm tra hồi quy vai trò/trạng thái bằng dữ liệu local tạm |

`lan.html` và `protocol.html` chỉ cập nhật fingerprint CSS/JS. Các browser checker hiện có cập nhật đường truy cập menu và biểu mẫu mới.

## Kết quả đã thực thi

| Kiểm tra | Kết quả |
| --- | --- |
| `python -m pytest tests controller_tests -q` | **500 test PASS**, một cảnh báo deprecation Starlette/httpx hiện có |
| Nhóm frontend/hồi quy sau các chỉnh sửa cuối | **38 PASS** |
| `node scripts/check_account_frontend_routing.cjs` | PASS: routing, CSRF, thu hồi phiên, calendar và chế độ bảng điểm |
| `node --check` các file JavaScript | PASS |
| `python scripts/version_frontend.py --check` | PASS, fingerprint khớp asset |
| `git diff --check` | PASS |
| `python scripts/check_workspace_layout.py` | **120 tổ hợp PASS** ở 1366×900, 1440×900, 360×900, 390×900, 768×900; không JS exception hoặc tràn ngang toàn trang |
| `python scripts/check_account_ui.py` | PASS: signup/login/restore, logout thất bại và thử lại, mobile drawer/focus, thu hồi phiên |
| `python scripts/check_ui_ux_report.py` | PASS: tài khoản, docs, Team/upload/mẫu, điều kiện thiếu đội, routing và 8 chiều rộng |
| `check_multiplayer_ui.check` trên server legacy tạm | PASS: 3 phiên, 2 trận Robot Battle/OTT v2 thực thi native, live/replay, pause độc lập, quyền và mobile 390 px; không JS exception |

Dự án phục vụ trực tiếp HTML/CSS/JS, không có bước bundle/npm build.

Ma trận 120 tổ hợp gồm Admin (Tổng quan, Hồ sơ, Tài khoản & đội, Mùa, Giải, Official, Luật); Player mới (Tổng quan, Team & Bot, Official, Thách đấu, Hồ sơ, Luật); Captain và thành viên có đội/bot/lịch. Trạng thái có dữ liệu dùng đội, bot Python biên dịch thật, mùa/giải và lịch local đặt nhiều giờ trong tương lai. Có 55 tài khoản giả để kiểm tra phân trang, tên đội dài, tìm kiếm không có kết quả và lỗi HTTP 500 được tiêm tại browser rồi thử lại.

Đã kiểm tra các chuyển trạng thái không đội → DRAFT → ACTIVE → bot hợp lệ → Active Bot, tham gia bằng lời mời, thành viên không có CTA chọn bot vượt quyền, tải mẫu khi chưa có đội, focus quay về mã đội, tab Arrow/Home/End, disclosure Escape, và mở replay gián đoạn chưa có frame. Kiểm tra riêng trên bản local xác nhận đổi Robot Battle → OTT, lưu luật, khôi phục mặc định qua dialog rồi đổi lại Robot Battle.

## Ảnh trước/sau

Cùng server Account-Only local, dữ liệu kiểm thử hai tài khoản và chưa có đội, viewport 1366×900. Ảnh chụp toàn trang. Tiêu đề chính chuyển từ khoảng y=359–398 px xuống khoảng y=141–163 px; Hồ sơ/quản trị bắt đầu sớm hơn do không mang ngữ cảnh cuộc thi. Team & Bot mặc định của Player mới giảm từ khoảng 2.002 px xuống khoảng 914–916 px.

| Màn hình | Trước | Sau |
| --- | --- | --- |
| Tổng quan Admin | [Ảnh trước](../.qa-evidence/before-admin-home.png) | [Ảnh sau](../.qa-evidence/after-admin-home.png) |
| Tổng quan Player mới | [Ảnh trước](../.qa-evidence/before-player-home.png) | [Ảnh sau](../.qa-evidence/after-player-home.png) |
| Team & Bot chưa có đội | [Ảnh trước](../.qa-evidence/before-team-bot.png) | [Ảnh sau](../.qa-evidence/after-team-bot.png) |
| Tài khoản & đội | [Ảnh trước](../.qa-evidence/before-admin-accounts.png) | [Ảnh sau](../.qa-evidence/after-admin-accounts.png) |

Ảnh có dữ liệu: [quản trị đội](../.qa-evidence/workspace-layout/admin-teams-populated.png), [Captain sẵn sàng](../.qa-evidence/workspace-layout/captain-home-ready.png), [Team & Bot](../.qa-evidence/workspace-layout/team-bot-ready.png), [mobile thành viên](../.qa-evidence/workspace-layout/member-mobile.png). [Số đo 120 tổ hợp](../.qa-evidence/workspace-layout/measurements.json). Bằng chứng trong `.qa-evidence/` là artifact local được Git ignore.

## Giới hạn

Lượt này không nghiệm thu lại Docker Sandbox, Battlecode 2026 hoặc tải production. Hai trận đã chạy là chế độ legacy/native local; lịch Account-Only chỉ đặt trong tương lai để kiểm tra UI, không thực thi Official/Season. Fixture replay gián đoạn và lỗi tải chỉ nằm trong browser kiểm thử. Website tham chiếu không truy cập được qua công cụ web; đối chiếu và ảnh trước/sau dựa trên code cùng bản chạy local.
