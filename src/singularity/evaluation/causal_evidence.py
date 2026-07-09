"""CausalGame-style causal evidence audits for Minecraft agent traces."""

from __future__ import annotations

import json
import os
import time
from typing import Any

from singularity.core.causal_index import CausalEventIndex, aggregate_causal_events


HYPOTHESIS_EVENTS = {"discovery_hypothesis", "hypothesis", "knowledge_gap"}
EXPERIMENT_EVENTS = {"discovery_experiment", "experiment", "causal_experiment", "causal_probe"}
CONSOLIDATION_EVENTS = {"discovery_consolidation", "causal_rule", "knowledge_consolidation"}
APPLICATION_EVENTS = {"discovery_application", "knowledge_application"}
RESOLUTION_EVENTS = {
    "knowledge_correction",
    "discovery_revision",
    "causal_revision",
    "counterexample_resolution",
    "failure_correction_completed",
}

CONTROL_TOKENS = {
    "control",
    "baseline",
    "negative control",
    "counterfactual",
    "without",
    "compare",
    "comparison",
    "hold constant",
    "same setup",
    "ablation",
}
OUTCOME_TOKENS = {"outcome", "observation", "observed", "measure", "measurement", "result", "evidence", "verified"}
INTERVENTION_TOKENS = {
    "intervention",
    "treatment",
    "manipulate",
    "manipulated",
    "change variable",
    "place",
    "dig",
    "craft",
    "use",
    "toggle",
    "trial",
}
SELECTION_BIAS_TOKENS = {
    "selection bias",
    "survivorship",
    "censored",
    "only successful",
    "success-only",
    "filtered to success",
    "sampled only",
}
MEASUREMENT_RISK_TOKENS = {
    "measurement error",
    "noisy",
    "noise",
    "uncertain",
    "ambiguous",
    "low confidence",
    "shared observation",
    "stale observation",
    "unverified",
    "missing screenshot",
}
HIDDEN_CONFOUNDER_TOKENS = {
    "confound",
    "hidden variable",
    "unobserved",
    "time of day",
    "tool tier",
    "lighting",
    "distance",
    "biome",
    "seed",
    "mob",
    "danger",
}
BIAS_MITIGATION_TOKENS = {
    "control",
    "random",
    "repeat",
    "replicate",
    "baseline",
    "counterfactual",
    "compare",
    "hold constant",
    "stratify",
    "verify",
    "separate",
    "negative control",
}
RESOLUTION_TOKENS = {
    "revise",
    "revised",
    "correction",
    "corrected",
    "counterexample",
    "failed because",
    "despite",
    "update rule",
    "do not promote",
}


def build_causal_evidence_report(
    session_log_paths: list[str],
    min_contrast_count: int = 1,
    max_unresolved_counterexamples: int = 0,
    require_bias_mitigation: bool = True,
) -> dict:
    """Audit whether causal memories/skills are backed by contrastive evidence."""
    thresholds = {
        "min_contrast_count": max(0, int(min_contrast_count or 0)),
        "max_unresolved_counterexamples": max(0, int(max_unresolved_counterexamples or 0)),
        "require_bias_mitigation": bool(require_bias_mitigation),
    }
    report = {
        "type": "causal_evidence_report",
        "generated_at": round(time.time(), 3),
        "thresholds": thresholds,
        "session_log_count": len(session_log_paths),
        "readable_log_count": 0,
        "ready_log_count": 0,
        "event_count": 0,
        "hypothesis_count": 0,
        "experiment_count": 0,
        "intervention_count": 0,
        "outcome_measure_count": 0,
        "contrast_control_count": 0,
        "causal_claim_count": 0,
        "causal_memory_write_count": 0,
        "application_count": 0,
        "successful_application_count": 0,
        "failed_application_count": 0,
        "counterexample_count": 0,
        "resolved_counterexample_count": 0,
        "unresolved_counterexample_count": 0,
        "bias_risk_counts": {},
        "addressed_bias_risk_counts": {},
        "action_transition_count": 0,
        "repeated_causal_summary_count": 0,
        "average_causal_evidence_score": 0.0,
        "cases": [],
        "checks": [],
        "policy_hints": [],
        "recommendations": [],
        "errors": [],
    }
    for path in session_log_paths:
        case = _case_from_log(path, thresholds)
        report["cases"].append(case)
        if case.get("log_available"):
            report["readable_log_count"] += 1
        if case.get("ready_for_causal_evidence_review"):
            report["ready_log_count"] += 1
        for key in (
            "event_count",
            "hypothesis_count",
            "experiment_count",
            "intervention_count",
            "outcome_measure_count",
            "contrast_control_count",
            "causal_claim_count",
            "causal_memory_write_count",
            "application_count",
            "successful_application_count",
            "failed_application_count",
            "counterexample_count",
            "resolved_counterexample_count",
            "unresolved_counterexample_count",
            "action_transition_count",
            "repeated_causal_summary_count",
        ):
            report[key] += int(case.get(key, 0) or 0)
        _merge_counts(report["bias_risk_counts"], case.get("bias_risk_counts", {}))
        _merge_counts(report["addressed_bias_risk_counts"], case.get("addressed_bias_risk_counts", {}))
        report["errors"].extend(case.get("errors", []))

    scores = [
        float(case.get("causal_evidence_score", 0.0) or 0.0)
        for case in report["cases"]
        if case.get("ready_for_causal_evidence_review")
    ]
    report["average_causal_evidence_score"] = round(sum(scores) / len(scores), 3) if scores else 0.0
    report["checks"] = _report_checks(report, thresholds)
    report["readiness"], report["decision"], report["reason"] = _report_decision(report["checks"], report)
    report["policy_hints"] = _policy_hints(report, thresholds)
    report["recommendations"] = _recommendations(report)
    return report


def write_causal_evidence_report(report: dict, output_path: str):
    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)


def build_causal_evidence_gate(
    causal_evidence_report_paths: list[str] = None,
    causal_evidence_reports: list[dict] = None,
    source: str = "",
    target: str = "causal_summary_skill_promotion",
    min_approved_reports: int = 1,
    min_contrast_count: int = 1,
    max_unresolved_counterexamples: int = 0,
    max_unmitigated_bias_risks: int = 0,
    required: bool = True,
) -> dict:
    """Build an approve/review/reject gate from causal evidence reports."""
    thresholds = {
        "min_approved_reports": max(0, int(min_approved_reports or 0)),
        "min_contrast_count": max(0, int(min_contrast_count or 0)),
        "max_unresolved_counterexamples": max(0, int(max_unresolved_counterexamples or 0)),
        "max_unmitigated_bias_risks": max(0, int(max_unmitigated_bias_risks or 0)),
    }
    inputs, load_errors = _load_causal_evidence_gate_inputs(
        causal_evidence_report_paths or [],
        causal_evidence_reports or [],
        source=source,
    )
    gate = {
        "type": "causal_evidence_gate",
        "generated_at": round(time.time(), 3),
        "target": target,
        "required": bool(required),
        "thresholds": thresholds,
        "report_count": len(inputs),
        "approved_report_count": 0,
        "review_report_count": 0,
        "rejected_report_count": 0,
        "error_report_count": 0,
        "readable_log_count": 0,
        "ready_log_count": 0,
        "causal_claim_count": 0,
        "causal_memory_write_count": 0,
        "contrast_control_count": 0,
        "unresolved_counterexample_count": 0,
        "counterexample_count": 0,
        "unmitigated_bias_risk_count": 0,
        "average_causal_evidence_score": 0.0,
        "sources": [],
        "readinesses": [],
        "evidence": [],
        "missing": [],
        "warnings": [],
        "errors": list(load_errors),
        "checks": [],
        "policy_hints": [],
    }

    scores = []
    for item in inputs:
        source_name = item["source"]
        report = item["report"]
        readiness = str(report.get("readiness") or "unknown").lower()
        gate["sources"].append(source_name)
        gate["readinesses"].append(readiness)
        if readiness == "approved":
            gate["approved_report_count"] += 1
            gate["evidence"].append(f"{source_name}: causal evidence report approved")
        elif readiness == "rejected":
            gate["rejected_report_count"] += 1
            gate["missing"].append(f"{source_name}: causal evidence report rejected")
        elif readiness == "error":
            gate["error_report_count"] += 1
            gate["missing"].append(f"{source_name}: causal evidence report errored")
        else:
            gate["review_report_count"] += 1
            gate["missing"].append(f"{source_name}: causal evidence report {readiness}")

        for key in (
            "readable_log_count",
            "ready_log_count",
            "causal_claim_count",
            "causal_memory_write_count",
            "contrast_control_count",
            "unresolved_counterexample_count",
            "counterexample_count",
        ):
            gate[key] += _safe_int(report.get(key, 0))
        gate["unmitigated_bias_risk_count"] += _unmitigated_bias_count(report)
        score = _safe_float_or_none(report.get("average_causal_evidence_score"))
        if score is not None:
            scores.append(score)
        if report.get("reason"):
            gate["warnings"].append(f"{source_name}: {report.get('reason')}")
        for check in report.get("checks", []) if isinstance(report.get("checks", []), list) else []:
            if isinstance(check, dict) and check.get("status") in {"warn", "fail"}:
                gate["warnings"].append(f"{source_name}: {check.get('detail', 'causal evidence check')}")
        for hint in report.get("policy_hints", []) if isinstance(report.get("policy_hints", []), list) else []:
            if str(hint or "").strip():
                gate["policy_hints"].append(str(hint))
        for recommendation in report.get("recommendations", []) if isinstance(report.get("recommendations", []), list) else []:
            if str(recommendation or "").strip():
                gate["warnings"].append(f"{source_name}: {recommendation}")
        for error in report.get("errors", []) if isinstance(report.get("errors", []), list) else []:
            if str(error or "").strip():
                gate["errors"].append(f"{source_name}: {error}")

    gate["average_causal_evidence_score"] = round(sum(scores) / len(scores), 3) if scores else 0.0
    gate["warnings"] = _dedupe(gate["warnings"])
    gate["policy_hints"] = _dedupe(gate["policy_hints"])
    gate["checks"] = _causal_evidence_gate_checks(gate, thresholds)
    gate["readiness"], gate["decision"], gate["reason"] = _causal_evidence_gate_decision(gate, thresholds)
    gate["policy_hints"] = _causal_evidence_gate_policy_hints(gate)
    return gate


def _case_from_log(path: str, thresholds: dict) -> dict:
    case = _empty_case(path)
    if not path or not os.path.exists(path):
        case["errors"].append(f"{path}: missing")
        _finalize_case(case, [], thresholds)
        return case

    events = []
    case["log_available"] = True
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    case["invalid_json_count"] += 1
                    continue
                if isinstance(event, dict):
                    events.append(event)
                else:
                    case["invalid_json_count"] += 1
    except OSError as exc:
        case["errors"].append(f"{path}: {exc}")

    for index, event in enumerate(events):
        _ingest_event(case, event, index)
    _ingest_causal_transitions(case, events)
    _finalize_case(case, events, thresholds)
    return case


def _empty_case(path: str) -> dict:
    return {
        "source_log": path,
        "log_available": False,
        "invalid_json_count": 0,
        "event_count": 0,
        "hypothesis_count": 0,
        "experiment_count": 0,
        "intervention_count": 0,
        "outcome_measure_count": 0,
        "contrast_control_count": 0,
        "causal_claim_count": 0,
        "causal_memory_write_count": 0,
        "application_count": 0,
        "successful_application_count": 0,
        "failed_application_count": 0,
        "counterexample_count": 0,
        "resolved_counterexample_count": 0,
        "unresolved_counterexample_count": 0,
        "bias_risk_counts": {},
        "addressed_bias_risk_counts": {},
        "action_transition_count": 0,
        "repeated_causal_summary_count": 0,
        "causal_claims": [],
        "counterexamples": [],
        "resolution_events": [],
        "issues": [],
        "causal_evidence_score": 0.0,
        "ready_for_causal_evidence_review": False,
        "errors": [],
    }


def _ingest_event(case: dict, event: dict, index: int):
    event_type = str(event.get("type") or "").strip().lower()
    data = event.get("data", {}) if isinstance(event.get("data", {}), dict) else {}
    text = _event_text(data)
    case["event_count"] += 1

    if event_type in HYPOTHESIS_EVENTS or _looks_like_hypothesis(text):
        case["hypothesis_count"] += 1
    if event_type in EXPERIMENT_EVENTS or _looks_like_experiment_event(event_type, text):
        case["experiment_count"] += 1
        if _has_intervention(data, text):
            case["intervention_count"] += 1
        if _has_outcome_measure(data, text):
            case["outcome_measure_count"] += 1
    if _has_contrast_control(data, text, event_type):
        case["contrast_control_count"] += 1
    _ingest_bias_risks(case, data, text)

    if event_type == "memory_write" and _looks_like_causal_memory(data, text):
        case["causal_memory_write_count"] += 1
        _append_causal_claim(case, event_type, data, text, index)
    elif event_type in CONSOLIDATION_EVENTS or _looks_like_causal_claim(data, text):
        _append_causal_claim(case, event_type, data, text, index)
    if event_type in APPLICATION_EVENTS:
        case["application_count"] += 1
        success = _event_success(data)
        if success is True:
            case["successful_application_count"] += 1
        elif success is False:
            case["failed_application_count"] += 1
            _append_counterexample(case, "failed_application", data, text, index)
    if event_type == "goal_end" and _looks_like_application(text):
        case["application_count"] += 1
        success = _event_success(data)
        if success is True:
            case["successful_application_count"] += 1
        elif success is False:
            case["failed_application_count"] += 1
            _append_counterexample(case, "failed_application_goal", data, text, index)
    if event_type == "goal_verification":
        success = _event_success(data)
        context = data.get("context", {}) if isinstance(data.get("context", {}), dict) else {}
        if success is False or context.get("accepted") is False:
            _append_counterexample(case, "goal_verification_reject", data, text, index)
        elif success is True or context.get("accepted") is True:
            case["outcome_measure_count"] += 1
    if event_type == "action":
        result = data.get("result", {}) if isinstance(data.get("result", {}), dict) else {}
        action_text = _event_text(data)
        if _looks_like_experiment_event(event_type, action_text):
            case["experiment_count"] += 1
            case["intervention_count"] += 1
            case["outcome_measure_count"] += 1
        if _event_success(result) is False:
            _append_counterexample(case, "failed_action", data, action_text, index)
    if event_type in RESOLUTION_EVENTS or _looks_like_resolution(text):
        case["resolution_events"].append({"index": index, "type": event_type, "detail": _short_text(text)})


def _ingest_bias_risks(case: dict, data: dict, text: str):
    risks = data.get("bias_risks", []) if isinstance(data.get("bias_risks", []), list) else []
    for risk in risks:
        risk_name = _bias_risk_name(str(risk))
        if risk_name:
            _increment(case["bias_risk_counts"], risk_name)
    for risk_name, tokens in (
        ("selection_bias", SELECTION_BIAS_TOKENS),
        ("measurement_error", MEASUREMENT_RISK_TOKENS),
        ("hidden_confounder", HIDDEN_CONFOUNDER_TOKENS),
    ):
        if _contains_any(text, tokens):
            _increment(case["bias_risk_counts"], risk_name)

    mitigation_text = _event_text({
        "bias_mitigation": data.get("bias_mitigation"),
        "controls": data.get("controls"),
        "control": data.get("control"),
        "held_constant": data.get("held_constant"),
        "notes": data.get("notes"),
        "text": text,
    })
    if _contains_any(mitigation_text, BIAS_MITIGATION_TOKENS):
        for risk_name in list(case["bias_risk_counts"].keys()):
            _increment(case["addressed_bias_risk_counts"], risk_name)


def _ingest_causal_transitions(case: dict, events: list[dict]):
    try:
        index = CausalEventIndex("", persist=False)
        created = index.ingest_session_events(events)
        summaries = aggregate_causal_events(created)
    except Exception as exc:
        case["errors"].append(f"causal_transition_ingest: {exc}")
        return
    case["action_transition_count"] = len(created)
    case["repeated_causal_summary_count"] = sum(1 for summary in summaries if summary.repeat_count > 1)


def _append_causal_claim(case: dict, event_type: str, data: dict, text: str, index: int):
    claim = _first_text(data, ["rule", "causal_rule", "finding", "lesson", "content", "summary", "hypothesis"]) or text
    if not claim:
        return
    case["causal_claim_count"] += 1
    case["causal_claims"].append({
        "event_index": index,
        "event_type": event_type,
        "claim": _short_text(claim, 240),
        "has_contrast_control": _has_contrast_control(data, text, event_type),
        "has_outcome_measure": _has_outcome_measure(data, text),
    })


def _append_counterexample(case: dict, category: str, data: dict, text: str, index: int):
    reason = _first_text(data, ["reason", "error", "message", "status", "outcome"]) or text or category
    case["counterexample_count"] += 1
    case["counterexamples"].append({
        "event_index": index,
        "category": category,
        "reason": _short_text(reason, 220),
        "resolved": False,
    })


def _finalize_case(case: dict, events: list[dict], thresholds: dict):
    resolution_indices = [int(item.get("index", -1)) for item in case.get("resolution_events", [])]
    for counterexample in case["counterexamples"]:
        counter_index = int(counterexample.get("event_index", -1))
        counterexample["resolved"] = any(index > counter_index for index in resolution_indices)
    case["resolved_counterexample_count"] = sum(1 for item in case["counterexamples"] if item.get("resolved"))
    case["unresolved_counterexample_count"] = case["counterexample_count"] - case["resolved_counterexample_count"]

    issues = []
    if case["hypothesis_count"] <= 0 and (case["experiment_count"] or case["causal_claim_count"]):
        issues.append("missing_explicit_hypothesis")
    if case["experiment_count"] <= 0 and case["causal_claim_count"]:
        issues.append("causal_claim_without_experiment")
    if case["intervention_count"] <= 0 and case["experiment_count"]:
        issues.append("missing_intervention_protocol")
    if case["outcome_measure_count"] <= 0 and (case["experiment_count"] or case["causal_claim_count"]):
        issues.append("missing_outcome_measure")
    if case["contrast_control_count"] < thresholds["min_contrast_count"] and case["causal_claim_count"]:
        issues.append("missing_contrast_control")
    if case["unresolved_counterexample_count"] > thresholds["max_unresolved_counterexamples"]:
        issues.append("unresolved_counterexamples")
    if case["causal_memory_write_count"] and case["contrast_control_count"] < thresholds["min_contrast_count"]:
        issues.append("causal_memory_without_contrast")
    if thresholds["require_bias_mitigation"]:
        for risk, count in case["bias_risk_counts"].items():
            addressed = int(case["addressed_bias_risk_counts"].get(risk, 0) or 0)
            if count > addressed:
                issues.append(f"{risk}_unchecked")
    if case["application_count"] and case["successful_application_count"] <= 0:
        issues.append("application_without_success")

    case["issues"] = sorted(set(issues))
    case["causal_evidence_score"] = _causal_evidence_score(case, thresholds)
    case["ready_for_causal_evidence_review"] = bool(
        events
        and (
            case["hypothesis_count"]
            or case["experiment_count"]
            or case["causal_claim_count"]
            or case["causal_memory_write_count"]
            or case["counterexample_count"]
        )
    )


def _causal_evidence_score(case: dict, thresholds: dict) -> float:
    components = []
    components.append(1.0 if case["hypothesis_count"] > 0 else 0.0)
    components.append(1.0 if case["experiment_count"] > 0 and case["intervention_count"] > 0 else 0.0)
    components.append(1.0 if case["outcome_measure_count"] > 0 else 0.0)
    components.append(min(1.0, case["contrast_control_count"] / max(1, thresholds["min_contrast_count"])))
    unresolved_allowed = thresholds["max_unresolved_counterexamples"]
    if case["counterexample_count"] <= 0:
        components.append(1.0)
    else:
        components.append(1.0 if case["unresolved_counterexample_count"] <= unresolved_allowed else 0.0)
    risks = sum(int(count or 0) for count in case["bias_risk_counts"].values())
    addressed = sum(int(count or 0) for count in case["addressed_bias_risk_counts"].values())
    components.append(1.0 if risks == 0 else min(1.0, addressed / risks))
    return round(sum(components) / len(components), 3)


def _report_checks(report: dict, thresholds: dict) -> list[dict]:
    checks = []
    _add_check(checks, "logs_readable", report["readable_log_count"] > 0, f"{report['readable_log_count']} logs readable", "fail")
    _add_check(checks, "causal_evidence_present", report["ready_log_count"] > 0, f"{report['ready_log_count']} logs ready", "warn")
    _add_check(checks, "causal_claims_present", report["causal_claim_count"] > 0, f"{report['causal_claim_count']} causal claims", "warn")
    _add_check(checks, "experimental_protocol_present", report["experiment_count"] > 0 and report["intervention_count"] > 0, f"experiments={report['experiment_count']} interventions={report['intervention_count']}", "fail")
    _add_check(checks, "outcome_measurements_present", report["outcome_measure_count"] > 0, f"outcomes={report['outcome_measure_count']}", "fail")
    _add_check(checks, "contrast_controls_present", report["contrast_control_count"] >= thresholds["min_contrast_count"], f"contrast_controls={report['contrast_control_count']}", "fail")
    _add_check(checks, "counterexamples_resolved", report["unresolved_counterexample_count"] <= thresholds["max_unresolved_counterexamples"], f"unresolved_counterexamples={report['unresolved_counterexample_count']}", "fail")
    if thresholds["require_bias_mitigation"]:
        unmitigated = _unmitigated_bias_count(report)
        _add_check(checks, "bias_risks_mitigated", unmitigated <= 0, f"unmitigated_bias_risks={unmitigated}", "fail")
    if report["causal_memory_write_count"]:
        safe = report["contrast_control_count"] >= thresholds["min_contrast_count"] and report["unresolved_counterexample_count"] <= thresholds["max_unresolved_counterexamples"]
        _add_check(checks, "causal_memory_safe_for_promotion", safe, f"causal_memory_writes={report['causal_memory_write_count']}", "fail")
    return checks


def _report_decision(checks: list[dict], report: dict) -> tuple[str, str, str]:
    failures = [check for check in checks if check.get("status") == "fail"]
    warnings = [check for check in checks if check.get("status") == "warn"]
    if failures:
        return "rejected", "do_not_promote_causal_claims", failures[0].get("detail", "causal evidence failed")
    if warnings:
        return "review", "hold_causal_claim_promotion", warnings[0].get("detail", "causal evidence needs review")
    if report.get("causal_claim_count", 0) <= 0:
        return "review", "hold_causal_claim_promotion", "no causal claims found"
    return "approved", "allow_causal_claim_review", "causal claims have contrastive evidence and resolved counterexamples"


def _policy_hints(report: dict, thresholds: dict) -> list[str]:
    hints = []
    if report["contrast_control_count"] < thresholds["min_contrast_count"]:
        hints.append("add_contrast_control_to_discovery_experiments")
    if report["outcome_measure_count"] <= 0:
        hints.append("log_verified_outcome_measurements")
    if report["unresolved_counterexample_count"] > thresholds["max_unresolved_counterexamples"]:
        hints.append("resolve_counterexamples_before_causal_promotion")
    if _unmitigated_bias_count(report) > 0:
        hints.append("mitigate_selection_measurement_and_confounder_risks")
    if report["causal_memory_write_count"] and report["contrast_control_count"] < thresholds["min_contrast_count"]:
        hints.append("keep_causal_memory_review_only_until_contrastive")
    if report.get("readiness") == "approved":
        hints.append("causal_evidence_ready_for_discovery_gate")
    return _dedupe(hints)


def _recommendations(report: dict) -> list[str]:
    recommendations = []
    if report["hypothesis_count"] <= 0:
        recommendations.append("record_explicit_hypotheses_before_experiments")
    if report["contrast_control_count"] <= 0:
        recommendations.append("add_control_or_counterfactual_trials_to_minecraft_discovery_tasks")
    if report["bias_risk_counts"]:
        recommendations.append("log_bias_mitigation_for_selection_measurement_and_hidden_confounders")
    if report["unresolved_counterexample_count"]:
        recommendations.append("route_failed_applications_and_verifier_rejects_into_rule_revision")
    if report["causal_memory_write_count"] and report["unresolved_counterexample_count"]:
        recommendations.append("block_runtime_use_of_causal_memory_until_counterexamples_are_resolved")
    if report["repeated_causal_summary_count"] and report["contrast_control_count"] <= 0:
        recommendations.append("do_not_promote_repeated_causal_summaries_without_contrastive_tests")
    if report.get("readiness") == "approved":
        recommendations.append("use_this_report_as_supporting_evidence_before_discovery_skill_gate")
    return _dedupe(recommendations)


def _load_causal_evidence_gate_inputs(paths: list[str], reports: list[dict], source: str = "") -> tuple[list[dict], list[str]]:
    inputs = []
    errors = []
    if isinstance(reports, dict):
        reports = [reports]
    for index, payload in enumerate(reports or []):
        source_name = source or f"inline:{index + 1}"
        if not isinstance(payload, dict):
            errors.append(f"{source_name}: causal evidence report must be an object")
            continue
        error = _causal_evidence_report_type_error(payload, source_name)
        if error:
            errors.append(error)
            continue
        inputs.append({"source": source_name, "report": payload})
    for path in paths or []:
        if not path:
            continue
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                payload = json.load(f)
            if not isinstance(payload, dict):
                raise ValueError("causal evidence report JSON must be an object")
            error = _causal_evidence_report_type_error(payload, path)
            if error:
                errors.append(error)
                continue
            inputs.append({"source": path, "report": payload})
        except Exception as exc:
            errors.append(f"{path}: {exc}")
    return inputs, errors


def _causal_evidence_report_type_error(payload: dict, source: str) -> str:
    payload_type = str(payload.get("type") or "").strip()
    if payload_type and payload_type != "causal_evidence_report":
        return f"{source}: expected causal_evidence_report, got {payload_type}"
    if "readiness" not in payload or "decision" not in payload:
        return f"{source}: missing causal evidence report decision fields"
    return ""


def _causal_evidence_gate_checks(gate: dict, thresholds: dict) -> list[dict]:
    checks = []
    if not gate.get("required"):
        _add_check(checks, "causal_evidence_gate_required", True, "causal evidence gate not required", "warn")
        return checks
    _add_check(
        checks,
        "causal_evidence_reports_present",
        gate.get("report_count", 0) > 0,
        f"reports={gate.get('report_count', 0)}",
        "fail",
    )
    _add_check(
        checks,
        "causal_evidence_reports_approved",
        gate.get("approved_report_count", 0) >= thresholds["min_approved_reports"],
        f"approved_reports={gate.get('approved_report_count', 0)}",
        "fail",
    )
    _add_check(
        checks,
        "causal_claim_or_memory_present",
        gate.get("causal_claim_count", 0) > 0 or gate.get("causal_memory_write_count", 0) > 0,
        f"claims={gate.get('causal_claim_count', 0)} causal_memory={gate.get('causal_memory_write_count', 0)}",
        "fail",
    )
    _add_check(
        checks,
        "contrast_controls_present",
        gate.get("contrast_control_count", 0) >= thresholds["min_contrast_count"],
        f"contrast_controls={gate.get('contrast_control_count', 0)}",
        "fail",
    )
    _add_check(
        checks,
        "counterexamples_resolved",
        gate.get("unresolved_counterexample_count", 0) <= thresholds["max_unresolved_counterexamples"],
        f"unresolved_counterexamples={gate.get('unresolved_counterexample_count', 0)}",
        "fail",
    )
    _add_check(
        checks,
        "bias_risks_mitigated",
        gate.get("unmitigated_bias_risk_count", 0) <= thresholds["max_unmitigated_bias_risks"],
        f"unmitigated_bias_risks={gate.get('unmitigated_bias_risk_count', 0)}",
        "fail",
    )
    _add_check(
        checks,
        "causal_evidence_inputs_readable",
        not gate.get("errors"),
        f"errors={len(gate.get('errors', []))}",
        "fail",
    )
    return checks


def _causal_evidence_gate_decision(gate: dict, thresholds: dict) -> tuple[str, str, str]:
    if not gate.get("required"):
        return "not_required", "allow", "no_causal_evidence_gate_required"
    if gate.get("errors"):
        return "error", "reject", "causal_evidence_gate_error"
    if gate.get("report_count", 0) <= 0:
        return "review", "reject", "causal_evidence_gate_requires_report"
    if gate.get("rejected_report_count", 0) or gate.get("error_report_count", 0):
        return "rejected", "reject", "causal_evidence_report_rejected"
    if gate.get("approved_report_count", 0) < thresholds["min_approved_reports"]:
        return "review", "reject", "causal_evidence_gate_requires_approved_report"
    if gate.get("causal_claim_count", 0) <= 0 and gate.get("causal_memory_write_count", 0) <= 0:
        return "review", "reject", "causal_evidence_gate_requires_causal_claims"
    if gate.get("contrast_control_count", 0) < thresholds["min_contrast_count"]:
        return "rejected", "reject", "causal_evidence_gate_requires_contrast_controls"
    if gate.get("unresolved_counterexample_count", 0) > thresholds["max_unresolved_counterexamples"]:
        return "rejected", "reject", "causal_evidence_gate_blocks_unresolved_counterexamples"
    if gate.get("unmitigated_bias_risk_count", 0) > thresholds["max_unmitigated_bias_risks"]:
        return "rejected", "reject", "causal_evidence_gate_blocks_unmitigated_bias"
    failures = [check for check in gate.get("checks", []) if check.get("status") == "fail"]
    if failures:
        return "rejected", "reject", failures[0].get("detail", "causal evidence gate failed")
    warnings = [check for check in gate.get("checks", []) if check.get("status") == "warn"]
    if warnings:
        return "review", "reject", warnings[0].get("detail", "causal evidence gate requires review")
    return "approved", "allow", "causal_evidence_gate_approved"


def _causal_evidence_gate_policy_hints(gate: dict) -> list[str]:
    hints = list(gate.get("policy_hints", []) if isinstance(gate.get("policy_hints", []), list) else [])
    if not gate.get("required"):
        return _dedupe(hints)
    readiness = str(gate.get("readiness") or "unknown")
    if readiness == "approved":
        hints.append("causal_evidence_gate_approved")
    elif readiness == "review":
        hints.append("keep_causal_summary_skill_review_only")
    elif readiness in {"rejected", "error"}:
        hints.append("block_causal_summary_skill_promotion")
    if gate.get("contrast_control_count", 0) <= 0:
        hints.append("add_contrast_control_before_causal_skill_promotion")
    if gate.get("unresolved_counterexample_count", 0) > 0:
        hints.append("resolve_counterexamples_before_causal_skill_promotion")
    if gate.get("unmitigated_bias_risk_count", 0) > 0:
        hints.append("mitigate_bias_before_causal_skill_promotion")
    return _dedupe(hints)


def _add_check(checks: list[dict], name: str, passed: bool, detail: str, severity: str):
    checks.append({"name": name, "status": "pass" if passed else severity, "detail": detail})


def _looks_like_hypothesis(text: str) -> bool:
    return _contains_any(text, {"hypothesis", "knowledge gap", "need to know", "whether", "question"})


def _looks_like_experiment_event(event_type: str, text: str) -> bool:
    if event_type == "action":
        return _contains_any(text, {"experiment", "trial", "probe", "test", "causal"})
    return _contains_any(text, {"experiment", "trial", "probe", "test causal", "protocol"})


def _looks_like_causal_claim(data: dict, text: str) -> bool:
    if _first_text(data, ["rule", "causal_rule", "finding"]):
        return True
    return _contains_any(text, {"causal rule", "causes", "because", "if ", " then ", "leads to", "enables"})


def _looks_like_causal_memory(data: dict, text: str) -> bool:
    layer = str(data.get("layer") or "").lower()
    memory_type = str(data.get("memory_type") or "").lower()
    source = str(data.get("source") or "").lower()
    return (
        layer == "causal"
        or "causal" in memory_type
        or "rule" in memory_type
        or "discovery" in source
        or _looks_like_causal_claim(data, text)
    )


def _looks_like_application(text: str) -> bool:
    return _contains_any(text, {"application", "apply", "build", "construct", "held-out", "use the discovered"})


def _looks_like_resolution(text: str) -> bool:
    return _contains_any(text, RESOLUTION_TOKENS)


def _has_contrast_control(data: dict, text: str, event_type: str = "") -> bool:
    for key in ("control", "controls", "baseline", "negative_control", "counterfactual", "comparison", "held_constant"):
        value = data.get(key)
        if value not in (None, "", [], {}):
            return True
    return "control" in event_type or _contains_any(text, CONTROL_TOKENS)


def _has_intervention(data: dict, text: str) -> bool:
    for key in ("intervention", "treatment", "manipulated_variable", "changed_variable", "action", "actions", "experiment"):
        value = data.get(key)
        if value not in (None, "", [], {}):
            return True
    return _contains_any(text, INTERVENTION_TOKENS)


def _has_outcome_measure(data: dict, text: str) -> bool:
    for key in ("outcome", "observation", "observed", "measurement", "result", "success", "evidence", "verifier"):
        if key in data and data.get(key) not in (None, "", [], {}):
            return True
    return _contains_any(text, OUTCOME_TOKENS)


def _event_success(record: dict) -> bool | None:
    if not isinstance(record, dict):
        return None
    for key in ("success", "completed", "passed", "ok", "achieved", "accepted"):
        if isinstance(record.get(key), bool):
            return bool(record.get(key))
    status = str(record.get("status") or record.get("state") or record.get("outcome") or "").strip().lower()
    if status in {"achieved", "complete", "completed", "done", "ok", "pass", "passed", "success", "succeeded", "accepted"}:
        return True
    if status in {"aborted", "blocked", "error", "fail", "failed", "failure", "incomplete", "rejected"}:
        return False
    result = record.get("result")
    if isinstance(result, dict):
        return _event_success(result)
    if record.get("error"):
        return False
    return None


def _event_text(value: Any) -> str:
    parts = []
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                parts.append(f"{key}={_event_text(item)}")
            else:
                parts.append(f"{key}={item}")
    elif isinstance(value, list):
        parts.extend(_event_text(item) for item in value)
    elif value is not None:
        parts.append(str(value))
    return " ".join(part for part in parts if part).lower()


def _first_text(record: dict, keys: list[str]) -> str:
    for key in keys:
        value = record.get(key) if isinstance(record, dict) else None
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _bias_risk_name(text: str) -> str:
    lower = text.lower()
    if "selection" in lower or "survivorship" in lower or "censor" in lower:
        return "selection_bias"
    if "measurement" in lower or "noise" in lower or "uncertain" in lower:
        return "measurement_error"
    if "confound" in lower or "hidden" in lower or "unobserved" in lower:
        return "hidden_confounder"
    return lower.replace(" ", "_")[:80] if lower else ""


def _unmitigated_bias_count(report: dict) -> int:
    total = 0
    risks = report.get("bias_risk_counts", {}) if isinstance(report.get("bias_risk_counts", {}), dict) else {}
    addressed = report.get("addressed_bias_risk_counts", {}) if isinstance(report.get("addressed_bias_risk_counts", {}), dict) else {}
    for risk, count in risks.items():
        total += max(0, int(count or 0) - int(addressed.get(risk, 0) or 0))
    return total


def _contains_any(text: str, tokens: set[str]) -> bool:
    lower = str(text or "").lower()
    return any(token in lower for token in tokens)


def _short_text(text: str, limit: int = 180) -> str:
    compact = " ".join(str(text or "").split())
    return compact[:limit]


def _merge_counts(target: dict, source: dict):
    if not isinstance(source, dict):
        return
    for key, value in source.items():
        target[str(key)] = int(target.get(str(key), 0) or 0) + int(value or 0)


def _safe_int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _safe_float_or_none(value):
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _increment(counts: dict, key: str, amount: int = 1):
    counts[key] = int(counts.get(key, 0) or 0) + int(amount or 0)


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
