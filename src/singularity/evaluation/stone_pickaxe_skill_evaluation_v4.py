"""Third isolated recovery window for the SP-001 learned-skill evaluation.

The v1-v3 policies, reports, and retained failures are immutable. This adapter
evaluates only fresh r10-r12 candidates while importing the three v1 support
arms through exact path and hash bindings.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator

import singularity.evaluation.stone_pickaxe_skill_evaluation as _v1
import singularity.evaluation.stone_pickaxe_skill_evaluation_v2 as _v2
import singularity.evaluation.stone_pickaxe_skill_evaluation_v3 as _v3
from singularity.evaluation.stone_pickaxe_protocol import REPOSITORY_ROOT
from singularity.evaluation.stone_pickaxe_runtime import file_sha256, read_json, repo_relative


POLICY_RELATIVE_PATH = (
    "workspace/evals/sp001_skill_evaluation_v4/"
    "stone_pickaxe_paired_evaluation_policy_v4.json"
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
_SECOND_POLICY = _v2.POLICY
_SECOND_POLICY_SHA256 = _v2.POLICY_SHA256
_PREVIOUS_POLICY_RELATIVE_PATH = _v3.POLICY_RELATIVE_PATH
_PREVIOUS_POLICY = _v3.POLICY
_PREVIOUS_POLICY_SHA256 = _v3.POLICY_SHA256
_PREVIOUS_POLICY_IDENTITY_REPORT = _v3.policy_identity_report


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
    window = value.get("recovery_window", {}) if isinstance(value.get("recovery_window"), dict) else {}
    prior = window.get("prior_policy", {}) if isinstance(window.get("prior_policy"), dict) else {}
    prior_report = window.get("prior_report", {}) if isinstance(window.get("prior_report"), dict) else {}
    prior_window = (
        window.get("prior_window_policy", {})
        if isinstance(window.get("prior_window_policy"), dict)
        else {}
    )
    prior_window_report = (
        window.get("prior_window_report", {})
        if isinstance(window.get("prior_window_report"), dict)
        else {}
    )
    failed_runs = window.get("retained_failed_runs", [])
    failed_runs = failed_runs if isinstance(failed_runs, list) else []
    supports = value.get("inherited_support_bindings", [])
    supports = supports if isinstance(supports, list) else []

    _check(issues, "recovery_policy_id", value.get("id") == "stone-pickaxe-sp001-paired-evaluation-v4")
    _check(issues, "recovery_window_id", window.get("id") == "sp001-acquire-route-scope-recovery-v4")
    _check(issues, "prior_policy_id", prior.get("id") == _BASE_POLICY.get("id"))
    _check(issues, "prior_policy_path", prior.get("path") == _BASE_POLICY_RELATIVE_PATH)
    _check(issues, "prior_policy_hash", prior.get("sha256") == _BASE_POLICY_SHA256)
    _check_file(issues, "prior_policy_file", prior.get("path"), prior.get("sha256"))
    _check_file(issues, "prior_report_file", prior_report.get("path"), prior_report.get("sha256"))
    _check(issues, "prior_window_policy_id", prior_window.get("id") == _PREVIOUS_POLICY.get("id"))
    _check(
        issues,
        "prior_window_policy_path",
        prior_window.get("path") == _PREVIOUS_POLICY_RELATIVE_PATH,
    )
    _check(
        issues,
        "prior_window_policy_hash",
        prior_window.get("sha256") == _PREVIOUS_POLICY_SHA256,
    )
    _check_file(
        issues,
        "prior_window_policy_file",
        prior_window.get("path"),
        prior_window.get("sha256"),
    )
    _check_file(
        issues,
        "prior_window_report_file",
        prior_window_report.get("path"),
        prior_window_report.get("sha256"),
    )
    previous_identity = _PREVIOUS_POLICY_IDENTITY_REPORT()
    _check(issues, "prior_window_policy_identity", previous_identity.get("passed") is True)
    _check(
        issues,
        "runtime_fix_commit",
        window.get("runtime_fix_commit") == "18525025fb3dcf5c205bb79c772f57fc1ba3cc50",
    )
    _check(
        issues,
        "candidate_replicates_exact",
        value.get("arms", {}).get("candidate", {}).get("replicate_ids") == ["r10", "r11", "r12"],
    )
    _check(
        issues,
        "excluded_replicates_exact",
        window.get("excluded_replicate_ids")
        == ["r1", "r2", "r3", "r4", "r5", "r6", "r7", "r8", "r9"],
    )
    _check(issues, "candidate_only_authorization", window.get("live_authorization_scope") == "candidate_only")
    _check(issues, "prior_candidate_reuse_forbidden", window.get("prior_candidate_reuse_allowed") is False)
    _check(issues, "support_rerun_forbidden", window.get("support_rerun_allowed") is False)
    _check(issues, "automatic_retry_forbidden", window.get("automatic_retry_allowed") is False)
    _check(issues, "three_retained_failed_runs", len(failed_runs) == 3)
    expected_failures = [
        ("r1", _BASE_POLICY.get("id"), _BASE_POLICY_SHA256),
        ("r4", _SECOND_POLICY.get("id"), _SECOND_POLICY_SHA256),
        ("r7", _PREVIOUS_POLICY.get("id"), _PREVIOUS_POLICY_SHA256),
    ]
    actual_failures = [
        (
            item.get("replicate_id"),
            item.get("policy_id"),
            item.get("policy_sha256"),
        )
        for item in failed_runs
        if isinstance(item, dict)
    ]
    _check(issues, "retained_failed_run_identities", actual_failures == expected_failures)
    for raw_failed in failed_runs:
        failed = raw_failed if isinstance(raw_failed, dict) else {}
        label = str(failed.get("replicate_id") or "missing")
        _check(issues, f"failed_{label}_arm", failed.get("arm") == "candidate")
        _check(issues, f"failed_{label}_status", failed.get("status") == "fail")
        _check_file(issues, f"failed_{label}_file", failed.get("path"), failed.get("sha256"))
        retained = _read_bound_run(failed, issues, f"failed_{label}")
        _check(
            issues,
            f"failed_{label}_payload",
            retained.get("record_payload_sha256") == failed.get("record_payload_sha256"),
        )
        retained_audit = _verify_retained_failed_run(retained)
        _check(issues, f"failed_{label}_integrity", retained_audit.get("passed") is True)

    pair_replicates = [binding.get("replicate_id") for binding in value.get("pair_bindings", [])]
    _check(issues, "recovery_pair_replicates", pair_replicates == ["r10", "r11", "r12"])
    _check(issues, "three_inherited_support_bindings", len(supports) == 3)
    _check(
        issues,
        "inherited_support_arms",
        [(item.get("arm"), item.get("replicate_id")) for item in supports if isinstance(item, dict)]
        == [("shadow", "shadow-1"), ("advisory", "advisory-1"), ("fallback", "fallback-1")],
    )
    for arm in ("shadow", "advisory", "fallback"):
        spec = value.get("arms", {}).get(arm, {})
        _check(issues, f"{arm}_authorization_forbidden", spec.get("authorization_allowed") is False)
        _check(issues, f"{arm}_evidence_inherited", spec.get("evidence_source") == "inherited_v1")
    candidate_spec = value.get("arms", {}).get("candidate", {})
    _check(issues, "candidate_authorization_allowed", candidate_spec.get("authorization_allowed") is True)
    _check(issues, "candidate_evidence_fresh", candidate_spec.get("evidence_source") == "fresh_v4_live")
    for raw_binding in supports:
        binding = raw_binding if isinstance(raw_binding, dict) else {}
        label = str(binding.get("arm") or "missing")
        _check(issues, f"inherited_{label}_policy_id", binding.get("policy_id") == _BASE_POLICY.get("id"))
        _check(issues, f"inherited_{label}_policy_hash", binding.get("policy_sha256") == _BASE_POLICY_SHA256)
        _check_file(issues, f"inherited_{label}_file", binding.get("path"), binding.get("sha256"))
        run = _read_bound_run(binding, issues, label)
        if run:
            with _v1_policy_context():
                audit = _BASE_VERIFY_RUN_RECORD(run)
            _check(issues, f"inherited_{label}_integrity", audit.get("passed") is True)
            _check(issues, f"inherited_{label}_status", run.get("status") == "pass")
            _check(issues, f"inherited_{label}_arm", run.get("arm") == binding.get("arm"))
            _check(issues, f"inherited_{label}_replicate", run.get("replicate_id") == binding.get("replicate_id"))
            _check(
                issues,
                f"inherited_{label}_payload",
                run.get("record_payload_sha256") == binding.get("record_payload_sha256"),
            )

    report.update({
        "type": "stone_pickaxe_paired_recovery_policy_identity",
        "policy_path": POLICY_RELATIVE_PATH,
        "policy_sha256": effective_sha,
        "recovery_window_id": window.get("id", ""),
        "prior_policy_sha256": _BASE_POLICY_SHA256,
        "prior_window_policy_sha256": _PREVIOUS_POLICY_SHA256,
        "inherited_support_count": len(supports),
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
    git_head: str,
    existing_run_paths: Iterable[str | Path] | None = None,
) -> dict:
    identity = policy_identity_report()
    if not identity["passed"]:
        raise ValueError(f"recovery evaluation policy identity failed: {identity['issues']}")
    if str(arm or "").strip().lower() != "candidate":
        raise ValueError("the recovery window authorizes candidate arms only; support arms are inherited")
    with _policy_context():
        authorization = _v1.build_evaluation_authorization(
            arm=arm,
            replicate_id=replicate_id,
            episode_id=episode_id,
            git_head=git_head,
            existing_run_paths=existing_run_paths,
        )
    window = POLICY["recovery_window"]
    authorization.update({
        "evaluation_window_id": window["id"],
        "prior_policy_sha256": window["prior_policy"]["sha256"],
        "prior_window_policy_sha256": window["prior_window_policy"]["sha256"],
        "excluded_prior_replicate_ids": list(window["excluded_replicate_ids"]),
        "inherited_support_evidence": True,
    })
    return authorization


def validate_evaluation_authorization(
    authorization: Any,
    *,
    expected_arm: str = "",
    expected_replicate_id: str = "",
    expected_episode_id: str = "",
    expected_git_head: str = "",
) -> dict:
    with _policy_context():
        report = _v1.validate_evaluation_authorization(
            authorization,
            expected_arm=expected_arm,
            expected_replicate_id=expected_replicate_id,
            expected_episode_id=expected_episode_id,
            expected_git_head=expected_git_head,
        )
    issues = list(report.get("issues", []))
    value = authorization if isinstance(authorization, dict) else {}
    window = POLICY["recovery_window"]
    _check(issues, "authorization_candidate_only", value.get("arm") == "candidate")
    _check(issues, "authorization_window", value.get("evaluation_window_id") == window["id"])
    _check(issues, "authorization_prior_policy", value.get("prior_policy_sha256") == _BASE_POLICY_SHA256)
    _check(
        issues,
        "authorization_prior_window_policy",
        value.get("prior_window_policy_sha256") == _PREVIOUS_POLICY_SHA256,
    )
    _check(
        issues,
        "authorization_excluded_replicates",
        value.get("excluded_prior_replicate_ids") == window["excluded_replicate_ids"],
    )
    _check(issues, "authorization_inherited_support", value.get("inherited_support_evidence") is True)
    identity = policy_identity_report()
    if not identity["passed"]:
        issues.extend(f"recovery_policy:{issue}" for issue in identity["issues"])
    report.update({
        "type": "stone_pickaxe_skill_recovery_authorization_audit",
        "evaluation_window_id": window["id"],
        "issues": sorted(set(issues)),
        "passed": not issues,
    })
    return report


def build_skill_evaluation_runtime_config(**kwargs: Any):
    audit = validate_evaluation_authorization(kwargs.get("authorization"))
    if not audit["passed"]:
        raise ValueError(f"recovery evaluation authorization rejected: {audit['issues']}")
    with _policy_context():
        return _v1.build_skill_evaluation_runtime_config(**kwargs)


class StonePickaxeSkillEvaluationAgent(_v1.StonePickaxeSkillEvaluationAgent):
    """Evaluation agent pinned to the isolated v4 recovery policy."""

    def __init__(self, config: Any, authorization: dict):
        audit = validate_evaluation_authorization(authorization)
        if not audit["passed"]:
            raise ValueError(f"recovery evaluation authorization rejected: {audit['issues']}")
        with _policy_context():
            super().__init__(config, authorization)


def build_skill_evaluation_episode(*, authorization: dict, **kwargs: Any) -> dict:
    audit = validate_evaluation_authorization(authorization)
    if not audit["passed"]:
        raise ValueError(f"recovery evaluation authorization rejected: {audit['issues']}")
    with _policy_context():
        episode = _v1.build_skill_evaluation_episode(authorization=authorization, **kwargs)
    episode.setdefault("evaluation", {})["evaluation_window_id"] = POLICY["recovery_window"]["id"]
    return episode


def build_skill_evaluation_run(**kwargs: Any) -> dict:
    audit = validate_evaluation_authorization(kwargs.get("authorization"))
    if not audit["passed"]:
        raise ValueError(f"recovery evaluation authorization rejected: {audit['issues']}")
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
    index["prior_window_policy_sha256"] = _PREVIOUS_POLICY_SHA256
    return index


def build_paired_evaluation_report(run_paths: Iterable[str | Path]) -> dict:
    selected_paths, selection_errors, excluded = _select_window_run_paths(run_paths)
    original_verify = _v1.verify_run_record
    try:
        _v1.verify_run_record = _report_verify_dispatch
        with _policy_context():
            report = _BASE_BUILD_PAIRED_REPORT(selected_paths)
    finally:
        _v1.verify_run_record = original_verify

    identity = policy_identity_report()
    errors = list(report.get("errors", [])) + selection_errors
    if not identity["passed"]:
        errors.extend(f"recovery_policy:{issue}" for issue in identity["issues"])
    report.update({
        "type": "stone_pickaxe_skill_paired_recovery_evaluation",
        "evaluation_window_id": POLICY["recovery_window"]["id"],
        "prior_policy_id": _BASE_POLICY.get("id", ""),
        "prior_policy_sha256": _BASE_POLICY_SHA256,
        "prior_window_policy_id": _PREVIOUS_POLICY.get("id", ""),
        "prior_window_policy_sha256": _PREVIOUS_POLICY_SHA256,
        "excluded_prior_runs": excluded,
        "inherited_support_runs": [
            {
                "arm": binding["arm"],
                "replicate_id": binding["replicate_id"],
                "path": binding["path"],
                "sha256": binding["sha256"],
                "record_payload_sha256": binding["record_payload_sha256"],
            }
            for binding in POLICY["inherited_support_bindings"]
        ],
        "errors": sorted(set(errors)),
        "prior_evidence_mutated": False,
    })
    if errors:
        _force_review(report, errors)
    return report


def verify_run_record(run: Any) -> dict:
    value = run if isinstance(run, dict) else {}
    if _is_exact_inherited_support(value):
        with _v1_policy_context():
            return _BASE_VERIFY_RUN_RECORD(value)
    with _policy_context():
        report = _BASE_VERIFY_RUN_RECORD(value)
    issues = list(report.get("issues", []))
    if value.get("arm") == "candidate":
        _check(issues, "run_evaluation_window", value.get("evaluation_window_id") == POLICY["recovery_window"]["id"])
    _check(issues, "run_candidate_only", value.get("arm") in {"baseline", "candidate"})
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


def _report_verify_dispatch(run: Any) -> dict:
    value = run if isinstance(run, dict) else {}
    if _is_exact_inherited_support(value):
        with _v1_policy_context():
            return _BASE_VERIFY_RUN_RECORD(value)
    return verify_run_record(value)


def _select_window_run_paths(run_paths: Iterable[str | Path]) -> tuple[list[Path], list[str], list[dict]]:
    selected: dict[str, Path] = {}
    errors: list[str] = []
    excluded: list[dict] = []
    support_paths = {binding["path"]: binding for binding in POLICY["inherited_support_bindings"]}
    for relative, binding in support_paths.items():
        path = REPOSITORY_ROOT / relative
        if not path.is_file() or file_sha256(path) != binding["sha256"]:
            errors.append(f"inherited_support_binding_invalid:{binding['arm']}")
            continue
        selected[relative] = path

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
        if relative in support_paths:
            selected[relative] = path
            continue
        if run.get("policy_id") == POLICY["id"] or run.get("policy_sha256") == POLICY_SHA256:
            if run.get("policy_id") != POLICY["id"] or run.get("policy_sha256") != POLICY_SHA256:
                errors.append(f"window_policy_partial_match:{run.get('run_id', relative)}")
            elif run.get("arm") != "candidate":
                errors.append(f"window_non_candidate_run:{run.get('run_id', relative)}")
            elif run.get("replicate_id") not in POLICY["arms"]["candidate"]["replicate_ids"]:
                errors.append(f"window_replicate_out_of_scope:{run.get('run_id', relative)}")
            else:
                selected[relative] = path
            continue
        if run.get("policy_id") in {
            _BASE_POLICY.get("id"),
            _SECOND_POLICY.get("id"),
            _PREVIOUS_POLICY.get("id"),
        }:
            excluded.append({
                "run_id": str(run.get("run_id") or ""),
                "arm": str(run.get("arm") or ""),
                "replicate_id": str(run.get("replicate_id") or ""),
                "status": str(run.get("status") or ""),
                "path": relative,
                "reason": "superseded_window_not_reused",
            })
    return list(selected.values()), errors, sorted(excluded, key=lambda item: item["path"])


def _is_exact_inherited_support(run: dict) -> bool:
    return any(
        run.get("policy_id") == binding.get("policy_id")
        and run.get("policy_sha256") == binding.get("policy_sha256")
        and run.get("arm") == binding.get("arm")
        and run.get("replicate_id") == binding.get("replicate_id")
        and run.get("record_payload_sha256") == binding.get("record_payload_sha256")
        for binding in POLICY.get("inherited_support_bindings", [])
        if isinstance(binding, dict)
    )


def _verify_retained_failed_run(run: dict) -> dict:
    policy_id = run.get("policy_id")
    if policy_id == _BASE_POLICY.get("id"):
        with _v1_policy_context():
            return _BASE_VERIFY_RUN_RECORD(run)
    if policy_id == _SECOND_POLICY.get("id"):
        return _v2.verify_run_record(run)
    if policy_id == _PREVIOUS_POLICY.get("id"):
        return _v3.verify_run_record(run)
    return {"passed": False, "issues": ["retained_failure_policy_unknown"]}


def _read_bound_run(binding: dict, issues: list[str], label: str) -> dict:
    try:
        path = (REPOSITORY_ROOT / str(binding.get("path") or "")).resolve()
        path.relative_to(REPOSITORY_ROOT)
        value = read_json(path)
    except (OSError, ValueError, json.JSONDecodeError):
        issues.append(f"inherited_{label}_unreadable")
        return {}
    if not isinstance(value, dict):
        issues.append(f"inherited_{label}_object_required")
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
        gate["validation_issues"] = sorted(set(gate.get("validation_issues", [])) | set(errors))


def _check_file(issues: list[str], label: str, path: Any, expected_hash: Any) -> None:
    try:
        target = (REPOSITORY_ROOT / str(path or "")).resolve()
        target.relative_to(REPOSITORY_ROOT)
        passed = target.is_file() and file_sha256(target) == str(expected_hash or "").lower()
    except (OSError, ValueError):
        passed = False
    _check(issues, label, passed)


def _check(issues: list[str], label: str, passed: bool) -> None:
    if not passed:
        issues.append(label)
