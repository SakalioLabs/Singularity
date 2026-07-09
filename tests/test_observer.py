"""Tests for structured Minecraft player-state observations."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from singularity.observation.observer import Observer


class FakeBot:
    def get_player_state(self):
        return {
            "position": {"x": 1, "y": 64, "z": 2},
            "health": 18,
            "food": 17,
            "foodSaturation": 4.5,
            "oxygenLevel": 19,
            "experience": {"level": 7},
            "dimension": "overworld",
            "gameMode": "survival",
            "selectedSlot": 2,
            "equipment": [{"slot": 0, "name": "wooden_pickaxe", "count": 1}],
            "yaw": 0.25,
            "pitch": -0.5,
        }

    def get_inventory(self):
        return [{"name": "oak_log", "count": 3}]


def test_observer_preserves_restoration_critical_player_state():
    observation = Observer(FakeBot()).observe(mode="minimal")

    assert observation["dimension"] == "overworld"
    assert observation["game_mode"] == "survival"
    assert observation["hunger"] == 17
    assert observation["food_saturation"] == 4.5
    assert observation["oxygen"] == 19
    assert observation["xp_level"] == 7
    assert observation["selected_slot"] == 2
    assert observation["equipment"][0]["name"] == "wooden_pickaxe"
    assert observation["inventory"] == {"oak_log": 3}
    print("PASS: Observer preserves restoration-critical player state")


if __name__ == "__main__":
    test_observer_preserves_restoration_critical_player_state()
