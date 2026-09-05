import numpy as np
import pytest

from tennis_ai.geometry import COURT, associate_rackets, attach_poses, calibrate, project
from tennis_ai.pipeline import corrected_records
from tennis_ai.tracking import BallTracker, SceneMonitor, interpolate


def record(t, xy=None, scene=0):
    return {
        "timestamp": t,
        "scene": scene,
        "ball": {
            "status": "observed" if xy is not None else "missing",
            "xy": xy,
            "confidence": 0.9 if xy else None,
        },
    }


def test_interpolation_time_bound_and_unknowns():
    result = list(
        interpolate([record(0, [0, 0]), record(0.03), record(0.09, [9, 0]), record(0.12)])
    )
    assert result[1]["ball"]["status"] == "interpolated"
    assert result[1]["ball"]["xy"] == pytest.approx([3, 0])
    assert result[-1]["ball"]["status"] == "missing"
    result = list(interpolate([record(0, [0, 0]), record(0.05), record(0.101, [10, 0])]))
    assert result[1]["ball"]["status"] == "missing"


def test_interpolation_never_crosses_cut():
    result = list(interpolate([record(0, [0, 0]), record(0.03), record(0.06, [6, 0], scene=1)]))
    assert result[1]["ball"]["status"] == "missing"


def test_missing_stream_is_not_buffered():
    consumed = []

    def stream():
        for i in range(10000):
            consumed.append(i)
            yield record(i / 30)

    iterator = interpolate(stream())
    next(iterator)
    assert len(consumed) == 1


def test_court_roundtrip_and_degenerate_rejection():
    corners = [[80, 25], [240, 25], [40, 160], [280, 160]]
    court = calibrate(corners, (180, 320), manual=True)
    assert court
    assert project(corners, court["matrix"]) == pytest.approx(COURT[:4], abs=1e-4)
    assert calibrate([[5, 5]] * 4, (180, 320), manual=True) is None
    assert calibrate([[float("nan"), 0]] * 14, (180, 320)) is None


def test_pose_matching_is_one_to_one():
    players = [{"box": [0, 0, 50, 100]}, {"box": [0, 0, 50, 100]}]
    poses = [{"box": [0, 0, 50, 100], "pose": [[0, 0, 1]] * 17}]
    attach_poses(players, poses)
    assert sum("pose" in p for p in players) == 1


def test_ambiguous_racket_remains_unassigned():
    pose = [[10, 10, 1]] * 17
    players = [{"id": i, "box": [0, 0, 50, 100], "pose": pose} for i in (1, 2)]
    racket = [{"box": [5, 5, 15, 15]}]
    associate_rackets(players, racket)
    assert racket[0]["player_id"] is None
    associate_rackets(players[:1], racket)
    assert racket[0]["player_id"] == 1


def test_ball_reacquisition():
    tracker = BallTracker()

    def candidate(x):
        return [{"box": [x, 10, x + 2, 12], "confidence": 0.9}]

    assert tracker.update(candidate(10), 0, (180, 320), None)["status"] == "observed"
    assert tracker.update(candidate(280), 0.01, (180, 320), None)["status"] == "missing"
    assert tracker.update(candidate(280), 0.3, (180, 320), None)["status"] == "observed"


def test_scene_cut():
    monitor = SceneMonitor()
    assert monitor.update(np.zeros((180, 320, 3), np.uint8)) == (False, False)
    assert monitor.update(np.full((180, 320, 3), 255, np.uint8))[0]


def test_manual_calibration_expires_on_motion():
    records = [
        {"frame": i, "scene": 0, "camera_moving": i == 2, "court": None, "players": []}
        for i in range(3)
    ]
    correction = {"court": {"0": [[80, 25], [240, 25], [40, 160], [280, 160]]}}
    fixed = list(corrected_records(records, correction, (180, 320), 4))
    assert fixed[0]["court"] and fixed[1]["court"]
    assert fixed[2]["court"] is None


def test_heatmap_plateau_uses_centre():
    from tennis_ai.models import heatmap_centre

    heatmap = np.zeros((100, 100), dtype=np.float32)
    heatmap[30:51, 40:61] = 1
    assert heatmap_centre(heatmap) == pytest.approx([50, 40])
    assert heatmap_centre(np.zeros_like(heatmap)) is None
