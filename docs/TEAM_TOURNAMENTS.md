# Season, giải Team và Scrimmage

Các luồng này cần Account-Only và Docker Sandbox. Để chạy trận, Team phải ACTIVE và có bot ready/được attestation cho đúng game; Captain chọn Active Bot trước hạn khóa.

## Tổ chức giải

1. Admin chọn game và lưu luật. Có thể tạo giải trực tiếp từ các Team hoặc tạo Season với cửa sổ đăng ký/capacity.
2. Captain đăng ký/rút Team trong cửa sổ còn mở. Admin đóng đăng ký rồi chốt danh sách thành Tournament.
3. Admin bắt đầu Tournament để tạo fixture/nhánh; lên lịch riêng từng fixture với `bot_lock_at <= scheduled_at`, không đặt hạn trong quá khứ. Luật được snapshot khi xếp lịch.
4. Tới hạn khóa, hệ thống chốt bot/source/artifact; tới giờ thi đấu tự chạy Official, không cần Player online.
5. Chỉ kết quả được đối chiếu terminal replay mới hoàn tất fixture, tiến nhánh và cập nhật bảng điểm.
6. Khi giải COMPLETED, Admin xác nhận công bố Season; nhà vô địch và bảng điểm được lưu thành snapshot audit.

Ngày bắt đầu/kết thúc Season là lịch dự kiến; giờ khóa/giờ chạy của từng fixture điều khiển thực thi. Không tự kết thúc trận ở ngày cuối Season. Trận BLOCKED/INTERRUPTED/CANCELLED không được tính như đã đấu xong.

## Thể thức

| Số đội | Lựa chọn |
| --- | --- |
| 2–16 | Round Robin, Single/Double Elimination; Group + Knockout và Swiss + Knockout cần 4–16 |
| 17–64 | Tự chọn Group + Knockout |
| Trên 64 | Vòng loại Single Elimination xuống 16 hoặc 64, sau đó Group + Knockout |

Single Elimination có bye khi cần. Double Elimination loại sau hai lần thua; reset grand final chỉ khi đội từ nhánh thua thắng final đầu. Group + Knockout lấy hai đội đầu mỗi bảng. Swiss chạy 3 vòng cho 4–8 đội, 4 vòng cho 9–16, ưu tiên tránh gặp lại; top 4/top 8 vào knockout tương ứng dưới 8/từ 8 đội.

Round Robin/vòng bảng: thắng 3, hòa 1, thua 0; xếp theo điểm, hiệu số, điểm ghi được, số thắng, tên Team. Swiss: thắng 1, hòa 0,5, bye 1; thêm Buchholz trước hiệu số. Bảng Team tournament tách khỏi leaderboard Player legacy.

Knockout hòa tự lên lịch lại, khóa bot ngay và trễ một phút. Sau ba Official cùng hòa, Admin chọn đội đi tiếp; quyết định được audit. Chưa có tự sinh ngày thi đấu hoặc hủy toàn bộ Team Tournament.

## Scrimmage và replay

Member của Team ACTIVE gửi thách đấu khi cả hai đội có Active Bot hợp lệ. Bot và luật được chốt lúc gửi; trận tiếp tục khi logout. Mỗi đội gửi tối đa 3 yêu cầu pending; chặn cặp có cùng chiều/game đang pending, queue toàn cục tối đa 100. Challenger/Admin hủy khi còn QUEUED; Official được ưu tiên dispatch trong sức chứa chung hai trận.

Scrimmage không cộng điểm giải. Sau restart không chắc chắn, công việc đã claim được đánh dấu INTERRUPTED thay vì tự chạy lại hai lần. Admin và thành viên hiện tại của hai Team xem replay; đội ngoài bị từ chối. URL chia sẻ giữ loại `?official=ID#home` hoặc `?scrimmage=ID#home`; Battlecode có thêm tải `.bc26`.

API dùng namespace `/api/admin/`, `/api/player/`: `team-tournaments`, `official-matches`, `seasons`, `scrimmages`. Mutation yêu cầu cookie đúng audience và CSRF. Chi tiết request nằm trong các module `backend/*_http.py`.
