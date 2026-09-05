"""Generate portable notebooks using the same tested training helpers as the app."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def markdown(text):
    return {"cell_type": "markdown", "metadata": {}, "source": text.splitlines(keepends=True)}


def code(text):
    return {
        "cell_type": "code",
        "metadata": {},
        "source": text.splitlines(keepends=True),
        "execution_count": None,
        "outputs": [],
    }


bootstrap = [
    markdown(
        "## 1. Setup\nSelect **Runtime → Change runtime type → GPU**. This installs the versioned project wheel from the public GitHub release, including the same model and export code used locally."
    ),
    code("""from google.colab import files, drive
from pathlib import Path
import subprocess, sys
WHEEL = 'https://github.com/Paulyang5049/tennis-ai-local/releases/download/v0.2.0/tennis_ai_local-0.2.0-py3-none-any.whl'
subprocess.run([sys.executable, '-m', 'pip', 'install', WHEEL], check=True)
print('If pip replaced an already imported torch/numpy, restart the session before continuing.')"""),
    code("""import torch, importlib.metadata
assert torch.cuda.is_available(), 'Choose a GPU runtime'
print('GPU:', torch.cuda.get_device_name(0))
print({n: importlib.metadata.version(n) for n in ['torch', 'ultralytics', 'numpy']})
drive.mount('/content/drive')
DRIVE = Path('/content/drive/MyDrive/TennisAI')
DRIVE.mkdir(parents=True, exist_ok=True)
print('Checkpoints will be saved to', DRIVE)"""),
]

ball = [
    markdown(
        "# Train the YOLO26 tennis-ball detector\nLocal replay uses pretrained YOLO26 for people/rackets/pose. This notebook fine-tunes a separate ball detector. Default: YOLO26s, 1280 px, 100 epochs, patience 20, batch 4 → 2 → 1 if GPU memory is insufficient. Training and datasets live on Colab's temporary disk; recoverable checkpoints go to Drive.\n\nPublic dataset: abdullahtarek/tennis_analysis, Roboflow tennis-ball-detection v6, CC BY 4.0. Keep attribution with derivatives."
    ),
    *bootstrap,
    markdown(
        "## 2. Download and audit\nThe repository's original 428/100/50 split is **not** blindly reused. Exact decoded-image duplicates are removed and conservative filename families are kept together. Filename families do not prove video identity: inspect `audit.json`, and use separate real phone/broadcast clips for final validation."
    ),
    code("""from tennis_ai.training import prepare_ball, label_preview
DATA = Path('/content/tennis-ball')
try:
    data_yaml, audit = prepare_ball(DATA)
    print({k:v for k,v in audit.items() if k != 'manifest'})
except Exception as error:
    raise RuntimeError('Dataset unavailable or audit failed. The local COCO baseline remains usable; fix the data issue before training.') from error
label_preview(DATA)"""),
    markdown(
        "## 3. Smoke test\nRun one short epoch before committing to full training. This does not overwrite the recoverable full-training checkpoint."
    ),
    code("""from tennis_ai.training import train_ball
train_ball(data_yaml, '/content/ball-runs', DRIVE/'ball', smoke=True)"""),
    markdown(
        "## 4. Train or resume\nSet `RESUME=True` after a disconnect to use Drive's last checkpoint. Re-run setup and data preparation in a fresh session first."
    ),
    code("""import shutil
RESUME = False
checkpoint = None
if RESUME:
    checkpoint = Path('/content/ball-resume.pt')
    shutil.copy2(DRIVE/'ball'/'last.pt', checkpoint)
run, training_result = train_ball(data_yaml, '/content/ball-runs', DRIVE/'ball', resume=checkpoint)
print('Completed:', run)"""),
    markdown(
        "## 5. Compare baseline and candidate\nBoth detectors are evaluated against the same tennis-ball labels, with the baseline's COCO sports-ball class mapped correctly. Validation selects a candidate; test results are reported separately. Image recall is not trajectory coverage."
    ),
    code("""import json
from tennis_ai.training import evaluate_ball_images
best = DRIVE/'ball'/'best.pt'
report = {}
for split in ['val', 'test']:
    report[split] = {
        'baseline': evaluate_ball_images('yolo26s.pt', DATA, split, baseline=True),
        'candidate': evaluate_ball_images(best, DATA, split),
    }
a, b = report['val']['baseline'], report['val']['candidate']
report['image_candidate_pass'] = b['recall'] > a['recall'] and b['fp'] <= a['fp']
report['promotion'] = 'Candidate only: validate held-out video coverage and false detections before selecting locally.'
(DRIVE/'ball'/'evaluation.json').write_text(json.dumps(report, indent=2))
print(json.dumps(report, indent=2))"""),
    markdown(
        "## 6. Export to the Mac\nDownload and unzip this bundle inside the local project's `models/` folder. In the app, enter its folder in **Custom Colab model bundles**, verify it, then analyze the same held-out clips with baseline and candidate. Keep the baseline unless observed ball coverage improves without more false detections."
    ),
    code("""from tennis_ai.artifacts import package
bundle = package(best, DRIVE/'ball-bundle', 'ball', 1280, report)
archive = shutil.make_archive('/content/ball-bundle', 'zip', bundle)
files.download(archive)"""),
]
court = [
    markdown(
        "# Optional court model fine-tuning\nThe local app already uses the original pretrained TennisCourtDetector. Train this model only when you want to test a court-specific improvement. This keeps the original 15-channel heatmap architecture (14 court keypoints plus a centre point), not a human-pose checkpoint. Downloaded upstream code is not bundled with the local app."
    ),
    *bootstrap,
    markdown(
        "## 2. Download and inspect\nThe original dataset contains 8,841 images according to its README. This step validates annotations, removes file duplicates and groups filename families before splitting. If the download or grouping fails, keep the original local court model and resolve the data issue. The dataset download can take several minutes."
    ),
    code("""from tennis_ai.training import prepare_court
WORK = Path('/content/court-work')
data, audit = prepare_court(WORK)
print(audit)"""),
    code("""import cv2, json, matplotlib.pyplot as plt
sample = json.loads((data/'data_train.json').read_text())[0]
image = cv2.imread(str(data/'images'/(sample['id']+'.png')))
for i, (x,y) in enumerate(sample['kps']):
    cv2.circle(image, (int(x),int(y)), 5, (0,255,0), -1)
    cv2.putText(image, str(i), (int(x),int(y)), cv2.FONT_HERSHEY_SIMPLEX, .5, (0,0,255), 1)
plt.figure(figsize=(14,8)); plt.imshow(cv2.cvtColor(image, cv2.COLOR_BGR2RGB)); plt.axis('off');"""),
    markdown(
        "## 3. Verify pretrained inference and training\nThe helper loads the original weights, verifies finite 15×360×640 outputs, then runs two training and validation batches."
    ),
    code("""from tennis_ai.training import train_court
train_court(WORK, DRIVE/'court', smoke=True)"""),
    markdown(
        "## 4. Optional fine-tuning\nChange `RUN_FINE_TUNING` to True to run up to 50 epochs. Adam, learning rate 1e-5, batch size 2. Drive checkpoints include optimizer state and completed epoch; a rerun resumes automatically. Selection uses validation heatmap loss. This does not establish real-world court accuracy."
    ),
    code("""RUN_FINE_TUNING = False
if RUN_FINE_TUNING:
    bundle = train_court(WORK, DRIVE/'court', epochs=50)
    print('Bundle:', bundle)
else:
    print('Skipped: retain the pretrained court model.')"""),
    markdown(
        "## 5. Export\nAfter fine-tuning, download the bundle, unzip inside `models/`, and verify in the local app. Compare court-keypoint error on held-out phone and broadcast annotations with `tennis-ai evaluate`. Keep the original model if the candidate is worse."
    ),
    code("""import shutil
if RUN_FINE_TUNING:
    archive = shutil.make_archive('/content/court-bundle', 'zip', bundle)
    files.download(archive)"""),
]
for name, cells in [("01_train_ball_yolo26.ipynb", ball), ("02_finetune_court.ipynb", court)]:
    notebook = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python"},
            "accelerator": "GPU",
            "colab": {"provenance": []},
        },
        "cells": cells,
    }
    for i, cell in enumerate(cells):
        cell["id"] = f"cell-{i:03}"
    (ROOT / "notebooks" / name).write_text(json.dumps(notebook, indent=2))
