import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "workspace" / "evals" / "m4_probe43_report.json"
AUTHORIZATION_PATH = ROOT / "workspace" / "evals" / "m4_probe43_authorization.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _events(report: dict) -> list[dict]:
    events = []
    for line_number, line in enumerate(
        (ROOT / report["evidence_paths"]["raw_session_jsonl"]).read_text(
            encoding="utf-8"
        ).splitlines(),
        1,
    ):
        if not line.strip():
            continue
        event = json.loads(line)
        event["_line"] = line_number
        events.append(event)
    return events


def test_m4_probe43_report_binds_machine_step_place_failure():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    authorization = json.loads(AUTHORIZATION_PATH.read_text(encoding="utf-8"))

    assert report["probe_number"] == 43
    assert report["task_id"] == "BM-012"
    assert authorization["consumed"] is True
    assert authorization["consumed_by_episode"] == report["episode_id"]
    assert authorization["consumed_session_id"] == report["session_id"]
    assert authorization["next_authorization"] is False

    for name, path in report["evidence_paths"].items():
        assert _sha256(ROOT / path) == report["evidence_sha256"][name]

    assert report["frozen_controls"]["model"] == "grok-4.5"
    assert report["episode_result"]["completed"] is False
    assert report["episode_result"]["termination_reason"] == "episode_deadline"
    assert report["episode_result"]["planner_call_count"] == 12
    assert report["episode_result"]["real_planner_call_count"] == 12
    assert report["episode_result"]["machine_step_plan_count"] == 210
    assert report["episode_result"]["action_count"] == 218
    assert report["episode_result"]["successful_action_count"] == 10
    assert report["episode_result"]["failed_action_count"] == 208
    assert report["behavioral_progression"]["planks_to_crafting_table"] is True
    assert report["behavioral_progression"]["crafting_table_placed"] is False
    assert report["decision"]["counts_toward_bm012_success"] is False
    assert report["decision"]["bm012_success_count_after"] == 1


def test_probe43_jsonl_exposes_repeated_place_reference_gap():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    events = _events(report)

    assert len(events) == 3434
    actions = [event for event in events if event.get("type") == "action"]
    assert len(actions) == 218
    place_actions = [
        event for event in actions
        if event["data"]["action"]["type"] == "place"
    ]
    assert len(place_actions) == 207
    assert all(
        event["data"]["result"]["success"] is False
        and event["data"]["result"]["error"] == "placement target is occupied by dirt"
        and event["data"]["action"]["parameters"] == {
            "item": "crafting_table",
            "x": 114,
            "y": 133,
            "z": -29,
        }
        for event in place_actions
    )

    machine_steps = [
        event for event in events
        if event.get("type") == "m4_bm012_toolchain_machine_step_plan"
    ]
    assert len(machine_steps) == 210
    assert machine_steps[0]["_line"] == 218
    assert machine_steps[0]["data"]["reason"] == "craft_oak_planks_for_crafting_table"
    assert machine_steps[2]["_line"] == 242
    assert machine_steps[2]["data"]["reason"] == (
        "place_owned_crafting_table_at_verified_reference"
    )

    first_fail = place_actions[0]
    assert first_fail["_line"] == 251
    required = first_fail["data"]["result"]["action_verification"]["required"]
    assert required["adjacent_reference_candidates"] == [
        {"x": 115, "y": 133, "z": -29},
        {"x": 113, "y": 133, "z": -29},
        {"x": 114, "y": 133, "z": -28},
        {"x": 114, "y": 133, "z": -30},
    ]
    assert events[3380]["_line"] == 3381
    assert events[3380]["type"] == "runtime_interrupt"
    assert events[3380]["data"]["reason"] == "dusk_shelter_required"
    assert events[3421]["_line"] == 3422
    assert events[3421]["type"] == "episode_deadline_exceeded"


def test_probe43_offline_repair_uses_place_feedback_candidates():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    blocker = report["principal_blocker"]
    assert blocker["failure_layer"] == "m4_bm012_machine_step_place_failure_feedback_gap"
    assert blocker["repeated_failed_place_action_count"] == 207
    assert blocker["adjacent_reference_candidates_available"] is True
    assert blocker["place_feedback_consumed_before_repair"] is False

    repair = report["offline_repair"]
    assert repair["policy_id"] == "m4-bm012-machine-step-place-feedback-v1"
    assert repair["failed_place_references_excluded"] is True
    assert repair["adjacent_reference_candidates_reused"] is True
    assert repair["llm_fallback_when_no_verified_reference"] is True
    assert repair["protocol_changed"] is False
    assert repair["task_contract_changed"] is False
    assert repair["validated_offline"] is True
