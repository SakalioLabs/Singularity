import hashlib
import json
from pathlib import Path

import pytest

from singularity.evaluation import stone_pickaxe_sp003_phase120_runtime as phase120


REPO = Path(__file__).resolve().parents[1]
RUN_ID = "sp003_baseline_20260720_030918_15498d1d"
RUN_DIR = REPO / "workspace/evals/sp003_runs" / RUN_ID


def _events():
    return json.loads((RUN_DIR / "session.json").read_text(encoding="utf-8"))


def _cell_states(observation):
    return {
        tuple(block["position"][axis] for axis in ("x", "y", "z")): block["name"]
        for block in observation["sp003_complete_local_scan"]["blocks"]
    }


def test_phase121_retained_baseline_replays_step_up_egress_gap():
    manifest = json.loads((RUN_DIR / "manifest.json").read_text(encoding="utf-8"))
    consumption = json.loads(
        (RUN_DIR / "authorization_consumption.json").read_text(encoding="utf-8")
    )
    episode = json.loads((RUN_DIR / "episode.json").read_text(encoding="utf-8"))
    events = _events()

    assert hashlib.sha256((RUN_DIR / "manifest.json").read_bytes()).hexdigest() == (
        "f7f8cb5791c54ef7a6d500d0786592ebbea8392e0591e647643796d624ac6ce4"
    )
    assert manifest["passed"] is False
    assert manifest["evidence_eligible"] is False
    assert manifest["authorization_id"] == (
        "be060bcac33b43af7ec318b6a3d73d2da1e5dc1bc72aa5900ffa30609c3e55fe"
    )
    assert manifest["automatic_retry_allowed"] is False
    assert manifest["bm012_terminal_started"] is False
    assert consumption["authorization_commit"] == (
        "80bfb123169c4f45a2c43d35f37e5c5e5d32e20f"
    )
    assert consumption["consumed_by"] == "fresh_sp003_process_start"
    assert consumption["single_episode"] is True
    assert consumption["automatic_retry_allowed"] is False

    goal = episode["goal_result"]
    assert goal["termination_reason"] == "blocked_plan"
    assert goal["deadline_eligible"] is True
    assert goal["cycles"] == 14
    assert goal["action_count"] == 13
    assert goal["elapsed_s"] == pytest.approx(93.031)
    assert episode["reconciled_action_failure_indexes"] == []
    assert episode["post_deadline_action_indexes"] == []
    assert episode["unreconciled_action_failures"] == [
        {
            "index": 13,
            "action": {"type": "wait", "parameters": {"ms": 500}},
            "error": (
                "SP-003 action guard rejected: "
                "sp003_locked_partial_shaft_machine_target_required"
            ),
        }
    ]
    assert episode["distinct_log_source_ids"] == [
        "oak_log:119:140:-33",
        "oak_log:119:141:-33",
        "oak_log:119:142:-33",
    ]
    assert episode["distinct_stone_source_ids"] == []
    assert episode["stable_observation"]["inventory"] == {
        "oak_planks": 6,
        "stick": 4,
        "crafting_table": 1,
        "dirt": 2,
    }
    assert episode["stable_observation"]["position"] == {
        "x": 124.57113692072389,
        "y": 141,
        "z": -36.50994199857221,
    }

    planner_calls = [
        event["data"] for event in events if event.get("type") == "llm_planner_call"
    ]
    assert [call["call_index"] for call in planner_calls] == list(range(14))
    assert all(call["schema_valid"] is True for call in planner_calls)
    assert all(
        call["transport_evidence"]["attempt_count"] == 1
        and call["transport_evidence"]["retry_count"] == 0
        and call["transport_evidence"]["attempts"][0]["success"] is True
        for call in planner_calls
    )

    actions = [event["data"] for event in events if event.get("type") == "action"]
    assert len(actions) == 13
    assert sum(action["result"].get("success") is True for action in actions) == 12
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
        "wait",
    ]
    assert all(action["result"]["success"] is True for action in actions[:12])
    assert actions[-1]["result"]["verification_blocked"] is True
    assert actions[-1]["result"]["error"] == (
        "SP-003 action guard rejected: "
        "sp003_locked_partial_shaft_machine_target_required"
    )

    clearances = actions[10:12]
    assert [action["action"]["parameters"]["source_id"] for action in clearances] == [
        "grass_block:124:142:-37",
        "dirt:124:141:-37",
    ]
    assert {
        action["action"]["parameters"]["support_source_id"]
        for action in clearances
    } == {"stone:124:139:-37"}
    assert all(
        action["result"]["block_removed"] is True for action in clearances
    )
    assert actions[11]["result"]["pickup_collection"]["attempted"] is True
    assert actions[11]["result"]["pickup_collection"]["success"] is True
    assert actions[11]["post_observation"]["position"] == {
        "x": 124.57113692072389,
        "y": 141.76636799395752,
        "z": -36.50994199857221,
    }

    guards = [
        event["data"]
        for event in events
        if event.get("type") == "stone_pickaxe_sp003_action_guard"
    ]
    assert len(guards) == 13
    assert sum(guard["allowed"] is True for guard in guards) == 12
    assert guards[10]["table_staging"]["target_mode"] == "surface_clearance"
    assert guards[11]["table_staging"]["target_mode"] == (
        "locked_surface_clearance"
    )
    assert guards[11]["table_staging"]["partial_shaft_lock"] == {
        "support_source_id": "stone:124:139:-37",
        "support_cell": [124, 139, -37],
        "clearance_count": 1,
        "clearance_source_ids": ["grass_block:124:142:-37"],
        "clearance_source_cells": [[124, 142, -37]],
        "clearance_proof_fingerprints": [
            "5197278a4a9efa66781ae776c552cca8111ff7b0c15821c39a44c99c4a16844d"
        ],
    }
    assert guards[11]["selected_source"]["support_source_id"] == (
        "stone:124:139:-37"
    )
    assert guards[-1]["allowed"] is False
    assert guards[-1]["table_staging"]["blocker"] == (
        "locked_partial_shaft_machine_egress_unavailable"
    )
    assert guards[-1]["table_staging"]["partial_shaft_lock"][
        "clearance_count"
    ] == 2

    terminal_observation = next(
        event["data"]
        for event in reversed(events)
        if event.get("type") == "observation"
        and event["data"]["sp003_progress"]["surface_clearance_removal_count"]
        == 2
    )
    progress = terminal_observation["sp003_progress"]
    assert terminal_observation["sp003_complete_local_scan"]["scan_complete"] is True
    assert terminal_observation["sp003_complete_local_scan"]["origin_cell"] == {
        "x": 124,
        "y": 141,
        "z": -37,
    }
    lock = phase120._partial_clearance_lock(progress)
    assert lock["support_source_id"] == "stone:124:139:-37"
    assert phase120._machine_proven_shaft_egress(terminal_observation, lock) == {}

    states = _cell_states(terminal_observation)
    assert states[(124, 140, -37)] == "dirt"
    assert all(
        (x, 141, z) in states
        for x, z in ((123, -37), (125, -37), (124, -38), (124, -36))
    )
    assert states[(123, 141, -37)] == "grass_block"
    assert (123, 142, -37) not in states
    assert (123, 143, -37) not in states
    origin = (124, 141, -37)
    ground = (123, 141, -37)
    stand = (123, 142, -37)
    head = (123, 143, -37)
    assert abs(stand[0] - origin[0]) + abs(stand[2] - origin[2]) == 1
    assert stand[1] == origin[1] + 1
    assert ground == (stand[0], stand[1] - 1, stand[2])
    assert head == (stand[0], stand[1] + 1, stand[2])

    ledger = json.loads(
        (REPO / "workspace/evals/stone_pickaxe_failure_ledger.json").read_text(
            encoding="utf-8"
        )
    )
    failure = next(
        item
        for item in ledger["failures"]
        if item["id"] == "sp003-baseline-023-step-up-egress-proof-gap"
    )
    assert failure["automatic_retry_attempted"] is False
    assert failure["counts_toward_baseline_success"] is False
    assert len(failure["evidence"]) == 13
    for record in failure["evidence"]:
        path = REPO / record["path"]
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]
