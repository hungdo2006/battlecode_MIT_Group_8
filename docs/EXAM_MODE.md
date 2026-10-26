# Hướng dẫn mạng LAN cho giải Offline

Tài liệu kỹ thuật bổ sung cho [README](../README.md). Cấu hình này chạy trên **PC/server trường độc lập với AWS**, dùng **tài khoản và mật khẩu**; Admin không cần mã xác thực qua ứng dụng. Player được tự đăng ký trong LAN theo mặc định, có thể đóng sau khi đủ đội.

## Mạng và HTTPS

Mô hình: máy thi → mạng LAN nội bộ (switch/VLAN) → PC/server chạy NEON ARENA. Internet có thể ngắt ở router/VLAN **sau khi cài đặt và diễn tập**. Không dùng EC2 làm host Offline. Docker Compose **không tự ngắt Internet**; cần quản trị mạng ngăn đường WAN, IPv6, VPN/hotspot theo quy chế.

Trên PC chủ, cài Git/Python 3/Docker và chuẩn bị khi còn Internet:

~~~bash
git clone https://github.com/hungdo2006/battlecode_MIT_Group_8.git
cd battlecode_MIT_Group_8
python scripts/setup_exam_lan.py --ip 192.168.1.20
~~~

Thay IP bằng **địa chỉ IPv4 LAN của chính PC**. Script tạo/tái sử dụng file `.env` riêng tư, sinh khóa Controller, proxy và gói xuất kết quả offline; mặc định dùng **IP trực tiếp làm địa chỉ HTTPS**, không yêu cầu thiết lập DNS. Nếu đã có cấu hình host khác, script từ chối ghi đè; cần xem xét môi trường cũ trước khi sửa thủ công.

Cài đặt và tạo Admin **trên database mới, không có Arena writer đang chạy**:

~~~bash
docker compose -f compose.yaml -f compose.exam.yaml config -q
docker compose -f compose.yaml -f compose.exam.yaml build
docker compose -f compose.yaml -f compose.exam.yaml run --rm --no-deps arena python -m backend.admin_cli --data-dir /app/data migrate
docker compose -f compose.yaml -f compose.exam.yaml run --rm --no-deps arena python -m backend.admin_cli --data-dir /app/data create-admin --username organizer
docker compose -f compose.yaml -f compose.exam.yaml up -d --no-build --wait
~~~

**Cài chứng chỉ CA công khai** do Caddy tự tạo vào kho tin cậy trên **tất cả máy thi được trường quản lý**:

~~~bash
docker compose -f compose.yaml -f compose.exam.yaml cp gateway:/data/caddy/pki/authorities/local/root.crt ./arena-exam-root.crt
~~~

Trên máy thi mở `https://192.168.1.20`. Phải đăng nhập thành công, không có cảnh báo chứng chỉ, nộp bot và xem replay. Chỉ phân phối **root.crt công khai**, không đưa khóa riêng CA ra khỏi server. Đồng hồ máy thi và máy chủ phải tương đối chính xác.

Khi cần chặn đăng ký mới, thêm `ARENA_EXAM_SELF_REGISTRATION=0` vào file `.env` rồi tạo lại riêng container Arena trong một cửa sổ bảo trì (không có trận đang chạy), với cùng hai file Compose. Không sửa trực tiếp tài khoản trong database.

## Checklist trước giờ thi

1. Mỗi máy thi phải truy cập được website qua HTTPS. Thử tạo tài khoản Player, Team, biên dịch Python/C++/Java, Official và replay.
2. Kiểm tra thí sinh không đi Internet bằng cả IPv4/IPv6/DNS khác, VPN, proxy, Wi-Fi phụ, hotspot; giám thị kiểm soát thiết bị theo quy chế. Không có phần mềm nào tự bảo đảm thí sinh không dùng AI offline.
3. Không mở Docker API, Controller port 9000, SSH hoặc port 8000 cho máy thí sinh. Chỉ HTTPS LAN là cổng được truy cập.
4. Theo dõi CPU/RAM/dung lượng, lưu backup ngoài máy chủ, chuẩn bị UPS và thử phục hồi. Bot trong Docker sandbox không có Internet hoặc Docker socket.
5. Sau khi ảnh image đã được tải đủ, có thể ngắt WAN mà vẫn giữ LAN. Nếu restart trong giờ thi, dùng `docker compose -f compose.yaml -f compose.exam.yaml up -d --no-build --wait`, không tự kéo image.

## Xuất kết quả Offline

Khi **tất cả trận Official đã hoàn tất**, Admin mở **Giải đấu → Xuất kết quả offline**. Script thiết lập LAN đã đặt khóa ký và mã nhận diện điểm thi trong `.env`; trình duyệt tải gói JSON có chữ ký.

Việc **nhập lên AWS B1.5 không tự kích hoạt**: đội vận hành cần bảo vệ và cài đặt khóa ký chung vào phía Online theo một thay đổi cấu hình được backup/kiểm thử riêng (không tự sửa model B1.5 đang pin). Xem [Offline Results Transfer](OFFLINE_RESULTS_TRANSFER.md) để biết cách xem trước, xuất bản, các giới hạn và thử trên staging. Chưa hỗ trợ chuyển replay.

**Không** kết hợp `compose.exam.yaml` với `compose.public.yaml` hoặc chạy overlay thi Offline vào project EC2 đang phục vụ Internet.
