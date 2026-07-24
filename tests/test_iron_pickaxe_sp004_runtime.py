from __future__ import annotations

import copy

import pytest

from singularity.core.config import Config
from singularity.evaluation.iron_pickaxe_sp004_runtime import (
    SP004_GOAL,
    SP004_ROOT_GRAPH,
    IronPickaxeSP004Planner,
    SP004RuntimeSupervisor,
    build_sp004_runtime_config,
    empty_sp004_progress,
    guard_sp004_action,
    record_sp004_success,
    sp004_stage,
    verify_sp004_runtime_episode,
)


TABLE = {"name": "crafting_table", "position": {"x": 1, "y": 64, "z": 1}, "distance": 2.0}
FURNACE = {"name": "furnace", "position": {"x": 2, "y": 64, "z": 1}, "distance": 2.0}


def observation(inventory=None, blocks=None, held_item="stone_pickaxe", placement=None):
    value = {
        "inventory": dict(inventory or {}),
        "nearby_blocks": copy.deepcopy(blocks or []),
        "held_item": held_item,
    }
    if placement is not None:
        value["sp004_placement_target"] = copy.deepcopy(placement)
    return value


def resource(block, index, distance=2.0):
    return {
        "name": block,
        "position": {"x": index, "y": 60, "z": index + 20},
        "distance": distance,
    }


def action(action_type, **parameters):
    return {"type": action_type, "parameters": parameters}


def successful_dig(block, drop, index, stage):
    return {
        "action": action("dig", block=block, x=index, y=60, z=index + 20),
        "result": {
            "success": True,
            "sp004_stage": stage,
            "block_removed": True,
            "pickup_observed": True,
            "pickup_inventory_delta": {drop: 1},
        },
    }


def test_sp004_suppresses_only_unrelated_shelter_interrupts() -> None:
    supervisor = SP004RuntimeSupervisor(Config())
    decision = supervisor.evaluate_interrupt(
        {
            "time_of_day": 14000,
            "health": 20,
            "hunger": 20,
            "inventory": {},
            "nearby_entities": [],
        },
        SP004_GOAL,
    )

    assert decision.should_interrupt is False
    assert decision.reason == "sp004_shelter_interrupt_suppressed"
    assert decision.evidence["suppressed_reason"] == "night_shelter_required"

    health_decision = supervisor.evaluate_interrupt(
        {
            "time_of_day": 1000,
            "health": 1,
            "hunger": 20,
            "inventory": {},
            "nearby_entities": [],
        },
        SP004_GOAL,
    )
    assert health_decision.should_interrupt is True
    assert health_decision.reason == "health_critical"


def successful_craft(item, delta, count=1):
    return {
        "action": action("craft", item=item, count=count),
        "result": {"success": True, "inventory_delta": {item: delta}},
    }


def complete_episode(*, initial_sticks=0):
    rows = []
    for index in range(8):
        rows.append(successful_dig("stone", "cobblestone", index, "acquire_cobblestone"))
    for index in range(10):
        rows.append(successful_dig("coal_ore", "coal", index + 100, "acquire_coal"))
    for index in range(3):
        rows.append(successful_dig("iron_ore", "raw_iron", index + 200, "acquire_raw_iron"))
    rows.extend(
        [
            successful_craft("furnace", 1),
            {
                "action": action("place", item="furnace", x=2, y=64, z=1),
                "result": {"success": True, "block_placed": True, "placed_block": "furnace"},
            },
            {
                "action": action(
                    "smelt",
                    item="iron_ingot",
                    input="raw_iron",
                    fuel="coal",
                    count=3,
                    x=2,
                    y=64,
                    z=1,
                ),
                "result": {
                    "success": True,
                    "output_settled": True,
                    "output_inventory_increase": 3,
                    "input_inventory_decrease": 3,
                    "fuel_inventory_decrease": 1,
                    "smelt_attempts": 1,
                    "smelt_retry_count": 0,
                },
            },
        ]
    )
    if initial_sticks < 2:
        rows.append(successful_craft("stick", 4, count=4))
    rows.append(successful_craft("iron_pickaxe", 1))

    progress = empty_sp004_progress()
    for row in rows:
        progress = record_sp004_success(progress, row["action"], row["result"])

    initial_inventory = {"stone_pickaxe": 1, "oak_planks": 3}
    if initial_sticks:
        initial_inventory["stick"] = initial_sticks
    return {
        "initial_observation": observation(initial_inventory, [TABLE]),
        "observations": [
            observation(
                {
                    "stone_pickaxe": 1,
                    "oak_planks": 1 if initial_sticks < 2 else 3,
                    "coal": 9,
                    "stick": 4 if initial_sticks < 2 else initial_sticks,
                },
                [TABLE, FURNACE],
            )
        ],
        "actions": rows,
        "progress": progress,
        "terminal_observation": observation(
            {
                "stone_pickaxe": 1,
                "oak_planks": 1 if initial_sticks < 2 else 3,
                "coal": 9,
                "stick": 2 if initial_sticks < 2 else initial_sticks - 2,
                "iron_pickaxe": 1,
            },
            [TABLE, FURNACE],
            held_item="iron_pickaxe",
        ),
    }


def test_full_exact_found_table_path_passes_machine_verifier():
    report = verify_sp004_runtime_episode(complete_episode())

    assert report["passed"] is True
    assert report["criteria_issues"] == []
    assert report["metrics"] == {
        "action_count": 26,
        "stone_source_removal_count": 8,
        "coal_source_removal_count": 10,
        "iron_source_removal_count": 3,
        "smelt_action_count": 1,
        "iron_pickaxe_craft_count": 1,
    }
    assert report["counts_toward_capability"] is False
    assert report["counts_toward_m4"] is False


def test_existing_sticks_skip_stick_craft_without_weakening_order():
    episode = complete_episode(initial_sticks=2)

    report = verify_sp004_runtime_episode(episode)

    assert report["passed"] is True
    assert report["metrics"]["action_count"] == 25
    assert report["progress"]["stick_craft_count"] == 0


@pytest.mark.parametrize(
    ("mutation", "criterion"),
    [
        (lambda episode: episode["progress"]["stone_sources"].pop(), "progress_matches_action_evidence"),
        (
            lambda episode: episode["actions"].append(
                successful_dig("stone", "cobblestone", 999, "acquire_cobblestone")
            ),
            "only_required_ore_digs",
        ),
        (
            lambda episode: episode["actions"][0]["result"].update(success=False),
            "exact_eight_distinct_stone_sources",
        ),
        (
            lambda episode: episode["terminal_observation"]["inventory"].pop("iron_pickaxe"),
            "terminal_iron_pickaxe_present",
        ),
    ],
)
def test_verifier_fails_closed_on_incomplete_or_fabricated_evidence(mutation, criterion):
    episode = complete_episode()
    mutation(episode)

    report = verify_sp004_runtime_episode(episode)

    assert report["passed"] is False
    assert criterion in report["criteria_issues"]


def test_resource_guard_requires_exact_nearest_unique_target_and_stone_pickaxe():
    progress = empty_sp004_progress()
    near = resource("stone", 1)
    far = resource("stone", 2, distance=3.0)
    obs = observation({}, [far, near])
    exact = action("dig", block="stone", x=1, y=60, z=21)

    assert guard_sp004_action(exact, obs, progress)["passed"] is True
    assert guard_sp004_action(
        action("dig", block="coal_ore", x=1, y=60, z=21),
        obs,
        progress,
    )["passed"] is False
    assert guard_sp004_action(
        exact,
        observation({}, [near, far], held_item="wooden_pickaxe"),
        progress,
    )["passed"] is False


def test_resource_guard_requires_move_before_out_of_reach_dig():
    target = resource("stone", 5, distance=8.0)
    obs = observation({}, [target])
    progress = empty_sp004_progress()

    rejected = guard_sp004_action(
        action("dig", block="stone", x=5, y=60, z=25),
        obs,
        progress,
    )
    accepted = guard_sp004_action(action("move_to", x=5, z=25), obs, progress)

    assert rejected["passed"] is False
    assert "sp004_acquire_cobblestone_target_out_of_reach" in rejected["issues"]
    assert accepted["passed"] is True


def test_table_found_and_table_make_branches_are_bounded():
    progress = empty_sp004_progress()
    progress["stone_sources"] = [f"s{i}" for i in range(8)]
    progress["coal_sources"] = [f"c{i}" for i in range(10)]
    progress["iron_sources"] = [f"i{i}" for i in range(3)]

    assert sp004_stage(observation({"cobblestone": 8}, [TABLE]), progress) == "craft_furnace"
    assert sp004_stage(observation({"cobblestone": 8, "oak_planks": 4}), progress) == "craft_crafting_table"
    assert guard_sp004_action(
        action("craft", item="crafting_table", count=1),
        observation({"cobblestone": 8, "oak_planks": 4}),
        progress,
    )["passed"] is True

    made = record_sp004_success(
        progress,
        action("craft", item="crafting_table", count=1),
        {"success": True, "inventory_delta": {"crafting_table": 1}},
    )
    place_target = {
        "item": "crafting_table",
        "reference_position": {"x": 4, "y": 63, "z": 4},
    }
    assert sp004_stage(observation({"crafting_table": 1}, placement=place_target), made) == "place_crafting_table"
    assert guard_sp004_action(
        action("place", item="crafting_table", x=4, y=63, z=4),
        observation({"crafting_table": 1}, placement=place_target),
        made,
    )["passed"] is True


@pytest.mark.parametrize(
    "parameters",
    [
        {"item": "iron_ingot", "input": "raw_iron", "fuel": "coal", "count": 2},
        {"item": "iron_ingot", "input": "iron_ore", "fuel": "coal", "count": 3},
        {"item": "iron_ingot", "input": "raw_iron", "fuel": "charcoal", "count": 3},
    ],
)
def test_smelt_guard_rejects_wrong_exact_contract(parameters):
    progress = empty_sp004_progress()
    progress["stone_sources"] = [f"s{i}" for i in range(8)]
    progress["coal_sources"] = [f"c{i}" for i in range(10)]
    progress["iron_sources"] = [f"i{i}" for i in range(3)]
    progress["furnace_craft_count"] = 1
    progress["furnace_place_count"] = 1
    obs = observation(
        {"raw_iron": 3, "coal": 10},
        [TABLE, FURNACE],
    )

    report = guard_sp004_action(action("smelt", **parameters), obs, progress)

    assert report["passed"] is False
    assert report["fail_closed_before_action_execution"] is True


def test_failed_or_retried_smelt_does_not_advance_progress():
    progress = empty_sp004_progress()
    smelt = action(
        "smelt",
        item="iron_ingot",
        input="raw_iron",
        fuel="coal",
        count=3,
    )

    failed = record_sp004_success(progress, smelt, {"success": False, "error": "timeout"})
    retried = record_sp004_success(
        progress,
        smelt,
        {
            "success": True,
            "output_settled": True,
            "output_inventory_increase": 3,
            "input_inventory_decrease": 3,
            "fuel_inventory_decrease": 1,
            "smelt_attempts": 2,
            "smelt_retry_count": 1,
        },
    )

    assert failed == progress
    assert retried == progress


def test_terminal_stage_requires_machine_inventory_iron_pickaxe():
    episode = complete_episode()
    progress = episode["progress"]
    terminal = episode["terminal_observation"]

    assert sp004_stage(terminal, progress) == "complete"
    without_pickaxe = copy.deepcopy(terminal)
    without_pickaxe["inventory"].pop("iron_pickaxe")
    assert sp004_stage(without_pickaxe, progress) != "complete"


def test_runtime_config_uses_strict_real_llm_root_planner_without_skill_routes():
    config = build_sp004_runtime_config(base_config=Config())

    assert config.planner_protocol == "stone-pickaxe-skill-fixed-v1"
    assert config.require_llm_root_plan is True
    assert config.skill_execution_mode == "off"
    assert config.enable_skill_frontier_routing is False
    assert config.enable_memory_persistence is False
    assert config.max_action_timeout == 120000


def test_strict_planner_compacts_sp004_machine_state_and_target():
    state = {
        "stone_pickaxe_runtime_mode": "sp004",
        "sp004_stage": "acquire_coal",
        "sp004_progress": {
            "stone_sources": [f"s{i}" for i in range(8)],
            "coal_sources": ["c0"],
            "iron_sources": [],
        },
        "sp004_target": {
            "name": "coal_ore",
            "position": {"x": 10, "y": 61, "z": 12},
            "distance": 3.25,
        },
        "inventory": {"stone_pickaxe": 1, "cobblestone": 8, "coal": 1},
        "equipment": [{"name": "stone_pickaxe"}],
        "nearby_blocks": [
            {
                "name": "coal_ore",
                "position": {"x": 10, "y": 61, "z": 12},
                "distance": 3.25,
            }
        ],
    }

    compact = IronPickaxeSP004Planner._compact_sp004_state(state)

    assert compact["runtime_mode"] == "sp004"
    assert compact["sp004_stage"] == "acquire_coal"
    assert compact["sp004_progress"]["stone_source_removal_count"] == 8
    assert compact["sp004_progress"]["coal_source_removal_count"] == 1
    assert compact["sp004_target"] == {
        "name": "coal_ore",
        "position": {"x": 10, "y": 61, "z": 12},
        "distance": 3.25,
    }
    assert compact["held_item"] == "stone_pickaxe"


def test_strict_planner_requires_exact_sp004_root_graph():
    plan = {
        "schema_version": "stone-pickaxe-plan-v1",
        "plan_kind": "root",
        "goal": SP004_GOAL,
        "status": "planning",
        "reasoning": "Mine the first observed stone source.",
        "subtasks": copy.deepcopy(SP004_ROOT_GRAPH),
        "actions": [
            {
                "type": "dig",
                "parameters": {"block": "stone", "x": 1, "y": 60, "z": 21},
            }
        ],
    }

    accepted = IronPickaxeSP004Planner._validate_stone_pickaxe_plan_envelope(
        plan,
        expected_goal=SP004_GOAL,
        expected_kind="root",
        runtime_mode="sp004",
    )
    malformed = copy.deepcopy(plan)
    malformed["subtasks"].pop()
    rejected = IronPickaxeSP004Planner._validate_stone_pickaxe_plan_envelope(
        malformed,
        expected_goal=SP004_GOAL,
        expected_kind="root",
        runtime_mode="sp004",
    )

    assert accepted["passed"] is True
    assert rejected["passed"] is False
    assert "sp004_exact_root_graph_required" in rejected["issues"]


def test_strict_planner_accepts_exact_smelt_continuation_action():
    plan = {
        "schema_version": "stone-pickaxe-plan-v1",
        "plan_kind": "continuation",
        "goal": SP004_GOAL,
        "status": "planning",
        "reasoning": "The furnace and exact inputs are machine observed.",
        "subtasks": [],
        "actions": [
            {
                "type": "smelt",
                "parameters": {
                    "item": "iron_ingot",
                    "input": "raw_iron",
                    "fuel": "coal",
                    "count": 3,
                    "x": 2,
                    "y": 65,
                    "z": 1,
                },
            }
        ],
    }

    report = IronPickaxeSP004Planner._validate_stone_pickaxe_plan_envelope(
        plan,
        expected_goal=SP004_GOAL,
        expected_kind="continuation",
        runtime_mode="sp004",
    )

    assert report["passed"] is True


def test_strict_planner_prompt_binds_authoritative_sp004_stage():
    planner = object.__new__(IronPickaxeSP004Planner)
    planner.strict_m2 = False
    planner.strict_m4 = False
    planner.strict_stone_pickaxe = True
    planner._expected_plan_kind = "continuation"
    state = {
        "stone_pickaxe_runtime_mode": "sp004",
        "sp004_stage": "smelt_iron",
        "sp004_progress": {},
        "sp004_target": {
            "name": "furnace",
            "position": {"x": 2, "y": 65, "z": 1},
            "distance": 2.0,
        },
        "inventory": {"raw_iron": 3, "coal": 10},
        "nearby_blocks": [
            {
                "name": "furnace",
                "position": {"x": 2, "y": 65, "z": 1},
                "distance": 2.0,
            }
        ],
    }

    prompt = planner._build_planning_prompt(SP004_GOAL, state, "")

    assert "Authoritative stage: smelt_iron" in prompt
    assert "item=iron_ingot input=raw_iron fuel=coal count=3" in prompt
    assert '"runtime_mode":"sp004"' in prompt
