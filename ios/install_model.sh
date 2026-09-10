#!/bin/sh
set -eu
cd "$(dirname "$0")"
source_dir=${1:-../mobile-toolchain/exports/yolo26s-640-fp16}
[ -f "$source_dir/ModelManifest.json" ] && [ -d "$source_dir/Detector.mlpackage" ] || { echo 'Model export is missing' >&2; exit 1; }
mkdir -p TennisApp/Resources/Models
cp "$source_dir/ModelManifest.json" TennisApp/Resources/Models/ModelManifest.json
# ditto updates the generated model resource only.
ditto "$source_dir/Detector.mlpackage" TennisApp/Resources/Models/Detector.mlpackage
./generate_project.sh
