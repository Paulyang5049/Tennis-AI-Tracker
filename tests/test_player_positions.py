from copy import deepcopy

import pytest

from tennis_ai.geometry import calibrate
from tennis_ai.player_tracking import SceneRoles
from tennis_ai.positions import player_position


def frame():
    return {
        "frame": 0,
        "timestamp": 0.0,
        "scene": 0,
        "court": calibrate([[0, 0], [100, 0], [0, 100], [100, 100]], (100, 100), manual=True),
        "quality": {"eligible_for_positions": True, "calibration_id": "fixture-calibration"},
    }


def test_ankles_and_box_fallback_keep_method_and_uncertainty():
    player = {
        "id": 1,
        "box": [30, 50, 50, 80],
        "confidence": 0.9,
        "pose": [[0, 0, 0] for _ in range(17)],
    }
    player["pose"][15:17] = [[38, 75, 0.9], [42, 75, 0.9]]
    result = player_position(player, frame(), "near")
    assert result["position_court_m"] == pytest.approx([4.388, 17.8275], abs=1e-5)
    assert result["method"] == "ankles_homography" and result["error_m"] is None
    player.pop("pose")
    assert player_position(player, frame(), "near")["method"] == "box_bottom_homography"
    invalid = frame()
    invalid["quality"]["eligible_for_positions"] = False
    result = player_position(player, invalid, "near")
    assert result["image_point_px"] == [40, 80] and result["position_court_m"] is None


def test_ambiguous_same_side_abstains_and_scene_reset_drops_context():
    roles = SceneRoles(players=2)
    players = [
        {"id": 1, "box": [30, 55, 50, 80], "confidence": 0.9},
        {"id": 2, "box": [60, 5, 80, 25], "confidence": 0.9},
    ]
    result = roles.update(players, frame())
    assert [p["side"] for p in result] == ["near", "far"]
    crossing = deepcopy(players)
    crossing[1]["box"] = [55, 55, 70, 80]
    assert all(p["side"] == "unknown" for p in roles.update(crossing, frame()))
    next_scene = {**frame(), "scene": 1}
    switched = roles.update(list(reversed(players)), next_scene)
    assert [p["side"] for p in switched] == ["far", "near"]
