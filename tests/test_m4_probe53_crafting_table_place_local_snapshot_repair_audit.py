"""Bind the Probe 53 owned-table placement repair to retained evidence."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from singularity.action.verifier import ActionVerifier
from singularity.core.agent import (
    M4_BM013_BM014_CRAFTING_TABLE_PLACE_LOCAL_SNAPSHOT_KEY,
    M4_BM013_BM014_CRAFTING_TABLE_PLACE_LOCAL_SNAPSHOT_POLICY_ID,
    M4_BM013_BM014_FURNACE_PLACE_LOCAL_SNAPSHOT_POLICY_ID,
)


ROOT = Path(__file__).resolve().parents[1]
AUDIT_RELATIVE = (
    "workspace/evals/"
    "m4_probe53_crafting_table_place_local_snapshot_repair_audit.json"
)
AUDIT_PATH = ROOT / AUDIT_RELATIVE
REPORT_PATH = ROOT / "workspace/evals/m4_probe53_report.json"
AUTHORIZATION_PATH = ROOT / "workspace/evals/m4_probe53_authorization.json"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_blob(commit: str, relative_path: str) -> bytes:
    return subprocess.check_output(
        ["git", "show", f"{commit}:{Path(relative_path).as_posix()}"],
        cwd=ROOT,
    )


def _origin_commit() -> str:
    """Return the commit that first retained this audit, if it exists yet."""
    output = subprocess.check_output(
        [
            "git",
            "log",
            "--diff-filter=A",
            "--format=%H",
            "--",
            AUDIT_RELATIVE,
        ],
        cwd=ROOT,
        text=True,
    )
    commits = [line.strip() for line in output.splitlines() if line.strip()]
    return commits[-1] if commits else ""


def test_probe53_table_repair_audit_binds_report_auth_and_raw_evidence():
    audit = _json(AUDIT_PATH)
    report = _json(REPORT_PATH)
    authorization = _json(AUTHORIZATION_PATH)
    bindings = audit["bindings"]

    assert audit["type"] == (
        "m4_probe53_crafting_table_place_local_snapshot_repair_audit"
    )
    assert audit["profile"] == "m4-fixed-v1"
    assert audit["task_id"] == "BM-014"
    assert audit["counts_toward_bm014_success"] is False
    assert audit["counts_toward_capability"] is False

    assert bindings["probe_53_report_path"] == (
        REPORT_PATH.relative_to(ROOT).as_posix()
    )
    assert report["episode_id"] == bindings["probe_53_episode_id"]
    assert report["session_id"] == bindings["probe_53_session_id"]
    assert report["level_name"] == bindings["probe_53_level_name"]

    assert authorization["consumed"] is True
    assert authorization["consumed_by_episode"] == report["episode_id"]
    assert authorization["consumed_session_id"] == report["session_id"]
    assert authorization["consumed_level_name"] == report["level_name"]
    assert authorization["consumed_event_line"] == 2
    assert authorization["consumed_monotonic_s"] == 892493.828
    assert authorization["probe_54_authorized"] is False
    assert _sha256(AUTHORIZATION_PATH) == (
        bindings["probe_53_consumed_authorization_sha256"]
    )

    assert bindings["raw_evidence_paths"] == report["evidence_paths"]
    assert bindings["raw_evidence_sha256"] == report["evidence_sha256"]
    for key, relative_path in bindings["raw_evidence_paths"].items():
        assert _sha256(ROOT / relative_path) == (
            bindings["raw_evidence_sha256"][key]
        )


def test_probe53_table_repair_audit_binds_the_repair_source_transaction():
    audit = _json(AUDIT_PATH)
    origin_commit = _origin_commit()

    for key, relative_path in audit["source_paths"].items():
        if origin_commit:
            actual = hashlib.sha256(
                _git_blob(origin_commit, relative_path)
            ).hexdigest()
        else:
            actual = _sha256(ROOT / relative_path)
        assert actual == audit["source_sha256"][key]

    repair = audit["offline_repair"]
    assert repair["policy_id"] == (
        M4_BM013_BM014_CRAFTING_TABLE_PLACE_LOCAL_SNAPSHOT_POLICY_ID
    )
    assert repair["snapshot_key"] == (
        M4_BM013_BM014_CRAFTING_TABLE_PLACE_LOCAL_SNAPSHOT_KEY
    )
    assert repair["policy_isolation"]["furnace_policy_id_unchanged"] == (
        M4_BM013_BM014_FURNACE_PLACE_LOCAL_SNAPSHOT_POLICY_ID
    )
    assert ActionVerifier.M4_CRAFTING_TABLE_PLACE_LOCAL_SNAPSHOT_POLICY_ID == (
        repair["policy_id"]
    )
    assert ActionVerifier.M4_CRAFTING_TABLE_PLACE_LOCAL_SNAPSHOT_KEY == (
        repair["snapshot_key"]
    )


def test_probe53_table_repair_is_complete_bounded_and_fail_closed():
    audit = _json(AUDIT_PATH)
    repair = audit["offline_repair"]
    snapshot = repair["complete_snapshot"]
    candidates = repair["candidate_derivation"]
    verifier = repair["action_verifier"]
    execution = repair["execution_path_gates"]
    isolation = repair["policy_isolation"]

    assert snapshot["source"] == "get_shelter_state.blocks"
    assert snapshot["required_position_count"] == 36
    assert snapshot["candidate_limit"] == 27
    assert snapshot["maximum_snapshot_age_ms"] == 5000
    assert snapshot["machine_snapshot_passed_required"] is True
    assert snapshot["snapshot_and_current_player_same_cell_required"] is True
    assert snapshot["duplicate_position_rejected"] is True
    assert snapshot["malformed_position_rejected"] is True

    assert candidates["same_snapshot_solid_reference_required"] is True
    assert candidates["same_snapshot_replaceable_target_above_required"] is True
    assert candidates["exact_integral_reference_target_pair_required"] is True
    assert (
        candidates[
            "target_outside_snapshot_and_current_player_collision_union_required"
        ]
        is True
    )
    assert candidates["failed_reference_and_target_feedback_excluded"] is True
    assert candidates["feedback_isolated_by_item"] is True
    assert candidates["speculative_nearby_blocks_fallback"] is False

    assert verifier["task_scope"] == ["BM-013", "BM-014"]
    assert verifier["applies_to_every_crafting_table_place_in_scope"] is True
    assert verifier["independent_snapshot_key_hard_required"] is True
    assert verifier["independent_policy_id_hard_required"] is True
    assert verifier["furnace_envelope_cannot_authorize_table"] is True
    assert verifier["table_envelope_cannot_authorize_furnace"] is True
    assert verifier["exact_snapshot_pair_hard_required"] is True
    assert verifier["target_evidence_after_repair"] == "target:air"
    assert verifier["target_not_observed_occupied_acceptance_possible"] is False
    assert verifier["visible_unrelated_table_bypass_possible"] is False

    assert execution["missing_candidate_plan_status"] == "blocked"
    assert execution["missing_candidate_action_count"] == 0
    assert execution["full_think_fallback_suppressed"] is True
    assert execution["suppressed_execution_paths"] == [
        "learned_skill",
        "bm012_machine_step",
        "llm_plan",
        "rule_plan",
        "visual_action_grounding",
    ]
    assert isolation["bm012_generic_crafting_table_place_behavior_unchanged"] is True
    assert isolation["bm012_generic_furnace_place_behavior_unchanged"] is True
    assert isolation["furnace_preferred_crafting_table_reference_unchanged"] is True


def test_probe53_table_repair_preserves_controls_and_locks_probe54():
    audit = _json(AUDIT_PATH)
    blocker = audit["blocker_before_repair"]
    validation = audit["offline_validation"]
    controls = audit["offline_repair"]["unchanged_controls"]
    decision = audit["decision"]

    assert blocker["capability_failure"] is True
    assert blocker["infrastructure_failure"] is False
    assert blocker["occupied_stone_crafting_table_place_failure_count"] == 24
    assert len(blocker["occupied_stone_failure_lines"]) == 24
    assert blocker["termination_reason"] == "episode_deadline"
    assert blocker["smelt_budget_at_action_start_s"] == 3.453
    assert blocker["smelt_feasible_in_remaining_budget"] is False

    assert validation["focused_python_pass_count"] == 21
    assert validation["focused_python_fail_count"] == 0
    assert validation["independent_review_pass_count"] == 55
    assert validation["independent_review_fail_count"] == 0
    assert validation["full_m4_python_pass_count"] == 276
    assert validation["full_m4_python_fail_count"] == 0
    assert validation["historical_binding_regression_pass_count"] == 46
    assert validation["python_compile_source_file_count"] == 3
    assert validation["python_compile_passed"] is True
    assert validation["git_diff_check_passed"] is True

    assert controls["protocol"] is True
    assert controls["task_contract"] is True
    assert controls["deadline_s"] == 300
    assert controls["model"] == "grok-4.5"
    assert controls["planner_attempt_count"] == 1
    assert controls["planner_retry_count"] == 0
    assert controls["client_retry_count"] == 0
    assert controls["proxy_retry_count"] == 0
    assert controls["smelt_physics"] is True
    assert controls["success_threshold"] == 3
    assert controls["skill_execution_mode"] == "off"

    assert decision["repair_claimed_complete_offline"] is True
    assert decision["live_validation_complete"] is False
    assert decision["counts_toward_bm014_success"] is False
    assert decision["counts_toward_capability"] is False
    assert decision["bm014_attempt_count"] == 3
    assert decision["bm014_failure_count"] == 2
    assert decision["bm014_eligible_success_count"] == 1
    assert decision["remaining_success_count"] == 2
    assert decision["bm014_status"] == "live_observed"
    assert decision["m4_status"] == "live_observed"
    assert decision["probe_54_authorized"] is False
