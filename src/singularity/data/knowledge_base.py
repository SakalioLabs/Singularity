"""Knowledge base loader - loads Minecraft domain knowledge for LLM planning."""
import json
import os
import logging

logger = logging.getLogger("singularity.knowledge")

_DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')


class KnowledgeBase:
    """Loads and provides access to Minecraft domain knowledge."""

    def __init__(self):
        self.recipes: dict = {}
        self.tool_progression: list = []
        self.survival_guide: list = []
        self._load()

    def _load(self):
        path = os.path.join(_DATA_DIR, 'crafting_recipes.json')
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.recipes = data.get('recipes', {})
            self.tool_progression = data.get('tool_progression', [])
            self.survival_guide = data.get('survival_first_night', [])
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

    def get_recipe_chain(self, item: str, depth: int = 0) -> dict:
        """Get full recipe chain showing all required raw materials."""
        if depth > 5:
            return {item: "deep recursion"}
        recipe = self.recipes.get(item)
        if not recipe:
            return {item: "raw material"}
        chain = {}
        for mat, count in recipe.get('ingredients', {}).items():
            sub_chain = self.get_recipe_chain(mat, depth + 1)
            chain[mat] = {"count": count, "chain": sub_chain}
        return {item: chain}

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
        return "\n".join(lines)
