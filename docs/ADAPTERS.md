# Bot protocol và adapter

Robot Battle/OTT chạy Python engine của NEON ARENA; mỗi bot nhận một dòng JSON qua stdin, trả một JSON action qua stdout và flush. Ghi debug vào stderr. Một process được giữ suốt trận; timeout mặc định 3 giây cho phản hồi đầu, 1 giây cho phản hồi sau. Nộp một file `.py`, `.cpp` hoặc `.java` (Java dùng `Main`, không package), tối đa 256 KiB.

## Robot Battle

Observation có `player`, `turn`, `rules`, `you`, `enemy`; robot có `x/y/hp`. Cả hai hành động được tính từ cùng state trước lượt.

```json
{"type":"move","direction":"up"}
{"type":"attack"}
{"type":"wait"}
```

Move bốn hướng; ra biên/va chạm đứng yên. Attack trúng khi khoảng cách Manhattan sau move bằng 1; damage đồng thời. Kết quả theo knockout hoặc HP khi hết lượt. Mẫu: `samples/hunter.py`, `hunter.cpp`, `Main.java`.

## OTT v2

Observation có `board`, `player`, `goals`, `scores`, `legal_actions` và trạng thái round. Chọn từ `legal_actions` là cách bắt đầu đơn giản nhất.

```json
{"action":"move","from":{"row":1,"col":3},"to":{"row":2,"col":4}}
```

Board 9×9: row 0 ở dưới, col 0 bên trái; ô null hoặc `{id,owner,type}`, type rock/paper/scissors. A hướng tới (8,8), B tới (0,0). Chỉ bot đang tới lượt được gọi; không có action wait/attack riêng. Server kiểm tra lại nước đi. Round kết thúc bởi goal, elimination, turn_limit hoặc stalemate; lỗi bot xử thua trận. Mẫu trong `samples/ott_v2/`.

Nguồn OTT và MIT license được giữ nguyên kèm checksum trong [snapshot tham chiếu](reference/ottv2/SOURCE.json). README ở snapshot là tài liệu upstream, không phải cách chạy NEON ARENA. `tests/reference_ott.mjs` đối chiếu engine bằng Node; runtime không dùng Express/Socket.IO của upstream.

## Thêm game

1. Tạo `GameAdapter` trong `backend/engine/` với rules model, metadata và samples; đăng ký ở `create_registry()`.
2. Cài các method state/observation/action/result theo [interface](../backend/engine/base.py). Adapter stateless; không thay đổi snapshot/frame cũ.
3. Thêm renderer bằng `NeonRenderers.register` trong `frontend/renderers.js` nếu cần.
4. Thêm test engine, protocol và integration; bot phải khai báo đúng `game_id`.

Vòng lặp chung: observation → bot action → validate → apply → serialize → lưu replay. Lỗi runner/hạ tầng phải tách khỏi lỗi bot. [Battlecode 2026](BATTLECODE_2026.md) dùng `whole_match` và engine chính thức, không dùng protocol stdin/stdout trên.

Legacy stream: `/ws/matches/{id}?after=N`, `hello → state(seq) → complete`. Account-Only có endpoint competition theo audience và API replay Official/Scrimmage riêng. Renderer dựa trên game trong replay, không dựa trên game workspace đang chọn.
