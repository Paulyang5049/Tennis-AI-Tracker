"""Score ball detectors on the public TrackNet tennis dataset, split by game.

The dataset (10 broadcast games, 1280 x 720 frames with one ball point per frame)
stays local and is never committed. Whole games go to one split, so a threshold
fitted on train/val games is never scored on frames from the same match.

Caveat recorded in every report: the published TrackNet weights were trained on a
random frame split over all ten games, so their scores here are in-sample.

    python -m tennis_ai.ball_benchmark DATASET --model yolo-coco --output report.json
"""

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any

import cv2

from tennis_ai.tracking import TRACKERS, create_ball_tracker

DEFINITION = "ball-public-v1"
SPLITS = {"train": (1, 2, 3, 4, 5, 6), "val": (7, 8), "test": (9, 10)}
FPS = 30.0
TOLERANCES = (5, 10)  # Pixels at 1280 x 720; 5 px is the TrackNet paper's criterion.
IN_SAMPLE = {"tracknet-v2": "weights were trained on frames from all ten games"}


def clips(dataset, games):
    for game in games:
        folders = (Path(dataset) / f"game{game}").glob("Clip*")
        for folder in sorted(folders, key=lambda p: int(p.name[4:])):
            with (folder / "Label.csv").open(newline="") as stream:
                yield game, folder, list(csv.DictReader(stream))


def predict(dataset, games, detect, reset=lambda: None, tracker="baseline-v1"):
    """One row per labelled frame: truth, detector candidates and the tracker's pick.

    The pick uses a ball tracker without court geometry, so this measures detector
    plus temporal selection, not the full pipeline.
    """
    for game, folder, labels in clips(dataset, games):
        reset()
        selector = create_ball_tracker(tracker)
        for index, label in enumerate(labels):
            frame = cv2.imread(str(folder / label["file name"]))
            if frame is None:
                raise ValueError(f"Unreadable frame {folder / label['file name']}")
            candidates = detect(frame)
            ball = selector.update(candidates, index / FPS, frame.shape, None)
            scale = 1280 / frame.shape[1]
            visibility = int(label["visibility"])
            yield {
                "game": game,
                "clip": folder.name,
                "frame": label["file name"],
                "visibility": visibility,
                "status": label["status"] or None,
                "truth": [float(label["x-coordinate"]), float(label["y-coordinate"])]
                if visibility
                else None,
                "selected": [v * scale for v in ball["xy"]] if ball["xy"] else None,
                "candidates": [
                    [
                        (c["box"][0] + c["box"][2]) / 2 * scale,
                        (c["box"][1] + c["box"][3]) / 2 * scale,
                        c["confidence"],
                    ]
                    for c in candidates
                ],
            }


def replay(rows, tracker):
    """Re-run only the selector over cached candidates; seconds instead of a model pass."""
    selector: Any = None
    clip, index = None, 0
    for row in rows:
        if (row["game"], row["clip"]) != clip:
            selector, clip, index = create_ball_tracker(tracker), (row["game"], row["clip"]), 0
        candidates = [{"box": [x, y, x, y], "confidence": c} for x, y, c in row["candidates"]]
        ball = selector.update(candidates, index / FPS, (720, 1280), None)
        index += 1
        yield {**row, "selected": ball["xy"]}


def score(rows, tolerance):
    """Counts follow `evaluate.py`: a wrong position is both a false positive and a miss."""
    tp = fp = fn = reachable = frames = 0
    by_visibility: dict[str, list[int]] = {}
    for row in rows:
        frames += 1
        truth, selected = row["truth"], row["selected"]
        hit = bool(truth and selected and math.dist(truth, selected) <= tolerance)
        tp += hit
        fp += selected is not None and not hit
        if truth:
            fn += not hit
            seen = by_visibility.setdefault(str(row["visibility"]), [0, 0])
            seen[0] += hit
            seen[1] += 1
            reachable += any(math.dist(truth, c[:2]) <= tolerance for c in row["candidates"])
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    return {
        "frames": frames,
        "ball_frames": tp + fn,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": 2 * precision * recall / (precision + recall) if precision and recall else None,
        # Upper bound for any selector: the right point was among the candidates.
        "candidate_recall": reachable / (tp + fn) if tp + fn else None,
        "recall_by_visibility": {
            key: {"hit": hit, "total": total, "recall": hit / total}
            for key, (hit, total) in sorted(by_visibility.items())
        },
    }


def report(rows, model, weights_sha256=None, tracker="baseline-v1"):
    rows = list(rows)
    games = sorted({row["game"] for row in rows})
    groups = {name: [r for r in rows if r["game"] in members] for name, members in SPLITS.items()}
    groups.update({f"game{game}": [r for r in rows if r["game"] == game] for game in games})
    return {
        "schema_version": 1,
        "definition_version": DEFINITION,
        "dataset": "TrackNet tennis (10 broadcast games), local copy, not redistributed",
        "model": model,
        "weights_sha256": weights_sha256,
        "in_sample_warning": IN_SAMPLE.get(model),
        "selector": f"{tracker} without court geometry",
        "splits": {name: list(members) for name, members in SPLITS.items()},
        "results": {
            f"{tolerance}px": {
                name: score(group, tolerance) for name, group in groups.items() if group
            }
            for tolerance in TOLERANCES
        },
    }


def main():
    from tennis_ai.artifacts import sha256, ultralytics_path
    from tennis_ai.models import BALL_MODELS, TrackNetBall, choose_device

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("dataset", nargs="?", help="Folder holding game1 ... game10")
    parser.add_argument("--replay", help="Rescore cached --frames rows with another ball tracker")
    parser.add_argument("--ball-tracker", choices=TRACKERS, default="baseline-v1")
    parser.add_argument("--root", default=str(Path.cwd()), help="Project assets folder")
    parser.add_argument("--model", choices=BALL_MODELS, default="yolo-coco")
    parser.add_argument("--ball-bundle", help="Fine-tuned single-class ball bundle (YOLO)")
    parser.add_argument("--device", default="auto")
    parser.add_argument("--games", type=int, nargs="+", default=list(range(1, 11)))
    parser.add_argument("--frames", help="Also keep per-frame rows (JSONL) for later rescoring")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    models = Path(args.root) / "models"
    weights = models / ("tracknet_ball.pt" if args.model == "tracknet-v2" else "yolo26s.pt")
    name = args.model
    if args.ball_bundle:
        from tennis_ai.artifacts import validate_bundle

        if args.model != "yolo-coco":
            parser.error("--ball-bundle replaces the yolo-coco detector only")
        weights, _ = validate_bundle(args.ball_bundle, "ball")
        name = f"bundle:{Path(args.ball_bundle).name}"
    if args.replay:
        with open(args.replay) as cached:
            rows = list(replay(map(json.loads, cached), args.ball_tracker))
        if args.frames:
            with open(args.frames, "w") as replayed:
                replayed.writelines(json.dumps(row) + "\n" for row in rows)
        result = report(rows, name, sha256(weights), args.ball_tracker)
        Path(args.output).write_text(json.dumps(result, indent=2) + "\n")
        return
    if not args.dataset:
        parser.error("dataset is required unless --replay is given")
    device = choose_device(args.device)
    if args.model == "tracknet-v2":
        tracknet = TrackNetBall(args.root, device)
        detect, reset = tracknet.detect, tracknet.reset
    else:
        from ultralytics import YOLO

        yolo: Any = YOLO(ultralytics_path(weights))

        # Same call as the pipeline's detector pass: COCO sports ball, or the bundle's class.
        classes = None if args.ball_bundle else [32]

        def detect(frame):
            boxes = yolo.predict(
                frame, device=device, verbose=False, classes=classes, conf=0.1, imgsz=1280
            )
            return [
                {"box": row[:4].tolist(), "confidence": float(row[4])}
                for row in boxes[0].boxes.data.cpu().numpy()
            ]

        def reset():
            return None

    rows = []
    stream = open(args.frames, "w") if args.frames else None
    for row in predict(args.dataset, args.games, detect, reset, args.ball_tracker):
        rows.append(row)
        if stream:
            stream.write(json.dumps(row) + "\n")
        if row["frame"] == "0000.jpg":
            print(f"game{row['game']} {row['clip']}", flush=True)
    if stream:
        stream.close()
    result = report(rows, name, sha256(weights), args.ball_tracker)
    Path(args.output).write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result["results"]["5px"].get("test"), indent=2))


if __name__ == "__main__":
    main()
