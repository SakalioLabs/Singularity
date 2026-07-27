"""Bind the one-use Probe 55 authorization to the pushed Probe 54 gate."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUTHORIZATION_PATH = ROOT / "workspace/evals/m4_probe55_authorization.json"
GATE_PARENT_COMMIT = "19c495d5aab0fcf46a09e077a33a368c42987130"
GATE_TREE = "2c2cf0020d9072c7049e2f83c02bc2af6e90a110"
POLICY_ID = "m4-bm013-bm014-portable-crafting-table-recovery-v1"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _git_blob(commit: str, path: str) -> bytes:
    return subprocess.run(
        ["git", "show", f"{commit}:{Path(path).as_posix()}"],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout


def _git_json(commit: str, path: str) -> dict:
    return json.loads(_git_blob(commit, path).decode("utf-8"))


def _git_revision(revision: str) -> str:
    return subprocess.run(
        ["git", "rev-parse", revision],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ).stdout.strip()


def _git_sha256(commit: str, path: str) -> str:
    return hashlib.sha256(_git_blob(commit, path)).hexdigest()


def test_probe55_authorization_binds_pushed_gate_and_fixed_contract():
    authorization = _json(AUTHORIZATION_PATH)

    assert authorization["type"] == "m4_live_probe_authorization"
    assert authorization["schema_version"] == 1
    assert authorization["profile"] == "m4-fixed-v1"
    assert authorization["provider_revision"] == (
        "m4-grok-4.5-openai-compatible-v2"
    )
    assert authorization["task_id"] == "BM-014"
    assert authorization["probe_number"] == 55
    assert authorization["task_contract_id"] == (
        "m4-bm014-iron-pickaxe-contract-v1"
    )
    assert authorization["protocol_sha256"] == _git_sha256(
        GATE_PARENT_COMMIT,
        "src/singularity/data/m4_protocol.json",
    )
    assert authorization["task_contract_sha256"] == _git_sha256(
        GATE_PARENT_COMMIT,
        "src/singularity/data/m4_bm014_protocol.json",
    )
    assert authorization["gate_parent_commit"] == GATE_PARENT_COMMIT
    assert authorization["gate_tree"] == GATE_TREE
    assert _git_revision(GATE_PARENT_COMMIT) == GATE_PARENT_COMMIT
    assert _git_revision(f"{GATE_PARENT_COMMIT}^{{tree}}") == GATE_TREE
    assert authorization["policy_id"] == POLICY_ID
    assert authorization["gate_remote_readback"] == {
        "commit_parent_verified": True,
        "tree_verified": True,
        "expected_blob_count": 24,
        "blob_mismatch_count": 0,
    }
    assert authorization["gate_clean_validation"] == {
        "m4_python_pass_count": 298,
        "m4_python_fail_count": 0,
        "capability_action_python_pass_count": 43,
        "capability_action_python_fail_count": 0,
    }


def test_probe55_authorization_freezes_every_gate_dependency():
    authorization = _json(AUTHORIZATION_PATH)
    path_hash_pairs = (
        ("prior_probe_report_path", "prior_probe_report_sha256"),
        ("prior_probe_report_test_path", "prior_probe_report_test_sha256"),
        (
            "prior_probe_consumed_authorization_path",
            "prior_probe_consumed_authorization_sha256",
        ),
        (
            "prior_probe_consumed_authorization_test_path",
            "prior_probe_consumed_authorization_test_sha256",
        ),
        ("repair_audit_path", "repair_audit_sha256"),
        ("repair_audit_test_path", "repair_audit_test_sha256"),
        ("capability_evidence_path", "capability_evidence_sha256"),
        ("failure_ledger_path", "failure_ledger_sha256"),
    )
    for path_key, hash_key in path_hash_pairs:
        assert authorization[hash_key] == _git_sha256(
            GATE_PARENT_COMMIT,
            authorization[path_key],
        )

    assert set(authorization["repair_source_paths"]) == {
        "agent",
        "agent_tests",
    }
    assert set(authorization["repair_source_sha256"]) == {
        "agent",
        "agent_tests",
    }
    for key, relative_path in authorization["repair_source_paths"].items():
        assert authorization["repair_source_sha256"][key] == _git_sha256(
            GATE_PARENT_COMMIT,
            relative_path,
        )


def test_probe55_authorization_binds_probe54_failure_and_canonical_counts():
    authorization = _json(AUTHORIZATION_PATH)
    report = _git_json(
        GATE_PARENT_COMMIT,
        authorization["prior_probe_report_path"],
    )
    consumed = _git_json(
        GATE_PARENT_COMMIT,
        authorization["prior_probe_consumed_authorization_path"],
    )
    repair = _git_json(
        GATE_PARENT_COMMIT,
        authorization["repair_audit_path"],
    )
    capability = _git_json(
        GATE_PARENT_COMMIT,
        authorization["capability_evidence_path"],
    )
    ledger = _git_json(
        GATE_PARENT_COMMIT,
        authorization["failure_ledger_path"],
    )
    m4 = next(phase for phase in capability["phases"] if phase["id"] == "M4")
    bm014 = next(
        benchmark
        for benchmark in m4["benchmarks"]
        if benchmark["task_id"] == "BM-014"
    )

    assert report["episode_id"] == authorization["prior_probe_episode_id"]
    assert report["session_id"] == authorization["prior_probe_session_id"]
    assert report["level_name"] == authorization["prior_probe_level_name"]
    assert report["eligibility"]["eligible"] is False
    assert report["eligibility"]["success"] is False
    assert report["eligibility"]["counts_toward_bm014_success"] is False
    assert report["failure_analysis"]["classification"] == (
        "capability_navigation_inventory_preservation_failure"
    )
    assert report["failure_analysis"]["infrastructure_failure"] is False
    assert report["failure_analysis"]["counts_as_bm014_attempt"] is True
    assert report["failure_analysis"]["counts_as_bm014_failure"] is True
    assert report["failure_analysis"]["primary_cause"] == (
        "navigation_inventory_depletion_caused_portable_station_recovery_gap"
    )
    assert report["failure_analysis"]["secondary_amplification"] == (
        "planner_transport_timeout"
    )
    assert (
        report["failure_analysis"][
            "planner_timeouts_were_distinct_cycle_calls_not_same_call_retries"
        ]
        is True
    )
    assert report["decision"]["bm014_attempt_count_after"] == 4
    assert report["decision"]["bm014_failure_count_after"] == 3
    assert report["decision"]["bm014_success_count_after"] == 1
    assert report["decision"]["remaining_success_count"] == 2
    assert report["decision"]["probe_55_authorized"] is False

    assert consumed["probe_number"] == 54
    assert consumed["consumed"] is True
    assert consumed["consumed_by_episode"] == report["episode_id"]
    assert consumed["consumed_session_id"] == report["session_id"]
    assert consumed["consumed_level_name"] == report["level_name"]
    assert consumed["consumed_event_line"] == 2
    assert consumed["one_use"] is True
    assert consumed["maximum_episode_count"] == 1
    assert consumed["maximum_retry_count"] == 0
    assert consumed["next_authorization"] is False
    assert consumed["probe_55_authorized"] is False

    assert repair["classification"] == "offline_capability_failure_remediation"
    assert repair["offline_repair"]["policy_id"] == POLICY_ID
    assert repair["decision"]["repair_claimed_complete_offline"] is True
    assert repair["decision"]["live_validation_complete"] is False
    assert repair["decision"]["counts_toward_bm014_success"] is False
    assert repair["decision"]["counts_toward_capability"] is False
    assert repair["decision"]["probe_55_authorized"] is False

    assert bm014["attempts"] == authorization["prior_bm014_attempt_count"] == 4
    assert bm014["failures"] == authorization["prior_bm014_failure_count"] == 3
    assert (
        bm014["successes"]
        == authorization["prior_bm014_eligible_success_count"]
        == 1
    )
    assert (
        bm014["repeats_required"]
        == authorization["required_bm014_eligible_success_count"]
        == 3
    )
    assert authorization["remaining_bm014_eligible_success_count_before_probe"] == (
        bm014["repeats_required"] - bm014["successes"]
    ) == 2
    assert bm014["status"] == authorization["bm014_status_before_probe"] == (
        "live_observed"
    )
    assert m4["status"] == authorization["m4_status_before_probe"] == (
        "live_observed"
    )

    gate = ledger["current_gate"]
    assert ledger["live_episode_count_under_current_protocol"] == 30
    assert gate["bm014_probe_54_consumed"] is True
    assert gate["bm014_probe_54_eligible"] is False
    assert gate["bm014_probe_54_counts_toward_success"] is False
    assert gate["bm014_probe_54_portable_table_repair_complete_offline"] is True
    assert gate["bm014_probe_55_authorized"] is False
    assert gate["bm014_attempt_count"] == 4
    assert gate["bm014_failure_count"] == 3
    assert gate["bm014_success_count"] == 1
    assert gate["bm014_remaining_eligible_success_count"] == 2
    assert gate["bm014_status"] == gate["m4_status"] == "live_observed"
    assert gate["bm014_locked"] is True


def test_probe55_authorization_binds_every_portable_recovery_boundary():
    authorization = _json(AUTHORIZATION_PATH)
    audit = _git_json(
        GATE_PARENT_COMMIT,
        authorization["repair_audit_path"],
    )
    repair = audit["offline_repair"]
    replay = repair["ordered_mutation_replay"]
    reclaim = repair["remote_resource_move_reclaim"]
    table_return = repair["historical_table_return"]
    material = repair["material_recovery"]
    execution = repair["execution_path_gates"]
    isolation = repair["policy_isolation"]
    controls = repair["unchanged_controls"]
    audit_validation = audit["offline_validation"]
    validation = authorization["repair_validation"]

    assert validation["focused_agent_python_pass_count"] == (
        audit_validation["focused_agent_pass_count"]
    ) == 26
    assert validation["audit_python_pass_count"] == (
        audit_validation["audit_pass_count"]
    ) == 5
    assert validation["combined_agent_and_audit_python_pass_count"] == (
        audit_validation["combined_pass_count"]
    ) == 31
    assert audit_validation["focused_agent_fail_count"] == 0
    assert audit_validation["audit_fail_count"] == 0
    assert audit_validation["combined_fail_count"] == 0

    assert validation["ordered_successful_place_and_dig_mutations_replayed"] is True
    assert replay["successful_place_and_dig_only"] is True
    assert validation["same_coordinate_later_mutation_wins"] == (
        replay["same_coordinate_later_mutation_wins"]
    ) is True
    assert validation["removed_or_replaced_table_not_returned"] == (
        replay["removed_or_replaced_table_excluded"]
    ) is True
    assert validation["aggregate_delta_fallback_live_enabled"] == (
        replay["aggregate_delta_fallback_live_enabled"]
    ) is False
    assert validation["aggregate_delta_fallback_isolated_offline_only"] == (
        replay["aggregate_delta_fallback_isolated_offline_only"]
    ) is True
    assert validation["ambiguous_aggregate_place_and_remove_same_cell_rejected"] == (
        replay["ambiguous_aggregate_place_and_remove_same_cell_rejected"]
    ) is True

    assert validation["remote_resource_move_must_be_move_to"] == (
        reclaim["underlying_next_action_must_be_remote_move_to"]
    ) is True
    assert validation["proactive_reclaim_requires_current_machine_observation"] == (
        reclaim["crafting_table_must_be_currently_machine_observed"]
    ) is True
    assert validation["proactive_reclaim_requires_episode_owned_place_history"] == (
        reclaim[
            "crafting_table_must_be_episode_owned_by_successful_mutation_history"
        ]
    ) is True
    assert validation["maximum_reclaim_distance"] == (
        reclaim["maximum_interaction_distance"]
    ) == 4.5
    assert validation["arbitrary_unowned_table_reclaimed"] == (
        reclaim["arbitrary_unowned_table_reclaimed"]
    ) is False
    assert reclaim["historical_coordinate_alone_authorizes_reclaim"] is False

    assert validation["historical_table_coordinate_is_navigation_only"] is True
    assert table_return["use"] == (
        "navigation target for current reobservation only"
    )
    assert table_return["historical_coordinate_treated_as_current_block_observation"] is False
    assert validation["return_requires_current_reobservation_before_use"] == (
        table_return["current_reobservation_required_before_use"]
    ) is True
    assert validation["in_range_unobserved_table_does_not_repeat_move"] is True
    assert table_return["within_4_5_and_not_currently_visible_repeats_navigation"] is False

    assert validation["current_machine_observed_oak_log_is_only_material_fallback"] is True
    assert material["current_machine_observed_oak_log_can_be_dug"] is True
    assert material["historical_or_inferred_oak_log_can_be_dug"] is False
    assert validation["missing_table_and_oak_log_fails_closed"] is True
    assert material[
        "no_retained_table_and_no_current_machine_observed_oak_log_status"
    ] == "blocked"
    assert material["blocked_action_count"] == 0
    assert validation["full_think_fallback_suppressed"] == (
        execution["full_think_fallback_suppressed"]
    ) is True
    assert execution["suppressed_execution_paths"] == [
        "learned_skill",
        "bm012_machine_step",
        "llm_plan",
        "rule_plan",
        "visual_action_grounding",
    ]

    assert validation["bm012_generic_place_behavior_unchanged"] == (
        isolation["bm012_generic_crafting_table_behavior_unchanged"]
    ) is True
    assert validation["probe53_crafting_table_snapshot_policy_unchanged"] == (
        isolation["probe_53_crafting_table_local_snapshot_policy_unchanged"]
    ) is True
    assert validation["furnace_policy_unchanged"] == (
        isolation["furnace_local_snapshot_policy_unchanged"]
    ) is True
    assert validation[
        "protocol_task_deadline_retry_provider_skill_and_smelt_controls_unchanged"
    ] is True
    assert controls == {
        "protocol": True,
        "task_contract": True,
        "deadline_s": 300,
        "model": "grok-4.5",
        "skill_execution_mode": "off",
        "smelt_physics": True,
        "success_threshold": 3,
        "planner_same_call_retry_count": 0,
        "client_retry_count": 0,
        "proxy_retry_count": 0,
        "provider_transport_policy": "single-attempt",
    }


def test_probe55_authorization_is_unconsumed_one_use_and_strictly_bounded():
    authorization = _json(AUTHORIZATION_PATH)

    assert authorization["authorized"] is True
    assert authorization["one_use"] is True
    assert authorization["maximum_episode_count"] == 1
    assert authorization["maximum_retry_count"] == 0
    assert authorization["client_max_retries"] == 0
    assert authorization["proxy_max_retries"] == 0
    assert authorization["fresh_level_required"] is True
    assert authorization["fixed_runtime_limits_required"] is True
    assert authorization["credential_provider_preflight_required"] is True
    assert authorization["credential_provider_preflight_before_minecraft"] is True
    assert authorization["skill_execution_mode"] == "off"
    assert authorization[
        "counts_toward_capability_before_independent_verification"
    ] is False
    assert authorization["consumed"] is False
    assert authorization["next_authorization"] is False
    assert authorization["probe_56_authorized"] is False

    forbidden_exact = {
        "authorization_commit",
        "authorization_tree",
        "probe_55_authorized",
        "probe_55_episode_id",
        "probe_55_session_id",
        "probe_55_level_name",
        "consumed_by_episode",
        "consumed_session_id",
        "consumed_level_name",
        "consumed_at",
        "consumed_at_utc",
        "consumed_monotonic_s",
        "consumed_event_line",
        "consumed_evidence_dir",
        "consumed_report_path",
    }
    assert forbidden_exact.isdisjoint(authorization)
    assert not any(
        key.startswith("probe_56_") and key != "probe_56_authorized"
        for key in authorization
    )
    assert not any(
        key.startswith("consumed_")
        for key in authorization
    )
