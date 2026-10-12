"""One competition, one admission lock, latest-state WebSocket notifications.

No game-specific rules live here. The adapter validates configuration, while
the store persists the selected game and immutable open-competition snapshot.
"""
import asyncio
from uuid import uuid4


class CompetitionConflict(ValueError):
    pass


class Competition:
    def __init__(self, store, manager):
        self.store = store
        self.manager = manager
        # Shared by configuration/open/close, match admission and submission commit.
        self.lock = asyncio.Lock()
        self.changed = asyncio.Condition()
        self.revision = 0
        self.server_id = uuid4().hex

    def get_state(self):
        state = self.store.get_competition()
        pending = len(self.manager.live)  # Includes bot cleanup, not just visible status.
        phase = "open" if state["competition_locked"] else "draining" if pending else "setup"
        return {**state, "phase": phase, "pending_matches": pending,
                "can_edit": phase == "setup", "rules": state["active_rules_snapshot"]
                if state["competition_locked"] else self.store.get_rules(state["selected_game_id"]),
                "revision": self.revision, "server_id": self.server_id}

    def require_editable(self):
        if self.store.competition_locked:
            raise CompetitionConflict("Cuộc thi đã khóa. Hãy đóng cuộc thi trước khi sửa game hoặc luật.")
        if self.manager.live:
            raise CompetitionConflict("Còn trận đang chạy/chờ hoặc bot đang được thu hồi. Hãy đợi hoặc hủy trận hợp lệ.")

    async def publish(self):
        async with self.changed:
            self.revision += 1
            self.changed.notify_all()

    async def open(self):
        async with self.lock:
            self.require_editable()
            await asyncio.to_thread(self.store.open_competition)
            await self.publish()
            return self.get_state()

    async def close(self):
        async with self.lock:
            # Closing admission is immediate; existing matches retain their snapshots.
            await asyncio.to_thread(self.store.close_competition)
            await self.publish()
            return self.get_state()
