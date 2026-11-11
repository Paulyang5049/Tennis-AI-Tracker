"""Main-camera view filter for broadcast video. A heuristic, not a validated classifier.

Broadcasts cut between the high main camera and close-ups, replays and crowd shots.
Only the main camera shows the whole court, so "the court model found a valid court"
is used as the signal. Frames outside the main view are kept as raw evidence but are
blanked for event detection, so a ball in a replay cannot become a hit or bounce.
"""

import json
from pathlib import Path

VIEW_FILTERS = ("main-view-v1",)


def main_view_flags(samples, min_main=1.0, max_gap=0.5):
    """One bool per (timestamp, has_court) sample: True where the main camera is on air."""
    samples = list(samples)
    flags = [bool(has_court) for _, has_court in samples]
    times = [float(timestamp) for timestamp, _ in samples]

    def runs():
        start = 0
        for index in range(1, len(flags) + 1):
            if index == len(flags) or flags[index] != flags[start]:
                yield start, index
                start = index

    def duration(start, end):
        return times[min(end, len(times) - 1)] - times[start]

    # A short loss of calibration inside the main view is not a camera change.
    for start, end in list(runs()):
        if not flags[start] and 0 < start and end < len(flags) and duration(start, end) <= max_gap:
            flags[start:end] = [True] * (end - start)
    # A calibrated blink is more likely a wide replay angle than a playable view.
    for start, end in list(runs()):
        if flags[start] and duration(start, end) < min_main:
            flags[start:end] = [False] * (end - start)
    return flags


def blank(frame):
    """The same frame with nothing an event detector could use, marked as a break."""
    return {
        **frame,
        "cut": True,
        "players": [],
        "rackets": [],
        "ball_candidates": [],
        "ball": {"status": "missing", "xy": None, "confidence": None},
    }


def _records(path):
    with Path(path).open() as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def event_frames(path, view_filter=None):
    """Frames for event detection, read twice when a view filter needs whole-video context."""
    if view_filter is None:
        yield from _records(path)
        return
    if view_filter not in VIEW_FILTERS:
        raise ValueError("Unsupported view filter")
    flags = main_view_flags((r["timestamp"], r.get("court") is not None) for r in _records(path))
    previous = True
    for record, keep in zip(_records(path), flags, strict=True):
        if keep:
            # Returning to the main camera starts a new continuity, like a cut.
            yield record if previous else {**record, "cut": True}
        else:
            yield blank(record)
        previous = keep


def view_summary(path, view_filter="main-view-v1"):
    if view_filter not in VIEW_FILTERS:
        raise ValueError("Unsupported view filter")
    flags = main_view_flags((r["timestamp"], r.get("court") is not None) for r in _records(path))
    segments = sum(1 for i, keep in enumerate(flags) if keep and (i == 0 or not flags[i - 1]))
    return {
        "view_filter": view_filter,
        "frames": len(flags),
        "main_view_frames": sum(flags),
        "main_view_segments": segments,
        "note": "Heuristic from court calibration; not a validated shot classifier",
    }
