# Kiểm chứng network multi-client v2.1

Ngày **12/10/2026**, Windows, Asia/Saigon. Bổ sung trực tiếp source tại `D:\LTM`, sau bản đa game. Không dùng Docker hay cloud; không thay đổi firewall hệ thống.

Báo cáo này ghi nhận thời điểm v2.1. Review v2.2 đã thêm Organizer/Player, lựa chọn game riêng và replay append-only; xem [REVIEW_VERIFICATION.md](REVIEW_VERIFICATION.md) cho kết quả hiện tại.

## Chức năng đã triển khai

| Yêu cầu | Triển khai / bằng chứng |
| --- | --- |
| Bind LAN | run.py mặc định `0.0.0.0:8000`; console in IPv4, đã gọi HTTP/WS qua Wi-Fi IP `192.168.2.16` |
| URL tự động | REST relative paths; WS dùng location.host/protocol, HTTPS tự chọn WSS; không hardcode localhost trong app.js |
| Mỗi người nộp bot | Cookie/nickname riêng; form multipart thực tế; mỗi submission ghi owner từ server, không tin owner do client tự gửi |
| Cùng quan sát trực tiếp | Hai socket riêng nhận cùng sequence/frame/result; slow spectator không giữ lock của simulation; Pause riêng từng browser |
| Tìm trận của người khác | Bot library và match history chung tự refresh 2 giây, hiển thị owner/creator/ID; B tìm trận A tạo qua UI và nhấn Live |
| Phân biệt phiên | Token 256 bit HttpOnly/SameSite, hash lưu disk, ID public khác token, rename validation, TTL 30 ngày, restart vẫn giữ phiên |
| Hướng dẫn tại website | `/lan`: origin/IP gợi ý từ API, checklist hai laptop, ipconfig, Private firewall/LocalSubnet, isolation, troubleshooting |
| IP/firewall | NETWORKING.md và trang /lan có lệnh kiểm tra TCP và rule Private cụ thể; app không tắt/mở firewall tự động |
| VPS/HTTPS/WSS | Exact host allowlist, read-only public mode, trusted proxy flags, Nginx template; HTTPS/WSS thật bằng certificate local đã kiểm tra |
| An toàn demo | Trusted LAN bots only, giữ timeout/output limits; domain public bắt buộc chỉ xem, upload/start/rules bị chặn cả backend; subprocess không phải sandbox |

## Test suite

- **100 test Python pass**, không skip, gồm 8 test network mới và toàn bộ engine/runner/multigame cũ. Một warning Starlette TestClient về dependency httpx, không lỗi runtime.
- **8/8 test JavaScript luật OTT nguồn pass**.
- `node --check` cho app.js/renderers.js và Python compileall pass.
- Test network bao gồm hai identity/upload/discovery/WS/reconnect, persistent/tampered/expired cookies, per-user sample cache, metadata ownership, read-only blocks, HTTPS forwarded headers từ proxy tin cậy, từ chối Origin sai và Host không được phép.

## Server/client thực tế

Uvicorn bind `0.0.0.0:8000`, gọi qua `http://192.168.2.16:8000`, không chỉ loopback.

| Kịch bản | ID trận | Kết quả / frame |
| --- | --- | --- |
| Hai HTTP cookie jars, A upload Python, B upload C++, Robot | `3005cd79bb054d13` | A knockout; 10 frame; hai WS = replay; reconnect after=5 |
| Hai HTTP cookie jars, A upload Python, B upload Java, OTT | `a5155ad818ba435d` | A tới goal; 14 frame; hai WS = replay; reconnect after=7 |
| Hai Chrome contexts, mỗi người upload PY/C++ qua form, Robot | `f5ea573e01874188` | A knockout, 28 frame; B tự thấy bot/trận, nhấn Live, Pause độc lập |
| Hai Chrome contexts, mỗi người upload PY/C++ qua form, OTT 2 ván | `512d5c13350f4c93` | A thắng 2–0, 28 frame; B tìm Live qua history; stream cùng replay |

`check_lan.py` thực sự download rồi multipart upload source bằng hai cookie jar, không dùng sample-submit chung để giả lập hai owner. `check_multiclient_ui.py` tạo hai browser contexts có cookie/ID khác nhau, nhập nickname, nộp file qua form, chờ auto-discovery ở cả hai, B tìm row trận A tạo và bấm Live khi đang running. Cả hai có WebSocket thật; A pause vẫn nhận mọi frame trong khi B playback tiến lên. Frame ở cả hai khớp HTTP replay. Không mock API/board/result.

Đã chạy lại `check_ui.py --spectator-url http://192.168.2.16:8000`: dynamic Rules, hai game, luật thực sự, defaults, old replay đúng renderer, Pause/Reset/Start/Victory và cả năm view không tràn ngang ở 390px. Trận regression `01245c427d01438f` (Robot) và `c5a545f428504b0c` (OTT). Scripts trả luật/game organizer về cấu hình trước QA.

## HTTPS và giới hạn xác minh proxy

`scripts/check_https.py --match-id 512d5c13350f4c93` đã pass: Uvicorn TLS trên port loopback tạm, certificate được xác thực bằng CA local, cookie Secure giữ cùng identity, **28 WSS frame khớp replay thật**, POST bot trả 403. Chỉ copy một replay đã hoàn tất vào folder tạm; không chạy code bot, không ảnh hưởng dữ liệu production, không sửa Windows trust store. Listener/certificate được dọn sau test.

Proxy-header tests dùng Uvicorn ProxyHeadersMiddleware: chỉ peer tin cậy được chuyển scheme thành HTTPS/WSS; spoofed forwarded scheme bị bỏ qua; Host/Origin đúng được nhận; scheme/host/port sai bị từ chối. `deploy/nginx.conf.example` theo tài liệu FastAPI/Uvicorn/Nginx. **Máy này không có Nginx và chưa triển khai VPS/domain/certificate public**, nên chưa xác minh một Nginx deployment thật. Cấu hình hiện tại phục vụ ở gốc domain `/`, một worker. Public mode chỉ xem; chưa có remote scheduler/admin.

## Hai thiết bị vật lý

Ở bước kiểm chứng trước, **người dùng đã xác nhận thiết bị thứ hai cùng Wi-Fi mở URL LAN và thấy danh sách trận**; server cũng nhận HTTP từ `192.168.2.4`. Đây là bằng chứng truy cập LAN từ thiết bị thật.

Kịch bản mới nickname → mỗi người upload → cùng xem live được tự động xác minh bằng hai clients/browser contexts độc lập trên laptop host. **Chưa có xác nhận toàn bộ kịch bản mới từ hai laptop vật lý** tại thời điểm viết báo cáo. Có checklist trong NETWORKING.md và /lan để thực hiện; không coi automation cùng máy là hai laptop.

## Ảnh QA

- [Thư viện bot và người nộp](screenshots/network/shared-bots.png)
- [Client B xem cùng trận](screenshots/network/client-b-live.png)
- [Danh sách trận và người tạo](screenshots/network/shared-match.png)
- [Trang hướng dẫn LAN](screenshots/network/lan-guide.png)

Phiên là nhận diện browser cho nhóm tin cậy, chưa có login/roles. Rules dùng chung cho nhóm, match giữ snapshot. Bot/replay cũ vẫn được giữ, UI nhận diện bản ghi chưa có owner. README và NETWORKING.md giải thích giới hạn subprocess, single worker và cách chạy Windows/LAN/proxy.
