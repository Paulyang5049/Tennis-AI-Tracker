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

## Main-camera view filter on a full broadcast — 2026-11-10

`--view-filter main-view-v1` was applied to the cached frames of one full broadcast run (41,564 frames at 59.94 fps; footage and outputs stay outside version control). No event labels exist for this match, so these are development observations, not accuracy.

- A court calibration was present in 21,011 frames, grouped into 35 main-camera segments. The existing cut detector reported only 18 scenes, so it misses most cuts on this footage.
- Two contact sheets were inspected: 24 of 24 sampled frames with a court were the main camera; 22 of 24 sampled frames without a court were close-ups, replays or crowd shots, and 2 were main-camera frames the court model missed.
- With the filter, `baseline-v1` hit candidates fell from 112 to 40 and rallies from 24 to 10; `contact-v2` hit candidates fell from 220 to 166 and rallies from 37 to 27. Bounce candidates fell from 54 to 46 in both. Whether the removed candidates were false is not measured.

## Ball detectors on the public TrackNet dataset — 2026-11-11

`python -m tennis_ai.ball_benchmark` scored both ball detectors on the public TrackNet tennis dataset: 10 broadcast games, 95 rally clips, 19,835 frames at 1280×720 and 30 fps, one labelled ball point per frame (729 frames without a ball). The dataset stays local and is not redistributed; its readme states no licence. Whole games form the splits: games 1–6 train, 7–8 validation, 9–10 test. A prediction counts when it lies within the tolerance of the label; a wrong position is both a false positive and a miss. Each detector's candidates pass through the shipped `baseline-v1` ball selector without court geometry, so this is not the full pipeline.

| Detector | Split | Frames | Precision (5 px) | Recall (5 px) | Precision (10 px) | Recall (10 px) | Right point among candidates (5 px) |
|---|---|---:|---:|---:|---:|---:|---:|
| YOLO26s COCO sports ball (default) | train | 12,279 | 0.245 | 0.195 | 0.278 | 0.221 | 0.441 |
| | validation | 3,839 | 0.693 | 0.407 | 0.784 | 0.461 | 0.477 |
| | test | 3,717 | 0.553 | 0.338 | 0.581 | 0.355 | 0.476 |
| TrackNet (`tracknet-v2`, in-sample) | train | 12,279 | 0.972 | 0.936 | 0.995 | 0.958 | 0.939 |
| | validation | 3,839 | 0.968 | 0.919 | 0.994 | 0.943 | 0.926 |
| | test | 3,717 | 0.979 | 0.939 | 0.997 | 0.956 | 0.939 |

- **The TrackNet figures are in-sample and are not a held-out result.** The upstream training script shuffles the frames of all ten games before its 70/30 split, so the published weights (the same file as `models/tracknet_ball.pt`, by SHA-256) have probably seen every game. They show what the model does on footage like its training data, nothing more. A fair comparison needs labelled frames from other matches.
- The YOLO detector was never trained on this data, so its figures are clean. It finds the labelled point among its candidates in under half of the ball frames, and almost never when the label marks the ball as hard to see (43 of 277 test frames).
- In games 1 and 5 the selector locked onto a fixed on-screen object for nearly the whole game (0 correct of 1,920 ball frames in game 1) although the right point was among the candidates in 28% and 72% of frames. This is a selector failure, separate from detector recall; court geometry, which the pipeline normally supplies, was not available here.
- An opt-in selector, `--ball-tracker static-reject-v1`, drops any detection that stays in one 6-pixel cell for at least 10 frames and 0.3 s. Its thresholds were fixed before scoring; a sweep on the train and validation games showed nearby settings behave alike (a faster 6-frame setting scored about 0.015 F1 higher on train and was not adopted). The test games were scored once, after that. With the same YOLO detections at 5 px:

  | Selector | Train P / R | Validation P / R | Test P / R |
  |---|---:|---:|---:|
  | `baseline-v1` | 0.245 / 0.195 | 0.693 / 0.407 | 0.553 / 0.338 |
  | `static-reject-v1` | 0.782 / 0.407 | 0.790 / 0.450 | 0.775 / 0.428 |

  Recall now sits close to the detector's ceiling (0.441, 0.477 and 0.476), so what remains is detector recall. Game 1 went from 0 to 445 correct frames of 1,920. With TrackNet detections the two selectors score the same to within 0.001. The dataset is 30 fps rally clips only; the selector has not been run through the full pipeline, on 25 or 60 fps footage, or on whole broadcasts, so `baseline-v1` stays the default.
- On the Apple M4, YOLO ran at about 16 frames per second and TrackNet at about 4.5, reading images from an external drive.
- The labels also mark 516 hit frames and 523 bounce frames. They are used by the event benchmark below.

## Fine-tuned ball bundle on the public TrackNet dataset — 2026-11-11

`ball-v0.2.0-candidate` (YOLO26s fine-tuned on the Roboflow tennis-ball set, never on
TrackNet) was scored with `ball_benchmark --ball-bundle`. It never saw these games, so all
three splits are out-of-sample.

| Selector | Train P / R (5 px) | Validation P / R | Test P / R | Test P / R (10 px) | Right point among candidates (test, 5 px) |
|---|---:|---:|---:|---:|---:|
| `baseline-v1` | 0.551 / 0.431 | 0.342 / 0.234 | 0.659 / 0.615 | 0.716 / 0.668 | 0.804 |
| `static-reject-v1` | 0.811 / 0.521 | 0.740 / 0.399 | 0.853 / 0.763 | 0.941 / 0.841 | 0.804 |

- On the test games it beats the COCO detector with either selector (COCO with
  `static-reject-v1`: 0.775 / 0.428). The validation games are harder for it (candidate
  ceiling 0.437), so the gain is uneven across matches.
- It remains a candidate bundle: the in-sample TrackNet weights still score higher, and
  neither has a held-out result from other broadcasts.

## Hit and bounce candidates on the public TrackNet dataset — 2026-11-11

`python -m tennis_ai.event_benchmark` scores hit and bounce candidates against the dataset's
516 hit and 523 bounce frames, split by game as above. Players, poses, rackets and court
geometry were cached once with the pipeline's own models. A prediction matches a label
within ±2 frames (67 ms). The landing estimate is the observed ball pixel at the predicted
bounce frame, projected through the automatic court fit; the dataset has no court labels,
so metre errors inherit that fit's error. `learned-events-v1` (opt-in, candidates only)
was trained on games 1–6 with three ball sources (labelled, TrackNet and
`ball-v0.2.0` + `static-reject-v1`), its thresholds were picked on games 7–8, and the test
games 9–10 were scored once.

Test games, ±2 frames (93 hits, 99 bounces):

| Ball source | Detector | Hit P / R | Bounce P / R | Bounce within 0.5 m | Median landing error |
|---|---|---:|---:|---:|---:|
| Labelled ball | `baseline-v1` | 0.850 / 0.366 | 0.492 / 0.313 | 0.74 (31) | 0.12 m |
| | `contact-v2` | 0.762 / 0.516 | 0.492 / 0.313 | 0.74 (31) | 0.12 m |
| | `learned-events-v1` | 0.840 / 0.849 | 0.957 / 0.899 | 0.88 (89) | 0.00 m |
| `ball-v0.2.0` + `static-reject-v1` (clean) | `baseline-v1` | 0.694 / 0.269 | 0.583 / 0.283 | 0.71 (28) | 0.19 m |
| | `contact-v2` | 0.688 / 0.473 | 0.583 / 0.283 | 0.71 (28) | 0.19 m |
| | `learned-events-v1` | 0.621 / 0.634 | 0.857 / 0.848 | 0.81 (81) | 0.12 m |
| TrackNet (in-sample ball) | `baseline-v1` | 0.722 / 0.280 | 0.474 / 0.273 | 0.81 (27) | 0.12 m |
| | `contact-v2` | 0.730 / 0.495 | 0.474 / 0.273 | 0.81 (27) | 0.12 m |
| | `learned-events-v1` | 0.844 / 0.817 | 0.928 / 0.909 | 0.85 (89) | 0.10 m |

- The learned model roughly doubles bounce recall and lifts bounce precision on every ball
  source. With the labelled ball, a matched bounce's landing is the labelled point itself,
  so its zero median error measures only frame timing.
- **The plan's landing gate is not passed.** With the only clean ball source, bounce
  precision is 0.857 (gate 0.90). The TrackNet row passes on precision, but that ball
  detector was trained on these games. All rows are broadcast rally clips at 30 fps from
  one dataset; nothing here is a held-out broadcast result.
- Hits on the clean ball source stay weak (0.62 / 0.63): the ball is often lost near the
  far player.
- The weights stay local: the dataset has no licence.

## Learned events and automatic links on a full broadcast — 2026-11-11

`--event-detector learned-events-v1 --auto-links auto-v1` was run over the cached frames of
the full broadcast (41,564 frames at 59.94 fps, resampled to the model's 30 fps), with
`--view-filter main-view-v1`. No event labels exist for this match.

| Detector | Hits | Bounces | Rallies | Bounces with a landing | Landing inside the court | Hit → bounce links |
|---|---:|---:|---:|---:|---:|---:|
| `contact-v2` | 166 | 46 | 27 | 35 | 29 | 32 |
| `learned-events-v1` | 211 | 165 | 40 | 109 | 90 | 117 |

A seeded sample of 16 bounces with a landing was inspected as still frames. About 10 showed
the ball at the court surface, which a still cannot confirm as the contact frame. Six were
wrong: two racket contacts, a toss, a pre-serve bounce, a ball near a ball kid off court, and
one close-up that passed the main-view filter. Automatic landings therefore stay
unreviewed candidates in the assisted view, and both options stay opt-in.

## Cut detection and court stability on the public TrackNet clips — 2026-11-11

`python -m tennis_ai.scene_benchmark` uses structure the dataset guarantees instead of labels:
each clip is one still-camera shot, so the clips of a split joined end to end give a known
shot change at every boundary, any cut inside a clip is false, and any frame-to-frame move of
the court estimate inside a clip is jitter. The `broadcast-v1` thresholds (frame difference
> 0.03 and brightness-histogram distance > 0.10) were chosen on train, confirmed on
validation, and test was scored once.

| Split | Boundaries | Cut recall `baseline-v1` → `broadcast-v1` | False cuts | Court p95 jitter, raw → smoothed (px) | Jumps > 20 px, raw → smoothed |
|---|---:|---:|---:|---:|---:|
| Train | 55 | 0.00 → 0.18 | 0 → 0 | 5.13 → 0.97 | 137 → 58 |
| Validation | 17 | 0.00 → 0.18 | 0 → 0 | 1.36 → 0.46 | 0 → 0 |
| Test | 20 | 0.05 → 0.20 | 0 → 0 | 0.73 → 0.27 | 0 → 0 |

- Most boundaries join two rallies filmed by the same wide camera; their frame difference
  (median 0.021) overlaps the largest in-clip differences (0.015), so no appearance test can
  find them. Boundary recall is a harsh lower bound, not broadcast cut recall.
- The clips never pan, so the false-cut rate there says nothing about camera pans. On the
  full broadcast (41,564 frames) the first version reported 630 cuts against the baseline's
  17; a contact sheet showed most extra ones inside fast pans and slow-motion replays. The
  histogram test now also requires the frame difference to be an isolated step (more than
  three times the previous frame's difference plus 0.01). With that, it reported 84 cuts.
  Of the first 40 cuts only it found, about 39 were real changes between the wide view,
  close-ups and crowd shots that `baseline-v1` missed, and one looked like a cut inside one shot.
  The public-clip figures above are unchanged by the step rule. No cut labels exist, so
  this is a development check.
- Court coverage did not change (≥ 0.96 in every split): the two-second hold rarely bridges
  a failed fit here.

## Fine-tuning the ball bundle on TrackNet games 1–6 — 2026-11-11

`ball-v0.2.0` was fine-tuned locally (Apple M4, MPS, 1280 px, batch 4, no mosaic) on every
second frame of games 1–6, with each point label drawn as a 16-px box. Validation mAP50 on
games 7–8 went 0.44, 0.59, 0.51, 0.43 over four epochs, so training was stopped and the
epoch-2 weights were kept (about 55 minutes per epoch). The weights stay local: the
dataset has no licence.

| Model, with `static-reject-v1` | Train P / R (5 px) | Validation P / R | Test P / R | Test P / R (10 px) | Test candidate ceiling (5 px) |
|---|---:|---:|---:|---:|---:|
| `ball-v0.2.0` | 0.811 / 0.521 | 0.740 / 0.399 | 0.853 / 0.763 | 0.941 / 0.841 | 0.804 |
| Fine-tuned (epoch 2) | 0.868 / 0.750 (trained on) | 0.757 / 0.627 (epoch chosen here) | 0.847 / 0.745 | 0.915 / 0.805 | 0.844 |

- **Fine-tuning did not improve the untouched test games.** The detector finds the right
  point more often there (ceiling 0.804 → 0.844), but the selected ball is right slightly
  less often. The large validation gain comes from the games used to choose the epoch.
- Validation peaked at epoch 2 and then fell while training loss kept falling: six
  training games overfit quickly. More matches, or the hard frames (occlusion and the far
  player), are the next lever, not more epochs.
- `ball-v0.2.0` stays the best clean result. Nothing is promoted.

## `static-reject-v1` on a full broadcast — 2026-11-11

Both selectors were replayed over the cached ball candidates and court geometry of the full
broadcast run (41,564 frames at 59.94 fps, 1920 × 1080), so this is the pipeline's ball stage
with court geometry and without re-running any model. No ball labels exist for this match.

| Measure | `baseline-v1` | `static-reject-v1` |
|---|---:|---:|
| Frames with an observed ball | 20,599 | 18,917 |
| Busiest 6-px cell (frames) | 1,509 at (108, 228) | 108 at (462, 912) |
| Second busiest cell | 1,465 at (462, 912) | 42 |
| Main-view `contact-v2` hits / rallies / bounces | 166 / 27 / 46 | 193 / 32 / 49 |

- The two selectors chose the same point in 16,200 frames. 1,863 frames had a ball only
  under the baseline, 181 only under the new selector and 2,536 a different point.
- A seeded sample of 24 baseline-only frames showed the scoreboard's tournament logo, a
  giant decorative ball in the stands, the umpire chair, court-line marks and a ball held by
  a ball kid. None was a ball in flight. In 8 inspected frames where the selectors
  disagreed, the baseline point was a fixed graphic or object and the new point lay over the court.
- More hit and rally candidates is not evidence of better events, because none of them is
  labelled. `baseline-v1` stays the default: changing it needs labelled held-out events.

## Stroke classification measure — 2026-11-11

`scripts/contact_labels.py score` now reports per-class precision, recall and F1 for serve,
forehand and backhand and their macro F1, with abstentions counted as misses. The plan's T5
gate is a macro F1 of at least 0.80 on human labels from matches not used for tuning.

On the 86 hits the coding assistant judged on 2026-11-04 (a visual check, not human
labels, on the strips used to tune `stroke-v1`), `stroke-v1` reaches a macro F1 of 0.975
(serve 1.000, forehand 0.974, backhand 0.952; 5 abstentions). This is tuning evidence on
in-sample clips; the gate stays open until a player or coach labels another match.
