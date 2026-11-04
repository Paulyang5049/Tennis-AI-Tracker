import json

import pytest

from tennis_ai.annotation import annotate_ball, export_event_annotations
from tennis_ai.package import atomic_json


def test_explicit_absence_and_unlabelled_frames_are_distinct(tmp_path):
    atomic_json(
        tmp_path / "summary.json",
        {
            "schema_version": 1,
            "frames": 100,
            "video": {"width": 320, "height": 180, "duration": 10},
        },
    )
    path = annotate_ball(tmp_path, 4, [30, 50], "far")
    annotate_ball(tmp_path, 7, None)
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert [r["frame"] for r in rows] == [4, 7]
    assert rows[1]["ball"] is None and rows[0]["distance"] == "far"
    with pytest.raises(ValueError):
        annotate_ball(tmp_path, 100, None)
    with pytest.raises(ValueError):
        annotate_ball(tmp_path, 3, [400, 50])
    with pytest.raises(ValueError, match="Confirm"):
        export_event_annotations(tmp_path, 0, 10)
    document = json.loads(export_event_annotations(tmp_path, 0, 10, True).read_text())
    assert document["coverage"]["hit"] == [[0, 10]]
    assert document["events"] == []
