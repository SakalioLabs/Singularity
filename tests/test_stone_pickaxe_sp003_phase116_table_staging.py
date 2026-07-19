from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from singularity.core.planner import Planner
from singularity.evaluation import stone_pickaxe_sp003_runtime as base
from singularity.evaluation.stone_pickaxe_sp003_phase116_runtime import (
    SP003_TABLE_STAGING_POLICY_ID,
    StonePickaxeSP003Phase116RuntimeAgent,
    _table_staging_state,
    _table_staging_target,
    guard_sp003_phase116_action,
)


REPO = Path(__file__).resolve().parents[1]
PHASE116_FIX_COMMIT = "c5f120cc89d55ca31e3fcdaebef9aa7f2b7838a3"
RUN_DIR = (
    REPO
    / "workspace/evals/sp003_runs/sp003_baseline_20260719_232840_66a67eeb"
)


@pytest.fixture(scope="module")
def events():
    return json.loads((RUN_DIR / "session.json").read_text(encoding="utf-8"))


def _pre_guard_observation(events, predicate):
    guard_index = next(
        index
        for index, event in enumerate(events)
        if event.get("type") == "stone_pickaxe_sp003_action_guard"
        and predicate(event.get("data", {}).get("action", {}))
    )
    return copy.deepcopy(
        next(
            event["data"]
            for event in reversed(events[:guard_index])
            if event.get("type") == "observation"
            and isinstance(event.get("data"), dict)
        )
    )


def _action_event(events, source_id):
    return next(
        event["data"]
        for event in events
        if event.get("type") == "action"
        and event.get("data", {}).get("action", {}).get("parameters", {}).get(
            "source_id"
        )
        == source_id
    )


def _staged_progress(observation, surface_ids=()):
    retained = observation["sp003_progress"]
    progress = base._empty_progress()
    progress.update(
        {
            "log_source_ids": set(retained["log_source_ids"]),
            "log_item": retained["log_item"],
            "plank_craft_count": 1,
            "stick_craft_count": 1,
            "crafting_table_craft_count": 1,
            "crafting_table_place_count": 0,
            "wooden_pickaxe_craft_count": 0,
            "wooden_pickaxe_equip_count": 0,
            "surface_clearance_source_ids": set(surface_ids),
        }
    )
    return progress


def _carry_table(observation, progress, *, dirt=0):
    observation["inventory"] = {
        "oak_planks": 6,
        "stick": 4,
        "crafting_table": 1,
        **({"dirt": dirt} if dirt else {}),
    }
    observation["equipment"] = [None, None, None, None, None, None]
    observation["sp003_progress"] = base._progress_snapshot(progress)
    return observation


def test_phase116_stages_table_with_one_inventory_preserving_stone_probe(events):
    observation = _pre_guard_observation(
        events,
        lambda action: action.get("type") == "place",
    )
    progress = _staged_progress(observation)
    _carry_table(observation, progress)

    staging = _table_staging_state(observation, progress)
    target = staging["target"]
    assert staging["active"] is True
    assert staging["ready_for_table_placement"] is False
    assert staging["target_mode"] == "navigation"
    assert target["source_id"] == "stone:121:137:-33"
    assert target["stone_clearance_probe"] is True

    guard = guard_sp003_phase116_action(
        {"type": "move_to", "parameters": {"x": 121, "z": -33}},
        observation,
        progress,
    )
    assert guard["allowed"], guard
    assert guard["policy_id"] == SP003_TABLE_STAGING_POLICY_ID
    assert guard["action"]["parameters"] == {
        "x": 121.5,
        "z": -32.5,
        "tolerance": base.SP003_MOVE_TO_CONTINUOUS_TOLERANCE,
        "preserve_inventory": True,
    }
    assert guard["action_repair"]["attempt_limit"] == 1
    assert guard["action_repair"]["world_mutation"] is False


def test_phase116_rejects_early_table_placement_and_wrong_staging_move(events):
    observation = _pre_guard_observation(
        events,
        lambda action: action.get("type") == "place",
    )
    progress = _staged_progress(observation)
    _carry_table(observation, progress)

    early_place = guard_sp003_phase116_action(
        {
            "type": "place",
            "parameters": {
                "item": "crafting_table",
                "x": 119,
                "y": 140,
                "z": -34,
            },
        },
        observation,
        progress,
    )
    wrong_move = guard_sp003_phase116_action(
        {"type": "move_to", "parameters": {"x": 122, "z": -33}},
        observation,
        progress,
    )
    assert early_place["allowed"] is False
    assert "sp003_table_staging_navigation_required" in early_place["issues"]
    assert wrong_move["allowed"] is False
    assert "sp003_table_staging_navigation_target_mismatch" in wrong_move["issues"]


def test_phase116_binds_retained_machine_proven_clearance_before_tool_craft(events):
    observation = _pre_guard_observation(
        events,
        lambda action: action.get("parameters", {}).get("source_id")
        == "grass_block:124:142:-37",
    )
    progress = _staged_progress(observation)
    _carry_table(observation, progress)

    target = _table_staging_target(observation, progress)
    assert target["source_id"] == "grass_block:124:142:-37"
    assert target["support_source_id"] == "stone:124:139:-37"
    assert _table_staging_state(observation, progress)["target_mode"] == (
        "surface_clearance"
    )
    assert target["clearance_proof"]["obstruction_source_ids_top_down"] == [
        "grass_block:124:142:-37",
        "dirt:124:141:-37",
        "dirt:124:140:-37",
    ]

    guard = guard_sp003_phase116_action(
        {
            "type": "dig",
            "parameters": {
                "block": "grass_block",
                "x": 124,
                "y": 142,
                "z": -37,
            },
        },
        observation,
        progress,
    )
    assert guard["allowed"], guard
    params = guard["action"]["parameters"]
    assert params["stone_surface_clearance"] is True
    assert params["support_source_id"] == "stone:124:139:-37"
    assert params["surface_clearance_proof"] == target["clearance_proof"]
    assert params["surface_clearance_proof_fingerprint"] == (
        base.canonical_sha256(target["clearance_proof"])
    )


def test_phase116_clearance_guard_rejects_forgery_wrong_family_and_skill_context(events):
    observation = _pre_guard_observation(
        events,
        lambda action: action.get("parameters", {}).get("source_id")
        == "grass_block:124:142:-37",
    )
    progress = _staged_progress(observation)
    _carry_table(observation, progress)
    canonical = {
        "block": "grass_block",
        "x": 124,
        "y": 142,
        "z": -37,
    }

    forged = guard_sp003_phase116_action(
        {
            "type": "dig",
            "parameters": {**canonical, "surface_clearance_proof": {"forged": True}},
        },
        observation,
        progress,
    )
    wrong_family = guard_sp003_phase116_action(
        {
            "type": "dig",
            "parameters": {**canonical, "block": "stone"},
        },
        observation,
        progress,
    )
    skill_bound = guard_sp003_phase116_action(
        {
            "type": "dig",
            "parameters": canonical,
            "skill_context": {
                "skill_id": "learned:acquire_cobblestone",
                "version": "1.1.0",
            },
        },
        observation,
        progress,
        arm="candidate",
    )
    assert forged["allowed"] is False
    assert "sp003_table_staging_clearance_parameters_unexpected" in forged["issues"]
    assert wrong_family["allowed"] is False
    assert "sp003_table_staging_clearance_block_forbidden" in wrong_family["issues"]
    assert skill_bound["allowed"] is False
    assert "sp003_table_staging_skill_context_forbidden" in skill_bound["issues"]


def test_phase116_hand_clearance_reuses_existing_progress_and_machine_result(events):
    observation = _pre_guard_observation(
        events,
        lambda action: action.get("parameters", {}).get("source_id")
        == "grass_block:124:142:-37",
    )
    progress = _staged_progress(observation)
    _carry_table(observation, progress)
    guard = guard_sp003_phase116_action(
        {
            "type": "dig",
            "parameters": {
                "block": "grass_block",
                "x": 124,
                "y": 142,
                "z": -37,
            },
        },
        observation,
        progress,
    )
    retained = _action_event(events, "grass_block:124:142:-37")
    after = base.record_sp003_success(
        progress,
        guard["action"],
        retained["result"],
    )
    assert after["surface_clearance_source_ids"] == [
        "grass_block:124:142:-37"
    ]
    assert after["surface_clearance_removal_count"] == 1
    assert after["wooden_pickaxe_craft_count"] == 0
    assert after["crafting_table_place_count"] == 0


def test_phase116_continues_second_shaft_then_exposes_one_local_table_place(events):
    first_shaft_ids = {
        "grass_block:124:142:-37",
        "dirt:124:141:-37",
        "dirt:124:140:-37",
    }
    observation = _pre_guard_observation(
        events,
        lambda action: action.get("parameters", {}).get("source_id")
        == "dirt:124:141:-38",
    )
    progress = _staged_progress(observation, first_shaft_ids)
    _carry_table(observation, progress, dirt=3)
    second_shaft = _table_staging_state(observation, progress)
    assert second_shaft["target"]["source_id"] == "dirt:124:141:-38"
    assert second_shaft["target_mode"] == "surface_clearance"

    ready_observation = _pre_guard_observation(
        events,
        lambda action: action.get("parameters", {}).get("source_id")
        == "stone:124:139:-38",
    )
    all_clearance_ids = set(
        ready_observation["sp003_progress"]["surface_clearance_source_ids"]
    )
    ready_progress = _staged_progress(ready_observation, all_clearance_ids)
    _carry_table(ready_observation, ready_progress, dirt=5)
    ready = _table_staging_state(ready_observation, ready_progress)
    assert len(all_clearance_ids) == 5
    assert ready["ready_for_table_placement"] is True
    assert ready["pickup_access_source_id"] == "stone:124:139:-38"
    assert ready["target"] == {}

    reference = base._place_reference_candidates(ready_observation)[0]
    assert reference["source_id"] == "grass_block:123:141:-37"
    assert reference["target_position"] == {"x": 123, "y": 142, "z": -37}
    place_guard = guard_sp003_phase116_action(
        {
            "type": "place",
            "parameters": {
                "item": "crafting_table",
                **reference["position"],
            },
        },
        ready_observation,
        ready_progress,
    )
    assert place_guard["allowed"], place_guard
    assert place_guard["action"]["parameters"]["reference_source_id"] == (
        reference["source_id"]
    )


def test_phase116_local_table_is_visible_from_retained_terminal_pit_and_allows_craft(events):
    episode = json.loads((RUN_DIR / "episode.json").read_text(encoding="utf-8"))
    terminal = copy.deepcopy(episode["stable_observation"])
    table_position = {"x": 123, "y": 142, "z": -37}
    distance = math.sqrt(
        sum(
            (float(terminal["position"][axis]) - table_position[axis]) ** 2
            for axis in ("x", "y", "z")
        )
    )
    assert distance == pytest.approx(4.296874774664889)
    assert distance < 4.5
    terminal.setdefault("nearby_blocks", []).insert(
        0,
        {
            "name": "crafting_table",
            "position": table_position,
            "distance": distance,
        },
    )
    terminal["equipment"] = [
        {"slot": 0, "name": "wooden_pickaxe", "count": 1},
        None,
        None,
        None,
        None,
        None,
    ]
    progress = base._empty_progress()
    progress.update(
        {
            "log_source_ids": {"oak_log:1:1:1", "oak_log:1:2:1", "oak_log:1:3:1"},
            "log_item": "oak_log",
            "plank_craft_count": 1,
            "stick_craft_count": 1,
            "crafting_table_craft_count": 1,
            "crafting_table_place_count": 1,
            "crafting_table_position": table_position,
            "wooden_pickaxe_craft_count": 1,
            "wooden_pickaxe_equip_count": 1,
            "surface_clearance_source_ids": set(
                episode["distinct_surface_clearance_source_ids"]
            ),
            "stone_source_ids": set(episode["distinct_stone_source_ids"]),
        }
    )
    guard = guard_sp003_phase116_action(
        {
            "type": "craft",
            "parameters": {"item": "stone_pickaxe", "count": 1},
        },
        terminal,
        progress,
    )
    assert base._nearby_crafting_table_observed(terminal) is True
    assert guard["allowed"], guard


def test_phase116_planner_compacts_markers_and_runner_uses_overlay(events):
    observation = _pre_guard_observation(
        events,
        lambda action: action.get("type") == "place",
    )
    progress = _staged_progress(observation)
    _carry_table(observation, progress)
    observation["stone_pickaxe_runtime_mode"] = "sp003"
    observation["sp003_targets"] = [_table_staging_target(observation, progress)]
    compact = Planner._compact_stone_pickaxe_state(observation)
    assert compact["sp003_stage"] == "place_crafting_table"
    assert compact["sp003_targets"] == [
        {
            "source_id": "stone:121:137:-33",
            "name": "stone",
            "position": {"x": 121.0, "y": 137.0, "z": -33.0},
            "distance": 3.606,
            "horizontal_distance": 1.645,
            "navigation_only": True,
            "remaining_clearance_count": 0,
            "stone_clearance_probe": True,
            "vertical_delta": -3.0,
        }
    ]
    policy = json.loads(base.SP003_POLICY_PATH.read_text(encoding="utf-8"))
    allowed_target_fields = set(
        policy["episode_contract"]["planner_state_target_fields"]
    )
    assert set(compact["sp003_targets"][0]) <= allowed_target_fields
    prompt = Planner._stone_pickaxe_system_prompt(
        SimpleNamespace(_expected_plan_kind="continuation")
    )
    assert "During place_crafting_table" in prompt
    assert "stone_clearance_probe=true or stone_pickup_approach=true" in prompt
    assert "when the first target has stone_surface_clearance=true" in prompt
    runner = (
        REPO / "scripts/stone_pickaxe_sp003_episode_runner.py"
    ).read_text(encoding="utf-8")
    assert "StonePickaxeSP003Phase116RuntimeAgent(config, arm=args.arm)" in runner


def test_phase116_overlay_observation_replaces_premature_place_target(monkeypatch, events):
    observation = _pre_guard_observation(
        events,
        lambda action: action.get("type") == "place",
    )
    progress = _staged_progress(observation)
    _carry_table(observation, progress)
    monkeypatch.setattr(
        base.StonePickaxeSP003RuntimeAgent,
        "_observe",
        lambda _self: copy.deepcopy(observation),
    )
    agent = StonePickaxeSP003Phase116RuntimeAgent.__new__(
        StonePickaxeSP003Phase116RuntimeAgent
    )
    agent.sp003_progress = progress
    staged = agent._observe()
    assert staged["sp003_table_staging"]["active"] is True
    assert staged["sp003_table_staging"]["target_mode"] == "navigation"
    assert staged["sp003_targets"][0]["source_id"] == "stone:121:137:-33"


def test_phase116_repair_stays_within_original_action_and_mutation_bounds():
    expected = {
        "log_digs": 3,
        "crafts_before_table": 3,
        "table_staging_moves": 3,
        "surface_clearances": 5,
        "table_placements": 1,
        "wooden_pickaxe_crafts": 1,
        "wooden_pickaxe_equips": 1,
        "stone_digs": 3,
        "stone_pickaxe_crafts": 1,
    }
    assert sum(expected.values()) == 21
    assert expected["surface_clearances"] <= base.SP003_SURFACE_CLEARANCE_MAX
    assert expected["table_placements"] == 1
    assert expected["stone_digs"] == 3
    assert sum(expected.values()) <= 32


def test_phase116_audit_binds_implementation_and_protected_identities():
    audit = json.loads(
        (
            REPO
            / "workspace/evals/stone_pickaxe_sp003_local_table_staging_repair.json"
        ).read_text(encoding="utf-8")
    )
    assert audit["phase"] == 116
    assert audit["base_commit"] == (
        "14ce593e2e830ff1a6bece11e1e7abb63d013155"
    )
    assert audit["policy_id"] == SP003_TABLE_STAGING_POLICY_ID
    assert audit["status"] == "offline_verified"
    assert audit["retained_failure"]["manifest_sha256"] == (
        "77a95b8ec79da0182daf7d8d60d6d6527fb69ee4ac4ebdc9dd42e283af7d4005"
    )
    records = [
        *audit["implementation"],
        *audit["protected_phase_114_identities"],
        *audit["protected_runtime_identities"],
    ]
    for record in records:
        if record["path"].startswith("node_modules/"):
            assert hashlib.sha256((REPO / record["path"]).read_bytes()).hexdigest() == (
                record["sha256"]
            )
            continue
        historical = subprocess.check_output(
            ["git", "show", f"{PHASE116_FIX_COMMIT}:{record['path']}"],
            cwd=REPO,
        )
        assert hashlib.sha256(historical).hexdigest() == record["sha256"]
    assert audit["live_episode_run"] is False
    assert audit["live_authorization"] is False
    assert audit["automatic_retry_allowed"] is False
    assert audit["counts_toward_baseline_success"] is False
    assert audit["counts_toward_capability"] is False
    assert audit["counts_toward_m4"] is False
