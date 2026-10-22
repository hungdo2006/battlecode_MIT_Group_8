# Vận hành và bàn giao

Áp dụng cho một backend worker và một controller trên mỗi sandbox namespace, dùng filesystem local/Docker named volumes. Không chạy nhiều replica, xóa `.writer.lock` hoặc dùng NFS/SMB để chia sẻ writer. Backend và controller phải cùng phiên bản protocol.

## Migration và Admin

Schema hiện tại: **19**, xác định bởi `backend/account_schema.py` và `SCHEMA_VERSION`. Migration 18 thêm giới hạn đội và tombstone bot; migration 19 thêm lượt tìm trận. Không sửa các migration 1–17. DB cũ phải migrate offline; không tự sửa `PRAGMA user_version`. Trước cập nhật: đóng admission, đợi/hủy công việc hợp lệ, dừng writer và sao lưu. Rehearse trên bản sao trước dữ liệu thật.

Với image đã build cho phiên bản đích và Arena đã dừng:

```sh
docker compose run --rm --no-deps arena python -m backend.admin_cli --data-dir /app/data migrate
docker compose run --rm --no-deps arena python -m backend.admin_cli --data-dir /app/data check
```

Tạo Admin bằng `create-admin --username organizer`; enroll/rotate MFA bằng `enroll-admin-totp --username organizer` với cùng prefix CLI. Hai lệnh cần terminal riêng tư tương tác; không pipe mật khẩu hoặc lưu TOTP secret vào log. Enroll/rotate MFA thu hồi phiên cũ. Quản lý Player qua UI Admin, không sửa trực tiếp bảng users.

Giới hạn đội mặc định 5, tính cả Captain; Admin chỉnh 2–20 ở **Tài khoản & đội → Đội**. Giảm giới hạn giữ nguyên thành viên, chỉ chặn mời/nhận thêm. Xóa bot là ẩn bằng tombstone: giữ nguyên ownership, source, artifact và snapshot để trận/replay cũ tiếp tục đọc được. Không chạy thao tác dọn uploads/artifacts chỉ vì bot bị ẩn; chưa bổ sung garbage collector.

Đấu luyện ghép FIFO giữa các đội chủ động tìm, cùng game, có bot hợp lệ. Một đội chỉ có một lượt tìm hoặc trận đấu luyện đang xử lý. Reload/mất mạng giữ lượt tìm tối đa 5 phút; restart hủy các lượt chưa ghép với lý do rõ ràng. Trận đã tạo dùng dispatcher hiện tại, giới hạn tổng hai trận và ưu tiên Official. Recovery của trận đã claim giữ cơ chế không tự chạy lại khi không chắc đã thực thi.

Phiên Admin/Player mới mặc định tối đa 8 giờ, idle 1 giờ theo PR #17. Các phiên đã phát hành giữ TTL được lưu trong DB; cập nhật code không thay TTL của phiên cũ. Heartbeat frontend chỉ chạy khi có tương tác trong trang đang hiển thị, thường không quá một lần/45 giây; backend gộp cập nhật last_seen trong 30 giây và không thay expires_at/cookie. Feed chỉ đọc, WebSocket và GET me/csrf không thay thế heartbeat. 429 và lỗi mạng được giữ phiên; chỉ bằng chứng xác thực hết hạn/thu hồi mới chuyển về đăng nhập.

Trước deploy AWS, thực hiện quy trình cold backup/restore bên dưới và checklist riêng tại [báo cáo Team/Bot/Đấu luyện/Session](TEAM_MATCHMAKING_SESSION.md). Không downgrade bằng cách hạ user_version hoặc xóa bảng mới; rollback dùng bộ snapshot trước migration và đúng image IDs đã sao lưu.

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
