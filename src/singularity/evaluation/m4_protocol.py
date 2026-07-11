"""Fixed M4 protocol and machine-checkable episode eligibility gates."""

from __future__ import annotations

import hashlib
import json
import math
import time
from pathlib import Path


PROTOCOL_PATH = Path(__file__).resolve().parent.parent / "data" / "m4_protocol.json"
PROTOCOL_BYTES = PROTOCOL_PATH.read_bytes()
PROTOCOL = json.loads(PROTOCOL_BYTES.decode("utf-8"))
PROTOCOL_SHA256 = hashlib.sha256(PROTOCOL_BYTES).hexdigest()
TASKS_BY_ID = {str(task["id"]): task for task in PROTOCOL["tasks"]}


def canonical_sha256(value) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def protocol_integrity_report() -> dict:
    expected = {
        "reset_protocol_sha256": canonical_sha256(PROTOCOL.get("reset_contract", {})),
        "validation_protocol_sha256": canonical_sha256(PROTOCOL.get("validation_contract", {})),
    }
    issues = [name for name, value in expected.items() if str(PROTOCOL.get(name) or "") != value]
    if PROTOCOL.get("profile") != "m4-fixed-v1":
        issues.append("profile_mismatch")
    if PROTOCOL.get("game_mode") != "survival":
        issues.append("survival_mode_required")
    if PROTOCOL.get("difficulty") == "peaceful":
        issues.append("peaceful_difficulty_forbidden")
    gamerules = PROTOCOL.get("gamerules", {})
    if gamerules.get("doDaylightCycle") is not True:
        issues.append("natural_time_progression_required")
    if gamerules.get("doMobSpawning") is not True:
        issues.append("mob_spawning_required")
    if PROTOCOL.get("initial_inventory") != {}:
        issues.append("initial_inventory_must_be_empty")
    controls = PROTOCOL.get("baseline_runtime_controls", {})
    if controls.get("skill_execution_mode") != "off":
        issues.append("learned_skill_execution_must_be_off")
    for name in (
        "learned_executable_skills_enabled",
        "quarantined_skills_enabled",
        "vision_enabled",
        "multi_agent_enabled",
    ):
        if controls.get(name) is not False:
            issues.append(f"baseline_control_mismatch:{name}")
    planner_contract = PROTOCOL.get("validation_contract", {}).get("planner_evidence", {})
    required_extra_body = {"thinking": {"type": "disabled"}}
    if PROTOCOL.get("llm", {}).get("extra_body") != required_extra_body:
        issues.append("planner_thinking_must_be_disabled")
    if planner_contract.get("required_extra_body") != required_extra_body:
        issues.append("planner_extra_body_contract_mismatch")
    if planner_contract.get("real_llm_call_required") is not True:
        issues.append("planner_real_llm_call_must_be_required")
    if planner_contract.get("schema_valid_call_required") is not True:
        issues.append("planner_schema_valid_call_must_be_required")
    if planner_contract.get("finish_reason") != "stop":
        issues.append("planner_finish_reason_must_be_stop")
    if planner_contract.get("reasoning_content_max_bytes") != 0:
        issues.append("planner_reasoning_content_must_be_disabled")
    return {
        "passed": not issues,
        "issues": issues,
        "protocol_sha256": PROTOCOL_SHA256,
        **expected,
    }


def task_spec(task_id: str) -> dict:
    return TASKS_BY_ID.get(str(task_id or "").upper().strip(), {})


def remaining_budget_s(
    episode_deadline_monotonic: float,
    maximum_s: float,
    now_monotonic: float | None = None,
) -> float:
    """Return a bounded call/action budget from the one absolute episode deadline."""
    now = time.monotonic() if now_monotonic is None else float(now_monotonic)
    remaining = max(0.0, float(episode_deadline_monotonic) - now)
    return min(max(0.0, float(maximum_s)), remaining)


def validate_preflight(preflight: dict, task_id: str = "BM-011") -> dict:
    issues = []
    checks = []

    def require(name: str, passed: bool, detail=""):
        checks.append({"name": name, "passed": bool(passed), "detail": detail})
        if not passed:
            issues.append(name)

    require("preflight_type", preflight.get("type") == "m4_preflight")
    require("preflight_passed", preflight.get("passed") is True)
    require("task_id", str(preflight.get("task_id") or "") == task_id)
    require("protocol_profile", preflight.get("profile") == PROTOCOL["profile"])
    require("protocol_sha256", preflight.get("protocol_sha256") == PROTOCOL_SHA256)
    require("server_jar_sha256", preflight.get("server_jar_sha256") == PROTOCOL["server_jar_sha256"])
    require("world_seed", str(preflight.get("world_seed") or "") == PROTOCOL["world_seed"])
    require("fresh_episode", preflight.get("fresh_episode") is True)
    require("game_mode", preflight.get("game_mode") == PROTOCOL["game_mode"])
    require("difficulty", preflight.get("difficulty") == PROTOCOL["difficulty"])
    require("empty_inventory", _inventory_counts(preflight.get("initial_inventory")) == {})
    require("initial_player_state", _player_state_matches(preflight.get("initial_player_state", {})))
    require(
        "initial_time",
        _number_near(preflight.get("initial_time_of_day"), PROTOCOL["initial_time_of_day"], 600),
    )
    require("weather", preflight.get("weather") == PROTOCOL["weather"])
    require("gamerules", _mapping_contains(preflight.get("gamerules", {}), PROTOCOL["gamerules"]))
    require("runtime_versions", _mapping_contains(preflight.get("runtime_versions", {}), PROTOCOL["runtime_versions"]))
    require("llm", _mapping_contains(preflight.get("llm", {}), PROTOCOL["llm"]))
    require("identities", _mapping_contains(preflight.get("identities", {}), PROTOCOL["identities"]))
    require(
        "baseline_runtime_controls",
        _mapping_contains(preflight.get("runtime_controls", {}), PROTOCOL["baseline_runtime_controls"]),
    )
    source_checks = preflight.get("source_checks", {})
    require(
        "runtime_source_binding",
        isinstance(source_checks, dict)
        and bool(source_checks)
        and all(value is True for value in source_checks.values()),
        source_checks,
    )
    require("episode_id", bool(str(preflight.get("episode_id") or "").strip()))
    require("level_name", bool(str(preflight.get("level_name") or "").strip()))
    return {"passed": not issues, "issues": issues, "checks": checks}


def evaluate_bm011_episode(
    events: list[dict],
    result: dict,
    preflight: dict,
    manifest: dict,
) -> dict:
    """Independently evaluate one BM-011 session; textual completion is never sufficient."""
    issues = []
    checks = []

    def require(name: str, passed: bool, detail=""):
        checks.append({"name": name, "passed": bool(passed), "detail": detail})
        if not passed:
            issues.append(name)

    preflight_report = validate_preflight(preflight, "BM-011")
    require("preflight_eligible", preflight_report["passed"], preflight_report["issues"])
    integrity = protocol_integrity_report()
    require("protocol_integrity", integrity["passed"], integrity["issues"])

    require("manifest_type", manifest.get("type") == "m4_runtime_manifest")
    require("manifest_task", manifest.get("task_id") == "BM-011")
    require("manifest_profile", manifest.get("profile") == PROTOCOL["profile"])
    require("manifest_protocol", manifest.get("protocol_sha256") == PROTOCOL_SHA256)
    require("manifest_reset_protocol", manifest.get("reset_protocol_sha256") == PROTOCOL["reset_protocol_sha256"])
    require(
        "manifest_validation_protocol",
        manifest.get("validation_protocol_sha256") == PROTOCOL["validation_protocol_sha256"],
    )
    require("manifest_episode", bool(manifest.get("episode_id")) and manifest.get("episode_id") == preflight.get("episode_id"))
    require("manifest_session", bool(manifest.get("session_id")))
    require("manifest_level", bool(manifest.get("level_name")) and manifest.get("level_name") == preflight.get("level_name"))
    require(
        "manifest_deadline_policy",
        manifest.get("deadline_policy_id") == PROTOCOL["deadline_policy"]["id"],
    )
    require(
        "manifest_runtime_controls",
        _mapping_contains(manifest.get("runtime_controls", {}), PROTOCOL["baseline_runtime_controls"]),
    )
    runtime_limits = manifest.get("runtime_limits", {})
    task_limit = task_spec("BM-011")
    require(
        "manifest_runtime_limits",
        isinstance(runtime_limits, dict)
        and _bounded_positive(runtime_limits.get("max_duration_s"), task_limit.get("max_duration_s"))
        and _bounded_positive(runtime_limits.get("max_goals"), PROTOCOL["limits"]["max_autonomous_goals"])
        and _bounded_positive(runtime_limits.get("max_cycles_per_goal"), PROTOCOL["limits"]["max_cycles_per_goal"]),
        runtime_limits,
    )

    evidence_hashes = result.get("evidence_hashes", {}) if isinstance(result.get("evidence_hashes"), dict) else {}
    unhashed_result = dict(result)
    unhashed_result.pop("evidence_hashes", None)
    require("preflight_content_hash", evidence_hashes.get("preflight_sha256") == canonical_sha256(preflight))
    require("manifest_content_hash", evidence_hashes.get("manifest_sha256") == canonical_sha256(manifest))
    require("session_content_hash", evidence_hashes.get("session_sha256") == canonical_sha256(events))
    require("result_content_hash", evidence_hashes.get("result_sha256") == canonical_sha256(unhashed_result))

    event_types = [str(event.get("type") or "") for event in events if isinstance(event, dict)]
    required_events = PROTOCOL["validation_contract"]["autonomy"]["required_events"]
    for event_type in required_events:
        require(f"event:{event_type}", event_type in event_types)

    active_events = _active_episode_events(events)
    planner_controls = planner_provider_controls_report(active_events)
    require("planner_provider_controls", planner_controls["passed"], planner_controls["violations"])
    auto_goals = [event.get("data", {}) for event in active_events if event.get("type") == "auto_goal"]
    require("autonomous_goal_present", bool(auto_goals))
    require(
        "autonomous_goal_source",
        bool(auto_goals) and all(str(goal.get("selection_source") or "") in {"goal_generator", "curriculum"} for goal in auto_goals),
    )
    require(
        "autonomous_goal_reason",
        bool(auto_goals) and all(bool(str(goal.get("selection_reason") or "").strip()) for goal in auto_goals),
    )
    require(
        "autonomous_goal_priority",
        bool(auto_goals) and all(_finite_number(goal.get("priority")) for goal in auto_goals),
    )
    require("external_step_script_absent", not result.get("external_step_script"))

    action_events = [event for event in active_events if event.get("type") == "action"]
    require("action_present", bool(action_events))
    require("action_pre_observations", bool(action_events) and all(_action_observation(event, "pre_observation") for event in action_events))
    require("action_post_observations", bool(action_events) and all(_action_observation(event, "post_observation") for event in action_events))
    require("action_verifier", bool(action_events) and all(_action_verifier_present(event) for event in action_events))

    forbidden = _forbidden_active_events(active_events)
    require("active_episode_forbidden_commands_absent", not forbidden, forbidden)
    require("quarantined_skill_absent", not _quarantined_skill_used(active_events))
    require("strategic_root_skill_absent", not _strategic_root_skill_used(active_events))

    observations = [
        event.get("data", {}) for event in active_events
        if event.get("type") == "observation" and isinstance(event.get("data"), dict)
    ]
    times = [_normalized_time(obs.get("time_of_day")) for obs in observations]
    times = [value for value in times if value is not None]
    night_index = next((index for index, value in enumerate(times) if 12000 <= value < 23000), None)
    dawn_index = next(
        (index for index, value in enumerate(times) if night_index is not None and index > night_index and (value >= 23000 or value < 1000)),
        None,
    )
    require("night_observed", night_index is not None)
    require("next_dawn_observed", dawn_index is not None)
    require("natural_time_progression", _natural_time_progression(times))

    terminal_observation = observations[-1] if observations else {}
    terminal_state = result.get("terminal_state", {}) if isinstance(result.get("terminal_state"), dict) else {}
    health = terminal_observation.get("health", terminal_state.get("health", 0))
    require("terminal_health", _finite_number(health) and float(health) > 0)
    require("terminal_bot_connected", terminal_state.get("bot_connected") is True)
    require("terminal_machine_verification", _terminal_verification_matches(active_events, terminal_observation, terminal_state))

    started = _finite_or_none(manifest.get("episode_started_monotonic"))
    ended = _finite_or_none(manifest.get("episode_ended_monotonic"))
    deadline = _finite_or_none(manifest.get("episode_deadline_monotonic"))
    duration = ended - started if started is not None and ended is not None else None
    active_event_times = [
        _event_monotonic(event)
        for event in active_events
    ]
    bounded_event_times = [
        value
        for event, value in zip(active_events, active_event_times)
        if event.get("type") != "autonomous_end"
    ]
    task = task_spec("BM-011")
    require("monotonic_runtime", duration is not None and duration >= 0 and deadline is not None)
    require(
        "active_event_monotonic_complete",
        bool(active_event_times) and all(value is not None for value in active_event_times),
    )
    require(
        "active_event_monotonic_ordered",
        bool(active_event_times)
        and all(value is not None for value in active_event_times)
        and all(current >= previous for previous, current in zip(active_event_times, active_event_times[1:])),
    )
    require(
        "active_event_monotonic_bounds",
        bool(bounded_event_times)
        and all(value is not None for value in bounded_event_times)
        and started is not None
        and ended is not None
        and bounded_event_times[0] >= started
        and bounded_event_times[-1] <= ended,
    )
    require(
        "episode_within_deadline",
        duration is not None
        and ended is not None
        and deadline is not None
        and duration <= float(task["max_duration_s"])
        and ended <= deadline,
    )
    require("result_duration_eligible", _result_duration_eligible(result, task))
    require("no_post_deadline_execution", not _post_deadline_execution(active_events, deadline))

    success = not issues
    return {
        "type": "m4_episode_eligibility",
        "task_id": "BM-011",
        "profile": PROTOCOL["profile"],
        "protocol_sha256": PROTOCOL_SHA256,
        "eligible": success,
        "success": success,
        "issues": issues,
        "checks": checks,
        "evidence": {
            "event_count": len(events),
            "action_count": len(action_events),
            "autonomous_goal_count": len(auto_goals),
            "planner_provider_controls": planner_controls,
            "night_observation_index": night_index,
            "dawn_observation_index": dawn_index,
            "terminal_health": health,
            "episode_duration_s": round(duration, 3) if duration is not None else None,
            "forbidden_events": forbidden,
        },
    }


def planner_provider_controls_report(events: list[dict]) -> dict:
    """Verify that real M4 Planner calls used the pinned non-thinking payload."""
    contract = PROTOCOL["validation_contract"]["planner_evidence"]
    calls = [
        event.get("data", {})
        for event in events
        if isinstance(event, dict)
        and event.get("type") == "llm_planner_call"
        and isinstance(event.get("data"), dict)
    ]
    real_calls = [call for call in calls if call.get("real_llm_call") is True]
    schema_valid_calls = [call for call in real_calls if call.get("schema_valid") is True]
    violations = []
    durations = []
    total_tokens = 0
    expected_extra_body = contract["required_extra_body"]
    expected_finish_reason = str(contract["finish_reason"])
    reasoning_limit = int(contract["reasoning_content_max_bytes"])

    if contract.get("real_llm_call_required") is True and not real_calls:
        violations.append("real_llm_call_missing")
    if contract.get("schema_valid_call_required") is True and not schema_valid_calls:
        violations.append("schema_valid_real_llm_call_missing")

    for index, call in enumerate(real_calls):
        metadata = call.get("provider_metadata", {}) if isinstance(call.get("provider_metadata"), dict) else {}
        call_id = str(call.get("call_id") or f"call_{index}")
        if metadata.get("extra_body") != expected_extra_body:
            violations.append(f"{call_id}:extra_body_mismatch")
        if metadata.get("finish_reason") != expected_finish_reason:
            violations.append(f"{call_id}:finish_reason_mismatch")
        reasoning_bytes = _finite_or_none(metadata.get("reasoning_content_byte_count"))
        if reasoning_bytes is None or reasoning_bytes < 0 or reasoning_bytes > reasoning_limit:
            violations.append(f"{call_id}:reasoning_content_exceeded")
        duration_ms = _finite_or_none(metadata.get("duration_ms"))
        if duration_ms is not None:
            durations.append(duration_ms)
        try:
            total_tokens += max(0, int(metadata.get("total_tokens") or 0))
        except (TypeError, ValueError):
            pass

    return {
        "passed": not violations,
        "call_count": len(calls),
        "real_call_count": len(real_calls),
        "schema_valid_real_call_count": len(schema_valid_calls),
        "expected_extra_body": expected_extra_body,
        "expected_finish_reason": expected_finish_reason,
        "reasoning_content_max_bytes": reasoning_limit,
        "max_call_duration_ms": round(max(durations), 3) if durations else None,
        "total_token_usage": total_tokens,
        "violations": violations,
    }


def _active_episode_events(events: list[dict]) -> list[dict]:
    start = next((index for index, event in enumerate(events) if event.get("type") == "autonomous_start"), None)
    if start is None:
        return []
    end = next(
        (index for index in range(start, len(events)) if events[index].get("type") == "autonomous_end"),
        len(events) - 1,
    )
    return [event for event in events[start:end + 1] if isinstance(event, dict)]


def _forbidden_active_events(events: list[dict]) -> list[str]:
    forbidden = set(PROTOCOL["reset_contract"]["active_episode_forbidden_commands"])
    found = []
    for event in events:
        event_type = str(event.get("type") or "")
        data = event.get("data", {}) if isinstance(event.get("data"), dict) else {}
        command = str(data.get("command") or data.get("backend_command") or "").lower()
        if event_type in {"benchmark_reset", "reset_benchmark"}:
            found.append(event_type)
        if command in forbidden or any(token in command for token in ("time set", "gamemode", "teleport", "give")):
            found.append(command or event_type)
        action = data.get("action", {}) if isinstance(data.get("action"), dict) else {}
        params = action.get("parameters", {}) if isinstance(action.get("parameters"), dict) else {}
        message = str(params.get("message") or "").lower()
        if action.get("type") == "chat" and any(token in message for token in ("/time", "/gamemode", "/tp", "/teleport", "/give")):
            found.append(message.split()[0])
    return sorted(set(found))


def _quarantined_skill_used(events: list[dict]) -> bool:
    return any(
        event.get("type") in {"skill_selected", "skill_execution_start"}
        and str((event.get("data") or {}).get("status") or "").lower() == "quarantined"
        for event in events
    )


def _strategic_root_skill_used(events: list[dict]) -> bool:
    prohibited = set(PROTOCOL["validation_contract"]["skills"]["prohibited_root_skills"])
    return any(
        event.get("type") in {"skill_selected", "skill_execution_start"}
        and str((event.get("data") or {}).get("skill_name") or (event.get("data") or {}).get("skill") or "") in prohibited
        and (event.get("data") or {}).get("root_goal") is True
        for event in events
    )


def _action_observation(event: dict, key: str) -> bool:
    data = event.get("data", {}) if isinstance(event.get("data"), dict) else {}
    return isinstance(data.get(key), dict) and bool(data.get(key))


def _action_verifier_present(event: dict) -> bool:
    data = event.get("data", {}) if isinstance(event.get("data"), dict) else {}
    result = data.get("result", {}) if isinstance(data.get("result"), dict) else {}
    return isinstance(result.get("action_verification"), dict) and bool(result.get("action_verification"))


def _terminal_verification_matches(events: list[dict], observation: dict, terminal_state: dict) -> bool:
    verification = next(
        (
            event.get("data", {}) for event in reversed(events)
            if event.get("type") == "terminal_survival_verification" and isinstance(event.get("data"), dict)
        ),
        {},
    )
    if verification.get("passed") is not True or verification.get("source") != "machine_state":
        return False
    observed_time = _normalized_time(observation.get("time_of_day"))
    verified_time = _normalized_time(verification.get("time_of_day"))
    return bool(
        observed_time is not None
        and verified_time == observed_time
        and verification.get("health") == observation.get("health", terminal_state.get("health"))
        and verification.get("bot_connected") is True
    )


def _natural_time_progression(times: list[int]) -> bool:
    if len(times) < 2:
        return False
    maximum_gap = int(PROTOCOL["validation_contract"]["survival"]["maximum_observation_tick_gap"])
    deltas = [int((current - previous) % 24000) for previous, current in zip(times, times[1:])]
    return any(delta > 0 for delta in deltas) and all(0 <= delta <= maximum_gap for delta in deltas)


def _post_deadline_execution(events: list[dict], deadline: float | None) -> bool:
    if deadline is None:
        return True
    executable_types = {"auto_goal", "plan", "action", "skill_execution_start"}
    for event in events:
        if event.get("type") not in executable_types:
            continue
        value = _event_monotonic(event)
        if value is None or value >= deadline:
            return True
    return False


def _event_monotonic(event: dict) -> float | None:
    data = event.get("data", {}) if isinstance(event.get("data"), dict) else {}
    return _finite_or_none(event.get("monotonic_s", data.get("monotonic_s")))


def _result_duration_eligible(result: dict, task: dict) -> bool:
    duration = _finite_or_none(result.get("elapsed_s"))
    return bool(
        result.get("completed") is True
        and result.get("termination_reason") == "terminal_survival_verified"
        and duration is not None
        and duration <= float(task["max_duration_s"])
    )


def _mapping_contains(actual, expected) -> bool:
    return isinstance(actual, dict) and all(actual.get(key) == value for key, value in expected.items())


def _inventory_counts(value) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    counts = {}
    for name, raw_count in value.items():
        try:
            count = int(raw_count or 0)
        except (TypeError, ValueError):
            continue
        if name and count > 0:
            counts[str(name)] = count
    return counts


def _player_state_matches(actual: dict) -> bool:
    expected = PROTOCOL["initial_player_state"]
    return isinstance(actual, dict) and all(_number_near(actual.get(key), value, 0.25) for key, value in expected.items())


def _number_near(value, expected, tolerance: float) -> bool:
    return _finite_number(value) and abs(float(value) - float(expected)) <= float(tolerance)


def _bounded_positive(value, maximum) -> bool:
    number = _finite_or_none(value)
    limit = _finite_or_none(maximum)
    return number is not None and limit is not None and 0 < number <= limit


def _normalized_time(value) -> int | None:
    number = _finite_or_none(value)
    return int(number) % 24000 if number is not None else None


def _finite_number(value) -> bool:
    return _finite_or_none(value) is not None


def _finite_or_none(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None
