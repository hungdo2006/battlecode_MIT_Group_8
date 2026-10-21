"use strict";

// Shared progressive enhancements for the workspace and standalone documents.
(() => {
  let sequence = 0;
  for (const form of document.querySelectorAll(".account-form, #account-team-create, #admin-invite-form")) {
    form.noValidate = true;
    const controls = [...form.querySelectorAll("input, select, textarea")];
    for (const input of controls) {
      const error = document.createElement("small");
      error.id = `field-error-${++sequence}`;
      error.className = "field-error";
      error.hidden = true;
      error.setAttribute("aria-live", "polite");
      input.insertAdjacentElement("afterend", error);
      input.setAttribute("aria-describedby", [input.getAttribute("aria-describedby"), error.id].filter(Boolean).join(" "));
      input.addEventListener("input", () => {
        error.hidden = true;
        input.removeAttribute("aria-invalid");
      });
      if (input.autocomplete === "new-password") {
        const hint = document.createElement("small");
        hint.id = `password-hint-${sequence}`;
        hint.className = "form-note";
        hint.textContent = "Ít nhất 8 ký tự, tối đa 1024 ký tự.";
        error.insertAdjacentElement("afterend", hint);
        input.setAttribute("aria-describedby", `${input.getAttribute("aria-describedby")} ${hint.id}`);
      }
      if (input.type === "password") {
        const wrapper = document.createElement("span");
        wrapper.className = "password-control";
        input.before(wrapper);
        wrapper.append(input);
        const toggle = document.createElement("button");
        toggle.type = "button";
        toggle.className = "password-toggle";
        toggle.textContent = "Hiện";
        toggle.setAttribute("aria-label", "Hiện mật khẩu");
        toggle.setAttribute("aria-pressed", "false");
        toggle.addEventListener("click", () => {
          const start = input.selectionStart, end = input.selectionEnd;
          const show = input.type === "password";
          input.type = show ? "text" : "password";
          toggle.textContent = show ? "Ẩn" : "Hiện";
          toggle.setAttribute("aria-label", show ? "Ẩn mật khẩu" : "Hiện mật khẩu");
          toggle.setAttribute("aria-pressed", String(show));
          input.focus({ preventScroll: true });
          if (start !== null) input.setSelectionRange(start, end);
        });
        wrapper.append(toggle);
      }
    }
    form.addEventListener("submit", event => {
      let first;
      for (const input of controls) {
        if (!input.willValidate || !input.getClientRects().length) continue;
        const value = input.value;
        let message = "";
        if (input.validity.valueMissing) message = "Vui lòng nhập hoặc chọn thông tin này.";
        else if (input.validity.typeMismatch) message = "Vui lòng nhập địa chỉ email hợp lệ.";
        else if (value && input.minLength > 0 && value.length < input.minLength) message = `Cần ít nhất ${input.minLength} ký tự.`;
        else if (input.maxLength > 0 && value.length > input.maxLength) message = `Chỉ nhập tối đa ${input.maxLength} ký tự.`;
        else if (input.validity.patternMismatch) message = input.name === "slug"
          ? "Mã đội chỉ gồm chữ cái không dấu, chữ số và dấu gạch ngang (-)."
          : input.name === "username" ? "Tên đăng nhập chỉ gồm chữ cái không dấu, chữ số và các dấu . _ - ." : "Thông tin chưa đúng định dạng yêu cầu.";
        else if (!input.validity.valid) message = "Giá trị chưa hợp lệ hoặc nằm ngoài giới hạn cho phép.";
        if (!message && input.name === "confirm_password" && value !== form.elements.password?.value) message = "Hai mật khẩu chưa trùng nhau.";
        const errorId = input.getAttribute("aria-describedby").split(" ").find(id => id.startsWith("field-error-"));
        const error = document.getElementById(errorId);
        error.textContent = message;
        error.hidden = !message;
        input.setAttribute("aria-invalid", String(!!message));
        if (message && !first) first = input;
      }
      if (first) {
        event.preventDefault();
        event.stopImmediatePropagation();
        first.focus();
      }
    }, true);
  }
  for (const pre of document.querySelectorAll(".landing-protocol pre, .protocol-document pre")) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "text-button copy-code";
    button.textContent = "Sao chép code";
    button.setAttribute("aria-live", "polite");
    button.addEventListener("click", async () => {
      const source = pre.dataset.copySource || pre.textContent;
      try {
        await navigator.clipboard.writeText(source);
        button.textContent = "Đã sao chép";
      } catch {
        let input = button.nextElementSibling;
        if (!input?.classList.contains("copy-fallback")) {
          input = document.createElement("textarea");
          input.className = "copy-fallback";
          input.readOnly = true;
          input.setAttribute("aria-label", "Code nguyên gốc để sao chép");
          button.after(input);
        }
        input.value = source;
        input.focus();
        input.select();
        if (document.execCommand("copy")) {
          input.remove();
          button.textContent = "Đã sao chép";
          button.focus({ preventScroll: true });
        } else button.textContent = "Đã chọn code. Nhấn Ctrl+C hoặc ⌘C để sao chép.";
      }
    });
    pre.after(button);
  }
})();
