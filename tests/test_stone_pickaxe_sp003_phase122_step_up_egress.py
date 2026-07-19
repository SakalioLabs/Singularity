from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from singularity.evaluation import stone_pickaxe_sp003_phase120_runtime as phase120
from singularity.evaluation import stone_pickaxe_sp003_phase122_runtime as phase122
from singularity.evaluation import stone_pickaxe_sp003_runtime as base


REPO = Path(__file__).resolve().parents[1]
PHASE122_BASE_COMMIT = "5bd4210fb0a17a053f80cea3b0f66621f2ad7f67"
PHASE122_FIX_COMMIT = "6d9d1b5b9fce021101fad69ab8af05f28508bfe1"
PHASE119_RUN_DIR = (
    REPO
    / "workspace/evals/sp003_runs/sp003_baseline_20260720_015550_a54561d9"
)
PHASE121_RUN_DIR = (
    REPO
    / "workspace/evals/sp003_runs/sp003_baseline_20260720_030918_15498d1d"
)


def _retained_observations(run_dir: Path) -> list[dict]:
    events = json.loads((run_dir / "session.json").read_text(encoding="utf-8"))
    return [event["data"] for event in events if event.get("type") == "observation"]


def _terminal_observation() -> dict:
    return copy.deepcopy(_retained_observations(PHASE121_RUN_DIR)[-1])


def _block(name: str, cell: tuple[int, int, int], origin: tuple[int, int, int]):
    return {
        "name": name,
        "position": {"x": cell[0], "y": cell[1], "z": cell[2]},
        "distance": math.sqrt(
            sum((cell[index] - origin[index]) ** 2 for index in range(3))
        ),
    }


def _rebuilt_observation(
    source: dict,
    *,
    position: tuple[float, float, float] | None = None,
    replace: tuple[str, tuple[int, int, int]] | None = None,
    add: tuple[str, tuple[int, int, int]] | None = None,
) -> dict:
    coordinates = position or tuple(source["position"][axis] for axis in ("x", "y", "z"))
    origin = tuple(math.floor(value) for value in coordinates)
    blocks = {
        tuple(item["position"][axis] for axis in ("x", "y", "z")): item["name"]
        for item in source["nearby_blocks"]
        if abs(item["position"]["x"] - origin[0]) <= 1
        and -3 <= item["position"]["y"] - origin[1] <= 3
        and abs(item["position"]["z"] - origin[2]) <= 1
    }
    if replace:
        name, cell = replace
        assert cell in blocks
        blocks[cell] = name
    if add:
        name, cell = add
        blocks[cell] = name
    records = [_block(name, cell, origin) for cell, name in blocks.items()]
    raw = {
        "position": {"x": coordinates[0], "y": coordinates[1], "z": coordinates[2]},
        "inventory": copy.deepcopy(source["inventory"]),
        "nearby_blocks": records,
        "ground_block": source.get("ground_block", "grass_block"),
    }
    scan = base._bounded_complete_local_scan(raw, records, raw)
    raw["sp003_complete_local_scan"] = scan
    raw["sp003_stone_approach_stands"] = base._stone_approach_stands(scan)
    raw["sp003_stone_pickup_accesses"] = base._stone_pickup_accesses(scan)
    raw["sp003_stone_surface_clearances"] = base._stone_surface_clearances(scan)
    return raw


def test_phase122_retained_terminal_selects_exact_step_up_egress():
    observation = _terminal_observation()
    progress = observation["sp003_progress"]

    parent = phase120._table_staging_state(observation, progress)
    assert parent["blocker"] == "locked_partial_shaft_machine_egress_unavailable"

    staging = phase122._table_staging_state(observation, progress)
    assert staging["blocked"] is False
    assert staging["target_mode"] == "locked_shaft_step_up_egress"
    target = staging["target"]
    assert target["position"] == {"x": 123.5, "y": 142, "z": -36.5}
    assert target["locked_support_source_id"] == "stone:124:139:-37"
    proof = target["shaft_step_up_egress_proof"]
    assert proof["remaining_obstruction_source_ids_top_down"] == [
        "dirt:124:140:-37"
    ]
    assert proof["current_feet_cell_state"] == "air"
    assert proof["current_head_cell_state"] == "air"
    assert proof["egress_ground_source_id"] == "grass_block:123:141:-37"
    assert proof["egress_feet_cell_state"] == "air"
    assert proof["egress_head_cell_state"] == "air"
    assert proof["egress_horizontal_manhattan_distance"] == 1
    assert proof["egress_vertical_delta"] == 1
    assert proof["inventory_preservation_required"] is True
    assert proof["attempt_limit"] == 1
    assert proof["world_mutation"] is False


@pytest.mark.parametrize(
    "parameters",
    [
        {"x": 123.5, "y": 142, "z": -36.5},
        {"x": 123.5, "z": -36.5},
    ],
)
def test_phase122_guard_binds_exact_step_up_without_mutation(parameters):
    observation = _terminal_observation()
    guard = phase122.guard_sp003_phase122_action(
        {"type": "move_to", "parameters": parameters},
        observation,
        observation["sp003_progress"],
    )

    assert guard["allowed"], guard
    assert guard["action"]["parameters"] == {
        "x": 123.5,
        "y": 142,
        "z": -36.5,
        "tolerance": 1.0,
        "preserve_inventory": True,
    }
    assert guard["action_repair"]["target_mode"] == (
        "locked_shaft_step_up_egress"
    )
    assert guard["action_repair"]["attempt_limit"] == 1
    assert guard["action_repair"]["world_mutation"] is False
    assert guard["parameter_normalization"]["planner_retry"] is False


def test_phase122_step_up_fails_closed_on_action_or_scan_tamper():
    observation = _terminal_observation()
    progress = observation["sp003_progress"]
    target = phase122._table_staging_state(observation, progress)["target"]
    cases = [
        (
            {
                "type": "move_to",
                "parameters": {"x": 123.5, "y": 141, "z": -36.5},
            },
            "sp003_partial_shaft_step_up_target_mismatch",
        ),
        (
            {
                "type": "move_to",
                "parameters": {
                    "x": 123.5,
                    "y": 142,
                    "z": -36.5,
                    "tolerance": 8,
                },
            },
            "sp003_partial_shaft_step_up_parameters_unexpected",
        ),
        (
            {
                "type": "move_to",
                "parameters": copy.deepcopy(target["position"]),
                "skill_context": {"skill_id": "learned:acquire_cobblestone"},
            },
            "sp003_partial_shaft_step_up_skill_context_forbidden",
        ),
    ]
    for action, expected_issue in cases:
        guard = phase122.guard_sp003_phase122_action(action, observation, progress)
        assert not guard["allowed"]
        assert expected_issue in guard["issues"]
        assert guard["action_repair"] == {}

    altered = []
    tampered = copy.deepcopy(observation)
    tampered["sp003_complete_local_scan"]["backend_sha256"] = "0" * 64
    altered.append(tampered)
    altered.append(
        _rebuilt_observation(
            observation,
            add=("dirt", (123, 143, -37)),
        )
    )
    altered.append(
        _rebuilt_observation(
            observation,
            replace=("oak_log", (123, 141, -37)),
        )
    )
    altered.append(
        _rebuilt_observation(
            observation,
            add=("dirt", (124, 142, -37)),
        )
    )
    for unsafe in altered:
        staging = phase122._table_staging_state(unsafe, progress)
        assert staging["blocked"] is True
        assert staging["target"] == {}
        assert staging["blocker"] == (
            "locked_partial_shaft_machine_egress_unavailable"
        )


def test_phase122_step_up_has_one_attempt_per_proof_fingerprint():
    observation = _terminal_observation()
    progress = observation["sp003_progress"]
    target = phase122._table_staging_state(observation, progress)["target"]
    fingerprint = target["shaft_step_up_egress_proof_fingerprint"]

    exhausted = phase122._table_staging_state(
        observation,
        progress,
        attempted_egress_fingerprints={fingerprint},
    )
    assert exhausted["blocked"] is True
    assert exhausted["target"] == {}
    assert "target_mode" not in exhausted
    assert exhausted["blocker"] == (
        "locked_partial_shaft_step_up_egress_attempt_exhausted"
    )

    guard = phase122.guard_sp003_phase122_action(
        {"type": "move_to", "parameters": copy.deepcopy(target["position"])},
        observation,
        progress,
        attempted_egress_fingerprints={fingerprint},
    )
    assert not guard["allowed"]
    assert "sp003_locked_partial_shaft_machine_target_required" in guard["issues"]


def test_phase122_preserves_phase120_same_level_egress_first():
    observation = next(
        item
        for item in _retained_observations(PHASE119_RUN_DIR)
        if item["sp003_progress"]["surface_clearance_removal_count"] == 1
        and item["sp003_complete_local_scan"]["origin_cell"]
        == {"x": 121, "y": 141, "z": -37}
    )
    progress = observation["sp003_progress"]
    expected = phase120._table_staging_state(observation, progress)
    staging = phase122._table_staging_state(observation, progress)
    assert staging == expected
    assert staging["policy_id"] == (
        phase120.SP003_PARTIAL_SHAFT_CONTINUATION_POLICY_ID
    )
    assert staging["target_mode"] == "locked_shaft_egress"

    guard = phase122.guard_sp003_phase122_action(
        {
            "type": "move_to",
            "parameters": copy.deepcopy(staging["target"]["position"]),
        },
        observation,
        progress,
    )
    assert guard["allowed"], guard
    assert guard["action_repair"]["target_mode"] == "locked_shaft_egress"
    assert guard["selected_source"]["shaft_egress_proof"]["policy_id"] == (
        phase120.SP003_PARTIAL_SHAFT_CONTINUATION_POLICY_ID
    )


def test_phase122_after_step_up_continues_the_same_locked_shaft():
    terminal = _terminal_observation()
    observation = _rebuilt_observation(
        terminal,
        position=(123.5, 142, -36.5),
    )
    progress = terminal["sp003_progress"]

    staging = phase122._table_staging_state(observation, progress)
    assert staging["target_mode"] == "locked_surface_clearance"
    assert staging["partial_shaft_lock"]["support_source_id"] == (
        "stone:124:139:-37"
    )
    assert staging["target"]["source_id"] == "dirt:124:140:-37"

    guard = phase122.guard_sp003_phase122_action(
        {
            "type": "dig",
            "parameters": {"block": "dirt", "x": 124, "y": 140, "z": -37},
        },
        observation,
        progress,
    )
    assert guard["allowed"], guard
    assert guard["action"]["parameters"]["stone_surface_clearance"] is True
    assert guard["action"]["parameters"]["support_source_id"] == (
        "stone:124:139:-37"
    )


def test_phase122_agent_consumes_step_up_attempt_once(monkeypatch):
    observation = _terminal_observation()
    progress = observation["sp003_progress"]
    target = phase122._table_staging_state(observation, progress)["target"]
    delegated = []

    def fake_verify(_self, action, _observation, _goal, _context=None):
        delegated.append(copy.deepcopy(action))
        return {"status": "accept"}, {"success": True}

    monkeypatch.setattr(base.Agent, "_verify_action_for_execution", fake_verify)
    agent = phase122.StonePickaxeSP003Phase122RuntimeAgent.__new__(
        phase122.StonePickaxeSP003Phase122RuntimeAgent
    )
    agent.sp003_progress = progress
    agent.sp003_arm = "baseline"
    agent._sp003_phase120_egress_attempted_fingerprints = set()
    agent.session_logger = SimpleNamespace(log=lambda *args, **kwargs: None)

    action = {"type": "move_to", "parameters": copy.deepcopy(target["position"])}
    verification, result = agent._verify_action_for_execution(
        action,
        observation,
        "SP-003",
        {"cycle": 13},
    )
    assert verification == {"status": "accept"}
    assert result == {"success": True}
    assert len(delegated) == 1
    assert agent._sp003_phase120_egress_attempted_fingerprints == {
        target["shaft_step_up_egress_proof_fingerprint"]
    }

    second = {"type": "move_to", "parameters": copy.deepcopy(target["position"])}
    verification, result = agent._verify_action_for_execution(
        second,
        observation,
        "SP-003",
        {"cycle": 14},
    )
    assert verification["status"] == "reject"
    assert result["verification_blocked"] is True
    assert len(delegated) == 1


def test_phase122_observe_exposes_step_up_target(monkeypatch):
    observation = _terminal_observation()
    monkeypatch.setattr(
        phase120.StonePickaxeSP003Phase120RuntimeAgent,
        "_observe",
        lambda _self: copy.deepcopy(observation),
    )
    agent = phase122.StonePickaxeSP003Phase122RuntimeAgent.__new__(
        phase122.StonePickaxeSP003Phase122RuntimeAgent
    )
    agent.sp003_progress = observation["sp003_progress"]
    agent._sp003_phase120_egress_attempted_fingerprints = set()

    enriched = agent._observe()
    assert enriched["sp003_table_staging"]["target_mode"] == (
        "locked_shaft_step_up_egress"
    )
    assert enriched["sp003_targets"] == [
        enriched["sp003_table_staging"]["target"]
    ]


def test_phase122_runner_is_process_local_and_launcher_uses_it():
    wrapper = (
        REPO / "scripts/stone_pickaxe_sp003_phase122_episode_runner.py"
    ).read_text(encoding="utf-8")
    launcher = (REPO / "scripts/stone-pickaxe-sp003-runtime.ps1").read_text(
        encoding="utf-8-sig"
    )
    assert "frozen_runner.StonePickaxeSP003Phase116RuntimeAgent" in wrapper
    assert "StonePickaxeSP003Phase122RuntimeAgent" in wrapper
    assert launcher.count("stone_pickaxe_sp003_phase122_episode_runner.py") == 2
    assert "stone_pickaxe_sp003_phase120_episode_runner.py" not in launcher

    for relative in [
        "scripts/stone_pickaxe_sp003_episode_runner.py",
        "scripts/stone_pickaxe_sp003_phase120_episode_runner.py",
    ]:
        current = (REPO / relative).read_bytes()
        historical = subprocess.check_output(
            ["git", "show", f"{PHASE122_BASE_COMMIT}:{relative}"],
            cwd=REPO,
        )
        assert current == historical


def test_phase122_audit_binds_repair_and_protected_identities():
    audit = json.loads(
        (
            REPO
            / "workspace/evals/stone_pickaxe_sp003_partial_clearance_shaft_step_up_repair.json"
        ).read_text(encoding="utf-8")
    )
    assert audit["phase"] == 122
    assert audit["base_commit"] == PHASE122_BASE_COMMIT
    assert audit["policy_id"] == phase122.SP003_PARTIAL_SHAFT_STEP_UP_POLICY_ID
    assert audit["status"] == "offline_verified"
    assert audit["retained_failure"]["manifest_sha256"] == (
        "f7f8cb5791c54ef7a6d500d0786592ebbea8392e0591e647643796d624ac6ce4"
    )
    for record in [
        *audit["implementation"],
        *audit["protected_phase_120_identities"],
        *audit["protected_runtime_identities"],
        *audit["retained_evidence_identities"],
    ]:
        if record["path"].startswith("node_modules/"):
            assert hashlib.sha256((REPO / record["path"]).read_bytes()).hexdigest() == (
                record["sha256"]
            )
            continue
        historical = subprocess.check_output(
            ["git", "show", f"{PHASE122_FIX_COMMIT}:{record['path']}"],
            cwd=REPO,
        )
        assert hashlib.sha256(historical).hexdigest() == record["sha256"]
    assert audit["live_episode_run"] is False
    assert audit["live_authorization"] is False
    assert audit["automatic_retry_allowed"] is False
    assert audit["counts_toward_baseline_success"] is False
    assert audit["counts_toward_skill_gate"] is False
    assert audit["counts_toward_capability"] is False
    assert audit["counts_toward_m4"] is False
