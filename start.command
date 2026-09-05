#!/bin/zsh
set -e
cd "${0:A:h}"
if [[ ! -x .venv/bin/tennis-ai ]]; then
  echo "Tennis AI is not installed yet. Open README.md and follow Reproduce installation."
  read -k 1 "?Press any key to close."
  exit 1
fi
exec .venv/bin/tennis-ai app
