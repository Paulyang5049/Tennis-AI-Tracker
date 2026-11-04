# Validation report

Baseline local run: 2026-09-05 on an Apple M4 MacBook Air with 16 GB RAM, Python 3.11.15.

## Offline upgrade and interface checks — 2026-09-08 to 10

- Python: 72 tests passed; Ruff lint/format and mypy passed after integration.
- Desktop browser: actual upload, analysis, cancellation/resume, library refresh/reopen, synchronized replay, exact-frame images, player-label and four-corner saves, reviewed event persistence and MP4 clip download exercised. Automated integration tests separately verify audio preservation and portable cached re-export.
- Layout: 1440 px desktop and 390 px mobile have no horizontal overflow across the four sections. Keyboard focus is visible and moves from Analyze to Cancel; reduced-motion disables transitions. Light/dark rendering inspected, with no JavaScript errors in the exercised workflow. This is a scoped accessibility check, not a full assistive-technology audit.
- Real Apple MPS recovery: a 90-frame broadcast clip produced byte-identical `frames.jsonl` after interrupted/resumed versus uninterrupted analysis. This does not establish two-hour stability.
- Core ML: real YOLO26s 640 FP16 export, recursive checksum verification and macOS prediction passed. The bundled model also loaded and ran inside the iOS 27 simulator. No labelled parity or phone accuracy result exists.
- Swift: all 12 XCTest core tests passed using Xcode 27 beta (27A5252f); simulator and unsigned iOS device builds succeeded with minimum deployment target iOS 26. Only per-command `DEVELOPER_DIR` was set.
- Native simulator integration: `ios/check_simulator.py` builds an isolated check app using the production importer, engine, detector, SQLite store and clip exporter. A synthetic H.264 B-frame video with a sine audio track imported and analyzed all 12 frames; its 0.4-second export retained the full duration and one audio track. Review-frame access, reviewed-hit persistence and analysis-package export/re-import passed. A three-second excerpt of the supplied broadcast also passed with 179 decoded frames matching FFmpeg, a 2.1-second audio clip, and rejection of partial, missing-artifact and oversized imports. These checks fixed decoded timestamp origin and empty edit-list frame handling. Pose/racket ownership survives SQLite export, and verified statistics consistently require reviewed events.
- Native app launch succeeded in the iPhone 17 Pro / iOS 27 simulator. The integration check invokes production functions; it does not establish a completed tap-by-tap SwiftUI/file-picker workflow. That UI check, signed phone installation, performance, heat, battery and two-hour tests remain unverified.
- README: original banner, published UI screenshot, development UI screenshot and workflow illustration were pushed separately to main; all four images loaded on the actual GitHub page. The redesigned UI is explicitly labelled a development preview.
- Nine local review lenses and an independent 12-candidate validation batch returned results. The coordinator hit its account limit after validation; the primary agent completed synthesis and tested the final fixes. No external cross-model review ran. See `docs/reviews/full-feature-20260910-closure/review.json`.

## Full broadcast check — 2026-09-10

The user-supplied 11-minute-34-second clip completed desktop processing with 41,564 output frames and AAC audio. JSONL frame indices were contiguous and timestamps strictly increasing; the review database contained the same 41,564 unique frame indices. Browser reopening, synchronized playback and point-event export passed. The approximately four-second point clip retained audio.

Observed ball coverage was 49.56%, interpolated coverage 6.53%, and court calibration coverage 50.55%. The system produced 112 hit, 54 bounce and 24 rally candidates, all unreviewed, with zero confirmed events. Inspection found a ball false positive on the scoreboard serve icon and unstable player IDs; no labelled accuracy metric is available. Runtime recorded in the resumed summary is not the accumulated time across interruptions.

The [checked-in snapshot](docs/data/validation-2026-09-10.json) drives the README charts. The full source video, derived video and detailed local logs remain outside version control. iOS README screenshots use a separate solid-green UI fixture and do not represent this full-video run.

## Development-build visual report — 2026-09-10

The README charts and iOS screenshots were produced from [development revision 5c064e5](https://github.com/Paulyang5049/Tennis-AI-Tracker/tree/5c064e5/) of the offline upgrade. Python 72 tests and Swift 12 tests passed. Native integration on a real three-second excerpt retained 179 frames matching FFmpeg and a 2.1-second clip with audio. Signed-device performance and detection accuracy remain unverified.

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

## Gap-tolerant hit candidates — 2026-11-04

Thirteen user-supplied broadcast clips (two matches, 1920×1080 at 25 fps, 3,786 frames, all tagged as slice examples) were analysed with the default pipeline on an Apple M4 at about 7.3 frames per second. The clips and outputs remain outside version control. No human contact labels exist, so the figures below are development evidence, not accuracy.

- Ball positions: 128 randomly sampled observed positions were inspected; about 126 were the match ball. One run of six frames selected a spare ball held by a ball kid. No scoreboard false positive occurred.
- Contacts were approximated by trajectory changes between the near and far halves of the image. `baseline-v1` placed a hit candidate within those contact windows for 28 of 78 contacts in the tuning match and 6 of 23 in the other match. For most missed contacts the ball was unobserved for at least two of the seven frames around the contact.
- `contact-v2` (opt-in) covered 74 of 78 and 22 of 23 of the same windows, from cached frames. A visual check of 24 candidates found only by `contact-v2` judged 19 as real hits; the false ones were serve tosses at clip start and movement after a dead ball. Five of 103 consecutive hit pairs repeated the same player.
- Contact timing was not validated; far-court contacts may be offset by 0.1–0.3 s. The near-side confirmation line was tightened after a serve-toss false positive in the tuning match; the same failure also appeared in the other match, so it is not a fully untouched test.

## TrackNet ball model on the slice clips — 2026-11-04

The same 13 broadcast clips were analysed with `--ball-model tracknet-v2 --event-detector contact-v2` on the Apple M4, from the project on an external drive. Results compare against the earlier default runs; no human ball labels exist, so these are development observations, not accuracy.

- The ball was observed in 84.9% of 3,786 frames, against 80.0% with the default YOLO sports-ball detector. Where both observed a ball (2,768 frames), 96.9% of positions agreed within 15 pixels.
- In a visual check of 32 random frames where only TrackNet observed a ball, about 27 showed the match ball (often a motion-blurred streak or a ball against the net or advertising boards), 2 were white shoes, 2 were balls in the crowd or out of play, and 1 was unclear.
- `contact-v2` produced 104 hit candidates from TrackNet frames and placed a candidate within 95 of the 101 contact windows derived from the default trajectory.
- TrackNet analysis ran at 2.8 frames per second against 7.3 for the default, because it adds a full-resolution heatmap network per frame. It stays opt-in.
- The run exposed that Ultralytics strips apostrophes from weight paths, so a project under a folder such as "Paul's SSD" could not load any model. Weights are now passed through an apostrophe-free link.

## Stroke-type candidates on the slice clips — 2026-11-04

`stroke-v1` (opt-in) was applied to the 103 `contact-v2` hit candidates of the same 13 clips, from cached frames. It suggested 42 forehands, 35 backhands, 11 serves and 2 volleys, and left 13 unknown. No human stroke labels exist, so these are development observations, not accuracy.

- The coding assistant, not a coach or the player, inspected a five-frame strip from 0.3 s before to 0.3 s after every candidate and could judge 86 of them. The rule agreed on 80, left 5 unknown, and called one volley a forehand because the opponent's previous hit was more than 2 s earlier. None of the 86 received the wrong forehand, backhand or serve label. The other 17 were false hits, partly outside the frame or unclear.
- The thresholds were chosen after viewing the same strips, so this is tuning evidence, not held-out accuracy. A first version inferred handedness from the raised wrist at a serve. It swapped the forehands and backhands of four player tracks, because the toss arm is also raised. The rule now assumes right-handed players.
- With `wrist-v1` spin on the same hits: forehands 12 topspin, 3 slice, 27 unknown; backhands 7 topspin, 2 slice, 26 unknown. About seven hits looked like slices in the strips. `wrist-v1` called one of them slice and one topspin, and left five unknown. Of its six slice calls, one looked like a slice and one was a volley. Neither the wrist height path nor the detected racket box separated slice from topspin at this resolution, where players are about 80–250 pixels tall. Spin candidates stay unreliable until human labels exist to fit and test them.
