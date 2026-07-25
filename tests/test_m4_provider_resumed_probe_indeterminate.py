import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = (
    ROOT
    / "workspace"
    / "evals"
    / "m4_provider_resumed_probe_indeterminate_20260726.json"
)
SCHEMA_PATH = (
    ROOT
    / "workspace"
    / "evals"
    / "schemas"
    / "m4_provider_resumed_probe_indeterminate.schema.json"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_m4_indeterminate_probe_cannot_complete_the_resumed_blocked_threshold():
    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    Draft202012Validator(schema).validate(audit)
    prior = audit["previous_resumed_audit"]
    assert _sha256(ROOT / prior["path"]) == prior["sha256"]
    attempt = audit["probe_attempt"]
    assert attempt["automatic_retry_count"] == 0
    assert attempt["provider_result_observed"] is False
    assert attempt["probe_process_clean_after_audit"] is True
    decision = audit["decision"]
    assert decision["qualifying_http401_observation"] is False
    assert decision["fixed_provider_recovery_proven"] is False
    assert decision["blocked_threshold_satisfied"] is False
    assert decision["current_proven_consecutive_count"] == 0
    assert decision["goal_status_after_audit"] == "active"
    assert decision["probe_25_authorized"] is False
    assert audit["safety"]["same_turn_manual_retry_performed"] is False
