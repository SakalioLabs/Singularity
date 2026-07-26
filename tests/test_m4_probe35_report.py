import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "workspace" / "evals" / "m4_probe35_report.json"
AUTHORIZATION_PATH = ROOT / "workspace" / "evals" / "m4_probe35_authorization.json"


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


def test_m4_probe35_report_binds_stone_pickaxe_breakthrough_and_failure():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    authorization = json.loads(AUTHORIZATION_PATH.read_text(encoding="utf-8"))

    assert report["probe_number"] == 35
    assert report["task_id"] == "BM-012"
    assert report["frozen_controls"]["model"] == "grok-4.5"
    assert authorization["consumed"] is True
    assert authorization["consumed_by_episode"] == report["episode_id"]
    assert authorization["next_authorization"] is False

    for name, path in report["evidence_paths"].items():
        assert _sha256(ROOT / path) == report["evidence_sha256"][name]

    events = _events(report)
    calls = [event for event in events if event.get("type") == "llm_planner_call"]
    real_calls = [call for call in calls if call["data"]["real_llm_call"]]
    actions = [event for event in events if event.get("type") == "action"]

    assert len(events) == 857
    assert len(calls) == 37
    assert len(real_calls) == 35
    assert sum(call["data"]["schema_valid"] is True for call in real_calls) == 32
    assert len(actions) == 31
    assert sum(action["data"]["result"]["success"] is True for action in actions) == 30

    result = report["episode_result"]
    assert result["maximum_inventory"]["cobblestone"] == 3
    assert result["maximum_inventory"]["stone_pickaxe"] == 1
    assert result["maximum_inventory"]["raw_iron"] == 0
    assert result["terminal_inventory"]["stone_pickaxe"] == 1
    assert result["terminal_inventory"]["coal"] == 1
    assert result["terminal_health"] == 20
    assert result["deadline_eligible"] is False
    assert report["behavioral_progression"]["full_stone_pickaxe_loop_completed"] is True
    assert report["behavioral_progression"]["stone_pickaxe_to_raw_iron"] is False
    assert report["decision"]["counts_toward_bm012_success"] is False


def test_probe35_exercised_station_bypass_then_found_equipment_contains_gap():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    review = report["intervention_review"]
    blocker = report["principal_blocker"]

    assert review["probe_34_station_access_frontier_yield_bypass_live_exercised"] is True
    assert review["frontier_yield_self_interrupt_recurred"] is False
    assert review["station_access_craft_goal_line"] == 443
    assert review["station_access_place_goal_line"] == 492
    assert review["stone_pickaxe_goal_line"] == 521
    assert review["stone_pickaxe_craft_action_line"] == 538
    assert review["stone_pickaxe_craft_delta"] == {"stone_pickaxe": 1}
    assert review["yield_result"] == "intervention_exercised_new_blocker"

    assert blocker["failure_layer"] == "m4_equipment_contains_equip_criteria_grounding_gap"
    assert blocker["first_raw_iron_goal_line"] == 545
    assert blocker["first_equipment_contains_plan_line"] == 554
    assert blocker["unsupported_success_criteria"] == {
        "equipment_contains": "stone_pickaxe"
    }
    assert blocker["first_empty_plan_line"] == 577
    assert blocker["first_runtime_interrupt_line"] == 598
    assert blocker["equip_deadline_interrupt_count"] == 5
    assert blocker["equip_precondition_grounding_failure_count"] == 3
    assert blocker["raw_iron_goal_attempt_count"] == 5
    assert blocker["coal_ore_dig_line"] == 786
    assert blocker["raw_iron_dig_action_count"] == 0
    assert blocker["terminal_raw_iron"] == 0
    assert report["offline_repair"]["policy_id"] == (
        "m4-equip-success-criteria-equipment-contains-v1"
    )
    assert report["offline_repair"]["validated_offline"] is True
    assert report["offline_repair"]["probe_36_authorized"] is False


def test_probe35_jsonl_contains_equipment_contains_and_stone_pickaxe_craft():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    events = _events(report)

    stone_pickaxe_crafts = [
        event
        for event in events
        if event.get("type") == "action"
        and event["data"]["action"].get("type") == "craft"
        and event["data"]["action"].get("parameters", {}).get("item") == "stone_pickaxe"
    ]
    assert [event["_line"] for event in stone_pickaxe_crafts] == [538]
    assert stone_pickaxe_crafts[0]["data"]["result"]["success"] is True
    assert stone_pickaxe_crafts[0]["data"]["result"]["inventory_delta"] == {
        "stone_pickaxe": 1
    }

    equipment_contains = [
        event
        for event in events
        if event.get("type") == "plan"
        if any(
            subtask.get("success_criteria") == {
                "equipment_contains": "stone_pickaxe"
            }
            for subtask in event["data"].get("subtasks", [])
            if isinstance(subtask, dict)
        )
    ]
    assert [event["_line"] for event in equipment_contains] == [554]

    empty_plans = [event for event in events if event.get("type") == "empty_plan"]
    assert [event["_line"] for event in empty_plans] == [577, 656, 691, 797]
    assert sum(
        event["data"]["reason"] == "task_deadline_elapsed"
        and event["data"]["evidence"]["task"] == "Equip stone pickaxe"
        for event in events
        if event.get("type") == "runtime_interrupt"
    ) == 5
    assert [
        event["_line"]
        for event in events
        if event.get("type") == "episode_deadline_exceeded"
    ] == [851]
