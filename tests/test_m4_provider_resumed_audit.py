import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = (
    ROOT / "workspace" / "evals" / "m4_provider_resumed_audit_r1_20260726.json"
)
SCHEMA_PATH = (
    ROOT
    / "workspace"
    / "evals"
    / "schemas"
    / "m4_provider_resumed_audit.schema.json"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_m4_provider_resumed_audit_starts_a_fresh_fail_closed_count():
    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    Draft202012Validator(schema).validate(audit)
    prior = audit["previous_blocked_audit"]
    assert _sha256(ROOT / prior["path"]) == prior["sha256"]
    assert audit["probe"]["attempt_count"] == 1
    assert audit["probe"]["retry_count"] == 0
    assert audit["probe"]["minecraft_started"] is False
    assert audit["result"]["http_status"] == 401
    assert audit["result"]["credit_error_proven"] is True
    assert audit["decision"]["resumed_consecutive_count"] == 1
    assert audit["decision"]["blocked_threshold"] == 3
    assert audit["decision"]["goal_status_after_audit"] == "active"
    assert audit["decision"]["probe_25_authorized"] is False
    assert audit["decision"]["counts_toward_bm012_success"] is False
    assert audit["decision"]["counts_toward_capability"] is False
