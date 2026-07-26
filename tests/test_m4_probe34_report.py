import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "workspace" / "evals" / "m4_probe34_report.json"
AUTHORIZATION_PATH = ROOT / "workspace" / "evals" / "m4_probe34_authorization.json"


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


def test_m4_probe34_report_binds_station_frontier_self_interrupt():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    authorization = json.loads(AUTHORIZATION_PATH.read_text(encoding="utf-8"))

    assert report["probe_number"] == 34
    assert report["task_id"] == "BM-012"
    assert report["frozen_controls"]["model"] == "grok-4.5"
    assert report["frozen_controls"]["base_url"] == "http://192.168.3.27:8317/v1"
    assert authorization["consumed"] is True
    assert authorization["consumed_by_episode"] == report["episode_id"]
    assert authorization["maximum_retry_count"] == 0
    assert authorization["next_authorization"] is False

    for name, path in report["evidence_paths"].items():
        assert _sha256(ROOT / path) == report["evidence_sha256"][name]

    events = _events(report)
    calls = [event for event in events if event.get("type") == "llm_planner_call"]
    real_calls = [call for call in calls if call["data"]["real_llm_call"]]
    actions = [event for event in events if event.get("type") == "action"]

    assert len(events) == 570
    assert len(calls) == 16
    assert len(real_calls) == 16
    assert all(call["data"]["schema_valid"] is True for call in real_calls)
    assert len(actions) == 18
    assert all(action["data"]["result"]["success"] is True for action in actions)

    result = report["episode_result"]
    assert result["maximum_inventory"]["wooden_pickaxe"] == 1
    assert result["maximum_inventory"]["cobblestone"] == 3
    assert result["maximum_inventory"]["stone_pickaxe"] == 0
    assert result["terminal_inventory"]["cobblestone"] == 3
    assert result["terminal_health"] == 20
    assert result["death_count"] == 0
    assert report["behavioral_progression"]["wooden_pickaxe_to_three_cobblestone"] is True
    assert report["behavioral_progression"]["cobblestone_to_stone_pickaxe"] is False
    assert report["decision"]["counts_toward_bm012_success"] is False
    assert report["decision"]["counts_toward_capability"] is False


def test_probe34_exercised_repairs_then_found_frontier_yield_blocker():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    review = report["intervention_review"]
    blocker = report["principal_blocker"]

    assert review["probe_33_equip_success_criteria_grounding_live_exercised"] is True
    assert review["equip_grounding_event_line"] == 334
    assert review["equip_grounding_source_field"] == "success_criteria.equipped"
    assert review["probe_32_station_access_repair_live_exercised"] is True
    assert review["station_access_auto_goal_line"] == 414
    assert review["station_access_selected_goal"] == (
        "Craft crafting table for stone-pickaxe crafting"
    )
    assert review["yield_result"] == "intervention_exercised_new_blocker"

    assert blocker["failure_layer"] == "m4_station_access_goal_frontier_yield_self_interrupt"
    assert blocker["first_station_access_goal_line"] == 414
    assert blocker["first_frontier_yield_line"] == 419
    assert blocker["first_interrupt_line"] == 421
    assert blocker["termination_reason"] == (
        "runtime_interrupt:bm012_stone_pickaxe_frontier_ready"
    )
    assert blocker["repeated_station_goal_count"] == 19
    assert blocker["station_goal_action_count"] == 0
    assert blocker["station_goal_planner_call_count"] == 0
    assert blocker["terminal_stone_pickaxe"] == 0
    assert report["offline_repair"]["policy_id"] == (
        "m4-bm012-station-access-frontier-yield-bypass-v1"
    )
    assert report["offline_repair"]["validated_offline"] is True
    assert report["offline_repair"]["probe_35_authorized"] is False


def test_probe34_jsonl_contains_exact_self_interrupt_shape():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    events = _events(report)
    station_goal = "Craft crafting table for stone-pickaxe crafting"

    equip_grounding = [
        event
        for event in events
        if event.get("type") == "llm_planner_call"
        and event["data"].get("schema_validation", {})
        .get("equip_success_criteria_grounding", {})
        .get("normalizations")
    ]
    assert [event["_line"] for event in equip_grounding] == [334]
    normalization = equip_grounding[0]["data"]["schema_validation"][
        "equip_success_criteria_grounding"
    ]["normalizations"][0]
    assert normalization["source_field"] == "success_criteria.equipped"
    assert normalization["item"] == "wooden_pickaxe"

    auto_goals = [
        event
        for event in events
        if event.get("type") == "auto_goal"
        and event["data"].get("goal") == station_goal
    ]
    interruptions = [
        event
        for event in events
        if event.get("type") == "auto_goal_interrupted"
        and event["data"].get("goal") == station_goal
    ]
    yields = [
        event
        for event in events
        if event.get("type") == "m4_bm012_stone_pickaxe_frontier_yield"
    ]
    actions_after_last_stone_dig = [
        event for event in events if event.get("type") == "action" and event["_line"] > 407
    ]
    planner_after_first_station_goal = [
        event
        for event in events
        if event.get("type") == "llm_planner_call" and event["_line"] > 414
    ]

    assert [event["_line"] for event in auto_goals] == [
        414,
        424,
        432,
        440,
        448,
        456,
        464,
        472,
        480,
        488,
        496,
        504,
        512,
        520,
        528,
        536,
        544,
        552,
        560,
    ]
    assert [event["data"]["goal_index"] for event in auto_goals] == list(range(6, 25))
    assert len(interruptions) == 19
    assert all(
        event["data"]["termination_reason"]
        == "runtime_interrupt:bm012_stone_pickaxe_frontier_ready"
        for event in interruptions
    )
    assert [event["_line"] for event in yields] == [419]
    assert yields[0]["data"]["recommended_goal"] == station_goal
    assert actions_after_last_stone_dig == []
    assert planner_after_first_station_goal == []
