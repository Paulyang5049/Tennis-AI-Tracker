"""Blind hit, bounce and stroke labels for a held-out broadcast, and scoring against them.

The labeller never sees automatic events: segments come only from the main-camera view
test (a court was found) and cuts, the labelling page shows raw frames without overlays,
and candidates are read only when scoring. Only segments marked complete are scored,
and a complete segment is exhaustive: a hit or bounce missing from it is a miss.

    python -m tennis_ai.heldout_labels init ANALYSIS --labels LABELS
    python -m tennis_ai.heldout_labels app LABELS
    python -m tennis_ai.heldout_labels score LABELS --output report.json

The labels folder holds ground truth only and stays local, like the footage.
"""

import argparse
import json
import math
import statistics
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tennis_ai.events import STROKES as EVENT_STROKES
from tennis_ai.package import atomic_json

DEFINITION = "broadcast-heldout-v1"
KINDS = ("hit", "bounce")
SIDES = ("near", "far")
STROKES = (*EVENT_STROKES, "unknown")
TOLERANCES = (2 / 30, 4 / 30)  # Seconds; the same ±2 and ±4 frames at 30 fps as T3.


def _records(frames_path):
    with Path(frames_path).open() as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def segments(frames_path, min_seconds=3.0):
    """Main-camera runs between cuts, at least min_seconds long. No event or ball input."""
    from tennis_ai.views import main_view_flags

    records = [
        (r["frame"], r["timestamp"], r.get("court") is not None, bool(r.get("cut")))
        for r in _records(frames_path)
    ]
    flags = main_view_flags((t, court) for _, t, court, _ in records)
    result: list[dict[str, Any]] = []
    run: list[tuple] = []

    def close():
        if run and run[-1][1] - run[0][1] >= min_seconds:
            result.append(
                {
                    "id": f"s{len(result) + 1:03d}",
                    "first_frame": run[0][0],
                    "last_frame": run[-1][0],
                    "start": round(run[0][1], 3),
                    "end": round(run[-1][1], 3),
                    "complete": False,
                }
            )

    for record, keep in zip(records, flags, strict=True):
        if not keep or (record[3] and run):
            close()
            run = []
        if keep:
            run.append(record)
    close()
    return result


def init(analysis, labels, min_seconds=3.0):
    analysis, labels = Path(analysis), Path(labels)
    summary = json.loads((analysis / "summary.json").read_text())
    if (labels / "manifest.json").exists():
        raise FileExistsError(f"{labels} already holds labels")
    labels.mkdir(parents=True, exist_ok=True)
    found = segments(analysis / "frames.jsonl", min_seconds)
    atomic_json(
        labels / "manifest.json",
        {
            "schema_version": 1,
            "definition_version": DEFINITION,
            "analysis": str(analysis.resolve()),
            "source_sha256": summary["source_sha256"],
            "fps": summary["video"]["fps"],
            "created": datetime.now(UTC).isoformat(timespec="seconds"),
            "blind": "labels are written without seeing automatic events",
            "segments": found,
        },
    )
    (labels / "labels.jsonl").touch()
    return found


def load(labels):
    labels = Path(labels)
    manifest = json.loads((labels / "manifest.json").read_text())
    rows = [json.loads(line) for line in (labels / "labels.jsonl").read_text().splitlines() if line]
    return manifest, rows


def _write_rows(labels, rows):
    path = Path(labels) / "labels.jsonl"
    pending = path.with_suffix(".pending")
    rows = sorted(rows, key=lambda r: (r["frame"], r["kind"]))
    pending.write_text("".join(json.dumps(r, allow_nan=False) + "\n" for r in rows))
    pending.replace(path)


def add_label(labels, segment, frame, timestamp, kind, side=None, stroke=None, xy=None):
    """One labelled hit or bounce. A bounce needs the ball pixel at ground contact."""
    if kind not in KINDS:
        raise ValueError("Kind must be hit or bounce")
    if side not in (None, *SIDES) or stroke not in (None, *STROKES):
        raise ValueError("Unsupported side or stroke")
    if kind == "bounce" and (xy is None or not all(math.isfinite(v) for v in xy)):
        raise ValueError("Click the ball at ground contact before saving a bounce")
    manifest, rows = load(labels)
    span = next((s for s in manifest["segments"] if s["id"] == segment), None)
    if span is None or not span["first_frame"] <= frame <= span["last_frame"]:
        raise ValueError("The frame is outside the chosen segment")
    row = {
        "id": f"{kind}-{frame}",
        "segment": segment,
        "frame": int(frame),
        "time": round(float(timestamp), 4),
        "kind": kind,
        "side": side,
        "stroke": stroke if kind == "hit" else None,
        "xy": [round(float(v), 1) for v in xy] if kind == "bounce" and xy else None,
    }
    _write_rows(labels, [r for r in rows if r["id"] != row["id"]] + [row])
    return row


def remove_label(labels, label_id):
    _, rows = load(labels)
    _write_rows(labels, [r for r in rows if r["id"] != label_id])


def set_complete(labels, segment, complete=True):
    manifest, _ = load(labels)
    for span in manifest["segments"]:
        if span["id"] == segment:
            span["complete"] = bool(complete)
    atomic_json(Path(labels) / "manifest.json", manifest)


def match_times(predicted, truth, tolerance):
    """Greedy one-to-one matching by time distance; (pred index, truth index) pairs."""
    pairs = sorted(
        (abs(p - t), i, j)
        for i, p in enumerate(predicted)
        for j, t in enumerate(truth)
        if abs(p - t) <= tolerance + 1e-9
    )
    used_p, used_t, result = set(), set(), []
    for _, i, j in pairs:
        if i not in used_p and j not in used_t:
            used_p.add(i)
            used_t.add(j)
            result.append((i, j))
    return result


def _rate(a, b):
    return round(a / b, 3) if b else None


def score(manifest, rows, events, courts, tolerance):
    """events: automatic candidate dicts; courts: frame -> court record for landing metres."""
    from tennis_ai.contact_labels import stroke_classification
    from tennis_ai.geometry import project

    done = [s for s in manifest["segments"] if s["complete"]]
    result: dict[str, Any] = {"segments": len(done)}
    for kind in KINDS:
        tp = fp = fn = 0
        metres: list[float] = []
        strokes: list[tuple[str, str]] = []
        for span in done:
            truth = [r for r in rows if r["segment"] == span["id"] and r["kind"] == kind]
            pred = [
                e
                for e in events
                if e["kind"] == kind and span["start"] - 1e-6 <= e["start"] <= span["end"] + 1e-6
            ]
            pairs = match_times([e["start"] for e in pred], [r["time"] for r in truth], tolerance)
            tp, fp, fn = tp + len(pairs), fp + len(pred) - len(pairs), fn + len(truth) - len(pairs)
            for i, j in pairs:
                if kind == "hit" and truth[j]["stroke"] not in (None, "unknown"):
                    strokes.append((truth[j]["stroke"], pred[i].get("stroke") or "unknown"))
                court = courts.get(truth[j]["frame"])
                if kind == "bounce" and court and pred[i].get("position"):
                    actual = project([truth[j]["xy"]], court["matrix"])[0].tolist()
                    metres.append(math.dist(actual, pred[i]["position"]))
        precision, recall = _rate(tp, tp + fp), _rate(tp, tp + fn)
        result[kind] = {
            "labelled": tp + fn,
            "predicted": tp + fp,
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": precision,
            "recall": recall,
            "f1": round(2 * precision * recall / (precision + recall), 3)
            if precision and recall
            else None,
        }
        if kind == "bounce":
            result[kind].update(
                {
                    "landings_scored": len(metres),
                    "median_landing_error_m": round(statistics.median(metres), 3)
                    if metres
                    else None,
                    "within_0_5_m": _rate(sum(m <= 0.5 for m in metres), len(metres)),
                }
            )
        if kind == "hit":
            result[kind]["stroke_classification"] = stroke_classification(strokes)
    return result


def report(labels, events_path=None, name=None):
    manifest, rows = load(labels)
    analysis = Path(manifest["analysis"])
    events_path = Path(events_path or analysis / "events.json")
    events = [
        e
        for e in json.loads(events_path.read_text())["events"]
        if e.get("provenance") == "automatic" and not e.get("excluded")
    ]
    courts = {r["frame"]: r["court"] for r in _records(analysis / "frames.jsonl") if r.get("court")}
    return {
        "schema_version": 1,
        "definition_version": DEFINITION,
        "source_sha256": manifest["source_sha256"],
        "predictions": name or str(events_path),
        "landing_error": "labelled ground-contact pixel and the candidate landing, both "
        "through the automatic court fit at that frame; court error is not removed",
        "results": {
            f"{round(t * 30)}f": score(manifest, rows, events, courts, t) for t in TOLERANCES
        },
    }


def create_app(labels):
    import gradio as gr

    from tennis_ai.review import preview

    manifest, _ = load(labels)
    analysis = manifest["analysis"]
    ids = [s["id"] for s in manifest["segments"]]

    def span(segment):
        return next(s for s in load(labels)[0]["segments"] if s["id"] == segment)

    def table(segment):
        _, rows = load(labels)
        return [
            [r["id"], r["kind"], r["time"], r["side"] or "", r["stroke"] or "", r["xy"] or ""]
            for r in rows
            if r["segment"] == segment
        ]

    def show(segment, frame):
        s = span(segment)
        frame = max(s["first_frame"], min(s["last_frame"], int(frame)))
        raw, _, record = preview(analysis, frame)  # The raw frame only: no overlays.
        info = f"{segment} · frame {frame} · {record['timestamp']:.3f} s"
        return raw, frame, record["timestamp"], info

    def choose(segment):
        s = span(segment)
        raw, frame, time, info = show(segment, s["first_frame"])
        slider = gr.update(minimum=s["first_frame"], maximum=s["last_frame"], value=frame)
        return raw, slider, time, info, table(segment), s["complete"], None, None

    def step(segment, frame, delta):
        return show(segment, int(frame) + delta)

    def click(event: gr.SelectData):
        return event.index[0], event.index[1]

    def save(segment, frame, time, kind, side, stroke, x, y):
        xy = [x, y] if x is not None and y is not None else None
        try:
            add_label(labels, segment, int(frame), time, kind, side or None, stroke or None, xy)
        except ValueError as error:
            raise gr.Error(str(error)) from error
        return table(segment), None, None

    def delete(segment, label_id):
        if label_id:
            remove_label(labels, label_id.strip())
        return table(segment)

    with gr.Blocks(title="Blind labels") as app:
        gr.Markdown(
            "## Blind hit and bounce labels\nLabel every hit and every bounce in a segment, "
            "then mark it complete. Bounce: step to the ground-contact frame and click the "
            "ball. Do not open automatic events for this video while labelling."
        )
        with gr.Row():
            segment = gr.Dropdown(ids, value=ids[0] if ids else None, label="Segment")
            info = gr.Markdown()
            complete = gr.Checkbox(label="Segment fully labelled (every hit and bounce)")
        image = gr.Image(type="numpy", interactive=False, label="Raw frame · click the ball")
        frame = gr.Slider(0, 1, step=1, label="Frame")
        time = gr.State()
        with gr.Row():
            buttons = {d: gr.Button(f"{d:+d}") for d in (-10, -1, 1, 10)}
        with gr.Row():
            kind = gr.Radio(list(KINDS), value="hit", label="Event")
            side = gr.Radio(["", *SIDES], value="", label="Player side")
            stroke = gr.Dropdown(["", *STROKES], value="", label="Stroke (hits)")
            x = gr.Number(label="Ball x (px)")
            y = gr.Number(label="Ball y (px)")
        save_button = gr.Button("Save label at this frame", variant="primary")
        rows = gr.Dataframe(
            headers=["id", "kind", "time", "side", "stroke", "xy"], interactive=False
        )
        with gr.Row():
            remove_id = gr.Textbox(label="Label id to delete")
            remove_button = gr.Button("Delete label")
        segment.change(choose, segment, [image, frame, time, info, rows, complete, x, y])  # type: ignore[attr-defined]
        frame.release(show, [segment, frame], [image, frame, time, info])  # type: ignore[attr-defined]
        for delta, button in buttons.items():
            button.click(  # type: ignore[attr-defined]
                lambda s, f, d=delta: step(s, f, d), [segment, frame], [image, frame, time, info]
            )
        image.select(click, outputs=[x, y])  # type: ignore[attr-defined]
        save_button.click(  # type: ignore[attr-defined]
            save, [segment, frame, time, kind, side, stroke, x, y], [rows, x, y]
        )
        remove_button.click(delete, [segment, remove_id], rows)  # type: ignore[attr-defined]
        complete.input(lambda s, c: set_complete(labels, s, c), [segment, complete])  # type: ignore[attr-defined]
        app.load(choose, segment, [image, frame, time, info, rows, complete, x, y])
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    start = commands.add_parser("init", help="Find main-camera segments for labelling")
    start.add_argument("analysis")
    start.add_argument("--labels", required=True)
    start.add_argument("--min-seconds", type=float, default=3.0)
    page = commands.add_parser("app", help="Open the local blind labelling page")
    page.add_argument("labels")
    page.add_argument("--port", type=int, default=7861)
    scoring = commands.add_parser("score", help="Score automatic events on complete segments")
    scoring.add_argument("labels")
    scoring.add_argument("--events", help="Events JSON (default: the analysis events.json)")
    scoring.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.command == "init":
        found = init(args.analysis, args.labels, args.min_seconds)
        seconds = sum(s["end"] - s["start"] for s in found)
        print(f"{len(found)} segments, {seconds / 60:.1f} min of main-camera play")
    elif args.command == "app":
        create_app(args.labels).launch(server_name="127.0.0.1", server_port=args.port)
    else:
        result = report(args.labels, args.events)
        Path(args.output).write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result["results"]["2f"], indent=2))


if __name__ == "__main__":
    main()
