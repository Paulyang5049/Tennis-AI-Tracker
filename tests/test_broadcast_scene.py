import numpy as np
import pytest

from tennis_ai.geometry import COURT, CourtSmoother, _from_points
from tennis_ai.pipeline import Settings
from tennis_ai.tracking import SceneMonitor


def court(dx=0.0):
    points = COURT * 40 + np.array([200 + dx, 100])
    return _from_points(points, {"source": "model", "fit_error_px": 1.0})


def test_smoother_blends_agreeing_fits_and_needs_two_fits_to_jump():
    smoother = CourtSmoother()
    first = smoother.update(court(), 0.0)
    blended = smoother.update(court(4), 0.5)
    assert 0 < CourtSmoother.shift(blended, first) < 4 and blended["smoothed"]
    assert CourtSmoother.shift(smoother.update(court(60), 1.0), first) < 4  # one outlier
    assert CourtSmoother.shift(smoother.update(court(61), 1.5), court(61)) < 1e-3


def test_smoother_holds_briefly_then_forgets_and_resets_on_cut():
    smoother = CourtSmoother(hold=2.0)
    smoother.update(court(), 0.0)
    assert smoother.update(None, 1.0)["held"]
    assert smoother.update(None, 2.5) is None
    smoother.update(court(), 3.0)
    assert smoother.update(None, 3.1, cut=True) is None
    assert smoother.update(None, 3.2, moving=True) is None


def test_moving_camera_takes_each_fit():
    smoother = CourtSmoother()
    smoother.update(court(), 0.0)
    assert CourtSmoother.shift(smoother.update(court(50), 0.5, moving=True), court(50)) < 1e-3


def test_histogram_cut_catches_similar_brightness_shot_change():
    dark = np.full((90, 160, 3), 60, np.uint8)
    split = dark.copy()
    split[:, :80] = 30
    split[:, 80:] = 90  # same mean brightness, different distribution
    for version, expected in (("baseline-v1", False), ("broadcast-v1", True)):
        monitor = SceneMonitor(version)
        monitor.update(dark)
        assert monitor.update(split)[0] is expected
    with pytest.raises(ValueError):
        SceneMonitor("other")


def test_settings_accept_only_known_broadcast_scene():
    assert Settings(broadcast_scene="broadcast-v1").broadcast_scene == "broadcast-v1"
    with pytest.raises(ValueError):
        Settings(broadcast_scene="x")
