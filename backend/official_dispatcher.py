"""Single-process, fail-closed Official Match dispatcher.

The SQLite claim is committed before any runner side effect. Restart never
reissues a claimed match, even when the underlying JSON record is missing.
"""
import asyncio
import logging
from contextlib import nullcontext

from .models import MatchRequest
from .official_service import OfficialSchedule

log = logging.getLogger(__name__)


class OfficialDispatcher:
    def __init__(self, runtime, writer, store, registry, manager):
        self.runtime = runtime
        self.writer = writer
        self.store = store
        self.registry = registry
        self.manager = manager

    def _service(self, auth, conn):
        return OfficialSchedule(conn, self.writer, auth, self.store, self.registry)

    async def recover(self):
        return await self.runtime.run(lambda auth, conn:
            self._service(auth, conn).recover_uncertain())

    async def tick(self):
        await self.runtime.run(lambda auth, conn:
            self._service(auth, conn).sync_execution())
        gate = getattr(self.manager, "runner_control", None)
        if gate and gate.closed:
            return
        with gate.operation() if gate else nullcontext():
            await self._dispatch()

    async def _dispatch(self):
        await self.runtime.run(lambda auth, conn:
            self._service(auth, conn).freeze_due())
        await self.runtime.run(lambda auth, conn:
            self._service(auth, conn).sync_execution())
        # No implicit legacy fallback: Official Matches run only in sandbox.
        if getattr(self.manager.runner, "mode", None) != "sandbox":
            return
        status = await asyncio.to_thread(self.manager.runner.health)
        if not status.get("ready"):
            return
        # No more than two concurrent matches across the entire MatchManager.
        # Failed/malformed locked requests are blocked individually.
        for _ in range(16):
            if len(self.manager.live) >= 2:
                break
            plan = await self.runtime.run(lambda auth, conn:
                self._service(auth, conn).claim_due())
            if not plan:
                break
            if "blocked" in plan:
                continue
            try:
                await self.manager.start(
                    MatchRequest(game_id=plan["game_id"],
                                 bot_a=plan["slots"]["A"]["bot_id"],
                                 bot_b=plan["slots"]["B"]["bot_id"]),
                    created_by={"kind":"OFFICIAL","request_id":plan["id"]},
                    official=plan)
            except Exception:
                log.exception("Official dispatch failed for %s", plan["id"])
                await self.runtime.run(lambda auth, conn:
                    self._service(auth, conn).dispatch_failed(plan["id"]))
            else:
                await self.runtime.run(lambda auth, conn:
                    self._service(auth, conn).sync_execution())
        await self.runtime.run(lambda auth, conn:
            self._service(auth, conn).sync_execution())
