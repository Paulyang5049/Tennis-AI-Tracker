import json

import pytest

from tennis_ai.geometry import calibrate
from tennis_ai.quality import quality_for_record
from tennis_ai.tracking import create_ball_tracker


def candidate(x, y, confidence=0.9):
    return {"box": [x - 1, y - 1, x + 1, y + 1], "confidence": confidence}


def test_quality_abstains_after_camera_motion_and_stale_calibration():
    court = calibrate([[80, 25], [240, 25], [40, 160], [280, 160]], (180, 320), manual=True)
    record = {"timestamp": 1, "scene": 0, "court": court}
    assert quality_for_record(record, (180, 320))["eligible_for_positions"]
    assert not quality_for_record({**record, "camera_moving": True}, (180, 320))[
        "eligible_for_positions"
    ]
    assert not quality_for_record({**record, "cut": True}, (180, 320))["eligible_for_positions"]
    court["source"] = "model"
    result = quality_for_record(record, (180, 320), calibration_time=-2)
    assert "stale_calibration" in result["reasons"]
    assert not result["eligible_for_positions"]


def test_scoreboard_mask_and_experimental_strategy_remain_explicit():
    baseline = create_ball_tracker("baseline-v1")
    challenger = create_ball_tracker("experimental-motion-v1", masks=[[0, 0, 0.3, 0.2]])
    boxes = [candidate(20, 10, 0.99), candidate(160, 100, 0.7)]
    assert baseline.update(boxes, 0, (180, 320), None)["xy"] == [20, 10]
    assert challenger.update(boxes, 0, (180, 320), None)["xy"] == [160, 100]
    with pytest.raises(ValueError):
        create_ball_tracker("unversioned")


def test_stationary_overlay_suppression_and_resume_match():
    tracker = create_ball_tracker("experimental-motion-v1")
    for i in range(9):
        tracker.update([candidate(10, 10)], i / 30, (180, 320), None)
    state = json.loads(json.dumps(tracker.snapshot()))
    resumed = create_ball_tracker("experimental-motion-v1")
    resumed.restore(state)
    boxes = [candidate(10, 10), candidate(170, 100, 0.7)]
    for i in range(9, 15):
        assert tracker.update(boxes, i / 30, (180, 320), None) == resumed.update(
            boxes, i / 30, (180, 320), None
        )
    assert tracker.update([candidate(10, 10)], 0.5, (180, 320), None)["status"] == "missing"
