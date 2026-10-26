"use strict";

// Shared progressive enhancements for the workspace and standalone documents.
(() => {
  // Public entry is a progressive enhancement, independent of auth/business state.
  const landing = document.getElementById("account-landing");
  if (landing) {
    const header = landing.querySelector(".landing-header");
    const menu = document.getElementById("landing-menu-toggle");
    const navigation = document.getElementById("landing-navigation");
    const mobile = window.matchMedia("(max-width: 640px)");
    const closeMenu = (returnFocus = false) => {
      navigation.classList.remove("is-open");
      menu.setAttribute("aria-expanded", "false");
      if (returnFocus) menu.focus();
    };
    menu.hidden = false;
    header.classList.add("is-enhanced");
    menu.addEventListener("click", () => {
      const open = menu.getAttribute("aria-expanded") !== "true";
      menu.setAttribute("aria-expanded", String(open));
      navigation.classList.toggle("is-open", open);
    });
    navigation.addEventListener("click", event => {
      if (event.target.closest("a, button")) closeMenu();
    });
    header.addEventListener("keydown", event => {
      if (event.key === "Escape" && menu.getAttribute("aria-expanded") === "true") {
        event.preventDefault();
        closeMenu(true);
      }
    });
    mobile.addEventListener("change", () => closeMenu());
    // Additional entry points proxy the original buttons, including their disabled
    // state. Registration availability still comes exclusively from app bootstrap.
    for (const kind of ["login", "register"]) {
      const original = document.getElementById(`landing-${kind}`);
      const triggers = [...landing.querySelectorAll(`[data-landing-auth="${kind}"]`)];
      const sync = () => { for (const trigger of triggers) trigger.disabled = original.disabled; };
      new MutationObserver(sync).observe(original, { attributes: true, attributeFilter: ["disabled"] });
      sync();
      for (const trigger of triggers) trigger.addEventListener("click", () => original.click());
    }
    const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
    // Keep public section links out of the application's workspace hash router.
    // Native hrefs remain useful when JS is unavailable.
    landing.addEventListener("click", event => {
      if (event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
      const link = event.target.closest('a[href^="#landing-"]');
      const target = link && document.getElementById(link.hash.slice(1));
      if (!target) return;
      event.preventDefault();
      if (!target.hasAttribute("tabindex")) {
        target.tabIndex = -1;
        target.addEventListener("blur", () => target.removeAttribute("tabindex"), { once: true });
      }
      target.focus({ preventScroll: true });
      target.scrollIntoView({ behavior: motion.matches ? "instant" : "smooth", block: "start" });
    });
    const enter = node => {
      if (motion.matches) return;
      node.classList.add("is-entering");
      node.addEventListener("animationend", () => node.classList.remove("is-entering"), { once: true });
    };
    landing.querySelectorAll("[data-intro]").forEach((node, index) => {
      node.style.setProperty("--intro-delay", `${Math.min(index * 65, 260)}ms`);
      enter(node);
    });
    if ("IntersectionObserver" in window && !motion.matches) {
      const observer = new IntersectionObserver(entries => {
        for (const entry of entries) if (entry.isIntersecting) {
          enter(entry.target);
          observer.unobserve(entry.target);
        }
      }, { threshold: 0.08 });
      landing.querySelectorAll("[data-reveal]").forEach(node => observer.observe(node));
      motion.addEventListener("change", () => {
        if (motion.matches) {
          observer.disconnect();
          landing.querySelectorAll(".is-entering").forEach(node => node.classList.remove("is-entering"));
        }
      });
    }
  }
  // Describe scrollable tables only while their columns exceed the visible area.
  for (const region of document.querySelectorAll("[data-scroll-hint]")) {
    const hint = document.getElementById(region.dataset.scrollHint);
    if (!hint) continue;
    const sync = () => {
      hint.hidden = !region.clientWidth || region.scrollWidth <= region.clientWidth + 1;
      if (hint.hidden) region.removeAttribute("aria-describedby");
      else region.setAttribute("aria-describedby", hint.id);
    };
    const observer = new ResizeObserver(sync);
    observer.observe(region);
    sync();
  }

  for (const tablist of document.querySelectorAll("[data-tabs]")) {
    const tabs = [...tablist.querySelectorAll('[role="tab"]')];
    const select = tab => {
      for (const item of tabs) {
        const active = item === tab;
        item.setAttribute("aria-selected", String(active));
        item.tabIndex = active ? 0 : -1;
        document.getElementById(item.getAttribute("aria-controls")).hidden = !active;
      }
    };
    for (const tab of tabs) {
      tab.addEventListener("click", () => select(tab));
      tab.addEventListener("keydown", event => {
        const index = tabs.indexOf(tab);
        const next = event.key === "Home" ? tabs[0] : event.key === "End" ? tabs.at(-1)
          : event.key === "ArrowRight" ? tabs[(index + 1) % tabs.length]
          : event.key === "ArrowLeft" ? tabs[(index + tabs.length - 1) % tabs.length] : null;
        if (next) { event.preventDefault(); select(next); next.focus(); }
      });
    }
  }
  const accountMenu = document.getElementById("user-menu");
  accountMenu?.addEventListener("toggle", () => {
    accountMenu.querySelector("summary").setAttribute("aria-expanded", String(accountMenu.open));
  });
  document.addEventListener("click", event => {
    if (accountMenu?.open && (!accountMenu.contains(event.target) || event.target.closest("a, #organizer-toggle"))) accountMenu.open = false;
  });
  document.addEventListener("keydown", event => {
    if (event.key !== "Escape") return;
    const details = accountMenu?.open ? accountMenu : event.target.closest("details[open]");
    if (!details) return;
    event.preventDefault();
    details.open = false;
    details.querySelector("summary").focus();
  });
  for (const details of document.querySelectorAll(".workflow-disclosure")) {
    if (!details.querySelector("form")) continue;
    const close = document.createElement("button");
    close.type = "button";
    close.className = "button ghost small disclosure-close";
    close.textContent = "Đóng biểu mẫu";
    close.addEventListener("click", () => {
      details.open = false;
      details.querySelector("summary").focus();
    });
    details.append(close);
  }
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
        if (!message && input.name === "confirm_password" && value !== (form.elements.password || form.elements.new_password)?.value) message = "Hai mật khẩu chưa trùng nhau.";
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
