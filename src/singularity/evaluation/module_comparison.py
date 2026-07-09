"""Offline Orak-style comparison for optional agent modules."""

from __future__ import annotations

import json
import os
import time
from typing import Any


MODULE_ORDER = [
    "plan_cache",
    "visual_action_grounding",
    "action_verification",
    "action_candidate_selection",
    "skill_memory",
    "policy_skill",
    "memory_policy",
    "goal_verification",
    "control_policy",
]


def build_agent_module_comparison_report(
    baseline_log_paths: list[str],
    candidate_log_paths: list[str],
    baseline_label: str = "baseline",
    candidate_label: str = "candidate",
    max_completion_regression: float = 0.0,
    max_action_failure_regression: float = 0.10,
    max_verifier_reject_regression: float = 0.10,
    max_empty_plan_regression: float = 0.10,
) -> dict:
    """Compare baseline and candidate session logs as module-level experiment units."""
    thresholds = {
        "max_completion_regression": float(max_completion_regression),
        "max_action_failure_regression": float(max_action_failure_regression),
        "max_verifier_reject_regression": float(max_verifier_reject_regression),
        "max_empty_plan_regression": float(max_empty_plan_regression),
    }
    baseline = summarize_agent_module_logs(baseline_log_paths, baseline_label)
    candidate = summarize_agent_module_logs(candidate_log_paths, candidate_label)
    deltas = _summary_deltas(baseline, candidate)
    module_deltas = _module_deltas(baseline, candidate)
    module_activity = _module_activity(baseline, candidate, module_deltas)
    checks = _comparison_checks(baseline, candidate, deltas, module_activity, thresholds)
    readiness, decision, reason = _comparison_decision(checks)
    recommendations = _comparison_recommendations(candidate, deltas, module_activity, readiness)
    return {
        "type": "agent_module_comparison_report",
        "generated_at": round(time.time(), 3),
        "baseline_label": baseline_label,
        "candidate_label": candidate_label,
        "thresholds": thresholds,
        "baseline": baseline,
        "candidate": candidate,
        "deltas": deltas,
        "module_deltas": module_deltas,
        "module_activity": module_activity,
        "checks": checks,
        "readiness": readiness,
        "decision": decision,
        "reason": reason,
        "recommendations": recommendations,
    }


def summarize_agent_module_logs(session_log_paths: list[str], label: str = "") -> dict:
    """Summarize module signals from one group of session JSONL logs."""
    summary = _empty_summary(label, session_log_paths)
    for path in session_log_paths:
        if not path:
            continue
        if not os.path.exists(path):
            summary["errors"].append(f"{path}: missing")
            continue
        summary["readable_log_count"] += 1
        source = {"path": path, "event_count": 0, "invalid_json_count": 0}
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                for line_number, line in enumerate(f, 1):
                    if not line.strip():
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        source["invalid_json_count"] += 1
                        summary["invalid_json_count"] += 1
                        continue
                    if not isinstance(event, dict):
                        source["invalid_json_count"] += 1
                        summary["invalid_json_count"] += 1
                        continue
                    source["event_count"] += 1
                    _ingest_event(summary, event)
        except OSError as exc:
            summary["errors"].append(f"{path}: {exc}")
            continue
        summary["sources"].append(source)
    _finalize_summary(summary)
    return summary


def write_agent_module_comparison_report(report: dict, output_path: str):
    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)


def _empty_summary(label: str, session_log_paths: list[str]) -> dict:
    return {
        "label": label,
        "requested_log_count": len(session_log_paths),
        "readable_log_count": 0,
        "session_log_paths": list(session_log_paths),
        "sources": [],
        "errors": [],
        "invalid_json_count": 0,
        "event_count": 0,
        "event_type_counts": {},
        "goal_start_count": 0,
        "goal_end_count": 0,
        "completed_goal_count": 0,
        "failed_goal_count": 0,
        "completion_rate": 0.0,
        "action_count": 0,
        "action_success_count": 0,
        "action_failure_count": 0,
        "action_unknown_count": 0,
        "action_failure_rate": 0.0,
        "plan_count": 0,
        "blocked_plan_count": 0,
        "empty_plan_count": 0,
        "empty_plan_rate": 0.0,
        "module_activity_count": 0,
        "active_modules": [],
        "modules": {
            "plan_cache": {
                "hit_count": 0,
                "miss_count": 0,
                "query_count": 0,
                "signature_count": 0,
                "hit_rate": 0.0,
                "activity_count": 0,
            },
            "visual_action_grounding": {
                "suggestion_event_count": 0,
                "suggestion_count": 0,
                "intervention_count": 0,
                "intervention_phases": {},
                "suggestion_kinds": {},
                "intervention_kinds": {},
                "action_types": {},
                "activity_count": 0,
            },
            "action_verification": {
                "event_count": 0,
                "accept_count": 0,
                "reject_count": 0,
                "review_count": 0,
                "unknown_count": 0,
                "reject_rate": 0.0,
                "status_counts": {},
                "action_types": {},
                "activity_count": 0,
            },
            "action_candidate_selection": {
                "event_count": 0,
                "repaired_reject_count": 0,
                "repair_rate": 0.0,
                "selected_types": {},
                "activity_count": 0,
            },
            "skill_memory": {
                "hint_event_count": 0,
                "hint_count": 0,
                "task_families": {},
                "activity_count": 0,
            },
            "policy_skill": {
                "hint_event_count": 0,
                "intervention_count": 0,
                "action_count": 0,
                "success_count": 0,
                "failure_count": 0,
                "success_rate": 0.0,
                "skills": [],
                "activity_count": 0,
            },
            "memory_policy": {
                "write_count": 0,
                "read_count": 0,
                "manage_count": 0,
                "read_filter_event_count": 0,
                "read_filtered_entries": 0,
                "policy_decisions": {},
                "read_filter_reasons": {},
                "activity_count": 0,
            },
            "goal_verification": {
                "event_count": 0,
                "achieved_count": 0,
                "failed_count": 0,
                "unknown_count": 0,
                "accepted_count": 0,
                "rejected_count": 0,
                "accept_rate": 0.0,
                "acceptance_reasons": {},
                "activity_count": 0,
            },
            "control_policy": {
                "event_count": 0,
                "fallback_count": 0,
                "backend_counts": {},
                "preferred_control_counts": {},
                "fallback_reasons": {},
                "action_backend_counts": {},
                "activity_count": 0,
            },
        },
    }


def _ingest_event(summary: dict, event: dict):
    event_type = str(event.get("type") or "unknown")
    data = event.get("data", {}) if isinstance(event.get("data", {}), dict) else {}
    summary["event_count"] += 1
    _increment(summary["event_type_counts"], event_type)

    if event_type == "goal_start":
        summary["goal_start_count"] += 1
    elif event_type in {"goal_end", "auto_goal_complete", "auto_goal_failed"}:
        summary["goal_end_count"] += 1
        completed = _goal_completed(event_type, data)
        if completed is True:
            summary["completed_goal_count"] += 1
        elif completed is False:
            summary["failed_goal_count"] += 1
    elif event_type == "plan":
        _ingest_plan(summary, data)
    elif event_type == "action":
        _ingest_action(summary, data)
    elif event_type in {"plan_cache_hit", "plan_cache_miss", "plan_cache_signature"}:
        _ingest_plan_cache(summary, event_type)
    elif event_type in {"visual_action_suggestion", "visual_action_intervention"}:
        _ingest_visual_action(summary, event_type, data)
    elif event_type == "action_verification":
        _ingest_action_verification(summary, data)
    elif event_type == "action_candidate_selection":
        _ingest_action_candidate_selection(summary, data)
    elif event_type == "skill_memory_hint":
        _ingest_skill_memory(summary, data)
    elif event_type in {
        "policy_hint",
        "policy_intervention",
        "failure_correction_selected",
        "failure_correction_action",
        "failure_correction_completed",
        "failure_correction_failed",
    }:
        _ingest_policy_skill(summary, event_type, data)
    elif event_type in {"memory_write", "memory_read", "memory_manage", "memory_consolidation"}:
        _ingest_memory_policy(summary, event_type, data)
    elif event_type == "goal_verification":
        _ingest_goal_verification(summary, data)


def _ingest_plan(summary: dict, data: dict):
    summary["plan_count"] += 1
    actions = data.get("actions", [])
    if not isinstance(actions, list):
        actions = []
    status = str(data.get("status") or "").lower()
    reason = str(data.get("reason") or data.get("failure_reason") or "").lower()
    if not actions:
        summary["empty_plan_count"] += 1
    if status in {"blocked", "failed", "error"} or "blocked" in reason or "empty plan" in reason:
        summary["blocked_plan_count"] += 1


def _ingest_action(summary: dict, data: dict):
    summary["action_count"] += 1
    result = data.get("result", {}) if isinstance(data.get("result", {}), dict) else {}
    success = _action_success(result)
    if success is True:
        summary["action_success_count"] += 1
    elif success is False:
        summary["action_failure_count"] += 1
    else:
        summary["action_unknown_count"] += 1
    _ingest_control_policy(summary, data, result)


def _ingest_plan_cache(summary: dict, event_type: str):
    module = summary["modules"]["plan_cache"]
    if event_type == "plan_cache_hit":
        module["hit_count"] += 1
    elif event_type == "plan_cache_miss":
        module["miss_count"] += 1
    elif event_type == "plan_cache_signature":
        module["signature_count"] += 1


def _ingest_visual_action(summary: dict, event_type: str, data: dict):
    module = summary["modules"]["visual_action_grounding"]
    if event_type == "visual_action_suggestion":
        module["suggestion_event_count"] += 1
        suggestions = data.get("suggestions", [])
        if not isinstance(suggestions, list):
            suggestions = [data.get("suggestion", {})]
        module["suggestion_count"] += len([item for item in suggestions if isinstance(item, dict)])
        for suggestion in suggestions:
            if isinstance(suggestion, dict):
                _increment(module["suggestion_kinds"], str(suggestion.get("kind") or "unknown"))
                _increment_action_type(module["action_types"], suggestion)
    else:
        module["intervention_count"] += 1
        phase = str(data.get("phase") or "unknown")
        _increment(module["intervention_phases"], phase)
        suggestion = data.get("suggestion", {}) if isinstance(data.get("suggestion", {}), dict) else {}
        _increment(module["intervention_kinds"], str(suggestion.get("kind") or "unknown"))
        _increment_action_type(module["action_types"], suggestion)


def _ingest_action_verification(summary: dict, data: dict):
    module = summary["modules"]["action_verification"]
    verification = data.get("verification", {}) if isinstance(data.get("verification", {}), dict) else data
    action = data.get("action", {}) if isinstance(data.get("action", {}), dict) else {}
    status = _verification_status(verification.get("status") or data.get("status"))
    module["event_count"] += 1
    _increment(module["status_counts"], status)
    action_type = str(verification.get("action_type") or action.get("type") or "unknown")
    _increment(module["action_types"], action_type)
    if status == "accept":
        module["accept_count"] += 1
    elif status == "reject":
        module["reject_count"] += 1
    elif status == "review":
        module["review_count"] += 1
    else:
        module["unknown_count"] += 1


def _ingest_action_candidate_selection(summary: dict, data: dict):
    module = summary["modules"]["action_candidate_selection"]
    selection = data.get("selection", {}) if isinstance(data.get("selection", {}), dict) else data
    selected = selection.get("selected_action", {}) if isinstance(selection.get("selected_action", {}), dict) else {}
    module["event_count"] += 1
    _increment(module["selected_types"], str(selected.get("type") or "unknown"))
    original = selection.get("original_verification", {}) if isinstance(selection.get("original_verification", {}), dict) else {}
    selected_verification = selection.get("selected_verification", {}) if isinstance(selection.get("selected_verification", {}), dict) else {}
    original_status = _verification_status(original.get("status"))
    selected_status = _verification_status(selected_verification.get("status"))
    if bool(selection.get("repaired_reject")) or (original_status == "reject" and selected_status != "reject"):
        module["repaired_reject_count"] += 1


def _ingest_skill_memory(summary: dict, data: dict):
    module = summary["modules"]["skill_memory"]
    module["hint_event_count"] += 1
    family = str(data.get("task_family") or "unknown")
    _increment(module["task_families"], family)
    hint_count = data.get("hint_count")
    if hint_count is None:
        hints = data.get("hints", [])
        hint_count = len(hints) if isinstance(hints, list) else 0
    module["hint_count"] += _safe_int(hint_count, 0)


def _ingest_policy_skill(summary: dict, event_type: str, data: dict):
    module = summary["modules"]["policy_skill"]
    if event_type == "policy_hint":
        module["hint_event_count"] += 1
        return
    phase = str(data.get("phase") or "").lower()
    if not phase:
        phase = {
            "failure_correction_selected": "selected",
            "failure_correction_action": "action",
            "failure_correction_completed": "completed",
            "failure_correction_failed": "failed",
        }.get(event_type, "")
    if phase == "selected":
        module["intervention_count"] += 1
    elif phase == "action":
        module["action_count"] += 1
    elif phase == "completed":
        module["success_count"] += 1
    elif phase == "failed":
        module["failure_count"] += 1
    skills = set(module.get("skills", []))
    if data.get("skill"):
        skills.add(str(data["skill"]))
    hints = data.get("hints", [])
    if isinstance(hints, list):
        for hint in hints:
            if isinstance(hint, str) and ":" in hint:
                skills.add(hint.split(":", 1)[0])
    module["skills"] = sorted(skills)


def _ingest_memory_policy(summary: dict, event_type: str, data: dict):
    module = summary["modules"]["memory_policy"]
    if event_type == "memory_write":
        module["write_count"] += 1
    elif event_type == "memory_read":
        module["read_count"] += 1
        filter_report = data.get("read_filter_report", {}) if isinstance(data.get("read_filter_report", {}), dict) else {}
        if filter_report:
            module["read_filter_event_count"] += 1
            module["read_filtered_entries"] += _safe_int(filter_report.get("filtered_entries"), 0)
            reasons = filter_report.get("filter_reasons", {})
            if isinstance(reasons, dict):
                for reason, count in reasons.items():
                    _increment(module["read_filter_reasons"], str(reason or "unknown"), _safe_int(count, 1))
    else:
        module["manage_count"] += 1
    decision = data.get("policy_decision", {}) if isinstance(data.get("policy_decision", {}), dict) else {}
    if decision.get("decision"):
        _increment(module["policy_decisions"], str(decision["decision"]))


def _ingest_goal_verification(summary: dict, data: dict):
    module = summary["modules"]["goal_verification"]
    context = data.get("context", {}) if isinstance(data.get("context", {}), dict) else {}
    module["event_count"] += 1
    if data.get("achieved") is True:
        module["achieved_count"] += 1
    if str(data.get("status") or "").lower() == "failed" or data.get("achieved") is False:
        module["failed_count"] += 1
    if str(data.get("status") or "").lower() == "unknown":
        module["unknown_count"] += 1
    if context.get("accepted") is True:
        module["accepted_count"] += 1
    elif context.get("accepted") is False:
        module["rejected_count"] += 1
    elif data.get("achieved") is True:
        module["accepted_count"] += 1
    elif data.get("achieved") is False:
        module["rejected_count"] += 1
    reason = context.get("acceptance_reason")
    if reason:
        _increment(module["acceptance_reasons"], str(reason))


def _ingest_control_policy(summary: dict, data: dict, result: dict):
    policy = result.get("control_policy", {}) if isinstance(result.get("control_policy", {}), dict) else {}
    if not policy:
        return
    module = summary["modules"]["control_policy"]
    action = data.get("action", {}) if isinstance(data.get("action", {}), dict) else {}
    module["event_count"] += 1
    action_type = str(policy.get("action_type") or result.get("action_type") or action.get("type") or "unknown")
    backend = str(policy.get("backend") or result.get("backend") or "unknown")
    preferred_control = str(policy.get("preferred_control") or "unknown")
    _increment(module["backend_counts"], backend)
    _increment(module["preferred_control_counts"], preferred_control)
    _increment(module["action_backend_counts"], f"{action_type}:{backend}")
    fallback = str(policy.get("fallback_reason") or "")
    if fallback:
        module["fallback_count"] += 1
        _increment(module["fallback_reasons"], fallback)


def _finalize_summary(summary: dict):
    summary["completion_rate"] = _ratio(summary["completed_goal_count"], summary["goal_end_count"])
    known_actions = summary["action_success_count"] + summary["action_failure_count"]
    summary["action_failure_rate"] = _ratio(summary["action_failure_count"], known_actions)
    summary["empty_plan_rate"] = _ratio(summary["empty_plan_count"], summary["plan_count"])

    plan_cache = summary["modules"]["plan_cache"]
    plan_cache["query_count"] = plan_cache["hit_count"] + plan_cache["miss_count"]
    plan_cache["hit_rate"] = _ratio(plan_cache["hit_count"], plan_cache["query_count"])
    plan_cache["activity_count"] = plan_cache["hit_count"] + plan_cache["miss_count"] + plan_cache["signature_count"]

    visual = summary["modules"]["visual_action_grounding"]
    visual["activity_count"] = (
        visual["suggestion_event_count"] + visual["suggestion_count"] + visual["intervention_count"]
    )

    verifier = summary["modules"]["action_verification"]
    verifier["reject_rate"] = _ratio(verifier["reject_count"], verifier["event_count"])
    verifier["activity_count"] = verifier["event_count"]

    candidate = summary["modules"]["action_candidate_selection"]
    candidate["repair_rate"] = _ratio(candidate["repaired_reject_count"], candidate["event_count"])
    candidate["activity_count"] = candidate["event_count"]

    skill_memory = summary["modules"]["skill_memory"]
    skill_memory["activity_count"] = skill_memory["hint_event_count"] + skill_memory["hint_count"]

    policy = summary["modules"]["policy_skill"]
    policy["success_rate"] = _ratio(policy["success_count"], policy["success_count"] + policy["failure_count"])
    policy["activity_count"] = (
        policy["hint_event_count"]
        + policy["intervention_count"]
        + policy["action_count"]
        + policy["success_count"]
        + policy["failure_count"]
    )

    memory = summary["modules"]["memory_policy"]
    memory["activity_count"] = memory["write_count"] + memory["read_count"] + memory["manage_count"]

    goal = summary["modules"]["goal_verification"]
    goal["accept_rate"] = _ratio(goal["accepted_count"], goal["accepted_count"] + goal["rejected_count"])
    goal["activity_count"] = goal["event_count"]

    control = summary["modules"]["control_policy"]
    control["activity_count"] = control["event_count"]

    active_modules = [
        name for name in MODULE_ORDER
        if summary["modules"].get(name, {}).get("activity_count", 0) > 0
    ]
    summary["active_modules"] = active_modules
    summary["module_activity_count"] = sum(
        int(summary["modules"].get(name, {}).get("activity_count", 0) or 0)
        for name in MODULE_ORDER
    )


def _summary_deltas(baseline: dict, candidate: dict) -> dict:
    keys = [
        "readable_log_count",
        "event_count",
        "goal_end_count",
        "completed_goal_count",
        "failed_goal_count",
        "completion_rate",
        "action_count",
        "action_success_count",
        "action_failure_count",
        "action_failure_rate",
        "plan_count",
        "blocked_plan_count",
        "empty_plan_count",
        "empty_plan_rate",
        "module_activity_count",
    ]
    return {f"{key}_delta": _numeric_delta(candidate.get(key), baseline.get(key)) for key in keys}


def _module_deltas(baseline: dict, candidate: dict) -> dict:
    result = {}
    baseline_modules = baseline.get("modules", {}) if isinstance(baseline.get("modules", {}), dict) else {}
    candidate_modules = candidate.get("modules", {}) if isinstance(candidate.get("modules", {}), dict) else {}
    for module_name in MODULE_ORDER:
        base_module = baseline_modules.get(module_name, {})
        cand_module = candidate_modules.get(module_name, {})
        metrics = {}
        for key, value in cand_module.items():
            if isinstance(value, (int, float)) and isinstance(base_module.get(key, 0), (int, float)):
                metrics[f"{key}_delta"] = _numeric_delta(value, base_module.get(key, 0))
        result[module_name] = metrics
    return result


def _module_activity(baseline: dict, candidate: dict, module_deltas: dict) -> dict:
    modules = []
    for module_name in MODULE_ORDER:
        baseline_activity = _module_activity_count(baseline, module_name)
        candidate_activity = _module_activity_count(candidate, module_name)
        modules.append({
            "module": module_name,
            "baseline_activity_count": baseline_activity,
            "candidate_activity_count": candidate_activity,
            "activity_delta": module_deltas.get(module_name, {}).get("activity_count_delta", 0),
            "candidate_active": candidate_activity > 0,
            "new_or_increased": candidate_activity > baseline_activity,
        })
    active = [item for item in modules if item["candidate_active"]]
    increased = [item for item in modules if item["new_or_increased"]]
    return {
        "modules": modules,
        "candidate_active_module_count": len(active),
        "new_or_increased_module_count": len(increased),
        "candidate_active_modules": [item["module"] for item in active],
        "new_or_increased_modules": [item["module"] for item in increased],
    }


def _comparison_checks(
    baseline: dict,
    candidate: dict,
    deltas: dict,
    module_activity: dict,
    thresholds: dict,
) -> list[dict]:
    checks = []
    _add_check(
        checks,
        "baseline_logs_readable",
        baseline.get("readable_log_count", 0) > 0,
        f"{baseline.get('readable_log_count', 0)} baseline logs readable",
        severity="warn",
    )
    _add_check(
        checks,
        "candidate_logs_readable",
        candidate.get("readable_log_count", 0) > 0,
        f"{candidate.get('readable_log_count', 0)} candidate logs readable",
        severity="fail",
    )
    _add_check(
        checks,
        "candidate_module_activity",
        module_activity.get("candidate_active_module_count", 0) > 0,
        f"{module_activity.get('candidate_active_module_count', 0)} candidate modules active",
        severity="warn",
    )
    _add_check(
        checks,
        "module_activity_increased",
        module_activity.get("new_or_increased_module_count", 0) > 0,
        f"{module_activity.get('new_or_increased_module_count', 0)} modules increased versus baseline",
        severity="warn",
    )
    completion_delta = float(deltas.get("completion_rate_delta", 0.0) or 0.0)
    _add_check(
        checks,
        "completion_rate_not_regressed",
        completion_delta >= -float(thresholds["max_completion_regression"]),
        f"completion_rate_delta={completion_delta}",
        severity="fail",
    )
    action_failure_delta = float(deltas.get("action_failure_rate_delta", 0.0) or 0.0)
    _add_check(
        checks,
        "action_failure_rate_not_regressed",
        action_failure_delta <= float(thresholds["max_action_failure_regression"]),
        f"action_failure_rate_delta={action_failure_delta}",
        severity="fail",
    )
    verifier_delta = _numeric_delta(
        candidate.get("modules", {}).get("action_verification", {}).get("reject_rate", 0.0),
        baseline.get("modules", {}).get("action_verification", {}).get("reject_rate", 0.0),
    )
    _add_check(
        checks,
        "verifier_reject_rate_not_regressed",
        verifier_delta <= float(thresholds["max_verifier_reject_regression"]),
        f"verifier_reject_rate_delta={verifier_delta}",
        severity="fail",
    )
    empty_plan_delta = float(deltas.get("empty_plan_rate_delta", 0.0) or 0.0)
    _add_check(
        checks,
        "empty_plan_rate_not_regressed",
        empty_plan_delta <= float(thresholds["max_empty_plan_regression"]),
        f"empty_plan_rate_delta={empty_plan_delta}",
        severity="fail",
    )
    if baseline.get("errors"):
        checks.append({
            "name": "baseline_log_errors",
            "status": "warn",
            "detail": "; ".join(str(error) for error in baseline.get("errors", [])[:4]),
        })
    if candidate.get("errors"):
        checks.append({
            "name": "candidate_log_errors",
            "status": "fail",
            "detail": "; ".join(str(error) for error in candidate.get("errors", [])[:4]),
        })
    return checks


def _comparison_decision(checks: list[dict]) -> tuple[str, str, str]:
    failures = [check for check in checks if check.get("status") == "fail"]
    warnings = [check for check in checks if check.get("status") == "warn"]
    if failures:
        return (
            "rejected",
            "reject_candidate_module_profile",
            failures[0].get("detail") or failures[0].get("name") or "candidate module comparison failed",
        )
    if warnings:
        return (
            "review",
            "hold_candidate_module_profile",
            warnings[0].get("detail") or warnings[0].get("name") or "candidate module evidence needs review",
        )
    return (
        "approved",
        "allow_candidate_module_profile_review",
        "candidate modules show activity without configured regressions",
    )


def _comparison_recommendations(candidate: dict, deltas: dict, module_activity: dict, readiness: str) -> list[str]:
    recommendations = []
    active = set(module_activity.get("candidate_active_modules", []))
    if not active:
        recommendations.append("run_candidate_with_module_runtime_switches_or_profile_enabled")
    if "plan_cache" in active:
        recommendations.append("run_plan_cache_runtime_report_and_plan_cache_gate_before_runtime_reuse")
    if "visual_action_grounding" in active:
        recommendations.append("run_visual_action_ablation_or_visual_review_pipeline_before_visual_policy_promotion")
    if "action_verification" in active or "action_candidate_selection" in active:
        recommendations.append("compare_action_verification_and_action_candidate_reports_on_the_same_logs")
    if "skill_memory" in active:
        recommendations.append("run_skill_memory_quality_report_and_gate_before_promoting_reuse_hints")
    if "memory_policy" in active:
        recommendations.append("run_memory_policy_and_promptware_reports_before_strict_memory_enforcement")
    if "control_policy" in active:
        recommendations.append("compare_mixed_policy_ablation_or_action_abstraction_report_before_backend_switching")
    if float(deltas.get("completion_rate_delta", 0.0) or 0.0) > 0:
        recommendations.append("preserve_candidate_logs_as_positive_module_evidence")
    if float(deltas.get("action_failure_rate_delta", 0.0) or 0.0) < 0:
        recommendations.append("mine_failure_reduction_cases_for_task_stream_or_knowledge_correction_gates")
    if readiness == "approved":
        recommendations.append("package_candidate_artifacts_in_runtime_profile_after_dedicated_gates_pass")
    return _dedupe(recommendations)


def _add_check(checks: list[dict], name: str, passed: bool, detail: str, severity: str):
    if passed:
        status = "pass"
    else:
        status = severity
    checks.append({"name": name, "status": status, "detail": detail})


def _goal_completed(event_type: str, data: dict) -> bool | None:
    if event_type == "auto_goal_complete":
        return True
    if event_type == "auto_goal_failed":
        return False
    result = data.get("result", {}) if isinstance(data.get("result", {}), dict) else {}
    if "completed" in result:
        return bool(result.get("completed"))
    if "completed" in data:
        return bool(data.get("completed"))
    status = str(data.get("status") or result.get("status") or "").lower()
    if status in {"completed", "complete", "success", "pass", "passed"}:
        return True
    if status in {"failed", "failure", "fail", "timeout", "blocked"}:
        return False
    return None


def _action_success(result: dict) -> bool | None:
    if "success" in result:
        return bool(result.get("success"))
    status = str(result.get("status") or "").lower()
    if status in {"success", "succeeded", "pass", "passed", "ok"}:
        return True
    if status in {"failed", "failure", "fail", "error", "blocked", "timeout"}:
        return False
    if result.get("error"):
        return False
    return None


def _verification_status(status: Any) -> str:
    text = str(status or "").strip().lower()
    if text in {"accept", "accepted", "pass", "passed", "approved", "ok"}:
        return "accept"
    if text in {"reject", "rejected", "fail", "failed", "blocked", "deny", "denied"}:
        return "reject"
    if text in {"review", "warn", "warning", "unknown", "uncertain"}:
        return "review" if text != "unknown" else "unknown"
    return text or "unknown"


def _increment_action_type(counts: dict, suggestion: dict):
    action = suggestion.get("action", {}) if isinstance(suggestion.get("action", {}), dict) else {}
    action_type = str(action.get("type") or "")
    if action_type:
        _increment(counts, action_type)


def _module_activity_count(summary: dict, module_name: str) -> int:
    modules = summary.get("modules", {}) if isinstance(summary.get("modules", {}), dict) else {}
    module = modules.get(module_name, {}) if isinstance(modules.get(module_name, {}), dict) else {}
    return _safe_int(module.get("activity_count"), 0)


def _numeric_delta(candidate_value: Any, baseline_value: Any) -> float:
    try:
        return round(float(candidate_value or 0) - float(baseline_value or 0), 3)
    except (TypeError, ValueError):
        return 0.0


def _ratio(numerator: int | float, denominator: int | float) -> float:
    try:
        denominator = float(denominator)
        if denominator <= 0:
            return 0.0
        return round(float(numerator) / denominator, 3)
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _increment(counts: dict, key: str, amount: int = 1):
    counts[key] = counts.get(key, 0) + amount


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
