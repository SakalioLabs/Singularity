"""Verifier-calibrated, reviewable soft retirement for learned skills."""

import json
import os
from collections import defaultdict
from typing import Optional


SCHEMA_VERSION = 1


BUILTIN_VERIFIER_CALIBRATION_CASES = [
    {
        "id": "builtin-calibration-defect-1",
        "truth_success": False,
        "judge_pass": False,
        "defect_injected": True,
        "judge_id": "builtin_reward_judge_v1",
        "verifier_id": "builtin_deterministic_fixture_v1",
        "task_stream_id": "builtin_calibration_stream",
        "session_id": "builtin-calibration-session-1",
        "seed": "11",
        "source": "builtin",
        "evidence_kind": "synthetic_control",
        "non_verifier_modules_fixed": True,
    },
    {
        "id": "builtin-calibration-defect-2",
        "truth_success": False,
        "judge_pass": False,
        "defect_injected": True,
        "judge_id": "builtin_reward_judge_v1",
        "verifier_id": "builtin_deterministic_fixture_v1",
        "task_stream_id": "builtin_calibration_stream",
        "session_id": "builtin-calibration-session-2",
        "seed": "12",
        "source": "builtin",
        "evidence_kind": "synthetic_control",
        "non_verifier_modules_fixed": True,
    },
    {
        "id": "builtin-calibration-defect-3",
        "truth_success": False,
        "judge_pass": False,
        "defect_injected": True,
        "judge_id": "builtin_reward_judge_v1",
        "verifier_id": "builtin_deterministic_fixture_v1",
        "task_stream_id": "builtin_calibration_stream",
        "session_id": "builtin-calibration-session-3",
        "seed": "13",
        "source": "builtin",
        "evidence_kind": "synthetic_control",
        "non_verifier_modules_fixed": True,
    },
    {
        "id": "builtin-calibration-pass-1",
        "truth_success": True,
        "judge_pass": True,
        "defect_injected": False,
        "judge_id": "builtin_reward_judge_v1",
        "verifier_id": "builtin_deterministic_fixture_v1",
        "task_stream_id": "builtin_calibration_stream",
        "session_id": "builtin-calibration-session-4",
        "seed": "14",
        "source": "builtin",
        "evidence_kind": "synthetic_control",
        "non_verifier_modules_fixed": True,
    },
]


BUILTIN_SKILL_CONTRIBUTION_CASES = [
    {
        "id": f"builtin-contribution-{index}",
        "skill": "builtin_unreliable_shelter_shortcut",
        "task_family": "building",
        "baseline_successes": 1,
        "baseline_trials": 1,
        "candidate_successes": 0,
        "candidate_trials": 1,
        "candidate_failure_verified_count": 1,
        "baseline_session_id": f"builtin-baseline-{index}",
        "candidate_session_id": f"builtin-candidate-{index}",
        "judge_id": "builtin_reward_judge_v1",
        "verifier_id": "builtin_deterministic_fixture_v1",
        "planner_id": "builtin_fixed_planner_v1",
        "action_backend": "builtin_fixed_backend_v1",
        "task_stream_id": "builtin_contribution_stream",
        "seed": str(20 + index),
        "source": "builtin",
        "evidence_kind": "synthetic_control",
        "no_skill_baseline": True,
        "non_skill_modules_fixed": True,
        "built_in": False,
    }
    for index in range(1, 4)
]


def load_case_files(paths: list[str]) -> tuple[list[dict], list[str]]:
    """Load JSON or JSONL case fixtures without carrying raw prompts into reports."""
    cases = []
    errors = []
    for path in paths or []:
        try:
            with open(path, "r", encoding="utf-8-sig") as handle:
                if path.lower().endswith(".jsonl"):
                    payloads = [json.loads(line) for line in handle if line.strip()]
                else:
                    payload = json.load(handle)
                    if isinstance(payload, list):
                        payloads = payload
                    elif isinstance(payload, dict) and isinstance(payload.get("cases"), list):
                        payloads = payload["cases"]
                    else:
                        payloads = [payload]
            for payload in payloads:
                if isinstance(payload, dict):
                    item = dict(payload)
                    item.setdefault("source", path)
                    cases.append(item)
                else:
                    errors.append(f"{path}: case is not an object")
        except Exception as error:
            errors.append(f"{path}: {error}")
    return cases, errors


def build_verifier_calibration_report(
    cases: list[dict],
    *,
    require_live_evidence: bool = True,
    min_defect_probes: int = 3,
    min_control_passes: int = 1,
    max_false_pass_rate: float = 0.10,
    min_failure_detection_recall: float = 0.90,
    load_errors: Optional[list[str]] = None,
) -> dict:
    """Measure false-pass bias using verifier-backed defect injection."""
    thresholds = {
        "require_live_evidence": bool(require_live_evidence),
        "min_defect_probes": max(1, _as_int(min_defect_probes, 3)),
        "min_control_passes": max(0, _as_int(min_control_passes, 1)),
        "max_false_pass_rate": _clamp_rate(max_false_pass_rate, 0.10),
        "min_failure_detection_recall": _clamp_rate(min_failure_detection_recall, 0.90),
    }
    normalized = [_normalize_calibration_case(case, index) for index, case in enumerate(cases or [], start=1)]
    evidence_cases = [case for case in normalized if _evidence_allowed(case, thresholds["require_live_evidence"])]
    eligible = [case for case in evidence_cases if case["eligible"]]
    true_failures = [case for case in eligible if case["truth_success"] is False]
    true_passes = [case for case in eligible if case["truth_success"] is True]
    defect_probes = [case for case in true_failures if case["defect_injected"]]
    false_passes = [case for case in true_failures if case["judge_pass"] is True]
    false_fails = [case for case in true_passes if case["judge_pass"] is False]
    false_pass_rate = _rate(len(false_passes), len(true_failures))
    failure_recall = _rate(len(true_failures) - len(false_passes), len(true_failures))
    false_fail_rate = _rate(len(false_fails), len(true_passes))
    judge_groups = defaultdict(list)
    for case in eligible:
        judge_groups[case["judge_id"]].append(case)
    judge_profiles = [
        _judge_calibration_summary(judge_id, group, thresholds)
        for judge_id, group in sorted(judge_groups.items())
    ]
    errors = list(load_errors or [])

    report = {
        "type": "skill_verifier_calibration_report",
        "schema_version": SCHEMA_VERSION,
        "research_basis": ["blind_curator_false_pass_calibration"],
        "readiness": "review",
        "decision": "keep_skill_retirement_review_only",
        "reason": "verifier calibration requires eligible defect-injection evidence",
        "runtime_eligible": False,
        "thresholds": thresholds,
        "case_count": len(normalized),
        "evidence_candidate_count": len(evidence_cases),
        "eligible_case_count": len(eligible),
        "provenance_complete_case_count": sum(1 for case in evidence_cases if case["provenance_complete"]),
        "live_case_count": sum(1 for case in eligible if case["evidence_kind"] == "live_trace"),
        "defect_probe_count": len(defect_probes),
        "true_failure_count": len(true_failures),
        "control_pass_count": len(true_passes),
        "false_pass_count": len(false_passes),
        "false_pass_rate": false_pass_rate,
        "failure_detection_recall": failure_recall,
        "false_fail_count": len(false_fails),
        "false_fail_rate": false_fail_rate,
        "judge_ids": sorted({case["judge_id"] for case in eligible if case["judge_id"]}),
        "verifier_ids": sorted({case["verifier_id"] for case in eligible if case["verifier_id"]}),
        "approved_judge_ids": [],
        "judges": judge_profiles,
        "ineligible_case_count": len(normalized) - len(eligible),
        "case_summaries": [_calibration_case_summary(case) for case in normalized],
        "policy_hints": [
            "use_defect_injection_to_measure_false_pass_bias",
            "never_retire_or_delete_skills_from_an_uncalibrated_judge",
        ],
        "errors": errors,
    }

    if errors:
        report.update({
            "readiness": "error",
            "decision": "do_not_soft_quarantine_skills",
            "reason": "calibration case files could not be loaded",
        })
    elif not evidence_cases:
        report["reason"] = "no runtime-eligible calibration evidence was supplied"
    elif len(eligible) != len(evidence_cases):
        report["reason"] = "calibration evidence is missing outcomes, fixed controls, or provenance"
    elif any(profile["readiness"] == "rejected" for profile in judge_profiles):
        report.update({
            "readiness": "rejected",
            "decision": "do_not_soft_quarantine_skills",
            "reason": "at least one judge exceeds the false-pass retirement safety threshold",
        })
    elif not judge_profiles or any(profile["readiness"] != "approved" for profile in judge_profiles):
        report["reason"] = "each judge needs enough live defect and control evidence"
    else:
        report.update({
            "readiness": "approved",
            "decision": "allow_judge_for_soft_retirement_audits",
            "reason": "defect injection shows acceptable false-pass behavior under fixed controls",
            "runtime_eligible": True,
            "approved_judge_ids": [profile["judge_id"] for profile in judge_profiles],
        })
    return report


def build_skill_contribution_report(
    cases: list[dict],
    *,
    require_live_evidence: bool = True,
    min_paired_cases: int = 3,
    min_baseline_trials: int = 3,
    min_candidate_trials: int = 3,
    min_distinct_candidate_sessions: int = 3,
    min_verified_candidate_failures: int = 2,
    min_negative_delta: float = 0.20,
    load_errors: Optional[list[str]] = None,
) -> dict:
    """Compare each learned skill with a fixed-control no-skill baseline."""
    thresholds = {
        "require_live_evidence": bool(require_live_evidence),
        "min_paired_cases": max(1, _as_int(min_paired_cases, 3)),
        "min_baseline_trials": max(1, _as_int(min_baseline_trials, 3)),
        "min_candidate_trials": max(1, _as_int(min_candidate_trials, 3)),
        "min_distinct_candidate_sessions": max(1, _as_int(min_distinct_candidate_sessions, 3)),
        "min_verified_candidate_failures": max(1, _as_int(min_verified_candidate_failures, 2)),
        "min_negative_delta": max(0.0, min(1.0, abs(_as_float(min_negative_delta, 0.20)))),
    }
    normalized = [_normalize_contribution_case(case, index) for index, case in enumerate(cases or [], start=1)]
    grouped = defaultdict(list)
    for case in normalized:
        if case["skill"]:
            grouped[(case["skill"], case["task_family"])].append(case)

    skills = []
    for (skill, task_family), group in sorted(grouped.items()):
        skills.append(_skill_contribution_summary(skill, task_family, group, thresholds))

    errors = list(load_errors or [])
    ready_profiles = [item for item in skills if item["candidate_readiness"] in {"ready", "retain"}]
    candidates = [item for item in skills if item["candidate_readiness"] == "ready"]
    evidence_cases = [case for case in normalized if _evidence_allowed(case, thresholds["require_live_evidence"])]
    report = {
        "type": "skill_contribution_report",
        "schema_version": SCHEMA_VERSION,
        "research_basis": ["blind_curator_no_skill_contribution_baseline"],
        "readiness": "review",
        "decision": "keep_skill_retirement_review_only",
        "reason": "skill contribution requires fixed-control baseline evidence",
        "runtime_eligible": False,
        "thresholds": thresholds,
        "case_count": len(normalized),
        "evidence_candidate_count": len(evidence_cases),
        "eligible_case_count": sum(item["eligible_pair_count"] for item in skills),
        "skill_count": len(skills),
        "evaluated_skill_count": len(ready_profiles),
        "soft_quarantine_candidate_count": len(candidates),
        "retain_skill_count": sum(1 for item in skills if item["candidate_readiness"] == "retain"),
        "review_skill_count": sum(1 for item in skills if item["candidate_readiness"] == "review"),
        "skills": skills,
        "case_summaries": [_contribution_case_summary(case) for case in normalized],
        "policy_hints": [
            "compare_each_skill_with_a_fixed_no_skill_baseline",
            "require_verifier_backed_failures_and_distinct_sessions",
            "soft_quarantine_only_never_delete_skill_files",
        ],
        "errors": errors,
    }
    if errors:
        report.update({
            "readiness": "error",
            "decision": "do_not_soft_quarantine_skills",
            "reason": "contribution case files could not be loaded",
        })
    elif not evidence_cases:
        report["reason"] = "no runtime-eligible contribution evidence was supplied"
    elif not ready_profiles:
        report["reason"] = "no skill has enough fixed-control contribution evidence"
    else:
        report.update({
            "readiness": "ready",
            "decision": "emit_reviewable_soft_quarantine_candidates",
            "reason": "fixed-control skill contribution estimates are available",
            "runtime_eligible": all(item["runtime_eligible"] for item in ready_profiles),
        })
    return report


def build_skill_retirement_gate(
    *,
    calibration_reports: Optional[list[dict]] = None,
    calibration_report_paths: Optional[list[str]] = None,
    contribution_reports: Optional[list[dict]] = None,
    contribution_report_paths: Optional[list[str]] = None,
    require_live_evidence: bool = True,
    min_distinct_candidate_sessions: int = 3,
    min_paired_cases: int = 3,
    min_verified_candidate_failures: int = 2,
    min_negative_delta: float = 0.20,
) -> dict:
    """Approve a read-only runtime overlay only after both evidence stages pass."""
    calibration_items, calibration_errors = _load_reports(
        calibration_reports or [], calibration_report_paths or [], "skill_verifier_calibration_report"
    )
    contribution_items, contribution_errors = _load_reports(
        contribution_reports or [], contribution_report_paths or [], "skill_contribution_report"
    )
    errors = calibration_errors + contribution_errors
    thresholds = {
        "require_live_evidence": bool(require_live_evidence),
        "min_distinct_candidate_sessions": max(1, _as_int(min_distinct_candidate_sessions, 3)),
        "min_paired_cases": max(1, _as_int(min_paired_cases, 3)),
        "min_verified_candidate_failures": max(1, _as_int(min_verified_candidate_failures, 2)),
        "min_negative_delta": max(0.0, min(1.0, abs(_as_float(min_negative_delta, 0.20)))),
    }

    judge_states = defaultdict(list)
    calibration_summaries = []
    for source, payload in calibration_items:
        readiness = str(payload.get("readiness") or "unknown").strip().lower()
        runtime_eligible = payload.get("runtime_eligible") is True
        live_ok = (
            not thresholds["require_live_evidence"]
            or _as_int(payload.get("live_case_count")) == _as_int(payload.get("eligible_case_count")) > 0
        )
        summary = {
            "source": source,
            "readiness": readiness,
            "runtime_eligible": runtime_eligible,
            "live_evidence_complete": live_ok,
            "false_pass_rate": payload.get("false_pass_rate"),
            "failure_detection_recall": payload.get("failure_detection_recall"),
            "judge_ids": _strings(payload.get("judge_ids", [])),
            "approved_judge_ids": _strings(payload.get("approved_judge_ids", [])),
        }
        calibration_summaries.append(summary)
        for judge_id in summary["judge_ids"]:
            judge_states[judge_id].append(
                readiness == "approved"
                and runtime_eligible
                and live_ok
                and judge_id in summary["approved_judge_ids"]
            )
    approved_judges = sorted(judge for judge, states in judge_states.items() if states and all(states))

    candidates = []
    contribution_summaries = []
    for source, payload in contribution_items:
        contribution_summaries.append({
            "source": source,
            "readiness": str(payload.get("readiness") or "unknown").strip().lower(),
            "runtime_eligible": payload.get("runtime_eligible") is True,
            "soft_quarantine_candidate_count": _as_int(payload.get("soft_quarantine_candidate_count")),
        })
        for item in payload.get("skills", []) if isinstance(payload.get("skills"), list) else []:
            if not isinstance(item, dict) or item.get("candidate_readiness") != "ready":
                continue
            candidates.append(_retirement_gate_candidate(source, item, approved_judges, thresholds))

    approved = [item for item in candidates if item["candidate_readiness"] == "approved"]
    review = [item for item in candidates if item["candidate_readiness"] == "review"]
    rejected_calibration = any(item["readiness"] in {"rejected", "error"} for item in calibration_summaries)
    report = {
        "type": "skill_retirement_gate",
        "schema_version": SCHEMA_VERSION,
        "research_basis": [
            "blind_curator_false_pass_calibration",
            "fixed_control_no_skill_contribution_baseline",
            "runtime_overlay_without_file_mutation",
        ],
        "readiness": "review",
        "decision": "keep_skills_active_pending_retirement_review",
        "reason": "soft retirement requires calibrated judges and negative contribution evidence",
        "soft_quarantine_allowed": False,
        "automatic_delete_allowed": False,
        "deletion_policy": "prohibited",
        "thresholds": thresholds,
        "calibration_report_count": len(calibration_items),
        "contribution_report_count": len(contribution_items),
        "approved_judge_ids": approved_judges,
        "candidate_count": len(candidates),
        "approved_candidate_count": len(approved),
        "review_candidate_count": len(review),
        "candidates": candidates,
        "calibration_reports": calibration_summaries,
        "contribution_reports": contribution_summaries,
        "policy_hints": [
            "apply_quarantine_as_a_read_only_runtime_overlay",
            "retain_skill_files_and_evidence_for_review_and_recovery",
            "recalibrate_judges_before_contribution_based_retirement",
        ],
        "errors": errors,
    }
    if errors:
        report.update({
            "readiness": "error",
            "decision": "do_not_soft_quarantine_skills",
            "reason": "retirement gate inputs could not be loaded or validated",
        })
    elif not calibration_items or not contribution_items:
        report["reason"] = "both calibration and contribution reports are required"
    elif rejected_calibration and not approved_judges:
        report.update({
            "readiness": "rejected",
            "decision": "do_not_soft_quarantine_skills",
            "reason": "verifier calibration rejects contribution-based retirement",
        })
    elif not candidates:
        report["reason"] = "no negative-contribution skill candidate was supplied"
    elif not approved:
        report["reason"] = "retirement candidates are missing calibrated, live, fixed-control evidence"
    else:
        report.update({
            "readiness": "approved",
            "decision": "allow_read_only_skill_soft_quarantine",
            "reason": "calibrated judges and fixed-control contribution evidence support runtime-only quarantine",
            "soft_quarantine_allowed": True,
        })
    return report


def save_report(report: dict, path: str) -> str:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)
    return path


def print_verifier_calibration_report(report: dict):
    print("\nSkill Verifier Calibration")
    print(f"  readiness: {report.get('readiness', 'unknown')}")
    print(f"  decision: {report.get('decision', '')}")
    print(f"  reason: {report.get('reason', '')}")
    print(
        "  evidence: "
        f"eligible={report.get('eligible_case_count', 0)}/{report.get('case_count', 0)}, "
        f"defects={report.get('defect_probe_count', 0)}, live={report.get('live_case_count', 0)}"
    )
    print(
        "  bias: "
        f"false_pass={_format_rate(report.get('false_pass_rate'))}, "
        f"failure_recall={_format_rate(report.get('failure_detection_recall'))}, "
        f"false_fail={_format_rate(report.get('false_fail_rate'))}"
    )
    for error in report.get("errors", []):
        print(f"  error: {error}")


def print_skill_contribution_report(report: dict):
    print("\nSkill Contribution Report")
    print(f"  readiness: {report.get('readiness', 'unknown')}")
    print(f"  decision: {report.get('decision', '')}")
    print(f"  reason: {report.get('reason', '')}")
    print(
        "  skills: "
        f"evaluated={report.get('evaluated_skill_count', 0)}/{report.get('skill_count', 0)}, "
        f"quarantine_candidates={report.get('soft_quarantine_candidate_count', 0)}, "
        f"retain={report.get('retain_skill_count', 0)}"
    )
    for item in report.get("skills", [])[:12]:
        marker = "+" if item.get("candidate_readiness") == "ready" else "=" if item.get("candidate_readiness") == "retain" else "!"
        print(
            f"  [{marker}] {item.get('skill')} ({item.get('task_family') or 'any'}): "
            f"{item.get('candidate_readiness')} delta={item.get('contribution_delta')} "
            f"sessions={item.get('distinct_candidate_session_count', 0)}"
        )
    for error in report.get("errors", []):
        print(f"  error: {error}")


def print_skill_retirement_gate(report: dict):
    print("\nSkill Retirement Gate")
    print(f"  readiness: {report.get('readiness', 'unknown')}")
    print(f"  decision: {report.get('decision', '')}")
    print(f"  reason: {report.get('reason', '')}")
    print(
        "  policy: "
        f"soft_quarantine={report.get('soft_quarantine_allowed') is True}, "
        f"automatic_delete={report.get('automatic_delete_allowed') is True}"
    )
    print(
        "  candidates: "
        f"approved={report.get('approved_candidate_count', 0)}, "
        f"review={report.get('review_candidate_count', 0)}"
    )
    for item in report.get("candidates", [])[:12]:
        marker = "+" if item.get("candidate_readiness") == "approved" else "!"
        print(
            f"  [{marker}] {item.get('skill')} ({item.get('task_family') or 'any'}): "
            f"{item.get('candidate_readiness')}"
        )
        if item.get("issues"):
            print(f"      issues: {', '.join(item.get('issues', []))}")
    for error in report.get("errors", []):
        print(f"  error: {error}")


def _normalize_calibration_case(case: dict, index: int) -> dict:
    case = case if isinstance(case, dict) else {}
    truth_success = _as_optional_bool(case.get("truth_success", case.get("ground_truth_success")))
    judge_pass = _as_optional_bool(case.get("judge_pass", case.get("verifier_pass")))
    source = str(case.get("source") or "").strip()[:300]
    evidence_kind = str(case.get("evidence_kind") or "unknown").strip().lower()[:64]
    normalized = {
        "case_id": str(case.get("id") or case.get("case_id") or f"calibration-{index}")[:96],
        "truth_success": truth_success,
        "judge_pass": judge_pass,
        "defect_injected": case.get("defect_injected") is True,
        "judge_id": str(case.get("judge_id") or "").strip()[:96],
        "verifier_id": str(case.get("verifier_id") or "").strip()[:96],
        "task_stream_id": str(case.get("task_stream_id") or "").strip()[:96],
        "session_id": str(case.get("session_id") or "").strip()[:96],
        "seed": str(case.get("seed") or "").strip()[:64],
        "source": source,
        "evidence_kind": evidence_kind,
        "non_verifier_modules_fixed": case.get("non_verifier_modules_fixed") is True,
        "builtin_fixture": source.casefold() == "builtin" or case.get("builtin_fixture") is True,
    }
    normalized["provenance_complete"] = bool(
        normalized["source"]
        and not normalized["builtin_fixture"]
        and all(normalized[key] for key in ("judge_id", "verifier_id", "task_stream_id", "session_id", "seed"))
    )
    normalized["eligible"] = bool(
        truth_success is not None
        and judge_pass is not None
        and normalized["non_verifier_modules_fixed"]
        and normalized["provenance_complete"]
    )
    return normalized


def _normalize_contribution_case(case: dict, index: int) -> dict:
    case = case if isinstance(case, dict) else {}
    baseline_trials = _trial_value(case, "baseline_trials", "baseline_success", default=1)
    candidate_trials = _trial_value(case, "candidate_trials", "candidate_success", default=1)
    baseline_successes = _success_value(case, "baseline_successes", "baseline_success", baseline_trials)
    candidate_successes = _success_value(case, "candidate_successes", "candidate_success", candidate_trials)
    source = str(case.get("source") or "").strip()[:300]
    normalized = {
        "case_id": str(case.get("id") or case.get("case_id") or f"contribution-{index}")[:96],
        "skill": str(case.get("skill") or case.get("skill_name") or "").strip()[:128],
        "task_family": str(case.get("task_family") or "").strip().lower()[:64],
        "baseline_successes": min(baseline_trials, max(0, baseline_successes)),
        "baseline_trials": max(0, baseline_trials),
        "candidate_successes": min(candidate_trials, max(0, candidate_successes)),
        "candidate_trials": max(0, candidate_trials),
        "candidate_failure_verified_count": max(0, _as_int(case.get("candidate_failure_verified_count"))),
        "baseline_session_id": str(case.get("baseline_session_id") or "").strip()[:96],
        "candidate_session_id": str(case.get("candidate_session_id") or "").strip()[:96],
        "judge_id": str(case.get("judge_id") or "").strip()[:96],
        "verifier_id": str(case.get("verifier_id") or "").strip()[:96],
        "planner_id": str(case.get("planner_id") or "").strip()[:96],
        "action_backend": str(case.get("action_backend") or "").strip()[:96],
        "task_stream_id": str(case.get("task_stream_id") or "").strip()[:96],
        "seed": str(case.get("seed") or "").strip()[:64],
        "source": source,
        "evidence_kind": str(case.get("evidence_kind") or "unknown").strip().lower()[:64],
        "no_skill_baseline": case.get("no_skill_baseline") is True,
        "non_skill_modules_fixed": case.get("non_skill_modules_fixed") is True,
        "built_in": case.get("built_in") is True,
        "builtin_fixture": source.casefold() == "builtin" or case.get("builtin_fixture") is True,
    }
    candidate_failures = normalized["candidate_trials"] - normalized["candidate_successes"]
    if case.get("candidate_failure_verified") is True and not normalized["candidate_failure_verified_count"]:
        normalized["candidate_failure_verified_count"] = candidate_failures
    normalized["candidate_failure_verified_count"] = min(
        candidate_failures, normalized["candidate_failure_verified_count"]
    )
    provenance_fields = (
        "source", "judge_id", "verifier_id", "planner_id", "action_backend", "task_stream_id",
        "seed", "baseline_session_id", "candidate_session_id",
    )
    normalized["provenance_complete"] = bool(
        all(normalized[field] for field in provenance_fields)
        and not normalized["builtin_fixture"]
        and normalized["baseline_session_id"] != normalized["candidate_session_id"]
    )
    normalized["eligible"] = bool(
        normalized["skill"]
        and normalized["baseline_trials"] > 0
        and normalized["candidate_trials"] > 0
        and normalized["no_skill_baseline"]
        and normalized["non_skill_modules_fixed"]
        and normalized["provenance_complete"]
    )
    return normalized


def _skill_contribution_summary(skill: str, task_family: str, group: list[dict], thresholds: dict) -> dict:
    evidence = [case for case in group if _evidence_allowed(case, thresholds["require_live_evidence"])]
    eligible = [case for case in evidence if case["eligible"]]
    baseline_trials = sum(case["baseline_trials"] for case in eligible)
    baseline_successes = sum(case["baseline_successes"] for case in eligible)
    candidate_trials = sum(case["candidate_trials"] for case in eligible)
    candidate_successes = sum(case["candidate_successes"] for case in eligible)
    baseline_rate = _rate(baseline_successes, baseline_trials)
    candidate_rate = _rate(candidate_successes, candidate_trials)
    delta = None if baseline_rate is None or candidate_rate is None else round(candidate_rate - baseline_rate, 6)
    sessions = sorted({case["candidate_session_id"] for case in eligible if case["candidate_session_id"]})
    judge_ids = sorted({case["judge_id"] for case in eligible if case["judge_id"]})
    verifier_ids = sorted({case["verifier_id"] for case in eligible if case["verifier_id"]})
    verified_failures = sum(case["candidate_failure_verified_count"] for case in eligible)
    enough_evidence = bool(
        len(eligible) >= thresholds["min_paired_cases"]
        and baseline_trials >= thresholds["min_baseline_trials"]
        and candidate_trials >= thresholds["min_candidate_trials"]
        and len(sessions) >= thresholds["min_distinct_candidate_sessions"]
    )
    negative = delta is not None and delta <= -thresholds["min_negative_delta"]
    candidate_ready = enough_evidence and negative and verified_failures >= thresholds["min_verified_candidate_failures"]
    if candidate_ready:
        readiness = "ready"
        decision = "propose_read_only_soft_quarantine"
        reason = "skill underperforms its fixed no-skill baseline with verifier-backed failures"
    elif enough_evidence and delta is not None and delta >= 0:
        readiness = "retain"
        decision = "keep_skill_active"
        reason = "skill contribution is non-negative under fixed controls"
    else:
        readiness = "review"
        decision = "collect_more_fixed_control_evidence"
        reason = "skill contribution evidence does not meet the soft-quarantine threshold"
    return {
        "skill": skill,
        "task_family": task_family,
        "built_in": any(case["built_in"] for case in group),
        "candidate_readiness": readiness,
        "decision": decision,
        "reason": reason,
        "runtime_eligible": bool(eligible) and all(case["evidence_kind"] == "live_trace" for case in eligible),
        "pair_count": len(group),
        "evidence_pair_count": len(evidence),
        "eligible_pair_count": len(eligible),
        "provenance_complete_pair_count": sum(1 for case in evidence if case["provenance_complete"]),
        "fixed_control_pair_count": sum(1 for case in evidence if case["non_skill_modules_fixed"]),
        "no_skill_baseline_pair_count": sum(1 for case in evidence if case["no_skill_baseline"]),
        "live_pair_count": sum(1 for case in eligible if case["evidence_kind"] == "live_trace"),
        "baseline_successes": baseline_successes,
        "baseline_trials": baseline_trials,
        "baseline_success_rate": baseline_rate,
        "candidate_successes": candidate_successes,
        "candidate_trials": candidate_trials,
        "candidate_success_rate": candidate_rate,
        "contribution_delta": delta,
        "verified_candidate_failure_count": verified_failures,
        "distinct_candidate_session_count": len(sessions),
        "candidate_session_ids": sessions,
        "judge_ids": judge_ids,
        "verifier_ids": verifier_ids,
        "evidence_kinds": sorted({case["evidence_kind"] for case in eligible}),
        "sources": sorted({case["source"] for case in eligible}),
    }


def _judge_calibration_summary(judge_id: str, cases: list[dict], thresholds: dict) -> dict:
    true_failures = [case for case in cases if case["truth_success"] is False]
    true_passes = [case for case in cases if case["truth_success"] is True]
    defect_probes = [case for case in true_failures if case["defect_injected"]]
    false_passes = [case for case in true_failures if case["judge_pass"] is True]
    false_fails = [case for case in true_passes if case["judge_pass"] is False]
    false_pass_rate = _rate(len(false_passes), len(true_failures))
    failure_recall = _rate(len(true_failures) - len(false_passes), len(true_failures))
    runtime_eligible = bool(cases) and all(case["evidence_kind"] == "live_trace" for case in cases)
    readiness = "review"
    reason = "judge needs more live defect and control evidence"
    if (
        len(defect_probes) >= thresholds["min_defect_probes"]
        and len(true_passes) >= thresholds["min_control_passes"]
        and false_pass_rate is not None
        and failure_recall is not None
    ):
        if (
            false_pass_rate > thresholds["max_false_pass_rate"]
            or failure_recall < thresholds["min_failure_detection_recall"]
        ):
            readiness = "rejected"
            reason = "judge false-pass bias exceeds the retirement safety threshold"
        elif runtime_eligible:
            readiness = "approved"
            reason = "judge detects injected failures within the configured threshold"
        else:
            reason = "judge calibration is offline-only until live evidence is supplied"
    return {
        "judge_id": judge_id,
        "readiness": readiness,
        "reason": reason,
        "runtime_eligible": runtime_eligible,
        "case_count": len(cases),
        "defect_probe_count": len(defect_probes),
        "control_pass_count": len(true_passes),
        "false_pass_count": len(false_passes),
        "false_pass_rate": false_pass_rate,
        "failure_detection_recall": failure_recall,
        "false_fail_count": len(false_fails),
        "false_fail_rate": _rate(len(false_fails), len(true_passes)),
        "verifier_ids": sorted({case["verifier_id"] for case in cases if case["verifier_id"]}),
    }


def _retirement_gate_candidate(source: str, item: dict, approved_judges: list[str], thresholds: dict) -> dict:
    issues = []
    eligible_pairs = _as_int(item.get("eligible_pair_count"))
    session_ids = _strings(item.get("candidate_session_ids", []))
    judge_ids = _strings(item.get("judge_ids", []))
    evidence_kinds = _strings(item.get("evidence_kinds", []))
    delta = _as_optional_float(item.get("contribution_delta"))
    if item.get("built_in") is True:
        issues.append("built_in_skills_cannot_be_soft_quarantined")
    if item.get("runtime_eligible") is not True:
        issues.append("contribution_evidence_is_not_runtime_eligible")
    if eligible_pairs < thresholds["min_paired_cases"]:
        issues.append("insufficient_paired_cases")
    if len(session_ids) < thresholds["min_distinct_candidate_sessions"]:
        issues.append("insufficient_distinct_candidate_sessions")
    if _as_int(item.get("provenance_complete_pair_count")) < eligible_pairs:
        issues.append("incomplete_provenance")
    if _as_int(item.get("fixed_control_pair_count")) < eligible_pairs:
        issues.append("non_skill_modules_not_fixed")
    if _as_int(item.get("no_skill_baseline_pair_count")) < eligible_pairs:
        issues.append("missing_no_skill_baseline")
    if _as_int(item.get("verified_candidate_failure_count")) < thresholds["min_verified_candidate_failures"]:
        issues.append("insufficient_verifier_backed_failures")
    if delta is None or delta > -thresholds["min_negative_delta"]:
        issues.append("negative_contribution_threshold_not_met")
    if not judge_ids or any(judge_id not in approved_judges for judge_id in judge_ids):
        issues.append("judge_not_approved_by_calibration")
    if thresholds["require_live_evidence"] and (
        evidence_kinds != ["live_trace"] or _as_int(item.get("live_pair_count")) != eligible_pairs
    ):
        issues.append("live_evidence_required")
    readiness = "approved" if not issues else "review"
    return {
        "skill": str(item.get("skill") or "")[:128],
        "task_family": str(item.get("task_family") or "").strip().lower()[:64],
        "source": source,
        "candidate_readiness": readiness,
        "decision": "soft_quarantine_runtime_overlay" if readiness == "approved" else "keep_skill_active_pending_review",
        "reason": (
            "calibrated contribution evidence allows read-only runtime quarantine"
            if readiness == "approved"
            else "retirement evidence is incomplete or ineligible"
        ),
        "issues": issues,
        "contribution_delta": delta,
        "eligible_pair_count": eligible_pairs,
        "verified_candidate_failure_count": _as_int(item.get("verified_candidate_failure_count")),
        "candidate_session_ids": session_ids,
        "judge_ids": judge_ids,
        "verifier_ids": _strings(item.get("verifier_ids", [])),
        "automatic_delete_allowed": False,
    }


def _load_reports(payloads: list[dict], paths: list[str], expected_type: str) -> tuple[list[tuple[str, dict]], list[str]]:
    items = []
    errors = []
    for index, payload in enumerate(payloads, start=1):
        if not isinstance(payload, dict):
            errors.append(f"inline:{index}: report is not an object")
            continue
        items.append((f"inline:{index}", payload))
    for path in paths:
        try:
            with open(path, "r", encoding="utf-8-sig") as handle:
                payload = json.load(handle)
            if not isinstance(payload, dict):
                raise ValueError("report is not an object")
            items.append((path, payload))
        except Exception as error:
            errors.append(f"{path}: {error}")
    valid = []
    for source, payload in items:
        if payload.get("type") != expected_type or _as_int(payload.get("schema_version")) != SCHEMA_VERSION:
            errors.append(f"{source}: expected {expected_type} schema {SCHEMA_VERSION}")
            continue
        valid.append((source, payload))
    return valid, errors


def _evidence_allowed(case: dict, require_live: bool) -> bool:
    if case.get("builtin_fixture"):
        return False
    kind = str(case.get("evidence_kind") or "").strip().lower()
    return kind == "live_trace" if require_live else kind not in {"", "unknown", "builtin"}


def _calibration_case_summary(case: dict) -> dict:
    return {
        "case_id": case["case_id"],
        "truth_success": case["truth_success"],
        "judge_pass": case["judge_pass"],
        "defect_injected": case["defect_injected"],
        "judge_id": case["judge_id"],
        "verifier_id": case["verifier_id"],
        "evidence_kind": case["evidence_kind"],
        "provenance_complete": case["provenance_complete"],
        "eligible": case["eligible"] and not case["builtin_fixture"],
    }


def _contribution_case_summary(case: dict) -> dict:
    return {
        "case_id": case["case_id"],
        "skill": case["skill"],
        "task_family": case["task_family"],
        "baseline_successes": case["baseline_successes"],
        "baseline_trials": case["baseline_trials"],
        "candidate_successes": case["candidate_successes"],
        "candidate_trials": case["candidate_trials"],
        "candidate_failure_verified_count": case["candidate_failure_verified_count"],
        "evidence_kind": case["evidence_kind"],
        "provenance_complete": case["provenance_complete"],
        "eligible": case["eligible"] and not case["builtin_fixture"],
    }


def _trial_value(case: dict, count_key: str, bool_key: str, default: int) -> int:
    if count_key in case:
        return max(0, _as_int(case.get(count_key)))
    if bool_key in case:
        return 1
    return default


def _success_value(case: dict, count_key: str, bool_key: str, trials: int) -> int:
    if count_key in case:
        return max(0, _as_int(case.get(count_key)))
    value = _as_optional_bool(case.get(bool_key))
    return trials if value is True else 0


def _as_optional_bool(value) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value or "").strip().lower()
    if text in {"true", "pass", "passed", "success", "succeeded", "achieved", "1"}:
        return True
    if text in {"false", "fail", "failed", "failure", "rejected", "0"}:
        return False
    return None


def _as_int(value, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _as_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_optional_float(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clamp_rate(value, default: float) -> float:
    return max(0.0, min(1.0, _as_float(value, default)))


def _rate(numerator: int, denominator: int) -> Optional[float]:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 6)


def _strings(values) -> list[str]:
    if not isinstance(values, list):
        return []
    return sorted({str(value or "").strip()[:128] for value in values if str(value or "").strip()})


def _format_rate(value) -> str:
    number = _as_optional_float(value)
    return "n/a" if number is None else f"{number:.3f}"
