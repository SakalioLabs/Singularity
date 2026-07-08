"""Runtime supervisor for interruptible planner/actor execution."""
import time
from dataclasses import dataclass, field
from typing import Optional

from singularity.core.config import Config


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

    def __init__(self, config: Config, explorer=None):
        self.config = config
        self.explorer = explorer

    def evaluate_interrupt(self, observation: dict, goal: str = "", active_task=None) -> InterruptDecision:
        """Return the highest-priority interrupt that applies to the current state."""
        checks = [
            self._health_interrupt(observation),
            self._hostile_interrupt(observation),
            self._deadline_interrupt(active_task),
            self._return_to_base_interrupt(observation),
        ]
        applicable = [decision for decision in checks if decision.should_interrupt]
        if not applicable:
            return InterruptDecision(False)
        applicable.sort(key=lambda decision: decision.priority, reverse=True)
        return applicable[0]

    def _health_interrupt(self, observation: dict) -> InterruptDecision:
        health = observation.get("health", 20)
        if health >= self.config.health_critical_threshold:
            return InterruptDecision(False)
        action = self._food_action(observation.get("inventory", {}))
        return InterruptDecision(
            True,
            reason="health_critical",
            priority=100,
            recommended_goal="Recover health before continuing",
            emergency_action=action,
            evidence={"health": health, "threshold": self.config.health_critical_threshold},
        )

    def _hostile_interrupt(self, observation: dict) -> InterruptDecision:
        hostiles = [
            entity for entity in observation.get("nearby_entities", [])
            if entity.get("hostile") and entity.get("distance", 999) <= 6
        ]
        if not hostiles:
            return InterruptDecision(False)
        nearest = sorted(hostiles, key=lambda entity: entity.get("distance", 999))[0]
        action = self._weapon_action(observation.get("inventory", {}))
        return InterruptDecision(
            True,
            reason="hostile_nearby",
            priority=90,
            recommended_goal="Handle nearby hostile entity",
            emergency_action=action,
            evidence={"entity": nearest},
        )

    def _deadline_interrupt(self, active_task) -> InterruptDecision:
        if not active_task or not getattr(active_task, "deadline", None):
            return InterruptDecision(False)
        seconds_left = active_task.deadline - time.time()
        if seconds_left > 0:
            return InterruptDecision(False)
        return InterruptDecision(
            True,
            reason="task_deadline_elapsed",
            priority=70,
            recommended_goal=f"Replan overdue task: {active_task.title}",
            evidence={"task_id": active_task.id, "task": active_task.title, "seconds_left": round(seconds_left, 2)},
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
