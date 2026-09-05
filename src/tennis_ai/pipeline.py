"""Analysis and re-rendering share disk-backed records and bounded video buffers."""

import importlib.metadata
import json
import sqlite3
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from tennis_ai.artifacts import sha256
from tennis_ai.geometry import associate_rackets, attach_poses, calibrate, ground_point, project
from tennis_ai.models import Models
from tennis_ai.render import Renderer
from tennis_ai.tracking import BallTracker, SceneMonitor, interpolate
from tennis_ai.video import Cancelled, VideoWriter, decode, mux_audio, probe


@dataclass
class Settings:
    players: int = 2
    device: str = "auto"
    ball_bundle: str | None = None
    court_bundle: str | None = None

    def __post_init__(self):
        if self.players not in (2, 4):
            raise ValueError("Choose singles (2) or doubles (4)")
        if self.device not in ("auto", "cpu", "mps", "cuda"):
            raise ValueError("Unknown inference device")


def connect(folder):
    connection = sqlite3.connect(Path(folder) / "cache.sqlite")
    connection.execute(
        "CREATE TABLE IF NOT EXISTS frames (idx INTEGER PRIMARY KEY, time REAL, data TEXT)"
    )
    return connection


def rows(connection):
    for (data,) in connection.execute("SELECT data FROM frames ORDER BY idx"):
        yield json.loads(data)


def select_players(players, court, limit, previous=None):
    candidates = []
    previous = previous or set()
    for player in players:
        if court:
            x, y = project([ground_point(player)], court["matrix"])[0]
            if not (-3.5 <= x <= 14.5 and -6 <= y <= 30):
                continue
        priority = player["confidence"] + (0.3 if player["id"] in previous else 0)
        candidates.append((priority, player))
    return [player for _, player in sorted(candidates, key=lambda x: x[0], reverse=True)[:limit]]


def analyze(source, output, root, settings=None, cancel=None, progress=None, model_factory=Models):
    settings = settings or Settings()
    cancel = cancel or threading.Event()
    progress = progress or (lambda fraction, message: None)
    source, output = Path(source).resolve(), Path(output).resolve()
    metadata = probe(source)
    if cancel.is_set():
        raise Cancelled("Cancelled before model loading")
    output.mkdir(parents=True, exist_ok=True)
    if (output / "cache.sqlite").exists():
        raise ValueError(
            "Output already contains an analysis; use a new folder or the re-render command"
        )
    summary = {
        "schema_version": 1,
        "status": "running",
        "source": str(source),
        "source_sha256": sha256(source),
        "video": metadata,
        "settings": asdict(settings),
        "versions": {n: importlib.metadata.version(n) for n in ["ultralytics", "torch", "av"]},
    }
    summary_path = output / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2))
    started = time.monotonic()
    connection = connect(output)
    try:
        progress(0, "Loading models")
        models = model_factory(
            root, settings.device, settings.ball_bundle, settings.court_bundle, metadata["fps"]
        )
        ball_tracker, scene_monitor = BallTracker(), SceneMonitor()
        scene, court, last_calibration = 0, None, -10.0
        for index, timestamp, frame in decode(source):
            if cancel.is_set():
                raise Cancelled("Analysis cancelled; partial cache retained")
            cut, moving = scene_monitor.update(frame)
            if cut:
                scene += 1
                models.reset()
                ball_tracker.reset()
                court = None
            if cut or moving or timestamp - last_calibration >= 1.0:
                # Invalidate stale geometry rather than carry it through a pan or failed fit.
                court = models.court_geometry(frame)
                last_calibration = timestamp
            players, rackets, balls, poses = models.infer(frame, court)
            attach_poses(players, poses)
            associate_rackets(players, rackets)
            ball = ball_tracker.update(balls, timestamp, frame.shape, court)
            record = {
                "schema_version": 1,
                "frame": index,
                "timestamp": timestamp,
                "scene": scene,
                "camera_moving": bool(moving),
                "cut": bool(cut),
                "court": court,
                "players": players,
                "rackets": rackets,
                "ball_candidates": balls,
                "ball": ball,
            }
            connection.execute(
                "INSERT INTO frames VALUES (?, ?, ?)", (index, timestamp, json.dumps(record))
            )
            if index % 30 == 0:
                connection.commit()
                progress(
                    min(0.75, 0.75 * timestamp / max(metadata["duration"], 0.01)),
                    f"Analyzed frame {index + 1} / {timestamp:.1f}s",
                )
        connection.commit()
        summary.update(
            {
                "status": "inference_complete",
                "device": models.device,
                "ball_model": "custom YOLO26s"
                if settings.ball_bundle
                else "COCO sports-ball baseline",
                "warnings": models.warnings,
                "inference_seconds": time.monotonic() - started,
            }
        )
        summary_path.write_text(json.dumps(summary, indent=2))
        del models
        render_cached(output, cancel=cancel, progress=progress, check_source=False)
    except Exception as error:
        connection.commit()
        summary["status"] = "cancelled" if isinstance(error, Cancelled) else "failed"
        summary["error"] = str(error)
        summary_path.write_text(json.dumps(summary, indent=2))
        raise
    finally:
        connection.close()
    return output


def corrected_records(records, corrections, shape, limit):
    active = None
    previous_scene = None
    selected_ids: set[int] = set()
    for record in records:
        if record["scene"] != previous_scene or record.get("camera_moving"):
            active = None
        if record["scene"] != previous_scene:
            selected_ids.clear()
        previous_scene = record["scene"]
        corners = corrections.get("court", {}).get(str(record["frame"]))
        if corners is not None:
            active = calibrate(corners, shape, manual=True)
            if active is None:
                raise ValueError(f"Invalid court corners at frame {record['frame']}")
        if active is not None:
            record["court"] = active
        record["players"] = select_players(record["players"], record["court"], limit, selected_ids)
        selected_ids = {p["id"] for p in record["players"]}
        labels = corrections.get("labels", {}).get(str(record["scene"]), {})
        for player in record["players"]:
            player["label"] = labels.get(str(player["id"]), f"P{player['id']}")
        yield record


def render_cached(output, overlays=None, cancel=None, progress=None, check_source=True):
    output = Path(output)
    cancel = cancel or threading.Event()
    progress = progress or (lambda fraction, message: None)
    summary_path = output / "summary.json"
    summary = json.loads(summary_path.read_text())
    if summary["status"] not in ("complete", "inference_complete"):
        raise ValueError("Only a completed inference cache can be rendered")
    source, metadata = summary["source"], summary["video"]
    if check_source and sha256(source) != summary["source_sha256"]:
        raise ValueError("Source video changed; cached predictions cannot be reused")
    corrections_path = output / "corrections.json"
    corrections = json.loads(corrections_path.read_text()) if corrections_path.exists() else {}
    connection = connect(output)
    records = corrected_records(
        interpolate(rows(connection)),
        corrections,
        (metadata["height"], metadata["width"]),
        summary["settings"]["players"],
    )
    renderer = Renderer(overlays)
    review_path = output / "review.pending.sqlite"
    review_path.unlink(missing_ok=True)
    review = sqlite3.connect(review_path)
    review.execute("CREATE TABLE frames (idx INTEGER PRIMARY KEY, time REAL, data TEXT)")
    silent = output / "silent.tmp.mp4"
    pending = output / "annotated.pending.mp4"
    json_path = output / "frames.pending.jsonl"
    writer = VideoWriter(silent, metadata["width"], metadata["height"], metadata["fps"])
    count, observed, inferred, court_frames = 0, 0, 0, 0
    started = time.monotonic()
    try:
        try:
            with json_path.open("w") as export:
                for index, timestamp, image in decode(source):
                    if cancel.is_set():
                        raise Cancelled("Render cancelled")
                    record = next(records, None)
                    if (
                        record is None
                        or record["frame"] != index
                        or abs(record["timestamp"] - timestamp) > 1e-5
                    ):
                        raise ValueError("Cache does not match the source video")
                    writer.write(renderer.draw(image, record), timestamp)
                    payload = json.dumps(record, allow_nan=False)
                    export.write(payload + "\n")
                    review.execute(
                        "INSERT INTO frames VALUES (?, ?, ?)", (index, timestamp, payload)
                    )
                    count += 1
                    observed += record["ball"]["status"] == "observed"
                    inferred += record["ball"]["status"] == "interpolated"
                    court_frames += record["court"] is not None
                    if index % 30 == 0:
                        progress(
                            min(0.98, 0.75 + 0.23 * timestamp / max(metadata["duration"], 0.01)),
                            f"Rendering frame {index + 1}",
                        )
        finally:
            writer.close()
        mux_audio(silent, source, pending, metadata, cancel)
        if cancel.is_set():
            raise Cancelled("Export cancelled")
        review.commit()
        review.close()
        review_path.replace(output / "review.sqlite")
        pending.replace(output / "annotated.mp4")
        json_path.replace(output / "frames.jsonl")
        summary.update(
            {
                "status": "complete",
                "frames": count,
                "ball_observed_fraction": observed / max(count, 1),
                "ball_interpolated_fraction": inferred / max(count, 1),
                "court_calibrated_fraction": court_frames / max(count, 1),
                "render_seconds": time.monotonic() - started,
                "accuracy_metrics": None,
                "metrics_note": "Coverage is not accuracy. Ground-truth annotations are required for precision/recall.",
                "overlays": sorted(renderer.overlays),
            }
        )
        summary_path.write_text(json.dumps(summary, indent=2))
        progress(1, "Complete")
    finally:
        connection.close()
        review.close()
        review_path.unlink(missing_ok=True)
        silent.unlink(missing_ok=True)
        pending.unlink(missing_ok=True)
        json_path.unlink(missing_ok=True)
    return output
