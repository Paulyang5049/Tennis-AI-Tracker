"""Inference-free event review and original-video clip export."""

import json
import math
import sqlite3
import subprocess
import threading
import uuid
from pathlib import Path

from tennis_ai.events import regenerate_events, summarize_events, update_event
from tennis_ai.jobs import run_lock
from tennis_ai.pipeline import load_summary
from tennis_ai.video import Cancelled


def events_for(folder):
    folder = Path(folder)
    path = folder / "events.json"
    if path.exists():
        return json.loads(path.read_text())
    if not (folder / "frames.jsonl").exists():
        return {"schema_version": 2, "events": []}
    with run_lock(folder):
        return regenerate_events(folder / "frames.jsonl", path, folder / "corrections.json")


def edit_event(folder, event_id, changes):
    folder = Path(folder)
    with run_lock(folder):
        summary = load_summary(folder)
        duration = summary["video"]["duration"]
        for field in ("start", "end"):
            if field in changes and not 0 <= changes[field] <= duration:
                raise ValueError("Event is outside the video's duration")
        if summary["status"] != "complete":
            raise ValueError("Complete the analysis before editing events")
        return update_event(folder / "events.json", folder / "corrections.json", event_id, changes)


def frame_at(folder, timestamp):
    with sqlite3.connect(Path(folder) / "review.sqlite") as connection:
        result = connection.execute(
            "SELECT idx FROM frames WHERE time<=? ORDER BY time DESC LIMIT 1", (timestamp,)
        ).fetchone()
    return result[0] if result else 0


def statistics(folder):
    return summarize_events(events_for(folder))


def export_event_clip(folder, start, end):
    """Use a two-second context window for point events; preserve explicit ranges."""
    if start == end:
        duration = load_summary(folder)["video"]["duration"]
        if not math.isfinite(start) or not 0 <= start <= duration:
            raise ValueError("Choose an event within the video duration")
        start, end = max(0, start - 2), min(duration, end + 2)
    return export_clip(folder, start, end)


def export_clip(folder, start, end, destination=None, cancel=None):
    folder = Path(folder)
    summary = load_summary(folder)
    if (
        not all(math.isfinite(t) for t in (start, end))
        or not 0 <= start < end <= summary["video"]["duration"]
    ):
        raise ValueError("Choose a nonempty clip within the video duration")
    cancel = cancel or threading.Event()
    destination = Path(destination) if destination else folder / "clips" / f"{uuid.uuid4().hex}.mp4"
    destination = destination.resolve()
    if destination == Path(summary["source"]).resolve():
        raise ValueError("A clip cannot replace its source video")
    if destination.suffix.lower() != ".mp4":
        raise ValueError("Clip destination must end in .mp4")
    destination.parent.mkdir(parents=True, exist_ok=True)
    pending = destination.with_name(f".{uuid.uuid4().hex}.pending.mp4")
    log = pending.with_suffix(".log")
    process = None
    try:
        if cancel.is_set():
            raise Cancelled("Clip export cancelled")
        with log.open("w+") as stream:
            process = subprocess.Popen(
                [
                    "ffmpeg",
                    "-y",
                    "-v",
                    "error",
                    "-i",
                    summary["source"],
                    "-ss",
                    str(start),
                    "-t",
                    str(end - start),
                    "-map",
                    "0:v:0",
                    "-map",
                    "0:a:0?",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    "-crf",
                    "21",
                    "-preset",
                    "veryfast",
                    "-c:a",
                    "aac",
                    "-movflags",
                    "+faststart",
                    str(pending),
                ],
                stderr=stream,
                stdout=subprocess.DEVNULL,
            )
            while process.poll() is None:
                if cancel.wait(0.1):
                    raise Cancelled("Clip export cancelled")
            if process.returncode:
                stream.seek(0)
                raise RuntimeError(f"Clip export failed: {stream.read()[-2000:]}")
        if cancel.is_set():
            raise Cancelled("Clip export cancelled")
        pending.replace(destination)
        return destination
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        pending.unlink(missing_ok=True)
        log.unlink(missing_ok=True)
