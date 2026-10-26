"""UX navigation remains task based without changing server-side permissions."""
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "frontend"


class Audit(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.view_links = []
        self.view_sections = []
        self.hrefs = []
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            self.ids.append(a["id"])
            if a["id"].startswith("view-"):
                self.view_sections.append(a["id"].removeprefix("view-"))
        if tag == "a":
            if "data-view" in a:
                self.view_links.append(a["data-view"])
            self.hrefs.append(a.get("href", ""))


def test_navigation_is_unique_and_all_links_reach_existing_views():
    parser = Audit()
    parser.feed((ROOT / "index.html").read_text(encoding="utf-8"))
    assert len(parser.ids) == len(set(parser.ids))
    assert len(parser.view_links) == len(set(parser.view_links))
    assert set(parser.view_links) <= set(parser.view_sections)
    for view in ("home", "upload", "tournaments", "administration", "official",
                 "standings", "watch", "seasons", "rules", "system"):
        assert view in parser.view_links
    assert "nav-advanced" in parser.ids
    assert "player-setup-journey" in parser.ids
    assert "admin-tournament-journey" in parser.ids
    assert "player-tournament-signup" in parser.ids
    assert "#seasons" in parser.hrefs


def test_guided_actions_have_controls_and_do_not_mutate_backend_roles():
    script = (ROOT / "app.js").read_text(encoding="utf-8")
    assert "function renderPlayerJourney()" in script
    assert "function renderAdminTournamentJourney()" in script
    assert 'app.accountAudience !== "player"' in script
    assert 'app.accountAudience !== "admin"' in script
    assert '"#account-team-activate"' in script
    assert '"#team-tournament-admin-panel"' in script
    assert '"#player-tournament-signup"' in script
    assert "Game mặc định" in script
    # UX journey cannot unilaterally activate Team or select bot; the real
    # server endpoints still require Captain permissions.
    player = script.split("function renderPlayerJourney() {", 1)[1].split(
        "function renderAdminTournamentJourney()", 1)[0]
    assert '"/api/player/active-bot"' not in player
    assert '"/activate"' not in player


def test_guided_layout_is_responsive():
    css = (ROOT / "styles.css").read_text(encoding="utf-8")
    assert ".nav-advanced" in css
    assert ".journey-steps" in css
    assert "@media(max-width:480px)" in css
    assert ".tournament-signup-shortcut" in css

def test_default_game_config_is_absent_from_account_only_navigation():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "app.js").read_text(encoding="utf-8")
    assert 'class="nav-item hidden" href="#rules" data-view="rules"' in html
    assert '''$('.nav-item[data-view="rules"]').classList.toggle("hidden", app.accountOnly);''' in js
    assert 'view === "rules" || view === "create"' in js
    overview = js.split("function renderWorkspaceOverview() {", 1)[1].split("function renderPlayerJourney()", 1)[0]
    assert '["rules",' not in overview
    assert '["tournaments", "Giải đấu"' in overview
    # Maintain the legacy rules view and engine configuration for backwards compatibility.
    assert 'id="view-rules"' in html
