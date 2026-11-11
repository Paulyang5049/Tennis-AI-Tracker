"""Court geometry in metres, in the upstream 14-keypoint order."""

import cv2
import numpy as np

# Far left/right, near left/right; singles lines; service lines; centre service line.
COURT = np.array(
    [
        [0, 0],
        [10.97, 0],
        [0, 23.77],
        [10.97, 23.77],
        [1.37, 0],
        [1.37, 23.77],
        [9.60, 0],
        [9.60, 23.77],
        [1.37, 5.485],
        [9.60, 5.485],
        [1.37, 18.285],
        [9.60, 18.285],
        [5.485, 5.485],
        [5.485, 18.285],
    ],
    dtype=np.float32,
)
LINES = [(0, 1), (2, 3), (0, 2), (1, 3), (4, 5), (6, 7), (8, 9), (10, 11), (12, 13)]


def project(points, matrix):
    points = np.asarray(points, dtype=np.float32).reshape(-1, 1, 2)
    return cv2.perspectiveTransform(points, np.asarray(matrix, dtype=np.float64)).reshape(-1, 2)


def calibrate(points, shape, manual=False):
    """Fit image-to-court mapping; reject degenerate and inconsistent fits."""
    pts = np.asarray(points, dtype=np.float32)
    reference = COURT[:4] if len(pts) == 4 else COURT
    if pts.shape != reference.shape:
        raise ValueError("Court requires 4 ordered outer corners or 14 ordered keypoints")
    valid = np.isfinite(pts).all(axis=1)
    if valid.sum() < (4 if manual else 6):
        return None
    # Fit in image space so RANSAC threshold is in pixels.
    inverse, mask = cv2.findHomography(reference[valid], pts[valid], cv2.RANSAC, 6.0)
    if inverse is None or not np.isfinite(inverse).all() or abs(np.linalg.det(inverse)) < 1e-9:
        return None
    corners = project(COURT[[0, 1, 3, 2]], inverse)
    h, w = shape[:2]
    if not cv2.isContourConvex(corners.astype(np.float32)):
        return None
    area = abs(cv2.contourArea(corners))
    if not 0.01 * w * h < area < 4 * w * h:
        return None
    if mask is None or mask.sum() < (4 if manual else 6):
        return None
    inliers = mask.ravel().astype(bool)
    error = np.linalg.norm(project(reference[valid], inverse) - pts[valid], axis=1)
    if float(np.median(error[inliers])) > 6:
        return None
    return {
        "matrix": np.linalg.inv(inverse).tolist(),
        "points": project(COURT, inverse).tolist(),
        "source": "manual" if manual else "model",
        "fit_error_px": float(np.median(error[inliers])),
    }


def ground_point(player):
    pose = player.get("pose")
    if pose:
        ankles = [p[:2] for p in pose[15:17] if p[2] >= 0.4]
        if ankles:
            return np.mean(ankles, axis=0).tolist()
    x1, _, x2, y2 = player["box"]
    return [(x1 + x2) / 2, y2]


def iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / max(union, 1e-9)


def attach_poses(players, poses):
    matches = sorted(
        [
            (iou(p["box"], s["box"]), i, j)
            for i, p in enumerate(players)
            for j, s in enumerate(poses)
        ],
        reverse=True,
    )
    used_p, used_s = set(), set()
    for score, i, j in matches:
        if score >= 0.3 and i not in used_p and j not in used_s:
            players[i]["pose"] = poses[j]["pose"]
            used_p.add(i)
            used_s.add(j)


def associate_rackets(players, rackets):
    for racket in rackets:
        x1, y1, x2, y2 = racket["box"]
        centre = np.array([(x1 + x2) / 2, (y1 + y2) / 2])
        candidates = []
        for player in players:
            height = max(player["box"][3] - player["box"][1], 1)
            for wrist in player.get("pose", [])[9:11]:
                if wrist[2] >= 0.4:
                    candidates.append(
                        (float(np.linalg.norm(centre - wrist[:2])) / height, player["id"])
                    )
        # One candidate per player; ambiguous ownership remains unassigned.
        best: dict[int, float] = {}
        for distance, pid in candidates:
            best[pid] = min(distance, best.get(pid, float("inf")))
        ranked = sorted((d, pid) for pid, d in best.items())
        racket["player_id"] = None
        if (
            ranked
            and ranked[0][0] < 0.6
            and (len(ranked) == 1 or ranked[1][0] - ranked[0][0] > 0.15)
        ):
            racket["player_id"] = ranked[0][1]


def _from_points(points, previous):
    """Court record whose homography maps exactly onto these 14 image points."""
    inverse, _ = cv2.findHomography(COURT, np.asarray(points, dtype=np.float32))
    if inverse is None or not np.isfinite(inverse).all() or abs(np.linalg.det(inverse)) < 1e-9:
        return None
    return {
        **previous,
        "matrix": np.linalg.inv(inverse).tolist(),
        "points": project(COURT, inverse).tolist(),
    }


class CourtSmoother:
    """Opt-in (broadcast-v1) temporal filter for automatic court fits within one shot.

    A fit that agrees with the current court (median keypoint shift <= ``agree_px``)
    is blended in, which removes frame-to-frame jitter on a still camera. A fit that
    disagrees replaces the court only when the next fit confirms it, so one bad fit
    cannot jump the court. While the camera moves every fit is taken as is. A failed
    fit holds the last court for at most ``hold`` seconds of a still camera, and is
    marked ``held``. A cut forgets everything. Manual calibrations pass through.
    """

    version = "broadcast-v1"

    def __init__(self, alpha=0.35, agree_px=8.0, hold=2.0):
        self.alpha, self.agree_px, self.hold = alpha, agree_px, hold
        self.reset()

    def reset(self):
        self.court, self.pending, self.fitted_at = None, None, None

    def snapshot(self):
        return {"court": self.court, "pending": self.pending, "fitted_at": self.fitted_at}

    def restore(self, state):
        self.court, self.pending = state.get("court"), state.get("pending")
        self.fitted_at = state.get("fitted_at")

    @staticmethod
    def shift(a, b):
        return float(np.median(np.linalg.norm(np.subtract(a["points"], b["points"]), axis=1)))

    def update(self, fit, timestamp, cut=False, moving=False):
        if cut:
            self.reset()
        if fit is not None and fit.get("source") == "manual":
            self.court, self.pending, self.fitted_at = fit, None, timestamp
            return fit
        if fit is None:
            if self.court and not moving and timestamp - self.fitted_at <= self.hold:
                return {**self.court, "held": True}
            if moving or (self.fitted_at is not None and timestamp - self.fitted_at > self.hold):
                self.court = None
            return None
        if self.court is None or moving:
            self.court, self.pending = fit, None
        elif self.shift(fit, self.court) <= self.agree_px:
            blended = (1 - self.alpha) * np.asarray(self.court["points"]) + self.alpha * np.asarray(
                fit["points"]
            )
            self.court = _from_points(blended, {**fit, "smoothed": True}) or fit
            self.pending = None
        elif self.pending is not None and self.shift(fit, self.pending) <= self.agree_px:
            self.court, self.pending = fit, None
        else:
            self.pending = fit
        self.fitted_at = timestamp
        return self.court
