import collections
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "workspace" / "evals" / "m4_probe33_report.json"
AUTHORIZATION_PATH = ROOT / "workspace" / "evals" / "m4_probe33_authorization.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _events(report: dict) -> list[dict]:
    return [
        json.loads(line)
        for line in (
            ROOT / report["evidence_paths"]["raw_session_jsonl"]
        ).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_m4_probe33_report_binds_equip_criteria_grounding_gap():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    authorization = json.loads(AUTHORIZATION_PATH.read_text(encoding="utf-8"))

    assert report["probe_number"] == 33
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

    assert len(events) == 1250
    assert len(calls) == 67
    assert len(real_calls) == 62
    assert all(call["data"]["schema_valid"] is True for call in real_calls)
    assert len(actions) == 22
    assert sum(action["data"]["result"]["success"] is True for action in actions) == 20

    result = report["episode_result"]
    assert result["maximum_inventory"]["wooden_pickaxe"] == 1
    assert result["maximum_inventory"]["cobblestone"] == 2
    assert result["maximum_inventory"]["stone_pickaxe"] == 0
    assert result["terminal_inventory"]["cobblestone"] == 2
    assert result["terminal_health"] == 20
    assert result["death_count"] == 0
    assert report["behavioral_progression"]["wooden_pickaxe_to_two_cobblestone"] is True
    assert report["behavioral_progression"]["wooden_pickaxe_to_three_cobblestone"] is False
    assert report["behavioral_progression"]["cobblestone_to_stone_pickaxe"] is False

    blocker = report["principal_blocker"]
    assert blocker["failure_layer"] == "m4_equip_subtask_success_criteria_grounding_gap"
    assert blocker["first_unrecovered_action_line"] == 389
    assert blocker["first_unrecovered_distance_to_target"] == 2.0446464174023595
    assert blocker["navigation_margin_later_recovered_by_dig_line"] == 457
    assert blocker["equip_success_criteria_alias_counts"] == {
        "equipment_has": 1,
        "equipped": 1,
        "wooden_pickaxe_equipped_success_flag": 12,
    }
    assert blocker["equipped_precondition_flag_count"] == 13
    assert blocker["equip_task_deadline_fail_count"] == 12
    assert blocker["mine_task_deadline_fail_count"] == 6
    assert blocker["ready_task_binding_suppression_count"] == 69
    assert blocker["task_machine_completed"] is False
    assert blocker["terminal_stone_pickaxe"] == 0
    assert report["decision"]["counts_toward_bm012_success"] is False
    assert report["decision"]["counts_toward_capability"] is False


def test_probe33_station_access_intervention_was_not_exercised():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    review = report["intervention_review"]

    assert review["probe_32_station_access_repair_live_exercised"] is False
    assert review["yield_result"] == "intervention_not_exercised_new_blocker"
    assert review["maximum_cobblestone_observed"] == 2
    assert review["probe_32_detached_station_blocker_recurred"] is False
    assert report["offline_repair"]["policy_id"] == "m4-equip-success-criteria-grounding-v1"
    assert report["offline_repair"]["normalizes_dependent_precondition_flags"] is True
    assert report["offline_repair"]["validated_offline"] is True
    assert report["offline_repair"]["probe_34_authorized"] is False


def test_probe33_jsonl_contains_the_three_grok_equip_aliases():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    alias_counts = collections.Counter()
    precondition_flag_count = 0

    for event in _events(report):
        if event.get("type") != "plan":
            continue
        for subtask in event["data"].get("subtasks", []):
            criteria = subtask.get("success_criteria", {})
            if "equipment_has" in criteria:
                alias_counts["equipment_has"] += 1
            if "equipped" in criteria:
                alias_counts["equipped"] += 1
            if criteria.get("flags") == ["wooden_pickaxe_equipped"]:
                alias_counts["wooden_pickaxe_equipped_success_flag"] += 1
            preconditions = subtask.get("preconditions", {})
            if preconditions.get("flags") == ["wooden_pickaxe_equipped"]:
                precondition_flag_count += 1

    assert dict(alias_counts) == {
        "equipment_has": 1,
        "equipped": 1,
        "wooden_pickaxe_equipped_success_flag": 12,
    }
    assert precondition_flag_count == 13
