"""Build the shared contact-v2 fixture that Python and Swift must interpret identically."""

import argparse
import json
from pathlib import Path

from tennis_ai.events import generate_candidates

NEAR = {"id": 1, "box": [900, 800, 1000, 1000], "confidence": 0.9}
FAR = {"id": 2, "box": [940, 300, 1000, 380], "confidence": 0.9}
GAP = [None] * 40
# Ball image y per frame at 30 fps; None is an unobserved frame.
TRACK = (
    # Near hit with eight unobserved frames at contact.
    [500, 560, 620, 680, 720, 760, 800, 830, 850]
    + [None] * 8
    + [740, 650, 560, 470, 400, 360]
    # A near serve toss that does not count, then the serve.
    + GAP
    + [880, 820, 740, 660, 600, 570, 560, 580, 640, 720, 800, 760, 640, 520, 440, 380]
    # A far contact with a gradual image turn.
    + GAP
    + [600, 520, 450, 390, 350, 330, 320, 318, 322, 340, 380, 450, 540, 620, 700]
    # A ball passing the far player without a return.
    + GAP
    + [600, 520, 440, 380, 340, 310, 280, 250, 220]
)


def frames():
    for index, y in enumerate(TRACK):
        yield {
            "schema_version": 2,
            "frame": index,
            "timestamp": round(index / 30, 6),
            "scene": 0,
            "cut": False,
            "camera_moving": False,
            "court": None,
            "players": [NEAR, FAR],
            "rackets": [],
            "ball_candidates": [],
            "ball": {
                "status": "missing" if y is None else "observed",
                "xy": None if y is None else [950, y],
                "confidence": None if y is None else 0.9,
            },
        }


def expected():
    keep = ("id", "kind", "start", "end", "player_id")
    return [
        {key: event[key] for key in keep}
        for event in generate_candidates(frames(), "contact-v2")
        if event["kind"] in ("hit", "rally")
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    folder = Path(__file__).resolve().parents[1] / "contracts/fixtures/contact-v2"
    outputs = {
        folder / "frames.jsonl": "".join(
            json.dumps(f, separators=(",", ":")) + "\n" for f in frames()
        ),
        folder / "expected.json": json.dumps(expected(), indent=2) + "\n",
    }
    if args.check:
        stale = [p.name for p, text in outputs.items() if not p.exists() or p.read_text() != text]
        if stale:
            parser.exit(1, f"Stale contact fixture {stale}; run scripts/build_contact_fixture.py\n")
        return
    folder.mkdir(parents=True, exist_ok=True)
    for path, text in outputs.items():
        path.write_text(text)


if __name__ == "__main__":
    main()
