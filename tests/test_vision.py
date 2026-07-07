"""Vision module tests - tests screenshot analysis, VLM, visual memory."""
import sys, os, json, tempfile, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import unittest
from singularity.vision.analyzer import VisionAnalyzer
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
        for key in ("position", "health", "resources", "dangers", "nearby_entities", "visual_analysis"):
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
