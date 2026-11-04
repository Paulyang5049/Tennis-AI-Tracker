"""Verify Swift reports against Python using the same portable evidence snapshots."""

import json
import sys
from pathlib import Path

from tennis_ai.evidence import load_evidence
from tennis_ai.review_statistics import review_report
from tennis_ai.schema import validate_schema


def main():
    root = Path(sys.argv[1])
    count = 0
    for name in ("minimal", "uncertain", "corrected", "full", "legacy-track"):
        folder = root / name
        fixtures = Path(__file__).resolve().parents[1] / "contracts/fixtures/v3"
        source = fixtures / ("full" if name == "legacy-track" else name)
        graph = load_evidence(source)
        if name == "legacy-track":
            graph["tracks"] = [
                json.loads(row)
                for row in (fixtures / "legacy-track.jsonl").read_text().splitlines()
            ]
        exported = load_evidence(folder)
        duration = json.loads((folder / "manifest.json").read_text())["media"]["duration"]
        for view in ("assisted", "human_verified"):
            swift = json.loads((folder / f"report-{view}.json").read_text())
            validate_schema("review-report-v1.schema.json", swift)
            python = review_report(graph, view=view, end=duration)
            assert swift == python, f"Report mismatch: {name}/{view}"
            assert swift == review_report(exported, view=view, end=duration)
            count += 1
    print(f"Python/Swift review report parity: {count} reports passed")


if __name__ == "__main__":
    main()
