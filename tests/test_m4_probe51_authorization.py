import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUTHORIZATION_PATH = ROOT / "workspace" / "evals" / "m4_probe51_authorization.json"
AUTHORIZATION_COMMIT = "38d37263f7e4171698de182f8ad6b8ecfaf4db81"
GATE_PARENT_COMMIT = "ee6f972aedc79777a703fc0b37419a260f42398b"
GATE_TREE = "39b4c7198a4f204525b461935cdad7e6984ef2bd"


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _authorization() -> dict:
    return json.loads(AUTHORIZATION_PATH.read_text(encoding="utf-8"))


def _git_blob(commit: str, path: str) -> bytes:
    result = subprocess.run(
        ["git", "show", f"{commit}:{Path(path).as_posix()}"],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout


def _git_json(commit: str, path: str) -> dict:
    return json.loads(_git_blob(commit, path).decode("utf-8"))


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


def _issued_authorization() -> dict:
    return _git_json(
        AUTHORIZATION_COMMIT,
        "workspace/evals/m4_probe51_authorization.json",
    )


def test_probe51_authorization_binds_pushed_bm014_repair_and_contract():
    authorization = _authorization()
    issued = _issued_authorization()
    assert authorization["type"] == "m4_live_probe_authorization"
    assert authorization["task_id"] == "BM-014"
    assert authorization["probe_number"] == 51
    assert authorization["task_contract_id"] == (
        "m4-bm014-iron-pickaxe-contract-v1"
    )
    assert authorization["task_contract_sha256"] == issued["task_contract_sha256"]
    assert issued["task_contract_sha256"] == _sha256_bytes(
        _git_blob(
            AUTHORIZATION_COMMIT,
            "src/singularity/data/m4_bm014_protocol.json",
        )
    )
    assert authorization["gate_parent_commit"] == GATE_PARENT_COMMIT
    assert authorization["gate_tree"] == GATE_TREE
    assert authorization["policy_id"] == (
        "m4-inventory-purpose-clause-grounding-v1"
    )
    assert issued["gate_parent_commit"] == GATE_PARENT_COMMIT
    assert issued["gate_tree"] == GATE_TREE
    assert _git_revision(f"{AUTHORIZATION_COMMIT}^") == GATE_PARENT_COMMIT
    assert _git_revision(f"{GATE_PARENT_COMMIT}^{{tree}}") == GATE_TREE


def test_probe51_authorization_hashes_repair_and_prior_closure_evidence():
    authorization = _authorization()
    issued = _issued_authorization()
    for path_key, hash_key in (
        ("repair_audit_path", "repair_audit_sha256"),
        ("repair_source_path", "repair_source_sha256"),
        ("repair_goal_verifier_test_path", "repair_goal_verifier_test_sha256"),
        ("repair_agent_test_path", "repair_agent_test_sha256"),
        ("repair_audit_test_path", "repair_audit_test_sha256"),
    ):
        assert authorization[path_key] == issued[path_key]
        assert authorization[hash_key] == issued[hash_key]
        assert issued[hash_key] == _sha256_bytes(
            _git_blob(AUTHORIZATION_COMMIT, issued[path_key])
        )

    closure = issued["bm013_closure"]
    assert authorization["bm013_closure"] == closure
    assert closure["commit"] == "84b9817dd7f65f4c001314874592bc096fc82c36"
    assert closure["tree"] == "adf8399f0857c41095e80e9e57ed43842e3e238e"
    assert closure["probe_50_report_sha256"] == _sha256_bytes(
        _git_blob(closure["commit"], closure["probe_50_report_path"])
    )
    capability_blob = _git_blob(
        closure["commit"],
        closure["capability_evidence_path"],
    )
    # This evidence hash was issued from the Windows CRLF checkout; derive those
    # exact gate-time bytes from the immutable, LF-normalized Git blob.
    assert closure["capability_evidence_sha256"] == _sha256_bytes(
        capability_blob.replace(b"\n", b"\r\n")
    )
    assert closure["eligible_success_count"] == 3
    assert closure["repeat_verified"] is True


def test_probe51_authorization_was_issued_unconsumed_then_consumed_at_jsonl_line_2():
    authorization = _authorization()
    issued = _issued_authorization()
    consumed_fields = {
        "consumed_by_episode",
        "consumed_session_id",
        "consumed_level_name",
        "consumed_at",
        "consumed_at_utc",
        "consumed_monotonic_s",
        "consumed_event_line",
        "consumed_evidence_dir",
        "consumed_report_path",
    }
    assert set(authorization) - set(issued) == consumed_fields
    for key, value in issued.items():
        if key != "consumed":
            assert authorization[key] == value

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
    assert issued["consumed"] is False
    assert authorization["consumed"] is True
    assert authorization["next_authorization"] is False
    assert authorization["probe_52_authorized"] is False
    assert issued["probe_52_authorized"] is False

    evidence_dir = ROOT / authorization["consumed_evidence_dir"]
    jsonl_path = evidence_dir / (
        f"session_{authorization['consumed_session_id']}.jsonl"
    )
    with jsonl_path.open(encoding="utf-8") as handle:
        first_event = json.loads(next(handle))
        consumed_event = json.loads(next(handle))

    assert first_event["type"] == "connect"
    assert authorization["consumed_event_line"] == 2
    assert authorization["consumed_at"] == consumed_event["type"] == "autonomous_start"
    assert authorization["consumed_session_id"] == consumed_event["session"]
    assert authorization["consumed_monotonic_s"] == consumed_event["monotonic_s"]
    assert authorization["consumed_at_utc"] == (
        datetime.fromtimestamp(consumed_event["ts"], tz=timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )
    assert authorization["consumed_by_episode"] == evidence_dir.name
    assert consumed_event["data"]["task_id"] == authorization["task_id"]
    assert (
        consumed_event["data"]["task_contract_id"]
        == authorization["task_contract_id"]
    )
    assert (
        consumed_event["data"]["task_contract_sha256"]
        == authorization["task_contract_sha256"]
    )

    manifest = json.loads(
        (evidence_dir / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["episode_id"] == authorization["consumed_by_episode"]
    assert manifest["session_id"] == authorization["consumed_session_id"]
    assert manifest["level_name"] == authorization["consumed_level_name"]
    assert authorization["consumed_report_path"] == (
        "workspace/evals/m4_probe51_report.json"
    )
