"""Exercise the actual logout function with deterministic HTTP failure results."""
import json
from pathlib import Path
import subprocess

import pytest


@pytest.mark.parametrize("outcome", ["503", "network", "unconfirmed", "401", "success"])
def test_logout_requires_confirmed_revocation(outcome):
    source = (Path(__file__).resolve().parents[1] / "frontend/app.js").read_text(encoding="utf-8")
    start = source.index("async function accountLogout() {")
    logout = source[start:source.index('\n$("#session-form")', start)]
    harness = r'''
const assert = require('node:assert/strict');
const outcome = OUTCOME;
const app = {accountAudience: 'admin', account: {id: 'admin'}, participant: {},
  role: 'organizer', organizerAvailable: true, csrf: 'csrf', initialized: true};
let dialog = null, errorToast = null, attempts = 0, closes = 0;
app.competitionSocket = app.socket = {close() { closes++; }};
function renderSession() {}
function showAccountDialog(message) { dialog = message; }
function toast(message, error) { errorToast = {message, error}; }
function jsonOptions() { return {}; }
function accountExpired() { app.account = null; app.accountAudience = null; }
async function api() {
  attempts++;
  if (attempts > 1 || outcome === 'success') return {logged_out: true};
  if (outcome === 'unconfirmed') return {};
  throw Object.assign(new Error(outcome), {status: outcome === '401' ? 401 : outcome === '503' ? 503 : undefined});
}
LOGOUT
(async () => {
  await accountLogout();
  assert.equal(app.logoutBusy, false);
  if (['503', 'network', 'unconfirmed'].includes(outcome)) {
    assert.equal(app.account.id, 'admin');
    assert.equal(app.accountAudience, 'admin');
    assert.equal(app.logoutError, true);
    assert.equal(dialog, null);
    assert.equal(closes, 0);
    assert.equal(errorToast.error, true);
    assert.match(errorToast.message, /Chưa xác nhận đăng xuất/);
    await accountLogout(); // The same session can retry after connectivity returns.
    assert.equal(attempts, 2);
    assert.equal(app.account, null);
    assert.equal(dialog, 'Đã đăng xuất an toàn.');
  } else if (outcome === '401') {
    assert.equal(app.account, null);
    assert.equal(dialog, 'Phiên đã hết hiệu lực. Hãy đăng nhập lại.');
    assert.equal(errorToast, null);
  } else {
    assert.equal(app.account, null);
    assert.equal(app.role, 'player');
    assert.equal(dialog, 'Đã đăng xuất an toàn.');
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
'''.replace("OUTCOME", json.dumps(outcome)).replace("LOGOUT", logout)
    result = subprocess.run(["node", "-"], input=harness, text=True, encoding="utf-8",
                            capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr
