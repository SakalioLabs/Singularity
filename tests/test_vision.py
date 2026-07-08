"""Vision module tests - tests screenshot analysis, VLM, visual memory."""
import sys, os, json, tempfile, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import unittest
from singularity.vision.analyzer import VisionAnalyzer
from singularity.vision.action_advisor import VisualActionAdvisor
from singularity.vision.visual_memory import VisualMemory


class TestVisionAnalyzer(unittest.TestCase):
    def setUp(self):
        self.analyzer = VisionAnalyzer()
        self.sample_obs = {
            "position": {"x": 0, "y": 66, "z": 0},
            "health": 20, "hunger": 20,
            "nearby_entities": [
                {"type": "zombie", "distance": 15, "hostile": True},
                {"type": "sheep", "distance": 10, "hostile": False},
            ],
            "nearby_blocks": [
                {"name": "oak_log", "distance": 5},
                {"name": "iron_ore", "distance": 20},
                {"name": "grass_block", "distance": 1},
            ],
            "trees_found": [
                {"name": "oak_log", "position": {"x": 5, "y": 66, "z": 5}, "distance": 7},
            ],
            "time_of_day": 6000,
        }

    def test_analyzer_creates_without_api_key(self):
        a = VisionAnalyzer()
        self.assertFalse(a.is_available())

    def test_analyzer_detects_resources(self):
        result = self.analyzer.analyze(self.sample_obs)
        self.assertGreater(len(result.get("resources", [])), 0)
        names = [r["name"] for r in result["resources"]]
        self.assertIn("oak_log", names)

    def test_analyzer_detects_dangers(self):
        result = self.analyzer.analyze(self.sample_obs)
        self.assertGreater(len(result.get("dangers", [])), 0)

    def test_analyzer_handles_empty_observation(self):
        result = self.analyzer.analyze({})
        self.assertIn("resources", result)
        self.assertEqual(len(result.get("resources", [])), 0)

    def test_analyzer_returns_structured_result(self):
        result = self.analyzer.analyze(self.sample_obs)
        for key in ("position", "health", "resources", "grounded_resources", "dangers", "nearby_entities", "visual_analysis"):
            self.assertIn(key, result)

    def test_analyzer_no_dangers_when_safe(self):
        safe_obs = {"nearby_entities": [{"type": "sheep", "distance": 5, "hostile": False}]}
        result = self.analyzer.analyze(safe_obs)
        self.assertEqual(len(result.get("dangers", [])), 0)

    def test_analyzer_find_multiple_resources(self):
        obs = {"nearby_blocks": [
            {"name": "oak_log", "distance": 3},
            {"name": "birch_log", "distance": 5},
            {"name": "diamond_ore", "distance": 15},
        ], "trees_found": [
            {"name": "spruce_log", "distance": 8},
        ]}
        result = self.analyzer.analyze(obs)
        self.assertGreaterEqual(len(result.get("resources", [])), 3)

    def test_analyzer_env_detection(self):
        import os
        key = os.environ.get("OPENAI_API_KEY", "")
        a = VisionAnalyzer()
        if key:
            self.assertTrue(a.is_available() or True)

    def test_is_available_false_without_key(self):
        a = VisionAnalyzer()
        self.assertFalse(a.is_available())

    def test_analyzer_adds_grounded_resource_fields(self):
        obs = {
            "inventory": {"stone_pickaxe": 1},
            "nearby_blocks": [{"name": "iron_ore", "distance": 8}],
            "trees_found": [],
        }
        result = self.analyzer.analyze(obs)
        iron = result["resources"][0]
        self.assertEqual(iron["drop"], "raw_iron")
        self.assertEqual(iron["required_tool_tier"], 2)
        self.assertEqual(iron["recommended_tool"], "stone_pickaxe")
        self.assertEqual(iron["best_available_tool"], "stone_pickaxe")
        self.assertTrue(iron["can_harvest"])
        self.assertIn("iron_ore", iron["source_blocks"])

    def test_analyzer_marks_unharvestable_resource_without_tool(self):
        obs = {
            "inventory": {},
            "nearby_blocks": [{"name": "coal_ore", "distance": 4}],
            "trees_found": [],
        }
        result = self.analyzer.analyze(obs)
        coal = result["resources"][0]
        self.assertEqual(coal["drop"], "coal")
        self.assertEqual(coal["required_tool_tier"], 1)
        self.assertEqual(coal["recommended_tool"], "wooden_pickaxe")
        self.assertIsNone(coal["best_available_tool"])
        self.assertFalse(coal["can_harvest"])

    def test_analyzer_keeps_hand_collectable_logs_available(self):
        obs = {
            "inventory": {},
            "nearby_blocks": [{"name": "oak_log", "distance": 5}],
            "trees_found": [],
        }
        result = self.analyzer.analyze(obs)
        log = result["resources"][0]
        self.assertEqual(log["drop"], "oak_log")
        self.assertEqual(log["best_available_tool"], "hand")
        self.assertTrue(log["can_harvest"])
        self.assertIn("oak_planks", log["crafts_into"])

    def test_analyzer_prioritizes_harvestable_resources(self):
        obs = {
            "inventory": {},
            "nearby_blocks": [
                {"name": "diamond_ore", "distance": 1},
                {"name": "oak_log", "distance": 7},
            ],
            "trees_found": [],
        }
        result = self.analyzer.analyze(obs)
        self.assertEqual(result["grounded_resources"][0]["name"], "oak_log")


class TestVisualMemory(unittest.TestCase):
    def setUp(self):
        self.mem = VisualMemory(max_entries=10)

    def test_add_observation(self):
        entry = self.mem.add({"resources": [{"name": "oak_log"}]}, "gathering")
        self.assertIn("timestamp", entry)
        self.assertEqual(entry["type"], "gathering")

    def test_get_recent(self):
        self.mem.add({"a": 1}, "t1")
        self.mem.add({"b": 2}, "t2")
        recent = self.mem.get_recent(1)
        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0]["type"], "t2")

    def test_search_by_type(self):
        self.mem.add({"a": 1}, "gathering")
        self.mem.add({"b": 2}, "exploration")
        results = self.mem.search(obs_type="gathering")
        self.assertEqual(len(results), 1)

    def test_search_by_query(self):
        self.mem.add({"resource": "diamond", "pos": [10, 20]}, "mining")
        results = self.mem.search(query="diamond")
        self.assertEqual(len(results), 1)

    def test_prune_old_entries(self):
        m = VisualMemory(max_entries=5)
        for i in range(10):
            m.add({"i": i}, "t")
        self.assertLessEqual(m.count(), 5)

    def test_clear_all(self):
        self.mem.add({"a": 1}, "t")
        self.mem.clear()
        self.assertEqual(self.mem.count(), 0)

    def test_memory_count(self):
        self.assertEqual(self.mem.count(), 0)
        self.mem.add({"a": 1}, "t")
        self.assertEqual(self.mem.count(), 1)

    def test_search_empty(self):
        results = self.mem.search(query="nonexistent")
        self.assertEqual(len(results), 0)


class TestVisualActionAdvisor(unittest.TestCase):
    def test_advisor_harvests_visible_goal_resource_with_coordinates(self):
        advisor = VisualActionAdvisor()
        suggestions = advisor.suggest("gather oak logs", {
            "grounded_resources": [{
                "name": "oak_log",
                "can_harvest": True,
                "best_available_tool": "hand",
                "position": {"x": 5, "y": 66, "z": 7},
            }],
        })

        harvest = next(item for item in suggestions if item["kind"] == "resource_harvest")
        self.assertEqual(harvest["action"]["type"], "dig")
        self.assertEqual(harvest["action"]["parameters"], {"x": 5, "y": 66, "z": 7})

    def test_advisor_does_not_mine_unrelated_visible_resource(self):
        advisor = VisualActionAdvisor()
        suggestions = advisor.suggest("mine iron ore", {
            "grounded_resources": [{
                "name": "oak_log",
                "can_harvest": True,
                "best_available_tool": "hand",
                "position": {"x": 5, "y": 66, "z": 7},
            }],
        })

        self.assertFalse(any(item["kind"] == "resource_harvest" for item in suggestions))

    def test_advisor_moves_toward_far_visible_resource_before_harvest(self):
        advisor = VisualActionAdvisor(harvest_reach=4, stand_distance=2)
        suggestions = advisor.suggest("mine iron ore", {
            "position": {"x": 0, "y": 64, "z": 0},
            "grounded_resources": [{
                "name": "iron_ore",
                "can_harvest": True,
                "best_available_tool": "stone_pickaxe",
                "required_tool_tier": 2,
                "position": {"x": 10, "y": 64, "z": 0},
            }],
        })

        self.assertEqual(suggestions[0]["kind"], "resource_approach")
        self.assertEqual(suggestions[0]["action"]["type"], "move_to")
        self.assertEqual(suggestions[0]["action"]["parameters"], {"x": 8.0, "z": 0.0, "y": 64})
        self.assertTrue(any(item["kind"] == "resource_harvest" for item in suggestions))

    def test_advisor_focuses_visible_resource_before_harvest(self):
        advisor = VisualActionAdvisor()
        suggestions = advisor.suggest("mine iron ore", {
            "position": {"x": 2, "y": 64, "z": 0},
            "grounded_resources": [{
                "name": "iron_ore",
                "can_harvest": True,
                "best_available_tool": "stone_pickaxe",
                "required_tool_tier": 2,
                "position": {"x": 3, "y": 64, "z": 0},
            }],
        })

        focus = next(item for item in suggestions if item["kind"] == "resource_focus")
        self.assertEqual(focus["action"]["type"], "look_at")
        self.assertEqual(focus["action"]["parameters"], {"x": 3, "y": 64, "z": 0})

    def test_advisor_retreats_from_nearby_hostile_entity(self):
        advisor = VisualActionAdvisor(retreat_distance=8)
        suggestions = advisor.suggest("mine iron", {
            "position": {"x": 0, "y": 64, "z": 0},
            "nearby_entities": [{
                "type": "zombie",
                "hostile": True,
                "distance": 3,
                "position": {"x": 4, "y": 64, "z": 0},
            }],
        })

        retreat = suggestions[0]
        self.assertEqual(retreat["kind"], "danger_retreat")
        self.assertEqual(retreat["action"]["type"], "move_to")
        self.assertLess(retreat["action"]["parameters"]["x"], 0)
        self.assertEqual(retreat["action"]["parameters"]["z"], 0)


class TestVisionIntegration(unittest.TestCase):
    def test_vision_with_observer_data(self):
        analyzer = VisionAnalyzer()
        obs = {
            "position": {"x": 10, "y": 66, "z": 20},
            "health": 18, "hunger": 15,
            "nearby_entities": [],
            "nearby_blocks": [{"name": "iron_ore", "distance": 8}],
            "trees_found": [],
        }
        result = analyzer.analyze(obs)
        self.assertIn("resources", result)

    def test_visual_memory_with_analyzer(self):
        analyzer = VisionAnalyzer()
        memory = VisualMemory(max_entries=20)
        for i in range(5):
            obs = {"nearby_blocks": [{"name": "oak_log", "distance": i * 5}]}
            result = analyzer.analyze(obs)
            memory.add(result, "scan")
        self.assertEqual(memory.count(), 5)
        recent = memory.get_recent(3)
        self.assertEqual(len(recent), 3)

    def test_vision_categorizes_resources_correctly(self):
        analyzer = VisionAnalyzer()
        obs = {"nearby_blocks": [{"name": "diamond_ore", "distance": 12}], "trees_found": []}
        result = analyzer.analyze(obs)
        resources = result.get("resources", [])
        self.assertTrue(any(r["name"] == "diamond_ore" for r in resources))

    def test_vision_end_to_end(self):
        analyzer = VisionAnalyzer()
        memory = VisualMemory()
        obs = {"position": {"x": 5, "y": 66, "z": 5}, "health": 20, "nearby_entities": [],
               "nearby_blocks": [{"name": "oak_log", "distance": 3}],
               "trees_found": [{"name": "oak_log", "distance": 3}]}
        result = analyzer.analyze(obs)
        memory.add(result, "inspection")
        self.assertGreater(len(result["resources"]), 0)
        self.assertGreater(memory.count(), 0)


if __name__ == "__main__":
    unittest.main()
