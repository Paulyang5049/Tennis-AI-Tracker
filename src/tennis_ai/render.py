"""Cached overlays and a ground-plane player map."""

from collections import deque

import cv2
import numpy as np

from tennis_ai.geometry import COURT, LINES, ground_point, project

SKELETON = [
    (5, 6),
    (5, 7),
    (7, 9),
    (6, 8),
    (8, 10),
    (5, 11),
    (6, 12),
    (11, 12),
    (11, 13),
    (13, 15),
    (12, 14),
    (14, 16),
    (0, 1),
    (0, 2),
]
COLORS = [(70, 220, 120), (255, 160, 70), (90, 120, 255), (220, 100, 220)]
DEFAULT_OVERLAYS = ["Ball", "Court", "Players", "Pose", "Rackets", "Mini court"]


def text(image, message, point, color=(255, 255, 255)):
    cv2.putText(
        image,
        message,
        tuple(map(int, point)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        (0, 0, 0),
        3,
        cv2.LINE_AA,
    )
    cv2.putText(
        image, message, tuple(map(int, point)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA
    )


class Renderer:
    def __init__(self, overlays=None):
        self.overlays = set(DEFAULT_OVERLAYS if overlays is None else overlays)
        self.trail: deque = deque(maxlen=240)
        self.scene = None

    def draw(self, frame, record):
        image = frame.copy()
        if record["scene"] != self.scene:
            self.trail.clear()
            self.scene = record["scene"]
        while self.trail and record["timestamp"] - self.trail[0][0] > 1:
            self.trail.popleft()
        ball = record["ball"]
        self.trail.append((record["timestamp"], ball["xy"], ball["status"]))
        court = record.get("court")
        if court and "Court" in self.overlays:
            points = np.rint(court["points"]).astype(int)
            for a, b in LINES:
                cv2.line(image, tuple(points[a]), tuple(points[b]), (240, 220, 50), 2)
            net = np.rint(
                project([[0, 11.885], [10.97, 11.885]], np.linalg.inv(court["matrix"]))
            ).astype(int)
            cv2.line(image, tuple(net[0]), tuple(net[1]), (80, 170, 255), 2)
        for player in record["players"]:
            color = COLORS[player["id"] % len(COLORS)]
            x1, y1, x2, y2 = map(int, player["box"])
            if "Players" in self.overlays:
                cv2.rectangle(image, (x1, y1), (x2, y2), color, 2)
                text(image, player.get("label", f"P{player['id']}"), (x1, max(20, y1 - 8)), color)
            if "Pose" in self.overlays and player.get("pose"):
                pose = player["pose"]
                for a, b in SKELETON:
                    if pose[a][2] > 0.4 and pose[b][2] > 0.4:
                        cv2.line(
                            image,
                            tuple(map(int, pose[a][:2])),
                            tuple(map(int, pose[b][:2])),
                            color,
                            2,
                        )
        if "Rackets" in self.overlays:
            for racket in record["rackets"]:
                x1, y1, x2, y2 = map(int, racket["box"])
                cv2.rectangle(image, (x1, y1), (x2, y2), (210, 100, 255), 2)
                owner = racket.get("player_id")
                text(image, f"Racket / P{owner}" if owner is not None else "Racket / ?", (x1, y1))
        if "Ball" in self.overlays:
            previous = None
            for _, point, status in self.trail:
                if point is None:
                    previous = None
                    continue
                point = tuple(map(int, point))
                color = (0, 200, 255) if status == "interpolated" else (30, 255, 220)
                if previous is not None and status == "observed" and previous[1] == "observed":
                    cv2.line(image, previous[0], point, color, 2)
                cv2.circle(image, point, 4, color, 1 if status == "interpolated" else -1)
                previous = (point, status)
        if "Mini court" in self.overlays and court:
            self.mini_court(image, record)
        text(
            image,
            f"{record['timestamp']:.3f}s  Scene {record['scene']}  Ball: {ball['status']}",
            (12, 24),
        )
        if not court:
            text(
                image, "Court not calibrated - use four-corner correction", (12, 47), (0, 180, 255)
            )
        return image

    @staticmethod
    def mini_court(image, record):
        h, w = image.shape[:2]
        scale = min(6.0, h / 36, w / 50)
        panel_w, panel_h = int(18 * scale), int(32 * scale)
        x0, y0 = w - panel_w - 8, h - panel_h - 8
        if x0 < 0 or y0 < 0:
            return
        panel = image[y0 : y0 + panel_h, x0 : x0 + panel_w]
        panel[:] = (panel.astype(float) * 0.2 + np.array([35, 70, 35]) * 0.8).astype(np.uint8)
        offset = np.array([x0 + 3.5 * scale, y0 + 4 * scale])
        points = np.rint(COURT * scale + offset).astype(int)
        for a, b in LINES:
            cv2.line(image, tuple(points[a]), tuple(points[b]), (220, 220, 220), 1)
        net = np.rint(np.array([[0, 11.885], [10.97, 11.885]]) * scale + offset).astype(int)
        cv2.line(image, tuple(net[0]), tuple(net[1]), (160, 210, 255), 1)
        for player in record["players"]:
            xy = project([ground_point(player)], record["court"]["matrix"])[0]
            if -3 <= xy[0] <= 14 and -4 <= xy[1] <= 28:
                point = tuple(np.rint(xy * scale + offset).astype(int))
                cv2.circle(image, point, 4, COLORS[player["id"] % 4], -1)
                text(image, player.get("label", f"P{player['id']}"), point)
