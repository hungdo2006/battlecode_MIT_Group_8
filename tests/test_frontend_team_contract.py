"""Account-Only frontend regressions and platform-independent fingerprints."""
from pathlib import Path
import re
from scripts import version_frontend

ROOT = Path(__file__).resolve().parent.parent


def test_account_only_permissions_operate_on_node_lists():
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    assert 'document.querySelectorAll(".player-only, [data-go=upload]' in js
    assert 'document.querySelectorAll(".nav-item[data-view=upload], #view-upload .two-column' in js
    assert 'document.querySelectorAll(\'[data-sample]\')' in js
    # A single-node selector cannot be followed by NodeList.forEach. Guard
    # the entire script so legacy and account-only branches are covered.
    assert not re.search(r"(?<!\$)\$\([^;\n]*?\)\.forEach\(", js)
    assert '(!accountPlayer && location.hash === "#upload")' in js


def test_team_invitations_are_visible_when_no_team_exists():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    assert html.count('id="account-team-inbox"') == 1
    assert html.index('id="account-team-inbox"') < html.index('id="account-team-manage"')


def test_frontend_fingerprint_is_stable_under_windows_autocrlf(tmp_path, monkeypatch):
    monkeypatch.setattr(version_frontend, "FRONTEND", tmp_path)
    asset = tmp_path / "app.js"
    document = '<script src="/static/app.js?v=old"></script>'
    asset.write_bytes(b"const a=1;\nconst b=2;\n")
    result = version_frontend.versioned_html(document)
    asset.write_bytes(b"const a=1;\r\nconst b=2;\r\n")
    assert version_frontend.versioned_html(document) == result


def test_committed_asset_versions_current():
    # The build script checks *all* HTML documents, not only index.html.
    for page in sorted((ROOT / "frontend").glob("*.html")):
        html = page.read_text(encoding="utf-8")
        assert version_frontend.versioned_html(html) == html, page.name


def test_account_only_refresh_unwraps_team_bot_response():
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    assert 'const response = await api("/api/player/bots");' in js
    assert 'if (!Array.isArray(response.bots))' in js
    assert 'app.bots = response.bots;' in js
    assert 'app.bots = await api("/api/bots");' in js  # legacy still accepts array
    assert 'async function refreshBots() {' in js


def test_team_rename_preserves_form_across_async_boundary():
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    handler = js.split('$("#account-team-rename").addEventListener("submit"', 1)[1]
    handler = handler.split('$("#account-team-leave").addEventListener', 1)[0]
    assert 'const form = event.currentTarget;' in handler
    assert 'display_name: form.elements.display_name.value' in handler
    assert 'form.reset();' in handler
    assert 'await refreshAccountTeam();' in handler
    assert 'event.currentTarget.reset()' not in handler


def test_browser_account_checker_navigates_to_team_workspace():
    checker = (ROOT / "scripts" / "check_account_ui.py").read_text(encoding="utf-8")
    assert checker.index('page.locator(\'.nav-item[data-view="upload"]\').click()') < checker.index(
        'page.locator("#account-team-panel").wait_for(state="visible")')


def test_account_websocket_handshake_denial_checks_http_auth():
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    assert 'const socketAudience = app.accountAudience;' in js
    assert 'cache: "no-store"' in js
    # Match a braced or multiline branch, not one brittle spelling.
    assert re.search(
        r"if\s*\(response\.status\s*===\s*401\s*\|\|\s*response\.status\s*===\s*403\)\s*\{\s*accountExpired\(\);",
        js,
    )
    assert 'if (socket !== app.competitionSocket) return;' in js
    assert '.catch(retry);' in js


def test_official_workspace_is_account_only_and_form_has_deadlines():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    assert 'id="view-official"' in html
    assert 'id="official-schedule-form"' in html
    assert 'name="bot_lock_at"' in html
    assert 'name="scheduled_at"' in html
    assert 'id="official-match-list"' in html
    assert 'data-view="official"' in html
    assert 'app.accountOnly' in js
    assert 'async function refreshOfficialMatches({includeTeams = true} = {})' in js
    assert '/api/admin/official-matches' in js
    assert 'official-matches/" + encodeURIComponent(id) + "/replay' in js
    assert 'if (app.accountOnly) { app.tournaments = []; renderTournaments(); return; }' in js
    assert 'async function refreshStandings()' in js
    assert 'app.standings = await api(`/api/standings${query}`);' in js



def test_account_only_does_not_fetch_legacy_standings_during_admin_bootstrap():
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    standings = js.split("async function refreshStandings() {", 1)[1]
    standings = standings.split("\nasync function refreshTournaments()", 1)[0]
    # /api/admin/standings does not exist. This must be checked before
    # the generic API helper scopes /api/standings to the Admin audience.
    assert standings.index("if (app.accountOnly) {") < standings.index(
        'app.standings = await api(`/api/standings${query}`);'
    )
    assert "app.standings = [];" in standings
    assert "renderStandings();" in standings
    assert re.search(r"if \(app\.accountOnly\) \{[^}]*return;", standings, re.S)

    bootstrap = js.split("async function bootstrap() {", 1)[1]
    bootstrap = bootstrap.split('bootstrap();\n$("#retry-connection")', 1)[0]
    assert bootstrap.index("await refreshStandings();") < bootstrap.index(
        "connectCompetitionSocket();"
    )


def test_account_only_background_poll_respects_auth_budget_and_keeps_online_on_429():
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    # Previous Admin polling made four protected requests every 2 seconds.
    # Legacy-only fast polling is retained; Account-Only uses one slower feed.
    legacy = js.split('setInterval(async () => {', 1)[1].split('}, 2000);', 1)[0]
    assert 'if (app.accountOnly) return;' in legacy
    official = js.split('// Account-Only polls one Official endpoint', 1)[1]
    official = official.split('}, 10000);', 1)[0]
    assert 'Date.now() < app.pollPauseUntil' in official
    assert 'app.officialRefreshing' in official
    assert 'refreshOfficialMatches({includeTeams: false})' in official
    assert 'if (error.transport) setConnection(false);' in official
    assert 'setConnection(false)' not in official.replace(
        'if (error.transport) setConnection(false);', '')
    assert 'if (isAdmin && includeTeams)' in js
    assert 'const teams = await api("/api/admin/teams");' in js
    assert 'response.status === 429' in js
    assert 'response.headers.get("Retry-After")' in js
    assert 'app.pollPauseUntil = Math.max(' in js
    assert 'if (error.status !== 429) setConnection(false);' in js


def test_account_only_websocket_reconnect_backoff_preserves_revocation_checks():
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    assert "competitionRetryMs: 5000" in js
    assert "if (app.accountOnly) app.competitionRetryMs = 5000;" in js
    assert "Math.min(30000, app.competitionRetryMs * 2)" in js
    assert "Math.max(0, app.pollPauseUntil - Date.now())" in js
    assert 'response.status === 429' in js
    assert 'response.status === 401 || response.status === 403' in js
    assert "accountExpired();" in js
    # Legacy reconnect still uses its original 1200ms schedule.
    assert "app.competitionTimer = setTimeout(connectCompetitionSocket, 1200);" in js


def test_live_replay_cannot_poll_inside_retry_after_window():
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    replay = js.split("function scheduleOfficialReplayPoll(", 1)[1]
    replay = replay.split("function connectSocket(", 1)[0]
    assert 'Date.now() < app.pollPauseUntil' in replay
    assert 'Math.max(1600, app.pollPauseUntil - Date.now() + 250)' in replay
    assert 'scheduleOfficialReplayPoll(id, generation);' in replay
    assert 'setTimeout(() => pollOfficialReplay(id, generation), 1600)' not in replay
    assert 'generation !== app.generation' in replay


def test_account_startup_retries_after_429_without_manual_action():
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    bootstrap = js.split("function scheduleAccountBootstrapRetry()", 1)[1]
    bootstrap = bootstrap.split('bootstrap();\n$("#retry-connection")', 1)[0]
    assert 'app.pollPauseUntil - Date.now() + 250' in bootstrap
    assert 'app.bootstrapTimer = setTimeout(() => {' in bootstrap
    assert '!app.initialized && !app.initializing' in bootstrap
    assert 'if (app.accountOnly && error.status === 429) scheduleAccountBootstrapRetry();' in bootstrap
    assert 'if (response.status === 429) {' in js  # restoreAccount path


def test_successful_account_poll_restores_network_indicator():
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    official = js.split('// Account-Only polls one Official endpoint', 1)[1]
    official = official.split('}, 10000);', 1)[0]
    assert 'await refreshOfficialMatches({includeTeams: false});' in official
    assert 'if (app.accountOnly && app.account && app.initialized) setConnection(true);' in official
    assert 'if (error.transport) setConnection(false);' in official


def test_phase43a_auth_choice_has_no_browser_selected_role():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    assert 'id="account-login-choice"' in html
    assert 'id="account-register-choice"' in html
    assert 'id="account-register-form"' in html
    assert 'name="audience"' not in html
    assert 'app.selfRegistration = health.self_registration === true;' in js
    assert 'api("/api/account/auth/login"' in js
    assert 'api("/api/account/auth/register"' in js
    assert 'acceptAccount(data, data.audience);' in js



def test_anonymous_account_entry_paths_are_exact_and_authenticated_writes_keep_csrf():
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    routing = js.split("const PUBLIC_ACCOUNT_ENTRY_PATHS = new Set([", 1)[1]
    routing = routing.split("]);", 1)[0]
    expected = {
        "/api/account/auth/login", "/api/account/auth/register",
        "/api/account/auth/verify-email", "/api/account/auth/resend-verification",
        "/api/account/auth/request-reset", "/api/account/auth/reset-password",
        "/api/player/auth/login", "/api/admin/auth/login", "/api/player/auth/activate",
    }
    assert set(re.findall(r'"(/api/[^"]+)"', routing)) == expected
    assert '!PUBLIC_ACCOUNT_ENTRY_PATHS.has(requestUrl.pathname)' in js
    assert '|| path.startsWith("/api/account/")) return path;' in js
    # Anonymous entry actions are exempt from session CSRF, not from backend
    # Origin, body and rate limits. Every other authenticated write still
    # retrieves the token through accountCsrf().
    assert "const token = await accountCsrf();" in js
    assert 'if (!app.accountAudience) throw new Error(' in js


def test_mid_bootstrap_revocation_rechecks_session_without_conflating_permission_denial():
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    assert 'async function recheckAccountAfterForbidden(accountAtRequest, audienceAtRequest)' in js
    assert 'if (app.accountOnly && response.status === 403)' in js
    assert 'await recheckAccountAfterForbidden(accountAtRequest, audienceAtRequest);' in js
    assert 'app.account !== accountAtRequest' in js
    assert 'proof.status === 401 && app.account === accountAtRequest' in js
    assert 'cache: "no-store"' in js
    smoke = (ROOT / "scripts" / "check_account_frontend_routing.cjs").read_text(encoding="utf-8")
    for scenario in ('"permission"', '"revoked"', '"changed-session"', '"offline"'):
        assert scenario in smoke
    checker = (ROOT / "scripts" / "check_account_ui.py").read_text(encoding="utf-8")
    assert 'landing.wait_for(state="visible", timeout=16000)' in checker
    assert 'assert not dialog.is_visible()' in checker
