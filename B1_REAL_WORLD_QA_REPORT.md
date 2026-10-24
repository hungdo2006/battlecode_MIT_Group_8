# NEON ARENA — Phase B1 QA và phạm vi PR

Ngày kiểm thử: 24/10/2026, Asia/Saigon (UTC+7).
Revision gốc: `b4bcc1edb8cb4bf0285aa4450cf66b9f26ce69e3`.
Nhánh: `qa/b1-real-world-20261024` → `main`.

## Kết luận và phạm vi

Worker Docker, HTTPS RPC, Official Match, replay, hai trận đồng thời, mất kết nối
và phục hồi đã PASS trên một laptop Windows. **Chưa nghiệm thu hai máy thật qua
Internet**: cần Cloud staging độc lập với domain/HTTPS công khai.

PR gồm hai bản sửa, regression test và harness QA có thể chạy lại. Báo cáo này
chỉ giữ kết quả tổng hợp; ảnh, XML/JSON, database, tài khoản/bot/kết quả giả sinh
ra và chứng chỉ QA không được đưa vào Git. Bản báo cáo đầy đủ của đợt kiểm thử
được giữ cục bộ trong `.qa-evidence/b1-pr-20261024/`.

Không có thay đổi AWS, database production, secret, Compose/Caddy production,
runner protocol, giới hạn hai trận, cơ chế CSRF hoặc chính sách Admin MFA.

## Các lỗi đã sửa

### Font HTTP 403 sau HTTPS gateway

Browser gửi Origin HTTPS khi tải font cùng site; Caddy dùng HTTP ở hop nội bộ.
Middleware trước đây so Origin HTTPS với scheme HTTP upstream nên từ chối font.

`backend/main.py` dùng `guard_account_scope` hiện có cho request có Origin ở
chế độ Public Gateway. Chỉ chấp nhận HTTPS metadata sau khi xác thực gateway
secret, Host/Origin chính xác và địa chỉ peer. Không tin `Forwarded` hoặc
`X-Forwarded-*` do client tự gửi. LAN vẫn sử dụng kiểm tra same-origin cũ.

Regression test yêu cầu font hợp lệ trả 200 với magic `wOF2`; tiếp tục từ chối
Origin/Host/port sai, gateway secret thiếu hoặc sai, duplicate headers, giả
HTTPS/client-IP/proxy headers và kết nối trực tiếp từ public peer.

### Replay hiển thị `Invalid Date`

Replay trả `created_at` dạng ISO, trong khi hàm giao diện chỉ nhận Unix seconds.
`officialDateTime` nay xử lý Unix seconds, numeric string và ISO; giá trị thiếu
hoặc không hợp lệ hiển thị dấu gạch. Đã cập nhật fingerprint frontend.

Test Node thực thi chính hàm formatter, so sánh thời điểm tương đương và kiểm
tra giá trị lỗi. Cả hai lỗi đều có regression FAIL trước sửa và PASS sau sửa.

## Kiểm thử đã thực hiện

| Hạng mục | Kết quả |
| --- | --- |
| Hồi quy toàn bộ sau hai bản sửa ở đợt QA ban đầu | **651 PASS**, một cảnh báo deprecation Starlette/httpx |
| Worker smoke, rebuild image QA | **PASS**: compile/runtime Docker thật, Controller riêng tư, agent không có Docker socket |
| Baseline HTTPS E2E | **PASS**: certificate + hostname verification, Official và replay thật, disconnect/reconnect |
| Python/C++/Java và lỗi compile/crash/timeout | **PASS**: lỗi bot xử đúng phía, không nhầm lỗi hạ tầng thành bot thua |
| Hai Official đồng thời, lịch thứ ba | **PASS**: hai active, lịch thứ ba chờ rồi hoàn tất |
| Mất mạng agent giữa hai trận | **PASS**: cả hai INTERRUPTED, không winner giả, health/upload 503 khi offline |
| Restart Controller và Cloud giữa trận | **PASS**: giữ replay, không thực thi lại claim không chắc chắn, không orphan bot sau recovery |
| Official mới sau reconnect/restart | **PASS** |
| Kết quả/replay/standings sau restart Cloud | **PASS**: cùng hash trước/sau restart |
| Sai key, competing worker, session/result không hợp lệ | **PASS**: HTTP 401/409 và không công bố kết quả giả |
| UI Admin/system/Official/replay desktop và mobile | **PASS** bằng Playwright Python + Chrome; không còn lỗi tải static hoặc `Invalid Date` |
| Cleanup | **PASS**: chỉ tài nguyên có nhãn QA; các volume có sẵn được giữ nguyên |

Lần Docker mở rộng hoàn chỉnh chạy 16 Official thật: 12 COMPLETED, bốn
INTERRUPTED có chủ đích. Retest UI sau sửa timestamp chạy thêm hai trận.
Các lượt đo recovery khoảng 30 giây khi mất mạng agent, 3 giây khi restart
Controller và 24 giây khi restart Cloud, gồm overhead quan sát/polling.
Đây không phải số đo SLA/WAN hoặc stress test.

Chạy lại khi chuẩn bị PR: **665/665 bài hồi quy PASS** trong 207,61 giây,
**43 bài focused PASS** (là tập con của bộ đầy đủ). `version_frontend --check`,
`node --check`, account routing/CSRF frontend và `git diff --check` đều PASS.
Docker acceptance với script đã rà soát PASS toàn bộ, kể cả UI, in-flight
outage/restart, Official mới sau reconnect và cleanup cả hai project. Các
kiểm tra mới cũng chứng minh cleanup/browser lỗi không thể trả exit code 0
khi nhánh `--ui-only` đang return.

## Harness và giới hạn an toàn

`scripts/check_b1_real_world_qa.py` dùng hai project Compose QA ngẫu nhiên,
database/uploads/artifacts mới và secret sinh riêng ở runtime. Chỉ đọc
`.env.example`, loại các biến `ARENA_*`/namespace của người vận hành khỏi môi
trường kế thừa. Từ chối Docker endpoint không cục bộ và Engine không chạy Linux.
Kiểm tra cả endpoint của context và `DOCKER_HOST`: override trỏ local không
được che context remote hoặc ngược lại. Trường hợp này có regression FAIL/PASS;
guard cuối cũng đã nhận đúng Docker Desktop Linux cục bộ khi chạy preflight thật.

Agent/RPC luôn xác minh TLS. Browser QA dùng exception cho CA tạm thời trong
một context Chrome trỏ tới alias QA cố định; không cài CA vào Windows và không
thay đổi trust của agent. Admin password-only chỉ bật trong Cloud QA kín có dữ
liệu giả; staging/production vẫn phải dùng TOTP.

Browser endpoint chỉ bind `127.0.0.1`. Script không mở Internet/firewall, SSH,
AWS CLI, production endpoint hoặc chạy prune. Cleanup xác minh prefix/nhãn
volume và kiểm tra không còn resource của project QA; cleanup/browser lỗi
trả mã khác 0, kể cả chế độ `--ui-only`.

Mặc định bằng chứng ghi vào `.qa-evidence/b1-real-world/` đã bị Git bỏ qua.
Thư mục bằng chứng lịch sử `docs/qa/b1-real-world-20261024/` cũng bị bỏ qua.
Không commit dữ liệu sinh ra khi chạy lại.

## Chạy lại

Yêu cầu Docker Desktop Linux containers, dependencies trong
`requirements-dev.txt`; UI cần Playwright Python và Chrome đã cài.

```powershell
.\.venv\Scripts\python.exe -m pytest tests controller_tests -ra
.\.venv\Scripts\python.exe scripts/version_frontend.py --check
node --check frontend/app.js
node scripts/check_account_frontend_routing.cjs
.\.venv\Scripts\python.exe scripts/check_remote_worker_docker.py --build
.\.venv\Scripts\python.exe scripts/check_b1_real_world_qa.py --build
```

Chỉ kiểm tra lại giao diện:

```powershell
.\.venv\Scripts\python.exe scripts/check_b1_real_world_qa.py --build --ui-only
```

CI hiện có chạy hồi quy Python/Node trên Ubuntu và Windows, quyền chỉ đọc;
không triển khai hạ tầng hoặc chạy các bài Docker/browser thay release gate.

## Các giới hạn còn lại

- Chỉ một laptop, hai project Docker; chưa có public CA/DNS/WAN/NAT/proxy của
  trường học, PC thứ hai, rút Wi-Fi thật hay sleep/restart Windows/Docker Desktop.
- Hai trận là Robot Battle, cùng hai đội/artifacts bất biến với lịch độc lập;
  chưa thử B1 + Battlecode26, raw replay lớn hoặc tải CPU/RAM cao nhiều giờ.
- Restart cùng volume không chứng minh backup/restore hai bộ storage độc lập.
- Playwright MCP không được expose trong phiên; UI dùng Playwright Python.
- Windows hiện sleep sau 60 phút AC/10 phút pin; cần chuẩn bị nguồn điện và
  chính sách sleep/lid phù hợp trước pilot. Đợt QA không đổi power policy.

Để nghiệm thu hai máy thật, cần staging VM/FQDN/storage riêng, secret mới,
Admin TOTP, cùng revision/image ở hai máy, backup/restore rehearsal và kiểm
thử hai trận qua Internet kèm ngắt/nối mạng có kiểm soát. Tham khảo
[runbook B1](docs/REMOTE_RUNNER_B1.md). PR để draft cho tới khi các gate staging
được đánh giá; không tự merge hoặc triển khai AWS production.
