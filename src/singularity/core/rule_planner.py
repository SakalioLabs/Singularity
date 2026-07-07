"""Rule-based fallback planner for M1 benchmarks - no LLM required."""
import math
import logging

logger = logging.getLogger("singularity.rule_planner")

TREE_BLOCKS = {"oak_log", "birch_log", "spruce_log", "jungle_log", "acacia_log", "dark_oak_log"}


class RuleBasedPlanner:
    """Simple rule-based planner for basic Minecraft tasks without an LLM."""

    def __init__(self):
        self._explore_offset = 0

    def plan_from_goal(self, goal: str, world_state: dict) -> dict:
        goal_lower = goal.lower()
        inv = world_state.get("inventory", {})
        trees = world_state.get("trees_found", [])
        pos = world_state.get("position", {})

        # More specific matches first
        if "craft" in goal_lower and "pickaxe" in goal_lower and "stone" in goal_lower:
            return self._plan_craft_stone_pickaxe(inv, trees, pos)
        elif "craft" in goal_lower and "pickaxe" in goal_lower and "wooden" in goal_lower:
            return self._plan_craft_wooden_pickaxe(inv, trees, pos)
        elif "craft" in goal_lower and "table" in goal_lower:
            return self._plan_craft_workbench(inv, trees, pos)
        elif ("gather" in goal_lower or "chop" in goal_lower) and ("oak" in goal_lower or "log" in goal_lower or "wood" in goal_lower):
            return self._plan_gather_wood(inv, trees, pos)
        elif "cobblestone" in goal_lower or ("mine" in goal_lower and "stone" in goal_lower):
            return self._plan_mine_cobblestone(inv)
        return {"status": "blocked", "reasoning": f"No rule for goal: {goal}", "actions": []}

    def _plan_gather_wood(self, inv: dict, trees: list, pos: dict) -> dict:
        oak_logs = inv.get("oak_log", 0)
        if oak_logs >= 3:
            return {"status": "complete", "reasoning": f"Have {oak_logs} oak logs", "actions": []}
        if trees:
            nearest = trees[0]
            tpos = nearest.get("position", {})
            dist = nearest.get("distance", 999)
            # If tree is within 5 blocks, just dig it directly
            if dist <= 3.0:
                return {
                    "status": "in_progress",
                    "reasoning": f"Digging {nearest['name']} at distance {dist:.1f}",
                    "actions": [
                        {"type": "dig", "parameters": {"x": tpos.get("x", 0), "y": tpos.get("y", 0), "z": tpos.get("z", 0)}},
                    ]
                }
            # Otherwise navigate to tree then dig
            return {
                "status": "in_progress",
                "reasoning": f"Navigating to {nearest['name']} at {dist:.1f} blocks",
                "actions": [
                    {"type": "walk_to", "parameters": {"x": tpos.get("x", 0), "z": tpos.get("z", 0), "ms": 1500}},
                    {"type": "dig", "parameters": {"x": tpos.get("x", 0), "y": tpos.get("y", 0), "z": tpos.get("z", 0)}},
                ]
            }
        # No trees found - explore in expanding directions
        cx = pos.get("x", 0)
        cz = pos.get("z", 0)
        self._explore_offset = (self._explore_offset + 1) % 8
        angles = [0, 45, 90, 135, 180, 225, 270, 315]
        angle = math.radians(angles[self._explore_offset])
        dist = 25
        tx = cx + dist * math.cos(angle)
        tz = cz + dist * math.sin(angle)
        return {
            "status": "in_progress",
            "reasoning": f"Exploring direction {angles[self._explore_offset]}deg to find trees",
            "actions": [
                {"type": "move_to", "parameters": {"x": round(tx), "z": round(tz)}},
                {"type": "wait", "parameters": {"ms": 500}},
            ]
        }

    def _plan_craft_workbench(self, inv: dict, trees: list, pos: dict) -> dict:
        if inv.get("crafting_table", 0) >= 1:
            return {"status": "complete", "reasoning": "Already have crafting table", "actions": []}
        if inv.get("oak_planks", 0) >= 4:
            return {"status": "in_progress", "reasoning": "Crafting table",
                    "actions": [{"type": "craft", "parameters": {"item": "crafting_table"}}]}
        if inv.get("oak_log", 0) >= 1:
            return {"status": "in_progress", "reasoning": "Need planks first",
                    "actions": [{"type": "craft", "parameters": {"item": "oak_planks", "count": 4}}]}
        # No wood - gather some first
        return self._plan_gather_wood(inv, trees, pos)

    def _plan_craft_wooden_pickaxe(self, inv: dict, trees: list, pos: dict) -> dict:
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
        # No wood - gather some
        return self._plan_gather_wood(inv, trees, pos)

    def _plan_mine_cobblestone(self, inv: dict) -> dict:
        if inv.get("cobblestone", 0) >= 3:
            return {"status": "complete", "reasoning": f"Have {inv.get('cobblestone', 0)} cobblestone", "actions": []}
        if inv.get("wooden_pickaxe", 0) >= 1 or inv.get("stone_pickaxe", 0) >= 1:
            return {"status": "in_progress", "reasoning": "Mining cobblestone",
                    "actions": [{"type": "dig", "parameters": {"x": -9, "y": 63, "z": 3}}]}
        return {"status": "blocked", "reasoning": "Need pickaxe to mine cobblestone", "actions": []}

    def _plan_craft_stone_pickaxe(self, inv: dict, trees: list, pos: dict) -> dict:
        if inv.get("stone_pickaxe", 0) >= 1:
            return {"status": "complete", "reasoning": "Already have", "actions": []}
        if inv.get("cobblestone", 0) >= 3 and inv.get("stick", 0) >= 2:
            return {"status": "in_progress", "reasoning": "Crafting stone pickaxe",
                    "actions": [{"type": "craft", "parameters": {"item": "stone_pickaxe"}}]}
        # Need cobblestone - mine some
        if inv.get("wooden_pickaxe", 0) >= 1 or inv.get("stone_pickaxe", 0) >= 1:
            return self._plan_mine_cobblestone(inv)
        # Need wooden pickaxe first
        if inv.get("wooden_pickaxe", 0) < 1:
            return self._plan_craft_wooden_pickaxe(inv, trees, pos)
        return {"status": "blocked", "reasoning": "Need cobblestone and sticks", "actions": []}
