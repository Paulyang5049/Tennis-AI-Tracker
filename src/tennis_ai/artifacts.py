"""Versioned, checksummed local model bundles."""

import hashlib
import importlib.metadata
import json
import shutil
from pathlib import Path

ARCHITECTURES = {"ball": "yolo26s", "court": "TennisCourtDetector-15"}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def package(weights, destination, kind, input_size, metrics=None):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / "weights.pt"
    if Path(weights).resolve() != target.resolve():
        shutil.copy2(weights, target)
    versions = {
        name: importlib.metadata.version(name) for name in ["torch", "ultralytics", "numpy"]
    }
    manifest = {
        "schema_version": 1,
        "kind": kind,
        "architecture": ARCHITECTURES[kind],
        "classes": {"0": "tennis ball"} if kind == "ball" else {},
        "input_size": input_size,
        "versions": versions,
        "sha256": sha256(target),
        "weights": "weights.pt",
        "metrics": metrics or {},
    }
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return destination


def validate_bundle(folder, kind):
    folder = Path(folder).resolve()
    manifest = json.loads((folder / "manifest.json").read_text())
    if manifest.get("schema_version") != 1 or manifest.get("kind") != kind:
        raise ValueError("Incompatible model bundle schema or task")
    if manifest.get("architecture") != ARCHITECTURES[kind]:
        raise ValueError("Model architecture does not match the selected task")
    target = (folder / manifest["weights"]).resolve()
    if target.parent != folder or not target.is_file():
        raise ValueError("Bundle weights must be a file inside the bundle")
    if sha256(target) != manifest.get("sha256"):
        raise ValueError("Model checksum mismatch")
    if kind == "ball" and manifest.get("classes") != {"0": "tennis ball"}:
        raise ValueError("Expected a single tennis ball class")
    expected_size = 1280 if kind == "ball" else [360, 640]
    if manifest.get("input_size") != expected_size:
        raise ValueError(f"Expected input size {expected_size}")
    for name in ["torch", "ultralytics"]:
        installed = importlib.metadata.version(name)
        trained = manifest.get("versions", {}).get(name)
        if not trained or installed.split(".")[:2] != trained.split(".")[:2]:
            raise ValueError(f"{name} version mismatch: bundle {trained}, installed {installed}")
    return target, manifest
