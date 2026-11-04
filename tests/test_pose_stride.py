import numpy as np
import pytest

from tennis_ai.models import in_reach
from tennis_ai.pipeline import Settings, analyze
from tennis_ai.video import VideoWriter


def clip(path, frames=7):
    writer = VideoWriter(path, 64, 64, 30)
    for index in range(frames):
        writer.write(np.zeros((64, 64, 3), dtype=np.uint8), index / 30)
    writer.close()
    return path


def adapter(calls):
    class Adapter:
        def __init__(self, *args, **kwargs):
            self.device, self.warnings = "cpu", []

        def reset(self):
            pass

        def court_geometry(self, frame):
            return None

        def infer(self, frame, court=None, **kwargs):
            calls.append(kwargs)
            return [], [], [], []

    return Adapter


def test_stride_requests_detail_on_schedule_and_default_keeps_old_calls(tmp_path):
    source = clip(tmp_path / "clip.mp4")
    calls: list[dict] = []
    analyze(source, tmp_path / "default", tmp_path, model_factory=adapter(calls))
    assert calls == [{}] * 7  # stride 1 keeps the original two-argument call
    calls.clear()
    analyze(
        source, tmp_path / "stride", tmp_path, Settings(pose_stride=3), model_factory=adapter(calls)
    )
    assert [c["detail"] for c in calls] == [True, False, False, True, False, False, True]


def test_ball_in_a_players_reach_forces_detail_and_strides_are_bounded():
    player = [900, 800, 1000, 1000]  # 200 px tall
    assert in_reach([1100, 900, 1110, 910], player)  # within 0.6 heights to the side
    assert in_reach([945, 705, 955, 715], player)  # just above the head
    assert not in_reach([945, 1010, 955, 1020], player)  # below the feet
    assert not in_reach([1300, 900, 1310, 910], player)
    for bad in (0, 11, True):
        with pytest.raises(ValueError):
            Settings(pose_stride=bad)
