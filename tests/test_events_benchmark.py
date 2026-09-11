import hashlib
import json
from pathlib import Path

import pytest

from tennis_ai.benchmark import (
    evaluate_events,
    evaluate_frames,
    evaluate_manifest,
    load_manifest,
    match_events,
)
from tennis_ai.events import (
    CandidateDetector,
    apply_corrections,
    generate_candidates,
    new_event,
    regenerate_events,
    summarize_events,
    update_event,
)


def write_json(path, value):
    path.write_text(json.dumps(value))
    return path


def write_lines(path, rows):
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return path


def frame(index, point, timestamp=None, **updates):
    return {
        "frame": index,
        "timestamp": index / 30 if timestamp is None else timestamp,
        "scene": 0,
        "players": [],
        "rackets": [],
        "ball": {"status": "observed" if point is not None else "missing", "xy": point},
        **updates,
    }


def events_file(path, events, coverage=None):
    return write_json(path, {"schema_version": 2, "events": events, "coverage": coverage or {}})


def test_shared_fixtures_aggregate_only_reviewed():
    document = json.loads(
        (Path(__file__).resolve().parents[1] / "contracts/fixtures/events.json").read_text()
    )
    summary = summarize_events(document)
    assert summary["verified"]["hit"] == 1
    assert summary["verified"]["rally"] == 0
    assert summary["candidates"]["rally"] == 1
    assert summary["verified"]["landings"][0]["event_id"] == "bounce-0-2"
    assert summary["evidence"][1]["start"] == 0.8


def test_stream_candidates_do_not_project_airborne_ball_and_resume_identically():
    rows = [
        frame(i, point, court={"matrix": [[1, 0, 0], [0, 1, 0], [0, 0, 1]]})
        for i, point in enumerate(([10, 10], [10, 20], [10, 10]))
    ]
    uninterrupted = list(generate_candidates(rows))
    assert len(uninterrupted) == 1
    assert uninterrupted[0]["kind"] == "bounce"
    assert uninterrupted[0]["position"] is None
    assert uninterrupted[0]["stroke"] == "unknown"
    detector = CandidateDetector()
    before = detector.feed(rows[0]) + detector.feed(rows[1])
    detector = CandidateDetector.from_state(json.loads(json.dumps(detector.state_dict())))
    assert before + detector.feed(rows[2]) + detector.finish() == uninterrupted


def test_interpolation_cuts_and_moving_camera_never_contact_evidence():
    for change in (
        {"ball": {"status": "interpolated", "xy": [10, 20]}},
        {"camera_moving": True},
        {"cut": True},
        {"scene": 1},
    ):
        rows = [frame(0, [10, 10]), frame(1, [10, 20], **change), frame(2, [10, 10])]
        assert list(generate_candidates(rows)) == []


def test_hit_and_rally_candidates_have_stable_ids_and_bounded_state():
    players = [{"id": 4, "box": [0, 0, 100, 100]}]
    detector = CandidateDetector()
    output = []
    for index in range(50):
        output.extend(detector.feed(frame(index, [30 if index % 2 else 10, 10], players=players)))
        assert len(detector.state_dict()["samples"]) <= 3
    output.extend(detector.finish())
    assert len([e for e in output if e["kind"] == "rally"]) == 1
    assert all(e["player_id"] == 4 for e in output if e["kind"] == "hit")
    assert len({e["id"] for e in output}) == len(output)
    assert summarize_events(output)["verified"]["hit"] == 0


def test_edits_removals_and_manual_additions_survive_regeneration(tmp_path):
    frames = write_lines(
        tmp_path / "frames.jsonl", [frame(0, [10, 10]), frame(1, [10, 20]), frame(2, [10, 10])]
    )
    events = tmp_path / "events.json"
    corrections = write_json(
        tmp_path / "corrections.json", {"court": {"0": [[0, 0]]}, "labels": {"0": {"1": "Paul"}}}
    )
    doc = regenerate_events(frames, events, corrections)
    event_id = doc["events"][0]["id"]
    update_event(
        events, corrections, event_id, {"position": [2.5, 5], "reviewed": True, "favorite": True}
    )
    update_event(
        events, corrections, None, {"kind": "hit", "start": 1, "stroke": "serve", "reviewed": True}
    )
    # Simulate a detector revision removing the original candidate entirely.
    write_lines(frames, [frame(0, None)])
    doc = regenerate_events(frames, events, corrections)
    summary = summarize_events(doc)
    assert summary["verified"]["bounce"] == 1
    assert summary["verified"]["strokes"] == {"serve": 1}
    assert summary["verified"]["landings"][0]["position"] == [2.5, 5]
    assert json.loads(corrections.read_text())["labels"]["0"]["1"] == "Paul"
    update_event(events, corrections, event_id, {"excluded": True})
    assert (
        summarize_events(regenerate_events(frames, events, corrections))["verified"]["bounce"] == 0
    )


def test_favorite_does_not_promote_candidate_and_invalid_edits_are_rejected(tmp_path):
    event = new_event("hit", 1)
    path = events_file(tmp_path / "events.json", [event])
    corrections = tmp_path / "corrections.json"
    doc = update_event(path, corrections, event["id"], {"favorite": True})
    assert summarize_events(doc)["verified"]["hit"] == 0
    with pytest.raises(ValueError, match="identical"):
        update_event(path, corrections, event["id"], {"end": 2})
    with pytest.raises(ValueError, match="Unsupported"):
        update_event(path, corrections, event["id"], {"id": "overwrite"})
    with pytest.raises(ValueError, match="id"):
        apply_corrections([], {"events": {"other": event}})


def test_matching_is_one_to_one_and_maximum_cardinality():
    pred = [new_event("hit", 0.08), new_event("hit", 0)]
    truth = [new_event("hit", 0), new_event("hit", 0.17)]
    assert len(match_events(pred, truth, "hit")) == 2
    assert len(match_events(pred, truth[:1], "hit")) == 1
    assert (
        match_events([new_event("rally", 0, end=2)], [new_event("rally", 1, end=3)], "rally") == []
    )
    assert (
        len(
            match_events(
                [new_event("rally", 0, end=2)], [new_event("rally", 0.5, end=2.5)], "rally"
            )
        )
        == 1
    )


def test_missing_frame_predictions_count_as_false_negatives_and_absence_as_fp(tmp_path):
    gt = write_lines(
        tmp_path / "gt.jsonl",
        [
            {"frame": 0, "ball": [10, 10], "distance": "far"},
            {"frame": 1, "ball": None},
            {"frame": 2},
        ],
    )
    pred = write_lines(tmp_path / "pred.jsonl", [frame(1, [10, 10]), frame(2, [10, 10])])
    result = evaluate_frames(pred, gt)
    assert (result["tp"], result["fp"], result["fn"]) == (0, 1, 1)
    assert result["labelled_frames"] == 2
    assert result["legacy_metrics"]["unspecified"]["ball_recall"] == 0
    assert result["missing_prediction_frames"] == 1


def test_six_pixel_tolerance_scales_and_interpolation_is_missing(tmp_path):
    gt = write_lines(tmp_path / "gt.jsonl", [{"frame": 0, "ball": [10, 10]}])
    pred = write_lines(tmp_path / "pred.jsonl", [frame(0, [14, 10])])
    assert evaluate_frames(pred, gt, height=1080)["tp"] == 1
    assert evaluate_frames(pred, gt, height=540)["fn"] == 1
    write_lines(pred, [frame(0, [10, 10], ball={"status": "interpolated", "xy": [10, 10]})])
    assert evaluate_frames(pred, gt)["fn"] == 1


def test_unknown_and_missed_strokes_are_fn_and_unmatched_predictions_are_fp(tmp_path):
    gt = events_file(
        tmp_path / "gt.json",
        [
            new_event("hit", 1, stroke="serve", id="a"),
            new_event("hit", 2, stroke="forehand", id="b"),
            new_event("hit", 3, stroke="backhand", id="c"),
        ],
        {"hit": [[0, 5]]},
    )
    pred = events_file(
        tmp_path / "pred.json",
        [
            new_event("hit", 1, id="a"),
            new_event("hit", 2, stroke="volley", id="b"),
            new_event("hit", 4, stroke="overhead", id="c"),
        ],
    )
    result = evaluate_events(pred, gt, 5)
    assert result["events"]["hit"]["tp"] == 2
    assert result["events"]["hit"]["fn"] == 1
    assert result["events"]["hit"]["fp"] == 1
    for label in ("serve", "forehand", "backhand"):
        assert result["strokes"]["per_class"][label]["fn"] == 1
    for label in ("volley", "overhead"):
        assert result["strokes"]["per_class"][label]["fp"] == 1
    assert result["strokes"]["macro_f1"] == 0


def test_landing_metrics_include_missed_events_and_missing_positions(tmp_path):
    gt = events_file(
        tmp_path / "gt.json",
        [new_event("bounce", i, id=str(i), position=[1, 2]) for i in (1, 2, 3)],
        {"bounce": [[0, 4]]},
    )
    pred = events_file(
        tmp_path / "pred.json",
        [new_event("bounce", 1, id="a", position=[1.3, 2.4]), new_event("bounce", 2, id="b")],
    )
    result = evaluate_events(pred, gt, 4)
    assert result["landing"]["median_error_m"] == pytest.approx(0.5)
    assert result["landing"]["missed_bounce_events"] == 1
    assert result["landing"]["matched_missing_prediction_positions"] == 1


def test_event_negative_time_must_be_explicit(tmp_path):
    pred = events_file(tmp_path / "pred.json", [new_event("hit", 1)])
    gt = events_file(tmp_path / "gt.json", [])
    result = evaluate_events(pred, gt, 2)
    assert result["events"]["hit"]["fp"] == 0
    assert result["events"]["hit"]["outside_coverage_predictions"] == 1
    assert not result["events"]["hit"]["fully_annotated"]
    events_file(gt, [], {"hit": [[0, 2]]})
    assert evaluate_events(pred, gt, 2)["events"]["hit"]["fp"] == 1


def clip(tmp_path, name="one", **updates):
    source = tmp_path / f"{name}.mp4"
    source.write_bytes(b"synthetic-placeholder-no-private-video")
    write_lines(tmp_path / f"{name}-gt.jsonl", [{"frame": 0, "ball": [10, 10]}])
    write_lines(tmp_path / f"{name}-pred.jsonl", [frame(0, [10, 10])])
    return {
        "clip_id": name,
        "match_id": name,
        "split": "test",
        "category": "phone-singles",
        "source": source.name,
        "annotations": f"{name}-gt.jsonl",
        "predictions": f"{name}-pred.jsonl",
        "width": 1920,
        "height": 1080,
        "duration": 2,
        **updates,
    }


def test_manifest_rejects_original_match_leakage_duplicate_source_and_missing_files(tmp_path):
    first = clip(tmp_path)
    second = clip(tmp_path, "two", match_id="one", split="train")
    path = write_json(tmp_path / "manifest.json", {"schema_version": 1, "clips": [first, second]})
    with pytest.raises(ValueError, match="leaks"):
        load_manifest(path)
    second.update(match_id="two", source=first["source"])
    write_json(path, {"schema_version": 1, "clips": [first, second]})
    with pytest.raises(ValueError, match="Duplicate clip source"):
        load_manifest(path)
    first["annotations"] = "absent.jsonl"
    write_json(path, {"schema_version": 1, "clips": [first]})
    with pytest.raises(ValueError, match="Missing"):
        load_manifest(path)


def test_manifest_rejects_escaping_paths_and_symlinks(tmp_path):
    row = clip(tmp_path)
    path = tmp_path / "manifest.json"
    for invalid in ("../outside.mp4", "/tmp/outside.mp4"):
        write_json(path, {"schema_version": 1, "clips": [{**row, "source": invalid}]})
        with pytest.raises(ValueError, match="relative paths"):
            load_manifest(path)
    outside = tmp_path.parent / f"{tmp_path.name}-outside.mp4"
    outside.write_bytes(b"x")
    try:
        (tmp_path / "link.mp4").symlink_to(outside)
        write_json(path, {"schema_version": 1, "clips": [{**row, "source": "link.mp4"}]})
        with pytest.raises(ValueError, match="escapes"):
            load_manifest(path)
    finally:
        outside.unlink()


def test_perfect_sparse_frames_cannot_pass_phone_release_gate(tmp_path):
    rows = [clip(tmp_path, str(i)) for i in range(5)]
    path = write_json(tmp_path / "manifest.json", {"schema_version": 1, "clips": rows})
    report = evaluate_manifest(path)
    assert report["categories"]["phone-singles"]["frames"]["precision"] == 1
    gate = report["phone_quality_gates"]["phone-singles"]
    assert gate["independent_matches"] == 5
    assert not gate["passed"]
    assert any("negative" in reason for reason in gate["reasons"])
    assert any("event inputs" in reason for reason in gate["reasons"])
    assert report["phone_quality_gates"]["phone-doubles"]["independent_matches"] == 0
    assert not report["release_ready"]


def test_empty_manifest_reports_missing_coverage_not_success(tmp_path):
    path = write_json(tmp_path / "manifest.json", {"schema_version": 1, "clips": []})
    report = evaluate_manifest(path)
    assert not report["phone_quality_passed"]
    assert report["categories"]["phone-singles"]["frames"]["precision"] is None


def test_frame_benchmark_streams_without_whole_file_reads(tmp_path, monkeypatch):
    """An unordered long history uses the disk index, not read_text/readlines."""
    truth = tmp_path / "truth.jsonl"
    predictions = tmp_path / "predictions.jsonl"
    with truth.open("w") as gt, predictions.open("w") as pred:
        for index in reversed(range(12000)):
            gt.write(json.dumps({"frame": index, "ball": [10, 10]}) + "\n")
            pred.write(json.dumps(frame(index, [10, 10])) + "\n")

    def forbidden(*args, **kwargs):
        raise AssertionError("Frame histories must not be read wholesale")

    monkeypatch.setattr(Path, "read_text", forbidden)
    result = evaluate_frames(predictions, truth)
    assert result["tp"] == 12000
    assert result["missing_prediction_frames"] == 0


def test_disk_frame_index_rejects_duplicate_ids(tmp_path):
    gt = write_lines(tmp_path / "gt.jsonl", [{"frame": 1, "ball": None}])
    pred = write_lines(tmp_path / "pred.jsonl", [frame(1, None), frame(1, None)])
    with pytest.raises(ValueError, match="Duplicate"):
        evaluate_frames(pred, gt)


@pytest.mark.parametrize("declared", [None, "bad", "0" * 64, 123])
def test_declared_source_sha256_must_be_valid_and_match(tmp_path, declared):
    row = clip(tmp_path, source_sha256=declared)
    path = write_json(tmp_path / "manifest.json", {"schema_version": 1, "clips": [row]})
    with pytest.raises(ValueError, match="source_sha256"):
        load_manifest(path)


def test_source_checksum_optional_and_valid_digest_accepted(tmp_path):
    row = clip(tmp_path)
    path = write_json(tmp_path / "manifest.json", {"schema_version": 1, "clips": [row]})
    assert len(load_manifest(path)["clips"]) == 1
    row["source_sha256"] = hashlib.sha256((tmp_path / row["source"]).read_bytes()).hexdigest()
    write_json(path, {"schema_version": 1, "clips": [row]})
    assert load_manifest(path)["clips"][0]["source_sha256"] == row["source_sha256"]


@pytest.mark.parametrize("declared", [False, True])
def test_content_alias_across_splits_rejected_even_with_different_match_ids(tmp_path, declared):
    rows = [clip(tmp_path, "a"), clip(tmp_path, "b", split="train")]
    if declared:
        for row in rows:
            row["source_sha256"] = hashlib.sha256(
                (tmp_path / row["source"]).read_bytes()
            ).hexdigest()
    path = write_json(tmp_path / "manifest.json", {"schema_version": 1, "clips": rows})
    with pytest.raises(ValueError, match="content.*leaks"):
        evaluate_manifest(path)


def test_ball_bootstrap_resamples_matches_not_clips_and_is_reproducible(tmp_path):
    rows = [clip(tmp_path, "a"), clip(tmp_path, "b", match_id="a"), clip(tmp_path, "c")]
    write_lines(tmp_path / "c-pred.jsonl", [frame(0, [100, 100])])
    path = write_json(tmp_path / "manifest.json", {"schema_version": 1, "clips": rows})
    report = evaluate_manifest(path)
    result = report["categories"]["phone-singles"]["frames"]
    ci = result["confidence_intervals"]
    assert result["precision"] == pytest.approx(2 / 3)
    assert ci["unit"] == "match"
    assert ci["independent_matches"] == 2
    assert ci["seed"] == 0
    assert ci["resamples"] == 2000
    for metric in ("precision", "recall"):
        assert ci[metric]["status"] == "ok"
        assert ci[metric]["lower"] == 0
        assert ci[metric]["upper"] == 1
    write_json(path, {"schema_version": 1, "clips": rows[::-1]})
    assert evaluate_manifest(path)["categories"]["phone-singles"]["frames"] == result
    # Combining two clips into one must leave the cluster distribution unchanged.
    write_lines(tmp_path / "a-gt.jsonl", [{"frame": i, "ball": [10, 10]} for i in range(2)])
    write_lines(tmp_path / "a-pred.jsonl", [frame(i, [10, 10]) for i in range(2)])
    write_json(path, {"schema_version": 1, "clips": [rows[0], rows[2]]})
    assert evaluate_manifest(path)["categories"]["phone-singles"]["frames"] == result


@pytest.mark.parametrize("count", [0, 1])
def test_ball_bootstrap_reports_insufficient_matches(tmp_path, count):
    rows = [clip(tmp_path, str(i), match_id="same") for i in range(count * 3)]
    path = write_json(tmp_path / "manifest.json", {"schema_version": 1, "clips": rows})
    ci = evaluate_manifest(path)["categories"]["phone-singles"]["frames"]["confidence_intervals"]
    assert ci["independent_matches"] == count
    for metric in ("precision", "recall"):
        assert ci[metric]["status"] == "insufficient_matches"
        assert ci[metric]["lower"] is None
        assert ci[metric]["upper"] is None


def test_ball_bootstrap_reports_undefined_denominators(tmp_path):
    rows = [clip(tmp_path, str(i)) for i in range(2)]
    for row in rows:
        write_lines(tmp_path / row["predictions"], [frame(0, None)])
    path = write_json(tmp_path / "manifest.json", {"schema_version": 1, "clips": rows})
    ci = evaluate_manifest(path)["categories"]["phone-singles"]["frames"]["confidence_intervals"]
    assert ci["precision"]["status"] == "undefined_denominator"
    assert ci["precision"]["lower"] is None
    assert ci["precision"]["valid_resamples"] == 0
    assert ci["recall"]["lower"] == ci["recall"]["upper"] == 0
