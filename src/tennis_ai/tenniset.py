"""Convert TenniSet stroke labels to contact windows and score hit candidates against them.

TenniSet (Faulkner and Dick, 2017) labels each Hit and Serve as a frame interval
around the stroke, about 28 frames for a hit, rather than the contact frame. The
windows therefore cannot become instantaneous `event_annotations.json` hits
without inventing contact times. A candidate scores as a match when its frame
lies inside a window, one candidate per window. Windows keep source frame numbers,
and candidate times map back to frames through the analysis's own frame
timestamps, so no frame rate is assumed.

TenniSet's own Train/Val/Test splits are time ranges inside one match. This
project keeps every frame of a match in one split, so those ranges are recorded
for reference only. Results are development evidence on broadcast footage.
"""

import argparse
import bisect
import hashlib
import json
from pathlib import Path

from tennis_ai.events import generate_candidates

FORMAT = "tenniset-contact-windows"
LIMITATIONS = (
    "Windows span the labelled stroke, not the contact frame; contact timing is not validated.",
    "Hits between points may be unlabelled; predictions outside points are counted separately.",
    "TenniSet within-match splits are not used; assign the whole video to one split.",
    "Broadcast footage only; not evidence of phone accuracy.",
)


def stroke_for(kind, custom):
    """Map TenniSet Side/Type labels to the project's stroke names."""
    if kind == "Serve":
        return "serve"
    shot = custom.get("Type")
    if shot == "Volley":
        return "volley"
    if shot == "Smash":
        return "overhead"
    return {"Forehand": "forehand", "Backhand": "backhand"}.get(custom.get("Side"), "unknown")


def _span(event):
    start, end = int(event["start"]), int(event["end"])
    if not 0 <= start <= end:
        raise ValueError(f"Invalid TenniSet interval: {event}")
    return start, end


def convert(path):
    """Read one TenniSet annotation JSON and return a contact-window document."""
    raw = Path(path).read_bytes()
    annotation = json.loads(raw)
    classes = annotation["classes"]
    usable = classes.get("USE") or classes.get("Match")
    if not usable:
        raise ValueError("TenniSet file has no USE or Match interval to define coverage")
    windows = [
        {
            "id": f"{kind.lower()}-{event['name']}",
            "kind": kind.lower(),
            "start_frame": _span(event)[0],
            "end_frame": _span(event)[1],
            "stroke": stroke_for(kind, event.get("custom", {})),
            "player": event.get("custom", {}).get("Player") or None,
        }
        for kind in ("Hit", "Serve")
        for event in classes.get(kind, [])
    ]
    return {
        "format": FORMAT,
        "version": 1,
        "source": {
            "dataset": "TenniSet",
            "annotation": Path(path).name,
            "annotation_sha256": hashlib.sha256(raw).hexdigest(),
            "video": annotation.get("video"),
            "licence": "not verified; local research use only",
        },
        "coverage_frames": [list(_span(event)) for event in usable],
        "points_frames": [list(_span(event)) for event in classes.get("Point", [])],
        "tenniset_splits": [
            {"split": event["custom"].get("Type"), "frames": list(_span(event))}
            for event in classes.get("SPLITS", [])
        ],
        "windows": sorted(windows, key=lambda w: (w["start_frame"], w["id"])),
        "limitations": list(LIMITATIONS),
    }


def _inside(frame, spans):
    return any(start <= frame <= end for start, end in spans)


def match_windows(frames, windows):
    """Maximum one-to-one matching of candidate frames to the windows containing them.

    Taking windows in order of end frame and giving each the earliest free candidate
    inside it is optimal for points on a line. Returns (frame index, window index) pairs.
    """
    order = sorted(range(len(frames)), key=lambda i: frames[i])
    ordered = [frames[i] for i in order]
    taken = [False] * len(order)
    pairs = []
    for w in sorted(range(len(windows)), key=lambda w: windows[w]["end_frame"]):
        k = bisect.bisect_left(ordered, windows[w]["start_frame"])
        while k < len(order) and taken[k]:
            k += 1
        if k < len(order) and ordered[k] <= windows[w]["end_frame"]:
            taken[k] = True
            pairs.append((order[k], w))
    return sorted(pairs)


def candidate_frames(events, frames):
    """Source frame of each hit candidate, via the nearest analysis timestamp."""
    times = [row["timestamp"] for row in frames]
    result = []
    for event in events:
        k = bisect.bisect_left(times, event["start"])
        nearest = min(
            (i for i in (k - 1, k) if 0 <= i < len(times)),
            key=lambda i: abs(times[i] - event["start"]),
        )
        result.append(frames[nearest]["frame"])
    return result


def _rate(numerator, denominator):
    return round(numerator / denominator, 3) if denominator else None


def score(document, predicted):
    """Count hit candidate frames against windows inside the declared coverage."""
    if document.get("format") != FORMAT or document.get("version") != 1:
        raise ValueError(f"Expected {FORMAT} version 1")
    covered = [f for f in predicted if _inside(f, document["coverage_frames"])]
    windows = [
        w for w in document["windows"] if _inside(w["start_frame"], document["coverage_frames"])
    ]
    pairs = match_windows(covered, windows)
    matched = {i for i, _ in pairs}
    unmatched = [f for i, f in enumerate(covered) if i not in matched]
    tp = len(pairs)
    recall_by_kind = {}
    for kind in ("hit", "serve"):
        total = sum(w["kind"] == kind for w in windows)
        found = sum(windows[w]["kind"] == kind for _, w in pairs)
        recall_by_kind[kind] = {"windows": total, "matched": found, "recall": _rate(found, total)}
    return {
        "tp": tp,
        "fp": len(unmatched),
        "fn": len(windows) - tp,
        "precision": _rate(tp, len(covered)),
        "recall": _rate(tp, len(windows)),
        "recall_by_kind": recall_by_kind,
        "fp_outside_points": sum(not _inside(f, document["points_frames"]) for f in unmatched),
        "outside_coverage_predictions": len(predicted) - len(covered),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    converting = commands.add_parser("convert", help="Write contact windows from a TenniSet JSON")
    converting.add_argument("annotation")
    converting.add_argument("output")
    scoring = commands.add_parser("score", help="Score hit candidates from a cached analysis")
    scoring.add_argument("windows")
    scoring.add_argument("analysis", help="Analysis folder of the same full video")
    scoring.add_argument("--detectors", nargs="+", default=["baseline-v1", "contact-v2"])
    args = parser.parse_args()
    if args.command == "convert":
        document = convert(args.annotation)
        Path(args.output).write_text(json.dumps(document, indent=2) + "\n")
        print(f"Wrote {len(document['windows'])} windows to {args.output}")
        return
    document = json.loads(Path(args.windows).read_text())
    path = Path(args.analysis) / "frames.jsonl"
    frames = [json.loads(line) for line in path.open() if line.strip()]
    report = {}
    for detector in args.detectors:
        hits = [e for e in generate_candidates(frames, detector) if e["kind"] == "hit"]
        report[detector] = score(document, candidate_frames(hits, frames))
    print(json.dumps(report, indent=2))
