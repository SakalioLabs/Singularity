"""Unit tests for action controller safety helpers."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from singularity.action.controller import ActionController
from singularity.action.mapping import ActionMapper
from singularity.action.policy import ActionGranularityPolicy
from singularity.core.config import Config


class FakeBot:
    def __init__(self):
        self.calls = []

    def equip(self, item_name, destination="hand"):
        self.calls.append(("equip", item_name, destination))
        return {"success": True}

    def use_item(self):
        self.calls.append(("use_item",))
        return {"success": True}


def test_use_item_equips_requested_item_first():
    bot = FakeBot()
    controller = ActionController(bot, Config())
    result = controller.execute(
        {"type": "use_item", "parameters": {"item": "bread", "destination": "hand"}},
        {"health": 20, "inventory": {"bread": 1}},
    )

    assert result["success"] is True
    assert result["backend"] == "mineflayer"
    assert result["backend_command"] == "use_item"
    assert result["control_policy"]["preferred_control"] == "mineflayer_api_ok"
    assert bot.calls == [("equip", "bread", "hand"), ("use_item",)]
    print("PASS: ActionController equips item before use_item")


def test_action_mapper_desktop_backend_is_planned_not_executable():
    mapper = ActionMapper()
    command = mapper.map({"type": "craft", "parameters": {"item": "torch", "count": 4}}, backend="desktop")

    assert command.backend == "desktop"
    assert command.command == "open_inventory_craft"
    assert command.params["item"] == "torch"
    assert command.executable is False
    print("PASS: ActionMapper maps canonical action to desktop plan")


def test_action_controller_rejects_non_executable_backend():
    bot = FakeBot()
    controller = ActionController(bot, Config(), backend="desktop")
    result = controller.execute(
        {"type": "craft", "parameters": {"item": "torch"}},
        {"health": 20, "inventory": {"coal": 1, "stick": 1}},
    )

    assert result["success"] is False
    assert result["backend"] == "desktop"
    assert result["backend_command"] == "open_inventory_craft"
    assert "not executable" in result["error"]
    assert bot.calls == []
    print("PASS: ActionController reports planned desktop backend without executing")


def test_action_controller_rejects_unknown_canonical_action():
    controller = ActionController(FakeBot(), Config())
    result = controller.execute({"type": "teleport", "parameters": {}}, {"health": 20})

    assert result["success"] is False
    assert result["backend_command"] == "teleport"
    assert "unknown canonical action" in result["error"]
    assert result["control_policy"]["backend"] == "mineflayer"
    print("PASS: ActionController rejects unknown canonical action")


def test_action_granularity_policy_records_visual_preference_without_breaking_mineflayer():
    feedback = {
        "policy_hints": [
            {
                "action_type": "use_item",
                "preferred_control": "consider_low_level_visual_control",
                "reason": "visual_or_precision_sensitive",
            }
        ]
    }
    bot = FakeBot()
    policy = ActionGranularityPolicy(feedback)
    controller = ActionController(bot, Config(), action_policy=policy)
    result = controller.execute(
        {"type": "use_item", "parameters": {"item": "bread"}},
        {"health": 20, "inventory": {"bread": 1}},
    )

    assert result["success"] is True
    assert result["backend"] == "mineflayer"
    assert result["control_policy"]["preferred_backend"] == "desktop"
    assert result["control_policy"]["preferred_control"] == "consider_low_level_visual_control"
    assert result["control_policy"]["fallback_reason"] == "preferred backend desktop is not enabled"
    assert bot.calls == [("equip", "bread", "hand"), ("use_item",)]
    print("PASS: ActionGranularityPolicy preserves safe Mineflayer fallback")


def test_action_granularity_policy_can_emit_planned_desktop_mapping():
    feedback = {
        "policy_hints": [
            {
                "action_type": "place",
                "preferred_control": "consider_low_level_visual_control",
                "reason": "visual_or_precision_sensitive",
            }
        ]
    }
    policy = ActionGranularityPolicy(
        feedback,
        executable_backends={"mineflayer", "desktop"},
        allow_planned_backend=True,
    )
    controller = ActionController(FakeBot(), Config(), action_policy=policy)
    result = controller.execute(
        {"type": "place", "parameters": {"x": 1, "y": 64, "z": 2, "item": "torch"}},
        {"health": 20, "inventory": {"torch": 1}},
    )

    assert result["success"] is False
    assert result["backend"] == "desktop"
    assert result["backend_command"] == "mouse_place_block"
    assert result["control_policy"]["backend"] == "desktop"
    assert result["control_policy"]["preferred_backend"] == "desktop"
    assert "not executable" in result["error"]
    print("PASS: ActionGranularityPolicy can choose planned desktop mapping")


if __name__ == "__main__":
    test_use_item_equips_requested_item_first()
    test_action_mapper_desktop_backend_is_planned_not_executable()
    test_action_controller_rejects_non_executable_backend()
    test_action_controller_rejects_unknown_canonical_action()
    test_action_granularity_policy_records_visual_preference_without_breaking_mineflayer()
    test_action_granularity_policy_can_emit_planned_desktop_mapping()
    print("\nAction controller tests PASSED")
