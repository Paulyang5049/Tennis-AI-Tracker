"""Render the README court map from made-up shots. It is an illustration, not a result."""

import random
from pathlib import Path

import cv2

from tennis_ai.shots import classify
from tennis_ai.tactics import court_map, tendency


def main():
    rng = random.Random(7)
    shots = []
    for index in range(18):
        # A right-hander pulled wide on the deuce side, mostly answering cross-court.
        hitter = [rng.uniform(8.6, 10.4), rng.uniform(23.6, 25.2)]
        cross = rng.random() < 0.67
        landing = [rng.uniform(1.8, 4.2) if cross else rng.uniform(7.2, 9.3), rng.uniform(1.0, 6.5)]
        if index % 9 == 4:
            landing = [rng.uniform(4.6, 6.2), rng.uniform(2.0, 5.0)]
        shots.append(
            {
                "id": f"demo-{index}",
                "start": float(index),
                "participant_id": "opponent",
                "incoming_shot_id": None,
                "role": "return",
                "stroke": "forehand",
                "hitter_normalized_m": [round(v, 2) for v in hitter],
                "landing_normalized_m": [round(v, 2) for v in landing],
                **classify("return", "forehand", hitter, landing, "right"),
            }
        )
    document = {"definition_version": "shots-v1", "view": "assisted", "shots": shots}
    result = tendency(document, participant_id="opponent", where={"role": "return"})
    image = court_map(result, "SYNTHETIC EXAMPLE: returns of a wide deuce serve")
    target = Path(__file__).resolve().parents[1] / "docs/images/tactics-demo.png"
    if not cv2.imwrite(str(target), image):
        raise SystemExit("Could not write the demo image")
    print(target)


if __name__ == "__main__":
    main()
