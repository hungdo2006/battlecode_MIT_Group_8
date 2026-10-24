# NEON ARENA

Nền tảng tự host để thi đấu bot: Robot Battle, OTT v2, OTT Advanced và Battlecode 2026 tùy chọn. Player quản lý Team/bot; Admin tổ chức giải, lên lịch Official Match và công bố kết quả Season. Bot chạy trong Docker Sandbox; Scrimmage tiếp tục chạy khi người chơi đăng xuất.

## Chạy nhanh

Cần Docker Engine/Desktop chạy Linux containers, Docker Compose hỗ trợ `!reset` khi dùng public overlay, và Python 3 để tạo cấu hình.

```sh
python scripts/configure_sandbox.py
docker compose up -d --build --wait
docker compose ps
```

Mở **http://localhost:8000**. Mặc định là demo LAN dùng mã Organizer trong `.env`, chưa bật tài khoản. Muốn chỉ truy cập từ máy này, đặt `ARENA_BIND_IP=127.0.0.1` trong `.env` trước khi chạy. Windows có thể dùng `py -3` thay `python`.

## Tài liệu

| Nhu cầu | Hướng dẫn |
| --- | --- |
| Cài Docker, bật Account-Only | [Cài đặt](docs/SANDBOX.md) |
| Demo nhiều máy | [LAN và chế độ legacy](docs/NETWORKING.md) |
| Đăng ký, Team, bot và khôi phục tài khoản | [Tài khoản](docs/USERNAME_ONLY_SIGNUP.md) |
| Season, Official Match, Scrimmage và bảng điểm | [Giải đấu](docs/TEAM_TOURNAMENTS.md) |
| Migration, backup/restore, public HTTPS | [Vận hành](docs/OPERATIONS.md) |
| Thi trực tiếp trong phòng máy không Internet | [Exam LAN](docs/EXAM_MODE.md) |
| Chuyển kết quả giải offline lên website online | [Offline Results Transfer](docs/OFFLINE_RESULTS_TRANSFER.md) |
| Luật theo từng vòng và công bố kết quả | [Round Rules](docs/ROUND_RULES.md) |
| Cài thêm game đã qua kiểm duyệt | [Game Adapter](docs/NEW_GAME_ADAPTER.md) |
| Protocol bot và thêm game | [Adapter](docs/ADAPTERS.md) |
| Bật engine MIT tùy chọn | [Battlecode 2026](docs/BATTLECODE_2026.md) |
| Chạy kiểm thử và phạm vi đã xác minh | [QA](docs/QA.md) |
| **AWS EC2 ↔ PC Runner (B1.5)** | [Chuyển Runner dùng chung database](docs/B15_SHARED_PILOT_RUNNER_SWITCH.md) |

Backend: Python/FastAPI, SQLite và JSON/JSONL. Frontend: HTML/CSS/JavaScript/Canvas. Source chính nằm trong `backend/`, `frontend/`, `sandbox_controller/`, `samples/`; test trong `tests/` và `controller_tests/`.

`docker compose down` giữ dữ liệu; thêm `-v` sẽ xóa volume. Giữ kín `.env`, token, cookie và backup. Public HTTPS cần cấu hình riêng; kết quả QA cục bộ không chứng nhận production.
