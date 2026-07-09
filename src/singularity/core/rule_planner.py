"""Rule-based fallback planner for M1 benchmarks - no LLM required."""
import math
import logging
import re

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
        if "explore" in goal_lower and "frontier" in goal_lower:
            return self._plan_explore_frontier(goal, world_state, pos)
        elif "craft" in goal_lower and "pickaxe" in goal_lower and "stone" in goal_lower:
            return self._plan_craft_stone_pickaxe(inv, trees, pos)
        elif "craft" in goal_lower and "pickaxe" in goal_lower and "wooden" in goal_lower:
            return self._plan_craft_wooden_pickaxe(inv, trees, pos)
        elif "craft" in goal_lower and "table" in goal_lower:
            return self._plan_craft_workbench(inv, trees, pos)
        elif ("gather" in goal_lower or "chop" in goal_lower) and ("oak" in goal_lower or "log" in goal_lower or "wood" in goal_lower):
            return self._plan_gather_wood(inv, trees, pos)
        elif "cobblestone" in goal_lower or ("mine" in goal_lower and "stone" in goal_lower):
            return self._plan_mine_cobblestone(inv, trees, pos)
        return {"status": "blocked", "reasoning": f"No rule for goal: {goal}", "actions": []}

    def _plan_explore_frontier(self, goal: str, world_state: dict, pos: dict) -> dict:
        target = self._frontier_target(goal, pos)
        resource = self._frontier_resource(goal)
        dist = self._flat_distance(pos, target)
        actions = []
        if dist > 4.0:
            actions.append({"type": "move_to", "parameters": {"x": round(target["x"]), "z": round(target["z"])}})
        look_target = self._visible_resource_position(resource, world_state) if resource else {}
        if not look_target:
            look_target = {"x": target["x"], "y": pos.get("y", 64), "z": target["z"]}
        actions.append({
            "type": "look_at",
            "parameters": {
                "x": round(look_target.get("x", target["x"])),
                "y": round(look_target.get("y", pos.get("y", 64))),
                "z": round(look_target.get("z", target["z"])),
            },
        })
        actions.append({"type": "wait", "parameters": {"ms": 600}})
        resource_text = f" and inspect {resource}" if resource else ""
        return {
            "status": "in_progress",
            "reasoning": (
                f"Following mapped frontier evidence toward x={round(target['x'])}, "
                f"z={round(target['z'])}{resource_text}"
            ),
            "subtasks": [
                {
                    "title": "Navigate to mapped frontier",
                    "type": "exploration",
                    "priority": 1,
                    "success_criteria": {"position_near": {"x": round(target["x"]), "z": round(target["z"])}},
                    "opportunity_triggers": ["frontier"],
                    "tags": ["frontier", "navigation"],
                    "rationale": "Use structured world-model frontier feedback before random exploration",
                },
                {
                    "title": f"Inspect frontier {resource or 'landmarks'}",
                    "type": "exploration",
                    "priority": 2,
                    "success_criteria": {"observed": resource or "landmark"},
                    "depends_on": ["Navigate to mapped frontier"],
                    "opportunity_triggers": [resource] if resource else ["landmark"],
                    "tags": ["frontier", "inspection"],
                    "rationale": "Record visible resources and risk before interacting",
                },
            ],
            "actions": actions,
        }

    def _frontier_target(self, goal: str, pos: dict) -> dict:
        coord_match = re.search(
            r"near\s+x\s*=\s*(-?\d+(?:\.\d+)?)\s*,\s*z\s*=\s*(-?\d+(?:\.\d+)?)",
            goal,
            flags=re.IGNORECASE,
        )
        if coord_match:
            return {"x": float(coord_match.group(1)), "z": float(coord_match.group(2))}
        direction = self._frontier_direction(goal)
        offsets = {
            "east": (24, 0),
            "west": (-24, 0),
            "south": (0, 24),
            "north": (0, -24),
            "southeast": (18, 18),
            "southwest": (-18, 18),
            "northeast": (18, -18),
            "northwest": (-18, -18),
        }
        dx, dz = offsets.get(direction, (20, 20))
        return {"x": float(pos.get("x", 0) or 0) + dx, "z": float(pos.get("z", 0) or 0) + dz}

    def _frontier_direction(self, goal: str) -> str:
        text = goal.lower()
        for direction in ("southeast", "southwest", "northeast", "northwest", "east", "west", "south", "north"):
            if direction in text:
                return direction
        return ""

    def _frontier_resource(self, goal: str) -> str:
        match = re.search(r"(?:inspect|check|observe)\s+([a-zA-Z0-9_]+)", goal)
        if match:
            return match.group(1).lower()
        return ""

    def _visible_resource_position(self, resource: str, world_state: dict) -> dict:
        if not resource:
            return {}
        for key in ("nearby_blocks", "grounded_resources"):
            for item in world_state.get(key, []) or []:
                if isinstance(item, str) or not isinstance(item, dict):
                    continue
                name = str(item.get("name") or item.get("type") or item.get("block") or item.get("resource") or "").lower()
                if name != resource:
                    continue
                position = item.get("position", {}) if isinstance(item.get("position", {}), dict) else item
                return {
                    "x": position.get("x", 0),
                    "y": position.get("y", world_state.get("position", {}).get("y", 64)),
                    "z": position.get("z", 0),
                }
        return {}

    def _flat_distance(self, a: dict, b: dict) -> float:
        dx = float(a.get("x", 0) or 0) - float(b.get("x", 0) or 0)
        dz = float(a.get("z", 0) or 0) - float(b.get("z", 0) or 0)
        return math.sqrt(dx * dx + dz * dz)

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

    def _plan_mine_cobblestone(self, inv: dict, trees: list = None, pos: dict = None) -> dict:
        if inv.get("cobblestone", 0) >= 3:
            return {"status": "complete", "reasoning": f"Have {inv.get('cobblestone', 0)} cobblestone", "actions": []}
        if inv.get("wooden_pickaxe", 0) >= 1 or inv.get("stone_pickaxe", 0) >= 1:
            return {"status": "in_progress", "reasoning": "Mining cobblestone",
                    "actions": [{"type": "dig", "parameters": {"x": -9, "y": 63, "z": 3}}]}
        fallback = self._plan_craft_wooden_pickaxe(inv, trees or [], pos or {})
        fallback = dict(fallback)
        reasoning = fallback.get("reasoning", "")
        fallback["reasoning"] = (
            f"Need pickaxe before mining cobblestone; {reasoning}"
            if reasoning
            else "Need pickaxe before mining cobblestone"
        )
        return fallback

    def _plan_craft_stone_pickaxe(self, inv: dict, trees: list, pos: dict) -> dict:
        if inv.get("stone_pickaxe", 0) >= 1:
            return {"status": "complete", "reasoning": "Already have", "actions": []}
        if inv.get("cobblestone", 0) >= 3 and inv.get("stick", 0) >= 2:
            return {"status": "in_progress", "reasoning": "Crafting stone pickaxe",
                    "actions": [{"type": "craft", "parameters": {"item": "stone_pickaxe"}}]}
        # Need cobblestone - mine some
        if inv.get("wooden_pickaxe", 0) >= 1 or inv.get("stone_pickaxe", 0) >= 1:
            return self._plan_mine_cobblestone(inv, trees, pos)
        # Need wooden pickaxe first
        if inv.get("wooden_pickaxe", 0) < 1:
            return self._plan_craft_wooden_pickaxe(inv, trees, pos)
        return {"status": "blocked", "reasoning": "Need cobblestone and sticks", "actions": []}
