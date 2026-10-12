import asyncio
import logging
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from backend.engine.base import GameAdapter, InvalidAction
from backend.models import MatchRequest
from backend.runner import BotError, BotProcess
from backend.storage import Store

logger = logging.getLogger(__name__)


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class LiveMatch:
    meta: dict
    adapter: GameAdapter
    state: dict
    frames: list[dict]
    changed: asyncio.Condition = field(default_factory=asyncio.Condition)


class MatchManager:
    def __init__(self, store: Store, tick_seconds: float = 0.18):
        self.store = store
        self.registry = store.registry
        self.tick_seconds = tick_seconds
        self.live: dict[str, LiveMatch] = {}
        self.tasks: set[asyncio.Task] = set()

    async def start(self, request: MatchRequest, created_by: dict | None = None) -> dict:
        if len(self.live) >= 2:
            raise ValueError("Tối đa 2 trận cùng lúc. Hãy đợi trận hiện tại kết thúc.")
        game_id = request.game_id or request.game or self.store.selected_game_id
        adapter = self.registry.get(game_id)
        bots = {"A": self.store.get_bot(request.bot_a), "B": self.store.get_bot(request.bot_b)}
        if any(not bot or bot["status"] != "ready" for bot in bots.values()):
            raise ValueError("Cả hai bot phải tồn tại và đã biên dịch thành công.")
        if any(bot["game_id"] != game_id for bot in bots.values()):
            raise ValueError("Cả hai submission phải thuộc game đã chọn.")
        rules = adapter.validate_rules(self.store.get_rules(game_id) if request.rules is None else request.rules)
        state = adapter.create_initial_state(rules)
        metadata = adapter.get_metadata()
        match_id = self.store.new_id()
        meta = {"id": match_id, "game_id": game_id, "game": game_id,
                "game_name": metadata["name"], "game_version": metadata["version"],
                "status": "queued", "created_at": timestamp(),
                "created_by": deepcopy(created_by),
                "bots": {p: {"id": b["id"], "name": b["name"], "language": b["language"],
                             "owner": deepcopy(b.get("owner"))} for p, b in bots.items()},
                "rules": deepcopy(rules), "turn": 0, "result": None}
        live = LiveMatch(meta, adapter, state, [adapter.serialize_state(state)])
        self.live[match_id] = live
        try:
            await asyncio.to_thread(self.store.save_match, meta)
            await asyncio.to_thread(self.store.save_replay, match_id, live.frames)
        except Exception:
            self.live.pop(match_id, None)
            raise
        task = asyncio.create_task(self._run(live, bots), name=f"match-{match_id}")
        self.tasks.add(task)

        def cleanup(done):
            self.tasks.discard(done)
            self.live.pop(match_id, None)

        task.add_done_callback(cleanup)
        return deepcopy(meta)

    def get_match(self, match_id: str) -> dict | None:
        live = self.live.get(match_id)
        return deepcopy(live.meta) if live else self.store.get_match(match_id)

    def get_matches(self) -> list[dict]:
        return [self.get_match(m["id"]) for m in self.store.get_matches()]

    def get_replay(self, match_id: str) -> dict | None:
        match = self.get_match(match_id)
        if not match:
            return None
        live = self.live.get(match_id)
        replay = {"version": 1, "frames": deepcopy(live.frames)} if live else self.store.get_replay(match_id)
        return {"match": match, **(replay or {"version": 1, "frames": []})}

    async def _publish(self, live: LiveMatch, state: dict):
        live.state = state
        frame = live.adapter.serialize_state(state)
        result = live.adapter.get_result(state)
        live.meta.update(turn=frame["turn"], result=result)
        if result:
            live.meta.update(status="completed", finished_at=timestamp())
        async with live.changed:
            live.frames.append(frame)
            # Persist every turn: replay survives browser closure and server restarts.
            await asyncio.to_thread(self.store.save_replay, live.meta["id"], live.frames)
            await asyncio.to_thread(self.store.save_match, live.meta)
            live.changed.notify_all()

    async def _run(self, live: LiveMatch, bots: dict):
        processes: dict[str, BotProcess] = {}
        try:
            live.meta["status"] = "running"
            await asyncio.to_thread(self.store.save_match, live.meta)
            faults = {}
            # Launch is quick and synchronous so shutdown always owns every created process.
            for player, bot in bots.items():
                try:
                    processes[player] = BotProcess(bot["command"], Path(bot["folder"]))
                except BotError as exc:
                    faults[player] = str(exc)
            if faults:
                await self._publish(live, live.adapter.forfeit(live.state, faults))
                return
            while not live.adapter.is_game_over(live.state):
                players = live.adapter.get_players_to_act(live.state)
                responses = await asyncio.gather(*[
                    asyncio.to_thread(processes[p].request, live.adapter.get_observation(live.state, p)) for p in players
                ], return_exceptions=True)
                actions, faults = {}, {}
                for player, response in zip(players, responses):
                    if isinstance(response, BaseException):
                        faults[player] = str(response)
                    else:
                        try:
                            actions[player] = live.adapter.validate_action(live.state, player, response)
                        except InvalidAction as exc:
                            faults[player] = str(exc)
                state = (live.adapter.forfeit(live.state, faults) if faults
                         else live.adapter.apply_action(live.state, actions))
                await self._publish(live, state)
                if not live.adapter.is_game_over(live.state):
                    await asyncio.sleep(self.tick_seconds)
        except asyncio.CancelledError:
            live.meta.update(status="interrupted", result={"winner": None, "reason": "server_shutdown", "faults": {}})
            await asyncio.to_thread(self.store.save_match, live.meta)
            async with live.changed:
                live.changed.notify_all()
            raise
        except Exception:
            logger.exception("Match %s failed", live.meta["id"])
            live.meta.update(status="interrupted", result={"winner": None, "reason": "server_error", "faults": {}})
            await asyncio.to_thread(self.store.save_match, live.meta)
            async with live.changed:
                live.changed.notify_all()
        finally:
            await asyncio.gather(*[asyncio.to_thread(p.close) for p in processes.values()])

    async def shutdown(self):
        pending = list(self.tasks)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
