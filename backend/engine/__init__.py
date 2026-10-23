from .registry import GameRegistry
import os


def create_registry() -> GameRegistry:
    """Installation entry point. Core never imports game implementations."""
    from .robot import RobotBattleAdapter
    from .ott import OTTAdapter
    registry = GameRegistry()
    registry.register(RobotBattleAdapter())
    registry.register(OTTAdapter())
    from .ott_advanced import OTTAdvancedAdapter
    registry.register(OTTAdvancedAdapter())
    if os.environ.get("ARENA_BATTLECODE26") == "1":
        from .battlecode import BattlecodeAdapter
        registry.register(BattlecodeAdapter())
    return registry
