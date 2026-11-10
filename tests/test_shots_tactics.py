import json
import subprocess
import sys
from pathlib import Path

import pytest

from tennis_ai.evidence import load_evidence
from tennis_ai.shots import classify, derive_shots, normalize
from tennis_ai.tactics import court_map, parse_filters, tendency, wilson

FIXTURE = Path(__file__).resolve().parents[1] / "contracts/fixtures/v3/full"


def event(kind, ident, time, **extra):
    base = {
        "id": ident,
        "kind": kind,
        "start": time,
        "end": time,
        "scene": 0,
        "player_id": None,
        "stroke": "unknown",
        "position": None,
        "provenance": "manual",
        "reviewed": True,
        "confidence": None,
        "excluded": False,
        "favorite": False,
    }
    return base | extra


def match():
    """Two points: I (near, track 1) serve wide from deuce; the opponent (far, track 2) returns."""
    events, links, rallies = [], [], []
    returns = ([8.5, 20.0], [8.0, 21.0])  # Far player's cross-court returns, court metres.
    for n, target in enumerate(returns):
        t = 10.0 * n
        events += [
            event(
                "hit",
                f"s{n}",
                t + 1,
                player_id=1,
                stroke="serve",
                hitter_position_court_m=[6.5, 24.0],
            ),
            event("bounce", f"sb{n}", t + 1.6, position=[1.8, 7.0]),
            event("hit", f"r{n}", t + 2.2, player_id=2, stroke="forehand"),
            event("bounce", f"rb{n}", t + 3.0, position=target),
        ]
        links += [
            {
                "id": f"ls{n}",
                "shot_id": f"s{n}",
                "bounce_id": f"sb{n}",
                "reviewed": True,
                "confidence": None,
            },
            {
                "id": f"lr{n}",
                "shot_id": f"r{n}",
                "bounce_id": f"rb{n}",
                "reviewed": n == 0,
                "confidence": None,
            },
        ]
        rallies.append(
            {
                "id": f"p{n}",
                "start": t + 1,
                "end": t + 3,
                "shot_ids": [f"s{n}", f"r{n}"],
                "reviewed": True,
            }
        )
    side = {"scene": 0, "start": 0, "end": 60, "reviewed": True, "confidence": None}
    return {
        "events": {
            "schema_version": 3,
            "events": events,
            "participants": [
                {"id": "me", "name": "Me", "role": "self"},
                {"id": "opp", "name": "Opponent", "role": "opponent"},
            ],
            "assignments": [
                side | {"id": "a1", "track_id": 1, "side": "near", "participant_id": "me"},
                side | {"id": "a2", "track_id": 2, "side": "far", "participant_id": "opp"},
            ],
            "links": links,
        },
        "rallies": {"schema_version": 1, "rallies": rallies},
        "tracks": [
            {
                "timestamp": 2.0,
                "scene": 0,
                "track_id": 2,
                "position_court_m": [2.0, -0.5],
                "reviewed": True,
            },
            {
                "timestamp": 12.3,
                "scene": 0,
                "track_id": 2,
                "position_court_m": [2.2, -0.4],
                "reviewed": False,
            },
        ],
    }


def test_shot_paths_roles_and_serve_return_tendency():
    document = derive_shots(match(), handedness={"opp": "right"})
    shots = {s["id"]: s for s in document["shots"]}
    serve, reply = shots["s0"], shots["r0"]
    assert (serve["role"], serve["serve_side"], serve["direction"]) == ("serve", "deuce", "wide")
    assert serve["landing_in"] is True and serve["hitter_position_source"] == "event"
    assert (reply["role"], reply["incoming_shot_id"], reply["ordinal"]) == ("return", "s0", 2)
    assert reply["participant_id"] == "opp" and reply["hitter_position_source"] == "track"
    # The far player is rotated to the bottom: stored facts stay in the package frame.
    assert reply["landing_court_m"] == [8.5, 20.0]
    assert reply["landing_normalized_m"] == [2.47, 3.77]
    assert (reply["direction"], reply["depth"], reply["width"]) == ("cross_court", "mid", "left")
    assert "link:lr0" in reply["support_refs"] and "rally:p0" in reply["support_refs"]

    result = tendency(
        document,
        participant_id="opp",
        where={"role": "return"},
        incoming={"serve_side": "deuce", "direction": "wide"},
    )
    assert result["sample_count"] == 2 and result["support"] == "limited"
    row = result["distributions"]["direction"][0]
    assert (row["value"], row["count"], row["share"]) == ("cross_court", 2, 1.0)
    assert row["interval_95"][0] < 0.5  # Two shots prove very little.
    assert row["shot_ids"] == ["r0", "r1"]
    assert (
        tendency(document, participant_id="opp", incoming={"serve_side": "ad"})["sample_count"] == 0
    )
    image = court_map(result, "Opponent return")
    assert image.ndim == 3 and image.std() > 0


def test_verified_view_drops_unreviewed_evidence_instead_of_guessing():
    document = derive_shots(match(), view="human_verified")
    shots = {s["id"]: s for s in document["shots"]}
    assert shots["r0"]["landing_court_m"] == [8.5, 20.0]
    # Unreviewed link and unreviewed track sample: both ends stay null.
    assert shots["r1"]["landing_court_m"] is None and shots["r1"]["direction"] is None
    assert shots["r1"]["hitter_position_court_m"] is None
    result = tendency(document, participant_id="opp", where={"role": "return"})
    assert result["sample_count"] == 1 and result["exclusions"] == {"r1": "missing_landing"}
    bundle = match()
    bundle["events"]["events"][2]["reviewed"] = False
    document = derive_shots(bundle, view="human_verified")
    assert document["exclusions"] == {"r0": "unreviewed"}
    # A rally with an ineligible shot gives no serve/return context to the rest.
    assert next(s for s in document["shots"] if s["id"] == "s0")["rally_id"] is None


def test_geometry_rules():
    assert normalize([1.0, 2.0], "far") == [9.97, 21.77]
    assert normalize([1.0, 2.0], None) is None
    ad_t = classify("serve", "serve", [4.0, 24.0], [5.8, 6.0])
    assert (ad_t["serve_side"], ad_t["direction"], ad_t["landing_in"]) == ("ad", "t", True)
    fault = classify("serve", "serve", [4.0, 24.0], [3.0, 6.0])
    assert fault["landing_in"] is False and fault["direction"] is None
    # Right-hander's forehand from the backhand corner, hit diagonally.
    assert (
        classify("rally", "forehand", [2.0, 23.0], [8.5, 2.0], "right")["direction"] == "inside_out"
    )
    assert classify("rally", "forehand", [2.0, 23.0], [8.5, 2.0])["direction"] == "cross_court"
    assert (
        classify("rally", "backhand", [2.0, 23.0], [2.0, 1.0], "right")["direction"]
        == "down_the_line"
    )
    long = classify("rally", "unknown", [5.0, 23.0], [5.4, -0.5])
    assert (long["depth"], long["landing_in"], long["direction"]) == ("long", False, "middle")
    netted = classify("rally", "unknown", [5.0, 23.0], [5.0, 13.0])
    assert (netted["depth"], netted["direction"]) == ("own_side", None)
    assert classify("rally", "unknown", None, [2.0, 1.0])["direction"] is None
    assert wilson(0, 0) is None and wilson(5, 10) == [0.2366, 0.7634]
    with pytest.raises(ValueError):
        parse_filters(["speed=fast"])
    with pytest.raises(ValueError):
        derive_shots(match(), handedness={"opp": "both"})


def test_cli_derives_from_a_shared_fixture(tmp_path):
    document = derive_shots(load_evidence(FIXTURE), view="human_verified")
    assert [s["id"] for s in document["shots"]] == ["shot-1"]
    assert document["shots"][0]["landing_court_m"] == [5, 17]
    output, picture = tmp_path / "tendency.json", tmp_path / "map.png"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "tennis_ai.cli",
            "tendency",
            str(FIXTURE),
            "--participant",
            "self",
            "--output",
            str(output),
            "--map",
            str(picture),
        ],
        check=True,
    )
    assert json.loads(output.read_text())["sample_count"] == 1
    assert picture.stat().st_size > 1000
