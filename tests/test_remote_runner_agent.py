"""PC agent must not accept arbitrary URLs or privileged controller methods."""
from copy import deepcopy

import pytest

from remote_runner.agent import WorkerAgent


SECRET = "unit-only-worker-key-" + "x" * 42


@pytest.mark.parametrize("origin", (
    "http://arena.example.com",
    "https://arena.example.com/unsafe",
    "https://user:pass@arena.example.com",
    "https://arena.example.com?next=evil",
    "https://arena.example.com#fragment",
    "file:///etc/passwd",
    "https://",
))
def test_worker_requires_exact_verified_https_origin(origin):
    with pytest.raises(ValueError, match="HTTPS origin"):
        WorkerAgent(server_url=origin, key=SECRET)


def test_agent_forwards_only_explicit_sandbox_operations(monkeypatch):
    agent = WorkerAgent(server_url="https://arena.example.com", key=SECRET)
    calls = []

    def fake_request(url, *, payload=None, session=None, is_controller=False, timeout=15, limit=None):
        calls.append((url, payload, is_controller))
        return 200, {"action": {"type": "wait"}}

    monkeypatch.setattr(agent, "_request", fake_request)
    task = {"id": "a" * 32, "path": "/runtime/job_1/request",
            "payload": {"seq": 0, "observation": {"turn": 1}}}
    assert agent.controller(task)[0] == 200
    assert calls[0][0] == "http://controller:9000/runtime/job_1/request"
    assert calls[0][2] is True

    calls.clear()
    for forbidden in (
        "https://external.example/health", "/openapi.json",
        "/runtime/job_1/request?command=whoami",
        "/../../etc/passwd",
    ):
        changed = deepcopy(task)
        changed["path"] = forbidden
        assert agent.controller(changed)[0] == 400
    assert calls == []


def test_agent_never_executes_invalid_job_id(monkeypatch):
    agent = WorkerAgent(server_url="https://arena.example.com", key=SECRET)
    executed = []
    monkeypatch.setattr(agent, "controller", lambda task: executed.append(task))
    agent.execute({"id": "../oops", "path": "/health"}, "valid-session")
    assert executed == []
