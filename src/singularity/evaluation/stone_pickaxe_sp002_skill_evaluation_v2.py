"""Non-overlapping recovery window for the SP-002 crafting evaluation.

V1 evidence is immutable. This adapter keeps its policy and failed shadow run
verifiable while giving one-action SP-002 episodes a first-cycle learned-skill
routing opportunity under fresh support and candidate replicate identifiers.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator

import singularity.evaluation.stone_pickaxe_sp002_skill_evaluation as _v1
from singularity.evaluation.stone_pickaxe_protocol import REPOSITORY_ROOT
from singularity.evaluation.stone_pickaxe_sp002_runtime import (
    file_sha256,
    read_json,
    repo_relative,
)


POLICY_RELATIVE_PATH = (
    "workspace/evals/sp002_skill_evaluation_v2/"
    "stone_pickaxe_sp002_paired_evaluation_policy_v2.json"
)
POLICY_PATH = REPOSITORY_ROOT / POLICY_RELATIVE_PATH
POLICY = read_json(POLICY_PATH)
POLICY_SHA256 = file_sha256(POLICY_PATH)
AUTHORIZATION_ROOT = _v1.AUTHORIZATION_ROOT
RUN_TYPE = _v1.RUN_TYPE
REPORT_TYPE = _v1.REPORT_TYPE

canonical_record_sha256 = _v1.canonical_record_sha256

_BASE_POLICY_RELATIVE_PATH = _v1.POLICY_RELATIVE_PATH
_BASE_POLICY_PATH = _v1.POLICY_PATH
_BASE_POLICY = _v1.POLICY
_BASE_POLICY_SHA256 = _v1.POLICY_SHA256
_BASE_POLICY_IDENTITY_REPORT = _v1.policy_identity_report
_BASE_VERIFY_RUN_RECORD = _v1.verify_run_record
_BASE_BUILD_PAIRED_REPORT = _v1.build_paired_evaluation_report


@contextmanager
def _policy_context(
    policy: dict = POLICY,
    *,
    relative_path: str = POLICY_RELATIVE_PATH,
    path: Path = POLICY_PATH,
    sha256: str = POLICY_SHA256,
) -> Iterator[None]:
    previous = (
        _v1.POLICY_RELATIVE_PATH,
        _v1.POLICY_PATH,
        _v1.POLICY,
        _v1.POLICY_SHA256,
    )
    _v1.POLICY_RELATIVE_PATH = relative_path
    _v1.POLICY_PATH = path
    _v1.POLICY = policy
    _v1.POLICY_SHA256 = sha256
    try:
        yield
    finally:
        (
            _v1.POLICY_RELATIVE_PATH,
            _v1.POLICY_PATH,
            _v1.POLICY,
            _v1.POLICY_SHA256,
        ) = previous


@contextmanager
def _v1_policy_context() -> Iterator[None]:
    with _policy_context(
        _BASE_POLICY,
        relative_path=_BASE_POLICY_RELATIVE_PATH,
        path=_BASE_POLICY_PATH,
        sha256=_BASE_POLICY_SHA256,
    ):
        yield


def policy_identity_report(policy: dict | None = None) -> dict:
    value = policy if isinstance(policy, dict) else POLICY
    effective_sha = POLICY_SHA256 if value is POLICY else canonical_record_sha256(value)
    with _policy_context(value, sha256=effective_sha):
        report = _BASE_POLICY_IDENTITY_REPORT(value)
    issues = list(report.get("issues", []))
    window = _mapping(value.get("recovery_window"))
    prior = _mapping(window.get("prior_policy"))
    prior_report = _mapping(window.get("prior_report"))
    failed = _mapping(window.get("retained_failed_run"))

    _check(issues, "recovery_policy_id", value.get("id") == "stone-pickaxe-sp002-paired-evaluation-v2")
    _check(issues, "recovery_window_id", window.get("id") == "sp002-first-cycle-skill-routing-v2")
    _check(issues, "prior_policy_id", prior.get("id") == _BASE_POLICY.get("id"))
    _check(issues, "prior_policy_path", prior.get("path") == _BASE_POLICY_RELATIVE_PATH)
    _check(issues, "prior_policy_hash", prior.get("sha256") == _BASE_POLICY_SHA256)
    _check_file(issues, "prior_policy_file", prior.get("path"), prior.get("sha256"))
    _check_file(issues, "prior_report_file", prior_report.get("path"), prior_report.get("sha256"))
    _check(issues, "prior_report_policy", prior_report.get("policy_id") == _BASE_POLICY.get("id"))
    _check(issues, "failed_run_arm", failed.get("arm") == "shadow")
    _check(issues, "failed_run_replicate", failed.get("replicate_id") == "shadow-1")
    _check(issues, "failed_run_status", failed.get("status") == "fail")
    _check_file(issues, "failed_run_file", failed.get("path"), failed.get("sha256"))
    failed_run = _read_bound_run(failed, issues, "failed_run")
    if failed_run:
        with _v1_policy_context():
            failed_audit = _BASE_VERIFY_RUN_RECORD(failed_run)
        _check(issues, "failed_run_integrity", failed_audit.get("passed") is True)
        _check(issues, "failed_run_policy", failed_run.get("policy_id") == _BASE_POLICY.get("id"))
        _check(issues, "failed_run_payload", failed_run.get("record_payload_sha256") == failed.get("record_payload_sha256"))
        failed_checks = sorted(
            key
            for key, passed in _mapping(failed_run.get("checks")).items()
            if passed is not True
        )
        _check(issues, "failed_run_exact_check", failed_checks == ["shadow_plan_observed"])

    expected_arms = {
        "shadow": ["shadow-2"],
        "advisory": ["advisory-2"],
        "fallback": ["fallback-2"],
        "candidate": ["r4", "r5", "r6"],
    }
    for arm, replicates in expected_arms.items():
        spec = _mapping(_mapping(value.get("arms")).get(arm))
        _check(issues, f"{arm}_replicates_exact", spec.get("replicate_ids") == replicates)
        _check(issues, f"{arm}_authorization_allowed", spec.get("authorization_allowed") is True)
        _check(issues, f"{arm}_fresh_v2", spec.get("evidence_source") == "fresh_v2_live")
    pair_replicates = [
        _mapping(binding).get("replicate_id")
        for binding in value.get("pair_bindings", [])
    ]
    _check(issues, "recovery_pair_replicates", pair_replicates == ["r4", "r5", "r6"])
    _check(
        issues,
        "excluded_replicates_exact",
        window.get("excluded_replicate_ids")
        == ["shadow-1", "advisory-1", "fallback-1", "r1", "r2", "r3"],
    )
    _check(issues, "prior_reuse_forbidden", window.get("prior_replicate_reuse_allowed") is False)
    _check(issues, "automatic_retry_forbidden", window.get("automatic_retry_allowed") is False)
    _check(issues, "first_cycle_fix", window.get("first_cycle_skill_routing_required") is True)
    _check(issues, "root_plan_required", window.get("llm_root_plan_required") is True)
    _check(issues, "single_action_preserved", window.get("maximum_actions") == 1)

    report.update({
        "type": "stone_pickaxe_sp002_paired_recovery_policy_identity",
        "policy_path": POLICY_RELATIVE_PATH,
        "policy_sha256": effective_sha,
        "recovery_window_id": window.get("id", ""),
        "prior_policy_sha256": _BASE_POLICY_SHA256,
        "retained_failed_run_sha256": failed.get("sha256", ""),
        "excluded_replicate_ids": list(window.get("excluded_replicate_ids", [])),
        "issues": sorted(set(issues)),
        "passed": not issues,
    })
    return report


def build_evaluation_authorization(
    *,
    arm: str,
    replicate_id: str,
    episode_id: str,
    authorization_predecessor: str,
    existing_run_paths: Iterable[str | Path] | None = None,
) -> dict:
    identity = policy_identity_report()
    if not identity["passed"]:
        raise ValueError(f"SP-002 v2 policy identity failed: {identity['issues']}")
    normalized_arm = str(arm or "").strip().lower()
    normalized_replicate = str(replicate_id or "").strip().lower()
    spec = arm_spec(normalized_arm)
    if spec.get("authorization_allowed") is not True:
        raise ValueError(f"arm {normalized_arm!r} is not authorized in v2")
    if normalized_replicate in POLICY["recovery_window"]["excluded_replicate_ids"]:
        raise ValueError(f"replicate {normalized_replicate!r} belongs to the prior window")
    with _policy_context():
        authorization = _v1.build_evaluation_authorization(
            arm=normalized_arm,
            replicate_id=normalized_replicate,
            episode_id=episode_id,
            authorization_predecessor=authorization_predecessor,
            existing_run_paths=existing_run_paths,
        )
    window = POLICY["recovery_window"]
    authorization.update({
        "evaluation_window_id": window["id"],
        "prior_policy_sha256": _BASE_POLICY_SHA256,
        "retained_failed_run_sha256": window["retained_failed_run"]["sha256"],
        "excluded_prior_replicate_ids": list(window["excluded_replicate_ids"]),
        "first_cycle_skill_routing_required": True,
    })
    return authorization


def validate_evaluation_authorization(
    authorization: Any,
    *,
    expected_arm: str = "",
    expected_replicate_id: str = "",
    expected_episode_id: str = "",
    current_head: str = "",
    parent_head: str = "",
) -> dict:
    with _policy_context():
        report = _v1.validate_evaluation_authorization(
            authorization,
            expected_arm=expected_arm,
            expected_replicate_id=expected_replicate_id,
            expected_episode_id=expected_episode_id,
            current_head=current_head,
            parent_head=parent_head,
        )
    issues = list(report.get("issues", []))
    value = authorization if isinstance(authorization, dict) else {}
    window = POLICY["recovery_window"]
    _check(issues, "authorization_window", value.get("evaluation_window_id") == window["id"])
    _check(issues, "authorization_prior_policy", value.get("prior_policy_sha256") == _BASE_POLICY_SHA256)
    _check(
        issues,
        "authorization_failed_run",
        value.get("retained_failed_run_sha256") == window["retained_failed_run"]["sha256"],
    )
    _check(
        issues,
        "authorization_excluded_replicates",
        value.get("excluded_prior_replicate_ids") == window["excluded_replicate_ids"],
    )
    _check(issues, "authorization_first_cycle_fix", value.get("first_cycle_skill_routing_required") is True)
    _check(issues, "authorization_not_prior_replicate", value.get("replicate_id") not in window["excluded_replicate_ids"])
    identity = policy_identity_report()
    if not identity["passed"]:
        issues.extend(f"recovery_policy:{issue}" for issue in identity["issues"])
    report.update({
        "type": "stone_pickaxe_sp002_skill_recovery_authorization_audit",
        "evaluation_window_id": window["id"],
        "issues": sorted(set(issues)),
        "passed": not issues,
    })
    return report


def build_skill_evaluation_runtime_config(**kwargs: Any):
    audit = validate_evaluation_authorization(kwargs.get("authorization"))
    if not audit["passed"]:
        raise ValueError(f"SP-002 v2 authorization rejected: {audit['issues']}")
    with _policy_context():
        return _v1.build_skill_evaluation_runtime_config(**kwargs)


class StonePickaxeSP002SkillEvaluationAgent(_v1.StonePickaxeSP002SkillEvaluationAgent):
    """V2 agent that gives one-action episodes a first-cycle skill hook."""

    def __init__(self, config: Any, authorization: dict):
        audit = validate_evaluation_authorization(authorization)
        if not audit["passed"]:
            raise ValueError(f"SP-002 v2 authorization rejected: {audit['issues']}")
        with _policy_context():
            super().__init__(config, authorization)

    def _think(self, observation: dict, override_goal: str = None) -> dict:
        mode = str(getattr(self.config, "skill_execution_mode", "off") or "off").strip().lower()
        first_root_cycle = bool(
            getattr(self.config, "require_llm_root_plan", False)
            and not getattr(self, "_m2_root_plan_valid", False)
            and mode in {"shadow", "advisory", "evaluation", "runtime"}
            and getattr(self, "_use_llm", False)
        )
        if not first_root_cycle:
            return super()._think(observation, override_goal)

        goal = override_goal or self.current_goal or "explore"
        if self._episode_deadline_reached():
            return {
                "status": "blocked",
                "reasoning": "Episode deadline exhausted before first-cycle skill routing",
                "actions": [],
                "deadline_suppressed": True,
            }
        self._active_skill_advisory_hint = ""

        if mode in {"shadow", "advisory", "runtime"}:
            skill_plan = self._learned_skill_plan(goal, observation)
            self.session_logger.log("sp002_skill_first_cycle_routing", {
                "policy_id": POLICY["recovery_window"]["first_cycle_routing_policy_id"],
                "goal": goal,
                "mode": mode,
                "root_plan_valid_before_routing": False,
                "direct_skill_plan_returned": skill_plan is not None,
                "runtime_influence": mode == "advisory",
            })
            plan = self._think_llm(observation, goal)
            plan = self._blocked_plan_rule_fallback(plan, goal, observation)
            return self._apply_visual_action_grounding(plan, observation, goal)

        root_plan = self._think_llm(observation, goal)
        root_plan = self._blocked_plan_rule_fallback(root_plan, goal, observation)
        if not getattr(self, "_m2_root_plan_valid", False):
            return self._apply_visual_action_grounding(root_plan, observation, goal)
        skill_plan = self._learned_skill_plan(goal, observation)
        skill_actions = (
            list(skill_plan.get("actions", []))
            if isinstance(skill_plan, dict) and isinstance(skill_plan.get("actions"), list)
            else []
        )
        if not skill_actions:
            self.session_logger.log("sp002_skill_first_cycle_routing", {
                "policy_id": POLICY["recovery_window"]["first_cycle_routing_policy_id"],
                "goal": goal,
                "mode": mode,
                "root_plan_valid_before_routing": True,
                "direct_skill_plan_returned": False,
                "runtime_influence": False,
            })
            return self._apply_visual_action_grounding(root_plan, observation, goal)

        merged = dict(root_plan)
        merged["actions"] = skill_actions
        merged["sp002_skill_first_cycle_overlay"] = {
            "schema_version": 1,
            "policy_id": POLICY["recovery_window"]["first_cycle_routing_policy_id"],
            "root_planner_call_preserved": True,
            "root_subtasks_preserved": True,
            "skill_action_count": len(skill_actions),
        }
        self.session_logger.log("sp002_skill_first_cycle_routing", {
            "policy_id": POLICY["recovery_window"]["first_cycle_routing_policy_id"],
            "goal": goal,
            "mode": mode,
            "root_plan_valid_before_routing": True,
            "direct_skill_plan_returned": True,
            "skill_action_count": len(skill_actions),
            "runtime_influence": True,
        })
        return self._apply_visual_action_grounding(merged, observation, goal)


def build_skill_evaluation_episode(*, authorization: dict, **kwargs: Any) -> dict:
    audit = validate_evaluation_authorization(authorization)
    if not audit["passed"]:
        raise ValueError(f"SP-002 v2 authorization rejected: {audit['issues']}")
    with _policy_context():
        episode = _v1.build_skill_evaluation_episode(authorization=authorization, **kwargs)
    episode.setdefault("evaluation", {})["evaluation_window_id"] = POLICY["recovery_window"]["id"]
    return episode


def build_skill_evaluation_run(**kwargs: Any) -> dict:
    audit = validate_evaluation_authorization(kwargs.get("authorization"))
    if not audit["passed"]:
        raise ValueError(f"SP-002 v2 authorization rejected: {audit['issues']}")
    with _policy_context():
        run = _v1.build_skill_evaluation_run(**kwargs)
    run["evaluation_window_id"] = POLICY["recovery_window"]["id"]
    run["record_payload_sha256"] = _record_payload_sha256(run)
    return run


def build_baseline_index() -> dict:
    with _policy_context():
        index = _v1.build_baseline_index()
    index["evaluation_window_id"] = POLICY["recovery_window"]["id"]
    index["prior_policy_sha256"] = _BASE_POLICY_SHA256
    return index


def build_paired_evaluation_report(run_paths: Iterable[str | Path]) -> dict:
    selected, selection_errors, excluded = _select_window_run_paths(run_paths)
    with _policy_context():
        report = _BASE_BUILD_PAIRED_REPORT(selected)
    identity = policy_identity_report()
    errors = list(report.get("errors", [])) + selection_errors
    if not identity["passed"]:
        errors.extend(f"recovery_policy:{issue}" for issue in identity["issues"])
    report.update({
        "type": "stone_pickaxe_sp002_skill_paired_recovery_evaluation",
        "evaluation_window_id": POLICY["recovery_window"]["id"],
        "prior_policy_id": _BASE_POLICY.get("id", ""),
        "prior_policy_sha256": _BASE_POLICY_SHA256,
        "retained_failed_run": dict(POLICY["recovery_window"]["retained_failed_run"]),
        "excluded_prior_runs": excluded,
        "support_runs": _support_run_summaries(selected),
        "errors": sorted(set(errors)),
        "prior_evidence_mutated": False,
    })
    if errors:
        _force_review(report, errors)
    return report


def verify_run_record(run: Any) -> dict:
    value = run if isinstance(run, dict) else {}
    with _policy_context():
        report = _BASE_VERIFY_RUN_RECORD(value)
    issues = list(report.get("issues", []))
    if value.get("arm") != "baseline":
        _check(
            issues,
            "run_evaluation_window",
            value.get("evaluation_window_id") == POLICY["recovery_window"]["id"],
        )
    report.update({"issues": sorted(set(issues)), "passed": not issues})
    return report


def arm_spec(arm: str) -> dict:
    with _policy_context():
        return _v1.arm_spec(arm)


def pair_binding(replicate_id: str) -> dict:
    with _policy_context():
        return _v1.pair_binding(replicate_id)


def discover_evaluation_run_paths(root: str | Path = AUTHORIZATION_ROOT) -> list[Path]:
    return _v1.discover_evaluation_run_paths(root)


def discover_evaluation_authorization_paths(root: str | Path = AUTHORIZATION_ROOT) -> list[Path]:
    return _v1.discover_evaluation_authorization_paths(root)


def _select_window_run_paths(
    run_paths: Iterable[str | Path],
) -> tuple[list[Path], list[str], list[dict]]:
    selected: list[Path] = []
    errors: list[str] = []
    excluded: list[dict] = []
    allowed = {
        (arm, replicate)
        for arm, spec in _mapping(POLICY.get("arms")).items()
        for replicate in _mapping(spec).get("replicate_ids", [])
    }
    for raw_path in run_paths:
        path = Path(raw_path)
        if not path.is_absolute():
            path = REPOSITORY_ROOT / path
        try:
            relative = repo_relative(path)
            run = read_json(path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"window_run_unreadable:{type(exc).__name__}")
            continue
        if run.get("policy_id") == POLICY["id"] or run.get("policy_sha256") == POLICY_SHA256:
            if run.get("policy_id") != POLICY["id"] or run.get("policy_sha256") != POLICY_SHA256:
                errors.append(f"window_policy_partial_match:{run.get('run_id', relative)}")
            elif (run.get("arm"), run.get("replicate_id")) not in allowed:
                errors.append(f"window_replicate_out_of_scope:{run.get('run_id', relative)}")
            else:
                selected.append(path)
            continue
        if run.get("policy_id") == _BASE_POLICY.get("id"):
            excluded.append({
                "run_id": str(run.get("run_id") or ""),
                "arm": str(run.get("arm") or ""),
                "replicate_id": str(run.get("replicate_id") or ""),
                "status": str(run.get("status") or ""),
                "path": relative,
                "reason": "prior_window_not_reused",
            })
    return selected, errors, sorted(excluded, key=lambda item: item["path"])


def _support_run_summaries(run_paths: Iterable[Path]) -> list[dict]:
    groups: dict[tuple[str, str], list[dict]] = {}
    for path in run_paths:
        try:
            run = read_json(path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        key = (str(run.get("arm") or ""), str(run.get("replicate_id") or ""))
        groups.setdefault(key, []).append(run)

    summaries: list[dict] = []
    for arm in ("shadow", "advisory", "fallback"):
        for replicate in _mapping(_mapping(POLICY.get("arms")).get(arm)).get(
            "replicate_ids", []
        ):
            values = groups.get((arm, replicate), [])
            summaries.append({
                "arm": arm,
                "replicate_id": replicate,
                "run_id": values[0].get("run_id", "") if len(values) == 1 else "",
                "status": (
                    values[0].get("status", "missing")
                    if len(values) == 1
                    else "duplicate" if values else "missing"
                ),
            })
    return summaries


def _read_bound_run(binding: dict, issues: list[str], label: str) -> dict:
    try:
        path = (REPOSITORY_ROOT / str(binding.get("path") or "")).resolve()
        path.relative_to(REPOSITORY_ROOT)
        value = read_json(path)
    except (OSError, ValueError, json.JSONDecodeError):
        issues.append(f"{label}_unreadable")
        return {}
    if not isinstance(value, dict):
        issues.append(f"{label}_object_required")
        return {}
    return value


def _record_payload_sha256(record: dict) -> str:
    payload = dict(record)
    payload.pop("record_payload_sha256", None)
    return canonical_record_sha256(payload)


def _force_review(report: dict, errors: Iterable[str]) -> None:
    report["decision"] = "retain_advisory"
    report["readiness"] = "review"
    gate = report.get("executable_promotion_gate", {})
    if isinstance(gate, dict):
        gate["decision"] = "retain_advisory"
        gate["readiness"] = "review"
        gate["validation_issues"] = sorted(
            set(gate.get("validation_issues", [])) | set(errors)
        )


def _check_file(issues: list[str], label: str, path: Any, expected_hash: Any) -> None:
    try:
        target = (REPOSITORY_ROOT / str(path or "")).resolve()
        target.relative_to(REPOSITORY_ROOT)
        passed = target.is_file() and file_sha256(target) == str(expected_hash or "").lower()
    except (OSError, ValueError):
        passed = False
    _check(issues, label, passed)


def _mapping(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _check(issues: list[str], label: str, passed: bool) -> None:
    if not passed:
        issues.append(label)
