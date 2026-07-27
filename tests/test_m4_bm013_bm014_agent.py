"""Focused strict-M4 BM-013/014 goal, planning, and terminal tests."""

import copy
from types import SimpleNamespace

from singularity.core.agent import Agent
from singularity.core.goal_generator import GoalGenerator
from singularity.core.goal_verifier import GoalVerifier
from singularity.core.planner import Planner
from singularity.evaluation.m4_protocol import PROTOCOL, PROTOCOL_SHA256


def _observation(inventory=None, nearby_blocks=None, **overrides):
    state = {
        "health": 20,
        "hunger": 20,
        "time_of_day": 0,
        "position": {"x": 0, "y": 64, "z": 0},
        "inventory": dict(inventory or {}),
        "nearby_blocks": list(nearby_blocks or []),
        "nearby_entities": [],
    }
    state.update(overrides)
    return state


def _table():
    return {
        "name": "crafting_table",
        "position": {"x": 1, "y": 63, "z": 0},
        "distance": 1.5,
    }


def _furnace():
    return {
        "name": "furnace",
        "position": {"x": 2, "y": 63, "z": 0},
        "distance": 2.5,
    }


def _machine_agent(task_id):
    agent = object.__new__(Agent)
    agent.config = SimpleNamespace(planner_protocol="m4-fixed-v1")
    agent._m4_task_id = task_id
    agent._m4_real_schema_valid_llm_call_observed = True
    agent._m4_real_schema_valid_llm_call_evidence = {
        "policy_id": "m4-bm013-bm014-real-schema-valid-llm-gate-v1",
        "call_id": "llm-fixture",
        "real_llm_call": True,
        "schema_valid": True,
    }
    agent.planner = SimpleNamespace(
        _active_root_plan_id="root-fixture",
        _last_call_id="llm-fixture",
    )
    agent.session_logger = SimpleNamespace(events=[], log=lambda *args, **kwargs: None)
    agent._write_memory_episode = lambda *args, **kwargs: None
    return agent


def _lifecycle(task_id):
    episode_id = f"m4-{task_id.lower()}-fixture"
    return {
        "type": "m4_player_lifecycle",
        "schema_version": 1,
        "verifier_id": PROTOCOL["identities"]["player_lifecycle_verifier"],
        "source": "mineflayer_events",
        "profile": PROTOCOL["profile"],
        "protocol_sha256": PROTOCOL_SHA256,
        "tracker_id": f"{task_id.lower()}-tracker",
        "episode_id": episode_id,
        "level_name": f"{episode_id}_world",
        "baseline_id": "b" * 64,
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


def test_bm013_goal_generator_follows_fresh_exact_chain_and_safety_priority():
    generator = GoalGenerator()
    cases = [
        ({}, [], "Gather 6 oak logs for iron-tool progression"),
        ({"oak_log": 6}, [], "Craft a crafting table for iron-tool progression"),
        (
            {"crafting_table": 1, "oak_log": 5},
            [],
            "Craft a wooden pickaxe for cobblestone acquisition",
        ),
        (
            {"wooden_pickaxe": 1, "cobblestone": 10},
            [_table()],
            "Gather 11 cobblestone for stone pickaxe and furnace",
        ),
        (
            {"wooden_pickaxe": 1, "cobblestone": 11},
            [_table()],
            "Craft a stone pickaxe for ore acquisition",
        ),
        (
            {"stone_pickaxe": 1, "cobblestone": 8},
            [_table()],
            "Collect 1 raw iron from iron ore with the stone pickaxe",
        ),
        (
            {"stone_pickaxe": 1, "cobblestone": 8, "raw_iron": 1},
            [_table()],
            "Collect 1 coal for furnace fuel with the stone pickaxe",
        ),
        (
            {
                "stone_pickaxe": 1,
                "cobblestone": 8,
                "raw_iron": 1,
                "coal": 1,
            },
            [_table()],
            "Craft a furnace for iron smelting",
        ),
        (
            {"stone_pickaxe": 1, "raw_iron": 1, "coal": 1, "furnace": 1},
            [_table()],
            "Smelt an iron ingot",
        ),
        (
            {"iron_ingot": 1},
            [_table(), _furnace()],
            "Smelt an iron ingot",
        ),
    ]
    for inventory, blocks, expected in cases:
        assert (
            generator.next_goal(
                _observation(inventory, blocks),
                task_id="BM-013",
            )
            == expected
        )

    threatened = _observation(
        {},
        [],
        nearby_entities=[{"hostile": True, "distance": 3}],
    )
    assert generator.next_goal(threatened, task_id="BM-013").startswith("Flee")


def test_bm014_goal_generator_batches_three_iron_then_finishes_pickaxe_chain():
    generator = GoalGenerator()
    table = [_table()]
    assert generator.next_goal(
        _observation(
            {"stone_pickaxe": 1, "cobblestone": 8},
            table,
        ),
        task_id="BM-014",
    ).startswith("Collect 3 raw iron")
    assert generator.next_goal(
        _observation(
            {
                "stone_pickaxe": 1,
                "raw_iron": 3,
                "coal": 1,
                "furnace": 1,
            },
            table,
        ),
        task_id="BM-014",
    ) == "Smelt 3 iron ingots from 3 raw iron using coal"
    assert generator.next_goal(
        _observation({"iron_ingot": 3}, table),
        task_id="BM-014",
    ) == "Ensure 2 sticks for crafting the iron pickaxe"
    assert generator.next_goal(
        _observation({"iron_ingot": 3, "stick": 2}, table),
        task_id="BM-014",
    ) == "Craft an iron pickaxe"
    assert generator.next_goal(
        _observation({"iron_pickaxe": 1}, [_table(), _furnace()]),
        task_id="BM-014",
    ) == "Craft an iron pickaxe"


def test_bm014_stick_machine_step_closes_goal_before_iron_pickaxe_frontier():
    generator = GoalGenerator()
    verifier = GoalVerifier()
    agent = _machine_agent("BM-014")
    before = _observation(
        {"iron_ingot": 3, "oak_planks": 2},
        [_table(), _furnace()],
    )
    goal = generator.next_goal(before, task_id="BM-014")
    assert goal == "Ensure 2 sticks for crafting the iron pickaxe"

    plan = agent._m4_bm013_bm014_toolchain_machine_step_plan(before, goal)
    assert plan["actions"] == [
        {"type": "craft", "parameters": {"item": "stick", "count": 4}}
    ]
    assert plan["machine_step_plan"]["reason"] == "craft_sticks_for_iron_pickaxe"

    after = _observation(
        {"iron_ingot": 3, "stick": 4},
        [_table(), _furnace()],
    )
    verification = verifier.verify(
        goal,
        after,
        recent_actions=[{
            "action": plan["actions"][0],
            "result": {"success": True},
            "before_observation": before,
            "after_observation": after,
        }],
    )
    assert verification.achieved
    assert verification.target_inventory == {"stick": 2}
    assert verification.inventory_delta == {"stick": 4}
    assert "inventory:iron_pickaxe" not in verification.matched_rules
    assert generator.next_goal(after, task_id="BM-014") == "Craft an iron pickaxe"


def test_bm014_stick_frontier_preserves_two_step_log_to_planks_to_sticks():
    generator = GoalGenerator()
    verifier = GoalVerifier()
    agent = _machine_agent("BM-014")
    goal = "Ensure 2 sticks for crafting the iron pickaxe"
    log_state = _observation(
        {"iron_ingot": 3, "oak_log": 1},
        [_table(), _furnace()],
    )
    assert generator.next_goal(log_state, task_id="BM-014") == goal

    planks_plan = agent._m4_bm013_bm014_toolchain_machine_step_plan(
        log_state,
        goal,
    )
    assert planks_plan["actions"] == [
        {"type": "craft", "parameters": {"item": "oak_planks", "count": 4}}
    ]
    assert (
        planks_plan["machine_step_plan"]["reason"]
        == "craft_oak_planks_for_iron_pickaxe_sticks"
    )

    planks_state = _observation(
        {"iron_ingot": 3, "oak_planks": 4},
        [_table(), _furnace()],
    )
    assert not verifier.verify(goal, planks_state).achieved
    assert generator.next_goal(planks_state, task_id="BM-014") == goal

    sticks_plan = agent._m4_bm013_bm014_toolchain_machine_step_plan(
        planks_state,
        goal,
    )
    assert sticks_plan["actions"] == [
        {"type": "craft", "parameters": {"item": "stick", "count": 4}}
    ]
    assert (
        sticks_plan["machine_step_plan"]["reason"]
        == "craft_sticks_for_iron_pickaxe"
    )


def test_bm013_bm014_machine_steps_require_real_schema_valid_llm_gate():
    agent = _machine_agent("BM-013")
    state = _observation(
        {},
        [{"name": "oak_log", "position": {"x": 1, "y": 64, "z": 0}, "distance": 1}],
    )
    agent._m4_real_schema_valid_llm_call_observed = False
    assert agent._m4_bm013_bm014_toolchain_machine_step_plan(
        state,
        "Gather 6 oak logs for iron-tool progression",
    ) is None
    bm014 = _machine_agent("BM-014")
    bm014._m4_real_schema_valid_llm_call_observed = False
    assert bm014._m4_bm013_bm014_toolchain_machine_step_plan(
        _observation(
            {"iron_ingot": 3, "oak_planks": 2},
            [_table(), _furnace()],
        ),
        "Ensure 2 sticks for crafting the iron pickaxe",
    ) is None

    agent._m4_real_schema_valid_llm_call_observed = True
    plan = agent._m4_bm013_bm014_toolchain_machine_step_plan(
        state,
        "Gather 6 oak logs for iron-tool progression",
    )
    assert plan["actions"] == [
        {
            "type": "dig",
            "parameters": {"x": 1, "y": 64, "z": 0, "block": "oak_log"},
        }
    ]
    assert plan["machine_step_plan"]["qualifying_llm_call_id"] == "llm-fixture"


def test_machine_smelt_batches_bind_exact_materials_and_observed_furnace():
    for task_id, count, goal in (
        ("BM-013", 1, "Smelt an iron ingot"),
        ("BM-014", 3, "Smelt 3 iron ingots from 3 raw iron using coal"),
    ):
        agent = _machine_agent(task_id)
        plan = agent._m4_bm013_bm014_toolchain_machine_step_plan(
            _observation(
                {"raw_iron": count, "coal": 1},
                [_furnace(), _table()],
            ),
            goal,
        )
        assert plan["actions"] == [
            {
                "type": "smelt",
                "parameters": {
                    "item": "iron_ingot",
                    "input": "raw_iron",
                    "fuel": "coal",
                    "count": count,
                    "x": 2,
                    "y": 63,
                    "z": 0,
                    "timeout_ms": 35000,
                },
            }
        ]
        assert plan["machine_step_plan"]["target"]["name"] == "furnace"


def test_machine_furnace_place_coal_search_and_iron_pickaxe_actions_are_bounded():
    bm013 = _machine_agent("BM-013")
    furnace_craft = bm013._m4_bm013_bm014_toolchain_machine_step_plan(
        _observation(
            {"cobblestone": 8, "stone_pickaxe": 1},
            [_table()],
        ),
        "Craft a furnace for iron smelting",
    )
    assert furnace_craft["actions"] == [
        {"type": "craft", "parameters": {"item": "furnace", "count": 1}}
    ]

    place = bm013._m4_bm013_bm014_toolchain_machine_step_plan(
        _observation(
            {"raw_iron": 1, "coal": 1, "furnace": 1},
            [
                _table(),
                {
                    "name": "grass_block",
                    "position": {"x": 3, "y": 63, "z": 0},
                    "distance": 3,
                },
            ],
        ),
        "Smelt an iron ingot",
    )
    assert place["actions"][0]["type"] == "place"
    assert place["actions"][0]["parameters"]["item"] == "furnace"
    assert place["machine_step_plan"]["place_candidate_bound_policy_id"]

    search = bm013._m4_bm013_bm014_toolchain_machine_step_plan(
        _observation(
            {"stone_pickaxe": 1, "held_item": "stone_pickaxe"},
            [
                {
                    "name": "stone",
                    "position": {"x": 1, "y": 63, "z": 0},
                    "distance": 2,
                }
            ],
            held_item="stone_pickaxe",
        ),
        "Collect 1 coal for furnace fuel with the stone pickaxe",
    )
    assert search["actions"][0]["type"] == "dig"
    assert search["machine_step_plan"]["reason"] == (
        "dig_search_block_for_coal_with_stone_pickaxe"
    )

    bm014 = _machine_agent("BM-014")
    craft = bm014._m4_bm013_bm014_toolchain_machine_step_plan(
        _observation(
            {"iron_ingot": 3, "stick": 2},
            [_table()],
        ),
        "Craft an iron pickaxe",
    )
    assert craft["actions"] == [
        {"type": "craft", "parameters": {"item": "iron_pickaxe", "count": 1}}
    ]


def test_planner_smelt_grounding_requires_exact_integer_furnace_coordinates():
    valid = {
        "actions": [
            {
                "type": "smelt",
                "parameters": {
                    "item": "iron_ingot",
                    "input": "raw_iron",
                    "fuel": "coal",
                    "count": 3,
                    "x": 4,
                    "y": 63,
                    "z": 2,
                    "timeout_ms": 35000,
                },
            }
        ]
    }
    grounded, report = Planner._ground_m4_action_parameters(valid)
    assert report["passed"] is True
    assert report["smelt_action_count"] == 1
    assert grounded == valid

    fractional = copy.deepcopy(valid)
    fractional["actions"][0]["parameters"]["x"] = 4.5
    _, rejected = Planner._ground_m4_action_parameters(fractional)
    assert rejected["passed"] is False
    assert any("smelt_furnace_coordinates" in issue for issue in rejected["issues"])

    missing_fuel = copy.deepcopy(valid)
    missing_fuel["actions"][0]["parameters"].pop("fuel")
    _, rejected = Planner._ground_m4_action_parameters(missing_fuel)
    assert rejected["passed"] is False
    assert any("smelt_fuel_missing_or_invalid" in issue for issue in rejected["issues"])


def test_bm013_bm014_terminal_verification_binds_task_inventory_connection_and_lifecycle():
    for task_id, goal, inventory, item in (
        ("BM-013", "Smelt an iron ingot", {"iron_ingot": 1}, "iron_ingot"),
        ("BM-014", "Craft an iron pickaxe", {"iron_pickaxe": 1}, "iron_pickaxe"),
    ):
        lifecycle = _lifecycle(task_id)
        agent = _machine_agent(task_id)
        agent._m4_player_lifecycle_identity = Agent._m4_lifecycle_identity(lifecycle)
        agent.bot = SimpleNamespace(
            _connected=True,
            get_player_lifecycle=lambda lifecycle=lifecycle: copy.deepcopy(lifecycle),
        )
        state = _observation(
            inventory,
            [_furnace(), _table()],
            player_lifecycle=copy.deepcopy(lifecycle),
        )
        verification = agent._m4_terminal_task_verification(task_id, goal, state)
        assert verification["type"] == "m4_terminal_task_verification"
        assert verification["task_id"] == task_id
        assert verification["output_item"] == item
        assert verification["inventory"][item] == 1
        assert verification["bot_connected"] is True

        agent.bot._connected = False
        assert not agent._m4_terminal_task_verification(task_id, goal, state)
        agent.bot._connected = True
        wrong_goal = "Smelt an iron ingot" if task_id == "BM-014" else "Craft an iron pickaxe"
        assert not agent._m4_terminal_task_verification(task_id, wrong_goal, state)
