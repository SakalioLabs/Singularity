"""Evidence ledger for Minecraft Agent capability claims."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional


SUCCESS_STATUSES = {"success", "succeeded", "pass", "passed", "complete", "completed"}
FAILURE_STATUSES = {"fail", "failed", "error", "blocked", "timeout", "rejected"}
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
        "evidence_kind": "unmapped_live",
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
        "evidence_kind": "unmapped_live",
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
        "evidence_kind": "unmapped_live",
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
) -> dict:
    """Compare declared phase completion against source and execution evidence."""
    min_repeats = max(1, int(min_repeats or 1))
    source_root_path = Path(source_root)
    declared, status_errors = _load_declared_status(status_path)
    records, load_errors, loaded_paths = _load_benchmark_records(benchmark_result_paths or [])
    benchmark_stats = _summarize_benchmarks(records)

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
        status = _phase_status(spec["evidence_kind"], source_ready, task_stats, min_repeats)
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
            "missing_evidence": _missing_phase_evidence(spec, status, task_stats, source_checks, min_repeats),
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
    claim_readiness = "rejected" if contradictions else "review" if unsupported or load_errors or status_errors else "approved"
    system_complete = all(phase["completion_claim_allowed"] for phase in phases)
    has_failed_evidence = any(phase["status"] in {"source_incomplete", "failing"} for phase in phases)
    if contradictions or has_failed_evidence:
        readiness = "rejected"
    elif system_complete and not load_errors and not status_errors:
        readiness = "approved"
    else:
        readiness = "review"
    report = {
        "type": "capability_evidence_report",
        "schema_version": 1,
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
        },
        "inputs": {
            "status_path": status_path,
            "source_root": source_root,
            "benchmark_result_paths": loaded_paths,
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
        "errors": status_errors + load_errors,
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
        print(
            f"  [{phase.get('id')}] {phase.get('status')}: "
            f"declared={declared}, claim={phase.get('claim_assessment')}{benchmark_text}"
        )
    for recommendation in report.get("recommendations", [])[:12]:
        print(f"  -> {recommendation}")


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


def _phase_status(evidence_kind: str, source_ready: bool, tasks: list[dict], min_repeats: int) -> str:
    if evidence_kind == "source":
        return "source_verified" if source_ready else "source_incomplete"
    if evidence_kind == "unmapped_live":
        return "unverified"
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
) -> list[str]:
    if status in {"source_verified", "repeat_verified"}:
        return []
    if spec["evidence_kind"] == "source":
        return [f"missing_source:{check['path']}" for check in source_checks if not check["exists"]]
    if spec["evidence_kind"] == "unmapped_live":
        return ["machine_checkable_live_acceptance_not_mapped"]
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
            recommendations.append(f"diagnose_and_rerun_{phase_id}_benchmarks")
        elif phase["status"] == "not_run":
            recommendations.append(f"run_{phase_id}_benchmarks")
        elif phase["status"] == "live_observed":
            recommendations.append(f"repeat_{phase_id}_benchmarks_to_policy_minimum")
        elif phase["status"] == "unverified":
            recommendations.append(f"define_machine_checkable_{phase_id}_live_acceptance")
    return list(dict.fromkeys(recommendations))
