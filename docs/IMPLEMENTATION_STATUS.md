# Offline tennis upgrade status

This branch implements the desktop review/data workflow, shared AnalysisPackage v2/v3,
a Core ML conversion toolchain and a native iOS 26 development app. It is not an
App Store release, a validated automatic stroke classifier or a phone accuracy report.

## Implemented and locally exercised

- Self-contained analysis folders, legacy export, source integrity checks and relative paths.
- Atomic SQLite prediction/tracker checkpoints, explicit resume identity checks and timestamp seek.
- Saved-match browser, exact-frame review, event corrections, reviewed-only statistics and audio clip export.
- Explicit ball/absence annotations, event coverage intervals and match-isolated benchmark reports.
- Candidate hits/bounces/rallies. All automatic strokes remain unknown; manual labels cover five strokes.
- Isolated, hash-locked Core ML conversion with verified tensor shape and package digest.
- Explicit v2-to-v3 save-as, shared evidence fixtures, separate participant/assignment/link
  contracts, durable event correction audit and invalidated derived claims after review edits.
- Owner-restricted desktop package folders, exact-name match deletion, iOS protected storage
  and default backup exclusion. Physical-device privacy acceptance remains pending.
- Feature-branch CI uploads development-only test reports, wheel, contract/benchmark status
  and unsigned simulator build. Promotion readiness fails closed while evidence is missing.
- Opt-in motion/overlay ball filtering, per-scene capture-quality summaries and conservative
  Python player ground-position estimates. These are unvalidated candidates; the baseline
  tracker remains the default. Missing calibration and ambiguous sides remain explicit.
- Participant/assignment/link/rally audit replay in both runtimes, with shared recovery
  fixtures and a desktop `review-entity` CLI. Native identity editing, interval validation,
  identity retraction and player-position export are implemented. Reopening an unchanged
  package preserves its derived metrics.
- Assisted and human-confirmed review reports, with input digests, support references,
  exclusion reasons, unknown strokes and nullable empty denominators. Personal statistics
  require confirmed scene-local identity in both views. CI compares ten complete
  Python/Swift reports generated from shared evidence fixtures, including a legacy
  track sample with omitted optional fields.
- Native Overview / Review / Court pages, prioritized review, evidence seeking, identity
  and association editors, paginated evidence lists and disclosed report/clip/package export.
  New analyses use v3; older v2 matches remain readable and migrate by explicit save-as.

The 2026-09-23 review-loop batch has passed 129 Python tests, 37 Swift tests, ten
cross-runtime report comparisons and an unsigned simulator build. The synthetic-video
SwiftUI path passes import, explicit migration, identity and association review,
statistics-to-video, all three exports, reimport, reopening the original match and
correction of a linked event after removing its association.
Simplified Chinese at accessibility XXXL passed a text-clipping and control-description
audit. Import uses the production importer with a simulator fixture hook; the system
document picker, actual VoiceOver navigation, share destination and all failure-state
UI paths remain unverified. Independent review found a post-association editing block;
audited removal and event reclassification now have Python/Swift regression coverage.
The final adversarial finding was independently rechecked after the fix; see the
[audit receipt](reviews/2026-09-23-review-loop.md) and
[development evidence](data/development-2026-09-23.json).

The 2026-09-13 incremental batch passed 112 Python tests and 19 Swift tests. See
[incremental evidence](data/development-2026-09-13.json). A partial independent review found
an audit-order defect that has been fixed; other review agents did not finish because of
usage limits. This batch is development progress, not completion of U2-U6 or release approval.

The 2026-09-12 foundation batch passed 103 Python tests, 15 Swift tests, four Swift-to-Python
fixture exports, wheel resource loading and an unsigned Xcode simulator build. See
[development evidence](data/development-2026-09-12.json). These are software checks, not
accuracy, coach utility or physical-device results. The live repository has no protected
TestFlight/release environment configured; signed distribution is not enabled.

The native implementation and its exact validation results are documented in
[iOS instructions](../ios/README.md). It uses bundled models and manual court
calibration; the downloaded third-party court checkpoint is excluded from iOS.

## Evidence and remaining release gates

| Requirement | Evidence / remaining work |
|---|---|
| Desktop recovery matches uninterrupted inference | Real 90-frame broadcast run with Apple MPS produced byte-identical final frame JSONL after interruption and resume. This is short-clip recovery evidence. |
| Portable source, correction persistence and audio export | Automated integration tests cover moving folders, deleting the external original, rerendering and timed AAC/H.264 export. |
| Core ML conversion | Actual YOLO26s 640 FP16 package verified and executed on macOS. See [model evidence](MODEL_RELEASE.md). |
| Python/Swift interoperability | Shared fixtures and Swift core tests; native SDK build results are recorded separately in the iOS instructions. |
| Phone ball precision / recall | Pending independently labelled phone singles and doubles, five original matches per setting; target >=90% precision and >=75% recall with near/far breakdown. |
| Hit, bounce, rally and five-stroke accuracy | Pending complete event annotations and a trained/validated classifier; heuristics and manual edits do not satisfy this requirement. |
| Model conversion parity | Pending independently labelled fixed-frame comparison; ball precision and recall each may drop by at most 2 percentage points. |
| iPhone 15 Pro performance | Pending physical device: 10-minute 1080p30 analysis <=20 minutes, 2-hour run, peak memory, heat, battery, interruption and recovery. |
| Offline and export acceptance | Pending physical device airplane-mode workflow, rotation/VFR/audio, low storage, background suspension and export playback. |
| Free/open-source distribution | Source is AGPL-3.0-only; publishing requires confirmed model/dependency distribution terms, signing and App Store route. No public release has been made by this work. |

The user currently has no private phone match recordings available. Public footage
may support development only when its licence allows the intended use; it cannot be
silently treated as representative held-out phone data. No fabricated labels, accuracy
numbers or device results fill these gaps. Instructions for collecting the missing
evidence are in [annotation guide](ANNOTATION.md) and [model release protocol](MODEL_RELEASE.md).

## Continuation

1. Complete the remaining tap-by-tap native UI checks and choose the user's signing team for a physical phone. Xcode 27 beta builds and the native simulator integration check now pass.
2. Execute the device checklist and attach measured results.
3. Collect independent match-level labels, run the benchmark and conversion parity tools.
4. Retain the documented device and accuracy gates before release; the review-loop code audit is complete, while the listed UI acceptance paths remain open.
5. Train/promote models only after the relevant gates pass; then review the distribution route.
