"""Offline contract tests for the fixed M4 autonomous-survival protocol."""

import copy
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from singularity.evaluation.m4_protocol import (
    PROTOCOL,
    PROTOCOL_SHA256,
    canonical_sha256,
    evaluate_bm011_episode,
    protocol_integrity_report,
    remaining_budget_s,
    task_spec,
    validate_m4_player_lifecycle,
    validate_preflight,
)


def _lifecycle(death_count=0, respawn_count=0, spawn_count=0):
    baseline_deaths = 2
    baseline_respawns = 2
    baseline_spawns = 3
    last_death = None
    last_respawn = None
    if death_count:
        last_death = {
            "kind": "death",
            "event_sequence": 7,
            "observed_at_ms": 1700000001000,
            "bridge_monotonic_ms": 1100,
            "position": {"x": 1, "y": 64, "z": 1},
            "health": 0,
            "death_count_total": baseline_deaths + death_count,
        }
    if respawn_count:
        last_respawn = {
            "kind": "respawn",
            "event_sequence": 8,
            "observed_at_ms": 1700000002000,
            "bridge_monotonic_ms": 1200,
            "position": {"x": 1, "y": 64, "z": 1},
            "health": 20,
            "respawn_count_total": baseline_respawns + respawn_count,
            "spawn_count_total": baseline_spawns + spawn_count,
        }
    return {
        "type": "m4_player_lifecycle",
        "schema_version": 1,
        "verifier_id": PROTOCOL["identities"]["player_lifecycle_verifier"],
        "source": "mineflayer_events",
        "profile": PROTOCOL["profile"],
        "protocol_sha256": PROTOCOL_SHA256,
        "tracker_id": "m4-fixture-tracker-01",
        "episode_id": "m4-fixture-episode-01",
        "level_name": "m4_fixture_level_01",
        "baseline_id": "a" * 64,
        "baseline_established": True,
        "initial_spawn_observed": True,
        "baseline_death_count_total": baseline_deaths,
        "baseline_respawn_count_total": baseline_respawns,
        "baseline_spawn_count_total": baseline_spawns,
        "baseline_observed_at_ms": 1700000000000,
        "baseline_bridge_monotonic_ms": 1000,
        "death_count_total": baseline_deaths + death_count,
        "respawn_count_total": baseline_respawns + respawn_count,
        "spawn_count_total": baseline_spawns + spawn_count,
        "death_count": death_count,
        "respawn_count": respawn_count,
        "spawn_count": spawn_count,
        "pending_respawn_count": death_count - respawn_count,
        "uninterrupted": death_count == 0 and respawn_count == 0,
        "last_death": last_death,
        "last_respawn": last_respawn,
    }


def _preflight():
    return {
        "type": "m4_preflight",
        "passed": True,
        "task_id": "BM-011",
        "profile": PROTOCOL["profile"],
        "protocol_sha256": PROTOCOL_SHA256,
        "server_jar_sha256": PROTOCOL["server_jar_sha256"],
        "world_seed": PROTOCOL["world_seed"],
        "fresh_episode": True,
        "game_mode": PROTOCOL["game_mode"],
        "difficulty": PROTOCOL["difficulty"],
        "initial_inventory": {},
        "initial_player_state": dict(PROTOCOL["initial_player_state"]),
        "initial_time_of_day": PROTOCOL["initial_time_of_day"],
        "weather": PROTOCOL["weather"],
        "gamerules": dict(PROTOCOL["gamerules"]),
        "runtime_versions": dict(PROTOCOL["runtime_versions"]),
        "llm": dict(PROTOCOL["llm"]),
        "identities": dict(PROTOCOL["identities"]),
        "runtime_controls": dict(PROTOCOL["baseline_runtime_controls"]),
        "player_lifecycle_baseline": _lifecycle(),
        "source_checks": {"protocol_status_bound": True, "reset_bound": True},
        "episode_id": "m4-fixture-episode-01",
        "level_name": "m4_fixture_level_01",
    }


def _manifest():
    return {
        "type": "m4_runtime_manifest",
        "task_id": "BM-011",
        "profile": PROTOCOL["profile"],
        "protocol_sha256": PROTOCOL_SHA256,
        "reset_protocol_sha256": PROTOCOL["reset_protocol_sha256"],
        "validation_protocol_sha256": PROTOCOL["validation_protocol_sha256"],
        "deadline_policy_id": PROTOCOL["deadline_policy"]["id"],
        "episode_id": "m4-fixture-episode-01",
        "session_id": "m4-fixture-session-01",
        "level_name": "m4_fixture_level_01",
        "episode_started_monotonic": 100.0,
        "episode_deadline_monotonic": 1300.0,
        "episode_ended_monotonic": 805.0,
        "runtime_controls": dict(PROTOCOL["baseline_runtime_controls"]),
        "runtime_limits": {
            "max_duration_s": 1200,
            "max_goals": 24,
            "max_cycles_per_goal": 40,
        },
    }


def _observation(time_of_day: int, monotonic_s: float, health: float = 20, lifecycle=None):
    return {
        "type": "observation",
        "monotonic_s": monotonic_s,
        "data": {
            "time_of_day": time_of_day,
            "health": health,
            "food": 18,
            "inventory": {"oak_planks": 2},
            "position": {"x": 1, "y": 64, "z": 1},
            "player_lifecycle": copy.deepcopy(lifecycle or _lifecycle()),
        },
    }


def _events():
    before = _observation(9000, 101.0)["data"]
    after = _observation(11000, 104.0)["data"]
    return [
        {"type": "benchmark_reset", "monotonic_s": 90.0, "data": {"success": True}},
        {"type": "autonomous_start", "monotonic_s": 100.0, "data": {"mode": "autonomous"}},
        {"type": "m4_player_lifecycle", "monotonic_s": 100.5, "data": _lifecycle()},
        _observation(9000, 101.0),
        {
            "type": "auto_goal",
            "monotonic_s": 102.0,
            "data": {
                "goal": "Gather shelter materials",
                "selection_source": "goal_generator",
                "selection_reason": "daylight preparation bootstrap",
                "priority": 60,
            },
        },
        {
            "type": "llm_planner_call",
            "monotonic_s": 102.5,
            "data": {
                "call_id": "m4-fixture-planner-01",
                "real_llm_call": True,
                "schema_valid": True,
                "provider_metadata": {
                    "extra_body": copy.deepcopy(PROTOCOL["llm"]["extra_body"]),
                    "finish_reason": "stop",
                    "reasoning_content_byte_count": 0,
                    "duration_ms": 750,
                    "total_tokens": 128,
                },
            },
        },
        {"type": "plan", "monotonic_s": 103.0, "data": {"status": "planning"}},
        {
            "type": "action",
            "monotonic_s": 104.0,
            "data": {
                "action": {"type": "craft", "parameters": {"item": "oak_planks"}},
                "result": {
                    "success": True,
                    "action_verification": {"decision": "allow", "confidence": 1.0},
                },
                "pre_observation": before,
                "post_observation": after,
            },
        },
        _observation(11000, 105.0),
        _observation(13000, 300.0),
        _observation(17000, 500.0),
        _observation(22000, 750.0),
        _observation(23010, 801.0, health=18),
        {
            "type": "terminal_survival_verification",
            "monotonic_s": 802.0,
            "data": {
                "passed": True,
                "source": "machine_state",
                "time_of_day": 23010,
                "health": 18,
                "bot_connected": True,
                "uninterrupted_survival": True,
                "player_lifecycle_verifier_id": PROTOCOL["identities"]["player_lifecycle_verifier"],
                "player_lifecycle": _lifecycle(),
            },
        },
        {"type": "goal_end", "monotonic_s": 803.0, "data": {"completed": True}},
        {"type": "autonomous_end", "monotonic_s": 804.0, "data": {"completed": True}},
    ]


def _result(events=None):
    session_events = _events() if events is None else events
    terminal_observation = next(
        event["data"] for event in reversed(session_events)
        if event.get("type") == "observation"
    )
    result = {
        "completed": True,
        "termination_reason": "terminal_survival_verified",
        "elapsed_s": 705.0,
        "external_step_script": False,
        "terminal_state": {
            "health": 18,
            "bot_connected": True,
            "time_of_day": 23010,
            "player_lifecycle": copy.deepcopy(terminal_observation["player_lifecycle"]),
        },
    }
    result["evidence_hashes"] = {
        "preflight_sha256": canonical_sha256(_preflight()),
        "manifest_sha256": canonical_sha256(_manifest()),
        "session_sha256": canonical_sha256(session_events),
        "result_sha256": canonical_sha256(result),
    }
    return result


def test_m4_protocol_integrity_and_scope():
    report = protocol_integrity_report()
    assert report["passed"], report
    assert PROTOCOL["profile"] == "m4-fixed-v1"
    assert PROTOCOL["difficulty"] == "normal"
    assert PROTOCOL["gamerules"]["doDaylightCycle"] is True
    assert PROTOCOL["gamerules"]["doMobSpawning"] is True
    assert PROTOCOL["validation_contract"]["survival"]["active_episode_death_count"] == 0
    assert PROTOCOL["validation_contract"]["survival"]["uninterrupted_survival_required"] is True
    assert task_spec("BM-011")["terminal_goal"] == "Survive until the next dawn"
    assert task_spec("BM-012")["id"] == "BM-012"
    print("PASS: M4 protocol integrity and independent task scope")


def test_m4_deadline_budget_uses_one_absolute_deadline():
    assert remaining_budget_s(200.0, 90.0, now_monotonic=100.0) == 90.0
    assert remaining_budget_s(150.0, 90.0, now_monotonic=100.0) == 50.0
    assert remaining_budget_s(99.0, 90.0, now_monotonic=100.0) == 0.0
    print("PASS: M4 call/action budgets share one absolute deadline")


def test_m4_preflight_requires_survival_fresh_episode():
    assert validate_preflight(_preflight())["passed"]
    invalid = _preflight()
    invalid["difficulty"] = "peaceful"
    invalid["fresh_episode"] = False
    invalid["initial_inventory"] = {"oak_log": 1}
    report = validate_preflight(invalid)
    assert not report["passed"]
    assert {"difficulty", "fresh_episode", "empty_inventory"}.issubset(report["issues"])
    print("PASS: M4 preflight rejects peaceful, reused, or preloaded episodes")


def test_m4_player_lifecycle_contract_requires_bridge_owned_zero_delta():
    baseline = validate_m4_player_lifecycle(
        _lifecycle(),
        episode_id="m4-fixture-episode-01",
        require_uninterrupted=True,
    )
    death = validate_m4_player_lifecycle(
        _lifecycle(death_count=1, respawn_count=1, spawn_count=1),
        episode_id="m4-fixture-episode-01",
        require_uninterrupted=True,
    )
    malformed = _lifecycle()
    malformed["source"] = "terminal_health_inference"
    malformed["death_count"] = False

    assert baseline["passed"] is True
    assert death["passed"] is False
    assert {"active_episode_death_count", "active_episode_respawn_count", "uninterrupted_survival"}.issubset(
        death["issues"]
    )
    assert validate_m4_player_lifecycle(malformed)["passed"] is False

    invalid_preflight = _preflight()
    invalid_preflight["player_lifecycle_baseline"] = _lifecycle(
        death_count=1,
        respawn_count=1,
        spawn_count=1,
    )
    assert "player_lifecycle_baseline" in validate_preflight(invalid_preflight)["issues"]
    print("PASS: M4 lifecycle accepts only bridge-owned zero-death episode baselines")


def test_bm011_eligible_machine_state_evidence():
    report = evaluate_bm011_episode(_events(), _result(), _preflight(), _manifest())
    assert report["eligible"], report
    assert report["evidence"]["planner_provider_controls"]["passed"] is True
    assert report["evidence"]["planner_provider_controls"]["schema_valid_real_call_count"] == 1
    assert report["evidence"]["night_observation_index"] is not None
    assert report["evidence"]["dawn_observation_index"] is not None
    assert report["evidence"]["maximum_death_count"] == 0
    assert report["evidence"]["maximum_respawn_count"] == 0
    assert report["evidence"]["uninterrupted_survival"] is True
    print("PASS: BM-011 gate accepts bounded autonomous machine-state evidence")


def test_bm011_rejects_probe14_death_respawn_false_positive():
    events = _events()
    death_lifecycle = _lifecycle(death_count=1, respawn_count=1, spawn_count=1)
    insert_at = next(
        index for index, event in enumerate(events)
        if event.get("type") == "observation" and event.get("monotonic_s") == 500.0
    )
    events.insert(insert_at, {
        "type": "m4_player_lifecycle",
        "monotonic_s": 499.0,
        "data": copy.deepcopy(death_lifecycle),
    })
    for event in events:
        if event.get("type") == "observation" and event.get("monotonic_s", 0) >= 500.0:
            event["data"]["health"] = 20
            event["data"]["inventory"] = {}
            event["data"]["player_lifecycle"] = copy.deepcopy(death_lifecycle)
        if event.get("type") == "terminal_survival_verification":
            event["data"]["health"] = 20
            event["data"]["uninterrupted_survival"] = False
            event["data"]["player_lifecycle"] = copy.deepcopy(death_lifecycle)

    result = _result(events)
    result["terminal_state"]["health"] = 20
    report = evaluate_bm011_episode(events, result, _preflight(), _manifest())

    assert report["eligible"] is False
    assert {
        "active_episode_death_absent",
        "active_episode_respawn_absent",
        "uninterrupted_survival",
        "terminal_player_lifecycle",
        "terminal_machine_verification",
    }.issubset(report["issues"])
    assert report["evidence"]["maximum_death_count"] == 1
    assert report["evidence"]["maximum_respawn_count"] == 1
    print("PASS: BM-011 independently rejects Probe 14-style death, respawn, health-20 terminal false positives")


def test_bm011_rejects_missing_or_rolled_back_lifecycle_evidence():
    missing = _events()
    next(event for event in missing if event.get("type") == "observation")["data"].pop("player_lifecycle")
    missing_report = evaluate_bm011_episode(missing, _result(missing), _preflight(), _manifest())
    assert "player_lifecycle_observation_complete" in missing_report["issues"]

    rollback = _events()
    death_lifecycle = _lifecycle(death_count=1, respawn_count=1, spawn_count=1)
    observations = [event for event in rollback if event.get("type") == "observation"]
    observations[2]["data"]["player_lifecycle"] = death_lifecycle
    rollback_report = evaluate_bm011_episode(rollback, _result(rollback), _preflight(), _manifest())
    assert "player_lifecycle_counts_monotonic" in rollback_report["issues"]
    assert "active_episode_death_absent" in rollback_report["issues"]

    event_only = _events()
    event_only.insert(-3, {
        "type": "m4_player_lifecycle",
        "monotonic_s": 800.5,
        "data": _lifecycle(death_count=1, respawn_count=1, spawn_count=1),
    })
    event_only_report = evaluate_bm011_episode(
        event_only,
        _result(event_only),
        _preflight(),
        _manifest(),
    )
    assert "active_episode_death_absent" in event_only_report["issues"]
    assert "active_episode_respawn_absent" in event_only_report["issues"]

    malformed = _events()
    malformed_observation = next(event for event in malformed if event.get("type") == "observation")
    malformed_observation["data"]["player_lifecycle"]["death_count"] = "unknown"
    malformed_report = evaluate_bm011_episode(
        malformed,
        _result(malformed),
        _preflight(),
        _manifest(),
    )
    assert "player_lifecycle_observation_valid" in malformed_report["issues"]
    assert "active_episode_death_absent" in malformed_report["issues"]
    assert malformed_report["evidence"]["maximum_death_count"] is None
    print("PASS: BM-011 fails closed on missing or rolled-back lifecycle evidence")


def test_bm011_rejects_shortened_runtime_limits():
    manifest = _manifest()
    manifest["runtime_limits"] = {
        "max_duration_s": 240,
        "max_goals": 4,
        "max_cycles_per_goal": 8,
    }

    report = evaluate_bm011_episode(_events(), _result(), _preflight(), manifest)

    assert report["eligible"] is False
    assert "manifest_runtime_limits" in report["issues"]
    print("PASS: BM-011 gate rejects shortened runtime harness limits")


def test_bm011_rejects_active_reset_and_time_command():
    events = _events()
    events.insert(5, {
        "type": "bridge_command",
        "monotonic_s": 103.5,
        "data": {"command": "time set day"},
    })
    events.insert(6, {"type": "benchmark_reset", "monotonic_s": 103.6, "data": {"success": True}})
    report = evaluate_bm011_episode(events, _result(events), _preflight(), _manifest())
    assert not report["eligible"]
    assert "active_episode_forbidden_commands_absent" in report["issues"]
    print("PASS: BM-011 gate rejects active reset and time manipulation")


def test_bm011_rejects_deadline_overrun_and_post_deadline_action():
    manifest = _manifest()
    manifest["episode_deadline_monotonic"] = 800.0
    manifest["episode_ended_monotonic"] = 901.0
    result = _result()
    result["elapsed_s"] = 1201.0
    events = _events()
    action = next(event for event in events if event["type"] == "action")
    events.insert(-2, copy.deepcopy(action))
    events[-3]["monotonic_s"] = 850.0
    report = evaluate_bm011_episode(events, result, _preflight(), manifest)
    assert not report["eligible"]
    assert "episode_within_deadline" in report["issues"]
    assert "result_duration_eligible" in report["issues"]
    assert "no_post_deadline_execution" in report["issues"]
    print("PASS: BM-011 gate independently rejects deadline overrun")


def test_bm011_rejects_unpinned_planner_provider_controls():
    events = _events()
    planner_call = next(event for event in events if event["type"] == "llm_planner_call")
    planner_call["data"]["provider_metadata"].update({
        "extra_body": {},
        "finish_reason": "length",
        "reasoning_content_byte_count": 64,
    })
    report = evaluate_bm011_episode(events, _result(events), _preflight(), _manifest())
    assert not report["eligible"]
    assert "planner_provider_controls" in report["issues"]
    violations = report["evidence"]["planner_provider_controls"]["violations"]
    assert "m4-fixture-planner-01:extra_body_mismatch" in violations
    assert "m4-fixture-planner-01:finish_reason_mismatch" in violations
    assert "m4-fixture-planner-01:reasoning_content_exceeded" in violations
    print("PASS: BM-011 gate rejects unpinned Planner provider controls")


def test_bm011_rejects_missing_or_unordered_monotonic_event_time():
    missing = _events()
    plan = next(event for event in missing if event["type"] == "plan")
    plan.pop("monotonic_s")
    missing_report = evaluate_bm011_episode(missing, _result(), _preflight(), _manifest())
    assert not missing_report["eligible"]
    assert "active_event_monotonic_complete" in missing_report["issues"]
    assert "no_post_deadline_execution" in missing_report["issues"]

    unordered = _events()
    action = next(event for event in unordered if event["type"] == "action")
    action["monotonic_s"] = 99.0
    unordered_report = evaluate_bm011_episode(unordered, _result(), _preflight(), _manifest())
    assert not unordered_report["eligible"]
    assert "active_event_monotonic_ordered" in unordered_report["issues"]

    missing_deadline = _manifest()
    missing_deadline.pop("episode_deadline_monotonic")
    missing_deadline_report = evaluate_bm011_episode(
        _events(),
        _result(),
        _preflight(),
        missing_deadline,
    )
    assert not missing_deadline_report["eligible"]
    assert "monotonic_runtime" in missing_deadline_report["issues"]
    assert "episode_within_deadline" in missing_deadline_report["issues"]
    print("PASS: BM-011 gate rejects missing or unordered monotonic event time")


def test_bm011_rejects_scripted_goal_and_quarantined_skill():
    events = _events()
    auto_goal = next(event for event in events if event["type"] == "auto_goal")
    auto_goal["data"]["selection_source"] = "benchmark_script"
    events.insert(5, {
        "type": "skill_execution_start",
        "monotonic_s": 103.5,
        "data": {"skill_name": "survive_first_night", "status": "quarantined", "root_goal": True},
    })
    report = evaluate_bm011_episode(events, _result(), _preflight(), _manifest())
    assert not report["eligible"]
    assert "autonomous_goal_source" in report["issues"]
    assert "quarantined_skill_absent" in report["issues"]
    assert "strategic_root_skill_absent" in report["issues"]
    print("PASS: BM-011 gate rejects scripted goals and quarantined root skills")


if __name__ == "__main__":
    test_m4_protocol_integrity_and_scope()
    test_m4_deadline_budget_uses_one_absolute_deadline()
    test_m4_preflight_requires_survival_fresh_episode()
    test_bm011_eligible_machine_state_evidence()
    test_bm011_rejects_shortened_runtime_limits()
    test_bm011_rejects_active_reset_and_time_command()
    test_bm011_rejects_deadline_overrun_and_post_deadline_action()
    test_bm011_rejects_unpinned_planner_provider_controls()
    test_bm011_rejects_missing_or_unordered_monotonic_event_time()
    test_bm011_rejects_scripted_goal_and_quarantined_skill()
    print("\nM4 protocol tests PASSED")
