"""Unit tests for automatic open-ended curriculum."""
import os
import sys
import tempfile

sys.path.insert(0, "src")

from singularity.core.agent import Agent
from singularity.core.coach import CoachPolicy
from singularity.core.config import Config
from singularity.core.curriculum import CurriculumGoalCandidate, CurriculumManager
from singularity.core.goal_generator import GoalGenerator
from singularity.core.memory import MemorySystem
from singularity.core.skill_library import SkillLibrary
from singularity.core.task_system import TaskStatus, TaskSystem


def test_curriculum_keeps_emergency_goal():
    manager = CurriculumManager()
    obs = {
        "health": 4,
        "time_of_day": 5000,
        "inventory": {"oak_log": 8, "bread": 1},
        "nearby_entities": [],
    }

    goal = manager.next_goal(obs, "Eat food to restore health")

    assert goal == "Eat food to restore health"
    print("PASS: Curriculum keeps emergency health goal")


def test_curriculum_promotes_ready_crafting_progression():
    manager = CurriculumManager()
    skills = SkillLibrary(persist=False)
    obs = {
        "health": 20,
        "time_of_day": 3000,
        "inventory": {"oak_log": 4},
        "nearby_entities": [],
        "nearby_blocks": [],
    }

    goal = manager.next_goal(obs, "Explore surroundings and gather resources", skill_library=skills)

    assert goal == "Craft crafting table"
    assert manager.last_decision["selected"] == "Craft crafting table"
    print("PASS: Curriculum promotes ready crafting progression")


def test_curriculum_requires_world_ready_crafting_station_before_pickaxe():
    manager = CurriculumManager()
    observation = {
        "health": 20,
        "time_of_day": 1806,
        "inventory": {"oak_log": 4, "crafting_table": 1, "oak_planks": 4},
        "nearby_entities": [],
        "nearby_blocks": [{"name": "grass_block"}, {"name": "oak_log"}],
    }

    goals = manager.propose_goals(
        observation,
        "Gather 6 oak logs for iron-tool progression",
        skill_library=SkillLibrary(persist=False),
    )

    assert goals[0].title == "Place crafting table for tool progression"
    assert goals[0].reasons[0] == "bm012_crafting_table_unplaced"
    assert all(candidate.title != "Craft wooden pickaxe" for candidate in goals)

    observation["nearby_blocks"].append({"name": "crafting_table"})
    ready = manager.propose_goals(
        observation,
        "Gather 6 oak logs for iron-tool progression",
        skill_library=SkillLibrary(persist=False),
    )
    assert ready[0].title == "Craft wooden pickaxe"
    print("PASS: Curriculum replays Probe 2 with machine-grounded crafting-station readiness")


def test_curriculum_uses_visible_novel_resource_when_stable():
    manager = CurriculumManager()
    memory = MemorySystem(memory_dir=tempfile.mkdtemp(), persist=False)
    obs = {
        "health": 20,
        "time_of_day": 4000,
        "inventory": {"crafting_table": 1, "wooden_pickaxe": 1, "oak_log": 4},
        "nearby_entities": [],
        "nearby_blocks": [{"name": "pumpkin"}],
    }

    goals = manager.propose_goals(
        obs,
        "Explore surroundings and gather resources",
        memory_system=memory,
        skill_library=SkillLibrary(persist=False),
    )
    titles = [candidate.title for candidate in goals]

    assert any("pumpkin" in title for title in titles)
    assert goals[0].score >= goals[-1].score
    print("PASS: Curriculum proposes visible novel resource exploration")


def test_curriculum_uses_exploration_feedback_for_goal_ranking():
    manager = CurriculumManager()
    memory = MemorySystem(memory_dir=tempfile.mkdtemp(), persist=False)
    manager.record_exploration_feedback({
        "discovered_resources": ["pumpkin"],
        "action_failure_categories": {"perception": 2},
        "low_movement_log_count": 1,
        "hostile_encounter_count": 1,
        "path_distance": 5.5,
    })
    obs = {
        "health": 20,
        "time_of_day": 4000,
        "inventory": {"crafting_table": 1, "wooden_pickaxe": 1, "oak_log": 4},
        "nearby_entities": [],
        "nearby_blocks": [{"name": "pumpkin"}],
    }

    goals = manager.propose_goals(
        obs,
        "Explore surroundings and gather resources",
        memory_system=memory,
        skill_library=SkillLibrary(persist=False),
    )
    titles = [candidate.title for candidate in goals]
    scout = next(candidate for candidate in goals if candidate.title == "Scout nearby area and record landmarks")
    diagnostic = next(candidate for candidate in goals if candidate.category == "exploration_diagnostic")

    assert not any("Inspect nearby pumpkin" in title for title in titles)
    assert "coverage_gap_feedback" in scout.reasons
    assert diagnostic.title == "Scan nearby area and verify landmarks before deeper exploration"
    assert "perception_failure_feedback" in diagnostic.reasons
    summary = manager.summary()
    assert summary["exploration_feedback"]["discovered_resources"] == ["pumpkin"]
    assert summary["exploration_feedback"]["action_failure_categories"]["perception"] == 2
    print("PASS: Curriculum uses exploration feedback for goal ranking")


def test_curriculum_scores_structured_frontiers_with_transfer_memory():
    manager = CurriculumManager()
    memory = MemorySystem(memory_dir=tempfile.mkdtemp(), persist=False)
    memory.record_experience(
        goal="Explore mapped coal frontier",
        task="Navigate east frontier and mine coal_ore",
        outcome="Reached the frontier safely and collected coal",
        actions=[{"type": "move", "parameters": {"target": "east frontier"}}],
        dimensions={
            "process": "approach visible frontier before mining",
            "interaction": "coal_ore requires close positioning before dig",
        },
        tags=["frontier", "coal_ore", "navigation"],
        success=True,
    )
    memory.record_experience(
        goal="Explore hostile cave frontier",
        task="Navigate west frontier",
        outcome="Retreated after hostile pressure blocked the route",
        correction="bring torches and scout a safer route first",
        tags=["frontier", "hostile", "west"],
        success=False,
    )
    manager.record_world_model_feedback({
        "frontier_count": 2,
        "frontiers": [
            {
                "cell": {"x": 1, "z": 0},
                "center": {"x": 12, "z": 4},
                "direction": "east",
                "nearby_resources": ["coal_ore"],
                "nearby_danger_count": 0,
            },
            {
                "cell": {"x": -1, "z": 0},
                "center": {"x": -12, "z": 2},
                "direction": "west",
                "nearby_resources": ["cave"],
                "nearby_danger_count": 2,
            },
        ],
    })
    obs = {
        "health": 20,
        "time_of_day": 4000,
        "inventory": {"crafting_table": 1, "wooden_pickaxe": 1, "oak_log": 4},
        "nearby_entities": [],
        "nearby_blocks": [],
    }

    goals = manager.propose_goals(
        obs,
        "Explore surroundings and gather resources",
        memory_system=memory,
        skill_library=SkillLibrary(persist=False),
    )
    frontier_goals = [candidate for candidate in goals if candidate.category == "world_model_frontier"]
    east = next(candidate for candidate in frontier_goals if "east frontier" in candidate.title)
    west = next(candidate for candidate in frontier_goals if "west frontier" in candidate.title)

    assert east.score > west.score
    assert "structured_frontier_feedback" in east.reasons
    assert "frontier_transfer_success" in east.reasons
    assert "frontier_resource_opportunity" in east.reasons
    assert "frontier_failure_memory_penalty" in west.reasons
    assert "frontier_danger_penalty" in west.reasons
    assert east.target_items == ["coal_ore"]
    print("PASS: Curriculum scores structured frontiers with transfer memory")


def test_curriculum_penalizes_repeated_failures():
    manager = CurriculumManager()
    obs = {
        "health": 20,
        "time_of_day": 3000,
        "inventory": {"oak_log": 4},
        "nearby_entities": [],
    }
    manager.record_goal_outcome("Craft crafting table", False, 10)
    manager.record_goal_outcome("Craft crafting table", False, 12)

    candidates = manager.propose_goals(obs, "Explore surroundings and gather resources")
    craft = next(candidate for candidate in candidates if candidate.title == "Craft crafting table")

    assert "recent_failure_penalty" in craft.reasons
    assert craft.score < 48.0
    print("PASS: Curriculum penalizes repeated failed goals")


def test_agent_autonomous_selector_uses_curriculum_when_no_ready_task():
    tmpdir = tempfile.mkdtemp()
    agent = object.__new__(Agent)
    agent.config = Config(memory_dir=os.path.join(tmpdir, "memory"), skill_dir=os.path.join(tmpdir, "skills"))
    agent.task_system = TaskSystem()
    agent.curriculum = CurriculumManager()
    agent.memory = MemorySystem(agent.config.memory_dir, persist=False)
    agent.skill_library = SkillLibrary(agent.config.skill_dir, persist=False)

    goal = agent._select_autonomous_goal(
        {"health": 20, "time_of_day": 3000, "inventory": {"oak_log": 4}, "nearby_entities": []},
        "Explore surroundings and gather resources",
    )

    assert goal == "Craft crafting table"
    assert agent.memory.l2_episodic[-1]["type"] == "curriculum_goal"
    print("PASS: Agent autonomous selector uses curriculum when no task is ready")


def test_m4_bm012_selector_preserves_exact_three_cobblestone_frontier():
    tmpdir = tempfile.mkdtemp()
    agent = object.__new__(Agent)
    agent.config = Config(
        memory_dir=os.path.join(tmpdir, "memory"),
        skill_dir=os.path.join(tmpdir, "skills"),
        planner_protocol="m4-fixed-v1",
    )
    agent._m4_task_id = "BM-012"
    agent.task_system = TaskSystem()
    agent.curriculum = CurriculumManager()
    agent.memory = MemorySystem(agent.config.memory_dir, persist=False)
    agent.skill_library = SkillLibrary(agent.config.skill_dir, persist=False)

    fallback = "Gather 3 cobblestone with the wooden pickaxe"
    goal = agent._select_autonomous_goal(
        {
            "health": 20,
            "hunger": 20,
            "time_of_day": 5000,
            "inventory": {"wooden_pickaxe": 1},
            "nearby_entities": [],
            "nearby_blocks": [{"name": "stone"}],
        },
        fallback,
    )

    assert goal == fallback
    assert goal != "Mine 12 cobblestone for stone tools and furnace"

    iron_fallback = "Collect 8 raw iron from iron ore with the stone pickaxe"
    iron_goal = agent._select_autonomous_goal(
        {
            "health": 20,
            "hunger": 20,
            "time_of_day": 11000,
            "inventory": {"stone_pickaxe": 1},
            "nearby_entities": [],
            "nearby_blocks": [],
        },
        iron_fallback,
    )
    assert iron_goal == iron_fallback
    assert iron_goal != "Mine iron ore for iron tools"
    print("PASS: strict BM-012 preserves exact cobblestone and iron frontiers")


def test_m4_bm012_goal_generator_closes_wood_to_stone_pickaxe_frontier():
    generator = GoalGenerator()
    base = {
        "health": 20,
        "hunger": 20,
        "time_of_day": 5000,
        "inventory": {
            "oak_log": 3,
            "oak_planks": 3,
            "stick": 2,
            "wooden_pickaxe": 1,
        },
        "nearby_entities": [],
        "nearby_blocks": [{"name": "crafting_table"}, {"name": "stone"}],
    }

    gather = generator.next_goal(base, task_id="BM-012")
    ready = dict(base)
    ready["inventory"] = {**base["inventory"], "cobblestone": 3}
    craft = generator.next_goal(ready, task_id="BM-012")

    assert gather == "Gather 3 cobblestone with the wooden pickaxe"
    assert craft == "Craft a stone pickaxe for mining iron ore"
    print("PASS: strict BM-012 closes wood-to-stone-pickaxe frontier")


def test_m4_bm012_goal_generator_repairs_detached_crafting_station_frontier():
    generator = GoalGenerator()
    detached = {
        "health": 20,
        "hunger": 20,
        "time_of_day": 7000,
        "inventory": {
            "oak_log": 3,
            "oak_planks": 3,
            "stick": 2,
            "wooden_pickaxe": 1,
            "cobblestone": 3,
        },
        "nearby_entities": [],
        "nearby_blocks": [{"name": "stone"}, {"name": "coal_ore"}],
    }
    carrying_table = dict(detached)
    carrying_table["inventory"] = {**detached["inventory"], "crafting_table": 1}

    craft_table = generator.next_goal(detached, task_id="BM-012")
    craft_decision = dict(generator.last_decision)
    place_table = generator.next_goal(carrying_table, task_id="BM-012")
    place_decision = dict(generator.last_decision)

    assert craft_table == "Craft crafting table for stone-pickaxe crafting"
    assert craft_decision["selection_reason"] == "bm012_stone_pickaxe_crafting_table_missing"
    assert place_table == "Place the crafting table nearby for stone-pickaxe crafting"
    assert place_decision["selection_reason"] == "bm012_stone_pickaxe_crafting_table_unplaced"
    print("PASS: strict BM-012 restores crafting-station access before stone-pickaxe crafting")


def test_m4_bm012_frontier_yield_preserves_station_access_goals():
    tmpdir = tempfile.mkdtemp()
    agent = object.__new__(Agent)
    agent.config = Config(
        memory_dir=os.path.join(tmpdir, "memory"),
        skill_dir=os.path.join(tmpdir, "skills"),
        planner_protocol="m4-fixed-v1",
    )
    agent._m4_task_id = "BM-012"
    observation = {
        "health": 20,
        "hunger": 20,
        "time_of_day": 4658,
        "inventory": {
            "oak_log": 3,
            "oak_planks": 3,
            "stick": 3,
            "wooden_pickaxe": 1,
            "cobblestone": 3,
        },
        "nearby_entities": [],
        "nearby_blocks": [{"name": "stone"}, {"name": "coal_ore"}],
    }

    station_goals = [
        "Craft crafting table for stone-pickaxe crafting",
        "Place the crafting table nearby for stone-pickaxe crafting",
        "Gather 1 log for stone-pickaxe crafting table access",
    ]
    for goal in station_goals:
        assert agent._m4_bm012_stone_pickaxe_frontier_ready(observation, goal) is False
        assert agent._yield_m4_bm012_stone_pickaxe_frontier(
            observation,
            goal,
            {"phase": "pre_planner"},
        ) is False

    assert agent._m4_bm012_stone_pickaxe_frontier_ready(
        observation,
        "Mine 12 cobblestone for stone tools and furnace",
    ) is True
    print("PASS: strict BM-012 station-access goals bypass stale frontier yield")


def test_m4_bm012_selector_preserves_stone_pickaxe_frontier_over_stale_tasks():
    tmpdir = tempfile.mkdtemp()
    agent = object.__new__(Agent)
    agent.config = Config(
        memory_dir=os.path.join(tmpdir, "memory"),
        skill_dir=os.path.join(tmpdir, "skills"),
        planner_protocol="m4-fixed-v1",
    )
    agent._m4_task_id = "BM-012"
    agent.task_system = TaskSystem()
    agent.curriculum = CurriculumManager()
    agent.memory = MemorySystem(agent.config.memory_dir, persist=False)
    agent.skill_library = SkillLibrary(agent.config.skill_dir, persist=False)
    stale = agent.task_system.create_task(
        "Mine 12 cobblestone",
        status=TaskStatus.ACCEPTED,
        priority=0,
        preconditions={"inventory": {"wooden_pickaxe": 1}},
        success_criteria={"inventory": {"cobblestone": 12}},
    )
    observation = {
        "health": 20,
        "hunger": 20,
        "time_of_day": 6011,
        "inventory": {
            "oak_log": 3,
            "oak_planks": 3,
            "stick": 2,
            "wooden_pickaxe": 1,
            "cobblestone": 3,
        },
        "nearby_entities": [],
        "nearby_blocks": [{"name": "crafting_table"}, {"name": "stone"}],
    }

    selected = agent._select_autonomous_goal(
        observation,
        "Craft a stone pickaxe for mining iron ore",
    )

    assert selected == "Craft a stone pickaxe for mining iron ore"
    assert stale in agent.task_system.get_ready_tasks(observation)
    print("PASS: strict BM-012 stone-pickaxe frontier outranks stale cobblestone tasks")


def test_m4_bm012_selector_preserves_detached_station_frontier_over_coal():
    tmpdir = tempfile.mkdtemp()
    agent = object.__new__(Agent)
    agent.config = Config(
        memory_dir=os.path.join(tmpdir, "memory"),
        skill_dir=os.path.join(tmpdir, "skills"),
        planner_protocol="m4-fixed-v1",
    )
    agent._m4_task_id = "BM-012"
    agent.task_system = TaskSystem()
    agent.curriculum = CurriculumManager()
    agent.memory = MemorySystem(agent.config.memory_dir, persist=False)
    agent.skill_library = SkillLibrary(agent.config.skill_dir, persist=False)
    observation = {
        "health": 20,
        "hunger": 20,
        "time_of_day": 7000,
        "inventory": {
            "oak_log": 3,
            "oak_planks": 3,
            "stick": 2,
            "wooden_pickaxe": 1,
            "cobblestone": 3,
        },
        "nearby_entities": [],
        "nearby_blocks": [{"name": "stone"}, {"name": "coal_ore"}],
    }

    fallback = "Craft crafting table for stone-pickaxe crafting"
    selected = agent._select_autonomous_goal(observation, fallback)

    assert selected == fallback
    assert selected != "Collect coal or charcoal for torches"
    assert agent._last_autonomous_goal_decision["selection_source"] == "goal_generator"
    print("PASS: strict BM-012 station-access frontier outranks nearby coal")


def test_coach_policy_biases_curriculum_candidates_without_mutating_inputs():
    candidates = [
        CurriculumGoalCandidate(
            "Explore east frontier cell",
            "world_model_frontier",
            45.0,
            reasons=["world_model_frontier_feedback"],
        ),
        CurriculumGoalCandidate(
            "Craft torches for cave and night safety",
            "crafting",
            48.0,
            reasons=["reduce_exploration_risk"],
        ),
        CurriculumGoalCandidate(
            "Scout safer route around mapped danger cells",
            "world_model_safety",
            44.0,
            reasons=["world_model_danger_feedback"],
        ),
    ]

    explorer_ranked = CoachPolicy.from_style("explorer").rank_curriculum_candidates(
        candidates,
        {"health": 20, "time_of_day": 4000, "nearby_entities": []},
    )
    safe_ranked = CoachPolicy.from_style("safe").rank_curriculum_candidates(
        candidates,
        {"health": 8, "time_of_day": 13000, "nearby_entities": [{"hostile": True, "distance": 6}]},
    )

    assert explorer_ranked[0].category == "world_model_frontier"
    assert "coach:explorer:world_model_frontier_feedback" in explorer_ranked[0].reasons
    assert safe_ranked[0].category == "world_model_safety"
    assert "coach:safe:danger_pressure" in safe_ranked[0].reasons
    assert candidates[0].score == 45.0
    assert all(not reason.startswith("coach:") for reason in candidates[0].reasons)
    print("PASS: Coach policy biases curriculum candidates without mutating inputs")


def test_agent_autonomous_selector_records_coached_curriculum_decision():
    tmpdir = tempfile.mkdtemp()
    agent = object.__new__(Agent)
    agent.config = Config(
        memory_dir=os.path.join(tmpdir, "memory"),
        skill_dir=os.path.join(tmpdir, "skills"),
        coach_style="explorer",
    )
    agent.task_system = TaskSystem()
    agent.curriculum = CurriculumManager()
    agent.curriculum.record_world_model_feedback({
        "frontier_count": 4,
        "suggested_goals": ["Explore east frontier cell (1,0) near x=12, z=4"],
        "frontiers": [{"cell": {"x": 1, "z": 0}, "direction": "east"}],
    })
    agent.memory = MemorySystem(agent.config.memory_dir, persist=False)
    agent.skill_library = SkillLibrary(agent.config.skill_dir, persist=False)

    goal = agent._select_autonomous_goal(
        {
            "health": 20,
            "time_of_day": 4000,
            "inventory": {"crafting_table": 1, "wooden_pickaxe": 1, "oak_log": 4},
            "nearby_entities": [],
        },
        "Explore surroundings and gather resources",
    )

    assert goal == "Explore east frontier cell (1,0) near x=12, z=4"
    assert agent.curriculum.last_decision["coach"]["styles"] == ["explorer"]
    assert agent.curriculum.last_decision["candidates"][0]["title"] == goal
    assert agent.memory.l2_episodic[-1]["data"]["decision"]["coach"]["styles"] == ["explorer"]
    print("PASS: Agent autonomous selector records coached curriculum decision")


if __name__ == "__main__":
    test_curriculum_keeps_emergency_goal()
    test_curriculum_promotes_ready_crafting_progression()
    test_curriculum_uses_visible_novel_resource_when_stable()
    test_curriculum_uses_exploration_feedback_for_goal_ranking()
    test_curriculum_scores_structured_frontiers_with_transfer_memory()
    test_curriculum_penalizes_repeated_failures()
    test_agent_autonomous_selector_uses_curriculum_when_no_ready_task()
    test_m4_bm012_selector_preserves_exact_three_cobblestone_frontier()
    test_m4_bm012_goal_generator_closes_wood_to_stone_pickaxe_frontier()
    test_m4_bm012_goal_generator_repairs_detached_crafting_station_frontier()
    test_m4_bm012_frontier_yield_preserves_station_access_goals()
    test_m4_bm012_selector_preserves_stone_pickaxe_frontier_over_stale_tasks()
    test_m4_bm012_selector_preserves_detached_station_frontier_over_coal()
    test_coach_policy_biases_curriculum_candidates_without_mutating_inputs()
    test_agent_autonomous_selector_records_coached_curriculum_decision()
    print("\nCurriculum tests PASSED")
