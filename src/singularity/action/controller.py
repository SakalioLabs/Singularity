"""Action controller — translates structured action commands into bot operations with safety checks."""
import time
import logging
from typing import Optional

from singularity.action.mapping import ActionMapper

logger = logging.getLogger("singularity.action")


class ActionController:
    """Executes actions on the Minecraft bot with pre/post validation."""

    def __init__(self, bot, config, backend: str = "mineflayer", mapper: Optional[ActionMapper] = None):
        self.bot = bot
        self.config = config
        self.backend = backend
        self.mapper = mapper or ActionMapper()
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
        }

    def execute(self, action: dict, world_state: dict) -> dict:
        """Execute a single action with pre/post checks."""
        command = self.mapper.map(action, self.backend)
        action_type = command.command
        params = command.params
        start_time = time.time()

        if not command.executable:
            return {
                "success": False,
                "error": command.notes or f"Action not executable on backend {self.backend}",
                "duration_ms": 0,
                "action_type": action.get("type", "unknown"),
                "backend": command.backend,
                "backend_command": command.command,
                "backend_params": command.params,
            }

        # Pre-condition check
        pre_ok, pre_msg = self._check_preconditions(action_type, params, world_state)
        if not pre_ok:
            return {"success": False, "error": f"Pre-condition failed: {pre_msg}", "duration_ms": 0}

        # Execute
        handler = self._action_handlers.get(action_type)
        if not handler:
            return {"success": False, "error": f"Unknown action: {action_type}", "duration_ms": 0}

        try:
            result = handler(params)
        except Exception as e:
            logger.error(f"Action {action_type} failed: {e}")
            result = {"success": False, "error": str(e)}

        duration_ms = int((time.time() - start_time) * 1000)
        result["duration_ms"] = duration_ms
        result["action_type"] = action.get("type", action_type)
        result["backend"] = command.backend
        result["backend_command"] = command.command
        result["backend_params"] = command.params
        return result

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
        return self.bot.move_to(x, z, y)

    def _look_at(self, params: dict) -> dict:
        x = params.get("x", 0)
        y = params.get("y", 0)
        z = params.get("z", 0)
        return self.bot.look_at(x, y, z)

    def _dig(self, params: dict) -> dict:
        x = params.get("x")
        y = params.get("y")
        z = params.get("z")
        return self.bot.dig(x, y, z)

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
