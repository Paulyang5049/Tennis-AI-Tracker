# Model release and conversion evidence

The first mobile detector is a development candidate, not a validated tennis
model. Converting or loading a Core ML package does not establish ball accuracy,
long-video stability, iPhone speed or redistribution permission.

## Files and runtime contract

`scripts/export_coreml.py` produces a directory containing `Detector.mlpackage`
and `ModelManifest.json`. A successful export verifies the actual Core ML input
and output specification, captures source checksum and provenance, records the
conversion environment, and recursively fingerprints every model package file.

Copy both files into `ios/TennisApp/Resources/Models/`, then regenerate the Xcode
project using the iOS build instructions. Do not rename the manifest. The app
requires locally bundled models and performs no runtime download. Generated
weights stay outside source control. The third-party court detector is excluded.

The manifest schema is version 1 (separate from AnalysisPackage version 2):

- Input feature `image`: square RGB image, 640 pixels by default. The model
  embeds scale `1/255` and zero bias; do not scale bytes again before Core ML.
- Orient the source image first. Resize bilinearly with aspect preserved;
  resize width/height are `floor(original_dimension * ratio + 0.5)`, with
  `ratio=min(size/width,size/height)`. Pad RGB `(114,114,114)`, left and top
  `floor((size-resized_dimension)/2)`. Retain the actual resized dimensions.
- Read `output.name` from the manifest, not a hard-coded generated feature name.
  Output is one MLMultiArray `[1,N,6]`, each row
  `[x1,y1,x2,y2,confidence,class_id]` in input-image pixels, origin top left.
  The YOLO26 end-to-end head already selects top detections. No additional NMS
  and no Vision recognized-object wrapper are assumed.
- Filter confidence and COCO IDs 0 (person), 32 (sports ball), 38 (tennis racket).
  Inverse coordinates are `(x-left)*source_width/resized_width` and
  `(y-top)*source_height/resized_height`, clipped to oriented source bounds.
  Discard nonfinite, degenerate, fractional-class and padding-only boxes.
- `package_sha256` hashes UTF-8 records sorted by relative POSIX path, each
  `path + NUL + file_sha256 + NUL + decimal_size_bytes + LF`.
  Source/package hashes are identity checks, not an assertion of trust or licence.
  The package digest is distinct from Xcode's compiled `.mlmodelc` representation.

The installed Ultralytics 8.4.140 exporter explicitly disables `nms=True` for
end-to-end models. Its Core ML image input scales bytes by 1/255; its detect head
returns `xyxy, confidence, class_id`. The script uses those observed interfaces
and rejects any export with a different shape. The app reads the same manifest.

## Labelled parity benchmark

Use the same fixed, independently labelled frames for source PyTorch and Core ML.
Export each oriented frame once as PNG, retain source presentation time in the
dataset provenance, and record its checksum. Group all adjacent clips by the
original match in the main evaluation dataset before assigning train/val/test;
this benchmark consumes only the held-out test partition and never trains.

Frame manifest example (replace the illustrative checksum with the real hash):

```json
{
  "schema_version": 1,
  "frames": [{
    "image": "frames/match-001-frame-00300.png",
    "sha256": "<actual SHA-256>",
    "match_id": "original-match-001",
    "split": "test",
    "detections": [
      {"class_id": 32, "box": [951, 301, 957, 307]}
    ]
  }]
}
```

Boxes use oriented original pixels, not normalized YOLO labels. Label all visible
instances of evaluated classes in each frame; an empty list means confirmed
absence, never unlabelled data. Images are relative to the frame manifest.
Duplicate frame content, escaping paths and checksum mismatches are rejected.

```sh
mobile-toolchain/.venv/bin/python scripts/export_coreml.py benchmark \
  --manifest mobile-toolchain/exports/yolo26s-640-fp16/ModelManifest.json \
  --frames data/mobile-parity/frames.json \
  --report mobile-toolchain/exports/yolo26s-640-fp16/parity.json
```

Both predictors receive identical RGB pixels and letterbox geometry. One-to-one
ball matching uses a centre tolerance of 6 pixels at 1080p, scaled by image height;
person/racket matching uses box IoU >=0.5. Report TP, FP, FN, precision and recall
per class for both models. The conversion gate compares **percentage-point**
drops, requiring ball precision and recall each to drop by at most 2 points.
Without reference true-positive ball evidence the gate remains pending, even
if two empty predictors agree. Passing on one dataset is conversion evidence for
that dataset; it does not meet the phone-scene accuracy gate automatically.

Reports contain image hashes, match IDs and per-frame predictions for audit, plus
macOS prediction median/p95 latency after one warmup. Timing excludes decode and
preprocessing and is not an iPhone benchmark. This initial comparison uses CPU
PyTorch and Core ML `ALL` compute units; it is not a hardware speedup claim.
The benchmark creates a separate report and does not promote a manifest's
validation status automatically.

## Release gates and licence provenance

- Record source URL, exact source checksum, upstream model name/version, training
  dataset provenance and distribution terms for each candidate. The default
  source is the existing YOLO26s COCO model recorded in `models/provenance.json`.
  A supplied `--license` string records an assertion, not clearance.
- The project declares AGPL-3.0-only; Ultralytics publishes AGPL-3.0/Enterprise
  options. Public source availability does not settle App Store distribution
  compatibility. Confirm the actual dependency/model terms and chosen App Store
  distribution route before publishing. See `THIRD_PARTY.md`.
- Require held-out fixed-camera phone singles and doubles results, five original
  matches per setting, and near/far ball breakdowns. Preserve the planned 90%
  precision/75% recall thresholds and identify results below them as test-only.
- Require physical iPhone 15 Pro tests: 10 minutes at 1080p30 within 20 minutes
  analysis, two-hour bounded-memory run, airplane mode, thermal pause/resume,
  interruption, portrait/rotated/VFR video, low storage and audiovisual export.
- Keep the manifest `validation` fields pending until reproducible evidence is
  attached. Neither simulator compilation nor desktop Core ML inference satisfies
  these physical-device requirements.

Primary references: [Ultralytics Core ML export](https://docs.ultralytics.com/integrations/coreml/),
[Apple PyTorch conversion workflow](https://apple.github.io/coremltools/docs-guides/source/convert-pytorch-workflow.html),
[Ultralytics licensing](https://www.ultralytics.com/license).

## Local conversion evidence (development candidate)

The isolated pinned environment completed a real YOLO26s 640 FP16 export on
Apple M4 / macOS arm64 with CPython 3.11.15. The retained local output is
`mobile-toolchain/exports/yolo26s-640-fp16/` (ignored generated artifact), with
package digest `5c30a13c0b968a597a0f9692631e01c2d6adf4767dbc326b930a7523c01586a7`.
The actual output feature is `var_1443`, shape `[1,300,6]`; recursive package
verification passed. Core ML also loaded and predicted on a synthetic uniform
640x640 RGB image, returning finite values at the expected shape. This is a
runtime/interface smoke test with **no accuracy evidence**.

Conversion emitted a Core ML MIL range-cast overflow warning and disabled the
unsupported scikit-learn conversion API (1.7.2 versus its supported <=1.5.1 range).
The PyTorch export and runtime smoke test nevertheless completed. Preserve these
warnings with candidate evidence; no labelled conversion parity, phone-scene
accuracy, INT8 candidate or physical-iPhone performance result has been measured.
All release validation fields remain pending. The desktop environment was not
changed to achieve this export.
