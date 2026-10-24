# B1.2 — Báo cáo chuẩn bị pilot WAN

Ngày: 24/10/2026, Asia/Saigon. Theo [Issue #29](https://github.com/hungdo2006/battlecode_MIT_Group_8/issues/29).
Baseline `main`: `043c6b1b8aa02cbd6ed87797319b660ff325b2a6` (PR #28 đã merge).
Nhánh chuẩn bị riêng: `feat/b1-2-wan-pilot-preparation-20261024`.

**Đã chuẩn bị hướng dẫn và công cụ; chưa có kết nối WAN/staging thật.** Không
tạo AWS resource, deploy, SSH production, đọc production secret/volume hoặc merge.

## Những phần đã hoàn thành

| Phần | Kết quả |
| --- | --- |
| Rà soát Issue/runbook/hai Compose B1 | DONE; dùng `main` mới nhất, không overlay compose production |
| [Runbook operator](docs/B1_WAN_PILOT_RUNBOOK.md) | DONE: approval → hai checkout → env riêng → MFA → Cloud/Worker → probe → Official/replay → outage → restore/cleanup |
| [Checklist PASS/FAIL/BLOCKED](docs/B1_WAN_ACCEPTANCE_CHECKLIST.md) | DONE; nhận dạng SHA/image/host, evidence kín và gate riêng cho WAN/backup |
| [Cost/Free Tier review](docs/B1_WAN_COST_REVIEW.md) | DONE ở mức chính sách/worksheet/nguồn AWS; entitlement account thực tế BLOCKED |
| Template `deploy/b1-cloud.env.example` / `b1-worker.env.example` | DONE; token Controller chỉ có ở Worker, không chứa key thực tế |
| Template `deploy/b1-pilot-plan.example.json` | DONE; metadata non-secret, IP/revision/rates và approval chưa điền |
| `scripts/check_b1_wan_preflight.py` | DONE: config, inventory local pilot, HTTPS GET pinned IP, calculator gross offline |
| Kiểm thử preflight | **55 PASS**, không live WAN/AWS/DB hoặc Docker job |
| Resolve Cloud/Worker Compose bằng key giả | **PASS**; chỉ `docker compose config`, chưa tạo service |
| Docker Desktop preflight | **PASS**, context local `desktop-linux`, Linux Engine `29.8.2` |
| Hồi quy đầy đủ | **720 PASS** trong 170,22 giây; một deprecation warning Starlette/httpx có sẵn |

Công cụ dùng stdlib Python + Git/Docker CLI. Không có lệnh provision AWS, SSH,
start/stop container, thay đổi firewall, DB, backup/restore hoặc xóa trong script.
Default config dùng key giả; private env chỉ được đọc khi operator chọn rõ file
trong `.b1-pilot/<role>.env`. Không tự đọc `.env` đang dùng. Output không chứa
env/credential/body HTTP; lỗi chỉ có mã chẩn đoán. `.b1-pilot/` bị Git và Docker
build context bỏ qua; `.qa-evidence/` giữ evidence local ngoài commit.

## Phân biệt những gì tool chứng minh

- Config PASS: mô hình Compose có namespace/volume/project riêng, strict
  Account-Only/MFA và giới hạn socket/port; chưa chứng minh live deployment.
- Host PASS: inventory đúng project và checkout SHA sạch; image IDs được ghi
  riêng. Operator vẫn phải đối chiếu ánh xạ build/SHA, không tự nhận image đúng
  revision chỉ vì checkout đúng.
- HTTPS PASS: DNS staging trong approved IP, TLS/hostname verification, health
  và anonymous machine rejection đúng. Chưa chứng minh hai máy vật lý, toàn bộ
  luồng bot/match, public issuer được operator review hoặc backup/restore.
- Cost PASS: phép tính gross đủ dữ liệu và trong cap; không trừ credit, không
  xác minh Free Tier, không cấp quyền tạo VM. Giá/rate phải do owner điền đúng
  region và kiểm tra Billing đang dùng chung với production.

Trong phiên này, HTTPS thật **NOT RUN/BLOCKED**: không có FQDN/IP staging được
duyệt. Mẫu plan không thể mở mạng khi approval còn false. Công cụ chỉ có GET
health và GET machine poll không bearer/cookie; không connect/disconnect runner
hay tạo trận qua endpoint. IP pin giữ SNI; không redirect/proxy/custom-CA bypass.

## Những việc còn cần owner thực hiện

1. **Billing:** cung cấp thông tin không bí mật: ngày mở account, plan, region,
   credit còn lại/expiry, allowance đã dùng, quote và budget cap. Không cần
   cung cấp AWS access key, SSH key, password hoặc TOTP. Hiện không có AWS CLI/
   Billing connector nên không thể kết luận account có được miễn phí.
2. **Phê duyệt:** duyệt chi phí, cửa sổ chạy/retention, VM/DNS/storage staging
   độc lập và quyền operator; sau đó owner mới cấp hạ tầng. Chưa có phê duyệt
   thì không triển khai dù config PASS.
3. **Thông tin staging:** chốt FQDN/IP/resource IDs/tag, production exclusion IPs,
   approved full SHA/image mapping; điền private plan và ba key đúng vai trò
   qua kênh kín. Không dùng secret hoặc cert production.
4. **Bootstrap staging:** owner chạy CLI offline để migrate/check data mới,
   tạo Admin và enroll TOTP trong terminal riêng. Giữ public MFA và TLS thật.
5. **Laptop:** Docker Desktop Linux, điện ổn định và sleep/lid phù hợp. Policy
   đọc được hiện tại là 60 phút AC/10 phút pin; đợt chuẩn bị không thay đổi.
6. **Pilot:** chạy probe offline/online từ laptop, rồi manual Official/replay/
   standings/two-match queue, outage/recovery và metrics theo checklist. Có
   approval riêng cho mất mạng thật, không tắt mạng/Engine gây ảnh hưởng việc khác.
7. **Restore/cleanup:** review phương pháp cold backup hai bộ storage + images/
   gateway state, drill restore vào project mới, fence auth; sau nghiệm thu owner
   stop/xóa tài nguyên staging đúng ID/tag và kiểm tra Billing còn lại.

Chưa PASS WAN và restore thật → không đánh dấu B1 production-ready. Không tự
merge PR chuẩn bị này và không thay đổi AWS production.

## Evidence local và cách kiểm tra ngay

Evidence local: `.qa-evidence/b1-2-preparation/` (không commit). Tất cả trạng thái
prepared/test ở trên được tách khỏi nghiệm thu WAN thực tế; checklist tracked
giữ BLOCKED cho tới khi operator chạy trên staging đã duyệt.

```powershell
.\.venv\Scripts\python.exe scripts/check_b1_wan_preflight.py config --role cloud
.\.venv\Scripts\python.exe scripts/check_b1_wan_preflight.py config --role worker
.\.venv\Scripts\python.exe scripts/check_b1_wan_preflight.py cost --plan deploy/b1-pilot-plan.example.json
.\.venv\Scripts\python.exe -m pytest tests/test_b1_wan_preflight.py -ra
```

Exit code: PASS=0, FAIL=1, BLOCKED=2. Cost với template chưa điền phải BLOCKED.
Lệnh HTTPS live chỉ chạy sau khi owner cung cấp staging riêng và bật approval
trong private plan lẫn flag `--ack-staging-only`; không thử với endpoint production.
