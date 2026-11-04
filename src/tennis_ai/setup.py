"""Fetch upstream assets to ignored local folders, with provenance."""

import json
import shutil
import tempfile
import urllib.request
from pathlib import Path

from tennis_ai.artifacts import sha256, ultralytics_path

COURT_COMMIT = "e5cd4f1ce26b15361700d3d89e068cbf0e82749e"
TRACKNET_COMMIT = "730ea17a324321c553c480179caa8ff13e4cf553"
TRACKNET_WEIGHTS = "1XEYZ4myUN7QT-NeBYJI0xteLsvs-ZAOl"
BALL_COMMIT = "d557527793820f1e6b06872256824255facd47fd"


def download(url, destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    try:
        with urllib.request.urlopen(url, timeout=60) as source, temporary.open("wb") as target:
            while chunk := source.read(1024 * 1024):
                target.write(chunk)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def _download_drive(file_id, path, message):
    """Fetch a Google Drive checkpoint and verify it deserializes before keeping it."""
    import gdown
    import torch

    part = path.with_suffix(".part")
    try:
        if not gdown.download(id=file_id, output=str(part), quiet=False):
            raise RuntimeError(message)
        torch.load(part, map_location="cpu", weights_only=True)
        part.replace(path)
    finally:
        part.unlink(missing_ok=True)


def setup(root, include_court=True, include_tracknet=False):
    from ultralytics import YOLO
    from ultralytics.utils.downloads import attempt_download_asset

    root = Path(root).resolve()
    folder = root / "models"
    folder.mkdir(parents=True, exist_ok=True)
    provenance = {}
    for name in ["yolo26s.pt", "yolo26s-pose.pt"]:
        path = folder / name
        if not path.exists():
            # Download outside the project: Ultralytics mangles paths with apostrophes.
            with tempfile.TemporaryDirectory() as staging:
                shutil.move(attempt_download_asset(str(Path(staging) / name)), path)
        YOLO(ultralytics_path(path))  # Verify deserialization before reporting success.
        provenance[name] = {"sha256": sha256(path), "source": "Ultralytics release assets"}
    if include_court:
        architecture = root / "external" / "TennisCourtDetector" / "tracknet.py"
        download(
            f"https://raw.githubusercontent.com/yastrebksv/TennisCourtDetector/{COURT_COMMIT}/tracknet.py",
            architecture,
        )
        path = folder / "court.pt"
        if not path.exists():
            _download_drive(
                "1f-Co64ehgq4uddcQm1aFBDtbnyZhQvgG",
                path,
                "Court download unavailable; manual calibration remains usable",
            )
        provenance["court.pt"] = {
            "sha256": sha256(path),
            "upstream_commit": COURT_COMMIT,
            "architecture_sha256": sha256(architecture),
        }
    if include_tracknet:
        # Upstream has no licence file: download for local use only, never redistribute.
        architecture = root / "external" / "TrackNet" / "model.py"
        download(
            f"https://raw.githubusercontent.com/yastrebksv/TrackNet/{TRACKNET_COMMIT}/model.py",
            architecture,
        )
        path = folder / "tracknet_ball.pt"
        if not path.exists():
            _download_drive(TRACKNET_WEIGHTS, path, "TrackNet download unavailable")
        provenance["tracknet_ball.pt"] = {
            "sha256": sha256(path),
            "upstream_commit": TRACKNET_COMMIT,
            "architecture_sha256": sha256(architecture),
        }
    (folder / "provenance.json").write_text(json.dumps(provenance, indent=2))
    return provenance
