"""Portable AnalysisPackage v2; v1 runs remain readable without migration."""

import json
import os
import shutil
import tempfile
from pathlib import Path

from tennis_ai.artifacts import sha256


def atomic_json(path, value):
    path = Path(path)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(value, stream, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def relative_asset(folder, name):
    root = Path(folder).resolve()
    path = Path(name)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("Package assets must use contained relative paths")
    target = (root / path).resolve()
    if not target.is_relative_to(root) or target == root:
        raise ValueError("Package asset escapes its folder")
    return target


def write_manifest(folder, source, metadata, settings, model_provenance, status="running"):
    folder, source = Path(folder).resolve(), Path(source).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    if source.parent != folder:
        target = folder / f"source{source.suffix.lower()}"
        if not target.exists():
            temporary = target.with_suffix(target.suffix + ".pending")
            try:
                shutil.copy2(source, temporary)
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
        elif sha256(target) != sha256(source):
            raise ValueError("Package already contains a different source video")
        source = target
    digest = sha256(source)
    manifest = {
        "schema_version": 2,
        "media": {"id": digest, "sha256": digest, "path": source.name, **metadata},
        "settings": settings,
        "model_provenance": model_provenance,
        "status": status,
        "coordinate_system": "oriented_pixels_top_left",
        "artifacts": {
            "frames": "frames.jsonl",
            "events": "events.json",
            "corrections": "corrections.json",
        },
    }
    atomic_json(folder / "manifest.json", manifest)
    return manifest


def load_manifest(folder):
    folder = Path(folder)
    path = folder / "manifest.json"
    if path.exists():
        manifest = json.loads(path.read_text())
        if manifest.get("schema_version") != 2:
            raise ValueError("Unsupported analysis package version")
        relative_asset(folder, manifest["media"]["path"])
        for name in manifest["artifacts"].values():
            relative_asset(folder, name)
        return manifest
    legacy = json.loads((folder / "summary.json").read_text())
    if legacy.get("schema_version", 1) != 1:
        raise ValueError("Unsupported legacy package version")
    source = Path(legacy["source"])
    if source.parent.resolve() != folder.resolve():
        # Read-only legacy adapter: external paths cannot be represented as a portable package.
        raise ValueError("Legacy media is external; export a portable package first")
    return {
        "schema_version": 2,
        "media": {
            "id": legacy["source_sha256"],
            "sha256": legacy["source_sha256"],
            "path": source.name,
            **legacy["video"],
        },
        "settings": legacy["settings"],
        "model_provenance": legacy.get("versions", {}),
        "status": legacy["status"],
        "coordinate_system": "oriented_pixels_top_left",
        "artifacts": {
            "frames": "frames.jsonl",
            "events": "events.json",
            "corrections": "corrections.json",
        },
    }


def update_status(folder, status):
    path = Path(folder) / "manifest.json"
    if path.exists():
        manifest = load_manifest(folder)
        manifest["status"] = status
        atomic_json(path, manifest)
