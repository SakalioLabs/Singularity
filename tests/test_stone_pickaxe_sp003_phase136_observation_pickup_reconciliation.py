from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from singularity.evaluation.stone_pickaxe_protocol import canonical_sha256
from singularity.evaluation.stone_pickaxe_sp003_runtime import (
    SP003_OBSERVATION_LOG_PICKUP_POLICY_ID,
    _empty_progress,
    _progress_snapshot,
    _sp003_observation_targets,
    guard_sp003_action,
    reconcile_sp003_observation_log_pickups,
    record_sp003_success,
    verify_sp003_policy_identity,
)


REPO = Path(__file__).resolve().parents[1]
RUN_ID = "sp003_baseline_20260720_121934_e86b807f"
RUN_DIR = REPO / "workspace/evals/sp003_runs" / RUN_ID
AUDIT_PATH = (
    REPO
    / "workspace/evals/stone_pickaxe_sp003_observation_pickup_reconciliation_repair.json"
)


def _phase135_counterfactual():
    events = json.loads((RUN_DIR / "session.json").read_text(encoding="utf-8"))
    log_actions = [
        copy.deepcopy(event["data"])
        for event in events
        if event.get("type") == "action"
        and event.get("data", {}).get("action", {}).get("parameters", {}).get(
            "block"
        )
        == "oak_log"
    ]
    progress = _empty_progress()
    for data in log_actions[:3]:
        record_sp003_success(progress, data["action"], data["result"])
    return progress, copy.deepcopy(events[96]["data"]), log_actions[3]


def test_phase136_exact_phase135_replay_reconciles_within_one_observation():
    progress, observed, fourth_log_action = _phase135_counterfactual()
    before = _progress_snapshot(progress)

    proof = reconcile_sp003_observation_log_pickups(progress, observed)
    after = _progress_snapshot(progress)

    assert observed["inventory"] == {"oak_log": 3}
    assert before["log_source_removal_count"] == 2
    assert before["pending_log_pickup_count"] == 1
    assert proof["policy_id"] == SP003_OBSERVATION_LOG_PICKUP_POLICY_ID
    assert proof["fresh_observation_boundary_count"] == 1
    assert proof["reconciled_pending_source_ids"] == ["oak_log:119:141:-33"]
    assert proof["proof_fingerprint"] == canonical_sha256({
        key: value
        for key, value in proof.items()
        if key != "proof_fingerprint"
    })
    assert after["log_source_removal_count"] == 3
    assert after["pending_log_pickup_count"] == 0
    assert after["successful_mutation_count"] == before["successful_mutation_count"]
    assert _sp003_observation_targets(observed, progress) == []
    assert fourth_log_action["action"]["parameters"]["source_id"] == (
        "oak_log:119:143:-33"
    )
    plank = guard_sp003_action(
        {"type": "craft", "parameters": {"item": "oak_planks", "count": 12}},
        observed,
        progress,
    )
    assert plank["allowed"], plank
    assert reconcile_sp003_observation_log_pickups(progress, observed) == {}
    assert _progress_snapshot(progress) == after


@pytest.mark.parametrize(
    "inventory,tamper",
    [
        ({"oak_log": 4}, None),
        ({"oak_log": 2}, None),
        ({"birch_log": 3}, None),
        ({"oak_log": 3, "birch_log": 1}, None),
        (
            {"oak_log": 3},
            lambda progress: progress["pending_log_pickups"][0].update(
                {"proof_fingerprint": "f" * 64}
            ),
        ),
    ],
)
def test_phase136_fails_closed_for_overshoot_stale_wrong_family_and_forgery(
    inventory,
    tamper,
):
    progress, observed, _ = _phase135_counterfactual()
    observed["inventory"] = inventory
    if tamper is not None:
        tamper(progress)
    before = _progress_snapshot(progress)

    assert reconcile_sp003_observation_log_pickups(progress, observed) == {}
    assert _progress_snapshot(progress) == before


def test_phase136_policy_is_bound_and_live_authorization_remains_false():
    identity = verify_sp003_policy_identity()
    assert identity["passed"], identity
    assert identity["checks"][
        "observation_log_pickup_reconciliation_contract"
    ] is True

    policy = json.loads(
        (
            REPO / "workspace/evals/stone_pickaxe_sp003_harness_policy.json"
        ).read_text(encoding="utf-8")
    )
    contract = policy["episode_contract"]
    assert contract[
        "observation_delayed_log_pickup_reconciliation_policy_id"
    ] == SP003_OBSERVATION_LOG_PICKUP_POLICY_ID
    assert contract["observation_delayed_pickup_reconciliation_tick_max"] == 1
    assert contract["observation_delayed_pickup_action_invocation_allowed"] is False
    assert contract["observation_delayed_pickup_world_mutation_allowed"] is False
    assert policy["current_state"]["live_authorization"] is False


def test_phase136_audit_binds_repair_and_retained_phase135_evidence():
    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    assert audit["phase"] == 136
    assert audit["base_commit"] == "0e66e22ddefb0b64ca3efc02220df631074fdcd7"
    assert audit["policy_id"] == SP003_OBSERVATION_LOG_PICKUP_POLICY_ID
    assert audit["status"] == "offline_verified"
    assert audit["retained_phase_135_failure"]["episode_id"] == RUN_ID
    assert audit["retained_phase_135_failure"]["manifest_sha256"] == (
        "9ed16b45f2ca9bbb6ef9e38b5d0ae9d9cbf072dd056108027f27405bb5c5cf48"
    )
    assert audit["counterfactual_tests"]["focused_cases"] == "20/20"
    assert audit["repair_contract"]["fresh_observation_boundary_count_max"] == 1
    assert audit["repair_contract"]["action_invocation_allowed"] is False
    assert audit["repair_contract"]["world_mutation_allowed"] is False
    assert audit["live_episode_run"] is False
    assert audit["live_authorization"] is False
    assert audit["counts_toward_baseline_success"] is False
    assert audit["counts_toward_skill_gate"] is False
    assert audit["counts_toward_capability"] is False
    assert audit["counts_toward_m4"] is False
    for record in [
        *audit["implementation"],
        *audit["protected_identities"],
        *audit["retained_phase_135_identities"],
    ]:
        path = REPO / record["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]
