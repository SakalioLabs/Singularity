"""Materialize fixed-protocol stone-pickaxe skill lifecycle transitions."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from singularity.core.skill_extractor import SkillCandidateQueue, SkillExtractor
from singularity.core.skill_learning import SkillLearningLedger
from singularity.core.skill_library import SkillLibrary
from singularity.evaluation.stone_pickaxe_protocol import (
    PROTOCOL,
    PROTOCOL_SHA256,
    build_prospective_skill_candidate,
    validate_candidate_matches_prospective_contract,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FAILURE_LEDGER = "workspace/evals/stone_pickaxe_failure_ledger.json"
DEFAULT_QUEUE = "workspace/skills/skill_candidates.jsonl"
DEFAULT_LEARNING_LEDGER = "workspace/evals/skill_learning_ledger.json"
DEFAULT_STORAGE = "workspace/skills"
DEFAULT_PROMOTION = "workspace/evals/acquire_cobblestone_promotion.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("extract-candidate", "promote-advisory"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--task-id", choices=["SP-001"], default="SP-001")
        subparser.add_argument("--failure-ledger", default=DEFAULT_FAILURE_LEDGER)
        subparser.add_argument("--queue", default=DEFAULT_QUEUE)
        subparser.add_argument("--learning-ledger", default=DEFAULT_LEARNING_LEDGER)
        subparser.add_argument("--storage-path", default=DEFAULT_STORAGE)
        subparser.add_argument("--output", default=DEFAULT_PROMOTION)
    subparsers.choices["promote-advisory"].add_argument("--candidate-id", default="")
    return parser.parse_args()


def repository_path(value: str, *, must_exist: bool = False) -> Path:
    path = (REPOSITORY_ROOT / str(value or "")).resolve()
    try:
        path.relative_to(REPOSITORY_ROOT)
    except ValueError as exc:
        raise ValueError(f"path escapes repository: {value}") from exc
    if must_exist and not path.exists():
        raise FileNotFoundError(path)
    return path


def relative_path(path: Path) -> str:
    return path.resolve().relative_to(REPOSITORY_ROOT).as_posix()


def read_json(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def exact_candidate(queue: SkillCandidateQueue, task_id: str, candidate_id: str = ""):
    contract_skill_id = str(PROTOCOL["prospective_skill_contracts"][task_id]["skill_id"])
    matches = [
        candidate for candidate in queue.all()
        if candidate.skill_id == contract_skill_id
        and (not candidate_id or candidate.id == candidate_id)
    ]
    if len(matches) != 1:
        raise ValueError(
            f"expected one {contract_skill_id} candidate, found {len(matches)}"
        )
    return matches[0]


def base_report(task_id: str, candidate, promotion_report: dict) -> dict:
    return {
        "type": "stone_pickaxe_skill_promotion",
        "schema_version": 1,
        "protocol_id": PROTOCOL["id"],
        "protocol_sha256": PROTOCOL_SHA256,
        "generated_at_utc": utc_now(),
        "task_id": task_id,
        "skill_id": candidate.skill_id,
        "candidate_id": candidate.id,
        "skill_version": candidate.version,
        "stage": candidate.status,
        "candidate_contract": {
            "name": candidate.name,
            "task_family": candidate.task_family,
            "layer": candidate.layer,
            "preconditions": candidate.preconditions,
            "required_observations": candidate.required_observations,
            "postconditions": candidate.postconditions,
            "bounded_action_template": candidate.bounded_action_template,
        },
        "source_gate": {
            "success_count": candidate.success_count,
            "source_session_ids": candidate.source_session_ids,
            "source_environment_ids": candidate.source_environment_ids,
            "source_session_sha256s": candidate.signals["stone_pickaxe_gate"]["session_sha256s"],
            "runtime_eligible": candidate.runtime_eligible,
            "evidence_kind": candidate.evidence_kind,
        },
        "promotion_review": promotion_report,
        "lifecycle_history": [],
        "counts_toward_capability": False,
        "counts_toward_m4": False,
    }


def run_extract_candidate(args: argparse.Namespace) -> int:
    failure_ledger_path = repository_path(args.failure_ledger, must_exist=True)
    queue_path = repository_path(args.queue)
    learning_ledger_path = repository_path(args.learning_ledger)
    storage_path = repository_path(args.storage_path, must_exist=True)
    output_path = repository_path(args.output)
    if output_path.exists():
        raise FileExistsError(f"candidate promotion artifact already exists: {relative_path(output_path)}")

    failure_ledger = read_json(failure_ledger_path)
    candidate = build_prospective_skill_candidate(
        args.task_id,
        failure_ledger.get("eligible_successes", []),
        repository_root=REPOSITORY_ROOT,
    )
    library = SkillLibrary(storage_path=str(storage_path), persist=True)
    if library.skill_versions(candidate.skill_id):
        raise ValueError(f"skill already exists before candidate extraction: {candidate.skill_id}")
    queue = SkillCandidateQueue(str(queue_path))
    queued = queue.enqueue(candidate)
    match = validate_candidate_matches_prospective_contract(args.task_id, queued)
    if not match["passed"]:
        raise ValueError(f"queued candidate contract mismatch: {match['issues']}")
    extractor = SkillExtractor(library, auto_promote=False)
    promotion = extractor.validate_candidate_for_promotion(queued)
    if promotion.decision != "promote_advisory":
        raise ValueError(f"candidate is not advisory-ready: {promotion.reason}; {promotion.missing}")
    queued.signals = {
        **queued.signals,
        "verification_gate": promotion.gate,
        "promotion_report": promotion.to_dict(),
    }
    queue.save()
    learning_ledger = SkillLearningLedger(str(learning_ledger_path))
    learning_ledger.record_candidate(queued, promotion.to_dict())
    learning_ledger.record_decision(
        queued.skill_id,
        "retain_candidate_for_explicit_advisory_review",
        "fixed_protocol_candidate_created_after_three_eligible_live_successes",
        evidence=promotion.to_dict(),
    )
    report = base_report(args.task_id, queued, promotion.to_dict())
    report["stage"] = "candidate"
    report["advisory_ready"] = True
    report["lifecycle_history"].append({
        "stage": "candidate",
        "at_utc": utc_now(),
        "decision": "candidate_created",
        "source_success_count": queued.success_count,
    })
    report["artifacts"] = {
        "candidate_queue": relative_path(queue_path),
        "skill_learning_ledger": relative_path(learning_ledger_path),
        "custom_skill_mutated": False,
    }
    write_json(output_path, report)
    print(json.dumps({
        "candidate_id": queued.id,
        "skill_id": queued.skill_id,
        "stage": "candidate",
        "advisory_ready": True,
        "output": relative_path(output_path),
    }, indent=2))
    return 0


def run_promote_advisory(args: argparse.Namespace) -> int:
    queue_path = repository_path(args.queue, must_exist=True)
    learning_ledger_path = repository_path(args.learning_ledger)
    storage_path = repository_path(args.storage_path, must_exist=True)
    output_path = repository_path(args.output, must_exist=True)
    queue = SkillCandidateQueue(str(queue_path))
    candidate = exact_candidate(queue, args.task_id, args.candidate_id)
    match = validate_candidate_matches_prospective_contract(args.task_id, candidate)
    if not match["passed"]:
        raise ValueError(f"candidate contract mismatch: {match['issues']}")
    if candidate.status != "candidate" or candidate.review_status != "pending":
        raise ValueError(
            f"candidate is not pending: status={candidate.status} review={candidate.review_status}"
        )
    library = SkillLibrary(storage_path=str(storage_path), persist=True)
    if library.skill_versions(candidate.skill_id):
        raise ValueError(f"skill version already exists: {candidate.skill_id}")
    extractor = SkillExtractor(library, auto_promote=False)
    promotion = extractor.validate_candidate_for_promotion(candidate)
    if promotion.decision != "promote_advisory":
        raise ValueError(f"advisory promotion rejected: {promotion.reason}; {promotion.missing}")
    skill = extractor.approve_candidate(candidate)
    if skill is None or skill.status != "advisory":
        raise RuntimeError("advisory skill was not created")
    queue.save()
    learning_ledger = SkillLearningLedger(str(learning_ledger_path))
    learning_ledger.record_candidate(candidate, promotion.to_dict())
    learning_ledger.record_skill(skill)
    learning_ledger.record_decision(
        skill.skill_id,
        "promote_advisory",
        promotion.reason,
        evidence=promotion.to_dict(),
    )
    report = read_json(output_path)
    if report.get("candidate_id") != candidate.id or report.get("stage") != "candidate":
        raise ValueError("promotion artifact is not at the candidate stage")
    report.update({
        "generated_at_utc": utc_now(),
        "stage": "advisory",
        "advisory_ready": True,
        "promotion_review": promotion.to_dict(),
        "advisory_skill": {
            "skill_id": skill.skill_id,
            "name": skill.name,
            "version": skill.version,
            "status": skill.status,
            "source_session_ids": skill.source_session_ids,
            "source_environment_ids": skill.source_environment_ids,
            "rollback_target": skill.rollback_target,
        },
    })
    report.setdefault("lifecycle_history", []).append({
        "stage": "advisory",
        "at_utc": utc_now(),
        "decision": "promote_advisory",
        "reason": promotion.reason,
    })
    report.setdefault("artifacts", {})["custom_skill_mutated"] = True
    write_json(output_path, report)
    print(json.dumps({
        "candidate_id": candidate.id,
        "skill_id": skill.skill_id,
        "version": skill.version,
        "stage": skill.status,
        "output": relative_path(output_path),
    }, indent=2))
    return 0


def main() -> int:
    args = parse_args()
    if args.command == "extract-candidate":
        return run_extract_candidate(args)
    if args.command == "promote-advisory":
        return run_promote_advisory(args)
    raise RuntimeError(f"unsupported command: {args.command}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, indent=2), file=sys.stderr)
        raise
