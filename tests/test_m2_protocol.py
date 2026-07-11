"""Offline contract tests for M2; these fixtures never count as live evidence."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from singularity.evaluation.m2_protocol import (
    PROTOCOL,
    TASKS_BY_ID,
    protocol_integrity_report,
    validate_root_plan,
    verify_shelter_5x5,
    verify_task_outcome,
)


def valid_root_plan(goal="Gather wood and craft workbench"):
    return {
        "schema_version": "m2-root-plan-v1",
        "plan_kind": "root",
        "goal": goal,
        "status": "planning",
        "reasoning": "Gather one log before crafting its products.",
        "subtasks": [
            {
                "id": "gather_log",
                "title": "Gather an oak log",
                "type": "gather",
                "priority": 1,
                "depends_on": [],
                "preconditions": {},
                "success_criteria": {"inventory": {"oak_log": 1}},
                "rationale": "The recipe needs planks made from a log.",
            },
            {
                "id": "craft_table",
                "title": "Craft the workbench",
                "type": "craft",
                "priority": 2,
                "depends_on": ["gather_log"],
                "preconditions": {"inventory": {"oak_log": 1}},
                "success_criteria": {"inventory": {"crafting_table": 1}},
                "rationale": "This creates the requested final inventory item.",
            },
        ],
        "actions": [
            {
                "type": "dig",
                "parameters": {"block": "oak_log", "x": 3, "y": 64, "z": 0},
            }
        ],
    }


def action_event(action_type, parameters=None, **result):
    return {
        "type": "action",
        "data": {
            "action": {"type": action_type, "parameters": parameters or {}},
            "result": {"success": True, "action_type": action_type, **result},
            "pre_observation": {"inventory": {}},
            "post_observation": {"inventory": {}},
        },
    }


def shelter_snapshots(*, baseline_filled=False, omit_roof=False):
    origin = {"x": 3, "y": 64, "z": 3}
    wall = []
    for x in range(3, 8):
        for z in range(3, 8):
            if x not in {3, 7} and z not in {3, 7}:
                continue
            for y in (64, 65):
                if (x, z) == (5, 3):
                    continue
                wall.append((x, y, z))
    roof = [
        (x, 66, z)
        for x in range(3, 8)
        for z in range(3, 8)
        if not (omit_roof and x == 5 and z == 5)
    ]
    all_positions = [
        (x, y, z)
        for x in range(3, 8)
        for y in range(64, 67)
        for z in range(3, 8)
    ]
    structure = set(wall + roof)
    baseline = {
        "origin": origin,
        "blocks": [
            {
                "position": {"x": x, "y": y, "z": z},
                "name": "cobblestone" if baseline_filled and (x, y, z) in structure else "air",
            }
            for x, y, z in all_positions
        ],
    }
    post = {
        "origin": origin,
        "blocks": [
            {
                "position": {"x": x, "y": y, "z": z},
                "name": "cobblestone" if (x, y, z) in structure else "air",
            }
            for x, y, z in all_positions
        ],
    }
    return baseline, post


def test_m2_protocol_is_fixed_and_exact():
    assert protocol_integrity_report()["passed"]
    assert PROTOCOL["profile"] == "m2-fixed-v1"
    assert PROTOCOL["server_build"] == "paper-1.20.4-499"
    assert PROTOCOL["server_jar_sha256"] == "cabed3ae77cf55deba7c7d8722bc9cfd5e991201c211665f9265616d9fe5c77b"
    assert PROTOCOL["runtime_versions"] == {"node": "22.16.0", "python": "3.12.8"}
    assert PROTOCOL["llm"] == {
        "provider": "openai",
        "base_url": "https://opencode.ai/zen/go/v1",
        "model": "deepseek-v4-flash",
        "temperature": 0.0,
        "max_tokens": 4096,
        "response_format": {"type": "json_object"},
        "extra_body": {"thinking": {"type": "disabled"}},
    }
    assert PROTOCOL["llm_response_contract"] == {
        "id": "m2-visible-json-response-v1",
        "finish_reason": "stop",
        "reasoning_content_max_bytes": 0,
    }
    assert PROTOCOL["llm_transport_policy"] == {
        "id": "m2-bounded-transport-retry-v1",
        "sdk_max_retries": 0,
        "application_max_retries": 1,
        "retryable_error_types": ["APIConnectionError"],
        "reset_client_before_retry": True,
        "backoff_ms": 1000,
    }
    assert PROTOCOL["planner_context"]["successful_action_summary"] == {
        "profile": "m2-successful-action-summary-v1",
        "source": "current_goal_session_action_events",
        "max_actions": 8,
        "max_chars": 1600,
        "allowed_fields": ["type", "block", "item", "position", "inventory_delta"],
    }
    assert PROTOCOL["deadline_policy"] == {
        "id": "m2-hard-total-deadline-v1",
        "planner_timeout": "remaining_goal_time_minus_action_guard",
        "planner_max_retries": 0,
        "action_guard_ms": 30000,
        "post_planner_action_suppression": True,
        "eligibility_duration_required": True,
    }
    assert PROTOCOL["verifier_id"] == "m2-machine-verifier-v2"
    assert PROTOCOL["skill_runtime_profile_id"] == "m2-bounded-skills-v2"
    assert PROTOCOL["ingredient_equivalence_policy"]["id"] == "minecraft-planks-tag-v1"
    assert PROTOCOL["ingredient_equivalence_policy"]["applies_to"] == [
        "action_verifier",
        "knowledge_base",
        "learned_skill_preconditions",
        "learned_skill_contract_readiness",
    ]
    assert "dark_oak_planks" in PROTOCOL["ingredient_equivalence_policy"]["members"]
    assert [task["id"] for task in PROTOCOL["tasks"]] == [
        "BM-006", "BM-007", "BM-008", "BM-009", "BM-010"
    ]
    assert [task["goal"] for task in PROTOCOL["tasks"]] == [
        "Gather wood and craft workbench",
        "Craft wooden pickaxe and get cobblestone",
        "Find coal or make charcoal",
        "Craft a torch",
        "Build a simple 5x5 shelter",
    ]
    assert TASKS_BY_ID["BM-010"]["success_criteria"]["structure"] == "shelter-outer-5x5-v1"
    assert "dark_oak_log" in TASKS_BY_ID["BM-006"]["success_criteria"]["required_source_blocks"]
    print("PASS: M2 protocol pins runtime, LLM settings, hashes, and exact BM-006..010 goals")


def test_root_plan_schema_requires_ordered_dependent_subtasks():
    accepted = validate_root_plan(
        valid_root_plan(),
        expected_goal="Gather wood and craft workbench",
    )
    assert accepted["passed"]
    assert accepted["subtask_count"] == 2
    assert accepted["dependency_edge_count"] == 1

    invalid = valid_root_plan()
    invalid["subtasks"][0]["depends_on"] = ["future_node"]
    invalid["subtasks"][1]["depends_on"] = []
    invalid["actions"][0]["type"] = "shell"
    rejected = validate_root_plan(
        invalid,
        expected_goal="Gather wood and craft workbench",
    )
    assert not rejected["passed"]
    assert "dependent_subtasks_missing" in rejected["issues"]
    assert any("dependency_not_earlier_node" in issue for issue in rejected["issues"])
    assert any("action_type_not_allowed" in issue for issue in rejected["issues"])

    live_failure_shapes = [
        {"block_name": "oak_log", "position": {"x": 3, "y": 64, "z": 0}},
        {"target": "oak_log", "position": [3, 64, 0]},
        {"block_position": {"x": 3, "y": 64, "z": 0}},
    ]
    for bad_parameters in live_failure_shapes:
        bad_dig = valid_root_plan()
        bad_dig["actions"][0]["parameters"] = bad_parameters
        rejected_dig = validate_root_plan(
            bad_dig,
            expected_goal="Gather wood and craft workbench",
        )
        assert not rejected_dig["passed"]
        assert "action[0]:parameter_missing:block" in rejected_dig["issues"]
        assert "action[0]:parameter_missing:x" in rejected_dig["issues"]
        assert any("parameter_unexpected" in issue for issue in rejected_dig["issues"])

    bad_craft = valid_root_plan()
    bad_craft["actions"] = [{"type": "craft", "parameters": {"recipe": "oak_planks"}}]
    rejected_craft = validate_root_plan(
        bad_craft,
        expected_goal="Gather wood and craft workbench",
    )
    assert not rejected_craft["passed"]
    assert "action[0]:parameter_missing:item" in rejected_craft["issues"]
    assert "action[0]:parameter_unexpected:recipe" in rejected_craft["issues"]

    valid_craft = valid_root_plan()
    valid_craft["actions"] = [{"type": "craft", "parameters": {"item": "oak_planks", "count": 1}}]
    assert validate_root_plan(
        valid_craft,
        expected_goal="Gather wood and craft workbench",
    )["passed"]
    print("PASS: Root-plan schema rejects missing dependency order and unbounded actions")


def test_task_verifier_requires_observed_delta_and_action_proof():
    setup = {"after_state": {"inventory": {}}}
    terminal = {"inventory": {"crafting_table": 1}}
    events = [
        action_event("dig", {"x": 3, "y": 64, "z": 0}, block="oak_log", block_removed=True, pickup_observed=True),
        action_event("craft", {"item": "oak_planks", "count": 1}, item="oak_planks"),
        action_event("craft", {"item": "crafting_table", "count": 1}, item="crafting_table"),
    ]
    passed = verify_task_outcome(
        "BM-006",
        setup_evidence=setup,
        terminal_evidence=terminal,
        action_events=events,
    )
    assert passed["passed"]
    assert passed["planner_completion_trusted"] is False

    dark_oak_events = [
        action_event(
            "dig",
            {"x": 3, "y": 64, "z": 0},
            block="dark_oak_log",
            block_removed=True,
            pickup_observed=True,
        ),
        action_event("craft", {"item": "dark_oak_planks", "count": 4}, item="dark_oak_planks"),
        action_event("craft", {"item": "crafting_table", "count": 1}, item="crafting_table"),
    ]
    dark_oak_passed = verify_task_outcome(
        "BM-006",
        setup_evidence=setup,
        terminal_evidence=terminal,
        action_events=dark_oak_events,
    )
    assert dark_oak_passed["passed"], dark_oak_passed["issues"]

    preexisting = verify_task_outcome(
        "BM-006",
        setup_evidence={"after_state": {"inventory": {"crafting_table": 1}}},
        terminal_evidence=terminal,
        action_events=events,
    )
    assert not preexisting["passed"]
    assert "inventory_delta_missing:crafting_table" in preexisting["issues"]

    no_actions = verify_task_outcome(
        "BM-006",
        setup_evidence=setup,
        terminal_evidence=terminal,
        action_events=[],
    )
    assert not no_actions["passed"]
    assert "required_action_missing:dig" in no_actions["issues"]
    assert "required_action_missing:craft" in no_actions["issues"]
    print("PASS: M2 task verifier rejects preexisting inventory and action-free completion claims")


def test_bm010_verifier_requires_episode_built_walls_roof_entrance_and_interior():
    baseline, post = shelter_snapshots()
    passed = verify_shelter_5x5(
        baseline,
        post,
        {"x": 5.5, "y": 64, "z": 5.5},
    )
    assert passed["passed"]
    assert passed["wall_coverage"] == 0.9375
    assert passed["roof_coverage"] == 1.0
    assert passed["episode_delta_block_count"] == 55
    assert passed["player_inside"]

    natural_baseline, same_post = shelter_snapshots(baseline_filled=True)
    natural = verify_shelter_5x5(
        natural_baseline,
        same_post,
        {"x": 5.5, "y": 64, "z": 5.5},
    )
    assert not natural["passed"]
    assert "counted_structure_not_episode_delta" in natural["issues"]

    baseline, open_roof = shelter_snapshots(omit_roof=True)
    roof_failed = verify_shelter_5x5(
        baseline,
        open_roof,
        {"x": 5.5, "y": 64, "z": 5.5},
    )
    assert not roof_failed["passed"]
    assert "roof_coverage_below_minimum" in roof_failed["issues"]

    outside = verify_shelter_5x5(
        baseline,
        post,
        {"x": 0, "y": 64, "z": 0},
    )
    assert not outside["passed"]
    assert "player_not_inside_protected_area" in outside["issues"]
    print("PASS: BM-010 rejects natural terrain, incomplete roofs, and unprotected player state")


if __name__ == "__main__":
    test_m2_protocol_is_fixed_and_exact()
    test_root_plan_schema_requires_ordered_dependent_subtasks()
    test_task_verifier_requires_observed_delta_and_action_proof()
    test_bm010_verifier_requires_episode_built_walls_roof_entrance_and_interior()
    print("M2 protocol tests PASSED")
