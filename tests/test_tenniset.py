import json

import pytest
from test_contact_candidates import GAP_AT_CONTACT, hits, rows

from tennis_ai.tenniset import candidate_frames, convert, match_windows, score


def tenniset(tmp_path, **classes):
    base = {
        "USE": [{"name": "0001", "start": 0, "end": 1000, "custom": {}}],
        "Point": [{"name": "0001", "start": 100, "end": 400, "custom": {"Score": "15-0"}}],
        "SPLITS": [{"name": "0001", "start": 0, "end": 1000, "custom": {"Type": "Train"}}],
        "Serve": [{"name": "0001", "start": 100, "end": 175, "custom": {"Player": "A"}}],
        "Hit": [
            {
                "name": "0001",
                "start": 160,
                "end": 188,
                "custom": {"Side": "Backhand", "Type": "Slice", "Player": "B"},
            },
            {
                "name": "0002",
                "start": 220,
                "end": 248.0,
                "custom": {"Side": "Forehand", "Type": "Volley", "Player": "A"},
            },
            {
                "name": "0003",
                "start": 600,
                "end": 628,
                "custom": {"Side": "Forehand", "Type": "Smash", "Player": "B"},
            },
        ],
    }
    path = tmp_path / "V001.json"
    path.write_text(json.dumps({"video": "data/videos/V001.mp4", "classes": {**base, **classes}}))
    return path


def test_convert_keeps_frame_windows_strokes_and_provenance(tmp_path):
    document = convert(tenniset(tmp_path))
    assert [
        (w["id"], w["start_frame"], w["end_frame"], w["stroke"]) for w in document["windows"]
    ] == [
        ("serve-0001", 100, 175, "serve"),
        ("hit-0001", 160, 188, "backhand"),
        ("hit-0002", 220, 248, "volley"),
        ("hit-0003", 600, 628, "overhead"),
    ]
    assert document["coverage_frames"] == [[0, 1000]]
    assert document["tenniset_splits"] == [{"split": "Train", "frames": [0, 1000]}]
    assert len(document["source"]["annotation_sha256"]) == 64
    assert any("not the contact frame" in text for text in document["limitations"])


def test_convert_requires_coverage(tmp_path):
    with pytest.raises(ValueError):
        convert(tenniset(tmp_path, USE=[], Match=[]))


def test_matching_is_one_to_one_and_maximal():
    windows = [{"start_frame": 0, "end_frame": 10}, {"start_frame": 5, "end_frame": 6}]
    assert match_windows([5, 8], windows) == [(0, 1), (1, 0)]
    assert match_windows([5, 5, 5], windows) == [(0, 1), (1, 0)]
    assert match_windows([11], windows) == []


def test_score_separates_misses_extra_candidates_and_uncovered_time(tmp_path):
    document = convert(tenniset(tmp_path))
    report = score(document, [170, 172, 230, 500, 1200])
    assert (report["tp"], report["fp"], report["fn"]) == (3, 1, 1)
    assert report["recall_by_kind"]["hit"] == {"windows": 3, "matched": 2, "recall": 0.667}
    assert report["recall_by_kind"]["serve"]["matched"] == 1
    assert report["fp_outside_points"] == 1
    assert report["outside_coverage_predictions"] == 1
    with pytest.raises(ValueError):
        score({**document, "version": 2}, [])


def test_candidate_times_map_to_analysis_frames():
    frames = rows(GAP_AT_CONTACT)
    found = hits(frames)
    assert len(found) == 1
    (frame,) = candidate_frames(found, frames)
    assert frames[frame]["timestamp"] == pytest.approx(found[0]["start"], abs=1 / 60)
    windows = {
        "format": "tenniset-contact-windows",
        "version": 1,
        "coverage_frames": [[0, 30]],
        "points_frames": [[0, 30]],
        "windows": [{"kind": "hit", "start_frame": 6, "end_frame": 18}],
    }
    assert score(windows, [frame])["tp"] == 1
