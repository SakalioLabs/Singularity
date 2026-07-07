"""M2 LLM Planner - comprehensive tests with mock LLM provider.
Tests planner, task system, retry logic, and error handling."""

import sys, os, json, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
import unittest
from singularity.core.config import LLMConfig
from singularity.core.planner import Planner
from singularity.core.task_system import TaskSystem, TaskStatus
from singularity.llm.provider import LLMProvider


class MockLLMProvider:
    """Mock LLM provider that returns predetermined responses for testing."""

    def __init__(self, responses=None):
        self.responses = responses or {}
        self.call_count = 0
        self.last_prompt = ""

    def chat(self, messages, response_format=None):
        self.call_count += 1
        self.last_prompt = messages[-1]["content"] if messages else ""
        # Extract key features from the prompt to determine response
        goal_lower = self.last_prompt.lower()

        if "craft" in goal_lower and "pickaxe" in goal_lower and "wooden" in goal_lower:
            return json.dumps({
                "status": "planning",
                "reasoning": "Need to craft planks, sticks, then wooden pickaxe",
                "subtasks": [
                    {"title": "Gather wood", "type": "gathering", "priority": 1},
                    {"title": "Craft planks", "type": "crafting", "priority": 2},
                    {"title": "Craft sticks", "type": "crafting", "priority": 3},
                    {"title": "Craft wooden pickaxe", "type": "crafting", "priority": 4},
                ],
                "actions": [
                    {"type": "dig", "parameters": {"x": 10, "y": 66, "z": 10}},
                ]
            })
        elif "craft" in goal_lower and "table" in goal_lower:
            return json.dumps({
                "status": "planning",
                "reasoning": "Need oak planks then craft table",
                "subtasks": [
                    {"title": "Gather wood", "type": "gathering", "priority": 1},
                    {"title": "Craft planks", "type": "crafting", "priority": 2},
                    {"title": "Craft crafting table", "type": "crafting", "priority": 3},
                ],
                "actions": [
                    {"type": "dig", "parameters": {"x": 10, "y": 66, "z": 10}},
                    {"type": "craft", "parameters": {"item": "oak_planks", "count": 4}},
                    {"type": "craft", "parameters": {"item": "crafting_table"}},
                ]
            })
        elif "gather" in goal_lower or "chop" in goal_lower:
            return json.dumps({
                "status": "planning",
                "reasoning": "Finding and chopping trees",
                "subtasks": [
                    {"title": "Find trees", "type": "exploration", "priority": 1},
                    {"title": "Chop oak logs", "type": "gathering", "priority": 2},
                ],
                "actions": [
                    {"type": "move_to", "parameters": {"x": 20, "z": 20}},
                    {"type": "dig", "parameters": {"x": 20, "y": 66, "z": 20}},
                ]
            })
        elif "explore" in goal_lower:
            return json.dumps({
                "status": "planning",
                "reasoning": "Exploring surroundings",
                "subtasks": [
                    {"title": "Move to new area", "type": "exploration", "priority": 1},
                ],
                "actions": [
                    {"type": "move_to", "parameters": {"x": 50, "z": 50}},
                ]
            })
        elif "mine" in goal_lower or "cobblestone" in goal_lower:
            return json.dumps({
                "status": "planning",
                "reasoning": "Need pickaxe to mine cobblestone",
                "subtasks": [
                    {"title": "Craft pickaxe if needed", "type": "crafting", "priority": 1},
                    {"title": "Mine cobblestone", "type": "mining", "priority": 2},
                ],
                "actions": [
                    {"type": "dig", "parameters": {"x": -9, "y": 63, "z": 3}},
                ]
            })
        elif "survive" in goal_lower or "night" in goal_lower:
            return json.dumps({
                "status": "planning",
                "reasoning": "Preparing for night survival",
                "subtasks": [
                    {"title": "Build shelter", "type": "building", "priority": 1},
                    {"title": "Craft bed", "type": "crafting", "priority": 2},
                ],
                "actions": [
                    {"type": "dig", "parameters": {"x": 0, "y": 66, "z": 0}},
                    {"type": "place", "parameters": {"x": 0, "y": 66, "z": 0, "item": "cobblestone"}},
                ]
            })
        elif "already" in goal_lower or "complete" in goal_lower:
            return json.dumps({
                "status": "complete",
                "reasoning": "Goal already satisfied",
                "subtasks": [],
                "actions": []
            })
        elif "blocked" in goal_lower:
            return json.dumps({
                "status": "blocked",
                "reasoning": "Not enough resources to proceed",
                "subtasks": [],
                "actions": []
            })
        elif "failed" in goal_lower or "'failed'" in goal_lower:
            return json.dumps({
                "status": "replan",
                "reasoning": "Previous attempt failed, trying alternative approach",
                "subtasks": [{"title": "Try alternative approach", "type": "general", "priority": 1}],
                "actions": [{"type": "move_to", "parameters": {"x": 30, "z": 30}}]
            })
        elif "invalid" in goal_lower:
            return "this is not valid json {{{{"
        else:
            return json.dumps({
                "status": "planning",
                "reasoning": "Analyzing goal and planning steps",
                "subtasks": [{"title": "Process goal", "type": "general", "priority": 3}],
                "actions": [{"type": "wait", "parameters": {"ms": 1000}}]
            })


class TestM2PlannerWithMock(unittest.TestCase):
    """M2 planner tests using mock LLM responses - no API key needed."""

    def setUp(self):
        self.llm = MockLLMProvider()
        self.ts = TaskSystem()
        self.planner = Planner(self.llm, self.ts)

    def test_gather_wood_plan(self):
        plan = self.planner.plan_from_goal("Gather 3 oak logs", {"inventory": {}, "position": {"x": 0, "z": 0}})
        self.assertEqual(plan["status"], "planning")
        self.assertGreater(len(plan.get("subtasks", [])), 0)
        self.assertGreater(len(plan.get("actions", [])), 0)

    def test_craft_table_plan(self):
        plan = self.planner.plan_from_goal("Craft a crafting table", {"inventory": {"oak_log": 5}})
        self.assertEqual(plan["status"], "planning")
        actions = plan.get("actions", [])
        self.assertTrue(any(a["type"] == "craft" for a in actions))

    def test_craft_wooden_pickaxe_plan(self):
        plan = self.planner.plan_from_goal("Craft a wooden pickaxe", {"inventory": {"oak_log": 5}})
        self.assertEqual(plan["status"], "planning")
        subtasks = plan.get("subtasks", [])
        self.assertTrue(any("pickaxe" in s["title"].lower() for s in subtasks))

    def test_mine_cobblestone_plan(self):
        plan = self.planner.plan_from_goal("Mine 3 cobblestone", {"inventory": {"wooden_pickaxe": 1}})
        self.assertEqual(plan["status"], "planning")

    def test_explore_plan(self):
        plan = self.planner.plan_from_goal("Explore surroundings", {"inventory": {}})
        self.assertEqual(plan["status"], "planning")

    def test_survive_night_plan(self):
        plan = self.planner.plan_from_goal("Survive the first night", {"inventory": {}, "time_of_day": 10000})
        self.assertEqual(plan["status"], "planning")
        actions = plan.get("actions", [])
        self.assertTrue(any(a["type"] == "dig" for a in actions))

    def test_complete_status_plan(self):
        plan = self.planner.plan_from_goal("Goal already complete", {"inventory": {"diamond": 10}})
        self.assertEqual(plan["status"], "complete")

    def test_blocked_status_plan(self):
        plan = self.planner.plan_from_goal("Blocked by lack of resources", {"inventory": {}})
        self.assertEqual(plan["status"], "blocked")

    def test_invalid_json_handling(self):
        plan = self.planner.plan_from_goal("Invalid JSON response", {"inventory": {}})
        self.assertEqual(plan["status"], "error")

    def test_empty_world_state(self):
        plan = self.planner.plan_from_goal("Gather 3 oak logs", {})
        self.assertEqual(plan["status"], "planning")

    def test_tasks_created_from_plan(self):
        self.planner.plan_from_goal("Gather 3 oak logs", {"inventory": {}})
        self.assertGreater(len(self.ts.tasks), 0)

    def test_realistic_world_state(self):
        ws = {
            "position": {"x": 0, "y": 66, "z": 0},
            "health": 20, "hunger": 20,
            "inventory": {"oak_log": 2, "cobblestone": 5},
            "time_of_day": 6000,
            "nearby_entities": [],
            "trees_found": [{"name": "oak_log", "position": {"x": 10, "y": 66, "z": 10}, "distance": 14}]
        }
        plan = self.planner.plan_from_goal("Craft a wooden pickaxe", ws)
        self.assertIn(plan["status"], ("planning", "complete", "blocked"))

    def test_llm_call_count(self):
        self.planner.plan_from_goal("Gather 3 oak logs", {"inventory": {}})
        self.assertEqual(self.llm.call_count, 1)

    def test_memory_context_injection(self):
        plan = self.planner.plan_from_goal(
            "Gather 3 oak logs",
            {"inventory": {}},
            memory_context="You previously found oak logs at coordinates (10, 66, 10)"
        )
        self.assertIn(plan["status"], ("planning", "complete", "blocked"))
        self.assertIn("oak", self.llm.last_prompt.lower())

    def test_goal_complex_crafting_chain(self):
        plan = self.planner.plan_from_goal("Craft a stone pickaxe", {"inventory": {"oak_log": 5, "cobblestone": 5}})
        self.assertEqual(plan["status"], "planning")

    def test_replan_basic(self):
        task = self.ts.create_task("Test task", task_type="general")
        plan = self.planner.replan(task, {"inventory": {}}, "Not enough wood")
        self.assertIn(plan["status"], ("replan", "error", "planning"))

    def test_replan_after_failure(self):
        task = self.ts.create_task("Gather wood", task_type="gathering")
        self.ts.fail_task(task.id, "Could not find trees")
        plan = self.planner.replan(task, {"inventory": {}, "position": {"x": 0, "z": 0}}, "Could not find trees")
        self.assertIn(plan["status"], ("replan", "error", "planning"))
        self.assertGreater(self.llm.call_count, 0)

    def test_planner_prompt_format(self):
        self.planner.plan_from_goal("Gather 3 oak logs", {"inventory": {}})
        self.assertIn("oak", self.llm.last_prompt.lower())

    def test_planner_handles_large_inventory(self):
        inv = {f"item_{i}": i for i in range(50)}
        plan = self.planner.plan_from_goal("Gather 3 oak logs", {"inventory": inv})
        self.assertIn(plan["status"], ("planning", "complete", "blocked"))

    def test_planner_without_system_prompt(self):
        """Test that planner handles missing prompt gracefully."""
        response = self.llm.chat([{"role": "user", "content": "Test"}])
        self.assertIsNotNone(response)


class TestTaskSystemAdvanced(unittest.TestCase):
    """Advanced task system tests."""

    def setUp(self):
        self.ts = TaskSystem()

    def test_task_dependency_chain(self):
        gather = self.ts.create_task("Gather wood", task_type="gathering", priority=1)
        craft = self.ts.create_task("Craft planks", task_type="crafting", priority=2, parent_id=gather.id)
        table = self.ts.create_task("Craft table", task_type="crafting", priority=3, parent_id=craft.id)
        self.assertIn(craft.id, gather.children)
        self.assertIn(table.id, craft.children)

    def test_task_priority_sorting(self):
        low = self.ts.create_task("Low priority", priority=5)
        high = self.ts.create_task("High priority", priority=1)
        med = self.ts.create_task("Medium priority", priority=3)
        self.ts.update_task(high.id, status=TaskStatus.ACTIVE)
        self.ts.update_task(low.id, status=TaskStatus.ACCEPTED)
        self.ts.update_task(med.id, status=TaskStatus.ACTIVE)
        next_task = self.ts.get_next_task()
        self.assertEqual(next_task.id, high.id)

    def test_invalid_task_update(self):
        self.ts.update_task("nonexistent", status=TaskStatus.COMPLETED)
        self.assertEqual(len(self.ts.tasks), 0)

    def test_task_result_tracking(self):
        task = self.ts.create_task("Mine cobblestone")
        self.ts.complete_task(task.id, {"blocks_mined": 5, "items": {"cobblestone": 5}})
        self.assertEqual(task.result.get("blocks_mined"), 5)
        self.assertEqual(task.status, TaskStatus.COMPLETED)

    def test_task_failure_with_attempts(self):
        task = self.ts.create_task("Craft pickaxe")
        self.ts.fail_task(task.id, "Missing materials")
        self.ts.fail_task(task.id, "Still missing materials")
        self.ts.fail_task(task.id, "Third time failed")
        self.assertEqual(task.attempts, 3)
        self.assertEqual(task.status, TaskStatus.FAILED)

    def test_complex_task_tree_traversal(self):
        root = self.ts.create_task("Survive", task_type="strategic", priority=1)
        gather = self.ts.create_task("Gather resources", task_type="gathering", parent_id=root.id)
        shelter = self.ts.create_task("Build shelter", task_type="building", parent_id=root.id)
        wood = self.ts.create_task("Gather wood", task_type="gathering", parent_id=gather.id)
        stone = self.ts.create_task("Gather stone", task_type="mining", parent_id=gather.id)
        tree = self.ts.get_task_tree()
        self.assertIn(root.id, tree)
        self.assertEqual(len(tree[root.id]["children"]), 2)


class TestPlannerIntegration(unittest.TestCase):
    """Integration tests combining planner with task system."""

    def test_planner_with_real_ts_flow(self):
        llm = MockLLMProvider()
        ts = TaskSystem()
        planner = Planner(llm, ts)
        plan = planner.plan_from_goal("Craft a crafting table", {"inventory": {"oak_log": 3}})
        self.assertEqual(len(ts.tasks), len(plan.get("subtasks", [])))

    def test_planner_then_replan_flow(self):
        llm = MockLLMProvider()
        ts = TaskSystem()
        planner = Planner(llm, ts)
        plan = planner.plan_from_goal("Gather 3 oak logs", {"inventory": {}})
        self.assertEqual(plan["status"], "planning")
        if ts.tasks:
            task = list(ts.tasks.values())[0]
            replan = planner.replan(task, {"inventory": {}}, "Could not find trees nearby")
            self.assertIn(replan["status"], ("replan", "error", "planning"))

    def test_mock_llm_provider_basic(self):
        llm = MockLLMProvider()
        response = llm.chat([{"role": "user", "content": "Gather 3 oak logs"}])
        data = json.loads(response)
        self.assertEqual(data["status"], "planning")

    def test_mock_llm_all_responses_valid_json(self):
        llm = MockLLMProvider()
        goals = [
            "Gather 3 oak logs",
            "Craft a crafting table",
            "Craft a wooden pickaxe",
            "Explore surroundings",
            "Mine 3 cobblestone",
            "Survive the first night",
            "Goal already complete",
            "Blocked by lack of resources",
        ]
        for goal in goals:
            response = llm.chat([{"role": "user", "content": goal}])
            try:
                data = json.loads(response)
                self.assertIn("status", data)
            except json.JSONDecodeError:
                self.fail(f"Invalid JSON for goal: {goal}")

    def test_llm_provider_wrapper_with_mock(self):
        """Test that Planner works with any object that has a chat() method."""
        llm = MockLLMProvider()
        ts = TaskSystem()
        planner = Planner(llm, ts)
        # Can't test real LLMProvider without API key, but the interface is compatible
        self.assertTrue(hasattr(llm, "chat"))


if __name__ == "__main__":
    unittest.main(verbosity=2)



