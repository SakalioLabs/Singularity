"""Offline BM-012 task-contract, machine-verifier, and eligibility tests."""

import copy
import json
import os
import shutil
import sys
import tempfile
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from singularity.core.agent import Agent
from singularity.evaluation.capability_evidence import build_capability_evidence_report
from singularity.evaluation.m4_protocol import (
    BM012_CONTRACT,
    BM012_CONTRACT_SHA256,
    PROTOCOL,
    PROTOCOL_SHA256,
    canonical_sha256,
    evaluate_bm012_episode,
    task_contract_integrity_report,
)
from singularity.evaluation.m4_runtime import (
    attach_m4_evidence_hashes,
    build_m4_episode_progress_report,
)


EPISODE_ID = "m4-bm012-fixture-episode"
LEVEL_NAME = f"{EPISODE_ID}_bm012"


def _lifecycle(death_count=0, respawn_count=0):
    return {
        "type": "m4_player_lifecycle",
        "schema_version": 1,
        "verifier_id": PROTOCOL["identities"]["player_lifecycle_verifier"],
        "source": "mineflayer_events",
        "profile": PROTOCOL["profile"],
        "protocol_sha256": PROTOCOL_SHA256,
        "tracker_id": "bm012-fixture-tracker",
        "episode_id": EPISODE_ID,
        "level_name": LEVEL_NAME,
        "baseline_id": "b" * 64,
        "baseline_established": True,
        "initial_spawn_observed": True,
        "baseline_death_count_total": 0,
        "baseline_respawn_count_total": 0,
        "baseline_spawn_count_total": 1,
        "baseline_observed_at_ms": 1700000000000,
        "baseline_bridge_monotonic_ms": 1000,
        "death_count_total": death_count,
        "respawn_count_total": respawn_count,
        "spawn_count_total": 1 + respawn_count,
        "death_count": death_count,
        "respawn_count": respawn_count,
        "spawn_count": respawn_count,
        "pending_respawn_count": max(0, death_count - respawn_count),
        "uninterrupted": death_count == 0 and respawn_count == 0,
        "last_death": None,
        "last_respawn": None,
    }


def _state(raw_iron, time_of_day):
    return {
        "time_of_day": time_of_day,
        "health": 20,
        "hunger": 18,
        "inventory": {"raw_iron": raw_iron} if raw_iron else {},
        "position": {"x": 4, "y": 20, "z": 8},
        "player_lifecycle": _lifecycle(),
    }


def _preflight():
    return {
        "type": "m4_preflight",
        "passed": True,
        "task_id": "BM-012",
        "profile": PROTOCOL["profile"],
        "protocol_sha256": PROTOCOL_SHA256,
        "server_jar_sha256": PROTOCOL["server_jar_sha256"],
        "world_seed": PROTOCOL["world_seed"],
        "fresh_episode": True,
        "game_mode": PROTOCOL["game_mode"],
        "difficulty": PROTOCOL["difficulty"],
        "initial_inventory": {},
        "initial_player_state": dict(PROTOCOL["initial_player_state"]),
        "initial_time_of_day": BM012_CONTRACT["initial_time_of_day"],
        "weather": PROTOCOL["weather"],
        "gamerules": dict(PROTOCOL["gamerules"]),
        "runtime_versions": dict(PROTOCOL["runtime_versions"]),
        "llm": dict(PROTOCOL["llm"]),
        "identities": dict(PROTOCOL["identities"]),
        "runtime_controls": dict(PROTOCOL["baseline_runtime_controls"]),
        "task_contract_id": BM012_CONTRACT["id"],
        "task_contract_sha256": BM012_CONTRACT_SHA256,
        "player_lifecycle_baseline": _lifecycle(),
        "source_checks": {
            "protocol_status_bound": True,
            "reset_bound": True,
            "task_contract_bound": True,
        },
        "episode_id": EPISODE_ID,
        "level_name": LEVEL_NAME,
    }


def _manifest():
    return {
        "type": "m4_runtime_manifest",
        "task_id": "BM-012",
        "profile": PROTOCOL["profile"],
        "protocol_sha256": PROTOCOL_SHA256,
        "reset_protocol_sha256": PROTOCOL["reset_protocol_sha256"],
        "validation_protocol_sha256": PROTOCOL["validation_protocol_sha256"],
        "deadline_policy_id": PROTOCOL["deadline_policy"]["id"],
        "task_contract_id": BM012_CONTRACT["id"],
        "task_contract_sha256": BM012_CONTRACT_SHA256,
        "episode_id": EPISODE_ID,
        "session_id": "m4-bm012-fixture-session",
        "level_name": LEVEL_NAME,
        "episode_started_monotonic": 100.0,
        "episode_deadline_monotonic": 700.0,
        "episode_ended_monotonic": 116.0,
        "runtime_controls": dict(PROTOCOL["baseline_runtime_controls"]),
        "runtime_limits": {
            "max_duration_s": 600,
            "max_goals": 24,
            "max_cycles_per_goal": 40,
        },
    }


def _planner_call():
    return {
        "type": "llm_planner_call",
        "monotonic_s": 102.5,
        "data": {
            "call_id": "bm012-fixture-planner",
            "real_llm_call": True,
            "schema_valid": True,
            "provider_metadata": {
                "extra_body": copy.deepcopy(PROTOCOL["llm"]["extra_body"]),
                "finish_reason": "stop",
                "reasoning_content_byte_count": 0,
                "duration_ms": 500,
                "total_tokens": 256,
            },
        },
    }


def _events():
    events = [
        {
            "type": "autonomous_start",
            "monotonic_s": 100.0,
            "data": {
                "mode": "autonomous",
                "task_id": "BM-012",
                "task_contract_id": BM012_CONTRACT["id"],
                "task_contract_sha256": BM012_CONTRACT_SHA256,
            },
        },
        {"type": "m4_player_lifecycle", "monotonic_s": 100.1, "data": _lifecycle()},
        {"type": "observation", "monotonic_s": 101.0, "data": _state(0, 0)},
        {
            "type": "auto_goal",
            "monotonic_s": 102.0,
            "data": {
                "goal": "Collect 8 raw iron from iron ore with the stone pickaxe",
                "selection_source": "goal_generator",
                "selection_reason": "bm012_stone_pickaxe_ready_for_iron",
                "priority": 6,
                "priority_class": "tool_resource_progression",
            },
        },
        _planner_call(),
        {
            "type": "plan",
            "monotonic_s": 102.75,
            "data": {"status": "planning", "actions": [{"type": "dig"}]},
        },
    ]
    for index in range(8):
        before = _state(index, 20 + index * 10)
        after = _state(index + 1, 30 + index * 10)
        events.append({
            "type": "action",
            "monotonic_s": 103.0 + index,
            "data": {
                "action": {
                    "type": "dig",
                    "parameters": {"x": index, "y": 20, "z": 8, "block": "iron_ore"},
                },
                "result": {
                    "success": True,
                    "block_removed": True,
                    "target_block_before": {
                        "name": "iron_ore",
                        "position": {"x": index, "y": 20, "z": 8},
                    },
                    "target_block_after": {
                        "name": "air",
                        "position": {"x": index, "y": 20, "z": 8},
                    },
                    "action_verification": {"decision": "allow", "confidence": 1.0},
                },
                "pre_observation": before,
                "post_observation": after,
            },
        })
    terminal_state = _state(8, 200)
    events.extend([
        {"type": "observation", "monotonic_s": 112.0, "data": terminal_state},
        {
            "type": "terminal_resource_verification",
            "monotonic_s": 113.0,
            "data": {
                "type": "m4_terminal_resource_verification",
                "schema_version": 1,
                "passed": True,
                "source": "machine_state",
                "task_id": "BM-012",
                "goal": "Collect 8 raw iron from iron ore with the stone pickaxe",
                "verifier_id": BM012_CONTRACT["terminal_verifier"]["id"],
                "task_contract_id": BM012_CONTRACT["id"],
                "task_contract_sha256": BM012_CONTRACT_SHA256,
                "qualifying_item": "raw_iron",
                "required_count": 8,
                "observed_count": 8,
                "inventory": {"raw_iron": 8},
                "health": 20,
                "food": 18,
                "bot_connected": True,
                "uninterrupted_survival": True,
                "player_lifecycle_verifier_id": PROTOCOL["identities"]["player_lifecycle_verifier"],
                "player_lifecycle": _lifecycle(),
            },
        },
        {"type": "goal_end", "monotonic_s": 114.0, "data": {"completed": True}},
        {"type": "autonomous_end", "monotonic_s": 115.0, "data": {"completed": True}},
    ])
    return events


def _result(events):
    result = {
        "type": "m4_episode_result",
        "schema_version": 1,
        "task_id": "BM-012",
        "profile": PROTOCOL["profile"],
        "completed": True,
        "termination_reason": "terminal_task_verified",
        "elapsed_s": 15.0,
        "deadline_eligible": True,
        "external_step_script": False,
        "terminal_state": {
            **_state(8, 200),
            "bot_connected": True,
        },
    }
    return attach_m4_evidence_hashes(result, _preflight(), _manifest(), events)


def _rehash(result, events, preflight=None, manifest=None):
    payload = dict(result)
    payload.pop("evidence_hashes", None)
    return attach_m4_evidence_hashes(
        payload,
        preflight or _preflight(),
        manifest or _manifest(),
        events,
    )


def test_bm012_contract_and_independent_eligibility_accept_machine_provenance():
    integrity = task_contract_integrity_report("BM-012")
    assert integrity["passed"], integrity
    events = _events()
    result = _result(events)
    eligibility = evaluate_bm012_episode(events, result, _preflight(), _manifest())
    assert eligibility["eligible"], eligibility
    resource = eligibility["evidence"]["resource_acquisition"]
    assert resource["initial_target_count"] == 0
    assert resource["terminal_target_passed"] is True
    assert resource["successful_source_action_count"] == 8
    assert resource["positive_inventory_delta"]["raw_iron"] == 8
    progress = build_m4_episode_progress_report(events, result, _preflight(), _manifest(), eligibility)
    assert progress["task_id"] == "BM-012"
    assert progress["progress_gate_passed"] is True
    assert progress["counts_toward_task_success"] is True
    print("PASS: BM-012 accepts task-bound machine inventory and eight observed iron-source digs")


def test_bm012_eligibility_rejects_preload_missing_source_actions_and_text_only_completion():
    events = _events()
    events[2]["data"]["inventory"] = {"raw_iron": 8}
    result = _rehash(_result(_events()), events)
    preload = evaluate_bm012_episode(events, result, _preflight(), _manifest())
    assert not preload["eligible"]
    assert "resource_initial_inventory_empty" in preload["issues"]

    events = _events()
    action_indexes = [index for index, event in enumerate(events) if event.get("type") == "action"]
    del events[action_indexes[-1]]
    result = _rehash(_result(_events()), events)
    missing_source = evaluate_bm012_episode(events, result, _preflight(), _manifest())
    assert not missing_source["eligible"]
    assert "resource_successful_source_actions" in missing_source["issues"]

    events = [event for event in _events() if event.get("type") != "terminal_resource_verification"]
    result = _rehash(_result(_events()), events)
    text_only = evaluate_bm012_episode(events, result, _preflight(), _manifest())
    assert not text_only["eligible"]
    assert "event:terminal_resource_verification" in text_only["issues"]
    assert "terminal_machine_verification" in text_only["issues"]
    print("PASS: BM-012 rejects preloaded, under-provenanced, and text-only completion claims")


def test_bm012_eligibility_rejects_contract_limit_and_deadline_drift():
    events = _events()
    preflight = _preflight()
    preflight["task_contract_sha256"] = "0" * 64
    result = _rehash(_result(events), events, preflight=preflight)
    drifted_contract = evaluate_bm012_episode(events, result, preflight, _manifest())
    assert not drifted_contract["eligible"]
    assert "preflight_eligible" in drifted_contract["issues"]

    manifest = _manifest()
    manifest["runtime_limits"]["max_duration_s"] = 601
    result = _rehash(_result(events), events, manifest=manifest)
    drifted_limit = evaluate_bm012_episode(events, result, _preflight(), manifest)
    assert not drifted_limit["eligible"]
    assert "manifest_runtime_limits" in drifted_limit["issues"]

    manifest = _manifest()
    manifest["episode_ended_monotonic"] = 701.0
    result = _rehash(_result(events), events, manifest=manifest)
    deadline = evaluate_bm012_episode(events, result, _preflight(), manifest)
    assert not deadline["eligible"]
    assert "episode_within_deadline" in deadline["issues"]
    print("PASS: BM-012 rejects task-contract, runtime-limit, and absolute-deadline drift")


def test_agent_bm012_terminal_verifier_requires_task_lifecycle_and_machine_inventory():
    lifecycle = _lifecycle()
    agent = object.__new__(Agent)
    agent.config = SimpleNamespace(planner_protocol="m4-fixed-v1")
    agent._m4_task_id = "BM-012"
    agent._m4_player_lifecycle_identity = Agent._m4_lifecycle_identity(lifecycle)
    agent.bot = SimpleNamespace(
        _connected=True,
        get_player_lifecycle=lambda: copy.deepcopy(lifecycle),
    )
    observation = _state(8, 200)
    verification = agent._m4_terminal_resource_verification(
        "Collect 8 raw iron from iron ore with the stone pickaxe",
        observation,
    )
    assert verification["passed"] is True
    assert verification["observed_count"] == 8
    assert verification["task_contract_sha256"] == BM012_CONTRACT_SHA256

    assert not agent._m4_terminal_resource_verification("Collect iron", _state(7, 200))
    agent._m4_task_id = "BM-011"
    assert not agent._m4_terminal_resource_verification("Collect iron", observation)
    agent._m4_task_id = "BM-012"
    dead = _lifecycle(death_count=1)
    agent.bot.get_player_lifecycle = lambda: dead
    assert not agent._m4_terminal_resource_verification("Collect iron", observation)
    print("PASS: Agent terminalizes BM-012 only from bound live inventory and lifecycle state")


def test_capability_adapter_rechecks_complete_bm012_bundle():
    directory = tempfile.mkdtemp(prefix="m4-bm012-capability-", dir=".")
    try:
        events = _events()
        preflight = _preflight()
        manifest = _manifest()
        result = _result(events)
        eligibility = evaluate_bm012_episode(events, result, preflight, manifest)
        payloads = {
            "preflight.json": preflight,
            "manifest.json": manifest,
            "session.json": events,
            "result.json": result,
            "eligibility.json": eligibility,
        }
        for name, payload in payloads.items():
            with open(os.path.join(directory, name), "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2)
        eligibility_path = os.path.join(directory, "eligibility.json")
        report = build_capability_evidence_report(
            benchmark_result_paths=[eligibility_path],
            status_path="workspace/STATUS.md",
        )
        m4 = next(phase for phase in report["phases"] if phase["id"] == "M4")
        bm012 = next(task for task in m4["benchmarks"] if task["task_id"] == "BM-012")
        assert bm012["attempts"] == 1
        assert bm012["successes"] == 1
        assert bm012["ineligible_successes"] == 0
    finally:
        shutil.rmtree(directory)
    print("PASS: capability adapter independently rechecks a complete BM-012 bundle")


if __name__ == "__main__":
    test_bm012_contract_and_independent_eligibility_accept_machine_provenance()
    test_bm012_eligibility_rejects_preload_missing_source_actions_and_text_only_completion()
    test_bm012_eligibility_rejects_contract_limit_and_deadline_drift()
    test_agent_bm012_terminal_verifier_requires_task_lifecycle_and_machine_inventory()
    test_capability_adapter_rechecks_complete_bm012_bundle()
    print("\nM4 BM-012 resource tests PASSED")
