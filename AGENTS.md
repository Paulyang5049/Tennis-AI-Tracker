# AI Tennis Tracker project instructions

## Scope and authority

This file supplements the global instructions for the entire repository. It records
project-specific facts, contracts and verification commands. Do not copy global
instructions here. If a planned design conflicts with checked-in contracts or measured
evidence, the contracts and evidence win until they are deliberately updated together.

## Product contract

- Build an offline, evidence-first tennis analysis tool for players and coaches.
- The iOS app is the player workflow. The Python/Gradio application is the annotation,
  training, benchmark and advanced-review workbench.
- Keep automatic candidates, reviewed facts and derived coaching claims visibly distinct.
  Confidence, coverage or a plausible clip is not ground-truth accuracy.
- Candidate evidence may power a clearly labelled assisted estimate, but only human-reviewed
  inputs enter the human-verified view until a separately versioned auto-accept policy passes
  its held-out and review-burden gate.
- Every human-verified statistic and coaching recommendation must resolve to the reviewed
  events and clips that support it. An optional language model may explain verified metrics;
  it must not invent events, outcomes or certainty.
- Preserve uncertainty. Missing, occluded or ambiguous observations stay nullable or are
  explicitly marked for review; do not silently interpolate them into facts.
- A landing coordinate requires bounce evidence. Never project an airborne ball through
  the court homography and call that point a landing.
- Record contact as two different observations: the player's court position at contact
  and the ball/racket contact point in image pixels. Do not claim a three-dimensional
  contact coordinate unless a separately validated calibration supports it.
- Singles on fixed, full-court phone video is the first promotion target. Preserve doubles
  in schemas, but do not describe it as validated until its own held-out gate passes.
- Keep imported video and analysis local by default. Do not commit private footage,
  generated match outputs, datasets, credentials or model weights.
- Keep scene-local near/far tracks separate from persistent self/opponent participants. A
  side change requires an explicit mapping; unresolved mappings block participant metrics.
- Imported media and analysis stay in app-controlled protected storage, are excluded from
  cloud backup by default, support complete match deletion, and leave the app only through an
  explicit export/share action that names included media.

## Current technical truth

- `contracts/analysis-v2.schema.json`, `contracts/events-v2.schema.json` and
  `contracts/fixtures/` define the current portable Python/Swift interchange contract.
- `docs/IMPLEMENTATION_STATUS.md`, `VALIDATION.md` and
  `docs/data/validation-2026-09-10.json` are the sources for implemented status and measured
  results. Update them when the corresponding evidence changes.
- The current automatic event detector in `src/tennis_ai/events.py` is a candidate
  heuristic, not a validated contact, bounce, rally or stroke classifier.
- Current AnalysisPackage v2 uses oriented video pixels and supports manually calibrated
  court geometry. Any v3 change must retain a v2 reader or provide an explicit,
  fixture-tested migration.
- `docs/plans/2026-09-11-1411-feat-tennis-coaching-intelligence-plan.md` is the approved
  implementation sequence once the user accepts it. It does not override evidence or
  release gates.

## Engineering boundaries

- Define cross-runtime JSON Schema and fixtures before changing Python and Swift readers.
- Keep source observations, reviewed corrections, derived metrics and narrative insights
  in separate layers. Derived data must carry input/review/model provenance.
- Group all footage from the same match in one evaluation split. Fit thresholds and
  calibration on training/validation matches only; report the untouched test split by
  phone/broadcast, singles/doubles and near/far court where sample size permits.
- Compare new models against the shipped baseline on the same frozen benchmark. A model is
  promoted only when the relevant gate passes; model availability or higher coverage is
  insufficient.
- Core ML conversion requires fixed labelled-sample parity plus physical-device performance
  evidence. Simulator success is not device performance evidence.
- Tests must not download models or depend on private footage. Use generated media, small
  committed fixtures and injected model adapters.
- Keep model and dataset source, version, checksum, licence and intended use in provenance.
  Do not redistribute an asset until its terms permit that exact distribution route.

## Agent coordination and context

- The integrating agent owns product and data contracts, dependency order, final review and
  release-gate decisions. Delegate only independent units with explicit file ownership and
  acceptance criteria.
- Before an implementation unit starts, give its agent a compact capsule containing the
  goal, active requirement/unit IDs, allowed files, relevant contracts and fixtures,
  required checks, dependencies and current diff. The capsule is a convenience, not a
  source of truth.
- Return a delta capsule containing decisions, files changed, checks run, evidence produced,
  unresolved risks and the next dependency. Keep generated capsules under `.context/` and
  out of version control.
- Never let two agents edit a shared contract, project file or migration simultaneously.
  Integrate contract changes before parallel runtime work starts.
- Run at most two implementation agents concurrently plus the integrating agent. U2 ball
  tracking and U3 player/position work may overlap only with disjoint source ownership.

## Verification

Use the narrowest checks that prove the changed behavior, then run the full affected suite
before an update is published.

```sh
uv run ruff check src scripts tests
uv run ruff format --check src scripts tests
uv run mypy src
uv run pytest -q
swift test --package-path ios
python3 ios/generate_project.py
xcodebuild -project ios/TennisOffline.xcodeproj -scheme TennisOffline -sdk iphonesimulator \
  -destination 'generic/platform=iOS Simulator' -derivedDataPath ios/DerivedData \
  CODE_SIGNING_ALLOWED=NO build
```

For documentation-only updates, inspect links and generated references, run
`git diff --check`, and confirm that factual claims still match the cited validation files.

## Update and publication policy

- An update is a coherent, reviewable batch, not each file save. After its applicable checks
  pass, commit only in-scope files and push the active feature branch. Preserve unrelated
  worktree changes.
- Every branch push should publish development evidence as CI artifacts: test reports,
  contract fixtures, benchmark summaries, a Python wheel and an unsigned simulator build
  when those inputs exist. Artifacts must be labelled development-only.
- A push is not a production release. Promotion to `main`, internal TestFlight and a formal
  tagged/App Store release are separate states.
- Internal TestFlight requires configured signing secrets plus contract, accuracy, Core ML
  parity and physical-device gates. A formal release additionally requires versioned model
  provenance, distribution-licence review, release notes and explicit protected-environment
  approval. Never bypass a failed or unavailable gate merely to satisfy “publish”.
