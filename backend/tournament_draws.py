from __future__ import annotations

from copy import deepcopy
from math import ceil, log2


def _next_power_of_two(value: int) -> int:
    return 1 << ceil(log2(value))


def _new_match(number: int, player_a=None, player_b=None, *, source_a=None, source_b=None, new_id):
    if player_a is None and player_b is None:
        status = "waiting"
    elif player_a is None or player_b is None:
        status = "bye"
    else:
        status = "pending"
    return {"id": new_id(), "number": number, "player_a": deepcopy(player_a),
            "player_b": deepcopy(player_b), "source_a": source_a, "source_b": source_b,
            "winner_id": None, "loser_id": None, "status": status,
            "match_id": None, "invitation_id": None, "result": None}


def _target(match: dict, slot: str) -> dict:
    return {"match_id": match["id"], "slot": slot}


def _link(source: dict, target: dict, outcome: str, slot: str, label: str):
    source[f"{outcome}_to"] = _target(target, slot)
    target.setdefault("source_refs", {})[slot] = {"match_id": source["id"], "result": outcome}
    target[f"source_{slot.lower()}"] = label


def _all_matches(tournament: dict) -> list[dict]:
    return [match for round_data in tournament.get("rounds", [])
            for match in round_data.get("matches", [])]


def current_round_for_scheduling(tournament: dict) -> dict | None:
    """For round robin, return only the earliest round that is not fully resolved."""
    if tournament.get("format") != "round_robin":
        return None
    for round_data in tournament.get("rounds", []):
        matches = round_data.get("matches", [])
        if matches and any(match.get("status") not in {"completed", "skipped"} for match in matches):
            return round_data
    return None


def _put_player(tournament: dict, destination: dict | None, player: dict | None):
    if not destination or not player:
        return
    target = next((m for m in _all_matches(tournament) if m["id"] == destination["match_id"]), None)
    if not target or target.get("status") in {"completed", "skipped"}:
        return
    slot = destination["slot"].lower()
    target[f"player_{slot}"] = deepcopy(player)
    target[f"source_{slot}"] = None
    target.get("source_refs", {}).pop(destination["slot"], None)
    if target.get("player_a") and target.get("player_b"):
        target["status"] = "pending"


def _settle_byes(tournament: dict):
    matches = _all_matches(tournament)
    by_id = {match["id"]: match for match in matches}
    changed = True
    while changed:
        changed = False
        for match in matches:
            refs = match.get("source_refs", {})
            for slot, ref in list(refs.items()):
                source = by_id.get(ref["match_id"])
                if source and source.get("status") in {"completed", "skipped"}:
                    refs.pop(slot, None)
                    changed = True
            if match.get("status") == "bye":
                player = match.get("player_a") or match.get("player_b")
                match.update(status="completed", winner_id=player["player_id"], result={"bye": True})
                _put_player(tournament, match.get("winner_to"), player)
                changed = True
            elif match.get("status") in {"waiting", "pending"} and not refs:
                a, b = match.get("player_a"), match.get("player_b")
                if a and b:
                    match["status"] = "pending"
                elif a or b:
                    match.update(status="bye", winner_id=(a or b)["player_id"], result={"bye": True})
                    changed = True
                else:
                    match["status"] = "skipped"
                    changed = True


def _single_elimination(participants: list[dict], new_id) -> list[dict]:
    size = _next_power_of_two(len(participants))
    slots = participants + [None] * (size - len(participants))
    rounds = []
    for round_index in range(int(log2(size))):
        matches = []
        count = size >> (round_index + 1)
        for index in range(count):
            if round_index == 0:
                a, b = slots[index * 2:index * 2 + 2]
                match = _new_match(index + 1, a, b, new_id=new_id)
            else:
                previous = rounds[-1]["matches"]
                match = _new_match(index + 1,
                    source_a=f"Thắng trận {previous[index * 2]['number']} vòng {round_index}",
                    source_b=f"Thắng trận {previous[index * 2 + 1]['number']} vòng {round_index}", new_id=new_id)
            match["bracket"] = "main"
            matches.append(match)
        rounds.append({"name": f"Vòng {round_index + 1}", "bracket": "main", "matches": matches})
    for round_index, round_data in enumerate(rounds[:-1]):
        for index, match in enumerate(round_data["matches"]):
            _link(match, rounds[round_index + 1]["matches"][index // 2], "winner",
                  "A" if index % 2 == 0 else "B", f"Thắng trận {match['number']} vòng {round_index + 1}")
    return rounds


def _round_robin(participants: list[dict], new_id) -> list[dict]:
    teams = list(participants)
    if len(teams) % 2:
        teams.append(None)
    rounds = []
    for round_index in range(len(teams) - 1):
        matches, bye_player = [], None
        for index in range(len(teams) // 2):
            a, b = teams[index], teams[-1 - index]
            if a is None or b is None:
                bye_player = b or a
                continue
            match = _new_match(len(matches) + 1, a, b, new_id=new_id)
            match["bracket"] = "round_robin"
            matches.append(match)
        rounds.append({"name": f"Vòng {round_index + 1}", "bracket": "round_robin",
                       "matches": matches, "bye_player": bye_player})
        teams = [teams[0], teams[-1], *teams[1:-1]]
    return rounds


def _double_elimination(participants: list[dict], new_id) -> list[dict]:
    winners = _single_elimination(participants, new_id)
    for round_data in winners:
        round_data["bracket"] = "winners"
        for match in round_data["matches"]:
            match["bracket"] = "winners"
    size = _next_power_of_two(len(participants))
    width = int(log2(size))
    losers = []
    # The lower bracket alternates elimination rounds and drop-in rounds.
    counts = [max(1, size // (2 ** (i // 2 + 2))) for i in range(2 * (width - 1))]
    for round_index, count in enumerate(counts):
        matches = [_new_match(index + 1, source_a="Đang chờ nhánh trước",
                              source_b="Đang chờ nhánh trước", new_id=new_id)
                   for index in range(count)]
        for match in matches:
            match["bracket"] = "losers"
        losers.append({"name": f"Nhánh thua {round_index + 1}", "bracket": "losers", "matches": matches})

    if losers:
        # Round one receives pairs of losers from winners round one.
        for index, upper_match in enumerate(winners[0]["matches"]):
            target = losers[0]["matches"][index // 2]
            slot = "A" if index % 2 == 0 else "B"
            _link(upper_match, target, "loser", slot, f"Thua nhánh thắng trận {upper_match['number']}")
        # Odd lower rounds receive upper-bracket drops; even rounds consolidate.
        for index, lower_round in enumerate(losers[:-1]):
            following = losers[index + 1]["matches"]
            if index % 2 == 0:
                for match_index, lower_match in enumerate(lower_round["matches"]):
                    _link(lower_match, following[match_index], "winner", "A",
                          f"Thắng nhánh thua trận {lower_match['number']}")
                winners_index = index // 2 + 1
                if winners_index < len(winners):
                    for drop_index, upper_match in enumerate(winners[winners_index]["matches"]):
                        _link(upper_match, following[drop_index], "loser", "B",
                              f"Thua nhánh thắng trận {upper_match['number']}")
            else:
                for match_index, lower_match in enumerate(lower_round["matches"]):
                    target = following[match_index // 2]
                    slot = "A" if match_index % 2 == 0 else "B"
                    _link(lower_match, target, "winner", slot,
                          f"Thắng nhánh thua trận {lower_match['number']}")

    final = _new_match(1, source_a="Vô địch nhánh thắng", source_b="Vô địch nhánh thua", new_id=new_id)
    final["bracket"] = "final"
    _link(winners[-1]["matches"][0], final, "winner", "A", "Vô địch nhánh thắng")
    if losers:
        _link(losers[-1]["matches"][0], final, "winner", "B", "Vô địch nhánh thua")
    else:
        # In a two-player double elimination, the first winners-bracket loser
        # drops directly into the grand final.
        _link(winners[-1]["matches"][0], final, "loser", "B", "Thua nhánh thắng")
    reset = _new_match(1, source_a="Chờ chung kết đầu", source_b="Chờ chung kết đầu", new_id=new_id)
    reset.update(bracket="final", conditional="losers_bracket_wins", status="skipped")
    final["reset_match_id"] = reset["id"]
    return winners + losers + [
        {"name": "Chung kết tổng", "bracket": "final", "matches": [final]},
        {"name": "Chung kết reset (nếu cần)", "bracket": "final", "matches": [reset]},
    ]


def generate_tournament_draw(tournament: dict, new_id) -> list[dict]:
    participants, fmt = tournament["participants"], tournament["format"]
    if fmt == "single_elimination":
        rounds = _single_elimination(participants, new_id)
    elif fmt == "round_robin":
        rounds = _round_robin(participants, new_id)
    elif fmt == "double_elimination":
        rounds = _double_elimination(participants, new_id)
    else:
        raise ValueError(f"Thể thức giải không được hỗ trợ: {fmt}")
    if fmt != "round_robin":
        tournament["rounds"] = rounds
        _settle_byes(tournament)
    return rounds


def apply_match_result(tournament: dict, tournament_match_id: str, game_match: dict) -> bool:
    match = next((m for m in _all_matches(tournament) if m["id"] == tournament_match_id), None)
    if not match or match.get("status") == "completed":
        return False
    match["match_id"] = game_match["id"]
    match["result"] = deepcopy(game_match.get("result"))
    match["match_status"] = game_match.get("status")
    side = (game_match.get("result") or {}).get("winner")
    is_round_robin = match.get("bracket") == "round_robin"
    if game_match.get("status") != "completed" or (side not in {"A", "B"} and not is_round_robin):
        match["status"] = "needs_attention"
        return True
    if is_round_robin and side not in {"A", "B"}:
        match.update(status="completed", winner_id=None, loser_id=None)
    else:
        players = game_match.get("participants") or {}
        winner = players.get(side) or {}
        loser = players.get("B" if side == "A" else "A") or {}
        match.update(winner_id=winner.get("id"), loser_id=loser.get("id"), status="completed")
        player_winner = match.get(f"player_{side.lower()}") or {
            "player_id": winner.get("id"), "nickname": winner.get("name", "Player")}
        player_loser = match.get(f"player_{'b' if side == 'A' else 'a'}") or {
            "player_id": loser.get("id"), "nickname": loser.get("name", "Player")}
        _put_player(tournament, match.get("winner_to"), player_winner)
        _put_player(tournament, match.get("loser_to"), player_loser)
        reset_id = match.get("reset_match_id")
        if reset_id:
            reset = next((m for m in _all_matches(tournament) if m["id"] == reset_id), None)
            if reset:
                if side == "B":
                    reset["player_a"] = deepcopy(match.get("player_a"))
                    reset["player_b"] = deepcopy(match.get("player_b"))
                    reset.update(status="pending", source_a=None, source_b=None)
                else:
                    reset["status"] = "skipped"
    _settle_byes(tournament)
    matches = _all_matches(tournament)
    if matches and all(m.get("status") in {"completed", "skipped"} for m in matches):
        tournament["status"] = "completed"
        final_matches = [m for m in matches if m.get("bracket") == "final"]
        if tournament.get("format") == "round_robin":
            standings = tournament_standings(tournament)
            tournament["winner_id"] = standings[0]["player_id"] if standings else None
        else:
            champion_matches = final_matches or [m for m in matches if not m.get("winner_to")]
            tournament["winner_id"] = next((m.get("winner_id") for m in reversed(champion_matches)
                                             if m.get("status") == "completed" and m.get("winner_id")), None)
    return True


def tournament_standings(tournament: dict) -> list[dict]:
    rows = {p["player_id"]: {"player_id": p["player_id"], "nickname": p["nickname"],
                             "played": 0, "wins": 0, "draws": 0, "losses": 0, "points": 0,
                             "head_to_head": 0, "score_difference": 0}
            for p in tournament.get("participants", [])}
    completed_matches = []
    for match in _all_matches(tournament):
        if match.get("bracket") != "round_robin" or match.get("status") != "completed" or not match.get("match_id"):
            continue
        a, b = match.get("player_a") or {}, match.get("player_b") or {}
        aid, bid = a.get("player_id"), b.get("player_id")
        if aid not in rows or bid not in rows:
            continue
        completed_matches.append((match, aid, bid))
        rows[aid]["played"] += 1; rows[bid]["played"] += 1
        if match.get("winner_id") == aid:
            rows[aid]["wins"] += 1; rows[aid]["points"] += 3; rows[bid]["losses"] += 1
        elif match.get("winner_id") == bid:
            rows[bid]["wins"] += 1; rows[bid]["points"] += 3; rows[aid]["losses"] += 1
        else:
            rows[aid]["draws"] += 1; rows[bid]["draws"] += 1
            rows[aid]["points"] += 1; rows[bid]["points"] += 1

        # Scores are optional so older matches and games without a score map
        # remain compatible. Forfeits intentionally have no fabricated score.
        scores = (match.get("result") or {}).get("scores") or {}
        score_a, score_b = scores.get("A"), scores.get("B")
        if (isinstance(score_a, (int, float)) and not isinstance(score_a, bool)
                and isinstance(score_b, (int, float)) and not isinstance(score_b, bool)):
            rows[aid]["score_difference"] += score_a - score_b
            rows[bid]["score_difference"] += score_b - score_a

    # Head-to-head points are calculated only within each group tied on total
    # points, as required by the tournament tie-break policy.
    point_groups: dict[int, list[str]] = {}
    for player_id, row in rows.items():
        point_groups.setdefault(row["points"], []).append(player_id)
    for tied_ids in point_groups.values():
        if len(tied_ids) < 2:
            continue
        tied = set(tied_ids)
        for match, aid, bid in completed_matches:
            if aid not in tied or bid not in tied:
                continue
            if match.get("winner_id") == aid:
                rows[aid]["head_to_head"] += 3
            elif match.get("winner_id") == bid:
                rows[bid]["head_to_head"] += 3
            else:
                rows[aid]["head_to_head"] += 1
                rows[bid]["head_to_head"] += 1

    standings = sorted(rows.values(), key=lambda row: (
        -row["points"], -row["head_to_head"], -row["score_difference"],
        -row["wins"], row["nickname"].casefold(), row["player_id"]))
    rank = 0
    previous_key = None
    for position, row in enumerate(standings, start=1):
        tie_key = (row["points"], row["head_to_head"], row["score_difference"], row["wins"])
        if tie_key != previous_key:
            rank = position
            previous_key = tie_key
        row["rank"] = rank
    return standings
