# NEON ARENA

**NEON ARENA** là nền tảng tổ chức giải đấu lập trình bot. Người chơi tạo tài khoản, lập đội và nộp bot; ban tổ chức tạo giải, xếp lịch, công bố kết quả và xem replay. Hệ thống sử dụng Docker để chạy bot trong môi trường tách biệt.

Có hai hình thức tổ chức:

| Hình thức | Cách hoạt động |
| --- | --- |
| **Offline (trong phòng máy)** | Một PC/server của trường chạy NEON ARENA; các máy thi kết nối qua mạng LAN, không cần Internet trong giờ thi. |
| **Online (qua Internet)** | Người chơi truy cập [website NEON ARENA](https://traitimcodon.duckdns.org); bot chạy trên AWS hoặc PC/server chuyên dụng. |

## 1. Tổ chức giải Offline

### Cài đặt lần đầu

Chuẩn bị một PC/server có **Git, Python 3 và Docker** (Windows: Docker Desktop ở chế độ Linux Containers; Ubuntu: Docker Engine + Compose). Khi máy vẫn có Internet, mở Terminal và chạy:

~~~bash
git clone https://github.com/hungdo2006/battlecode_MIT_Group_8.git
cd battlecode_MIT_Group_8
python scripts/setup_exam_lan.py --ip 192.168.1.20
~~~

Thay `192.168.1.20` bằng **IP LAN thực tế của máy chủ**. Chương trình sẽ tự chuẩn bị các khóa và file cấu hình cần thiết.

Tiếp theo, khởi tạo NEON ARENA và tạo tài khoản Admin:

~~~bash
docker compose -f compose.yaml -f compose.exam.yaml config -q
docker compose -f compose.yaml -f compose.exam.yaml build
docker compose -f compose.yaml -f compose.exam.yaml run --rm --no-deps arena python -m backend.admin_cli --data-dir /app/data migrate
docker compose -f compose.yaml -f compose.exam.yaml run --rm --no-deps arena python -m backend.admin_cli --data-dir /app/data create-admin --username organizer
docker compose -f compose.yaml -f compose.exam.yaml up -d --no-build --wait
~~~

Terminal sẽ hỏi **mật khẩu Admin**. Sau khi thiết lập xong tài khoản Admin, người chơi có thể tự đăng ký bằng username/password trong LAN. Ban tổ chức cần thiết lập sẵn **mạng LAN và HTTPS trước buổi thi** để các máy thí sinh truy cập an toàn. Xem [Hướng dẫn HTTPS LAN](docs/EXAM_MODE.md) để biết các bước kỹ thuật chi tiết.

### Khi tổ chức giải

1. Các máy thi kết nối vào cùng mạng LAN (dây mạng hoặc Wi-Fi nội bộ) và mở `https://192.168.1.20` (thay bằng IP thật). Kiểm tra đăng nhập, nộp bot và replay trước giờ thi.
2. Admin tạo giải, công bố luật, chốt đội và xếp lịch; người chơi nộp bot và thi đấu.
3. Kết thúc, Admin kiểm tra bảng điểm và chọn **Giải đấu → Xuất kết quả offline** để tải file JSON.

**Đưa kết quả lên website Online:** Vào Admin Online → **Giải đấu → Nhập kết quả giải offline**.

## 2. Tổ chức giải Online

Với [website NEON ARENA](https://traitimcodon.duckdns.org) **đã chạy trên AWS**, người chơi chỉ cần truy cập, đăng ký tài khoản và nộp bot; không phải cài phần mềm.

Ban tổ chức đăng nhập Admin, tạo giải và luật, mở đăng ký, chốt đội, xếp lịch rồi theo dõi kết quả/replay. Xem [Hướng dẫn quản lý giải đấu](docs/TEAM_TOURNAMENTS.md).

Trước giờ thi, đội kỹ thuật kiểm tra Runner trên EC2:

~~~bash
cd ~/neon-arena-b1-pilot
sudo python3 -m scripts.arena_operator status
~~~

Chỉ mở giải khi Runner sẵn sàng và đã thử ít nhất một trận. Việc sao lưu, phục hồi và xử lý lỗi nằm trong [Hướng dẫn vận hành Arena Server](docs/ARENA_SERVER_OPERATIONS.md).

## 3. Dùng PC/server mạnh để chạy bot Online

Đây là **tùy chọn** khi muốn PC của trường xử lý bot thay cho EC2. Website, tài khoản và kết quả vẫn nằm trên AWS; PC chỉ nhận công việc, chạy bot rồi gửi kết quả về.

Trên PC có **Git, Python 3 và Docker**, thiết lập một lần:

~~~bash
git clone https://github.com/hungdo2006/battlecode_MIT_Group_8.git neon-arena-worker
cd neon-arena-worker
python scripts/setup_remote_worker.py
~~~

Chương trình sẽ hỏi **khóa kết nối đang dùng trên AWS**; lấy khóa này từ người vận hành EC2 qua kênh riêng tư. Sau đó bật Docker và chạy:

~~~bash
python scripts/arena_worker.py start
python scripts/arena_worker.py status
~~~

Cuối cùng, đội kỹ thuật chuyển nơi chạy bot từ **Local (EC2)** sang **Remote (PC)** theo [Hướng dẫn chuyển Runner](docs/ARENA_SERVER_OPERATIONS.md). Không chuyển khi đang có trận đấu và không bật hai Worker dùng chung khóa cùng lúc.

**Giới hạn hiện tại:** NEON ARENA chỉ sử dụng **một Runner tại một thời điểm**, tối đa **hai trận đồng thời**. PC mạnh hơn không tự tăng giới hạn này.

---

**Lưu ý:** Không đưa mật khẩu, file `.env` hoặc khóa kết nối lên GitHub. Không xóa Docker volume khi dọn máy vì có thể làm mất dữ liệu giải đấu.
