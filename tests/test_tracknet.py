import numpy as np
import pytest
import torch

from tennis_ai.models import TrackNetBall, tracknet_point
from tennis_ai.pipeline import Settings, analyze
from tennis_ai.video import VideoWriter


def class_map(x=320, y=180, value=64, radius=4):
    """A 360 x 640 class map with one ball-like disc, as upstream argmax would produce."""
    yy, xx = np.mgrid[:360, :640]
    classes = np.zeros((360, 640), dtype=np.int64)
    classes[(xx - x) ** 2 + (yy - y) ** 2 <= radius**2] = value
    return classes


class FakeNet(torch.nn.Module):
    """Stands in for the downloaded network; puts the ball where the current frame is brightest."""

    def forward(self, x):
        current = x[0, :3].mean(dim=0)
        y, xpos = divmod(int(current.argmax()), 640)
        logits = torch.zeros(1, 256, 360 * 640)
        logits[0, 64] = torch.from_numpy(class_map(xpos, y).reshape(-1) > 0).float()
        return logits


def frame_with_dot(x, y, width=1280, height=720):
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[y - 3 : y + 4, x - 3 : x + 4] = 255
    return frame


def test_postprocess_scales_the_upstream_heatmap_to_frame_pixels():
    point = tracknet_point(class_map(320, 180), 1920, 1080)
    assert point is not None
    assert abs(point[0] - 960) <= 3 and abs(point[1] - 540) <= 3
    assert tracknet_point(np.zeros((360, 640), dtype=np.int64), 1920, 1080) is None


def test_detector_needs_three_frames_and_resumes_identically():
    detector = TrackNetBall(None, "cpu", net=FakeNet())
    assert detector.detect(frame_with_dot(400, 300)) == []
    assert detector.detect(frame_with_dot(420, 300)) == []
    box = detector.detect(frame_with_dot(440, 300))[0]["box"]
    assert abs((box[0] + box[2]) / 2 - 440) <= 4 and abs((box[1] + box[3]) / 2 - 300) <= 4
    resumed = TrackNetBall(None, "cpu", net=FakeNet())
    resumed.restore(detector.snapshot())
    nxt = frame_with_dot(460, 300)
    assert resumed.detect(nxt) == detector.detect(nxt)
    detector.reset()
    assert detector.detect(nxt) == []


def test_ball_model_settings_and_adapter_arguments(tmp_path):
    with pytest.raises(ValueError):
        Settings(ball_model="unversioned")
    with pytest.raises(ValueError):
        Settings(ball_model="tracknet-v2", ball_bundle="models/ball-bundle")
    received = []

    class Adapter:
        def __init__(self, *args, **kwargs):
            received.append(kwargs)
            self.device, self.warnings = "cpu", []

        def reset(self):
            pass

        def court_geometry(self, frame):
            return None

        def infer(self, frame, court=None):
            return [], [], [], []

    source = tmp_path / "clip.mp4"
    writer = VideoWriter(source, 64, 64, 30)
    for index in range(3):
        writer.write(np.zeros((64, 64, 3), dtype=np.uint8), index / 30)
    writer.close()
    analyze(source, tmp_path / "default", tmp_path, model_factory=Adapter)
    analyze(
        source,
        tmp_path / "tracknet",
        tmp_path,
        Settings(ball_model="tracknet-v2"),
        model_factory=Adapter,
    )
    assert received == [{}, {"ball_model": "tracknet-v2"}]
