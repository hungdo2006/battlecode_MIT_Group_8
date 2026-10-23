# Kiểm thử và trạng thái xác minh

## Regression

Tại repository, trong Python 3.13 virtualenv có Node 24 và toolchain C++/Java phù hợp:

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

Browser checker cần thêm package Playwright và Chrome:

```sh
python -m pip install playwright
python scripts/check_account_ui.py
python scripts/check_ui_ux_report.py
python scripts/check_workspace_layout.py
```

Script này dùng server/dữ liệu native tạm; không chứng minh bot chạy Docker. CI baseline hiện chạy Python/Controller/frontend checks trên Windows và Ubuntu, chưa chạy browser hoặc sandbox thật.

Kiểm tra bố cục theo vai trò, tab, menu avatar, Team/bot, mùa/giải và bằng chứng ngày 22/10/2026: [Cải tổ workspace](WORKSPACE_LAYOUT_REVIEW.md). Checker mới chạy ma trận 120 tổ hợp trên server local tạm và không thực thi lịch Official.

Sửa và kiểm thử lại R01–R12 (reset phiên/replay, history, CTA bot, lịch quá hạn và metadata): [Khắc phục kiểm thử lại](RETEST_FIXES.md), chạy thêm `python scripts/check_retest_regressions.py`.

Team capacity, archive bot, tìm trận FIFO, heartbeat và hồi quy PR #17/CI: [Team/Bot/Đấu luyện/Session](TEAM_MATCHMAKING_SESSION.md). Playwright MCP dùng `scripts/serve_feature_qa.py` với dữ liệu tạm và runner fixture; kiểm tra Docker thật vẫn là release gate riêng.

Đối chiếu từng phát hiện và phạm vi kiểm tra bổ sung: [Khắc phục báo cáo UI/UX](UI_UX_REVIEW_FIXES.md).

## Docker và end-to-end

```sh
python scripts/check_docker.py --build
python scripts/check_sandbox_lifecycle.py
```

Các checker này tạo môi trường riêng và kiểm tra sandbox/lifecycle, không thay thế nghiệm thu đầy đủ Team/Season Account-Only. `check_battlecode_engine.py`, `check_battlecode_platform.py` và `check_workspace_ui.py` có phụ thuộc fixture/engine Battlecode; chỉ dùng theo [hướng dẫn tùy chọn](BATTLECODE_2026.md), không dùng để dựng QA Robot/OTT đơn thuần.

Với Account-Only, tạo project/namespace/image tags/volumes QA riêng, tài khoản giả và ít nhất hai Team; ưu tiên bốn Team để thử Round Robin. Kiểm tra bằng browser thật:

1. Signup/login/logout/reload; quyền Player/Admin, Captain/member và cách ly source giữa Team.
2. Upload bot đúng/sai, diagnostics, Active Bot; Single Elimination và Round Robin chạy sandbox thật.
3. Deadline khóa bot, fixture, kết quả/bảng điểm và replay khớp backend.
4. Season đăng ký → chốt đội → giải → công bố; Scrimmage khi Player logout.
5. Desktop/mobile, focus/modal, console, 401/403/404/429, lỗi server và WebSocket reconnect.

Ghi SHA, cấu hình, lệnh, PASS/FAIL/SKIP/BLOCKED, screenshot/trace/log đã lọc secret và giới hạn chưa thử. Không dùng dữ liệu thật, stress production hoặc xóa tài nguyên của môi trường khác. Xem [vận hành](OPERATIONS.md) trước diễn tập migration/restore.

## Kết quả đã thực thi ngày 21/10/2026

Source SHA `41910da49644b698543b68787dc0d8e0be874455`:

| Phạm vi | Kết quả |
| --- | --- |
| Python/Controller | 469 + 25 = **494 PASS**, 0 FAIL/SKIP; một warning Starlette/httpx deprecation |
| Docker Account-Only | 1 Admin, 5 Player, 4 Team; **11 Official + 2 Scrimmage** COMPLETED |
| Robot Battle | Single Elimination 4 đội, Round Robin 6 trận, Season có công bố; offline Scrimmage |
| OTT v2 | Python/C++ compile thật, Official/Scrimmage và replay |
| Chrome 1440/390px | **48 tổ hợp layout** có dữ liệu, không JS exception hoặc HTTP 429/500 ngoài bài fault injection |
| Backend | Outcome Official khớp terminal replay/game adapter; SQLite schema 17, integrity OK |

Đây là nghiệm thu pilot local có giám sát. AWS/public TLS/SMTP, tải lớn, crash/restore Docker của giải này và Battlecode **chưa được nghiệm thu trong lượt đó**. HTTP 500 được giả lập ở browser để thử UI; 429 được thử thật có giới hạn. Bằng chứng chi tiết ở máy QA (`QA_REPORT.md`, `.qa-evidence/`), không commit credential/trace thô. Các con số trên là mốc lịch sử của SHA nêu trên, không phải kết quả CI cho mọi commit mới.
