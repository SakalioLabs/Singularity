import hashlib
import json
from pathlib import Path

import jsonschema


ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = (
    ROOT
    / "workspace"
    / "evals"
    / "m4_probe23_failed_bound_ready_task_offline_audit.json"
)
SCHEMA_PATH = (
    ROOT
    / "workspace"
    / "evals"
    / "schemas"
    / "m4_probe23_failed_bound_ready_task_offline_audit.schema.json"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_m4_probe23_failed_bound_ready_task_offline_audit_is_bound_and_fail_closed():
    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(audit)

    source = audit["source_evidence"]
    assert _sha256(ROOT / source["path"]) == source["sha256"]
    assert source["modified"] is False
    for record in audit["implementation"]:
        assert _sha256(ROOT / record["path"]) == record["sha256"]

    contract = audit["repair_contract"]
    assert contract["scope"] == "selected_bound_ready_task"
    assert contract["terminal_statuses"] == ["failed", "blocked"]
    assert contract["completion_source"] == "machine_state_reconciliation"
    assert contract["max_scheduler_latency_ticks"] == 1
    assert contract["failure_history_preserved"] is True
    assert contract["idempotent_by_task_fingerprint_state_generation"] is True
    assert contract["wrong_item_rejected"] is True
    assert contract["binding_drift_rejected"] is True
    assert audit["evidence_discipline"]["live_episode_run"] is False
    assert audit["evidence_discipline"]["counts_toward_bm012_success"] is False
    assert audit["authorization"] == {
        "probe_23_consumed": True,
        "probe_24_authorized": False,
        "next_authorized_episode": None,
    }
