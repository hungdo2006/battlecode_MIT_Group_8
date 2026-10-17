"use strict";

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const app = {
  bots: [], matches: [], games: [], selectedGameId: null, rules: {}, match: null, frames: [],
  cursor: 0, paused: false, speed: 1, socket: null, generation: 0,
  switchingGame: false, launching: false, transition: null, nextFrameAt: 0,
  victoryDismissed: false, displayedResult: false, reconnectTimer: null,
  participant: null, readOnly: false, refreshing: false,
  role: "player", organizerAvailable: false,
  accountOnly: false, accountAuth: false, account: null, accountAudience: null, csrf: null,
  competition: null, competitionSocket: null, competitionTimer: null,
  competitionGeneration: 0, competitionBusy: false, shuttingDown: false,
  lobby: null, invitationBusy: false, seenStarts: new Set(), seenFinishes: new Set(), heartbeatTimer: null,
  uploading: false, seeding: false, rulesBusy: false, rulesDirty: false,
  sampleBusy: new Set(), activeBotBusy: new Set(), invitationCancelling: new Set(),
  initialized: false, initializing: false, serverOnline: false, lobbyOnline: false, arenaOnline: false,
};

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function setText(selector, value) {
  const node = $(selector);
  if (node.textContent !== value) node.textContent = value;
}

// Presentation helpers never decide permissions or change server state.
function busyButton(button, busy) {
  button.classList.toggle("is-loading", busy);
  button.setAttribute("aria-busy", String(busy));
  if (busy) button.disabled = true;
}

function confirmAction(title, description, action) {
  const dialog = $("#confirm-dialog");
  if (dialog.open) return Promise.resolve(false);
  $("#confirm-title").textContent = title;
  $("#confirm-description").textContent = description;
  $("#confirm-accept").textContent = action;
  dialog.returnValue = "cancel";
  return new Promise(resolve => {
    dialog.addEventListener("close", () => resolve(dialog.returnValue === "confirm"), { once: true });
    dialog.showModal();
    $("#confirm-cancel").focus();
  });
}
$("#confirm-cancel").onclick = () => $("#confirm-dialog").close("cancel");
$("#confirm-accept").onclick = () => $("#confirm-dialog").close("confirm");

const statusLabels = { READY: "Sẵn sàng", ONLINE: "Đang online", OFFLINE: "Offline", INVITED: "Được mời", IN_MATCH: "Đang đấu", PENDING: "Chờ phản hồi", PARTIALLY_ACCEPTED: "Chờ đối thủ", STARTED: "Đang thi đấu", FINISHED: "Đã kết thúc", DECLINED: "Đã từ chối", CANCELLED: "Đã hủy", EXPIRED: "Hết thời gian", completed: "Hoàn thành", running: "Đang đấu", queued: "Đang chờ", interrupted: "Gián đoạn" };
function statusBadge(status) {
  const badge = el("span", `match-status status-${status.toLowerCase()} ${["running", "queued", "interrupted"].includes(status) ? status : ""}`, statusLabels[status] || status);
  badge.dataset.status = status;
  return badge;
}

// Polling should not steal keyboard focus or collapse diagnostics being read.
function preserveListState(target) {
  const focused = target.contains(document.activeElement) ? document.activeElement : null;
  const key = focused?.dataset.focusKey;
  const open = new Set([...target.querySelectorAll("details[open]")].map(node => node.dataset.botId));
  return () => {
    target.querySelectorAll("details").forEach(node => { node.open = open.has(node.dataset.botId); });
    if (key && document.activeElement === document.body) target.querySelector(`[data-focus-key="${CSS.escape(key)}"]`)?.focus({ preventScroll: true });
  };
}

let toastTimer;
function toast(message, error = false) {
  const node = $("#toast");
  node.textContent = message;
  node.classList.remove("hidden");
  node.classList.toggle("error", error);
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => node.classList.add("hidden"), error ? 8500 : 4000);
}

async function api(path, options = {}) {
  path = scopedApiPath(path);
  const method = (options.method || "GET").toUpperCase();
  if (app.accountOnly && !["GET", "HEAD", "OPTIONS"].includes(method) && !path.includes("/auth/login")
      && !path.includes("/auth/activate")) {
    const token = await accountCsrf();
    options = { ...options, headers: { ...(options.headers || {}), "X-CSRF-Token": token } };
    if (options.body === undefined) {
      options.body = "{}";
      options.headers["Content-Type"] = "application/json";
    }
  }
  let response;
  try { response = await fetch(path, options); }
  catch { throw new Error("Mất kết nối với máy chủ. Kiểm tra mạng và thử lại."); }
  let data;
  try { data = await response.json(); }
  catch { throw new Error(`Máy chủ chưa sẵn sàng (HTTP ${response.status}). Hãy thử lại.`); }
  if (!response.ok) {
    const detail = Array.isArray(data.detail)
      ? data.detail.map(item => `${item.loc?.join(".")}: ${item.msg}`).join("; ")
      : data.detail;
    const error = new Error(detail || `HTTP ${response.status}`);
    error.status = response.status;
    if (app.accountOnly && response.status === 401 && !path.includes("/auth/login")) accountExpired();
    throw error;
  }
  return data;
}

function scopedApiPath(path) {
  if (!app.accountOnly || !path.startsWith("/api/") || path === "/api/health"
      || path.startsWith("/api/player/") || path.startsWith("/api/admin/")) return path;
  return `/api/${app.accountAudience || "player"}${path.slice(4)}`;
}

async function accountCsrf() {
  if (app.csrf) return app.csrf;
  if (!app.accountAudience) throw new Error("Phiên tài khoản chưa sẵn sàng.");
  const response = await fetch(`/api/${app.accountAudience}/auth/csrf`);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401) accountExpired();
    throw Object.assign(new Error(data.detail || "Phiên đăng nhập đã hết hạn."), { status: response.status });
  }
  app.csrf = data.csrf_token;
  return app.csrf;
}

function jsonOptions(method, body) {
  return { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}

function ownerLabel(owner) {
  if (!owner) return "Submission cũ / chưa có phiên";
  return `${owner.name} · ${owner.id.slice(0, 4).toUpperCase()}${owner.id === app.participant?.id ? " · CỦA BẠN" : ""}`;
}

function languageLabel(language) { return ({ py: "Python", cpp: "C++", java: "Java" })[language] || language; }
function fighterLabel(match, side) {
  const key = side.toLowerCase();
  const bot = match.bots[side];
  const name = match[`player_${key}_name_snapshot`] || match.participants?.[side]?.name || bot.owner?.name || bot.name;
  return `${name} / ${languageLabel(bot.language)} · ${bot.name}`;
}
function activeFrozen() {
  if (app.lobby?.me?.current_match_id) return true;
  return (app.lobby?.invitations || []).some(inv => ["PENDING", "PARTIALLY_ACCEPTED"].includes(inv.status)
    && inv.responses[app.participant?.id] === "ACCEPTED");
}

function acceptLobby(lobby) {
  app.lobby = lobby;
  app.serverClockOffset = lobby.server_time * 1000 - Date.now();
  const players = $("#players-list"); players.replaceChildren();
  $("#players-count").textContent = `${lobby.players.length} PLAYERS`;
  if (!lobby.players.length) players.append(el("div", "empty-state", "Đang chờ Player mở website qua LAN."));
  for (const player of lobby.players) {
    const row = el("div", "player-row");
    const info = el("div", "bot-description");
    info.append(el("strong", "", player.display_name), el("small", "", player.active_bot ? `${player.active_bot.name} / ${languageLabel(player.active_bot.language)}` : "Chưa có Active Bot tương thích"));
    row.append(info, statusBadge(player.status));
    if (player.current_match_id) {
      const live = el("button", "button ghost small", "LIVE ↗");
      live.onclick = () => loadMatch(player.current_match_id).catch(e => toast(e.message, true)); row.append(live);
    }
    players.append(row);
  }
  const me = lobby.me;
  $("#player-status").textContent = statusLabels[me?.status || "OFFLINE"];
  $("#player-status").dataset.status = me?.status || "OFFLINE";
  $("#active-bot-name").textContent = me?.active_bot ? `${me.active_bot.name} / ${languageLabel(me.active_bot.language)}` : "Chưa chọn Active Bot";
  $("#player-match-note").textContent = me?.current_match_id ? "Bot đang thi đấu trên server. Bạn có thể reconnect để xem tiếp." : me?.invitation_id ? "Bạn đang có lời mời. Chọn Accept hoặc Decline." : "Chọn bot READY rồi chờ Organizer gửi lời mời. Giữ website mở.";
  $("#resume-match").classList.toggle("hidden", !me?.current_match_id);
  populateBotSelectors(); renderBots(); renderInvitations(); applyPermissions();
  for (const inv of [...lobby.invitations].reverse()) {
    const relevant = inv.player_ids.includes(app.participant?.id) || app.role === "organizer";
    if (inv.status === "STARTED" && relevant && !app.seenStarts.has(inv.id)) {
      app.seenStarts.add(inv.id);
      if (!inv.finished || me?.current_match_id === inv.match_id) {
        loadMatch(inv.match_id).then(refreshMatches).catch(error => { app.seenStarts.delete(inv.id); toast(error.message, true); });
      }
    }
    if (inv.finished && relevant && !app.seenFinishes.has(inv.id)) {
      app.seenFinishes.add(inv.id);
      if (app.match?.id === inv.match_id) toast("MATCH FINISHED / Kết quả đã lưu. Player sẵn sàng cho lời mời tiếp theo.");
    }
  }
}

function renderInvitations() {
  const target = $("#invitations-list"); target.replaceChildren();
  const invitations = app.lobby?.invitations || [];
  if (!invitations.length) target.append(el("div", "empty-state", "Chưa có lời mời thi đấu."));
  for (const inv of invitations.slice(0, 20)) {
    const row = el("div", "invitation-row"), info = el("div", "bot-description");
    const names = inv.player_ids.map(pid => `${inv.players[pid].name} · ${pid.slice(0, 6).toUpperCase()} / ${languageLabel(inv.bots[pid].language)}`);
    info.append(el("strong", "", names.join(" VS ")), el("small", "", `${inv.game_name} / ${inv.id}`),
      el("small", "", inv.player_ids.map(pid => `${inv.players[pid].name}: ${inv.responses[pid]}`).join(" · ")));
    row.append(info, statusBadge(inv.finished ? "FINISHED" : inv.status));
    if (app.role === "organizer" && ["PENDING", "PARTIALLY_ACCEPTED"].includes(inv.status)) {
      const cancel = el("button", "button ghost small", "Hủy lời mời");
      cancel.disabled = app.invitationCancelling.has(inv.id);
      cancel.onclick = async () => {
        if (app.invitationCancelling.has(inv.id)) return;
        if (!await confirmAction("Hủy lời mời này?", "Hai Player sẽ được giải phóng khỏi lời mời. Trận chưa bắt đầu sẽ không được tạo.", "Hủy lời mời")) return;
        app.invitationCancelling.add(inv.id); busyButton(cancel, true);
        try { await api(`/api/invitations/${inv.id}/cancel`, { method: "POST" }); }
        catch (error) { toast(error.message, true); }
        finally { app.invitationCancelling.delete(inv.id); renderInvitations(); }
      };
      row.append(cancel);
    }
    target.append(row);
  }
  const pending = app.role === "player" && invitations.find(inv => ["PENDING", "PARTIALLY_ACCEPTED"].includes(inv.status));
  const dialog = $("#invitation-dialog");
  if (!pending) { if (dialog.open) dialog.close(); app.currentInvitation = null; return; }
  app.currentInvitation = pending;
  const fighters = $("#invitation-fighters"); fighters.replaceChildren();
  for (const pid of pending.player_ids) {
    const info = el("div", "invitation-fighter");
    info.append(el("h3", "", pending.players[pid].name), el("small", "", `ID / ${pid.slice(0, 6).toUpperCase()}`), el("p", "", pending.bots[pid].name), el("span", "tag", languageLabel(pending.bots[pid].language)));
    fighters.append(info);
  }
  $("#invitation-game").textContent = `${pending.game_name} / Mời bởi Organizer ${pending.organizer.name}`;
  const accepted = pending.responses[app.participant.id] === "ACCEPTED";
  $("#invitation-wait").textContent = accepted ? "Đã chấp nhận · Đang chờ đối thủ. Active Bot đã chốt." : "Chấp nhận để xác nhận Active Bot hiện tại của bạn.";
  $("#invitation-accept").disabled = accepted || app.invitationBusy || app.readOnly;
  $("#invitation-decline").disabled = app.invitationBusy || app.readOnly;
  updateInvitationCountdown();
  if (!dialog.open) dialog.showModal();
}

function updateInvitationCountdown() {
  if (!app.currentInvitation) return;
  const left = Math.max(0, Math.ceil((app.currentInvitation.expires_at * 1000 - Date.now() - app.serverClockOffset) / 1000));
  $("#invitation-countdown").textContent = `Còn ${left} giây để phản hồi`;
  if (!left) $("#invitation-accept").disabled = true;
}
setInterval(updateInvitationCountdown, 500);
$("#invitation-dialog").addEventListener("cancel", event => event.preventDefault());
for (const action of ["accept", "decline"]) $("#invitation-" + action).addEventListener("click", async () => {
  if (!app.currentInvitation || app.invitationBusy) return;
  const id = app.currentInvitation.id;
  app.invitationBusy = true; renderInvitations();
  try {
    const inv = await api(`/api/invitations/${id}/${action}`, { method: "POST" });
    const index = app.lobby.invitations.findIndex(item => item.id === inv.id);
    if (index >= 0 && app.lobby.invitations[index].status !== "STARTED") app.lobby.invitations[index] = inv;
    renderInvitations();
  } catch (error) { toast(error.message, true); }
  finally { app.invitationBusy = false; renderInvitations(); }
});
$("#resume-match").onclick = () => { if (app.lobby?.me?.current_match_id) loadMatch(app.lobby.me.current_match_id).catch(e => toast(e.message, true)); };

function renderSession() {
  if (app.accountOnly) {
    $("#participant-name").textContent = app.account?.display_name || "Chưa đăng nhập";
    $("#participant-id").textContent = app.account
      ? `ACCOUNT / ${app.account.username} · ${app.account.system_role}`
      : "Account-Only · cần xác thực";
    $("#participant-role").textContent = app.account?.system_role || "SIGNED OUT";
    $("#session-form").classList.add("hidden");
    $("#organizer-toggle").textContent = "Đăng xuất";
    $("#organizer-toggle").disabled = !app.account;
    $("#organizer-toggle").title = "Thu hồi phiên tài khoản hiện tại";
    applyPermissions();
    return;
  }
  $("#participant-name").textContent = app.participant.name;
  $("#participant-id").textContent = `ID / ${app.participant.id.toUpperCase()} · Phiên riêng của trình duyệt`;
  $("#session-name").value = app.participant.name;
  $("#readonly-notice").classList.toggle("hidden", !app.readOnly);
  $("#participant-role").textContent = app.role === "organizer" ? "ORGANIZER" : "PLAYER";
  $("#organizer-toggle").textContent = app.role === "organizer" ? "Rời Organizer" : "Mở quyền Organizer";
  $("#organizer-toggle").disabled = app.readOnly || !app.organizerAvailable;
  $("#organizer-toggle").title = app.organizerAvailable ? "Quyền chỉnh luật cho phiên này" : "Máy chủ cần cấu hình ARENA_ADMIN_CODE để mở quyền";
  applyPermissions();
}

function applyPermissions() {
  const organizer = app.role === "organizer" && !app.readOnly;
  const accountPlayer = app.accountOnly && app.accountAudience !== "admin";
  const allowed = organizer && app.competition?.can_edit && !app.competitionBusy && !app.rulesBusy;
  $$("#rules-form input, #rules-form textarea, #rules-form select, #rules-form [type=submit], #default-rules").forEach(node => {
    node.disabled = !allowed; node.title = allowed ? "" : "Cần quyền Organizer và cuộc thi đang ở trạng thái cấu hình";
  });
  $$(".game-select, .game-card").forEach(node => { node.disabled = !allowed || app.switchingGame; });
  $("#competition-open").disabled = !allowed || app.rulesDirty;
  $("#competition-open").title = app.rulesDirty ? "Lưu cấu hình trước khi mở cuộc thi" : allowed ? "Khóa game và luật đã lưu để bắt đầu nhận trận" : "Chờ quyền Organizer và trạng thái SETUP";
  $("#competition-close").disabled = !organizer || !app.competition?.competition_locked || app.competitionBusy;
  $("#competition-open").classList.toggle("hidden", app.role !== "organizer" || app.competition?.phase !== "setup");
  $("#competition-close").classList.toggle("hidden", app.role !== "organizer" || !app.competition?.competition_locked);
  $("#rules-access-note").textContent = app.competition?.competition_locked ? "Luật đã chốt. Đóng cuộc thi và chờ các trận kết thúc để cấu hình lại." : app.competition?.phase === "draining" ? "Cuộc thi đang đóng. Chờ các trận và tác vụ còn lại kết thúc để chỉnh cấu hình." : allowed ? app.rulesDirty ? "Có thay đổi chưa lưu. Lưu cấu hình trước khi mở cuộc thi." : "Chọn game, lưu cấu hình rồi nhấn Lock game & mở cuộc thi." : "Game và luật do Organizer quyết định. Chọn Active Bot để sẵn sàng nhận lời mời.";
  $$(".organizer-only").forEach(node => node.classList.toggle("hidden", !organizer));
  $$(".player-only, [data-go=upload], .nav-item[data-view=upload]").forEach(node => node.classList.toggle("hidden", organizer));
  if (app.accountOnly) {
    $$(".player-only, [data-go=upload], .nav-item[data-view=upload], #quick-match, #create-match").forEach(node => node.classList.add("hidden"));
    if (["#upload", "#create"].includes(location.hash)) location.hash = "home";
  }
  $('.nav-item[data-view="create"]').classList.toggle("hidden", app.accountOnly);
  $('.nav-item[data-view="watch"]').classList.toggle("hidden", accountPlayer);
  $(".docs-link").classList.toggle("hidden", app.accountOnly);
  if (accountPlayer && location.hash === "#watch") location.hash = "home";
  $$("#rules-form [type=submit], #default-rules").forEach(node => node.classList.toggle("hidden", !organizer));
  if (organizer && location.hash === "#upload") location.hash = "create";
  $$("#quick-match [type=submit], #create-match [type=submit]").forEach(node => {
    node.disabled = !organizer || !app.competition?.competition_locked || app.launching || app.competitionBusy
      || (app.lobby?.players || []).filter(player => player.status === "READY").length < 2;
    node.title = node.disabled ? app.competition?.phase !== "open" ? "Cuộc thi cần được mở trước khi gửi lời mời" : "Cần hai Player đang online, có Active Bot và sẵn sàng" : "Hai Player sẽ tự xác nhận lời mời";
  });
  $("#upload-form [type=submit]").disabled = organizer || app.readOnly || app.uploading || !app.selectedGameId;
  $("#seed-samples").disabled = organizer || app.readOnly || app.seeding || !app.selectedGameId;
  $$('[data-sample]').forEach(node => { node.disabled = organizer || app.readOnly || app.seeding || app.sampleBusy.has(`${node.dataset.gameId}:${node.dataset.sample}`); });
  $$(".game-select, .game-card").forEach(node => { node.title = allowed ? "Chọn game của cuộc thi" : app.competition?.competition_locked ? "Game đã khóa; đóng cuộc thi để cấu hình lại" : "Chỉ Organizer được chọn game"; });
  renderCompetitionBanner();
}

function renderCompetitionBanner() {
  const state = app.competition;
  setText("#competition-status", state?.phase === "open" ? "OPEN · Cuộc thi đang mở" : state?.phase === "draining" ? "DRAINING · Chờ trận kết thúc" : "SETUP · Đang chuẩn bị");
  $("#competition-banner").dataset.phase = state?.phase || "setup";
  $("#competition-banner").classList.toggle("competition-live", state?.competition_locked === true);
  setText("#competition-game", app.games.find(game => game.game_id === state?.selected_game_id)?.name || "Đang tải game…");
  const legacyMessage = state?.phase === "open" ? "Game và luật đã khóa. Organizer mời hai Player READY; trận bắt đầu sau hai lượt ACCEPT." : state?.phase === "draining" ? `Đã chặn trận mới. Đang chờ ${state.pending_matches} trận/bot kết thúc trước khi mở khóa cấu hình.` : "Ban tổ chức đang chuẩn bị game và luật. Có thể nộp bot cho game hiện tại; chưa thể tạo trận.";
  const accountMessage = state?.phase === "open" ? "Game và luật đã khóa. Nộp bot theo Team và Official Match sẽ được mở ở Phase 4.2C–D." : state?.phase === "draining" ? `Đã chặn trận mới. Đang chờ ${state.pending_matches} tác vụ hiện có kết thúc trước khi mở khóa cấu hình.` : "Admin đang chuẩn bị game và luật. Chức năng Team submission hiện được khóa an toàn.";
  setText("#competition-message", app.accountOnly ? accountMessage : legacyMessage);
}

async function acceptCompetition(state) {
  const previous = app.competition;
  if (previous?.server_id === state.server_id && previous.revision > state.revision) return;
  const changed = app.selectedGameId !== state.selected_game_id || JSON.stringify(app.rules) !== JSON.stringify(state.rules)
    || previous?.competition_locked !== state.competition_locked;
  app.competition = state;
  applyPermissions();
  if (!changed) return;
  const generation = ++app.competitionGeneration;
  const fresh = await api(`/api/games/${state.selected_game_id}`);
  const latest = app.competition;
  if (generation !== app.competitionGeneration || latest.server_id !== state.server_id
      || latest.selected_game_id !== state.selected_game_id || JSON.stringify(latest.rules) !== JSON.stringify(state.rules)) return;
  Object.assign(app.games.find(game => game.game_id === latest.selected_game_id), fresh, { rules: structuredClone(latest.rules) });
  app.selectedGameId = latest.selected_game_id;
  app.rules = structuredClone(latest.rules);
  populateGameSelectors(); populateBotSelectors(); renderRules(true); renderSamples();
  applyPermissions();
}

function connectCompetitionSocket() {
  if (app.shuttingDown || (app.accountOnly && !app.account)) return;
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  const socketPath = app.accountOnly ? `/api/${app.accountAudience}/ws/competition` : "/ws/competition";
  const socket = new WebSocket(`${scheme}://${location.host}${socketPath}`);
  app.competitionSocket = socket;
  socket.onopen = () => {
    app.lobbyOnline = true; renderConnection();
    clearInterval(app.heartbeatTimer);
    if (!app.accountOnly) {
      const beat = () => { if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: "heartbeat" })); };
      beat(); app.heartbeatTimer = setInterval(beat, 10000);
    }
  };
  socket.onmessage = event => {
    if (socket !== app.competitionSocket) return;
    let message; try { message = JSON.parse(event.data); } catch { return; }
    if (message.type === "competition") {
      const restarted = app.competition && app.competition.server_id !== message.state.server_id;
      if (restarted && !app.accountOnly) api("/api/session").then(acceptSession).catch(() => {});
      acceptCompetition(message.state).catch(error => toast(error.message, true));
      if (!app.accountOnly && message.role && message.role !== app.role) api("/api/session").then(acceptSession).catch(() => {});
      if (message.lobby) acceptLobby(message.lobby);
    }
  };
  socket.onclose = event => {
    if (socket === app.competitionSocket) { app.lobbyOnline = false; renderConnection(); }
    if (socket === app.competitionSocket) clearInterval(app.heartbeatTimer);
    if (app.accountOnly && [1008, 4401].includes(event.code)) {
      accountExpired();
      return;
    }
    if (!app.shuttingDown && socket === app.competitionSocket && (!app.accountOnly || app.account)) app.competitionTimer = setTimeout(connectCompetitionSocket, 1200);
  };
}

function acceptSession(data) {
  app.participant = data.participant; app.readOnly = data.read_only;
  app.role = data.role; app.organizerAvailable = data.organizer_available;
  renderSession();
  renderBots();
  renderInvitations();
}

function showAccountDialog(message = "Đăng nhập để tiếp tục vào workspace.") {
  const dialog = $("#account-dialog");
  $("#account-feedback").textContent = message;
  $("#account-feedback").classList.remove("hidden", "error");
  if (!dialog.open) dialog.showModal();
  $("#account-username").focus();
}

function acceptAccount(data, audience) {
  app.account = data.account;
  app.accountAudience = audience;
  app.csrf = null;
  app.role = data.account.system_role === "ADMIN" ? "organizer" : "player";
  app.participant = { id: data.account.id, name: data.account.display_name };
  app.organizerAvailable = app.role === "organizer";
  if ($("#account-dialog").open) $("#account-dialog").close();
  renderSession();
}

$("#account-dialog").addEventListener("cancel", event => event.preventDefault());

function accountExpired() {
  if (!app.accountOnly || !app.account) return;
  app.account = null; app.participant = null; app.accountAudience = null; app.csrf = null;
  app.role = "player"; app.organizerAvailable = false; app.initialized = false;
  app.competitionSocket?.close(); app.socket?.close();
  clearTimeout(app.competitionTimer); clearTimeout(app.reconnectTimer);
  renderSession();
  showAccountDialog("Phiên đã hết hạn hoặc bị thu hồi. Hãy đăng nhập lại.");
}

async function restoreAccount() {
  for (const audience of ["admin", "player"]) {
    const response = await fetch(`/api/${audience}/auth/me`, { headers: { "Accept": "application/json" } });
    if (response.ok) {
      acceptAccount(await response.json(), audience);
      return true;
    }
  }
  return false;
}

$("#account-login-form").addEventListener("submit", async event => {
  event.preventDefault();
  const form = event.currentTarget;
  const audience = form.elements.audience.value;
  const button = form.querySelector("[type=submit]");
  busyButton(button, true);
  try {
    const data = await api(`/api/${audience}/auth/login`, jsonOptions("POST", {
      username: form.elements.username.value, password: form.elements.password.value
    }));
    form.elements.password.value = "";
    acceptAccount(data, audience);
    app.initialized = false;
    await bootstrap();
  } catch (error) {
    feedback("#account-feedback", error.message, true);
  } finally { busyButton(button, false); button.disabled = false; }
});

$("#account-activation-form").addEventListener("submit", async event => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("[type=submit]");
  busyButton(button, true);
  try {
    await api("/api/player/auth/activate", jsonOptions("POST", {
      token: form.elements.token.value, password: form.elements.password.value
    }));
    form.reset();
    $("#account-login-form [name=username]").focus();
    feedback("#account-feedback", "Kích hoạt thành công. Hãy đăng nhập bằng tài khoản vừa tạo.");
  } catch (error) { feedback("#account-feedback", error.message, true); }
  finally { busyButton(button, false); button.disabled = false; }
});

async function accountLogout() {
  if (!app.accountAudience) return;
  const audience = app.accountAudience;
  try { await api(`/api/${audience}/auth/logout`, jsonOptions("POST", {})); }
  catch (error) { if (error.status !== 401) toast(error.message, true); }
  app.account = null; app.participant = null; app.accountAudience = null; app.csrf = null;
  app.initialized = false;
  app.competitionSocket?.close(); app.socket?.close();
  clearTimeout(app.competitionTimer); clearTimeout(app.reconnectTimer);
  renderSession();
  showAccountDialog("Đã đăng xuất an toàn.");
}

$("#session-form").addEventListener("submit", async event => {
  event.preventDefault();
  const button = event.currentTarget.querySelector("button");
  button.disabled = true;
  try {
    const data = await api("/api/session", jsonOptions("PUT", { name: $("#session-name").value }));
    acceptSession(data); renderBots();
    toast("Đã lưu nickname. Bot và trận mới sẽ ghi tên này.");
  } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; }
});

$("#organizer-toggle").addEventListener("click", async () => {
  if (app.accountOnly) { await accountLogout(); return; }
  if (app.role !== "organizer") { $("#organizer-dialog").showModal(); $("#organizer-code").focus(); return; }
  try { acceptSession(await api("/api/session/organizer", { method: "DELETE" })); toast("Đã trở về quyền Player."); }
  catch (error) { toast(error.message, true); }
});
$("#organizer-cancel").addEventListener("click", () => $("#organizer-dialog").close());
$("#organizer-dialog").addEventListener("close", () => { $("#organizer-code").value = ""; });
$("#organizer-form").addEventListener("submit", async event => {
  event.preventDefault();
  const button = event.currentTarget.querySelector("[type=submit]"); button.disabled = true;
  try {
    acceptSession(await api("/api/session/organizer", jsonOptions("POST", { code: $("#organizer-code").value })));
    $("#organizer-dialog").close(); toast("Đã mở quyền Organizer cho phiên này.");
  } catch (error) { toast(error.message, true); }
  finally { $("#organizer-code").value = ""; button.disabled = false; }
});

const labels = { home: "Tổng quan", upload: "Nộp bot", create: "Phòng thi đấu", watch: "Lịch sử & Replay", rules: "Game & Luật chơi" };
function navigate() {
  let view = location.hash.slice(1) || "home";
  if (!labels[view]) view = "home";
  $$(".view").forEach(node => node.classList.toggle("active", node.id === `view-${view}`));
  $$(".nav-item").forEach(node => node.classList.toggle("active", node.dataset.view === view));
  $("#page-label").textContent = labels[view];
  document.body.dataset.view = view;
  $$(".nav-item[data-view]").forEach(node => node.setAttribute("aria-current", node.dataset.view === view ? "page" : "false"));
  document.title = `${labels[view]} · NEON ARENA`;
  window.scrollTo({ top: 0, behavior: "instant" });
}
window.addEventListener("hashchange", navigate);
$(".skip-link").addEventListener("click", event => {
  event.preventDefault();
  $("#main-content").focus({ preventScroll: true });
  $("#main-content").scrollIntoView({ block: "start", behavior: "instant" });
});
$$("[data-go]").forEach(button => button.addEventListener("click", () => { location.hash = button.dataset.go; }));
navigate();

function setConnection(online) {
  app.serverOnline = online;
  renderConnection();
}

function renderConnection() {
  const ready = app.serverOnline && app.lobbyOnline;
  const label = !app.serverOnline ? "Mất kết nối" : !app.lobbyOnline ? "Đang kết nối lại" : "Đã kết nối";
  if ($("#connection").dataset.connection !== label) {
    $("#connection").dataset.connection = label;
    $("#connection").replaceChildren(el("i", "status-dot"), document.createTextNode(label));
    $("#connection .status-dot").style.background = ready ? "var(--success)" : "var(--warning)";
  }
  $("#network-notice").classList.toggle("hidden", ready || !app.initialized && app.initializing);
  setText("#network-message", !app.serverOnline ? "Chưa kết nối được máy chủ. Kiểm tra mạng; dữ liệu đã nhận vẫn được giữ trên màn hình." : "Kết nối cập nhật trực tiếp đang khôi phục. Bạn vẫn có thể xem các lượt đã nhận.");
}

function renderStats() {
  $("#stat-bots").textContent = String(app.bots.length).padStart(2, "0");
  $("#stat-matches").textContent = String(app.matches.filter(m => m.status === "completed").length).padStart(2, "0");
  const running = app.matches.filter(m => ["running", "queued"].includes(m.status)).length;
  $("#stat-live").textContent = String(running).padStart(2, "0");
  $("#live-note").textContent = running ? "Đang cập nhật trực tiếp" : "Chờ trận đấu tiếp theo";
}

function populateBotSelectors() {
  const ready = (app.lobby?.players || []).filter(player => player.status === "READY");
  $$(".player-select").forEach(select => {
    const selected = select.value;
    const isA = select.classList.contains("player-a");
    const placeholder = el("option", "", isA ? "Chọn Player A" : "Chọn Player B");
    placeholder.value = "";
    select.replaceChildren(placeholder);
    ready.forEach(player => {
      const option = el("option", "", `${player.display_name} / ${languageLabel(player.active_bot.language)} · ${player.active_bot.name}`);
      option.value = player.player_id;
      select.append(option);
    });
    select.value = ready.some(player => player.player_id === selected) ? selected : (ready[isA ? 0 : 1]?.player_id || "");
  });
}
$$(".player-select").forEach(select => select.addEventListener("change", () => {
  const selector = select.classList.contains("player-a") ? ".player-a" : ".player-b";
  $$(selector).forEach(other => { other.value = select.value; });
}));

function renderBots() {
  const target = $("#bot-library");
  const restore = preserveListState(target);
  target.replaceChildren();
  const mine = app.bots.filter(bot => bot.owner?.id === app.participant?.id);
  if (!mine.length) target.append(el("div", "empty-state", "Chưa có submission. Tải code hoặc dùng bot mẫu ở trên."));
  mine.forEach(bot => {
    const row = el("div", "bot-row"); row.dataset.botId = bot.id;
    row.append(el("span", `language-icon ${bot.language === "py" ? "python" : bot.language}`, bot.language.toUpperCase()));
    const description = el("div", "bot-description");
    description.append(el("strong", "", bot.name), el("small", "", bot.filename));
    description.append(el("small", "bot-owner", `NỘP BỞI / ${ownerLabel(bot.owner)}`));
    description.append(el("span", "tag", app.games.find(game => game.game_id === bot.game_id)?.name || bot.game_id));
    const status = statusBadge(bot.status === "ready" ? "READY" : "interrupted");
    status.textContent = bot.status === "ready" ? "Sẵn sàng" : "Biên dịch lỗi";
    status.classList.toggle("bot-error", bot.status === "error");
    row.append(description, status);
    const active = app.lobby?.me?.active_bot_id === bot.id;
    const button = el("button", "button ghost small", active ? "Active Bot ✓" : "Chọn làm Active Bot");
    button.dataset.action = "set-active"; button.dataset.focusKey = `active-${bot.id}`;
    button.disabled = app.role !== "player" || app.readOnly || bot.status !== "ready" || bot.game_id !== app.selectedGameId || active || activeFrozen() || app.activeBotBusy.has(bot.id);
    button.title = active ? "Bot đang đại diện cho bạn" : bot.status !== "ready" ? "Cần biên dịch thành công trước khi chọn" : bot.game_id !== app.selectedGameId ? "Bot thuộc game khác; chọn hoặc nộp bot cho game hiện tại" : activeFrozen() ? "Active Bot đã chốt trong lời mời hoặc trận đang chạy" : "Dùng bot này để nhận lời mời thi đấu";
    button.addEventListener("click", async () => {
      if (app.activeBotBusy.has(bot.id)) return;
      app.activeBotBusy.add(bot.id); busyButton(button, true);
      try { await api("/api/players/active-bot", jsonOptions("PUT", { bot_id: bot.id })); toast("Đã chọn Active Bot. Chờ Organizer gửi lời mời."); }
      catch (error) { toast(error.message, true); }
      finally { app.activeBotBusy.delete(bot.id); renderBots(); }
    });
    row.append(button);
    if (bot.logs) {
      const details = el("details");
      details.dataset.botId = bot.id;
      details.append(el("summary", "", "Compiler log"), el("pre", "", bot.logs));
      row.append(details);
    }
    target.append(row);
  });
  populateBotSelectors();
  renderStats();
  restore();
}

function selectedGame() { return app.games.find(game => game.game_id === app.selectedGameId); }

function populateGameSelectors() {
  $$(".game-select").forEach(select => {
    select.replaceChildren(...app.games.map(game => {
      const option = el("option", "", game.name);
      option.value = game.game_id;
      return option;
    }));
    select.value = app.selectedGameId || "";
  });
}

async function selectGame(gameId, persist = true) {
  if (app.switchingGame) { populateGameSelectors(); return; }
  if (!app.games.some(game => game.game_id === gameId)) return;
  app.switchingGame = true;
  $$(".game-select").forEach(node => { node.disabled = true; });
  try {
    if (persist) await api("/api/games/selected", jsonOptions("PUT", { game_id: gameId }));
    await acceptCompetition(await api("/api/competition"));
    $("#rules-feedback").classList.add("hidden");
  } catch (error) { toast(error.message, true); populateGameSelectors(); }
  finally { app.switchingGame = false; applyPermissions(); }
}
$$(".game-select").forEach(select => select.addEventListener("change", () => selectGame(select.value)));

function renderRules(fillForm = false) {
  const game = selectedGame();
  if (!game) return;
  $("#workspace-game-name").textContent = `${game.name} / ${game.turn_mode === "simultaneous" ? "ĐỒNG THỜI" : "LUÂN PHIÊN"}`;
  $("#game-name").textContent = game.name;
  $("#hero-game-label").textContent = game.name;
  $("#game-description").textContent = game.description;
  $("#rules-heading").textContent = `${game.name} · Cấu hình luật`;
  $("#create-game-label").textContent = game.badge || game.name;
  $("#match-mode-hint").textContent = game.turn_mode === "simultaneous" ? "Hai bot nhận cùng trạng thái và hành động đồng thời." : "Hai bot đi luân phiên. Server chỉ hỏi bot đến lượt.";
  const source = $("#game-source");
  source.classList.toggle("hidden", !game.source_url);
  if (game.source_url) source.href = game.source_url;
  const fixed = $("#game-fixed");
  fixed.replaceChildren(...Object.entries(game.fixed_rules || {}).map(([key, value]) => {
    const item = el("span", "fixed-rule");
    const fixedLabels = { movement: "Di chuyển", attack_range: "Tầm tấn công", board_size: "Bàn chơi", capture: "Ăn quân", pieces: "Quân cờ", goals: "Đích đến" };
    item.append(el("small", "", fixedLabels[key] || key.replaceAll("_", " ")), document.createTextNode(String(value)));
    return item;
  }));
  const library = $("#game-library");
  library.replaceChildren(...app.games.map(installed => {
    const button = el("button", "game-card" + (installed.game_id === app.selectedGameId ? " selected" : ""));
    button.type = "button"; button.dataset.gameId = installed.game_id;
    button.setAttribute("aria-pressed", String(installed.game_id === app.selectedGameId));
    const copy = el("div", "game-card-copy");
    copy.append(el("h2", "", installed.name), el("p", "", installed.description), el("small", "", `Đã cài đặt · v${installed.version} · ${installed.turn_mode === "simultaneous" ? "Đồng thời" : "Luân phiên"}`));
    button.append(el("span", "game-card-icon", installed.name.slice(0, 2).toUpperCase()), copy);
    button.addEventListener("click", () => selectGame(installed.game_id));
    return button;
  }));
  $("#rules-guide").replaceChildren(...[...(game.guide || []), { title: "BOT FAULT", description: "Timeout, crash, JSON hoặc action không hợp lệ: bot bị xử thua. Game state chỉ do server cập nhật." }].map((item, index) => {
    const row = el("li"), copy = el("div");
    const guideLabels = { MOVE: "Di chuyển", ATTACK: "Tấn công", WIN: "Điều kiện thắng", "BOT FAULT": "Lỗi bot", MOVEMENT: "Di chuyển", CAPTURE: "Ăn quân", SERIES: "Nhiều ván đấu", GOAL: "Đích đến" };
    copy.append(el("strong", "", guideLabels[item.title] || item.title), el("p", "", item.description));
    row.append(el("span", "", String(index + 1).padStart(2, "0")), copy);
    return row;
  }));
  const properties = game.rules_schema.properties || {};
  if (fillForm) {
    app.rulesDirty = false;
    $("#rules-fields").replaceChildren(...Object.entries(properties).map(([key, schema]) => {
      const label = el("label", "", schema.title || key);
      if (schema.minimum !== undefined && schema.maximum !== undefined) label.append(el("span", "input-hint", `${schema.minimum}–${schema.maximum}`));
      let input;
      if (schema.enum) {
        input = el("select");
        schema.enum.forEach(value => { const option = el("option", "", String(value)); option.value = String(value); input.append(option); });
      } else if (["object", "array"].includes(schema.type)) input = el("textarea");
      else {
        input = el("input");
        input.type = schema.type === "boolean" ? "checkbox" : ["integer", "number"].includes(schema.type) ? "number" : "text";
        if (schema.minimum !== undefined) input.min = schema.minimum;
        if (schema.maximum !== undefined) input.max = schema.maximum;
        if (input.type === "number") input.step = schema.type === "integer" ? "1" : "any";
      }
      input.name = key;
      input.id = `rule-${key}`;
      if (schema.type === "boolean") input.checked = Boolean(app.rules[key]);
      else input.value = ["object", "array"].includes(schema.type) ? JSON.stringify(app.rules[key], null, 2) : String(app.rules[key] ?? schema.default ?? "");
      input.required = schema.type !== "boolean";
      label.append(input);
      if (schema.description) {
        const description = el("small", "field-description", schema.description);
        description.id = `rule-help-${key}`;
        input.setAttribute("aria-describedby", description.id);
        label.append(description);
      }
      return label;
    }));
  }
  $("#create-rules").replaceChildren(...Object.entries(app.rules).map(([key, value]) => {
    const chip = el("span");
    chip.append(el("strong", "", String(value)), document.createTextNode(` ${properties[key]?.title || key}`));
    return chip;
  }));
  if (!app.match) updateHud(currentFrame());
}

function renderSamples() {
  const game = selectedGame();
  if (!game) return;
  $("#samples-game").textContent = game.badge || game.name;
  $("#action-examples").textContent = (game.action_examples || []).map(action => JSON.stringify(action)).join("\n");
  $("#sample-list").replaceChildren(...game.samples.map(sample => {
    const row = el("div", "sample-card");
    const copy = el("div");
    copy.append(el("strong", "", sample.name), el("p", "", sample.description));
    const link = el("a", "icon-button", "⇩");
    link.href = scopedApiPath(`/api/games/${game.game_id}/samples/${sample.language}`);
    link.title = `Tải bot ${sample.language}`;
    link.setAttribute("aria-label", link.title);
    const button = el("button", "icon-button", "＋");
    button.dataset.sample = sample.language; button.title = `Nộp mẫu ${sample.language}`;
    button.dataset.gameId = game.game_id;
    button.setAttribute("aria-label", button.title);
    button.addEventListener("click", async () => {
      const key = `${game.game_id}:${sample.language}`;
      if (app.sampleBusy.has(key)) return;
      app.sampleBusy.add(key); busyButton(button, true);
      try { const bot = await addSample(sample.language, game.game_id); toast(`${bot.name} đã sẵn sàng.`); }
      catch (error) { toast(error.message, true); }
      finally { app.sampleBusy.delete(key); busyButton(button, false); applyPermissions(); await refreshBots().catch(() => {}); }
    });
    row.append(el("span", `language-icon ${sample.language}`, sample.language === "python" ? "PY" : sample.language === "cpp" ? "C++" : "JAVA"), copy, link, button);
    return row;
  }));
  if (!game.samples.length) $("#sample-list").append(el("div", "empty-state", "Game này chưa có bot mẫu. Hãy nộp bot theo tài liệu adapter."));
  applyPermissions();
}

function resultDescription(match) {
  if (match.status === "interrupted") return "Gián đoạn";
  if (!match.result) return "Đang thi đấu";
  return match.result.winner ? `${fighterLabel(match, match.result.winner)} thắng` : "Hòa";
}

function renderMatchList(target, matches) {
  const restore = preserveListState(target);
  target.replaceChildren();
  if (!matches.length) target.append(el("div", "empty-state", "Chưa có trận đấu. Organizer mời hai Player READY để thi đấu."));
  matches.forEach((match, index) => {
    const row = el("div", "match-row");
    row.dataset.matchId = match.id;
    row.dataset.gameId = match.game_id;
    row.append(el("span", "match-id", `#${String(index + 1).padStart(3, "0")}`));
    const names = el("div", "match-names");
    names.append(document.createTextNode(fighterLabel(match, "A")), el("span", "", "VS"), document.createTextNode(fighterLabel(match, "B")));
    names.append(el("small", "match-date", `${match.game_name || app.games.find(g => g.game_id === match.game_id)?.name || match.game_id} · ${new Date(match.created_at).toLocaleString("vi-VN")} · ${match.turn} lượt`));
    names.append(el("small", "match-date", `#${match.id} · TẠO BỞI / ${match.created_by ? ownerLabel(match.created_by) : "Trận cũ"}`));
    row.append(names, statusBadge(match.status), el("span", "match-result", resultDescription(match)));
    const button = el("button", "button ghost", ["running", "queued"].includes(match.status) ? "Live ↗" : "Replay ↗");
    button.dataset.focusKey = `match-${match.id}`;
    button.setAttribute("aria-label", `${["running", "queued"].includes(match.status) ? "Xem trực tiếp" : "Xem replay"} trận ${match.id}`);
    button.addEventListener("click", () => loadMatch(match.id).catch(error => toast(error.message, true)));
    row.append(button);
    target.append(row);
  });
  restore();
}

function renderMatches() {
  renderMatchList($("#recent-matches"), app.matches.slice(0, 4));
  renderMatchList($("#all-matches"), app.matches);
  $("#history-count").textContent = `${app.matches.length} trận`;
  renderStats();
}

async function refreshBots() { app.bots = await api("/api/bots"); renderBots(); }
async function refreshMatches() { app.matches = await api("/api/matches"); renderMatches(); }
$("#refresh-bots").addEventListener("click", () => refreshBots().catch(e => toast(e.message, true)));
$("#refresh-matches").addEventListener("click", () => refreshMatches().catch(e => toast(e.message, true)));

function feedback(selector, message, error = false) {
  const target = $(selector);
  target.textContent = message;
  target.className = "feedback" + (error ? " error" : "");
}

$("#upload-form").addEventListener("submit", async event => {
  event.preventDefault();
  if (app.uploading) return;
  const form = event.currentTarget;
  const button = form.querySelector("[type=submit]");
  const file = $("#bot-file").files[0];
  if (!file || !file.size || file.size > 256 * 1024 || !/\.(py|cpp|java)$/i.test(file.name)) {
    feedback("#upload-feedback", "Chọn file .py, .cpp hoặc .java có nội dung, không vượt quá 256 KiB.", true);
    $("#bot-file").setAttribute("aria-invalid", "true");
    return;
  }
  app.uploading = true; busyButton(button, true);
  form.setAttribute("aria-busy", "true");
  button.textContent = "Đang tải & biên dịch…";
  feedback("#upload-feedback", "Đang gửi code và chờ kết quả biên dịch từ máy chủ…");
  $("#upload-feedback").classList.add("pending");
  $("#compiler-log").classList.add("hidden");
  try {
    const body = new FormData(form);
    // Disabled Player game selectors are omitted by FormData; use server state explicitly.
    body.set("game_id", app.competition.selected_game_id);
    const bot = await api("/api/bots", { method: "POST", body });
    feedback("#upload-feedback", bot.status === "ready" ? `${bot.name} đã sẵn sàng thi đấu.` : "Biên dịch thất bại. Kiểm tra log bên dưới.", bot.status !== "ready");
    if (bot.logs) {
      $("#compiler-log").textContent = bot.logs;
      $("#compiler-log").classList.remove("hidden");
    }
    await refreshBots();
    if (bot.status === "ready") { form.reset(); populateGameSelectors(); updateSelectedFile(); }
  } catch (error) { feedback("#upload-feedback", error.message, true); }
  finally { app.uploading = false; busyButton(button, false); form.setAttribute("aria-busy", "false"); button.textContent = "Tải lên & biên dịch ↗"; applyPermissions(); }
});
function updateSelectedFile() {
  const file = $("#bot-file").files[0];
  $("#file-label").textContent = file?.name || "Thả code vào đây";
  $("#file-language").classList.toggle("hidden", !file);
  $("#file-language").textContent = file ? `${languageLabel(file.name.split(".").pop().toLowerCase())} · ${(file.size / 1024).toFixed(1)} KiB` : "";
  $("#bot-file").removeAttribute("aria-invalid");
}
$("#bot-file").addEventListener("change", updateSelectedFile);
const dropZone = $("#drop-zone");
["dragenter", "dragover"].forEach(name => dropZone.addEventListener(name, event => { event.preventDefault(); dropZone.classList.add("dragover"); }));
["dragleave", "drop"].forEach(name => dropZone.addEventListener(name, () => dropZone.classList.remove("dragover")));
dropZone.addEventListener("drop", event => {
  event.preventDefault();
  if (app.uploading || !event.dataTransfer?.files.length) return;
  const transfer = new DataTransfer(); transfer.items.add(event.dataTransfer.files[0]);
  $("#bot-file").files = transfer.files;
  updateSelectedFile();
});

async function addSample(language, gameId = app.selectedGameId) {
  const bot = await api(`/api/games/${gameId}/samples/${language}/submit`, { method: "POST" });
  if (bot.status !== "ready") throw new Error(bot.logs || "Biên dịch bot mẫu thất bại.");
  return bot;
}
$("#seed-samples").addEventListener("click", async event => {
  if (app.seeding) return;
  const button = event.currentTarget;
  app.seeding = true; busyButton(button, true); applyPermissions();
  button.textContent = "Đang thêm…";
  const errors = [];
  const gameId = app.selectedGameId;
  const languages = selectedGame()?.samples.map(sample => sample.language) || [];
  const seeded = [];
  try {
    for (const language of languages) {
      try { seeded.push(await addSample(language, gameId)); } catch (error) { errors.push(`${language.toUpperCase()}: ${error.message}`); }
    }
    await refreshBots();
    toast(errors.length ? errors.join("\n") : seeded.length ? `${seeded.length} bot mẫu đã sẵn sàng. Chọn SET AS ACTIVE BOT trong My Submissions.` : "Game này chưa có bot mẫu; hãy nộp code cho game đã chọn.", errors.length > 0);
  } finally { app.seeding = false; busyButton(button, false); button.textContent = "Bắt đầu với bot mẫu ↗"; applyPermissions(); }
});

$("#rules-form").addEventListener("input", () => { app.rulesDirty = true; applyPermissions(); });

$("#rules-form").addEventListener("submit", async event => {
  event.preventDefault();
  if (app.rulesBusy) return;
  const form = event.currentTarget;
  const button = form.querySelector("[type=submit]");
  const game = selectedGame();
  if (!game) return;
  app.rulesBusy = true; busyButton(button, true);
  try {
    const rules = Object.fromEntries(Object.entries(game.rules_schema.properties).map(([key, schema]) => {
      const input = form.elements[key];
      const value = schema.type === "boolean" ? input.checked : ["integer", "number"].includes(schema.type) ? Number(input.value) : ["object", "array"].includes(schema.type) ? JSON.parse(input.value) : input.value;
      return [key, value];
    }));
    await api(`/api/games/${game.game_id}/rules`, jsonOptions("PUT", rules));
    app.rulesDirty = false;
    await acceptCompetition(await api("/api/competition"));
    feedback("#rules-feedback", "Đã lưu cấu hình. Mở cuộc thi để áp dụng cho các trận mới.");
  } catch (error) { feedback("#rules-feedback", error.message, true); }
  finally { app.rulesBusy = false; busyButton(button, false); applyPermissions(); }
});
$("#default-rules").addEventListener("click", async event => {
  if (app.rulesBusy) return;
  const button = event.currentTarget;
  const game = selectedGame();
  if (!game) return;
  if (!await confirmAction("Khôi phục luật mặc định?", `Cấu hình hiện tại của ${game.name} sẽ được thay bằng luật mặc định và lưu lên máy chủ.`, "Khôi phục mặc định")) return;
  app.rulesBusy = true; busyButton(button, true); applyPermissions();
  try {
    await api(`/api/games/${game.game_id}/rules/reset`, { method: "POST" });
    await acceptCompetition(await api("/api/competition"));
    feedback("#rules-feedback", `Đã khôi phục và lưu luật mặc định của ${game.name}.`);
  } catch (error) { feedback("#rules-feedback", error.message, true); }
  finally { app.rulesBusy = false; busyButton(button, false); applyPermissions(); }
});

for (const [selector, action] of [["#competition-open", "open"], ["#competition-close", "close"]]) {
  $(selector).addEventListener("click", async () => {
    if (app.competitionBusy) return;
    if (action === "close" && !await confirmAction("Đóng cuộc thi?", "Lời mời và trận mới sẽ bị chặn. Các trận đang chạy vẫn tiếp tục; chỉ được chỉnh game và luật sau khi chúng kết thúc.", "Đóng cuộc thi")) return;
    app.competitionBusy = true; applyPermissions();
    try {
      await acceptCompetition(await api(`/api/competition/${action}`, { method: "POST" }));
      toast(action === "open" ? "Cuộc thi đã mở. Game và luật đã khóa." : "Đã đóng cuộc thi. Các trận hiện tại giữ snapshot và tiếp tục chạy.");
    } catch (error) { toast(error.message, true); }
    finally { app.competitionBusy = false; applyPermissions(); }
  });
}

async function launch(event) {
  event.preventDefault();
  if (app.launching) return;
  if (app.switchingGame) { toast("Đang chọn game, hãy đợi một chút."); return; }
  app.launching = true;
  const buttons = [$("#quick-match [type=submit]"), $("#create-match [type=submit]")];
  buttons.forEach(button => { button.disabled = true; });
  try {
    const form = event.currentTarget;
    await api("/api/invitations", jsonOptions("POST", { player_a_id: form.elements.player_a_id.value, player_b_id: form.elements.player_b_id.value }));
    toast("Đã gửi lời mời. Trận tự bắt đầu sau khi cả hai Player Accept.");
  } catch (error) { toast(error.message, true); }
  finally { app.launching = false; applyPermissions(); }
}
$("#quick-match").addEventListener("submit", launch);
$("#create-match").addEventListener("submit", launch);

async function loadMatch(id) {
  const generation = ++app.generation;
  app.socket?.close();
  clearTimeout(app.reconnectTimer);
  const payload = await api(`/api/matches/${id}/replay`);
  if (generation !== app.generation) return;
  app.match = payload.match;
  app.frames = payload.frames;
  app.cursor = 0;
  app.paused = false;
  app.victoryDismissed = false;
  app.displayedResult = false;
  app.nextFrameAt = performance.now() + 650;
  app.transition = null;
  document.body.classList.add("has-match");
  $("#standby-overlay").classList.add("hidden");
  $("#victory-overlay").classList.add("hidden");
  location.hash = "home";
  const link = new URL(location.href);
  link.searchParams.set("match", id);
  history.replaceState(null, "", link);
  if (app.frames.length) setFrame(0, false);
  updatePlayback();
  if (["running", "queued"].includes(app.match.status)) connectSocket(id, generation);
  else if (!app.frames.length) toast("Trận bị gián đoạn trước khi có trạng thái replay.", true);
}

function connectSocket(id, generation) {
  if (generation !== app.generation || (app.accountOnly && (!app.account || app.accountAudience !== "admin"))) return;
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  const socketPath = app.accountOnly ? `/api/admin/ws/matches/${id}` : `/ws/matches/${id}`;
  const socket = new WebSocket(`${scheme}://${location.host}${socketPath}?after=${app.frames.length - 1}`);
  app.socket = socket;
  app.arenaOnline = false;
  socket.onopen = () => { if (generation === app.generation) { app.arenaOnline = true; updatePlayback(); } };
  socket.onmessage = event => {
    if (generation !== app.generation) return;
    let message;
    try { message = JSON.parse(event.data); } catch { return; }
    if (message.type === "hello") app.match = message.match;
    if (message.type === "state") {
      app.frames[message.seq] = message.state;
      if (app.frames.length === 1) setFrame(0, false);
    }
    if (message.type === "complete") {
      app.match = message.match;
      refreshMatches().catch(() => {});
    }
    updatePlayback();
  };
  socket.onclose = event => {
    if (app.accountOnly && [1008, 4401].includes(event.code)) {
      accountExpired();
      return;
    }
    if (generation !== app.generation || !["running", "queued"].includes(app.match?.status)
        || (app.accountOnly && !app.account)) return;
    app.arenaOnline = false; updatePlayback();
    app.reconnectTimer = setTimeout(async () => {
      if (generation !== app.generation) return;
      try {
        const payload = await api(`/api/matches/${id}/replay`);
        if (generation !== app.generation) return;
        app.match = payload.match;
        app.frames = payload.frames;
        updatePlayback();
        if (["running", "queued"].includes(app.match.status)) connectSocket(id, generation);
        else refreshMatches().catch(() => {});
      } catch {
        if (generation === app.generation) connectSocket(id, generation);
      }
    }, 1500);
  };
  socket.onerror = () => { if (generation === app.generation) { app.arenaOnline = false; updatePlayback(); } };
}

function currentFrame() { return app.frames[app.cursor] || selectedGame()?.preview_state || null; }
function frameGameId(frame) { return frame?.game_id || app.match?.game_id || app.match?.game || app.selectedGameId; }
function updateHud(frame) {
  if (!frame) return;
  const gameId = frameGameId(frame);
  const hud = NeonRenderers.get(gameId).hud(frame);
  $("#arena-game").textContent = app.games.find(game => game.game_id === gameId)?.badge || gameId;
  $("#arena-map-label").textContent = hud.grid;
  $("#arena-phase").textContent = hud.phase;
  $("#turn-counter").textContent = String(frame.turn).padStart(3, "0");
  $("#turn-max").textContent = hud.turnMax;
  for (const player of ["A", "B"]) {
    const key = player.toLowerCase();
    $("#fighter-" + key + "-name").textContent = app.match ? fighterLabel(app.match, player) : "Chưa có bot thi đấu";
    $("#hp-" + key + "-fill").style.width = `${Math.max(0, Math.min(100, 100 * hud.players[player].value / hud.players[player].max))}%`;
    $("#hp-" + key + "-text").textContent = hud.players[player].text;
  }
}

function updatePlayback() {
  const timeline = $("#timeline");
  timeline.max = Math.max(0, app.frames.length - 1);
  timeline.value = app.cursor;
  $("#play-start").classList.toggle("selected", !app.paused && !!app.match);
  $("#play-pause").classList.toggle("selected", app.paused && !!app.match);
  $("#play-start").setAttribute("aria-pressed", String(!app.paused && !!app.match));
  $("#play-pause").setAttribute("aria-pressed", String(app.paused && !!app.match));
  timeline.setAttribute("aria-valuetext", `Lượt ${currentFrame()?.turn || 0}, ${app.frames.length} trạng thái đã nhận`);
  ["#play-pause", "#play-reset", "#play-speed", "#timeline", "#share-match", "#download-replay"].forEach(selector => {
    $(selector).disabled = !app.match;
    $(selector).title = !app.match ? "Chọn một trận để dùng playback" : $(selector).getAttribute("aria-label");
  });
  const live = ["running", "queued"].includes(app.match?.status);
  const status = $("#arena-status");
  status.classList.toggle("running", live);
  const label = !app.match ? "Chờ trận đấu" : app.paused ? "Tạm dừng" : live ? app.arenaOnline ? "Trực tiếp" : "Đang kết nối lại" : "Replay";
  status.replaceChildren(el("i"), document.createTextNode(label));
  $("#feed-label").textContent = !app.match ? "Chưa chọn trận" : app.paused ? live ? "Tạm dừng hiển thị · Trận vẫn tiếp tục" : "Replay đang tạm dừng" : live ? app.arenaOnline ? "Cập nhật trực tiếp" : "Đang khôi phục luồng trận…" : "Replay từ dữ liệu đã lưu";
}

function setFrame(index, animate = true) {
  const previous = currentFrame();
  app.cursor = Math.max(0, Math.min(index, app.frames.length - 1));
  const frame = currentFrame();
  const now = performance.now();
  app.transition = { from: animate ? previous : frame, to: frame, started: now, duration: animate ? 280 / app.speed : 0 };
  app.nextFrameAt = now + 430 / app.speed;
  app.displayedResult = false;
  app.victoryDismissed = false;
  $("#victory-overlay").classList.add("hidden");
  updateHud(frame);
  renderCombatLog();
  updatePlayback();
}

function renderCombatLog() {
  const log = $("#combat-log");
  log.replaceChildren();
  if (!app.match) return;
  const lines = [];
  lines.push({ turn: "SYS", text: `${fighterLabel(app.match, "A")} vs ${fighterLabel(app.match, "B")}`, type: "" });
  for (const frame of app.frames.slice(0, app.cursor + 1)) {
    const renderer = NeonRenderers.get(frameGameId(frame));
    for (const event of frame.events) {
      const text = renderer.log(event);
      if (!text) continue;
      lines.push({ turn: String(frame.turn).padStart(3, "0"), text, type: event.type });
    }
    if (frame.result) lines.push({ turn: "END", text: frame.result.winner ? `${frame.result.winner} chiến thắng` : "Hòa", type: "result" });
  }
  lines.slice(-35).forEach(line => {
    const row = el("div", `log-line ${line.type}`);
    row.append(el("span", "", line.turn), document.createTextNode(line.text));
    log.append(row);
  });
  log.scrollTop = log.scrollHeight;
}

function showResult(frame) {
  if (app.victoryDismissed || app.displayedResult) return;
  const result = frame.result || (app.cursor === app.frames.length - 1 && app.match?.status === "interrupted" ? app.match.result : null);
  if (!result) return;
  app.displayedResult = true;
  $("#victory-overlay").classList.remove("hidden");
  $("#victory-title").textContent = app.match?.status === "interrupted" ? "Trận bị gián đoạn" : result.winner ? "Chiến thắng!" : "Trận đấu hòa";
  $("#victory-winner").textContent = result.winner ? fighterLabel(app.match, result.winner) : "Không có người thắng";
  const reasons = { bot_error: "Lỗi bot: " + Object.entries(result.faults || {}).map(([p, error]) => `${p}: ${error}`).join(" · "), server_restart: "Máy chủ đã khởi động lại giữa trận.", server_shutdown: "Máy chủ dừng giữa trận.", server_error: "Máy chủ gặp lỗi khi xử lý trận đấu.", runner_unavailable: "Hạ tầng chạy bot bị gián đoạn. Không xử thua Player.", organizer_cancelled: "Organizer đã hủy trận đấu." };
  $("#victory-reason").textContent = reasons[result.reason] || NeonRenderers.get(frameGameId(frame)).result(result);
}

$("#play-pause").addEventListener("click", () => { app.paused = true; updatePlayback(); });
$("#play-start").addEventListener("click", () => {
  if (!app.match) { location.hash = "create"; return; }
  if (app.cursor === app.frames.length - 1 && app.match.status === "completed") setFrame(0, false);
  app.paused = false;
  app.nextFrameAt = performance.now() + 400 / app.speed;
  updatePlayback();
});
$("#play-reset").addEventListener("click", () => {
  if (!app.frames.length) return;
  app.paused = true;
  setFrame(0, false);
});
$("#timeline").addEventListener("input", event => {
  if (!app.frames.length) return;
  app.paused = true;
  setFrame(Number(event.target.value), false);
});
$("#play-speed").addEventListener("change", event => { app.speed = Number(event.target.value); });
$("#dismiss-victory").addEventListener("click", () => { app.victoryDismissed = true; $("#victory-overlay").classList.add("hidden"); });
$("#share-match").addEventListener("click", async () => {
  if (!app.match) { toast("Chọn một trận trước khi chia sẻ."); return; }
  const url = new URL(location.href); url.searchParams.set("match", app.match.id); url.hash = "home";
  try {
    if (navigator.clipboard) await navigator.clipboard.writeText(url.href);
    else {
      const input = el("textarea"); input.value = url.href; document.body.append(input);
      input.select(); if (!document.execCommand("copy")) throw new Error("Copy unavailable"); input.remove();
    }
    toast("Đã sao chép link theo dõi. Các máy khác mở link qua IP LAN của host.");
  } catch { toast(url.href); }
});
$("#download-replay").addEventListener("click", async () => {
  if (!app.match) { toast("Chọn một trận trước khi tải replay."); return; }
  try {
    const replay = await api(`/api/matches/${app.match.id}/replay`);
    const url = URL.createObjectURL(new Blob([JSON.stringify(replay, null, 2)], { type: "application/json" }));
    const link = el("a");
    link.href = url;
    link.download = `neon-arena-${app.match.id}.json`;
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (error) { toast(error.message, true); }
});

// A renderer is selected only from the frame's game_id, never from the
// organizer's current game selection: old replays retain the right renderer.
const canvas = $("#arena");
const ctx = canvas.getContext("2d");
const motionPreference = window.matchMedia("(prefers-reduced-motion: reduce)");
let reducedMotion = motionPreference.matches;
motionPreference.addEventListener("change", event => { reducedMotion = event.matches; });
function draw(time) {
  const frame = currentFrame();
  if (!frame) return;
  NeonRenderers.get(frameGameId(frame)).draw(ctx, canvas, frame, app.transition, time, reducedMotion);
  if (app.match && (!app.transition?.duration || time >= app.transition.started + app.transition.duration)) showResult(frame);
}

function animate(time) {
  if (!app.paused && app.frames.length && time >= app.nextFrameAt && app.cursor < app.frames.length - 1) setFrame(app.cursor + 1);
  if ($("#view-home").classList.contains("active") && !document.hidden) draw(time);
  requestAnimationFrame(animate);
}
requestAnimationFrame(animate);
setInterval(() => { $("#clock").textContent = new Date().toLocaleTimeString("vi-VN", { hour12: false }); }, 1000);

async function bootstrap() {
  if (app.initializing) return;
  app.initializing = true;
  try {
    const health = await api("/api/health");
    app.accountAuth = health.account_auth === true;
    app.accountOnly = health.account_only === true;
    if (app.accountOnly) {
      $("#account-mode-note").classList.remove("hidden");
      if (!app.account && !await restoreAccount()) {
        setConnection(true); renderSession(); showAccountDialog(); return;
      }
    } else {
      // Establish the legacy cookie first; parallel startup requests then share one identity.
      acceptSession(await api("/api/session"));
    }
    const canInspectPrivate = !app.accountOnly || app.accountAudience === "admin";
    const [bots, registry, matches, competition] = await Promise.all([
      canInspectPrivate ? api("/api/bots") : Promise.resolve([]),
      api("/api/games"),
      canInspectPrivate ? api("/api/matches") : Promise.resolve([]),
      api("/api/competition")
    ]);
    app.bots = bots; app.games = registry.games; app.matches = matches;
    await acceptCompetition(competition);
    setConnection(health.status === "ok");
    renderBots(); renderRules(true); renderMatches();
    applyPermissions();
    app.initialized = true;
    connectCompetitionSocket();
    updatePlayback();
    const matchId = new URL(location.href).searchParams.get("match");
    if (matchId) await loadMatch(matchId);
  } catch (error) { setConnection(false); toast(`Chưa kết nối được workspace: ${error.message}`, true); }
  finally { app.initializing = false; renderConnection(); }
}
bootstrap();
$("#retry-connection").addEventListener("click", async event => {
  const button = event.currentTarget; busyButton(button, true);
  try {
    if (!app.initialized) await bootstrap();
    else {
      setConnection((await api("/api/health")).status === "ok");
      if (app.competitionSocket?.readyState !== WebSocket.OPEN) {
        clearTimeout(app.competitionTimer); app.competitionSocket?.close(); connectCompetitionSocket();
      }
    }
  } catch (error) { setConnection(false); toast(error.message, true); }
  finally { busyButton(button, false); button.disabled = false; }
});
setInterval(async () => {
  if (document.hidden || app.refreshing || !app.participant || (app.accountOnly && app.accountAudience !== "admin")) return;
  if (!app.initialized) { bootstrap(); return; }
  app.refreshing = true;
  try { await Promise.all([refreshMatches(), refreshBots()]); setConnection(true); }
  catch { setConnection(false); }
  finally { app.refreshing = false; }
}, 2000);
window.addEventListener("beforeunload", () => { app.shuttingDown = true; app.generation++; app.socket?.close(); clearTimeout(app.competitionTimer); clearInterval(app.heartbeatTimer); app.competitionSocket?.close(); });
