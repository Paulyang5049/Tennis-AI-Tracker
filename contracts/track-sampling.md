# Automatic track summary sampling v1

`automatic_track_sampling = candidate-first-per-half-second-v1` in manifest
`derivation_versions` describes generated track summaries, not source observations.
For each `(scene, track_id, floor(timestamp * 2))`, retain the first candidate
observed in chronological frame order. Never interpolate. Preserve every existing
reviewed sample; its bucket suppresses newly generated candidates. Existing imported
tracks are not rewritten by importing or resuming. Original per-frame player
observations remain in `frames.jsonl` at their original timestamps.

Both runtimes reject a generated summary before persistence if it exceeds 100,000
rows or 32 MiB of encoded JSONL. Four stable tracks over two hours produce at most
57,600 candidate samples. Track fragmentation can still reach a limit and must
surface an error, not produce an unimportable completed package.

For review report input hashing, omit dictionary entries with null values before
normalizing numbers and sorting keys. Optional absent/null fields have identical
semantics after schema validation, including fields inside audit payloads. Array
order and null array elements are preserved.

Links and rallies may carry optional `removed: true` after an explicit audited
removal. Removed records retain their IDs and history but do not constrain event
type or time edits and do not contribute to reports or review queues. A later
replacement with the same ID and `removed` absent restores the association.
