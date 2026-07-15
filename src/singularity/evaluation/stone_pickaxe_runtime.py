"""Controlled runtime helpers for the stone-pickaxe microbenchmarks.

The runtime restores an immutable survival-prepared world snapshot and lets the
normal Agent/Planner choose actions.  This module only supplies protocol gates,
machine observations, evidence adaptation, and snapshot identity checks.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from singularity.core.agent import Agent
from singularity.core.config import BotConfig, Config, LLMConfig
from singularity.core.goal_verifier import GoalVerification
from singularity.evaluation.stone_pickaxe_protocol import (
    PROTOCOL,
    PROTOCOL_SHA256,
    REPOSITORY_ROOT,
    canonical_sha256,
    verify_sp001_episode,
)


RUNTIME_POLICY_ID = "stone-pickaxe-controlled-runtime-v1"
FIXTURE_POLICY_ID = "stone-pickaxe-survival-fixture-preparation-v1"
ACTION_GUARD_POLICY_ID = "stone-pickaxe-action-guard-v1"
SNAPSHOT_POLICY_ID = "stone-pickaxe-immutable-snapshot-v1"
WORLD_COMPONENTS = ("world", "world_nether", "world_the_end")
SP001_GOAL = "Gather 3 cobblestone with the wooden pickaxe"
FIXTURE_GOAL = (
    "Prepare the SP-001 fixture using only normal survival actions: craft exactly "
    "one wooden pickaxe from gathered resources, keep cobblestone and stone_pickaxe "
    "at zero, then move to a safe position with at least three exposed stone blocks "
    "within interaction range. Do not mine stone."
)

LOG_ITEMS = {
    "oak_log",
    "spruce_log",
    "birch_log",
    "jungle_log",
    "acacia_log",
    "dark_oak_log",
    "mangrove_log",
    "cherry_log",
    "crimson_stem",
    "warped_stem",
}
PLANK_ITEMS = {item.replace("_log", "_planks") for item in LOG_ITEMS if item.endswith("_log")}
PLANK_ITEMS.update({"crimson_planks", "warped_planks", "bamboo_planks"})
PREPARATION_DIG_BLOCKS = LOG_ITEMS | {
    "oak_leaves",
    "spruce_leaves",
    "birch_leaves",
    "jungle_leaves",
    "acacia_leaves",
    "dark_oak_leaves",
    "mangrove_leaves",
    "cherry_leaves",
    "dirt",
    "grass_block",
    "coarse_dirt",
    "podzol",
    "rooted_dirt",
    "mud",
    "snow",
    "snow_block",
    "gravel",
    "sand",
}
PREPARATION_CRAFT_ITEMS = PLANK_ITEMS | {"stick", "crafting_table", "wooden_pickaxe"}
NON_MUTATING_ACTIONS = {"move_to", "walk_to", "look_at", "wait", "equip"}
FORBIDDEN_COMMAND_TOKENS = {"give", "teleport", "tp", "gamemode", "setblock"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def repo_relative(path: str | Path) -> str:
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(REPOSITORY_ROOT).as_posix()
    except ValueError as exc:
        raise ValueError(f"path must stay inside repository: {path}") from exc


def write_json(path: str | Path, payload: Any) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    return target


def read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def file_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def snapshot_tree_report(
    snapshot_root: str | Path,
    component_names: dict[str, str] | None = None,
) -> dict:
    """Hash only canonical world components, never helper manifests."""
    root = Path(snapshot_root).resolve()
    issues: list[str] = []
    records: list[dict] = []
    names = dict(component_names or {})
    for component in WORLD_COMPONENTS:
        component_root = root / str(names.get(component) or component)
        if not component_root.is_dir():
            issues.append(f"missing_component:{component}")
            continue
        for path in sorted(component_root.rglob("*"), key=lambda value: value.as_posix()):
            if path.is_symlink():
                issues.append(f"symlink_forbidden:{path.relative_to(root).as_posix()}")
                continue
            if not path.is_file():
                continue
            relative = f"{component}/{path.relative_to(component_root).as_posix()}"
            records.append({
                "path": relative,
                "size": path.stat().st_size,
                "sha256": file_sha256(path),
            })
    identity_payload = [
        [record["path"], record["size"], record["sha256"]]
        for record in records
    ]
    return {
        "type": "stone_pickaxe_snapshot_tree_report",
        "schema_version": 1,
        "policy_id": SNAPSHOT_POLICY_ID,
        "passed": not issues and bool(records),
        "issues": issues,
        "components": list(WORLD_COMPONENTS),
        "file_count": len(records),
        "total_bytes": sum(record["size"] for record in records),
        "tree_sha256": canonical_sha256(identity_payload),
    }


def source_id(name: str, position: Any) -> str:
    value = position if isinstance(position, dict) else {}
    coordinates = []
    for axis in ("x", "y", "z"):
        number = _finite(value.get(axis))
        if number is None:
            return ""
        coordinates.append(str(round(number)))
    return f"{str(name or '').strip()}:{':'.join(coordinates)}"


def evidence_observation(
    observation: Any,
    *,
    role: str,
    ordinal: int,
    monotonic_s: float,
    source_state: dict | None = None,
) -> dict:
    raw = observation if isinstance(observation, dict) else {}
    inventory = raw.get("inventory") if isinstance(raw.get("inventory"), dict) else {}
    position = raw.get("position") if isinstance(raw.get("position"), dict) else {}
    interaction_range = float(
        PROTOCOL["fixture_policy"]["cobblestone_sources"]["interaction_range"]
    )
    search_radius = float(
        PROTOCOL["fixture_policy"]["cobblestone_sources"]["search_radius"]
    )
    observed_blocks = []
    for block in raw.get("nearby_blocks", []) if isinstance(raw.get("nearby_blocks"), list) else []:
        if not isinstance(block, dict) or block.get("name") != "stone":
            continue
        block_position = block.get("position") if isinstance(block.get("position"), dict) else {}
        identifier = source_id("stone", block_position)
        distance = _finite(block.get("distance"))
        if not identifier or distance is None or distance > search_radius:
            continue
        observed_blocks.append({
            "source_id": identifier,
            "name": "stone",
            "position": _compact_position(block_position),
            "distance": round(distance, 6),
            "observed": True,
            "reachable": distance <= interaction_range,
        })
    observed_blocks.sort(key=lambda item: (item["distance"], item["source_id"]))
    hostiles = [
        entity
        for entity in raw.get("nearby_entities", [])
        if isinstance(entity, dict)
        and entity.get("hostile") is True
        and (_finite(entity.get("distance")) or 0.0) <= 8.0
    ]
    health = _finite(raw.get("health"))
    safe = bool(
        health is not None
        and health > 0
        and raw.get("game_mode") == "survival"
        and not hostiles
    )
    ground = str(raw.get("ground_block") or "")
    movable = bool(
        safe
        and all(_finite(position.get(axis)) is not None for axis in ("x", "y", "z"))
        and ground not in {"", "air", "lava", "water"}
    )
    compact = {
        "role": str(role),
        "monotonic_s": float(monotonic_s),
        "position": _compact_position(position),
        "inventory": {str(key): _count(value) for key, value in sorted(inventory.items())},
        "health": health,
        "hunger": _finite(raw.get("hunger")),
        "game_mode": str(raw.get("game_mode") or ""),
        "dimension": str(raw.get("dimension") or ""),
        "ground_block": ground,
        "safe": safe,
        "movable": movable,
        "observed_blocks": observed_blocks,
        "nearby_hostile_count": len(hostiles),
        "player_lifecycle": dict(raw.get("player_lifecycle") or {}),
    }
    if isinstance(source_state, dict):
        compact["source"] = dict(source_state)
    compact["observation_id"] = canonical_sha256({
        "role": str(role),
        "ordinal": int(ordinal),
        "observation": compact,
    })
    return compact


def audit_sp001_fixture(observation: Any) -> dict:
    normalized = evidence_observation(
        observation,
        role="fixture_audit",
        ordinal=0,
        monotonic_s=0.0,
    )
    inventory = normalized["inventory"]
    reachable = [
        block
        for block in normalized["observed_blocks"]
        if block.get("reachable") is True
    ]
    checks = {
        "wooden_pickaxe_exact": inventory.get("wooden_pickaxe", 0) == 1,
        "cobblestone_absent": inventory.get("cobblestone", 0) == 0,
        "stone_pickaxe_absent": inventory.get("stone_pickaxe", 0) == 0,
        "survival_mode": normalized.get("game_mode") == "survival",
        "safe": normalized.get("safe") is True,
        "movable": normalized.get("movable") is True,
        "three_reachable_observed_stone_sources": len(reachable) >= 3,
    }
    return {
        "type": "stone_pickaxe_fixture_machine_audit",
        "schema_version": 1,
        "policy_id": FIXTURE_POLICY_ID,
        "passed": all(checks.values()),
        "checks": checks,
        "issues": sorted(key for key, passed in checks.items() if not passed),
        "observation": normalized,
        "reachable_source_count": len(reachable),
        "reachable_sources": reachable,
        "counts_toward_skill_gate": False,
        "counts_toward_capability": False,
        "counts_toward_m4": False,
    }


def guard_runtime_action(mode: str, action: Any, observation: Any) -> dict:
    value = action if isinstance(action, dict) else {}
    params = value.get("parameters") if isinstance(value.get("parameters"), dict) else {}
    action_type = str(value.get("type") or "")
    normalized_mode = str(mode or "").strip().lower()
    issues: list[str] = []
    normalized_action = {
        "type": action_type,
        "parameters": dict(params),
    }
    selected_source = {}

    if normalized_mode == "sp001":
        if action_type == "dig":
            if params.get("block") != "stone":
                issues.append("sp001_dig_requires_exact_stone")
            candidates = _observed_stone_candidates(observation, reachable_only=True)
            target_id = source_id("stone", params)
            matching = [item for item in candidates if item["source_id"] == target_id]
            if not target_id or not matching:
                issues.append("sp001_dig_target_must_be_reachable_and_observed")
            elif candidates[0]["source_id"] != target_id:
                issues.append("sp001_dig_target_must_be_nearest_observed")
            else:
                selected_source = matching[0]
                normalized_action["parameters"]["source_id"] = target_id
            inventory = observation.get("inventory", {}) if isinstance(observation, dict) else {}
            if _count(inventory.get("wooden_pickaxe")) != 1:
                issues.append("sp001_exact_wooden_pickaxe_required")
        elif action_type == "equip":
            if params.get("item") != "wooden_pickaxe":
                issues.append("sp001_only_wooden_pickaxe_may_be_equipped")
        elif action_type in {"move_to", "walk_to", "look_at", "wait"}:
            issues.extend(_non_mutating_action_issues(action_type, params, observation, 32.0))
        else:
            issues.append(f"sp001_action_type_forbidden:{action_type or 'missing'}")
    elif normalized_mode == "prepare_fixture":
        if action_type == "dig":
            block = str(params.get("block") or "")
            if block not in PREPARATION_DIG_BLOCKS:
                issues.append(f"fixture_dig_block_forbidden:{block or 'missing'}")
        elif action_type == "craft":
            item = str(params.get("item") or "")
            if item not in PREPARATION_CRAFT_ITEMS:
                issues.append(f"fixture_craft_item_forbidden:{item or 'missing'}")
            inventory = observation.get("inventory", {}) if isinstance(observation, dict) else {}
            if item == "wooden_pickaxe" and _count(inventory.get("wooden_pickaxe")) >= 1:
                issues.append("fixture_duplicate_wooden_pickaxe_forbidden")
        elif action_type == "place":
            if params.get("item") != "crafting_table":
                issues.append("fixture_only_crafting_table_placement_allowed")
        elif action_type in NON_MUTATING_ACTIONS:
            issues.extend(_non_mutating_action_issues(action_type, params, observation, 64.0))
        else:
            issues.append(f"fixture_action_type_forbidden:{action_type or 'missing'}")
    else:
        issues.append("unsupported_runtime_mode")

    return {
        "type": "stone_pickaxe_action_guard",
        "schema_version": 1,
        "policy_id": ACTION_GUARD_POLICY_ID,
        "mode": normalized_mode,
        "allowed": not issues,
        "issues": issues,
        "action": normalized_action,
        "selected_source": selected_source,
        "runtime_influence": True,
    }


class StonePickaxeRuntimeAgent(Agent):
    """Agent with protocol action guards; action choice remains Planner-owned."""

    def __init__(self, config: Config, runtime_mode: str):
        self.stone_pickaxe_runtime_mode = str(runtime_mode or "").strip().lower()
        super().__init__(config)

    def _observe(self) -> dict:
        observation = super()._observe()
        scan = self.bot.get_nearby_blocks(
            radius=int(PROTOCOL["fixture_policy"]["cobblestone_sources"]["search_radius"])
        )
        if isinstance(scan, list):
            observation = dict(observation)
            observation["nearby_blocks"] = scan[:50]
        return observation

    def _verify_action_for_execution(
        self,
        action: dict,
        observation: dict,
        goal: str,
        context: dict = None,
    ):
        guard = guard_runtime_action(
            self.stone_pickaxe_runtime_mode,
            action,
            observation,
        )
        self.session_logger.log(
            "stone_pickaxe_action_guard",
            {"goal": goal, "context": context or {}, **guard},
            level="INFO" if guard["allowed"] else "ERROR",
        )
        if not guard["allowed"]:
            verification = {
                "action_type": str(action.get("type") or "unknown"),
                "status": "reject",
                "score": 0.0,
                "reason": "; ".join(guard["issues"]),
                "policy_id": ACTION_GUARD_POLICY_ID,
                "guard": guard,
            }
            return verification, {
                "success": False,
                "error": f"Stone-pickaxe action guard rejected: {verification['reason']}",
                "action_type": verification["action_type"],
                "duration_ms": 0,
                "action_verification": verification,
                "verification_blocked": True,
            }
        normalized = guard.get("action", {})
        if isinstance(normalized, dict):
            action.clear()
            action.update(normalized)
        return super()._verify_action_for_execution(action, observation, goal, context)

    def _goal_is_verified(
        self,
        goal: str,
        observation: dict,
        context: dict = None,
        recent_actions: list[dict] = None,
    ):
        if self.stone_pickaxe_runtime_mode != "prepare_fixture":
            return super()._goal_is_verified(goal, observation, context, recent_actions)
        if self._episode_deadline_reached():
            return False, self._deadline_goal_verification(
                goal,
                context,
                "fixture_goal_verifier",
            )
        audit = audit_sp001_fixture(observation)
        verification = GoalVerification(
            goal=goal,
            achieved=audit["passed"],
            status="achieved" if audit["passed"] else "failed",
            confidence=1.0,
            evidence=[
                "exact wooden_pickaxe and zero target inventory verified",
                f"reachable observed stone sources={audit['reachable_source_count']}",
            ] if audit["passed"] else [],
            missing=list(audit["issues"]),
            matched_rules=["stone_pickaxe:fixture_machine_audit"],
            target_inventory={"wooden_pickaxe": 1, "cobblestone": 0, "stone_pickaxe": 0},
            critic={"fixture_machine_audit": audit},
        )
        self._log_goal_verification(
            verification,
            {**(context or {}), "accepted": audit["passed"]},
        )
        return audit["passed"], verification


def build_runtime_config(
    *,
    api_key: str,
    log_dir: str,
    host: str,
    port: int,
    username: str,
    bridge_host: str,
    bridge_port: int,
) -> Config:
    planner = PROTOCOL["planner"]
    environment = PROTOCOL["environment"]
    return Config(
        bot=BotConfig(
            host=host,
            port=int(port),
            username=username,
            version=environment["minecraft_version"],
            bridge_host=bridge_host,
            bridge_port=int(bridge_port),
        ),
        llm=LLMConfig(
            provider=planner["provider"],
            model=planner["model"],
            api_key=api_key,
            base_url=planner["base_url"],
            max_tokens=int(planner["max_tokens"]),
            temperature=float(planner["temperature"]),
        ),
        log_dir=log_dir,
        planner_protocol=PROTOCOL["id"],
        require_llm_root_plan=True,
        skill_execution_mode="off",
        enable_skill_candidate_extraction=False,
        enable_policy_skills=False,
        enable_skill_frontier_routing=False,
        enable_memory_policy=False,
        enable_memory_persistence=False,
        enable_planning_memory_context=False,
        enable_task_memory_context=False,
        enable_task_continuity_context=False,
        enable_task_readiness_context=False,
        enable_task_readiness_recovery=False,
        enable_bounded_planning_context=False,
        enable_skill_memory_context=False,
        enable_curriculum_planner_context=False,
        enable_knowledge_correction_context=False,
        enable_task_precondition_context=False,
        enable_weighted_memory_retrieval=False,
        enable_coaching_policy=False,
        enable_vision_analysis=False,
        enable_visual_action_grounding=False,
        enable_screenshot_capture=False,
        enable_goal_critic=False,
        enable_self_evolution_policy=False,
        enable_world_model_curriculum_feedback=False,
        enable_action_candidate_selection=False,
        enable_blocked_plan_rule_fallback=False,
        enable_plan_cache=False,
        episode_abort_mode="off",
        frontier_budget_mode="off",
        enable_autocurriculum=False,
        enable_goal_verification=True,
        enable_action_verification=True,
        enforce_action_verification=True,
        max_action_timeout=int(
            float(PROTOCOL["deadline_policy"]["per_action_timeout_s"]) * 1000
        ),
    )


def runtime_controls(config: Config) -> dict:
    return {
        "planner_protocol": str(config.planner_protocol),
        "require_llm_root_plan": bool(config.require_llm_root_plan),
        "skill_execution_mode": str(config.skill_execution_mode),
        "skill_candidate_extraction": bool(config.enable_skill_candidate_extraction),
        "policy_skills": bool(config.enable_policy_skills),
        "memory_persistence": bool(config.enable_memory_persistence),
        "planning_memory_context": bool(config.enable_planning_memory_context),
        "task_memory_context": bool(config.enable_task_memory_context),
        "task_continuity_context": bool(config.enable_task_continuity_context),
        "vision_analysis": bool(config.enable_vision_analysis),
        "visual_action_grounding": bool(config.enable_visual_action_grounding),
        "goal_verification": bool(config.enable_goal_verification),
        "action_verification": bool(config.enable_action_verification),
        "action_verification_enforced": bool(config.enforce_action_verification),
        "action_candidate_selection": bool(config.enable_action_candidate_selection),
        "automatic_retry": False,
        "external_step_script": False,
    }


def build_fixture_artifact(
    preparation: dict,
    snapshot_report: dict,
    *,
    snapshot_path: str,
) -> dict:
    audit = preparation.get("fixture_audit", {}) if isinstance(preparation, dict) else {}
    checks = {
        "protocol_identity": preparation.get("protocol_sha256") == PROTOCOL_SHA256,
        "preparation_machine_audit": audit.get("passed") is True,
        "survival_preparation": preparation.get("game_mode") == "survival",
        "normal_agent_actions": preparation.get("external_step_script") is False,
        "no_forbidden_intervention": preparation.get("forbidden_interventions") == [],
        "no_target_result_injection": preparation.get("target_result_injection") is False,
        "snapshot_tree": snapshot_report.get("passed") is True,
    }
    return {
        "type": "stone_pickaxe_fixture_manifest",
        "schema_version": 1,
        "generated_at_utc": utc_now(),
        "fixture_id": "sp001-acquire-cobblestone-v1",
        "policy_id": FIXTURE_POLICY_ID,
        "protocol_id": PROTOCOL["id"],
        "protocol_sha256": PROTOCOL_SHA256,
        "snapshot": {
            "policy_id": SNAPSHOT_POLICY_ID,
            "path": str(snapshot_path).replace("\\", "/"),
            "tree_sha256": snapshot_report.get("tree_sha256", ""),
            "file_count": snapshot_report.get("file_count", 0),
            "total_bytes": snapshot_report.get("total_bytes", 0),
            "components": list(snapshot_report.get("components", [])),
            "immutable": True,
            "restoration_only": True,
        },
        "preparation": {
            "session_id": str(preparation.get("session_id") or ""),
            "episode_id": str(preparation.get("episode_id") or ""),
            "level_name": str(preparation.get("level_name") or ""),
            "evidence_path": str(preparation.get("evidence_path") or ""),
            "goal": str(preparation.get("goal") or ""),
            "machine_audit": audit,
            "administrative_commands": list(preparation.get("administrative_commands", [])),
        },
        "checks": checks,
        "snapshot_identity_verified": all(checks.values()),
        "issues": sorted(key for key, passed in checks.items() if not passed),
        "counts_toward_skill_gate": False,
        "counts_toward_capability": False,
        "counts_toward_m4": False,
    }


def build_sp001_episode(
    *,
    episode_id: str,
    session_id: str,
    session_sha256: str,
    events: list[dict],
    initial_observation: dict,
    terminal_observation: dict,
    initial_monotonic: float,
    terminal_monotonic: float,
    goal_result: dict,
    fixture_manifest: dict,
    hypothesis_path: str,
    level_name: str,
) -> dict:
    action_events = [
        event
        for event in events
        if isinstance(event, dict)
        and event.get("type") == "action"
        and isinstance(event.get("data"), dict)
    ]
    deadline = _finite(goal_result.get("episode_deadline_monotonic"))
    transitions = []
    action_failures = []
    false_success_digs = []
    non_target_mutations = []
    post_deadline_actions = []
    forbidden_interventions = []
    for index, event in enumerate(action_events, start=1):
        data = event["data"]
        action = data.get("action") if isinstance(data.get("action"), dict) else {}
        params = action.get("parameters") if isinstance(action.get("parameters"), dict) else {}
        result = data.get("result") if isinstance(data.get("result"), dict) else {}
        action_type = str(action.get("type") or "")
        if result.get("success") is not True:
            action_failures.append({
                "index": index,
                "action": action,
                "error": str(result.get("error") or "action_not_successful"),
            })
        finished = _finite(result.get("action_finished_monotonic"))
        started = _finite(result.get("action_started_monotonic"))
        if finished is None:
            elapsed = _finite(event.get("elapsed_s")) or 0.0
            finished = float(goal_result.get("episode_started_monotonic") or initial_monotonic) + elapsed
        if started is None:
            started = finished - max(0, _count(result.get("duration_ms"))) / 1000.0
        if (
            result.get("accepted_within_episode_deadline") is False
            or (deadline is not None and finished > deadline)
        ):
            post_deadline_actions.append(index)
        if action_type == "chat":
            message = str(params.get("message") or "").strip().lower().lstrip("/")
            token = message.split(" ", 1)[0]
            if token in FORBIDDEN_COMMAND_TOKENS:
                forbidden_interventions.append({"index": index, "command": token})
        if result.get("success") is True and action_type in {"place", "build_shelter_5x5", "build_shelter_cell"}:
            non_target_mutations.append({"index": index, "action": action})
        if action_type == "dig":
            block = str(result.get("block") or params.get("block") or "")
            target = result.get("target") if isinstance(result.get("target"), dict) else params
            identifier = str(params.get("source_id") or source_id(block, target))
            before_source = {
                "id": identifier,
                "name": block,
                "present": (
                    result.get("target_block_before", {}).get("name") == block
                    if isinstance(result.get("target_block_before"), dict)
                    else False
                ),
                "position": _compact_position(target),
            }
            after_block = result.get("target_block_after", {}) if isinstance(result.get("target_block_after"), dict) else {}
            after_source = {
                "id": identifier,
                "name": block,
                "present": after_block.get("name") == block,
                "position": _compact_position(target),
            }
            pre = evidence_observation(
                data.get("pre_observation"),
                role="pre_dig",
                ordinal=index,
                monotonic_s=started,
                source_state=before_source,
            )
            post = evidence_observation(
                data.get("post_observation"),
                role="post_dig",
                ordinal=index,
                monotonic_s=finished,
                source_state=after_source,
            )
            pickup_delta = result.get("pickup_inventory_delta") if isinstance(result.get("pickup_inventory_delta"), dict) else {}
            tool = result.get("dig_tool_equip") if isinstance(result.get("dig_tool_equip"), dict) else {}
            verification = result.get("action_verification") if isinstance(result.get("action_verification"), dict) else {}
            transition_action = {
                "type": "dig",
                "parameters": {
                    "block": block,
                    "source_id": identifier,
                    **_compact_position(target),
                },
            }
            transition = {
                "source_id": identifier,
                "source_block": block,
                "tool": str(tool.get("equipped_tool") or tool.get("selected_tool") or ""),
                "action_verified": bool(
                    result.get("success") is True
                    and verification.get("status") == "accept"
                    and tool.get("passed") is True
                ),
                "action": transition_action,
                "pre_observation": pre,
                "post_observation": post,
                "pickup": {
                    "observed": result.get("pickup_observed") is True,
                    "source_id": identifier,
                    "item": "cobblestone",
                    "count": _count(pickup_delta.get("cobblestone")),
                    "inventory_delta": dict(pickup_delta),
                },
                "action_started_monotonic": started,
                "action_finished_monotonic": finished,
                "backend_result": {
                    "success": result.get("success") is True,
                    "block_removed": result.get("block_removed") is True,
                    "expected_drops": list(result.get("expected_drops", [])),
                    "dig_postcondition": dict(result.get("dig_postcondition") or {}),
                    "dig_tool_equip": dict(tool),
                },
            }
            transitions.append(transition)
            if result.get("success") is True and not (
                result.get("block_removed") is True
                and result.get("pickup_observed") is True
                and _count(pickup_delta.get("cobblestone")) >= 1
            ):
                false_success_digs.append(index)
            if result.get("success") is True and block != "stone":
                non_target_mutations.append({"index": index, "action": action, "observed_block": block})

    selected_skills = []
    for event in events:
        if not isinstance(event, dict) or event.get("type") != "skill_selected":
            continue
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        skill = data.get("skill") if isinstance(data.get("skill"), dict) else {}
        selected_skills.append({
            "skill_id": str(skill.get("skill_id") or data.get("skill_id") or ""),
            "version": str(skill.get("version") or data.get("version") or ""),
            "status": str(skill.get("status") or data.get("status") or ""),
        })
    initial = evidence_observation(
        initial_observation,
        role="initial",
        ordinal=0,
        monotonic_s=initial_monotonic,
    )
    terminal = evidence_observation(
        terminal_observation,
        role="terminal",
        ordinal=len(action_events) + 1,
        monotonic_s=terminal_monotonic,
    )
    fixture_snapshot = fixture_manifest.get("snapshot", {}) if isinstance(fixture_manifest, dict) else {}
    fixture_verified = fixture_manifest.get("snapshot_identity_verified") is True
    protocol_match = fixture_manifest.get("protocol_sha256") == PROTOCOL_SHA256
    eligibility = {
        "passed": bool(
            fixture_verified
            and protocol_match
            and not forbidden_interventions
            and not post_deadline_actions
            and not selected_skills
        ),
        "protocol_match": protocol_match,
        "reset_clean": fixture_verified,
        "no_forbidden_intervention": not forbidden_interventions,
        "no_post_deadline_action": not post_deadline_actions,
        "fixture_snapshot_tree_sha256": fixture_snapshot.get("tree_sha256", ""),
    }
    return {
        "type": "stone_pickaxe_microbenchmark_episode",
        "schema_version": 1,
        "protocol_id": PROTOCOL["id"],
        "protocol_sha256": PROTOCOL_SHA256,
        "task_id": "SP-001",
        "session_id": str(session_id),
        "episode_id": str(episode_id),
        "session_sha256": str(session_sha256),
        "level_name": str(level_name),
        "evidence_kind": PROTOCOL["evidence_policy"]["live_evidence_kind"],
        "hypothesis_path": str(hypothesis_path).replace("\\", "/"),
        "fixture": {
            "fixture_id": fixture_manifest.get("fixture_id", ""),
            "manifest_protocol_sha256": fixture_manifest.get("protocol_sha256", ""),
            "snapshot_tree_sha256": fixture_snapshot.get("tree_sha256", ""),
            "snapshot_identity_verified": fixture_verified,
        },
        "episode_started_monotonic": goal_result.get("episode_started_monotonic"),
        "episode_deadline_monotonic": goal_result.get("episode_deadline_monotonic"),
        "episode_ended_monotonic": terminal_monotonic,
        "deadline_policy_id": goal_result.get("deadline_policy_id", ""),
        "action_count": len(action_events),
        "action_failure_count": len(action_failures),
        "action_failures": action_failures,
        "false_success_dig_count": len(false_success_digs),
        "false_success_dig_action_indexes": false_success_digs,
        "world_mutating_non_target_actions": non_target_mutations,
        "initial_observation": initial,
        "transitions": transitions,
        "terminal_observation": terminal,
        "goal_result": dict(goal_result),
        "eligibility": eligibility,
        "reset_contamination": False,
        "post_deadline_action_count": len(post_deadline_actions),
        "post_deadline_action_indexes": post_deadline_actions,
        "forbidden_interventions": forbidden_interventions,
        "selected_skills": selected_skills,
        "external_step_script": False,
        "counts_toward_capability": False,
        "counts_toward_m4": False,
    }


def build_sp001_run_audit(
    episode: dict,
    verification: dict,
    events: list[dict],
    task_graph: dict,
) -> dict:
    failed = list(episode.get("action_failures", []))
    plans = [
        event.get("data", {})
        for event in events
        if isinstance(event, dict)
        and event.get("type") == "plan"
        and isinstance(event.get("data"), dict)
    ]
    first_failure = failed[0] if failed else {}
    earliest = {}
    if first_failure:
        earliest = {
            "event_type": "action",
            "action_index": first_failure.get("index"),
            "action": first_failure.get("action", {}),
            "error": first_failure.get("error", ""),
            "recovered": False,
        }
    elif not verification.get("passed"):
        earliest = {
            "event_type": "machine_verification",
            "issues": list(verification.get("criteria_issues", []))
            + list(verification.get("eligibility_issues", [])),
            "recovered": False,
        }
    next_fix = "none_episode_passed"
    if not verification.get("passed"):
        joined = " ".join(
            list(verification.get("criteria_issues", []))
            + [str(first_failure.get("error") or "")]
        ).lower()
        if "fixture" in joined or "initial_reachable_source" in joined:
            next_fix = "offline_fixture_source_visibility_or_reachability"
        elif "guard" in joined or "nearest_observed" in joined:
            next_fix = "offline_planner_action_grounding_for_nearest_observed_stone"
        elif "pickup" in joined or "inventory_delta" in joined:
            next_fix = "offline_dig_pickup_postcondition_binding"
        elif "deadline" in joined:
            next_fix = "offline_deadline_budgeting"
        else:
            next_fix = "offline_first_failed_transition_reproduction"
    return {
        "type": "stone_pickaxe_run_audit",
        "schema_version": 1,
        "task_id": "SP-001",
        "episode_id": episode.get("episode_id", ""),
        "machine_verification_passed": verification.get("passed") is True,
        "evidence_eligible": verification.get("evidence_eligible") is True,
        "earliest_unrecovered_transition": earliest,
        "first_failed_action": first_failure,
        "planner_decision": plans[-1] if plans else {},
        "task_graph_state": task_graph,
        "deadline_state": {
            "policy_id": episode.get("deadline_policy_id", ""),
            "started_monotonic": episode.get("episode_started_monotonic"),
            "deadline_monotonic": episode.get("episode_deadline_monotonic"),
            "ended_monotonic": episode.get("episode_ended_monotonic"),
            "post_deadline_action_count": episode.get("post_deadline_action_count", 0),
        },
        "evidence_eligibility": {
            "passed": verification.get("evidence_eligible") is True,
            "criteria_issues": list(verification.get("criteria_issues", [])),
            "eligibility_issues": list(verification.get("eligibility_issues", [])),
        },
        "single_next_offline_fix": next_fix,
        "automatic_retry_allowed": False,
    }


def task_graph_snapshot(agent: Any) -> dict:
    system = getattr(agent, "task_system", None)
    tasks = getattr(system, "tasks", {}) if system is not None else {}
    records = []
    for task_id, task in sorted(tasks.items() if isinstance(tasks, dict) else []):
        if is_dataclass(task):
            value = asdict(task)
        else:
            value = dict(getattr(task, "__dict__", {}) or {})
        status = value.get("status")
        value["status"] = getattr(status, "value", str(status or ""))
        value["id"] = str(value.get("id") or task_id)
        records.append(value)
    transitions = list(getattr(system, "_transition_events", []) or []) if system is not None else []
    return {
        "task_count": len(records),
        "tasks": records,
        "transition_count": len(transitions),
        "transitions": transitions,
        "sha256": canonical_sha256({"tasks": records, "transitions": transitions}),
    }


def verify_fixture_manifest(manifest: Any, snapshot_root: str | Path) -> dict:
    value = manifest if isinstance(manifest, dict) else {}
    tree = snapshot_tree_report(snapshot_root)
    snapshot = value.get("snapshot") if isinstance(value.get("snapshot"), dict) else {}
    checks = {
        "manifest_type": value.get("type") == "stone_pickaxe_fixture_manifest",
        "manifest_schema": value.get("schema_version") == 1,
        "protocol_id": value.get("protocol_id") == PROTOCOL["id"],
        "protocol_sha256": value.get("protocol_sha256") == PROTOCOL_SHA256,
        "manifest_verified": value.get("snapshot_identity_verified") is True,
        "tree_report": tree.get("passed") is True,
        "tree_sha256": tree.get("tree_sha256") == snapshot.get("tree_sha256"),
        "file_count": tree.get("file_count") == snapshot.get("file_count"),
        "total_bytes": tree.get("total_bytes") == snapshot.get("total_bytes"),
    }
    return {
        "type": "stone_pickaxe_fixture_preflight",
        "schema_version": 1,
        "passed": all(checks.values()),
        "checks": checks,
        "issues": sorted(key for key, passed in checks.items() if not passed),
        "tree": tree,
        "expected_tree_sha256": snapshot.get("tree_sha256", ""),
    }


def verify_sp001_runtime_episode(episode: dict) -> dict:
    return verify_sp001_episode(episode)


def _observed_stone_candidates(observation: Any, *, reachable_only: bool) -> list[dict]:
    raw = observation if isinstance(observation, dict) else {}
    interaction_range = float(
        PROTOCOL["fixture_policy"]["cobblestone_sources"]["interaction_range"]
    )
    search_radius = float(
        PROTOCOL["fixture_policy"]["cobblestone_sources"]["search_radius"]
    )
    candidates = []
    for block in raw.get("nearby_blocks", []) if isinstance(raw.get("nearby_blocks"), list) else []:
        if not isinstance(block, dict) or block.get("name") != "stone":
            continue
        position = block.get("position") if isinstance(block.get("position"), dict) else {}
        identifier = source_id("stone", position)
        distance = _finite(block.get("distance"))
        if not identifier or distance is None or distance > search_radius:
            continue
        if reachable_only and distance > interaction_range:
            continue
        candidates.append({
            "source_id": identifier,
            "name": "stone",
            "position": _compact_position(position),
            "distance": distance,
        })
    candidates.sort(key=lambda item: (item["distance"], item["source_id"]))
    return candidates


def _non_mutating_action_issues(
    action_type: str,
    params: dict,
    observation: Any,
    maximum_distance: float,
) -> list[str]:
    if action_type == "wait":
        duration = _finite(params.get("ms"))
        return [] if duration is not None and 0 <= duration <= 1000 else ["wait_must_be_bounded_to_1000ms"]
    if action_type == "equip":
        return [] if str(params.get("item") or "") else ["equip_item_required"]
    required = ("x", "z") if action_type in {"move_to", "walk_to"} else ("x", "y", "z")
    if any(_finite(params.get(axis)) is None for axis in required):
        return [f"{action_type}_finite_coordinates_required"]
    current = observation.get("position", {}) if isinstance(observation, dict) else {}
    if all(_finite(current.get(axis)) is not None for axis in ("x", "z")):
        distance = math.hypot(
            float(params["x"]) - float(current["x"]),
            float(params["z"]) - float(current["z"]),
        )
        if distance > maximum_distance:
            return [f"{action_type}_outside_bounded_radius"]
    return []


def _compact_position(value: Any) -> dict:
    position = value if isinstance(value, dict) else {}
    compact = {}
    for axis in ("x", "y", "z"):
        number = _finite(position.get(axis))
        if number is not None:
            compact[axis] = round(number, 6)
    return compact


def _finite(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


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
