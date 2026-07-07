"""Observation module - reads game state from the bot bridge and produces structured observations."""
import logging

logger = logging.getLogger("singularity.observation")

TREE_BLOCKS = {"oak_log", "birch_log", "spruce_log", "jungle_log", "acacia_log", "dark_oak_log"}


class Observer:
    """Collects and structures game state observations from the Minecraft bot."""

    def __init__(self, bot):
        self.bot = bot

    def observe(self, mode: str = "normal") -> dict:
        obs = {}
        player = self.bot.get_player_state()
        obs.update({
            "position": player.get("position", {}),
            "health": player.get("health", 20),
            "hunger": player.get("food", 20),
            "xp_level": player.get("experience", {}).get("level", 0),
            "yaw": player.get("yaw", 0),
            "pitch": player.get("pitch", 0),
        })
        inventory = self.bot.get_inventory()
        obs["inventory"] = self._summarize_inventory(inventory)
        obs["inventory_count"] = len(inventory)
        if mode in ("normal", "deep"):
            entities = self.bot.get_nearby_entities(radius=32)
            obs["nearby_entities"] = self._summarize_entities(entities)
            obs["time_of_day"] = self.bot.get_time()
            obs["is_daytime"] = 0 <= obs["time_of_day"] < 12000 or obs["time_of_day"] >= 23000
            obs["weather"] = self.bot.get_weather()
            # Small scan for general context
            blocks_near = self.bot.get_nearby_blocks(radius=8)
            obs["nearby_blocks"] = blocks_near[:50]
            # Dedicated tree scanner at larger radius
            obs["trees_found"] = self.bot.get_nearby_trees(radius=32)
            obs["ground_block"] = self.bot.get_block_below()
        if mode == "deep":
            obs["biome"] = self.bot.get_biome()
            obs["light_level"] = self.bot.get_light_level()
            obs["visible_dangers"] = self._identify_dangers(obs.get("nearby_entities", []))
        return obs

    def _summarize_inventory(self, inventory: list) -> dict:
        summary = {}
        for item in inventory:
            name = item.get("name", "unknown")
            count = item.get("count", 1)
            summary[name] = summary.get(name, 0) + count
        return summary

    def _summarize_entities(self, entities: list) -> list:
        summarized = []
        for e in entities:
            summarized.append({
                "type": e.get("name", "unknown"),
                "distance": round(e.get("distance", 0), 1),
                "hostile": e.get("hostile", False),
                "health": e.get("health"),
            })
        summarized.sort(key=lambda x: x["distance"])
        return summarized[:20]

    def _identify_dangers(self, entities: list) -> list:
        dangers = []
        hostile_types = {"zombie", "skeleton", "creeper", "spider", "enderman", "witch", "phantom"}
        for e in entities:
            name = e.get("type", "").lower()
            if e.get("hostile") or name in hostile_types:
                dangers.append({"type": e.get("type"), "distance": e.get("distance")})
        return dangers
