"""Package the canonical contracts for installed, completely offline validators."""

import argparse
import json
from pathlib import Path


def generated(root):
    schemas = {
        path.name: json.loads(path.read_text())
        for path in sorted((root / "contracts").glob("*.schema.json"))
    }
    return json.dumps(schemas, indent=2, ensure_ascii=False) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    target = root / "src/tennis_ai/contract_schemas.json"
    content = generated(root)
    if args.check:
        if not target.exists() or target.read_text() != content:
            parser.exit(1, "Packaged schemas are stale; run scripts/sync_contract_schemas.py\n")
    else:
        target.write_text(content)


if __name__ == "__main__":
    main()
