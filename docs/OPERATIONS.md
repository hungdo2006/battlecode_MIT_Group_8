# Vận hành và bàn giao

Áp dụng cho một backend worker và một controller trên mỗi sandbox namespace, dùng filesystem local/Docker named volumes. Không chạy nhiều replica, xóa `.writer.lock` hoặc dùng NFS/SMB để chia sẻ writer. Backend và controller phải cùng phiên bản protocol.

## Migration và Admin

Schema hiện tại: **17**, xác định bởi `backend/account_schema.py` và `SCHEMA_VERSION`. DB cũ phải migrate offline; không tự sửa `PRAGMA user_version`. Trước cập nhật: đóng admission, đợi/hủy công việc hợp lệ, dừng writer và sao lưu. Rehearse trên bản sao trước dữ liệu thật.

Với image đã build cho phiên bản đích và Arena đã dừng:

```sh
docker compose run --rm --no-deps arena python -m backend.admin_cli --data-dir /app/data migrate
docker compose run --rm --no-deps arena python -m backend.admin_cli --data-dir /app/data check
```

Tạo Admin bằng `create-admin --username organizer`; enroll/rotate MFA bằng `enroll-admin-totp --username organizer` với cùng prefix CLI. Hai lệnh cần terminal riêng tư tương tác; không pipe mật khẩu hoặc lưu TOTP secret vào log. Enroll/rotate MFA thu hồi phiên cũ. Quản lý Player qua UI Admin, không sửa trực tiếp bảng users.

## Cold backup

Giữ cùng Compose project cho lệnh stop/start và script; thêm `--project <name>` nếu đã dùng `-p`. Dừng cả Arena/controller, không dùng `down` trước backup vì script cần inspect container đã dừng.

```sh
docker compose stop arena controller
python scripts/backup_docker.py --output backups/arena-snapshot.tar.gz
docker compose up -d --no-build --wait
```

Backup hợp lệ gồm ba file: `.tar.gz` (data/uploads/artifacts và manifest), `.tar.gz.images.tar` (image được tham chiếu) và `.tar.gz.receipt.json` (checksum/inventory). Giữ cả ba; file dở dang không có receipt hợp lệ không phải backup hoàn chỉnh. `--metadata-only` không thay thế bản sao image độc lập.

Lưu backup có phân quyền/mã hóa ngoài repository; sao lưu `.env`, khóa và quyền sở hữu hạ tầng qua kênh riêng. Public gateway còn có `caddy_data`/`caddy_config`, không thuộc ba volume core mà helper sao lưu.

## Restore và rollback

```sh
python scripts/restore_docker.py --backup backups/arena-snapshot.tar.gz --project neon-arena-restore-drill01 --load-images
```

Project đích phải mới và bắt đầu bằng `neon-arena-restore-`; helper không overwrite volume gốc hoặc tự start app. Đối chiếu receipt, architecture và đúng image IDs; tạo Compose override dùng các IDs đó, project restore, namespace riêng và bind loopback. Không build đè tag trước khi xác minh artifact compatibility.

Trước startup bản phục hồi, chạy CLI trên volume data đích với schema tương thích:

```sh
docker compose -p neon-arena-restore-drill01 run --rm --no-deps arena python -m backend.admin_cli --data-dir /app/data invalidate-restored-auth
```

Nếu dùng override, thêm cùng `-f` vào lệnh trên và mọi lệnh của môi trường restore. Kiểm tra integrity, bot, replay và một trận mới; giữ volume cũ cho đến khi xác minh xong. Không mở hai writer lên cùng bộ dữ liệu. Controller lease ngăn owner cũ tiếp tục công việc; lỗi hạ tầng không được quy thành bot thua.

## Public HTTPS

`compose.public.yaml` là cấu hình triển khai cần operator review, không phải bằng chứng đã triển khai AWS. Cần domain/DNS, TLS, secrets riêng và staging đúng cấu hình đích.

- Caddy là ingress duy nhất ở 80/443; public overlay gỡ port Arena bằng `!reset`. Controller và Docker socket chỉ ở mạng nội bộ.
- Đặt `ARENA_PUBLIC_DOMAIN`, `ARENA_PROXY_SECRET` ngẫu nhiên từ 48 ký tự; secret gateway khác runner token. Không chia sẻ output Compose có nội suy secret.
- Gateway bật Account-Only/HTTPS; origins và hosts phải khớp domain. Không bật `ARENA_AUTH_ALLOW_HTTP` trên public gateway.
- Mặc định dùng `ARENA_ADMIN_TOTP_REQUIRED=1`, `ARENA_PUBLIC_ADMIN_PASSWORD_ONLY=0`. Enrollment offline và các opt-in signup/password-only tại [tài khoản](USERNAME_ONLY_SIGNUP.md).
- Nếu dùng email verification, cấu hình SMTP STARTTLS và thử delivery/recovery trước khi mở đăng ký. Tắt self-registration không đồng nghĩa tắt email verification.

Kiểm tra cú pháp mà không in giá trị nội suy:

```sh
docker compose -f compose.yaml -f compose.public.yaml config -q
```

Trước go-live: chạy browser/Docker/HTTPS/WebSocket QA trên staging, kiểm tra quyền Team/CSRF/rate limit, backup/restore, recovery khi crash và giới hạn tải. Ban tổ chức giữ domain, cloud, MFA, backup, giám sát và quy trình sự cố. Không suy nghiệm thu public từ unit test hoặc local QA; việc triển khai cần ủy quyền riêng.
