"""Exact-frame review and persisted user corrections."""

import json
import sqlite3
from pathlib import Path

import av
import cv2

from tennis_ai.geometry import calibrate
from tennis_ai.jobs import run_lock
from tennis_ai.package import atomic_json
from tennis_ai.pipeline import connect, corrected_records, load_summary, rows
from tennis_ai.render import Renderer
from tennis_ai.tracking import interpolate
from tennis_ai.video import oriented_image


def preview(folder, index, overlays=None):
    folder = Path(folder)
    summary = load_summary(folder)
    index = max(0, min(int(index), summary["frames"] - 1))
    with sqlite3.connect(folder / "review.sqlite") as conn:
        row = conn.execute("SELECT time, data FROM frames WHERE idx=?", (index,)).fetchone()
        timestamp, payload = row
        history = [
            json.loads(r[0])
            for r in conn.execute(
                "SELECT data FROM frames WHERE time>=? AND idx<=? ORDER BY idx",
                (timestamp - 1, index),
            )
        ]
    metadata = summary["video"]
    with av.open(summary["source"]) as container:
        stream = container.streams.video[0]
        container.seek(
            max(0, int((timestamp + metadata["origin"]) / float(stream.time_base))),
            stream=stream,
            backward=True,
        )
        selected = None
        for frame in container.decode(stream):
            if float(frame.pts * frame.time_base) + 1e-5 >= timestamp + metadata["origin"]:
                selected = oriented_image(frame)
                break
    if selected is None:
        raise ValueError("Cannot seek to this frame")
    renderer = Renderer(overlays)
    for record in history[:-1]:
        renderer.trail.append((record["timestamp"], record["ball"]["xy"], record["ball"]["status"]))
        renderer.scene = record["scene"]
    record = json.loads(payload)
    rendered = renderer.draw(selected, record)
    return (
        cv2.cvtColor(selected, cv2.COLOR_BGR2RGB),
        cv2.cvtColor(rendered, cv2.COLOR_BGR2RGB),
        record,
    )


def save_correction(folder, frame, corners=None, labels=None):
    with run_lock(folder):
        return _save_correction(folder, frame, corners, labels)


def _save_correction(folder, frame, corners=None, labels=None):
    folder = Path(folder)
    summary = load_summary(folder)
    metadata = summary["video"]
    path = folder / "corrections.json"
    corrections = json.loads(path.read_text()) if path.exists() else {"court": {}, "labels": {}}
    with connect(folder) as conn:
        row = conn.execute("SELECT data FROM frames WHERE idx=?", (int(frame),)).fetchone()
    if row is None:
        raise ValueError("Frame does not exist")
    record = json.loads(row[0])
    if corners is not None:
        if (
            len(corners) != 4
            or calibrate(corners, (metadata["height"], metadata["width"]), manual=True) is None
        ):
            raise ValueError("Select far-left, far-right, near-left, near-right outer corners")
        corrections.setdefault("court", {})[str(int(frame))] = corners
    if labels is not None:
        if not isinstance(labels, dict) or any(
            not str(k).isdigit() or not isinstance(v, str) or len(v) > 40 for k, v in labels.items()
        ):
            raise ValueError('Labels must be an object such as {"1": "Paul", "2": "Opponent"}')
        corrections.setdefault("labels", {})[str(record["scene"])] = labels
    atomic_json(path, corrections)
    # Update review metadata immediately without running a model or re-encoding video.
    with connect(folder) as source, sqlite3.connect(folder / "review.sqlite") as target:
        for corrected in corrected_records(
            interpolate(rows(source)),
            corrections,
            (metadata["height"], metadata["width"]),
            summary["settings"]["players"],
        ):
            target.execute(
                "UPDATE frames SET data=? WHERE idx=?", (json.dumps(corrected), corrected["frame"])
            )
