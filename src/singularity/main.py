"""Singularity - Minecraft LLM Agent entry point."""
import sys
import json
import logging
import argparse
import os

from singularity.core.config import Config, BotConfig, LLMConfig
from singularity.core.runtime_profile import (
    DEFAULT_SECURITY_SCAN_BYTES,
    build_runtime_profile_payload,
    build_runtime_profile_report,
    build_runtime_profile_report_from_profiles,
    build_runtime_profile_security_audit,
    build_runtime_profile_security_audit_from_profiles,
    build_runtime_profile_suite_report,
    load_runtime_profiles,
    merge_arg_profile_list,
    profile_bool_arg,
    profile_str_arg,
)


def _llm_config_from_args(args) -> LLMConfig:
    return LLMConfig(
        provider=getattr(args, "llm_provider", "openai") or "openai",
        model=getattr(args, "llm_model", "gpt-4o-mini") or "gpt-4o-mini",
        api_key=(
            getattr(args, "api_key", "")
            or os.environ.get("SINGULARITY_LLM_API_KEY", "")
            or os.environ.get("OPENAI_API_KEY", "")
        ),
        base_url=getattr(args, "llm_base_url", "") or os.environ.get("SINGULARITY_LLM_BASE_URL", ""),
    )


def _promotion_critic_from_args(args):
    if not getattr(args, "promotion_critic", False):
        return None
    from singularity.core.skill_extractor import SkillPromotionCritic
    from singularity.llm.provider import LLMProvider

    return SkillPromotionCritic(LLMProvider(_llm_config_from_args(args)))


def _goal_critic_from_args(args):
    if not getattr(args, "goal_critic", False):
        return None
    from singularity.core.goal_verifier import GoalVerificationCritic
    from singularity.llm.provider import LLMProvider

    return GoalVerificationCritic(LLMProvider(_llm_config_from_args(args)))


def _add_goal_critic_runtime_gate_args(parser):
    parser.add_argument(
        "--goal-critic-gate",
        action="append",
        default=[],
        help="Approved goal-verification-critic-gate JSON required before --goal-critic affects runtime completion decisions",
    )


def _add_runtime_profile_args(parser):
    parser.add_argument(
        "--runtime-profile",
        action="append",
        default=[],
        help="Reusable runtime profile JSON that bundles approved gates, feedback artifacts, and safe switches",
    )


def _add_memory_promptware_runtime_args(parser):
    parser.add_argument("--enforce-memory-write-gate", action="store_true", help="Suppress unsafe memory writes only when approved memory-promptware gates are supplied")
    parser.add_argument("--memory-promptware-gate", action="append", default=[], help="Approved memory-promptware-gate JSON required before strict memory write enforcement")


def _add_memory_attribution_runtime_args(parser):
    parser.add_argument("--enable-weighted-memory-retrieval", action="store_true", help="Enable MemTier-style weighted retrieval only when approved memory-attribution gates are supplied")
    parser.add_argument("--memory-attribution-gate", action="append", default=[], help="Approved memory-attribution-gate JSON required before weighted memory retrieval")


def _add_plan_cache_runtime_args(parser):
    parser.add_argument("--enable-plan-cache", action="store_true", help="Reuse approved AgenticCache-style plan-transition cache entries before LLM planning")
    parser.add_argument("--plan-cache", action="append", default=[], help="Approved plan-transition-cache-report JSON for runtime plan reuse")
    parser.add_argument("--plan-cache-gate", action="append", default=[], help="Approved plan-cache-gate JSON required before runtime plan-cache loading")
    parser.add_argument("--plan-cache-min-confidence", type=float, default=0.75, help="Minimum confidence for runtime plan-cache entries")


def _print_runtime_profile_report(report: dict):
    print("\nRuntime Profile Validation")
    print(f"  readiness: {report.get('readiness', 'unknown')}")
    print(f"  decision: {report.get('decision', 'unknown')}")
    print(f"  reason: {report.get('reason', '')}")
    print(
        "  inputs: "
        f"profiles={report.get('profile_count', 0)}, "
        f"gates={report.get('approved_gate_count', 0)}/{report.get('gate_count', 0)} approved, "
        f"artifacts={report.get('artifact_count', 0)}"
    )
    settings = report.get("settings", {}) if isinstance(report.get("settings", {}), dict) else {}
    if settings:
        parts = [f"{key}={value}" for key, value in sorted(settings.items())]
        print(f"  settings: {', '.join(parts)}")
    if report.get("missing"):
        print(f"  missing: {', '.join(report.get('missing', []))}")
    for gate in report.get("gate_reports", [])[:12]:
        marker = "+" if gate.get("readiness") == "approved" else "x" if gate.get("readiness") == "rejected" else "!"
        print(
            f"  [{marker}] {gate.get('field')} {gate.get('path')}: "
            f"{gate.get('readiness')} {gate.get('decision', '')}"
        )
        if gate.get("reason"):
            print(f"      {gate.get('reason')}")
    for error in report.get("errors", []):
        print(f"  error: {error}")


def _print_runtime_profile_security_audit(report: dict):
    print("\nRuntime Profile Security Audit")
    print(f"  readiness: {report.get('readiness', 'unknown')}")
    print(f"  decision: {report.get('decision', 'unknown')}")
    print(f"  reason: {report.get('reason', '')}")
    print(
        "  inputs: "
        f"profiles={report.get('profile_count', 0)}, "
        f"paths_scanned={report.get('scanned_path_count', 0)}, "
        f"records_scanned={report.get('scanned_record_count', 0)}, "
        f"findings={report.get('finding_count', 0)} "
        f"(included={report.get('included_finding_count', report.get('finding_count', 0))})"
    )
    if report.get("include_gates"):
        print("  scope: artifacts and gates")
    else:
        print("  scope: artifacts")
    for finding in report.get("findings", [])[:12]:
        print(
            f"  [!] {finding.get('field')} {finding.get('path')} "
            f"{finding.get('record_path')}: {','.join(finding.get('flags', []))}"
        )
        print(f"      sha256={finding.get('content_sha256', '')}")
    if report.get("truncated_finding_count"):
        print(f"  truncated findings: {report.get('truncated_finding_count')}")
    if report.get("missing"):
        print(f"  missing: {', '.join(report.get('missing', []))}")
    for error in report.get("errors", []):
        print(f"  error: {error}")


def _print_runtime_profile_suite_report(report: dict):
    print("\nRuntime Profile Suite")
    print(f"  readiness: {report.get('readiness', 'unknown')}")
    print(f"  decision: {report.get('decision', 'unknown')}")
    print(f"  reason: {report.get('reason', '')}")
    print(
        "  inputs: "
        f"profiles={report.get('approved_profile_count', 0)}/{report.get('profile_count', 0)} approved, "
        f"review={report.get('review_profile_count', 0)}, "
        f"rejected={report.get('rejected_profile_count', 0)}, "
        f"errors={report.get('error_profile_count', 0)}"
    )
    if report.get("runtime_dir"):
        print(f"  runtime_dir: {report.get('runtime_dir')}")
    if report.get("required_profiles"):
        print(f"  required: {', '.join(report.get('required_profiles', []))}")
    if report.get("missing_required_profiles"):
        print(f"  missing required: {', '.join(report.get('missing_required_profiles', []))}")
    for item in report.get("profiles", [])[:20]:
        marker = "+" if item.get("readiness") == "approved" else "x" if item.get("readiness") in {"rejected", "error"} else "!"
        name = f" ({item.get('name')})" if item.get("name") else ""
        print(
            f"  [{marker}] {item.get('path')}{name}: "
            f"validation={item.get('validation_readiness')} "
            f"security={item.get('security_readiness')} "
            f"gates={item.get('approved_gate_count', 0)}/{item.get('gate_count', 0)} "
            f"artifacts={item.get('artifact_count', 0)} "
            f"findings={item.get('finding_count', 0)}"
        )
        if item.get("missing"):
            print(f"      missing: {', '.join(item.get('missing', []))}")
        for error in item.get("errors", [])[:4]:
            print(f"      error: {error}")
    for error in report.get("errors", [])[:20]:
        print(f"  error: {error}")


def _print_agent_module_comparison_report(report: dict):
    baseline = report.get("baseline", {}) if isinstance(report.get("baseline", {}), dict) else {}
    candidate = report.get("candidate", {}) if isinstance(report.get("candidate", {}), dict) else {}
    deltas = report.get("deltas", {}) if isinstance(report.get("deltas", {}), dict) else {}
    activity = report.get("module_activity", {}) if isinstance(report.get("module_activity", {}), dict) else {}
    print("\nAgent Module Comparison")
    print(f"  readiness: {report.get('readiness', 'unknown')}")
    print(f"  decision: {report.get('decision', 'unknown')}")
    print(f"  reason: {report.get('reason', '')}")
    print(
        "  logs: "
        f"baseline={baseline.get('readable_log_count', 0)}/{baseline.get('requested_log_count', 0)}, "
        f"candidate={candidate.get('readable_log_count', 0)}/{candidate.get('requested_log_count', 0)}"
    )
    print(
        "  completion: "
        f"baseline={baseline.get('completion_rate', 0)} "
        f"candidate={candidate.get('completion_rate', 0)} "
        f"delta={deltas.get('completion_rate_delta', 0)}"
    )
    print(
        "  actions: "
        f"baseline_fail_rate={baseline.get('action_failure_rate', 0)} "
        f"candidate_fail_rate={candidate.get('action_failure_rate', 0)} "
        f"delta={deltas.get('action_failure_rate_delta', 0)}"
    )
    print(
        "  modules: "
        f"active={activity.get('candidate_active_module_count', 0)}, "
        f"increased={activity.get('new_or_increased_module_count', 0)}"
    )
    if activity.get("candidate_active_modules"):
        print(f"  active modules: {', '.join(activity.get('candidate_active_modules', []))}")
    for item in activity.get("modules", [])[:12]:
        if item.get("candidate_activity_count", 0) <= 0 and item.get("baseline_activity_count", 0) <= 0:
            continue
        marker = "+" if item.get("new_or_increased") else "~"
        print(
            f"  [{marker}] {item.get('module')}: "
            f"baseline={item.get('baseline_activity_count', 0)} "
            f"candidate={item.get('candidate_activity_count', 0)} "
            f"delta={item.get('activity_delta', 0)}"
        )
    for check in report.get("checks", [])[:12]:
        marker = "+" if check.get("status") == "pass" else "x" if check.get("status") == "fail" else "!"
        print(f"  [{marker}] {check.get('name')}: {check.get('detail')}")
    for recommendation in report.get("recommendations", [])[:8]:
        print(f"  next: {recommendation}")


def _print_causal_evidence_report(report: dict):
    print("\nCausal Evidence Audit")
    print(f"  readiness: {report.get('readiness', 'unknown')}")
    print(f"  decision: {report.get('decision', 'unknown')}")
    print(f"  reason: {report.get('reason', '')}")
    print(
        "  logs: "
        f"readable={report.get('readable_log_count', 0)}/{report.get('session_log_count', 0)}, "
        f"ready={report.get('ready_log_count', 0)}"
    )
    print(
        "  protocol: "
        f"hypotheses={report.get('hypothesis_count', 0)}, "
        f"experiments={report.get('experiment_count', 0)}, "
        f"interventions={report.get('intervention_count', 0)}, "
        f"outcomes={report.get('outcome_measure_count', 0)}, "
        f"controls={report.get('contrast_control_count', 0)}"
    )
    print(
        "  claims: "
        f"causal={report.get('causal_claim_count', 0)}, "
        f"causal_memory={report.get('causal_memory_write_count', 0)}, "
        f"counterexamples={report.get('counterexample_count', 0)}, "
        f"unresolved={report.get('unresolved_counterexample_count', 0)}"
    )
    print(f"  score: {report.get('average_causal_evidence_score', 0)}")
    if report.get("bias_risk_counts"):
        parts = [f"{key}={value}" for key, value in sorted(report.get("bias_risk_counts", {}).items())]
        print(f"  bias risks: {', '.join(parts)}")
    for check in report.get("checks", [])[:12]:
        marker = "+" if check.get("status") == "pass" else "x" if check.get("status") == "fail" else "!"
        print(f"  [{marker}] {check.get('name')}: {check.get('detail')}")
    for hint in report.get("policy_hints", [])[:8]:
        print(f"  hint: {hint}")
    for case in report.get("cases", [])[:6]:
        marker = "+" if case.get("ready_for_causal_evidence_review") and not case.get("issues") else "!"
        print(
            f"  [{marker}] {case.get('source_log')}: "
            f"score={case.get('causal_evidence_score', 0)}, "
            f"claims={case.get('causal_claim_count', 0)}, "
            f"controls={case.get('contrast_control_count', 0)}, "
            f"unresolved={case.get('unresolved_counterexample_count', 0)}"
        )
        if case.get("issues"):
            print(f"      issues: {', '.join(case.get('issues', [])[:8])}")
    for error in report.get("errors", []):
        print(f"  error: {error}")


def _print_causal_evidence_gate(report: dict):
    print("\nCausal Evidence Gate")
    print(f"  target: {report.get('target', '')}")
    print(f"  readiness: {report.get('readiness', 'unknown')}")
    print(f"  decision: {report.get('decision', 'unknown')}")
    print(f"  reason: {report.get('reason', '')}")
    print(
        "  reports: "
        f"total={report.get('report_count', 0)}, "
        f"approved={report.get('approved_report_count', 0)}, "
        f"review={report.get('review_report_count', 0)}, "
        f"rejected={report.get('rejected_report_count', 0)}, "
        f"errors={report.get('error_report_count', 0)}"
    )
    print(
        "  evidence: "
        f"claims={report.get('causal_claim_count', 0)}, "
        f"causal_memory={report.get('causal_memory_write_count', 0)}, "
        f"controls={report.get('contrast_control_count', 0)}, "
        f"unresolved={report.get('unresolved_counterexample_count', 0)}, "
        f"unmitigated_bias={report.get('unmitigated_bias_risk_count', 0)}"
    )
    print(f"  score: {report.get('average_causal_evidence_score', 0)}")
    for check in report.get("checks", [])[:12]:
        marker = "+" if check.get("status") == "pass" else "x" if check.get("status") == "fail" else "!"
        print(f"  [{marker}] {check.get('name')}: {check.get('detail')}")
    for hint in report.get("policy_hints", [])[:8]:
        print(f"  hint: {hint}")
    for missing in report.get("missing", [])[:8]:
        print(f"  missing: {missing}")
    for error in report.get("errors", [])[:8]:
        print(f"  error: {error}")


def _runtime_profile_payload_from_args(args) -> dict:
    settings = {}
    if getattr(args, "enable_goal_critic", False):
        settings["enable_goal_critic"] = True
    if getattr(args, "coach_style", ""):
        settings["coach_style"] = getattr(args, "coach_style", "")
    if getattr(args, "capture_screenshots", False):
        settings["enable_screenshot_capture"] = True
    if getattr(args, "enforce_memory_write_gate", False):
        settings["enforce_memory_write_gate"] = True
    if getattr(args, "enable_weighted_memory_retrieval", False):
        settings["enable_weighted_memory_retrieval"] = True
    if getattr(args, "enable_plan_cache", False):
        settings["enable_plan_cache"] = True
    if getattr(args, "screenshot_dir", ""):
        settings["screenshot_dir"] = getattr(args, "screenshot_dir", "")
    path_fields = {
        "goal_critic_gate_paths": getattr(args, "goal_critic_gate", []) or [],
        "mixed_policy_patch_paths": getattr(args, "mixed_policy_patch", []) or [],
        "mixed_policy_gate_paths": getattr(args, "mixed_policy_gate", []) or [],
        "self_evolution_feedback_paths": getattr(args, "self_evolution_feedback", []) or [],
        "world_model_feedback_paths": getattr(args, "world_model_feedback", []) or [],
        "world_model_gate_paths": getattr(args, "world_model_gate", []) or [],
        "knowledge_correction_feedback_paths": getattr(args, "knowledge_correction_feedback", []) or [],
        "knowledge_correction_gate_paths": getattr(args, "knowledge_correction_gate", []) or [],
        "task_precondition_feedback_paths": getattr(args, "task_precondition_feedback", []) or [],
        "task_precondition_gate_paths": getattr(args, "task_precondition_gate", []) or [],
        "plan_cache_paths": getattr(args, "plan_cache", []) or [],
        "plan_cache_gate_paths": getattr(args, "plan_cache_gate", []) or [],
        "action_value_feedback_paths": getattr(args, "action_value_feedback", []) or [],
        "action_value_transition_gate_paths": getattr(args, "action_value_transition_gate", []) or [],
        "action_value_transition_evaluator_report_paths": getattr(args, "action_value_transition_evaluator_report", []) or [],
        "skill_memory_quality_feedback_paths": getattr(args, "skill_memory_quality_feedback", []) or [],
        "skill_memory_quality_gate_paths": getattr(args, "skill_memory_quality_gate", []) or [],
        "skill_runtime_default_gate_paths": getattr(args, "skill_runtime_default_gate", []) or [],
        "memory_promptware_gate_paths": getattr(args, "memory_promptware_gate", []) or [],
        "memory_attribution_gate_paths": getattr(args, "memory_attribution_gate", []) or [],
        "coach_style_ablation_paths": getattr(args, "coach_style_ablation", []) or [],
        "coach_style_gate_paths": getattr(args, "coach_style_gate", []) or [],
    }
    return build_runtime_profile_payload(
        name=getattr(args, "name", "") or "",
        description=getattr(args, "description", "") or "",
        settings=settings,
        path_fields=path_fields,
    )


def _add_coaching_args(parser):
    parser.add_argument(
        "--coach-style",
        type=str,
        default="",
        help="Advisory runtime coaching style for planner/curriculum bias: safe, explorer, efficient, resourceful, builder",
    )
    parser.add_argument(
        "--no-coaching-policy",
        action="store_true",
        help="Disable advisory runtime coaching even when --coach-style is supplied",
    )


def _add_skill_runtime_default_args(parser):
    parser.add_argument(
        "--skill-runtime-default-gate",
        action="append",
        default=[],
        help="Approved skill-runtime-default-gate JSON required before learned skills act as task-family defaults",
    )


def _add_task_continuity_args(parser):
    parser.add_argument(
        "--no-task-continuity-context",
        action="store_true",
        help="Disable durable task-continuity checkpoints and planner context",
    )


def _add_bounded_planning_context_args(parser):
    parser.add_argument(
        "--no-bounded-planning-context",
        action="store_true",
        help="Disable per-decision typed memory character budgets",
    )
    parser.add_argument(
        "--planning-memory-read-limit",
        type=int,
        default=600,
        help="Maximum characters returned by one planner memory read",
    )
    parser.add_argument(
        "--planning-memory-cycle-limit",
        type=int,
        default=2400,
        help="Maximum memory characters assembled for one planner decision",
    )


def _add_knowledge_correction_args(parser):
    parser.add_argument(
        "--knowledge-correction-feedback",
        action="append",
        default=[],
        help="knowledge-correction-report JSON to load as gated advisory planner feedback",
    )
    parser.add_argument(
        "--knowledge-correction-gate",
        action="append",
        default=[],
        help="Approved knowledge-correction-gate JSON required before loading correction feedback",
    )
    parser.add_argument(
        "--no-knowledge-correction-context",
        action="store_true",
        help="Disable gated knowledge-correction hints in planner context",
    )


def _add_task_precondition_args(parser):
    parser.add_argument(
        "--task-precondition-feedback",
        action="append",
        default=[],
        help="task-precondition-report JSON to load as gated advisory hidden-prerequisite planner feedback",
    )
    parser.add_argument(
        "--task-precondition-gate",
        action="append",
        default=[],
        help="Approved task-precondition-gate JSON required before loading task-precondition feedback",
    )
    parser.add_argument(
        "--no-task-precondition-context",
        action="store_true",
        help="Disable gated task-precondition hints in planner context",
    )


def _merge_skill_memory_quality_feedback_paths(paths: list[str]) -> dict:
    feedback = {
        "quality_label_counts": {},
        "hint_type_counts": {},
        "task_family_counts": {},
        "hint_quality_items": [],
        "policy_hints": [],
    }
    for path in paths or []:
        with open(path, "r", encoding="utf-8-sig") as f:
            payload = json.load(f)
        current = payload.get("skill_memory_quality_feedback", payload) if isinstance(payload, dict) else {}
        if not isinstance(current, dict):
            continue
        for key in ("quality_label_counts", "hint_type_counts", "task_family_counts"):
            for name, count in (current.get(key, {}) or {}).items():
                try:
                    amount = int(float(count or 0))
                except (TypeError, ValueError):
                    amount = 0
                feedback[key][str(name)] = feedback[key].get(str(name), 0) + amount
        for key in ("hint_quality_items", "policy_hints"):
            values = current.get(key, [])
            if isinstance(values, list):
                feedback[key].extend(item for item in values if isinstance(item, dict))
    return feedback


def _load_skill_memory_quality_ablation_cases(args) -> list[dict]:
    case_file = getattr(args, "case_file", "") or ""
    if case_file:
        with open(case_file, "r", encoding="utf-8-sig") as f:
            if case_file.lower().endswith(".jsonl"):
                return [json.loads(line) for line in f if line.strip()]
            payload = json.load(f)
        if isinstance(payload, dict) and isinstance(payload.get("cases"), list):
            return payload["cases"]
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            return [payload]
    goals = getattr(args, "goal", []) or []
    task_family = getattr(args, "task_family", "") or ""
    return [
        {"id": f"goal_{index}", "goal": goal, "task_family": task_family}
        for index, goal in enumerate(goals, start=1)
    ]


def _load_knowledge_correction_ablation_cases(args) -> list[dict] | None:
    case_file = getattr(args, "case_file", "") or ""
    if case_file:
        with open(case_file, "r", encoding="utf-8-sig") as f:
            if case_file.lower().endswith(".jsonl"):
                return [json.loads(line) for line in f if line.strip()]
            payload = json.load(f)
        if isinstance(payload, dict) and isinstance(payload.get("cases"), list):
            return payload["cases"]
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            return [payload]
    goals = getattr(args, "goal", []) or []
    if goals:
        current_state = {}
        state_json = getattr(args, "current_state_json", "") or ""
        state_file = getattr(args, "current_state_file", "") or ""
        if state_file:
            with open(state_file, "r", encoding="utf-8-sig") as f:
                current_state = json.load(f)
        elif state_json:
            current_state = json.loads(state_json)
        if not isinstance(current_state, dict):
            current_state = {}
        return [
            {"id": f"goal_{index}", "goal": goal, "current_state": current_state}
            for index, goal in enumerate(goals, start=1)
        ]
    return None


def main():
    parser = argparse.ArgumentParser(description="Singularity Minecraft LLM Agent")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Run goal command
    run_parser = subparsers.add_parser("run", help="Run a single goal")
    run_parser.add_argument("--goal", type=str, default="Gather 3 oak logs", help="Goal in natural language")
    _add_runtime_profile_args(run_parser)
    run_parser.add_argument("--host", type=str, default="localhost")
    run_parser.add_argument("--port", type=int, default=25565)
    run_parser.add_argument("--username", type=str, default="Singularity")
    run_parser.add_argument("--bridge-host", type=str, default="127.0.0.1")
    run_parser.add_argument("--bridge-port", type=int, default=3000)
    run_parser.add_argument("--llm-provider", type=str, default="openai")
    run_parser.add_argument("--llm-model", type=str, default="gpt-4o-mini")
    run_parser.add_argument("--llm-base-url", type=str, default="")
    run_parser.add_argument("--api-key", type=str, default="")
    run_parser.add_argument("--goal-critic", action="store_true", help="Use configured LLM as fallback critic for unknown goal verification")
    _add_goal_critic_runtime_gate_args(run_parser)
    _add_task_continuity_args(run_parser)
    _add_bounded_planning_context_args(run_parser)
    run_parser.add_argument("--no-skill-memory-context", action="store_true", help="Disable skill-level memory hints in planner context")
    run_parser.add_argument("--no-vision-analysis", action="store_true", help="Disable structured vision grounding on observations")
    run_parser.add_argument("--no-visual-action-grounding", action="store_true", help="Disable visual suggestions from modifying planned actions")
    run_parser.add_argument("--capture-screenshots", action="store_true", help="Ask the bridge renderer to capture screenshots for visual analysis")
    run_parser.add_argument("--screenshot-dir", type=str, default="logs/screenshots", help="Directory for captured screenshot files")
    run_parser.add_argument("--screenshot-min-interval", type=float, default=2.0, help="Minimum seconds between screenshot capture attempts")
    run_parser.add_argument("--mixed-policy-patch", action="append", default=[], help="Approved mixed-initiative policy patch JSON to load at runtime")
    run_parser.add_argument("--mixed-policy-gate", action="append", default=[], help="Approved mixed-policy gate JSON required before loading runtime policy patches")
    run_parser.add_argument("--self-evolution-feedback", action="append", default=[], help="self-evolution-report JSON to load as advisory planner feedback")
    run_parser.add_argument("--world-model-feedback", action="append", default=[], help="world-model-report JSON to load into autonomous curriculum after approved gate")
    run_parser.add_argument("--world-model-gate", action="append", default=[], help="Approved world-model-feedback-gate JSON required before loading world-model feedback")
    _add_memory_promptware_runtime_args(run_parser)
    _add_memory_attribution_runtime_args(run_parser)
    _add_plan_cache_runtime_args(run_parser)
    _add_knowledge_correction_args(run_parser)
    _add_task_precondition_args(run_parser)
    run_parser.add_argument("--action-value-feedback", action="append", default=[], help="action-value-report JSON to load for advisory action candidate scoring")
    run_parser.add_argument("--action-value-transition-gate", action="append", default=[], help="Approved action-value-transition-gate JSON required before loading ASV transition scores")
    run_parser.add_argument("--action-value-transition-evaluator-report", action="append", default=[], help="Approved action-value-transition-evaluator-report JSON required before loading ASV transition scores")
    run_parser.add_argument("--skill-memory-quality-feedback", action="append", default=[], help="skill-memory-quality-report JSON to load for advisory skill-memory retrieval ranking")
    run_parser.add_argument("--skill-memory-quality-gate", action="append", default=[], help="Approved skill-memory-quality-gate JSON required before loading quality feedback")
    _add_skill_runtime_default_args(run_parser)
    _add_coaching_args(run_parser)
    run_parser.add_argument("--log-level", type=str, default="INFO")

    # Autonomous mode (M4 + M5)
    auto_parser = subparsers.add_parser("autonomous", help="Run autonomous survival (M4 + M5)")
    _add_runtime_profile_args(auto_parser)
    auto_parser.add_argument("--max-goals", type=int, default=10, help="Maximum goals to pursue")
    auto_parser.add_argument("--max-cycles", type=int, default=80, help="Max cycles per goal")
    auto_parser.add_argument("--host", type=str, default="localhost")
    auto_parser.add_argument("--port", type=int, default=25565)
    auto_parser.add_argument("--username", type=str, default="Singularity")
    auto_parser.add_argument("--bridge-host", type=str, default="127.0.0.1")
    auto_parser.add_argument("--bridge-port", type=int, default=3000)
    auto_parser.add_argument("--llm-provider", type=str, default="openai")
    auto_parser.add_argument("--llm-model", type=str, default="gpt-4o-mini")
    auto_parser.add_argument("--llm-base-url", type=str, default="")
    auto_parser.add_argument("--api-key", type=str, default="")
    auto_parser.add_argument("--goal-critic", action="store_true", help="Use configured LLM as fallback critic for unknown goal verification")
    _add_goal_critic_runtime_gate_args(auto_parser)
    _add_task_continuity_args(auto_parser)
    _add_bounded_planning_context_args(auto_parser)
    auto_parser.add_argument("--no-skill-memory-context", action="store_true", help="Disable skill-level memory hints in planner context")
    auto_parser.add_argument("--no-vision-analysis", action="store_true", help="Disable structured vision grounding on observations")
    auto_parser.add_argument("--no-visual-action-grounding", action="store_true", help="Disable visual suggestions from modifying planned actions")
    auto_parser.add_argument("--capture-screenshots", action="store_true", help="Ask the bridge renderer to capture screenshots for visual analysis")
    auto_parser.add_argument("--screenshot-dir", type=str, default="logs/screenshots", help="Directory for captured screenshot files")
    auto_parser.add_argument("--screenshot-min-interval", type=float, default=2.0, help="Minimum seconds between screenshot capture attempts")
    auto_parser.add_argument("--mixed-policy-patch", action="append", default=[], help="Approved mixed-initiative policy patch JSON to load at runtime")
    auto_parser.add_argument("--mixed-policy-gate", action="append", default=[], help="Approved mixed-policy gate JSON required before loading runtime policy patches")
    auto_parser.add_argument("--self-evolution-feedback", action="append", default=[], help="self-evolution-report JSON to load as advisory planner feedback")
    auto_parser.add_argument("--world-model-feedback", action="append", default=[], help="world-model-report JSON to load into autonomous curriculum after approved gate")
    auto_parser.add_argument("--world-model-gate", action="append", default=[], help="Approved world-model-feedback-gate JSON required before loading world-model feedback")
    _add_memory_promptware_runtime_args(auto_parser)
    _add_memory_attribution_runtime_args(auto_parser)
    _add_plan_cache_runtime_args(auto_parser)
    _add_knowledge_correction_args(auto_parser)
    _add_task_precondition_args(auto_parser)
    auto_parser.add_argument("--action-value-feedback", action="append", default=[], help="action-value-report JSON to load for advisory action candidate scoring")
    auto_parser.add_argument("--action-value-transition-gate", action="append", default=[], help="Approved action-value-transition-gate JSON required before loading ASV transition scores")
    auto_parser.add_argument("--action-value-transition-evaluator-report", action="append", default=[], help="Approved action-value-transition-evaluator-report JSON required before loading ASV transition scores")
    auto_parser.add_argument("--skill-memory-quality-feedback", action="append", default=[], help="skill-memory-quality-report JSON to load for advisory skill-memory retrieval ranking")
    auto_parser.add_argument("--skill-memory-quality-gate", action="append", default=[], help="Approved skill-memory-quality-gate JSON required before loading quality feedback")
    _add_skill_runtime_default_args(auto_parser)
    _add_coaching_args(auto_parser)
    auto_parser.add_argument("--log-level", type=str, default="INFO")

    # Benchmark command
    bench_parser = subparsers.add_parser("benchmark", help="Run benchmarks")
    _add_runtime_profile_args(bench_parser)
    bench_parser.add_argument("--suite", type=str, default="m1", choices=["m1", "m2", "all"])
    bench_parser.add_argument("--host", type=str, default="localhost")
    bench_parser.add_argument("--port", type=int, default=25565)
    bench_parser.add_argument("--username", type=str, default="Singularity")
    bench_parser.add_argument("--bridge-host", type=str, default="127.0.0.1")
    bench_parser.add_argument("--bridge-port", type=int, default=3000)
    bench_parser.add_argument("--llm-provider", type=str, default="openai")
    bench_parser.add_argument("--llm-model", type=str, default="gpt-4o-mini")
    bench_parser.add_argument("--llm-base-url", type=str, default="")
    bench_parser.add_argument("--api-key", type=str, default="")
    bench_parser.add_argument("--goal-critic", action="store_true", help="Use configured LLM as fallback critic for unknown goal verification")
    _add_goal_critic_runtime_gate_args(bench_parser)
    _add_task_continuity_args(bench_parser)
    _add_bounded_planning_context_args(bench_parser)
    bench_parser.add_argument("--no-skill-memory-context", action="store_true", help="Disable skill-level memory hints in planner context")
    bench_parser.add_argument("--no-vision-analysis", action="store_true", help="Disable structured vision grounding on observations")
    bench_parser.add_argument("--no-visual-action-grounding", action="store_true", help="Disable visual suggestions from modifying planned actions")
    bench_parser.add_argument("--capture-screenshots", action="store_true", help="Ask the bridge renderer to capture screenshots for visual analysis")
    bench_parser.add_argument("--screenshot-dir", type=str, default="logs/screenshots", help="Directory for captured screenshot files")
    bench_parser.add_argument("--screenshot-min-interval", type=float, default=2.0, help="Minimum seconds between screenshot capture attempts")
    bench_parser.add_argument("--mixed-policy-patch", action="append", default=[], help="Approved mixed-initiative policy patch JSON to load in benchmark agents")
    bench_parser.add_argument("--mixed-policy-gate", action="append", default=[], help="Approved mixed-policy gate JSON required before loading benchmark policy patches")
    bench_parser.add_argument("--self-evolution-feedback", action="append", default=[], help="self-evolution-report JSON to load as advisory planner feedback")
    bench_parser.add_argument("--world-model-feedback", action="append", default=[], help="world-model-report JSON to load into autonomous curriculum after approved gate")
    bench_parser.add_argument("--world-model-gate", action="append", default=[], help="Approved world-model-feedback-gate JSON required before loading world-model feedback")
    _add_memory_promptware_runtime_args(bench_parser)
    _add_memory_attribution_runtime_args(bench_parser)
    _add_plan_cache_runtime_args(bench_parser)
    _add_knowledge_correction_args(bench_parser)
    _add_task_precondition_args(bench_parser)
    bench_parser.add_argument("--knowledge-correction-preflight", action="store_true", help="Run approved gate and suite-coverage preflight before knowledge-correction-assisted benchmarks")
    bench_parser.add_argument("--knowledge-correction-preflight-output", type=str, default="", help="Optional JSON path for the knowledge-correction benchmark preflight report")
    bench_parser.add_argument("--action-value-feedback", action="append", default=[], help="action-value-report JSON to load for advisory action candidate scoring")
    bench_parser.add_argument("--action-value-transition-gate", action="append", default=[], help="Approved action-value-transition-gate JSON required before loading ASV transition scores")
    bench_parser.add_argument("--action-value-transition-evaluator-report", action="append", default=[], help="Approved action-value-transition-evaluator-report JSON required before loading ASV transition scores")
    bench_parser.add_argument("--action-value-transition-preflight", action="store_true", help="Run saved action-value transition gate/evaluator preflight before transition-scored benchmarks")
    bench_parser.add_argument("--action-value-transition-preflight-output", type=str, default="", help="Optional JSON path for the action-value transition benchmark preflight report")
    bench_parser.add_argument("--require-action-value-transition-evaluator-report", action="store_true", help="Require approved state-grounded evaluator reports in action-value transition preflight")
    bench_parser.add_argument("--skill-memory-quality-feedback", action="append", default=[], help="skill-memory-quality-report JSON to load for advisory skill-memory retrieval ranking")
    bench_parser.add_argument("--skill-memory-quality-gate", action="append", default=[], help="Approved skill-memory-quality-gate JSON required before loading quality feedback")
    bench_parser.add_argument("--skill-memory-quality-preflight", action="store_true", help="Run gate and offline ranking preflight before quality-feedback-assisted benchmarks")
    bench_parser.add_argument("--skill-memory-quality-preflight-output", type=str, default="", help="Optional JSON path for the skill-memory quality benchmark preflight report")
    _add_skill_runtime_default_args(bench_parser)
    bench_parser.add_argument("--skill-runtime-default-preflight", action="store_true", help="Run approved runtime-default gate coverage preflight before learned default-skill benchmarks")
    bench_parser.add_argument("--skill-runtime-default-preflight-output", type=str, default="", help="Optional JSON path for the skill runtime-default benchmark preflight report")
    bench_parser.add_argument("--runtime-profile-suite-report", action="append", default=[], help="Approved runtime-profile-suite-report JSON required before profile-assisted benchmarks")
    bench_parser.add_argument("--runtime-profile-suite-preflight", action="store_true", help="Run runtime profile suite coverage preflight before profile-assisted benchmarks")
    bench_parser.add_argument("--runtime-profile-suite-preflight-output", type=str, default="", help="Optional JSON path for the runtime profile suite benchmark preflight report")
    bench_parser.add_argument("--runtime-profile-suite-required-profile", action="append", default=[], help="Required profile label for this benchmark preflight, such as m1 or m2")
    _add_coaching_args(bench_parser)
    bench_parser.add_argument("--coach-style-ablation", action="append", default=[], help="coach-style-ablation JSON used by benchmark coach-style preflight")
    bench_parser.add_argument("--coach-style-gate", action="append", default=[], help="Approved coach-style-gate JSON required before coach-style benchmark runs")
    bench_parser.add_argument("--coach-style-preflight", action="store_true", help="Run coach-style ablation/gate preflight before style-biased benchmarks")
    bench_parser.add_argument("--coach-style-preflight-output", type=str, default="", help="Optional JSON path for the coach-style benchmark preflight report")
    bench_parser.add_argument("--require-coach-style-goal-change", action="store_true", help="Require at least one top-goal change for each requested coach style")
    bench_parser.add_argument("--log-level", type=str, default="INFO")
    bench_parser.add_argument("--output", type=str, default="benchmark_results.json")
    bench_parser.add_argument("--preflight", action="store_true", help="Run readiness checks before benchmarks")
    bench_parser.add_argument("--ingest", action="store_true", help="Ingest passing benchmark traces into memory and skill candidate queue")
    bench_parser.add_argument("--promotion-critic", action="store_true", help="Use configured LLM as fallback critic for unknown skill-candidate verifier gates during ingestion")
    bench_parser.add_argument("--policy-skill-ablation", action="store_true", help="Run suite twice with reviewed policy skills disabled and enabled")
    bench_parser.add_argument("--skill-memory-ablation", action="store_true", help="Run suite twice with policy skills enabled but skill-memory context disabled vs enabled")
    bench_parser.add_argument("--visual-action-ablation", action="store_true", help="Run suite twice with visual action grounding disabled and enabled")
    bench_parser.add_argument("--mixed-policy-ablation", action="store_true", help="Run suite twice without and with approved mixed-policy patches")

    capability_parser = subparsers.add_parser(
        "capability-evidence-report",
        help="Compare M0-M7 completion claims against source, live, and repeated benchmark evidence",
    )
    capability_parser.add_argument("--benchmark-results", action="append", default=[], help="Benchmark result JSON to include; defaults to logs/benchmarks/benchmark_results.json")
    capability_parser.add_argument("--m3-evidence", action="append", default=[], help="Continual-learning report or task-stream transfer gate JSON; repeat for multiple files; defaults to current artifacts when available")
    capability_parser.add_argument("--m5-evidence", action="append", default=[], help="Exploration report or world-model feedback gate JSON; repeat for multiple files; defaults to current artifacts when available")
    capability_parser.add_argument("--m6-evidence", action="append", default=[], help="Visual trace or non-builtin visual-action ablation JSON; repeat for multiple files; defaults to current artifacts when available")
    capability_parser.add_argument("--status-file", type=str, default="workspace/STATUS.md", help="Markdown phase status table to audit")
    capability_parser.add_argument("--source-root", type=str, default=".", help="Repository root for source-presence checks")
    capability_parser.add_argument("--min-repeats", type=int, default=3, help="Distinct successful executions required for a capability claim")
    capability_parser.add_argument("--check-runtime", action="store_true", help="Include current benchmark preflight evidence")
    capability_parser.add_argument("--host", type=str, default="localhost")
    capability_parser.add_argument("--port", type=int, default=25565)
    capability_parser.add_argument("--bridge-host", type=str, default="127.0.0.1")
    capability_parser.add_argument("--bridge-port", type=int, default=3000)
    capability_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    capability_parser.add_argument("--strict", action="store_true", help="Exit nonzero until the full capability ledger is repeat-verified")
    capability_parser.add_argument("--log-level", type=str, default="INFO")

    # Benchmark preflight command
    preflight_parser = subparsers.add_parser("preflight", help="Check benchmark readiness without running tasks")
    preflight_parser.add_argument("--host", type=str, default="localhost")
    preflight_parser.add_argument("--port", type=int, default=25565)
    preflight_parser.add_argument("--username", type=str, default="Singularity")
    preflight_parser.add_argument("--bridge-host", type=str, default="127.0.0.1")
    preflight_parser.add_argument("--bridge-port", type=int, default=3000)
    preflight_parser.add_argument("--skip-network", action="store_true", help="Skip bot bridge and MC server TCP checks")
    preflight_parser.add_argument("--screenshot-renderer", action="store_true", help="Check optional prismarine-viewer screenshot renderer dependencies")
    preflight_parser.add_argument("--log-level", type=str, default="INFO")

    # Screenshot bridge runtime smoke test
    screenshot_smoke_parser = subparsers.add_parser("screenshot-smoke-test", help="Capture one screenshot through the live bridge and verify the local image file")
    screenshot_smoke_parser.add_argument("--host", type=str, default="localhost")
    screenshot_smoke_parser.add_argument("--port", type=int, default=25565)
    screenshot_smoke_parser.add_argument("--username", type=str, default="Singularity")
    screenshot_smoke_parser.add_argument("--bridge-host", type=str, default="127.0.0.1")
    screenshot_smoke_parser.add_argument("--bridge-port", type=int, default=3000)
    screenshot_smoke_parser.add_argument("--screenshot-dir", type=str, default="logs/screenshots", help="Directory for default smoke-test screenshot")
    screenshot_smoke_parser.add_argument("--screenshot-path", type=str, default="", help="Exact screenshot path to request from the bridge")
    screenshot_smoke_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    screenshot_smoke_parser.add_argument("--log-level", type=str, default="INFO")

    # Skills info command
    skills_parser = subparsers.add_parser("skills", help="List available skills")

    # Skill graph governance report
    skill_graph_parser = subparsers.add_parser("skill-graph-report", help="Report skill dependencies, provenance, and promotion gates")
    skill_graph_parser.add_argument("--skill-storage-path", type=str, default="workspace/skills", help="Skill storage path containing custom_skills.jsonl")
    skill_graph_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    skill_graph_parser.add_argument("--log-level", type=str, default="INFO")

    # Skill contract retrieval report
    skill_contract_parser = subparsers.add_parser("skill-contract-report", help="Report skill contract readiness for a goal and world state")
    skill_contract_parser.add_argument("--skill-storage-path", type=str, default="workspace/skills", help="Skill storage path containing custom_skills.jsonl")
    skill_contract_parser.add_argument("--goal", type=str, required=True, help="Goal or task query to score against skill contracts")
    skill_contract_parser.add_argument("--world-state-json", type=str, default="", help="Optional world state JSON object")
    skill_contract_parser.add_argument("--world-state-file", type=str, default="", help="Optional world state JSON file")
    skill_contract_parser.add_argument("--limit", type=int, default=20)
    skill_contract_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    skill_contract_parser.add_argument("--log-level", type=str, default="INFO")

    # Skill-local memory report
    skill_memory_parser = subparsers.add_parser("skill-memory-report", help="Report per-skill replay, failure, and transfer memories")
    skill_memory_parser.add_argument("--skill-storage-path", type=str, default="workspace/skills", help="Skill storage path containing custom_skills.jsonl")
    skill_memory_parser.add_argument("--goal", type=str, default="", help="Optional goal query to score skill contracts alongside memory")
    skill_memory_parser.add_argument("--task-family", type=str, default="", help="Optional task-family zone such as crafting, mining, shelter, or navigation")
    skill_memory_parser.add_argument("--include-builtins", action="store_true", help="Include built-in skills even when they have no skill memory")
    skill_memory_parser.add_argument("--limit", type=int, default=20)
    skill_memory_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    skill_memory_parser.add_argument("--log-level", type=str, default="INFO")

    # MUSE-style skill lifecycle report
    skill_lifecycle_parser = subparsers.add_parser(
        "skill-lifecycle-report",
        help="Audit skill creation, memory, management, evaluation, and refinement readiness",
    )
    skill_lifecycle_parser.add_argument("--skill-storage-path", type=str, default="workspace/skills", help="Skill storage path containing custom_skills.jsonl")
    skill_lifecycle_parser.add_argument("--goal", type=str, default="", help="Optional goal query to score skill contracts alongside lifecycle readiness")
    skill_lifecycle_parser.add_argument("--task-family", type=str, default="", help="Optional task-family zone such as crafting, mining, shelter, or navigation")
    skill_lifecycle_parser.add_argument("--include-builtins", action="store_true", help="Include built-in skills in the lifecycle audit")
    skill_lifecycle_parser.add_argument("--limit", type=int, default=20)
    skill_lifecycle_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    skill_lifecycle_parser.add_argument("--log-level", type=str, default="INFO")

    skill_runtime_gate_parser = subparsers.add_parser(
        "skill-runtime-default-gate",
        help="Gate task-family runtime-default skill enablement with lifecycle and transfer evidence",
    )
    skill_runtime_gate_parser.add_argument("--skill-lifecycle-report", action="append", default=[], help="Saved skill-lifecycle-report JSON")
    skill_runtime_gate_parser.add_argument("--task-stream-transfer-gate", action="append", default=[], help="Saved approved task-stream-transfer-gate JSON")
    skill_runtime_gate_parser.add_argument("--skill-memory-quality-gate", action="append", default=[], help="Optional saved skill-memory-quality-gate JSON")
    skill_runtime_gate_parser.add_argument("--target-task-family", type=str, default="", help="Optional task-family scope such as crafting, mining, shelter, or navigation")
    skill_runtime_gate_parser.add_argument("--require-skill-memory-quality-gate", action="store_true", help="Require approved localized skill-memory quality evidence")
    skill_runtime_gate_parser.add_argument("--min-runtime-candidates", type=int, default=1, help="Minimum approved runtime-default candidates required")
    skill_runtime_gate_parser.add_argument("--output", type=str, default="", help="Optional JSON gate report path")
    skill_runtime_gate_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline skill-memory quality report
    skill_memory_quality_parser = subparsers.add_parser(
        "skill-memory-quality-report",
        help="Audit typed skill-memory hints against later session outcomes",
    )
    skill_memory_quality_parser.add_argument("--session-log", action="append", default=[], help="Session JSONL log to inspect")
    skill_memory_quality_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    skill_memory_quality_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline skill-memory quality ranking ablation
    skill_memory_quality_ablation_parser = subparsers.add_parser(
        "skill-memory-quality-ablation",
        help="Compare skill-memory hint ranking before and after quality feedback",
    )
    skill_memory_quality_ablation_parser.add_argument("--skill-storage-path", type=str, default="workspace/skills", help="Skill storage path containing custom_skills.jsonl")
    skill_memory_quality_ablation_parser.add_argument("--quality-feedback", action="append", default=[], help="skill-memory-quality-report JSON to apply for the adjusted ranking")
    skill_memory_quality_ablation_parser.add_argument("--goal", action="append", default=[], help="Goal/query to compare; repeat for multiple cases")
    skill_memory_quality_ablation_parser.add_argument("--task-family", type=str, default="", help="Optional task-family zone for all --goal cases")
    skill_memory_quality_ablation_parser.add_argument("--case-file", type=str, default="", help="Optional JSON/JSONL case file with goal and task_family fields")
    skill_memory_quality_ablation_parser.add_argument("--limit", type=int, default=5)
    skill_memory_quality_ablation_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    skill_memory_quality_ablation_parser.add_argument("--log-level", type=str, default="INFO")

    skill_memory_quality_gate_parser = subparsers.add_parser(
        "skill-memory-quality-gate",
        help="Gate REUSE skill-memory promotion with localized quality evidence",
    )
    skill_memory_quality_gate_parser.add_argument("--skill-memory-report", action="append", default=[], help="Saved skill-memory-report JSON")
    skill_memory_quality_gate_parser.add_argument("--quality-feedback", action="append", default=[], help="Saved skill-memory-quality-report JSON or feedback JSON")
    skill_memory_quality_gate_parser.add_argument("--target", type=str, default="skill_memory_reuse_promotion", help="Promotion target label for the gate report")
    skill_memory_quality_gate_parser.add_argument("--min-supported-reuse", type=int, default=2, help="Minimum localized supported REUSE count required")
    skill_memory_quality_gate_parser.add_argument("--max-conflicting-reuse", type=int, default=0, help="Maximum localized conflicting REUSE count allowed")
    skill_memory_quality_gate_parser.add_argument("--output", type=str, default="", help="Optional JSON gate report path")
    skill_memory_quality_gate_parser.add_argument("--log-level", type=str, default="INFO")

    # Memory consolidation report
    memory_report_parser = subparsers.add_parser("memory-consolidation-report", help="Report repeatedly recalled memories worth consolidation")
    memory_report_parser.add_argument("--memory-dir", type=str, default="workspace/memory")
    memory_report_parser.add_argument("--min-score", type=float, default=0.65)
    memory_report_parser.add_argument("--min-recall-count", type=int, default=2)
    memory_report_parser.add_argument("--min-unique-queries", type=int, default=2)
    memory_report_parser.add_argument("--limit", type=int, default=20)
    memory_report_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    memory_report_parser.add_argument("--log-level", type=str, default="INFO")

    memory_maintenance_parser = subparsers.add_parser(
        "memory-maintenance-report",
        help="Report review-only memory management skill candidates",
    )
    memory_maintenance_parser.add_argument("--memory-dir", type=str, default="workspace/memory")
    memory_maintenance_parser.add_argument("--query", type=str, default="", help="Optional retrieval query to scope promptware/filter checks")
    memory_maintenance_parser.add_argument("--current-state-json", type=str, default="", help="Optional current state JSON object")
    memory_maintenance_parser.add_argument("--current-state-file", type=str, default="", help="Optional current state JSON file")
    memory_maintenance_parser.add_argument("--memory-attribution-gate", action="append", default=[], help="Optional saved memory-attribution-gate JSON")
    memory_maintenance_parser.add_argument("--min-consolidation-score", type=float, default=0.65)
    memory_maintenance_parser.add_argument("--min-recall-count", type=int, default=2)
    memory_maintenance_parser.add_argument("--min-unique-queries", type=int, default=2)
    memory_maintenance_parser.add_argument("--limit", type=int, default=80)
    memory_maintenance_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    memory_maintenance_parser.add_argument("--log-level", type=str, default="INFO")

    # Echo-style transfer memory report
    transfer_memory_parser = subparsers.add_parser("transfer-memory-report", help="Report transfer-axis experience matches for a query")
    transfer_memory_parser.add_argument("--memory-dir", type=str, default="workspace/memory")
    transfer_memory_parser.add_argument("--query", type=str, required=True, help="Goal or task query to retrieve transferable experiences for")
    transfer_memory_parser.add_argument("--current-state-json", type=str, default="", help="Optional current state JSON object")
    transfer_memory_parser.add_argument("--current-state-file", type=str, default="", help="Optional current state JSON file")
    transfer_memory_parser.add_argument("--min-score", type=float, default=0.1)
    transfer_memory_parser.add_argument("--limit", type=int, default=10)
    transfer_memory_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    transfer_memory_parser.add_argument("--log-level", type=str, default="INFO")

    task_memory_parser = subparsers.add_parser("task-memory-report", help="Report task-centric memory context for a goal and task")
    task_memory_parser.add_argument("--memory-dir", type=str, default="workspace/memory")
    task_memory_parser.add_argument("--goal", type=str, required=True, help="Goal query to scope task memory")
    task_memory_parser.add_argument("--task-json", type=str, default="", help="Optional task JSON object")
    task_memory_parser.add_argument("--task-file", type=str, default="", help="Optional task JSON file")
    task_memory_parser.add_argument("--current-state-json", type=str, default="", help="Optional current state JSON object")
    task_memory_parser.add_argument("--current-state-file", type=str, default="", help="Optional current state JSON file")
    task_memory_parser.add_argument("--min-score", type=float, default=0.1)
    task_memory_parser.add_argument("--limit", type=int, default=5)
    task_memory_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    task_memory_parser.add_argument("--log-level", type=str, default="INFO")

    task_continuity_parser = subparsers.add_parser(
        "task-continuity-report",
        help="Report durable task-continuity checkpoints for resuming unresolved tasks",
    )
    task_continuity_parser.add_argument("--memory-dir", type=str, default="workspace/memory")
    task_continuity_parser.add_argument("--goal", type=str, default="", help="Optional goal query to scope continuity checkpoints")
    task_continuity_parser.add_argument("--current-state-json", type=str, default="", help="Optional current state JSON object")
    task_continuity_parser.add_argument("--current-state-file", type=str, default="", help="Optional current state JSON file")
    task_continuity_parser.add_argument("--limit", type=int, default=10)
    task_continuity_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    task_continuity_parser.add_argument("--log-level", type=str, default="INFO")

    task_continuity_import_parser = subparsers.add_parser(
        "task-continuity-import",
        help="Import durable task-continuity checkpoints from session JSONL logs",
    )
    task_continuity_import_parser.add_argument("--memory-dir", type=str, default="workspace/memory")
    task_continuity_import_parser.add_argument("--session-log", action="append", default=[], help="Session JSONL log to import")
    task_continuity_import_parser.add_argument("--source", type=str, default="session_import", help="Source label stored on imported checkpoints")
    task_continuity_import_parser.add_argument("--output", type=str, default="", help="Optional JSON import report path")
    task_continuity_import_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline memory policy trace report
    memory_policy_parser = subparsers.add_parser("memory-policy-report", help="Report memory write/read/manage policy gaps in session logs")
    memory_policy_parser.add_argument("--session-log", action="append", default=[], help="Session JSONL log to inspect")
    memory_policy_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    memory_policy_parser.add_argument("--log-level", type=str, default="INFO")

    memory_attribution_parser = subparsers.add_parser(
        "memory-attribution-report",
        help="Attribute memory reads to downstream plan/action/goal outcomes",
    )
    memory_attribution_parser.add_argument("--session-log", action="append", default=[], help="Session JSONL log to inspect")
    memory_attribution_parser.add_argument(
        "--attribution-window-events",
        type=int,
        default=16,
        help="Maximum events after a plan to inspect before the next plan",
    )
    memory_attribution_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    memory_attribution_parser.add_argument("--log-level", type=str, default="INFO")

    memory_attribution_gate_parser = subparsers.add_parser(
        "memory-attribution-gate",
        help="Gate weighted retrieval on outcome-attributed memory-read evidence",
    )
    memory_attribution_gate_parser.add_argument("--memory-attribution-report", action="append", default=[], help="Saved memory-attribution-report JSON")
    memory_attribution_gate_parser.add_argument("--target", type=str, default="weighted_memory_retrieval", help="Gate target label")
    memory_attribution_gate_parser.add_argument("--min-ready-logs", type=int, default=1, help="Minimum ready logs required")
    memory_attribution_gate_parser.add_argument("--min-attributed-reads", type=int, default=1, help="Minimum supported/conflicting reads required")
    memory_attribution_gate_parser.add_argument("--min-supported-reads", type=int, default=1, help="Minimum supported reads required")
    memory_attribution_gate_parser.add_argument("--min-attributed-read-rate", type=float, default=0.5, help="Minimum attributed reads divided by total reads")
    memory_attribution_gate_parser.add_argument("--max-conflicting-read-rate", type=float, default=0.0, help="Maximum conflicting reads divided by attributed reads")
    memory_attribution_gate_parser.add_argument("--max-no-result-read-rate", type=float, default=0.2, help="Maximum no-result reads divided by total reads")
    memory_attribution_gate_parser.add_argument("--output", type=str, default="", help="Optional JSON gate report path")
    memory_attribution_gate_parser.add_argument("--log-level", type=str, default="INFO")

    task_precondition_parser = subparsers.add_parser(
        "task-precondition-report",
        help="Mine review-only task precondition candidates from stalled plans and failed actions",
    )
    task_precondition_parser.add_argument("--session-log", action="append", default=[], help="Session JSONL log to inspect")
    task_precondition_parser.add_argument("--min-evidence-count", type=int, default=1, help="Minimum repeated evidence required per candidate")
    task_precondition_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    task_precondition_parser.add_argument("--log-level", type=str, default="INFO")

    task_precondition_gate_parser = subparsers.add_parser(
        "task-precondition-gate",
        help="Gate task-precondition reports before planner/runtime use",
    )
    task_precondition_gate_parser.add_argument("--task-precondition-report", action="append", default=[], help="Saved task-precondition-report JSON")
    task_precondition_gate_parser.add_argument("--target", type=str, default="planner_task_precondition_feedback", help="Gate target label")
    task_precondition_gate_parser.add_argument("--min-ready-logs", type=int, default=1, help="Minimum ready logs required")
    task_precondition_gate_parser.add_argument("--min-candidates", type=int, default=1, help="Minimum task-precondition candidates required")
    task_precondition_gate_parser.add_argument("--min-high-confidence-candidates", type=int, default=0, help="Minimum candidates above --min-confidence")
    task_precondition_gate_parser.add_argument("--min-confidence", type=float, default=0.55, help="Confidence threshold for high-confidence candidates")
    task_precondition_gate_parser.add_argument("--output", type=str, default="", help="Optional JSON gate report path")
    task_precondition_gate_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline bounded planner context report
    bounded_context_parser = subparsers.add_parser("bounded-context-report", help="Audit bounded typed retrieval context before planner calls")
    bounded_context_parser.add_argument("--session-log", action="append", default=[], help="Session JSONL log to inspect")
    bounded_context_parser.add_argument("--max-read-chars", type=int, default=1200, help="Maximum characters allowed from any single memory read")
    bounded_context_parser.add_argument("--max-cycle-chars", type=int, default=2400, help="Maximum total memory-read characters allowed before each plan")
    bounded_context_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    bounded_context_parser.add_argument("--log-level", type=str, default="INFO")

    bounded_context_gate_parser = subparsers.add_parser("bounded-context-gate", help="Gate bounded-context reports before runtime/profile use")
    bounded_context_gate_parser.add_argument("--bounded-context-report", action="append", default=[], help="Saved bounded-context-report JSON")
    bounded_context_gate_parser.add_argument("--target", type=str, default="planner_context_contract", help="Gate target label")
    bounded_context_gate_parser.add_argument("--min-ready-logs", type=int, default=1, help="Minimum ready logs required")
    bounded_context_gate_parser.add_argument("--min-bounded-cycle-rate", type=float, default=1.0, help="Minimum bounded planning cycle rate required")
    bounded_context_gate_parser.add_argument("--max-unbounded-cycles", type=int, default=0, help="Maximum unbounded planner cycles allowed")
    bounded_context_gate_parser.add_argument("--max-missing-read-cycles", type=int, default=0, help="Maximum planner cycles without memory_read traces")
    bounded_context_gate_parser.add_argument("--max-oversized-read-cycles", type=int, default=0, help="Maximum planner cycles with oversized memory reads")
    bounded_context_gate_parser.add_argument("--max-oversized-cycles", type=int, default=0, help="Maximum planner cycles over total context budget")
    bounded_context_gate_parser.add_argument("--max-raw-context-cycles", type=int, default=0, help="Maximum planner cycles with raw transcript/context-window risk")
    bounded_context_gate_parser.add_argument("--max-low-diversity-cycles", type=int, default=0, help="Maximum planner cycles with low typed-retrieval diversity before review")
    bounded_context_gate_parser.add_argument("--output", type=str, default="", help="Optional JSON gate report path")
    bounded_context_gate_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline continual-learning trace report
    continual_parser = subparsers.add_parser("continual-learning-report", help="Report open-ended continual-learning diagnostics in session logs")
    continual_parser.add_argument("--session-log", action="append", default=[], help="Session JSONL log to inspect")
    continual_parser.add_argument("--cell-size", type=float, default=8.0, help="XZ block span per world-model cell")
    continual_parser.add_argument("--max-read-chars", type=int, default=1200, help="Maximum characters allowed from any single memory read")
    continual_parser.add_argument("--max-cycle-chars", type=int, default=2400, help="Maximum total memory-read characters allowed before each plan")
    continual_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    continual_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline controlled task-stream transfer report
    task_stream_parser = subparsers.add_parser(
        "task-stream-transfer-report",
        help="Report AgentCL-style transfer gains, stability, and interference in controlled task streams",
    )
    task_stream_parser.add_argument("--stream-file", action="append", default=[], help="JSON/JSONL controlled task stream spec")
    task_stream_parser.add_argument("--cell-size", type=float, default=8.0, help="XZ block span per world-model cell when deriving scores from session logs")
    task_stream_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    task_stream_parser.add_argument("--log-level", type=str, default="INFO")

    task_stream_gate_parser = subparsers.add_parser(
        "task-stream-transfer-gate",
        help="Gate memory or skill promotion using AgentCL-style task-stream transfer reports",
    )
    task_stream_gate_parser.add_argument("--transfer-report", action="append", default=[], help="Saved task-stream-transfer-report JSON")
    task_stream_gate_parser.add_argument("--target", type=str, default="memory_or_skill_promotion", help="Promotion target label for the gate report")
    task_stream_gate_parser.add_argument("--min-plasticity-gain", type=float, default=0.01, help="Minimum baseline-to-first-pass gain required")
    task_stream_gate_parser.add_argument("--min-stability-gain", type=float, default=0.0, help="Minimum second-pass minus first-pass gain required")
    task_stream_gate_parser.add_argument("--min-generalization-gain", type=float, default=0.0, help="Minimum held-out minus baseline gain required")
    task_stream_gate_parser.add_argument("--min-reuse-coverage", type=float, default=0.5, help="Minimum expected reuse-tag coverage required")
    task_stream_gate_parser.add_argument("--max-interference-count", type=int, default=0, help="Maximum allowed transfer/interference regressions")
    task_stream_gate_parser.add_argument("--no-require-heldout", action="store_true", help="Allow approval without held-out generalization evidence")
    task_stream_gate_parser.add_argument("--output", type=str, default="", help="Optional JSON gate report path")
    task_stream_gate_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline memory read filter report
    memory_read_parser = subparsers.add_parser("memory-read-filter-report", help="Report stale or condition-mismatched durable memories for a query")
    memory_read_parser.add_argument("--memory-dir", type=str, default="workspace/memory")
    memory_read_parser.add_argument("--query", type=str, default="", help="Optional retrieval query to filter relevant entries")
    memory_read_parser.add_argument("--current-state-json", type=str, default="", help="Optional current state JSON object for conditional applicability checks")
    memory_read_parser.add_argument("--current-state-file", type=str, default="", help="Optional JSON file with current state for conditional applicability checks")
    memory_read_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    memory_read_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline promptware memory audit
    memory_promptware_parser = subparsers.add_parser("memory-promptware-report", help="Report promptware or memory-injection threats in durable memory")
    memory_promptware_parser.add_argument("--memory-dir", type=str, default="workspace/memory")
    memory_promptware_parser.add_argument("--query", type=str, default="", help="Optional retrieval query to scope the audit")
    memory_promptware_parser.add_argument("--current-state-json", type=str, default="", help="Optional current state JSON object for conditional applicability checks")
    memory_promptware_parser.add_argument("--current-state-file", type=str, default="", help="Optional JSON file with current state for conditional applicability checks")
    memory_promptware_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    memory_promptware_parser.add_argument("--log-level", type=str, default="INFO")

    memory_promptware_gate_parser = subparsers.add_parser(
        "memory-promptware-gate",
        help="Gate stricter memory enforcement using saved memory-promptware-report JSON",
    )
    memory_promptware_gate_parser.add_argument("--memory-promptware-report", action="append", default=[], help="Saved memory-promptware-report JSON")
    memory_promptware_gate_parser.add_argument("--max-flagged-entries", type=int, default=0, help="Maximum flagged durable memory entries allowed")
    memory_promptware_gate_parser.add_argument("--max-flagged-experiences", type=int, default=0, help="Maximum flagged transferable experiences allowed")
    memory_promptware_gate_parser.add_argument("--output", type=str, default="", help="Optional JSON gate report path")
    memory_promptware_gate_parser.add_argument("--log-level", type=str, default="INFO")

    plan_cache_parser = subparsers.add_parser("plan-cache-report", help="Mine AgenticCache-style plan transitions from session logs")
    plan_cache_parser.add_argument("--session-log", action="append", default=[], help="Agent session JSONL log to mine")
    plan_cache_parser.add_argument("--min-support", type=int, default=1, help="Minimum repeated transition support for runtime cache approval")
    plan_cache_parser.add_argument("--min-success-rate", type=float, default=0.6, help="Minimum action/goal success rate for runtime cache approval")
    plan_cache_parser.add_argument("--max-entries", type=int, default=200, help="Maximum cache entries to include")
    plan_cache_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    plan_cache_parser.add_argument("--log-level", type=str, default="INFO")

    plan_cache_runtime_parser = subparsers.add_parser("plan-cache-runtime-report", help="Audit runtime plan-cache hits from session logs")
    plan_cache_runtime_parser.add_argument("--session-log", action="append", default=[], help="Agent session JSONL log with plan-cache hit/miss events")
    plan_cache_runtime_parser.add_argument("--min-cache-hits", type=int, default=1, help="Minimum cache hits required for approval")
    plan_cache_runtime_parser.add_argument("--max-rejected-action-rate", type=float, default=0.0, help="Maximum verifier-rejected action rate after cache hits")
    plan_cache_runtime_parser.add_argument("--max-action-failure-rate", type=float, default=0.3, help="Maximum failed action rate after cache hits")
    plan_cache_runtime_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    plan_cache_runtime_parser.add_argument("--log-level", type=str, default="INFO")

    plan_cache_gate_parser = subparsers.add_parser("plan-cache-gate", help="Gate plan-cache artifacts before runtime use")
    plan_cache_gate_parser.add_argument("--plan-cache-report", action="append", default=[], help="Saved plan-cache-report JSON")
    plan_cache_gate_parser.add_argument("--runtime-report", action="append", default=[], help="Optional saved plan-cache-runtime-report JSON")
    plan_cache_gate_parser.add_argument("--min-accepted-entries", type=int, default=1, help="Minimum accepted cache entries required")
    plan_cache_gate_parser.add_argument("--min-runtime-hits", type=int, default=0, help="Minimum runtime cache hits required when runtime reports are supplied")
    plan_cache_gate_parser.add_argument("--max-promptware-threats", type=int, default=0, help="Maximum promptware threats allowed across cache reports")
    plan_cache_gate_parser.add_argument("--max-rejected-action-rate", type=float, default=0.0, help="Maximum verifier-rejected action rate after cache hits")
    plan_cache_gate_parser.add_argument("--max-action-failure-rate", type=float, default=0.3, help="Maximum failed action rate after cache hits")
    plan_cache_gate_parser.add_argument("--output", type=str, default="", help="Optional JSON gate report path")
    plan_cache_gate_parser.add_argument("--log-level", type=str, default="INFO")

    agent_module_parser = subparsers.add_parser(
        "agent-module-comparison-report",
        help="Compare baseline vs candidate session logs across optional agent modules",
    )
    agent_module_parser.add_argument("--baseline-session-log", action="append", default=[], help="Baseline Agent session JSONL log")
    agent_module_parser.add_argument("--candidate-session-log", action="append", default=[], help="Candidate Agent session JSONL log")
    agent_module_parser.add_argument("--baseline-label", type=str, default="baseline")
    agent_module_parser.add_argument("--candidate-label", type=str, default="candidate")
    agent_module_parser.add_argument("--max-completion-regression", type=float, default=0.0)
    agent_module_parser.add_argument("--max-action-failure-regression", type=float, default=0.10)
    agent_module_parser.add_argument("--max-verifier-reject-regression", type=float, default=0.10)
    agent_module_parser.add_argument("--max-empty-plan-regression", type=float, default=0.10)
    agent_module_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    agent_module_parser.add_argument("--log-level", type=str, default="INFO")

    # Skill candidate review queue
    candidates_parser = subparsers.add_parser("skill-candidates", help="Review extracted skill candidates")
    candidates_parser.add_argument("--queue", type=str, default="workspace/skills/skill_candidates.jsonl")
    candidates_parser.add_argument("--storage-path", type=str, default="workspace/skills")
    candidates_parser.add_argument("--session", type=str, default="", help="Extract candidates from a session JSONL log")
    candidates_parser.add_argument("--promotion-critic", action="store_true", help="Use configured LLM as fallback critic for unknown verifier gates")
    candidates_parser.add_argument("--discovery-skill-gate", action="append", default=[], help="Saved discovery-application-report JSON required before approving experiment-derived skills")
    candidates_parser.add_argument("--task-stream-transfer-gate", action="append", default=[], help="Saved task-stream-transfer-gate JSON required before promoting transfer-tested skills")
    candidates_parser.add_argument("--causal-evidence-gate", action="append", default=[], help="Saved causal-evidence-report JSON required before approving causal-summary skills")
    candidates_parser.add_argument("--llm-provider", type=str, default="openai")
    candidates_parser.add_argument("--llm-model", type=str, default="gpt-4o-mini")
    candidates_parser.add_argument("--llm-base-url", type=str, default="")
    candidates_parser.add_argument("--api-key", type=str, default="")
    candidates_parser.add_argument("--causal-summaries", action="store_true", help="Extract repeated causal-summary candidates from the session log")
    candidates_parser.add_argument("--min-causal-repeats", type=int, default=3, help="Minimum repeated causal events before queueing a summary candidate")
    candidates_parser.add_argument("--min-causal-value", type=float, default=0.65, help="Minimum causal value score before queueing a summary candidate")
    candidates_parser.add_argument("--failure-corrections", action="store_true", help="Extract repeated failure-to-correction candidates from the session log")
    candidates_parser.add_argument("--min-failure-repeats", type=int, default=2, help="Minimum repeated failures before queueing a correction candidate")
    candidates_parser.add_argument("--min-failure-value", type=float, default=0.55, help="Minimum failure value score before queueing a correction candidate")
    candidates_parser.add_argument("--approve", type=str, default="", help="Approve a candidate id")
    candidates_parser.add_argument("--reject", type=str, default="", help="Reject a candidate id")
    candidates_parser.add_argument("--reason", type=str, default="", help="Reason for rejection")
    candidates_parser.add_argument("--all", action="store_true", help="List all candidates, not just pending")

    skill_edit_parser = subparsers.add_parser(
        "skill-edit-proposal-report",
        help="Review queued skill candidates as create/update/retain/reject proposals",
    )
    skill_edit_parser.add_argument("--queue", type=str, default="workspace/skills/skill_candidates.jsonl")
    skill_edit_parser.add_argument("--skill-storage-path", type=str, default="workspace/skills")
    skill_edit_parser.add_argument("--discovery-skill-gate", action="append", default=[], help="Saved discovery-application-report JSON to include in candidate validation")
    skill_edit_parser.add_argument("--task-stream-transfer-gate", action="append", default=[], help="Saved task-stream-transfer-gate JSON used as counterfactual probe evidence")
    skill_edit_parser.add_argument("--causal-evidence-gate", action="append", default=[], help="Saved causal-evidence-report JSON to include in causal-summary validation")
    skill_edit_parser.add_argument("--include-all", action="store_true", help="Include approved/rejected candidates as retain/review records")
    skill_edit_parser.add_argument("--no-require-transfer-gate", action="store_true", help="Allow create/update proposals without approved transfer probe evidence")
    skill_edit_parser.add_argument("--min-score", type=float, default=0.55, help="Minimum candidate score for create/update proposals")
    skill_edit_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    skill_edit_parser.add_argument("--log-level", type=str, default="INFO")

    # M7 collaboration benchmark dry-run/assignment
    collab_parser = subparsers.add_parser("collab-benchmark", help="Prepare an M7 collaboration benchmark")
    _add_runtime_profile_args(collab_parser)
    collab_parser.add_argument("--spec", type=str, default="workspace/benchmarks/m7_time_sensitive_shelter.json")
    collab_parser.add_argument("--state-path", type=str, default="workspace/multiagent/collab_benchmark_state.json")
    collab_parser.add_argument("--no-reset", action="store_true", help="Keep existing shared-state file")
    collab_parser.add_argument("--preflight", action="store_true", help="Check Agent executor role bridges before execution")
    collab_parser.add_argument("--execute", action="store_true", help="Run the synchronous state-transition executor after assignment")
    collab_parser.add_argument("--executor", type=str, default="simulated", choices=["simulated", "agent"], help="Task executor for --execute")
    collab_parser.add_argument("--max-steps", type=int, default=0, help="Maximum dispatch steps for --execute")
    collab_parser.add_argument("--mixed-policy-ablation", action="store_true", help="Run Agent-backed collaboration once without and once with approved mixed-policy patches")
    collab_parser.add_argument("--host", type=str, default="localhost")
    collab_parser.add_argument("--port", type=int, default=25565)
    collab_parser.add_argument("--username", type=str, default="Singularity")
    collab_parser.add_argument("--bridge-host", type=str, default="127.0.0.1")
    collab_parser.add_argument("--bridge-port", type=int, default=3000)
    collab_parser.add_argument("--bridge-port-base", type=int, default=0, help="Use sequential bridge ports from this base for Agent executor roles")
    collab_parser.add_argument("--role-bridge-port", action="append", default=[], metavar="ROLE=PORT", help="Explicit Agent executor bridge port for a role; repeat for multiple roles")
    collab_parser.add_argument("--single-agent-baseline", action="store_true", help="Run a single-agent baseline after collaboration execution")
    collab_parser.add_argument("--baseline-role-id", type=str, default="single_agent", help="Role id for --single-agent-baseline")
    collab_parser.add_argument("--baseline-state-path", type=str, default="", help="Optional shared-state path for the single-agent baseline")
    collab_parser.add_argument("--llm-provider", type=str, default="openai")
    collab_parser.add_argument("--llm-model", type=str, default="gpt-4o-mini")
    collab_parser.add_argument("--llm-base-url", type=str, default="")
    collab_parser.add_argument("--api-key", type=str, default="")
    collab_parser.add_argument("--goal-critic", action="store_true", help="Use configured LLM as fallback critic for unknown goal verification")
    _add_goal_critic_runtime_gate_args(collab_parser)
    _add_task_continuity_args(collab_parser)
    collab_parser.add_argument("--no-skill-memory-context", action="store_true", help="Disable skill-level memory hints in planner context")
    collab_parser.add_argument("--no-vision-analysis", action="store_true", help="Disable structured vision grounding on observations")
    collab_parser.add_argument("--no-visual-action-grounding", action="store_true", help="Disable visual suggestions from modifying planned actions")
    collab_parser.add_argument("--capture-screenshots", action="store_true", help="Ask each Agent bridge renderer to capture screenshots for visual analysis")
    collab_parser.add_argument("--screenshot-dir", type=str, default="logs/screenshots", help="Directory for captured screenshot files")
    collab_parser.add_argument("--screenshot-min-interval", type=float, default=2.0, help="Minimum seconds between screenshot capture attempts")
    collab_parser.add_argument("--mixed-policy-patch", action="append", default=[], help="Approved mixed-initiative policy patch JSON to load in Agent executor roles")
    collab_parser.add_argument("--mixed-policy-gate", action="append", default=[], help="Approved mixed-policy gate JSON required before loading Agent executor policy patches")
    collab_parser.add_argument("--self-evolution-feedback", action="append", default=[], help="self-evolution-report JSON to load as advisory planner feedback")
    collab_parser.add_argument("--world-model-feedback", action="append", default=[], help="world-model-report JSON to load into Agent executor curriculum after approved gate")
    collab_parser.add_argument("--world-model-gate", action="append", default=[], help="Approved world-model-feedback-gate JSON required before loading world-model feedback")
    _add_memory_promptware_runtime_args(collab_parser)
    _add_memory_attribution_runtime_args(collab_parser)
    _add_plan_cache_runtime_args(collab_parser)
    _add_knowledge_correction_args(collab_parser)
    _add_task_precondition_args(collab_parser)
    collab_parser.add_argument("--action-value-feedback", action="append", default=[], help="action-value-report JSON to load for advisory action candidate scoring")
    collab_parser.add_argument("--action-value-transition-gate", action="append", default=[], help="Approved action-value-transition-gate JSON required before loading ASV transition scores")
    collab_parser.add_argument("--action-value-transition-evaluator-report", action="append", default=[], help="Approved action-value-transition-evaluator-report JSON required before loading ASV transition scores")
    collab_parser.add_argument("--skill-memory-quality-feedback", action="append", default=[], help="skill-memory-quality-report JSON to load for advisory skill-memory retrieval ranking")
    collab_parser.add_argument("--skill-memory-quality-gate", action="append", default=[], help="Approved skill-memory-quality-gate JSON required before loading quality feedback")
    _add_skill_runtime_default_args(collab_parser)
    collab_parser.add_argument("--runtime-profile-suite-report", action="append", default=[], help="Approved runtime-profile-suite-report JSON required before profile-assisted M7 Agent collaboration")
    collab_parser.add_argument("--runtime-profile-suite-preflight", action="store_true", help="Run runtime profile suite coverage preflight before M7 Agent collaboration")
    collab_parser.add_argument("--runtime-profile-suite-preflight-output", type=str, default="", help="Optional JSON path for the runtime profile suite M7 preflight report")
    collab_parser.add_argument("--runtime-profile-suite-required-profile", action="append", default=[], help="Required profile label for M7 preflight, defaults to m7")
    _add_coaching_args(collab_parser)
    collab_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    collab_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline scheduling ablation
    scheduling_parser = subparsers.add_parser("scheduling-ablation", help="Compare direct-only vs causal-opportunity task scheduling")
    scheduling_parser.add_argument("--session-log", action="append", default=[], help="Replay a session JSONL log into scheduling ablation cases")
    scheduling_parser.add_argument("--max-cases-per-log", type=int, default=20)
    scheduling_parser.add_argument("--min-value-score", type=float, default=0.55, help="Minimum causal event value for session-log replay")
    scheduling_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    scheduling_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline runtime coaching ablation
    coach_ablation_parser = subparsers.add_parser(
        "coach-style-ablation",
        help="Compare baseline curriculum ranking against advisory coaching styles",
    )
    coach_ablation_parser.add_argument("--style", action="append", default=[], help="Coach style to compare; repeat for multiple styles")
    coach_ablation_parser.add_argument("--case-file", action="append", default=[], help="JSON/JSONL cases with observation/current_state and fallback_goal fields")
    coach_ablation_parser.add_argument("--session-log", action="append", default=[], help="Replay observation snapshots from session JSONL logs")
    coach_ablation_parser.add_argument("--fallback-goal", type=str, default="Explore surroundings and gather resources", help="Fallback goal for session-log observations")
    coach_ablation_parser.add_argument("--max-cases-per-log", type=int, default=20)
    coach_ablation_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    coach_ablation_parser.add_argument("--log-level", type=str, default="INFO")

    coach_gate_parser = subparsers.add_parser(
        "coach-style-gate",
        help="Gate advisory coaching styles with offline curriculum ablation evidence",
    )
    coach_gate_parser.add_argument("--coach-style-ablation", action="append", default=[], help="Saved coach-style-ablation JSON report")
    coach_gate_parser.add_argument("--style", action="append", default=[], help="Style that must be covered; repeat for multiple styles")
    coach_gate_parser.add_argument("--target", type=str, default="coach_style_curriculum_bias", help="Gate target label")
    coach_gate_parser.add_argument("--min-cases-per-style", type=int, default=1, help="Minimum ablation cases required per style")
    coach_gate_parser.add_argument("--min-score-changed-per-style", type=int, default=1, help="Minimum score-changing cases required per style")
    coach_gate_parser.add_argument("--require-goal-change", action="store_true", help="Require at least one top-goal change for each requested style")
    coach_gate_parser.add_argument("--output", type=str, default="", help="Optional JSON gate report path")
    coach_gate_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline promotion review visual ablation
    review_parser = subparsers.add_parser("promotion-review-ablation", help="Compare skill promotion review with and without visual evidence")
    review_parser.add_argument("--session-log", action="append", default=[], help="Replay a session JSONL log into promotion review ablation")
    review_parser.add_argument("--promotion-critic", action="store_true", help="Use configured LLM critic for unknown verifier gates")
    review_parser.add_argument("--llm-provider", type=str, default="openai")
    review_parser.add_argument("--llm-model", type=str, default="gpt-4o-mini")
    review_parser.add_argument("--llm-base-url", type=str, default="")
    review_parser.add_argument("--api-key", type=str, default="")
    review_parser.add_argument("--causal-summaries", action="store_true", help="Include repeated causal-summary candidates")
    review_parser.add_argument("--failure-corrections", action="store_true", help="Include repeated failure-correction candidates")
    review_parser.add_argument("--label-file", type=str, default="", help="Optional manual labels JSON/JSONL for agreement metrics")
    review_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    review_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline goal verification visual ablation
    goal_review_parser = subparsers.add_parser("goal-verification-ablation", help="Compare goal verification with deterministic, API visual, and screenshot/VLM evidence")
    goal_review_parser.add_argument("--session-log", action="append", default=[], help="Replay a session JSONL log into goal verification ablation")
    goal_review_parser.add_argument("--goal-critic", action="store_true", help="Use configured LLM critic for unknown goal verifier coverage")
    goal_review_parser.add_argument("--llm-provider", type=str, default="openai")
    goal_review_parser.add_argument("--llm-model", type=str, default="gpt-4o-mini")
    goal_review_parser.add_argument("--llm-base-url", type=str, default="")
    goal_review_parser.add_argument("--api-key", type=str, default="")
    goal_review_parser.add_argument("--label-file", type=str, default="", help="Optional manual labels JSON/JSONL for agreement metrics")
    goal_review_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    goal_review_parser.add_argument("--log-level", type=str, default="INFO")

    goal_critic_gate_parser = subparsers.add_parser(
        "goal-verification-critic-gate",
        help="Gate runtime goal-verification critics with offline ablation and manual-label evidence",
    )
    goal_critic_gate_parser.add_argument("--goal-verification-ablation", action="append", default=[], help="Saved goal-verification-ablation or visual-review-pipeline JSON")
    goal_critic_gate_parser.add_argument("--label-validation", action="append", default=[], help="Saved review-label-validate or visual-review-pipeline JSON")
    goal_critic_gate_parser.add_argument("--target", type=str, default="goal_verification_critic_runtime", help="Gate target label")
    goal_critic_gate_parser.add_argument("--min-cases", type=int, default=1, help="Minimum goal-verification ablation cases required")
    goal_critic_gate_parser.add_argument("--min-manual-labels", type=int, default=1, help="Minimum manual goal labels required")
    goal_critic_gate_parser.add_argument("--min-screenshot-cases", type=int, default=1, help="Minimum verified screenshot-backed goal cases required")
    goal_critic_gate_parser.add_argument("--min-screenshot-manual-matches", type=int, default=1, help="Minimum screenshot/VLM judgments matching manual labels")
    goal_critic_gate_parser.add_argument("--max-screenshot-manual-mismatches", type=int, default=0, help="Maximum allowed screenshot/VLM mismatches against manual labels")
    goal_critic_gate_parser.add_argument("--min-screenshot-added-value", type=int, default=0, help="Minimum screenshot/VLM added-value cases required")
    goal_critic_gate_parser.add_argument("--no-require-label-validation", action="store_true", help="Allow approval without a separate review-label-validate report")
    goal_critic_gate_parser.add_argument("--output", type=str, default="", help="Optional JSON gate report path")
    goal_critic_gate_parser.add_argument("--log-level", type=str, default="INFO")

    runtime_profile_parser = subparsers.add_parser(
        "runtime-profile-validate",
        help="Validate reusable runtime profiles before live Agent startup",
    )
    runtime_profile_parser.add_argument("--runtime-profile", action="append", default=[], help="Runtime profile JSON to validate")
    runtime_profile_parser.add_argument("--output", type=str, default="", help="Optional JSON validation report path")
    runtime_profile_parser.add_argument("--log-level", type=str, default="INFO")

    runtime_profile_security_parser = subparsers.add_parser(
        "runtime-profile-security-audit",
        help="Audit runtime profile artifacts for promptware-like payloads before live Agent startup",
    )
    runtime_profile_security_parser.add_argument("--runtime-profile", action="append", default=[], help="Runtime profile JSON to audit")
    runtime_profile_security_parser.add_argument("--include-gates", action="store_true", help="Also scan referenced gate reports")
    runtime_profile_security_parser.add_argument("--max-scan-bytes", type=int, default=DEFAULT_SECURITY_SCAN_BYTES, help="Maximum bytes to scan per referenced file")
    runtime_profile_security_parser.add_argument("--max-findings", type=int, default=50, help="Maximum findings to include in the saved report")
    runtime_profile_security_parser.add_argument("--output", type=str, default="", help="Optional JSON audit report path")
    runtime_profile_security_parser.add_argument("--log-level", type=str, default="INFO")

    runtime_profile_suite_parser = subparsers.add_parser(
        "runtime-profile-suite-report",
        help="Validate and promptware-audit a directory of runtime profiles before live suites",
    )
    runtime_profile_suite_parser.add_argument("--runtime-profile", action="append", default=[], help="Runtime profile JSON to include")
    runtime_profile_suite_parser.add_argument("--runtime-dir", type=str, default="workspace/runtime", help="Directory of runtime profile JSON files to include")
    runtime_profile_suite_parser.add_argument("--required-profile", action="append", default=[], help="Required profile label such as m1, m2, or m7")
    runtime_profile_suite_parser.add_argument("--include-gates", action="store_true", help="Also promptware-scan referenced gate reports")
    runtime_profile_suite_parser.add_argument("--max-scan-bytes", type=int, default=DEFAULT_SECURITY_SCAN_BYTES, help="Maximum bytes to scan per referenced file")
    runtime_profile_suite_parser.add_argument("--max-findings", type=int, default=50, help="Maximum findings to include per profile security audit")
    runtime_profile_suite_parser.add_argument("--output", type=str, default="", help="Optional JSON suite report path")
    runtime_profile_suite_parser.add_argument("--log-level", type=str, default="INFO")

    runtime_profile_build_parser = subparsers.add_parser(
        "runtime-profile-build",
        help="Build a reusable runtime profile JSON from approved gates and feedback artifacts",
    )
    runtime_profile_build_parser.add_argument("--name", type=str, default="", help="Profile name")
    runtime_profile_build_parser.add_argument("--description", type=str, default="", help="Profile description")
    runtime_profile_build_parser.add_argument("--enable-goal-critic", action="store_true", help="Set enable_goal_critic in profile settings")
    runtime_profile_build_parser.add_argument("--coach-style", type=str, default="", help="Set coach_style in profile settings")
    runtime_profile_build_parser.add_argument("--capture-screenshots", action="store_true", help="Set enable_screenshot_capture in profile settings")
    runtime_profile_build_parser.add_argument("--enforce-memory-write-gate", action="store_true", help="Set enforce_memory_write_gate in profile settings")
    runtime_profile_build_parser.add_argument("--enable-weighted-memory-retrieval", action="store_true", help="Set enable_weighted_memory_retrieval in profile settings")
    runtime_profile_build_parser.add_argument("--enable-plan-cache", action="store_true", help="Set enable_plan_cache in profile settings")
    runtime_profile_build_parser.add_argument("--screenshot-dir", type=str, default="", help="Set screenshot_dir in profile settings")
    runtime_profile_build_parser.add_argument("--goal-critic-gate", action="append", default=[], help="Approved goal-verification-critic-gate JSON")
    runtime_profile_build_parser.add_argument("--mixed-policy-patch", action="append", default=[], help="Approved mixed-policy patch JSON")
    runtime_profile_build_parser.add_argument("--mixed-policy-gate", action="append", default=[], help="Approved mixed-policy gate JSON")
    runtime_profile_build_parser.add_argument("--self-evolution-feedback", action="append", default=[], help="self-evolution feedback JSON")
    runtime_profile_build_parser.add_argument("--world-model-feedback", action="append", default=[], help="world-model feedback JSON")
    runtime_profile_build_parser.add_argument("--world-model-gate", action="append", default=[], help="Approved world-model gate JSON")
    runtime_profile_build_parser.add_argument("--knowledge-correction-feedback", action="append", default=[], help="knowledge-correction feedback JSON")
    runtime_profile_build_parser.add_argument("--knowledge-correction-gate", action="append", default=[], help="Approved knowledge-correction gate JSON")
    runtime_profile_build_parser.add_argument("--task-precondition-feedback", action="append", default=[], help="task-precondition feedback JSON")
    runtime_profile_build_parser.add_argument("--task-precondition-gate", action="append", default=[], help="Approved task-precondition gate JSON")
    runtime_profile_build_parser.add_argument("--plan-cache", action="append", default=[], help="Approved plan-transition-cache report JSON")
    runtime_profile_build_parser.add_argument("--plan-cache-gate", action="append", default=[], help="Approved plan-cache gate JSON")
    runtime_profile_build_parser.add_argument("--action-value-feedback", action="append", default=[], help="action-value feedback JSON")
    runtime_profile_build_parser.add_argument("--action-value-transition-gate", action="append", default=[], help="Approved action-value transition gate JSON")
    runtime_profile_build_parser.add_argument("--action-value-transition-evaluator-report", action="append", default=[], help="Approved action-value evaluator report JSON")
    runtime_profile_build_parser.add_argument("--skill-memory-quality-feedback", action="append", default=[], help="skill-memory quality feedback JSON")
    runtime_profile_build_parser.add_argument("--skill-memory-quality-gate", action="append", default=[], help="Approved skill-memory quality gate JSON")
    runtime_profile_build_parser.add_argument("--skill-runtime-default-gate", action="append", default=[], help="Approved skill runtime-default gate JSON")
    runtime_profile_build_parser.add_argument("--memory-promptware-gate", action="append", default=[], help="Approved memory-promptware gate JSON")
    runtime_profile_build_parser.add_argument("--memory-attribution-gate", action="append", default=[], help="Approved memory-attribution gate JSON")
    runtime_profile_build_parser.add_argument("--coach-style-ablation", action="append", default=[], help="coach-style ablation JSON")
    runtime_profile_build_parser.add_argument("--coach-style-gate", action="append", default=[], help="Approved coach-style gate JSON")
    runtime_profile_build_parser.add_argument("--output", type=str, default="", help="Optional runtime profile JSON path")
    runtime_profile_build_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline manual review label templates
    label_template_parser = subparsers.add_parser("review-label-template", help="Generate JSONL manual review label templates from session logs")
    label_template_parser.add_argument("--session-log", action="append", default=[], help="Session JSONL log to convert into review label templates")
    label_template_parser.add_argument("--mode", type=str, default="both", choices=["promotion", "goal", "both"], help="Template type to generate")
    label_template_parser.add_argument("--causal-summaries", action="store_true", help="Include repeated causal-summary promotion candidates")
    label_template_parser.add_argument("--failure-corrections", action="store_true", help="Include repeated failure-correction promotion candidates")
    label_template_parser.add_argument("--output", type=str, default="", help="Optional JSONL output path")
    label_template_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline manual review label validation
    label_validate_parser = subparsers.add_parser("review-label-validate", help="Validate manual review labels before visual ablations")
    label_validate_parser.add_argument("--label-file", type=str, required=True, help="Manual labels JSON/JSONL file to validate")
    label_validate_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    label_validate_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline visual trace coverage report
    visual_trace_parser = subparsers.add_parser("visual-trace-report", help="Report screenshot/VLM/API visual evidence coverage in session logs")
    visual_trace_parser.add_argument("--session-log", action="append", default=[], help="Session JSONL log to inspect")
    visual_trace_parser.add_argument("--causal-summaries", action="store_true", help="Include repeated causal-summary promotion candidates")
    visual_trace_parser.add_argument("--failure-corrections", action="store_true", help="Include repeated failure-correction promotion candidates")
    visual_trace_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    visual_trace_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline open-world exploration trace report
    exploration_trace_parser = subparsers.add_parser("exploration-trace-report", help="Report autonomous/open-world exploration coverage in session logs")
    exploration_trace_parser.add_argument("--session-log", action="append", default=[], help="Session JSONL log to inspect")
    exploration_trace_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    exploration_trace_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline CausalGame-style causal evidence audit
    causal_evidence_parser = subparsers.add_parser(
        "causal-evidence-report",
        help="Audit contrastive causal evidence, bias risks, and counterexamples in session logs",
    )
    causal_evidence_parser.add_argument("--session-log", action="append", default=[], help="Session JSONL log to inspect")
    causal_evidence_parser.add_argument("--min-contrast-count", type=int, default=1, help="Minimum contrast/control trials required for causal claims")
    causal_evidence_parser.add_argument("--max-unresolved-counterexamples", type=int, default=0, help="Maximum unresolved counterexamples allowed")
    causal_evidence_parser.add_argument("--no-require-bias-mitigation", action="store_true", help="Do not reject claims solely for unmitigated selection/measurement/confounder risks")
    causal_evidence_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    causal_evidence_parser.add_argument("--log-level", type=str, default="INFO")

    causal_evidence_gate_parser = subparsers.add_parser(
        "causal-evidence-gate",
        help="Gate causal evidence reports before causal-summary skill promotion",
    )
    causal_evidence_gate_parser.add_argument("--causal-evidence-report", action="append", default=[], help="Saved causal-evidence-report JSON")
    causal_evidence_gate_parser.add_argument("--target", type=str, default="causal_summary_skill_promotion", help="Gate target label")
    causal_evidence_gate_parser.add_argument("--min-approved-reports", type=int, default=1, help="Minimum approved causal evidence reports required")
    causal_evidence_gate_parser.add_argument("--min-contrast-count", type=int, default=1, help="Minimum contrast/control trials required across reports")
    causal_evidence_gate_parser.add_argument("--max-unresolved-counterexamples", type=int, default=0, help="Maximum unresolved counterexamples allowed")
    causal_evidence_gate_parser.add_argument("--max-unmitigated-bias-risks", type=int, default=0, help="Maximum unmitigated bias risks allowed")
    causal_evidence_gate_parser.add_argument("--output", type=str, default="", help="Optional JSON gate report path")
    causal_evidence_gate_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline world-model trace report
    world_model_parser = subparsers.add_parser("world-model-report", help="Build AGI-Maze-style world-state cells and exploration frontiers from session logs")
    world_model_parser.add_argument("--session-log", action="append", default=[], help="Session JSONL log to inspect")
    world_model_parser.add_argument("--cell-size", type=float, default=8.0, help="XZ block span per world-model cell")
    world_model_parser.add_argument("--limit", type=int, default=12, help="Maximum cells/frontiers/hotspots to include per case")
    world_model_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    world_model_parser.add_argument("--log-level", type=str, default="INFO")

    world_model_gate_parser = subparsers.add_parser(
        "world-model-feedback-gate",
        help="Gate world-model frontier/resource feedback before runtime curriculum loading",
    )
    world_model_gate_parser.add_argument("--world-model-report", action="append", default=[], help="Saved world-model-report JSON")
    world_model_gate_parser.add_argument("--target", type=str, default="world_model_curriculum_feedback", help="Gate target label")
    world_model_gate_parser.add_argument("--min-ready-logs", type=int, default=1, help="Minimum ready world-model logs required")
    world_model_gate_parser.add_argument("--min-frontiers", type=int, default=1, help="Minimum frontier count required")
    world_model_gate_parser.add_argument("--min-actionable-items", type=int, default=1, help="Minimum structured frontiers, hotspots, or suggested goals required")
    world_model_gate_parser.add_argument("--output", type=str, default="", help="Optional JSON gate report path")
    world_model_gate_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline self-evolution trace report
    self_evolution_parser = subparsers.add_parser("self-evolution-report", help="Report execution progress, stagnation, and adaptor hints in session logs")
    self_evolution_parser.add_argument("--session-log", action="append", default=[], help="Session JSONL log to inspect")
    self_evolution_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    self_evolution_parser.add_argument("--log-level", type=str, default="INFO")

    self_evolution_counterexample_parser = subparsers.add_parser("self-evolution-counterexample-report", help="Aggregate unresolved counterexamples before self-evolution plan repair")
    self_evolution_counterexample_parser.add_argument("--self-evolution-report", action="append", default=[], help="Saved self-evolution-report JSON")
    self_evolution_counterexample_parser.add_argument("--terminal-commitment-report", action="append", default=[], help="Saved terminal-commitment-report JSON")
    self_evolution_counterexample_parser.add_argument("--plan-action-report", action="append", default=[], help="Saved plan-action-compliance-report JSON")
    self_evolution_counterexample_parser.add_argument("--action-verification-report", action="append", default=[], help="Saved action-verification-report JSON")
    self_evolution_counterexample_parser.add_argument("--action-value-report", action="append", default=[], help="Saved action-value-report JSON")
    self_evolution_counterexample_parser.add_argument("--limit", type=int, default=120, help="Maximum counterexamples to include")
    self_evolution_counterexample_parser.add_argument("--output", type=str, default="", help="Optional JSON counterexample report path")
    self_evolution_counterexample_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline plan-action compliance trace report
    plan_action_parser = subparsers.add_parser("plan-action-compliance-report", help="Report whether executed actions follow preceding plan windows")
    plan_action_parser.add_argument("--session-log", action="append", default=[], help="Session JSONL log to inspect")
    plan_action_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    plan_action_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline plan/act latency report for Parallelized Planning-Acting evidence
    plan_act_latency_parser = subparsers.add_parser("plan-act-latency-report", help="Report planner wait, stale actions, and interrupt opportunities from Agent logs")
    plan_act_latency_parser.add_argument("--session-log", action="append", default=[], help="Session JSONL log to inspect")
    plan_act_latency_parser.add_argument("--collab-report", action="append", default=[], help="Saved collab-benchmark JSON whose role session logs should be inspected")
    plan_act_latency_parser.add_argument("--stale-plan-s", type=float, default=5.0, help="Plan age threshold before an action is counted as stale")
    plan_act_latency_parser.add_argument("--long-action-s", type=float, default=2.0, help="Action duration threshold for interrupt opportunities")
    plan_act_latency_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    plan_act_latency_parser.add_argument("--log-level", type=str, default="INFO")

    plan_act_gate_parser = subparsers.add_parser("plan-act-latency-gate", help="Gate interruptible plan/act execution with baseline/candidate latency and verifier evidence")
    plan_act_gate_parser.add_argument("--baseline-plan-act-report", action="append", default=[], help="Baseline plan-act-latency-report JSON")
    plan_act_gate_parser.add_argument("--candidate-plan-act-report", action="append", default=[], help="Candidate interruptible plan-act-latency-report JSON")
    plan_act_gate_parser.add_argument("--baseline-verifier-report", action="append", default=[], help="Baseline verifier/action/terminal report JSON")
    plan_act_gate_parser.add_argument("--candidate-verifier-report", action="append", default=[], help="Candidate verifier/action/terminal report JSON")
    plan_act_gate_parser.add_argument("--target", type=str, default="interruptible_plan_act_executor", help="Gate target label")
    plan_act_gate_parser.add_argument("--min-candidate-logs", type=int, default=1, help="Minimum candidate logs required")
    plan_act_gate_parser.add_argument("--min-stale-reduction", type=int, default=1, help="Minimum stale-plan action reduction required")
    plan_act_gate_parser.add_argument("--max-verifier-reject-delta", type=int, default=0, help="Maximum allowed increase in verifier rejections")
    plan_act_gate_parser.add_argument("--output", type=str, default="", help="Optional JSON gate report path")
    plan_act_gate_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline terminal commitment trace report
    terminal_commitment_parser = subparsers.add_parser("terminal-commitment-report", help="Report VIGIL-style world completion versus terminal completion claims")
    terminal_commitment_parser.add_argument("--session-log", action="append", default=[], help="Session JSONL log to inspect")
    terminal_commitment_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    terminal_commitment_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline action verification replay report
    action_verification_parser = subparsers.add_parser("action-verification-report", help="Replay logged actions through deterministic action verification")
    action_verification_parser.add_argument("--session-log", action="append", default=[], help="Session JSONL log to inspect")
    action_verification_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    action_verification_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline verifier-guided candidate action selection report
    action_candidate_parser = subparsers.add_parser("action-candidate-report", help="Replay logged actions through verifier-guided candidate selection")
    action_candidate_parser.add_argument("--session-log", action="append", default=[], help="Session JSONL log to inspect")
    action_candidate_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    action_candidate_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline action outcome value profile report
    action_value_parser = subparsers.add_parser("action-value-report", help="Aggregate action outcome values from session logs")
    action_value_parser.add_argument("--session-log", action="append", default=[], help="Session JSONL log to inspect")
    action_value_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    action_value_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline XENON-style knowledge correction report
    knowledge_correction_parser = subparsers.add_parser("knowledge-correction-report", help="Mine dependency and failed-action knowledge corrections from session logs")
    knowledge_correction_parser.add_argument("--session-log", action="append", default=[], help="Session JSONL log to inspect")
    knowledge_correction_parser.add_argument("--min-failure-repeats", type=int, default=2, help="Minimum repeated failed/no-progress attempts before emitting a correction candidate")
    knowledge_correction_parser.add_argument("--max-failure-value-score", type=float, default=0.35, help="Maximum action value score considered a failed-action memory")
    knowledge_correction_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    knowledge_correction_parser.add_argument("--log-level", type=str, default="INFO")

    knowledge_correction_gate_parser = subparsers.add_parser("knowledge-correction-gate", help="Gate knowledge-correction reports before planner/runtime use")
    knowledge_correction_gate_parser.add_argument("--knowledge-correction-report", action="append", default=[], help="Saved knowledge-correction-report JSON")
    knowledge_correction_gate_parser.add_argument("--target", type=str, default="planner_knowledge_correction_feedback", help="Gate target label")
    knowledge_correction_gate_parser.add_argument("--min-ready-logs", type=int, default=1, help="Minimum ready logs required")
    knowledge_correction_gate_parser.add_argument("--min-corrections", type=int, default=1, help="Minimum correction candidates required")
    knowledge_correction_gate_parser.add_argument("--output", type=str, default="", help="Optional JSON gate report path")
    knowledge_correction_gate_parser.add_argument("--log-level", type=str, default="INFO")

    knowledge_correction_review_template_parser = subparsers.add_parser("knowledge-correction-review-template", help="Generate JSONL item-level review templates for knowledge corrections")
    knowledge_correction_review_template_parser.add_argument("--knowledge-correction-report", action="append", default=[], help="Saved knowledge-correction-report JSON")
    knowledge_correction_review_template_parser.add_argument("--output", type=str, default="", help="Optional JSONL label template path")
    knowledge_correction_review_template_parser.add_argument("--log-level", type=str, default="INFO")

    knowledge_correction_review_validate_parser = subparsers.add_parser("knowledge-correction-review-validate", help="Validate item-level knowledge-correction review labels and emit approved feedback")
    knowledge_correction_review_validate_parser.add_argument("--label-file", type=str, required=True, help="Filled knowledge-correction review labels JSON/JSONL")
    knowledge_correction_review_validate_parser.add_argument("--knowledge-correction-report", action="append", default=[], help="Original knowledge-correction-report JSON for target matching")
    knowledge_correction_review_validate_parser.add_argument("--output", type=str, default="", help="Optional JSON validation report path")
    knowledge_correction_review_validate_parser.add_argument("--log-level", type=str, default="INFO")

    knowledge_correction_ablation_parser = subparsers.add_parser("knowledge-correction-ablation", help="Compare planner context with gated knowledge corrections disabled vs enabled")
    _add_knowledge_correction_args(knowledge_correction_ablation_parser)
    knowledge_correction_ablation_parser.add_argument("--suite", type=str, default="m1", choices=["m1", "m2", "all"], help="Benchmark suite used when no explicit --goal or --case-file is supplied")
    knowledge_correction_ablation_parser.add_argument("--goal", action="append", default=[], help="Goal/query to compare; repeat for multiple cases")
    knowledge_correction_ablation_parser.add_argument("--case-file", type=str, default="", help="Optional JSON/JSONL cases with goal and current_state fields")
    knowledge_correction_ablation_parser.add_argument("--current-state-json", type=str, default="", help="Optional JSON object shared by all --goal cases")
    knowledge_correction_ablation_parser.add_argument("--current-state-file", type=str, default="", help="Optional JSON file shared by all --goal cases")
    knowledge_correction_ablation_parser.add_argument("--limit", type=int, default=6, help="Maximum planner-context correction hints per case")
    knowledge_correction_ablation_parser.add_argument("--output", type=str, default="", help="Optional JSON ablation report path")
    knowledge_correction_ablation_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline action transition value runtime-readiness gate
    action_value_gate_parser = subparsers.add_parser("action-value-transition-gate", help="Gate ASV-style transition-value feedback before runtime use")
    action_value_gate_parser.add_argument("--action-value-report", action="append", default=[], help="Saved action-value-report JSON")
    action_value_gate_parser.add_argument("--target", type=str, default="action_value_transition_feedback", help="Gate target label")
    action_value_gate_parser.add_argument("--min-trusted-items", type=int, default=1, help="Minimum trusted transition signatures required")
    action_value_gate_parser.add_argument("--min-trusted-transitions", type=int, default=1, help="Minimum trusted transition attempts required")
    action_value_gate_parser.add_argument("--min-transition-confidence", type=float, default=0.75, help="Minimum average transition confidence")
    action_value_gate_parser.add_argument("--max-low-confidence-rate", type=float, default=0.25, help="Maximum overall low-confidence transition rate")
    action_value_gate_parser.add_argument("--max-item-low-confidence-rate", type=float, default=0.25, help="Maximum per-item low-confidence transition rate")
    action_value_gate_parser.add_argument("--output", type=str, default="", help="Optional JSON gate report path")
    action_value_gate_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline state-grounded evaluator comparison for action transition values
    action_value_eval_parser = subparsers.add_parser("action-value-transition-evaluator-report", help="Compare deterministic ASV transition labels against a state-grounded LLM evaluator")
    action_value_eval_parser.add_argument("--action-value-report", action="append", default=[], help="Saved action-value-report JSON")
    action_value_eval_parser.add_argument("--session-log", action="append", default=[], help="Session JSONL log to inspect directly")
    action_value_eval_parser.add_argument("--limit", type=int, default=40, help="Maximum transition windows to evaluate")
    action_value_eval_parser.add_argument("--min-transition-confidence", type=float, default=0.75, help="Minimum deterministic transition confidence")
    action_value_eval_parser.add_argument("--min-evaluator-confidence", type=float, default=0.65, help="Minimum LLM evaluator confidence")
    action_value_eval_parser.add_argument("--min-evaluated-transitions", type=int, default=1, help="Minimum evaluated transition windows required")
    action_value_eval_parser.add_argument("--min-label-agreement-rate", type=float, default=0.75, help="Minimum deterministic-vs-evaluator label agreement")
    action_value_eval_parser.add_argument("--max-avg-score-delta", type=float, default=0.25, help="Maximum average absolute score delta")
    action_value_eval_parser.add_argument("--max-large-score-delta-rate", type=float, default=0.25, help="Maximum rate of large score deltas")
    action_value_eval_parser.add_argument("--llm-evaluator", action="store_true", help="Call the configured LLM as the state-grounded evaluator")
    action_value_eval_parser.add_argument("--llm-provider", type=str, default="openai")
    action_value_eval_parser.add_argument("--llm-model", type=str, default="gpt-4o-mini")
    action_value_eval_parser.add_argument("--llm-base-url", type=str, default="")
    action_value_eval_parser.add_argument("--api-key", type=str, default="")
    action_value_eval_parser.add_argument("--output", type=str, default="", help="Optional JSON evaluator report path")
    action_value_eval_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline self-evolution automatic repair gate
    self_evolution_gate_parser = subparsers.add_parser("self-evolution-gate", help="Gate automatic self-evolution plan repair with verifier and counterexample evidence")
    self_evolution_gate_parser.add_argument("--self-evolution-report", action="append", default=[], help="Saved self-evolution-report JSON")
    self_evolution_gate_parser.add_argument("--verifier-report", action="append", default=[], help="Saved goal verifier or goal-verification-ablation JSON")
    self_evolution_gate_parser.add_argument("--counterexample-report", action="append", default=[], help="Saved counterexample JSON proving unresolved counterexamples are absent or reviewed")
    self_evolution_gate_parser.add_argument("--output", type=str, default="", help="Optional JSON gate report path")
    self_evolution_gate_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline discovery-to-application trace report
    discovery_parser = subparsers.add_parser("discovery-application-report", help="Report SciCrafter-style discovery-to-application evidence in session logs")
    discovery_parser.add_argument("--session-log", action="append", default=[], help="Session JSONL log to inspect")
    discovery_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    discovery_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline action abstraction report
    action_abstraction_parser = subparsers.add_parser("action-abstraction-report", help="Report canonical actions and backend mapping coverage in session logs")
    action_abstraction_parser.add_argument("--session-log", action="append", default=[], help="Session JSONL log to inspect")
    action_abstraction_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    action_abstraction_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline mixed-initiative task template report
    mixed_parser = subparsers.add_parser("mixed-initiative-report", help="Compile MineNPC-style task templates and optionally validate bounded evidence")
    mixed_parser.add_argument("--goal", type=str, default="Collect 20 oak logs", help="Natural-language Minecraft request")
    mixed_template_choices = [
        "auto",
        "collect_oak_logs",
        "fetch_named_tool",
        "craft_or_process_item",
        "collect_or_mine_resource",
        "build_or_place_structure",
        "unsupported_request",
    ]
    mixed_parser.add_argument("--template", type=str, default="auto", choices=mixed_template_choices, help="Template to use")
    mixed_parser.add_argument("--context-json", type=str, default="", help="Optional JSON object with slots, memory_preferences, or clarification_answers")
    mixed_parser.add_argument("--context-file", type=str, default="", help="Optional JSON file with context")
    mixed_parser.add_argument("--evidence-json", type=str, default="", help="Optional bounded evidence JSON object")
    mixed_parser.add_argument("--evidence-file", type=str, default="", help="Optional bounded evidence JSON file")
    mixed_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    mixed_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline mixed-initiative trace report
    mixed_trace_parser = subparsers.add_parser("mixed-initiative-trace-report", help="Replay session logs through MineNPC-style task validators")
    mixed_trace_parser.add_argument("--session-log", action="append", default=[], help="Session JSONL log to inspect")
    mixed_trace_parser.add_argument("--template", type=str, default="auto", choices=mixed_template_choices, help="Template to use for all goals")
    mixed_trace_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    mixed_trace_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline mixed-initiative recommendation queue
    mixed_queue_parser = subparsers.add_parser(
        "mixed-initiative-review-queue",
        help="Aggregate mixed-initiative trace recommendations into review queue items",
    )
    mixed_queue_parser.add_argument("--trace-report", action="append", default=[], help="Saved mixed-initiative trace JSON report")
    mixed_queue_parser.add_argument("--session-log", action="append", default=[], help="Session JSONL log to inspect directly")
    mixed_queue_parser.add_argument("--template", type=str, default="auto", choices=mixed_template_choices, help="Template to force for session-log inputs")
    mixed_queue_parser.add_argument("--output", type=str, default="", help="Optional JSON queue path")
    mixed_queue_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline mixed-initiative review experiment routing
    mixed_review_plan_parser = subparsers.add_parser(
        "mixed-initiative-review-plan",
        help="Route mixed-initiative review queue items into follow-up experiment cases",
    )
    mixed_review_plan_parser.add_argument("--review-queue", action="append", default=[], help="Saved mixed-initiative review queue JSON")
    mixed_review_plan_parser.add_argument("--trace-report", action="append", default=[], help="Saved mixed-initiative trace JSON report")
    mixed_review_plan_parser.add_argument("--session-log", action="append", default=[], help="Session JSONL log to inspect directly")
    mixed_review_plan_parser.add_argument("--template", type=str, default="auto", choices=mixed_template_choices, help="Template to force for session-log inputs")
    mixed_review_plan_parser.add_argument("--output", type=str, default="", help="Optional JSON experiment plan path")
    mixed_review_plan_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline mixed-initiative review approval labels
    mixed_review_label_parser = subparsers.add_parser(
        "mixed-initiative-review-label-template",
        help="Generate JSONL operator approval labels from mixed-initiative review plans",
    )
    mixed_review_label_parser.add_argument("--review-plan", action="append", default=[], help="Saved mixed-initiative review plan JSON")
    mixed_review_label_parser.add_argument("--review-queue", action="append", default=[], help="Saved mixed-initiative review queue JSON")
    mixed_review_label_parser.add_argument("--trace-report", action="append", default=[], help="Saved mixed-initiative trace JSON report")
    mixed_review_label_parser.add_argument("--session-log", action="append", default=[], help="Session JSONL log to inspect directly")
    mixed_review_label_parser.add_argument("--template", type=str, default="auto", choices=mixed_template_choices, help="Template to force for session-log inputs")
    mixed_review_label_parser.add_argument("--output", type=str, default="", help="Optional JSONL label template path")
    mixed_review_label_parser.add_argument("--log-level", type=str, default="INFO")

    mixed_review_label_validate_parser = subparsers.add_parser(
        "mixed-initiative-review-label-validate",
        help="Validate filled mixed-initiative review approval labels",
    )
    mixed_review_label_validate_parser.add_argument("--label-file", type=str, default="", help="Filled mixed-initiative review labels JSON/JSONL")
    mixed_review_label_validate_parser.add_argument("--review-plan", action="append", default=[], help="Saved mixed-initiative review plan JSON for case matching")
    mixed_review_label_validate_parser.add_argument("--output", type=str, default="", help="Optional JSON validation report path")
    mixed_review_label_validate_parser.add_argument("--log-level", type=str, default="INFO")

    mixed_review_execute_parser = subparsers.add_parser(
        "mixed-initiative-review-execute",
        help="Execute approved mixed-initiative review labels through whitelisted report builders",
    )
    mixed_review_execute_parser.add_argument("--label-file", type=str, default="", help="Filled approved mixed-initiative review labels JSON/JSONL")
    mixed_review_execute_parser.add_argument("--review-plan", action="append", default=[], help="Saved mixed-initiative review plan JSON for case matching")
    mixed_review_execute_parser.add_argument("--output-dir", type=str, default="", help="Optional directory for per-case artifact JSON")
    mixed_review_execute_parser.add_argument("--dry-run", action="store_true", help="Validate approvals and show executable cases without running reports")
    mixed_review_execute_parser.add_argument("--output", type=str, default="", help="Optional JSON execution report path")
    mixed_review_execute_parser.add_argument("--log-level", type=str, default="INFO")

    mixed_policy_patch_parser = subparsers.add_parser(
        "mixed-initiative-policy-patch",
        help="Build reusable action/template policy feedback from approved review execution artifacts",
    )
    mixed_policy_patch_parser.add_argument("--execution-report", action="append", default=[], help="Saved mixed-initiative review execution JSON")
    mixed_policy_patch_parser.add_argument("--artifact", action="append", default=[], help="Per-case artifact JSON emitted by mixed-initiative-review-execute")
    mixed_policy_patch_parser.add_argument("--output", type=str, default="", help="Optional JSON policy patch path")
    mixed_policy_patch_parser.add_argument("--log-level", type=str, default="INFO")

    mixed_policy_ablation_parser = subparsers.add_parser(
        "mixed-initiative-policy-ablation",
        help="Compare baseline vs approved mixed-initiative policy patch decisions",
    )
    mixed_policy_ablation_parser.add_argument("--policy-patch", action="append", default=[], help="Approved mixed-initiative policy patch JSON")
    mixed_policy_ablation_parser.add_argument("--action", action="append", default=[], help="Canonical action type or JSON object to compare")
    mixed_policy_ablation_parser.add_argument("--template-id", action="append", default=[], help="Template id to compare review decisions")
    mixed_policy_ablation_parser.add_argument("--candidate-id", action="append", default=[], help="Template-candidate id to compare review decisions")
    mixed_policy_ablation_parser.add_argument("--allow-planned-backend", action="store_true", help="Allow planned desktop backend decisions in the comparison")
    mixed_policy_ablation_parser.add_argument("--output", type=str, default="", help="Optional JSON ablation report path")
    mixed_policy_ablation_parser.add_argument("--log-level", type=str, default="INFO")

    mixed_policy_gate_parser = subparsers.add_parser(
        "mixed-initiative-policy-gate",
        help="Gate mixed-policy patch promotion using offline/live ablation reports",
    )
    mixed_policy_gate_parser.add_argument("--policy-ablation", action="append", default=[], help="Saved mixed-initiative-policy-ablation JSON")
    mixed_policy_gate_parser.add_argument("--benchmark-ablation", action="append", default=[], help="Saved benchmark --mixed-policy-ablation JSON")
    mixed_policy_gate_parser.add_argument("--collab-ablation", action="append", default=[], help="Saved collab-benchmark --mixed-policy-ablation JSON")
    mixed_policy_gate_parser.add_argument("--output", type=str, default="", help="Optional JSON gate report path")
    mixed_policy_gate_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline mixed-initiative held-out variant report
    mixed_variant_parser = subparsers.add_parser(
        "mixed-initiative-variant-report",
        help="Replay held-out natural-language variants through mixed-initiative templates",
    )
    mixed_variant_parser.add_argument("--case-file", action="append", default=[], help="JSON/JSONL variant case file")
    mixed_variant_parser.add_argument("--no-builtins", action="store_true", help="Skip built-in held-out variant cases")
    mixed_variant_parser.add_argument(
        "--template",
        type=str,
        default="auto",
        choices=mixed_template_choices,
        help="Template to force for all variants",
    )
    mixed_variant_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    mixed_variant_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline visual review pipeline
    visual_pipeline_parser = subparsers.add_parser("visual-review-pipeline", help="Run visual trace audit, review templates, label validation, and optional ablations")
    visual_pipeline_parser.add_argument("--session-log", action="append", default=[], help="Session JSONL log to inspect")
    visual_pipeline_parser.add_argument("--mode", type=str, default="both", choices=["promotion", "goal", "both"], help="Review mode to include")
    visual_pipeline_parser.add_argument("--label-file", type=str, default="", help="Optional filled manual labels JSON/JSONL file to validate and use")
    visual_pipeline_parser.add_argument("--run-ablations", action="store_true", help="Also run promotion/goal visual ablations after trace and label checks")
    visual_pipeline_parser.add_argument("--promotion-critic", action="store_true", help="Use configured LLM critic for promotion ablation")
    visual_pipeline_parser.add_argument("--goal-critic", action="store_true", help="Use configured LLM critic for goal-verification ablation")
    visual_pipeline_parser.add_argument("--llm-provider", type=str, default="openai")
    visual_pipeline_parser.add_argument("--llm-model", type=str, default="gpt-4o-mini")
    visual_pipeline_parser.add_argument("--llm-base-url", type=str, default="")
    visual_pipeline_parser.add_argument("--api-key", type=str, default="")
    visual_pipeline_parser.add_argument("--causal-summaries", action="store_true", help="Include repeated causal-summary promotion candidates")
    visual_pipeline_parser.add_argument("--failure-corrections", action="store_true", help="Include repeated failure-correction promotion candidates")
    visual_pipeline_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    visual_pipeline_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline reviewed policy-skill ablation
    policy_parser = subparsers.add_parser("policy-skill-ablation", help="Compare reviewed policy skills disabled vs enabled")
    policy_parser.add_argument("--skill-storage-path", type=str, default="", help="Load approved custom skills from this storage path and generate ablation cases")
    policy_parser.add_argument("--no-builtin", action="store_true", help="Skip built-in policy-skill ablation cases")
    policy_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    policy_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline visual action grounding ablation
    visual_action_parser = subparsers.add_parser("visual-action-ablation", help="Compare visual action grounding disabled vs enabled")
    visual_action_parser.add_argument("--session-log", action="append", default=[], help="Replay visual action interventions from session JSONL logs")
    visual_action_parser.add_argument("--max-cases-per-log", type=int, default=20, help="Maximum mined visual-action cases per session log; 0 means unlimited")
    visual_action_parser.add_argument("--include-builtin", action="store_true", help="Include built-in visual action cases when replaying session logs")
    visual_action_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    visual_action_parser.add_argument("--log-level", type=str, default="INFO")

    # Legacy: direct goal without subcommand
    parser.add_argument("--goal", type=str, default=None)

    args = parser.parse_args()

    log_level = getattr(args, "log_level", "INFO") or "INFO"
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    runtime_profiles = []
    runtime_profile_errors = []
    if getattr(args, "runtime_profile", []):
        runtime_profiles, runtime_profile_errors = load_runtime_profiles(getattr(args, "runtime_profile", []) or [])
        if runtime_profile_errors and args.command not in {"runtime-profile-validate", "runtime-profile-security-audit", "runtime-profile-suite-report"}:
            for error in runtime_profile_errors:
                print(f"runtime profile error: {error}")
            sys.exit(1)

    if args.command == "runtime-profile-validate":
        report = build_runtime_profile_report(getattr(args, "runtime_profile", []) or [])
        _print_runtime_profile_report(report)
        if getattr(args, "output", ""):
            output_dir = os.path.dirname(args.output)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        if report.get("readiness") in {"error", "rejected"}:
            sys.exit(1)
        return

    if args.command == "runtime-profile-security-audit":
        report = build_runtime_profile_security_audit(
            getattr(args, "runtime_profile", []) or [],
            include_gates=getattr(args, "include_gates", False),
            max_scan_bytes=getattr(args, "max_scan_bytes", DEFAULT_SECURITY_SCAN_BYTES),
            max_findings=getattr(args, "max_findings", 50),
        )
        _print_runtime_profile_security_audit(report)
        if getattr(args, "output", ""):
            output_dir = os.path.dirname(args.output)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        if report.get("readiness") in {"error", "rejected"}:
            sys.exit(1)
        return

    if args.command == "runtime-profile-suite-report":
        report = build_runtime_profile_suite_report(
            profile_paths=getattr(args, "runtime_profile", []) or [],
            runtime_dir=getattr(args, "runtime_dir", "") or "",
            required_profiles=getattr(args, "required_profile", []) or [],
            include_gates=getattr(args, "include_gates", False),
            max_scan_bytes=getattr(args, "max_scan_bytes", DEFAULT_SECURITY_SCAN_BYTES),
            max_findings=getattr(args, "max_findings", 50),
        )
        _print_runtime_profile_suite_report(report)
        if getattr(args, "output", ""):
            output_dir = os.path.dirname(args.output)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        if report.get("readiness") in {"error", "rejected"}:
            sys.exit(1)
        return

    if args.command == "runtime-profile-build":
        payload = _runtime_profile_payload_from_args(args)
        profile_label = getattr(args, "output", "") or f"inline:{payload.get('name', 'runtime_profile')}"
        report = build_runtime_profile_report_from_profiles([payload], profile_paths=[profile_label])
        security_report = build_runtime_profile_security_audit_from_profiles([payload], profile_paths=[profile_label])
        if (
            getattr(args, "output", "")
            and report.get("readiness") not in {"error", "rejected"}
            and security_report.get("readiness") not in {"error", "rejected"}
        ):
            output_dir = os.path.dirname(args.output)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            print(f"Runtime profile saved to {args.output}")
        elif not getattr(args, "output", ""):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            print("Runtime profile not saved because validation or security audit did not approve it")
        _print_runtime_profile_report(report)
        _print_runtime_profile_security_audit(security_report)
        if report.get("readiness") in {"error", "rejected"} or security_report.get("readiness") in {"error", "rejected"}:
            sys.exit(1)
        return

    if runtime_profiles:
        security_report = build_runtime_profile_security_audit_from_profiles(
            runtime_profiles,
            profile_paths=getattr(args, "runtime_profile", []) or [],
            load_errors=runtime_profile_errors,
        )
        if security_report.get("readiness") in {"error", "rejected"}:
            _print_runtime_profile_security_audit(security_report)
            sys.exit(1)

    # Handle skills command (no server needed)
    if args.command == "skills":
        from singularity.core.skill_library import SkillLibrary
        lib = SkillLibrary(persist=True)
        print(f"\nSingularity Skill Library ({len(lib.skills)} skills)\n")
        for layer in ("primitive", "composite", "strategic"):
            skills = lib.list_skills(layer)
            if skills:
                print(f"  [{layer.upper()}]")
                for s in skills:
                    uses = f" ({s.total_uses} uses, {s.success_rate:.0%} success)" if s.total_uses > 0 else ""
                    print(f"    - {s.name}: {s.description}{uses}")
        return

    if args.command == "skill-graph-report":
        from singularity.core.skill_library import SkillLibrary

        lib = SkillLibrary(storage_path=getattr(args, "skill_storage_path", "workspace/skills"), persist=True)
        report = lib.skill_graph_report()
        print("\nSkill Graph Governance")
        print(f"  skills: {report['skill_count']} ({report['custom_skill_count']} custom)")
        print(f"  edges: {report['edge_count']}")
        print(f"  missing dependencies: {report['missing_dependency_count']}")
        print(f"  ungoverned custom skills: {report['ungoverned_custom_skill_count']}")
        print(f"  missing postconditions: {report['missing_postcondition_count']}")
        print(f"  cycles: {report['cycle_count']}")
        if report["issue_counts"]:
            parts = [f"{key}={value}" for key, value in sorted(report["issue_counts"].items())]
            print(f"  issues: {', '.join(parts)}")
        for node in report["nodes"]:
            if node["built_in"] and not node["issues"]:
                continue
            marker = "!" if node["issues"] else "+"
            governance = node["governance"]
            print(
                f"  [{marker}] {node['name']} layer={node['layer']} "
                f"gate={governance['gate_readiness']} deps={len(node['dependencies'])}"
            )
            if node["issues"]:
                print(f"      issues: {', '.join(node['issues'])}")
            if node["missing_dependencies"]:
                print(f"      missing deps: {', '.join(node['missing_dependencies'])}")
        if getattr(args, "output", ""):
            output_dir = os.path.dirname(args.output)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "skill-contract-report":
        from singularity.core.skill_library import SkillLibrary

        world_state = {}
        if getattr(args, "world_state_file", ""):
            with open(args.world_state_file, "r", encoding="utf-8-sig") as f:
                world_state = json.load(f)
        elif getattr(args, "world_state_json", ""):
            try:
                world_state = json.loads(args.world_state_json)
            except json.JSONDecodeError as exc:
                print(f"skill-contract-report could not parse --world-state-json: {exc}")
                sys.exit(1)
        if not isinstance(world_state, dict):
            print("skill-contract-report world state must be a JSON object")
            sys.exit(1)

        lib = SkillLibrary(storage_path=getattr(args, "skill_storage_path", "workspace/skills"), persist=True)
        report = lib.skill_contract_report(
            goal=getattr(args, "goal", ""),
            world_state=world_state,
            limit=getattr(args, "limit", 20),
        )
        print("\nSkill Contract Report")
        print(f"  goal: {report['goal']}")
        print(
            f"  skills: {report['skill_count']}, matched: {report['matched_count']}, "
            f"ready/review/blocked: {report['ready_count']}/{report['review_count']}/{report['blocked_count']}"
        )
        if report["issue_counts"]:
            parts = [f"{key}={value}" for key, value in sorted(report["issue_counts"].items())]
            print(f"  issues: {', '.join(parts)}")
        for match in report["matches"][:getattr(args, "limit", 20)]:
            if match["score"] <= 0 and match["readiness"] == "ready":
                continue
            issues = f" issues={','.join(match['issues'])}" if match["issues"] else ""
            print(
                f"  - {match['name']} score={match['score']:.2f} "
                f"readiness={match['readiness']}{issues}"
            )
            if match["goal_matches"] or match["postcondition_matches"]:
                terms = sorted(set(match["goal_matches"] + match["postcondition_matches"]))
                print(f"      matches: {', '.join(terms[:8])}")
            if match["missing_preconditions"] or match["missing_required_items"] or match["missing_dependencies"]:
                missing = match["missing_preconditions"] + match["missing_required_items"] + match["missing_dependencies"]
                print(f"      missing: {', '.join(str(item) for item in missing[:8])}")
        if getattr(args, "output", ""):
            output_dir = os.path.dirname(args.output)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "skill-memory-report":
        from singularity.core.skill_library import SkillLibrary

        lib = SkillLibrary(storage_path=getattr(args, "skill_storage_path", "workspace/skills"), persist=True)
        report = lib.skill_memory_report(
            goal=getattr(args, "goal", ""),
            task_family=getattr(args, "task_family", ""),
            include_builtins=getattr(args, "include_builtins", False),
            limit=getattr(args, "limit", 20),
        )
        print("\nSkill Memory Report")
        if report["goal"]:
            print(f"  goal: {report['goal']}")
        if report["task_family"]:
            print(f"  task family: {report['task_family']}")
        print(
            f"  skills: {report['skill_count']}, with memory: {report['skills_with_memory_count']}, "
            f"memories: {report['memory_count']}"
        )
        print(
            f"  success/failure memories: {report['success_memory_count']}/{report['failure_memory_count']}, "
            f"approved/review transfer memories: "
            f"{report['approved_transfer_memory_count']}/{report['review_transfer_memory_count']}"
        )
        if report["issue_counts"]:
            parts = [f"{key}={value}" for key, value in sorted(report["issue_counts"].items())]
            print(f"  issues: {', '.join(parts)}")
        if report["task_family_counts"]:
            parts = [f"{key}={value}" for key, value in sorted(report["task_family_counts"].items())]
            print(f"  task families: {', '.join(parts)}")
        for skill in report["skills"][:getattr(args, "limit", 20)]:
            if skill["built_in"] and not skill["memory_count"] and not getattr(args, "include_builtins", False):
                continue
            issues = f" issues={','.join(skill['issues'])}" if skill["issues"] else ""
            print(
                f"  - {skill['name']} memories={skill['memory_count']} "
                f"success/failure={skill['success_memory_count']}/{skill['failure_memory_count']} "
                f"gate={skill['gate_readiness']} contract={skill['contract_readiness']}{issues}"
            )
            for memory in skill["memories"][-2:]:
                label = memory.get("task_family") or memory.get("type") or "memory"
                note = memory.get("note", "")
                if note:
                    print(f"      {label}: {note[:120]}")
        if getattr(args, "output", ""):
            output_dir = os.path.dirname(args.output)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "skill-lifecycle-report":
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        runner = BenchmarkRunner(Config(skill_dir=getattr(args, "skill_storage_path", "workspace/skills")))
        report = runner.run_skill_lifecycle_report(
            skill_storage_path=getattr(args, "skill_storage_path", "workspace/skills"),
            goal=getattr(args, "goal", ""),
            task_family=getattr(args, "task_family", ""),
            include_builtins=getattr(args, "include_builtins", False),
            limit=getattr(args, "limit", 20),
        )
        runner.print_skill_lifecycle_report(report)
        if getattr(args, "output", ""):
            runner.save_skill_lifecycle_report(report, getattr(args, "output", ""))
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "skill-runtime-default-gate":
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        lifecycle_reports = getattr(args, "skill_lifecycle_report", []) or []
        transfer_gates = getattr(args, "task_stream_transfer_gate", []) or []
        if not lifecycle_reports:
            print("skill-runtime-default-gate requires at least one --skill-lifecycle-report")
            sys.exit(1)
        if not transfer_gates:
            print("skill-runtime-default-gate requires at least one --task-stream-transfer-gate")
            sys.exit(1)
        runner = BenchmarkRunner(Config())
        report = runner.build_skill_runtime_default_gate(
            lifecycle_report_paths=lifecycle_reports,
            transfer_gate_paths=transfer_gates,
            quality_gate_paths=getattr(args, "skill_memory_quality_gate", []) or [],
            target_task_family=getattr(args, "target_task_family", ""),
            require_quality_gate=getattr(args, "require_skill_memory_quality_gate", False),
            min_runtime_candidates=getattr(args, "min_runtime_candidates", 1),
        )
        runner.print_skill_runtime_default_gate_report(report)
        if getattr(args, "output", ""):
            runner.save_skill_runtime_default_gate_report(report, getattr(args, "output", ""))
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "skill-memory-quality-report":
        from dataclasses import asdict
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        session_logs = getattr(args, "session_log", []) or []
        if not session_logs:
            print("skill-memory-quality-report requires at least one --session-log")
            sys.exit(1)
        runner = BenchmarkRunner(Config())
        report = runner.run_skill_memory_quality_report_from_logs(session_logs)
        runner.print_skill_memory_quality_report(report)
        quality_feedback = runner.skill_memory_quality_feedback(report)
        if getattr(args, "output", ""):
            output_dir = os.path.dirname(args.output)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump({
                    "log_count": report.log_count,
                    "ready_log_count": report.ready_log_count,
                    "hint_event_count": report.hint_event_count,
                    "hint_count": report.hint_count,
                    "hint_type_counts": report.hint_type_counts,
                    "task_family_counts": report.task_family_counts,
                    "post_hint_failed_action_count": report.post_hint_failed_action_count,
                    "post_hint_goal_success_count": report.post_hint_goal_success_count,
                    "post_hint_goal_failure_count": report.post_hint_goal_failure_count,
                    "repeated_post_hint_failure_count": report.repeated_post_hint_failure_count,
                    "quality_label_counts": report.quality_label_counts,
                    "hint_quality_items": report.hint_quality_items,
                    "skill_memory_quality_feedback": quality_feedback,
                    "errors": report.errors,
                    "cases": [asdict(case) for case in report.cases],
                }, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "skill-memory-quality-ablation":
        from singularity.core.skill_library import SkillLibrary

        feedback_paths = getattr(args, "quality_feedback", []) or []
        if not feedback_paths:
            print("skill-memory-quality-ablation requires at least one --quality-feedback")
            sys.exit(1)
        cases = _load_skill_memory_quality_ablation_cases(args)
        if not cases:
            print("skill-memory-quality-ablation requires --goal or --case-file")
            sys.exit(1)
        feedback = _merge_skill_memory_quality_feedback_paths(feedback_paths)
        lib = SkillLibrary(storage_path=getattr(args, "skill_storage_path", "workspace/skills"), persist=True)
        report = lib.skill_memory_quality_ablation(
            feedback,
            cases=cases,
            limit=getattr(args, "limit", 5),
        )
        report["quality_feedback_paths"] = list(feedback_paths)

        print("\nSkill Memory Quality Ablation")
        print(
            f"  cases: {report['case_count']}, changed: {report['changed_count']}, "
            f"promoted: {report['promoted_count']}, demoted: {report['demoted_count']}, "
            f"quality applications: {report['quality_policy_application_count']}"
        )
        for case in report["cases"]:
            marker = "+" if case["changed"] else "~"
            print(f"  [{marker}] {case['id']}: {case['goal']} ({case['task_family'] or 'any'})")
            if case["promoted"]:
                print("      promoted: " + ", ".join(f"{item['skill']}#{item['adjusted_rank']}" for item in case["promoted"][:4]))
            if case["demoted"]:
                print("      demoted: " + ", ".join(f"{item['skill']}#{item['baseline_rank']}->{item['adjusted_rank']}" for item in case["demoted"][:4]))
            for item in case["adjusted_hints"][:min(3, getattr(args, "limit", 5))]:
                quality = ",".join(item.get("quality_policies", [])) or "none"
                print(f"      adjusted {item['rank']}: {item['hint_type']} {item['skill']} quality={quality}")
        if getattr(args, "output", ""):
            output_dir = os.path.dirname(args.output)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "skill-memory-quality-gate":
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        memory_reports = getattr(args, "skill_memory_report", []) or []
        feedback_paths = getattr(args, "quality_feedback", []) or []
        if not memory_reports:
            print("skill-memory-quality-gate requires at least one --skill-memory-report")
            sys.exit(1)
        if not feedback_paths:
            print("skill-memory-quality-gate requires at least one --quality-feedback")
            sys.exit(1)
        runner = BenchmarkRunner(Config())
        report = runner.build_skill_memory_quality_gate(
            memory_report_paths=memory_reports,
            quality_feedback_paths=feedback_paths,
            target=getattr(args, "target", "skill_memory_reuse_promotion"),
            min_supported_reuse=getattr(args, "min_supported_reuse", 2),
            max_conflicting_reuse=getattr(args, "max_conflicting_reuse", 0),
        )
        runner.print_skill_memory_quality_gate_report(report)
        if getattr(args, "output", ""):
            output_dir = os.path.dirname(args.output)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "memory-consolidation-report":
        from singularity.core.memory import MemorySystem

        memory = MemorySystem(memory_dir=getattr(args, "memory_dir", "workspace/memory"))
        candidates = memory.memory_consolidation_candidates(
            min_score=getattr(args, "min_score", 0.65),
            min_recall_count=getattr(args, "min_recall_count", 2),
            min_unique_queries=getattr(args, "min_unique_queries", 2),
            limit=getattr(args, "limit", 20),
        )
        report = {
            "memory_dir": getattr(args, "memory_dir", "workspace/memory"),
            "candidate_count": len(candidates),
            "min_score": getattr(args, "min_score", 0.65),
            "min_recall_count": getattr(args, "min_recall_count", 2),
            "min_unique_queries": getattr(args, "min_unique_queries", 2),
            "candidates": candidates,
        }
        print("\nMemory Consolidation Report")
        print(f"  candidates: {len(candidates)}")
        for candidate in candidates:
            label = candidate.get("content") or f"{candidate.get('task')} -> {candidate.get('outcome')}"
            print(
                f"  - {candidate['kind']} {candidate['id']} "
                f"score={candidate['score']:.2f} "
                f"recalls={candidate['recall_count']} "
                f"queries={candidate['unique_query_count']}: {label[:120]}"
            )
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            print(f"  saved: {args.output}")
        return

    if args.command == "memory-maintenance-report":
        from singularity.core.memory import MemorySystem

        current_state = {}
        if getattr(args, "current_state_file", ""):
            with open(args.current_state_file, "r", encoding="utf-8-sig") as f:
                current_state = json.load(f)
        elif getattr(args, "current_state_json", ""):
            current_state = json.loads(args.current_state_json)
        if not isinstance(current_state, dict):
            print("memory-maintenance-report current state must be a JSON object")
            sys.exit(1)

        memory = MemorySystem(memory_dir=getattr(args, "memory_dir", "workspace/memory"))
        report = memory.memory_maintenance_report(
            query=getattr(args, "query", ""),
            current_state=current_state,
            attribution_gate_paths=getattr(args, "memory_attribution_gate", []) or [],
            min_consolidation_score=getattr(args, "min_consolidation_score", 0.65),
            min_recall_count=getattr(args, "min_recall_count", 2),
            min_unique_queries=getattr(args, "min_unique_queries", 2),
            limit=getattr(args, "limit", 80),
        )
        print("\nMemory Maintenance Report")
        print(f"  candidates: {report.get('candidate_count', 0)}/{report.get('total_candidate_count', 0)}")
        if report.get("operation_counts"):
            parts = [f"{key}={value}" for key, value in sorted(report.get("operation_counts", {}).items())]
            print(f"  operations: {', '.join(parts)}")
        if report.get("recommended_skill_counts"):
            parts = [f"{key}={value}" for key, value in sorted(report.get("recommended_skill_counts", {}).items())]
            print(f"  skills: {', '.join(parts)}")
        if report.get("policy_hints"):
            print(f"  policy hints: {', '.join(report.get('policy_hints', []))}")
        for candidate in report.get("candidates", [])[:10]:
            print(
                f"  - {candidate.get('priority', 'review')} "
                f"{candidate.get('operation', 'unknown')} "
                f"{candidate.get('memory_id', '')} "
                f"skill={candidate.get('recommended_skill', 'unknown')} "
                f"score={float(candidate.get('score') or 0.0):.2f}"
            )
        if getattr(args, "output", ""):
            output_dir = os.path.dirname(args.output)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            print(f"  saved: {args.output}")
        return

    if args.command == "transfer-memory-report":
        from singularity.core.memory import MemorySystem

        current_state = {}
        if getattr(args, "current_state_file", ""):
            with open(args.current_state_file, "r", encoding="utf-8-sig") as f:
                current_state = json.load(f)
        elif getattr(args, "current_state_json", ""):
            current_state = json.loads(args.current_state_json)
        if not isinstance(current_state, dict):
            print("transfer-memory-report current state must be a JSON object")
            sys.exit(1)

        memory = MemorySystem(memory_dir=getattr(args, "memory_dir", "workspace/memory"))
        report = memory.transfer_memory_report(
            getattr(args, "query", ""),
            current_state=current_state,
            limit=getattr(args, "limit", 10),
            min_score=getattr(args, "min_score", 0.1),
        )
        print("\nTransfer Memory Report")
        print(f"  query: {report['query']}")
        print(f"  experiences: {report['experience_count']}, matches: {report['match_count']}")
        if report["axis_counts"]:
            parts = [f"{axis}={count}" for axis, count in sorted(report["axis_counts"].items())]
            print(f"  axes: {', '.join(parts)}")
        for match in report["matches"]:
            axes = ",".join(match.get("matched_axes", [])) or "text"
            print(
                f"  - {match['id']} score={match['score']:.2f} "
                f"axes={axes}: {match['task']} -> {match['outcome']}"
            )
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            print(f"  saved: {args.output}")
        return

    if args.command == "task-memory-report":
        from singularity.core.memory import MemorySystem

        current_state = {}
        if getattr(args, "current_state_file", ""):
            with open(args.current_state_file, "r", encoding="utf-8-sig") as f:
                current_state = json.load(f)
        elif getattr(args, "current_state_json", ""):
            current_state = json.loads(args.current_state_json)
        if not isinstance(current_state, dict):
            print("task-memory-report current state must be a JSON object")
            sys.exit(1)

        task = {}
        if getattr(args, "task_file", ""):
            with open(args.task_file, "r", encoding="utf-8-sig") as f:
                task = json.load(f)
        elif getattr(args, "task_json", ""):
            task = json.loads(args.task_json)
        if task and not isinstance(task, dict):
            print("task-memory-report task must be a JSON object")
            sys.exit(1)

        memory = MemorySystem(memory_dir=getattr(args, "memory_dir", "workspace/memory"))
        report = memory.task_memory_profile(
            getattr(args, "goal", ""),
            task=task,
            current_state=current_state,
            limit=getattr(args, "limit", 5),
            min_score=getattr(args, "min_score", 0.1),
        )
        print("\nTask Memory Report")
        print(f"  goal: {report['goal']}")
        if report["task"].get("title"):
            print(f"  task: {report['task'].get('title')}")
        print(f"  scoped memories: {report['memory_match_count']}, transfer matches: {report['transfer_match_count']}")
        if report["axis_counts"]:
            parts = [f"{axis}={count}" for axis, count in sorted(report["axis_counts"].items())]
            print(f"  transfer axes: {', '.join(parts)}")
        for memory_match in report["memory_matches"][:getattr(args, "limit", 5)]:
            print(f"  - memory {memory_match['id']} score={memory_match['score']:.2f}: {memory_match['content'][:120]}")
        for transfer in report["transfer_matches"][:getattr(args, "limit", 5)]:
            axes = ",".join(transfer.get("matched_axes", [])) or "text"
            print(
                f"  - transfer {transfer['id']} score={transfer['score']:.2f} "
                f"axes={axes}: {transfer['task']} -> {transfer['outcome']}"
            )
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            print(f"  saved: {args.output}")
        return

    if args.command == "task-continuity-report":
        from singularity.core.memory import MemorySystem

        current_state = {}
        if getattr(args, "current_state_file", ""):
            with open(args.current_state_file, "r", encoding="utf-8-sig") as f:
                current_state = json.load(f)
        elif getattr(args, "current_state_json", ""):
            current_state = json.loads(args.current_state_json)
        if not isinstance(current_state, dict):
            print("task-continuity-report current state must be a JSON object")
            sys.exit(1)

        memory = MemorySystem(memory_dir=getattr(args, "memory_dir", "workspace/memory"))
        report = memory.task_continuity_report(
            goal=getattr(args, "goal", ""),
            current_state=current_state,
            limit=getattr(args, "limit", 10),
        )
        print("\nTask Continuity Report")
        if report.get("goal"):
            print(f"  goal: {report.get('goal')}")
        print(
            f"  readiness: {report.get('readiness')} "
            f"decision={report.get('decision')}"
        )
        print(
            f"  records: {report.get('record_count', 0)}/{report.get('total_record_count', 0)}, "
            f"unresolved={report.get('unresolved_task_count', 0)}, "
            f"ready/blocked/failed="
            f"{report.get('ready_task_count', 0)}/"
            f"{report.get('blocked_task_count', 0)}/"
            f"{report.get('failed_task_count', 0)}"
        )
        if report.get("missing_precondition_counts"):
            parts = [
                f"{key}={value}"
                for key, value in sorted(report.get("missing_precondition_counts", {}).items())
            ]
            print(f"  missing preconditions: {', '.join(parts[:8])}")
        if report.get("blocker_counts"):
            parts = [f"{key}={value}" for key, value in sorted(report.get("blocker_counts", {}).items())]
            print(f"  blockers: {', '.join(parts[:6])}")
        if report.get("policy_hints"):
            print(f"  policy hints: {', '.join(report.get('policy_hints', [])[:6])}")
        for candidate in report.get("resume_candidates", [])[:8]:
            suffix = ""
            if candidate.get("missing_preconditions"):
                suffix = f" missing={json.dumps(candidate.get('missing_preconditions'), ensure_ascii=False)[:120]}"
            elif candidate.get("blockers"):
                suffix = f" blockers={'; '.join(str(item) for item in candidate.get('blockers', [])[:2])[:120]}"
            print(
                f"  - {candidate.get('status_bucket')} "
                f"{candidate.get('title')} "
                f"priority={candidate.get('priority')} from={candidate.get('checkpoint_id')}{suffix}"
            )
        for action in report.get("next_actions", [])[:6]:
            print(f"  next: {action}")
        if getattr(args, "output", ""):
            output_dir = os.path.dirname(args.output)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            print(f"  saved: {args.output}")
        return

    if args.command == "task-continuity-import":
        from singularity.core.memory import MemorySystem

        session_logs = getattr(args, "session_log", []) or []
        if not session_logs:
            print("task-continuity-import requires at least one --session-log")
            sys.exit(1)
        memory = MemorySystem(memory_dir=getattr(args, "memory_dir", "workspace/memory"))
        imports = [
            memory.import_task_continuity_from_session_log(path, source=getattr(args, "source", "session_import"))
            for path in session_logs
        ]
        imported_count = sum(1 for item in imports if item.get("imported"))
        failed_count = len(imports) - imported_count
        report = {
            "type": "task_continuity_import_report",
            "memory_dir": getattr(args, "memory_dir", "workspace/memory"),
            "session_log_count": len(session_logs),
            "imported_count": imported_count,
            "failed_count": failed_count,
            "imports": imports,
        }
        print("\nTask Continuity Import")
        print(
            f"  logs: {len(session_logs)}, imported={imported_count}, "
            f"failed={failed_count}"
        )
        for item in imports[:12]:
            marker = "+" if item.get("imported") else "!"
            if item.get("imported"):
                record = item.get("record", {}) if isinstance(item.get("record", {}), dict) else {}
                print(
                    f"  [{marker}] {item.get('source_log')}: "
                    f"{record.get('id')} goal={record.get('goal', '')[:80]} "
                    f"ready/blocked/failed="
                    f"{item.get('ready_task_count', 0)}/"
                    f"{item.get('blocked_task_count', 0)}/"
                    f"{item.get('failed_task_count', 0)}"
                )
                for action in item.get("next_actions", [])[:3]:
                    print(f"      next: {action}")
            else:
                print(f"  [{marker}] {item.get('source_log')}: {item.get('reason') or item.get('error')}")
        if getattr(args, "output", ""):
            output_dir = os.path.dirname(args.output)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            print(f"  saved: {args.output}")
        return

    if args.command == "memory-policy-report":
        from dataclasses import asdict
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        session_logs = getattr(args, "session_log", []) or []
        if not session_logs:
            print("memory-policy-report requires at least one --session-log")
            sys.exit(1)
        runner = BenchmarkRunner(Config())
        report = runner.run_memory_policy_report_from_logs(session_logs)
        runner.print_memory_policy_report(report)
        memory_policy_feedback = runner.memory_policy_feedback(report)
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump({
                    "log_count": report.log_count,
                    "ready_log_count": report.ready_log_count,
                    "event_count": report.event_count,
                    "explicit_memory_write_count": report.explicit_memory_write_count,
                    "explicit_memory_read_count": report.explicit_memory_read_count,
                    "explicit_memory_manage_count": report.explicit_memory_manage_count,
                    "semantic_write_candidate_count": report.semantic_write_candidate_count,
                    "missed_semantic_write_count": report.missed_semantic_write_count,
                    "failure_learning_candidate_count": report.failure_learning_candidate_count,
                    "consolidation_signal_count": report.consolidation_signal_count,
                    "noisy_write_candidate_count": report.noisy_write_candidate_count,
                    "missing_read_trace_count": report.missing_read_trace_count,
                    "read_filter_event_count": report.read_filter_event_count,
                    "read_filtered_entry_count": report.read_filtered_entry_count,
                    "read_filter_reasons": report.read_filter_reasons,
                    "memory_policy_feedback": memory_policy_feedback,
                    "errors": report.errors,
                    "cases": [asdict(case) for case in report.cases],
                }, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "memory-attribution-report":
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        session_logs = getattr(args, "session_log", []) or []
        if not session_logs:
            print("memory-attribution-report requires at least one --session-log")
            sys.exit(1)
        runner = BenchmarkRunner(Config())
        report = runner.run_memory_attribution_report_from_logs(
            session_logs,
            attribution_window_events=getattr(args, "attribution_window_events", 16),
        )
        runner.print_memory_attribution_report(report)
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "memory-attribution-gate":
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        runner = BenchmarkRunner(Config())
        report = runner.build_memory_attribution_gate(
            memory_attribution_report_paths=getattr(args, "memory_attribution_report", []) or [],
            target=getattr(args, "target", "weighted_memory_retrieval"),
            min_ready_logs=getattr(args, "min_ready_logs", 1),
            min_attributed_reads=getattr(args, "min_attributed_reads", 1),
            min_supported_reads=getattr(args, "min_supported_reads", 1),
            min_attributed_read_rate=getattr(args, "min_attributed_read_rate", 0.5),
            max_conflicting_read_rate=getattr(args, "max_conflicting_read_rate", 0.0),
            max_no_result_read_rate=getattr(args, "max_no_result_read_rate", 0.2),
        )
        runner.print_memory_attribution_gate_report(report)
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        if report.get("readiness") != "approved":
            sys.exit(2)
        return

    if args.command == "task-precondition-report":
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        session_logs = getattr(args, "session_log", []) or []
        if not session_logs:
            print("task-precondition-report requires at least one --session-log")
            sys.exit(1)
        runner = BenchmarkRunner(Config())
        report = runner.run_task_precondition_report_from_logs(
            session_logs,
            min_evidence_count=getattr(args, "min_evidence_count", 1),
        )
        print("\nTask Precondition Report")
        print(
            "  logs: "
            f"{report.get('ready_log_count', 0)}/{report.get('log_count', 0)}, "
            f"candidates={report.get('candidate_count', 0)}, "
            f"failed_actions={report.get('failed_action_count', 0)}, "
            f"blocked={report.get('blocked_plan_count', 0)}, "
            f"empty={report.get('empty_plan_count', 0)}"
        )
        if report.get("candidate_type_counts"):
            parts = [f"{key}={value}" for key, value in sorted(report.get("candidate_type_counts", {}).items())]
            print(f"  candidate types: {', '.join(parts)}")
        if report.get("policy_hints"):
            hints = [
                f"{hint.get('task_precondition_policy', 'unknown')}({hint.get('priority', 'review')})"
                for hint in report.get("policy_hints", [])[:6]
            ]
            print(f"  policy hints: {', '.join(hints)}")
        for candidate in report.get("candidates", [])[:8]:
            print(
                f"  - {candidate.get('candidate_type', 'unknown')} "
                f"{candidate.get('action_signature', '')} "
                f"evidence={candidate.get('evidence_count', 0)} "
                f"confidence={float(candidate.get('confidence') or 0.0):.2f}: "
                f"{candidate.get('recommendation', '')}"
            )
        if getattr(args, "output", ""):
            output_dir = os.path.dirname(args.output)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "task-precondition-gate":
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        report_paths = getattr(args, "task_precondition_report", []) or []
        if not report_paths:
            print("task-precondition-gate requires at least one --task-precondition-report")
            sys.exit(1)
        runner = BenchmarkRunner(Config())
        report = runner.build_task_precondition_gate(
            task_precondition_report_paths=report_paths,
            target=getattr(args, "target", "planner_task_precondition_feedback"),
            min_ready_logs=getattr(args, "min_ready_logs", 1),
            min_candidates=getattr(args, "min_candidates", 1),
            min_high_confidence_candidates=getattr(args, "min_high_confidence_candidates", 0),
            min_confidence=getattr(args, "min_confidence", 0.55),
        )
        runner.print_task_precondition_gate_report(report)
        if getattr(args, "output", ""):
            output_dir = os.path.dirname(args.output)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        if report.get("readiness") != "approved":
            sys.exit(2)
        return

    if args.command == "bounded-context-report":
        from dataclasses import asdict
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        session_logs = getattr(args, "session_log", []) or []
        if not session_logs:
            print("bounded-context-report requires at least one --session-log")
            sys.exit(1)
        runner = BenchmarkRunner(Config())
        report = runner.run_bounded_context_report_from_logs(
            session_logs,
            max_read_chars=getattr(args, "max_read_chars", 1200),
            max_cycle_chars=getattr(args, "max_cycle_chars", 2400),
        )
        runner.print_bounded_context_report(report)
        bounded_context_feedback = runner.bounded_context_feedback(report)
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump({
                    "log_count": report.log_count,
                    "ready_log_count": report.ready_log_count,
                    "planning_cycle_count": report.planning_cycle_count,
                    "bounded_cycle_count": report.bounded_cycle_count,
                    "unbounded_cycle_count": report.unbounded_cycle_count,
                    "missing_read_cycle_count": report.missing_read_cycle_count,
                    "oversized_read_cycle_count": report.oversized_read_cycle_count,
                    "oversized_cycle_count": report.oversized_cycle_count,
                    "raw_context_cycle_count": report.raw_context_cycle_count,
                    "low_diversity_cycle_count": report.low_diversity_cycle_count,
                    "max_read_chars": report.max_read_chars,
                    "max_cycle_chars": report.max_cycle_chars,
                    "read_layers": report.read_layers,
                    "read_types": report.read_types,
                    "bounded_context_feedback": bounded_context_feedback,
                    "errors": report.errors,
                    "cases": [asdict(case) for case in report.cases],
                }, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "bounded-context-gate":
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        runner = BenchmarkRunner(Config())
        report = runner.build_bounded_context_gate(
            bounded_context_report_paths=getattr(args, "bounded_context_report", []) or [],
            target=getattr(args, "target", "planner_context_contract"),
            min_ready_logs=getattr(args, "min_ready_logs", 1),
            min_bounded_cycle_rate=getattr(args, "min_bounded_cycle_rate", 1.0),
            max_unbounded_cycles=getattr(args, "max_unbounded_cycles", 0),
            max_missing_read_cycles=getattr(args, "max_missing_read_cycles", 0),
            max_oversized_read_cycles=getattr(args, "max_oversized_read_cycles", 0),
            max_oversized_cycles=getattr(args, "max_oversized_cycles", 0),
            max_raw_context_cycles=getattr(args, "max_raw_context_cycles", 0),
            max_low_diversity_cycles=getattr(args, "max_low_diversity_cycles", 0),
        )
        runner.print_bounded_context_gate_report(report)
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        if report.get("readiness") != "approved":
            sys.exit(2)
        return

    if args.command == "continual-learning-report":
        from dataclasses import asdict
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        session_logs = getattr(args, "session_log", []) or []
        if not session_logs:
            print("continual-learning-report requires at least one --session-log")
            sys.exit(1)
        runner = BenchmarkRunner(Config())
        report = runner.run_continual_learning_report_from_logs(
            session_logs,
            cell_size=getattr(args, "cell_size", 8.0),
            max_read_chars=getattr(args, "max_read_chars", 1200),
            max_cycle_chars=getattr(args, "max_cycle_chars", 2400),
        )
        runner.print_continual_learning_report(report)
        continual_learning_feedback = runner.continual_learning_feedback(report)
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump({
                    "type": "continual_learning_report",
                    "schema_version": 1,
                    "log_count": report.log_count,
                    "ready_log_count": report.ready_log_count,
                    "event_count": report.event_count,
                    "observation_count": report.observation_count,
                    "action_count": report.action_count,
                    "failed_action_count": report.failed_action_count,
                    "completed_goal_count": report.completed_goal_count,
                    "failed_goal_count": report.failed_goal_count,
                    "progress_event_count": report.progress_event_count,
                    "object_exploration_count": report.object_exploration_count,
                    "memory_read_count": report.memory_read_count,
                    "memory_write_count": report.memory_write_count,
                    "unbounded_context_cycle_count": report.unbounded_context_cycle_count,
                    "average_axis_scores": report.average_axis_scores,
                    "continual_learning_feedback": continual_learning_feedback,
                    "errors": report.errors,
                    "cases": [asdict(case) for case in report.cases],
                }, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "task-stream-transfer-report":
        from dataclasses import asdict
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        stream_files = getattr(args, "stream_file", []) or []
        if not stream_files:
            print("task-stream-transfer-report requires at least one --stream-file")
            sys.exit(1)
        runner = BenchmarkRunner(Config())
        report = runner.run_task_stream_transfer_report_from_files(
            stream_files,
            cell_size=getattr(args, "cell_size", 8.0),
        )
        runner.print_task_stream_transfer_report(report)
        task_stream_feedback = runner.task_stream_transfer_feedback(report)
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump({
                    "type": "task_stream_transfer_report",
                    "schema_version": 1,
                    "stream_count": report.stream_count,
                    "ready_stream_count": report.ready_stream_count,
                    "task_count": report.task_count,
                    "reusable_relation_count": report.reusable_relation_count,
                    "reuse_expected_tag_count": report.reuse_expected_tag_count,
                    "reuse_hit_tag_count": report.reuse_hit_tag_count,
                    "reuse_coverage": report.reuse_coverage,
                    "interference_count": report.interference_count,
                    "average_plasticity_gain": report.average_plasticity_gain,
                    "average_stability_gain": report.average_stability_gain,
                    "average_generalization_gain": report.average_generalization_gain,
                    "task_stream_feedback": task_stream_feedback,
                    "errors": report.errors,
                    "cases": [asdict(case) for case in report.cases],
                }, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "task-stream-transfer-gate":
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        transfer_reports = getattr(args, "transfer_report", []) or []
        if not transfer_reports:
            print("task-stream-transfer-gate requires at least one --transfer-report")
            sys.exit(1)
        runner = BenchmarkRunner(Config())
        report = runner.build_task_stream_transfer_gate(
            transfer_report_paths=transfer_reports,
            target=getattr(args, "target", "memory_or_skill_promotion"),
            min_plasticity_gain=getattr(args, "min_plasticity_gain", 0.01),
            min_stability_gain=getattr(args, "min_stability_gain", 0.0),
            min_generalization_gain=getattr(args, "min_generalization_gain", 0.0),
            min_reuse_coverage=getattr(args, "min_reuse_coverage", 0.5),
            max_interference_count=getattr(args, "max_interference_count", 0),
            require_heldout=not getattr(args, "no_require_heldout", False),
        )
        runner.print_task_stream_transfer_gate_report(report)
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "memory-read-filter-report":
        from singularity.core.memory import MemorySystem

        current_state = {}
        if getattr(args, "current_state_file", ""):
            with open(args.current_state_file, "r", encoding="utf-8-sig") as f:
                current_state = json.load(f)
        elif getattr(args, "current_state_json", ""):
            current_state = json.loads(args.current_state_json)
        memory = MemorySystem(memory_dir=getattr(args, "memory_dir", "workspace/memory"))
        report = memory.memory_read_filter_report(
            query=getattr(args, "query", ""),
            current_state=current_state or None,
        )
        print("\nMemory Read Filter Report")
        print(f"  memory dir: {getattr(args, 'memory_dir', 'workspace/memory')}")
        print(f"  query: {report['query'] or '-'}")
        print(f"  total entries: {report['total_entries']}")
        print(f"  usable entries: {report['usable_entries']}")
        print(f"  filtered entries: {report['filtered_entries']}")
        for reason, count in sorted(report["filter_reasons"].items()):
            print(f"    - {reason}: {count}")
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "memory-promptware-report":
        from singularity.core.memory import MemorySystem

        current_state = {}
        if getattr(args, "current_state_file", ""):
            with open(args.current_state_file, "r", encoding="utf-8-sig") as f:
                current_state = json.load(f)
        elif getattr(args, "current_state_json", ""):
            current_state = json.loads(args.current_state_json)
        if current_state and not isinstance(current_state, dict):
            print("memory-promptware-report current state must be a JSON object")
            sys.exit(1)

        memory = MemorySystem(memory_dir=getattr(args, "memory_dir", "workspace/memory"))
        report = memory.memory_promptware_report(
            query=getattr(args, "query", ""),
            current_state=current_state or None,
        )
        print("\nMemory Promptware Report")
        print(f"  memory dir: {getattr(args, 'memory_dir', 'workspace/memory')}")
        print(f"  query: {report['query'] or '-'}")
        print(
            f"  flagged entries: {report['flagged_entry_count']}, "
            f"flagged experiences: {report['flagged_experience_count']}"
        )
        for reason, count in sorted(report["reason_counts"].items()):
            print(f"    - {reason}: {count}")
        for entry in report["flagged_entries"]:
            print(f"  - memory {entry['id']} flags={','.join(entry['flags'])} tags={','.join(entry['tags'])}")
        for experience in report["flagged_experiences"]:
            print(f"  - experience {experience['id']} flags={','.join(experience['flags'])} tags={','.join(experience['tags'])}")
        if getattr(args, "output", ""):
            output_dir = os.path.dirname(args.output)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "memory-promptware-gate":
        from singularity.core.memory import build_memory_promptware_gate

        report = build_memory_promptware_gate(
            report_paths=getattr(args, "memory_promptware_report", []) or [],
            max_flagged_entries=getattr(args, "max_flagged_entries", 0),
            max_flagged_experiences=getattr(args, "max_flagged_experiences", 0),
        )
        print("\nMemory Promptware Gate")
        print(f"  readiness: {report.get('readiness', 'unknown')}")
        print(f"  decision: {report.get('decision', 'unknown')}")
        print(f"  reason: {report.get('reason', '')}")
        print(
            "  inputs: "
            f"reports={report.get('report_count', 0)}, "
            f"entries={report.get('flagged_entry_count', 0)}/{report.get('total_entries', 0)} flagged, "
            f"experiences={report.get('flagged_experience_count', 0)}/{report.get('total_experiences', 0)} flagged"
        )
        if report.get("reason_counts"):
            parts = [f"{key}={value}" for key, value in sorted(report.get("reason_counts", {}).items())]
            print(f"  flags: {', '.join(parts)}")
        if report.get("missing"):
            print(f"  missing: {', '.join(report.get('missing', []))}")
        for check in report.get("checks", [])[:12]:
            marker = "+" if check.get("status") == "pass" else "x" if check.get("status") == "fail" else "!"
            print(f"  [{marker}] {check.get('kind')} {check.get('source')}: {check.get('detail')}")
        for error in report.get("errors", []):
            print(f"  error: {error}")
        if getattr(args, "output", ""):
            output_dir = os.path.dirname(args.output)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        if report.get("readiness") in {"error", "rejected"}:
            sys.exit(1)
        return

    if args.command == "plan-cache-report":
        from singularity.core.plan_cache import build_plan_transition_cache_report, write_plan_transition_cache_report

        logs = getattr(args, "session_log", []) or []
        if not logs:
            print("plan-cache-report requires at least one --session-log")
            sys.exit(1)
        report = build_plan_transition_cache_report(
            session_log_paths=logs,
            min_support=getattr(args, "min_support", 1),
            min_success_rate=getattr(args, "min_success_rate", 0.6),
            max_entries=getattr(args, "max_entries", 200),
        )
        print("\nPlan Transition Cache Report")
        print(f"  readiness: {report.get('readiness', 'unknown')}")
        print(f"  decision: {report.get('decision', 'unknown')}")
        print(f"  reason: {report.get('reason', '')}")
        print(
            "  inputs: "
            f"logs={report.get('session_log_count', 0)}, "
            f"plans={report.get('plan_event_count', 0)}, "
            f"candidates={report.get('transition_candidate_count', 0)}, "
            f"accepted={report.get('accepted_entry_count', 0)}"
        )
        if report.get("promptware_threat_count"):
            print(f"  promptware threats: {report.get('promptware_threat_count')}")
        for entry in report.get("entries", [])[:8]:
            marker = "+" if entry.get("accepted_for_runtime") else "!"
            actions = entry.get("plan", {}).get("actions", []) if isinstance(entry.get("plan", {}), dict) else []
            action_types = [str(action.get("type", "")) for action in actions if isinstance(action, dict)]
            print(
                f"  [{marker}] {entry.get('id')} confidence={entry.get('confidence')} "
                f"support={entry.get('support_count')} success={entry.get('success_rate')} "
                f"actions={','.join(action_types[:5])}"
            )
        for error in report.get("errors", []):
            print(f"  error: {error}")
        if getattr(args, "output", ""):
            write_plan_transition_cache_report(report, args.output)
            print(f"\nReport saved to {args.output}")
        if report.get("readiness") == "error":
            sys.exit(1)
        return

    if args.command == "plan-cache-runtime-report":
        from singularity.core.plan_cache import build_plan_cache_runtime_report, write_plan_transition_cache_report

        logs = getattr(args, "session_log", []) or []
        if not logs:
            print("plan-cache-runtime-report requires at least one --session-log")
            sys.exit(1)
        report = build_plan_cache_runtime_report(
            session_log_paths=logs,
            min_cache_hits=getattr(args, "min_cache_hits", 1),
            max_rejected_action_rate=getattr(args, "max_rejected_action_rate", 0.0),
            max_action_failure_rate=getattr(args, "max_action_failure_rate", 0.3),
        )
        print("\nPlan Cache Runtime Report")
        print(f"  readiness: {report.get('readiness', 'unknown')}")
        print(f"  decision: {report.get('decision', 'unknown')}")
        print(f"  reason: {report.get('reason', '')}")
        print(
            "  cache: "
            f"hits={report.get('plan_cache_hit_count', 0)}, "
            f"misses={report.get('plan_cache_miss_count', 0)}, "
            f"hit_rate={report.get('plan_cache_hit_rate', 0)}"
        )
        print(
            "  post-hit actions: "
            f"actions={report.get('post_hit_action_count', 0)}, "
            f"failures={report.get('post_hit_action_failure_count', 0)} "
            f"rate={report.get('post_hit_action_failure_rate', 0)}, "
            f"verifier_rejects={report.get('post_hit_action_verification_reject_count', 0)} "
            f"rate={report.get('post_hit_action_verification_reject_rate', 0)}"
        )
        for item in report.get("hit_examples", [])[:8]:
            print(
                f"  [+] {item.get('entry_id', '-')}: "
                f"actions={item.get('action_count', 0)}, "
                f"failures={item.get('action_failure_count', 0)}, "
                f"rejects={item.get('verification_reject_count', 0)}, "
                f"completed={item.get('goal_completed', False)}"
            )
        for error in report.get("errors", []):
            print(f"  error: {error}")
        if getattr(args, "output", ""):
            write_plan_transition_cache_report(report, args.output)
            print(f"\nReport saved to {args.output}")
        if report.get("readiness") == "error":
            sys.exit(1)
        return

    if args.command == "plan-cache-gate":
        from singularity.core.plan_cache import build_plan_cache_gate, write_plan_transition_cache_report

        report = build_plan_cache_gate(
            cache_report_paths=getattr(args, "plan_cache_report", []) or [],
            runtime_report_paths=getattr(args, "runtime_report", []) or [],
            min_accepted_entries=getattr(args, "min_accepted_entries", 1),
            min_runtime_hits=getattr(args, "min_runtime_hits", 0),
            max_promptware_threats=getattr(args, "max_promptware_threats", 0),
            max_rejected_action_rate=getattr(args, "max_rejected_action_rate", 0.0),
            max_action_failure_rate=getattr(args, "max_action_failure_rate", 0.3),
        )
        print("\nPlan Cache Gate")
        print(f"  readiness: {report.get('readiness', 'unknown')}")
        print(f"  decision: {report.get('decision', 'unknown')}")
        print(f"  reason: {report.get('reason', '')}")
        print(
            "  inputs: "
            f"cache_reports={report.get('approved_cache_report_count', 0)}/{report.get('cache_report_count', 0)} approved, "
            f"runtime_reports={report.get('approved_runtime_report_count', 0)}/{report.get('runtime_report_count', 0)} approved, "
            f"accepted_entries={report.get('accepted_entry_count', 0)}, "
            f"runtime_hits={report.get('runtime_hit_count', 0)}"
        )
        print(
            "  runtime rates: "
            f"failure={report.get('runtime_action_failure_rate', 0)}, "
            f"verifier_reject={report.get('runtime_action_verification_reject_rate', 0)}"
        )
        if report.get("missing"):
            print(f"  missing: {', '.join(report.get('missing', []))}")
        for check in report.get("checks", [])[:12]:
            marker = "+" if check.get("status") == "pass" else "x" if check.get("status") == "fail" else "!"
            print(f"  [{marker}] {check.get('kind')} {check.get('source')}: {check.get('readiness')}")
        for error in report.get("errors", []):
            print(f"  error: {error}")
        if getattr(args, "output", ""):
            write_plan_transition_cache_report(report, args.output)
            print(f"\nReport saved to {args.output}")
        if report.get("readiness") in {"error", "rejected"}:
            sys.exit(1)
        return

    if args.command == "agent-module-comparison-report":
        from singularity.evaluation.module_comparison import (
            build_agent_module_comparison_report,
            write_agent_module_comparison_report,
        )

        baseline_logs = getattr(args, "baseline_session_log", []) or []
        candidate_logs = getattr(args, "candidate_session_log", []) or []
        if not baseline_logs or not candidate_logs:
            print("agent-module-comparison-report requires at least one --baseline-session-log and one --candidate-session-log")
            sys.exit(1)
        report = build_agent_module_comparison_report(
            baseline_log_paths=baseline_logs,
            candidate_log_paths=candidate_logs,
            baseline_label=getattr(args, "baseline_label", "baseline"),
            candidate_label=getattr(args, "candidate_label", "candidate"),
            max_completion_regression=getattr(args, "max_completion_regression", 0.0),
            max_action_failure_regression=getattr(args, "max_action_failure_regression", 0.10),
            max_verifier_reject_regression=getattr(args, "max_verifier_reject_regression", 0.10),
            max_empty_plan_regression=getattr(args, "max_empty_plan_regression", 0.10),
        )
        _print_agent_module_comparison_report(report)
        if getattr(args, "output", ""):
            write_agent_module_comparison_report(report, args.output)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "skill-edit-proposal-report":
        from singularity.core.skill_extractor import build_skill_edit_proposal_report

        report = build_skill_edit_proposal_report(
            queue_path=getattr(args, "queue", "workspace/skills/skill_candidates.jsonl"),
            skill_storage_path=getattr(args, "skill_storage_path", "workspace/skills"),
            discovery_gate_paths=getattr(args, "discovery_skill_gate", []) or [],
            transfer_gate_paths=getattr(args, "task_stream_transfer_gate", []) or [],
            causal_evidence_gate_paths=getattr(args, "causal_evidence_gate", []) or [],
            include_all=getattr(args, "include_all", False),
            require_transfer_gate=not getattr(args, "no_require_transfer_gate", False),
            min_score=getattr(args, "min_score", 0.55),
        )
        print("\nSkill Edit Proposal Report")
        print(f"  candidates: {report['candidate_count']}")
        print(
            "  proposals: "
            + ", ".join(f"{key}={value}" for key, value in sorted(report["proposal_counts"].items()))
            if report["proposal_counts"]
            else "  proposals: none"
        )
        print(
            f"  readiness: approved={report['ready_count']}, "
            f"review={report['review_count']}, rejected={report['reject_count']}"
        )
        print(f"  transfer probe required: {report['require_transfer_gate']}")
        for proposal in report["proposals"][:12]:
            marker = "+" if proposal["readiness"] == "approved" else "x" if proposal["readiness"] == "rejected" else "!"
            target = f" -> {proposal['target_skill']}" if proposal.get("target_skill") else ""
            print(
                f"  [{marker}] {proposal['candidate_id']} {proposal['proposal']}{target}: "
                f"{proposal['candidate_name']} score={proposal['score']:.2f}"
            )
            print(f"      {proposal['reason']}")
        if getattr(args, "output", ""):
            output_dir = os.path.dirname(args.output)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "skill-candidates":
        from singularity.core.skill_extractor import SkillCandidateQueue, SkillExtractor
        from singularity.core.skill_library import SkillLibrary

        queue = SkillCandidateQueue(getattr(args, "queue", "workspace/skills/skill_candidates.jsonl"))
        promotion_critic = _promotion_critic_from_args(args)
        if getattr(args, "session", ""):
            lib = SkillLibrary(storage_path=getattr(args, "storage_path", "workspace/skills"))
            extractor = SkillExtractor(
                lib,
                auto_promote=False,
                promotion_critic=promotion_critic,
                discovery_gate_paths=getattr(args, "discovery_skill_gate", []) or [],
                transfer_gate_paths=getattr(args, "task_stream_transfer_gate", []) or [],
                causal_evidence_gate_paths=getattr(args, "causal_evidence_gate", []) or [],
            )
            candidates = extractor.extract_skill_candidates(args.session)
            if getattr(args, "causal_summaries", False):
                candidates.extend(extractor.extract_causal_skill_candidates(
                    args.session,
                    min_repeats=getattr(args, "min_causal_repeats", 3),
                    min_value_score=getattr(args, "min_causal_value", 0.65),
                ))
            if getattr(args, "failure_corrections", False):
                candidates.extend(extractor.extract_failure_correction_candidates(
                    args.session,
                    min_failures=getattr(args, "min_failure_repeats", 2),
                    min_value_score=getattr(args, "min_failure_value", 0.55),
                ))
            for candidate in candidates:
                if promotion_critic:
                    report = extractor.validate_candidate_for_promotion(candidate)
                    candidate.signals = {
                        **candidate.signals,
                        "verification_gate": report.gate,
                        "promotion_report": report.to_dict(),
                    }
                queue.enqueue(candidate)
                print(f"queued {candidate.id}: {candidate.name} score={candidate.score}")
            if not candidates:
                print("no promotable candidates found")
            return
        if getattr(args, "approve", ""):
            lib = SkillLibrary(storage_path=getattr(args, "storage_path", "workspace/skills"), persist=True)
            candidate = queue.approve(
                args.approve,
                lib,
                promotion_critic=promotion_critic,
                discovery_gate_paths=getattr(args, "discovery_skill_gate", []) or [],
                transfer_gate_paths=getattr(args, "task_stream_transfer_gate", []) or [],
                causal_evidence_gate_paths=getattr(args, "causal_evidence_gate", []) or [],
            )
            if not candidate:
                print(f"candidate not found: {args.approve}")
                sys.exit(1)
            if candidate.review_status != "approved":
                print(f"{candidate.review_status} {candidate.id}: {candidate.name}; reason={candidate.reason}")
                sys.exit(2)
            print(f"approved {candidate.id}: {candidate.name}")
            return
        if getattr(args, "reject", ""):
            candidate = queue.reject(args.reject, getattr(args, "reason", ""))
            if not candidate:
                print(f"candidate not found: {args.reject}")
                sys.exit(1)
            print(f"rejected {candidate.id}: {candidate.name}")
            return

        candidates = queue.all() if getattr(args, "all", False) else queue.pending()
        print(f"\nSkill Candidates ({len(candidates)})\n")
        for candidate in candidates:
            report = candidate.signals.get("promotion_report", {}) if isinstance(candidate.signals, dict) else {}
            gate = report.get("gate", {}) if isinstance(report, dict) else {}
            if not gate and isinstance(candidate.signals, dict):
                gate = candidate.signals.get("verification_gate", {})
            gate_text = ""
            if isinstance(gate, dict) and gate:
                gate_text = f" gate={gate.get('decision', 'allow')}/{gate.get('status', 'unknown')}:{gate.get('reason', '')}"
            discovery_gate = report.get("discovery_gate", {}) if isinstance(report, dict) else {}
            if not discovery_gate and isinstance(candidate.signals, dict):
                discovery_gate = candidate.signals.get("discovery_skill_gate", {})
            discovery_text = ""
            if isinstance(discovery_gate, dict) and discovery_gate.get("required"):
                discovery_text = f" discovery={discovery_gate.get('readiness', 'unknown')}:{discovery_gate.get('reason', '')}"
            transfer_gate = report.get("transfer_gate", {}) if isinstance(report, dict) else {}
            if not transfer_gate and isinstance(candidate.signals, dict):
                transfer_gate = candidate.signals.get("task_stream_transfer_gate", {})
            transfer_text = ""
            if isinstance(transfer_gate, dict) and transfer_gate.get("required"):
                transfer_text = f" transfer={transfer_gate.get('readiness', 'unknown')}:{transfer_gate.get('reason', '')}"
            causal_gate = report.get("causal_evidence_gate", {}) if isinstance(report, dict) else {}
            if not causal_gate and isinstance(candidate.signals, dict):
                causal_gate = candidate.signals.get("causal_evidence_gate", {})
            causal_text = ""
            if isinstance(causal_gate, dict) and causal_gate.get("required"):
                causal_text = f" causal={causal_gate.get('readiness', 'unknown')}:{causal_gate.get('reason', '')}"
            print(f"- {candidate.id} [{candidate.review_status}] {candidate.name} score={candidate.score}{gate_text}{discovery_text}{transfer_text}{causal_text}: {candidate.description}")
        return

    if args.command == "collab-benchmark":
        from singularity.evaluation.collaboration_benchmark import CollaborationBenchmarkSpec
        from singularity.evaluation.collaboration_runner import CollaborationBenchmarkRunner

        runner = CollaborationBenchmarkRunner(getattr(args, "state_path", "workspace/multiagent/collab_benchmark_state.json"))
        executor_mode = getattr(args, "executor", "simulated")
        spec_path = getattr(args, "spec", "workspace/benchmarks/m7_time_sensitive_shelter.json")
        task_executor = None
        output_path = getattr(args, "output", "")
        run_baseline = getattr(args, "single_agent_baseline", False)
        run_mixed_policy_ablation = getattr(args, "mixed_policy_ablation", False)
        baseline_role_id = getattr(args, "baseline_role_id", "single_agent") or "single_agent"
        baseline_state_path = getattr(args, "baseline_state_path", "") or ""
        if run_mixed_policy_ablation:
            if executor_mode != "agent":
                print("collab-benchmark --mixed-policy-ablation requires --executor agent")
                sys.exit(1)
            if not getattr(args, "execute", False):
                print("collab-benchmark --mixed-policy-ablation requires --execute")
                sys.exit(1)
            if run_baseline:
                print("collab-benchmark --mixed-policy-ablation cannot be combined with --single-agent-baseline")
                sys.exit(1)
            if not merge_arg_profile_list(args, "mixed_policy_patch", runtime_profiles, "mixed_policy_patch_paths"):
                print("collab-benchmark --mixed-policy-ablation requires at least one --mixed-policy-patch")
                sys.exit(1)
        if run_baseline and not (getattr(args, "preflight", False) or getattr(args, "execute", False)):
            print("collab-benchmark --single-agent-baseline requires --preflight or --execute")
            sys.exit(1)
        if run_baseline and not baseline_state_path:
            root, ext = os.path.splitext(runner.state_path)
            baseline_state_path = f"{root}_single_agent_baseline{ext or '.json'}"
        spec = CollaborationBenchmarkSpec.load_json(spec_path)
        schedule_report = runner.analyze_schedule(spec)
        baseline_schedule_report = None
        if run_baseline:
            baseline_schedule_report = runner.analyze_single_agent_baseline_schedule(
                spec,
                baseline_role_id=baseline_role_id,
            )
        output_payload = {
            "type": "collaboration_benchmark",
            "spec_path": spec_path,
            "state_path": runner.state_path,
            "executor": executor_mode,
            "schedule_analysis": runner.schedule_report_to_dict(schedule_report),
            "single_agent_baseline_schedule": runner.schedule_report_to_dict(baseline_schedule_report) if baseline_schedule_report else None,
            "schedule_comparison": runner.compare_schedule_reports(schedule_report, baseline_schedule_report) if baseline_schedule_report else None,
            "execution_schedule_comparison": None,
            "single_agent_baseline_schedule_execution_comparison": None,
            "agent_bridge_launch_plan": None,
            "single_agent_baseline_bridge_launch_plan": None,
            "runtime_profile_suite_preflight": None,
            "preflight": None,
            "single_agent_baseline_preflight": None,
            "dry_run": None,
            "execution": None,
            "single_agent_baseline": None,
            "baseline_comparison": None,
        }
        runner.print_schedule_report(schedule_report)
        if baseline_schedule_report:
            runner.print_schedule_report(baseline_schedule_report, title="Single-Agent Baseline Schedule Analysis")
            comparison = runner.compare_schedule_reports(schedule_report, baseline_schedule_report)
            print(f"\nSchedule Comparison")
            print(f"  makespan delta: {comparison['makespan_s_delta']}s")
            print(f"  speedup: {comparison['speedup']}x")
        runtime_profile_suite_paths = getattr(args, "runtime_profile_suite_report", []) or []
        if (
            getattr(args, "runtime_profile_suite_preflight", False)
            or runtime_profile_suite_paths
            or getattr(args, "runtime_profile", [])
        ):
            from singularity.evaluation.benchmark_runner import BenchmarkRunner

            profile_suite_runner = BenchmarkRunner(Config())
            profile_suite_report = profile_suite_runner.run_runtime_profile_suite_preflight(
                suite="m7",
                profile_paths=getattr(args, "runtime_profile", []) or [],
                suite_report_paths=runtime_profile_suite_paths,
                required_profiles=getattr(args, "runtime_profile_suite_required_profile", []) or [],
            )
            profile_suite_runner.print_runtime_profile_suite_preflight_report(profile_suite_report)
            output_payload["runtime_profile_suite_preflight"] = profile_suite_report
            profile_suite_preflight_output = getattr(args, "runtime_profile_suite_preflight_output", "") or ""
            if profile_suite_preflight_output:
                profile_suite_runner.save_runtime_profile_suite_preflight_report(
                    profile_suite_report,
                    profile_suite_preflight_output,
                )
            if not profile_suite_report.get("ready"):
                runner.save_json_report(output_payload, output_path)
                sys.exit(1)
        if executor_mode == "agent":
            from singularity.evaluation.collaboration_executor import AgentCollaborationExecutor

            role_bridge_ports = {}
            for item in getattr(args, "role_bridge_port", []) or []:
                if "=" not in item:
                    print(f"invalid --role-bridge-port value: {item}; expected ROLE=PORT")
                    sys.exit(1)
                role_id, raw_port = (part.strip() for part in item.split("=", 1))
                if not role_id:
                    print(f"invalid --role-bridge-port value: {item}; role cannot be empty")
                    sys.exit(1)
                try:
                    port = int(raw_port)
                except ValueError:
                    print(f"invalid port in --role-bridge-port value: {item}")
                    sys.exit(1)
                if port <= 0:
                    print(f"invalid port in --role-bridge-port value: {item}")
                    sys.exit(1)
                role_bridge_ports[role_id] = port

            def make_agent_executor(mixed_policy_patch_paths):
                return AgentCollaborationExecutor(Config(
                    bot=BotConfig(
                        host=getattr(args, "host", "localhost"),
                        port=getattr(args, "port", 25565),
                        username=getattr(args, "username", "Singularity"),
                        bridge_host=getattr(args, "bridge_host", "127.0.0.1"),
                        bridge_port=getattr(args, "bridge_port", 3000),
                    ),
                    llm=LLMConfig(
                        provider=getattr(args, "llm_provider", "openai"),
                        model=getattr(args, "llm_model", "gpt-4o-mini"),
                        api_key=(
                            getattr(args, "api_key", "")
                            or os.environ.get("SINGULARITY_LLM_API_KEY", "")
                            or os.environ.get("OPENAI_API_KEY", "")
                        ),
                        base_url=getattr(args, "llm_base_url", "") or os.environ.get("SINGULARITY_LLM_BASE_URL", ""),
                    ),
                    enable_goal_critic=profile_bool_arg(args, "goal_critic", runtime_profiles, "enable_goal_critic", "goal_critic"),
                    goal_critic_gate_paths=merge_arg_profile_list(args, "goal_critic_gate", runtime_profiles, "goal_critic_gate_paths"),
                    enforce_memory_write_gate=profile_bool_arg(args, "enforce_memory_write_gate", runtime_profiles, "enforce_memory_write_gate", "memory_write_gate"),
                    memory_promptware_gate_paths=merge_arg_profile_list(args, "memory_promptware_gate", runtime_profiles, "memory_promptware_gate_paths"),
                    enable_weighted_memory_retrieval=profile_bool_arg(args, "enable_weighted_memory_retrieval", runtime_profiles, "enable_weighted_memory_retrieval", "weighted_memory_retrieval"),
                    memory_attribution_gate_paths=merge_arg_profile_list(args, "memory_attribution_gate", runtime_profiles, "memory_attribution_gate_paths"),
                    enable_plan_cache=profile_bool_arg(args, "enable_plan_cache", runtime_profiles, "enable_plan_cache", "plan_cache"),
                    plan_cache_paths=merge_arg_profile_list(args, "plan_cache", runtime_profiles, "plan_cache_paths"),
                    plan_cache_gate_paths=merge_arg_profile_list(args, "plan_cache_gate", runtime_profiles, "plan_cache_gate_paths"),
                    plan_cache_min_confidence=getattr(args, "plan_cache_min_confidence", 0.75),
                    enable_task_continuity_context=not getattr(args, "no_task_continuity_context", False),
                    enable_skill_memory_context=not getattr(args, "no_skill_memory_context", False),
                    enable_coaching_policy=not getattr(args, "no_coaching_policy", False),
                    coach_style=profile_str_arg(args, "coach_style", runtime_profiles, "coach_style", default=""),
                    enable_vision_analysis=not getattr(args, "no_vision_analysis", False),
                    enable_visual_action_grounding=not getattr(args, "no_visual_action_grounding", False),
                    enable_screenshot_capture=profile_bool_arg(args, "capture_screenshots", runtime_profiles, "enable_screenshot_capture", "capture_screenshots"),
                    mixed_policy_patch_paths=list(mixed_policy_patch_paths or []),
                    mixed_policy_gate_paths=merge_arg_profile_list(args, "mixed_policy_gate", runtime_profiles, "mixed_policy_gate_paths"),
                    self_evolution_feedback_paths=merge_arg_profile_list(args, "self_evolution_feedback", runtime_profiles, "self_evolution_feedback_paths"),
                    world_model_feedback_paths=merge_arg_profile_list(args, "world_model_feedback", runtime_profiles, "world_model_feedback_paths"),
                    world_model_gate_paths=merge_arg_profile_list(args, "world_model_gate", runtime_profiles, "world_model_gate_paths"),
                    enable_knowledge_correction_context=not getattr(args, "no_knowledge_correction_context", False),
                    knowledge_correction_feedback_paths=merge_arg_profile_list(args, "knowledge_correction_feedback", runtime_profiles, "knowledge_correction_feedback_paths"),
                    knowledge_correction_gate_paths=merge_arg_profile_list(args, "knowledge_correction_gate", runtime_profiles, "knowledge_correction_gate_paths"),
                    enable_task_precondition_context=not getattr(args, "no_task_precondition_context", False),
                    task_precondition_feedback_paths=merge_arg_profile_list(args, "task_precondition_feedback", runtime_profiles, "task_precondition_feedback_paths"),
                    task_precondition_gate_paths=merge_arg_profile_list(args, "task_precondition_gate", runtime_profiles, "task_precondition_gate_paths"),
                    action_value_feedback_paths=merge_arg_profile_list(args, "action_value_feedback", runtime_profiles, "action_value_feedback_paths"),
                    action_value_transition_gate_paths=merge_arg_profile_list(args, "action_value_transition_gate", runtime_profiles, "action_value_transition_gate_paths"),
                    action_value_transition_evaluator_report_paths=merge_arg_profile_list(args, "action_value_transition_evaluator_report", runtime_profiles, "action_value_transition_evaluator_report_paths"),
                    skill_memory_quality_feedback_paths=merge_arg_profile_list(args, "skill_memory_quality_feedback", runtime_profiles, "skill_memory_quality_feedback_paths"),
                    skill_memory_quality_gate_paths=merge_arg_profile_list(args, "skill_memory_quality_gate", runtime_profiles, "skill_memory_quality_gate_paths"),
                    skill_runtime_default_gate_paths=merge_arg_profile_list(args, "skill_runtime_default_gate", runtime_profiles, "skill_runtime_default_gate_paths"),
                    screenshot_dir=profile_str_arg(args, "screenshot_dir", runtime_profiles, "screenshot_dir", default="logs/screenshots"),
                    screenshot_min_interval_s=getattr(args, "screenshot_min_interval", 2.0),
                ), bridge_port_base=getattr(args, "bridge_port_base", 0) or None, role_bridge_ports=role_bridge_ports)

            if run_mixed_policy_ablation:
                from singularity.evaluation.mixed_initiative import build_mixed_initiative_policy_ablation

                patch_paths = merge_arg_profile_list(args, "mixed_policy_patch", runtime_profiles, "mixed_policy_patch_paths")
                baseline_executor = make_agent_executor([])
                patched_executor = make_agent_executor(patch_paths)
                bridge_launch_plan = patched_executor.bridge_launch_plan(spec)
                patched_executor.print_bridge_launch_plan(bridge_launch_plan)
                output_payload["type"] = "collaboration_mixed_policy_ablation"
                output_payload["mixed_policy_patch_paths"] = list(patch_paths)
                output_payload["policy_decision_report"] = build_mixed_initiative_policy_ablation(
                    patch_paths=patch_paths
                ).to_dict()
                output_payload["agent_bridge_launch_plan"] = patched_executor.bridge_launch_plan_to_dict(bridge_launch_plan)
                if getattr(args, "preflight", False):
                    bridge_report = patched_executor.preflight_bridges(spec)
                    patched_executor.print_bridge_preflight_report(bridge_report)
                    output_payload["preflight"] = patched_executor.bridge_preflight_report_to_dict(bridge_report)
                    if not bridge_report.ok:
                        runner.save_json_report(output_payload, output_path)
                        sys.exit(1)

                root, ext = os.path.splitext(runner.state_path)
                baseline_mixed_state_path = f"{root}_mixed_policy_baseline{ext or '.json'}"
                patched_mixed_state_path = f"{root}_mixed_policy_patched{ext or '.json'}"
                baseline_mixed_runner = CollaborationBenchmarkRunner(baseline_mixed_state_path)
                patched_mixed_runner = CollaborationBenchmarkRunner(patched_mixed_state_path)
                try:
                    baseline_result = baseline_mixed_runner.execute(
                        spec,
                        executor=baseline_executor,
                        reset=not getattr(args, "no_reset", False),
                        max_steps=getattr(args, "max_steps", 0) or None,
                    )
                    patched_result = patched_mixed_runner.execute(
                        spec,
                        executor=patched_executor,
                        reset=not getattr(args, "no_reset", False),
                        max_steps=getattr(args, "max_steps", 0) or None,
                    )
                finally:
                    baseline_executor.close()
                    patched_executor.close()

                print("\nMixed Policy Baseline")
                baseline_mixed_runner.print_execution_report(baseline_result)
                baseline_schedule_comparison = baseline_mixed_runner.compare_schedule_to_execution(
                    schedule_report,
                    baseline_result,
                )
                baseline_mixed_runner.print_schedule_execution_comparison(
                    baseline_schedule_comparison,
                    title="Baseline Schedule vs Execution",
                )
                print("\nMixed Policy Patched")
                patched_mixed_runner.print_execution_report(patched_result)
                patched_schedule_comparison = patched_mixed_runner.compare_schedule_to_execution(
                    schedule_report,
                    patched_result,
                )
                patched_mixed_runner.print_schedule_execution_comparison(
                    patched_schedule_comparison,
                    title="Patched Schedule vs Execution",
                )
                mixed_policy_comparison = runner.compare_mixed_policy_execution_reports(
                    baseline_result,
                    patched_result,
                )
                print("\nMixed Policy Execution Comparison")
                print(f"  ok delta: {mixed_policy_comparison['ok_delta']}")
                print(f"  completed delta: {mixed_policy_comparison['completed_tasks_delta']}")
                print(f"  failed delta: {mixed_policy_comparison['failed_tasks_delta']}")
                print(f"  elapsed delta: {mixed_policy_comparison['total_elapsed_s_delta']}s")
                baseline_control = mixed_policy_comparison.get("baseline_control_policy", {})
                patched_control = mixed_policy_comparison.get("patched_control_policy", {})
                print(f"  control changed: {mixed_policy_comparison.get('control_policy_changed', False)}")
                print(f"  baseline control: {baseline_control.get('preferred_control_counts', {})}")
                print(f"  patched control: {patched_control.get('preferred_control_counts', {})}, fallbacks={patched_control.get('fallback_count', 0)}")
                output_payload["baseline_execution"] = baseline_mixed_runner.execution_report_to_dict(baseline_result)
                output_payload["patched_execution"] = patched_mixed_runner.execution_report_to_dict(patched_result)
                output_payload["baseline_schedule_execution_comparison"] = baseline_mixed_runner.schedule_execution_comparison_to_dict(
                    baseline_schedule_comparison
                )
                output_payload["patched_schedule_execution_comparison"] = patched_mixed_runner.schedule_execution_comparison_to_dict(
                    patched_schedule_comparison
                )
                output_payload["mixed_policy_comparison"] = mixed_policy_comparison
                runner.save_json_report(output_payload, output_path)
                if not baseline_result.ok or not patched_result.ok:
                    sys.exit(1)
                return

            task_executor = make_agent_executor(merge_arg_profile_list(args, "mixed_policy_patch", runtime_profiles, "mixed_policy_patch_paths"))
            bridge_launch_plan = task_executor.bridge_launch_plan(spec)
            task_executor.print_bridge_launch_plan(bridge_launch_plan)
            output_payload["agent_bridge_launch_plan"] = task_executor.bridge_launch_plan_to_dict(bridge_launch_plan)
            if run_baseline:
                baseline_spec = runner.single_agent_baseline_spec(spec, baseline_role_id=baseline_role_id)
                baseline_bridge_launch_plan = task_executor.bridge_launch_plan(baseline_spec)
                task_executor.print_bridge_launch_plan(
                    baseline_bridge_launch_plan,
                    title="Single-Agent Baseline Bridge Launch Plan",
                )
                output_payload["single_agent_baseline_bridge_launch_plan"] = task_executor.bridge_launch_plan_to_dict(
                    baseline_bridge_launch_plan
                )

        if getattr(args, "preflight", False):
            if not task_executor:
                print("collab-benchmark --preflight currently checks Agent executor bridges; use --executor agent")
                sys.exit(1)
            bridge_report = task_executor.preflight_bridges(spec)
            task_executor.print_bridge_preflight_report(bridge_report)
            output_payload["preflight"] = task_executor.bridge_preflight_report_to_dict(bridge_report)
            if not bridge_report.ok:
                runner.save_json_report(output_payload, output_path)
                sys.exit(1)
            if run_baseline:
                baseline_spec = runner.single_agent_baseline_spec(spec, baseline_role_id=baseline_role_id)
                baseline_bridge_report = task_executor.preflight_bridges(baseline_spec)
                print("\nSingle-Agent Baseline")
                task_executor.print_bridge_preflight_report(baseline_bridge_report)
                output_payload["single_agent_baseline_preflight"] = task_executor.bridge_preflight_report_to_dict(baseline_bridge_report)
                if not baseline_bridge_report.ok:
                    runner.save_json_report(output_payload, output_path)
                    sys.exit(1)
            if not getattr(args, "execute", False):
                runner.save_json_report(output_payload, output_path)
                return

        if getattr(args, "execute", False) or executor_mode != "simulated":
            try:
                result = runner.execute(
                    spec,
                    executor=task_executor,
                    reset=not getattr(args, "no_reset", False),
                    max_steps=getattr(args, "max_steps", 0) or None,
                )
                baseline_report = None
                if run_baseline:
                    baseline_runner = CollaborationBenchmarkRunner(baseline_state_path)
                    baseline_report = baseline_runner.run_single_agent_baseline(
                        spec,
                        executor=task_executor,
                        baseline_role_id=baseline_role_id,
                        reset=True,
                        max_steps=getattr(args, "max_steps", 0) or None,
                    )
            finally:
                if task_executor and hasattr(task_executor, "close"):
                    task_executor.close()
            runner.print_execution_report(result)
            output_payload["execution"] = runner.execution_report_to_dict(result)
            execution_schedule_comparison = runner.compare_schedule_to_execution(schedule_report, result)
            runner.print_schedule_execution_comparison(execution_schedule_comparison)
            output_payload["execution_schedule_comparison"] = runner.schedule_execution_comparison_to_dict(execution_schedule_comparison)
            if run_baseline and baseline_report is not None:
                print("\nSingle-Agent Baseline")
                baseline_runner.print_execution_report(baseline_report)
                output_payload["single_agent_baseline"] = baseline_runner.execution_report_to_dict(baseline_report)
                output_payload["baseline_comparison"] = runner.compare_execution_reports(result, baseline_report)
                baseline_schedule_execution_comparison = runner.compare_schedule_to_execution(
                    baseline_schedule_report,
                    baseline_report,
                )
                runner.print_schedule_execution_comparison(
                    baseline_schedule_execution_comparison,
                    title="Single-Agent Schedule vs Execution",
                )
                output_payload["single_agent_baseline_schedule_execution_comparison"] = runner.schedule_execution_comparison_to_dict(
                    baseline_schedule_execution_comparison
                )
            runner.save_json_report(output_payload, output_path)
            if not result.ok:
                sys.exit(1)
            if run_baseline and baseline_report is not None and not baseline_report.ok:
                sys.exit(1)
            return
        result = runner.prepare(spec, reset=not getattr(args, "no_reset", False))
        runner.print_result(result)
        output_payload["dry_run"] = runner.run_result_to_dict(result)
        runner.save_json_report(output_payload, output_path)
        if not result.ok:
            sys.exit(1)
        return

    if args.command == "scheduling-ablation":
        from dataclasses import asdict
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        runner = BenchmarkRunner(Config())
        session_logs = getattr(args, "session_log", []) or []
        if session_logs:
            report = runner.run_scheduling_ablation_from_logs(
                session_logs,
                max_cases_per_log=getattr(args, "max_cases_per_log", 20),
                min_value_score=getattr(args, "min_value_score", 0.55),
            )
        else:
            report = runner.run_scheduling_ablation()
        runner.print_scheduling_ablation_report(report)
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump({
                    "changed_count": report.changed_count,
                    "helped_count": report.helped_count,
                    "cases": [asdict(case) for case in report.cases],
                }, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "coach-style-ablation":
        from dataclasses import asdict
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        runner = BenchmarkRunner(Config())
        styles = getattr(args, "style", []) or []
        cases = []
        case_files = getattr(args, "case_file", []) or []
        session_logs = getattr(args, "session_log", []) or []
        if case_files:
            cases.extend(runner.load_coach_style_ablation_cases(case_files))
        if session_logs:
            cases.extend(runner.coach_style_ablation_cases_from_logs(
                session_logs,
                max_cases_per_log=getattr(args, "max_cases_per_log", 20),
                fallback_goal=getattr(args, "fallback_goal", "Explore surroundings and gather resources"),
                styles=styles,
            ))
        report = runner.run_coach_style_ablation(
            cases=cases if cases else None,
            styles=styles or None,
        )
        runner.print_coach_style_ablation_report(report)
        if getattr(args, "output", ""):
            output_dir = os.path.dirname(args.output)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump({
                    "changed_count": report.changed_count,
                    "score_changed_count": report.score_changed_count,
                    "style_changed_counts": report.style_changed_counts,
                    "cases": [asdict(case) for case in report.cases],
                }, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "coach-style-gate":
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        ablation_reports = getattr(args, "coach_style_ablation", []) or []
        if not ablation_reports:
            print("coach-style-gate requires at least one --coach-style-ablation")
            sys.exit(1)
        runner = BenchmarkRunner(Config())
        report = runner.build_coach_style_gate(
            coach_ablation_report_paths=ablation_reports,
            styles=getattr(args, "style", []) or [],
            target=getattr(args, "target", "coach_style_curriculum_bias"),
            min_cases_per_style=getattr(args, "min_cases_per_style", 1),
            min_score_changed_per_style=getattr(args, "min_score_changed_per_style", 1),
            require_goal_change=getattr(args, "require_goal_change", False),
        )
        runner.print_coach_style_gate_report(report)
        if getattr(args, "output", ""):
            output_dir = os.path.dirname(args.output)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        if report.get("readiness") in {"rejected", "error"}:
            sys.exit(1)
        return

    if args.command == "promotion-review-ablation":
        from dataclasses import asdict
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        session_logs = getattr(args, "session_log", []) or []
        if not session_logs:
            print("promotion-review-ablation requires at least one --session-log")
            sys.exit(1)
        runner = BenchmarkRunner(Config(llm=_llm_config_from_args(args)))
        manual_labels = runner.load_promotion_review_labels(getattr(args, "label_file", "")) if getattr(args, "label_file", "") else {}
        report = runner.run_promotion_review_ablation_from_logs(
            session_logs,
            promotion_critic=_promotion_critic_from_args(args),
            include_causal_summaries=getattr(args, "causal_summaries", False),
            include_failure_corrections=getattr(args, "failure_corrections", False),
            manual_labels=manual_labels,
        )
        runner.print_promotion_review_ablation_report(report)
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump({
                    "candidate_count": report.candidate_count,
                    "changed_count": report.changed_count,
                    "visual_helped_count": report.visual_helped_count,
                    "api_visual_helped_count": report.api_visual_helped_count,
                    "screenshot_vlm_helped_count": report.screenshot_vlm_helped_count,
                    "screenshot_vlm_added_value_count": report.screenshot_vlm_added_value_count,
                    "manual_labeled_count": report.manual_labeled_count,
                    "deterministic_manual_match_count": report.deterministic_manual_match_count,
                    "api_visual_manual_match_count": report.api_visual_manual_match_count,
                    "screenshot_vlm_manual_match_count": report.screenshot_vlm_manual_match_count,
                    "screenshot_vlm_manual_improvement_count": report.screenshot_vlm_manual_improvement_count,
                    "errors": report.errors,
                    "cases": [asdict(case) for case in report.cases],
                }, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "goal-verification-ablation":
        from dataclasses import asdict
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        session_logs = getattr(args, "session_log", []) or []
        if not session_logs:
            print("goal-verification-ablation requires at least one --session-log")
            sys.exit(1)
        runner = BenchmarkRunner(Config(llm=_llm_config_from_args(args)))
        manual_labels = runner.load_goal_verification_labels(getattr(args, "label_file", "")) if getattr(args, "label_file", "") else {}
        report = runner.run_goal_verification_ablation_from_logs(
            session_logs,
            goal_critic=_goal_critic_from_args(args),
            manual_labels=manual_labels,
        )
        runner.print_goal_verification_ablation_report(report)
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump({
                    "goal_count": report.goal_count,
                    "changed_count": report.changed_count,
                    "visual_helped_count": report.visual_helped_count,
                    "api_visual_helped_count": report.api_visual_helped_count,
                    "screenshot_vlm_helped_count": report.screenshot_vlm_helped_count,
                    "screenshot_vlm_added_value_count": report.screenshot_vlm_added_value_count,
                    "manual_labeled_count": report.manual_labeled_count,
                    "deterministic_manual_match_count": report.deterministic_manual_match_count,
                    "api_visual_manual_match_count": report.api_visual_manual_match_count,
                    "screenshot_vlm_manual_match_count": report.screenshot_vlm_manual_match_count,
                    "screenshot_vlm_manual_improvement_count": report.screenshot_vlm_manual_improvement_count,
                    "errors": report.errors,
                    "cases": [asdict(case) for case in report.cases],
                }, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "goal-verification-critic-gate":
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        ablation_paths = getattr(args, "goal_verification_ablation", []) or []
        label_validation_paths = getattr(args, "label_validation", []) or []
        if not ablation_paths:
            print("goal-verification-critic-gate requires at least one --goal-verification-ablation")
            sys.exit(1)
        runner = BenchmarkRunner(Config())
        report = runner.build_goal_verification_critic_gate(
            goal_ablation_report_paths=ablation_paths,
            label_validation_report_paths=label_validation_paths,
            target=getattr(args, "target", "goal_verification_critic_runtime"),
            min_cases=getattr(args, "min_cases", 1),
            min_manual_labels=getattr(args, "min_manual_labels", 1),
            min_screenshot_cases=getattr(args, "min_screenshot_cases", 1),
            min_screenshot_manual_matches=getattr(args, "min_screenshot_manual_matches", 1),
            max_screenshot_manual_mismatches=getattr(args, "max_screenshot_manual_mismatches", 0),
            min_screenshot_added_value=getattr(args, "min_screenshot_added_value", 0),
            require_label_validation=not getattr(args, "no_require_label_validation", False),
        )
        runner.print_goal_verification_critic_gate_report(report)
        if getattr(args, "output", ""):
            output_dir = os.path.dirname(args.output)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        if report.get("readiness") == "error":
            sys.exit(1)
        return

    if args.command == "plan-act-latency-report":
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        session_logs = getattr(args, "session_log", []) or []
        collab_reports = getattr(args, "collab_report", []) or []
        if not session_logs and not collab_reports:
            print("plan-act-latency-report requires at least one --session-log or --collab-report")
            sys.exit(1)
        runner = BenchmarkRunner(Config())
        report = runner.build_plan_act_latency_report(
            session_log_paths=session_logs,
            collab_report_paths=collab_reports,
            stale_plan_s=getattr(args, "stale_plan_s", 5.0),
            long_action_s=getattr(args, "long_action_s", 2.0),
        )
        runner.print_plan_act_latency_report(report)
        if getattr(args, "output", ""):
            output_dir = os.path.dirname(args.output)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        if report.get("readiness") == "error":
            sys.exit(1)
        return

    if args.command == "plan-act-latency-gate":
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        runner = BenchmarkRunner(Config())
        report = runner.build_plan_act_latency_gate(
            baseline_report_paths=getattr(args, "baseline_plan_act_report", []) or [],
            candidate_report_paths=getattr(args, "candidate_plan_act_report", []) or [],
            baseline_verifier_report_paths=getattr(args, "baseline_verifier_report", []) or [],
            candidate_verifier_report_paths=getattr(args, "candidate_verifier_report", []) or [],
            target=getattr(args, "target", "interruptible_plan_act_executor"),
            min_candidate_logs=getattr(args, "min_candidate_logs", 1),
            min_stale_reduction=getattr(args, "min_stale_reduction", 1),
            max_verifier_reject_delta=getattr(args, "max_verifier_reject_delta", 0),
        )
        runner.print_plan_act_latency_gate_report(report)
        if getattr(args, "output", ""):
            output_dir = os.path.dirname(args.output)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        if report.get("readiness") in {"error", "rejected"}:
            sys.exit(1)
        return

    if args.command == "review-label-template":
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        session_logs = getattr(args, "session_log", []) or []
        if not session_logs:
            print("review-label-template requires at least one --session-log")
            sys.exit(1)
        runner = BenchmarkRunner(Config())
        templates = runner.build_review_label_templates_from_logs(
            session_logs,
            mode=getattr(args, "mode", "both"),
            include_causal_summaries=getattr(args, "causal_summaries", False),
            include_failure_corrections=getattr(args, "failure_corrections", False),
        )
        lines = [json.dumps(template, ensure_ascii=False, default=str) for template in templates]
        if getattr(args, "output", ""):
            output_dir = os.path.dirname(args.output)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                for line in lines:
                    f.write(line + "\n")
            print(f"Review label template saved to {args.output} ({len(lines)} records)")
        else:
            for line in lines:
                print(line)
        return

    if args.command == "review-label-validate":
        from dataclasses import asdict
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        runner = BenchmarkRunner(Config())
        report = runner.validate_review_labels(getattr(args, "label_file", ""))
        runner.print_review_label_validation_report(report)
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump({
                    "label_path": report.label_path,
                    "ok": report.ok,
                    "label_count": report.label_count,
                    "ok_count": report.ok_count,
                    "error_count": report.error_count,
                    "invalid_readiness_count": report.invalid_readiness_count,
                    "unknown_readiness_count": report.unknown_readiness_count,
                    "screenshot_unverified_count": report.screenshot_unverified_count,
                    "errors": report.errors,
                    "cases": [asdict(case) for case in report.cases],
                }, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        if not report.ok:
            sys.exit(1)
        return

    if args.command == "visual-trace-report":
        from dataclasses import asdict
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        session_logs = getattr(args, "session_log", []) or []
        if not session_logs:
            print("visual-trace-report requires at least one --session-log")
            sys.exit(1)
        runner = BenchmarkRunner(Config())
        report = runner.run_visual_trace_report_from_logs(
            session_logs,
            include_causal_summaries=getattr(args, "causal_summaries", False),
            include_failure_corrections=getattr(args, "failure_corrections", False),
        )
        runner.print_visual_trace_report(report)
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump({
                    "type": "visual_trace_report",
                    "schema_version": 1,
                    "log_count": report.log_count,
                    "ready_log_count": report.ready_log_count,
                    "screenshot_log_count": report.screenshot_log_count,
                    "raw_screenshot_log_count": report.raw_screenshot_log_count,
                    "missing_screenshot_count": report.missing_screenshot_count,
                    "invalid_screenshot_count": report.invalid_screenshot_count,
                    "goal_count": report.goal_count,
                    "goals_with_visual_evidence_count": report.goals_with_visual_evidence_count,
                    "promotion_candidate_count": report.promotion_candidate_count,
                    "promotion_candidates_with_visual_evidence_count": report.promotion_candidates_with_visual_evidence_count,
                    "errors": report.errors,
                    "cases": [asdict(case) for case in report.cases],
                }, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "exploration-trace-report":
        from dataclasses import asdict
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        session_logs = getattr(args, "session_log", []) or []
        if not session_logs:
            print("exploration-trace-report requires at least one --session-log")
            sys.exit(1)
        runner = BenchmarkRunner(Config())
        report = runner.run_exploration_trace_report_from_logs(session_logs)
        runner.print_exploration_trace_report(report)
        curriculum_feedback = runner.exploration_curriculum_feedback(report)
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump({
                    "type": "exploration_trace_report",
                    "schema_version": 1,
                    "log_count": report.log_count,
                    "ready_log_count": report.ready_log_count,
                    "observation_count": report.observation_count,
                    "goal_count": report.goal_count,
                    "completed_goal_count": report.completed_goal_count,
                    "failed_goal_count": report.failed_goal_count,
                    "failed_action_count": report.failed_action_count,
                    "logs_with_movement_count": report.logs_with_movement_count,
                    "visual_observation_count": report.visual_observation_count,
                    "hostile_encounter_count": report.hostile_encounter_count,
                    "unique_block_type_count": report.unique_block_type_count,
                    "unique_entity_type_count": report.unique_entity_type_count,
                    "unique_resource_type_count": report.unique_resource_type_count,
                    "curriculum_feedback": curriculum_feedback,
                    "errors": report.errors,
                    "cases": [asdict(case) for case in report.cases],
                }, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "world-model-report":
        from dataclasses import asdict
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        session_logs = getattr(args, "session_log", []) or []
        if not session_logs:
            print("world-model-report requires at least one --session-log")
            sys.exit(1)
        runner = BenchmarkRunner(Config())
        report = runner.run_world_model_report_from_logs(
            session_logs,
            cell_size=getattr(args, "cell_size", 8.0),
            limit=getattr(args, "limit", 12),
        )
        runner.print_world_model_report(report)
        world_model_feedback = runner.world_model_curriculum_feedback(report)
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump({
                    "type": "world_model_report",
                    "schema_version": 1,
                    "log_count": report.log_count,
                    "ready_log_count": report.ready_log_count,
                    "observation_count": report.observation_count,
                    "unique_cell_count": report.unique_cell_count,
                    "frontier_count": report.frontier_count,
                    "resource_hotspot_count": report.resource_hotspot_count,
                    "danger_cell_count": report.danger_cell_count,
                    "world_model_feedback": world_model_feedback,
                    "errors": report.errors,
                    "cases": [asdict(case) for case in report.cases],
                }, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "world-model-feedback-gate":
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        report_paths = getattr(args, "world_model_report", []) or []
        if not report_paths:
            print("world-model-feedback-gate requires at least one --world-model-report")
            sys.exit(1)
        runner = BenchmarkRunner(Config())
        report = runner.build_world_model_feedback_gate(
            world_model_report_paths=report_paths,
            target=getattr(args, "target", "world_model_curriculum_feedback"),
            min_ready_logs=getattr(args, "min_ready_logs", 1),
            min_frontiers=getattr(args, "min_frontiers", 1),
            min_actionable_items=getattr(args, "min_actionable_items", 1),
        )
        runner.print_world_model_feedback_gate_report(report)
        if getattr(args, "output", ""):
            output_dir = os.path.dirname(args.output)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "self-evolution-report":
        from dataclasses import asdict
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        session_logs = getattr(args, "session_log", []) or []
        if not session_logs:
            print("self-evolution-report requires at least one --session-log")
            sys.exit(1)
        runner = BenchmarkRunner(Config())
        report = runner.run_self_evolution_report_from_logs(session_logs)
        runner.print_self_evolution_report(report)
        self_evolution_feedback = runner.self_evolution_feedback(report)
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump({
                    "log_count": report.log_count,
                    "ready_log_count": report.ready_log_count,
                    "observation_count": report.observation_count,
                    "action_count": report.action_count,
                    "failed_action_count": report.failed_action_count,
                    "progress_signal_count": report.progress_signal_count,
                    "regression_signal_count": report.regression_signal_count,
                    "stagnation_signal_count": report.stagnation_signal_count,
                    "repeated_failure_count": report.repeated_failure_count,
                    "no_progress_success_count": report.no_progress_success_count,
                    "repeated_success_loop_count": report.repeated_success_loop_count,
                    "blocked_plan_count": report.blocked_plan_count,
                    "empty_plan_count": report.empty_plan_count,
                    "zero_action_failure_count": report.zero_action_failure_count,
                    "relative_reward_delta": report.relative_reward_delta,
                    "self_evolution_feedback": self_evolution_feedback,
                    "errors": report.errors,
                    "cases": [asdict(case) for case in report.cases],
                }, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "self-evolution-counterexample-report":
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        self_reports = getattr(args, "self_evolution_report", []) or []
        terminal_reports = getattr(args, "terminal_commitment_report", []) or []
        plan_action_reports = getattr(args, "plan_action_report", []) or []
        action_verification_reports = getattr(args, "action_verification_report", []) or []
        action_value_reports = getattr(args, "action_value_report", []) or []
        if not any((self_reports, terminal_reports, plan_action_reports, action_verification_reports, action_value_reports)):
            print("self-evolution-counterexample-report requires at least one saved report")
            sys.exit(1)
        runner = BenchmarkRunner(Config())
        report = runner.build_self_evolution_counterexample_report(
            self_evolution_report_paths=self_reports,
            terminal_commitment_report_paths=terminal_reports,
            plan_action_report_paths=plan_action_reports,
            action_verification_report_paths=action_verification_reports,
            action_value_report_paths=action_value_reports,
            limit=getattr(args, "limit", 120),
        )
        runner.print_self_evolution_counterexample_report(report)
        if getattr(args, "output", ""):
            output_dir = os.path.dirname(args.output)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        if report.get("readiness") == "error":
            sys.exit(1)
        return

    if args.command == "plan-action-compliance-report":
        from dataclasses import asdict
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        session_logs = getattr(args, "session_log", []) or []
        if not session_logs:
            print("plan-action-compliance-report requires at least one --session-log")
            sys.exit(1)
        runner = BenchmarkRunner(Config())
        report = runner.run_plan_action_compliance_report_from_logs(session_logs)
        runner.print_plan_action_compliance_report(report)
        plan_action_feedback = runner.plan_action_compliance_feedback(report)
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump({
                    "log_count": report.log_count,
                    "ready_log_count": report.ready_log_count,
                    "plan_count": report.plan_count,
                    "action_count": report.action_count,
                    "planned_action_count": report.planned_action_count,
                    "ordered_match_count": report.ordered_match_count,
                    "unordered_match_count": report.unordered_match_count,
                    "missing_planned_action_count": report.missing_planned_action_count,
                    "unplanned_action_count": report.unplanned_action_count,
                    "order_violation_count": report.order_violation_count,
                    "empty_plan_count": report.empty_plan_count,
                    "blocked_plan_count": report.blocked_plan_count,
                    "plan_follow_score": report.plan_follow_score,
                    "action_precision": report.action_precision,
                    "compliance_score": report.compliance_score,
                    "plan_action_feedback": plan_action_feedback,
                    "errors": report.errors,
                    "cases": [asdict(case) for case in report.cases],
                }, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "terminal-commitment-report":
        from dataclasses import asdict
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        session_logs = getattr(args, "session_log", []) or []
        if not session_logs:
            print("terminal-commitment-report requires at least one --session-log")
            sys.exit(1)
        runner = BenchmarkRunner(Config())
        report = runner.run_terminal_commitment_report_from_logs(session_logs)
        runner.print_terminal_commitment_report(report)
        terminal_commitment_feedback = runner.terminal_commitment_feedback(report)
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump({
                    "goal_count": report.goal_count,
                    "ready_goal_count": report.ready_goal_count,
                    "world_complete_count": report.world_complete_count,
                    "terminal_complete_count": report.terminal_complete_count,
                    "verified_success_count": report.verified_success_count,
                    "unsupported_commitment_count": report.unsupported_commitment_count,
                    "post_attainment_drift_count": report.post_attainment_drift_count,
                    "missed_execution_count": report.missed_execution_count,
                    "unknown_world_count": report.unknown_world_count,
                    "world_completion_score": report.world_completion_score,
                    "terminal_commitment_score": report.terminal_commitment_score,
                    "unsupported_commitment_rate": report.unsupported_commitment_rate,
                    "post_attainment_drift_rate": report.post_attainment_drift_rate,
                    "terminal_commitment_feedback": terminal_commitment_feedback,
                    "errors": report.errors,
                    "cases": [asdict(case) for case in report.cases],
                }, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "action-verification-report":
        from dataclasses import asdict
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        session_logs = getattr(args, "session_log", []) or []
        if not session_logs:
            print("action-verification-report requires at least one --session-log")
            sys.exit(1)
        runner = BenchmarkRunner(Config())
        report = runner.run_action_verification_report_from_logs(session_logs)
        runner.print_action_verification_report(report)
        action_verification_feedback = runner.action_verification_feedback(report)
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump({
                    "log_count": report.log_count,
                    "ready_log_count": report.ready_log_count,
                    "action_count": report.action_count,
                    "verified_action_count": report.verified_action_count,
                    "accepted_action_count": report.accepted_action_count,
                    "review_action_count": report.review_action_count,
                    "rejected_action_count": report.rejected_action_count,
                    "rejected_success_count": report.rejected_success_count,
                    "failed_without_reject_count": report.failed_without_reject_count,
                    "reject_rate": report.reject_rate,
                    "review_rate": report.review_rate,
                    "action_verification_feedback": action_verification_feedback,
                    "errors": report.errors,
                    "cases": [asdict(case) for case in report.cases],
                }, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "action-candidate-report":
        from dataclasses import asdict
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        session_logs = getattr(args, "session_log", []) or []
        if not session_logs:
            print("action-candidate-report requires at least one --session-log")
            sys.exit(1)
        runner = BenchmarkRunner(Config())
        report = runner.run_action_candidate_report_from_logs(session_logs)
        runner.print_action_candidate_report(report)
        action_candidate_feedback = runner.action_candidate_feedback(report)
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump({
                    "log_count": report.log_count,
                    "ready_log_count": report.ready_log_count,
                    "action_count": report.action_count,
                    "original_reject_count": report.original_reject_count,
                    "changed_selection_count": report.changed_selection_count,
                    "repaired_reject_count": report.repaired_reject_count,
                    "unchanged_reject_count": report.unchanged_reject_count,
                    "selection_change_rate": report.selection_change_rate,
                    "repaired_reject_rate": report.repaired_reject_rate,
                    "action_candidate_feedback": action_candidate_feedback,
                    "errors": report.errors,
                    "cases": [asdict(case) for case in report.cases],
                }, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "action-value-report":
        from dataclasses import asdict
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        session_logs = getattr(args, "session_log", []) or []
        if not session_logs:
            print("action-value-report requires at least one --session-log")
            sys.exit(1)
        runner = BenchmarkRunner(Config())
        report = runner.run_action_value_report_from_logs(session_logs)
        runner.print_action_value_report(report)
        action_value_feedback = runner.action_value_feedback(report)
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump({
                    "log_count": report.log_count,
                    "ready_log_count": report.ready_log_count,
                    "action_count": report.action_count,
                    "success_count": report.success_count,
                    "failure_count": report.failure_count,
                    "unknown_outcome_count": report.unknown_outcome_count,
                    "signature_count": report.signature_count,
                    "success_rate": report.success_rate,
                    "failure_rate": report.failure_rate,
                    "failure_correction_pair_count": report.failure_correction_pair_count,
                    "state_transition_count": report.state_transition_count,
                    "positive_transition_count": report.positive_transition_count,
                    "negative_transition_count": report.negative_transition_count,
                    "no_progress_transition_count": report.no_progress_transition_count,
                    "low_confidence_transition_count": report.low_confidence_transition_count,
                    "action_local_transition_count": report.action_local_transition_count,
                    "next_observation_transition_count": report.next_observation_transition_count,
                    "shared_observation_transition_count": report.shared_observation_transition_count,
                    "wide_observation_gap_transition_count": report.wide_observation_gap_transition_count,
                    "missing_transition_window_count": report.missing_transition_window_count,
                    "transition_window_diagnostics": action_value_feedback.get("transition_window_diagnostics", {}),
                    "action_value_feedback": action_value_feedback,
                    "errors": report.errors,
                    "cases": [asdict(case) for case in report.cases],
                }, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "knowledge-correction-report":
        from dataclasses import asdict
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        session_logs = getattr(args, "session_log", []) or []
        if not session_logs:
            print("knowledge-correction-report requires at least one --session-log")
            sys.exit(1)
        runner = BenchmarkRunner(Config())
        report = runner.run_knowledge_correction_report_from_logs(
            session_logs,
            min_failure_repeats=getattr(args, "min_failure_repeats", 2),
            max_failure_value_score=getattr(args, "max_failure_value_score", 0.35),
        )
        runner.print_knowledge_correction_report(report)
        knowledge_correction_feedback = runner.knowledge_correction_feedback(report)
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump({
                    "log_count": report.log_count,
                    "ready_log_count": report.ready_log_count,
                    "action_count": report.action_count,
                    "failure_action_count": report.failure_action_count,
                    "repeated_failure_signature_count": report.repeated_failure_signature_count,
                    "recovery_pair_count": report.recovery_pair_count,
                    "dependency_correction_count": report.dependency_correction_count,
                    "failure_action_memory_count": report.failure_action_memory_count,
                    "low_confidence_transition_count": report.low_confidence_transition_count,
                    "knowledge_correction_feedback": knowledge_correction_feedback,
                    "errors": report.errors,
                    "cases": [asdict(case) for case in report.cases],
                }, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "knowledge-correction-gate":
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        knowledge_correction_reports = getattr(args, "knowledge_correction_report", []) or []
        if not knowledge_correction_reports:
            print("knowledge-correction-gate requires at least one --knowledge-correction-report")
            sys.exit(1)
        runner = BenchmarkRunner(Config())
        report = runner.build_knowledge_correction_gate(
            knowledge_correction_report_paths=knowledge_correction_reports,
            target=getattr(args, "target", "planner_knowledge_correction_feedback"),
            min_ready_logs=getattr(args, "min_ready_logs", 1),
            min_corrections=getattr(args, "min_corrections", 1),
        )
        runner.print_knowledge_correction_gate_report(report)
        if getattr(args, "output", ""):
            output_dir = os.path.dirname(args.output)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        if report.get("readiness") in {"rejected", "error"}:
            sys.exit(1)
        return

    if args.command == "knowledge-correction-review-template":
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        report_paths = getattr(args, "knowledge_correction_report", []) or []
        if not report_paths:
            print("knowledge-correction-review-template requires at least one --knowledge-correction-report")
            sys.exit(1)
        runner = BenchmarkRunner(Config())
        templates = runner.build_knowledge_correction_review_templates(
            knowledge_correction_report_paths=report_paths,
        )
        error_count = sum(1 for template in templates if template.get("type") == "error")
        print("\nKnowledge Correction Review Template")
        print(f"  labels: {len(templates) - error_count}")
        print(f"  errors: {error_count}")
        for template in templates[:8]:
            if template.get("type") == "error":
                print(f"  [x] {template.get('error', '')}")
                continue
            print(
                f"  [?] {template.get('correction_type')} {template.get('key')} "
                f"readiness={template.get('readiness')}"
            )
        if getattr(args, "output", ""):
            output_dir = os.path.dirname(args.output)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                for template in templates:
                    f.write(json.dumps(template, ensure_ascii=False) + "\n")
            print(f"\nReview template saved to {args.output}")
        return

    if args.command == "knowledge-correction-review-validate":
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        runner = BenchmarkRunner(Config())
        report = runner.validate_knowledge_correction_review_labels(
            label_path=getattr(args, "label_file", ""),
            knowledge_correction_report_paths=getattr(args, "knowledge_correction_report", []) or [],
        )
        print("\nKnowledge Correction Review Validation")
        print(f"  labels: {report.get('valid_count', 0)}/{report.get('label_count', 0)} valid")
        print(
            "  readiness: "
            f"approved={report.get('approved_count', 0)}, "
            f"review={report.get('review_count', 0)}, "
            f"rejected={report.get('rejected_count', 0)}, "
            f"unknown={report.get('unknown_count', 0)}"
        )
        print(
            "  approved feedback: "
            f"dependency={report.get('approved_dependency_correction_count', 0)}, "
            f"failed_memories={report.get('approved_failure_action_memory_count', 0)}"
        )
        if report.get("invalid_readiness_count"):
            print(f"  invalid readiness: {report.get('invalid_readiness_count')}")
        if report.get("missing_match_count"):
            print(f"  missing targets: {report.get('missing_match_count')}")
        if report.get("duplicate_key_count"):
            print(f"  duplicate keys: {report.get('duplicate_key_count')}")
        for case in report.get("cases", [])[:8]:
            marker = "+" if case.get("ok") else "x"
            print(
                f"  [{marker}] {case.get('index')} {case.get('correction_type') or 'unknown'} "
                f"{case.get('key', '')}: {case.get('readiness') or 'invalid'}"
            )
            if case.get("errors"):
                print(f"      errors: {', '.join(case.get('errors', []))}")
            if case.get("warnings"):
                print(f"      warnings: {', '.join(case.get('warnings', []))}")
        if getattr(args, "output", ""):
            output_dir = os.path.dirname(args.output)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            print(f"\nValidation report saved to {args.output}")
        if not report.get("ok"):
            sys.exit(1)
        return

    if args.command == "knowledge-correction-ablation":
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        cases = _load_knowledge_correction_ablation_cases(args)
        config = Config(
            enable_knowledge_correction_context=not getattr(args, "no_knowledge_correction_context", False),
            knowledge_correction_feedback_paths=getattr(args, "knowledge_correction_feedback", []) or [],
            knowledge_correction_gate_paths=getattr(args, "knowledge_correction_gate", []) or [],
        )
        runner = BenchmarkRunner(config)
        report = runner.run_knowledge_correction_ablation(
            cases=cases,
            suite=getattr(args, "suite", "m1"),
            limit=getattr(args, "limit", 6),
        )
        runner.print_knowledge_correction_ablation_report(report)
        if getattr(args, "output", ""):
            runner.save_knowledge_correction_ablation_report(report, getattr(args, "output", ""))
            print(f"\nReport saved to {args.output}")
        if report.get("readiness") in {"rejected", "error"}:
            sys.exit(1)
        return

    if args.command == "action-value-transition-gate":
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        action_value_reports = getattr(args, "action_value_report", []) or []
        if not action_value_reports:
            print("action-value-transition-gate requires at least one --action-value-report")
            sys.exit(1)
        runner = BenchmarkRunner(Config())
        report = runner.build_action_value_transition_gate(
            action_value_report_paths=action_value_reports,
            target=getattr(args, "target", "action_value_transition_feedback"),
            min_trusted_items=getattr(args, "min_trusted_items", 1),
            min_trusted_transitions=getattr(args, "min_trusted_transitions", 1),
            min_transition_confidence=getattr(args, "min_transition_confidence", 0.75),
            max_low_confidence_rate=getattr(args, "max_low_confidence_rate", 0.25),
            max_item_low_confidence_rate=getattr(args, "max_item_low_confidence_rate", 0.25),
        )
        runner.print_action_value_transition_gate_report(report)
        if getattr(args, "output", ""):
            output_dir = os.path.dirname(args.output)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        if report.get("readiness") in {"rejected", "error"}:
            sys.exit(1)
        return

    if args.command == "action-value-transition-evaluator-report":
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        action_value_reports = getattr(args, "action_value_report", []) or []
        session_logs = getattr(args, "session_log", []) or []
        if not action_value_reports and not session_logs:
            print("action-value-transition-evaluator-report requires at least one --action-value-report or --session-log")
            sys.exit(1)
        evaluator = None
        if getattr(args, "llm_evaluator", False):
            from singularity.llm.provider import LLMProvider
            evaluator = LLMProvider(_llm_config_from_args(args))
        runner = BenchmarkRunner(Config(llm=_llm_config_from_args(args)))
        report = runner.build_action_value_transition_evaluator_report(
            action_value_report_paths=action_value_reports,
            session_log_paths=session_logs,
            evaluator=evaluator,
            limit=getattr(args, "limit", 40),
            min_transition_confidence=getattr(args, "min_transition_confidence", 0.75),
            min_evaluator_confidence=getattr(args, "min_evaluator_confidence", 0.65),
            min_evaluated_transitions=getattr(args, "min_evaluated_transitions", 1),
            min_label_agreement_rate=getattr(args, "min_label_agreement_rate", 0.75),
            max_avg_score_delta=getattr(args, "max_avg_score_delta", 0.25),
            max_large_score_delta_rate=getattr(args, "max_large_score_delta_rate", 0.25),
        )
        runner.print_action_value_transition_evaluator_report(report)
        if getattr(args, "output", ""):
            output_dir = os.path.dirname(args.output)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        if report.get("readiness") in {"rejected", "error"}:
            sys.exit(1)
        return

    if args.command == "self-evolution-gate":
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        self_evolution_reports = getattr(args, "self_evolution_report", []) or []
        verifier_reports = getattr(args, "verifier_report", []) or []
        counterexample_reports = getattr(args, "counterexample_report", []) or []
        if not self_evolution_reports and not verifier_reports and not counterexample_reports:
            print("self-evolution-gate requires at least one evidence report")
            sys.exit(1)
        runner = BenchmarkRunner(Config())
        report = runner.build_self_evolution_plan_repair_gate(
            self_evolution_report_paths=self_evolution_reports,
            verifier_report_paths=verifier_reports,
            counterexample_report_paths=counterexample_reports,
        )
        runner.print_self_evolution_gate_report(report)
        if getattr(args, "output", ""):
            output_dir = os.path.dirname(args.output)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        if report.get("readiness") in {"rejected", "error"}:
            sys.exit(1)
        return

    if args.command == "discovery-application-report":
        from dataclasses import asdict
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        session_logs = getattr(args, "session_log", []) or []
        if not session_logs:
            print("discovery-application-report requires at least one --session-log")
            sys.exit(1)
        runner = BenchmarkRunner(Config())
        report = runner.run_discovery_application_report_from_logs(session_logs)
        runner.print_discovery_application_report(report)
        discovery_feedback = runner.discovery_application_feedback(report)
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump({
                    "log_count": report.log_count,
                    "ready_log_count": report.ready_log_count,
                    "goal_count": report.goal_count,
                    "completed_goal_count": report.completed_goal_count,
                    "hypothesis_count": report.hypothesis_count,
                    "experiment_count": report.experiment_count,
                    "consolidation_count": report.consolidation_count,
                    "application_count": report.application_count,
                    "successful_application_count": report.successful_application_count,
                    "failed_application_count": report.failed_application_count,
                    "experiment_action_count": report.experiment_action_count,
                    "failed_experiment_action_count": report.failed_experiment_action_count,
                    "causal_memory_write_count": report.causal_memory_write_count,
                    "complete_loop_count": report.complete_loop_count,
                    "discovery_feedback": discovery_feedback,
                    "errors": report.errors,
                    "cases": [asdict(case) for case in report.cases],
                }, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "causal-evidence-report":
        from singularity.evaluation.causal_evidence import (
            build_causal_evidence_report,
            write_causal_evidence_report,
        )

        session_logs = getattr(args, "session_log", []) or []
        if not session_logs:
            print("causal-evidence-report requires at least one --session-log")
            sys.exit(1)
        report = build_causal_evidence_report(
            session_log_paths=session_logs,
            min_contrast_count=getattr(args, "min_contrast_count", 1),
            max_unresolved_counterexamples=getattr(args, "max_unresolved_counterexamples", 0),
            require_bias_mitigation=not getattr(args, "no_require_bias_mitigation", False),
        )
        _print_causal_evidence_report(report)
        if getattr(args, "output", ""):
            write_causal_evidence_report(report, args.output)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "causal-evidence-gate":
        from singularity.evaluation.causal_evidence import (
            build_causal_evidence_gate,
            write_causal_evidence_report,
        )

        report = build_causal_evidence_gate(
            causal_evidence_report_paths=getattr(args, "causal_evidence_report", []) or [],
            target=getattr(args, "target", "causal_summary_skill_promotion"),
            min_approved_reports=getattr(args, "min_approved_reports", 1),
            min_contrast_count=getattr(args, "min_contrast_count", 1),
            max_unresolved_counterexamples=getattr(args, "max_unresolved_counterexamples", 0),
            max_unmitigated_bias_risks=getattr(args, "max_unmitigated_bias_risks", 0),
        )
        _print_causal_evidence_gate(report)
        if getattr(args, "output", ""):
            write_causal_evidence_report(report, args.output)
            print(f"\nReport saved to {args.output}")
        if report.get("readiness") != "approved":
            sys.exit(2)
        return

    if args.command == "action-abstraction-report":
        from dataclasses import asdict
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        session_logs = getattr(args, "session_log", []) or []
        if not session_logs:
            print("action-abstraction-report requires at least one --session-log")
            sys.exit(1)
        runner = BenchmarkRunner(Config())
        report = runner.run_action_abstraction_report_from_logs(session_logs)
        runner.print_action_abstraction_report(report)
        action_abstraction_feedback = runner.action_abstraction_feedback(report)
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump({
                    "log_count": report.log_count,
                    "action_count": report.action_count,
                    "failed_action_count": report.failed_action_count,
                    "unknown_canonical_count": report.unknown_canonical_count,
                    "failed_mapping_count": report.failed_mapping_count,
                    "desktop_planned_count": report.desktop_planned_count,
                    "low_level_candidate_count": report.low_level_candidate_count,
                    "action_abstraction_feedback": action_abstraction_feedback,
                    "errors": report.errors,
                    "cases": [asdict(case) for case in report.cases],
                }, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "mixed-initiative-report":
        from singularity.evaluation.mixed_initiative import build_mixed_initiative_report

        def load_json_arg(json_text: str = "", json_path: str = "") -> dict:
            if json_path:
                with open(json_path, "r", encoding="utf-8-sig") as f:
                    return json.load(f)
            if json_text:
                return json.loads(json_text)
            return {}

        context = load_json_arg(
            getattr(args, "context_json", ""),
            getattr(args, "context_file", ""),
        )
        evidence = None
        if getattr(args, "evidence_json", "") or getattr(args, "evidence_file", ""):
            evidence = load_json_arg(
                getattr(args, "evidence_json", ""),
                getattr(args, "evidence_file", ""),
            )
        report = build_mixed_initiative_report(
            getattr(args, "goal", "Collect 20 oak logs"),
            template_id=getattr(args, "template", "auto"),
            context=context,
            evidence=evidence,
        )
        plan = report["plan"]
        print("\nMixed-Initiative Task Report")
        print(f"  template: {plan['template_id']} ({plan['category']})")
        print(f"  goal: {plan['goal']}")
        print(f"  preview: {plan['plan_preview']}")
        if plan["clarifying_questions"]:
            print(f"  clarification: {plan['clarifying_questions'][0]}")
        print(f"  unbound slots: {plan['unbound_slot_count']}")
        for subtask in plan["subtasks"]:
            marker = "?" if subtask["missing_parameters"] else "+"
            print(f"  [{marker}] {subtask['id']}: {subtask['name']}")
            if subtask["bound_parameters"]:
                params = ", ".join(f"{key}={value}" for key, value in subtask["bound_parameters"].items())
                print(f"      params: {params}")
            if subtask["missing_parameters"]:
                print(f"      missing: {', '.join(subtask['missing_parameters'])}")
            if subtask["clarifying_question"]:
                print(f"      question: {subtask['clarifying_question']}")
        if report["validation"]:
            summary = report["validation_summary"]
            print(
                "  validation: "
                f"passed={summary['passed']}, failed={summary['failed']}, "
                f"invalid={summary['invalid']}, unknown={summary['unknown']}"
            )
            for result in report["validation"]:
                marker = "+" if result["success"] else "x" if result["status"] == "invalid" else "-"
                print(f"  [{marker}] {result['subtask_id']}: {result['status']}")
                if result["evidence"]:
                    print(f"      evidence: {'; '.join(result['evidence'][:3])}")
                if result["missing"]:
                    print(f"      missing: {'; '.join(result['missing'][:3])}")
                if result["policy_violations"]:
                    details = [violation["detail"] for violation in result["policy_violations"][:3]]
                    print(f"      policy: {'; '.join(details)}")
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "mixed-initiative-variant-report":
        from singularity.evaluation.mixed_initiative import build_mixed_initiative_variant_report

        report = build_mixed_initiative_variant_report(
            case_paths=getattr(args, "case_file", []) or [],
            include_builtin=not getattr(args, "no_builtins", False),
            template_id=getattr(args, "template", "auto"),
        )
        print("\nMixed-Initiative Variant Report")
        print(f"  cases: {report.case_count}")
        print(f"  fully passed: {report.fully_passed_count}/{report.case_count}")
        print(f"  template matches: {report.template_match_count}/{report.case_count}")
        print(f"  slot matches: {report.slot_match_count}/{report.case_count}")
        print(f"  validation success: {report.validation_success_count}/{report.validation_checked_count}")
        print(f"  clarifications: {report.clarification_count}")
        for case in report.cases:
            marker = "+" if case.fully_passed else "x"
            expected = case.expected_template_id or "<none>"
            print(f"  [{marker}] {case.id}: {case.goal}")
            print(f"      template: expected={expected}, actual={case.actual_template_id}")
            if case.slot_mismatches:
                print(f"      slot mismatches: {'; '.join(case.slot_mismatches[:3])}")
            if case.needs_clarification:
                print(f"      clarification needed, unbound_slots={case.unbound_slot_count}")
            if case.validation_checked:
                status = "passed" if case.validation_success else "failed"
                print(
                    f"      validation: {status}, passed={case.validation_passed_count}, "
                    f"failed={case.validation_failed_count}, invalid={case.validation_invalid_count}, "
                    f"unknown={case.validation_unknown_count}"
                )
        for error in report.errors:
            print(f"  error: {error}")
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "mixed-initiative-review-queue":
        from singularity.evaluation.mixed_initiative import build_mixed_initiative_review_queue

        trace_reports = getattr(args, "trace_report", []) or []
        session_logs = getattr(args, "session_log", []) or []
        if not trace_reports and not session_logs:
            print("mixed-initiative-review-queue requires --trace-report or --session-log")
            sys.exit(1)
        report = build_mixed_initiative_review_queue(
            trace_report_paths=trace_reports,
            session_log_paths=session_logs,
            template_id=getattr(args, "template", "auto"),
        )
        print("\nMixed-Initiative Review Queue")
        print(f"  items: {report.item_count}")
        print(f"  high priority: {report.high_priority_count}")
        if report.decision_counts:
            parts = [f"{key}={value}" for key, value in sorted(report.decision_counts.items())]
            print(f"  decisions: {', '.join(parts)}")
        for item in report.items:
            print(f"  [{item.priority}] {item.id}")
            print(f"      {item.target_type}:{item.target_id} -> {item.decision}")
            if item.source_goals:
                print(f"      examples: {', '.join(item.source_goals[:3])}")
            if item.action_items:
                print(f"      next: {item.action_items[0]}")
        for error in report.errors:
            print(f"  error: {error}")
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)
            print(f"\nQueue saved to {args.output}")
        return

    if args.command == "mixed-initiative-review-plan":
        from singularity.evaluation.mixed_initiative import build_mixed_initiative_review_experiment_plan

        review_queues = getattr(args, "review_queue", []) or []
        trace_reports = getattr(args, "trace_report", []) or []
        session_logs = getattr(args, "session_log", []) or []
        if not review_queues and not trace_reports and not session_logs:
            print("mixed-initiative-review-plan requires --review-queue, --trace-report, or --session-log")
            sys.exit(1)
        report = build_mixed_initiative_review_experiment_plan(
            review_queue_paths=review_queues,
            trace_report_paths=trace_reports,
            session_log_paths=session_logs,
            template_id=getattr(args, "template", "auto"),
        )
        print("\nMixed-Initiative Review Experiment Plan")
        print(f"  cases: {report.case_count}")
        print(f"  ready: {report.ready_count}")
        print(f"  high priority: {report.high_priority_count}")
        if report.route_counts:
            parts = [f"{key}={value}" for key, value in sorted(report.route_counts.items())]
            print(f"  routes: {', '.join(parts)}")
        for case in report.cases:
            marker = "+" if case.ready else "!"
            print(f"  {marker} [{case.priority}] {case.id}")
            print(f"      {case.route}: {case.target_type}:{case.target_id} -> {case.decision}")
            if case.source_goals:
                print(f"      examples: {', '.join(case.source_goals[:3])}")
            if case.missing_inputs:
                print(f"      missing: {', '.join(case.missing_inputs)}")
            if case.recommended_commands:
                print(f"      command: {case.recommended_commands[0]}")
        for error in report.errors:
            print(f"  error: {error}")
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)
            print(f"\nExperiment plan saved to {args.output}")
        return

    if args.command == "mixed-initiative-review-label-template":
        from singularity.evaluation.mixed_initiative import build_mixed_initiative_review_label_templates

        review_plans = getattr(args, "review_plan", []) or []
        review_queues = getattr(args, "review_queue", []) or []
        trace_reports = getattr(args, "trace_report", []) or []
        session_logs = getattr(args, "session_log", []) or []
        if not review_plans and not review_queues and not trace_reports and not session_logs:
            print("mixed-initiative-review-label-template requires --review-plan, --review-queue, --trace-report, or --session-log")
            sys.exit(1)
        templates = build_mixed_initiative_review_label_templates(
            review_plan_paths=review_plans,
            review_queue_paths=review_queues,
            trace_report_paths=trace_reports,
            session_log_paths=session_logs,
            template_id=getattr(args, "template", "auto"),
        )
        lines = [json.dumps(template, ensure_ascii=False, default=str) for template in templates]
        if getattr(args, "output", ""):
            output_dir = os.path.dirname(args.output)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                for line in lines:
                    f.write(line + "\n")
            print(f"Mixed-initiative review label template saved to {args.output} ({len(lines)} records)")
        else:
            for line in lines:
                print(line)
        return

    if args.command == "mixed-initiative-review-label-validate":
        from singularity.evaluation.mixed_initiative import validate_mixed_initiative_review_labels

        label_file = getattr(args, "label_file", "")
        if not label_file:
            print("mixed-initiative-review-label-validate requires --label-file")
            sys.exit(1)
        report = validate_mixed_initiative_review_labels(
            label_file,
            review_plan_paths=getattr(args, "review_plan", []) or [],
        )
        print("\nMixed-Initiative Review Label Validation")
        print(f"  labels: {report.ok_count}/{report.label_count} ok")
        print(f"  approved: {report.approved_count}")
        print(f"  rejected: {report.rejected_count}")
        print(f"  unknown: {report.unknown_count}")
        print(f"  executable approved cases: {report.executable_count}")
        if report.approved_route_counts:
            parts = [f"{key}={value}" for key, value in sorted(report.approved_route_counts.items())]
            print(f"  approved routes: {', '.join(parts)}")
        for case in report.cases:
            marker = "+" if case.ok else "x"
            label = case.case_id or case.queue_item_id or case.target_id or f"record-{case.index}"
            print(f"  [{marker}] {case.index} {case.route or 'unknown_route'}: {label}")
            print(f"      readiness={case.readiness or 'invalid'}, commands={len(case.recommended_commands)}")
            if case.errors:
                print(f"      errors: {', '.join(case.errors)}")
            if case.warnings:
                print(f"      warnings: {', '.join(case.warnings)}")
        for error in report.errors:
            print(f"  error: {error}")
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        if not report.ok:
            sys.exit(1)
        return

    if args.command == "mixed-initiative-review-execute":
        from singularity.evaluation.mixed_initiative import execute_mixed_initiative_review_labels

        label_file = getattr(args, "label_file", "")
        if not label_file:
            print("mixed-initiative-review-execute requires --label-file")
            sys.exit(1)
        report = execute_mixed_initiative_review_labels(
            label_file,
            review_plan_paths=getattr(args, "review_plan", []) or [],
            output_dir=getattr(args, "output_dir", "") or "",
            dry_run=getattr(args, "dry_run", False),
        )
        print("\nMixed-Initiative Review Execution")
        print(f"  dry run: {report.dry_run}")
        print(f"  cases: {report.case_count}")
        print(f"  executed: {report.executed_count}")
        print(f"  dry-run cases: {report.dry_run_count}")
        print(f"  skipped: {report.skipped_count}")
        print(f"  failed: {report.failed_count}")
        if report.route_counts:
            parts = [f"{key}={value}" for key, value in sorted(report.route_counts.items())]
            print(f"  routes: {', '.join(parts)}")
        for case in report.cases:
            marker = "+" if case.status in {"executed", "dry_run"} else ("-" if case.status == "skipped" else "x")
            print(f"  [{marker}] {case.status} {case.route}: {case.case_id or case.target_id}")
            if case.artifact_summaries:
                summary = ", ".join(f"{key}={value}" for key, value in sorted(case.artifact_summaries.items())[:6])
                print(f"      summary: {summary}")
            for artifact_path in case.artifact_paths:
                print(f"      artifact: {artifact_path}")
            if case.errors:
                print(f"      errors: {', '.join(case.errors)}")
        for error in report.errors:
            print(f"  error: {error}")
        if getattr(args, "output", ""):
            output_dir = os.path.dirname(args.output)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        if not report.ok:
            sys.exit(1)
        return

    if args.command == "mixed-initiative-policy-patch":
        from singularity.evaluation.mixed_initiative import build_mixed_initiative_policy_patch

        execution_reports = getattr(args, "execution_report", []) or []
        artifacts = getattr(args, "artifact", []) or []
        if not execution_reports and not artifacts:
            print("mixed-initiative-policy-patch requires --execution-report or --artifact")
            sys.exit(1)
        patch = build_mixed_initiative_policy_patch(
            execution_report_paths=execution_reports,
            artifact_paths=artifacts,
        )
        print("\nMixed-Initiative Policy Patch")
        print(f"  ok: {patch.ok}")
        print(f"  artifacts: {patch.artifact_count}")
        print(f"  action policy hints: {patch.action_policy_hint_count}")
        print(f"  mixed policy hints: {patch.mixed_policy_hint_count}")
        print(f"  template updates: {patch.template_update_count}")
        action_hints = patch.action_policy_feedback.get("policy_hints", [])
        if action_hints:
            hints = [
                f"{item.get('action_type')}->{item.get('preferred_control')}"
                for item in action_hints[:6]
                if isinstance(item, dict)
            ]
            print(f"  action hint sample: {', '.join(hints)}")
        mixed_hints = patch.mixed_initiative_feedback.get("policy_hints", [])
        if mixed_hints:
            hints = [
                f"{item.get('policy')}:{item.get('template_id') or item.get('candidate_id') or 'trace'}"
                for item in mixed_hints[:6]
                if isinstance(item, dict)
            ]
            print(f"  mixed hint sample: {', '.join(hints)}")
        for error in patch.errors:
            print(f"  error: {error}")
        if getattr(args, "output", ""):
            output_dir = os.path.dirname(args.output)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(patch.to_dict(), f, indent=2, ensure_ascii=False)
            print(f"\nPolicy patch saved to {args.output}")
        if not patch.ok:
            sys.exit(1)
        return

    if args.command == "mixed-initiative-policy-ablation":
        from singularity.evaluation.mixed_initiative import build_mixed_initiative_policy_ablation

        patch_paths = getattr(args, "policy_patch", []) or []
        if not patch_paths:
            print("mixed-initiative-policy-ablation requires at least one --policy-patch")
            sys.exit(1)
        actions = []
        for raw_action in getattr(args, "action", []) or []:
            raw_action = str(raw_action or "").strip()
            if not raw_action:
                continue
            if raw_action.startswith("{"):
                actions.append(json.loads(raw_action))
            else:
                actions.append({"id": raw_action, "type": raw_action, "parameters": {}})
        report = build_mixed_initiative_policy_ablation(
            patch_paths=patch_paths,
            actions=actions,
            template_ids=getattr(args, "template_id", []) or [],
            candidate_ids=getattr(args, "candidate_id", []) or [],
            allow_planned_backend=getattr(args, "allow_planned_backend", False),
        )
        print("\nMixed-Initiative Policy Ablation")
        print(f"  ok: {report.ok}")
        print(f"  patches: {report.patch_count}")
        print(f"  action decisions changed: {report.action_changed_count}/{len(report.action_cases)}")
        print(f"  template decisions changed: {report.template_changed_count}/{len(report.template_cases)}")
        print(f"  candidate decisions changed: {report.candidate_changed_count}/{len(report.candidate_cases)}")
        if report.action_cases:
            print("  action cases:")
            for case in report.action_cases[:8]:
                base = case.baseline
                patched = case.patched
                marker = "*" if case.changed else "-"
                print(
                    f"    {marker} {case.id}: "
                    f"{base.get('backend')}/{base.get('preferred_control')} -> "
                    f"{patched.get('backend')}/{patched.get('preferred_control')}"
                )
                if patched.get("fallback_reason"):
                    print(f"      fallback: {patched.get('fallback_reason')}")
        review_cases = list(report.template_cases) + list(report.candidate_cases)
        if review_cases:
            print("  review cases:")
            for case in review_cases[:8]:
                marker = "*" if case.changed else "-"
                print(
                    f"    {marker} {case.target_type}:{case.target_id}: "
                    f"{case.baseline.get('decision')} -> {case.patched.get('decision')}"
                )
        if report.patched_recommendations:
            print("  patched recommendations:")
            for item in report.patched_recommendations[:8]:
                print(
                    f"    - {item.get('decision')}[{item.get('priority', 'normal')}] "
                    f"{item.get('target_type')}:{item.get('target_id')}"
                )
        for error in report.errors:
            print(f"  error: {error}")
        if getattr(args, "output", ""):
            output_dir = os.path.dirname(args.output)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        if not report.ok:
            sys.exit(1)
        return

    if args.command == "mixed-initiative-policy-gate":
        from singularity.evaluation.mixed_initiative import build_mixed_initiative_policy_gate

        policy_ablation_paths = getattr(args, "policy_ablation", []) or []
        benchmark_ablation_paths = getattr(args, "benchmark_ablation", []) or []
        collab_ablation_paths = getattr(args, "collab_ablation", []) or []
        if not policy_ablation_paths and not benchmark_ablation_paths and not collab_ablation_paths:
            print("mixed-initiative-policy-gate requires at least one ablation report")
            sys.exit(1)
        report = build_mixed_initiative_policy_gate(
            policy_ablation_paths=policy_ablation_paths,
            benchmark_ablation_paths=benchmark_ablation_paths,
            collaboration_ablation_paths=collab_ablation_paths,
        )
        print("\nMixed-Initiative Policy Gate")
        print(f"  readiness: {report.readiness}")
        print(f"  decision: {report.decision}")
        print(f"  reason: {report.reason}")
        print(f"  evidence: {report.evidence_count}, warnings: {report.warning_count}, regressions: {report.regression_count}")
        for check in report.checks:
            marker = "+" if check.get("status") == "pass" else "!" if check.get("status") == "warn" else "x"
            print(f"  [{marker}] {check.get('source')}: {check.get('detail')}")
        for error in report.errors:
            print(f"  error: {error}")
        if getattr(args, "output", ""):
            output_dir = os.path.dirname(args.output)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        if report.readiness == "rejected":
            sys.exit(1)
        return

    if args.command == "mixed-initiative-trace-report":
        from singularity.evaluation.mixed_initiative import build_mixed_initiative_trace_report

        session_logs = getattr(args, "session_log", []) or []
        if not session_logs:
            print("mixed-initiative-trace-report requires at least one --session-log")
            sys.exit(1)
        report = build_mixed_initiative_trace_report(
            session_logs,
            template_id=getattr(args, "template", "auto"),
        )
        print("\nMixed-Initiative Trace Report")
        print(f"  logs: {report.log_count}")
        print(f"  goals: {report.goal_count}")
        print(f"  goals needing clarification: {report.needs_clarification_count}")
        print(f"  unbound slots: {report.unbound_slot_count}")
        print(f"  unsupported template goals: {report.unsupported_goal_count}")
        print(f"  validator success: {report.validator_success_count}/{report.goal_count}")
        print(
            "  actions: "
            f"total={report.action_count}, valid={report.valid_action_count}, "
            f"invalid={report.invalid_action_count}, successful={report.successful_action_count}, "
            f"failed={report.failed_action_count}"
        )
        print(
            "  action success rates: "
            f"raw={report.action_success_rate:.2f}, valid_only={report.valid_action_success_rate:.2f}"
        )
        print(f"  policy violations: {report.policy_violation_count}")
        if report.agreement_counts:
            parts = [f"{key}={value}" for key, value in sorted(report.agreement_counts.items())]
            print(f"  agreement: {', '.join(parts)}")
        if report.template_action_metrics:
            print("  template action metrics:")
            for item in report.template_action_metrics:
                print(
                    f"    - {item['template_id']}: actions={item['action_count']}, "
                    f"valid={item['valid_action_count']}, invalid={item['invalid_action_count']}, "
                    f"valid_success_rate={item['valid_action_success_rate']:.2f}"
                )
        feedback = report.mixed_initiative_feedback
        if feedback.get("policy_hints"):
            print("  feedback hints:")
            for hint in feedback["policy_hints"][:6]:
                target = hint.get("template_id") or hint.get("candidate_id") or "trace"
                print(
                    f"    - {hint['policy']}[{hint.get('priority', 'low')}] "
                    f"{target}: {hint.get('reason', '')}"
                )
        if report.mixed_initiative_recommendations:
            print("  recommendations:")
            for item in report.mixed_initiative_recommendations[:6]:
                print(
                    f"    - {item['decision']}[{item.get('priority', 'normal')}] "
                    f"{item['target_type']}:{item['target_id']}"
                )
        if report.template_candidates:
            print("  template candidates:")
            for candidate in report.template_candidates[:6]:
                examples = ", ".join(candidate["example_goals"][:2])
                print(
                    f"    - {candidate['candidate_id']} x{candidate['count']} "
                    f"({candidate['category']}): {examples}"
                )
        for case in report.cases:
            marker = "+" if case.validator_success else "x" if case.policy_violation_count else "~"
            print(f"  [{marker}] {case.goal}")
            print(f"      template={case.template_id}, preview={case.plan_preview}")
            print(
                f"      subtasks={case.validation_passed_count}/{case.subtask_count} passed, "
                f"failed={case.validation_failed_count}, invalid={case.validation_invalid_count}, "
                f"unknown={case.validation_unknown_count}"
            )
            if case.action_count:
                print(
                    f"      actions: total={case.action_count}, valid={case.valid_action_count}, "
                    f"invalid={case.invalid_action_count}, successful={case.successful_action_count}, "
                    f"failed={case.failed_action_count}"
                )
            if case.needs_clarification and case.clarifying_questions:
                print(f"      clarification: {case.clarifying_questions[0]}")
            if case.goal_verification_status:
                print(
                    f"      goal verifier: status={case.goal_verification_status}, "
                    f"accepted={case.goal_verification_accepted}"
                )
            if case.template_candidate:
                print(f"      template candidate: {case.template_candidate.get('candidate_id')}")
            print(f"      agreement: {case.agreement}")
        for error in report.errors:
            print(f"  error: {error}")
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "visual-review-pipeline":
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        session_logs = getattr(args, "session_log", []) or []
        if not session_logs:
            print("visual-review-pipeline requires at least one --session-log")
            sys.exit(1)
        runner = BenchmarkRunner(Config(llm=_llm_config_from_args(args)))
        report = runner.run_visual_review_pipeline(
            session_logs,
            mode=getattr(args, "mode", "both"),
            label_file=getattr(args, "label_file", ""),
            promotion_critic=_promotion_critic_from_args(args),
            goal_critic=_goal_critic_from_args(args),
            include_causal_summaries=getattr(args, "causal_summaries", False),
            include_failure_corrections=getattr(args, "failure_corrections", False),
            run_ablations=getattr(args, "run_ablations", False),
        )
        runner.print_visual_review_pipeline_report(report)
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(runner.visual_review_pipeline_report_to_dict(report), f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        if report.label_validation is not None and not report.label_validation.ok:
            sys.exit(1)
        return

    if args.command == "policy-skill-ablation":
        from dataclasses import asdict
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        runner = BenchmarkRunner(Config())
        report = runner.run_policy_skill_ablation(
            skill_storage_path=getattr(args, "skill_storage_path", ""),
            include_builtin=not getattr(args, "no_builtin", False),
        )
        runner.print_policy_skill_ablation_report(report)
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump({
                    "helped_count": report.helped_count,
                    "cases": [asdict(case) for case in report.cases],
                }, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "visual-action-ablation":
        from dataclasses import asdict
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        runner = BenchmarkRunner(Config())
        session_logs = getattr(args, "session_log", []) or []
        if session_logs:
            report = runner.run_visual_action_ablation_from_logs(
                session_logs,
                max_cases_per_log=getattr(args, "max_cases_per_log", 20),
                include_builtin=getattr(args, "include_builtin", False),
            )
        else:
            report = runner.run_visual_action_ablation()
        runner.print_visual_action_ablation_report(report)
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump({
                    "type": "visual_action_ablation_report",
                    "schema_version": 1,
                    "passed_count": report.passed_count,
                    "changed_count": report.changed_count,
                    "helped_count": report.helped_count,
                    "cases": [asdict(case) for case in report.cases],
                }, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    # Build config from args
    host = getattr(args, "host", "localhost") or "localhost"
    port = getattr(args, "port", 25565) or 25565
    username = getattr(args, "username", "Singularity") or "Singularity"
    bridge_host = getattr(args, "bridge_host", "127.0.0.1") or "127.0.0.1"
    bridge_port = getattr(args, "bridge_port", 3000) or 3000
    config = Config(
        bot=BotConfig(host=host, port=port, username=username, bridge_host=bridge_host, bridge_port=bridge_port),
        llm=_llm_config_from_args(args),
        enable_goal_critic=profile_bool_arg(args, "goal_critic", runtime_profiles, "enable_goal_critic", "goal_critic"),
        goal_critic_gate_paths=merge_arg_profile_list(args, "goal_critic_gate", runtime_profiles, "goal_critic_gate_paths"),
        enforce_memory_write_gate=profile_bool_arg(args, "enforce_memory_write_gate", runtime_profiles, "enforce_memory_write_gate", "memory_write_gate"),
        memory_promptware_gate_paths=merge_arg_profile_list(args, "memory_promptware_gate", runtime_profiles, "memory_promptware_gate_paths"),
        enable_weighted_memory_retrieval=profile_bool_arg(args, "enable_weighted_memory_retrieval", runtime_profiles, "enable_weighted_memory_retrieval", "weighted_memory_retrieval"),
        memory_attribution_gate_paths=merge_arg_profile_list(args, "memory_attribution_gate", runtime_profiles, "memory_attribution_gate_paths"),
        enable_plan_cache=profile_bool_arg(args, "enable_plan_cache", runtime_profiles, "enable_plan_cache", "plan_cache"),
        plan_cache_paths=merge_arg_profile_list(args, "plan_cache", runtime_profiles, "plan_cache_paths"),
        plan_cache_gate_paths=merge_arg_profile_list(args, "plan_cache_gate", runtime_profiles, "plan_cache_gate_paths"),
        plan_cache_min_confidence=getattr(args, "plan_cache_min_confidence", 0.75),
        enable_task_continuity_context=not getattr(args, "no_task_continuity_context", False),
        enable_bounded_planning_context=not getattr(args, "no_bounded_planning_context", False),
        planning_memory_read_limit_chars=max(1, int(getattr(args, "planning_memory_read_limit", 600) or 600)),
        planning_memory_cycle_limit_chars=max(1, int(getattr(args, "planning_memory_cycle_limit", 2400) or 2400)),
        enable_skill_memory_context=not getattr(args, "no_skill_memory_context", False),
        enable_coaching_policy=not getattr(args, "no_coaching_policy", False),
        coach_style=profile_str_arg(args, "coach_style", runtime_profiles, "coach_style", default=""),
        coach_style_ablation_paths=merge_arg_profile_list(args, "coach_style_ablation", runtime_profiles, "coach_style_ablation_paths"),
        coach_style_gate_paths=merge_arg_profile_list(args, "coach_style_gate", runtime_profiles, "coach_style_gate_paths"),
        enable_vision_analysis=not getattr(args, "no_vision_analysis", False),
        enable_visual_action_grounding=not getattr(args, "no_visual_action_grounding", False),
        mixed_policy_patch_paths=merge_arg_profile_list(args, "mixed_policy_patch", runtime_profiles, "mixed_policy_patch_paths"),
        mixed_policy_gate_paths=merge_arg_profile_list(args, "mixed_policy_gate", runtime_profiles, "mixed_policy_gate_paths"),
        self_evolution_feedback_paths=merge_arg_profile_list(args, "self_evolution_feedback", runtime_profiles, "self_evolution_feedback_paths"),
        world_model_feedback_paths=merge_arg_profile_list(args, "world_model_feedback", runtime_profiles, "world_model_feedback_paths"),
        world_model_gate_paths=merge_arg_profile_list(args, "world_model_gate", runtime_profiles, "world_model_gate_paths"),
        enable_knowledge_correction_context=not getattr(args, "no_knowledge_correction_context", False),
        knowledge_correction_feedback_paths=merge_arg_profile_list(args, "knowledge_correction_feedback", runtime_profiles, "knowledge_correction_feedback_paths"),
        knowledge_correction_gate_paths=merge_arg_profile_list(args, "knowledge_correction_gate", runtime_profiles, "knowledge_correction_gate_paths"),
        enable_task_precondition_context=not getattr(args, "no_task_precondition_context", False),
        task_precondition_feedback_paths=merge_arg_profile_list(args, "task_precondition_feedback", runtime_profiles, "task_precondition_feedback_paths"),
        task_precondition_gate_paths=merge_arg_profile_list(args, "task_precondition_gate", runtime_profiles, "task_precondition_gate_paths"),
        action_value_feedback_paths=merge_arg_profile_list(args, "action_value_feedback", runtime_profiles, "action_value_feedback_paths"),
        action_value_transition_gate_paths=merge_arg_profile_list(args, "action_value_transition_gate", runtime_profiles, "action_value_transition_gate_paths"),
        action_value_transition_evaluator_report_paths=merge_arg_profile_list(args, "action_value_transition_evaluator_report", runtime_profiles, "action_value_transition_evaluator_report_paths"),
        skill_memory_quality_feedback_paths=merge_arg_profile_list(args, "skill_memory_quality_feedback", runtime_profiles, "skill_memory_quality_feedback_paths"),
        skill_memory_quality_gate_paths=merge_arg_profile_list(args, "skill_memory_quality_gate", runtime_profiles, "skill_memory_quality_gate_paths"),
        skill_runtime_default_gate_paths=merge_arg_profile_list(args, "skill_runtime_default_gate", runtime_profiles, "skill_runtime_default_gate_paths"),
        enable_screenshot_capture=profile_bool_arg(args, "capture_screenshots", runtime_profiles, "enable_screenshot_capture", "capture_screenshots"),
        screenshot_dir=profile_str_arg(args, "screenshot_dir", runtime_profiles, "screenshot_dir", default="logs/screenshots"),
        screenshot_min_interval_s=getattr(args, "screenshot_min_interval", 2.0),
    )

    if args.command == "capability-evidence-report":
        from dataclasses import asdict
        from singularity.evaluation.benchmark_runner import BenchmarkRunner
        from singularity.evaluation.capability_evidence import (
            build_capability_evidence_report,
            print_capability_evidence_report,
            write_capability_evidence_report,
        )

        runtime_evidence = {}
        if getattr(args, "check_runtime", False):
            preflight_report = BenchmarkRunner(config).preflight(check_network=True)
            runtime_evidence = {**asdict(preflight_report), "ok": preflight_report.ok}
        benchmark_paths = getattr(args, "benchmark_results", []) or []
        if not benchmark_paths and os.path.isfile("logs/benchmarks/benchmark_results.json"):
            benchmark_paths = ["logs/benchmarks/benchmark_results.json"]
        phase_evidence_paths = {
            "M3": getattr(args, "m3_evidence", []) or [],
            "M5": getattr(args, "m5_evidence", []) or [],
            "M6": getattr(args, "m6_evidence", []) or [],
        }
        default_phase_evidence_paths = {
            "M3": [
                "logs/benchmarks/continual_learning_current.json",
                "logs/benchmarks/task_stream_transfer_gate_current.json",
            ],
            "M5": [
                "logs/benchmarks/exploration_trace_current.json",
                "logs/benchmarks/world_model_gate_current.json",
            ],
            "M6": [
                "logs/benchmarks/visual_trace_current.json",
                "logs/benchmarks/visual_action_ablation_current.json",
            ],
        }
        for phase_id, default_paths in default_phase_evidence_paths.items():
            if not phase_evidence_paths[phase_id]:
                phase_evidence_paths[phase_id] = [
                    path for path in default_paths if os.path.isfile(path)
                ]
        report = build_capability_evidence_report(
            benchmark_result_paths=benchmark_paths,
            status_path=getattr(args, "status_file", "workspace/STATUS.md"),
            source_root=getattr(args, "source_root", "."),
            min_repeats=getattr(args, "min_repeats", 3),
            runtime_evidence=runtime_evidence,
            phase_evidence_paths=phase_evidence_paths,
        )
        print_capability_evidence_report(report)
        if getattr(args, "output", ""):
            write_capability_evidence_report(report, args.output)
            print(f"\nReport saved to {args.output}")
        if getattr(args, "strict", False) and report.get("readiness") != "approved":
            sys.exit(1)

    elif args.command == "preflight":
        from singularity.evaluation.benchmark_runner import BenchmarkRunner
        runner = BenchmarkRunner(config)
        report = runner.preflight(
            check_network=not getattr(args, "skip_network", False),
            check_screenshot_renderer=getattr(args, "screenshot_renderer", False),
        )
        runner.print_preflight(report)
        if not report.ok:
            sys.exit(1)

    elif args.command == "screenshot-smoke-test":
        from dataclasses import asdict
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        runner = BenchmarkRunner(config)
        report = runner.run_screenshot_smoke_test(getattr(args, "screenshot_path", ""))
        runner.print_screenshot_smoke_report(report)
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump({
                    **asdict(report),
                    "ok": report.ok,
                }, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        if not report.ok:
            sys.exit(1)

    elif args.command == "benchmark":
        from singularity.evaluation.benchmark_runner import BenchmarkRunner
        runner = BenchmarkRunner(config)
        if getattr(args, "preflight", False):
            report = runner.preflight(
                check_screenshot_renderer=config.enable_screenshot_capture,
            )
            runner.print_preflight(report)
            if not report.ok:
                sys.exit(1)
        runtime_profile_suite_paths = getattr(args, "runtime_profile_suite_report", []) or []
        if (
            getattr(args, "runtime_profile_suite_preflight", False)
            or runtime_profile_suite_paths
            or getattr(args, "runtime_profile", [])
        ):
            report = runner.run_runtime_profile_suite_preflight(
                suite=args.suite,
                profile_paths=getattr(args, "runtime_profile", []) or [],
                suite_report_paths=runtime_profile_suite_paths,
                required_profiles=getattr(args, "runtime_profile_suite_required_profile", []) or [],
            )
            runner.print_runtime_profile_suite_preflight_report(report)
            runtime_profile_suite_preflight_output = getattr(args, "runtime_profile_suite_preflight_output", "") or ""
            if runtime_profile_suite_preflight_output:
                runner.save_runtime_profile_suite_preflight_report(report, runtime_profile_suite_preflight_output)
            if not report.get("ready"):
                sys.exit(1)
        quality_feedback_paths = config.skill_memory_quality_feedback_paths
        if getattr(args, "skill_memory_quality_preflight", False) or quality_feedback_paths:
            report = runner.run_skill_memory_quality_preflight(suite=args.suite)
            runner.print_skill_memory_quality_preflight_report(report)
            quality_preflight_output = getattr(args, "skill_memory_quality_preflight_output", "") or ""
            if quality_preflight_output:
                runner.save_skill_memory_quality_preflight_report(report, quality_preflight_output)
            if not report.get("ready"):
                sys.exit(1)
        runtime_default_gate_paths = config.skill_runtime_default_gate_paths
        if getattr(args, "skill_runtime_default_preflight", False) or runtime_default_gate_paths:
            report = runner.run_skill_runtime_default_preflight(suite=args.suite)
            runner.print_skill_runtime_default_preflight_report(report)
            runtime_default_preflight_output = getattr(args, "skill_runtime_default_preflight_output", "") or ""
            if runtime_default_preflight_output:
                runner.save_skill_runtime_default_preflight_report(report, runtime_default_preflight_output)
            if not report.get("ready"):
                sys.exit(1)
        knowledge_correction_feedback_paths = config.knowledge_correction_feedback_paths
        if getattr(args, "knowledge_correction_preflight", False) or knowledge_correction_feedback_paths:
            report = runner.run_knowledge_correction_preflight(suite=args.suite)
            runner.print_knowledge_correction_preflight_report(report)
            knowledge_correction_preflight_output = getattr(args, "knowledge_correction_preflight_output", "") or ""
            if knowledge_correction_preflight_output:
                runner.save_knowledge_correction_preflight_report(report, knowledge_correction_preflight_output)
            if not report.get("ready"):
                sys.exit(1)
        transition_gate_paths = config.action_value_transition_gate_paths
        transition_evaluator_paths = config.action_value_transition_evaluator_report_paths
        if (
            getattr(args, "action_value_transition_preflight", False)
            or transition_gate_paths
            or transition_evaluator_paths
        ):
            report = runner.run_action_value_transition_preflight(
                suite=args.suite,
                require_evaluator_report=getattr(args, "require_action_value_transition_evaluator_report", False),
            )
            runner.print_action_value_transition_preflight_report(report)
            transition_preflight_output = getattr(args, "action_value_transition_preflight_output", "") or ""
            if transition_preflight_output:
                runner.save_action_value_transition_preflight_report(report, transition_preflight_output)
            if not report.get("ready"):
                sys.exit(1)
        coach_style_paths = config.coach_style_ablation_paths
        coach_gate_paths = config.coach_style_gate_paths
        coach_style = config.coach_style
        if (
            getattr(args, "coach_style_preflight", False)
            or coach_style_paths
            or coach_gate_paths
            or (coach_style and not getattr(args, "no_coaching_policy", False))
        ):
            report = runner.run_coach_style_preflight(
                suite=args.suite,
                require_goal_change=getattr(args, "require_coach_style_goal_change", False),
            )
            runner.print_coach_style_preflight_report(report)
            coach_preflight_output = getattr(args, "coach_style_preflight_output", "") or ""
            if coach_preflight_output:
                runner.save_coach_style_preflight_report(report, coach_preflight_output)
            if not report.get("ready"):
                sys.exit(1)
        if getattr(args, "policy_skill_ablation", False):
            report = runner.run_policy_skill_benchmark_ablation(suite=args.suite)
            runner.print_policy_skill_benchmark_ablation_report(report)
            runner.save_policy_skill_benchmark_ablation_report(report, args.output)
            return
        if getattr(args, "skill_memory_ablation", False):
            report = runner.run_skill_memory_benchmark_ablation(suite=args.suite)
            runner.print_skill_memory_benchmark_ablation_report(report)
            runner.save_skill_memory_benchmark_ablation_report(report, args.output)
            return
        if getattr(args, "visual_action_ablation", False):
            report = runner.run_visual_action_benchmark_ablation(suite=args.suite)
            runner.print_visual_action_benchmark_ablation_report(report)
            runner.save_visual_action_benchmark_ablation_report(report, args.output)
            return
        if getattr(args, "mixed_policy_ablation", False):
            patch_paths = config.mixed_policy_patch_paths
            if not patch_paths:
                print("benchmark --mixed-policy-ablation requires at least one --mixed-policy-patch")
                sys.exit(1)
            report = runner.run_mixed_policy_benchmark_ablation(
                patch_paths=patch_paths,
                suite=args.suite,
            )
            runner.print_mixed_policy_benchmark_ablation_report(report)
            runner.save_mixed_policy_benchmark_ablation_report(report, args.output)
            return
        if args.suite == "m1":
            runner.run_m1_suite()
        elif args.suite == "m2":
            runner.run_m2_suite()
        else:
            runner.run_m1_suite()
            runner.run_m2_suite()
        runner.print_summary()
        runner.save_results(args.output)
        if getattr(args, "ingest", False):
            report = runner.ingest_results(promotion_critic=_promotion_critic_from_args(args))
            runner.print_ingestion_report(report)

    elif args.command == "autonomous":
        from singularity.core.agent import Agent
        agent = Agent(config)
        if not agent.connect():
            print("Failed to connect to Minecraft server")
            sys.exit(1)
        try:
            result = agent.run_autonomous(
                max_goals=getattr(args, "max_goals", 10),
                max_cycles_per_goal=getattr(args, "max_cycles", 80),
            )
            print(json.dumps(result, indent=2, default=str))
        finally:
            agent.disconnect()

    else:
        from singularity.core.agent import Agent
        goal = args.goal if args.goal else "Gather 3 oak logs"
        agent = Agent(config)
        if not agent.connect():
            print("Failed to connect to Minecraft server")
            sys.exit(1)
        try:
            result = agent.run_goal(goal)
            print(json.dumps(result, indent=2, default=str))
        finally:
            agent.disconnect()


if __name__ == "__main__":
    main()
