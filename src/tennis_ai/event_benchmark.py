"""Score hit and bounce candidates on the public TrackNet tennis dataset, split by game.

The dataset marks 516 hit frames and 523 bounce frames over 95 broadcast clips. Inputs
are cached once (players, poses, rackets and court geometry per frame) so event
detectors can be rescored in seconds:

    python -m tennis_ai.event_benchmark scene DATASET --output scene.jsonl
    python -m tennis_ai.event_benchmark score scene.jsonl --ball truth --output report.json

Ball sources: ``truth`` uses the labelled ball (isolates the event logic), or a cached
``ball_benchmark`` frames file (detector plus selector). The landing gate in the plan
(accuracy >= 0.90, median error <= 0.5 m) also needs per-clip court geometry; clips
whose court detector fails are scored in pixels only.
"""

import argparse
import json
import math
import statistics
from pathlib import Path
from typing import Any

import cv2

from tennis_ai.ball_benchmark import FPS, IN_SAMPLE, SPLITS, clips
from tennis_ai.events import EVENT_DETECTORS, generate_candidates

DEFINITION = "events-public-v1"
KINDS = {"1": "hit", "2": "bounce"}
TOLERANCES = (2, 4)  # Frames at 30 fps: about 67 ms and 133 ms.
CALIBRATE_EVERY = 30


def cache_scene(dataset, games, models):
    """Per-frame players, rackets and court, as the pipeline would compute them."""
    from tennis_ai.geometry import associate_rackets, attach_poses
    from tennis_ai.pipeline import select_players

    for game, folder, labels in clips(dataset, games):
        models.reset()
        court, previous = None, set[int]()
        for index, label in enumerate(labels):
            frame = cv2.imread(str(folder / label["file name"]))
            if frame is None:
                raise ValueError(f"Unreadable frame {folder / label['file name']}")
            if index % CALIBRATE_EVERY == 0 or court is None:
                court = models.court_geometry(frame) or court
            players, rackets, _balls, poses = models.infer(frame, court)
            attach_poses(players, poses)
            associate_rackets(players, rackets)
            players = select_players(players, court, 2, previous)
            previous = {p["id"] for p in players}
            yield {
                "game": game,
                "clip": folder.name,
                "frame": label["file name"],
                "court": court,
                "players": players,
                "rackets": rackets,
            }


def labelled(dataset_rows):
    """Group ball rows into clips with their labelled events."""
    grouped: dict[tuple, list] = {}
    for row in dataset_rows:
        grouped.setdefault((row["game"], row["clip"]), []).append(row)
    return grouped


def frames(ball_rows, scene_rows, ball="truth"):
    """Pipeline-shaped frame records for one clip; unobserved balls stay unobserved."""
    scenes = {row["frame"]: row for row in scene_rows}
    for index, row in enumerate(ball_rows):
        point = row["truth"] if ball == "truth" else row["selected"]
        scene = scenes.get(row["frame"], {})
        yield {
            "frame": index,
            "timestamp": index / FPS,
            "scene": 0,
            "ball": {"status": "observed" if point else "missing", "xy": point},
            "players": scene.get("players", []),
            "rackets": scene.get("rackets", []),
        }


def match(predicted, truth, tolerance):
    """Greedy one-to-one matching by frame distance; returns matched (pred, truth) pairs."""
    pairs = sorted(
        (abs(p - t), i, j)
        for i, p in enumerate(predicted)
        for j, t in enumerate(truth)
        if abs(p - t) <= tolerance
    )
    used_p, used_t, result = set(), set(), []
    for _, i, j in pairs:
        if i not in used_p and j not in used_t:
            used_p.add(i)
            used_t.add(j)
            result.append((i, j))
    return result


def clip_events(ball_rows, scene_rows, detector, ball="truth"):
    """Predicted event frames by kind, from a heuristic detector or a callable."""
    if callable(detector):
        return detector(ball_rows, scene_rows, ball)
    events = generate_candidates(frames(ball_rows, scene_rows, ball), detector)
    result: dict[str, list[int]] = {"hit": [], "bounce": []}
    for event in events:
        if event["kind"] in result:
            result[event["kind"]].append(round(event["start"] * FPS))
    return result


def _court_point(court, xy):
    from tennis_ai.geometry import project

    if not court or xy is None:
        return None
    return project([xy], court["matrix"])[0].tolist()


def score(clips_data, tolerance):
    """clips_data: list of (ball_rows, scene_rows, predicted) per clip."""
    totals: dict[str, Any] = {}
    for kind in ("hit", "bounce"):
        tp = fp = fn = 0
        pixel_errors: list[float] = []
        metre_errors: list[float] = []
        for ball_rows, scene_rows, predicted in clips_data:
            truth = [i for i, row in enumerate(ball_rows) if KINDS.get(row["status"]) == kind]
            pred = predicted[kind]
            pairs = match(pred, truth, tolerance)
            tp += len(pairs)
            fp += len(pred) - len(pairs)
            fn += len(truth) - len(pairs)
            if kind != "bounce":
                continue
            scenes = {row["frame"]: row for row in scene_rows}
            for i, j in pairs:
                actual = ball_rows[truth[j]]["truth"]
                # The landing estimate is the observed ball at the predicted frame.
                guess = ball_rows[pred[i]].get("_point")
                if actual is None or guess is None:
                    continue
                pixel_errors.append(math.dist(actual, guess))
                court = scenes.get(ball_rows[truth[j]]["frame"], {}).get("court")
                a, g = _court_point(court, actual), _court_point(court, guess)
                if a and g:
                    metre_errors.append(math.dist(a, g))
        precision = tp / (tp + fp) if tp + fp else None
        recall = tp / (tp + fn) if tp + fn else None
        totals[kind] = {
            "labelled": tp + fn,
            "predicted": tp + fp,
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": precision,
            "recall": recall,
            "f1": 2 * precision * recall / (precision + recall) if precision and recall else None,
        }
        if kind == "bounce":
            totals[kind]["median_pixel_error"] = (
                statistics.median(pixel_errors) if pixel_errors else None
            )
            totals[kind]["median_metre_error"] = (
                statistics.median(metre_errors) if metre_errors else None
            )
            totals[kind]["within_0_5_m"] = (
                sum(e <= 0.5 for e in metre_errors) / len(metre_errors) if metre_errors else None
            )
            totals[kind]["metre_scored"] = len(metre_errors)
    return totals


def evaluate(ball_rows, scene_rows, detector, ball="truth"):
    """Predicted events per clip, with the observed point used as the landing estimate."""
    by_clip = labelled(ball_rows)
    scenes = labelled(scene_rows)
    result = []
    for key, rows in by_clip.items():
        rows = [
            {**row, "_point": row["truth"] if ball == "truth" else row["selected"]} for row in rows
        ]
        predicted = clip_events(rows, scenes.get(key, []), detector, ball)
        result.append((key, rows, scenes.get(key, []), predicted))
    return result


def report(evaluated, detector_name, ball, ball_model=None):
    groups = {
        name: [e for e in evaluated if e[0][0] in members] for name, members in SPLITS.items()
    }
    return {
        "schema_version": 1,
        "definition_version": DEFINITION,
        "dataset": "TrackNet tennis (10 broadcast games), local copy, not redistributed",
        "event_detector": detector_name,
        "ball_source": ball,
        "ball_in_sample_warning": IN_SAMPLE.get(ball_model or ""),
        "splits": {name: list(members) for name, members in SPLITS.items()},
        "landing_estimate": "observed ball pixel at the predicted bounce frame",
        "results": {
            f"{tolerance}f": {
                name: score([e[1:] for e in group], tolerance)
                for name, group in groups.items()
                if group
            }
            for tolerance in TOLERANCES
        },
    }


def load_jsonl(path):
    with open(path) as stream:
        return [json.loads(line) for line in stream]


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    scene = commands.add_parser("scene", help="Cache players, rackets and court per frame")
    scene.add_argument("dataset")
    scene.add_argument("--root", default=str(Path.cwd()))
    scene.add_argument("--device", default="auto")
    scene.add_argument("--games", type=int, nargs="+", default=list(range(1, 11)))
    scene.add_argument("--output", required=True)
    scoring = commands.add_parser("score", help="Score an event detector on cached inputs")
    scoring.add_argument("scene")
    scoring.add_argument("--dataset", help="Dataset folder; needed for --ball truth")
    scoring.add_argument(
        "--ball", default="truth", help="'truth' or a ball_benchmark --frames JSONL file"
    )
    scoring.add_argument("--ball-model", help="Model behind the --ball file, for warnings")
    scoring.add_argument(
        "--event-detector", default="baseline-v1", choices=[*EVENT_DETECTORS, "learned"]
    )
    scoring.add_argument("--weights", help="Learned event model weights (event_model)")
    scoring.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.command == "scene":
        from tennis_ai.models import Models

        models = Models(args.root, args.device)
        with open(args.output, "w") as stream:
            for row in cache_scene(args.dataset, args.games, models):
                stream.write(json.dumps(row) + "\n")
                if row["frame"] == "0000.jpg":
                    print(f"game{row['game']} {row['clip']}", flush=True)
        return
    scene_rows = load_jsonl(args.scene)
    if args.ball == "truth":
        if not args.dataset:
            parser.error("--dataset is required for --ball truth")
        ball_rows = list(truth_rows(args.dataset))
    else:
        ball_rows = load_jsonl(args.ball)
    detector: Any = args.event_detector
    if detector == "learned":
        from tennis_ai.event_model import load_detector

        detector = load_detector(args.weights)
    source = "truth" if args.ball == "truth" else "selected"
    result = report(
        evaluate(ball_rows, scene_rows, detector, source),
        args.event_detector,
        "labelled ball" if source == "truth" else Path(args.ball).name,
        args.ball_model,
    )
    Path(args.output).write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result["results"]["2f"].get("test"), indent=2))


def truth_rows(dataset, games=range(1, 11)):
    for game, folder, labels in clips(dataset, games):
        for label in labels:
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
                "selected": None,
                "candidates": [],
            }


if __name__ == "__main__":
    main()
