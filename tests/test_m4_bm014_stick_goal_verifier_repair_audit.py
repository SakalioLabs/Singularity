import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPAIR_COMMIT = "ee6f972aedc79777a703fc0b37419a260f42398b"
REPAIR_TREE = "39b4c7198a4f204525b461935cdad7e6984ef2bd"
AUDIT_PATH = (
    ROOT / "workspace" / "evals"
    / "m4_bm014_stick_goal_verifier_repair_audit.json"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _git_blob(commit: str, path: str) -> bytes:
    result = subprocess.run(
        ["git", "show", f"{commit}:{Path(path).as_posix()}"],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout


def _git_revision(revision: str) -> str:
    result = subprocess.run(
        ["git", "rev-parse", revision],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return result.stdout.strip()


def _audit() -> dict:
    return json.loads(AUDIT_PATH.read_text(encoding="utf-8"))


def test_bm014_stick_goal_repair_audit_binds_frozen_contract_and_parent():
    audit = _audit()
    assert audit["type"] == "m4_bm014_stick_goal_verifier_repair_audit"
    assert audit["profile"] == "m4-fixed-v1"
    assert audit["task_id"] == "BM-014"
    assert audit["task_contract_id"] == "m4-bm014-iron-pickaxe-contract-v1"
    assert audit["task_contract_sha256"] == (
        "1941a668a2ca3b0181ec0b32e3c17e2040ba74995e1d36a4d125ab92cf15354f"
    )
    assert audit["repair_parent"]["commit"] == (
        "84b9817dd7f65f4c001314874592bc096fc82c36"
    )
    assert audit["repair_parent"]["tree"] == (
        "adf8399f0857c41095e80e9e57ed43842e3e238e"
    )
    assert _git_revision(f"{REPAIR_COMMIT}^") == audit["repair_parent"]["commit"]
    assert _git_revision(f"{REPAIR_COMMIT}^{{tree}}") == REPAIR_TREE


def test_bm014_stick_goal_repair_audit_hashes_exact_sources():
    audit = _audit()
    for key, relative_path in audit["source_paths"].items():
        assert audit["source_sha256"][key] == _sha256_bytes(
            _git_blob(REPAIR_COMMIT, relative_path)
        )
    assert audit["repair_parent"]["probe_50_report_sha256"] == _sha256_bytes(
        _git_blob(
            audit["repair_parent"]["commit"],
            audit["repair_parent"]["probe_50_report_path"],
        )
    )
    capability_blob = _git_blob(
        audit["repair_parent"]["commit"],
        audit["repair_parent"]["capability_evidence_path"],
    )
    # The frozen audit recorded the Windows CRLF checkout hash; reproduce those
    # gate-time bytes from the immutable LF-normalized Git blob.
    assert audit["repair_parent"]["capability_evidence_sha256"] == _sha256_bytes(
        capability_blob.replace(b"\n", b"\r\n")
    )


def test_bm014_stick_goal_repair_audit_is_offline_and_does_not_authorize_live():
    audit = _audit()
    assert audit["classification"] == "offline_repair"
    assert audit["counts_toward_bm014_success"] is False
    assert audit["counts_toward_capability"] is False
    assert audit["offline_repair"]["default_verbs_unchanged"] is True
    assert audit["offline_repair"]["other_manual_anchor_verbs_unchanged"] is True
    assert audit["offline_repair"]["purpose_clause_behavior"] == {
        "primary_target": {"stick": 2},
        "nonbinding_suffix": "for crafting the iron pickaxe",
        "iron_pickaxe_bound_by_exact_goal": False,
        "explicit_then_followup_remains_binding": True,
    }
    assert audit["decision"]["repair_offline_gate_passed"] is True
    assert audit["decision"]["bm014_eligible_success_count"] == 0
    assert audit["decision"]["bm014_authorized"] is False
    assert audit["decision"]["bm014_live_locked"] is True
    assert audit["decision"]["probe_51_authorized"] is False
