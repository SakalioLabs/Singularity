import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "workspace" / "evals" / "m4_probe24_report.json"
AUTHORIZATION_PATH = ROOT / "workspace" / "evals" / "m4_probe24_authorization.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_m4_probe24_report_binds_provider_failure_and_immutable_evidence():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    authorization = json.loads(AUTHORIZATION_PATH.read_text(encoding="utf-8"))

    assert report["probe_number"] == 24
    assert report["task_id"] == "BM-012"
    assert report["authorization"]["consumed"] is True
    assert authorization["consumed"] is True
    assert authorization["consumed_by_episode"] == report["episode_id"]
    assert authorization["maximum_retry_count"] == 0
    assert authorization["next_authorization"] is False

    for name, path in report["evidence_paths"].items():
        assert _sha256(ROOT / path) == report["evidence_sha256"][name]

    first_attempt = report["preflight_attempts"][0]
    first_root = (
        ROOT
        / "logs"
        / "benchmarks"
        / "m4"
        / first_attempt["episode_id"]
    )
    assert _sha256(first_root / "protocol_status.json") == (
        first_attempt["evidence"]["protocol_status_sha256"]
    )
    assert _sha256(first_root / "reset.json") == (
        first_attempt["evidence"]["reset_sha256"]
    )
    assert _sha256(first_root / "preflight.json") == (
        first_attempt["evidence"]["preflight_sha256"]
    )
    blocker = ROOT / "logs" / "benchmarks" / "m4" / "m4_runtime_blocker_20260725_225040.json"
    assert _sha256(blocker) == first_attempt["evidence"]["blocker_sha256"]

    session_path = ROOT / report["evidence_paths"]["raw_session_jsonl"]
    events = [
        json.loads(line)
        for line in session_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    calls = [event for event in events if event.get("type") == "llm_planner_call"]
    actions = [event for event in events if event.get("type") == "action"]
    reconciliations = [
        event
        for event in events
        if event.get("type")
        == "m4_failed_bound_ready_task_machine_state_reconciliation"
    ]
    assert len(calls) == 24
    assert not actions
    assert not reconciliations
    assert all(call["data"]["real_llm_call"] is False for call in calls)
    assert all(call["data"]["schema_valid"] is False for call in calls)
    assert all(call["data"]["response_byte_count"] == 0 for call in calls)
    assert all(
        call["data"]["provider_metadata"]["error_type"] == "AuthenticationError"
        for call in calls
    )
    assert all(
        call["data"]["transport_evidence"]["attempt_count"] == 1
        and call["data"]["transport_evidence"]["retry_count"] == 0
        for call in calls
    )

    assert report["decision"]["value"] == "infrastructure_ineligible"
    assert report["decision"]["counts_toward_bm012_success"] is False
    assert report["decision"]["counts_toward_capability"] is False
    assert report["intervention_measurement"]["live_validated"] is False
    assert report["intervention_measurement"]["live_rejected"] is False
    assert report["eligibility"]["pass_count"] == 62
    assert report["eligibility"]["check_count"] == 74
