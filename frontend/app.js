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
  accountOnly: false, accountAuth: false, account: null, accountAudience: null, csrf: null,
  usernameOnlySignup: false,
  team: null, activeTeamBot: null, officialMatches: [], officialTeams: [], teamTournaments: [],
  scrimmages: [], practiceRefreshing: false, replayKind: null, replayRequestId: null, replayPath: null,
  seasons: [], seasonsBusy: false,
  officialRefreshing: false, pollPauseUntil: 0, bootstrapTimer: null,
  logoutBusy: false, logoutError: false,
  competition: null, competitionSocket: null, competitionTimer: null, competitionRetryMs: 5000,
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

// Anonymous account-entry mutations require a trusted Origin, strict JSON/body
// limits and source rate limits on the server; they do not have a session CSRF
// token yet. Keep this list exact: other Account-Only writes still require CSRF.
const PUBLIC_ACCOUNT_ENTRY_PATHS = new Set([
  "/api/account/auth/login",
  "/api/account/auth/register",
  "/api/account/auth/verify-email",
  "/api/account/auth/resend-verification",
  "/api/account/auth/request-reset",
  "/api/account/auth/reset-password",
  "/api/player/auth/login",
  "/api/admin/auth/login",
  "/api/player/auth/activate",
]);

// A 403 can mean a forbidden operation or a session revoked between the
// request boundary and a domain permission check. Confirm auth before logout.
async function recheckAccountAfterForbidden(accountAtRequest, audienceAtRequest) {
  if (!app.accountOnly || !accountAtRequest || app.account !== accountAtRequest
      || app.accountAudience !== audienceAtRequest
      || !["player", "admin"].includes(audienceAtRequest)) return;
  try {
    const proof = await fetch(`/api/${audienceAtRequest}/auth/me`, {
      headers: { "Accept": "application/json" }, cache: "no-store"
    });
    // Genuine permission errors, throttling and failed probes do not prove
    // revocation. Never clear a newer login while an old probe is in flight.
    if (proof.status === 401 && app.account === accountAtRequest
        && app.accountAudience === audienceAtRequest) accountExpired();
  } catch {
    // Keep the original 403; a network error is not a revocation proof.
  }
}

async function api(path, options = {}) {
  if (typeof path !== "string" || !path.startsWith("/") || path.startsWith("//") || /^[a-zA-Z][a-zA-Z\d+.-]*:/.test(path)) {
    throw new Error("Đường dẫn API không hợp lệ.");
  }
  path = scopedApiPath(path);
  const requestUrl = new URL(path, window.location.origin);
  if (requestUrl.origin !== window.location.origin || !requestUrl.pathname.startsWith("/api/")) {
    throw new Error("Đường dẫn API không hợp lệ.");
  }
  const accountAtRequest = app.account, audienceAtRequest = app.accountAudience;
  const method = (options.method || "GET").toUpperCase();
  if (app.accountOnly && !["GET", "HEAD", "OPTIONS"].includes(method)
      && !PUBLIC_ACCOUNT_ENTRY_PATHS.has(requestUrl.pathname)) {
    const token = await accountCsrf();
    options = { ...options, headers: { ...(options.headers || {}), "X-CSRF-Token": token } };
    if (options.body === undefined) {
      options.body = "{}";
      options.headers["Content-Type"] = "application/json";
    }
  }
  let response;
  try { response = await fetch(requestUrl.toString(), options); }
  catch {
    const error = new Error("Mất kết nối với máy chủ. Kiểm tra mạng và thử lại.");
    error.transport = true;
    throw error;
  }
  const raw = await response.text();
  let data;
  try { data = raw ? JSON.parse(raw) : {}; }
  catch {
    if (!response.ok) throw new Error(`HTTP ${response.status}: ${raw.slice(0, 240)}`);
    throw new Error(`Máy chủ chưa sẵn sàng (HTTP ${response.status}). Hãy thử lại.`);
  }
  if (!response.ok) {
    const detail = Array.isArray(data.detail)
      ? data.detail.map(item => `${item.loc?.join(".")}: ${item.msg}`).join("; ")
      : data.detail;
    const error = new Error(detail || `HTTP ${response.status}`);
    error.status = response.status;
    if (app.accountOnly && response.status === 429) {
      // Server-enforced per-session budget; wait rather than repeatedly retry.
      const retryAfter = Number(response.headers.get("Retry-After"));
      const seconds = Number.isFinite(retryAfter) && retryAfter > 0
        ? Math.min(120, Math.ceil(retryAfter)) : 60;
      app.pollPauseUntil = Math.max(app.pollPauseUntil, Date.now() + seconds * 1000);
    }
    if (app.accountOnly && response.status === 401 && !path.includes("/auth/login")) accountExpired();
    if (app.accountOnly && response.status === 403) {
      await recheckAccountAfterForbidden(accountAtRequest, audienceAtRequest);
    }
    throw error;
  }
  return data;
}

function scopedApiPath(path) {
  if (!app.accountOnly || !path.startsWith("/api/") || path === "/api/health"
      || path.startsWith("/api/player/") || path.startsWith("/api/admin/")
      || path.startsWith("/api/account/")) return path;
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

// Account tools use their existing scoped authority; public navigation is only presentation.
$("#admin-recovery-host").append($("#admin-player-recovery-panel"));
let adminAccountOffset=0, adminAccountTotal=0, administrationBusy=false, systemBusy=false;
$("#profile-form").addEventListener("submit",async event=>{
  event.preventDefault();const form=event.currentTarget,button=form.querySelector("[type=submit]");busyButton(button,true);
  try {
    const response=await api(`/api/${app.accountAudience}/profile`,jsonOptions("PATCH",{display_name:form.elements.display_name.value}));
    app.account=response.account;app.participant.name=response.account.display_name;renderSession();
    feedback("#profile-feedback","Đã lưu hồ sơ.");
  } catch(error){feedback("#profile-feedback",error.message,true);}
  finally{busyButton(button,false);button.disabled=false;}
});

async function refreshAdministration() {
  if (administrationBusy || app.accountAudience!=="admin" || !app.account) return;
  administrationBusy=true;
  const account=app.account;
  try {
    const query=$("#admin-account-query").value.trim();
    const [response,teams,submissions]=await Promise.all([api(`/api/admin/accounts?offset=${adminAccountOffset}&search=${encodeURIComponent(query)}`),api("/api/admin/teams"),api("/api/admin/submissions")]);
    if (app.account!==account) return;
    adminAccountTotal=response.total;
    const target=$("#admin-accounts-body"),restore=preserveListState(target);target.replaceChildren();
    for(const user of response.accounts){
      const row=el("tr"),name=el("td");name.append(el("strong","",user.display_name),el("small","",user.username));
      row.append(name,el("td","",user.system_role),el("td","",user.status),el("td","",user.team_name||"Chưa có đội"));
      const actions=el("td"),buttons=el("div","form-buttons");
      if(user.system_role==="PLAYER"){
        if(["ACTIVE","DISABLED"].includes(user.status)){
          const action=user.status==="DISABLED"?"enable":"disable",button=el("button","button ghost small",action==="enable"?"Mở lại":"Vô hiệu hóa");
          button.type="button";button.dataset.focusKey=user.id+"-status";
          button.onclick=async()=>{
            if(!await confirmAction(action==="enable"?"Mở lại tài khoản?":"Vô hiệu hóa tài khoản?",action==="enable"?"Player có thể đăng nhập lại bằng mật khẩu đã có.":"Thu hồi các phiên đăng nhập hiện tại và chặn lần đăng nhập tiếp theo.",action==="enable"?"Mở lại":"Vô hiệu hóa"))return;
            button.disabled=true;
            try{await api(`/api/admin/accounts/${encodeURIComponent(user.id)}/${action}`,jsonOptions("POST",{}));await refreshAdministration();}
            catch(error){button.disabled=false;toast(error.message,true);}
          };buttons.append(button);
        }
        if(user.status==="ACTIVE"){
          const recovery=el("button","button ghost small","Khôi phục mật khẩu");recovery.type="button";recovery.dataset.focusKey=user.id+"-recover";
          recovery.onclick=()=>{
            const panel=$("#admin-player-recovery-panel");panel.querySelector("details").open=true;
            const input=$("#admin-player-recovery-form [name=username]");input.value=user.username;input.focus();
          };buttons.append(recovery);
        }
      } else buttons.append(el("span","form-note","Admin"));
      actions.append(buttons);row.append(actions);target.append(row);
    }
    if(!response.accounts.length){const row=el("tr"),cell=el("td","empty-state","Không tìm thấy tài khoản.");cell.colSpan=5;row.append(cell);target.append(row);}
    restore();
    setText("#admin-account-count",`${Math.min(response.total,adminAccountOffset+1)}–${Math.min(response.total,adminAccountOffset+response.accounts.length)} / ${response.total} tài khoản`);
    $("#admin-accounts-prev").disabled=adminAccountOffset===0;
    $("#admin-accounts-next").disabled=adminAccountOffset+response.limit>=response.total;
    renderAdminTeams(teams.teams);
    const bots=$("#admin-submissions-list");bots.replaceChildren();
    if(!submissions.bots.length)bots.append(el("div","empty-state","Chưa có submission."));
    for(const bot of submissions.bots){
      const row=el("article","bot-row"),copy=el("div","bot-description");copy.append(el("strong","",bot.name),el("small","",`${bot.game_id} · ${bot.language} · ${bot.status}`));
      const details=el("details"),summary=el("summary","","Xem chẩn đoán biên dịch"),log=el("pre","compiler-log");details.append(summary,log);let loaded=false;
      details.addEventListener("toggle",async()=>{if(!details.open||loaded)return;loaded=true;
        try{const response=await api(`/api/admin/submissions/${encodeURIComponent(bot.id)}`);log.textContent=response.bot.logs||"Không có lỗi biên dịch.";}
        catch(error){loaded=false;log.textContent=error.message;}
      });row.append(copy,details);bots.append(row);
    }
  }finally{administrationBusy=false;}
}
function renderAdminTeams(teams){
  const target=$("#admin-teams-list");target.replaceChildren();
  if(!teams.length)target.append(el("div","empty-state","Chưa có đội thi đấu."));
  for(const team of teams){
    const row=el("article","official-match-row"),copy=el("div","official-match-copy");
    copy.append(el("strong","",team.display_name),el("p","form-note",`${team.slug} · ${team.status} · ${team.member_count} thành viên`));row.append(copy);
    const members=el("button","button ghost small","Xem thành viên");members.type="button";
    members.onclick=async()=>{
      members.disabled=true;
      try{const detail=await api(`/api/admin/teams/${encodeURIComponent(team.id)}`);
        const list=el("div","team-member-detail");
        for(const member of detail.members)list.append(el("p","form-note",`${member.display_name} · ${member.username} · ${member.team_role}`));
        row.append(list);
      }catch(error){members.disabled=false;toast(error.message,true);}
    };row.append(members);
    if(team.status!=="ARCHIVED"){
      const archive=el("button","button ghost small","Lưu trữ đội");archive.type="button";
      archive.onclick=async()=>{
        if(!await confirmAction("Lưu trữ đội?",`${team.display_name} sẽ không nhận submission hoặc lịch thi đấu mới.`,"Lưu trữ đội"))return;
        archive.disabled=true;
        try{await api(`/api/admin/teams/${encodeURIComponent(team.id)}/archive`,jsonOptions("POST",{}));await refreshAdministration();}
        catch(error){archive.disabled=false;toast(error.message,true);}
      };row.append(archive);
    }
    target.append(row);
  }
}
$("#admin-account-search").addEventListener("submit",event=>{event.preventDefault();adminAccountOffset=0;refreshAdministration().catch(error=>toast(error.message,true));});
$("#admin-accounts-prev").onclick=()=>{adminAccountOffset=Math.max(0,adminAccountOffset-50);refreshAdministration().catch(error=>toast(error.message,true));};
$("#admin-accounts-next").onclick=()=>{if(adminAccountOffset+50<adminAccountTotal)adminAccountOffset+=50;refreshAdministration().catch(error=>toast(error.message,true));};
$("#admin-refresh-teams").onclick=()=>refreshAdministration().catch(error=>toast(error.message,true));
$("#admin-invite-form").addEventListener("submit",async event=>{
  event.preventDefault();const form=event.currentTarget,button=form.querySelector("[type=submit]");busyButton(button,true);
  $("#admin-invite-token").value="";$("#admin-invite-token-label").classList.add("hidden");
  try{const grant=await api("/api/admin/auth/invitations",jsonOptions("POST",{username:form.elements.username.value,name:form.elements.name.value}));
    $("#admin-invite-token").value=grant.token;$("#admin-invite-token-label").classList.remove("hidden");
    feedback("#admin-invite-feedback","Đã tạo lời mời. Gửi riêng mã kích hoạt cho đúng Player.");await refreshAdministration();
  }catch(error){feedback("#admin-invite-feedback",error.message,true);}
  finally{busyButton(button,false);button.disabled=false;}
});
async function refreshSystem(){
  if(systemBusy || app.accountAudience!=="admin" || !app.account)return;
  systemBusy=true;const account=app.account;
  try{const snapshot=await api("/api/admin/system");if(app.account!==account)return;
    const target=$("#system-status");target.replaceChildren();
    const rows=[["Runner",snapshot.runner.ready?"Sẵn sàng":"Không khả dụng"],["Chế độ thực thi",snapshot.runner.mode],["Battlecode 2026",snapshot.runner.battlecode26?"Đã cấu hình":"Chưa cấu hình"],["Trận đang chạy",`${snapshot.active_matches.length} / ${snapshot.capacity}`],["Scrimmage chờ",String(snapshot.scrimmages.QUEUED||0)],["Official đã lên lịch",String(snapshot.official.SCHEDULED||0)]];
    for(const[label,value]of rows){const pair=el("div");pair.append(el("dt","",label),el("dd","",value));target.append(pair);}
    for(const[selector,matches]of [["#system-active",snapshot.active_matches],["#system-interruptions",snapshot.recent_interruptions]]){
      const list=$(selector);list.replaceChildren();
      if(!matches.length)list.append(el("div","empty-state",selector==="#system-active"?"Không có trận đang chạy.":"Chưa ghi nhận trận bị gián đoạn."));
      for(const match of matches){const row=el("div","official-match-row"),copy=el("div","official-match-copy");copy.append(el("strong","",`${match.player_a_name_snapshot||"A"} vs ${match.player_b_name_snapshot||"B"}`),el("p","form-note",`${match.game_id} · ${match.status} · ${match.result?.reason||"Đang xử lý"}`));row.append(copy);list.append(row);}
    }
    $("#system-feedback").classList.add("hidden");
  }finally{systemBusy=false;}
}
$("#system-refresh").onclick=()=>refreshSystem().catch(error=>feedback("#system-feedback",error.message,true));

async function refreshSeasons(){
  if(app.seasonsBusy || !app.accountOnly || !app.account)return;
  app.seasonsBusy=true;const account=app.account;
  try{if(app.accountAudience==="admin")await refreshTeamTournaments();const response=await api(`/api/${app.accountAudience}/seasons`);if(app.account!==account)return;
    app.seasons=response.seasons;
    const game=$("#season-game");
    if(!game.childElementCount){
      for(const item of app.games){const option=el("option","",item.name);option.value=item.game_id;game.append(option);}
      game.value=app.selectedGameId;
      const form=$("#season-create");
      for(const[key,offset]of [["registration_opens_at",-60000],["registration_closes_at",86400000],["starts_at",90000000],["ends_at",176400000]])form.elements[key].value=officialLocalInput(Date.now()+offset);
    }
    const target=$("#season-list"),restore=preserveListState(target);target.replaceChildren();
    if(!app.seasons.length)target.append(el("div","empty-state","Chưa có mùa thi đấu. Admin sẽ mở đăng ký khi cuộc thi sẵn sàng."));
    for(const season of app.seasons){
      const card=el("article","season-card"),heading=el("div","tournament-card-heading");
      heading.append(el("h3","",season.name),el("span","tag",season.published_at?"Đã công bố":season.registration_open?"Đang đăng ký":season.registration_closed?"Đã chốt đăng ký":"Sắp mở đăng ký"));
      card.append(heading,el("p","form-note",`${season.game_id} · ${season.registered_teams} / ${season.max_teams} đội đăng ký`));
      const dates=el("dl","season-dates");
      for(const[key,title]of [["registration_opens_at","Mở đăng ký"],["registration_closes_at","Đóng đăng ký"],["starts_at","Bắt đầu thi đấu"],["ends_at","Kết thúc dự kiến"]]){
        const item=el("div");item.append(el("dt","",title),el("dd","",officialDateTime(season[key])));dates.append(item);
      }card.append(dates);
      const actions=el("div","form-buttons");
      const actionButton=(title,action,body={},primary=false)=>{
        const button=el("button",`button ${primary?"primary":"ghost"} small`,title);button.type="button";button.dataset.focusKey=season.id+"-"+action;
        button.onclick=async()=>{
          if(["publish","withdraw","close-registration"].includes(action) && !await confirmAction(title,action==="publish"?"Công bố nhà vô địch từ kết quả giải đã được xác minh. Kết quả công bố được lưu làm bản ghi chính thức.":"Thao tác áp dụng cho đăng ký của mùa giải này.",title))return;
          button.disabled=true;
          try{await api(`/api/${app.accountAudience}/seasons/${encodeURIComponent(season.id)}/${action}`,jsonOptions("POST",typeof body==="function"?body():body));
            if(action==="tournament")await refreshTeamTournaments();await refreshSeasons();toast("Đã cập nhật mùa thi đấu.");
          }catch(error){button.disabled=false;toast(error.message,true);}
        };actions.append(button);return button;
      };
      if(app.accountAudience==="player"){
        if(season.registration_open){
          const button=actionButton(season.my_registration?"Rút đăng ký":"Đăng ký đội",season.my_registration?"withdraw":"register",{},!season.my_registration);
          button.disabled=app.team?.my_role!=="CAPTAIN"||app.team?.team?.status!=="ACTIVE";
          if(button.disabled)button.title="Captain của Team ACTIVE thực hiện đăng ký.";
        }
        if(season.my_registration)card.append(el("p","form-note","Đội của bạn đã đăng ký mùa thi đấu này."));
      }else{
        const roster=el("button","button ghost small","Xem đội đăng ký");roster.type="button";
        roster.onclick=async()=>{
          roster.disabled=true;
          try{const data=await api(`/api/admin/seasons/${encodeURIComponent(season.id)}/entries`);const list=el("div","team-member-detail");
            if(!data.teams.length)list.append(el("p","form-note","Chưa có đội đăng ký."));
            for(const team of data.teams)list.append(el("p","form-note",`${team.display_name} · ${team.status} · ${team.member_count} thành viên`));card.append(list);
          }catch(error){roster.disabled=false;toast(error.message,true);}
        };actions.append(roster);
        if(!season.tournament_id){
          if(!season.registration_closed)actionButton("Đóng đăng ký","close-registration");
          else{
            const format=el("select");format.setAttribute("aria-label","Thể thức giải "+season.name);
            for(const[value,label]of [["round_robin","Vòng tròn"],["single_elimination","Loại trực tiếp"],["double_elimination","Nhánh thắng/thua"],["group_knockout","Vòng bảng + loại trực tiếp"],["swiss_single_elimination","Swiss + loại trực tiếp"]]){const option=el("option","",label);option.value=value;format.append(option);}
            actions.append(format);
            const button=actionButton("Chốt đội & tạo giải","tournament",()=>({format:format.value}),true);button.disabled=season.registered_teams<2;
          }
        }else if(!season.published_at){
          const button=actionButton("Xác nhận & công bố kết quả","publish");
          button.disabled=!app.teamTournaments.some(item=>item.id===season.tournament_id && item.status==="COMPLETED");
          button.title=button.disabled?"Hoàn tất và xác minh tất cả trận của giải trước khi công bố.":"Công bố kết quả giải đã xác minh";
        }
      }
      if(season.tournament_id){const link=el("a","button ghost small","Xem giải & bảng điểm ↗");link.href="#tournaments";actions.append(link);}
      if(actions.childElementCount)card.append(actions);
      if(season.publication){const result=el("div","season-publication");result.append(el("strong","",`Nhà vô địch: ${season.publication.champion.team_name_snapshot}`),el("p","form-note",`Công bố ${officialDateTime(season.published_at)}`));card.append(result);}
      target.append(card);
    }restore();
  }finally{app.seasonsBusy=false;}
}
$("#refresh-seasons").onclick=()=>refreshSeasons().catch(error=>toast(error.message,true));
$("#season-create").addEventListener("submit",async event=>{
  event.preventDefault();const form=event.currentTarget,button=form.querySelector("[type=submit]");busyButton(button,true);
  try{const payload={name:form.elements.name.value,game_id:form.elements.game_id.value,max_teams:Number(form.elements.max_teams.value)};
    for(const key of ["registration_opens_at","registration_closes_at","starts_at","ends_at"]){payload[key]=Math.floor(new Date(form.elements[key].value).getTime()/1000);if(!Number.isFinite(payload[key]))throw new Error("Chọn thời gian hợp lệ.");}
    await api("/api/admin/seasons",jsonOptions("POST",payload));feedback("#season-create-feedback","Đã tạo mùa giải. Captain có thể đăng ký trong thời hạn đã chọn.");await refreshSeasons();
  }catch(error){feedback("#season-create-feedback",error.message,true);}
  finally{busyButton(button,false);button.disabled=false;}
});

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
    if (!app.account) {
      $("#admin-player-recovery-token").value = "";
      $("#admin-player-recovery-result").classList.add("hidden");
      $("#admin-invite-token").value = "";
      $("#admin-invite-token-label").classList.add("hidden");
      $("#admin-accounts-body").replaceChildren();
      $("#admin-teams-list").replaceChildren();
    }
    $("#participant-name").textContent = app.account?.display_name || "Chưa đăng nhập";
    $("#participant-id").textContent = app.account
      ? `ACCOUNT / ${app.account.username} · ${app.account.system_role}`
      : "Account-Only · cần xác thực";
    $("#participant-role").textContent = app.account?.system_role || "SIGNED OUT";
    $(".avatar").href = "#profile";
    $(".avatar").setAttribute("aria-label", "Hồ sơ cá nhân");
    $("#session-form").classList.add("hidden");
    $("#organizer-toggle").textContent = app.logoutBusy ? "Đang đăng xuất…" : app.logoutError ? "Thử lại đăng xuất" : "Đăng xuất";
    $("#organizer-toggle").disabled = !app.account || app.logoutBusy;
    $("#organizer-toggle").title = app.logoutError ? "Chưa xác nhận thu hồi phiên trên server. Nhấn để thử lại." : "Thu hồi phiên tài khoản hiện tại";
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
  const accountPlayer = app.accountOnly && app.accountAudience === "player";
  $('.nav-item[data-view="scrimmage"]').classList.toggle("hidden", !app.accountOnly);
  $('.nav-item[data-view="profile"]').classList.toggle("hidden", !app.accountOnly);
  $('.nav-item[data-view="seasons"]').classList.toggle("hidden", !app.accountOnly);
  $("#season-admin-panel").classList.toggle("hidden", !app.accountOnly || app.accountAudience!=="admin");
  $$('.nav-item[data-view="administration"], .nav-item[data-view="system"]').forEach(node=>node.classList.toggle("hidden", !app.accountOnly || app.accountAudience!=="admin"));
  $("#scrimmage-create-panel").classList.toggle("hidden", !accountPlayer);
  setText("#scrimmage-nav-label", accountPlayer ? "Thách đấu" : "Hàng đợi Scrimmage");
  setText("#scrimmage-title", accountPlayer ? "Thách đấu" : "Hàng đợi Scrimmage");
  document.body.dataset.accountMode = app.accountOnly ? app.accountAudience || "signed-out" : "legacy";
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
    document.querySelectorAll(".player-only, [data-go=upload], .nav-item[data-view=upload], #quick-match, #create-match").forEach(node => node.classList.add("hidden"));
    if (accountPlayer) {
      document.querySelectorAll(".nav-item[data-view=upload], #view-upload .two-column, #view-upload .library-panel, #view-upload .upload-section-heading, [data-go=upload]").forEach(node => node.classList.remove("hidden"));
      $("#account-team-panel").classList.remove("hidden");
      $("#account-team-panel").closest(".view").classList.remove("hidden");
    } else {
      $("#account-team-panel").classList.add("hidden");
    }
    if (location.hash === "#create" || (!accountPlayer && location.hash === "#upload")) location.hash = "home";
    $$('.nav-item[data-view="official"], .nav-item[data-view="tournaments"], .nav-item[data-view="standings"]').forEach(node => node.classList.remove("hidden"));
  } else {
    $$('.nav-item[data-view="official"]').forEach(node => node.classList.add("hidden"));
  }
  $('.nav-item[data-view="create"]').classList.toggle("hidden", app.accountOnly);
  $$('[data-go="create"]').forEach(node => node.classList.toggle("hidden", app.accountOnly));
  $$('[data-go="official"]').forEach(node => node.classList.toggle("hidden", !app.accountOnly));
  $$('[data-go="watch"], .history-panel').forEach(node => node.classList.remove("hidden"));
  $$(".legacy-match-panel").forEach(node => node.classList.toggle("hidden", app.accountOnly || !organizer));
  setText("#standby-overlay > span:not(.standby-icon)", app.accountOnly
    ? "Chọn một trận trong lịch đấu để xem diễn biến hoặc replay."
    : "Trận sẽ bắt đầu khi hai Player chấp nhận lời mời.");
  $('.nav-item[data-view="watch"]').classList.remove("hidden");
  $(".docs-link").classList.toggle("hidden", app.accountOnly);
  $$("#rules-form [type=submit], #default-rules").forEach(node => node.classList.toggle("hidden", !organizer));
  if (organizer && location.hash === "#upload") location.hash = "create";
  $$("#quick-match [type=submit], #create-match [type=submit]").forEach(node => {
    node.disabled = !organizer || !app.competition?.competition_locked || app.launching || app.competitionBusy
      || (app.lobby?.players || []).filter(player => player.status === "READY").length < 2;
    node.title = node.disabled ? app.competition?.phase !== "open" ? "Cuộc thi cần được mở trước khi gửi lời mời" : "Cần hai Player đang online, có Active Bot và sẵn sàng" : "Hai Player sẽ tự xác nhận lời mời";
  });
  $("#upload-form [type=submit]").disabled = organizer || app.readOnly || app.uploading || !app.selectedGameId;
  $("#seed-samples").disabled = app.accountOnly || organizer || app.readOnly || app.seeding || !app.selectedGameId;
  $("#seed-samples").classList.toggle("hidden", app.accountOnly);
  document.querySelectorAll('[data-sample]').forEach(node => { node.disabled = app.accountOnly || organizer || app.readOnly || app.seeding || app.sampleBusy.has(`${node.dataset.gameId}:${node.dataset.sample}`); });
  $$(".game-select, .game-card").forEach(node => { node.title = allowed ? "Chọn game của cuộc thi" : app.competition?.competition_locked ? "Game đã khóa; đóng cuộc thi để cấu hình lại" : "Chỉ Organizer được chọn game"; });
  renderCompetitionBanner();
  renderWorkspaceOverview();
}

function renderCompetitionBanner() {
  const state = app.competition;
  setText("#competition-status", state?.phase === "open" ? "OPEN · Cuộc thi đang mở" : state?.phase === "draining" ? "DRAINING · Chờ trận kết thúc" : "SETUP · Đang chuẩn bị");
  $("#competition-banner").dataset.phase = state?.phase || "setup";
  $("#competition-banner").classList.toggle("competition-live", state?.competition_locked === true);
  setText("#competition-game", app.games.find(game => game.game_id === state?.selected_game_id)?.name || "Đang tải game…");
  const legacyMessage = state?.phase === "open" ? "Game và luật đã khóa. Organizer mời hai Player READY; trận bắt đầu sau hai lượt ACCEPT." : state?.phase === "draining" ? `Đã chặn trận mới. Đang chờ ${state.pending_matches} trận/bot kết thúc trước khi mở khóa cấu hình.` : "Ban tổ chức đang chuẩn bị game và luật. Có thể nộp bot cho game hiện tại; chưa thể tạo trận.";
  const accountMessage = state?.phase === "open" ? "Game và luật đã khóa. Captain chọn bot đại diện trước giờ khóa của từng trận." : state?.phase === "draining" ? `Đã chặn trận mới. Đang chờ ${state.pending_matches} tác vụ hiện có kết thúc trước khi mở khóa cấu hình.` : "Admin đang chuẩn bị game và luật. Team có thể nộp bot cho game hiện tại.";
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
  const socketAudience = app.accountAudience;
  const socket = new WebSocket(`${scheme}://${location.host}${socketPath}`);
  app.competitionSocket = socket;
  socket.onopen = () => {
    if (socket !== app.competitionSocket) return;
    if (app.accountOnly) app.competitionRetryMs = 5000;
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
    if (socket !== app.competitionSocket) return;
    app.lobbyOnline = false; renderConnection();
    clearInterval(app.heartbeatTimer);
    if (app.shuttingDown) return;
    if (app.accountOnly) {
      if (!app.account || socketAudience !== app.accountAudience) return;
      if ([1008, 4401].includes(event.code)) {
        accountExpired();
        return;
      }
      // A rejected handshake may close with 1006, never delivering 1008.
      // Verify the cookie against protected HTTP; a network outage is NOT logout.
      const stillCurrent = () => socket === app.competitionSocket &&
        !app.shuttingDown && !!app.account && app.accountAudience === socketAudience;
      const retry = () => {
        if (!stillCurrent()) return;
        // A failed WebSocket handshake also consumes the per-session limiter.
        // Exponential backoff avoids 429 loops when the socket is unavailable.
        const delay = Math.max(app.competitionRetryMs,
          Math.max(0, app.pollPauseUntil - Date.now()));
        app.competitionRetryMs = Math.min(30000, app.competitionRetryMs * 2);
        app.competitionTimer = setTimeout(connectCompetitionSocket, delay);
      };
      fetch(`/api/${socketAudience}/auth/me`, {
        headers: { "Accept": "application/json" }, cache: "no-store"
      }).then(response => {
        if (!stillCurrent()) return;
        if (response.status === 401 || response.status === 403) {
          accountExpired();
        } else {
          if (response.status === 429) {
            const retryAfter = Number(response.headers.get("Retry-After"));
            const seconds = Number.isFinite(retryAfter) && retryAfter > 0
              ? Math.min(120, Math.ceil(retryAfter)) : 60;
            app.pollPauseUntil = Math.max(app.pollPauseUntil,
              Date.now() + seconds * 1000);
          }
          retry();
        }
      }).catch(retry);
      return;
    }
    app.competitionTimer = setTimeout(connectCompetitionSocket, 1200);
  };

}

function acceptSession(data) {
  app.participant = data.participant; app.readOnly = data.read_only;
  app.role = data.role; app.organizerAvailable = data.organizer_available;
  renderSession();
  renderBots();
  renderInvitations();
}

// The public welcome screen is presentation-only. All protected APIs still
// require a verified Account-Only session and server-enforced role.
function showAccountLanding(message = "Chọn Đăng nhập hoặc Đăng ký để bắt đầu.") {
  closeWorkspaceNavigation({ returnFocus: false });
  if ($("#account-dialog").open) $("#account-dialog").close();
  document.body.classList.add("account-landing-active");
  $("#account-landing").classList.remove("hidden");
  $("#landing-login").disabled = false;
  $("#landing-register").disabled = !app.selfRegistration;
  $("#landing-register-note").textContent = app.selfRegistration
    ? "Tạo tài khoản Player để tham gia các giải đấu."
    : "Ban tổ chức hiện chưa mở đăng ký Player.";
  $("#landing-status").textContent = message;
  $("#landing-retry").classList.add("hidden");
}

function hideAccountLanding() {
  document.body.classList.remove("account-landing-active");
  $("#account-landing").classList.add("hidden");
}

function accountEntryTab(tab) {
  const registration = tab === "register" && app.selfRegistration;
  $("#account-login-form").classList.toggle("hidden", registration);
  $("#account-register-form").classList.toggle("hidden", !registration);
  $("#account-login-choice").classList.toggle("primary", !registration);
  $("#account-login-choice").classList.toggle("ghost", registration);
  $("#account-register-choice").classList.toggle("primary", registration);
  $("#account-register-choice").classList.toggle("ghost", !registration);
  $("#account-title").textContent = registration ? "Đăng ký Player" : "Đăng nhập NEON ARENA";
  const first = registration ? $("#account-register-form [name=username]") : $("#account-username");
  first.focus();
}

function showAccountDialog(message = "Đăng nhập để tiếp tục vào workspace.", tab = "login") {
  const dialog = $("#account-dialog");
  $("#account-feedback").textContent = message;
  $("#account-feedback").classList.remove("hidden", "error");
  if (!dialog.open) dialog.showModal();
  $("#account-register-choice").classList.toggle("hidden", !app.selfRegistration);
  $("#account-email-tools").classList.toggle("hidden", !app.emailVerification);
  $("#account-password-tools").classList.toggle("hidden", !(app.emailVerification || app.usernameOnlySignup));
  $("#account-request-reset-form").classList.toggle("hidden", !app.emailVerification);
  $("#account-register-name-field").classList.toggle("hidden", !app.emailVerification);
  $("#account-register-email-field").classList.toggle("hidden", !app.emailVerification);
  $("#account-register-form [name=display_name]").required = app.emailVerification;
  $("#account-register-form [name=email]").required = app.emailVerification;
  $("#account-register-note").textContent = app.emailVerification
    ? "Đăng ký chỉ tạo tài khoản Player. Phải xác minh email trước khi đăng nhập."
    : "Đăng ký chỉ tạo tài khoản Player. Nếu quên mật khẩu, liên hệ Admin để nhận mã khôi phục.";
  $("#account-recovery-note").textContent = app.emailVerification
    ? "Có thể nhận email khôi phục, hoặc nhờ Admin cấp mã một lần."
    : "Liên hệ Admin để nhận mã khôi phục dùng một lần, có hạn 30 phút.";
  accountEntryTab(tab);
  if (app.resetTokenLoaded) {
    $("#account-password-tools").open = true;
    $("#account-reset-password-form [name=password]").focus();
    app.resetTokenLoaded = false;
  }
}

function acceptAccount(data, audience) {
  $("#admin-player-recovery-token").value = "";
  $("#admin-player-recovery-result").classList.add("hidden");
  $("#admin-invite-token").value = "";
  $("#admin-invite-token-label").classList.add("hidden");
  app.logoutError = false;
  app.account = data.account;
  app.pollPauseUntil = 0;
  clearTimeout(app.bootstrapTimer); app.bootstrapTimer = null;
  app.competitionRetryMs = 5000;
  app.accountAudience = audience;
  app.csrf = null;
  app.role = data.account.system_role === "ADMIN" ? "organizer" : "player";
  app.participant = { id: data.account.id, name: data.account.display_name };
  app.organizerAvailable = app.role === "organizer";
  if ($("#account-dialog").open) $("#account-dialog").close();
  hideAccountLanding();
  renderSession();
}

$("#account-dialog").addEventListener("cancel", event => {
  if (!app.accountOnly || app.account) event.preventDefault();
});
$("#account-back").addEventListener("click", () => {
  $("#account-dialog").close();
  $("#landing-login").focus();
});
$("#landing-login").addEventListener("click", () => showAccountDialog(undefined, "login"));
$("#landing-register").addEventListener("click", () => {
  if (app.selfRegistration) showAccountDialog(undefined, "register");
});
$("#landing-retry").addEventListener("click", () => bootstrap());
$("#account-login-choice").addEventListener("click", () => accountEntryTab("login"));
$("#account-register-choice").addEventListener("click", () => accountEntryTab("register"));

function accountExpired() {
  if (!app.accountOnly || !app.account) return;
  $("#admin-player-recovery-token").value = "";
  $("#admin-player-recovery-result").classList.add("hidden");
  app.account = null; app.participant = null; app.accountAudience = null; app.csrf = null;
  app.pollPauseUntil = 0;
  clearTimeout(app.bootstrapTimer); app.bootstrapTimer = null;
  app.generation++; clearTimeout(app.reconnectTimer);
  app.role = "player"; app.organizerAvailable = false; app.initialized = false;
  app.competitionSocket?.close(); app.socket?.close();
  clearTimeout(app.competitionTimer); clearTimeout(app.reconnectTimer);
  renderSession();
  showAccountLanding("Phiên đã hết hạn hoặc bị thu hồi. Hãy đăng nhập lại.");
}

async function restoreAccount() {
  for (const audience of ["admin", "player"]) {
    const response = await fetch(`/api/${audience}/auth/me`, { headers: { "Accept": "application/json" } });
    if (response.status === 429) {
      // Restore is a direct fetch, not api(); still honor a limited session.
      const retryAfter = Number(response.headers.get("Retry-After"));
      const seconds = Number.isFinite(retryAfter) && retryAfter > 0
        ? Math.min(120, Math.ceil(retryAfter)) : 60;
      app.pollPauseUntil = Math.max(app.pollPauseUntil, Date.now() + seconds * 1000);
      throw Object.assign(new Error("Authentication temporarily rate-limited"), { status: 429 });
    }
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
  const button = form.querySelector("[type=submit]");
  busyButton(button, true);
  try {
    const data = await api("/api/account/auth/login", jsonOptions("POST", {
      username: form.elements.username.value, password: form.elements.password.value,
      ...(form.elements.otp.value ? { otp: form.elements.otp.value } : {})
    }));
    form.elements.password.value = ""; form.elements.otp.value = "";
    acceptAccount(data, data.audience);
    app.initialized = false;
    await bootstrap();
  } catch (error) {
    feedback("#account-feedback", error.message, true);
  } finally { busyButton(button, false); button.disabled = false; }
});

$("#account-register-form").addEventListener("submit", async event => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("[type=submit]");
  if (form.elements.password.value !== form.elements.confirm_password.value) {
    feedback("#account-feedback", "Hai mật khẩu chưa trùng nhau.", true);
    return;
  }
  busyButton(button, true);
  try {
    if (!app.selfRegistration) throw new Error("Đăng ký hiện chưa được mở.");
    const registered = await api("/api/account/auth/register", jsonOptions("POST", {
      username: form.elements.username.value,
      ...(app.emailVerification ? {
        display_name: form.elements.display_name.value,
        email: form.elements.email.value
      } : {}),
      password: form.elements.password.value
    }));
    const username = form.elements.username.value;
    form.reset();
    accountEntryTab("login");
    $("#account-username").value = username;
    feedback("#account-feedback", registered.registration_pending
      ? "Đã nhận yêu cầu. Kiểm tra email, mở liên kết xác minh rồi mới đăng nhập."
      : "Tạo tài khoản Player thành công. Hãy đăng nhập để tiếp tục.");
  } catch (error) {
    feedback("#account-feedback", error.message, true);
  } finally { busyButton(button, false); button.disabled = false; }
});

$("#account-request-reset-form").addEventListener("submit", async event => {
  event.preventDefault();
  const form = event.currentTarget, button = form.querySelector("[type=submit]");
  busyButton(button, true);
  try {
    await api("/api/account/auth/request-reset", jsonOptions("POST", {
      username: form.elements.username.value, email: form.elements.email.value
    }));
    feedback("#account-feedback", "Nếu tài khoản đủ điều kiện, email khôi phục đã được gửi.");
  } catch (error) { feedback("#account-feedback", error.message, true); }
  finally { busyButton(button, false); button.disabled = false; }
});

$("#account-reset-password-form").addEventListener("submit", async event => {
  event.preventDefault();
  const form = event.currentTarget, button = form.querySelector("[type=submit]");
  if (form.elements.password.value !== form.elements.confirm_password.value) {
    feedback("#account-feedback", "Hai mật khẩu chưa trùng nhau.", true);
    return;
  }
  busyButton(button, true);
  try {
    await api("/api/account/auth/reset-password", jsonOptions("POST", {
      token: form.elements.token.value, password: form.elements.password.value
    }));
    form.reset();
    $("#account-password-tools").open = false;
    feedback("#account-feedback", "Đã đổi mật khẩu và thu hồi phiên cũ. Hãy đăng nhập lại.");
  } catch (error) { feedback("#account-feedback", error.message, true); }
  finally { busyButton(button, false); button.disabled = false; }
});

$("#account-email-form").addEventListener("submit", async event => {
  event.preventDefault();
  const form = event.currentTarget, button = form.querySelector("[type=submit]");
  busyButton(button, true);
  try {
    await api("/api/account/auth/verify-email", jsonOptions("POST", {
      token: form.elements.token.value
    }));
    form.reset();
    feedback("#account-feedback", "Xác minh email thành công. Bạn có thể đăng nhập.");
  } catch (error) { feedback("#account-feedback", error.message, true); }
  finally { busyButton(button, false); button.disabled = false; }
});

$("#account-resend-form").addEventListener("submit", async event => {
  event.preventDefault();
  const form = event.currentTarget, button = form.querySelector("[type=submit]");
  busyButton(button, true);
  try {
    await api("/api/account/auth/resend-verification", jsonOptions("POST", {
      username: form.elements.username.value, email: form.elements.email.value
    }));
    feedback("#account-feedback", "Nếu tài khoản cần xác minh, email mới sẽ được gửi.");
  } catch (error) { feedback("#account-feedback", error.message, true); }
  finally { busyButton(button, false); button.disabled = false; }
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
  if (!app.accountAudience || app.logoutBusy) return;
  const audience = app.accountAudience;
  app.logoutBusy = true; app.logoutError = false; renderSession();
  try {
    const result = await api(`/api/${audience}/auth/logout`, jsonOptions("POST", {}));
    if (result.logged_out !== true) throw new Error("Server chưa xác nhận thu hồi phiên.");
  } catch (error) {
    if (error.status === 401) {
      accountExpired();
    } else {
      // Keep the account and retry action: a lost response does not prove that
      // the server revoked the session or removed the browser cookie.
      app.logoutError = true;
      toast(`Chưa xác nhận đăng xuất. ${error.message} Nhấn “Thử lại đăng xuất”.`, true);
    }
    return;
  } finally {
    app.logoutBusy = false; renderSession();
  }
  // A successfully revoked account must cancel any pending startup retry.
  clearTimeout(app.bootstrapTimer); app.bootstrapTimer = null;
  app.pollPauseUntil = 0;
  app.account = null; app.participant = null; app.accountAudience = null; app.csrf = null;
  app.role = "player"; app.organizerAvailable = false; app.initialized = false;
  app.competitionSocket?.close(); app.socket?.close();
  clearTimeout(app.competitionTimer); clearTimeout(app.reconnectTimer);
  renderSession();
  showAccountLanding("Đã đăng xuất an toàn. Bạn có thể đăng nhập lại.");
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

const labels = {
  home: "Tổng quan",
  standings: "Bảng xếp hạng",
  upload: "Team & Bot",
  create: "Phòng thi đấu",
  tournaments: "Giải đấu",
  watch: "Lịch sử & Replay",
  official: "Official Match",
  scrimmage: "Thách đấu",
  profile: "Hồ sơ cá nhân",
  administration: "Tài khoản & đội",
  system: "Giám sát hệ thống",
  seasons: "Mùa thi đấu",
  rules: "Game & Luật chơi",
};

// One navigation tree on every viewport. This only manages presentation/focus;
// the existing router and server remain responsible for access and permissions.
const navigationViewport = window.matchMedia("(max-width: 1023px)");
const workspaceNavigation = $("#workspace-navigation");
const navigationToggle = $("#nav-toggle");
const navigationBackdrop = $("#nav-backdrop");

function closeWorkspaceNavigation({ returnFocus = true } = {}) {
  const wasOpen = document.body.dataset.navigation === "open";
  delete document.body.dataset.navigation;
  navigationBackdrop.hidden = true;
  navigationToggle.setAttribute("aria-expanded", "false");
  $(".shell").inert = false;
  $(".skip-link").inert = false;
  workspaceNavigation.removeAttribute("role");
  workspaceNavigation.removeAttribute("aria-modal");
  workspaceNavigation.inert = navigationViewport.matches;
  if (wasOpen && returnFocus && navigationToggle.getClientRects().length) navigationToggle.focus();
}

function openWorkspaceNavigation() {
  if (!navigationViewport.matches || document.body.classList.contains("account-landing-active")) return;
  document.body.dataset.navigation = "open";
  workspaceNavigation.inert = false;
  workspaceNavigation.setAttribute("role", "dialog");
  workspaceNavigation.setAttribute("aria-modal", "true");
  navigationBackdrop.hidden = false;
  navigationToggle.setAttribute("aria-expanded", "true");
  $(".shell").inert = true;
  $(".skip-link").inert = true;
  requestAnimationFrame(() => {
    if (document.body.dataset.navigation === "open") $("#nav-close").focus();
  });
}

navigationToggle.addEventListener("click", openWorkspaceNavigation);
$("#nav-close").addEventListener("click", () => closeWorkspaceNavigation());
navigationBackdrop.addEventListener("click", () => closeWorkspaceNavigation());
workspaceNavigation.addEventListener("click", event => {
  if (event.target.closest("a[href]") && navigationViewport.matches) closeWorkspaceNavigation();
});
navigationViewport.addEventListener("change", () => {
  const focusedNavigation = workspaceNavigation.contains(document.activeElement);
  closeWorkspaceNavigation({ returnFocus: false });
  if (focusedNavigation) {
    if (navigationViewport.matches) navigationToggle.focus();
    else workspaceNavigation.querySelector(".nav-item.active:not(.hidden)")?.focus();
  }
});
document.addEventListener("keydown", event => {
  if (document.body.dataset.navigation !== "open") return;
  if (event.key === "Escape") {
    event.preventDefault();
    event.stopPropagation();
    closeWorkspaceNavigation();
  } else if (event.key === "Tab") {
    const controls = [...workspaceNavigation.querySelectorAll('a[href], button:not(:disabled), [tabindex="0"]')]
      .filter(node => node.getClientRects().length && !node.closest(".hidden, [hidden]"));
    const first = controls[0], last = controls.at(-1);
    if (event.shiftKey && (document.activeElement === first || !workspaceNavigation.contains(document.activeElement))) {
      event.preventDefault(); last?.focus();
    } else if (!event.shiftKey && (document.activeElement === last || !workspaceNavigation.contains(document.activeElement))) {
      event.preventDefault(); first?.focus();
    }
  }
}, true);
closeWorkspaceNavigation({ returnFocus: false });

function navigate() {
  closeWorkspaceNavigation({ returnFocus: false });
  let view = location.hash.slice(1) || "home";
  if (!labels[view] || (["official", "scrimmage"].includes(view) && !app.accountOnly)) view = "home";
  if (["profile","administration","system","seasons"].includes(view) && !app.accountOnly) view="home";
  if (["administration","system"].includes(view) && app.accountAudience!=="admin") view="home";
  $$(".view").forEach(node => node.classList.toggle("active", node.id === `view-${view}`));
  $$(".nav-item").forEach(node => node.classList.toggle("active", node.dataset.view === view));
  $("#page-label").textContent = labels[view];
  document.body.dataset.view = view;
  $$(".nav-item[data-view]").forEach(node => node.setAttribute("aria-current", node.dataset.view === view ? "page" : "false"));
  document.title = `${labels[view]} · NEON ARENA`;
  window.scrollTo({ top: 0, behavior: "instant" });
  if (app.initialized && app.accountOnly && ["scrimmage", "watch"].includes(view)) refreshScrimmages().catch(error => toast(error.message, true));
  if (app.account && view==="profile") {
    $("#profile-username").value=app.account.username;
    $("#profile-display-name").value=app.account.display_name;
    setText("#profile-role",app.account.system_role);
  }
  if (app.initialized && view==="administration") refreshAdministration().catch(error=>toast(error.message,true));
  if (app.initialized && view==="system") refreshSystem().catch(error=>feedback("#system-feedback",error.message,true));
  if (app.initialized && view==="seasons") refreshSeasons().catch(error=>toast(error.message,true));
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
  const matches = app.accountOnly ? app.officialMatches : app.matches;
  $("#stat-matches").textContent = String(matches.filter(m => ["completed", "COMPLETED"].includes(m.status)).length).padStart(2, "0");
  const running = matches.filter(m => ["running", "queued", "RUNNING", "QUEUED"].includes(m.status)).length;
  $("#stat-live").textContent = String(running).padStart(2, "0");
  $("#live-note").textContent = running ? "Đang cập nhật trực tiếp" : "Chờ trận đấu tiếp theo";
  renderWorkspaceOverview();
}

function renderWorkspaceOverview() {
  const root = $("#workspace-overview");
  root.classList.toggle("hidden", !app.accountOnly);
  if (!app.accountOnly) return;
  const admin = app.accountAudience === "admin";
  setText("#overview-title", admin ? "Điều hành cuộc thi" : "Chuẩn bị cho trận đấu tiếp theo");
  setText("#overview-role", admin ? "Admin" : app.team?.my_role === "CAPTAIN" ? "Captain" : "Player");
  setText("#view-home .hero h1", admin ? "Tổng quan cuộc thi" : "Không gian của bạn");
  setText("#view-home .hero p", admin ? "Cấu hình cuộc thi, lên lịch và theo dõi kết quả trong một không gian." : "Quản lý đội, chuẩn bị bot và theo dõi lịch thi đấu của bạn.");
  const steps = admin ? [
    ["rules", "01", "Chốt game & luật", app.competition?.competition_locked ? "Luật đã khóa cho cuộc thi." : "Kiểm tra cấu hình trước khi mở cuộc thi."],
    ["tournaments", "02", "Tổ chức giải đấu", `${app.teamTournaments.length} giải · ${app.officialTeams.length} đội đang hoạt động.`],
    ["official", "03", "Lên lịch thi đấu", "Chọn đội, hạn khóa bot và giờ bắt đầu."]
  ] : [
    ["upload", "01", app.team?.team ? app.team.team.display_name : "Tạo hoặc tham gia đội", app.team?.team ? `${app.team.team.member_count} thành viên · ${app.team.team.status}` : "Bắt đầu với một đội và các đồng đội của bạn."],
    ["upload", "02", app.activeTeamBot?.bot?.name || "Chuẩn bị bot đại diện", app.activeTeamBot?.bot ? "Active Bot đã chọn cho game hiện tại." : "Nộp code, kiểm tra biên dịch và chọn Active Bot."],
    ["official", "03", "Theo dõi trận đấu", "Xem lịch, kết quả và replay của đội bạn."]
  ];
  // Keep links stable during background refresh so keyboard focus is retained.
  const target = $("#overview-steps");
  if (!target.childElementCount) for (let i = 0; i < 3; i++) {
    const link = el("a", "overview-step");
    link.append(el("span", "overview-number"), el("h3"), el("p"), el("span", "overview-arrow", "↗"));
    link.lastChild.setAttribute("aria-hidden", "true");
    target.append(link);
  }
  steps.forEach(([view, number, title, note], i) => {
    const link = target.children[i];
    link.href = `#${view}`;
    for (const [selector, value] of [[".overview-number", number], ["h3", title], ["p", note]]) {
      if (link.querySelector(selector).textContent !== value) link.querySelector(selector).textContent = value;
    }
  });
  const next = [...app.officialMatches].filter(item => ["SCHEDULED", "LOCKED", "QUEUED", "RUNNING", "BLOCKED"].includes(item.status))
    .sort((a, b) => a.scheduled_at - b.scheduled_at)[0];
  setText("#overview-next-title", next ? `${next.game_id} · ${officialDateTime(next.scheduled_at)}` : "Chưa có lịch thi đấu sắp tới");
  setText("#overview-next-note", next ? `Trạng thái: ${next.status} · Khóa bot: ${officialDateTime(next.bot_lock_at)}` : admin ? "Tạo một lịch đấu hoặc xếp lịch từ giải đấu đã bắt đầu." : "Lịch mới sẽ xuất hiện khi Admin xếp trận cho đội của bạn.");
}

function renderPracticeRows(target, requests, completedOnly = false) {
  const restore = preserveListState(target);
  target.replaceChildren();
  const visible = completedOnly ? requests.filter(item => ["COMPLETED","INTERRUPTED","CANCELLED"].includes(item.status)) : requests;
  if (!visible.length) target.append(el("div", "empty-state", completedOnly ? "Chưa có trận thử hoàn tất. Gửi thách đấu hoặc xem lịch đấu chính thức để bắt đầu." : "Chưa có trận thử nào. Hai đội cần Active Bot sẵn sàng cho cùng một game."));
  const names = {QUEUED:"Đang chờ",DISPATCHING:"Đang chuẩn bị",RUNNING:"Đang thi đấu",COMPLETED:"Hoàn tất",INTERRUPTED:"Gián đoạn",CANCELLED:"Đã hủy"};
  for (const item of visible) {
    const row = el("article", "official-match-row"), copy = el("div", "official-match-copy");
    copy.append(el("strong", "", `${item.teams.A.team_name_snapshot} vs ${item.teams.B.team_name_snapshot}`),
      el("p", "form-note", `${item.game_id} · ${new Date(item.created_at*1000).toLocaleString("vi-VN")}`),
      el("span", "tag", names[item.status] || item.status));
    if (item.result) copy.append(el("p", "form-note", `Kết quả: ${item.result.winner ? item.teams[item.result.winner].team_name_snapshot + " thắng" : "Hòa"} · ${item.result.reason}`));
    if (item.status_reason) copy.append(el("p", "form-note", `Lý do: ${item.status_reason}`));
    row.append(copy);
    if (item.match_id && ["RUNNING","COMPLETED","INTERRUPTED"].includes(item.status)) {
      const watch = el("button", "button ghost small", "Xem Live / Replay ↗"); watch.type = "button";
      watch.dataset.focusKey = item.id + "-watch";
      watch.onclick = () => loadMatch(item.id, false, true).catch(error => toast(error.message,true));
      row.append(watch);
      if (item.game_id === "battlecode26" && item.status === "COMPLETED") {
        const raw = el("a", "button ghost small", "Tải .bc26");
        raw.href = `/api/${app.accountAudience}/scrimmages/${encodeURIComponent(item.id)}/replay.bc26`;
        raw.setAttribute("download", ""); raw.dataset.focusKey = item.id + "-raw"; row.append(raw);
      }
    }
    if (item.status === "QUEUED" && (app.accountAudience === "admin" || item.teams.A.team_id === app.team?.team?.id)) {
      const cancel = el("button", "button ghost small", "Hủy yêu cầu"); cancel.type = "button";
      cancel.dataset.focusKey = item.id + "-cancel";
      cancel.onclick = async () => {
        if (!await confirmAction("Hủy trận thử?", "Yêu cầu sẽ được gỡ khỏi hàng đợi trước khi chạy.", "Hủy trận thử")) return;
        cancel.disabled = true;
        try { await api(`/api/${app.accountAudience}/scrimmages/${encodeURIComponent(item.id)}/cancel`,jsonOptions("POST",{})); await refreshScrimmages(); }
        catch(error) { cancel.disabled = false; toast(error.message,true); }
      };
      row.append(cancel);
    }
    target.append(row);
  }
  restore();
}

async function refreshPracticeOpponents() {
  if (!app.accountOnly || app.accountAudience !== "player") return;
  const account = app.account, teamId = app.team?.team?.id;
  const game = $("#scrimmage-game").value;
  const ready = app.team?.team?.status === "ACTIVE";
  const select = $("#scrimmage-opponent"), button = $("#scrimmage-create [type=submit]");
  button.disabled = true;
  select.replaceChildren();
  if (!ready || !game) {
    setText("#scrimmage-eligibility", "Tạo hoặc tham gia Team, kích hoạt Team và chọn Active Bot trước khi thách đấu.");
    return;
  }
  const response = await api(`/api/player/scrimmage-opponents?game_id=${encodeURIComponent(game)}`);
  if (app.account !== account || app.accountAudience !== "player" || app.team?.team?.id !== teamId || game !== $("#scrimmage-game").value) return;
  for (const team of response.teams) {
    const option = el("option", "", `${team.display_name} · ${team.bot_name}`); option.value = team.id; select.append(option);
  }
  button.disabled = !response.teams.length || app.runnerMode !== "sandbox";
  setText("#scrimmage-eligibility", app.runnerMode !== "sandbox" ? "Máy chủ này đang ở chế độ native. Scrimmage tự động cần Docker Sandbox." : response.teams.length ? "Bot của hai đội sẽ được chốt ngay khi gửi. Tối đa 3 yêu cầu đang chờ cho đội của bạn." : "Chưa có đội đối thủ với Active Bot hợp lệ cho game này.");
}

async function refreshScrimmages() {
  if (!app.accountOnly || !app.account || app.practiceRefreshing) return;
  const account = app.account, audience = app.accountAudience;
  app.practiceRefreshing = true;
  try {
    const response = await api(`/api/${audience}/scrimmages`);
    if (app.account !== account || app.accountAudience !== audience) return;
    app.scrimmages = response.requests;
    renderPracticeRows($("#scrimmage-list"), app.scrimmages);
    if (audience === "player") renderMatches();
    const game = $("#scrimmage-game"), previous = game.value;
    if (!game.childElementCount) {
      for (const item of app.games) { const option=el("option","",item.name); option.value=item.game_id; game.append(option); }
      game.value = previous || app.selectedGameId;
    }
    if (document.body.dataset.view === "scrimmage") await refreshPracticeOpponents();
  } finally { app.practiceRefreshing = false; }
}
$("#scrimmage-game").addEventListener("change", () => refreshPracticeOpponents().catch(error=>feedback("#scrimmage-feedback",error.message,true)));
$("#refresh-scrimmages").addEventListener("click",()=>refreshScrimmages().catch(error=>toast(error.message,true)));
$("#scrimmage-create").addEventListener("submit", async event => {
  event.preventDefault();
  const form=event.currentTarget, button=form.querySelector("[type=submit]"); busyButton(button,true);
  try {
    await api("/api/player/scrimmages",jsonOptions("POST",{game_id:form.elements.game_id.value,opponent_team_id:form.elements.opponent_team_id.value}));
    feedback("#scrimmage-feedback","Đã vào hàng đợi. Bạn có thể rời trang; máy chủ sẽ tự chạy trận.");
    await refreshScrimmages();
  } catch(error) { feedback("#scrimmage-feedback",error.message,true); }
  finally { busyButton(button,false); await refreshPracticeOpponents().catch(()=>{}); }
});
setInterval(() => {
  if (!document.hidden && app.accountOnly && app.account && app.initialized && !app.practiceRefreshing
      && Date.now() >= app.pollPauseUntil && ["scrimmage","watch"].includes(document.body.dataset.view))
    refreshScrimmages().catch(error=>{if(error.transport)setConnection(false);});
}, 10000);

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
  if (app.accountOnly && app.accountAudience === "player") {
    renderAccountBotLibrary();
    return;
  }
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
  updateUploadProtocol();
}

function updateUploadProtocol() {
  const battlecode = app.selectedGameId === "battlecode26";
  $("#bot-file").accept = battlecode ? ".py,.java" : ".py,.cpp,.java";
  setText("#file-help", battlecode ? ".py · .java — một file, tối đa 256 KiB" : ".py · .cpp · .java — tối đa 256 KiB");
  $("#upload-protocol-note").innerHTML = battlecode
    ? 'Python: hàm <code>turn()</code> không có tham số, dùng <code>rc</code>. Java 21: <code>package arena;</code> và <code>public class RobotPlayer</code> với <code>public static void run(RobotController rc)</code>. Nộp một file; engine chính thức điều khiển trận đấu.'
    : 'Java dùng <code>public class Main</code>, không có package. Trả một dòng JSON trên <code>stdout</code> và flush; ghi debug vào <code>stderr</code>.';
  const link = $("#upload-protocol-link");
  link.href = battlecode ? "https://github.com/battlecode/battlecode26/tree/103abf6b67a2cf544e6344dddef9318af9ae9193" : "/static/protocol.html";
  link.textContent = battlecode ? "Xem API Battlecode và ví dụ ↗" : "Đọc giao thức bot ↗";
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
  const modeLabel = game.turn_mode === "official_engine" ? "ENGINE CHÍNH THỨC" : game.turn_mode === "simultaneous" ? "ĐỒNG THỜI" : "LUÂN PHIÊN";
  $("#workspace-game-name").textContent = `${game.name} / ${modeLabel}`;
  $("#game-name").textContent = game.name;
  $("#hero-game-label").textContent = game.name;
  $("#game-description").textContent = game.description;
  $("#rules-heading").textContent = `${game.name} · Cấu hình luật`;
  $("#create-game-label").textContent = game.badge || game.name;
  $("#match-mode-hint").textContent = game.turn_mode === "official_engine" ? "Engine Battlecode chính thức điều khiển toàn bộ trận trong Docker Sandbox." : game.turn_mode === "simultaneous" ? "Hai bot nhận cùng trạng thái và hành động đồng thời." : "Hai bot đi luân phiên. Server chỉ hỏi bot đến lượt.";
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
    copy.append(el("h2", "", installed.name), el("p", "", installed.description), el("small", "", `Đã cài đặt · v${installed.version} · ${installed.turn_mode === "official_engine" ? "Engine chính thức" : installed.turn_mode === "simultaneous" ? "Đồng thời" : "Luân phiên"}`));
    button.append(el("span", "game-card-icon", installed.name.slice(0, 2).toUpperCase()), copy);
    button.addEventListener("click", () => selectGame(installed.game_id));
    return button;
  }));
  const faultGuide = game.turn_mode === "official_engine"
    ? "Lỗi và giới hạn của bot do engine Battlecode xử lý. Nếu hạ tầng bị gián đoạn, trận được đánh dấu INTERRUPTED để Admin kiểm tra."
    : "Timeout, crash, JSON hoặc action không hợp lệ: bot bị xử thua. Game state chỉ do server cập nhật.";
  $("#rules-guide").replaceChildren(...[...(game.guide || []), { title: "BOT FAULT", description: faultGuide }].map((item, index) => {
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
  $("#action-examples").closest(".protocol-preview").classList.toggle("hidden", !game.action_examples?.length);
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
    const corrections = match.result_corrections || [];
    if (corrections.length) {
      const history = el("details", "match-correction-history");
      history.append(el("summary", "match-date", `Lịch sử điều chỉnh (${corrections.length})`));
      for (const correction of corrections) {
        const oldResult = correction.previous_result?.winner || "Hòa";
        const newResult = correction.new_result?.winner || "Hòa";
        history.append(el("small", "match-date",
          `${correction.corrected_at ? new Date(correction.corrected_at).toLocaleString("vi-VN") : ""} · ${correction.actor?.name || "Organizer"}: ${oldResult} → ${newResult} · ${correction.reason}`));
      }
      names.append(history);
    }
    row.append(names, statusBadge(match.status), el("span", "match-result", resultDescription(match)));
    const actions = el("div", "match-actions");
    const button = el("button", "button ghost match-view-button", ["running", "queued"].includes(match.status) ? "Live ↗" : "Replay ↗");
    button.dataset.focusKey = `match-${match.id}`;
    button.setAttribute("aria-label", `${["running", "queued"].includes(match.status) ? "Xem trực tiếp" : "Xem replay"} trận ${match.id}`);
    button.addEventListener("click", () => loadMatch(match.id).catch(error => toast(error.message, true)));
    actions.append(button);
    if (app.role === "organizer" && match.status === "completed" && match.result_correctable !== false
        && !match.tournament_id && !match.tournament_match_id && !match.official_request_id) {
      const correct = el("button", "button ghost match-correct-button", "Sửa kết quả");
      correct.dataset.focusKey = `correct-${match.id}`;
      correct.addEventListener("click", () => correctMatchResult(match).catch(error => toast(error.message, true)));
      actions.append(correct);
    }
    row.append(actions);
    target.append(row);
  });
  restore();
}

async function correctMatchResult(match) {
  const selection = window.prompt(
    `Kết quả mới cho ${fighterLabel(match, "A")} vs ${fighterLabel(match, "B")}? Nhập A, B hoặc H để hòa.`,
    match.result?.winner || "A",
  );
  if (selection === null) return;
  const choice = selection.trim().toUpperCase();
  const winner = choice === "H" || choice === "DRAW" ? "DRAW" : choice;
  if (!["A", "B", "DRAW"].includes(winner)) throw new Error("Nhập A, B hoặc H (hòa).");
  const reason = window.prompt("Lý do điều chỉnh (ít nhất 5 ký tự):");
  if (reason === null) return;
  const matchPath = `/api/matches/${encodeURIComponent(match.id)}/correct-result`;
  const updated = await api(matchPath, jsonOptions("POST", { winner, reason }));
  app.matches = app.matches.map(item => item.id === updated.id ? updated : item);
  await refreshStandings();
  renderMatches();
  toast("Đã điều chỉnh kết quả và lưu vào lịch sử.");
}

function renderMatches() {
  if (app.accountOnly && app.accountAudience === "player") {
    renderPracticeRows($("#all-matches"), app.scrimmages, true);
    renderPracticeRows($("#recent-matches"), app.scrimmages.slice(0,4), true);
    setText("#history-count", `${app.scrimmages.length} trận thử`);
    renderStats();
    return;
  }
  renderMatchList($("#recent-matches"), app.matches.slice(0, 4));
  renderMatchList($("#all-matches"), app.matches);
  $("#history-count").textContent = `${app.matches.length} trận`;
  renderStats();
}

function renderStandings() {
  const tbody = $("#standings-body");
  tbody.replaceChildren();
  if (app.accountOnly) {
    setText("#view-standings .page-intro p", "Bảng điểm theo từng giải đấu. Kết quả được giữ riêng theo game và thể thức.");
    const headers = $$(".standings-table th");
    ["Hạng", "Đội", "Đã đấu", "Thắng", "Hòa", "Thua", "Điểm", "Giải đấu"].forEach((text, i) => { headers[i].textContent = text; });
    const tournaments = app.teamTournaments.filter(t => !app.standingsGameId || t.game_id === app.standingsGameId);
    for (const tournament of tournaments) {
      const sections = tournament.groups?.length ? tournament.groups.map(group => [group.name, group.standings]) : [[tournament.name, tournament.standings]];
      for (const [name, standings] of sections) {
        if (!standings?.length) continue;
        const group = el("tr", "standings-section"), heading = el("th", "", `${tournament.name}${name !== tournament.name ? " · " + name : ""}`);
        heading.colSpan = 8; heading.scope = "colgroup"; group.append(heading); tbody.append(group);
        standings.forEach(item => {
          const row = el("tr");
          [item.rank, item.team_name, item.played, item.wins, item.draws, item.losses, item.points].forEach(value => row.append(el("td", "", String(value ?? "—"))));
          const cell = el("td"), link = el("a", "standings-link", "Xem giải ↗");
          link.href = "#tournaments"; cell.append(link); row.append(cell); tbody.append(row);
        });
      }
    }
    if (!tbody.childElementCount) {
      const row = el("tr"), cell = el("td", "empty-state"); cell.colSpan = 8;
      cell.append(el("p", "", "Chưa có bảng điểm cho game này. Giải loại trực tiếp được theo dõi theo nhánh đấu."));
      const link = el("a", "text-button", "Xem các giải đấu ↗"); link.href = "#tournaments";
      cell.append(link); row.append(cell); tbody.append(row);
    }
    return;
  }

  if (!app.standings.length) {
    const row = el("tr");
    const cell = el("td", "empty-state", "Game này chưa có kết quả trận đấu tự do.");
    cell.colSpan = 8;
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

    row.append(el("td", "standing-win-rate", `${Number(player.win_rate || 0).toFixed(1)}%`));
    const formCell = el("td", "standing-form");
    const formLabels = { W: ["T", "Thắng"], D: ["H", "Hòa"], L: ["B", "Thua"] };
    for (const result of player.form || []) {
      const [label, title] = formLabels[result] || ["—", "Không rõ"];
      const mark = el("span", `form-mark ${result.toLowerCase()}`, label);
      mark.title = title;
      mark.setAttribute("aria-label", title);
      formCell.append(mark);
    }
    if (!formCell.childElementCount) formCell.textContent = "—";
    row.append(formCell);

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
        table.tabIndex = 0;
        table.setAttribute("role", "table");
        table.setAttribute("aria-label", "Bảng xếp hạng vòng tròn");
        const columns = [
          ["rank", "HẠNG", "Thứ hạng"], ["player", "NGƯỜI CHƠI", "Tên người chơi"],
          ["played", "ĐẤU", "Số trận đã đấu"], ["wins", "THẮNG", "Số trận thắng"],
          ["draws", "HÒA", "Số trận hòa"], ["losses", "THUA", "Số trận thua"],
          ["points", "ĐIỂM", "Tổng điểm"], ["head-to-head", "ĐỐI ĐẦU", "Điểm đối đầu trong nhóm hòa điểm"],
          ["difference", "HIỆU SỐ", "Hiệu số điểm ghi được"],
        ];
        const header = el("div", "tournament-standing-row heading");
        header.setAttribute("role", "row");
        for (const [key, label, title] of columns) {
          const cell = el("span", `tournament-standing-cell ${key}`, label);
          cell.title = title;
          cell.setAttribute("role", "columnheader");
          header.append(cell);
        }
        table.append(header);
        tournament.standings.forEach((player, index) => {
          const row = el("div", "tournament-standing-row");
          row.setAttribute("role", "row");
          const difference = Number(player.score_difference || 0);
          const values = [
            player.rank ?? index + 1, player.nickname, player.played, player.wins,
            player.draws, player.losses, player.points, player.head_to_head ?? 0,
            `${difference > 0 ? "+" : ""}${difference}`,
          ];
          values.forEach((value, columnIndex) => {
            const [key] = columns[columnIndex];
            const cell = el("span", `tournament-standing-cell ${key}`, value);
            if (key === "player") cell.title = player.nickname;
            if (key === "difference") cell.classList.add(difference > 0 ? "positive" : difference < 0 ? "negative" : "neutral");
            cell.setAttribute("role", "cell");
            row.append(cell);
          });
          table.append(row);
        });
        disclosure.append(table, el("p", "tournament-standing-note", "Thứ tự xếp hạng: điểm → đối đầu → hiệu số → số trận thắng."));
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
      bracket.tabIndex = 0;
      bracket.setAttribute("role", "region");
      bracket.setAttribute("aria-label", "Nhánh đấu, cuộn ngang để xem các vòng");
      const lanes = tournament.format === "double_elimination"
        ? ["winners", "losers", "final"]
        : ["main"];
      for (const laneName of lanes) {
        const laneRounds = (tournament.rounds || []).filter(round => round.bracket === laneName);
        if (!laneRounds.length) continue;
        const lane = el("section", "tournament-bracket-lane");
        lane.append(el("h4", "", bracketNames[laneName]));
        const board = el("div", "tournament-bracket-board");
        board.tabIndex = 0;
        board.setAttribute("role", "region");
        board.setAttribute("aria-label", bracketNames[laneName]);
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
  // Legacy free-play standings have no Account-Only route. Team tournament
  // standings are provided by the audience-scoped Team Tournament endpoints.
  if (app.accountOnly) {
    app.standings = [];
    renderStandings();
    return;
  }
  const query = app.standingsGameId
    ? `?game_id=${encodeURIComponent(app.standingsGameId)}`
    : "";
  app.standings = await api(`/api/standings${query}`);
  renderStandings();
}

async function refreshTournaments() {
  if (app.accountOnly) { app.tournaments = []; renderTournaments(); return; }
  app.tournaments = await api("/api/tournaments");
  renderTournaments();
}
function updateTeamTournamentPolicy() {
  const form = $("#team-tournament-create");
  if (!form) return;
  const count = form.querySelectorAll('input[name="team_id"]:checked').length;
  const format = form.elements.format;
  const largeField = count > 64;
  if (count > 16) format.value = "group_knockout";
  format.disabled = count > 16;
  $("#team-tournament-qualifier-target-row").classList.toggle("hidden", !largeField);
  const policy = $("#team-tournament-selection-policy");
  policy.textContent = largeField
    ? "Trên 64 đội: đấu loại trực tiếp để rút gọn về số đội được chọn, sau đó vào vòng bảng + loại trực tiếp."
    : count > 16
    ? "17–64 đội: tự động áp dụng vòng bảng + loại trực tiếp."
    : "Từ 2–16 đội: Organizer được chọn thể thức.";
}
function renderTeamTournaments() {
  const legacyVisible = !app.accountOnly;
  $("#view-tournaments > .page-intro").classList.toggle("hidden", !legacyVisible);
  $("#view-tournaments > .tournament-create-panel").classList.toggle("hidden", !legacyVisible);
  $("#view-tournaments > .tournament-list-panel").classList.toggle("hidden", !legacyVisible);
  const root = $("#account-team-tournaments");
  root.classList.toggle("hidden", legacyVisible);
  if (legacyVisible) return;
  $("#team-tournament-admin-panel").classList.toggle("hidden", app.accountAudience !== "admin");
  const gameSelect = $("#team-tournament-game"), previousGame = gameSelect.value;
  gameSelect.replaceChildren(...app.games.map(game => {
    const option = el("option", "", game.name); option.value = game.game_id; return option;
  }));
  gameSelect.value = app.games.some(game => game.game_id === previousGame)
    ? previousGame : (app.competition?.selected_game_id || app.games[0]?.game_id || "");
  const teamOptions = $("#team-tournament-team-options");
  if (app.accountAudience === "admin") {
    teamOptions.replaceChildren();
    for (const team of app.officialTeams) {
      const label = el("label", "tournament-player-option");
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox"; checkbox.name = "team_id"; checkbox.value = team.id;
      label.append(checkbox, el("span", "", `${team.display_name} · ${team.member_count} thành viên`));
      teamOptions.append(label);
    }
    if (!app.officialTeams.length) teamOptions.append(el("div", "empty-state", "Chưa có Team ACTIVE."));
    updateTeamTournamentPolicy();
  }
  const target = $("#team-tournaments-list"); target.replaceChildren();
  if (!app.teamTournaments.length) {
    target.append(el("div", "empty-state", "Chưa có giải đấu Team nào.")); return;
  }
  const statusNames = { REGISTRATION: "ĐANG ĐĂNG KÝ", ACTIVE: "ĐANG DIỄN RA", COMPLETED: "ĐÃ KẾT THÚC", CANCELLED: "ĐÃ HỦY" };
  for (const tournament of app.teamTournaments) {
    const card = el("article", "tournament-card");
    const heading = el("div", "tournament-card-heading");
    const title = el("div", "tournament-card-title");
    title.append(el("span", "tournament-id", `TEAM TOURNAMENT / ${tournament.id.slice(0, 8).toUpperCase()}`),
      el("h3", "", tournament.name));
    heading.append(title, el("span", `tournament-status ${tournament.status.toLowerCase()}`, statusNames[tournament.status] || tournament.status));
    const meta = el("div", "tournament-meta");
    meta.append(el("span", "tournament-meta-item", tournament.game_id),
      el("span", "tournament-meta-item", `${tournament.teams.length} đội`),
      el("span", "tournament-meta-item", ({round_robin:"Vòng tròn tính điểm", single_elimination:"Loại trực tiếp", double_elimination:"Double Elimination", group_knockout:"Vòng bảng + loại trực tiếp", swiss_single_elimination:"Vòng Thụy Sĩ + Loại trực tiếp"})[tournament.format] || tournament.format));
    if (tournament.qualifier_target) meta.append(el("span", "tournament-meta-item", `Vòng loại → ${tournament.qualifier_target} đội`));
    const chips = el("div", "tournament-player-chips");
    tournament.teams.forEach(team => chips.append(el("span", "tournament-player-chip", team.team_name_snapshot)));
    const actions = el("div", "tournament-actions");
    if (app.accountAudience === "admin" && tournament.status === "REGISTRATION") {
      const start = el("button", "button primary small", "BẮT ĐẦU & TẠO LỊCH"); start.type = "button";
      start.onclick = async () => {
        start.disabled = true;
        try { await api(`/api/admin/team-tournaments/${encodeURIComponent(tournament.id)}/start`, jsonOptions("POST", {})); await refreshTeamTournaments(); }
        catch (error) { start.disabled = false; toast(error.message, true); }
      };
      actions.append(start);
    }
    card.append(heading, meta, chips);
    if (tournament.qualifier_target) {
      const qualifierRounds = [...new Set(tournament.bracket.filter(slot => slot.bracket === "WINNERS").map(slot => slot.round_number))].sort((a, b) => a - b);
      const done = (roundNumber) => tournament.bracket.filter(slot => slot.bracket === "WINNERS" && slot.round_number === roundNumber).every(slot => ["COMPLETED", "BYE"].includes(slot.status));
      const activeRound = qualifierRounds.find(roundNumber => !done(roundNumber));
      const qualifierMessage = tournament.status === "REGISTRATION"
        ? `Khi bắt đầu, vòng loại trực tiếp sẽ rút gọn còn ${tournament.qualifier_target} đội.`
        : tournament.groups.length
        ? `Vòng loại hoàn tất · ${tournament.qualifier_target} đội vào vòng bảng.`
        : `Vòng loại để còn ${tournament.qualifier_target} đội${activeRound ? ` · Đang ở vòng ${qualifierRounds.indexOf(activeRound) + 1}/${qualifierRounds.length}` : ""}.`;
      card.append(el("p", "tournament-feedback", qualifierMessage));
    }
    if (["round_robin", "group_knockout", "swiss_single_elimination"].includes(tournament.format) && tournament.standings.length) {
      const isSwiss = tournament.format === "swiss_single_elimination";
      if (isSwiss) {
        const progress = el("p", "tournament-feedback", `Vòng Swiss: ${tournament.swiss_rounds_completed}/${tournament.swiss_rounds_total} hoàn tất · top ${tournament.teams.length < 8 ? 4 : 8} vào vòng loại trực tiếp.`);
        card.append(progress);
      }
      const table = el("div", "tournament-standings"); table.setAttribute("role", "table");
      table.tabIndex = 0;
      table.setAttribute("aria-label", "Bảng điểm giải đấu, cuộn ngang để xem đầy đủ");
      const columns = [["rank", "HẠNG"], ["team_name", "ĐỘI"], ["played", "ĐẤU"], ["wins", "THẮNG"], ["draws", "HÒA"], ["losses", "THUA"], ...(isSwiss ? [["byes", "BYE"], ["buchholz", "BUCHHOLZ"]] : []), ["points", "ĐIỂM"]];
      const headerRow = el("div", "tournament-standing-row heading");
      columns.forEach(([key, label]) => { const cell = el("span", `tournament-standing-cell ${key}`, label); cell.setAttribute("role", "columnheader"); headerRow.append(cell); });
      table.append(headerRow);
      tournament.standings.forEach(item => {
        const row = el("div", "tournament-standing-row"); row.setAttribute("role", "row");
        columns.forEach(([key]) => { const cell = el("span", `tournament-standing-cell ${key}`, item[key] ?? 0); cell.setAttribute("role", "cell"); row.append(cell); });
        table.append(row);
      });
      card.append(table);
      if (isSwiss && tournament.swiss_byes?.length) {
        const byeSummary = tournament.swiss_byes.map(item => `Vòng ${item.round_number}: ${item.team_name}`).join(" · ");
        card.append(el("p", "tournament-feedback", `Lượt miễn đấu: ${byeSummary}`));
      }
    }
    if (tournament.format === "group_knockout") {
      for (const group of tournament.groups || []) {
        const groupPanel = el("section", "tournament-group");
        groupPanel.append(el("h4", "", `${group.name} · Hai đội đầu bảng vào vòng loại trực tiếp`));
        const table = el("div", "tournament-standings"); table.setAttribute("role", "table");
        table.tabIndex = 0;
        table.setAttribute("aria-label", "Bảng điểm " + group.name);
        const columns = [["rank", "HẠNG"], ["team_name", "ĐỘI"], ["played", "ĐẤU"], ["wins", "THẮNG"], ["draws", "HÒA"], ["losses", "THUA"], ["score_difference", "HIỆU SỐ"], ["score_for", "ĐIỂM SỐ"], ["points", "ĐIỂM"]];
        const header = el("div", "tournament-standing-row heading");
        columns.forEach(([key, label]) => header.append(el("span", `tournament-standing-cell ${key}`, label)));
        table.append(header);
        group.standings.forEach(item => {
          const row = el("div", "tournament-standing-row");
          columns.forEach(([key]) => row.append(el("span", `tournament-standing-cell ${key}`, String(item[key] ?? 0))));
          table.append(row);
        });
        groupPanel.append(table); card.append(groupPanel);
      }
    }
    if (actions.childElementCount) card.append(actions);
    if (["single_elimination", "double_elimination", "group_knockout", "swiss_single_elimination"].includes(tournament.format) && tournament.bracket.length) {
      const bracket = el("div", "tournament-bracket");
      bracket.tabIndex = 0;
      bracket.setAttribute("role", "region");
      bracket.setAttribute("aria-label", "Nhánh đấu, cuộn ngang để xem các vòng");
      const bracketRounds = [...new Set(tournament.bracket.map(slot => slot.round_number))].sort((a, b) => a - b);
      const isLargeQualifier = tournament.format === "group_knockout" && Boolean(tournament.qualifier_target);
      const qualifierRounds = isLargeQualifier ? bracketRounds.filter(round => tournament.bracket.some(slot => slot.round_number === round && slot.bracket === "WINNERS")) : [];
      const playoffRounds = bracketRounds.filter(round => !qualifierRounds.includes(round));
      const bracketStatus = { PENDING: "CHỜ VÒNG TRƯỚC", READY: "CHỜ XẾP LỊCH", COMPLETED: "ĐÃ CÓ ĐỘI ĐI TIẾP", BYE: "MIỄN ĐẤU", TIE: "CẦN PHÂN ĐỊNH" };
      for (let roundIndex = 0; roundIndex < bracketRounds.length; roundIndex++) {
        const round = bracketRounds[roundIndex];
        const roundSlots = tournament.bracket.filter(slot => slot.round_number === round);
        const column = el("section", "tournament-bracket-round");
        const isQualifierRound = isLargeQualifier && qualifierRounds.includes(round);
        const playoffIndex = playoffRounds.indexOf(round);
        const qualified = playoffRounds.length ? tournament.bracket.filter(slot => slot.round_number === playoffRounds[0]).length : 0;
        const knockoutRounds = qualified === 2 ? ["BÁN KẾT", "CHUNG KẾT"] : qualified === 4 ? ["TỨ KẾT", "BÁN KẾT", "CHUNG KẾT"] : qualified === 8 ? ["VÒNG 1/8", "TỨ KẾT", "BÁN KẾT", "CHUNG KẾT"] : [];
        const roundName = isQualifierRound ? `VÒNG LOẠI ${qualifierRounds.indexOf(round) + 1}`
          : ["group_knockout", "swiss_single_elimination"].includes(tournament.format) ? knockoutRounds[playoffIndex] : null;
        column.append(el("h4", "", roundName || (playoffIndex === playoffRounds.length - 1 ? "CHUNG KẾT" : `VÒNG ${roundIndex + 1}`)));
        for (const slot of roundSlots) {
          const matchCard = el("div", `tournament-bracket-match ${slot.status.toLowerCase()}`);
          const teamName = id => tournament.teams.find(team => team.team_id === id)?.team_name_snapshot || "Chờ đội đi tiếp";
          matchCard.append(el("span", "tournament-bracket-player", teamName(slot.team_a_id)),
            el("span", "tournament-bracket-player", teamName(slot.team_b_id)),
            el("small", "", slot.conditional_status === "SKIPPED" ? "CHUNG KẾT RESET KHÔNG CẦN THI ĐẤU" : bracketStatus[slot.status] || slot.status),
            el("small", "", isLargeQualifier && slot.bracket === "WINNERS" ? "VÒNG LOẠI" : ({WINNERS:"NHÁNH THẮNG",LOSERS:"NHÁNH THUA",FINAL:"CHUNG KẾT TỔNG",RESET:"CHUNG KẾT RESET"})[slot.bracket] || "NHÁNH CHÍNH"));
          if (slot.winner_team_id) matchCard.append(el("small", "tournament-match-winner", `ĐI TIẾP · ${teamName(slot.winner_team_id)}`));
          if (slot.status === "TIE" && app.accountAudience === "admin" && slot.fixture_id) {
            for (const teamId of [slot.team_a_id, slot.team_b_id]) {
              const resolve = el("button", "button ghost small", `Chọn ${teamName(teamId)} đi tiếp`);
              resolve.type = "button";
              resolve.onclick = async () => {
                resolve.disabled = true;
                try {
                  await api(`/api/admin/team-tournaments/${encodeURIComponent(tournament.id)}/fixtures/${encodeURIComponent(slot.fixture_id)}/resolve-tie`,
                    jsonOptions("POST", { winner_team_id: teamId }));
                  await refreshTeamTournaments();
                } catch (error) { resolve.disabled = false; toast(error.message, true); }
              };
              matchCard.append(resolve);
            }
          }
          column.append(matchCard);
        }
        bracket.append(column);
      }
      card.append(bracket);
    }
    const fixtureList = el("div", "tournament-schedule");
    tournament.fixtures.forEach(fixture => {
      const fixtureCard = el("section", "tournament-schedule-match");
      const teamA = tournament.teams.find(team => team.team_id === fixture.team_a_id)?.team_name_snapshot || "Team A";
      const teamB = tournament.teams.find(team => team.team_id === fixture.team_b_id)?.team_name_snapshot || "Team B";
      const groupName = tournament.groups?.find(group => group.id === fixture.group_id)?.name;
      const bracketSlot = tournament.bracket.find(slot => slot.fixture_id === fixture.id);
      const qualifierSlot = bracketSlot?.bracket === "WINNERS" ? bracketSlot : null;
      const playoffRounds = [...new Set(tournament.bracket.filter(slot => !(tournament.qualifier_target && slot.bracket === "WINNERS")).map(slot => slot.round_number))].sort((a, b) => a - b);
      const playoffRound = bracketSlot ? playoffRounds.indexOf(bracketSlot.round_number) + 1 : fixture.round_number;
      const groupRound = fixture.round_number - (tournament.qualifier_rounds_total || 0);
      const stageName = qualifierSlot && tournament.qualifier_target ? `Vòng loại · Vòng ${qualifierSlot.round_number}` : fixture.stage === "GROUP" ? (tournament.format === "swiss_single_elimination" ? `Swiss · Vòng ${fixture.round_number}` : `${groupName || "Vòng bảng"} · Vòng ${groupRound}`) : ["group_knockout", "swiss_single_elimination"].includes(tournament.format) ? `Loại trực tiếp · Vòng ${playoffRound}` : `Vòng ${fixture.round_number}`;
      fixtureCard.append(el("span", "", `${stageName} · ${teamA} VS ${teamB}`));
      fixtureCard.append(el("small", `tournament-match-state ${(fixture.match_status || "pending").toLowerCase()}`, fixture.match_status || "CHƯA XẾP LỊCH"));
      if (app.accountAudience === "admin" && tournament.status === "ACTIVE" && !fixture.official_request_id) {
        const controls = el("div", "form-buttons");
        const lockInput = document.createElement("input"); lockInput.type = "datetime-local"; lockInput.setAttribute("aria-label", "Thời điểm khóa bot"); lockInput.value = officialLocalInput(Date.now() + 120000);
        const scheduledInput = document.createElement("input"); scheduledInput.type = "datetime-local"; scheduledInput.setAttribute("aria-label", "Thời điểm thi đấu"); scheduledInput.value = officialLocalInput(Date.now() + 300000);
        const schedule = el("button", "button ghost small", "XẾP LỊCH"); schedule.type = "button";
        schedule.onclick = async () => {
          schedule.disabled = true;
          try {
            const bot_lock_at = Math.floor(new Date(lockInput.value).getTime() / 1000);
            const scheduled_at = Math.floor(new Date(scheduledInput.value).getTime() / 1000);
            if (!Number.isFinite(bot_lock_at) || !Number.isFinite(scheduled_at)) throw new Error("Chọn thời gian hợp lệ.");
            await api(`/api/admin/team-tournaments/${encodeURIComponent(tournament.id)}/fixtures/${encodeURIComponent(fixture.id)}/schedule`, jsonOptions("POST", { bot_lock_at, scheduled_at }));
            await refreshTeamTournaments(); await refreshOfficialMatches({includeTeams:false});
          } catch (error) { schedule.disabled = false; toast(error.message, true); }
        };
        controls.append(lockInput, scheduledInput, schedule); fixtureCard.append(controls);
      }
      if (fixture.official_request_id && fixture.match_id) {
        const replay = el("button", "button ghost small", "XEM LIVE / REPLAY"); replay.type = "button";
        replay.onclick = () => loadMatch(fixture.official_request_id, true).catch(error => toast(error.message, true));
        fixtureCard.append(replay);
      }
      fixtureList.append(fixtureCard);
    });
    if (tournament.fixtures.length) card.append(fixtureList);
    target.append(card);
  }
}

async function refreshTeamTournaments() {
  if (!app.accountOnly || !app.account) return;
  const response = await api(`/api/${app.accountAudience}/team-tournaments`);
  if (!Array.isArray(response.tournaments)) throw new Error("Dữ liệu giải đấu Team không hợp lệ.");
  app.teamTournaments = response.tournaments;
  renderTeamTournaments();
  renderStandings();
  renderWorkspaceOverview();
}
async function refreshBots() {
  if (app.accountOnly) {
    if (app.accountAudience !== "player") return;
    // Account-Only returns {bots: [...]}, not the legacy bare array.
    // Keep the current library intact on a failed or malformed response.
    if (!app.team?.team) {
      app.bots = [];
    } else {
      const response = await api("/api/player/bots");
      if (!Array.isArray(response.bots)) throw new Error("Dữ liệu submission của Team không hợp lệ.");
      app.bots = response.bots;
    }
  } else {
    app.bots = await api("/api/bots");
  }
  renderBots();
}
async function refreshMatches() {
  if (app.accountOnly && app.accountAudience !== "admin") {
    await refreshScrimmages(); return;
  }
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
$("#refresh-team-tournaments").addEventListener("click", () => refreshTeamTournaments().catch(e => toast(e.message, true)));
$("#team-tournament-team-options").addEventListener("change", updateTeamTournamentPolicy);
$("#team-tournament-create").elements.format.addEventListener("change", updateTeamTournamentPolicy);
$("#team-tournament-create").addEventListener("submit", async event => {
  event.preventDefault();
  const form = event.currentTarget, button = form.querySelector("[type=submit]");
  const team_ids = [...form.querySelectorAll('input[name="team_id"]:checked')].map(input => input.value);
  if (team_ids.length < 2) {
    feedback("#team-tournament-feedback", "Chọn ít nhất 2 đội.", true); return;
  }
  button.disabled = true;
  try {
    await api("/api/admin/team-tournaments", jsonOptions("POST", {
      name: form.elements.name.value, game_id: form.elements.game_id.value, team_ids,
      format: form.elements.format.value,
      qualifier_target: team_ids.length > 64 ? Number(form.elements.qualifier_target.value) : null
    }));
    form.reset();
    updateTeamTournamentPolicy();
    feedback("#team-tournament-feedback", "Đã tạo giải. Bắt đầu giải để tạo lịch hoặc nhánh đấu.");
    await refreshTeamTournaments();
  } catch (error) { feedback("#team-tournament-feedback", error.message, true); }
  finally { button.disabled = false; }
});
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
  if (app.uploading) return;
  const form = event.currentTarget;
  const button = form.querySelector("[type=submit]");
  const file = $("#bot-file").files[0];
  const battlecode = app.selectedGameId === "battlecode26";
  if (!file || !file.size || file.size > 256 * 1024 || !(battlecode ? /\.(py|java)$/i : /\.(py|cpp|java)$/i).test(file.name)) {
    feedback("#upload-feedback", battlecode ? "Battlecode nhận một file .py hoặc .java có nội dung, tối đa 256 KiB." : "Chọn file .py, .cpp hoặc .java có nội dung, không vượt quá 256 KiB.", true);
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
    if (app.accountOnly) {
      if (!app.team?.team) throw new Error("Cần tham gia Team trước khi nộp bot.");
      const source_base64 = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onerror = () => reject(new Error("Không thể đọc file bot."));
        reader.onload = () => resolve(String(reader.result).split(",")[1]);
        reader.readAsDataURL(file);
      });
      const response = await api("/api/player/bots", jsonOptions("POST", {
        filename: file.name, name: form.elements.name.value,
        game_id: app.competition.selected_game_id, source_base64
      }));
      const bot = response.bot;
      feedback("#upload-feedback", bot.status === "ready" ? "Bot đã nộp cho Team." : "Biên dịch lỗi.", bot.status !== "ready");
      if (bot.logs) {
        $("#compiler-log").textContent = bot.logs;
        $("#compiler-log").classList.remove("hidden");
      }
      await refreshAccountTeam();
      return;
    }
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

async function loadMatch(id, official = false, practice = false) {
  const generation = ++app.generation;
  app.socket?.close();
  clearTimeout(app.reconnectTimer);
  const replayPath = practice ? "/api/" + app.accountAudience + "/scrimmages/" + encodeURIComponent(id) + "/replay" : official
    ? "/api/" + app.accountAudience + "/official-matches/" + encodeURIComponent(id) + "/replay"
    : "/api/matches/" + encodeURIComponent(id) + "/replay";
  const payload = await api(replayPath);
  if (generation !== app.generation) return;
  app.match = payload.match;
  app.replayKind = practice ? "scrimmage" : official ? "official" : "match";
  app.replayRequestId = id;
  app.replayPath = replayPath;
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
  for (const key of ["match", "official", "scrimmage"]) link.searchParams.delete(key);
  link.searchParams.set(app.replayKind, id);
  history.replaceState(null, "", link);
  if (app.frames.length) setFrame(0, false);
  updatePlayback();
  if (["running", "queued"].includes(app.match.status)) {
    if (official || practice) pollOfficialReplay(id, generation);
    else connectSocket(id, generation);
  } else if (!app.frames.length) toast("Trận bị gián đoạn trước khi có trạng thái replay.", true);
}

function scheduleOfficialReplayPoll(id, generation) {
  if (generation !== app.generation || !app.account || !app.accountOnly ||
      !["running", "queued"].includes(app.match?.status)) return;
  // The live replay shares the same server-side auth budget as the calendar.
  // Never send another replay request while a 429 Retry-After is in force.
  const delay = Math.max(1600, app.pollPauseUntil - Date.now() + 250);
  clearTimeout(app.reconnectTimer);
  app.reconnectTimer = setTimeout(() => pollOfficialReplay(id, generation), delay);
}

async function pollOfficialReplay(id, generation) {
  if (generation !== app.generation || !app.account || !app.accountOnly) return;
  if (Date.now() < app.pollPauseUntil) {
    scheduleOfficialReplayPoll(id, generation);
    return;
  }
  try {
    const payload = await api(app.replayKind === "scrimmage" ? app.replayPath : "/api/" + app.accountAudience + "/official-matches/" + encodeURIComponent(id) + "/replay");
    if (generation !== app.generation) return;
    app.match = payload.match;
    app.frames = payload.frames;
    if (app.frames.length) setFrame(Math.min(app.cursor, app.frames.length - 1), false);
    updatePlayback();
  } catch (error) {
    if (generation !== app.generation || error.status === 401) return;
    // Preserve the previously received replay on transient network failure.
  }
  scheduleOfficialReplayPoll(id, generation);
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

const battlecodeTerrain = new WeakMap();
function currentFrame() {
  const frame = app.frames[app.cursor] || selectedGame()?.preview_state || null;
  if (frame?.game_id === "battlecode26") {
    if (battlecodeTerrain.has(frame)) return {...frame, ...battlecodeTerrain.get(frame)};
    let board, dirt = new Set(), cheese = new Set(), traps = new Map();
    for (let i=0;i<=app.cursor && i<app.frames.length;i++) {
      const item=app.frames[i], cached=battlecodeTerrain.get(item);
      if (cached) {
        board=cached.board; dirt=new Set(cached.terrain.dirt); cheese=new Set(cached.terrain.cheese); traps=new Map(cached.terrain.traps);
        continue;
      }
      if (item.board) { board=item.board; dirt=new Set(board.initial_dirt); cheese=new Set(board.initial_cheese); }
      for (const event of item.events || []) {
        if (event.type==="PlaceDirt") dirt.add(event.loc);
        if (event.type==="BreakDirt") dirt.delete(event.loc);
        if (event.type==="CheesePickup") cheese.delete(event.loc);
        if (event.type==="CheeseSpawn") cheese.add(event.loc);
        if (event.type==="PlaceTrap") traps.set(event.loc,event.team);
        if (["RemoveTrap","TriggerTrap"].includes(event.type)) traps.delete(event.loc);
      }
      battlecodeTerrain.set(item,{board,terrain:{dirt:[...dirt],cheese:[...cheese],traps:[...traps]}});
    }
    return {...frame, ...battlecodeTerrain.get(frame)};
  }
  return frame;
}
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
  if (app.match.result_corrections?.length && app.cursor === app.frames.length - 1) {
    const winner = app.match.result?.winner;
    lines.push({ turn: "ORG", text: winner ? `Kết quả Organizer xác nhận: ${winner} thắng` : "Kết quả Organizer xác nhận: Hòa", type: "result" });
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
  const atEnd = app.cursor === app.frames.length - 1;
  const corrected = atEnd && app.match?.result_corrections?.length ? app.match.result : null;
  const result = corrected || frame.result || (atEnd && app.match?.status === "interrupted" ? app.match.result : null);
  if (!result) return;
  app.displayedResult = true;
  $("#victory-overlay").classList.remove("hidden");
  $("#victory-title").textContent = corrected ? "Kết quả được điều chỉnh" : app.match?.status === "interrupted" ? "Trận bị gián đoạn" : result.winner ? "Chiến thắng!" : "Trận đấu hòa";
  $("#victory-winner").textContent = result.winner ? fighterLabel(app.match, result.winner) : "Không có người thắng";
  const correctionHistory = app.match?.result_corrections || [];
  const latestCorrection = correctionHistory[correctionHistory.length - 1];
  const reasons = { organizer_correction: `Organizer đã điều chỉnh kết quả: ${latestCorrection?.reason || "không có ghi chú"}. Replay vẫn giữ nguyên diễn biến trận ban đầu.`, bot_error: "Lỗi bot: " + Object.entries(result.faults || {}).map(([p, error]) => `${p}: ${error}`).join(" · "), server_restart: "Máy chủ đã khởi động lại giữa trận.", server_shutdown: "Máy chủ dừng giữa trận.", server_error: "Máy chủ gặp lỗi khi xử lý trận đấu.", runner_unavailable: "Hạ tầng chạy bot bị gián đoạn. Không xử thua Player.", organizer_cancelled: "Organizer đã hủy trận đấu." };
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
  const url = new URL(location.href);
  for (const key of ["match", "official", "scrimmage"]) url.searchParams.delete(key);
  url.searchParams.set(app.replayKind || "match", app.replayRequestId || app.match.id); url.hash = "home";
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
    const replay = await api(app.replayPath || `/api/matches/${app.match.id}/replay`);
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

function scheduleAccountBootstrapRetry() {
  if (!app.accountOnly || app.initialized || app.shuttingDown) return;
  clearTimeout(app.bootstrapTimer);
  // Wait until the shared source/session budget is replenished. A slight
  // margin prevents retrying on the exact backend window boundary.
  const delay = Math.max(1000, app.pollPauseUntil - Date.now() + 250);
  app.bootstrapTimer = setTimeout(() => {
    app.bootstrapTimer = null;
    if (app.accountOnly && !app.initialized && !app.initializing &&
        !app.shuttingDown) bootstrap();
  }, delay);
}

async function bootstrap() {
  if (app.initializing) return;
  clearTimeout(app.bootstrapTimer); app.bootstrapTimer = null;
  app.initializing = true;
  try {
    const health = await api("/api/health");
    app.runnerMode = health.runner?.mode;
    // Report connectivity from the public health probe, not from an unrelated
    // protected GET that may legitimately return 429 during bootstrap.
    setConnection(health.status === "ok");
    app.accountAuth = health.account_auth === true;
    app.accountOnly = health.account_only === true;
    app.selfRegistration = health.self_registration === true;
    app.emailVerification = health.email_verification === true;
    app.usernameOnlySignup = health.username_only_signup === true;
    app.adminTotpRequired = health.admin_totp_required === true;
    $("#account-admin-otp-field").classList.toggle("hidden", !app.adminTotpRequired);
    if (app.accountOnly && app.emailVerification) {
      const reset = /^#reset-password=([A-Za-z0-9_-]{43})$/.exec(location.hash);
      if (reset) {
        history.replaceState(null, "", location.pathname + location.search);
        $("#account-reset-password-form [name=token]").value = reset[1];
        app.resetTokenLoaded = true;
      }
      const verification = /^#verify-email=([A-Za-z0-9_-]{43})$/.exec(location.hash);
      if (verification) {
        history.replaceState(null, "", location.pathname + location.search);
        try {
          await api("/api/account/auth/verify-email", jsonOptions("POST", {
            token: verification[1]
          }));
          app.emailVerificationNotice = "Xác minh email thành công. Bạn có thể đăng nhập.";
        } catch (error) {
          app.emailVerificationNotice = "Không thể xác minh email: " + error.message;
        }
      }
    }
    if (app.accountOnly) {
      $("#account-mode-note").classList.remove("hidden");
      if (!app.account && !await restoreAccount()) {
        setConnection(true); renderSession();
        showAccountLanding(app.emailVerificationNotice || undefined);
        // Deep links for password recovery and email verification must
        // still open the relevant form without an extra click.
        if (app.resetTokenLoaded || app.emailVerificationNotice) {
          showAccountDialog(app.emailVerificationNotice || undefined);
        }
        app.emailVerificationNotice = null;
        return;
      }
    } else {
      // Establish the legacy cookie first; parallel startup requests then share one identity.
      acceptSession(await api("/api/session"));
      hideAccountLanding();
    }
    const canInspectPrivate = !app.accountOnly || app.accountAudience === "admin";
    const [bots, registry, matches, tournaments, competition] = await Promise.all([
      canInspectPrivate ? api("/api/bots") : Promise.resolve([]),
      api("/api/games"),
      canInspectPrivate ? api("/api/matches") : Promise.resolve([]),
      !app.accountOnly ? api("/api/tournaments") : Promise.resolve([]),
      api("/api/competition")
    ]);
    app.bots = bots; app.games = registry.games; app.matches = matches; app.tournaments = tournaments;
    await acceptCompetition(competition);
    if (app.accountOnly && app.accountAudience === "player") await refreshAccountTeam();
    if (app.accountOnly) {
      await refreshOfficialMatches();
      await refreshTeamTournaments();
      await refreshScrimmages();
    }
    populateStandingsGameSelector();
    if (canInspectPrivate) await refreshStandings();
    else app.standings = [];
    setConnection(health.status === "ok");
    renderBots(); renderRules(true); renderMatches(); renderStandings(); renderTournaments(); renderTeamTournaments();
    applyPermissions();
    // Resolve mode-specific deep links once the server's auth mode is known.
    app.initialized = true;
    navigate();
    connectCompetitionSocket();
    updatePlayback();
    const params = new URL(location.href).searchParams;
    const officialId = params.get("official"), matchId = params.get("match"), practiceId = params.get("scrimmage");
    if (practiceId && app.accountOnly) await loadMatch(practiceId, false, true);
    else if (officialId && app.accountOnly) await loadMatch(officialId, true);
    else if (matchId && (!app.accountOnly || app.accountAudience === "admin")) await loadMatch(matchId);
  } catch (error) {
    // A 429 is a responsive server asking us to slow down, not a disconnect.
    // Unlike the legacy polling loop, an uninitialized Account-Only workspace
    // needs its own timed retry after Retry-After elapses.
    if (app.accountOnly && error.status === 429) scheduleAccountBootstrapRetry();
    else if (error.transport || !app.accountOnly) setConnection(false);
    if (document.body.classList.contains("account-landing-active")) {
      $("#landing-status").textContent = error.status === 429
        ? "Máy chủ đang giới hạn yêu cầu. Hệ thống sẽ tự thử lại."
        : "Không thể kết nối máy chủ. Hãy thử lại sau.";
      $("#landing-retry").classList.toggle("hidden", error.status === 429);
    }
    toast(`Chưa kết nối được workspace: ${error.message}`, true);
  }
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
  } catch (error) {
    if (error.status !== 429) setConnection(false);
    toast(error.message, true);
  }
  finally { busyButton(button, false); button.disabled = false; }
});
setInterval(async () => {
  // Legacy retains its 2-second lobby refresh. Account-Only uses a separate
  // low-frequency feed below, avoiding four protected GETs every 2 seconds.
  if (app.accountOnly) return;
  if (document.hidden || app.refreshing || !app.participant) return;
  if (!app.initialized) { bootstrap(); return; }
  app.refreshing = true;
  try {
    await Promise.all([refreshMatches(), refreshBots(), refreshTournaments()]);
    if (app.accountOnly) await refreshOfficialMatches();
    setConnection(true);
  }
  catch { setConnection(false); }
  finally { app.refreshing = false; }
}, 2000);
window.addEventListener("beforeunload", () => { app.shuttingDown = true; app.generation++; app.socket?.close(); clearTimeout(app.bootstrapTimer); clearTimeout(app.competitionTimer); clearInterval(app.heartbeatTimer); app.competitionSocket?.close(); });

async function refreshAccountTeam() {
  if (!app.accountOnly || app.accountAudience !== "player" || !app.account) return;
  const [mine, invites] = await Promise.all([api("/api/player/team"), api("/api/player/team-invitations")]);
  app.team = mine;
  const team = mine.team, captain = mine.my_role === "CAPTAIN";
  $("#account-team-create").classList.toggle("hidden", !!team);
  $("#account-team-manage").classList.toggle("hidden", !team);
  $("#account-team-status").textContent = team
    ? `${team.display_name} · ${team.status} · ${mine.my_role} · ${team.member_count} thành viên`
    : "Bạn chưa tham gia Team. Tạo Team mới hoặc nhận lời mời bên dưới.";
  $("#account-team-invite").classList.toggle("hidden", !captain || team?.status === "ARCHIVED");
  $("#account-team-activate").classList.toggle("hidden", !captain || team?.status !== "DRAFT");
  $("#account-team-archive").classList.toggle("hidden", !captain);
  $("#account-team-rename").classList.toggle("hidden", !captain);
  $("#account-team-leave").classList.toggle("hidden", !team || captain);
  const inbox = $("#account-team-inbox");
  inbox.replaceChildren();
  for (const inv of invites.invitations.filter(i => i.status === "PENDING")) {
    const row = el("div", "bot-row"), label = el("span", "", `Lời mời: ${inv.team_display_name} · hết hạn ${new Date(inv.expires_at*1000).toLocaleString("vi-VN")}`);
    row.append(label);
    for (const action of ["accept","decline"]) {
      const btn = el("button", "button ghost small", action === "accept" ? "Tham gia" : "Từ chối");
      btn.disabled = !!team && action === "accept";
      btn.onclick = async () => {
        try {
          await api(`/api/player/team-invitations/${encodeURIComponent(inv.id)}/${action}`, jsonOptions("POST", {}));
          await refreshAccountTeam();
        } catch (e) { toast(e.message, true); }
      };
      row.append(btn);
    }
    inbox.append(row);
  }
  if (!inbox.childElementCount) inbox.append(el("p", "form-note", "Không có lời mời Team đang chờ."));
  if (team) {
    const members = await api(`/api/player/teams/${encodeURIComponent(team.id)}/members`);
    const target = $("#account-team-members");
    target.replaceChildren();
    target.append(el("strong", "", "Thành viên: "));
    target.append(document.createTextNode(members.members.map(m => `${m.display_name} (${m.team_role})`).join(", ")));
    const actions = $("#account-team-member-actions"); actions.replaceChildren();
    if (captain) for (const member of members.members.filter(m => m.team_role === "MEMBER")) {
      const row=el("div","bot-row");row.append(el("span","",member.display_name));
      for(const action of ["captain-transfer","remove"]){
        const btn=el("button","button ghost small",action==="remove"?"Xóa thành viên":"Chuyển Captain");
        btn.onclick=async()=>{
          if(!confirm(action==="remove"?"Xóa thành viên khỏi Team?":"Chuyển quyền Captain cho thành viên này?"))return;
          const path=action==="remove" ? `/api/player/teams/${team.id}/members/${member.user_id}/remove`
            : `/api/player/teams/${team.id}/captain-transfer`;
          try{await api(path,jsonOptions("POST",action==="remove"?{}:{new_captain_user_id:member.user_id}));await refreshAccountTeam();}
          catch(e){toast(e.message,true);}
        };row.append(btn);
      }actions.append(row);
    }
  }
  const bots = team ? await api("/api/player/bots") : {bots:[]};
  app.bots = bots.bots;
  app.activeTeamBot = team ? (await api(`/api/player/active-bot?game_id=${encodeURIComponent(app.competition.selected_game_id)}`)).active : null;
  renderBots();
  renderStats();
}
function renderAccountBotLibrary() {
  const target = $("#bot-library");
  target.replaceChildren();
  if (!app.bots.length) target.append(el("div","empty-state","Team chưa có submission."));
  for (const bot of app.bots) {
    const row=el("div","bot-row"), name=el("strong","",`${bot.name} · ${bot.language.toUpperCase()} · ${bot.status}`);
    row.append(name,el("span","tag",bot.game_id));
    const active=app.activeTeamBot?.bot?.id===bot.id;
    const btn=el("button","button ghost small",active?"Active Bot ✓":"Chọn Active Bot");
    btn.disabled=app.team?.my_role!=="CAPTAIN" || app.team?.team?.status!=="ACTIVE" || bot.status!=="ready" || active;
    btn.onclick=async()=>{
      try { await api("/api/player/active-bot",jsonOptions("PUT",{bot_id:bot.id,game_id:bot.game_id})); await refreshAccountTeam(); }
      catch(e){toast(e.message,true);}
    };
    row.append(btn);
    const view=el("button","button ghost small","Xem source");
    view.onclick=async()=>{
      try{const src=await api(`/api/player/bots/${bot.id}/source`);
        const details=el("details");details.open=true;
        details.append(el("summary","","Source · "+src.filename),el("pre","",src.source));
        row.append(details);view.disabled=true;
      }catch(e){toast(e.message,true);}
    };row.append(view);
    if(bot.logs) {const details=el("details"); details.append(el("summary","","Compiler log"),el("pre","",bot.logs));row.append(details);}
    target.append(row);
  }
}
$("#account-team-create").addEventListener("submit",async event=>{
  event.preventDefault(); const form=event.currentTarget,btn=form.querySelector("button");btn.disabled=true;
  try { await api("/api/player/teams",jsonOptions("POST",{
    slug:form.elements.slug.value,display_name:form.elements.display_name.value
  })); await refreshAccountTeam();toast("Đã tạo Team.");}
  catch(e){toast(e.message,true);}finally{btn.disabled=false;}
});
$("#account-team-invite").addEventListener("submit",async event=>{
  event.preventDefault();const form=event.currentTarget,btn=form.querySelector("button");btn.disabled=true;
  try {await api(`/api/player/teams/${app.team.team.id}/invitations`,jsonOptions("POST",{username:form.elements.username.value}));
    form.reset();toast("Đã gửi lời mời.");await refreshAccountTeam();}
  catch(e){toast(e.message,true);}finally{btn.disabled=false;}
});
$("#account-team-activate").addEventListener("click",async()=>{
  try {await api(`/api/player/teams/${app.team.team.id}/activate`,jsonOptions("POST",{}));await refreshAccountTeam();}
  catch(e){toast(e.message,true);}
});
$("#account-team-archive").addEventListener("click",async()=>{
  if(!confirm("Lưu trữ Team sẽ kết thúc tất cả memberships và hủy lời mời. Tiếp tục?"))return;
  try{await api(`/api/player/teams/${app.team.team.id}/archive`,jsonOptions("POST",{}));await refreshAccountTeam();}
  catch(e){toast(e.message,true);}
});

$("#account-team-rename").addEventListener("submit", async event => {
  event.preventDefault();
  // currentTarget is only available while the browser dispatches the event,
  // not after the first await. Keep a stable reference for subsequent updates.
  const form = event.currentTarget;
  const button = form.querySelector("[type=submit]");
  button.disabled = true;
  try {
    await api(`/api/player/teams/${app.team.team.id}`, jsonOptions("PATCH", {
      display_name: form.elements.display_name.value
    }));
    form.reset();
    await refreshAccountTeam();
    toast("Đã đổi tên Team.");
  } catch (error) {
    toast(error.message, true);
  } finally {
    button.disabled = false;
  }
});
$("#account-team-leave").addEventListener("click",async()=>{
  if(!confirm("Bạn muốn rời Team?"))return;
  try{await api(`/api/player/teams/${app.team.team.id}/leave`,jsonOptions("POST",{}));await refreshAccountTeam();}
  catch(e){toast(e.message,true);}
});


// Account-Only polls one Official endpoint at a measured cadence. Never poll
// Team dropdown options continuously, and honor Retry-After when limited.
setInterval(async () => {
  if (document.hidden || !app.accountOnly || !app.initialized || !app.account ||
      app.officialRefreshing || Date.now() < app.pollPauseUntil) return;
  app.officialRefreshing = true;
  try {
    await refreshOfficialMatches({includeTeams: false});
    if (location.hash === "#tournaments" && !$("#account-team-tournaments").contains(document.activeElement)) {
      await refreshTeamTournaments();
    }
    if (app.accountOnly && app.account && app.initialized) setConnection(true);
  } catch (error) {
    // HTTP 429/403/validation errors do not mean that the network is down.
    if (error.transport) setConnection(false);
  } finally {
    app.officialRefreshing = false;
  }
}, 10000);

// Phase 4.2D3: Account-Only Official Match workspace.
// Uses the same authenticated API wrapper as Team management.
function officialDateTime(seconds) {
  return new Date(seconds * 1000).toLocaleString("vi-VN");
}
function officialLocalInput(ms) {
  const date = new Date(ms);
  return new Date(ms - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}
async function refreshOfficialMatches({includeTeams = true} = {}) {
  if (!app.accountOnly || !app.account) return;
  const account = app.account, audience = app.accountAudience;
  const isAdmin = audience === "admin";
  const response = await api("/api/" + audience + "/official-matches");
  if (app.account !== account || app.accountAudience !== audience) return;
  if (!Array.isArray(response.requests)) throw new Error("Danh sách Official Match không hợp lệ.");
  if (isAdmin && includeTeams) {
    const teams = await api("/api/admin/teams");
    if (app.account !== account || app.accountAudience !== audience) return;
    app.officialTeams = teams.teams.filter(team => team.status === "ACTIVE");
    for (const [selector, fallback] of [
      ["#official-team-a", app.officialTeams[0]?.id || ""],
      ["#official-team-b", app.officialTeams[1]?.id || ""]
    ]) {
      const input = $(selector), previous = input.value;
      input.replaceChildren(...app.officialTeams.map(team => {
        const option = el("option", "", team.display_name);
        option.value = team.id;
        return option;
      }));
      input.value = app.officialTeams.some(team => team.id === previous) ? previous : fallback;
    }
    const game = $("#official-game"), previous = game.value;
    game.replaceChildren(...app.games.map(item => {
      const option = el("option", "", item.name);
      option.value = item.game_id;
      return option;
    }));
    game.value = app.games.some(item => item.game_id === previous)
      ? previous : app.competition?.selected_game_id || "";
    $("#official-schedule-form [type=submit]").disabled = app.officialTeams.length < 2 || !app.games.length;
  }
  app.officialMatches = response.requests;
  $("#official-admin-panel").classList.toggle("hidden", !isAdmin);
  $("#admin-player-recovery-panel").classList.toggle("hidden", !isAdmin);
  $("#official-list-heading").textContent = isAdmin ? "Tất cả Official Matches" : "Trận đấu của Team tôi";
  renderOfficialMatches();
  renderStats();
}
function renderOfficialMatches() {
  const target = $("#official-match-list");
  target.replaceChildren();
  if (!app.officialMatches.length) {
    target.append(el("div", "empty-state", "Chưa có trận đấu chính thức nào."));
    return;
  }
  for (const item of app.officialMatches) {
    const row = el("article", "official-match-row");
    const copy = el("div", "official-match-copy");
    const slots = Object.fromEntries((item.slots || []).map(slot => [slot.side, slot]));
    const label = side => slots[side]?.team_name_snapshot ||
      app.officialTeams.find(team => team.id === (side === "A" ? item.team_a_id : item.team_b_id))?.display_name ||
      (side === "A" ? "Team A" : "Team B");
    copy.append(el("strong", "", label("A") + " vs " + label("B")));
    copy.append(el("div", "form-note", item.game_id + " · Khóa: " + officialDateTime(item.bot_lock_at) +
      " · Đấu: " + officialDateTime(item.scheduled_at)));
    copy.append(el("span", "tag official-match-status", "Trạng thái: " + item.status));
    if (item.status_reason) copy.append(el("div", "form-note", item.status_reason));
    if (item.outcome) copy.append(el("div", "form-note", "Kết quả: " +
      (item.outcome.winner_side || "Hòa") + " · " + (item.outcome.turn ?? 0) + " lượt"));
    row.append(copy);
    if (item.match_id) {
      const watch = el("button", "button ghost small", "Xem Live / Replay ↗");
      watch.type = "button";
      watch.onclick = () => loadMatch(item.id, true).catch(error => toast(error.message, true));
      row.append(watch);
    }
    if (app.accountAudience === "admin" && ["SCHEDULED","LOCKED","BLOCKED"].includes(item.status)) {
      const cancel = el("button", "button ghost small", "Hủy lịch");
      cancel.type = "button";
      cancel.onclick = async () => {
        if (!window.confirm("Hủy lịch thi đấu này?")) return;
        cancel.disabled = true;
        try {
          await api("/api/admin/official-matches/" + encodeURIComponent(item.id) + "/cancel",
            jsonOptions("POST", {}));
          await refreshOfficialMatches();
        } catch (error) { cancel.disabled = false; toast(error.message, true); }
      };
      row.append(cancel);
    }
    target.append(row);
  }
}
$("#official-refresh").addEventListener("click", () =>
  refreshOfficialMatches().catch(error => toast(error.message, true)));

$("#admin-player-recovery-form").addEventListener("submit", async event => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("[type=submit]");
  $("#admin-player-recovery-token").value = "";
  $("#admin-player-recovery-result").classList.add("hidden");
  busyButton(button, true);
  try {
    if (!app.accountOnly || app.account?.system_role !== "ADMIN") {
      throw new Error("Chỉ Admin được cấp mã khôi phục.");
    }
    const issued = await api("/api/admin/auth/player-recovery", jsonOptions("POST", {
      username: form.elements.username.value
    }));
    form.reset();
    $("#admin-player-recovery-token").value = issued.token;
    $("#admin-player-recovery-result").classList.remove("hidden");
    feedback("#admin-player-recovery-feedback", "Mã chỉ có hiệu lực 30 phút. Hãy chuyển riêng cho Player.");
  } catch (error) {
    feedback("#admin-player-recovery-feedback", error.message, true);
  } finally {
    busyButton(button, false); button.disabled = false;
  }
});
$("#admin-player-recovery-copy").addEventListener("click", async () => {
  const token = $("#admin-player-recovery-token").value;
  if (!token) return;
  try {
    await navigator.clipboard.writeText(token);
    feedback("#admin-player-recovery-feedback", "Đã sao chép mã. Chỉ chia sẻ riêng cho đúng Player.");
  } catch {
    $("#admin-player-recovery-token").select();
    feedback("#admin-player-recovery-feedback", "Chọn và sao chép mã trong ô phía trên.");
  }
});
$("#official-schedule-form").addEventListener("submit", async event => {
  event.preventDefault();
  const form = event.currentTarget, button = form.querySelector("[type=submit]");
  const lock = Math.floor(new Date(form.elements.bot_lock_at.value).getTime() / 1000);
  const scheduled = Math.floor(new Date(form.elements.scheduled_at.value).getTime() / 1000);
  if (!Number.isFinite(lock) || !Number.isFinite(scheduled) || lock > scheduled ||
      lock < Math.floor(Date.now() / 1000)) {
    feedback("#official-schedule-feedback", "Giờ khóa bot và giờ thi đấu không hợp lệ.", true);
    return;
  }
  button.disabled = true;
  try {
    await api("/api/admin/official-matches", jsonOptions("POST", {
      team_a_id: form.elements.team_a_id.value, team_b_id: form.elements.team_b_id.value,
      game_id: form.elements.game_id.value, bot_lock_at: lock, scheduled_at: scheduled
    }));
    feedback("#official-schedule-feedback", "Đã xếp lịch Official Match.");
    await refreshOfficialMatches();
  } catch (error) {
    feedback("#official-schedule-feedback", error.message, true);
  } finally { button.disabled = false; }
});
{
  const form = $("#official-schedule-form");
  form.elements.bot_lock_at.value = officialLocalInput(Date.now() + 120000);
  form.elements.scheduled_at.value = officialLocalInput(Date.now() + 300000);
}
