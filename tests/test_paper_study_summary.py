"""The paper's descriptive counts must remain tied to frozen records."""

import hashlib
import json
from copy import deepcopy

import pytest

from tennis_ai.events import new_event
from tennis_ai.paper_study import summarize


def _write(path, value):
    path.write_text(json.dumps(value))
    return path.name


def _events(events, duration=300):
    return {
        "schema_version": 2,
        "events": events,
        "coverage": {kind: [[0, duration]] for kind in ("hit", "bounce", "rally")},
    }


def _study(tmp_path):
    candidates = [
        new_event("hit", 1, id="hit-a"),
        new_event("hit", 1.05, id="hit-duplicate"),
        new_event("bounce", 2, id="bounce-a"),
        new_event("rally", 0, id="rally-a", end=3),
    ]
    truth = [candidates[i] for i in (0, 2, 3)]
    reviewer_two = [candidates[i] for i in (0, 3)]
    clips = []
    for index in range(3):
        prefix = f"clip-{index}"
        report = {
            "view": "human_verified",
            "metrics": [{"id": "hits", "value": 1}, {"id": "stroke.forehand", "value": 0}],
        }
        audit = [
            {
                "metric_id": metric,
                "support_resolves": True,
                "inputs_eligible": True,
                "media_opens": True,
            }
            for metric in ("hits", "stroke.forehand")
        ]
        candidate_path = tmp_path / f"{prefix}-candidates.json"
        _write(candidate_path, _events(candidates))
        clips.append(
            {
                "code": prefix,
                "original_match_code": f"match-{index}",
                "duration_seconds": 300,
                "setting": {"fixed_camera": True, "full_court": True, "singles": True},
                "rights": {"analysis_permission": True, "figure_permission": False},
                "source_sha256": "b" * 64,
                "candidates": candidate_path.name,
                "candidate_sha256": hashlib.sha256(candidate_path.read_bytes()).hexdigest(),
                "adjudicated_events": _write(tmp_path / f"{prefix}-truth.json", _events(truth)),
                "adjudicator_code": "A",
                "adjudication_log": _write(tmp_path / f"{prefix}-adjudication.json", []),
                "reviewers": [
                    {
                        "code": code,
                        "independent_events": _write(
                            tmp_path / f"{prefix}-{code}.json", _events(events)
                        ),
                        "annotation_minutes": 12 + offset,
                        "review_minutes": 5 + offset,
                        "paused_minutes": 0,
                        "decisions": {"accept": 2, "correct": 1, "exclude": 1, "unresolved": 0},
                    }
                    for code, events, offset in (("R1", truth, 0), ("R2", reviewer_two, 1))
                ],
                "trace_reports": [
                    {
                        "report": _write(tmp_path / f"{prefix}-report.json", report),
                        "audit": _write(tmp_path / f"{prefix}-audit.json", audit),
                    }
                ],
            }
        )
    manifest = {
        "schema_version": 1,
        "freeze": {
            "software_commit": "a" * 40,
            "model_sha256": {"detector": "c" * 64},
            "protocol_revision": "study-v1",
            "frozen_at_utc": "2026-09-29T00:00:00Z",
        },
        "clips": clips,
    }
    return manifest


def test_study_summary_counts_and_trace_denominator(tmp_path):
    manifest = _study(tmp_path)
    path = tmp_path / "study.json"
    _write(path, manifest)
    report = summarize(path)
    first = report["clips"][0]
    assert first["events"]["hit"]["tp"] == 1
    assert first["events"]["hit"]["fp"] == 1
    assert first["events"]["hit"]["matched_start_error_seconds"]["median"] == 0
    assert first["reviewer_positive_event_agreement"]["bounce"] == {
        "matched": 0,
        "reviewer1_only": 1,
        "reviewer2_only": 0,
    }
    assert report["pooled"]["events"]["hit"]["tp"] == 3
    assert report["pooled"]["events"]["hit"]["fp"] == 3
    assert report["pooled"]["events"]["hit"]["fully_annotated_clips"] == 3
    assert report["pooled"]["events"]["hit"]["labelled_seconds"] == 900
    assert report["pooled"]["traceability"] == {
        "passed": 6,
        "non_null_metrics": 6,
        "proportion": 1.0,
    }
    assert report["pooled"]["annotation_minutes"] == {"median": 12.5, "min": 12, "max": 13}


def test_study_summary_rejects_reused_match_and_incomplete_audit(tmp_path):
    manifest = _study(tmp_path)
    path = tmp_path / "study.json"
    reused = deepcopy(manifest)
    reused["clips"][1]["original_match_code"] = reused["clips"][0]["original_match_code"]
    _write(path, reused)
    with pytest.raises(ValueError, match="original-match codes"):
        summarize(path)

    audit_path = tmp_path / manifest["clips"][0]["trace_reports"][0]["audit"]
    _write(
        audit_path,
        [
            {
                "metric_id": "hits",
                "support_resolves": True,
                "inputs_eligible": True,
                "media_opens": True,
            }
        ],
    )
    _write(path, manifest)
    with pytest.raises(ValueError, match="exactly one row per non-null metric"):
        summarize(path)


def test_study_summary_rejects_changed_predictions_and_exposes_incomplete_coverage(tmp_path):
    manifest = _study(tmp_path)
    path = tmp_path / "study.json"
    _write(path, manifest)
    candidate_path = tmp_path / manifest["clips"][0]["candidates"]
    candidate_path.write_text(candidate_path.read_text() + " ")
    with pytest.raises(ValueError, match="Frozen candidate file SHA-256"):
        summarize(path)

    manifest = _study(tmp_path)
    reviewer_path = tmp_path / manifest["clips"][0]["reviewers"][1]["independent_events"]
    reviewer_events = json.loads(reviewer_path.read_text())
    reviewer_events["coverage"]["hit"] = [[0, 150]]
    _write(reviewer_path, reviewer_events)
    _write(path, manifest)
    assert summarize(path)["clips"][0]["reviewer_positive_event_agreement"]["hit"] is None
