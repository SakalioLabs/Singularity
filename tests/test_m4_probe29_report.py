import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "workspace" / "evals" / "m4_probe29_report.json"
AUTHORIZATION_PATH = ROOT / "workspace" / "evals" / "m4_probe29_authorization.json"
REPAIR_AUDIT_PATH = (
    ROOT
    / "workspace"
    / "evals"
    / "m4_probe29_failed_bound_nearby_block_repair_audit.json"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_m4_probe29_report_binds_failed_ready_task_reconciliation_gap():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    authorization = json.loads(AUTHORIZATION_PATH.read_text(encoding="utf-8"))

    assert report["probe_number"] == 29
    assert report["task_id"] == "BM-012"
    assert report["frozen_controls"]["model"] == "grok-4.5"
    assert authorization["consumed"] is True
    assert authorization["consumed_by_episode"] == report["episode_id"]
    assert authorization["maximum_retry_count"] == 0
    assert authorization["next_authorization"] is False

    for name, path in report["evidence_paths"].items():
        assert _sha256(ROOT / path) == report["evidence_sha256"][name]

    events = [
        json.loads(line)
        for line in (
            ROOT / report["evidence_paths"]["raw_session_jsonl"]
        ).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    calls = [event for event in events if event.get("type") == "llm_planner_call"]
    real_calls = [call for call in calls if call["data"]["real_llm_call"]]
    actions = [event for event in events if event.get("type") == "action"]
    verifications = [
        event for event in events if event.get("type") == "goal_verification"
    ]
    gates = [
        event
        for event in events
        if event.get("type") == "m4_ready_task_goal_verifier_binding"
    ]

    assert len(calls) == 52
    assert len(real_calls) == 51
    assert sum(call["data"]["schema_valid"] is True for call in real_calls) == 50
    assert all(
        call["data"]["transport_evidence"]["attempt_count"] == 1
        and call["data"]["transport_evidence"]["retry_count"] == 0
        for call in real_calls
    )
    assert len(actions) == 14
    assert sum(action["data"]["result"]["success"] is True for action in actions) == 10
    assert len(verifications) == 53
    assert all(event["data"]["status"] == "achieved" for event in verifications)

    successful_places = [
        event
        for event in actions
        if event["data"]["action"]["type"] == "place"
        and event["data"]["result"]["success"] is True
    ]
    assert len(successful_places) == 1
    assert successful_places[0]["data"]["result"]["placed_position"] == {
        "x": 106,
        "y": 136,
        "z": -30,
    }
    achieved_suppressions = [
        event
        for event in gates
        if event["data"]["verifier_achieved"] is True
        and event["data"]["decision"]
        == "suppress_until_bound_task_machine_completion"
    ]
    assert len(achieved_suppressions) == 51
    assert all(event["data"]["binding_valid"] is True for event in achieved_suppressions)
    assert all(event["data"]["task_status"] == "failed" for event in achieved_suppressions)

    maximum_inventory = report["episode_result"]["maximum_inventory"]
    assert maximum_inventory["crafting_table"] == 1
    assert maximum_inventory["wooden_pickaxe"] == 0
    assert maximum_inventory["stone_pickaxe"] == 0
    assert maximum_inventory["raw_iron"] == 0
    assert report["episode_result"]["terminal_nearby_crafting_table"] is True
    assert report["decision"]["counts_toward_bm012_success"] is False
    assert report["decision"]["counts_toward_capability"] is False


def test_m4_probe29_repair_audit_is_narrow_and_source_bound():
    audit = json.loads(REPAIR_AUDIT_PATH.read_text(encoding="utf-8"))
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    assert audit["source_probe_number"] == report["probe_number"] == 29
    assert audit["source_episode_id"] == report["episode_id"]
    assert audit["source_probe_report_sha256"] == _sha256(REPORT_PATH)
    assert (
        audit["policy_id"]
        == "m4-failed-bound-ready-task-machine-state-reconciliation-v1"
    )
    assert audit["repair"]["criterion"] == "nearby_block_present"
    assert audit["repair"]["ordinary_failed_dependency_scope_changed"] is False
    assert all(audit["fail_closed_boundaries"].values())
    assert audit["verification"]["probe_30_authorized"] is False
    assert audit["verification"]["counts_toward_bm012_success"] is False
    assert audit["verification"]["counts_toward_capability"] is False
