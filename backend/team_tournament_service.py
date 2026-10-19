"""Account-only round-robin tournaments for active Teams."""
from __future__ import annotations

import json
from math import ceil, log2
from uuid import uuid4

from .account_database import require_writer, transaction
from .auth_service import AccountConflict


class TournamentNotFound(ValueError):
    pass


class TournamentConflict(AccountConflict):
    pass


def _apply_table_result(standings, fixture, outcome):
    a, b = standings[fixture["team_a_id"]], standings[fixture["team_b_id"]]
    a["played"] += 1; b["played"] += 1
    result = outcome.get("result") or {}
    scores = result.get("scores") or {}
    score_a = scores.get("A", 0) if isinstance(scores, dict) else 0
    score_b = scores.get("B", 0) if isinstance(scores, dict) else 0
    score_a = score_a if isinstance(score_a, int) and not isinstance(score_a, bool) else 0
    score_b = score_b if isinstance(score_b, int) and not isinstance(score_b, bool) else 0
    a["score_for"] += score_a; b["score_for"] += score_b
    a["score_difference"] += score_a - score_b
    b["score_difference"] += score_b - score_a
    winner = outcome.get("winner_team_id")
    if winner == a["team_id"]:
        a["wins"] += 1; a["points"] += 3; b["losses"] += 1
    elif winner == b["team_id"]:
        b["wins"] += 1; b["points"] += 3; a["losses"] += 1
    else:
        a["draws"] += 1; b["draws"] += 1
        a["points"] += 1; b["points"] += 1


def _swiss_round_count(team_count):
    return max(3, ceil(log2(team_count)))


def _swiss_standings(connection, tournament_id, group_id=None):
    rows = connection.execute("""SELECT e.team_id,e.team_name_snapshot
        FROM team_tournament_entries e LEFT JOIN team_tournament_group_entries ge
        ON ge.tournament_id=e.tournament_id AND ge.team_id=e.team_id
        WHERE e.tournament_id=? AND (? IS NULL OR ge.group_id=?) ORDER BY e.rowid""",
        (tournament_id, group_id, group_id)).fetchall()
    table = {row["team_id"]: {"team_id": row["team_id"], "team_name": row["team_name_snapshot"],
        "played": 0, "wins": 0, "draws": 0, "losses": 0, "points_half": 0,
        "score_for": 0, "score_difference": 0, "opponents": [], "byes": 0} for row in rows}
    fixtures = connection.execute("""SELECT f.team_a_id,f.team_b_id,r.status,r.outcome_json
        FROM team_tournament_fixtures f LEFT JOIN official_match_requests r ON r.id=f.official_request_id
        WHERE f.tournament_id=? AND f.stage='GROUP'""", (tournament_id,)).fetchall()
    for fixture in fixtures:
        if fixture["status"] != "COMPLETED":
            continue
        a, b = table[fixture["team_a_id"]], table[fixture["team_b_id"]]
        outcome = json.loads(fixture["outcome_json"] or "{}")
        result = outcome.get("result") or {}
        scores = result.get("scores") or {}
        score_a, score_b = scores.get("A", 0), scores.get("B", 0)
        score_a = score_a if isinstance(score_a, int) and not isinstance(score_a, bool) else 0
        score_b = score_b if isinstance(score_b, int) and not isinstance(score_b, bool) else 0
        a["played"] += 1; b["played"] += 1
        a["score_for"] += score_a; b["score_for"] += score_b
        a["score_difference"] += score_a - score_b; b["score_difference"] += score_b - score_a
        a["opponents"].append(b["team_id"]); b["opponents"].append(a["team_id"])
        winner = outcome.get("winner_team_id")
        if winner == a["team_id"]:
            a["wins"] += 1; a["points_half"] += 2; b["losses"] += 1
        elif winner == b["team_id"]:
            b["wins"] += 1; b["points_half"] += 2; a["losses"] += 1
        else:
            a["draws"] += 1; b["draws"] += 1
            a["points_half"] += 1; b["points_half"] += 1
    byes = connection.execute("SELECT team_id FROM team_tournament_swiss_byes WHERE tournament_id=?",
                              (tournament_id,)).fetchall()
    for bye in byes:
        if bye["team_id"] in table:
            table[bye["team_id"]]["points_half"] += 2
            table[bye["team_id"]]["wins"] += 1
            table[bye["team_id"]]["byes"] += 1
    for item in table.values():
        item["buchholz_half"] = sum(table[opponent]["points_half"] for opponent in item["opponents"])
        item["points"] = item["points_half"] / 2
        item["buchholz"] = item["buchholz_half"] / 2
        item.pop("points_half"); item.pop("buchholz_half"); item.pop("opponents")
    return sorted(table.values(), key=lambda item: (-item["points"], -item["buchholz"],
        -item["score_difference"], -item["score_for"], -item["wins"], item["team_name"].casefold()))


def _swiss_pair_round(connection, tournament_id, group_id, round_number, now, seeded=False):
    ranked = _swiss_standings(connection, tournament_id, group_id)
    if seeded:
        team_ids = [item["team_id"] for item in ranked]
        bye_team = team_ids.pop() if len(team_ids) % 2 else None
        # Pair the top half against the bottom half for the opening round.
        half = ceil(len(team_ids) / 2)
        pairs = [(team_ids[index], team_ids[index + half])
                 for index in range(len(team_ids) - half)]
    else:
        bye_rows = connection.execute("SELECT team_id FROM team_tournament_swiss_byes WHERE tournament_id=?",
                                      (tournament_id,)).fetchall()
        previous_byes = {item["team_id"] for item in bye_rows}
        bye_team = next((item["team_id"] for item in reversed(ranked)
                         if item["team_id"] not in previous_byes), None) if len(ranked) % 2 else None
        pool = [item["team_id"] for item in ranked if item["team_id"] != bye_team]
        history = connection.execute("""SELECT team_a_id,team_b_id FROM team_tournament_fixtures
            WHERE tournament_id=? AND stage='GROUP'""", (tournament_id,)).fetchall()
        rematches = {frozenset((item["team_a_id"], item["team_b_id"])) for item in history}

        def find_pairs(remaining):
            if not remaining:
                return []
            first = remaining[0]
            choices = sorted(remaining[1:], key=lambda opponent:
                (frozenset((first, opponent)) in rematches,
                 abs(next(i for i, row in enumerate(ranked) if row["team_id"] == first) -
                     next(i for i, row in enumerate(ranked) if row["team_id"] == opponent))))
            for opponent in choices:
                rest = [team for team in remaining if team not in (first, opponent)]
                suffix = find_pairs(rest)
                if suffix is not None:
                    return [(first, opponent), *suffix]
            return None
        pairs = find_pairs(pool) or []
    for team_a_id, team_b_id in pairs:
        connection.execute("""INSERT INTO team_tournament_fixtures
            (id,tournament_id,round_number,team_a_id,team_b_id,created_at,stage,group_id)
            VALUES (?,?,?,?,?,?,'GROUP',?)""",
            (uuid4().hex, tournament_id, round_number, team_a_id, team_b_id, now, group_id))
    if bye_team:
        connection.execute("INSERT INTO team_tournament_swiss_byes(tournament_id,round_number,team_id) VALUES (?,?,?)",
                           (tournament_id, round_number, bye_team))


def _create_swiss_playoffs(connection, tournament_id, group_id, team_count, now):
    qualified_count = 4 if team_count < 8 else 8
    seed_pairs = [(1, 4), (2, 3)] if qualified_count == 4 else [(1, 8), (4, 5), (2, 7), (3, 6)]
    previous = []
    match_count = len(seed_pairs)
    round_number = _swiss_round_count(team_count) + 1
    while match_count:
        current = []
        for index in range(match_count):
            slot_id = uuid4().hex
            source_a_group_id = source_a_group_rank = None
            source_b_group_id = source_b_group_rank = None
            source_a_slot = source_b_slot = None
            if not previous:
                source_a_group_id, source_a_group_rank = group_id, seed_pairs[index][0]
                source_b_group_id, source_b_group_rank = group_id, seed_pairs[index][1]
            else:
                source_a_slot, source_b_slot = previous[index * 2:index * 2 + 2]
            connection.execute("""INSERT INTO team_tournament_bracket_slots
                (id,tournament_id,round_number,match_number,source_a_slot_id,source_b_slot_id,
                 source_a_group_id,source_a_group_rank,source_b_group_id,source_b_group_rank,status)
                VALUES (?,?,?,?,?,?,?,?,?,?, 'PENDING')""",
                (slot_id,tournament_id,round_number,index+1,source_a_slot,source_b_slot,
                 source_a_group_id,source_a_group_rank,source_b_group_id,source_b_group_rank))
            current.append(slot_id)
        previous = current
        match_count //= 2
        round_number += 1


def advance_swiss_stage(connection, tournament_id, now, actor_user_id=None):
    row = connection.execute("""SELECT count(*) AS team_count FROM team_tournament_entries
        WHERE tournament_id=?""", (tournament_id,)).fetchone()
    team_count = row["team_count"]
    if team_count < 4:
        return
    group = connection.execute("SELECT id FROM team_tournament_groups WHERE tournament_id=? LIMIT 1",
                               (tournament_id,)).fetchone()
    if not group:
        return
    group_id = group["id"]
    round_row = connection.execute("""SELECT max(round_number) FROM (
        SELECT round_number FROM team_tournament_fixtures WHERE tournament_id=? AND stage='GROUP'
        UNION ALL SELECT round_number FROM team_tournament_swiss_byes WHERE tournament_id=?)""",
        (tournament_id, tournament_id)).fetchone()
    current_round = round_row[0] or 0
    if not current_round:
        _swiss_pair_round(connection, tournament_id, group_id, 1, now, seeded=True)
        return
    pending = connection.execute("""SELECT count(*) FROM team_tournament_fixtures f
        LEFT JOIN official_match_requests r ON r.id=f.official_request_id
        WHERE f.tournament_id=? AND f.stage='GROUP' AND f.round_number=? AND coalesce(r.status,'')<>'COMPLETED'""",
        (tournament_id, current_round)).fetchone()[0]
    if pending:
        return
    total_rounds = _swiss_round_count(team_count)
    if current_round < total_rounds:
        _swiss_pair_round(connection, tournament_id, group_id, current_round + 1, now)
        return
    if not connection.execute("SELECT 1 FROM team_tournament_bracket_slots WHERE tournament_id=? LIMIT 1",
                              (tournament_id,)).fetchone():
        _create_swiss_playoffs(connection, tournament_id, group_id, team_count, now)
        advance_single_elimination(connection, tournament_id, now, actor_user_id)


def advance_single_elimination(connection, tournament_id, now, actor_user_id=None):
    """Materialize ready bracket fixtures and resolve byes/conditional finals."""
    changed = True
    while changed:
        changed = False
        tournament_format = connection.execute("""SELECT coalesce(f.format,t.format)
            FROM team_tournaments t LEFT JOIN team_tournament_format_overrides f
            ON f.tournament_id=t.id WHERE t.id=?""", (tournament_id,)).fetchone()[0]
        if tournament_format == "double_elimination":
            final = connection.execute("""SELECT id,source_a_slot_id,winner_team_id,status
                FROM team_tournament_bracket_slots WHERE tournament_id=? AND bracket='FINAL'""",
                (tournament_id,)).fetchone()
            reset = connection.execute("""SELECT id,status,conditional_status FROM team_tournament_bracket_slots
                WHERE tournament_id=? AND bracket='RESET'""", (tournament_id,)).fetchone()
            if final and final["status"] == "COMPLETED" and reset and reset["conditional_status"] == "WAITING":
                upper = connection.execute("SELECT winner_team_id FROM team_tournament_bracket_slots WHERE id=?",
                                           (final["source_a_slot_id"],)).fetchone()
                upper_champion = upper["winner_team_id"] if upper else None
                if final["winner_team_id"] == upper_champion:
                    connection.execute("""UPDATE team_tournament_bracket_slots
                        SET status='BYE',winner_team_id=?,conditional_status='SKIPPED' WHERE id=?""",
                        (upper_champion, reset["id"]))
                else:
                    connection.execute("UPDATE team_tournament_bracket_slots SET conditional_status='ACTIVE' WHERE id=?",
                                       (reset["id"],))
                changed = True
        slots = connection.execute("""SELECT * FROM team_tournament_bracket_slots
            WHERE tournament_id=? AND status='PENDING' AND conditional_status<>'WAITING'
            ORDER BY round_number,match_number""", (tournament_id,)).fetchall()
        for row in slots:
            slot = dict(row)
            participants = [slot["team_a_id"], slot["team_b_id"]]
            source_ids = [slot["source_a_slot_id"], slot["source_b_slot_id"]]
            group_sources = [
                (slot["source_a_group_id"], slot["source_a_group_rank"]),
                (slot["source_b_group_id"], slot["source_b_group_rank"]),
            ]
            unresolved = False
            for side, source_id in enumerate(source_ids):
                group_id, group_rank = group_sources[side]
                if group_id:
                    if participants[side]:
                        continue
                    fixtures = connection.execute("""SELECT f.team_a_id,f.team_b_id,
                        f.official_request_id,r.status,r.outcome_json FROM team_tournament_fixtures f
                        LEFT JOIN official_match_requests r ON r.id=f.official_request_id
                        WHERE f.tournament_id=? AND f.group_id=?""",
                        (tournament_id, group_id)).fetchall()
                    if not fixtures or any(item["status"] != "COMPLETED" for item in fixtures):
                        unresolved = True
                        continue
                    if tournament_format == "swiss_single_elimination":
                        ranked = _swiss_standings(connection, tournament_id, group_id)
                        if group_rank > len(ranked):
                            unresolved = True
                            continue
                        participants[side] = ranked[group_rank - 1]["team_id"]
                        column = "team_a_id" if side == 0 else "team_b_id"
                        if slot[column] != participants[side]:
                            connection.execute(f"UPDATE team_tournament_bracket_slots SET {column}=? WHERE id=?",
                                               (participants[side], slot["id"]))
                            changed = True
                        continue
                    entry_rows = connection.execute("""SELECT e.team_id,e.team_name_snapshot
                        FROM team_tournament_group_entries ge JOIN team_tournament_entries e
                        ON e.tournament_id=ge.tournament_id AND e.team_id=ge.team_id
                        WHERE ge.tournament_id=? AND ge.group_id=? ORDER BY e.rowid""",
                        (tournament_id, group_id)).fetchall()
                    standings = {item["team_id"]: {"team_id": item["team_id"],
                        "team_name": item["team_name_snapshot"], "played": 0, "wins": 0,
                        "draws": 0, "losses": 0, "points": 0, "score_for": 0,
                        "score_difference": 0} for item in entry_rows}
                    for item in fixtures:
                        outcome = json.loads(item["outcome_json"] or "{}")
                        _apply_table_result(standings, item, outcome)
                    ranked = sorted(standings.values(), key=lambda item:
                        (-item["points"], -item["score_difference"], -item["score_for"],
                         -item["wins"], item["team_name"].casefold()))
                    if group_rank > len(ranked):
                        unresolved = True
                        continue
                    participants[side] = ranked[group_rank - 1]["team_id"]
                elif source_id:
                    if participants[side]:
                        continue
                    source = connection.execute("SELECT status,winner_team_id,team_a_id,team_b_id FROM team_tournament_bracket_slots WHERE id=?",
                                                (source_id,)).fetchone()
                    if not source or source["status"] == "TIE":
                        unresolved = True
                        continue
                    if source["status"] not in ("COMPLETED", "BYE"):
                        unresolved = True
                        continue
                    result_kind = slot["source_a_result"] if side == 0 else slot["source_b_result"]
                    if result_kind == "WINNER" or source["status"] == "BYE":
                        participants[side] = source["winner_team_id"] if result_kind == "WINNER" else None
                    else:
                        participants[side] = (source["team_b_id"] if source["winner_team_id"] == source["team_a_id"]
                                              else source["team_a_id"])
                else:
                    continue
                column = "team_a_id" if side == 0 else "team_b_id"
                if slot[column] != participants[side]:
                    connection.execute(f"UPDATE team_tournament_bracket_slots SET {column}=? WHERE id=?",
                                       (participants[side], slot["id"]))
                    changed = True
            if unresolved:
                continue
            if participants[0] is None and participants[1] is None:
                connection.execute("UPDATE team_tournament_bracket_slots SET status='BYE' WHERE id=?",
                                   (slot["id"],))
                changed = True
                continue
            if participants[0] is None or participants[1] is None:
                winner = participants[0] or participants[1]
                connection.execute("""UPDATE team_tournament_bracket_slots
                    SET status='BYE',winner_team_id=? WHERE id=?""", (winner, slot["id"]))
                changed = True
                continue
            fixture_id = slot["fixture_id"]
            if fixture_id is None:
                fixture_id = uuid4().hex
                connection.execute("""INSERT INTO team_tournament_fixtures
                    (id,tournament_id,round_number,team_a_id,team_b_id,created_at)
                    VALUES (?,?,?,?,?,?)""", (fixture_id, tournament_id,
                        slot["round_number"], participants[0], participants[1], now))
                connection.execute("UPDATE team_tournament_bracket_slots SET fixture_id=?,status='READY' WHERE id=?",
                                   (fixture_id, slot["id"]))
                if actor_user_id:
                    connection.execute("""INSERT INTO team_tournament_audit
                        (tournament_id,fixture_id,actor_user_id,action,occurred_at)
                        VALUES (?,?,?,'BRACKET_FIXTURE_READY',?)""",
                        (tournament_id, fixture_id, actor_user_id, now))
                changed = True
    final = connection.execute("""SELECT status FROM team_tournament_bracket_slots
        WHERE tournament_id=? ORDER BY round_number DESC,match_number LIMIT 1""",
        (tournament_id,)).fetchone()
    if final and final["status"] in ("COMPLETED", "BYE"):
        connection.execute("UPDATE team_tournaments SET status='COMPLETED' WHERE id=? AND status='ACTIVE'",
                           (tournament_id,))


class TeamTournamentService:
    def __init__(self, connection, writer, auth, registry):
        self.db, self.writer, self.auth, self.registry = connection, writer, auth, registry

    def _ready(self):
        require_writer(self.writer, self.writer.path.parent)

    def _user(self, actor, *, admin=False):
        return self.auth.require_actor(actor, self.auth._now(), admin=admin,
                                       player_only=not admin, touch=False)

    def create(self, actor, *, name, game_id, team_ids, format="round_robin"):
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
            if format not in ("round_robin", "single_elimination", "group_knockout", "double_elimination", "swiss_single_elimination"):
                raise ValueError("Unsupported Team tournament format")
            if format in ("group_knockout", "swiss_single_elimination") and len(team_ids) < 4:
                raise ValueError("This tournament format requires at least four Teams")
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
            if format in ("single_elimination", "group_knockout", "double_elimination", "swiss_single_elimination"):
                self.db.execute("INSERT INTO team_tournament_format_overrides VALUES (?,?)",
                                (tournament_id, format))
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
            row = self.db.execute("""SELECT t.*,coalesce(f.format,t.format) AS effective_format
                FROM team_tournaments t LEFT JOIN team_tournament_format_overrides f
                ON f.tournament_id=t.id WHERE t.id=?""", (tournament_id,)).fetchone()
            if not row:
                raise TournamentNotFound("Tournament not found")
            if row["status"] != "REGISTRATION":
                raise TournamentConflict("Tournament is not accepting a start operation")
            teams = [dict(team) for team in self.db.execute("""SELECT team_id AS id,
                team_name_snapshot AS name FROM team_tournament_entries
                WHERE tournament_id=? ORDER BY rowid""", (tournament_id,))]
            if len(teams) < 2:
                raise TournamentConflict("Tournament needs at least two Teams")
            if row["effective_format"] == "round_robin":
                rotation = teams + ([None] if len(teams) % 2 else [])
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
            elif row["effective_format"] == "single_elimination":
                size = 1
                while size < len(teams):
                    size *= 2
                bye_count = size - len(teams)
                first_round = []
                for team in teams[:bye_count]:
                    first_round.extend((team, None))
                remaining = teams[bye_count:]
                first_round.extend(remaining + [None] * (size - len(teams) - bye_count))
                slots_by_round = []
                match_count = size // 2
                for round_number in range(1, (size.bit_length())):
                    current = []
                    for index in range(match_count):
                        slot_id = uuid4().hex
                        if round_number == 1:
                            a, b = first_round[index * 2:index * 2 + 2]
                            team_a_id, team_b_id = (a or {}).get("id"), (b or {}).get("id")
                            source_a = source_b = None
                        else:
                            previous = slots_by_round[-1]
                            team_a_id = team_b_id = None
                            source_a, source_b = previous[index * 2:index * 2 + 2]
                        self.db.execute("""INSERT INTO team_tournament_bracket_slots
                            (id,tournament_id,round_number,match_number,team_a_id,team_b_id,
                             source_a_slot_id,source_b_slot_id,status)
                            VALUES (?,?,?,?,?,?,?,?, 'PENDING')""",
                            (slot_id, tournament_id, round_number, index + 1, team_a_id,
                             team_b_id, source_a, source_b))
                        current.append(slot_id)
                    slots_by_round.append(current)
                    match_count //= 2
            elif row["effective_format"] == "double_elimination":
                size = 1
                while size < len(teams):
                    size *= 2
                width = size.bit_length() - 1
                bye_count = size - len(teams)
                first_round = []
                for team in teams[:bye_count]:
                    first_round.extend((team, None))
                first_round.extend(teams[bye_count:] + [None] * (size - len(teams) - bye_count))
                winners_rounds = []
                round_number = 1
                match_count = size // 2
                for round_index in range(width):
                    current = []
                    for index in range(match_count):
                        slot_id = uuid4().hex
                        team_a_id = team_b_id = source_a = source_b = None
                        if round_index == 0:
                            a, b = first_round[index * 2:index * 2 + 2]
                            team_a_id, team_b_id = (a or {}).get("id"), (b or {}).get("id")
                        else:
                            previous = winners_rounds[-1]
                            source_a, source_b = previous[index * 2:index * 2 + 2]
                        self.db.execute("""INSERT INTO team_tournament_bracket_slots
                            (id,tournament_id,round_number,match_number,team_a_id,team_b_id,
                             source_a_slot_id,source_b_slot_id,bracket,status)
                            VALUES (?,?,?,?,?,?,?,?, 'WINNERS','PENDING')""",
                            (slot_id,tournament_id,round_number,index+1,team_a_id,team_b_id,source_a,source_b))
                        current.append(slot_id)
                    winners_rounds.append(current)
                    round_number += 1
                    match_count //= 2

                lower_rounds = []
                lower_counts = [max(1, size // (2 ** (index // 2 + 2)))
                                for index in range(2 * (width - 1))]
                for index, count in enumerate(lower_counts):
                    current = []
                    for match_index in range(count):
                        slot_id = uuid4().hex
                        self.db.execute("""INSERT INTO team_tournament_bracket_slots
                            (id,tournament_id,round_number,match_number,bracket,status)
                            VALUES (?,?,?,?, 'LOSERS','PENDING')""",
                            (slot_id,tournament_id,round_number,match_index+1))
                        current.append(slot_id)
                    lower_rounds.append(current)
                    round_number += 1
                if lower_rounds:
                    # First lower round pairs drops from adjacent first-round winners fixtures.
                    for index, upper_slot in enumerate(winners_rounds[0]):
                        target = lower_rounds[0][index // 2]
                        side = "a" if index % 2 == 0 else "b"
                        self.db.execute(f"""UPDATE team_tournament_bracket_slots
                            SET source_{side}_slot_id=?,source_{side}_result='LOSER' WHERE id=?""",
                            (upper_slot,target))
                    for index, lower_round in enumerate(lower_rounds[:-1]):
                        following = lower_rounds[index + 1]
                        if index % 2 == 0:
                            for match_index, lower_slot in enumerate(lower_round):
                                target = following[match_index]
                                self.db.execute("""UPDATE team_tournament_bracket_slots
                                    SET source_a_slot_id=?,source_a_result='WINNER' WHERE id=?""",
                                    (lower_slot,target))
                            winners_index = index // 2 + 1
                            if winners_index < len(winners_rounds):
                                for drop_index, upper_slot in enumerate(winners_rounds[winners_index]):
                                    target = following[drop_index]
                                    self.db.execute("""UPDATE team_tournament_bracket_slots
                                        SET source_b_slot_id=?,source_b_result='LOSER' WHERE id=?""",
                                        (upper_slot,target))
                        else:
                            for match_index, lower_slot in enumerate(lower_round):
                                target = following[match_index // 2]
                                side = "a" if match_index % 2 == 0 else "b"
                                self.db.execute(f"""UPDATE team_tournament_bracket_slots
                                    SET source_{side}_slot_id=?,source_{side}_result='WINNER' WHERE id=?""",
                                    (lower_slot,target))

                grand_final_id = uuid4().hex
                winner_champion_slot = winners_rounds[-1][0]
                loser_champion_slot = lower_rounds[-1][0] if lower_rounds else winner_champion_slot
                self.db.execute("""INSERT INTO team_tournament_bracket_slots
                    (id,tournament_id,round_number,match_number,source_a_slot_id,source_b_slot_id,
                     source_a_result,source_b_result,bracket,status)
                    VALUES (?,?,?,1,?,?,'WINNER',?,'FINAL','PENDING')""",
                    (grand_final_id,tournament_id,round_number,winner_champion_slot,
                     loser_champion_slot,"LOSER" if not lower_rounds else "WINNER"))
                round_number += 1
                reset_id = uuid4().hex
                self.db.execute("""INSERT INTO team_tournament_bracket_slots
                    (id,tournament_id,round_number,match_number,source_a_slot_id,source_b_slot_id,
                     source_a_result,source_b_result,bracket,status,conditional_status)
                    VALUES (?,?,?,1,?,?,'WINNER',?,'RESET','PENDING','WAITING')""",
                    (reset_id,tournament_id,round_number,winner_champion_slot,
                     loser_champion_slot,"LOSER" if not lower_rounds else "WINNER"))
            elif row["effective_format"] == "swiss_single_elimination":
                group_id = uuid4().hex
                self.db.execute("""INSERT INTO team_tournament_groups
                    (id,tournament_id,group_number,name) VALUES (?,?,1,'Swiss Stage')""",
                    (group_id,tournament_id))
                self.db.executemany("""INSERT INTO team_tournament_group_entries
                    (tournament_id,group_id,team_id) VALUES (?,?,?)""",
                    [(tournament_id,group_id,team["id"]) for team in teams])
                _swiss_pair_round(self.db,tournament_id,group_id,1,now,seeded=True)
            else:
                group_count = 2 if len(teams) <= 8 else 4
                groups = []
                for index in range(group_count):
                    group_id = uuid4().hex
                    group_name = f"Bảng {chr(65 + index)}"
                    self.db.execute("""INSERT INTO team_tournament_groups
                        (id,tournament_id,group_number,name) VALUES (?,?,?,?)""",
                        (group_id, tournament_id, index + 1, group_name))
                    groups.append({"id": group_id, "name": group_name, "teams": []})
                for index, team in enumerate(teams):
                    group = groups[index % group_count]
                    group["teams"].append(team)
                    self.db.execute("""INSERT INTO team_tournament_group_entries
                        (tournament_id,group_id,team_id) VALUES (?,?,?)""",
                        (tournament_id, group["id"], team["id"]))
                for group in groups:
                    rotation = group["teams"] + ([None] if len(group["teams"]) % 2 else [])
                    for round_number in range(1, len(rotation)):
                        for index in range(len(rotation) // 2):
                            a, b = rotation[index], rotation[-1-index]
                            if a is None or b is None:
                                continue
                            self.db.execute("""INSERT INTO team_tournament_fixtures
                                (id,tournament_id,round_number,team_a_id,team_b_id,created_at,stage,group_id)
                                VALUES (?,?,?,?,?,?,'GROUP',?)""",
                                (uuid4().hex, tournament_id, round_number, a["id"], b["id"], now, group["id"]))
                        rotation = [rotation[0], rotation[-1], *rotation[1:-1]]
                # Top two from each group qualify. Cross-group pairing follows
                # football conventions: A1-B2, B1-A2 (and C/D analogously).
                first_round = []
                for index in range(0, group_count, 2):
                    first_round.extend(((groups[index]["id"], 1), (groups[index + 1]["id"], 2),
                                        (groups[index + 1]["id"], 1), (groups[index]["id"], 2)))
                slots_by_round = []
                match_count = len(first_round) // 2
                for round_number in range(1, match_count.bit_length() + 1):
                    current = []
                    for index in range(match_count):
                        slot_id = uuid4().hex
                        source_a_group_id = source_a_group_rank = None
                        source_b_group_id = source_b_group_rank = None
                        source_a_slot = source_b_slot = None
                        if round_number == 1:
                            source_a_group_id, source_a_group_rank = first_round[index * 2]
                            source_b_group_id, source_b_group_rank = first_round[index * 2 + 1]
                        else:
                            previous = slots_by_round[-1]
                            source_a_slot, source_b_slot = previous[index * 2:index * 2 + 2]
                        self.db.execute("""INSERT INTO team_tournament_bracket_slots
                            (id,tournament_id,round_number,match_number,source_a_slot_id,source_b_slot_id,
                             source_a_group_id,source_a_group_rank,source_b_group_id,source_b_group_rank,status)
                            VALUES (?,?,?,?,?,?,?,?,?,?, 'PENDING')""",
                            (slot_id,tournament_id,round_number,index+1,source_a_slot,source_b_slot,
                             source_a_group_id,source_a_group_rank,source_b_group_id,source_b_group_rank))
                        current.append(slot_id)
                    slots_by_round.append(current)
                    match_count //= 2
            self.db.execute("UPDATE team_tournaments SET status='ACTIVE',started_at=? WHERE id=?",
                             (now, tournament_id))
            if row["effective_format"] in ("single_elimination", "group_knockout", "double_elimination"):
                advance_single_elimination(self.db, tournament_id, now, admin["id"])
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

    def resolve_tie(self, actor, tournament_id, fixture_id, winner_team_id):
        self._ready()
        with transaction(self.db):
            now = self.auth._now()
            admin = self.auth.require_actor(actor, now, admin=True)
            row = self.db.execute("""SELECT b.* FROM team_tournament_bracket_slots b
                JOIN team_tournament_fixtures f ON f.id=b.fixture_id
                WHERE b.tournament_id=? AND f.id=?""", (tournament_id, fixture_id)).fetchone()
            if not row or row["status"] != "TIE" or winner_team_id not in (row["team_a_id"], row["team_b_id"]):
                raise TournamentConflict("This fixture has no unresolved tie")
            self.db.execute("UPDATE team_tournament_bracket_slots SET status='COMPLETED',winner_team_id=? WHERE id=?",
                             (winner_team_id, row["id"]))
            self.db.execute("""INSERT INTO team_tournament_audit
                (tournament_id,fixture_id,actor_user_id,action,occurred_at)
                VALUES (?,?,?,'TIE_RESOLVED_BY_ADMIN',?)""",
                (tournament_id, fixture_id, admin["id"], now))
            advance_single_elimination(self.db, tournament_id, now, admin["id"])
            return self.detail(actor, tournament_id, admin=True)

    def _detail(self, tournament_id):
        row = self.db.execute("""SELECT t.*,coalesce(f.format,t.format) AS effective_format
            FROM team_tournaments t LEFT JOIN team_tournament_format_overrides f
            ON f.tournament_id=t.id WHERE t.id=?""", (tournament_id,)).fetchone()
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
        bracket = []
        if row["effective_format"] in ("single_elimination", "group_knockout", "double_elimination", "swiss_single_elimination"):
            for item in self.db.execute("""SELECT b.*,r.id AS official_request_id,
                r.status AS match_status,r.scheduled_at,r.match_id,r.outcome_json
                FROM team_tournament_bracket_slots b
                LEFT JOIN team_tournament_fixtures f ON f.id=b.fixture_id
                LEFT JOIN official_match_requests r ON r.id=f.official_request_id
                WHERE b.tournament_id=? ORDER BY b.round_number,b.match_number""", (tournament_id,)):
                slot = dict(item)
                slot["outcome"] = json.loads(slot.pop("outcome_json") or "{}")
                bracket.append(slot)
        standings = {item["team_id"]: {"team_id": item["team_id"],
            "team_name": item["team_name_snapshot"], "played": 0, "wins": 0,
            "draws": 0, "losses": 0, "points": 0, "score_for": 0,
            "score_difference": 0} for item in entries}
        for fixture in fixtures:
            if row["effective_format"] in ("group_knockout", "swiss_single_elimination") and fixture["stage"] != "GROUP":
                continue
            if fixture["match_status"] != "COMPLETED":
                continue
            _apply_table_result(standings, fixture, fixture["outcome"])
        ranked = sorted(standings.values(), key=lambda item:
            (-item["points"], -item["score_difference"], -item["score_for"],
             -item["wins"], item["team_name"].casefold()))
        for index, item in enumerate(ranked, 1):
            item["rank"] = index
        if row["effective_format"] == "swiss_single_elimination":
            ranked = _swiss_standings(self.db, tournament_id)
            for index, item in enumerate(ranked, 1):
                item["rank"] = index
        groups = []
        if row["effective_format"] == "group_knockout":
            for group in self.db.execute("""SELECT id,name,group_number FROM team_tournament_groups
                WHERE tournament_id=? ORDER BY group_number""", (tournament_id,)):
                member_ids = {item[0] for item in self.db.execute("""SELECT team_id FROM team_tournament_group_entries
                    WHERE tournament_id=? AND group_id=?""", (tournament_id, group["id"]))}
                group_rows = [dict(item) for item in ranked if item["team_id"] in member_ids]
                for position, item in enumerate(group_rows, 1):
                    item["rank"] = position
                groups.append({"id": group["id"], "name": group["name"],
                    "group_number": group["group_number"], "standings": group_rows})
        result = {key: row[key] for key in ("id", "name", "game_id", "status", "created_at", "started_at")}
        result["format"] = row["effective_format"]
        if result["status"] == "ACTIVE" and result["format"] == "round_robin" and fixtures and all(f["match_status"] == "COMPLETED" for f in fixtures):
            result["status"] = "COMPLETED"
        result.update(teams=entries, fixtures=fixtures,
            standings=[] if row["effective_format"] == "group_knockout" else ranked,
            groups=groups, bracket=bracket)
        if row["effective_format"] == "swiss_single_elimination":
            result["swiss_rounds_total"] = _swiss_round_count(len(entries))
            result["swiss_rounds_completed"] = self.db.execute("""SELECT coalesce(max(round_number),0)
                FROM team_tournament_fixtures WHERE tournament_id=? AND stage='GROUP' AND id NOT IN (
                    SELECT f.id FROM team_tournament_fixtures f LEFT JOIN official_match_requests r
                    ON r.id=f.official_request_id WHERE f.tournament_id=? AND coalesce(r.status,'')<>'COMPLETED')""",
                (tournament_id,tournament_id)).fetchone()[0]
            result["swiss_byes"] = [dict(item) for item in self.db.execute("""SELECT b.round_number,
                b.team_id,e.team_name_snapshot AS team_name FROM team_tournament_swiss_byes b
                JOIN team_tournament_entries e ON e.tournament_id=b.tournament_id AND e.team_id=b.team_id
                WHERE b.tournament_id=? ORDER BY b.round_number""", (tournament_id,))]
        return result
