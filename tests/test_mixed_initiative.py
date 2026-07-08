"""Unit tests for MineNPC-style mixed-initiative task templates."""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from singularity.evaluation.mixed_initiative import (
    BoundedEvidenceValidator,
    MixedInitiativeFeedbackPolicy,
    MixedInitiativeTemplateCompiler,
    apply_mixed_initiative_policy_patch,
    build_mixed_initiative_report,
    build_mixed_initiative_policy_patch,
    build_mixed_initiative_review_experiment_plan,
    build_mixed_initiative_review_label_templates,
    build_mixed_initiative_review_queue,
    build_mixed_initiative_trace_report,
    build_mixed_initiative_variant_report,
    execute_mixed_initiative_review_labels,
    validate_mixed_initiative_review_labels,
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
    assert report.action_count == 1
    assert report.valid_action_count == 1
    assert report.invalid_action_count == 0
    assert report.successful_action_count == 1
    assert report.valid_successful_action_count == 1
    assert report.action_type_counts["dig"] == 1
    assert report.template_action_metrics[0]["template_id"] == "collect_oak_logs"
    assert report.template_action_metrics[0]["valid_action_success_rate"] == 1.0
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
    feedback = report.mixed_initiative_feedback
    assert any(hint["policy"] == "audit_goal_verifier_acceptance" for hint in feedback["policy_hints"])
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
    assert report.action_count == 1
    assert report.successful_action_count == 1
    assert report.invalid_action_count == 1
    assert report.valid_action_count == 0
    assert report.valid_successful_action_count == 0
    assert report.action_success_rate == 1.0
    assert report.valid_action_success_rate == 0.0
    assert report.cases[0].agreement == "invalid_policy"
    assert report.cases[0].invalid_action_count == 1
    assert report.template_action_metrics[0]["invalid_action_count"] == 1
    feedback = report.mixed_initiative_feedback
    policies = {hint["policy"]: hint for hint in feedback["policy_hints"]}
    assert policies["reject_invalid_actions"]["priority"] == "high"
    assert policies["reject_invalid_actions"]["invalid_action_count"] == 1
    assert all(result["status"] == "invalid" for result in report.cases[0].validation)
    print("PASS: Mixed-initiative trace report invalidates privileged shortcuts")


def test_mixed_initiative_trace_report_feedback_flags_failed_actions():
    session_path = write_jsonl([
        {"type": "goal_start", "data": {"goal": "Craft 4 torches"}},
        {"type": "observation", "data": {"inventory": {"stick": 1}}},
        {
            "type": "action",
            "data": {
                "action": {"type": "craft", "parameters": {"item": "torch"}},
                "result": {"success": False, "error": "Missing coal"},
            },
        },
        {"type": "observation", "data": {"inventory": {"stick": 1}}},
        {"type": "goal_end", "data": {"goal": "Craft 4 torches", "result": {"completed": False}}},
    ])

    report = build_mixed_initiative_trace_report([session_path])

    assert report.failed_action_count == 1
    assert report.valid_action_success_rate == 0.0
    assert report.template_action_metrics[0]["template_id"] == "craft_or_process_item"
    feedback = report.mixed_initiative_feedback
    policies = {hint["policy"]: hint for hint in feedback["policy_hints"]}
    assert policies["inspect_backend_execution"]["template_id"] == "craft_or_process_item"
    assert policies["improve_action_policy"]["valid_action_success_rate"] == 0.0
    recommendations = report.mixed_initiative_recommendations
    assert recommendations[0]["decision"] == "inspect_backend_execution"
    assert recommendations[0]["target_id"] == "craft_or_process_item"
    assert report.to_dict()["mixed_initiative_recommendations"][0]["target_id"] == "craft_or_process_item"
    print("PASS: Mixed-initiative feedback flags failed backend actions")


def test_mixed_initiative_feedback_policy_consumes_template_hints():
    session_path = write_jsonl([
        {"type": "goal_start", "data": {"goal": "Craft 4 torches"}},
        {"type": "observation", "data": {"inventory": {"stick": 1}}},
        {
            "type": "action",
            "data": {
                "action": {"type": "craft", "parameters": {"item": "torch"}},
                "result": {"success": False, "error": "Missing coal"},
            },
        },
        {"type": "observation", "data": {"inventory": {"stick": 1}}},
        {"type": "goal_end", "data": {"goal": "Craft 4 torches", "result": {"completed": False}}},
    ])
    report = build_mixed_initiative_trace_report([session_path])

    policy = MixedInitiativeFeedbackPolicy(report.mixed_initiative_feedback)
    decision = policy.decide_template("craft_or_process_item")
    profile = policy.feedback_profile()

    assert decision.decision == "inspect_backend_execution"
    assert decision.priority == "high"
    assert decision.should_review
    assert decision.should_inspect_backend
    assert "craft_or_process_item" in profile["templates_for_review"]
    assert profile["policy_counts"]["inspect_backend_execution"] == 1
    assert policy.recommendations()[0]["target_id"] == "craft_or_process_item"
    print("PASS: Mixed-initiative feedback policy consumes template hints")


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
    feedback = report.mixed_initiative_feedback
    candidate_hint = feedback["template_candidate_hints"][0]
    assert candidate_hint["policy"] == "promote_template_candidate"
    assert candidate_hint["candidate_id"] == "general_player_request"
    assert candidate_hint["priority"] == "medium"
    recommendation = report.mixed_initiative_recommendations[0]
    assert recommendation["decision"] == "promote_template_candidate"
    assert recommendation["target_id"] == "general_player_request"
    print("PASS: Mixed-initiative trace report groups unsupported goals into template candidates")


def test_mixed_initiative_feedback_policy_consumes_candidate_hints():
    first_path = write_jsonl([
        {"type": "goal_start", "data": {"goal": "Organize inventory"}},
        {"type": "observation", "data": {"inventory": {"stick": 1}}},
        {"type": "goal_end", "data": {"goal": "Organize inventory", "result": {"completed": False}}},
    ])
    second_path = write_jsonl([
        {"type": "goal_start", "data": {"goal": "Sort inventory"}},
        {"type": "observation", "data": {"inventory": {"coal": 1}}},
        {"type": "goal_end", "data": {"goal": "Sort inventory", "result": {"completed": False}}},
    ])
    report = build_mixed_initiative_trace_report([first_path, second_path])

    policy = MixedInitiativeFeedbackPolicy(report.mixed_initiative_feedback)
    decision = policy.decide_candidate("general_player_request")
    profile = policy.feedback_profile()

    assert decision.decision == "promote_template_candidate"
    assert decision.priority == "medium"
    assert decision.should_promote_template
    assert "general_player_request" in profile["candidates_for_promotion"]
    assert profile["policy_counts"]["promote_template_candidate"] == 1
    print("PASS: Mixed-initiative feedback policy consumes candidate hints")


def test_mixed_initiative_review_queue_groups_trace_recommendations():
    craft_path = write_jsonl([
        {"type": "goal_start", "data": {"goal": "Craft 4 torches"}},
        {"type": "observation", "data": {"inventory": {"stick": 1}}},
        {
            "type": "action",
            "data": {
                "action": {"type": "craft", "parameters": {"item": "torch"}},
                "result": {"success": False, "error": "Missing coal"},
            },
        },
        {"type": "observation", "data": {"inventory": {"stick": 1}}},
        {"type": "goal_end", "data": {"goal": "Craft 4 torches", "result": {"completed": False}}},
    ])
    first_unsupported = write_jsonl([
        {"type": "goal_start", "data": {"goal": "Organize inventory"}},
        {"type": "observation", "data": {"inventory": {"stick": 1}}},
        {"type": "goal_end", "data": {"goal": "Organize inventory", "result": {"completed": False}}},
    ])
    second_unsupported = write_jsonl([
        {"type": "goal_start", "data": {"goal": "Sort inventory"}},
        {"type": "observation", "data": {"inventory": {"coal": 1}}},
        {"type": "goal_end", "data": {"goal": "Sort inventory", "result": {"completed": False}}},
    ])
    craft_report = build_mixed_initiative_trace_report([craft_path])
    candidate_report = build_mixed_initiative_trace_report([first_unsupported, second_unsupported])

    queue = build_mixed_initiative_review_queue(trace_reports=[craft_report, candidate_report])

    assert queue.item_count == 2
    assert queue.high_priority_count == 1
    decisions = {item.decision: item for item in queue.items}
    assert decisions["inspect_backend_execution"].target_id == "craft_or_process_item"
    assert decisions["inspect_backend_execution"].source_goals == ["Craft 4 torches"]
    assert decisions["promote_template_candidate"].target_id == "general_player_request"
    assert decisions["promote_template_candidate"].recommendation_count == 1
    assert "Organize inventory" in decisions["promote_template_candidate"].source_goals
    print("PASS: Mixed-initiative review queue groups trace recommendations")


def test_mixed_initiative_review_queue_loads_saved_trace_report():
    craft_path = write_jsonl([
        {"type": "goal_start", "data": {"goal": "Craft 4 torches"}},
        {"type": "observation", "data": {"inventory": {"stick": 1}}},
        {
            "type": "action",
            "data": {
                "action": {"type": "craft", "parameters": {"item": "torch"}},
                "result": {"success": False, "error": "Missing coal"},
            },
        },
        {"type": "observation", "data": {"inventory": {"stick": 1}}},
        {"type": "goal_end", "data": {"goal": "Craft 4 torches", "result": {"completed": False}}},
    ])
    trace_report = build_mixed_initiative_trace_report([craft_path]).to_dict()
    report_path = os.path.join(tempfile.mkdtemp(), "mixed_trace.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(trace_report, f)

    queue = build_mixed_initiative_review_queue(trace_report_paths=[report_path])

    assert queue.errors == []
    assert queue.item_count == 1
    assert queue.items[0].source_reports == [report_path]
    assert queue.items[0].decision == "inspect_backend_execution"
    assert queue.to_dict()["items"][0]["id"].startswith("miq-template-craft-or-process-item")
    print("PASS: Mixed-initiative review queue loads saved trace reports")


def test_mixed_initiative_review_plan_routes_queue_items_to_experiments():
    craft_path = write_jsonl([
        {"type": "goal_start", "data": {"goal": "Craft 4 torches"}},
        {"type": "observation", "data": {"inventory": {"stick": 1}}},
        {
            "type": "action",
            "data": {
                "action": {"type": "craft", "parameters": {"item": "torch"}},
                "result": {"success": False, "error": "Missing coal"},
            },
        },
        {"type": "observation", "data": {"inventory": {"stick": 1}}},
        {"type": "goal_end", "data": {"goal": "Craft 4 torches", "result": {"completed": False}}},
    ])
    unsupported_path = write_jsonl([
        {"type": "goal_start", "data": {"goal": "Organize inventory"}},
        {"type": "observation", "data": {"inventory": {"stick": 1}}},
        {"type": "goal_end", "data": {"goal": "Organize inventory", "result": {"completed": False}}},
    ])
    craft_report = build_mixed_initiative_trace_report([craft_path])
    candidate_report = build_mixed_initiative_trace_report([unsupported_path])
    queue = build_mixed_initiative_review_queue(trace_reports=[craft_report, candidate_report])

    plan = build_mixed_initiative_review_experiment_plan(review_queue=queue)

    assert plan.case_count == 2
    assert plan.ready_count == 2
    assert plan.route_counts["backend_inspection"] == 1
    assert plan.route_counts["template_approval"] == 1
    routes = {case.route: case for case in plan.cases}
    assert craft_path in routes["backend_inspection"].source_logs
    assert "mixed-initiative-trace-report" in routes["backend_inspection"].recommended_commands[0]
    assert "mixed-initiative-variant-report" in routes["template_approval"].recommended_commands[0]
    assert routes["template_approval"].success_metrics == [
        "template_match_count",
        "slot_mismatch_count",
        "validation_success_count",
        "unsupported_template_count",
    ]
    print("PASS: Mixed-initiative review plan routes queue items to experiments")


def test_mixed_initiative_review_plan_loads_saved_queue():
    craft_path = write_jsonl([
        {"type": "goal_start", "data": {"goal": "Craft 4 torches"}},
        {"type": "observation", "data": {"inventory": {"stick": 1}}},
        {
            "type": "action",
            "data": {
                "action": {"type": "craft", "parameters": {"item": "torch"}},
                "result": {"success": False, "error": "Missing coal"},
            },
        },
        {"type": "observation", "data": {"inventory": {"stick": 1}}},
        {"type": "goal_end", "data": {"goal": "Craft 4 torches", "result": {"completed": False}}},
    ])
    queue = build_mixed_initiative_review_queue(
        trace_reports=[build_mixed_initiative_trace_report([craft_path])]
    )
    queue_path = os.path.join(tempfile.mkdtemp(), "mixed_review_queue.json")
    with open(queue_path, "w", encoding="utf-8") as f:
        json.dump(queue.to_dict(), f)

    plan = build_mixed_initiative_review_experiment_plan(review_queue_paths=[queue_path])

    assert plan.errors == []
    assert plan.case_count == 1
    assert plan.cases[0].route == "backend_inspection"
    assert plan.cases[0].queue_item_id == queue.items[0].id
    assert plan.to_dict()["route_counts"] == {"backend_inspection": 1}
    print("PASS: Mixed-initiative review plan loads saved queues")


def test_mixed_initiative_review_label_template_exports_approval_records():
    unsupported_path = write_jsonl([
        {"type": "goal_start", "data": {"goal": "Organize inventory"}},
        {"type": "observation", "data": {"inventory": {"stick": 1}}},
        {"type": "goal_end", "data": {"goal": "Organize inventory", "result": {"completed": False}}},
    ])
    queue = build_mixed_initiative_review_queue(
        trace_reports=[build_mixed_initiative_trace_report([unsupported_path])]
    )
    plan = build_mixed_initiative_review_experiment_plan(review_queue=queue)

    labels = build_mixed_initiative_review_label_templates(review_plan=plan)

    assert len(labels) == 1
    assert labels[0]["type"] == "mixed_initiative_review"
    assert labels[0]["readiness"] == "unknown"
    assert labels[0]["route"] == "template_approval"
    assert labels[0]["case_id"] == plan.cases[0].id
    assert "mixed-initiative-variant-report" in labels[0]["recommended_commands"][0]
    print("PASS: Mixed-initiative review label template exports approval records")


def test_mixed_initiative_review_label_validation_approves_executable_cases():
    craft_path = write_jsonl([
        {"type": "goal_start", "data": {"goal": "Craft 4 torches"}},
        {"type": "observation", "data": {"inventory": {"stick": 1}}},
        {
            "type": "action",
            "data": {
                "action": {"type": "craft", "parameters": {"item": "torch"}},
                "result": {"success": False, "error": "Missing coal"},
            },
        },
        {"type": "observation", "data": {"inventory": {"stick": 1}}},
        {"type": "goal_end", "data": {"goal": "Craft 4 torches", "result": {"completed": False}}},
    ])
    queue = build_mixed_initiative_review_queue(
        trace_reports=[build_mixed_initiative_trace_report([craft_path])]
    )
    plan = build_mixed_initiative_review_experiment_plan(review_queue=queue)
    plan_path = os.path.join(tempfile.mkdtemp(), "mixed_review_plan.json")
    with open(plan_path, "w", encoding="utf-8") as f:
        json.dump(plan.to_dict(), f)
    label_path = os.path.join(tempfile.mkdtemp(), "mixed_review_labels.jsonl")
    with open(label_path, "w", encoding="utf-8") as f:
        f.write(json.dumps({
            "type": "mixed_initiative_review",
            "case_id": plan.cases[0].id,
            "readiness": "approved",
            "reviewer": "manual_fixture",
            "notes": "backend failure is reproducible and should be inspected",
        }) + "\n")

    report = validate_mixed_initiative_review_labels(label_path, review_plan_paths=[plan_path])

    assert report.ok
    assert report.label_count == 1
    assert report.approved_count == 1
    assert report.executable_count == 1
    assert report.approved_route_counts == {"backend_inspection": 1}
    assert report.cases[0].source_logs == [craft_path]
    assert "mixed-initiative-trace-report" in report.cases[0].recommended_commands[0]
    print("PASS: Mixed-initiative review label validation approves executable cases")


def test_mixed_initiative_review_execution_runs_approved_backend_inspection():
    craft_path = write_jsonl([
        {"type": "goal_start", "data": {"goal": "Craft 4 torches"}},
        {"type": "observation", "data": {"inventory": {"stick": 1}}},
        {
            "type": "action",
            "data": {
                "action": {"type": "craft", "parameters": {"item": "torch"}},
                "result": {"success": False, "error": "Missing coal"},
            },
        },
        {"type": "observation", "data": {"inventory": {"stick": 1}}},
        {"type": "goal_end", "data": {"goal": "Craft 4 torches", "result": {"completed": False}}},
    ])
    queue = build_mixed_initiative_review_queue(
        trace_reports=[build_mixed_initiative_trace_report([craft_path])]
    )
    plan = build_mixed_initiative_review_experiment_plan(review_queue=queue)
    tmpdir = tempfile.mkdtemp()
    plan_path = os.path.join(tmpdir, "mixed_review_plan.json")
    label_path = os.path.join(tmpdir, "mixed_review_labels.jsonl")
    output_dir = os.path.join(tmpdir, "artifacts")
    with open(plan_path, "w", encoding="utf-8") as f:
        json.dump(plan.to_dict(), f)
    with open(label_path, "w", encoding="utf-8") as f:
        f.write(json.dumps({
            "type": "mixed_initiative_review",
            "case_id": plan.cases[0].id,
            "readiness": "approved",
            "reviewer": "manual_fixture",
            "notes": "run whitelisted backend inspection",
        }) + "\n")

    report = execute_mixed_initiative_review_labels(
        label_path,
        review_plan_paths=[plan_path],
        output_dir=output_dir,
    )

    assert report.ok
    assert report.executed_count == 1
    assert report.failed_count == 0
    assert report.cases[0].status == "executed"
    assert report.cases[0].artifact_paths
    assert os.path.exists(report.cases[0].artifact_paths[0])
    with open(report.cases[0].artifact_paths[0], "r", encoding="utf-8") as f:
        artifact = json.load(f)
    assert artifact["route"] == "backend_inspection"
    assert artifact["trace_report"]["failed_action_count"] == 1
    assert report.cases[0].artifact_summaries["failed_action_count"] == 1
    print("PASS: Mixed-initiative review execution runs approved backend inspection")


def test_mixed_initiative_review_execution_dry_run_does_not_write_artifacts():
    craft_path = write_jsonl([
        {"type": "goal_start", "data": {"goal": "Craft 4 torches"}},
        {"type": "observation", "data": {"inventory": {"stick": 1}}},
        {
            "type": "action",
            "data": {
                "action": {"type": "craft", "parameters": {"item": "torch"}},
                "result": {"success": False, "error": "Missing coal"},
            },
        },
        {"type": "goal_end", "data": {"goal": "Craft 4 torches", "result": {"completed": False}}},
    ])
    queue = build_mixed_initiative_review_queue(
        trace_reports=[build_mixed_initiative_trace_report([craft_path])]
    )
    plan = build_mixed_initiative_review_experiment_plan(review_queue=queue)
    tmpdir = tempfile.mkdtemp()
    label_path = os.path.join(tmpdir, "mixed_review_labels.jsonl")
    with open(label_path, "w", encoding="utf-8") as f:
        f.write(json.dumps({
            "type": "mixed_initiative_review",
            "case_id": plan.cases[0].id,
            "readiness": "approved",
            "reviewer": "manual_fixture",
            "notes": "dry run only",
        }) + "\n")

    report = execute_mixed_initiative_review_labels(
        label_path,
        review_plan=plan,
        output_dir=os.path.join(tmpdir, "artifacts"),
        dry_run=True,
    )

    assert report.ok
    assert report.executed_count == 0
    assert report.dry_run_count == 1
    assert report.cases[0].status == "dry_run"
    assert report.cases[0].artifact_paths == []
    assert report.cases[0].artifact_summaries["source_log_count"] == 1
    print("PASS: Mixed-initiative review execution dry-run avoids artifacts")


def test_mixed_initiative_policy_patch_applies_mixed_feedback():
    craft_path = write_jsonl([
        {"type": "goal_start", "data": {"goal": "Craft 4 torches"}},
        {"type": "observation", "data": {"inventory": {"stick": 1}}},
        {
            "type": "action",
            "data": {
                "action": {"type": "craft", "parameters": {"item": "torch"}},
                "result": {"success": False, "error": "Missing coal"},
            },
        },
        {"type": "observation", "data": {"inventory": {"stick": 1}}},
        {"type": "goal_end", "data": {"goal": "Craft 4 torches", "result": {"completed": False}}},
    ])
    queue = build_mixed_initiative_review_queue(
        trace_reports=[build_mixed_initiative_trace_report([craft_path])]
    )
    plan = build_mixed_initiative_review_experiment_plan(review_queue=queue)
    tmpdir = tempfile.mkdtemp()
    label_path = os.path.join(tmpdir, "mixed_review_labels.jsonl")
    with open(label_path, "w", encoding="utf-8") as f:
        f.write(json.dumps({
            "type": "mixed_initiative_review",
            "case_id": plan.cases[0].id,
            "readiness": "approved",
            "reviewer": "manual_fixture",
            "notes": "apply feedback patch",
        }) + "\n")
    execution = execute_mixed_initiative_review_labels(
        label_path,
        review_plan=plan,
        output_dir=os.path.join(tmpdir, "artifacts"),
    )

    patch = build_mixed_initiative_policy_patch(execution_report=execution)
    policy = MixedInitiativeFeedbackPolicy()
    applied = apply_mixed_initiative_policy_patch(patch, mixed_policy=policy)

    assert patch.ok
    assert patch.mixed_policy_hint_count >= 1
    assert patch.template_update_count >= 1
    assert applied["mixed_policy_hints_applied"] >= 1
    decision = policy.decide_template("craft_or_process_item")
    assert decision.should_inspect_backend
    assert decision.decision == "inspect_backend_execution"
    print("PASS: Mixed-initiative policy patch applies mixed feedback")


def test_mixed_initiative_policy_patch_applies_action_feedback():
    from singularity.action.policy import ActionGranularityPolicy

    tmpdir = tempfile.mkdtemp()
    artifact_path = os.path.join(tmpdir, "action_policy_artifact.json")
    execution_path = os.path.join(tmpdir, "execution.json")
    with open(artifact_path, "w", encoding="utf-8") as f:
        json.dump({
            "route": "action_policy_ablation",
            "target_id": "build_or_place_structure",
            "action_abstraction": {
                "action_abstraction_feedback": {
                    "action_count": 2,
                    "low_level_candidate_count": 1,
                    "canonical_action_types": {"place": 2},
                    "lower_level_action_types": {"place": 1},
                    "policy_hints": [
                        {
                            "action_type": "place",
                            "count": 2,
                            "preferred_control": "consider_low_level_visual_control",
                            "reason": "visual_or_precision_sensitive",
                            "low_level_candidate_count": 1,
                        }
                    ],
                }
            },
        }, f)
    with open(execution_path, "w", encoding="utf-8") as f:
        json.dump({
            "cases": [
                {
                    "status": "executed",
                    "artifact_paths": [artifact_path],
                }
            ]
        }, f)

    patch = build_mixed_initiative_policy_patch(execution_report_paths=[execution_path])
    policy = ActionGranularityPolicy()
    applied = apply_mixed_initiative_policy_patch(patch, action_policy=policy)

    assert patch.ok
    assert patch.action_policy_hint_count == 1
    assert applied["action_policy_hints_applied"] == 1
    assert policy.hints()["place"]["preferred_control"] == "consider_low_level_visual_control"
    assert policy.hints()["place"]["low_level_candidate_count"] == 1
    print("PASS: Mixed-initiative policy patch applies action feedback")


def test_mixed_initiative_variant_report_checks_heldout_templates():
    report = build_mixed_initiative_variant_report()

    assert report.case_count >= 7
    assert report.template_mismatch_count == 0
    assert report.slot_mismatch_count == 0
    assert report.validation_failure_count == 0
    assert report.fully_passed_count == report.case_count
    assert report.validation_checked_count >= 6
    assert report.validation_success_count == report.validation_checked_count
    assert any(case.id == "smelt_ingots_heldout" for case in report.cases)
    print("PASS: Mixed-initiative variant report validates held-out template paraphrases")


def test_mixed_initiative_variant_report_flags_slot_mismatch():
    report = build_mixed_initiative_variant_report(
        include_builtin=False,
        cases=[
            {
                "id": "bad_expected_item",
                "goal": "Craft 4 torches",
                "expected_template_id": "craft_or_process_item",
                "expected_slots": {"item": "stick"},
            }
        ],
    )

    assert report.case_count == 1
    assert report.template_match_count == 1
    assert report.slot_mismatch_count == 1
    assert report.fully_passed_count == 0
    assert "item: expected stick, got torch" in report.cases[0].slot_mismatches
    print("PASS: Mixed-initiative variant report flags held-out slot regressions")


def test_mixed_initiative_variant_report_loads_jsonl_case_file():
    path = write_jsonl([
        {
            "id": "jsonl_craft_variant",
            "goal": "Make 2 torches",
            "expected_template_id": "craft_or_process_item",
            "expected_slots": {"item": "torch", "count": 2},
        }
    ])

    report = build_mixed_initiative_variant_report(
        include_builtin=False,
        case_paths=[path],
    )

    assert report.errors == []
    assert report.case_count == 1
    assert report.fully_passed_count == 1
    assert report.cases[0].source == path
    print("PASS: Mixed-initiative variant report loads JSONL held-out case files")


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
    test_mixed_initiative_trace_report_feedback_flags_failed_actions()
    test_mixed_initiative_feedback_policy_consumes_template_hints()
    test_mixed_initiative_trace_report_groups_template_candidates()
    test_mixed_initiative_feedback_policy_consumes_candidate_hints()
    test_mixed_initiative_review_queue_groups_trace_recommendations()
    test_mixed_initiative_review_queue_loads_saved_trace_report()
    test_mixed_initiative_review_plan_routes_queue_items_to_experiments()
    test_mixed_initiative_review_plan_loads_saved_queue()
    test_mixed_initiative_review_label_template_exports_approval_records()
    test_mixed_initiative_review_label_validation_approves_executable_cases()
    test_mixed_initiative_review_execution_runs_approved_backend_inspection()
    test_mixed_initiative_review_execution_dry_run_does_not_write_artifacts()
    test_mixed_initiative_policy_patch_applies_mixed_feedback()
    test_mixed_initiative_policy_patch_applies_action_feedback()
    test_mixed_initiative_variant_report_checks_heldout_templates()
    test_mixed_initiative_variant_report_flags_slot_mismatch()
    test_mixed_initiative_variant_report_loads_jsonl_case_file()
    print("\nMixed-initiative tests PASSED")
