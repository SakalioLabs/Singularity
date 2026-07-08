"""Unit tests for automatic open-ended curriculum."""
import os
import sys
import tempfile

sys.path.insert(0, "src")

from singularity.core.agent import Agent
from singularity.core.config import Config
from singularity.core.curriculum import CurriculumManager
from singularity.core.memory import MemorySystem
from singularity.core.skill_library import SkillLibrary
from singularity.core.task_system import TaskSystem


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


if __name__ == "__main__":
    test_curriculum_keeps_emergency_goal()
    test_curriculum_promotes_ready_crafting_progression()
    test_curriculum_uses_visible_novel_resource_when_stable()
    test_curriculum_uses_exploration_feedback_for_goal_ranking()
    test_curriculum_penalizes_repeated_failures()
    test_agent_autonomous_selector_uses_curriculum_when_no_ready_task()
    print("\nCurriculum tests PASSED")
