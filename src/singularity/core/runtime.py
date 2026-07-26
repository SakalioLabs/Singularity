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

    BM012_DUSK_IRON_POLICY_ID = "m4-bm012-bounded-dusk-iron-continuation-v1"
    M4_EXPLOSIVE_HOSTILE_HORIZON_POLICY_ID = (
        "m4-preplanner-explosive-hostile-horizon-v1"
    )
    HOSTILE_INTERRUPT_DISTANCE = 8.0
    M4_EXPLOSIVE_HOSTILE_DISTANCE = 16.0
    EXPLOSIVE_HOSTILE_TYPES = frozenset({"creeper"})

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
        hostile_decision = self._hostile_interrupt(observation)
        night_decision = self._night_interrupt(observation, goal)
        checks = [
            self._health_interrupt(observation),
            hostile_decision,
            self._hunger_interrupt(observation),
            night_decision,
            self._deadline_interrupt(active_task),
            self._return_to_base_interrupt(observation),
        ]
        applicable = [decision for decision in checks if decision.should_interrupt]
        if not applicable:
            if hostile_decision.reason == "m4_hostile_safe_state_grounding":
                return hostile_decision
            if night_decision.reason == "m4_bm012_bounded_dusk_iron_continuation":
                return night_decision
            return InterruptDecision(False)
        applicable.sort(key=lambda decision: decision.priority, reverse=True)
        decision = applicable[0]
        grounding = hostile_decision.evidence.get("m4_hostile_safe_state_grounding")
        if isinstance(grounding, dict) and grounding:
            decision.evidence = {
                **dict(decision.evidence or {}),
                "m4_hostile_safe_state_grounding": grounding,
            }
        return decision

    def evaluate_preplanner_interrupt(self, observation: dict) -> InterruptDecision:
        """Catch strict-M4 explosive threats that can close during planner latency."""
        if str(getattr(self.config, "planner_protocol", "") or "") != "m4-fixed-v1":
            return InterruptDecision(False)
        decision = self._hostile_interrupt(observation)
        horizon = decision.evidence.get("m4_explosive_hostile_horizon")
        if decision.should_interrupt and isinstance(horizon, dict) and horizon:
            return decision
        return InterruptDecision(False)

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
        strict_m4 = str(getattr(self.config, "planner_protocol", "") or "") == "m4-fixed-v1"
        hostiles = []
        for entity in observation.get("nearby_entities", []):
            if not isinstance(entity, dict) or not entity.get("hostile"):
                continue
            hostile_type = str(entity.get("type") or "").strip().lower()
            distance = self._number(entity.get("distance", 999), 999.0)
            threshold = self.HOSTILE_INTERRUPT_DISTANCE
            if strict_m4 and hostile_type in self.EXPLOSIVE_HOSTILE_TYPES:
                threshold = self.M4_EXPLOSIVE_HOSTILE_DISTANCE
            if distance <= threshold:
                hostiles.append(entity)
        if not hostiles:
            return InterruptDecision(False)
        nearest = sorted(
            hostiles,
            key=lambda entity: self._number(entity.get("distance", 999), 999.0),
        )[0]
        action = self._hostile_action(observation, nearest)
        safe_state_grounding = self._m4_verified_shelter_hostile_grounding(
            observation,
            hostiles,
            nearest,
            action,
        )
        if safe_state_grounding:
            return InterruptDecision(
                False,
                reason="m4_hostile_safe_state_grounding",
                evidence={"m4_hostile_safe_state_grounding": safe_state_grounding},
            )
        evidence = {"entity": nearest}
        nearest_type = str(nearest.get("type") or "").strip().lower()
        nearest_distance = self._number(nearest.get("distance", 999), 999.0)
        if (
            strict_m4
            and nearest_type in self.EXPLOSIVE_HOSTILE_TYPES
            and self.HOSTILE_INTERRUPT_DISTANCE < nearest_distance
            <= self.M4_EXPLOSIVE_HOSTILE_DISTANCE
        ):
            evidence["m4_explosive_hostile_horizon"] = {
                "policy_id": self.M4_EXPLOSIVE_HOSTILE_HORIZON_POLICY_ID,
                "hostile_type": nearest_type,
                "distance": nearest_distance,
                "legacy_interrupt_distance": self.HOSTILE_INTERRUPT_DISTANCE,
                "explosive_interrupt_distance": self.M4_EXPLOSIVE_HOSTILE_DISTANCE,
                "planner_latency_exposure": True,
            }
        return InterruptDecision(
            True,
            reason="hostile_nearby",
            priority=120,
            recommended_goal="Handle nearby hostile entity",
            emergency_action=action,
            evidence=evidence,
        )

    def _m4_verified_shelter_hostile_grounding(
        self,
        observation: dict,
        hostiles: list[dict],
        nearest: dict,
        suppressed_action: Optional[dict],
    ) -> dict:
        """Prove that staying put is safer than reacting to an outside hostile."""
        if str(getattr(self.config, "planner_protocol", "") or "") != "m4-fixed-v1":
            return {}

        report = observation.get("shelter_verification")
        if not is_machine_verified_shelter(report):
            return {}
        risk = report.get("hostile_path_risk", {})
        coordinates = report.get("coordinate_evidence", {})
        if not isinstance(risk, dict) or not isinstance(coordinates, dict):
            return {}
        nearby_count = self._number(risk.get("nearby_hostile_count", -1), -1.0)
        if not (
            risk.get("method") == "complete_local_collision_enclosure"
            and risk.get("direct_reachability") == "blocked"
            and risk.get("hostiles_inside") == []
            and nearby_count.is_integer()
            and nearby_count >= len(hostiles)
        ):
            return {}

        observed_player_cell = self._floor_cell(observation.get("position"))
        verified_player_cell = self._integral_cell(coordinates.get("player_cell"))
        hostile_cell = self._integral_cell(nearest.get("cell")) or self._floor_cell(
            nearest.get("position")
        )
        if not (
            observed_player_cell
            and verified_player_cell == observed_player_cell
            and hostile_cell
            and hostile_cell != observed_player_cell
        ):
            return {}

        return {
            "policy_scope": "strict_m4_verified_shelter",
            "suppressed_interrupt_reason": "hostile_nearby",
            "suppressed_emergency_action": suppressed_action,
            "outward_move_suppressed": bool(
                isinstance(suppressed_action, dict)
                and suppressed_action.get("type") == "move_to"
            ),
            "safe_state_policy": "maintain_verified_shelter",
            "hostile_entity": nearest,
            "hostile_cell": hostile_cell,
            "observed_player_cell": observed_player_cell,
            "verified_player_cell": verified_player_cell,
            "nearby_hostile_count": int(nearby_count),
            "direct_reachability": risk.get("direct_reachability"),
            "hostiles_inside": [],
            "entrance_state": coordinates.get("entrance", {}).get("state"),
            "shelter_verifier_id": report.get("verifier_id"),
            "shelter_contract_sha256": report.get("contract_sha256"),
        }

    @classmethod
    def _floor_cell(cls, value) -> dict:
        if not isinstance(value, dict):
            return {}
        try:
            numbers = {axis: cls._number(value[axis], float("nan")) for axis in ("x", "y", "z")}
        except KeyError:
            return {}
        if not all(math.isfinite(number) for number in numbers.values()):
            return {}
        return {axis: math.floor(number) for axis, number in numbers.items()}

    @classmethod
    def _integral_cell(cls, value) -> dict:
        if not isinstance(value, dict):
            return {}
        try:
            numbers = {axis: cls._number(value[axis], float("nan")) for axis in ("x", "y", "z")}
        except KeyError:
            return {}
        if not all(math.isfinite(number) and number.is_integer() for number in numbers.values()):
            return {}
        return {axis: int(number) for axis, number in numbers.items()}

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

    def _night_interrupt(self, observation: dict, goal: str = "") -> InterruptDecision:
        time_of_day = int(self._number(observation.get("time_of_day", 0), 0.0)) % 24000
        shelter_verified = is_machine_verified_shelter(observation.get("shelter_verification"))
        if GoalGenerator.DUSK_START <= time_of_day < GoalGenerator.NIGHT_START:
            if shelter_verified:
                return InterruptDecision(False)
            continuation = self._m4_bm012_dusk_iron_continuation(
                observation,
                goal,
                time_of_day,
            )
            if continuation:
                return InterruptDecision(
                    False,
                    reason="m4_bm012_bounded_dusk_iron_continuation",
                    evidence=continuation,
                )
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

    def _m4_bm012_dusk_iron_continuation(
        self,
        observation: dict,
        goal: str,
        time_of_day: int,
    ) -> dict:
        if str(getattr(self.config, "planner_protocol", "") or "") != "m4-fixed-v1":
            return {}
        goal_lower = str(goal or "").strip().lower()
        if not goal_lower.startswith((
            "collect 8 raw iron from iron ore with the stone pickaxe",
            "mine iron ore for iron tools",
        )):
            return {}
        inventory = (
            observation.get("inventory", {})
            if isinstance(observation.get("inventory"), dict)
            else {}
        )
        health = self._number(observation.get("health", 20), 20.0)
        hunger = self._number(
            observation.get("hunger", observation.get("food", 20)),
            20.0,
        )
        hostiles = [
            entity
            for entity in observation.get("nearby_entities", []) or []
            if (
                isinstance(entity, dict)
                and entity.get("hostile")
                and self._number(entity.get("distance", 999), 999.0) <= 8
            )
        ]
        try:
            stone_pickaxe = int(inventory.get("stone_pickaxe", 0) or 0)
            raw_iron = int(inventory.get("raw_iron", 0) or 0)
            iron_ore = int(inventory.get("iron_ore", 0) or 0)
        except (TypeError, ValueError):
            return {}
        if not (
            stone_pickaxe >= 1
            and max(raw_iron, iron_ore) < 8
            and health >= 16
            and hunger >= 16
            and not hostiles
        ):
            return {}
        return {
            "policy_id": self.BM012_DUSK_IRON_POLICY_ID,
            "task_id": "BM-012",
            "goal": str(goal),
            "time_of_day": int(time_of_day),
            "stone_pickaxe_count": stone_pickaxe,
            "raw_iron_count": raw_iron,
            "iron_ore_count": iron_ore,
            "health": health,
            "hunger": hunger,
            "nearby_hostile_count": 0,
            "night_start": GoalGenerator.NIGHT_START,
            "night_interrupt_preserved": True,
        }

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
