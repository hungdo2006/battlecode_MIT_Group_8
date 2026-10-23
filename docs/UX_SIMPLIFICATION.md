# NEON ARENA — Đơn giản hóa hành trình Admin / Player

## Nguyên tắc

- Mỗi vai trò nhìn thấy công việc cần làm trước; các công cụ ít dùng được nhóm dưới **Thiết lập & công cụ**.
- Dùng ngôn ngữ của người tổ chức thi: **Giải đấu**, **Đội**, **Bot đại diện**, **Trận chính thức**, **Kết quả**.
- Giữ nguyên các routes/hash, Account-Only ACL, cơ chế khóa và snapshot, Team DRAFT/ACTIVE, Active Bot, Season, Tournament và Official Match. Không migration, không thay đổi API hay phân quyền.
- Giao diện là lớp hướng dẫn, **không** được xem là rào bảo mật hoặc tự chuyển trạng thái nếu backend chưa cho phép.

## Hành trình Admin

1. **Tổng quan** hiển thị hành động tiếp theo dựa trên số đội sẵn sàng và giải đấu.
2. **Quản lý đội** để xem đội, thành viên và bot.
3. **Giải đấu**: màn hình hướng dẫn tạo giải → công bố luật mỗi vòng nếu cần → xếp lịch trận → công bố kết quả. Có nút tạo giải rõ ràng và liên kết tạo **đợt đăng ký** (Season) cho giải mở đăng ký theo thời gian.
4. **Trận chính thức** và **Kết quả & bảng điểm** dành cho giám sát và công bố.
5. Cấu hình game toàn cục nay ghi rõ là **cấu hình game mặc định**, không khóa game trong Season/Tournament. Các công cụ Season và giám sát kỹ thuật vẫn còn trong menu nâng cao.

## Hành trình Player

1. **Đội & bot của tôi** hiển thị bốn bước theo dữ liệu thực: vào đội, trưởng đội xác nhận đội sẵn sàng, nộp bot `ready`, trưởng đội chọn **bot đại diện**.
2. Bước nào chưa xong được chỉ rõ trong một thẻ hướng dẫn. Nút chỉ dẫn tới trang/điều khiển thật, không tự thay đổi dữ liệu.
3. **Giải đấu** hiển thị liên kết tới **Đợt đăng ký** ngay trong trang, không yêu cầu người dùng hiểu Season ở menu riêng.
4. **Đấu luyện**, **Kết quả**, **Xem lại trận đấu** vẫn hoạt động qua các endpoint cũ.

## Tại sao chưa xóa nút kích hoạt đội hoặc tự chọn bot?

Trạng thái Team ACTIVE và việc Captain chọn bot đại diện hiện được backend dùng để xác định đội hợp lệ, quyền đăng ký và đóng băng bot tại thời hạn Official. Tự động hóa hai thao tác này cần đặc tả sản phẩm và kiểm thử các tình huống nhiều bot, quyền Captain, giải nhiều game, khóa bot và dữ liệu cũ. Bản UX này chỉ **giải thích và dẫn đường**, không thay đổi logic nghiệp vụ ngầm.

## QA / nghiệm thu trước khi merge

- Player chưa có đội: thấy hướng dẫn tạo hoặc nhận lời mời; Admin không thấy thẻ Player.
- Team DRAFT: Captain có nút **Xác nhận đội sẵn sàng**; Member vẫn nộp code được nhưng không tự kích hoạt.
- Team ACTIVE có / không có bot ready / bot đại diện: tiến độ hướng dẫn và nút đều khớp dữ liệu.
- Admin ít hơn 2 đội: CTA mở trang quản lý đội. Đủ 2 đội: CTA mở form tạo giải, có thể chọn game khác game mặc định đang khóa.
- Player ở trang Giải đấu tìm được nút **Xem đợt đăng ký**; Captain có thể đăng ký khi hợp lệ.
- Các liên kết `#official`, `#seasons`, `#rules`, `#system`, replay, trang điểm công khai và màn hình mobile vẫn tới đúng nơi.
- Đọc Game & Luật khi bị khóa: không nhầm nút khóa mặc định thành khóa tất cả giải.
- Kiểm thử với tài khoản Admin, Captain, Member; thao tác không có quyền phải bị backend từ chối; dùng Playwright kiểm tra console, responsive và focus/keyboard.
- Chạy Python/Node regression và Docker/staging trước khi triển khai EC2.

**Giới hạn:** Chưa thay đổi thiết kế schema Season/Tournament hay tự động hóa trạng thái Team/Active Bot; đây là bước 1 của lộ trình UX, không phải một rewrite toàn hệ thống.
