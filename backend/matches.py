import asyncio
import base64
import logging
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone

from backend.engine.base import GameAdapter, InvalidAction
from backend.models import MatchRequest
from backend.runner import BotError
from backend.execution import LegacyRunner, RunnerUnavailable, Session
from backend.storage import Store
from backend.artifact_compat import artifact_current

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
    def __init__(self, store: Store, tick_seconds: float = 0.18, runner=None):
        self.runner = runner or LegacyRunner()
        self.store = store
        self.registry = store.registry
        self.tick_seconds = tick_seconds
        self.live: dict[str, LiveMatch] = {}
        self.tasks: set[asyncio.Task] = set()
        self.match_tasks: dict[str, asyncio.Task] = {}
        self.on_activity = None

    async def start(self, request: MatchRequest, created_by: dict | None = None,
                    participants: dict | None = None, invitation_id: str | None = None,
                    tournament_id: str | None = None,
                    tournament_match_id: str | None = None,
                    official: dict | None = None, scrimmage: dict | None = None) -> dict:
        if len(self.live) >= 2:
            raise ValueError("Tối đa 2 trận cùng lúc. Hãy đợi trận hiện tại kết thúc.")
        # Only the trusted server-side Official dispatcher can supply this
        # snapshot. Legacy/public match requests retain their original admission.
        if official is not None and scrimmage is not None:
            raise ValueError('A match cannot be both Official and Scrimmage')
        plan = official if official is not None else scrimmage
        if plan is None:
            game_id, rules = self.store.match_configuration(request.game_id or request.game, request.rules)
        else:
            game_id = plan["game_id"]
            if request.game_id != game_id or request.bot_a != plan["slots"]["A"]["bot_id"] or request.bot_b != plan["slots"]["B"]["bot_id"]:
                raise ValueError("Official request differs from locked slots")
            rules = deepcopy(plan["rules_snapshot"])
        bots = {"A": self.store.get_bot(request.bot_a), "B": self.store.get_bot(request.bot_b)}
        if any(not bot or bot["status"] != "ready" for bot in bots.values()):
            raise ValueError("Cả hai bot phải tồn tại và đã biên dịch thành công.")
        if plan:
            for side, bot in bots.items():
                slot = plan["slots"][side]
                if (bot.get("team_id") != slot["team_id"]
                    or bot.get("game_id") != slot["game_id"]
                    or bot.get("artifact_id") != slot["artifact_id"]
                    or bot.get("artifact_digest") != slot["artifact_digest"]):
                    raise ValueError("Frozen Official artifact changed before launch")
        adapter = self.registry.get(game_id)
        if any(bot["game_id"] != game_id for bot in bots.values()):
            raise ValueError("Cả hai submission phải thuộc game đã chọn.")
        for bot in bots.values():
            self.runner.compatible(bot)
            if not artifact_current(self.store, bot):
                raise ValueError("Bot đã biên dịch bằng Sandbox cũ. Hãy nộp lại mã nguồn và chọn bot đại diện mới.")
        rules = adapter.validate_rules(rules)
        state = adapter.create_initial_state(rules)
        metadata = adapter.get_metadata()
        match_id = ("o" + official["id"][:15]) if official else ("s" + scrimmage["id"][:15]) if scrimmage else self.store.new_id()
        if plan and (self.store.get_match(match_id) is not None or
                         (self.store.replays / f"{match_id}.jsonl").exists()):
            raise ValueError("Official match has already been published; never dispatch twice")
        meta = {"id": match_id, "game_id": game_id, "game": game_id,
                "game_name": metadata["name"], "game_version": metadata["version"],
                "status": "queued", "created_at": timestamp(),
                "created_by": deepcopy(created_by),
                "bots": {p: {"id": b["id"], "name": b["name"], "language": b["language"],
                             "owner": deepcopy(b.get("owner"))} for p, b in bots.items()},
                "rules": deepcopy(rules), "rules_snapshot": deepcopy(rules), "turn": 0, "result": None}
        meta.update(invitation_id=invitation_id, participants=deepcopy(participants), winner=None)
        meta.update(tournament_id=tournament_id, tournament_match_id=tournament_match_id)
        if official:
            meta["official_request_id"] = official["id"]
            meta["official_team_ids"] = {
                side: official["slots"][side]["team_id"] for side in ("A", "B")
            }
        if scrimmage:
            meta['scrimmage_request_id'] = scrimmage['id']
        for side, bot in bots.items():
            prefix = side.lower()
            participant = (
                {"id": plan["slots"][side]["team_id"],
                 "name": plan["slots"][side]["team_name_snapshot"]}
                if plan else (participants or {}).get(side) or bot.get("owner") or {}
            )
            meta.update({f"player_{prefix}_id": participant.get("id"),
                         f"player_{prefix}_name_snapshot": participant.get("name"),
                         f"bot_{prefix}_id": bot["id"], f"bot_{prefix}_name_snapshot": bot["name"],
                         f"bot_{prefix}_language": bot["language"]})
        live = LiveMatch(meta, adapter, state, [adapter.serialize_state(state)])
        self.live[match_id] = live
        try:
            await asyncio.to_thread(self.store.save_match, meta)
            await asyncio.to_thread(self.store.start_replay, match_id, live.frames[0])
        except Exception:
            self.live.pop(match_id, None)
            raise
        task = asyncio.create_task(self._run(live, bots), name=f"match-{match_id}")
        self.tasks.add(task)
        self.match_tasks[match_id] = task

        def cleanup(done):
            self.tasks.discard(done)
            self.match_tasks.pop(match_id, None)
            self.live.pop(match_id, None)

        task.add_done_callback(cleanup)
        if self.on_activity:
            await self.on_activity()
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
        if replay and any(not frame.get('pending_engine') for frame in replay.get('frames', [])):
            replay['frames'] = [frame for frame in replay['frames'] if not frame.get('pending_engine')]
        return {"match": match, **(replay or {"version": 1, "frames": []})}

    async def _publish_external(self, live, payload):
        frames = payload.get('frames')
        if not isinstance(frames, list) or not 1 <= len(frames) <= 6000:
            raise RunnerUnavailable('Invalid official-engine replay')
        outcome = frames[-1].get('result')
        if not isinstance(outcome, dict) or outcome.get('winner') not in ('A', 'B', None):
            raise RunnerUnavailable('Official-engine result is unavailable')
        for frame in frames:
            if frame.get('game_id') != live.meta['game_id'] or not isinstance(frame.get('turn'), int):
                raise RunnerUnavailable('Official-engine frame identity mismatch')
            frame['rules'] = deepcopy(live.meta['rules'])
            frame['max_rounds'] = payload.get('max_rounds', 0)
        raw = base64.b64decode(payload['raw_replay'], validate=True)
        if not raw.startswith(b'\x1f\x8b') or len(raw) > 8 * 1024 * 1024:
            raise RunnerUnavailable('Invalid raw official replay')
        def persist():
            with (self.store.replays / (live.meta['id'] + '.bc26')).open('xb') as stream:
                stream.write(raw)
            with self.store.lock:
                with (self.store.replays / (live.meta['id'] + '.jsonl')).open('ab') as stream:
                    for frame in frames:
                        stream.write(self.store._frame_line(frame))
        await asyncio.to_thread(persist)
        live.state = frames[-1]
        live.meta.update(turn=frames[-1]['turn'], result=outcome, winner=outcome.get('winner'),
                         status='completed', finished_at=timestamp(), raw_replay_available=True,
                         engine_commit=payload.get('engine_commit'))
        async with live.changed:
            live.frames.extend(frames)
            await asyncio.to_thread(self.store.save_match, live.meta)
            live.changed.notify_all()

    async def _publish(self, live: LiveMatch, state: dict):
        frame = live.adapter.serialize_state(state)
        # Append only the new frame; do not hold the spectator condition during disk IO.
        await asyncio.to_thread(self.store.append_replay_frame, live.meta["id"], frame)
        live.state = state
        result = live.adapter.get_result(state)
        live.meta.update(turn=frame["turn"], result=result, winner=result.get("winner") if result else None)
        if result:
            live.meta.update(status="completed", finished_at=timestamp())
        async with live.changed:
            live.frames.append(frame)
            # The complete record is written before this frame becomes visible to spectators.
            await asyncio.to_thread(self.store.save_match, live.meta)
            live.changed.notify_all()

    async def _run(self, live: LiveMatch, bots: dict):
        processes: dict[str, Session] = {}
        try:
            live.meta["status"] = "running"
            await asyncio.to_thread(self.store.save_match, live.meta)
            if getattr(live.adapter, 'whole_match', False):
                if not hasattr(self.runner, 'whole_match'):
                    raise RunnerUnavailable('Official Battlecode requires its configured sandbox')
                session = processes['engine'] = self.runner.whole_match(bots, 'bc-r-' + live.meta['id'])
                payload = await asyncio.to_thread(session.run, live.meta['rules'])
                await self._publish_external(live, payload)
                return
            faults = {}
            # Register the handle before remote startup: cancellation owns it even while Docker creates it.
            for player, bot in bots.items():
                try:
                    processes[player] = self.runner.session(bot, f"r-{live.meta['id']}-{player}")
                    await asyncio.to_thread(processes[player].start)
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
                    if isinstance(response, BotError):
                        faults[player] = str(response)
                    elif isinstance(response, BaseException):
                        raise response
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
            reason = live.meta.pop("cancel_reason", "server_shutdown")
            live.meta.update(status="interrupted", result={"winner": None, "reason": reason, "faults": {}})
            await asyncio.to_thread(self.store.save_match, live.meta)
            async with live.changed:
                live.changed.notify_all()
            raise
        except Exception as exc:
            logger.exception("Match %s failed", live.meta["id"])
            live.meta.update(status="interrupted", result={"winner": None, "reason": "runner_unavailable" if isinstance(exc, RunnerUnavailable) else "server_error", "faults": {}})
            await asyncio.to_thread(self.store.save_match, live.meta)
            async with live.changed:
                live.changed.notify_all()
        finally:
            # Shutdown can arrive after a terminal frame, while this finally is
            # already closing remote handles. Keep ownership until all closes
            # finish even when cancellation lands during cleanup.
            closing = asyncio.gather(*[asyncio.to_thread(p.close) for p in processes.values()], return_exceptions=True)
            try:
                await asyncio.shield(closing)
            except asyncio.CancelledError:
                await closing
                raise
            finally:
                self.live.pop(live.meta["id"], None)
                if self.on_activity:
                    await self.on_activity()

    async def cancel(self, match_id: str):
        task = self.match_tasks.get(match_id)
        live = self.live.get(match_id)
        if not task or not live or task.done() or live.meta["status"] not in ("queued", "running"):
            raise ValueError("Trận không còn chạy/chờ để hủy.")
        live.meta["cancel_reason"] = "organizer_cancelled"
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        # A queued task canceled before entering _run has no finally handler.
        if live.meta["status"] != "interrupted":
            live.meta.pop("cancel_reason", None)
            live.meta.update(status="interrupted", result={"winner": None, "reason": "organizer_cancelled", "faults": {}})
            await asyncio.to_thread(self.store.save_match, live.meta)
        if self.on_activity:
            await self.on_activity()
        return self.get_match(match_id)

    async def shutdown(self):
        pending = list(self.tasks)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
