import hashlib
import json
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[1]


def test_phase117_retained_baseline_replays_exact_navigation_y_rejection():
    run_dir = (
        REPO
        / "workspace/evals/sp003_runs/sp003_baseline_20260720_011038_c6886c53"
    )
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    consumption = json.loads(
        (run_dir / "authorization_consumption.json").read_text(encoding="utf-8")
    )
    episode = json.loads((run_dir / "episode.json").read_text(encoding="utf-8"))
    events = json.loads((run_dir / "session.json").read_text(encoding="utf-8"))

    assert manifest["passed"] is False
    assert manifest["evidence_eligible"] is False
    assert manifest["authorization_id"] == (
        "8c8be4b0431b6b6c18f8e2be1bfdf26d99e435e062df6421c0df23876bc703c7"
    )
    assert manifest["automatic_retry_allowed"] is False
    assert manifest["bm012_terminal_started"] is False
    assert consumption["authorization_commit"] == (
        "38e5c3709102bcde4c43eb417e8aa19c4593f582"
    )
    assert consumption["consumed_by"] == "fresh_sp003_process_start"
    assert consumption["single_episode"] is True
    assert consumption["automatic_retry_allowed"] is False

    goal = episode["goal_result"]
    assert goal["termination_reason"] == "max_duration"
    assert goal["deadline_eligible"] is False
    assert goal["cycles"] == 18
    assert goal["action_count"] == 17
    assert goal["elapsed_s"] == pytest.approx(300.0)
    assert len(episode["raw_action_failures"]) == 8
    assert episode["reconciled_action_failure_indexes"] == []
    assert len(episode["unreconciled_action_failures"]) == 8
    assert episode["post_deadline_action_indexes"] == []
    assert len(episode["distinct_log_source_ids"]) == 3
    assert episode["distinct_surface_clearance_source_ids"] == []
    assert episode["distinct_stone_source_ids"] == []
    assert episode["stable_observation"]["inventory"] == {
        "oak_planks": 6,
        "stick": 4,
        "crafting_table": 1,
    }

    planner_calls = [
        event["data"]
        for event in events
        if event.get("type") == "llm_planner_call"
    ]
    assert [call["call_index"] for call in planner_calls] == list(range(18))
    assert all(call["schema_valid"] is True for call in planner_calls[:17])
    assert planner_calls[17]["schema_valid"] is False
    assert all(
        call["transport_evidence"]["attempt_count"] == 1
        and call["transport_evidence"]["retry_count"] == 0
        and call["transport_evidence"]["attempts"][0]["success"] is True
        for call in planner_calls[:17]
    )
    assert planner_calls[17]["transport_evidence"]["attempt_count"] == 1
    assert planner_calls[17]["transport_evidence"]["retry_count"] == 0
    assert planner_calls[17]["transport_evidence"]["attempts"][0]["success"] is False

    actions = [event["data"] for event in events if event.get("type") == "action"]
    assert len(actions) == 17
    assert sum(item["result"].get("success") is True for item in actions) == 9
    assert [item["action"]["type"] for item in actions[:7]] == [
        "move_to",
        "dig",
        "dig",
        "dig",
        "craft",
        "craft",
        "craft",
    ]
    assert all(item["result"]["success"] is True for item in actions[:7])

    rejected = actions[7:15]
    assert len(rejected) == 8
    assert all(item["action"]["type"] == "move_to" for item in rejected)
    assert all(
        "sp003_table_staging_move_requires_exact_xz"
        in item["result"]["error"]
        for item in rejected
    )
    exact_machine_targets = [
        item
        for item in rejected
        if item["action"]["parameters"]
        == {"x": 121.0, "y": 137.0, "z": -33.0}
    ]
    assert len(exact_machine_targets) == 5
    assert all(
        item["result"]["error"]
        == "SP-003 action guard rejected: sp003_table_staging_move_requires_exact_xz"
        for item in exact_machine_targets
    )
    assert all(
        item["action"]["parameters"]
        == {"x": 121.0, "y": 140.0, "z": -33.0}
        and "sp003_table_staging_navigation_target_mismatch"
        in item["result"]["error"]
        for item in rejected
        if item not in exact_machine_targets
    )

    assert [item["action"]["parameters"] for item in actions[15:]] == [
        {"x": 121.5, "z": -32.5, "tolerance": 1.6, "preserve_inventory": True},
        {"x": 122.5, "z": -35.5, "tolerance": 1.6, "preserve_inventory": True},
    ]
    assert all(item["result"]["success"] is True for item in actions[15:])
    guard_events = [
        event
        for event in events
        if event.get("type") == "stone_pickaxe_sp003_action_guard"
    ]
    assert guard_events[15]["elapsed_s"] - guard_events[7]["elapsed_s"] > 230.0

    ledger = json.loads(
        (REPO / "workspace/evals/stone_pickaxe_failure_ledger.json").read_text(
            encoding="utf-8"
        )
    )
    failure = next(
        item
        for item in ledger["failures"]
        if item["id"] == "sp003-baseline-021-exact-navigation-y-rejection"
    )
    assert failure["automatic_retry_attempted"] is False
    assert failure["counts_toward_baseline_success"] is False
    assert len(failure["evidence"]) == 13
    for record in failure["evidence"]:
        path = REPO / record["path"]
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]
