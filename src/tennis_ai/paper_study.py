"""Summarize a frozen, private reviewer study without publishing its source records."""

import argparse
import hashlib
import json
import math
import statistics
from pathlib import Path

from tennis_ai.benchmark import evaluate_events, match_events
from tennis_ai.events import KINDS


def _object(value, label):
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _list(value, label):
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")
    return value


def _number(value, label, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label} must be finite and numeric")
    if value < 0 or (positive and value == 0):
        raise ValueError(f"{label} must be nonnegative")
    return value


def _code(value, label):
    if not isinstance(value, str) or not value or any(c in value for c in ("/", "\\", "\n")):
        raise ValueError(f"{label} must be a nonempty private code without path separators")
    return value


def _sha256(value, label):
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(c not in "0123456789abcdef" for c in value)
    ):
        raise ValueError(f"{label} must be a lowercase SHA-256")
    return value


def _file(base, value, label):
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must name a file")
    path = (base / value).resolve()
    if not path.is_file():
        raise ValueError(f"{label} does not exist: {path}")
    return path


def _events(path):
    document = _object(json.loads(path.read_text()), str(path))
    if document.get("schema_version") != 2:
        raise ValueError(f"{path} must use events schema version 2")
    return [e for e in _list(document.get("events"), "events") if not e.get("excluded", False)]


def _matched_times(predicted, truth, kind):
    a = [e for e in predicted if e["kind"] == kind]
    b = [e for e in truth if e["kind"] == kind]
    return [abs(a[i]["start"] - b[j]["start"]) for i, j in match_events(a, b, kind)]


def _median_range(values):
    return (
        {"median": statistics.median(values), "min": min(values), "max": max(values)}
        if values
        else None
    )


def _trace(base, entries):
    passed = total = 0
    failures: dict[str, int] = {}
    reports = _list(entries, "trace_reports")
    if not reports:
        raise ValueError("At least one human-verified report requires a trace audit")
    for index, raw in enumerate(reports):
        row = _object(raw, f"trace_reports[{index}]")
        report = _object(
            json.loads(_file(base, row.get("report"), "review report").read_text()), "review report"
        )
        if report.get("view") != "human_verified":
            raise ValueError("Trace audit requires human_verified reports")
        metrics = _list(report.get("metrics"), "report metrics")
        non_null_rows = [m for m in metrics if m["value"] is not None]
        non_null = {m["id"] for m in non_null_rows}
        if len(non_null) != len(non_null_rows):
            raise ValueError("Report contains duplicate non-null metric IDs")
        checks = _list(
            json.loads(_file(base, row.get("audit"), "trace audit").read_text()), "trace audit"
        )
        indexed = {_code(c["metric_id"], "metric_id"): c for c in checks}
        if len(indexed) != len(checks) or set(indexed) != non_null:
            raise ValueError("Trace audit must have exactly one row per non-null metric")
        for metric_id in sorted(non_null):
            check = indexed[metric_id]
            fields = ("support_resolves", "inputs_eligible", "media_opens")
            if any(type(check.get(field)) is not bool for field in fields):
                raise ValueError(f"Trace audit flags must be boolean: {metric_id}")
            total += 1
            if all(check[field] for field in fields):
                passed += 1
            else:
                code = _code(check.get("failure_code"), "failure_code")
                if code not in {
                    "missing_support",
                    "unreviewed_input",
                    "identity_unresolved",
                    "association_unreviewed",
                    "media_missing",
                    "seek_failed",
                    "other",
                }:
                    raise ValueError(f"Unknown trace failure code: {code}")
                failures[code] = failures.get(code, 0) + 1
    return {
        "passed": passed,
        "non_null_metrics": total,
        "failures": failures,
        "proportion": passed / total if total else None,
    }


def _reviewer(base, value):
    row = _object(value, "reviewer")
    code = _code(row.get("code"), "reviewer code")
    independent = _file(base, row.get("independent_events"), "independent events")
    annotation = _number(row.get("annotation_minutes"), "annotation_minutes", positive=True)
    review = _number(row.get("review_minutes"), "review_minutes", positive=True)
    paused = _number(row.get("paused_minutes"), "paused_minutes")
    decisions = _object(row.get("decisions"), "decisions")
    expected = {"accept", "correct", "exclude", "unresolved"}
    if set(decisions) != expected or any(
        type(decisions[key]) is not int or decisions[key] < 0 for key in expected
    ):
        raise ValueError("Decisions require nonnegative accept/correct/exclude/unresolved counts")
    return {
        "code": code,
        "independent_path": independent,
        "annotation_minutes": annotation,
        "review_minutes": review,
        "paused_minutes": paused,
        "decisions": decisions,
    }


def summarize(path):
    path = Path(path).resolve()
    base = path.parent
    study = _object(json.loads(path.read_text()), "study manifest")
    if study.get("schema_version") != 1:
        raise ValueError("Study manifest must use schema_version=1")
    freeze = _object(study.get("freeze"), "freeze")
    for field in ("software_commit", "protocol_revision", "frozen_at_utc"):
        _code(freeze.get(field), field)
    if len(freeze["software_commit"]) != 40 or any(
        c not in "0123456789abcdef" for c in freeze["software_commit"]
    ):
        raise ValueError("software_commit must be a full lowercase Git SHA")
    models = _object(freeze.get("model_sha256"), "model_sha256")
    if not models:
        raise ValueError("Freeze must identify at least one model")
    for name, digest in models.items():
        _code(name, "model name")
        _sha256(digest, f"model {name} SHA-256")
    clips = _list(study.get("clips"), "clips")
    if len(clips) < 3:
        raise ValueError("Study requires at least three clips")
    codes, matches, output = set(), set(), []
    pooled = {kind: {key: 0 for key in ("tp", "fp", "fn")} for kind in KINDS}
    pooled_coverage = {
        kind: {"labelled_seconds": 0, "fully_annotated_clips": 0, "outside_coverage_predictions": 0}
        for kind in KINDS
    }
    all_annotation, all_review = [], []
    trace_passed = trace_total = 0
    for index, raw in enumerate(clips):
        clip = _object(raw, f"clips[{index}]")
        code = _code(clip.get("code"), "clip code")
        match_code = _code(clip.get("original_match_code"), "original match code")
        if code in codes or match_code in matches:
            raise ValueError("Clip and original-match codes must be unique")
        codes.add(code)
        matches.add(match_code)
        duration = _number(clip.get("duration_seconds"), "duration_seconds", positive=True)
        if not 300 <= duration <= 600:
            raise ValueError("Each study clip must be 5–10 minutes")
        setting = _object(clip.get("setting"), "setting")
        if any(setting.get(key) is not True for key in ("fixed_camera", "full_court", "singles")):
            raise ValueError("Study clips must be fixed-camera, full-court singles")
        rights = _object(clip.get("rights"), "rights")
        if rights.get("analysis_permission") is not True:
            raise ValueError("Analysis permission is required")
        if type(rights.get("figure_permission")) is not bool:
            raise ValueError("Figure permission must be explicitly recorded")
        _sha256(clip.get("source_sha256"), "source_sha256")
        candidate_path = _file(base, clip.get("candidates"), "candidates")
        expected_candidate_sha = _sha256(clip.get("candidate_sha256"), "candidate_sha256")
        if hashlib.sha256(candidate_path.read_bytes()).hexdigest() != expected_candidate_sha:
            raise ValueError("Frozen candidate file SHA-256 does not match the manifest")
        adjudicated_path = _file(base, clip.get("adjudicated_events"), "adjudicated events")
        reviewers = [_reviewer(base, item) for item in _list(clip.get("reviewers"), "reviewers")]
        if len(reviewers) != 2 or reviewers[0]["code"] == reviewers[1]["code"]:
            raise ValueError("Exactly two distinct independent reviewers are required")
        adjudicator = _code(clip.get("adjudicator_code"), "adjudicator code")
        if adjudicator in {r["code"] for r in reviewers}:
            raise ValueError("Adjudicator must be distinct from reviewers")
        _file(base, clip.get("adjudication_log"), "adjudication log")
        candidate_events = _events(candidate_path)
        if any(sum(r["decisions"].values()) != len(candidate_events) for r in reviewers):
            raise ValueError("Each reviewer must decide every candidate")
        event_result = evaluate_events(candidate_path, adjudicated_path, duration)["events"]
        independent_result = evaluate_events(
            reviewers[0]["independent_path"], reviewers[1]["independent_path"], duration
        )["events"]
        reverse_independent = evaluate_events(
            reviewers[1]["independent_path"], reviewers[0]["independent_path"], duration
        )["events"]
        adjudicated_events = _events(adjudicated_path)
        agreement = {}
        event_summary = {}
        for kind in KINDS:
            result = event_result[kind]
            counts = {key: result[key] for key in ("tp", "fp", "fn")}
            for key in counts:
                pooled[kind][key] += counts[key]
            pooled_coverage[kind]["labelled_seconds"] += result["labelled_seconds"]
            pooled_coverage[kind]["fully_annotated_clips"] += int(result["fully_annotated"])
            pooled_coverage[kind]["outside_coverage_predictions"] += result[
                "outside_coverage_predictions"
            ]
            event_summary[kind] = {
                **counts,
                "precision": result["precision"],
                "recall": result["recall"],
                "labelled_seconds": result["labelled_seconds"],
                "fully_annotated": result["fully_annotated"],
                "outside_coverage_predictions": result["outside_coverage_predictions"],
            }
            if kind != "rally":
                event_summary[kind]["matched_start_error_seconds"] = (
                    _median_range(_matched_times(candidate_events, adjudicated_events, kind))
                    if result["fully_annotated"]
                    else None
                )
            pair = independent_result[kind]
            both_complete = pair["fully_annotated"] and reverse_independent[kind]["fully_annotated"]
            agreement[kind] = (
                {
                    "matched": pair["tp"],
                    "reviewer1_only": pair["fp"],
                    "reviewer2_only": pair["fn"],
                }
                if both_complete
                else None
            )
        trace = _trace(base, clip.get("trace_reports"))
        trace_passed += trace["passed"]
        trace_total += trace["non_null_metrics"]
        for reviewer in reviewers:
            all_annotation.append(reviewer["annotation_minutes"])
            all_review.append(reviewer["review_minutes"])
        output.append(
            {
                "code": code,
                "duration_seconds": duration,
                "events": event_summary,
                "reviewer_positive_event_agreement": agreement,
                "reviewer_minutes": [
                    {
                        key: reviewer[key]
                        for key in (
                            "code",
                            "annotation_minutes",
                            "review_minutes",
                            "paused_minutes",
                            "decisions",
                        )
                    }
                    for reviewer in reviewers
                ],
                "traceability": trace,
            }
        )

    def counts_with_rates(values):
        tp, fp, fn = (values[key] for key in ("tp", "fp", "fn"))
        return {
            **values,
            "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None,
        }

    return {
        "scope": "descriptive study summary from supplied private records; source rights, independence, and human audit flags require external verification",
        "freeze": freeze,
        "clips": output,
        "pooled": {
            "events": {
                kind: {
                    **counts_with_rates(pooled[kind]),
                    **pooled_coverage[kind],
                    "clips": len(clips),
                }
                for kind in KINDS
            },
            "annotation_minutes": _median_range(all_annotation),
            "review_minutes": _median_range(all_review),
            "traceability": {
                "passed": trace_passed,
                "non_null_metrics": trace_total,
                "proportion": trace_passed / trace_total if trace_total else None,
            },
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="Private study manifest JSON; never commit it")
    args = parser.parse_args()
    print(json.dumps(summarize(args.manifest), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
