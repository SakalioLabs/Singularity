import json
import os
import subprocess
import sys
import tempfile

from singularity.evaluation.critical_transition import (
    analyze_critical_trajectory,
    build_critical_transition_report,
    build_transition_units,
)


def _event(session, event_type, data):
    return {"session": session, "type": event_type, "data": data}


def _obs(x=0, z=0, blocks=None):
    return {
        "position": {"x": x, "y": 64, "z": z},
        "health": 20,
        "inventory": {},
        "nearby_blocks": blocks or [],
    }


def _false_navigation_events(session="ct-test-nav"):
    goal = "Gather oak logs"
    move = {"type": "move_to", "parameters": {"x": 12, "z": 0}}
    dig = {"type": "dig", "parameters": {"x": 12, "y": 64, "z": 0}}
    return [
        _event(session, "connect", {"success": True}),
        _event(session, "goal_start", {"goal": goal}),
        _event(session, "observation", _obs()),
        _event(session, "plan", {"status": "in_progress", "reasoning": "private raw chain", "actions": [move, dig]}),
        _event(session, "action", {"action": move, "result": {"success": True, "position": {"x": 2, "y": 64, "z": 0}}}),
        _event(session, "action", {"action": dig, "result": {"success": True, "block": "oak_log"}}),
        _event(session, "observation", _obs(2, 0)),
        _event(session, "goal_end", {"goal": goal, "result": {"completed": False, "cycles": 2}}),
    ]


def test_transition_units_group_action_cycles_without_raw_reasoning():
    events = _false_navigation_events()
    units = build_transition_units(events)

    assert len(units) == 2
    assert units[0]["action_type"] == "move_to"
    assert units[0]["observation_before_index"] == 2
    assert units[0]["observation_after_index"] == 6
    assert units[0]["belief_present"] is True
    assert "private raw chain" not in json.dumps(units, default=str)
    print("PASS: Transition Units group action cycles without raw planner reasoning")


def test_dependency_localizer_finds_upstream_false_navigation():
    report = analyze_critical_trajectory(
        _false_navigation_events(),
        case_id="false-navigation",
        source_kind="case_file",
        expected_label={"critical_unit_ordinal": 1, "category": "tool_output_misinterpretation"},
    )

    diagnosis = report["diagnosis"]
    assert diagnosis["found"] is True
    assert diagnosis["critical_unit_ordinal"] == 1
    assert diagnosis["constraint_id"] == "navigation_success_without_reach"
    assert diagnosis["category"] == "tool_output_misinterpretation"
    assert diagnosis["baselines"]["recency_unit_ordinal"] == 2
    assert report["label_evaluation"]["exact_unit_match"] is True
    assert report["repair_memory_candidate"]["automatic_retry_allowed"] is False
    print("PASS: Dependency localizer finds upstream false navigation before terminal symptom")


def test_empty_failed_plans_become_planner_response_units():
    goal = "Craft a wooden pickaxe"
    events = [
        _event("ct-empty", "goal_start", {"goal": goal}),
        _event("ct-empty", "observation", _obs()),
        _event("ct-empty", "plan", {"status": "blocked", "reasoning": "missing material", "actions": []}),
        _event("ct-empty", "observation", _obs()),
        _event("ct-empty", "plan", {"status": "blocked", "reasoning": "still missing", "actions": []}),
        _event("ct-empty", "goal_end", {"goal": goal, "result": {"completed": False, "cycles": 2}}),
    ]
    report = analyze_critical_trajectory(events, case_id="empty-plan")

    assert report["action_event_count"] == 0
    assert report["planner_response_unit_count"] == 2
    assert report["unit_coverage_rate"] == 1.0
    assert report["diagnosis"]["critical_unit_ordinal"] == 1
    assert report["diagnosis"]["constraint_id"] == "empty_plan_without_transition"
    assert report["diagnosis"]["category"] == "intent_plan_misalignment"
    print("PASS: Empty failed plans become diagnosable planner-response Transition Units")


def test_planned_but_unlogged_actions_become_adherence_failure():
    goal = "Move to the tree"
    move = {"type": "move_to", "parameters": {"x": 8, "z": 0}}
    events = [
        _event("ct-unexecuted", "goal_start", {"goal": goal}),
        _event("ct-unexecuted", "observation", _obs()),
        _event("ct-unexecuted", "plan", {"status": "in_progress", "reasoning": "move", "actions": [move]}),
        _event("ct-unexecuted", "goal_end", {"goal": goal, "result": {"completed": False, "cycles": 1}}),
    ]
    report = analyze_critical_trajectory(events, case_id="unexecuted-plan")

    assert report["action_event_count"] == 0
    assert report["planner_response_unit_count"] == 1
    assert report["diagnosis"]["constraint_id"] == "planned_actions_not_executed"
    assert report["diagnosis"]["category"] == "plan_adherence_failure"
    print("PASS: Planned but unlogged actions become a plan-adherence failure unit")


def test_guarded_navigation_suffix_deferral_is_not_an_execution_omission():
    goal = "Approach then mine the tree"
    walk = {"type": "walk_to", "parameters": {"x": 12, "z": 0, "ms": 500}}
    dig = {"type": "dig", "parameters": {"x": 12, "y": 64, "z": 0}}
    events = [
        _event("ct-deferred", "goal_start", {"goal": goal}),
        _event("ct-deferred", "observation", _obs()),
        _event("ct-deferred", "plan", {"status": "in_progress", "actions": [walk, dig]}),
        _event("ct-deferred", "action", {
            "action": walk,
            "result": {
                "success": True,
                "reached": False,
                "requires_replan": True,
                "replan_reason": "navigation_target_unreached",
                "position": {"x": 2, "y": 64, "z": 0},
            },
        }),
        _event("ct-deferred", "observation", _obs(2, 0)),
        _event("ct-deferred", "goal_end", {"goal": goal, "result": {"completed": False, "cycles": 1}}),
    ]

    units = build_transition_units(events)
    constraints = {item["constraint_id"] for item in units[0]["violations"]}

    assert len(units) == 1
    assert units[0]["plan_suffix_deferred"] is True
    assert units[0]["planned_actions_omitted"] == 1
    assert units[0]["planned_actions_deferred"] == 1
    assert "planned_actions_not_executed" not in constraints
    print("PASS: Guarded navigation suffix deferral is distinct from execution omission")


def test_empty_plan_is_recovered_by_a_later_verified_transition():
    goal = "Reach the tree"
    move = {"type": "move_to", "parameters": {"x": 4, "z": 0}}
    events = [
        _event("ct-empty-recovery", "goal_start", {"goal": goal}),
        _event("ct-empty-recovery", "observation", _obs()),
        _event("ct-empty-recovery", "plan", {"status": "in_progress", "actions": []}),
        _event("ct-empty-recovery", "observation", _obs()),
        _event("ct-empty-recovery", "plan", {"status": "in_progress", "actions": [move]}),
        _event("ct-empty-recovery", "action", {
            "action": move,
            "result": {"success": True, "reached": True, "position": {"x": 4, "y": 64, "z": 0}},
        }),
        _event("ct-empty-recovery", "observation", _obs(4, 0)),
        _event("ct-empty-recovery", "goal_end", {"goal": goal, "result": {"completed": False, "cycles": 2}}),
    ]

    units = build_transition_units(events)
    empty_violation = next(
        item
        for item in units[0]["violations"]
        if item["constraint_id"] == "empty_plan_without_transition"
    )

    assert empty_violation["recovered"] is True
    assert empty_violation["recovery_unit_id"] == units[1]["unit_id"]
    print("PASS: A later verified transition recovers an earlier empty plan")


def test_later_verified_action_recovers_an_earlier_execution_omission():
    goal = "Move then craft"
    move = {"type": "move_to", "parameters": {"x": 4, "z": 0}}
    craft = {"type": "craft", "parameters": {}}
    events = [
        _event("ct-omission-recovery", "goal_start", {"goal": goal}),
        _event("ct-omission-recovery", "observation", _obs()),
        _event("ct-omission-recovery", "plan", {"status": "in_progress", "actions": [move]}),
        _event("ct-omission-recovery", "observation", _obs()),
        _event("ct-omission-recovery", "plan", {"status": "in_progress", "actions": [move]}),
        _event("ct-omission-recovery", "action", {"action": move, "result": {"success": True, "position": {"x": 4, "y": 64, "z": 0}}}),
        _event("ct-omission-recovery", "observation", _obs(4, 0)),
        _event("ct-omission-recovery", "plan", {"status": "in_progress", "actions": [craft]}),
        _event("ct-omission-recovery", "action", {"action": craft, "result": {"success": False, "error": "item required"}}),
        _event("ct-omission-recovery", "goal_end", {"goal": goal, "result": {"completed": False, "cycles": 3}}),
    ]
    report = analyze_critical_trajectory(events, case_id="omission-recovery")

    assert report["diagnosis"]["critical_unit_ordinal"] == 3
    assert report["diagnosis"]["constraint_id"] == "invalid_action_schema"
    assert report["recovered_violation_count"] >= 1
    print("PASS: Later verified action recovers an earlier plan-execution omission")


def test_recovered_failure_is_not_selected_as_critical():
    goal = "Reach target then craft"
    move = {"type": "move_to", "parameters": {"x": 4, "z": 0}}
    craft = {"type": "craft", "parameters": {}}
    events = [
        _event("ct-recovery", "goal_start", {"goal": goal}),
        _event("ct-recovery", "observation", _obs()),
        _event("ct-recovery", "plan", {"status": "in_progress", "actions": [move]}),
        _event("ct-recovery", "action", {"action": move, "result": {"success": False, "error": "path blocked"}}),
        _event("ct-recovery", "observation", _obs()),
        _event("ct-recovery", "plan", {"status": "in_progress", "actions": [move]}),
        _event("ct-recovery", "action", {"action": move, "result": {"success": True, "reached": True, "position": {"x": 4, "y": 64, "z": 0}}}),
        _event("ct-recovery", "observation", _obs(4, 0)),
        _event("ct-recovery", "plan", {"status": "in_progress", "actions": [craft]}),
        _event("ct-recovery", "action", {"action": craft, "result": {"success": False, "error": "item required"}}),
        _event("ct-recovery", "goal_end", {"goal": goal, "result": {"completed": False, "cycles": 3}}),
    ]
    report = analyze_critical_trajectory(events, case_id="recovery")

    assert report["diagnosis"]["critical_unit_ordinal"] == 3
    assert report["diagnosis"]["constraint_id"] == "invalid_action_schema"
    assert report["recovered_violation_count"] >= 1
    print("PASS: Localizer skips an earlier failure that later recovered")


def test_builtin_controls_outperform_recency_and_never_gain_authority():
    report = build_critical_transition_report(
        include_builtins=True,
        evidence_kind="synthetic_control",
    )

    localization = report["localization_metrics"]
    assert report["readiness"] == "review"
    assert report["metrics"]["mean_unit_coverage_rate"] == 1.0
    assert localization["exact_unit_accuracy"] == 1.0
    assert localization["category_accuracy"] == 1.0
    assert localization["localizer_exact_gain_over_recency"] > 0
    assert report["planner_guidance_allowed"] is False
    assert report["runtime_intervention_allowed"] is False
    assert report["automatic_memory_promotion_allowed"] is False
    assert "graph" not in report["trajectories"][0]
    assert report["trajectories"][0]["graph_summary"]["full_graph_included"] is False
    print("PASS: Synthetic controls improve over recency without gaining runtime authority")


def test_external_labels_and_manifests_are_counted():
    tmpdir = tempfile.mkdtemp()
    session_path = os.path.join(tmpdir, "session.jsonl")
    label_path = os.path.join(tmpdir, "labels.jsonl")
    events = _false_navigation_events("ct-external")
    with open(session_path, "w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event) + "\n")
    with open(label_path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "session_id": "ct-external",
            "critical_unit_ordinal": 1,
            "category": "tool_output_misinterpretation",
            "reviewer_id": "reviewer-1",
        }) + "\n")

    report = build_critical_transition_report(
        session_log_paths=[session_path],
        label_paths=[label_path],
        evidence_kind="live_trace",
    )

    assert report["localization_metrics"]["externally_labeled_trajectory_count"] == 1
    assert report["localization_metrics"]["exact_unit_accuracy"] == 1.0
    assert report["evidence_integrity"]["source_manifests_valid"] is True
    assert "external_manual_critical_transition_labels" not in report["missing"]
    assert report["runtime_eligible"] is False
    print("PASS: External labels and source manifests are audited without runtime promotion")


def test_live_trace_integrity_requires_ids_present_in_the_source_events():
    tmpdir = tempfile.mkdtemp()
    session_path = os.path.join(tmpdir, "session_without_id.jsonl")
    events = _false_navigation_events("ct-removed")
    with open(session_path, "w", encoding="utf-8") as handle:
        for event in events:
            event = dict(event)
            event.pop("session", None)
            handle.write(json.dumps(event) + "\n")

    report = build_critical_transition_report(
        session_log_paths=[session_path],
        evidence_kind="live_trace",
    )

    assert report["evidence_integrity"]["explicit_session_ids"] is False
    assert report["evidence_integrity"]["distinct_session_count"] == 0
    assert "explicit_live_session_ids" in report["missing"]
    print("PASS: Live integrity does not mistake a fallback fingerprint for an explicit session id")


def test_critical_transition_cli_writes_report():
    tmpdir = tempfile.mkdtemp()
    output_path = os.path.join(tmpdir, "critical_transition.json")
    env = dict(os.environ)
    env["PYTHONPATH"] = "src"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "singularity.main",
            "critical-transition-report",
            "--include-builtins",
            "--evidence-kind",
            "synthetic_control",
            "--output",
            output_path,
        ],
        cwd=os.getcwd(),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Critical Transition Report" in result.stdout
    with open(output_path, "r", encoding="utf-8") as handle:
        report = json.load(handle)
    assert report["type"] == "critical_transition_report"
    assert report["trajectory_count"] == 6
    print("PASS: Critical transition CLI writes review-only report")


if __name__ == "__main__":
    test_transition_units_group_action_cycles_without_raw_reasoning()
    test_dependency_localizer_finds_upstream_false_navigation()
    test_empty_failed_plans_become_planner_response_units()
    test_planned_but_unlogged_actions_become_adherence_failure()
    test_guarded_navigation_suffix_deferral_is_not_an_execution_omission()
    test_empty_plan_is_recovered_by_a_later_verified_transition()
    test_later_verified_action_recovers_an_earlier_execution_omission()
    test_recovered_failure_is_not_selected_as_critical()
    test_builtin_controls_outperform_recency_and_never_gain_authority()
    test_external_labels_and_manifests_are_counted()
    test_live_trace_integrity_requires_ids_present_in_the_source_events()
    test_critical_transition_cli_writes_report()
    print("\nCritical transition tests PASSED")
