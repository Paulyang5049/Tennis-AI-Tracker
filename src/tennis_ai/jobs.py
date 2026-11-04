"""JSON checkpoints committed with predictions; no executable checkpoint objects."""

import fcntl
import json
from contextlib import contextmanager
from pathlib import Path

import numpy as np


@contextmanager
def run_lock(folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / ".analysis.lock").open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("This analysis is already being modified by another worker") from error
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def initialize(connection):
    connection.execute("CREATE TABLE IF NOT EXISTS job (key TEXT PRIMARY KEY, data TEXT NOT NULL)")


def save(connection, key, value):
    connection.execute(
        "INSERT OR REPLACE INTO job VALUES (?, ?)", (key, json.dumps(value, allow_nan=False))
    )


def read(connection, key):
    initialize(connection)
    result = connection.execute("SELECT data FROM job WHERE key=?", (key,)).fetchone()
    return json.loads(result[0]) if result else None


TRACK_FIELDS = (
    "track_id",
    "is_activated",
    "state",
    "score",
    "start_frame",
    "frame_id",
    "tracklet_len",
    "cls",
    "idx",
    "angle",
    "_tlwh",
    "mean",
    "covariance",
)
ARRAY_FIELDS = {"_tlwh", "mean", "covariance"}


def snapshot_tracker(tracker):
    from ultralytics.trackers.basetrack import BaseTrack

    def encode(track):
        result = {}
        for name in TRACK_FIELDS:
            value = getattr(track, name)
            result[name] = value.tolist() if isinstance(value, (np.ndarray, np.generic)) else value
        return result

    return {
        "version": 1,
        "frame_id": tracker.frame_id,
        "next_id": BaseTrack._count,
        **{
            name: [encode(t) for t in getattr(tracker, name)]
            for name in ("tracked_stracks", "lost_stracks", "removed_stracks")
        },
    }


def restore_tracker(tracker, snapshot):
    from ultralytics.trackers.basetrack import BaseTrack
    from ultralytics.trackers.byte_tracker import STrack

    if snapshot.get("version") != 1:
        raise ValueError("Unsupported tracker checkpoint version")
    tracker.reset()
    tracker.frame_id = snapshot["frame_id"]
    BaseTrack._count = snapshot["next_id"]
    for name in ("tracked_stracks", "lost_stracks", "removed_stracks"):
        tracks = []
        for data in snapshot[name]:
            track = STrack(np.array([0, 0, 1, 1, 0]), 0.0, 0)
            for field in TRACK_FIELDS:
                value = data[field]
                if field in ARRAY_FIELDS and value is not None:
                    value = np.asarray(value, dtype=np.float32 if field == "_tlwh" else np.float64)
                setattr(track, field, value)
            track.kalman_filter = tracker.kalman_filter
            tracks.append(track)
        setattr(tracker, name, tracks)
