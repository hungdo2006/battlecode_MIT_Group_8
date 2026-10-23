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


## Trạng thái hệ thống dành cho Admin

Trang **Trạng thái hệ thống** (trong **Thiết lập & công cụ**) có hai tầng thông tin:

- **Thông tin vận hành:** hệ thống sẵn sàng hay cần kiểm tra, số trận đang chạy / giới hạn đồng thời, đấu luyện đang chờ, trận chính thức đã xếp lịch hoặc đã chốt bot, danh sách trận đang chạy và sự cố gần đây. Nút cập nhật lấy lại dữ liệu từ API.
- **Chi tiết kỹ thuật (mở khi cần):** môi trường runner, Battlecode 2026 tùy chọn, Python/C++/Java có được phát hiện trên host hay không và trạng thái trận tự do.

Các thẻ này dùng duy nhất API Admin hiện có `/api/admin/system`; không tự kết luận về CPU, RAM, container Docker hay kết nối AWS vì endpoint chưa cung cấp các giá trị này. `Battlecode 2026` chưa cấu hình không phải lỗi của OTT/Robot Battle. Danh sách sự cố là các trận `interrupted` trong dữ liệu API, không phải log hệ điều hành.

### Acceptance

- Runner sẵn sàng / chưa sẵn sàng: lời dẫn và biểu tượng hiển thị đúng.
- Số trận đang chạy và giới hạn, hai hàng đợi, danh sách trận và sự cố đúng dữ liệu backend.
- Không có Battlecode: chi tiết kỹ thuật giải thích đây là tùy chọn.
- User Player không truy cập được trang và API Admin; UX không được thay thế phân quyền backend.
- Ngắt mạng / hết phiên: hiển thị lỗi tải trạng thái, không khẳng định dữ liệu cũ là hiện tại.
- Desktop/mobile 1440, 768, 390, 360 px: nội dung không tràn và mục kỹ thuật đóng mặc định.
- Sau đổi JS/CSS cập nhật fingerprint mọi trang HTML tham chiếu.


## Đấu luyện — chọn đội và đấu thử trực tiếp

Đây là **đấu luyện tự chọn đối thủ**, không phải ghép trận ngẫu nhiên. Player chọn trò chơi, xem danh sách các đội **ACTIVE và có bot đại diện hợp lệ** trong game đó, rồi nhấn **Đấu thử** cạnh đội muốn đối đầu.

- Không cần hai đội đồng thời online, không có nút "Tìm đối thủ", đồng hồ chờ 5 phút hay hàng ghép ngẫu nhiên.
- API `GET /api/player/scrimmage-opponents?game_id=...` trả về các đội đã có bot hợp lệ; danh sách loại bỏ chính đội mình và có tìm kiếm theo tên trên trình duyệt.
- Khi đã sẵn sàng, bất cứ thành viên đội ACTIVE nào có thể chủ động chọn đối thủ. Trưởng đội (Captain) chịu trách nhiệm chọn bot đại diện trước đó; Member không thể thay Captain chọn bot.
- Nút **Đấu thử** gọi `POST /api/player/scrimmages` với `{game_id, opponent_team_id}`. Backend **ngay lập tức tạo một yêu cầu trận QUEUED**, snapshot luật và bot hai đội, rồi dispatcher thực thi trên Sandbox. **Đối thủ không cần chấp nhận.**
- Khi bot bên mình chưa đủ điều kiện, các nút đấu bị khóa và có liên kết trở về **Đội & bot của tôi**.
- Giới hạn server vẫn là tối đa 3 trận đang chờ/chạy mà đội chủ động tạo, không gửi trùng cùng cặp đội/game; chỉ có thể hủy trận khi QUEUED.
- **Các trận đấu luyện** hiển thị trạng thái, kết quả và nút live/replay, kèm bộ lọc tất cả / chờ-đang đấu / đã kết thúc.
- Frontend bỏ giao diện và lời gọi `/api/player/matchmaking`. Endpoint ghép trận cũ được giữ trong backend cho dữ liệu và client lịch sử, **không có đường vào trong giao diện mới**. Việc xóa hẳn API/schema cũ sẽ là một migration riêng nếu thực sự cần.
- Không cộng điểm giải đấu, không thay đổi Tournament/Official, không migration database.

### QA Đấu luyện trực tiếp

- Tài khoản chưa có đội, Team DRAFT, ACTIVE chưa có bot, ACTIVE có bot cho game A nhưng chưa có cho game B: danh sách và nút hợp lệ chính xác.
- Tài khoản Captain và Member đều thấy danh sách đội; Member chỉ xem bot và không có quyền tự chọn bot đại diện.
- Hai đội có bot `ready`/attested cho OTT, Robot Battle, OTT Advanced: bấm **Đấu thử** đúng đội, tạo QUEUED, chạy thật trên Sandbox, có replay chính xác và không cộng điểm Tournament.
- Đội khác không có bot hợp lệ hoặc chưa ACTIVE không được quảng cáo như đối thủ sẵn sàng; đội mình không xuất hiện.
- Không cho gửi trùng cặp đội/game đang chờ, giới hạn 3 trận chờ/chạy, hủy QUEUED, không hủy khi đã DISPATCHING/RUNNING.
- Thay game liên tục trong khi đang tải: kết quả request game cũ không ghi đè game mới, nút không được bật cho game chưa kiểm tra.
- Bộ lọc tên đội, bộ lọc lịch sử, nút cập nhật, tải lại, lỗi mạng và xử lý 403/409. Kiểm tra bàn phím/đọc màn hình, responsive 360/390/768/1440.
- Docker Sandbox thật và ưu tiên xử lý Official phải được nghiệm thu ở môi trường có Docker trước khi production.
