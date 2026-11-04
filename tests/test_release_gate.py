import importlib.util
from pathlib import Path


def module():
    path = Path(__file__).resolve().parents[1] / "scripts/release_gate.py"
    spec = importlib.util.spec_from_file_location("release_gate", path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def test_development_does_not_require_signing():
    assert module().assess({}, "development")["ready"]


def test_missing_or_partial_evidence_never_promotes():
    gate = module()
    assert not gate.assess({}, "internal-testflight")["ready"]
    evidence = {"gates": {name: {"status": "passed"} for name in gate.REQUIRED["formal"]}}
    # A green label without an evidence record, exact source/model and approval is insufficient.
    assert not gate.assess(evidence, "formal")["ready"]


def test_different_commit_and_unprotected_environment_fail():
    gate = module()
    evidence = {
        "source_commit": "a" * 40,
        "model_sha256": "b" * 64,
        "protected_environment_approved": False,
        "gates": {
            name: {"status": "passed", "evidence_sha256": "c" * 64}
            for name in gate.REQUIRED["formal"]
        },
    }
    assert not gate.assess(evidence, "formal", commit="d" * 40)["ready"]
    assert not gate.assess(evidence, "formal", commit="a" * 40)["ready"]
