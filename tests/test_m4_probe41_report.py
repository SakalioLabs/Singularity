import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "workspace" / "evals" / "m4_probe41_report.json"
AUTHORIZATION_PATH = ROOT / "workspace" / "evals" / "m4_probe41_authorization.json"


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


def test_m4_probe41_report_binds_toolchain_detour_failure():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    authorization = json.loads(AUTHORIZATION_PATH.read_text(encoding="utf-8"))

    assert report["probe_number"] == 41
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
    assert report["episode_result"]["planner_call_count"] == 23
    assert report["episode_result"]["real_planner_call_count"] == 20
    assert report["episode_result"]["schema_valid_real_planner_call_count"] == 20
    assert report["episode_result"]["schema_invalid_nonreal_call_count"] == 3
    assert report["episode_result"]["action_count"] == 18
    assert report["episode_result"]["successful_action_count"] == 17
    assert report["episode_result"]["terminal_inventory"]["wooden_pickaxe"] == 1
    assert "stone_pickaxe" not in report["episode_result"]["terminal_inventory"]
    assert report["behavioral_progression"]["crafting_table_to_wooden_pickaxe"] is True
    assert report["behavioral_progression"]["wooden_pickaxe_to_three_cobblestone"] is False
    assert report["decision"]["counts_toward_bm012_success"] is False
    assert report["decision"]["bm012_success_count_after"] == 1


def test_probe41_jsonl_exposes_pre_cobblestone_detour():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    events = _events(report)

    assert len(events) == 598
    actions = [event for event in events if event.get("type") == "action"]
    assert len(actions) == 18
    assert sum(action["data"]["result"]["success"] is True for action in actions) == 17

    first_empty = events[127]
    assert first_empty["_line"] == 128
    assert first_empty["type"] == "empty_plan"
    assert first_empty["data"]["goal"] == "Gather 6 oak logs for tools and shelter"

    coal_goal = events[189]
    assert coal_goal["_line"] == 190
    assert coal_goal["type"] == "auto_goal"
    assert coal_goal["data"]["goal"] == "Collect coal or charcoal for torches"
    assert coal_goal["data"]["selection_reason"] == "curriculum_ranked:night_and_cave_safety"

    wooden_pickaxe = events[511]
    assert wooden_pickaxe["_line"] == 512
    assert wooden_pickaxe["data"]["action"] == {
        "type": "craft",
        "parameters": {"item": "wooden_pickaxe", "count": 1},
    }
    assert wooden_pickaxe["data"]["result"]["success"] is True

    dig_blocks = [
        event["data"]["action"]["parameters"].get("block")
        for event in actions
        if event["data"]["action"]["type"] == "dig"
    ]
    assert dig_blocks == ["oak_log"] * 6
    assert not any(block in {"stone", "iron_ore"} for block in dig_blocks)

    deadline = events[583]
    assert deadline["_line"] == 584
    assert deadline["type"] == "episode_deadline_exceeded"
    post_deadline_wait = events[588]
    assert post_deadline_wait["_line"] == 589
    assert post_deadline_wait["data"]["action"]["type"] == "wait"
    assert post_deadline_wait["data"]["result"]["success"] is False


def test_probe41_offline_repair_locks_toolchain_fallbacks():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    blocker = report["principal_blocker"]
    assert blocker["failure_layer"] == "m4_bm012_toolchain_progression_fallback_gap"
    assert blocker["coal_detour_goal_line"] == 190
    assert blocker["wooden_pickaxe_craft_action_line"] == 512
    assert blocker["cobblestone_dig_action_count"] == 0
    assert blocker["terminal_wooden_pickaxe"] == 1

    repair = report["offline_repair"]
    assert repair["policy_id"] == "m4-bm012-toolchain-progression-fallback-lock-v1"
    assert "gather 6 oak_log" not in repair["protected_fallback_prefixes"]
    assert "craft a wooden pickaxe for stone acquisition" in repair["protected_fallback_prefixes"]
    assert "gather 3 cobblestone with the wooden pickaxe" in repair["protected_fallback_prefixes"]
    assert repair["survival_emergencies_still_preserved"] is True
    assert repair["non_m4_controls_unchanged"] is True
    assert repair["protocol_changed"] is False
    assert repair["task_contract_changed"] is False
    assert repair["validated_offline"] is True
