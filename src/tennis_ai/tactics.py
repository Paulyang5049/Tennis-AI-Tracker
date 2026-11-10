"""Shot tendencies: "when X happens, where does this player hit?".

Descriptive counts over derived shot paths. Every figure carries its sample size
and interval; nothing here predicts, ranks players or claims a cause.
"""

import math

import cv2
import numpy as np

from tennis_ai.shots import CENTRE, LENGTH, NET, SERVICE_LINE, SINGLES, WIDTH

DEFINITION = "tendency-v1"
FILTERS = ("role", "stroke", "spin", "serve_side", "direction", "depth", "width", "side")
AXES = ("direction", "depth", "width")
COLOURS = {  # BGR
    "cross_court": (80, 170, 255),
    "down_the_line": (90, 220, 120),
    "middle": (235, 235, 235),
    "inside_out": (230, 120, 220),
    "inside_in": (240, 200, 90),
    "t": (90, 220, 120),
    "body": (235, 235, 235),
    "wide": (80, 170, 255),
    None: (160, 160, 160),
}


def parse_filters(items):
    """Turn ["role=return", "stroke=backhand"] into a validated filter mapping."""
    result = {}
    for item in items or []:
        key, sep, value = item.partition("=")
        if not sep or key not in FILTERS or not value:
            raise ValueError(f"Filter must be key=value with key in {', '.join(FILTERS)}")
        result[key] = value
    return result


def wilson(count, total, z=1.96):
    """95% Wilson score interval; stays honest for the small samples a match gives."""
    if not total:
        return None
    p = count / total
    centre = p + z * z / (2 * total)
    spread = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total))
    scale = 1 + z * z / total
    return [
        round(max(0.0, (centre - spread) / scale), 4),
        round(min(1.0, (centre + spread) / scale), 4),
    ]


def tendency(document, *, participant_id=None, where=None, incoming=None, min_support=8):
    """Distribution of one player's shots that match `where`, given the shot they received."""
    where, incoming = where or {}, incoming or {}
    if set(where) - set(FILTERS) or set(incoming) - set(FILTERS):
        raise ValueError("Unknown tendency filter")
    shots = {shot["id"]: shot for shot in document["shots"]}

    def matches(shot, conditions):
        return all(shot.get(key) == value for key, value in conditions.items())

    selected, exclusions = [], {}
    for shot in document["shots"]:
        if participant_id is not None and shot["participant_id"] != participant_id:
            continue
        if not matches(shot, where):
            continue
        if incoming:
            previous = shots.get(shot["incoming_shot_id"])
            if previous is None or not matches(previous, incoming):
                continue
        if shot["landing_normalized_m"] is None:
            exclusions[shot["id"]] = "missing_landing"
            continue
        selected.append(shot)
    total = len(selected)
    distributions = {}
    for axis in AXES:
        counts: dict[str, int] = {}
        for shot in selected:
            key = shot[axis] if shot[axis] is not None else "unclassified"
            counts[key] = counts.get(key, 0) + 1
        distributions[axis] = [
            {
                "value": key,
                "count": count,
                "share": round(count / total, 4),
                "interval_95": wilson(count, total),
                "shot_ids": [s["id"] for s in selected if (s[axis] or "unclassified") == key],
            }
            for key, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        ]
    return {
        "schema_version": 1,
        "definition_version": DEFINITION,
        "shots_definition_version": document["definition_version"],
        "view": document["view"],
        "participant_id": participant_id,
        "where": dict(sorted(where.items())),
        "incoming": dict(sorted(incoming.items())),
        "sample_count": total,
        "min_support": min_support,
        "support": "adequate" if total >= min_support else "limited",
        "distributions": distributions,
        "points": [
            {
                "shot_id": s["id"],
                "start": s["start"],
                "hitter": s["hitter_normalized_m"],
                "landing": s["landing_normalized_m"],
                "direction": s["direction"],
            }
            for s in selected
        ],
        "exclusions": exclusions,
    }


def court_map(result, title="", scale=34, margin=70):
    """Top-down picture of a tendency: the hitter is always at the bottom."""
    pad_x, pad_y = 3.0, 4.0  # Metres of run-off drawn around the court.
    width = int((WIDTH + 2 * pad_x) * scale)
    height = int((LENGTH + 2 * pad_y) * scale) + margin
    image = np.full((height, width, 3), (58, 44, 30), np.uint8)

    def px(point):
        return (
            int(round((point[0] + pad_x) * scale)),
            int(round((point[1] + pad_y) * scale)) + margin,
        )

    cv2.rectangle(image, px((0, 0)), px((WIDTH, LENGTH)), (150, 98, 46), -1)
    white = (245, 245, 245)
    low, high = SINGLES
    for a, b in (
        ((0, 0), (WIDTH, 0)),
        ((0, LENGTH), (WIDTH, LENGTH)),
        ((0, 0), (0, LENGTH)),
        ((WIDTH, 0), (WIDTH, LENGTH)),
        ((low, 0), (low, LENGTH)),
        ((high, 0), (high, LENGTH)),
        ((low, SERVICE_LINE), (high, SERVICE_LINE)),
        ((low, LENGTH - SERVICE_LINE), (high, LENGTH - SERVICE_LINE)),
        ((CENTRE, SERVICE_LINE), (CENTRE, LENGTH - SERVICE_LINE)),
    ):
        cv2.line(image, px(a), px(b), white, 2, cv2.LINE_AA)
    cv2.line(image, px((-0.9, NET)), px((WIDTH + 0.9, NET)), (30, 30, 30), 3, cv2.LINE_AA)
    paths = image.copy()
    for point in result["points"]:
        if point["hitter"] is not None:
            colour = COLOURS.get(point["direction"], COLOURS[None])
            cv2.line(paths, px(point["hitter"]), px(point["landing"]), colour, 2, cv2.LINE_AA)
    image = cv2.addWeighted(paths, 0.55, image, 0.45, 0)
    for point in result["points"]:
        colour = COLOURS.get(point["direction"], COLOURS[None])
        if point["hitter"] is not None:
            cv2.circle(image, px(point["hitter"]), 4, white, 1, cv2.LINE_AA)
        cv2.circle(image, px(point["landing"]), 7, colour, -1, cv2.LINE_AA)
        cv2.circle(image, px(point["landing"]), 7, (20, 20, 20), 1, cv2.LINE_AA)
    font = cv2.FONT_HERSHEY_SIMPLEX
    # OpenCV's built-in font is ASCII-only; drop anything it cannot draw.
    heading = (title or "Shot tendency").encode("ascii", "ignore").decode()
    cv2.putText(image, heading, (16, 30), font, 0.7, white, 2, cv2.LINE_AA)
    note = f"n={result['sample_count']}  support: {result['support']}  view: {result['view']}"
    cv2.putText(image, note, (16, 56), font, 0.5, (200, 200, 200), 1, cv2.LINE_AA)
    y = height - 14 - 20 * len(result["distributions"]["direction"])
    for row in result["distributions"]["direction"]:
        y += 20
        colour = COLOURS.get(row["value"], COLOURS[None])
        cv2.circle(image, (24, y - 5), 6, colour, -1, cv2.LINE_AA)
        label = f"{row['value']}  {row['count']}/{result['sample_count']} ({row['share']:.0%})"
        cv2.putText(image, label, (40, y), font, 0.5, white, 1, cv2.LINE_AA)
    return image
