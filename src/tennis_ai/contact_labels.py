"""Score hit and spin candidates against a player's hand-labelled contact sheet.

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
from tennis_ai.events import SPINS, annotate_spin, generate_candidates, new_event

COLUMNS = ("clip", "time_s", "side", "spin", "note")


def write_template(path, clips):
    with Path(path).open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(COLUMNS)
        for clip in clips:
            writer.writerow([clip, "", "", "", "one row per contact; delete this row"])


def read_labels(path):
    labels = defaultdict(list)
    with Path(path).open(newline="") as stream:
        for row in csv.DictReader(stream):
            if not (row.get("time_s") or "").strip():
                continue
            spin = (row.get("spin") or "unknown").strip() or "unknown"
            if spin not in (*SPINS, "unknown"):
                raise ValueError(f"Unsupported spin label: {spin}")
            side = (row.get("side") or "").strip()
            if side not in ("", "near", "far"):
                raise ValueError(f"Side must be near, far or blank: {side}")
            labels[row["clip"].strip()].append(
                new_event("hit", float(row["time_s"]), spin=spin, provenance="manual")
            )
    return labels


def _rate(numerator, denominator):
    return round(numerator / denominator, 3) if denominator else None


def score(labels, clips, frames_for, detectors, spin_detector=None, tolerances=(0.1, 0.2)):
    """Return per-detector, per-tolerance hit counts and spin agreement on matched hits."""
    report = {}
    for detector in detectors:
        rows = {}
        for tolerance in tolerances:
            tp = fp = fn = 0
            spin: Counter[str] = Counter()
            for clip in clips:
                frames = frames_for(clip)
                predicted = [e for e in generate_candidates(frames, detector) if e["kind"] == "hit"]
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
                    if truth[j]["spin"] != "unknown":
                        guess = predicted[i].get("spin") or "unknown"
                        spin[
                            "abstained"
                            if guess == "unknown"
                            else "correct"
                            if guess == truth[j]["spin"]
                            else "wrong"
                        ] += 1
            rows[str(tolerance)] = {
                "tp": tp,
                "fp": fp,
                "fn": fn,
                "precision": _rate(tp, tp + fp),
                "recall": _rate(tp, tp + fn),
                "spin_on_matched_hits": dict(spin),
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
        json.dumps(score(labels, clips, frames_for, args.detectors, args.spin_detector), indent=2)
    )
