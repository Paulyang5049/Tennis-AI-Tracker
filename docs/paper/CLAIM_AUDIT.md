# Manuscript claim audit

Status: working draft; no independent reviewer study has been run. This table links current quantitative claims to checked-in evidence and records the main limits. Recheck it at the exact submission revision.

The prioritized scientific and manuscript findings are in [PRESUBMISSION_REVIEW.md](PRESUBMISSION_REVIEW.md).
The frozen study rules and blank private recording sheets are in [REVIEWER_STUDY.md](REVIEWER_STUDY.md) and [STUDY_PACKET.md](STUDY_PACKET.md). They contain no measured reviewer outcomes.
`scripts/paper_study_summary.py` can recompute descriptive counts from a private frozen manifest after data collection. It has been checked only with constructed records; it is not study evidence.

| Manuscript claim | Evidence | Interpretation / limit |
| --- | --- | --- |
| 693.53 seconds; 41,564 retained of 41,564 expected frames | `docs/data/validation-2026-09-10.json`, `VALIDATION.md` full broadcast check | One broadcast processing run; not representative phone-video performance. |
| Observed-ball 49.56%, interpolated 6.53%, court calibrated 50.55% | Same validation snapshot, `full_video` fields | Availability, not correctness or accuracy. |
| 112 hits, 54 bounces, 24 rallies; zero reviewed | Same validation snapshot, `full_video.candidates` and `reviewed_events` | 190 unreviewed candidates; no event precision, recall, or verified match statistic follows. |
| 129 Python and 37 Swift tests; ten equal reports; unsigned simulator build | `docs/data/development-2026-09-23.json` and `docs/IMPLEMENTATION_STATUS.md` | Development checks at that batch, not an independent reviewer or physical-device result. |
| Scoreboard serve-icon false ball and unstable player IDs | `VALIDATION.md` full broadcast check | Qualitative inspection only; no measured error rate. |
| Experimental model 0 TP / 34 FP / 50 FN; baseline 2 / 21 / 48 | `VALIDATION.md` Google Colab section | Small image split at fixed 0.1 confidence and 0.5 IoU; original-video independence and near-duplicates unverified. Candidate failed promotion. |
| Unreviewed synthetic hit: assisted 1, human verified undefined; link marked unreviewed in a fixture copy: assisted landing 1, human verified undefined | `scripts/paper_fixture_evidence.py`, `docs/data/paper-fixture-evidence.json`, and `contracts/fixtures/v3` | Deterministic report-policy demonstration on constructed evidence; no independent video, user, or accuracy result. |
| Constructed reports retain support references for hits, stroke categories including zero values, landings, unassigned landings, rally length, and player positions | `tests/test_review_statistics.py` and shared v3 fixtures | Structural report checks only. The fixtures do not prove that references open real source media or that reviewers can resolve them. |
| No verified phone-match cohort | `benchmarks/acquisition.json` | Current recorded availability is zero; future reviewer study has no results. |

## Submission review

- Verify every citation against its publisher or original preprint. EventAnchor is a close predecessor for interactive racket-sports annotation; the manuscript must not claim superior review efficiency without a direct comparison.
- Confirm the diagram matches the current code and cross-runtime contracts; verify every non-null human-verified statistic's eligibility and support fields before making a universal traceability claim.
- Zero-valued stroke categories now reference the eligible hits that define their denominator in Python and Swift; retain the source-media audit in the reviewer study before claiming universal traceability.
- Replace protocol language with measured results only after independent reviewers, adjudication, and frozen outputs exist. Keep engineering tests, coverage, accuracy, and user outcomes in separate result tables.
- Verify figure and footage permissions, remove private metadata from the LaTeX upload, inspect the compiled PDF, and retain the AI-assistance disclosure after author review.

## Remaining submission blockers

- Acquire permission-cleared fixed-camera singles clips from distinct original matches. The existing local broadcast highlights file has not been cleared for figures or study reuse and does not match the target camera setting.
- Recruit two independent annotators/reviewers and an adjudicator, freeze the protocol, run the study, and replace proposed-study wording with actual methods and results. If the study cannot be done, substantially narrow the manuscript's research claim and obtain an external scholarly assessment before submitting.
- Have the named author approve the final scientific claims, affiliations, rights, and AI-use disclosure. Confirm arXiv category endorsement in the author's account and inspect the upload-generated PDF and source archive.
