"""Experimental temporal candidates and durable human event review.

Candidates deliberately do not infer stroke labels or ground-plane ball positions.
Only reviewed, non-excluded records may drive measured statistics.
"""

import json
import math
from collections import Counter, deque
from copy import deepcopy
from pathlib import Path
from typing import Any
from uuid import uuid4

from tennis_ai.package import atomic_json

STROKES = ("serve", "forehand", "backhand", "volley", "overhead")
KINDS = ("hit", "bounce", "rally")


def validate_event(event):
    """Validate the shared schema, preserving additive fields."""
    if not isinstance(event.get("id"), str) or not event["id"]:
        raise ValueError("Event id must be a nonempty string")
    if event.get("kind") not in KINDS:
        raise ValueError("Event kind must be hit, bounce or rally")
    for key in ("start", "end"):
        value = event.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("Event times must be numeric")
        if not math.isfinite(value) or value < 0:
            raise ValueError("Event times must be finite and nonnegative")
    if event["end"] < event["start"]:
        raise ValueError("Event end must not precede start")
    if event["kind"] != "rally" and event["end"] != event["start"]:
        raise ValueError("Point events must have identical start/end times")
    if event.get("stroke") not in (*STROKES, "unknown"):
        raise ValueError("Unsupported stroke")
    if not isinstance(event.get("scene"), int) or isinstance(event["scene"], bool):
        raise ValueError("Event scene must be an integer")
    player = event.get("player_id")
    if player is not None and (not isinstance(player, int) or isinstance(player, bool)):
        raise ValueError("Event player_id must be an integer or null")
    if event.get("provenance") not in ("automatic", "manual"):
        raise ValueError("Event provenance must be automatic or manual")
    for key in ("reviewed", "excluded", "favorite"):
        if not isinstance(event.get(key), bool):
            raise ValueError(f"Event {key} must be a boolean")
    confidence = event.get("confidence")
    if confidence is not None and (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not math.isfinite(confidence)
        or not 0 <= confidence <= 1
    ):
        raise ValueError("Event confidence must be null or between zero and one")
    point = event.get("position")
    if point is not None:
        if event["kind"] != "bounce" or not isinstance(point, (list, tuple)) or len(point) != 2:
            raise ValueError("Only bounce events can have a court position [x, y]")
        if any(
            isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x)
            for x in point
        ):
            raise ValueError("Court position must be finite")
    return event


def new_event(kind, timestamp, scene=0, frame=0, **updates):
    event = {
        "id": f"{kind}-{scene}-{frame}",
        "kind": kind,
        "start": float(timestamp),
        "end": float(timestamp),
        "scene": int(scene),
        "player_id": None,
        "stroke": "unknown",
        "position": None,
        "provenance": "automatic",
        "reviewed": False,
        "confidence": None,
        "excluded": False,
        "favorite": False,
    }
    event.update(updates)
    return validate_event(event)


def _box_distance(point, box):
    x, y = point
    x1, y1, x2, y2 = box
    return math.hypot(max(x1 - x, 0, x - x2), max(y1 - y, 0, y - y2))


class CandidateDetector:
    """Three observed samples plus constant-size rally/cooldown state.

    Point hypotheses use image trajectory turns and player/racket proximity.
    These are heuristics, not a validated physical contact classifier. A gap,
    scene cut or moving camera breaks continuity; interpolation is never evidence.
    """

    def __init__(self, max_gap=0.2, rally_gap=2.0, cooldown=0.25):
        self.max_gap = max_gap
        self.rally_gap = rally_gap
        self.cooldown = cooldown
        self.samples: deque[dict[str, Any]] = deque(maxlen=3)
        self.last_times = {}
        self.rally = None
        self.scene = None
        self.last_timestamp = None

    def _close_rally(self):
        result = []
        if self.rally and self.rally["hits"] >= 2:
            r = self.rally
            result.append(
                new_event(
                    "rally",
                    max(0, r["start"] - 0.5),
                    r["scene"],
                    r["frame"],
                    end=r["end"],
                    confidence=None,
                )
            )
        self.rally = None
        return result

    def feed(self, frame):
        timestamp = float(frame["timestamp"])
        if not math.isfinite(timestamp) or timestamp < 0:
            raise ValueError("Frame timestamps must be finite and nonnegative")
        if self.last_timestamp is not None and timestamp < self.last_timestamp:
            raise ValueError("Candidate generation requires ordered presentation timestamps")
        self.last_timestamp = timestamp
        scene = int(frame.get("scene", 0))
        result = []
        if self.scene != scene or frame.get("cut") or frame.get("camera_moving"):
            result.extend(self._close_rally())
            self.samples.clear()
            self.last_times.clear()
        self.scene = scene
        if self.rally and timestamp - self.rally["end"] > self.rally_gap:
            result.extend(self._close_rally())
        ball = frame.get("ball", {})
        point = ball.get("xy")
        if frame.get("camera_moving") or ball.get("status") != "observed" or point is None:
            self.samples.clear()
            return result
        if len(point) != 2 or not all(math.isfinite(float(v)) for v in point):
            raise ValueError("Observed ball must have finite pixel coordinates")
        if self.samples and timestamp - self.samples[-1]["timestamp"] > self.max_gap:
            self.samples.clear()
        if self.samples and timestamp <= self.samples[-1]["timestamp"]:
            return result  # duplicate PTS does not create a velocity
        # Keep only the context used by the contact heuristic, never full video frames.
        self.samples.append(
            {
                "timestamp": timestamp,
                "frame": int(frame["frame"]),
                "xy": list(point),
                "players": [{"id": p["id"], "box": p["box"]} for p in frame.get("players", [])][:4],
                "rackets": [
                    {"player_id": p.get("player_id"), "box": p["box"]}
                    for p in frame.get("rackets", [])
                ][:8],
            }
        )
        if self.rally:
            self.rally["end"] = timestamp
        if len(self.samples) < 3:
            return result
        a, b, c = self.samples
        u = [(b["xy"][i] - a["xy"][i]) / (b["timestamp"] - a["timestamp"]) for i in (0, 1)]
        v = [(c["xy"][i] - b["xy"][i]) / (c["timestamp"] - b["timestamp"]) for i in (0, 1)]
        un, vn = math.hypot(*u), math.hypot(*v)
        if min(un, vn) < 20:
            return result
        cosine = (u[0] * v[0] + u[1] * v[1]) / (un * vn)
        owners = []
        for player in b["players"]:
            height = max(1, player["box"][3] - player["box"][1])
            distance = _box_distance(b["xy"], player["box"]) / height
            if distance <= 0.2:
                owners.append((distance, player["id"]))
        racket_near = any(_box_distance(b["xy"], r["box"]) <= 15 for r in b["rackets"])
        kind = None
        if cosine < 0.35 and (owners or racket_near):
            kind = "hit"
        elif cosine < 0.7 and u[1] > 20 and v[1] < -20 and not owners and not racket_near:
            kind = "bounce"
        if kind is None or b["timestamp"] - self.last_times.get(kind, -math.inf) < self.cooldown:
            return result
        self.last_times[kind] = b["timestamp"]
        owners.sort()
        player_id = (
            owners[0][1]
            if owners and (len(owners) == 1 or owners[1][0] - owners[0][0] > 0.1)
            else None
        )
        result.append(
            new_event(
                kind,
                b["timestamp"],
                scene,
                b["frame"],
                player_id=player_id if kind == "hit" else None,
            )
        )
        if kind == "hit":
            if self.rally is None:
                self.rally = {
                    "start": b["timestamp"],
                    "end": timestamp,
                    "scene": scene,
                    "frame": b["frame"],
                    "hits": 0,
                }
            self.rally["hits"] += 1
        return result

    def finish(self):
        return self._close_rally()

    def state_dict(self):
        return deepcopy(
            {
                "version": 1,
                "max_gap": self.max_gap,
                "rally_gap": self.rally_gap,
                "cooldown": self.cooldown,
                "samples": list(self.samples),
                "last_times": self.last_times,
                "rally": self.rally,
                "scene": self.scene,
                "last_timestamp": self.last_timestamp,
            }
        )

    @classmethod
    def from_state(cls, state):
        if state.get("version") != 1:
            raise ValueError("Unsupported temporal candidate state")
        detector = cls(state["max_gap"], state["rally_gap"], state["cooldown"])
        detector.samples.extend(deepcopy(state["samples"]))
        detector.last_times = deepcopy(state["last_times"])
        detector.rally = deepcopy(state["rally"])
        detector.scene = state["scene"]
        detector.last_timestamp = state["last_timestamp"]
        return detector


def generate_candidates(frames):
    detector = CandidateDetector()
    for frame in frames:
        yield from detector.feed(frame)
    yield from detector.finish()


def _event_list(events):
    if isinstance(events, dict):
        if events.get("schema_version") not in (2, 3):
            raise ValueError("Unsupported event schema")
        events = events["events"]
    result = [deepcopy(validate_event(event)) for event in events]
    if len({event["id"] for event in result}) != len(result):
        raise ValueError("Duplicate event ids")
    return result


def apply_corrections(events, corrections):
    merged = {event["id"]: event for event in _event_list(events)}
    # Store full corrected records, so edits/additions survive a changed detector.
    for event_id, event in corrections.get("events", {}).items():
        if event_id != event.get("id"):
            raise ValueError("Correction id does not match its event")
        merged[event_id] = deepcopy(validate_event(event))
    return {
        "schema_version": 2,
        "events": sorted(merged.values(), key=lambda e: (e["start"], e["kind"], e["id"])),
    }


def regenerate_events(frames_path, events_path, corrections_path=None):
    with Path(frames_path).open() as stream:
        candidates = generate_candidates(json.loads(line) for line in stream if line.strip())
        corrections = (
            json.loads(Path(corrections_path).read_text())
            if corrections_path and Path(corrections_path).exists()
            else {}
        )
        document = apply_corrections(candidates, corrections)
    atomic_json(events_path, document)
    return document


def update_event(events_path, corrections_path, event_id, changes):
    """Add with event_id=None; remove using excluded=True; review explicitly.

    A full correction is persisted before the derived events file. After a crash,
    regeneration therefore recovers the edit. Court and label corrections survive.
    """
    document = (
        json.loads(Path(events_path).read_text())
        if Path(events_path).exists()
        else {"schema_version": 2, "events": []}
    )
    corrections = (
        json.loads(Path(corrections_path).read_text())
        if Path(corrections_path).exists()
        else {"court": {}, "labels": {}}
    )
    document = apply_corrections(document, corrections)
    by_id = {event["id"]: event for event in document["events"]}
    allowed = {
        "kind",
        "start",
        "end",
        "scene",
        "player_id",
        "stroke",
        "position",
        "reviewed",
        "excluded",
        "favorite",
    }
    if set(changes) - allowed:
        raise ValueError("Unsupported event edit fields")
    if event_id is None:
        event_id = f"manual-{uuid4().hex}"
        event = new_event(
            changes.get("kind", "hit"), changes.get("start", 0), id=event_id, provenance="manual"
        )
    else:
        if event_id not in by_id:
            raise ValueError(f"Unknown event: {event_id}")
        event = deepcopy(by_id[event_id])
    event.update(changes)
    if event["kind"] != "rally" and "start" in changes and "end" not in changes:
        event["end"] = event["start"]
    if set(changes) - {"reviewed", "excluded", "favorite"}:
        event["provenance"] = "manual"
        event["confidence"] = None
    validate_event(event)
    corrections.setdefault("events", {})[event_id] = event
    atomic_json(corrections_path, corrections)
    document = apply_corrections(document, corrections)
    atomic_json(events_path, document)
    return document


def summarize_events(events):
    rows = [event for event in _event_list(events) if not event["excluded"]]
    verified = [event for event in rows if event["reviewed"]]
    candidates = [event for event in rows if not event["reviewed"]]

    def counts(items):
        counter = Counter(event["kind"] for event in items)
        return {kind: counter[kind] for kind in KINDS}

    return {
        "verified": {
            **counts(verified),
            "strokes": dict(Counter(e["stroke"] for e in verified if e["kind"] == "hit")),
            "landings": [
                {
                    "event_id": e["id"],
                    "timestamp": e["start"],
                    "position": e["position"],
                    "player_id": e["player_id"],
                }
                for e in verified
                if e["kind"] == "bounce" and e["position"] is not None
            ],
        },
        "candidates": counts(candidates),
        "evidence": [
            {
                "event_id": e["id"],
                "kind": e["kind"],
                "start": e["start"],
                "end": e["end"],
                "scene": e["scene"],
                "player_id": e["player_id"],
                "reviewed": e["reviewed"],
                "favorite": e["favorite"],
            }
            for e in rows
        ],
    }
