"""Fresh, media-free review reports. No inferred identity or event association."""

import hashlib
import json
import math
from collections import defaultdict

from tennis_ai.events import STROKES


def _canonical(value):
    if isinstance(value, dict):
        return {k: _canonical(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_canonical(v) for v in value]
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{value:.9f}"
    return value


def review_report(bundle, *, view="assisted", participant_id=None, start=0.0, end):
    if (
        view not in ("assisted", "human_verified")
        or not 0 <= start <= end
        or not math.isfinite(end)
    ):
        raise ValueError("Invalid report view or time range")
    verified = view == "human_verified"
    root = bundle["events"]
    events = {e["id"]: e for e in root["events"]}
    people = {p["id"] for p in root["participants"]}
    assignments = defaultdict(list)
    links_by_bounce = defaultdict(list)
    for assignment in root["assignments"]:
        assignments[assignment["scene"], assignment["track_id"]].append(assignment)
    for link in root["links"]:
        if not link.get("removed", False):
            links_by_bounce[link["bounce_id"]].append(link)
    source = {k: bundle[k] for k in ("events", "rallies", "tracks", "audit")}
    digest = hashlib.sha256(
        json.dumps(
            _canonical(source), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()

    def identity(scene, track, time):
        rows = [a for a in assignments[scene, track] if a["start"] <= time < a["end"]]
        if len(rows) != 1 or not rows[0]["reviewed"]:
            return None
        pid = rows[0]["participant_id"]
        return pid if pid in people else None

    def reason(event, personal=True):
        if event["excluded"]:
            return "excluded"
        if not start <= event["start"] <= end:
            return "outside_range"
        if verified and not event["reviewed"]:
            return "unreviewed"
        if personal and participant_id is not None:
            pid = identity(event["scene"], event.get("player_id"), event["start"])
            if pid != participant_id or event.get("participant_id") not in (None, pid):
                return "unresolved_or_other_identity"
        return None

    def metric(key, included, excluded, *, refs=None, points=None, value=None):
        ids = sorted({e["id"] for e in included})
        n = len(points) if points is not None else len(included)
        return {
            "id": key,
            "value": (value if value is not None else n) if n else None,
            "sample_count": n,
            "event_ids": ids,
            "support_refs": sorted(set(refs or ids)),
            "exclusions": excluded,
            "points": points or [],
        }

    hits = [e for e in events.values() if e["kind"] == "hit"]
    accepted = [e for e in hits if reason(e) is None]
    excluded = {e["id"]: reason(e) for e in hits if reason(e) is not None}
    metrics = [metric("hits", accepted, excluded)]
    for stroke in (*STROKES, "unknown"):
        selected = [e for e in accepted if e["stroke"] == stroke]
        row = metric("stroke." + stroke, selected, excluded)
        # A zero category is meaningful only when an eligible hit denominator exists.
        row["value"] = len(selected) if accepted else None
        metrics.append(row)
    landing_events, points, unassigned, skipped, refs = [], [], [], {}, []
    for bounce in events.values():
        if bounce["kind"] != "bounce":
            continue
        why = reason(bounce, False)
        if why or bounce.get("position") is None:
            skipped[bounce["id"]] = why or "missing_bounce_position"
            continue
        links = links_by_bounce[bounce["id"]]
        pid, hit = None, None
        if len(links) == 1 and (not verified or links[0]["reviewed"]):
            hit = events.get(links[0]["shot_id"])
            if (
                hit
                and hit["kind"] == "hit"
                and reason(hit, False) is None
                and hit["scene"] == bounce["scene"]
                and hit["start"] <= bounce["start"]
            ):
                pid = identity(hit["scene"], hit.get("player_id"), hit["start"])
                if hit.get("participant_id") not in (None, pid):
                    pid = None
        point = {
            "reference": bounce["id"],
            "timestamp": bounce["start"],
            "position": bounce["position"],
            "participant_id": pid,
        }
        if pid is None:
            unassigned.append(point)
        if participant_id is not None and pid != participant_id:
            skipped[bounce["id"]] = "unresolved_or_other_identity"
            continue
        points.append(point)
        landing_events.append(bounce)
        if pid is not None and hit is not None:
            landing_events.append(hit)
            refs.append("link:" + links[0]["id"])
    metrics.append(
        metric(
            "landings",
            landing_events,
            skipped,
            refs=refs + [p["reference"] for p in points],
            points=points,
        )
    )
    metrics.append(
        metric(
            "unassigned_landings",
            [events[p["reference"]] for p in unassigned],
            {},
            points=unassigned,
        )
    )
    rally_events, rally_refs, lengths, rally_excluded = [], [], [], {}
    for rally in bundle["rallies"]["rallies"]:
        if rally.get("removed", False):
            rally_excluded["rally:" + rally["id"]] = "removed"
            continue
        shots = [events.get(e) for e in rally["shot_ids"]]
        if (
            not shots
            or not rally["reviewed"]
            or any(e is None or e["kind"] != "hit" or reason(e, False) is not None for e in shots)
        ):
            rally_excluded["rally:" + rally["id"]] = "missing_or_ineligible_shot_list"
            continue
        if participant_id is not None and not any(reason(e) is None for e in shots):
            rally_excluded["rally:" + rally["id"]] = "unresolved_or_other_identity"
            continue
        lengths.append(len(shots))
        rally_events.extend(shots)
        rally_refs.append("rally:" + rally["id"])
    row = metric(
        "rally_length",
        rally_events,
        rally_excluded,
        refs=rally_refs,
        value=sum(lengths) / len(lengths) if lengths else None,
    )
    row["sample_count"] = len(lengths)
    metrics.append(row)
    positions, track_excluded = [], {}
    for index, sample in enumerate(bundle["tracks"]):
        ref = f"track:{index}"
        pid = identity(sample["scene"], sample["track_id"], sample["timestamp"])
        why = None
        if not start <= sample["timestamp"] <= end:
            why = "outside_range"
        elif verified and not sample["reviewed"]:
            why = "unreviewed"
        elif sample["position_court_m"] is None:
            why = "missing_position"
        elif participant_id is not None and pid != participant_id:
            why = "unresolved_or_other_identity"
        if why:
            track_excluded[ref] = why
        else:
            positions.append(
                {
                    "reference": ref,
                    "timestamp": sample["timestamp"],
                    "position": sample["position_court_m"],
                    "participant_id": pid,
                }
            )
    metrics.append(
        metric(
            "player_positions",
            [],
            track_excluded,
            refs=[p["reference"] for p in positions],
            points=positions,
        )
    )
    return {
        "schema_version": 1,
        "definition_version": "review-loop-v1",
        "view": view,
        "participant_id": participant_id,
        "start": start,
        "end": end,
        "input_digest": digest,
        "metrics": metrics,
    }
