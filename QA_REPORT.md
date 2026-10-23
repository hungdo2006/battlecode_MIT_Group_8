# NEON ARENA — QA Admin / Player sau PR #20

Ngày kiểm thử: **23/10/2026, Asia/Saigon**. Baseline: main **`8eb84657c892ed8cf456e2c97d61d24a846e9dcb`** (PR #20). Nhánh sửa: `qa/ux-simplification-pr20`, commit ứng dụng **`6aefe26`**.

**Kết luận:** Các luồng UI đã kiểm tra đạt sau khi sửa các lỗi dưới đây: **23 nhóm Playwright MCP**, **105 tổ hợp trang/vai trò/kích thước**, **547 test Python/controller** và bốn browser checker. Đây là nghiệm thu chức năng/giao diện trên môi trường local có runner fixture; **chưa nghiệm thu thực thi Docker hoặc triển khai production**.

## 1. Phạm vi và môi trường

- Đã fetch và fast-forward main tới PR #20, đọc `docs/UX_SIMPLIFICATION.md`, tạo nhánh mới trước khi sửa. Không commit trực tiếp vào main, không merge PR sửa và không thay đổi AWS.
- Windows, Python 3.13.12 trong `.venv`, Node; trình duyệt Chromium qua Playwright MCP. Desktop/tablet/mobile là viewport giả lập, không phải thiết bị vật lý.
- Hai server loopback tạm lần lượt tại cổng 8792 và 8793; DB schema **20**, thư mục data/uploads tạm do `TemporaryDirectory` quản lý. Chỉ sử dụng tài khoản QA, hai đội, giải loại trực tiếp và giải vòng tròn từ đợt đăng ký.
- Auth, membership, bot ownership, CSRF, upload journal, luật vòng, lịch Official, chốt bot, bảng điểm và replay API dùng backend thật. Python được kiểm tra cú pháp thật; metadata artifact và kết quả trận/replay là **fixture có nhãn `qa_fixture`**. Không thực thi bot trong tiến trình web hoặc giả nhận đã chạy Docker.
- `docker version` đã kiểm tra cả ngoài sandbox: không có pipe `dockerDesktopLinuxEngine`. Vì vậy Docker build, sandbox execution, crash/restore và kiểm thử tải là **BLOCKED/NOT RUN** trong lượt này.
- Báo cáo QA cũ đã được sao lưu vào `.qa-evidence/pr20/previous-QA_REPORT.md`. Thư mục `design-research/` có sẵn được giữ nguyên. Không dùng hoặc xóa dữ liệu production.

## 2. Lỗi phát hiện và sửa

| ID | Mức độ | Tái hiện / trước sửa | Sửa và kiểm chứng lại |
| --- | --- | --- | --- |
| UX01 | High | Player không đổi được `Game của bot`. Khi giải dùng OTT Advanced nhưng mặc định là Robot Battle, selector bị khóa; thử nộp game khác nhận 409 vì API Team bot dùng gate của game mặc định. | Tách lựa chọn game cho bot khỏi mặc định. Mẫu, giao thức, upload, bot đại diện và tiến độ dùng cùng game đã chọn; thay đổi mặc định không ghi đè lựa chọn. API vẫn kiểm tra game đã cài, membership, CSRF và journal nhưng bỏ gate legacy khỏi Team upload. **FAIL → PASS**, P02/P05 và 3 integration case mới. |
| UX02 | Medium | Menu mobile có `details` nâng cao nhưng vòng Tab bỏ qua summary và tính cả link đang bị đóng. Tab cuối không quay về đầu; checker Account UI thất bại. | Vòng focus gồm summary và chỉ lấy phần tử thực sự hiển thị. **FAIL → PASS** khi menu nâng cao đóng/mở, Tab/Shift+Tab/Escape. |
| UX03 | Medium | Header `SETUP/OPEN · Cuộc thi...`, hộp thoại “Đóng cuộc thi” và trang “Mùa thi đấu” vẫn khiến phạm vi mặc định/Season/giải khó phân biệt. Trang Player cũng dùng lời dẫn dành cho Admin. | Header, banner, xác nhận và toast nói rõ phạm vi game mặc định; Season thống nhất thành **Đợt đăng ký**; giải/luật vòng/lịch Official cấu hình riêng. Lời dẫn theo vai trò. **FAIL → PASS** trong walkthrough khác game mặc định và đăng ký → tạo giải. |
| UX04 | Medium | Member nhận CTA “Chọn bot đại diện” dù thao tác chỉ thuộc Captain. Backend vẫn chặn đúng quyền. | Member được dẫn tới “Xem bot của đội”; hướng dẫn nhờ trưởng đội chọn. **FAIL → PASS**, browser checker kiểm tra CTA và MCP kiểm tra request giả bị 403. |
| UX05 | Medium | Sau lưu nháp luật, editor vòng tự đóng. Rerender danh sách giải tạo lại checkbox đội, làm mất lựa chọn đang soạn. | Giữ trạng thái mở theo khóa giải/vòng và giữ các đội được chọn còn hợp lệ. **FAIL → PASS**, A05 và regression browser mới. |
| UX06 | Low | Console Chromium báo pattern mã đội không hợp lệ với chế độ regex `v`; pattern username có cùng dạng dấu `-`. Phần mở đầu nói ba bước trong khi hướng dẫn có bốn bước. | Escape dấu gạch ngang, kiểm tra mọi HTML pattern bằng RegExp `v`; sửa mô tả bốn bước. **FAIL → PASS**, không còn console error regex sau sửa. |
| UX07 | Low | Luật đã công bố hiển thị JSON thô; hai ô thời gian xếp lịch chỉ có aria-label, thiếu nhãn nhìn thấy. | Hiển thị từng giá trị bằng nhãn từ schema, tên game thân thiện; thêm nhãn **Khóa bot / Thi đấu**. **FAIL → PASS**, Admin/Player đọc được luật đã công bố, keyboard/form-label audit đạt. |

Giữ nguyên migration 1–20, ranh giới Admin/Player/Captain, nguồn đối thủ, snapshot và ưu tiên dispatcher. API upload legacy vẫn giữ gate game mặc định. **Không cần migration mới cho bản sửa QA này.**

## 3. Ca kiểm thử Playwright MCP

PASS dưới đây chỉ áp dụng phạm vi được mô tả. Những ca có kết quả trận dùng fixture không chứng minh bot thi đấu Docker thật.

| ID | Ca kiểm thử | Kết quả |
| --- | --- | --- |
| P01 | Hai Player tạo hai đội; Captain mời Member, Member nhận lời; Captain xác nhận đội sẵn sàng; Member không có nút kích hoạt | PASS |
| P02 | Chọn OTT Advanced, nộp mẫu và chọn bot đại diện khi Robot Battle mặc định đang khóa; không đổi cấu hình toàn cục | PASS |
| P03 | Tìm đợt đăng ký từ trang Giải đấu, cả hai Captain đăng ký đội | PASS |
| P04 | Member nộp Python lỗi rồi file hợp lệ, xem SyntaxError; request chọn bot giả bị backend 403 | PASS |
| P05 | Admin đổi game mặc định; game bot đã chọn và game ban đầu được pin của Player không bị ghi đè; xác nhận mở khóa nói rõ phạm vi | PASS |
| A01 | Admin tạo/bắt đầu giải OTT Advanced trong lúc game mặc định Robot Battle khóa | PASS |
| A02 | Form luật chặn số ngoài phạm vi; nháp không xuất hiện với Player; công bố có xác nhận và hạn chỉnh bot | PASS |
| A03 | Xếp lịch Official từ giải, hủy có xác nhận rồi xếp lại; giữ fixture và luật đã công bố | PASS |
| A04 | Admin xem danh sách đội đăng ký, đóng đăng ký và chốt đội để tạo giải vòng tròn | PASS |
| A05 | Refresh không mất tên/checkbox đang soạn; lưu nháp giữ editor mở; luật công bố đọc bằng nhãn | PASS |
| A06 | Admin mở tab Đội, xem thành viên, trạng thái và quân số/giới hạn | PASS |
| A07 | Giải liên kết đợt đăng ký: công bố luật, xếp lịch và đối soát kết quả fixture trước khi công bố nhà vô địch | PASS — fixture |
| R01 | Chốt bot/claim Official, lưu terminal replay fixture; service xác minh và cập nhật nhánh; bật điểm công khai | PASS — fixture |
| R02 | Player dự giải mở replay Official bằng renderer OTT Advanced | PASS — fixture |
| R03 | Admin/Captain/Member xem bảng điểm bằng filter OTT Advanced dù mặc định là Robot Battle | PASS |
| R04 | Admin xác nhận công bố nhà vô địch từ giải đã hoàn tất; hai Player đã đăng ký đều thấy kết quả | PASS — fixture |
| S01 | Khách không đăng nhập xem điểm công khai; response không có source/artifact/slot riêng tư; Player ngoài giải lấy replay bị 404 | PASS |
| U01 | Admin: 7 trang × 5 chiều rộng | PASS — 35 tổ hợp |
| U02 | Captain: 8 trang × 5 chiều rộng | PASS — 40 tổ hợp |
| U03 | Member: 5 trang × 5 chiều rộng | PASS — 25 tổ hợp |
| U04 | Menu mobile: Tab, Shift+Tab, summary nâng cao đóng/mở, Escape trả focus về nút menu | PASS |
| U05 | Avatar mở bằng bàn phím, Escape đóng và trả focus | PASS |
| U06 | Trang kết quả công khai: 5 chiều rộng, bảng cuộn trong container | PASS — 5 tổ hợp |

Chiều rộng: **1440, 1366, 768, 390, 360 px**. Tổng **105 tổ hợp** không tràn ngang, một H1 hiển thị, không trùng ID. Kiểm tra nhãn cho trường nhập hiển thị trên workspace đạt. Kiểm tra form đang mở và focus được bổ sung trong các flow và browser checker; không chỉ kiểm tra màn hình rỗng.

**Console:** không có page exception hoặc console error JavaScript/regex sau sửa. Không có HTTP 5xx/429 ngoài dự kiến trong MCP. Các 401 khi dò audience trước login, 403 cho request Member giả và 404 của replay ngoài giải là kết quả bảo mật dự kiến, không coi là lỗi runtime. Có 422 khi harness dùng giờ cũ sau khi đẩy nhanh đồng hồ và chưa chờ UI cập nhật luật; sau chờ publication/rerender thì xếp lịch và hoàn tất thành công. Không xác định đây là lỗi ngày bắt đầu Season.

## 4. Regression và khả năng tái chạy

| Nhóm | Kết quả đã chạy local |
| --- | --- |
| Python/controller baseline PR #20 | **544 PASS**, 0 FAIL, 228,15 giây |
| Python/controller sau sửa chính, thêm 3 integration case | **547 PASS**, 0 FAIL, 166,25 giây; một warning Starlette/httpx deprecation |
| Frontend contract/journey sau chốt copy và fingerprint | **22 PASS** |
| Node routing/CSRF/stale-response, JS syntax và frontend fingerprint | PASS |
| `scripts/check_account_ui.py` | PASS; bổ sung game riêng, không PUT mặc định, pattern `v`, focus menu đóng/mở; có profile/password và thu hồi hai tab |
| `scripts/check_workspace_layout.py` | PASS **120 tổ hợp**; bổ sung giữ checkbox, lưu nháp/mở editor/công bố luật |
| `scripts/check_ui_ux_report.py` | PASS, **8 chiều rộng** |
| `scripts/check_retest_regressions.py` | PASS, **14 nhóm** replay/history/late response/time/filter/metadata |
| `git diff --check` | PASS |
| Docker build / sandbox thật / crash-restore | **BLOCKED** — engine không hoạt động |
| AWS, SMTP, tải lớn, trình đọc màn hình thật, Safari/Firefox và thiết bị thật | **NOT RUN** |

Bốn browser checker ban đầu có lỗi: một lỗi focus thật và các kỳ vọng cũ về CTA, ACTIVE/MEMBER, Active Bot hoặc nội dung trước PR #20. Đã cập nhật kỳ vọng sang hành trình/nhãn mới, thêm assertion hành vi và chạy lại đạt; không skip test để lấy PASS. Một lượt regression giữa lúc sửa có fingerprint chưa tái tạo; đã tái tạo và kiểm tra lại. CI trên PR là lần kiểm tra toàn bộ riêng cho commit được push, xem trạng thái trực tiếp trên GitHub.

```text
.venv\Scripts\python.exe -m pytest tests controller_tests -ra --tb=short --durations=12 -o faulthandler_timeout=60
.venv\Scripts\python.exe -m pytest tests/test_frontend_team_contract.py tests/test_ux_journeys.py -q
node scripts/check_account_frontend_routing.cjs
node --check frontend/app.js
node --check frontend/renderers.js
node --check frontend/ui.js
node --check frontend/protocol.js
node --check frontend/lan.js
.venv\Scripts\python.exe scripts/version_frontend.py --check
.venv\Scripts\python.exe scripts/check_account_ui.py
.venv\Scripts\python.exe scripts/check_workspace_layout.py
.venv\Scripts\python.exe scripts/check_ui_ux_report.py
.venv\Scripts\python.exe scripts/check_retest_regressions.py
git diff --check
```

MCP dùng `scripts/serve_feature_qa.py --port 8793`, không dùng thư mục production. Helper có route QA để đẩy đồng hồ và tạo replay fixture; các route này chỉ đăng ký bởi helper, không có trong app production và helper không được COPY vào Docker runtime. File machine-readable của lượt MCP ở `.qa-evidence/pr20/mcp-final-results.json` (local, không chứa cookie/token).

## 5. Đánh giá khả năng hiểu Game / Season / Tournament / Official

| Khái niệm | Hành động người dùng / phạm vi sau sửa |
| --- | --- |
| Game mặc định | Cấu hình mặc định của trận tự do. Khóa/mở ở đây không quyết định game của mọi giải hoặc ngăn nộp bot game khác. |
| Đợt đăng ký (Season) | Khoảng thời gian tuyển đội; Captain đăng ký, Admin chốt đội để tạo giải và xác nhận công bố kết quả sau cùng. |
| Giải đấu (Tournament) | Chọn game, thể thức và đội; tạo vòng/nhánh, công bố luật, theo dõi bảng điểm riêng. |
| Trận chính thức (Official Match) | Một trận cụ thể trong lịch, có hạn khóa bot và giờ chạy; bot/luật được chốt, kết quả được đối soát với replay. |

Walkthrough kỹ thuật đã chứng minh game mặc định khác game giải vẫn sử dụng được, đăng ký có đường vào ngay từ Giải đấu và việc mở khóa mặc định không bị mô tả như đóng toàn bộ giải. **Chưa có nghiên cứu với giáo viên/học sinh thật**, nên không kết luận mọi người dùng đều hết nhầm lẫn.

## 6. Minh chứng và tệp thay đổi

Ảnh chỉ chứa dữ liệu giả và nhãn QA, không có credential hoặc mã nguồn riêng của người chơi:

- [Admin desktop: hướng dẫn, luật công bố, nhánh và replay](docs/screenshots/pr20-qa/admin-tournaments-desktop.png).
- [Captain mobile: tiến độ, bot đại diện và game bot riêng](docs/screenshots/pr20-qa/player-team-mobile.png).
- [Bảng điểm công khai mobile](docs/screenshots/pr20-qa/public-results-mobile.png).

Ảnh trước sửa, log và kết quả chi tiết khác nằm tại `.qa-evidence/pr20/` (Git ignore). Ảnh toàn trang mobile đã được xem trực tiếp: các thẻ, nút và trường nhập xuống dòng trong viewport; bảng công khai cuộn trong vùng của nó.

Tệp ứng dụng: `backend/bot_http.py`, `frontend/app.js`, `frontend/index.html` (kèm fingerprint). Regression: `tests/test_team_bots.py`, bốn browser checker. Fixture QA: `scripts/serve_feature_qa.py`. Báo cáo này được rà để có thể version cùng PR; không đưa trace/cookie/token/dữ liệu thật vào Git.

## 7. Đề xuất tiếp theo và điều kiện triển khai

1. Trước xếp lịch, hiển thị bot sẵn sàng theo **game của giải** cho từng đội; phân biệt đội đã xác nhận tham gia với bot đã đủ điều kiện.
2. Từ một giải, thêm đường dẫn “Chuẩn bị bot cho game này” mang sẵn game sang Đội & bot; giảm thao tác chọn tay nhưng giữ quyền Captain.
3. Thêm bộ lọc/tìm giải khi có nhiều giải; mở sẵn tab Đội từ CTA quản lý đội, giảm chiều dài màn hình mobile sau khi hoàn thành onboarding.
4. Thống nhất thêm nhãn tiếng Việt ở trang điểm công khai và các phần còn dùng mã game/format, Captain/Team/ACTIVE. Cân nhắc chú giải ngắn cho từng phạm vi và mốc thời gian Season.
5. Tổ chức usability test với giáo viên và học sinh thật, đo thời gian hoàn thành, thao tác nhầm và tỷ lệ tự hoàn thành; kiểm tra screen reader/contrast/cross-browser trước khi tuyên bố WCAG AA.
6. Chạy Docker staging riêng: compile/thi đấu thật Robot/OTT/OTT Advanced, đủ giải liên kết đợt đăng ký, ưu tiên Official, replay, recovery và tải dự kiến. Không lấy fixture làm release gate Docker.

Không thay đổi AWS trong lượt QA. Bản sửa không có migration mới; hệ thống cũ chưa ở schema 20 vẫn cần cold backup, dừng writer và offline migrate/check theo [OPERATIONS](docs/OPERATIONS.md) trước startup. Chỉ triển khai sau review và các release gate chưa chạy nêu trên.
