"""Reviewed game adapter registry. Never import contestant-supplied modules."""
import os
import re
from importlib.metadata import entry_points

from .base import GameAdapter
from .registry import GameRegistry


def load_approved_plugins(registry):
    """Only load preinstalled entry points explicitly approved by the operator.

    No uploaded code, package paths or arbitrary module imports from the UI.
    Packages must be installed in a reviewed server image and all plugin names
    must be listed by the operator in ARENA_APPROVED_GAME_PLUGINS.
    """
    requested = [s.strip() for s in os.environ.get("ARENA_APPROVED_GAME_PLUGINS", "").split(",") if s.strip()]
    if not requested:
        return
    if len(set(requested)) != len(requested) or len(requested) > 16 or any(
        not re.fullmatch(r"[a-z][a-z0-9_-]{0,47}", name) for name in requested
    ):
        raise ValueError("Invalid approved game plugin list")
    installed = {ep.name: ep for ep in entry_points(group="neon_arena.games")}
    for name in requested:
        entry = installed.get(name)
        if entry is None:
            raise ValueError(f"Approved game plugin is not installed: {name}")
        adapter = entry.load()()
        if not isinstance(adapter, GameAdapter):
            raise TypeError(f"Invalid reviewed game adapter: {name}")
        registry.register(adapter)


def create_registry() -> GameRegistry:
    from .robot import RobotBattleAdapter
    from .ott import OTTAdapter
    from .ott_advanced import OTTAdvancedAdapter

    registry = GameRegistry()
    registry.register(RobotBattleAdapter())
    registry.register(OTTAdapter())
    registry.register(OTTAdvancedAdapter())
    if os.environ.get("ARENA_BATTLECODE26") == "1":
        from .battlecode import BattlecodeAdapter
        registry.register(BattlecodeAdapter())
    load_approved_plugins(registry)
    return registry
