"""Inference-free event review and original-video clip export."""

import json
import math
import os
import shutil
import sqlite3
import subprocess
import threading
import uuid
from pathlib import Path

from tennis_ai.events import regenerate_events, summarize_events, update_event
from tennis_ai.jobs import run_lock
from tennis_ai.pipeline import load_summary
from tennis_ai.video import Cancelled


def protect_match(folder):
    """Owner-only local analysis storage; never chmod symlink targets."""
    folder = Path(folder)
    if folder.is_symlink() or not folder.is_dir():
        raise ValueError("Match storage must be a real directory")
    if os.name == "posix":
        folder.chmod(0o700)
        for current, directories, files in os.walk(folder, followlinks=False):
            for name in directories + files:
                path = Path(current) / name
                if not path.is_symlink():
                    path.chmod(0o700 if path.is_dir() else 0o600)


def delete_match(library_root, match_name, confirmation):
    """Delete only an explicitly named direct child, including its derived clips."""
    root = Path(library_root).resolve()
    if not match_name or Path(match_name).name != match_name or match_name in (".", ".."):
        raise ValueError("Choose an exact library match name")
    if confirmation != match_name:
        raise ValueError("Match-name confirmation does not match")
    target = root / match_name
    if target.is_symlink():
        raise ValueError("Cannot delete a symlink as a match")
    if target.resolve().parent != root or not target.is_dir():
        raise ValueError("Match is outside the configured library or missing")
    if not (target / "summary.json").is_file() and not (target / "manifest.json").is_file():
        raise ValueError("Selected directory is not an analysis package")
    with run_lock(target):
        # shutil.rmtree does not follow child symlinks. Re-check exact root after locking.
        if target.is_symlink() or target.resolve().parent != root:
            raise ValueError("Match root changed during deletion")
        shutil.rmtree(target)


def events_for(folder):
    folder = Path(folder)
    if (folder / "manifest.json").exists():
        from tennis_ai.package import load_manifest

        if load_manifest(folder)["schema_version"] == 3:
            from tennis_ai.evidence import load_evidence

            return load_evidence(folder)["events"]
    path = folder / "events.json"
    if path.exists():
        return json.loads(path.read_text())
    if not (folder / "frames.jsonl").exists():
        return {"schema_version": 2, "events": []}
    with run_lock(folder):
        return regenerate_events(folder / "frames.jsonl", path, folder / "corrections.json")


def edit_event(folder, event_id, changes):
    folder = Path(folder)
    if (folder / "manifest.json").exists():
        from tennis_ai.package import load_manifest

        if load_manifest(folder)["schema_version"] == 3:
            from tennis_ai.evidence import edit_evidence_event

            return edit_evidence_event(folder, event_id, changes)
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
