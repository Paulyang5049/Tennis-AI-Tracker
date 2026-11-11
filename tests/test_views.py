import json

import pytest

from tennis_ai.events import generate_candidates, regenerate_events
from tennis_ai.pipeline import Settings
from tennis_ai.views import event_frames, main_view_flags, view_summary


def frame(index, court=True, ball=None):
    return {
        "schema_version": 2,
        "frame": index,
        "timestamp": index / 10,
        "scene": 0,
        "cut": False,
        "camera_moving": False,
        "court": {"matrix": [[1, 0, 0], [0, 1, 0], [0, 0, 1]]} if court else None,
        "players": [{"id": 1, "box": [0, 0, 10, 10], "confidence": 0.9}],
        "rackets": [],
        "ball_candidates": [],
        "ball": {"status": "observed", "xy": ball, "confidence": 0.8}
        if ball
        else {"status": "missing", "xy": None, "confidence": None},
    }


def test_short_calibration_gaps_are_bridged_and_blinks_are_dropped():
    court = [True] * 15 + [False] * 3 + [True] * 15 + [False] * 20 + [True] * 4 + [False] * 10
    flags = main_view_flags((i / 10, c) for i, c in enumerate(court))
    assert flags[:33] == [True] * 33  # 0.3 s without a court inside the main view
    assert not any(flags[33:])  # 0.4 s of court between cutaways is not a playable view
    assert main_view_flags([]) == []
    assert main_view_flags([(0.0, False), (0.1, True)]) == [False, False]


def test_filter_blanks_cutaways_and_restarts_continuity(tmp_path):
    path = tmp_path / "frames.jsonl"
    court = [True] * 20 + [False] * 20 + [True] * 20
    rows = [frame(i, c, [100 + i, 200]) for i, c in enumerate(court)]
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    assert list(event_frames(path)) == rows
    filtered = list(event_frames(path, "main-view-v1"))
    assert filtered[:20] == rows[:20]
    cutaway = filtered[25]
    assert cutaway["ball"]["status"] == "missing" and cutaway["players"] == [] and cutaway["cut"]
    assert cutaway["timestamp"] == rows[25]["timestamp"]
    assert filtered[40]["cut"] is True and filtered[40]["ball"] == rows[40]["ball"]
    assert filtered[41] == rows[41]
    summary = view_summary(path)
    assert (summary["main_view_frames"], summary["main_view_segments"]) == (40, 2)
    with pytest.raises(ValueError):
        list(event_frames(path, "other"))
    with pytest.raises(ValueError):
        Settings(view_filter="other")
    assert Settings(view_filter="main-view-v1").view_filter == "main-view-v1"


def test_a_turn_seen_only_in_a_cutaway_is_not_a_candidate(tmp_path):
    def turn(start, court):
        # The ball drops, then rises: the baseline detector's trajectory-turn cue.
        ys = [300, 340, 380, 420, 380, 340, 300]
        return [frame(start + i, court, [100, y]) for i, y in enumerate(ys)]

    rows = [frame(i) for i in range(15)] + turn(15, False) + [frame(22 + i) for i in range(15)]
    path = tmp_path / "frames.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    unfiltered = list(generate_candidates(event_frames(path)))
    assert unfiltered, "the synthetic turn should produce a candidate without the filter"
    assert list(generate_candidates(event_frames(path, "main-view-v1"))) == []
    events = regenerate_events(path, tmp_path / "events.json", view_filter="main-view-v1")
    assert events["events"] == []
