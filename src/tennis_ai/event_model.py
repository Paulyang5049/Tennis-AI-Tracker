"""Opt-in learned hit/bounce candidates from a ball track plus player boxes and poses.

A small per-frame classifier over a window of observed ball positions, relative to the
window's own observations, and the ball's distance to the nearest player's wrists.
Missing observations stay missing (a mask), never interpolated. Peaks become event
candidates. It is a candidate source like the heuristics, not a validated classifier:
promotion needs the plan's landing gate on held-out matches.

    python -m tennis_ai.event_model train scene.jsonl --dataset DATASET \
        --ball tracknet.frames.jsonl --ball yolo.static.frames.jsonl --output events.pt
"""

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import torch
from torch import nn

from tennis_ai.ball_benchmark import SPLITS

VERSION = "learned-events-v1"
WINDOW = 6
CLASSES = ("none", "hit", "bounce")
LABELS = {"1": 1, "2": 2}
NMS = {"hit": 8, "bounce": 5}


def _reach(xy, players):
    """Ball distance to the nearest wrist (or upper-body point), in player heights."""
    best = 3.0
    for player in players:
        x1, y1, x2, y2 = player["box"]
        height = max(1.0, y2 - y1)
        joints = [j[:2] for j in (player.get("pose") or [])[9:11] if len(j) == 3 and j[2] >= 0.3]
        for ax, ay in joints or [[(x1 + x2) / 2, y1 + 0.4 * height]]:
            best = min(best, math.hypot(xy[0] - ax, xy[1] - ay) / height)
    return best


def features(points, players):
    """One row per frame. points: list of [x, y] or None; players: list per frame."""
    count = len(points)
    reach = [_reach(p, players[i]) if p else 3.0 for i, p in enumerate(points)]
    rows = np.zeros((count, (2 * WINDOW + 1) * 4 + 3), np.float32)
    for t in range(count):
        window = range(t - WINDOW, t + WINDOW + 1)
        present = [points[k] for k in window if 0 <= k < count and points[k]]
        if len(present) < 2:
            continue
        anchor = points[t] or np.mean(present, axis=0).tolist()
        values = []
        for k in window:
            point = points[k] if 0 <= k < count else None
            if point:
                values += [1.0, (point[0] - anchor[0]) / 100, (point[1] - anchor[1]) / 100]
                values.append(reach[k] / 3)
            else:
                values += [0.0, 0.0, 0.0, 1.0]
        values += [anchor[0] / 1280, anchor[1] / 720, 1.0 if points[t] else 0.0]
        rows[t] = values
    return rows


class EventNet(nn.Module):
    def __init__(self, inputs):
        super().__init__()
        self.layers = nn.Sequential(
            nn.Linear(inputs, 96), nn.ReLU(), nn.Linear(96, 96), nn.ReLU(), nn.Linear(96, 3)
        )

    def forward(self, x):
        return self.layers(x)


def clip_inputs(ball_rows, scene_rows, ball):
    scenes = {row["frame"]: row for row in scene_rows}
    points = [row["truth"] if ball == "truth" else row["selected"] for row in ball_rows]
    players = [scenes.get(row["frame"], {}).get("players", []) for row in ball_rows]
    return features(points, players)


def peaks(probabilities, threshold, spacing):
    """Frames whose probability is above threshold and the maximum within +-spacing."""
    result: list[int] = []
    for t, value in enumerate(probabilities):
        if value < threshold:
            continue
        lo, hi = max(0, t - spacing), min(len(probabilities), t + spacing + 1)
        if value >= probabilities[lo:hi].max() and not (result and t - result[-1] <= spacing):
            result.append(t)
    return result


class LearnedDetector:
    def __init__(self, net, thresholds):
        self.net = net.eval()
        self.thresholds = thresholds

    def probabilities(self, ball_rows, scene_rows, ball):
        x = torch.from_numpy(clip_inputs(ball_rows, scene_rows, ball))
        with torch.inference_mode():
            return torch.softmax(self.net(x), dim=1).numpy()

    def __call__(self, ball_rows, scene_rows, ball):
        p = self.probabilities(ball_rows, scene_rows, ball)
        return {
            kind: peaks(p[:, index], self.thresholds[kind], NMS[kind])
            for index, kind in enumerate(CLASSES)
            if kind != "none"
        }


def load_detector(path):
    state = torch.load(path, map_location="cpu", weights_only=True)
    if state.get("version") != VERSION:
        raise ValueError("Unsupported learned event model")
    net = EventNet(state["inputs"])
    net.load_state_dict(state["weights"])
    return LearnedDetector(net, state["thresholds"])


def _targets(ball_rows):
    y = np.zeros(len(ball_rows), np.int64)
    for i, row in enumerate(ball_rows):
        label = LABELS.get(row["status"] or "")
        if label:
            # One frame either side is still the event: labels are single-frame picks.
            for k in (i - 1, i, i + 1):
                if 0 <= k < len(y) and y[k] == 0:
                    y[k] = label
            y[i] = label
    return y


def _groups(rows):
    grouped: dict[tuple, list] = {}
    for row in rows:
        grouped.setdefault((row["game"], row["clip"]), []).append(row)
    return grouped


def train(sources, scene_rows, epochs=60, seed=0):
    """sources: list of (ball_rows, ball) pairs. Fits on train games, thresholds on val."""
    from tennis_ai.event_benchmark import evaluate, score

    torch.manual_seed(seed)
    np.random.seed(seed)
    scenes = _groups(scene_rows)
    xs, ys = [], []
    for ball_rows, ball in sources:
        for key, rows in _groups(ball_rows).items():
            if key[0] in SPLITS["train"]:
                xs.append(clip_inputs(rows, scenes.get(key, []), ball))
                ys.append(_targets(rows))
    x, y = torch.from_numpy(np.concatenate(xs)), torch.from_numpy(np.concatenate(ys))
    counts = torch.bincount(y, minlength=3).float()
    net = EventNet(x.shape[1])
    loss_fn = nn.CrossEntropyLoss(weight=(counts.sum() / (3 * counts.clamp(min=1))).sqrt())
    optimiser = torch.optim.AdamW(net.parameters(), lr=2e-3, weight_decay=1e-4)
    for _ in range(epochs):
        order = torch.randperm(len(x))
        for start in range(0, len(x), 512):
            batch = order[start : start + 512]
            optimiser.zero_grad()
            loss_fn(net(x[batch]), y[batch]).backward()
            optimiser.step()
    detector = LearnedDetector(net, {"hit": 0.5, "bounce": 0.5})
    thresholds: dict[str, Any] = {}
    for kind in ("hit", "bounce"):
        best = (-1.0, 0.5)
        for threshold in np.arange(0.2, 0.95, 0.05):
            detector.thresholds = {**detector.thresholds, kind: float(threshold)}
            f1s = []
            for ball_rows, ball in sources:
                val = [r for r in ball_rows if r["game"] in SPLITS["val"]]
                evaluated = evaluate(val, scene_rows, detector, ball)
                f1s.append(score([e[1:] for e in evaluated], 2)[kind]["f1"] or 0.0)
            if np.mean(f1s) > best[0]:
                best = (float(np.mean(f1s)), float(threshold))
        thresholds[kind] = round(best[1], 2)
        detector.thresholds[kind] = thresholds[kind]
    return net, thresholds


def save_model(path, net, thresholds, ball_sources=()):
    torch.save(
        {
            "version": VERSION,
            "inputs": net.layers[0].in_features,
            "weights": net.state_dict(),
            "thresholds": thresholds,
            "trained_on_games": list(SPLITS["train"]),
            "thresholds_from_games": list(SPLITS["val"]),
            "ball_sources": list(ball_sources),
        },
        path,
    )


def main():
    from tennis_ai.event_benchmark import load_jsonl, truth_rows

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    fit = commands.add_parser("train")
    fit.add_argument("scene")
    fit.add_argument("--dataset", required=True)
    fit.add_argument("--ball", action="append", default=[], help="ball_benchmark frames JSONL")
    fit.add_argument("--epochs", type=int, default=60)
    fit.add_argument("--output", required=True)
    args = parser.parse_args()
    scene_rows = load_jsonl(args.scene)
    sources = [(list(truth_rows(args.dataset)), "truth")]
    sources += [(load_jsonl(path), "selected") for path in args.ball]
    net, thresholds = train(sources, scene_rows, args.epochs)
    save_model(args.output, net, thresholds, ["labelled ball", *(Path(p).name for p in args.ball)])
    print(json.dumps(thresholds))


if __name__ == "__main__":
    main()


STEP = 1 / 30  # The model's window is defined at 30 frames per second.


def _segments(frames):
    """Runs of frames within one scene and without a cut, in order."""
    run: list[dict] = []
    for frame in frames:
        if run and (frame.get("cut") or frame.get("scene", 0) != run[-1].get("scene", 0)):
            yield run
            run = []
        run.append(frame)
    if run:
        yield run


def _resample(run):
    """Nearest pipeline record for every 1/30 s step; a step without one stays empty."""
    times = [float(f["timestamp"]) for f in run]
    result, index, t = [], 0, times[0]
    while t <= times[-1] + 1e-9:
        while index + 1 < len(times) and abs(times[index + 1] - t) <= abs(times[index] - t):
            index += 1
        result.append(run[index] if abs(times[index] - t) <= STEP / 2 + 1e-6 else None)
        t += STEP
    return result


def _scaled(player, scale):
    out = {**player, "box": [v * scale for v in player["box"]]}
    if player.get("pose"):
        out["pose"] = [[x * scale, y * scale, c] for x, y, c in player["pose"]]
    return out


def stream_events(frames, weights, width=1280, rally_gap=2.0):
    """Learned hit/bounce candidates (and rallies of two or more hits) for pipeline frames.

    Frames are resampled to 30 fps and scaled to 1280 px wide, the training geometry.
    A hit names the player whose wrist is nearest the ball at that step, if any.
    """
    from tennis_ai.events import new_event

    detector = load_detector(weights)
    scale = 1280 / width
    events = []
    for run in _segments(frames):
        steps = _resample(run)
        if len(steps) < 3:
            continue
        points = [
            [v * scale for v in s["ball"]["xy"]]
            if s and s.get("ball", {}).get("status") == "observed" and s["ball"].get("xy")
            else None
            for s in steps
        ]
        players = [[_scaled(p, scale) for p in (s or {}).get("players", [])[:4]] for s in steps]
        x = torch.from_numpy(features(points, players))
        with torch.inference_mode():
            p = torch.softmax(detector.net(x), dim=1).numpy()
        for index, kind in ((1, "hit"), (2, "bounce")):
            for t in peaks(p[:, index], detector.thresholds[kind], NMS[kind]):
                record = steps[t] or next(s for s in steps[t:] + steps[::-1] if s)
                player_id = None
                if kind == "hit" and points[t]:
                    near = [
                        (_reach(points[t], [pl]), pl["id"])
                        for pl in players[t]
                        if _reach(points[t], [pl]) < 1.0
                    ]
                    player_id = min(near)[1] if near else None
                events.append(
                    new_event(
                        kind,
                        float(record["timestamp"]),
                        int(record.get("scene", 0)),
                        int(record["frame"]),
                        # A softmax score is not a calibrated probability; keep it out.
                        player_id=player_id,
                    )
                )
    hits = sorted((e for e in events if e["kind"] == "hit"), key=lambda e: e["start"])
    rally: list[dict] = []
    for hit in [*hits, None]:
        if rally and (
            hit is None
            or hit["scene"] != rally[-1]["scene"]
            or hit["start"] - rally[-1]["start"] > rally_gap
        ):
            if len(rally) >= 2:
                first = rally[0]
                events.append(
                    new_event(
                        "rally",
                        max(0.0, first["start"] - 0.5),
                        first["scene"],
                        int(first["id"].rsplit("-", 1)[1]),
                        end=rally[-1]["start"],
                    )
                )
            rally = []
        if hit is not None:
            rally.append(hit)
    return sorted(events, key=lambda e: (e["start"], e["kind"]))
