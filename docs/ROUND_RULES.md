# Luật theo vòng thi và bảng xếp hạng

Mục tiêu: Cho Admin ra cấu hình mới giữa các vòng, học sinh có 15 hoặc 20 phút cập nhật/chọn bot trước khi khóa. Không sửa luật của trận đã xếp lịch hoặc lịch sử đã chấm.

## Vòng thi có phiên bản luật bất biến

- Mỗi round được định danh bằng `tournament_id`, `stage` (`GROUP` hoặc `KNOCKOUT`) và `round_number`.
- Chỉ Admin được lưu nháp luật cho **vòng đã sinh fixture** của Tournament ACTIVE; luật phải hợp lệ theo GameAdapter, không cho phép truyền arbitrary fields.
- Admin chọn `editing_minutes=15|20`, nhấn **Lưu nháp**, sau đó **Công bố**. DRAFT không được thấy ở Player hoặc dùng để xếp lịch.
- Công bố bất biến, `bot_lock_at` tối thiểu `published_at + editing_minutes*60`. Lúc xếp lịch fixture, hệ thống đưa đúng ruleset vào `official_match_requests.rules_json`, sau đó trận sở hữu snapshot độc lập.
- Không cho tạo/chỉnh draft nếu vòng đã từng xếp lịch Official, kể cả lịch đã hủy. Nếu giải chưa khai báo round-specific rules, luồng cũ tiếp tục dùng luật toàn cục.
- Hệ thống vẫn dùng bot lock có sẵn: Captain phải chọn Active Bot trước hạn. Chưa có nút khóa **mọi** nộp code toàn site; các nộp trễ không ảnh hưởng trận đã chốt nhưng vẫn có thể hiển thị trong thư viện.

Ví dụ: Tournament vòng 1 OTT v2, vòng 2 OTT Advanced **không** thể đổi game giữa vòng: một Tournament chọn một `game_id` duy nhất. Để thay cấu trúc OTT giữa vòng, tạo Tournament `ott_advanced` từ đầu, rồi cấu hình `board_size`/ `max_move_distance` riêng cho từng vòng. Luật OTT v2 9×9 cũ không thay đổi.

**Giới hạn:** Phần cấu hình hiện lưu quy tắc theo **vòng đã được engine sinh fixture**, không phải vòng chưa tồn tại; nếu trận đã lên lịch từ trước thì không thể bật luật mới hồi tố. Cần tránh sử dụng API tạo Official Match độc lập để thay cho fixture Tournament trong cuộc thi theo vòng.

## Quyền xem bảng xếp hạng

- `PRIVATE` (mặc định): chỉ Admin và đội tham gia được xem giải cùng bảng điểm.
- `SIGNED_IN`: mọi Player đăng nhập đều xem được.
- `PUBLIC`: mọi người xem trang `/results` và `GET /api/public/standings`, chỉ metadata Tournament, bảng điểm và nhóm; không có nguồn bot, account, ID trận hoặc replay.
- Chính sách hiển thị kết quả **không** cấp quyền xem trận/replay nếu người xem không thuộc Team.
- Bảng điểm loại trực tiếp có thể trống; nhánh đấu giữ riêng theo quyền truy cập.

Tương thích: migration append-only **20** sau 19; offline migration/backup bắt buộc. Không dùng code mới với schema 19 chưa migration. Đây là thay đổi candidate trên nhánh mới; CI + Playwright + Docker staging và LAN dry run vẫn là điều kiện trước release.
