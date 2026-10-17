"use strict";

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const app = {
  bots: [], matches: [], standings: [], standingsGameId: null, tournaments: [], games: [], selectedGameId: null, rules: {}, match: null, frames: [],
  cursor: 0, paused: false, speed: 1, socket: null, generation: 0,
  switchingGame: false, launching: false, transition: null, nextFrameAt: 0,
  victoryDismissed: false, displayedResult: false, reconnectTimer: null,
  participant: null, readOnly: false, refreshing: false,
  role: "player", organizerAvailable: false,
  competition: null, competitionSocket: null, competitionTimer: null,
  competitionGeneration: 0, competitionBusy: false, shuttingDown: false,
  lobby: null, invitationBusy: false, seenStarts: new Set(), seenFinishes: new Set(), heartbeatTimer: null,
};

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

let toastTimer;
function toast(message, error = false) {
  const node = $("#toast");
  node.textContent = message;
  node.className = "toast" + (error ? " error" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => node.classList.add("hidden"), error ? 8500 : 4000);
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const raw = await response.text();
  let data;
  try {
    data = raw ? JSON.parse(raw) : {};
  } catch {
    if (!response.ok) throw new Error(`HTTP ${response.status}: ${raw.slice(0, 240)}`);
    throw new Error("Máy chủ trả về dữ liệu không hợp lệ.");
  }
  if (!response.ok) {
    const detail = Array.isArray(data.detail)
      ? data.detail.map(item => `${item.loc?.join(".")}: ${item.msg}`).join("; ")
      : data.detail;
    throw new Error(detail || `HTTP ${response.status}`);
  }
  return data;
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
    row.append(info, el("span", `match-status ${player.online ? "running" : "interrupted"}`, player.status));
    if (player.current_match_id) {
      const live = el("button", "button ghost small", "LIVE ↗");
      live.onclick = () => loadMatch(player.current_match_id).catch(e => toast(e.message, true)); row.append(live);
    }
    if (app.role === "organizer" && !app.readOnly) {
      const remove = el("button", "button ghost small player-delete", "XÓA PLAYER");
      remove.type = "button";
      remove.title = "Xóa Player khỏi danh sách hoạt động";
      remove.addEventListener("click", async () => {
        if (!window.confirm(
          `Xóa ${player.display_name} khỏi danh sách Player? Lịch sử trận và bảng xếp hạng đã lưu sẽ được giữ lại.`
        )) return;
        remove.disabled = true;
        try {
          await api(`/api/players/${player.player_id}`, { method: "DELETE" });
          app.lobby.players = await api("/api/players");
          acceptLobby(app.lobby);
          toast(`${player.nickname} đã được xóa khỏi danh sách Player.`);
        } catch (error) {
          toast(error.message, true);
          remove.disabled = false;
        }
      });
      row.append(remove);
    }
    players.append(row);
  }

  renderTournamentPlayerOptions();

  const me = lobby.me;
  $("#player-status").textContent = me?.status || "OFFLINE";
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

function renderTournamentPlayerOptions() {
  const target = $("#tournament-player-options");
  if (!target) return;

  const previouslySelected = new Set(
    [...target.querySelectorAll('input[name="tournament_player_id"]:checked')]
      .map(input => input.value)
  );

  target.replaceChildren();

  const players = app.lobby?.players || [];
  if (!players.length) {
    target.append(el("div", "empty-state", "Chưa có Player nào."));
    return;
  }

  for (const player of players) {
    const label = el("label", "tournament-player-option");
    const checkbox = document.createElement("input");

    checkbox.type = "checkbox";
    checkbox.name = "tournament_player_id";
    checkbox.value = player.player_id;
    checkbox.checked = previouslySelected.has(player.player_id);

    label.append(
      checkbox,
      el("span", "", `${player.nickname} · ${player.status}`)
    );
    target.append(label);
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
    row.append(info, el("span", "match-status", inv.finished ? "FINISHED" : inv.status));
    if (app.role === "organizer" && ["PENDING", "PARTIALLY_ACCEPTED"].includes(inv.status)) {
      const cancel = el("button", "button ghost small", "CANCEL");
      cancel.onclick = async () => { try { await api(`/api/invitations/${inv.id}/cancel`, { method: "POST" }); } catch (error) { toast(error.message, true); } };
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
  $("#invitation-wait").textContent = accepted ? "WAITING FOR OPPONENT... Active Bot đã chốt." : "Chấp nhận để xác nhận Active Bot hiện tại của bạn.";
  $("#invitation-accept").disabled = accepted || app.invitationBusy || app.readOnly;
  $("#invitation-decline").disabled = app.invitationBusy || app.readOnly;
  updateInvitationCountdown();
  if (!dialog.open) dialog.showModal();
}

function updateInvitationCountdown() {
  if (!app.currentInvitation) return;
  const left = Math.max(0, Math.ceil((app.currentInvitation.expires_at * 1000 - Date.now() - app.serverClockOffset) / 1000));
  $("#invitation-countdown").textContent = `${left}s TO RESPOND`;
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
  const allowed = organizer && app.competition?.can_edit && !app.competitionBusy;
  $$("#rules-form input, #rules-form textarea, #rules-form select, #rules-form [type=submit], #default-rules").forEach(node => {
    node.disabled = !allowed; node.title = allowed ? "" : "Cần quyền Organizer và cuộc thi đang ở trạng thái cấu hình";
  });
  $$(".game-select, .game-card").forEach(node => { node.disabled = !allowed || app.switchingGame; });
  $("#competition-open").disabled = !allowed;
  $("#competition-close").disabled = !organizer || !app.competition?.competition_locked || app.competitionBusy;
  $("#competition-open").classList.toggle("hidden", app.role !== "organizer");
  $("#competition-close").classList.toggle("hidden", app.role !== "organizer");
  $("#rules-access-note").textContent = app.competition?.competition_locked ? "LOCKED RULESET / Snapshot đã chốt. Đóng cuộc thi và chờ các trận kết thúc để cấu hình lại." : allowed ? "ORGANIZER / Chọn game, lưu luật rồi LOCK GAME / OPEN COMPETITION." : "PLAYER / Game và luật do ban tổ chức chốt. Chọn Active Bot rồi chờ lời mời.";
  $$(".organizer-only").forEach(node => node.classList.toggle("hidden", !organizer));
  $$(".player-only, [data-go=upload], .nav-item[data-view=upload]").forEach(node => node.classList.toggle("hidden", organizer));
  $$("#rules-form [type=submit], #default-rules").forEach(node => node.classList.toggle("hidden", !organizer));
  if (organizer && location.hash === "#upload") location.hash = "create";
  $$("#quick-match [type=submit], #create-match [type=submit]").forEach(node => {
    node.disabled = !organizer || !app.competition?.competition_locked || app.launching || app.competitionBusy
      || (app.lobby?.players || []).filter(player => player.status === "READY").length < 2;
  });
  $$("#upload-form [type=submit], #seed-samples, [data-sample]").forEach(node => { node.disabled = organizer || app.readOnly; });
  renderCompetitionBanner();
}

function renderCompetitionBanner() {
  const state = app.competition;
  $("#competition-status").textContent = state?.phase === "open" ? "COMPETITION OPEN" : state?.phase === "draining" ? "CLOSING / WAITING" : "WAITING FOR ORGANIZER";
  $("#competition-banner").classList.toggle("competition-live", state?.competition_locked === true);
  $("#competition-game").textContent = app.games.find(game => game.game_id === state?.selected_game_id)?.name || "Đang tải game…";
  $("#competition-message").textContent = state?.phase === "open" ? "Game và luật đã khóa. Organizer mời hai Player READY; trận bắt đầu sau hai lượt ACCEPT." : state?.phase === "draining" ? `Đã chặn trận mới. Đang chờ ${state.pending_matches} trận/bot kết thúc trước khi mở khóa cấu hình.` : "Ban tổ chức đang chuẩn bị game và luật. Có thể nộp bot cho game hiện tại; chưa thể tạo trận.";
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
  if (app.shuttingDown) return;
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${scheme}://${location.host}/ws/competition`);
  app.competitionSocket = socket;
  socket.onopen = () => {
    clearInterval(app.heartbeatTimer);
    const beat = () => { if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: "heartbeat" })); };
    beat(); app.heartbeatTimer = setInterval(beat, 10000);
  };
  socket.onmessage = event => {
    if (socket !== app.competitionSocket) return;
    let message; try { message = JSON.parse(event.data); } catch { return; }
    if (message.type === "competition") {
      const restarted = app.competition && app.competition.server_id !== message.state.server_id;
      if (restarted) api("/api/session").then(acceptSession).catch(() => {});
      acceptCompetition(message.state).catch(error => toast(error.message, true));
      if (message.role && message.role !== app.role) api("/api/session").then(acceptSession).catch(() => {});
      if (message.lobby) acceptLobby(message.lobby);
    }
  };
  socket.onclose = () => {
    if (socket === app.competitionSocket) clearInterval(app.heartbeatTimer);
    if (!app.shuttingDown && socket === app.competitionSocket) app.competitionTimer = setTimeout(connectCompetitionSocket, 1200);
  };
}

function acceptSession(data) {
  app.participant = data.participant; app.readOnly = data.read_only;
  app.role = data.role; app.organizerAvailable = data.organizer_available;
  renderSession();
  renderBots();
  renderInvitations();
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

const labels = { home: "OVERVIEW", standings: "BẢNG XẾP HẠNG", upload: "BOT LABORATORY", create: "MATCH CONTROL", tournaments: "GIẢI ĐẤU", watch: "BATTLE ARCHIVE", rules: "GAME CONFIGURATION" };
function navigate() {
  let view = location.hash.slice(1) || "home";
  if (!labels[view]) view = "home";
  $$(".view").forEach(node => node.classList.toggle("active", node.id === `view-${view}`));
  $$(".nav-item").forEach(node => node.classList.toggle("active", node.dataset.view === view));
  $("#page-label").textContent = labels[view];
  window.scrollTo({ top: 0, behavior: "instant" });
}
window.addEventListener("hashchange", navigate);
$$("[data-go]").forEach(button => button.addEventListener("click", () => { location.hash = button.dataset.go; }));
navigate();

function setConnection(online) {
  $("#connection").replaceChildren(el("i", "status-dot"), document.createTextNode(online ? "SYSTEM ONLINE" : "SERVER OFFLINE"));
  $("#connection .status-dot").style.background = online ? "var(--green)" : "var(--pink)";
}

function renderStats() {
  $("#stat-bots").textContent = String(app.bots.length).padStart(2, "0");
  $("#stat-matches").textContent = String(app.matches.filter(m => m.status === "completed").length).padStart(2, "0");
  const running = app.matches.filter(m => ["running", "queued"].includes(m.status)).length;
  $("#stat-live").textContent = String(running).padStart(2, "0");
  $("#live-note").textContent = running ? "BATTLE IN PROGRESS" : "SYSTEM STANDBY";
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
  target.replaceChildren();
  const mine = app.bots.filter(bot => bot.owner?.id === app.participant?.id);
  if (!mine.length) target.append(el("div", "empty-state", "Chưa có submission. Tải code hoặc dùng bot mẫu ở trên."));
  mine.forEach(bot => {
    const row = el("div", "bot-row");
    row.append(el("span", `language-icon ${bot.language === "py" ? "python" : bot.language}`, bot.language.toUpperCase()));
    const description = el("div", "bot-description");
    description.append(el("strong", "", bot.name), el("small", "", bot.filename));
    description.append(el("small", "bot-owner", `NỘP BỞI / ${ownerLabel(bot.owner)}`));
    description.append(el("span", "tag", app.games.find(game => game.game_id === bot.game_id)?.name || bot.game_id));
    row.append(description, el("span", `match-status ${bot.status === "error" ? "interrupted" : ""}`, bot.status.toUpperCase()));
    const active = app.lobby?.me?.active_bot_id === bot.id;
    const button = el("button", "button ghost small", active ? "ACTIVE BOT ✓" : "SET AS ACTIVE BOT");
    button.disabled = app.role !== "player" || app.readOnly || bot.status !== "ready" || bot.game_id !== app.selectedGameId || active || activeFrozen();
    button.addEventListener("click", async () => {
      button.disabled = true;
      try { await api("/api/players/active-bot", jsonOptions("PUT", { bot_id: bot.id })); toast("Đã chọn Active Bot. Chờ Organizer gửi lời mời."); }
      catch (error) { toast(error.message, true); }
    });
    row.append(button);
    if (bot.logs) {
      const details = el("details");
      details.append(el("summary", "", "Compiler log"), el("pre", "", bot.logs));
      row.append(details);
    }
    target.append(row);
  });
  populateBotSelectors();
  renderStats();
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
  $("#game-description").textContent = game.description;
  $("#rules-heading").textContent = `${game.name.toUpperCase()} / RULESET`;
  $("#create-game-label").textContent = game.badge || game.name;
  $("#match-mode-hint").textContent = game.turn_mode === "simultaneous" ? "Hai bot nhận cùng trạng thái và hành động đồng thời." : "Hai bot đi luân phiên. Server chỉ hỏi bot đến lượt.";
  const source = $("#game-source");
  source.classList.toggle("hidden", !game.source_url);
  if (game.source_url) source.href = game.source_url;
  const fixed = $("#game-fixed");
  fixed.replaceChildren(...Object.entries(game.fixed_rules || {}).map(([key, value]) => {
    const item = el("span", "fixed-rule");
    item.append(el("small", "", key.toUpperCase()), document.createTextNode(String(value)));
    return item;
  }));
  const library = $("#game-library");
  library.replaceChildren(...app.games.map(installed => {
    const button = el("button", "game-card" + (installed.game_id === app.selectedGameId ? " selected" : ""));
    button.type = "button"; button.dataset.gameId = installed.game_id;
    button.setAttribute("aria-pressed", String(installed.game_id === app.selectedGameId));
    const copy = el("div", "game-card-copy");
    copy.append(el("h2", "", installed.name), el("p", "", installed.description), el("small", "", `INSTALLED / v${installed.version} / ${installed.turn_mode.toUpperCase()}`));
    button.append(el("span", "game-card-icon", installed.name.slice(0, 2).toUpperCase()), copy);
    button.addEventListener("click", () => selectGame(installed.game_id));
    return button;
  }));
  $("#rules-guide").replaceChildren(...[...(game.guide || []), { title: "BOT FAULT", description: "Timeout, crash, JSON hoặc action không hợp lệ: bot bị xử thua. Game state chỉ do server cập nhật." }].map((item, index) => {
    const row = el("li"), copy = el("div");
    copy.append(el("strong", "", item.title), el("p", "", item.description));
    row.append(el("span", "", String(index + 1).padStart(2, "0")), copy);
    return row;
  }));
  const properties = game.rules_schema.properties || {};
  if (fillForm) {
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
      if (schema.type === "boolean") input.checked = Boolean(app.rules[key]);
      else input.value = ["object", "array"].includes(schema.type) ? JSON.stringify(app.rules[key], null, 2) : String(app.rules[key] ?? schema.default ?? "");
      input.required = schema.type !== "boolean";
      label.append(input);
      if (schema.description) label.append(el("small", "field-description", schema.description));
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
    link.href = `/api/games/${game.game_id}/samples/${sample.language}`;
    link.title = `Tải bot ${sample.language}`;
    const button = el("button", "icon-button", "＋");
    button.dataset.sample = sample.language; button.title = `Nộp mẫu ${sample.language}`;
    button.addEventListener("click", async () => {
      button.disabled = true;
      try { const bot = await addSample(sample.language, game.game_id); toast(`${bot.name} đã sẵn sàng.`); }
      catch (error) { toast(error.message, true); }
      finally { button.disabled = false; await refreshBots().catch(() => {}); }
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
  return match.result.winner ? `${fighterLabel(match, match.result.winner)} WINS` : "DRAW";
}

function renderMatchList(target, matches) {
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
    row.append(names, el("span", `match-status ${match.status}`, match.status.toUpperCase()), el("span", "match-result", resultDescription(match)));
    const button = el("button", "button ghost", ["running", "queued"].includes(match.status) ? "Live ↗" : "Replay ↗");
    button.addEventListener("click", () => loadMatch(match.id).catch(error => toast(error.message, true)));
    row.append(button);
    target.append(row);
  });
}

function renderMatches() {
  renderMatchList($("#recent-matches"), app.matches.slice(0, 4));
  renderMatchList($("#all-matches"), app.matches);
  $("#history-count").textContent = `${app.matches.length} MATCHES`;
  renderStats();
}

function renderStandings() {
  const tbody = $("#standings-body");
  tbody.replaceChildren();

  if (!app.standings.length) {
    const row = el("tr");
    const cell = el("td", "empty-state", "Game này chưa có kết quả trận đấu tự do.");
    cell.colSpan = 6;
    row.append(cell);
    tbody.append(row);
    return;
  }

  for (const player of app.standings) {
    const row = el("tr");

    [
      player.rank,
      player.nickname,
      player.played,
      player.wins,
      player.draws,
      player.losses,
    ].forEach((value, index) => {
      row.append(el("td", index === 3 ? "standing-wins" : "", String(value ?? 0)));
    });

    tbody.append(row);
  }
}

function renderTournaments() {
  const target = $("#tournaments-list");
  const expanded = new Set(
    [...target.querySelectorAll(".tournament-details[open]")]
      .map(node => node.dataset.tournamentId)
  );
  target.replaceChildren();

  if (!app.tournaments.length) {
    target.append(el("div", "empty-state", "Chưa có giải đấu nào."));
    return;
  }

  const formatNames = {
    single_elimination: "Loại trực tiếp",
    double_elimination: "Double elimination",
    round_robin: "Vòng tròn tính điểm",
  };
  const statusNames = {
    registration: "ĐANG ĐĂNG KÝ",
    active: "ĐANG DIỄN RA",
    completed: "ĐÃ KẾT THÚC",
  };
  const bracketNames = {
    main: "NHÁNH LOẠI TRỰC TIẾP",
    winners: "NHÁNH THẮNG",
    losers: "NHÁNH THUA",
    final: "CHUNG KẾT",
  };
  const matchStatusNames = {
    pending: "CHỜ NGƯỜI CHƠI SẴN SÀNG", waiting: "CHỜ VÒNG TRƯỚC", bye: "MIỄN ĐẤU",
    invited: "ĐÃ GỬI LỜI MỜI", playing: "ĐANG THI ĐẤU", completed: "ĐÃ CÓ KẾT QUẢ",
    needs_attention: "CẦN ORGANIZER XỬ LÝ", skipped: "KHÔNG CẦN THI ĐẤU",
  };
  const retryTournamentMatch = (tournament, match, button) => {
    button.addEventListener("click", async () => {
      button.disabled = true;
      try {
        await api(`/api/tournaments/${tournament.id}/matches/${match.id}/retry`, { method: "POST" });
        await refreshTournaments();
        toast("Đã đưa cặp đấu trở lại hàng chờ tự động ghép trận.");
      } catch (error) {
        button.disabled = false;
        toast(error.message, true);
      }
    });
  };

  for (const tournament of app.tournaments) {
    const row = el("article", "tournament-card");
    const heading = el("div", "tournament-card-heading");
    const titleBlock = el("div", "tournament-card-title");
    const status = tournament.status || "registration";
    const players = tournament.participants || [];

    titleBlock.append(
      el("span", "tournament-id", `TOURNAMENT / ${(tournament.id || "").slice(0, 8).toUpperCase()}`),
      el("h3", "", tournament.name)
    );
    heading.append(
      titleBlock,
      el("span", `tournament-status ${status}`, statusNames[status] || status.toUpperCase())
    );

    const details = el("div", "tournament-meta");
    details.append(
      el("span", "tournament-meta-item", formatNames[tournament.format] || tournament.format),
      el("span", "tournament-meta-item", `${players.length} người chơi`)
    );

    const participants = el("div", "tournament-players");
    participants.append(el("span", "tournament-players-label", "NGƯỜI CHƠI"));
    const playerList = el("div", "tournament-player-chips");
    for (const player of players) {
      playerList.append(el("span", "tournament-player-chip", player.nickname));
    }
    if (!players.length) playerList.append(el("span", "tournament-player-chip muted", "Chưa có người chơi"));
    participants.append(playerList);

    const actions = el("div", "tournament-actions");
    if (app.role === "organizer" && status === "registration") {
      const startButton = el("button", "button primary small", "BẮT ĐẦU & TẠO NHÁNH");
      startButton.type = "button";
      startButton.addEventListener("click", async () => {
        startButton.disabled = true;
        try {
          const started = await api(`/api/tournaments/${tournament.id}/start`, { method: "POST" });
          app.tournaments = app.tournaments.map(item => item.id === started.id ? started : item);
          renderTournaments();
        } catch (error) {
          toast(error.message, true);
          startButton.disabled = false;
        }
      });
      actions.append(startButton);
    }
    if (app.role === "organizer") {
      const deleteButton = el("button", "button ghost small tournament-delete", "XÓA GIẢI");
      deleteButton.type = "button";
      deleteButton.addEventListener("click", async () => {
        if (!window.confirm(`Bạn có chắc muốn xóa giải "${tournament.name}"? Thao tác này không thể hoàn tác.`)) return;
        deleteButton.disabled = true;
        try {
          await api(`/api/tournaments/${tournament.id}`, { method: "DELETE" });
          app.tournaments = app.tournaments.filter(item => item.id !== tournament.id);
          renderTournaments();
          toast(`Đã xóa giải "${tournament.name}".`);
        } catch (error) {
          toast(error.message, true);
          deleteButton.disabled = false;
        }
      });
      actions.append(deleteButton);
    }

    const disclosure = el("details", "tournament-details");
    disclosure.dataset.tournamentId = tournament.id;
    disclosure.open = expanded.has(tournament.id);
    const summary = el("summary", "", tournament.rounds?.length ? "XEM NHÁNH / LỊCH ĐẤU" : "XEM THỂ LỆ GIẢI");
    disclosure.append(summary);

    if (!tournament.rounds?.length) {
      disclosure.append(el("p", "tournament-draw-note", "Organizer bắt đầu giải để tạo nhánh hoặc lịch thi đấu."));
    } else if (tournament.format === "round_robin") {
      if (tournament.standings?.length) {
        const table = el("div", "tournament-standings");
        table.append(el("div", "tournament-standing-row heading", "HẠNG · NGƯỜI CHƠI · TRẬN · THẮNG · HÒA · THUA · ĐIỂM · ĐIỂM ĐỐI ĐẦU · HIỆU SỐ"));
        tournament.standings.forEach((player, index) => {
          table.append(el("div", "tournament-standing-row",
            `${player.rank ?? index + 1}. ${player.nickname} · ${player.played} · ${player.wins} · ${player.draws} · ${player.losses} · ${player.points} · ${player.head_to_head} · ${player.score_difference > 0 ? "+" : ""}${player.score_difference}`));
        });
        disclosure.append(table);
      }
      const schedule = el("div", "tournament-schedule");
      const currentRoundIndex = tournament.rounds.findIndex(round =>
        (round.matches || []).some(match => !["completed", "skipped"].includes(match.status))
      );
      tournament.rounds.forEach((round, roundIndex) => {
        const roundCard = el("section", "tournament-round tournament-schedule-round");
        const roundHeading = el("div", "tournament-round-heading");
        roundHeading.append(el("h4", "", round.name));
        if (roundIndex === currentRoundIndex) {
          roundHeading.append(el("span", "tournament-round-state active", "VÒNG ĐANG MỞ"));
        } else if (currentRoundIndex >= 0 && roundIndex > currentRoundIndex) {
          roundHeading.append(el("span", "tournament-round-state waiting", "CHỜ VÒNG TRƯỚC"));
        } else if (currentRoundIndex >= 0 && roundIndex < currentRoundIndex) {
          roundHeading.append(el("span", "tournament-round-state done", "ĐÃ HOÀN TẤT"));
        } else {
          roundHeading.append(el("span", "tournament-round-state done", "ĐÃ HOÀN TẤT"));
        }
        roundCard.append(roundHeading);
        for (const match of round.matches || []) {
          const matchCard = el("div", "tournament-schedule-match");
          const a = match.player_a?.nickname || "Chưa xác định";
          const b = match.player_b?.nickname || "Chưa xác định";
          matchCard.append(el("span", "", a), el("span", "tournament-versus", "VS"), el("span", "", b));
          const winner = players.find(player => player.player_id === match.winner_id);
          const resultLabel = roundIndex > currentRoundIndex && currentRoundIndex >= 0
            ? "CHỜ VÒNG TRƯỚC"
            : match.status === "completed"
            ? (winner ? `THẮNG: ${winner.nickname}` : "HÒA")
            : matchStatusNames[match.status] || (match.status || "").toUpperCase();
          matchCard.append(el("small", `tournament-match-state ${match.status || ""}`, resultLabel));
          if (app.role === "organizer" && match.status === "needs_attention") {
            const retry = el("button", "button ghost small", "GỬI LẠI LỜI MỜI");
            retry.type = "button";
            retryTournamentMatch(tournament, match, retry);
            matchCard.append(retry);
          }
          roundCard.append(matchCard);
        }
        if (round.bye_player) {
          roundCard.append(el("p", "tournament-bye-note", `${round.bye_player.nickname} được nghỉ vòng này.`));
        }
        schedule.append(roundCard);
      });
      disclosure.append(schedule);
    } else {
      const bracket = el("div", "tournament-bracket");
      const lanes = tournament.format === "double_elimination"
        ? ["winners", "losers", "final"]
        : ["main"];
      for (const laneName of lanes) {
        const laneRounds = (tournament.rounds || []).filter(round => round.bracket === laneName);
        if (!laneRounds.length) continue;
        const lane = el("section", "tournament-bracket-lane");
        lane.append(el("h4", "", bracketNames[laneName]));
        const board = el("div", "tournament-bracket-board");
        for (const round of laneRounds) {
          const roundColumn = el("div", "tournament-bracket-round");
          roundColumn.append(el("h5", "", round.name));
          for (const match of round.matches || []) {
            const matchCard = el("div", `tournament-bracket-match ${match.status || "waiting"}`);
            const sideName = (player, source) => player?.nickname || source || "Chờ người thắng vòng trước";
            matchCard.append(
              el("span", "tournament-bracket-player", sideName(match.player_a, match.source_a)),
              el("span", "tournament-bracket-player", sideName(match.player_b, match.source_b)),
              el("small", "", matchStatusNames[match.status] || (match.status || "").toUpperCase())
            );
            if (match.winner_id) {
              const winner = players.find(player => player.player_id === match.winner_id);
              if (winner) matchCard.append(el("small", "tournament-match-winner", `THẮNG · ${winner.nickname}`));
            }
            if (app.role === "organizer" && match.status === "needs_attention") {
              const retry = el("button", "button ghost small", "GỬI LẠI LỜI MỜI");
              retry.type = "button";
              retryTournamentMatch(tournament, match, retry);
              matchCard.append(retry);
            }
            roundColumn.append(matchCard);
          }
          board.append(roundColumn);
        }
        lane.append(board);
        bracket.append(lane);
      }
      disclosure.append(bracket);
    }

    row.append(heading, details, participants);
    if (actions.childElementCount) row.append(actions);
    row.append(disclosure);
    target.append(row);
  }
}

async function refreshBots() { app.bots = await api("/api/bots"); renderBots(); }
function populateStandingsGameSelector() {
  const select = $("#standings-game-select");
  if (!select) return;
  select.replaceChildren(...app.games.map(game => {
    const option = el("option", "", game.name);
    option.value = game.game_id;
    return option;
  }));

  const preferred = app.competition?.selected_game_id;
  app.standingsGameId = app.games.some(game => game.game_id === preferred)
    ? preferred
    : app.games[0]?.game_id || null;
  select.value = app.standingsGameId || "";
  select.disabled = !app.games.length;
}

async function refreshStandings() {
  const query = app.standingsGameId
    ? `?game_id=${encodeURIComponent(app.standingsGameId)}`
    : "";
  app.standings = await api(`/api/standings${query}`);
  renderStandings();
}

async function refreshTournaments() {
  app.tournaments = await api("/api/tournaments");
  renderTournaments();
}
async function refreshMatches() {
  const [matches] = await Promise.all([
    api("/api/matches"),
    refreshStandings(),
  ]);

  app.matches = matches;
  renderMatches();
}
$("#refresh-bots").addEventListener("click", () => refreshBots().catch(e => toast(e.message, true)));
$("#refresh-matches").addEventListener("click", () => refreshMatches().catch(e => toast(e.message, true)));
$("#refresh-tournaments").addEventListener("click", () => refreshTournaments().catch(e => toast(e.message, true)));
$("#standings-game-select").addEventListener("change", event => {
  app.standingsGameId = event.currentTarget.value || null;
  refreshStandings().catch(error => toast(error.message, true));
});

function feedback(selector, message, error = false) {
  const target = $(selector);
  target.textContent = message;
  target.className = "feedback" + (error ? " error" : "");
}

$("#tournament-create-form").addEventListener("submit", async event => {
  event.preventDefault();

  const form = event.currentTarget;
  const button = form.querySelector('[type="submit"]');
  const formData = new FormData(form);

  const player_ids = [
    ...form.querySelectorAll('input[name="tournament_player_id"]:checked')
  ].map(input => input.value);

  const payload = {
    name: formData.get("name"),
    format: formData.get("format"),
    player_ids,
  };

  button.disabled = true;

  try {
    const tournament = await api(
      "/api/tournaments",
      jsonOptions("POST", payload)
    );

    feedback(
      "#tournament-feedback",
      `Đã tạo giải "${tournament.name}".`
    );
    app.tournaments.unshift(tournament);
    renderTournaments();
    form.reset();
    renderTournamentPlayerOptions();
  } catch (error) {
    feedback("#tournament-feedback", error.message, true);
  } finally {
    button.disabled = false;
  }
});

$("#upload-form").addEventListener("submit", async event => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("[type=submit]");
  const file = $("#bot-file").files[0];
  if (!file || file.size > 256 * 1024 || !/\.(py|cpp|java)$/i.test(file.name)) {
    feedback("#upload-feedback", "Chọn file .py, .cpp hoặc .java không vượt quá 256 KiB.", true);
    return;
  }
  button.disabled = true;
  button.textContent = "Đang tải & biên dịch…";
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
    if (bot.status === "ready") { form.reset(); populateGameSelectors(); $("#file-label").textContent = "Chọn hoặc kéo file vào đây"; }
  } catch (error) { feedback("#upload-feedback", error.message, true); }
  finally { button.disabled = false; button.textContent = "Upload & Compile ↗"; applyPermissions(); }
});
$("#bot-file").addEventListener("change", () => { $("#file-label").textContent = $("#bot-file").files[0]?.name || "Chọn hoặc kéo file vào đây"; });
const dropZone = $("#drop-zone");
["dragenter", "dragover"].forEach(name => dropZone.addEventListener(name, () => dropZone.classList.add("dragover")));
["dragleave", "drop"].forEach(name => dropZone.addEventListener(name, () => dropZone.classList.remove("dragover")));

async function addSample(language, gameId = app.selectedGameId) {
  const bot = await api(`/api/games/${gameId}/samples/${language}/submit`, { method: "POST" });
  if (bot.status !== "ready") throw new Error(bot.logs || "Biên dịch bot mẫu thất bại.");
  return bot;
}
$("#seed-samples").addEventListener("click", async event => {
  const button = event.currentTarget;
  button.disabled = true;
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
  } finally { button.disabled = false; button.textContent = "Thêm bot mẫu ↗"; applyPermissions(); }
});

$("#rules-form").addEventListener("submit", async event => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("[type=submit]");
  const game = selectedGame();
  if (!game) return;
  button.disabled = true;
  try {
    const rules = Object.fromEntries(Object.entries(game.rules_schema.properties).map(([key, schema]) => {
      const input = form.elements[key];
      const value = schema.type === "boolean" ? input.checked : ["integer", "number"].includes(schema.type) ? Number(input.value) : ["object", "array"].includes(schema.type) ? JSON.parse(input.value) : input.value;
      return [key, value];
    }));
    await api(`/api/games/${game.game_id}/rules`, jsonOptions("PUT", rules));
    await acceptCompetition(await api("/api/competition"));
    feedback("#rules-feedback", "Đã lưu. Bộ luật này áp dụng cho các trận bắt đầu từ bây giờ.");
  } catch (error) { feedback("#rules-feedback", error.message, true); }
  finally { applyPermissions(); }
});
$("#default-rules").addEventListener("click", async event => {
  const game = selectedGame();
  if (!game) return;
  const button = event.currentTarget; button.disabled = true;
  try {
    await api(`/api/games/${game.game_id}/rules/reset`, { method: "POST" });
    await acceptCompetition(await api("/api/competition"));
    feedback("#rules-feedback", `Đã khôi phục và lưu luật mặc định của ${game.name}.`);
  } catch (error) { feedback("#rules-feedback", error.message, true); }
  finally { applyPermissions(); }
});

for (const [selector, action] of [["#competition-open", "open"], ["#competition-close", "close"]]) {
  $(selector).addEventListener("click", async () => {
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
  if (generation !== app.generation) return;
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${scheme}://${location.host}/ws/matches/${id}?after=${app.frames.length - 1}`);
  app.socket = socket;
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
  socket.onclose = () => {
    if (generation !== app.generation || !["running", "queued"].includes(app.match?.status)) return;
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
  socket.onerror = () => { $("#feed-label").textContent = "RECONNECTING…"; };
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
    $("#fighter-" + key + "-name").textContent = app.match ? fighterLabel(app.match, player) : "CHƯA CHỌN BOT";
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
  const live = ["running", "queued"].includes(app.match?.status);
  const status = $("#arena-status");
  status.classList.toggle("running", live);
  const label = !app.match ? "STANDBY" : app.paused ? "PAUSED" : live ? "LIVE" : "REPLAY";
  status.replaceChildren(el("i"), document.createTextNode(label));
  $("#feed-label").textContent = !app.match ? "WAITING FOR MATCH" : app.paused ? "PLAYBACK PAUSED / BACKEND CONTINUES" : live ? "WEBSOCKET / LIVE FEED" : "REPLAY / SAVED JSON";
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
  $("#victory-title").textContent = app.match?.status === "interrupted" ? "INTERRUPTED" : result.winner ? "VICTORY" : "DRAW";
  $("#victory-winner").textContent = result.winner ? fighterLabel(app.match, result.winner) : "KHÔNG CÓ NGƯỜI THẮNG";
  const reasons = { bot_error: "Lỗi bot: " + Object.entries(result.faults || {}).map(([p, error]) => `${p}: ${error}`).join(" · "), server_restart: "Máy chủ đã khởi động lại giữa trận.", server_shutdown: "Máy chủ dừng giữa trận.", server_error: "Máy chủ gặp lỗi khi xử lý trận đấu." };
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
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
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
  try {
    // Establish the cookie first; parallel startup requests then share one identity.
    const session = await api("/api/session");
    acceptSession(session);
    const [health, bots, registry, matches, tournaments, competition] = await Promise.all([
      api("/api/health"),
      api("/api/bots"),
      api("/api/games"),
      api("/api/matches"),
      api("/api/tournaments"),
      api("/api/competition"),
    ]);
    app.bots = bots; app.games = registry.games; app.matches = matches; app.tournaments = tournaments;
    await acceptCompetition(competition);
    populateStandingsGameSelector();
    await refreshStandings();
    setConnection(health.status === "ok");
    renderBots(); renderRules(true); renderMatches(); renderStandings(); renderTournaments();
    applyPermissions();
    connectCompetitionSocket();
    const matchId = new URL(location.href).searchParams.get("match");
    if (matchId) await loadMatch(matchId);
  } catch (error) { setConnection(false); toast(`Không kết nối được backend: ${error.message}`, true); }
}
bootstrap();
setInterval(async () => {
  if (document.hidden || app.refreshing || !app.participant) return;
  app.refreshing = true;
  try { await Promise.all([refreshMatches(), refreshBots(), refreshTournaments()]); setConnection(true); }
  catch { setConnection(false); }
  finally { app.refreshing = false; }
}, 2000);
window.addEventListener("beforeunload", () => { app.shuttingDown = true; app.generation++; app.socket?.close(); clearTimeout(app.competitionTimer); clearInterval(app.heartbeatTimer); app.competitionSocket?.close(); });
