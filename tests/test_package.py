import json

import pytest

from tennis_ai.artifacts import sha256
from tennis_ai.package import export_package, load_manifest, relative_asset, write_manifest


def test_package_is_portable_and_rejects_escape(tmp_path):
    media = tmp_path / "source.mp4"
    media.write_bytes(b"video")
    metadata = {"width": 1920, "height": 1080, "duration": 2.0, "origin": 0.0}
    manifest = write_manifest(tmp_path, media, metadata, {"players": 4}, {"detector": "abc"})
    assert manifest["schema_version"] == 2
    assert load_manifest(tmp_path)["media"]["path"] == "source.mp4"
    with pytest.raises(ValueError):
        relative_asset(tmp_path, "../private.mp4")
    with pytest.raises(ValueError):
        relative_asset(tmp_path, "/private.mp4")


def test_v1_adapter_and_future_version(tmp_path):
    (tmp_path / "source.mp4").write_bytes(b"video")
    summary = {
        "schema_version": 1,
        "source": str(tmp_path / "source.mp4"),
        "source_sha256": "abc",
        "video": {"width": 320, "height": 180},
        "settings": {"players": 2},
        "status": "complete",
    }
    (tmp_path / "summary.json").write_text(json.dumps(summary))
    assert load_manifest(tmp_path)["schema_version"] == 2
    assert not (tmp_path / "manifest.json").exists()
    (tmp_path / "manifest.json").write_text('{"schema_version": 99}')
    with pytest.raises(ValueError, match="version"):
        load_manifest(tmp_path)


def test_export_legacy_survives_source_and_folder_move(tmp_path):
    source = tmp_path / "external.mp4"
    source.write_bytes(b"original-video")
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    summary = {
        "schema_version": 1,
        "source": str(source),
        "source_sha256": sha256(source),
        "video": {"width": 320, "height": 180, "duration": 1, "origin": 0},
        "settings": {"players": 2},
        "status": "complete",
    }
    (legacy / "summary.json").write_text(json.dumps(summary))
    (legacy / "frames.jsonl").write_text("")
    (legacy / "cache.sqlite").write_bytes(b"cache")
    target = export_package(legacy, tmp_path / "export")
    source.unlink()
    moved = tmp_path / "moved"
    target.rename(moved)
    manifest = load_manifest(moved)
    assert relative_asset(moved, manifest["media"]["path"]).read_bytes() == b"original-video"
    assert (moved / "cache.sqlite").read_bytes() == b"cache"
    assert json.loads((moved / "events.json").read_text())["schema_version"] == 2
    with pytest.raises(ValueError, match="already exists"):
        export_package(legacy, moved)


def test_export_rejects_changed_source_and_cleans_staging(tmp_path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"changed")
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "summary.json").write_text(
        json.dumps({"status": "complete", "source": str(source), "source_sha256": "old"})
    )
    with pytest.raises(ValueError, match="Source changed"):
        export_package(legacy, tmp_path / "export")
    assert not (tmp_path / "export").exists()
    assert not list(tmp_path.glob(".package-*"))


def test_explicit_v3_migration_and_roundtrip_preserve_v2(tmp_path):
    from tennis_ai.evidence import load_evidence

    source = tmp_path / "run"
    source.mkdir()
    video = source / "source.mp4"
    video.write_bytes(b"video")
    metadata = {"width": 320, "height": 180, "duration": 2, "origin": 0}
    write_manifest(source, video, metadata, {"players": 2}, {}, "complete")
    (source / "frames.jsonl").write_text("")
    (source / "summary.json").write_text(
        json.dumps(
            {
                "status": "complete",
                "source": str(video),
                "source_sha256": sha256(video),
                "video": metadata,
                "settings": {"players": 2},
            }
        )
    )
    before = (source / "manifest.json").read_bytes()
    target = export_package(source, tmp_path / "v3", version=3)
    assert (source / "manifest.json").read_bytes() == before
    assert load_manifest(target)["migration"]["from_version"] == 2
    assert load_evidence(target)["events"]["participants"] == []
    second = export_package(target, tmp_path / "roundtrip")
    assert load_manifest(second)["schema_version"] == 3
    assert load_evidence(second) == load_evidence(target)
    with pytest.raises(ValueError, match="downgrade"):
        export_package(target, tmp_path / "downgrade", version=2)
