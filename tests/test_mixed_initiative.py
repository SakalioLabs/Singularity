"""Unit tests for MineNPC-style mixed-initiative task templates."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from singularity.evaluation.mixed_initiative import (
    BoundedEvidenceValidator,
    MixedInitiativeTemplateCompiler,
    build_mixed_initiative_report,
)


def test_collect_logs_template_binds_goal_slots_and_context():
    compiler = MixedInitiativeTemplateCompiler()

    plan = compiler.compile_goal(
        "Collect 20 oak logs within 10 blocks",
        context={"slots": {"dropoff_location": "base_chest"}},
    )

    assert plan.template_id == "collect_oak_logs"
    assert plan.plan_preview == "locate oak tree -> harvest oak logs -> return or report completion"
    assert not plan.needs_clarification
    harvest = next(subtask for subtask in plan.subtasks if subtask.id == "harvest_oak_logs")
    locate = next(subtask for subtask in plan.subtasks if subtask.id == "locate_oak_tree")
    assert harvest.bound_parameters["count"] == 20
    assert harvest.success_validator["inventory_at_least"]["oak_log"] == 20
    assert locate.bound_parameters["search_radius"] == 10
    print("PASS: Mixed-initiative template binds inferred goal slots and explicit context")


def test_fetch_tool_template_asks_single_targeted_clarification():
    compiler = MixedInitiativeTemplateCompiler()

    plan = compiler.compile_goal(
        "Get me a pickaxe",
        context={"memory_preferences": {"landmark": "weapon_storage"}},
    )

    assert plan.template_id == "fetch_named_tool"
    assert plan.needs_clarification
    assert plan.unbound_slot_count == 1
    assert "Which pickaxe" in plan.clarifying_questions[0]
    select = next(subtask for subtask in plan.subtasks if subtask.id == "select_pickaxe")
    assert select.missing_parameters == ["tool_variant"]
    print("PASS: Mixed-initiative template asks one targeted clarification for missing slot")


def test_clarification_answer_resolves_validator_and_memory_candidate():
    compiler = MixedInitiativeTemplateCompiler()

    plan = compiler.compile_goal(
        "Get me a pickaxe",
        context={
            "memory_preferences": {"landmark": "weapon_storage"},
            "clarification_answers": {"tool_variant": "iron"},
        },
    )

    assert not plan.needs_clarification
    assert plan.unbound_slot_count == 0
    assert plan.memory_write_candidates
    assert plan.memory_write_candidates[0]["slot"] == "tool_variant"
    select = next(subtask for subtask in plan.subtasks if subtask.id == "select_pickaxe")
    assert select.success_validator["inventory_at_least"]["iron_pickaxe"] == 1
    print("PASS: Clarification answers resolve validators and create scoped memory candidates")


def test_bounded_validator_accepts_inventory_evidence():
    compiler = MixedInitiativeTemplateCompiler()
    plan = compiler.compile_goal("Collect 20 oak logs")
    harvest = next(subtask for subtask in plan.subtasks if subtask.id == "harvest_oak_logs")
    validator = BoundedEvidenceValidator()

    result = validator.validate_subtask(
        harvest,
        {
            "post_observation": {"inventory": {"oak_log": 20}},
            "actions": [
                {
                    "action": {"type": "dig", "parameters": {"block": "oak_log"}},
                    "result": {"success": True},
                }
            ],
        },
    )

    assert result.success
    assert result.status == "passed"
    assert "inventory has 20/20 oak_log" in result.evidence
    print("PASS: Bounded validator accepts in-world inventory evidence")


def test_bounded_validator_rejects_privileged_commands():
    compiler = MixedInitiativeTemplateCompiler()
    plan = compiler.compile_goal("Collect 20 oak logs")
    harvest = next(subtask for subtask in plan.subtasks if subtask.id == "harvest_oak_logs")
    validator = BoundedEvidenceValidator()

    result = validator.validate_subtask(
        harvest,
        {
            "post_observation": {"inventory": {"oak_log": 64}},
            "actions": [
                {
                    "action": {"type": "chat", "parameters": {"message": "/give Singularity oak_log 64"}},
                    "result": {"success": True},
                }
            ],
        },
    )

    assert not result.success
    assert result.status == "invalid"
    assert result.policy_violations[0].kind == "forbidden_command"
    print("PASS: Bounded validator rejects privileged command shortcuts")


def test_mixed_initiative_report_validates_all_subtasks():
    report = build_mixed_initiative_report(
        "Collect 20 oak logs",
        evidence={
            "post_observation": {
                "inventory": {"oak_log": 20},
                "nearby_blocks": [{"name": "oak_log"}],
            },
            "recent_chat": ["logs collected"],
        },
    )

    assert report["plan"]["template_id"] == "collect_oak_logs"
    assert report["validation_summary"]["checked_subtasks"] == 3
    assert report["validation_summary"]["passed"] == 3
    print("PASS: Mixed-initiative report validates each template subtask")


if __name__ == "__main__":
    test_collect_logs_template_binds_goal_slots_and_context()
    test_fetch_tool_template_asks_single_targeted_clarification()
    test_clarification_answer_resolves_validator_and_memory_candidate()
    test_bounded_validator_accepts_inventory_evidence()
    test_bounded_validator_rejects_privileged_commands()
    test_mixed_initiative_report_validates_all_subtasks()
    print("\nMixed-initiative tests PASSED")
