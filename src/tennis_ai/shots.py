"""Derived shot paths on the 2D court. Adds no measured facts.

A shot path is the hitter's ground point at contact joined to the bounce that a
link associates with that hit. Both ends lie on the court plane, so no airborne
ball position is ever projected. Anything missing stays null.
"""

from collections import defaultdict
from typing import Any

from tennis_ai.schema import validate_schema

DEFINITION = "shots-v1"
WIDTH, LENGTH = 10.97, 23.77
NET, CENTRE = LENGTH / 2, WIDTH / 2
SINGLES = (1.37, 9.60)
SERVICE_LINE = 5.485  # Far service line in the hitter-at-bottom frame.
DEEP_LINE = SERVICE_LINE / 2
HANDS = ("right", "left")


def normalize(point, side):
    """Rotate into a frame where the hitter is always on the near (bottom) side."""
    if point is None or side not in ("near", "far"):
        return None
    x, y = point
    if side == "far":
        x, y = WIDTH - x, LENGTH - y
    return [round(x, 3), round(y, 3)]


def _third(x, low, high):
    return min(2, max(0, int(3 * (x - low) / (high - low))))


def classify(role, stroke, hitter, landing, hand=None):
    """Rule-based labels from normalized points. Returns only what the geometry supports."""
    out: dict[str, Any] = {
        "serve_side": None,
        "direction": None,
        "depth": None,
        "width": None,
        "landing_in": None,
    }
    if role == "serve" and hitter is not None:
        out["serve_side"] = "deuce" if hitter[0] > CENTRE else "ad"
    if landing is None:
        return out
    x, y = landing
    low, high = SINGLES
    out["width"] = (
        "wide_left"
        if x < low
        else "wide_right"
        if x > high
        else ("left", "centre", "right")[_third(x, low, high)]
    )
    if y > NET:
        out["depth"], out["landing_in"] = "own_side", False
        return out
    out["depth"] = (
        "long" if y < 0 else "deep" if y < DEEP_LINE else "mid" if y < SERVICE_LINE else "short"
    )
    out["landing_in"] = low <= x <= high and y >= 0
    if role == "serve":
        side = out["serve_side"]
        if side is None:
            out["landing_in"] = None
            return out
        # A deuce serve goes diagonally into the box on the server's left.
        box = (low, CENTRE) if side == "deuce" else (CENTRE, high)
        out["landing_in"] = box[0] <= x <= box[1] and SERVICE_LINE <= y <= NET
        if out["landing_in"]:
            third = _third(x, *box)
            toward_centre = 2 if side == "deuce" else 0
            out["direction"] = "t" if third == toward_centre else "body" if third == 1 else "wide"
        return out
    if hitter is None:
        return out
    if out["width"] == "centre":
        out["direction"] = "middle"
        return out
    hitter_right = hitter[0] > CENTRE
    landing_right = x > CENTRE
    out["direction"] = "down_the_line" if hitter_right == landing_right else "cross_court"
    if hand in HANDS and stroke in ("forehand", "backhand"):
        natural_right = (hand == "right") == (stroke == "forehand")
        if natural_right != hitter_right:
            out["direction"] = "inside_out" if out["direction"] == "cross_court" else "inside_in"
    return out


def derive_shots(bundle, *, view="assisted", handedness=None, max_position_gap=0.5):
    """One record per eligible hit; ineligible hits are listed with a reason."""
    if view not in ("assisted", "human_verified"):
        raise ValueError("Invalid shot view")
    handedness = handedness or {}
    if any(hand not in HANDS for hand in handedness.values()):
        raise ValueError("Handedness must be right or left")
    verified = view == "human_verified"
    root = bundle["events"]
    events = {e["id"]: e for e in root["events"]}
    people = {p["id"] for p in root["participants"]}
    assignments, tracks = defaultdict(list), defaultdict(list)
    for row in root["assignments"]:
        assignments[row["scene"], row["track_id"]].append(row)
    for sample in bundle.get("tracks", []):
        if sample.get("position_court_m") is not None and (sample["reviewed"] or not verified):
            tracks[sample["scene"], sample["track_id"]].append(sample)
    by_shot, by_bounce = defaultdict(list), defaultdict(list)
    for link in root["links"]:
        if not link.get("removed", False):
            by_shot[link["shot_id"]].append(link)
            by_bounce[link["bounce_id"]].append(link)

    def usable(event):
        return not event["excluded"] and (event["reviewed"] or not verified)

    def identity(event):
        rows = [
            a
            for a in assignments[event["scene"], event.get("player_id")]
            if a["start"] <= event["start"] < a["end"]
        ]
        if len(rows) != 1 or not rows[0]["reviewed"]:
            return None, None
        pid = rows[0]["participant_id"]
        if pid not in people or event.get("participant_id") not in (None, pid):
            pid = None
        return pid, rows[0]["side"]

    def position(event):
        if event.get("hitter_position_court_m") is not None:
            return list(event["hitter_position_court_m"]), "event"
        rows = tracks[event["scene"], event.get("player_id")]
        if not rows:
            return None, None
        best = min(rows, key=lambda s: abs(s["timestamp"] - event["start"]))
        if abs(best["timestamp"] - event["start"]) > max_position_gap:
            return None, None
        return list(best["position_court_m"]), "track"

    def landing(event):
        links = by_shot[event["id"]]
        if len(links) != 1 or (verified and not links[0]["reviewed"]):
            return None, None
        link = links[0]
        bounce = events.get(link["bounce_id"])
        if (
            bounce is None
            or bounce["kind"] != "bounce"
            or not usable(bounce)
            or bounce.get("position") is None
            or bounce["scene"] != event["scene"]
            or bounce["start"] < event["start"]
            or len(by_bounce[bounce["id"]]) != 1
        ):
            return None, None
        return bounce, link

    context: dict[str, tuple[Any, Any, Any, Any]] = {}
    for rally in bundle["rallies"]["rallies"]:
        found = [events.get(i) for i in rally["shot_ids"]]
        hits = [e for e in found if e is not None and e["kind"] == "hit" and usable(e)]
        if rally.get("removed", False) or (verified and not rally["reviewed"]):
            continue
        if len(hits) != len(found):
            continue
        served = bool(hits) and hits[0]["stroke"] == "serve"
        for index, event in enumerate(hits):
            role: str | None = "rally"
            if index == 0:
                role = "serve" if served else None
            elif index == 1:
                role = "return" if served else None
            context[event["id"]] = (
                rally["id"],
                index + 1,
                role,
                hits[index - 1]["id"] if index else None,
            )

    shots, exclusions = [], {}
    for event in sorted(events.values(), key=lambda e: (e["start"], e["id"])):
        if event["kind"] != "hit":
            continue
        if not usable(event):
            exclusions[event["id"]] = "excluded" if event["excluded"] else "unreviewed"
            continue
        rally_id, ordinal, shot_role, incoming = context.get(event["id"], (None, None, None, None))
        if rally_id is None and event["stroke"] == "serve":
            shot_role = "serve"
        pid, side = identity(event)
        hitter, source = position(event)
        if side is None and hitter is not None:
            side = "near" if hitter[1] > NET else "far"
        bounce, link = landing(event)
        hitter_n = normalize(hitter, side)
        landing_n = normalize(bounce["position"] if bounce else None, side)
        refs = [event["id"]]
        if bounce is not None:
            refs += [bounce["id"], "link:" + link["id"]]
        if rally_id is not None:
            refs.append("rally:" + rally_id)
        shots.append(
            {
                "id": event["id"],
                "start": event["start"],
                "scene": event["scene"],
                "rally_id": rally_id,
                "ordinal": ordinal,
                "role": shot_role,
                "incoming_shot_id": incoming,
                "participant_id": pid,
                "side": side,
                "stroke": event["stroke"],
                "spin": event.get("spin"),
                "reviewed": event["reviewed"],
                "hitter_position_court_m": hitter,
                "hitter_position_source": source,
                "landing_court_m": list(bounce["position"]) if bounce else None,
                "bounce_id": bounce["id"] if bounce else None,
                "hitter_normalized_m": hitter_n,
                "landing_normalized_m": landing_n,
                **classify(shot_role, event["stroke"], hitter_n, landing_n, handedness.get(pid)),
                "support_refs": refs,
            }
        )
    document = {
        "schema_version": 1,
        "definition_version": DEFINITION,
        "view": view,
        "coordinate_system": "hitter_near_x_right_y_near_m",
        "handedness": dict(sorted(handedness.items())),
        "shots": shots,
        "exclusions": exclusions,
    }
    validate_schema("shots-v1.schema.json", document)
    return document
