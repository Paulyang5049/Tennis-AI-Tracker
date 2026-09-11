"""Portable AnalysisPackage v2; v1 runs remain readable without migration."""

import json
import math
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
    if not name or "\\" in str(name) or path.is_absolute() or ".." in path.parts:
        raise ValueError("Package assets must use contained relative paths")
    target = (root / path).resolve()
    if not target.is_relative_to(root) or target == root:
        raise ValueError("Package asset escapes its folder")
    return target


def write_manifest(folder, source, metadata, settings, model_provenance, status="running"):
    folder, source = Path(folder).resolve(), Path(source).resolve()
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == "posix":
        folder.chmod(0o700)
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
    for name, value in (
        ("events.json", {"schema_version": 2, "events": []}),
        ("corrections.json", {"court": {}, "labels": {}}),
    ):
        if not (folder / name).exists():
            atomic_json(folder / name, value)
    return manifest


def load_manifest(folder):
    folder = Path(folder)
    path = folder / "manifest.json"
    if path.exists():
        if path.stat().st_size > 1_048_576:
            raise ValueError("Manifest exceeds size limit")
        manifest = json.loads(path.read_text())
        if manifest.get("schema_version") not in (2, 3):
            raise ValueError("Unsupported analysis package version")
        if manifest["schema_version"] == 3:
            from tennis_ai.evidence import ASSET_VERSIONS
            from tennis_ai.schema import validate_schema

            validate_schema("analysis-v3.schema.json", manifest)

            if (
                manifest.get("asset_versions") != ASSET_VERSIONS
                or manifest.get("review_policy_version") != "human-reviewed-v1"
                or manifest.get("storage_policy") != "local-no-backup-explicit-export"
                or not set(ASSET_VERSIONS).issubset(manifest["artifacts"])
            ):
                raise ValueError("Invalid v3 versions, storage or review policy")
        media = manifest["media"]
        if (
            manifest["settings"].get("players") not in (2, 4)
            or manifest.get("coordinate_system") != "oriented_pixels_top_left"
            or any(
                not isinstance(media.get(key), (int, float))
                or isinstance(media[key], bool)
                or not math.isfinite(media[key])
                or media[key] <= 0
                for key in ("width", "height", "duration")
            )
            or not math.isfinite(media.get("origin", 0))
        ):
            raise ValueError("Invalid package media, settings or coordinates")
        relative_asset(folder, manifest["media"]["path"])
        for name in manifest["artifacts"].values():
            relative_asset(folder, name)
        targets = [relative_asset(folder, name) for name in manifest["artifacts"].values()]
        reserved = {relative_asset(folder, manifest["media"]["path"]), path.resolve()}
        if len(set(targets)) != len(targets) or set(targets) & reserved:
            raise ValueError("Package assets must be distinct from media and manifest")
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


def export_package(folder, destination, version=None):
    """Copy a completed legacy/current run into a self-contained directory."""
    from tennis_ai.jobs import run_lock

    folder, destination = Path(folder).resolve(), Path(destination).resolve()
    if destination.exists():
        raise ValueError("Package destination already exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with (
        run_lock(folder),
        tempfile.TemporaryDirectory(dir=destination.parent, prefix=".package-") as staging,
    ):
        summary = json.loads((folder / "summary.json").read_text())
        if summary["status"] != "complete":
            raise ValueError("Only completed runs can be exported")
        manifest = load_manifest(folder) if (folder / "manifest.json").exists() else None
        selected_version = version or (manifest["schema_version"] if manifest else 2)
        if selected_version not in (2, 3):
            raise ValueError("Unsupported export version")
        if manifest and manifest["schema_version"] == 3 and selected_version == 2:
            raise ValueError("Cannot downgrade v3 evidence to v2")
        if manifest and manifest["schema_version"] == 3:
            from tennis_ai.evidence import load_evidence

            load_evidence(folder, manifest)
        source = (
            relative_asset(folder, manifest["media"]["path"])
            if manifest
            else Path(summary["source"])
        )
        if sha256(source) != summary["source_sha256"]:
            raise ValueError("Source changed; predictions cannot be exported")
        temporary = Path(staging) / "analysis"
        copied = write_manifest(
            temporary,
            source,
            summary["video"],
            summary["settings"],
            manifest["model_provenance"] if manifest else summary.get("versions", {}),
            status="complete",
        )
        if copied["media"]["sha256"] != summary["source_sha256"]:
            raise ValueError("Source changed during package copy")
        for name in (
            "frames.jsonl",
            "events.json",
            "corrections.json",
            "annotated.mp4",
            "review.sqlite",
            "cache.sqlite",
            "annotations.jsonl",
            "event_annotations.json",
        ):
            if (folder / name).is_file():
                shutil.copy2(folder / name, temporary / name)
        if manifest:
            for key in ("frames", "events", "corrections"):
                source_asset = relative_asset(folder, manifest["artifacts"][key])
                if source_asset.is_file():
                    shutil.copy2(source_asset, temporary / copied["artifacts"][key])
        events_exist = (
            relative_asset(folder, manifest["artifacts"]["events"])
            if manifest
            else folder / "events.json"
        ).exists()
        if not events_exist:
            from tennis_ai.events import regenerate_events

            regenerate_events(
                temporary / "frames.jsonl",
                temporary / "events.json",
                temporary / "corrections.json",
            )
        if selected_version == 3:
            from tennis_ai.evidence import ASSET_VERSIONS, ASSETS, load_evidence

            if manifest and manifest["schema_version"] == 3:
                # Preserve every declared evidence asset, including additive assets.
                for name in manifest["artifacts"].values():
                    target = relative_asset(temporary, name)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(relative_asset(folder, name), target)
                copied = {**manifest, "media": copied["media"]}
            else:
                copied.update(
                    schema_version=3,
                    court_coordinate_system="far_left_x_right_y_near_m",
                    asset_versions=ASSET_VERSIONS,
                    review_policy_version="human-reviewed-v1",
                    derivation_versions={},
                    storage_policy="local-no-backup-explicit-export",
                    migration={
                        "from_version": 2,
                        "source_media_sha256": copied["media"]["sha256"],
                        "method": "additive-v1",
                    },
                )
                copied["artifacts"].update(ASSETS)
                document = json.loads((temporary / "events.json").read_text())
                document.update(schema_version=3, participants=[], assignments=[], links=[])
                for event in document["events"]:
                    if event.get("position") is not None:
                        event["position_source"] = "legacy_v2"
                atomic_json(temporary / "events.json", document)
                for key in ("rallies", "metrics", "insights"):
                    atomic_json(temporary / ASSETS[key], {"schema_version": 1, key: []})
                for key in ("tracks", "audit"):
                    (temporary / ASSETS[key]).touch()
            atomic_json(temporary / "manifest.json", copied)
            load_evidence(temporary, copied)
        summary["source"] = str(destination / copied["media"]["path"])
        atomic_json(temporary / "summary.json", summary)
        if destination.exists():
            raise ValueError("Package destination already exists")
        temporary.replace(destination)
    return destination
