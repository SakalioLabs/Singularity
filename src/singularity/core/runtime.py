"""Runtime supervisor for interruptible planner/actor execution."""
import math
import time
from dataclasses import dataclass, field
from typing import Optional

from singularity.core.config import Config
from singularity.core.goal_generator import GoalGenerator
from singularity.evaluation.m4_shelter import is_machine_verified_shelter


@dataclass
class InterruptDecision:
    """Decision emitted when the actor loop should yield or re-prioritize."""

    should_interrupt: bool
    reason: str = ""
    priority: int = 0
    recommended_goal: str = ""
    emergency_action: Optional[dict] = None
    evidence: dict = field(default_factory=dict)


class RuntimeSupervisor:
    """Evaluates fast actor-side interrupts between planner cycles."""

    SURVIVAL_INTERRUPT_REASONS = frozenset({
        "hostile_nearby",
        "health_critical",
        "hunger_critical",
        "dusk_shelter_required",
        "night_shelter_required",
        "night_safety_maintenance",
    })

    def __init__(self, config: Config, explorer=None):
        self.config = config
        self.explorer = explorer

    def evaluate_interrupt(self, observation: dict, goal: str = "", active_task=None) -> InterruptDecision:
        """Return the highest-priority interrupt that applies to the current state."""
        checks = [
            self._health_interrupt(observation),
            self._hostile_interrupt(observation),
            self._hunger_interrupt(observation),
            self._night_interrupt(observation),
            self._deadline_interrupt(active_task),
            self._return_to_base_interrupt(observation),
        ]
        applicable = [decision for decision in checks if decision.should_interrupt]
        if not applicable:
            return InterruptDecision(False)
        applicable.sort(key=lambda decision: decision.priority, reverse=True)
        return applicable[0]

    def _health_interrupt(self, observation: dict) -> InterruptDecision:
        health = self._number(observation.get("health", 20), 20.0)
        if health >= self.config.health_critical_threshold:
            return InterruptDecision(False)
        action = self._food_action(observation.get("inventory", {}))
        return InterruptDecision(
            True,
            reason="health_critical",
            priority=110,
            recommended_goal="Recover health before continuing",
            emergency_action=action,
            evidence={"health": health, "threshold": self.config.health_critical_threshold},
        )

    def _hostile_interrupt(self, observation: dict) -> InterruptDecision:
        hostiles = [
            entity for entity in observation.get("nearby_entities", [])
            if (
                isinstance(entity, dict)
                and entity.get("hostile")
                and self._number(entity.get("distance", 999), 999.0) <= 8
            )
        ]
        if not hostiles:
            return InterruptDecision(False)
        nearest = sorted(
            hostiles,
            key=lambda entity: self._number(entity.get("distance", 999), 999.0),
        )[0]
        action = self._hostile_action(observation, nearest)
        return InterruptDecision(
            True,
            reason="hostile_nearby",
            priority=120,
            recommended_goal="Handle nearby hostile entity",
            emergency_action=action,
            evidence={"entity": nearest},
        )

    def _hunger_interrupt(self, observation: dict) -> InterruptDecision:
        hunger = self._number(observation.get("hunger", observation.get("food", 20)), 20.0)
        if hunger > GoalGenerator.LOW_HUNGER:
            return InterruptDecision(False)
        return InterruptDecision(
            True,
            reason="hunger_critical",
            priority=100,
            recommended_goal=(
                "Eat available food to restore hunger"
                if self._food_action(observation.get("inventory", {}))
                else "Find food and gather a safe supply before continuing"
            ),
            emergency_action=self._food_action(observation.get("inventory", {})),
            evidence={"hunger": hunger, "threshold": GoalGenerator.LOW_HUNGER},
        )

    def _night_interrupt(self, observation: dict) -> InterruptDecision:
        time_of_day = int(self._number(observation.get("time_of_day", 0), 0.0)) % 24000
        shelter_verified = is_machine_verified_shelter(observation.get("shelter_verification"))
        if GoalGenerator.DUSK_START <= time_of_day < GoalGenerator.NIGHT_START:
            if shelter_verified:
                return InterruptDecision(False)
            return InterruptDecision(
                True,
                reason="dusk_shelter_required",
                priority=80,
                recommended_goal="Build verified shelter before nightfall",
                evidence={"time_of_day": time_of_day, "shelter_verified": False},
            )
        if GoalGenerator.NIGHT_START <= time_of_day < GoalGenerator.NIGHT_END:
            if not shelter_verified:
                return InterruptDecision(
                    True,
                    reason="night_shelter_required",
                    priority=90,
                    recommended_goal="Reach or build emergency verified shelter immediately",
                    evidence={"time_of_day": time_of_day, "shelter_verified": False},
                )
            return InterruptDecision(
                True,
                reason="night_safety_maintenance",
                priority=85,
                recommended_goal="Remain in verified shelter until dawn",
                evidence={"time_of_day": time_of_day, "shelter_verified": True},
            )
        return InterruptDecision(False)

    def _deadline_interrupt(self, active_task) -> InterruptDecision:
        if not active_task or not getattr(active_task, "deadline", None):
            return InterruptDecision(False)
        evaluated_at = time.time()
        seconds_left = active_task.deadline - evaluated_at
        if seconds_left > 0:
            return InterruptDecision(False)
        return InterruptDecision(
            True,
            reason="task_deadline_elapsed",
            priority=70,
            recommended_goal=f"Replan overdue task: {active_task.title}",
            evidence={
                "task_id": active_task.id,
                "task": active_task.title,
                "deadline_wallclock": active_task.deadline,
                "evaluated_at_wallclock": evaluated_at,
                "seconds_left": round(seconds_left, 2),
            },
        )

    def _return_to_base_interrupt(self, observation: dict) -> InterruptDecision:
        if not self.explorer:
            return InterruptDecision(False)
        should_return, reason = self.explorer.should_return(
            observation.get("position", {}),
            observation.get("inventory_count", 0),
        )
        if not should_return:
            return InterruptDecision(False)
        action = None
        try:
            target = self.explorer.get_return_direction(observation.get("position", {}))
            action = {"type": "move_to", "parameters": {"x": target["x"], "z": target["z"]}}
        except Exception:
            action = None
        return InterruptDecision(
            True,
            reason="return_to_base",
            priority=40,
            recommended_goal="Return to base before continuing",
            emergency_action=action,
            evidence={"reason": reason, "position": observation.get("position", {})},
        )

    def _food_action(self, inventory: dict) -> Optional[dict]:
        for item in ("cooked_beef", "cooked_porkchop", "bread", "apple", "beef", "porkchop"):
            if inventory.get(item, 0) > 0:
                return {"type": "use_item", "parameters": {"item": item, "destination": "hand"}}
        return None

    def _weapon_action(self, inventory: dict) -> Optional[dict]:
        for item in ("iron_sword", "stone_sword", "wooden_sword", "iron_axe", "stone_axe", "wooden_axe"):
            if inventory.get(item, 0) > 0:
                return {"type": "equip", "parameters": {"item": item, "destination": "hand"}}
        return None

    def _hostile_action(self, observation: dict, hostile: dict) -> Optional[dict]:
        equip_action = self._weapon_action(observation.get("inventory", {}))
        if equip_action:
            weapon = str(equip_action.get("parameters", {}).get("item") or "")
            equipped = {
                str(item.get("name") or "")
                for item in observation.get("equipment", [])
                if isinstance(item, dict)
            }
            entity_id = hostile.get("id")
            if weapon in equipped and entity_id is not None:
                return {"type": "attack", "parameters": {"entity_id": entity_id}}
            return equip_action

        player = observation.get("position", {})
        target = hostile.get("position", {})
        if not isinstance(player, dict) or not isinstance(target, dict):
            return None
        try:
            px, pz = float(player["x"]), float(player["z"])
            tx, tz = float(target["x"]), float(target["z"])
        except (KeyError, TypeError, ValueError):
            return None
        dx, dz = px - tx, pz - tz
        length = (dx * dx + dz * dz) ** 0.5
        if length < 0.001:
            dx, dz, length = 1.0, 0.0, 1.0
        params = {
            "x": round(px + 8.0 * dx / length, 3),
            "z": round(pz + 8.0 * dz / length, 3),
        }
        if "y" in player:
            params["y"] = player["y"]
        return {"type": "move_to", "parameters": params}

    @classmethod
    def goal_is_aligned(cls, reason: str, goal: str) -> bool:
        text = str(goal or "").strip().lower()
        if reason == "hostile_nearby":
            return text.startswith(("attack nearest hostile", "flee from the nearest hostile"))
        if reason == "health_critical":
            return text.startswith(("eat available food to recover critical health", "find food and avoid danger"))
        if reason == "hunger_critical":
            return text.startswith(("eat available food to restore hunger", "find food and gather a safe supply"))
        if reason == "dusk_shelter_required":
            return text.startswith((
                "build verified shelter before nightfall",
                "reach or build emergency verified shelter",
            ))
        if reason == "night_shelter_required":
            return text.startswith((
                "build verified shelter before nightfall",
                "reach or build emergency verified shelter",
            ))
        if reason == "night_safety_maintenance":
            return text.startswith("remain in verified shelter until dawn")
        return False

    @staticmethod
    def _number(value, default: float) -> float:
        try:
            number = float(value)
            return number if math.isfinite(number) else float(default)
        except (TypeError, ValueError):
            return float(default)
