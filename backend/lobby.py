"""Small server-owned lobby; all mutations share Competition.lock.

Identity comes from the existing cookie. Presence is memory-only, submissions
are immutable, and pending invitations are cancelled on restart, never resumed.
"""
import asyncio
import logging
import time
from copy import deepcopy
from uuid import uuid4

from fastapi import HTTPException

from backend.models import MatchRequest
from backend.storage import Store
from backend.tournament_draws import apply_match_result, current_round_for_scheduling

PENDING = {"PENDING", "PARTIALLY_ACCEPTED"}
TERMINAL_MATCH = {"completed", "interrupted"}
logger = logging.getLogger(__name__)


class Lobby:
    invitation_seconds = 60
    heartbeat_seconds = 35

    def __init__(self, store, sessions, manager, competition):
        self.store, self.sessions = store, sessions
        self.manager, self.control = manager, competition
        self.player_path = store.data / "players.json"
        self.invitation_path = store.data / "invitations.json"
        self.players = Store._read(self.player_path, {})
        self.invitations = Store._read(self.invitation_path, {})
        self.connections = {}  # player_id -> {connection_id: monotonic last heartbeat}
        self.wakeup = asyncio.Event()
        self.stopping = False
        linked_matches = {m.get("invitation_id"): m for m in store.get_matches() if m.get("invitation_id")}
        for invitation in self.invitations.values():
            linked = linked_matches.get(invitation["id"])
            if linked:
                # A crash between match save and invitation save still consumes
                # the invitation; never create a second match after restart.
                invitation.update(status="STARTED", match_id=linked["id"], finished=True,
                                  result=linked["result"], match_status=linked["status"])
            elif invitation["status"] in PENDING | {"ACCEPTED"}:
                invitation.update(status="CANCELLED", reason="server_restart")
        Store._write(self.invitation_path, self.invitations)
        self.worker = asyncio.create_task(self._maintain(), name="lobby-maintenance")

    def role(self, player_id):
        for key, record in self.sessions.records.items():
            if record["participant"]["id"] == player_id:
                return self.sessions.role(key)
        return "player"

    def identity(self, player_id):
        return next((deepcopy(r["participant"]) for r in self.sessions.records.values()
                     if r["participant"]["id"] == player_id), None)

    def remember(self, participant):
        if participant and participant["id"] not in self.players:
            self.players[participant["id"]] = {"active_bot_id": None, "last_match_id": None}
            Store._write(self.player_path, self.players)

    def reservation(self, player_id):
        for inv in reversed(list(self.invitations.values())):
            if player_id not in inv["player_ids"]:
                continue
            if inv["status"] in PENDING:
                return inv
            if inv["status"] == "STARTED" and inv.get("match_id") in self.manager.live:
                return inv
        return None

    def is_online(self, player_id):
        return self.role(player_id) == "player" and any(
            time.monotonic() - last < self.heartbeat_seconds
            for last in self.connections.get(player_id, {}).values())

    def active_bot(self, player_id):
        bot = self.store.get_bot(self.players.get(player_id, {}).get("active_bot_id"))
        if (bot and bot["status"] == "ready" and bot.get("owner", {}).get("id") == player_id
                and bot["game_id"] == self.store.selected_game_id):
            return {k: deepcopy(bot[k]) for k in ("id", "name", "language", "game_id", "created_at")}
        return None

    def player(self, player_id):
        identity = self.identity(player_id)
        if not identity:
            return None
        online, active = self.is_online(player_id), self.active_bot(player_id)
        reserved = self.reservation(player_id)
        state = ("OFFLINE" if not online else "IN_MATCH" if reserved and reserved["status"] == "STARTED"
                 else "INVITED" if reserved else "READY" if active else "ONLINE")
        return {"player_id": player_id, "nickname": identity["name"],
                "display_name": f"{identity['name']} · {player_id[:6].upper()}",
                "online": online, "status": state, "active_bot": active,
                "active_bot_id": active["id"] if active else None,
                "invitation_id": reserved["id"] if reserved else None,
                "current_match_id": reserved.get("match_id") if reserved else None,
                "last_match_id": self.players.get(player_id, {}).get("last_match_id")}

    def delete_player(self, player_id):
        if player_id not in self.players or self.role(player_id) != "player":
            return False
        if any(tournament.get("status") in {"registration", "active"}
               and any(player.get("player_id") == player_id
                       for player in tournament.get("participants", []))
               for tournament in self.store.get_tournaments()):
            raise HTTPException(409, "Không thể xóa Player đang tham gia một giải chưa kết thúc.")
        if self.reservation(player_id) or any(
            match.meta.get("player_a_id") == player_id or match.meta.get("player_b_id") == player_id
            for match in self.manager.live.values()
        ):
            raise HTTPException(409, "Không thể xóa Player đang có lời mời hoặc trận đấu chưa kết thúc.")

        # Revoke every browser session for this identity and remove its lobby
        # profile together. Historical matches keep their saved name snapshots.
        with self.sessions.lock:
            previous_players = deepcopy(self.players)
            previous_sessions = deepcopy(self.sessions.records)
            previous_organizers = set(self.sessions.organizers)
            previous_connections = deepcopy(self.connections.get(player_id, {}))
            session_keys = [
                key for key, record in self.sessions.records.items()
                if record["participant"]["id"] == player_id
            ]
            self.players.pop(player_id, None)
            self.sessions.records = {
                key: record for key, record in self.sessions.records.items()
                if key not in session_keys
            }
            self.sessions.organizers.difference_update(session_keys)
            self.connections.pop(player_id, None)
            try:
                Store._write(self.player_path, self.players)
                Store._write(self.sessions.path, self.sessions.records)
            except Exception:
                self.players = previous_players
                self.sessions.records = previous_sessions
                self.sessions.organizers = previous_organizers
                self.connections[player_id] = previous_connections
                try:
                    Store._write(self.player_path, self.players)
                    Store._write(self.sessions.path, self.sessions.records)
                except Exception:
                    logger.exception("Failed to roll back player deletion for %s", player_id)
                raise
        return True

    def snapshot(self, participant, role):
        player_id = participant["id"] if participant else None
        players = [self.player(pid) for pid in self.players if self.role(pid) == "player"]
        invitations = [deepcopy(inv) for inv in reversed(list(self.invitations.values()))
                       if role == "organizer" or player_id in inv["player_ids"]]
        # Full current state repairs missed events after reconnect; no accept is implicit.
        return {"players": [p for p in players if p], "me": self.player(player_id) if player_id else None,
                "invitations": invitations[:100], "server_time": time.time()}

    async def connect(self, participant):
        async with self.control.lock:
            self.remember(participant)
            connection_id = uuid4().hex
            self.connections.setdefault(participant["id"], {})[connection_id] = time.monotonic()
            await self.control.publish()
            return connection_id

    async def heartbeat(self, player_id, connection_id):
        async with self.control.lock:
            was_online = self.is_online(player_id)
            self.connections.setdefault(player_id, {})[connection_id] = time.monotonic()
            if not was_online:
                await self.control.publish()

    async def disconnect(self, player_id, connection_id):
        async with self.control.lock:
            self.connections.get(player_id, {}).pop(connection_id, None)
            await self.control.publish()

    async def activity(self):
        # Called even during start/cancel under admission lock. Never acquire that
        # lock here: maintenance reconciles completion after runner cleanup.
        self.wakeup.set()
        await self.control.publish()

    def set_active(self, participant, bot_id):
        player_id = participant["id"]
        self.remember(participant)
        reserved = self.reservation(player_id)
        if reserved and (reserved["status"] == "STARTED" or reserved["responses"][player_id] == "ACCEPTED"):
            raise HTTPException(409, "Active Bot đã chốt; đợi trận kết thúc hoặc lời mời bị hủy.")
        bot = self.store.get_bot(bot_id)
        if not bot or bot.get("owner", {}).get("id") != player_id:
            raise HTTPException(403, "Chỉ được chọn submission của chính mình.")
        if bot["status"] != "ready" or bot["game_id"] != self.store.selected_game_id:
            raise HTTPException(409, "Bot phải READY và thuộc game ban tổ chức đang chọn.")
        previous = deepcopy(self.players)
        self.players[player_id]["active_bot_id"] = bot_id
        try:
            Store._write(self.player_path, self.players)
            if reserved and reserved["status"] in PENDING:
                inv = deepcopy(reserved)
                inv["bots"][player_id] = self.active_bot(player_id)
                self.save_invitation(inv)
        except Exception:
            self.players = previous
            Store._write(self.player_path, self.players)
            raise
        return self.player(player_id)

    def save_invitation(self, invitation):
        previous = self.invitations.get(invitation["id"])
        self.invitations[invitation["id"]] = deepcopy(invitation)
        try:
            Store._write(self.invitation_path, self.invitations)
        except Exception:
            if previous is None:
                self.invitations.pop(invitation["id"], None)
            else:
                self.invitations[invitation["id"]] = previous
            raise

    def create_invitation(self, organizer, player_a, player_b, tournament_id=None, tournament_match_id=None):
        if not self.store.competition_locked:
            raise HTTPException(409, "Cuộc thi chưa OPEN.")
        if player_a == player_b:
            raise HTTPException(409, "Phải chọn hai Player khác nhau.")
        players = [self.player(pid) if pid in self.players else None for pid in (player_a, player_b)]
        if any(not p or p["status"] != "READY" for p in players):
            raise HTTPException(409, "Cả hai Player phải online, READY và chưa có lời mời/trận khác.")
        game_id = self.store.selected_game_id
        invitation = {"id": self.store.new_id(), "status": "PENDING", "player_ids": [player_a, player_b],
                      "players": {p["player_id"]: {"id": p["player_id"], "name": p["nickname"]} for p in players},
                      "bots": {p["player_id"]: p["active_bot"] for p in players},
                      "responses": {pid: "PENDING" for pid in (player_a, player_b)},
                      "organizer": deepcopy(organizer), "game_id": game_id,
                      "game_name": self.store.registry.get(game_id).get_metadata()["name"],
                      "rules_snapshot": deepcopy(self.store.active_rules_snapshot),
                      "created_at": time.time(), "expires_at": time.time() + self.invitation_seconds,
                      "match_id": None, "tournament_id": tournament_id,
                      "tournament_match_id": tournament_match_id}
        self.save_invitation(invitation)
        return deepcopy(invitation)

    def expire(self):
        changed = False
        for inv in list(self.invitations.values()):
            if inv["status"] in PENDING and time.time() >= inv["expires_at"]:
                self.save_invitation({**inv, "status": "EXPIRED", "reason": "response_timeout"})
                changed = True
        return changed

    def cancel_pending(self, reason):
        for inv in list(self.invitations.values()):
            if inv["status"] in PENDING:
                self.save_invitation({**inv, "status": "CANCELLED", "reason": reason})

    async def respond(self, invitation_id, participant, accept):
        # Caller holds Competition.lock. The second accept starts once under
        # the same lock, and repeated accept returns the existing match_id.
        self.expire()
        inv = deepcopy(self.invitations.get(invitation_id))
        if not inv:
            raise HTTPException(404, "Không tìm thấy lời mời.")
        player_id = participant["id"]
        if player_id not in inv["player_ids"]:
            raise HTTPException(403, "Bạn không thuộc lời mời này.")
        if inv["status"] == "STARTED" and accept:
            return inv
        if inv["status"] not in PENDING:
            raise HTTPException(409, f"Lời mời đã {inv['status']}.")
        if not accept:
            inv["responses"][player_id] = "DECLINED"
            inv["status"] = "DECLINED"
            self.save_invitation(inv)
            return inv
        if not self.store.competition_locked or inv["game_id"] != self.store.selected_game_id:
            raise HTTPException(409, "Cuộc thi đã đóng hoặc thay đổi.")
        if not self.is_online(player_id):
            raise HTTPException(409, "Mở kết nối website trước khi Accept.")
        if inv["responses"][player_id] != "ACCEPTED":
            bot = self.active_bot(player_id)
            if not bot:
                raise HTTPException(409, "Active Bot không còn hợp lệ.")
            inv["bots"][player_id] = bot  # Freeze this submission on accept.
            inv["responses"][player_id] = "ACCEPTED"
        inv["status"] = "PARTIALLY_ACCEPTED"
        if not all(v == "ACCEPTED" for v in inv["responses"].values()):
            self.save_invitation(inv)
            return inv
        if any(not self.is_online(pid) or not self.active_bot(pid)
               or self.active_bot(pid)["id"] != inv["bots"][pid]["id"] for pid in inv["player_ids"]):
            inv.update(status="CANCELLED", reason="player_unavailable")
            self.save_invitation(inv)
            return inv
        a, b = inv["player_ids"]
        try:
            match = await self.manager.start(
                MatchRequest(bot_a=inv["bots"][a]["id"], bot_b=inv["bots"][b]["id"], game_id=inv["game_id"]),
                created_by=inv["organizer"], participants={"A": self.identity(a), "B": self.identity(b)},
                invitation_id=inv["id"], tournament_id=inv.get("tournament_id"),
                tournament_match_id=inv.get("tournament_match_id"))
        except Exception as exc:
            inv.update(status="CANCELLED", reason="match_start_failed")
            self.save_invitation(inv)
            if isinstance(exc, ValueError):
                raise HTTPException(409, str(exc)) from exc
            raise
        inv.update(status="STARTED", match_id=match["id"])
        try:
            self.save_invitation(inv)
        except Exception:
            # Match metadata durably contains invitation_id. Keep it consumed
            # in memory too if the invitation write fails; retries return the
            # same ID, and restart recovery links it from matches.json.
            self.invitations[inv["id"]] = deepcopy(inv)
            if self.manager.get_match(match["id"])["status"] not in TERMINAL_MATCH:
                await self.manager.cancel(match["id"])
            self.wakeup.set()
            raise
        for pid in inv["player_ids"]:
            self.players[pid]["last_match_id"] = match["id"]
        Store._write(self.player_path, self.players)
        return inv

    def cancel(self, invitation_id):
        inv = self.invitations.get(invitation_id)
        if not inv:
            raise HTTPException(404, "Không tìm thấy lời mời.")
        if inv["status"] == "CANCELLED":
            return deepcopy(inv)
        if inv["status"] not in PENDING:
            raise HTTPException(409, "Chỉ hủy được lời mời chưa bắt đầu.")
        self.save_invitation({**inv, "status": "CANCELLED", "reason": "organizer_cancelled"})
        return deepcopy(self.invitations[invitation_id])

    async def _maintain(self):
        try:
            while not self.stopping:
                try:
                    await asyncio.wait_for(self.wakeup.wait(), timeout=1)
                except asyncio.TimeoutError:
                    pass
                self.wakeup.clear()
                try:
                    async with self.control.lock:
                        changed = self.expire()
                        if not self.store.competition_locked and any(i["status"] in PENDING for i in self.invitations.values()):
                            self.cancel_pending("competition_closed")
                            changed = True
                        for pid, connections in self.connections.items():
                            stale = [cid for cid, last in connections.items()
                                     if time.monotonic() - last >= self.heartbeat_seconds]
                            for cid in stale:
                                connections.pop(cid)
                            changed = changed or bool(stale)
                        for inv in list(self.invitations.values()):
                            bracket_match = None
                            if inv.get("tournament_id") and inv.get("tournament_match_id"):
                                tournament = self.store.get_tournament(inv["tournament_id"])
                                if tournament and tournament.get("status") == "active":
                                    bracket_match = next((m for r in tournament.get("rounds", [])
                                                          for m in r.get("matches", [])
                                                          if m["id"] == inv["tournament_match_id"]), None)
                                    if bracket_match and inv["status"] in {"DECLINED", "EXPIRED", "CANCELLED"} \
                                            and bracket_match.get("status") == "invited":
                                        bracket_match.update(status="needs_attention",
                                                             attention_reason=inv.get("reason", inv["status"].lower()))
                                        await asyncio.to_thread(self.store.save_tournament, tournament)
                                        changed = True
                                    if bracket_match and inv["status"] == "STARTED" \
                                            and bracket_match.get("status") == "invited":
                                        bracket_match.update(status="playing", match_id=inv.get("match_id"))
                                        await asyncio.to_thread(self.store.save_tournament, tournament)
                                        changed = True
                                    if bracket_match and inv["status"] == "STARTED" and not bracket_match.get("result"):
                                        played_match = self.manager.get_match(inv.get("match_id"))
                                        if played_match and played_match.get("status") in TERMINAL_MATCH:
                                            apply_match_result(tournament, inv["tournament_match_id"], played_match)
                                            await asyncio.to_thread(self.store.save_tournament, tournament)
                                            changed = True
                            if inv["status"] == "STARTED" and not inv.get("finished"):
                                match = self.manager.get_match(inv["match_id"])
                                if inv["match_id"] not in self.manager.live and match and match["status"] in TERMINAL_MATCH:
                                    self.save_invitation({**inv, "finished": True,
                                                          "result": match["result"], "match_status": match["status"]})
                                    changed = True
                        changed = await self._schedule_tournament_matches() or changed
                        if changed:
                            await self.control.publish()
                except Exception:
                    # Transient disk trouble must not kill expiration/presence forever.
                    logger.exception("Lobby maintenance failed; retrying on next tick")
        except asyncio.CancelledError:
            pass

    async def _schedule_tournament_matches(self):
        """Create invitations for ready tournament pairings without starting games directly."""
        if not self.store.competition_locked:
            return False
        changed = False
        active_invites = sum(1 for inv in self.invitations.values()
                             if inv.get("status") in PENDING | {"STARTED"}
                             and (inv.get("status") != "STARTED" or inv.get("match_id") in self.manager.live))
        if len(self.manager.live) + sum(1 for inv in self.invitations.values()
                                        if inv.get("status") in PENDING) >= 2:
            return False
        organizer_fallback = next((deepcopy(record["participant"]) for key, record in self.sessions.records.items()
                                   if self.sessions.role(key) == "organizer"), None)
        for tournament in self.store.get_tournaments():
            if tournament.get("status") != "active":
                continue
            organizer = tournament.get("organizer") or organizer_fallback
            if not organizer:
                continue
            if tournament.get("format") == "round_robin":
                current_round = current_round_for_scheduling(tournament)
                round_data_to_schedule = [current_round] if current_round else []
            else:
                round_data_to_schedule = tournament.get("rounds", [])
            for round_data in round_data_to_schedule:
                for match in round_data.get("matches", []):
                    if active_invites >= 2:
                        return changed
                    if match.get("status") != "pending" or not match.get("player_a") or not match.get("player_b"):
                        continue
                    a_id = match["player_a"].get("player_id")
                    b_id = match["player_b"].get("player_id")
                    if not a_id or not b_id:
                        continue
                    a, b = self.player(a_id), self.player(b_id)
                    if not a or not b or a.get("status") != "READY" or b.get("status") != "READY":
                        continue
                    try:
                        invitation = self.create_invitation(organizer, a_id, b_id,
                                                            tournament["id"], match["id"])
                    except HTTPException as exc:
                        if exc.status_code == 409:
                            continue
                        raise
                    match.update(status="invited", invitation_id=invitation["id"])
                    await asyncio.to_thread(self.store.save_tournament, tournament)
                    active_invites += 1
                    changed = True
        return changed

    async def shutdown(self):
        self.stopping = True
        self.worker.cancel()
        await asyncio.gather(self.worker, return_exceptions=True)
