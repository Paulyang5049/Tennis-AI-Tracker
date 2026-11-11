"""Score hit, stroke and spin candidates against a player's hand-labelled contact sheet.

Labels are written without looking at candidates. Each listed clip is treated
as exhaustively labelled for hits, so a clip with no rows has no hits. These
are development checks on the labeller's own clips, not a frozen benchmark.
"""

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

from tennis_ai.benchmark import match_events
from tennis_ai.events import (
    SPINS,
    STROKES,
    annotate_spin,
    annotate_strokes,
    generate_candidates,
    new_event,
)

COLUMNS = ("clip", "time_s", "side", "stroke", "spin", "note")
# The technique pairs a player cares about first, such as a backhand slice.
TECHNIQUES = tuple(f"{stroke}/{spin}" for stroke in ("forehand", "backhand") for spin in SPINS)


def write_template(path, clips):
    with Path(path).open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(COLUMNS)
        for clip in clips:
            writer.writerow([clip, "", "", "", "", "one row per contact; delete this row"])


def read_labels(path):
    labels = defaultdict(list)
    with Path(path).open(newline="") as stream:
        for row in csv.DictReader(stream):
            if not (row.get("time_s") or "").strip():
                continue
            spin = (row.get("spin") or "unknown").strip() or "unknown"
            if spin not in (*SPINS, "unknown"):
                raise ValueError(f"Unsupported spin label: {spin}")
            stroke = (row.get("stroke") or "unknown").strip() or "unknown"
            if stroke not in (*STROKES, "unknown"):
                raise ValueError(f"Unsupported stroke label: {stroke}")
            side = (row.get("side") or "").strip()
            if side not in ("", "near", "far"):
                raise ValueError(f"Side must be near, far or blank: {side}")
            labels[row["clip"].strip()].append(
                new_event(
                    "hit", float(row["time_s"]), stroke=stroke, spin=spin, provenance="manual"
                )
            )
    return labels


def _rate(numerator, denominator):
    return round(numerator / denominator, 3) if denominator else None


def _agreement(counter, truth, guess):
    """Count one labelled attribute; an unknown label is not scored."""
    if truth != "unknown":
        counter[
            "abstained" if guess == "unknown" else "correct" if guess == truth else "wrong"
        ] += 1


GATE_CLASSES = ("serve", "forehand", "backhand")
GATE_MACRO_F1 = 0.80


def stroke_classification(pairs):
    """Per-class precision/recall/F1 and macro F1 over serve, forehand and backhand.

    pairs: (label, guess) strokes on matched hits whose label is a gate class. An
    abstention (`unknown`) or any other guess is a miss for the labelled class, so a
    detector cannot raise its score by abstaining. This is the plan's T5 measure; it
    is a promotion gate only on human labels from matches never used for tuning.
    """
    rows = {}
    pairs = [(t, g) for t, g in pairs if t in GATE_CLASSES]
    for kind in GATE_CLASSES:
        tp = sum(t == kind and g == kind for t, g in pairs)
        predicted = sum(g == kind for _, g in pairs)
        support = sum(t == kind for t, _ in pairs)
        precision = tp / predicted if predicted else None
        recall = tp / support if support else None
        f1 = (
            2 * precision * recall / (precision + recall)
            if precision and recall
            else (0.0 if support else None)
        )
        rows[kind] = {
            "support": support,
            "precision": _rate(tp, predicted),
            "recall": _rate(tp, support),
            "f1": round(f1, 3) if f1 is not None else None,
        }
    scored = [row["f1"] for row in rows.values() if row["f1"] is not None]
    macro = round(sum(scored) / len(scored), 3) if len(scored) == len(GATE_CLASSES) else None
    return {
        "classes": rows,
        "macro_f1": macro,
        "abstained": sum(g == "unknown" for _, g in pairs),
        "gate_macro_f1": GATE_MACRO_F1,
        "meets_gate_threshold": None if macro is None else macro >= GATE_MACRO_F1,
    }


def _technique(event):
    pair = f"{event['stroke']}/{event.get('spin') or 'unknown'}"
    return pair if pair in TECHNIQUES else "unknown"


def score(
    labels,
    clips,
    frames_for,
    detectors,
    spin_detector=None,
    tolerances=(0.1, 0.2),
    stroke_detector=None,
):
    """Return per-detector, per-tolerance hit counts and label agreement on matched hits.

    Technique scores the forehand/backhand by topspin/slice/flat pair; a matched hit
    counts only when both labels are present in the sheet.
    """
    report = {}
    for detector in detectors:
        rows = {}
        for tolerance in tolerances:
            tp = fp = fn = 0
            spin: Counter[str] = Counter()
            stroke: Counter[str] = Counter()
            technique: Counter[str] = Counter()
            confusion: Counter[str] = Counter()
            stroke_pairs: list[tuple[str, str]] = []
            for clip in clips:
                frames = frames_for(clip)
                predicted = [e for e in generate_candidates(frames, detector) if e["kind"] == "hit"]
                if stroke_detector:
                    predicted = annotate_strokes(predicted, frames, stroke_detector)
                if spin_detector:
                    predicted = annotate_spin(predicted, frames, spin_detector)
                truth = labels.get(clip, [])
                pairs = match_events(predicted, truth, "hit", tolerance=tolerance)
                tp, fp, fn = (
                    tp + len(pairs),
                    fp + len(predicted) - len(pairs),
                    fn + len(truth) - len(pairs),
                )
                for i, j in pairs:
                    guess, label = predicted[i], truth[j]
                    _agreement(spin, label["spin"], guess.get("spin") or "unknown")
                    _agreement(stroke, label["stroke"], guess["stroke"])
                    stroke_pairs.append((label["stroke"], guess["stroke"]))
                    _agreement(technique, _technique(label), _technique(guess))
                    if _technique(label) != "unknown":
                        confusion[f"{_technique(label)} -> {_technique(guess)}"] += 1
            rows[str(tolerance)] = {
                "tp": tp,
                "fp": fp,
                "fn": fn,
                "precision": _rate(tp, tp + fp),
                "recall": _rate(tp, tp + fn),
                "spin_on_matched_hits": dict(spin),
                "stroke_on_matched_hits": dict(stroke),
                "stroke_classification": stroke_classification(stroke_pairs),
                "technique_on_matched_hits": dict(technique),
                "technique_confusion": dict(sorted(confusion.items())),
            }
        report[detector] = rows
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    template = commands.add_parser("template", help="Write a blank labelling sheet")
    template.add_argument("output")
    template.add_argument("clips", nargs="+", help="Clip names, matching analysis folder names")
    scoring = commands.add_parser("score", help="Score candidates from cached analyses")
    scoring.add_argument("labels")
    scoring.add_argument("analyses", help="Folder holding one analysis folder per clip")
    scoring.add_argument("--clips", nargs="+", help="Default: every clip named in the sheet")
    scoring.add_argument("--detectors", nargs="+", default=["baseline-v1", "contact-v2"])
    scoring.add_argument("--spin-detector", choices=["wrist-v1"])
    scoring.add_argument("--stroke-detector", choices=["stroke-v1"])
    args = parser.parse_args()
    if args.command == "template":
        write_template(args.output, args.clips)
        print(f"Wrote {args.output}. Label every contact without looking at candidates.")
        return
    labels = read_labels(args.labels)
    with Path(args.labels).open(newline="") as stream:
        named = sorted({row["clip"].strip() for row in csv.DictReader(stream)})
    clips = args.clips or named

    def frames_for(clip):
        path = Path(args.analyses) / clip / "frames.jsonl"
        return [json.loads(line) for line in path.open() if line.strip()]

    print(
        json.dumps(
            score(
                labels,
                clips,
                frames_for,
                args.detectors,
                args.spin_detector,
                stroke_detector=args.stroke_detector,
            ),
            indent=2,
        )
    )
