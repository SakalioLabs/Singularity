import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = (
    ROOT
    / "workspace"
    / "evals"
    / "m4_post_probe24_provider_recovery_probe_r1.json"
)
SCHEMA_PATH = (
    ROOT
    / "workspace"
    / "evals"
    / "schemas"
    / "m4_post_probe24_provider_recovery_probe.schema.json"
)
PROBE24_REPORT_PATH = ROOT / "workspace" / "evals" / "m4_probe24_report.json"
PROBE24_REPORT_SHA256 = (
    "91d2a85d11be604e1a2dae79513734f536a2ede7fc10527ad14f6715b4736af3"
)


def test_m4_post_probe24_provider_recovery_probe_is_bounded_and_fail_closed():
    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    Draft202012Validator(schema).validate(audit)
    assert audit["request"]["attempt_count"] == 1
    assert audit["request"]["retry_count"] == 0
    assert audit["request"]["minecraft_started"] is False
    assert audit["result"]["http_status"] == 401
    assert audit["result"]["probe24_credit_exhaustion_reconfirmed"] is False
    assert audit["decision"]["authorizes_probe_25"] is False
    assert audit["decision"]["counts_toward_bm012_success"] is False
    assert audit["decision"]["counts_toward_capability"] is False
    assert hashlib.sha256(PROBE24_REPORT_PATH.read_bytes()).hexdigest() == (
        PROBE24_REPORT_SHA256
    )
