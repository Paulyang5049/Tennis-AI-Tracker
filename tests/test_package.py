import json

import pytest

from tennis_ai.package import load_manifest, relative_asset, write_manifest


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
