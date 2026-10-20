# Nghiệm thu Player / Admin — 20-10-2026

## Kết quả kiểm thử

- **494 kiểm thử Python đạt**: toàn bộ `tests` và `controller_tests`.
  Có một cảnh báo deprecation Starlette/httpx, không có kiểm thử thất bại.
- **116 lượt kiểm tra giao diện đạt** trên Chrome ở 1440, 1366, 768, 390 và 360px:
  Player/Admin, trang công khai, trang có dữ liệu và replay. Không có lỗi
  JavaScript, ID trùng, tràn ngang toàn trang hoặc phản hồi 429 trong lượt cuối.
- Kiểm thử bàn phím di động đạt: vòng focus, Escape, backdrop, trả focus,
  nền inert và chuyển về sidebar desktop.
- Playwright MCP đã thực sự điều hướng, đọc snapshot, đo font/CSS và chụp ảnh.
  Chrome xác nhận headline dùng Inter Variable tự host, gồm các ký tự tiếng Việt.
- Docker chạy engine Battlecode chính thức với Java/Java, Python/Java,
  Python/Python và hai bot mẫu có di chuyển. Có kiểm tra entrypoint sai,
  hành động replay, tách số King/cheese và file `.bc26` gốc.
- Docker platform đạt: Scrimmage khi cả hai người chơi đã đăng xuất; replay
  riêng tư; mùa giải → đăng ký → chốt đội → Official Match → nhà vô địch;
  Round Robin có bảng điểm thực; Robot Battle và OTT v2 tiếp tục chạy thành công.

116 là số tổ hợp màn hình/kích thước, không phải 116 chức năng độc lập.
Kiểm thử dùng dữ liệu và tài khoản QA tạm, không dùng dữ liệu triển khai chính.

## Đối chiếu các trang trong yêu cầu

| Trang / chức năng | Kết quả và bằng chứng |
| --- | --- |
| Trang chủ và luật chơi | Headline Inter, bố cục hai cột, mẫu code có nhãn, workflow, responsive và reduced motion; `check_account_ui.py`, `check_workspace_ui.py`, Playwright MCP |
| Đăng ký / Đăng nhập | Đăng ký Player, khôi phục phiên, đăng xuất/thử lại và thu hồi phiên; bộ kiểm thử auth hiện có và `check_account_ui.py` |
| Dashboard cá nhân | Team, Active Bot, thống kê trận chính thức, lịch sắp tới; giao diện có dữ liệu, 5 kích thước |
| Đội và thành viên | Tạo/kích hoạt/đổi tên, lời mời, Captain/member, Active Bot và lưu trữ theo quyền; `test_team_http.py`, `test_team_service.py`, Docker platform |
| Nộp và quản lý phiên bản bot | Biên dịch trong sandbox, source của đội, diagnostics, Active Bot theo game; `test_team_bots.py`, `test_battlecode.py`, engine/platform thật và rà upload bằng MCP |
| Thách đấu / Scrimmage | Chốt bot/luật, hàng đợi bền vững, chạy offline, chống trùng, hủy khi còn chờ, quyền xem; `test_scrimmages.py`, Docker platform |
| Lịch sử / Replay | Scrimmage trong Lịch sử; trận chính thức trong Official Match. Link chia sẻ giữ đúng loại trận; tải JSON đúng quyền; tải `.bc26`; kiểm thử browser và Docker |
| Bảng xếp hạng | Bảng điểm theo game/giải/nhóm; nhánh đấu dành cho loại trực tiếp. Giải Round Robin chạy thật xác nhận đội thắng nhận 3 điểm; browser kiểm tra bảng đã có dữ liệu |
| Quản lý giải đấu | Các thể thức có sẵn, fixture, lịch khóa bot/bắt đầu, xác minh và tiến nhánh; `test_team_tournament_http.py`, Docker platform |
| Quản lý bản đồ và luật | Cấu hình luật bằng schema theo game, chọn bản đồ Battlecode có sẵn; adapter/controller từ chối bản đồ hoặc lựa chọn không hỗ trợ |
| Giám sát server và hàng đợi | Admin xem readiness thực, chế độ runner, Battlecode, số trận/queue, active và interruption; `test_workspace_http.py`, Docker và browser |
| Tài khoản và phân quyền | Tìm kiếm/phân trang, vai trò/trạng thái/đội; mời, recovery, khóa/mở Player và vô hiệu phiên cũ; API kiểm tra quyền, CSRF; `test_workspace_http.py`, Docker và browser |

## Đối chiếu luồng vận hành

Player có thể đăng ký/đăng nhập, cập nhật tên hiển thị, lập hoặc tham gia đội,
tải bot mẫu/API, nộp phiên bản, chọn Active Bot, gửi Scrimmage, xem kết quả và
replay, rồi đăng ký mùa giải bằng tài khoản Captain.

Admin có thể tạo mùa giải với hạn đăng ký và lịch dự kiến, cấu hình game,
kiểm tra đội/tài khoản/bot, chốt danh sách đăng ký thành giải, xếp lịch đấu,
theo dõi runner/queue, kiểm tra kết quả và công bố nhà vô địch đã được xác minh.
Mọi thao tác ghi vẫn đi qua xác thực, CSRF và kiểm tra quyền ở server.

Migration 15 → 17 được kiểm tra giữ nguyên Team và source attestation, tạo các
bảng mới rỗng, chạy lại an toàn. Kiểm thử shutdown xác nhận vẫn đợi đóng phiên
runner khi việc hủy task đến đúng lúc cleanup đang chạy.

## Phạm vi và giới hạn

- Battlecode là engine chính thức ghim commit, cần bật bằng Compose override;
  chưa được triển khai lên môi trường chính hoặc GitHub trong đợt này.
- Battlecode nhận một file Python/Java và ba bản đồ chính thức có sẵn. Chưa có
  upload ZIP nhiều file hoặc trình biên tập bản đồ tùy ý.
- Viewer web là bản trình bày gọn từ replay engine. Có `.bc26` để mở bằng client
  chính thức; không thay thế toàn bộ debugger/profiler của client đó.
- Hạn đăng ký được thực thi. Ngày bắt đầu/kết thúc mùa là lịch dự kiến;
  bot-lock/scheduled-start của từng trận điều khiển chạy thực tế.
- Admin trong giao diện quản lý trạng thái Player. Cấp quyền Admin tiếp tục qua
  quy trình bootstrap/TOTP hiện có, không mở chức năng tự nâng quyền.
- Kiểm thử đã phủ các luồng chính và hồi quy hiện có; chưa phải kiểm thử tải lớn
  hay mọi tổ hợp bot/map/ngôn ngữ có thể có.

## Chạy lại

```text
.venv\Scripts\python.exe -m pytest tests controller_tests -ra
node scripts/check_account_frontend_routing.cjs
.venv\Scripts\python.exe scripts/check_account_ui.py
.venv\Scripts\python.exe scripts/check_battlecode_engine.py
.venv\Scripts\python.exe scripts/check_battlecode_platform.py --serve
.venv\Scripts\python.exe scripts/check_workspace_ui.py
```

`check_workspace_ui.py` đọc fixture cục bộ do platform checker tạo, không in mật
khẩu. Dừng review bằng Ctrl+C hoặc marker được mô tả trong
[hướng dẫn Battlecode](BATTLECODE_2026.md). Chạy `version_frontend.py --check`,
`node --check` cho hai file JS và `git diff --check` trước khi commit.

Bằng chứng cục bộ: `design-research/battlecode26-engine/final-regression.xml`,
`platform-acceptance.json`, `workspace-ui/report.json` và các ảnh `*-final-*.png`.
Không đưa fixture đăng nhập tạm hoặc thư mục mã nguồn upstream tải về vào commit.
