"use strict";

(() => {
  const origin = window.location.origin;
  document.querySelector("#current-origin").textContent = "WEBSITE / " + origin;
  const links = document.querySelector("#lan-links");
  const link = document.createElement("a");
  link.href = origin;
  link.textContent = "Mở địa chỉ website đang truy cập →";
  link.className = "text-button";
  links.append(link);
  const note = document.createElement("p");
  note.textContent = "Địa chỉ trên là địa chỉ trình duyệt của bạn đang dùng. Khi kết nối LAN, lấy IPv4 của card Wi-Fi/Ethernet trên máy host bằng ipconfig; IP trong container, WSL hoặc VPN không tự động là địa chỉ dùng được từ máy khác.";
  links.append(note);
  async function load() {
    const mode = document.querySelector("#network-mode");
    try {
      const response = await fetch("/api/health");
      if (!response.ok) throw new Error();
      const health = await response.json();
      mode.textContent = health.read_only ? "Chỉ xem live và replay."
        : health.account_only ? "Chế độ tài khoản và đội: Admin xếp lịch, Player chuẩn bị bot và theo dõi kết quả."
        : "Chế độ demo legacy: Organizer mời các Player READY.";
      if (location.protocol === "https:") mode.textContent += " Kết nối hiện tại dùng HTTPS. Chia sẻ địa chỉ website ở trên khi truy cập qua tên miền.";
      document.querySelector("#lan-retry").hidden = true;
    } catch {
      mode.textContent = "Không kiểm tra được trạng thái server. Địa chỉ website vẫn là origin đang mở ở trên.";
      document.querySelector("#lan-retry").hidden = false;
    }
  }
  document.querySelector("#lan-retry").onclick = load;
  load();
})();
