"""Offline BM-013/BM-014 contract, provenance, progress, and loader tests."""

import copy
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from singularity.evaluation.capability_evidence import build_capability_evidence_report
from singularity.evaluation.m4_protocol import (
    PROTOCOL,
    PROTOCOL_SHA256,
    evaluate_m4_episode,
    evaluate_m4_episode_for_protocol_hash,
    supported_protocol_sha256s,
    task_contract,
    task_contract_integrity_report,
    task_contract_sha256,
    task_spec,
)
from singularity.evaluation.m4_runtime import (
    attach_m4_evidence_hashes,
    build_m4_episode_progress_report,
)


TASK_IDS = ("BM-013", "BM-014")


def _identity(task_id):
    suffix = task_id.lower().replace("-", "")
    return f"m4-{suffix}-fixture-episode", f"m4-{suffix}-fixture-episode_{suffix}"


def _lifecycle(task_id):
    episode_id, level_name = _identity(task_id)
    return {
        "type": "m4_player_lifecycle",
        "schema_version": 1,
        "verifier_id": PROTOCOL["identities"]["player_lifecycle_verifier"],
        "source": "mineflayer_events",
        "profile": PROTOCOL["profile"],
        "protocol_sha256": PROTOCOL_SHA256,
        "tracker_id": f"{task_id.lower()}-fixture-tracker",
        "episode_id": episode_id,
        "level_name": level_name,
        "baseline_id": "c" * 64,
        "baseline_established": True,
        "initial_spawn_observed": True,
        "baseline_death_count_total": 0,
        "baseline_respawn_count_total": 0,
        "baseline_spawn_count_total": 1,
        "baseline_observed_at_ms": 1700000000000,
        "baseline_bridge_monotonic_ms": 1000,
        "death_count_total": 0,
        "respawn_count_total": 0,
        "spawn_count_total": 1,
        "death_count": 0,
        "respawn_count": 0,
        "spawn_count": 0,
        "pending_respawn_count": 0,
        "uninterrupted": True,
        "last_death": None,
        "last_respawn": None,
    }


def _state(task_id, inventory, time_of_day):
    return {
        "time_of_day": time_of_day,
        "health": 20,
        "hunger": 18,
        "inventory": dict(inventory),
        "position": {"x": 4, "y": 64, "z": 8},
        "player_lifecycle": _lifecycle(task_id),
    }


def _preflight(task_id):
    episode_id, level_name = _identity(task_id)
    contract = task_contract(task_id)
    return {
        "type": "m4_preflight",
        "passed": True,
        "task_id": task_id,
        "profile": PROTOCOL["profile"],
        "protocol_sha256": PROTOCOL_SHA256,
        "server_jar_sha256": PROTOCOL["server_jar_sha256"],
        "world_seed": PROTOCOL["world_seed"],
        "fresh_episode": True,
        "game_mode": PROTOCOL["game_mode"],
        "difficulty": PROTOCOL["difficulty"],
        "initial_inventory": {},
        "initial_player_state": dict(PROTOCOL["initial_player_state"]),
        "initial_time_of_day": contract["initial_time_of_day"],
        "weather": PROTOCOL["weather"],
        "gamerules": dict(PROTOCOL["gamerules"]),
        "runtime_versions": dict(PROTOCOL["runtime_versions"]),
        "llm": copy.deepcopy(PROTOCOL["llm"]),
        "identities": dict(PROTOCOL["identities"]),
        "runtime_controls": dict(PROTOCOL["baseline_runtime_controls"]),
        "task_contract_id": contract["id"],
        "task_contract_sha256": task_contract_sha256(task_id),
        "player_lifecycle_baseline": _lifecycle(task_id),
        "source_checks": {
            "protocol_status_bound": True,
            "reset_bound": True,
            "task_contract_bound": True,
        },
        "episode_id": episode_id,
        "level_name": level_name,
    }


def _manifest(task_id):
    episode_id, level_name = _identity(task_id)
    task = task_spec(task_id)
    contract = task_contract(task_id)
    return {
        "type": "m4_runtime_manifest",
        "task_id": task_id,
        "profile": PROTOCOL["profile"],
        "protocol_sha256": PROTOCOL_SHA256,
        "reset_protocol_sha256": PROTOCOL["reset_protocol_sha256"],
        "validation_protocol_sha256": PROTOCOL["validation_protocol_sha256"],
        "deadline_policy_id": PROTOCOL["deadline_policy"]["id"],
        "task_contract_id": contract["id"],
        "task_contract_sha256": task_contract_sha256(task_id),
        "episode_id": episode_id,
        "session_id": f"{task_id.lower()}-fixture-session",
        "level_name": level_name,
        "episode_started_monotonic": 100.0,
        "episode_deadline_monotonic": 100.0 + float(task["max_duration_s"]),
        "episode_ended_monotonic": 112.0,
        "runtime_controls": dict(PROTOCOL["baseline_runtime_controls"]),
        "runtime_limits": {
            "max_duration_s": task["max_duration_s"],
            "max_goals": PROTOCOL["limits"]["max_autonomous_goals"],
            "max_cycles_per_goal": PROTOCOL["limits"]["max_cycles_per_goal"],
        },
    }


def _planner_call(task_id):
    return {
        "type": "llm_planner_call",
        "monotonic_s": 102.5,
        "data": {
            "call_id": f"{task_id.lower()}-fixture-planner",
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


def _action_fixture(task_id):
    if task_id == "BM-013":
        return (
            {
                "type": "smelt",
                "parameters": {
                    "item": "iron_ingot",
                    "input": "raw_iron",
                    "fuel": "coal",
                    "count": 1,
                },
            },
            {"raw_iron": 1, "coal": 1},
            {"iron_ingot": 1},
        )
    return (
        {
            "type": "craft",
            "parameters": {"item": "iron_pickaxe", "count": 1},
        },
        {"iron_ingot": 3, "stick": 2},
        {"iron_pickaxe": 1},
    )


def _events(task_id):
    contract = task_contract(task_id)
    verifier = contract["terminal_verifier"]
    action, before_inventory, after_inventory = _action_fixture(task_id)
    before = _state(task_id, before_inventory, 40)
    after = _state(task_id, after_inventory, 80)
    events = [
        {
            "type": "autonomous_start",
            "monotonic_s": 100.0,
            "data": {
                "mode": "autonomous",
                "task_id": task_id,
                "task_contract_id": contract["id"],
                "task_contract_sha256": task_contract_sha256(task_id),
            },
        },
        {"type": "m4_player_lifecycle", "monotonic_s": 100.1, "data": _lifecycle(task_id)},
        {"type": "observation", "monotonic_s": 101.0, "data": _state(task_id, {}, 0)},
        {
            "type": "auto_goal",
            "monotonic_s": 102.0,
            "data": {
                "goal": contract["terminal_goal"],
                "selection_source": "goal_generator",
                "selection_reason": f"{task_id.lower()}_machine_frontier_ready",
                "priority": 6,
            },
        },
        _planner_call(task_id),
        {
            "type": "plan",
            "monotonic_s": 102.75,
            "data": {"status": "planning", "actions": [copy.deepcopy(action)]},
        },
        {
            "type": "action",
            "monotonic_s": 103.0,
            "data": {
                "action": action,
                "result": {
                    "success": True,
                    "action_verification": {"decision": "allow", "confidence": 1.0},
                },
                "pre_observation": before,
                "post_observation": after,
            },
        },
        {"type": "observation", "monotonic_s": 104.0, "data": after},
        {
            "type": verifier["event_type"],
            "monotonic_s": 105.0,
            "data": {
                "type": verifier["payload_type"],
                "schema_version": 1,
                "passed": True,
                "source": verifier["source"],
                "task_id": task_id,
                "goal": contract["terminal_goal"],
                "verifier_id": verifier["id"],
                "task_contract_id": contract["id"],
                "task_contract_sha256": task_contract_sha256(task_id),
                "output_item": verifier["output_item"],
                "qualifying_item": verifier["output_item"],
                "required_count": verifier["output_count"],
                "observed_count": verifier["output_count"],
                "inventory": after_inventory,
                "health": 20,
                "food": 18,
                "bot_connected": True,
                "uninterrupted_survival": True,
                "player_lifecycle_verifier_id": PROTOCOL["identities"][
                    "player_lifecycle_verifier"
                ],
                "player_lifecycle": _lifecycle(task_id),
                "required_action_type": verifier["required_action_type"],
            },
        },
        {"type": "goal_end", "monotonic_s": 106.0, "data": {"completed": True}},
        {"type": "autonomous_end", "monotonic_s": 107.0, "data": {"completed": True}},
    ]
    return events


def _result(task_id, events):
    _, _, after_inventory = _action_fixture(task_id)
    result = {
        "type": "m4_episode_result",
        "schema_version": 1,
        "task_id": task_id,
        "profile": PROTOCOL["profile"],
        "completed": True,
        "termination_reason": task_contract(task_id)["terminal_verifier"][
            "termination_reason"
        ],
        "elapsed_s": 12.0,
        "deadline_eligible": True,
        "external_step_script": False,
        "terminal_state": {
            **_state(task_id, after_inventory, 80),
            "bot_connected": True,
        },
    }
    return attach_m4_evidence_hashes(
        result,
        _preflight(task_id),
        _manifest(task_id),
        events,
    )


def _rehash(task_id, result, events):
    payload = dict(result)
    payload.pop("evidence_hashes", None)
    return attach_m4_evidence_hashes(
        payload,
        _preflight(task_id),
        _manifest(task_id),
        events,
    )


@pytest.mark.parametrize("task_id", TASK_IDS)
def test_task_contract_and_machine_delta_provenance_are_independently_eligible(task_id):
    integrity = task_contract_integrity_report(task_id)
    assert integrity["passed"], integrity
    events = _events(task_id)
    result = _result(task_id, events)
    eligibility = evaluate_m4_episode(
        events,
        result,
        _preflight(task_id),
        _manifest(task_id),
        task_id,
    )
    assert eligibility["eligible"], eligibility
    provenance = eligibility["evidence"]["task_provenance"]
    assert provenance["initial_target_count"] == 0
    assert provenance["terminal_target_passed"] is True
    assert provenance["positive_inventory_delta_passed"] is True
    assert provenance["successful_source_action_count"] == 1
    assert provenance["successful_source_actions"][0]["action_type"] == (
        task_contract(task_id)["terminal_verifier"]["required_action_type"]
    )

    progress = build_m4_episode_progress_report(
        events,
        result,
        _preflight(task_id),
        _manifest(task_id),
        eligibility,
    )
    assert progress["type"] == "m4_task_progress_report"
    assert progress["task_id"] == task_id
    assert progress["progress_gate_passed"] is True
    assert progress["counts_toward_task_success"] is True
    assert progress["task_provenance"] == provenance
    assert progress["output_provenance"] == provenance


@pytest.mark.parametrize("task_id", TASK_IDS)
def test_terminal_inventory_without_action_bound_machine_delta_is_rejected(task_id):
    events = _events(task_id)
    action_event = next(event for event in events if event["type"] == "action")
    action_event["data"]["post_observation"]["inventory"] = dict(
        action_event["data"]["pre_observation"]["inventory"]
    )
    result = _rehash(task_id, _result(task_id, _events(task_id)), events)
    eligibility = evaluate_m4_episode(
        events,
        result,
        _preflight(task_id),
        _manifest(task_id),
        task_id,
    )
    assert not eligibility["eligible"]
    assert "output_successful_source_actions" in eligibility["issues"]
    provenance = eligibility["evidence"]["output_provenance"]
    assert provenance["successful_action_candidate_count"] == 1
    assert provenance["successful_source_action_count"] == 0


@pytest.mark.parametrize("task_id", TASK_IDS)
def test_wrong_terminal_event_or_preloaded_output_is_rejected(task_id):
    events = _events(task_id)
    terminal_index = next(
        index
        for index, event in enumerate(events)
        if event["type"] == task_contract(task_id)["terminal_verifier"]["event_type"]
    )
    events[terminal_index]["type"] = "terminal_survival_verification"
    result = _rehash(task_id, _result(task_id, _events(task_id)), events)
    wrong_event = evaluate_m4_episode(
        events,
        result,
        _preflight(task_id),
        _manifest(task_id),
        task_id,
    )
    assert not wrong_event["eligible"]
    assert (
        f"event:{task_contract(task_id)['terminal_verifier']['event_type']}"
        in wrong_event["issues"]
    )
    assert "terminal_machine_verification" in wrong_event["issues"]

    events = _events(task_id)
    output_item = task_contract(task_id)["terminal_verifier"]["output_item"]
    first_observation = next(event for event in events if event["type"] == "observation")
    first_observation["data"]["inventory"] = {output_item: 1}
    result = _rehash(task_id, _result(task_id, _events(task_id)), events)
    preloaded = evaluate_m4_episode(
        events,
        result,
        _preflight(task_id),
        _manifest(task_id),
        task_id,
    )
    assert not preloaded["eligible"]
    assert "output_initial_inventory_empty" in preloaded["issues"]


@pytest.mark.parametrize("task_id", TASK_IDS)
def test_capability_loader_accepts_complete_task_bundle(task_id):
    directory = Path(tempfile.mkdtemp(prefix=f"m4-{task_id.lower()}-capability-", dir="."))
    try:
        events = _events(task_id)
        preflight = _preflight(task_id)
        manifest = _manifest(task_id)
        result = _result(task_id, events)
        eligibility = evaluate_m4_episode(
            events,
            result,
            preflight,
            manifest,
            task_id,
        )
        for name, payload in {
            "preflight.json": preflight,
            "manifest.json": manifest,
            "session.json": events,
            "result.json": result,
            "eligibility.json": eligibility,
        }.items():
            (directory / name).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        report = build_capability_evidence_report(
            benchmark_result_paths=[str(directory / "eligibility.json")],
            status_path="workspace/STATUS.md",
        )
        m4 = next(phase for phase in report["phases"] if phase["id"] == "M4")
        task = next(row for row in m4["benchmarks"] if row["task_id"] == task_id)
        assert task["attempts"] == 1
        assert task["successes"] == 1
        assert task["ineligible_successes"] == 0
    finally:
        shutil.rmtree(directory)


def test_predecessor_replay_never_rebinds_new_task_contracts():
    task_id = "BM-013"
    contract_base = task_contract(task_id)["base_protocol_sha256"]
    contract_sha = task_contract_sha256(task_id)
    predecessor = next(
        value for value in supported_protocol_sha256s() if value != PROTOCOL_SHA256
    )
    report = evaluate_m4_episode_for_protocol_hash(
        _events(task_id),
        _result(task_id, _events(task_id)),
        _preflight(task_id),
        _manifest(task_id),
        task_id,
        predecessor,
    )
    assert not report["eligible"]
    assert task_contract(task_id)["base_protocol_sha256"] == contract_base
    assert task_contract_sha256(task_id) == contract_sha
