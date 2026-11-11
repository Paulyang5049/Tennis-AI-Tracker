"""Cut detection and court-calibration stability on the public TrackNet clips.

No cut or court labels exist, so both measures use structure the dataset guarantees:

- Each clip is one continuous camera shot. Joining a split's clips end to end puts a
  known shot change at every boundary; detections inside a clip are false cuts. A
  boundary between two rallies filmed from the same wide camera can look nearly
  identical, so boundary recall is a harsh lower bound, not a broadcast cut recall.
- The camera holds still inside every clip, so the true court never moves there. Any
  frame-to-frame keypoint shift of the court estimate is jitter, and frames without
  a court are coverage loss.

    python -m tennis_ai.scene_benchmark DATASET --root ROOT --output scene-report.json
"""

import argparse
import json
import statistics
from pathlib import Path

import cv2
import numpy as np

from tennis_ai.ball_benchmark import FPS, SPLITS, clips
from tennis_ai.geometry import CourtSmoother
from tennis_ai.tracking import CUT_DETECTORS, SceneMonitor

DEFINITION = "scene-public-v1"


def cut_scores(clip_frames, version):
    """clip_frames: list of frame lists (small images) in playback order."""
    monitor = SceneMonitor(version)
    boundaries = found = false = frames = 0
    for number, images in enumerate(clip_frames):
        for index, image in enumerate(images):
            cut, _ = monitor.update(image)
            if index == 0 and number > 0:
                boundaries += 1
                found += cut
            elif index > 0:
                frames += 1
                false += cut
    return {
        "boundaries": boundaries,
        "boundary_recall": found / boundaries if boundaries else None,
        "frames": frames,
        "false_cuts": false,
        "false_cuts_per_1000_frames": 1000 * false / frames if frames else None,
    }


def court_scores(fits_by_clip, smooth):
    """fits_by_clip: per clip, the raw automatic fit (or None) for every frame."""
    shifts, frames, covered, jumps = [], 0, 0, 0
    for fits in fits_by_clip:
        smoother = CourtSmoother() if smooth else None
        previous = None
        for index, fit in enumerate(fits):
            court = smoother.update(fit, index / FPS) if smoother else fit
            frames += 1
            if court is None:
                previous = None
                continue
            covered += 1
            if previous is not None:
                shift = CourtSmoother.shift(court, previous)
                shifts.append(shift)
                jumps += shift > 20
            previous = court
    return {
        "frames": frames,
        "coverage": covered / frames if frames else None,
        "median_jitter_px": statistics.median(shifts) if shifts else None,
        "p95_jitter_px": float(np.percentile(shifts, 95)) if shifts else None,
        "jumps_over_20px": jumps,
    }


def collect(dataset, games, models):
    """Small grayscale-ready frames for cut tests and raw court fits for every frame."""
    images, fits = [], []
    for _game, folder, labels in clips(dataset, games):
        clip_images, clip_fits = [], []
        for label in labels:
            frame = cv2.imread(str(folder / label["file name"]))
            if frame is None:
                raise ValueError(f"Unreadable frame {folder / label['file name']}")
            clip_images.append(cv2.resize(frame, (160, 90)))
            clip_fits.append(models.court_geometry(frame) if models else None)
        images.append(clip_images)
        fits.append(clip_fits)
    return images, fits


def save_cache(path, images, fits):
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, *[np.stack(clip) for clip in images])
    path.with_suffix(".fits.json").write_text(json.dumps(fits))


def load_cache(path):
    with np.load(path) as archive:
        images = [list(archive[f"arr_{i}"]) for i in range(len(archive.files))]
    return images, json.loads(path.with_suffix(".fits.json").read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("dataset")
    parser.add_argument("--root", default=str(Path.cwd()))
    parser.add_argument("--device", default="auto")
    parser.add_argument("--cache", help="Folder for reusable frames and raw court fits")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    from tennis_ai.models import Models

    models = Models(args.root, args.device)
    results = {}
    for split, games in SPLITS.items():
        cache = Path(args.cache) / f"{split}.npz" if args.cache else None
        if cache and cache.is_file():
            images, fits = load_cache(cache)
        else:
            images, fits = collect(args.dataset, games, models)
            if cache:
                save_cache(cache, images, fits)
        results[split] = {
            "cuts": {version: cut_scores(images, version) for version in CUT_DETECTORS},
            "court": {
                "raw": court_scores(fits, False),
                CourtSmoother.version: court_scores(fits, True),
            },
        }
        print(split, json.dumps(results[split]), flush=True)
    Path(args.output).write_text(
        json.dumps(
            {
                "schema_version": 1,
                "definition_version": DEFINITION,
                "dataset": "TrackNet tennis (10 broadcast games), local copy, not redistributed",
                "splits": {name: list(members) for name, members in SPLITS.items()},
                "results": results,
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
