# Cài đặt Docker và Account-Only

Chạy lệnh tại thư mục repository. Windows cần Docker Desktop Linux containers; `docker version` phải có Server. Linux cần Docker Engine và Compose. Lệnh Python giả định Python 3 có trên PATH.

## Demo mặc định

```sh
python scripts/configure_sandbox.py
docker compose up -d --build --wait
docker compose ps
docker compose logs --tail 50 arena controller
```

Helper tạo/bổ sung `.env` và không thay giá trị đã có. Website mặc định: `http://localhost:8000`; mã Organizer đọc riêng trong `.env`. Chọn `ARENA_BIND_IP=127.0.0.1` cho local hoặc `0.0.0.0` cho LAN tin cậy.

## Account-Only cho giải local

Trên dữ liệu mới hoặc bản sao đã drain/backup, đặt trong `.env`:

```dotenv
ARENA_ACCOUNT_AUTH=1
ARENA_ACCOUNT_ONLY=1
ARENA_SELF_REGISTRATION=1
ARENA_AUTH_ALLOW_HTTP=1
ARENA_AUTH_ORIGINS=http://localhost:8000,http://127.0.0.1:8000
ARENA_ALLOWED_HOSTS=localhost,127.0.0.1
ARENA_BIND_IP=127.0.0.1
ARENA_EMAIL_VERIFICATION=0
ARENA_PUBLIC_USERNAME_SIGNUP=0
ARENA_ADMIN_TOTP_REQUIRED=0
ARENA_PUBLIC_ADMIN_PASSWORD_ONLY=0
```

Dừng backend trước khi bảo trì SQLite. Tạo Admin trong terminal tương tác; CLI hỏi mật khẩu, không truyền mật khẩu qua tham số:

```sh
docker compose stop arena
docker compose build
docker compose run --rm --no-deps arena python -m backend.admin_cli --data-dir /app/data migrate
docker compose run --rm --no-deps arena python -m backend.admin_cli --data-dir /app/data create-admin --username organizer
docker compose up -d --no-build --wait
```

Schema hiện tại là **17**; startup không tự migrate DB cũ. Account-Only vô hiệu quyền của mã Organizer legacy. Đọc [tài khoản](USERNAME_ONLY_SIGNUP.md) và [vận hành](OPERATIONS.md) trước khi dùng dữ liệu hiện có.

## Sandbox và lưu trữ

Chỉ Arena publish cổng web. Controller riêng quản lý Docker socket; bot không có socket/mạng, chạy non-root với giới hạn tài nguyên. Backend dùng runner `sandbox`; không tự fallback sang native khi lỗi Docker.

Ba volume là `arena_data` (SQLite, metadata, replay), `arena_uploads` (source) và `arena_artifacts` (artifact đã biên dịch). Dùng cùng Compose project cho mọi lệnh. Mỗi môi trường QA cần project, namespace, image tags và volumes riêng; chỉ đổi `-p` chưa tách được namespace/tag mặc định.

Chẩn đoán bằng `/api/health` và trang Admin **Giám sát hệ thống**. Không publish controller/Docker API. Xem [LAN](NETWORKING.md), [backup/restore](OPERATIONS.md) và [QA](QA.md).
