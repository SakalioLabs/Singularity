"""Unit tests for action controller safety helpers."""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from singularity.action.controller import ActionController
from singularity.action.mapping import ActionMapper
from singularity.action.policy import ActionGranularityPolicy
from singularity.core.agent import Agent
from singularity.core.config import Config
from singularity.core.self_evolution_policy import SelfEvolutionPolicy


class FakeBot:
    def __init__(self):
        self.calls = []

    def equip(self, item_name, destination="hand"):
        self.calls.append(("equip", item_name, destination))
        return {"success": True}

    def use_item(self):
        self.calls.append(("use_item",))
        return {"success": True}


def _write_mixed_policy_patch(tmpdir):
    patch_path = os.path.join(tmpdir, "mixed_policy_patch.json")
    with open(patch_path, "w", encoding="utf-8") as f:
        json.dump({
            "action_policy_feedback": {
                "policy_hints": [
                    {
                        "action_type": "place",
                        "preferred_control": "consider_low_level_visual_control",
                        "reason": "visual_or_precision_sensitive",
                        "low_level_candidate_count": 1,
                    }
                ]
            },
            "mixed_initiative_feedback": {
                "policy_hints": [
                    {
                        "policy": "inspect_backend_execution",
                        "template_id": "craft_or_process_item",
                        "priority": "high",
                    }
                ]
            },
            "template_policy_updates": [
                {"target_id": "craft_or_process_item", "decision": "inspect_backend_execution"}
            ],
        }, f)
    return patch_path


def _write_mixed_policy_gate(tmpdir, readiness):
    gate_path = os.path.join(tmpdir, f"mixed_policy_gate_{readiness}.json")
    with open(gate_path, "w", encoding="utf-8") as f:
        json.dump({
            "readiness": readiness,
            "decision": "allow_patch_auto_load" if readiness == "approved" else "manual_review_required",
            "reason": "test gate",
        }, f)
    return gate_path


def _write_self_evolution_feedback(tmpdir):
    feedback_path = os.path.join(tmpdir, "self_evolution.json")
    with open(feedback_path, "w", encoding="utf-8") as f:
        json.dump({
            "self_evolution_feedback": {
                "relative_reward_delta": -1.25,
                "action_failure_categories": {"perception": 2, "reasoning": 1},
                "typed_feedback_counts": {
                    "monitor_stagnation": 2,
                    "monitor_action_failure": 2,
                },
                "remedy_candidates": [
                    "dig coal_ore: learn perception remedy from failure (no target visible)",
                ],
                "adaptor_recommendations": [
                    "Before retrying dig, insert scan/look_at or visual grounding for the target.",
                    "Use accumulated typed feedback to rewrite only the unfinished plan suffix.",
                ],
                "policy_hints": [
                    {
                        "self_evolution_policy": "repair_stagnant_plan_suffix",
                        "priority": "high",
                        "reason": "execution produced repeated no-progress or repeated-failure signals",
                        "count": 2,
                    },
                    {
                        "self_evolution_policy": "induce_failure_remedies",
                        "priority": "high",
                        "reason": "failed actions should become typed remedy candidates before retry",
                        "count": 2,
                    },
                ],
            },
        }, f)
    return feedback_path


def test_self_evolution_policy_formats_advisory_context():
    policy = SelfEvolutionPolicy()
    applied = policy.record_self_evolution_feedback({
        "relative_reward_delta": -2.0,
        "action_failure_categories": {"perception": 2},
        "remedy_candidates": ["dig coal_ore: learn perception remedy from failure"],
        "adaptor_recommendations": ["Before retrying dig, insert scan/look_at."],
        "policy_hints": [
            {"self_evolution_policy": "repair_stagnant_plan_suffix", "priority": "high"},
            {"self_evolution_policy": "induce_failure_remedies", "priority": "high"},
        ],
    })

    advice = policy.advise("Craft torches", {"inventory": {"stick": 1}})
    context = policy.planner_context("Craft torches", {})

    assert applied == 2
    assert advice.mode == "repair_unfinished_plan_suffix"
    assert advice.priority == "high"
    assert advice.skill_reflection == "execution_lapse_first"
    assert advice.safety_gate == "advisory_only_requires_verification"
    assert "Self-evolution feedback" in context
    assert "do not bypass verification" in context
    assert "scan/look_at" in context
    print("PASS: SelfEvolutionPolicy formats advisory context")


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


def test_agent_loads_mixed_policy_patch_into_runtime_policies():
    tmpdir = tempfile.mkdtemp()
    patch_path = _write_mixed_policy_patch(tmpdir)
    config = Config(
        log_dir=os.path.join(tmpdir, "logs"),
        memory_dir=os.path.join(tmpdir, "memory"),
        skill_dir=os.path.join(tmpdir, "skills"),
        mixed_policy_patch_paths=[patch_path],
    )

    agent = Agent(config)

    assert agent.mixed_policy_patch_report["loaded_count"] == 1
    assert agent.mixed_policy_patch_report["action_policy_hints_applied"] == 1
    assert agent.mixed_policy_patch_report["mixed_policy_hints_applied"] == 1
    assert agent.mixed_policy_patch_report["template_policy_update_count"] == 1
    assert agent.action_controller.action_policy is agent.action_policy
    assert agent.action_policy.hints()["place"]["preferred_control"] == "consider_low_level_visual_control"
    decision = agent.mixed_initiative_policy.decide_template("craft_or_process_item")
    assert decision.decision == "inspect_backend_execution"
    assert decision.should_inspect_backend
    print("PASS: Agent loads mixed policy patch into runtime policies")


def test_agent_loads_mixed_policy_patch_when_gate_is_approved():
    tmpdir = tempfile.mkdtemp()
    patch_path = _write_mixed_policy_patch(tmpdir)
    gate_path = _write_mixed_policy_gate(tmpdir, "approved")
    config = Config(
        log_dir=os.path.join(tmpdir, "logs"),
        memory_dir=os.path.join(tmpdir, "memory"),
        skill_dir=os.path.join(tmpdir, "skills"),
        mixed_policy_patch_paths=[patch_path],
        mixed_policy_gate_paths=[gate_path],
    )

    agent = Agent(config)

    report = agent.mixed_policy_patch_report
    assert report["gate_required"] is True
    assert report["gate_approved"] is True
    assert report["gate_readiness"] == "approved"
    assert report["loaded_count"] == 1
    assert report["skipped_count"] == 0
    assert agent.action_policy.hints()["place"]["preferred_control"] == "consider_low_level_visual_control"
    print("PASS: Agent loads mixed policy patch when gate is approved")


def test_agent_loads_self_evolution_feedback_into_planner_policy():
    tmpdir = tempfile.mkdtemp()
    feedback_path = _write_self_evolution_feedback(tmpdir)
    config = Config(
        log_dir=os.path.join(tmpdir, "logs"),
        memory_dir=os.path.join(tmpdir, "memory"),
        skill_dir=os.path.join(tmpdir, "skills"),
        self_evolution_feedback_paths=[feedback_path],
    )

    agent = Agent(config)
    context = agent._self_evolution_context("Craft torches", {"inventory": {"stick": 1}})
    profile = agent.self_evolution_policy.feedback_profile()

    assert agent.self_evolution_feedback_report["loaded_count"] == 1
    assert agent.self_evolution_feedback_report["policy_hints_applied"] == 2
    assert profile["skill_reflection"] == "execution_lapse_first"
    assert "repair_stagnant_plan_suffix" in profile["policy_hints"]
    assert "advisory" in context
    assert "dig coal_ore" in context
    print("PASS: Agent loads self-evolution feedback into planner policy")


def test_agent_skips_mixed_policy_patch_when_gate_is_not_approved():
    for readiness in ("review", "rejected"):
        tmpdir = tempfile.mkdtemp()
        patch_path = _write_mixed_policy_patch(tmpdir)
        gate_path = _write_mixed_policy_gate(tmpdir, readiness)
        config = Config(
            log_dir=os.path.join(tmpdir, "logs"),
            memory_dir=os.path.join(tmpdir, "memory"),
            skill_dir=os.path.join(tmpdir, "skills"),
            mixed_policy_patch_paths=[patch_path],
            mixed_policy_gate_paths=[gate_path],
        )

        agent = Agent(config)

        report = agent.mixed_policy_patch_report
        assert report["gate_required"] is True
        assert report["gate_approved"] is False
        assert report["gate_readiness"] == readiness
        assert report["loaded_count"] == 0
        assert report["skipped_count"] == 1
        assert "place" not in agent.action_policy.hints()
    print("PASS: Agent skips mixed policy patch when gate is not approved")


if __name__ == "__main__":
    test_self_evolution_policy_formats_advisory_context()
    test_use_item_equips_requested_item_first()
    test_action_mapper_desktop_backend_is_planned_not_executable()
    test_action_controller_rejects_non_executable_backend()
    test_action_controller_rejects_unknown_canonical_action()
    test_action_granularity_policy_records_visual_preference_without_breaking_mineflayer()
    test_action_granularity_policy_can_emit_planned_desktop_mapping()
    test_agent_loads_mixed_policy_patch_into_runtime_policies()
    test_agent_loads_mixed_policy_patch_when_gate_is_approved()
    test_agent_loads_self_evolution_feedback_into_planner_policy()
    test_agent_skips_mixed_policy_patch_when_gate_is_not_approved()
    print("\nAction controller tests PASSED")
