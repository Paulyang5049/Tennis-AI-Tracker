# Contributing to Tennis AI Local

Thank you for helping build an open tennis-analysis tool for players and developers. Contributions can be code, reproducible bug reports, documentation, design work, annotation tools or carefully consented test footage.

## Before you contribute

- Search existing issues and open a focused issue before starting a large change.
- Keep personal videos local. Only share footage when every identifiable participant has agreed to that use and redistribution.
- Do not add model weights, datasets, match videos or generated outputs to the repository.
- Document the source, license and intended use of every new dataset or model.
- Report accuracy on held-out footage and distinguish measured results from confidence or coverage.

## Development setup

Use Python 3.11 or 3.12 and FFmpeg:

```sh
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -e '.[dev]'
.venv/bin/tennis-ai setup
```

Run the targeted checks before opening a pull request:

```sh
.venv/bin/ruff check src scripts tests
.venv/bin/ruff format --check src scripts tests
.venv/bin/mypy src
.venv/bin/pytest -q
```

Tests must not require model downloads or private footage. Use small generated videos and fake model adapters for pipeline tests. For model improvements, include a concise evaluation table split by phone/broadcast and singles/doubles footage where the data permits it.

## Pull requests

Keep each pull request centered on one problem. Explain the trigger, the behavior before and after the change, and the checks you ran. Update the README or validation notes when behavior, installation or a limitation changes.

By contributing, you agree that your contribution is licensed under the repository's GNU AGPL v3 license. Third-party material remains under its original terms and must not be submitted unless redistribution is clearly permitted.
