from __future__ import annotations

import hashlib
import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
RUN_ID = "sp003_baseline_20260720_095823_dad3c456"
RUN_DIR = REPO / "workspace/evals/sp003_runs" / RUN_ID
MANIFEST_SHA256 = "2ae4db2da1170ee976ce26fc42b03088ee0cfe13f60c226f4b44137159cdbee2"


def _load(name: str):
    return json.loads((RUN_DIR / name).read_text(encoding="utf-8"))


def _events(event_type: str):
    return [
        event["data"]
        for event in _load("session.json")
        if event.get("type") == event_type
    ]


def test_phase131_authorization_and_all_retained_payload_hashes_are_bound():
    manifest = _load("manifest.json")
    authorization = _load("authorization.json")
    consumption = _load("authorization_consumption.json")

    assert hashlib.sha256((RUN_DIR / "manifest.json").read_bytes()).hexdigest() == (
        MANIFEST_SHA256
    )
    assert manifest["episode_id"] == RUN_ID
    assert manifest["session_id"] == "5a470132-880"
    assert manifest["authorization_id"] == (
        "fd17e73797b4b227bde7da626b53ca563c222958b45c5af4dd6d601a96add3a9"
    )
    assert manifest["passed"] is False
    assert manifest["evidence_eligible"] is False
    assert manifest["single_episode"] is True
    assert manifest["automatic_retry_allowed"] is False
    assert manifest["bm012_terminal_started"] is False
    assert authorization["authorization_predecessor"] == (
        "a7f8cc140a2bc7b037595a980f6ef8512370c9f1"
    )
    assert authorization["harness_policy_sha256"] == (
        "231ebbed2a6371af2027b6b1e4b0730cd6535fd8f71e23196892ed4545d71727"
    )
    assert consumption["authorization_commit"] == (
        "67f4412294f4250e58612ba88d53b883aaca3fce"
    )
    assert consumption["consumed_by"] == "fresh_sp003_process_start"
    assert consumption["single_episode"] is True
    assert consumption["automatic_retry_allowed"] is False

    assert len(manifest["files"]) == 12
    for record in manifest["files"]:
        path = REPO / record["path"]
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]


def test_phase131_retains_behavioral_closure_and_ungrounded_direct_dig_failure():
    episode = _load("episode.json")
    verification = _load("verification.json")
    planner_calls = _events("llm_planner_call")
    plans = _events("plan")
    actions = _events("action")
    guards = _events("stone_pickaxe_sp003_action_guard")
    pre_dispatch = _events("stone_pickaxe_sp003_pre_dispatch_replan")
    actionless = _events("stone_pickaxe_sp003_actionless_planning_replan")
    observations = _events("observation")

    goal = episode["goal_result"]
    assert goal["completed"] is True
    assert goal["termination_reason"] == "goal_verified"
    assert goal["cycles"] == 23
    assert goal["action_count"] == 23
    assert goal["deadline_eligible"] is True
    assert len(planner_calls) == 23
    assert len(plans) == 23
    assert len(actions) == 23
    assert all(call["real_llm_call"] is True for call in planner_calls)
    assert all(call["schema_valid"] is True for call in planner_calls)
    assert all(
        call["transport_evidence"]["attempt_count"] == 1
        and call["transport_evidence"]["retry_count"] == 0
        for call in planner_calls
    )
    assert pre_dispatch == []
    assert actionless == []

    divergent_call = planner_calls[18]
    divergent_plan = plans[18]
    divergent_guard = guards[18]
    divergent_action = actions[18]
    assert divergent_call["call_id"] == "llm-f934d4a226d34e05"
    assert divergent_call["response_sha256"] == (
        "97249519e39c236178da7a4d3b2f2ba99fb8ea78e374b0f38daef272c879caf2"
    )
    assert divergent_plan["actions"] == [
        {
            "type": "dig",
            "parameters": {"block": "stone", "x": 124, "y": 138, "z": -38},
        }
    ]
    assert "navigation_only means only move_to" in divergent_plan["reasoning"]
    assert divergent_guard["policy_id"] == (
        "sp003-partial-clearance-shaft-step-up-egress-v1"
    )
    assert divergent_guard["allowed"] is False
    assert divergent_guard["issues"] == [
        "sp003_stone_grounded_approach_required_before_dig"
    ]
    assert divergent_action["result"]["success"] is False
    assert divergent_action["result"]["duration_ms"] == 0
    assert divergent_action["result"]["verification_blocked"] is True
    assert divergent_action["pre_observation"]["position"] == (
        divergent_action["post_observation"]["position"]
    )
    assert divergent_action["pre_observation"]["inventory"] == (
        divergent_action["post_observation"]["inventory"]
    )
    assert divergent_action["pre_observation"]["nearby_blocks"] == (
        divergent_action["post_observation"]["nearby_blocks"]
    )

    assert actions[19]["action"]["type"] == "move_to"
    assert actions[19]["result"]["success"] is True
    assert actions[20]["action"]["parameters"]["source_id"] == (
        "stone:124:139:-37"
    )
    assert actions[21]["action"]["parameters"]["source_id"] == (
        "stone:124:138:-37"
    )
    assert actions[22]["action"]["parameters"]["item"] == "stone_pickaxe"
    assert actions[22]["result"]["success"] is True

    terminal = observations[-1]
    assert terminal["inventory"] == {
        "stone_pickaxe": 1,
        "oak_planks": 3,
        "dirt": 5,
        "wooden_pickaxe": 1,
    }
    progress = terminal["sp003_progress"]
    assert progress["stone_source_removal_count"] == 3
    assert progress["stone_pickaxe_craft_count"] == 1
    assert verification["criteria"]["goal_machine_completed"] is True
    assert verification["criteria"]["exact_three_stone_sources"] is True
    assert verification["criteria"]["exact_three_stone_actions"] is False
    assert verification["criteria"]["zero_unreconciled_action_failures"] is False
    assert verification["criteria"]["sp002_machine_verifier"] is True
    assert verification["criteria"]["terminal_stone_pickaxe"] is True
    assert verification["criteria_issues"] == [
        "exact_three_stone_actions",
        "sp001_machine_verifier",
        "zero_unreconciled_action_failures",
    ]
    assert len(episode["raw_action_failures"]) == 1
    assert episode["raw_action_failures"] == episode["unreconciled_action_failures"]


def test_phase131_failure_ledger_binds_the_episode_without_granting_credit():
    ledger = json.loads(
        (REPO / "workspace/evals/stone_pickaxe_failure_ledger.json").read_text(
            encoding="utf-8"
        )
    )
    failure = next(
        item
        for item in ledger["failures"]
        if item["id"] == "sp003-baseline-028-ungrounded-stone-direct-dig"
    )

    assert failure["episode_id"] == RUN_ID
    assert failure["behavioral_empty_hand_to_stone_pickaxe_loop_completed"] is True
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
