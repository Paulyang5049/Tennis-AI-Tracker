# Review-loop implementation audit (development branch)

Scope: the offline import, identity, prioritized review, statistics, evidence navigation
and export changes on `feat/offline-ios-foundation`, compared with `78e649f`. The audit
covered the earlier `ae0037b` foundation and the current Python/iOS implementation.
Ten independent review lenses examined project standards, correctness, API contracts,
testing, maintainability, security, performance, reliability, Swift/iOS behavior and
cross-component failure sequences. Security reported no actionable finding.

All eleven actionable findings were addressed and checked with focused regressions:

| Area | Finding | Resolution |
|---|---|---|
| Identity | Participant overlap differed between runtimes; unresolved identity could not be saved | Shared negative fixture; atomic retraction and reopen tests |
| Statistics | Nullable legacy fields changed the Python/Swift digest | Shared canonical omission rule; independent legacy-track parity case |
| Long matches | Every frame created a track row; checkpoints repeatedly encoded history | Shared half-second candidate sampling and incremental SQLite storage; 30-minute generated observation and resume/export tests |
| Calibration | Camera movement left a stale homography active | Expire on movement or scene cut; persisted-frame and rerun tests |
| Evidence coverage | Position and rally metrics lacked nonempty cases | Both runtimes now test confirmed/candidate positions, exclusions and rally lengths |
| Recovery | A failed audit append could corrupt the only audit file | Fsynced temporary audit replacement and injected-failure reopen test |
| Review UX | Confirmed link could not be retracted; linked shot could not change type | Audited confirmation retraction plus optional removed link/rally records; reclassification and replay tests |
| Maintenance | Two identity policies could diverge | One indexed participant resolver for statistics and queue |

The final adversarial finding was independently rechecked against the current code
and focused tests after the fix; no actionable follow-up remained. The generated-video
SwiftUI check additionally covers the actual remove-association, edit-event and report
path. See [development evidence](../data/development-2026-09-23.json) for counts and
specific simulator results.

Remaining acceptance limits: the system document picker, an external share receiver,
actual VoiceOver navigation, all failure-state UI paths, two-hour physical-device memory
and the real-device performance/accuracy gates have not been verified. This audit does
not promote an automatic model or authorize TestFlight or a formal release.
