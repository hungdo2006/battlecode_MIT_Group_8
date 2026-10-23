"""System operator dashboard: status is readable without hiding diagnostics."""
from html.parser import HTMLParser
from pathlib import Path


FRONTEND = Path(__file__).resolve().parents[1] / "frontend"


class Ids(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.details = []
        self.controls = []

    def handle_starttag(self, tag, attrs):
        props = dict(attrs)
        if props.get("id"):
            self.ids.append(props["id"])
            if tag == "details":
                self.details.append(props["id"])
        if props.get("href"):
            self.controls.append(props["href"])


def test_system_dashboard_explains_health_and_workload():
    source = (FRONTEND / "index.html").read_text(encoding="utf-8")
    parser = Ids()
    parser.feed(source)
    assert len(parser.ids) == len(set(parser.ids))
    for selector_id in (
        "system-health", "system-health-title", "system-health-note",
        "system-last-checked", "system-refresh", "system-status",
        "system-technical", "system-active", "system-interruptions",
    ):
        assert selector_id in parser.ids
    assert "system-technical-details" in parser.details
    assert "#official" in parser.controls
    assert "Trạng thái hệ thống" in source
    assert "Battlecode 2026 không bắt buộc" in source


def test_system_dashboard_uses_existing_admin_authorized_api():
    source = (FRONTEND / "app.js").read_text(encoding="utf-8")
    rendering = source.split("async function refreshSystem(){", 1)[1].split(
        'async function refreshSeasons(){', 1
    )[0]
    assert 'app.accountAudience !== "admin"' in rendering
    assert 'api("/api/admin/system")' in rendering
    assert 'snapshot.runner.ready' in rendering
    assert 'snapshot.active_matches.length' in rendering
    assert 'snapshot.scrimmages.QUEUED' in rendering
    assert 'snapshot.official.SCHEDULED' in rendering
    assert 'snapshot.official.LOCKED' in rendering
    assert '"#system-health"' in rendering
    assert 'system-technical' in rendering
    assert 'snapshot.runner.battlecode26' in rendering
    assert "Dữ liệu nhận lúc" in rendering
    assert "CPU" not in rendering and "RAM" not in rendering


def test_system_dashboard_responsive_and_collapsible():
    source = (FRONTEND / "styles.css").read_text(encoding="utf-8")
    assert '.system-health[data-status="ready"]' in source
    assert '.system-health[data-status="warning"]' in source
    assert '.system-advanced' in source
    assert '@media (max-width: 560px)' in source
