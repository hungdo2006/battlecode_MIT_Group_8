"""Static safety contract for the Windows one-click local QA launcher.

Runtime Docker Desktop verification must be performed independently on Windows.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_batch_launchers_delegate_without_mutating_repository():
    start = (ROOT / "Start-NEON-ARENA-QA.bat").read_text(encoding="utf-8")
    stop = (ROOT / "Stop-NEON-ARENA-QA.bat").read_text(encoding="utf-8")
    assert 'scripts\\start_local_qa.ps1' in start
    assert 'scripts\\start_local_qa.ps1' in stop
    assert ' -Stop' in stop
    assert ' -Stop' not in start
    assert 'ExecutionPolicy Bypass' in start  # process invocation only, no policy change


def test_script_uses_isolated_project_images_and_loopback_origin():
    ps = (ROOT / "scripts" / "start_local_qa.ps1").read_text(encoding="utf-8")
    assert '$project = "neon-arena-click-qa"' in ps
    assert '"ARENA_BIND_IP=127.0.0.1"' in ps
    assert '$port = 18042' in ps
    assert '"ARENA_ACCOUNT_ONLY=1"' in ps
    assert '"ARENA_ACCOUNT_AUTH=1"' in ps
    assert '"ARENA_AUTH_ALLOW_HTTP=1"' in ps
    assert '"ARENA_AUTH_ORIGINS=$url"' in ps
    assert 'neon-arena-click-qa-bot:4.2' in ps
    assert 'neon-arena-click-qa-controller:4.2' in ps
    assert 'neon-arena-click-qa-arena:4.2' in ps
    assert 'SANDBOX_IMAGE: $botImage' in ps
    assert 'LOCALAPPDATA' in ps


def test_script_never_forces_branch_or_deletes_volumes():
    ps = (ROOT / "scripts" / "start_local_qa.ps1").read_text(encoding="utf-8")
    assert 'pull --ff-only origin main' in ps
    assert 'git -C $root pull --ff-only origin main' in ps
    assert '& git -C $root switch ' not in ps  # An error message may recommend switching manually
    assert 'Compose-Checked -Arguments @("down")' in ps
    assert 'down -v' not in ps
    assert 'down", "-v' not in ps
    assert 'reset --hard' not in ps
    assert 'git clean' not in ps
    assert 'An existing outdated/invalid schema' not in ps  # note is documentation only
    assert 'if ($dbExit -eq 15)' in ps
    assert '"migrate")' in ps
    assert 'Compose-Checked -Arguments @("run", "--rm", "--no-deps", "arena",' in ps


def test_password_stays_interactive_and_runner_token_is_random():
    ps = (ROOT / "scripts" / "start_local_qa.ps1").read_text(encoding="utf-8")
    assert 'RandomNumberGenerator' in ps
    assert 'GetBytes($buffer)' in ps
    assert 'create-admin' in ps
    assert 'the one you entered at first setup' in ps
    assert 'ARENA_RUNNER_TOKEN=$token' in ps
    assert 'password=' not in ps.lower()
