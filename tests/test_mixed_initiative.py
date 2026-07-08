"""Unit tests for MineNPC-style mixed-initiative task templates."""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from singularity.evaluation.mixed_initiative import (
    BoundedEvidenceValidator,
    MixedInitiativeTemplateCompiler,
    build_mixed_initiative_report,
    build_mixed_initiative_trace_report,
)


def write_jsonl(events):
    path = os.path.join(tempfile.mkdtemp(), "session.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")
    return path


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


def test_unknown_goal_uses_unsupported_template_candidate():
    compiler = MixedInitiativeTemplateCompiler()

    plan = compiler.compile_goal("Organize inventory for later")

    assert plan.template_id == "unsupported_request"
    assert plan.category == "template_gap"
    assert plan.subtasks[0].id == "template_needed"
    print("PASS: Unknown mixed-initiative goals use unsupported template instead of wrong validator")


def test_craft_template_binds_item_count_and_validates_inventory():
    compiler = MixedInitiativeTemplateCompiler()

    plan = compiler.compile_goal("Craft 4 torches before night")

    assert plan.template_id == "craft_or_process_item"
    produce = plan.subtasks[0]
    assert produce.id == "produce_item"
    assert produce.bound_parameters["item"] == "torch"
    assert produce.bound_parameters["count"] == 4
    assert produce.bound_parameters["process_action"] == "craft"
    assert produce.success_validator["inventory_at_least"]["torch"] == 4

    report = build_mixed_initiative_report(
        "Craft 4 torches before night",
        evidence={"post_observation": {"inventory": {"torch": 4}}},
    )

    assert report["validation_summary"]["checked_subtasks"] == 1
    assert report["validation_summary"]["passed"] == 1
    print("PASS: Craft/process template binds item counts and validates output inventory")


def test_mine_template_splits_source_block_and_inventory_drop():
    compiler = MixedInitiativeTemplateCompiler()

    plan = compiler.compile_goal("Mine 3 coal ore within 12 blocks")

    assert plan.template_id == "collect_or_mine_resource"
    locate = next(subtask for subtask in plan.subtasks if subtask.id == "locate_resource_source")
    collect = next(subtask for subtask in plan.subtasks if subtask.id == "collect_resource")
    assert locate.bound_parameters["source_block"] == "coal_ore"
    assert locate.bound_parameters["search_radius"] == 12
    assert locate.success_validator["nearby_block_present"] == ["coal_ore"]
    assert collect.bound_parameters["resource"] == "coal"
    assert collect.bound_parameters["count"] == 3
    assert collect.preconditions["nearby_block_present"] == ["coal_ore"]
    assert collect.success_validator["inventory_at_least"]["coal"] == 3
    print("PASS: Generic mine template separates source blocks from inventory drops")


def test_build_template_accepts_equivalent_place_actions():
    compiler = MixedInitiativeTemplateCompiler()

    plan = compiler.compile_goal("Build a cobblestone wall")

    assert plan.template_id == "build_or_place_structure"
    build = plan.subtasks[0]
    assert build.bound_parameters["structure"] == "wall"
    assert build.bound_parameters["material"] == "cobblestone"

    result = BoundedEvidenceValidator().validate_subtask(
        build,
        {
            "actions": [
                {
                    "action": {"type": "place_block", "parameters": {"block": "cobblestone"}},
                    "result": {"success": True},
                }
            ]
        },
    )

    assert result.success
    assert result.status == "passed"
    print("PASS: Build/place template accepts equivalent successful placement actions")


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


def test_mixed_initiative_trace_report_agrees_with_goal_verifier():
    session_path = write_jsonl([
        {"type": "goal_start", "data": {"goal": "Collect 20 oak logs"}},
        {"type": "observation", "data": {"inventory": {}, "nearby_blocks": [{"name": "oak_log"}]}},
        {
            "type": "action",
            "data": {
                "action": {"type": "dig", "parameters": {"block": "oak_log"}},
                "result": {"success": True},
            },
        },
        {
            "type": "observation",
            "data": {
                "inventory": {"oak_log": 20},
                "nearby_blocks": [{"name": "oak_log"}],
                "recent_chat": ["logs collected"],
            },
        },
        {
            "type": "goal_verification",
            "data": {
                "goal": "Collect 20 oak logs",
                "achieved": True,
                "status": "achieved",
                "context": {"accepted": True},
            },
        },
        {"type": "goal_end", "data": {"goal": "Collect 20 oak logs", "result": {"completed": True}}},
    ])

    report = build_mixed_initiative_trace_report([session_path])

    assert report.goal_count == 1
    assert report.validator_success_count == 1
    assert report.agreement_counts["agrees_success"] == 1
    case = report.cases[0]
    assert case.validation_passed_count == 3
    assert case.goal_verification_status == "achieved"
    assert case.evidence_summary["recent_chat_count"] == 1
    print("PASS: Mixed-initiative trace report agrees with goal verifier on bounded evidence")


def test_mixed_initiative_trace_report_flags_validator_stricter_case():
    session_path = write_jsonl([
        {"type": "goal_start", "data": {"goal": "Collect 20 oak logs"}},
        {"type": "observation", "data": {"inventory": {}, "nearby_blocks": [{"name": "oak_log"}]}},
        {"type": "observation", "data": {"inventory": {"oak_log": 20}, "nearby_blocks": [{"name": "oak_log"}]}},
        {
            "type": "goal_verification",
            "data": {
                "goal": "Collect 20 oak logs",
                "achieved": True,
                "status": "achieved",
                "context": {"accepted": True},
            },
        },
        {"type": "goal_end", "data": {"goal": "Collect 20 oak logs", "result": {"completed": True}}},
    ])

    report = build_mixed_initiative_trace_report([session_path])

    assert report.goal_count == 1
    case = report.cases[0]
    assert not case.validator_success
    assert case.validation_failed_count == 1
    assert case.agreement == "validator_stricter"
    print("PASS: Mixed-initiative trace report flags validator stricter than goal verifier")


def test_mixed_initiative_trace_report_flags_policy_violation():
    session_path = write_jsonl([
        {"type": "goal_start", "data": {"goal": "Collect 20 oak logs"}},
        {"type": "observation", "data": {"inventory": {}, "nearby_blocks": [{"name": "oak_log"}]}},
        {
            "type": "action",
            "data": {
                "action": {"type": "chat", "parameters": {"message": "/give Singularity oak_log 20"}},
                "result": {"success": True},
            },
        },
        {
            "type": "observation",
            "data": {
                "inventory": {"oak_log": 20},
                "nearby_blocks": [{"name": "oak_log"}],
                "recent_chat": ["logs collected"],
            },
        },
        {"type": "goal_end", "data": {"goal": "Collect 20 oak logs", "result": {"completed": True}}},
    ])

    report = build_mixed_initiative_trace_report([session_path])

    assert report.policy_violation_count == 3
    assert report.cases[0].agreement == "invalid_policy"
    assert all(result["status"] == "invalid" for result in report.cases[0].validation)
    print("PASS: Mixed-initiative trace report invalidates privileged shortcuts")


def test_mixed_initiative_trace_report_groups_template_candidates():
    first_path = write_jsonl([
        {"type": "goal_start", "data": {"goal": "Organize inventory"}},
        {"type": "observation", "data": {"inventory": {"stick": 1, "coal": 1}}},
        {"type": "goal_end", "data": {"goal": "Organize inventory", "result": {"completed": False}}},
    ])
    second_path = write_jsonl([
        {"type": "goal_start", "data": {"goal": "Sort inventory"}},
        {"type": "observation", "data": {"inventory": {"raw_iron": 1, "coal": 1}}},
        {"type": "goal_end", "data": {"goal": "Sort inventory", "result": {"completed": False}}},
    ])

    report = build_mixed_initiative_trace_report([first_path, second_path])

    assert report.unsupported_goal_count == 2
    candidate = report.template_candidates[0]
    assert candidate["candidate_id"] == "general_player_request"
    assert candidate["count"] == 2
    assert "goal_verification" in candidate["suggested_validators"]
    assert all(case.template_id == "unsupported_request" for case in report.cases)
    print("PASS: Mixed-initiative trace report groups unsupported goals into template candidates")


if __name__ == "__main__":
    test_collect_logs_template_binds_goal_slots_and_context()
    test_fetch_tool_template_asks_single_targeted_clarification()
    test_unknown_goal_uses_unsupported_template_candidate()
    test_craft_template_binds_item_count_and_validates_inventory()
    test_mine_template_splits_source_block_and_inventory_drop()
    test_build_template_accepts_equivalent_place_actions()
    test_clarification_answer_resolves_validator_and_memory_candidate()
    test_bounded_validator_accepts_inventory_evidence()
    test_bounded_validator_rejects_privileged_commands()
    test_mixed_initiative_report_validates_all_subtasks()
    test_mixed_initiative_trace_report_agrees_with_goal_verifier()
    test_mixed_initiative_trace_report_flags_validator_stricter_case()
    test_mixed_initiative_trace_report_flags_policy_violation()
    test_mixed_initiative_trace_report_groups_template_candidates()
    print("\nMixed-initiative tests PASSED")
