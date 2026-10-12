from abc import ABC, abstractmethod
from typing import Any
from copy import deepcopy

from pydantic import BaseModel


class InvalidAction(ValueError):
    pass


class GameAdapter(ABC):
    """Pure JSON state interface used by tournament core, with no subprocess/HTTP.

    apply_action receives a player->action mapping: simultaneous games ask both
    players, alternating games ask only the active player. An empty mapping can
    advance an automatic phase, such as starting the next round.
    """
    rules_model: type[BaseModel]
    metadata: dict
    samples: dict = {}

    def get_metadata(self) -> dict:
        return deepcopy(self.metadata)

    def get_rules_schema(self) -> dict:
        return self.rules_model.model_json_schema()

    def validate_rules(self, rules: dict | None = None) -> dict:
        return self.rules_model.model_validate({} if rules is None else rules).model_dump()

    @abstractmethod
    def create_initial_state(self, rules: dict) -> dict: ...

    @abstractmethod
    def get_observation(self, state: dict, player: str) -> dict: ...

    @abstractmethod
    def validate_action(self, state: dict, player: str, action: Any) -> dict: ...

    @abstractmethod
    def apply_action(self, state: dict, actions: dict[str, dict]) -> dict: ...

    @abstractmethod
    def get_players_to_act(self, state: dict) -> tuple[str, ...]: ...

    def is_game_over(self, state: dict) -> bool:
        return state["result"] is not None

    def get_result(self, state: dict) -> dict | None:
        return deepcopy(state["result"])

    def serialize_state(self, state: dict) -> dict:
        return deepcopy(state)

    def forfeit(self, state: dict, faults: dict[str, str]) -> dict:
        next_state = self.serialize_state(state)
        if self.is_game_over(next_state):
            return next_state
        next_state["turn"] += 1
        next_state["actions"] = {}
        next_state["events"] = [{"type": "fault", "player": p, "message": msg} for p, msg in faults.items()]
        next_state["result"] = {"winner": None if len(faults) == 2 else ("B" if "A" in faults else "A"),
                                "reason": "bot_error", "faults": deepcopy(faults)}
        return next_state


class GameEngine(ABC):
    """Internal legacy robot engine, retained for its focused unit tests.

    Tournament core uses GameAdapter above; this implementation is wrapped by
    RobotBattleAdapter so the existing robot rules do not need to be rewritten.
    """

    @abstractmethod
    def observation(self, player: str) -> dict[str, Any]: ...

    @abstractmethod
    def validate_action(self, action: Any) -> dict[str, Any]: ...

    @abstractmethod
    def step(self, actions: dict[str, dict]) -> dict: ...

    @abstractmethod
    def snapshot(self) -> dict: ...

    @abstractmethod
    def forfeit(self, faults: dict[str, str]) -> dict: ...

    @property
    @abstractmethod
    def finished(self) -> bool: ...
