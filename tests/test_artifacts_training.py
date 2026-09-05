import ast
import json
from pathlib import Path

import pytest

from tennis_ai.artifacts import package, validate_bundle
from tennis_ai.evaluate import evaluate
from tennis_ai.training import partition_groups, source_group


def test_bundle_validation(tmp_path):
    weights = tmp_path / "fake.pt"
    weights.write_bytes(b"test-not-a-checkpoint")
    folder = package(weights, tmp_path / "bundle", "ball", 1280)
    path, _ = validate_bundle(folder, "ball")
    assert path.read_bytes() == weights.read_bytes()
    with pytest.raises(ValueError, match="task"):
        validate_bundle(folder, "court")
    (folder / "weights.pt").write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="checksum"):
        validate_bundle(folder, "ball")


def test_bundle_version_and_path(tmp_path):
    weights = tmp_path / "fake.pt"
    weights.write_bytes(b"test")
    folder = package(weights, tmp_path / "bundle", "ball", 1280)
    manifest = json.loads((folder / "manifest.json").read_text())
    manifest["versions"]["ultralytics"] = "0.0.0"
    (folder / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="version mismatch"):
        validate_bundle(folder, "ball")
    manifest["weights"] = "../fake.pt"
    (folder / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="inside"):
        validate_bundle(folder, "ball")


def test_group_partition_no_leakage():
    items = ["clay1_jpg.rf.abc", "clay2_jpg.rf.def", "synthetic1", "synthetic2", "grass1", "hard1"]
    splits = partition_groups(items, source_group)
    groups = [set(map(source_group, part)) for part in splits]
    assert all(groups)
    assert not groups[0] & groups[1] and not groups[1] & groups[2] and not groups[0] & groups[2]
    with pytest.raises(ValueError, match="Too few"):
        partition_groups(["clay1", "clay2"], source_group)


def test_notebooks_compile_and_have_no_outputs():
    for path in (Path(__file__).parents[1] / "notebooks").glob("*.ipynb"):
        notebook = json.loads(path.read_text())
        for cell in notebook["cells"]:
            if cell["cell_type"] == "code":
                ast.parse("".join(cell["source"]))
                assert cell["outputs"] == []


def test_evaluator_does_not_count_unlabelled_as_negative(tmp_path):
    predictions = tmp_path / "pred.jsonl"
    truth = tmp_path / "gt.jsonl"
    predictions.write_text(
        json.dumps(
            {
                "frame": 0,
                "scene": 0,
                "ball": {"status": "observed", "xy": [10, 10]},
                "players": [],
                "rackets": [],
                "court": None,
            }
        )
        + "\n"
    )
    truth.write_text(json.dumps({"frame": 0, "category": "phone-doubles", "ball": [10, 10]}) + "\n")
    metrics = evaluate(predictions, truth)["phone-doubles"]
    assert metrics["ball_recall"] == metrics["ball_precision"] == 1
    assert metrics["racket_recall"] is None
    assert metrics["player_id_switches"] is None
