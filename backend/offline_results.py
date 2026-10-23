"""Portable, signed, public-only results for disconnected school events.

This archive does not modify SQLite tournament/identity authority, bot artifacts,
Official scores or legacy replay. Sign offline; verify and publish separately
through a CSRF-protected Admin operation when connectivity returns.
"""
import hashlib
import hmac
import json
import os
import re
import threading

from .storage import Store

VERSION = "neon-offline-results-v1"
MAX_BYTES = 1024 * 1024
_lock = threading.RLock()
_SCORE_KEYS = ("rank", "team_name", "played", "wins", "draws", "losses",
               "points", "score_for", "score_difference", "byes", "buchholz")
_SCORE_COUNTS = {"rank", "played", "wins", "draws", "losses", "score_for",
                 "score_difference", "byes", "buchholz"}


class OfflineResultsError(ValueError):
    pass


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _key():
    value = os.environ.get("ARENA_OFFLINE_RESULTS_KEY", "")
    if len(value.encode("utf-8")) < 32:
        raise OfflineResultsError("Admin chưa cấu hình khóa đồng bộ kết quả offline (32+ ký tự).")
    return value.encode("utf-8")


def _source():
    value = os.environ.get("ARENA_OFFLINE_SITE_ID", "")
    if not re.fullmatch(r"[a-zA-Z0-9_-]{3,48}", value):
        raise OfflineResultsError("Cần ARENA_OFFLINE_SITE_ID riêng cho máy tổ chức thi offline.")
    return value


def _text(value, length=128):
    if not isinstance(value, str) or not value.strip() or len(value) > length:
        raise OfflineResultsError("Tên hoặc định danh giải offline không hợp lệ.")
    return value


def _score(row, *, strict=False):
    if not isinstance(row, dict):
        raise OfflineResultsError("Bảng điểm offline không hợp lệ.")
    result = {key: row[key] for key in _SCORE_KEYS if key in row}
    # The internal scorer includes team_id; strip it from public exports.
    # Imported/signed packages must contain ONLY approved public fields.
    if (strict and set(row) != set(result)) or not result.get("team_name"):
        raise OfflineResultsError("Bảng điểm có trường không được công bố.")
    _text(result["team_name"], 128)
    for key, value in result.items():
        if key == "team_name":
            continue
        if type(value) not in (int, float) or (key in _SCORE_COUNTS and type(value) is not int):
            raise OfflineResultsError("Điểm số giải offline không hợp lệ.")
        if key not in ("score_difference",) and value < 0:
            raise OfflineResultsError("Điểm số âm không hợp lệ.")
    return result


def _project(detail):
    if detail.get("status") != "COMPLETED":
        raise OfflineResultsError("Chỉ có thể xuất kết quả giải đã hoàn thành.")
    fixtures = detail.get("fixtures") or []
    if not fixtures or len(fixtures) > 4096 or any(f.get("match_status") != "COMPLETED" for f in fixtures):
        raise OfflineResultsError("Giải còn trận chưa hoàn thành; không thể công bố kết quả.")
    team_names = {t["team_id"]: _text(t["team_name_snapshot"]) for t in detail["teams"]}
    if len(team_names) < 2 or len(team_names) > 128:
        raise OfflineResultsError("Số đội không hợp lệ.")
    def name(team_id):
        return team_names.get(team_id) if team_id is not None else None

    matches = []
    for f in fixtures:
        outcome = f.get("outcome") or {}
        winner = outcome.get("winner_team_id")
        if winner not in (f["team_a_id"], f["team_b_id"], None):
            raise OfflineResultsError("Trận có kết quả không khớp các đội tham gia.")
        matches.append({
            "round": f["round_number"], "stage": f["stage"],
            "team_a": name(f["team_a_id"]), "team_b": name(f["team_b_id"]),
            "winner": name(winner),
        })
    bracket = []
    for slot in detail.get("bracket") or []:
        if slot["status"] not in ("COMPLETED", "BYE", "PENDING") and slot.get("conditional_status") != "SKIPPED":
            raise OfflineResultsError("Nhánh đấu chưa được xác nhận.")
        bracket.append({"round": slot["round_number"], "status": slot["status"],
                        "team_a": name(slot.get("team_a_id")),
                        "team_b": name(slot.get("team_b_id")),
                        "winner": name(slot.get("winner_team_id"))})
    result = {
        "id": _text(detail["id"], 128),
        "name": _text(detail["name"], 128),
        "game_id": _text(detail["game_id"], 64),
        "format": _text(detail["format"], 64),
        "status": "COMPLETED",
        "teams": sorted(team_names.values()),
        "standings": [_score(x) for x in detail.get("standings") or []],
        "groups": [{"name": _text(g["name"]), "standings": [_score(x) for x in g["standings"]]}
                   for g in detail.get("groups") or []],
        "matches": matches,
        "bracket": bracket,
    }
    return result


def _validate(payload):
    if not isinstance(payload, dict) or set(payload) != {"version", "source", "tournament"}:
        raise OfflineResultsError("Gói kết quả không đúng định dạng.")
    if payload["version"] != VERSION or not re.fullmatch(r"[a-zA-Z0-9_-]{3,48}", str(payload["source"])):
        raise OfflineResultsError("Phiên bản hoặc mã điểm thi không hợp lệ.")
    tournament = payload["tournament"]
    fields = {"id", "name", "game_id", "format", "status", "teams", "standings",
              "groups", "matches", "bracket"}
    if not isinstance(tournament, dict) or set(tournament) != fields:
        raise OfflineResultsError("Thiếu dữ liệu giải đấu.")
    for key in ("id", "name", "game_id", "format"):
        _text(tournament[key], 128)
    if tournament["status"] != "COMPLETED":
        raise OfflineResultsError("Chỉ nhận giải đã kết thúc.")
    if not isinstance(tournament["teams"], list) or not 2 <= len(tournament["teams"]) <= 128:
        raise OfflineResultsError("Danh sách đội không hợp lệ.")
    for team in tournament["teams"]:
        _text(team)
    for key, maximum in (("standings", 128), ("groups", 64), ("matches", 4096), ("bracket", 4096)):
        if not isinstance(tournament[key], list) or len(tournament[key]) > maximum:
            raise OfflineResultsError("Gói kết quả vượt giới hạn.")
    for score in tournament["standings"]:
        _score(score, strict=True)
    for group in tournament["groups"]:
        if not isinstance(group, dict) or set(group) != {"name", "standings"}:
            raise OfflineResultsError("Bảng đấu sai định dạng.")
        _text(group["name"])
        if not isinstance(group["standings"], list) or len(group["standings"]) > 128:
            raise OfflineResultsError("Bảng điểm nhóm không hợp lệ.")
        for score in group["standings"]:
            _score(score, strict=True)
    for key, names in (("matches", {"round","stage","team_a","team_b","winner"}),
                       ("bracket", {"round","status","team_a","team_b","winner"})):
        for row in tournament[key]:
            if not isinstance(row, dict) or set(row) != names or type(row["round"]) is not int or row["round"] < 0:
                raise OfflineResultsError("Dữ liệu trận/nhánh đấu không hợp lệ.")
            _text(row["stage"] if key == "matches" else row["status"], 64)
            for side in ("team_a", "team_b", "winner"):
                if row[side] is not None:
                    _text(row[side])
    if not tournament["matches"]:
        raise OfflineResultsError("Gói giải đấu không có trận hoàn tất.")
    return payload


def export_package(detail):
    payload = _validate({"version": VERSION, "source": _source(),
                         "tournament": _project(detail)})
    raw = _canonical(payload)
    if len(raw) > MAX_BYTES:
        raise OfflineResultsError("Giải đấu vượt kích thước gói xuất cho phép.")
    return {"payload": payload, "signature": hmac.new(_key(), raw, hashlib.sha256).hexdigest()}


def verify_package(package):
    if not isinstance(package, dict) or set(package) != {"payload", "signature"}:
        raise OfflineResultsError("Gói kết quả không có chữ ký hợp lệ.")
    raw = _canonical(package["payload"])
    if len(raw) > MAX_BYTES or not re.fullmatch(r"[a-f0-9]{64}", str(package["signature"])):
        raise OfflineResultsError("Gói kết quả vượt giới hạn hoặc sai chữ ký.")
    expected = hmac.new(_key(), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, package["signature"]):
        raise OfflineResultsError("Chữ ký không hợp lệ. Không nhập dữ liệu.")
    return _validate(package["payload"])


def preview(package):
    payload = verify_package(package)
    t = payload["tournament"]
    return {"source": payload["source"], "tournament_id": t["id"],
            "name": t["name"], "game_id": t["game_id"], "format": t["format"],
            "teams": len(t["teams"]), "matches": len(t["matches"]),
            "status": t["status"]}


def _archive_path(store):
    return store.data / "offline_publications.json"


def imported_results(store):
    path = _archive_path(store)
    if not path.exists():
        return []
    data = Store._read(path, {})
    if not isinstance(data, dict):
        raise OfflineResultsError("Kho kết quả đã nhập bị hỏng.")
    return [item["tournament"] | {"source": item["source"], "offline": True}
            for _, item in sorted(data.items(), reverse=True)]


def publish_import(store, package):
    summary = preview(package)
    payload = package["payload"]
    record_key = summary["source"] + ":" + summary["tournament_id"]
    with _lock:
        path = _archive_path(store)
        existing = Store._read(path, {})
        if not isinstance(existing, dict):
            raise OfflineResultsError("Kho kết quả đã nhập bị hỏng.")
        if record_key in existing:
            if existing[record_key] != payload:
                raise OfflineResultsError("Giải này đã được công bố với dữ liệu khác.")
            return {**summary, "already_imported": True}
        if len(existing) >= 100:
            raise OfflineResultsError("Kho kết quả công bố đã đầy.")
        existing[record_key] = payload
        Store._write(path, existing)
    return {**summary, "already_imported": False}
