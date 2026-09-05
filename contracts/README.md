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
