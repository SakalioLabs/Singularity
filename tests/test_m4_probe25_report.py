import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "workspace" / "evals" / "m4_probe25_report.json"
AUTHORIZATION_PATH = ROOT / "workspace" / "evals" / "m4_probe25_authorization.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_m4_probe25_report_binds_stale_credential_failure_and_evidence():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    authorization = json.loads(AUTHORIZATION_PATH.read_text(encoding="utf-8"))

    assert report["probe_number"] == 25
    assert report["task_id"] == "BM-012"
    assert report["authorization"]["consumed"] is True
    assert authorization["consumed"] is True
    assert authorization["consumed_by_episode"] == report["episode_id"]
    assert authorization["maximum_retry_count"] == 0
    assert authorization["next_authorization"] is False

    for name, path in report["evidence_paths"].items():
        assert _sha256(ROOT / path) == report["evidence_sha256"][name]

    session_path = ROOT / report["evidence_paths"]["raw_session_jsonl"]
    events = [
        json.loads(line)
        for line in session_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    calls = [event for event in events if event.get("type") == "llm_planner_call"]
    actions = [event for event in events if event.get("type") == "action"]
    assert len(calls) == 24
    assert not actions
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

    assert report["planner_failure"]["http_status"] == 401
    assert report["planner_failure"]["provider_health_before_episode"] is True
    assert report["planner_failure"]["selected_runtime_credential_health"] is False
    assert report["runtime_repair"]["runs_before_minecraft_start"] is True
    assert report["decision"]["value"] == "infrastructure_ineligible"
    assert report["decision"]["counts_toward_bm012_success"] is False
    assert report["decision"]["counts_toward_capability"] is False
    assert report["eligibility"]["pass_count"] == 62
    assert report["eligibility"]["check_count"] == 74
