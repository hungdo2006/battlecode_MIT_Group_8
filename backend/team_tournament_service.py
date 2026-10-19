"""Account-only round-robin tournaments for active Teams."""
from __future__ import annotations

import json
from uuid import uuid4

from .account_database import require_writer, transaction
from .auth_service import AccountConflict


class TournamentNotFound(ValueError):
    pass


class TournamentConflict(AccountConflict):
    pass


class TeamTournamentService:
    def __init__(self, connection, writer, auth, registry):
        self.db, self.writer, self.auth, self.registry = connection, writer, auth, registry

    def _ready(self):
        require_writer(self.writer, self.writer.path.parent)

    def _user(self, actor, *, admin=False):
        return self.auth.require_actor(actor, self.auth._now(), admin=admin,
                                       player_only=not admin, touch=False)

    def create(self, actor, *, name, game_id, team_ids):
        self._ready()
        with transaction(self.db):
            now = self.auth._now()
            admin = self.auth.require_actor(actor, now, admin=True)
            name = name.strip() if isinstance(name, str) else ""
            team_ids = list(team_ids) if isinstance(team_ids, list) else []
            if not 1 <= len(name) <= 64:
                raise ValueError("Tournament name must be 1–64 characters")
            if not 2 <= len(team_ids) <= 16 or len(set(team_ids)) != len(team_ids):
                raise ValueError("A tournament requires 2–16 distinct Teams")
            if game_id not in self.registry.ids():
                raise ValueError("Unknown game")
            rows = self.db.execute(
                "SELECT id,display_name,status FROM teams WHERE id IN (%s)" %
                ",".join("?" for _ in team_ids), team_ids).fetchall()
            if len(rows) != len(team_ids):
                raise TournamentNotFound("Team not found")
            if any(row["status"] != "ACTIVE" for row in rows):
                raise TournamentConflict("All participating Teams must be ACTIVE")
            tournament_id = uuid4().hex
            self.db.execute("""INSERT INTO team_tournaments
                (id,name,game_id,format,status,created_by,created_at)
                VALUES (?,?,?,'round_robin','REGISTRATION',?,?)""",
                (tournament_id, name, game_id, admin["id"], now))
            by_id = {row["id"]: row for row in rows}
            self.db.executemany("""INSERT INTO team_tournament_entries
                (tournament_id,team_id,team_name_snapshot) VALUES (?,?,?)""",
                [(tournament_id, team_id, by_id[team_id]["display_name"]) for team_id in team_ids])
            self.db.execute("""INSERT INTO team_tournament_audit
                (tournament_id,actor_user_id,action,occurred_at)
                VALUES (?,?,'CREATED',?)""", (tournament_id, admin["id"], now))
            return self.detail(actor, tournament_id, admin=True)

    def start(self, actor, tournament_id):
        self._ready()
        with transaction(self.db):
            now = self.auth._now()
            admin = self.auth.require_actor(actor, now, admin=True)
            row = self.db.execute("SELECT * FROM team_tournaments WHERE id=?", (tournament_id,)).fetchone()
            if not row:
                raise TournamentNotFound("Tournament not found")
            if row["status"] != "REGISTRATION":
                raise TournamentConflict("Tournament is not accepting a start operation")
            teams = [dict(team) for team in self.db.execute("""SELECT team_id AS id,
                team_name_snapshot AS name FROM team_tournament_entries
                WHERE tournament_id=? ORDER BY rowid""", (tournament_id,))]
            if len(teams) < 2:
                raise TournamentConflict("Tournament needs at least two Teams")
            rotation = teams + ([None] if len(teams) % 2 else [])
            rounds = []
            for round_number in range(1, len(rotation)):
                for index in range(len(rotation) // 2):
                    a, b = rotation[index], rotation[-1-index]
                    if a is None or b is None:
                        continue
                    fixture_id = uuid4().hex
                    self.db.execute("""INSERT INTO team_tournament_fixtures
                        (id,tournament_id,round_number,team_a_id,team_b_id,created_at)
                        VALUES (?,?,?,?,?,?)""",
                        (fixture_id, tournament_id, round_number, a["id"], b["id"], now))
                rotation = [rotation[0], rotation[-1], *rotation[1:-1]]
            self.db.execute("UPDATE team_tournaments SET status='ACTIVE',started_at=? WHERE id=?",
                             (now, tournament_id))
            self.db.execute("""INSERT INTO team_tournament_audit
                (tournament_id,actor_user_id,action,occurred_at)
                VALUES (?,?,'STARTED',?)""", (tournament_id, admin["id"], now))
            return self.detail(actor, tournament_id, admin=True)

    def list(self, actor, *, admin=False):
        user = self._user(actor, admin=admin)
        if admin:
            ids = [row[0] for row in self.db.execute(
                "SELECT id FROM team_tournaments ORDER BY created_at DESC,id DESC LIMIT 100")]
        else:
            ids = [row[0] for row in self.db.execute("""SELECT DISTINCT t.id,t.created_at
                FROM team_tournaments t JOIN team_tournament_entries e ON e.tournament_id=t.id
                JOIN team_memberships m ON m.team_id=e.team_id
                WHERE m.user_id=? AND m.left_at IS NULL
                ORDER BY t.created_at DESC,t.id DESC LIMIT 100""", (user["id"],))]
        return [self._detail(tournament_id) for tournament_id in ids]

    def detail(self, actor, tournament_id, *, admin=False):
        user = self._user(actor, admin=admin)
        if not admin and not self.db.execute("""SELECT 1 FROM team_tournament_entries e
            JOIN team_memberships m ON m.team_id=e.team_id
            WHERE e.tournament_id=? AND m.user_id=? AND m.left_at IS NULL LIMIT 1""",
            (tournament_id, user["id"])).fetchone():
            raise TournamentNotFound("Tournament not found")
        return self._detail(tournament_id)

    def _detail(self, tournament_id):
        row = self.db.execute("SELECT * FROM team_tournaments WHERE id=?", (tournament_id,)).fetchone()
        if not row:
            raise TournamentNotFound("Tournament not found")
        entries = [dict(item) for item in self.db.execute("""SELECT team_id,team_name_snapshot
            FROM team_tournament_entries WHERE tournament_id=? ORDER BY rowid""", (tournament_id,))]
        fixtures = []
        for item in self.db.execute("""SELECT f.*,r.status AS match_status,r.scheduled_at,
            r.match_id,r.outcome_json FROM team_tournament_fixtures f
            LEFT JOIN official_match_requests r ON r.id=f.official_request_id
            WHERE f.tournament_id=? ORDER BY f.round_number,f.id""", (tournament_id,)):
            fixture = dict(item)
            outcome = json.loads(fixture.pop("outcome_json") or "{}")
            fixture["outcome"] = outcome
            fixtures.append(fixture)
        standings = {item["team_id"]: {"team_id": item["team_id"],
            "team_name": item["team_name_snapshot"], "played": 0, "wins": 0,
            "draws": 0, "losses": 0, "points": 0} for item in entries}
        for fixture in fixtures:
            if fixture["match_status"] != "COMPLETED":
                continue
            outcome = fixture["outcome"]
            winner = outcome.get("winner_team_id")
            a, b = standings[fixture["team_a_id"]], standings[fixture["team_b_id"]]
            a["played"] += 1; b["played"] += 1
            if winner == a["team_id"]:
                a["wins"] += 1; a["points"] += 3; b["losses"] += 1
            elif winner == b["team_id"]:
                b["wins"] += 1; b["points"] += 3; a["losses"] += 1
            else:
                a["draws"] += 1; b["draws"] += 1; a["points"] += 1; b["points"] += 1
        ranked = sorted(standings.values(), key=lambda item: (-item["points"], -item["wins"], item["team_name"].casefold()))
        for index, item in enumerate(ranked, 1):
            item["rank"] = index
        result = {key: row[key] for key in ("id", "name", "game_id", "format", "status", "created_at", "started_at")}
        if result["status"] == "ACTIVE" and fixtures and all(f["match_status"] == "COMPLETED" for f in fixtures):
            result["status"] = "COMPLETED"
        result.update(teams=entries, fixtures=fixtures, standings=ranked)
        return result
