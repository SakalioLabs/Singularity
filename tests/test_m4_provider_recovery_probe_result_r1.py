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
