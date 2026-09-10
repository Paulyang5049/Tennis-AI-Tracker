"""Contract, integrity and metric tests; no Core ML, models or downloads needed."""

import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "coreml_export", Path(__file__).resolve().parents[1] / "scripts/export_coreml.py"
)
exporter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(exporter)


@pytest.fixture
def release(tmp_path):
    package = tmp_path / "Detector.mlpackage"
    weights = package / "Data" / "weights"
    weights.mkdir(parents=True)
    (weights / "weight.bin").write_bytes(b"synthetic-weights")
    (package / "Manifest.json").write_text("{}")
    manifest = exporter.make_manifest(
        package, {"sha256": "a" * 64}, 640, 16, "var_123", [1, 300, 6], {}
    )
    manifest_path = tmp_path / "ModelManifest.json"
    exporter.write_json(manifest_path, manifest)
    return package, manifest_path, manifest


def test_cli_defaults_and_invalid_precision():
    args = exporter.build_parser().parse_args(["export", "--output", "candidate"])
    assert (args.imgsz, args.quantize) == (640, 16)
    with pytest.raises(SystemExit):
        exporter.build_parser().parse_args(["export", "--output", "candidate", "--quantize", "4"])


def test_verified_manifest_records_decoder_contract(release):
    package, path, manifest = release
    assert exporter.verify(path) == manifest
    assert manifest["input"]["scale"] == 1 / 255
    assert manifest["output"]["name"] == "var_123"
    assert manifest["output"]["shape"] == [1, 300, 6]
    assert not manifest["output"]["nms"]
    assert manifest["validation"]["status"] == "pending"
    assert len(manifest["files"]) == 2
    assert exporter.package_digest(list(reversed(manifest["files"]))) == manifest["package_sha256"]
    assert package.is_dir()


@pytest.mark.parametrize("change", ["modify", "delete", "add"])
def test_package_integrity_covers_nested_files(release, change):
    package, path, _ = release
    weights = package / "Data/weights/weight.bin"
    if change == "modify":
        weights.write_bytes(b"altered")
    elif change == "delete":
        weights.unlink()
    else:
        (package / "extra.bin").write_bytes(b"extra")
    with pytest.raises(ValueError, match="integrity"):
        exporter.verify(path)


def test_reject_symlinks_and_escape(release, tmp_path):
    package, path, _ = release
    (package / "link").symlink_to(path)
    with pytest.raises(ValueError, match="symlink"):
        exporter.verify(path)
    for unsafe in ("../outside", "/absolute", "..\\outside"):
        with pytest.raises(ValueError, match="Unsafe"):
            exporter.contained(tmp_path, unsafe)


def test_reject_non_end2end_output_shape(release):
    package, _, _ = release
    with pytest.raises(ValueError, match="shape"):
        exporter.make_manifest(package, {}, 640, 16, "out", [1, 84, 8400], {})


def test_never_load_unverified_or_remote_weights(tmp_path):
    args = exporter.build_parser().parse_args(["inspect", "--weights", "https://example.org/x.pt"])
    with pytest.raises(ValueError, match="existing local"):
        exporter.check_source(args)
    source = tmp_path / "yolo26n.pt"
    source.write_bytes(b"synthetic")
    args.weights = source
    with pytest.raises(ValueError, match="checksum"):
        exporter.check_source(args)
    args.expected_sha256 = exporter.sha256(source)
    assert exporter.check_source(args)[1]["sha256"] == args.expected_sha256
    source.write_bytes(b"modified")
    with pytest.raises(ValueError, match="checksum"):
        exporter.check_source(args)


def test_letterbox_roundtrip_landscape_portrait_and_odd_dimensions():
    for width, height in ((1920, 1080), (1080, 1920), (1001, 563)):
        geometry = exporter.letterbox_geometry(width, height, 640)
        row = [
            geometry["left"],
            geometry["top"],
            geometry["left"] + geometry["resized_width"],
            geometry["top"] + geometry["resized_height"],
            0.9,
            32,
        ]
        decoded = exporter.decode_rows([row], geometry, 0.25)
        assert decoded[0]["box"] == pytest.approx([0, 0, width, height])
        assert decoded[0]["class_id"] == 32


def test_decode_filters_nonfinite_classes_confidence_and_padding():
    geometry = exporter.letterbox_geometry(1920, 1080, 640)
    rows = [
        [0, 0, 10, 10, 0.9, 32],
        [0, 150, 20, 170, 0.2, 32],
        [0, 150, 20, 170, 0.9, 4],
        [0, 150, 20, 170, float("nan"), 32],
        [0, 150, 20, 170, 0.9, 32.4],
        [0, 150, 20, 170, 0.9, 32],
    ]
    assert len(exporter.decode_rows(rows, geometry, 0.25)) == 1


def test_ball_matching_is_one_to_one_and_respects_1080p_tolerance():
    truth = [{"class_id": 32, "box": [8, 8, 12, 12]}]
    predictions = [
        {"class_id": 32, "box": [14, 8, 18, 12], "confidence": 0.9},
        {"class_id": 32, "box": [8, 8, 12, 12], "confidence": 0.8},
    ]
    assert exporter.counts(predictions, truth, 32, 1080) == {"tp": 1, "fp": 1, "fn": 0}
    assert exporter.counts(predictions[:1], truth, 32, 540) == {"tp": 0, "fp": 1, "fn": 1}


def test_two_percentage_point_parity_gate_and_no_evidence():
    ref = exporter.metrics({"tp": 100, "fp": 0, "fn": 0})
    assert (
        exporter.parity(ref, exporter.metrics({"tp": 98, "fp": 0, "fn": 2}))["status"] == "passed"
    )
    assert (
        exporter.parity(ref, exporter.metrics({"tp": 97, "fp": 0, "fn": 3}))["status"] == "failed"
    )
    empty = exporter.metrics({"tp": 0, "fp": 0, "fn": 0})
    assert exporter.parity(empty, empty)["status"] == "pending"
    blind = exporter.metrics({"tp": 0, "fp": 0, "fn": 100})
    assert exporter.parity(blind, blind)["status"] == "pending"


def test_frame_manifest_hash_and_original_match_required(tmp_path):
    image = tmp_path / "test.png"
    image.write_bytes(b"synthetic-frame-for-hash-test")
    path = tmp_path / "frames.json"
    frame = {
        "image": "test.png",
        "sha256": exporter.sha256(image),
        "split": "test",
        "match_id": "original-match-1",
        "detections": [],
    }
    exporter.write_json(path, {"schema_version": 1, "frames": [frame]})
    assert exporter.load_frames(path) == [frame]
    frame["split"] = "train"
    exporter.write_json(path, {"schema_version": 1, "frames": [frame]})
    with pytest.raises(ValueError, match="split=test"):
        exporter.load_frames(path)
    frame["split"] = "test"
    frame["sha256"] = "0" * 64
    exporter.write_json(path, {"schema_version": 1, "frames": [frame]})
    with pytest.raises(ValueError, match="checksum"):
        exporter.load_frames(path)


def test_pending_dependencies_do_not_create_release(tmp_path, monkeypatch):
    source = tmp_path / "model.pt"
    source.write_bytes(b"synthetic")
    destination = tmp_path / "release"
    monkeypatch.setattr(exporter, "environment", lambda: {"problems": ["coremltools missing"]})
    result = exporter.main(
        [
            "export",
            "--weights",
            str(source),
            "--expected-sha256",
            exporter.sha256(source),
            "--output",
            str(destination),
        ]
    )
    assert result == 2
    assert not destination.exists()


def test_verify_rejects_manifest_model_path_traversal(release):
    _, path, manifest = release
    manifest["model_file"] = "../Detector.mlpackage"
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="Unsupported"):
        exporter.verify(path)


@pytest.mark.parametrize("shape", [[1, 0, 6], [1, 300.0, 6], [True, 300, 6]])
def test_verify_rejects_invalid_runtime_dimensions(release, shape):
    _, path, manifest = release
    manifest["output"]["shape"] = shape
    exporter.write_json(path, manifest)
    with pytest.raises(ValueError, match="output contract"):
        exporter.verify(path)
