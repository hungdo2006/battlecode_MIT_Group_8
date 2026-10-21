# Battlecode 2026 — tùy chọn

Integration dùng engine MIT chính thức, ghim commit `103abf6b67a2cf544e6344dddef9318af9ae9193`; checksum archive `bb0bab34c26a60d423bbb5d1a0e55ab28d9ee31a76780ef314161c41b4ffc696` trong [Dockerfile](../integrations/battlecode26/Dockerfile). Java 21 chạy engine, Python 3.12 chạy crossplay bridge. Mặc định chỉ bật Robot Battle và OTT v2.

## Bật engine

Sau [cài đặt sandbox](SANDBOX.md) và [backup/migration](OPERATIONS.md):

```sh
docker compose -f compose.yaml -f compose.battlecode.yaml up -d --build --wait
```

Giữ cùng override cho các lệnh Compose sau đó. Build cần truy cập source/dependency registry; native runner không chạy được Battlecode. Đổi engine image có thể làm receipt bot cũ không tương thích: nộp/biên dịch lại.

## Bot và replay

| Ngôn ngữ | Entrypoint | Mẫu |
| --- | --- | --- |
| Python | `def turn():`, dùng globals API chính thức như `rc`, `Direction` | `samples/battlecode26/bot.py` |
| Java | `package arena; public class RobotPlayer`, `public static void run(RobotController rc)` | `samples/battlecode26/RobotPlayer.java` |

Nhận một file UTF-8 không rỗng, tối đa 256 KiB. Không hỗ trợ C++, ZIP nhiều file hoặc upload map tùy ý. Map có sẵn: DefaultSmall/DefaultMedium/DefaultLarge. Bot dùng API Battlecode, không dùng JSON stdin của Robot/OTT.

Controller chạy whole-match trong container không mạng, non-root và có giới hạn tài nguyên. Lỗi hạ tầng/replay không hoàn chỉnh gây INTERRUPTED, không tự gán thua cho Player. Viewer web là bản gọn từ replay chính thức; tải `.bc26` để dùng client MIT đầy đủ. Quyền xem theo [Official/Scrimmage](TEAM_TOURNAMENTS.md).

## Kiểm thử tùy chọn

```sh
docker build -f integrations/battlecode26/Dockerfile -t neon-arena-battlecode:2026 .
python scripts/check_battlecode_engine.py
python scripts/check_battlecode_platform.py
```

Platform checker tạo Compose/account/volume riêng, chạy cả Season và Scrimmage, rồi cleanup. `--serve` giữ server tạm cho browser review; dừng bằng Ctrl+C hoặc marker `design-research/battlecode26-engine/stop-platform-review`. Không commit fixture đăng nhập. Các checker này dùng tag engine nêu trên: chỉ chạy trên Engine QA phù hợp.

Lượt QA ngày 21/10/2026 trong [QA](QA.md) đã chủ động tắt Battlecode; kết quả Robot/OTT không chứng minh engine này đã được kiểm thử lại.
