"""Fail-closed paired evaluation for the SP-001 learned skill.

The base stone-pickaxe protocol and retained SP-001 episodes stay immutable.
This module binds one advisory skill to one supplemental policy, adapts the
three retained skill-off successes as baseline arms, and produces promotion
review evidence without granting normal runtime or capability authority.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import replace
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from singularity.core.config import Config
from singularity.core.skill_learning import (
    EVALUATION_AUTHORIZATION_TYPE,
    EXECUTABLE_PROMOTION_GATE_TYPE,
    evaluation_authorization_issues,
    executable_promotion_gate_issues,
)
from singularity.evaluation.stone_pickaxe_protocol import (
    PROTOCOL,
    PROTOCOL_SHA256,
    REPOSITORY_ROOT,
)
from singularity.evaluation.stone_pickaxe_runtime import (
    ACTION_GUARD_POLICY_ID,
    RUNTIME_POLICY_ID,
    SP001_GOAL,
    StonePickaxeRuntimeAgent,
    build_runtime_config,
    build_sp001_episode,
    file_sha256,
    read_json,
    repo_relative,
    utc_now,
)


POLICY_RELATIVE_PATH = "workspace/evals/stone_pickaxe_paired_evaluation_policy.json"
POLICY_PATH = REPOSITORY_ROOT / POLICY_RELATIVE_PATH
POLICY = read_json(POLICY_PATH)
POLICY_SHA256 = file_sha256(POLICY_PATH)
RUN_TYPE = "stone_pickaxe_skill_evaluation_run"
REPORT_TYPE = "stone_pickaxe_skill_paired_evaluation"
AUTHORIZATION_ROOT = REPOSITORY_ROOT / "workspace/evals/sp001_skill_evaluation_runs"


def canonical_record_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()


def policy_identity_report(policy: dict | None = None) -> dict:
    value = policy if isinstance(policy, dict) else POLICY
    issues: list[str] = []
    base = value.get("base_protocol", {}) if isinstance(value.get("base_protocol"), dict) else {}
    fixture_spec = value.get("fixture", {}) if isinstance(value.get("fixture"), dict) else {}
    skill_spec = value.get("target_skill", {}) if isinstance(value.get("target_skill"), dict) else {}
    implementation = value.get("implementation", {}) if isinstance(value.get("implementation"), dict) else {}

    _check(issues, "policy_type", value.get("type") == "stone_pickaxe_paired_evaluation_policy")
    _check(issues, "policy_schema", value.get("schema_version") == 1)
    _check(issues, "policy_task", value.get("task_id") == "SP-001")
    _check(issues, "base_protocol_id", base.get("id") == PROTOCOL["id"])
    _check(issues, "base_protocol_declared_hash", base.get("sha256") == PROTOCOL_SHA256)
    _check_file(issues, "base_protocol_file", base.get("path"), base.get("sha256"))
    _check_file(
        issues,
        "fixture_manifest_file",
        fixture_spec.get("path"),
        fixture_spec.get("manifest_sha256"),
    )
    fixture = _read_repository_json(fixture_spec.get("path"), issues, "fixture_manifest")
    _check(issues, "fixture_id", fixture.get("fixture_id") == fixture_spec.get("id"))
    _check(
        issues,
        "fixture_protocol",
        fixture.get("protocol_sha256") == PROTOCOL_SHA256,
    )
    snapshot = fixture.get("snapshot", {}) if isinstance(fixture.get("snapshot"), dict) else {}
    _check(
        issues,
        "fixture_tree",
        snapshot.get("tree_sha256") == fixture_spec.get("tree_sha256"),
    )
    _check(issues, "fixture_verified", fixture.get("snapshot_identity_verified") is True)

    _check_file(
        issues,
        "promotion_file",
        skill_spec.get("promotion_path"),
        skill_spec.get("promotion_sha256"),
    )
    promotion = _read_repository_json(skill_spec.get("promotion_path"), issues, "promotion")
    _check(issues, "promotion_stage", promotion.get("stage") == "advisory")
    _check(issues, "promotion_candidate", promotion.get("candidate_id") == skill_spec.get("candidate_id"))
    _check(issues, "promotion_skill", promotion.get("skill_id") == skill_spec.get("skill_id"))
    _check(issues, "promotion_version", promotion.get("skill_version") == skill_spec.get("version"))
    _check(issues, "promotion_capability_false", promotion.get("counts_toward_capability") is False)
    _check(issues, "promotion_m4_false", promotion.get("counts_toward_m4") is False)

    skill_records = _jsonl_records(skill_spec.get("record_path"), issues, "skill_records")
    exact_skills = [
        record
        for record in skill_records
        if record.get("skill_id") == skill_spec.get("skill_id")
        and record.get("version") == skill_spec.get("version")
    ]
    _check(issues, "exact_skill_record_count", len(exact_skills) == 1)
    skill = exact_skills[0] if len(exact_skills) == 1 else {}
    _check(issues, "skill_name", skill.get("name") == skill_spec.get("name"))
    _check(issues, "skill_status", skill.get("status") == skill_spec.get("required_status"))
    _check(issues, "skill_family", skill.get("task_family") == skill_spec.get("task_family"))
    _check(
        issues,
        "skill_record_hash",
        bool(skill) and canonical_record_sha256(skill) == skill_spec.get("record_canonical_sha256"),
    )
    skill_gate = skill.get("gate", {}) if isinstance(skill.get("gate"), dict) else {}
    _check(
        issues,
        "skill_executable_gate_absent",
        not skill_gate.get("executable_promotion"),
    )

    queue_records = _jsonl_records(skill_spec.get("queue_path"), issues, "candidate_queue")
    candidates = [record for record in queue_records if record.get("id") == skill_spec.get("candidate_id")]
    _check(issues, "candidate_queue_record_count", len(candidates) == 1)
    candidate = candidates[0] if len(candidates) == 1 else {}
    _check(issues, "candidate_skill", candidate.get("skill_id") == skill_spec.get("skill_id"))
    _check(issues, "candidate_version", candidate.get("version") == skill_spec.get("version"))
    _check(issues, "candidate_status", candidate.get("status") == "advisory")
    _check(issues, "candidate_review", candidate.get("review_status") == "approved")
    _check(
        issues,
        "candidate_queue_hash",
        bool(candidate)
        and canonical_record_sha256(candidate) == skill_spec.get("queue_record_canonical_sha256"),
    )
    for label, raw_record in sorted(implementation.items()):
        record = raw_record if isinstance(raw_record, dict) else {}
        _check_implementation_file(
            issues,
            f"implementation_{label}",
            record.get("path"),
            record.get("sha256"),
        )

    baseline_sessions = []
    baseline_episodes = []
    for binding in value.get("pair_bindings", []) if isinstance(value.get("pair_bindings"), list) else []:
        prefix = str(binding.get("replicate_id") or "missing")
        for label in ("episode", "verification", "manifest", "session"):
            _check_file(
                issues,
                f"baseline_{prefix}_{label}",
                binding.get(f"{label}_path"),
                binding.get(f"{label}_sha256"),
            )
        episode = _read_repository_json(binding.get("episode_path"), issues, f"baseline_{prefix}_episode")
        verification = _read_repository_json(
            binding.get("verification_path"), issues, f"baseline_{prefix}_verification"
        )
        manifest = _read_repository_json(binding.get("manifest_path"), issues, f"baseline_{prefix}_manifest")
        baseline_sessions.append(str(episode.get("session_id") or ""))
        baseline_episodes.append(str(episode.get("episode_id") or ""))
        _check(issues, f"baseline_{prefix}_episode_id", episode.get("episode_id") == binding.get("baseline_episode_id"))
        _check(issues, f"baseline_{prefix}_session_id", episode.get("session_id") == binding.get("baseline_session_id"))
        _check(issues, f"baseline_{prefix}_protocol", episode.get("protocol_sha256") == PROTOCOL_SHA256)
        _check(issues, f"baseline_{prefix}_selected_skills", episode.get("selected_skills") == [])
        _check(issues, f"baseline_{prefix}_verification", verification.get("passed") is True)
        _check(issues, f"baseline_{prefix}_manifest", manifest.get("passed") is True)
    _check(issues, "three_pair_bindings", len(baseline_sessions) == 3)
    _check(issues, "baseline_sessions_distinct", len(set(baseline_sessions)) == 3)
    _check(issues, "baseline_episodes_distinct", len(set(baseline_episodes)) == 3)

    fixed = value.get("fixed_controls", {}) if isinstance(value.get("fixed_controls"), dict) else {}
    task = next(item for item in PROTOCOL["tasks"] if item["id"] == "SP-001")
    _check(issues, "fixed_goal", fixed.get("goal") == SP001_GOAL)
    _check(issues, "fixed_episode_timeout", fixed.get("episode_timeout_s") == task["episode_timeout_s"])
    _check(issues, "fixed_maximum_cycles", fixed.get("maximum_cycles") == task["maximum_cycles"])
    _check(issues, "fixed_maximum_actions", fixed.get("maximum_actions") == task["maximum_actions"])
    _check(issues, "fixed_action_timeout", fixed.get("per_action_timeout_s") == PROTOCOL["deadline_policy"]["per_action_timeout_s"])
    _check(issues, "fixed_deadline", fixed.get("deadline_policy_id") == PROTOCOL["deadline_policy"]["id"])
    _check(issues, "fixed_runtime_policy", fixed.get("runtime_policy_id") == RUNTIME_POLICY_ID)
    _check(issues, "fixed_action_guard", fixed.get("action_guard_policy_id") == ACTION_GUARD_POLICY_ID)
    return {
        "type": "stone_pickaxe_paired_policy_identity",
        "schema_version": 1,
        "policy_id": value.get("id", ""),
        "policy_path": POLICY_RELATIVE_PATH,
        "policy_sha256": POLICY_SHA256 if value is POLICY else canonical_record_sha256(value),
        "passed": not issues,
        "issues": sorted(set(issues)),
        "skill_record_canonical_sha256": canonical_record_sha256(skill) if skill else "",
        "candidate_record_canonical_sha256": canonical_record_sha256(candidate) if candidate else "",
        "baseline_session_ids": baseline_sessions,
        "baseline_episode_ids": baseline_episodes,
        "counts_toward_capability": False,
        "counts_toward_m4": False,
    }


def build_evaluation_authorization(
    *,
    arm: str,
    replicate_id: str,
    episode_id: str,
    git_head: str,
    existing_run_paths: Iterable[str | Path] | None = None,
) -> dict:
    normalized_arm = str(arm or "").strip().lower()
    normalized_replicate = str(replicate_id or "").strip().lower()
    normalized_episode = str(episode_id or "").strip()
    identity = policy_identity_report()
    if not identity["passed"]:
        raise ValueError(f"paired evaluation policy identity failed: {identity['issues']}")
    spec = arm_spec(normalized_arm)
    if normalized_replicate not in spec.get("replicate_ids", []):
        raise ValueError(f"replicate {normalized_replicate!r} is not allowed for arm {normalized_arm!r}")
    if not normalized_episode:
        raise ValueError("episode_id is required")
    if len(str(git_head or "")) != 40 or any(character not in "0123456789abcdef" for character in str(git_head).lower()):
        raise ValueError("a full lowercase git commit is required")
    duplicates = _duplicate_run_ids(normalized_arm, normalized_replicate, existing_run_paths)
    if duplicates:
        raise ValueError(f"arm/replicate already consumed: {duplicates}")
    skill = POLICY["target_skill"]
    fixture = POLICY["fixture"]
    binding = pair_binding(normalized_replicate) if normalized_arm == "candidate" else {}
    return {
        "type": EVALUATION_AUTHORIZATION_TYPE,
        "schema_version": 1,
        "authorization_id": f"sp001-eval:{normalized_arm}:{normalized_replicate}:{normalized_episode}",
        "generated_at_utc": utc_now(),
        "allowed": True,
        "single_use": True,
        "created_before_live_process_start": True,
        "episode_id": normalized_episode,
        "experiment_id": normalized_episode,
        "arm": normalized_arm,
        "replicate_id": normalized_replicate,
        "pair_id": str(binding.get("pair_id") or ""),
        "git_head": str(git_head).lower(),
        "policy_id": POLICY["id"],
        "policy_path": POLICY_RELATIVE_PATH,
        "policy_sha256": POLICY_SHA256,
        "task_id": "SP-001",
        "skill_id": skill["skill_id"],
        "skill_name": skill["name"],
        "skill_version": skill["version"],
        "skill_status": skill["required_status"],
        "candidate_id": skill["candidate_id"],
        "skill_record_canonical_sha256": skill["record_canonical_sha256"],
        "promotion_sha256": skill["promotion_sha256"],
        "single_target_skill": True,
        "skill_execution_mode": spec["skill_execution_mode"],
        "direct_skill_execution_allowed": spec["direct_skill_execution_allowed"],
        "action_verifier_enforced": True,
        "action_controller_enforced": True,
        "goal_verifier_enforced": True,
        "reobserve_each_cycle": True,
        "reobserve_each_action": True,
        "fallback_to_agentic_planning": True,
        "world_protocol_sha256": PROTOCOL_SHA256,
        "fixture_tree_sha256": fixture["tree_sha256"],
        "baseline_binding": dict(binding),
        "runtime_scope": "controlled_live_sp001_skill_evaluation_only",
        "normal_runtime_permission": False,
        "automatic_retry_allowed": False,
        "counts_toward_capability": False,
        "counts_toward_m4": False,
    }


def validate_evaluation_authorization(
    authorization: Any,
    *,
    expected_arm: str = "",
    expected_replicate_id: str = "",
    expected_episode_id: str = "",
    expected_git_head: str = "",
) -> dict:
    value = authorization if isinstance(authorization, dict) else {}
    issues = list(
        evaluation_authorization_issues(
            value,
            POLICY["target_skill"]["skill_id"],
            str(value.get("experiment_id") or ""),
        )
    )
    identity = policy_identity_report()
    if not identity["passed"]:
        issues.extend(f"policy:{issue}" for issue in identity["issues"])
    arm = str(value.get("arm") or "").strip().lower()
    replicate = str(value.get("replicate_id") or "").strip().lower()
    try:
        spec = arm_spec(arm)
    except ValueError:
        spec = {}
        issues.append("authorization_arm_invalid")
    _check(issues, "authorization_replicate_invalid", replicate in spec.get("replicate_ids", []))
    _check(issues, "authorization_mode_invalid", value.get("skill_execution_mode") == spec.get("skill_execution_mode"))
    _check(issues, "authorization_direct_execution_invalid", value.get("direct_skill_execution_allowed") is spec.get("direct_skill_execution_allowed"))
    _check(issues, "authorization_policy_id", value.get("policy_id") == POLICY["id"])
    _check(issues, "authorization_policy_path", value.get("policy_path") == POLICY_RELATIVE_PATH)
    _check(issues, "authorization_policy_hash", value.get("policy_sha256") == POLICY_SHA256)
    _check(issues, "authorization_task", value.get("task_id") == "SP-001")
    _check(issues, "authorization_episode_binding", value.get("experiment_id") == value.get("episode_id"))
    _check(issues, "authorization_single_use", value.get("single_use") is True)
    _check(issues, "authorization_pre_live", value.get("created_before_live_process_start") is True)
    _check(issues, "authorization_skill_name", value.get("skill_name") == POLICY["target_skill"]["name"])
    _check(issues, "authorization_skill_version", value.get("skill_version") == POLICY["target_skill"]["version"])
    _check(issues, "authorization_skill_status", value.get("skill_status") == "advisory")
    _check(issues, "authorization_candidate", value.get("candidate_id") == POLICY["target_skill"]["candidate_id"])
    _check(issues, "authorization_skill_hash", value.get("skill_record_canonical_sha256") == POLICY["target_skill"]["record_canonical_sha256"])
    _check(issues, "authorization_promotion_hash", value.get("promotion_sha256") == POLICY["target_skill"]["promotion_sha256"])
    _check(issues, "authorization_fixture", value.get("fixture_tree_sha256") == POLICY["fixture"]["tree_sha256"])
    _check(issues, "authorization_direct_runtime_forbidden", value.get("normal_runtime_permission") is False)
    _check(issues, "authorization_retry_forbidden", value.get("automatic_retry_allowed") is False)
    _check(issues, "authorization_capability_false", value.get("counts_toward_capability") is False)
    _check(issues, "authorization_m4_false", value.get("counts_toward_m4") is False)
    if expected_arm:
        _check(issues, "authorization_expected_arm", arm == str(expected_arm).lower())
    if expected_replicate_id:
        _check(issues, "authorization_expected_replicate", replicate == str(expected_replicate_id).lower())
    if expected_episode_id:
        _check(issues, "authorization_expected_episode", value.get("episode_id") == expected_episode_id)
    if expected_git_head:
        _check(issues, "authorization_expected_git_head", value.get("git_head") == expected_git_head.lower())
    if arm == "candidate":
        expected_binding = pair_binding(replicate)
        _check(issues, "authorization_pair_binding", value.get("baseline_binding") == expected_binding)
        _check(issues, "authorization_pair_id", value.get("pair_id") == expected_binding.get("pair_id"))
    else:
        _check(issues, "authorization_support_pair_empty", value.get("baseline_binding") == {})
        _check(issues, "authorization_support_pair_id_empty", value.get("pair_id") == "")
    return {
        "type": "stone_pickaxe_skill_evaluation_authorization_audit",
        "schema_version": 1,
        "passed": not issues,
        "issues": sorted(set(issues)),
        "arm": arm,
        "replicate_id": replicate,
        "episode_id": str(value.get("episode_id") or ""),
        "policy_sha256": POLICY_SHA256,
        "normal_runtime_permission": False,
        "counts_toward_capability": False,
        "counts_toward_m4": False,
    }


def build_skill_evaluation_runtime_config(
    *,
    authorization: dict,
    api_key: str,
    log_dir: str,
    host: str,
    port: int,
    username: str,
    bridge_host: str,
    bridge_port: int,
) -> Config:
    audit = validate_evaluation_authorization(authorization)
    if not audit["passed"]:
        raise ValueError(f"skill evaluation authorization rejected: {audit['issues']}")
    base = build_runtime_config(
        api_key=api_key,
        log_dir=log_dir,
        host=host,
        port=port,
        username=username,
        bridge_host=bridge_host,
        bridge_port=bridge_port,
    )
    return replace(
        base,
        skill_execution_mode=str(authorization["skill_execution_mode"]),
        target_skill_id=str(authorization["skill_id"]),
        skill_experiment_id=str(authorization["experiment_id"]),
        skill_evaluation_authorization=dict(authorization),
        skill_fault_profile="",
        enable_skill_candidate_extraction=False,
        skill_runtime_default_gate_paths=[],
    )


class StonePickaxeSkillEvaluationAgent(StonePickaxeRuntimeAgent):
    """SP-001 agent whose learned-skill artifacts remain read-only."""

    def __init__(self, config: Config, authorization: dict):
        audit = validate_evaluation_authorization(authorization)
        if not audit["passed"]:
            raise ValueError(f"skill evaluation authorization rejected: {audit['issues']}")
        self.stone_pickaxe_skill_authorization = dict(authorization)
        super().__init__(config, "sp001")
        self.skill_library.persist = False
        self.skill_learning_ledger = None


def build_skill_evaluation_episode(*, authorization: dict, **kwargs: Any) -> dict:
    episode = build_sp001_episode(**kwargs)
    audit = validate_evaluation_authorization(
        authorization,
        expected_episode_id=str(kwargs.get("episode_id") or ""),
    )
    arm = str(authorization.get("arm") or "")
    selected = episode.get("selected_skills", []) if isinstance(episode.get("selected_skills"), list) else []
    expected_skill = POLICY["target_skill"]
    exact_selected = [
        item
        for item in selected
        if isinstance(item, dict)
        and item.get("skill_id") == expected_skill["skill_id"]
        and item.get("version") == expected_skill["version"]
        and item.get("status") == expected_skill["required_status"]
    ]
    selection_allowed = (
        len(selected) == 1 and len(exact_selected) == 1
        if arm == "candidate"
        else len(selected) == 0
    )
    eligibility = dict(episode.get("eligibility", {}) or {})
    eligibility["skill_evaluation_authorization"] = audit["passed"]
    eligibility["skill_arm_selection"] = selection_allowed
    eligibility["passed"] = bool(
        eligibility.get("protocol_match") is True
        and eligibility.get("planner_request_controls") is True
        and eligibility.get("reset_clean") is True
        and eligibility.get("no_forbidden_intervention") is True
        and eligibility.get("no_post_deadline_action") is True
        and audit["passed"]
        and selection_allowed
    )
    episode["eligibility"] = eligibility
    episode["evaluation"] = {
        "policy_id": POLICY["id"],
        "policy_sha256": POLICY_SHA256,
        "authorization_id": authorization.get("authorization_id", ""),
        "authorization_fingerprint": canonical_record_sha256(authorization),
        "arm": arm,
        "replicate_id": authorization.get("replicate_id", ""),
        "pair_id": authorization.get("pair_id", ""),
        "skill_id": authorization.get("skill_id", ""),
        "skill_version": authorization.get("skill_version", ""),
        "normal_runtime_permission": False,
    }
    episode["counts_toward_capability"] = False
    episode["counts_toward_m4"] = False
    return episode


def build_skill_evaluation_run(
    *,
    episode: dict,
    verification: dict,
    events: list[dict],
    authorization: dict,
    source_evidence: list[dict],
    preflight_passed: bool,
) -> dict:
    arm = str(authorization.get("arm") or "")
    metrics = _evaluation_metrics(events, episode, verification)
    authorization_audit = validate_evaluation_authorization(
        authorization,
        expected_arm=arm,
        expected_replicate_id=str(authorization.get("replicate_id") or ""),
        expected_episode_id=str(episode.get("episode_id") or ""),
    )
    policy_audit = policy_identity_report()
    source_integrity = _source_evidence_valid(source_evidence)
    checks = {
        "preflight_passed": preflight_passed is True,
        "authorization_passed": authorization_audit["passed"],
        "policy_identity_passed": policy_audit["passed"],
        "source_evidence_integrity": source_integrity,
        "base_machine_verification_passed": verification.get("passed") is True,
        "base_evidence_eligible": verification.get("evidence_eligible") is True,
        "episode_skill_arm_eligible": episode.get("eligibility", {}).get("skill_arm_selection") is True,
        "no_quarantined_skill": not any(
            isinstance(item, dict) and item.get("status") == "quarantined"
            for item in episode.get("selected_skills", [])
        ),
        "normal_runtime_permission_false": authorization.get("normal_runtime_permission") is False,
        "automatic_retry_forbidden": authorization.get("automatic_retry_allowed") is False,
        "skill_artifact_read_only": (
            policy_audit.get("skill_record_canonical_sha256")
            == POLICY["target_skill"]["record_canonical_sha256"]
        ),
    }
    if arm == "shadow":
        checks.update({
            "shadow_plan_observed": metrics["skill_shadow_plan_count"] >= 1,
            "no_direct_skill_selection": metrics["skill_selected_count"] == 0,
            "no_direct_skill_execution": metrics["skill_executed_count"] == 0,
        })
    elif arm == "advisory":
        checks.update({
            "advisory_hint_observed": metrics["skill_advisory_hint_count"] >= 1,
            "no_direct_skill_selection": metrics["skill_selected_count"] == 0,
            "no_direct_skill_execution": metrics["skill_executed_count"] == 0,
        })
    elif arm == "fallback":
        checks.update({
            "fallback_observed": metrics["skill_fallback_count"] >= 1,
            "advisory_runtime_execution_blocked": metrics["skill_selected_count"] == 0,
            "no_direct_skill_execution": metrics["skill_executed_count"] == 0,
            "ordinary_planner_completed_goal": verification.get("passed") is True,
        })
    elif arm == "candidate":
        checks.update({
            "single_exact_skill_selected": metrics["skill_selected_count"] == 1,
            "skill_executed": metrics["skill_executed_count"] >= 1,
            "skill_completed": metrics["skill_completion_count"] >= 1,
            "candidate_steps_verified": metrics["candidate_steps_verified"] is True,
            "candidate_steps_reobserved": metrics["candidate_steps_reobserved"] is True,
            "exact_skill_context_only": metrics["exact_skill_context_only"] is True,
            "zero_skill_fallback": metrics["skill_fallback_count"] == 0,
            "zero_action_failures": metrics["failed_actions"] == 0,
            "zero_verifier_rejects": metrics["verifier_rejects"] == 0,
            "high_confidence_attribution": metrics["attribution_confidence"] >= 0.9,
        })
    else:
        checks["known_arm"] = False

    controls = fixed_control_profile(episode)
    record = {
        "type": RUN_TYPE,
        "schema_version": 1,
        "policy_id": POLICY["id"],
        "policy_sha256": POLICY_SHA256,
        "protocol_id": PROTOCOL["id"],
        "protocol_sha256": PROTOCOL_SHA256,
        "task_id": "SP-001",
        "run_id": f"{arm}:{episode.get('episode_id', '')}",
        "arm": arm,
        "replicate_id": authorization.get("replicate_id", ""),
        "pair_id": authorization.get("pair_id", ""),
        "episode_id": episode.get("episode_id", ""),
        "session_id": episode.get("session_id", ""),
        "skill_id": authorization.get("skill_id", ""),
        "skill_version": authorization.get("skill_version", ""),
        "candidate_id": authorization.get("candidate_id", ""),
        "status": "pass" if all(checks.values()) else "fail",
        "checks": checks,
        "metrics": metrics,
        "fixed_controls": controls,
        "fixed_controls_fingerprint": canonical_record_sha256(controls),
        "initial_state_fingerprint": initial_state_fingerprint(episode.get("initial_observation", {})),
        "source_evidence": list(source_evidence),
        "authorization_fingerprint": canonical_record_sha256(authorization),
        "evidence_kind": PROTOCOL["evidence_policy"]["live_evidence_kind"],
        "live_minecraft": True,
        "normal_runtime_permission": False,
        "counts_toward_capability": False,
        "counts_toward_m4": False,
        "automatic_retry_allowed": False,
    }
    record["record_payload_sha256"] = _record_payload_sha256(record)
    return record


def build_baseline_index() -> dict:
    records = [_baseline_run_record(binding) for binding in POLICY["pair_bindings"]]
    return {
        "type": "stone_pickaxe_skill_baseline_index",
        "schema_version": 1,
        "policy_id": POLICY["id"],
        "policy_sha256": POLICY_SHA256,
        "task_id": "SP-001",
        "record_count": len(records),
        "all_records_passed": all(record.get("status") == "pass" for record in records),
        "records": records,
        "prior_evidence_mutated": False,
        "counts_toward_capability": False,
        "counts_toward_m4": False,
    }


def build_paired_evaluation_report(run_paths: Iterable[str | Path]) -> dict:
    baseline_index = build_baseline_index()
    baselines = {
        str(record.get("replicate_id") or ""): record
        for record in baseline_index["records"]
    }
    runs: list[dict] = []
    errors: list[str] = []
    for raw_path in run_paths:
        path = Path(raw_path)
        if not path.is_absolute():
            path = REPOSITORY_ROOT / path
        try:
            run = read_json(path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"{repo_relative(path)}:{type(exc).__name__}")
            continue
        integrity = verify_run_record(run)
        if not integrity["passed"]:
            errors.extend(f"{run.get('run_id', repo_relative(path))}:{issue}" for issue in integrity["issues"])
        runs.append(run)

    groups: dict[tuple[str, str], list[dict]] = {}
    for run in runs:
        key = (str(run.get("arm") or ""), str(run.get("replicate_id") or ""))
        groups.setdefault(key, []).append(run)
    for (arm, replicate), values in sorted(groups.items()):
        if len(values) > 1:
            errors.append(f"duplicate_arm_replicate:{arm}:{replicate}")

    pairs = []
    for binding in POLICY["pair_bindings"]:
        replicate = binding["replicate_id"]
        baseline = baselines[replicate]
        candidates = groups.get(("candidate", replicate), [])
        candidate = candidates[0] if len(candidates) == 1 else {}
        controls_match = bool(
            candidate
            and baseline.get("fixed_controls_fingerprint")
            == candidate.get("fixed_controls_fingerprint")
        )
        initial_match = bool(
            candidate
            and baseline.get("initial_state_fingerprint")
            == candidate.get("initial_state_fingerprint")
        )
        pair = {
            "pair_id": binding["pair_id"],
            "replicate_id": replicate,
            "baseline_run_id": baseline.get("run_id", ""),
            "candidate_run_id": candidate.get("run_id", ""),
            "baseline_session_id": baseline.get("session_id", ""),
            "candidate_session_id": candidate.get("session_id", ""),
            "baseline_passed": baseline.get("status") == "pass",
            "candidate_passed": candidate.get("status") == "pass",
            "fixed_controls_match": controls_match,
            "initial_state_match": initial_match,
            "baseline_integrity": verify_run_record(baseline)["passed"],
            "candidate_integrity": bool(candidate) and verify_run_record(candidate)["passed"],
            "baseline_metrics": dict(baseline.get("metrics", {})),
            "candidate_metrics": dict(candidate.get("metrics", {})),
        }
        pair["eligible"] = all((
            pair["baseline_passed"],
            pair["candidate_passed"],
            pair["fixed_controls_match"],
            pair["initial_state_match"],
            pair["baseline_integrity"],
            pair["candidate_integrity"],
        ))
        pairs.append(pair)

    valid_pairs = [pair for pair in pairs if pair["eligible"]]
    aggregate = _aggregate_metrics(valid_pairs)
    baseline_sessions = sorted({pair["baseline_session_id"] for pair in valid_pairs if pair["baseline_session_id"]})
    candidate_sessions = sorted({pair["candidate_session_id"] for pair in valid_pairs if pair["candidate_session_id"]})
    shadow_verified = _support_arm_verified(groups, "shadow", "skill_shadow_plan_count")
    advisory_verified = _support_arm_verified(groups, "advisory", "skill_advisory_hint_count")
    fallback_verified = _support_arm_verified(groups, "fallback", "skill_fallback_count")
    candidate_steps_verified = bool(valid_pairs) and all(
        pair["candidate_metrics"].get("candidate_steps_verified") is True
        for pair in valid_pairs
    )
    candidate_steps_reobserved = bool(valid_pairs) and all(
        pair["candidate_metrics"].get("candidate_steps_reobserved") is True
        for pair in valid_pairs
    )
    no_completion_regression = all(
        int(pair["candidate_passed"]) >= int(pair["baseline_passed"])
        for pair in valid_pairs
    )
    no_action_failure_regression = aggregate["candidate_failed_actions"] <= aggregate["baseline_failed_actions"]
    no_verifier_regression = aggregate["candidate_verifier_rejects"] <= aggregate["baseline_verifier_rejects"]
    no_no_progress_regression = aggregate["candidate_no_progress_loops"] <= aggregate["baseline_no_progress_loops"]
    minimum_evidence = bool(
        len(valid_pairs) == 3
        and len(baseline_sessions) == 3
        and len(candidate_sessions) == 3
        and not set(baseline_sessions).intersection(candidate_sessions)
    )
    fixed_controls_match = len(valid_pairs) == 3
    promotable = all((
        not errors,
        minimum_evidence,
        shadow_verified,
        advisory_verified,
        fallback_verified,
        fixed_controls_match,
        candidate_steps_verified,
        candidate_steps_reobserved,
        no_completion_regression,
        no_action_failure_regression,
        no_verifier_regression,
        no_no_progress_regression,
    ))
    report = {
        "type": REPORT_TYPE,
        "schema_version": 1,
        "policy_id": POLICY["id"],
        "policy_sha256": POLICY_SHA256,
        "protocol_id": PROTOCOL["id"],
        "protocol_sha256": PROTOCOL_SHA256,
        "task_id": "SP-001",
        "skill_id": POLICY["target_skill"]["skill_id"],
        "evaluated_skill_version": POLICY["target_skill"]["version"],
        "candidate_id": POLICY["target_skill"]["candidate_id"],
        "pair_count": len(pairs),
        "valid_pair_count": len(valid_pairs),
        "baseline_session_ids": baseline_sessions,
        "candidate_session_ids": candidate_sessions,
        "shadow_verified": shadow_verified,
        "advisory_verified": advisory_verified,
        "fallback_verified": fallback_verified,
        "fixed_controls_match": fixed_controls_match,
        "live_minecraft_only": bool(valid_pairs) and all(
            baselines[pair["replicate_id"]].get("live_minecraft") is True
            and next(
                (
                    run.get("live_minecraft") is True
                    for run in groups.get(("candidate", pair["replicate_id"]), [])
                ),
                False,
            )
            for pair in valid_pairs
        ),
        "candidate_steps_verified": candidate_steps_verified,
        "candidate_steps_reobserved": candidate_steps_reobserved,
        "no_completion_rate_regression": no_completion_regression,
        "no_action_failure_regression": no_action_failure_regression,
        "no_verifier_reject_regression": no_verifier_regression,
        "no_no_progress_regression": no_no_progress_regression,
        "aggregate_metrics": aggregate,
        "decision": "review_executable_new_version" if promotable else "retain_advisory",
        "readiness": "approved" if promotable else "review",
        "pairs": pairs,
        "support_runs": [
            {
                "arm": arm,
                "replicate_id": replicate,
                "run_id": values[0].get("run_id", "") if len(values) == 1 else "",
                "status": values[0].get("status", "missing") if len(values) == 1 else "duplicate" if values else "missing",
            }
            for arm, replicate in (("shadow", "shadow-1"), ("advisory", "advisory-1"), ("fallback", "fallback-1"))
            for values in [groups.get((arm, replicate), [])]
        ],
        "errors": sorted(set(errors)),
        "base_protocol_mutated": False,
        "prior_episode_mutated": False,
        "normal_runtime_permission": False,
        "counts_toward_capability": False,
        "counts_toward_m4": False,
    }
    report["executable_promotion_gate"] = _promotion_gate(report, promotable)
    return report


def verify_run_record(run: Any) -> dict:
    value = run if isinstance(run, dict) else {}
    issues: list[str] = []
    _check(issues, "run_type", value.get("type") == RUN_TYPE)
    _check(issues, "run_schema", value.get("schema_version") == 1)
    _check(issues, "run_policy", value.get("policy_id") == POLICY["id"])
    _check(issues, "run_policy_hash", value.get("policy_sha256") == POLICY_SHA256)
    _check(issues, "run_protocol", value.get("protocol_sha256") == PROTOCOL_SHA256)
    _check(issues, "run_task", value.get("task_id") == "SP-001")
    _check(issues, "run_arm", value.get("arm") in {"baseline", "shadow", "advisory", "fallback", "candidate"})
    _check(issues, "run_episode", bool(str(value.get("episode_id") or "")))
    _check(issues, "run_session", bool(str(value.get("session_id") or "")))
    _check(issues, "run_live", value.get("live_minecraft") is True)
    _check(issues, "run_capability_false", value.get("counts_toward_capability") is False)
    _check(issues, "run_m4_false", value.get("counts_toward_m4") is False)
    _check(issues, "run_retry_false", value.get("automatic_retry_allowed") is False)
    _check(issues, "run_source_integrity", _source_evidence_valid(value.get("source_evidence", [])))
    issues.extend(_run_source_binding_issues(value))
    _check(issues, "run_record_fingerprint", value.get("record_payload_sha256") == _record_payload_sha256(value))
    if value.get("status") == "pass":
        checks = value.get("checks", {}) if isinstance(value.get("checks"), dict) else {}
        _check(issues, "run_pass_checks", bool(checks) and all(checks.values()))
    return {"passed": not issues, "issues": sorted(set(issues))}


def arm_spec(arm: str) -> dict:
    normalized = str(arm or "").strip().lower()
    spec = POLICY.get("arms", {}).get(normalized)
    if not isinstance(spec, dict):
        raise ValueError(f"unsupported evaluation arm: {arm}")
    return spec


def pair_binding(replicate_id: str) -> dict:
    matches = [
        binding
        for binding in POLICY.get("pair_bindings", [])
        if binding.get("replicate_id") == str(replicate_id or "").strip().lower()
    ]
    if len(matches) != 1:
        raise ValueError(f"exactly one baseline binding is required for {replicate_id!r}")
    return dict(matches[0])


def fixed_control_profile(episode: dict) -> dict:
    fixed = POLICY["fixed_controls"]
    fixture = episode.get("fixture", {}) if isinstance(episode.get("fixture"), dict) else {}
    return {
        "protocol_id": PROTOCOL["id"],
        "protocol_sha256": PROTOCOL_SHA256,
        "task_id": "SP-001",
        "goal": SP001_GOAL,
        "fixture_id": fixture.get("fixture_id", ""),
        "fixture_tree_sha256": fixture.get("snapshot_tree_sha256", ""),
        "episode_timeout_s": fixed["episode_timeout_s"],
        "maximum_cycles": fixed["maximum_cycles"],
        "maximum_actions": fixed["maximum_actions"],
        "per_action_timeout_s": fixed["per_action_timeout_s"],
        "deadline_policy_id": fixed["deadline_policy_id"],
        "runtime_policy_id": fixed["runtime_policy_id"],
        "action_guard_policy_id": fixed["action_guard_policy_id"],
        "planner": dict(PROTOCOL["planner"]),
        "environment": dict(PROTOCOL["environment"]),
        "action_verifier_enforced": True,
        "action_controller_enforced": True,
        "goal_verifier_enforced": True,
        "automatic_retry_allowed": False,
    }


def initial_state_fingerprint(observation: Any) -> str:
    value = observation if isinstance(observation, dict) else {}
    blocks = []
    for block in value.get("observed_blocks", []) if isinstance(value.get("observed_blocks"), list) else []:
        if not isinstance(block, dict):
            continue
        blocks.append({
            "source_id": str(block.get("source_id") or ""),
            "name": str(block.get("name") or ""),
            "position": dict(block.get("position") or {}),
            "reachable": block.get("reachable") is True,
        })
    payload = {
        "position": dict(value.get("position") or {}),
        "inventory": dict(value.get("inventory") or {}),
        "health": value.get("health"),
        "hunger": value.get("hunger"),
        "game_mode": value.get("game_mode"),
        "dimension": value.get("dimension"),
        "ground_block": value.get("ground_block"),
        "safe": value.get("safe"),
        "movable": value.get("movable"),
        "observed_blocks": sorted(blocks, key=lambda item: (item["source_id"], item["name"])),
    }
    return canonical_record_sha256(payload)


def discover_evaluation_run_paths(root: str | Path = AUTHORIZATION_ROOT) -> list[Path]:
    path = Path(root)
    if not path.is_absolute():
        path = REPOSITORY_ROOT / path
    if not path.exists():
        return []
    return sorted(path.glob("*/evaluation_run.json"), key=lambda item: item.as_posix())


def discover_evaluation_authorization_paths(
    root: str | Path = AUTHORIZATION_ROOT,
) -> list[Path]:
    path = Path(root)
    if not path.is_absolute():
        path = REPOSITORY_ROOT / path
    if not path.exists():
        return []
    return sorted(path.glob("*/authorization.json"), key=lambda item: item.as_posix())


def _baseline_run_record(binding: dict) -> dict:
    episode = read_json(REPOSITORY_ROOT / binding["episode_path"])
    verification = read_json(REPOSITORY_ROOT / binding["verification_path"])
    events = read_json(REPOSITORY_ROOT / binding["session_path"])
    metrics = _evaluation_metrics(events, episode, verification)
    checks = {
        "retained_episode_hash": file_sha256(REPOSITORY_ROOT / binding["episode_path"]) == binding["episode_sha256"],
        "retained_verification_hash": file_sha256(REPOSITORY_ROOT / binding["verification_path"]) == binding["verification_sha256"],
        "retained_manifest_hash": file_sha256(REPOSITORY_ROOT / binding["manifest_path"]) == binding["manifest_sha256"],
        "retained_session_hash": file_sha256(REPOSITORY_ROOT / binding["session_path"]) == binding["session_sha256"],
        "machine_verification_passed": verification.get("passed") is True,
        "evidence_eligible": verification.get("evidence_eligible") is True,
        "skill_mode_off": episode.get("selected_skills") == [],
        "no_skill_selected": metrics["skill_selected_count"] == 0,
        "no_skill_executed": metrics["skill_executed_count"] == 0,
    }
    controls = fixed_control_profile(episode)
    source_evidence = [
        {"path": binding[f"{label}_path"], "sha256": binding[f"{label}_sha256"]}
        for label in ("episode", "verification", "manifest", "session")
    ]
    record = {
        "type": RUN_TYPE,
        "schema_version": 1,
        "policy_id": POLICY["id"],
        "policy_sha256": POLICY_SHA256,
        "protocol_id": PROTOCOL["id"],
        "protocol_sha256": PROTOCOL_SHA256,
        "task_id": "SP-001",
        "run_id": f"baseline:{episode.get('episode_id', '')}",
        "arm": "baseline",
        "replicate_id": binding["replicate_id"],
        "pair_id": binding["pair_id"],
        "episode_id": episode.get("episode_id", ""),
        "session_id": episode.get("session_id", ""),
        "skill_id": POLICY["target_skill"]["skill_id"],
        "skill_version": POLICY["target_skill"]["version"],
        "candidate_id": POLICY["target_skill"]["candidate_id"],
        "status": "pass" if all(checks.values()) else "fail",
        "checks": checks,
        "metrics": metrics,
        "fixed_controls": controls,
        "fixed_controls_fingerprint": canonical_record_sha256(controls),
        "initial_state_fingerprint": initial_state_fingerprint(episode.get("initial_observation", {})),
        "source_evidence": source_evidence,
        "authorization_fingerprint": "",
        "evidence_kind": PROTOCOL["evidence_policy"]["live_evidence_kind"],
        "live_minecraft": True,
        "normal_runtime_permission": False,
        "counts_toward_capability": False,
        "counts_toward_m4": False,
        "automatic_retry_allowed": False,
    }
    record["record_payload_sha256"] = _record_payload_sha256(record)
    return record


def _evaluation_metrics(events: list[dict], episode: dict, verification: dict) -> dict:
    values = events if isinstance(events, list) else []
    action_events = [event for event in values if isinstance(event, dict) and event.get("type") == "action"]
    skill_actions = []
    for event in action_events:
        data = event.get("data", {}) if isinstance(event.get("data"), dict) else {}
        action = data.get("action", {}) if isinstance(data.get("action"), dict) else {}
        context = action.get("skill_context", {}) if isinstance(action.get("skill_context"), dict) else {}
        if context.get("skill_id"):
            skill_actions.append(data)
    outcomes = [
        event.get("data", {})
        for event in values
        if isinstance(event, dict)
        and event.get("type") == "skill_execution_outcome"
        and isinstance(event.get("data"), dict)
    ]
    outcome = outcomes[-1] if outcomes else {}
    verifier_rejects = sum(
        1
        for event in values
        if isinstance(event, dict)
        and event.get("type") == "action_verification"
        and isinstance(event.get("data"), dict)
        and isinstance(event["data"].get("verification"), dict)
        and event["data"]["verification"].get("status") == "reject"
    )
    steps_verified = bool(skill_actions) and all(
        isinstance(data.get("result"), dict)
        and data["result"].get("success") is True
        and isinstance(data["result"].get("action_verification"), dict)
        and data["result"]["action_verification"].get("status") == "accept"
        for data in skill_actions
    )
    steps_reobserved = bool(skill_actions) and all(
        isinstance(data.get("pre_observation"), dict)
        and isinstance(data.get("post_observation"), dict)
        and canonical_record_sha256(data["pre_observation"])
        != canonical_record_sha256(data["post_observation"])
        for data in skill_actions
    )
    exact = POLICY["target_skill"]
    exact_context = bool(skill_actions) and all(
        data.get("action", {}).get("skill_context", {}).get("skill_id") == exact["skill_id"]
        and data.get("action", {}).get("skill_context", {}).get("version") == exact["version"]
        and data.get("action", {}).get("skill_context", {}).get("status") == exact["required_status"]
        for data in skill_actions
    )
    result = episode.get("goal_result", {}) if isinstance(episode.get("goal_result"), dict) else {}
    return {
        "task_completion": int(verification.get("passed") is True),
        "environment_steps": _safe_int(result.get("cycles")),
        "successful_actions": sum(
            1
            for event in action_events
            if isinstance(event.get("data"), dict)
            and isinstance(event["data"].get("result"), dict)
            and event["data"]["result"].get("success") is True
        ),
        "failed_actions": _safe_int(episode.get("action_failure_count")),
        "verifier_rejects": verifier_rejects,
        "planner_calls": sum(1 for event in values if isinstance(event, dict) and event.get("type") == "llm_planner_call"),
        "no_progress_loops": sum(
            1
            for event in values
            if isinstance(event, dict) and event.get("type") in {"empty_plan", "blocked_plan"}
        ),
        "skill_selected_count": sum(1 for event in values if isinstance(event, dict) and event.get("type") == "skill_selected"),
        "skill_executed_count": len(skill_actions),
        "skill_completion_count": sum(1 for item in outcomes if item.get("success") is True),
        "skill_outcome_count": len(outcomes),
        "skill_fallback_count": sum(1 for event in values if isinstance(event, dict) and event.get("type") == "skill_fallback"),
        "skill_shadow_plan_count": sum(1 for event in values if isinstance(event, dict) and event.get("type") == "skill_shadow_plan"),
        "skill_advisory_hint_count": sum(1 for event in values if isinstance(event, dict) and event.get("type") == "skill_advisory_hint"),
        "candidate_steps_verified": steps_verified,
        "candidate_steps_reobserved": steps_reobserved,
        "exact_skill_context_only": exact_context,
        "attribution_confidence": float(outcome.get("attribution_confidence", 0.0) or 0.0),
    }


def _promotion_gate(report: dict, promotable: bool) -> dict:
    policy_gate = POLICY["promotion_gate"]
    gate = {
        "type": EXECUTABLE_PROMOTION_GATE_TYPE,
        "schema_version": 1,
        "skill_id": POLICY["target_skill"]["skill_id"],
        "skill_version": policy_gate["promoted_version"],
        "promoted_skill_version": policy_gate["promoted_version"],
        "evaluated_skill_version": POLICY["target_skill"]["version"],
        "readiness": "approved" if promotable else "review",
        "decision": "promote_executable" if promotable else "retain_advisory",
        "single_target_skill": True,
        "paired_live_session_count": report["valid_pair_count"],
        "baseline_session_ids": list(report["baseline_session_ids"]),
        "candidate_session_ids": list(report["candidate_session_ids"]),
        "shadow_plan_verified": report["shadow_verified"],
        "advisory_hint_verified": report["advisory_verified"],
        "fixed_controls_match": report["fixed_controls_match"],
        "live_minecraft_only": report["live_minecraft_only"],
        "goal_verifier_enforced": True,
        "action_verifier_enforced": True,
        "action_controller_enforced": True,
        "candidate_steps_reobserved": report["candidate_steps_reobserved"],
        "candidate_steps_verified": report["candidate_steps_verified"],
        "fallback_verified": report["fallback_verified"],
        "no_completion_rate_regression": report["no_completion_rate_regression"],
        "no_action_failure_regression": report["no_action_failure_regression"],
        "no_verifier_reject_regression": report["no_verifier_reject_regression"],
        "no_no_progress_regression": report["no_no_progress_regression"],
        "rollback_path_present": bool(policy_gate["rollback_target"]),
        "rollback_target": policy_gate["rollback_target"],
        "transfer_scope": {
            "task_family": POLICY["target_skill"]["task_family"],
            "source_blocks": ["stone"],
            "target_item": "cobblestone",
            "quantity_range": {"minimum": 1, "default": 3, "maximum": 8},
        },
        "thresholds": {"min_paired_live_sessions": 3},
        "synthetic_evidence_count": 0,
        "normal_runtime_permission": False,
        "counts_toward_capability": False,
        "counts_toward_m4": False,
    }
    gate["validation_issues"] = executable_promotion_gate_issues(
        gate,
        skill_id=POLICY["target_skill"]["skill_id"],
        version=policy_gate["promoted_version"],
    )
    return gate


def _support_arm_verified(groups: dict[tuple[str, str], list[dict]], arm: str, metric: str) -> bool:
    replicate = arm_spec(arm)["replicate_ids"][0]
    runs = groups.get((arm, replicate), [])
    return bool(
        len(runs) == 1
        and runs[0].get("status") == "pass"
        and verify_run_record(runs[0])["passed"]
        and _safe_int(runs[0].get("metrics", {}).get(metric)) >= 1
        and _safe_int(runs[0].get("metrics", {}).get("skill_executed_count")) == 0
    )


def _aggregate_metrics(pairs: list[dict]) -> dict:
    result = {
        "baseline_failed_actions": 0,
        "candidate_failed_actions": 0,
        "baseline_verifier_rejects": 0,
        "candidate_verifier_rejects": 0,
        "baseline_no_progress_loops": 0,
        "candidate_no_progress_loops": 0,
        "baseline_environment_steps": 0,
        "candidate_environment_steps": 0,
        "baseline_planner_calls": 0,
        "candidate_planner_calls": 0,
    }
    for pair in pairs:
        baseline = pair["baseline_metrics"]
        candidate = pair["candidate_metrics"]
        for suffix, key in (
            ("failed_actions", "failed_actions"),
            ("verifier_rejects", "verifier_rejects"),
            ("no_progress_loops", "no_progress_loops"),
            ("environment_steps", "environment_steps"),
            ("planner_calls", "planner_calls"),
        ):
            result[f"baseline_{suffix}"] += _safe_int(baseline.get(key))
            result[f"candidate_{suffix}"] += _safe_int(candidate.get(key))
    result["environment_step_gain"] = result["baseline_environment_steps"] - result["candidate_environment_steps"]
    result["planner_call_gain"] = result["baseline_planner_calls"] - result["candidate_planner_calls"]
    return result


def _duplicate_run_ids(
    arm: str,
    replicate_id: str,
    existing_run_paths: Iterable[str | Path] | None,
) -> list[str]:
    paths = (
        list(existing_run_paths)
        if existing_run_paths is not None
        else discover_evaluation_run_paths() + discover_evaluation_authorization_paths()
    )
    duplicates = []
    for raw_path in paths:
        path = Path(raw_path)
        if not path.is_absolute():
            path = REPOSITORY_ROOT / path
        try:
            run = read_json(path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if run.get("arm") == arm and run.get("replicate_id") == replicate_id:
            duplicates.append(
                str(
                    run.get("run_id")
                    or run.get("authorization_id")
                    or repo_relative(path)
                )
            )
    return sorted(set(duplicates))


def _source_evidence_valid(records: Any) -> bool:
    if not isinstance(records, list) or not records:
        return False
    for record in records:
        if not isinstance(record, dict):
            return False
        path = REPOSITORY_ROOT / str(record.get("path") or "")
        expected = str(record.get("sha256") or "").lower()
        try:
            resolved = path.resolve()
            resolved.relative_to(REPOSITORY_ROOT)
        except (OSError, ValueError):
            return False
        if not resolved.is_file() or len(expected) != 64 or file_sha256(resolved) != expected:
            return False
    return True


def _run_source_binding_issues(run: dict) -> list[str]:
    issues: list[str] = []
    records = run.get("source_evidence", []) if isinstance(run.get("source_evidence"), list) else []
    by_name: dict[str, list[Path]] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        path = (REPOSITORY_ROOT / str(record.get("path") or "")).resolve()
        by_name.setdefault(path.name, []).append(path)
    episode_paths = by_name.get("episode.json", [])
    verification_paths = by_name.get("verification.json", [])
    session_paths = by_name.get("session.json", [])
    _check(issues, "run_source_episode_count", len(episode_paths) == 1)
    _check(issues, "run_source_verification_count", len(verification_paths) == 1)
    _check(issues, "run_source_session_count", len(session_paths) == 1)
    if not (len(episode_paths) == len(verification_paths) == len(session_paths) == 1):
        return issues
    try:
        episode = read_json(episode_paths[0])
        verification = read_json(verification_paths[0])
        events = read_json(session_paths[0])
    except (OSError, ValueError, json.JSONDecodeError):
        issues.append("run_source_payload_unreadable")
        return issues
    _check(issues, "run_source_episode_id", episode.get("episode_id") == run.get("episode_id"))
    _check(issues, "run_source_session_id", episode.get("session_id") == run.get("session_id"))
    _check(issues, "run_source_protocol", episode.get("protocol_sha256") == run.get("protocol_sha256"))
    _check(issues, "run_source_session_hash", episode.get("session_sha256") == file_sha256(session_paths[0]))
    _check(issues, "run_source_verification_task", verification.get("task_id") == "SP-001")
    _check(issues, "run_source_verification_protocol", verification.get("protocol_sha256") == PROTOCOL_SHA256)
    _check(issues, "run_source_metrics", run.get("metrics") == _evaluation_metrics(events, episode, verification))
    controls = fixed_control_profile(episode)
    _check(issues, "run_source_fixed_controls", run.get("fixed_controls") == controls)
    _check(
        issues,
        "run_source_fixed_controls_fingerprint",
        run.get("fixed_controls_fingerprint") == canonical_record_sha256(controls),
    )
    _check(
        issues,
        "run_source_initial_state_fingerprint",
        run.get("initial_state_fingerprint")
        == initial_state_fingerprint(episode.get("initial_observation", {})),
    )
    arm = str(run.get("arm") or "")
    if arm == "baseline":
        binding_matches = [
            binding
            for binding in POLICY["pair_bindings"]
            if binding.get("replicate_id") == run.get("replicate_id")
            and binding.get("episode_path") == repo_relative(episode_paths[0])
            and binding.get("session_path") == repo_relative(session_paths[0])
        ]
        _check(issues, "run_source_baseline_binding", len(binding_matches) == 1)
        _check(issues, "run_source_baseline_no_skill", episode.get("selected_skills") == [])
    else:
        evaluation = episode.get("evaluation", {}) if isinstance(episode.get("evaluation"), dict) else {}
        _check(issues, "run_source_evaluation_arm", evaluation.get("arm") == arm)
        _check(issues, "run_source_evaluation_replicate", evaluation.get("replicate_id") == run.get("replicate_id"))
        _check(issues, "run_source_evaluation_pair", evaluation.get("pair_id") == run.get("pair_id"))
        authorization_paths = by_name.get("authorization.json", [])
        _check(issues, "run_source_authorization_count", len(authorization_paths) == 1)
        if len(authorization_paths) == 1:
            try:
                authorization = read_json(authorization_paths[0])
            except (OSError, ValueError, json.JSONDecodeError):
                issues.append("run_source_authorization_unreadable")
            else:
                audit = validate_evaluation_authorization(
                    authorization,
                    expected_arm=arm,
                    expected_replicate_id=str(run.get("replicate_id") or ""),
                    expected_episode_id=str(run.get("episode_id") or ""),
                )
                _check(issues, "run_source_authorization", audit["passed"])
                _check(
                    issues,
                    "run_source_authorization_fingerprint",
                    run.get("authorization_fingerprint") == canonical_record_sha256(authorization),
                )
    return issues


def _record_payload_sha256(record: dict) -> str:
    payload = dict(record)
    payload.pop("record_payload_sha256", None)
    return canonical_record_sha256(payload)


def _jsonl_records(path: Any, issues: list[str], label: str) -> list[dict]:
    try:
        target = (REPOSITORY_ROOT / str(path or "")).resolve()
        target.relative_to(REPOSITORY_ROOT)
        records = [
            json.loads(line)
            for line in target.read_text(encoding="utf-8-sig").splitlines()
            if line.strip()
        ]
    except (OSError, ValueError, json.JSONDecodeError):
        issues.append(f"{label}_unreadable")
        return []
    if not all(isinstance(record, dict) for record in records):
        issues.append(f"{label}_object_records_required")
        return []
    return records


def _read_repository_json(path: Any, issues: list[str], label: str) -> dict:
    try:
        target = (REPOSITORY_ROOT / str(path or "")).resolve()
        target.relative_to(REPOSITORY_ROOT)
        value = read_json(target)
    except (OSError, ValueError, json.JSONDecodeError):
        issues.append(f"{label}_unreadable")
        return {}
    if not isinstance(value, dict):
        issues.append(f"{label}_object_required")
        return {}
    return value


def _check_file(issues: list[str], label: str, path: Any, expected_hash: Any) -> None:
    try:
        target = (REPOSITORY_ROOT / str(path or "")).resolve()
        target.relative_to(REPOSITORY_ROOT)
        passed = target.is_file() and file_sha256(target) == str(expected_hash or "").lower()
    except (OSError, ValueError):
        passed = False
    _check(issues, label, passed)


def _check_implementation_file(
    issues: list[str],
    label: str,
    path: Any,
    expected_hash: Any,
) -> None:
    relative = str(path or "").replace("\\", "/")
    expected = str(expected_hash or "").lower()
    try:
        target = (REPOSITORY_ROOT / relative).resolve()
        target.relative_to(REPOSITORY_ROOT)
        passed = target.is_file() and file_sha256(target) == expected
    except (OSError, ValueError):
        passed = False
    if not passed:
        passed = _committed_implementation_matches(relative, expected)
    _check(issues, label, passed)


@lru_cache(maxsize=128)
def _committed_implementation_matches(relative: str, expected: str) -> bool:
    if not relative or not re.fullmatch(r"[0-9a-f]{64}", expected):
        return False
    try:
        target = (REPOSITORY_ROOT / relative).resolve()
        target.relative_to(REPOSITORY_ROOT)
        commits = subprocess.check_output(
            ["git", "log", "--format=%H", "--", relative],
            cwd=REPOSITORY_ROOT,
            stderr=subprocess.DEVNULL,
        ).decode("ascii").splitlines()
    except (OSError, subprocess.SubprocessError, UnicodeDecodeError, ValueError):
        return False
    for commit in commits:
        try:
            retained = subprocess.check_output(
                ["git", "show", f"{commit}:{relative}"],
                cwd=REPOSITORY_ROOT,
                stderr=subprocess.DEVNULL,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if hashlib.sha256(retained).hexdigest() == expected:
            return True
    return False


def _check(issues: list[str], label: str, passed: bool) -> None:
    if not passed:
        issues.append(label)


def _safe_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0
