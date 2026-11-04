import json
import shutil
import sqlite3
import threading

import numpy as np
import pytest

from tennis_ai.pipeline import analyze, resume_analysis
from tennis_ai.video import Cancelled, VideoWriter


class StatefulModels:
    calls = 0

    def __init__(self, *args):
        self.device, self.warnings, self.counter = "cpu", [], 0

    def reset(self):
        self.counter = 0

    def court_geometry(self, frame):
        return None

    def snapshot(self):
        return {"counter": self.counter}

    def restore(self, state):
        self.counter = state["counter"]

    def infer(self, frame, court=None):
        type(self).calls += 1
        self.counter += 1
        return (
            [{"id": self.counter, "box": [5, 5, 10, 25], "confidence": 0.9}],
            [],
            [{"box": [15, 15, 17, 17], "confidence": 0.9}],
            [],
        )


def make_video(path):
    writer = VideoWriter(path, 64, 48, 30)
    for frame in range(35):
        writer.write(np.zeros((48, 64, 3), np.uint8), frame / 30)
    writer.close()


def test_resume_after_cancel_matches_uninterrupted_and_relocation(tmp_path):
    video = tmp_path / "original.mp4"
    make_video(video)
    full, partial = tmp_path / "full", tmp_path / "partial"
    analyze(video, full, tmp_path, model_factory=StatefulModels)
    cancel = threading.Event()

    def stop(fraction, message):
        if message.startswith("Analyzed frame"):
            cancel.set()

    with pytest.raises(Cancelled):
        analyze(
            video, partial, tmp_path, cancel=cancel, progress=stop, model_factory=StatefulModels
        )
    with sqlite3.connect(partial / "cache.sqlite") as db:
        committed = db.execute("SELECT count(*) FROM frames").fetchone()[0]
    assert 0 < committed < 35
    moved = tmp_path / "moved"
    shutil.move(partial, moved)
    video.unlink()
    StatefulModels.calls = 0
    resume_analysis(moved, tmp_path, model_factory=StatefulModels)
    assert StatefulModels.calls == 35 - committed
    assert (moved / "frames.jsonl").read_text() == (full / "frames.jsonl").read_text()
    assert json.loads((moved / "manifest.json").read_text())["status"] == "complete"


def test_resume_rejects_changed_settings_and_media(tmp_path):
    video = tmp_path / "original.mp4"
    make_video(video)
    folder = tmp_path / "run"
    analyze(video, folder, tmp_path, model_factory=StatefulModels)
    summary = json.loads((folder / "summary.json").read_text())
    summary["settings"]["players"] = 4
    (folder / "summary.json").write_text(json.dumps(summary))
    with pytest.raises(ValueError, match="changed|mismatch"):
        resume_analysis(folder, tmp_path, model_factory=StatefulModels)


def test_model_tracker_json_roundtrip():
    from types import SimpleNamespace

    from ultralytics.engine.results import Boxes
    from ultralytics.trackers.byte_tracker import BYTETracker

    from tennis_ai.jobs import restore_tracker, snapshot_tracker

    args = SimpleNamespace(
        track_high_thresh=0.25,
        track_low_thresh=0.1,
        new_track_thresh=0.25,
        track_buffer=30,
        match_thresh=0.8,
        fuse_score=True,
    )
    tracker = BYTETracker(args)
    detections = Boxes(np.array([[10, 10, 30, 50, 0.9, 0]], dtype=np.float32), (100, 100))
    tracker.update(detections)
    state = json.loads(json.dumps(snapshot_tracker(tracker)))
    expected = tracker.update(detections)
    replacement = BYTETracker(args)
    restore_tracker(replacement, state)
    np.testing.assert_allclose(replacement.update(detections), expected)


def test_seek_decoder_preserves_absolute_frame_identity_and_variable_pts(tmp_path):
    from tennis_ai.video import decode

    source = tmp_path / "variable.mp4"
    writer = VideoWriter(source, 64, 48, 30)
    for timestamp in (0, 0.03, 0.09, 0.13, 0.24):
        writer.write(np.zeros((48, 64, 3), np.uint8), timestamp)
    writer.close()
    expected = list(decode(source))
    resumed = list(decode(source, after=(2, expected[2][1])))
    assert [(i, t) for i, t, _ in resumed] == [(i, t) for i, t, _ in expected[3:]]
