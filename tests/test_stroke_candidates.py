import json

import pytest
from test_contact_candidates import GAP_AT_CONTACT, rows

from tennis_ai.events import annotate_strokes, new_event, regenerate_events
from tennis_ai.pipeline import Settings

BOX = [900, 800, 1000, 1000]  # 200 px tall, centred at x=950; shoulders at y=840


def player(side, wrist_x, wrist_y=880, court_y=24.0, player_id=1):
    points = [[950, 850, 0.9] for _ in range(17)]
    points[5] = [930, 840, 0.9]
    points[6] = [970, 840, 0.9]
    points[9] = [wrist_x, wrist_y, 0.9]
    points[10] = [wrist_x, wrist_y, 0.9]
    return {
        "id": player_id,
        "box": BOX,
        "pose": points,
        "side": side,
        "court_position": None if court_y is None else {"position_court_m": [5.0, court_y]},
    }


def frames(side="near", ball_x=1050, early_x=1000, late_x=900, wrist_y=880, court_y=24.0):
    """A hit at t=1.0: the ball arrives at ball_x and the wrists swing from early_x to late_x."""
    result = []
    for index in range(10, 40):
        timestamp = index / 25
        dt = timestamp - 1.0
        wrist = early_x if dt < 0 else late_x
        result.append(
            {
                "frame": index,
                "timestamp": timestamp,
                "scene": 0,
                "players": [player(side, wrist, wrist_y, court_y)],
                "ball": {"status": "observed", "xy": [ball_x, 900]}
                if -0.25 <= dt <= 0
                else {"status": "missing", "xy": None},
            }
        )
    return result


def stroke(sequence, *context, **event):
    hit = new_event("hit", 1.0, frame=25, player_id=1, **event)
    found = annotate_strokes([*context, hit], sequence)
    return next(e for e in found if e["id"] == hit["id"])["stroke"]


def test_incoming_ball_and_swing_direction_give_forehand_or_backhand():
    # Near player seen from behind: the player's right is the image's right.
    assert stroke(frames()) == "forehand"
    assert stroke(frames(ball_x=850, early_x=900, late_x=1000)) == "backhand"
    # Far player faces the camera, so the same image side is the other hand.
    assert stroke(frames("far", court_y=0.0)) == "backhand"
    assert stroke(frames("far", ball_x=850, early_x=900, late_x=1000, court_y=0.0)) == "forehand"


def test_contradicting_or_weak_side_cues_stay_unknown():
    assert stroke(frames(ball_x=1050, early_x=900, late_x=1000)) == "unknown"
    assert stroke(frames(ball_x=960, early_x=955, late_x=950)) == "unknown"
    assert stroke(frames(side=None, court_y=None)) == "unknown"  # no side or court position
    assert stroke(frames(side=None)) == "forehand"  # the court position gives the side


def test_raised_wrist_at_an_opening_hit_is_a_serve():
    serve = frames(wrist_y=780)  # 0.3 player heights above the shoulders
    assert stroke(serve) == "serve"
    returned = new_event("hit", 0.2, frame=5, player_id=2)
    # An overhead after the opponent's shot may be a smash or a high volley.
    assert stroke(serve, returned) == "unknown"
    # A serve is struck behind the baseline, not near the net.
    assert stroke(frames(wrist_y=780, court_y=16.0)) == "unknown"


def test_a_return_near_the_net_without_a_bounce_is_a_volley():
    returned = new_event("hit", 0.2, frame=5, player_id=2)
    assert stroke(frames(court_y=16.0), returned) == "volley"
    bounce = new_event("bounce", 0.6, frame=15)
    assert stroke(frames(court_y=16.0), returned, bounce) == "forehand"
    assert stroke(frames(court_y=24.0), returned) == "forehand"


def test_reviewed_and_manual_hits_are_never_changed():
    assert stroke(frames(), reviewed=True) == "unknown"
    assert stroke(frames(), provenance="manual", stroke="backhand") == "backhand"


def test_unknown_stroke_detectors_are_rejected():
    with pytest.raises(ValueError):
        annotate_strokes([], [], "unversioned")
    with pytest.raises(ValueError):
        Settings(stroke_detector="unversioned")
    assert Settings().stroke_detector is None


def test_regeneration_applies_the_selected_stroke_detector(tmp_path):
    path = tmp_path / "frames.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows(GAP_AT_CONTACT)))
    document = regenerate_events(
        path, tmp_path / "events.json", detector="contact-v2", stroke_detector="stroke-v1"
    )
    # Synthetic tracks carry no pose, side or court position, so the rule abstains.
    assert [e["stroke"] for e in document["events"] if e["kind"] == "hit"] == ["unknown"]
