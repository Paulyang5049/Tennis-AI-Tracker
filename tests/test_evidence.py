from copy import deepcopy
from pathlib import Path

import pytest

from tennis_ai.evidence import load_evidence, validate_evidence

FIXTURES = Path(__file__).resolve().parents[1] / "contracts/fixtures/v3"


def test_track_sampling_preserves_frames_and_bounds_summary(tmp_path, monkeypatch):
    import json
    import shutil

    import tennis_ai.evidence as evidence
    from tennis_ai.package import load_manifest

    shutil.copytree(FIXTURES / "full", tmp_path, dirs_exist_ok=True)
    manifest = load_manifest(tmp_path)
    sample = json.loads((FIXTURES / "legacy-track.jsonl").read_text())
    fixture = json.loads((FIXTURES / "track-sampling-v1.json").read_text())
    frames = [
        {"players": [{"court_position": dict(sample, timestamp=t)}]} for t in fixture["timestamps"]
    ]
    original = deepcopy(frames)
    result = evidence.persist_frame_tracks(tmp_path, manifest, frames)
    assert [s["timestamp"] for s in result["tracks"]] == fixture["retained"]
    assert frames == original
    assert (
        load_manifest(tmp_path)["derivation_versions"]["automatic_track_sampling"]
        == evidence.TRACK_SAMPLING_VERSION
    )
    before = (tmp_path / "tracks.jsonl").read_bytes()
    monkeypatch.setattr(evidence, "MAX_ROWS", 3)
    # Four selected rows exceed the bound; no existing asset is replaced.
    with pytest.raises(ValueError, match="portable limits"):
        evidence.persist_frame_tracks(
            tmp_path,
            manifest,
            frames + [{"players": [{"court_position": dict(sample, timestamp=2)}]}],
        )
    assert (tmp_path / "tracks.jsonl").read_bytes() == before


def test_long_match_sampling_is_portable(tmp_path):
    import json
    import shutil

    from tennis_ai.evidence import persist_frame_tracks
    from tennis_ai.package import atomic_json, load_manifest

    shutil.copytree(FIXTURES / "full", tmp_path, dirs_exist_ok=True)
    manifest = load_manifest(tmp_path)
    manifest["media"]["duration"] = 1800
    atomic_json(tmp_path / "manifest.json", manifest)
    sample = json.loads((FIXTURES / "legacy-track.jsonl").read_text())
    frames = (
        {
            "players": [
                {"court_position": dict(sample, timestamp=i / 30, track_id=track)}
                for track in (1, 2)
            ]
        }
        for i in range(54_000)
    )
    graph = persist_frame_tracks(tmp_path, manifest, frames)
    assert len(graph["tracks"]) == 7200
    assert load_evidence(tmp_path) == graph


def test_failed_audit_replace_keeps_match_reopenable(tmp_path, monkeypatch):
    import shutil

    from tennis_ai.evidence import review_entity

    shutil.copytree(FIXTURES / "full", tmp_path, dirs_exist_ok=True)
    before = load_evidence(tmp_path)
    original_replace = __import__("os").replace

    def fail_audit_replace(source, target):
        if str(target).endswith("corrections.jsonl"):
            raise OSError("injected audit write failure")
        return original_replace(source, target)

    monkeypatch.setattr("tennis_ai.evidence.os.replace", fail_audit_replace)
    with pytest.raises(OSError, match="injected audit"):
        review_entity(tmp_path, "participant", {"id": "self", "name": "Changed", "role": "self"})
    assert load_evidence(tmp_path) == before
    assert not list(tmp_path.glob(".audit-*"))


def test_removed_links_and_rallies_allow_reviewed_shot_reclassification(tmp_path):
    import json
    import shutil

    from tennis_ai.evidence import edit_evidence_event, review_entity
    from tennis_ai.review_statistics import review_report

    shutil.copytree(FIXTURES / "full", tmp_path, dirs_exist_ok=True)
    graph = load_evidence(tmp_path)
    link = dict(graph["events"]["links"][0], reviewed=False, removed=True)
    review_entity(tmp_path, "link", link, reason="remove wrong link")
    rally = {
        "id": "wrong-rally",
        "start": 1,
        "end": 1,
        "shot_ids": ["shot-1"],
        "reviewed": True,
        "outcome": None,
    }
    review_entity(tmp_path, "rally", rally, reason="create rally")
    review_entity(
        tmp_path, "rally", dict(rally, reviewed=False, removed=True), reason="remove wrong rally"
    )
    edit_evidence_event(
        tmp_path,
        "shot-1",
        {"kind": "bounce", "contact_point_image_px": None, "hitter_position_court_m": None},
    )
    edited = load_evidence(tmp_path)
    assert next(e for e in edited["events"]["events"] if e["id"] == "shot-1")["kind"] == "bounce"
    assert (
        next(
            r
            for r in review_report(edited, view="human_verified", end=5)["metrics"]
            if r["id"] == "hits"
        )["value"]
        is None
    )
    stale = json.loads((tmp_path / "events.json").read_text())
    stale["links"] = graph["events"]["links"]
    (tmp_path / "events.json").write_text(json.dumps(stale))
    assert load_evidence(tmp_path) == edited


def test_shared_removed_link_audit_replays(tmp_path):
    import shutil

    shutil.copytree(FIXTURES / "full", tmp_path, dirs_exist_ok=True)
    shutil.copyfile(FIXTURES / "removed-associations-audit.jsonl", tmp_path / "corrections.jsonl")
    graph = load_evidence(tmp_path)
    assert graph["events"]["links"][0]["removed"] is True
    assert graph["metrics"]["metrics"] == []
    assert load_evidence(tmp_path) == graph


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


def test_participant_cannot_occupy_two_tracks_at_once():
    import json

    bundle = deepcopy(load_evidence(FIXTURES / "full"))
    bundle["events"]["assignments"] = json.loads(
        (FIXTURES / "overlapping-participant-assignments.json").read_text()
    )
    with pytest.raises(ValueError, match="Overlapping participant"):
        validate_evidence(bundle, 5)


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
