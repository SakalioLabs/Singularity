import hashlib
import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
RUN_ID = "sp003_baseline_20260720_051930_f39bab4c"
RUN_DIR = REPO / "workspace/evals/sp003_runs" / RUN_ID


def _load(name: str):
    return json.loads((RUN_DIR / name).read_text(encoding="utf-8"))


def _events(event_type: str):
    return [
        event["data"]
        for event in _load("session.json")
        if event.get("type") == event_type
    ]


def test_phase125_authorization_and_all_retained_payload_hashes_are_bound():
    manifest = _load("manifest.json")
    authorization = _load("authorization.json")
    consumption = _load("authorization_consumption.json")

    assert hashlib.sha256((RUN_DIR / "manifest.json").read_bytes()).hexdigest() == (
        "0ef3e451deab673caf500d975098b5f050a3236a6fac8a13f79e7557e97f177e"
    )
    assert manifest["episode_id"] == RUN_ID
    assert manifest["session_id"] == "0674ec29-1be"
    assert manifest["authorization_id"] == (
        "6ec558902e8fcb1e8640caee4be67d2fc9bd7e5111c6affefd7e11a7023103c7"
    )
    assert manifest["passed"] is False
    assert manifest["evidence_eligible"] is False
    assert manifest["single_episode"] is True
    assert manifest["automatic_retry_allowed"] is False
    assert manifest["bm012_terminal_started"] is False
    assert authorization["authorization_predecessor"] == (
        "19d5780e6b125ab3353ed00d5ab18ae273461434"
    )
    assert authorization["single_episode"] is True
    assert authorization["automatic_retry_allowed"] is False
    assert consumption["authorization_commit"] == (
        "c524b0c723ff5bc6a8d4d4e20f3108f56487007b"
    )
    assert consumption["consumed_by"] == "fresh_sp003_process_start"
    assert consumption["single_episode"] is True
    assert consumption["automatic_retry_allowed"] is False

    assert len(manifest["files"]) == 12
    for record in manifest["files"]:
        path = REPO / record["path"]
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]


def test_phase125_live_proves_first_tool_craft_and_retains_strict_blockers():
    episode = _load("episode.json")
    verification = _load("verification.json")
    planner_calls = _events("llm_planner_call")
    plans = _events("plan")
    actions = _events("action")

    goal = episode["goal_result"]
    assert goal["completed"] is True
    assert goal["termination_reason"] == "goal_verified"
    assert goal["cycles"] == 24
    assert goal["action_count"] == 24
    assert goal["elapsed_s"] == 149.0
    assert goal["deadline_eligible"] is True
    assert episode["post_deadline_action_indexes"] == []
    assert episode["reconciled_action_failure_indexes"] == []
    assert episode["unreconciled_action_failures"] == [
        {
            "index": 14,
            "action": {
                "type": "dig",
                "parameters": {
                    "block": "grass_block",
                    "x": 123,
                    "y": 141,
                    "z": -37,
                },
            },
            "error": (
                "SP-003 action guard rejected: "
                "sp003_action_forbidden_for_stage:prepare_wooden_pickaxe:dig"
            ),
        }
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
    failure_call = planner_calls[13]
    assert failure_call["response_sha256"] == (
        "680d20b2c4a06aaa7ce6de33c536ff08396c1df45188b4cb3bfbd6e1f23043e1"
    )
    assert failure_call["response_byte_count"] == 586
    failure_plan = next(
        plan
        for plan in plans
        if plan["planner_call_id"] == failure_call["call_id"]
    )
    assert failure_plan["reasoning"] == (
        "Stage place_crafting_table: first target has stone_surface_clearance=true, "
        "dig the grass_block target to clear surface."
    )
    assert failure_plan["actions"] == [
        {
            "type": "dig",
            "parameters": {"block": "grass_block", "x": 123, "y": 141, "z": -37},
        }
    ]

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
        "dig",
        "place",
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
    assert actions[13]["result"]["success"] is False
    assert actions[14]["result"]["placed_position"] == {
        "x": 123,
        "y": 142,
        "z": -37,
    }

    wooden = actions[15]
    assert wooden["action"]["parameters"] == {
        "item": "wooden_pickaxe",
        "count": 1,
    }
    assert wooden["result"]["success"] is True
    assert wooden["result"]["craft_calls"] == 1
    assert wooden["result"]["craft_attempts"] == 1
    assert wooden["result"]["craft_retry_count"] == 0
    assert wooden["result"]["inventory_signed_delta"] == {
        "oak_planks": -3,
        "stick": -2,
        "wooden_pickaxe": 1,
    }
    assert wooden["result"]["crafting_table_position"] == {
        "x": 123,
        "y": 142,
        "z": -37,
    }
    assert wooden["result"]["attempts"][0]["craft_calls"] == 1
    refresh = wooden["result"]["attempts"][0]["authoritative_inventory_refresh"]
    assert refresh["success"] is True
    assert refresh["window_id"] == 3
    assert refresh["crafting_table_position"] == {
        "x": 123,
        "y": 142,
        "z": -37,
    }

    stone = actions[23]
    assert stone["action"]["parameters"] == {"item": "stone_pickaxe", "count": 1}
    assert stone["result"]["success"] is True
    assert stone["result"]["craft_calls"] == 1
    assert stone["result"]["craft_attempts"] == 1
    assert stone["result"]["craft_retry_count"] == 0
    assert stone["result"]["inventory_signed_delta"] == {
        "stick": -2,
        "cobblestone": -3,
        "stone_pickaxe": 1,
    }
    assert stone["result"]["crafting_table_position"] == (
        wooden["result"]["crafting_table_position"]
    )

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

    requested_surface = [
        action
        for action in actions
        if action["action"]["type"] == "dig"
        and action["action"]["parameters"].get("block") in {"grass_block", "dirt"}
    ]
    assert len(requested_surface) == 6
    assert sum(action["result"].get("success") is True for action in requested_surface) == 5
    assert verification["metrics"]["surface_clearance_removal_count"] == 5
    assert verification["metrics"]["stone_source_removal_count"] == 3
    assert verification["components"]["sp002"]["passed"] is True
    assert verification["components"]["sp001"]["criteria_issues"] == [
        "initial_movable",
        "transition_1:nearest_observed_source",
        "transition_3:nearest_observed_source",
    ]
    assert verification["criteria_issues"] == [
        "bounded_surface_clearance_machine_proof",
        "sp001_machine_verifier",
        "zero_unreconciled_action_failures",
    ]


def test_phase125_failure_ledger_binds_the_episode_without_granting_credit():
    ledger = json.loads(
        (REPO / "workspace/evals/stone_pickaxe_failure_ledger.json").read_text(
            encoding="utf-8"
        )
    )
    failure = next(
        item
        for item in ledger["failures"]
        if item["id"] == "sp003-baseline-025-stage-target-and-sp001-source-order"
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
