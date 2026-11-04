# AnalysisPackage v2

The shared Python/Swift contract is a directory with `manifest.json`, a contained
source video, `frames.jsonl`, `events.json`, and `corrections.json`. SQLite files
are runtime indexes/checkpoints, not the interchange format. Assets are relative
paths; reject absolute paths, traversal and symlinks escaping the package.

`manifest.json` has schema_version=2, media (id=SHA256, sha256, path, width,
height, duration, origin, optional fps/rotation/has_audio), settings (players=2|4),
model_provenance (string-to-string fingerprints), status and artifacts
(frames/events/corrections relative filenames). coordinate_system is
`oriented_pixels_top_left`: x right, y down, after applying video orientation.
Timestamps are source presentation times in seconds minus media.origin, never
frame/fps estimates. Width/height describe oriented analysis pixels. Court
coordinates are metres: far-left doubles corner=(0,0), near-right=(10.97,23.77).

Frames retain the existing v1 record fields: schema_version (1 or 2), frame,
timestamp, scene, cut, camera_moving, court (nullable: matrix/points/source),
players (id, box xyxy, confidence, optional pose/label), rackets, ball_candidates,
ball (status observed|interpolated|missing, xy nullable, confidence nullable).
v2 adds no mandatory frame field other than schema_version=2 for new writers.
Missing values are null, never NaN; interpolation is never an observation.

`events.json` is {"schema_version":2,"events":[...]}. Each event:
id (stable string), kind (hit|bounce|rally), start/end (seconds; equal for point
events), scene (int), player_id (nullable int), stroke (serve|forehand|backhand|
volley|overhead|unknown), position (nullable [x,y] in court metres), provenance
(automatic|manual), reviewed (bool), confidence (nullable 0..1), excluded (bool),
favorite (bool). Automatic events are **unvalidated candidates**. Do not report
them as measured truth. Manual/reviewed, non-excluded events drive verified stats.
Rally boundaries are editable; instantaneous events must have end=start.
Only reviewed bounce positions contribute to the landing map.

`corrections.json` retains court (frame index string -> four ordered corners:
far-left, far-right, near-left, near-right) and labels (scene string -> track ID
string -> display name). Edits supersede predictions; no inference is required.

Status: running, paused, cancelled, failed, inference_complete, complete.
A checkpoint commits frames and runtime state in one SQLite transaction. Resume
must validate media, settings, model hashes and runtime compatibility. Restored
tracking and temporal event context must not reset at a storage chunk boundary.
Derived frames/events can be regenerated from the complete raw cache and edits.

v1 summary.json is read without modification. External legacy media remains
supported by desktop review; conversion into a portable package copies the media.
Reject unknown major schema versions. Ignore unknown additive JSON keys.

`fixtures/` contains synthetic shared fixtures, not private video or trained data.
# AnalysisPackage v3

v3 adds separately versioned events, tracks, rallies, metrics, insights and an append-only
event correction log. The v2 reader and existing event semantics remain available. Run
`tennis-ai package INPUT OUTPUT --version 3` for an explicit copy; the input is never migrated
in place. A v3 export preserves v3 and rejects downgrade to v2.

Both versions use oriented image pixels. v3 explicitly declares the existing court frame:
`far_left_x_right_y_near_m`, dimensions 10.97 × 23.77 m. `position` remains bounce-only;
`contact_point_image_px` is the ball/racket observation and `hitter_position_court_m` is the
player's ground point. `contact_interval` carries uncertain contact timing independently
from the backward-compatible instantaneous event anchor. No 3D point is inferred.

`events.json` stores persistent participants, time-bounded scene/track assignments and
shot-bounce links. Human-verified participant events require a reviewed matching assignment.
Rallies reference ordered shots; metrics and coaching cards reference their input evidence.
The `corrections.jsonl` audit survives a crash before `events.json` materialization, while
`corrections.json` retains legacy court/label corrections. Metrics and insights are invalidated
after an event change. Four synthetic fixtures are under `fixtures/v3/`; source media is
intentionally absent. They are contract data, not an accuracy benchmark.

Canonical schemas live here; `scripts/sync_contract_schemas.py` generates the wheel's offline
schema resource, and its `--check` mode detects drift. Swift exports are validated against
the same Python schemas in branch CI. Imports bound evidence assets to 32 MiB / 100,000 rows,
reject duplicate IDs, broken references, non-finite values and escaped/aliased asset paths.

Audit entries may include `entity_type` (`event`, `participant`, `assignment`, `rally`);
omission means `event` for existing logs. Replay replaces an existing entity in its original
array slot and appends missing entities. Unchanged replay preserves derived results;
recovered changes invalidate metrics and insights. `fixtures/v3/entity-audit.jsonl` is shared
by Python and Swift recovery tests. `tennis-ai review-entity FOLDER KIND ENTITY.json`
records a complete participant, assignment or rally correction with an optional `--reason`.

`quality-v1.schema.json` describes capture eligibility heuristics, not measured accuracy.
Player ground positions retain their ankle/box method, calibration identity and nullable
error estimate. An `unknown` side or `ambiguous` role does not establish participant identity.
