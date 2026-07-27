import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUTHORIZATION_PATH = ROOT / "workspace" / "evals" / "m4_probe51_authorization.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _authorization() -> dict:
    return json.loads(AUTHORIZATION_PATH.read_text(encoding="utf-8"))


def test_probe51_authorization_binds_pushed_bm014_repair_and_contract():
    authorization = _authorization()
    assert authorization["type"] == "m4_live_probe_authorization"
    assert authorization["task_id"] == "BM-014"
    assert authorization["probe_number"] == 51
    assert authorization["task_contract_id"] == (
        "m4-bm014-iron-pickaxe-contract-v1"
    )
    assert authorization["task_contract_sha256"] == _sha256(
        ROOT / "src" / "singularity" / "data" / "m4_bm014_protocol.json"
    )
    assert authorization["gate_parent_commit"] == (
        "ee6f972aedc79777a703fc0b37419a260f42398b"
    )
    assert authorization["gate_tree"] == (
        "39b4c7198a4f204525b461935cdad7e6984ef2bd"
    )
    assert authorization["policy_id"] == (
        "m4-inventory-purpose-clause-grounding-v1"
    )


def test_probe51_authorization_hashes_repair_and_prior_closure_evidence():
    authorization = _authorization()
    for path_key, hash_key in (
        ("repair_audit_path", "repair_audit_sha256"),
        ("repair_source_path", "repair_source_sha256"),
        ("repair_goal_verifier_test_path", "repair_goal_verifier_test_sha256"),
        ("repair_agent_test_path", "repair_agent_test_sha256"),
        ("repair_audit_test_path", "repair_audit_test_sha256"),
    ):
        assert authorization[hash_key] == _sha256(ROOT / authorization[path_key])

    closure = authorization["bm013_closure"]
    assert closure["commit"] == "84b9817dd7f65f4c001314874592bc096fc82c36"
    assert closure["tree"] == "adf8399f0857c41095e80e9e57ed43842e3e238e"
    assert closure["probe_50_report_sha256"] == _sha256(
        ROOT / closure["probe_50_report_path"]
    )
    assert closure["capability_evidence_sha256"] == _sha256(
        ROOT / closure["capability_evidence_path"]
    )
    assert closure["eligible_success_count"] == 3
    assert closure["repeat_verified"] is True


def test_probe51_authorization_is_one_unconsumed_zero_retry_episode():
    authorization = _authorization()
    assert authorization["authorized"] is True
    assert authorization["one_use"] is True
    assert authorization["maximum_episode_count"] == 1
    assert authorization["maximum_retry_count"] == 0
    assert authorization["client_max_retries"] == 0
    assert authorization["proxy_max_retries"] == 0
    assert authorization["fresh_level_required"] is True
    assert authorization["fixed_runtime_limits_required"] is True
    assert authorization["skill_execution_mode"] == "off"
    assert authorization["prior_bm014_eligible_success_count"] == 0
    assert authorization["required_bm014_eligible_success_count"] == 3
    assert authorization["remaining_bm014_eligible_success_count_before_probe"] == 3
    assert authorization["counts_toward_capability_before_independent_verification"] is False
    assert authorization["consumed"] is False
    assert authorization["next_authorization"] is False
    assert authorization["probe_52_authorized"] is False
