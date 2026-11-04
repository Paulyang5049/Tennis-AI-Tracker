import importlib.util
import subprocess
from pathlib import Path


def load_script():
    path = Path(__file__).resolve().parents[1] / "scripts/context_snapshot.py"
    spec = importlib.util.spec_from_file_location("context_snapshot", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_capsule_bounded_and_private_sources_excluded(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "AGENTS.md").write_text("# Rules\nNever invent evidence.\n")
    plans = tmp_path / "docs/plans"
    plans.mkdir(parents=True)
    plan = plans / "upgrade.md"
    plan.write_text(
        "# Upgrade\n## Goal capsule\nReview a match.\n"
        "## Implementation units\n### U0 — Evidence\nUse fixtures.\n"
        "### U1 — Package\nLater.\n"
    )
    (tmp_path / "private-player.mp4").write_text("PRIVATE VIDEO")
    (tmp_path / ".env").write_text("SECRET_TOKEN=not-for-capsule")
    output = load_script().snapshot(tmp_path, "U0", plan.relative_to(tmp_path))
    assert "U0" in output and "Use fixtures." in output
    assert "private-player" not in output and "SECRET_TOKEN" not in output
    assert len(output.splitlines()) <= 120
    assert "not authoritative" in output


def test_capsule_rejects_external_or_symlink_source(tmp_path):
    import pytest

    outside = tmp_path / "outside.md"
    outside.write_text("private")
    root = tmp_path / "repo"
    root.mkdir()
    (root / "AGENTS.md").symlink_to(outside)
    with pytest.raises(ValueError, match="source"):
        load_script().snapshot(root, "U0", Path("plan.md"))
