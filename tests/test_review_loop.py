import json
import shutil
from pathlib import Path

import pytest

from tennis_ai.evidence import load_evidence, review_entity

FIXTURES = Path(__file__).resolve().parents[1] / "contracts/fixtures/v3"


def test_link_review_replay_is_idempotent_and_invalidates(tmp_path):
    shutil.copytree(FIXTURES / "full", tmp_path, dirs_exist_ok=True)
    original = (tmp_path / "events.json").read_bytes()
    link = json.loads((FIXTURES / "link-audit.jsonl").read_text())["after"]
    link["confidence"] = 0.8
    reviewed = review_entity(tmp_path, "link", link)
    assert reviewed["metrics"]["metrics"] == []
    assert reviewed["insights"]["insights"] == []
    review_entity(tmp_path, "link", link)
    assert len(load_evidence(tmp_path)["audit"]) == 1
    (tmp_path / "events.json").write_bytes(original)
    assert load_evidence(tmp_path) == reviewed
    assert load_evidence(tmp_path) == reviewed


@pytest.mark.parametrize("field,value", [("bounce_id", "missing"), ("shot_id", "bounce-1")])
def test_invalid_link_does_not_append(tmp_path, field, value):
    shutil.copytree(FIXTURES / "full", tmp_path, dirs_exist_ok=True)
    link = dict(load_evidence(tmp_path)["events"]["links"][0])
    link[field] = value
    before = (tmp_path / "corrections.jsonl").read_bytes()
    with pytest.raises(ValueError):
        review_entity(tmp_path, "link", link)
    assert (tmp_path / "corrections.jsonl").read_bytes() == before


def test_v3_writer_and_track_persistence_preserve_review(tmp_path):
    from tennis_ai.evidence import persist_frame_tracks
    from tennis_ai.package import write_manifest

    source = tmp_path / "source.mp4"
    source.write_bytes(b"generated-test")
    manifest = write_manifest(
        tmp_path,
        source,
        {"width": 320, "height": 180, "duration": 5, "origin": 0},
        {"players": 2},
        {},
        "complete",
        version=3,
    )
    sample = {
        "schema_version": 1,
        "timestamp": 1,
        "scene": 0,
        "track_id": 1,
        "side": "unknown",
        "position_court_m": [4, 5],
        "method": "ankles_homography",
        "reviewed": False,
        "calibration_id": "cal-1",
    }
    frames = [{"players": [{"court_position": sample}]}]
    persist_frame_tracks(tmp_path, manifest, frames)
    assert load_evidence(tmp_path)["tracks"] == [sample]
    sample["reviewed"] = True
    (tmp_path / "tracks.jsonl").write_text(json.dumps(sample) + "\n")
    automatic = {**sample, "reviewed": False, "position_court_m": [8, 9]}
    persist_frame_tracks(tmp_path, manifest, [{"players": [{"court_position": automatic}]}])
    assert load_evidence(tmp_path)["tracks"] == [sample]


def test_analysis_export_and_rerender_preserve_review(tmp_path, monkeypatch):
    import numpy as np

    from tennis_ai.events import new_event
    from tennis_ai.evidence import edit_evidence_event
    from tennis_ai.package import export_package, load_manifest
    from tennis_ai.pipeline import analyze, render_cached
    from tennis_ai.video import VideoWriter

    class Models:
        device = "cpu"
        warnings = []

        def __init__(self, *args):
            pass

        def reset(self):
            pass

        def court_geometry(self, frame):
            return None

        def infer(self, frame, court=None):
            return [{"id": 1, "box": [10, 10, 20, 30], "confidence": 0.9}], [], [], []

    source = tmp_path / "generated.mp4"
    writer = VideoWriter(source, 64, 64, 30)
    for timestamp in (0, 1 / 30, 2 / 30):
        writer.write(np.zeros((64, 64, 3), dtype=np.uint8), timestamp)
    writer.close()
    monkeypatch.setattr(
        "tennis_ai.events.generate_candidates",
        lambda frames: iter([new_event("hit", 0, id="candidate")]),
    )
    folder = tmp_path / "run"
    analyze(source, folder, tmp_path, model_factory=Models)
    assert load_manifest(folder)["schema_version"] == 3
    assert len(load_evidence(folder)["tracks"]) == 3
    assert all(t["position_court_m"] is None for t in load_evidence(folder)["tracks"])
    edit_evidence_event(folder, "candidate", {"reviewed": True})
    before = load_evidence(folder)
    monkeypatch.setattr(
        "tennis_ai.events.generate_candidates",
        lambda frames: pytest.fail("Completed rerender must not regenerate reviewed events"),
    )
    render_cached(folder)
    assert load_evidence(folder) == before
    exported = export_package(folder, tmp_path / "export")
    assert load_evidence(exported) == before


def test_canonical_link_audit_replays_from_unmaterialized_state(tmp_path):
    shutil.copytree(FIXTURES / "full", tmp_path, dirs_exist_ok=True)
    document = json.loads((tmp_path / "events.json").read_text())
    document["links"] = []
    (tmp_path / "events.json").write_text(json.dumps(document))
    shutil.copyfile(FIXTURES / "link-audit.jsonl", tmp_path / "corrections.jsonl")
    replayed = load_evidence(tmp_path)
    assert replayed["events"]["links"] == [replayed["audit"][0]["after"]]
    assert replayed["metrics"]["metrics"] == []
    assert load_evidence(tmp_path) == replayed


def test_explicit_v2_migration_exports_frame_positions(tmp_path):
    from tennis_ai.artifacts import sha256
    from tennis_ai.package import export_package, load_manifest, write_manifest

    folder = tmp_path / "v2"
    folder.mkdir()
    source = folder / "source.mp4"
    source.write_bytes(b"generated-test")
    metadata = {"width": 320, "height": 180, "duration": 5, "origin": 0}
    write_manifest(folder, source, metadata, {"players": 2}, {}, "complete")
    (folder / "summary.json").write_text(
        json.dumps(
            {
                "status": "complete",
                "source": str(source),
                "source_sha256": sha256(source),
                "video": metadata,
                "settings": {"players": 2},
            }
        )
    )
    sample = {
        "schema_version": 1,
        "timestamp": 1,
        "scene": 0,
        "track_id": 1,
        "side": "unknown",
        "position_court_m": None,
        "method": None,
        "reviewed": False,
        "calibration_id": None,
    }
    (folder / "frames.jsonl").write_text(
        json.dumps({"players": [{"court_position": sample}]}) + "\n"
    )
    target = export_package(folder, tmp_path / "v3", version=3)
    assert load_evidence(target)["tracks"] == [sample]
    assert load_manifest(folder)["schema_version"] == 2
