import hashlib
import json
from pathlib import Path

import pytest

from singularity.evaluation import stone_pickaxe_sp003_phase122_runtime as phase122


REPO = Path(__file__).resolve().parents[1]
RUN_ID = "sp003_baseline_20260720_040104_4676408a"
RUN_DIR = REPO / "workspace/evals/sp003_runs" / RUN_ID


def _events():
    return json.loads((RUN_DIR / "session.json").read_text(encoding="utf-8"))


def test_phase123_retains_behavioral_loop_with_strict_first_craft_failure():
    manifest = json.loads((RUN_DIR / "manifest.json").read_text(encoding="utf-8"))
    consumption = json.loads(
        (RUN_DIR / "authorization_consumption.json").read_text(encoding="utf-8")
    )
    episode = json.loads((RUN_DIR / "episode.json").read_text(encoding="utf-8"))
    verification = json.loads(
        (RUN_DIR / "verification.json").read_text(encoding="utf-8")
    )
    events = _events()

    assert hashlib.sha256((RUN_DIR / "manifest.json").read_bytes()).hexdigest() == (
        "6420a734dd42c74a7c866f7cb3a23e5d2bb2f2b774a037e0f853d0a9b12a6133"
    )
    assert manifest["passed"] is False
    assert manifest["evidence_eligible"] is False
    assert manifest["authorization_id"] == (
        "059c91792260b6ee49d7333c16d8e14e8ac55a54d7f6c136da98ccc40c704d91"
    )
    assert manifest["automatic_retry_allowed"] is False
    assert manifest["bm012_terminal_started"] is False
    assert consumption["authorization_commit"] == (
        "8dd14bfe7183c78218019cb3a3344d1e87a5c4ed"
    )
    assert consumption["consumed_by"] == "fresh_sp003_process_start"
    assert consumption["single_episode"] is True
    assert consumption["automatic_retry_allowed"] is False

    goal = episode["goal_result"]
    assert goal["completed"] is True
    assert goal["termination_reason"] == "goal_verified"
    assert goal["deadline_eligible"] is True
    assert goal["cycles"] == 24
    assert goal["action_count"] == 24
    assert goal["elapsed_s"] == pytest.approx(153.375)
    assert episode["post_deadline_action_indexes"] == []
    assert episode["reconciled_action_failure_indexes"] == []
    assert episode["unreconciled_action_failures"] == [
        {
            "index": 15,
            "action": {
                "type": "craft",
                "parameters": {"item": "wooden_pickaxe", "count": 1},
            },
            "error": (
                "Crafted wooden_pickaxe output did not remain stable after 1 attempts"
            ),
        }
    ]

    planner_calls = [
        event["data"] for event in events if event.get("type") == "llm_planner_call"
    ]
    assert [call["call_index"] for call in planner_calls] == list(range(24))
    assert all(call["real_llm_call"] is True for call in planner_calls)
    assert all(call["schema_valid"] is True for call in planner_calls)
    assert all(
        call["transport_evidence"]["attempt_count"] == 1
        and call["transport_evidence"]["retry_count"] == 0
        and call["transport_evidence"]["attempts"][0]["success"] is True
        for call in planner_calls
    )

    actions = [event["data"] for event in events if event.get("type") == "action"]
    assert len(actions) == 24
    assert sum(action["result"].get("success") is True for action in actions) == 23
    assert [action["action"]["type"] for action in actions] == [
        "move_to",
        "dig",
        "dig",
        "dig",
        "craft",
        "craft",
        "craft",
        "move_to",
        "move_to",
        "move_to",
        "dig",
        "dig",
        "dig",
        "place",
        "craft",
        "craft",
        "equip",
        "dig",
        "dig",
        "dig",
        "move_to",
        "dig",
        "dig",
        "craft",
    ]
    assert actions[13]["result"]["placed_position"] == {
        "x": 123,
        "y": 142,
        "z": -37,
    }

    first_wood = actions[14]
    assert first_wood["action"]["parameters"] == {
        "item": "wooden_pickaxe",
        "count": 1,
    }
    assert first_wood["result"]["success"] is False
    assert first_wood["result"]["craft_attempts"] == 1
    assert first_wood["result"]["craft_retry_count"] == 0
    assert first_wood["result"]["inventory_before"] == (
        first_wood["result"]["inventory_after"]
    )
    assert first_wood["result"]["inventory_signed_delta"] == {}
    first_attempt = first_wood["result"]["attempts"][0]
    assert first_attempt["craft_calls"] == 1
    assert first_attempt["success"] is False
    assert first_attempt["authoritative_inventory_refresh"]["success"] is True
    assert first_attempt["authoritative_inventory_refresh"]["window_id"] == 2
    assert first_attempt["authoritative_inventory_refresh"][
        "crafting_table_position"
    ] == {"x": 123, "y": 142, "z": -37}

    second_wood = actions[15]
    assert second_wood["result"]["success"] is True
    assert second_wood["result"]["craft_attempts"] == 1
    assert second_wood["result"]["craft_retry_count"] == 0
    assert second_wood["result"]["inventory_signed_delta"] == {
        "oak_planks": -3,
        "stick": -2,
        "wooden_pickaxe": 1,
    }
    assert second_wood["result"]["crafting_table_position"] == {
        "x": 123,
        "y": 142,
        "z": -37,
    }

    stone_crafts = [
        action
        for action in actions
        if action["action"]["type"] == "craft"
        and action["action"]["parameters"].get("item") == "stone_pickaxe"
    ]
    assert len(stone_crafts) == 1
    assert stone_crafts[0]["result"]["success"] is True
    assert stone_crafts[0]["result"]["crafting_table_position"] == {
        "x": 123,
        "y": 142,
        "z": -37,
    }
    assert stone_crafts[0]["result"]["inventory_signed_delta"] == {
        "stick": -2,
        "cobblestone": -3,
        "stone_pickaxe": 1,
    }

    assert episode["distinct_log_source_ids"] == [
        "oak_log:119:140:-33",
        "oak_log:119:141:-33",
        "oak_log:119:142:-33",
    ]
    assert episode["distinct_surface_clearance_source_ids"] == [
        "dirt:124:140:-37",
        "dirt:124:140:-38",
        "dirt:124:141:-37",
        "dirt:124:141:-38",
        "grass_block:124:142:-37",
    ]
    assert episode["distinct_stone_source_ids"] == [
        "stone:124:138:-38",
        "stone:124:139:-37",
        "stone:124:139:-38",
    ]
    assert episode["stable_observation"]["inventory"] == {
        "oak_planks": 3,
        "stone_pickaxe": 1,
        "dirt": 5,
        "wooden_pickaxe": 1,
    }
    assert episode["task_graph"]["task_count"] == 5
    assert all(
        task["status"] == "completed" for task in episode["task_graph"]["tasks"]
    )
    assert verification["components"]["sp002"]["passed"] is True
    assert verification["components"]["sp001"]["passed"] is False
    assert verification["components"]["sp001"]["criteria_issues"] == [
        "initial_movable",
        "transition_1:nearest_observed_source",
        "transition_3:nearest_observed_source",
    ]

    assert verification["criteria_issues"] == [
        "all_crafts_single_verified_attempt",
        "one_wooden_pickaxe_craft",
        "same_machine_proven_table_for_tool_crafts",
        "sp001_machine_verifier",
        "zero_unreconciled_action_failures",
    ]
    assert verification["metrics"]["surface_clearance_removal_count"] == 5
    assert verification["metrics"]["stone_source_removal_count"] == 3
    assert verification["task_graph"]["passed"] is True

    guards = [
        event["data"]
        for event in events
        if event.get("type") == "stone_pickaxe_sp003_action_guard"
    ]
    assert len(guards) == 24
    assert all(guard["allowed"] is True for guard in guards)
    assert all(
        guard["policy_id"] == phase122.SP003_PARTIAL_SHAFT_STEP_UP_POLICY_ID
        for guard in guards
    )
    assert [guards[index]["table_staging"].get("target_mode") for index in range(10, 13)] == [
        "surface_clearance",
        "locked_surface_clearance",
        "locked_surface_clearance",
    ]
    assert all(
        guard.get("table_staging", {}).get("target_mode")
        != "locked_shaft_step_up_egress"
        for guard in guards
    )

    ledger = json.loads(
        (REPO / "workspace/evals/stone_pickaxe_failure_ledger.json").read_text(
            encoding="utf-8"
        )
    )
    failure = next(
        item
        for item in ledger["failures"]
        if item["id"] == "sp003-baseline-024-first-table-tool-craft-noop"
    )
    assert failure["automatic_retry_attempted"] is False
    assert failure["behavioral_empty_hand_to_stone_pickaxe_loop_completed"] is True
    assert failure["counts_toward_baseline_success"] is False
    assert len(failure["evidence"]) == 13
    for record in failure["evidence"]:
        path = REPO / record["path"]
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]

    for record in manifest["files"]:
        path = REPO / record["path"]
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]
