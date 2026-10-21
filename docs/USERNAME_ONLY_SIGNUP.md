# Tài khoản và Team

Áp dụng khi bật [Account-Only](SANDBOX.md). Admin và Player dùng chung form đăng nhập; server xác định vai trò. Đăng ký luôn tạo Player, không cấp quyền Admin.

## Luồng Player

1. Đăng ký nếu Admin đã bật self-registration; xác minh email nếu môi trường yêu cầu.
2. Trong **Team & Bot**, tạo Team hoặc nhận lời mời. Mỗi Player có tối đa một membership chưa rời Team.
3. Người tạo là Captain; Team mới ở DRAFT, Captain kích hoạt thành ACTIVE.
4. Member được nộp/xem source bot trong Team. Chỉ Captain chọn Active Bot theo game, quản lý thành viên và đăng ký Season.
5. Nộp một file Python/C++/Java tối đa 256 KiB cho Robot/OTT; chờ ready trước khi chọn. Bản nộp mới là phiên bản mới; lỗi biên dịch có diagnostics. [Battlecode](BATTLECODE_2026.md) có định dạng riêng.

Admin có thể quản lý trạng thái Player và xem vận hành. Đội khác không được đọc source/diagnostics riêng; quyền xem giải/replay được kiểm tra ở server. Xem [giải đấu](TEAM_TOURNAMENTS.md).

## Chế độ đăng ký

| Môi trường | Cấu hình |
| --- | --- |
| Local/LAN, không xác minh email | `ARENA_SELF_REGISTRATION=1`, `ARENA_EMAIL_VERIFICATION=0`; username + password từ 8 ký tự |
| Public có email | `ARENA_EMAIL_VERIFICATION=1` và SMTP STARTTLS hợp lệ; đăng ký chờ xác minh |
| Public pilot không email | `ARENA_PUBLIC_USERNAME_SIGNUP=1`, `ARENA_EMAIL_VERIFICATION=0`; cần HTTPS Account-Only gateway và self-registration |

Không cần bật `ARENA_PUBLIC_USERNAME_SIGNUP` cho local. Đóng nhận mới bằng `ARENA_SELF_REGISTRATION=0`; giữ sender/email verification nếu còn tài khoản chờ xác minh hoặc cần email recovery. Không có email thì hệ thống không chứng minh được danh tính qua email.

Giới hạn đăng ký hiện tại là 5 lần thử/60 giây theo địa chỉ nguồn tin cậy, trong bộ nhớ một backend; không thay thế kiểm soát tuyển sinh hoặc chống lạm dụng ở gateway.

## Khôi phục và Admin MFA

Player không dùng email recovery có thể xin mã từ Admin tại **Official Match → Hỗ trợ khôi phục tài khoản Player**, rồi nhập ở **Quên mật khẩu Player?**. Admin phải xác minh danh tính ngoài hệ thống. Mã dùng một lần, hạn 30 phút; cấp mã mới vô hiệu mã cũ. Reset thành công thu hồi phiên cũ. Không chụp/chia sẻ mã trong log hoặc ticket.

Admin được bootstrap offline, không qua đăng ký Player hoặc recovery Player. Public gateway chấp nhận đúng một cấu hình:

- Mặc định bảo vệ MFA: `ARENA_ADMIN_TOTP_REQUIRED=1`, `ARENA_PUBLIC_ADMIN_PASSWORD_ONLY=0`.
- Pilot có giám sát được chủ môi trường chọn: `ARENA_ADMIN_TOTP_REQUIRED=0`, `ARENA_PUBLIC_ADMIN_PASSWORD_ONLY=1`.

Cấu hình thứ hai giảm bảo vệ khi lộ mật khẩu; không xóa dữ liệu TOTP đã enroll. Cách enroll, migration và public HTTPS ở [vận hành](OPERATIONS.md).
