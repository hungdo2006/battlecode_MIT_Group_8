"""Replay timestamps and schedule epochs share a display formatter."""
from pathlib import Path
import subprocess


def test_official_datetime_accepts_replay_iso_and_schedule_epoch():
    root = Path(__file__).resolve().parents[1]
    script = r'''
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('frontend/app.js', 'utf8');
const code = source.match(/^function officialDateTime\([^)]*\) \{[\s\S]*?^\}/m)[0];
const format = vm.runInNewContext(code + '\nofficialDateTime');
const instant = '2026-10-24T05:00:00+00:00';
const seconds = Date.parse(instant) / 1000;
const expected = new Date(instant).toLocaleString('vi-VN');
assert.equal(format(seconds), expected);
assert.equal(format(String(seconds)), expected);
assert.equal(format(instant), expected);
assert.equal(format('2026-10-24T12:00:00+07:00'), expected);
assert.equal(format(seconds + 0.5), new Date(seconds * 1000 + 500).toLocaleString('vi-VN'));
assert.equal(format('invalid QA timestamp'), '\u2014');
assert.equal(format(null), '\u2014');
assert.equal(format(undefined), '\u2014');
assert.equal(format(''), '\u2014');
assert.equal(format(NaN), '\u2014');
'''
    result = subprocess.run(['node', '-e', script], cwd=root,
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
