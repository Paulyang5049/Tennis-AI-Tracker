import json

import pytest

from tennis_ai.events import new_event
from tennis_ai.heldout_labels import add_label, init, load, report, segments, set_complete

COURT = {"matrix": [[0.01, 0, 0], [0, 0.01, 0], [0, 0, 1]]}


def write_analysis(folder, events):
    folder.mkdir()
    # 10 s at 10 fps: main view 0-4 s, a cut at 4 s, close-up 6-8 s (no court).
    with (folder / "frames.jsonl").open("w") as stream:
        for i in range(100):
            t = i / 10
            court = None if 60 <= i < 80 else COURT
            stream.write(json.dumps({"frame": i, "timestamp": t, "court": court, "cut": i == 40}))
            stream.write("\n")
    (folder / "summary.json").write_text(
        json.dumps({"source_sha256": "0" * 64, "video": {"fps": 10.0}})
    )
    (folder / "events.json").write_text(json.dumps({"schema_version": 2, "events": events}))


def test_segments_split_at_cuts_and_skip_close_ups(tmp_path):
    write_analysis(tmp_path / "run", [])
    found = segments(tmp_path / "run" / "frames.jsonl", min_seconds=1.5)
    assert [(s["first_frame"], s["last_frame"]) for s in found] == [(0, 39), (40, 59), (80, 99)]
    assert not any(s["complete"] for s in found)


def test_blind_labels_score_only_complete_segments(tmp_path):
    hit = new_event("hit", 1.0, 0, 10, stroke="forehand")
    bounce = new_event("bounce", 2.05, 0, 21)
    bounce["position"] = [5.0, 5.0]
    stray = new_event("bounce", 9.0, 0, 90)  # In a segment nobody completed.
    write_analysis(tmp_path / "run", [hit, bounce, stray])
    labels = tmp_path / "labels"
    found = init(tmp_path / "run", labels, min_seconds=1.5)
    first = found[0]["id"]
    with pytest.raises(ValueError):
        add_label(labels, first, 20, 2.0, "bounce")  # A bounce needs its pixel.
    with pytest.raises(ValueError):
        add_label(labels, first, 85, 8.5, "hit")  # Outside the segment.
    add_label(labels, first, 10, 1.0, "hit", "near", "backhand")
    add_label(labels, first, 20, 2.0, "bounce", xy=[500, 560])
    add_label(labels, first, 30, 3.0, "hit", "far", "forehand")
    set_complete(labels, first)
    assert len(load(labels)[1]) == 3
    result = report(labels)["results"]["2f"]
    assert result["segments"] == 1
    assert (result["hit"]["tp"], result["hit"]["fp"], result["hit"]["fn"]) == (1, 0, 1)
    assert (result["bounce"]["tp"], result["bounce"]["fp"]) == (1, 0)  # The stray is ignored.
    assert result["bounce"]["median_landing_error_m"] == pytest.approx(0.6, abs=1e-3)
    assert result["hit"]["stroke_classification"]["classes"]["backhand"]["support"] == 1
    with pytest.raises(FileExistsError):
        init(tmp_path / "run", labels)
