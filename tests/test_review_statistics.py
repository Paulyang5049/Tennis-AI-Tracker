import json
from pathlib import Path

from tennis_ai.evidence import load_evidence
from tennis_ai.review_statistics import review_report


def test_positions_keep_evidence_exclusions_and_rally_lengths():
    root = Path(__file__).resolve().parents[1] / "contracts/fixtures/v3"
    graph = load_evidence(root / "full")
    graph["tracks"] = [
        json.loads(row) for row in (root / "report-tracks.jsonl").read_text().splitlines()
    ]
    for view, count in (("assisted", 2), ("human_verified", 1)):
        report = review_report(graph, view=view, participant_id="self", end=3)
        positions = next(row for row in report["metrics"] if row["id"] == "player_positions")
        assert positions["value"] == count
        assert positions["sample_count"] == count
        assert positions["support_refs"] == [f"track:{i}" for i in range(count)]
        assert positions["points"][0]["position"] == [4, 2]
        assert positions["exclusions"]["track:2"] == "missing_position"
        assert positions["exclusions"]["track:3"] == "outside_range"
        assert positions["exclusions"]["track:4"] == "unresolved_or_other_identity"
        if view == "human_verified":
            assert positions["exclusions"]["track:1"] == "unreviewed"
    shot = graph["events"]["events"][0]
    graph["events"]["events"].extend(
        [dict(shot, id="shot-2", start=3, end=3), dict(shot, id="shot-3", start=4, end=4)]
    )
    graph["rallies"]["rallies"] = [
        {"id": "one", "start": 1, "end": 1, "shot_ids": ["shot-1"], "reviewed": True},
        {"id": "two", "start": 3, "end": 4, "shot_ids": ["shot-2", "shot-3"], "reviewed": True},
    ]

    def rally():
        return next(
            row
            for row in review_report(graph, view="human_verified", end=5)["metrics"]
            if row["id"] == "rally_length"
        )

    assert rally()["value"] == 1.5
    assert rally()["sample_count"] == 2
    assert rally()["event_ids"] == ["shot-1", "shot-2", "shot-3"]
    graph["events"]["events"][-1]["reviewed"] = False
    assert rally()["value"] == 1
    assert rally()["exclusions"] == {"rally:two": "missing_or_ineligible_shot_list"}


def test_report_separates_views_and_unassigned_landings():
    graph = load_evidence(Path(__file__).resolve().parents[1] / "contracts/fixtures/v3/full")
    report = review_report(graph, view="human_verified", participant_id="self", end=5)
    rows = {row["id"]: row for row in report["metrics"]}
    assert rows["hits"]["value"] == 1
    assert rows["stroke.unknown"]["value"] == 1
    assert rows["landings"]["event_ids"] == ["bounce-1", "shot-1"]
    graph["events"]["links"][0]["reviewed"] = False
    changed = review_report(graph, view="human_verified", participant_id="self", end=5)
    assert changed["input_digest"] != report["input_digest"]
    assert next(r for r in changed["metrics"] if r["id"] == "landings")["value"] is None
    assisted = review_report(graph, view="assisted", participant_id="self", end=5)
    assert next(r for r in assisted["metrics"] if r["id"] == "landings")["value"] == 1


def test_scene_mapping_and_empty_denominator():
    graph = load_evidence(Path(__file__).resolve().parents[1] / "contracts/fixtures/v3/full")
    graph["events"]["events"][0]["scene"] = 1
    report = review_report(graph, view="assisted", participant_id="self", end=5)
    assert next(r for r in report["metrics"] if r["id"] == "hits")["value"] is None


def test_candidate_identity_never_creates_personal_statistics():
    graph = load_evidence(Path(__file__).resolve().parents[1] / "contracts/fixtures/v3/full")
    graph["events"]["assignments"][0]["reviewed"] = False
    report = review_report(graph, view="assisted", participant_id="self", end=5)
    assert next(r for r in report["metrics"] if r["id"] == "hits")["value"] is None
