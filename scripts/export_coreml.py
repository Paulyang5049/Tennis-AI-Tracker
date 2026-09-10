#!/usr/bin/env python3
"""Offline, hash-checked YOLO26 Core ML export and labelled conversion parity.

The inspection, verification and metric helpers use only the standard library.
No imports of the desktop tennis_ai package or dependency auto-installation.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import shutil
import statistics
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
CLASS_NAMES = {"0": "person", "32": "sports ball", "38": "tennis racket"}
PINS = {
    "ultralytics": "8.4.140",
    "coremltools": "9.0",
    "numpy": "2.3.5",
    "torch": "2.7.0",
    "torchvision": "0.22.0",
    "opencv-python": "4.11.0.86",
    "scikit-learn": "1.7.2",
    "Pillow": "11.3.0",
}
DEFAULT_HASH = "646f8bc3fe0a656803d95c294f7852321748cb29d13466a1af8862e2db384a1b"


def sha256(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def local_file(value: str | Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"Expected an existing local, non-symlink file: {path}")
    return path.resolve()


def contained(root: Path, relative: str) -> Path:
    path = PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts or "\\" in relative or not path.parts:
        raise ValueError(f"Unsafe relative path: {relative}")
    resolved = root.joinpath(*path.parts).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError(f"Path escapes package: {relative}")
    return resolved


def package_files(package: Path) -> list[dict]:
    if not package.is_dir() or package.is_symlink():
        raise ValueError("Expected a non-symlink .mlpackage directory")
    files = []
    for path in sorted(package.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"Package symlinks are unsupported: {path}")
        if path.is_file():
            files.append(
                {
                    "path": path.relative_to(package).as_posix(),
                    "sha256": sha256(path),
                    "size_bytes": path.stat().st_size,
                }
            )
    if not files:
        raise ValueError("Empty model package")
    return files


def package_digest(files: list[dict]) -> str:
    """Hash UTF-8 lines: relative_path NUL sha256 NUL decimal_size LF, sorted by path."""
    data = "".join(
        f"{f['path']}\0{f['sha256']}\0{f['size_bytes']}\n"
        for f in sorted(files, key=lambda f: f["path"])
    )
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def check_source(args: argparse.Namespace) -> tuple[Path, dict]:
    weights = local_file(args.weights)
    if weights.suffix != ".pt":
        raise ValueError("Only local YOLO26 .pt detection weights are supported")
    digest = sha256(weights)
    expected = args.expected_sha256
    if not expected and weights.name == "yolo26s.pt":
        expected = DEFAULT_HASH
    if not expected or len(expected) != 64 or digest != expected.lower():
        raise ValueError(
            "Weights checksum mismatch or missing --expected-sha256; "
            "verify trusted provenance before loading PyTorch weights"
        )
    return weights, {
        "filename": weights.name,
        "sha256": digest,
        "url": args.source_url,
        "license": args.license,
        "redistribution_status": "not_assessed",
    }


def environment() -> dict:
    installed, problems = {}, []
    for name, expected in PINS.items():
        try:
            installed[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            installed[name] = None
        if installed[name] != expected:
            problems.append(f"{name}: expected {expected}, found {installed[name] or 'missing'}")
    if sys.version_info[:2] != (3, 11):
        problems.append("Use the isolated CPython 3.11 toolchain")
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        problems.append("This pinned release toolchain targets macOS arm64")
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "dependencies": installed,
        "problems": problems,
        "status": "ready" if not problems else "pending",
    }


def require_environment() -> dict:
    result = environment()
    if result["problems"]:
        raise ValueError(
            "Conversion pending; isolated dependencies unavailable/incompatible: "
            + "; ".join(result["problems"])
        )
    # Ultralytics must never repair this environment or fetch anything implicitly.
    os.environ["YOLO_AUTOINSTALL"] = "false"
    os.environ["YOLO_OFFLINE"] = "true"
    return result


def make_manifest(
    package: Path,
    source: dict,
    size: int,
    bits: int,
    output_name: str,
    shape: list[int],
    runtime: dict,
) -> dict:
    if len(shape) != 3 or shape[0] != 1 or shape[-1] != 6 or shape[1] < 1:
        raise ValueError(f"Unsupported YOLO output shape {shape}; expected [1,N,6]")
    files = package_files(package)
    digest = package_digest(files)
    return {
        "schema_version": 1,
        "model_id": f"yolo26-{digest[:16]}",
        "model_file": "Detector.mlpackage",
        "source": source,
        "package_sha256": digest,
        "files": files,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "environment": runtime,
        "input": {
            "name": "image",
            "width": size,
            "height": size,
            "color_space": "RGB",
            "scale": 1 / 255,
            "bias": [0, 0, 0],
            "resize": "letterbox",
            "interpolation": "bilinear",
            "padding_value": 114,
            "orientation": "oriented_pixels_top_left",
            "rounding": "floor(value+0.5)",
            "padding_alignment": "center_floor_left_top",
        },
        "output": {
            "name": output_name,
            "shape": shape,
            "layout": "xyxy_confidence_class",
            "coordinates": "input_pixels_top_left",
            "nms": False,
        },
        "classes": CLASS_NAMES,
        "confidence_threshold": 0.25,
        "quantization": "fp16" if bits == 16 else "w8a16",
        "validation": {
            "status": "pending",
            "conversion_parity": "pending",
            "phone_accuracy": "pending",
            "iphone_15_pro_performance": "pending",
            "reason": "Export success is not model or device validation",
        },
    }


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def export(args: argparse.Namespace) -> dict:
    weights, source = check_source(args)
    runtime = require_environment()
    destination = args.output.resolve()
    if destination.exists():
        raise ValueError(f"Output already exists; use a new release directory: {destination}")
    import coremltools as ct
    from ultralytics import YOLO

    destination.parent.mkdir(parents=True, exist_ok=True)
    # Exporter deletes an existing sibling package: keep it inside a fresh staging directory.
    with tempfile.TemporaryDirectory(prefix=".coreml-", dir=destination.parent) as temp:
        staging = Path(temp)
        staged_weights = staging / "Detector.pt"
        shutil.copyfile(weights, staged_weights)
        model = YOLO(str(staged_weights), task="detect")
        if model.task != "detect" or not getattr(model.model, "end2end", False):
            raise ValueError("The app decoder requires a YOLO26 end-to-end detection model")
        if any(model.names.get(int(k)) != v for k, v in CLASS_NAMES.items()):
            raise ValueError("This app model must retain COCO class IDs 0,32,38")
        exported = Path(
            model.export(
                format="coreml",
                imgsz=args.imgsz,
                batch=1,
                dynamic=False,
                nms=False,
                end2end=True,
                quantize=args.quantize,
                device="cpu",
            )
        )
        if not exported.is_dir() or exported.suffix != ".mlpackage":
            raise ValueError("Exporter did not produce the required ML Program .mlpackage")
        spec = ct.models.MLModel(str(exported), skip_model_load=True).get_spec()
        inputs, outputs = list(spec.description.input), list(spec.description.output)
        if (
            len(inputs) != 1
            or inputs[0].name != "image"
            or inputs[0].type.imageType.width != args.imgsz
            or inputs[0].type.imageType.height != args.imgsz
            or len(outputs) != 1
        ):
            raise ValueError("Exported model interface differs from the app contract")
        manifest = make_manifest(
            exported,
            source,
            args.imgsz,
            args.quantize,
            outputs[0].name,
            list(outputs[0].type.multiArrayType.shape),
            runtime,
        )
        release = staging / "release"
        release.mkdir()
        shutil.move(str(exported), release / "Detector.mlpackage")
        write_json(release / "ModelManifest.json", manifest)
        # This output is isolated and complete before becoming visible to a consumer.
        shutil.move(str(release), destination)
    return {
        "status": "exported_unvalidated",
        "directory": str(destination),
        "package_sha256": manifest["package_sha256"],
        "validation": manifest["validation"],
    }


def verify(manifest_path: Path) -> dict:
    manifest_path = local_file(manifest_path)
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("schema_version") != 1 or manifest.get("model_file") != "Detector.mlpackage":
        raise ValueError("Unsupported model manifest")
    package = contained(manifest_path.parent, manifest["model_file"])
    actual = package_files(package)
    if actual != manifest.get("files") or package_digest(actual) != manifest.get("package_sha256"):
        raise ValueError(
            "Model package integrity check failed (modified, missing or additional files)"
        )
    output = manifest["output"]
    shape = output["shape"]
    if (
        output["layout"] != "xyxy_confidence_class"
        or output["nms"]
        or output.get("coordinates") != "input_pixels_top_left"
        or len(shape) != 3
        or shape[0] != 1
        or shape[2] != 6
        or any(type(value) is not int or value < 1 for value in shape)
    ):
        raise ValueError("Unsupported model output contract")
    return manifest


def letterbox_geometry(width: int, height: int, size: int) -> dict:
    if min(width, height, size) <= 0:
        raise ValueError("Image dimensions must be positive")
    ratio = min(size / width, size / height)
    resized_w = max(1, math.floor(width * ratio + 0.5))
    resized_h = max(1, math.floor(height * ratio + 0.5))
    return {
        "width": width,
        "height": height,
        "resized_width": resized_w,
        "resized_height": resized_h,
        "left": (size - resized_w) // 2,
        "top": (size - resized_h) // 2,
    }


def decode_rows(rows, geometry: dict, threshold: float) -> list[dict]:
    result = []
    for row in rows:
        if len(row) != 6 or not all(math.isfinite(float(v)) for v in row):
            continue
        x1, y1, x2, y2, confidence, label = map(float, row)
        if confidence < threshold or confidence > 1 or not label.is_integer():
            continue
        if str(int(label)) not in CLASS_NAMES:
            continue
        box = []
        for value, offset, resized, original in (
            (x1, geometry["left"], geometry["resized_width"], geometry["width"]),
            (y1, geometry["top"], geometry["resized_height"], geometry["height"]),
            (x2, geometry["left"], geometry["resized_width"], geometry["width"]),
            (y2, geometry["top"], geometry["resized_height"], geometry["height"]),
        ):
            box.append(max(0.0, min(original, (value - offset) * original / resized)))
        if box[2] > box[0] and box[3] > box[1]:
            result.append({"class_id": int(label), "box": box, "confidence": confidence})
    return result


def iou(a: list[float], b: list[float]) -> float:
    intersection = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(
        0, min(a[3], b[3]) - max(a[1], b[1])
    )
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - intersection
    return intersection / union if union > 0 else 0.0


def counts(predictions: list[dict], truth: list[dict], class_id: int, height: int) -> dict:
    """Confidence-ranked one-to-one matching. Ball: 6 pixels at 1080p; others: IoU .5."""
    expected = [d for d in truth if d["class_id"] == class_id]
    predicted = sorted(
        (d for d in predictions if d["class_id"] == class_id),
        key=lambda d: d["confidence"],
        reverse=True,
    )
    available = set(range(len(expected)))
    tp = 0
    for pred in predicted:
        choices = []
        for index in available:
            a, b = pred["box"], expected[index]["box"]
            if class_id == 32:
                distance = math.hypot(
                    (a[0] + a[2] - b[0] - b[2]) / 2, (a[1] + a[3] - b[1] - b[3]) / 2
                )
                if distance <= 6 * height / 1080:
                    choices.append((distance, index))
            else:
                overlap = iou(a, b)
                if overlap >= 0.5:
                    choices.append((-overlap, index))
        if choices:
            available.remove(min(choices)[1])
            tp += 1
    return {"tp": tp, "fp": len(predicted) - tp, "fn": len(expected) - tp}


def metrics(count: dict) -> dict:
    tp, fp, fn = (count[key] for key in ("tp", "fp", "fn"))
    return {
        **count,
        "precision": tp / (tp + fp) if tp + fp else 0.0,
        "recall": tp / (tp + fn) if tp + fn else None,
    }


def parity(reference: dict, converted: dict) -> dict:
    if reference["tp"] + reference["fn"] == 0 or reference["tp"] == 0:
        return {"status": "pending", "reason": "No true-positive reference ball evidence"}
    drops = {key: (reference[key] - converted[key]) * 100 for key in ("precision", "recall")}
    return {
        "status": "passed" if all(drop <= 2.0 + 1e-9 for drop in drops.values()) else "failed",
        "drop_percentage_points": drops,
        "maximum_drop_percentage_points": 2.0,
    }


def load_frames(path: Path) -> list[dict]:
    data = json.loads(local_file(path).read_text())
    frames = data.get("frames", [])
    if data.get("schema_version") != 1 or not frames:
        raise ValueError("Expected labelled frame manifest schema_version=1 with nonempty frames")
    seen = set()
    for frame in frames:
        if frame.get("split") != "test" or not frame.get("match_id"):
            raise ValueError("Benchmark frames require split=test and original match_id")
        image = local_file(contained(path.parent, frame["image"]))
        digest = sha256(image)
        if digest != frame.get("sha256") or digest in seen:
            raise ValueError("Frame checksum mismatch or duplicate frame content")
        seen.add(digest)
        for item in frame["detections"]:
            box = item.get("box", [])
            if (
                str(item.get("class_id")) not in CLASS_NAMES
                or len(box) != 4
                or not all(isinstance(x, (int, float)) and math.isfinite(x) for x in box)
                or box[2] <= box[0]
                or box[3] <= box[1]
            ):
                raise ValueError("Invalid ground-truth class_id or oriented xyxy pixel box")
    return frames


def benchmark(args: argparse.Namespace) -> dict:
    weights, source = check_source(args)
    manifest = verify(args.manifest)
    if source["sha256"] != manifest["source"]["sha256"]:
        raise ValueError("Reference weights differ from exported source")
    frames = load_frames(args.frames)
    runtime = require_environment()
    import coremltools as ct
    import numpy as np
    import torch
    from PIL import Image
    from ultralytics import YOLO

    torch.set_num_threads(1)
    torch_model = YOLO(str(weights), task="detect").model.cpu().float().eval()
    torch_model.fuse(verbose=False)
    if not getattr(torch_model, "end2end", False):
        raise ValueError("Benchmark reference must use YOLO26 end-to-end detection")
    coreml_model = ct.models.MLModel(
        str(args.manifest.parent / manifest["model_file"]), compute_units=ct.ComputeUnit.ALL
    )
    size = manifest["input"]["width"]
    threshold = args.confidence if args.confidence is not None else manifest["confidence_threshold"]
    totals = {
        kind: {key: {"tp": 0, "fp": 0, "fn": 0} for key in CLASS_NAMES}
        for kind in ("pytorch", "coreml")
    }
    timings = {key: [] for key in totals}
    observations = []
    for frame in frames:
        with Image.open(contained(args.frames.parent, frame["image"])) as original:
            # Fixtures must already be oriented, as AnalysisPackage v2 requires.
            if original.getexif().get(274, 1) != 1:
                raise ValueError("Apply image orientation before constructing benchmark frames")
            rgb = original.convert("RGB")
        geometry = letterbox_geometry(*rgb.size, size)
        image = Image.new("RGB", (size, size), (114, 114, 114))
        resized = rgb.resize(
            (geometry["resized_width"], geometry["resized_height"]), Image.Resampling.BILINEAR
        )
        image.paste(resized, (geometry["left"], geometry["top"]))
        tensor = torch.from_numpy(np.asarray(image).copy()).permute(2, 0, 1).unsqueeze(0)
        tensor = tensor.float() / 255
        if not observations:
            with torch.inference_mode():
                torch_model(tensor)
            coreml_model.predict({manifest["input"]["name"]: image})
        start = time.perf_counter()
        with torch.inference_mode():
            reference = torch_model(tensor)
        timings["pytorch"].append((time.perf_counter() - start) * 1000)
        reference = reference[0] if isinstance(reference, tuple) else reference
        start = time.perf_counter()
        converted = coreml_model.predict({manifest["input"]["name"]: image})
        timings["coreml"].append((time.perf_counter() - start) * 1000)
        outputs = {
            "pytorch": reference.detach().cpu().numpy(),
            "coreml": converted[manifest["output"]["name"]],
        }
        evidence = {
            "image": frame["image"],
            "sha256": frame["sha256"],
            "match_id": frame["match_id"],
            "predictions": {},
        }
        for kind, output in outputs.items():
            if list(output.shape) != manifest["output"]["shape"]:
                raise ValueError(f"Runtime tensor shape differs from manifest: {output.shape}")
            predictions = decode_rows(output[0], geometry, threshold)
            evidence["predictions"][kind] = predictions
            for key in CLASS_NAMES:
                count = counts(predictions, frame["detections"], int(key), rgb.height)
                for metric in count:
                    totals[kind][key][metric] += count[metric]
        observations.append(evidence)
    measured = {
        kind: {key: metrics(count) for key, count in classes.items()}
        for kind, classes in totals.items()
    }
    result = {
        "schema_version": 1,
        "status": "measured",
        "environment": runtime,
        "package_sha256": manifest["package_sha256"],
        "weights_sha256": source["sha256"],
        "frame_manifest_sha256": sha256(args.frames),
        "confidence_threshold": threshold,
        "frame_count": len(frames),
        "match_count": len({f["match_id"] for f in frames}),
        "metrics": measured,
        "ball_conversion_parity": parity(measured["pytorch"]["32"], measured["coreml"]["32"]),
        "latency_ms": {
            kind: {
                "median": statistics.median(values),
                "p95": sorted(values)[math.ceil(len(values) * 0.95) - 1],
            }
            for kind, values in timings.items()
        },
        "latency_scope": "macOS prediction only; excludes decode/preprocess; one warmup",
        "phone_accuracy": "pending",
        "iphone_15_pro_performance": "pending",
        "observations": observations,
    }
    if args.report.exists():
        raise ValueError("Benchmark report exists; choose a new report path")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    write_json(args.report, result)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("inspect", "export", "benchmark"):
        sub = commands.add_parser(command)
        sub.add_argument("--weights", type=Path, default=ROOT / "models/yolo26s.pt")
        sub.add_argument("--expected-sha256")
        sub.add_argument("--source-url", default="https://github.com/ultralytics/assets/releases")
        sub.add_argument("--license", default="AGPL-3.0 (Ultralytics); distribution not assessed")
        if command == "export":
            sub.add_argument("--output", type=Path, required=True)
            sub.add_argument("--imgsz", type=int, choices=(640, 960, 1280), default=640)
            sub.add_argument("--quantize", type=int, choices=(16, 8), default=16)
        if command == "benchmark":
            sub.add_argument("--manifest", type=Path, required=True)
            sub.add_argument("--frames", type=Path, required=True)
            sub.add_argument("--report", type=Path, required=True)
            sub.add_argument("--confidence", type=float)
    commands.add_parser("verify").add_argument("--manifest", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "inspect":
            _, source = check_source(args)
            result = {"source": source, "environment": environment()}
        elif args.command == "export":
            result = export(args)
        elif args.command == "verify":
            manifest = verify(args.manifest)
            result = {"status": "integrity_verified", "package_sha256": manifest["package_sha256"]}
        else:
            if args.confidence is not None and not 0 < args.confidence <= 1:
                raise ValueError("confidence must be in (0,1]")
            result = benchmark(args)
    except Exception as exc:
        print(json.dumps({"status": "pending_or_failed", "error": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
