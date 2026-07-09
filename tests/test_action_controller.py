"""Unit tests for action controller safety helpers."""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from singularity.action.controller import ActionController
from singularity.action.mapping import ActionMapper
from singularity.action.policy import ActionGranularityPolicy
from singularity.action.selection import ActionCandidateSelector
from singularity.action.value import ActionValueProfile
from singularity.action.verifier import ActionVerifier
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


def _write_action_value_feedback(tmpdir):
    feedback_path = os.path.join(tmpdir, "action_value.json")
    with open(feedback_path, "w", encoding="utf-8") as f:
        json.dump({
            "action_value_feedback": {
                "action_value_items": [
                    {
                        "signature": "dig:coal_ore",
                        "action_type": "dig",
                        "attempts": 4,
                        "successes": 4,
                        "failures": 0,
                        "unknown_outcomes": 0,
                        "verifier_accepts": 4,
                        "task_families": {"crafting": 4},
                    }
                ],
                "state_transition_value_items": [
                    {
                        "signature": "dig:coal_ore",
                        "action_type": "dig",
                        "attempts": 4,
                        "avg_transition_value_score": 0.2,
                        "avg_transition_confidence": 0.5,
                        "low_confidence_transitions": 4,
                    }
                ],
            }
        }, f)
    return feedback_path


def _write_trusted_action_value_feedback(tmpdir):
    feedback_path = os.path.join(tmpdir, "trusted_action_value.json")
    with open(feedback_path, "w", encoding="utf-8") as f:
        json.dump({
            "action_value_feedback": {
                "action_value_items": [
                    {
                        "signature": "dig:coal_ore",
                        "action_type": "dig",
                        "attempts": 4,
                        "successes": 4,
                        "failures": 0,
                        "unknown_outcomes": 0,
                        "verifier_accepts": 4,
                        "task_families": {"crafting": 4},
                    }
                ],
                "state_transition_value_items": [
                    {
                        "signature": "dig:coal_ore",
                        "action_type": "dig",
                        "attempts": 4,
                        "avg_transition_value_score": 0.2,
                        "avg_transition_confidence": 1.0,
                        "low_confidence_transitions": 0,
                    }
                ],
            }
        }, f)
    return feedback_path


def _write_action_value_transition_gate(tmpdir, readiness="approved"):
    gate_path = os.path.join(tmpdir, f"action_value_transition_gate_{readiness}.json")
    decision = "approve" if readiness == "approved" else "hold_for_review"
    with open(gate_path, "w", encoding="utf-8") as f:
        json.dump({
            "type": "action_value_transition_gate",
            "readiness": readiness,
            "decision": decision,
            "reason": "trusted transition values are ready" if readiness == "approved" else "needs review",
            "trusted_item_count": 1 if readiness == "approved" else 0,
            "trusted_transition_count": 4 if readiness == "approved" else 0,
        }, f)
    return gate_path


def _write_action_value_transition_evaluator_report(tmpdir, readiness="approved"):
    report_path = os.path.join(tmpdir, f"action_value_transition_evaluator_{readiness}.json")
    decision = "approve_comparison" if readiness == "approved" else "hold_for_review"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump({
            "type": "action_value_transition_evaluator_report",
            "readiness": readiness,
            "decision": decision,
            "reason": "state-grounded evaluator agrees" if readiness == "approved" else "needs review",
            "evaluated_count": 2 if readiness == "approved" else 0,
            "agreement_rate": 1.0 if readiness == "approved" else 0.0,
            "avg_abs_score_delta": 0.02 if readiness == "approved" else 0.0,
        }, f)
    return report_path


def _write_skill_memory_quality_feedback(tmpdir):
    feedback_path = os.path.join(tmpdir, "skill_memory_quality.json")
    with open(feedback_path, "w", encoding="utf-8") as f:
        json.dump({
            "skill_memory_quality_feedback": {
                "quality_label_counts": {
                    "reuse_conflicted_with_failures": 1,
                    "avoid_unheeded_post_hint_failures": 1,
                },
                "hint_type_counts": {"REUSE": 2, "AVOID": 1},
                "task_family_counts": {"crafting": 2},
                "hint_quality_items": [
                    {
                        "hint_type": "REUSE",
                        "skill": "craft_torch_memory_skill",
                        "task_family": "crafting",
                        "count": 1,
                        "labels": {"reuse_conflicted_with_failures": 1},
                    },
                ],
                "policy_hints": [
                    {
                        "skill_memory_policy": "demote_conflicting_reuse_hints",
                        "priority": "high",
                        "reason": "REUSE hint conflicted with later failures",
                        "count": 1,
                    },
                    {
                        "skill_memory_policy": "tighten_avoid_hint_prompting",
                        "priority": "medium",
                        "reason": "AVOID hint was followed by failed actions",
                        "count": 1,
                    },
                ],
            },
        }, f)
    return feedback_path


def _write_skill_memory_quality_gate(tmpdir, readiness):
    gate_path = os.path.join(tmpdir, f"skill_memory_quality_gate_{readiness}.json")
    with open(gate_path, "w", encoding="utf-8") as f:
        json.dump({
            "readiness": readiness,
            "decision": "allow_supported_reuse_skill_memory_promotion"
            if readiness == "approved"
            else "keep_skill_memory_review_only",
            "reason": "test skill-memory quality gate",
            "approved_count": 1 if readiness == "approved" else 0,
            "rejected_count": 1 if readiness == "rejected" else 0,
        }, f)
    return gate_path


def _write_knowledge_correction_feedback(tmpdir):
    feedback_path = os.path.join(tmpdir, "knowledge_correction.json")
    with open(feedback_path, "w", encoding="utf-8") as f:
        json.dump({
            "knowledge_correction_feedback": {
                "log_count": 1,
                "ready_log_count": 1,
                "dependency_correction_count": 1,
                "failure_action_memory_count": 1,
                "dependency_corrections": [
                    {
                        "type": "dependency_correction",
                        "goal": "Craft torches",
                        "failed_signature": "craft:torch",
                        "recovery_signature": "dig:coal_ore",
                        "target_items": ["torch"],
                        "evidence_count": 2,
                        "confidence": 0.85,
                        "recommendation": "add_reviewed_prerequisite_or_ordering_edge",
                        "correction": "Before retrying craft:torch, collect or expose coal_ore with dig when the goal is Craft torches.",
                        "knowledge_dimensions": {
                            "attribute": ["crafting", "torch"],
                            "interaction": ["dig_before_craft"],
                        },
                    },
                ],
                "failure_action_memories": [
                    {
                        "type": "failed_action_memory",
                        "signature": "craft:torch",
                        "action_type": "craft",
                        "attempts": 3,
                        "failures": 3,
                        "task_families": {"crafting": 3},
                        "recommendation": "avoid_or_replan_until_preconditions_change",
                        "reason": "repeated_failed_action",
                        "knowledge_dimensions": {
                            "attribute": ["crafting", "torch"],
                            "function": ["failed_action_memory"],
                        },
                    },
                ],
                "policy_hints": [
                    {
                        "knowledge_correction_policy": "review_dependency_graph_corrections",
                        "priority": "high",
                        "count": 1,
                    },
                ],
            },
        }, f)
    return feedback_path


def _write_knowledge_correction_gate(tmpdir, readiness):
    gate_path = os.path.join(tmpdir, f"knowledge_correction_gate_{readiness}.json")
    with open(gate_path, "w", encoding="utf-8") as f:
        json.dump({
            "type": "knowledge_correction_gate",
            "readiness": readiness,
            "decision": "allow_reviewed_knowledge_correction_feedback"
            if readiness == "approved"
            else "hold_knowledge_corrections_for_review",
            "reason": "test knowledge-correction gate",
            "source_count": 1,
            "ready_log_count": 1 if readiness == "approved" else 0,
            "correction_count": 2 if readiness == "approved" else 0,
            "dependency_correction_count": 1 if readiness == "approved" else 0,
            "failure_action_memory_count": 1 if readiness == "approved" else 0,
        }, f)
    return gate_path


def _write_task_precondition_feedback(tmpdir):
    feedback_path = os.path.join(tmpdir, "task_preconditions.json")
    with open(feedback_path, "w", encoding="utf-8") as f:
        json.dump({
            "task_precondition_feedback": {
                "log_count": 1,
                "ready_log_count": 1,
                "failed_action_count": 2,
                "blocked_plan_count": 1,
                "candidate_count": 2,
                "candidate_type_counts": {
                    "inventory_precondition": 1,
                    "tool_precondition": 1,
                },
                "candidates": [
                    {
                        "type": "task_precondition_candidate",
                        "candidate_id": "torch_missing_coal",
                        "candidate_type": "inventory_precondition",
                        "task_family": "crafting",
                        "goal": "Craft torches then mine iron ore",
                        "goal_signature": "torch_goal",
                        "action_signature": "craft:torch",
                        "action_type": "craft",
                        "target": "torch",
                        "inferred_preconditions": {"inventory": {"coal": 1, "stick": 1}},
                        "evidence_count": 2,
                        "confidence": 0.82,
                        "recommendation": "Before retrying craft:torch, satisfy inferred inventory prerequisites.",
                    },
                    {
                        "type": "task_precondition_candidate",
                        "candidate_id": "iron_needs_stone_pickaxe",
                        "candidate_type": "tool_precondition",
                        "task_family": "mining",
                        "goal": "Craft torches then mine iron ore",
                        "goal_signature": "torch_goal",
                        "action_signature": "dig:iron_ore",
                        "action_type": "dig",
                        "target": "iron_ore",
                        "inferred_preconditions": {
                            "inventory": {"stone_pickaxe": 1},
                            "tool_for": {"iron_ore": "stone_pickaxe"},
                        },
                        "evidence_count": 1,
                        "confidence": 0.7,
                        "recommendation": "Before retrying dig:iron_ore, insert tool acquisition or upgrade prerequisites.",
                    },
                ],
                "policy_hints": [
                    {
                        "task_precondition_policy": "review_task_precondition_candidates",
                        "priority": "high",
                        "count": 2,
                    },
                ],
            },
        }, f)
    return feedback_path


def _write_task_precondition_gate(tmpdir, readiness):
    gate_path = os.path.join(tmpdir, f"task_precondition_gate_{readiness}.json")
    with open(gate_path, "w", encoding="utf-8") as f:
        json.dump({
            "type": "task_precondition_gate",
            "readiness": readiness,
            "decision": "allow_reviewed_task_precondition_feedback"
            if readiness == "approved"
            else "hold_task_precondition_feedback_for_review",
            "reason": "test task-precondition gate",
            "source_count": 1,
            "ready_log_count": 1 if readiness == "approved" else 0,
            "candidate_count": 2 if readiness == "approved" else 0,
            "high_confidence_candidate_count": 2 if readiness == "approved" else 0,
        }, f)
    return gate_path


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


def test_agent_loads_action_value_feedback_into_candidate_selector():
    tmpdir = tempfile.mkdtemp()
    feedback_path = _write_action_value_feedback(tmpdir)
    config = Config(
        log_dir=os.path.join(tmpdir, "logs"),
        memory_dir=os.path.join(tmpdir, "memory"),
        skill_dir=os.path.join(tmpdir, "skills"),
        action_value_feedback_paths=[feedback_path],
    )

    agent = Agent(config)
    report = agent.action_value_feedback_report
    value = agent.action_candidate_selector.value_profile.score(
        {"type": "dig", "parameters": {"block": "coal_ore"}},
        goal="Craft torches",
    )

    assert report["loaded_count"] == 1
    assert report["value_items_loaded"] == 1
    assert report["transition_values_loaded"] == 0
    assert report["transition_values_skipped"] == 1
    assert report["transition_skip_reasons"]["low_transition_confidence"] == 1
    assert value["attempts"] == 4
    assert "transition_value_applied" not in value
    assert value["value_score"] > 0.7
    print("PASS: Agent loads action-value feedback into candidate selector")


def test_agent_suppresses_transition_values_without_runtime_gate_approval():
    tmpdir = tempfile.mkdtemp()
    feedback_path = _write_trusted_action_value_feedback(tmpdir)
    gate_path = _write_action_value_transition_gate(tmpdir, readiness="review")
    config = Config(
        log_dir=os.path.join(tmpdir, "logs"),
        memory_dir=os.path.join(tmpdir, "memory"),
        skill_dir=os.path.join(tmpdir, "skills"),
        action_value_feedback_paths=[feedback_path],
        action_value_transition_gate_paths=[gate_path],
    )

    agent = Agent(config)
    report = agent.action_value_feedback_report
    value = agent.action_candidate_selector.value_profile.score(
        {"type": "dig", "parameters": {"block": "coal_ore"}},
        goal="Craft torches",
    )

    assert report["loaded_count"] == 1
    assert report["transition_gate_required"] is True
    assert report["transition_gate_approved"] is False
    assert report["transition_gate_readiness"] == "review"
    assert report["transition_values_loaded"] == 0
    assert report["transition_values_suppressed_by_gate"] == 1
    assert report["transition_skip_reasons"]["transition_runtime_gate_not_approved"] == 1
    assert value["attempts"] == 4
    assert "transition_value_applied" not in value
    print("PASS: Agent suppresses transition values without runtime gate approval")


def test_agent_loads_transition_values_with_gate_and_evaluator_approval():
    tmpdir = tempfile.mkdtemp()
    feedback_path = _write_trusted_action_value_feedback(tmpdir)
    gate_path = _write_action_value_transition_gate(tmpdir, readiness="approved")
    evaluator_path = _write_action_value_transition_evaluator_report(tmpdir, readiness="approved")
    config = Config(
        log_dir=os.path.join(tmpdir, "logs"),
        memory_dir=os.path.join(tmpdir, "memory"),
        skill_dir=os.path.join(tmpdir, "skills"),
        action_value_feedback_paths=[feedback_path],
        action_value_transition_gate_paths=[gate_path],
        action_value_transition_evaluator_report_paths=[evaluator_path],
    )

    agent = Agent(config)
    report = agent.action_value_feedback_report
    value = agent.action_candidate_selector.value_profile.score(
        {"type": "dig", "parameters": {"block": "coal_ore"}},
        goal="Craft torches",
    )

    assert report["transition_gate_required"] is True
    assert report["transition_gate_approved"] is True
    assert report["transition_gate_readiness"] == "approved"
    assert report["transition_values_loaded"] == 1
    assert report["transition_values_suppressed_by_gate"] == 0
    assert value["transition_value_applied"] is True
    assert value["transition_value_score"] == 0.2
    print("PASS: Agent loads transition values with gate and evaluator approval")


def test_agent_loads_skill_memory_quality_feedback_into_library():
    tmpdir = tempfile.mkdtemp()
    feedback_path = _write_skill_memory_quality_feedback(tmpdir)
    config = Config(
        log_dir=os.path.join(tmpdir, "logs"),
        memory_dir=os.path.join(tmpdir, "memory"),
        skill_dir=os.path.join(tmpdir, "skills"),
        skill_memory_quality_feedback_paths=[feedback_path],
    )

    agent = Agent(config)
    profile = agent.skill_library.skill_memory_quality_profile()

    assert agent.skill_memory_quality_feedback_report["loaded_count"] == 1
    assert agent.skill_memory_quality_feedback_report["policy_hints_applied"] == 2
    assert "demote_conflicting_reuse_hints" in profile["policy_hints"]
    assert profile["task_family_counts"]["crafting"] == 2
    assert profile["hint_quality_items"][0]["skill"] == "craft_torch_memory_skill"
    print("PASS: Agent loads skill-memory quality feedback into library")


def test_agent_loads_skill_memory_quality_feedback_when_gate_is_approved():
    tmpdir = tempfile.mkdtemp()
    feedback_path = _write_skill_memory_quality_feedback(tmpdir)
    gate_path = _write_skill_memory_quality_gate(tmpdir, "approved")
    config = Config(
        log_dir=os.path.join(tmpdir, "logs"),
        memory_dir=os.path.join(tmpdir, "memory"),
        skill_dir=os.path.join(tmpdir, "skills"),
        skill_memory_quality_feedback_paths=[feedback_path],
        skill_memory_quality_gate_paths=[gate_path],
    )

    agent = Agent(config)
    report = agent.skill_memory_quality_feedback_report
    profile = agent.skill_library.skill_memory_quality_profile()

    assert report["gate_required"] is True
    assert report["gate_approved"] is True
    assert report["gate_readiness"] == "approved"
    assert report["loaded_count"] == 1
    assert report["skipped_count"] == 0
    assert "demote_conflicting_reuse_hints" in profile["policy_hints"]
    print("PASS: Agent loads skill-memory quality feedback when gate is approved")


def test_agent_skips_skill_memory_quality_feedback_when_gate_is_not_approved():
    for readiness in ("review", "rejected"):
        tmpdir = tempfile.mkdtemp()
        feedback_path = _write_skill_memory_quality_feedback(tmpdir)
        gate_path = _write_skill_memory_quality_gate(tmpdir, readiness)
        config = Config(
            log_dir=os.path.join(tmpdir, "logs"),
            memory_dir=os.path.join(tmpdir, "memory"),
            skill_dir=os.path.join(tmpdir, "skills"),
            skill_memory_quality_feedback_paths=[feedback_path],
            skill_memory_quality_gate_paths=[gate_path],
        )

        agent = Agent(config)
        report = agent.skill_memory_quality_feedback_report
        profile = agent.skill_library.skill_memory_quality_profile()

        assert report["gate_required"] is True
        assert report["gate_approved"] is False
        assert report["gate_readiness"] == readiness
        assert report["loaded_count"] == 0
        assert report["skipped_count"] == 1
        assert profile["policy_hints"] == []
        assert profile["hint_quality_items"] == []
    print("PASS: Agent skips skill-memory quality feedback when gate is not approved")


def test_agent_loads_knowledge_correction_feedback_when_gate_is_approved():
    tmpdir = tempfile.mkdtemp()
    feedback_path = _write_knowledge_correction_feedback(tmpdir)
    gate_path = _write_knowledge_correction_gate(tmpdir, "approved")
    config = Config(
        log_dir=os.path.join(tmpdir, "logs"),
        memory_dir=os.path.join(tmpdir, "memory"),
        skill_dir=os.path.join(tmpdir, "skills"),
        knowledge_correction_feedback_paths=[feedback_path],
        knowledge_correction_gate_paths=[gate_path],
    )

    agent = Agent(config)
    report = agent.knowledge_correction_feedback_report
    context = agent._knowledge_correction_context("Craft torches", {"inventory": {"stick": 1}})

    assert report["gate_required"] is True
    assert report["gate_approved"] is True
    assert report["gate_readiness"] == "approved"
    assert report["loaded_count"] == 1
    assert report["skipped_count"] == 0
    assert report["dependency_correction_count"] == 1
    assert report["failure_action_memory_count"] == 1
    assert report["context_item_count"] == 2
    assert "Knowledge correction feedback" in context
    assert "gate-approved, advisory only" in context
    assert "craft:torch" in context
    assert "dig:coal_ore" in context
    assert "avoid_or_replan_until_preconditions_change" in context
    print("PASS: Agent loads knowledge-correction feedback when gate is approved")


def test_agent_skips_knowledge_correction_feedback_without_approved_gate():
    tmpdir = tempfile.mkdtemp()
    feedback_path = _write_knowledge_correction_feedback(tmpdir)
    missing_gate_config = Config(
        log_dir=os.path.join(tmpdir, "logs_missing"),
        memory_dir=os.path.join(tmpdir, "memory_missing"),
        skill_dir=os.path.join(tmpdir, "skills_missing"),
        knowledge_correction_feedback_paths=[feedback_path],
    )

    missing_agent = Agent(missing_gate_config)
    missing_report = missing_agent.knowledge_correction_feedback_report
    assert missing_report["gate_required"] is True
    assert missing_report["gate_approved"] is False
    assert missing_report["gate_readiness"] == "missing"
    assert missing_report["loaded_count"] == 0
    assert missing_report["skipped_count"] == 1
    assert missing_agent._knowledge_correction_context("Craft torches", {}) == ""

    review_gate_path = _write_knowledge_correction_gate(tmpdir, "review")
    review_config = Config(
        log_dir=os.path.join(tmpdir, "logs_review"),
        memory_dir=os.path.join(tmpdir, "memory_review"),
        skill_dir=os.path.join(tmpdir, "skills_review"),
        knowledge_correction_feedback_paths=[feedback_path],
        knowledge_correction_gate_paths=[review_gate_path],
    )

    review_agent = Agent(review_config)
    review_report = review_agent.knowledge_correction_feedback_report
    assert review_report["gate_required"] is True
    assert review_report["gate_approved"] is False
    assert review_report["gate_readiness"] == "review"
    assert review_report["loaded_count"] == 0
    assert review_report["skipped_count"] == 1
    assert review_agent._knowledge_correction_context("Craft torches", {}) == ""
    print("PASS: Agent skips knowledge-correction feedback without approved gate")


def test_agent_loads_task_precondition_feedback_when_gate_is_approved():
    tmpdir = tempfile.mkdtemp()
    feedback_path = _write_task_precondition_feedback(tmpdir)
    gate_path = _write_task_precondition_gate(tmpdir, "approved")
    config = Config(
        log_dir=os.path.join(tmpdir, "logs"),
        memory_dir=os.path.join(tmpdir, "memory"),
        skill_dir=os.path.join(tmpdir, "skills"),
        task_precondition_feedback_paths=[feedback_path],
        task_precondition_gate_paths=[gate_path],
    )

    agent = Agent(config)
    report = agent.task_precondition_feedback_report
    context = agent._task_precondition_context(
        "Craft torches then mine iron ore",
        {"inventory": {"stick": 1, "wooden_pickaxe": 1}},
    )

    assert report["gate_required"] is True
    assert report["gate_approved"] is True
    assert report["gate_readiness"] == "approved"
    assert report["loaded_count"] == 1
    assert report["skipped_count"] == 0
    assert report["candidate_count"] == 2
    assert "Task precondition feedback" in context
    assert "gate-approved, advisory only" in context
    assert "craft:torch" in context
    assert "inventory coal=1, stick=1" in context
    assert "missing now: inventory coal=1" in context
    assert "dig:iron_ore" in context
    assert "stone_pickaxe=1" in context
    assert "tool_for iron_ore->stone_pickaxe" in context
    print("PASS: Agent loads task-precondition feedback when gate is approved")


def test_agent_skips_task_precondition_feedback_without_approved_gate():
    tmpdir = tempfile.mkdtemp()
    feedback_path = _write_task_precondition_feedback(tmpdir)
    missing_gate_config = Config(
        log_dir=os.path.join(tmpdir, "logs_missing"),
        memory_dir=os.path.join(tmpdir, "memory_missing"),
        skill_dir=os.path.join(tmpdir, "skills_missing"),
        task_precondition_feedback_paths=[feedback_path],
    )

    missing_agent = Agent(missing_gate_config)
    missing_report = missing_agent.task_precondition_feedback_report
    assert missing_report["gate_required"] is True
    assert missing_report["gate_approved"] is False
    assert missing_report["gate_readiness"] == "missing"
    assert missing_report["loaded_count"] == 0
    assert missing_report["skipped_count"] == 1
    assert missing_agent._task_precondition_context("Craft torches", {}) == ""

    review_gate_path = _write_task_precondition_gate(tmpdir, "review")
    review_config = Config(
        log_dir=os.path.join(tmpdir, "logs_review"),
        memory_dir=os.path.join(tmpdir, "memory_review"),
        skill_dir=os.path.join(tmpdir, "skills_review"),
        task_precondition_feedback_paths=[feedback_path],
        task_precondition_gate_paths=[review_gate_path],
    )

    review_agent = Agent(review_config)
    review_report = review_agent.task_precondition_feedback_report
    assert review_report["gate_required"] is True
    assert review_report["gate_approved"] is False
    assert review_report["gate_readiness"] == "review"
    assert review_report["loaded_count"] == 0
    assert review_report["skipped_count"] == 1
    assert review_agent._task_precondition_context("Craft torches", {}) == ""
    print("PASS: Agent skips task-precondition feedback without approved gate")


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


def test_action_verifier_rejects_missing_craft_materials_and_tools():
    verifier = ActionVerifier()

    torch = verifier.verify(
        {"type": "craft", "parameters": {"item": "torch", "count": 4}},
        {"inventory": {"stick": 1}},
    )
    assert torch.status == "reject"
    assert "coal" in " ".join(torch.missing)

    planks = verifier.verify(
        {"type": "craft", "parameters": {"item": "oak_planks", "count": 4}},
        {"inventory": {"oak_log": 1}},
    )
    assert planks.status == "accept"

    stone = verifier.verify(
        {"type": "dig", "parameters": {"block": "stone"}},
        {"inventory": {}, "nearby_blocks": [{"name": "stone"}]},
    )
    assert stone.status == "reject"
    assert "wooden_pickaxe" in stone.missing

    log = verifier.verify(
        {"type": "dig", "parameters": {"block": "oak_log"}},
        {"inventory": {}, "nearby_blocks": [{"name": "oak_log"}]},
    )
    assert log.status == "accept"
    print("PASS: ActionVerifier rejects impossible craft/mine actions before execution")


def test_action_candidate_selector_repairs_rejected_craft_action():
    selector = ActionCandidateSelector()

    selection = selector.select(
        {"type": "craft", "parameters": {"item": "torch", "count": 4}},
        {
            "inventory": {"stick": 1, "wooden_pickaxe": 1},
            "nearby_blocks": [{"name": "coal_ore", "position": {"x": 4, "y": 64, "z": 7}}],
        },
        goal="Craft torches",
    )
    data = selection.as_dict()
    assert data["changed"] is True
    assert data["original_verification"]["status"] == "reject"
    assert data["selected_verification"]["status"] == "accept"
    assert data["selected_action"]["type"] == "dig"
    assert data["selected_action"]["parameters"]["block"] == "coal_ore"

    retained = selector.select(
        {"type": "craft", "parameters": {"item": "oak_planks", "count": 4}},
        {"inventory": {"oak_log": 1}},
        goal="Craft oak planks",
    ).as_dict()
    assert retained["changed"] is False
    assert retained["selected_action"]["parameters"]["item"] == "oak_planks"
    print("PASS: ActionCandidateSelector repairs rejected craft actions conservatively")


def test_action_candidate_selector_surfaces_action_value_evidence():
    profile = ActionValueProfile()
    for _ in range(4):
        profile.record(
            {"type": "dig", "parameters": {"block": "coal_ore"}},
            {"success": True},
            goal="Craft torches",
        )
    selector = ActionCandidateSelector(value_profile=profile)

    selection = selector.select(
        {"type": "craft", "parameters": {"item": "torch", "count": 4}},
        {
            "inventory": {"stick": 1, "wooden_pickaxe": 1},
            "nearby_blocks": [{"name": "coal_ore"}],
        },
        goal="Craft torches",
    ).as_dict()

    selected = selection["candidates"][selection["selected_index"]]
    assert selected["action"]["type"] == "dig"
    assert selected["value"]["signature"] == "dig:coal_ore"
    assert selected["value"]["attempts"] == 4
    assert selected["value"]["value_score"] > 0.7
    print("PASS: ActionCandidateSelector surfaces action-value evidence")


def test_action_value_profile_gates_transition_value_feedback():
    low_confidence = ActionValueProfile()
    low_loaded = low_confidence.merge_feedback({
        "action_value_items": [
            {
                "signature": "wait:low_impact",
                "action_type": "wait",
                "attempts": 6,
                "successes": 6,
                "failures": 0,
            }
        ],
        "state_transition_value_items": [
            {
                "signature": "wait:low_impact",
                "action_type": "wait",
                "attempts": 6,
                "avg_transition_value_score": 0.2,
                "avg_transition_confidence": 0.5,
                "low_confidence_transitions": 6,
            }
        ],
    })
    low_score = low_confidence.score({"type": "wait", "parameters": {"ticks": 20}})

    trusted = ActionValueProfile()
    trusted_loaded = trusted.merge_feedback({
        "action_value_items": [
            {
                "signature": "wait:low_impact",
                "action_type": "wait",
                "attempts": 6,
                "successes": 6,
                "failures": 0,
            }
        ],
        "state_transition_value_items": [
            {
                "signature": "wait:low_impact",
                "action_type": "wait",
                "attempts": 6,
                "avg_transition_value_score": 0.2,
                "avg_transition_confidence": 1.0,
                "low_confidence_transitions": 0,
            }
        ],
    })
    trusted_score = trusted.score({"type": "wait", "parameters": {"ticks": 20}})

    assert low_loaded == 1
    assert low_confidence.last_merge_report["transition_values_skipped"] == 1
    assert low_confidence.last_merge_report["transition_skip_reasons"]["low_transition_confidence"] == 1
    assert "transition_value_applied" not in low_score
    assert trusted_loaded == 2
    assert trusted.last_merge_report["transition_values_loaded"] == 1
    assert trusted_score["transition_value_applied"] is True
    assert trusted_score["transition_value_score"] == 0.2
    assert trusted_score["value_score"] < trusted_score["outcome_value_score"]
    print("PASS: ActionValueProfile gates transition-value feedback by confidence")


def test_action_candidate_selector_uses_failure_correction_pairs():
    profile = ActionValueProfile()
    loaded = profile.merge_feedback({
        "failure_correction_pairs": [
            {
                "failed_signature": "attack:untargeted",
                "recovery_signature": "look_at:low_impact",
                "recovery_action": {"type": "look_at", "parameters": {"x": 2, "y": 64, "z": 3}},
                "goal": "Defend from hostile mob",
            }
        ]
    })
    selector = ActionCandidateSelector(value_profile=profile)

    selection = selector.select(
        {"type": "attack", "parameters": {}},
        {"nearby_entities": []},
        goal="Defend from hostile mob",
    ).as_dict()

    selected = selection["candidates"][selection["selected_index"]]
    assert loaded == 1
    assert selection["changed"] is True
    assert selection["original_verification"]["status"] == "reject"
    assert selected["source"] == "value_repair"
    assert selected["action"]["type"] == "look_at"
    assert selected["verification"]["status"] == "accept"
    print("PASS: ActionCandidateSelector uses action-value failure-correction pairs")


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
    test_agent_loads_action_value_feedback_into_candidate_selector()
    test_agent_suppresses_transition_values_without_runtime_gate_approval()
    test_agent_loads_transition_values_with_gate_and_evaluator_approval()
    test_agent_loads_skill_memory_quality_feedback_into_library()
    test_agent_loads_skill_memory_quality_feedback_when_gate_is_approved()
    test_agent_skips_skill_memory_quality_feedback_when_gate_is_not_approved()
    test_agent_loads_knowledge_correction_feedback_when_gate_is_approved()
    test_agent_skips_knowledge_correction_feedback_without_approved_gate()
    test_agent_loads_task_precondition_feedback_when_gate_is_approved()
    test_agent_skips_task_precondition_feedback_without_approved_gate()
    test_agent_skips_mixed_policy_patch_when_gate_is_not_approved()
    test_action_verifier_rejects_missing_craft_materials_and_tools()
    test_action_candidate_selector_repairs_rejected_craft_action()
    test_action_candidate_selector_surfaces_action_value_evidence()
    test_action_value_profile_gates_transition_value_feedback()
    test_action_candidate_selector_uses_failure_correction_pairs()
    print("\nAction controller tests PASSED")
