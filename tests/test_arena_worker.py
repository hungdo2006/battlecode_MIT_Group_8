"""Arena Worker command aliases preserve the tested Compose project."""
from types import SimpleNamespace

from scripts import arena_worker


def test_worker_alias_keeps_project_and_private_config(monkeypatch, tmp_path):
    env = tmp_path / ".b1-pilot" / "worker.env"
    env.parent.mkdir()
    env.write_text("ARENA_REMOTE_RUNNER_KEY=private-test-only\n")
    monkeypatch.setattr(arena_worker, "ROOT", tmp_path)
    monkeypatch.setattr(arena_worker, "ENV", env)
    monkeypatch.setattr(arena_worker, "COMPOSE", tmp_path / "compose.remote-worker.yaml")
    called = []

    def fake_run(command, *, cwd, check):
        called.append((command, cwd, check))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(arena_worker.subprocess, "run", fake_run)
    arena_worker.main(["status"])
    arena_worker.main(["stop-agent"])
    arena_worker.main(["start"])
    assert all(command[0][:6] == ["docker", "compose", "--env-file", str(env),
                                    "-p", "neon-b1-worker"] for command in called)
    assert called[0][0][-1] == "ps"
    assert called[1][0][-2:] == ["stop", "agent"]
    assert called[2][0][-4:] == ["up", "-d", "--build", "--wait"]
