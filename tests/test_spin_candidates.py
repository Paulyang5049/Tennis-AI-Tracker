import pytest

from tennis_ai.events import annotate_spin, new_event
from tennis_ai.pipeline import Settings

BOX = [900, 800, 1000, 1000]  # 200 px tall; shoulders at y=840


def pose(wrist_y, conf=0.9):
    points = [[950, 850, 0.9] for _ in range(17)]
    points[5] = [930, 840, conf]
    points[6] = [970, 840, conf]
    points[9] = [920, wrist_y, conf]
    points[10] = [980, 900, 0.1]  # the other wrist is not visible
    return points


def frames(early_y, late_y, hit_time=1.0, player_pose=pose):
    rows = []
    for index in range(20, 34):
        timestamp = index / 25
        wrist = early_y if timestamp - hit_time <= -0.08 else late_y
        rows.append(
            {
                "frame": index,
                "timestamp": timestamp,
                "scene": 0,
                "players": [{"id": 1, "box": BOX, "pose": player_pose(wrist)}],
            }
        )
    return rows


def spin(early_y, late_y, **event):
    hit = new_event("hit", 1.0, frame=25, player_id=1, **event)
    return annotate_spin([hit], frames(early_y, late_y))[0].get("spin")


def test_wrist_swing_direction_suggests_slice_or_topspin():
    assert spin(820, 900) == "slice"  # high to low through contact
    assert spin(940, 820) == "topspin"  # low to high
    assert spin(860, 870) == "unknown"  # too little change to decide


def test_serves_overheads_and_reviewed_or_unattributed_hits_are_left_alone():
    assert spin(660, 900) == "unknown"  # wrist far above the shoulders: serve or overhead
    assert spin(820, 900, reviewed=True) is None
    assert spin(820, 900, provenance="manual") is None
    hit = new_event("hit", 1.0, frame=25)
    assert annotate_spin([hit], frames(820, 900))[0].get("spin") is None
    hidden = annotate_spin(
        [new_event("hit", 1.0, frame=25, player_id=1)],
        frames(820, 900, player_pose=lambda y: pose(y, conf=0.1)),
    )
    assert hidden[0]["spin"] == "unknown"


def test_unknown_spin_detectors_are_rejected():
    with pytest.raises(ValueError):
        annotate_spin([], [], "unversioned")
    with pytest.raises(ValueError):
        Settings(spin_detector="unversioned")
    assert Settings().spin_detector is None
