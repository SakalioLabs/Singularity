"""Goal generator - proposes survival goals based on world state for M4 autonomous loop."""
import logging

from singularity.evaluation.m4_shelter import is_machine_verified_shelter

logger = logging.getLogger("singularity.goal_generator")


class GoalGenerator:
    """Proposes prioritized survival goals based on observation."""

    NIGHT_START = 12000
    NIGHT_END = 23000
    DUSK_START = 10000
    CRITICAL_HEALTH = 6
    LOW_HUNGER = 8
    FOOD_ITEMS = (
        "bread", "apple", "cooked_porkchop", "cooked_beef", "cooked_chicken",
        "baked_potato", "carrot", "potato", "beef", "porkchop", "melon_slice",
    )
    WEAPON_ITEMS = (
        "wooden_sword", "stone_sword", "iron_sword", "diamond_sword",
        "wooden_axe", "stone_axe", "iron_axe", "diamond_axe",
    )

    def __init__(self):
        self.last_decision: dict = {}

    def next_goal(self, observation: dict, task_id: str = "") -> str:
        observation = observation if isinstance(observation, dict) else {}
        time_of_day = self._normalized_time(observation.get("time_of_day", 0))
        health = self._number(observation.get("health", 20), 20.0)
        hunger = self._number(observation.get("hunger", observation.get("food", 20)), 20.0)
        inv = observation.get("inventory", {}) if isinstance(observation.get("inventory"), dict) else {}
        entities = observation.get("nearby_entities", [])
        entities = entities if isinstance(entities, list) else []
        hostiles = [entity for entity in entities if isinstance(entity, dict) and entity.get("hostile")]
        nearby_hostiles = [
            entity for entity in hostiles
            if self._number(entity.get("distance", 999), 999.0) <= 8.0
        ]
        food_count = sum(self._count(inv.get(item, 0)) for item in self.FOOD_ITEMS)
        shelter_verified = self._has_verified_shelter(observation)

        # Priority 1: immediate hostile threat.
        if nearby_hostiles:
            if any(self._count(inv.get(item, 0)) > 0 for item in self.WEAPON_ITEMS):
                return self._select(
                    "Attack nearest hostile mob",
                    1,
                    "immediate_threat",
                    "hostile_within_8_blocks_weapon_available",
                    time_of_day,
                    health,
                    hunger,
                    shelter_verified,
                )
            return self._select(
                "Flee from the nearest hostile mob toward safety",
                1,
                "immediate_threat",
                "hostile_within_8_blocks_no_weapon",
                time_of_day,
                health,
                hunger,
                shelter_verified,
            )

        # Priority 2: critical health.
        if health < self.CRITICAL_HEALTH:
            if food_count > 0:
                return self._select(
                    "Eat available food to recover critical health",
                    2,
                    "critical_health",
                    "health_below_critical_food_available",
                    time_of_day,
                    health,
                    hunger,
                    shelter_verified,
                )
            return self._select(
                "Find food and avoid danger until health can recover",
                2,
                "critical_health",
                "health_below_critical_no_food",
                time_of_day,
                health,
                hunger,
                shelter_verified,
            )

        # Priority 3: hunger and food acquisition.
        if hunger <= self.LOW_HUNGER:
            if food_count > 0:
                return self._select(
                    "Eat available food to restore hunger",
                    3,
                    "hunger_food",
                    "hunger_low_food_available",
                    time_of_day,
                    health,
                    hunger,
                    shelter_verified,
                )
            return self._select(
                "Find food and gather a safe supply before continuing",
                3,
                "hunger_food",
                "hunger_low_no_food",
                time_of_day,
                health,
                hunger,
                shelter_verified,
            )

        # Priority 4: secure shelter before or during the hostile window.
        if self.DUSK_START <= time_of_day < self.NIGHT_START and not shelter_verified:
            return self._select(
                "Build verified shelter before nightfall",
                4,
                "shelter_preparation",
                "dusk_without_machine_verified_shelter",
                time_of_day,
                health,
                hunger,
                shelter_verified,
            )
        if self.NIGHT_START <= time_of_day < self.NIGHT_END and not shelter_verified:
            return self._select(
                "Reach or build emergency verified shelter immediately",
                4,
                "shelter_preparation",
                "night_without_machine_verified_shelter",
                time_of_day,
                health,
                hunger,
                shelter_verified,
            )

        # Priority 5: maintain a machine-verified safe state through night.
        if self.DUSK_START <= time_of_day < self.NIGHT_START and shelter_verified:
            return self._select(
                "Enter and maintain verified shelter through nightfall",
                5,
                "night_safety_maintenance",
                "dusk_with_machine_verified_shelter",
                time_of_day,
                health,
                hunger,
                shelter_verified,
            )
        if self.NIGHT_START <= time_of_day < self.NIGHT_END and shelter_verified:
            return self._select(
                "Remain in verified shelter until dawn",
                5,
                "night_safety_maintenance",
                "night_with_machine_verified_shelter",
                time_of_day,
                health,
                hunger,
                shelter_verified,
            )

        # Priority 6: tool and resource progression.
        if str(task_id or "").upper().strip() == "BM-012":
            return self._bm012_progression(
                observation,
                inv,
                time_of_day,
                health,
                hunger,
                shelter_verified,
            )
        if not inv.get("wooden_pickaxe") and inv.get("oak_log", 0) >= 3:
            return self._progression("Craft wooden pickaxe", "wood_ready_for_first_pickaxe", time_of_day, health, hunger, shelter_verified)
        if inv.get("wooden_pickaxe") and not inv.get("stone_pickaxe") and inv.get("cobblestone", 0) >= 3:
            return self._progression("Craft stone pickaxe", "stone_ready_for_tool_upgrade", time_of_day, health, hunger, shelter_verified)
        if inv.get("stone_pickaxe") and not inv.get("iron_pickaxe") and inv.get("iron_ingot", 0) >= 3:
            return self._progression("Craft iron pickaxe", "iron_ready_for_tool_upgrade", time_of_day, health, hunger, shelter_verified)

        if inv.get("oak_log", 0) < 6:
            return self._progression("Gather 6 oak logs for tools and shelter", "wood_reserve_below_target", time_of_day, health, hunger, shelter_verified)
        if not inv.get("crafting_table"):
            return self._progression("Craft crafting table", "crafting_table_missing", time_of_day, health, hunger, shelter_verified)
        if not inv.get("wooden_pickaxe"):
            return self._progression("Craft wooden pickaxe", "wooden_pickaxe_missing", time_of_day, health, hunger, shelter_verified)

        return self._progression(
            "Explore surroundings and gather resources",
            "basic_progression_ready",
            time_of_day,
            health,
            hunger,
            shelter_verified,
        )

    def _bm012_progression(
        self,
        observation: dict,
        inventory: dict,
        time_of_day: int,
        health: float,
        hunger: float,
        shelter_verified: bool,
    ) -> str:
        if self._count(inventory.get("raw_iron")) >= 8 or self._count(inventory.get("iron_ore")) >= 8:
            return self._progression(
                "Confirm collection of 8 iron resources",
                "bm012_inventory_target_reached",
                time_of_day,
                health,
                hunger,
                shelter_verified,
            )
        if self._count(inventory.get("oak_log")) < 6:
            return self._progression(
                "Gather 6 oak logs for iron-tool progression",
                "bm012_wood_reserve_below_target",
                time_of_day,
                health,
                hunger,
                shelter_verified,
            )
        nearby_blocks = observation.get("nearby_blocks", [])
        nearby_blocks = nearby_blocks if isinstance(nearby_blocks, list) else []
        table_available = self._count(inventory.get("crafting_table")) > 0 or any(
            isinstance(block, dict) and block.get("name") == "crafting_table"
            for block in nearby_blocks
        )
        if not table_available:
            return self._progression(
                "Craft and place a crafting table for iron-tool progression",
                "bm012_crafting_table_missing",
                time_of_day,
                health,
                hunger,
                shelter_verified,
            )
        if self._count(inventory.get("wooden_pickaxe")) < 1:
            return self._progression(
                "Craft a wooden pickaxe for stone acquisition",
                "bm012_wooden_pickaxe_missing",
                time_of_day,
                health,
                hunger,
                shelter_verified,
            )
        if self._count(inventory.get("stone_pickaxe")) < 1:
            if self._count(inventory.get("cobblestone")) < 3:
                return self._progression(
                    "Gather 3 cobblestone with the wooden pickaxe",
                    "bm012_cobblestone_below_stone_pickaxe_requirement",
                    time_of_day,
                    health,
                    hunger,
                    shelter_verified,
                )
            return self._progression(
                "Craft a stone pickaxe for mining iron ore",
                "bm012_stone_pickaxe_ready_to_craft",
                time_of_day,
                health,
                hunger,
                shelter_verified,
            )
        return self._progression(
            "Collect 8 raw iron from iron ore with the stone pickaxe",
            "bm012_stone_pickaxe_ready_for_iron",
            time_of_day,
            health,
            hunger,
            shelter_verified,
        )

    def _progression(self, goal, reason, time_of_day, health, hunger, shelter_verified):
        return self._select(
            goal,
            6,
            "tool_resource_progression",
            reason,
            time_of_day,
            health,
            hunger,
            shelter_verified,
        )

    def _select(
        self,
        goal: str,
        priority: int,
        priority_class: str,
        reason: str,
        time_of_day: int,
        health: float,
        hunger: float,
        shelter_verified: bool,
    ) -> str:
        self.last_decision = {
            "goal": goal,
            "selection_source": "goal_generator",
            "selection_reason": reason,
            "priority": int(priority),
            "priority_class": priority_class,
            "time_of_day": time_of_day,
            "health": health,
            "hunger": hunger,
            "shelter_verified": shelter_verified,
        }
        return goal

    @staticmethod
    def _has_verified_shelter(observation: dict) -> bool:
        return is_machine_verified_shelter(observation.get("shelter_verification"))

    @staticmethod
    def _normalized_time(value) -> int:
        try:
            return int(float(value)) % 24000
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _number(value, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    @staticmethod
    def _count(value) -> int:
        try:
            return max(0, int(value or 0))
        except (TypeError, ValueError):
            return 0
