import json
import sqlite3
import subprocess
import threading
from pathlib import Path

import numpy as np
import pytest

from tennis_ai.app import preserve_upload
from tennis_ai.geometry import calibrate
from tennis_ai.pipeline import Settings, analyze, render_cached
from tennis_ai.review import preview, save_correction
from tennis_ai.video import Cancelled, VideoWriter, decode, probe


class FakeModels:
    def __init__(self, *args):
        self.device = "cpu"
        self.warnings = []

    def reset(self):
        pass

    def court_geometry(self, frame):
        return calibrate([[80, 25], [240, 25], [40, 160], [280, 160]], frame.shape, manual=True)

    def infer(self, frame, court=None):
        return (
            [{"id": 1, "box": [100, 50, 130, 120], "confidence": 0.9}],
            [],
            [{"box": [170, 80, 176, 86], "confidence": 0.9}],
            [],
        )


@pytest.fixture
def video(tmp_path):
    path = tmp_path / "video.mp4"
    writer = VideoWriter(path, 320, 180, 30)
    for t in [0, 0.03333, 0.10, 0.13333]:
        writer.write(np.zeros((180, 320, 3), np.uint8), t)
    writer.close()
    return path


def test_variable_timestamps_export_and_cached_render(tmp_path, video):
    output = tmp_path / "run"
    analyze(video, output, tmp_path, Settings(players=4), model_factory=FakeModels)
    summary = json.loads((output / "summary.json").read_text())
    assert summary["frames"] == 4 and summary["status"] == "complete"
    before = [t for _, t, _ in decode(video)]
    after = [t for _, t, _ in decode(output / "annotated.mp4")]
    assert after == pytest.approx(before, abs=1 / 90000)
    assert summary["ball_observed_fraction"] == 1
    save_correction(output, 0, labels={"1": "Paul"})
    raw, rendered, record = preview(output, 2)
    assert record["players"][0]["label"] == "Paul"
    assert raw.shape == rendered.shape == (180, 320, 3)
    render_cached(output, overlays=["Players"])
    assert (
        json.loads((output / "frames.jsonl").read_text().splitlines()[0])["players"][0]["label"]
        == "Paul"
    )
    assert json.loads((output / "summary.json").read_text())["overlays"] == ["Players"]


def test_audio_survives(tmp_path, video):
    audio_video = tmp_path / "with-audio.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-i",
            str(video),
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=1000:duration=0.18",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            str(audio_video),
        ],
        check=True,
    )
    analyze(audio_video, tmp_path / "audio-run", tmp_path, model_factory=FakeModels)
    assert probe(tmp_path / "audio-run" / "annotated.mp4")["has_audio"]
    import av

    def audio_times(path):
        with av.open(str(path)) as container:
            frames = list(container.decode(audio=0))
            return float(frames[0].time), float(frames[-1].time)

    assert audio_times(audio_video) == pytest.approx(
        audio_times(tmp_path / "audio-run" / "annotated.mp4"), abs=0.025
    )


def test_invalid_input_and_existing_output(tmp_path, video):
    bad = tmp_path / "bad.mp4"
    bad.write_text("not a video")
    with pytest.raises(ValueError):
        probe(bad)
    with pytest.raises(ValueError):
        Settings(players=3)
    output = tmp_path / "run"
    analyze(video, output, tmp_path, model_factory=FakeModels)
    with pytest.raises(ValueError, match="already contains"):
        analyze(video, output, tmp_path, model_factory=FakeModels)
    Path(json.loads((output / "summary.json").read_text())["source"]).write_bytes(b"changed")
    with pytest.raises(ValueError, match="changed"):
        render_cached(output)


def test_cancellation_before_loading(tmp_path, video):
    event = threading.Event()
    event.set()
    with pytest.raises(Cancelled):
        analyze(video, tmp_path / "run", tmp_path, cancel=event, model_factory=FakeModels)
    assert not (tmp_path / "run" / "cache.sqlite").exists()


def test_cancellation_during_render_preserves_previous_export(tmp_path, video):
    output = tmp_path / "run"
    analyze(video, output, tmp_path, model_factory=FakeModels)
    previous = (output / "annotated.mp4").read_bytes()
    event = threading.Event()
    event.set()
    with pytest.raises(Cancelled):
        render_cached(output, cancel=event)
    assert (output / "annotated.mp4").read_bytes() == previous
    assert not (output / "annotated.pending.mp4").exists()


def test_bounded_records_on_disk(tmp_path, video):
    analyze(video, tmp_path / "run", tmp_path, model_factory=FakeModels)
    with sqlite3.connect(tmp_path / "run" / "cache.sqlite") as db:
        assert db.execute("SELECT count(*) FROM frames").fetchone()[0] == 4


def test_uploaded_source_is_preserved(tmp_path, video):
    preserved = preserve_upload(video, tmp_path / "run")
    assert preserved.name == "source.mp4"
    assert preserved.read_bytes() == video.read_bytes()
    assert preserve_upload(video, tmp_path / "run") == preserved


def test_phone_rotation_matches_ffmpeg_display(tmp_path, video):
    rotated = tmp_path / "rotated.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-display_rotation",
            "90",
            "-i",
            str(video),
            "-c",
            "copy",
            str(rotated),
        ],
        check=True,
    )
    info = probe(rotated)
    assert (info["width"], info["height"]) == (180, 320)
    frame = next(decode(rotated))[2]
    assert frame.shape[:2] == (320, 180)
    import av

    from tennis_ai.video import oriented_image

    # Non-symmetric content checks the rotation direction against FFmpeg's autorotation.
    source = tmp_path / "pattern.mp4"
    writer = VideoWriter(source, 320, 180, 30)
    pixels = np.zeros((180, 320, 3), np.uint8)
    pixels[:90, :160] = [0, 0, 255]
    writer.write(pixels, 0)
    writer.close()
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-display_rotation",
            "90",
            "-i",
            str(source),
            "-c",
            "copy",
            str(rotated),
        ],
        check=True,
    )
    raw = subprocess.check_output(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(rotated),
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "bgr24",
            "pipe:1",
        ]
    )
    expected = np.frombuffer(raw, np.uint8).reshape(320, 180, 3)
    with av.open(str(rotated)) as container:
        actual = oriented_image(next(container.decode(video=0)))
    assert np.mean(np.abs(expected.astype(float) - actual)) < 1


def test_cut_resets_model_ids(tmp_path):
    source = tmp_path / "cut.mp4"
    writer = VideoWriter(source, 320, 180, 30)
    writer.write(np.zeros((180, 320, 3), np.uint8), 0)
    writer.write(np.full((180, 320, 3), 255, np.uint8), 0.03333)
    writer.close()
    calls = []

    class ResetModels(FakeModels):
        def reset(self):
            calls.append("reset")

    analyze(source, tmp_path / "run", tmp_path, model_factory=ResetModels)
    lines = [
        json.loads(line) for line in (tmp_path / "run" / "frames.jsonl").read_text().splitlines()
    ]
    assert calls == ["reset"]
    assert lines[0]["scene"] == 0 and lines[1]["scene"] == 1
