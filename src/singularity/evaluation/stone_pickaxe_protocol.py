"""Fixed stone-pickaxe microbenchmarks and their offline verification harness.

The harness consumes declarative observations and evidence records only. It does
not start Minecraft, execute learned-skill code, or turn offline fixtures into
live evidence.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable

from singularity.core.skill_runtime import (
    ALLOWED_OPERATIONS,
    DSL_VERSION,
    validate_bounded_action_template,
)
from singularity.core.task_system import Task, TaskStatus, TaskSystem
from singularity.evaluation.m4_protocol import (
    PROTOCOL as M4_PROTOCOL,
    PROTOCOL_SHA256 as M4_PROTOCOL_SHA256,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PROTOCOL_PATH = REPOSITORY_ROOT / "workspace" / "evals" / "stone_pickaxe_protocol.json"
PROTOCOL_BYTES = PROTOCOL_PATH.read_bytes()
PROTOCOL = json.loads(PROTOCOL_BYTES.decode("utf-8"))
PROTOCOL_SHA256 = hashlib.sha256(PROTOCOL_BYTES).hexdigest()
TASKS_BY_ID = {str(task.get("id") or ""): task for task in PROTOCOL.get("tasks", [])}


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def file_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def task_spec(task_id: str) -> dict:
    return TASKS_BY_ID.get(str(task_id or "").upper().strip(), {})


def prospective_skill_contract(task_id: str) -> dict:
    contracts = PROTOCOL.get("prospective_skill_contracts", {})
    return contracts.get(str(task_id or "").upper().strip(), {}) if isinstance(contracts, dict) else {}


def protocol_integrity_report() -> dict:
    issues: list[str] = []

    def require(name: str, passed: bool) -> None:
        if not passed:
            issues.append(name)

    require("type", PROTOCOL.get("type") == "stone_pickaxe_skill_protocol")
    require("schema_version", PROTOCOL.get("schema_version") == 1)
    require("protocol_id", PROTOCOL.get("id") == "stone-pickaxe-skill-fixed-v1")
    require("phase_scope", PROTOCOL.get("phase_scope") == "protocol_and_offline_harness")
    require("base_protocol_sha256", PROTOCOL.get("base_protocol", {}).get("sha256") == M4_PROTOCOL_SHA256)

    environment = PROTOCOL.get("environment", {})
    for key in ("minecraft_version", "server_build", "server_jar_sha256", "world_seed", "game_mode", "difficulty"):
        m4_key = "world_seed" if key == "world_seed" else key
        require(f"environment:{key}", environment.get(key) == M4_PROTOCOL.get(m4_key))
    require("runtime_versions", environment.get("runtime_versions") == M4_PROTOCOL.get("runtime_versions"))

    planner = PROTOCOL.get("planner", {})
    m4_llm = M4_PROTOCOL.get("llm", {})
    for key in ("provider", "base_url", "model", "temperature", "max_tokens"):
        require(f"planner:{key}", planner.get(key) == m4_llm.get(key))
    require("planner:thinking", planner.get("thinking") == "disabled")
    require("planner:retries", planner.get("provider_retries") == 0)

    identities = PROTOCOL.get("identities", {})
    require("skill_runtime_identity", identities.get("skill_runtime") == DSL_VERSION)
    require("action_backend_identity", identities.get("action_backend") == "mineflayer-bridge-v1")
    require("goal_verifier_identity", identities.get("goal_verifier") == "stone-pickaxe-machine-verifier-v1")
    require("bounded_operation_set", ALLOWED_OPERATIONS == {"acquire_block_drop", "craft_item"})

    deadline = PROTOCOL.get("deadline_policy", {})
    require("single_absolute_deadline", deadline.get("single_absolute_deadline_required") is True)
    require("per_action_timeout", deadline.get("per_action_timeout_s") == 60)
    require("no_post_deadline_action", deadline.get("post_deadline_action_allowed") is False)

    controls = PROTOCOL.get("runtime_controls", {})
    require("default_skills_off", controls.get("default_skill_execution_mode") == "off")
    require("empty_skill_allowlist", controls.get("learned_skill_allowlist") == [])
    require("quarantined_skills_off", controls.get("quarantined_skills_enabled") is False)
    require("no_automatic_retry", controls.get("automatic_retry_allowed") is False)
    require("no_external_step_script", controls.get("external_step_script_allowed") is False)

    fixture = PROTOCOL.get("fixture_policy", {})
    require(
        "forbidden_commands",
        set(fixture.get("forbidden_commands", []))
        == {"give", "teleport", "gamemode", "setblock", "result_injection"},
    )
    require("no_target_injection", fixture.get("target_result_injection_allowed") is False)
    sources = fixture.get("cobblestone_sources", {})
    require("source_allowlist", sources.get("block_allowlist") == ["stone"])
    require("source_selector", sources.get("selector") == "nearest_observed")
    require("no_duplicate_source", sources.get("duplicate_source_dig_allowed") is False)

    require("task_ids", set(TASKS_BY_ID) == {"SP-001", "SP-002", "SP-003"})
    expected_limits = {
        "SP-001": (180, 12, 8),
        "SP-002": (90, 6, 1),
        "SP-003": (300, 20, 9),
    }
    for task_id, limits in expected_limits.items():
        task = task_spec(task_id)
        require(f"{task_id}:limits", (
            task.get("episode_timeout_s"),
            task.get("maximum_cycles"),
            task.get("maximum_actions"),
        ) == limits)
    require("sp003_dependency_path", task_spec("SP-003").get("dependency_path") == ["SP-001", "SP-002"])

    for task_id in ("SP-001", "SP-002"):
        report = validate_prospective_skill_contract(task_id, prospective_skill_contract(task_id))
        issues.extend(f"{task_id}:{issue}" for issue in report["issues"])

    evidence = PROTOCOL.get("evidence_policy", {})
    require("offline_not_skill_evidence", evidence.get("offline_counts_toward_skill_gate") is False)
    require("offline_not_capability_evidence", evidence.get("offline_counts_toward_capability") is False)
    require("microbenchmark_not_m4_evidence", evidence.get("skill_microbenchmark_counts_toward_m4") is False)

    promotion = PROTOCOL.get("promotion_gates", {})
    require("three_live_before_extraction", promotion.get("minimum_independent_eligible_live_successes_before_extraction") == 3)
    require("three_paired_evaluations", promotion.get("minimum_independent_eligible_baseline_candidate_pairs") == 3)
    require(
        "lifecycle_order",
        promotion.get("lifecycle_order") == ["candidate", "advisory", "paired_evaluation", "executable"],
    )
    require("no_version_rewrite", promotion.get("in_place_version_rewrite_allowed") is False)

    cases = PROTOCOL.get("offline_acceptance_cases", [])
    require("thirty_offline_cases", [case.get("id") for case in cases] == list(range(1, 31)))
    require("unique_offline_case_names", len({case.get("name") for case in cases}) == 30)
    return {
        "passed": not issues,
        "issues": sorted(set(issues)),
        "protocol_id": PROTOCOL.get("id"),
        "protocol_sha256": PROTOCOL_SHA256,
        "base_protocol_sha256": M4_PROTOCOL_SHA256,
    }


def validate_prospective_skill_contract(task_id: str, contract: Any) -> dict:
    normalized_id = str(task_id or "").upper().strip()
    issues: list[str] = []
    if not isinstance(contract, dict):
        return {"passed": False, "issues": ["contract_must_be_object"], "template": {}}

    if contract.get("artifact_state") != "not_created":
        issues.append("artifact_must_remain_uncreated")
    if contract.get("layer") != "composite":
        issues.append("layer_must_be_composite")

    if normalized_id == "SP-001":
        expected = {
            "skill_id": "learned:acquire_cobblestone",
            "task_family": "mining",
            "preconditions": {"inventory": {"wooden_pickaxe": 1}},
            "required_observations": ["inventory", "observed_block:stone"],
            "postconditions": {"inventory": {"cobblestone": 3}},
        }
        template_report = validate_acquire_template(contract.get("bounded_action_template"))
    elif normalized_id == "SP-002":
        expected = {
            "skill_id": "learned:craft_stone_pickaxe",
            "task_family": "crafting",
            "preconditions": {
                "inventory": {"cobblestone": 3, "stick": 2},
                "nearby_block_present": ["crafting_table"],
                "nearby_block_max_distance": {"crafting_table": 4.5},
            },
            "required_observations": ["inventory", "nearby_block:crafting_table"],
            "postconditions": {"inventory": {"stone_pickaxe": 1}},
        }
        template_report = validate_craft_template(contract.get("bounded_action_template"))
    else:
        return {"passed": False, "issues": ["unsupported_task_id"], "template": {}}

    for key, value in expected.items():
        if contract.get(key) != value:
            issues.append(f"exact_{key}_required")
    issues.extend(template_report["issues"])
    return {
        "passed": not issues,
        "issues": sorted(set(issues)),
        "template": template_report.get("normalized_template", {}),
    }


def validate_acquire_template(template: Any) -> dict:
    validation = validate_bounded_action_template(template)
    issues = list(validation.issues)
    raw = template if isinstance(template, dict) else {}
    prohibited = {"x", "y", "z", "position", "coordinates", "source_id", "block_id", "session_id", "episode_id"}
    for path in _matching_key_paths(raw, prohibited):
        issues.append(f"fixture_specific_field_forbidden:{path}")

    expected = prospective_skill_contract("SP-001").get("bounded_action_template", {})
    if raw != expected:
        issues.append("exact_sp001_template_required")
    normalized = validation.normalized_template
    phase = normalized.get("phases", [{}])[0] if normalized.get("phases") else {}
    if normalized.get("max_actions") != 8:
        issues.append("max_actions_must_equal_8")
    if phase.get("op") != "acquire_block_drop":
        issues.append("acquire_operation_required")
    if phase.get("source_blocks") != ["stone"]:
        issues.append("source_allowlist_mismatch")
    if phase.get("target_item") != "cobblestone":
        issues.append("exact_cobblestone_target_required")
    return {
        "passed": not issues,
        "issues": sorted(set(issues)),
        "normalized_template": normalized,
    }


def validate_craft_template(template: Any) -> dict:
    validation = validate_bounded_action_template(template)
    issues = list(validation.issues)
    raw = template if isinstance(template, dict) else {}
    expected = prospective_skill_contract("SP-002").get("bounded_action_template", {})
    if raw != expected:
        issues.append("exact_sp002_template_required")
    if _matching_key_paths(raw, {"recipe"}):
        issues.append("recipe_alias_forbidden")
    normalized = validation.normalized_template
    phase = normalized.get("phases", [{}])[0] if normalized.get("phases") else {}
    if normalized.get("max_actions") != 1:
        issues.append("max_actions_must_equal_1")
    expected_phase = {
        "id": "craft_target",
        "op": "craft_item",
        "item": "stone_pickaxe",
        "count": 1,
        "target_item": "stone_pickaxe",
        "target_count": 1,
    }
    if phase != expected_phase:
        issues.append("exact_stone_pickaxe_craft_phase_required")
    return {
        "passed": not issues,
        "issues": sorted(set(issues)),
        "normalized_template": normalized,
    }


def plan_sp001_action(
    observation: Any,
    quantity: int = 3,
    used_source_ids: Iterable[str] | None = None,
) -> dict:
    task = task_spec("SP-001")
    minimum = 1
    maximum = prospective_skill_contract("SP-001")["bounded_action_template"]["parameters"]["quantity"]["maximum"]
    if not _strict_integer(quantity) or quantity < minimum or quantity > maximum:
        return _plan_fallback("parameter_outside_transfer_scope:quantity")
    if not isinstance(observation, dict):
        return _plan_fallback("observation_required")
    inventory = observation.get("inventory")
    if not isinstance(inventory, dict):
        return _plan_fallback("inventory_observation_required")
    if _count(inventory.get("cobblestone")) >= quantity:
        return {
            "status": "complete",
            "reasoning": "exact cobblestone postcondition already satisfied",
            "actions": [],
            "target_count": quantity,
            "requires_reobservation": False,
        }

    issues = []
    if _count(inventory.get("wooden_pickaxe")) < 1:
        issues.append("inventory:wooden_pickaxe>=1")
    if observation.get("safe") is not True:
        issues.append("safe_state_required")
    if observation.get("movable") is not True:
        issues.append("movable_state_required")
    if issues:
        return _plan_fallback("preconditions_not_met", issues)

    excluded = {str(value) for value in (used_source_ids or []) if str(value)}
    candidates = _sp001_source_candidates(observation, excluded)
    if not candidates:
        return _plan_fallback("required_observation_missing", ["reachable_observed_block:stone"])
    target = candidates[0]
    position = target["position"]
    action = {
        "type": "dig",
        "parameters": {
            "block": target["name"],
            "source_id": target["source_id"],
            "x": round(position["x"]),
            "y": round(position["y"]),
            "z": round(position["z"]),
        },
    }
    return {
        "status": "in_progress",
        "reasoning": "dig the nearest reachable observed allowlisted source",
        "actions": [action],
        "selected_source": target,
        "target_count": quantity,
        "requires_reobservation": True,
        "maximum_actions": task["maximum_actions"],
    }


def verify_sp001_episode(evidence: Any) -> dict:
    value = evidence if isinstance(evidence, dict) else {}
    criteria_issues: list[str] = []
    task = task_spec("SP-001")
    initial = value.get("initial_observation") if isinstance(value.get("initial_observation"), dict) else {}
    initial_inventory = _inventory(initial)
    _require_issue(criteria_issues, "initial_wooden_pickaxe_exact", initial_inventory.get("wooden_pickaxe", 0) == 1)
    _require_issue(criteria_issues, "initial_cobblestone_zero", initial_inventory.get("cobblestone", 0) == 0)
    _require_issue(criteria_issues, "initial_stone_pickaxe_zero", initial_inventory.get("stone_pickaxe", 0) == 0)
    _require_issue(criteria_issues, "initial_safe", initial.get("safe") is True)
    _require_issue(criteria_issues, "initial_movable", initial.get("movable") is True)
    _require_issue(criteria_issues, "initial_reachable_source", bool(_sp001_source_candidates(initial, set())))

    transitions = value.get("transitions") if isinstance(value.get("transitions"), list) else []
    seen_sources: set[str] = set()
    removal_count = 0
    pickup_count = 0
    deadline = _finite_number(value.get("episode_deadline_monotonic"))
    approved_tools = set(task["machine_success"]["approved_tools"])
    source_allowlist = set(PROTOCOL["fixture_policy"]["cobblestone_sources"]["block_allowlist"])

    for index, transition in enumerate(transitions):
        prefix = f"transition_{index + 1}"
        if not isinstance(transition, dict):
            criteria_issues.append(f"{prefix}:object_required")
            continue
        source_id = str(transition.get("source_id") or "")
        source_block = str(transition.get("source_block") or "")
        _require_issue(criteria_issues, f"{prefix}:source_id", bool(source_id))
        _require_issue(criteria_issues, f"{prefix}:distinct_source", bool(source_id) and source_id not in seen_sources)
        if source_id:
            seen_sources.add(source_id)
        _require_issue(criteria_issues, f"{prefix}:source_allowlist", source_block in source_allowlist)
        _require_issue(criteria_issues, f"{prefix}:approved_tool", transition.get("tool") in approved_tools)
        _require_issue(criteria_issues, f"{prefix}:action_verified", transition.get("action_verified") is True)

        action = transition.get("action") if isinstance(transition.get("action"), dict) else {}
        parameters = action.get("parameters") if isinstance(action.get("parameters"), dict) else {}
        _require_issue(criteria_issues, f"{prefix}:dig_action", action.get("type") == "dig")
        _require_issue(criteria_issues, f"{prefix}:dig_block", parameters.get("block") == source_block)
        _require_issue(criteria_issues, f"{prefix}:dig_source", parameters.get("source_id") == source_id)

        pre = transition.get("pre_observation") if isinstance(transition.get("pre_observation"), dict) else {}
        post = transition.get("post_observation") if isinstance(transition.get("post_observation"), dict) else {}
        _require_issue(criteria_issues, f"{prefix}:pre_observation", bool(str(pre.get("observation_id") or "")))
        _require_issue(criteria_issues, f"{prefix}:post_observation", bool(str(post.get("observation_id") or "")))
        _require_issue(
            criteria_issues,
            f"{prefix}:observation_identity",
            bool(str(pre.get("observation_id") or ""))
            and str(pre.get("observation_id")) != str(post.get("observation_id") or ""),
        )
        pre_source = pre.get("source") if isinstance(pre.get("source"), dict) else {}
        post_source = post.get("source") if isinstance(post.get("source"), dict) else {}
        source_removed = (
            pre_source.get("id") == source_id
            and pre_source.get("name") == source_block
            and pre_source.get("present") is True
            and post_source.get("id") == source_id
            and post_source.get("name") == source_block
            and post_source.get("present") is False
        )
        _require_issue(criteria_issues, f"{prefix}:source_removed", source_removed)
        if source_removed:
            removal_count += 1

        pickup = transition.get("pickup") if isinstance(transition.get("pickup"), dict) else {}
        valid_pickup = (
            pickup.get("observed") is True
            and pickup.get("source_id") == source_id
            and pickup.get("item") == "cobblestone"
            and _strict_integer(pickup.get("count"))
            and pickup.get("count") >= 1
        )
        _require_issue(criteria_issues, f"{prefix}:pickup_provenance", valid_pickup)
        if valid_pickup:
            pickup_count += int(pickup["count"])
        pre_count = _inventory(pre).get("cobblestone", 0)
        post_count = _inventory(post).get("cobblestone", 0)
        _require_issue(criteria_issues, f"{prefix}:inventory_delta", post_count - pre_count >= 1)
        _validate_transition_deadline(criteria_issues, transition, deadline, prefix)

    minimum_removals = task["machine_success"]["minimum_distinct_source_removals"]
    _require_issue(criteria_issues, "minimum_distinct_source_removals", removal_count >= minimum_removals)
    _require_issue(criteria_issues, "minimum_pickup_count", pickup_count >= 3)
    terminal = value.get("terminal_observation") if isinstance(value.get("terminal_observation"), dict) else {}
    terminal_count = _inventory(terminal).get("cobblestone", 0)
    inventory_delta = terminal_count - initial_inventory.get("cobblestone", 0)
    last_transition = transitions[-1] if transitions and isinstance(transitions[-1], dict) else {}
    last_post = last_transition.get("post_observation", {})
    _require_issue(criteria_issues, "terminal_observation", bool(str(terminal.get("observation_id") or "")))
    _require_issue(criteria_issues, "terminal_cobblestone_delta", inventory_delta >= 3)
    _require_issue(
        criteria_issues,
        "terminal_matches_transition",
        not transitions or (bool(last_transition) and terminal_count >= _inventory(last_post).get("cobblestone", 0)),
    )

    return _verification_report(
        "SP-001",
        value,
        criteria_issues,
        {
            "source_removal_count": removal_count,
            "distinct_source_count": len(seen_sources),
            "pickup_count": pickup_count,
            "inventory_delta": {"cobblestone": inventory_delta},
        },
    )


def verify_sp002_episode(evidence: Any) -> dict:
    value = evidence if isinstance(evidence, dict) else {}
    criteria_issues: list[str] = []
    initial = value.get("initial_observation") if isinstance(value.get("initial_observation"), dict) else {}
    initial_inventory = _inventory(initial)
    _require_issue(criteria_issues, "initial_cobblestone_exact", initial_inventory.get("cobblestone", 0) == 3)
    _require_issue(criteria_issues, "initial_stick_exact", initial_inventory.get("stick", 0) == 2)
    _require_issue(criteria_issues, "initial_stone_pickaxe_zero", initial_inventory.get("stone_pickaxe", 0) == 0)
    _require_issue(criteria_issues, "initial_crafting_table", _table_observed(initial))

    transitions = value.get("transitions") if isinstance(value.get("transitions"), list) else []
    _require_issue(criteria_issues, "exactly_one_craft_action", len(transitions) == 1)
    transition = transitions[0] if len(transitions) == 1 and isinstance(transitions[0], dict) else {}
    action = transition.get("action") if isinstance(transition.get("action"), dict) else {}
    parameters = action.get("parameters") if isinstance(action.get("parameters"), dict) else {}
    _require_issue(criteria_issues, "craft_action_type", action.get("type") == "craft")
    _require_issue(criteria_issues, "craft_item_exact", parameters.get("item") == "stone_pickaxe")
    _require_issue(criteria_issues, "craft_count_exact", parameters.get("count") == 1)
    _require_issue(criteria_issues, "recipe_alias_forbidden", "recipe" not in parameters)
    _require_issue(criteria_issues, "action_verified", transition.get("action_verified") is True)

    pre = transition.get("pre_observation") if isinstance(transition.get("pre_observation"), dict) else {}
    post = transition.get("post_observation") if isinstance(transition.get("post_observation"), dict) else {}
    stable = transition.get("stable_observation") if isinstance(transition.get("stable_observation"), dict) else {}
    pre_inventory = _inventory(pre)
    post_inventory = _inventory(post)
    stable_inventory = _inventory(stable)
    _require_issue(criteria_issues, "pre_materials_cobblestone", pre_inventory.get("cobblestone", 0) >= 3)
    _require_issue(criteria_issues, "pre_materials_stick", pre_inventory.get("stick", 0) >= 2)
    _require_issue(criteria_issues, "pre_stone_pickaxe_zero", pre_inventory.get("stone_pickaxe", 0) == 0)
    _require_issue(criteria_issues, "pre_crafting_table", _table_observed(pre))
    _require_issue(
        criteria_issues,
        "cobblestone_consumption_exact",
        pre_inventory.get("cobblestone", 0) - post_inventory.get("cobblestone", 0) == 3,
    )
    _require_issue(
        criteria_issues,
        "stick_consumption_exact",
        pre_inventory.get("stick", 0) - post_inventory.get("stick", 0) == 2,
    )
    _require_issue(
        criteria_issues,
        "stone_pickaxe_delta",
        post_inventory.get("stone_pickaxe", 0) - pre_inventory.get("stone_pickaxe", 0) >= 1,
    )

    table = transition.get("crafting_table_interaction") if isinstance(transition.get("crafting_table_interaction"), dict) else {}
    table_distance = _finite_number(table.get("distance"))
    valid_table_interaction = (
        table.get("observed") is True
        and table.get("interactive") is True
        and bool(str(table.get("block_id") or ""))
        and table.get("observation_id") == pre.get("observation_id")
        and table_distance is not None
        and table_distance <= PROTOCOL["fixture_policy"]["nearby_crafting_table"]["maximum_distance"]
    )
    _require_issue(criteria_issues, "crafting_table_interaction", valid_table_interaction)

    post_time = _finite_number(post.get("monotonic_s"))
    stable_time = _finite_number(stable.get("monotonic_s"))
    delay = PROTOCOL["evidence_policy"]["stable_reobservation_delay_s"]
    _require_issue(criteria_issues, "stable_observation_id", bool(str(stable.get("observation_id") or "")))
    _require_issue(
        criteria_issues,
        "stable_observation_distinct",
        bool(str(post.get("observation_id") or ""))
        and str(stable.get("observation_id") or "") != str(post.get("observation_id") or ""),
    )
    _require_issue(
        criteria_issues,
        "stable_reobservation_delay",
        post_time is not None and stable_time is not None and stable_time - post_time >= delay,
    )
    _require_issue(
        criteria_issues,
        "stable_stone_pickaxe",
        stable_inventory.get("stone_pickaxe", 0) >= post_inventory.get("stone_pickaxe", 0) >= 1,
    )
    deadline = _finite_number(value.get("episode_deadline_monotonic"))
    _validate_transition_deadline(criteria_issues, transition, deadline, "craft_transition")
    if deadline is not None:
        _require_issue(criteria_issues, "stable_observation_before_deadline", stable_time is not None and stable_time <= deadline)

    inventory_delta = stable_inventory.get("stone_pickaxe", 0) - initial_inventory.get("stone_pickaxe", 0)
    return _verification_report(
        "SP-002",
        value,
        criteria_issues,
        {
            "craft_action_count": len(transitions),
            "material_delta": {
                "cobblestone": post_inventory.get("cobblestone", 0) - pre_inventory.get("cobblestone", 0),
                "stick": post_inventory.get("stick", 0) - pre_inventory.get("stick", 0),
            },
            "inventory_delta": {"stone_pickaxe": inventory_delta},
            "stable_observation_id": str(stable.get("observation_id") or ""),
        },
    )


def verify_sp003_episode(evidence: Any) -> dict:
    value = evidence if isinstance(evidence, dict) else {}
    acquire = verify_sp001_episode(value.get("sp001"))
    craft = verify_sp002_episode(value.get("sp002"))
    chain = value.get("chain") if isinstance(value.get("chain"), dict) else {}
    issues = []
    _require_issue(issues, "sp001_machine_criteria", acquire["criteria_passed"])
    _require_issue(issues, "sp002_machine_criteria", craft["criteria_passed"])
    _require_issue(issues, "dependency_path", chain.get("dependency_path") == ["SP-001", "SP-002"])
    _require_issue(issues, "acquire_releases_craft", chain.get("acquire_completion_released_craft") is True)
    _require_issue(issues, "no_overdig", acquire["metrics"].get("source_removal_count") == 3)
    _require_issue(issues, "no_wooden_pickaxe_recraft", chain.get("wooden_pickaxe_recraft_count") == 0)
    _require_issue(issues, "no_crafting_table_recraft", chain.get("crafting_table_recraft_count") == 0)
    _require_issue(issues, "no_iron_mining", chain.get("iron_mining_action_count") == 0)
    _require_issue(issues, "terminal_stone_pickaxe", _inventory(chain.get("terminal_observation", {})).get("stone_pickaxe", 0) >= 1)
    _require_issue(
        issues,
        "separate_skill_attribution",
        chain.get("skill_attribution") == {
            "SP-001": "learned:acquire_cobblestone",
            "SP-002": "learned:craft_stone_pickaxe",
        },
    )
    report = _verification_report("SP-003", value, issues, {
        "sp001": acquire,
        "sp002": craft,
    })
    if not acquire["evidence_eligible"] or not craft["evidence_eligible"]:
        report["eligibility_issues"] = sorted(set(report["eligibility_issues"] + ["eligible_component_evidence_required"]))
        report["evidence_eligible"] = False
        report["passed"] = False
        report["counts_toward_skill_gate"] = False
    return report


class StonePickaxeCompositeHarness:
    """Small TaskSystem-backed state machine for SP-003 dependency tests."""

    def __init__(self) -> None:
        self.task_system = TaskSystem()
        acquire = self.task_system.create_task(
            "Acquire 3 cobblestone",
            task_type="mining",
            status=TaskStatus.ACCEPTED,
            priority=1,
            success_criteria={"inventory": {"cobblestone": 3}},
            root_plan_id="stone-pickaxe-composite",
            tags=["stone_pickaxe_protocol", "SP-001"],
        )
        craft = self.task_system.create_task(
            "Craft 1 stone pickaxe",
            task_type="crafting",
            status=TaskStatus.ACCEPTED,
            priority=2,
            preconditions={
                "inventory": {"cobblestone": 3, "stick": 2},
                "nearby_block_present": ["crafting_table"],
            },
            success_criteria={"inventory": {"stone_pickaxe": 1}},
            depends_on=[acquire.id],
            root_plan_id="stone-pickaxe-composite",
            tags=["stone_pickaxe_protocol", "SP-002"],
        )
        self.task_ids = {"SP-001": acquire.id, "SP-002": craft.id}
        self.attributions: list[dict] = []
        self._recovery_bindings: dict[tuple[str, str], str] = {}

    def task(self, task_id: str) -> Task:
        normalized = str(task_id or "").upper().strip()
        return self.task_system.tasks[self.task_ids[normalized]]

    def ensure_task(self, task_id: str) -> Task:
        return self.task(task_id)

    def frontier(self, world_state: dict) -> list[Task]:
        return self.task_system.get_ready_tasks(world_state if isinstance(world_state, dict) else {})

    def complete_from_machine_state(self, task_id: str, world_state: dict) -> bool:
        normalized = str(task_id or "").upper().strip()
        task = self.task(normalized)
        if task.status == TaskStatus.COMPLETED:
            return False
        inventory = _inventory(world_state)
        if normalized == "SP-001":
            satisfied = inventory.get("cobblestone", 0) >= 3
        elif normalized == "SP-002":
            satisfied = (
                self.task("SP-001").status == TaskStatus.COMPLETED
                and inventory.get("stone_pickaxe", 0) >= 1
            )
        else:
            raise ValueError("unsupported task id")
        if not satisfied:
            return False
        self.task_system.complete_task(
            task.id,
            result={
                "completed_by": "offline_machine_state_harness",
                "counts_toward_live_evidence": False,
                "world_state_fingerprint": canonical_sha256(world_state),
            },
            reason="stone_pickaxe_offline_machine_state",
        )
        for child_id in list(task.children):
            child = self.task_system.tasks.get(child_id)
            if child and child.status in {TaskStatus.ACCEPTED, TaskStatus.ACTIVE, TaskStatus.WAITING, TaskStatus.BLOCKED}:
                self.task_system.cancel_task(
                    child.id,
                    {"disposition": "stale_recovery_sibling", "counts_toward_live_evidence": False},
                    reason="stone_pickaxe_parent_machine_completed",
                )
        return True

    def ensure_recovery_child(self, task_id: str, fingerprint: str) -> Task | None:
        normalized = str(task_id or "").upper().strip()
        target = self.task(normalized)
        if target.status in {TaskStatus.COMPLETED, TaskStatus.CANCELLED, TaskStatus.FAILED}:
            return None
        key = str(fingerprint or "").strip()
        if not key:
            raise ValueError("recovery fingerprint required")
        binding_key = (target.id, key)
        matching = [
            task
            for task in self.task_system.tasks.values()
            if isinstance(task.metadata, dict)
            and task.metadata.get("stone_pickaxe_recovery", {}).get("fingerprint") == key
            and task.metadata.get("stone_pickaxe_recovery", {}).get("target_task_id") == target.id
            and task.status in {TaskStatus.ACCEPTED, TaskStatus.ACTIVE}
        ]
        matching.sort(key=lambda task: (task.created_at, task.id))
        if matching:
            bound_id = self._recovery_bindings.get(binding_key, "")
            keep = next((task for task in matching if task.id == bound_id), matching[0])
            self._recovery_bindings[binding_key] = keep.id
            for stale in matching:
                if stale.id == keep.id:
                    continue
                self.task_system.cancel_task(
                    stale.id,
                    {"disposition": "stale_recovery_sibling", "fingerprint": key},
                    reason="stone_pickaxe_recovery_deduplicated",
                )
            return keep
        if target.status in {TaskStatus.ACCEPTED, TaskStatus.ACTIVE}:
            self.task_system.update_task(
                target.id,
                status=TaskStatus.WAITING,
                reason="stone_pickaxe_recovery_child_active",
            )
        child = self.task_system.create_task(
            f"Recover prerequisite for {target.title}",
            task_type="recovery",
            parent_id=target.id,
            status=TaskStatus.ACCEPTED,
            priority=target.priority,
            success_criteria=dict(target.success_criteria or {}),
            failure_criteria={"max_failures": 3},
            root_plan_id=target.root_plan_id,
            tags=["stone_pickaxe_recovery", normalized],
            metadata={
                "stone_pickaxe_recovery": {
                    "fingerprint": key,
                    "target_task_id": target.id,
                    "attempt_budget": 3,
                    "counts_toward_live_evidence": False,
                }
            },
        )
        self._recovery_bindings[binding_key] = child.id
        return child

    def record_skill_attribution(self, task_id: str, skill_id: str, postconditions: Any) -> dict:
        normalized = str(task_id or "").upper().strip()
        expected = {
            "SP-001": ("learned:acquire_cobblestone", "cobblestone"),
            "SP-002": ("learned:craft_stone_pickaxe", "stone_pickaxe"),
        }
        if normalized not in expected:
            return {"accepted": False, "reason": "unsupported_task_id"}
        expected_skill, expected_item = expected[normalized]
        inventory = postconditions.get("inventory", {}) if isinstance(postconditions, dict) else {}
        valid = (
            skill_id == expected_skill
            and isinstance(inventory, dict)
            and set(inventory) == {expected_item}
            and _strict_integer(inventory.get(expected_item))
            and inventory[expected_item] >= 1
        )
        if not valid:
            return {"accepted": False, "reason": "attribution_scope_mismatch"}
        record = {
            "task_id": normalized,
            "skill_id": skill_id,
            "postconditions": {"inventory": {expected_item: inventory[expected_item]}},
            "root_goal_attributed": False,
            "counts_toward_live_evidence": False,
        }
        self.attributions.append(record)
        return {"accepted": True, "record": record}


def _verification_report(task_id: str, evidence: dict, criteria_issues: list[str], metrics: dict) -> dict:
    eligibility_issues = _eligibility_issues(task_id, evidence)
    criteria_issues = sorted(set(criteria_issues))
    eligibility_issues = sorted(set(eligibility_issues))
    criteria_passed = not criteria_issues
    evidence_eligible = criteria_passed and not eligibility_issues
    return {
        "type": "stone_pickaxe_machine_verification",
        "schema_version": 1,
        "protocol_id": PROTOCOL["id"],
        "protocol_sha256": PROTOCOL_SHA256,
        "task_id": task_id,
        "criteria_passed": criteria_passed,
        "evidence_eligible": evidence_eligible,
        "passed": criteria_passed and evidence_eligible,
        "criteria_issues": criteria_issues,
        "eligibility_issues": eligibility_issues,
        "metrics": metrics,
        "evidence_kind": str(evidence.get("evidence_kind") or ""),
        "counts_toward_skill_gate": evidence_eligible,
        "counts_toward_capability": False,
        "counts_toward_m4": False,
    }


def _eligibility_issues(task_id: str, evidence: dict) -> list[str]:
    issues = []
    if evidence.get("type") != "stone_pickaxe_microbenchmark_episode":
        issues.append("episode_type")
    if evidence.get("schema_version") != 1:
        issues.append("episode_schema_version")
    if evidence.get("task_id") != task_id:
        issues.append("task_id")
    if evidence.get("protocol_id") != PROTOCOL["id"]:
        issues.append("protocol_id")
    if evidence.get("protocol_sha256") != PROTOCOL_SHA256:
        issues.append("protocol_sha256")
    if not str(evidence.get("session_id") or "").strip():
        issues.append("session_id")
    if not str(evidence.get("episode_id") or "").strip():
        issues.append("episode_id")
    session_hash = str(evidence.get("session_sha256") or "")
    if len(session_hash) != 64 or any(character not in "0123456789abcdef" for character in session_hash):
        issues.append("session_sha256")
    if evidence.get("evidence_kind") != PROTOCOL["evidence_policy"]["live_evidence_kind"]:
        issues.append("live_evidence_required")
    eligibility = evidence.get("eligibility") if isinstance(evidence.get("eligibility"), dict) else {}
    for key in ("passed", "protocol_match", "reset_clean", "no_forbidden_intervention", "no_post_deadline_action"):
        if eligibility.get(key) is not True:
            issues.append(f"eligibility:{key}")
    if evidence.get("reset_contamination") is not False:
        issues.append("reset_contamination")
    if evidence.get("post_deadline_action_count") != 0:
        issues.append("post_deadline_action_count")
    if evidence.get("forbidden_interventions") != []:
        issues.append("forbidden_interventions")
    selected_skills = evidence.get("selected_skills") if isinstance(evidence.get("selected_skills"), list) else []
    if any(isinstance(skill, dict) and skill.get("status") == "quarantined" for skill in selected_skills):
        issues.append("quarantined_skill_selected")
    return issues


def _validate_transition_deadline(
    issues: list[str],
    transition: dict,
    deadline: float | None,
    prefix: str,
) -> None:
    started = _finite_number(transition.get("action_started_monotonic"))
    finished = _finite_number(transition.get("action_finished_monotonic"))
    _require_issue(issues, f"{prefix}:action_start_time", started is not None)
    _require_issue(issues, f"{prefix}:action_finish_time", finished is not None)
    _require_issue(issues, f"{prefix}:action_time_order", started is not None and finished is not None and finished >= started)
    if deadline is None:
        issues.append(f"{prefix}:episode_deadline")
    else:
        _require_issue(issues, f"{prefix}:action_before_deadline", finished is not None and finished <= deadline)


def _sp001_source_candidates(observation: dict, excluded: set[str]) -> list[dict]:
    values = observation.get("observed_blocks")
    if not isinstance(values, list):
        return []
    player = observation.get("position") if isinstance(observation.get("position"), dict) else {}
    allowlist = set(PROTOCOL["fixture_policy"]["cobblestone_sources"]["block_allowlist"])
    radius = float(PROTOCOL["fixture_policy"]["cobblestone_sources"]["search_radius"])
    candidates = []
    for value in values:
        if not isinstance(value, dict):
            continue
        source_id = str(value.get("source_id") or "")
        name = str(value.get("name") or "")
        position = value.get("position") if isinstance(value.get("position"), dict) else {}
        if not source_id or source_id in excluded or name not in allowlist:
            continue
        if value.get("observed") is not True or value.get("reachable") is not True:
            continue
        coordinates = [_finite_number(position.get(axis)) for axis in ("x", "y", "z")]
        if any(coordinate is None for coordinate in coordinates):
            continue
        normalized_position = dict(zip(("x", "y", "z"), coordinates))
        distance = _distance(player, normalized_position)
        if distance > radius:
            continue
        candidates.append({
            "source_id": source_id,
            "name": name,
            "position": normalized_position,
            "distance": round(distance, 6),
        })
    candidates.sort(key=lambda item: (
        item["distance"],
        item["source_id"],
        item["position"]["x"],
        item["position"]["y"],
        item["position"]["z"],
    ))
    return candidates


def _table_observed(observation: dict) -> bool:
    blocks = observation.get("nearby_blocks")
    if not isinstance(blocks, list):
        return False
    maximum = float(PROTOCOL["fixture_policy"]["nearby_crafting_table"]["maximum_distance"])
    for block in blocks:
        if not isinstance(block, dict) or block.get("name") != "crafting_table":
            continue
        distance = _finite_number(block.get("distance"))
        if block.get("observed") is True and block.get("interactive") is True and distance is not None and distance <= maximum:
            return True
    return False


def _inventory(observation: Any) -> dict[str, int]:
    if not isinstance(observation, dict) or not isinstance(observation.get("inventory"), dict):
        return {}
    return {str(item): _count(count) for item, count in observation["inventory"].items()}


def _count(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    if not math.isfinite(number) or number < 0:
        return 0
    return int(number)


def _strict_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _distance(left: dict, right: dict) -> float:
    values = []
    for axis in ("x", "y", "z"):
        left_value = _finite_number(left.get(axis))
        right_value = _finite_number(right.get(axis))
        values.append((left_value or 0.0) - (right_value or 0.0))
    return math.sqrt(sum(value * value for value in values))


def _plan_fallback(reason: str, issues: list[str] | None = None) -> dict:
    return {
        "status": "fallback",
        "reasoning": reason,
        "fallback_reason": reason,
        "issues": list(issues or []),
        "actions": [],
        "requires_reobservation": False,
    }


def _require_issue(issues: list[str], name: str, passed: bool) -> None:
    if not passed:
        issues.append(name)


def _matching_key_paths(value: Any, names: set[str], path: str = "template") -> list[str]:
    found = []
    if isinstance(value, dict):
        for key, nested in value.items():
            key_text = str(key).strip().lower()
            child = f"{path}.{key_text}"
            if key_text in names:
                found.append(child)
            found.extend(_matching_key_paths(nested, names, child))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            found.extend(_matching_key_paths(nested, names, f"{path}[{index}]"))
    return found
