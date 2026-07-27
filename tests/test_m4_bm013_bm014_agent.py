"""Focused strict-M4 BM-013/014 goal, planning, and terminal tests."""

import copy
from types import SimpleNamespace

from singularity.core.agent import Agent
from singularity.action.verifier import ActionVerifier
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


def _machine_block(name, position, *, solid):
    return {
        "name": name,
        "type": 1 if solid else 0,
        "position": dict(position),
        "collision": "block" if solid else "empty",
        "solid": solid,
        "passable": not solid,
    }


def _complete_local_machine_state(
    *overrides,
    player_cell=None,
    observed_at_ms=1785125823000,
):
    player_cell = dict(player_cell or {"x": 118, "y": 123, "z": -50})
    blocks = {}
    for dx in range(-1, 2):
        for dy in range(-1, 3):
            for dz in range(-1, 2):
                position = {
                    "x": player_cell["x"] + dx,
                    "y": player_cell["y"] + dy,
                    "z": player_cell["z"] + dz,
                }
                blocks[(position["x"], position["y"], position["z"])] = (
                    _machine_block("air", position, solid=False)
                )
    for block in overrides:
        position = block["position"]
        blocks[(position["x"], position["y"], position["z"])] = copy.deepcopy(
            block,
        )
    return {
        "success": True,
        "type": "m4_shelter_machine_snapshot",
        "source": "mineflayer_world_state",
        "player_position": {
            "x": player_cell["x"] + 0.5,
            "y": player_cell["y"],
            "z": player_cell["z"] + 0.5,
        },
        "player_cell": player_cell,
        "observed_at_ms": observed_at_ms,
        "blocks": list(blocks.values()),
    }


def _machine_snapshot_check(*, passed=True):
    return {
        "name": "machine_snapshot",
        "passed": passed,
        "evidence": {
            "expected_snapshot_position_count": 36,
            "observed_snapshot_position_count": 36,
            "duplicate_positions": [],
        },
    }


def _local_place_snapshot(
    reference_block,
    target_block,
    *,
    policy_id="m4-bm013-bm014-furnace-place-local-snapshot-v1",
):
    reference = {
        **copy.deepcopy(reference_block),
        "machine_observed": True,
        "machine_state_source": "get_shelter_state.blocks",
        "grounding_policy_id": policy_id,
    }
    target = {
        **copy.deepcopy(target_block),
        "machine_observed": True,
        "machine_state_source": "get_shelter_state.blocks",
        "grounding_policy_id": policy_id,
    }
    return {
        "schema_version": 1,
        "policy_id": policy_id,
        "source": "get_shelter_state.blocks",
        "machine_snapshot_passed": True,
        "player_position": {"x": 0.5, "y": 64.0, "z": 0.5},
        "player_cell": {"x": 0, "y": 64, "z": 0},
        "observed_at_ms": 1785125823000,
        "snapshot_position_count": 36,
        "candidate_limit": 27,
        "candidate_count": 1,
        "candidates": [{
            "reference_block": reference,
            "target_block": target,
        }],
    }


def _crafting_table_local_place_snapshot(reference_block, target_block):
    return _local_place_snapshot(
        reference_block,
        target_block,
        policy_id=(
            "m4-bm013-bm014-crafting-table-place-local-snapshot-v1"
        ),
    )


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
            m4_local_place_candidates=_local_place_snapshot(
                _machine_block(
                    "crafting_table",
                    {"x": 1, "y": 63, "z": 0},
                    solid=True,
                ),
                _machine_block(
                    "air",
                    {"x": 1, "y": 64, "z": 0},
                    solid=False,
                ),
            ),
        ),
        "Smelt an iron ingot",
    )
    assert place["actions"][0]["type"] == "place"
    assert place["actions"][0]["parameters"]["item"] == "furnace"
    assert place["machine_step_plan"]["place_candidate_bound_policy_id"]
    assert place["machine_step_plan"]["furnace_place_local_snapshot_policy_id"] == (
        "m4-bm013-bm014-furnace-place-local-snapshot-v1"
    )

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


def test_remote_ore_move_reclaims_only_a_current_episode_owned_crafting_table():
    agent = _machine_agent("BM-014")
    table = _table()
    table_position = table["position"]
    table_key = ",".join(str(table_position[axis]) for axis in ("x", "y", "z"))
    agent._m4_episode_block_delta = {
        "placed": {
            table_key: {
                "operation": "place",
                "action_type": "place",
                "success": True,
                "position": table_position,
                "before": {"name": "air"},
                "after": {"name": "crafting_table"},
            },
        },
        "removed": {},
    }
    remote_iron = {
        "name": "iron_ore",
        "position": {"x": 12, "y": 62, "z": 0},
        "distance": 12,
    }
    state = _observation(
        {
            "stone_pickaxe": 1,
            "cobblestone": 8,
            "held_item": "stone_pickaxe",
        },
        [table, remote_iron],
        held_item="stone_pickaxe",
    )
    plan = agent._m4_bm013_bm014_toolchain_machine_step_plan(
        state,
        "Collect 3 raw iron from iron ore with the stone pickaxe",
    )
    assert plan["actions"] == [{
        "type": "dig",
        "parameters": {**table_position, "block": "crafting_table"},
    }]
    evidence = plan["machine_step_plan"]
    assert evidence["reason"] == (
        "reclaim_episode_owned_crafting_table_before_remote_resource_move"
    )
    assert evidence["target"]["machine_observed"] is True
    assert evidence["target"]["episode_owned"] is True
    assert evidence["target"]["requires_current_observation_before_use"] is True
    assert evidence["portable_crafting_table_recovery_policy_id"] == (
        "m4-bm013-bm014-portable-crafting-table-recovery-v1"
    )

    unowned = _machine_agent("BM-014")
    unowned._m4_episode_block_delta = {"placed": {}, "removed": {}}
    unowned_plan = unowned._m4_bm013_bm014_toolchain_machine_step_plan(
        state,
        "Collect 3 raw iron from iron ore with the stone pickaxe",
    )
    assert unowned_plan["actions"] == [{
        "type": "move_to",
        "parameters": remote_iron["position"],
    }]
    assert (
        unowned_plan["machine_step_plan"][
            "portable_crafting_table_recovery_policy_id"
        ]
        is None
    )

    out_of_range = _machine_agent("BM-014")
    out_of_range._m4_episode_block_delta = agent._m4_episode_block_delta
    remote_table = {
        **table,
        "distance": 5,
    }
    out_of_range_plan = (
        out_of_range._m4_bm013_bm014_toolchain_machine_step_plan(
            _observation(
                {
                    "stone_pickaxe": 1,
                    "cobblestone": 8,
                    "held_item": "stone_pickaxe",
                },
                [remote_table, remote_iron],
                held_item="stone_pickaxe",
            ),
            "Collect 3 raw iron from iron ore with the stone pickaxe",
        )
    )
    assert out_of_range_plan["actions"] == [{
        "type": "move_to",
        "parameters": remote_iron["position"],
    }]


def test_probe54_missing_station_returns_to_nearest_retained_owned_table():
    agent = _machine_agent("BM-014")
    far_position = {"x": 112, "y": 136, "z": -28}
    near_position = {"x": 113, "y": 128, "z": -29}

    def placed_record(position):
        return {
            "operation": "place",
            "action_type": "place",
            "success": True,
            "position": position,
            "before": {"name": "air"},
            "after": {"name": "crafting_table"},
        }

    agent._m4_episode_block_delta = {
        "placed": {
            "112,136,-28": placed_record(far_position),
            "113,128,-29": placed_record(near_position),
        },
        # Probe 54 had mined stone from the eventual near table cell before
        # placing the table there, so the aggregate buckets contain both keys.
        "removed": {
            "113,128,-29": {
                "operation": "remove",
                "action_type": "dig",
                "success": True,
                "position": near_position,
                "before": {"name": "stone"},
                "after": {"name": "air"},
            },
        },
    }
    agent.session_logger.events = [
        {
            "type": "action",
            "data": {
                "action": {
                    "type": "place",
                    "parameters": {"item": "crafting_table", **far_position},
                },
                "result": {
                    "success": True,
                    "target_block_before": {
                        "name": "air",
                        "position": far_position,
                    },
                    "target_block_after": {
                        "name": "crafting_table",
                        "position": far_position,
                    },
                },
            },
        },
        {
            "type": "action",
            "data": {
                "action": {
                    "type": "dig",
                    "parameters": {"block": "stone", **near_position},
                },
                "result": {
                    "success": True,
                    "target_block_before": {
                        "name": "stone",
                        "position": near_position,
                    },
                    "target_block_after": {
                        "name": "air",
                        "position": near_position,
                    },
                },
            },
        },
        {
            "type": "action",
            "data": {
                "action": {
                    "type": "place",
                    "parameters": {"item": "crafting_table", **near_position},
                },
                "result": {
                    "success": True,
                    "target_block_before": {
                        "name": "air",
                        "position": near_position,
                    },
                    "target_block_after": {
                        "name": "crafting_table",
                        "position": near_position,
                    },
                },
            },
        },
    ]
    state = _observation(
        {
            "wooden_pickaxe": 1,
            "stone_pickaxe": 1,
            "cobblestone": 80,
            "raw_iron": 4,
            "coal": 1,
            "oak_planks": 3,
        },
        [],
        position={"x": 118.5, "y": 123, "z": -49.49},
    )
    plan = agent._m4_bm013_bm014_toolchain_machine_step_plan(
        state,
        "Craft a furnace for iron smelting",
    )
    assert plan["actions"] == [{
        "type": "move_to",
        "parameters": near_position,
    }]
    evidence = plan["machine_step_plan"]
    assert evidence["reason"] == (
        "return_to_episode_owned_crafting_table_for_current_reobservation"
    )
    assert evidence["target"]["machine_observed"] is False
    assert evidence["target"]["historically_machine_verified"] is True
    assert evidence["target"]["episode_owned"] is True
    assert evidence["target"]["requires_current_observation_before_use"] is True
    assert evidence["portable_crafting_table_recovery_policy_id"] == (
        "m4-bm013-bm014-portable-crafting-table-recovery-v1"
    )


def test_missing_station_uses_only_machine_observed_log_or_fails_closed():
    agent = _machine_agent("BM-014")
    agent._m4_episode_block_delta = {"placed": {}, "removed": {}}
    inventory = {
        "stone_pickaxe": 1,
        "cobblestone": 80,
        "raw_iron": 4,
        "coal": 1,
        "oak_planks": 3,
    }
    oak = {
        "name": "oak_log",
        "position": {"x": 2, "y": 64, "z": 0},
        "distance": 2,
    }
    recovery = agent._m4_bm013_bm014_toolchain_machine_step_plan(
        _observation(inventory, [oak]),
        "Craft a furnace for iron smelting",
    )
    assert recovery["actions"] == [{
        "type": "dig",
        "parameters": {**oak["position"], "block": "oak_log"},
    }]
    assert recovery["machine_step_plan"]["reason"] == (
        "dig_verified_oak_log_for_portable_crafting_table_recovery"
    )
    assert recovery["machine_step_plan"]["target"]["recovery_mode"] == (
        "machine_observed_log"
    )

    blocked = agent._m4_bm013_bm014_toolchain_machine_step_plan(
        _observation(inventory, []),
        "Craft a furnace for iron smelting",
    )
    assert blocked["status"] == "blocked"
    assert blocked["actions"] == []
    assert blocked["reason_code"] == (
        "portable_crafting_table_recovery_unavailable"
    )
    assert blocked["bounded_block"]["policy_id"] == (
        "m4-bm013-bm014-portable-crafting-table-recovery-v1"
    )
    assert blocked["bounded_block"]["fallback_suppressed"] is True
    assert "llm_plan" in blocked["bounded_block"]["suppressed_paths"]


def test_missing_station_does_not_loop_on_an_unobserved_reached_table_target():
    agent = _machine_agent("BM-014")
    position = {"x": 1, "y": 63, "z": 0}
    agent._m4_episode_block_delta = {
        "placed": {
            "1,63,0": {
                "operation": "place",
                "action_type": "place",
                "success": True,
                "position": position,
                "before": {"name": "air"},
                "after": {"name": "crafting_table"},
            },
        },
        "removed": {},
    }
    inventory = {
        "stone_pickaxe": 1,
        "cobblestone": 80,
        "raw_iron": 4,
        "coal": 1,
        "oak_planks": 3,
    }
    reached_without_table = _observation(
        inventory,
        [],
        position={"x": 1.5, "y": 63, "z": 0.5},
    )
    blocked = agent._m4_bm013_bm014_toolchain_machine_step_plan(
        reached_without_table,
        "Craft a furnace for iron smelting",
    )
    assert blocked["status"] == "blocked"
    assert blocked["actions"] == []
    assert blocked["reason_code"] == (
        "portable_crafting_table_recovery_unavailable"
    )

    oak = {
        "name": "oak_log",
        "position": {"x": 2, "y": 63, "z": 0},
        "distance": 1,
    }
    recover = agent._m4_bm013_bm014_toolchain_machine_step_plan(
        _observation(
            inventory,
            [oak],
            position={"x": 1.5, "y": 63, "z": 0.5},
        ),
        "Craft a furnace for iron smelting",
    )
    assert recover["actions"] == [{
        "type": "dig",
        "parameters": {**oak["position"], "block": "oak_log"},
    }]
    assert recover["machine_step_plan"]["target"]["recovery_mode"] == (
        "machine_observed_log"
    )


def test_removed_owned_table_is_not_a_return_target_and_bm012_is_unchanged():
    agent = _machine_agent("BM-014")
    position = {"x": 1, "y": 63, "z": 0}
    record = {
        "operation": "place",
        "action_type": "place",
        "success": True,
        "position": position,
        "before": {"name": "air"},
        "after": {"name": "crafting_table"},
    }
    agent._m4_episode_block_delta = {
        "placed": {"1,63,0": record},
        "removed": {
            "1,63,0": {
                "operation": "remove",
                "action_type": "dig",
                "success": True,
                "position": position,
                "before": {"name": "crafting_table"},
                "after": {"name": "air"},
            },
        },
    }
    blocked = agent._m4_bm013_bm014_toolchain_machine_step_plan(
        _observation(
            {"stone_pickaxe": 1, "cobblestone": 8, "oak_planks": 3},
            [],
        ),
        "Craft a furnace for iron smelting",
    )
    assert blocked["reason_code"] == (
        "portable_crafting_table_recovery_unavailable"
    )

    bm012 = _machine_agent("BM-012")
    bm012._m4_episode_block_delta = {
        "placed": {"1,63,0": record},
        "removed": {},
    }
    action, reason, target = bm012._m4_bm012_crafting_table_access_action(
        _observation({"oak_planks": 3}, []),
        {"oak_planks": 3},
    )
    assert action is None
    assert reason == "crafting_table_materials_missing"
    assert target == {}


def test_probe51_furnace_place_uses_machine_verified_table_top_instead_of_cave_shell():
    agent = _machine_agent("BM-014")
    table_position = {"x": 118, "y": 122, "z": -49}
    target_position = {"x": 118, "y": 123, "z": -49}
    machine_state = _complete_local_machine_state(
        _machine_block("crafting_table", table_position, solid=True),
        _machine_block("air", target_position, solid=False),
        _machine_block(
            "stone",
            {"x": 119, "y": 124, "z": -49},
            solid=True,
        ),
        _machine_block(
            "stone",
            {"x": 119, "y": 125, "z": -49},
            solid=True,
        ),
    )
    snapshot = agent._m4_bm013_bm014_local_place_candidate_snapshot(
        machine_state,
        {"checks": [_machine_snapshot_check()]},
    )
    assert snapshot["snapshot_position_count"] == 36
    assert snapshot["candidate_count"] == 1
    assert snapshot["player_position"] == machine_state["player_position"]
    assert snapshot["candidates"][0]["reference_block"]["position"] == table_position
    assert snapshot["candidates"][0]["target_block"]["position"] == target_position

    observation = _observation(
        {"raw_iron": 3, "coal": 1, "furnace": 1},
        [
            {
                "name": "stone",
                "position": {"x": 117, "y": 123, "z": -50},
                "distance": 1,
            },
            {
                "name": "crafting_table",
                "position": table_position,
                "distance": 1.414,
            },
            {
                "name": "stone",
                "position": {"x": 119, "y": 124, "z": -49},
                "distance": 1.732,
            },
        ],
        position={"x": 118.5, "y": 123, "z": -49.5},
        m4_local_place_candidates=snapshot,
    )
    plan = agent._m4_bm013_bm014_toolchain_machine_step_plan(
        observation,
        "Smelt 3 iron ingots from 3 raw iron using coal",
    )
    action = plan["actions"][0]
    assert action == {
        "type": "place",
        "parameters": {
            "item": "furnace",
            "x": 118,
            "y": 122,
            "z": -49,
        },
    }
    assert plan["machine_step_plan"]["reason"] == (
        "place_owned_furnace_at_machine_verified_local_air_target"
    )
    assert plan["machine_step_plan"]["target"]["target_position"] == target_position
    assert plan["machine_step_plan"]["target"]["target_block"]["name"] == "air"

    decision = ActionVerifier().verify(
        action,
        observation,
        goal="Smelt 3 iron ingots from 3 raw iron using coal",
        protocol="m4-fixed-v1",
        task_id="BM-014",
    )
    assert decision.status == "accept"
    assert "target:air" in decision.evidence
    assert "target:not_observed_occupied" not in decision.evidence


def test_furnace_local_place_candidates_attach_only_after_machine_snapshot_passes():
    agent = _machine_agent("BM-014")
    machine_state = _complete_local_machine_state(
        _machine_block(
            "crafting_table",
            {"x": 118, "y": 122, "z": -49},
            solid=True,
        ),
        _machine_block(
            "air",
            {"x": 118, "y": 123, "z": -49},
            solid=False,
        ),
        _machine_block(
            "stone",
            {"x": 119, "y": 123, "z": -50},
            solid=True,
        ),
    )
    report = {
        "passed": False,
        "issues": ["physical_barriers"],
        "checks": [
            _machine_snapshot_check(),
            {"name": "physical_barriers", "passed": False},
        ],
    }
    agent.bot = SimpleNamespace(get_shelter_state=lambda: copy.deepcopy(machine_state))
    agent.m4_shelter_verifier = SimpleNamespace(
        verify=lambda state, delta: copy.deepcopy(report),
    )
    agent._m4_episode_block_delta = {"placed": {}, "removed": {}}
    agent._m4_shelter_verification_fingerprint = ""
    attached = agent._attach_m4_shelter_verification(
        _observation(
            {"raw_iron": 3, "coal": 1, "furnace": 1},
            [],
            position={"x": 118.5, "y": 123, "z": -49.5},
        )
    )
    assert attached["shelter_verification"]["passed"] is False
    assert attached["m4_local_place_candidates"]["candidate_count"] == 2
    assert attached["m4_crafting_table_place_candidates"]["candidate_count"] == 1
    assert attached["m4_crafting_table_place_candidates"]["policy_id"] == (
        "m4-bm013-bm014-crafting-table-place-local-snapshot-v1"
    )

    failed_report = copy.deepcopy(report)
    failed_report["checks"][0]["passed"] = False
    agent.m4_shelter_verifier = SimpleNamespace(
        verify=lambda state, delta: copy.deepcopy(failed_report),
    )
    not_attached = agent._attach_m4_shelter_verification(
        _observation(
            {"raw_iron": 3, "coal": 1, "furnace": 1},
            [],
        )
    )
    assert "m4_local_place_candidates" not in not_attached
    assert "m4_crafting_table_place_candidates" not in not_attached


def test_furnace_local_snapshot_selection_fails_closed_on_incomplete_or_unsafe_evidence():
    agent = _machine_agent("BM-014")
    table = _machine_block(
        "crafting_table",
        {"x": 118, "y": 122, "z": -49},
        solid=True,
    )
    air = _machine_block(
        "air",
        {"x": 118, "y": 123, "z": -49},
        solid=False,
    )
    passed_report = {"checks": [_machine_snapshot_check()]}
    base_state = _complete_local_machine_state(table, air)

    assert agent._m4_bm013_bm014_local_place_candidate_snapshot(
        base_state,
        {"checks": [_machine_snapshot_check(passed=False)]},
    ) == {}
    without_target = copy.deepcopy(base_state)
    without_target["blocks"] = [
        block
        for block in without_target["blocks"]
        if block["position"] != air["position"]
    ]
    assert agent._m4_bm013_bm014_local_place_candidate_snapshot(
        without_target,
        passed_report,
    ) == {}
    occupied_target = _machine_block(
        "clay",
        {"x": 118, "y": 123, "z": -49},
        solid=True,
    )
    assert agent._m4_bm013_bm014_local_place_candidate_snapshot(
        _complete_local_machine_state(table, occupied_target),
        passed_report,
    )["candidate_count"] == 0
    duplicate_state = copy.deepcopy(base_state)
    duplicate_state["blocks"][-1] = copy.deepcopy(air)
    assert agent._m4_bm013_bm014_local_place_candidate_snapshot(
        duplicate_state,
        passed_report,
    ) == {}

    snapshot = agent._m4_bm013_bm014_local_place_candidate_snapshot(
        base_state,
        passed_report,
    )
    current_occupied_observation = _observation(
        {"raw_iron": 3, "coal": 1, "furnace": 1},
        [
            {"name": "crafting_table", "position": table["position"]},
            {"name": "stone", "position": air["position"]},
        ],
        position={"x": 118.5, "y": 123, "z": -49.5},
        m4_local_place_candidates=snapshot,
    )
    assert agent._m4_bm013_bm014_furnace_place_reference(
        current_occupied_observation,
    ) == {}
    current_occupied_decision = ActionVerifier().verify(
        {
            "type": "place",
            "parameters": {"item": "furnace", **table["position"]},
        },
        current_occupied_observation,
        protocol="m4-fixed-v1",
        task_id="BM-014",
    )
    assert current_occupied_decision.status == "reject"
    assert "observed_target:stone" in current_occupied_decision.evidence

    collision_observation = _observation(
        {"raw_iron": 3, "coal": 1, "furnace": 1},
        [{"name": "crafting_table", "position": table["position"]}],
        position={"x": 118.5, "y": 123, "z": -48.5},
        m4_local_place_candidates=snapshot,
    )
    assert agent._m4_bm013_bm014_furnace_place_reference(
        collision_observation,
    ) == {}

    failed_event = {
        "type": "action",
        "data": {
            "action": {
                "type": "place",
                "parameters": {"item": "furnace", **table["position"]},
            },
            "result": {
                "success": False,
                "error": "placement target is occupied by stone",
                "placed_position": air["position"],
                "target_block_before": {
                    "name": "stone",
                    "position": air["position"],
                },
            },
        },
    }
    agent.session_logger.events = [failed_event]
    failed_observation = _observation(
        {"raw_iron": 3, "coal": 1, "furnace": 1},
        [{"name": "crafting_table", "position": table["position"]}],
        position={"x": 118.5, "y": 123, "z": -49.5},
        m4_local_place_candidates=snapshot,
    )
    assert agent._m4_bm013_bm014_furnace_place_reference(
        failed_observation,
    ) == {}
    blocked = agent._m4_bm013_bm014_toolchain_machine_step_plan(
        failed_observation,
        "Smelt 3 iron ingots from 3 raw iron using coal",
    )
    assert blocked["status"] == "blocked"
    assert blocked["actions"] == []
    assert blocked["reason_code"] == "furnace_place_local_snapshot_unavailable"
    assert blocked["bounded_block"]["fallback_suppressed"] is True

    bm012 = _machine_agent("BM-012")
    assert bm012._m4_bm013_bm014_local_place_candidate_snapshot(
        base_state,
        passed_report,
    ) == {}
    assert bm012._m4_bm012_place_reference(
        _observation(
            {"crafting_table": 1},
            [{
                "name": "grass_block",
                "position": {"x": 1, "y": 63, "z": 0},
                "distance": 1.5,
            }],
        ),
    ) == {"x": 1, "y": 63, "z": 0}
    bm012_furnace_control = ActionVerifier().verify(
        {
            "type": "place",
            "parameters": {
                "item": "furnace",
                "x": 1,
                "y": 63,
                "z": 0,
            },
        },
        _observation({"furnace": 1}, []),
        protocol="m4-fixed-v1",
        task_id="BM-012",
    )
    assert bm012_furnace_control.status == "accept"
    assert "target:not_observed_occupied" in bm012_furnace_control.evidence


def test_m4_furnace_place_verifier_rejects_missing_forged_stale_or_unbound_snapshot():
    verifier = ActionVerifier()
    action = {
        "type": "place",
        "parameters": {"item": "furnace", "x": 1, "y": 63, "z": 0},
    }
    reference = _machine_block(
        "crafting_table",
        {"x": 1, "y": 63, "z": 0},
        solid=True,
    )
    target = _machine_block(
        "air",
        {"x": 1, "y": 64, "z": 0},
        solid=False,
    )
    valid_snapshot = _local_place_snapshot(reference, target)
    base = _observation(
        {"furnace": 1},
        [],
        observed_at_ms=1785125823000,
        m4_local_place_candidates=valid_snapshot,
    )
    accepted = verifier.verify(
        action,
        base,
        protocol="m4-fixed-v1",
        task_id="BM-014",
    )
    assert accepted.status == "accept"
    assert (
        "policy:m4-bm013-bm014-furnace-place-local-snapshot-v1"
        in accepted.evidence
    )

    invalid_states = []
    missing = copy.deepcopy(base)
    missing.pop("m4_local_place_candidates")
    invalid_states.append(missing)

    forged = copy.deepcopy(base)
    forged["m4_local_place_candidates"]["candidate_count"] = 2
    invalid_states.append(forged)

    stale = copy.deepcopy(base)
    stale["observed_at_ms"] += (
        ActionVerifier.M4_FURNACE_PLACE_MAX_SNAPSHOT_AGE_MS + 1
    )
    invalid_states.append(stale)

    unbound = copy.deepcopy(base)
    unbound["position"] = {"x": 1.0, "y": 64.0, "z": 0.0}
    invalid_states.append(unbound)

    wrong_pair = copy.deepcopy(base)
    wrong_pair["m4_local_place_candidates"]["candidates"][0][
        "reference_block"
    ]["position"] = {"x": 2, "y": 63, "z": 0}
    wrong_pair["m4_local_place_candidates"]["candidates"][0][
        "target_block"
    ]["position"] = {"x": 2, "y": 64, "z": 0}
    invalid_states.append(wrong_pair)

    for state in invalid_states:
        decision = verifier.verify(
            action,
            state,
            protocol="m4-fixed-v1",
            task_id="BM-014",
        )
        assert decision.status == "reject"
        assert decision.policy_id == (
            ActionVerifier.M4_FURNACE_PLACE_LOCAL_SNAPSHOT_POLICY_ID
        )
        assert "target:not_observed_occupied" not in decision.evidence

    wrong_pair_decision = verifier.verify(
        action,
        wrong_pair,
        protocol="m4-fixed-v1",
        task_id="BM-014",
    )
    assert wrong_pair_decision.missing == [
        "m4_local_place_candidates.exact_pair",
    ]
    assert wrong_pair_decision.required["reference_position"] == {
        "x": 1,
        "y": 63,
        "z": 0,
    }
    assert wrong_pair_decision.required["target_position"] == {
        "x": 1,
        "y": 64,
        "z": 0,
    }

    fractional_action = copy.deepcopy(action)
    fractional_action["parameters"]["x"] = 1.5
    fractional = verifier.verify(
        fractional_action,
        base,
        protocol="m4-fixed-v1",
        task_id="BM-014",
    )
    assert fractional.status == "reject"
    assert "exact integral reference coordinates" in fractional.reason


def test_furnace_place_collision_unions_snapshot_and_current_same_cell_positions():
    agent = _machine_agent("BM-014")
    verifier = ActionVerifier()
    reference = _machine_block(
        "crafting_table",
        {"x": 1, "y": 63, "z": 0},
        solid=True,
    )
    target = _machine_block(
        "air",
        {"x": 1, "y": 64, "z": 0},
        solid=False,
    )
    observation = _observation(
        {"raw_iron": 3, "coal": 1, "furnace": 1},
        [],
        position={"x": 0.95, "y": 64.0, "z": 0.5},
        m4_local_place_candidates=_local_place_snapshot(reference, target),
    )
    action = {
        "type": "place",
        "parameters": {"item": "furnace", **reference["position"]},
    }

    assert agent._m4_bm013_bm014_furnace_place_reference(observation) == {}
    decision = verifier.verify(
        action,
        observation,
        protocol="m4-fixed-v1",
        task_id="BM-014",
    )
    assert decision.status == "reject"
    assert "intersects the player's collision cells" in decision.reason
    assert decision.required["player_position"] == {
        "x": 0.5,
        "y": 64.0,
        "z": 0.5,
    }
    assert decision.required["current_player_position"] == observation["position"]
    snapshot_cells = {
        (cell["x"], cell["y"], cell["z"])
        for cell in ActionVerifier._m4_player_collision_evidence(
            decision.required["player_position"],
        )["cells"]
    }
    current_cells = {
        (cell["x"], cell["y"], cell["z"])
        for cell in ActionVerifier._m4_player_collision_evidence(
            decision.required["current_player_position"],
        )["cells"]
    }
    required_cells = {
        (cell["x"], cell["y"], cell["z"])
        for cell in decision.required["player_collision_cells"]
    }
    target_key = (target["position"]["x"], target["position"]["y"], target["position"]["z"])
    assert required_cells == snapshot_cells | current_cells
    assert len(required_cells) == len(decision.required["player_collision_cells"])
    assert target_key not in snapshot_cells
    assert target_key in current_cells


def test_furnace_snapshot_selector_rejects_bad_envelope_and_uses_snapshot_position():
    agent = _machine_agent("BM-014")
    reference = _machine_block(
        "crafting_table",
        {"x": 1, "y": 63, "z": 0},
        solid=True,
    )
    target = _machine_block(
        "air",
        {"x": 1, "y": 64, "z": 0},
        solid=False,
    )
    snapshot = _local_place_snapshot(reference, target)
    observation = _observation(
        {"raw_iron": 3, "coal": 1, "furnace": 1},
        [],
        m4_local_place_candidates=snapshot,
    )
    selected = agent._m4_bm013_bm014_furnace_place_reference(observation)
    assert selected["reference_position"] == reference["position"]
    assert selected["snapshot_player_position"] == snapshot["player_position"]

    for field, value in (
        ("snapshot_position_count", 35),
        ("candidate_limit", 26),
        ("candidate_count", 2),
        ("observed_at_ms", float("nan")),
    ):
        invalid = copy.deepcopy(observation)
        invalid["m4_local_place_candidates"][field] = value
        assert agent._m4_bm013_bm014_furnace_place_reference(invalid) == {}

    mismatched_position = copy.deepcopy(observation)
    mismatched_position["position"] = {"x": 1, "y": 64, "z": 0}
    assert agent._m4_bm013_bm014_furnace_place_reference(
        mismatched_position,
    ) == {}


def test_exact_smelt_without_valid_local_candidate_blocks_full_think_fallbacks():
    agent = _machine_agent("BM-014")
    calls = []
    visual_calls = []
    agent.visual_action_advisor = SimpleNamespace(
        suggest=lambda *args, **kwargs: (
            visual_calls.append("suggest")
            or [{
                "kind": "resource_furnace",
                "reason": "forged visual furnace suggestion",
                "action": {
                    "type": "place",
                    "parameters": {
                        "item": "furnace",
                        "x": 1,
                        "y": 63,
                        "z": 0,
                    },
                },
            }]
        ),
    )
    agent._learned_skill_plan = lambda *args, **kwargs: calls.append("learned")
    agent._m4_bm012_toolchain_machine_step_plan = (
        lambda *args, **kwargs: calls.append("bm012")
    )
    agent._think_llm = lambda *args, **kwargs: calls.append("llm")
    agent._think_rule = lambda *args, **kwargs: calls.append("rule")
    agent._apply_visual_action_grounding = (
        lambda *args, **kwargs: visual_calls.append("grounding")
    )
    agent._use_llm = True
    agent.current_goal = "Smelt 3 iron ingots from 3 raw iron using coal"

    plan = agent._think(
        _observation(
            {"raw_iron": 3, "coal": 1, "furnace": 1},
            [],
        ),
    )

    assert plan["status"] == "blocked"
    assert plan["actions"] == []
    assert plan["reason_code"] == "furnace_place_local_snapshot_unavailable"
    assert plan["bounded_block"]["fallback_suppressed"] is True
    assert plan["bounded_block"]["suppressed_paths"] == [
        "learned_skill",
        "bm012_machine_step",
        "llm_plan",
        "rule_plan",
        "visual_action_grounding",
    ]
    assert calls == []
    assert visual_calls == []


def test_probe53_owned_table_place_uses_independent_complete_snapshot_pair():
    agent = _machine_agent("BM-014")
    reference_position = {"x": 118, "y": 122, "z": -51}
    target_position = {"x": 118, "y": 123, "z": -51}
    reference = _machine_block(
        "coal_ore",
        reference_position,
        solid=True,
    )
    target = _machine_block(
        "air",
        target_position,
        solid=False,
    )
    machine_state = _complete_local_machine_state(
        reference,
        target,
        _machine_block(
            "stone",
            {"x": 119, "y": 122, "z": -49},
            solid=True,
        ),
        _machine_block(
            "clay",
            {"x": 119, "y": 123, "z": -49},
            solid=True,
        ),
    )
    report = {"checks": [_machine_snapshot_check()]}

    table_snapshot = (
        agent._m4_bm013_bm014_crafting_table_place_candidate_snapshot(
            machine_state,
            report,
        )
    )
    furnace_snapshot = agent._m4_bm013_bm014_local_place_candidate_snapshot(
        machine_state,
        report,
    )
    assert table_snapshot["policy_id"] == (
        "m4-bm013-bm014-crafting-table-place-local-snapshot-v1"
    )
    assert table_snapshot["candidate_count"] == 1
    assert table_snapshot["candidates"][0]["reference_block"]["position"] == (
        reference_position
    )
    assert table_snapshot["candidates"][0]["target_block"]["position"] == (
        target_position
    )
    assert table_snapshot["candidates"][0]["reference_block"][
        "grounding_policy_id"
    ] == table_snapshot["policy_id"]
    assert furnace_snapshot["policy_id"] == (
        "m4-bm013-bm014-furnace-place-local-snapshot-v1"
    )
    assert table_snapshot != furnace_snapshot

    observation = _observation(
        {"crafting_table": 1, "cobblestone": 8},
        [{"name": "coal_ore", "position": reference_position, "distance": 1.414}],
        position={"x": 118.5, "y": 123, "z": -49.5},
        m4_crafting_table_place_candidates=table_snapshot,
    )
    plan = agent._m4_bm013_bm014_toolchain_machine_step_plan(
        observation,
        "Craft a furnace for iron smelting",
    )
    action = plan["actions"][0]
    assert action == {
        "type": "place",
        "parameters": {
            "item": "crafting_table",
            **reference_position,
        },
    }
    assert plan["machine_step_plan"]["reason"] == (
        "place_owned_crafting_table_at_machine_verified_local_air_target"
    )
    assert plan["machine_step_plan"][
        "crafting_table_place_local_snapshot_policy_id"
    ] == table_snapshot["policy_id"]
    assert plan["machine_step_plan"][
        "furnace_place_local_snapshot_policy_id"
    ] is None
    assert plan["machine_step_plan"]["target"]["target_position"] == target_position

    decision = ActionVerifier().verify(
        action,
        observation,
        protocol="m4-fixed-v1",
        task_id="BM-014",
    )
    assert decision.status == "accept"
    assert f"policy:{table_snapshot['policy_id']}" in decision.evidence
    assert "target:air" in decision.evidence
    assert "target:not_observed_occupied" not in decision.evidence


def test_table_place_verifier_rejects_missing_forged_stale_wrong_or_fractional():
    verifier = ActionVerifier()
    action = {
        "type": "place",
        "parameters": {"item": "crafting_table", "x": 1, "y": 63, "z": 0},
    }
    reference = _machine_block(
        "stone",
        {"x": 1, "y": 63, "z": 0},
        solid=True,
    )
    target = _machine_block(
        "air",
        {"x": 1, "y": 64, "z": 0},
        solid=False,
    )
    valid_snapshot = _crafting_table_local_place_snapshot(reference, target)
    base = _observation(
        {"crafting_table": 1},
        [],
        observed_at_ms=1785125823000,
        m4_crafting_table_place_candidates=valid_snapshot,
    )
    accepted = verifier.verify(
        action,
        base,
        protocol="m4-fixed-v1",
        task_id="BM-014",
    )
    assert accepted.status == "accept"
    assert (
        "policy:m4-bm013-bm014-crafting-table-place-local-snapshot-v1"
        in accepted.evidence
    )
    assert "target:air" in accepted.evidence

    invalid_states = []
    missing = copy.deepcopy(base)
    missing.pop("m4_crafting_table_place_candidates")
    missing["m4_local_place_candidates"] = _local_place_snapshot(
        _machine_block(
            "crafting_table",
            reference["position"],
            solid=True,
        ),
        target,
    )
    invalid_states.append(missing)

    forged = copy.deepcopy(base)
    forged["m4_crafting_table_place_candidates"]["candidate_count"] = 2
    invalid_states.append(forged)

    wrong_policy = copy.deepcopy(base)
    wrong_policy["m4_crafting_table_place_candidates"]["policy_id"] = (
        "m4-bm013-bm014-furnace-place-local-snapshot-v1"
    )
    invalid_states.append(wrong_policy)

    stale = copy.deepcopy(base)
    stale["observed_at_ms"] += (
        ActionVerifier.M4_CRAFTING_TABLE_PLACE_MAX_SNAPSHOT_AGE_MS + 1
    )
    invalid_states.append(stale)

    unbound = copy.deepcopy(base)
    unbound["position"] = {"x": 1.0, "y": 64.0, "z": 0.0}
    invalid_states.append(unbound)

    zero_candidates = copy.deepcopy(base)
    zero_candidates["m4_crafting_table_place_candidates"]["candidates"] = []
    zero_candidates["m4_crafting_table_place_candidates"]["candidate_count"] = 0
    invalid_states.append(zero_candidates)

    wrong_pair = copy.deepcopy(base)
    wrong_pair["m4_crafting_table_place_candidates"]["candidates"][0][
        "reference_block"
    ]["position"] = {"x": 2, "y": 63, "z": 0}
    wrong_pair["m4_crafting_table_place_candidates"]["candidates"][0][
        "target_block"
    ]["position"] = {"x": 2, "y": 64, "z": 0}
    invalid_states.append(wrong_pair)

    visible_table_bypass = copy.deepcopy(missing)
    visible_table_bypass["nearby_blocks"] = [_table()]
    invalid_states.append(visible_table_bypass)

    for state in invalid_states:
        decision = verifier.verify(
            action,
            state,
            protocol="m4-fixed-v1",
            task_id="BM-014",
        )
        assert decision.status == "reject"
        assert decision.policy_id == (
            ActionVerifier.M4_CRAFTING_TABLE_PLACE_LOCAL_SNAPSHOT_POLICY_ID
        )
        assert "target:not_observed_occupied" not in decision.evidence

    wrong_pair_decision = verifier.verify(
        action,
        wrong_pair,
        protocol="m4-fixed-v1",
        task_id="BM-014",
    )
    assert wrong_pair_decision.missing == [
        "m4_crafting_table_place_candidates.exact_pair",
    ]
    assert wrong_pair_decision.required["reference_position"] == {
        "x": 1,
        "y": 63,
        "z": 0,
    }
    assert wrong_pair_decision.required["target_position"] == {
        "x": 1,
        "y": 64,
        "z": 0,
    }

    fractional_action = copy.deepcopy(action)
    fractional_action["parameters"]["x"] = 1.5
    fractional = verifier.verify(
        fractional_action,
        base,
        protocol="m4-fixed-v1",
        task_id="BM-014",
    )
    assert fractional.status == "reject"
    assert fractional.policy_id == (
        ActionVerifier.M4_CRAFTING_TABLE_PLACE_LOCAL_SNAPSHOT_POLICY_ID
    )
    assert "exact integral reference coordinates" in fractional.reason

    furnace_cannot_borrow_table_envelope = verifier.verify(
        {
            "type": "place",
            "parameters": {"item": "furnace", "x": 1, "y": 63, "z": 0},
        },
        _observation(
            {"furnace": 1},
            [],
            observed_at_ms=1785125823000,
            m4_crafting_table_place_candidates=valid_snapshot,
        ),
        protocol="m4-fixed-v1",
        task_id="BM-014",
    )
    assert furnace_cannot_borrow_table_envelope.status == "reject"
    assert furnace_cannot_borrow_table_envelope.policy_id == (
        ActionVerifier.M4_FURNACE_PLACE_LOCAL_SNAPSHOT_POLICY_ID
    )


def test_table_selector_rejects_current_occupancy_player_collision_and_feedback():
    agent = _machine_agent("BM-014")
    verifier = ActionVerifier()
    reference = _machine_block(
        "stone",
        {"x": 1, "y": 63, "z": 0},
        solid=True,
    )
    target = _machine_block(
        "air",
        {"x": 1, "y": 64, "z": 0},
        solid=False,
    )
    snapshot = _crafting_table_local_place_snapshot(reference, target)
    action = {
        "type": "place",
        "parameters": {
            "item": "crafting_table",
            **reference["position"],
        },
    }

    occupied = _observation(
        {"crafting_table": 1, "cobblestone": 8},
        [{"name": "stone", "position": target["position"]}],
        m4_crafting_table_place_candidates=snapshot,
    )
    assert (
        agent._m4_bm013_bm014_crafting_table_place_reference(occupied)
        == {}
    )
    occupied_decision = verifier.verify(
        action,
        occupied,
        protocol="m4-fixed-v1",
        task_id="BM-014",
    )
    assert occupied_decision.status == "reject"
    assert "observed_target:stone" in occupied_decision.evidence

    collision = _observation(
        {"crafting_table": 1, "cobblestone": 8},
        [],
        position={"x": 0.95, "y": 64.0, "z": 0.5},
        m4_crafting_table_place_candidates=snapshot,
    )
    assert (
        agent._m4_bm013_bm014_crafting_table_place_reference(collision)
        == {}
    )
    collision_decision = verifier.verify(
        action,
        collision,
        protocol="m4-fixed-v1",
        task_id="BM-014",
    )
    assert collision_decision.status == "reject"
    assert "intersects the player's collision cells" in collision_decision.reason
    assert collision_decision.required["current_player_position"] == (
        collision["position"]
    )

    failed_event = {
        "type": "action",
        "data": {
            "action": action,
            "result": {
                "success": False,
                "error": "placement target is occupied by stone",
                "placed_position": target["position"],
                "target_block_before": {
                    "name": "stone",
                    "position": target["position"],
                },
            },
        },
    }
    alternate_reference = _machine_block(
        "stone",
        {"x": -2, "y": 63, "z": 0},
        solid=True,
    )
    alternate_target = _machine_block(
        "air",
        {"x": -2, "y": 64, "z": 0},
        solid=False,
    )
    alternate_snapshot = _crafting_table_local_place_snapshot(
        alternate_reference,
        alternate_target,
    )
    retry_snapshot = copy.deepcopy(snapshot)
    retry_snapshot["candidates"].append(
        copy.deepcopy(alternate_snapshot["candidates"][0]),
    )
    retry_snapshot["candidate_count"] = 2
    agent.session_logger.events = [failed_event]
    retry_observation = _observation(
        {"crafting_table": 1, "cobblestone": 8},
        [],
        m4_crafting_table_place_candidates=retry_snapshot,
    )
    retry_selection = (
        agent._m4_bm013_bm014_crafting_table_place_reference(
            retry_observation,
        )
    )
    assert retry_selection["reference_position"] == (
        alternate_reference["position"]
    )
    assert retry_selection["target_position"] == alternate_target["position"]

    furnace_feedback_agent = _machine_agent("BM-014")
    furnace_feedback = copy.deepcopy(failed_event)
    furnace_feedback["data"]["action"]["parameters"]["item"] = "furnace"
    furnace_feedback_agent.session_logger.events = [furnace_feedback]
    unaffected_selection = (
        furnace_feedback_agent._m4_bm013_bm014_crafting_table_place_reference(
            _observation(
                {"crafting_table": 1, "cobblestone": 8},
                [],
                m4_crafting_table_place_candidates=snapshot,
            )
        )
    )
    assert unaffected_selection["reference_position"] == reference["position"]

    feedback = _observation(
        {"crafting_table": 1, "cobblestone": 8},
        [],
        m4_crafting_table_place_candidates=snapshot,
    )
    assert (
        agent._m4_bm013_bm014_crafting_table_place_reference(feedback)
        == {}
    )
    blocked = agent._m4_bm013_bm014_toolchain_machine_step_plan(
        feedback,
        "Craft a furnace for iron smelting",
    )
    assert blocked["status"] == "blocked"
    assert blocked["actions"] == []
    assert blocked["reason_code"] == (
        "crafting_table_place_local_snapshot_unavailable"
    )
    assert blocked["bounded_block"]["policy_id"] == (
        "m4-bm013-bm014-crafting-table-place-local-snapshot-v1"
    )
    assert blocked["bounded_block"]["fallback_suppressed"] is True


def test_owned_table_without_valid_snapshot_blocks_all_think_fallbacks():
    agent = _machine_agent("BM-014")
    calls = []
    visual_calls = []
    agent.visual_action_advisor = SimpleNamespace(
        suggest=lambda *args, **kwargs: (
            visual_calls.append("suggest")
            or [{
                "kind": "resource_crafting_table",
                "reason": "forged visual table suggestion",
                "action": {
                    "type": "place",
                    "parameters": {
                        "item": "crafting_table",
                        "x": 1,
                        "y": 63,
                        "z": 0,
                    },
                },
            }]
        ),
    )
    agent._learned_skill_plan = lambda *args, **kwargs: calls.append("learned")
    agent._m4_bm012_toolchain_machine_step_plan = (
        lambda *args, **kwargs: calls.append("bm012")
    )
    agent._think_llm = lambda *args, **kwargs: calls.append("llm")
    agent._think_rule = lambda *args, **kwargs: calls.append("rule")
    agent._apply_visual_action_grounding = (
        lambda *args, **kwargs: visual_calls.append("grounding")
    )
    agent._use_llm = True
    agent.current_goal = "Craft a furnace for iron smelting"

    plan = agent._think(
        _observation(
            {"crafting_table": 1, "cobblestone": 8},
            [],
        ),
    )

    assert plan["status"] == "blocked"
    assert plan["actions"] == []
    assert plan["reason_code"] == (
        "crafting_table_place_local_snapshot_unavailable"
    )
    assert plan["bounded_block"]["suppressed_paths"] == [
        "learned_skill",
        "bm012_machine_step",
        "llm_plan",
        "rule_plan",
        "visual_action_grounding",
    ]
    assert calls == []
    assert visual_calls == []


def test_bm012_table_and_furnace_place_controls_remain_generic():
    agent = _machine_agent("BM-012")
    observation = _observation(
        {"crafting_table": 1},
        [{
            "name": "grass_block",
            "position": {"x": 1, "y": 63, "z": 0},
            "distance": 1.5,
        }],
    )
    action, reason, target = agent._m4_bm012_crafting_table_access_action(
        observation,
        observation["inventory"],
    )
    assert action == {
        "type": "place",
        "parameters": {
            "item": "crafting_table",
            "x": 1,
            "y": 63,
            "z": 0,
        },
    }
    assert reason == "place_owned_crafting_table_at_verified_reference"
    assert target == {
        "reference_position": {"x": 1, "y": 63, "z": 0},
    }

    verifier = ActionVerifier()
    for item in ("crafting_table", "furnace"):
        generic = verifier.verify(
            {
                "type": "place",
                "parameters": {
                    "item": item,
                    "x": 1,
                    "y": 63,
                    "z": 0,
                },
            },
            _observation({item: 1}, []),
            protocol="m4-fixed-v1",
            task_id="BM-012",
        )
        assert generic.status == "accept"
        assert "target:not_observed_occupied" in generic.evidence
        assert all(
            "bm013-bm014" not in evidence
            for evidence in generic.evidence
        )


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
