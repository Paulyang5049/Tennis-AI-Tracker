"""Leakage-aware multi-video evaluation; missing coverage never passes a gate."""

import json
import math
import sqlite3
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

from tennis_ai.events import KINDS, STROKES, new_event
from tennis_ai.geometry import iou
from tennis_ai.package import relative_asset
from tennis_ai.training import detection_counts

PHONE_CATEGORIES = ("phone-singles", "phone-doubles")
REQUIRED_CONDITIONS = {"occlusion", "end_change", "different_lighting", "far_ball"}


def _number(value, name, minimum=0, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be finite numeric data")
    if value < minimum or (positive and value == minimum):
        raise ValueError(f"Invalid {name}")
    return value


def load_manifest(path):
    """Validate files and original-match disjointness before computing any metric."""
    path = Path(path).resolve()
    document = json.loads(path.read_text())
    if document.get("schema_version") != 1 or not isinstance(document.get("clips"), list):
        raise ValueError("Expected benchmark manifest schema_version=1 and clips list")
    ids, sources = set(), set()
    match_splits: dict[str, str] = {}
    clips = []
    for raw in document["clips"]:
        row = dict(raw)
        for key in ("clip_id", "match_id", "category"):
            if not isinstance(row.get(key), str) or not row[key].strip():
                raise ValueError(f"Each clip requires {key}")
        if row["category"] in ("phone_singles", "phone_doubles"):
            row["category"] = row["category"].replace("_", "-")
        if row.get("split") not in ("train", "val", "test"):
            raise ValueError("Split must be train, val or test")
        if row["clip_id"] in ids:
            raise ValueError("Duplicate clip_id")
        ids.add(row["clip_id"])
        previous = match_splits.setdefault(row["match_id"], row["split"])
        if previous != row["split"]:
            raise ValueError(f"Original match {row['match_id']} leaks across splits")
        for key in ("source", "annotations", "predictions"):
            if not isinstance(row.get(key), str) or not row[key]:
                raise ValueError(f"Each clip requires {key} path")
        for key in (
            "source",
            "annotations",
            "predictions",
            "event_annotations",
            "event_predictions",
        ):
            if row.get(key) is not None:
                target = relative_asset(path.parent, row[key])
                if not target.is_file():
                    raise ValueError(f"Missing {key}: {row[key]}")
                row[key] = target
        if row["source"] in sources:
            raise ValueError(
                "Duplicate clip source path; export distinct clips with shared match_id"
            )
        sources.add(row["source"])
        for key in ("width", "height", "duration"):
            _number(row.get(key), key, positive=True)
        conditions = row.get("conditions", [])
        if not isinstance(conditions, list) or any(not isinstance(c, str) for c in conditions):
            raise ValueError("conditions must be a list of names")
        clips.append(row)
    return {**document, "clips": clips}


def _index_jsonl(connection, table, path):
    connection.execute(f"CREATE TABLE {table} (frame INTEGER PRIMARY KEY, body TEXT)")
    with Path(path).open() as stream:
        for line in stream:
            if not line.strip():
                continue
            row = json.loads(line)
            frame = row.get("frame")
            if isinstance(frame, bool) or not isinstance(frame, int) or frame < 0:
                raise ValueError("Frame ids must be nonnegative integers")
            try:
                connection.execute(f"INSERT INTO {table} VALUES (?, ?)", (frame, line))
            except sqlite3.IntegrityError as exc:
                raise ValueError("Duplicate annotated/predicted frame") from exc
    connection.commit()


def _counts(tp=0, fp=0, fn=0):
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / (tp + fn) if tp + fn else None,
        "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None,
    }


def _merge_counts(rows):
    return _counts(*(sum(row[key] for row in rows) for key in ("tp", "fp", "fn")))


def evaluate_frames(predictions, annotations, height=1080):
    """Use the existing evaluator, filling missing rows so omitted predictions are FN.

    Only explicitly labelled frames count; ball:null is a negative, omission is
    unlabelled. Coordinates stay in oriented analysis pixels. The six-pixel
    tolerance is scaled from 1080-pixel image height.
    """
    tolerance = 6 * _number(height, "height", positive=True) / 1080
    groups: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "tp": 0,
            "fp": 0,
            "fn": 0,
            "positive_frames": 0,
            "negative_frames": 0,
            "labelled_frames": 0,
        }
    )
    missing_rows = 0
    # The legacy evaluator skips GT frames absent from predictions. Canonical rows
    # explicitly represent these as missing detections and preserve other metrics.
    with tempfile.TemporaryDirectory(prefix="tennis-benchmark-") as temporary:
        connection = sqlite3.connect(str(Path(temporary) / "frames.sqlite"))
        connection.execute("PRAGMA cache_size = -2048")
        connection.execute("PRAGMA temp_store = FILE")
        _index_jsonl(connection, "predictions", predictions)
        _index_jsonl(connection, "annotations", annotations)

        def pairs():
            nonlocal missing_rows
            query = "SELECT a.frame, a.body, p.body FROM annotations a LEFT JOIN predictions p USING(frame) ORDER BY a.frame"
            for index, truth_body, prediction_body in connection.execute(query):
                gt = json.loads(truth_body)
                if prediction_body is None:
                    missing_rows += 1
                pred = {
                    "frame": index,
                    "scene": 0,
                    "ball": {"status": "missing", "xy": None},
                    "players": [],
                    "rackets": [],
                    "court": None,
                    **(json.loads(prediction_body) if prediction_body else {}),
                }
                yield pred, gt
                if "ball" not in gt:
                    continue
                category = gt.get("distance", "unspecified")
                if category not in ("near", "far", "unspecified"):
                    raise ValueError("Annotated ball distance must be near or far")
                m = groups[category]
                ball = pred["ball"]
                observed = ball.get("status") == "observed"
                present = gt["ball"] is not None
                for point in ([gt["ball"]] if present else []) + (
                    [ball.get("xy")] if observed else []
                ):
                    if not isinstance(point, list) or len(point) != 2:
                        raise ValueError("Ball annotation/prediction must be [x,y] or null")
                    for value in point:
                        _number(value, "ball coordinate", minimum=-1e9)
                hit = observed and present and math.dist(ball["xy"], gt["ball"]) <= tolerance
                m["tp"] += int(hit)
                m["fp"] += int(observed and not hit)
                m["fn"] += int(present and not hit)
                m["positive_frames"] += int(present)
                m["negative_frames"] += int(not present)
                m["labelled_frames"] += 1

        try:
            legacy = _evaluate_pairs(pairs(), tolerance_px=tolerance)
        finally:
            connection.close()
    distances = {name: {**m, **_counts(m["tp"], m["fp"], m["fn"])} for name, m in groups.items()}
    total = _merge_counts(list(distances.values()))
    for key in ("positive_frames", "negative_frames", "labelled_frames"):
        total[key] = sum(m[key] for m in distances.values())
    return {
        **total,
        "distance": distances,
        "missing_prediction_frames": missing_rows,
        "tolerance_px": tolerance,
        "legacy_metrics": legacy,
    }


def interval_iou(a, b):
    intersection = max(0, min(a["end"], b["end"]) - max(a["start"], b["start"]))
    union = max(a["end"], b["end"]) - min(a["start"], b["start"])
    return intersection / union if union else 0.0


def match_events(predictions, truth, kind, tolerance=0.1, rally_iou=0.5):
    """Maximum-cardinality one-to-one matching with deterministic nearest preference.

    Returns index pairs. Unlike greedy matching, a flexible prediction cannot
    consume the only eligible annotation for another prediction.
    """
    neighbors = {}
    for i, pred in enumerate(predictions):
        candidates = []
        for j, actual in enumerate(truth):
            score = (
                interval_iou(pred, actual)
                if kind == "rally"
                else abs(pred["start"] - actual["start"])
            )
            eligible = score >= rally_iou if kind == "rally" else score <= tolerance + 1e-9
            if eligible:
                candidates.append((-score if kind == "rally" else score, j))
        neighbors[i] = [j for _, j in sorted(candidates)]
    owners: dict[int, int] = {}

    def assign(i, seen):
        for j in neighbors[i]:
            if j in seen:
                continue
            seen.add(j)
            if j not in owners or assign(owners[j], seen):
                owners[j] = i
                return True
        return False

    for i in sorted(neighbors, key=lambda x: (len(neighbors[x]), x)):
        assign(i, set())
    return sorted((i, j) for j, i in owners.items())


def _read_events(path):
    if path is None:
        return {"events": [], "coverage": {}}
    document = json.loads(Path(path).read_text())
    if document.get("schema_version") != 2 or not isinstance(document.get("events"), list):
        raise ValueError("Expected events schema_version=2")
    events, ids = [], set()
    for index, raw in enumerate(document["events"]):
        data = dict(raw)
        kind, timestamp = data.pop("kind"), data.pop("start")
        event = new_event(kind, timestamp, **{**{"id": f"annotation-{index}"}, **data})
        if event["id"] in ids:
            raise ValueError("Duplicate event ids")
        ids.add(event["id"])
        if not event["excluded"]:
            events.append(event)
    return {**document, "events": events}


def _coverage(document, duration):
    result = {}
    raw = document.get("coverage", {})
    if not isinstance(raw, dict):
        raise ValueError("Event coverage must map kinds to annotated time intervals")
    for kind in KINDS:
        spans = raw.get(kind, [])
        if not isinstance(spans, list):
            raise ValueError("Event coverage must contain interval lists")
        merged: list[list[float]] = []
        for span in sorted(spans):
            if not isinstance(span, list) or len(span) != 2:
                raise ValueError("Coverage interval requires [start,end]")
            start, end = span
            _number(start, "coverage start")
            _number(end, "coverage end")
            if end <= start or end > duration + 1e-6:
                raise ValueError("Coverage interval lies outside clip duration")
            if merged and start <= merged[-1][1]:
                merged[-1][1] = max(end, merged[-1][1])
            else:
                merged.append([start, end])
        result[kind] = merged
    return result


def _covered(event, spans):
    return any(event["start"] >= start and event["end"] <= end for start, end in spans)


def evaluate_events(predictions, annotations, duration):
    """Annotations declare exhaustive intervals per kind, including negative time.

    Uncovered predictions are reported but not treated as false positives; a
    release gate cannot pass until every event kind covers the complete clip.
    """
    _number(duration, "duration", positive=True)
    pred_doc, gt_doc = _read_events(predictions), _read_events(annotations)
    spans = _coverage(gt_doc, duration)
    for event in pred_doc["events"] + gt_doc["events"]:
        if event["end"] > duration + 1e-6:
            raise ValueError("Event lies outside clip duration")
    report, stroke_counts, landing_errors = {}, {s: [0, 0, 0] for s in STROKES}, []
    for event in gt_doc["events"]:
        if not _covered(event, spans[event["kind"]]):
            raise ValueError("Ground-truth event lies outside declared annotation coverage")
    unknown_truth = 0
    landing_missing_positions = 0
    for kind in KINDS:
        raw_predictions = [e for e in pred_doc["events"] if e["kind"] == kind]
        predicted = [e for e in raw_predictions if _covered(e, spans[kind])]
        truth = [e for e in gt_doc["events"] if e["kind"] == kind]
        pairs = match_events(predicted, truth, kind)
        report[kind] = {
            **_counts(len(pairs), len(predicted) - len(pairs), len(truth) - len(pairs)),
            "labelled_seconds": sum(b - a for a, b in spans[kind]),
            "fully_annotated": spans[kind] == [[0, duration]],
            "outside_coverage_predictions": len(raw_predictions) - len(predicted),
            "ground_truth_events": len(truth),
        }
        if kind == "hit":
            prediction_to_truth = dict(pairs)
            truth_to_prediction = {j: i for i, j in pairs}
            for j, event in enumerate(truth):
                label = event["stroke"]
                if label not in STROKES:
                    unknown_truth += 1
                    continue
                i = truth_to_prediction.get(j)
                label_pred = predicted[i]["stroke"] if i is not None else "unknown"
                stroke_counts[label][0 if label == label_pred else 2] += 1
            for i, event in enumerate(predicted):
                label = event["stroke"]
                if label not in STROKES:
                    continue
                matched_truth = prediction_to_truth.get(i)
                # Unknown ground-truth classes are unlabelled, not classification negatives.
                if matched_truth is not None and truth[matched_truth]["stroke"] == "unknown":
                    continue
                if matched_truth is None or truth[matched_truth]["stroke"] != label:
                    stroke_counts[label][1] += 1
        if kind == "bounce":
            for i, j in pairs:
                if truth[j]["position"] is None:
                    continue
                if predicted[i]["position"] is None:
                    landing_missing_positions += 1
                else:
                    landing_errors.append(math.dist(predicted[i]["position"], truth[j]["position"]))
            report[kind]["ground_truth_positions"] = sum(e["position"] is not None for e in truth)
    per_class = {label: _counts(*counts) for label, counts in stroke_counts.items()}
    return {
        "events": report,
        "strokes": {
            "per_class": per_class,
            "macro_f1": sum(m["f1"] or 0 for m in per_class.values()) / len(STROKES),
            "unknown_ground_truth": unknown_truth,
        },
        "landing": {
            "matched_errors_m": landing_errors,
            "matched_positions": len(landing_errors),
            "matched_missing_prediction_positions": landing_missing_positions,
            "missed_bounce_events": report["bounce"]["fn"],
            "unlabelled_ground_truth_positions": report["bounce"]["ground_truth_events"]
            - report["bounce"]["ground_truth_positions"],
            "median_error_m": float(np.median(landing_errors)) if landing_errors else None,
            "p90_error_m": float(np.percentile(landing_errors, 90)) if landing_errors else None,
        },
        "inputs_present": predictions is not None and annotations is not None,
    }


def _aggregate(clips):
    frame = _merge_counts([clip["frames"] for clip in clips])
    for key in ("positive_frames", "negative_frames", "labelled_frames"):
        frame[key] = sum(clip["frames"][key] for clip in clips)
    frame["distance"] = {}
    for distance in ("near", "far"):
        values = [
            clip["frames"]["distance"][distance]
            for clip in clips
            if distance in clip["frames"]["distance"]
        ]
        frame["distance"][distance] = {
            **_merge_counts(values),
            "positive_frames": sum(value["positive_frames"] for value in values),
        }
    event_metrics = {
        kind: _merge_counts([clip["temporal"]["events"][kind] for clip in clips]) for kind in KINDS
    }
    stroke_metrics = {
        label: _merge_counts([clip["temporal"]["strokes"]["per_class"][label] for clip in clips])
        for label in STROKES
    }
    errors = [error for clip in clips for error in clip["temporal"]["landing"]["matched_errors_m"]]
    return {
        "frames": frame,
        "events": event_metrics,
        "strokes": {
            "per_class": stroke_metrics,
            "macro_f1": sum(m["f1"] or 0 for m in stroke_metrics.values()) / len(STROKES),
        },
        "landing": {
            "matched_positions": len(errors),
            "median_error_m": float(np.median(errors)) if errors else None,
            "p90_error_m": float(np.percentile(errors, 90)) if errors else None,
            **{
                key: sum(clip["temporal"]["landing"][key] for clip in clips)
                for key in (
                    "matched_missing_prediction_positions",
                    "missed_bounce_events",
                    "unlabelled_ground_truth_positions",
                )
            },
        },
    }


def _gate(category, clips, metrics, split):
    reasons = []
    matches = {clip["match_id"] for clip in clips}
    if split != "test":
        reasons.append("Release gates require the held-out test split")
    if len(matches) < 5:
        reasons.append("At least five independent held-out matches are required")
    conditions = set().union(*(set(clip["conditions"]) for clip in clips))
    missing_conditions = sorted(REQUIRED_CONDITIONS - conditions)
    if missing_conditions:
        reasons.append("Missing scene coverage: " + ", ".join(missing_conditions))
    frames = metrics["frames"]
    if not frames["positive_frames"] or not frames["negative_frames"]:
        reasons.append("Ball evaluation requires labelled positive and negative frames")
    for distance in ("near", "far"):
        if not frames["distance"][distance]["positive_frames"]:
            reasons.append(f"Missing {distance}-court positive ball annotations")

    def threshold(value, limit, label, maximum=False):
        if value is None or (value > limit if maximum else value < limit):
            reasons.append(f"{label} has not reached {limit}")

    threshold(frames["precision"], 0.90, "Ball precision")
    threshold(frames["recall"], 0.75, "Ball recall")
    for clip in clips:
        if not clip["frames"]["labelled_frames"]:
            reasons.append(f"{clip['clip_id']}: no annotated ball frames")
        if not clip["temporal"]["inputs_present"]:
            reasons.append(f"{clip['clip_id']}: missing event inputs")
        if any(not metric["fully_annotated"] for metric in clip["temporal"]["events"].values()):
            reasons.append(f"{clip['clip_id']}: incomplete event/negative-time annotation")
    for kind in ("hit", "bounce"):
        threshold(metrics["events"][kind]["f1"], 0.85, f"{kind} F1")
    for field in ("precision", "recall"):
        threshold(metrics["events"]["rally"][field], 0.90, f"Rally {field}")
    if any(m["tp"] + m["fn"] == 0 for m in metrics["strokes"]["per_class"].values()):
        reasons.append("All five stroke classes need ground-truth support")
    threshold(metrics["strokes"]["macro_f1"], 0.80, "Stroke macro-F1")
    landing = metrics["landing"]
    threshold(landing["median_error_m"], 0.5, "Median landing error (m)", maximum=True)
    threshold(landing["p90_error_m"], 1.0, "P90 landing error (m)", maximum=True)
    if (
        landing["matched_missing_prediction_positions"]
        or landing["unlabelled_ground_truth_positions"]
    ):
        reasons.append("Landing positions are incomplete; matched-pair error alone is insufficient")
    return {
        "category": category,
        "passed": not reasons,
        "independent_matches": len(matches),
        "clips": len(clips),
        "missing_conditions": missing_conditions,
        "reasons": reasons,
    }


def evaluate_manifest(path, split="test"):
    manifest = load_manifest(path)
    if split not in ("train", "val", "test"):
        raise ValueError("Split must be train, val or test")
    clips = []
    for row in manifest["clips"]:
        if row["split"] != split:
            continue
        clips.append(
            {
                "clip_id": row["clip_id"],
                "match_id": row["match_id"],
                "category": row["category"],
                "conditions": row.get("conditions", []),
                "frames": evaluate_frames(row["predictions"], row["annotations"], row["height"]),
                "temporal": evaluate_events(
                    row.get("event_predictions"), row.get("event_annotations"), row["duration"]
                ),
            }
        )
    categories = sorted({clip["category"] for clip in clips} | set(PHONE_CATEGORIES))
    grouped = {
        category: _aggregate([clip for clip in clips if clip["category"] == category])
        for category in categories
    }
    gates = {
        category: _gate(
            category,
            [clip for clip in clips if clip["category"] == category],
            grouped[category],
            split,
        )
        for category in PHONE_CATEGORIES
    }
    return {
        "schema_version": 1,
        "split": split,
        "clips": clips,
        "categories": grouped,
        "phone_quality_gates": gates,
        "phone_quality_passed": all(gate["passed"] for gate in gates.values()),
        "release_ready": False,
        "remaining_release_checks": [
            "iPhone 15 Pro runtime/memory/thermal and interruption tests",
            "Core ML conversion precision/recall parity",
            "Code/model/data distribution verification",
        ],
        "notes": [
            "Unlabelled frames/time are not negatives.",
            "Public broadcast results do not validate phone singles or doubles.",
            "Quality gates do not certify runtime, conversion or distribution readiness.",
        ],
    }


def _evaluate_pairs(pairs, tolerance_px):
    """Legacy auxiliary metrics over disk-joined rows without loading frame histories."""
    metrics: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "frames": 0,
            "ball_tp": 0,
            "ball_fp": 0,
            "ball_fn": 0,
            "ball_labelled": 0,
            "racket_tp": 0,
            "racket_fn": 0,
            "racket_labelled": 0,
            "player_id_switches": 0,
            "player_labelled": 0,
            "court_errors": [],
        }
    )
    previous: dict[tuple, int] = {}
    for pred, gt in pairs:
        category = gt.get("category", "unspecified")
        m = metrics[category]
        m["frames"] += 1
        if "ball" in gt:
            m["ball_labelled"] += 1
            observed = pred["ball"]["status"] == "observed"
            present = gt["ball"] is not None
            hit = (
                observed
                and present
                and np.linalg.norm(np.array(pred["ball"]["xy"]) - gt["ball"]) <= tolerance_px
            )
            m["ball_tp"] += int(hit)
            m["ball_fp"] += int(observed and not hit)
            m["ball_fn"] += int(present and not hit)
        if "rackets" in gt:
            m["racket_labelled"] += 1
            tp, _, fn = detection_counts([r["box"] for r in pred["rackets"]], gt["rackets"])
            m["racket_tp"] += tp
            m["racket_fn"] += fn
        if "players" in gt:
            m["player_labelled"] += 1
            pairs = sorted(
                [
                    (iou(p["box"], g["box"]), i, j)
                    for i, p in enumerate(pred["players"])
                    for j, g in enumerate(gt["players"])
                ],
                reverse=True,
            )
            used_p, used_g = set(), set()
            for score, i, j in pairs:
                if score < 0.5 or i in used_p or j in used_g:
                    continue
                used_p.add(i)
                used_g.add(j)
                identity = (category, pred["scene"], str(gt["players"][j]["id"]))
                current = pred["players"][i]["id"]
                if identity in previous and previous[identity] != current:
                    m["player_id_switches"] += 1
                previous[identity] = current
        if "court" in gt and pred.get("court"):
            for predicted, actual in zip(pred["court"]["points"], gt["court"]):
                if actual is not None:
                    m["court_errors"].append(float(np.linalg.norm(np.array(predicted) - actual)))
    report = {}
    for category, m in metrics.items():
        report[category] = {
            "annotated_frames": m["frames"],
            "ball_precision": m["ball_tp"] / max(1, m["ball_tp"] + m["ball_fp"])
            if m["ball_labelled"]
            else None,
            "ball_recall": m["ball_tp"] / max(1, m["ball_tp"] + m["ball_fn"])
            if m["ball_labelled"]
            else None,
            "racket_recall": m["racket_tp"] / max(1, m["racket_tp"] + m["racket_fn"])
            if m["racket_labelled"]
            else None,
            "player_id_switches": m["player_id_switches"] if m["player_labelled"] else None,
            "court_median_error_px": float(np.median(m["court_errors"]))
            if m["court_errors"]
            else None,
            "ball_tolerance_px": tolerance_px,
        }
    return report
