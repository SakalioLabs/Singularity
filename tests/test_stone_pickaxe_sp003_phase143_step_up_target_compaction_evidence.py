"""Evidence checks for the single-use Phase 143 step-up target failure."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
RUN_ID = "sp003_baseline_20260720_173513_afba21cd"
RUN_DIR = REPO / "workspace/evals/sp003_runs" / RUN_ID
MANIFEST_SHA256 = "b8c901cc1f200815bbc32c43d2fb0bcacbbf17ba9d71365de0bc592b216fb71e"
FILE_HASHES = {
    "audit.json": "af36bcc89bd611652f37b815a9ba51bc0656ec0cbb046d5b5dc133dfb53cdef5",
    "authorization.json": "4536ccd7845fe24c631710cd41c54c9ee442c4355034860739cb45fd2a9138f3",
    "authorization_consumption.json": "79a995577a55fb1f269054c7348c164251512a20afb16e65d12d3979fbaaed8a",
    "episode.json": "00ac16454a9732e2202cb5a99a7d0b75992dc46d40671d15bf1ec8d328ca95d1",
    "manifest.json": MANIFEST_SHA256,
    "preflight.json": "25820e48cbadba4b591d8e9e60c416bcf38eec96196421507c82f3e0d9ffc145",
    "protocol_status.json": "9e25cfbfdb553cfa94bb0f17f0123a40544951a308b81350be10a57ef71d04cd",
    "reset.json": "526fc6c2dc04ebd19b705650b54069d771282fba3bed6268c64ff4d8f101dc94",
    "reset_audit.json": "a8c8be85aee67d4e2231146b3de369e7e892637307cbe12d4bf4d28e29e3aade",
    "session.json": "3c978d47dbfc0ab6d12fef535577c7399b773ec358dba2fd968bdda01ff1e681",
    "session_dc3e3ade-e4f.jsonl": "3ee5f34cc307bedca43f49ed13dda004145ca893882d5a7e4f0fa568edb7fcde",
    "session_dc3e3ade-e4f_summary.json": "80797219885968fa8826fb0dab256146ea2dbb738465414cdc6735e76792d53b",
    "verification.json": "c9c977d7469b84376ec2f225abfb99bb5a86bb8e5bb6f72f20d0a6107e7800b5",
}


def _load(name: str):
    return json.loads((RUN_DIR / name).read_text(encoding="utf-8"))


def _event_data(event_type: str) -> list[dict]:
    return [
        event["data"]
        for event in _load("session.json")
        if event.get("type") == event_type
    ]


def test_phase143_authorization_and_all_retained_payload_hashes_are_bound() -> None:
    manifest = _load("manifest.json")
    authorization = _load("authorization.json")
    consumption = _load("authorization_consumption.json")

    assert manifest["episode_id"] == RUN_ID
    assert manifest["session_id"] == "dc3e3ade-e4f"
    assert manifest["authorization_id"] == (
        "89d7546714ee12d40ab1a1eee30dcfadf1a61e8b0e270ba6c12cc2f2e42f94cb"
    )
    assert manifest["passed"] is False
    assert manifest["evidence_eligible"] is False
    assert manifest["single_episode"] is True
    assert manifest["automatic_retry_allowed"] is False
    assert manifest["bm012_terminal_started"] is False
    assert authorization["authorization_predecessor"] == (
        "6bd489f2af2bb9756bc5546735559d77c667453e"
    )
    assert consumption["authorization_commit"] == (
        "5b82e7bbdc676dae5918cf99b0c6410f4468c3ce"
    )
    assert consumption["consumed_by"] == "fresh_sp003_process_start"
    assert consumption["single_episode"] is True
    assert consumption["automatic_retry_allowed"] is False

    assert set(FILE_HASHES) == {path.name for path in RUN_DIR.iterdir()}
    for name, expected in FILE_HASHES.items():
        assert hashlib.sha256((RUN_DIR / name).read_bytes()).hexdigest() == expected
    assert len(manifest["files"]) == 12
    for record in manifest["files"]:
        assert FILE_HASHES[Path(record["path"]).name] == record["sha256"]


def test_phase143_retains_the_step_up_target_compaction_failure() -> None:
    episode = _load("episode.json")
    verification = _load("verification.json")
    planner_calls = _event_data("llm_planner_call")
    plans = _event_data("plan")
    actions = _event_data("action")
    observations = _event_data("observation")
    pre_dispatch = _event_data("stone_pickaxe_sp003_pre_dispatch_replan")

    assert len(planner_calls) == len(plans) == 23
    assert len(actions) == 22
    assert all(call["real_llm_call"] is True for call in planner_calls)
    assert all(call["schema_valid"] is True for call in planner_calls)
    assert all(
        call["transport_evidence"]["attempt_count"] == 1
        and call["transport_evidence"]["retry_count"] == 0
        for call in planner_calls
    )
    assert sum(call["provider_metadata"]["duration_ms"] for call in planner_calls) == (
        62400
    )

    step_up_observation = next(
        observation
        for observation in observations
        if observation.get("sp003_targets")
        and observation["sp003_targets"][0].get(
            "stone_clearance_shaft_step_up_egress"
        )
        is True
    )
    target = step_up_observation["sp003_targets"][0]
    assert target["source_id"] == (
        "sp003_clearance_shaft_step_up_egress:120:141:-37"
    )
    assert target["navigation_only"] is True
    assert target["stone_clearance_shaft_step_up_egress"] is True
    assert target["stand_position"] == {"x": 120.5, "y": 141, "z": -36.5}

    divergent_call = planner_calls[13]
    divergent_plan = plans[13]
    divergent_action = actions[12]
    assert divergent_call["call_id"] == "llm-47b868e32e5d4372"
    assert divergent_call["response_sha256"] == (
        "2de820729335b6824dbe5fa2f26873f6eaba61199350fdb17e422c44310f4e96"
    )
    assert "first target has all booleans false" in divergent_plan["reasoning"]
    assert divergent_plan["actions"] == [
        {
            "type": "place",
            "parameters": {
                "item": "crafting_table",
                "x": 120.5,
                "y": 141,
                "z": -36.5,
            },
        }
    ]
    guard = divergent_action["result"]["action_verification"]["guard"]
    assert guard["policy_id"] == (
        "sp003-partial-clearance-shaft-step-up-egress-v1"
    )
    assert guard["issues"] == [
        "sp003_partial_shaft_step_up_navigation_required",
        "sp003_partial_shaft_step_up_parameters_unexpected",
    ]
    assert divergent_action["result"]["success"] is False
    assert divergent_action["result"]["duration_ms"] == 0
    assert divergent_action["result"]["verification_blocked"] is True

    step_up_rejections = actions[12:]
    assert len(step_up_rejections) == 10
    assert all(
        "sp003_partial_shaft_step_up_" in action["result"]["error"]
        and action["result"]["duration_ms"] == 0
        and action["pre_observation"]["position"]
        == action["post_observation"]["position"]
        and action["pre_observation"]["inventory"]
        == action["post_observation"]["inventory"]
        for action in step_up_rejections
    )
    assert len(pre_dispatch) == 1
    assert pre_dispatch[0]["granted"] is True
    assert pre_dispatch[0]["guard"]["issues"] == [
        "sp003_exact_one_table_craft_required"
    ]

    progress = episode["stable_observation"]["sp003_progress"]
    assert progress["log_source_removal_count"] == 3
    assert progress["plank_craft_count"] == 1
    assert progress["stick_craft_count"] == 1
    assert progress["crafting_table_craft_count"] == 1
    assert progress["crafting_table_place_count"] == 0
    assert progress["surface_clearance_removal_count"] == 2
    assert progress["wooden_pickaxe_craft_count"] == 0
    assert progress["stone_source_removal_count"] == 0
    assert progress["stone_pickaxe_craft_count"] == 0
    assert len(episode["raw_action_failures"]) == 12
    assert episode["reconciled_action_failure_indexes"] == [2]
    assert len(episode["unreconciled_action_failures"]) == 11
    assert episode["goal_result"]["completed"] is False
    assert episode["goal_result"]["termination_reason"] == "max_duration"
    assert episode["goal_result"]["elapsed_s"] == 329.829
    assert verification["criteria"]["one_table_place"] is False
    assert verification["criteria"]["terminal_stone_pickaxe"] is False
    assert verification["criteria"]["no_retry"] is True
    assert verification["criteria"]["no_capability_credit"] is True
    assert verification["criteria"]["no_m4_credit"] is True


def test_phase143_ledger_holds_live_gate_for_phase144_offline_repair() -> None:
    ledger = json.loads(
        (REPO / "workspace/evals/stone_pickaxe_failure_ledger.json").read_text(
            encoding="utf-8"
        )
    )
    failure = next(
        item
        for item in ledger["failures"]
        if item["id"] == "sp003-baseline-033-step-up-target-compaction-gap"
    )
    gate = ledger["next_required_gate"]

    assert failure["episode_id"] == RUN_ID
    assert failure["manifest_sha256"] == MANIFEST_SHA256
    assert failure["authorization_consumed"] is True
    assert failure["authorization_reuse_allowed"] is False
    assert failure["automatic_retry_attempted"] is False
    assert failure["counts_toward_baseline_success"] is False
    assert failure["counts_toward_skill_gate"] is False
    assert failure["counts_toward_capability"] is False
    assert failure["counts_toward_m4"] is False
    assert len(failure["evidence"]) == 13
    for record in failure["evidence"]:
        path = REPO / record["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]

    assert gate["id"] == (
        "sp003_phase_144_offline_repair_commit_push_then_phase_145_bounded_no_minecraft_step_up_provider_probe"
    )
    assert gate["authorization"] is False
    assert gate["live_episode_limit"] == 0
    assert gate["normal_runtime_permission"] is False
    assert gate["automatic_retry_allowed"] is False
    assert ledger["live_authorization"] is False
