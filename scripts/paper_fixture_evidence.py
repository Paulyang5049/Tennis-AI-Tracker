"""Reproduce the manuscript's synthetic review-policy example from shared fixtures."""

import json
import sys
from pathlib import Path

from tennis_ai.evidence import load_evidence
from tennis_ai.review_statistics import review_report

ROOT = Path(__file__).resolve().parents[1] / "contracts/fixtures/v3"


def metric(graph, view, name, participant_id=None):
    report = review_report(graph, view=view, participant_id=participant_id, end=5)
    row = next(item for item in report["metrics"] if item["id"] == name)
    return {
        "value": row["value"],
        "sample_count": row["sample_count"],
        "event_ids": row["event_ids"],
        "support_refs": row["support_refs"],
        "exclusions": row["exclusions"],
    }


def main():
    uncertain = load_evidence(ROOT / "uncertain")
    full = load_evidence(ROOT / "full")
    before = metric(full, "human_verified", "landings", "self")
    full["events"]["links"][0]["reviewed"] = False
    after = metric(full, "human_verified", "landings", "self")
    assisted_after = metric(full, "assisted", "landings", "self")

    # These checks make changes in the underlying fixture visible before a paper update.
    assert metric(uncertain, "assisted", "hits")["value"] == 1
    assert metric(uncertain, "human_verified", "hits")["value"] is None
    assert before["value"] == 1 and before["support_refs"] == [
        "bounce-1",
        "link:link-1",
    ]
    assert after["value"] is None and assisted_after["value"] == 1

    result = {
        "scope": "synthetic shared fixtures; no video or independent reviewer outcome",
        "uncertain": {
            "assisted_hits": metric(uncertain, "assisted", "hits"),
            "human_verified_hits": metric(uncertain, "human_verified", "hits"),
        },
        "full_link_retraction": {
            "human_verified_landings_before": before,
            "human_verified_landings_after": after,
            "assisted_landings_after": assisted_after,
        },
    }
    sys.stdout.write(json.dumps(result, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
