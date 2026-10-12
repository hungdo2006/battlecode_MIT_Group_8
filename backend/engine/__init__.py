from .registry import GameRegistry


def create_registry() -> GameRegistry:
    """Installation entry point. Core never imports game implementations."""
    from .robot import RobotBattleAdapter
    from .ott import OTTAdapter
    registry = GameRegistry()
    registry.register(RobotBattleAdapter())
    registry.register(OTTAdapter())
    return registry
