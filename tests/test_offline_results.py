"""Offline competition packages can be signed on a laptop and imported later."""
import hashlib
import hmac
import os
from copy import deepcopy
from types import SimpleNamespace

import pytest

from backend.offline_results import (
    OfflineResultsError, export_package, imported_results,
    preview, publish_import, verify_package, _canonical,
)


def complete_event():
    return {
        "id": "5eea123abc", "name": "Giải đấu trường",
        "game_id": "ott_v2", "format": "round_robin",
        "status": "COMPLETED",
        "teams": [
            {"team_id": "team-a", "team_name_snapshot": "Đội A"},
            {"team_id": "team-b", "team_name_snapshot": "Đội B"},
        ],
        "standings": [
            {"team_id": "team-a", "team_name": "Đội A", "rank": 1, "played": 1,
             "wins": 1, "draws": 0, "losses": 0, "points": 3,
             "score_for": 4, "score_difference": 2},
            {"team_id": "team-b", "team_name": "Đội B", "rank": 2, "played": 1,
             "wins": 0, "draws": 0, "losses": 1, "points": 0,
             "score_for": 2, "score_difference": -2},
        ],
        "groups": [], "bracket": [],
        "fixtures": [{
            "round_number": 1, "stage": "GROUP",
            "team_a_id": "team-a", "team_b_id": "team-b",
            "match_status": "COMPLETED",
            "outcome": {"winner_team_id": "team-a"},
            "official_request_id": "private-request-id",
            "match_id": "private-match-id",
        }],
    }


@pytest.fixture
def keys(monkeypatch):
    monkeypatch.setenv("ARENA_OFFLINE_SITE_ID", "school-lab-a")
    monkeypatch.setenv("ARENA_OFFLINE_RESULTS_KEY", "private-shared-export-key-" + "x" * 40)


def test_signed_export_import_publication_is_separate_and_idempotent(keys, tmp_path):
    source=complete_event()
    package=export_package(source)
    exported=verify_package(package)
    assert exported["tournament"]["name"] == "Giải đấu trường"
    assert "team_id" not in str(exported)
    assert "private-request-id" not in str(exported)
    assert "private-match-id" not in str(exported)
    assert "source_sha256" not in str(exported)
    mirror=SimpleNamespace(data=tmp_path)
    assert imported_results(mirror)==[]
    first=publish_import(mirror,package)
    second=publish_import(mirror,package)
    assert first["already_imported"] is False
    assert second["already_imported"] is True
    published=imported_results(mirror)
    assert len(published)==1 and published[0]["offline"] is True
    assert published[0]["source"]=="school-lab-a"
    assert published[0]["standings"][0]["team_name"]=="Đội A"
    assert source["fixtures"][0]["match_id"]=="private-match-id"


def test_tampered_package_is_rejected(keys, tmp_path):
    package=export_package(complete_event())
    package["payload"]["tournament"]["standings"][0]["points"]=9000
    with pytest.raises(OfflineResultsError,match="Chữ ký"):
        publish_import(SimpleNamespace(data=tmp_path),package)
    assert imported_results(SimpleNamespace(data=tmp_path))==[]


def test_incomplete_tournament_cannot_be_exported(keys):
    detail=complete_event()
    detail["status"]="ACTIVE"
    with pytest.raises(OfflineResultsError,match="hoàn thành"):
        export_package(detail)
    detail["status"]="COMPLETED"
    detail["fixtures"][0]["match_status"]="INTERRUPTED"
    with pytest.raises(OfflineResultsError,match="chưa hoàn thành"):
        export_package(detail)


def test_original_publication_cannot_be_overwritten(keys,tmp_path):
    initial=export_package(complete_event())
    mirror=SimpleNamespace(data=tmp_path)
    publish_import(mirror,initial)
    changed=complete_event()
    changed["standings"][0]["points"]=9
    with pytest.raises(OfflineResultsError,match="dữ liệu khác"):
        publish_import(mirror,export_package(changed))
    assert imported_results(mirror)[0]["standings"][0]["points"]==3


def test_wrong_shared_key_fails_closed(keys, monkeypatch):
    package=export_package(complete_event())
    monkeypatch.setenv("ARENA_OFFLINE_RESULTS_KEY","different-shared-key-"+"z"*40)
    with pytest.raises(OfflineResultsError,match="Chữ ký"):
        verify_package(package)


def test_missing_credentials_disable_exports(keys,monkeypatch):
    detail=complete_event()
    monkeypatch.delenv("ARENA_OFFLINE_RESULTS_KEY")
    with pytest.raises(OfflineResultsError,match="khóa"):
        export_package(detail)
    monkeypatch.setenv("ARENA_OFFLINE_RESULTS_KEY","x"*40)
    monkeypatch.delenv("ARENA_OFFLINE_SITE_ID")
    with pytest.raises(OfflineResultsError,match="SITE_ID"):
        export_package(detail)


def test_preview_is_read_only(keys,tmp_path):
    archive=SimpleNamespace(data=tmp_path)
    summary=preview(export_package(complete_event()))
    assert summary["teams"]==2 and summary["matches"]==1
    assert not (tmp_path/"offline_publications.json").exists()
    assert imported_results(archive)==[]


def test_schema_rejects_unsigned_injected_fields(keys):
    package=export_package(complete_event())
    body=deepcopy(package)
    body["payload"]["tournament"]["bots"]=[{"source":"private"}]
    with pytest.raises(OfflineResultsError):
        verify_package(body)


def test_signed_invalid_team_and_source_payloads_rejected(keys):
    original = export_package(complete_event())
    for mutate in (
        lambda p: p["payload"]["tournament"]["matches"][0].update(winner="Not a participant"),
        lambda p: p["payload"].update(source=None),
        lambda p: p["payload"]["tournament"]["standings"][0].update(team_name="Other team"),
        lambda p: p["payload"]["tournament"]["matches"][0].update(team_b=None),
    ):
        body = deepcopy(original)
        mutate(body)
        body["signature"] = hmac.new(os.environ["ARENA_OFFLINE_RESULTS_KEY"].encode(),
                                     _canonical(body["payload"]), hashlib.sha256).hexdigest()
        with pytest.raises(OfflineResultsError):
            verify_package(body)


def test_bad_local_results_rejected_before_signature(keys):
    duplicate = complete_event()
    duplicate["teams"][1]["team_name_snapshot"] = "Đội A"
    with pytest.raises(OfflineResultsError, match="duy nhất"):
        export_package(duplicate)

    invalid_pair = complete_event()
    invalid_pair["fixtures"][0]["team_b_id"] = "not-an-entrant"
    with pytest.raises(OfflineResultsError, match="hai đội"):
        export_package(invalid_pair)

    nonfinite = complete_event()
    nonfinite["standings"][0]["points"] = float("inf")
    with pytest.raises(OfflineResultsError, match="hữu hạn"):
        export_package(nonfinite)

    control_char = complete_event()
    control_char["name"] = "Event\nspoofed"
    with pytest.raises(OfflineResultsError):
        export_package(control_char)


def test_malformed_signature_type_fails_as_validation_error(keys):
    package = export_package(complete_event())
    package["signature"] = int("1" * 64)
    with pytest.raises(OfflineResultsError, match="chữ ký"):
        verify_package(package)


def test_unresolved_bracket_cannot_be_exported(keys):
    detail = complete_event()
    detail["bracket"] = [{"round_number": 2, "status": "PENDING",
                          "team_a_id": None, "team_b_id": None}]
    with pytest.raises(OfflineResultsError, match="chưa được xác nhận"):
        export_package(detail)


@pytest.mark.parametrize("status,winner", [("PENDING", None), ("SKIPPED", "Đội A")])
def test_signed_unresolved_or_fabricated_skipped_bracket_rejected(keys, status, winner):
    package = export_package(complete_event())
    package["payload"]["tournament"]["bracket"] = [{
        "round": 2, "status": status, "team_a": "Đội A", "team_b": None,
        "winner": winner,
    }]
    package["signature"] = hmac.new(os.environ["ARENA_OFFLINE_RESULTS_KEY"].encode(),
                                    _canonical(package["payload"]), hashlib.sha256).hexdigest()
    with pytest.raises(OfflineResultsError):
        verify_package(package)
