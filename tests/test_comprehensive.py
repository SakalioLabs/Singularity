"""Comprehensive unit tests for Singularity - runs without Minecraft server.

Tests all core modules: GoalGenerator, Explorer, MemorySystem, SkillLibrary,
TaskSystem, KnowledgeBase, RulePlanner, SessionLogger, Config.
"""
import sys
import os
import json
import time
import tempfile
import unittest

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from singularity.core.config import Config, BotConfig, LLMConfig
from singularity.core.goal_generator import GoalGenerator
from singularity.core.explorer import Explorer
from singularity.core.memory import MemorySystem
from singularity.core.skill_library import SkillLibrary
from singularity.core.task_system import TaskSystem, TaskStatus
from singularity.core.rule_planner import RuleBasedPlanner
from singularity.data.knowledge_base import KnowledgeBase
from singularity.logging.session_logger import SessionLogger


class TestConfig(unittest.TestCase):
    """Test configuration dataclasses."""

    def test_default_config(self):
        config = Config()
        self.assertEqual(config.bot.host, "localhost")
        self.assertEqual(config.bot.port, 25565)
        self.assertEqual(config.bot.username, "Singularity")
        self.assertEqual(config.bot.bridge_host, "127.0.0.1")
        self.assertEqual(config.bot.bridge_port, 3000)
        self.assertEqual(config.llm.provider, "openai")
        self.assertEqual(config.llm.model, "gpt-4o-mini")
        self.assertEqual(config.health_critical_threshold, 4.0)
        self.assertEqual(config.max_action_timeout, 30000)

    def test_custom_config(self):
        config = Config(
            bot=BotConfig(host="192.168.1.10", port=25566, username="TestBot", bridge_port=3005),
            llm=LLMConfig(provider="anthropic", model="claude-3", api_key="test-key"),
        )
        self.assertEqual(config.bot.host, "192.168.1.10")
        self.assertEqual(config.bot.bridge_port, 3005)
        self.assertEqual(config.llm.provider, "anthropic")


class TestGoalGenerator(unittest.TestCase):
    """Test M4 goal generator - 8 priority scenarios."""

    def setUp(self):
        self.gen = GoalGenerator()

    def test_critical_threat_no_weapon(self):
        obs = {"nearby_entities": [{"hostile": True, "distance": 5, "type": "zombie"}], "inventory": {}}
        goal = self.gen.next_goal(obs)
        self.assertIn("Flee", goal)

    def test_critical_threat_with_weapon(self):
        obs = {
            "nearby_entities": [{"hostile": True, "distance": 5, "type": "zombie"}],
            "inventory": {"wooden_sword": 1},
        }
        goal = self.gen.next_goal(obs)
        self.assertIn("Attack", goal)

    def test_critical_health_with_food(self):
        obs = {"health": 4, "inventory": {"bread": 2}, "nearby_entities": [], "time_of_day": 6000}
        goal = self.gen.next_goal(obs)
        self.assertIn("Eat", goal)

    def test_critical_health_no_food(self):
        obs = {"health": 4, "inventory": {}, "nearby_entities": [], "time_of_day": 6000}
        goal = self.gen.next_goal(obs)
        self.assertIn("food", goal.lower())

    def test_dusk_shelter_needed(self):
        obs = {"health": 20, "inventory": {}, "nearby_entities": [], "time_of_day": 11000}
        goal = self.gen.next_goal(obs)
        self.assertIn("shelter", goal.lower())

    def test_night_smelt(self):
        obs = {"health": 20, "inventory": {"furnace": 1, "raw_iron": 3}, "nearby_entities": [], "time_of_day": 14000}
        goal = self.gen.next_goal(obs)
        self.assertIn("Smelt", goal)

    def test_tool_progression_wooden(self):
        obs = {"health": 20, "inventory": {"oak_log": 5}, "nearby_entities": [], "time_of_day": 1000}
        goal = self.gen.next_goal(obs)
        self.assertIn("wooden", goal.lower())

    def test_default_explore(self):
        obs = {"health": 20, "inventory": {"oak_log": 10, "crafting_table": 1, "wooden_pickaxe": 1, "stone_pickaxe": 1, "cobblestone": 10}, "nearby_entities": [], "time_of_day": 3000}
        goal = self.gen.next_goal(obs)
        # Should be something resource-gathering related
        self.assertIsInstance(goal, str)
        self.assertTrue(len(goal) > 0)


class TestExplorer(unittest.TestCase):
    """Test M5 explorer module."""

    def setUp(self):
        self.explorer = Explorer()

    def test_set_base(self):
        self.explorer.set_base(100, 64, 200)
        self.assertEqual(self.explorer.base_position, {"x": 100, "y": 64, "z": 200})

    def test_distance_to_base(self):
        self.explorer.set_base(0, 64, 0)
        dist = self.explorer.distance_to_base({"x": 3, "z": 4})
        self.assertAlmostEqual(dist, 5.0, places=1)

    def test_distance_no_base(self):
        dist = self.explorer.distance_to_base({"x": 100, "z": 100})
        self.assertEqual(dist, 0)

    def test_should_return_inventory_full(self):
        self.explorer.set_base(0, 64, 0)
        should, reason = self.explorer.should_return({"x": 10, "z": 10}, 36)
        self.assertTrue(should)
        self.assertIn("Inventory", reason)

    def test_should_return_too_far(self):
        self.explorer.set_base(0, 64, 0)
        self.explorer.max_exploration_distance = 200
        should, reason = self.explorer.should_return({"x": 200, "z": 0}, 10)
        self.assertTrue(should)
        self.assertIn("Too far", reason)

    def test_should_not_return_close(self):
        self.explorer.set_base(0, 64, 0)
        should, reason = self.explorer.should_return({"x": 10, "z": 10}, 5)
        self.assertFalse(should)

    def test_record_position(self):
        self.explorer.record_position({"x": 1, "y": 64, "z": 1})
        self.assertEqual(len(self.explorer.path_history), 1)

    def test_path_history_capped(self):
        self.explorer.path_history = [{"x": i} for i in range(600)]
        self.explorer.record_position({"x": 600})
        self.assertLessEqual(len(self.explorer.path_history), 251)

    def test_add_landmark(self):
        self.explorer.add_landmark("village", {"x": 100, "z": 200}, "structure")
        self.assertEqual(len(self.explorer.landmarks), 1)
        self.assertEqual(self.explorer.landmarks[0]["name"], "village")

    def test_find_nearest_landmark(self):
        self.explorer.add_landmark("near", {"x": 10, "z": 10}, "tree")
        self.explorer.add_landmark("far", {"x": 500, "z": 500}, "tree")
        nearest = self.explorer.find_nearest_landmark({"x": 0, "z": 0})
        self.assertEqual(nearest["name"], "near")

    def test_find_nearest_by_type(self):
        self.explorer.add_landmark("tree", {"x": 5, "z": 5}, "tree")
        self.explorer.add_landmark("village", {"x": 2, "z": 2}, "structure")
        nearest = self.explorer.find_nearest_landmark({"x": 0, "z": 0}, landmark_type="structure")
        self.assertEqual(nearest["name"], "village")

    def test_return_direction(self):
        self.explorer.set_base(100, 64, 200)
        direction = self.explorer.get_return_direction({"x": 50, "z": 150})
        self.assertEqual(direction["x"], 50)
        self.assertEqual(direction["z"], 50)

    def test_exploration_target(self):
        self.explorer.set_base(0, 64, 0)
        self.explorer.path_history = [{"x": i, "z": 0} for i in range(10)]
        target = self.explorer.get_exploration_target({"x": 0, "z": 0})
        self.assertIn("x", target)
        self.assertIn("z", target)


class TestMemorySystem(unittest.TestCase):
    """Test L0-L6 memory layers."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.memory = MemorySystem(memory_dir=self.tmpdir)

    def test_write_context(self):
        self.memory.write_context({"cycle": 1, "health": 20})
        self.assertEqual(len(self.memory.l0_context), 1)

    def test_context_capped(self):
        for i in range(60):
            self.memory.write_context({"cycle": i})
        self.assertLessEqual(len(self.memory.l0_context), 40)

    def test_write_working(self):
        self.memory.write_working("last_goal", "Gather wood")
        self.assertEqual(self.memory.l1_working["last_goal"], "Gather wood")

    def test_write_episode(self):
        self.memory.write_episode("action", {"type": "dig", "success": True})
        self.assertEqual(len(self.memory.l2_episodic), 1)
        self.assertEqual(self.memory.l2_episodic[0]["type"], "action")

    def test_write_fact(self):
        self.memory.write_fact("oak_planks_crafting", "1 log = 4 planks", source="wiki")
        self.assertIn("oak_planks_crafting", self.memory.l3_semantic)
        self.assertTrue(self.memory.l3_semantic["oak_planks_crafting"]["verified"])

    def test_get_context_window(self):
        self.memory.write_context({"health": 20})
        self.memory.write_working("goal", "survive")
        window = self.memory.get_context_window()
        self.assertIn("health", window)
        self.assertIn("survive", window)

    def test_get_relevant_memory(self):
        self.memory.write_fact("oak_tree_location", "Found at x=100, z=200")
        result = self.memory.get_relevant_memory("oak tree")
        self.assertIn("oak_tree_location", result)

    def test_save_session(self):
        self.memory.write_episode("test", {"data": "value"})
        self.memory.save_session("test-session-001")
        # Check file was created
        date_str = time.strftime("%Y-%m-%d")
        filepath = os.path.join(self.tmpdir, f"{date_str}.md")
        self.assertTrue(os.path.exists(filepath))

    def test_clear_session(self):
        self.memory.write_context({"test": 1})
        self.memory.write_working("key", "val")
        self.memory.clear_session()
        self.assertEqual(len(self.memory.l0_context), 0)
        self.assertEqual(len(self.memory.l1_working), 0)
        # L2+ should persist
        self.memory.write_episode("persist", {"data": 1})
        self.memory.clear_session()
        self.assertEqual(len(self.memory.l2_episodic), 1)


class TestSkillLibrary(unittest.TestCase):
    """Test skill library with 17 builtin skills."""

    def setUp(self):
        self.lib = SkillLibrary()

    def test_builtin_skills_loaded(self):
        self.assertGreaterEqual(len(self.lib.skills), 17)

    def test_primitive_skills(self):
        primitives = self.lib.list_skills("primitive")
        names = {s.name for s in primitives}
        self.assertIn("move_to", names)
        self.assertIn("dig_block", names)
        self.assertIn("craft_item", names)

    def test_composite_skills(self):
        composites = self.lib.list_skills("composite")
        names = {s.name for s in composites}
        self.assertIn("gather_wood", names)
        self.assertIn("craft_tools", names)
        self.assertIn("build_shelter", names)

    def test_strategic_skills(self):
        strategies = self.lib.list_skills("strategic")
        names = {s.name for s in strategies}
        self.assertIn("survive_first_night", names)

    def test_get_skill(self):
        skill = self.lib.get_skill("move_to")
        self.assertIsNotNone(skill)
        self.assertEqual(skill.layer, "primitive")

    def test_record_use(self):
        self.lib.record_use("move_to", True)
        skill = self.lib.get_skill("move_to")
        self.assertEqual(skill.total_uses, 1)
        self.assertEqual(skill.successful_uses, 1)
        self.assertEqual(skill.success_rate, 1.0)

    def test_record_failure(self):
        self.lib.record_use("dig_block", False)
        self.lib.record_use("dig_block", True)
        skill = self.lib.get_skill("dig_block")
        self.assertEqual(skill.total_uses, 2)
        self.assertEqual(skill.successful_uses, 1)
        self.assertEqual(skill.success_rate, 0.5)

    def test_create_skill(self):
        skill = self.lib.create_skill("custom_mining", "Mine diamonds", "dig at y=-59")
        self.assertIn("custom_mining", self.lib.skills)
        self.assertEqual(skill.description, "Mine diamonds")

    def test_get_recommended_empty(self):
        # No skills have been used yet (besides those just recorded in other tests)
        lib2 = SkillLibrary()
        recs = lib2.get_recommended_skills("any goal", {})
        self.assertEqual(len(recs), 0)

    def test_get_recommended_with_usage(self):
        self.lib.record_use("move_to", True)
        self.lib.record_use("dig_block", True)
        self.lib.record_use("dig_block", False)
        recs = self.lib.get_recommended_skills("dig", {})
        # move_to has 100%, dig_block has 50%
        self.assertGreaterEqual(len(recs), 1)


class TestTaskSystem(unittest.TestCase):
    """Test hierarchical task state machine."""

    def setUp(self):
        self.ts = TaskSystem()

    def test_create_task(self):
        task = self.ts.create_task("Gather wood", task_type="gathering")
        self.assertEqual(task.title, "Gather wood")
        self.assertEqual(task.status, TaskStatus.PROPOSED)

    def test_create_subtask(self):
        parent = self.ts.create_task("Build shelter")
        child = self.ts.create_task("Gather wood", parent_id=parent.id)
        self.assertIn(child.id, parent.children)

    def test_update_task(self):
        task = self.ts.create_task("Test task")
        self.ts.update_task(task.id, status=TaskStatus.ACTIVE)
        self.assertEqual(self.ts.tasks[task.id].status, TaskStatus.ACTIVE)

    def test_complete_task(self):
        task = self.ts.create_task("Test task")
        self.ts.complete_task(task.id, {"items_gained": 3})
        self.assertEqual(task.status, TaskStatus.COMPLETED)
        self.assertEqual(task.result["items_gained"], 3)

    def test_fail_task(self):
        task = self.ts.create_task("Test task")
        self.ts.fail_task(task.id, "No resources")
        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertEqual(task.attempts, 1)

    def test_get_next_task(self):
        self.ts.create_task("Low priority", priority=5)
        high = self.ts.create_task("High priority", priority=1)
        self.ts.update_task(high.id, status=TaskStatus.ACTIVE)
        next_task = self.ts.get_next_task()
        self.assertEqual(next_task.id, high.id)

    def test_get_next_task_empty(self):
        self.ts.create_task("Proposed only")
        next_task = self.ts.get_next_task()
        self.assertIsNone(next_task)

    def test_task_tree(self):
        parent = self.ts.create_task("Parent")
        self.ts.create_task("Child 1", parent_id=parent.id)
        self.ts.create_task("Child 2", parent_id=parent.id)
        tree = self.ts.get_task_tree()
        self.assertIn(parent.id, tree)

    def test_multiple_failures(self):
        task = self.ts.create_task("Retry task")
        self.ts.fail_task(task.id, "First fail")
        self.ts.fail_task(task.id, "Second fail")
        self.assertEqual(task.attempts, 2)


class TestRulePlanner(unittest.TestCase):
    """Test rule-based planner for M1 benchmarks."""

    def setUp(self):
        self.planner = RuleBasedPlanner()

    def test_gather_wood_already_have(self):
        obs = {"inventory": {"oak_log": 5}, "trees_found": []}
        plan = self.planner.plan_from_goal("Gather 3 oak logs", obs)
        self.assertEqual(plan["status"], "complete")

    def test_gather_wood_need_more(self):
        obs = {"inventory": {"oak_log": 1}, "trees_found": [
            {"name": "oak_log", "position": {"x": 10, "y": 64, "z": 10}, "distance": 15}
        ]}
        plan = self.planner.plan_from_goal("Gather 3 oak logs", obs)
        self.assertEqual(plan["status"], "in_progress")
        self.assertTrue(len(plan["actions"]) > 0)

    def test_gather_wood_explore(self):
        obs = {"inventory": {}, "trees_found": []}
        plan = self.planner.plan_from_goal("Gather 3 oak logs", obs)
        self.assertEqual(plan["status"], "in_progress")

    def test_explore_frontier_uses_world_model_coordinates(self):
        obs = {
            "inventory": {"wooden_pickaxe": 1},
            "position": {"x": 0, "y": 64, "z": 0},
            "nearby_blocks": [{"name": "coal_ore", "position": {"x": 11, "y": 63, "z": 5}}],
        }
        plan = self.planner.plan_from_goal(
            "Explore east frontier cell (1,0) near x=12, z=4 to inspect coal_ore",
            obs,
        )
        self.assertEqual(plan["status"], "in_progress")
        self.assertEqual(plan["actions"][0]["type"], "move_to")
        self.assertEqual(plan["actions"][0]["parameters"], {"x": 12, "z": 4})
        self.assertEqual(plan["actions"][1]["type"], "look_at")
        self.assertEqual(plan["actions"][1]["parameters"]["x"], 11)
        self.assertIn("coal_ore", plan["reasoning"])
        self.assertEqual(plan["subtasks"][1]["success_criteria"]["observed"], "coal_ore")

    def test_explore_frontier_direction_fallback(self):
        obs = {"inventory": {}, "position": {"x": 5, "y": 64, "z": 7}}
        plan = self.planner.plan_from_goal("Explore west frontier cell (-1,0)", obs)
        self.assertEqual(plan["status"], "in_progress")
        self.assertEqual(plan["actions"][0]["type"], "move_to")
        self.assertEqual(plan["actions"][0]["parameters"], {"x": -19, "z": 7})

    def test_craft_workbench_complete(self):
        obs = {"inventory": {"crafting_table": 1}}
        plan = self.planner.plan_from_goal("Craft a crafting table", obs)
        self.assertEqual(plan["status"], "complete")

    def test_craft_workbench_need_planks(self):
        obs = {"inventory": {"oak_log": 2}}
        plan = self.planner.plan_from_goal("Craft a crafting table", obs)
        self.assertEqual(plan["status"], "in_progress")
        self.assertEqual(plan["actions"][0]["parameters"]["item"], "oak_planks")

    def test_craft_workbench_have_planks(self):
        obs = {"inventory": {"oak_planks": 4}}
        plan = self.planner.plan_from_goal("Craft a crafting table", obs)
        self.assertEqual(plan["status"], "in_progress")
        self.assertEqual(plan["actions"][0]["parameters"]["item"], "crafting_table")

    def test_craft_wooden_pickaxe_complete(self):
        obs = {"inventory": {"wooden_pickaxe": 1}}
        plan = self.planner.plan_from_goal("Craft a wooden pickaxe", obs)
        self.assertEqual(plan["status"], "complete")

    def test_craft_wooden_pickaxe_need_materials(self):
        obs = {"inventory": {"oak_planks": 3, "stick": 2}}
        plan = self.planner.plan_from_goal("Craft a wooden pickaxe", obs)
        self.assertEqual(plan["status"], "in_progress")

    def test_mine_cobblestone_complete(self):
        obs = {"inventory": {"cobblestone": 5}}
        plan = self.planner.plan_from_goal("Mine cobblestone", obs)
        self.assertEqual(plan["status"], "complete")

    def test_mine_cobblestone_bootstraps_pickaxe(self):
        obs = {
            "inventory": {},
            "trees_found": [
                {"name": "oak_log", "position": {"x": 2, "y": 64, "z": 2}, "distance": 2.0}
            ],
            "position": {"x": 0, "y": 64, "z": 0},
        }
        plan = self.planner.plan_from_goal("Mine cobblestone", obs)
        self.assertEqual(plan["status"], "in_progress")
        self.assertTrue(plan["actions"])
        self.assertIn("Need pickaxe", plan["reasoning"])

    def test_mine_cobblestone_have_pickaxe(self):
        obs = {"inventory": {"wooden_pickaxe": 1}}
        plan = self.planner.plan_from_goal("Mine cobblestone", obs)
        self.assertEqual(plan["status"], "in_progress")

    def test_stone_pickaxe_complete(self):
        obs = {"inventory": {"stone_pickaxe": 1}}
        plan = self.planner.plan_from_goal("Craft a stone pickaxe", obs)
        self.assertEqual(plan["status"], "complete")

    def test_stone_pickaxe_need_materials(self):
        obs = {"inventory": {"cobblestone": 3, "stick": 2}}
        plan = self.planner.plan_from_goal("Craft a stone pickaxe", obs)
        self.assertEqual(plan["status"], "in_progress")

    def test_unknown_goal(self):
        obs = {"inventory": {}}
        plan = self.planner.plan_from_goal("Build a rocket ship", obs)
        self.assertEqual(plan["status"], "blocked")


class TestKnowledgeBase(unittest.TestCase):
    """Test crafting knowledge base."""

    def setUp(self):
        self.kb = KnowledgeBase()

    def test_recipes_loaded(self):
        self.assertGreater(len(self.kb.recipes), 0)

    def test_get_recipe(self):
        recipe = self.kb.get_recipe("oak_planks")
        self.assertIsNotNone(recipe)

    def test_can_craft_with_ingredients(self):
        inv = {"oak_log": 5}
        result = self.kb.can_craft("oak_planks", inv)
        self.assertTrue(result)

    def test_cannot_craft_without_ingredients(self):
        inv = {}
        result = self.kb.can_craft("oak_planks", inv)
        self.assertFalse(result)

    def test_recipe_chain(self):
        chain = self.kb.get_recipe_chain("crafting_table")
        self.assertIsInstance(chain, list)

    def test_list_all_recipes(self):
        names = self.kb.list_recipes()
        self.assertIn("oak_planks", names)


class TestSessionLogger(unittest.TestCase):
    """Test structured JSON session logging."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.logger = SessionLogger(log_dir=self.tmpdir)

    def test_log_event(self):
        self.logger.log("test_event", {"data": "value"})
        self.assertEqual(len(self.logger.events), 1)

    def test_log_observation(self):
        self.logger.log_observation({"health": 20, "position": {"x": 0, "z": 0}})
        self.assertEqual(self.logger.events[0]["type"], "observation")

    def test_log_plan(self):
        self.logger.log_plan({"status": "in_progress", "actions": []})
        self.assertEqual(self.logger.events[0]["type"], "plan")

    def test_log_action(self):
        self.logger.log_action({"type": "dig"}, {"success": True})
        self.assertEqual(self.logger.events[0]["type"], "action")

    def test_log_error(self):
        self.logger.log_error("test error", {"context": "test"})
        self.assertEqual(self.logger.events[0]["level"], "ERROR")

    def test_summary(self):
        self.logger.log_observation({"test": 1})
        self.logger.log_action({"type": "dig"}, {"success": True})
        self.logger.log("policy_hint", {"phase": "hint", "hints": ["correct_craft_torch: if craft:torch fails, try dig:coal_ore"]})
        self.logger.log("policy_intervention", {"phase": "selected", "skill": "correct_craft_torch"})
        self.logger.log("policy_intervention", {"phase": "action", "skill": "correct_craft_torch"})
        self.logger.log("policy_intervention", {"phase": "completed", "skill": "correct_craft_torch"})
        self.logger.log("skill_memory_hint", {
            "goal": "Craft torches",
            "task_family": "crafting",
            "hint_count": 2,
            "hints": ["craft_torch_memory_skill[failure_correction]/success: mine coal first"],
        })
        self.logger.log("memory_write", {
            "layer": "episodic",
            "memory_type": "action",
            "operation": "write_episode",
            "policy_decision": {"decision": "failure_learning_candidate"},
        })
        self.logger.log("memory_read", {
            "layer": "mixed",
            "memory_type": "relevant_memory",
            "operation": "retrieve",
            "query": "craft torch",
            "policy_decision": {"decision": "read_instrumented"},
            "retrieval_trace": {
                "weighted_retrieval_enabled": True,
                "weighted_memory_match_count": 1,
                "weighted_transfer_match_count": 0,
                "attribution_policy_counts": {"boost_supported_memory": 1},
            },
            "read_filter_report": {
                "filtered_entries": 2,
                "filter_reasons": {"superseded": 1, "conditional_mismatch": 1},
            },
        })
        self.logger.log("memory_manage", {"layer": "episodic", "memory_type": "lifecycle", "operation": "save_session"})
        self.logger.log_error("error")
        summary = self.logger.get_summary()
        self.assertEqual(summary["action_count"], 1)
        self.assertEqual(summary["error_count"], 1)
        metrics = summary["intervention_metrics"]
        self.assertEqual(metrics["policy_hint_count"], 1)
        self.assertEqual(metrics["policy_intervention_count"], 1)
        self.assertEqual(metrics["policy_intervention_actions"], 1)
        self.assertEqual(metrics["policy_intervention_successes"], 1)
        self.assertEqual(metrics["policy_intervention_success_rate"], 1.0)
        self.assertEqual(metrics["skill_memory_hint_event_count"], 1)
        self.assertEqual(metrics["skill_memory_hint_count"], 2)
        self.assertEqual(metrics["skill_memory_task_families"]["crafting"], 1)
        self.assertEqual(summary["skill_memory_metrics"]["skill_memory_hint_count"], 2)
        memory = summary["memory_policy_metrics"]
        self.assertEqual(memory["memory_write_count"], 1)
        self.assertEqual(memory["memory_read_count"], 1)
        self.assertEqual(memory["memory_manage_count"], 1)
        self.assertEqual(memory["memory_write_layers"]["episodic"], 1)
        self.assertEqual(memory["memory_read_types"]["relevant_memory"], 1)
        self.assertEqual(memory["memory_manage_operations"]["save_session"], 1)
        self.assertEqual(memory["memory_policy_decisions"]["failure_learning_candidate"], 1)
        self.assertEqual(memory["memory_policy_decisions"]["read_instrumented"], 1)
        self.assertEqual(memory["memory_read_filter_event_count"], 1)
        self.assertEqual(memory["memory_read_filtered_entries"], 2)
        self.assertEqual(memory["memory_read_filter_reasons"]["superseded"], 1)
        self.assertEqual(memory["memory_read_filter_reasons"]["conditional_mismatch"], 1)
        self.assertEqual(memory["memory_retrieval_trace_event_count"], 1)
        self.assertEqual(memory["weighted_memory_read_count"], 1)
        self.assertEqual(memory["weighted_memory_match_count"], 1)
        self.assertEqual(memory["memory_attribution_policy_counts"]["boost_supported_memory"], 1)

    def test_visual_action_summary_metrics(self):
        self.logger.log("visual_action_suggestion", {
            "goal": "mine iron ore",
            "suggestions": [
                {"kind": "resource_approach", "action": {"type": "move_to", "parameters": {"x": 8, "y": 64, "z": 0}}},
                {"kind": "resource_harvest", "action": {"type": "dig", "parameters": {"x": 10, "y": 64, "z": 0}}},
            ],
        })
        self.logger.log("visual_action_intervention", {
            "goal": "mine iron ore",
            "phase": "prepend_approach",
            "suggestion": {"kind": "resource_approach", "action": {"type": "move_to", "parameters": {"x": 8, "y": 64, "z": 0}}},
        })

        summary = self.logger.get_summary()
        visual = summary["visual_action_metrics"]
        metrics = summary["intervention_metrics"]

        self.assertEqual(visual["visual_action_suggestion_event_count"], 1)
        self.assertEqual(visual["visual_action_suggestion_count"], 2)
        self.assertEqual(visual["visual_action_intervention_count"], 1)
        self.assertEqual(visual["visual_action_intervention_phases"]["prepend_approach"], 1)
        self.assertEqual(visual["visual_action_suggestion_kinds"]["resource_harvest"], 1)
        self.assertEqual(visual["visual_action_action_types"]["move_to"], 2)
        self.assertEqual(visual["visual_action_goals"], ["mine iron ore"])
        self.assertEqual(metrics["visual_action_intervention_count"], 1)

    def test_jsonl_file_written(self):
        self.logger.log("test", {"value": 1})
        log_files = os.listdir(self.tmpdir)
        jsonl_files = [f for f in log_files if f.endswith('.jsonl')]
        self.assertEqual(len(jsonl_files), 1)

    def test_close_writes_summary(self):
        self.logger.close()
        log_files = os.listdir(self.tmpdir)
        summary_files = [f for f in log_files if 'summary' in f]
        self.assertEqual(len(summary_files), 1)


class TestIntegrationRulePlannerGoalGenerator(unittest.TestCase):
    """Integration: GoalGenerator -> RulePlanner -> ActionController flow."""

    def test_full_gather_wood_flow(self):
        gen = GoalGenerator()
        planner = RuleBasedPlanner()

        # Initial state: no wood
        obs = {"health": 20, "inventory": {}, "nearby_entities": [], "time_of_day": 6000, "trees_found": []}
        goal = gen.next_goal(obs)
        self.assertIn("oak", goal.lower())

        plan = planner.plan_from_goal(goal, obs)
        self.assertEqual(plan["status"], "in_progress")

        # After gathering: have wood
        obs2 = {"health": 20, "inventory": {"oak_log": 8}, "nearby_entities": [], "time_of_day": 7000, "trees_found": []}
        goal2 = gen.next_goal(obs2)
        plan2 = planner.plan_from_goal(goal2, obs2)
        # Should have enough wood, goal should shift to crafting
        self.assertIn("craft", goal2.lower())

    def test_night_preparation_flow(self):
        gen = GoalGenerator()
        planner = RuleBasedPlanner()

        # Dusk time, no shelter
        obs = {"health": 20, "inventory": {"oak_log": 3}, "nearby_entities": [], "time_of_day": 11000, "trees_found": []}
        goal = gen.next_goal(obs)
        self.assertIn("shelter", goal.lower())

    def test_threat_response_flow(self):
        gen = GoalGenerator()

        # Hostile nearby, no weapon
        obs = {
            "health": 20,
            "inventory": {},
            "nearby_entities": [{"hostile": True, "distance": 6, "type": "creeper"}],
            "time_of_day": 13000,
        }
        goal = gen.next_goal(obs)
        self.assertIn("Flee", goal)

        # Same but with sword
        obs["inventory"]["stone_sword"] = 1
        goal2 = gen.next_goal(obs)
        self.assertIn("Attack", goal2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
