import csv

import pytest
from test_contact_candidates import GAP_AT_CONTACT, rows

from tennis_ai.contact_labels import read_labels, score, write_template
from tennis_ai.events import new_event


def test_template_round_trips_and_blank_rows_mean_no_hits(tmp_path):
    sheet = tmp_path / "labels.csv"
    write_template(sheet, ["1", "2"])
    assert read_labels(sheet) == {}
    with sheet.open("a", newline="") as stream:
        csv.writer(stream).writerow(["1", "0.45", "near", "backhand", "slice", ""])
    labels = read_labels(sheet)
    assert [(e["start"], e["stroke"], e["spin"]) for e in labels["1"]] == [
        (0.45, "backhand", "slice")
    ]
    # An older sheet without a stroke column still reads.
    sheet.write_text("clip,time_s,side,spin,note\n1,0.45,near,slice,\n")
    assert read_labels(sheet)["1"][0]["stroke"] == "unknown"


def test_stroke_column_is_read_and_validated(tmp_path):
    sheet = tmp_path / "labels.csv"
    sheet.write_text("clip,time_s,side,stroke,spin,note\n1,0.4,near,backhand,slice,\n")
    assert read_labels(sheet)["1"][0]["stroke"] == "backhand"
    sheet.write_text("clip,time_s,side,stroke,spin,note\n1,0.4,near,lob,,\n")
    with pytest.raises(ValueError):
        read_labels(sheet)


def test_invalid_labels_are_rejected(tmp_path):
    sheet = tmp_path / "labels.csv"
    sheet.write_text("clip,time_s,side,spin,note\n1,0.4,middle,slice,\n")
    with pytest.raises(ValueError):
        read_labels(sheet)
    sheet.write_text("clip,time_s,side,spin,note\n1,0.4,near,backspin,\n")
    with pytest.raises(ValueError):
        read_labels(sheet)


def test_score_counts_matches_per_detector_and_tolerance(tmp_path):
    sheet = tmp_path / "labels.csv"
    sheet.write_text("clip,time_s,side,spin,note\nA,0.42,near,slice,\nA,2.0,far,,\n")
    frames = rows(GAP_AT_CONTACT)
    report = score(read_labels(sheet), ["A"], lambda clip: frames, ["contact-v2"])
    loose = report["contact-v2"]["0.1"]
    assert (loose["tp"], loose["fp"], loose["fn"]) == (1, 0, 1)
    assert loose["recall"] == 0.5
    assert loose["spin_on_matched_hits"] == {"abstained": 1}
    assert loose["stroke_on_matched_hits"] == {}
    assert loose["technique_confusion"] == {}


def test_score_reports_stroke_and_technique_agreement():
    labels = {"A": [new_event("hit", 0.42, stroke="backhand", spin="slice")]}
    frames = rows(GAP_AT_CONTACT)
    report = score(labels, ["A"], lambda clip: frames, ["contact-v2"], stroke_detector="stroke-v1")
    loose = report["contact-v2"]["0.1"]
    # The synthetic tracks carry no pose or court position, so stroke-v1 abstains.
    assert loose["stroke_on_matched_hits"] == {"abstained": 1}
    assert loose["technique_on_matched_hits"] == {"abstained": 1}
    assert loose["technique_confusion"] == {"backhand/slice -> unknown": 1}
