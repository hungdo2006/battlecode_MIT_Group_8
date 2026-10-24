# Kiểm thử NEON ARENA

## Regression bắt buộc

Tại repository với Python 3.13, Node 24 và toolchain Java/C++ phù hợp:

```sh
python -m pip install -r requirements-dev.txt
python -m pytest tests controller_tests -ra
node scripts/check_account_frontend_routing.cjs
node --check frontend/app.js
node --check frontend/renderers.js
node --check frontend/ui.js
node --check frontend/protocol.js
node --check frontend/lan.js
python scripts/version_frontend.py --check
git diff --check
```

GitHub Actions chạy Python/Controller và frontend checks trên Ubuntu và Windows, đồng thời resolve cấu hình Compose B1.3–B1.5 với secret giả. Đây **không** phải chứng nhận Docker thực tế hoặc hiệu năng giải đấu.

## Kiểm thử tùy chọn trên môi trường riêng

```sh
python scripts/check_docker.py --build
python scripts/check_sandbox_lifecycle.py
```

Kiểm thử browser cần cài Playwright/Chrome:

```sh
python -m pip install playwright
python scripts/check_account_ui.py
python scripts/check_ui_ux_report.py
python scripts/check_workspace_layout.py
python scripts/check_retest_regressions.py
```

Các script Docker/browser dùng môi trường kiểm thử riêng. Không chạy vào website AWS đang vận hành, không dùng dữ liệu người chơi thật hoặc xóa volume khác. Battlecode 2026 có checker tùy chọn, xem [tài liệu engine](BATTLECODE_2026.md).

## Nghiệm thu trước giải thật

1. Đăng ký/đăng nhập Admin và Player, Team và phân quyền; nộp bot Python/C++/Java.
2. Official, Scrimmage, Season, tính điểm, replay và thử giới hạn trận đồng thời.
3. Với B1.5: tạo backup lạnh và restore drill, thử Local → Remote → Local khi không có công việc đang chạy; xem [runbook](B15_SHARED_PILOT_RUNNER_SWITCH.md).
4. Thử ngắt kết nối PC, mạng, mất nguồn, hàng chờ; đảm bảo không có kết quả thắng giả.
5. Thử tải với số lượng đội/người chơi dự kiến và lưu bản backup **ngoài** EC2.

Ngày 24/10/2026, người vận hành đã xác nhận B1.5 chuyển Runner hai chiều và Scrimmage/replay ở cả hai chế độ trên EC2 và laptop. Điều đó không thay thế kiểm thử tải lớn hoặc buổi diễn tập với PC trường.

Báo cáo QA và ảnh chụp cũ được lược khỏi nhánh hiện tại để giảm nhiễu; lịch sử vẫn xem được trong Git/PR. CI tạo artifact kiểm thử mới cho từng PR.
