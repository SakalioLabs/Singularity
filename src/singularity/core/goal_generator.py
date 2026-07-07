"""Goal generator - proposes survival goals based on world state for M4 autonomous loop."""
import logging

logger = logging.getLogger("singularity.goal_generator")


class GoalGenerator:
    """Proposes prioritized survival goals based on observation."""

    NIGHT_START = 12000
    DUSK_START = 10000
    CRITICAL_HEALTH = 6

    def next_goal(self, observation: dict) -> str:
        time = observation.get("time_of_day", 0)
        health = observation.get("health", 20)
        inv = observation.get("inventory", {})
        entities = observation.get("nearby_entities", [])
        hostiles = [e for e in entities if e.get("hostile")]

        # Priority 1: Critical threat
        if hostiles and min(e.get("distance", 999) for e in hostiles) < 8:
            if inv.get("wooden_sword") or inv.get("stone_sword") or inv.get("iron_sword"):
                return "Attack nearest hostile mob"
            return "Flee to shelter"

        # Priority 2: Critical health
        if health < self.CRITICAL_HEALTH:
            food = inv.get("bread", 0) + inv.get("cooked_porkchop", 0) + inv.get("apple", 0)
            if food > 0:
                return "Eat food to restore health"
            return "Find food"

        # Priority 3: Night preparation
        if self.DUSK_START <= time < self.NIGHT_START:
            if not inv.get("crafting_table"):
                return "Craft crafting table and build shelter"
            return "Build shelter before nightfall"

        # Priority 4: Night survival (craft/smelt during night)
        if time >= self.NIGHT_START or time < 1000:
            if inv.get("furnace") and inv.get("raw_iron"):
                return "Smelt iron ore during night"
            if inv.get("crafting_table"):
                return "Craft tools and organize inventory during night"
            return "Wait for dawn in shelter"

        # Priority 5: Tool progression
        if not inv.get("wooden_pickaxe") and inv.get("oak_log", 0) >= 3:
            return "Craft wooden pickaxe"
        if inv.get("wooden_pickaxe") and not inv.get("stone_pickaxe") and inv.get("cobblestone", 0) >= 3:
            return "Craft stone pickaxe"
        if inv.get("stone_pickaxe") and not inv.get("iron_pickaxe") and inv.get("iron_ingot", 0) >= 3:
            return "Craft iron pickaxe"

        # Priority 6: Resource gathering
        if inv.get("oak_log", 0) < 6:
            return "Gather 6 oak logs for tools and shelter"
        if not inv.get("crafting_table"):
            return "Craft crafting table"
        if not inv.get("wooden_pickaxe"):
            return "Craft wooden pickaxe"

        # Default: Explore
        return "Explore surroundings and gather resources"
