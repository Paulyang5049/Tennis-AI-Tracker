"""Temporal selection with explicit unknowns and bounded interpolation."""

import math
from collections import deque
from typing import Any

import cv2
import numpy as np

from tennis_ai.geometry import project


class BallTracker:
    version = "baseline-v1"

    def __init__(self):
        self.history: deque = deque(maxlen=2)

    def reset(self):
        self.history.clear()

    def snapshot(self):
        return {"version": self.version, "history": list(self.history)}

    def restore(self, state):
        if state.get("version") != self.version:
            raise ValueError("Ball tracker version changed")
        self.reset()
        for timestamp, xy in state["history"]:
            if (
                not math.isfinite(timestamp)
                or len(xy) != 2
                or not all(math.isfinite(v) for v in xy)
            ):
                raise ValueError("Invalid tracker checkpoint")
            self.history.append((timestamp, xy))

    def update(self, candidates, time, shape, court):
        diagonal = float(np.hypot(*shape[:2]))
        if self.history and time - self.history[-1][0] > 0.25:
            self.reset()
        predicted = None
        if self.history:
            predicted = np.array(self.history[-1][1])
            if len(self.history) == 2:
                (t0, p0), (t1, p1) = self.history
                velocity = (np.array(p1) - p0) / max(t1 - t0, 1e-3)
                predicted = predicted + velocity * (time - t1)
        ranked = []
        for candidate in candidates:
            x1, y1, x2, y2 = candidate["box"]
            point = np.array([(x1 + x2) / 2, (y1 + y2) / 2])
            score = candidate["confidence"]
            if predicted is not None:
                distance = float(np.linalg.norm(point - predicted)) / diagonal
                elapsed = time - self.history[-1][0]
                if distance > max(0.08, min(0.35, elapsed * 3)):
                    continue
                score -= 2 * distance
            if court:
                x, y = project([point], court["matrix"])[0]
                if not (-4 < x < 15 and -8 < y < 32):
                    score -= 0.3
            ranked.append((score, candidate, point))
        if not ranked:
            return {"status": "missing", "xy": None, "confidence": None}
        _, candidate, point = max(ranked, key=lambda x: x[0])
        self.history.append((time, point.tolist()))
        return {"status": "observed", "xy": point.tolist(), "confidence": candidate["confidence"]}


class MotionBallChallenger(BallTracker):
    """Opt-in temporal hard-negative experiment. Never selected by default.

    Uses explicit normalized overlay masks and repeated edge detections to suppress
    scoreboard candidates. Missing output remains unknown, not confirmed absence.
    """

    version = "experimental-motion-v1"

    def __init__(self, masks=()):
        super().__init__()
        self.masks = [list(box) for box in masks]
        for box in self.masks:
            if (
                len(box) != 4
                or not all(
                    isinstance(v, (int, float))
                    and not isinstance(v, bool)
                    and math.isfinite(v)
                    and 0 <= v <= 1
                    for v in box
                )
                or box[0] >= box[2]
                or box[1] >= box[3]
            ):
                raise ValueError("Overlay masks must be normalized [left, top, right, bottom]")
        self.repeated = {}

    def reset(self):
        super().reset()
        self.repeated = {}

    def snapshot(self):
        return {**super().snapshot(), "masks": self.masks, "repeated": self.repeated}

    def restore(self, state):
        if state.get("masks") != self.masks:
            raise ValueError("Overlay masks changed")
        super().restore(state)
        self.repeated = state["repeated"]

    def update(self, candidates, time, shape, court):
        h, w = shape[:2]
        self.repeated = {
            key: item for key, item in self.repeated.items() if time - item["last"] <= 0.75
        }
        accepted = []
        for candidate in candidates:
            x1, y1, x2, y2 = candidate["box"]
            x, y = (x1 + x2) / 2, (y1 + y2) / 2
            if any(a <= x / w <= c and b <= y / h <= d for a, b, c, d in self.masks):
                continue
            key = f"{round(x / 3)}:{round(y / 3)}"
            item = self.repeated.setdefault(key, {"first": time, "last": time, "count": 0})
            item["last"] = time
            item["count"] += 1
            edge = y / h < 0.22 and (x / w < 0.3 or x / w > 0.7)
            if edge and item["count"] >= 6 and time - item["first"] >= 0.15:
                continue
            accepted.append(candidate)
        # Bound hard-negative context even if a detector floods the frame with candidates.
        self.repeated = dict(
            sorted(self.repeated.items(), key=lambda item: item[1]["last"], reverse=True)[:256]
        )
        # Reset only motion history after a gap; retain the independent overlay evidence.
        if self.history and time - self.history[-1][0] > 0.25:
            self.history.clear()
        return super().update(accepted, time, shape, court)


def create_ball_tracker(version="baseline-v1", masks=()):
    if version == "baseline-v1":
        if masks:
            raise ValueError("Overlay masks require the explicit experimental tracker")
        return BallTracker()
    if version == "experimental-motion-v1":
        return MotionBallChallenger(masks)
    raise ValueError("Unsupported ball tracker version")


def interpolate(records, max_gap=0.1):
    """Yield records in order; never infer across cuts or unbounded gaps."""
    pending: deque[dict[str, Any]] = deque()
    anchor = None
    for record in records:
        if record.get("cut") or record.get("camera_moving"):
            yield from pending
            pending.clear()
            anchor = None
            yield record
            continue
        if anchor and record["scene"] != anchor["scene"]:
            yield from pending
            pending.clear()
            anchor = None
        ball = record["ball"]
        if ball["status"] == "observed":
            if anchor and pending and record["timestamp"] - anchor["timestamp"] <= max_gap + 1e-9:
                span = record["timestamp"] - anchor["timestamp"]
                for missing in pending:
                    alpha = (missing["timestamp"] - anchor["timestamp"]) / max(span, 1e-9)
                    xy = (1 - alpha) * np.array(anchor["ball"]["xy"]) + alpha * np.array(ball["xy"])
                    missing["ball"] = {
                        "status": "interpolated",
                        "xy": xy.tolist(),
                        "confidence": None,
                    }
            yield from pending
            pending.clear()
            yield record
            anchor = record
        else:
            pending.append(record)
            if (
                anchor is None
                or record["timestamp"] - anchor["timestamp"] > max_gap
                or len(pending) > 120
            ):
                yield from pending
                pending.clear()
                anchor = None
    yield from pending


class SceneMonitor:
    """Detect hard cuts and global camera movement using small grayscale frames."""

    def __init__(self):
        self.previous = None

    def update(self, frame):
        gray = cv2.cvtColor(cv2.resize(frame, (160, 90)), cv2.COLOR_BGR2GRAY)
        cut, moving = False, False
        if self.previous is not None:
            difference = float(np.mean(cv2.absdiff(gray, self.previous))) / 255
            cut = difference > 0.24
            if not cut:
                shift, response = cv2.phaseCorrelate(
                    self.previous.astype(np.float32), gray.astype(np.float32)
                )
                moving = response > 0.15 and np.hypot(shift[0], shift[1]) > 0.6
        self.previous = gray
        return cut, moving
