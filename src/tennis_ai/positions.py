"""Ground-point estimates; airborne ball pixels never enter this projection."""

import math


def footpoint(player):
    pose = player.get("pose") or []
    ankles = [
        p[:2]
        for p in pose[15:17]
        if len(p) >= 3 and p[2] >= 0.6 and all(math.isfinite(v) for v in p)
    ]
    if len(ankles) == 2:
        return [sum(p[i] for p in ankles) / 2 for i in (0, 1)], "ankles_homography"
    x1, _, x2, bottom = player["box"]
    return [(x1 + x2) / 2, bottom], "box_bottom_homography"


def player_position(player, record, side="unknown", role_state="candidate"):
    image, method = footpoint(player)
    quality = record.get("quality") or {}
    court = record.get("court")
    position = None
    if court and quality.get("eligible_for_positions") and quality.get("calibration_id"):
        h = court["matrix"]
        if len(h) == 3 and all(len(row) == 3 and all(math.isfinite(v) for v in row) for row in h):
            x, y = image
            denominator = h[2][0] * x + h[2][1] * y + h[2][2]
            if abs(denominator) > 1e-10:
                projected = [(h[i][0] * x + h[i][1] * y + h[i][2]) / denominator for i in (0, 1)]
                if (
                    all(math.isfinite(v) for v in projected)
                    and -4 <= projected[0] <= 15
                    and -8 <= projected[1] <= 32
                ):
                    position = projected
    return {
        "schema_version": 1,
        "timestamp": record["timestamp"],
        "scene": record["scene"],
        "track_id": player["id"],
        "side": side,
        "position_court_m": position,
        "method": method if position is not None else None,
        "reviewed": False,
        "calibration_id": quality.get("calibration_id") if position is not None else None,
        "image_point_px": image,
        "error_m": None,
        "role_state": role_state,
    }
