# Game adapters và protocol

`backend/matches.py` không import Robot Battle, OTT, không đọc HP/board và không rẽ nhánh theo game ID. `backend/models.py` chỉ chứa DTO chung. Luật nằm trong adapter; runner chỉ nhận command và trao đổi JSON Lines.

## Cách đăng ký game

1. Tạo module trong `backend/engine/`, viết một subclass `GameAdapter` của `base.py`.
2. Định nghĩa `rules_model` bằng Pydantic, `metadata` và `samples`. Chỉ đưa vào schema các thông số engine thật sự dùng. Các trường mặc định của schema được hiển thị tự động trên Rules UI.
3. `create_registry()` trong `backend/engine/__init__.py` gọi `registry.register(YourAdapter())`.
4. Viết bot mẫu cho observation/action của game. Mỗi source là file độc lập, Java dùng `Main`.
5. Nếu cần hình ảnh riêng, gọi `NeonRenderers.register(game_id, renderer)` trong `frontend/renderers.js`. Nếu chưa có renderer riêng, viewer hiển thị JSON state thật bằng renderer chung.

Không sửa manager, upload, compiler, WebSocket, store hoặc DTO. Test `test_installing_third_adapter_needs_no_core_change` trong `tests/test_multigame.py` đăng ký `CounterAdapter`, nộp Python bot, chạy trận ba lượt qua HTTP/WS và kiểm tra kết quả/replay.

## Interface

| Method | Dữ liệu / trách nhiệm |
| --- | --- |
| `get_metadata()` | game_id, name, version, description, turn_mode, renderer, guide, luật cố định, action_examples |
| `get_rules_schema()` | JSON Schema cho cấu hình; form dùng type/default/minimum/maximum/enum/title/description |
| `validate_rules(values)` | Validate và trả dict đầy đủ, có defaults; không dùng state toàn cục |
| `create_initial_state(rules)` | Dict state mới cho mỗi trận, dùng bộ luật đã validate |
| `get_observation(state, player)` | JSON tách biệt khỏi state, chỉ thông tin bot cần nhận |
| `get_players_to_act(state)` | `('A','B')` đồng thời; `('A',)`/`('B',)` luân phiên; `()` pha tự động |
| `validate_action(state, player, action)` | Kiểm tra schema và luật của action; raise `InvalidAction` khi sai |
| `apply_action(state, actions)` | Mapping player → action của lượt; tính state mới trên server, không sửa frame cũ |
| `is_game_over(state)` | Trận có kết quả cuối hay chưa |
| `get_result(state)` | Winner A/B/null, reason, faults và các thông tin kết quả riêng |
| `serialize_state(state)` | Bản JSON tách biệt dùng cho live/replay |
| `forfeit(state, faults)` | Xử thua khi lỗi bot; implementation chung có thể được dùng lại |

Các trường chung của frame: `game_id`, `turn` (integer sequence tăng một mỗi frame), `rules`, `actions`, `events`, `result`. State riêng của game nằm cạnh các trường này. Adapter stateless được dùng lại giữa nhiều trận, nên không giữ mutable state trận trên `self`. Rules snapshot và frame cũ phải được giữ nguyên.

Vòng lặp core:

```text
adapter.get_players_to_act(state)
   → runner.request(adapter.get_observation(state, player))
   → adapter.validate_action(state, player, output)
   → adapter.apply_action(state, validated_actions)
   → adapter.serialize_state(state)
   → lưu replay + WebSocket broadcast
```

Nếu bot lỗi, gọi `forfeit` thay cho apply. Game tự kiểm tra các điều kiện thắng, giới hạn lượt và chuyển ván. Core không truy cập các field luật riêng.

## Transport chung

- Một process mỗi bot, giữ suốt trận và các ván.
- Mỗi request: một dòng JSON UTF-8 trên stdin.
- Mỗi response: một dòng JSON trên stdout + newline + flush; stderr dành cho debug.
- 3 giây cho request đầu gồm startup, 1 giây cho request sau; output bị giới hạn.
- Python/C++/Java dùng cùng runner. C++/Java compile một lần mỗi submission, không compile mỗi lượt.
- Submission lưu `game_id`; cả hai bot phải thuộc game của trận. Không suy đoán game bằng extension hoặc nội dung code.

## Robot Battle

Envelope: `protocol=1`, `game_id=robot_battle`, `game` alias, `player`, `turn`, `rules`, `you`, `enemy`. Robot có `x`, `y`, `hp`; x sang phải, y xuống dưới. Mỗi lượt hỏi cả A/B từ cùng state trước lượt.

```json
{"type":"move","direction":"right"}
{"type":"attack"}
{"type":"wait"}
```

Move 4 hướng, damage sau move, khoảng cách Manhattan 1. Va chạm/ra biên đứng yên. Win/lượt/HP do `RobotBattleAdapter` và engine robot xử lý.

## OTT v2

Envelope: `protocol=1`, `game_id=ott_v2`, `game`, `player`, `turn`, `round`, `round_turn`, `current_player`, `rules`, `board_size=9`, `board`, `goals`, `counts`, `scores`, `last_move`, `legal_actions`.

Board là mảng 9 hàng × 9 cột; ô null hoặc `{id, owner, type}`. Owner A/B, type rock/paper/scissors. Row 0 ở dưới; col 0 bên trái. A/P1 nhắm `(8,8)` i9, B/P2 nhắm `(0,0)` a1. Chỉ hỏi bot đang đến lượt.

```json
{"action":"move","from":{"row":1,"col":3},"to":{"row":2,"col":4}}
```

`legal_actions` là danh sách đúng schema action trên. Bot có thể chọn từ danh sách hoặc tự tính. Không tin output của bot: server kiểm tra lại lượt, chủ quân, bounds, khoảng cách, cản quân và quan hệ RPS. Các trường board/winner/scores không hợp lệ trong action. Không có wait hoặc attack riêng.

`last_move` gồm player, from, to, piece_type, piece_id, captured. Lưu ý khi đọc JSON: `last_move.player` là người đi trước đó, không phải `player` của envelope. Bot mẫu C++/Java dùng regex cho schema cố định, lấy field player đầu tiên; viết bot phức tạp nên dùng parser JSON tổng quát.

Round có thể kết thúc bằng goal, elimination, turn_limit hoặc stalemate. Hai lý do cuối là mở rộng tournament để bot tự chạy hữu hạn. `round_results`/`scores` lưu lịch sử điểm; frame chuyển ván không gọi bot. Trận nhiều ván kết thúc bằng `series_complete`. Lỗi bot xử thua cả trận.

## WebSocket và replay

`/ws/matches/{id}?after=-1`: hello → state có seq → complete. `seq=0` là trạng thái đầu. `after=N` nhận từ N+1, kể cả kết nối sau khi trận đã xong. Client chậm không giữ lock mô phỏng khi gửi dữ liệu. `/api/matches/{id}/replay` trả metadata và toàn bộ frame đã lưu.

Metadata trận lưu game ID, tên, phiên bản, luật đầy đủ khi bắt đầu. Renderer dựa trên game ID của frame/trận, không dựa trên game đang được organizer chọn. Pause/Reset/Start thuộc client; server tiếp tục chạy. URL `/?match=ID#home` tự mở trận ở browser mới.

## Nguồn OTT và giấy phép

Nguồn: [hungdo2006/ottv2-playhtml](https://github.com/hungdo2006/ottv2-playhtml). Bản đọc ngày 12/10/2026 có các file js chuyển tiếp sang `src/engine`; bản chuẩn nằm trong `config/rules/standard-9x9.json`. Snapshot source + SHA-256 và MIT license được giữ tại `docs/reference/ottv2/`. Các file này chỉ là reference cho test, không được nạp vào backend runtime hoặc phục vụ như engine trên frontend. Không tích hợp playhtml, Express hoặc Socket.IO.

`tests/reference_ott.mjs` và test Python đối chiếu nước đi/kết quả với module JavaScript nguồn trên các state được sinh có seed. Node chỉ cần cho kiểm chứng này; các trận của ứng dụng chạy Python engine thuần.
