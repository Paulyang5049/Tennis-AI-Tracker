from copy import deepcopy
from pathlib import Path

import pytest

from tennis_ai.evidence import load_evidence, validate_evidence

FIXTURES = Path(__file__).resolve().parents[1] / "contracts/fixtures/v3"


def test_shared_entity_audit_replay_is_idempotent(tmp_path):
    import json
    import shutil

    shutil.copytree(FIXTURES / "full", tmp_path, dirs_exist_ok=True)
    shutil.copyfile(FIXTURES / "entity-audit.jsonl", tmp_path / "corrections.jsonl")
    recovered = load_evidence(tmp_path)
    assert recovered["rallies"]["rallies"][0]["shot_ids"] == ["shot-1"]
    recovered["events"]["participants"].append(
        {"id": "opponent", "name": "Opponent", "role": "opponent"}
    )
    for key in ("events", "rallies"):
        (tmp_path / f"{key}.json").write_text(json.dumps(recovered[key]))
    # Restore valid derived results after materialization; replay must retain them.
    again = load_evidence(tmp_path)
    assert [p["id"] for p in again["events"]["participants"]] == ["self", "opponent"]
    assert again["metrics"] == json.loads((FIXTURES / "full/metrics.json").read_text())


def test_cli_identity_review_persists_audit(tmp_path, monkeypatch, capsys):
    import json
    import shutil

    from tennis_ai.cli import main

    folder = tmp_path / "match"
    shutil.copytree(FIXTURES / "minimal", folder)
    payload = tmp_path / "person.json"
    person = {"id": "self", "name": "Player", "role": "self"}
    payload.write_text(json.dumps(person))
    monkeypatch.setattr(
        "sys.argv", ["tennis-ai", "review-entity", str(folder), "participant", str(payload)]
    )
    main()
    result = json.loads(capsys.readouterr().out)
    assert result["events"]["participants"] == [person]
    assert load_evidence(folder)["audit"][0]["entity_type"] == "participant"


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


def test_side_change_mapping_is_audited_and_preserves_identity(tmp_path):
    import shutil

    from tennis_ai.evidence import review_entity

    folder = tmp_path / "match"
    shutil.copytree(FIXTURES / "minimal", folder)
    review_entity(folder, "participant", {"id": "self", "name": "Me", "role": "self"})
    for entity_id, start, end, side in [("near", 0, 2, "near"), ("far", 2, 5, "far")]:
        review_entity(
            folder,
            "assignment",
            {
                "id": entity_id,
                "scene": 0,
                "start": start,
                "end": end,
                "track_id": 1,
                "side": side,
                "participant_id": "self",
                "reviewed": True,
                "confidence": None,
            },
        )
    graph = load_evidence(folder)
    assert len(graph["audit"]) == 3
    assert {a["participant_id"] for a in graph["events"]["assignments"]} == {"self"}
    assert graph["events"]["assignments"][1]["side"] == "far"
