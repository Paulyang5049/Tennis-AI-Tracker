"""Evaluate exported predictions against explicitly annotated held-out frames."""

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

from tennis_ai.geometry import iou
from tennis_ai.training import detection_counts


def evaluate(predictions, ground_truth, tolerance_px=6):
    """GT JSONL: frame, category, and optional ball/players/rackets/court fields.

    Omitted fields are unlabelled (not negatives). Ball null is an annotated absence.
    Player entries have id and box; racket entries are boxes; court is 14 xy/null points.
    """
    truth = {
        row["frame"]: row for row in map(json.loads, Path(ground_truth).read_text().splitlines())
    }
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
    with Path(predictions).open() as stream:
        for line in stream:
            pred = json.loads(line)
            gt = truth.get(pred["frame"])
            if gt is None:
                continue
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
                        m["court_errors"].append(
                            float(np.linalg.norm(np.array(predicted) - actual))
                        )
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
