"use strict";

(() => {
  const target = document.querySelector("#examples");
  const back = document.querySelector("#protocol-back");
  const retry = document.querySelector("#examples-retry");
  function action(message, label, href) {
    target.textContent = message;
    const link = document.createElement("a");
    link.className = "text-button";
    link.textContent = label;
    link.href = href;
    target.append(document.createElement("br"), link);
  }
  async function load() {
    retry.hidden = true;
    target.textContent = "Đang tải bot mẫu…";
    try {
      const healthResponse = await fetch("/api/health");
      if (!healthResponse.ok) throw new Error("Máy chủ chưa sẵn sàng.");
      const health = await healthResponse.json();
      let prefix = "/api";
      if (health.account_only) {
        prefix = null;
        for (const audience of ["admin", "player"]) {
          const response = await fetch(`/api/${audience}/auth/me`);
          if (response.ok) {
            prefix = `/api/${audience}`;
            back.href = audience === "player" ? "/#upload" : "/#home";
            back.textContent = audience === "player" ? "← Trở về Team & Bot" : "← Về workspace";
            break;
          }
          if (![401, 403].includes(response.status)) throw new Error(response.status === 429
            ? "Máy chủ đang giới hạn yêu cầu. Chờ một lát rồi thử lại." : "Không kiểm tra được phiên đăng nhập.");
        }
        if (!prefix) {
          back.href = "/?auth=login&returnTo=upload";
          back.textContent = "Đăng nhập để nộp bot →";
          action("Đăng nhập để tải bot mẫu theo game. Sau khi đăng nhập, bạn sẽ trở lại đúng mục Bot mẫu.", "Đăng nhập để xem bot mẫu →", "/?auth=login&returnTo=examples");
          return;
        }
      } else {
        back.href = "/#upload";
        back.textContent = "← Trở về Team & Bot";
      }
      const response = await fetch(prefix + "/games");
      if (!response.ok) {
        if ([401, 403].includes(response.status)) {
          action("Phiên đã hết hạn. Đăng nhập lại để tải bot mẫu.", "Đăng nhập →", "/?auth=login&returnTo=examples");
          return;
        }
        throw new Error("Không tải được danh sách game từ máy chủ.");
      }
      const data = await response.json();
      if (!Array.isArray(data.games)) throw new Error("Dữ liệu danh sách game không hợp lệ.");
      target.replaceChildren();
      for (const game of data.games) {
        const row = document.createElement("p");
        row.textContent = game.name + ": ";
        for (const sample of game.samples || []) {
          const link = document.createElement("a");
          link.className = "text-button";
          link.href = `${prefix}/games/${encodeURIComponent(game.game_id)}/samples/${encodeURIComponent(sample.language)}`;
          link.textContent = sample.language + " ⇩";
          row.append(link, document.createTextNode("   "));
        }
        if (!game.samples?.length) row.append("Chưa có bot mẫu cho game này.");
        target.append(row);
      }
      if (!data.games.length) target.textContent = "Chưa có game được cài đặt trên máy chủ.";
    } catch (error) {
      target.textContent = (error instanceof TypeError ? "Mất kết nối với máy chủ." : error.message) + " Bấm Thử lại để tải bot mẫu.";
      retry.hidden = false;
    }
  }
  retry.addEventListener("click", load);
  load();
})();
