from copy import deepcopy
from pathlib import Path

import pytest

from tennis_ai.evidence import load_evidence, validate_evidence

FIXTURES = Path(__file__).resolve().parents[1] / "contracts/fixtures/v3"


def test_packaged_schemas_match_canonical_contracts():
    import json
    from importlib.resources import files

    from jsonschema import Draft202012Validator

    root = FIXTURES.parents[1]
    packaged = json.loads(files("tennis_ai").joinpath("contract_schemas.json").read_text())
    expected = {path.name: json.loads(path.read_text()) for path in root.glob("*.schema.json")}
    assert packaged == expected
    for schema in packaged.values():
        Draft202012Validator.check_schema(schema)


@pytest.mark.parametrize("name", ["minimal", "uncertain", "corrected", "full"])
def test_shared_v3_fixtures(name):
    bundle = load_evidence(FIXTURES / name)
    assert bundle["events"]["schema_version"] == 3
    validate_evidence(bundle, 5)


@pytest.mark.parametrize("mutation", ["reference", "time", "nan", "mapping", "airborne"])
def test_invalid_evidence_fails_closed(mutation):
    bundle = deepcopy(load_evidence(FIXTURES / "full"))
    doc = bundle["events"]
    if mutation == "reference":
        doc["links"][0]["bounce_id"] = "missing"
    elif mutation == "time":
        doc["events"][0]["contact_interval"] = [2, 1]
    elif mutation == "nan":
        doc["events"][0]["contact_point_image_px"] = [float("nan"), 0]
    elif mutation == "mapping":
        doc["assignments"][0]["participant_id"] = None
    else:
        doc["events"][0]["position"] = [1, 2]
    with pytest.raises(ValueError):
        validate_evidence(bundle, 5)


def test_audit_fixture_retains_before_after():
    bundle = load_evidence(FIXTURES / "corrected")
    assert bundle["audit"][0]["before"]["stroke"] == "unknown"
    assert bundle["audit"][0]["after"]["stroke"] == "forehand"


def test_v3_manifest_can_be_loaded_without_migration():
    from tennis_ai.package import load_manifest

    path = FIXTURES / "minimal" / "manifest.json"
    before = path.read_bytes()
    assert load_manifest(path.parent)["schema_version"] == 3
    assert path.read_bytes() == before


def test_v3_review_is_audited_and_survives_crash_replay(tmp_path):
    import shutil

    from tennis_ai.evidence import edit_evidence_event

    target = tmp_path / "match"
    shutil.copytree(FIXTURES / "full", target)
    original = (target / "events.json").read_bytes()
    edit_evidence_event(
        target, "shot-1", {"stroke": "backhand"}, actor="reviewer", reason="video review"
    )
    bundle = load_evidence(target)
    assert bundle["audit"][0]["before"]["stroke"] == "unknown"
    assert bundle["events"]["events"][0]["stroke"] == "backhand"
    # Simulate failure between durable audit append and materialized event write.
    (target / "events.json").write_bytes(original)
    assert load_evidence(target)["events"]["events"][0]["stroke"] == "backhand"
    edit_evidence_event(target, "shot-1", {"favorite": True}, actor="reviewer", reason="bookmark")
    assert [r["sequence"] for r in load_evidence(target)["audit"]] == [1, 2]
