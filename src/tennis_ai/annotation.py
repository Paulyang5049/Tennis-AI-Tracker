"""Explicit ground truth, separate from automatic predictions and review edits."""

import json
import math
import os
import tempfile
from pathlib import Path

from tennis_ai.jobs import run_lock
from tennis_ai.library import events_for
from tennis_ai.package import atomic_json
from tennis_ai.pipeline import load_summary


def annotate_ball(folder, frame, ball, distance="unspecified"):
    folder = Path(folder)
    if distance not in ("near", "far", "unspecified"):
        raise ValueError("Choose near, far or unspecified distance")
    with run_lock(folder):
        summary = load_summary(folder)
        if not isinstance(frame, int) or not 0 <= frame < summary.get("frames", 0):
            raise ValueError("Choose a frame from a completed analysis")
        if ball is not None:
            width, height = summary["video"]["width"], summary["video"]["height"]
            if (
                len(ball) != 2
                or not all(math.isfinite(x) for x in ball)
                or not 0 <= ball[0] < width
                or not 0 <= ball[1] < height
            ):
                raise ValueError("Ball point must be inside the oriented frame")
        path = folder / "annotations.jsonl"
        rows = {}
        if path.exists():
            for line in path.read_text().splitlines():
                row = json.loads(line)
                rows[row["frame"]] = row
        rows[frame] = {**rows.get(frame, {}), "frame": frame, "ball": ball, "distance": distance}
        fd, pending = tempfile.mkstemp(dir=folder, prefix=".annotations-")
        try:
            with os.fdopen(fd, "w") as stream:
                for index in sorted(rows):
                    stream.write(json.dumps(rows[index], allow_nan=False) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(pending, path)
        finally:
            Path(pending).unlink(missing_ok=True)
        return path


def export_event_annotations(folder, start, end, reviewed_interval=False):
    if not reviewed_interval:
        raise ValueError(
            "Confirm that this interval was exhaustively reviewed, including no-event times"
        )
    folder = Path(folder)
    duration = load_summary(folder)["video"]["duration"]
    if not all(math.isfinite(t) for t in (start, end)) or not 0 <= start < end <= duration:
        raise ValueError("Choose an annotation interval within the video duration")
    document = events_for(folder)
    selected = [
        event
        for event in document["events"]
        if event["reviewed"]
        and not event["excluded"]
        and start <= event["start"]
        and event["end"] <= end
    ]
    with run_lock(folder):
        path = folder / "event_annotations.json"
        atomic_json(
            path,
            {
                "schema_version": 2,
                "events": selected,
                "coverage": {kind: [[start, end]] for kind in ("hit", "bounce", "rally")},
            },
        )
        return path
