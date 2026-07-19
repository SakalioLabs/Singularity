import copy
import hashlib
import json
import math
from pathlib import Path
import subprocess
from types import SimpleNamespace

from singularity.evaluation import stone_pickaxe_sp003_phase116_runtime as phase116
from singularity.evaluation import stone_pickaxe_sp003_phase120_runtime as phase120
from singularity.evaluation import stone_pickaxe_sp003_runtime as base


REPO = Path(__file__).resolve().parents[1]
PHASE120_FIX_COMMIT = "360aa2d8d9de966b49f9140b048c3b016929db34"
RUN_DIR = (
    REPO
    / "workspace/evals/sp003_runs/sp003_baseline_20260720_015550_a54561d9"
)


def _retained_observations():
    events = json.loads((RUN_DIR / "session.json").read_text(encoding="utf-8"))
    return [event["data"] for event in events if event.get("type") == "observation"]


def _block(name, cell, origin):
    return {
        "name": name,
        "position": {"x": cell[0], "y": cell[1], "z": cell[2]},
        "distance": math.sqrt(
            sum((cell[index] - origin[index]) ** 2 for index in range(3))
        ),
    }


def _progress(clearances):
    progress = base._empty_progress()
    progress["log_source_ids"] = {
        "dark_oak_log:118:141:-38",
        "dark_oak_log:119:141:-38",
        "dark_oak_log:119:142:-38",
    }
    progress["log_item"] = "dark_oak_log"
    progress["plank_craft_count"] = 1
    progress["stick_craft_count"] = 1
    progress["crafting_table_craft_count"] = 1
    for name, cell, support in clearances:
        source = base.source_id(
            name,
            {"x": cell[0], "y": cell[1], "z": cell[2]},
        )
        support_id = base.source_id(
            "stone",
            {"x": support[0], "y": support[1], "z": support[2]},
        )
        progress["surface_clearance_source_ids"].add(source)
        progress["successful_mutations"].append(
            {
                "type": "dig",
                "item": "",
                "block": name,
                "source_id": source,
                "support_source_id": support_id,
                "proof_fingerprint": base.canonical_sha256(
                    {
                        "source_id": source,
                        "support_source_id": support_id,
                    }
                ),
            }
        )
    return progress


def _observation(position, blocks):
    origin = tuple(math.floor(position[axis]) for axis in range(3))
    records = [_block(name, cell, origin) for name, cell in blocks]
    raw = {
        "position": {"x": position[0], "y": position[1], "z": position[2]},
        "inventory": {
            "dark_oak_planks": 6,
            "stick": 4,
            "crafting_table": 1,
        },
        "nearby_blocks": copy.deepcopy(records),
        "ground_block": "grass_block",
    }
    scan = base._bounded_complete_local_scan(raw, records, raw)
    raw["sp003_complete_local_scan"] = scan
    raw["sp003_stone_approach_stands"] = base._stone_approach_stands(scan)
    raw["sp003_stone_pickup_accesses"] = base._stone_pickup_accesses(scan)
    raw["sp003_stone_surface_clearances"] = base._stone_surface_clearances(scan)
    return raw


def test_phase120_retained_first_displacement_selects_one_proven_egress():
    observation = next(
        item
        for item in _retained_observations()
        if item["sp003_progress"]["surface_clearance_removal_count"] == 1
        and item["sp003_complete_local_scan"]["origin_cell"]
        == {"x": 121, "y": 141, "z": -37}
    )
    progress = observation["sp003_progress"]

    parent = phase116._table_staging_state(observation, progress)
    assert parent["target"]["support_source_id"] == "stone:122:138:-36"

    staging = phase120._table_staging_state(observation, progress)
    assert staging["target_mode"] == "locked_shaft_egress"
    assert staging["partial_shaft_lock"]["support_source_id"] == (
        "stone:121:138:-37"
    )
    target = staging["target"]
    assert target["position"] == {"x": 120.5, "y": 141, "z": -36.5}
    assert target["stone_clearance_shaft_egress"] is True
    proof = target["shaft_egress_proof"]
    assert proof["scan_complete"] is True
    assert proof["player_in_locked_support_column"] is True
    assert proof["remaining_obstruction_source_ids_top_down"] == [
        "dirt:121:140:-37",
        "dirt:121:139:-37",
    ]
    assert proof["egress_ground_source_id"] == "grass_block:120:140:-37"
    assert proof["egress_feet_cell_state"] == "air"
    assert proof["egress_head_cell_state"] == "air"
    assert proof["world_mutation"] is False

    action = {
        "type": "move_to",
        "parameters": {"x": 120.5, "y": 141, "z": -36.5},
    }
    guard = phase120.guard_sp003_phase120_action(action, observation, progress)
    assert guard["allowed"], guard
    assert guard["action"]["parameters"] == {
        "x": 120.5,
        "y": 141,
        "z": -36.5,
        "tolerance": 1.0,
        "preserve_inventory": True,
    }
    assert guard["action_repair"]["target_mode"] == "locked_shaft_egress"
    assert guard["action_repair"]["world_mutation"] is False

    attempted = {target["shaft_egress_proof_fingerprint"]}
    exhausted = phase120._table_staging_state(
        observation,
        progress,
        attempted_egress_fingerprints=attempted,
    )
    assert exhausted["blocked"] is True
    assert exhausted["target"] == {}
    assert exhausted["blocker"] == "locked_partial_shaft_egress_attempt_exhausted"


def test_phase120_same_shaft_reaches_access_in_three_clearances():
    support = (1, 0, 0)
    top = (1, 3, 0)
    middle = (1, 2, 0)
    bottom = (1, 1, 0)
    progress = _progress([("grass_block", top, support)])

    after_egress = _observation(
        (0.5, 3, 0.5),
        [
            ("grass_block", (0, 2, 0)),
            ("stone", support),
            ("dirt", middle),
            ("dirt", bottom),
        ],
    )
    first = phase120._table_staging_state(after_egress, progress)
    assert first["target_mode"] == "locked_surface_clearance"
    assert first["target"]["source_id"] == "dirt:1:2:0"
    assert first["target"]["support_source_id"] == "stone:1:0:0"

    first_guard = phase120.guard_sp003_phase120_action(
        {"type": "dig", "parameters": {"block": "dirt", "x": 1, "y": 2, "z": 0}},
        after_egress,
        progress,
    )
    assert first_guard["allowed"], first_guard
    assert first_guard["action"]["parameters"]["stone_surface_clearance"] is True

    progress = _progress(
        [
            ("grass_block", top, support),
            ("dirt", middle, support),
        ]
    )
    second_observation = _observation(
        (0.5, 3, 0.5),
        [
            ("grass_block", (0, 2, 0)),
            ("stone", support),
            ("dirt", bottom),
        ],
    )
    second = phase120._table_staging_state(second_observation, progress)
    assert second["target_mode"] == "locked_surface_clearance"
    assert second["target"]["source_id"] == "dirt:1:1:0"

    progress = _progress(
        [
            ("grass_block", top, support),
            ("dirt", middle, support),
            ("dirt", bottom, support),
        ]
    )
    clear_observation = _observation(
        (0.5, 3, 0.5),
        [("grass_block", (0, 2, 0)), ("stone", support)],
    )
    approach = phase120._table_staging_state(clear_observation, progress)
    assert approach["target_mode"] == "locked_navigation"
    assert approach["target"]["source_id"] == "stone:1:0:0"
    assert approach["target"]["stone_pickup_approach"] is True

    access_observation = _observation(
        (1.5, 1, 0.5),
        [
            ("stone", support),
            ("stone", (1, -1, 0)),
            ("stone", (0, 0, 0)),
        ],
    )
    access = phase120._table_staging_state(access_observation, progress)
    assert access["ready_for_table_placement"] is True
    assert access["pickup_access_source_id"] == "stone:1:0:0"
    assert access["target"] == {}
    assert base._progress_snapshot(progress)["surface_clearance_removal_count"] == 3


def test_phase120_reentry_after_second_clearance_gets_one_fresh_egress():
    support = (1, 0, 0)
    progress = _progress(
        [
            ("grass_block", (1, 3, 0), support),
            ("dirt", (1, 2, 0), support),
        ]
    )
    observation = _observation(
        (1.5, 3, 0.5),
        [
            ("grass_block", (0, 2, 0)),
            ("stone", support),
            ("dirt", (1, 1, 0)),
        ],
    )

    staging = phase120._table_staging_state(observation, progress)
    assert staging["target_mode"] == "locked_shaft_egress"
    assert staging["partial_shaft_lock"]["clearance_count"] == 2
    assert staging["target"]["position"] == {"x": 0.5, "y": 3, "z": 0.5}
    fingerprint = staging["target"]["shaft_egress_proof_fingerprint"]
    assert fingerprint

    exhausted = phase120._table_staging_state(
        observation,
        progress,
        attempted_egress_fingerprints={fingerprint},
    )
    assert exhausted["blocked"] is True
    assert exhausted["blocker"] == "locked_partial_shaft_egress_attempt_exhausted"


def test_phase120_latest_valid_clearance_support_owns_the_lock():
    first_support = (1, 0, 0)
    latest_support = (2, 0, 0)
    progress = _progress(
        [
            ("grass_block", (1, 3, 0), first_support),
            ("grass_block", (2, 3, 0), latest_support),
            ("dirt", (1, 2, 0), first_support),
        ]
    )
    lock = phase120._partial_clearance_lock(progress)
    assert lock["support_source_id"] == "stone:1:0:0"
    assert lock["clearance_count"] == 2


def test_phase120_egress_and_lock_fail_closed_on_tamper_or_budget_exhaustion():
    observation = next(
        item
        for item in _retained_observations()
        if item["sp003_progress"]["surface_clearance_removal_count"] == 1
        and item["sp003_complete_local_scan"]["origin_cell"]
        == {"x": 121, "y": 141, "z": -37}
    )
    progress = observation["sp003_progress"]
    target = phase120._table_staging_state(observation, progress)["target"]

    wrong_y = phase120.guard_sp003_phase120_action(
        {
            "type": "move_to",
            "parameters": {"x": 120.5, "y": 142, "z": -36.5},
        },
        observation,
        progress,
    )
    assert not wrong_y["allowed"]
    assert "sp003_partial_shaft_egress_target_mismatch" in wrong_y["issues"]

    extra = phase120.guard_sp003_phase120_action(
        {
            "type": "move_to",
            "parameters": {"x": 120.5, "y": 141, "z": -36.5, "tolerance": 8},
        },
        observation,
        progress,
    )
    assert not extra["allowed"]
    assert "sp003_partial_shaft_egress_parameters_unexpected" in extra["issues"]

    skill = phase120.guard_sp003_phase120_action(
        {
            "type": "move_to",
            "parameters": copy.deepcopy(target["position"]),
            "skill_context": {"skill_id": "learned:acquire_cobblestone"},
        },
        observation,
        progress,
    )
    assert not skill["allowed"]
    assert "sp003_partial_shaft_egress_skill_context_forbidden" in skill["issues"]

    tampered = copy.deepcopy(observation)
    tampered["sp003_complete_local_scan"]["backend_sha256"] = "0" * 64
    blocked = phase120._table_staging_state(tampered, progress)
    assert blocked["blocked"] is True
    assert blocked["target"] == {}
    assert blocked["blocker"] == "locked_partial_shaft_machine_egress_unavailable"

    missing_player = copy.deepcopy(observation)
    missing_player["position"] = {}
    blocked = phase120._table_staging_state(missing_player, progress)
    assert blocked["blocked"] is True
    assert blocked["target"] == {}
    assert blocked["blocker"] == "locked_partial_shaft_machine_egress_unavailable"

    final = next(
        item
        for item in reversed(_retained_observations())
        if item["sp003_progress"]["surface_clearance_removal_count"] == 6
    )
    exhausted = phase120._table_staging_state(final, final["sp003_progress"])
    assert exhausted["blocked"] is True
    assert exhausted["target"] == {}
    assert exhausted["blocker"] == "locked_partial_shaft_episode_clearance_limit_reached"
    seventh = phase120.guard_sp003_phase120_action(
        {
            "type": "dig",
            "parameters": {"block": "grass_block", "x": 124, "y": 140, "z": -38},
        },
        final,
        final["sp003_progress"],
    )
    assert not seventh["allowed"]
    assert seventh["action_repair"] == {}


def test_phase120_without_prior_clearance_preserves_phase118_behavior():
    observation = next(
        item
        for item in _retained_observations()
        if item["sp003_progress"]["surface_clearance_removal_count"] == 0
        and item.get("sp003_table_staging", {}).get("active") is True
    )
    progress = observation["sp003_progress"]
    assert phase120._table_staging_state(observation, progress) == (
        phase116._table_staging_state(observation, progress)
    )
    target = observation["sp003_table_staging"]["target"]["position"]
    guard = phase120.guard_sp003_phase120_action(
        {"type": "move_to", "parameters": copy.deepcopy(target)},
        observation,
        progress,
    )
    assert guard["allowed"]
    assert guard["parent_policy_id"] == (
        phase120.phase118.SP003_EXACT_NAVIGATION_PARAMETER_POLICY_ID
    )


def test_phase120_agent_consumes_one_egress_attempt(monkeypatch):
    observation = next(
        item
        for item in _retained_observations()
        if item["sp003_progress"]["surface_clearance_removal_count"] == 1
        and item["sp003_complete_local_scan"]["origin_cell"]
        == {"x": 121, "y": 141, "z": -37}
    )
    target = phase120._table_staging_state(
        observation,
        observation["sp003_progress"],
    )["target"]
    delegated = []

    def fake_verify(_self, action, _observation, _goal, _context=None):
        delegated.append(copy.deepcopy(action))
        return {"status": "accept"}, {"success": True}

    monkeypatch.setattr(base.Agent, "_verify_action_for_execution", fake_verify)
    agent = phase120.StonePickaxeSP003Phase120RuntimeAgent.__new__(
        phase120.StonePickaxeSP003Phase120RuntimeAgent
    )
    agent.sp003_progress = observation["sp003_progress"]
    agent.sp003_arm = "baseline"
    agent._sp003_phase120_egress_attempted_fingerprints = set()
    agent.session_logger = SimpleNamespace(log=lambda *args, **kwargs: None)
    action = {"type": "move_to", "parameters": copy.deepcopy(target["position"])}

    verification, result = agent._verify_action_for_execution(
        action,
        observation,
        "SP-003",
        {"cycle": 10},
    )
    assert verification == {"status": "accept"}
    assert result == {"success": True}
    assert delegated == [action]
    assert agent._sp003_phase120_egress_attempted_fingerprints == {
        target["shaft_egress_proof_fingerprint"]
    }

    second_action = {
        "type": "move_to",
        "parameters": copy.deepcopy(target["position"]),
    }
    verification, result = agent._verify_action_for_execution(
        second_action,
        observation,
        "SP-003",
        {"cycle": 11},
    )
    assert verification["status"] == "reject"
    assert result["verification_blocked"] is True
    assert "sp003_locked_partial_shaft_machine_target_required" in result["error"]
    assert len(delegated) == 1


def test_phase120_observe_exposes_table_reference_after_locked_access(monkeypatch):
    support = (1, 0, 0)
    progress = _progress(
        [
            ("grass_block", (1, 3, 0), support),
            ("dirt", (1, 2, 0), support),
            ("dirt", (1, 1, 0), support),
        ]
    )
    observation = _observation(
        (1.5, 1, 0.5),
        [
            ("stone", support),
            ("stone", (1, -1, 0)),
            ("stone", (0, 0, 0)),
        ],
    )
    monkeypatch.setattr(
        phase120.phase118.StonePickaxeSP003Phase118RuntimeAgent,
        "_observe",
        lambda _self: copy.deepcopy(observation),
    )
    agent = phase120.StonePickaxeSP003Phase120RuntimeAgent.__new__(
        phase120.StonePickaxeSP003Phase120RuntimeAgent
    )
    agent.sp003_progress = progress
    agent._sp003_phase120_egress_attempted_fingerprints = set()

    enriched = agent._observe()
    assert enriched["sp003_table_staging"]["ready_for_table_placement"] is True
    assert enriched["sp003_targets"]
    reference = enriched["sp003_targets"][0]
    assert reference["name"] in phase120.SP003_SHAFT_EGRESS_GROUND_BLOCKS

    guard = phase120.guard_sp003_phase120_action(
        {
            "type": "place",
            "parameters": {
                "item": "crafting_table",
                **copy.deepcopy(reference["position"]),
            },
        },
        enriched,
        progress,
    )
    assert guard["allowed"], guard
    assert guard["selected_source"]["source_id"] == reference["source_id"]
    assert guard["action_repair"]["target_mode"] == "table_placement"
    assert guard["action_repair"]["world_mutation"] == (
        "one_machine_bound_crafting_table_placement"
    )


def test_phase120_runner_is_process_local_and_launcher_uses_it():
    wrapper = (
        REPO / "scripts/stone_pickaxe_sp003_phase120_episode_runner.py"
    ).read_text(encoding="utf-8")
    launcher = subprocess.check_output(
        [
            "git",
            "show",
            f"{PHASE120_FIX_COMMIT}:scripts/stone-pickaxe-sp003-runtime.ps1",
        ],
        cwd=REPO,
        text=True,
        encoding="utf-8",
    )
    frozen = (REPO / "scripts/stone_pickaxe_sp003_episode_runner.py").read_bytes()
    phase118_wrapper = (
        REPO / "scripts/stone_pickaxe_sp003_phase118_episode_runner.py"
    ).read_bytes()

    assert "frozen_runner.StonePickaxeSP003Phase116RuntimeAgent" in wrapper
    assert "StonePickaxeSP003Phase120RuntimeAgent" in wrapper
    assert launcher.count("stone_pickaxe_sp003_phase120_episode_runner.py") == 2
    assert "stone_pickaxe_sp003_phase118_episode_runner.py" not in launcher
    assert base.file_sha256(REPO / "scripts/stone_pickaxe_sp003_episode_runner.py") == (
        "0ca5ad64c0f77b246276bb9e9c01d8d88bc95227bcb9a017a14150e9173ba8a5"
    )
    assert base.file_sha256(
        REPO / "scripts/stone_pickaxe_sp003_phase118_episode_runner.py"
    ) == "875f5ac63030f5ba70b49abcecbbe58ffe9045140462dd4a925fd631122eeaa4"
    assert frozen
    assert phase118_wrapper


def test_phase120_audit_binds_repair_and_protected_identities():
    audit = json.loads(
        (
            REPO
            / "workspace/evals/stone_pickaxe_sp003_partial_clearance_shaft_continuation_repair.json"
        ).read_text(encoding="utf-8")
    )
    assert audit["phase"] == 120
    assert audit["base_commit"] == (
        "5eedb1b43c04ef0d0c2dac5c6c2062953bff65bb"
    )
    assert audit["policy_id"] == (
        phase120.SP003_PARTIAL_SHAFT_CONTINUATION_POLICY_ID
    )
    assert audit["status"] == "offline_verified"
    assert audit["retained_failure"]["manifest_sha256"] == (
        "fb64e76fc8980421a7bb957740f1e11ddadbddf6d82576524c426270fe09080b"
    )
    for record in audit["implementation"]:
        historical = subprocess.check_output(
            ["git", "show", f"{PHASE120_FIX_COMMIT}:{record['path']}"],
            cwd=REPO,
        )
        assert hashlib.sha256(historical).hexdigest() == record["sha256"]
    for record in [
        *audit["protected_phase_118_identities"],
        *audit["protected_runtime_identities"],
        *audit["retained_evidence_identities"],
    ]:
        if record["path"].startswith("node_modules/"):
            assert hashlib.sha256((REPO / record["path"]).read_bytes()).hexdigest() == (
                record["sha256"]
            )
            continue
        historical = subprocess.check_output(
            ["git", "show", f"{PHASE120_FIX_COMMIT}:{record['path']}"],
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
