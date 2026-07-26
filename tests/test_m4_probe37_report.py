import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "workspace" / "evals" / "m4_probe37_report.json"
AUTHORIZATION_PATH = ROOT / "workspace" / "evals" / "m4_probe37_authorization.json"


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


def test_m4_probe37_report_binds_grok_stone_pickaxe_progress_and_failure():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    authorization = json.loads(AUTHORIZATION_PATH.read_text(encoding="utf-8"))

    assert report["probe_number"] == 37
    assert report["task_id"] == "BM-012"
    assert authorization["consumed"] is True
    assert authorization["consumed_by_episode"] == report["episode_id"]
    assert authorization["next_authorization"] is False

    for name, path in report["evidence_paths"].items():
        assert _sha256(ROOT / path) == report["evidence_sha256"][name]

    assert report["frozen_controls"]["model"] == "grok-4.5"
    assert report["frozen_controls"]["provider_modalities"] == ["text", "image"]
    assert report["frozen_controls"]["runtime_modalities"] == ["text"]
    assert report["episode_result"]["planner_call_count"] == 34
    assert report["episode_result"]["real_planner_call_count"] == 32
    assert report["episode_result"]["schema_valid_real_planner_call_count"] == 29
    assert report["episode_result"]["action_count"] == 29
    assert report["episode_result"]["successful_action_count"] == 27
    assert report["episode_result"]["failed_action_count"] == 2
    assert report["episode_result"]["maximum_inventory"]["stone_pickaxe"] == 1
    assert report["episode_result"]["maximum_inventory"]["raw_iron"] == 0
    assert report["behavioral_progression"]["full_stone_pickaxe_loop_completed"] is True
    assert report["behavioral_progression"]["equipment_map_gap_exposed"] is True
    assert report["behavioral_progression"]["stone_pickaxe_to_raw_iron"] is False
    assert report["decision"]["counts_toward_bm012_success"] is False
    assert report["decision"]["counts_toward_capability"] is False


def test_probe37_jsonl_exposes_equipment_map_and_transitive_flag_gap():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    events = _events(report)

    assert len(events) == 813
    calls = [event for event in events if event.get("type") == "llm_planner_call"]
    real_calls = [call for call in calls if call["data"]["real_llm_call"]]
    actions = [event for event in events if event.get("type") == "action"]
    assert len(calls) == 34
    assert len(real_calls) == 32
    assert sum(call["data"]["schema_valid"] is True for call in real_calls) == 29
    assert len(actions) == 29
    assert sum(action["data"]["result"]["success"] is True for action in actions) == 27

    equipment_map_plans = [
        event
        for event in events
        if event.get("type") == "plan"
        and event["_line"] == 619
        and any(
            subtask.get("success_criteria") == {
                "equipment": {"stone_pickaxe": 1}
            }
            for subtask in event["data"].get("subtasks", [])
            if isinstance(subtask, dict)
        )
    ]
    assert len(equipment_map_plans) == 1

    invalid_calls = [
        event
        for event in events
        if event.get("type") == "llm_planner_call"
        and event["_line"] in {654, 671}
    ]
    assert [event["_line"] for event in invalid_calls] == [654, 671]
    assert all(
        event["data"]["schema_validation"]["issues"]
        == ["subtask[2]:equip_precondition_grounding_failed"]
        for event in invalid_calls
    )

    blocker = report["principal_blocker"]
    assert blocker["failure_layer"] == (
        "m4_equipment_map_transitive_equip_precondition_grounding_gap"
    )
    assert blocker["first_equipment_map_plan_line"] == 619
    assert blocker["first_transitive_equip_precondition_schema_rejection_line"] == 654
    assert blocker["second_transitive_equip_precondition_schema_rejection_line"] == 671
    assert blocker["raw_iron_dig_action_count"] == 0
    assert blocker["terminal_raw_iron"] == 0
    assert blocker["terminal_stone_pickaxe"] == 1
    assert report["offline_repair"]["policy_id"] == (
        "m4-equip-equipment-map-transitive-precondition-grounding-v1"
    )
    assert report["offline_repair"]["validated_offline"] is True


def test_probe37_recovered_place_replan_noise_is_nonterminal():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    events = _events(report)
    recovered = report["recovered_nonterminal_findings"]

    assert recovered["recovered"] is True
    assert recovered["place_replan_repeated_reference_line"] == 248
    assert recovered["place_replan_empty_plan_line"] == 253
    assert recovered["successful_table_place_line_after_recovery"] == 305
    assert [
        event["_line"]
        for event in events
        if event.get("type") == "action"
        and event["data"]["action"]["type"] == "place"
        and event["data"]["result"]["success"] is True
    ][0] == 305
