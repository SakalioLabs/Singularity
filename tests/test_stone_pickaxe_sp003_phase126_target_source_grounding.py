from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import subprocess

from singularity.core.planner import Planner
from singularity.evaluation.stone_pickaxe_protocol import (
    _sp001_source_candidates,
    canonical_sha256,
    verify_sp001_episode,
)
from singularity.evaluation.stone_pickaxe_sp002_runtime import evidence_observation
from singularity.evaluation.stone_pickaxe_sp003_runtime import (
    SP003_POLICY_PATH,
    SP003_SP001_SOURCE_ORDER_LIMIT,
    SP003_SP001_SOURCE_ORDER_POLICY_ID,
    SP003_TABLE_TARGET_SEMANTICS_POLICY_ID,
    StonePickaxeSP003RuntimeAgent,
    _build_sp001_component,
    _bounded_complete_local_scan,
    _empty_progress,
    _place_reference_candidates,
    _safe_stone_candidates,
    _sp003_sp001_evidence_observation,
    _sp003_sp001_source_order_contract,
    _stone_approach_stands,
    _stone_pickup_accesses,
    _stone_surface_clearances,
)


REPO = Path(__file__).resolve().parents[1]
PHASE126_FIX_COMMIT = "8d21c177003aecde3ff9b5159ae4ba780508375d"
PHASE125_RUN = (
    REPO
    / "workspace/evals/sp003_runs/sp003_baseline_20260720_051930_f39bab4c"
)
AUDIT_PATH = (
    REPO
    / "workspace/evals/stone_pickaxe_sp003_stage_target_and_sp001_source_grounding_repair.json"
)


def _block(name: str, x: int, y: int, z: int, distance: float) -> dict:
    return {
        "name": name,
        "position": {"x": x, "y": y, "z": z},
        "distance": distance,
    }


def _stone_stage_world() -> tuple[dict, dict]:
    player = {"x": 0.9, "y": 64.0, "z": 0.1}
    blocks = [
        _block("stone", 1, 63, 0, 2.0),
        _block("stone", 1, 62, 0, 2.5),
        _block("stone", 0, 63, 1, 1.4),
        _block("stone", 0, 62, 1, 2.0),
        _block("stone", -1, 63, 0, 1.1),
        _block("stone", -1, 62, 0, 1.8),
        _block("stone", 1, 64, 1, 0.2),
    ]
    world = {
        "position": player,
        "nearby_blocks": blocks,
        "inventory": {"wooden_pickaxe": 1},
        "equipment": [{"name": "wooden_pickaxe"}],
        "health": 20,
        "hunger": 20,
        "game_mode": "survival",
        "dimension": "overworld",
        "ground_block": "stone",
    }
    scan = _bounded_complete_local_scan(world, blocks, world)
    assert scan["scan_complete"] is True
    world["sp003_complete_local_scan"] = scan
    world["sp003_stone_approach_stands"] = _stone_approach_stands(scan)
    world["sp003_stone_pickup_accesses"] = _stone_pickup_accesses(scan)
    world["sp003_stone_surface_clearances"] = _stone_surface_clearances(scan)
    progress = _empty_progress()
    progress.update({
        "log_source_ids": {"oak_log:1:64:0", "oak_log:1:65:0", "oak_log:1:66:0"},
        "log_source_removal_count": 3,
        "log_item": "oak_log",
        "plank_craft_count": 1,
        "stick_craft_count": 1,
        "crafting_table_craft_count": 1,
        "crafting_table_place_count": 1,
        "wooden_pickaxe_craft_count": 1,
        "wooden_pickaxe_equip_count": 1,
    })
    return world, progress


def test_phase126_table_reference_has_literal_place_semantics_in_planner_state():
    world = {
        "position": {"x": 0.5, "y": 64.0, "z": 0.5},
        "nearby_blocks": [_block("grass_block", 1, 63, 0, 1.225)],
        "inventory": {"crafting_table": 1, "oak_planks": 6, "stick": 4},
        "equipment": [],
        "stone_pickaxe_runtime_mode": "sp003",
        "sp003_arm": "baseline",
        "sp003_progress": {
            "log_source_removal_count": 3,
            "log_item": "oak_log",
            "plank_craft_count": 1,
            "stick_craft_count": 1,
            "crafting_table_craft_count": 1,
        },
    }
    targets = _place_reference_candidates(world)
    assert len(targets) == 1
    assert targets[0]["name"] == "grass_block"
    assert targets[0]["machine_proven_placement"] is True
    assert (
        targets[0]["target_semantics_policy_id"]
        == SP003_TABLE_TARGET_SEMANTICS_POLICY_ID
    )
    world["sp003_targets"] = targets

    compact = Planner._compact_stone_pickaxe_state(world)
    target = compact["sp003_targets"][0]
    assert compact["sp003_stage"] == "place_crafting_table"
    assert target["machine_proven_placement"] is True
    assert target["stone_surface_clearance"] is False
    assert target["stone_clearance_probe"] is False
    assert target["stone_pickup_approach"] is False
    assert target["stone_pickup_access"] is False
    assert target["target_semantics_policy_id"] == (
        SP003_TABLE_TARGET_SEMANTICS_POLICY_ID
    )

    planner = object.__new__(Planner)
    planner._expected_plan_kind = "continuation"
    prompt = Planner._stone_pickaxe_system_prompt(planner)
    assert "false means absent" in prompt
    assert "machine_proven_placement=true requires place" in prompt
    assert "Never dig that reference" in prompt


def test_phase126_sp001_snapshot_uses_machine_reachability_and_exact_source_order():
    world, progress = _stone_stage_world()
    candidates = [
        candidate
        for candidate in _safe_stone_candidates(world, progress)
        if candidate.get("stone_pickup_access") is True
    ]
    assert [candidate["source_id"] for candidate in candidates] == [
        "stone:1:63:0",
        "stone:0:63:1",
        "stone:-1:63:0",
    ]
    assert [candidate["distance"] for candidate in candidates] == [
        1.00995,
        1.618641,
        2.149419,
    ]
    contract = _sp003_sp001_source_order_contract(world, progress)
    assert contract["policy_id"] == SP003_SP001_SOURCE_ORDER_POLICY_ID
    assert contract["source_limit"] == SP003_SP001_SOURCE_ORDER_LIMIT
    assert contract["source_count"] == 3
    unsigned = {
        key: value
        for key, value in contract.items()
        if key != "contract_fingerprint"
    }
    assert contract["contract_fingerprint"] == canonical_sha256(unsigned)
    world["sp003_sp001_source_order"] = contract

    agent = object.__new__(StonePickaxeSP003RuntimeAgent)
    snapshot = agent._action_observation_snapshot(world)
    assert snapshot["ground_block"] == "stone"
    assert snapshot["sp003_sp001_source_order"] == contract
    evidence = _sp003_sp001_evidence_observation(
        snapshot,
        role="phase126_pre_dig",
        ordinal=1,
        monotonic_s=1.0,
    )
    assert evidence["movable"] is True
    assert evidence["sp003_sp001_source_order_valid"] is True
    by_id = {block["source_id"]: block for block in evidence["observed_blocks"]}
    assert by_id["stone:1:64:1"]["reachable"] is False
    assert by_id["stone:1:64:1"]["distance"] < by_id["stone:1:63:0"]["distance"]
    assert [
        candidate["source_id"]
        for candidate in _sp001_source_candidates(evidence, set())
    ] == [
        "stone:1:63:0",
        "stone:0:63:1",
        "stone:-1:63:0",
    ]


def test_phase126_sp001_source_order_tampering_fails_closed():
    world, progress = _stone_stage_world()
    contract = _sp003_sp001_source_order_contract(world, progress)
    contract["sources"][0]["distance"] += 0.1
    unsigned = {
        key: value
        for key, value in contract.items()
        if key != "contract_fingerprint"
    }
    contract["contract_fingerprint"] = canonical_sha256(unsigned)
    world["sp003_sp001_source_order"] = contract

    agent = object.__new__(StonePickaxeSP003RuntimeAgent)
    snapshot = agent._action_observation_snapshot(world)
    evidence = _sp003_sp001_evidence_observation(
        snapshot,
        role="phase126_tampered_pre_dig",
        ordinal=1,
        monotonic_s=1.0,
    )
    assert evidence["sp003_sp001_source_order_valid"] is False
    assert not any(block["reachable"] for block in evidence["observed_blocks"])
    assert _sp001_source_candidates(evidence, set()) == []

    missing_position = copy.deepcopy(snapshot)
    missing_position.pop("position")
    missing_position_evidence = _sp003_sp001_evidence_observation(
        missing_position,
        role="phase126_missing_position_pre_dig",
        ordinal=1,
        monotonic_s=1.0,
    )
    assert missing_position_evidence["sp003_sp001_source_order_valid"] is False
    assert not any(
        block["reachable"]
        for block in missing_position_evidence["observed_blocks"]
    )


def test_phase126_phase125_machine_state_counterfactual_passes_sp001_verifier():
    events = json.loads((PHASE125_RUN / "session.json").read_text(encoding="utf-8"))
    episode = json.loads((PHASE125_RUN / "episode.json").read_text(encoding="utf-8"))
    actions = [
        copy.deepcopy(event) for event in events if event.get("type") == "action"
    ]
    observations = [
        event["data"] for event in events if event.get("type") == "observation"
    ]
    agent = object.__new__(StonePickaxeSP003RuntimeAgent)
    stone_ordinal = 0
    for event in actions:
        data = event["data"]
        action = data.get("action", {})
        params = action.get("parameters", {})
        if action.get("type") != "dig" or params.get("block") != "stone":
            continue
        pre = copy.deepcopy(next(
            observation
            for observation in reversed(observations)
            if observation.get("sp003_progress", {}).get(
                "stone_source_removal_count"
            ) == stone_ordinal
        ))
        post = copy.deepcopy(next(
            observation
            for observation in observations
            if observation.get("sp003_progress", {}).get(
                "stone_source_removal_count"
            ) == stone_ordinal + 1
        ))
        for raw in (pre, post):
            contract = _sp003_sp001_source_order_contract(
                raw,
                raw.get("sp003_progress", {}),
            )
            if contract:
                raw["sp003_sp001_source_order"] = contract
        data["pre_observation"] = agent._action_observation_snapshot(pre)
        data["post_observation"] = agent._action_observation_snapshot(post)
        stone_ordinal += 1

    component = _build_sp001_component(
        action_events=actions,
        episode_id=episode["episode_id"],
        session_id=episode["session_id"],
        session_sha256=episode["session_sha256"],
        level_name=episode["level_name"],
        goal_result=episode["goal_result"],
        planner_audit=episode["planner_request_controls"],
        reset_audit=episode["reset_audit"],
        forbidden=episode["forbidden_interventions"],
        post_deadline=[],
        initial_monotonic=episode["episode_started_monotonic"],
        selected_skills=episode["selected_skills"],
    )
    report = verify_sp001_episode(component)
    assert report["passed"] is True
    assert report["criteria_issues"] == []
    assert component["initial_observation"]["movable"] is True
    assert [transition["source_id"] for transition in component["transitions"]] == [
        "stone:124:139:-38",
        "stone:124:139:-37",
        "stone:124:138:-38",
    ]
    assert [
        [
            block["source_id"]
            for block in transition["pre_observation"]["observed_blocks"]
            if block["reachable"] is True
        ]
        for transition in component["transitions"]
    ] == [
        ["stone:124:139:-38"],
        ["stone:124:139:-37"],
        ["stone:124:138:-38"],
    ]


def test_phase126_legacy_phase125_snapshots_keep_original_evidence_semantics():
    events = json.loads((PHASE125_RUN / "session.json").read_text(encoding="utf-8"))
    action = next(
        event["data"]
        for event in events
        if event.get("type") == "action"
        and (event.get("data") or {}).get("action", {}).get("type") == "dig"
        and (event.get("data") or {}).get("action", {}).get("parameters", {}).get(
            "block"
        ) == "stone"
    )
    raw = action["pre_observation"]
    assert "ground_block" not in raw
    assert "sp003_sp001_source_order" not in raw
    expected = evidence_observation(
        raw,
        role="phase125_legacy",
        ordinal=1,
        monotonic_s=1.0,
    )
    actual = _sp003_sp001_evidence_observation(
        raw,
        role="phase125_legacy",
        ordinal=1,
        monotonic_s=1.0,
    )
    assert actual == expected
    assert actual["movable"] is False


def test_phase126_policy_binds_target_and_source_grounding_without_credit():
    policy = json.loads(SP003_POLICY_PATH.read_text(encoding="utf-8"))
    contract = policy["episode_contract"]
    assert contract["planner_target_boolean_markers_explicit"] is True
    assert contract["planner_target_false_marker_inference_allowed"] is False
    assert contract["table_target_semantics_policy_id"] == (
        SP003_TABLE_TARGET_SEMANTICS_POLICY_ID
    )
    assert contract["sp001_source_order_policy_id"] == (
        SP003_SP001_SOURCE_ORDER_POLICY_ID
    )
    assert contract["sp001_source_order_limit"] == SP003_SP001_SOURCE_ORDER_LIMIT
    assert contract["sp001_unproven_nearby_stone_reachable"] is False
    assert contract["sp001_legacy_snapshot_semantics_unchanged"] is True
    assert policy["current_state"]["live_authorization"] is False
    assert policy["capability_policy"]["counts_toward_capability"] is False
    assert policy["capability_policy"]["counts_toward_m4"] is False


def test_phase126_audit_binds_implementation_and_protected_evidence():
    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    assert audit["phase"] == 126
    assert audit["base_commit"] == "41b484a1e755d3743b6aa111e3017125452fa240"
    assert audit["status"] == "offline_verified"
    assert audit["policy_ids"] == [
        SP003_TABLE_TARGET_SEMANTICS_POLICY_ID,
        SP003_SP001_SOURCE_ORDER_POLICY_ID,
    ]
    assert audit["counterfactual_replay"]["sp001_machine_verifier_passed"] is True
    assert audit["counterfactual_replay"]["criteria_issues"] == []
    assert audit["repair_contract"]["planner_action_rewrite_allowed"] is False
    assert audit["repair_contract"]["automatic_retry_added"] is False
    assert audit["repair_contract"]["legacy_evidence_semantics_unchanged"] is True
    assert audit["live_episode_run"] is False
    assert audit["live_authorization"] is False
    assert audit["counts_toward_baseline_success"] is False
    assert audit["counts_toward_capability"] is False
    assert audit["counts_toward_m4"] is False
    for record in audit["implementation"]:
        retained = subprocess.check_output(
            ["git", "show", f"{PHASE126_FIX_COMMIT}:{record['path']}"],
            cwd=REPO,
        )
        assert hashlib.sha256(retained).hexdigest() == record["sha256"]
    for record in [
        *audit["protected_identities"],
        *audit["retained_phase_125_identities"],
    ]:
        if record["path"] == (
            "src/singularity/evaluation/stone_pickaxe_sp003_phase122_runtime.py"
        ):
            retained = subprocess.check_output(
                ["git", "show", f"{PHASE126_FIX_COMMIT}:{record['path']}"],
                cwd=REPO,
            )
        else:
            retained = (REPO / record["path"]).read_bytes()
        assert hashlib.sha256(retained).hexdigest() == record["sha256"]
