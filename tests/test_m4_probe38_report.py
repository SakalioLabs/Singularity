import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "workspace" / "evals" / "m4_probe38_report.json"
AUTHORIZATION_PATH = ROOT / "workspace" / "evals" / "m4_probe38_authorization.json"


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


def test_m4_probe38_report_binds_grok_bm012_success():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    authorization = json.loads(AUTHORIZATION_PATH.read_text(encoding="utf-8"))

    assert report["probe_number"] == 38
    assert report["task_id"] == "BM-012"
    assert authorization["consumed"] is True
    assert authorization["consumed_by_episode"] == report["episode_id"]
    assert authorization["next_authorization"] is False

    for name, path in report["evidence_paths"].items():
        assert _sha256(ROOT / path) == report["evidence_sha256"][name]

    assert report["frozen_controls"]["model"] == "grok-4.5"
    assert report["frozen_controls"]["provider_modalities"] == ["text", "image"]
    assert report["frozen_controls"]["runtime_modalities"] == ["text"]
    assert report["episode_result"]["completed"] is True
    assert report["episode_result"]["termination_reason"] == "terminal_task_verified"
    assert report["episode_result"]["planner_call_count"] == 34
    assert report["episode_result"]["real_planner_call_count"] == 29
    assert report["episode_result"]["schema_valid_real_planner_call_count"] == 29
    assert report["episode_result"]["schema_invalid_real_planner_call_count"] == 0
    assert report["episode_result"]["action_count"] == 34
    assert report["episode_result"]["successful_action_count"] == 33
    assert report["episode_result"]["failed_action_count"] == 1
    assert report["episode_result"]["terminal_inventory"]["raw_iron"] == 8
    assert report["episode_result"]["terminal_inventory"]["stone_pickaxe"] == 1
    assert report["episode_result"]["terminal_health"] == 20
    assert report["behavioral_progression"]["full_stone_pickaxe_loop_completed"] is True
    assert report["behavioral_progression"]["raw_iron_to_eight"] is True
    assert report["decision"]["counts_toward_bm012_success"] is True
    assert report["decision"]["bm012_success_count_after"] == 1
    assert report["decision"]["counts_toward_capability"] is False


def test_probe38_jsonl_proves_eight_grounded_iron_sources():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    events = _events(report)

    assert len(events) == 821
    calls = [event for event in events if event.get("type") == "llm_planner_call"]
    real_calls = [call for call in calls if call["data"]["real_llm_call"]]
    actions = [event for event in events if event.get("type") == "action"]
    iron_digs = [
        event
        for event in actions
        if event["data"]["action"]["type"] == "dig"
        and event["data"]["action"]["parameters"]["block"] == "iron_ore"
    ]

    assert len(calls) == 34
    assert len(real_calls) == 29
    assert sum(call["data"]["schema_valid"] is True for call in real_calls) == 29
    assert len(actions) == 34
    assert sum(action["data"]["result"]["success"] is True for action in actions) == 33
    assert [event["_line"] for event in iron_digs] == [575, 594, 629, 665, 741, 759, 784, 811]
    assert len({tuple(dig["data"]["result"]["target"].values()) for dig in iron_digs}) == 8
    assert all(dig["data"]["result"]["dig_tool_equip"]["passed"] is True for dig in iron_digs)
    assert all(dig["data"]["result"]["pickup_observed"] is True for dig in iron_digs)
    assert all(
        dig["data"]["result"]["pickup_inventory_delta"]["raw_iron"] == 1
        for dig in iron_digs
    )

    terminal = [event for event in events if event.get("type") == "terminal_resource_verification"]
    assert [event["_line"] for event in terminal] == [815]
    assert terminal[0]["data"]["passed"] is True
    assert terminal[0]["data"]["observed_count"] == 8
    assert terminal[0]["data"]["health"] == 20
    assert terminal[0]["data"]["uninterrupted_survival"] is True
    assert report["resource_acquisition"]["successful_source_action_count"] == 8


def test_probe38_prior_equipment_map_blocker_did_not_recur():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    events = _events(report)

    equipment_map_plans = [
        event
        for event in events
        if event.get("type") == "plan"
        for subtask in event["data"].get("subtasks", [])
        if isinstance(subtask, dict)
        and subtask.get("success_criteria") == {"equipment": {"stone_pickaxe": 1}}
    ]
    invalid_real_calls = [
        event
        for event in events
        if event.get("type") == "llm_planner_call"
        and event["data"]["real_llm_call"]
        and event["data"]["schema_valid"] is False
    ]
    equipment_groundings = []
    precondition_groundings = []
    for event in events:
        validation = event.get("data", {}).get("schema_validation") or {}
        grounding = validation.get("equip_success_criteria_grounding") or {}
        equipment_groundings.extend(grounding.get("normalizations") or [])
        precondition_groundings.extend(grounding.get("precondition_normalizations") or [])

    assert equipment_map_plans == []
    assert invalid_real_calls == []
    assert [
        normalization["source_field"]
        for normalization in equipment_groundings
        if normalization["item"] == "stone_pickaxe"
    ] == [
        "success_criteria.equipment_has",
        "success_criteria.equipment_has",
    ]
    assert precondition_groundings == []
    review = report["intervention_review"]
    assert review["probe_37_equipment_map_transitive_repair_live_exercised"] is False
    assert review["prior_failure_recurred"] is False
    assert review["yield_result"] == "prior_blocker_not_recurred_successful_alternative_path"
    assert report["previous_blocker_regression_check"]["raw_iron_dig_action_count"] == 8
