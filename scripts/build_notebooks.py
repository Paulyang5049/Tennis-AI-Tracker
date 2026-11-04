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
WHEEL = 'https://github.com/Paulyang5049/Tennis-AI-Tracker/releases/download/v0.3.0/tennis_ai_local-0.3.0-py3-none-any.whl'
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
wasb = [
    markdown(
        "# Benchmark WASB tennis ball detectors\nRuns the published WASB-SBDT evaluation (BMVC 2023) on the TrackNet tennis dataset: WASB, TrackNetV2, ResTrackNetV2 and MonoTrack, each with its tennis weights. Upstream has not released training code, so this notebook evaluates and does not train.\n\nThe split is upstream's: game1–game7 train, game8–game10 test, grouped by match. Treat game8–game10 as held-out. Do not tune thresholds on them. Upstream code and weights are MIT. The dataset licence has not been verified, so keep data, weights and outputs out of the repository and use them for local research only.\n\nThe first run downloads the upstream tennis weights and `Dataset.zip` (2.56 GB) into `MyDrive/TennisAI-external/` and reuses them after that. Results and logs are written to `TennisAI-external/wasb_results/`."
    ),
    markdown("## 1. Setup\nSelect **Runtime → Change runtime type → GPU**."),
    code("""import hashlib, json, os, shutil, subprocess, sys
from pathlib import Path
import torch
assert torch.cuda.is_available(), 'Choose a GPU runtime'
print('GPU:', torch.cuda.get_device_name(0), '| torch', torch.__version__)
from google.colab import drive
drive.mount('/content/drive')
EXT = Path('/content/drive/MyDrive/TennisAI-external')
WEIGHTS, RESULTS = EXT/'wasb_weights', EXT/'wasb_results'
RESULTS.mkdir(parents=True, exist_ok=True)
WEIGHTS.mkdir(parents=True, exist_ok=True)
total, used, free = shutil.disk_usage('/content/drive/MyDrive')
print(f'Drive free: {free/1e9:.1f} GB')"""),
    markdown(
        "## 2. Tennis weights\nGoogle Drive IDs from upstream `MODEL_ZOO.md` at the pinned commit. Files already in Drive are reused."
    ),
    code("""import gdown
WEIGHT_IDS = {
    'wasb': '14AeyIOCQ2UaQmbZLNQJa1H_eSwxUXk7z',
    'tracknetv2': '1BCnmvDX-LZpbkk4vlMEXMm-uzCoqJzDx',
    'restracknetv2': '112qHZpPWgqCeZbbFXC0oRulrVsokzWYZ',
    'monotrack': '1mC3yWf6ySlzF-1d-s_LNH1QWexHz2M3D',
}
for model, file_id in WEIGHT_IDS.items():
    target = WEIGHTS/f'{model}_tennis_best.pth.tar'
    if not target.exists():
        gdown.download(id=file_id, output=str(target), quiet=True)
    print(target.name, f'{target.stat().st_size/1e6:.1f} MB')"""),
    markdown(
        "## 3. Tennis dataset\nThe upstream SharePoint link needs its share cookie before the file URL resolves, so `curl` keeps a cookie jar. The archive is cached in Drive and unpacked to the faster local disk."
    ),
    code("""SHARE = 'https://nycu1-my.sharepoint.com/:u:/g/personal/tik_m365_nycu_edu_tw/ETCr6-M0e1VDhGCdMbvljcsBu31AJTO5xa_1cW8pHa7niA?e=55tLJ9'
ZIP, ZIP_BYTES = EXT/'Dataset.zip', 2_564_111_322
if not ZIP.exists() or ZIP.stat().st_size != ZIP_BYTES:
    jar, part = '/content/sharepoint.jar', Path('/content/Dataset.zip.part')
    subprocess.run(['curl', '-sSL', '-c', jar, '-b', jar, '-o', '/dev/null', SHARE], check=True)
    subprocess.run(['curl', '-SL', '--fail', '-c', jar, '-b', jar, '-o', str(part), SHARE + '&download=1'], check=True)
    assert part.stat().st_size == ZIP_BYTES, part.stat().st_size
    shutil.copy2(part, ZIP); part.unlink()
DATA = Path('/content/datasets')
if not (DATA/'tennis'/'game10').exists():
    DATA.mkdir(parents=True, exist_ok=True)
    subprocess.run(['unzip', '-q', '-o', str(ZIP), '-d', str(DATA)], check=True)
    (DATA/'Dataset').rename(DATA/'tennis')
print(sorted(p.name for p in (DATA/'tennis').iterdir()))"""),
    markdown(
        "## 4. WASB-SBDT code\nPinned to the upstream commit that was reviewed. Colab's current Python and PyTorch replace the Dockerfile's versions, which needs two compatibility changes. Hydra 1.2 fails on Python 3.11+, so this uses 1.3.2. NumPy 2 removed `np.Inf`, so the clone is patched to `np.inf`. Neither change affects the metrics."
    ),
    code("""import re
WASB_COMMIT = '923462cacdeb3353b84ddebdedb3f4b7a8553b0f'
HYDRA = 'hydra-core==1.3.2'
WASB = Path('/content/WASB-SBDT')
if not WASB.exists():
    subprocess.run(['git', 'clone', '-q', 'https://github.com/nttcom/WASB-SBDT', str(WASB)], check=True)
subprocess.run(['git', '-C', str(WASB), 'checkout', '-q', '--force', WASB_COMMIT], check=True)
PATCHED = []
for source in sorted((WASB/'src').rglob('*.py')):
    text = source.read_text()
    if re.search(r'np\\.Inf\\b', text):
        source.write_text(re.sub(r'np\\.Inf\\b', 'np.inf', text))
        PATCHED.append(str(source.relative_to(WASB)))
print('np.Inf -> np.inf in', PATCHED)
subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', HYDRA, 'einops', 'timm'], check=True)
(WASB/'pretrained_weights').mkdir(exist_ok=True)
for weight in WEIGHTS.glob('*_tennis_best.pth.tar'):
    shutil.copy2(weight, WASB/'pretrained_weights'/weight.name)"""),
    markdown(
        "## 5. Evaluate on the held-out test matches\nUpstream evaluation settings: score threshold 0.5 and a 4-pixel match distance. Each model's full log is saved to Drive."
    ),
    code("""MODELS = {
    'wasb': [],
    'tracknetv2': ['detector.postprocessor.use_hm_weight=False', 'tracker=intra_frame_peak'],
    'restracknetv2': ['detector.postprocessor.use_hm_weight=False', 'tracker=intra_frame_peak'],
    'monotrack': ['detector.postprocessor.use_hm_weight=False', 'tracker=intra_frame_peak'],
}
def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()
def total_metrics(log):
    # The last two table rows after '-- TOTAL --' are the header and the all-test-match values.
    lines = log[log.rfind('-- TOTAL --'):].splitlines()
    rows = [[cell.strip() for cell in line.split(' - ', 1)[-1].strip('| ').split('|')]
            for line in lines if 'utils.evaluator' in line and '|' in line and '----' not in line]
    return dict(zip(*rows[-2:])) if len(rows) >= 2 else None
runs = {}
for model, extra in MODELS.items():
    weight = WASB/'pretrained_weights'/f'{model}_tennis_best.pth.tar'
    out = RESULTS/model
    command = [sys.executable, 'main.py', '--config-name=eval', 'dataset=tennis', f'model={model}',
               f'dataset.root_dir={DATA/"tennis"}', 'runner.gpus=[0]', f'output_dir={out}',
               f'detector.model_path={weight}', *extra]
    print('$', ' '.join(command))
    result = subprocess.run(command, cwd=WASB/'src', capture_output=True, text=True)
    out.mkdir(parents=True, exist_ok=True)
    (out/'stdout.log').write_text(result.stdout + result.stderr)
    print('\\n'.join((result.stdout + result.stderr).strip().splitlines()[-15:]))
    runs[model] = {'returncode': result.returncode, 'test_total': total_metrics(result.stdout + result.stderr),
                   'weights_sha256': sha256(weight), 'command': command[1:]}"""),
    markdown(
        "## 6. Provenance\nThe summary records the inputs and each model's metrics over all test matches. Full logs are in `stdout.log`. These numbers come from broadcast footage only and are not evidence of accuracy on phone video."
    ),
    code("""summary = {
    'label': 'development-only benchmark; not a promotion gate',
    'wasb_commit': WASB_COMMIT,
    'compatibility': {'hydra': HYDRA, 'np_inf_patched': PATCHED},
    'weight_drive_ids': WEIGHT_IDS,
    'dataset': {'archive': 'Dataset.zip', 'bytes': ZIP.stat().st_size, 'sha256': sha256(ZIP), 'test_matches': ['game8', 'game9', 'game10']},
    'gpu': torch.cuda.get_device_name(0), 'torch': torch.__version__,
    'runs': runs,
}
(RESULTS/'summary.json').write_text(json.dumps(summary, indent=2))
print(json.dumps(summary, indent=2))"""),
]
for name, cells in [
    ("01_train_ball_yolo26.ipynb", ball),
    ("02_finetune_court.ipynb", court),
    ("03_benchmark_wasb_tennis.ipynb", wasb),
]:
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
