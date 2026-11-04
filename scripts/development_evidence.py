"""Print public development provenance from an explicit non-media allowlist."""

import hashlib
import json
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
paths = [
    root / "pyproject.toml",
    root / "uv.lock",
    *sorted((root / "contracts").glob("*.schema.json")),
]
print(
    json.dumps(
        {
            "artifact_type": "development-only",
            "source_commit": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=root, text=True
            ).strip(),
            "files": {
                str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in paths
            },
            "bundled_models": [],
            "accuracy_status": "not-a-labelled-benchmark",
            "distribution": "unsigned-development-artifacts-only",
        },
        indent=2,
    )
)
