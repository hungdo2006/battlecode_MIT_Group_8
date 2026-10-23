# Tạo game mới cho NEON ARENA (Game Adapter)

NEON ARENA không chỉ giới hạn Robot Battle/OTT: `GameRegistry` dùng giao diện `GameAdapter`. Hiện có `robot_battle`, `ott_v2`, `ott_advanced` (và `battlecode26` opt-in).

## Đăng ký game mới: gói đã được kiểm duyệt

Game lập trình backend phải được **đội kỹ thuật** review, test và đóng gói vào Docker image của server. Không hỗ trợ Admin upload file Python bất kỳ lên website (rủi ro thực thi mã phía server).

Một distribution wheel đã cài có thể khai báo Python entry point:

```toml
[project.entry-points."neon_arena.games"]
school_exam = "school_exam.adapter:SchoolGameAdapter"
```

`SchoolGameAdapter` phải là lớp không tham số khởi tạo, kế thừa `backend.engine.base.GameAdapter`. Game cần khai báo metadata duy nhất, Pydantic rules_model, phương thức tạo trạng thái, observation, validate action, apply action, player-to-act, terminal result. Không thực thi bot trong adapter và không truy cập Internet/file dữ liệu đối thủ.

**Chỉ sau khi** artifact được review/cài vào image và kiểm thử, operator mới đặt `ARENA_APPROVED_GAME_PLUGINS=school_exam` trong .env riêng của server. Ứng dụng nạp các entry point *đã cài* và *được duyệt*, từ chối tên không tồn tại và game_id trùng. Mặc định không nạp plugin ngoài. Để nâng cấp plugin phải rollout image mới qua backup/migration/QA; Admin chỉ chọn game đã có sẵn trong UI.

Renderer tự chọn dạng tổng quát nếu không cài renderer custom; muốn hình ảnh game chuyên nghiệp phải bổ sung renderer cùng protocol và regression replay. Mỗi thay đổi phá vỡ luật/observation nên tăng game_id hoặc giữ adapter version cũ để replay và bot đã chấm không đổi.

## OTT Advanced

Bản variant nằm ở `backend/engine/ott_advanced.py`, định danh `ott_advanced`; kích thước 7/9/11, nước đi thẳng/chéo 1–3 ô, **không nhảy quân**, ăn quân ở ô đến, 9 quân/mỗi bên, đích hai góc đối diện. Hạn lượt và số ván giữ kiểu OTT v2. Dùng sample Python `samples/ott_v2/runner.py` vì nó đọc `legal_actions` + `goals` động. Sample C++/Java OTT v2 cũ chỉ hiểu tọa độ 0–8 nên chưa công bố làm mẫu cho OTT Advanced.
