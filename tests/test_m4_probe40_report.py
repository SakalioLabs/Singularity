import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "workspace" / "evals" / "m4_probe40_report.json"
AUTHORIZATION_PATH = ROOT / "workspace" / "evals" / "m4_probe40_authorization.json"


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


def _held_item(observation: dict) -> str:
    equipment = observation.get("equipment", [])
    if isinstance(equipment, list) and equipment and isinstance(equipment[0], dict):
        return str(equipment[0].get("name") or "")
    return ""


def test_m4_probe40_report_binds_grok_bm012_resource_scan_failure():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    authorization = json.loads(AUTHORIZATION_PATH.read_text(encoding="utf-8"))

    assert report["probe_number"] == 40
    assert report["task_id"] == "BM-012"
    assert authorization["consumed"] is True
    assert authorization["consumed_by_episode"] == report["episode_id"]
    assert authorization["consumed_session_id"] == report["session_id"]
    assert authorization["next_authorization"] is False

    for name, path in report["evidence_paths"].items():
        assert _sha256(ROOT / path) == report["evidence_sha256"][name]

    assert report["frozen_controls"]["model"] == "grok-4.5"
    assert report["frozen_controls"]["provider_modalities"] == ["text", "image"]
    assert report["frozen_controls"]["runtime_modalities"] == ["text"]
    assert report["episode_result"]["completed"] is False
    assert report["episode_result"]["termination_reason"] == "episode_deadline"
    assert report["episode_result"]["planner_call_count"] == 34
    assert report["episode_result"]["real_planner_call_count"] == 33
    assert report["episode_result"]["schema_valid_real_planner_call_count"] == 32
    assert report["episode_result"]["schema_invalid_real_planner_call_count"] == 1
    assert report["episode_result"]["planner_timeout_call_count"] == 1
    assert report["episode_result"]["action_count"] == 37
    assert report["episode_result"]["successful_action_count"] == 37
    assert report["episode_result"]["failed_action_count"] == 0
    assert report["episode_result"]["terminal_inventory"]["stone_pickaxe"] == 1
    assert report["episode_result"]["terminal_inventory"].get("raw_iron", 0) == 0
    assert report["episode_result"]["terminal_health"] == 20
    assert report["behavioral_progression"]["full_stone_pickaxe_loop_completed"] is True
    assert report["behavioral_progression"]["stone_pickaxe_to_raw_iron"] is False
    assert report["decision"]["counts_toward_bm012_success"] is False
    assert report["decision"]["bm012_success_count_after"] == 1
    assert report["decision"]["counts_toward_capability"] is False


def test_probe40_jsonl_exposes_resource_scan_gap_and_tool_downgrade_loop():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    events = _events(report)

    assert len(events) == 829
    calls = [event for event in events if event.get("type") == "llm_planner_call"]
    real_calls = [call for call in calls if call["data"]["real_llm_call"]]
    actions = [event for event in events if event.get("type") == "action"]

    assert len(calls) == 34
    assert len(real_calls) == 33
    assert sum(call["data"]["schema_valid"] is True for call in real_calls) == 32
    assert sum(call["data"]["schema_valid"] is False for call in real_calls) == 1
    assert len(actions) == 37
    assert sum(action["data"]["result"]["success"] is True for action in actions) == 37

    stone_pickaxe_craft = events[513]
    assert stone_pickaxe_craft["_line"] == 514
    assert stone_pickaxe_craft["data"]["action"] == {
        "type": "craft",
        "parameters": {"item": "stone_pickaxe", "count": 1},
    }
    assert stone_pickaxe_craft["data"]["result"]["success"] is True

    first_search_dig = events[551]
    assert first_search_dig["_line"] == 552
    assert first_search_dig["data"]["action"]["parameters"] == {
        "x": 113,
        "y": 131,
        "z": -29,
        "block": "stone",
    }
    first_result = first_search_dig["data"]["result"]
    assert first_result["success"] is True
    assert first_result["dig_tool_equip"]["selected_tool"] == "wooden_pickaxe"
    assert first_result["dig_tool_equip"]["equipped_tool"] == "wooden_pickaxe"
    assert _held_item(first_search_dig["data"]["pre_observation"]) == "stone_pickaxe"
    assert _held_item(first_search_dig["data"]["post_observation"]) == "wooden_pickaxe"

    search_dig_lines = [552, 582, 629, 718, 759]
    for line in search_dig_lines:
        event = events[line - 1]
        result = event["data"]["result"]
        assert event["data"]["action"]["type"] == "dig"
        assert event["data"]["action"]["parameters"]["block"] == "stone"
        assert result["success"] is True
        assert result["dig_tool_equip"]["selected_tool"] == "wooden_pickaxe"

    dig_actions = [event for event in actions if event["data"]["action"]["type"] == "dig"]
    assert not any(
        event["data"]["action"]["parameters"].get("block") == "iron_ore"
        for event in dig_actions
    )
    observations = [event for event in events if event.get("type") == "observation"]
    assert not any(
        block.get("name") == "iron_ore"
        for event in observations
        for block in event["data"].get("nearby_blocks", [])
        if isinstance(block, dict)
    )

    blocker = report["principal_blocker"]
    assert blocker["failure_layer"] == "m4_bm012_raw_iron_resource_scan_gap"
    assert blocker["secondary_failure_layer"] == "m4_bm012_raw_iron_dig_tool_downgrade_loop"
    assert blocker["first_search_dig_line"] == 552
    assert blocker["first_search_dig_post_held_item"] == "wooden_pickaxe"
    assert blocker["old_observation_saw_iron_ore"] is False
    assert blocker["new_resource_scan_radius"] == 16
    assert blocker["raw_iron_dig_action_count"] == 0


def test_probe40_offline_repair_is_bounded_and_keeps_frozen_controls():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    repair = report["offline_repair"]
    assert repair["policy_id"] == (
        "m4-bm012-resource-scan-and-stone-pickaxe-dig-preference-v1"
    )
    assert repair["bounded_resource_scan_radius"] == 16
    assert repair["preferred_tool_for_raw_iron_search_digs"] == "stone_pickaxe"
    assert repair["backend_preferred_tool_selection_fail_closed"] is True
    assert repair["planner_prompt_surfaces_resource_scan"] is True
    assert repair["protocol_changed"] is False
    assert repair["task_contract_changed"] is False
    assert repair["deadline_policy_changed"] is False
    assert repair["success_threshold_changed"] is False
    assert repair["validated_offline"] is True
