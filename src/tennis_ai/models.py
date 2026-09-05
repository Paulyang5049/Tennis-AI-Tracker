"""YOLO26 and a locally downloaded specialist court model."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import torch

from tennis_ai.artifacts import validate_bundle
from tennis_ai.geometry import calibrate, ground_point, iou, project


def choose_device(requested="auto"):
    if requested != "auto":
        if requested == "mps" and not torch.backends.mps.is_available():
            raise ValueError("Apple MPS is unavailable; select CPU")
        if requested == "cuda" and not torch.cuda.is_available():
            raise ValueError("CUDA is unavailable; select CPU")
        return requested
    return (
        "cuda"
        if torch.cuda.is_available()
        else "mps"
        if torch.backends.mps.is_available()
        else "cpu"
    )


class Models:
    def __init__(self, root, device="auto", ball_bundle=None, court_bundle=None, fps=30):
        from ultralytics import YOLO
        from ultralytics.trackers.byte_tracker import BYTETracker

        self.root = Path(root)
        self.device = choose_device(device)
        self.warnings = []
        model_dir = self.root / "models"
        for name in ["yolo26s.pt", "yolo26s-pose.pt"]:
            if not (model_dir / name).is_file():
                raise FileNotFoundError("Models are missing. Run: tennis-ai setup")
        self.detector = YOLO(str(model_dir / "yolo26s.pt"))
        self.pose = YOLO(str(model_dir / "yolo26s-pose.pt"))
        self.ball = None
        self.ball_manifest = None
        if ball_bundle:
            path, self.ball_manifest = validate_bundle(ball_bundle, "ball")
            self.ball = YOLO(str(path))
            if self.ball.names != {0: "tennis ball"}:
                raise ValueError("Actual checkpoint classes disagree with manifest")
        self.tracker = BYTETracker(
            SimpleNamespace(
                track_high_thresh=0.25,
                track_low_thresh=0.1,
                new_track_thresh=0.25,
                track_buffer=max(1, round(fps)),
                match_thresh=0.8,
                fuse_score=True,
            ),
        )
        self.court = None
        weights = model_dir / "court.pt"
        if court_bundle:
            weights, _ = validate_bundle(court_bundle, "court")
        architecture = self.root / "external" / "TennisCourtDetector" / "tracknet.py"
        if weights.exists() and architecture.exists():
            spec = importlib.util.spec_from_file_location("tennis_court_upstream", architecture)
            if spec is None or spec.loader is None:
                raise ValueError("Cannot load court architecture")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self.court = module.BallTrackerNet(out_channels=15)
            self.court.load_state_dict(torch.load(weights, map_location="cpu", weights_only=True))
            self.court.to(self.device).eval()
        else:
            self.warnings.append(
                "Court model unavailable. Use manual corner calibration or run setup again."
            )

    def reset(self):
        self.tracker.reset()

    def predict(self, model, frame, **kwargs):
        try:
            return model.predict(frame, device=self.device, verbose=False, **kwargs)[0]
        except RuntimeError as error:
            if self.device != "mps":
                raise
            self.warnings.append(f"MPS inference failed; continued on CPU: {str(error)[:160]}")
            self.device = "cpu"
            if self.court is not None:
                self.court.to("cpu")
            return model.predict(frame, device="cpu", verbose=False, **kwargs)[0]

    def infer(self, frame, court=None):
        result = self.predict(self.detector, frame, classes=[0, 32, 38], conf=0.1, imgsz=1280)
        boxes = result.boxes.cpu().numpy()
        tracks = self.tracker.update(boxes[boxes.cls == 0], frame)
        players = [
            {"id": int(row[4]), "box": row[:4].tolist(), "confidence": float(row[5])}
            for row in tracks
        ]
        rackets = [
            {"box": row[:4].tolist(), "confidence": float(row[4])}
            for row in boxes.data
            if int(row[5]) == 38 and row[4] >= 0.25
        ]
        ball_boxes = boxes.data[boxes.cls == 32]
        if self.ball:
            ball_boxes = (
                self.predict(self.ball, frame, conf=0.1, imgsz=1280).boxes.cpu().numpy().data
            )
        balls = [{"box": row[:4].tolist(), "confidence": float(row[4])} for row in ball_boxes]
        pose_result = self.predict(self.pose, frame, conf=0.25, imgsz=640)
        poses = []
        if pose_result.keypoints is not None:
            for box, keypoints in zip(
                pose_result.boxes.xyxy.cpu().tolist(), pose_result.keypoints.data.cpu().tolist()
            ):
                poses.append({"box": box, "pose": keypoints})
        # Small far-court players benefit from a second pass on a larger player crop.
        candidates = []
        for player in players:
            if court:
                x, y = project([ground_point(player)], court["matrix"])[0]
                if not (-2 <= x <= 13 and -5 <= y <= 29):
                    continue
            if player["confidence"] >= 0.5:
                candidates.append(player)
        for player in sorted(candidates, key=lambda p: p["confidence"], reverse=True)[:4]:
            x1, y1, x2, y2 = player["box"]
            height = y2 - y1
            left, top = max(0, int(x1 - height * 0.6)), max(0, int(y1 - height * 0.25))
            right, bottom = (
                min(frame.shape[1], int(x2 + height * 0.6)),
                min(frame.shape[0], int(y2 + height * 0.25)),
            )
            crop = frame[top:bottom, left:right]
            if crop.size == 0:
                continue
            if not any(iou(player["box"], pose["box"]) >= 0.3 for pose in poses):
                result = self.predict(self.pose, crop, conf=0.25, imgsz=640)
                if result.keypoints is not None:
                    for box, keypoints in zip(
                        result.boxes.xyxy.cpu().tolist(), result.keypoints.data.cpu().tolist()
                    ):
                        box = [box[0] + left, box[1] + top, box[2] + left, box[3] + top]
                        for point in keypoints:
                            point[0] += left
                            point[1] += top
                        poses.append({"box": box, "pose": keypoints})
            result = self.predict(self.detector, crop, classes=[38], conf=0.25, imgsz=640)
            for row in result.boxes.data.cpu().tolist():
                box = [row[0] + left, row[1] + top, row[2] + left, row[3] + top]
                if not any(iou(box, existing["box"]) > 0.4 for existing in rackets):
                    rackets.append({"box": box, "confidence": row[4]})
        return players, rackets, balls, poses

    def court_geometry(self, frame):
        if self.court is None:
            return None
        # Preserve upstream BGR preprocessing and 360 x 640 heatmap resolution.
        array = cv2.resize(frame, (640, 360)).astype(np.float32) / 255
        inp = torch.from_numpy(array.transpose(2, 0, 1)).unsqueeze(0)
        with torch.inference_mode():
            try:
                heatmaps = self.court(inp.to(self.device))[0].sigmoid().cpu().numpy()
            except RuntimeError:
                if self.device != "mps":
                    raise
                self.device = "cpu"
                self.court.to("cpu")
                self.warnings.append("Court MPS inference failed; continued on CPU.")
                heatmaps = self.court(inp)[0].sigmoid().numpy()
        h, w = frame.shape[:2]
        points = []
        for heatmap in heatmaps[:14]:
            centre = heatmap_centre(heatmap)
            points.append(
                [centre[0] * w / 640, centre[1] * h / 360] if centre else [np.nan, np.nan]
            )
        return calibrate(points, frame.shape)


def heatmap_centre(heatmap):
    """Use the blob centre, not argmax: upstream heatmaps have broad flat peaks."""
    mask = (heatmap > 170 / 255).astype(np.uint8)
    count, _, stats, centres = cv2.connectedComponentsWithStats(mask)
    valid = [i for i in range(1, count) if 20 <= stats[i, cv2.CC_STAT_AREA] <= 4000]
    if not valid:
        return None
    selected = max(valid, key=lambda i: stats[i, cv2.CC_STAT_AREA])
    return centres[selected].tolist()
