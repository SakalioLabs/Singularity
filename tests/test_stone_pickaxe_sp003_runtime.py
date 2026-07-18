from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from singularity.core.agent import Agent
from singularity.core.planner import Planner
from singularity.core.task_system import TaskStatus, TaskSystem
from singularity.evaluation.stone_pickaxe_protocol import PROTOCOL_SHA256
from singularity.evaluation.stone_pickaxe_sp002_runtime import (
    StonePickaxeRuntimeAgent as StonePickaxeSP002RuntimeAgent,
    build_runtime_config,
)
from singularity.evaluation.stone_pickaxe_sp003_runtime import (
    EXPECTED_SKILLS,
    SP003_GOAL,
    SP003_POLICY_PATH,
    SP003_RUNTIME_POLICY_ID,
    StonePickaxeSP003RuntimeAgent,
    _empty_progress,
    _merge_local_sp003_blocks,
    _navigation_inventory_proof,
    _progress_snapshot,
    _sp003_observation_targets,
    audit_sp003_initial_state,
    audit_sp003_reset,
    build_sp003_authorization,
    build_sp003_episode,
    build_sp003_runtime_config,
    guard_sp003_action,
    record_sp003_success,
    source_id,
    sp003_runtime_controls,
    verify_sp003_authorization,
    verify_sp003_policy_identity,
    verify_sp003_runtime_episode,
)


REPO = Path(__file__).resolve().parents[1]


class LogStub:
    def __init__(self):
        self.events = []

    def log(self, event_type, data, **_kwargs):
        self.events.append({"type": event_type, "data": data})


def block(name, x, y, z, distance):
    return {
        "name": name,
        "position": {"x": x, "y": y, "z": z},
        "distance": distance,
    }


def observation(
    inventory=None,
    blocks=None,
    *,
    held="",
    flags=None,
    position=None,
):
    equipment = [{"name": held, "count": 1}] if held else []
    return {
        "position": position or {"x": 0.0, "y": 64.0, "z": 0.0},
        "inventory": dict(inventory or {}),
        "equipment": equipment,
        "nearby_blocks": list(blocks or []),
        "nearby_entities": [],
        "flags": list(flags or []),
        "health": 20,
        "hunger": 20,
        "game_mode": "survival",
        "dimension": "overworld",
        "ground_block": "grass_block",
    }


def accepted_result(**updates):
    value = {
        "success": True,
        "action_verification": {"status": "accept"},
        "duration_ms": 100,
    }
    value.update(updates)
    return value


def test_policy_identity_binds_frozen_protocol_and_promoted_skills():
    report = verify_sp003_policy_identity()
    assert report["passed"], report
    assert report["protocol_sha256"] == PROTOCOL_SHA256
    assert report["policy_id"] == SP003_RUNTIME_POLICY_ID
    policy = json.loads(SP003_POLICY_PATH.read_text(encoding="utf-8"))
    assert policy["protocol"]["bytes_must_remain_unchanged"] is True
    assert policy["reset_substrate"]["reset_only"] is True
    assert policy["reset_substrate"]["bm012_terminal_execution_allowed"] is False
    assert [(item["skill_id"], item["version"]) for item in policy["skills"]] == [
        ("learned:acquire_cobblestone", "1.1.0"),
        ("learned:craft_stone_pickaxe", "1.0.1"),
    ]


def test_initial_state_requires_exact_empty_inventory_and_observed_log():
    logs = [block("oak_log", 2, 64, 0, 2.0)]
    passed = audit_sp003_initial_state(observation({}, logs))
    assert passed["passed"], passed
    contaminated = audit_sp003_initial_state(observation({"stick": 1}, logs))
    assert not contaminated["passed"]
    assert "inventory_exact_empty" in contaminated["issues"]
    missing = audit_sp003_initial_state(observation({}, []))
    assert "observed_log_source" in missing["issues"]


def test_reset_audit_accepts_natural_tick_drift_and_machine_proven_empty_fixture():
    evidence_dir = (
        REPO
        / "workspace/evals/sp003_runs/sp003_baseline_20260719_044130_998a5bbd"
    )
    status = json.loads((evidence_dir / "protocol_status.json").read_text(encoding="utf-8"))
    reset = json.loads((evidence_dir / "reset.json").read_text(encoding="utf-8"))
    report = audit_sp003_reset(
        status,
        reset,
        episode_id="sp003_baseline_20260719_044130_998a5bbd",
        level_name="sp003_baseline_20260719_044130_998a5bbd_world",
    )
    assert report["passed"], report

    fixture_tamper = copy.deepcopy(reset)
    fixture_tamper["after_state"]["fixture_blocks"] = [
        {"name": "crafting_table", "position": {"x": 97, "y": 144, "z": -32}}
    ]
    fixture_report = audit_sp003_reset(
        status,
        fixture_tamper,
        episode_id="sp003_baseline_20260719_044130_998a5bbd",
        level_name="sp003_baseline_20260719_044130_998a5bbd_world",
    )
    assert "no_fixture_blocks" in fixture_report["issues"]

    time_tamper = copy.deepcopy(reset)
    time_tamper["after_state"]["time_of_day"] = 601
    time_report = audit_sp003_reset(
        status,
        time_tamper,
        episode_id="sp003_baseline_20260719_044130_998a5bbd",
        level_name="sp003_baseline_20260719_044130_998a5bbd_world",
    )
    assert "daylight_start" in time_report["issues"]


def test_log_guard_uses_nearest_observed_same_family_and_stops_at_three():
    progress = _empty_progress()
    world = observation({}, [
        block("oak_log", 1, 64, 0, 1.0),
        block("birch_log", 2, 64, 0, 2.0),
    ])
    nearest = guard_sp003_action(
        {"type": "dig", "parameters": {"block": "oak_log", "x": 1, "y": 64, "z": 0}},
        world,
        progress,
    )
    assert nearest["allowed"], nearest
    result = accepted_result(
        block="oak_log",
        block_removed=True,
        pickup_observed=True,
        pickup_inventory_delta={"oak_log": 1},
    )
    record_sp003_success(progress, nearest["action"], result)
    mixed = guard_sp003_action(
        {"type": "dig", "parameters": {"block": "birch_log", "x": 2, "y": 64, "z": 0}},
        observation({"oak_log": 1}, [block("birch_log", 2, 64, 0, 2.0)]),
        progress,
    )
    assert not mixed["allowed"]
    assert "sp003_mixed_log_family_forbidden" in mixed["issues"]
    same_family = guard_sp003_action(
        {"type": "dig", "parameters": {"block": "oak_log", "x": 3, "y": 64, "z": 0}},
        observation(
            {"oak_log": 1},
            [
                block("birch_log", 2, 64, 0, 1.0),
                block("oak_log", 3, 64, 0, 2.0),
            ],
        ),
        progress,
    )
    assert same_family["allowed"], same_family
    progress["log_source_ids"] = {"oak_log:1:64:0", "oak_log:2:64:0", "oak_log:3:64:0"}
    stopped = guard_sp003_action(
        {"type": "dig", "parameters": {"block": "oak_log", "x": 4, "y": 64, "z": 0}},
        observation({"oak_log": 3}, [block("oak_log", 4, 64, 0, 2.0)]),
        progress,
    )
    assert not stopped["allowed"]
    assert any("stage:prepare_wooden_pickaxe" in issue for issue in stopped["issues"])


def preparation_progress():
    progress = _empty_progress()
    progress["log_source_ids"] = {"oak_log:1:64:0", "oak_log:2:64:0", "oak_log:3:64:0"}
    progress["log_item"] = "oak_log"
    return progress


def test_preparation_guard_enforces_exact_recipe_sequence_and_single_table():
    progress = preparation_progress()
    planks = guard_sp003_action(
        {"type": "craft", "parameters": {"item": "oak_planks", "count": 12}},
        observation({"oak_log": 3}),
        progress,
    )
    assert planks["allowed"], planks
    wrong = guard_sp003_action(
        {"type": "craft", "parameters": {"item": "birch_planks", "count": 12}},
        observation({"oak_log": 3}),
        progress,
    )
    assert not wrong["allowed"]

    progress["plank_craft_count"] = 1
    sticks = guard_sp003_action(
        {"type": "craft", "parameters": {"item": "stick", "count": 4}},
        observation({"oak_planks": 12}),
        progress,
    )
    assert sticks["allowed"], sticks
    progress["stick_craft_count"] = 1
    table = guard_sp003_action(
        {"type": "craft", "parameters": {"item": "crafting_table", "count": 1}},
        observation({"oak_planks": 10, "stick": 4}),
        progress,
    )
    assert table["allowed"], table
    progress["crafting_table_craft_count"] = 1
    references = [block("grass_block", 2, 63, 0, 2.2)]
    place = guard_sp003_action(
        {"type": "place", "parameters": {"item": "crafting_table", "x": 2, "y": 63, "z": 0}},
        observation({"oak_planks": 6, "stick": 4, "crafting_table": 1}, references),
        progress,
    )
    assert place["allowed"], place
    target_cell = guard_sp003_action(
        {
            "type": "place",
            "parameters": {"item": "crafting_table", "x": 2, "y": 64, "z": 0},
        },
        observation({"crafting_table": 1}, references),
        progress,
    )
    assert target_cell["allowed"], target_cell
    assert target_cell["action"]["parameters"] == {
        "item": "crafting_table",
        "x": 2,
        "y": 63,
        "z": 0,
        "reference_source_id": "grass_block:2:63:0",
    }
    progress["crafting_table_place_count"] = 1
    table_block = [block("crafting_table", 2, 64, 0, 2.0)]
    wooden = guard_sp003_action(
        {"type": "craft", "parameters": {"item": "wooden_pickaxe", "count": 1}},
        observation({"oak_planks": 6, "stick": 4}, table_block),
        progress,
    )
    assert wooden["allowed"], wooden
    duplicate_place = guard_sp003_action(
        {"type": "place", "parameters": {"item": "crafting_table", "x": 2, "y": 63, "z": 0}},
        observation({"crafting_table": 1}, table_block + references),
        progress,
    )
    assert not duplicate_place["allowed"]
    assert "sp003_duplicate_table_placement_forbidden" in duplicate_place["issues"]


def test_stone_guard_requires_held_wooden_pickaxe_nearest_source_and_exact_limit():
    progress = preparation_progress()
    progress.update({
        "plank_craft_count": 1,
        "stick_craft_count": 1,
        "crafting_table_craft_count": 1,
        "crafting_table_place_count": 1,
        "wooden_pickaxe_craft_count": 1,
    })
    stones = [block("stone", 1, 63, 0, 1.4), block("stone", 2, 63, 0, 2.2)]
    no_tool = guard_sp003_action(
        {"type": "dig", "parameters": {"block": "stone", "x": 1, "y": 63, "z": 0}},
        observation({"wooden_pickaxe": 1}, stones),
        progress,
    )
    assert "sp003_stone_dig_requires_held_wooden_pickaxe" in no_tool["issues"]
    farther = guard_sp003_action(
        {"type": "dig", "parameters": {"block": "stone", "x": 2, "y": 63, "z": 0}},
        observation({"wooden_pickaxe": 1}, stones, held="wooden_pickaxe"),
        progress,
    )
    assert "sp003_stone_target_must_be_nearest_observed" in farther["issues"]
    nearest = guard_sp003_action(
        {"type": "dig", "parameters": {"block": "stone", "x": 1, "y": 63, "z": 0}},
        observation({"wooden_pickaxe": 1}, stones, held="wooden_pickaxe"),
        progress,
    )
    assert nearest["allowed"], nearest
    support_safe_world = observation(
        {"wooden_pickaxe": 1},
        [
            block("stone", 0, 63, 0, 1.0),
            block("stone", 1, 63, 0, 1.4),
        ],
        held="wooden_pickaxe",
    )
    safe_targets = _sp003_observation_targets(support_safe_world, progress)
    assert [item["source_id"] for item in safe_targets] == ["stone:1:63:0"]
    below = guard_sp003_action(
        {"type": "dig", "parameters": {"block": "stone", "x": 0, "y": 63, "z": 0}},
        support_safe_world,
        progress,
    )
    assert not below["allowed"]
    assert "sp003_stone_target_must_be_reachable_and_observed" in below["issues"]
    progress["stone_source_ids"] = {"stone:1:63:0", "stone:2:63:0", "stone:3:63:0"}
    fourth = guard_sp003_action(
        {"type": "dig", "parameters": {"block": "stone", "x": 4, "y": 63, "z": 0}},
        observation({"wooden_pickaxe": 1, "cobblestone": 3}, [block("stone", 4, 63, 0, 2.0)], held="wooden_pickaxe"),
        progress,
    )
    assert not fourth["allowed"]
    assert any("stage:craft_stone_pickaxe" in issue for issue in fourth["issues"])


def test_stone_pickaxe_guard_rejects_iron_and_requires_exact_terminal_craft():
    progress = preparation_progress()
    progress.update({
        "plank_craft_count": 1,
        "stick_craft_count": 1,
        "crafting_table_craft_count": 1,
        "crafting_table_place_count": 1,
        "wooden_pickaxe_craft_count": 1,
        "stone_source_ids": {"stone:1:63:0", "stone:2:63:0", "stone:3:63:0"},
    })
    table = [block("crafting_table", 2, 64, 0, 2.0)]
    craft = guard_sp003_action(
        {"type": "craft", "parameters": {"item": "stone_pickaxe", "count": 1}},
        observation({"wooden_pickaxe": 1, "cobblestone": 3, "stick": 2}, table, held="wooden_pickaxe"),
        progress,
    )
    assert craft["allowed"], craft
    wrong_count = guard_sp003_action(
        {"type": "craft", "parameters": {"item": "stone_pickaxe", "count": 2}},
        observation({"wooden_pickaxe": 1, "cobblestone": 3, "stick": 2}, table, held="wooden_pickaxe"),
        progress,
    )
    assert not wrong_count["allowed"]
    iron = guard_sp003_action(
        {"type": "dig", "parameters": {"block": "iron_ore", "x": 1, "y": 63, "z": 0}},
        observation({"wooden_pickaxe": 1}, [block("iron_ore", 1, 63, 0, 1.4)], held="wooden_pickaxe"),
        progress,
    )
    assert "iron_mining_forbidden" in iron["issues"]


def test_progress_only_advances_on_verified_machine_success():
    progress = _empty_progress()
    action = {
        "type": "dig",
        "parameters": {
            "block": "oak_log",
            "x": 1,
            "y": 64,
            "z": 0,
            "source_id": "oak_log:1:64:0",
        },
    }
    record_sp003_success(progress, action, {"success": True})
    assert _progress_snapshot(progress)["log_source_removal_count"] == 0
    record_sp003_success(
        progress,
        action,
        accepted_result(
            block="oak_log",
            block_removed=True,
            pickup_observed=True,
            pickup_inventory_delta={"oak_log": 1},
        ),
    )
    assert _progress_snapshot(progress)["log_source_removal_count"] == 1
    record_sp003_success(progress, action, accepted_result(block_removed=False))
    assert _progress_snapshot(progress)["log_source_removal_count"] == 1


def test_third_baseline_reviewed_plank_transition_unblocks_exact_stick_craft():
    session_path = (
        REPO
        / "workspace/evals/sp003_runs/sp003_baseline_20260719_051736_a27843f7/session.json"
    )
    events = json.loads(session_path.read_text(encoding="utf-8"))
    plank_event = next(
        event["data"]
        for event in events
        if event.get("type") == "action"
        and event.get("data", {}).get("action", {}).get("parameters", {}).get("item")
        == "dark_oak_planks"
    )
    action = plank_event["action"]
    result = plank_event["result"]
    assert result["action_verification"]["status"] == "review"
    assert result["inventory_signed_delta"] == {
        "dark_oak_log": -3,
        "dark_oak_planks": 12,
    }

    progress = _empty_progress()
    progress["log_source_ids"] = {
        "dark_oak_log:93:142:-31",
        "dark_oak_log:94:141:-31",
        "dark_oak_log:94:142:-31",
    }
    progress["log_item"] = "dark_oak_log"
    after = record_sp003_success(progress, action, result)

    assert after["plank_craft_count"] == 1
    assert after["successful_mutation_count"] == 1
    sticks = guard_sp003_action(
        {"type": "craft", "parameters": {"item": "stick", "count": 4}},
        observation(result["inventory_after"]),
        progress,
    )
    assert sticks["allowed"], sticks


def test_reviewed_craft_without_exact_machine_delta_fails_closed():
    progress = preparation_progress()
    action = {
        "type": "craft",
        "parameters": {"item": "oak_planks", "count": 12},
    }
    result = accepted_result(
        action_verification={"status": "review"},
        item="oak_planks",
        count=12,
        requested_output_count=12,
        craft_attempts=1,
        craft_retry_count=0,
        inventory_delta={"oak_planks": 12},
        inventory_signed_delta={"oak_log": -3, "oak_planks": 11},
    )

    after = record_sp003_success(progress, action, result)

    assert after["plank_craft_count"] == 0
    assert after["successful_mutation_count"] == 0


def test_machine_proven_table_position_can_be_used_for_bounded_return_navigation():
    progress = preparation_progress()
    progress.update({
        "plank_craft_count": 1,
        "stick_craft_count": 1,
        "crafting_table_craft_count": 1,
    })
    action = {
        "type": "place",
        "parameters": {"item": "crafting_table", "x": 2, "y": 63, "z": 0},
    }
    record_sp003_success(
        progress,
        action,
        accepted_result(
            item="crafting_table",
            requested_item_equipped=True,
            placed_position={"x": 2, "y": 64, "z": 0},
            target_block_after={"name": "crafting_table"},
        ),
    )
    progress["wooden_pickaxe_craft_count"] = 1
    progress["stone_source_ids"] = {
        "stone:1:63:0",
        "stone:2:63:0",
        "stone:3:63:0",
    }
    remote = observation(
        {"wooden_pickaxe": 1, "cobblestone": 3, "stick": 2},
        [],
        held="wooden_pickaxe",
        position={"x": 12.0, "y": 64.0, "z": 0.0},
    )
    targets = _sp003_observation_targets(remote, progress)
    assert targets == [{
        "source_id": "crafting_table:2:64:0",
        "name": "crafting_table",
        "position": {"x": 2.0, "y": 64.0, "z": 0.0},
        "distance": 10.0,
        "machine_proven_placement": True,
    }]
    guarded = guard_sp003_action(
        {"type": "move_to", "parameters": {"x": 2, "y": 64, "z": 0}},
        remote,
        progress,
    )
    assert guarded["allowed"], guarded
    assert guarded["action"]["parameters"]["preserve_inventory"] is True
    assert "y" not in guarded["action"]["parameters"]


def test_local_sp003_scan_keeps_multiple_stone_sources_ahead_of_global_diversity():
    world = observation(
        {},
        [block("stone", 20, 61, 0, 20.2), block("iron_ore", 4, 63, 0, 4.2)],
    )
    local = [
        block("stone", 1, 63, 0, 1.4),
        block("stone", 2, 63, 0, 2.2),
        block("stone", 1, 62, 0, 2.4),
    ]

    merged = _merge_local_sp003_blocks(world, local)

    assert [source_id(item["name"], item["position"]) for item in merged[:3]] == [
        "stone:1:63:0",
        "stone:2:63:0",
        "stone:1:62:0",
    ]
    assert len([item for item in merged if item["name"] == "stone"]) == 4


def test_planner_compacts_sp003_state_and_requires_exact_five_node_graph():
    policy = json.loads(SP003_POLICY_PATH.read_text(encoding="utf-8"))
    world = observation({}, [block("oak_log", 2, 64, 0, 2.0)])
    world.update({
        "stone_pickaxe_runtime_mode": "sp003",
        "sp003_arm": "baseline",
        "flags": ["sp003_wood_acquired"],
        "sp003_progress": {"log_source_removal_count": 3},
        "sp003_targets": [{"name": "oak_log", "position": {"x": 2, "y": 64, "z": 0}}],
    })
    compact = Planner._compact_stone_pickaxe_state(world)
    assert compact["runtime_mode"] == "sp003"
    assert compact["flags"] == ["sp003_wood_acquired"]
    assert compact["sp003_progress"]["log_source_removal_count"] == 3
    assert compact["sp003_targets"][0]["name"] == "oak_log"
    valid = {
        "schema_version": "stone-pickaxe-plan-v1",
        "plan_kind": "root",
        "goal": SP003_GOAL,
        "status": "planning",
        "reasoning": "Start with the nearest observed log.",
        "subtasks": policy["task_graph"],
        "actions": [{"type": "dig", "parameters": {"block": "oak_log", "x": 2, "y": 64, "z": 0}}],
    }
    assert Planner._validate_stone_pickaxe_plan_envelope(valid, SP003_GOAL, "root", "sp003")["passed"]
    drifted = copy.deepcopy(valid)
    drifted["subtasks"][0]["title"] = "Gather some wood"
    report = Planner._validate_stone_pickaxe_plan_envelope(drifted, SP003_GOAL, "root", "sp003")
    assert not report["passed"]
    assert "sp003_exact_root_graph_required" in report["issues"]
    planner = object.__new__(Planner)
    planner._expected_plan_kind = "continuation"
    prompt = Planner._stone_pickaxe_system_prompt(planner)
    assert "never add 1 to y or emit target_position" in prompt
    assert "when it exceeds 4.5, emit move_to with only that target's x and z" in prompt
    assert "Never dig a block directly below the player" in prompt


def test_fourth_baseline_return_move_replays_as_horizontal_inventory_preserving_navigation():
    session_path = (
        REPO
        / "workspace/evals/sp003_runs/sp003_baseline_20260719_055541_f863c62c/session.json"
    )
    events = json.loads(session_path.read_text(encoding="utf-8"))
    action_events = [event for event in events if event.get("type") == "action"]
    returned = action_events[21]
    before = returned["data"]["pre_observation"]
    after = returned["data"]["post_observation"]
    assert before["inventory"]["dirt"] == 3
    assert before["inventory"]["cobblestone"] == 3
    assert "dirt" not in after["inventory"]
    assert "cobblestone" not in after["inventory"]
    assert any(
        item.get("name") == "cobblestone"
        and item.get("position") == {"x": 94, "y": 141, "z": -31}
        for item in after["nearby_blocks"]
    )
    retained_proof = _navigation_inventory_proof(
        before["inventory"],
        after["inventory"],
    )
    assert not retained_proof["passed"]
    assert retained_proof["inventory_losses"] == {
        "cobblestone": -3,
        "dirt": -3,
    }
    progress_event = next(
        event
        for event in reversed(events[: events.index(returned)])
        if event.get("type") == "stone_pickaxe_sp003_progress"
    )
    guarded = guard_sp003_action(
        returned["data"]["action"],
        before,
        progress_event["data"]["after"],
    )
    assert guarded["allowed"], guarded
    assert guarded["action"]["parameters"] == {
        "x": 93,
        "z": -31,
        "preserve_inventory": True,
    }


def test_navigation_feedback_fails_closed_on_loss_and_reuses_one_post_observation(monkeypatch):
    agent = StonePickaxeSP003RuntimeAgent.__new__(StonePickaxeSP003RuntimeAgent)
    agent.session_logger = LogStub()
    agent._sp003_feedback_observation_override = None
    post = observation({"wooden_pickaxe": 1, "stick": 2})
    observations = []

    def observe_once():
        observations.append(True)
        return copy.deepcopy(post)

    agent._observe = observe_once

    def consume_cached_observation(self, _action, _result, _fallback, _context=None):
        cached = copy.deepcopy(self._sp003_feedback_observation_override)
        self._sp003_feedback_observation_override = None
        return cached

    monkeypatch.setattr(
        StonePickaxeSP002RuntimeAgent,
        "_apply_action_feedback",
        consume_cached_observation,
    )
    action = {
        "type": "move_to",
        "parameters": {"x": 2, "z": 0, "preserve_inventory": True},
    }
    result = {"success": True, "reached": True}
    before = observation({"wooden_pickaxe": 1, "stick": 2, "cobblestone": 3})

    observed = StonePickaxeSP003RuntimeAgent._apply_action_feedback(
        agent,
        action,
        result,
        before,
    )

    assert observed == post
    assert len(observations) == 1
    assert result["success"] is False
    assert result["inventory_preservation"]["inventory_losses"] == {"cobblestone": -3}
    assert agent.session_logger.events[-1]["type"] == (
        "stone_pickaxe_sp003_navigation_inventory_preservation"
    )


def test_stone_pickaxe_reconciliation_accepts_flags_only_for_sp003():
    task_system = TaskSystem()
    task = task_system.create_task(
        "Acquire exactly three logs from empty hands",
        status=TaskStatus.ACCEPTED,
        success_criteria={"flags": ["sp003_wood_acquired"]},
    )
    agent = StonePickaxeSP003RuntimeAgent.__new__(StonePickaxeSP003RuntimeAgent)
    agent.config = SimpleNamespace(planner_protocol="stone-pickaxe-skill-fixed-v1")
    agent.stone_pickaxe_runtime_mode = "sp003"
    agent.task_system = task_system
    agent.session_logger = LogStub()
    agent._flush_task_state_transitions = lambda _context: None
    completed = StonePickaxeSP003RuntimeAgent._reconcile_stone_pickaxe_satisfied_tasks(
        agent,
        {"flags": ["sp003_wood_acquired"]},
        SP003_GOAL,
        1,
    )
    assert [item.id for item in completed] == [task.id]
    assert task.status == TaskStatus.COMPLETED


def test_runtime_config_uses_no_skills_for_baseline_and_both_approved_gates_for_candidate(tmp_path):
    base = build_runtime_config(
        api_key="test",
        log_dir=str(tmp_path),
        host="127.0.0.1",
        port=25565,
        username="Singularity",
        bridge_host="127.0.0.1",
        bridge_port=30000,
    )
    baseline = build_sp003_runtime_config(base_config=base, arm="baseline")
    assert baseline.skill_execution_mode == "off"
    assert baseline.skill_runtime_default_gate_paths == []
    candidate = build_sp003_runtime_config(base_config=base, arm="candidate")
    assert candidate.skill_execution_mode == "runtime"
    assert candidate.enable_skill_frontier_routing is True
    assert len(candidate.skill_runtime_default_gate_paths) == 2
    controls = sp003_runtime_controls(candidate, arm="candidate")
    assert controls["skill_library_persistence"] is False
    assert controls["skill_learning_ledger_write"] is False
    agent = StonePickaxeSP003RuntimeAgent(candidate, arm="candidate")
    profile = agent.skill_library.skill_runtime_default_profile()
    assert set(profile["approved_skills"]) == {
        "learned_acquire_cobblestone",
        "learned_craft_stone_pickaxe",
    }
    mining_observation = observation(
        {"wooden_pickaxe": 1, "stick": 2},
        [block("stone", 1, 63, 0, 1.4)],
        held="wooden_pickaxe",
    )
    mining = agent.skill_library.select_runtime_skill(
        "Mine exactly three stone blocks for cobblestone",
        mining_observation,
        execution_mode="runtime",
    )
    assert (mining.skill_id, mining.version) == (
        "learned:acquire_cobblestone",
        "1.1.0",
    )
    craft = agent.skill_library.select_runtime_skill(
        "Craft exactly one stone pickaxe",
        observation(
            {"cobblestone": 3, "stick": 2},
            [block("crafting_table", 1, 64, 0, 1.0)],
        ),
        execution_mode="runtime",
    )
    assert (craft.skill_id, craft.version) == (
        "learned:craft_stone_pickaxe",
        "1.0.1",
    )
    assert agent.skill_library.select_runtime_skill(
        "Acquire exactly three logs from empty hands",
        observation({}, [block("oak_log", 1, 64, 0, 1.0)]),
        execution_mode="runtime",
    ) is None


def test_candidate_routes_equip_through_planner_before_acquire_skill():
    agent = StonePickaxeSP003RuntimeAgent.__new__(StonePickaxeSP003RuntimeAgent)
    agent.sp003_arm = "candidate"
    agent.sp003_progress = preparation_progress()
    agent.sp003_progress.update({
        "plank_craft_count": 1,
        "stick_craft_count": 1,
        "crafting_table_craft_count": 1,
        "crafting_table_place_count": 1,
        "wooden_pickaxe_craft_count": 1,
    })
    agent._active_skill_execution = {}
    assert StonePickaxeSP003RuntimeAgent._learned_skill_plan(
        agent,
        "Mine exactly three stone blocks for cobblestone",
        observation(
            {"wooden_pickaxe": 1, "stick": 2},
            [block("stone", 5, 63, 0, 5.0)],
        ),
    ) is None
    guarded = guard_sp003_action(
        {
            "type": "move_to",
            "parameters": {"x": 5.0, "z": 0.0, "tolerance": 1.75},
        },
        observation(
            {"wooden_pickaxe": 1, "stick": 2},
            [block("stone", 5, 63, 0, 5.0)],
            held="wooden_pickaxe",
        ),
        agent.sp003_progress,
    )
    assert guarded["allowed"], guarded


def test_authorization_is_parent_bound_one_use_and_candidate_requires_prior_manifest():
    parent = "1" * 40
    current = "2" * 40
    authorization = build_sp003_authorization(
        arm="baseline",
        replicate_id="baseline",
        episode_id="sp003_baseline_test",
        authorization_predecessor=parent,
    )
    report = verify_sp003_authorization(
        authorization,
        expected_arm="baseline",
        expected_replicate_id="baseline",
        expected_episode_id="sp003_baseline_test",
        current_head=current,
        parent_head=parent,
    )
    assert report["passed"], report
    reused = verify_sp003_authorization(
        authorization,
        expected_arm="baseline",
        expected_replicate_id="baseline",
        expected_episode_id="sp003_baseline_test",
        current_head=parent,
        parent_head=parent,
    )
    assert not reused["passed"]
    with pytest.raises(ValueError):
        build_sp003_authorization(
            arm="candidate",
            replicate_id="r1",
            episode_id="sp003_candidate_r1",
            authorization_predecessor=parent,
        )


def test_multiskill_rollover_finalizes_first_component_and_routes_second(monkeypatch):
    agent = StonePickaxeSP003RuntimeAgent.__new__(StonePickaxeSP003RuntimeAgent)
    agent._m2_skill_contribution_complete = True
    agent._active_skill_execution = {
        "skill_id": "learned:acquire_cobblestone",
        "route_goal": "Acquire exactly three cobblestone with the wooden pickaxe",
    }
    calls = []
    plans = [None, {"status": "in_progress", "actions": [{"type": "craft"}]}]

    def fake_plan(_self, goal, _observation):
        calls.append(goal)
        return plans.pop(0)

    finalized = []
    agent._finalize_active_skill_outcome = lambda *args: finalized.append(args)
    monkeypatch.setattr(Agent, "_learned_skill_plan", fake_plan)
    result = StonePickaxeSP003RuntimeAgent._learned_skill_plan(
        agent,
        "Craft exactly one stone pickaxe",
        {"inventory": {"cobblestone": 3, "stick": 2}},
    )
    assert result["status"] == "in_progress"
    assert len(calls) == 2
    assert len(finalized) == 1
    assert agent._active_skill_execution == {}
    assert agent._m2_skill_contribution_complete is False


def task_graph_fixture():
    policy = json.loads(SP003_POLICY_PATH.read_text(encoding="utf-8"))
    ids = {node["id"]: f"task-{index}" for index, node in enumerate(policy["task_graph"], start=1)}
    tasks = []
    for node in policy["task_graph"]:
        tasks.append({
            "id": ids[node["id"]],
            "title": node["title"],
            "status": "completed",
            "plan_node_id": node["id"],
            "preconditions": node["preconditions"],
            "success_criteria": node["success_criteria"],
            "depends_on": [ids[item] for item in node["depends_on"]],
        })
    return {"task_count": 5, "tasks": tasks, "transitions": [], "sha256": "0" * 64}


def action_event(index, action, before, after, **result_updates):
    result = accepted_result(
        action_started_monotonic=100.0 + index,
        action_finished_monotonic=100.5 + index,
    )
    result.update(result_updates)
    return {
        "type": "action",
        "elapsed_s": float(index),
        "data": {
            "action": action,
            "result": result,
            "pre_observation": before,
            "post_observation": after,
        },
    }


def craft_event(index, item, count, before, after, *, table_position=None):
    result = {
        "item": item,
        "requested_output_count": count,
        "craft_attempts": 1,
        "craft_retry_count": 0,
        "craft_calls": 1,
        "stable_ms": 750,
        "inventory_before": dict(before["inventory"]),
        "inventory_after": dict(after["inventory"]),
        "inventory_signed_delta": {
            key: after["inventory"].get(key, 0) - before["inventory"].get(key, 0)
            for key in sorted(set(before["inventory"]) | set(after["inventory"]))
            if after["inventory"].get(key, 0) != before["inventory"].get(key, 0)
        },
        "authoritative_inventory_refresh": {
            "policy_id": "crafting-table-window-items-inventory-refresh-v1",
            "attempted": table_position is not None,
            "success": table_position is not None,
            "authoritative": table_position is not None,
            "window_items_observed": table_position is not None,
            "source": "crafting_table_window_items",
            "inventory_after": dict(after["inventory"]),
        },
        "crafting_table_found": table_position is not None,
        "crafting_table_position": dict(table_position or {}),
    }
    return action_event(
        index,
        {"type": "craft", "parameters": {"item": item, "count": count}},
        before,
        after,
        **result,
    )


def synthetic_sp003_events():
    logs = [
        block("oak_log", 1, 64, 0, 1.0),
        block("oak_log", 2, 64, 0, 2.0),
        block("oak_log", 3, 64, 0, 3.0),
    ]
    states = [observation({}, logs)]
    events = []
    for index in range(1, 4):
        before = states[-1]
        remaining = logs[index:]
        after = observation({"oak_log": index}, remaining)
        params = {
            "block": "oak_log",
            "x": index,
            "y": 64,
            "z": 0,
            "source_id": f"oak_log:{index}:64:0",
        }
        events.append(action_event(
            index,
            {"type": "dig", "parameters": params},
            before,
            after,
            block="oak_log",
            target={"x": index, "y": 64, "z": 0},
            target_block_before={"name": "oak_log"},
            target_block_after={"name": "air"},
            block_removed=True,
            pickup_observed=True,
            pickup_inventory_delta={"oak_log": 1},
        ))
        states.append(after)

    after_planks = observation({"oak_planks": 12})
    events.append(craft_event(4, "oak_planks", 12, states[-1], after_planks))
    after_sticks = observation({"oak_planks": 10, "stick": 4})
    events.append(craft_event(5, "stick", 4, after_planks, after_sticks))
    after_table = observation({"oak_planks": 6, "stick": 4, "crafting_table": 1})
    events.append(craft_event(6, "crafting_table", 1, after_sticks, after_table))
    table_position = {"x": 2, "y": 64, "z": 0}
    table_blocks = [block("crafting_table", 2, 64, 0, 2.0)]
    placed = observation({"oak_planks": 6, "stick": 4}, table_blocks)
    events.append(action_event(
        7,
        {"type": "place", "parameters": {"item": "crafting_table", "x": 2, "y": 63, "z": 0}},
        after_table,
        placed,
        item="crafting_table",
        requested_item_equipped=True,
        placed_position=table_position,
        target_block_after={"name": "crafting_table"},
    ))
    wooden = observation({"oak_planks": 3, "stick": 2, "wooden_pickaxe": 1}, table_blocks)
    events.append(craft_event(8, "wooden_pickaxe", 1, placed, wooden, table_position=table_position))
    equipped = observation(
        {"oak_planks": 3, "stick": 2, "wooden_pickaxe": 1},
        table_blocks + [
            block("stone", 1, 63, 0, 1.4),
            block("stone", 2, 63, 0, 2.2),
            block("stone", 3, 63, 0, 3.2),
        ],
        held="wooden_pickaxe",
    )
    events.append(action_event(
        9,
        {"type": "equip", "parameters": {"item": "wooden_pickaxe"}},
        wooden,
        equipped,
        item="wooden_pickaxe",
    ))
    current = equipped
    for offset, index in enumerate(range(10, 13), start=1):
        before = current
        remaining_stones = [
            block("stone", number, 63, 0, float(number) + 0.2)
            for number in range(offset + 1, 4)
        ]
        inventory = {"oak_planks": 3, "stick": 2, "wooden_pickaxe": 1, "cobblestone": offset}
        after = observation(inventory, table_blocks + remaining_stones, held="wooden_pickaxe")
        params = {
            "block": "stone",
            "x": offset,
            "y": 63,
            "z": 0,
            "source_id": f"stone:{offset}:63:0",
        }
        events.append(action_event(
            index,
            {"type": "dig", "parameters": params},
            before,
            after,
            block="stone",
            target={"x": offset, "y": 63, "z": 0},
            target_block_before={"name": "stone"},
            target_block_after={"name": "air"},
            block_removed=True,
            pickup_observed=True,
            pickup_inventory_delta={"cobblestone": 1},
            dig_tool_equip={
                "passed": True,
                "equipped_tool": "wooden_pickaxe",
                "selected_tool": "wooden_pickaxe",
            },
            expected_drops=["cobblestone"],
            dig_postcondition={"passed": True},
        ))
        current = after
    terminal = observation(
        {"oak_planks": 3, "wooden_pickaxe": 1, "stone_pickaxe": 1},
        table_blocks,
        held="wooden_pickaxe",
    )
    events.append(craft_event(13, "stone_pickaxe", 1, current, terminal, table_position=table_position))
    return states[0], terminal, events


def build_passing_episode(monkeypatch):
    monkeypatch.setattr(
        "singularity.evaluation.stone_pickaxe_sp003_runtime.planner_request_controls_audit",
        lambda _events: {"passed": True, "issues": [], "call_count": 13},
    )
    initial, terminal, events = synthetic_sp003_events()
    goal_result = {
        "completed": True,
        "cycles": 13,
        "action_count": 13,
        "elapsed_s": 13.2,
        "episode_started_monotonic": 100.0,
        "episode_ended_monotonic": 113.6,
        "episode_deadline_monotonic": 400.0,
        "deadline_policy_id": "stone-pickaxe-hard-total-deadline-v1",
        "termination_reason": "goal_verified",
    }
    return build_sp003_episode(
        arm="baseline",
        replicate_id="baseline",
        episode_id="sp003_baseline_synthetic",
        session_id="session-sp003-baseline",
        session_sha256="a" * 64,
        level_name="sp003_baseline_synthetic_world",
        events=events,
        initial_observation=initial,
        stable_observation=terminal,
        initial_monotonic=100.0,
        stable_monotonic=114.0,
        goal_result=goal_result,
        reset_audit={"passed": True},
        authorization_path="workspace/evals/stone_pickaxe_sp003_next_authorization.json",
        authorization_sha256="b" * 64,
        authorization_preflight={"passed": True},
        task_graph=task_graph_fixture(),
        skill_store_sha256_before="c" * 64,
        skill_store_sha256_after="c" * 64,
    )


def test_synthetic_empty_hand_episode_passes_both_component_verifiers(monkeypatch):
    episode = build_passing_episode(monkeypatch)
    report = verify_sp003_runtime_episode(episode)
    assert report["passed"], report
    assert report["components"]["sp001"]["criteria_passed"] is True
    assert report["components"]["sp002"]["criteria_passed"] is True
    assert report["metrics"]["log_source_removal_count"] == 3
    assert report["metrics"]["stone_source_removal_count"] == 3


def test_candidate_requires_two_separate_exact_skill_attributions(monkeypatch):
    episode = build_passing_episode(monkeypatch)
    episode["arm"] = "candidate"
    episode["replicate_id"] = "r1"
    episode["sequence_position"] = 1
    episode["selected_skills"] = [
        {"skill_id": skill_id, "version": version, "status": "executable"}
        for skill_id, version in EXPECTED_SKILLS.items()
    ]
    episode["local_skill_attributions"] = [
        {"skill_id": skill_id, "version": version, "postconditions_met": True}
        for skill_id, version in EXPECTED_SKILLS.items()
    ]
    episode["skill_action_map"] = [
        {
            "skill_id": "learned:acquire_cobblestone",
            "version": "1.1.0",
            "action": "dig:stone",
            "success": True,
        },
        {
            "skill_id": "learned:craft_stone_pickaxe",
            "version": "1.0.1",
            "action": "craft:stone_pickaxe",
            "success": True,
        },
    ]
    passed = verify_sp003_runtime_episode(episode)
    assert passed["passed"], passed
    broken = copy.deepcopy(episode)
    broken["local_skill_attributions"] = broken["local_skill_attributions"][:1]
    rejected = verify_sp003_runtime_episode(broken)
    assert not rejected["passed"]
    assert "candidate_separate_local_attribution" in rejected["criteria_issues"]


def test_verifier_fails_closed_on_overdig_wrong_family_or_skill_store_mutation(monkeypatch):
    episode = build_passing_episode(monkeypatch)
    overdig = copy.deepcopy(episode)
    overdig["action_type_counts"]["dig:stone"] = 4
    assert "exact_three_stone_actions" in verify_sp003_runtime_episode(overdig)["criteria_issues"]
    wrong_family = copy.deepcopy(episode)
    wrong_family["log_transition_proofs"][1]["source_block"] = "dirt"
    assert "log_transition_machine_proof" in verify_sp003_runtime_episode(wrong_family)["criteria_issues"]
    malformed = copy.deepcopy(episode)
    malformed["craft_backend_proofs"][0] = None
    assert "all_crafts_single_verified_attempt" in verify_sp003_runtime_episode(malformed)["criteria_issues"]
    mutated = copy.deepcopy(episode)
    mutated["skill_store_sha256_after"] = "d" * 64
    assert "skill_store_immutable" in verify_sp003_runtime_episode(mutated)["criteria_issues"]


def test_goal_machine_verifier_requires_exact_completed_graph():
    agent = StonePickaxeSP003RuntimeAgent.__new__(StonePickaxeSP003RuntimeAgent)
    agent.sp003_progress = preparation_progress()
    agent.sp003_progress.update({
        "plank_craft_count": 1,
        "stick_craft_count": 1,
        "crafting_table_craft_count": 1,
        "crafting_table_place_count": 1,
        "wooden_pickaxe_craft_count": 1,
        "stone_source_ids": {"stone:1:63:0", "stone:2:63:0", "stone:3:63:0"},
        "stone_pickaxe_craft_count": 1,
    })
    agent.task_system = TaskSystem()
    policy = json.loads(SP003_POLICY_PATH.read_text(encoding="utf-8"))
    previous = None
    for node in policy["task_graph"]:
        task = agent.task_system.create_task(
            node["title"],
            task_type=node["type"],
            status=TaskStatus.COMPLETED,
            preconditions=node["preconditions"],
            success_criteria=node["success_criteria"],
            depends_on=[previous.id] if previous else [],
            plan_node_id=node["id"],
        )
        previous = task
    agent._episode_deadline_monotonic = None
    agent._log_goal_verification = lambda *_args, **_kwargs: None
    achieved, verification = StonePickaxeSP003RuntimeAgent._goal_is_verified(
        agent,
        SP003_GOAL,
        observation({"stone_pickaxe": 1}),
    )
    assert achieved, verification.to_dict()
    previous.status = TaskStatus.FAILED
    achieved, verification = StonePickaxeSP003RuntimeAgent._goal_is_verified(
        agent,
        SP003_GOAL,
        observation({"stone_pickaxe": 1}),
    )
    assert not achieved
    assert "task_graph_complete" in verification.missing


def test_sp003_runner_and_launcher_enforce_fresh_single_episode_contract():
    runner = (REPO / "scripts/stone_pickaxe_sp003_episode_runner.py").read_text(
        encoding="utf-8"
    )
    launcher = (REPO / "scripts/stone-pickaxe-sp003-runtime.ps1").read_text(
        encoding="utf-8-sig"
    )
    assert "SP-003 evidence must use workspace/evals/sp003_runs/<episode_id>" in runner
    assert 'expected_level_name = f"{args.episode_id}_world"' in runner
    assert '"automatic_retry_allowed": False' in runner
    assert "skill_runtime_default_profile()" in runner
    assert ".runtime_default_gate_profile()" not in runner
    assert '"--craft-max-attempts", "1"' in launcher
    assert '"--require", "./src/bot/sp003_inventory_preserving_navigation.js"' in launcher
    assert "Assert-FreshRuntimePaths" in launcher
    assert "Assert-CleanSynchronizedMain" in launcher
    assert "automatic retry is forbidden" in launcher
