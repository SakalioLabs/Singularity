import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDIT_RELATIVE = (
    "workspace/evals/m4_probe31_stone_pickaxe_frontier_repair_audit.json"
)
AUDIT_PATH = ROOT / AUDIT_RELATIVE
SOURCE_SNAPSHOT_COMMIT = "efa4226a44b7e72618bb7f92e46453a7d7f25710"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sealed_evidence_sha256(path: Path, expected: str) -> str:
    payload = path.read_bytes()
    direct = hashlib.sha256(payload).hexdigest()
    if direct == expected:
        return direct
    assert b"\r" not in payload
    return hashlib.sha256(payload.replace(b"\n", b"\r\n")).hexdigest()


def _git_sha256(commit: str, path: str) -> str:
    payload = subprocess.check_output(
        ["git", "show", f"{commit}:{Path(path).as_posix()}"],
        cwd=ROOT,
    )
    return hashlib.sha256(payload).hexdigest()


def test_probe31_stone_pickaxe_audit_binds_immutable_evidence():
    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    report_path = ROOT / audit["evidence_paths"]["probe_report"]
    raw_path = ROOT / audit["evidence_paths"]["raw_session_jsonl"]
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert _sha256(report_path) == audit["evidence_sha256"]["probe_report"]
    expected = audit["evidence_sha256"]["raw_session_jsonl"]
    assert _sealed_evidence_sha256(raw_path, expected) == expected
    assert audit["probe_number"] == report["probe_number"] == 31
    assert audit["episode_id"] == report["episode_id"]
    assert audit["first_unrecovered_transition"] == report["principal_blocker"]
    assert report["behavioral_progression"]["wooden_pickaxe_to_cobblestone"] is True
    assert report["behavioral_progression"]["cobblestone_to_stone_pickaxe"] is False


def test_probe31_stone_pickaxe_repair_is_bounded_and_grants_no_credit():
    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    repair = audit["offline_repair"]

    assert repair["policy_id"] == "m4-bm012-stone-pickaxe-frontier-yield-v1"
    assert repair["scope"] == "strict_m4_bm012_only"
    assert repair["frontier_yield_trigger"] == {
        "wooden_pickaxe_min": 1,
        "stone_pickaxe_max": 0,
        "cobblestone_min": 3,
    }
    assert repair["yield_boundaries"] == ["pre_planner", "post_action"]
    assert repair["survival_interrupt_priority_preserved"] is True
    assert repair["non_m4_unchanged"] is True
    assert repair["capability_upgrade"] is False
    assert audit["counts_toward_bm012_success"] is False
    assert audit["counts_toward_capability"] is False
    assert audit["decision"]["probe_32_authorized"] is False


def test_probe31_repair_source_hashes_are_bound_to_the_repair_commit():
    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    assert {
        key: _git_sha256(SOURCE_SNAPSHOT_COMMIT, path)
        for key, path in audit["source_paths"].items()
    } == audit["source_sha256"]
