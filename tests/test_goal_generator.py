"""Unit tests for M4 Goal Generator."""
import sys
sys.path.insert(0, "src")
from singularity.core.goal_generator import GoalGenerator
from singularity.evaluation.m4_shelter import (
    M4_SHELTER_CONTRACT_SHA256,
    M4_SHELTER_REQUIRED_CHECKS,
    M4_SHELTER_VERIFIER_ID,
)

gg = GoalGenerator()

def test_hostile_threat():
    obs = {"time_of_day": 5000, "health": 20, "inventory": {}, "nearby_entities": [{"type": "zombie", "distance": 5, "hostile": True}]}
    goal = gg.next_goal(obs)
    assert "Flee" in goal or "Attack" in goal
    print(f"PASS: Hostile nearby -> {goal}")

def test_critical_health():
    obs = {"time_of_day": 5000, "health": 4, "inventory": {"bread": 2}, "nearby_entities": []}
    goal = gg.next_goal(obs)
    assert "food" in goal.lower() or "eat" in goal.lower()
    print(f"PASS: Low health -> {goal}")

def test_night_preparation():
    obs = {"time_of_day": 11000, "health": 20, "inventory": {"oak_log": 6}, "nearby_entities": []}
    goal = gg.next_goal(obs)
    assert "shelter" in goal.lower() or "craft" in goal.lower()
    print(f"PASS: Dusk -> {goal}")

def test_night_indoors():
    obs = {
        "time_of_day": 15000,
        "health": 20,
        "inventory": {"crafting_table": 1, "furnace": 1, "raw_iron": 4},
        "nearby_entities": [],
        "shelter_verification": {
            "type": "m4_shelter_state_verification",
            "verifier_id": M4_SHELTER_VERIFIER_ID,
            "contract_sha256": M4_SHELTER_CONTRACT_SHA256,
            "passed": True,
            "safe_state": True,
            "source": "machine_state",
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
        },
    }
    goal = gg.next_goal(obs)
    assert "verified shelter" in goal.lower() and "dawn" in goal.lower()
    print(f"PASS: Night -> {goal}")

def test_tool_progression():
    obs = {"time_of_day": 3000, "health": 20, "inventory": {"oak_log": 6, "oak_planks": 4, "stick": 4, "crafting_table": 1}, "nearby_entities": []}
    goal = gg.next_goal(obs)
    print(f"PASS: Tool progression -> {goal}")

def test_default_explore():
    obs = {"time_of_day": 3000, "health": 20, "inventory": {}, "nearby_entities": []}
    goal = gg.next_goal(obs)
    assert goal
    print(f"PASS: Default -> {goal}")

if __name__ == "__main__":
    test_hostile_threat()
    test_critical_health()
    test_night_preparation()
    test_night_indoors()
    test_tool_progression()
    test_default_explore()
    print("\nAll goal generator tests PASSED")
