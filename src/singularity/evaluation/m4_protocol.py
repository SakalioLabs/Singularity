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
BM012_CONTRACT_PATH = Path(__file__).resolve().parent.parent / "data" / "m4_bm012_protocol.json"
BM012_CONTRACT_BYTES = BM012_CONTRACT_PATH.read_bytes()
BM012_CONTRACT = json.loads(BM012_CONTRACT_BYTES.decode("utf-8"))
BM012_CONTRACT_SHA256 = hashlib.sha256(BM012_CONTRACT_BYTES).hexdigest()
TASK_CONTRACTS_BY_ID = {"BM-012": BM012_CONTRACT}
TASK_CONTRACT_SHA256_BY_ID = {"BM-012": BM012_CONTRACT_SHA256}
M4_PLAYER_LIFECYCLE_VERIFIER_ID = str(
    PROTOCOL.get("identities", {}).get("player_lifecycle_verifier") or ""
)


def canonical_sha256(value) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_m4_player_lifecycle(
    value,
    episode_id: str = "",
    require_uninterrupted: bool = True,
) -> dict:
    """Validate one bridge-owned M4 death/respawn continuity snapshot."""
    lifecycle = value if isinstance(value, dict) else {}
    issues = []

    def require(name: str, passed: bool):
        if not passed:
            issues.append(name)

    expected_source = str(PROTOCOL["validation_contract"]["survival"]["player_lifecycle_source"])
    require("type", lifecycle.get("type") == "m4_player_lifecycle")
    require("schema_version", lifecycle.get("schema_version") == 1)
    require("verifier_id", lifecycle.get("verifier_id") == M4_PLAYER_LIFECYCLE_VERIFIER_ID)
    require("source", lifecycle.get("source") == expected_source)
    require("profile", lifecycle.get("profile") == PROTOCOL["profile"])
    require("protocol_sha256", lifecycle.get("protocol_sha256") == PROTOCOL_SHA256)
    require("tracker_id", bool(str(lifecycle.get("tracker_id") or "").strip()))
    require("episode_id", bool(str(lifecycle.get("episode_id") or "").strip()))
    if episode_id:
        require("episode_id_match", str(lifecycle.get("episode_id") or "") == str(episode_id))
    require("level_name", bool(str(lifecycle.get("level_name") or "").strip()))
    baseline_id = str(lifecycle.get("baseline_id") or "")
    require(
        "baseline_id",
        len(baseline_id) == 64 and all(character in "0123456789abcdef" for character in baseline_id),
    )
    require("baseline_established", lifecycle.get("baseline_established") is True)
    require("initial_spawn_observed", lifecycle.get("initial_spawn_observed") is True)

    integer_fields = (
        "baseline_death_count_total",
        "baseline_respawn_count_total",
        "baseline_spawn_count_total",
        "death_count_total",
        "respawn_count_total",
        "spawn_count_total",
        "death_count",
        "respawn_count",
        "spawn_count",
        "pending_respawn_count",
    )
    integers = {}
    for name in integer_fields:
        raw = lifecycle.get(name)
        passed = isinstance(raw, int) and not isinstance(raw, bool) and raw >= 0
        require(name, passed)
        if passed:
            integers[name] = raw
    for name in ("baseline_observed_at_ms", "baseline_bridge_monotonic_ms"):
        raw = lifecycle.get(name)
        require(
            name,
            isinstance(raw, (int, float))
            and not isinstance(raw, bool)
            and math.isfinite(float(raw))
            and float(raw) >= 0,
        )

    if len(integers) == len(integer_fields):
        death_delta = integers["death_count_total"] - integers["baseline_death_count_total"]
        respawn_delta = integers["respawn_count_total"] - integers["baseline_respawn_count_total"]
        spawn_delta = integers["spawn_count_total"] - integers["baseline_spawn_count_total"]
        require("death_count_delta", death_delta == integers["death_count"] and death_delta >= 0)
        require("respawn_count_delta", respawn_delta == integers["respawn_count"] and respawn_delta >= 0)
        require("spawn_count_delta", spawn_delta == integers["spawn_count"] and spawn_delta >= 0)
        require("baseline_spawn_observed", integers["baseline_spawn_count_total"] >= 1)
        require(
            "baseline_respawn_not_ahead_of_death",
            integers["baseline_respawn_count_total"] <= integers["baseline_death_count_total"],
        )
        require("respawn_not_ahead_of_death", integers["respawn_count"] <= integers["death_count"])
        require("respawn_has_spawn", integers["spawn_count"] >= integers["respawn_count"])
        require(
            "pending_respawn_count_match",
            integers["pending_respawn_count"] == integers["death_count"] - integers["respawn_count"],
        )
        require(
            "uninterrupted_consistency",
            lifecycle.get("uninterrupted") is (
                integers["death_count"] == 0 and integers["respawn_count"] == 0
            ),
        )
        require(
            "last_death_consistency",
            (integers["death_count"] == 0 and lifecycle.get("last_death") is None)
            or (
                integers["death_count"] > 0
                and _valid_lifecycle_event(lifecycle.get("last_death"), "death")
                and lifecycle["last_death"].get("death_count_total") == integers["death_count_total"]
            ),
        )
        require(
            "last_respawn_consistency",
            (integers["respawn_count"] == 0 and lifecycle.get("last_respawn") is None)
            or (
                integers["respawn_count"] > 0
                and _valid_lifecycle_event(lifecycle.get("last_respawn"), "respawn")
                and lifecycle["last_respawn"].get("respawn_count_total") == integers["respawn_count_total"]
                and lifecycle["last_respawn"].get("spawn_count_total") == integers["spawn_count_total"]
            ),
        )
        if require_uninterrupted:
            expected_deaths = int(PROTOCOL["validation_contract"]["survival"]["active_episode_death_count"])
            expected_respawns = int(PROTOCOL["validation_contract"]["survival"]["active_episode_respawn_count"])
            require("active_episode_death_count", integers["death_count"] == expected_deaths)
            require("active_episode_respawn_count", integers["respawn_count"] == expected_respawns)
            require("uninterrupted_survival", lifecycle.get("uninterrupted") is True)

    return {
        "passed": not issues,
        "issues": issues,
        "death_count": lifecycle.get("death_count"),
        "respawn_count": lifecycle.get("respawn_count"),
        "baseline_id": baseline_id,
        "episode_id": str(lifecycle.get("episode_id") or ""),
    }


def _valid_lifecycle_event(value, kind: str) -> bool:
    if not isinstance(value, dict) or value.get("kind") != kind:
        return False
    return bool(
        isinstance(value.get("event_sequence"), int)
        and not isinstance(value.get("event_sequence"), bool)
        and value["event_sequence"] > 0
        and isinstance(value.get("observed_at_ms"), (int, float))
        and not isinstance(value.get("observed_at_ms"), bool)
        and math.isfinite(float(value["observed_at_ms"]))
        and isinstance(value.get("bridge_monotonic_ms"), (int, float))
        and not isinstance(value.get("bridge_monotonic_ms"), bool)
        and math.isfinite(float(value["bridge_monotonic_ms"]))
    )


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
    survival_contract = PROTOCOL.get("validation_contract", {}).get("survival", {})
    reset_contract = PROTOCOL.get("reset_contract", {})
    if not M4_PLAYER_LIFECYCLE_VERIFIER_ID:
        issues.append("player_lifecycle_verifier_id_missing")
    if survival_contract.get("player_lifecycle_source") != "mineflayer_events":
        issues.append("player_lifecycle_source_mismatch")
    if survival_contract.get("player_lifecycle_observation_required") is not True:
        issues.append("player_lifecycle_observation_must_be_required")
    if survival_contract.get("player_lifecycle_event_required") is not True:
        issues.append("player_lifecycle_event_must_be_required")
    if survival_contract.get("active_episode_death_count") != 0:
        issues.append("active_episode_deaths_must_be_zero")
    if survival_contract.get("active_episode_respawn_count") != 0:
        issues.append("active_episode_respawns_must_be_zero")
    if survival_contract.get("uninterrupted_survival_required") is not True:
        issues.append("uninterrupted_survival_must_be_required")
    if reset_contract.get("establish_player_lifecycle_baseline") is not True:
        issues.append("player_lifecycle_baseline_must_be_reset")
    if reset_contract.get("player_lifecycle_source") != "mineflayer_events":
        issues.append("reset_player_lifecycle_source_mismatch")
    return {
        "passed": not issues,
        "issues": issues,
        "protocol_sha256": PROTOCOL_SHA256,
        **expected,
    }


def task_spec(task_id: str) -> dict:
    return TASKS_BY_ID.get(str(task_id or "").upper().strip(), {})


def task_contract(task_id: str) -> dict:
    return TASK_CONTRACTS_BY_ID.get(str(task_id or "").upper().strip(), {})


def task_contract_sha256(task_id: str) -> str:
    return TASK_CONTRACT_SHA256_BY_ID.get(str(task_id or "").upper().strip(), "")


def task_contract_integrity_report(task_id: str) -> dict:
    normalized = str(task_id or "").upper().strip()
    if normalized == "BM-011":
        return {"passed": True, "issues": [], "task_id": normalized, "contract_sha256": ""}
    contract = task_contract(normalized)
    task = task_spec(normalized)
    issues = []

    def require(name: str, passed: bool):
        if not passed:
            issues.append(name)

    require("contract_present", bool(contract))
    require("contract_type", contract.get("type") == "m4_task_contract")
    require("contract_schema", contract.get("schema_version") == 1)
    require("contract_profile", contract.get("profile") == PROTOCOL["profile"])
    require("contract_base_protocol", contract.get("base_protocol_sha256") == PROTOCOL_SHA256)
    require("contract_task", contract.get("task_id") == normalized)
    require("task_present", bool(task))
    require("task_name", contract.get("name") == task.get("name"))
    require("task_terminal_goal", contract.get("terminal_goal") == task.get("terminal_goal"))
    require("task_duration", contract.get("max_duration_s") == task.get("max_duration_s"))
    require("task_success_criteria", contract.get("success_criteria") == task.get("success_criteria"))
    require(
        "task_goal_limit",
        contract.get("max_autonomous_goals") == PROTOCOL["limits"]["max_autonomous_goals"],
    )
    require(
        "task_cycle_limit",
        contract.get("max_cycles_per_goal") == PROTOCOL["limits"]["max_cycles_per_goal"],
    )
    require(
        "task_total_cycle_limit",
        contract.get("max_total_cycles") == PROTOCOL["limits"]["max_total_cycles"],
    )
    verifier = contract.get("terminal_verifier", {})
    require("terminal_verifier_id", bool(str(verifier.get("id") or "")))
    require("terminal_event_type", verifier.get("event_type") == "terminal_resource_verification")
    require("terminal_source", verifier.get("source") == "machine_state")
    require("terminal_reason", verifier.get("termination_reason") == "terminal_task_verified")
    require("source_action", verifier.get("required_action_type") == "dig")
    require("source_blocks", set(verifier.get("source_blocks", [])) == {"iron_ore", "deepslate_iron_ore"})
    return {
        "passed": not issues,
        "issues": issues,
        "task_id": normalized,
        "contract_id": str(contract.get("id") or ""),
        "contract_sha256": task_contract_sha256(normalized),
    }


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
    task_id = str(task_id or "").upper().strip()
    contract = task_contract(task_id)
    expected_initial_time = contract.get("initial_time_of_day", PROTOCOL["initial_time_of_day"])
    issues = []
    checks = []

    def require(name: str, passed: bool, detail=""):
        checks.append({"name": name, "passed": bool(passed), "detail": detail})
        if not passed:
            issues.append(name)

    require("preflight_type", preflight.get("type") == "m4_preflight")
    require("preflight_passed", preflight.get("passed") is True)
    require("task_id", str(preflight.get("task_id") or "").upper().strip() == task_id)
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
        _number_near(preflight.get("initial_time_of_day"), expected_initial_time, 600),
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
    if contract:
        integrity = task_contract_integrity_report(task_id)
        require("task_contract_integrity", integrity["passed"], integrity["issues"])
        require("task_contract_id", preflight.get("task_contract_id") == contract.get("id"))
        require("task_contract_sha256", preflight.get("task_contract_sha256") == task_contract_sha256(task_id))
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
    lifecycle_report = validate_m4_player_lifecycle(
        preflight.get("player_lifecycle_baseline"),
        episode_id=str(preflight.get("episode_id") or ""),
        require_uninterrupted=True,
    )
    require("player_lifecycle_baseline", lifecycle_report["passed"], lifecycle_report["issues"])
    return {"passed": not issues, "issues": issues, "checks": checks}


def evaluate_m4_episode(
    events: list[dict],
    result: dict,
    preflight: dict,
    manifest: dict,
    task_id: str = "",
) -> dict:
    normalized = str(
        task_id
        or manifest.get("task_id")
        or preflight.get("task_id")
        or result.get("task_id")
        or ""
    ).upper().strip()
    if normalized not in {"BM-011", "BM-012"}:
        return {
            "type": "m4_episode_eligibility",
            "task_id": normalized,
            "profile": PROTOCOL["profile"],
            "protocol_sha256": PROTOCOL_SHA256,
            "eligible": False,
            "success": False,
            "issues": ["unsupported_task"],
            "checks": [{"name": "supported_task", "passed": False, "detail": normalized}],
            "evidence": {},
        }
    return _evaluate_m4_episode(events, result, preflight, manifest, normalized)


def evaluate_bm011_episode(
    events: list[dict],
    result: dict,
    preflight: dict,
    manifest: dict,
) -> dict:
    return _evaluate_m4_episode(events, result, preflight, manifest, "BM-011")


def evaluate_bm012_episode(
    events: list[dict],
    result: dict,
    preflight: dict,
    manifest: dict,
) -> dict:
    return _evaluate_m4_episode(events, result, preflight, manifest, "BM-012")


def _evaluate_m4_episode(
    events: list[dict],
    result: dict,
    preflight: dict,
    manifest: dict,
    task_id: str,
) -> dict:
    """Independently evaluate one M4 session; textual completion is never sufficient."""
    issues = []
    checks = []

    def require(name: str, passed: bool, detail=""):
        checks.append({"name": name, "passed": bool(passed), "detail": detail})
        if not passed:
            issues.append(name)

    preflight_report = validate_preflight(preflight, task_id)
    require("preflight_eligible", preflight_report["passed"], preflight_report["issues"])
    integrity = protocol_integrity_report()
    require("protocol_integrity", integrity["passed"], integrity["issues"])

    require("manifest_type", manifest.get("type") == "m4_runtime_manifest")
    require("manifest_task", manifest.get("task_id") == task_id)
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
    task_limit = task_spec(task_id)
    require(
        "manifest_runtime_limits",
        isinstance(runtime_limits, dict)
        and _number_near(runtime_limits.get("max_duration_s"), task_limit.get("max_duration_s"), 0.0)
        and _number_near(runtime_limits.get("max_goals"), PROTOCOL["limits"]["max_autonomous_goals"], 0.0)
        and _number_near(runtime_limits.get("max_cycles_per_goal"), PROTOCOL["limits"]["max_cycles_per_goal"], 0.0),
        runtime_limits,
    )
    contract = task_contract(task_id)
    if contract:
        contract_integrity = task_contract_integrity_report(task_id)
        require("task_contract_integrity", contract_integrity["passed"], contract_integrity["issues"])
        require("manifest_task_contract_id", manifest.get("task_contract_id") == contract.get("id"))
        require(
            "manifest_task_contract_sha256",
            manifest.get("task_contract_sha256") == task_contract_sha256(task_id),
        )

    evidence_hashes = result.get("evidence_hashes", {}) if isinstance(result.get("evidence_hashes"), dict) else {}
    unhashed_result = dict(result)
    unhashed_result.pop("evidence_hashes", None)
    require("preflight_content_hash", evidence_hashes.get("preflight_sha256") == canonical_sha256(preflight))
    require("manifest_content_hash", evidence_hashes.get("manifest_sha256") == canonical_sha256(manifest))
    require("session_content_hash", evidence_hashes.get("session_sha256") == canonical_sha256(events))
    require("result_content_hash", evidence_hashes.get("result_sha256") == canonical_sha256(unhashed_result))
    if task_id == "BM-012":
        require("result_type", result.get("type") == "m4_episode_result")
        require("result_task", result.get("task_id") == task_id)
        require("result_profile", result.get("profile") == PROTOCOL["profile"])

    event_types = [str(event.get("type") or "") for event in events if isinstance(event, dict)]
    required_events = list(PROTOCOL["validation_contract"]["autonomy"]["required_events"])
    if task_id == "BM-012":
        required_events = [
            contract["terminal_verifier"]["event_type"]
            if event_type == "terminal_survival_verification"
            else event_type
            for event_type in required_events
        ]
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
    lifecycle_values = [observation.get("player_lifecycle") for observation in observations]
    lifecycle_reports = [
        validate_m4_player_lifecycle(
            value,
            episode_id=str(manifest.get("episode_id") or ""),
            require_uninterrupted=False,
        )
        for value in lifecycle_values
    ]
    lifecycle_events = [
        event.get("data", {}) for event in active_events
        if event.get("type") == "m4_player_lifecycle" and isinstance(event.get("data"), dict)
    ]
    lifecycle_event_reports = [
        validate_m4_player_lifecycle(
            value,
            episode_id=str(manifest.get("episode_id") or ""),
            require_uninterrupted=False,
        )
        for value in lifecycle_events
    ]
    lifecycle_event_death_counts = [value.get("death_count") for value in lifecycle_events]
    lifecycle_event_respawn_counts = [value.get("respawn_count") for value in lifecycle_events]
    lifecycle_complete = bool(observations) and all(isinstance(value, dict) for value in lifecycle_values)
    lifecycle_valid = lifecycle_complete and all(report["passed"] for report in lifecycle_reports)
    lifecycle_baseline = preflight.get("player_lifecycle_baseline", {})
    expected_lifecycle_baseline = _lifecycle_baseline_signature(lifecycle_baseline)
    lifecycle_baselines_match = bool(expected_lifecycle_baseline) and all(
        _lifecycle_baseline_signature(value) == expected_lifecycle_baseline
        for value in lifecycle_values
        if isinstance(value, dict)
    ) and sum(isinstance(value, dict) for value in lifecycle_values) == len(lifecycle_values)
    death_counts = [value.get("death_count") for value in lifecycle_values if isinstance(value, dict)]
    respawn_counts = [value.get("respawn_count") for value in lifecycle_values if isinstance(value, dict)]
    lifecycle_counts_monotonic = bool(death_counts) and bool(respawn_counts) and all(
        isinstance(value, int) and not isinstance(value, bool) for value in death_counts + respawn_counts
    ) and all(current >= previous for previous, current in zip(death_counts, death_counts[1:])) and all(
        current >= previous for previous, current in zip(respawn_counts, respawn_counts[1:])
    )
    lifecycle_event_baselines_match = bool(lifecycle_events) and all(
        _lifecycle_baseline_signature(value) == expected_lifecycle_baseline
        for value in lifecycle_events
    )
    lifecycle_event_counts_monotonic = bool(lifecycle_event_death_counts) and bool(
        lifecycle_event_respawn_counts
    ) and all(
        isinstance(value, int) and not isinstance(value, bool)
        for value in lifecycle_event_death_counts + lifecycle_event_respawn_counts
    ) and all(
        current >= previous
        for previous, current in zip(lifecycle_event_death_counts, lifecycle_event_death_counts[1:])
    ) and all(
        current >= previous
        for previous, current in zip(lifecycle_event_respawn_counts, lifecycle_event_respawn_counts[1:])
    )
    require("player_lifecycle_observation_complete", lifecycle_complete)
    require(
        "player_lifecycle_observation_valid",
        lifecycle_valid,
        [report["issues"] for report in lifecycle_reports if not report["passed"]],
    )
    require("player_lifecycle_baseline_consistent", lifecycle_baselines_match)
    require("player_lifecycle_counts_monotonic", lifecycle_counts_monotonic)
    require("player_lifecycle_event_present", bool(lifecycle_events))
    require(
        "player_lifecycle_event_valid",
        bool(lifecycle_event_reports) and all(report["passed"] for report in lifecycle_event_reports),
        [report["issues"] for report in lifecycle_event_reports if not report["passed"]],
    )
    require("player_lifecycle_event_baseline_consistent", lifecycle_event_baselines_match)
    require("player_lifecycle_event_counts_monotonic", lifecycle_event_counts_monotonic)
    all_death_counts = death_counts + lifecycle_event_death_counts
    all_respawn_counts = respawn_counts + lifecycle_event_respawn_counts
    death_counts_valid = bool(all_death_counts) and all(
        isinstance(value, int) and not isinstance(value, bool)
        for value in all_death_counts
    )
    respawn_counts_valid = bool(all_respawn_counts) and all(
        isinstance(value, int) and not isinstance(value, bool)
        for value in all_respawn_counts
    )
    maximum_death_count = max(all_death_counts) if death_counts_valid else None
    maximum_respawn_count = max(all_respawn_counts) if respawn_counts_valid else None
    require(
        "active_episode_death_absent",
        death_counts_valid and maximum_death_count == 0,
        all_death_counts,
    )
    require(
        "active_episode_respawn_absent",
        respawn_counts_valid and maximum_respawn_count == 0,
        all_respawn_counts,
    )
    require(
        "uninterrupted_survival",
        lifecycle_valid and all(value.get("uninterrupted") is True for value in lifecycle_values),
    )
    times = [_normalized_time(obs.get("time_of_day")) for obs in observations]
    times = [value for value in times if value is not None]
    night_index = None
    dawn_index = None
    if task_id == "BM-011":
        night_index = next((index for index, value in enumerate(times) if 12000 <= value < 23000), None)
        dawn_index = next(
            (
                index
                for index, value in enumerate(times)
                if night_index is not None and index > night_index and (value >= 23000 or value < 1000)
            ),
            None,
        )
        require("night_observed", night_index is not None)
        require("next_dawn_observed", dawn_index is not None)
    require("natural_time_progression", _natural_time_progression(times))

    terminal_observation = observations[-1] if observations else {}
    terminal_state = result.get("terminal_state", {}) if isinstance(result.get("terminal_state"), dict) else {}
    terminal_lifecycle = terminal_state.get("player_lifecycle")
    terminal_lifecycle_report = validate_m4_player_lifecycle(
        terminal_lifecycle,
        episode_id=str(manifest.get("episode_id") or ""),
        require_uninterrupted=True,
    )
    require(
        "terminal_player_lifecycle",
        terminal_lifecycle_report["passed"]
        and _lifecycle_terminal_signature(terminal_lifecycle)
        == _lifecycle_terminal_signature(terminal_observation.get("player_lifecycle")),
        terminal_lifecycle_report["issues"],
    )
    health = terminal_observation.get("health", terminal_state.get("health", 0))
    require("terminal_health", _finite_number(health) and float(health) > 0)
    require("terminal_bot_connected", terminal_state.get("bot_connected") is True)
    resource_acquisition = {}
    if task_id == "BM-011":
        terminal_machine_verified = _terminal_verification_matches(
            active_events,
            terminal_observation,
            terminal_state,
        )
    else:
        resource_acquisition = _resource_acquisition_report(
            active_events,
            observations,
            terminal_state,
            contract,
        )
        require(
            "resource_initial_inventory_empty",
            resource_acquisition.get("initial_target_count") == 0,
            resource_acquisition,
        )
        require(
            "resource_terminal_inventory_target",
            resource_acquisition.get("terminal_target_passed") is True,
            resource_acquisition,
        )
        require(
            "resource_successful_source_actions",
            resource_acquisition.get("successful_source_action_count", 0)
            >= int(contract["terminal_verifier"]["successful_source_action_count_minimum"]),
            resource_acquisition,
        )
        require(
            "resource_positive_inventory_delta",
            resource_acquisition.get("positive_inventory_delta_passed") is True,
            resource_acquisition,
        )
        terminal_machine_verified = _terminal_resource_verification_matches(
            active_events,
            terminal_observation,
            terminal_state,
            contract,
        )
    require("terminal_machine_verification", terminal_machine_verified)

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
    task = task_spec(task_id)
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
    require("result_duration_eligible", _result_duration_eligible(result, task, task_id))
    require("no_post_deadline_execution", not _post_deadline_execution(active_events, deadline))

    success = not issues
    return {
        "type": "m4_episode_eligibility",
        "task_id": task_id,
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
            "task_contract_id": str(contract.get("id") or ""),
            "task_contract_sha256": task_contract_sha256(task_id),
            "resource_acquisition": resource_acquisition,
            "player_lifecycle_verifier_id": M4_PLAYER_LIFECYCLE_VERIFIER_ID,
            "player_lifecycle_event_count": len(lifecycle_events),
            "maximum_death_count": maximum_death_count,
            "maximum_respawn_count": maximum_respawn_count,
            "uninterrupted_survival": bool(
                lifecycle_valid
                and maximum_death_count == 0
                and maximum_respawn_count == 0
            ),
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


def _lifecycle_baseline_signature(value) -> tuple:
    lifecycle = value if isinstance(value, dict) else {}
    fields = (
        "verifier_id",
        "source",
        "profile",
        "protocol_sha256",
        "tracker_id",
        "episode_id",
        "level_name",
        "baseline_id",
        "baseline_death_count_total",
        "baseline_respawn_count_total",
        "baseline_spawn_count_total",
        "baseline_observed_at_ms",
        "baseline_bridge_monotonic_ms",
    )
    signature = tuple(lifecycle.get(name) for name in fields)
    return signature if all(value is not None and value != "" for value in signature) else ()


def _lifecycle_terminal_signature(value) -> tuple:
    lifecycle = value if isinstance(value, dict) else {}
    baseline = _lifecycle_baseline_signature(lifecycle)
    if not baseline:
        return ()
    return baseline + tuple(
        lifecycle.get(name)
        for name in (
            "death_count_total",
            "respawn_count_total",
            "spawn_count_total",
            "death_count",
            "respawn_count",
            "spawn_count",
            "pending_respawn_count",
            "uninterrupted",
        )
    )


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
    observed_lifecycle = observation.get("player_lifecycle")
    terminal_lifecycle = terminal_state.get("player_lifecycle")
    verified_lifecycle = verification.get("player_lifecycle")
    lifecycle_report = validate_m4_player_lifecycle(
        verified_lifecycle,
        episode_id=str((observed_lifecycle or {}).get("episode_id") or ""),
        require_uninterrupted=True,
    )
    return bool(
        observed_time is not None
        and verified_time == observed_time
        and verification.get("health") == observation.get("health", terminal_state.get("health"))
        and verification.get("bot_connected") is True
        and lifecycle_report["passed"]
        and _lifecycle_terminal_signature(verified_lifecycle)
        == _lifecycle_terminal_signature(observed_lifecycle)
        == _lifecycle_terminal_signature(terminal_lifecycle)
    )


def _terminal_resource_verification_matches(
    events: list[dict],
    observation: dict,
    terminal_state: dict,
    contract: dict,
) -> bool:
    verifier = contract.get("terminal_verifier", {}) if isinstance(contract, dict) else {}
    event_type = str(verifier.get("event_type") or "")
    verification = next(
        (
            event.get("data", {})
            for event in reversed(events)
            if event.get("type") == event_type and isinstance(event.get("data"), dict)
        ),
        {},
    )
    observed_inventory = _inventory_counts(observation.get("inventory"))
    terminal_inventory = _inventory_counts(terminal_state.get("inventory"))
    verified_inventory = _inventory_counts(verification.get("inventory"))
    qualifying_item = str(verification.get("qualifying_item") or "")
    criteria = contract.get("success_criteria", {}).get("inventory_any", {})
    required_count = criteria.get(qualifying_item)
    observed_lifecycle = observation.get("player_lifecycle")
    terminal_lifecycle = terminal_state.get("player_lifecycle")
    verified_lifecycle = verification.get("player_lifecycle")
    lifecycle_report = validate_m4_player_lifecycle(
        verified_lifecycle,
        episode_id=str((observed_lifecycle or {}).get("episode_id") or ""),
        require_uninterrupted=True,
    )
    return bool(
        verification.get("type") == verifier.get("payload_type")
        and verification.get("passed") is True
        and verification.get("source") == verifier.get("source")
        and verification.get("task_id") == contract.get("task_id")
        and verification.get("verifier_id") == verifier.get("id")
        and verification.get("task_contract_id") == contract.get("id")
        and verification.get("task_contract_sha256") == task_contract_sha256(contract.get("task_id"))
        and qualifying_item in criteria
        and isinstance(required_count, int)
        and not isinstance(required_count, bool)
        and verification.get("required_count") == required_count
        and verification.get("observed_count") == observed_inventory.get(qualifying_item)
        and observed_inventory.get(qualifying_item, 0) >= required_count
        and observed_inventory == terminal_inventory == verified_inventory
        and verification.get("health") == observation.get("health", terminal_state.get("health"))
        and verification.get("bot_connected") is True
        and lifecycle_report["passed"]
        and _lifecycle_terminal_signature(verified_lifecycle)
        == _lifecycle_terminal_signature(observed_lifecycle)
        == _lifecycle_terminal_signature(terminal_lifecycle)
    )


def _resource_acquisition_report(
    events: list[dict],
    observations: list[dict],
    terminal_state: dict,
    contract: dict,
) -> dict:
    criteria = contract.get("success_criteria", {}).get("inventory_any", {})
    target_items = tuple(str(item) for item in criteria)
    source_blocks = set(contract.get("terminal_verifier", {}).get("source_blocks", []))
    initial_inventory = _inventory_counts((observations[0] if observations else {}).get("inventory"))
    terminal_observation = observations[-1] if observations else {}
    terminal_inventory = _inventory_counts(
        terminal_observation.get("inventory", terminal_state.get("inventory"))
    )
    source_actions = []
    for index, event in enumerate(events):
        if event.get("type") != "action" or not isinstance(event.get("data"), dict):
            continue
        data = event["data"]
        action = data.get("action", {}) if isinstance(data.get("action"), dict) else {}
        result = data.get("result", {}) if isinstance(data.get("result"), dict) else {}
        before_block = result.get("target_block_before", {})
        before_block = before_block if isinstance(before_block, dict) else {}
        if (
            action.get("type") != contract.get("terminal_verifier", {}).get("required_action_type")
            or result.get("success") is not True
            or result.get("block_removed") is not True
            or str(before_block.get("name") or "") not in source_blocks
        ):
            continue
        source_actions.append({
            "event_index": index + 1,
            "block": str(before_block.get("name") or ""),
            "position": before_block.get("position", {}),
        })
    qualifying_items = [
        item
        for item, required in criteria.items()
        if terminal_inventory.get(item, 0) >= int(required)
    ]
    positive_delta = {
        item: terminal_inventory.get(item, 0) - initial_inventory.get(item, 0)
        for item in target_items
    }
    return {
        "target_items": list(target_items),
        "initial_inventory": {item: initial_inventory.get(item, 0) for item in target_items},
        "terminal_inventory": {item: terminal_inventory.get(item, 0) for item in target_items},
        "initial_target_count": sum(initial_inventory.get(item, 0) for item in target_items),
        "qualifying_items": qualifying_items,
        "terminal_target_passed": bool(qualifying_items),
        "positive_inventory_delta": positive_delta,
        "positive_inventory_delta_passed": any(
            positive_delta.get(item, 0) >= int(criteria[item]) for item in qualifying_items
        ),
        "successful_source_action_count": len(source_actions),
        "successful_source_actions": source_actions,
    }


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


def _result_duration_eligible(result: dict, task: dict, task_id: str = "BM-011") -> bool:
    duration = _finite_or_none(result.get("elapsed_s"))
    contract = task_contract(task_id)
    expected_reason = (
        contract.get("terminal_verifier", {}).get("termination_reason")
        if contract
        else "terminal_survival_verified"
    )
    return bool(
        result.get("completed") is True
        and result.get("termination_reason") == expected_reason
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
