# Annotation and held-out evaluation

Keep original video and annotation files local. Publish only footage for which
all identifiable participants and the recording owner permit the proposed use.
A public video URL alone is not a training or redistribution licence.

## Dataset manifest

The `tennis-ai benchmark` input is JSON with `schema_version: 1` and a `clips`
list. Each clip contains `clip_id`, `match_id`, `split` (`train`, `val`, `test`),
`category` (`phone-singles`, `phone-doubles`, or a descriptive public/broadcast
category), relative `source`, `annotations`, `predictions`, positive `width`,
`height`, `duration`, and optional `event_annotations`, `event_predictions` paths.
`conditions` is a list: use `occlusion`, `end_change`, `different_lighting`, and
`far_ball` when actually present. These are coverage labels, not model outcomes.

Use the **original match ID** for every crop, frame, adjacent clip and recording
of the same match. Assign splits by match before model selection; the loader
rejects matches appearing across splits and duplicate source paths. It cannot
infer that two renamed videos came from the same match: maintain that provenance
in collection records. Never tune on the held-out test partition. Keep phone
singles and doubles results separate from broadcast results.

## Frame annotation JSONL

One object per line; frame IDs are nonnegative unique integers, matching the
prediction frame IDs. Coordinates refer to the oriented analysis frame at the
manifest width/height, not display-scaled previews. Include original presentation
timestamps in provenance for variable-frame-rate source videos.

```json
{"frame": 90, "ball": [842, 376], "distance": "far"}
{"frame": 91, "ball": null}
{"frame": 92, "players": [{"id": 1, "box": [20, 30, 100, 240]}]}
```

`ball: null` means the annotator checked the frame and confirmed absence. An
omitted `ball` is unlabelled, including occluded/ambiguous cases that cannot be
resolved; it is never a true negative. Annotate the visible ball centre. Use
`distance: near` or `far` according to the court half, not apparent ball size;
omitted distance is reported as unspecified. Optional `players` contain persistent
IDs and xyxy boxes, `rackets` contain xyxy boxes, and `court` contains 14 xy/null
landmarks using the existing court convention. Empty lists mean confirmed absence.
Do not manufacture hidden positions from interpolation.

Missing prediction rows count as misses on positive labelled frames. Interpolated
ball positions are not observed detections. Ball centre matching uses six pixels
at 1080p, scaled by oriented image height. Frame JSONL is indexed on temporary disk
and joined in order with a 2 MiB SQLite page cache; histories are not materialized
in memory. Temporary disk space is proportional to input JSONL size. Auxiliary court-error samples and player identity history remain in memory. Event JSON
and event matching also scale with event count; this is not a claim of constant
memory for arbitrarily large event annotation sets.

## Event annotation JSON

Use `schema_version: 2`, an `events` list following `contracts/events-v2.schema.json`,
and explicit per-kind exhaustive annotation coverage:

```json
{"schema_version": 2, "events": [], "coverage": {"hit": [[0, 60]], "bounce": [[0, 60]], "rally": [[0, 60]]}}
```

This example confirms that no events occurred during a fully reviewed 60-second
clip. Empty events without coverage do **not** assert absence. Every labelled event
must fall inside the declared coverage. Fully annotate negative time as well as
contacts; uncovered predictions are reported separately and not false positives.

`hit` and `bounce` have equal start/end seconds; `rally` spans start to end. Use
real presentation times, scene IDs, unique event IDs and `stroke` from `serve`,
`forehand`, `backhand`, `volley`, `overhead`, `unknown`. A missing or unknown predicted
stroke counts as FN for a known truth class. Wrong known classes produce FN and FP.
Unknown truth strokes do not establish classification negatives. Event matching
is one-to-one, with 0.1-second contact tolerance and rally interval IoU >= 0.5.

Only a visible grounded bounce may receive a court position in metres. Never
project an airborne ball through a planar court transform and call it a landing.
Keep ambiguous positions null. Landing reports expose missed bounces and missing
positions alongside matched-pair error. Have a second annotator independently
review a representative subset and adjudicate disagreements before evaluating.
Automatic candidates remain unreviewed until a person explicitly confirms them;
favoriting a candidate does not verify it.

## Gates and contribution

The phone gate needs at least five original held-out matches **per setting**,
positive and negative ball frames, near/far positives and all declared conditions.
Current gates require ball precision/recall >= 90%/75%, hit/bounce F1 >= 85%, rally
precision/recall >= 90%, five supported stroke classes with macro-F1 >= 80%, and
landing median/P90 <= 0.5/1.0 m. Sparse or incomplete evidence cannot pass.
A quality gate does not certify iPhone runtime, conversion parity or distribution.
See [model release](MODEL_RELEASE.md) for the separate checks.

Use the footage contribution issue form to describe consent, setting, original
match grouping and access terms first. Do not attach private footage or personal
contact details to a public issue. Agree on a suitable transfer location before
sharing files. Contributions need not be public to be useful for a locally run,
permission-scoped evaluation; report those limits with the results.
