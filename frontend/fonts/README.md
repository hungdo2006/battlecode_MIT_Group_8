# Phông chữ tự host

- **Inter Variable**: font nội dung, biểu mẫu và workspace, có ký tự tiếng Việt. Nguồn: [rsms/inter](https://github.com/rsms/inter), file InterVariable.woff2; giấy phép [SIL OFL 1.1](OFL.txt).
- **Handjet Variable**: font display của landing (phương án A được duyệt), 49,856 byte WOFF2. Tác giả Rosetta / David Březina; nguồn [Google Fonts tại revision đã kiểm tra](https://github.com/google/fonts/tree/e7db6ca603fd4862010383ff17ffd6cc4ffac1c0/ofl/handjet); giấy phép [SIL OFL 1.1](Handjet-OFL.txt). Bản TTF gốc có SHA-256 `9262749e8bb0b73ebcae0e20428689c3c59576eebeb6c4e1020300d2d41bdf4d`. Chuyển nguyên bộ glyph sang WOFF2 bằng fontTools 4.67.0 / Brotli 1.2.1; trục `wght` 100–900, `ELSH` 0–16, `ELGR` 1–2. Landing dùng weight 550, ELSH 2, ELGR 1; không trộn font khác vào hero. Đã kiểm tra ký tự tiếng Việt, cả NFC và NFD. Nội dung, biểu mẫu và tiêu đề thẻ tính năng dùng Inter.
- **VT323 Regular**: asset lịch sử của bản landing trước; hiện không preload hoặc sử dụng trong giao diện. Nguồn: [Google Fonts](https://github.com/google/fonts/tree/main/ofl/vt323), tác giả Peter Hull; giấy phép [SIL OFL 1.1](VT323-OFL.txt). Bản TTF gốc có SHA-256 `cf4de751ada78ceac033dbe16a687742939995b77bc2a052ae17a4957958594d`.
- **Source Serif 4**: asset từ thiết kế trước, không phải headline hiện tại. Nguồn: [adobe-fonts/source-serif](https://github.com/adobe-fonts/source-serif), file SourceSerif4Variable.woff2; giấy phép [SIL OFL 1.1](SourceSerif4-OFL.txt).

Inter và Source Serif 4 được lấy ngày 20/10/2026. Giữ license đi kèm khi phân phối; ứng dụng không cần font CDN.
