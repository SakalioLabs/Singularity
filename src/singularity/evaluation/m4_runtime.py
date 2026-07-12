"""M4 live-runtime evidence builders and preparation diagnostics."""

from __future__ import annotations

import json
import math
import platform
from collections import Counter

from singularity.evaluation.m4_protocol import (
    PROTOCOL,
    PROTOCOL_SHA256,
    canonical_sha256,
    planner_provider_controls_report,
    task_contract,
    task_contract_sha256,
    validate_preflight,
)


def runtime_controls_from_config(config) -> dict:
    """Return the auditable, secret-free M4 controls from the live Config."""
    mode = str(getattr(config, "skill_execution_mode", "off") or "off").strip().lower()
    return {
        "skill_execution_mode": mode,
        "learned_executable_skills_enabled": mode in {"evaluation", "runtime"},
        "quarantined_skills_enabled": False,
        "policy_skills_enabled": bool(getattr(config, "enable_policy_skills", True)),
        "skill_memory_context_enabled": bool(getattr(config, "enable_skill_memory_context", True)),
        "memory_persistence_enabled": bool(getattr(config, "enable_memory_persistence", True)),
        "vision_enabled": bool(getattr(config, "enable_vision_analysis", True)),
        "visual_action_grounding_enabled": bool(getattr(config, "enable_visual_action_grounding", True)),
        "screenshot_capture_enabled": bool(getattr(config, "enable_screenshot_capture", False)),
        "self_evolution_policy_enabled": bool(getattr(config, "enable_self_evolution_policy", True)),
        "world_model_curriculum_feedback_enabled": bool(
            getattr(config, "enable_world_model_curriculum_feedback", True)
        ),
        "multi_agent_enabled": False,
        "autocurriculum_enabled": bool(getattr(config, "enable_autocurriculum", True)),
        "goal_verification_enabled": bool(getattr(config, "enable_goal_verification", True)),
        "action_verification_enabled": bool(getattr(config, "enable_action_verification", True)),
        "action_verification_enforced": bool(getattr(config, "enforce_action_verification", True)),
    }


def build_m4_preflight(
    protocol_status: dict,
    reset_evidence: dict,
    episode_id: str,
    level_name: str,
    fresh_episode: bool,
    task_id: str = "BM-011",
) -> dict:
    """Build the canonical preflight only from runtime and observed reset evidence."""
    status = protocol_status if isinstance(protocol_status, dict) else {}
    reset = reset_evidence if isinstance(reset_evidence, dict) else {}
    normalized_task_id = str(task_id or "").upper().strip()
    contract = task_contract(normalized_task_id)
    status_contracts = status.get("task_contracts", {}) if isinstance(status.get("task_contracts"), dict) else {}
    status_contract = status_contracts.get(normalized_task_id, {})
    status_contract = status_contract if isinstance(status_contract, dict) else {}
    state = reset.get("after_state", {}) if isinstance(reset.get("after_state"), dict) else {}
    dependencies = status.get("dependencies", {}) if isinstance(status.get("dependencies"), dict) else {}
    runtime_versions = {
        "python": platform.python_version(),
        "node": str((status.get("runtime_versions") or {}).get("node") or ""),
        "mineflayer": str(dependencies.get("mineflayer") or ""),
        "mineflayer_pathfinder": str(dependencies.get("mineflayer-pathfinder") or ""),
        "minecraft_data": str(dependencies.get("minecraft-data") or ""),
    }
    identities = {
        "agent": str(status.get("agent_id") or ""),
        "goal_generator": str(status.get("goal_generator_id") or ""),
        "curriculum": str(status.get("curriculum_id") or ""),
        "planner": str(status.get("planner_id") or ""),
        "action_backend": str(status.get("action_backend_id") or ""),
        "goal_verifier": str(status.get("verifier_id") or ""),
        "runtime_interrupt": str(status.get("runtime_interrupt_id") or ""),
        "skill_runtime_profile": str(status.get("skill_runtime_profile_id") or ""),
        "player_lifecycle_verifier": str(status.get("player_lifecycle_verifier_id") or ""),
    }
    source_checks = {
        "status_profile": status.get("profile") == PROTOCOL["profile"],
        "status_protocol": status.get("protocol_sha256") == PROTOCOL_SHA256,
        "status_episode": str(status.get("episode_id") or "") == str(episode_id or ""),
        "status_level": str(status.get("level_name") or "") == str(level_name or ""),
        "status_seed": str(status.get("seed") or "") == PROTOCOL["world_seed"],
        "status_server_jar": status.get("server_jar_sha256") == PROTOCOL["server_jar_sha256"],
        "status_player_lifecycle_supported": status.get("player_lifecycle_supported") is True,
        "status_player_lifecycle_source": status.get("player_lifecycle_source")
        == PROTOCOL["validation_contract"]["survival"]["player_lifecycle_source"],
        "reset_profile": reset.get("profile") == PROTOCOL["profile"],
        "reset_protocol": reset.get("protocol_sha256") == PROTOCOL_SHA256,
        "reset_contract": reset.get("reset_protocol_sha256") == PROTOCOL["reset_protocol_sha256"],
        "reset_validation": reset.get("validation_protocol_sha256") == PROTOCOL["validation_protocol_sha256"],
        "reset_task": str(reset.get("task_id") or "").upper() == str(task_id or "").upper(),
        "reset_episode": str(reset.get("episode_id") or "") == str(episode_id or ""),
        "reset_level": str(reset.get("level_name") or "") == str(level_name or ""),
        "reset_seed": str(reset.get("seed") or "") == PROTOCOL["world_seed"],
        "reset_server_jar": reset.get("server_jar_sha256") == PROTOCOL["server_jar_sha256"],
        "reset_player_lifecycle": isinstance(reset.get("player_lifecycle"), dict)
        and reset["player_lifecycle"].get("baseline_established") is True
        and reset["player_lifecycle"].get("episode_id") == str(episode_id or "")
        and reset["player_lifecycle"].get("protocol_sha256") == PROTOCOL_SHA256
        and reset["player_lifecycle"].get("death_count") == 0
        and reset["player_lifecycle"].get("respawn_count") == 0
        and reset["player_lifecycle"].get("uninterrupted") is True,
    }
    if contract:
        source_checks.update({
            "status_task_contract_id": status_contract.get("id") == contract.get("id"),
            "status_task_contract_sha256": status_contract.get("sha256")
            == task_contract_sha256(normalized_task_id),
            "reset_task_contract_id": reset.get("task_contract_id") == contract.get("id"),
            "reset_task_contract_sha256": reset.get("task_contract_sha256")
            == task_contract_sha256(normalized_task_id),
        })
    preliminary_pass = bool(
        status.get("success") is True
        and status.get("configured") is True
        and reset.get("success") is True
        and fresh_episode
        and all(source_checks.values())
    )
    preflight = {
        "type": "m4_preflight",
        "schema_version": 1,
        "passed": preliminary_pass,
        "task_id": normalized_task_id,
        "profile": str(status.get("profile") or ""),
        "protocol_sha256": str(status.get("protocol_sha256") or ""),
        "server_jar_sha256": str(status.get("server_jar_sha256") or ""),
        "world_seed": str(status.get("seed") or ""),
        "fresh_episode": bool(fresh_episode),
        "game_mode": str(state.get("game_mode") or ""),
        "difficulty": str(state.get("difficulty") or ""),
        "initial_inventory": dict(state.get("inventory", {}) or {}),
        "initial_player_state": {
            "health": state.get("health"),
            "food": state.get("food"),
            "saturation": state.get("food_saturation"),
        },
        "initial_time_of_day": state.get("time_of_day"),
        "weather": str(state.get("weather") or ""),
        "gamerules": dict(reset.get("gamerules", {}) or {}),
        "runtime_versions": runtime_versions,
        "llm": dict(status.get("llm", {}) or {}),
        "identities": identities,
        "runtime_controls": dict(status.get("runtime_controls", {}) or {}),
        "task_contract_id": str(contract.get("id") or ""),
        "task_contract_sha256": task_contract_sha256(normalized_task_id),
        "player_lifecycle_baseline": dict(reset.get("player_lifecycle", {}) or {}),
        "episode_id": str(episode_id or ""),
        "level_name": str(level_name or ""),
        "reset_evidence_sha256": canonical_sha256(reset),
        "protocol_status_sha256": canonical_sha256(status),
        "reset_checks": dict(reset.get("checks", {}) or {}),
        "source_checks": source_checks,
    }
    validation = validate_preflight(preflight, task_id=preflight["task_id"])
    preflight["passed"] = preliminary_pass and validation["passed"]
    preflight["validation"] = validation
    return preflight


def build_m4_runtime_manifest(
    preflight: dict,
    session_id: str,
    episode_started_monotonic: float,
    episode_deadline_monotonic: float,
    episode_ended_monotonic: float,
    evidence_paths: dict | None = None,
    runtime_controls: dict | None = None,
    runtime_limits: dict | None = None,
) -> dict:
    controls = dict(runtime_controls or {})
    task_id = str(preflight.get("task_id") or "BM-011").upper().strip()
    contract = task_contract(task_id)
    return {
        "type": "m4_runtime_manifest",
        "schema_version": 1,
        "task_id": task_id,
        "profile": PROTOCOL["profile"],
        "protocol_sha256": PROTOCOL_SHA256,
        "reset_protocol_sha256": PROTOCOL["reset_protocol_sha256"],
        "validation_protocol_sha256": PROTOCOL["validation_protocol_sha256"],
        "deadline_policy_id": PROTOCOL["deadline_policy"]["id"],
        "episode_id": str(preflight.get("episode_id") or ""),
        "session_id": str(session_id or ""),
        "level_name": str(preflight.get("level_name") or ""),
        "world_seed": PROTOCOL["world_seed"],
        "episode_started_monotonic": float(episode_started_monotonic),
        "episode_deadline_monotonic": float(episode_deadline_monotonic),
        "episode_ended_monotonic": float(episode_ended_monotonic),
        "runtime_versions": dict(preflight.get("runtime_versions", {}) or {}),
        "llm": dict(PROTOCOL["llm"]),
        "identities": dict(PROTOCOL["identities"]),
        "runtime_controls": controls,
        "task_contract_id": str(contract.get("id") or ""),
        "task_contract_sha256": task_contract_sha256(task_id),
        "skill_execution_mode": controls.get("skill_execution_mode"),
        "learned_executable_skills_enabled": controls.get("learned_executable_skills_enabled"),
        "quarantined_skills_enabled": controls.get("quarantined_skills_enabled"),
        "vision_enabled": controls.get("vision_enabled"),
        "multi_agent_enabled": controls.get("multi_agent_enabled"),
        "runtime_limits": dict(runtime_limits or {}),
        "evidence_paths": dict(evidence_paths or {}),
    }


def attach_m4_evidence_hashes(
    result: dict,
    preflight: dict,
    manifest: dict,
    events: list[dict],
) -> dict:
    payload = dict(result)
    payload.pop("evidence_hashes", None)
    payload["evidence_hashes"] = {
        "preflight_sha256": canonical_sha256(preflight),
        "manifest_sha256": canonical_sha256(manifest),
        "session_sha256": canonical_sha256(events),
        "result_sha256": canonical_sha256(payload),
    }
    return payload


def build_m4_preparation_report(
    events: list[dict],
    result: dict,
    preflight: dict,
    manifest: dict,
    eligibility: dict,
) -> dict:
    active = _active_events(events)
    observations = [
        event.get("data", {}) for event in active
        if event.get("type") == "observation" and isinstance(event.get("data"), dict)
    ]
    goals = [
        event.get("data", {}) for event in active
        if event.get("type") == "auto_goal" and isinstance(event.get("data"), dict)
    ]
    actions = [
        event.get("data", {}) for event in active
        if event.get("type") == "action" and isinstance(event.get("data"), dict)
    ]
    plans = [
        event.get("data", {}) for event in active
        if event.get("type") == "plan" and isinstance(event.get("data"), dict)
    ]
    state_samples = _state_samples(active, result)
    before = observations[0] if observations else {}
    after = state_samples[-1] if state_samples else before
    inventory_delta = _positive_inventory_delta(before.get("inventory", {}), after.get("inventory", {}))
    successful_actions = [action for action in actions if (action.get("result") or {}).get("success") is True]
    crafting_actions = [action for action in actions if (action.get("action") or {}).get("type") == "craft"]
    shelter_goals = [
        goal for goal in goals
        if any(token in str(goal.get("goal") or "").lower() for token in ("shelter", "nightfall", "safe point"))
    ]
    shelter_plans = [plan for plan in plans if _contains_shelter_intent(plan)]
    world_block_delta = _verified_world_block_delta(actions)
    pre_dusk_samples = [sample for sample in state_samples if _is_pre_dusk_state(sample)]
    pre_dusk_after = pre_dusk_samples[-1] if pre_dusk_samples else before
    pre_dusk_inventory_delta = _positive_inventory_delta(
        before.get("inventory", {}),
        pre_dusk_after.get("inventory", {}),
    )
    pre_dusk_world_block_delta = _verified_world_block_delta(actions, pre_dusk_only=True)
    goal_titles = [str(goal.get("goal") or "") for goal in goals if goal.get("goal")]
    repeated_goal_max = _max_consecutive(goal_titles)
    plan_signatures = [
        canonical_sha256({
            "status": plan.get("status"),
            "actions": plan.get("actions", []),
        })
        for plan in plans
    ]
    failed_action_signatures = [
        _action_signature(action.get("action", {}))
        for action in actions
        if (action.get("result") or {}).get("success") is not True
    ]
    no_progress_transitions = sum(
        1 for previous, current in zip(observations, observations[1:])
        if not _observable_progress(previous, current)
    )
    planner_controls = planner_provider_controls_report(active)
    machine_visible_progress = bool(inventory_delta or world_block_delta)
    pre_dusk_machine_visible_progress = bool(pre_dusk_inventory_delta or pre_dusk_world_block_delta)
    first_unrecovered = (
        _pre_dusk_planner_transition(active)
        if not pre_dusk_machine_visible_progress
        else {}
    ) or _first_unrecovered_transition(active)
    required_recording = {
        "autonomous_goals": bool(goals),
        "resource_acquisition": bool(pre_dusk_inventory_delta),
        "crafting_behavior_recorded": bool(crafting_actions),
        "shelter_or_safe_point_intent": bool(shelter_goals or shelter_plans),
        "planner_provider_controls": planner_controls["passed"],
        "time_remaining_recorded": _finite(manifest.get("episode_deadline_monotonic"))
        and _finite(manifest.get("episode_ended_monotonic")),
        "inventory_world_delta_recorded": bool(state_samples),
        "loop_metrics_recorded": True,
    }
    g2_passed = bool(
        preflight.get("passed") is True
        and required_recording["autonomous_goals"]
        and required_recording["planner_provider_controls"]
        and bool(actions)
        and pre_dusk_machine_visible_progress
        and result.get("deadline_eligible") is True
    )
    return {
        "type": "m4_preparation_report",
        "schema_version": 1,
        "task_id": "BM-011",
        "profile": PROTOCOL["profile"],
        "protocol_sha256": PROTOCOL_SHA256,
        "readiness": "approved" if g2_passed else "review",
        "decision": "allow_g3_shelter_verifier_work" if g2_passed else "diagnose_first_unrecovered_transition",
        "g2_passed": g2_passed,
        "counts_toward_bm011_success": bool(eligibility.get("eligible")),
        "episode_id": manifest.get("episode_id"),
        "session_id": manifest.get("session_id"),
        "level_name": manifest.get("level_name"),
        "required_recording": required_recording,
        "autonomous_goals": goals,
        "planner_provider_controls": planner_controls,
        "action_count": len(actions),
        "successful_action_count": len(successful_actions),
        "crafting_action_count": len(crafting_actions),
        "shelter_goal_count": len(shelter_goals),
        "shelter_plan_count": len(shelter_plans),
        "inventory_delta": inventory_delta,
        "world_block_delta": world_block_delta,
        "machine_visible_progress": machine_visible_progress,
        "pre_dusk_inventory_delta": pre_dusk_inventory_delta,
        "pre_dusk_world_block_delta": pre_dusk_world_block_delta,
        "pre_dusk_machine_visible_progress": pre_dusk_machine_visible_progress,
        "pre_dusk_last_state": _compact_state(pre_dusk_after),
        "time_of_day_before": before.get("time_of_day"),
        "time_of_day_after": after.get("time_of_day"),
        "time_remaining_s": _remaining_time(manifest),
        "same_goal_max_consecutive": repeated_goal_max,
        "same_plan_max_consecutive": _max_consecutive(plan_signatures),
        "same_failed_action_max_count": max(Counter(failed_action_signatures).values(), default=0),
        "goal_switch_count": sum(1 for previous, current in zip(goal_titles, goal_titles[1:]) if previous != current),
        "no_progress_observation_transitions": no_progress_transitions,
        "first_unrecovered_transition": first_unrecovered,
        "before_state": _compact_state(before),
        "after_state": _compact_state(after),
        "deadline_eligible": bool(result.get("deadline_eligible")),
        "evidence_eligible": bool(eligibility.get("eligible")),
        "eligibility_issues": list(eligibility.get("issues", [])),
    }


def build_m4_episode_progress_report(
    events: list[dict],
    result: dict,
    preflight: dict,
    manifest: dict,
    eligibility: dict,
) -> dict:
    task_id = str(manifest.get("task_id") or preflight.get("task_id") or "").upper().strip()
    if task_id == "BM-011":
        return build_m4_preparation_report(events, result, preflight, manifest, eligibility)
    if task_id != "BM-012":
        raise ValueError(f"unsupported M4 progress report task: {task_id or '<missing>'}")

    active = _active_events(events)
    observations = [
        event.get("data", {})
        for event in active
        if event.get("type") == "observation" and isinstance(event.get("data"), dict)
    ]
    goals = [
        event.get("data", {})
        for event in active
        if event.get("type") == "auto_goal" and isinstance(event.get("data"), dict)
    ]
    actions = [
        event.get("data", {})
        for event in active
        if event.get("type") == "action" and isinstance(event.get("data"), dict)
    ]
    successful_actions = [
        action for action in actions if (action.get("result") or {}).get("success") is True
    ]
    before = observations[0] if observations else {}
    terminal = result.get("terminal_state", {}) if isinstance(result.get("terminal_state"), dict) else {}
    after = observations[-1] if observations else terminal
    planner_controls = planner_provider_controls_report(active)
    resource_evidence = eligibility.get("evidence", {}).get("resource_acquisition", {})
    resource_evidence = resource_evidence if isinstance(resource_evidence, dict) else {}
    first_unrecovered = _first_unrecovered_transition(active)
    progress_gate_passed = bool(
        preflight.get("passed") is True
        and goals
        and actions
        and planner_controls["passed"]
        and result.get("deadline_eligible") is True
        and (
            resource_evidence.get("successful_source_action_count", 0) > 0
            or any(
                token in str(goal.get("goal") or "").lower()
                for goal in goals
                for token in ("iron", "stone pickaxe", "cobblestone")
            )
        )
    )
    return {
        "type": "m4_resource_progress_report",
        "schema_version": 1,
        "task_id": task_id,
        "profile": PROTOCOL["profile"],
        "protocol_sha256": PROTOCOL_SHA256,
        "task_contract_id": str(task_contract(task_id).get("id") or ""),
        "task_contract_sha256": task_contract_sha256(task_id),
        "readiness": "eligible" if eligibility.get("eligible") is True else "review",
        "decision": "count_bm012_success" if eligibility.get("eligible") is True else "diagnose_first_unrecovered_transition",
        "progress_gate_passed": progress_gate_passed,
        "counts_toward_task_success": bool(eligibility.get("eligible")),
        "episode_id": manifest.get("episode_id"),
        "session_id": manifest.get("session_id"),
        "level_name": manifest.get("level_name"),
        "autonomous_goals": goals,
        "planner_provider_controls": planner_controls,
        "action_count": len(actions),
        "successful_action_count": len(successful_actions),
        "resource_acquisition": resource_evidence,
        "before_state": _compact_state(before),
        "after_state": _compact_state(after),
        "time_remaining_s": _remaining_time(manifest),
        "first_unrecovered_transition": first_unrecovered,
        "deadline_eligible": bool(result.get("deadline_eligible")),
        "evidence_eligible": bool(eligibility.get("eligible")),
        "eligibility_issues": list(eligibility.get("issues", [])),
    }


def _active_events(events: list[dict]) -> list[dict]:
    typed = [event for event in events if isinstance(event, dict)]
    start = next((index for index, event in enumerate(typed) if event.get("type") == "autonomous_start"), None)
    if start is None:
        return []
    end = next(
        (index for index in range(start, len(typed)) if typed[index].get("type") == "autonomous_end"),
        len(typed) - 1,
    )
    return typed[start:end + 1]


def _state_samples(events: list[dict], result: dict) -> list[dict]:
    samples = []
    for event in events:
        data = event.get("data", {}) if isinstance(event.get("data"), dict) else {}
        if event.get("type") == "observation":
            samples.append(dict(data))
        elif event.get("type") == "action" and isinstance(data.get("post_observation"), dict):
            samples.append(dict(data["post_observation"]))
    terminal = result.get("terminal_state", {}) if isinstance(result.get("terminal_state"), dict) else {}
    if terminal:
        normalized = dict(samples[-1]) if samples else {}
        normalized.update(terminal)
        if "hunger" not in normalized and "food" in normalized:
            normalized["hunger"] = normalized.get("food")
        samples.append(normalized)
    return samples


def _is_pre_dusk_state(state: dict) -> bool:
    value = _number(state.get("time_of_day"))
    if value is None:
        return False
    normalized = int(value) % 24000
    survival = PROTOCOL["validation_contract"]["survival"]
    return int(survival["preparation_start_time"]) <= normalized < int(survival["dusk_start_time"])


def _contains_shelter_intent(value) -> bool:
    try:
        text = json.dumps(value, sort_keys=True, default=str)
    except (TypeError, ValueError):
        text = str(value)
    text = text.lower()
    return any(token in text for token in ("shelter", "nightfall", "safe point", "safe_state"))


def _verified_world_block_delta(actions: list[dict], pre_dusk_only: bool = False) -> list[dict]:
    changes = []
    for action_event in actions:
        action = action_event.get("action", {}) if isinstance(action_event.get("action"), dict) else {}
        result = action_event.get("result", {}) if isinstance(action_event.get("result"), dict) else {}
        if result.get("success") is not True or action.get("type") not in {"dig", "place", "build_shelter_5x5"}:
            continue
        before = action_event.get("pre_observation", {})
        after = action_event.get("post_observation", {})
        if not isinstance(before, dict) or not isinstance(after, dict):
            continue
        if pre_dusk_only and not _is_pre_dusk_state(after):
            continue
        before_blocks = _nearby_block_map(before.get("nearby_blocks", []))
        after_blocks = _nearby_block_map(after.get("nearby_blocks", []))
        for position in sorted(set(before_blocks) | set(after_blocks)):
            previous = before_blocks.get(position, "air")
            current = after_blocks.get(position, "air")
            if previous == current:
                continue
            changes.append({
                "action_type": str(action.get("type") or ""),
                "position": {"x": position[0], "y": position[1], "z": position[2]},
                "before": previous,
                "after": current,
            })
    return changes


def _nearby_block_map(blocks) -> dict:
    mapped = {}
    for block in blocks if isinstance(blocks, list) else []:
        if not isinstance(block, dict) or not isinstance(block.get("position"), dict):
            continue
        position = block["position"]
        try:
            key = tuple(int(round(float(position[axis]))) for axis in ("x", "y", "z"))
        except (KeyError, TypeError, ValueError):
            continue
        mapped[key] = str(block.get("name") or "air")
    return mapped


def _positive_inventory_delta(before, after) -> dict:
    before = before if isinstance(before, dict) else {}
    after = after if isinstance(after, dict) else {}
    delta = {}
    for item in sorted(set(before) | set(after)):
        change = _count(after.get(item)) - _count(before.get(item))
        if change > 0:
            delta[str(item)] = change
    return delta


def _observable_progress(before: dict, after: dict) -> bool:
    if _positive_inventory_delta(before.get("inventory", {}), after.get("inventory", {})):
        return True
    before_pos = before.get("position", {}) if isinstance(before.get("position"), dict) else {}
    after_pos = after.get("position", {}) if isinstance(after.get("position"), dict) else {}
    if _position_distance(before_pos, after_pos) >= 0.5:
        return True
    before_time = _number(before.get("time_of_day"))
    after_time = _number(after.get("time_of_day"))
    if before_time is not None and after_time is not None and (after_time - before_time) % 24000 > 0:
        return True
    return _number(before.get("health")) != _number(after.get("health"))


def _first_unrecovered_transition(events: list[dict]) -> dict:
    current_goal = ""
    goal_by_index = {}
    for index, event in enumerate(events):
        data = event.get("data", {}) if isinstance(event.get("data"), dict) else {}
        if event.get("type") == "auto_goal":
            current_goal = str(data.get("goal") or "")
        goal_by_index[index] = current_goal
    completed_goals = [
        (index, str((event.get("data") or {}).get("goal") or ""))
        for index, event in enumerate(events)
        if event.get("type") == "auto_goal_complete" and isinstance(event.get("data"), dict)
    ]
    successful_actions = [
        (index, _action_signature((event.get("data") or {}).get("action", {})))
        for index, event in enumerate(events)
        if event.get("type") == "action"
        and isinstance(event.get("data"), dict)
        and isinstance(event["data"].get("result"), dict)
        and event["data"]["result"].get("success") is True
    ]
    recovered_plans = [
        (index, goal_by_index.get(index, ""))
        for index, event in enumerate(events)
        if event.get("type") == "plan"
        and isinstance(event.get("data"), dict)
        and event["data"].get("status") in {"planning", "complete", "blocked"}
        and bool(event["data"].get("actions"))
    ]
    active_goal = ""
    for index, event in enumerate(events):
        data = event.get("data", {}) if isinstance(event.get("data"), dict) else {}
        if event.get("type") == "auto_goal":
            active_goal = str(data.get("goal") or "")
            continue
        if event.get("type") == "episode_deadline_exceeded":
            return {
                "event_type": event.get("type"),
                "goal": active_goal,
                "detail": data,
                "monotonic_s": event.get("monotonic_s"),
            }
        if event.get("type") == "action":
            result = data.get("result", {}) if isinstance(data.get("result"), dict) else {}
            if result.get("success") is not True:
                signature = _action_signature(data.get("action", {}))
                goal = str((data.get("action_context") or {}).get("goal") or active_goal)
                recovered = any(later > index and later_signature == signature for later, later_signature in successful_actions)
                recovered = recovered or any(later > index and completed_goal == goal for later, completed_goal in completed_goals)
                if recovered:
                    continue
                return {
                    "event_type": "action",
                    "goal": goal,
                    "action": data.get("action", {}),
                    "error": str(result.get("error") or "action_not_verified_success"),
                    "monotonic_s": event.get("monotonic_s"),
                }
        if event.get("type") in {"empty_plan", "auto_goal_failed"}:
            goal = str(data.get("goal") or active_goal)
            recovered = any(later > index and completed_goal == goal for later, completed_goal in completed_goals)
            recovered = recovered or any(later > index and planned_goal == goal for later, planned_goal in recovered_plans)
            if recovered:
                continue
            return {
                "event_type": event.get("type"),
                "goal": goal,
                "detail": data,
                "monotonic_s": event.get("monotonic_s"),
            }
    return {}


def _pre_dusk_planner_transition(events: list[dict]) -> dict:
    """Identify a Planner call that consumed the remaining fixed preparation window."""
    survival = PROTOCOL["validation_contract"]["survival"]
    preparation_start = int(survival["preparation_start_time"])
    dusk_start = int(survival["dusk_start_time"])
    latest_observation = {}
    active_goal = ""
    for event in events:
        data = event.get("data", {}) if isinstance(event.get("data"), dict) else {}
        if event.get("type") == "observation":
            latest_observation = data
            continue
        if event.get("type") == "auto_goal":
            active_goal = str(data.get("goal") or "")
            continue
        if event.get("type") != "llm_planner_call":
            continue
        time_of_day = _number(latest_observation.get("time_of_day"))
        provider = data.get("provider_metadata", {}) if isinstance(data.get("provider_metadata"), dict) else {}
        duration_ms = _number(provider.get("duration_ms"))
        if time_of_day is None or duration_ms is None:
            continue
        normalized_time = int(time_of_day) % 24000
        if not preparation_start <= normalized_time < dusk_start:
            continue
        nominal_ticks_per_second = 20.0
        preparation_budget_s = (dusk_start - normalized_time) / nominal_ticks_per_second
        duration_s = duration_ms / 1000.0
        if duration_s < preparation_budget_s:
            continue
        return {
            "event_type": "llm_planner_call",
            "transition": "pre_dusk_planning_window_exhausted",
            "goal": str(data.get("goal") or active_goal),
            "call_id": str(data.get("call_id") or ""),
            "call_duration_s": round(duration_s, 3),
            "pre_call_time_of_day": normalized_time,
            "dusk_start_time": dusk_start,
            "preparation_budget_s": round(preparation_budget_s, 3),
            "nominal_ticks_per_second": nominal_ticks_per_second,
            "monotonic_s": event.get("monotonic_s"),
        }
    return {}


def _compact_state(observation: dict) -> dict:
    return {
        "position": observation.get("position", {}),
        "health": observation.get("health"),
        "hunger": observation.get("hunger", observation.get("food")),
        "inventory": observation.get("inventory", {}),
        "time_of_day": observation.get("time_of_day"),
        "nearby_hostile_count": sum(
            1 for entity in observation.get("nearby_entities", [])
            if isinstance(entity, dict) and entity.get("hostile")
        ),
    }


def _remaining_time(manifest: dict):
    deadline = _number(manifest.get("episode_deadline_monotonic"))
    ended = _number(manifest.get("episode_ended_monotonic"))
    if deadline is None or ended is None:
        return None
    return round(max(0.0, deadline - ended), 3)


def _action_signature(action: dict) -> str:
    if not isinstance(action, dict):
        return "unknown"
    params = action.get("parameters", {}) if isinstance(action.get("parameters"), dict) else {}
    subject = params.get("item") or params.get("block") or params.get("entity_id") or ""
    return f"{action.get('type', 'unknown')}:{subject}"


def _max_consecutive(values: list[str]) -> int:
    maximum = 0
    current = 0
    previous = object()
    for value in values:
        if value == previous:
            current += 1
        else:
            current = 1
            previous = value
        maximum = max(maximum, current)
    return maximum


def _position_distance(before: dict, after: dict) -> float:
    try:
        return math.sqrt(sum((float(after[key]) - float(before[key])) ** 2 for key in ("x", "y", "z")))
    except (KeyError, TypeError, ValueError):
        return 0.0


def _number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _finite(value) -> bool:
    return _number(value) is not None


def _count(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
