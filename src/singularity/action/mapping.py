"""Canonical action mapping for multiple execution backends."""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class BackendCommand:
    """Backend-specific command derived from a canonical agent action."""

    backend: str
    command: str
    params: dict = field(default_factory=dict)
    executable: bool = True
    notes: str = ""


class ActionMapper:
    """Maps high-level actions to Mineflayer API or future desktop controls."""

    CANONICAL_ACTIONS = {
        "walk_to", "move_to", "look_at", "dig", "place", "craft",
        "attack", "equip", "use_item", "chat", "wait", "build_shelter_5x5",
    }

    def map(self, action: dict, backend: str = "mineflayer") -> BackendCommand:
        action_type = action.get("type", "unknown")
        params = action.get("parameters", {})
        if action_type not in self.CANONICAL_ACTIONS:
            return BackendCommand(backend, action_type, params, executable=False, notes=f"unknown canonical action: {action_type}")
        if backend == "mineflayer":
            return self._map_mineflayer(action_type, params)
        if backend == "desktop":
            return self._map_desktop(action_type, params)
        return BackendCommand(backend, action_type, params, executable=False, notes=f"unknown backend: {backend}")

    def _map_mineflayer(self, action_type: str, params: dict) -> BackendCommand:
        return BackendCommand("mineflayer", action_type, dict(params))

    def _map_desktop(self, action_type: str, params: dict) -> BackendCommand:
        mapping = {
            "move_to": ("keyboard_mouse_nav", {"target": self._position(params)}),
            "walk_to": ("keyboard_mouse_walk", {"target": self._position(params), "duration_ms": params.get("ms", 2000)}),
            "look_at": ("mouse_look_at", {"target": self._position(params, include_y=True)}),
            "dig": ("mouse_hold_attack", {"target_block": self._position(params, include_y=True)}),
            "place": ("mouse_place_block", {"target_block": self._position(params, include_y=True), "item": params.get("item")}),
            "craft": ("open_inventory_craft", {"item": params.get("item"), "count": params.get("count", 1)}),
            "attack": ("mouse_click_attack", {"entity_id": params.get("entity_id")}),
            "equip": ("hotbar_equip", {"item": params.get("item"), "destination": params.get("destination", "hand")}),
            "use_item": ("right_click_use", {"item": params.get("item"), "destination": params.get("destination", "hand")}),
            "chat": ("keyboard_chat", {"message": params.get("message", "")}),
            "wait": ("wait", {"duration_ms": params.get("ms", 1000)}),
            "build_shelter_5x5": (
                "build_shelter_5x5",
                dict(params),
            ),
        }
        command, mapped_params = mapping[action_type]
        return BackendCommand(
            "desktop",
            command,
            mapped_params,
            executable=False,
            notes="desktop backend mapping is planned but not executable yet",
        )

    def _position(self, params: dict, include_y: bool = False) -> dict:
        position = {"x": params.get("x", 0), "z": params.get("z", 0)}
        if include_y or "y" in params:
            position["y"] = params.get("y")
        return position
