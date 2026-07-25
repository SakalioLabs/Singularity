import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = ROOT / "workspace" / "evals" / "m4_provider_blocked_audit_20260725.json"
SCHEMA_PATH = (
    ROOT
    / "workspace"
    / "evals"
    / "schemas"
    / "m4_provider_blocked_audit.schema.json"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_m4_provider_blocked_audit_binds_three_fail_closed_goal_turns():
    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    Draft202012Validator(schema).validate(audit)
    observations = audit["goal_turn_observations"]
    assert [item["goal_turn"] for item in observations] == [1, 2, 3]
    assert all(item["http_status"] == 401 for item in observations)
    assert all(item["retry_count"] == 0 for item in observations)
    assert all(item["real_planner_response_count"] == 0 for item in observations)
    assert all(item["gameplay_action_count"] == 0 for item in observations)

    for item in observations[:2]:
        assert _sha256(ROOT / item["evidence_path"]) == item["evidence_sha256"]

    blocked = audit["blocked_audit"]
    assert blocked["same_blocking_condition_across_three_goal_turns"] is True
    assert blocked["fixed_provider_recovery_proven"] is False
    assert blocked["probe_25_authorized"] is False
    assert blocked["goal_status"] == "blocked"
    assert audit["evidence_discipline"]["counts_toward_bm012_success"] is False
    assert audit["evidence_discipline"]["counts_toward_capability"] is False
