# NEON ARENA

**NEON ARENA** là website tổ chức giải đấu lập trình bot: người chơi đăng ký, lập đội và nộp bot; ban tổ chức tạo giải, xếp lịch, xem bảng điểm và replay. Bot được chạy trong Docker.

Có **hai cách tổ chức giải**:

| Hình thức | Người chơi truy cập | Bot chạy trên |
| --- | --- | --- |
| **Offline (phòng máy)** | Website trên PC/server của trường qua mạng LAN | Chính PC/server của trường |
| **Online (qua Internet)** | [Website NEON ARENA](https://traitimcodon.duckdns.org) đặt trên AWS | AWS hoặc PC chuyên dụng |

**Tài khoản:** Admin đăng nhập bằng **username và password**. Người chơi có thể tự đăng ký khi ban tổ chức mở đăng ký.

## 1. Thi Offline — tổ chức trong phòng máy

**Hiểu đơn giản:** Một PC/server ở trường chạy NEON ARENA. Các máy thi kết nối vào đó qua mạng LAN; khi thi có thể ngắt Internet nhưng vẫn giữ LAN. Không cần AWS.

### Chuẩn bị một lần trước giải

Cài **Git, Python 3 và Docker** trên máy chủ (Windows dùng Docker Desktop với Linux Containers, Linux dùng Docker Engine + Compose). Khi máy vẫn còn Internet, mở Terminal và chạy:

~~~bash
git clone https://github.com/hungdo2006/battlecode_MIT_Group_8.git
cd battlecode_MIT_Group_8
python scripts/setup_exam_lan.py --ip 192.168.1.20
~~~

**Đổi `192.168.1.20` thành địa chỉ IP LAN thật của máy chủ.** Script tự tạo file cấu hình, các khóa bảo mật và khóa xuất kết quả; bạn không cần tự điền những chuỗi ngẫu nhiên trong `.env`.

Khởi tạo hệ thống và tài khoản Admin (lần đầu, khi Arena chưa chạy):

~~~bash
docker compose -f compose.yaml -f compose.exam.yaml config -q
docker compose -f compose.yaml -f compose.exam.yaml build
docker compose -f compose.yaml -f compose.exam.yaml run --rm --no-deps arena python -m backend.admin_cli --data-dir /app/data migrate
docker compose -f compose.yaml -f compose.exam.yaml run --rm --no-deps arena python -m backend.admin_cli --data-dir /app/data create-admin --username organizer
docker compose -f compose.yaml -f compose.exam.yaml up -d --no-build --wait
~~~

Terminal sẽ hỏi **mật khẩu Admin**. Người chơi có thể tự đăng ký bằng username/password trong LAN; khi cần đóng đăng ký, ban tổ chức đặt `ARENA_EXAM_SELF_REGISTRATION=0` trong `.env` và triển khai lại Arena ngoài giờ thi.

**Một bước bắt buộc trước khi máy khác truy cập:** website LAN dùng HTTPS với chứng chỉ do Caddy của trường cấp. Xuất chứng chỉ CA công khai:

~~~bash
docker compose -f compose.yaml -f compose.exam.yaml cp gateway:/data/caddy/pki/authorities/local/root.crt ./arena-exam-root.crt
~~~

Cài `arena-exam-root.crt` vào **kho chứng chỉ tin cậy** trên các máy thi do trường quản lý. Sau đó mở `https://192.168.1.20` (thay bằng IP thật). Không cần tên miền hay Internet; không bỏ qua cảnh báo chứng chỉ. Xem [hướng dẫn HTTPS LAN](docs/EXAM_MODE.md) nếu cần.

### Khi tổ chức giải

1. **Trước giờ thi:** thử đăng nhập, đăng ký, nộp bot, chạy một trận luyện và xem replay. Đội kỹ thuật tách Internet khỏi mạng phòng thi nhưng vẫn giữ LAN; Docker không tự chặn Internet.
2. **Trong giờ thi:** Admin tạo giải và luật, nhận/chốt các đội, đặt giờ khóa bot và lịch đấu. Người chơi nộp bot; hệ thống xử lý các trận Official và lưu kết quả.
3. **Kết thúc:** Admin kiểm tra bảng điểm, replay và sao lưu dữ liệu ra thiết bị khác.

**Xuất kết quả ở đâu?** Sau khi giải đã hoàn tất các trận Official, đăng nhập Admin → **Giải đấu → Xuất kết quả offline**. Trình duyệt tải xuống file `neon-results-....json`. Script thiết lập LAN đã chuẩn bị khóa ký cho file này.

**Đưa kết quả lên website Online:** Vào Admin Online → **Giải đấu → Nhập kết quả giải offline**, chọn file và xem trước trước khi công bố. **Lưu ý:** AWS hệ thống AWS hiện tại hiện *chưa được cấu hình sẵn khóa xác minh file*, nên bước nhập lên AWS cần được đội kỹ thuật chuẩn bị và kiểm thử riêng. Gói này chỉ gồm kết quả/bảng điểm, **không chuyển replay hoặc tài khoản**. Xem [chuyển kết quả Offline → Online](docs/OFFLINE_RESULTS_TRANSFER.md).

## 2. Thi Online — dùng website AWS đang hoạt động

**Đơn giản nhất:** nếu AWS EC2 đã chạy NEON ARENA và Runner đang sẵn sàng, ban tổ chức và người chơi chỉ cần mở **[https://traitimcodon.duckdns.org](https://traitimcodon.duckdns.org)**. Không phải clone repo trên máy người chơi.

Ban tổ chức đăng nhập Admin, tạo giải, công bố luật và mở đăng ký; người chơi lập Team, nộp bot; Admin chốt lịch, theo dõi các trận và công bố kết quả.

Đội kỹ thuật sử dụng công cụ **Arena Operator** để kiểm tra trên **EC2 Ubuntu**:

~~~bash
cd ~/neon-arena-b1-pilot
sudo python3 -m scripts.arena_operator status
~~~

Chỉ mở giải khi Runner báo sẵn sàng. Nếu đang ở chế độ **Remote**, PC chạy bot cũng phải đang bật và kết nối; website còn hoạt động không có nghĩa là bot vẫn chạy được nếu PC đã tắt.

**Tên gọi:** Arena Server là máy AWS; Arena Worker là PC chạy bot; Arena Operator là lệnh quản lý Server. Thư mục `~/neon-arena-b1-pilot` vẫn giữ nguyên vì là đường dẫn cài đặt hiện tại. Trên EC2 chưa cập nhật mã Git, lệnh cũ `scripts.b15_pilot_runner` vẫn hoạt động như trước.

Các lệnh này chỉ dành cho **AWS hệ thống AWS hiện tại đã được triển khai**, không tự cài một AWS mới. Trước giải thật cần thử một trận, replay và backup; xem [hướng dẫn vận hành hệ thống AWS hiện tại](docs/B15_SHARED_PILOT_RUNNER_SWITCH.md).

## 3. Thi Online nhưng chạy bot bằng PC mạnh của trường

**Remote Worker là gì?** Website, tài khoản và kết quả **vẫn ở AWS**. PC trường chỉ nhận công việc chạy bot qua HTTPS, chạy trong Docker rồi gửi kết quả về AWS. Bạn **không cần copy folder `.b1-pilot`, database hay dữ liệu AWS** sang PC.

### Thiết lập PC lần đầu

Trên PC (cài Git, Python 3, Docker Desktop Linux Containers hoặc Docker Engine trên Ubuntu), clone repo rồi chạy trình tạo cấu hình:

~~~bash
git clone https://github.com/hungdo2006/battlecode_MIT_Group_8.git neon-arena-worker
cd neon-arena-worker
python scripts/setup_remote_worker.py
~~~

Script sẽ hỏi **một khóa kết nối có sẵn trên AWS** (nhập ẩn). Người vận hành EC2 cung cấp khóa qua kênh riêng tư. Khóa này chứng minh PC được phép nhận công việc. Script tự tạo **khóa Docker riêng cho PC**, namespace và thông số socket; không cần tự chỉnh năm dòng cấu hình như trước.

**Nếu thay laptop Worker cũ:** trước tiên, khi không có trận đang chạy, chuyển AWS sang Local và dừng agent của laptop cũ theo [runbook hệ thống AWS hiện tại](docs/B15_SHARED_PILOT_RUNNER_SWITCH.md). Chỉ sau đó mới khởi động Worker trên PC trường để tránh hai máy cùng dùng một khóa.

Bật Docker rồi chạy (PowerShell Windows, dùng một dòng nên Ubuntu cũng dùng được):

~~~bash
docker compose --env-file .b1-pilot/worker.env -p neon-b1-worker -f compose.remote-worker.yaml up -d --build --wait
~~~

PC chỉ kết nối **ra ngoài qua HTTPS**, không cần mở cổng cho người ngoài truy cập PC.

### Cho AWS chuyển việc chạy bot sang PC

Trên **EC2**, tại `~/neon-arena-b1-pilot`, chỉ khi không có trận hoặc lượt biên dịch đang chạy:

~~~bash
sudo python3 -m scripts.arena_operator switch --target remote --backup-directory .runner-switch/b15-backup-002
sudo python3 -m scripts.arena_operator status
~~~

`b15-backup-002` là **ví dụ từ hệ thống EC2 pilot hiện tại**; trên máy khác phải dùng backup đã kiểm tra và còn hợp lệ. Nếu EC2 đang dùng **Remote laptop cũ**, phải chuyển về Local và dừng agent laptop cũ trước khi bật Worker PC mới như hướng dẫn trên. **Không dùng hai Remote Worker cùng một khóa đồng thời.**

Muốn chạy bot trở lại trên EC2, chờ hết công việc rồi chạy:

~~~bash
sudo python3 -m scripts.arena_operator switch --target local --backup-directory .runner-switch/b15-backup-002
sudo python3 -m scripts.arena_operator status
~~~

**Giới hạn hiện tại:** chỉ **một Runner hoạt động tại một thời điểm, tối đa hai trận đồng thời**. PC mạnh hơn có thể giúp chạy bot ổn định hơn, nhưng chưa tự tăng số trận hay hỗ trợ nhiều PC chạy song song. Xem [runbook chuyển Runner](docs/B15_SHARED_PILOT_RUNNER_SWITCH.md).

## Vì sao vẫn cần vài thông số thiết lập?

- **IP LAN:** để các máy thi biết website nằm trên máy nào. Mỗi trường có IP khác nhau nên cần nhập **một lần**.
- **Khóa bảo mật:** để máy lạ không giả làm website hoặc Remote Worker. Các script đã **tự tạo khóa mới**, riêng khóa ghép nối Remote phải khớp với AWS nên cần nhập một lần.
- **HTTPS nội bộ:** để đăng nhập bằng mật khẩu an toàn hơn trong LAN; vẫn cần cài chứng chỉ CA tin cậy trên máy thí sinh.

**Không chia sẻ** file `.env`, `.b1-pilot/worker.env` hoặc khóa qua GitHub/chat. Không chạy `docker compose down -v` vì lệnh này có thể xóa dữ liệu giải đấu.
