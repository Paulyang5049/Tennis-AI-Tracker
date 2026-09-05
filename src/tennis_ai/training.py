"""Colab helpers shared with the distributable local application."""

import collections
import json
import random
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from tennis_ai.artifacts import package, sha256
from tennis_ai.geometry import iou
from tennis_ai.setup import BALL_COMMIT, COURT_COMMIT, download


def source_group(stem):
    """Conservative filename-family grouping, not a claim of known video identity."""
    stem = re.sub(r"\.rf\..*$", "", stem)
    stem = re.sub(r"_(jpg|png|jpeg)$", "", stem)
    group = re.sub(r"\d+", "#", stem)
    return group


def partition_groups(items, group_key, ratios=(0.7, 0.15, 0.15), seed=42):
    groups = collections.defaultdict(list)
    for item in items:
        groups[group_key(item)].append(item)
    if len(groups) < len(ratios):
        raise ValueError(
            "Too few independent filename groups. Supply source-video group IDs before splitting."
        )
    keys = sorted(groups)
    random.Random(seed).shuffle(keys)
    keys.sort(key=lambda key: len(groups[key]), reverse=True)
    splits: list[list[Any]] = [[] for _ in ratios]
    total = len(items)
    for key in keys:
        destination = min(range(len(ratios)), key=lambda i: len(splits[i]) / (total * ratios[i]))
        splits[destination].extend(groups[key])
    return splits


def prepare_ball(destination):
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / "upstream.zip"
    download(
        f"https://codeload.github.com/abdullahtarek/tennis_analysis/zip/{BALL_COMMIT}", archive
    )
    raw = destination / "raw"
    raw.mkdir(exist_ok=True)
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            name = member.filename
            if "/tennis-ball-detection-6/" not in name or member.is_dir():
                continue
            if "/images/" in name or "/labels/" in name:
                kind = "images" if "/images/" in name else "labels"
                target = raw / kind / Path(name).name
            elif Path(name).name.startswith("README"):
                target = destination / Path(name).name
            else:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(member) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
    archive.unlink()
    seen: dict[str, str] = {}
    items, duplicates = [], []
    for image in sorted((raw / "images").glob("*")):
        pixels = cv2.imread(str(image))
        if pixels is None:
            raise ValueError(f"Unreadable image: {image.name}")
        # Hash decoded pixels to catch identical imagery with different file encodings.
        import hashlib

        digest = hashlib.sha256(pixels.tobytes()).hexdigest()
        if digest in seen:
            duplicates.append([image.name, seen[digest]])
            continue
        seen[digest] = image.name
        label = raw / "labels" / f"{image.stem}.txt"
        if not label.exists():
            raise ValueError(f"Missing label: {label}")
        for line in label.read_text().splitlines():
            values = list(map(float, line.split()))
            if (
                len(values) != 5
                or values[0] != 0
                or not all(0 <= x <= 1 for x in values[1:])
                or min(values[3:]) <= 0
            ):
                raise ValueError(f"Invalid YOLO annotation: {label}")
        items.append(image)
    splits = partition_groups(items, lambda p: source_group(p.stem))
    manifest = []
    for name, images in zip(["train", "val", "test"], splits):
        for kind in ["images", "labels"]:
            (destination / name / kind).mkdir(parents=True, exist_ok=True)
        for image in images:
            shutil.copy2(image, destination / name / "images" / image.name)
            label = raw / "labels" / f"{image.stem}.txt"
            shutil.copy2(label, destination / name / "labels" / label.name)
            manifest.append(
                {
                    "file": image.name,
                    "split": name,
                    "group": source_group(image.stem),
                    "sha256": sha256(image),
                }
            )
    config = f"path: {destination}\ntrain: train/images\nval: val/images\ntest: test/images\nnames:\n  0: tennis ball\n"
    (destination / "data.yaml").write_text(config)
    audit = {
        "upstream_commit": BALL_COMMIT,
        "duplicates_removed": duplicates,
        "counts": dict(zip(["train", "val", "test"], map(len, splits))),
        "grouping": "Conservative filename families; source videos remain unverified. Near-duplicates may remain.",
        "manifest": manifest,
        "license": "CC BY 4.0; retain upstream README attribution",
    }
    (destination / "audit.json").write_text(json.dumps(audit, indent=2))
    return destination / "data.yaml", audit


def label_preview(data, split="train", count=6):
    import matplotlib.pyplot as plt

    data = Path(data)
    images = sorted((data / split / "images").glob("*"))[:count]
    fig, axes = plt.subplots(2, 3, figsize=(15, 8))
    for ax, image in zip(axes.flat, images):
        pixels = cv2.imread(str(image))
        if pixels is None:
            raise ValueError(f"Unreadable image: {image}")
        h, w = pixels.shape[:2]
        for line in (data / split / "labels" / f"{image.stem}.txt").read_text().splitlines():
            _, x, y, bw, bh = map(float, line.split())
            cv2.rectangle(
                pixels,
                (int((x - bw / 2) * w), int((y - bh / 2) * h)),
                (int((x + bw / 2) * w), int((y + bh / 2) * h)),
                (0, 255, 0),
                2,
            )
        ax.imshow(cv2.cvtColor(pixels, cv2.COLOR_BGR2RGB))
        ax.set_title(image.name[:24])
        ax.axis("off")
    return fig


def detection_counts(predictions, truth, threshold=0.5):
    pairs = sorted(
        [(iou(p, g), i, j) for i, p in enumerate(predictions) for j, g in enumerate(truth)],
        reverse=True,
    )
    used_p, used_g = set(), set()
    for score, i, j in pairs:
        if score >= threshold and i not in used_p and j not in used_g:
            used_p.add(i)
            used_g.add(j)
    return len(used_p), len(predictions) - len(used_p), len(truth) - len(used_g)


def evaluate_ball_images(weights, data, split, baseline=False, device=0):
    from ultralytics import YOLO

    model: Any = YOLO(str(weights))
    tp = fp = fn = 0
    for image in sorted((Path(data) / split / "images").glob("*")):
        pixels = cv2.imread(str(image))
        if pixels is None:
            raise ValueError(f"Unreadable image: {image}")
        h, w = pixels.shape[:2]
        truth = []
        for line in (Path(data) / split / "labels" / f"{image.stem}.txt").read_text().splitlines():
            _, x, y, bw, bh = map(float, line.split())
            truth.append([(x - bw / 2) * w, (y - bh / 2) * h, (x + bw / 2) * w, (y + bh / 2) * h])
        result = model.predict(
            pixels,
            classes=[32] if baseline else [0],
            conf=0.1,
            imgsz=1280,
            device=device,
            verbose=False,
        )[0]
        a, b, c = detection_counts(result.boxes.xyxy.cpu().tolist(), truth)
        tp += a
        fp += b
        fn += c
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": tp / max(1, tp + fp),
        "recall": tp / max(1, tp + fn),
        "confidence": 0.1,
        "iou": 0.5,
        "split": split,
    }


def train_ball(data_yaml, local_runs, drive_runs, resume=None, smoke=False):
    import torch
    from ultralytics import YOLO

    if not torch.cuda.is_available():
        raise RuntimeError("Select a Colab GPU runtime before training")
    drive_runs = Path(drive_runs)
    drive_runs.mkdir(parents=True, exist_ok=True)

    def persist(trainer):
        for name in ["last.pt", "best.pt"]:
            source = Path(trainer.save_dir) / "weights" / name
            if source.exists():
                temporary = drive_runs / (name + ".part")
                shutil.copy2(source, temporary)
                temporary.replace(drive_runs / name)
        for name in ["args.yaml", "results.csv"]:
            source = Path(trainer.save_dir) / name
            if source.exists():
                shutil.copy2(source, drive_runs / name)

    for batch in [4, 2, 1]:
        model: Any = YOLO(str(resume) if resume else "yolo26s.pt")
        if not smoke:
            model.add_callback("on_model_save", persist)
        try:
            result = model.train(
                data=str(data_yaml),
                epochs=1 if smoke else 100,
                patience=20,
                imgsz=1280,
                batch=batch,
                device=0,
                workers=2,
                cache=False,
                seed=42,
                deterministic=True,
                project=str(local_runs),
                name="smoke" if smoke else f"ball-b{batch}",
                exist_ok=False,
                resume=bool(resume),
                fraction=0.05 if smoke else 1.0,
                save=True,
                save_period=1,
                plots=True,
            )
            return Path(model.trainer.save_dir), result
        except torch.cuda.OutOfMemoryError:
            del model
            import gc

            gc.collect()
            torch.cuda.empty_cache()
            if batch == 1:
                raise
    raise RuntimeError("Training failed")


def prepare_court(destination):
    """Download original JSON/image archive, and audit/repartition by filename family."""
    import gdown

    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / "court.zip"
    result = gdown.download(
        id="1lhAaeQCmk2y440PmagA0KmIVBIysVMwu", output=str(archive), quiet=False
    )
    if not result or not zipfile.is_zipfile(archive):
        raise RuntimeError(
            "Court dataset download unavailable or not ZIP. Keep pretrained court model."
        )
    extracted = destination / "archive"
    extracted.mkdir(exist_ok=True)
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            target = (extracted / member.filename).resolve()
            if not target.is_relative_to(extracted):
                raise ValueError("Unsafe dataset archive path")
        bundle.extractall(extracted)
    annotations = list(extracted.rglob("data_train.json"))
    if len(annotations) != 1:
        raise ValueError("Expected one data_train.json in the original dataset")
    original = annotations[0].parent
    output = destination / "data"
    output.mkdir(exist_ok=True)
    if not (output / "images").exists():
        shutil.copytree(original / "images", output / "images")
    examples = json.loads((original / "data_train.json").read_text()) + json.loads(
        (original / "data_val.json").read_text()
    )
    seen, unique, duplicates = set(), [], []
    for item in examples:
        image = output / "images" / (item["id"] + ".png")
        digest = sha256(image)
        if digest in seen:
            duplicates.append(item["id"])
            continue
        seen.add(digest)
        if np.asarray(item["kps"]).shape != (14, 2):
            raise ValueError("Expected 14 court keypoints")
        unique.append(item)
    splits = partition_groups(unique, lambda item: source_group(item["id"]))
    for name, items in zip(["train", "val", "test"], splits):
        (output / f"data_{name}.json").write_text(json.dumps(items))
    audit = {
        "counts": list(map(len, splits)),
        "duplicates_removed": duplicates,
        "grouping": "Filename families, source identities unverified; evaluate phone footage independently.",
    }
    (output / "audit.json").write_text(json.dumps(audit, indent=2))
    for filename in ["tracknet.py", "dataset.py", "utils.py"]:
        download(
            f"https://raw.githubusercontent.com/yastrebksv/TennisCourtDetector/{COURT_COMMIT}/{filename}",
            destination / filename,
        )
    weights = destination / "pretrained.pt"
    if not weights.exists():
        gdown.download(id="1f-Co64ehgq4uddcQm1aFBDtbnyZhQvgG", output=str(weights), quiet=False)
    return output, audit


def train_court(workspace, drive_runs, epochs=50, smoke=False):
    """Original heatmap architecture, with optimizer and epoch recovery."""
    import os
    import sys

    import torch
    from torch.utils.data import DataLoader

    workspace = Path(workspace).resolve()
    drive_runs = Path(drive_runs).resolve()
    drive_runs.mkdir(parents=True, exist_ok=True)
    if not torch.cuda.is_available():
        raise RuntimeError("Court fine-tuning requires a Colab GPU runtime")
    sys.path.insert(0, str(workspace))
    previous = Path.cwd()
    os.chdir(workspace)
    try:
        from dataset import courtDataset
        from tracknet import BallTrackerNet

        model = BallTrackerNet(out_channels=15).cuda()
        optimizer = torch.optim.Adam(model.parameters(), lr=1e-5)
        checkpoint = drive_runs / "resume.pt"
        start, best = 0, float("inf")
        if checkpoint.exists() and not smoke:
            saved = torch.load(checkpoint, map_location="cpu", weights_only=True)
            model.load_state_dict(saved["model"])
            optimizer.load_state_dict(saved["optimizer"])
            start, best = saved["epoch"] + 1, saved["best"]
        else:
            model.load_state_dict(
                torch.load(workspace / "pretrained.pt", map_location="cpu", weights_only=True)
            )
        loaders = {
            name: DataLoader(
                courtDataset(name), batch_size=2, shuffle=name == "train", num_workers=2
            )
            for name in ["train", "val"]
        }
        # Pretrained inference is verified before changing weights.
        first = next(iter(loaders["val"]))[0].float().cuda()
        model.eval()
        with torch.no_grad():
            prediction = model(first).sigmoid()
        if prediction.shape[1:] != (15, 360, 640) or not torch.isfinite(prediction).all():
            raise ValueError("Court checkpoint inference failed")
        history = []
        for epoch in range(start, start + 1 if smoke else epochs):
            losses = {}
            for split, loader in loaders.items():
                model.train(split == "train")
                total, count = 0.0, 0
                for step, batch in enumerate(loader):
                    with torch.set_grad_enabled(split == "train"):
                        prediction = model(batch[0].float().cuda()).sigmoid()
                        loss = torch.nn.functional.mse_loss(prediction, batch[1].float().cuda())
                        if split == "train":
                            optimizer.zero_grad()
                            loss.backward()
                            optimizer.step()
                    total += loss.item()
                    count += 1
                    if (smoke and step >= 1) or (split == "train" and step >= 999):
                        break
                losses[split] = total / max(1, count)
            history.append({"epoch": epoch, **losses})
            print(history[-1], flush=True)
            if not smoke:
                if losses["val"] < best:
                    best = losses["val"]
                    torch.save(model.state_dict(), drive_runs / "best.pt")
                saved = {
                    "model": model.state_dict(),
                    "optimizer": optimizer.state_dict(),
                    "epoch": epoch,
                    "best": best,
                }
                torch.save(saved, drive_runs / "resume.part")
                (drive_runs / "resume.part").replace(checkpoint)
                (drive_runs / "history.json").write_text(json.dumps(history, indent=2))
        if not smoke:
            return package(
                drive_runs / "best.pt",
                drive_runs / "court-bundle",
                "court",
                [360, 640],
                {"best_val_heatmap_mse": best},
            )
        return history
    finally:
        os.chdir(previous)
        sys.path.remove(str(workspace))
