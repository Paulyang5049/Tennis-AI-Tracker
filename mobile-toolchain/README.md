# Isolated Core ML toolchain

This environment is separate from the desktop environment. CPython 3.11 on
Apple Silicon macOS is the reproducible target. The direct requirements and
transitive hash lock are committed; generated models and environments are ignored.

From the repository root:

```sh
uv venv --python 3.11 mobile-toolchain/.venv
uv pip sync --python mobile-toolchain/.venv/bin/python --require-hashes mobile-toolchain/requirements.lock
mobile-toolchain/.venv/bin/python scripts/export_coreml.py inspect
mobile-toolchain/.venv/bin/python scripts/export_coreml.py export --output mobile-toolchain/exports/yolo26s-640-fp16
mobile-toolchain/.venv/bin/python scripts/export_coreml.py verify --manifest mobile-toolchain/exports/yolo26s-640-fp16/ModelManifest.json
```

Setup downloads pinned Python packages. Export, verify and benchmark use local
weights only and disable Ultralytics auto-installation. Do not run `pip install`
in the desktop environment to repair conversion. `inspect` works without model
libraries and reports missing/incompatible dependencies. An unsuccessful export
returns exit code 2 and never creates a valid-looking model release directory.

Default source is the existing `models/yolo26s.pt`, checked against its recorded
SHA-256 before PyTorch opens it. For a locally obtained YOLO26n candidate, pass
`--weights`, `--expected-sha256`, `--source-url` and `--license` from verified
provenance. Custom non-COCO and non-end-to-end detectors are intentionally rejected
because their class IDs and tensor layout differ from the app contract.

`--imgsz` accepts 640 (default), 960 or 1280. `--quantize 8` requests 8-bit weight
palettization with FP16 compute, not full integer activation quantization. Compare
both detector sizes at the same input resolution before reducing resolution or
weight precision. New candidates must use a new output directory; existing
releases cannot be overwritten.

See [model release protocol](../docs/MODEL_RELEASE.md) for the Swift decoder,
labelled parity benchmark, provenance and physical-device release gates.

To deliberately update the dependency lock after conversion validation:

```sh
uv pip compile mobile-toolchain/requirements.in --python-version 3.11 --python-platform aarch64-apple-darwin --generate-hashes --output-file mobile-toolchain/requirements.lock
```
