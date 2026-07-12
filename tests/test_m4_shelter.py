"""Offline G3 tests for the M4 machine-checkable shelter verifier."""

import copy
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from singularity.core.agent import Agent
from singularity.action.verifier import ActionVerifier
from singularity.core.goal_generator import GoalGenerator
from singularity.core.goal_verifier import GoalVerifier
from singularity.core.planner import Planner
from singularity.core.task_system import TaskSystem
from singularity.evaluation.m4_shelter import (
    M4_SHELTER_CONTRACT_SHA256,
    M4_SHELTER_REQUIRED_CHECKS,
    M4_SHELTER_VERIFIER_ID,
    M4ShelterVerifier,
    is_machine_verified_shelter,
)
from singularity.evaluation.m4_protocol import PROTOCOL, PROTOCOL_SHA256


CELL = {"x": 0, "y": 64, "z": 0}


def _lifecycle(death_count=0, respawn_count=0):
    return {
        "type": "m4_player_lifecycle",
        "schema_version": 1,
        "verifier_id": PROTOCOL["identities"]["player_lifecycle_verifier"],
        "source": "mineflayer_events",
        "profile": PROTOCOL["profile"],
        "protocol_sha256": PROTOCOL_SHA256,
        "tracker_id": "m4-shelter-fixture-tracker",
        "episode_id": "m4-shelter-fixture-episode",
        "level_name": "m4-shelter-fixture-episode_bm011",
        "baseline_id": "c" * 64,
        "baseline_established": True,
        "initial_spawn_observed": True,
        "baseline_death_count_total": 0,
        "baseline_respawn_count_total": 0,
        "baseline_spawn_count_total": 1,
        "baseline_observed_at_ms": 1700000000000,
        "baseline_bridge_monotonic_ms": 1000,
        "death_count_total": death_count,
        "respawn_count_total": respawn_count,
        "spawn_count_total": 1 + respawn_count,
        "death_count": death_count,
        "respawn_count": respawn_count,
        "spawn_count": respawn_count,
        "pending_respawn_count": death_count - respawn_count,
        "uninterrupted": death_count == 0 and respawn_count == 0,
        "last_death": None if not death_count else {
            "kind": "death",
            "event_sequence": 2,
            "observed_at_ms": 1700000001000,
            "bridge_monotonic_ms": 1100,
            "death_count_total": death_count,
        },
        "last_respawn": None if not respawn_count else {
            "kind": "respawn",
            "event_sequence": 3,
            "observed_at_ms": 1700000002000,
            "bridge_monotonic_ms": 1200,
            "respawn_count_total": respawn_count,
            "spawn_count_total": 1 + respawn_count,
        },
    }


def _key(position):
    return f"{position['x']},{position['y']},{position['z']}"


def _block(position, name="air"):
    solid = name != "air"
    return {
        "name": name,
        "type": 1 if solid else 0,
        "position": dict(position),
        "collision": "block" if solid else "empty",
        "solid": solid,
        "passable": not solid,
    }


def _structural_positions():
    positions = []
    for dx, dz in ((0, -1), (1, 0), (0, 1), (-1, 0)):
        positions.extend([
            {"x": CELL["x"] + dx, "y": CELL["y"], "z": CELL["z"] + dz},
            {"x": CELL["x"] + dx, "y": CELL["y"] + 1, "z": CELL["z"] + dz},
        ])
    positions.append({"x": CELL["x"], "y": CELL["y"] + 2, "z": CELL["z"]})
    return positions


def _snapshot(hostiles=None):
    blocks = {}
    for dx in range(-1, 2):
        for dy in range(-1, 3):
            for dz in range(-1, 2):
                position = {"x": CELL["x"] + dx, "y": CELL["y"] + dy, "z": CELL["z"] + dz}
                blocks[_key(position)] = _block(position)
    floor = {"x": CELL["x"], "y": CELL["y"] - 1, "z": CELL["z"]}
    blocks[_key(floor)] = _block(floor, "stone")
    for position in _structural_positions():
        blocks[_key(position)] = _block(position, "oak_planks")
    return {
        "success": True,
        "type": "m4_shelter_machine_snapshot",
        "schema_version": 1,
        "source": "mineflayer_world_state",
        "player_position": {"x": 0.5, "y": 64.0, "z": 0.5},
        "player_cell": dict(CELL),
        "blocks": list(blocks.values()),
        "nearby_hostiles": list(hostiles or []),
    }


def _delta(positions=None):
    positions = _structural_positions() if positions is None else positions
    return {
        "placed": {
            _key(position): {
                "operation": "place",
                "action_type": "place",
                "success": True,
                "position": dict(position),
                "before": {"name": "air"},
                "after": {"name": "oak_planks"},
            }
            for position in positions
        },
        "removed": {},
    }


def _replace_block(snapshot, position, name):
    for index, block in enumerate(snapshot["blocks"]):
        if block["position"] == position:
            snapshot["blocks"][index] = _block(position, name)
            return
    raise AssertionError(f"fixture position missing: {position}")


def test_g3_sealed_cell_requires_complete_machine_geometry_and_delta():
    report = M4ShelterVerifier().verify(_snapshot(), _delta())

    assert report["passed"] is True
    assert report["safe_state"] is True
    assert report["episode_block_delta"]["matched_position_count"] == 9
    assert report["coordinate_evidence"]["entrance"]["state"] == "fully_sealed"
    assert len(report["coordinate_evidence"]["entrance"]["sealed_boundary_columns"]) == 4
    assert all(check["passed"] for check in report["checks"])
    assert is_machine_verified_shelter(report)
    print("PASS: G3 accepts only the complete nine-block sealed-cell shelter baseline")


def test_g3_rejects_missing_wall_or_overhead_cover():
    wall_gap = _snapshot()
    _replace_block(wall_gap, {"x": 1, "y": 64, "z": 0}, "air")
    wall_report = M4ShelterVerifier().verify(wall_gap, _delta())
    assert wall_report["passed"] is False
    assert "physical_barriers" in wall_report["issues"]
    assert "hostile_path_risk" in wall_report["issues"]

    open_roof = _snapshot()
    _replace_block(open_roof, {"x": 0, "y": 66, "z": 0}, "air")
    roof_report = M4ShelterVerifier().verify(open_roof, _delta())
    assert roof_report["passed"] is False
    assert "overhead_cover_or_approved_alternative" in roof_report["issues"]
    assert "hostile_path_risk" in roof_report["issues"]
    print("PASS: G3 rejects wall apertures and missing overhead cover")


def test_g3_rejects_nonstandable_interior_and_hostile_inside():
    no_floor = _snapshot()
    _replace_block(no_floor, {"x": 0, "y": 63, "z": 0}, "air")
    floor_report = M4ShelterVerifier().verify(no_floor, _delta())
    assert "standable_interior" in floor_report["issues"]

    flooded = _snapshot()
    water = {"x": 0, "y": 64, "z": 0}
    _replace_block(flooded, water, "air")
    for index, block in enumerate(flooded["blocks"]):
        if block["position"] == water:
            flooded["blocks"][index] = dict(_block(water), name="water", type=9)
            break
    flooded_report = M4ShelterVerifier().verify(flooded, _delta())
    assert "standable_interior" in flooded_report["issues"]

    hostile = {
        "name": "zombie",
        "position": {"x": 0.7, "y": 64.0, "z": 0.4},
        "cell": dict(CELL),
        "distance": 0.3,
    }
    hostile_report = M4ShelterVerifier().verify(_snapshot([hostile]), _delta())
    assert hostile_report["passed"] is False
    assert "hostile_path_risk" in hostile_report["issues"]
    assert hostile_report["hostile_path_risk"]["hostiles_inside"][0]["name"] == "zombie"
    print("PASS: G3 requires a standable interior and proves no hostile is inside it")


def test_g3_requires_the_complete_bounded_snapshot():
    incomplete = _snapshot()
    incomplete["blocks"].pop()
    report = M4ShelterVerifier().verify(incomplete, _delta())

    assert report["passed"] is False
    assert "machine_snapshot" in report["issues"]
    machine = next(check for check in report["checks"] if check["name"] == "machine_snapshot")
    assert machine["evidence"]["expected_snapshot_position_count"] == 36
    assert machine["evidence"]["observed_snapshot_position_count"] == 35
    print("PASS: G3 rejects truncated snapshots even when all central claims look plausible")


def test_g3_requires_current_episode_provenance_for_every_structure_block():
    positions = _structural_positions()
    report = M4ShelterVerifier().verify(_snapshot(), _delta(positions[:-1]))

    assert report["passed"] is False
    assert "episode_block_delta_or_approved_natural_safe_point" in report["issues"]
    assert report["episode_block_delta"]["matched_position_count"] == 8
    assert report["natural_safe_point"]["allowed"] is False
    print("PASS: G3 rejects pre-existing or partially attributed structures")


def test_g3_rejects_text_flags_and_spoofed_machine_claims():
    spoof = {
        "passed": True,
        "safe_state": True,
        "source": "machine_state",
    }
    assert is_machine_verified_shelter(spoof) is False

    verifier = GoalVerifier()
    legacy = verifier.verify(
        "Build verified shelter before nightfall",
        {
            "flags": ["in_shelter", "shelter_built"],
            "structures": {"shelter": {"complete": True}},
            "placed_blocks": list(range(12)),
            "shelter_verification": spoof,
        },
        recent_actions=[{"action": {"type": "place"}, "result": {"success": True}}],
    )
    assert legacy.achieved is False
    assert legacy.matched_rules == ["world:m4_machine_shelter"]

    report = M4ShelterVerifier().verify(_snapshot(), _delta())
    verified = verifier.verify("Build verified shelter before nightfall", {"shelter_verification": report})
    assert verified.achieved is True
    assert verified.confidence == 1.0
    print("PASS: GoalVerifier ignores text claims and accepts only the pinned machine report")


def test_g3_goal_generator_requires_pinned_complete_report():
    generator = GoalGenerator()
    base = {
        "time_of_day": 15000,
        "health": 20,
        "hunger": 20,
        "inventory": {},
        "nearby_entities": [],
    }
    spoofed = dict(base, shelter_verification={"passed": True, "source": "machine_state"})
    assert "emergency verified shelter" in generator.next_goal(spoofed).lower()

    report = M4ShelterVerifier().verify(_snapshot(), _delta())
    verified = dict(base, shelter_verification=report)
    assert "remain in verified shelter" in generator.next_goal(verified).lower()
    print("PASS: GoalGenerator changes night priority only for a complete pinned G3 report")


class _Observer:
    def observe(self):
        return {
            "position": {"x": 0.5, "y": 64.0, "z": 0.5},
            "time_of_day": 15000,
            "inventory": {},
            "player_lifecycle": _lifecycle(),
        }


class _Bot:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.calls = 0

    def get_shelter_state(self):
        self.calls += 1
        return copy.deepcopy(self.snapshot)

    def get_player_lifecycle(self):
        return _lifecycle()


class _SessionLogger:
    def __init__(self):
        self.events = []

    def log(self, event_type, data, level="INFO"):
        self.events.append({"type": event_type, "data": data, "level": level})


def test_g3_agent_tracks_place_delta_and_attaches_transition_evidence():
    agent = object.__new__(Agent)
    agent.config = SimpleNamespace(planner_protocol="m4-fixed-v1", enable_vision_analysis=False)
    agent.observer = _Observer()
    agent.bot = _Bot(_snapshot())
    agent.session_logger = _SessionLogger()
    agent.m4_shelter_verifier = M4ShelterVerifier()
    agent._m4_episode_block_delta = {"placed": {}, "removed": {}}
    agent._m4_shelter_verification_fingerprint = ""

    for position in _structural_positions():
        result = {
            "success": True,
            "target_block_before": {"name": "air", "position": position},
            "target_block_after": {"name": "oak_planks", "position": position},
        }
        agent._record_m4_episode_block_delta(
            {"type": "place", "parameters": {"item": "oak_planks"}},
            result,
        )

    first = agent._observe()
    second = agent._observe()
    assert first["shelter_verification"]["passed"] is True
    assert second["shelter_verification"]["passed"] is True
    assert len(agent._m4_episode_block_delta["placed"]) == 9
    assert agent.bot.calls == 2
    assert [event["type"] for event in agent.session_logger.events] == [
        "m4_player_lifecycle",
        "shelter_state_verification",
    ]
    print("PASS: Agent binds verified place results to bounded machine-state transition evidence")


def test_g0_agent_logs_lifecycle_baseline_and_death_transition_once():
    agent = object.__new__(Agent)
    agent.config = SimpleNamespace(planner_protocol="m4-fixed-v1")
    agent.session_logger = _SessionLogger()

    baseline = {"player_lifecycle": _lifecycle()}
    died = {"player_lifecycle": _lifecycle(death_count=1, respawn_count=1)}
    agent._record_m4_player_lifecycle(baseline)
    agent._record_m4_player_lifecycle(baseline)
    agent._record_m4_player_lifecycle(died)
    agent._record_m4_player_lifecycle(died)
    replaced = copy.deepcopy(baseline)
    replaced["player_lifecycle"]["baseline_id"] = "d" * 64
    agent._record_m4_player_lifecycle(replaced)

    events = [event for event in agent.session_logger.events if event["type"] == "m4_player_lifecycle"]
    assert len(events) == 3
    assert events[0]["data"]["death_count"] == 0
    assert events[0]["data"]["validation_passed"] is True
    assert events[1]["data"]["death_count"] == 1
    assert events[1]["data"]["respawn_count"] == 1
    assert events[1]["data"]["uninterrupted"] is False
    assert events[1]["data"]["validation_passed"] is True
    assert events[2]["data"]["validation_passed"] is False
    assert "baseline_identity_changed" in events[2]["data"]["validation_issues"]
    print("PASS: Agent emits one canonical lifecycle event per baseline or death-count transition")


def test_g5_partial_shelter_failure_relocates_before_template_retry():
    agent = object.__new__(Agent)
    agent.config = SimpleNamespace(planner_protocol="m4-fixed-v1")
    agent.session_logger = _SessionLogger()
    agent._m4_shelter_relocation = {}
    build_action = {
        "type": "build_shelter_cell",
        "parameters": {"origin": dict(CELL), "material": "oak_planks"},
    }
    failed_result = {
        "success": False,
        "template_id": "m4-sealed-cell-v1",
        "material": "oak_planks",
        "origin": dict(CELL),
        "error": "no grounded neighbor exists for sealed-cell placement",
        "atomicity": {
            "passed": True,
            "mode": "mutation_free_preflight_rejection",
            "mutation_count": 0,
            "inventory_preserved": True,
        },
        "relocation_required": True,
        "relocation_origin": {"x": 3, "y": 64, "z": 0},
        "relocation_target": {"x": 3.5, "y": 64.0, "z": 0.5},
        "relocation_search_radius": 6,
    }

    invalid_result = dict(failed_result)
    invalid_result["relocation_target"] = {"x": 30.5, "y": 64.0, "z": 0.5}
    agent._update_m4_shelter_relocation(build_action, invalid_result)
    assert agent._m4_shelter_relocation == {}
    invalid_result = dict(failed_result)
    invalid_result["relocation_search_radius"] = 6.5
    agent._update_m4_shelter_relocation(build_action, invalid_result)
    assert agent._m4_shelter_relocation == {}

    agent._update_m4_shelter_relocation(build_action, failed_result)
    relocation = dict(agent._m4_shelter_relocation)
    assert relocation["status"] == "scheduled"
    assert relocation["source_origin"] == CELL
    assert relocation["target_origin"] == {"x": 3, "y": 64, "z": 0}
    assert relocation["target_position"] == {"x": 3.5, "y": 64.0, "z": 0.5}
    assert relocation["search_radius"] == 6

    snapshot = _snapshot()
    _replace_block(snapshot, {"x": 0, "y": 66, "z": 0}, "air")
    shelter = M4ShelterVerifier().verify(snapshot, {"placed": {}})
    plan, grounding = Planner._ground_m4_shelter_phase(
        {"status": "planning", "subtasks": [], "actions": []},
        goal="Build verified shelter before nightfall",
        world_state={
            "inventory": {"oak_planks": 16},
            "shelter_verification": shelter,
            "m4_shelter_relocation": relocation,
        },
    )
    move = {
        "type": "move_to",
        "parameters": {"x": 3.5, "y": 64.0, "z": 0.5},
    }
    assert plan["actions"] == [move]
    assert grounding["activated"] is True
    assert grounding["reason"] == "partial_failure_relocation_required"
    assert grounding["recovery_id"] == relocation["recovery_id"]

    agent._update_m4_shelter_relocation(move, {"success": False, "error": "blocked"})
    assert agent._m4_shelter_relocation == relocation
    agent._update_m4_shelter_relocation(move, {"success": True})
    assert agent._m4_shelter_relocation == {}
    recovery_events = [
        event["data"] for event in agent.session_logger.events
        if event["type"] == "m4_shelter_atomicity_recovery"
    ]
    assert [event["status"] for event in recovery_events] == [
        "scheduled",
        "retry_required",
        "completed",
    ]
    print("PASS: Probe 16 partial shelter failure relocates before a bounded template retry")


def test_g3_report_contract_rejects_missing_required_check():
    report = M4ShelterVerifier().verify(_snapshot(), _delta())
    report["checks"] = [
        check for check in report["checks"]
        if check["name"] != M4_SHELTER_REQUIRED_CHECKS[-1]
    ]
    assert report["contract_sha256"] == M4_SHELTER_CONTRACT_SHA256
    assert report["verifier_id"] == M4_SHELTER_VERIFIER_ID
    assert is_machine_verified_shelter(report) is False
    print("PASS: report acceptance requires every pinned G3 check")


def test_g3_planner_receives_compact_machine_state_without_coordinate_bloat():
    report = M4ShelterVerifier().verify(_snapshot(), _delta())
    planner = Planner(llm=None, task_system=TaskSystem(), protocol="m4-fixed-v1")
    planner._expected_plan_kind = "continuation"
    prompt = planner._build_planning_prompt(
        "Remain in verified shelter until dawn",
        {"inventory": {}, "shelter_verification": report},
        "",
    )

    assert "Current shelter machine state" in prompt
    assert M4_SHELTER_VERIFIER_ID in prompt
    assert '"passed": true' in prompt
    assert '"matched_position_count": 9' in prompt
    assert "sealed_boundary_columns" not in prompt
    print("PASS: Planner receives the verifier decision without duplicating coordinate evidence")


def test_g5_shelter_phase_grounding_executes_bounded_template_when_material_ready():
    snapshot = _snapshot()
    _replace_block(snapshot, {"x": 0, "y": 66, "z": 0}, "air")
    report = M4ShelterVerifier().verify(snapshot, {"placed": {}})
    plan, grounding = Planner._ground_m4_shelter_phase(
        {
            "status": "planning",
            "reasoning": "gather unrelated resources",
            "subtasks": [],
            "actions": [{"type": "dig", "parameters": {"x": 4, "y": 64, "z": 4}}],
        },
        goal="Build verified shelter before nightfall",
        world_state={
            "inventory": {"oak_planks": 16},
            "shelter_verification": report,
        },
    )

    expected = {
        "type": "build_shelter_cell",
        "parameters": {
            "origin": {"x": 0, "y": 64, "z": 0},
            "material": "oak_planks",
        },
    }
    assert grounding["activated"] is True
    assert grounding["reason"] == "shelter_goal_and_material_ready"
    assert plan["actions"] == [expected]
    decision = ActionVerifier().verify(
        expected,
        {"inventory": {"oak_planks": 16}, "shelter_verification": report},
        goal="Build verified shelter before nightfall",
    )
    assert decision.status == "accept"


def test_g5_shelter_phase_grounding_requires_goal_snapshot_and_ten_inventory_blocks():
    snapshot = _snapshot()
    _replace_block(snapshot, {"x": 0, "y": 66, "z": 0}, "air")
    report = M4ShelterVerifier().verify(snapshot, {"placed": {}})
    base = {"status": "planning", "subtasks": [], "actions": [{"type": "wait", "parameters": {"ms": 1}}]}

    unrelated, unrelated_report = Planner._ground_m4_shelter_phase(
        base,
        goal="Gather oak logs",
        world_state={"inventory": {"oak_planks": 16}, "shelter_verification": report},
    )
    insufficient, insufficient_report = Planner._ground_m4_shelter_phase(
        base,
        goal="Build verified shelter before nightfall",
        world_state={"inventory": {"oak_planks": 8}, "shelter_verification": report},
    )

    assert unrelated["actions"] == base["actions"]
    assert unrelated_report["reason"] == "goal_is_not_shelter"
    assert insufficient["actions"] == base["actions"]
    assert insufficient_report["reason"] == "building_material_below_10"


def test_g5_agent_records_bounded_shelter_action_as_nine_placement_deltas():
    agent = object.__new__(Agent)
    agent.config = SimpleNamespace(planner_protocol="m4-fixed-v1", enable_vision_analysis=False)
    agent.observer = _Observer()
    agent.bot = _Bot(_snapshot())
    agent.session_logger = _SessionLogger()
    agent.m4_shelter_verifier = M4ShelterVerifier()
    agent._m4_episode_block_delta = {"placed": {}, "removed": {}}
    agent._m4_shelter_verification_fingerprint = ""

    positions = _structural_positions()
    agent._record_m4_episode_block_delta(
        {
            "type": "build_shelter_cell",
            "parameters": {"origin": CELL, "material": "oak_planks"},
        },
        {
            "success": True,
            "material": "oak_planks",
            "placed_positions": positions,
        },
    )

    observation = agent._observe()
    assert len(agent._m4_episode_block_delta["placed"]) == 9
    assert observation["shelter_verification"]["passed"] is True
    assert observation["shelter_verification"]["episode_block_delta"]["matched_position_count"] == 9


def test_g5_verified_shelter_maintenance_waits_for_named_time_boundary():
    report = M4ShelterVerifier().verify(_snapshot(), _delta())
    verifier = GoalVerifier()

    dusk = verifier.verify(
        "Enter and maintain verified shelter through nightfall",
        {"time_of_day": 11226, "shelter_verification": report},
    )
    night = verifier.verify(
        "Enter and maintain verified shelter through nightfall",
        {"time_of_day": 12000, "shelter_verification": report},
    )
    before_dawn = verifier.verify(
        "Remain in verified shelter until dawn",
        {"time_of_day": 13800, "shelter_verification": report},
    )
    dawn = verifier.verify(
        "Remain in verified shelter until dawn",
        {"time_of_day": 23000, "shelter_verification": report},
    )

    assert dusk.achieved is False
    assert dusk.missing == ["nightfall boundary not yet observed"]
    assert night.achieved is True
    assert before_dawn.achieved is False
    assert before_dawn.missing == ["dawn boundary not yet observed"]
    assert dawn.achieved is True


def test_g5_terminal_survival_verification_requires_machine_dawn_state():
    report = M4ShelterVerifier().verify(_snapshot(), _delta())
    agent = object.__new__(Agent)
    agent.config = SimpleNamespace(planner_protocol="m4-fixed-v1")
    agent.bot = SimpleNamespace(_connected=True)
    agent._m4_player_lifecycle_identity = agent._m4_lifecycle_identity(_lifecycle())
    dawn_state = {
        "time_of_day": 23000,
        "health": 18,
        "hunger": 17,
        "shelter_verification": report,
        "player_lifecycle": _lifecycle(),
    }

    verification = agent._m4_terminal_survival_verification(
        "Remain in verified shelter until dawn",
        dawn_state,
    )

    assert verification["passed"] is True
    assert verification["source"] == "machine_state"
    assert verification["time_of_day"] == 23000
    assert verification["health"] == 18
    assert verification["food"] == 17
    assert verification["bot_connected"] is True
    assert verification["uninterrupted_survival"] is True
    assert verification["player_lifecycle"]["death_count"] == 0
    assert verification["shelter_verifier_id"] == M4_SHELTER_VERIFIER_ID
    assert verification["shelter_contract_sha256"] == M4_SHELTER_CONTRACT_SHA256

    assert agent._m4_terminal_survival_verification(
        "Remain in verified shelter until dawn",
        dict(dawn_state, time_of_day=13943),
    ) == {}
    agent.bot._connected = True
    dead_state = dict(
        dawn_state,
        health=20,
        player_lifecycle=_lifecycle(death_count=1, respawn_count=1),
    )
    assert agent._m4_terminal_survival_verification(
        "Remain in verified shelter until dawn",
        dead_state,
    ) == {}
    replaced_baseline = copy.deepcopy(dawn_state)
    replaced_baseline["player_lifecycle"]["baseline_id"] = "d" * 64
    assert agent._m4_terminal_survival_verification(
        "Remain in verified shelter until dawn",
        replaced_baseline,
    ) == {}
    print("PASS: terminal survival cannot be restored by health 20 after death and respawn")
    assert agent._m4_terminal_survival_verification(
        "Remain in verified shelter until dawn",
        dict(dawn_state, time_of_day=float("inf")),
    ) == {}
    assert agent._m4_terminal_survival_verification(
        "Remain in verified shelter until dawn",
        dict(dawn_state, health=float("inf")),
    ) == {}
    agent.bot._connected = False
    assert agent._m4_terminal_survival_verification(
        "Remain in verified shelter until dawn",
        dawn_state,
    ) == {}
    agent.bot._connected = True
    assert agent._m4_terminal_survival_verification(
        "Remain in verified shelter until dawn",
        dict(dawn_state, shelter_verification={"passed": True, "source": "machine_state"}),
    ) == {}


def test_g5_maintenance_phase_grounding_keeps_one_root_active_with_bounded_waits():
    report = M4ShelterVerifier().verify(_snapshot(), _delta())
    base = {"status": "complete", "reasoning": "already safe", "subtasks": [], "actions": []}

    waiting, waiting_report = Planner._ground_m4_maintenance_phase(
        base,
        goal="Enter and maintain verified shelter through nightfall",
        world_state={"time_of_day": 11226, "shelter_verification": report},
    )
    reached, reached_report = Planner._ground_m4_maintenance_phase(
        base,
        goal="Enter and maintain verified shelter through nightfall",
        world_state={"time_of_day": 12000, "shelter_verification": report},
    )

    assert waiting["status"] == "planning"
    assert waiting["actions"] == [{"type": "wait", "parameters": {"ms": 15000}}]
    assert waiting_report["activated"] is True
    assert waiting_report["boundary"] == "nightfall"
    assert waiting_report["boundary_reached"] is False
    assert ActionVerifier().verify(waiting["actions"][0], {}, goal="maintain shelter").status == "accept"
    assert reached == base
    assert reached_report["activated"] is False
    assert reached_report["boundary_reached"] is True


if __name__ == "__main__":
    test_g3_sealed_cell_requires_complete_machine_geometry_and_delta()
    test_g3_rejects_missing_wall_or_overhead_cover()
    test_g3_rejects_nonstandable_interior_and_hostile_inside()
    test_g3_requires_the_complete_bounded_snapshot()
    test_g3_requires_current_episode_provenance_for_every_structure_block()
    test_g3_rejects_text_flags_and_spoofed_machine_claims()
    test_g3_goal_generator_requires_pinned_complete_report()
    test_g3_agent_tracks_place_delta_and_attaches_transition_evidence()
    test_g3_report_contract_rejects_missing_required_check()
    test_g3_planner_receives_compact_machine_state_without_coordinate_bloat()
    test_g5_terminal_survival_verification_requires_machine_dawn_state()
    print("\nM4 G3 shelter-verifier tests PASSED")
