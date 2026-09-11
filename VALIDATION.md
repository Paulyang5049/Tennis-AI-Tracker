# Validation report

Last local run: 2026-09-05 on an Apple M4 MacBook Air with 16 GB RAM, Python 3.11.15.

## Development-build visual report — 2026-09-10

The README charts and iOS screenshots describe [development revision 5c064e5](https://github.com/Paulyang5049/Tennis-AI-Tracker/tree/5c064e5/), rather than main-branch functionality. Python 72 tests and Swift 12 tests passed. Native integration on a real three-second excerpt retained 179 frames matching FFmpeg and a 2.1-second clip with audio. Signed-device performance and detection accuracy remain unverified.

## Full broadcast check — 2026-09-10

The user-supplied 11-minute-34-second clip completed desktop processing with 41,564 output frames and AAC audio. JSONL frame indices were contiguous and timestamps strictly increasing; the review database contained the same 41,564 unique frame indices. Browser reopening, synchronized playback and point-event export passed. The approximately four-second point clip retained audio.

Observed ball coverage was 49.56%, interpolated coverage 6.53%, and court calibration coverage 50.55%. The system produced 112 hit, 54 bounce and 24 rally candidates, all unreviewed, with zero confirmed events. Inspection found a ball false positive on the scoreboard serve icon and unstable player IDs; no labelled accuracy metric is available. Runtime recorded in the resumed summary is not the accumulated time across interruptions.

The [checked-in snapshot](docs/data/validation-2026-09-10.json) drives the README charts. The full source video, derived video and detailed local logs remain outside version control. iOS README screenshots use a separate solid-green UI fixture and do not represent this full-video run.

## Verified locally

- YOLO26s detection, YOLO26s pose and the specialist 15-channel court checkpoint downloaded, deserialized and ran on Apple MPS. Their SHA-256 values are in `models/provenance.json`.
- A three-second, 1920×1080, 30 fps broadcast sample was processed through all 90 frames and exported through the command line. Inference took 11.8 seconds and rendering took 0.64 seconds on this machine.
- Visual inspection at frame 45 confirmed aligned court geometry, both selected players, both body poses, a racket box, ball trail and the miniature court. The output is `outputs/broadcast-verified/annotated.mp4`; `preview.jpg` is the inspected still.
- The browser workflow was exercised through upload → Analyze → completed replay/downloads → exact-frame review. It displayed all three deliverables and frame-level model data.
- A real YOLO26 single-class training smoke run completed on the audited ball dataset and produced `best.pt`. The deliberately tiny CPU smoke configuration (one epoch, 128 px, 2% of training data) verifies wiring and checkpoint creation; its zero mAP is not an accuracy result.
- The Colab-produced ball bundle passed its checksum, architecture, class-map, input-size and dependency compatibility checks locally. It also completed the same 90-frame broadcast sample on Apple MPS in 15.3 seconds.
- The public ball dataset download produced 578 readable labeled images, no exact decoded-pixel duplicates, and a grouped 468/60/50 train/validation/test split. The audit records that source-video identities remain unknown.
- Automated checks cover homography, bounded interpolation, cut resets, ball reacquisition, one-to-one pose matching, ambiguous rackets, disk-backed records, variable timestamps, phone rotation metadata, audio preservation, upload persistence, cancellation, atomic re-export, bundle integrity/version checks, dataset grouping, notebook syntax and evaluation semantics.

## Verified in Google Colab

- The ball notebook ran end to end on a Tesla T4 with Python 3.13.15, PyTorch 2.14.0, Ultralytics 8.4.140 and NumPy 2.4.6. This run established package support for Python 3.13.
- The audited dataset contained 468 training, 60 validation and 50 test images, with no exact decoded-pixel duplicates found. Source-video identities and possible near-duplicates remain unverified.
- YOLO26s trained at 1280 px with batch size 4. Early stopping ended the run after 43 epochs (0.527 hours); the best checkpoint came from epoch 23. Ultralytics' final best-checkpoint validation reported precision 0.187, recall 0.200, mAP50 0.0616 and mAP50-95 0.0123.
- The fixed 0.1-confidence, 0.5-IoU comparison found 17 true positives, 215 false positives and 43 false negatives for the candidate on validation, versus 0/66/60 for the COCO baseline. On the untouched test split, the candidate produced 0/34/50 versus the baseline's 2/21/48.
- The candidate therefore failed the promotion gate. The release bundle is an experimental reproducibility artifact; the COCO sports-ball detector remains the application default.

## Current measured sample output

The broadcast smoke run reported 73.3% observed-ball coverage, 13.3% interpolated coverage and 100% court-calibrated frames with the baseline. The experimental candidate reported 92.2% observed and 7.8% interpolated coverage on the same clip. These are availability measures, not accuracy; the candidate's failed held-out test prevents promotion. The source clip has no ground-truth annotations, so precision, recall, ID switches, racket recall and court-point error remain unreported.

## Needs external runtime or user footage

- Optional court fine-tuning still requires a Google Colab GPU and Google Drive. Its notebook is syntax-checked but has not been executed in Colab.
- Phone singles, phone doubles and broadcast doubles accuracy require representative videos plus held-out annotations. The included evaluator reports per-category results once those labels exist.
- The court dataset archive download and its redistribution terms were not independently confirmed. The notebook stops with a clear error and retains the pretrained model if the archive is unavailable.
- Scene-cut and camera-motion detection are heuristic. Dissolves, zooms and rapid pans need validation on the target footage.
