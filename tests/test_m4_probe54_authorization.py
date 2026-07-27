"""Bind the one-use Probe 54 authorization to the pushed Probe 53 gate."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUTHORIZATION_PATH = ROOT / "workspace/evals/m4_probe54_authorization.json"
GATE_PARENT_COMMIT = "cf888555f080bd82b6a893c50494ca05b38a1688"
GATE_TREE = "a711e9962f0153208f565d95aaf473caf2ece22d"


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


def test_probe54_authorization_binds_pushed_gate_and_fixed_contract():
    authorization = _json(AUTHORIZATION_PATH)
    assert authorization["type"] == "m4_live_probe_authorization"
    assert authorization["schema_version"] == 1
    assert authorization["profile"] == "m4-fixed-v1"
    assert authorization["task_id"] == "BM-014"
    assert authorization["probe_number"] == 54
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
    assert _git_revision(f"{GATE_PARENT_COMMIT}^{{tree}}") == GATE_TREE
    assert authorization["policy_id"] == (
        "m4-bm013-bm014-crafting-table-place-local-snapshot-v1"
    )
    assert authorization["gate_remote_readback"] == {
        "commit_parent_verified": True,
        "tree_verified": True,
        "expected_blob_count": 19,
        "blob_mismatch_count": 0,
    }
    assert authorization["gate_clean_validation"] == {
        "m4_python_pass_count": 279,
        "m4_python_fail_count": 0,
        "capability_action_python_pass_count": 38,
        "capability_action_python_fail_count": 0,
    }


def test_probe54_authorization_freezes_all_gate_dependencies():
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
        ("portability_audit_path", "portability_audit_sha256"),
        ("portability_audit_test_path", "portability_audit_test_sha256"),
    )
    for path_key, hash_key in path_hash_pairs:
        assert authorization[hash_key] == _git_sha256(
            GATE_PARENT_COMMIT,
            authorization[path_key],
        )

    assert set(authorization["repair_source_paths"]) == {
        "agent",
        "action_verifier",
        "agent_tests",
    }
    for key, relative_path in authorization["repair_source_paths"].items():
        assert authorization["repair_source_sha256"][key] == _git_sha256(
            GATE_PARENT_COMMIT,
            relative_path,
        )


def test_probe54_authorization_binds_probe53_failure_repair_and_counts():
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
        "capability_scheduling_failure"
    )
    assert report["failure_analysis"]["infrastructure_failure"] is False
    assert report["failure_analysis"]["counts_as_bm014_attempt"] is True
    assert report["failure_analysis"]["counts_as_bm014_failure"] is True
    assert report["decision"]["bm014_attempt_count_after"] == 3
    assert report["decision"]["bm014_failure_count_after"] == 2
    assert report["decision"]["bm014_success_count_after"] == 1
    assert report["decision"]["remaining_success_count"] == 2
    assert report["decision"]["probe_54_authorized"] is False

    assert consumed["probe_number"] == 53
    assert consumed["consumed"] is True
    assert consumed["consumed_by_episode"] == report["episode_id"]
    assert consumed["consumed_session_id"] == report["session_id"]
    assert consumed["consumed_level_name"] == report["level_name"]
    assert consumed["next_authorization"] is False
    assert consumed["probe_54_authorized"] is False

    assert repair["classification"] == "offline_capability_failure_remediation"
    assert repair["offline_repair"]["status"] == "completed"
    assert repair["offline_repair"]["policy_id"] == authorization["policy_id"]
    assert repair["offline_repair"]["snapshot_key"] == (
        "m4_crafting_table_place_candidates"
    )
    assert repair["decision"]["repair_claimed_complete_offline"] is True
    assert repair["decision"]["live_validation_complete"] is False
    assert repair["decision"]["counts_toward_bm014_success"] is False
    assert repair["decision"]["counts_toward_capability"] is False
    assert repair["decision"]["probe_54_authorized"] is False

    assert bm014["attempts"] == authorization["prior_bm014_attempt_count"] == 3
    assert bm014["failures"] == authorization["prior_bm014_failure_count"] == 2
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
    assert ledger["live_episode_count_under_current_protocol"] == 29
    assert gate["bm014_probe_53_consumed"] is True
    assert gate["bm014_probe_53_eligible"] is False
    assert gate["bm014_probe_53_counts_toward_success"] is False
    assert gate["bm014_probe_53_crafting_table_repair_complete_offline"] is True
    assert gate["bm014_probe_54_authorized"] is False
    assert gate["bm014_attempt_count"] == 3
    assert gate["bm014_failure_count"] == 2
    assert gate["bm014_success_count"] == 1
    assert gate["bm014_status"] == gate["m4_status"] == "live_observed"


def test_probe54_authorization_binds_repair_boundaries_and_portability():
    authorization = _json(AUTHORIZATION_PATH)
    repair = _git_json(
        GATE_PARENT_COMMIT,
        authorization["repair_audit_path"],
    )
    portability = _git_json(
        GATE_PARENT_COMMIT,
        authorization["portability_audit_path"],
    )
    validation = authorization["repair_validation"]
    audit_validation = repair["offline_validation"]

    assert validation["focused_python_pass_count"] == (
        audit_validation["focused_python_pass_count"]
    ) == 21
    assert validation["independent_review_pass_count"] == (
        audit_validation["independent_review_pass_count"]
    ) == 55
    assert validation["full_m4_python_pass_count"] == (
        audit_validation["full_m4_python_pass_count"]
    ) == 276
    assert validation["historical_binding_regression_pass_count"] == (
        audit_validation["historical_binding_regression_pass_count"]
    ) == 46
    assert validation["complete_snapshot_required"] is True
    assert validation["exact_reference_target_pair_required"] is True
    assert validation["snapshot_and_current_player_collision_union_required"] is True
    assert validation["full_think_fallback_suppressed"] is True
    assert validation["bm012_control_unchanged"] is True
    assert validation["furnace_policy_unchanged"] is True

    offline = repair["offline_repair"]
    assert offline["complete_snapshot"]["required_position_count"] == 36
    assert offline["complete_snapshot"]["candidate_limit"] == 27
    assert offline["complete_snapshot"]["maximum_snapshot_age_ms"] == 5000
    assert offline["candidate_derivation"][
        "exact_integral_reference_target_pair_required"
    ] is True
    assert offline["candidate_derivation"][
        "target_outside_snapshot_and_current_player_collision_union_required"
    ] is True
    assert offline["action_verifier"]["applies_to_every_crafting_table_place_in_scope"] is True
    assert offline["action_verifier"]["visible_unrelated_table_bypass_possible"] is False
    assert offline["execution_path_gates"]["missing_candidate_action_count"] == 0
    assert offline["execution_path_gates"]["full_think_fallback_suppressed"] is True
    assert offline["policy_isolation"][
        "bm012_generic_crafting_table_place_behavior_unchanged"
    ] is True

    assert portability["classification"] == (
        "offline_evidence_portability_remediation"
    )
    assert portability["counts_toward_bm014_success"] is False
    assert portability["counts_toward_capability"] is False
    assert portability["parent_binding"]["commit"] == _git_revision(
        f"{GATE_PARENT_COMMIT}^"
    )
    assert portability["parent_binding"]["tree"] == _git_revision(
        f"{GATE_PARENT_COMMIT}^^{{tree}}"
    )
    survey = portability["parent_clean_checkout_survey"]
    assert survey["report_bound_raw_file_count"] == 240
    assert survey["missing_file_count"] == 40
    assert survey["missing_episode_count"] == 4
    assert survey["partition_complete"] is True
    remediation = portability["remediation"]
    assert remediation["archive_count"] == 4
    assert remediation["archived_regular_file_count"] == 40
    assert remediation["files_per_archive"] == 10
    assert remediation["expected_portable_report_binding_count"] == 240
    assert portability["decision"]["portability_repair_complete_offline"] is True
    assert portability["decision"]["probe_54_authorized"] is False

    bound_archives = authorization["portability_archives"]
    audit_archives = remediation["archives"]
    assert len(bound_archives) == len(audit_archives) == 4
    for bound, audited in zip(bound_archives, audit_archives, strict=True):
        assert bound["probe_number"] == audited["probe_number"]
        assert bound["episode_id"] == audited["episode_id"]
        assert bound["path"] == audited["archive_path"]
        assert bound["sha256"] == audited["archive_sha256"]
        assert bound["sha256"] == _git_sha256(
            GATE_PARENT_COMMIT,
            bound["path"],
        )
        assert audited["regular_file_member_count"] == 10


def test_probe54_authorization_is_unconsumed_and_has_strict_negative_boundaries():
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
    assert authorization["probe_55_authorized"] is False

    forbidden_exact = {
        "probe_54_authorized",
        "authorization_commit",
        "authorization_tree",
    }
    assert forbidden_exact.isdisjoint(authorization)
    assert not any(key.startswith("consumed_") for key in authorization)
