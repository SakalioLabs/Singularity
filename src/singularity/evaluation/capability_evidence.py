"""Evidence ledger for Minecraft Agent capability claims."""

from __future__ import annotations

import json
import hashlib
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from singularity.evaluation.m1_protocol import (
    PROTOCOL as M1_PROTOCOL,
    PROTOCOL_SHA256 as M1_PROTOCOL_SHA256,
    TASKS_BY_ID as M1_TASKS_BY_ID,
    action_transition_proof,
    inventory_counts,
)
from singularity.evaluation.m2_protocol import (
    PROTOCOL as M2_PROTOCOL,
    PROTOCOL_SHA256 as M2_PROTOCOL_SHA256,
    TASKS_BY_ID as M2_TASKS_BY_ID,
)
from singularity.evaluation.m4_protocol import (
    PROTOCOL_SHA256 as M4_PROTOCOL_SHA256,
    evaluate_bm011_episode,
)


SUCCESS_STATUSES = {"success", "succeeded", "pass", "passed", "complete", "completed"}
FAILURE_STATUSES = {"fail", "failed", "error", "blocked", "timeout", "rejected"}
LIVE_PHASE_IDS = ("M3", "M5", "M6")
EXPLORATION_MIN_DISTANCE = 16.0
CANONICAL_PHASE_STATUSES = {
    "source_verified",
    "repeat_verified",
    "live_observed",
    "partial",
    "failing",
    "not_run",
    "source_incomplete",
}
README_BADGE_STATUS = {
    "source_verified": "Source%20Verified",
    "repeat_verified": "Repeat%20Verified",
    "live_observed": "Live%20Observed",
    "partial": "Partial",
    "failing": "Live%20Failing",
    "not_run": "Not%20Run",
    "source_incomplete": "Source%20Incomplete",
}
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
EXECUTION_BOUNDARY_FIELDS = EXECUTION_FIELDS - {"success", "completed"}
M1_TASK_IDS = set(M1_TASKS_BY_ID)
M2_TASK_IDS = set(M2_TASKS_BY_ID)
M4_TASK_IDS = {"BM-011", "BM-012", "BM-013", "BM-014"}

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
            "src/singularity/evaluation/m2_protocol.py",
            "src/singularity/data/m2_protocol.json",
            "src/singularity/evaluation/benchmark_runner.py",
            "src/bot/bot_server.js",
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
    source_root_path = Path(source_root).resolve()
    status_file, status_display, status_path_error = _resolve_repository_input(status_path, source_root_path)
    declared, status_errors = _load_declared_status(str(status_file))
    if status_path_error:
        status_errors.append(status_path_error)
    records, load_errors, loaded_paths = _load_benchmark_records(
        benchmark_result_paths or [],
        source_root=source_root_path,
    )
    benchmark_stats = _summarize_benchmarks(records)
    m2_pairing_gate = _build_m2_pairing_gate(records, min_repeats)
    live_evidence, live_errors, loaded_phase_paths = _load_live_phase_evidence(
        phase_evidence_paths or {},
        min_repeats=min_repeats,
        source_root=source_root_path,
    )
    evidence_files = _build_evidence_file_manifest(
        source_root=source_root_path,
        benchmark_result_paths=loaded_paths,
        phase_evidence_paths=loaded_phase_paths,
        benchmark_records=records,
        live_evidence=live_evidence,
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
        benchmark_gate = {}
        if spec["id"] == "M2":
            benchmark_gate = m2_pairing_gate
            if status == "repeat_verified" and not benchmark_gate.get("approved"):
                status = "partial"
        declaration = declared.get(spec["id"], {})
        declared_complete = _declared_complete(declaration)
        claim_assessment = _claim_assessment(declared_complete, status)
        missing_evidence = _missing_phase_evidence(
            spec,
            status,
            task_stats,
            source_checks,
            min_repeats,
            live_evidence=phase_live_evidence,
        )
        if spec["id"] == "M2" and not benchmark_gate.get("approved"):
            missing_evidence.extend(benchmark_gate.get("missing", []))
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
            "benchmark_gate": benchmark_gate,
            "required_live_execution_count": min_repeats if spec["evidence_kind"] == "live_report" else 0,
            "live_observed_execution_count": int(phase_live_evidence.get("verified_successes", 0) or 0),
            "missing_evidence": list(dict.fromkeys(missing_evidence)),
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
                "M2": "three distinct eligible live sessions per task plus three complete skill-off/skill-on pairs for BM-006 and BM-007",
                "M3": "three distinct successful continual-learning sessions plus an approved held-out transfer gate",
                "M4": "three distinct independently eligible fresh m4-fixed-v1 episode bundles per BM-011 through BM-014",
                "M5": f"three distinct autonomous exploration sessions covering at least {EXPLORATION_MIN_DISTANCE:g} blocks plus an approved world-model gate",
                "M6": "three distinct screenshot-backed sessions with matching non-builtin visual-action ablations",
            },
        },
        "inputs": {
            "status_path": status_display,
            "source_root": ".",
            "benchmark_result_paths": loaded_paths,
            "phase_evidence_paths": loaded_phase_paths,
        },
        "evidence_files": evidence_files,
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


def audit_capability_document_consistency(
    report: dict,
    status_path: str = "workspace/STATUS.md",
    progress_path: str = "workspace/PROGRESS.md",
    readme_path: str = "README.md",
) -> dict:
    expected = {
        str(phase.get("id") or ""): str(phase.get("status") or "")
        for phase in report.get("phases", [])
        if isinstance(phase, dict)
    }
    documents = {
        "status": _markdown_phase_statuses(status_path),
        "progress": _markdown_phase_statuses(progress_path),
        "readme": _readme_badge_statuses(readme_path),
    }
    errors = []
    for document, statuses in documents.items():
        for phase_id, expected_status in expected.items():
            observed = statuses.get(phase_id)
            if observed != expected_status:
                errors.append(
                    f"{document}_status_mismatch:{phase_id}:expected={expected_status}:observed={observed or 'missing'}"
                )
    return {
        "consistent": not errors,
        "expected": expected,
        "documents": documents,
        "errors": errors,
    }


def _markdown_phase_statuses(path: str) -> dict[str, str]:
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except Exception:
        return {}
    statuses = {}
    for line in text.splitlines():
        match = re.match(r"^\|\s*(M[0-7])\s*\|", line)
        if not match:
            continue
        phase_id = match.group(1)
        observed = next(
            (status for status in CANONICAL_PHASE_STATUSES if f"`{status}`" in line),
            "",
        )
        if observed:
            statuses[phase_id] = observed
    return statuses


def _readme_badge_statuses(path: str) -> dict[str, str]:
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except Exception:
        return {}
    statuses = {}
    for phase_id in (f"M{index}" for index in range(8)):
        for status, badge_text in README_BADGE_STATUS.items():
            if f"badge/{phase_id}-{badge_text}-" in text:
                statuses[phase_id] = status
                break
    return statuses


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


def _portable_reference(value) -> str:
    return str(value or "").strip().replace("\\", "/")


def _resolve_repository_input(raw_path, source_root: Path) -> tuple[Path, str, str]:
    raw_text = str(raw_path or "").strip()
    portable = _portable_reference(raw_text)
    candidate = Path(raw_text)
    if not candidate.is_absolute():
        candidate = source_root / Path(portable)
    resolved = candidate.resolve()
    try:
        display = resolved.relative_to(source_root.resolve()).as_posix()
    except ValueError:
        return resolved, portable, f"evidence_path_outside_repository:{portable}"
    return resolved, display, ""


def _m3_source_log_contract(source_ref: str, case: dict, source_root: Path) -> dict:
    expected_session_id = str(case.get("source_session_id") or "").strip()
    raw_path = str(case.get("source_log") or source_ref or "").strip()
    raw_candidate = Path(raw_path)
    path, display, path_error = _resolve_repository_input(raw_path, source_root)
    metadata = _session_log_metadata(path, display)
    profiles = metadata.pop("profiles", [])
    resets = metadata.pop("resets", [])
    goal_verifications = metadata.pop("goal_verifications", [])
    goal_ends = metadata.pop("goal_ends", [])
    skill_selections = metadata.pop("skill_selections", [])
    skill_outcomes = metadata.pop("skill_outcomes", [])
    actual_hash = metadata.get("content_sha256", "")
    actual_protocol = metadata.get("protocol_hash", "")
    actual_kind = metadata.get("evidence_kind", "")
    checks = {
        "source_log_repo_relative": not raw_candidate.is_absolute() and not path_error,
        "source_log_exists": path.is_file(),
        "source_session_declared": bool(expected_session_id),
        "source_session_matches": bool(expected_session_id)
        and metadata.get("session_id") == expected_session_id,
        "source_hash_declared": bool(
            re.fullmatch(r"[0-9a-f]{64}", str(case.get("source_log_sha256") or "").lower())
        ),
        "source_hash_matches": bool(actual_hash)
        and actual_hash == str(case.get("source_log_sha256") or "").lower(),
        "protocol_declared": case.get("protocol_sha256") == M1_PROTOCOL_SHA256,
        "protocol_matches": actual_protocol == M1_PROTOCOL_SHA256,
        "evidence_kind_declared": case.get("evidence_kind") == "live_minecraft_skill_research",
        "evidence_kind_matches": actual_kind == "live_minecraft_skill_research",
        "source_marked_eligible": case.get("eligibility") is True,
        "runtime_profile_present": any(
            profile.get("arm") == "runtime"
            and profile.get("protocol_sha256") == M1_PROTOCOL_SHA256
            and profile.get("evidence_kind") == "live_minecraft_skill_research"
            for profile in profiles
        ),
        "verified_reset_present": any(
            reset.get("success") is True
            and reset.get("protocol_sha256") == M1_PROTOCOL_SHA256
            for reset in resets
        ),
        "goal_verifier_achieved": any(
            item.get("achieved") is True or str(item.get("status") or "").lower() == "achieved"
            for item in goal_verifications
        ),
        "verified_goal_end_present": any(
            isinstance(item.get("result"), dict)
            and item["result"].get("completed") is True
            and item["result"].get("termination_reason") == "goal_verified"
            for item in goal_ends
        ),
        "skill_retrieval_present": bool(skill_selections),
        "skill_outcome_attributed": any(
            item.get("success") is True
            and float(item.get("attribution_confidence", 0.0) or 0.0) >= 0.9
            for item in skill_outcomes
        ),
    }
    eligibility = all(checks.values())
    return {
        "checks": checks,
        "repo_relative_path": display,
        "session_id": metadata.get("session_id", ""),
        "content_sha256": actual_hash,
        "protocol_hash": actual_protocol,
        "evidence_kind": actual_kind,
        "eligibility": eligibility,
    }


def _session_log_metadata(path: Path, display: str) -> dict:
    empty = {
        "repo_relative_path": display,
        "session_id": "",
        "session_ids": [],
        "content_sha256": "",
        "protocol_hash": "",
        "evidence_kind": "unknown",
        "profiles": [],
        "resets": [],
        "goal_verifications": [],
        "goal_ends": [],
        "skill_selections": [],
        "skill_outcomes": [],
    }
    if not path.is_file():
        return empty
    events = []
    try:
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if line.strip():
                event = json.loads(line)
                if isinstance(event, dict):
                    events.append(event)
    except Exception:
        return empty
    sessions = _unique_strings(event.get("session") for event in events)

    def event_data(*event_types: str) -> list[dict]:
        allowed = set(event_types)
        return [
            event.get("data", {})
            for event in events
            if event.get("type") in allowed and isinstance(event.get("data"), dict)
        ]

    profiles = event_data("skill_learning_runtime_profile", "benchmark_runtime_profile")
    resets = event_data("benchmark_reset")
    protocol_hashes = _unique_strings(
        item.get("protocol_sha256") for item in profiles + resets
        if item.get("protocol_sha256")
    )
    evidence_kinds = _unique_strings(
        item.get("evidence_kind") for item in profiles if item.get("evidence_kind")
    )
    return {
        **empty,
        "session_id": sessions[0] if len(sessions) == 1 else "",
        "session_ids": sessions,
        "content_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "protocol_hash": protocol_hashes[0] if len(protocol_hashes) == 1 else "",
        "evidence_kind": evidence_kinds[0] if len(evidence_kinds) == 1 else "unknown",
        "profiles": profiles,
        "resets": resets,
        "goal_verifications": event_data("goal_verification"),
        "goal_ends": event_data("goal_end"),
        "skill_selections": event_data("skill_selected"),
        "skill_outcomes": event_data("skill_execution_outcome"),
    }


def _build_evidence_file_manifest(
    source_root: Path,
    benchmark_result_paths: list[str],
    phase_evidence_paths: dict[str, list[str]],
    benchmark_records: list[dict],
    live_evidence: dict,
) -> list[dict]:
    entries: dict[str, dict] = {}

    def add_entry(
        repo_path: str,
        role: str,
        session_ids=None,
        protocol_hashes=None,
        evidence_kinds=None,
        eligibility: str = "eligible_input",
        counts_toward_repeat_verified: bool = False,
    ):
        path, display, path_error = _resolve_repository_input(repo_path, source_root)
        sessions = _unique_strings(session_ids or [])
        protocols = _unique_strings(protocol_hashes or [])
        kinds = _unique_strings(evidence_kinds or [])
        if display not in entries:
            entries[display] = {
                "repo_relative_path": display,
                "session_id": sessions[0] if len(sessions) == 1 else "multiple" if sessions else "not_applicable",
                "session_ids": sessions,
                "content_sha256": hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "",
                "protocol_hash": protocols[0] if len(protocols) == 1 else "multiple" if protocols else "unversioned",
                "protocol_hashes": protocols,
                "evidence_kind": kinds[0] if len(kinds) == 1 else "mixed" if kinds else "unknown",
                "evidence_kinds": kinds,
                "eligibility": "ineligible" if path_error or not path.is_file() else eligibility,
                "counts_toward_repeat_verified": bool(counts_toward_repeat_verified),
                "roles": [role],
            }
            return
        entry = entries[display]
        entry["session_ids"] = _unique_strings(entry["session_ids"] + sessions)
        entry["session_id"] = (
            entry["session_ids"][0]
            if len(entry["session_ids"]) == 1
            else "multiple" if entry["session_ids"] else "not_applicable"
        )
        entry["protocol_hashes"] = _unique_strings(entry["protocol_hashes"] + protocols)
        entry["protocol_hash"] = (
            entry["protocol_hashes"][0]
            if len(entry["protocol_hashes"]) == 1
            else "multiple" if entry["protocol_hashes"] else "unversioned"
        )
        entry["evidence_kinds"] = _unique_strings(entry["evidence_kinds"] + kinds)
        entry["evidence_kind"] = entry["evidence_kinds"][0] if len(entry["evidence_kinds"]) == 1 else "mixed"
        entry["counts_toward_repeat_verified"] = bool(
            entry["counts_toward_repeat_verified"] or counts_toward_repeat_verified
        )
        if role not in entry["roles"]:
            entry["roles"].append(role)

    for result_path in benchmark_result_paths:
        records = [record for record in benchmark_records if record.get("source_path") == result_path]
        outcomes = {record.get("outcome") for record in records}
        eligibility = (
            "eligible_success" if "success" in outcomes
            else "eligible_failure_evidence" if "failure" in outcomes
            else "ineligible"
        )
        add_entry(
            result_path,
            "benchmark_result",
            session_ids=[record.get("session_id") for record in records],
            protocol_hashes=[record.get("protocol_hash") for record in records],
            evidence_kinds=[record.get("evidence_kind") for record in records],
            eligibility=eligibility,
            counts_toward_repeat_verified="success" in outcomes,
        )
        for record in records:
            log_path = record.get("session_log")
            if not log_path:
                continue
            add_entry(
                log_path,
                "benchmark_source_session",
                session_ids=[record.get("session_id")],
                protocol_hashes=[record.get("protocol_hash")],
                evidence_kinds=[record.get("evidence_kind")],
                eligibility="eligible_success" if record.get("outcome") == "success" else str(record.get("outcome") or "ineligible"),
                counts_toward_repeat_verified=record.get("outcome") == "success",
            )

    for phase_id, paths in phase_evidence_paths.items():
        phase_summary = live_evidence.get(phase_id, {})
        case_records = list(phase_summary.get("primary_cases", []))
        support_records = list(phase_summary.get("support_evidence", []))
        for report_path in paths:
            report_file, _, _ = _resolve_repository_input(report_path, source_root)
            try:
                report_payload = json.loads(report_file.read_text(encoding="utf-8-sig"))
            except Exception:
                report_payload = {}
            primary = [item for item in case_records if item.get("report_path") == report_path]
            support = [item for item in support_records if item.get("report_path") == report_path]
            successful = bool(primary and any(item.get("success") for item in primary)) or bool(
                support and any(item.get("approved") for item in support)
            )
            sessions = []
            protocols = []
            kinds = []
            for item in primary:
                metrics = item.get("metrics", {}) if isinstance(item.get("metrics"), dict) else {}
                sessions.append(metrics.get("session_id"))
                protocols.append(metrics.get("protocol_hash"))
                kinds.append(metrics.get("evidence_kind"))
            for item in support:
                sessions.extend(item.get("heldout_source_session_ids", []))
                protocols.append(item.get("protocol_hash"))
                kinds.append(item.get("evidence_kind"))
            add_entry(
                report_path,
                f"{phase_id.lower()}_report_input",
                session_ids=sessions,
                protocol_hashes=protocols,
                evidence_kinds=(
                    [report_payload.get("type")]
                    if report_payload.get("type")
                    else kinds or [phase_summary.get("primary_evidence_type")]
                ),
                eligibility="eligible_input",
                counts_toward_repeat_verified=(
                    successful and phase_summary.get("status") == "repeat_verified"
                ),
            )
            for item in support:
                for session_id in item.get("heldout_source_session_ids", []):
                    session_path = f"logs/session_{session_id}.jsonl"
                    log_file, log_display, _ = _resolve_repository_input(session_path, source_root)
                    metadata = _session_log_metadata(log_file, log_display)
                    add_entry(
                        session_path,
                        f"{phase_id.lower()}_support_session",
                        session_ids=[session_id],
                        protocol_hashes=[metadata.get("protocol_hash") or item.get("protocol_hash")],
                        evidence_kinds=[metadata.get("evidence_kind") or item.get("evidence_kind")],
                        eligibility="eligible_support",
                        counts_toward_repeat_verified=bool(
                            item.get("approved") and phase_summary.get("status") == "repeat_verified"
                        ),
                    )
        for item in case_records:
            metrics = item.get("metrics", {}) if isinstance(item.get("metrics"), dict) else {}
            source_path = metrics.get("repo_relative_path")
            if not source_path:
                continue
            add_entry(
                source_path,
                f"{phase_id.lower()}_source_session",
                session_ids=[metrics.get("session_id")],
                protocol_hashes=[metrics.get("protocol_hash")],
                evidence_kinds=[metrics.get("evidence_kind")],
                eligibility="eligible_success" if item.get("success") else "ineligible",
                counts_toward_repeat_verified=bool(item.get("success")),
            )

    return [entries[path] for path in sorted(entries)]


def _unique_strings(values) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if str(value or "").strip()))


def _load_live_phase_evidence(
    phase_evidence_paths: dict[str, Iterable[str]],
    min_repeats: int,
    source_root: Path,
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
            normalized_paths.get(phase_id, []),
            source_root=source_root,
        )
        errors.extend(phase_errors)
        loaded_paths[phase_id] = phase_loaded_paths
        if phase_id == "M3":
            summary, adapter_errors = _build_m3_live_evidence(
                payloads,
                min_repeats,
                source_root=source_root,
            )
        elif phase_id == "M5":
            summary, adapter_errors = _build_m5_live_evidence(payloads, min_repeats)
        else:
            summary, adapter_errors = _build_m6_live_evidence(payloads, min_repeats)
        summaries[phase_id] = summary
        errors.extend(adapter_errors)
    return summaries, errors, loaded_paths


def _load_evidence_payloads(
    paths: Iterable[str],
    source_root: Path,
) -> tuple[list[tuple[str, dict]], list[str], list[str]]:
    payloads = []
    errors = []
    loaded_paths = []
    seen = set()
    for raw_path in paths:
        raw_text = str(raw_path or "").strip()
        if not raw_text:
            continue
        path, path_text, path_error = _resolve_repository_input(raw_text, source_root)
        if path_error:
            errors.append(path_error)
            continue
        path_key = os.path.normcase(str(path))
        if path_key in seen:
            continue
        seen.add(path_key)
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
    source_root: Optional[Path] = None,
) -> tuple[dict, list[str]]:
    source_root = (source_root or Path(".")).resolve()
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
                records.append(_assess_m3_case(
                    source_path,
                    index,
                    case,
                    source_root=source_root,
                    report_payload=payload,
                ))
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


def _assess_m3_case(
    source_path: str,
    index: int,
    case: dict,
    source_root: Path,
    report_payload: dict,
) -> dict:
    source_ref, source_key = _case_source_ref(case.get("source_log"), source_path, index)
    memory_read_count = _as_int(case.get("memory_read_count"))
    memory_write_count = _as_int(case.get("memory_write_count"))
    skill_retrieval_count = _as_int(case.get("skill_retrieval_count"))
    skill_outcome_write_count = _as_int(case.get("skill_outcome_write_count"))
    source_contract = _m3_source_log_contract(
        source_ref=source_ref,
        case=case,
        source_root=source_root,
    )
    checks = {
        "typed_continual_report": report_payload.get("type") == "continual_learning_report",
        "continual_report_schema": _as_int(report_payload.get("schema_version")) >= 2,
        "continual_report_errors_empty": not list(report_payload.get("errors", []) or []),
        "source_log_present": bool(str(case.get("source_log") or "").strip()),
        **source_contract["checks"],
        "ready_for_continual_learning_review": case.get("ready_for_continual_learning_review") is True,
        "completed_goal": _as_int(case.get("completed_goal_count")) >= 1,
        "memory_read": memory_read_count >= 1 or skill_retrieval_count >= 1,
        "memory_write": memory_write_count >= 1 or skill_outcome_write_count >= 1,
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
            "memory_read_count": memory_read_count,
            "memory_write_count": memory_write_count,
            "skill_retrieval_count": skill_retrieval_count,
            "skill_outcome_write_count": skill_outcome_write_count,
            "progress_event_count": _as_int(case.get("progress_event_count")),
            "unbounded_context_cycle_count": _as_int(case.get("unbounded_context_cycle_count")),
            "repo_relative_path": source_contract["repo_relative_path"],
            "session_id": source_contract["session_id"],
            "content_sha256": source_contract["content_sha256"],
            "protocol_hash": source_contract["protocol_hash"],
            "evidence_kind": source_contract["evidence_kind"],
            "eligibility": source_contract["eligibility"],
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
    heldout_sessions = _unique_strings(payload.get("heldout_source_session_ids", []))
    checks = {
        "typed_transfer_gate": payload.get("type") == "task_stream_transfer_gate",
        "transfer_gate_schema": _as_int(payload.get("schema_version")) >= 1,
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
        "heldout_sessions_distinct": len(heldout_sessions) >= 2,
        "training_heldout_disjoint": (
            "training_heldout_overlap_count" in payload
            and _as_int(payload.get("training_heldout_overlap_count")) == 0
        ),
        "source_report_fingerprinted": bool(
            re.fullmatch(r"[0-9a-f]{64}", str(payload.get("source_report_fingerprint") or "").lower())
        ),
        "protocol_declared": payload.get("protocol_sha256") == M1_PROTOCOL_SHA256,
        "evidence_kind_declared": payload.get("evidence_kind") == "live_minecraft_skill_research",
        "gate_marked_eligible": payload.get("eligibility") is True,
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
        "heldout_source_session_ids": heldout_sessions,
        "source_report_fingerprint": str(payload.get("source_report_fingerprint") or ""),
        "protocol_hash": str(payload.get("protocol_sha256") or ""),
        "evidence_kind": str(payload.get("evidence_kind") or "unknown"),
        "eligibility": not failed,
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
    source_ref = _portable_reference(raw_ref)
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


def _load_benchmark_records(
    paths: Iterable[str],
    source_root: Optional[Path] = None,
) -> tuple[list[dict], list[str], list[str]]:
    records = []
    errors = []
    loaded_paths = []
    source_root = (source_root or Path(".")).resolve()
    seen = set()
    seen_m1_sessions = set()
    seen_m1_hashes = set()
    seen_m1_episodes = set()
    seen_m2_sessions = set()
    seen_m2_hashes = set()
    seen_m2_episodes = set()
    seen_m4_sessions = set()
    seen_m4_hashes = set()
    seen_m4_episodes = set()
    seen_m4_levels = set()
    for raw_path in paths:
        raw_text = str(raw_path or "").strip()
        if not raw_text:
            continue
        path, path_text, path_error = _resolve_repository_input(raw_text, source_root)
        if path_error:
            errors.append(path_error)
            continue
        if not path.is_file():
            errors.append(f"benchmark_results_missing:{path_text}")
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            errors.append(f"benchmark_results_unreadable:{path_text}:{exc}")
            continue
        loaded_paths.append(path_text)
        if isinstance(payload, dict) and payload.get("type") == "m4_episode_eligibility":
            normalized = _normalize_m4_episode_bundle(payload, path, path_text, source_root)
            if normalized:
                if normalized["outcome"] == "success":
                    duplicate_reasons = []
                    for value, seen_values, reason in (
                        (normalized.get("session_id", ""), seen_m4_sessions, "duplicate_m4_session"),
                        (normalized.get("session_sha256", ""), seen_m4_hashes, "duplicate_m4_session_log"),
                        (normalized.get("episode_id", ""), seen_m4_episodes, "duplicate_m4_episode"),
                        (normalized.get("level_name", ""), seen_m4_levels, "duplicate_m4_level"),
                    ):
                        if not value or value in seen_values:
                            duplicate_reasons.append(reason)
                    if duplicate_reasons:
                        normalized["outcome"] = "ineligible"
                        normalized["eligibility_reasons"].extend(duplicate_reasons)
                    else:
                        seen_m4_sessions.add(normalized["session_id"])
                        seen_m4_hashes.add(normalized["session_sha256"])
                        seen_m4_episodes.add(normalized["episode_id"])
                        seen_m4_levels.add(normalized["level_name"])
                records.append(normalized)
            continue
        for record_path, record in _walk_records(payload):
            normalized = _normalize_execution_record(record, str(path), record_path)
            if not normalized:
                continue
            normalized["source_path"] = path_text
            run_ref = normalized.get("run_ref") or f"{path_text}:{record_path}"
            key = (normalized["task_id"], run_ref)
            if key in seen:
                continue
            seen.add(key)
            if normalized["outcome"] == "success" and normalized["task_id"] in M1_TASK_IDS:
                duplicate_reasons = []
                session_id = normalized.get("session_id", "")
                session_hash = normalized.get("session_sha256", "")
                episode_id = normalized.get("episode_id", "")
                if session_id in seen_m1_sessions:
                    duplicate_reasons.append("duplicate_m1_session")
                if session_hash in seen_m1_hashes:
                    duplicate_reasons.append("duplicate_m1_session_log")
                if episode_id in seen_m1_episodes:
                    duplicate_reasons.append("duplicate_m1_episode")
                if duplicate_reasons:
                    normalized["outcome"] = "ineligible"
                    normalized["eligibility_reasons"].extend(duplicate_reasons)
                else:
                    seen_m1_sessions.add(session_id)
                    seen_m1_hashes.add(session_hash)
                    seen_m1_episodes.add(episode_id)
            if normalized["outcome"] == "success" and normalized["task_id"] in M2_TASK_IDS:
                duplicate_reasons = []
                session_id = normalized.get("session_id", "")
                session_hash = normalized.get("session_sha256", "")
                episode_id = normalized.get("episode_id", "")
                if session_id in seen_m2_sessions:
                    duplicate_reasons.append("duplicate_m2_session")
                if session_hash in seen_m2_hashes:
                    duplicate_reasons.append("duplicate_m2_session_log")
                if episode_id in seen_m2_episodes:
                    duplicate_reasons.append("duplicate_m2_episode")
                if duplicate_reasons:
                    normalized["outcome"] = "ineligible"
                    normalized["eligibility_reasons"].extend(duplicate_reasons)
                else:
                    seen_m2_sessions.add(session_id)
                    seen_m2_hashes.add(session_hash)
                    seen_m2_episodes.add(episode_id)
            records.append(normalized)
    return records, errors, loaded_paths


def _normalize_m4_episode_bundle(
    eligibility: dict,
    eligibility_path: Path,
    source_path: str,
    source_root: Path,
) -> dict:
    task_id = str(eligibility.get("task_id") or "").upper().strip()
    if task_id != "BM-011":
        return {}
    episode_dir = eligibility_path.parent
    payloads = {}
    issues = []
    for name in ("preflight", "manifest", "session", "result"):
        path = episode_dir / f"{name}.json"
        try:
            payloads[name] = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            payloads[name] = [] if name == "session" else {}
            issues.append(f"m4_{name}_unavailable")
    manifest = payloads["manifest"] if isinstance(payloads["manifest"], dict) else {}
    events = payloads["session"] if isinstance(payloads["session"], list) else []
    result = payloads["result"] if isinstance(payloads["result"], dict) else {}
    preflight = payloads["preflight"] if isinstance(payloads["preflight"], dict) else {}
    independent = evaluate_bm011_episode(events, result, preflight, manifest)
    issues.extend(str(item) for item in independent.get("issues", []))
    if eligibility.get("profile") != "m4-fixed-v1":
        issues.append("m4_eligibility_profile_mismatch")
    if eligibility.get("protocol_sha256") != M4_PROTOCOL_SHA256:
        issues.append("m4_eligibility_protocol_mismatch")
    if manifest.get("protocol_sha256") != M4_PROTOCOL_SHA256:
        issues.append("m4_manifest_protocol_mismatch")
    stored_eligible = eligibility.get("eligible") is True and eligibility.get("success") is True
    independently_eligible = independent.get("eligible") is True and independent.get("success") is True
    if stored_eligible != independently_eligible:
        issues.append("m4_stored_independent_eligibility_mismatch")
    candidate_success = stored_eligible or result.get("completed") is True
    if stored_eligible and independently_eligible and not issues:
        outcome = "success"
    elif candidate_success:
        outcome = "ineligible"
    else:
        outcome = "failure"
    session_id = str(manifest.get("session_id") or "").strip()
    episode_id = str(manifest.get("episode_id") or "").strip()
    level_name = str(manifest.get("level_name") or "").strip()
    session_path = episode_dir / "session.json"
    try:
        session_display = session_path.resolve().relative_to(source_root.resolve()).as_posix()
    except ValueError:
        session_display = ""
        issues.append("m4_session_path_outside_repository")
        if outcome == "success":
            outcome = "ineligible"
    session_sha256 = hashlib.sha256(session_path.read_bytes()).hexdigest() if session_path.is_file() else ""
    if not session_id:
        issues.append("m4_session_id_missing")
    if not episode_id:
        issues.append("m4_episode_id_missing")
    if not level_name.startswith(f"{episode_id}_"):
        issues.append("m4_fresh_level_identity_missing")
    if not session_sha256:
        issues.append("m4_session_hash_missing")
    if issues and outcome == "success":
        outcome = "ineligible"
    return {
        "task_id": task_id,
        "outcome": outcome,
        "status": "pass" if candidate_success else "fail",
        "run_ref": f"{session_id}:{session_display}",
        "source_path": source_path,
        "record_path": "$",
        "eligibility_reasons": list(dict.fromkeys(issues)),
        "session_id": session_id,
        "session_sha256": session_sha256,
        "session_log": session_display,
        "protocol_hash": str(manifest.get("protocol_sha256") or "").lower().strip(),
        "evidence_kind": "live_minecraft_m4",
        "episode_id": episode_id,
        "level_name": level_name,
        "server_jar_sha256": str(manifest.get("runtime_versions", {}).get("server_jar_sha256") or "").lower(),
        "resolved_session_log": str(session_path.resolve()) if session_path.is_file() else "",
        "experiment_metadata": {},
        "m2_metrics": {},
    }


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
    if not EXECUTION_BOUNDARY_FIELDS.intersection(record):
        return {}
    status = str(record.get("status") or record.get("outcome") or "").lower().strip()
    success_value = record.get("success")
    completed_value = record.get("completed")
    candidate_success = status in SUCCESS_STATUSES or success_value is True or completed_value is True
    eligibility_reasons = []
    if candidate_success and task_id in M1_TASK_IDS:
        eligibility_reasons = _m1_live_eligibility_issues(record, source_path)
    if candidate_success and task_id in M2_TASK_IDS:
        eligibility_reasons = _m2_live_eligibility_issues(record, source_path)
    if candidate_success and task_id in M4_TASK_IDS:
        eligibility_reasons = ["m4_episode_bundle_required"]
    if candidate_success and not eligibility_reasons:
        outcome = "success"
    elif candidate_success:
        outcome = "ineligible"
    elif status in FAILURE_STATUSES or success_value is False or completed_value is False:
        outcome = "failure"
    else:
        return {}
    session_id = str(record.get("session_id") or "").strip()
    log_ref = _portable_reference(record.get("session_log") or record.get("log") or "")
    run_ref = ":".join(part for part in (session_id, log_ref) if part)
    setup = record.get("setup_evidence", {}) if isinstance(record.get("setup_evidence"), dict) else {}
    runtime = record.get("runtime_profile", {}) if isinstance(record.get("runtime_profile"), dict) else {}
    validation = record.get("evidence_validation", {}) if isinstance(record.get("evidence_validation"), dict) else {}
    experiment = record.get("experiment_metadata", {}) if isinstance(record.get("experiment_metadata"), dict) else {}
    return {
        "task_id": task_id,
        "outcome": outcome,
        "status": status,
        "run_ref": run_ref,
        "source_path": source_path,
        "record_path": record_path,
        "eligibility_reasons": eligibility_reasons,
        "session_id": session_id,
        "session_sha256": str(record.get("session_sha256") or "").lower().strip(),
        "session_log": log_ref,
        "protocol_hash": str(
            runtime.get("protocol_sha256")
            or setup.get("protocol_sha256")
            or ""
        ).lower().strip(),
        "evidence_kind": str(record.get("evidence_kind") or runtime.get("evidence_kind") or "unknown"),
        "episode_id": str(
            setup.get("episode_id")
        ).strip(),
        "server_jar_sha256": str(
            setup.get("server_jar_sha256")
        ).lower().strip(),
        "resolved_session_log": str(_resolve_evidence_path(log_ref, source_path) or ""),
        "experiment_metadata": experiment,
        "m2_metrics": {
            key: validation.get(key)
            for key in (
                "planner_call_count",
                "replan_count",
                "planner_token_usage",
                "planner_latency_ms",
                "action_event_count",
                "action_failure_count",
                "verifier_reject_count",
                "skill_selected_count",
                "skill_action_success_count",
                "fallback_count",
                "failure_replan_proved",
            )
            if key in validation
        },
    }


def _m1_live_eligibility_issues(record: dict, source_path: str) -> list[str]:
    issues = []
    task_id = str(record.get("task_id") or record.get("benchmark_id") or "").upper().strip()
    spec = M1_TASKS_BY_ID.get(task_id, {})
    if record.get("evidence_kind") != "live_minecraft":
        issues.append("evidence_kind_not_live_minecraft")
    if record.get("protocol_eligible") is not True:
        issues.append("protocol_eligible_not_true")
    if record.get("goal_verified") is not True:
        issues.append("goal_verified_not_true")
    if record.get("criteria_verified") is not True:
        issues.append("criteria_verified_not_true")

    setup = record.get("setup_evidence", {}) if isinstance(record.get("setup_evidence"), dict) else {}
    validation = record.get("evidence_validation", {}) if isinstance(record.get("evidence_validation"), dict) else {}
    runtime = record.get("runtime_profile", {}) if isinstance(record.get("runtime_profile"), dict) else {}
    if setup.get("success") is not True:
        issues.append("benchmark_reset_not_successful")
    if setup.get("task_id") != task_id:
        issues.append("benchmark_reset_task_mismatch")
    if str(setup.get("seed") or "") != str(M1_PROTOCOL["world_seed"]):
        issues.append("benchmark_reset_seed_mismatch")
    if setup.get("observed_minecraft_version") != M1_PROTOCOL["minecraft_version"]:
        issues.append("benchmark_minecraft_version_mismatch")
    if "paper" not in str(setup.get("server_brand") or "").lower():
        issues.append("benchmark_server_brand_not_paper")
    server_hash = str(setup.get("server_jar_sha256") or "").lower()
    if server_hash != M1_PROTOCOL["server_jar_sha256"]:
        issues.append("benchmark_server_jar_hash_mismatch")
    checks = setup.get("checks", {}) if isinstance(setup.get("checks"), dict) else {}
    if not checks or any(value is not True for name, value in checks.items() if name != "position_distance"):
        issues.append("benchmark_reset_checks_not_verified")
    expected_initial = inventory_counts(spec.get("initial_inventory", {}))
    observed_initial = inventory_counts(
        setup.get("after_state", {}).get("inventory", {})
        if isinstance(setup.get("after_state"), dict)
        else {}
    )
    if observed_initial != expected_initial:
        issues.append("benchmark_reset_inventory_mismatch")
    episode_id = str(setup.get("episode_id") or "")
    level_name = str(setup.get("level_name") or "")
    if not episode_id or not level_name.startswith(f"{episode_id}_"):
        issues.append("fresh_episode_level_not_proven")
    if validation.get("passed") is not True:
        issues.append("session_evidence_validation_not_passed")
    if runtime.get("isolated") is not True:
        issues.append("m1_runtime_not_isolated")
    if runtime.get("agent_id") != M1_PROTOCOL["agent_id"]:
        issues.append("m1_agent_identity_mismatch")
    if runtime.get("planner_id") != M1_PROTOCOL["planner_id"]:
        issues.append("m1_planner_identity_mismatch")
    if runtime.get("action_backend_id") != M1_PROTOCOL["action_backend_id"]:
        issues.append("m1_action_backend_identity_mismatch")
    if runtime.get("verifier_id") != M1_PROTOCOL["verifier_id"]:
        issues.append("m1_verifier_identity_mismatch")
    for name, payload in (("setup", setup), ("validation", validation), ("runtime", runtime)):
        if payload.get("protocol_sha256") != M1_PROTOCOL_SHA256:
            issues.append(f"{name}_protocol_hash_mismatch")

    final_inventory = inventory_counts(record.get("inventory", record.get("inventory_snapshot", {})))
    if not all(final_inventory.get(item, 0) >= int(count) for item, count in spec.get("success_criteria", {}).items()):
        issues.append("terminal_inventory_criteria_not_observed")

    session_id = str(record.get("session_id") or "").strip()
    log_ref = str(record.get("session_log") or record.get("log") or "").strip()
    if not session_id:
        issues.append("session_id_missing")
    if not log_ref:
        issues.append("session_log_missing")
        return issues
    log_path = _resolve_evidence_path(log_ref, source_path)
    if log_path is None:
        issues.append("session_log_unavailable")
        return issues
    expected_hash = str(record.get("session_sha256") or "").lower()
    actual_hash = hashlib.sha256(log_path.read_bytes()).hexdigest()
    if expected_hash != actual_hash:
        issues.append("session_log_hash_mismatch")
    issues.extend(_m1_session_log_issues(log_path, session_id, task_id))
    return list(dict.fromkeys(issues))


def _m2_live_eligibility_issues(record: dict, source_path: str) -> list[str]:
    issues = []
    task_id = str(record.get("task_id") or record.get("benchmark_id") or "").upper().strip()
    if record.get("evidence_kind") != "live_minecraft":
        issues.append("evidence_kind_not_live_minecraft")
    if record.get("protocol_eligible") is not True:
        issues.append("protocol_eligible_not_true")
    if record.get("goal_verified") is not True:
        issues.append("goal_verified_not_true")
    if record.get("criteria_verified") is not True:
        issues.append("criteria_verified_not_true")

    setup = record.get("setup_evidence", {}) if isinstance(record.get("setup_evidence"), dict) else {}
    terminal = record.get("terminal_evidence", {}) if isinstance(record.get("terminal_evidence"), dict) else {}
    validation = record.get("evidence_validation", {}) if isinstance(record.get("evidence_validation"), dict) else {}
    runtime = record.get("runtime_profile", {}) if isinstance(record.get("runtime_profile"), dict) else {}
    experiment = record.get("experiment_metadata", {}) if isinstance(record.get("experiment_metadata"), dict) else {}
    if setup.get("success") is not True or setup.get("task_id") != task_id:
        issues.append("m2_reset_not_successful")
    if setup.get("profile") != M2_PROTOCOL["profile"]:
        issues.append("m2_reset_profile_mismatch")
    if str(setup.get("seed") or "") != str(M2_PROTOCOL["world_seed"]):
        issues.append("m2_reset_seed_mismatch")
    if setup.get("observed_minecraft_version") != M2_PROTOCOL["minecraft_version"]:
        issues.append("m2_minecraft_version_mismatch")
    if "paper" not in str(setup.get("server_brand") or "").lower():
        issues.append("m2_server_brand_not_paper")
    if str(setup.get("server_jar_sha256") or "").lower() != M2_PROTOCOL["server_jar_sha256"]:
        issues.append("m2_server_jar_hash_mismatch")
    reset_checks = setup.get("checks", {}) if isinstance(setup.get("checks"), dict) else {}
    if not reset_checks or any(value is not True for name, value in reset_checks.items() if name != "position_distance"):
        issues.append("m2_reset_checks_not_verified")
    expected_initial = inventory_counts(M2_TASKS_BY_ID.get(task_id, {}).get("initial_inventory", {}))
    observed_initial = inventory_counts(
        setup.get("after_state", {}).get("inventory", {})
        if isinstance(setup.get("after_state"), dict)
        else {}
    )
    if observed_initial != expected_initial:
        issues.append("m2_reset_inventory_mismatch")
    episode_id = str(setup.get("episode_id") or "")
    level_name = str(setup.get("level_name") or "")
    if not episode_id or not level_name.startswith(f"{episode_id}_"):
        issues.append("m2_fresh_episode_level_not_proven")

    if terminal.get("success") is not True or terminal.get("task_id") != task_id:
        issues.append("m2_terminal_evidence_missing")
    if terminal.get("profile") != M2_PROTOCOL["profile"]:
        issues.append("m2_terminal_profile_mismatch")
    if validation.get("passed") is not True or validation.get("profile") != "m2_session_evidence_v1":
        issues.append("m2_session_validation_not_passed")
    if validation.get("valid_root_call_count") != 1:
        issues.append("m2_single_root_call_not_proven")
    if _as_int(validation.get("root_subtask_count")) < 2:
        issues.append("m2_root_subtasks_missing")
    if _as_int(validation.get("root_dependency_edge_count")) < 1:
        issues.append("m2_root_dependency_missing")
    if _as_int(validation.get("complete_task_transition_node_count")) < 2:
        issues.append("m2_task_state_paths_missing")
    if _as_int(validation.get("plan_cache_bypass_count")) != 0:
        issues.append("m2_plan_cache_or_fallback_present")
    if _as_int(validation.get("quarantined_skill_event_count")) != 0:
        issues.append("m2_quarantined_skill_present")
    if validation.get("goal_verifier_event_achieved") is not True:
        issues.append("m2_machine_goal_verifier_missing")

    expected_max_duration_s = _as_optional_float(
        M2_TASKS_BY_ID.get(task_id, {}).get("max_duration_s")
    )
    recorded_max_duration_s = _as_optional_float(record.get("max_duration_s"))
    goal_elapsed_s = _as_optional_float(record.get("goal_elapsed_s"))
    if (
        expected_max_duration_s is None
        or recorded_max_duration_s != expected_max_duration_s
    ):
        issues.append("m2_result_max_duration_mismatch")
    if (
        expected_max_duration_s is None
        or goal_elapsed_s is None
        or goal_elapsed_s > expected_max_duration_s
    ):
        issues.append("m2_result_goal_duration_exceeded")
    if str(record.get("termination_reason") or "") == "max_duration":
        issues.append("m2_result_terminated_at_deadline")
    if validation.get("duration_within_limit") is not True:
        issues.append("m2_validation_duration_not_proven")
    if _as_int(validation.get("deadline_exceeded_event_count")) != 0:
        issues.append("m2_validation_deadline_event_present")
    if _as_int(validation.get("post_deadline_action_count")) != 0:
        issues.append("m2_validation_post_deadline_action_present")

    if runtime.get("eligible_configuration") is not True or runtime.get("isolated") is not True:
        issues.append("m2_runtime_not_eligible")
    expected_runtime = {
        "protocol": M2_PROTOCOL["profile"],
        "protocol_sha256": M2_PROTOCOL_SHA256,
        "reset_protocol_sha256": M2_PROTOCOL["reset_protocol_sha256"],
        "validation_protocol_sha256": M2_PROTOCOL["validation_protocol_sha256"],
        "planner_schema_sha256": M2_PROTOCOL["planner_schema_sha256"],
        "agent_id": M2_PROTOCOL["agent_id"],
        "planner_id": M2_PROTOCOL["planner_id"],
        "action_backend_id": M2_PROTOCOL["action_backend_id"],
        "verifier_id": M2_PROTOCOL["verifier_id"],
        "skill_runtime_profile_id": M2_PROTOCOL["skill_runtime_profile_id"],
        "deadline_policy_id": M2_PROTOCOL["deadline_policy"]["id"],
        "llm_transport_policy_id": M2_PROTOCOL["llm_transport_policy"]["id"],
    }
    for name, expected in expected_runtime.items():
        if runtime.get(name) != expected:
            issues.append(f"m2_runtime_{name}_mismatch")
    for name, payload, expected in (
        ("setup", setup, M2_PROTOCOL_SHA256),
        ("terminal", terminal, M2_PROTOCOL_SHA256),
        ("validation", validation, M2_PROTOCOL_SHA256),
    ):
        if payload.get("protocol_sha256") != expected:
            issues.append(f"m2_{name}_protocol_hash_mismatch")
    if setup.get("reset_protocol_sha256") != M2_PROTOCOL["reset_protocol_sha256"]:
        issues.append("m2_setup_reset_contract_hash_mismatch")
    if terminal.get("validation_protocol_sha256") != M2_PROTOCOL["validation_protocol_sha256"]:
        issues.append("m2_terminal_validation_contract_hash_mismatch")

    arm = str(experiment.get("arm") or "default")
    skill_mode = str(experiment.get("skill_execution_mode") or "off")
    target_skill = str(experiment.get("target_skill_id") or "")
    if arm == "baseline" and (skill_mode != "off" or target_skill):
        issues.append("m2_baseline_skill_isolation_failed")
    if arm == "candidate" and (skill_mode != "runtime" or not target_skill):
        issues.append("m2_candidate_skill_configuration_missing")

    session_id = str(record.get("session_id") or "").strip()
    log_ref = str(record.get("session_log") or record.get("log") or "").strip()
    if not session_id:
        issues.append("session_id_missing")
    if not log_ref:
        issues.append("session_log_missing")
        return list(dict.fromkeys(issues))
    if Path(log_ref).is_absolute():
        issues.append("session_log_path_not_portable")
    log_path = _resolve_evidence_path(log_ref, source_path)
    if log_path is None:
        issues.append("session_log_unavailable")
        return list(dict.fromkeys(issues))
    expected_hash = str(record.get("session_sha256") or "").lower()
    if expected_hash != hashlib.sha256(log_path.read_bytes()).hexdigest():
        issues.append("session_log_hash_mismatch")
    issues.extend(_m2_session_log_issues(log_path, session_id, task_id))
    return list(dict.fromkeys(issues))


def _resolve_evidence_path(log_ref: str, source_path: str) -> Optional[Path]:
    candidate = Path(log_ref)
    candidates = [candidate]
    if not candidate.is_absolute():
        candidates.append(Path(source_path).resolve().parent / candidate)
    for path in candidates:
        if path.is_file():
            return path.resolve()
    return None


def _m1_session_log_issues(path: Path, session_id: str, task_id: str) -> list[str]:
    issues = []
    task_id = str(task_id or "").upper().strip()
    events = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except Exception:
            issues.append("session_log_invalid_jsonl")
            continue
        if isinstance(event, dict):
            events.append(event)
    if not events:
        return issues + ["session_log_empty"]
    event_sessions = {str(event.get("session") or "") for event in events if event.get("session")}
    if session_id not in event_sessions or len(event_sessions) != 1:
        issues.append("session_identity_mismatch")

    def event_data(event_type: str) -> list[dict]:
        return [
            event.get("data", {})
            for event in events
            if event.get("type") == event_type and isinstance(event.get("data"), dict)
        ]

    connects = event_data("connect")
    profiles = event_data("benchmark_runtime_profile")
    resets = event_data("benchmark_reset")
    validations = event_data("benchmark_evidence_validation")
    goal_verifications = event_data("goal_verification")
    goal_ends = event_data("goal_end")
    if not any(event.get("success") is True for event in connects):
        issues.append("live_connect_event_missing")
    if (
        not profiles
        or profiles[-1].get("isolated") is not True
        or profiles[-1].get("protocol_sha256") != M1_PROTOCOL_SHA256
        or profiles[-1].get("agent_id") != M1_PROTOCOL["agent_id"]
        or profiles[-1].get("planner_id") != M1_PROTOCOL["planner_id"]
        or profiles[-1].get("action_backend_id") != M1_PROTOCOL["action_backend_id"]
        or profiles[-1].get("verifier_id") != M1_PROTOCOL["verifier_id"]
    ):
        issues.append("isolated_runtime_event_missing")
    reset = resets[-1] if resets else {}
    reset_checks = reset.get("checks", {}) if isinstance(reset.get("checks"), dict) else {}
    reset_episode = str(reset.get("episode_id") or "")
    reset_level = str(reset.get("level_name") or "")
    if (
        not resets
        or reset.get("success") is not True
        or reset.get("task_id") != task_id
        or reset.get("protocol_sha256") != M1_PROTOCOL_SHA256
        or str(reset.get("seed") or "") != str(M1_PROTOCOL["world_seed"])
        or reset.get("observed_minecraft_version") != M1_PROTOCOL["minecraft_version"]
        or "paper" not in str(reset.get("server_brand") or "").lower()
        or str(reset.get("server_jar_sha256") or "").lower() != M1_PROTOCOL["server_jar_sha256"]
        or not reset_episode
        or not reset_level.startswith(f"{reset_episode}_")
        or not reset_checks
        or any(value is not True for name, value in reset_checks.items() if name != "position_distance")
    ):
        issues.append("verified_reset_event_missing")
    if (
        not validations
        or validations[-1].get("passed") is not True
        or validations[-1].get("protocol_sha256") != M1_PROTOCOL_SHA256
    ):
        issues.append("evidence_validation_event_missing")
    if not any(
        event.get("achieved") is True or str(event.get("status") or "").lower() == "achieved"
        for event in goal_verifications
    ):
        issues.append("achieved_goal_verifier_event_missing")
    if not any(
        isinstance(event.get("result"), dict)
        and event["result"].get("completed") is True
        and event["result"].get("termination_reason") == "goal_verified"
        for event in goal_ends
    ):
        issues.append("verified_goal_end_missing")

    actions = []
    for event in events:
        if event.get("type") != "action" or not isinstance(event.get("data"), dict):
            continue
        data = event["data"]
        action = data.get("action", {}) if isinstance(data.get("action"), dict) else {}
        result = data.get("result", {}) if isinstance(data.get("result"), dict) else {}
        context = data.get("action_context", {}) if isinstance(data.get("action_context"), dict) else {}
        action_type = str(action.get("type") or result.get("action_type") or "")
        actions.append((action_type, result, context, data))
        if action_type in {"move_to", "walk_to"} and result.get("success") is True:
            if result.get("reached") is not True:
                issues.append("successful_navigation_missing_reached")
                continue
            try:
                distance = float(result.get("distance_to_target"))
                tolerance = float(result.get("tolerance"))
            except (TypeError, ValueError):
                issues.append("successful_navigation_missing_tolerance_proof")
                continue
            if distance > tolerance:
                issues.append("successful_navigation_outside_tolerance")
    for index, (action_type, result, context, _) in enumerate(actions):
        if action_type not in {"move_to", "walk_to"} or result.get("reached") is True:
            continue
        cycle = context.get("cycle")
        for later_type, _, later_context, _ in actions[index + 1:]:
            if later_context.get("cycle") != cycle:
                break
            if later_type in {"dig", "place", "craft"}:
                issues.append("dependent_action_after_unreached_navigation")
                break
    required_action = "dig" if task_id in {"BM-001", "BM-004"} else "craft"
    relevant = [
        action_transition_proof(task_id, data)
        for action_type, result, _, data in actions
        if action_type == required_action and result.get("success") is True
    ]
    if not relevant:
        issues.append(f"successful_{required_action}_action_missing")
    elif any(proof.get("passed") is not True for proof in relevant):
        issues.append(f"{required_action}_state_transition_unverified")
    return list(dict.fromkeys(issues))


def _m2_session_log_issues(path: Path, session_id: str, task_id: str) -> list[str]:
    issues = []
    events = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except Exception:
            issues.append("m2_session_log_invalid_jsonl")
            continue
        if isinstance(event, dict):
            events.append(event)
    if not events:
        return issues + ["m2_session_log_empty"]
    event_sessions = {str(event.get("session") or "") for event in events if event.get("session")}
    if session_id not in event_sessions or len(event_sessions) != 1:
        issues.append("m2_session_identity_mismatch")

    def event_data(event_type: str) -> list[dict]:
        return [
            event.get("data", {})
            for event in events
            if event.get("type") == event_type and isinstance(event.get("data"), dict)
        ]

    if not any(item.get("success") is True for item in event_data("connect")):
        issues.append("m2_live_connect_event_missing")
    profiles = event_data("benchmark_runtime_profile")
    profile = profiles[-1] if profiles else {}
    if (
        profile.get("eligible_configuration") is not True
        or profile.get("protocol") != M2_PROTOCOL["profile"]
        or profile.get("protocol_sha256") != M2_PROTOCOL_SHA256
        or profile.get("planner_id") != M2_PROTOCOL["planner_id"]
        or profile.get("action_backend_id") != M2_PROTOCOL["action_backend_id"]
        or profile.get("verifier_id") != M2_PROTOCOL["verifier_id"]
        or profile.get("deadline_policy_id") != M2_PROTOCOL["deadline_policy"]["id"]
        or profile.get("llm_transport_policy_id") != M2_PROTOCOL["llm_transport_policy"]["id"]
    ):
        issues.append("m2_runtime_profile_event_missing")
    resets = event_data("benchmark_reset")
    reset = resets[-1] if resets else {}
    checks = reset.get("checks", {}) if isinstance(reset.get("checks"), dict) else {}
    episode_id = str(reset.get("episode_id") or "")
    level_name = str(reset.get("level_name") or "")
    if (
        reset.get("success") is not True
        or reset.get("task_id") != task_id
        or reset.get("protocol_sha256") != M2_PROTOCOL_SHA256
        or reset.get("reset_protocol_sha256") != M2_PROTOCOL["reset_protocol_sha256"]
        or reset.get("validation_protocol_sha256") != M2_PROTOCOL["validation_protocol_sha256"]
        or str(reset.get("seed") or "") != str(M2_PROTOCOL["world_seed"])
        or str(reset.get("server_jar_sha256") or "").lower() != M2_PROTOCOL["server_jar_sha256"]
        or not episode_id
        or not level_name.startswith(f"{episode_id}_")
        or not checks
        or any(value is not True for name, value in checks.items() if name != "position_distance")
    ):
        issues.append("m2_verified_reset_event_missing")

    planner_calls = event_data("llm_planner_call")
    valid_roots = []
    for call in planner_calls:
        metadata = call.get("provider_metadata", {}) if isinstance(call.get("provider_metadata"), dict) else {}
        schema = call.get("schema_validation", {}) if isinstance(call.get("schema_validation"), dict) else {}
        deadline = call.get("deadline_policy", {}) if isinstance(call.get("deadline_policy"), dict) else {}
        transport = call.get("transport_evidence", {}) if isinstance(call.get("transport_evidence"), dict) else {}
        transport_attempts = transport.get("attempts", []) if isinstance(transport.get("attempts"), list) else []
        timeout_s = _as_optional_float(metadata.get("timeout_s"))
        transport_exact = bool(
            transport.get("policy_id") == M2_PROTOCOL["llm_transport_policy"]["id"]
            and 1 <= len(transport_attempts)
            <= 1 + int(M2_PROTOCOL["llm_transport_policy"]["application_max_retries"])
            and _as_int(transport.get("attempt_count")) == len(transport_attempts)
            and _as_int(transport.get("retry_count")) == len(transport_attempts) - 1
            and transport_attempts[-1].get("success") is True
            and all(
                (_as_optional_float(attempt.get("timeout_s")) or 0) > 0
                and _as_int(attempt.get("sdk_max_retries"))
                == int(M2_PROTOCOL["llm_transport_policy"]["sdk_max_retries"])
                for attempt in transport_attempts
                if isinstance(attempt, dict)
            )
            and all(
                attempt.get("success") is True
                or any(
                    error_type in (attempt.get("error_chain") or [])
                    for error_type in M2_PROTOCOL["llm_transport_policy"]["retryable_error_types"]
                )
                for attempt in transport_attempts
                if isinstance(attempt, dict)
            )
        )
        if (
            call.get("plan_kind") == "root"
            and call.get("real_llm_call") is True
            and call.get("schema_valid") is True
            and schema.get("passed") is True
            and _as_int(schema.get("subtask_count")) >= 2
            and _as_int(schema.get("dependency_edge_count")) >= 1
            and metadata.get("provider") == M2_PROTOCOL["llm"]["provider"]
            and str(metadata.get("base_url") or "").rstrip("/") == str(M2_PROTOCOL["llm"]["base_url"]).rstrip("/")
            and metadata.get("model") == M2_PROTOCOL["llm"]["model"]
            and _as_optional_float(metadata.get("temperature")) == float(M2_PROTOCOL["llm"]["temperature"])
            and _as_int(metadata.get("max_tokens")) == int(M2_PROTOCOL["llm"]["max_tokens"])
            and metadata.get("response_format") == M2_PROTOCOL["llm"]["response_format"]
            and metadata.get("extra_body") == M2_PROTOCOL["llm"]["extra_body"]
            and metadata.get("finish_reason") == M2_PROTOCOL["llm_response_contract"]["finish_reason"]
            and _as_int(metadata.get("reasoning_content_byte_count"))
            <= int(M2_PROTOCOL["llm_response_contract"]["reasoning_content_max_bytes"])
            and timeout_s is not None
            and timeout_s > 0
            and _as_int(metadata.get("max_retries")) == int(M2_PROTOCOL["deadline_policy"]["planner_max_retries"])
            and deadline.get("policy_id") == M2_PROTOCOL["deadline_policy"]["id"]
            and _as_optional_float(deadline.get("request_timeout_s")) == timeout_s
            and _as_optional_float(deadline.get("action_guard_s"))
            == float(M2_PROTOCOL["deadline_policy"]["action_guard_ms"]) / 1000.0
            and transport_exact
            and _as_int(deadline.get("max_retries")) == int(M2_PROTOCOL["deadline_policy"]["planner_max_retries"])
            and _as_int(metadata.get("total_tokens")) > 0
            and re.fullmatch(r"[0-9a-f]{64}", str(metadata.get("request_sha256") or ""))
            and re.fullmatch(r"[0-9a-f]{64}", str(call.get("response_sha256") or ""))
        ):
            valid_roots.append(call)
    if len(valid_roots) != 1:
        issues.append("m2_single_valid_root_call_missing")
    root_id = str(valid_roots[0].get("root_plan_id") or "") if valid_roots else ""
    plans = event_data("plan")
    if not any(
        plan.get("root_plan_id") == root_id
        and plan.get("plan_kind") == "root"
        and (plan.get("schema_validation") or {}).get("passed") is True
        for plan in plans
    ):
        issues.append("m2_structured_root_plan_missing")

    paths = {}
    for transition in event_data("task_state_transition"):
        if str(transition.get("root_plan_id") or "") != root_id:
            continue
        node_id = str(transition.get("plan_node_id") or "")
        if node_id:
            paths.setdefault(node_id, []).append(str(transition.get("to_status") or ""))
    complete_paths = sum(
        1
        for statuses in paths.values()
        if "proposed" in statuses
        and "active" in statuses
        and ("completed" in statuses or "failed" in statuses)
    )
    if complete_paths < 2:
        issues.append("m2_task_transition_paths_missing")

    actions = event_data("action")
    if not actions:
        issues.append("m2_action_events_missing")
    for action in actions:
        result = action.get("result", {}) if isinstance(action.get("result"), dict) else {}
        if result.get("success") is True and (
            not isinstance(action.get("pre_observation"), dict)
            or not isinstance(action.get("post_observation"), dict)
        ):
            issues.append("m2_action_pre_post_observation_missing")
            break

    terminals = event_data("benchmark_terminal_evidence")
    terminal = terminals[-1] if terminals else {}
    if (
        terminal.get("success") is not True
        or terminal.get("task_id") != task_id
        or terminal.get("protocol_sha256") != M2_PROTOCOL_SHA256
        or terminal.get("validation_protocol_sha256") != M2_PROTOCOL["validation_protocol_sha256"]
    ):
        issues.append("m2_terminal_evidence_event_missing")
    validations = event_data("benchmark_evidence_validation")
    if (
        not validations
        or validations[-1].get("passed") is not True
        or validations[-1].get("profile") != "m2_session_evidence_v1"
        or validations[-1].get("protocol_sha256") != M2_PROTOCOL_SHA256
    ):
        issues.append("m2_evidence_validation_event_missing")
    if not any(
        item.get("achieved") is True
        and "m2:machine_verifier" in (item.get("matched_rules") or [])
        for item in event_data("goal_verification")
    ):
        issues.append("m2_achieved_goal_verifier_event_missing")
    if not any(
        isinstance(item.get("result"), dict)
        and item["result"].get("completed") is True
        and item["result"].get("termination_reason") == "goal_verified"
        for item in event_data("goal_end")
    ):
        issues.append("m2_verified_goal_end_missing")

    deadline_contract = M2_PROTOCOL["deadline_policy"]
    expected_max_duration_s = _as_optional_float(
        M2_TASKS_BY_ID.get(task_id, {}).get("max_duration_s")
    )
    goal_start_rows = [event for event in events if event.get("type") == "goal_start"]
    goal_limit_rows = [event for event in events if event.get("type") == "goal_limits"]
    goal_end_rows = [event for event in events if event.get("type") == "goal_end"]
    deadline_rows = [event for event in events if event.get("type") == "goal_deadline_exceeded"]
    goal_limit = (
        goal_limit_rows[-1].get("data", {})
        if goal_limit_rows and isinstance(goal_limit_rows[-1].get("data"), dict)
        else {}
    )
    goal_end = (
        goal_end_rows[-1].get("data", {})
        if goal_end_rows and isinstance(goal_end_rows[-1].get("data"), dict)
        else {}
    )
    goal_result = goal_end.get("result", {}) if isinstance(goal_end.get("result"), dict) else {}
    goal_elapsed_s = _as_optional_float(goal_result.get("elapsed_s"))
    if (
        len(goal_start_rows) != 1
        or len(goal_limit_rows) != 1
        or expected_max_duration_s is None
        or _as_optional_float(goal_limit.get("max_duration_s")) != expected_max_duration_s
        or goal_limit.get("deadline_policy_id") != deadline_contract["id"]
        or _as_int(goal_limit.get("action_guard_ms")) != int(deadline_contract["action_guard_ms"])
    ):
        issues.append("m2_goal_deadline_limits_invalid")
    if (
        len(goal_end_rows) != 1
        or expected_max_duration_s is None
        or _as_optional_float(goal_result.get("max_duration_s")) != expected_max_duration_s
        or goal_elapsed_s is None
    ):
        issues.append("m2_goal_end_duration_missing")
    elif goal_elapsed_s > expected_max_duration_s:
        issues.append("m2_goal_duration_exceeded")
    if deadline_rows:
        issues.append("m2_deadline_exceeded_event_present")

    post_deadline_action_count = 0
    if goal_start_rows and expected_max_duration_s is not None:
        start_ts = _as_optional_float(goal_start_rows[0].get("ts"))
        start_elapsed = _as_optional_float(goal_start_rows[0].get("elapsed_s"))
        for action_row in (event for event in events if event.get("type") == "action"):
            action_ts = _as_optional_float(action_row.get("ts"))
            action_elapsed = _as_optional_float(action_row.get("elapsed_s"))
            if start_ts is not None and action_ts is not None:
                offset_s = action_ts - start_ts
            elif start_elapsed is not None and action_elapsed is not None:
                offset_s = action_elapsed - start_elapsed
            else:
                offset_s = None
            if offset_s is not None and offset_s >= expected_max_duration_s:
                post_deadline_action_count += 1
    if post_deadline_action_count:
        issues.append("m2_post_deadline_action_present")

    forbidden = {"plan_cache_hit", "plan_cache_hybrid_hint", "planner_fallback"}
    if any(event.get("type") in forbidden for event in events):
        issues.append("m2_planner_bypass_event_present")
    for event in events:
        if not str(event.get("type") or "").startswith("skill_"):
            continue
        serialized = json.dumps(event.get("data", {}), sort_keys=True, default=str).lower()
        if (
            '"status": "quarantined"' in serialized
            or "craft_wooden_pickaxe@1.0.1" in serialized
            or ('"version": "1.0.1"' in serialized and "wooden_pickaxe" in serialized)
        ):
            issues.append("m2_quarantined_skill_event_present")
            break
    return list(dict.fromkeys(issues))


def _build_m2_pairing_gate(records: list[dict], min_repeats: int) -> dict:
    required_tasks = ("BM-006", "BM-007")
    metric_names = (
        "planner_call_count",
        "replan_count",
        "planner_token_usage",
        "planner_latency_ms",
        "action_event_count",
        "action_failure_count",
        "verifier_reject_count",
        "skill_selected_count",
        "skill_action_success_count",
        "fallback_count",
        "failure_replan_proved",
    )
    task_reports = {}
    missing = []
    for task_id in required_tasks:
        task_records = [
            record
            for record in records
            if record.get("task_id") == task_id and record.get("outcome") == "success"
        ]
        grouped = {}
        for record in task_records:
            experiment = record.get("experiment_metadata", {})
            if not isinstance(experiment, dict):
                continue
            arm = str(experiment.get("arm") or "default")
            pair_id = str(experiment.get("pair_id") or "")
            replicate_id = str(experiment.get("replicate_id") or "")
            if arm not in {"baseline", "candidate"} or not pair_id or not replicate_id:
                continue
            grouped.setdefault((pair_id, replicate_id), {})[arm] = record
        pairs = []
        for (pair_id, replicate_id), arms in sorted(grouped.items()):
            baseline = arms.get("baseline")
            candidate = arms.get("candidate")
            if not baseline or not candidate:
                continue
            baseline_experiment = baseline.get("experiment_metadata", {})
            candidate_experiment = candidate.get("experiment_metadata", {})
            baseline_isolated = bool(
                baseline_experiment.get("skill_execution_mode") == "off"
                and not baseline_experiment.get("target_skill_id")
            )
            candidate_enabled = bool(
                candidate_experiment.get("skill_execution_mode") == "runtime"
                and candidate_experiment.get("target_skill_id")
                and _as_int(candidate.get("m2_metrics", {}).get("skill_selected_count")) >= 1
                and _as_int(candidate.get("m2_metrics", {}).get("skill_action_success_count")) >= 1
            )
            comparable = bool(
                baseline.get("protocol_hash") == candidate.get("protocol_hash") == M2_PROTOCOL_SHA256
                and baseline.get("session_id") != candidate.get("session_id")
                and baseline.get("episode_id") != candidate.get("episode_id")
            )
            metrics = {}
            for name in metric_names:
                baseline_value = _as_optional_float(baseline.get("m2_metrics", {}).get(name))
                candidate_value = _as_optional_float(candidate.get("m2_metrics", {}).get(name))
                metrics[name] = {
                    "baseline": baseline_value,
                    "candidate": candidate_value,
                    "delta": (
                        round(candidate_value - baseline_value, 3)
                        if baseline_value is not None and candidate_value is not None
                        else None
                    ),
                }
            pairs.append({
                "pair_id": pair_id,
                "replicate_id": replicate_id,
                "baseline_session_id": baseline.get("session_id"),
                "candidate_session_id": candidate.get("session_id"),
                "baseline_skill_isolated": baseline_isolated,
                "candidate_skill_executed": candidate_enabled,
                "comparable": comparable,
                "eligible": baseline_isolated and candidate_enabled and comparable,
                "target_skill_id": candidate_experiment.get("target_skill_id", ""),
                "metrics": metrics,
            })
        eligible_pairs = [pair for pair in pairs if pair.get("eligible")]
        task_reports[task_id] = {
            "required_pairs": min_repeats,
            "complete_pair_count": len(pairs),
            "eligible_pair_count": len(eligible_pairs),
            "pairs": pairs,
        }
        if len(eligible_pairs) < min_repeats:
            missing.append(f"{task_id}:needs_{min_repeats - len(eligible_pairs)}_more_eligible_skill_pairs")
    replan_sessions = [
        record.get("session_id")
        for record in records
        if record.get("task_id") in M2_TASK_IDS
        and record.get("outcome") == "success"
        and record.get("m2_metrics", {}).get("failure_replan_proved") is True
    ]
    if not replan_sessions:
        missing.append("M2:needs_one_failure_replan_or_prerequisite_recovery_session")
    return {
        "type": "m2_skill_pairing_gate",
        "schema_version": 1,
        "approved": not missing,
        "required_tasks": list(required_tasks),
        "pairs_required_per_task": min_repeats,
        "tasks": task_reports,
        "failure_replan_session_count": len(replan_sessions),
        "failure_replan_session_ids": _unique_strings(replan_sessions),
        "missing": missing,
    }


def _summarize_benchmarks(records: list[dict]) -> dict:
    stats = {}
    for record in records:
        item = stats.setdefault(record["task_id"], {
            "attempts": 0,
            "successes": 0,
            "failures": 0,
            "ineligible_successes": 0,
            "ineligibility_reasons": [],
            "evidence_refs": [],
        })
        item["attempts"] += 1
        if record["outcome"] == "success":
            item["successes"] += 1
        elif record["outcome"] == "failure":
            item["failures"] += 1
        else:
            item["ineligible_successes"] += 1
            for reason in record.get("eligibility_reasons", []):
                if reason not in item["ineligibility_reasons"]:
                    item["ineligibility_reasons"].append(reason)
        ref = record.get("run_ref") or f"{record['source_path']}:{record['record_path']}"
        if ref not in item["evidence_refs"]:
            item["evidence_refs"].append(ref)
    return stats


def _benchmark_status(task_id: str, stats: dict, min_repeats: int) -> dict:
    attempts = int(stats.get("attempts", 0) or 0)
    successes = int(stats.get("successes", 0) or 0)
    failures = int(stats.get("failures", 0) or 0)
    ineligible_successes = int(stats.get("ineligible_successes", 0) or 0)
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
        "ineligible_successes": ineligible_successes,
        "ineligibility_reasons": list(stats.get("ineligibility_reasons", []))[:20],
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
