"""Account-Only frontend regressions and platform-independent fingerprints."""
from pathlib import Path
from scripts import version_frontend

ROOT = Path(__file__).resolve().parent.parent


def test_account_only_permissions_operate_on_node_lists():
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    assert '$$(".player-only, [data-go=upload]' in js
    assert '$$(".nav-item[data-view=upload], #view-upload .two-column' in js
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
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    assert version_frontend.versioned_html(html) == html
