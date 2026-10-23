"""Scrimmage UX is guided, while server-side matchmaking stays authoritative."""
from html.parser import HTMLParser
from pathlib import Path


FRONTEND = Path(__file__).resolve().parents[1] / "frontend"


class Audit(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.links = []
        self.details = []
    def handle_starttag(self, tag, attrs):
        args = dict(attrs)
        if "id" in args:
            self.ids.append(args["id"])
        if tag == "a":
            self.links.append(args.get("href", ""))
        if tag == "details":
            self.details.append(args.get("id", ""))


def test_practice_screen_exposes_guidance_and_live_actions():
    doc = (FRONTEND / "index.html").read_text(encoding="utf-8")
    parser = Audit()
    parser.feed(doc)
    assert len(parser.ids) == len(set(parser.ids))
    expected = [
        "view-scrimmage", "scrimmage-create-panel", "practice-state",
        "practice-state-title", "scrimmage-eligibility", "scrimmage-game",
        "matchmaking-state", "matchmaking-detail", "matchmaking-clock",
        "matchmaking-cancel", "matchmaking-watch", "scrimmage-bot-link",
        "practice-match-filter", "scrimmage-list", "refresh-scrimmages"
    ]
    assert all(key in parser.ids for key in expected)
    assert "Không tính điểm giải đấu" in doc
    assert "Tối đa 5 phút" in doc
    assert "Chọn trò chơi" in doc
    assert "Tìm đối thủ" in doc
    assert "Xem trận" in doc


def test_practice_state_is_driven_by_real_matchmaking_api():
    js = (FRONTEND / "app.js").read_text(encoding="utf-8")
    status = js.split("function renderMatchmaking() {", 1)[1].split(
        "\nfunction updateMatchmakingClock()", 1
    )[0]
    assert 'const pending=["SEARCHING","MATCHED","RUNNING"].includes(state);' in status
    assert 'app.team?.my_role==="CAPTAIN"' in status
    assert 'data.can_search && !pending' in status
    assert 'ready' in status and 'searching' in status and 'playing' in status
    assert 'data.ready_bot' in status
    assert 'search?.request?.match_id' in status
    assert 'team.status!=="ACTIVE"' in status
    assert 'workspaceLink("upload",{focus:"bots"})' in status
    assert 'app.matchmaking=null' in js  # Changing game clears stale state.
    assert '"/api/player/matchmaking/find"' in js
    assert "/api/player/matchmaking?game_id=" in js
    assert '"/cancel"' not in status  # No mutations in view rendering.


def test_practice_history_filter_is_frontend_only():
    js = (FRONTEND / "app.js").read_text(encoding="utf-8")
    code = js.split("function renderPracticeHistory() {", 1)[1].split(
        '$("#scrimmage-create").addEventListener', 1
    )[0]
    assert 'filter==="active"' in code
    assert 'filter==="done"' in code
    assert 'renderPracticeRows($("#scrimmage-list"),entries)' in code
    assert 'app.scrimmages.filter(' in code
    assert '/api/' not in code


def test_responsive_practice_layout():
    css = (FRONTEND / "styles.css").read_text(encoding="utf-8")
    assert ".practice-workspace" in css
    assert ".practice-state" in css
    assert ".practice-flow" in css
    assert "@media (max-width: 480px)" in css
