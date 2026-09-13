"""Versioned evidence graph. Nullable observations never become verified facts."""

import json
import math
import os
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from tennis_ai.events import validate_event
from tennis_ai.package import relative_asset
from tennis_ai.schema import validate_schema

ASSET_VERSIONS = {
    "frames": 2,
    "events": 3,
    "corrections": 2,
    "tracks": 1,
    "rallies": 1,
    "metrics": 1,
    "insights": 1,
    "audit": 1,
}
ASSETS = {
    "tracks": "tracks.jsonl",
    "rallies": "rallies.json",
    "metrics": "metrics.json",
    "insights": "insights.json",
    "audit": "corrections.jsonl",
}
MAX_BYTES = 32 * 1024 * 1024
MAX_ROWS = 100_000


def entity_rows(bundle, kind):
    if kind == "rally":
        return bundle["rallies"]["rallies"]
    key = {"event": "events", "participant": "participants", "assignment": "assignments"}.get(kind)
    if key is None:
        raise ValueError("Unsupported correction entity")
    return bundle["events"][key]


def finite(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Evidence numbers must be finite")
    return value


def point(value):
    if value is not None:
        if not isinstance(value, list) or len(value) != 2:
            raise ValueError("Evidence point must be null or [x, y]")
        for coordinate in value:
            finite(coordinate)


def indexed(rows):
    if not isinstance(rows, list) or len(rows) > MAX_ROWS:
        raise ValueError("Evidence collection exceeds row limit")
    result = {}
    for row in rows:
        key = row.get("id")
        if not isinstance(key, str) or not key or key in result:
            raise ValueError("Evidence IDs must be nonempty and unique")
        result[key] = row
    return result


def interval(row, duration):
    start, end = finite(row["start"]), finite(row["end"])
    if not 0 <= start <= end <= duration:
        raise ValueError("Invalid evidence temporal order or duration")


def confidence(value):
    if value is not None and not 0 <= finite(value) <= 1:
        raise ValueError("Confidence must be null or within [0, 1]")


def references(values, lookup):
    if (
        not isinstance(values, list)
        or len(set(values)) != len(values)
        or any(v not in lookup for v in values)
    ):
        raise ValueError("Broken or duplicate evidence reference")


def validate_evidence(bundle, duration):
    """Cross-asset invariants supplement the portable JSON Schemas."""
    for key, version in (("events", 3), ("rallies", 1), ("metrics", 1), ("insights", 1)):
        validate_schema(f"{key}-v{version}.schema.json", bundle[key])
    for key in ("tracks", "audit"):
        for row in bundle[key]:
            validate_schema(f"{key}-v1.schema.json", row)
    doc = bundle["events"]
    if doc["schema_version"] != 3:
        raise ValueError("Unsupported evidence schema")
    events = indexed(doc["events"])
    participants = indexed(doc["participants"])
    assignments = indexed(doc["assignments"])
    links = indexed(doc["links"])
    for participant in participants.values():
        if participant["role"] not in ("self", "opponent", "partner", "unknown"):
            raise ValueError("Unsupported participant role")
    for assignment in assignments.values():
        interval(assignment, duration)
        confidence(assignment["confidence"])
        if assignment["side"] not in ("near", "far") or not isinstance(
            assignment["reviewed"], bool
        ):
            raise ValueError("Invalid side assignment")
        pid = assignment["participant_id"]
        if pid is not None and pid not in participants:
            raise ValueError("Broken participant reference")
        if assignment["reviewed"] and pid is None:
            raise ValueError("Reviewed assignment needs a participant")
    assigned = sorted(assignments.values(), key=lambda a: (a["scene"], a["track_id"], a["start"]))
    for a, b in zip(assigned, assigned[1:]):
        if a["scene"] == b["scene"] and a["track_id"] == b["track_id"] and a["end"] > b["start"]:
            raise ValueError("Overlapping track assignment intervals")
    for event in events.values():
        validate_event(event)
        interval(event, duration)
        for key in ("contact_point_image_px", "hitter_position_court_m", "contact_interval"):
            point(event.get(key))
        if event.get("contact_interval") is not None:
            start, end = event["contact_interval"]
            if event["kind"] != "hit" or not 0 <= start <= event["start"] <= end <= duration:
                raise ValueError("Invalid contact interval")
        if event["kind"] != "hit" and any(
            event.get(k) is not None for k in ("contact_point_image_px", "hitter_position_court_m")
        ):
            raise ValueError("Contact observations belong to hit events")
        for value in event.get("field_confidence", {}).values():
            confidence(value)
        if event.get("position") is not None and event.get("position_source") not in (
            "reviewed_bounce",
            "legacy_v2",
        ):
            raise ValueError("Landing requires bounce provenance")
        pid = event.get("participant_id")
        if pid is not None:
            if pid not in participants:
                raise ValueError("Broken participant reference")
            matches = [
                a
                for a in assigned
                if a["scene"] == event["scene"]
                and a["track_id"] == event["player_id"]
                and a["start"] <= event["start"] < a["end"]
                and a["participant_id"] == pid
            ]
            if len(matches) != 1 or (event["reviewed"] and not matches[0]["reviewed"]):
                raise ValueError("Participant event requires an unambiguous matching assignment")
    for link in links.values():
        references([link["shot_id"], link["bounce_id"]], events)
        hit, bounce = events[link["shot_id"]], events[link["bounce_id"]]
        if (
            hit["kind"] != "hit"
            or bounce["kind"] != "bounce"
            or hit["scene"] != bounce["scene"]
            or hit["start"] > bounce["start"]
        ):
            raise ValueError("Invalid shot-bounce association")
        confidence(link["confidence"])
        if link["reviewed"] and not (hit["reviewed"] and bounce["reviewed"]):
            raise ValueError("Reviewed link requires reviewed events")
    for key in ("rallies", "metrics", "insights"):
        if bundle[key]["schema_version"] != 1:
            raise ValueError("Unsupported derived asset version")
        indexed(bundle[key][key])
    for rally in bundle["rallies"]["rallies"]:
        interval(rally, duration)
        references(rally["shot_ids"], events)
        times = [events[e]["start"] for e in rally["shot_ids"]]
        if times != sorted(times) or any(events[e]["kind"] != "hit" for e in rally["shot_ids"]):
            raise ValueError("Rally shots must be ordered hits")
        if any(not rally["start"] <= t <= rally["end"] for t in times):
            raise ValueError("Rally does not contain its shots")
    metrics = indexed(bundle["metrics"]["metrics"])
    for metric in metrics.values():
        references(metric["event_ids"], events)
        references(metric["excluded_event_ids"], events)
        if metric["value"] is not None:
            finite(metric["value"])
        if not 0 <= finite(metric["numerator"]) <= finite(metric["denominator"]):
            raise ValueError("Invalid metric counts")
        if metric["view"] not in ("human_verified", "assisted") or not metric["input_digest"]:
            raise ValueError("Metric needs view and input provenance")
        if metric["view"] == "human_verified" and any(
            not events[e]["reviewed"] or events[e]["excluded"] for e in metric["event_ids"]
        ):
            raise ValueError("Verified metric cannot use candidate or excluded evidence")
    for insight in bundle["insights"]["insights"]:
        references(insight["metric_ids"], metrics)
        references(insight["event_ids"], events)
        if (
            not insight["metric_ids"]
            or not insight["event_ids"]
            or any(metrics[m]["view"] != "human_verified" for m in insight["metric_ids"])
        ):
            raise ValueError("Coaching requires human-verified supporting metrics")
        supported = {e for m in insight["metric_ids"] for e in metrics[m]["event_ids"]}
        if not set(insight["event_ids"]).issubset(supported):
            raise ValueError("Insight evidence must support its metrics")
    indexed(bundle["audit"])
    entity_indexes = {
        "event": events,
        "participant": participants,
        "assignment": assignments,
        "rally": indexed(bundle["rallies"]["rallies"]),
    }
    for sequence, record in enumerate(bundle["audit"], 1):
        kind = record.get("entity_type", "event")
        entities = entity_indexes[kind]
        if (
            record["schema_version"] != 1
            or record["sequence"] != sequence
            or record["entity_id"] not in entities
        ):
            raise ValueError("Invalid append-only audit sequence or entity")
        if (
            not record["actor"]
            or not record["reason"]
            or not record["timestamp"]
            or record["after"]["id"] != record["entity_id"]
        ):
            raise ValueError("Audit requires actor, reason, timestamp and matching entity")
        marker = {
            "event": "kind",
            "participant": "role",
            "assignment": "track_id",
            "rally": "shot_ids",
        }[kind]
        if marker not in record["after"] or (
            record["before"] is not None
            and (marker not in record["before"] or record["before"]["id"] != record["entity_id"])
        ):
            raise ValueError("Audit payload does not match its entity type")
    for sample in bundle["tracks"]:
        if sample["schema_version"] != 1 or not 0 <= finite(sample["timestamp"]) <= duration:
            raise ValueError("Invalid track time or version")
        point(sample["position_court_m"])
        if sample["position_court_m"] is not None and (
            sample["method"] not in ("ankles_homography", "box_bottom_homography")
            or not sample["calibration_id"]
        ):
            raise ValueError("Player position needs ground-point method and calibration")
    return bundle


def read_bounded(path, lines=False):
    path = Path(path)
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("Evidence asset exceeds size limit")

    def reject(value):
        raise ValueError(f"Non-finite JSON number: {value}")

    if lines:
        with path.open() as stream:
            rows = []
            for line in stream:
                if line.strip():
                    rows.append(json.loads(line, parse_constant=reject))
                if len(rows) > MAX_ROWS:
                    raise ValueError("Evidence asset exceeds row limit")
            return rows
    return json.loads(path.read_text(), parse_constant=reject)


def load_evidence(folder, manifest=None):
    from tennis_ai.package import load_manifest

    manifest = manifest or load_manifest(folder)
    bundle = {
        key: read_bounded(
            relative_asset(folder, manifest["artifacts"][key]), key in ("tracks", "audit")
        )
        for key in ("events", "rallies", "metrics", "insights", "tracks", "audit")
    }
    # Audit is the durable source of truth; materialized events may lag a crash.
    original = deepcopy((bundle["events"], bundle["rallies"]))
    row_indexes = {
        kind: {row["id"]: i for i, row in enumerate(entity_rows(bundle, kind))}
        for kind in ("event", "participant", "assignment", "rally")
    }
    for record in bundle["audit"]:
        validate_schema("audit-v1.schema.json", record)
        kind = record.get("entity_type", "event")
        rows = entity_rows(bundle, kind)
        existing = row_indexes[kind].get(record["entity_id"])
        if existing is None:
            row_indexes[kind][record["entity_id"]] = len(rows)
            rows.append(deepcopy(record["after"]))
        else:
            rows[existing] = deepcopy(record["after"])
    bundle["events"]["events"].sort(key=lambda e: (e["start"], e["id"]))
    if (bundle["events"], bundle["rallies"]) != original:
        bundle["metrics"]["metrics"] = []
        bundle["insights"]["insights"] = []
    return validate_evidence(bundle, manifest["media"]["duration"])


def persist_review(folder, manifest, bundle, records):
    """Caller holds run_lock. One fsynced append precedes all materializations."""
    from tennis_ai.package import atomic_json

    bundle["audit"].extend(records)
    bundle["metrics"]["metrics"] = []
    bundle["insights"]["insights"] = []
    validate_evidence(bundle, manifest["media"]["duration"])
    path = relative_asset(folder, manifest["artifacts"]["audit"])
    with path.open("a") as stream:
        for record in records:
            stream.write(json.dumps(record, allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    for key in ("events", "rallies", "metrics", "insights"):
        atomic_json(relative_asset(folder, manifest["artifacts"][key]), bundle[key])


def review_entity(folder, kind, value, *, actor="local-user", reason="identity or rally review"):
    from tennis_ai.jobs import run_lock
    from tennis_ai.package import load_manifest

    if kind not in ("participant", "assignment", "rally"):
        raise ValueError("Use the event review API for event corrections")
    with run_lock(folder):
        manifest = load_manifest(folder)
        if manifest["status"] != "complete":
            raise ValueError("Complete the analysis before reviewing identity or rallies")
        bundle = load_evidence(folder, manifest)
        rows = entity_rows(bundle, kind)
        before = next((r for r in rows if r["id"] == value["id"]), None)
        if before is not None:
            rows.remove(before)
        rows.append(deepcopy(value))
        record = {
            "schema_version": 1,
            "entity_type": kind,
            "id": uuid4().hex,
            "sequence": len(bundle["audit"]) + 1,
            "entity_id": value["id"],
            "actor": actor,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "reason": reason,
            "before": before,
            "after": deepcopy(value),
        }
        persist_review(folder, manifest, bundle, [record])
        return bundle


def edit_evidence_event(folder, event_id, changes, *, actor="local-user", reason="event review"):
    """Append a durable full-record correction before materializing derived files."""
    from tennis_ai.events import new_event
    from tennis_ai.jobs import run_lock
    from tennis_ai.package import load_manifest

    with run_lock(folder):
        manifest = load_manifest(folder)
        if manifest["status"] != "complete":
            raise ValueError("Complete the analysis before editing events")
        bundle = load_evidence(folder, manifest)
        by_id = indexed(bundle["events"]["events"])
        before = by_id.get(event_id)
        if event_id is not None and before is None:
            raise ValueError("Unknown event")
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
            "participant_id",
            "contact_interval",
            "contact_point_image_px",
            "hitter_position_court_m",
            "position_source",
        }
        if set(changes) - allowed:
            raise ValueError("Unsupported event edit fields")
        event = (
            deepcopy(before)
            if before
            else new_event(
                changes.get("kind", "hit"), changes.get("start", 0), id=f"manual-{uuid4().hex}"
            )
        )
        event.update(changes)
        if event["kind"] != "rally" and "start" in changes and "end" not in changes:
            event["end"] = event["start"]
        if set(changes) - {"favorite", "reviewed", "excluded"}:
            event.update(provenance="manual", confidence=None, field_confidence={})
        if "position" in changes and changes["position"] is not None:
            event["position_source"] = "reviewed_bounce"
        if "start" in changes and "contact_interval" not in changes:
            event["contact_interval"] = None
        by_id[event["id"]] = event
        bundle["events"]["events"] = sorted(by_id.values(), key=lambda e: (e["start"], e["id"]))
        record = {
            "schema_version": 1,
            "id": uuid4().hex,
            "sequence": len(bundle["audit"]) + 1,
            "entity_id": event["id"],
            "actor": actor,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "reason": reason,
            "before": before,
            "after": event,
        }
        persist_review(folder, manifest, bundle, [record])
        return bundle["events"]
