# Private recording packet for the independent reviewer study

This is a blank collection instrument, not study data. Use it with `REVIEWER_STUDY.md`. Keep completed sheets and video outside the repository. Public results may contain anonymous clip codes and aggregate counts only when the recording terms permit them. Do not enter participant names, contact details, or source URLs containing access tokens in the public paper.

## 1. Freeze record, completed before annotation

Record one row per clip. The person who checks rights signs the private record. Three rows must refer to three distinct original matches; different camera views or extracts of one match do not count as distinct matches.

| Field | Required entry |
| --- | --- |
| Clip code and original match code | Anonymous, stable codes; keep the private identity mapping separately. |
| Source and rights | Recording owner, written permission for analysis, and separate permission for paper figures and redistribution. Record yes/no for each use. |
| Media identity | Source SHA-256, selected clip start/end, selected-clip SHA-256, resolution, frame rate, duration in seconds. |
| Setting | Fixed camera yes/no, full court yes/no, singles yes/no, near/far visibility, lighting, cuts and occlusions. |
| Software freeze | Git commit, model file SHA-256, model/config parameters, package or prediction digest, protocol revision, freeze date in UTC. |
| Review team | Two distinct coded reviewers and a distinct coded adjudicator; experience and practice-clip completion. |

Accept a clip only when it is 5–10 minutes long, all setting fields are yes, analysis permission is documented, and its original match code is unique in the study. Figure permission is checked separately; a clip may be studied without appearing in the paper. Lock the three clip codes and analysis settings before anyone sees candidates. Record deviations instead of silently replacing a clip.

## 2. Independent annotation sheets

Give each reviewer a clean player with no prediction overlay. Create one event row for every observed event. Use clip-relative seconds from the source timeline. For hits and bounces, `start_s` and `end_s` are equal. For rallies, they mark interval boundaries. Unknown identity or visibility is recorded explicitly. Reviewers independently record all no-event intervals they inspected; a gap is not evidence of absence.

| clip_code | reviewer_code | event_id | kind: hit/bounce/rally | start_s | end_s | player_code or unknown | visible/occluded/unresolved | note |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
|  |  |  |  |  |  |  |  |  |

| clip_code | reviewer_code | checked_start_s | checked_end_s | complete_for_hit | complete_for_bounce | complete_for_rally | interruption or uncertainty |
| --- | --- | --- | --- | --- | --- | --- | --- |
|  |  |  |  |  |  |  |  |

The adjudicator receives both original sheets, records every disagreement and resolution, and creates a separate final event and coverage sheet. Keep both reviewers' original rows unchanged.

| clip_code | disagreement_id | reviewer event IDs or interval | decision | reason | adjudicated event ID or unresolved |
| --- | --- | --- | --- | --- | --- |
|  |  |  |  |  |  |

## 3. Candidate review and time sheets

Freeze and save the candidates before review. Each reviewer then inspects the same candidate set and source clip. Record one row per candidate, including candidates that remain unresolved. Record additional missed events discovered during exhaustive independent annotation separately; candidate inspection alone cannot establish recall.

| clip_code | reviewer_code | candidate_id | candidate kind/time | decision: accept/correct/exclude/unresolved | corrected kind/time | reason |
| --- | --- | --- | --- | --- | --- | --- |
|  |  |  |  |  |  |  |

| clip_code | reviewer_code | independent annotation minutes | candidate review minutes | paused minutes | navigation failures | interruptions |
| --- | --- | --- | --- | --- | --- | --- |
|  |  |  |  |  |  |  |

Time includes active work only; record pauses separately. Reviewer IDs remain coded in public aggregates. Do not merge annotation and candidate-review time into a single number.

## 4. Traceability audit sheet

Generate each final human-verified report from the reviewed package. List every non-null metric, including a zero-valued stroke category. For each, inspect the event IDs, support references, review and identity status, denominator, and whether the referenced source frame or clip opens. Record each failure separately; a valid JSON reference alone does not prove media traceability.

| clip_code | view | metric_id | participant_code or all | value | denominator | support references resolve | inputs eligible | media opens | failure code |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
|  | human_verified |  |  |  |  |  |  |  |  |

Failure codes: `missing_support`, `unreviewed_input`, `identity_unresolved`, `association_unreviewed`, `media_missing`, `seek_failed`, `other`. A metric passes only when all three check columns are yes. The traceability denominator is the number of inspected non-null metrics; report `undefined` when it is zero. Keep assisted estimates in a separate sheet and never include them in this denominator.

## 5. Analysis rules and results to fill

Compare frozen candidates against adjudicated events only inside intervals exhaustively checked for that event kind. Use `tennis_ai.benchmark.match_events`: hits and bounces match one-to-one when start times differ by at most 0.1 seconds; rallies match one-to-one when interval intersection-over-union is at least 0.5. Report true positives, false positives, and false negatives by kind and clip. Precision is TP/(TP+FP), recall is TP/(TP+FN), and either is `undefined` when its denominator is zero. Report unmatched and unresolved events separately. For matched point events, report the absolute timing error median and range. Do not compute a timing error for unmatched events.

Compare the two independent reviewer sheets using the same kind-specific matching rules and report matched and unmatched positive events before adjudication. A long no-event interval must not dominate an agreement percentage. Report median and range of active annotation and candidate-review minutes across reviewers, correction counts by decision, and the traceability numerator/denominator. The small cohort supports descriptive results, not a population estimate or a model-promotion decision.

| Clip | Hit TP/FP/FN | Bounce TP/FP/FN | Rally TP/FP/FN | Reviewer positive matches/unmatched | Annotation min, median (range) | Review min, median (range) | Traceable/non-null metrics | Failures/deviations |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Match A | pending | pending | pending | pending | pending | pending | pending | pending |
| Match B | pending | pending | pending | pending | pending | pending | pending | pending |
| Match C | pending | pending | pending | pending | pending | pending | pending | pending |
| Pooled counts | pending | pending | pending | pending | report across six sessions | report across six sessions | pending | pending |

Before transferring any result to the manuscript, a second person recomputes the table from the frozen private sheets, confirms the source-media spot checks and rights, and adds the aggregate evidence path to `CLAIM_AUDIT.md`. Replace each `pending` entry only with measured data; preserve a separate `undefined` value when a denominator is zero.

## 6. Recompute the descriptive summary

Use `PYTHONPATH=src uv run python scripts/paper_study_summary.py /private/study.json` after the private sheets have been checked. The command prints JSON; save its output in the private release packet first. The tool reuses the repository's event matcher and coverage rules, checks the frozen candidate-file digests, rejects reused original-match codes, and requires one audit row for every non-null metric in each human-verified report. It does not verify recording rights, whether reviewers worked independently, or whether a human audit answer is correct. A second person must inspect those records.

The private `study.json` has `schema_version: 1`, a `freeze` object, and a `clips` list of at least three entries. The freeze records the full 40-character `software_commit`, a nonempty `model_sha256` object mapping model names to 64-character digests, `protocol_revision`, and `frozen_at_utc`. Each clip entry records `code`, unique `original_match_code`, `duration_seconds`, `source_sha256`, `setting` booleans (`fixed_camera`, `full_court`, `singles`), `rights` booleans (`analysis_permission`, `figure_permission`), paths to `candidates` and `adjudicated_events`, and the frozen candidate file's `candidate_sha256`. Paths are relative to `study.json`; event files use the existing `events-v2` format with exhaustive `coverage` intervals by kind.

Each clip also has `adjudicator_code`, `adjudication_log` path, exactly two `reviewers`, and at least one `trace_reports` entry. A reviewer entry contains `code`, `independent_events` path, active `annotation_minutes`, active `review_minutes`, `paused_minutes`, and nonnegative `decisions` counts for `accept`, `correct`, `exclude`, and `unresolved`; those counts must sum to the candidate count. A trace entry names one human-verified `report` and one `audit` JSON list. The audit has exactly one row for each non-null metric, keyed by `metric_id`, including zero-valued categories. Each row has Boolean `support_resolves`, `inputs_eligible`, and `media_opens`; a failed row also has one of the failure codes in Section 4.

The summary reports per-clip and pooled candidate counts, coverage, reviewer positive-event matches, active time, and traceability. It leaves matched timing and reviewer agreement undefined where full annotation coverage is missing. Do not copy these aggregates into the manuscript until the original match identities, permissions, reviewer independence, adjudication log, and source-media checks have been independently verified.
