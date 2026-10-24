# B1.2 — Chi phí và Free Tier theo account

Ngày đối chiếu nguồn công khai: **24/10/2026**. **Account-specific: BLOCKED** —
phiên chuẩn bị không có AWS CLI/connector Billing, ngày mở account, plan,
region, số dư/hạn credit hoặc allowance còn lại. Không đọc `.aws`/production
secrets. Không suy ra account miễn phí từ việc website production đang chạy.

## Owner cần kiểm tra trước khi duyệt VM

Trong Billing/Cost Management của **đúng account**, owner ghi riêng: ngày mở,
Free/Paid/legacy plan, credit còn lại và expiry, Free Tier usage còn lại trong
tháng (kể cả production đang tiêu thụ), region và quote instance/OS/storage/IP/
egress mong muốn. Account thuộc Organizations/billing transfer cần owner kiểm
tra entitlement thực tế, không chỉ nhìn tên instance. Không gửi access key,
account password, TOTP hay số thẻ cho Codex.

- Tài khoản mở trước 15/07/2025 dùng mô hình legacy với cửa sổ giới thiệu 12 tháng.
  Tại ngày báo cáo, các account thuộc nhóm đó đã qua cửa sổ 12 tháng; Always Free
  hoặc credit khác vẫn phải kiểm tra riêng. [EC2 Free Tier usage](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-free-tier-usage.html).
- Với chương trình mới, AWS mô tả Free plan tối đa sáu tháng hoặc tới khi hết
  credit; Paid plan tính usage ngoài credit/entitlement. Account mới có credit
  khởi đầu và cơ hội nhận thêm, không đồng nghĩa VM mới miễn phí vô điều kiện.
  [AWS Billing Free Tier](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/free-tier.html),
  [Choosing a plan](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/free-tier-plans.html).
- Public IPv4 chuẩn có giá công khai **USD 0,005/địa chỉ/giờ** cho cả in-use và
  idle. Ví dụ riêng khoản này: một IP giữ hai giờ có gross USD 0,01 trước
  entitlement/tax. [VPC pricing](https://aws.amazon.com/vpc/pricing/).
- EBS tính theo dung lượng provisioned và thời gian giữ; IOPS/throughput vượt
  baseline, snapshot và tax có thể thêm phí. Stop VM không làm volume biến mất.
  [EBS pricing](https://aws.amazon.com/ebs/pricing/).
- Stop EC2 dừng compute billing khi instance đã stopped, nhưng storage và một
  số tài nguyên IP vẫn có thể tính phí. Public IP có thể đổi sau stop/start,
  cần owner cập nhật DNS/plan cho staging. [EC2 lifecycle](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-instance-lifecycle.html).

## Worksheet và calculator offline

Copy `deploy/b1-pilot-plan.example.json` sang `.b1-pilot/plan.json`, điền thông
tin không bí mật của account và quote **đúng region** từ
[AWS Pricing Calculator](https://calculator.aws/), [EC2 On-Demand](https://aws.amazon.com/ec2/pricing/on-demand/),
[EBS](https://aws.amazon.com/ebs/pricing/), [VPC](https://aws.amazon.com/vpc/pricing/).
Ghi ngày/nguồn quote trong ghi chú private. Không dùng rate test fixture làm giá AWS.

```powershell
.\.venv\Scripts\python.exe scripts/check_b1_wan_preflight.py cost --plan .b1-pilot/plan.json
```

Tool không gọi AWS, không tự lấy hoặc trừ credit. Công thức gross lập kế hoạch:

```text
compute = hourly_rate × runtime_hours
EBS = provisioned_GB × GB_month_rate × storage_hours / 730
IPv4 = number_of_addresses × hourly_rate × address_retention_hours
egress = GB × reviewed_rate
gross = compute + EBS + IPv4 + egress + other_cost_usd
```

730 giờ là giả định tháng lập kế hoạch, không phải hóa đơn hay cách AWS luôn
chia tháng. Điền `other_cost_usd` cho DNS/hosted zone/domain, snapshot/backup,
surplus CPU credits (nếu instance burstable), additional IOPS/throughput, logs,
tax và phí khác đã review. Ghi rõ những khoản chưa biết, không đặt 0 để bỏ qua.
Tham khảo điều kiện CPU credit và data transfer tại
[EC2 On-Demand pricing](https://aws.amazon.com/ec2/pricing/on-demand/).

Thiếu metadata/rate → BLOCKED. Gross vượt cap → FAIL. PASS chỉ là phép tính đủ
input và trong cap, **không xác minh entitlement/credit hoặc phê duyệt triển khai**.
`account_free_tier_verified` luôn false. Owner vẫn phải ký review Billing.

## Đề xuất pilot ngắn hạn, chưa thực hiện

Chuẩn bị checkout/image/keys/checklist trên laptop trước; owner chọn một cửa sổ
pilot hữu hạn (ví dụ hai giờ), budget cap và thời gian retention riêng cho EBS/
IP/backup. Chỉ cấp VM sau khi quote và approval rõ ràng; không mặc định chọn
micro/Free Tier khi chưa đủ RAM/build/disk hoặc entitlement.

Không thêm NAT Gateway/load balancer/RDS/domain mới chỉ để thử B1 nếu chưa có
review chi phí riêng; cấu hình repo dùng Arena+Caddy trên staging VM độc lập.
Nếu dùng subdomain của domain hiện có, owner vẫn phải kiểm tra DNS/hosted-zone
charges. Budget/alert là bước owner duyệt. Cap trong plan là ngưỡng review của
operator; công cụ không cấu hình hoặc thực thi AWS spending limit và không tự
tạo dịch vụ theo dõi trong đợt chuẩn bị.

Kết thúc: owner xác minh ID/tag staging rồi dừng hoặc xóa theo retention đã ký;
release IP, xem EBS/snapshot/DNS/log còn giữ và review Billing sau phiên. Không
xóa gì thuộc production. Chưa có approval → không tạo/start VM, DNS hay dịch vụ.
