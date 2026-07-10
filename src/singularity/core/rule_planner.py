"""Rule-based fallback planner for M1 benchmarks - no LLM required."""
import math
import logging
import re

from singularity.data.knowledge_base import KnowledgeBase

logger = logging.getLogger("singularity.rule_planner")

TREE_BLOCKS = {"oak_log", "birch_log", "spruce_log", "jungle_log", "acacia_log", "dark_oak_log"}


class RuleBasedPlanner:
    """Simple rule-based planner for basic Minecraft tasks without an LLM."""

    def __init__(self, knowledge_base=None):
        self._explore_offset = 0
        self.knowledge_base = knowledge_base or KnowledgeBase()

    def plan_from_goal(self, goal: str, world_state: dict, memory_context: str = "") -> dict:
        """Plan deterministically while recording whether bounded memory was available."""
        plan = self._plan_from_goal(goal, world_state)
        if not isinstance(plan, dict):
            return plan
        result = dict(plan)
        if str(memory_context or "").strip():
            result["memory_context_available"] = True
            result["memory_context_influenced_plan"] = False
            result["reasoning"] = self._append_reasoning(
                result.get("reasoning", ""),
                "Bounded typed memory was available; deterministic rule selection remained world-state-driven",
            )
        else:
            result["memory_context_available"] = False
            result["memory_context_influenced_plan"] = False
        return result

    def _plan_from_goal(self, goal: str, world_state: dict) -> dict:
        goal_lower = goal.lower()
        inv = world_state.get("inventory", {})
        trees = world_state.get("trees_found", [])
        pos = world_state.get("position", {})

        # More specific matches first
        if "explore" in goal_lower and "frontier" in goal_lower:
            return self._plan_explore_frontier(goal, world_state, pos)
        elif "craft" in goal_lower and "pickaxe" in goal_lower and "stone" in goal_lower:
            return self._plan_craft_stone_pickaxe(inv, trees, pos, world_state)
        elif "craft" in goal_lower and "pickaxe" in goal_lower and "wooden" in goal_lower:
            return self._plan_craft_wooden_pickaxe(inv, trees, pos)
        elif "craft" in goal_lower and "table" in goal_lower:
            return self._plan_craft_workbench(inv, trees, pos)
        elif ("gather" in goal_lower or "chop" in goal_lower) and ("oak" in goal_lower or "log" in goal_lower or "wood" in goal_lower):
            return self._plan_gather_wood(inv, trees, pos, target_count=self._goal_target_count(goal_lower, 3))
        elif "cobblestone" in goal_lower or ("mine" in goal_lower and "stone" in goal_lower):
            return self._plan_mine_cobblestone(
                inv,
                trees,
                pos,
                world_state=world_state,
                target_count=self._goal_target_count(goal_lower, 3),
            )
        elif "mine" in goal_lower:
            visible_plan = self._plan_mine_visible_block(goal_lower, world_state, pos)
            if visible_plan:
                return visible_plan
            target = self._mining_target_from_goal(goal_lower)
            if target:
                return self._plan_explore_frontier(
                    f"Explore frontier and inspect {target}",
                    world_state,
                    pos,
                )
        return {"status": "blocked", "reasoning": f"No rule for goal: {goal}", "actions": []}

    def _append_reasoning(self, existing: str, addition: str) -> str:
        parts = [str(existing or "").strip(), str(addition or "").strip()]
        return "; ".join(part for part in parts if part)

    def _goal_target_count(self, goal: str, default: int) -> int:
        match = re.search(r"\b(\d+)\b", str(goal or ""))
        return max(1, int(match.group(1))) if match else max(1, int(default))

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

    def _plan_mine_visible_block(self, goal_lower: str, world_state: dict, pos: dict) -> dict:
        target = self._visible_block_named_in_goal(goal_lower, world_state)
        if not target:
            return {}
        name = target["name"]
        if target.get("can_harvest") is None:
            metadata = self.knowledge_base.describe_observed_resource(
                name,
                world_state.get("inventory", {}) if isinstance(world_state.get("inventory", {}), dict) else {},
            )
            target = dict(target)
            for key, value in metadata.items():
                if target.get(key) is None or target.get(key) == "":
                    target[key] = value
        if target.get("can_harvest") is False:
            tool = target.get("recommended_tool") or target.get("required_tool") or "better tool"
            return {
                "status": "blocked",
                "reasoning": f"Visible {name} requires {tool} before mining",
                "actions": [],
            }
        tpos = target.get("position", {})
        if not isinstance(tpos, dict) or "x" not in tpos or "z" not in tpos:
            return {
                "status": "blocked",
                "reasoning": f"Visible {name} has no grounded coordinates; observe it again before mining",
                "actions": [],
            }
        dist = target.get("distance")
        if dist is None:
            dist = self._flat_distance(pos or {}, tpos or {})
        actions = []
        if dist > 1.75:
            actions.append({
                "type": "move_to",
                "parameters": {
                    "x": round(tpos.get("x", 0)),
                    "z": round(tpos.get("z", 0)),
                    "tolerance": 1.75,
                },
            })
        actions.append({
            "type": "look_at",
            "parameters": {
                "x": round(tpos.get("x", 0)),
                "y": round(tpos.get("y", (pos or {}).get("y", 64))),
                "z": round(tpos.get("z", 0)),
            },
        })
        actions.append({
            "type": "dig",
            "parameters": {
                "x": round(tpos.get("x", 0)),
                "y": round(tpos.get("y", (pos or {}).get("y", 64))),
                "z": round(tpos.get("z", 0)),
            },
        })
        drop = target.get("drop") or name
        return {
            "status": "in_progress",
            "reasoning": f"Mining visible {name} for {drop}",
            "subtasks": [
                {
                    "title": f"Approach visible {name}",
                    "type": "navigation",
                    "priority": 1,
                    "success_criteria": {"position_near": {"x": round(tpos.get("x", 0)), "z": round(tpos.get("z", 0)), "radius": 4}},
                    "opportunity_triggers": [name],
                    "tags": ["resource", "navigation"],
                },
                {
                    "title": f"Mine visible {name}",
                    "type": "gathering",
                    "priority": 1,
                    "depends_on": [f"Approach visible {name}"],
                    "preconditions": {"nearby_block_present": [name]},
                    "success_criteria": {"inventory": {drop: 1}},
                    "opportunity_triggers": [name, drop],
                    "tags": ["resource", "mining"],
                },
            ],
            "actions": actions,
        }

    def _visible_block_named_in_goal(self, goal_lower: str, world_state: dict) -> dict:
        for key in ("grounded_resources", "nearby_blocks"):
            for item in world_state.get(key, []) or []:
                if isinstance(item, str):
                    name = item.lower()
                    if name and name in goal_lower:
                        return {"name": name, "position": {}, "distance": None}
                    continue
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or item.get("type") or item.get("block") or item.get("resource") or "").lower()
                drop = str(item.get("drop") or "").lower()
                if not name:
                    continue
                if name not in goal_lower and (not drop or drop not in goal_lower):
                    continue
                position = item.get("position", {}) if isinstance(item.get("position", {}), dict) else item
                return {
                    "name": name,
                    "drop": drop,
                    "position": position,
                    "distance": item.get("distance"),
                    "can_harvest": item.get("can_harvest"),
                    "recommended_tool": item.get("recommended_tool") or item.get("best_available_tool"),
                    "required_tool": item.get("required_tool"),
                }
        return {}

    def _mining_target_from_goal(self, goal_lower: str) -> str:
        match = re.search(r"\bmine\s+([a-z0-9_]+)", goal_lower)
        return match.group(1) if match else ""

    def _flat_distance(self, a: dict, b: dict) -> float:
        dx = float(a.get("x", 0) or 0) - float(b.get("x", 0) or 0)
        dz = float(a.get("z", 0) or 0) - float(b.get("z", 0) or 0)
        return math.sqrt(dx * dx + dz * dz)

    def _plan_gather_wood(self, inv: dict, trees: list, pos: dict, target_count: int = 3) -> dict:
        oak_logs = inv.get("oak_log", 0)
        if oak_logs >= target_count:
            return {"status": "complete", "reasoning": f"Have {oak_logs} oak logs", "actions": []}
        if trees:
            nearest = trees[0]
            tpos = nearest.get("position", {})
            dist = nearest.get("distance", 999)
            # Stand close enough that the block drop can be observed in inventory.
            if dist <= 1.75:
                return {
                    "status": "in_progress",
                    "reasoning": f"Digging {nearest['name']} at distance {dist:.1f}",
                    "actions": [
                        {"type": "dig", "parameters": {"x": tpos.get("x", 0), "y": tpos.get("y", 0), "z": tpos.get("z", 0)}},
                    ]
                }
            # Navigation must be re-observed before a dependent world-changing action.
            return {
                "status": "in_progress",
                "reasoning": f"Navigating to {nearest['name']} at {dist:.1f} blocks",
                "actions": [
                    {
                        "type": "move_to",
                        "parameters": {"x": tpos.get("x", 0), "z": tpos.get("z", 0), "tolerance": 1.75},
                    },
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

    def _plan_mine_cobblestone(
        self,
        inv: dict,
        trees: list = None,
        pos: dict = None,
        world_state: dict = None,
        target_count: int = 3,
    ) -> dict:
        if inv.get("cobblestone", 0) >= target_count:
            return {"status": "complete", "reasoning": f"Have {inv.get('cobblestone', 0)} cobblestone", "actions": []}
        if inv.get("wooden_pickaxe", 0) >= 1 or inv.get("stone_pickaxe", 0) >= 1:
            observed_state = dict(world_state or {})
            observed_state.setdefault("inventory", inv)
            observed_state.setdefault("position", pos or {})
            visible_plan = self._plan_mine_visible_block("mine stone", observed_state, pos or {})
            if visible_plan:
                visible_plan = dict(visible_plan)
                visible_plan["reasoning"] = self._append_reasoning(
                    visible_plan.get("reasoning", ""),
                    f"Need {target_count - int(inv.get('cobblestone', 0) or 0)} more cobblestone",
                )
                return visible_plan
            return {
                "status": "blocked",
                "reasoning": "No observed stone block has grounded coordinates; observe stone before mining cobblestone",
                "actions": [],
            }
        fallback = self._plan_craft_wooden_pickaxe(inv, trees or [], pos or {})
        fallback = dict(fallback)
        reasoning = fallback.get("reasoning", "")
        fallback["reasoning"] = (
            f"Need pickaxe before mining cobblestone; {reasoning}"
            if reasoning
            else "Need pickaxe before mining cobblestone"
        )
        return fallback

    def _plan_craft_stone_pickaxe(self, inv: dict, trees: list, pos: dict, world_state: dict = None) -> dict:
        if inv.get("stone_pickaxe", 0) >= 1:
            return {"status": "complete", "reasoning": "Already have", "actions": []}
        if inv.get("cobblestone", 0) >= 3 and inv.get("stick", 0) >= 2:
            return {"status": "in_progress", "reasoning": "Crafting stone pickaxe",
                    "actions": [{"type": "craft", "parameters": {"item": "stone_pickaxe"}}]}
        # Need cobblestone - mine some
        if inv.get("wooden_pickaxe", 0) >= 1 or inv.get("stone_pickaxe", 0) >= 1:
            return self._plan_mine_cobblestone(inv, trees, pos, world_state=world_state, target_count=3)
        # Need wooden pickaxe first
        if inv.get("wooden_pickaxe", 0) < 1:
            return self._plan_craft_wooden_pickaxe(inv, trees, pos)
        return {"status": "blocked", "reasoning": "Need cobblestone and sticks", "actions": []}
