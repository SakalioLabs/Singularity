"""Rule-based fallback planner for M1 benchmarks - no LLM required."""
import logging

logger = logging.getLogger("singularity.rule_planner")


class RuleBasedPlanner:
    """Simple rule-based planner for basic Minecraft tasks without an LLM."""

    def plan_from_goal(self, goal: str, world_state: dict) -> dict:
        goal_lower = goal.lower()
        inv = world_state.get("inventory", {})
        trees = world_state.get("trees_found", [])

        # Order matters: more specific matches first
        if "oak" in goal_lower and ("log" in goal_lower or "wood" in goal_lower):
            return self._plan_gather_wood(inv, trees)
        elif "craft" in goal_lower and "table" in goal_lower:
            return self._plan_craft_workbench(inv)
        elif "craft" in goal_lower and "pickaxe" in goal_lower and "wooden" in goal_lower:
            return self._plan_craft_wooden_pickaxe(inv)
        elif "craft" in goal_lower and "pickaxe" in goal_lower and "stone" in goal_lower:
            return self._plan_craft_stone_pickaxe(inv)
        elif "cobblestone" in goal_lower or ("mine" in goal_lower and "stone" in goal_lower):
            return self._plan_mine_cobblestone(inv)
        elif "stone" in goal_lower and "pickaxe" in goal_lower:
            return self._plan_craft_stone_pickaxe(inv)
        return {"status": "blocked", "reasoning": f"No rule for goal: {goal}", "actions": []}

    def _plan_gather_wood(self, inv: dict, trees: list) -> dict:
        oak_logs = inv.get("oak_log", 0)
        if oak_logs >= 3:
            return {"status": "complete", "reasoning": f"Have {oak_logs} oak logs", "actions": []}
        if trees:
            nearest = trees[0]
            pos = nearest.get("position", {})
            return {
                "status": "in_progress",
                "reasoning": f"Found {nearest['name']} at distance {nearest['distance']}, navigating",
                "actions": [
                    {"type": "move_to", "parameters": {"x": pos.get("x", 0), "z": pos.get("z", 0)}},
                    {"type": "dig", "parameters": {"x": pos.get("x", 0), "y": pos.get("y", 0), "z": pos.get("z", 0)}},
                ]
            }
        return {
            "status": "in_progress",
            "reasoning": "No trees nearby, exploring to find some",
            "actions": [
                {"type": "move_to", "parameters": {"x": 20, "z": 20}},
                {"type": "wait", "parameters": {"ms": 1000}},
            ]
        }

    def _plan_craft_workbench(self, inv: dict) -> dict:
        if inv.get("crafting_table", 0) >= 1:
            return {"status": "complete", "reasoning": "Already have crafting table", "actions": []}
        if inv.get("oak_planks", 0) >= 4:
            return {"status": "in_progress", "reasoning": "Crafting table",
                    "actions": [{"type": "craft", "parameters": {"item": "crafting_table"}}]}
        if inv.get("oak_log", 0) >= 1:
            return {"status": "in_progress", "reasoning": "Need planks first",
                    "actions": [{"type": "craft", "parameters": {"item": "oak_planks", "count": 4}}]}
        return {"status": "blocked", "reasoning": "Need oak logs", "actions": []}

    def _plan_craft_wooden_pickaxe(self, inv: dict) -> dict:
        if inv.get("wooden_pickaxe", 0) >= 1:
            return {"status": "complete", "reasoning": "Already have", "actions": []}
        if inv.get("oak_planks", 0) >= 3 and inv.get("stick", 0) >= 2:
            return {"status": "in_progress", "reasoning": "Crafting pickaxe",
                    "actions": [{"type": "craft", "parameters": {"item": "wooden_pickaxe"}}]}
        if inv.get("oak_planks", 0) < 3 and inv.get("oak_log", 0) >= 1:
            return {"status": "in_progress", "reasoning": "Need planks",
                    "actions": [{"type": "craft", "parameters": {"item": "oak_planks", "count": 4}}]}
        if inv.get("oak_planks", 0) >= 2 and inv.get("stick", 0) < 2:
            return {"status": "in_progress", "reasoning": "Need sticks",
                    "actions": [{"type": "craft", "parameters": {"item": "stick"}}]}
        return {"status": "blocked", "reasoning": "Need materials", "actions": []}

    def _plan_mine_cobblestone(self, inv: dict) -> dict:
        if inv.get("cobblestone", 0) >= 3:
            return {"status": "complete", "reasoning": f"Have {inv.get('cobblestone', 0)} cobblestone", "actions": []}
        if inv.get("wooden_pickaxe", 0) >= 1 or inv.get("stone_pickaxe", 0) >= 1:
            return {"status": "in_progress", "reasoning": "Mining",
                    "actions": [{"type": "dig", "parameters": {"x": -9, "y": 64, "z": 3}}]}
        return {"status": "blocked", "reasoning": "Need pickaxe", "actions": []}

    def _plan_craft_stone_pickaxe(self, inv: dict) -> dict:
        if inv.get("stone_pickaxe", 0) >= 1:
            return {"status": "complete", "reasoning": "Already have", "actions": []}
        if inv.get("cobblestone", 0) >= 3 and inv.get("stick", 0) >= 2:
            return {"status": "in_progress", "reasoning": "Crafting",
                    "actions": [{"type": "craft", "parameters": {"item": "stone_pickaxe"}}]}
        return {"status": "blocked", "reasoning": "Need cobblestone and sticks", "actions": []}
