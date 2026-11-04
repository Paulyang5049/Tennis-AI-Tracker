# Usage guide

Detailed instructions for the desktop app, the command line, Colab training and evaluation. For a quick start, see the [README](../README.md). For the iPhone developer build, see [ios/README.md](../ios/README.md).

## Desktop app

Open http://127.0.0.1:7860 after `tennis-ai app`. Upload a video, select Singles or Doubles, and click **Analyze video**. The app runs one background job at a time to bound memory use. Cancel finishes the current inference call, then stops. Large videos stay on disk.

**Replay:** original and annotated videos synchronize playback, seeking and speed. The annotated player is muted to prevent doubled audio. The exact-frame reviewer below is authoritative for frame stepping. Select overlays without inference; click **Re-export from cached predictions** to regenerate downloads.

**Court correction:** show a frame, then click the original image's far-left, far-right, near-left, near-right *outer doubles-court corners*. Save the four corners. Corrections persist until a camera cut/movement or the next correction. Refresh the frame to clear an unfinished selection. Review updates immediately; re-export updates video/JSONL.

**Player labels:** inspect the frame's scene and player IDs. Enter a mapping such as `{"3": "Paul", "5": "Partner"}`. Labels apply to those track IDs within that scene. IDs reset after camera cuts; this is not cross-camera person recognition.

**Saved analyses and event review:** reopen completed runs or resume a paused job. Under event review, inspect candidates, correct times/types/player IDs, mark reviewed events, exclude false detections and export a selected interval with audio. Only reviewed, non-excluded events enter verified statistics; automatic candidates remain a separate count. Ball annotations distinguish a confirmed absence from an unlabelled frame. See [annotation and benchmark instructions](ANNOTATION.md).

**Custom weights:** unzip a Colab bundle into `models/`, enter its absolute folder in the app, and click its verification button. Both checksum and dependency compatibility are checked before inference. Only load checkpoints from a source you trust. Leave the fields blank to retain pretrained models.

## Installation details

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
.venv/bin/tennis-ai analyze path/to/video.mp4 --output outputs/gap-tolerant --event-detector contact-v2
.venv/bin/tennis-ai analyze path/to/video.mp4 --output outputs/strokes --event-detector contact-v2 --stroke-detector stroke-v1 --spin-detector wrist-v1
.venv/bin/tennis-ai resume outputs/my-match
.venv/bin/tennis-ai render outputs/my-match
.venv/bin/tennis-ai package outputs/my-match outputs/portable-match
.venv/bin/tennis-ai clip outputs/my-match --start 10 --end 18 --output outputs/rally.mp4
.venv/bin/tennis-ai benchmark benchmark.json --split test --output outputs/metrics.json
.venv/bin/tennis-ai evaluate outputs/my-match/frames.jsonl annotations.jsonl --output metrics.json
```

`--ball-model tracknet-v2` replaces the single-frame sports-ball detector with an opt-in three-frame TrackNet heatmap model, which is designed for small, fast balls. Run `tennis-ai setup --with-tracknet` first; it downloads third-party code and weights without a licence for local use only (see [THIRD_PARTY.md](../THIRD_PARTY.md)). It has not been evaluated in this project.

`--event-detector contact-v2` selects an experimental hit-candidate detector that tolerates frames where the ball is not observed at contact. It has not been validated against labelled contacts, so `baseline-v1` remains the default. See [VALIDATION.md](../VALIDATION.md).

An analysis folder contains:

| File | Purpose |
|---|---|
| `manifest.json` | Package version (v2 or v3), relative paths, source hash, media coordinates and model provenance |
| `events.json` | Candidate and reviewed hit, bounce and rally events |
| `annotated.mp4` | Timestamped H.264 replay with source audio encoded to AAC |
| `frames.jsonl` | Final per-frame detections, court, pose, player labels and ball status |
| `summary.json` | Settings, versions, status, runtime, observed/interpolated ball coverage and court availability |
| `cache.sqlite` | Raw predictions for inference-free re-rendering |
| `review.sqlite` | Indexed corrected records for exact-frame review |
| `corrections.json` | Optional per-frame court correction and per-scene player labels |

New analyses copy the original video into their folder; moving the entire folder preserves access. Legacy runs with external media can be converted with `package` while their source is still available. Re-export verifies the source SHA-256. Resume validates source, settings, model weights, code and runtime versions, then restores predictions and tracker state from the last committed checkpoint; up to 29 uncommitted frames may be recomputed. A changed analysis environment requires a new run.

## Google Colab

Open either notebook from the `notebooks/` folder and select a GPU runtime. The notebook installs the versioned project wheel from the GitHub release.

1. `01_train_ball_yolo26.ipynb`: download/audit the 578-image ball dataset, inspect labels, smoke-test training, fine-tune YOLO26s at 1280 px, compare against the COCO sports-ball baseline and export a bundle.
2. `02_finetune_court.ipynb`: download/audit court data, verify pretrained inference, optionally fine-tune the original heatmap model and export a court bundle.

Data and active training are on `/content`; resumable checkpoints and final bundles go to `MyDrive/TennisAI`. Ball defaults: 100 maximum epochs, patience 20, batch 4 with 2/1 retries for CUDA memory errors. Use `RESUME=True` in the ball notebook after a runtime disconnect. Court resumes from its Drive optimizer/epoch checkpoint automatically.

The `v0.2.0` release includes an experimental ball bundle from a completed Tesla T4 run. It improved recall on the validation split but failed the untouched test split and produced more false detections, so the app continues to use the COCO sports-ball model by default. The bundle is published to make the result reproducible and to give contributors a concrete baseline for improving data splits, labels and training settings.

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
- **Events and miniature court:** ground-contact estimates from ankles or box bottoms. An airborne ball is not projected as a landing point. Heuristic candidates propose hits, bounces and rallies without verified accuracy. Five stroke labels can be assigned manually; automatic strokes remain `unknown` unless the opt-in `stroke-v1` candidates are selected. Only confirmed ground-contact locations appear in landing statistics. Scoring, measured ball speed and coaching diagnosis are not implemented.
- **Video:** each decoded frame is processed, source presentation timestamps are normalized to start at zero and preserved to 1/90,000 second resolution in output. Audio is re-encoded, not bit-identical. Original orientation should be baked into pixels; rotated phone video is handled as described in the validation report. Full-court views are the target; cut detection is heuristic and can miss dissolves or rapid pans.

## Accuracy evaluation

Coverage is *not* accuracy. No accuracy metric is fabricated from confidence scores. Supply held-out annotated JSONL, one line per labeled frame:

```json
{"frame": 42, "category": "phone-doubles", "ball": [621, 310], "players": [{"id": "near-left", "box": [100, 200, 180, 430]}], "rackets": [[165, 255, 205, 305]]}
```

Omit unlabelled fields. `"ball": null` means a confirmed absence. `court`, when supplied, is 14 `[x,y]` points or null entries in upstream order. Record ground-truth player identities consistently across a scene. Use categories such as `phone-singles`, `phone-doubles`, `broadcast-singles`, `broadcast-doubles` and run each clip separately.

The evaluator reports observed-ball precision/recall at a configurable pixel tolerance (default 6 px; scale for your resolution), racket recall at IoU 0.5, matched-player ID switches, and median court-point error. Pair these with coverage and runtime from the run summary. Missing annotation fields produce null metrics. Sparse annotations can undercount ID switches. Test separate phone/broadcast clips with occlusions, far-court balls, spare balls, spectators and camera cuts. Promote a ball candidate only when held-out observed coverage improves without more false detections. The match-level protocol is in [EVALUATION_PROTOCOL.md](EVALUATION_PROTOCOL.md).

## Label contacts and spin on your own clips

A quick way to measure hit and spin candidates on your own short clips. Analyze each clip into a folder named after the clip, then write a blank sheet:

```sh
.venv/bin/python scripts/contact_labels.py template labels.csv 1 2 3
```

Watch each clip **without the overlays** and add one row per racket contact: `clip`, `time_s` (contact time in seconds), `side` (`near` or `far`), `stroke` (`serve`, `forehand`, `backhand`, `volley`, `overhead` or blank), `spin` (`topspin`, `slice`, `flat` or blank) and an optional note. Older sheets without a `stroke` column still work. Every listed clip is treated as fully labelled, so a clip with no rows has no hits. Then score the cached analyses:

```sh
.venv/bin/python scripts/contact_labels.py score labels.csv outputs --stroke-detector stroke-v1 --spin-detector wrist-v1
```

The report gives hit precision and recall at 0.1 s and 0.2 s for `baseline-v1` and `contact-v2`, and how often the stroke and spin candidates agree with your labels on matched hits (`correct`, `wrong` or `abstained`). `technique_on_matched_hits` scores the forehand/backhand × topspin/slice/flat pair, such as a backhand slice, and `technique_confusion` lists which pairs were mistaken for which. This is a development check on your clips, not the frozen match-level benchmark in [EVALUATION_PROTOCOL.md](EVALUATION_PROTOCOL.md).

`--spin-detector wrist-v1` on `analyze` adds the same unvalidated spin candidates to automatic hits. It reads the hitter's wrist height relative to the shoulder line around contact: high to low suggests slice, low to high topspin. Serves, overheads and unclear swings stay `unknown`, and reviewed or manual hits are never changed.

`--stroke-detector stroke-v1` on `analyze` (or **Stroke type candidates** in the desktop app) suggests a stroke for automatic hits:

- `serve`: a wrist far above the shoulders at the opening hit, away from the net
- `volley`: within 6.9 m of the net with no bounce candidate since the opponent's shot
- `forehand` / `backhand`: the side where the incoming ball passes the player, checked against the swing direction
- `unknown`: weak or contradicting cues, and overheads that are not an opening hit

It assumes right-handed players, so a left-handed player's forehands and backhands come out swapped. Review reports count each forehand/backhand × topspin/slice/flat pair as `technique.<stroke>.<spin>`. Like every candidate, these enter human-verified statistics only after review.

## Checks

```sh
.venv/bin/ruff check src scripts tests
.venv/bin/ruff format --check src scripts tests
.venv/bin/mypy src
.venv/bin/pytest -q
swift test --package-path ios
```

See [VALIDATION.md](../VALIDATION.md) for the exact checks run and what remains unverified, and [THIRD_PARTY.md](../THIRD_PARTY.md) for sources and reuse boundaries.
