# Phông chữ tự host

- **Inter Variable**: font nội dung, biểu mẫu và workspace, có ký tự tiếng Việt. Nguồn: [rsms/inter](https://github.com/rsms/inter), file InterVariable.woff2; giấy phép [SIL OFL 1.1](OFL.txt).
- **VT323 Regular**: font tiêu đề pixel của landing page, 32.1 kB WOFF2, hỗ trợ tiếng Việt. Nguồn: [Google Fonts](https://github.com/google/fonts/tree/main/ofl/vt323), tác giả Peter Hull; giấy phép [SIL OFL 1.1](VT323-OFL.txt). Bản TTF tải ngày 26/10/2026 có SHA-256 `cf4de751ada78ceac033dbe16a687742939995b77bc2a052ae17a4957958594d`. Chuyển nguyên bộ glyph sang WOFF2 bằng fontTools 4.67.0, Brotli 1.2.1; đã kiểm tra cmap của toàn bộ U+1EA0–U+1EF9, Đ/đ, Ă/ă, Â/â, Ê/ê, Ô/ô, Ơ/ơ, Ư/ư và nội dung tiêu đề. Không ghép dấu từ font fallback.
- **Source Serif 4**: asset từ thiết kế trước, không phải headline hiện tại. Nguồn: [adobe-fonts/source-serif](https://github.com/adobe-fonts/source-serif), file SourceSerif4Variable.woff2; giấy phép [SIL OFL 1.1](SourceSerif4-OFL.txt).

Inter và Source Serif 4 được lấy ngày 20/10/2026. Giữ license đi kèm khi phân phối; ứng dụng không cần font CDN.
