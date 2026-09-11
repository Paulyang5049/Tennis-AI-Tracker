"""Report development/beta/release evidence readiness without uploading anything."""

import argparse
import json
import re
from pathlib import Path

REQUIRED = {
    "development": (),
    "internal-testflight": (
        "contracts",
        "phone_accuracy",
        "event_accuracy",
        "coreml_parity",
        "physical_device",
        "signing",
    ),
    "formal": (
        "contracts",
        "phone_accuracy",
        "event_accuracy",
        "coreml_parity",
        "physical_device",
        "signing",
        "model_provenance",
        "distribution_licence",
        "release_notes",
    ),
}


def digest(value, length):
    return isinstance(value, str) and re.fullmatch(rf"[a-f0-9]{{{length}}}", value) is not None


def assess(evidence, channel, commit=None):
    missing = []
    if channel != "development":
        if not digest(evidence.get("source_commit"), 40) or (
            commit and evidence.get("source_commit") != commit
        ):
            missing.append("exact_source_commit")
        if not digest(evidence.get("model_sha256"), 64):
            missing.append("versioned_model_sha256")
        if evidence.get("protected_environment_approved") is not True:
            missing.append("protected_environment_approval")
        for name in REQUIRED[channel]:
            gate = evidence.get("gates", {}).get(name, {})
            if gate.get("status") != "passed" or not digest(gate.get("evidence_sha256"), 64):
                missing.append(name)
    return {
        "channel": channel,
        "ready": not missing,
        "missing": missing,
        "scope": "Evidence readiness only; signed delivery also requires live protected-environment and signing checks.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", default="docs/data/release-gates.json")
    parser.add_argument("--channel", choices=REQUIRED, default="development")
    parser.add_argument("--commit")
    parser.add_argument(
        "--dry-run", action="store_true", help="Report missing gates without a nonzero exit"
    )
    args = parser.parse_args()
    path = Path(args.evidence)
    report = assess(
        json.loads(path.read_text()) if path.exists() else {}, args.channel, args.commit
    )
    print(json.dumps(report, indent=2))
    if not report["ready"] and not args.dry_run:
        parser.exit(1)


if __name__ == "__main__":
    main()
