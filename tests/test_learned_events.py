import pytest
from test_event_benchmark import bounce_clip
from test_pipeline import FakeModels, video  # noqa: F401

from tennis_ai.event_model import save_model, stream_events, train
from tennis_ai.events import new_event, place_bounces, propose_links
from tennis_ai.pipeline import Settings, analyze


@pytest.fixture
def weights(tmp_path):
    rows = [*bounce_clip(1), *bounce_clip(2), *bounce_clip(7)]
    net, thresholds = train([(rows, "truth")], [], epochs=40)
    path = tmp_path / "models" / "learned-events-v1.pt"
    path.parent.mkdir()
    save_model(path, net, thresholds, ["synthetic"])
    return path


def test_stream_events_resamples_60fps_and_scales_width(weights):
    frames = []
    for i in range(48):  # 0.8 s at 60 fps; the 30 fps V bounces at step 10 = 0.333 s
        step = i / 2
        y = 300 + 30 * (step if step <= 10 else 20 - step)
        frames.append(
            {
                "frame": i,
                "timestamp": i / 60,
                "scene": 0,
                "ball": {"status": "observed", "xy": [(600 + 5 * step) * 1.5, y * 1.5]},
                "players": [],
            }
        )
    events = stream_events(frames, weights, width=1920)
    bounces = [e for e in events if e["kind"] == "bounce"]
    assert bounces and abs(bounces[0]["start"] - 1 / 3) <= 2 / 30
    assert bounces[0]["confidence"] is None and bounces[0]["provenance"] == "automatic"


def test_bounce_landing_and_links_are_unreviewed_candidates():
    court = {"matrix": [[0.1, 0, 0], [0, 0.1, 0], [0, 0, 1]]}
    hit = new_event("hit", 1.0, 0, 30, player_id=1)
    bounce = new_event("bounce", 1.5, 0, 45)
    far = new_event("bounce", 9.0, 0, 270)
    reviewed = new_event("bounce", 1.6, 0, 48, reviewed=True)
    frames = [
        {"frame": 45, "scene": 0, "ball": {"status": "observed", "xy": [50, 120]}, "court": court},
        {"frame": 270, "scene": 0, "ball": {"status": "missing", "xy": None}, "court": court},
    ]
    place_bounces([hit, bounce, far, reviewed], frames)
    assert bounce["position"] == [5.0, 12.0]
    assert bounce["position_source"] == "automatic_bounce"  # Accepted by v3 evidence checks.
    assert far["position"] is None and reviewed["position"] is None
    links = propose_links([hit, bounce, far])
    assert [(link["shot_id"], link["bounce_id"], link["reviewed"]) for link in links] == [
        ("hit-0-30", "bounce-0-45", False)
    ]
    kept = [{"id": "x", "shot_id": "hit-0-30", "bounce_id": "bounce-0-45", "reviewed": True}]
    assert propose_links([hit, bounce], kept) == kept


def test_learned_detector_needs_local_weights_before_inference(tmp_path, video):  # noqa: F811
    settings = Settings(event_detector="learned-events-v1", auto_links="auto-v1")
    with pytest.raises(FileNotFoundError):
        analyze(video, tmp_path / "missing", tmp_path, settings, model_factory=FakeModels)
    with pytest.raises(ValueError):
        Settings(auto_links="other")


def test_pipeline_runs_learned_events_with_auto_links(tmp_path, video, weights):  # noqa: F811
    import json

    settings = Settings(event_detector="learned-events-v1", auto_links="auto-v1")
    output = tmp_path / "run"
    analyze(video, output, tmp_path, settings, model_factory=FakeModels)
    summary = json.loads((output / "summary.json").read_text())
    assert summary["status"] == "complete" and len(summary["event_model"]["sha256"]) == 64
    assert "links" in json.loads((output / "events.json").read_text())
