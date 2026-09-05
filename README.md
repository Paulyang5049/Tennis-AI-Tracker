# Tennis AI · Local

[![Tests](https://github.com/Paulyang5049/tennis-ai-local/actions/workflows/test.yml/badge.svg)](https://github.com/Paulyang5049/tennis-ai-local/actions/workflows/test.yml)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](LICENSE)
[![Open Ball Training in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/Paulyang5049/tennis-ai-local/blob/main/notebooks/01_train_ball_yolo26.ipynb)

A private, local-first YOLO26 tennis-video analysis and replay app for Apple Silicon and CPU, with portable Google Colab training notebooks. It supports selectable two-player or four-player analysis for full-court phone and broadcast footage. Processing is offline rather than real time.

## Why this project exists

Tennis is more than points and statistics. A recording can preserve a match, a friendship, a difficult training day and the small improvements that accumulate over time.

Tennis AI Local hopes to help tennis lovers record those moments and understand their game without sending personal videos to a server. It also gives developers an open foundation for experimenting with ball tracking, player pose, racket detection and court geometry. The long-term goal is a community-built tool that helps players revisit their tennis life and make thoughtful improvements to their performance.

This is an early-stage project, and contributions from players, coaches, computer-vision researchers, designers and developers are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for useful first contributions.

## What it can do

- Track a tennis ball and render a timestamp-aware trail.
- Detect and track two or four players.
- Draw body poses, rackets and reconstructed court lines.
- Project player ground positions onto a miniature court.
- Review exact frames, correct court corners and label players.
- Export an annotated video, structured frame data and a run summary.
- Train a dedicated YOLO26 tennis-ball detector in Google Colab.

## Start on this Mac

Clone the repository, then from the project folder:

```sh
git clone https://github.com/Paulyang5049/tennis-ai-local.git
cd tennis-ai-local
brew install ffmpeg uv
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -e '.[dev]'
.venv/bin/tennis-ai setup
.venv/bin/tennis-ai app
```

Open http://127.0.0.1:7860. Upload a video, select Singles or Doubles, and click **Analyze video**. The app runs one background job at a time to bound memory use. Cancel finishes the current inference call, then stops. Large videos stay on disk.

**Replay:** original and annotated videos synchronize playback, seeking and speed. The annotated player is muted to prevent doubled audio. The exact-frame reviewer below is authoritative for frame stepping. Select overlays without inference; click **Re-export from cached predictions** to regenerate downloads.

**Court correction:** show a frame, then click the original image's far-left, far-right, near-left, near-right *outer doubles-court corners*. Save the four corners. Corrections persist until a camera cut/movement or the next correction. Refresh the frame to clear an unfinished selection. Review updates immediately; re-export updates video/JSONL.

**Player labels:** inspect the frame's scene and player IDs. Enter a mapping such as `{"3": "Paul", "5": "Partner"}`. Labels apply to those track IDs within that scene. IDs reset after camera cuts; this is not cross-camera person recognition.

**Custom weights:** unzip a Colab bundle into `models/`, enter its absolute folder in the app, and click its verification button. Both checksum and dependency compatibility are checked before inference. Only load checkpoints from a source you trust. Leave the fields blank to retain pretrained models.

## Reproduce installation

Requires Python 3.11, 3.12 or 3.13 and FFmpeg on your path. Python 3.11 is the tested local environment; the training workflow is also exercised with Python 3.13 in Colab.

```sh
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -e '.[dev]'
.venv/bin/tennis-ai setup
.venv/bin/tennis-ai app
```

`setup` downloads YOLO26s detection, YOLO26s pose, the specialist court checkpoint and its original architecture. Assets are stored only in ignored `models/` and `external/` folders. Checksums and source revision are recorded in `models/provenance.json`. If the court download is unavailable, run `setup --without-court` and use manual calibration.

For a different working directory, pass `--root /absolute/path/to/AI_tennis` **before** the command. `auto` chooses CUDA, then MPS, then CPU. An MPS runtime error triggers a logged CPU retry; select CPU explicitly to diagnose GPU problems. Model downloads happen during setup, not normal analysis.

## Command line

```sh
.venv/bin/tennis-ai analyze path/to/video.mp4 --output outputs/my-match --players 4
.venv/bin/tennis-ai analyze path/to/video.mp4 --output outputs/custom-match --ball-bundle models/ball-bundle
.venv/bin/tennis-ai render outputs/my-match
.venv/bin/tennis-ai evaluate outputs/my-match/frames.jsonl annotations.jsonl --output metrics.json
```

An analysis folder contains:

| File | Purpose |
|---|---|
| `annotated.mp4` | Timestamped H.264 replay with source audio encoded to AAC |
| `frames.jsonl` | Final per-frame detections, court, pose, player labels and ball status |
| `summary.json` | Settings, versions, status, runtime, observed/interpolated ball coverage and court availability |
| `cache.sqlite` | Raw predictions for inference-free re-rendering |
| `review.sqlite` | Indexed corrected records for exact-frame review |
| `corrections.json` | Optional per-frame court correction and per-scene player labels |

The original video must remain at its recorded location. Re-export verifies its SHA-256 before using predictions. A completed export is replaced only after the new render finishes. Cancelled inference leaves a partial cache for diagnosis; start a new analysis folder to retry. Resuming local inference is not implemented.

## Google Colab

Use the Colab badge above or open either notebook from the `notebooks/` folder. Select a GPU runtime. The notebook installs the versioned project wheel from the GitHub release.

1. `01_train_ball_yolo26.ipynb`: download/audit the 578-image ball dataset, inspect labels, smoke-test training, fine-tune YOLO26s at 1280 px, compare against the COCO sports-ball baseline and export a bundle.
2. `02_finetune_court.ipynb`: download/audit court data, verify pretrained inference, optionally fine-tune the original heatmap model and export a court bundle.

Data and active training are on `/content`; resumable checkpoints and final bundles go to `MyDrive/TennisAI`. Ball defaults: 100 maximum epochs, patience 20, batch 4 with 2/1 retries for CUDA memory errors. Use `RESUME=True` in the ball notebook after a runtime disconnect. Court resumes from its Drive optimizer/epoch checkpoint automatically.

The `v0.2.0` release includes an experimental ball bundle from a completed Tesla T4 run. It improved recall on the validation split but failed the untouched test split and produced more false detections, so the app continues to use the COCO sports-ball model by default. The bundle is published to make the result reproducible and to give contributors a concrete baseline for improving data splits, labels and training settings. See [VALIDATION.md](VALIDATION.md) for the measured results.

The wheel pins the same PyTorch/Ultralytics versions used locally. If Colab replaces an already imported dependency, restart the runtime and continue after installation. GPU quota or download availability may stop a training run; the local baseline does not depend on training success.

To regenerate deliverables after code changes:

```sh
.venv/bin/python scripts/build_notebooks.py
uv build --wheel --out-dir colab_delivery
```

## Models and limitations

- **Players/rackets:** pretrained YOLO26s at 1280 px; ByteTrack tracks person detections. Court-region filtering and a stable-ID preference select up to two/four players. Spectators near a court can still be selected; labels do not fix incorrect detections.
- **Body:** YOLO26s-pose at 640 px, matched one-to-one by box overlap. Missing/low-confidence joints are not drawn.
- **Ball:** pretrained sports-ball class until a custom single-class YOLO26s bundle is selected. A motion/position gate chooses one ball; stationary spare balls and tiny far-court balls remain difficult.
- **Court:** 14 keypoints from the original 15-channel heatmap model, RANSAC geometry fit, recalibration at least once per second and after camera movement/cuts. Manual geometry is available when the model cannot fit.
- **Ball gaps:** only gaps bounded by observations within 100 ms, within one scene, are interpolated. Hollow yellow dots mean inferred points; unknown intervals are never joined.
- **Miniature court:** ground-contact estimates from ankles or box bottoms. An airborne ball is not projected as a landing point. No bounce detection, stroke classification, scoring, measured ball speed or coaching diagnosis is claimed.
- **Video:** each decoded frame is processed, source presentation timestamps are normalized to start at zero and preserved to 1/90,000 second resolution in output. Audio is re-encoded, not bit-identical. Original orientation should be baked into pixels; rotated phone video is handled as described in the validation report. Full-court views are the target; cut detection is heuristic and can miss dissolves or rapid pans.

## Accuracy evaluation

Coverage is *not* accuracy. No accuracy metric is fabricated from confidence scores. Supply held-out annotated JSONL, one line per labeled frame:

```json
{"frame": 42, "category": "phone-doubles", "ball": [621, 310], "players": [{"id": "near-left", "box": [100, 200, 180, 430]}], "rackets": [[165, 255, 205, 305]]}
```

Omit unlabelled fields. `"ball": null` means a confirmed absence. `court`, when supplied, is 14 `[x,y]` points or null entries in upstream order. Record ground-truth player identities consistently across a scene. Use categories such as `phone-singles`, `phone-doubles`, `broadcast-singles`, `broadcast-doubles` and run each clip separately.

The evaluator reports observed-ball precision/recall at a configurable pixel tolerance (default 6 px; scale for your resolution), racket recall at IoU 0.5, matched-player ID switches, and median court-point error. Pair these with coverage and runtime from the run summary. Missing annotation fields produce null metrics. Sparse annotations can undercount ID switches. Test separate phone/broadcast clips with occlusions, far-court balls, spare balls, spectators and camera cuts. Promote a ball candidate only when held-out observed coverage improves without more false detections.

## Checks

```sh
.venv/bin/ruff check src scripts tests
.venv/bin/ruff format --check src scripts tests
.venv/bin/mypy src
.venv/bin/pytest -q
```

See `VALIDATION.md` for the exact checks run and what remains unverified. See `THIRD_PARTY.md` for sources and reuse boundaries.

## Contributing and community

If you play tennis, a carefully described failure case is valuable even if you do not write code. If you develop software or work in computer vision, the roadmap includes better small-ball recall, stable doubles identities, phone-camera court calibration, contact timing, bounce detection and useful performance summaries.

Please open a focused issue before a large change. Do not upload private match footage without every identifiable participant's permission. Contribution instructions, dataset rules and the project conduct policy are in [CONTRIBUTING.md](CONTRIBUTING.md) and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

Tennis AI Local is released under GNU AGPL v3. The downloaded models, datasets and third-party repositories keep their own terms; see [THIRD_PARTY.md](THIRD_PARTY.md).
