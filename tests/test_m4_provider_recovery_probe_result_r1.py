import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
RESULT_PATH = (
    ROOT / "workspace" / "evals" / "m4_provider_recovery_probe_20260726_r1.json"
)
SCHEMA_PATH = (
    ROOT
    / "workspace"
    / "evals"
    / "schemas"
    / "m4_provider_recovery_probe.schema.json"
)
RESULT_SHA256 = "8c0101c305d6557e2d71a4319df181026e1365323e7715681f4395b840217c80"
RESULT_R2_PATH = (
    ROOT / "workspace" / "evals" / "m4_provider_recovery_probe_20260726_r2.json"
)
RESULT_R2_SHA256 = (
    "33d49dcb08511c2bb3a4fd5bf0f9e9601342b47ab78f4bd787bb0970d47b58be"
)
RESULT_R3_PATH = (
    ROOT / "workspace" / "evals" / "m4_provider_recovery_probe_20260726_r3.json"
)
RESULT_R3_SHA256 = (
    "b3568af61454e25d9fcf9264d06f1a28848291edfb42d48362197183b9cf7b8c"
)
BLOCKED_AUDIT_PATH = (
    ROOT / "workspace" / "evals" / "m4_provider_recovery_blocked_audit_20260726.json"
)
BLOCKED_SCHEMA_PATH = (
    ROOT
    / "workspace"
    / "evals"
    / "schemas"
    / "m4_provider_recovery_blocked_audit.schema.json"
)


def test_m4_provider_recovery_probe_r1_is_fixed_zero_retry_and_fail_closed():
    result = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    Draft202012Validator(schema).validate(result)
    assert hashlib.sha256(RESULT_PATH.read_bytes()).hexdigest() == RESULT_SHA256
    assert result["source_commit"] == "98818b74ef18ae876229ebc619336f86d5b1e2a4"
    assert result["provider"] == {
        "name": "openai",
        "base_url": "https://opencode.ai/zen/go/v1",
        "model": "deepseek-v4-flash",
    }
    assert result["request"]["attempt_count"] == 1
    assert result["request"]["automatic_retry_count"] == 0
    assert result["request"]["minecraft_started"] is False
    assert result["result"]["provider_result_observed"] is True
    assert result["result"]["classification"] == "fixed_provider_unavailable"
    assert result["result"]["http_status"] == 401
    assert result["result"]["credit_error"] is True
    assert result["result"]["supervisor_terminated_worker"] is False
    assert result["decision"]["recovery_gate_passed"] is False
    assert result["decision"]["probe_25_authorized"] is False
    assert result["decision"]["counts_toward_bm012_success"] is False
    assert result["decision"]["counts_toward_capability"] is False


def test_m4_provider_recovery_probe_r2_extends_the_fixed_provider_blocker():
    result = json.loads(RESULT_R2_PATH.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    Draft202012Validator(schema).validate(result)
    assert hashlib.sha256(RESULT_R2_PATH.read_bytes()).hexdigest() == RESULT_R2_SHA256
    assert result["source_commit"] == "74745c81e9d555238e814e05da6175dfb8f6eec9"
    assert result["provider"] == {
        "name": "openai",
        "base_url": "https://opencode.ai/zen/go/v1",
        "model": "deepseek-v4-flash",
    }
    assert result["request"]["attempt_count"] == 1
    assert result["request"]["automatic_retry_count"] == 0
    assert result["request"]["minecraft_started"] is False
    assert result["result"]["provider_result_observed"] is True
    assert result["result"]["classification"] == "fixed_provider_unavailable"
    assert result["result"]["http_status"] == 401
    assert result["result"]["credit_error"] is True
    assert result["result"]["supervisor_terminated_worker"] is False
    assert result["decision"]["recovery_gate_passed"] is False
    assert result["decision"]["probe_25_authorized"] is False
    assert result["decision"]["counts_toward_bm012_success"] is False
    assert result["decision"]["counts_toward_capability"] is False


def test_m4_provider_recovery_probe_r3_retains_supervisor_timeout_fail_closed():
    result = json.loads(RESULT_R3_PATH.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    Draft202012Validator(schema).validate(result)
    assert hashlib.sha256(RESULT_R3_PATH.read_bytes()).hexdigest() == RESULT_R3_SHA256
    assert result["source_commit"] == "c674ac46e1bf7da08b13320eb3ba5e052fb41c95"
    assert result["request"]["attempt_count"] == 1
    assert result["request"]["automatic_retry_count"] == 0
    assert result["request"]["minecraft_started"] is False
    assert result["result"]["classification"] == "probe_indeterminate"
    assert result["result"]["provider_result_observed"] is False
    assert result["result"]["error_type"] == "SupervisorTimeout"
    assert result["result"]["supervisor_terminated_worker"] is True
    assert result["decision"]["recovery_gate_passed"] is False
    assert result["decision"]["probe_25_authorized"] is False


def test_m4_provider_recovery_blocked_audit_binds_three_unavailable_turns():
    audit = json.loads(BLOCKED_AUDIT_PATH.read_text(encoding="utf-8"))
    schema = json.loads(BLOCKED_SCHEMA_PATH.read_text(encoding="utf-8"))

    Draft202012Validator(schema).validate(audit)
    for observation in audit["observations"]:
        path = ROOT / observation["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == observation["sha256"]
    shared = audit["shared_proof"]
    assert shared["usable_planner_response_count"] == 0
    assert shared["error_subtypes_identical"] is False
    assert shared["http401_credit_error_count"] == 2
    assert shared["supervisor_timeout_count"] == 1
    assert shared["same_blocking_condition_across_three_goal_turns"] is True
    blocked = audit["blocked_audit"]
    assert blocked["meaningful_code_only_progress_remaining"] is False
    assert blocked["probe_25_authorized"] is False
    assert blocked["goal_status"] == "blocked"
