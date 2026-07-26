import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "workspace" / "evals" / "m4_probe36_report.json"
AUTHORIZATION_PATH = ROOT / "workspace" / "evals" / "m4_probe36_authorization.json"


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


def test_m4_probe36_report_binds_equipment_object_gap():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    authorization = json.loads(AUTHORIZATION_PATH.read_text(encoding="utf-8"))

    assert report["probe_number"] == 36
    assert report["task_id"] == "BM-012"
    assert authorization["consumed"] is True
    assert authorization["consumed_by_episode"] == report["episode_id"]
    assert authorization["next_authorization"] is False

    for name, path in report["evidence_paths"].items():
        assert _sha256(ROOT / path) == report["evidence_sha256"][name]

    events = _events(report)
    calls = [event for event in events if event.get("type") == "llm_planner_call"]
    real_calls = [call for call in calls if call["data"]["real_llm_call"]]
    actions = [event for event in events if event.get("type") == "action"]

    assert len(events) == 1016
    assert len(calls) == 46
    assert len(real_calls) == 34
    assert sum(call["data"]["schema_valid"] is True for call in real_calls) == 32
    assert len(actions) == 29
    assert all(action["data"]["result"]["success"] is True for action in actions)

    assert report["episode_result"]["maximum_inventory"]["stone_pickaxe"] == 1
    assert report["episode_result"]["maximum_inventory"]["raw_iron"] == 0
    assert report["episode_result"]["terminal_inventory"]["stone_pickaxe"] == 1
    assert report["behavioral_progression"]["full_stone_pickaxe_loop_completed"] is True
    assert report["behavioral_progression"]["equipment_contains_grounding_exercised"] is True
    assert report["behavioral_progression"]["stone_pickaxe_to_raw_iron"] is False


def test_probe36_jsonl_exercises_equipment_contains_then_finds_equipment_object():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    events = _events(report)

    equipment_contains_normalized = [
        event
        for event in events
        if event.get("type") == "plan"
        and event["_line"] == 767
        and event["data"]["schema_validation"]["equip_success_criteria_grounding"][
            "normalizations"
        ][0]["source_field"] == "success_criteria.equipment_contains"
    ]
    assert len(equipment_contains_normalized) == 1

    equipment_object_plans = [
        event
        for event in events
        if event.get("type") == "plan"
        and any(
            subtask.get("success_criteria") == {
                "equipment": {"name": "stone_pickaxe"}
            }
            for subtask in event["data"].get("subtasks", [])
            if isinstance(subtask, dict)
        )
    ]
    assert [event["_line"] for event in equipment_object_plans] == [839]

    blocker = report["principal_blocker"]
    assert blocker["failure_layer"] == "m4_equipment_object_equip_criteria_grounding_gap"
    assert blocker["first_equipment_object_plan_line"] == 839
    assert blocker["first_equipment_object_task_deadline_line"] == 893
    assert blocker["first_equipment_object_schema_rejection_line"] == 938
    assert blocker["raw_iron_dig_action_count"] == 0
    assert blocker["stone_search_dig_count_after_raw_iron_goal"] == 2
    assert blocker["early_ready_task_invalid_envelope_count"] == 11
    assert blocker["early_ready_task_invalid_envelope_recovered"] is True
    assert report["offline_repair"]["policy_id"] == (
        "m4-equip-success-criteria-equipment-object-v1"
    )
    assert report["offline_repair"]["validated_offline"] is True
