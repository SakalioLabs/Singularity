import hashlib
import json
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[1]
RUN_ID = "sp003_baseline_20260720_015550_a54561d9"
RUN_DIR = REPO / "workspace/evals/sp003_runs" / RUN_ID


def test_phase119_retained_baseline_replays_clearance_budget_fragmentation():
    manifest = json.loads((RUN_DIR / "manifest.json").read_text(encoding="utf-8"))
    consumption = json.loads(
        (RUN_DIR / "authorization_consumption.json").read_text(encoding="utf-8")
    )
    episode = json.loads((RUN_DIR / "episode.json").read_text(encoding="utf-8"))
    events = json.loads((RUN_DIR / "session.json").read_text(encoding="utf-8"))

    assert hashlib.sha256((RUN_DIR / "manifest.json").read_bytes()).hexdigest() == (
        "fb64e76fc8980421a7bb957740f1e11ddadbddf6d82576524c426270fe09080b"
    )
    assert manifest["passed"] is False
    assert manifest["evidence_eligible"] is False
    assert manifest["authorization_id"] == (
        "0f3899baee5ec12b7ccf2fc313971b83a88e427b7946ecf108681754dcff185c"
    )
    assert manifest["automatic_retry_allowed"] is False
    assert manifest["bm012_terminal_started"] is False
    assert consumption["authorization_commit"] == (
        "9225f5e292dc89faa52d6d0133f861adcf6ac7c4"
    )
    assert consumption["consumed_by"] == "fresh_sp003_process_start"
    assert consumption["single_episode"] is True
    assert consumption["automatic_retry_allowed"] is False

    goal = episode["goal_result"]
    assert goal["termination_reason"] == "blocked_plan"
    assert goal["deadline_eligible"] is True
    assert goal["cycles"] == 17
    assert goal["action_count"] == 16
    assert goal["elapsed_s"] == pytest.approx(115.453)
    assert episode["reconciled_action_failure_indexes"] == []
    assert episode["post_deadline_action_indexes"] == []
    assert episode["unreconciled_action_failures"] == [
        {
            "index": 16,
            "action": {"type": "wait", "parameters": {"ms": 500}},
            "error": (
                "SP-003 action guard rejected: "
                "sp003_table_staging_machine_target_required"
            ),
        }
    ]
    assert episode["distinct_log_source_ids"] == [
        "dark_oak_log:118:141:-38",
        "dark_oak_log:119:141:-38",
        "dark_oak_log:119:142:-38",
    ]
    assert episode["distinct_stone_source_ids"] == []
    assert episode["stable_observation"]["inventory"] == {
        "dark_oak_planks": 6,
        "stick": 4,
        "crafting_table": 1,
        "dirt": 6,
    }
    assert episode["stable_observation"]["position"] == {
        "x": 124.55773230697416,
        "y": 140,
        "z": -36.52787840610114,
    }

    planner_calls = [
        event["data"] for event in events if event.get("type") == "llm_planner_call"
    ]
    assert [call["call_index"] for call in planner_calls] == list(range(17))
    assert all(call["schema_valid"] is True for call in planner_calls)
    assert all(
        call["transport_evidence"]["attempt_count"] == 1
        and call["transport_evidence"]["retry_count"] == 0
        and call["transport_evidence"]["attempts"][0]["success"] is True
        for call in planner_calls
    )

    actions = [event["data"] for event in events if event.get("type") == "action"]
    assert len(actions) == 16
    assert sum(item["result"].get("success") is True for item in actions) == 15
    assert [item["action"]["type"] for item in actions[:8]] == [
        "move_to",
        "dig",
        "dig",
        "dig",
        "craft",
        "craft",
        "craft",
        "move_to",
    ]
    assert all(item["result"]["success"] is True for item in actions[:15])

    clearances = actions[8:10] + actions[11:15]
    assert [item["action"]["parameters"]["source_id"] for item in clearances] == [
        "grass_block:121:141:-37",
        "grass_block:122:141:-36",
        "grass_block:124:142:-37",
        "dirt:124:141:-37",
        "dirt:124:140:-37",
        "dirt:124:141:-38",
    ]
    assert [
        item["action"]["parameters"]["support_source_id"] for item in clearances
    ] == [
        "stone:121:138:-37",
        "stone:122:138:-36",
        "stone:124:139:-37",
        "stone:124:139:-37",
        "stone:124:139:-37",
        "stone:124:139:-38",
    ]
    assert len(episode["distinct_surface_clearance_source_ids"]) == 6
    assert len(episode["surface_clearance_transition_proofs"]) == 6
    assert all(
        proof["action_verified"] is True and proof["block_removed"] is True
        for proof in episode["surface_clearance_transition_proofs"]
    )

    first_clearance = actions[8]
    assert first_clearance["pre_observation"]["position"] == {
        "x": 120.30547176468924,
        "y": 141,
        "z": -36.529987051893166,
    }
    assert first_clearance["post_observation"]["position"] == {
        "x": 121.38698174460036,
        "y": 141,
        "z": -36.51064552565356,
    }
    assert first_clearance["result"]["pickup_collection"]["attempted"] is True
    assert first_clearance["result"]["pickup_collection"]["success"] is True

    guards = [
        event["data"]
        for event in events
        if event.get("type") == "stone_pickaxe_sp003_action_guard"
    ]
    assert len(guards) == 16
    assert sum(guard["allowed"] is True for guard in guards) == 15
    normalized = [
        guard for guard in guards if guard["parameter_normalization"]["applied"]
    ]
    assert [
        guard["parameter_normalization"]["machine_target_source_id"]
        for guard in normalized
    ] == ["stone:121:138:-37", "stone:124:139:-37"]
    assert guards[-1]["table_staging"]["blocked"] is True
    assert guards[-1]["table_staging"]["blocker"] == (
        "machine_proven_stone_access_target_unavailable"
    )

    ledger = json.loads(
        (REPO / "workspace/evals/stone_pickaxe_failure_ledger.json").read_text(
            encoding="utf-8"
        )
    )
    failure = next(
        item
        for item in ledger["failures"]
        if item["id"] == "sp003-baseline-022-clearance-budget-fragmentation"
    )
    assert failure["automatic_retry_attempted"] is False
    assert failure["counts_toward_baseline_success"] is False
    assert len(failure["evidence"]) == 13
    for record in failure["evidence"]:
        path = REPO / record["path"]
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]
