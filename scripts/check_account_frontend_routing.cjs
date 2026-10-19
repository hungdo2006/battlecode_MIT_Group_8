"use strict";
// Real runtime checks for the frontend API helpers, without requiring Chrome,
// secrets, servers, or Node dependencies. Browser + Docker acceptance remains separate.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "..", "frontend", "app.js"), "utf8");
const start = source.indexOf("const PUBLIC_ACCOUNT_ENTRY_PATHS = new Set([");
const end = source.indexOf("\nfunction jsonOptions(", start);
assert(start >= 0 && end > start, "Frontend account API helpers not found");
const sourceHelpers = source.slice(start, end);
const origin = "https://arena-qa.example.org";
const calls = [];
let forbiddenMode = "none", expiredCalls = 0;
const app = { accountOnly: true, accountAudience: null, account: null, csrf: null, pollPauseUntil: 0 };
async function fakeFetch(url, options = {}) {
  const pathname = new URL(url, origin).pathname;
  calls.push({ pathname, method: (options.method || "GET").toUpperCase(), headers: options.headers || {} });
  if (pathname === "/api/player/team" && forbiddenMode !== "none") {
    return { ok: false, status: 403, text: async () => '{"detail":"Forbidden"}',
             headers: { get: () => null } };
  }
  if (pathname === "/api/player/auth/me" && forbiddenMode !== "none") {
    if (forbiddenMode === "offline") throw new Error("QA simulated transport outage");
    if (forbiddenMode === "changed-session") app.account = { id: "new-session" };
    const status = forbiddenMode === "permission" ? 200 : 401;
    return { ok: status === 200, status, text: async () => '{"detail":"Session"}',
             headers: { get: () => null } };
  }
  if (pathname.endsWith("/auth/csrf")) {
    return { ok: true, status: 200, json: async () => ({ csrf_token: "session-csrf-qa" }) };
  }
  return { ok: true, status: 200, text: async () => '{"ok":true}', headers: { get: () => null } };
}
const context = vm.createContext({ app, window: { location: { origin } }, URL, fetch: fakeFetch,
  accountExpired: () => { expiredCalls++; app.account = null; app.accountAudience = null; app.csrf = null; } });
const { api, scopedApiPath } = vm.runInContext(sourceHelpers + "\n({api,scopedApiPath})", context);

(async () => {
  const publicEntries = [
    "/api/account/auth/login", "/api/account/auth/register",
    "/api/account/auth/verify-email", "/api/account/auth/resend-verification",
    "/api/account/auth/request-reset", "/api/account/auth/reset-password",
    "/api/player/auth/login", "/api/admin/auth/login", "/api/player/auth/activate",
  ];
  for (const entry of publicEntries) {
    await api(entry, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
  }
  assert.deepEqual(calls.map(call => call.pathname), publicEntries, "entry URLs must not gain audience prefix");
  assert(calls.every(call => !("X-CSRF-Token" in call.headers)), "pre-session entry actions must not request CSRF");

  // An unknown write must never receive the anonymous exception.
  const prior = calls.length;
  await assert.rejects(api("/api/account/auth/unlisted", { method: "POST" }), /Phiên tài khoản/);
  assert.equal(calls.length, prior, "unknown pre-session mutation must not reach backend");

  // Public entry exception must not weaken authenticated Player/Admin writes.
  app.accountAudience = "player";
  assert.equal(scopedApiPath("/api/matches"), "/api/player/matches");
  await api("/api/player/teams", { method: "POST" });
  assert.deepEqual(calls.slice(-2).map(call => call.pathname),
    ["/api/player/auth/csrf", "/api/player/teams"]);
  assert.equal(calls.at(-1).headers["X-CSRF-Token"], "session-csrf-qa");
  app.csrf = null;
  app.accountAudience = "admin";
  await api("/api/admin/competition/open", { method: "POST" });
  assert.deepEqual(calls.slice(-2).map(call => call.pathname),
    ["/api/admin/auth/csrf", "/api/admin/competition/open"]);
  assert.equal(calls.at(-1).headers["X-CSRF-Token"], "session-csrf-qa");

  // Legacy mode must not silently rewrite routes or fetch Account-Only CSRF.
  app.accountOnly = false;
  app.accountAudience = null;
  app.csrf = null;
  await api("/api/matches", { method: "POST" });
  assert.equal(calls.at(-1).pathname, "/api/matches");
  // QA-03: recheck account after a 403 without confusing genuine forbidden
  // actions, revoked sessions, late probes, or transport failures.
  app.accountOnly = true;
  app.accountAudience = "player";
  app.csrf = null;
  app.account = { id: "before-revocation" };
  forbiddenMode = "permission";
  await assert.rejects(api("/api/player/team"), error => error.status === 403);
  assert.deepEqual(calls.slice(-2).map(call => call.pathname),
    ["/api/player/team", "/api/player/auth/me"]);
  assert.equal(expiredCalls, 0);
  assert(app.account, "genuine 403 should preserve valid account");

  forbiddenMode = "revoked";
  await assert.rejects(api("/api/player/team"), error => error.status === 403);
  assert.equal(expiredCalls, 1, "401 session proof should clear expired account");
  assert.equal(app.account, null);

  app.accountAudience = "player";
  app.account = { id: "old-session" };
  forbiddenMode = "changed-session";
  await assert.rejects(api("/api/player/team"), error => error.status === 403);
  assert.equal(expiredCalls, 1, "late proof must not logout a new session");
  assert.equal(app.account.id, "new-session");

  forbiddenMode = "offline";
  await assert.rejects(api("/api/player/team"), error => error.status === 403);
  assert.equal(expiredCalls, 1, "failed probe is not revocation proof");
  assert.equal(app.account.id, "new-session");

  // The legacy free-play standings endpoint is not available under
  // /api/admin or /api/player. Do not block Account-Only bootstrap/WebSocket.
  const standingsStart = source.indexOf("async function refreshStandings() {");
  const standingsEnd = source.indexOf("\nasync function refreshTournaments()", standingsStart);
  assert(standingsStart >= 0 && standingsEnd > standingsStart, "Standings helper missing");
  const standingsRequests = [];
  const standingsApp = {
    accountOnly: true, standingsGameId: "ott_v2", standings: [{ stale: true }],
  };
  let standingsRenders = 0;
  const refreshStandings = vm.runInNewContext(
    source.slice(standingsStart, standingsEnd) + "\nrefreshStandings",
    {
      app: standingsApp,
      api: async url => { standingsRequests.push(url); return [{ game_id: "ott_v2" }]; },
      renderStandings: () => { standingsRenders++; },
      encodeURIComponent,
    }
  );
  await refreshStandings();
  assert.equal(standingsRequests.length, 0, "Account-Only must not fetch legacy standings");
  assert.equal(standingsApp.standings.length, 0, "stale legacy standings must be cleared");
  assert.equal(standingsRenders, 1, "Account-Only should still render the empty standings state");

  standingsApp.accountOnly = false;
  await refreshStandings();
  assert.equal(standingsRequests.at(-1), "/api/standings?game_id=ott_v2",
    "Legacy mode must still load free-play standings");
  assert.equal(standingsApp.standings.length, 1);

  console.log("PASS: account routing/CSRF, forbidden-session recheck, stale-login guard and standings modes");
})().catch(error => { console.error(error); process.exitCode = 1; });
