# Kiểm chứng nền tảng đa game v2

Ngày **12/10/2026**, Windows, Asia/Saigon. Source nâng cấp trực tiếp tại `D:\LTM`. Báo cáo v1 được giữ riêng ở `VERIFICATION.md`.

## Rà soát và kiến trúc

- Đọc backend, frontend, runner, store, các bot mẫu, test, scripts và tài liệu hiện tại. V1 đã có robot engine riêng nhưng Rules model/UI, việc hỏi hai bot mỗi lượt, HUD và log còn giả định Robot Battle.
- Thêm `GameRegistry` và interface `GameAdapter`. Tách RobotRules vào module game. Tournament Core, DTO và store không chứa field HP/map/damage/board hoặc nhánh xử lý từng game.
- Robot engine cũ được bọc bằng adapter, giữ luật và test. OTT được port sang Python từ source tham khảo, không dùng playhtml/Express/Socket.IO trong ứng dụng.
- Đọc README, `js/rules.js`, `js/state.js`, `js/constants.js`, `js/ui.js` và các module engine/config được chúng import. Nguồn main hiện dùng các file js làm wrapper. Snapshot, hash SHA-256 và MIT license lưu trong `docs/reference/ottv2`.
- Giữ bot/replay v1; luật cũ được chuyển sang cấu hình từng game. Submission mới bắt buộc game ID; trận mới lưu game ID, phiên bản và snapshot luật.

## Kiểm thử tự động

```text
92 passed, 1 warning in 24.33s
```

Không test skip trên máy này. Có G++ 13.2.0, JDK 21.0.8, Python 3.13.12. Node 24 dùng cho test đối chiếu nguồn; không dùng trong backend runtime.

`node --test docs/reference/ottv2/tests/rules.test.js`: **8/8 test gốc qua**. Test Python còn so sánh các nước hợp lệ/không hợp lệ, board và winner với engine JavaScript nguồn trên các state sinh có seed. `node --check` cho app.js/renderers.js qua.

Cảnh báo duy nhất là Starlette TestClient deprecating httpx trong dependency test. Không có lỗi runtime hoặc test thất bại.

## Tám yêu cầu kiểm chứng

| Yêu cầu | Đã kiểm chứng bằng | Kết quả |
| --- | --- | --- |
| Chọn Robot hiển thị đúng luật | Browser + registry schema test | Chỉ map, HP, damage, max_turns |
| Chọn OTT hiển thị đúng luật | Browser + registry schema test | Chỉ max_turns/rounds; 9×9 và luật chuẩn là thông tin cố định |
| Luật ảnh hưởng thật | Trận Robot map 8, HP 90, damage 30; OTT 2 ván; test giới hạn 3 nước | State và kết quả dùng đúng snapshot, thay cấu hình sau Start không thay trận |
| Bot khác ngôn ngữ | Python/C++ và C++/Java trên cả hai game | Compile, chạy subprocess và hoàn thành thật, không bot_error |
| Engine tính kết quả đúng | Robot tests, OTT tests, source differential | Goal hai bên, RPS, loại hết một loại, simultaneous HP, limit/draw, nhiều ván |
| Live và replay | HTTP/WS thật + Chrome | Frame live khớp JSON replay; xem lại, tua/Pause/Reset/Start/Victory hoạt động |
| Thêm game không sửa core | CounterAdapter thứ ba inject qua registry | Nộp Python, tạo trận 3 lượt, kết quả và replay qua cùng core/API |
| Nhiều máy LAN theo dõi | Private IPv4 listener, 2 WS clients, 2 browser contexts, xác nhận của người dùng | Broadcast cùng trận qua IP LAN hoạt động; người dùng xác nhận thiết bị thứ hai thấy danh sách trận |

## Trận chạy qua server thật

| Game / bot | Cấu hình | Kết quả | Frame gồm lượt 0 |
| --- | --- | --- | --- |
| Robot: Python vs C++ | 8×8, 90 HP, damage 30, max 40 | A knockout ở lượt 5 | 6 |
| Robot: C++ vs Java | Mặc định | B knockout ở lượt 10 | 11 |
| OTT: Python vs C++ | max 20, 2 ván | A thắng 2–0, kết thúc sequence 27 | 28 |
| OTT: C++ vs Java | max 100, 1 ván | A tới i9 ở lượt 13 | 14 |
| OTT qua IP LAN: Python vs C++ | max 30, 1 ván | A tới i9 ở lượt 13 | 14 |

Các frame nhận qua WebSocket được so với replay lấy qua HTTP và khớp hoàn toàn. C++/Java chỉ compile khi nộp; compiler không nằm trong vòng lặp lượt. Cache bot mẫu dùng hash source để thay đổi source tạo submission mới thay vì dùng executable cũ.

## Browser và LAN

`scripts/check_ui.py --spectator-url http://192.168.2.16:8000` chạy hai Chrome contexts độc lập: context chính dùng loopback, spectator dùng **địa chỉ LAN thực của laptop** và deep link cùng match. Cả hai nhận dữ liệu live và complete giống JSON replay, dù pause riêng. Đã kiểm tra schema động, browser validation, default reset lưu thật, game-specific upload, luật thật, nhiều ván, renderer cho replay cũ sau khi đổi game và cả năm view ở 390px. Cấu hình organizer được trả về trạng thái ban đầu sau QA.

Đã mở lại một replay OTT thật có capture ở lượt 14: event ăn quân, số Kéo của A giảm từ 3 xuống 2, hiệu ứng quân bị ăn và nội suy di chuyển được vẽ trên Canvas mà không có JavaScript error. Không tạo hoặc thay board giả để chụp ảnh; viewer dùng JSON đã lưu của trận bot đã chạy.

`scripts/check_lan.py --url http://192.168.2.16:8000 --game ott_v2 --max-turns 30` đã qua: **2 WebSocket spectators, 14 frame giống replay**. Server bind `0.0.0.0:8000`; private Host và same-origin được chấp nhận. Host public hoặc Origin khác bị từ chối trong test.

Phần đối chiếu từng frame dùng một laptop chạy nhiều client độc lập. Ngoài ra, **người dùng đã xác nhận mở `http://192.168.2.16:8000/#watch` từ thiết bị thứ hai cùng Wi-Fi và thấy danh sách trận**. Đây là xác nhận truy cập LAN thực tế; so sánh frame live/replay chi tiết được thực hiện bởi các client tự động ở trên. README có bước theo dõi cùng trận và script có thể chạy từ máy thứ hai. Không sửa firewall hệ thống tự động.

Ảnh Chrome v2:

- [Rules Robot](screenshots/v2/rules-robot.png)
- [Rules OTT](screenshots/v2/rules-ott.png)
- [Bàn OTT](screenshots/v2/ott-board.png)
- [Ăn quân trong replay OTT](screenshots/v2/ott-capture.png)
- [OTT Victory](screenshots/v2/ott-victory.png)
- [Robot Victory](screenshots/v2/robot-victory.png)
- [Upload OTT](screenshots/v2/upload-ott.png)
- [Rules mobile](screenshots/v2/mobile-rules.png)

## Phạm vi

OTT giữ luật chuẩn 9×9, đội hình, 8 hướng và cả hai điều kiện thắng. Limit/draw/stalemate, số ván và tổng điểm là mở rộng tournament đã triển khai thật. Không hỗ trợ chỉnh kích thước/đội hình/cycle OTT trong UI/API. Không có plugin marketplace, bracket tự động, tài khoản hay triển khai Internet. Chỉ chạy bot tin cậy của nhóm: subprocess không phải sandbox; giới hạn runtime/output không ngăn bot đọc/ghi file hay truy cập mạng.
