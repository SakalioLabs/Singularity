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
    evaluate_m4_episode_for_protocol_hash,
    supported_protocol_sha256s,
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
            if f"badge/{phÛÍùÒÚ$z{-®éÜj×S`¢÷"FW&Ö–æÂævWB‚'fÆ–FF–öå÷&÷Fö6öÅ÷6†#Sb"’ÒÓ%õ$õDô4ôÅ²'fÆ–FF–öå÷&÷Fö6öÅ÷6†#Sb%Ð¢“ ¢—77VW2æVæB‚&Ó%÷FW&Ö–æÅöWf–FVæ6UöWfVçEöÖ—76–ær"¢fÆ–FF–öç2ÒWfVçEöFF‚&&Væ6†Ö&µöWf–FVæ6U÷fÆ–FF–öâ"¢–b€¢æ÷BfÆ–FF–öç0¢÷"fÆ–FF–öç5²ÓÒævWB‚'76VB"’—2æ÷BG'VP¢÷"fÆ–FF–öç5²ÓÒævWB‚'&öf–ÆR"’Ò&Ó%÷6W76–öåöWf–FVæ6U÷c ¢÷"fÆ–FF–öç5²ÓÒævWB‚'&÷Fö6öÅ÷6†#Sb"’ÒÓ%õ$õDô4ôÅõ4„#S`¢“ ¢—77VW2æVæB‚&Ó%öWf–FVæ6U÷fÆ–FF–öåöWfVçEöÖ—76–ær"¢–bæ÷Bç’€¢—FVÒævWB‚&6†–WfVB"’—2G'VP¢æB&Ó#¦Ö6†–æU÷fW&–f–W""–â†—FVÒævWB‚&ÖF6†VE÷'VÆW2"’÷"µÒ¢f÷"—FVÒ–âWfVçEöFF‚&vöÅ÷fW&–f–6F–öâ"¢“ ¢—77VW2æVæB‚&Ó%ö6†–WfVEövöÅ÷fW&–f–W%öWfVçEöÖ—76–ær"¢–bæ÷Bç’€¢—6–ç7Fæ6R†—FVÒævWB‚'&W7VÇB"’ÂF–7B¢æB—FVÕ²'&W7VÇB%ÒævWB‚&6ö×ÆWFVB"’—2G'VP¢æB—FVÕ²'&W7VÇB%ÒævWB‚'FW&Ö–æF–öå÷&V6öâ"’ÓÒ&vöÅ÷fW&–f–VB ¢f÷"—FVÒ–âWfVçEöFF‚&vöÅöVæB"¢“ ¢—77VW2æVæB‚&Ó%÷fW&–f–VEövöÅöVæEöÖ—76–ær" ¢FVFÆ–æUö6öçG&7BÒÓ%õ$õDô4ôÅ²&FVFÆ–æU÷öÆ–7’%Ð¢W‡V7FVEöÖ…öGW&F–öå÷2Òö5ö÷F–öæÅöfÆöB€¢Ó%õD4µ5ô%•ô”BævWB‡F6µö–BÂ·Ò’ævWB‚&Ö…öGW&F–öå÷2"¢¢vöÅ÷7F'E÷&÷w2Ò¶WfVçBf÷"WfVçB–âWfVçG2–bWfVçBævWB‚'G—R"’ÓÒ&vöÅ÷7F'B%Ð¢vöÅöÆ–Ö—E÷&÷w2Ò¶WfVçBf÷"WfVçB–âWfVçG2–bWfVçBævWB‚'G—R"’ÓÒ&vöÅöÆ–Ö—G2%Ð¢vöÅöVæE÷&÷w2Ò¶WfVçBf÷"WfVçB–âWfVçG2–bWfVçBævWB‚'G—R"’ÓÒ&vöÅöVæB%Ð¢FVFÆ–æU÷&÷w2Ò¶WfVçBf÷"WfVçB–âWfVçG2–bWfVçBævWB‚'G—R"’ÓÒ&vöÅöFVFÆ–æUöW†6VVFVB%Ð¢vöÅöÆ–Ö—BÒ€¢vöÅöÆ–Ö—E÷&÷w5²ÓÒævWB‚&FF"Â·Ò¢–bvöÅöÆ–Ö—E÷&÷w2æB—6–ç7Fæ6R†vöÅöÆ–Ö—E÷&÷w5²ÓÒævWB‚&FF"’ÂF–7B¢VÇ6R·Ð¢¢vöÅöVæBÒ€¢vöÅöVæE÷&÷w5²ÓÒævWB‚&FF"Â·Ò¢–bvöÅöVæE÷&÷w2æB—6–ç7Fæ6R†vöÅöVæE÷&÷w5²ÓÒævWB‚&FF"’ÂF–7B¢VÇ6R·Ð¢¢vöÅ÷&W7VÇBÒvöÅöVæBævWB‚'&W7VÇB"Â·Ò’–b—6–ç7Fæ6R†vöÅöVæBævWB‚'&W7VÇB"’ÂF–7B’VÇ6R·Ð¢vöÅöVÆ6VE÷2Òö5ö÷F–öæÅöfÆöB†vöÅ÷&W7VÇBævWB‚&VÆ6VE÷2"’¢–b€¢ÆVâ†vöÅ÷7F'E÷&÷w2’Ò¢÷"ÆVâ†vöÅöÆ–Ö—E÷&÷w2’Ò¢÷"W‡V7FVEöÖ…öGW&F–öå÷2—2æöæP¢÷"ö5ö÷F–öæÅöfÆöB†vöÅöÆ–Ö—BævWB‚&Ö…öGW&F–öå÷2"’’ÒW‡V7FVEöÖ…öGW&F–öå÷0¢÷"vöÅöÆ–Ö—BævWB‚&FVFÆ–æU÷öÆ–7•ö–B"’ÒFVFÆ–æUö6öçG&7E²&–B%Ð¢÷"ö5ö–çB†vöÅöÆ–Ö—BævWB‚&7F–öåöwV&Eö×2"’’Ò–çB†FVFÆ–æUö6öçG&7E²&7F–öåöwV&Eö×2%Ò¢“ ¢—77VW2æVæB‚&Ó%övöÅöFVFÆ–æUöÆ–Ö—G5ö–çfÆ–B"¢–b€¢ÆVâ†vöÅöVæE÷&÷w2’Ò¢÷"W‡V7FVEöÖ…öGW&F–öå÷2—2æöæP¢÷"ö5ö÷F–öæÅöfÆöB†vöÅ÷&W7VÇBævWB‚&Ö…öGW&F–öå÷2"’’ÒW‡V7FVEöÖ…öGW&F–öå÷0¢÷"vöÅöVÆ6VE÷2—2æöæP¢“ ¢—77VW2æVæB‚&Ó%övöÅöVæEöGW&F–öåöÖ—76–ær"¢VÆ–bvöÅöVÆ6VE÷2âW‡V7FVEöÖ…öGW&F–öå÷3 ¢—77VW2æVæB‚&Ó%övöÅöGW&F–öåöW†6VVFVB"¢–bFVFÆ–æU÷&÷w3 ¢—77VW2æVæB‚&Ó%öFVFÆ–æUöW†6VVFVEöWfVçE÷&W6VçB" ¢÷7EöFVFÆ–æUö7F–öåö6÷VçBÒ ¢–bvöÅ÷7F'E÷&÷w2æBW‡V7FVEöÖ…öGW&F–öå÷2—2æ÷BæöæS ¢7F'E÷G2Òö5ö÷F–öæÅöfÆöB†vöÅ÷7F'E÷&÷w5³ÒævWB‚'G2"’¢7F'EöVÆ6VBÒö5ö÷F–öæÅöfÆöB†vöÅ÷7F'E÷&÷w5³ÒævWB‚&VÆ6VE÷2"’¢f÷"7F–öå÷&÷r–â†WfVçBf÷"WfVçB–âWfVçG2–bWfVçBævWB‚'G—R"’ÓÒ&7F–öâ"“ ¢7F–öå÷G2Òö5ö÷F–öæÅöfÆöB†7F–öå÷&÷rævWB‚'G2"’¢7F–öåöVÆ6VBÒö5ö÷F–öæÅöfÆöB†7F–öå÷&÷rævWB‚&VÆ6VE÷2"’¢–b7F'E÷G2—2æ÷BæöæRæB7F–öå÷G2—2æ÷BæöæS ¢öfg6WE÷2Ò7F–öå÷G2Ò7F'E÷G0¢VÆ–b7F'EöVÆ6VB—2æ÷BæöæRæB7F–öåöVÆ6VB—2æ÷BæöæS ¢öfg6WE÷2Ò7F–öåöVÆ6VBÒ7F'EöVÆ6V@¢VÇ6S ¢öfg6WE÷2ÒæöæP¢–böfg6WE÷2—2æ÷BæöæRæBöfg6WE÷2ãÒW‡V7FVEöÖ…öGW&F–öå÷3 ¢÷7EöFVFÆ–æUö7F–öåö6÷VçB³Ò¢–b÷7EöFVFÆ–æUö7F–öåö6÷VçC ¢—77VW2æVæB‚&Ó%÷÷7EöFVFÆ–æUö7F–öå÷&W6VçB" ¢f÷&&–FFVâÒ²'Æåö66†Uö†—B"Â'Æåö66†Uö‡–'&–Eö†–çB"Â'ÆææW%öfÆÆ&6²'Ð¢–bç’†WfVçBævWB‚'G—R"’–âf÷&&–FFVâf÷"WfVçB–âWfVçG2“ ¢—77VW2æVæB‚&Ó%÷ÆææW%ö'—75öWfVçE÷&W6VçB"¢f÷"WfVçB–âWfVçG3 ¢–bæ÷B7G"†WfVçBævWB‚'G—R"’÷"""’ç7F'G7v—F‚‚'6¶–ÆÅò"“ ¢6öçF–çVP¢6W&–Æ—¦VBÒ§6öâæGV×2†WfVçBævWB‚&FF"Â·Ò’Â6÷'Eö¶W—3ÕG'VRÂFVfVÇC×7G"’æÆ÷vW"‚¢–b€¢r'7FGW2#¢'V&çF–æVB"r–â6W&–Æ—¦V@¢÷"&7&gE÷vööFVå÷–6¶†Tãã"–â6W&–Æ—¦V@¢÷"‚r'fW'6–öâ#¢#ãã"r–â6W&–Æ—¦VBæB'vööFVå÷–6¶†R"–â6W&–Æ—¦VB¢“ ¢—77VW2æVæB‚&Ó%÷V&çF–æVE÷6¶–ÆÅöWfVçE÷&W6VçB"¢'&V°¢&WGW&âÆ—7B†F–7Bæg&öÖ¶W—2†—77VW2’  ¦FVbö'V–ÆEöÓ%÷—&–æuövFR‡&V6÷&G3¢Æ—7E¶F–7EÒÂÖ–å÷&WVG3¢–çB’ÓâF–7C ¢&WV—&VE÷F6·2Ò‚$$ÒÓb"Â$$ÒÓr"¢ÖWG&–5öæÖW2Ò€¢'ÆææW%ö6ÆÅö6÷VçB"À¢'&WÆåö6÷VçB"À¢'ÆææW%÷Fö¶Vå÷W6vR"À¢'ÆææW%öÆFVæ7•ö×2"À¢&7F–öåöWfVçEö6÷VçB"À¢&7F–öåöf–ÇW&Uö6÷VçB"À¢'fW&–f–W%÷&V¦V7Eö6÷VçB"À¢'6¶–ÆÅ÷6VÆV7FVEö6÷VçB"À¢'6¶–ÆÅö7F–öå÷7V66W75ö6÷VçB"À¢&fÆÆ&6µö6÷VçB"À¢&f–ÇW&U÷&WÆå÷&÷fVB"À¢¢F6µ÷&W÷'G2Ò·Ð¢Ö—76–ærÒµÐ¢f÷"F6µö–B–â&WV—&VE÷F6·3 ¢F6µ÷&V6÷&G2Ò°¢&V6÷&@¢f÷"&V6÷&B–â&V6÷&G0¢–b&V6÷&BævWB‚'F6µö–B"’ÓÒF6µö–BæB&V6÷&BævWB‚&÷WF6öÖR"’ÓÒ'7V66W72 ¢Ð¢w&÷WVBÒ·Ð¢f÷"&V6÷&B–âF6µ÷&V6÷&G3 ¢W‡W&–ÖVçBÒ&V6÷&BævWB‚&W‡W&–ÖVçEöÖWFFF"Â·Ò¢–bæ÷B—6–ç7Fæ6R†W‡W&–ÖVçBÂF–7B“ ¢6öçF–çVP¢&ÒÒ7G"†W‡W&–ÖVçBævWB‚&&Ò"’÷"&FVfVÇB"¢—%ö–BÒ7G"†W‡W&–ÖVçBævWB‚'—%ö–B"’÷"""¢&WÆ–6FUö–BÒ7G"†W‡W&–ÖVçBævWB‚'&WÆ–6FUö–B"’÷"""¢–b&Òæ÷B–â²&&6VÆ–æR"Â&6æF–FFR'Ò÷"æ÷B—%ö–B÷"æ÷B&WÆ–6FUö–C ¢6öçF–çVP¢w&÷WVBç6WFFVfVÇB‚‡—%ö–BÂ&WÆ–6FUö–B’Â·Ò•¶&ÕÒÒ&V6÷&@¢—'2ÒµÐ¢f÷"‡—%ö–BÂ&WÆ–6FUö–B’Â&×2–â6÷'FVB†w&÷WVBæ—FV×2‚’“ ¢&6VÆ–æRÒ&×2ævWB‚&&6VÆ–æR"¢6æF–FFRÒ&×2ævWB‚&6æF–FFR"¢–bæ÷B&6VÆ–æR÷"æ÷B6æF–FFS ¢6öçF–çVP¢&6VÆ–æUöW‡W&–ÖVçBÒ&6VÆ–æRævWB‚&W‡W&–ÖVçEöÖWFFF"Â·Ò¢6æF–FFUöW‡W&–ÖVçBÒ6æF–FFRævWB‚&W‡W&–ÖVçEöÖWFFF"Â·Ò¢&6VÆ–æUö—6öÆFVBÒ&ööÂ€¢&6VÆ–æUöW‡W&–ÖVçBævWB‚'6¶–ÆÅöW†V7WF–öåöÖöFR"’ÓÒ&öfb ¢æBæ÷B&6VÆ–æUöW‡W&–ÖVçBævWB‚'F&vWE÷6¶–ÆÅö–B"¢¢6æF–FFUöVæ&ÆVBÒ&ööÂ€¢6æF–FFUöW‡W&–ÖVçBævWB‚'6¶–ÆÅöW†V7WF–öåöÖöFR"’ÓÒ''VçF–ÖR ¢æB6æF–FFUöW‡W&–ÖVçBævWB‚'F&vWE÷6¶–ÆÅö–B"¢æBö5ö–çB†6æF–FFRævWB‚&Ó%öÖWG&–72"Â·Ò’ævWB‚'6¶–ÆÅ÷6VÆV7FVEö6÷VçB"’’ãÒ¢æBö5ö–çB†6æF–FFRævWB‚&Ó%öÖWG&–72"Â·Ò’ævWB‚'6¶–ÆÅö7F–öå÷7V66W75ö6÷VçB"’’ãÒ¢¢6ö×&&ÆRÒ&ööÂ€¢&6VÆ–æRævWB‚'&÷Fö6öÅö†6‚"’ÓÒ6æF–FFRævWB‚'&÷Fö6öÅö†6‚"’ÓÒÓ%õ$õDô4ôÅõ4„#S`¢æB&6VÆ–æRævWB‚'6W76–öåö–B"’Ò6æF–FFRævWB‚'6W76–öåö–B"¢æB&6VÆ–æRævWB‚&W—6öFUö–B"’Ò6æF–FFRævWB‚&W—6öFUö–B"¢¢ÖWG&–72Ò·Ð¢f÷"æÖR–âÖWG&–5öæÖW3 ¢&6VÆ–æU÷fÇVRÒö5ö÷F–öæÅöfÆöB†&6VÆ–æRævWB‚&Ó%öÖWG&–72"Â·Ò’ævWB†æÖR’¢6æF–FFU÷fÇVRÒö5ö÷F–öæÅöfÆöB†6æF–FFRævWB‚&Ó%öÖWG&–72"Â·Ò’ævWB†æÖR’¢ÖWG&–75¶æÖUÒÒ°¢&&6VÆ–æR#¢&6VÆ–æU÷fÇVRÀ¢&6æF–FFR#¢6æF–FFU÷fÇVRÀ¢&FVÇF#¢€¢&÷VæB†6æF–FFU÷fÇVRÒ&6VÆ–æU÷fÇVRÂ2¢–b&6VÆ–æU÷fÇVR—2æ÷BæöæRæB6æF–FFU÷fÇVR—2æ÷BæöæP¢VÇ6RæöæP¢’À¢Ð¢—'2æVæB‡°¢'—%ö–B#¢—%ö–BÀ¢'&WÆ–6FUö–B#¢&WÆ–6FUö–BÀ¢&&6VÆ–æU÷6W76–öåö–B#¢&6VÆ–æRævWB‚'6W76–öåö–B"’À¢&6æF–FFU÷6W76–öåö–B#¢6æF–FFRævWB‚'6W76–öåö–B"’À¢&&6VÆ–æU÷6¶–ÆÅö—6öÆFVB#¢&6VÆ–æUö—6öÆFVBÀ¢&6æF–FFU÷6¶–ÆÅöW†V7WFVB#¢6æF–FFUöVæ&ÆVBÀ¢&6ö×&&ÆR#¢6ö×&&ÆRÀ¢&VÆ–v–&ÆR#¢&6VÆ–æUö—6öÆFVBæB6æF–FFUöVæ&ÆVBæB6ö×&&ÆRÀ¢'F&vWE÷6¶–ÆÅö–B#¢6æF–FFUöW‡W&–ÖVçBævWB‚'F&vWE÷6¶–ÆÅö–B"Â""’À¢&ÖWG&–72#¢ÖWG&–72À¢Ò¢VÆ–v–&ÆU÷—'2Ò·—"f÷"—"–â—'2–b—"ævWB‚&VÆ–v–&ÆR"•Ð¢F6µ÷&W÷'G5·F6µö–EÒÒ°¢'&WV—&VE÷—'2#¢Ö–å÷&WVG2À¢&6ö×ÆWFU÷—%ö6÷VçB#¢ÆVâ‡—'2’À¢&VÆ–v–&ÆU÷—%ö6÷VçB#¢ÆVâ†VÆ–v–&ÆU÷—'2’À¢'—'2#¢—'2À¢Ð¢–bÆVâ†VÆ–v–&ÆU÷—'2’ÂÖ–å÷&WVG3 ¢Ö—76–æræVæB†b'·F6µö–GÓ¦æVVG5÷¶Ö–å÷&WVG2ÒÆVâ†VÆ–v–&ÆU÷—'2—ÕöÖ÷&UöVÆ–v–&ÆU÷6¶–ÆÅ÷—'2"¢&WÆå÷6W76–öç2Ò°¢&V6÷&BævWB‚'6W76–öåö–B"¢f÷"&V6÷&B–â&V6÷&G0¢–b&V6÷&BævWB‚'F6µö–B"’–âÓ%õD4µô”E0¢æB&V6÷&BævWB‚&÷WF6öÖR"’ÓÒ'7V66W72 ¢æB&V6÷&BævWB‚&Ó%öÖWG&–72"Â·Ò’ævWB‚&f–ÇW&U÷&WÆå÷&÷fVB"’—2G'VP¢Ð¢–bæ÷B&WÆå÷6W76–öç3 ¢Ö—76–æræVæB‚$Ó#¦æVVG5ööæUöf–ÇW&U÷&WÆåö÷%÷&W&WV—6—FU÷&V6÷fW'•÷6W76–öâ"¢&WGW&â°¢'G—R#¢&Ó%÷6¶–ÆÅ÷—&–æuövFR"À¢'66†VÖ÷fW'6–öâ#¢À¢&&÷fVB#¢æ÷BÖ—76–ærÀ¢'&WV—&VE÷F6·2#¢Æ—7B‡&WV—&VE÷F6·2’À¢'—'5÷&WV—&VE÷W%÷F6²#¢Ö–å÷&WVG2À¢'F6·2#¢F6µ÷&W÷'G2À¢&f–ÇW&U÷&WÆå÷6W76–öåö6÷VçB#¢ÆVâ‡&WÆå÷6W76–öç2’À¢&f–ÇW&U÷&WÆå÷6W76–öåö–G2#¢÷Væ—VU÷7G&–æw2‡&WÆå÷6W76–öç2’À¢&Ö—76–ær#¢Ö—76–ærÀ¢Ð  ¦FVb÷7VÖÖ&—¦Uö&Væ6†Ö&·2‡&V6÷&G3¢Æ—7E¶F–7EÒ’ÓâF–7C ¢7FG2Ò·Ð¢f÷"&V6÷&B–â&V6÷&G3 ¢—FVÒÒ7FG2ç6WFFVfVÇB‡&V6÷&E²'F6µö–B%ÒÂ°¢&GFV×G2#¢À¢'7V66W76W2#¢À¢&f–ÇW&W2#¢À¢&–æVÆ–v–&ÆU÷7V66W76W2#¢À¢&–æVÆ–v–&–Æ—G•÷&V6öç2#¢µÒÀ¢&Wf–FVæ6U÷&Vg2#¢µÒÀ¢Ò¢—FVÕ²&GFV×G2%Ò³Ò¢–b&V6÷&E²&÷WF6öÖR%ÒÓÒ'7V66W72# ¢—FVÕ²'7V66W76W2%Ò³Ò¢VÆ–b&V6÷&E²&÷WF6öÖR%ÒÓÒ&f–ÇW&R# ¢—FVÕ²&f–ÇW&W2%Ò³Ò¢VÇ6S ¢—FVÕ²&–æVÆ–v–&ÆU÷7V66W76W2%Ò³Ò¢f÷"&V6öâ–â&V6÷&BævWB‚&VÆ–v–&–Æ—G•÷&V6öç2"ÂµÒ“ ¢–b&V6öâæ÷B–â—FVÕ²&–æVÆ–v–&–Æ—G•÷&V6öç2%Ó ¢—FVÕ²&–æVÆ–v–&–Æ—G•÷&V6öç2%ÒæVæB‡&V6öâ¢&VbÒ&V6÷&BævWB‚''Vå÷&Vb"’÷"b'·&V6÷&E²w6÷W&6U÷F‚u×Ó§·&V6÷&E²w&V6÷&E÷F‚u×Ò ¢–b&Vbæ÷B–â—FVÕ²&Wf–FVæ6U÷&Vg2%Ó ¢—FVÕ²&Wf–FVæ6U÷&Vg2%ÒæVæB‡&Vb¢&WGW&â7FG0  ¦FVbö&Væ6†Ö&µ÷7FGW2‡F6µö–C¢7G"Â7FG3¢F–7BÂÖ–å÷&WVG3¢–çB’ÓâF–7C ¢GFV×G2Ò–çB‡7FG2ævWB‚&GFV×G2"Â’÷"¢7V66W76W2Ò–çB‡7FG2ævWB‚'7V66W76W2"Â’÷"¢f–ÇW&W2Ò–çB‡7FG2ævWB‚&f–ÇW&W2"Â’÷"¢–æVÆ–v–&ÆU÷7V66W76W2Ò–çB‡7FG2ævWB‚&–æVÆ–v–&ÆU÷7V66W76W2"Â’÷"¢–b7V66W76W2ãÒÖ–å÷&WVG3 ¢7FGW2Ò'&WVE÷fW&–f–VB ¢VÆ–b7V66W76W2ãÒ ¢7FGW2Ò&Æ—fUöö'6W'fVB ¢VÆ–bGFV×G3 ¢7FGW2Ò&f–Æ–ær ¢VÇ6S ¢7FGW2Ò&æ÷E÷'Vâ ¢&WGW&â°¢'F6µö–B#¢F6µö–BÀ¢'7FGW2#¢7FGW2À¢&GFV×G2#¢GFV×G2À¢'7V66W76W2#¢7V66W76W2À¢&f–ÇW&W2#¢f–ÇW&W2À¢&–æVÆ–v–&ÆU÷7V66W76W2#¢–æVÆ–v–&ÆU÷7V66W76W2À¢&–æVÆ–v–&–Æ—G•÷&V6öç2#¢Æ—7B‡7FG2ævWB‚&–æVÆ–v–&–Æ—G•÷&V6öç2"ÂµÒ’•³£#ÒÀ¢'&WVG5÷&WV—&VB#¢Ö–å÷&WVG2À¢&Wf–FVæ6U÷&Vg2#¢Æ—7B‡7FG2ævWB‚&Wf–FVæ6U÷&Vg2"ÂµÒ’•³£#ÒÀ¢Ð  ¦FVb÷†6U÷7FGW2€¢Wf–FVæ6Uö¶–æC¢7G"À¢6÷W&6U÷&VG“¢&ööÂÀ¢F6·3¢Æ—7E¶F–7EÒÀ¢Ö–å÷&WVG3¢–çBÀ¢Æ—fUöWf–FVæ6S¢÷F–öæÅ¶F–7EÒÒæöæRÀ¢’Óâ7G# ¢–bWf–FVæ6Uö¶–æBÓÒ'6÷W&6R# ¢&WGW&â'6÷W&6U÷fW&–f–VB"–b6÷W&6U÷&VG’VÇ6R'6÷W&6Uö–æ6ö×ÆWFR ¢–bWf–FVæ6Uö¶–æBÓÒ&Æ—fU÷&W÷'B# ¢&WGW&â7G"‚†Æ—fUöWf–FVæ6R÷"·Ò’ævWB‚'7FGW2"’÷"&æ÷E÷'Vâ"¢–bæ÷BF6·2÷"æ÷Bç’‡F6µ²&GFV×G2%Òf÷"F6²–âF6·2“ ¢&WGW&â&æ÷E÷'Vâ ¢–bÆÂ‡F6µ²'7V66W76W2%ÒãÒÖ–å÷&WVG2f÷"F6²–âF6·2“ ¢&WGW&â'&WVE÷fW&–f–VB ¢–bÆÂ‡F6µ²'7V66W76W2%ÒãÒf÷"F6²–âF6·2“ ¢&WGW&â&Æ—fUöö'6W'fVB ¢–bç’‡F6µ²&GFV×G2%ÒæBæ÷BF6µ²'7V66W76W2%Òf÷"F6²–âF6·2“ ¢&WGW&â&f–Æ–ær ¢&WGW&â''F–Â   ¦FVbö6Æ–Õö76W76ÖVçB†FV6Æ&VEö6ö×ÆWFS¢&ööÂÂ7FGW3¢7G"’Óâ7G# ¢–bæ÷BFV6Æ&VEö6ö×ÆWFS ¢&WGW&â&æ÷Eö6Æ–ÖVEö6ö×ÆWFR ¢–b7FGW2–â²'6÷W&6U÷fW&–f–VB"Â'&WVE÷fW&–f–VB'Ó ¢&WGW&â'7W÷'FVB ¢–b7FGW2–â²'6÷W&6Uö–æ6ö×ÆWFR"Â&f–Æ–ær'Ó ¢&WGW&â&6öçG&F–7FVB ¢&WGW&â'Vç7W÷'FVB   ¦FVböÖ—76–æu÷†6UöWf–FVæ6R€¢7V3¢F–7BÀ¢7FGW3¢7G"À¢F6·3¢Æ—7E¶F–7EÒÀ¢6÷W&6Uö6†V6·3¢Æ—7E¶F–7EÒÀ¢Ö–å÷&WVG3¢–çBÀ¢Æ—fUöWf–FVæ6S¢÷F–öæÅ¶F–7EÒÒæöæRÀ¢’ÓâÆ—7E·7G%Ó ¢–b7FGW2–â²'6÷W&6U÷fW&–f–VB"Â'&WVE÷fW&–f–VB'Ó ¢&WGW&âµÐ¢–b7V5²&Wf–FVæ6Uö¶–æB%ÒÓÒ'6÷W&6R# ¢&WGW&â¶b&Ö—76–æu÷6÷W&6S§¶6†V6µ²wF‚u×Ò"f÷"6†V6²–â6÷W&6Uö6†V6·2–bæ÷B6†V6µ²&W†—7G2%ÕÐ¢–b7V5²&Wf–FVæ6Uö¶–æB%ÒÓÒ&Æ—fU÷&W÷'B# ¢&WGW&âÆ—7B‚†Æ—fUöWf–FVæ6R÷"·Ò’ævWB‚&Ö—76–ær"ÂµÒ’¢Ö—76–ærÒµÐ¢f÷"F6²–âF6·3 ¢–bF6µ²'7V66W76W2%ÒÂÖ–å÷&WVG3 ¢Ö—76–æræVæB†b'·F6µ²wF6µö–Bu×Ó¦æVVG5÷¶Ö–å÷&WVG2ÒF6µ²w7V66W76W2u×ÕöÖ÷&U÷7V66W76W2"¢&WGW&âÖ—76–æp  ¦FVb÷&V6öÖÖVæFF–öç2‡&W÷'C¢F–7B’ÓâÆ—7E·7G%Ó ¢&V6öÖÖVæFF–öç2ÒµÐ¢'VçF–ÖRÒ&W÷'BævWB‚''VçF–ÖUöWf–FVæ6R"Â·Ò¢–b'VçF–ÖRæBæ÷B'VçF–ÖRævWB‚&ö²"“ ¢&V6öÖÖVæFF–öç2æVæB‚'&W7F÷&UöÆ—fUöÖ–æV7&gE÷&VfÆ–v‡Eö&Vf÷&UöæWuö6&–Æ—G•ö6Æ–×2"¢f÷"†6R–â&W÷'BævWB‚'†6W2"ÂµÒ“ ¢†6Uö–BÒ†6U²&–B%ÒæÆ÷vW"‚¢–b†6U²&6Æ–Õö76W76ÖVçB%Ò–â²&6öçG&F–7FVB"Â'Vç7W÷'FVB'Ó ¢&V6öÖÖVæFF–öç2æVæB†b&F÷væw&FU÷·†6Uö–GÕö6ö×ÆWF–öåö6Æ–Õ÷VçF–ÅöWf–FVæ6U÷76W2"¢–b†6U²'7FGW2%ÒÓÒ&f–Æ–ær# ¢7Vff—‚Ò&Æ—fUöWf–FVæ6R"–b†6RævWB‚&Wf–FVæ6Uö¶–æB"’ÓÒ&Æ—fU÷&W÷'B"VÇ6R&&Væ6†Ö&·2 ¢&V6öÖÖVæFF–öç2æVæB†b&F–væ÷6UöæE÷&W'Vå÷·†6Uö–GÕ÷·7Vff—‡Ò"¢VÆ–b†6U²'7FGW2%ÒÓÒ&æ÷E÷'Vâ# ¢–b†6RævWB‚&Wf–FVæ6Uö¶–æB"’ÓÒ&Æ—fU÷&W÷'B# ¢&V6öÖÖVæFF–öç2æVæB†b&6öÆÆV7E÷·†6Uö–GÕöÆ—fUöWf–FVæ6R"¢VÇ6S ¢&V6öÖÖVæFF–öç2æVæB†b''Vå÷·†6Uö–GÕö&Væ6†Ö&·2"¢VÆ–b†6U²'7FGW2%ÒÓÒ''F–Â# ¢&V6öÖÖVæFF–öç2æVæB†b&6ö×ÆWFU÷·†6Uö–GÕöÆ—fUöWf–FVæ6Uö6öçG&7B"¢VÆ–b†6U²'7FGW2%ÒÓÒ&Æ—fUöö'6W'fVB# ¢7Vff—‚Ò&Æ—fUöWf–FVæ6R"–b†6RævWB‚&Wf–FVæ6Uö¶–æB"’ÓÒ&Æ—fU÷&W÷'B"VÇ6R&&Væ6†Ö&·2 ¢&V6öÖÖVæFF–öç2æVæB†b'&WVE÷·†6Uö–GÕ÷·7Vff—‡Õ÷Fõ÷öÆ–7•öÖ–æ–×VÒ"¢&WGW&âÆ—7B†F–7Bæg&öÖ¶W—2‡&V6öÖÖVæFF–öç2’ 