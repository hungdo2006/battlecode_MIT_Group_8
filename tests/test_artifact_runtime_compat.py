"""Old sandbox artifacts must not be advertised or dispatched as runnable."""
from types import SimpleNamespace

from backend.artifact_compat import artifact_current, public_bot_status


CURRENT = "sha256:" + "a" * 64
OLD = "sha256:" + "b" * 64


def _store(image=CURRENT):
    return SimpleNamespace(sandbox_image_for_game=lambda game: image)


def _bot(image=CURRENT, game="ott_v2"):
    return {"status": "ready", "game_id": game, "image": image}


def test_unchanged_compiled_bot_still_ready():
    bot = _bot()
    assert artifact_current(_store(), bot)
    assert public_bot_status(_store(), bot) == "ready"
    assert bot["status"] == "ready"


def test_outdated_compilation_needs_resubmission_without_mutating_history():
    bot = _bot(OLD)
    assert not artifact_current(_store(), bot)
    assert public_bot_status(_store(), bot) == "needs_rebuild"
    assert bot["status"] == "ready"  # Original immutable submission is retained.


def test_missing_image_metadata_and_unavailable_runner_fail_closed():
    assert not artifact_current(_store(), _bot(image=None))
    assert not artifact_current(_store(None), _bot())
    assert public_bot_status(_store(None), _bot()) == "needs_rebuild"


def test_recompiled_bot_with_new_image_becomes_eligible():
    old_bot = _bot(OLD)
    new_bot = _bot(CURRENT)
    assert not artifact_current(_store(), old_bot)
    assert artifact_current(_store(), new_bot)


def test_runtime_identity_is_game_specific_and_backend_only():
    bot = _bot(game="battlecode26")
    store = SimpleNamespace(
        sandbox_image_for_game=lambda game: CURRENT if game == "battlecode26" else OLD
    )
    assert artifact_current(store, bot)
    assert not artifact_current(store, _bot(game="ott_v2"))


def test_legacy_non_sandbox_store_without_controller_identity_is_unchanged():
    assert artifact_current(SimpleNamespace(), _bot())
    assert public_bot_status(SimpleNamespace(), _bot()) == "ready"


def test_failed_compile_is_not_mislabeled_as_expired():
    bot = _bot(OLD)
    bot["status"] = "error"
    assert not artifact_current(_store(), bot)
    assert public_bot_status(_store(), bot) == "error"


def test_integration_guards_use_the_same_compatibility_predicate():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    paths = ("backend/bot_service.py", "backend/scrimmage_service.py",
             "backend/official_service.py", "backend/matches.py")
    for path in paths:
        text = (root / path).read_text(encoding="utf-8")
        assert "artifact_current(" in text, path
    controller = (root / "sandbox_controller/service.py").read_text(encoding="utf-8")
    assert "'sandbox_image': app.state.controller.engine.image" in controller
    assert "'battlecode_image': getattr(app.state.controller.engine, 'battlecode_image', None)" in controller
