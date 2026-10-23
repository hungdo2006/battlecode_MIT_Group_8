"""Additional games require reviewed, installed, explicitly approved entry points."""
import pytest
import backend.engine as engine
from backend.engine.robot import RobotBattleAdapter


class ExampleAdapter(RobotBattleAdapter):
    metadata = {**RobotBattleAdapter.metadata, "game_id":"robot_example", "name":"Example Robot"}


class FakeEntry:
    def __init__(self):
        self.name = "school_exam"
    def load(self):
        return ExampleAdapter


def test_approved_reviewed_entrypoint_is_registered(monkeypatch):
    monkeypatch.setenv("ARENA_APPROVED_GAME_PLUGINS", "school_exam")
    monkeypatch.setattr(engine,"entry_points",lambda group: [FakeEntry()])
    registry=engine.create_registry()
    assert "robot_example" in registry.ids()
    assert "ott_v2" in registry.ids() and "ott_advanced" in registry.ids()


def test_unapproved_entrypoint_is_never_imported(monkeypatch):
    monkeypatch.delenv("ARENA_APPROVED_GAME_PLUGINS",raising=False)
    def fail(*args,**kwargs):
        raise AssertionError("Must not discover plugins until approved")
    monkeypatch.setattr(engine,"entry_points",fail)
    assert "robot_example" not in engine.create_registry().ids()


@pytest.mark.parametrize("plugins", ["missing","school_exam,school_exam","../bad","A"])
def test_invalid_plugin_configuration_fails_closed(monkeypatch,plugins):
    monkeypatch.setenv("ARENA_APPROVED_GAME_PLUGINS",plugins)
    monkeypatch.setattr(engine,"entry_points",lambda group: [FakeEntry()])
    with pytest.raises(ValueError):
        engine.create_registry()
