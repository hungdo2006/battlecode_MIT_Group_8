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
    assert 'if (response.status === 401 || response.status === 403) accountExpired();' in js
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
    assert 'if (app.accountOnly) { app.standings = []; renderStandings(); return; }' in js


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
