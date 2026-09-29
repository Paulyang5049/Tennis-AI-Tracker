# Manuscript claim audit

Status: working draft; no independent reviewer study has been run. This table links current quantitative claims to checked-in evidence and records the main limits. Recheck it at the exact submission revision.

| Manuscript claim | Evidence | Interpretation / limit |
| --- | --- | --- |
| 693.53 seconds; 41,564 retained of 41,564 expected frames | `docs/data/validation-2026-09-10.json`, `VALIDATION.md` full broadcast check | One broadcast processing run; not representative phone-video performance. |
| Observed-ball 49.56%, interpolated 6.53%, court calibrated 50.55% | Same validation snapshot, `full_video` fields | Availability, not correctness or accuracy. |
| 112 hits, 54 bounces, 24 rallies; zero reviewed | Same validation snapshot, `full_video.candidates` and `reviewed_events` | 190 unreviewed candidates; no event precision, recall, or verified match statistic follows. |
| 129 Python and 37 Swift tests; ten equal reports; unsigned simulator build | `docs/data/development-2026-09-23.json` and `docs/IMPLEMENTATION_STATUS.md` | Development checks at that batch, not an independent reviewer or physical-device result. |
| Scoreboard serve-icon false ball and unstable player IDs | `VALIDATION.md` full broadcast check | Qualitative inspection only; no measured error rate. |
| Experimental model 0 TP / 34 FP / 50 FN; baseline 2 / 21 / 48 | `VALIDATION.md` Google Colab section | Small image split at fixed 0.1 confidence and 0.5 IoU; original-video independence and near-duplicates unverified. Candidate failed promotion. |
| No verified phone-match cohort | `benchmarks/acquisition.json` | Current recorded availability is zero; future reviewer study has no results. |

## Submission review

- Verify every citation against its publisher or original preprint and ensure the literature comparison makes no unsupported superiority claim.
- Confirm the diagram matches the current code and cross-runtime contracts; verify every non-null human-verified statistic's eligibility and support fields before making a universal traceability claim.
- Replace protocol language with measured results only after independent reviewers, adjudication, and frozen outputs exist. Keep engineering tests, coverage, accuracy, and user outcomes in separate result tables.
- Verify figure and footage permissions, remove private metadata from the LaTeX upload, inspect the compiled PDF, and retain the AI-assistance disclosure after author review.
