import hashlib
import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
RUN_ID = "sp003_baseline_20260720_064839_abb7c5cb"
RUN_DIR = REPO / "workspace/evals/sp003_runs" / RUN_ID


def _load(name: str):
    return json.loads((RUN_DIR / name).read_text(encoding="utf-8"))


def _events(event_type: str):
    return [
        event["data"]
        for event in _load("session.json")
        if event.get("type") == event_type
    ]


def test_phase127_authorization_and_all_retained_payload_hashes_are_bound():
    manifest = _load("manifest.json")
    authorization = _load("authorization.json")
    consumption = _load("authorization_consumption.json")

    assert hashlib.sha256((RUN_DIR / "manifest.json").read_bytes()).hexdigest() == (
        "de2d72cd3963224106aba081e8a13d71c9a7ca1c65857f7fb16546d2d6bba9a2"
    )
    assert manifest["episode_id"] == RUN_ID
    assert manifest["session_id"] == "1dcad8c7-096"
    assert manifest["authorization_id"] == (
        "41859582359f2f565139dd3a470eafce132e1b2b20186f4a7fbb8bc1f610adf5"
    )
    assert manifest["passed"] is False
    assert manifest["evidence_eligible"] is False
    assert manifest["single_episode"] is True
    assert manifest["automatic_retry_allowed"] is False
    assert manifest["bm012_terminal_started"] is False
    assert authorization["authorization_predecessor"] == (
        "8d21c177003aecde3ff9b5159ae4ba780508375d"
    )
    assert authorization["harness_policy_sha256"] == (
        "cff307e100f3071a028f637b5ce2ba5202fe886fc80c843285dc1f60f1009f4f"
    )
    assert authorization["single_episode"] is True
    assert authorization["automatic_retry_allowed"] is False
    assert consumption["authorization_commit"] == (
        "a9ead681a1a36cb1acc1fcd703a6cd37dcd3dc8a"
    )
    assert consumption["consumed_by"] == "fresh_sp003_process_start"
    assert consumption["single_episode"] is True
    assert consumption["automatic_retry_allowed"] is False

    assert len(manifest["files"]) == 12
    for record in manifest["files"]:
        path = REPO / record["path"]
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]


def test_phase127_retains_stage_semantic_success_and_planner_failures():
    episode = _load("episode.json")
    verification = _load("verification.json")
    planner_calls = _events("llm_planner_call")
    plans = _events("plan")
    actions = _events("action")

    goal = episode["goal_result"]
    assert goal["completed"] is False
    assert goal["termination_reason"] == "empty_plan"
    assert goal["cycles"] == 12
    assert goal["action_count"] == 11
    assert goal["elapsed_s"] == 90.234
    assert goal["deadline_eligible"] is True
    assert episode["post_deadline_action_indexes"] == []
    assert episode["reconciled_action_failure_indexes"] == []
    assert episode["unreconciled_action_failures"] == [
        {
            "index": 7,
            "action": {
                "type": "craft",
                "parameters": {"item": "dark_oak_planks", "count": 2},
            },
            "error": (
                "SP-003 action guard rejected: "
                "sp003_exact_one_table_craft_required"
            ),
        }
    ]

    assert [call["call_index"] for call in planner_calls] == list(range(12))
    assert all(call["real_llm_call"] is True for call in planner_calls)
    assert all(call["schema_valid"] is True for call in planner_calls[:11])
    assert planner_calls[11]["schema_valid"] is False
    assert planner_calls[11]["schema_validation"]["issues"] == [
        "reasoning_too_long"
    ]
    assert planner_calls[11]["response_sha256"] == (
        "1d982a0a925e3cdb2f5dd671c579bd599c8b5253800ead9ee662eb22a54cc649"
    )
    assert planner_calls[11]["response_byte_count"] == 838
    assert all(
        call["transport_evidence"]["attempt_count"] == 1
        and call["transport_evidence"]["retry_count"] == 0
        and call["transport_evidence"]["attempts"][0]["success"] is True
        for call in planner_calls
    )
    assert plans[11]["status"] == "error"
    assert plans[11]["actions"] == []
    assert plans[11]["reasoning"] == (
        "Planner output rejected before execution: reasoning_too_long"
    )

    assert [action["action"]["type"] for action in actions] == [
        "move_to",
        "dig",
        "dig",
        "dig",
        "craft",
        "craft",
        "craft",
        "craft",
        "move_to",
        "dig",
        "dig",
    ]
    assert sum(action["result"].get("success") is True for action in actions) == 10
    assert actions[6]["action"]["parameters"] == {
        "item": "dark_oak_planks",
        "count": 2,
    }
    assert actions[6]["result"]["success"] is False
    assert actions[7]["action"]["parameters"] == {
        "item": "crafting_table",
        "count": 1,
    }
    assert actions[7]["result"]["success"] is True

    clearance = [
        action
        for action in actions
        if action["action"]["parameters"].get("stone_surface_clearance") is True
    ]
    assert [action["action"]["parameters"]["source_id"] for action in clearance] == [
        "grass_block:124:142:-37",
        "dirt:124:141:-37",
    ]
    assert all(action["result"]["success"] is True for action in clearance)
    assert all(
        action["action"]["parameters"].get("support_source_id")
        == "stone:124:139:-37"
        for action in clearance
    )
    assert episode["distinct_surface_clearance_source_ids"] == [
        "dirt:124:141:-37",
        "grass_block:124:142:-37",
    ]
    assert episode["table_placement_proofs"] == []
    assert episode["distinct_stone_source_ids"] == []
    assert episode["stable_observation"]["inventory"] == {
        "dark_oak_planks": 6,
        "stick": 4,
        "crafting_table": 1,
        "dirt": 2,
    }
    assert verification["metrics"]["log_source_removal_count"] == 3
    assert verification["metrics"]["surface_clearance_removal_count"] == 2
    assert verification["metrics"]["stone_source_removal_count"] == 0
    assert verification["criteria_issues"] == [
        "all_crafts_single_verified_attempt",
        "exact_task_graph_complete",
        "exact_three_stone_actions",
        "exact_three_stone_sources",
        "goal_machine_completed",
        "one_plank_craft",
        "one_stone_pickaxe_craft",
        "one_table_place",
        "one_wooden_pickaxe_craft",
        "one_wooden_pickaxe_equip",
        "planner_request_controls",
        "pre_dig_pickup_access_machine_proof",
        "same_machine_proven_table_for_tool_crafts",
        "sp001_machine_verifier",
        "sp002_machine_verifier",
        "table_placement_machine_proof",
        "terminal_stone_pickaxe",
        "zero_unreconciled_action_failures",
    ]


def test_phase127_failure_ledger_binds_the_episode_without_granting_credit():
    ledger = json.loads(
        (REPO / "workspace/evals/stone_pickaxe_failure_ledger.json").read_text(
            encoding="utf-8"
        )
    )
    failure = next(
        item
        for item in ledger["failures"]
        if item["id"] == "sp003-baseline-026-stage-action-and-reasoning-envelope"
    )

    assert failure["episode_id"] == RUN_ID
    assert failure["phase_126_target_semantics_live_exercised"] is True
    assert failure["behavioral_empty_hand_to_stone_pickaxe_loop_completed"] is False
    assert failure["strict_sp003_baseline_passed"] is False
    assert failure["automatic_retry_attempted"] is False
    assert failure["counts_toward_baseline_success"] is False
    assert failure["counts_toward_skill_gate"] is False
    assert failure["counts_toward_capability"] is False
    assert failure["counts_toward_m4"] is False
    assert len(failure["evidence"]) == 13
    for record in failure["evidence"]:
        path = REPO / record["path"]
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]

    assert ledger["live_authorization"] is False
    assert ledger["next_required_gate"]["authorization"] is False
    assert ledger["next_required_gate"]["live_episode_limit"] == 0
