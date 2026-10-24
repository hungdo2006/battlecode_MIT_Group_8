# B1.2 — Checklist nghiệm thu hai host qua Internet

Copy vào `.b1-pilot/acceptance.md` hoặc kho evidence kín; không điền IP/account,
session, secret hoặc ảnh thực tế vào bản tracked này. Chỉ dùng **PASS / FAIL /
BLOCKED**; chưa chạy là BLOCKED, không chuyển PASS từ unit/local Docker.

## Nhận dạng phiên

| Trường | Giá trị operator điền riêng |
| --- | --- |
| Pilot ID, operator, thời gian UTC/Asia-Saigon | BLOCKED |
| Approval chi phí / deployment / probe / outage / cleanup, người duyệt | BLOCKED |
| Staging VM ID/region/tag; FQDN/IP staging và production không trùng | BLOCKED |
| Xác nhận laptop và VM staging là hai host riêng | BLOCKED |
| Full SHA checkout Cloud / Worker, trạng thái tracked sạch | BLOCKED |
| Cloud Arena + Caddy image IDs, ánh xạ build/SHA | BLOCKED |
| Worker agent + Controller + bot toolchain image IDs | BLOCKED |
| Schema staging, source backup IDs, restore target IDs | BLOCKED |
| Thời điểm dừng/retention, dự toán gross/budget đã duyệt | BLOCKED |

## Ma trận kiểm thử

| Gate | PASS khi | Trạng thái | Evidence kín |
| --- | --- | --- | --- |
| Account/chi phí | Plan/credit/expiry/allowance account đã review, quote đúng region, có cap và approval | BLOCKED | Billing summary đã che thông tin |
| Tách production | VM/FQDN/IP/project/volume/cert/keys riêng; không SSH/probe production | BLOCKED | Inventory/attestation |
| Config Cloud | remote_sandbox, Account-Only, public HTTPS, TOTP; không socket/PC token/app port public | BLOCKED | preflight config |
| Config Worker | Controller private, agent không socket, không published port, namespace riêng | BLOCKED | preflight config |
| DNS/TLS public | DNS đúng approved staging IP, hostname/expiry/trust đúng, issuer public CA được review độc lập | BLOCKED | pinned HTTPS probe + browser issuer |
| Trước Worker | health 503, anonymous machine GET 401; Cloud vẫn lên được | BLOCKED | offline probe |
| Sau Worker | health 200, remote-outbound/ready, Account-Only/TOTP true | BLOCKED | online probe |
| Admin MFA | Password thiếu/sai OTP bị từ chối; đúng OTP đăng nhập được | BLOCKED | screenshot không OTP/secret |
| Python/C++/Java | Nguồn thật compile/runtime ở PC, artifact/toolchain đúng inventory | BLOCKED | bot IDs/status, không source riêng tư |
| Bot lỗi | Compile fail, crash, timeout phân loại đúng; không nhận nhầm lỗi hạ tầng | BLOCKED | sanitized outcomes |
| Hai trận + hàng chờ | Hai Official active đồng thời, lịch thứ ba chờ và chạy khi có chỗ | BLOCKED | system/status/time series |
| Result/replay | Outcome/terminal replay/turn/winner hoặc draw khớp; replay hợp lệ | BLOCKED | request IDs + replay hashes |
| Standings | Giải cập nhật đúng theo Official đã xác minh, không tính trận INTERRUPTED | BLOCKED | standings/fixtures hashes |
| Controlled agent stop | Hai trận đang có frame → fail closed/INTERRUPTED, không winner giả, không dispatch mới | BLOCKED | timing/status + retained replay |
| Link WAN thật | Outage được duyệt chỉ ảnh hưởng Worker staging, không production; semantics như trên | BLOCKED | thao tác/mốc thời gian |
| Reconnect | Lease/health phục hồi; Official mới PASS, claim cũ không tự replay, không orphan | BLOCKED | recovery/new-match evidence |
| Key/session | Sai key 401; worker thứ hai 409; reply stale/late không công bố | BLOCKED | codes only, không bearer/session |
| Restart Cloud/Controller | Fence epoch/claim, giữ evidence, không duplicate/winner giả; trận mới PASS | BLOCKED | before/after hashes |
| Load/latency | Ghi compile/match/roundtrip, CPU/RAM/disk; hai trận sustained theo thời lượng đã duyệt | BLOCKED | metrics + ngưỡng operator định trước |
| Cold backup/restore | Hai bộ storage + images + gateway state, restore mới, fence auth, replay/standings và trận mới PASS | BLOCKED | manifests/checksums/restore inventory |
| UI | Admin/system/Official/replay desktop/mobile qua staging, không font 403/Invalid Date/JS errors | BLOCKED | ảnh giả đã che dữ liệu |
| Cleanup/Billing | Tài nguyên staging dừng/xóa theo approval; volume ngoài pilot không chạm; chi phí còn giữ được ghi | BLOCKED | resource IDs/tags, Billing check |

## Quy tắc ghi bằng chứng

Ghi full revision, image IDs, tool version và thời gian có múi giờ cùng mỗi lần
chạy. SHA trong kế hoạch là **expected**, không phải bằng chứng live image đúng
revision; lưu ánh xạ build riêng. Probe read-only PASS không chứng minh trận đấu,
hai host hoặc backup/restore PASS. Không publish cookies, HAR, private CA/key,
password, TOTP, bearer hoặc session IDs; chụp ảnh sau khi xóa input bí mật.

Kết luận pilot do operator ghi: **BLOCKED** cho tới khi gate WAN và backup/
restore thật PASS. Không tự đánh dấu production-ready hay tự merge/deploy.
