"""Machine-verifiable SP-004 progression from a stone pickaxe to an iron pickaxe."""

from __future__ import annotations

import copy
import json
import math
from collections import Counter
from dataclasses import replace
from typing import Any

from singularity.core.agent import Agent
from singularity.core.config import Config
from singularity.core.goal_verifier import GoalVerification
from singularity.core.planner import Planner
from singularity.core.runtime import InterruptDecision, RuntimeSupervisor


SP004_GOAL = (
    "Starting with a stone pickaxe, mine exactly 8 stone, 10 coal ore, and "
    "3 iron ore; find or make a crafting table; craft and place a furnace; "
    "smelt the 3 raw iron with coal; and craft an iron pickaxe."
)
SP004_RUNTIME_POLICY_ID = "iron-pickaxe-sp004-stone-to-iron-runtime-v1"
SP004_ACTION_GUARD_POLICY_ID = "iron-pickaxe-sp004-action-guard-v1"
SP004_MACHINE_VERIFIER_ID = "iron-pickaxe-sp004-machine-verifier-v1"
SP004_RESOURCE_STAGES = {
    "acquire_cobblestone": ("stone", "cobblestone", "stone_sources", 8),
    "acquire_coal": ("coal_ore", "coal", "coal_sources", 10),
    "acquire_raw_iron": ("iron_ore", "raw_iron", "iron_sources", 3),
}
SP004_ORDERED_PROGRESS_STAGES = (
    "acquire_cobblestone",
    "acquire_coal",
    "acquire_raw_iron",
    "craft_furnace",
    "place_furnace",
    "smelt_iron",
    "craft_sticks",
    "craft_iron_pickaxe",
)
SP004_SCAN_RADIUS = 24
SP004_ROOT_GRAPH = [
    {
        "id": "acquire_cobblestone",
        "title": "Mine exactly eight stone blocks",
        "type": "gather",
        "priority": 1,
        "preconditions": {"inventory": {"stone_pickaxe": 1}},
        "success_criteria": {"flags": ["sp004_stone_acquired"]},
        "depends_on": [],
    },
    {
        "id": "acquire_coal",
        "title": "Mine exactly ten coal ore blocks",
        "type": "gather",
        "priority": 1,
        "preconditions": {"flags": ["sp004_stone_acquired"]},
        "success_criteria": {"flags": ["sp004_coal_acquired"]},
        "depends_on": ["acquire_cobblestone"],
    },
    {
        "id": "acquire_raw_iron",
        "title": "Mine exactly three iron ore blocks",
        "type": "gather",
        "priority": 1,
        "preconditions": {"flags": ["sp004_coal_acquired"]},
        "success_criteria": {"flags": ["sp004_raw_iron_acquired"]},
        "depends_on": ["acquire_coal"],
    },
    {
        "id": "observe_crafting_table",
        "title": "Find or make an interactive crafting table",
        "type": "verify",
        "priority": 1,
        "preconditions": {"flags": ["sp004_raw_iron_acquired"]},
        "success_criteria": {"nearby_block_present": "crafting_table"},
        "depends_on": ["acquire_raw_iron"],
    },
    {
        "id": "craft_furnace",
        "title": "Craft exactly one furnace",
        "type": "craft",
        "priority": 1,
        "preconditions": {
            "inventory": {"cobblestone": 8},
            "nearby_block_present": "crafting_table",
        },
        "success_criteria": {"flags": ["sp004_furnace_crafted"]},
        "depends_on": ["observe_crafting_table"],
    },
    {
        "id": "place_furnace",
        "title": "Place the furnace at the machine target",
        "type": "build",
        "priority": 1,
        "preconditions": {"inventory": {"furnace": 1}},
        "success_criteria": {"nearby_block_present": "furnace"},
        "depends_on": ["craft_furnace"],
    },
    {
        "id": "smelt_iron",
        "title": "Smelt exactly three raw iron with one coal",
        "type": "craft",
        "priority": 1,
        "preconditions": {
            "inventory": {"raw_iron": 3, "coal": 1},
            "nearby_block_present": "furnace",
        },
        "success_criteria": {"flags": ["sp004_iron_smelted"]},
        "depends_on": ["place_furnace"],
    },
    {
        "id": "craft_iron_pickaxe",
        "title": "Craft exactly one iron pickaxe",
        "type": "craft",
        "priority": 1,
        "preconditions": {
            "inventory": {"iron_ingot": 3, "stick": 2},
            "nearby_block_present": "crafting_table",
        },
        "success_criteria": {"inventory": {"iron_pickaxe": 1}},
        "depends_on": ["smelt_iron"],
    },
]
SP004_STAGE_INSTRUCTIONS = {
    "acquire_cobblestone": "If held_item is not stone_pickaxe, equip item=stone_pickaxe. Otherwise use only sp004_target: move to x/z if distance exceeds 4.5, else dig exact stone x/y/z.",
    "acquire_coal": "If held_item is not stone_pickaxe, equip item=stone_pickaxe. Otherwise use only sp004_target: move to x/z if distance exceeds 4.5, else dig exact coal_ore x/y/z.",
    "acquire_raw_iron": "If held_item is not stone_pickaxe, equip item=stone_pickaxe. Otherwise use only sp004_target: move to x/z if distance exceeds 4.5, else dig exact iron_ore x/y/z.",
    "locate_crafting_table": "Move only to the observed crafting-table target x/z.",
    "craft_crafting_table": "Craft exactly one crafting_table.",
    "place_crafting_table": "Place one crafting_table at target.reference_position x/y/z.",
    "craft_furnace": "Craft exactly one furnace.",
    "place_furnace": "Place one furnace at target.reference_position x/y/z.",
    "locate_furnace": "Move only to the observed furnace target x/z.",
    "smelt_iron": "Smelt item=iron_ingot input=raw_iron fuel=coal count=3 at the observed furnace.",
    "craft_sticks": "Craft exactly four sticks.",
    "craft_iron_pickaxe": "Craft exactly one iron_pickaxe.",
    "complete": "Return complete with no action.",
}


def empty_sp004_progress() -> dict:
    return {
        "stone_sources": [],
        "coal_sources": [],
        "iron_sources": [],
        "crafting_table_craft_count": 0,
        "crafting_table_place_count": 0,
        "furnace_craft_count": 0,
        "furnace_place_count": 0,
        "smelt_action_count": 0,
        "smelted_iron_ingot_count": 0,
        "smelted_raw_iron_count": 0,
        "smelting_fuel_consumed_count": 0,
        "stick_craft_count": 0,
        "iron_pickaxe_craft_count": 0,
        "stage_history": [],
    }


def progress_snapshot(progress: Any) -> dict:
    value = progress if isinstance(progress, dict) else {}
    snapshot = empty_sp004_progress()
    for key in ("stone_sources", "coal_sources", "iron_sources", "stage_history"):
        rows = value.get(key)
        snapshot[key] = copy.deepcopy(rows) if isinstance(rows, list) else []
    for key in set(snapshot) - {"stone_sources", "coal_sources", "iron_sources", "stage_history"}:
        snapshot[key] = _positive_int(value.get(key))
    return snapshot


def sp004_stage(observation: Any, progress: Any) -> str:
    obs = observation if isinstance(observation, dict) else {}
    state = progress_snapshot(progress)
    inventory = _inventory(obs)
    if (
        state["iron_pickaxe_craft_count"] == 1
        and _positive_int(inventory.get("iron_pickaxe")) >= 1
    ):
        return "complete"
    if len(state["stone_sources"]) < 8:
        return "acquire_cobblestone"
    if len(state["coal_sources"]) < 10:
        return "acquire_coal"
    if len(state["iron_sources"]) < 3:
        return "acquire_raw_iron"

    table = _nearest_block(obs, "crafting_table")
    if table is None:
        if _positive_int(inventory.get("crafting_table")) >= 1:
            return "place_crafting_table"
        if _positive_int(inventory.get("oak_planks")) >= 4:
            return "craft_crafting_table"
        return "locate_crafting_table"
    if _block_distance(table) > 4.5:
        return "locate_crafting_table"

    if state["furnace_craft_count"] == 0 and _positive_int(inventory.get("furnace")) == 0:
        return "craft_furnace"
    furnace = _nearest_block(obs, "furnace")
    if furnace is None:
        if _positive_int(inventory.get("furnace")) >= 1:
            return "place_furnace"
        return "craft_furnace"
    if _block_distance(furnace) > 4.5:
        return "locate_furnace"
    if (
        state["smelted_iron_ingot_count"] < 3
        or _positive_int(inventory.get("iron_ingot")) < 3
    ):
        return "smelt_iron"
    if _positive_int(inventory.get("stick")) < 2:
        return "craft_sticks"
    if _block_distance(table) > 4.5:
        return "locate_crafting_table"
    return "craft_iron_pickaxe"


def guard_sp004_action(action: Any, observation: Any, progress: Any) -> dict:
    obs = observation if isinstance(observation, dict) else {}
    state = progress_snapshot(progress)
    stage = sp004_stage(obs, state)
    issues: list[str] = []
    normalized = copy.deepcopy(action) if isinstance(action, dict) else {}
    if not isinstance(action, dict):
        issues.append("sp004_action_not_object")
        action = {}
    action_type = str(action.get("type") or "")
    params = action.get("parameters")
    if not isinstance(params, dict):
        issues.append("sp004_action_parameters_not_object")
        params = {}
    inventory = _inventory(obs)

    if stage in SP004_RESOURCE_STAGES:
        block_name, _drop_name, source_field, limit = SP004_RESOURCE_STAGES[stage]
        target = _resource_target(obs, block_name, state[source_field])
        if action_type == "equip":
            if params != {"item": "stone_pickaxe"}:
                issues.append(f"sp004_{stage}_exact_stone_pickaxe_equip_required")
            if _positive_int(inventory.get("stone_pickaxe")) != 1:
                issues.append(f"sp004_{stage}_stone_pickaxe_inventory_required")
            if _held_item(obs) == "stone_pickaxe":
                issues.append(f"sp004_{stage}_stone_pickaxe_already_held")
        elif target is None:
            issues.append(f"sp004_{stage}_machine_target_missing")
        elif action_type == "move_to":
            if _block_distance(target) <= 4.5:
                issues.append(f"sp004_{stage}_dig_required_within_reach")
            _check_horizontal_target(params, target, issues, f"sp004_{stage}")
        elif action_type == "dig":
            if _held_item(obs) != "stone_pickaxe":
                issues.append(f"sp004_{stage}_held_stone_pickaxe_required")
            if str(params.get("block") or "") != block_name:
                issues.append(f"sp004_{stage}_block_mismatch")
            _check_exact_target(params, target, issues, f"sp004_{stage}")
            if _block_distance(target) > 4.5:
                issues.append(f"sp004_{stage}_target_out_of_reach")
            source = _source_key(target)
            if source in set(state[source_field]):
                issues.append(f"sp004_{stage}_source_repeated")
            if len(state[source_field]) >= limit:
                issues.append(f"sp004_{stage}_source_limit_reached")
        else:
            issues.append(f"sp004_{stage}_requires_equip_move_or_dig")
    elif stage in {"locate_crafting_table", "locate_furnace"}:
        block_name = "crafting_table" if stage == "locate_crafting_table" else "furnace"
        target = _nearest_block(obs, block_name)
        if action_type != "move_to":
            issues.append(f"sp004_{stage}_requires_move_to")
        if target is None:
            issues.append(f"sp004_{stage}_observed_target_missing")
        else:
            _check_horizontal_target(params, target, issues, f"sp004_{stage}")
    elif stage == "craft_crafting_table":
        _check_craft(action_type, params, "crafting_table", 1, issues, stage)
        if _positive_int(inventory.get("oak_planks")) < 4:
            issues.append("sp004_crafting_table_materials_missing")
    elif stage == "place_crafting_table":
        _check_placement(action_type, params, obs, "crafting_table", issues, stage)
        if _positive_int(inventory.get("crafting_table")) != 1:
            issues.append("sp004_exact_crafting_table_item_required")
    elif stage == "craft_furnace":
        _check_craft(action_type, params, "furnace", 1, issues, stage)
        if _positive_int(inventory.get("cobblestone")) != 8:
            issues.append("sp004_exact_eight_cobblestone_required_for_furnace")
        if not _interactive_block(obs, "crafting_table"):
            issues.append("sp004_interactive_crafting_table_required_for_furnace")
        if state["furnace_craft_count"] != 0:
            issues.append("sp004_duplicate_furnace_craft_forbidden")
    elif stage == "place_furnace":
        _check_placement(action_type, params, obs, "furnace", issues, stage)
        if _positive_int(inventory.get("furnace")) != 1:
            issues.append("sp004_exact_furnace_item_required")
        if state["furnace_place_count"] != 0:
            issues.append("sp004_duplicate_furnace_placement_forbidden")
    elif stage == "smelt_iron":
        if action_type != "smelt":
            issues.append("sp004_smelt_iron_requires_smelt_action")
        expected = {
            "item": "iron_ingot",
            "input": "raw_iron",
            "fuel": "coal",
            "count": 3,
        }
        for key, value in expected.items():
            if params.get(key) != value:
                issues.append(f"sp004_smelt_iron_{key}_mismatch")
        furnace = _nearest_block(obs, "furnace")
        if furnace is None or _block_distance(furnace) > 4.5:
            issues.append("sp004_interactive_furnace_required")
        else:
            for axis in ("x", "y", "z"):
                if axis in params and not _same_number(
                    params.get(axis),
                    _position(furnace).get(axis),
                ):
                    issues.append(f"sp004_smelt_iron_furnace_{axis}_mismatch")
        if _positive_int(inventory.get("raw_iron")) != 3:
            issues.append("sp004_exact_three_raw_iron_required")
        if _positive_int(inventory.get("coal")) < 1:
            issues.append("sp004_coal_fuel_required")
        if state["smelt_action_count"] != 0:
            issues.append("sp004_duplicate_smelt_forbidden")
    elif stage == "craft_sticks":
        _check_craft(action_type, params, "stick", 4, issues, stage)
        if _positive_int(inventory.get("oak_planks")) < 2:
            issues.append("sp004_stick_materials_missing")
    elif stage == "craft_iron_pickaxe":
        _check_craft(action_type, params, "iron_pickaxe", 1, issues, stage)
        if _positive_int(inventory.get("iron_ingot")) != 3:
            issues.append("sp004_exact_three_iron_ingots_required")
        if _positive_int(inventory.get("stick")) < 2:
            issues.append("sp004_two_sticks_required")
        if not _interactive_block(obs, "crafting_table"):
            issues.append("sp004_interactive_crafting_table_required_for_iron_pickaxe")
        if state["iron_pickaxe_craft_count"] != 0:
            issues.append("sp004_duplicate_iron_pickaxe_craft_forbidden")
    elif stage == "complete":
        issues.append("sp004_terminal_action_forbidden")
    else:
        issues.append(f"sp004_unknown_stage:{stage}")

    return {
        "type": "iron_pickaxe_sp004_action_guard",
        "schema_version": 1,
        "policy_id": SP004_ACTION_GUARD_POLICY_ID,
        "passed": not issues,
        "stage": stage,
        "action": normalized,
        "progress": state,
        "issues": sorted(set(issues)),
        "fail_closed_before_action_execution": bool(issues),
    }


class IronPickaxeSP004Planner(Planner):
    """SP-004-only strict planner that leaves the shared Planner byte-stable."""

    def _system_prompt(self) -> str:
        return """You are the strict SP-004 Minecraft planner.
Return only one JSON object with schema_version=stone-pickaxe-plan-v1.
The required keys are plan_kind, goal, status, reasoning, subtasks, and actions.
Status planning requires exactly one action. Complete or blocked requires actions=[].
Allowed actions are equip, move_to, dig, craft, place, smelt, and wait.
Use only the supplied compact machine state and target. Never invent coordinates.
Craft parameters are item,count. Dig parameters are block,x,y,z.
Move parameters are x,z with optional y. Place parameters are item,x,y,z.
Smelt parameters are item,input,fuel,count with optional observed furnace x,y,z."""

    def _build_planning_prompt(
        self,
        goal: str,
        world_state: dict,
        memory_context: str,
    ) -> str:
        machine = self._compact_sp004_state(world_state)
        stage = str(machine.get("sp004_stage") or "unknown")
        instruction = SP004_STAGE_INSTRUCTIONS.get(
            stage,
            "Return blocked with no action because the stage is unknown.",
        )
        target_achieved = machine.get("inventory", {}).get("iron_pickaxe") == 1
        requires_target = stage in {
            "acquire_cobblestone",
            "acquire_coal",
            "acquire_raw_iron",
            "locate_crafting_table",
            "place_crafting_table",
            "place_furnace",
            "locate_furnace",
            "smelt_iron",
        }
        if target_achieved:
            gate = "Return status=complete, subtasks=[], actions=[]."
        elif requires_target and not machine.get("sp004_target"):
            gate = (
                "The required machine target is absent. Return status=blocked, "
                "subtasks=[], actions=[]. Never explore or invent coordinates."
            )
        elif self._expected_plan_kind == "root":
            gate = (
                "Return status=planning with exactly one action and copy the exact "
                f"root graph: {json.dumps(SP004_ROOT_GRAPH, sort_keys=True, separators=(',', ':'))}"
            )
        else:
            gate = (
                "Return status=planning with exactly one action and subtasks=[]. "
                "Do not repeat a completed mutation."
            )
        return f"""Exact goal: {goal}
Expected plan_kind: {self._expected_plan_kind}
Authoritative SP-004 machine state: {json.dumps(machine, sort_keys=True, separators=(',', ':'), default=str)}
Authoritative stage: {stage}
Required stage behavior: {instruction}
Gate: {gate}
Text predictions never advance machine state. Return compact contract-valid JSON only."""

    @staticmethod
    def _compact_sp004_state(world_state: Any) -> dict:
        state = world_state if isinstance(world_state, dict) else {}
        inventory = {
            str(item): min(_positive_int(count), 64)
            for item, count in _inventory(state).items()
            if _positive_int(count) > 0
        }
        progress = progress_snapshot(state.get("sp004_progress"))
        compact_progress = {
            "stone_source_removal_count": len(progress["stone_sources"]),
            "coal_source_removal_count": len(progress["coal_sources"]),
            "iron_source_removal_count": len(progress["iron_sources"]),
        }
        for field in (
            "crafting_table_craft_count",
            "crafting_table_place_count",
            "furnace_craft_count",
            "furnace_place_count",
            "smelt_action_count",
            "smelted_iron_ingot_count",
            "smelted_raw_iron_count",
            "smelting_fuel_consumed_count",
            "stick_craft_count",
            "iron_pickaxe_craft_count",
        ):
            compact_progress[field] = _positive_int(progress.get(field))
        target = state.get("sp004_target")
        target = target if isinstance(target, dict) else {}
        compact_target = {}
        for field in ("name", "item", "reference_block"):
            if target.get(field):
                compact_target[field] = str(target[field])[:64]
        for field in ("position", "reference_position"):
            position = _compact_finite_position(target.get(field))
            if position:
                compact_target[field] = position
        if _finite_number(target.get("distance")):
            compact_target["distance"] = round(float(target["distance"]), 3)
        blocks = []
        for block in _nearby_blocks(state):
            position = _compact_finite_position(_position(block))
            name = str(block.get("name") or "")[:64]
            if not name or not position:
                continue
            row = {"name": name, "position": position}
            if _finite_number(block.get("distance")):
                row["distance"] = round(float(block["distance"]), 3)
            blocks.append(row)
        priority = {"stone": 0, "coal_ore": 1, "iron_ore": 2, "crafting_table": 3, "furnace": 4}
        blocks.sort(
            key=lambda block: (
                priority.get(block["name"], 10),
                block.get("distance", math.inf),
                json.dumps(block["position"], sort_keys=True),
            )
        )
        return {
            "runtime_mode": "sp004",
            "sp004_stage": str(state.get("sp004_stage") or "")[:64],
            "sp004_progress": compact_progress,
            "sp004_target": compact_target,
            "inventory": inventory,
            "held_item": _held_item(state),
            "position": _compact_finite_position(state.get("position")),
            "nearby_blocks": blocks[:24],
        }

    @staticmethod
    def _validate_stone_pickaxe_plan_envelope(
        plan: dict,
        expected_goal: str,
        expected_kind: str,
        runtime_mode: str = "",
    ) -> dict:
        if str(runtime_mode or "") != "sp004":
            return Planner._validate_stone_pickaxe_plan_envelope(
                plan,
                expected_goal,
                expected_kind,
                runtime_mode,
            )
        value = plan if isinstance(plan, dict) else {}
        issues: list[str] = []
        allowed_keys = {
            "schema_version",
            "plan_kind",
            "goal",
            "status",
            "reasoning",
            "subtasks",
            "actions",
        }
        for field in sorted(set(value) - allowed_keys):
            issues.append(f"plan_field_unexpected:{field}")
        if value.get("schema_version") != "stone-pickaxe-plan-v1":
            issues.append("schema_version_invalid")
        if value.get("plan_kind") != expected_kind:
            issues.append("plan_kind_mismatch")
        if value.get("goal") != expected_goal:
            issues.append("goal_mismatch")
        status = str(value.get("status") or "")
        if status not in {"planning", "complete", "blocked"}:
            issues.append("status_invalid")
        reasoning = value.get("reasoning")
        if not isinstance(reasoning, str) or not reasoning.strip():
            issues.append("reasoning_missing")
        elif len(reasoning) > 320:
            issues.append("reasoning_too_long")
        subtasks = value.get("subtasks")
        if not isinstance(subtasks, list):
            issues.append("subtasks_not_array")
            subtasks = []
        if expected_kind == "root" and status == "planning":
            if subtasks != SP004_ROOT_GRAPH:
                issues.append("sp004_exact_root_graph_required")
        elif subtasks:
            issues.append("non_root_subtasks_forbidden")
        actions = value.get("actions")
        if not isinstance(actions, list):
            issues.append("actions_not_array")
            actions = []
        if status == "planning" and len(actions) != 1:
            issues.append("planning_action_count_must_equal_one")
        if status in {"complete", "blocked"} and actions:
            issues.append("terminal_actions_forbidden")
        if len(actions) == 1:
            IronPickaxeSP004Planner._validate_sp004_action(actions[0], issues)
        compact_chars = len(
            json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
        )
        if compact_chars > 8000:
            issues.append("plan_compact_size_exceeded")
        return {
            "type": "iron_pickaxe_sp004_plan_envelope_validation",
            "schema_version": 1,
            "passed": not issues,
            "expected_goal": expected_goal,
            "expected_kind": expected_kind,
            "status": status,
            "subtask_count": len(subtasks),
            "action_count": len(actions),
            "compact_plan_chars": compact_chars,
            "completion_requires_machine_verifier": True,
            "issues": sorted(set(issues)),
        }

    @staticmethod
    def _validate_sp004_action(action: Any, issues: list[str]) -> None:
        if not isinstance(action, dict):
            issues.append("action_not_object")
            return
        action_type = str(action.get("type") or "")
        params = action.get("parameters")
        if not isinstance(params, dict):
            issues.append("action_parameters_not_object")
            return
        allowed_by_type = {
            "equip": {"item"},
            "move_to": {"x", "y", "z"},
            "dig": {"block", "x", "y", "z"},
            "craft": {"item", "count"},
            "place": {"item", "x", "y", "z"},
            "smelt": {"item", "input", "fuel", "count", "x", "y", "z"},
            "wait": {"ms"},
        }
        allowed = allowed_by_type.get(action_type)
        if allowed is None:
            issues.append("action_type_forbidden")
            return
        for field in sorted(set(params) - allowed):
            issues.append(f"action_parameter_unexpected:{field}")
        coordinate_fields = {
            "move_to": ("x", "z"),
            "dig": ("x", "y", "z"),
            "place": ("x", "y", "z"),
        }.get(action_type, ())
        for field in coordinate_fields:
            if not _finite_number(params.get(field)):
                issues.append(f"action_parameter_{field}_invalid")
        if action_type == "move_to" and "y" in params and not _finite_number(params.get("y")):
            issues.append("action_parameter_y_invalid")
        if action_type == "dig" and not str(params.get("block") or ""):
            issues.append("dig_block_missing")
        if action_type == "equip" and not str(params.get("item") or ""):
            issues.append("equip_item_missing")
        if action_type in {"craft", "place"} and not str(params.get("item") or ""):
            issues.append(f"{action_type}_item_missing")
        if action_type == "craft":
            count = params.get("count", 1)
            if not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= 64:
                issues.append("craft_count_invalid")
        if action_type == "smelt":
            for field in ("item", "input", "fuel"):
                if not str(params.get(field) or ""):
                    issues.append(f"smelt_{field}_missing")
            count = params.get("count")
            if not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= 64:
                issues.append("smelt_count_invalid")
            for field in ("x", "y", "z"):
                if field in params and not _finite_number(params.get(field)):
                    issues.append(f"action_parameter_{field}_invalid")
        if action_type == "wait":
            wait_ms = params.get("ms")
            if not isinstance(wait_ms, int) or isinstance(wait_ms, bool) or not 1 <= wait_ms <= 2000:
                issues.append("wait_ms_invalid")


class SP004RuntimeSupervisor(RuntimeSupervisor):
    """Keep general safety checks while excluding unrelated shelter scheduling."""

    def evaluate_interrupt(self, observation: dict, goal: str = "", active_task=None):
        decision = super().evaluate_interrupt(observation, goal, active_task)
        if decision.reason in {"dusk_shelter_required", "night_shelter_required"}:
            return InterruptDecision(
                False,
                reason="sp004_shelter_interrupt_suppressed",
                evidence={
                    "policy_id": "sp004-peaceful-shelter-interrupt-isolation-v1",
                    "suppressed_reason": decision.reason,
                },
            )
        return decision


class IronPickaxeSP004RuntimeAgent(Agent):
    """Strict continuation agent for the stone-pickaxe-to-iron-pickaxe episode."""

    def __init__(self, config: Config):
        self.sp004_progress = empty_sp004_progress()
        super().__init__(config)
        self.runtime = SP004RuntimeSupervisor(config, self.explorer)
        if getattr(self, "_use_llm", False):
            self.planner = IronPickaxeSP004Planner(
                self.llm,
                self.task_system,
                protocol="stone-pickaxe-skill-fixed-v1",
            )
        self.skill_library.persist = False
        self.skill_learning_ledger = None

    def _observe(self) -> dict:
        observation = dict(super()._observe())
        try:
            scan = self.bot.get_nearby_blocks(radius=SP004_SCAN_RADIUS)
        except Exception:
            scan = []
        observation["nearby_blocks"] = _merge_scan_blocks(
            observation.get("nearby_blocks"),
            scan,
        )
        observation["held_item"] = _held_item(observation)
        observation["stone_pickaxe_runtime_mode"] = "sp004"
        observation["sp004_progress"] = progress_snapshot(self.sp004_progress)
        observation["sp004_stage"] = sp004_stage(observation, self.sp004_progress)
        observation["flags"] = sorted(
            set(str(flag) for flag in observation.get("flags", []) if str(flag))
            | set(_sp004_flags(observation, self.sp004_progress))
        )
        target = _sp004_target(observation, self.sp004_progress)
        if target:
            observation["sp004_target"] = target
        placement = _sp004_placement_target(observation, self.sp004_progress)
        if placement:
            observation["sp004_placement_target"] = placement
        return observation

    def _verify_action_for_execution(
        self,
        action: dict,
        observation: dict,
        goal: str,
        context: dict = None,
    ):
        guard = guard_sp004_action(action, observation, self.sp004_progress)
        self.session_logger.log(
            "iron_pickaxe_sp004_action_guard",
            {"goal": goal, "context": context or {}, **guard},
            level="INFO" if guard["passed"] else "ERROR",
        )
        if not guard["passed"]:
            verification = {
                "action_type": str(action.get("type") or "unknown"),
                "status": "reject",
                "score": 0.0,
                "reason": "; ".join(guard["issues"]),
                "policy_id": SP004_ACTION_GUARD_POLICY_ID,
                "guard": guard,
            }
            return verification, {
                "success": False,
                "error": f"SP-004 action guard rejected: {verification['reason']}",
                "action_type": verification["action_type"],
                "duration_ms": 0,
                "action_verification": verification,
                "verification_blocked": True,
            }
        return Agent._verify_action_for_execution(
            self,
            action,
            observation,
            goal,
            context,
        )

    def _apply_action_feedback(
        self,
        action: dict,
        result: dict,
        fallback_observation: dict,
        context: dict = None,
    ) -> dict:
        before = progress_snapshot(self.sp004_progress)
        self.sp004_progress = record_sp004_success(
            self.sp004_progress,
            action,
            result,
        )
        after = progress_snapshot(self.sp004_progress)
        if after != before:
            self.session_logger.log(
                "iron_pickaxe_sp004_progress",
                {
                    "schema_version": 1,
                    "policy_id": SP004_RUNTIME_POLICY_ID,
                    "goal": str((context or {}).get("goal") or ""),
                    "cycle": int((context or {}).get("cycle", 0) or 0),
                    "before": before,
                    "after": after,
                    "action": copy.deepcopy(action),
                    "result_proof": _bounded_result_proof(result),
                },
            )
        return super()._apply_action_feedback(
            action,
            result,
            fallback_observation,
            context,
        )

    def _goal_is_verified(
        self,
        goal: str,
        observation: dict,
        context: dict = None,
        recent_actions: list[dict] = None,
    ):
        inventory = _inventory(observation)
        state = progress_snapshot(self.sp004_progress)
        checks = {
            "stone_sources_exact": len(state["stone_sources"]) == 8,
            "coal_sources_exact": len(state["coal_sources"]) == 10,
            "iron_sources_exact": len(state["iron_sources"]) == 3,
            "furnace_crafted_exact": state["furnace_craft_count"] == 1,
            "furnace_placed_exact": state["furnace_place_count"] == 1,
            "smelt_action_exact": state["smelt_action_count"] == 1,
            "raw_iron_smelted_exact": state["smelted_raw_iron_count"] == 3,
            "iron_ingots_collected_exact": state["smelted_iron_ingot_count"] == 3,
            "coal_fuel_consumed_exact": state["smelting_fuel_consumed_count"] == 1,
            "iron_pickaxe_crafted_exact": state["iron_pickaxe_craft_count"] == 1,
            "terminal_iron_pickaxe": _positive_int(inventory.get("iron_pickaxe")) == 1,
            "terminal_stage_complete": sp004_stage(observation, state) == "complete",
        }
        achieved = all(checks.values())
        verification = GoalVerification(
            goal=goal,
            achieved=achieved,
            status="achieved" if achieved else "failed",
            confidence=1.0,
            evidence=(
                [
                    "SP-004 machine progress proves exact 8/10/3 resource removals",
                    "one zero-retry three-ingot smelt settled in inventory",
                    "terminal machine inventory contains exactly one iron_pickaxe",
                ]
                if achieved
                else []
            ),
            missing=sorted(name for name, passed in checks.items() if not passed),
            matched_rules=["iron_pickaxe:sp004_stone_to_iron_machine_terminal"],
            target_inventory={"iron_pickaxe": 1},
            critic={
                "policy_id": SP004_MACHINE_VERIFIER_ID,
                "checks": checks,
                "progress": state,
            },
        )
        self._log_goal_verification(
            verification,
            {**(context or {}), "accepted": achieved},
        )
        return achieved, verification


def build_sp004_runtime_config(*, base_config: Config) -> Config:
    return replace(
        base_config,
        llm=replace(
            base_config.llm,
            use_reasoning_json_fallback=True,
            use_forced_json_tool=True,
        ),
        skill_execution_mode="off",
        enable_skill_frontier_routing=False,
        enable_autocurriculum=False,
        enable_policy_skills=False,
        enable_memory_persistence=False,
        enable_planning_memory_context=False,
        enable_task_memory_context=False,
        enable_task_continuity_context=False,
        enable_task_readiness_context=False,
        enable_skill_memory_context=False,
        enable_curriculum_planner_context=False,
        enable_knowledge_correction_context=False,
        enable_task_precondition_context=False,
        enable_self_evolution_policy=False,
        enable_world_model_curriculum_feedback=False,
        planner_protocol="stone-pickaxe-skill-fixed-v1",
        require_llm_root_plan=True,
        max_action_timeout=120000,
    )


def record_sp004_success(progress: Any, action: Any, result: Any) -> dict:
    state = progress_snapshot(progress)
    if not isinstance(action, dict) or not isinstance(result, dict):
        return state
    if result.get("success") is not True:
        return state
    action_type = str(action.get("type") or "")
    params = action.get("parameters")
    params = params if isinstance(params, dict) else {}
    stage = str(result.get("sp004_stage") or "")
    if not stage:
        stage = _stage_for_action(action_type, params)

    if stage in SP004_RESOURCE_STAGES and action_type == "dig":
        block_name, drop_name, source_field, limit = SP004_RESOURCE_STAGES[stage]
        delta = result.get("pickup_inventory_delta")
        delta = delta if isinstance(delta, dict) else result.get("inventory_delta")
        delta = delta if isinstance(delta, dict) else {}
        source = _source_key(params)
        if (
            str(params.get("block") or "") == block_name
            and result.get("block_removed") is True
            and result.get("pickup_observed") is True
            and _positive_int(delta.get(drop_name)) >= 1
            and source
            and source not in state[source_field]
            and len(state[source_field]) < limit
        ):
            state[source_field].append(source)
            state["stage_history"].append(stage)
    elif action_type == "craft":
        item = str(params.get("item") or "")
        delta = result.get("inventory_delta")
        delta = delta if isinstance(delta, dict) else {}
        if item == "crafting_table" and _positive_int(delta.get(item)) >= 1:
            state["crafting_table_craft_count"] += 1
            state["stage_history"].append("craft_crafting_table")
        elif item == "furnace" and _positive_int(delta.get(item)) >= 1:
            state["furnace_craft_count"] += 1
            state["stage_history"].append("craft_furnace")
        elif item == "stick" and _positive_int(delta.get(item)) >= 4:
            state["stick_craft_count"] += 1
            state["stage_history"].append("craft_sticks")
        elif item == "iron_pickaxe" and _positive_int(delta.get(item)) >= 1:
            state["iron_pickaxe_craft_count"] += 1
            state["stage_history"].append("craft_iron_pickaxe")
    elif action_type == "place":
        item = str(params.get("item") or "")
        placed = (
            result.get("block_placed") is True
            or str(result.get("placed_block") or "") == item
        )
        if placed and item == "crafting_table":
            state["crafting_table_place_count"] += 1
            state["stage_history"].append("place_crafting_table")
        elif placed and item == "furnace":
            state["furnace_place_count"] += 1
            state["stage_history"].append("place_furnace")
    elif action_type == "smelt":
        if (
            result.get("output_settled") is True
            and _positive_int(result.get("output_inventory_increase")) == 3
            and _positive_int(result.get("input_inventory_decrease")) == 3
            and _positive_int(result.get("fuel_inventory_decrease")) == 1
            and _positive_int(result.get("smelt_attempts")) == 1
            and _positive_int(result.get("smelt_retry_count")) == 0
        ):
            state["smelt_action_count"] += 1
            state["smelted_iron_ingot_count"] += 3
            state["smelted_raw_iron_count"] += 3
            state["smelting_fuel_consumed_count"] += 1
            state["stage_history"].append("smelt_iron")
    return state


def verify_sp004_runtime_episode(episode: Any) -> dict:
    value = episode if isinstance(episode, dict) else {}
    initial = value.get("initial_observation")
    initial = initial if isinstance(initial, dict) else {}
    terminal = value.get("terminal_observation")
    terminal = terminal if isinstance(terminal, dict) else {}
    observations = value.get("observations")
    observations = observations if isinstance(observations, list) else []
    actions = value.get("actions")
    actions = actions if isinstance(actions, list) else []
    supplied_state = progress_snapshot(value.get("progress"))
    initial_inventory = _inventory(initial)
    terminal_inventory = _inventory(terminal)
    action_rows = [row for row in actions if isinstance(row, dict)]
    action_types = [
        str((row.get("action") or {}).get("type") or "")
        for row in action_rows
        if isinstance(row.get("action"), dict)
    ]
    action_results = [
        row.get("result") for row in action_rows if isinstance(row.get("result"), dict)
    ]
    state = empty_sp004_progress()
    for row in action_rows:
        state = record_sp004_success(state, row.get("action"), row.get("result"))
    dig_blocks = [
        str(((row.get("action") or {}).get("parameters") or {}).get("block") or "")
        for row in action_rows
        if str((row.get("action") or {}).get("type") or "") == "dig"
    ]
    table_observed = any(
        _nearest_block(obs, "crafting_table") is not None
        for obs in [initial, *observations, terminal]
        if isinstance(obs, dict)
    )
    furnace_observed = any(
        _nearest_block(obs, "furnace") is not None
        for obs in [initial, *observations, terminal]
        if isinstance(obs, dict)
    )
    history = list(state["stage_history"])
    initial_sticks = _positive_int(initial_inventory.get("stick"))
    required_history = list(SP004_ORDERED_PROGRESS_STAGES)
    if initial_sticks >= 2:
        required_history.remove("craft_sticks")
    criteria = {
        "initial_stone_pickaxe_present": _positive_int(initial_inventory.get("stone_pickaxe")) == 1,
        "initial_iron_pickaxe_absent": _positive_int(initial_inventory.get("iron_pickaxe")) == 0,
        "initial_mined_and_smelted_resources_absent": all(
            _positive_int(initial_inventory.get(item)) == 0
            for item in ("cobblestone", "coal", "raw_iron", "iron_ingot", "furnace")
        ),
        "exact_eight_distinct_stone_sources": len(state["stone_sources"]) == 8
        and len(set(state["stone_sources"])) == 8,
        "exact_ten_distinct_coal_sources": len(state["coal_sources"]) == 10
        and len(set(state["coal_sources"])) == 10,
        "exact_three_distinct_iron_sources": len(state["iron_sources"]) == 3
        and len(set(state["iron_sources"])) == 3,
        "only_required_ore_digs": Counter(dig_blocks)
        == Counter({"stone": 8, "coal_ore": 10, "iron_ore": 3}),
        "crafting_table_found_or_made": table_observed
        or state["crafting_table_craft_count"] == 1,
        "furnace_crafted_once": state["furnace_craft_count"] == 1,
        "furnace_placed_once": state["furnace_place_count"] == 1,
        "furnace_machine_observed": furnace_observed,
        "one_zero_retry_smelt": state["smelt_action_count"] == 1
        and action_types.count("smelt") == 1,
        "exact_three_raw_iron_smelted": state["smelted_raw_iron_count"] == 3,
        "exact_three_iron_ingots_collected": state["smelted_iron_ingot_count"] == 3,
        "exact_one_coal_fuel_consumed": state["smelting_fuel_consumed_count"] == 1,
        "sticks_available_for_pickaxe": (
            initial_sticks >= 2 and state["stick_craft_count"] == 0
        )
        or (initial_sticks < 2 and state["stick_craft_count"] == 1),
        "iron_pickaxe_crafted_once": state["iron_pickaxe_craft_count"] == 1,
        "terminal_iron_pickaxe_present": _positive_int(terminal_inventory.get("iron_pickaxe")) == 1,
        "no_failed_actions": len(action_results) == len(action_rows)
        and all(result.get("success") is True for result in action_results),
        "ordered_progression": _ordered_subsequence(history, tuple(required_history)),
        "progress_matches_action_evidence": supplied_state == state,
        "terminal_stage_complete": sp004_stage(terminal, state) == "complete",
    }
    issues = sorted(name for name, passed in criteria.items() if not passed)
    return {
        "type": "iron_pickaxe_sp004_machine_verification",
        "schema_version": 1,
        "verifier_id": SP004_MACHINE_VERIFIER_ID,
        "runtime_policy_id": SP004_RUNTIME_POLICY_ID,
        "passed": not issues,
        "criteria": criteria,
        "criteria_issues": issues,
        "metrics": {
            "action_count": len(action_rows),
            "stone_source_removal_count": len(state["stone_sources"]),
            "coal_source_removal_count": len(state["coal_sources"]),
            "iron_source_removal_count": len(state["iron_sources"]),
            "smelt_action_count": state["smelt_action_count"],
            "iron_pickaxe_craft_count": state["iron_pickaxe_craft_count"],
        },
        "progress": state,
        "terminal_inventory": terminal_inventory,
        "counts_toward_sp004_lifecycle": not issues,
        "counts_toward_capability": False,
        "counts_toward_m4": False,
    }


def _stage_for_action(action_type: str, params: dict) -> str:
    if action_type == "dig":
        block = str(params.get("block") or "")
        return {
            "stone": "acquire_cobblestone",
            "coal_ore": "acquire_coal",
            "iron_ore": "acquire_raw_iron",
        }.get(block, "")
    if action_type == "smelt":
        return "smelt_iron"
    return ""


def _inventory(observation: dict) -> dict:
    inventory = observation.get("inventory")
    return inventory if isinstance(inventory, dict) else {}


def _held_item(observation: dict) -> str:
    direct = observation.get("held_item")
    if isinstance(direct, str):
        return direct
    if isinstance(direct, dict):
        return str(direct.get("name") or "")
    equipment = observation.get("equipment")
    if isinstance(equipment, list) and equipment:
        main_hand = equipment[0]
        if isinstance(main_hand, dict):
            return str(main_hand.get("name") or "")
        if isinstance(main_hand, str):
            return main_hand
    return ""


def _merge_scan_blocks(*collections: Any) -> list[dict]:
    merged: list[dict] = []
    seen: set[str] = set()
    for collection in collections:
        if not isinstance(collection, list):
            continue
        for block in collection:
            if not isinstance(block, dict):
                continue
            key = f"{str(block.get('name') or '')}:{_source_key(block)}"
            if not key.strip(":") or key in seen:
                continue
            seen.add(key)
            merged.append(copy.deepcopy(block))
    priority = {
        "stone": 0,
        "coal_ore": 1,
        "iron_ore": 2,
        "crafting_table": 3,
        "furnace": 4,
    }
    return sorted(
        merged,
        key=lambda block: (
            priority.get(str(block.get("name") or ""), 10),
            _block_distance(block),
            _source_key(block),
        ),
    )[:80]


def _sp004_flags(observation: dict, progress: Any) -> list[str]:
    state = progress_snapshot(progress)
    flags = []
    if len(state["stone_sources"]) == 8:
        flags.append("sp004_stone_acquired")
    if len(state["coal_sources"]) == 10:
        flags.append("sp004_coal_acquired")
    if len(state["iron_sources"]) == 3:
        flags.append("sp004_raw_iron_acquired")
    if _nearest_block(observation, "crafting_table") is not None:
        flags.append("sp004_crafting_table_observed")
    if state["furnace_craft_count"] == 1:
        flags.append("sp004_furnace_crafted")
    if _nearest_block(observation, "furnace") is not None:
        flags.append("sp004_furnace_observed")
    if state["smelted_iron_ingot_count"] == 3:
        flags.append("sp004_iron_smelted")
    if _positive_int(_inventory(observation).get("iron_pickaxe")) == 1:
        flags.append("sp004_iron_pickaxe_crafted")
    return flags


def _sp004_target(observation: dict, progress: Any) -> dict:
    state = progress_snapshot(progress)
    stage = sp004_stage(observation, state)
    if stage in SP004_RESOURCE_STAGES:
        block_name, _drop, source_field, _limit = SP004_RESOURCE_STAGES[stage]
        target = _resource_target(observation, block_name, state[source_field])
        return copy.deepcopy(target) if target else {}
    if stage == "locate_crafting_table":
        target = _nearest_block(observation, "crafting_table")
        return copy.deepcopy(target) if target else {}
    if stage == "locate_furnace":
        target = _nearest_block(observation, "furnace")
        return copy.deepcopy(target) if target else {}
    placement = _sp004_placement_target(observation, state)
    if placement:
        return copy.deepcopy(placement)
    if stage == "smelt_iron":
        target = _nearest_block(observation, "furnace")
        return copy.deepcopy(target) if target else {}
    return {}


def _sp004_placement_target(observation: dict, progress: Any) -> dict:
    stage = sp004_stage(observation, progress)
    item = {
        "place_crafting_table": "crafting_table",
        "place_furnace": "furnace",
    }.get(stage)
    if not item:
        return {}
    reference = _open_place_reference(observation)
    if not reference:
        return {}
    return {
        "item": item,
        "reference_position": reference,
        "reference_block": "machine_observed_solid",
    }


def _open_place_reference(observation: dict) -> dict:
    occupied = {
        _source_key(block)
        for block in _nearby_blocks(observation)
        if _source_key(block)
    }
    player = _position(observation)
    candidates = []
    for block in _nearby_blocks(observation):
        if str(block.get("name") or "") in {"crafting_table", "furnace"}:
            continue
        position = _position(block)
        source = _source_key(block)
        if not source or _block_distance(block) > 4.5:
            continue
        above = {
            "x": position.get("x"),
            "y": float(position.get("y")) + 1 if isinstance(position.get("y"), (int, float)) else None,
            "z": position.get("z"),
        }
        above_key = _source_key(above)
        if not above_key or above_key in occupied:
            continue
        if all(isinstance(player.get(axis), (int, float)) for axis in ("x", "y", "z")):
            if (
                math.floor(float(player["x"])) == math.floor(float(above["x"]))
                and math.floor(float(player["z"])) == math.floor(float(above["z"]))
                and math.floor(float(player["y"])) in {
                    math.floor(float(above["y"])),
                    math.floor(float(above["y"])) - 1,
                }
            ):
                continue
        candidates.append(block)
    if not candidates:
        return {}
    return copy.deepcopy(_position(min(candidates, key=lambda block: (_block_distance(block), _source_key(block)))))


def _bounded_result_proof(result: Any) -> dict:
    value = result if isinstance(result, dict) else {}
    fields = (
        "success",
        "block_removed",
        "pickup_observed",
        "pickup_inventory_delta",
        "inventory_delta",
        "block_placed",
        "placed_block",
        "output_settled",
        "output_inventory_increase",
        "input_inventory_decrease",
        "fuel_inventory_decrease",
        "smelt_attempts",
        "smelt_retry_count",
        "error",
    )
    return {field: copy.deepcopy(value[field]) for field in fields if field in value}


def _nearby_blocks(observation: dict) -> list[dict]:
    blocks = observation.get("nearby_blocks")
    return [item for item in blocks if isinstance(item, dict)] if isinstance(blocks, list) else []


def _nearest_block(observation: dict, name: str) -> dict | None:
    matches = [block for block in _nearby_blocks(observation) if block.get("name") == name]
    if not matches:
        return None
    return min(matches, key=lambda block: (_block_distance(block), _source_key(block)))


def _resource_target(observation: dict, name: str, used_sources: list[str]) -> dict | None:
    used = set(str(item) for item in used_sources)
    candidates = [
        block
        for block in _nearby_blocks(observation)
        if block.get("name") == name and _source_key(block) not in used
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda block: (_block_distance(block), _source_key(block)))


def _interactive_block(observation: dict, name: str) -> bool:
    block = _nearest_block(observation, name)
    return block is not None and _block_distance(block) <= 4.5


def _position(value: dict) -> dict:
    position = value.get("position")
    if isinstance(position, dict):
        return position
    return value


def _source_key(value: dict) -> str:
    position = _position(value)
    coordinates = []
    for axis in ("x", "y", "z"):
        number = position.get(axis)
        if not isinstance(number, (int, float)) or isinstance(number, bool):
            return ""
        if not math.isfinite(float(number)):
            return ""
        coordinates.append(str(int(number)) if float(number).is_integer() else str(float(number)))
    return ",".join(coordinates)


def _block_distance(block: dict) -> float:
    value = block.get("distance")
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
        return float(value)
    return math.inf


def _placement_target(observation: dict, item: str) -> dict | None:
    target = observation.get("sp004_placement_target")
    if not isinstance(target, dict) or target.get("item") != item:
        return None
    reference = target.get("reference_position")
    return reference if isinstance(reference, dict) else None


def _check_craft(
    action_type: str,
    params: dict,
    item: str,
    count: int,
    issues: list[str],
    stage: str,
) -> None:
    if action_type != "craft":
        issues.append(f"sp004_{stage}_requires_craft")
    if params.get("item") != item:
        issues.append(f"sp004_{stage}_item_mismatch")
    if params.get("count", 1) != count:
        issues.append(f"sp004_{stage}_count_mismatch")


def _check_placement(
    action_type: str,
    params: dict,
    observation: dict,
    item: str,
    issues: list[str],
    stage: str,
) -> None:
    if action_type != "place":
        issues.append(f"sp004_{stage}_requires_place")
    if params.get("item") != item:
        issues.append(f"sp004_{stage}_item_mismatch")
    target = _placement_target(observation, item)
    if target is None:
        issues.append(f"sp004_{stage}_machine_target_missing")
        return
    _check_exact_target(params, {"position": target}, issues, f"sp004_{stage}")


def _check_exact_target(
    params: dict,
    target: dict,
    issues: list[str],
    prefix: str,
) -> None:
    position = _position(target)
    for axis in ("x", "y", "z"):
        if not _same_number(params.get(axis), position.get(axis)):
            issues.append(f"{prefix}_{axis}_mismatch")


def _check_horizontal_target(
    params: dict,
    target: dict,
    issues: list[str],
    prefix: str,
) -> None:
    position = _position(target)
    for axis in ("x", "z"):
        if not _same_number(params.get(axis), position.get(axis)):
            issues.append(f"{prefix}_{axis}_mismatch")


def _same_number(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return False
    try:
        left_number = float(left)
        right_number = float(right)
    except (TypeError, ValueError):
        return False
    return (
        math.isfinite(left_number)
        and math.isfinite(right_number)
        and abs(left_number - right_number) <= 1e-6
    )


def _finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _compact_finite_position(value: Any) -> dict:
    if not isinstance(value, dict):
        return {}
    if not all(_finite_number(value.get(axis)) for axis in ("x", "y", "z")):
        return {}
    return {axis: value[axis] for axis in ("x", "y", "z")}


def _positive_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _ordered_subsequence(history: list[str], required: tuple[str, ...]) -> bool:
    index = 0
    for stage in history:
        if index < len(required) and stage == required[index]:
            index += 1
    return index == len(required)
