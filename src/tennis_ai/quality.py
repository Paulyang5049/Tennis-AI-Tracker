"""Capture eligibility heuristics; these values are not recognition accuracy."""

import hashlib
import json
from typing import Any

import cv2
import numpy as np


def sharpness(image):
    gray = cv2.cvtColor(cv2.resize(image, (320, 180)), cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def quality_for_record(record, shape, calibration_time=None, sharpness_value=None):
    court = record.get("court")
    reasons = []
    visible, identifier, age = False, None, None
    if not court:
        reasons.append("missing_calibration")
    else:
        matrix = np.asarray(court.get("matrix", []), dtype=float)
        points = np.asarray(court.get("points", []), dtype=float)
        valid = (
            matrix.shape == (3, 3)
            and np.isfinite(matrix).all()
            and abs(np.linalg.det(matrix)) > 1e-10
        )
        valid = (
            valid
            and points.ndim == 2
            and points.shape[0] >= 4
            and points.shape[1] == 2
            and np.isfinite(points).all()
        )
        if not valid:
            reasons.append("invalid_calibration")
        else:
            h, w = shape[:2]
            visible = bool(
                (
                    (points[:4, 0] >= 0)
                    & (points[:4, 0] <= w)
                    & (points[:4, 1] >= 0)
                    & (points[:4, 1] <= h)
                ).all()
            )
            if not visible:
                reasons.append("court_out_of_view")
            payload = {"scene": record.get("scene", 0), "matrix": matrix.tolist()}
            identifier = hashlib.sha256(
                json.dumps(payload, sort_keys=True, allow_nan=False).encode()
            ).hexdigest()
            if calibration_time is not None:
                age = max(0, float(record["timestamp"]) - calibration_time)
            elif court.get("source") == "manual":
                age = 0.0  # Fixed-camera manual calibration expires on motion, not elapsed time.
            else:
                age = record.get("quality", {}).get("calibration_age_s")
            if court.get("source") != "manual" and (age is None or age > 2):
                reasons.append("stale_calibration")
    moving, cut = bool(record.get("camera_moving")), bool(record.get("cut"))
    if moving:
        reasons.append("camera_moving")
    if cut:
        reasons.append("scene_cut")
    if sharpness_value is not None and sharpness_value < 15:
        reasons.append("low_sharpness")
    return {
        "schema_version": 1,
        "eligible_for_positions": not reasons,
        "court_visible": visible,
        "camera_moving": moving,
        "scene_cut": cut,
        "calibration_id": identifier,
        "calibration_age_s": age,
        "sharpness": sharpness_value,
        "reasons": reasons,
    }


def summarize_quality(records):
    scenes: dict[int, dict[str, Any]] = {}
    for record in records:
        scene = scenes.setdefault(
            record["scene"], {"frames": 0, "eligible_frames": 0, "reasons": {}}
        )
        scene["frames"] += 1
        quality = record.get("quality", {})
        scene["eligible_frames"] += bool(quality.get("eligible_for_positions"))
        for reason in quality.get("reasons", []):
            scene["reasons"][reason] = scene["reasons"].get(reason, 0) + 1
    return {
        "schema_version": 1,
        "scenes": [{"scene": key, **value} for key, value in sorted(scenes.items())],
        "note": "Capture eligibility heuristics, not accuracy",
    }
