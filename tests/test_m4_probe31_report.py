import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "workspace" / "evals" / "m4_probe31_report.json"
AUTHORIZATION_PATH = ROOT / "workspace" / "evals" / "m4_probe31_authorization.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_m4_probe31_report_binds_stone_pickaxe_switch_gap():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    authorization = json.loads(AUTHORIZATION_PATH.read_text(encoding="utf-8"))

    assert report["probe_number"] == 31
    assert report["task_id"] == "BM-012"
    assert report["frozen_controls"]["model"] == "grok-4.5"
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

    assert len(calls) == 43
    assert len(real_calls) == 42
    assert all(call["data"]["schema_valid"] is True for call in real_calls)
    assert all(
        call["data"]["transport_evidence"]["attempt_count"] == 1
        and call["data"]["transport_evidence"]["retry_count"] == 0
        for call in real_calls
    )
    assert len(actions) == 32
    assert sum(action["data"]["result"]["success"] is True for action in actions) == 30

    maximum_inventory = report["episode_result"]["maximum_inventory"]
    assert maximum_inventory["wooden_pickaxe"] == 1
    assert maximum_inventory["cobblestone"] == 11
    assert maximum_inventory["stone_pickaxe"] == 0
    assert report["behavioral_progression"]["crafting_table_to_wooden_pickaxe"] is True
    assert report["behavioral_progression"]["wooden_pickaxe_to_cobblestone"] is True
    assert report["behavioral_progression"]["cobblestone_to_stone_pickaxe"] is False

    first = report["first_preparation_transition"]
    assert first["failure_layer"] == "pathfinder_completion_tolerance_margin"
    assert first["distance_to_target"] > first["tolerance"]
    assert first["recovered_by_later_dig_event_index"] == 393

    blocker = report["principal_blocker"]
    assert blocker["failure_layer"] == "m4_stone_pickaxe_progression_goal_granularity_gap"
    assert blocker["cobblestone_3_event_index"] == 543
    assert blocker["stone_pickaxe_craft_action_count"] == 0
    assert blocker["task_deadline_interrupt_count"] == 14
    assert blocker["dusk_shelter_interrupt_event_index"] == 874
    assert report["decision"]["counts_toward_bm012_success"] is False
    assert report["decision"]["counts_toward_capability"] is False


def test_probe31_did_not_recur_probe30_death_gap():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    review = report["intervention_review"]

    assert review["probe_30_preplanner_death_recurred"] is False
    assert review["branch_exercised"] is False
    assert review["health_preserved"] is True
    assert report["episode_result"]["terminal_health"] == 20
    assert report["episode_result"]["death_count"] == 0
    assert report["episode_result"]["respawn_count"] == 0
