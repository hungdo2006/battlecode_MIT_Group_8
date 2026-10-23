"""Player practice is a list of direct challenges, not automatic matchmaking."""
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


class Audit(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []

    def handle_starttag(self, tag, attrs):
        props = dict(attrs)
        if props.get("id"):
            self.ids.append(props["id"])


def test_practice_page_lists_teams_and_a_direct_trial_action():
    html = (FRONTEND / "index.html").read_text(encoding="utf-8")
    parser = Audit()
    parser.feed(html)
    assert len(parser.ids) == len(set(parser.ids))
    expected = (
        "view-scrimmage", "scrimmage-create-panel", "scrimmage-game",
        "practice-state", "practice-state-title", "scrimmage-eligibility",
        "scrimmage-bot-link", "practice-opponents", "practice-opponent-filter",
        "practice-refresh-teams", "practice-match-filter", "scrimmage-list",
        "refresh-scrimmages",
    )
    assert set(expected) <= set(parser.ids)
    assert "Đấu thử" in html and "Danh sách đội" in html
    assert "Không cần ghép trận ngẫu nhiên" in html
    assert "Đối thủ không cần xác nhận" in html
    assert "Tối đa 5 phút" not in html
    assert "matchmaking-cancel" not in parser.ids
    assert "matchmaking-state" not in parser.ids


def test_direct_challenge_uses_existing_authorized_endpoints():
    js = (FRONTEND / "app.js").read_text(encoding="utf-8")
    practice = js.split("async function refreshPracticeOpponents() {", 1)[1].split(
        "setInterval(() => {\n  if (!document.hidden && app.accountOnly", 1
    )[0]
    assert "/api/player/scrimmage-opponents?game_id=" in practice
    assert "/api/player/active-bot?game_id=" in practice
    assert 'api("/api/player/scrimmages",jsonOptions("POST"' in practice
    assert "opponent_team_id:opponent.id" in practice
    assert 'app.team?.team?.status!=="ACTIVE"' in practice
    assert "practiceOwnBotReady" in practice
    assert "practiceFetchedGame" in practice
    assert "practiceRefreshSeq" in practice  # Ignores stale game responses.
    assert "myPending.length>=3" in practice
    assert "involved" in practice
    assert "renderPracticeHistory()" in practice
    assert "/api/player/matchmaking/find" not in js  # No automatic matcher in frontend.
    assert "/api/player/matchmaking?game_id=" not in js


def test_history_filters_and_trial_button_state():
    js = (FRONTEND / "app.js").read_text(encoding="utf-8")
    history = js.split("function renderPracticeHistory() {", 1)[1].split(
        "setInterval(() => {\n  if (!document.hidden && app.accountOnly", 1
    )[0]
    assert 'filter==="active"' in history
    assert 'filter==="done"' in history
    assert 'renderPracticeRows($("#scrimmage-list"),entries)' in history
    assert "app.scrimmages.filter(" in history
    assert '/api/' not in history


def test_direct_team_challenges_keep_existing_backend_constraints():
    service = (ROOT / "backend" / "scrimmage_service.py").read_text(encoding="utf-8")
    assert "def opponents(self, actor, game_id):" in service
    assert "def create(self, actor, game_id, opponent_id):" in service
    assert "if mine['id'] == opponent_id:" in service
    assert "count >= 3:" in service
    assert "self.frozen(team_a,game_id)" in service
    assert "self.frozen(team_b,game_id)" in service
    assert "Only queued practice matches can be cancelled" in service


def test_practice_responsive_layout():
    css = (FRONTEND / "styles.css").read_text(encoding="utf-8")
    assert ".practice-opponent-row" in css
    assert ".practice-opponent-heading" in css
    assert ".practice-opponent-list" in css
    assert "@media (max-width:480px)" in css
