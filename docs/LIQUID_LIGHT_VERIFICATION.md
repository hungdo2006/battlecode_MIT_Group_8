# Phase 3 — Kiểm chứng Liquid Light UI

Ngày15/10/2026, nhánh `feature/product-polish`, Windows + Chrome headless,
Docker Desktop Linux containers. Không commit, push hoặc merge.

## Kết quả thực tế

| Kiểm tra đã chạy | Kết quả |
|---|---|
| Python unit/integration suite trên Windows | **159 passed**, 1 warning,74.36s |
| `node --check frontend/app.js` | PASS |
| `node --check frontend/renderers.js` | PASS |
| Build/khởi động Compose từ source mới | PASS |
| Ba browser/cookie session riêng, hai game, invitation/accept | PASS |
| Pause độc lập, reconnect, frame/replay/result đối chiếu ba client | PASS |
| Bộ kiểm tra Liquid Light bổ sung | **13 nhóm PASS**,0 JavaScript errors |
| Responsive Player:5 route ×7 viewport | **35 kiểm tra**, không tràn ngang document |
| Python/C++/Java qua Docker sandbox ở cả hai game | **6 trận completed**, không bot fault |
| Backend/controller restart, artifact reuse, down/up và backup | PASS |

Warning duy nhất của pytest là Starlette/httpx deprecation có sẵn.
Không chạy lại penetration/security probes của Phase2 trong đợt frontend này;
không tuyên bố sandbox có bảo đảm bảo mật mới.

## Luồng browser trên Docker sandbox thật

Lượt cuối: project QA `neon-arena-qa-c0a6808970`:

- Robot Battle: C++ vs Python, match`c80d766d4a794949`,10 frames, B thắng knockout.
- OTT v2: C++ vs Python, match`29a1ff33da5743a7`,28 frames, A thắng series2 ván.
- Cả ba phiên Organizer/Player nhận cùng match ID, frame và kết quả với replay API.
- Pause của một Player không ảnh hưởng Player còn lại hoặc backend.
- Đổi game của cuộc thi rồi mở replay cũ vẫn dùng renderer/snapshot của trận đó.

13 nhóm kiểm tra bổ sung:

1. Contrast tính từ computed styles: nút primary đạt ít nhất4.5:1, body đạt7:1.
2. Keyboard focus, Enter mở dialog, Escape đóng và xóa input mã, trả focus.
3. Form luật Robot/OTT đúng schema; thay đổi chưa lưu chặn Open; Lock chuyển read-only;
   Cancel xác nhận đóng không thay đổi trạng thái server.
4. Cancel xác nhận reset giữ nguyên cấu hình thật.
5. File sai được báo tại form; Python syntax error qua compiler sandbox trả
   diagnostics thật, không phải trạng thái giả.
6. Drag-and-drop File thật; chờ HTTP upload3s qua polling vẫn giữ disabled/busy;
   hai lần submit chỉ gửi một POST; bot thực sự compile ready và chọn Active Bot.
7. Compiler diagnostics mở rộng không tự đóng khi polling cập nhật danh sách.
8. Player Decline lời mời thật, trạng thái đồng bộ đến các client.
9. Hai bot Python wait chạy trận thật; đóng cuộc thi tạo DRAINING, giữ cấu hình
   read-only; Organizer hủy hợp lệ để giải phóng tài nguyên QA.
10. Hai Canvas sáng, seek/reset/speed, replay download chứa JSON thật đúng trận.
11. Browser offline/reconnect có phản hồi, không mất frames đang xem.
12. `prefers-reduced-motion` tác động cả CSS và Canvas.
13. Routes home/upload/create/watch/rules ở1920×1080,1440×1000,1366×768,
    1024×768,768×1024,390×844,320×740; trang LAN/protocol cũng mở được.

Một request upload được trì hoãn trong lớp vận chuyển để tạo độ trễ kiểm thử;
API response, source được compile và game state đều là dữ liệu thật.

## Regression Docker sau redesign

Project QA riêng`neon-arena-qa-e0cf950e57`:

| Game | Ngôn ngữ A / B | Match ID | Frames |
|---|---|---|---:|
| Robot | Python / C++ | c4221ea09d2e4e2e |10 |
| Robot | C++ / Java |9424a277c8e24c4f |11 |
| Robot | Python / Java | d513801884ba4e0a |10 |
| OTT | Python / C++ |1a1a2a1633a048d0 |28 |
| OTT | C++ / Java | f4bd211839604100 |28 |
| OTT | Python / Java | a46c896386ff48e6 |28 |

Cả sáu trận completed. Ba WebSocket stream khớp replay. Restart backend/controller
chạy lại artifact được; down/up giữ sessions/settings/submissions/history/replays.
Backup tar được mở kiểm tra data/uploads/artifacts, không chứa `.env`.
Các project/container/network/volume QA được dọn riêng; dữ liệu ứng dụng không bị sửa.

## Ảnh chụp thực tế

Ảnh được chụp từ Chrome với server thật; không dùng ảnh AI hoặc mockup. Screenshot
đưa scroll về đầu trang và hoàn tất CSS transition để tránh ảnh chụp giữa animation.

- [Overview](screenshots/liquid-light/overview.png)
- [Organizer / Robot rules](screenshots/liquid-light/organizer-robot-rules.png)
- [Organizer / OTT rules](screenshots/liquid-light/organizer-ott-rules.png)
- [Submission](screenshots/liquid-light/submission.png)
- [Compiler error](screenshots/liquid-light/compile-error.png)
- [Invitation](screenshots/liquid-light/robot_battle-invitation.png)
- [DRAINING](screenshots/liquid-light/competition-draining.png)
- [Robot Arena / replay](screenshots/liquid-light/arena-robot_battle.png)
- [OTT Arena / replay](screenshots/liquid-light/arena-ott_v2.png)
- [History](screenshots/liquid-light/history.png)
- [Mobile390px](screenshots/liquid-light/mobile-rules.png)

Đã xem lại ảnh thực tế để kiểm tra tính thống nhất màu, sidebar, bảng, typography
và trạng thái. Chưa kiểm thử Safari/Firefox, hai laptop vật lý, screen reader,
máy chiếu hoặc đo GPU/FPS. Không coi contrast/keyboard checks là chứng nhận WCAG đầy đủ.

Xem [LIQUID_LIGHT.md](LIQUID_LIGHT.md) để chạy ứng dụng và QA lại.
