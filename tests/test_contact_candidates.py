import json

import pytest

from tennis_ai.events import (
    ContactCandidateDetector,
    create_event_detector,
    generate_candidates,
)
from tennis_ai.pipeline import Settings

NEAR = {"id": 1, "box": [900, 800, 1000, 1000]}
FAR = {"id": 2, "box": [940, 300, 1000, 380]}


def frame(index, y, status="observed", x=950):
    return {
        "frame": index,
        "timestamp": index / 30,
        "scene": 0,
        "players": [NEAR, FAR],
        "rackets": [],
        "ball": {"status": status, "xy": None if status == "missing" else [x, y]},
    }


def rows(track):
    return [
        frame(i, y) if y is not None else frame(i, None, "missing") for i, y in enumerate(track)
    ]


# Approach the near player, lose the ball for eight frames at contact, then return it.
APPROACH = [500, 560, 620, 680, 720, 760, 800, 830, 850]
RETURN = [740, 650, 560, 470, 400, 360]
GAP_AT_CONTACT = APPROACH + [None] * 8 + RETURN


def hits(frames, detector="contact-v2"):
    return [e for e in generate_candidates(frames, detector) if e["kind"] == "hit"]


def test_hit_inside_unobserved_contact_frames_is_attributed_to_the_player():
    found = hits(rows(GAP_AT_CONTACT))
    assert hits(rows(GAP_AT_CONTACT), "baseline-v1") == []
    assert len(found) == 1
    hit = found[0]
    assert hit["player_id"] == 1
    assert hit["id"] == "hit-0-8"
    # Contact time lies between the last approach and first return observations.
    assert 8 / 30 < hit["start"] < 17 / 30
    assert hit["stroke"] == "unknown" and hit["position"] is None


def test_interpolated_samples_are_never_contact_evidence():
    frames = rows(GAP_AT_CONTACT)
    for index in range(9, 17):
        frames[index]["ball"] = {"status": "interpolated", "xy": [950, 860]}
    assert [e["start"] for e in hits(frames)] == [e["start"] for e in hits(rows(GAP_AT_CONTACT))]
    only_interpolated_return = rows(APPROACH + [None] * 8)
    only_interpolated_return += [
        {**frame(17 + i, y), "ball": {"status": "interpolated", "xy": [950, y]}}
        for i, y in enumerate(RETURN)
    ]
    assert hits(only_interpolated_return) == []


def test_serve_toss_and_a_ball_passing_a_player_are_not_hits():
    toss = [880, 820, 740, 660, 600, 570, 560, 580, 640, 720, 800]
    serve = [760, 640, 520, 440, 380]
    found = hits(rows(toss + serve))
    assert len(found) == 1
    assert found[0]["start"] > 6 / 30
    passing_far_player = [600, 520, 440, 380, 340, 310, 280, 250, 220]
    assert hits(rows(passing_far_player)) == []


def test_far_contact_needs_the_ball_to_come_back_past_the_net():
    # The image turn at a far contact is gradual; only the return direction confirms it.
    track = [600, 520, 450, 390, 350, 330, 320, 318, 322, 340, 380, 450, 540, 620, 700]
    found = hits(rows(track))
    assert len(found) == 1
    assert found[0]["player_id"] == 2


def test_cuts_reset_pending_contacts():
    frames = rows(GAP_AT_CONTACT)
    frames[17]["cut"] = True
    assert hits(frames) == []


def test_resume_matches_uninterrupted_run_and_state_is_bounded():
    frames = rows(GAP_AT_CONTACT + [None] * 3 + list(reversed(GAP_AT_CONTACT)))
    for index, record in enumerate(frames):
        record["frame"], record["timestamp"] = index, index / 30
    uninterrupted = list(generate_candidates(frames, "contact-v2"))
    for split in (5, 12, 20, 30):
        detector = ContactCandidateDetector()
        before = [e for record in frames[:split] for e in detector.feed(record)]
        state = json.loads(json.dumps(detector.state_dict()))
        detector = ContactCandidateDetector.from_state(state)
        after = [e for record in frames[split:] for e in detector.feed(record)]
        assert before + after + detector.finish() == uninterrupted
    held = ContactCandidateDetector()
    for index in range(200):
        held.feed(frame(index, 900))
    assert len(held.state_dict()["visit"]["samples"]) <= 40


def test_unknown_detector_versions_are_rejected():
    with pytest.raises(ValueError):
        create_event_detector("unversioned")
    with pytest.raises(ValueError):
        Settings(event_detector="unversioned")
    assert Settings().event_detector == "baseline-v1"


def test_shared_swift_fixture_is_current():
    import subprocess
    import sys
    from pathlib import Path

    script = Path(__file__).resolve().parents[1] / "scripts/build_contact_fixture.py"
    result = subprocess.run(
        [sys.executable, str(script), "--check"], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
