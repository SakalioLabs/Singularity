import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "workspace" / "evals" / "m4_probe32_report.json"
AUTHORIZATION_PATH = ROOT / "workspace" / "evals" / "m4_probe32_authorization.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_m4_probe32_report_binds_detached_station_frontier_gap():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    authorization = json.loads(AUTHORIZATION_PATH.read_text(encoding="utf-8"))

    assert report["probe_number"] == 32
    assert report["task_id"] == "BM-012"
    assert report["frozen_controls"]["model"] == "grok-4.5"
    assert report["frozen_controls"]["base_url"] == "http://192.168.3.27:8317/v1"
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

    assert len(calls) == 22
    assert len(real_calls) == 22
    assert all(call["data"]["schema_valid"] is True for call in real_calls)
    assert all(
        call["data"]["transport_evidence"]["attempt_count"] == 1
        and call["data"]["transport_evidence"]["retry_count"] == 0
        for call in real_calls
    )
    assert len(actions) == 20
    assert sum(action["data"]["result"]["success"] is True for action in actions) == 18

    maximum_inventory = report["episode_result"]["maximum_inventory"]
    assert maximum_inventory["wooden_pickaxe"] == 1
    assert maximum_inventory["cobblestone"] == 3
    assert maximum_inventory["stone_pickaxe"] == 0
    assert report["behavioral_progression"]["wooden_pickaxe_to_three_cobblestone"] is True
    assert report["behavioral_progression"]["three_cobblestone_frontier_yield_exercised"] is True
    assert report["behavioral_progression"]["cobblestone_to_stone_pickaxe"] is False

    blocker = report["principal_blocker"]
    assert blocker["failure_layer"] == "m4_stone_pickaxe_detached_crafting_station_frontier_gap"
    assert blocker["first_cobblestone_3_observation_index"] == 507
    assert blocker["crafting_table_nearby_at_cobblestone_3"] is False
    assert blocker["goal_generator_fallback_after_cobblestone_3"] == "Gather 6 oak logs for iron-tool progression"
    assert blocker["first_coal_curriculum_event_index"] == 527
    assert blocker["coal_goal_repeat_count"] == 19
    assert blocker["stone_pickaxe_craft_action_count"] == 0
    assert report["decision"]["counts_toward_bm012_success"] is False
    assert report["decision"]["counts_toward_capability"] is False


def test_probe32_frontier_yield_was_exercised_but_found_new_blocker():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    review = report["intervention_review"]

    assert review["probe_31_stone_pickaxe_frontier_yield_branch_exercised"] is True
    assert review["yield_event_count"] == 1
    assert review["yield_result"] == "intervention_exercised_new_blocker"
    assert review["yield_recommended_goal"] == "Gather 6 oak logs for iron-tool progression"
    assert report["offline_repair"]["policy_id"] == "m4-bm012-stone-pickaxe-station-access-v1"
    assert report["offline_repair"]["validated_offline"] is True
    assert report["offline_repair"]["probe_33_authorized"] is False
