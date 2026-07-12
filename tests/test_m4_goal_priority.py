"""Fixed-state G1 tests for M4 autonomous survival-goal priority."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from singularity.core.goal_generator import GoalGenerator
from singularity.core.agent import Agent
from singularity.core.config import Config
from singularity.core.task_system import TaskStatus, TaskSystem
from singularity.evaluation.m4_shelter import (
    M4_SHELTER_CONTRACT_SHA256,
    M4_SHELTER_REQUIRED_CHECKS,
    M4_SHELTER_VERIFIER_ID,
)


def _observation(**overrides):
    observation = {
        "time_of_day": 3000,
        "health": 20,
        "hunger": 20,
        "inventory": {},
        "nearby_entities": [],
    }
    observation.update(overrides)
    return observation


def _verified_shelter():
    return {
        "type": "m4_shelter_state_verification",
        "verifier_id": M4_SHELTER_VERIFIER_ID,
        "contract_sha256": M4_SHELTER_CONTRACT_SHA256,
        "passed": True,
        "source": "machine_state",
        "safe_state": True,
        "checks": [{"name": "machine_snapshot", "passed": True}] + [
            {"name": name, "passed": True}
            for name in M4_SHELTER_REQUIRED_CHECKS
        ],
        "issues": [],
        "episode_block_delta": {"required_position_count": 9, "matched_position_count": 9},
        "coordinate_evidence": {
            "entrance": {
                "state": "fully_sealed",
                "sealed_boundary_columns": [{}, {}, {}, {}],
            }
        },
    }


def _decision(generator: GoalGenerator, observation: dict, task_id: str = ""):
    goal = generator.next_goal(observation, task_id=task_id)
    decision = dict(generator.last_decision)
    assert decision["goal"] == goal
    assert decision["selection_source"] == "goal_generator"
    assert decision["selection_reason"]
    assert 1 <= decision["priority"] <= 6
    return goal, decision


def test_m4_goal_priority_fixed_state_matrix():
    generator = GoalGenerator()
    cases = [
        (
            "day_empty_inventory",
            _observation(),
            6,
            "tool_resource_progression",
            "Gather 6 oak logs",
        ),
        (
            "dusk_without_shelter",
            _observation(time_of_day=11000, inventory={"crafting_table": 1}),
            4,
            "shelter_preparation",
            "Build verified shelter",
        ),
        (
            "critical_health",
            _observation(health=4, hunger=4, inventory={"bread": 1}),
            2,
            "critical_health",
            "critical health",
        ),
        (
            "low_hunger_with_food",
            _observation(hunger=6, inventory={"cooked_beef": 1}),
            3,
            "hunger_food",
            "restore hunger",
        ),
        (
            "low_hunger_without_food",
            _observation(hunger=6),
            3,
            "hunger_food",
            "Find food",
        ),
        (
            "hostile_nearby",
            _observation(
                time_of_day=11000,
                health=3,
                hunger=3,
                inventory={"bread": 1},
                nearby_entities=[{"type": "zombie", "hostile": True, "distance": 5}],
            ),
            1,
            "immediate_threat",
            "Flee",
        ),
        (
            "night_with_verified_shelter",
            _observation(
                time_of_day=15000,
                inventory={"furnace": 1, "raw_iron": 4},
                shelter_verification=_verified_shelter(),
            ),
            5,
            "night_safety_maintenance",
            "Remain in verified shelter",
        ),
    ]

    for case_id, observation, priority, priority_class, goal_fragment in cases:
        goal, decision = _decision(generator, observation)
        assert decision["priority"] == priority, (case_id, decision)
        assert decision["priority_class"] == priority_class, (case_id, decision)
        assert goal_fragment.lower() in goal.lower(), (case_id, goal)

    print("PASS: G1 fixed-state matrix follows the six-level survival priority")


def test_m4_goal_priority_precedence_and_machine_shelter_requirement():
    generator = GoalGenerator()

    armed_goal, armed = _decision(generator, _observation(
        health=2,
        hunger=2,
        inventory={"iron_sword": 1, "bread": 1},
        nearby_entities=[{"type": "skeleton", "hostile": True, "distance": 8}],
    ))
    assert armed["priority"] == 1
    assert "Attack" in armed_goal

    unverified_goal, unverified = _decision(generator, _observation(
        time_of_day=15000,
        flags=["in_shelter", "shelter_built"],
        structures={"shelter": {"complete": True}},
        inventory={"crafting_table": 1, "furnace": 1, "raw_iron": 4},
    ))
    assert unverified["priority"] == 4
    assert "emergency verified shelter" in unverified_goal
    assert unverified["shelter_verified"] is False

    dawn_goal, dawn = _decision(generator, _observation(time_of_day=23000))
    assert dawn["priority"] == 6
    assert "dawn" not in dawn_goal.lower()
    print("PASS: threats dominate and shelter claims require machine-state verification")


def test_m4_hunger_priority_survives_ready_task_selection():
    generator = GoalGenerator()
    observation = _observation(hunger=5)
    fallback = generator.next_goal(observation)
    agent = object.__new__(Agent)
    agent.config = Config()
    agent.task_system = TaskSystem()
    agent.task_system.create_task(
        "Mine iron for later tool progression",
        status=TaskStatus.ACCEPTED,
        priority=0,
    )
    agent._last_autonomous_goal_decision = dict(generator.last_decision)

    selected = agent._select_autonomous_goal(observation, fallback)

    assert selected == fallback
    assert agent._last_autonomous_goal_decision["priority"] == 3
    assert agent._last_autonomous_goal_decision["priority_class"] == "hunger_food"
    print("PASS: ready curriculum tasks cannot override a low-hunger survival goal")


def test_bm012_goal_progression_is_autonomous_and_survival_preemptible():
    generator = GoalGenerator()
    table = [{"name": "crafting_table", "position": {"x": 1, "y": 64, "z": 1}}]
    cases = [
        (_observation(time_of_day=1000), "Gather 6 oak logs", "bm012_wood_reserve_below_target"),
        (
            _observation(time_of_day=1000, inventory={"oak_log": 6}),
            "crafting table",
            "bm012_crafting_table_missing",
        ),
        (
            _observation(time_of_day=1000, inventory={"oak_log": 6}, nearby_blocks=table),
            "wooden pickaxe",
            "bm012_wooden_pickaxe_missing",
        ),
        (
            _observation(
                time_of_day=1000,
                inventory={"oak_log": 6, "wooden_pickaxe": 1},
                nearby_blocks=table,
            ),
            "3 cobblestone",
            "bm012_cobblestone_below_stone_pickaxe_requirement",
        ),
        (
            _observation(
                time_of_day=1000,
                inventory={"oak_log": 6, "wooden_pickaxe": 1, "cobblestone": 3},
                nearby_blocks=table,
            ),
            "stone pickaxe",
            "bm012_stone_pickaxe_ready_to_craft",
        ),
        (
            _observation(
                time_of_day=1000,
                inventory={"oak_log": 6, "wooden_pickaxe": 1, "stone_pickaxe": 1},
                nearby_blocks=table,
            ),
            "Collect 8 raw iron",
            "bm012_stone_pickaxe_ready_for_iron",
        ),
        (
            _observation(time_of_day=1000, inventory={"raw_iron": 8}),
            "Confirm collection",
            "bm012_inventory_target_reached",
        ),
    ]
    for observation, expected_goal, expected_reason in cases:
        goal, decision = _decision(generator, observation, task_id="BM-012")
        assert expected_goal.lower() in goal.lower(), (goal, observation)
        assert decision["selection_reason"] == expected_reason
        assert decision["selection_source"] == "goal_generator"
        assert decision["priority_class"] == "tool_resource_progression"

    survival_goal, survival = _decision(
        generator,
        _observation(time_of_day=11000, inventory={"stone_pickaxe": 1}),
        task_id="BM-012",
    )
    assert "shelter" in survival_goal.lower()
    assert survival["priority_class"] == "shelter_preparation"
    print("PASS: BM-012 intermediate goals are autonomous while survival priorities still preempt")


if __name__ == "__main__":
    test_m4_goal_priority_fixed_state_matrix()
    test_m4_goal_priority_precedence_and_machine_shelter_requirement()
    test_m4_hunger_priority_survives_ready_task_selection()
    test_bm012_goal_progression_is_autonomous_and_survival_preemptible()
    print("\nM4 G1 goal-priority tests PASSED")
