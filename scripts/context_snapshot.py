"""Print a bounded, read-only execution capsule from allowlisted project sources."""

import argparse
import re
import subprocess
from pathlib import Path

DEFAULT_PLAN = Path("docs/plans/2026-09-11-1411-feat-tennis-coaching-intelligence-plan.md")


def source(root, path):
    target = root / path
    if target.is_symlink() or not target.resolve().is_relative_to(root.resolve()):
        raise ValueError("Context source must stay inside the repository without symlinks")
    if not target.exists():
        return []
    if target.stat().st_size > 256_000:
        raise ValueError("Context source exceeds size limit")
    # Do not carry accidental media paths, local paths or secret-shaped lines forward.
    return [
        line[:240]
        for line in target.read_text().splitlines()
        if not re.search(
            r"/Users/|/home/|(?:token|secret|password|api_key)\s*[:=]|\S+\.(?:mp4|mov|m4v)\b",
            line,
            re.I,
        )
    ]


def section(lines, pattern, limit):
    selected = []
    level = None
    for line in lines:
        heading = re.match(r"^(#+) ", line)
        if level is None:
            if re.search(pattern, line, re.I):
                level = len(heading[1]) if heading else 2
            else:
                continue
        elif heading and len(heading[1]) <= level:
            break
        selected.append(line)
    return selected[:limit]


def snapshot(root, unit, plan=DEFAULT_PLAN):
    root = Path(root).resolve()
    plan = Path(plan)
    if not re.fullmatch(r"U[0-7]", unit):
        raise ValueError("Choose U0 through U7")
    if plan.is_absolute() or ".." in plan.parts or plan.parts[:2] != ("docs", "plans"):
        raise ValueError("Plan source must be inside docs/plans")
    rules = source(root, Path("AGENTS.md"))
    lines = source(root, plan)
    active = section(lines, rf"^### {unit}\b", 45)
    if not active:
        raise ValueError("Active unit is missing from the plan source")
    git = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], cwd=root, capture_output=True, text=True
    )
    commit = git.stdout.strip() if git.returncode == 0 else "uncommitted"
    result = [
        "# Execution capsule (not authoritative)",
        f"Active unit: {unit}; source commit: {commit}",
        f"Plan: {plan.as_posix()}",
        "Read the cited sources and current diff before writing; this capsule may be stale.",
        "## Goal",
        *section(lines, r"^## (?:1\. )?Goal capsule", 15),
        "## Active unit",
        *active,
        "## Project rules (excerpt)",
        *rules[:20],
        "## Status (excerpt)",
        *source(root, Path("docs/IMPLEMENTATION_STATUS.md"))[:15],
        "## Contract sources",
    ]
    contracts = root / "contracts"
    if contracts.exists():
        result.extend(
            str(p.relative_to(root))
            for p in sorted(contracts.glob("*.schema.json"))
            if not p.is_symlink()
        )
    return "\n".join(result[:119]) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unit", required=True, choices=[f"U{i}" for i in range(8)])
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    args = parser.parse_args()
    print(snapshot(args.root, args.unit, args.plan), end="")


if __name__ == "__main__":
    main()
