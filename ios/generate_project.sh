#!/bin/sh
set -eu
cd "$(dirname "$0")"
python3 generate_project.py
