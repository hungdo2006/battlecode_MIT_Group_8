# Team, bot, đấu luyện và phiên đăng nhập

Nhánh `feature/team-bot-matchmaking-sessions` bắt đầu từ main `4b5f91f` (PR #17). Không merge main hoặc deploy AWS trong lượt làm việc này.

## Chức năng và dữ liệu

| Phần | Hành vi |
| --- | --- |
| Giới hạn đội | Admin chỉnh 2–20, mặc định 5 gồm Captain. Hiển thị quân số/giới hạn. Kiểm tra khi mời và nhận lời mời trong transaction BEGIN IMMEDIATE; giảm giới hạn không loại thành viên. UI cập nhật quân số và giới hạn định kỳ, không chỉ lúc reload. |
| Xóa bot | Member chỉ xóa bot mình nộp; Captain xóa bot của đội. Có xác nhận, CSRF, kiểm tra quyền và audit. Active Bot không xóa được. Tombstone ngăn hiển thị/chọn mới nhưng giữ source, artifact và dữ liệu trận đã khóa. Xóa lặp lại không ghi audit trùng. |
| Đấu luyện | FIFO giữa các đội chủ động tìm cùng game; revalidate membership/đội/bot khi ghép, chốt bot lúc ghép. Một transaction tạo request và cập nhật cả hai lượt tìm. Unique index ngăn hai lượt tìm cùng đội; double-submit trả lượt hiện tại. |
| Hủy và phục hồi | Lượt tìm tối đa 300 giây. Reload/mất mạng/mở tab khác đọc cùng state DB. Chỉ hủy lượt SEARCHING; nếu ghép trước khi hủy thì trả xung đột và UI đọc lại kết quả. Restart hủy lượt chưa ghép; request đã ghép giữ recovery của Scrimmage. |
| Thực thi | Tái sử dụng ScrimmageDispatcher/MatchManager/Docker Sandbox, không thêm executor trong tiến trình web. Giữ giới hạn hai trận, queue 100 request và Official chạy trước đấu luyện. Giữ API thách đấu cũ để tương thích nhưng không cho nó chen vào lượt matchmaking đang xử lý. |
| Phiên | Heartbeat dựa trên tương tác thật, tôn trọng idle TTL và absolute TTL đã lưu. Cookie/absolute expiry không được gia hạn. Cảnh báo gần hạn; lỗi mạng, 429, 403 thật và response cũ không được coi là logout. Revoke, MFA và CSRF vẫn được kiểm tra. |

Migration append-only **18–19**, không sửa các migration cũ: `team_policy`, `submission_archives`, `matchmaking_searches` và index của hàng tìm trận. Bản 17 có thể nâng trực tiếp. Test ép SQL lỗi ở migration 19 xác minh cả 18–19 rollback về 17, rồi migration lại thành công; dữ liệu Team/bot/Season/Tournament/Official và file replay được giữ.

API mới: `GET /api/{player,admin}/team-policy`, `PUT /api/admin/team-policy`, `DELETE /api/player/bots/{id}`, `GET /api/player/matchmaking?game_id=…`, `POST /api/player/matchmaking/find`, `POST /api/player/matchmaking/{id}/cancel`, `POST /api/{player,admin}/auth/heartbeat`. Mutation nhận JSON và đi qua auth/audience/CSRF hiện có. Client không được cung cấp team/uploader làm bằng chứng quyền. Response matchmaking không chứa source, artifact ID hoặc digest của đối thủ.

## Điều tra PR #17 và CI

Hai đường có thể giải thích việc đang dùng giao diện nhưng phiên hết idle: các API đọc có `touch=False`, trong khi chỉ tương tác ở frontend không cập nhật last_seen; phiên cũ cũng giữ idle TTL đã pin khi phát hành, dù default mới đã đổi. Không có log production để kết luận mọi lần logout thực tế đều cùng nguyên nhân. Giải pháp thêm heartbeat có giới hạn và kiểm tra fake clock, không tăng TTL vô hạn.

Đã tái hiện lỗi form đổi mật khẩu của PR #17: validator chung so confirm_password với `password`, nhưng form Profile dùng `new_password`. Đã sửa hỗ trợ cả hai tên và thêm browser regression kiểm tra mismatch, đổi thành công, thu hồi tab thứ hai.

Run [39790117598](https://github.com/hungdo2006/battlecode_MIT_Group_8/actions/runs/39790117598) bị hủy trên cả Ubuntu/Windows sau 30 phút ở bước Python. Test `test_account_websocket_auth_logout_and_idle_expiry` còn tăng fake clock 15 phút rồi chờ disconnect vô hạn, trong khi PR #17 đổi idle Admin thành 60 phút. Test nay đọc TTL của phiên; chạy riêng khoảng 2 giây. Giữ timeout job 30 phút, thêm tên test/durations và faulthandler sau 60 giây để có vị trí/stack nếu xuất hiện hang khác; không bỏ qua test.

## Kiểm chứng

Kết quả local: **520 test Python đạt, 0 lỗi** trong 166,09 giây (một cảnh báo thư viện Starlette/httpx có sẵn). Routing Node, syntax JavaScript, frontend fingerprint và `git diff --check` đạt. Bốn browser checker đạt: account/profile (gồm thu hồi hai tab), UI review ở 8 chiều rộng, workspace 120 tổ hợp và 14 nhóm hồi quy. Playwright MCP đạt 13 nhóm luồng cùng 15 tổ hợp responsive như mô tả bên dưới. Docker engine thật chưa chạy được; CI của PR được theo dõi riêng trên GitHub.

Lệnh regression:

```text
python -m pytest tests controller_tests -ra --tb=short --durations=12 -o faulthandler_timeout=60
node scripts/check_account_frontend_routing.cjs
node --check frontend/app.js
node --check frontend/ui.js
python scripts/version_frontend.py --check
git diff --check
python scripts/check_account_ui.py
python scripts/check_ui_ux_report.py
python scripts/check_workspace_layout.py
python scripts/check_retest_regressions.py
```

Test mới kiểm tra race hai người nhận chỗ cuối, ba đội cùng tìm, FIFO và bot chốt tại lúc ghép, IDOR/CSRF, quyền Member/Captain, archive Active Bot, bot đã khóa Official, dữ liệu Scrimmage cũ, timeout/restart, migration rollback/recovery và fake clock hoạt động/idle/absolute/revoke cho cả hai vai trò.

Playwright MCP đã chạy các flow trên server localhost dữ liệu tạm: Admin đặt giới hạn, Captain mời hai Member, hai người nhận lời; Member/Captain xóa theo quyền; Active Bot bị chặn xóa; hai đội tìm và được ghép; hủy/reload/tìm lại; đổi bot rồi ẩn bản đã chốt và mở replay; Admin tạo/bắt đầu giải, xếp/hủy Official từ Tournament; đổi mật khẩu đăng xuất hai tab; Admin hoạt động qua 75 phút không đổi absolute expiry, Player idle hết hạn và Admin absolute hết hạn. 13 nhóm kiểm tra hoàn thành, không có JavaScript exception. Responsive 15 tổ hợp: Admin/Team & Bot/Đấu luyện tại 1366, 1440, 360, 390, 768 px; không tràn ngang và mỗi trang một H1. Menu avatar Escape và các luồng bàn phím được kiểm tra.

Fixture MCP chạy bằng `python scripts/serve_feature_qa.py --port 8791`: auth, Team, bot ownership, queue và replay HTTP là backend thật với DB tạm. Runner/artifact và kết quả replay là fixture có nhãn; dispatcher không claim execution trong helper. Các route `__qa__` chỉ được đăng ký bởi script test, không có trong app production, và helper không được COPY vào Docker runtime.

**Chưa kiểm tra Docker engine thật cho tính năng mới:** `docker version` kể cả ngoài sandbox trả lỗi không có pipe `dockerDesktopLinuxEngine`. Không tuyên bố pass end-to-end sandbox, build Docker, AWS hoặc trình đọc màn hình thật. Test Python hiện có vẫn kiểm tra native engine/compiler và mock controller riêng.

Ảnh và kết quả local (Git ignore): [13 nhóm MCP](../.qa-evidence/team-features/mcp-results.json), [đang tìm trên mobile](../.qa-evidence/team-features/search-mobile.png), [giới hạn đội mobile](../.qa-evidence/team-features/team-limit-mobile.png), [replay bot đã ẩn](../.qa-evidence/team-features/archived-bot-replay-mobile.png), [Tournament mobile](../.qa-evidence/team-features/tournament-mobile.png). Các checker cũ giữ ma trận workspace 120 tổ hợp và UI review 8 chiều rộng.

## Tệp chính

- `backend/account_schema.py`, `team_service.py`, `team_http.py`: migration/capacity.
- `backend/bot_service.py`, `bot_http.py`, `workspace_http.py`: archive và projection quyền/metadata.
- `backend/matchmaking_service.py`, `scrimmage_service.py`, `scrimmage_http.py`: tìm/ghép/hủy, snapshot và dispatcher.
- `backend/auth_service.py`, `auth_http.py`: session activity và response TTL.
- `frontend/app.js`, `index.html`, `styles.css`, `ui.js`: UI, heartbeat, thông báo và xác nhận mật khẩu. `lan.html`/`protocol.html` đổi fingerprint dùng chung.
- `tests/test_team_management.py`, `test_session_activity.py`, `test_team_migration.py`, `test_account_database.py`, `test_account_only.py` và browser checkers; `.github/workflows/phase42e-baseline.yml`.

## Checklist cập nhật AWS sau review

1. Review/merge PR theo quy trình của chủ dự án. Rehearse trên staging hoặc project restore riêng với bản sao backup đầy đủ, không dùng dữ liệu thật cho test UI phá hủy.
2. Chuyển website sang bảo trì, ngăn yêu cầu mới; chờ trận chạy xong hoặc xử lý hủy theo nghiệp vụ. Dừng Arena/controller cùng Compose project. Không chạy hai writer trên một bộ volume.
3. Cold backup theo [OPERATIONS](OPERATIONS.md): giữ cùng bộ data/uploads/artifacts, manifest/receipt và image archive trước khi build đè tag. Sao lưu `.env` và khóa riêng ngoài Git. Kiểm tra receipt/checksum và khả năng restore.
4. Dùng image phiên bản mới đã kiểm tra tương thích artifact. Khi Arena vẫn dừng, chạy `docker compose run --rm --no-deps arena python -m backend.admin_cli --data-dir /app/data migrate`, rồi cùng prefix CLI `check`. Schema đích 19; không sửa version bằng SQL.
5. Khởi động controller/Arena, kiểm tra health, login/MFA/CSRF, dữ liệu cũ và một replay cũ; kiểm tra tìm trận thật với Docker trên staging và ưu tiên Official trước khi mở lại admission. Chưa có release gate này trong môi trường hiện tại.
6. Theo dõi lỗi API, 429, queue, dung lượng uploads/artifacts. Lượt SEARCHING trước restart sẽ hiển thị cần tìm lại; trận đã claim không được tự chạy lại khi uncertain. Bot ẩn vẫn chiếm lưu trữ để giữ lịch sử.
7. Nếu phải rollback, dừng writer và restore toàn bộ snapshot trước migration cùng image IDs phù hợp theo quy trình restore, chạy `invalidate-restored-auth` trước startup. Không hạ riêng schema hoặc ghép DB cũ với artifacts mới.
