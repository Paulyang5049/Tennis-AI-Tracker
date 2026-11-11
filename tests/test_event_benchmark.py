import numpy as np

from tennis_ai.event_benchmark import evaluate, match, report, score
from tennis_ai.event_model import LearnedDetector, features, peaks, train


def bounce_clip(game, offset=0):
    """Ball falls, bounces at frame 10, rises; labelled bounce at frame 10."""
    rows = []
    for i in range(24):
        y = 300 + 30 * (i if i <= 10 else 20 - i)
        rows.append(
            {
                "game": game,
                "clip": "Clip1",
                "frame": f"{i:04d}.jpg",
                "visibility": 1,
                "status": "2" if i == 10 + offset else "0",
                "truth": [600.0 + 5 * i, float(y)],
                "selected": [600.0 + 5 * i, float(y)] if i % 7 else None,
                "candidates": [],
            }
        )
    return rows


def test_match_is_one_to_one_within_tolerance():
    assert match([10, 11, 30], [10, 29], 2) == [(0, 0), (2, 1)]
    assert match([5], [9], 2) == []


def test_baseline_bounce_is_scored_with_frame_tolerance():
    rows = bounce_clip(9)
    evaluated = evaluate(rows, [], "baseline-v1", "truth")
    totals = score([e[1:] for e in evaluated], 2)["bounce"]
    assert (totals["tp"], totals["fn"]) == (1, 0)
    assert totals["median_pixel_error"] <= 10
    assert totals["median_metre_error"] is None  # no court geometry, pixels only
    result = report(evaluated, "baseline-v1", "labelled ball")
    assert set(result["results"]["2f"]) == {"test"}


def test_features_keep_missing_observations_masked():
    points = [[100.0, 100.0], None, [110.0, 120.0]]
    rows = features(points, [[], [], []])
    assert rows.shape[0] == 3
    assert rows[1, -1] == 0.0  # centre frame unobserved


def test_peaks_suppress_neighbours():
    p = np.array([0.1, 0.6, 0.9, 0.7, 0.1, 0.1, 0.8])
    assert peaks(p, 0.5, 2) == [2, 6]


def test_learned_model_trains_on_train_games_and_tunes_on_val():
    rows = [*bounce_clip(1), *bounce_clip(2), *bounce_clip(7)]
    net, thresholds = train([(rows, "truth")], [], epochs=40)
    detector = LearnedDetector(net, thresholds)
    found = detector(bounce_clip(9), [], "truth")
    assert set(thresholds) == {"hit", "bounce"}
    assert any(abs(frame - 10) <= 2 for frame in found["bounce"])
