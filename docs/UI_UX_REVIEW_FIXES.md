# Khắc phục báo cáo UI/UX ngày 21/10/2026

Đối chiếu 33 phát hiện UI-01–UI-33 trong `bao-cao-ui-ux-neon-arena.pdf` với mã nguồn. Các thay đổi áp dụng cho frontend và cấu hình trong repository; cần triển khai phiên bản mới để website đang chạy nhận bản sửa.

## Đối chiếu phát hiện

| Mục | Thay đổi |
| --- | --- |
| UI-01 | Tiêu đề, lời dẫn và trạng thái đổi đồng bộ giữa đăng nhập/đăng ký. |
| UI-02 | Hướng dẫn username 3–32 ký tự, bộ ký tự và chuẩn hóa chữ thường khớp `normalize_username`; có `aria-describedby`. |
| UI-03 | Hướng dẫn mật khẩu 8–1024 ký tự cạnh từng ô mật khẩu mới; đăng nhập giữ điều kiện mật khẩu hiện tại. |
| UI-04 | Liên hệ Admin qua `hungdonxqvbn@gmail.com`, cấu hình bằng `ARENA_SUPPORT_URL`; chỉ dẫn thông tin cần cung cấp. |
| UI-05 | Hướng dẫn xin mã nằm trước biểu mẫu, hạn 30 phút và 43 ký tự nằm sát ô mã. |
| UI-06 | Hai nút chọn tác vụ có `aria-pressed`; thao tác bằng Tab/Enter/Space theo ngữ nghĩa button. |
| UI-07 | Kiểm tra biểu mẫu tài khoản bằng thông báo tiếng Việt cạnh trường, `aria-invalid` và vùng thông báo; giữ kiểm tra server. Các lỗi xác thực phổ biến cũng được dịch. |
| UI-08 | Thanh đóng/quay lại cố định trong hộp thoại; Escape và phục hồi focus được kiểm tra. |
| UI-09 | Dành sẵn rãnh cuộn bằng `scrollbar-gutter: stable`. |
| UI-10 | Đổi “Invitation token” thành “Mã kích hoạt”. |
| UI-11 | Nêu nguồn mã Admin gửi, 43 ký tự, dùng một lần và cách xin mã mới khi hết hạn/không hợp lệ. |
| UI-12 | Bot mẫu phân biệt cần đăng nhập, lỗi phiên, lỗi server và mất kết nối; có đăng nhập/thử lại và quay về đúng anchor sau xác thực. |
| UI-13 | Liên kết quay lại đổi theo khách/Player/Admin; khách đăng nhập rồi tới Team & Bot. |
| UI-14 | Tăng chữ hướng dẫn, trạng thái, code, bước giới thiệu và footer trên landing; kiểm tra tràn ở nhiều độ rộng. |
| UI-15 | Ví dụ observation Robot Battle đúng engine, có thụt lề để đọc; nút sao chép lấy JSON một dòng và có chú thích giao thức JSON Lines. |
| UI-16 | Select game và nút cấu hình căn cùng đáy; đo cùng top cho Admin/Player trên desktop. |
| UI-17 | Hai header giải Team có cùng chiều cao; đo tiêu đề cùng trục. Panel legacy được giữ ẩn khi quyền UI cập nhật. |
| UI-18 | Account-Only dùng nhãn “BẢNG ĐIỂM GIẢI ĐẤU TEAM”, khớp mô tả/cột/dữ liệu; legacy giữ bảng free play. |
| UI-19 | Select đội/đối thủ có trạng thái tải, thiếu đội, chưa ACTIVE, không có đối thủ và lỗi tải; khóa khi không có lựa chọn. |
| UI-20 | Lý do khóa xếp lịch hiển thị cạnh nút và được liên kết bằng `aria-describedby`; có đường dẫn quản lý đội/bot. Cho lưu lịch trước khi bot được chốt, đúng điều kiện backend. |
| UI-21 | Tạo giải bị khóa nếu chọn dưới hai đội; hiển thị số đội đã chọn và yêu cầu tối thiểu. |
| UI-22 | “Mã đội” có giải thích khác tên hiển thị; 3–48 chữ cái ASCII/chữ số/gạch ngang, chuẩn hóa chữ thường, mã duy nhất. |
| UI-23 | Nộp file và mẫu dùng chung điều kiện membership, trạng thái đội và quyền. Khóa cả chọn/thả file khi thiếu điều kiện; có chỉ dẫn tạo/tham gia đội ngay trong upload. Nộp mẫu Account-Only dùng API upload JSON có CSRF. |
| UI-24 | Danh sách Account-Only là “Bot của đội”; hướng dẫn member nộp và Captain chọn bot đại diện. |
| UI-25 | Official Match phân biệt chưa có đội với đội chưa có lịch; có CTA Team & Bot. |
| UI-26 | Empty state Admin Account-Only hướng dẫn đội/Official/Scrimmage; Player READY chỉ xuất hiện trong legacy. |
| UI-27 | Hướng dẫn Player phân biệt Captain chọn bot trước hạn khóa Official, chốt bot khi gửi Scrimmage và không cần online. |
| UI-28 | Dịch `captures`, `first_player`, `TOURNAMENT` trong nhóm luật đã Việt hóa. |
| UI-29 | Trang LAN lấy origin từ trình duyệt, giữ đúng HTTPS sau reverse proxy. |
| UI-30 | Không tự đưa IP nội bộ server/container vào danh sách liên kết gợi ý; chỉ hiển thị origin đang dùng và hướng dẫn xác định card mạng của host. |
| UI-31 | Quy trình Account-Only sáu bước đặt trước; legacy thu gọn trong phần riêng. |
| UI-32 | Route không được phép chuyển về `#home`, đồng bộ nội dung/title/menu/breadcrumb; có thông báo ngắn. |
| UI-33 | Đăng xuất đã xác nhận đưa về `#home`, title công khai, xóa đích replay/xác thực cũ và toast của phiên trước. Đăng xuất chưa được xác nhận giữ phiên để thử lại. |

## Đề xuất bổ sung

C01/C02: thêm hiện/ẩn mật khẩu và nhập lại khi kích hoạt. C03: sao chép code, có phản hồi và cách chọn code khi clipboard không dùng được. C04: mũi tên đi tiếp cho CTA đăng nhập và hướng dẫn cùng tab. C05: mục lục tài liệu theo anchor. C07: liên kết thật từ hai bước đầu tới Bot mẫu và hướng dẫn tạo đội.

C06 (demo/replay công khai) và C08 (thử ưu tiên đăng ký) là đề xuất sản phẩm/thử nghiệm chuyển đổi trong báo cáo, không phải phát hiện lỗi. Không thêm dữ liệu trận giả hoặc thay đổi ưu tiên đăng ký trong đợt sửa này.

## Kiểm tra

```sh
python -m pytest tests controller_tests -ra
node scripts/check_account_frontend_routing.cjs
node --check frontend/app.js
node --check frontend/ui.js
node --check frontend/protocol.js
node --check frontend/lan.js
python scripts/version_frontend.py --check
python scripts/check_ui_ux_report.py
python scripts/check_account_ui.py
git diff --check
```

Checker UI dùng Chrome với locale `en-US`, server và tài khoản/đội tạm. Kiểm tra biểu mẫu, liên hệ, retry, xác thực/quay lại Bot mẫu, route theo vai trò, empty state, căn chỉnh DOM, nộp mẫu Python thực tế, origin HTTPS giả lập và bố cục ở 360/375/390/414/768/1024/1366/1440 px. Ảnh và kết quả regression được lưu cục bộ trong `.qa-evidence/ui-ux-review/`, không đưa vào commit.

Kết quả ngày 21/10/2026: **500 kiểm thử Python/Controller đạt**, hai checker trình duyệt đạt, kiểm tra cú pháp JavaScript/routing/CSRF/fingerprint và `git diff --check` đạt. Có một cảnh báo deprecation Starlette/httpx của môi trường kiểm thử.

Đây là kiểm tra UI trên native runner. Không thay thế nghiệm thu Docker/engine thật, Safari/Firefox, production hoặc tải lớn. Không thao tác website public hay dữ liệu đang vận hành.
