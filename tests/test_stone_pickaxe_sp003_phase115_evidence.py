import hashlib
import json
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[1]


def test_phase115_retained_baseline_replays_destroyed_egress_anchor_trap():
    run_dir = (
        REPO
        / "workspace/evals/sp003_runs/sp003_baseline_20260719_232840_66a67eeb"
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
        "24978bdcec2b06f48e3c47fd589e6a5b99ba189fdd47f9efecc7ea4be31702ae"
    )
    assert manifest["automatic_retry_allowed"] is False
    assert manifest["bm012_terminal_started"] is False
    assert consumption["authorization_commit"] == (
        "831a51b349d2dd1f932724cfb4b602e6627816ab"
    )
    assert consumption["consumed_by"] == "fresh_sp003_process_start"
    assert consumption["single_episode"] is True
    assert consumption["automatic_retry_allowed"] is False

    goal = episode["goal_result"]
    assert goal["termination_reason"] == "max_actions"
    assert goal["deadline_eligible"] is True
    assert goal["cycles"] == 33
    assert goal["action_count"] == 32
    assert goal["elapsed_s"] == pytest.approx(178.922)
    assert len(episode["raw_action_failures"]) == 11
    assert episode["reconciled_action_failure_indexes"] == []
    assert len(episode["unreconciled_action_failures"]) == 11
    assert episode["post_deadline_action_indexes"] == []
    assert len(episode["distinct_log_source_ids"]) == 3
    assert len(episode["distinct_surface_clearance_source_ids"]) == 5
    assert episode["distinct_stone_source_ids"] == [
        "stone:124:138:-37",
        "stone:124:139:-37",
        "stone:124:139:-38",
    ]
    assert episode["stable_observation"]["inventory"] == {
        "stick": 2,
        "oak_planks": 3,
        "wooden_pickaxe": 1,
        "dirt": 5,
        "cobblestone": 3,
    }
    assert episode["stable_observation"]["position"] == {
        "x": 124.49954446143933,
        "y": 138,
        "z": -36.53685937630339,
    }

    planner_calls = [
        event["data"]
        for event in events
        if event.get("type") == "llm_planner_call"
    ]
    assert [call["call_index"] for call in planner_calls] == list(range(33))
    assert all(call["schema_valid"] is True for call in planner_calls)
    assert all(
        call["transport_evidence"]["attempt_count"] == 1
        and call["transport_evidence"]["retry_count"] == 0
        and call["transport_evidence"]["attempts"][0]["success"] is True
        for call in planner_calls
    )

    actions = [event["data"] for event in events if event.get("type") == "action"]
    assert len(actions) == 32
    assert sum(item["result"].get("success") is True for item in actions) == 21
    assert actions[16]["action"]["parameters"]["source_id"] == (
        "dirt:124:141:-38"
    )
    assert actions[17]["action"]["parameters"]["source_id"] == (
        "dirt:124:140:-38"
    )
    assert [
        item["action"]["parameters"]["source_id"] for item in actions[18:21]
    ] == [
        "stone:124:139:-38",
        "stone:124:139:-37",
        "stone:124:138:-37",
    ]
    assert all(
        item["result"]["block_removed"] is True
        and item["result"]["pickup_observed"] is True
        and item["result"]["pickup_inventory_delta"] == {"cobblestone": 1}
        for item in actions[18:21]
    )

    action_20_guard_index = next(
        index
        for index, event in enumerate(events)
        if event.get("type") == "stone_pickaxe_sp003_action_guard"
        and event.get("data", {}).get("action", {}).get("parameters", {}).get(
            "source_id"
        )
        == "stone:124:139:-37"
    )
    pre_action_20 = next(
        event["data"]
        for event in reversed(events[:action_20_guard_index])
        if event.get("type") == "observation"
        and isinstance(
            event.get("data", {}).get("sp003_complete_local_scan"), dict
        )
    )
    scan = pre_action_20["sp003_complete_local_scan"]
    assert scan["origin_cell"] == {"x": 124, "y": 139, "z": -38}
    assert scan["targeted_air_visibility_complete"] is True
    assert scan["visibility_distance_strict_upper_bound"] > 3.3
    by_cell = {
        (item["position"]["x"], item["position"]["y"], item["position"]["z"]): item["name"]
        for item in scan["blocks"]
    }
    assert by_cell[(124, 139, -37)] == "stone"
    assert (124, 140, -37) not in by_cell
    assert (124, 141, -37) not in by_cell
    assert {
        (123, 139, -38): by_cell[(123, 140, -38)],
        (125, 139, -38): by_cell[(125, 140, -38)],
        (124, 139, -39): by_cell[(124, 140, -39)],
    } == {
        (123, 139, -38): "dirt",
        (125, 139, -38): "dirt",
        (124, 139, -39): "dirt",
    }

    failed_moves = actions[21:]
    assert len(failed_moves) == 11
    assert all(item["action"]["type"] == "move_to" for item in failed_moves)
    assert all(
        item["result"]["error"]
        == "pathfinder completed without reaching the target tolerance"
        for item in failed_moves
    )
    assert all(
        item["post_observation"]["position"]
        == {"x": 124.49954446143933, "y": 138, "z": -36.53685937630339}
        for item in failed_moves
    )

    final_scan = next(
        event["data"]["sp003_complete_local_scan"]
        for event in reversed(events)
        if event.get("type") == "observation"
        and isinstance(
            event.get("data", {}).get("sp003_complete_local_scan"), dict
        )
    )
    final_by_cell = {
        (item["position"]["x"], item["position"]["y"], item["position"]["z"]): item["name"]
        for item in final_scan["blocks"]
    }
    assert final_scan["origin_cell"] == {"x": 124, "y": 138, "z": -37}
    assert (124, 138, -37) not in final_by_cell
    assert {
        "west": final_by_cell[(123, 138, -37)],
        "east": final_by_cell[(125, 138, -37)],
        "north": final_by_cell[(124, 138, -36)],
        "south": final_by_cell[(124, 138, -38)],
    } == {
        "west": "dirt",
        "east": "stone",
        "north": "stone",
        "south": "stone",
    }

    ledger = json.loads(
        (REPO / "workspace/evals/stone_pickaxe_failure_ledger.json").read_text(
            encoding="utf-8"
        )
    )
    failure = next(
        item
        for item in ledger["failures"]
        if item["id"] == "sp003-baseline-020-destroyed-egress-anchor-trap"
    )
    assert failure["automatic_retry_attempted"] is False
    assert failure["counts_toward_baseline_success"] is False
    assert len(failure["evidence"]) == 13
    for record in failure["evidence"]:
        path = REPO / record["path"]
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]
