from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from singularity.core.agent import Agent
from singularity.core.planner import Planner
from singularity.core.task_system import TaskStatus, TaskSystem
from singularity.evaluation.stone_pickaxe_protocol import PROTOCOL_SHA256, canonical_sha256
from singularity.evaluation.stone_pickaxe_sp002_runtime import (
    StonePickaxeRuntimeAgent as StonePickaxeSP002RuntimeAgent,
    build_runtime_config,
)
from singularity.evaluation.stone_pickaxe_sp003_runtime import (
    EXPECTED_SKILLS,
    SP003_CLEARANCE_SCAN_RESPONSE_LIMIT,
    SP003_CLEARANCE_SHAFT_MAX,
    SP003_FROZEN_BRIDGE_SHA256,
    SP003_EXACT_GOALNEAR_COMPLETION_GROUNDING_POLICY_ID,
    SP003_GOAL,
    SP003_GOALBLOCK_COMPLETION_GROUNDING_POLICY_ID,
    SP003_GOALBLOCK_NUDGE_MAX_PULSES,
    SP003_GOALBLOCK_NUDGE_PULSE_MS,
    SP003_PATHFINDER_STOP_DRAIN_POLICY_ID,
    SP003_POLICY_PATH,
    SP003_PRE_DIG_PICKUP_ACCESS_POLICY_ID,
    SP003_RUNTIME_POLICY_ID,
    SP003_SURFACE_CLEARANCE_MAX,
    StonePickaxeSP003RuntimeAgent,
    _bounded_complete_local_scan,
    _empty_progress,
    _merge_local_sp003_blocks,
    _navigation_inventory_proof,
    _progress_snapshot,
    _sp003_observation_targets,
    _stone_approach_stands,
    _stone_pickup_accesses,
    _stone_surface_clearances,
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


def prioritize_block_response(blocks, limit=50):
    ordered = sorted(blocks, key=lambda item: item["distance"])
    selected = []
    selected_indexes = set()
    selected_names = set()
    for index, item in enumerate(ordered):
        if item["name"] in selected_names:
            continue
        selected.append(item)
        selected_indexes.add(index)
        selected_names.add(item["name"])
        if len(selected) >= limit:
            return selected
    for index, item in enumerate(ordered):
        if index in selected_indexes:
            continue
        selected.append(item)
        if len(selected) >= limit:
            break
    return selected


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
    assert policy["episode_contract"]["surface_clearance_actions_max"] == 6
    assert policy["episode_contract"]["surface_clearance_actions_per_shaft_max"] == 3
    assert policy["episode_contract"]["pre_dig_pickup_access_policy_id"] == (
        SP003_PRE_DIG_PICKUP_ACCESS_POLICY_ID
    )
    assert policy["episode_contract"]["pre_dig_scan_response_limit"] == 50
    assert policy["episode_contract"]["crafting_table_tool_settlement_delay_ms"] == 1000
    assert (
        policy["episode_contract"]["crafting_table_tool_settlement_install_event"]
        == "inject_allowed"
    )
    assert (
        policy["episode_contract"][
            "crafting_table_tool_settlement_requires_synchronous_craft"
        ]
        is False
    )
    assert (
        policy["episode_contract"][
            "delayed_log_pickup_reconciliation_policy_id"
        ]
        == "sp003-delayed-log-pickup-reconciliation-v1"
    )
    assert policy["episode_contract"]["pending_removed_log_sources_max"] == 3
    assert policy["episode_contract"]["delayed_pickup_raw_failure_preserved"] is True
    assert policy["episode_contract"]["table_reference_repair_attempts_max"] == 1
    assert policy["episode_contract"]["move_target_cell_centered"] is True
    assert policy["episode_contract"]["move_continuous_tolerance"] == 1.6
    assert policy["episode_contract"]["pickup_goal_near_requested_range"] == 1
    assert policy["episode_contract"]["pickup_goal_near_effective_range"] == 0
    assert (
        policy["episode_contract"][
            "pickup_inventory_or_distance_grounding_required"
        ]
        is True
    )
    assert (
        policy["episode_contract"][
            "pickup_goalblock_completion_grounding_policy_id"
        ]
        == SP003_GOALBLOCK_COMPLETION_GROUNDING_POLICY_ID
    )
    assert policy["episode_contract"]["pickup_goalblock_recovery_pulse_ms"] == (
        SP003_GOALBLOCK_NUDGE_PULSE_MS
    )
    assert policy["episode_contract"]["pickup_goalblock_recovery_pulses_max"] == (
        SP003_GOALBLOCK_NUDGE_MAX_PULSES
    )
    assert (
        policy["episode_contract"][
            "pickup_goalblock_recovery_world_mutation_allowed"
        ]
        is False
    )
    assert (
        policy["episode_contract"][
            "move_exact_goalnear_completion_grounding_policy_id"
        ]
        == SP003_EXACT_GOALNEAR_COMPLETION_GROUNDING_POLICY_ID
    )
    assert (
        policy["episode_contract"][
            "move_exact_goalnear_post_resolve_is_end_required"
        ]
        is True
    )
    assert (
        policy["episode_contract"]["move_exact_goalnear_marked_transformed_only"]
        is True
    )
    assert policy["episode_contract"]["move_exact_goalnear_recovery_pulse_ms"] == (
        SP003_GOALBLOCK_NUDGE_PULSE_MS
    )
    assert policy["episode_contract"]["move_exact_goalnear_recovery_pulses_max"] == (
        SP003_GOALBLOCK_NUDGE_MAX_PULSES
    )
    assert (
        policy["episode_contract"][
            "move_exact_goalnear_recovery_world_mutation_allowed"
        ]
        is False
    )
    assert policy["episode_contract"]["move_unmarked_goal_near_unchanged"] is True
    assert policy["episode_contract"]["move_non_unit_goal_near_unchanged"] is True
    assert policy["episode_contract"]["pathfinder_stop_drain_policy_id"] == (
        SP003_PATHFINDER_STOP_DRAIN_POLICY_ID
    )
    assert (
        policy["episode_contract"]["pathfinder_stop_drain_process_local_only"]
        is True
    )
    assert (
        policy["episode_contract"]["pathfinder_stop_drain_after_original_stop"]
        is True
    )
    assert (
        policy["episode_contract"][
            "pathfinder_stop_drain_set_goal_null_required"
        ]
        is True
    )
    assert (
        policy["episode_contract"][
            "pathfinder_stop_drain_before_next_goto_required"
        ]
        is True
    )
    assert (
        policy["episode_contract"][
            "pathfinder_stop_drain_original_stop_calls_per_request_max"
        ]
        == 1
    )
    assert (
        policy["episode_contract"][
            "pathfinder_stop_drain_automatic_retry_allowed"
        ]
        is False
    )
    assert (
        policy["episode_contract"][
            "pathfinder_stop_drain_world_mutation_allowed"
        ]
        is False
    )
    assert (
        policy["episode_contract"][
            "pathfinder_stop_drain_original_errors_propagated"
        ]
        is True
    )
    assert (
        policy["episode_contract"][
            "pathfinder_stop_drain_shared_bridge_change_allowed"
        ]
        is False
    )
    assert policy["episode_contract"]["planner_state_policy_id"] == (
        "sp003-bounded-planner-state-v1"
    )
    assert policy["episode_contract"]["planner_state_authoritative_stage"] is True
    assert policy["episode_contract"]["planner_state_target_limit"] == 1
    assert policy["episode_contract"]["planner_state_clearance_proof_omitted"] is True
    assert policy["episode_contract"]["planner_state_compact_json_max_chars"] == 2500
    assert policy["episode_contract"]["planner_user_prompt_max_chars"] == 5000
    assert policy["episode_contract"]["planner_action_rewrite_allowed"] is False
    assert policy["episode_contract"]["planner_reasoning_limit_chars"] == 320
    assert policy["episode_contract"]["planner_move_to_schema_policy_id"] == (
        "sp003-horizontal-move-envelope-v1"
    )
    assert policy["episode_contract"]["planner_move_to_required_axes"] == ["x", "z"]
    assert policy["episode_contract"]["planner_move_to_optional_axes"] == ["y"]
    assert (
        policy["episode_contract"]["planner_move_to_optional_y_must_be_finite"]
        is True
    )
    assert policy["episode_contract"]["planner_look_at_required_axes"] == [
        "x",
        "y",
        "z",
    ]
    assert (
        policy["episode_contract"][
            "planner_non_sp003_move_to_required_axes_unchanged"
        ]
        is True
    )
    assert [(item["skill_id"], item["version"]) for item in policy["skills"]] == [
        ("learned:acquire_cobblestone", "1.1.0"),
        ("learned:craft_stone_pickaxe", "1.0.1"),
    ]


def test_policy_identity_rejects_eager_craft_settlement_installation():
    policy = json.loads(SP003_POLICY_PATH.read_text(encoding="utf-8"))
    eager = copy.deepcopy(policy)
    eager["episode_contract"]["crafting_table_tool_settlement_install_event"] = (
        "create_bot_return"
    )
    assert not verify_sp003_policy_identity(eager)["checks"][
        "interactive_craft_settlement_contract"
    ]

    synchronous = copy.deepcopy(policy)
    synchronous["episode_contract"][
        "crafting_table_tool_settlement_requires_synchronous_craft"
    ] = True
    assert not verify_sp003_policy_identity(synchronous)["checks"][
        "interactive_craft_settlement_contract"
    ]

    unbounded = copy.deepcopy(policy)
    unbounded["episode_contract"]["pending_removed_log_sources_max"] = 4
    assert not verify_sp003_policy_identity(unbounded)["checks"][
        "delayed_log_pickup_reconciliation_contract"
    ]

    hidden_failure = copy.deepcopy(policy)
    hidden_failure["episode_contract"]["delayed_pickup_raw_failure_preserved"] = False
    assert not verify_sp003_policy_identity(hidden_failure)["checks"][
        "delayed_log_pickup_reconciliation_contract"
    ]

    arbitrary_reference = copy.deepcopy(policy)
    arbitrary_reference["episode_contract"][
        "table_reference_repair_requires_observed_solid"
    ] = False
    assert not verify_sp003_policy_identity(arbitrary_reference)["checks"][
        "bounded_table_reference_repair_contract"
    ]

    uncentered_goal = copy.deepcopy(policy)
    uncentered_goal["episode_contract"]["move_target_cell_centered"] = False
    assert not verify_sp003_policy_identity(uncentered_goal)["checks"][
        "bounded_move_metric_alignment_contract"
    ]

    loose_pickup_goal = copy.deepcopy(policy)
    loose_pickup_goal["episode_contract"]["pickup_goal_near_effective_range"] = 1
    assert not verify_sp003_policy_identity(loose_pickup_goal)["checks"][
        "exact_unit_pickup_goal_contract"
    ]

    unbounded_planner_state = copy.deepcopy(policy)
    unbounded_planner_state["episode_contract"]["planner_state_target_limit"] = 8
    assert not verify_sp003_policy_identity(unbounded_planner_state)["checks"][
        "bounded_planner_state_contract"
    ]

    widened_move_schema = copy.deepcopy(policy)
    widened_move_schema["episode_contract"]["planner_move_to_optional_axes"] = [
        "y",
        "tolerance",
    ]
    assert not verify_sp003_policy_identity(widened_move_schema)["checks"][
        "mode_specific_move_schema_contract"
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


def test_phase85_retained_canopy_observation_selects_navigation_only_ground_egress():
    session_path = (
        REPO
        / "workspace/evals/sp003_runs/sp003_baseline_20260719_072552_4e3a282c/session.json"
    )
    events = json.loads(session_path.read_text(encoding="utf-8"))
    retained = copy.deepcopy(next(
        event["data"] for event in events if event.get("type") == "observation"
    ))
    progress = _empty_progress()

    targets = _sp003_observation_targets(retained, progress)

    assert targets[0] == {
        "source_id": "grass_block:121:141:-36",
        "name": "grass_block",
        "position": {"x": 121.0, "y": 141.0, "z": -36.0},
        "distance": 25.495098,
        "horizontal_distance": 24.909837,
        "stand_position": {"x": 121, "y": 142, "z": -36},
        "navigation_only": True,
        "canopy_egress": True,
    }
    move = guard_sp003_action(
        {"type": "move_to", "parameters": {"x": 121, "y": 141, "z": -36}},
        retained,
        progress,
    )
    assert move["allowed"], move
    assert move["action"]["parameters"] == {
        "x": 121,
        "y": 142,
        "z": -36,
        "preserve_inventory": True,
    }
    assert move["selected_source"]["canopy_egress"] is True


def test_phase85_canopy_guard_rejects_log_dig_and_fails_closed_without_ground_egress():
    progress = _empty_progress()
    canopy = observation(
        {},
        [block("dark_oak_log", 94, 142, -31, 3.0)],
        position={"x": 96.5, "y": 144.0, "z": -31.5},
    )
    canopy["ground_block"] = "dark_oak_leaves"

    assert _sp003_observation_targets(canopy, progress) == []
    obstructed = copy.deepcopy(canopy)
    obstructed["nearby_blocks"].extend([
        block("grass_block", 121, 141, -36, 25.495098),
        block("oak_leaves", 121, 142, -36, 25.317978),
    ])
    assert _sp003_observation_targets(obstructed, progress) == []
    direct = guard_sp003_action(
        {
            "type": "dig",
            "parameters": {"block": "dark_oak_log", "x": 94, "y": 142, "z": -31},
        },
        canopy,
        progress,
    )
    assert not direct["allowed"]
    assert "sp003_canopy_egress_required_before_log_dig" in direct["issues"]
    move_to_log = guard_sp003_action(
        {"type": "move_to", "parameters": {"x": 94, "z": -31}},
        canopy,
        progress,
    )
    assert not move_to_log["allowed"]
    assert "acquire_wood_navigation_target_must_be_observed" in move_to_log["issues"]

    grounded = copy.deepcopy(canopy)
    grounded["ground_block"] = "grass_block"
    allowed = guard_sp003_action(
        {
            "type": "dig",
            "parameters": {"block": "dark_oak_log", "x": 94, "y": 142, "z": -31},
        },
        grounded,
        progress,
    )
    assert allowed["allowed"], allowed


def preparation_progress():
    progress = _empty_progress()
    progress["log_source_ids"] = {"oak_log:1:64:0", "oak_log:2:64:0", "oak_log:3:64:0"}
    progress["log_item"] = "oak_log"
    return progress


def complete_block_scan(blocks, *, origin=None, radius=1):
    vertical_min = -3
    vertical_max = 3
    return {
        "type": "sp003_bounded_complete_nearby_block_scan",
        "schema_version": 1,
        "scan_complete": True,
        "targeted_air_visibility_complete": False,
        "radius": radius,
        "vertical_min_offset": vertical_min,
        "vertical_max_offset": vertical_max,
        "origin_cell": dict(origin or {"x": 0, "y": 64, "z": 0}),
        "origin_stable": True,
        "post_scan_player_cell": dict(origin or {"x": 0, "y": 64, "z": 0}),
        "scanned_cell_count": (2 * radius + 1) ** 2
        * (vertical_max - vertical_min + 1),
        "backend_path": "src/bot/bot_server.js",
        "backend_sha256": SP003_FROZEN_BRIDGE_SHA256,
        "response_limit": SP003_CLEARANCE_SCAN_RESPONSE_LIMIT,
        "response_count": len(blocks),
        "completeness_basis": "result_count_below_frozen_backend_limit",
        "priority_unique_name_prefix_count": 0,
        "visibility_distance_strict_upper_bound": None,
        "selection_trace_fingerprint": "",
        "blocks": copy.deepcopy(list(blocks)),
    }


def attach_complete_sp003_scan(world, blocks, *, origin):
    scan = complete_block_scan(blocks, origin=origin)
    world["sp003_complete_local_scan"] = scan
    world["sp003_stone_approach_stands"] = _stone_approach_stands(scan)
    world["sp003_stone_pickup_accesses"] = _stone_pickup_accesses(scan)
    world["sp003_stone_surface_clearances"] = _stone_surface_clearances(scan)
    return scan


def cobblestone_progress():
    progress = preparation_progress()
    progress.update({
        "plank_craft_count": 1,
        "stick_craft_count": 1,
        "crafting_table_craft_count": 1,
        "crafting_table_place_count": 1,
        "wooden_pickaxe_craft_count": 1,
        "wooden_pickaxe_equip_count": 1,
    })
    return progress


def test_complete_stone_scan_proves_clear_stand_and_fails_closed_when_obstructed():
    stone = block("stone", 1, 61, 0, 3.162278)
    clear_scan = complete_block_scan([stone], origin={"x": 0, "y": 64, "z": 0})

    approaches = _stone_approach_stands(clear_scan)

    assert approaches[0]["source_id"] == "stone:1:61:0"
    assert approaches[0]["stand_position"] == {"x": 1, "y": 62, "z": 0}
    assert approaches[0]["proof"]["head_position"] == {"x": 1, "y": 63, "z": 0}
    obstructed = copy.deepcopy(clear_scan)
    obstructed["blocks"].append(block("dirt", 1, 63, 0, 1.414214))
    obstructed["response_count"] += 1
    assert _stone_approach_stands(obstructed) == []
    incomplete = copy.deepcopy(clear_scan)
    incomplete["scan_complete"] = False
    assert _stone_approach_stands(incomplete) == []
    incomplete_count = copy.deepcopy(clear_scan)
    incomplete_count["scanned_cell_count"] -= 1
    assert _stone_approach_stands(incomplete_count) == []
    assert _stone_approach_stands(clear_scan["blocks"]) == []
    machine_report = _bounded_complete_local_scan(
        observation(position={"x": 0.5, "y": 64.0, "z": 0.5}),
        [stone],
    )
    assert machine_report["scan_complete"] is True
    assert machine_report["response_count"] == 1
    assert _bounded_complete_local_scan(
        observation(position={"x": 0.5, "y": 64.0, "z": 0.5}),
        [stone] * 64,
    ) == {}
    assert _bounded_complete_local_scan(
        observation(position={"x": 0.5, "y": 64.0, "z": 0.5}),
        [stone],
        {"position": {"x": 1.5, "y": 64.0, "z": 0.5}},
    ) == {}


def test_phase88_retained_stone_target_requires_grounded_navigation_before_dig():
    session_path = (
        REPO
        / "workspace/evals/sp003_runs/sp003_baseline_20260719_081246_b6ebff81/session.json"
    )
    events = json.loads(session_path.read_text(encoding="utf-8"))
    retained = copy.deepcopy(next(
        event["data"]
        for event in events
        if event.get("type") == "observation"
        and (event.get("data", {}).get("sp003_targets") or [{}])[0].get("source_id")
        == "stone:124:139:-37"
    ))
    progress = copy.deepcopy(retained["sp003_progress"])
    retained["sp003_stone_approach_stands"] = []

    targets = _sp003_observation_targets(retained, progress)

    assert targets[0]["source_id"] == "stone:124:139:-37"
    assert targets[0]["stone_clearance_probe"] is True
    assert targets[0]["navigation_only"] is True
    direct = guard_sp003_action(
        {
            "type": "dig",
            "parameters": {"block": "stone", "x": 124, "y": 139, "z": -37},
        },
        retained,
        progress,
    )
    assert not direct["allowed"]
    assert "sp003_stone_clearance_probe_required_before_dig" in direct["issues"]
    horizontal = guard_sp003_action(
        {"type": "move_to", "parameters": {"x": 124, "z": -37}},
        retained,
        progress,
    )
    assert horizontal["allowed"], horizontal
    assert horizontal["action"]["parameters"] == {
        "x": 124.5,
        "z": -36.5,
        "tolerance": 1.6,
        "preserve_inventory": True,
    }
    assert horizontal["action_repair"]["policy_id"] == (
        "sp003-goalnearxz-cell-metric-alignment-v1"
    )

    centered = copy.deepcopy(retained)
    centered["position"] = {"x": 124.5, "y": 142.0, "z": -36.5}
    local_blocks = [
        item
        for item in retained["nearby_blocks"]
        if source_id(item["name"], item["position"]) == "stone:124:139:-37"
    ]
    centered_scan = complete_block_scan(
        local_blocks,
        origin={"x": 124, "y": 142, "z": -37},
    )
    centered["sp003_complete_local_scan"] = centered_scan
    centered["sp003_stone_approach_stands"] = _stone_approach_stands(centered_scan)
    centered["sp003_stone_surface_clearances"] = _stone_surface_clearances(
        centered_scan
    )
    centered_targets = _sp003_observation_targets(centered, progress)
    assert centered_targets[0]["stand_position"] == {"x": 124, "y": 140, "z": -37}
    assert centered_targets[0]["stone_pickup_approach"] is True
    grounded_direct = guard_sp003_action(
        {
            "type": "dig",
            "parameters": {"block": "stone", "x": 124, "y": 139, "z": -37},
        },
        centered,
        progress,
    )
    assert not grounded_direct["allowed"]
    assert "sp003_stone_grounded_approach_required_before_dig" in grounded_direct["issues"]
    move = guard_sp003_action(
        {"type": "move_to", "parameters": {"x": 124, "z": -37}},
        centered,
        progress,
    )
    assert move["allowed"], move
    assert move["action"]["parameters"] == {
        "x": 124.5,
        "y": 140,
        "z": -36.5,
        "tolerance": 1.6,
        "preserve_inventory": True,
    }
    assert move["selected_source"]["stone_pickup_approach"] is True
    forged = copy.deepcopy(centered)
    forged["sp003_stone_approach_stands"][0]["proof"]["scan_complete"] = False
    assert _sp003_observation_targets(forged, progress) == []


def test_phase91_retained_buried_stone_is_cleared_top_down_with_three_machine_proofs():
    session_path = (
        REPO
        / "workspace/evals/sp003_runs/sp003_baseline_20260719_092557_f63c1161/session.json"
    )
    events = json.loads(session_path.read_text(encoding="utf-8"))
    retained = copy.deepcopy(next(
        event["data"]
        for event in events
        if event.get("type") == "observation"
        and event.get("data", {}).get("position", {}).get("z") == -37.5
        and (event.get("data", {}).get("equipment") or [{}])[0]
    ))
    progress = copy.deepcopy(retained["sp003_progress"])
    origin = {"x": 123, "y": 142, "z": -38}
    local_blocks = [
        item
        for item in retained["nearby_blocks"]
        if abs(item["position"]["x"] - origin["x"]) <= 1
        and origin["y"] - 3 <= item["position"]["y"] <= origin["y"] + 3
        and abs(item["position"]["z"] - origin["z"]) <= 1
    ]
    assert len(local_blocks) == 29
    attach_complete_sp003_scan(retained, local_blocks, origin=origin)

    targets = _sp003_observation_targets(retained, progress)
    assert targets[0]["source_id"] == "grass_block:124:142:-38"
    assert targets[0]["support_source_id"] == "stone:124:139:-38"
    assert targets[0]["stone_surface_clearance"] is True
    assert targets[0]["remaining_clearance_count"] == 3
    assert targets[0]["clearance_proof"]["response_count"] == 29
    assert targets[0]["clearance_proof"]["obstruction_source_ids_top_down"] == [
        "grass_block:124:142:-38",
        "dirt:124:141:-38",
        "dirt:124:140:-38",
    ]

    support_dig = guard_sp003_action(
        {
            "type": "dig",
            "parameters": {"block": "stone", "x": 124, "y": 139, "z": -38},
        },
        retained,
        progress,
    )
    assert not support_dig["allowed"]
    assert "sp003_stone_surface_clearance_required_before_dig" in support_dig["issues"]
    wrong_order = guard_sp003_action(
        {
            "type": "dig",
            "parameters": {"block": "dirt", "x": 124, "y": 141, "z": -38},
        },
        retained,
        progress,
    )
    assert not wrong_order["allowed"]
    assert any("machine_proven" in issue for issue in wrong_order["issues"])

    removed = set()
    expected = [
        ("grass_block", 142),
        ("dirt", 141),
        ("dirt", 140),
    ]
    for block_name, y in expected:
        current = copy.deepcopy(retained)
        current_blocks = [
            item
            for item in local_blocks
            if source_id(item["name"], item["position"]) not in removed
        ]
        current["nearby_blocks"] = [
            item
            for item in current["nearby_blocks"]
            if source_id(item["name"], item["position"]) not in removed
        ]
        attach_complete_sp003_scan(current, current_blocks, origin=origin)
        target = _sp003_observation_targets(current, progress)[0]
        assert target["name"] == block_name
        assert target["position"] == {"x": 124, "y": y, "z": -38}
        guarded = guard_sp003_action(
            {
                "type": "dig",
                "parameters": {"block": block_name, "x": 124, "y": y, "z": -38},
            },
            current,
            progress,
        )
        assert guarded["allowed"], guarded
        assert guarded["action"]["parameters"]["stone_surface_clearance"] is True
        assert guarded["action"]["parameters"]["support_source_id"] == "stone:124:139:-38"
        result = accepted_result(
            block=block_name,
            block_removed=True,
            target_block_before={"name": block_name},
            target_block_after={"name": "air"},
        )
        snapshot = record_sp003_success(progress, guarded["action"], result)
        removed.add(f"{block_name}:124:{y}:-38")
        assert snapshot["surface_clearance_removal_count"] == len(removed)

    opened = copy.deepcopy(retained)
    opened_blocks = [
        item
        for item in local_blocks
        if source_id(item["name"], item["position"]) not in removed
    ]
    opened["nearby_blocks"] = [
        item
        for item in opened["nearby_blocks"]
        if source_id(item["name"], item["position"]) not in removed
    ]
    attach_complete_sp003_scan(opened, opened_blocks, origin=origin)
    opened_target = _sp003_observation_targets(opened, progress)[0]
    assert opened_target["source_id"] == "stone:124:139:-38"
    assert opened_target["stone_pickup_approach"] is True
    assert opened_target["stand_position"] == {"x": 124, "y": 140, "z": -38}
    assert opened_target["clearance_proof"]["entry_shaft_cell_states"] == [
        "air",
        "air",
        "air",
    ]

    fourth_blocks = [
        block("stone", 1, 63, 0, 1.414214),
        block("stone", 1, 62, 0, 2.236068),
        block("dirt", 1, 64, 0, 1.0),
    ]
    fourth_world = observation(
        {"wooden_pickaxe": 1},
        fourth_blocks,
        held="wooden_pickaxe",
    )
    attach_complete_sp003_scan(
        fourth_world,
        fourth_blocks,
        origin={"x": 0, "y": 64, "z": 0},
    )
    fourth = guard_sp003_action(
        {
            "type": "dig",
            "parameters": {"block": "dirt", "x": 1, "y": 64, "z": 0},
        },
        fourth_world,
        progress,
    )
    assert fourth["allowed"], fourth
    record_sp003_success(
        progress,
        fourth["action"],
        accepted_result(
            block="dirt",
            block_removed=True,
            target_block_before={"name": "dirt"},
            target_block_after={"name": "air"},
        ),
    )
    assert _progress_snapshot(progress)["surface_clearance_removal_count"] == 4

    progress["surface_clearance_source_ids"].update({"dirt:2:64:0", "dirt:3:64:0"})
    seventh_blocks = [
        block("stone", -1, 63, 0, 1.414214),
        block("stone", -1, 62, 0, 2.236068),
        block("dirt", -1, 64, 0, 1.0),
    ]
    seventh_world = observation(
        {"wooden_pickaxe": 1},
        seventh_blocks,
        held="wooden_pickaxe",
    )
    attach_complete_sp003_scan(
        seventh_world,
        seventh_blocks,
        origin={"x": 0, "y": 64, "z": 0},
    )
    assert _sp003_observation_targets(seventh_world, progress) == []
    seventh = guard_sp003_action(
        {
            "type": "dig",
            "parameters": {"block": "dirt", "x": -1, "y": 64, "z": 0},
        },
        seventh_world,
        progress,
    )
    assert not seventh["allowed"]
    assert "sp003_surface_clearance_removal_limit_reached" in seventh["issues"]
    assert SP003_CLEARANCE_SHAFT_MAX == 3
    assert SP003_SURFACE_CLEARANCE_MAX == 6


def test_surface_clearance_scan_fails_closed_on_incomplete_forged_or_disallowed_geometry():
    support = block("stone", 1, 61, 0, 3.162278)
    allowed = complete_block_scan(
        [
            support,
            block("dirt", 1, 62, 0, 2.236068),
            block("dirt", 1, 63, 0, 1.414214),
            block("grass_block", 1, 64, 0, 1.0),
        ],
        origin={"x": 0, "y": 64, "z": 0},
    )
    clearances = _stone_surface_clearances(allowed)
    assert clearances[0]["source_id"] == "grass_block:1:64:0"

    incomplete = copy.deepcopy(allowed)
    incomplete["scan_complete"] = False
    assert _stone_surface_clearances(incomplete) == []
    truncated = copy.deepcopy(allowed)
    truncated["response_count"] += 1
    assert _stone_surface_clearances(truncated) == []
    duplicate = copy.deepcopy(allowed)
    duplicate["blocks"].append(copy.deepcopy(duplicate["blocks"][0]))
    duplicate["response_count"] += 1
    assert _stone_surface_clearances(duplicate) == []
    disallowed = copy.deepcopy(allowed)
    disallowed["blocks"][3]["name"] = "coarse_dirt"
    assert _stone_surface_clearances(disallowed) == []
    player_column = complete_block_scan(
        [
            block("stone", 0, 61, 0, 3.0),
            block("dirt", 0, 62, 0, 2.0),
        ],
        origin={"x": 0, "y": 64, "z": 0},
    )
    assert _stone_surface_clearances(player_column) == []

    world = observation(
        {"wooden_pickaxe": 1},
        copy.deepcopy(allowed["blocks"]),
        held="wooden_pickaxe",
        position={"x": 0.5, "y": 64.0, "z": 0.5},
    )
    progress = cobblestone_progress()
    world["sp003_complete_local_scan"] = allowed
    world["sp003_stone_approach_stands"] = []
    world["sp003_stone_surface_clearances"] = copy.deepcopy(clearances)
    world["sp003_stone_surface_clearances"][0]["clearance_proof"]["scan_complete"] = False
    assert _sp003_observation_targets(world, progress) == []


def test_radius_one_scan_uses_strict_priority_visibility_at_frozen_limit():
    world = observation(position={"x": 0.5, "y": 64.0, "z": 0.5})
    local_blocks = [
        block("dirt", x, y, z, math.sqrt(x * x + (y - 64) ** 2 + z * z))
        for x in range(-1, 2)
        for y in range(61, 68)
        for z in range(-1, 2)
    ]
    assert len(local_blocks) == 63

    full = _bounded_complete_local_scan(
        world,
        local_blocks[:49],
        {"position": {"x": 0.5, "y": 64.0, "z": 0.5}},
    )
    assert full["scan_complete"] is True
    assert full["targeted_air_visibility_complete"] is False
    assert full["response_count"] == 49
    assert full["response_limit"] == 50

    prioritized = prioritize_block_response(local_blocks)
    saturated = _bounded_complete_local_scan(
        world,
        prioritized,
        {"position": {"x": 0.5, "y": 64.0, "z": 0.5}},
    )
    assert saturated["scan_complete"] is False
    assert saturated["targeted_air_visibility_complete"] is True
    assert saturated["priority_unique_name_prefix_count"] == 1
    assert saturated["visibility_distance_strict_upper_bound"] > 1
    assert saturated["selection_trace_fingerprint"] == canonical_sha256(prioritized)

    forged_distances = copy.deepcopy(prioritized)
    for item in forged_distances:
        item["distance"] += 10
    assert _bounded_complete_local_scan(
        world,
        forged_distances,
        {"position": {"x": 0.5, "y": 64.0, "z": 0.5}},
    ) == {}

    assert _bounded_complete_local_scan(
        world,
        local_blocks[:51],
        {"position": {"x": 0.5, "y": 64.0, "z": 0.5}},
    ) == {}


def test_saturated_priority_trace_proves_near_head_air_and_observed_obstruction():
    origin = {"x": 0, "y": 64, "z": 0}
    target_cell = (1, 63, 0)
    support_cell = (1, 62, 0)
    head_cell = (1, 64, 0)
    excluded = {
        (0, 64, 0),
        (0, 65, 0),
        target_cell,
        support_cell,
        head_cell,
    }
    dense = [
        block(
            "dirt",
            x,
            y,
            z,
            math.sqrt(x * x + (y - 64) ** 2 + z * z),
        )
        for x in range(-1, 2)
        for y in range(61, 68)
        for z in range(-1, 2)
        if (x, y, z) not in excluded
    ]
    dense.extend([
        block("stone", *target_cell, math.sqrt(2)),
        block("stone", *support_cell, math.sqrt(5)),
    ])
    world = observation(
        {"wooden_pickaxe": 1},
        dense,
        held="wooden_pickaxe",
        position={"x": 0.5, "y": 64.0, "z": 0.5},
    )
    response = prioritize_block_response(dense)
    assert len(response) == 50
    scan = _bounded_complete_local_scan(world, response, world)
    assert scan["targeted_air_visibility_complete"] is True
    assert scan["visibility_distance_strict_upper_bound"] > 1
    access = next(
        item
        for item in _stone_pickup_accesses(scan)
        if item["source_id"] == "stone:1:63:0"
    )
    assert access["pickup_access_proof"]["scan_complete"] is False
    assert access["pickup_access_proof"]["head_cell_state"] == "air"
    assert len(access["pickup_access_proof"]["priority_selection_trace"]) == 50

    covered_dense = [*dense, block("dirt", *head_cell, 1.0)]
    covered_scan = _bounded_complete_local_scan(
        world,
        prioritize_block_response(covered_dense),
        world,
    )
    assert not any(
        item["source_id"] == "stone:1:63:0"
        for item in _stone_pickup_accesses(covered_scan)
    )
    clearance = next(
        item
        for item in _stone_surface_clearances(covered_scan)
        if item["support_source_id"] == "stone:1:63:0"
    )
    assert clearance["source_id"] == "dirt:1:64:0"


def test_grounded_stone_approach_excludes_anchor_and_allows_adjacent_stone_dig():
    progress = cobblestone_progress()
    local_blocks = [
        block("stone", 124, 139, -37, 1.0),
        block("stone", 125, 139, -37, 1.414214),
        block("stone", 124, 138, -37, 2.0),
        block("stone", 125, 138, -37, 2.236068),
    ]
    grounded = observation(
        {"wooden_pickaxe": 1},
        local_blocks,
        held="wooden_pickaxe",
        position={"x": 124.5, "y": 140.0, "z": -36.5},
    )
    attach_complete_sp003_scan(
        grounded,
        local_blocks,
        origin={"x": 124, "y": 140, "z": -37},
    )

    targets = _sp003_observation_targets(grounded, progress)

    assert [target["source_id"] for target in targets] == ["stone:125:139:-37"]
    assert targets[0]["stone_pickup_access"] is True
    adjacent = guard_sp003_action(
        {
            "type": "dig",
            "parameters": {"block": "stone", "x": 125, "y": 139, "z": -37},
        },
        grounded,
        progress,
    )
    assert adjacent["allowed"], adjacent
    assert adjacent["action"]["parameters"]["stone_pickup_access"] is True
    proof = adjacent["action"]["parameters"]["pickup_access_proof"]
    assert proof["support_position"] == {"x": 125, "y": 138, "z": -37}
    assert proof["head_position"] == {"x": 125, "y": 140, "z": -37}
    assert adjacent["action"]["parameters"]["pickup_access_proof_fingerprint"] == (
        canonical_sha256(proof)
    )

    covered = copy.deepcopy(grounded)
    covered_blocks = [*local_blocks, block("dirt", 125, 140, -37, 1.0)]
    covered["nearby_blocks"] = covered_blocks
    attach_complete_sp003_scan(
        covered,
        covered_blocks,
        origin={"x": 124, "y": 140, "z": -37},
    )
    covered_targets = _sp003_observation_targets(covered, progress)
    assert covered_targets[0]["source_id"] == "dirt:125:140:-37"
    assert covered_targets[0]["support_source_id"] == "stone:125:139:-37"
    assert covered_targets[0]["stone_surface_clearance"] is True
    rejected = guard_sp003_action(
        {
            "type": "dig",
            "parameters": {"block": "stone", "x": 125, "y": 139, "z": -37},
        },
        covered,
        progress,
    )
    assert not rejected["allowed"]
    assert "sp003_stone_surface_clearance_required_before_dig" in rejected["issues"]

    wrong_support_blocks = [
        block("stone", 125, 139, -37, 1.414214),
        block("dirt", 125, 138, -37, 2.236068),
    ]
    wrong_support = observation(
        {"wooden_pickaxe": 1},
        wrong_support_blocks,
        held="wooden_pickaxe",
        position={"x": 124.5, "y": 140.0, "z": -36.5},
    )
    wrong_support_scan = attach_complete_sp003_scan(
        wrong_support,
        wrong_support_blocks,
        origin={"x": 124, "y": 140, "z": -37},
    )
    assert _stone_pickup_accesses(wrong_support_scan) == []
    unsupported = guard_sp003_action(
        {
            "type": "dig",
            "parameters": {"block": "stone", "x": 125, "y": 139, "z": -37},
        },
        wrong_support,
        progress,
    )
    assert not unsupported["allowed"]
    assert "sp003_stone_target_must_be_reachable_and_observed" in unsupported[
        "issues"
    ]


def test_phase97_move_replay_aligns_block_cell_and_continuous_distance_metrics():
    session_path = (
        REPO
        / "workspace/evals/sp003_runs/sp003_baseline_20260719_121946_1d855e28/session.json"
    )
    events = json.loads(session_path.read_text(encoding="utf-8"))
    retained_guard = next(
        event
        for event in events
        if event.get("type") == "stone_pickaxe_sp003_action_guard"
        and (event.get("data") or {}).get("selected_source", {}).get("source_id")
        == "stone:122:138:-36"
    )
    retained_action = next(
        event
        for event in events
        if event.get("type") == "action"
        and (event.get("data") or {}).get("action", {}).get("type") == "move_to"
        and (event.get("data") or {}).get("action", {}).get("parameters", {}).get("x")
        == 122
    )
    guard_index = events.index(retained_guard)
    retained_observation = next(
        event["data"]
        for event in reversed(events[:guard_index])
        if event.get("type") == "observation"
    )

    replayed = guard_sp003_action(
        {"type": "move_to", "parameters": {"x": 122, "z": -36}},
        copy.deepcopy(retained_observation),
        copy.deepcopy(retained_guard["data"]["progress"]),
    )

    assert replayed["allowed"], replayed
    assert replayed["action"]["parameters"] == {
        "x": 122.5,
        "z": -35.5,
        "tolerance": 1.6,
        "preserve_inventory": True,
    }
    assert replayed["action_repair"]["policy_id"] == (
        "sp003-goalnearxz-cell-metric-alignment-v1"
    )
    assert replayed["action_repair"]["pathfinder_goal_range"] == 1
    assert replayed["action_repair"]["pathfinder_goal_cell_unchanged"] is True

    final_position = retained_action["data"]["result"]["position"]
    old_distance = math.hypot(
        final_position["x"] - 122,
        final_position["z"] - (-36),
    )
    aligned_distance = math.hypot(
        final_position["x"] - replayed["action"]["parameters"]["x"],
        final_position["z"] - replayed["action"]["parameters"]["z"],
    )
    assert old_distance > 1.6
    assert aligned_distance <= replayed["action"]["parameters"]["tolerance"]


def test_phase99_provider_internal_server_error_is_fail_closed_and_immutable():
    run = (
        REPO
        / "workspace/evals/sp003_runs/sp003_baseline_20260719_135031_9aa6c664"
    )
    episode = json.loads((run / "episode.json").read_text(encoding="utf-8"))
    events = json.loads((run / "session.json").read_text(encoding="utf-8"))
    consumption = json.loads(
        (run / "authorization_consumption.json").read_text(encoding="utf-8")
    )
    planner = next(event["data"] for event in events if event["type"] == "llm_planner_call")
    transport = planner["transport_evidence"]

    assert episode["goal_result"]["termination_reason"] == "empty_plan"
    assert episode["action_count"] == 0
    assert episode["action_failures"] == []
    assert episode["distinct_log_source_ids"] == []
    assert episode["distinct_stone_source_ids"] == []
    assert episode["task_graph"]["task_count"] == 0
    assert episode["task_graph"]["transitions"] == []
    assert episode["initial_observation"]["inventory"] == {}
    assert episode["stable_observation"]["inventory"] == {}
    assert planner["real_llm_call"] is False
    assert planner["response_byte_count"] == 0
    assert planner["provider_metadata"]["error_type"] == "InternalServerError"
    assert transport["policy_id"] == "single-attempt"
    assert transport["attempt_count"] == 1
    assert transport["retry_count"] == 0
    assert transport["attempts"] == [
        {
            "attempt_index": 0,
            "success": False,
            "timeout_s": 299.938,
            "sdk_max_retries": 0,
            "error_type": "InternalServerError",
            "error_chain": ["InternalServerError", "HTTPStatusError"],
        }
    ]
    assert consumption["authorization_commit"] == (
        "0283c1f95638ae99d06b2aac9014c805f0a4dfd9"
    )
    assert consumption["automatic_retry_allowed"] is False

    ledger = json.loads(
        (REPO / "workspace/evals/stone_pickaxe_failure_ledger.json").read_text(
            encoding="utf-8"
        )
    )
    failure = next(
        item
        for item in ledger["failures"]
        if item["id"] == "sp003-baseline-012-root-planner-internal-server-error"
    )
    assert failure["automatic_retry_attempted"] is False
    assert failure["counts_toward_baseline_success"] is False
    assert len(failure["evidence"]) == 13
    for record in failure["evidence"]:
        path = REPO / record["path"]
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]


def test_phase100_provider_health_probe_matches_fixed_controls_without_credentials():
    path = REPO / "workspace/evals/stone_pickaxe_sp003_provider_health_probe.json"
    probe = json.loads(path.read_text(encoding="utf-8"))
    protocol = json.loads(
        (REPO / "workspace/evals/stone_pickaxe_protocol.json").read_text(
            encoding="utf-8"
        )
    )
    planner = protocol["planner"]

    assert probe["passed"] is True
    assert probe["predecessor_commit"] == (
        "812d2e647a05bf44c1b59b262635c9c14f016662"
    )
    assert probe["request_count"] == 1
    assert probe["retry_count"] == 0
    assert probe["provider"] == planner["provider"]
    assert probe["base_url"] == planner["base_url"]
    assert probe["model"] == planner["model"]
    assert probe["temperature"] == planner["temperature"]
    assert probe["max_tokens"] == planner["max_tokens"]
    assert probe["extra_body"] == {"thinking": {"type": planner["thinking"]}}
    assert probe["response_sha256"] == hashlib.sha256(b'{"ok":true}').hexdigest()
    assert probe["response_byte_count"] == 11
    assert probe["finish_reason"] == "stop"
    assert probe["reasoning_content_byte_count"] == 0
    assert probe["credential_value_retained"] is False
    assert probe["minecraft_process_started"] is False
    assert probe["authorization_created"] is False
    assert probe["counts_toward_baseline_success"] is False
    assert probe["counts_toward_capability"] is False
    assert probe["counts_toward_m4"] is False
    assert "api_key" not in path.read_text(encoding="utf-8").lower()


def test_phase101_retained_baseline_replays_stage_drift_and_context_bloat():
    run_dir = (
        REPO
        / "workspace/evals/sp003_runs/sp003_baseline_20260719_143554_ded97c9b"
    )
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    episode = json.loads((run_dir / "episode.json").read_text(encoding="utf-8"))
    events = json.loads((run_dir / "session.json").read_text(encoding="utf-8"))

    assert manifest["passed"] is False
    assert manifest["evidence_eligible"] is False
    assert manifest["authorization_id"] == (
        "579e77572b421ffb2ebf2f6ca90bc4340cc9700984d169c678c57e269b74ce3b"
    )
    assert manifest["automatic_retry_allowed"] is False
    assert manifest["bm012_terminal_started"] is False
    assert episode["goal_result"]["termination_reason"] == "empty_plan"
    assert episode["goal_result"]["deadline_eligible"] is True
    assert episode["action_count"] == 19
    assert [failure["error"] for failure in episode["action_failures"]] == [
        "SP-003 action guard rejected: sp003_exact_one_table_craft_required",
        "SP-003 action guard rejected: sp003_exact_one_table_craft_required",
        "SP-003 action guard rejected: sp003_stone_dig_requires_held_wooden_pickaxe",
    ]
    assert len(episode["distinct_log_source_ids"]) == 3
    assert len(episode["distinct_surface_clearance_source_ids"]) == 3
    assert len(episode["distinct_stone_source_ids"]) == 1
    assert episode["stable_observation"]["inventory"] == {
        "stick": 2,
        "oak_planks": 3,
        "wooden_pickaxe": 1,
        "dirt": 3,
        "cobblestone": 1,
    }

    planner_calls = {
        event["data"]["call_index"]: event["data"]
        for event in events
        if event.get("type") == "llm_planner_call"
    }
    assert planner_calls[6]["schema_valid"] is True
    assert planner_calls[7]["schema_valid"] is True
    assert planner_calls[19]["provider_metadata"]["prompt_tokens"] == 7512
    assert planner_calls[19]["response_byte_count"] == 928
    assert planner_calls[19]["schema_validation"]["issues"] == [
        "reasoning_too_long"
    ]
    assert all(
        call["transport_evidence"]["attempt_count"] == 1
        and call["transport_evidence"]["retry_count"] == 0
        for call in planner_calls.values()
    )

    ledger = json.loads(
        (REPO / "workspace/evals/stone_pickaxe_failure_ledger.json").read_text(
            encoding="utf-8"
        )
    )
    failure = next(
        item
        for item in ledger["failures"]
        if item["id"] == "sp003-baseline-013-stage-drift-context-bloat"
    )
    assert failure["automatic_retry_attempted"] is False
    assert failure["counts_toward_baseline_success"] is False
    assert len(failure["evidence"]) == 13
    for record in failure["evidence"]:
        path = REPO / record["path"]
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]


def test_phase103_retained_baseline_replays_move_to_y_contract_disconnect():
    run_dir = (
        REPO
        / "workspace/evals/sp003_runs/sp003_baseline_20260719_154642_73c81d37"
    )
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    episode = json.loads((run_dir / "episode.json").read_text(encoding="utf-8"))
    events = json.loads((run_dir / "session.json").read_text(encoding="utf-8"))

    assert manifest["passed"] is False
    assert manifest["evidence_eligible"] is False
    assert manifest["authorization_id"] == (
        "523e81eb1e3025b17e2090990c148b4a67858bf3cc7f8f9bf60433141a1777cc"
    )
    assert manifest["automatic_retry_allowed"] is False
    assert manifest["bm012_terminal_started"] is False
    assert episode["goal_result"]["termination_reason"] == "empty_plan"
    assert episode["goal_result"]["deadline_eligible"] is True
    assert episode["action_count"] == 12
    assert episode["action_failures"] == []
    assert len(episode["distinct_log_source_ids"]) == 3
    assert episode["distinct_surface_clearance_source_ids"] == []
    assert episode["distinct_stone_source_ids"] == []
    assert episode["stable_observation"]["inventory"] == {
        "stick": 2,
        "oak_planks": 3,
        "wooden_pickaxe": 1,
    }

    action_types = [
        event["data"]["action"]["type"]
        for event in events
        if event.get("type") == "action"
    ]
    assert {kind: action_types.count(kind) for kind in set(action_types)} == {
        "move_to": 3,
        "dig": 3,
        "craft": 4,
        "place": 1,
        "equip": 1,
    }

    planner_calls = {
        event["data"]["call_index"]: event["data"]
        for event in events
        if event.get("type") == "llm_planner_call"
    }
    assert sorted(planner_calls) == list(range(13))
    assert all(planner_calls[index]["schema_valid"] is True for index in range(12))
    terminal = planner_calls[12]
    assert terminal["call_id"] == "llm-a2ab5103f3a14ec0"
    assert terminal["schema_valid"] is False
    assert terminal["schema_validation"]["issues"] == [
        "action_parameter_y_invalid"
    ]
    assert terminal["provider_metadata"]["prompt_tokens"] == 2555
    assert terminal["response_byte_count"] == 523
    assert terminal["response_sha256"] == (
        "5e986734658478dffa609910ba3a2f07978896c72a399d223e907ed88f2d062b"
    )
    assert all(
        call["transport_evidence"]["attempt_count"] == 1
        and call["transport_evidence"]["retry_count"] == 0
        and call["transport_evidence"]["attempts"][0]["success"] is True
        for call in planner_calls.values()
    )

    compact_by_call = {}
    for call_index in (6, 12):
        event_index = next(
            index
            for index, event in enumerate(events)
            if event.get("type") == "llm_planner_call"
            and event.get("data", {}).get("call_index") == call_index
        )
        full = next(
            event["data"]
            for event in reversed(events[:event_index])
            if event.get("type") == "observation"
        )
        compact = Planner._compact_stone_pickaxe_state(full)
        compact_by_call[call_index] = compact
        compact_json = json.dumps(compact, sort_keys=True, separators=(",", ":"))
        assert len(compact_json) <= 2500
        assert "clearance_proof" not in compact_json

    assert compact_by_call[6]["sp003_stage"] == "craft_crafting_table"
    terminal_compact = compact_by_call[12]
    assert terminal_compact["sp003_stage"] == "acquire_cobblestone"
    assert terminal_compact["sp003_targets"][0]["source_id"] == "stone:124:139:-37"
    assert terminal_compact["sp003_targets"][0]["stone_clearance_probe"] is True
    assert terminal_compact["sp003_targets"][0]["navigation_only"] is True
    target_position = terminal_compact["sp003_targets"][0]["position"]
    repaired_envelope = {
        "schema_version": "stone-pickaxe-plan-v1",
        "plan_kind": "continuation",
        "goal": SP003_GOAL,
        "status": "planning",
        "reasoning": "Approach the machine-grounded clearance probe.",
        "subtasks": [],
        "actions": [
            {
                "type": "move_to",
                "parameters": {
                    "x": target_position["x"],
                    "z": target_position["z"],
                },
            }
        ],
    }
    repaired_report = Planner._validate_stone_pickaxe_plan_envelope(
        repaired_envelope,
        SP003_GOAL,
        "continuation",
        "sp003",
    )
    assert repaired_report["passed"], repaired_report

    ledger = json.loads(
        (REPO / "workspace/evals/stone_pickaxe_failure_ledger.json").read_text(
            encoding="utf-8"
        )
    )
    failure = next(
        item
        for item in ledger["failures"]
        if item["id"] == "sp003-baseline-014-move-to-schema-y-contract-disconnect"
    )
    assert failure["automatic_retry_attempted"] is False
    assert failure["counts_toward_baseline_success"] is False
    assert len(failure["evidence"]) == 13
    for record in failure["evidence"]:
        path = REPO / record["path"]
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]


def test_phase105_retained_baseline_replays_covered_stone_pickup_failure():
    run_dir = (
        REPO
        / "workspace/evals/sp003_runs/sp003_baseline_20260719_164341_b6f52e23"
    )
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    episode = json.loads((run_dir / "episode.json").read_text(encoding="utf-8"))
    events = json.loads((run_dir / "session.json").read_text(encoding="utf-8"))

    assert manifest["passed"] is False
    assert manifest["evidence_eligible"] is False
    assert manifest["authorization_id"] == (
        "01da5db4fdadaee2ead01915e59a18de5bfd45771ccd9291c536acacf859dbba"
    )
    assert manifest["automatic_retry_allowed"] is False
    assert manifest["bm012_terminal_started"] is False
    assert episode["goal_result"]["termination_reason"] == "max_duration"
    assert episode["goal_result"]["deadline_eligible"] is False
    assert episode["goal_result"]["cycles"] == 27
    assert episode["action_count"] == 27
    assert len(episode["raw_action_failures"]) == 9
    assert episode["reconciled_action_failure_indexes"] == []
    assert len(episode["unreconciled_action_failures"]) == 9
    assert episode["post_deadline_action_indexes"] == []
    assert len(episode["distinct_log_source_ids"]) == 3
    assert len(episode["distinct_surface_clearance_source_ids"]) == 3
    assert episode["distinct_stone_source_ids"] == []
    assert episode["stable_observation"]["inventory"] == {
        "stick": 2,
        "oak_planks": 3,
        "wooden_pickaxe": 1,
        "dirt": 3,
    }

    planner_calls = [
        event["data"]
        for event in events
        if event.get("type") == "llm_planner_call"
    ]
    assert [call["call_index"] for call in planner_calls] == list(range(27))
    assert all(call["schema_valid"] is True for call in planner_calls)
    assert all(
        call["transport_evidence"]["attempt_count"] == 1
        and call["transport_evidence"]["retry_count"] == 0
        and call["transport_evidence"]["attempts"][0]["success"] is True
        for call in planner_calls
    )
    assert max(
        call["provider_metadata"]["prompt_tokens"] for call in planner_calls
    ) == 2955
    assert max(call["response_byte_count"] for call in planner_calls) == 2095

    stone_actions = [
        (index, event["data"])
        for index, event in enumerate(events)
        if event.get("type") == "action"
        and event.get("data", {}).get("action", {}).get("parameters", {}).get(
            "block"
        )
        == "stone"
    ]
    removed = [item for item in stone_actions if item[1]["result"].get("block_removed")]
    assert [index for index, _data in removed] == [356, 376]
    expected = [
        (
            "stone:124:139:-38",
            964,
            1.6831034082055907,
            {"x": 124.875, "y": 139, "z": -37.875},
        ),
        (
            "stone:125:139:-37",
            1014,
            1.1649104141027862,
            {"x": 125.125, "y": 139, "z": -36.875},
        ),
    ]
    for (_index, action_event), (
        source,
        entity_id,
        final_distance,
        drop_position,
    ) in zip(removed, expected):
        params = action_event["action"]["parameters"]
        result = action_event["result"]
        pickup = result["pickup_collection"]
        assert params["source_id"] == source
        assert result["success"] is False
        assert result["target_block_before"]["name"] == "stone"
        assert result["target_block_after"]["name"] == "air"
        assert result["pickup_inventory_delta"] == {}
        assert result["error"] == "expected block drop was not acquired"
        assert pickup["entity_id"] == entity_id
        assert pickup["position"] == drop_position
        assert pickup["direct_navigation"]["pathfinder_resolved"] is True
        assert pickup["direct_navigation"]["completion_grounded"] is False
        assert pickup["final_distance"] == final_distance
        assert pickup["fallback_candidate"] is None
        assert pickup["fallback_attempt_count"] == 0
        assert pickup["error"] == (
            "pickup navigation completed outside acquisition range and no "
            "standable fallback was available"
        )
        head = {
            "x": params["x"],
            "y": params["y"] + 1,
            "z": params["z"],
        }
        assert any(
            block_item.get("name") == "dirt"
            and block_item.get("position") == head
            for block_item in action_event["pre_observation"]["nearby_blocks"]
        )

    first_guard_index = next(
        index
        for index, event in enumerate(events)
        if event.get("type") == "stone_pickaxe_sp003_action_guard"
        and event.get("data", {}).get("selected_source", {}).get("source_id")
        == "stone:124:139:-38"
    )
    first_observation = next(
        event["data"]
        for event in reversed(events[:first_guard_index])
        if event.get("type") == "observation"
    )
    assert first_observation["sp003_complete_local_scan"] == {}
    first_response = first_observation["nearby_blocks"][:50]
    saturated_replay = _bounded_complete_local_scan(
        first_observation,
        first_response,
        first_observation,
    )
    assert saturated_replay["scan_complete"] is False
    assert saturated_replay["targeted_air_visibility_complete"] is True
    assert saturated_replay["priority_unique_name_prefix_count"] == 5
    assert saturated_replay["visibility_distance_strict_upper_bound"] == (
        3.3166247903554
    )
    first_clearance = next(
        item
        for item in _stone_surface_clearances(saturated_replay)
        if item["support_source_id"] == "stone:124:139:-38"
    )
    assert first_clearance["source_id"] == "dirt:124:140:-38"
    assert first_clearance["remaining_clearance_count"] == 1

    second_guard_index = next(
        index
        for index, event in enumerate(events)
        if event.get("type") == "stone_pickaxe_sp003_action_guard"
        and event.get("data", {}).get("selected_source", {}).get("source_id")
        == "stone:125:139:-37"
    )
    second_observation = next(
        event["data"]
        for event in reversed(events[:second_guard_index])
        if event.get("type") == "observation"
    )
    complete_scan = second_observation["sp003_complete_local_scan"]
    assert complete_scan["scan_complete"] is True
    by_cell = {
        tuple(block_item["position"][axis] for axis in ("x", "y", "z")):
        block_item["name"]
        for block_item in complete_scan["blocks"]
    }
    assert by_cell[(125, 138, -37)] == "stone"
    assert by_cell[(125, 139, -37)] == "stone"
    assert by_cell[(125, 140, -37)] == "dirt"
    assert by_cell[(125, 141, -37)] == "dirt"

    replay_blocks = [
        item
        for item in complete_scan["blocks"]
        if tuple(item["position"][axis] for axis in ("x", "y", "z"))
        in {
            (125, 138, -37),
            (125, 139, -37),
            (125, 140, -37),
            (125, 141, -37),
        }
    ]
    replay = copy.deepcopy(second_observation)
    replay["nearby_blocks"] = copy.deepcopy(replay_blocks)
    replay_progress = copy.deepcopy(second_observation["sp003_progress"])
    attach_complete_sp003_scan(
        replay,
        replay_blocks,
        origin=complete_scan["origin_cell"],
    )
    clearance = next(
        target
        for target in _sp003_observation_targets(replay, replay_progress)
        if target.get("support_source_id") == "stone:125:139:-37"
    )
    assert clearance["source_id"] == "dirt:125:140:-37"
    assert clearance["remaining_clearance_count"] == 1
    covered_guard = guard_sp003_action(
        {
            "type": "dig",
            "parameters": {"block": "stone", "x": 125, "y": 139, "z": -37},
        },
        replay,
        replay_progress,
    )
    assert not covered_guard["allowed"]
    assert "sp003_stone_surface_clearance_required_before_dig" in covered_guard[
        "issues"
    ]

    opened = copy.deepcopy(replay)
    opened_blocks = [
        item
        for item in replay_blocks
        if item["position"] != {"x": 125, "y": 140, "z": -37}
    ]
    opened["nearby_blocks"] = copy.deepcopy(opened_blocks)
    attach_complete_sp003_scan(
        opened,
        opened_blocks,
        origin=complete_scan["origin_cell"],
    )
    opened_target = next(
        target
        for target in _sp003_observation_targets(opened, replay_progress)
        if target["source_id"] == "stone:125:139:-37"
    )
    assert opened_target["stone_pickup_access"] is True
    opened_guard = guard_sp003_action(
        {
            "type": "dig",
            "parameters": {
                "block": "stone",
                "x": 125,
                "y": 139,
                "z": -37,
                "stone_pickup_access": True,
                "pickup_access_proof": {"forged": True},
                "pickup_access_proof_fingerprint": "0" * 64,
            },
        },
        opened,
        replay_progress,
    )
    assert opened_guard["allowed"], opened_guard
    normalized_proof = opened_guard["action"]["parameters"][
        "pickup_access_proof"
    ]
    assert normalized_proof.get("forged") is None
    assert normalized_proof["target_source_id"] == "stone:125:139:-37"
    assert opened_guard["action"]["parameters"][
        "pickup_access_proof_fingerprint"
    ] == canonical_sha256(normalized_proof)

    ledger = json.loads(
        (REPO / "workspace/evals/stone_pickaxe_failure_ledger.json").read_text(
            encoding="utf-8"
        )
    )
    failure = next(
        item
        for item in ledger["failures"]
        if item["id"]
        == "sp003-baseline-015-covered-stone-pickup-access-disconnect"
    )
    assert failure["automatic_retry_attempted"] is False
    assert failure["counts_toward_baseline_success"] is False
    assert len(failure["evidence"]) == 13
    for record in failure["evidence"]:
        path = REPO / record["path"]
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]


def test_phase104_move_to_schema_repair_audit_binds_current_contract():
    audit_path = REPO / "workspace/evals/stone_pickaxe_sp003_move_to_schema_repair.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8"))

    assert audit["type"] == "stone_pickaxe_sp003_move_to_schema_repair"
    assert audit["phase"] == 104
    assert audit["base_commit"] == "06a8327a8d7a4ff358e0a2ec9b773c80a7da323f"
    assert audit["move_schema_policy_id"] == "sp003-horizontal-move-envelope-v1"
    assert audit["repair_contract"] == {
        "sp003_move_to_required_axes": ["x", "z"],
        "sp003_move_to_optional_axes": ["y"],
        "optional_y_must_be_finite": True,
        "sp003_look_at_required_axes": ["x", "y", "z"],
        "non_sp003_move_to_required_axes": ["x", "y", "z"],
        "action_rewrite_allowed": False,
        "action_guard_changed": False,
        "base_protocol_changed": False,
        "shared_bridge_changed": False,
        "automatic_retry_allowed": False,
    }
    assert audit["retained_replay"]["original_schema_issues"] == [
        "action_parameter_y_invalid"
    ]
    assert audit["retained_replay"]["reconstructed_x_z_envelope_passed"] is True
    assert audit["live_episode_run"] is False
    assert audit["live_authorization"] is False

    implementation_commit = "61a7a28fa30e6a40cd638ea9feff4a010f62babb"
    for record in audit["implementation"]:
        historical_bytes = subprocess.check_output(
            ["git", "show", f"{implementation_commit}:{record['path']}"],
            cwd=REPO,
        )
        assert hashlib.sha256(historical_bytes).hexdigest() == record["sha256"]


def test_phase106_pre_dig_pickup_access_audit_binds_current_contract():
    audit_path = (
        REPO
        / "workspace/evals/stone_pickaxe_sp003_pre_dig_pickup_access_repair.json"
    )
    audit = json.loads(audit_path.read_text(encoding="utf-8"))

    assert audit["type"] == "stone_pickaxe_sp003_pre_dig_pickup_access_repair"
    assert audit["phase"] == 106
    assert audit["base_commit"] == "b8d45909878438b5a40ab3da5326b684cd73cf5e"
    assert audit["pre_dig_pickup_access_policy_id"] == (
        SP003_PRE_DIG_PICKUP_ACCESS_POLICY_ID
    )
    assert audit["retained_failure"]["manifest_sha256"] == (
        "8a04a05943a7d41eacf382776ab4391fe8eeb75f5d5bd36501b77dccdfc988aa"
    )
    assert audit["retained_failure"]["session_sha256"] == (
        "ec019d6589d3010b7e08ffd9be579961214da4c94f514b51e1e0b470f7661727"
    )
    assert audit["repair_contract"]["direct_stone_requires_pickup_access"] is True
    assert audit["repair_contract"]["strict_priority_visibility_allowed"] is True
    assert audit["repair_contract"]["maximum_clearances_per_shaft"] == 3
    assert audit["repair_contract"]["maximum_clearances_per_episode"] == 6
    assert audit["repair_contract"]["caller_proof_is_authoritative"] is False
    assert audit["repair_contract"]["shared_bridge_changed"] is False
    assert audit["retained_replay"]["first_scan_unique_name_prefix_count"] == 5
    assert audit["retained_replay"]["first_scan_clearance_source_id"] == (
        "dirt:124:140:-38"
    )
    assert audit["live_episode_run"] is False
    assert audit["live_authorization"] is False
    assert audit["counts_toward_capability"] is False

    implementation_commit = "c49c8045a653dd8cf70c2f4f599ebda7c8e53c73"
    for record in audit["implementation"]:
        historical_bytes = subprocess.check_output(
            ["git", "show", f"{implementation_commit}:{record['path']}"],
            cwd=REPO,
        )
        assert hashlib.sha256(historical_bytes).hexdigest() == record["sha256"]


def test_phase107_retained_baseline_replays_goalblock_false_resolution():
    run_dir = (
        REPO
        / "workspace/evals/sp003_runs/sp003_baseline_20260719_184317_c5963fb7"
    )
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    consumption = json.loads(
        (run_dir / "authorization_consumption.json").read_text(encoding="utf-8")
    )
    episode = json.loads((run_dir / "episode.json").read_text(encoding="utf-8"))
    events = json.loads((run_dir / "session.json").read_text(encoding="utf-8"))

    assert manifest["passed"] is False
    assert manifest["evidence_eligible"] is False
    assert manifest["authorization_id"] == (
        "1857c3080329915309cb6d490c2a5636cf42269b0193473785aa4406adea9e85"
    )
    assert manifest["automatic_retry_allowed"] is False
    assert manifest["bm012_terminal_started"] is False
    assert consumption["authorization_commit"] == (
        "44b971a7a3836bdd02ff67cfaa5c4b22e2be0a24"
    )
    assert consumption["consumed_by"] == "fresh_sp003_process_start"
    assert consumption["single_episode"] is True
    assert consumption["automatic_retry_allowed"] is False

    goal = episode["goal_result"]
    assert goal["termination_reason"] == "max_actions"
    assert goal["deadline_eligible"] is True
    assert goal["cycles"] == 33
    assert goal["action_count"] == 32
    assert episode["action_count"] == 32
    assert len(episode["raw_action_failures"]) == 7
    assert episode["reconciled_action_failure_indexes"] == []
    assert len(episode["unreconciled_action_failures"]) == 7
    assert episode["post_deadline_action_indexes"] == []
    assert len(episode["distinct_log_source_ids"]) == 3
    assert len(episode["distinct_surface_clearance_source_ids"]) == 4
    assert episode["distinct_stone_source_ids"] == []
    assert episode["stable_observation"]["inventory"] == {
        "stick": 2,
        "oak_planks": 3,
        "wooden_pickaxe": 1,
        "dirt": 4,
    }

    planner_calls = [
        event["data"]
        for event in events
        if event.get("type") == "llm_planner_call"
    ]
    assert [call["call_index"] for call in planner_calls] == list(range(33))
    assert all(call["schema_valid"] is True for call in planner_calls)
    assert all(
        call["transport_evidence"]["attempt_count"] == 1
        and call["transport_evidence"]["retry_count"] == 0
        and call["transport_evidence"]["attempts"][0]["success"] is True
        for call in planner_calls
    )
    assert max(
        call["provider_metadata"]["prompt_tokens"] for call in planner_calls
    ) == 2974
    assert max(call["response_byte_count"] for call in planner_calls) == 1834

    stone_actions = [
        (index, event["data"])
        for index, event in enumerate(events)
        if event.get("type") == "action"
        and event.get("data", {}).get("action", {}).get("parameters", {}).get(
            "block"
        )
        == "stone"
    ]
    assert len(stone_actions) == 1
    event_index, stone = stone_actions[0]
    assert event_index == 376
    parameters = stone["action"]["parameters"]
    proof = parameters["pickup_access_proof"]
    result = stone["result"]
    pickup = result["pickup_collection"]
    assert parameters["source_id"] == "stone:124:139:-38"
    assert parameters["pickup_access_proof_fingerprint"] == (
        "cbd7c37ddecac2a265a68fa05732461d9a9bf9117578f6e7a838e624576ec9e1"
    )
    assert proof["policy_id"] == SP003_PRE_DIG_PICKUP_ACCESS_POLICY_ID
    assert proof["scan_complete"] is True
    assert proof["response_count"] == 49
    assert proof["scan_origin_cell"] == {"x": 124, "y": 140, "z": -37}
    assert proof["target_source_id"] == "stone:124:139:-38"
    assert proof["support_source_id"] == "stone:124:138:-38"
    assert proof["post_dig_stand_position"] == {"x": 124, "y": 139, "z": -38}
    assert proof["head_position"] == {"x": 124, "y": 140, "z": -38}
    assert proof["head_cell_state"] == "air"
    assert proof["pickup_access_proven"] is True

    assert result["success"] is False
    assert result["block_removed"] is True
    assert result["target_block_before"]["name"] == "stone"
    assert result["target_block_after"]["name"] == "air"
    assert result["dig_tool_equip"]["selected_tool"] == "wooden_pickaxe"
    assert result["dig_tool_equip"]["passed"] is True
    assert result["pickup_inventory_delta"] == {}
    assert result["error"] == "expected block drop was not acquired"
    assert pickup["item_name"] == "cobblestone"
    assert pickup["entity_id"] == 949
    assert pickup["position"] == {"x": 124.875, "y": 139, "z": -37.875}
    assert pickup["direct_navigation"]["pathfinder_resolved"] is True
    assert pickup["direct_navigation"]["completion_grounded"] is False
    assert pickup["fallback_attempt_count"] == 1
    assert pickup["fallback_same_cell_nudge_attempt_count"] == 0
    assert pickup["fallback_candidate"]["position"] == {
        "x": 124,
        "y": 139,
        "z": -38,
    }
    assert pickup["fallback_candidate"]["expected_pickup_distance"] == (
        0.5303300858899106
    )
    assert pickup["fallback_candidate"]["support"]["name"] == "stone"
    assert pickup["fallback_candidate"]["feet"]["name"] == "air"
    assert pickup["fallback_candidate"]["head"]["name"] == "air"
    assert pickup["fallback_navigation"]["goal_type"] == "GoalBlock"
    assert pickup["fallback_navigation"]["pathfinder_resolved"] is True
    assert pickup["fallback_navigation"]["position"] == pickup[
        "direct_navigation"
    ]["position"]
    assert pickup["fallback_navigation"]["completion_grounded"] is False
    assert pickup["final_distance"] == 1.777479930337906
    assert pickup["error"] == "pickup fallback completed outside acquisition range"

    actions_after_failure = [
        event["data"]
        for event in events[event_index + 1 :]
        if event.get("type") == "action"
    ]
    assert len(actions_after_failure) == 14
    assert all(item["action"]["type"] == "move_to" for item in actions_after_failure)
    guard_errors = [
        item["result"].get("error")
        for item in actions_after_failure
        if not item["result"].get("success")
    ]
    assert guard_errors == [
        "SP-003 action guard rejected: "
        "acquire_cobblestone_navigation_target_must_be_nearest_observed"
    ] * 6

    ledger = json.loads(
        (REPO / "workspace/evals/stone_pickaxe_failure_ledger.json").read_text(
            encoding="utf-8"
        )
    )
    failure = next(
        item
        for item in ledger["failures"]
        if item["id"] == "sp003-baseline-016-goalblock-empty-foot-cell-false-resolution"
    )
    assert failure["automatic_retry_attempted"] is False
    assert failure["counts_toward_baseline_success"] is False
    assert len(failure["evidence"]) == 13
    for record in failure["evidence"]:
        path = REPO / record["path"]
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]


def test_phase108_goalblock_completion_grounding_audit_binds_current_contract():
    audit_path = (
        REPO
        / "workspace/evals/stone_pickaxe_sp003_goalblock_completion_grounding_repair.json"
    )
    audit = json.loads(audit_path.read_text(encoding="utf-8"))

    assert audit["type"] == (
        "stone_pickaxe_sp003_goalblock_completion_grounding_repair"
    )
    assert audit["phase"] == 108
    assert audit["base_commit"] == "7be57b4d5e990c82e08f0a66aa04b7e9f8b5d27a"
    assert audit["policy_id"] == SP003_GOALBLOCK_COMPLETION_GROUNDING_POLICY_ID
    assert audit["retained_failure"]["manifest_sha256"] == (
        "f4556504447040d19e2c49c29b44ee3c4b7e062350f296a88b08f8f5a318133e"
    )
    assert audit["retained_failure"]["session_sha256"] == (
        "31d33f4ab1e772cac5d9b3a80a9bfb825c760ea7e477df912a405c80cc51e37b"
    )
    assert audit["retained_failure"]["fallback_position"] == audit[
        "retained_failure"
    ]["direct_position"]
    assert audit["retained_failure"]["fallback_goal"] == {
        "type": "GoalBlock",
        "x": 124,
        "y": 139,
        "z": -38,
    }
    assert audit["retained_failure"]["fallback_expected_pickup_distance"] == (
        0.5303300858899106
    )
    assert audit["dependency_root_cause"]["empty_path_checked_before_no_path_status"]
    assert audit["dependency_root_cause"]["vendored_dependency_modified"] is False
    dependency_path = REPO / audit["dependency_root_cause"]["path"]
    assert hashlib.sha256(dependency_path.read_bytes()).hexdigest() == audit[
        "dependency_root_cause"
    ]["sha256"]

    contract = audit["repair_contract"]
    assert contract["scope"] == "sp003_process_local_preload_only"
    assert contract["post_resolve_goal_is_end_checked"] is True
    assert contract["target_exactly_one_level_lower"] is True
    assert contract["target_horizontally_adjacent"] is True
    assert contract["target_support_solid_required"] is True
    assert contract["target_feet_passable_required"] is True
    assert contract["target_head_passable_required"] is True
    assert contract["movement_pulse_ms"] == SP003_GOALBLOCK_NUDGE_PULSE_MS
    assert contract["movement_pulses_max"] == SP003_GOALBLOCK_NUDGE_MAX_PULSES
    assert contract["movement_total_ms_max"] == 500
    assert contract["world_mutation_allowed"] is False
    assert contract["exhaustion_fails_closed"] is True
    assert contract["shared_bridge_changed"] is False
    assert contract["base_protocol_changed"] is False
    assert audit["retained_replay"]["phase_107_geometry_eligible"] is True
    assert audit["retained_replay"]["simulated_goal_is_end"] is True
    assert audit["retained_replay"]["integrated_dig_fallback_pickup_passed"]
    assert audit["retained_replay"]["integrated_pickup_inventory_delta"] == {
        "cobblestone": 1
    }
    assert audit["retained_replay"]["four_pulse_exhaustion_rejected"] is True
    assert audit["retained_replay"]["real_mineflayer_plugin_lifecycle_wrapped"]
    assert audit["live_episode_run"] is False
    assert audit["live_authorization"] is False
    assert audit["counts_toward_capability"] is False

    implementation_commit = "81dbf7141d1f64f54f787a80639700ddcdb2d08c"
    for record in audit["implementation"]:
        historical_bytes = subprocess.check_output(
            ["git", "show", f"{implementation_commit}:{record['path']}"],
            cwd=REPO,
        )
        assert hashlib.sha256(historical_bytes).hexdigest() == record["sha256"]


def test_phase110_exact_goalnear_completion_grounding_audit_binds_current_contract():
    audit_path = (
        REPO
        / "workspace/evals/stone_pickaxe_sp003_exact_goalnear_completion_grounding_repair.json"
    )
    audit = json.loads(audit_path.read_text(encoding="utf-8"))

    assert audit["type"] == (
        "stone_pickaxe_sp003_exact_goalnear_completion_grounding_repair"
    )
    assert audit["phase"] == 110
    assert audit["base_commit"] == "bc20b5a0dcb8bc3e32f08e73f4dc5411f97e4cf3"
    assert audit["policy_id"] == (
        SP003_EXACT_GOALNEAR_COMPLETION_GROUNDING_POLICY_ID
    )
    assert audit["retained_failure"]["manifest_sha256"] == (
        "20ac04c16decf3e704c22a8482b4b5b92273fd4bbc1e780511ac9c96a29d0afd"
    )
    assert audit["retained_failure"]["session_sha256"] == (
        "09d3dd6bc605ac9a740349ca674285bf1583ec0be27cc753ee213c631c9f7a57"
    )
    assert audit["retained_failure"]["unchanged_success_count"] == 12
    assert audit["retained_failure"]["player_cell"] == {
        "x": 124,
        "y": 141,
        "z": -37,
    }
    assert audit["retained_failure"]["target_cell"] == {
        "x": 124,
        "y": 140,
        "z": -38,
    }
    assert audit["retained_failure"]["continuous_distance"] == pytest.approx(
        1.4205534244189506
    )
    assert audit["dependency_root_cause"][
        "empty_path_checked_before_no_path_status"
    ]
    assert audit["dependency_root_cause"]["vendored_dependency_modified"] is False
    dependency_path = REPO / audit["dependency_root_cause"]["path"]
    assert hashlib.sha256(dependency_path.read_bytes()).hexdigest() == audit[
        "dependency_root_cause"
    ]["sha256"]

    contract = audit["repair_contract"]
    assert contract["scope"] == "sp003_process_local_preload_only"
    assert contract["marked_exact_unit_goalnear_only"] is True
    assert contract["requested_range"] == 1
    assert contract["effective_range"] == 0
    assert contract["post_resolve_goal_is_end_checked"] is True
    assert contract["target_exactly_one_level_lower"] is True
    assert contract["target_horizontally_adjacent"] is True
    assert contract["target_support_solid_required"] is True
    assert contract["target_feet_passable_required"] is True
    assert contract["target_head_passable_required"] is True
    assert contract["movement_pulse_ms"] == SP003_GOALBLOCK_NUDGE_PULSE_MS
    assert contract["movement_pulses_max"] == SP003_GOALBLOCK_NUDGE_MAX_PULSES
    assert contract["world_mutation_allowed"] is False
    assert contract["unmarked_goal_near_unchanged"] is True
    assert contract["non_unit_goal_near_unchanged"] is True
    assert contract["original_errors_propagated"] is True
    assert contract["shared_bridge_changed"] is False
    assert contract["base_protocol_changed"] is False

    replay = audit["retained_replay"]
    assert replay["phase_109_geometry_eligible"] is True
    assert replay["simulated_goal_is_end_after_pulses"] is True
    assert replay["move_to_handler_exact_cell_grounded"] is True
    assert replay["integrated_direct_pickup_inventory_delta"] == {
        "cobblestone": 1
    }
    assert replay["solid_head_rejected"] is True
    assert replay["four_pulse_exhaustion_rejected"] is True
    assert replay["unsupported_goalnear_variants_preserved"] is True
    assert audit["live_episode_run"] is False
    assert audit["live_authorization"] is False
    assert audit["counts_toward_capability"] is False

    implementation_commit = "cfa05fd60bb326b1d1b86b5d73864371d2ae057e"
    for record in audit["implementation"]:
        historical_bytes = subprocess.check_output(
            ["git", "show", f"{implementation_commit}:{record['path']}"],
            cwd=REPO,
        )
        assert hashlib.sha256(historical_bytes).hexdigest() == record["sha256"]


def test_phase109_retained_baseline_replays_exact_goalnear_false_resolution():
    run_dir = (
        REPO
        / "workspace/evals/sp003_runs/sp003_baseline_20260719_200026_f434442e"
    )
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    consumption = json.loads(
        (run_dir / "authorization_consumption.json").read_text(encoding="utf-8")
    )
    episode = json.loads((run_dir / "episode.json").read_text(encoding="utf-8"))
    events = json.loads((run_dir / "session.json").read_text(encoding="utf-8"))

    assert manifest["passed"] is False
    assert manifest["evidence_eligible"] is False
    assert manifest["authorization_id"] == (
        "997cedcd034128bc5f5d06fbb70c41b9bd99e71aca1486c90a3c3d84c6e429ca"
    )
    assert manifest["automatic_retry_allowed"] is False
    assert manifest["bm012_terminal_started"] is False
    assert consumption["authorization_commit"] == (
        "4b5bfc253a293beb8ff55235c9ce213957a09ac3"
    )
    assert consumption["consumed_by"] == "fresh_sp003_process_start"
    assert consumption["single_episode"] is True
    assert consumption["automatic_retry_allowed"] is False

    goal = episode["goal_result"]
    assert goal["termination_reason"] == "max_actions"
    assert goal["deadline_eligible"] is True
    assert goal["cycles"] == 33
    assert goal["action_count"] == 32
    assert goal["elapsed_s"] == pytest.approx(218.985)
    assert episode["action_count"] == 32
    assert len(episode["raw_action_failures"]) == 4
    assert episode["reconciled_action_failure_indexes"] == []
    assert len(episode["unreconciled_action_failures"]) == 4
    assert episode["post_deadline_action_indexes"] == []
    assert len(episode["distinct_log_source_ids"]) == 3
    assert len(episode["distinct_surface_clearance_source_ids"]) == 4
    assert episode["distinct_stone_source_ids"] == []
    assert episode["stable_observation"]["inventory"] == {
        "stick": 2,
        "oak_planks": 3,
        "wooden_pickaxe": 1,
        "dirt": 4,
    }

    planner_calls = [
        event["data"]
        for event in events
        if event.get("type") == "llm_planner_call"
    ]
    assert [call["call_index"] for call in planner_calls] == list(range(33))
    assert all(call["schema_valid"] is True for call in planner_calls)
    assert all(
        call["transport_evidence"]["attempt_count"] == 1
        and call["transport_evidence"]["retry_count"] == 0
        and call["transport_evidence"]["attempts"][0]["success"] is True
        for call in planner_calls
    )
    assert max(
        call["provider_metadata"]["prompt_tokens"] for call in planner_calls
    ) == 2974
    assert max(call["response_byte_count"] for call in planner_calls) == 2091

    actions = [event["data"] for event in events if event.get("type") == "action"]
    approach_actions = actions[16:]
    assert len(approach_actions) == 16
    assert all(item["action"]["type"] == "move_to" for item in approach_actions)
    successful_approaches = [
        item for item in approach_actions if item["result"].get("success") is True
    ]
    failed_approaches = [
        item for item in approach_actions if item["result"].get("success") is not True
    ]
    assert len(successful_approaches) == 12
    assert len(failed_approaches) == 4
    for item in successful_approaches:
        result = item["result"]
        assert item["pre_observation"]["position"] == item["post_observation"][
            "position"
        ]
        assert item["post_observation"]["position"] == result["position"]
        assert result["navigation_reached"] is True
        assert result["target"] == {"x": 124.5, "y": 140, "z": -37.5}
        assert result["distance_to_target"] == pytest.approx(1.4205534244189506)
        current_cell = {
            axis: math.floor(result["position"][axis]) for axis in ("x", "y", "z")
        }
        target_cell = {
            axis: math.floor(result["target"][axis]) for axis in ("x", "y", "z")
        }
        assert current_cell == {"x": 124, "y": 141, "z": -37}
        assert target_cell == {"x": 124, "y": 140, "z": -38}
        assert current_cell != target_cell
    assert [item["result"]["error"] for item in failed_approaches] == [
        "SP-003 action guard rejected: "
        "acquire_cobblestone_navigation_target_must_be_nearest_observed"
    ] * 4
    assert not any(
        item["action"].get("parameters", {}).get("block") == "stone"
        for item in actions
    )

    ledger = json.loads(
        (REPO / "workspace/evals/stone_pickaxe_failure_ledger.json").read_text(
            encoding="utf-8"
        )
    )
    failure = next(
        item
        for item in ledger["failures"]
        if item["id"] == "sp003-baseline-017-exact-goalnear-false-resolution"
    )
    assert failure["automatic_retry_attempted"] is False
    assert failure["counts_toward_baseline_success"] is False
    assert len(failure["evidence"]) == 13
    for record in failure["evidence"]:
        path = REPO / record["path"]
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]


def test_phase111_retained_baseline_replays_deferred_pathfinder_stop_poisoning():
    run_dir = (
        REPO
        / "workspace/evals/sp003_runs/sp003_baseline_20260719_210605_35b1bb55"
    )
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    consumption = json.loads(
        (run_dir / "authorization_consumption.json").read_text(encoding="utf-8")
    )
    episode = json.loads((run_dir / "episode.json").read_text(encoding="utf-8"))
    events = json.loads((run_dir / "session.json").read_text(encoding="utf-8"))

    assert manifest["passed"] is False
    assert manifest["evidence_eligible"] is False
    assert manifest["authorization_id"] == (
        "c33ec22ec4f7090c98e6909f7b418ecaa4909f70687406f51ff253ae856f94cf"
    )
    assert manifest["automatic_retry_allowed"] is False
    assert manifest["bm012_terminal_started"] is False
    assert consumption["authorization_commit"] == (
        "e148ac113e77e5d7cb61ea4647060d8838813dc1"
    )
    assert consumption["consumed_by"] == "fresh_sp003_process_start"
    assert consumption["single_episode"] is True
    assert consumption["automatic_retry_allowed"] is False

    goal = episode["goal_result"]
    assert goal["termination_reason"] == "max_actions"
    assert goal["deadline_eligible"] is True
    assert goal["cycles"] == 33
    assert goal["action_count"] == 32
    assert goal["elapsed_s"] == pytest.approx(242.078)
    assert episode["action_count"] == 32
    assert len(episode["raw_action_failures"]) == 29
    assert episode["reconciled_action_failure_indexes"] == []
    assert len(episode["unreconciled_action_failures"]) == 29
    assert episode["post_deadline_action_indexes"] == []
    assert len(episode["distinct_log_source_ids"]) == 2
    assert episode["distinct_surface_clearance_source_ids"] == []
    assert episode["distinct_stone_source_ids"] == []
    assert episode["stable_observation"]["inventory"] == {"oak_log": 2}

    planner_calls = [
        event["data"]
        for event in events
        if event.get("type") == "llm_planner_call"
    ]
    assert [call["call_index"] for call in planner_calls] == list(range(33))
    assert all(call["schema_valid"] is True for call in planner_calls)
    assert all(
        call["transport_evidence"]["attempt_count"] == 1
        and call["transport_evidence"]["retry_count"] == 0
        and call["transport_evidence"]["attempts"][0]["success"] is True
        for call in planner_calls
    )
    assert max(
        call["provider_metadata"]["prompt_tokens"] for call in planner_calls
    ) == 2974
    assert max(call["response_byte_count"] for call in planner_calls) == 2095

    actions = [event["data"] for event in events if event.get("type") == "action"]
    assert [item["action"]["type"] for item in actions].count("move_to") == 26
    assert [item["action"]["type"] for item in actions].count("dig") == 6
    assert sum(item["result"].get("success") is True for item in actions) == 3

    first_pickup = actions[1]["result"]["pickup_collection"]["direct_navigation"]
    assert first_pickup["pathfinder_resolved"] is False
    assert first_pickup["error"] == "Took to long to decide path to goal!"
    assert first_pickup["timeout_ms"] == 6000
    assert first_pickup["final_distance"] == pytest.approx(1.8019531744461517)

    stopped_error = (
        "Path was stopped before it could be completed! Thus, the desired goal "
        "was not reached."
    )
    stopped_results = 0
    for item in actions:
        result = item["result"]
        direct = (result.get("pickup_collection") or {}).get("direct_navigation") or {}
        if direct.get("error") == stopped_error or result.get("error") == stopped_error:
            stopped_results += 1
    assert stopped_results == 28

    failed_moves = [
        item
        for item in actions
        if item["action"]["type"] == "move_to"
        and item["result"].get("success") is not True
    ]
    assert len(failed_moves) == 25
    assert all(item["result"]["error"] == stopped_error for item in failed_moves)
    assert all(
        item["pre_observation"]["position"]
        == item["post_observation"]["position"]
        == {"x": 119.45600961424827, "y": 141, "z": -33.59777074730486}
        for item in failed_moves
    )
    assert not any(
        item["action"]["type"] in {"craft", "place", "equip"}
        or item["action"].get("parameters", {}).get("block") == "stone"
        for item in actions
    )

    ledger = json.loads(
        (REPO / "workspace/evals/stone_pickaxe_failure_ledger.json").read_text(
            encoding="utf-8"
        )
    )
    failure = next(
        item
        for item in ledger["failures"]
        if item["id"] == "sp003-baseline-018-pathfinder-deferred-stop-poisoning"
    )
    assert failure["automatic_retry_attempted"] is False
    assert failure["counts_toward_baseline_success"] is False
    assert len(failure["evidence"]) == 13
    for record in failure["evidence"]:
        path = REPO / record["path"]
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]


def test_phase112_pathfinder_stop_drain_audit_binds_current_contract():
    audit_path = (
        REPO / "workspace/evals/stone_pickaxe_sp003_pathfinder_stop_drain_repair.json"
    )
    audit = json.loads(audit_path.read_text(encoding="utf-8"))

    assert audit["type"] == "stone_pickaxe_sp003_pathfinder_stop_drain_repair"
    assert audit["phase"] == 112
    assert audit["base_commit"] == "3bbeeca4d162882d37bf08e8bb00857f66a451b1"
    assert audit["policy_id"] == SP003_PATHFINDER_STOP_DRAIN_POLICY_ID
    assert audit["retained_failure"]["manifest_sha256"] == (
        "e4e1eb83a6a9adbd8e497cf142376e9566d9065b09b87b922f760d8e29bff37c"
    )
    assert audit["retained_failure"]["session_sha256"] == (
        "ea145b598724ed9e31209e57a319dde7cd6d87359ea952888901874c577acaf6"
    )
    assert audit["retained_failure"]["path_stopped_cascade_count"] == 28
    assert audit["retained_failure"]["failed_horizontal_move_count"] == 25
    assert audit["retained_failure"]["automatic_retry_attempted"] is False

    dependency = audit["dependency_root_cause"]
    assert dependency["public_stop_sets_deferred_flag_only"] is True
    assert dependency["reset_path_consumes_deferred_stop"] is True
    assert dependency["later_goto_consumes_prior_stop_before_pathing"] is True
    assert dependency["vendored_dependency_modified"] is False
    dependency_path = REPO / dependency["path"]
    assert hashlib.sha256(dependency_path.read_bytes()).hexdigest() == dependency[
        "sha256"
    ]

    contract = audit["repair_contract"]
    assert contract["scope"] == "sp003_process_local_preload_only"
    assert contract["public_stop_wrapped_once_per_bot"] is True
    assert contract["original_stop_calls_per_request_max"] == 1
    assert contract["original_stop_called_before_drain"] is True
    assert contract["drain_operation"] == "original_setGoal(null)"
    assert contract["drain_immediate_before_return"] is True
    assert contract["deferred_stop_clear_required_before_next_goto"] is True
    assert contract["active_goto_must_reject"] is True
    assert contract["active_goto_false_success_allowed"] is False
    assert contract["navigation_retry_allowed"] is False
    assert contract["action_retry_allowed"] is False
    assert contract["world_mutation_allowed"] is False
    assert contract["shared_bridge_changed"] is False
    assert contract["base_protocol_changed"] is False

    replay = audit["retained_replay"]
    assert replay["phase_111_initial_pickup_timeout_preserved"] is True
    assert replay["phase_111_path_stopped_cascade_count"] == 28
    assert replay["deferred_stop_consumed_immediately"] is True
    assert replay["simulated_original_stop_call_count"] == 1
    assert replay["simulated_set_goal_null_call_count"] == 1
    assert replay["simulated_next_goto_succeeded"] is True
    assert replay["simulated_hidden_retry_count"] == 0
    assert replay["active_goto_rejected"] is True
    assert replay["active_goto_false_success"] is False
    assert replay["integrated_dig_pickup_timeout_preserved"] is True
    assert replay["integrated_following_move_passed"] is True
    assert replay["integrated_total_goto_count"] == 2
    assert replay["drain_world_mutation_count"] == 0

    for record in audit["implementation"]:
        path = REPO / record["path"]
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]
    protected = audit["protected_identities"]
    for prefix in ("shared_bridge", "base_protocol"):
        actual_sha256 = hashlib.sha256(
            (REPO / protected[f"{prefix}_path"]).read_bytes()
        ).hexdigest()
        assert actual_sha256 == protected[f"{prefix}_sha256"]
    assert audit["live_episode_run"] is False
    assert audit["live_authorization"] is False
    assert audit["automatic_retry_allowed"] is False
    assert audit["counts_toward_capability"] is False


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


def test_phase97_table_reference_replay_repairs_only_observed_unsafe_target():
    session_path = (
        REPO
        / "workspace/evals/sp003_runs/sp003_baseline_20260719_121946_1d855e28/session.json"
    )
    events = json.loads(session_path.read_text(encoding="utf-8"))
    retained_guard = next(
        event
        for event in events
        if event.get("type") == "stone_pickaxe_sp003_action_guard"
        and (event.get("data") or {}).get("action", {}).get("type") == "place"
        and (event.get("data") or {}).get("action", {}).get("parameters", {}).get("x")
        == 118
    )
    retained_action = next(
        event
        for event in events
        if event.get("type") == "action"
        and (event.get("data") or {}).get("action", {}).get("type") == "place"
        and (event.get("data") or {}).get("action", {}).get("parameters", {}).get("x")
        == 118
    )
    guard_data = retained_guard["data"]
    action_data = retained_action["data"]

    repaired = guard_sp003_action(
        copy.deepcopy(guard_data["action"]),
        copy.deepcopy(action_data["pre_observation"]),
        copy.deepcopy(guard_data["progress"]),
    )

    assert repaired["allowed"], repaired
    assert repaired["action"]["parameters"] == {
        "item": "crafting_table",
        "x": 119,
        "y": 139,
        "z": -33,
        "reference_source_id": "dirt:119:139:-33",
    }
    assert repaired["selected_source"]["source_id"] == "dirt:119:139:-33"
    assert repaired["action_repair"]["policy_id"] == (
        "sp003-table-reference-clear-target-repair-v1"
    )
    assert repaired["action_repair"]["attempt_limit"] == 1
    assert repaired["action_repair"]["attempt_count"] == 1
    assert repaired["action_repair"]["requested_reference"]["source_id"] == (
        "grass_block:118:139:-33"
    )
    assert repaired["action_repair"]["selected_reference"]["source_id"] == (
        "dirt:119:139:-33"
    )

    unobserved = guard_sp003_action(
        {
            "type": "place",
            "parameters": {
                "item": "crafting_table",
                "x": 999,
                "y": 139,
                "z": -33,
            },
        },
        copy.deepcopy(action_data["pre_observation"]),
        copy.deepcopy(guard_data["progress"]),
    )
    assert not unobserved["allowed"]
    assert unobserved["action_repair"] == {}
    assert "sp003_table_reference_must_be_observed_solid_with_clear_target" in (
        unobserved["issues"]
    )


def test_stone_guard_requires_held_wooden_pickaxe_nearest_source_and_exact_limit():
    progress = preparation_progress()
    progress.update({
        "plank_craft_count": 1,
        "stick_craft_count": 1,
        "crafting_table_craft_count": 1,
        "crafting_table_place_count": 1,
        "wooden_pickaxe_craft_count": 1,
    })
    stones = [
        block("stone", 1, 63, 0, 1.4),
        block("stone", 2, 63, 0, 2.2),
        block("stone", 1, 62, 0, 2.2),
    ]
    no_tool_world = observation({"wooden_pickaxe": 1}, stones)
    attach_complete_sp003_scan(
        no_tool_world,
        [stones[0], stones[2]],
        origin={"x": 0, "y": 64, "z": 0},
    )
    no_tool = guard_sp003_action(
        {"type": "dig", "parameters": {"block": "stone", "x": 1, "y": 63, "z": 0}},
        no_tool_world,
        progress,
    )
    assert "sp003_stone_dig_requires_held_wooden_pickaxe" in no_tool["issues"]
    held_world = copy.deepcopy(no_tool_world)
    held_world["equipment"] = [{"name": "wooden_pickaxe", "count": 1}]
    farther = guard_sp003_action(
        {"type": "dig", "parameters": {"block": "stone", "x": 2, "y": 63, "z": 0}},
        held_world,
        progress,
    )
    assert "sp003_stone_target_must_be_nearest_observed" in farther["issues"]
    nearest = guard_sp003_action(
        {"type": "dig", "parameters": {"block": "stone", "x": 1, "y": 63, "z": 0}},
        held_world,
        progress,
    )
    assert nearest["allowed"], nearest
    assert nearest["action"]["parameters"]["stone_pickup_access"] is True
    safe_blocks = [
        block("stone", 0, 63, 0, 1.0),
        block("stone", 1, 63, 0, 1.4),
        block("stone", 0, 62, 0, 2.0),
        block("stone", 1, 62, 0, 2.2),
    ]
    support_safe_world = observation(
        {"wooden_pickaxe": 1},
        safe_blocks,
        held="wooden_pickaxe",
    )
    attach_complete_sp003_scan(
        support_safe_world,
        safe_blocks,
        origin={"x": 0, "y": 64, "z": 0},
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


def retained_phase95_log_actions():
    session_path = (
        REPO
        / "workspace/evals/sp003_runs/"
        "sp003_baseline_20260719_112312_39755e3d/session.json"
    )
    events = json.loads(session_path.read_text(encoding="utf-8"))
    return [
        copy.deepcopy(event["data"])
        for event in events
        if event.get("type") == "action"
        and event.get("data", {}).get("action", {}).get("parameters", {}).get(
            "source_id"
        )
        in {
            "oak_log:119:142:-33",
            "oak_log:119:141:-33",
            "oak_log:119:140:-33",
        }
    ]


def test_phase95_delayed_pickup_replay_reconciles_exact_pending_source():
    first, second, third = retained_phase95_log_actions()
    progress = _empty_progress()

    after_first = record_sp003_success(progress, first["action"], first["result"])
    assert after_first["log_source_removal_count"] == 0
    assert after_first["pending_log_pickup_count"] == 1
    pending = after_first["pending_log_pickups"][0]
    assert pending["source_id"] == "oak_log:119:142:-33"
    assert pending["proof_fingerprint"] == canonical_sha256({
        key: value
        for key, value in pending.items()
        if key != "proof_fingerprint"
    })

    after_second = record_sp003_success(
        progress,
        second["action"],
        second["result"],
    )
    assert after_second["log_source_ids"] == [
        "oak_log:119:141:-33",
        "oak_log:119:142:-33",
    ]
    assert after_second["pending_log_pickup_count"] == 0
    assert after_second["delayed_log_pickup_reconciliation_count"] == 1
    reconciliation = second["result"][
        "sp003_delayed_log_pickup_reconciliation"
    ]
    assert reconciliation["current_source_reserved_count"] == 1
    assert reconciliation["surplus_pickup_count"] == 1
    assert reconciliation["reconciled_pending_source_ids"] == [
        "oak_log:119:142:-33"
    ]

    after_third = record_sp003_success(
        progress,
        third["action"],
        third["result"],
    )
    assert after_third["log_source_removal_count"] == 3
    plank = guard_sp003_action(
        {"type": "craft", "parameters": {"item": "oak_planks", "count": 12}},
        observation({"oak_log": 3}),
        progress,
    )
    assert plank["allowed"], plank


@pytest.mark.parametrize(
    "tamper",
    [
        lambda result: result["target_block_before"].update({"name": "air"}),
        lambda result: result["pickup_collection"].update({"detected": False}),
        lambda result: result["pickup_collection"].update({"item_name": "birch_log"}),
        lambda result: result.update({"expected_drops": ["stick"]}),
    ],
)
def test_pending_removed_log_requires_exact_machine_proof(tamper):
    first, _, _ = retained_phase95_log_actions()
    tamper(first["result"])
    progress = _empty_progress()

    after = record_sp003_success(progress, first["action"], first["result"])

    assert after["pending_log_pickup_count"] == 0
    assert after["log_source_removal_count"] == 0


def test_delayed_pickup_reconciliation_is_idempotent_and_surplus_bounded():
    first, second, _ = retained_phase95_log_actions()
    progress = _empty_progress()
    record_sp003_success(progress, first["action"], first["result"])
    record_sp003_success(progress, first["action"], first["result"])
    assert _progress_snapshot(progress)["pending_log_pickup_count"] == 1

    no_surplus = copy.deepcopy(second)
    no_surplus["result"]["pickup_inventory_delta"] = {"oak_log": 1}
    after = record_sp003_success(
        progress,
        no_surplus["action"],
        no_surplus["result"],
    )
    assert after["log_source_removal_count"] == 1
    assert after["pending_log_pickup_count"] == 1
    assert after["delayed_log_pickup_reconciliation_count"] == 0

    wrong_family = copy.deepcopy(second)
    wrong_family["action"]["parameters"].update({
        "block": "birch_log",
        "source_id": "birch_log:119:141:-33",
    })
    wrong_family["result"].update({
        "block": "birch_log",
        "pickup_inventory_delta": {"birch_log": 2},
    })
    wrong_family["result"]["target_block_before"]["name"] = "birch_log"
    wrong_after = record_sp003_success(
        progress,
        wrong_family["action"],
        wrong_family["result"],
    )
    assert wrong_after["log_source_removal_count"] == 1
    assert wrong_after["pending_log_pickup_count"] == 1
    assert wrong_after["delayed_log_pickup_reconciliation_count"] == 0


def test_one_pickup_surplus_reconciles_only_oldest_of_two_pending_sources():
    first, second, _ = retained_phase95_log_actions()
    progress = _empty_progress()
    record_sp003_success(progress, first["action"], first["result"])
    extra = copy.deepcopy(first)
    extra["action"]["parameters"].update({
        "x": 118,
        "source_id": "oak_log:118:142:-33",
    })
    extra["result"]["target"].update({"x": 118})
    extra["result"]["target_block_before"]["position"].update({"x": 118})
    extra["result"]["target_block_after"]["position"].update({"x": 118})
    extra["result"]["pickup_collection"]["entity_id"] += 1
    record_sp003_success(progress, extra["action"], extra["result"])
    assert _progress_snapshot(progress)["pending_log_pickup_count"] == 2

    after = record_sp003_success(progress, second["action"], second["result"])

    assert after["log_source_ids"] == [
        "oak_log:119:141:-33",
        "oak_log:119:142:-33",
    ]
    assert after["pending_log_pickup_count"] == 1
    assert after["pending_log_pickups"][0]["source_id"] == "oak_log:118:142:-33"


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


def test_sp003_move_to_envelope_uses_horizontal_required_axes_only():
    plan = {
        "schema_version": "stone-pickaxe-plan-v1",
        "plan_kind": "continuation",
        "goal": SP003_GOAL,
        "status": "planning",
        "reasoning": "Approach the machine-grounded clearance probe.",
        "subtasks": [],
        "actions": [{"type": "move_to", "parameters": {"x": 124, "z": -37}}],
    }

    horizontal = Planner._validate_stone_pickaxe_plan_envelope(
        plan,
        SP003_GOAL,
        "continuation",
        "sp003",
    )
    assert horizontal["passed"], horizontal

    with_y = copy.deepcopy(plan)
    with_y["actions"][0]["parameters"]["y"] = 139
    report = Planner._validate_stone_pickaxe_plan_envelope(
        with_y,
        SP003_GOAL,
        "continuation",
        "sp003",
    )
    assert report["passed"], report

    for invalid_y in (None, True, "139", math.inf, math.nan):
        invalid = copy.deepcopy(plan)
        invalid["actions"][0]["parameters"]["y"] = invalid_y
        report = Planner._validate_stone_pickaxe_plan_envelope(
            invalid,
            SP003_GOAL,
            "continuation",
            "sp003",
        )
        assert report["issues"] == ["action_parameter_y_invalid"]

    for runtime_mode in ("", "sp001", "sp002"):
        report = Planner._validate_stone_pickaxe_plan_envelope(
            plan,
            SP003_GOAL,
            "continuation",
            runtime_mode,
        )
        assert "action_parameter_y_invalid" in report["issues"]

    look_at = copy.deepcopy(plan)
    look_at["actions"][0]["type"] = "look_at"
    report = Planner._validate_stone_pickaxe_plan_envelope(
        look_at,
        SP003_GOAL,
        "continuation",
        "sp003",
    )
    assert "action_parameter_y_invalid" in report["issues"]


def test_planner_compacts_sp003_state_and_requires_exact_five_node_graph():
    policy = json.loads(SP003_POLICY_PATH.read_text(encoding="utf-8"))
    world = observation({}, [block("oak_log", 2, 64, 0, 2.0)])
    world.update({
        "stone_pickaxe_runtime_mode": "sp003",
        "sp003_arm": "baseline",
        "flags": ["sp003_wood_acquired"],
        "sp003_progress": {
            "log_source_removal_count": 3,
            "log_item": "oak_log",
        },
        "sp003_targets": [{"name": "oak_log", "position": {"x": 2, "y": 64, "z": 0}}],
    })
    world["inventory"] = {"oak_log": 3}
    compact = Planner._compact_stone_pickaxe_state(world)
    assert compact["runtime_mode"] == "sp003"
    assert compact["flags"] == ["sp003_wood_acquired"]
    assert compact["sp003_stage"] == "craft_matching_planks"
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
    verbose = copy.deepcopy(valid)
    verbose["reasoning"] = "x" * 321
    report = Planner._validate_stone_pickaxe_plan_envelope(
        verbose,
        SP003_GOAL,
        "root",
        "sp003",
    )
    assert not report["passed"]
    assert "reasoning_too_long" in report["issues"]
    planner = object.__new__(Planner)
    planner.strict_m2 = False
    planner.strict_m4 = False
    planner.strict_stone_pickaxe = True
    planner._expected_plan_kind = "continuation"
    prompt = Planner._stone_pickaxe_system_prompt(planner)
    assert "has canopy_egress=true, it is navigation-only" in prompt
    assert "has stone_surface_clearance=true, dig exactly that entry's block" in prompt
    assert "never dig its support_source_id stone" in prompt
    assert "has stone_clearance_probe=true, it is navigation-only" in prompt
    assert "wait for the bounded clearance scan" in prompt
    assert "has stone_pickup_approach=true, it is navigation-only" in prompt
    assert "let the action guard bind the machine-proven stand y" in prompt
    assert "require stone_pickup_access=true on the first target" in prompt
    assert "more than six machine-proven" in prompt
    assert "when that wood target's distance exceeds 4.5" in prompt
    assert "never add 1 to y or emit target_position" in prompt
    assert "when it exceeds 4.5 emit move_to with only that target's x and z" in prompt
    assert "Never dig a block directly below the player" in prompt

    planner._expected_plan_kind = "root"
    user_prompt = Planner._build_planning_prompt(planner, SP003_GOAL, world, "")
    assert len(user_prompt) <= 5000
    assert "SP-003 authoritative machine stage: craft_matching_planks." in user_prompt


def test_phase101_first_stage_drift_replays_as_exact_table_craft_stage():
    run_dir = (
        REPO
        / "workspace/evals/sp003_runs/sp003_baseline_20260719_143554_ded97c9b"
    )
    events = json.loads((run_dir / "session.json").read_text(encoding="utf-8"))
    call_index = next(
        index
        for index, event in enumerate(events)
        if event.get("type") == "llm_planner_call"
        and event.get("data", {}).get("call_index") == 6
    )
    full = next(
        event["data"]
        for event in reversed(events[:call_index])
        if event.get("type") == "observation"
    )

    compact = Planner._compact_stone_pickaxe_state(full)
    exact = guard_sp003_action(
        {"type": "craft", "parameters": {"item": "crafting_table", "count": 1}},
        full,
        full["sp003_progress"],
    )
    stale = guard_sp003_action(
        {"type": "craft", "parameters": {"item": "oak_planks", "count": 2}},
        full,
        full["sp003_progress"],
    )

    assert compact["sp003_stage"] == "craft_crafting_table"
    assert exact["allowed"], exact
    assert not stale["allowed"]
    assert stale["issues"] == ["sp003_exact_one_table_craft_required"]


@pytest.mark.parametrize(
    ("progress_updates", "inventory", "held", "blocks", "expected"),
    [
        ({}, {}, "", [], "acquire_wood"),
        (
            {"log_source_removal_count": 3, "log_item": "oak_log"},
            {"oak_log": 2},
            "",
            [],
            "await_log_pickup",
        ),
        (
            {"log_source_removal_count": 3, "log_item": "oak_log"},
            {"oak_log": 3},
            "",
            [],
            "craft_matching_planks",
        ),
        (
            {
                "log_source_removal_count": 3,
                "log_item": "oak_log",
                "plank_craft_count": 1,
            },
            {"oak_planks": 12},
            "",
            [],
            "craft_sticks",
        ),
        (
            {
                "log_source_removal_count": 3,
                "log_item": "oak_log",
                "plank_craft_count": 1,
                "stick_craft_count": 1,
            },
            {"oak_planks": 10, "stick": 4},
            "",
            [],
            "craft_crafting_table",
        ),
        (
            {
                "log_source_removal_count": 3,
                "log_item": "oak_log",
                "plank_craft_count": 1,
                "stick_craft_count": 1,
                "crafting_table_craft_count": 1,
            },
            {"crafting_table": 1, "oak_planks": 6, "stick": 4},
            "",
            [],
            "place_crafting_table",
        ),
        (
            {
                "log_source_removal_count": 3,
                "log_item": "oak_log",
                "plank_craft_count": 1,
                "stick_craft_count": 1,
                "crafting_table_craft_count": 1,
                "crafting_table_place_count": 1,
            },
            {"oak_planks": 6, "stick": 4},
            "",
            [],
            "return_to_crafting_table",
        ),
        (
            {
                "log_source_removal_count": 3,
                "log_item": "oak_log",
                "plank_craft_count": 1,
                "stick_craft_count": 1,
                "crafting_table_craft_count": 1,
                "crafting_table_place_count": 1,
            },
            {"oak_planks": 6, "stick": 4},
            "",
            [block("crafting_table", 1, 64, 0, 1.0)],
            "craft_wooden_pickaxe",
        ),
        (
            {"wooden_pickaxe_craft_count": 1},
            {"wooden_pickaxe": 1},
            "",
            [],
            "equip_wooden_pickaxe",
        ),
        (
            {"wooden_pickaxe_craft_count": 1},
            {"wooden_pickaxe": 1},
            "wooden_pickaxe",
            [],
            "acquire_cobblestone",
        ),
        (
            {
                "wooden_pickaxe_craft_count": 1,
                "stone_source_removal_count": 3,
            },
            {"wooden_pickaxe": 1, "cobblestone": 2},
            "wooden_pickaxe",
            [],
            "await_cobblestone_pickup",
        ),
        (
            {
                "wooden_pickaxe_craft_count": 1,
                "stone_source_removal_count": 3,
            },
            {"wooden_pickaxe": 1, "cobblestone": 3, "stick": 2},
            "wooden_pickaxe",
            [],
            "return_to_crafting_table",
        ),
        (
            {
                "wooden_pickaxe_craft_count": 1,
                "stone_source_removal_count": 3,
            },
            {"wooden_pickaxe": 1, "cobblestone": 3, "stick": 2},
            "wooden_pickaxe",
            [block("crafting_table", 1, 64, 0, 1.0)],
            "craft_stone_pickaxe",
        ),
        (
            {"stone_pickaxe_craft_count": 1},
            {"stone_pickaxe": 1},
            "",
            [],
            "complete",
        ),
    ],
)
def test_sp003_compact_state_exposes_exact_machine_stage(
    progress_updates,
    inventory,
    held,
    blocks,
    expected,
):
    world = observation(inventory, blocks, held=held)
    progress = _progress_snapshot(_empty_progress())
    progress.update(progress_updates)
    world.update({
        "stone_pickaxe_runtime_mode": "sp003",
        "sp003_arm": "baseline",
        "sp003_progress": progress,
        "sp003_targets": [],
    })

    compact = Planner._compact_stone_pickaxe_state(world)

    assert compact["sp003_stage"] == expected


def test_sp003_compact_state_uses_one_whitelisted_target_without_proof_body():
    world = observation(
        {"wooden_pickaxe": 1},
        [block("stone", index, 61, 0, float(index)) for index in range(1, 10)],
        held="wooden_pickaxe",
    )
    progress = _progress_snapshot(_empty_progress())
    progress["wooden_pickaxe_craft_count"] = 1
    first = {
        "source_id": "grass_block:1:63:0",
        "name": "grass_block",
        "position": {"x": 1, "y": 63, "z": 0},
        "distance": 1.25,
        "horizontal_distance": 1.0,
        "stand_position": {"x": 0, "y": 64, "z": 0},
        "navigation_only": True,
        "stone_surface_clearance": True,
        "support_source_id": "stone:1:62:0",
        "remaining_clearance_count": 3,
        "clearance_proof": {"history": ["x" * 1000] * 20},
        "unexpected": "x" * 10000,
    }
    world.update({
        "stone_pickaxe_runtime_mode": "sp003",
        "sp003_arm": "baseline",
        "sp003_progress": progress,
        "sp003_targets": [first, {"source_id": "stone:2:62:0"}],
    })

    compact = Planner._compact_stone_pickaxe_state(world)
    target = compact["sp003_targets"][0]

    assert len(compact["sp003_targets"]) == 1
    assert target["source_id"] == first["source_id"]
    assert target["position"] == first["position"]
    assert target["stone_surface_clearance"] is True
    assert "clearance_proof" not in target
    assert "unexpected" not in target
    assert len(json.dumps(compact, sort_keys=True, separators=(",", ":"))) <= 2500


def test_phase101_terminal_observation_compacts_to_bounded_stage_grounded_prompt():
    run_dir = (
        REPO
        / "workspace/evals/sp003_runs/sp003_baseline_20260719_143554_ded97c9b"
    )
    events = json.loads((run_dir / "session.json").read_text(encoding="utf-8"))
    call_index = next(
        index
        for index, event in enumerate(events)
        if event.get("type") == "llm_planner_call"
        and event.get("data", {}).get("call_index") == 19
    )
    full = next(
        event["data"]
        for event in reversed(events[:call_index])
        if event.get("type") == "observation"
    )
    assert len(json.dumps(full["sp003_progress"], default=str)) > 2000
    assert len(json.dumps(full["sp003_targets"], default=str)) > 11000

    compact = Planner._compact_stone_pickaxe_state(full)
    compact_json = json.dumps(compact, sort_keys=True, separators=(",", ":"))

    assert compact["sp003_stage"] == "acquire_cobblestone"
    assert len(compact["sp003_targets"]) == 1
    assert compact["sp003_targets"][0]["source_id"] == (
        full["sp003_targets"][0]["source_id"]
    )
    assert len(compact_json) <= 2500
    assert "clearance_proof" not in compact_json
    for excluded in (
        "log_source_ids",
        "pending_log_pickups",
        "delayed_log_pickup_reconciliations",
        "surface_clearance_source_ids",
        "stone_source_ids",
        "successful_mutations",
    ):
        assert excluded not in compact["sp003_progress"]

    planner = object.__new__(Planner)
    planner.strict_m2 = False
    planner.strict_m4 = False
    planner.strict_stone_pickaxe = True
    planner._expected_plan_kind = "continuation"
    prompt = Planner._build_planning_prompt(planner, SP003_GOAL, full, "")

    assert len(prompt) <= 5000
    assert "SP-003 authoritative machine stage: acquire_cobblestone." in prompt
    assert "clearance_proof" not in prompt


def test_non_sp003_compaction_retains_general_shape_without_machine_stage():
    world = observation(
        {"wooden_pickaxe": 1},
        [block("stone", index, 63, 0, float(index)) for index in range(1, 12)],
        held="wooden_pickaxe",
    )

    compact = Planner._compact_stone_pickaxe_state(world)

    assert compact["runtime_mode"] == ""
    assert compact["sp003_stage"] == ""
    assert compact["sp003_progress"] == {}
    assert compact["sp003_targets"] == []
    assert len(compact["nearby_blocks"]) == 11


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
        pickup_scan = complete_block_scan(
            [
                block("stone", offset, 63, 0, 1.0),
                block("stone", offset, 62, 0, 2.0),
            ],
            origin={"x": offset - 1, "y": 64, "z": 0},
        )
        pickup_access = _stone_pickup_accesses(pickup_scan)[0]
        pickup_proof = pickup_access["pickup_access_proof"]
        params = {
            "block": "stone",
            "x": offset,
            "y": 63,
            "z": 0,
            "source_id": f"stone:{offset}:63:0",
            "stone_pickup_access": True,
            "pickup_access_proof": pickup_proof,
            "pickup_access_proof_fingerprint": canonical_sha256(pickup_proof),
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


def delayed_pickup_synthetic_sp003_events():
    initial, terminal, events = synthetic_sp003_events()
    first = events[0]["data"]
    second = events[1]["data"]
    for data in (first, second):
        position = {
            axis: data["action"]["parameters"][axis]
            for axis in ("x", "y", "z")
        }
        data["result"]["target_block_before"]["position"] = dict(position)
        data["result"]["target_block_after"]["position"] = dict(position)
    first["result"].update({
        "success": False,
        "expected_drops": ["oak_log"],
        "pickup_observed": False,
        "pickup_inventory_delta": {},
        "pickup_collection": {
            "detected": True,
            "attempted": True,
            "entity_id": 827,
            "item_name": "oak_log",
            "position": {"x": 1.25, "y": 64.0, "z": 0.25},
            "success": False,
            "completion_grounded": False,
        },
        "dig_postcondition": {
            "required": True,
            "block_removed": True,
            "expected_drop_required": True,
            "expected_drop_observed": False,
            "passed": False,
        },
        "error": "expected block drop was not acquired",
    })
    first["post_observation"] = observation(
        {},
        [
            block("oak_log", 2, 64, 0, 2.0),
            block("oak_log", 3, 64, 0, 3.0),
        ],
    )
    second["pre_observation"] = copy.deepcopy(first["post_observation"])
    second["result"]["pickup_inventory_delta"] = {"oak_log": 2}

    progress = _empty_progress()
    for event in events[:3]:
        data = event["data"]
        record_sp003_success(progress, data["action"], data["result"])
    assert _progress_snapshot(progress)["log_source_removal_count"] == 3
    return initial, terminal, events


def build_passing_episode(monkeypatch, *, scenario=None):
    monkeypatch.setattr(
        "singularity.evaluation.stone_pickaxe_sp003_runtime.planner_request_controls_audit",
        lambda _events: {"passed": True, "issues": [], "call_count": 13},
    )
    initial, terminal, events = scenario or synthetic_sp003_events()
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


def test_episode_verifier_reconstructs_saturated_pickup_visibility(monkeypatch):
    initial, terminal, events = synthetic_sp003_events()
    target_cell = (1, 63, 0)
    support_cell = (1, 62, 0)
    head_cell = (1, 64, 0)
    excluded = {
        (0, 64, 0),
        (0, 65, 0),
        target_cell,
        support_cell,
        head_cell,
    }
    dense = [
        block(
            "dirt",
            x,
            y,
            z,
            math.sqrt(x * x + (y - 64) ** 2 + z * z),
        )
        for x in range(-1, 2)
        for y in range(61, 68)
        for z in range(-1, 2)
        if (x, y, z) not in excluded
    ]
    dense.extend([
        block("stone", *target_cell, math.sqrt(2)),
        block("stone", *support_cell, math.sqrt(5)),
    ])
    world = observation(
        {"wooden_pickaxe": 1},
        dense,
        held="wooden_pickaxe",
        position={"x": 0.5, "y": 64.0, "z": 0.5},
    )
    scan = _bounded_complete_local_scan(
        world,
        prioritize_block_response(dense),
        world,
    )
    pickup_proof = next(
        item["pickup_access_proof"]
        for item in _stone_pickup_accesses(scan)
        if item["source_id"] == "stone:1:63:0"
    )
    first_stone = next(
        event
        for event in events
        if event["data"]["action"]["type"] == "dig"
        and event["data"]["action"]["parameters"].get("source_id")
        == "stone:1:63:0"
    )
    first_stone["data"]["action"]["parameters"].update({
        "pickup_access_proof": pickup_proof,
        "pickup_access_proof_fingerprint": canonical_sha256(pickup_proof),
    })

    episode = build_passing_episode(
        monkeypatch,
        scenario=(initial, terminal, events),
    )
    report = verify_sp003_runtime_episode(episode)
    assert report["passed"], report

    tampered = copy.deepcopy(episode)
    transition = tampered["stone_pickup_access_transition_proofs"][0]
    transition["proof"]["visibility_distance_strict_upper_bound"] += 0.25
    transition["proof_fingerprint"] = canonical_sha256(transition["proof"])
    rejected = verify_sp003_runtime_episode(tampered)
    assert "pre_dig_pickup_access_machine_proof" in rejected["criteria_issues"]


def test_delayed_pickup_episode_preserves_raw_failure_and_passes_reconciliation(
    monkeypatch,
):
    episode = build_passing_episode(
        monkeypatch,
        scenario=delayed_pickup_synthetic_sp003_events(),
    )
    report = verify_sp003_runtime_episode(episode)

    assert report["passed"], report
    assert len(episode["action_failures"]) == 1
    assert episode["action_failures"] == episode["raw_action_failures"]
    assert episode["reconciled_action_failure_indexes"] == [1]
    assert episode["unreconciled_action_failures"] == []
    assert len(episode["pending_log_pickup_proofs"]) == 1
    assert len(episode["delayed_log_pickup_reconciliation_proofs"]) == 1
    assert report["criteria"]["transparent_raw_action_failure_accounting"] is True
    assert report["criteria"][
        "delayed_log_pickup_reconciliation_machine_proof"
    ] is True
    assert report["criteria"]["zero_unreconciled_action_failures"] is True
    assert report["metrics"]["raw_action_failure_count"] == 1
    assert report["metrics"]["reconciled_action_failure_count"] == 1


@pytest.mark.parametrize(
    "tamper",
    [
        lambda episode: episode["pending_log_pickup_proofs"][0]["proof"].update(
            {"drop_item_name": "birch_log"}
        ),
        lambda episode: episode[
            "delayed_log_pickup_reconciliation_proofs"
        ][0]["proof"].update({"surplus_pickup_count": 2}),
        lambda episode: episode.update({"raw_action_failures": []}),
        lambda episode: episode.update({"reconciled_action_failure_indexes": []}),
    ],
)
def test_delayed_pickup_episode_verifier_rejects_tamper(monkeypatch, tamper):
    episode = build_passing_episode(
        monkeypatch,
        scenario=delayed_pickup_synthetic_sp003_events(),
    )
    tamper(episode)

    report = verify_sp003_runtime_episode(episode)

    assert not report["passed"]
    assert any(
        issue
        in {
            "delayed_log_pickup_reconciliation_machine_proof",
            "log_transition_machine_proof",
            "transparent_raw_action_failure_accounting",
        }
        for issue in report["criteria_issues"]
    )


def add_bounded_surface_clearance_evidence(episode):
    obstruction_sets = [
        [
            block("dirt", 1, 62, 0, 2.236068),
            block("dirt", 1, 63, 0, 1.414214),
            block("grass_block", 1, 64, 0, 1.0),
        ],
        [
            block("dirt", 1, 62, 0, 2.236068),
            block("dirt", 1, 63, 0, 1.414214),
        ],
        [block("dirt", 1, 62, 0, 2.236068)],
    ]
    transitions = []
    for column in (1, -1):
        support = block("stone", column, 61, 0, 3.162278)
        for obstructions in obstruction_sets:
            shifted = [
                block(
                    item["name"],
                    column,
                    item["position"]["y"],
                    0,
                    item["distance"],
                )
                for item in obstructions
            ]
            scan = complete_block_scan(
                [support, *shifted],
                origin={"x": 0, "y": 64, "z": 0},
            )
            target = _stone_surface_clearances(scan)[0]
            proof = target["clearance_proof"]
            transitions.append({
                "index": 9 + len(transitions) + 1,
                "source_id": target["source_id"],
                "source_block": target["name"],
                "support_source_id": target["support_source_id"],
                "action_verified": True,
                "block_removed": True,
                "target_block_before": target["name"],
                "target_block_after": "air",
                "proof_fingerprint": canonical_sha256(proof),
                "proof": copy.deepcopy(proof),
            })
    episode["surface_clearance_transition_proofs"] = transitions
    episode["distinct_surface_clearance_source_ids"] = sorted(
        item["source_id"] for item in transitions
    )
    episode["action_type_counts"]["dig:grass_block"] = 2
    episode["action_type_counts"]["dig:dirt"] = 4
    episode["action_count"] += 6
    episode["goal_result"]["cycles"] += 6
    return episode


def test_machine_verifier_accepts_six_bounded_clearances_and_rejects_tamper_or_seventh(
    monkeypatch,
):
    episode = add_bounded_surface_clearance_evidence(build_passing_episode(monkeypatch))
    passed = verify_sp003_runtime_episode(episode)
    assert passed["passed"], passed
    assert passed["metrics"]["surface_clearance_removal_count"] == 6

    tampered = copy.deepcopy(episode)
    tampered["surface_clearance_transition_proofs"][0]["proof"][
        "selected_is_highest_obstruction"
    ] = False
    assert "bounded_surface_clearance_machine_proof" in verify_sp003_runtime_episode(
        tampered
    )["criteria_issues"]

    seventh = copy.deepcopy(episode)
    seventh["action_type_counts"]["dig:dirt"] = 5
    seventh["action_count"] += 1
    seventh["surface_clearance_transition_proofs"].append(
        copy.deepcopy(seventh["surface_clearance_transition_proofs"][-1])
    )
    seventh["surface_clearance_transition_proofs"][-1]["source_id"] = "dirt:2:62:0"
    seventh["distinct_surface_clearance_source_ids"].append("dirt:2:62:0")
    assert "bounded_surface_clearance_machine_proof" in verify_sp003_runtime_episode(
        seventh
    )["criteria_issues"]


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
    covered_pickup = copy.deepcopy(episode)
    covered_pickup["stone_pickup_access_transition_proofs"][0]["proof"][
        "head_cell_state"
    ] = "dirt"
    assert "pre_dig_pickup_access_machine_proof" in verify_sp003_runtime_episode(
        covered_pickup
    )["criteria_issues"]
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
