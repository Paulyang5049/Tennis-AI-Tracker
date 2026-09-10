"""Analysis and re-rendering share disk-backed records and bounded video buffers."""

import importlib.metadata
import json
import sqlite3
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from tennis_ai import jobs
from tennis_ai.artifacts import sha256
from tennis_ai.geometry import associate_rackets, attach_poses, calibrate, ground_point, project
from tennis_ai.models import Models
from tennis_ai.package import (
    atomic_json,
    load_manifest,
    relative_asset,
    update_status,
    write_manifest,
)
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
    connection.execute("CREATE INDEX IF NOT EXISTS frame_time ON frames(time)")
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


def fingerprints(root, settings, model_factory):
    result = {"adapter": f"{model_factory.__module__}.{model_factory.__qualname__}"}
    for module in ("pipeline.py", "tracking.py", "models.py", "jobs.py", "geometry.py", "video.py"):
        result[module] = sha256(Path(__file__).parent / module)
    if model_factory is Models:
        root = Path(root)
        files = {
            "detector": root / "models/yolo26s.pt",
            "pose": root / "models/yolo26s-pose.pt",
            "court": root / "models/court.pt",
            "court_architecture": root / "external/TennisCourtDetector/tracknet.py",
        }
        for kind in ("ball", "court"):
            bundle = getattr(settings, f"{kind}_bundle")
            if bundle:
                from tennis_ai.artifacts import validate_bundle

                files[kind], _ = validate_bundle(bundle, kind)
        result.update(
            {
                name: sha256(path) if path.is_file() else "unavailable"
                for name, path in files.items()
            }
        )
    return result


def load_summary(folder):
    folder = Path(folder)
    summary = json.loads((folder / "summary.json").read_text())
    if (folder / "manifest.json").exists():
        summary["source"] = str(relative_asset(folder, load_manifest(folder)["media"]["path"]))
    return summary


def analyze(source, output, root, settings=None, cancel=None, progress=None, model_factory=Models):
    with jobs.run_lock(output):
        return _analyze(source, output, root, settings, cancel, progress, model_factory)


def resume_analysis(output, root, cancel=None, progress=None, model_factory=Models):
    with jobs.run_lock(output):
        summary = load_summary(output)
        return _analyze(
            summary["source"],
            output,
            root,
            Settings(**summary["settings"]),
            cancel,
            progress,
            model_factory,
            resume=True,
        )


def _analyze(
    source,
    output,
    root,
    settings=None,
    cancel=None,
    progress=None,
    model_factory=Models,
    resume=False,
):
    settings = settings or Settings()
    cancel = cancel or threading.Event()
    progress = progress or (lambda fraction, message: None)
    source, output = Path(source).resolve(), Path(output).resolve()
    if cancel.is_set():
        raise Cancelled("Cancelled before model loading")
    if not resume and (output / "cache.sqlite").exists():
        raise ValueError("Output already contains an analysis; use resume or a new folder")
    metadata = probe(source)
    versions = {n: importlib.metadata.version(n) for n in ["ultralytics", "torch", "av", "numpy"]}
    provenance = fingerprints(root, settings, model_factory)
    identity = {
        "source_sha256": sha256(source),
        "settings": asdict(settings),
        "versions": versions,
        "models": provenance,
    }
    connection = connect(output)
    jobs.initialize(connection)
    checkpoint = None
    if resume:
        if jobs.read(connection, "identity") != identity:
            connection.close()
            raise ValueError("Resume mismatch: source, settings, models or runtime changed")
        summary = load_summary(output)
        phase = jobs.read(connection, "phase")
        if phase in ("inference_complete", "complete"):
            connection.close()
            summary["status"] = "inference_complete"
            atomic_json(output / "summary.json", summary)
            return _render_cached(output, cancel=cancel, progress=progress)
        checkpoint = jobs.read(connection, "checkpoint")
        if checkpoint and checkpoint["model"] is None:
            connection.close()
            raise ValueError("This model adapter does not support checkpoint restoration")
    else:
        try:
            manifest = write_manifest(output, source, metadata, asdict(settings), provenance)
            if manifest["media"]["sha256"] != identity["source_sha256"]:
                raise ValueError("Source changed during import")
            source = relative_asset(output, manifest["media"]["path"])
            summary = {
                "schema_version": 1,
                "status": "running",
                "source": str(source),
                "source_sha256": identity["source_sha256"],
                "video": metadata,
                "settings": asdict(settings),
                "versions": versions,
            }
            jobs.save(connection, "identity", identity)
            jobs.save(connection, "phase", "running")
            connection.commit()
        except Exception:
            connection.close()
            raise
    summary_path = output / "summary.json"
    summary["status"] = "running"
    summary.pop("error", None)
    atomic_json(summary_path, summary)
    update_status(output, "running")
    started = time.monotonic()
    inference_finished = False
    try:
        progress(0, "Loading models")
        models = model_factory(
            root, settings.device, settings.ball_bundle, settings.court_bundle, metadata["fps"]
        )
        ball_tracker, scene_monitor = BallTracker(), SceneMonitor()
        scene, court, last_calibration, last_frame = 0, None, -10.0, -1
        if checkpoint:
            import numpy as np

            models.restore(checkpoint["model"])
            ball_tracker.history.extend((t, xy) for t, xy in checkpoint["ball_history"])
            previous = checkpoint["previous_image"]
            scene_monitor.previous = np.asarray(previous, dtype=np.uint8) if previous else None
            scene, court = checkpoint["scene"], checkpoint["court"]
            last_calibration, last_frame = checkpoint["last_calibration"], checkpoint["frame"]

        def capture(index, timestamp, model):
            return {
                "frame": index,
                "timestamp": timestamp,
                "scene": scene,
                "court": court,
                "last_calibration": last_calibration,
                "ball_history": list(ball_tracker.history),
                "previous_image": scene_monitor.previous.tolist()
                if scene_monitor.previous is not None
                else None,
                "model": model.snapshot() if hasattr(model, "snapshot") else None,
            }

        index = -1
        after = (checkpoint["frame"], checkpoint["timestamp"]) if checkpoint else None
        for index, timestamp, frame in decode(source, after=after):
            if cancel.is_set():
                raise Cancelled("Analysis paused; use Resume to continue")
            if index <= last_frame:
                continue
            cut, moving = scene_monitor.update(frame)
            if cut:
                scene += 1
                models.reset()
                ball_tracker.reset()
                court = None
            if cut or moving or timestamp - last_calibration >= 1.0:
                court = models.court_geometry(frame)
                last_calibration = timestamp
            players, rackets, balls, poses = models.infer(frame, court)
            attach_poses(players, poses)
            associate_rackets(players, rackets)
            ball = ball_tracker.update(balls, timestamp, frame.shape, court)
            record = {
                "schema_version": 2,
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
                "INSERT INTO frames VALUES (?, ?, ?)",
                (index, timestamp, json.dumps(record, allow_nan=False)),
            )
            # Every checkpoint and its corresponding predictions commit atomically.
            if index % 30 == 0 or cancel.is_set():
                checkpoint = capture(index, timestamp, models)
                jobs.save(connection, "checkpoint", checkpoint)
                connection.commit()
                progress(
                    min(0.75, 0.75 * timestamp / max(metadata["duration"], 0.01)),
                    f"Analyzed frame {index + 1} / {timestamp:.1f}s",
                )
        if index >= 0:
            jobs.save(connection, "checkpoint", capture(index, timestamp, models))
        jobs.save(connection, "phase", "inference_complete")
        connection.commit()
        inference_finished = True
        summary.update(
            {
                "status": "inference_complete",
                "device": models.device,
                "ball_model": "custom YOLO26s"
                if settings.ball_bundle
                else "COCO sports-ball baseline",
                "warnings": models.warnings,
                "inference_seconds": summary.get("inference_seconds", 0)
                + time.monotonic()
                - started,
            }
        )
        atomic_json(summary_path, summary)
        del models
        _render_cached(output, cancel=cancel, progress=progress, check_source=False)
    except Exception as error:
        connection.rollback()
        status = "paused" if isinstance(error, Cancelled) else "failed"
        summary["status"], summary["error"] = status, str(error)
        if not inference_finished:
            summary["inference_seconds"] = (
                summary.get("inference_seconds", 0) + time.monotonic() - started
            )
        atomic_json(summary_path, summary)
        update_status(output, status)
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
    with jobs.run_lock(output):
        return _render_cached(output, overlays, cancel, progress, check_source)


def _render_cached(output, overlays=None, cancel=None, progress=None, check_source=True):
    output = Path(output)
    cancel = cancel or threading.Event()
    progress = progress or (lambda fraction, message: None)
    summary_path = output / "summary.json"
    summary = load_summary(output)
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
    review.execute("CREATE INDEX frame_time ON frames(time)")
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
        from tennis_ai.events import regenerate_events

        regenerate_events(
            output / "frames.jsonl", output / "events.json", output / "corrections.json"
        )
        atomic_json(summary_path, summary)
        update_status(output, "complete")
        jobs.initialize(connection)
        jobs.save(connection, "phase", "complete")
        connection.commit()
        progress(1, "Complete")
    finally:
        connection.close()
        review.close()
        review_path.unlink(missing_ok=True)
        silent.unlink(missing_ok=True)
        pending.unlink(missing_ok=True)
        json_path.unlink(missing_ok=True)
    return output
