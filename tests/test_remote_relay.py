"""B1 mailboxes fail closed for disconnects, replayed responses and invalid RPCs."""
from concurrent.futures import ThreadPoolExecutor
import time

import pytest

from backend.execution import RunnerUnavailable
from backend.remote_relay import RemoteRelay, STALE_AFTER


def test_one_outbound_agent_routes_controller_reply_and_disallows_replay():
    relay = RemoteRelay()
    session = relay.connect()
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = pool.submit(relay.call, "/health", timeout=2)
        task = relay.poll(session, timeout=1)
        assert task["path"] == "/health" and task["payload"] is None
        relay.respond(session, task["id"], 200, {"ready": True, "epoch": "e1"})
        assert pending.result(timeout=3) == (200, {"ready": True, "epoch": "e1"})
        with pytest.raises(ValueError, match="duplicate|unknown"):
            relay.respond(session, task["id"], 200, {"ready": False})
    relay.shutdown()


def test_existing_live_agent_cannot_be_superseded():
    relay = RemoteRelay()
    first = relay.connect()
    with pytest.raises(ValueError, match="already connected"):
        relay.connect()
    relay.disconnect(first)
    second = relay.connect()
    assert second != first
    with pytest.raises(ValueError, match="session"):
        relay.poll(first, timeout=0)
    relay.shutdown()


def test_disconnection_interrupts_pending_and_blocks_stale_results():
    relay = RemoteRelay()
    session = relay.connect()
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = pool.submit(relay.call, "/runtime/a-1/request",
                              {"observation": {"turn": 1}}, timeout=4)
        task = relay.poll(session, timeout=1)
        assert task["path"] == "/runtime/a-1/request"
        relay.disconnect(session)
        with pytest.raises(RunnerUnavailable, match="disconnected"):
            pending.result(timeout=2)
        with pytest.raises(ValueError, match="session"):
            relay.respond(session, task["id"], 200, {"action": {"type": "wait"}})
    with pytest.raises(RunnerUnavailable, match="not connected"):
        relay.call("/health", timeout=1)
    relay.shutdown()


def test_offline_worker_never_dispatches_and_stale_session_can_be_replaced():
    relay = RemoteRelay()
    with pytest.raises(RunnerUnavailable, match="not connected"):
        relay.call("/health", timeout=0)
    old = relay.connect()
    with relay.cv:
        relay.last_poll = time.monotonic() - STALE_AFTER - 1
    assert not relay.connected()
    new = relay.connect()
    assert new != old
    relay.shutdown()


@pytest.mark.parametrize("path", [
    "/../../../etc/passwd", "http://evil.test/health",
    "/health?token=leak", "/admin", "/runtime/a;rm",
    "/compile/" + "x" * 500,
])
def test_rpc_allowlist_denies_unsafe_paths(path):
    relay = RemoteRelay()
    relay.connect()
    with pytest.raises(ValueError, match="allowlisted"):
        relay.call(path, {}, timeout=0)
    relay.shutdown()


def test_bounded_queue_and_bad_response_rejected():
    relay = RemoteRelay()
    session = relay.connect()
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = pool.submit(relay.call, "/heartbeat", {}, timeout=4)
        task = relay.poll(session, timeout=1)
        with pytest.raises(ValueError):
            relay.respond(session, task["id"], 200, ["not an object"])
        with pytest.raises(ValueError):
            relay.respond(session, task["id"], 201, {"unexpected": True})
        relay.respond(session, task["id"], 409, {"detail": "lease invalid"})
        assert pending.result(timeout=2)[0] == 409
    relay.shutdown()
