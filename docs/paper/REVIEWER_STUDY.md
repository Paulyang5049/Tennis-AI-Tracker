# Independent reviewer study for the system paper

Status: protocol only. No clips, participants, independent labels, or results have been collected. This study evaluates the usefulness and integrity of the evidence-review workflow; it is not the model-promotion benchmark in `docs/EVALUATION_PROTOCOL.md`.

## Acquisition and freeze

Acquire at least three fixed-camera, full-court singles clips of 5–10 minutes from three original matches. Record each original match ID, camera position, resolution, frame rate, duration, lighting, scene changes, source, recording permission, analysis permission, and the exact permission for paper figures and data release. Exclude any clip without permission for research analysis. Never commit footage, identities, local logs, or detailed annotations. Maintain a private manifest with source SHA-256, package and prediction digests, software commit, model digests, reviewer instructions, and a dated freeze declaration. Derivatives of one match must stay in one split. Freeze the clip list and protocol before reviewers see candidates.

Two reviewers independently annotate each clip without model overlays: hit, bounce, and rally intervals, event type, player identity where visible, and intervals exhaustively checked for no events. They mark ambiguity and occlusion as unresolved. A third person adjudicates disagreements while retaining each original annotation and a reason for the decision. A reviewer must not use automatic predictions as the independent answer. Record reviewer experience and training, and give both the same short instructions and practice clip outside the study set.

## Review session

Run the frozen pipeline on every clip. After independent annotation, show each reviewer the same candidate set in the workbench. Use the same task order: inspect each candidate and its source frame or clip; accept, correct, exclude, or mark unresolved; then inspect the resulting assisted and human-verified reports. Record wall time for annotation and candidate review separately, pause time, candidate count, accepted count, corrected count, excluded count, unresolved count, missed events found during exhaustive annotation, and navigation failures. Do not infer missing events from candidate review alone.

For every non-null statistic in the human-verified report, check that its event IDs and support references resolve, all inputs are eligible reviewed records, and the source frame or clip can be opened. Record denominator as all inspected non-null statistics and numerator as those passing every check. Record each failure with a coded reason. Sample no statistic silently: if the output is too large, predeclare a deterministic sample and report its size and selection rule. Inspect assisted figures separately and retain their assisted label. Do not count an assisted estimate as a verified claim.

## Analysis and reporting

Report per match and pooled counts with denominators: candidate true/false/missed counts against adjudicated exhaustive intervals; timing errors for matched events; reviewer agreement before adjudication by event kind; median and range of annotation and review minutes; correction types; and traceability proportion. Define event matching with the existing benchmark's 0.1-second tolerance and one-to-one matching. For agreement, report raw agreement and confusion counts on predeclared time bins or matched events, with the unit stated; do not imply that agreement establishes ground truth. Preserve unresolved observations in denominators as a separate category. Report all three matches individually, including failures, and no significance test or population-wide accuracy estimate from this small cohort.

The independent labels may be exported to the existing benchmark manifest only after adjudication. A model accuracy or promotion claim additionally requires the match-isolated held-out cohort, near/far breakdown, fixed baseline comparison, and uncertainty rules in `docs/EVALUATION_PROTOCOL.md`. The current acquisition record in `benchmarks/acquisition.json` lists zero verified phone matches. Do not change that count until original match sources and annotations are audited.

## Release packet

Keep a private packet with permissions, manifest, raw independent labels, adjudication log, time log, and frozen predictions. Public artifacts may include the protocol, code revision, model provenance, aggregate tables, and only figures or data explicitly permitted for redistribution. Before the manuscript reports a result, independently recompute the aggregate from the frozen records and add its evidence path to `CLAIM_AUDIT.md`.
