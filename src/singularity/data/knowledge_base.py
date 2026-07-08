"""Knowledge base loader - loads Minecraft domain knowledge for LLM planning."""
import json
import os
import logging
import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("singularity.knowledge")

_DATA_DIR = os.path.dirname(__file__)


RESOURCE_DROPS = {
    "oak_log": "oak_log",
    "birch_log": "birch_log",
    "spruce_log": "spruce_log",
    "jungle_log": "jungle_log",
    "acacia_log": "acacia_log",
    "dark_oak_log": "dark_oak_log",
    "stone": "cobblestone",
    "coal_ore": "coal",
    "iron_ore": "raw_iron",
    "copper_ore": "raw_copper",
    "diamond_ore": "diamond",
    "dirt": "dirt",
    "sand": "sand",
    "gravel": "gravel",
}

TOOL_ROLES = {
    "pickaxe": ("stone", "cobblestone", "ore", "coal", "diamond", "gold"),
    "axe": ("log", "planks", "wood"),
    "shovel": ("dirt", "sand", "gravel", "clay"),
}


@dataclass
class KnowledgeEdge:
    """A small directed fact in the Minecraft item/block knowledge graph."""

    source: str
    relation: str
    target: str
    metadata: dict = field(default_factory=dict)


class MinecraftKnowledgeGraph:
    """Lightweight graph over recipes, tools, resources, and mineable blocks."""

    def __init__(self, recipes: dict, tool_progression: list, resource_drops: Optional[dict] = None):
        self.recipes = recipes
        self.tool_progression = tool_progression
        self.resource_drops = resource_drops or RESOURCE_DROPS
        self.nodes: set[str] = set()
        self.node_types: dict[str, set[str]] = defaultdict(set)
        self.edges: list[KnowledgeEdge] = []
        self.out_edges: dict[str, list[KnowledgeEdge]] = defaultdict(list)
        self.in_edges: dict[str, list[KnowledgeEdge]] = defaultdict(list)
        self.tool_tiers: dict[str, int] = {}
        self.mine_tiers: dict[str, int] = {}
        self._build()

    def neighbors(self, node: str, relation: Optional[str] = None) -> list[KnowledgeEdge]:
        edges = self.out_edges.get(node, [])
        if relation:
            return [edge for edge in edges if edge.relation == relation]
        return list(edges)

    def raw_requirements(self, item: str, count: int = 1) -> dict[str, int]:
        """Return terminal raw resources required to craft an item."""
        return self._raw_requirements(item, count, seen=set())

    def recipe_steps(self, item: str) -> list[dict]:
        """Return dependency-ordered craft steps for an item."""
        steps = []
        self._collect_recipe_steps(item, steps, seen=set())
        return steps

    def resource_plan(self, item: str, inventory: dict) -> dict:
        """Summarize missing resources, source blocks, and craft steps."""
        raw = self.raw_requirements(item)
        missing_raw = {
            name: max(0, count - inventory.get(name, 0))
            for name, count in raw.items()
        }
        missing_raw = {name: count for name, count in missing_raw.items() if count > 0}
        return {
            "target": item,
            "raw_requirements": raw,
            "missing_raw": missing_raw,
            "source_blocks": {
                name: self.source_blocks_for_resource(name)
                for name in missing_raw
            },
            "craft_steps": self.recipe_steps(item),
        }

    def source_blocks_for_resource(self, resource: str) -> list[str]:
        sources = [
            edge.source
            for edge in self.in_edges.get(resource, [])
            if edge.relation == "drops"
        ]
        if sources:
            return sorted(sources)
        if resource not in self.recipes:
            return [resource]
        return []

    def required_tool_tier(self, block_or_resource: str) -> int:
        if block_or_resource in self.mine_tiers:
            return self.mine_tiers[block_or_resource]
        drop = self.resource_drops.get(block_or_resource)
        if drop and drop in self.mine_tiers:
            return self.mine_tiers[drop]
        return 0

    def recommended_tool_for(self, block_or_resource: str) -> str:
        tier = self.required_tool_tier(block_or_resource)
        role = self._preferred_tool_role(block_or_resource)
        candidates = [
            tool
            for tool, tool_tier in self.tool_tiers.items()
            if tool_tier == tier and self._tool_matches_role(tool, role)
        ]
        if candidates:
            return sorted(candidates)[0]
        candidates = [tool for tool, tool_tier in self.tool_tiers.items() if tool_tier == tier]
        return sorted(candidates)[0] if candidates else "hand"

    def best_available_tool(self, block_or_resource: str, inventory: dict) -> Optional[str]:
        required = self.required_tool_tier(block_or_resource)
        role = self._preferred_tool_role(block_or_resource)
        candidates = [
            (tool_tier, tool)
            for tool, tool_tier in self.tool_tiers.items()
            if inventory.get(tool, 0) > 0
            and tool_tier >= required
            and self._tool_matches_role(tool, role)
        ]
        if not candidates and required == 0:
            return "hand"
        if not candidates:
            return None
        return sorted(candidates, reverse=True)[0][1]

    def can_mine(self, block_or_resource: str, inventory: dict) -> bool:
        return self.best_available_tool(block_or_resource, inventory) is not None

    def crafting_uses_for(self, resource: str) -> list[str]:
        """Return known craft targets that directly consume a resource."""
        uses = [
            edge.target
            for edge in self.neighbors(resource, "crafts_into")
        ]
        return sorted(set(uses))

    def format_summary(self, max_lines: int = 16) -> str:
        lines = ["Knowledge Graph:"]
        for block in ("oak_log", "stone", "coal_ore", "iron_ore", "diamond_ore"):
            drop = self.resource_drops.get(block, block)
            tool = self.recommended_tool_for(block)
            tier = self.required_tool_tier(block)
            lines.append(f"  {block} drops {drop}; min tool tier {tier}; recommended {tool}")
        for item in ("crafting_table", "wooden_pickaxe", "stone_pickaxe", "torch", "furnace"):
            if item in self.recipes:
                raw = self.raw_requirements(item)
                raw_str = ", ".join(f"{count}x {name}" for name, count in raw.items())
                lines.append(f"  {item} raw needs: {raw_str}")
        return "\n".join(lines[:max_lines])

    def _build(self):
        for item, recipe in self.recipes.items():
            self._tag_node(item, "item")
            category = recipe.get("category")
            if category:
                self._tag_node(item, category)
            for ingredient, count in recipe.get("ingredients", {}).items():
                self._tag_node(ingredient, "item")
                self._add_edge(item, "requires", ingredient, {"count": count, "output": recipe.get("output", 1)})
                self._add_edge(ingredient, "crafts_into", item, {"count": count, "output": recipe.get("output", 1)})

        for tier in self.tool_progression:
            tier_num = int(tier.get("tier", 0))
            for tool in tier.get("items", []):
                self.tool_tiers[tool] = tier_num
                self._tag_node(tool, "tool")
                self._add_edge(tool, "has_tier", f"tier:{tier_num}")
                for block in tier.get("can_mine", []):
                    self.mine_tiers[block] = min(tier_num, self.mine_tiers.get(block, tier_num))
                    self._tag_node(block, "block")
                    self._add_edge(tool, "can_mine", block, {"tier": tier_num})

        for block, drop in self.resource_drops.items():
            self._tag_node(block, "block")
            self._tag_node(drop, "item")
            self._add_edge(block, "drops", drop)

    def _add_edge(self, source: str, relation: str, target: str, metadata: Optional[dict] = None):
        self.nodes.update([source, target])
        edge = KnowledgeEdge(source, relation, target, metadata or {})
        self.edges.append(edge)
        self.out_edges[source].append(edge)
        self.in_edges[target].append(edge)

    def _tag_node(self, node: str, node_type: str):
        self.nodes.add(node)
        self.node_types[node].add(node_type)

    def _raw_requirements(self, item: str, count: int, seen: set[str]) -> dict[str, int]:
        if item in seen or item not in self.recipes:
            return {item: count}
        seen.add(item)
        recipe = self.recipes[item]
        output = max(1, int(recipe.get("output", 1)))
        batches = math.ceil(count / output)
        raw: dict[str, int] = defaultdict(int)
        for ingredient, ingredient_count in recipe.get("ingredients", {}).items():
            needed = int(ingredient_count) * batches
            for raw_item, raw_count in self._raw_requirements(ingredient, needed, seen.copy()).items():
                raw[raw_item] += raw_count
        return dict(raw)

    def _collect_recipe_steps(self, item: str, steps: list[dict], seen: set[str]):
        if item in seen or item not in self.recipes:
            return
        seen.add(item)
        recipe = self.recipes[item]
        for ingredient in recipe.get("ingredients", {}):
            self._collect_recipe_steps(ingredient, steps, seen)
        steps.append({
            "item": item,
            "ingredients": recipe.get("ingredients", {}),
            "output": recipe.get("output", 1),
        })

    def _preferred_tool_role(self, block_or_resource: str) -> str:
        name = block_or_resource.lower()
        for role, tokens in TOOL_ROLES.items():
            if any(token in name for token in tokens):
                return role
        return ""

    def _tool_matches_role(self, tool: str, role: str) -> bool:
        if tool == "hand":
            return True
        return not role or role in tool


class KnowledgeBase:
    """Loads and provides access to Minecraft domain knowledge."""

    def __init__(self):
        self.recipes: dict = {}
        self.tool_progression: list = []
        self.survival_guide: list = []
        self.graph: MinecraftKnowledgeGraph | None = None
        self._load()

    def _load(self):
        path = os.path.join(_DATA_DIR, 'crafting_recipes.json')
        try:
            with open(path, 'r', encoding='utf-8-sig') as f:
                data = json.load(f)
            self.recipes = data.get('recipes', {})
            self.tool_progression = data.get('tool_progression', [])
            self.survival_guide = data.get('survival_first_night', [])
            self.graph = MinecraftKnowledgeGraph(self.recipes, self.tool_progression)
            logger.info(f"Loaded {len(self.recipes)} recipes, {len(self.tool_progression)} tool tiers")
        except Exception as e:
            logger.warning(f"Could not load crafting recipes: {e}")

    def get_recipe(self, item: str) -> dict | None:
        return self.recipes.get(item)

    def get_ingredients(self, item: str) -> dict:
        recipe = self.recipes.get(item)
        if recipe:
            return recipe.get('ingredients', {})
        return {}

    def can_craft(self, item: str, inventory: dict) -> bool:
        """Check if an item can be crafted given current inventory."""
        ingredients = self.get_ingredients(item)
        if not ingredients:
            return False
        for mat, count in ingredients.items():
            if inventory.get(mat, 0) < count:
                return False
        return True

    def get_craftable_items(self, inventory: dict) -> list[str]:
        """Return list of items that can be crafted from current inventory."""
        craftable = []
        for item in self.recipes:
            if self.can_craft(item, inventory):
                craftable.append(item)
        return craftable

    def list_recipes(self) -> list[str]:
        """Return list of all known recipe names."""
        return list(self.recipes.keys())

    def can_mine(self, block_or_resource: str, inventory: dict) -> bool:
        """Check whether the current inventory can mine a block/resource."""
        return bool(self.graph and self.graph.can_mine(block_or_resource, inventory))

    def required_tool_tier(self, block_or_resource: str) -> int:
        """Return the minimum known tool tier for mining a block/resource."""
        return self.graph.required_tool_tier(block_or_resource) if self.graph else 0

    def recommended_tool_for(self, block_or_resource: str) -> str:
        """Return the minimum recommended tool for a block/resource."""
        return self.graph.recommended_tool_for(block_or_resource) if self.graph else "hand"

    def source_blocks_for_resource(self, resource: str) -> list[str]:
        """Return known blocks that produce a resource."""
        if not self.graph:
            return [resource]
        return self.graph.source_blocks_for_resource(resource)

    def describe_observed_resource(self, block_or_resource: str, inventory: Optional[dict] = None) -> dict:
        """Return graph-backed mining and crafting metadata for a visible block/resource."""
        inventory = inventory or {}
        if not self.graph:
            return {
                "drop": block_or_resource,
                "required_tool_tier": 0,
                "recommended_tool": "hand",
                "best_available_tool": "hand",
                "can_harvest": True,
                "source_blocks": [block_or_resource],
                "crafts_into": [],
                "known_to_graph": False,
            }

        drop = self.graph.resource_drops.get(block_or_resource, block_or_resource)
        best_tool = self.graph.best_available_tool(block_or_resource, inventory)
        return {
            "drop": drop,
            "required_tool_tier": self.graph.required_tool_tier(block_or_resource),
            "recommended_tool": self.graph.recommended_tool_for(block_or_resource),
            "best_available_tool": best_tool,
            "can_harvest": best_tool is not None,
            "source_blocks": self.graph.source_blocks_for_resource(drop),
            "crafts_into": self.graph.crafting_uses_for(drop),
            "known_to_graph": block_or_resource in self.graph.nodes or drop in self.graph.nodes,
        }

    def get_resource_plan(self, item: str, inventory: Optional[dict] = None) -> dict:
        """Return raw resource gaps, source blocks, and craft steps for an item."""
        if not self.graph:
            return {"target": item, "raw_requirements": {}, "missing_raw": {}, "source_blocks": {}, "craft_steps": []}
        return self.graph.resource_plan(item, inventory or {})

    def get_recipe_chain(self, item: str, depth: int = 0) -> list:
        """Get full recipe chain showing all required raw materials."""
        if depth > 5:
            return [{"item": item, "note": "deep recursion"}]
        recipe = self.recipes.get(item)
        if not recipe:
            return [{"item": item, "source": "raw material"}]
        chain = []
        for mat, count in recipe.get('ingredients', {}).items():
            sub_chain = self.get_recipe_chain(mat, depth + 1)
            chain.append({"item": mat, "count": count, "chain": sub_chain})
        return chain

    def format_for_prompt(self, max_items: int = 20) -> str:
        """Format recipes as compact text for LLM prompts."""
        lines = ["Key Recipes:"]
        priority_items = [
            "oak_planks", "stick", "crafting_table", "wooden_pickaxe", "wooden_axe",
            "stone_pickaxe", "stone_axe", "iron_pickaxe", "furnace", "torch",
            "chest", "bed", "shield"
        ]
        for item in priority_items[:max_items]:
            recipe = self.recipes.get(item)
            if recipe:
                ingredients = recipe['ingredients']
                ing_str = ", ".join(f"{v}x {k}" for k, v in ingredients.items())
                lines.append(f"  {item}: {ing_str} -> {recipe['output']}x {item}")
        if self.graph:
            lines.append("")
            lines.append(self.graph.format_summary(max_lines=10))
        return "\n".join(lines)

    def format_knowledge_graph_for_prompt(self, max_lines: int = 16) -> str:
        """Format graph-derived mining and dependency facts for prompts."""
        return self.graph.format_summary(max_lines=max_lines) if self.graph else ""
