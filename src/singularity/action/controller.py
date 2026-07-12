"""Action controller — translates structured action commands into bot operations with safety checks."""
import logging
import time
from typing import Optional

from singularity.action.mapping import ActionMapper
from singularity.action.policy import ActionGranularityPolicy, ActionPolicyDecision

logger = logging.getLogger("singularity.action")

NAVIGATION_ACTIONS = frozenset({"walk_to", "move_to"})


class ActionController:
    """Executes actions on the Minecraft bot with pre/post validation."""

    def __init__(
        self,
        bot,
        config,
        backend: str = "mineflayer",
        mapper: Optional[ActionMapper] = None,
        action_policy: Optional[ActionGranularityPolicy] = None,
    ):
        self.bot = bot
        self.config = config
        self.backend = backend
        self.mapper = mapper or ActionMapper()
        self.action_policy = action_policy
        self._episode_deadline_monotonic = None
        self._action_timeout_limit_s = None
        self._action_handlers = {
            "walk_to": self._walk_to,
            "move_to": self._move_to,
            "look_at": self._look_at,
            "dig": self._dig,
            "place": self._place,
            "craft": self._craft,
            "attack": self._attack,
            "equip": self._equip,
            "use_item": self._use_item,
            "chat": self._chat,
            "wait": self._wait,
            "build_shelter_5x5": self._build_shelter_5x5,
            "build_shelter_cell": self._build_shelter_cell,
        }

    def set_episode_deadline(self, deadline_monotonic, action_timeout_limit_s: float = None):
        """Bind action starts and transport waits to one absolute episode deadline."""
        self._episode_deadline_monotonic = (
            float(deadline_monotonic) if deadline_monotonic is not None else None
        )
        self._action_timeout_limit_s = (
            max(0.0, float(action_timeout_limit_s))
            if action_timeout_limit_s is not None
            else None
        )
        setter = getattr(self.bot, "set_action_deadline", None)
        if callable(setter):
            setter(self._episode_deadline_monotonic, self._action_timeout_limit_s)

    def execute(self, action: dict, world_state: dict) -> dict:
        """Execute a single action with pre/post checks."""
        policy_decision = self._select_action_policy(action)
        command = self.mapper.map(action, policy_decision.backend)
        action_type = command.command
        params = dict(command.params)
        command.params = params
        started_monotonic = time.monotonic()
        action_budget_s = self._remaining_action_budget_s(started_monotonic)
        if (
            self._episode_deadline_monotonic is not None
            and (action_budget_s is None or action_budget_s < 0.001)
        ):
            return {
                "success": False,
                "error": "action budget exhausted before action",
                "duration_ms": 0,
                "action_type": action.get("type", "unknown"),
                "backend": command.backend,
                "backend_command": command.command,
                "backend_params": params,
                "control_policy": policy_decision.as_dict(),
                "deadline_suppressed": True,
                "accepted_within_episode_deadline": False,
                "accepted_within_action_deadline": False,
                "action_budget_s": 0.0,
            }
        if action_budget_s is not None:
            params = self._bounded_action_params(action_type, params, action_budget_s)
            command.params = params

        if not command.executable:
            return {
                "success": False,
                "error": command.notes or f"Action not executable on backend {self.backend}",
                "duration_ms": 0,
                "action_type": action.get("type", "unknown"),
                "backend": command.backend,
                "backend_command": command.command,
                "backend_params": command.params,
                "control_policy": policy_decision.as_dict(),
            }

        # Pre-condition check
        pre_ok, pre_msg = self._check_preconditions(action_type, params, world_state)
        if not pre_ok:
            return {
                "success": False,
                "error": f"Pre-condition failed: {pre_msg}",
                "duration_ms": 0,
                "action_type": action.get("type", action_type),
                "backend": command.backend,
                "backend_command": command.command,
                "backend_params": command.params,
                "control_policy": policy_decision.as_dict(),
            }

        # Execute
        handler = self._action_handlers.get(action_type)
        if not handler:
            return {
                "success": False,
                "error": f"Unknown action: {action_type}",
                "duration_ms": 0,
                "action_type": action.get("type", action_type),
                "backend": command.backend,
                "backend_command": command.command,
                "backend_params": command.params,
                "control_policy": policy_decision.as_dict(),
            }

        try:
            result = handler(params)
        except Exception as e:
            logger.error(f"Action {action_type} failed: {e}")
            result = {"success": False, "error": str(e)}

        ended_monotonic = time.monotonic()
        duration_ms = int((ended_monotonic - started_monotonic) * 1000)
        result["duration_ms"] = duration_ms
        result["action_type"] = action.get("type", action_type)
        result["backend"] = command.backend
        result["backend_command"] = command.command
        result["backend_params"] = command.params
        result["control_policy"] = policy_decision.as_dict()
        if action_budget_s is not None:
            action_deadline_monotonic = started_monotonic + action_budget_s
            accepted_episode = ended_monotonic < self._episode_deadline_monotonic
            accepted_action = ended_monotonic < action_deadline_monotonic
            result["action_budget_s"] = round(action_budget_s, 3)
            result["action_deadline_monotonic"] = action_deadline_monotonic
            result["accepted_within_episode_deadline"] = accepted_episode
            result["accepted_within_action_deadline"] = accepted_action
            if not accepted_episode or not accepted_action:
                result["reported_success_before_deadline_check"] = bool(result.get("success"))
                result["success"] = False
                result["error"] = (
                    "episode deadline exceeded during action"
                    if not accepted_episode
                    else "action deadline exceeded during action"
                )
        if action_type in NAVIGATION_ACTIONS:
            reached = result.get("reached") is True
            result["navigation_reached"] = reached
            result["requires_replan"] = not reached
            if result["requires_replan"]:
                result["replan_reason"] = "navigation_target_unreached"
        return result

    def _remaining_action_budget_s(self, now_monotonic: float = None):
        if self._episode_deadline_monotonic is None:
            return None
        now = time.monotonic() if now_monotonic is None else float(now_monotonic)
        remaining = max(0.0, self._episode_deadline_monotonic - now)
        if self._action_timeout_limit_s is not None:
            remaining = min(remaining, self._action_timeout_limit_s)
        return remaining

    @staticmethod
    def _bounded_action_params(action_type: str, params: dict, budget_s: float) -> dict:
        bounded = dict(params)
        budget_ms = max(1, int(max(0.0, budget_s) * 1000))
        try:
            requested_timeout = int(bounded.get("timeout_ms", budget_ms))
        except (TypeError, ValueError):
            requested_timeout = budget_ms
        bounded["timeout_ms"] = max(1, min(requested_timeout, budget_ms))
        if action_type in {"wait", "walk_to"}:
            try:
                requested_wait = int(bounded.get("ms", 1000))
            except (TypeError, ValueError):
                requested_wait = 1000
            bounded["ms"] = max(1, min(requested_wait, budget_ms))
        return bounded

    def _select_action_policy(self, action: dict) -> ActionPolicyDecision:
        if self.action_policy is None:
            return ActionPolicyDecision(
                action_type=str(action.get("type") or "unknown"),
                backend=self.backend,
                preferred_backend=self.backend,
            )
        return self.action_policy.select_backend(action, self.backend, self.mapper)

    def _check_preconditions(self, action_type: str, params: dict, state: dict) -> tuple:
        """Check if action can be safely executed."""
        # Health safety
        if state.get("health", 20) < self.config.health_critical_threshold:
            return False, "Health critical"

        # Action-specific checks
        if action_type == "dig" and not state.get("inventory", {}).get("wooden_pickaxe"):
            # Allow hand digging for wood, but not stone
            pass

        if action_type == "craft":
            # Will be validated by the bot itself
            pass

        return True, "OK"

    def _move_to(self, params: dict) -> dict:
        x = params.get("x", 0)
        z = params.get("z", 0)
        y = params.get("y")
        timeout_ms = params.get("timeout_ms")
        if timeout_ms is None:
            timeout_ms = getattr(self.config, "max_action_timeout", 30000)
        return self.bot.move_to(
            x,
            z,
            y,
            tolerance=params.get("tolerance"),
            timeout_ms=timeout_ms,
        )

    def _look_at(self, params: dict) -> dict:
        x = params.get("x", 0)
        y = params.get("y", 0)
        z = params.get("z", 0)
        return self.bot.look_at(x, y, z)

    def _dig(self, params: dict) -> dict:
        x = params.get("x")
        y = params.get("y")
        z = params.get("z")
        timeout_ms = params.get("timeout_ms")
        if timeout_ms is None:
            return self.bot.dig(x, y, z)
        return self.bot.dig(x, y, z, timeout_ms=timeout_ms)

    def _place(self, params: dict) -> dict:
        x = params.get("x")
        y = params.get("y")
        z = params.get("z")
        item_name = params.get("item")
        return self.bot.place(x, y, z, item_name)

    def _craft(self, params: dict) -> dict:
        item_name = params.get("item")
        count = params.get("count", 1)
        return self.bot.craft(item_name, count)

    def _attack(self, params: dict) -> dict:
        entity_id = params.get("entity_id")
        return self.bot.attack(entity_id)

    def _equip(self, params: dict) -> dict:
        item_name = params.get("item")
        destination = params.get("destination", "hand")
        return self.bot.equip(item_name, destination)

    def _use_item(self, params: dict) -> dict:
        item_name = params.get("item")
        if item_name:
            equip_result = self.bot.equip(item_name, params.get("destination", "hand"))
            if not equip_result.get("success"):
                return equip_result
        return self.bot.use_item()

    def _chat(self, params: dict) -> dict:
        message = params.get("message", "")
        return self.bot.chat(message)

    def _walk_to(self, params: dict) -> dict:
        x = params.get("x", 0)
        z = params.get("z", 0)
        y = params.get("y")
        ms = params.get("ms", 2000)
        return self.bot.walk_to(x, z, y, ms)

    def _wait(self, params: dict) -> dict:
        ms = params.get("ms", 1000)
        time.sleep(ms / 1000.0)
        return {"success": True, "waited_ms": ms}

    def _build_shelter_5x5(self, params: dict) -> dict:
        return self.bot.build_shelter_5x5(params)

    def _build_shelter_cell(self, params: dict) -> dict:
        return self.bot.build_shelter_cell(params)
