import json
import sqlite3
import subprocess

import pytest
from test_pipeline import FakeModels

from tennis_ai.library import (
    edit_event,
    events_for,
    export_clip,
    export_event_clip,
    frame_at,
    statistics,
)
from tennis_ai.pipeline import analyze, render_cached
from tennis_ai.video import probe


def test_exact_match_deletion_and_permissions(tmp_path):
    from tennis_ai.library import delete_match, protect_match

    root = tmp_path / "outputs"
    match = root / "match-a"
    match.mkdir(parents=True)
    (match / "summary.json").write_text("{}")
    (match / "clips").mkdir()
    (match / "clips" / "one.mp4").write_bytes(b"clip")
    other = root / "match-b"
    other.mkdir()
    protect_match(match)
    assert match.stat().st_mode & 0o777 == 0o700
    assert (match / "clips" / "one.mp4").stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError, match="confirmation"):
        delete_match(root, "match-a", "wrong")
    assert match.exists()
    delete_match(root, "match-a", "match-a")
    assert not match.exists() and other.exists()
    with pytest.raises(ValueError):
        delete_match(root, "../outputs", "../outputs")
    external = tmp_path / "external"
    external.mkdir()
    (root / "link").symlink_to(external, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        delete_match(root, "link", "link")
    assert external.exists()


def test_edit_rerender_and_clip_do_not_run_inference(tmp_path):
    source = tmp_path / "source.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=black:s=320x180:r=30:d=1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-shortest",
            str(source),
        ],
        check=True,
    )
    output = tmp_path / "run"
    analyze(source, output, tmp_path, model_factory=FakeModels)
    with sqlite3.connect(output / "cache.sqlite") as db:
        before = db.execute("SELECT idx, time, data FROM frames ORDER BY idx").fetchall()
    event = {"kind": "rally", "start": 0.1, "end": 0.8, "reviewed": True, "favorite": True}
    document = edit_event(output, None, event)
    event_id = next(e["id"] for e in document["events"] if e["provenance"] == "manual")
    edit_event(output, None, {"kind": "bounce", "start": 0.5, "reviewed": True, "position": [2, 8]})
    assert statistics(output)["verified"]["rally"] == 1
    assert statistics(output)["verified"]["landings"][0]["position"] == [2, 8]
    assert frame_at(output, 0.5) == 15
    render_cached(output)
    assert next(e for e in events_for(output)["events"] if e["id"] == event_id)["favorite"]
    # Runtime job phase may be updated, but cached predictions remain identical.
    with sqlite3.connect(output / "cache.sqlite") as db:
        assert db.execute("SELECT idx, time, data FROM frames ORDER BY idx").fetchall() == before
    clip = export_clip(output, 0.2, 0.8)
    metadata = probe(clip)
    assert metadata["has_audio"]
    assert metadata["duration"] == pytest.approx(0.6, abs=0.05)
    # Hit/bounce events have equal start/end; export still yields playable audio/video.
    point_clip = export_event_clip(output, 0.5, 0.5)
    point_metadata = probe(point_clip)
    assert point_metadata["has_audio"]
    assert point_metadata["duration"] == pytest.approx(1, abs=0.05)
    with pytest.raises(ValueError, match="duration"):
        export_event_clip(output, 5, 5)
    with pytest.raises(ValueError, match="nonempty"):
        export_clip(output, 0.8, 0.2)
    with pytest.raises(ValueError, match="duration"):
        edit_event(output, event_id, {"end": 5})
    edit_event(output, event_id, {"excluded": True})
    assert statistics(output)["verified"]["rally"] == 0
    assert json.loads((output / "corrections.json").read_text())["events"][event_id]["excluded"]

    from tennis_ai.evidence import load_evidence
    from tennis_ai.package import export_package

    migrated = export_package(output, tmp_path / "v3", version=3)
    graph_before = load_evidence(migrated)
    render_cached(migrated)
    assert load_evidence(migrated) == graph_before
