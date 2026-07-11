"""Offline tests for M4 runtime evidence and G2 preparation diagnostics."""

import copy
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from singularity.evaluation.m4_protocol import PROTOCOL, PROTOCOL_SHA256
from singularity.evaluation.m4_runtime import (
    attach_m4_evidence_hashes,
    build_m4_preflight,
    build_m4_preparation_report,
    build_m4_runtime_manifest,
)


def _status():
    return {
        "success": True,
        "configured": True,
        "profile": PROTOCOL["profile"],
        "protocol_sha256": PROTOCOL_SHA256,
        "server_jar_sha256": PROTOCOL["server_jar_sha256"],
        "seed": PROTOCOL["world_seed"],
        "episode_id": "m4-fixture-episode",
        "level_name": "m4-fixture-episode_bm011",
        "runtime_versions": {"node": PROTOCOL["runtime_versions"]["node"]},
        "llm": dict(PROTOCOL["llm"]),
        "runtime_controls": dict(PROTOCOL["baseline_runtime_controls"]),
        "agent_id": PROTOCOL["identities"]["agent"],
        "goal_generator_id": PROTOCOL["identities"]["goal_generator"],
        "curriculum_id": PROTOCOL["identities"]["curriculum"],
        "planner_id": PROTOCOL["identities"]["planner"],
        "action_backend_id": PROTOCOL["identities"]["action_backend"],
        "verifier_id": PROTOCOL["identities"]["goal_verifier"],
        "runtime_interrupt_id": PROTOCOL["identities"]["runtime_interrupt"],
        "skill_runtime_profile_id": PROTOCOL["identities"]["skill_runtime_profile"],
        "dependencies": {
            "mineflayer": PROTOCOL["runtime_versions"]["mineflayer"],
            "mineflayer-pathfinder": PROTOCOL["runtime_versions"]["mineflayer_pathfinder"],
            "minecraft-data": PROTOCOL["runtime_versions"]["minecraft_data"],
        },
    }


def _reset():
    return {
        "success": True,
        "profile": PROTOCOL["profile"],
        "protocol_sha256": PROTOCOL_SHA256,
        "reset_protocol_sha256": PROTOCOL["reset_protocol_sha256"],
        "validation_protocol_sha256": PROTOCOL["validation_protocol_sha256"],
        "task_id": "BM-011",
        "episode_id": "m4-fixture-episode",
        "level_name": "m4-fixture-episode_bm011",
        "seed": PROTOCOL["world_seed"],
        "server_jar_sha256": PROTOCOL["server_jar_sha256"],
        "gamerules": dict(PROTOCOL["gamerules"]),
        "checks": {"inventory_exact": True, "position_at_spawn": True},
        "after_state": {
            "game_mode": PROTOCOL["game_mode"],
            "difficulty": PROTOCOL["difficulty"],
            "inventory": {},
            "health": 20,
            "food": 20,
            "food_saturation": 5,
            "time_of_day": 9000,
            "weather": "clear",
        },
    }


def _events():
    before = {
        "position": {"x": 0, "y": 64, "z": 0},
        "health": 20,
        "hunger": 20,
        "inventory": {},
        "time_of_day": 9000,
        "nearby_entities": [],
    }
    after = {
        **before,
        "position": {"x": 2, "y": 64, "z": 0},
        "inventory": {"oak_log": 1},
        "time_of_day": 9100,
    }
    return [
        {"type": "autonomous_start", "monotonic_s": 100.0, "data": {}},
        {"type": "observation", "monotonic_s": 101.0, "data": before},
        {
            "type": "auto_goal",
            "monotonic_s": 102.0,
            "data": {
                "goal": "Gather 6 oak logs for tools and shelter",
                "selection_source": "goal_generator",
                "selection_reason": "wood_reserve_below_target",
                "priority": 6,
            },
        },
        {
            "type": "plan",
            "monotonic_s": 103.0,
            "data": {"status": "planning", "actions": [{"type": "dig"}]},
        },
        {
            "type": "action",
            "monotonic_s": 104.0,
            "data": {
                "action": {"type": "dig", "parameters": {"block": "oak_log"}},
                "result": {"success": True},
                "pre_observation": before,
                "post_observation": after,
            },
        },
        {"type": "observation", "monotonic_s": 105.0, "data": after},
        {"type": "goal_end", "monotonic_s": 106.0, "data": {"success": False}},
        {"type": "autonomous_end", "monotonic_s": 107.0, "data": {}},
    ]


def test_m4_runtime_builds_valid_preflight_and_manifest():
    preflight = build_m4_preflight(
        _status(),
        _reset(),
        "m4-fixture-episode",
        "m4-fixture-episode_bm011",
        fresh_episode=True,
    )
    assert preflight["passed"], preflight
    assert preflight["llm"] == PROTOCOL["llm"]
    assert preflight["initial_player_state"]["saturation"] == 5

    manifest = build_m4_runtime_manifest(
        preflight,
        "m4-fixture-session",
        100.0,
        1300.0,
        108.0,
        {"session": "logs/benchmarks/m4/fixture/session.jsonl"},
        dict(PROTOCOL["baseline_runtime_controls"]),
        {"max_duration_s": 1200, "max_goals": 24, "max_cycles_per_goal": 40},
    )
    assert manifest["protocol_sha256"] == PROTOCOL_SHA256
    assert manifest["skill_execution_mode"] == "off"
    assert manifest["vision_enabled"] is False

    reused = build_m4_preflight(
        _status(),
        _reset(),
        "m4-fixture-episode",
        "m4-fixture-episode_bm011",
        fresh_episode=False,
    )
    assert reused["passed"] is False

    drifted_status = _status()
    drifted_status["episode_id"] = "different-episode"
    drifted = build_m4_preflight(
        drifted_status,
        _reset(),
        "m4-fixture-episode",
        "m4-fixture-episode_bm011",
        fresh_episode=True,
    )
    assert drifted["passed"] is False
    assert drifted["source_checks"]["status_episode"] is False
    print("PASS: M4 runtime builds a valid fresh preflight and fixed manifest")


def test_m4_preparation_report_requires_machine_visible_progress():
    preflight = build_m4_preflight(
        _status(),
        _reset(),
        "m4-fixture-episode",
        "m4-fixture-episode_bm011",
        fresh_episode=True,
    )
    manifest = build_m4_runtime_manifest(
        preflight,
        "m4-fixture-session",
        100.0,
        1300.0,
        108.0,
        runtime_controls=dict(PROTOCOL["baseline_runtime_controls"]),
        runtime_limits={"max_duration_s": 1200, "max_goals": 24, "max_cycles_per_goal": 40},
    )
    result = attach_m4_evidence_hashes(
        {
            "completed": False,
            "termination_reason": "preparation_probe_complete",
            "elapsed_s": 8.0,
            "deadline_eligible": True,
            "terminal_state": {"health": 20, "bot_connected": True},
        },
        preflight,
        manifest,
        _events(),
    )
    preparation = build_m4_preparation_report(
        _events(),
        result,
        preflight,
        manifest,
        {"eligible": False, "issues": ["next_dawn_observed"]},
    )

    assert preparation["g2_passed"] is True
    assert preparation["counts_toward_bm011_success"] is False
    assert preparation["inventory_delta"] == {"oak_log": 1}
    assert preparation["machine_visible_progress"] is True
    assert preparation["same_goal_max_consecutive"] == 1
    assert preparation["first_unrecovered_transition"] == {}
    print("PASS: G2 diagnostics separate preparation progress from BM-011 eligibility")


def test_m4_preparation_requires_progress_before_fixed_dusk_boundary():
    events = copy.deepcopy(_events())
    for event in events:
        data = event.get("data", {})
        if event.get("type") == "observation" and data.get("time_of_day") == 9100:
            data["time_of_day"] = 10100
        if event.get("type") == "action" and isinstance(data.get("post_observation"), dict):
            data["post_observation"]["time_of_day"] = 10100
    preflight = build_m4_preflight(
        _status(),
        _reset(),
        "m4-fixture-episode",
        "m4-fixture-episode_bm011",
        fresh_episode=True,
    )
    manifest = build_m4_runtime_manifest(
        preflight,
        "m4-fixture-session",
        100.0,
        1300.0,
        108.0,
        runtime_controls=dict(PROTOCOL["baseline_runtime_controls"]),
    )
    result = {
        "deadline_eligible": True,
        "terminal_state": copy.deepcopy(events[-2]["data"]),
    }
    report = build_m4_preparation_report(events, result, preflight, manifest, {"eligible": False, "issues": []})
    assert report["machine_visible_progress"] is True
    assert report["pre_dusk_machine_visible_progress"] is False
    assert report["g2_passed"] is False
    print("PASS: G2 rejects progress that first appears after the fixed dusk boundary")


def test_m4_preparation_skips_recovered_action_failure():
    events = copy.deepcopy(_events())
    failed = copy.deepcopy(events[4])
    failed["monotonic_s"] = 103.5
    failed["data"]["result"] = {"success": False, "error": "temporary target miss"}
    failed["data"]["post_observation"] = copy.deepcopy(failed["data"]["pre_observation"])
    events.insert(4, failed)
    preflight = build_m4_preflight(
        _status(),
        _reset(),
        "m4-fixture-episode",
        "m4-fixture-episode_bm011",
        fresh_episode=True,
    )
    manifest = build_m4_runtime_manifest(
        preflight,
        "m4-fixture-session",
        100.0,
        1300.0,
        108.0,
        runtime_controls=dict(PROTOCOL["baseline_runtime_controls"]),
    )
    report = build_m4_preparation_report(
        events,
        {"deadline_eligible": True, "terminal_state": events[-2]["data"]},
        preflight,
        manifest,
        {"eligible": False, "issues": []},
    )
    assert report["first_unrecovered_transition"] == {}
    print("PASS: G2 does not mislabel a later-recovered action failure")


if __name__ == "__main__":
    test_m4_runtime_builds_valid_preflight_and_manifest()
    test_m4_preparation_report_requires_machine_visible_progress()
    test_m4_preparation_requires_progress_before_fixed_dusk_boundary()
    test_m4_preparation_skips_recovered_action_failure()
    print("\nM4 runtime evidence tests PASSED")
