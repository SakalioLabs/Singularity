"""Evidence ledger for Minecraft Agent capability claims."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional


SUCCESS_STATUSES = {"success", "succeeded", "pass", "passed", "complete", "completed"}
FAILURE_STATUSES = {"fail", "failed", "error", "blocked", "timeout", "rejected"}
LIVE_PHASE_IDS = ("M3", "M5", "M6")
EXPLORATION_MIN_DISTANCE = 16.0
EXECUTION_FIELDS = {
    "cycles",
    "cycles_used",
    "duration_s",
    "inventory",
    "inventory_snapshot",
    "log",
    "session_log",
    "session_id",
    "intervention_metrics",
    "error",
    "completed",
    "success",
}

PHASE_SPECS = [
    {
        "id": "M0",
        "name": "Research Baseline",
        "benchmark_ids": [],
        "source_paths": [
            "workspace/papers/paper-index.md",
            "workspace/repos/repo-index.md",
            "workspace/benchmarks/benchmark-index.md",
            "workspace/ROADMAP.md",
            "workspace/OPEN_QUESTIONS.md",
            "workspace/DECISIONS.md",
        ],
        "evidence_kind": "source",
    },
    {
        "id": "M1",
        "name": "Minimum Viable Bot",
        "benchmark_ids": ["BM-001", "BM-002", "BM-003", "BM-004", "BM-005"],
        "source_paths": [
            "src/singularity/core/agent.py",
            "src/singularity/action/controller.py",
            "src/singularity/observation/observer.py",
            "src/bot/bot_server.js",
        ],
        "evidence_kind": "benchmark",
    },
    {
        "id": "M2",
        "name": "LLM Task Planning",
        "benchmark_ids": ["BM-006", "BM-007", "BM-008", "BM-009", "BM-010"],
        "source_paths": [
            "src/singularity/core/planner.py",
            "src/singularity/core/task_system.py",
            "src/singularity/core/reflector.py",
        ],
        "evidence_kind": "benchmark",
    },
    {
        "id": "M3",
        "name": "Skill Library and Memory",
        "benchmark_ids": [],
        "source_paths": [
            "src/singularity/core/memory.py",
            "src/singularity/core/skill_library.py",
            "src/singularity/core/skill_extractor.py",
        ],
        "evidence_kind": "live_report",
    },
    {
        "id": "M4",
        "name": "Autonomous Survival",
        "benchmark_ids": ["BM-011", "BM-012", "BM-013", "BM-014"],
        "source_paths": [
            "src/singularity/core/goal_generator.py",
            "src/singularity/core/curriculum.py",
            "src/singularity/core/runtime.py",
        ],
        "evidence_kind": "benchmark",
    },
    {
        "id": "M5",
        "name": "Open-World Exploration",
        "benchmark_ids": [],
        "source_paths": [
            "src/singularity/core/explorer.py",
            "src/singularity/core/curriculum.py",
        ],
        "evidence_kind": "live_report",
    },
    {
        "id": "M6",
        "name": "Vision and Multimodal",
        "benchmark_ids": [],
        "source_paths": [
            "src/singularity/vision/analyzer.py",
            "src/singularity/vision/visual_memory.py",
            "src/singularity/vision/action_advisor.py",
        ],
        "evidence_kind": "live_report",
    },
    {
        "id": "M7",
        "name": "Multi-Agent Collaboration",
        "benchmark_ids": ["BM-701"],
        "source_paths": [
            "src/singularity/multiagent/coordinator.py",
            "src/singularity/multiagent/protocol.py",
            "src/singularity/evaluation/collaboration_runner.py",
        ],
        "evidence_kind": "benchmark",
    },
]


def build_capability_evidence_report(
    benchmark_result_paths: Optional[Iterable[str]] = None,
    status_path: str = "workspace/STATUS.md",
    source_root: str = ".",
    min_repeats: int = 3,
    runtime_evidence: Optional[dict] = None,
    phase_evidence_paths: Optional[dict[str, Iterable[str]]] = None,
) -> dict:
    """Compare declared phase completion against source and execution evidence."""
    min_repeats = max(1, int(min_repeats or 1))
    source_root_path = Path(source_root)
    declared, status_errors = _load_declared_status(status_path)
    records, load_errors, loaded_paths = _load_benchmark_records(benchmark_result_paths or [])
    benchmark_stats = _summarize_benchmarks(records)
    live_evidence, live_errors, loaded_phase_paths = _load_live_phase_evidence(
        phase_evidence_paths or {},
        min_repeats=min_repeats,
    )

    phases = []
    for spec in PHASE_SPECS:
        source_checks = [
            {
                "path": path,
                "exists": (source_root_path / path).is_file(),
            }
            for path in spec["source_paths"]
        ]
        source_ready = bool(source_checks) and all(check["exists"] for check in source_checks)
        benchmark_ids = list(spec["benchmark_ids"])
        task_stats = [
            _benchmark_status(benchmark_id, benchmark_stats.get(benchmark_id, {}), min_repeats)
            for benchmark_id in benchmark_ids
        ]
        phase_live_evidence = live_evidence.get(spec["id"], {})
        status = _phase_status(
            spec["evidence_kind"],
            source_ready,
            task_stats,
            min_repeats,
            live_evidence=phase_live_evidence,
        )
        declaration = declared.get(spec["id"], {})
        declared_complete = _declared_complete(declaration)
        claim_assessment = _claim_assessment(declared_complete, status)
        phases.append({
            "id": spec["id"],
            "name": spec["name"],
            "evidence_kind": spec["evidence_kind"],
            "status": status,
            "completion_claim_allowed": status in {"source_verified", "repeat_verified"},
            "declared": declaration,
            "declared_complete": declared_complete,
            "claim_assessment": claim_assessment,
            "source_ready": source_ready,
            "source_checks": source_checks,
            "required_benchmark_count": len(benchmark_ids),
            "live_observed_benchmark_count": sum(1 for task in task_stats if task["successes"] >= 1),
            "repeat_verified_benchmark_count": sum(1 for task in task_stats if task["successes"] >= min_repeats),
            "benchmarks": task_stats,
            "live_evidence": phase_live_evidence,
            "required_live_execution_count": min_repeats if spec["evidence_kind"] == "live_report" else 0,
            "live_observed_execution_count": int(phase_live_evidence.get("verified_successes", 0) or 0),
            "missing_evidence": _missing_phase_evidence(
                spec,
                status,
                task_stats,
                source_checks,
                min_repeats,
                live_evidence=phase_live_evidence,
            ),
        })

    contradictions = [
        phase["id"]
        for phase in phases
        if phase["claim_assessment"] == "contradicted"
    ]
    unsupported = [
        phase["id"]
        for phase in phases
        if phase["claim_assessment"] == "unsupported"
    ]
    evidence_errors = load_errors + live_errors
    claim_readiness = "rejected" if contradictions else "review" if unsupported or evidence_errors or status_errors else "approved"
    system_complete = all(phase["completion_claim_allowed"] for phase in phases)
    has_failed_evidence = any(phase["status"] in {"source_incomplete", "failing"} for phase in phases)
    if contradictions or has_failed_evidence:
        readiness = "rejected"
    elif system_complete and not evidence_errors and not status_errors:
        readiness = "approved"
    else:
        readiness = "review"
    report = {
        "type": "capability_evidence_report",
        "schema_version": 2,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "readiness": readiness,
        "claim_readiness": claim_readiness,
        "system_status": "complete" if system_complete else "incomplete",
        "system_complete": system_complete,
        "policy": {
            "min_repeats": min_repeats,
            "source_presence_is_capability_evidence": False,
            "unit_tests_are_live_capability_evidence": False,
            "completion_requires_repeat_verified_execution": True,
            "live_phase_acceptance": {
                "M3": "three distinct successful continual-learning sessions plus an approved held-out transfer gate",
                "M5": f"three distinct autonomous exploration sessions covering at least {EXPLORATION_MIN_DISTANCE:g} blocks plus an approved world-model gate",
                "M6": "three distinct screenshot-backed sessions with matching non-builtin visual-action ablations",
            },
        },
        "inputs": {
            "status_path": status_path,
            "source_root": source_root,
            "benchmark_result_paths": loaded_paths,
            "phase_evidence_paths": loaded_phase_paths,
        },
        "runtime_evidence": runtime_evidence or {},
        "summary": {
            "phase_count": len(phases),
            "declared_complete_count": sum(1 for phase in phases if phase["declared_complete"]),
            "supported_completion_count": sum(1 for phase in phases if phase["claim_assessment"] == "supported"),
            "contradicted_completion_count": len(contradictions),
            "unsupported_completion_count": len(unsupported),
            "repeat_verified_phase_count": sum(1 for phase in phases if phase["status"] == "repeat_verified"),
            "live_observed_phase_count": sum(1 for phase in phases if phase["status"] == "live_observed"),
            "failing_phase_count": sum(1 for phase in phases if phase["status"] == "failing"),
            "system_complete": system_complete,
        },
        "contradicted_phases": contradictions,
        "unsupported_phases": unsupported,
        "phases": phases,
        "errors": status_errors + evidence_errors,
    }
    report["recommendations"] = _recommendations(report)
    return report


def write_capability_evidence_report(report: dict, output_path: str) -> str:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return str(path)


def print_capability_evidence_report(report: dict) -> None:
    print("\nCapability Evidence Report")
    print(f"  readiness: {report.get('readiness', 'review')}")
    print(f"  claim audit: {report.get('claim_readiness', 'review')}")
    print(f"  system status: {report.get('system_status', 'incomplete')}")
    runtime = report.get("runtime_evidence", {})
    if runtime:
        print(f"  runtime preflight: {'ready' if runtime.get('ok') else 'not ready'}")
    print("  policy: source/tests do not prove live capability; repeated execution is required")
    for phase in report.get("phases", []):
        declared = "complete" if phase.get("declared_complete") else "not complete"
        live = phase.get("live_observed_benchmark_count", 0)
        required = phase.get("required_benchmark_count", 0)
        benchmark_text = f", live={live}/{required}" if required else ""
        if phase.get("evidence_kind") == "live_report":
            evidence = phase.get("live_evidence", {})
            verified = evidence.get("verified_successes", 0)
            repeats = evidence.get("repeats_required", 0)
            support = "approved" if evidence.get("support_approved") else "missing"
            benchmark_text = f", verified_sessions={verified}/{repeats}, support={support}"
        print(
            f"  [{phase.get('id')}] {phase.get('status')}: "
            f"declared={declared}, claim={phase.get('claim_assessment')}{benchmark_text}"
        )
    for recommendation in report.get("recommendations", [])[:12]:
        print(f"  -> {recommendation}")


def _load_live_phase_evidence(
    phase_evidence_paths: dict[str, Iterable[str]],
    min_repeats: int,
) -> tuple[dict, list[str], dict]:
    normalized_paths = {}
    errors = []
    for raw_phase, paths in (phase_evidence_paths or {}).items():
        phase_id = str(raw_phase or "").upper().strip()
        path_items = [paths] if isinstance(paths, (str, Path)) else list(paths or [])
        if phase_id not in LIVE_PHASE_IDS:
            if path_items:
                errors.append(f"phase_evidence_unsupported:{phase_id or raw_phase}")
            continue
        normalized_paths.setdefault(phase_id, []).extend(path_items)

    summaries = {}
    loaded_paths = {}
    for phase_id in LIVE_PHASE_IDS:
        payloads, phase_errors, phase_loaded_paths = _load_evidence_payloads(
            normalized_paths.get(phase_id, [])
        )
        errors.extend(phase_errors)
        loaded_paths[phase_id] = phase_loaded_paths
        if phase_id == "M3":
            summary, adapter_errors = _build_m3_live_evidence(payloads, min_repeats)
        elif phase_id == "M5":
            summary, adapter_errors = _build_m5_live_evidence(payloads, min_repeats)
        else:
            summary, adapter_errors = _build_m6_live_evidence(payloads, min_repeats)
        summaries[phase_id] = summary
        errors.extend(adapter_errors)
    return summaries, errors, loaded_paths


def _load_evidence_payloads(paths: Iterable[str]) -> tuple[list[tuple[str, dict]], list[str], list[str]]:
    payloads = []
    errors = []
    loaded_paths = []
    seen = set()
    for raw_path in paths:
        path_text = str(raw_path or "").strip()
        if not path_text:
            continue
        path_key = os.path.normcase(os.path.abspath(path_text))
        if path_key in seen:
            continue
        seen.add(path_key)
        path = Path(path_text)
        if not path.is_file():
            errors.append(f"phase_evidence_missing:{path_text}")
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            errors.append(f"phase_evidence_unreadable:{path_text}:{exc}")
            continue
        if not isinstance(payload, dict):
            errors.append(f"phase_evidence_invalid_root:{path_text}:expected_object")
            continue
        payloads.append((path_text, payload))
        loaded_paths.append(path_text)
    return payloads, errors, loaded_paths


def _new_live_summary(phase_id: str, primary_type: str, support_type: str, min_repeats: int) -> dict:
    return {
        "phase_id": phase_id,
        "primary_evidence_type": primary_type,
        "support_evidence_type": support_type,
        "status": "not_run",
        "repeats_required": min_repeats,
        "loaded_report_count": 0,
        "primary_report_count": 0,
        "support_report_count": 0,
        "attempts": 0,
        "primary_successes": 0,
        "verified_successes": 0,
        "failures": 0,
        "support_approved": False,
        "evidence_refs": [],
        "primary_cases": [],
        "support_evidence": [],
        "missing": [],
    }


def _build_m3_live_evidence(
    payloads: list[tuple[str, dict]],
    min_repeats: int,
) -> tuple[dict, list[str]]:
    summary = _new_live_summary(
        "M3",
        "continual_learning_report",
        "task_stream_transfer_gate",
        min_repeats,
    )
    summary["loaded_report_count"] = len(payloads)
    records = []
    gates = []
    errors = []
    for source_path, payload in payloads:
        if _is_m3_transfer_gate(payload):
            summary["support_report_count"] += 1
            gates.append(_assess_m3_transfer_gate(source_path, payload))
            continue
        if _is_m3_continual_report(payload):
            summary["primary_report_count"] += 1
            for index, case in enumerate(_dict_cases(payload)):
                records.append(_assess_m3_case(source_path, index, case))
            continue
        errors.append(f"phase_evidence_unrecognized:M3:{source_path}")

    aggregate = _aggregate_case_records(records)
    approved_gates = [gate for gate in gates if gate["approved"]]
    support_approved = bool(approved_gates)
    verified_keys = aggregate["success_keys"] if support_approved else set()
    _finalize_live_summary(
        summary,
        aggregate,
        verified_keys=verified_keys,
        support_approved=support_approved,
        support_evidence=gates,
        support_missing="approved_heldout_task_stream_transfer_gate_required",
    )
    return summary, errors


def _build_m5_live_evidence(
    payloads: list[tuple[str, dict]],
    min_repeats: int,
) -> tuple[dict, list[str]]:
    summary = _new_live_summary(
        "M5",
        "exploration_trace_report",
        "world_model_feedback_gate",
        min_repeats,
    )
    summary["loaded_report_count"] = len(payloads)
    records = []
    gates = []
    errors = []
    for source_path, payload in payloads:
        if _is_m5_world_model_gate(payload):
            summary["support_report_count"] += 1
            gates.append(_assess_m5_world_model_gate(source_path, payload))
            continue
        if _is_m5_exploration_report(payload):
            summary["primary_report_count"] += 1
            for index, case in enumerate(_dict_cases(payload)):
                records.append(_assess_m5_case(source_path, index, case))
            continue
        errors.append(f"phase_evidence_unrecognized:M5:{source_path}")

    aggregate = _aggregate_case_records(records)
    approved_gates = [gate for gate in gates if gate["approved"]]
    support_approved = bool(approved_gates)
    verified_keys = aggregate["success_keys"] if support_approved else set()
    _finalize_live_summary(
        summary,
        aggregate,
        verified_keys=verified_keys,
        support_approved=support_approved,
        support_evidence=gates,
        support_missing="approved_world_model_feedback_gate_required",
    )
    return summary, errors


def _build_m6_live_evidence(
    payloads: list[tuple[str, dict]],
    min_repeats: int,
) -> tuple[dict, list[str]]:
    summary = _new_live_summary(
        "M6",
        "visual_trace_report",
        "visual_action_ablation",
        min_repeats,
    )
    summary["loaded_report_count"] = len(payloads)
    primary_records = []
    action_records = []
    ignored_builtin_count = 0
    errors = []
    for source_path, payload in payloads:
        if _is_m6_visual_action_report(payload):
            summary["support_report_count"] += 1
            for index, case in enumerate(_dict_cases(payload)):
                source_ref = str(case.get("source") or "").strip()
                if not source_ref or source_ref.lower() == "builtin":
                    ignored_builtin_count += 1
                    continue
                action_records.append(_assess_m6_action_case(source_path, index, case))
            continue
        if _is_m6_visual_trace_report(payload):
            summary["primary_report_count"] += 1
            for index, case in enumerate(_dict_cases(payload)):
                primary_records.append(_assess_m6_visual_case(source_path, index, case))
            continue
        errors.append(f"phase_evidence_unrecognized:M6:{source_path}")

    primary = _aggregate_case_records(primary_records)
    actions = _aggregate_case_records(action_records)
    verified_keys = primary["success_keys"].intersection(actions["success_keys"])
    support_approved = bool(actions["success_keys"])
    support_evidence = [{
        "approved": support_approved,
        "live_attempts": actions["attempts"],
        "live_successes": actions["successes"],
        "live_failures": actions["failures"],
        "evidence_refs": actions["evidence_refs"],
        "ignored_builtin_case_count": ignored_builtin_count,
        "cases": [_public_case_record(record) for record in action_records[:100]],
    }]
    summary["ignored_builtin_support_case_count"] = ignored_builtin_count
    summary["visual_action_success_count"] = actions["successes"]
    _finalize_live_summary(
        summary,
        primary,
        verified_keys=verified_keys,
        support_approved=support_approved,
        support_evidence=support_evidence,
        support_missing="matching_non_builtin_visual_action_ablation_required",
        verified_missing="needs_{count}_more_visual_action_linked_sessions",
    )
    return summary, errors


def _finalize_live_summary(
    summary: dict,
    aggregate: dict,
    verified_keys: set[str],
    support_approved: bool,
    support_evidence: list[dict],
    support_missing: str,
    verified_missing: str = "needs_{count}_more_distinct_successful_sessions",
) -> None:
    repeats = int(summary.get("repeats_required", 1) or 1)
    summary["attempts"] = aggregate["attempts"]
    summary["primary_successes"] = aggregate["successes"]
    summary["verified_successes"] = len(verified_keys)
    summary["failures"] = aggregate["failures"]
    summary["support_approved"] = bool(support_approved)
    summary["evidence_refs"] = [
        aggregate["ref_labels"].get(key, key)
        for key in sorted(verified_keys)
    ][:100]
    summary["primary_cases"] = [
        _public_case_record(record)
        for record in aggregate["records"][:100]
    ]
    summary["support_evidence"] = support_evidence[:100]

    missing = []
    if not aggregate["attempts"]:
        missing.append(f"{summary['primary_evidence_type']}_required")
    if aggregate["successes"] < repeats:
        missing.append(f"needs_{repeats - aggregate['successes']}_more_distinct_successful_sessions")
    if not support_approved:
        missing.append(support_missing)
    elif len(verified_keys) < repeats:
        missing.append(verified_missing.format(count=repeats - len(verified_keys)))
    summary["missing"] = list(dict.fromkeys(missing))

    if not aggregate["attempts"]:
        summary["status"] = "not_run"
    elif not aggregate["successes"]:
        summary["status"] = "failing"
    elif not verified_keys:
        summary["status"] = "partial"
    elif len(verified_keys) >= repeats:
        summary["status"] = "repeat_verified"
    else:
        summary["status"] = "live_observed"


def _aggregate_case_records(records: list[dict]) -> dict:
    grouped = {}
    labels = {}
    for record in records:
        key = record["source_key"]
        grouped.setdefault(key, []).append(record)
        labels.setdefault(key, record["source_ref"])
    success_keys = {
        key
        for key, items in grouped.items()
        if items and all(item.get("success") for item in items)
    }
    return {
        "attempts": len(grouped),
        "successes": len(success_keys),
        "failures": len(grouped) - len(success_keys),
        "success_keys": success_keys,
        "evidence_refs": [labels[key] for key in sorted(success_keys)],
        "ref_labels": labels,
        "records": records,
    }


def _assess_m3_case(source_path: str, index: int, case: dict) -> dict:
    source_ref, source_key = _case_source_ref(case.get("source_log"), source_path, index)
    checks = {
        "source_log_present": bool(str(case.get("source_log") or "").strip()),
        "ready_for_continual_learning_review": case.get("ready_for_continual_learning_review") is True,
        "completed_goal": _as_int(case.get("completed_goal_count")) >= 1,
        "memory_read": _as_int(case.get("memory_read_count")) >= 1,
        "memory_write": _as_int(case.get("memory_write_count")) >= 1,
        "progress_signal": _as_int(case.get("progress_event_count")) >= 1,
        "bounded_context": (
            "unbounded_context_cycle_count" in case
            and _as_int(case.get("unbounded_context_cycle_count")) == 0
        ),
    }
    return _case_assessment(
        source_path,
        source_ref,
        source_key,
        checks,
        {
            "completed_goal_count": _as_int(case.get("completed_goal_count")),
            "memory_read_count": _as_int(case.get("memory_read_count")),
            "memory_write_count": _as_int(case.get("memory_write_count")),
            "progress_event_count": _as_int(case.get("progress_event_count")),
            "unbounded_context_cycle_count": _as_int(case.get("unbounded_context_cycle_count")),
        },
    )


def _assess_m5_case(source_path: str, index: int, case: dict) -> dict:
    source_ref, source_key = _case_source_ref(case.get("source_log"), source_path, index)
    discovery_count = sum(
        len(value) if isinstance(value, list) else 0
        for value in (
            case.get("unique_block_types"),
            case.get("unique_entity_types"),
            case.get("unique_resource_types"),
        )
    )
    plan_signal_count = _as_int(case.get("multi_step_plan_count")) + _as_int(case.get("multi_hop_goal_count"))
    autonomous_goal_count = _as_int(case.get("auto_goal_count")) + _as_int(case.get("curriculum_goal_count"))
    checks = {
        "source_log_present": bool(str(case.get("source_log") or "").strip()),
        "ready_for_exploration_review": case.get("ready_for_exploration_review") is True,
        "completed_goal": _as_int(case.get("completed_goal_count")) >= 1,
        "distinct_positions": _as_int(case.get("unique_position_count")) >= 3,
        "minimum_path_distance": _as_float(case.get("path_distance")) >= EXPLORATION_MIN_DISTANCE,
        "multi_step_or_multi_hop_plan": plan_signal_count >= 1,
        "autonomous_or_curriculum_goal": autonomous_goal_count >= 1,
        "world_discovery": discovery_count >= 1,
    }
    return _case_assessment(
        source_path,
        source_ref,
        source_key,
        checks,
        {
            "completed_goal_count": _as_int(case.get("completed_goal_count")),
            "unique_position_count": _as_int(case.get("unique_position_count")),
            "path_distance": _as_float(case.get("path_distance")),
            "plan_signal_count": plan_signal_count,
            "autonomous_goal_count": autonomous_goal_count,
            "discovery_count": discovery_count,
        },
    )


def _assess_m6_visual_case(source_path: str, index: int, case: dict) -> dict:
    source_ref, source_key = _case_source_ref(case.get("source_log"), source_path, index)
    checks = {
        "source_log_present": bool(str(case.get("source_log") or "").strip()),
        "ready_for_visual_ablation": case.get("ready_for_visual_ablation") is True,
        "verified_screenshot": _as_int(case.get("screenshot_count")) >= 1,
        "no_missing_screenshots": (
            "missing_screenshot_count" in case
            and _as_int(case.get("missing_screenshot_count")) == 0
        ),
        "no_invalid_screenshots": (
            "invalid_screenshot_count" in case
            and _as_int(case.get("invalid_screenshot_count")) == 0
        ),
        "visual_analysis": _as_int(case.get("visual_analysis_count")) >= 1,
        "goal_uses_visual_evidence": _as_int(case.get("goals_with_visual_evidence")) >= 1,
    }
    return _case_assessment(
        source_path,
        source_ref,
        source_key,
        checks,
        {
            "screenshot_count": _as_int(case.get("screenshot_count")),
            "missing_screenshot_count": _as_int(case.get("missing_screenshot_count")),
            "invalid_screenshot_count": _as_int(case.get("invalid_screenshot_count")),
            "visual_analysis_count": _as_int(case.get("visual_analysis_count")),
            "goals_with_visual_evidence": _as_int(case.get("goals_with_visual_evidence")),
        },
    )


def _assess_m6_action_case(source_path: str, index: int, case: dict) -> dict:
    source_ref, source_key = _case_source_ref(case.get("source"), source_path, index)
    expected_phase = str(case.get("expected_phase") or "").strip()
    enabled_phases = case.get("enabled_phases", {}) if isinstance(case.get("enabled_phases", {}), dict) else {}
    checks = {
        "live_source": bool(source_ref) and source_ref.lower() != "builtin",
        "ablation_passed": case.get("passed") is True,
        "actions_changed": case.get("changed") is True,
        "enabled_helped": case.get("enabled_helped") is True,
        "intervention_replayed": _as_int(case.get("enabled_interventions")) >= 1,
        "expected_phase_present": bool(expected_phase),
        "expected_phase_observed": bool(expected_phase) and _as_int(enabled_phases.get(expected_phase)) >= 1,
    }
    return _case_assessment(
        source_path,
        source_ref,
        source_key,
        checks,
        {
            "enabled_interventions": _as_int(case.get("enabled_interventions")),
            "expected_phase": expected_phase,
            "enabled_phases": enabled_phases,
        },
    )


def _case_assessment(
    report_path: str,
    source_ref: str,
    source_key: str,
    checks: dict[str, bool],
    metrics: dict,
) -> dict:
    failed = [name for name, passed in checks.items() if not passed]
    return {
        "report_path": report_path,
        "source_ref": source_ref,
        "source_key": source_key,
        "success": not failed,
        "failed_criteria": failed,
        "metrics": metrics,
    }


def _public_case_record(record: dict) -> dict:
    return {
        key: value
        for key, value in record.items()
        if key != "source_key"
    }


def _assess_m3_transfer_gate(source_path: str, payload: dict) -> dict:
    thresholds = payload.get("thresholds", {}) if isinstance(payload.get("thresholds", {}), dict) else {}
    checks = {
        "readiness_approved": str(payload.get("readiness") or "").lower() == "approved",
        "promotion_allowed": payload.get("decision") == "allow_candidate_promotion",
        "passing_transfer_evidence": _as_int(payload.get("evidence_count")) >= 1,
        "no_transfer_regression": (
            "regression_count" in payload
            and _as_int(payload.get("regression_count")) == 0
        ),
        "ready_stream": _as_int(payload.get("ready_stream_count")) >= 1,
        "task_evidence": _as_int(payload.get("task_count")) >= 1,
        "heldout_required": thresholds.get("require_heldout") is True,
        "heldout_generalization_measured": _as_optional_float(payload.get("average_generalization_gain")) is not None,
    }
    failed = [name for name, passed in checks.items() if not passed]
    return {
        "report_path": source_path,
        "approved": not failed,
        "failed_criteria": failed,
        "readiness": payload.get("readiness"),
        "decision": payload.get("decision"),
        "ready_stream_count": _as_int(payload.get("ready_stream_count")),
        "task_count": _as_int(payload.get("task_count")),
        "average_generalization_gain": _as_optional_float(payload.get("average_generalization_gain")),
    }


def _assess_m5_world_model_gate(source_path: str, payload: dict) -> dict:
    structured_count = _as_int(payload.get("structured_frontier_count")) + _as_int(payload.get("structured_hotspot_count"))
    checks = {
        "readiness_approved": str(payload.get("readiness") or "").lower() == "approved",
        "feedback_allowed": payload.get("decision") == "allow_world_model_feedback",
        "source_report_present": _as_int(payload.get("source_count")) >= 1,
        "ready_world_model_log": _as_int(payload.get("ready_log_count")) >= 1,
        "actionable_feedback": _as_int(payload.get("actionable_item_count")) >= 1,
        "structured_map_evidence": structured_count >= 1,
    }
    failed = [name for name, passed in checks.items() if not passed]
    return {
        "report_path": source_path,
        "approved": not failed,
        "failed_criteria": failed,
        "readiness": payload.get("readiness"),
        "decision": payload.get("decision"),
        "ready_log_count": _as_int(payload.get("ready_log_count")),
        "actionable_item_count": _as_int(payload.get("actionable_item_count")),
        "structured_map_evidence_count": structured_count,
    }


def _is_m3_continual_report(payload: dict) -> bool:
    return payload.get("type") == "continual_learning_report" or (
        "continual_learning_feedback" in payload
        or _cases_have(payload, "ready_for_continual_learning_review")
    )


def _is_m3_transfer_gate(payload: dict) -> bool:
    return payload.get("type") == "task_stream_transfer_gate" or (
        "transfer_report_count" in payload
        and "readiness" in payload
        and "decision" in payload
        and "thresholds" in payload
    )


def _is_m5_exploration_report(payload: dict) -> bool:
    return payload.get("type") == "exploration_trace_report" or (
        "curriculum_feedback" in payload
        or _cases_have(payload, "ready_for_exploration_review")
    )


def _is_m5_world_model_gate(payload: dict) -> bool:
    return payload.get("type") == "world_model_feedback_gate" or (
        "structured_frontier_count" in payload
        and "actionable_item_count" in payload
        and "decision" in payload
    )


def _is_m6_visual_trace_report(payload: dict) -> bool:
    return payload.get("type") == "visual_trace_report" or (
        "screenshot_log_count" in payload
        and "goals_with_visual_evidence_count" in payload
    ) or _cases_have(payload, "ready_for_visual_ablation")


def _is_m6_visual_action_report(payload: dict) -> bool:
    return payload.get("type") == "visual_action_ablation_report" or (
        "passed_count" in payload
        and "changed_count" in payload
        and "helped_count" in payload
        and (_cases_have(payload, "enabled_interventions") or not _dict_cases(payload))
    )


def _dict_cases(payload: dict) -> list[dict]:
    cases = payload.get("cases", []) if isinstance(payload, dict) else []
    return [case for case in cases if isinstance(case, dict)] if isinstance(cases, list) else []


def _cases_have(payload: dict, key: str) -> bool:
    return any(key in case for case in _dict_cases(payload))


def _case_source_ref(raw_ref, report_path: str, index: int) -> tuple[str, str]:
    source_ref = str(raw_ref or "").strip()
    if source_ref:
        return source_ref, _source_ref_key(source_ref)
    fallback = f"{report_path}#case-{index + 1}"
    return fallback, _source_ref_key(fallback)


def _source_ref_key(source_ref: str) -> str:
    text = str(source_ref or "").strip()
    if not text:
        return ""
    try:
        return os.path.normcase(os.path.abspath(os.path.normpath(text)))
    except Exception:
        return text.casefold()


def _as_int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _as_float(value) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _as_optional_float(value) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _load_declared_status(status_path: str) -> tuple[dict, list[str]]:
    if not status_path:
        return {}, []
    path = Path(status_path)
    if not path.is_file():
        return {}, [f"status_file_missing:{status_path}"]
    try:
        text = path.read_text(encoding="utf-8-sig")
    except Exception as exc:
        return {}, [f"status_file_unreadable:{status_path}:{exc}"]
    rows = {}
    row_pattern = re.compile(
        r"^\|\s*(M[0-7])\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|",
        flags=re.MULTILINE,
    )
    for match in row_pattern.finditer(text):
        phase_id, name, status, progress = match.groups()
        rows[phase_id] = {
            "name": _clean_markdown(name),
            "status": _clean_markdown(status),
            "progress": _clean_markdown(progress),
        }
    return rows, [] if rows else [f"status_table_missing:{status_path}"]


def _clean_markdown(value: str) -> str:
    return re.sub(r"[*_`]", "", str(value or "")).strip()


def _declared_complete(declaration: dict) -> bool:
    status = str(declaration.get("status") or "").lower()
    progress = str(declaration.get("progress") or "").lower()
    return "complete" in status or progress.startswith("100")


def _load_benchmark_records(paths: Iterable[str]) -> tuple[list[dict], list[str], list[str]]:
    records = []
    errors = []
    loaded_paths = []
    seen = set()
    for raw_path in paths:
        path_text = str(raw_path or "").strip()
        if not path_text:
            continue
        path = Path(path_text)
        if not path.is_file():
            errors.append(f"benchmark_results_missing:{path_text}")
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            errors.append(f"benchmark_results_unreadable:{path_text}:{exc}")
            continue
        loaded_paths.append(path_text)
        for record_path, record in _walk_records(payload):
            normalized = _normalize_execution_record(record, path_text, record_path)
            if not normalized:
                continue
            run_ref = normalized.get("run_ref") or f"{path_text}:{record_path}"
            key = (normalized["task_id"], run_ref)
            if key in seen:
                continue
            seen.add(key)
            records.append(normalized)
    return records, errors, loaded_paths


def _walk_records(value, path: str = "$"):
    if isinstance(value, dict):
        yield path, value
        for key, child in value.items():
            yield from _walk_records(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_records(child, f"{path}[{index}]")


def _normalize_execution_record(record: dict, source_path: str, record_path: str) -> dict:
    task_id = str(record.get("task_id") or record.get("benchmark_id") or "").upper().strip()
    if not re.fullmatch(r"BM-\d+", task_id):
        return {}
    if not EXECUTION_FIELDS.intersection(record):
        return {}
    status = str(record.get("status") or record.get("outcome") or "").lower().strip()
    success_value = record.get("success")
    completed_value = record.get("completed")
    if status in SUCCESS_STATUSES or success_value is True or completed_value is True:
        outcome = "success"
    elif status in FAILURE_STATUSES or success_value is False or completed_value is False:
        outcome = "failure"
    else:
        return {}
    run_ref = str(
        record.get("session_id")
        or record.get("session_log")
        or record.get("log")
        or ""
    ).strip()
    return {
        "task_id": task_id,
        "outcome": outcome,
        "status": status,
        "run_ref": run_ref,
        "source_path": source_path,
        "record_path": record_path,
    }


def _summarize_benchmarks(records: list[dict]) -> dict:
    stats = {}
    for record in records:
        item = stats.setdefault(record["task_id"], {
            "attempts": 0,
            "successes": 0,
            "failures": 0,
            "evidence_refs": [],
        })
        item["attempts"] += 1
        item["successes" if record["outcome"] == "success" else "failures"] += 1
        ref = record.get("run_ref") or f"{record['source_path']}:{record['record_path']}"
        if ref not in item["evidence_refs"]:
            item["evidence_refs"].append(ref)
    return stats


def _benchmark_status(task_id: str, stats: dict, min_repeats: int) -> dict:
    attempts = int(stats.get("attempts", 0) or 0)
    successes = int(stats.get("successes", 0) or 0)
    failures = int(stats.get("failures", 0) or 0)
    if successes >= min_repeats:
        status = "repeat_verified"
    elif successes >= 1:
        status = "live_observed"
    elif attempts:
        status = "failing"
    else:
        status = "not_run"
    return {
        "task_id": task_id,
        "status": status,
        "attempts": attempts,
        "successes": successes,
        "failures": failures,
        "repeats_required": min_repeats,
        "evidence_refs": list(stats.get("evidence_refs", []))[:20],
    }


def _phase_status(
    evidence_kind: str,
    source_ready: bool,
    tasks: list[dict],
    min_repeats: int,
    live_evidence: Optional[dict] = None,
) -> str:
    if evidence_kind == "source":
        return "source_verified" if source_ready else "source_incomplete"
    if evidence_kind == "live_report":
        return str((live_evidence or {}).get("status") or "not_run")
    if not tasks or not any(task["attempts"] for task in tasks):
        return "not_run"
    if all(task["successes"] >= min_repeats for task in tasks):
        return "repeat_verified"
    if all(task["successes"] >= 1 for task in tasks):
        return "live_observed"
    if any(task["attempts"] and not task["successes"] for task in tasks):
        return "failing"
    return "partial"


def _claim_assessment(declared_complete: bool, status: str) -> str:
    if not declared_complete:
        return "not_claimed_complete"
    if status in {"source_verified", "repeat_verified"}:
        return "supported"
    if status in {"source_incomplete", "failing"}:
        return "contradicted"
    return "unsupported"


def _missing_phase_evidence(
    spec: dict,
    status: str,
    tasks: list[dict],
    source_checks: list[dict],
    min_repeats: int,
    live_evidence: Optional[dict] = None,
) -> list[str]:
    if status in {"source_verified", "repeat_verified"}:
        return []
    if spec["evidence_kind"] == "source":
        return [f"missing_source:{check['path']}" for check in source_checks if not check["exists"]]
    if spec["evidence_kind"] == "live_report":
        return list((live_evidence or {}).get("missing", []))
    missing = []
    for task in tasks:
        if task["successes"] < min_repeats:
            missing.append(f"{task['task_id']}:needs_{min_repeats - task['successes']}_more_successes")
    return missing


def _recommendations(report: dict) -> list[str]:
    recommendations = []
    runtime = report.get("runtime_evidence", {})
    if runtime and not runtime.get("ok"):
        recommendations.append("restore_live_minecraft_preflight_before_new_capability_claims")
    for phase in report.get("phases", []):
        phase_id = phase["id"].lower()
        if phase["claim_assessment"] in {"contradicted", "unsupported"}:
            recommendations.append(f"downgrade_{phase_id}_completion_claim_until_evidence_passes")
        if phase["status"] == "failing":
            suffix = "live_evidence" if phase.get("evidence_kind") == "live_report" else "benchmarks"
            recommendations.append(f"diagnose_and_rerun_{phase_id}_{suffix}")
        elif phase["status"] == "not_run":
            if phase.get("evidence_kind") == "live_report":
                recommendations.append(f"collect_{phase_id}_live_evidence")
            else:
                recommendations.append(f"run_{phase_id}_benchmarks")
        elif phase["status"] == "partial":
            recommendations.append(f"complete_{phase_id}_live_evidence_contract")
        elif phase["status"] == "live_observed":
            suffix = "live_evidence" if phase.get("evidence_kind") == "live_report" else "benchmarks"
            recommendations.append(f"repeat_{phase_id}_{suffix}_to_policy_minimum")
    return list(dict.fromkeys(recommendations))
