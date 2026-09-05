"""Fetch upstream assets to ignored local folders, with provenance."""

import json
import urllib.request
from pathlib import Path

from tennis_ai.artifacts import sha256

COURT_COMMIT = "e5cd4f1ce26b15361700d3d89e068cbf0e82749e"
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


def setup(root, include_court=True):
    from ultralytics import YOLO
    from ultralytics.utils.downloads import attempt_download_asset

    root = Path(root).resolve()
    folder = root / "models"
    folder.mkdir(parents=True, exist_ok=True)
    provenance = {}
    for name in ["yolo26s.pt", "yolo26s-pose.pt"]:
        path = folder / name
        if not path.exists():
            attempt_download_asset(str(path))
        YOLO(str(path))  # Verify checkpoint deserialization before reporting success.
        provenance[name] = {"sha256": sha256(path), "source": "Ultralytics release assets"}
    if include_court:
        architecture = root / "external" / "TennisCourtDetector" / "tracknet.py"
        download(
            f"https://raw.githubusercontent.com/yastrebksv/TennisCourtDetector/{COURT_COMMIT}/tracknet.py",
            architecture,
        )
        path = folder / "court.pt"
        if not path.exists():
            import gdown

            part = path.with_suffix(".part")
            try:
                result = gdown.download(
                    id="1f-Co64ehgq4uddcQm1aFBDtbnyZhQvgG", output=str(part), quiet=False
                )
                if not result:
                    raise RuntimeError(
                        "Court download unavailable; manual calibration remains usable"
                    )
                import torch

                torch.load(part, map_location="cpu", weights_only=True)
                part.replace(path)
            finally:
                part.unlink(missing_ok=True)
        provenance["court.pt"] = {
            "sha256": sha256(path),
            "upstream_commit": COURT_COMMIT,
            "architecture_sha256": sha256(architecture),
        }
    (folder / "provenance.json").write_text(json.dumps(provenance, indent=2))
    return provenance
