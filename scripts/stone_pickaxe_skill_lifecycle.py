"""Materialize fixed-protocol stone-pickaxe skill lifecycle transitions."""

from __future__ import annotations

import argparse
import json
import os
import sys
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from singularity.core.skill_extractor import SkillCandidateQueue, SkillExtractor
from singularity.core.skill_learning import (
    SkillLearningLedger,
    evidence_fingerprint,
    executable_promotion_gate_issues,
)
from singularity.core.skill_library import SkillLibrary
from singularity.evaluation.skill_learning_experiment import build_runtime_default_gate
from singularity.evaluation.stone_pickaxe_protocol import (
    PROTOCOL,
    PROTOCOL_SHA256,
    build_prospective_skill_candidate,
    validate_candidate_matches_prospective_contract,
)
from singularity.evaluation.stone_pickaxe_runtime import file_sha256
from singularity.evaluation.stone_pickaxe_skill_evaluation_v5 import (
    POLICY as V5_POLICY,
    POLICY_SHA256 as V5_POLICY_SHA256,
    build_paired_evaluation_report as build_v5_paired_evaluation_report,
    canonical_record_sha256,
    discover_evaluation_run_paths as discover_v5_evaluation_run_paths,
    policy_identity_report as v5_policy_identity_report,
)
from singularity.evaluation.stone_pickaxe_sp002_skill_evaluation_v2 import (
    POLICY as SP002_V2_POLICY,
    POLICY_SHA256 as SP002_V2_POLICY_SHA256,
    build_paired_evaluation_report as build_sp002_v2_paired_evaluation_report,
    discover_evaluation_run_paths as discover_sp002_v2_evaluation_run_paths,
    policy_identity_report as sp002_v2_policy_identity_report,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FAILURE_LEDGER = "workspace/evals/stone_pickaxe_failure_ledger.json"
DEFAULT_QUEUE = "workspace/skills/skill_candidates.jsonl"
DEFAULT_LEARNING_LEDGER = "workspace/evals/skill_learning_ledger.json"
DEFAULT_STORAGE = "workspace/skills"
DEFAULT_PROMOTION = "workspace/evals/acquire_cobblestone_promotion.json"
DEFAULT_PROMOTIONS = {
    "SP-001": DEFAULT_PROMOTION,
    "SP-002": "workspace/evals/craft_stone_pickaxe_promotion.json",
}
DEFAULT_PAIRED_REPORT = (
    "workspace/evals/sp001_skill_evaluation_v5/"
    "acquire_cobblestone_paired_evaluation_v5.json"
)
DEFAULT_EXECUTABLE_PROMOTION = (
    "workspace/evals/sp001_skill_promotion/"
    "acquire_cobblestone_executable_promotion.json"
)
DEFAULT_RUNTIME_GATE = (
    "workspace/evals/sp001_skill_promotion/"
    "acquire_cobblestone_runtime_default_gate.json"
)
DEFAULT_PAIRED_REPORTS = {
    "SP-001": DEFAULT_PAIRED_REPORT,
    "SP-002": (
        "workspace/evals/sp002_skill_evaluation_v2/"
        "craft_stone_pickaxe_paired_evaluation_v2.json"
    ),
}
DEFAULT_EXECUTABLE_PROMOTIONS = {
    "SP-001": DEFAULT_EXECUTABLE_PROMOTION,
    "SP-002": (
        "workspace/evals/sp002_skill_promotion/"
        "craft_stone_pickaxe_executable_promotion.json"
    ),
}
DEFAULT_RUNTIME_GATES = {
    "SP-001": DEFAULT_RUNTIME_GATE,
    "SP-002": (
        "workspace/evals/sp002_skill_promotion/"
        "craft_stone_pickaxe_runtime_default_gate.json"
    ),
}
EXECUTABLE_PROMOTION_CONFIGS = {
    "SP-001": {
        "policy": V5_POLICY,
        "policy_sha256": V5_POLICY_SHA256,
        "policy_identity": v5_policy_identity_report,
        "build_report": build_v5_paired_evaluation_report,
        "discover_runs": discover_v5_evaluation_run_paths,
        "report_type": "stone_pickaxe_skill_paired_recovery_evaluation",
        "transition_reason": (
            "three fresh v5 paired live trials passed the fixed stone-pickaxe "
            "promotion gate"
        ),
        "decision_reason": (
            "v5 r13-r15 produced three fresh eligible pairs and the exact "
            "1.1.0 gate passed"
        ),
        "next_gate": "sp002_offline_harness_and_separate_live_authorization",
    },
    "SP-002": {
        "policy": SP002_V2_POLICY,
        "policy_sha256": SP002_V2_POLICY_SHA256,
        "policy_identity": sp002_v2_policy_identity_report,
        "build_report": build_sp002_v2_paired_evaluation_report,
        "discover_runs": discover_sp002_v2_evaluation_run_paths,
        "report_type": "stone_pickaxe_sp002_skill_paired_recovery_evaluation",
        "transition_reason": (
            "three fresh SP-002 v2 paired live trials passed the fixed craft "
            "promotion gate"
        ),
        "decision_reason": (
            "SP-002 v2 r4-r6 produced three fresh eligible pairs and the exact "
            "1.0.1 gate passed"
        ),
        "next_gate": "sp003_composite_protocol_definition_and_offline_verification",
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("extract-candidate", "promote-advisory", "promote-executable"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--task-id", choices=("SP-001", "SP-002"), default="SP-001")
        subparser.add_argument("--failure-ledger", default=DEFAULT_FAILURE_LEDGER)
        subparser.add_argument("--queue", default=DEFAULT_QUEUE)
        subparser.add_argument("--learning-ledger", default=DEFAULT_LEARNING_LEDGER)
        subparser.add_argument("--storage-path", default=DEFAULT_STORAGE)
        subparser.add_argument("--output", default="")
    subparsers.choices["promote-advisory"].add_argument("--candidate-id", default="")
    executable = subparsers.choices["promote-executable"]
    executable.add_argument("--paired-report", default="")
    executable.add_argument("--runtime-gate-output", default="")
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


def exact_skill_version(library: SkillLibrary, skill_id: str, version: str):
    matches = [
        skill for skill in library.skill_versions(skill_id)
        if skill.version == version
    ]
    if len(matches) != 1:
        raise ValueError(f"expected one {skill_id}@{version} record, found {len(matches)}")
    return matches[0]


def validated_promotion_report(
    path: Path,
    task_id: str,
) -> tuple[dict, dict, dict, dict]:
    config = EXECUTABLE_PROMOTION_CONFIGS[task_id]
    policy = config["policy"]
    policy_sha256 = config["policy_sha256"]
    identity = config["policy_identity"]()
    if not identity.get("passed"):
        raise ValueError(
            f"{task_id} policy identity failed: {identity.get('issues', [])}"
        )
    stored = read_json(path)
    rebuilt = config["build_report"](config["discover_runs"]())
    if stored != rebuilt:
        raise ValueError("paired report does not match a fresh reconstruction from retained runs")

    target = policy["target_skill"]
    policy_gate = policy["promotion_gate"]
    gate = stored.get("executable_promotion_gate", {})
    gate = gate if isinstance(gate, dict) else {}
    issues = []
    expected_values = {
        "type": config["report_type"],
        "policy_id": policy["id"],
        "policy_sha256": policy_sha256,
        "protocol_id": PROTOCOL["id"],
        "protocol_sha256": PROTOCOL_SHA256,
        "task_id": task_id,
        "skill_id": target["skill_id"],
        "candidate_id": target["candidate_id"],
        "evaluated_skill_version": target["version"],
        "decision": "review_executable_new_version",
        "readiness": "approved",
        "evaluation_window_id": policy["recovery_window"]["id"],
    }
    for field, expected in expected_values.items():
        if stored.get(field) != expected:
            issues.append(f"paired_report_{field}_mismatch")
    if int(stored.get("valid_pair_count", 0) or 0) != int(
        policy_gate["minimum_independent_eligible_pairs"]
    ):
        issues.append("paired_report_pair_count_mismatch")
    if stored.get("errors") != []:
        issues.append("paired_report_errors_present")
    for field in (
        "fixed_controls_match",
        "live_minecraft_only",
        "candidate_steps_verified",
        "candidate_steps_reobserved",
        "no_completion_rate_regression",
        "no_action_failure_regression",
        "no_verifier_reject_regression",
        "no_no_progress_regression",
        "prior_evidence_mutated",
    ):
        expected = False if field == "prior_evidence_mutated" else True
        if stored.get(field) is not expected:
            issues.append(f"paired_report_check_failed:{field}")
    if stored.get("normal_runtime_permission") is not False:
        issues.append("paired_report_prepromotion_runtime_permission_invalid")
    if stored.get("counts_toward_capability") is not False:
        issues.append("paired_report_capability_credit_invalid")
    if stored.get("counts_toward_m4") is not False:
        issues.append("paired_report_m4_credit_invalid")
    expected_replicates = list(policy["arms"]["candidate"]["replicate_ids"])
    actual_replicates = [
        pair.get("replicate_id")
        for pair in stored.get("pairs", [])
        if isinstance(pair, dict) and pair.get("eligible") is True
    ]
    if actual_replicates != expected_replicates:
        issues.append("paired_report_eligible_replicates_mismatch")

    promoted_version = str(policy_gate["promoted_version"])
    issues.extend(
        f"promotion_gate:{issue}"
        for issue in executable_promotion_gate_issues(
            gate,
            skill_id=target["skill_id"],
            version=promoted_version,
        )
    )
    gate_expectations = {
        "evaluated_skill_version": target["version"],
        "promoted_skill_version": promoted_version,
        "rollback_target": policy_gate["rollback_target"],
        "normal_runtime_permission": False,
        "counts_toward_capability": False,
        "counts_toward_m4": False,
    }
    for field, expected in gate_expectations.items():
        if gate.get(field) != expected:
            issues.append(f"promotion_gate_{field}_mismatch")
    if gate.get("validation_issues") != []:
        issues.append("promotion_gate_validation_issues_present")
    if issues:
        raise ValueError(
            f"{task_id} executable promotion evidence rejected: "
            f"{sorted(set(issues))}"
        )
    return stored, gate, identity, config


def validated_v5_promotion_report(path: Path) -> tuple[dict, dict, dict]:
    report, gate, identity, _ = validated_promotion_report(path, "SP-001")
    return report, gate, identity


def build_stone_pickaxe_runtime_gate(
    report: dict,
    gate: dict,
    skill_name: str,
    source_report_path: str,
) -> dict:
    source = deepcopy(report)
    source["task_family"] = gate["transfer_scope"]["task_family"]
    source["report_id"] = (
        f"{report['policy_id']}:{canonical_record_sha256(report)}"
    )
    runtime_gate = build_runtime_default_gate(source, skill_name)
    runtime_gate.update({
        "source_report_path": source_report_path,
        "source_report_sha256": "",
        "source_report_canonical_sha256": canonical_record_sha256(report),
        "promoted_skill_version": gate["promoted_skill_version"],
        "normal_runtime_permission": True,
        "counts_toward_capability": False,
        "counts_toward_m4": False,
    })
    return runtime_gate


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
    output_path = repository_path(args.output or DEFAULT_PROMOTIONS[args.task_id])
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
    output_path = repository_path(
        args.output or DEFAULT_PROMOTIONS[args.task_id],
        must_exist=True,
    )
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


def run_promote_executable(args: argparse.Namespace) -> int:
    task_id = str(args.task_id)
    config = EXECUTABLE_PROMOTION_CONFIGS[task_id]
    storage_path = repository_path(args.storage_path, must_exist=True)
    learning_ledger_path = repository_path(args.learning_ledger)
    paired_report_path = repository_path(
        args.paired_report or DEFAULT_PAIRED_REPORTS[task_id],
        must_exist=True,
    )
    output_path = repository_path(
        args.output or DEFAULT_EXECUTABLE_PROMOTIONS[task_id]
    )
    runtime_gate_path = repository_path(
        args.runtime_gate_output or DEFAULT_RUNTIME_GATES[task_id]
    )
    if output_path == runtime_gate_path:
        raise ValueError("promotion output and runtime gate output must be different files")

    report, gate, policy_identity, config = validated_promotion_report(
        paired_report_path,
        task_id,
    )
    policy = config["policy"]
    target = policy["target_skill"]
    policy_gate = policy["promotion_gate"]
    source_version = str(target["version"])
    promoted_version = str(policy_gate["promoted_version"])
    skill_id = str(target["skill_id"])
    report_binding = {
        "path": relative_path(paired_report_path),
        "sha256": file_sha256(paired_report_path),
        "canonical_sha256": canonical_record_sha256(report),
        "policy_id": report["policy_id"],
        "policy_sha256": report["policy_sha256"],
        "evaluation_window_id": report["evaluation_window_id"],
        "valid_pair_count": report["valid_pair_count"],
        "candidate_replicate_ids": [pair["replicate_id"] for pair in report["pairs"]],
    }
    gate_fingerprint = evidence_fingerprint(gate)

    library = SkillLibrary(storage_path=str(storage_path), persist=True)
    source_skill = exact_skill_version(library, skill_id, source_version)
    source_hash = canonical_record_sha256(asdict(source_skill))
    if source_skill.status != target["required_status"]:
        raise ValueError(f"source skill is not advisory: {source_skill.status}")
    if source_hash != target["record_canonical_sha256"]:
        raise ValueError("source advisory skill does not match the frozen v5 record")

    existing_versions = library.skill_versions(skill_id)
    promoted_matches = [
        skill for skill in existing_versions
        if skill.version == promoted_version
    ]
    existing_artifacts = (output_path.exists(), runtime_gate_path.exists())
    if promoted_matches or any(existing_artifacts):
        if len(promoted_matches) != 1 or existing_artifacts != (True, True):
            raise ValueError("partial or duplicate executable promotion state detected")
        promoted = promoted_matches[0]
        promotion = read_json(output_path)
        runtime_gate = read_json(runtime_gate_path)
        promoted_gate = (
            promoted.gate.get("executable_promotion", {})
            if isinstance(promoted.gate, dict)
            else {}
        )
        learning = read_json(learning_ledger_path)
        checks = {
            "promoted_status": promoted.status == "executable",
            "promoted_parent": promoted.parent_version == source_version,
            "promoted_rollback": promoted.rollback_target == source_version,
            "promoted_gate": evidence_fingerprint(promoted_gate) == gate_fingerprint,
            "promotion_type": promotion.get("type") == "stone_pickaxe_skill_executable_promotion",
            "promotion_task": promotion.get("task_id") == task_id,
            "promotion_stage": promotion.get("stage") == "executable",
            "promotion_report": promotion.get("paired_evaluation") == report_binding,
            "promotion_gate": promotion.get("executable_promotion_gate_fingerprint") == gate_fingerprint,
            "promotion_skill_hash": (
                promotion.get("promoted_skill", {}).get("record_canonical_sha256")
                == canonical_record_sha256(asdict(promoted))
            ),
            "runtime_gate_hash": (
                promotion.get("runtime_default_gate", {}).get("sha256")
                == file_sha256(runtime_gate_path)
            ),
            "runtime_gate_readiness": runtime_gate.get("readiness") == "approved",
            "runtime_gate_permission": runtime_gate.get("normal_runtime_permission") is True,
            "runtime_gate_fingerprint": (
                runtime_gate.get("executable_promotion_gate_fingerprint") == gate_fingerprint
            ),
            "learning_ledger": (
                f"{skill_id}@{promoted_version}" in learning.get("skills", {})
                and learning["skills"][f"{skill_id}@{promoted_version}"].get("status")
                == "executable"
            ),
        }
        failed = sorted(name for name, passed in checks.items() if not passed)
        if failed:
            raise ValueError(f"existing executable promotion is inconsistent: {failed}")
        print(json.dumps({
            "skill_id": skill_id,
            "source_version": source_version,
            "promoted_version": promoted_version,
            "stage": "executable",
            "changed": False,
            "reason": "exact_promotion_already_applied",
            "output": relative_path(output_path),
            "runtime_gate": relative_path(runtime_gate_path),
        }, indent=2))
        return 0

    transition = library.transition_skill_status(
        skill_id,
        "executable",
        config["transition_reason"],
        evidence={
            "executable_promotion_gate": gate,
            "paired_evaluation": report_binding,
        },
        promoted_version=promoted_version,
    )
    if not transition.get("changed"):
        raise ValueError(
            f"executable promotion rejected: {transition.get('reason')}; "
            f"{transition.get('issues', [])}"
        )
    promoted = exact_skill_version(library, skill_id, promoted_version)
    promoted_gate = promoted.gate.get("executable_promotion", {})
    if promoted.status != "executable":
        raise RuntimeError("promoted skill is not executable")
    if promoted.parent_version != source_version or promoted.rollback_target != source_version:
        raise RuntimeError("promoted skill version lineage is invalid")
    if evidence_fingerprint(promoted_gate) != gate_fingerprint:
        raise RuntimeError("promoted skill gate fingerprint changed")

    runtime_gate = build_stone_pickaxe_runtime_gate(
        report,
        gate,
        promoted.name,
        relative_path(paired_report_path),
    )
    runtime_gate.update({
        "source_report_path": relative_path(paired_report_path),
        "source_report_sha256": file_sha256(paired_report_path),
    })
    write_json(runtime_gate_path, runtime_gate)
    promotion = {
        "type": "stone_pickaxe_skill_executable_promotion",
        "schema_version": 1,
        "report_id": f"{task_id.lower()}-executable-promotion:{gate_fingerprint[:16]}",
        "generated_at_utc": utc_now(),
        "protocol_id": PROTOCOL["id"],
        "protocol_sha256": PROTOCOL_SHA256,
        "task_id": task_id,
        "skill_id": skill_id,
        "candidate_id": target["candidate_id"],
        "stage": "executable",
        "source_skill": {
            "version": source_version,
            "status": source_skill.status,
            "record_canonical_sha256": source_hash,
            "preserved": True,
        },
        "promoted_skill": {
            "name": promoted.name,
            "version": promoted.version,
            "status": promoted.status,
            "parent_version": promoted.parent_version,
            "rollback_target": promoted.rollback_target,
            "record_canonical_sha256": canonical_record_sha256(asdict(promoted)),
        },
        "paired_evaluation": report_binding,
        "policy_identity": {
            "passed": policy_identity["passed"],
            "policy_sha256": policy_identity["policy_sha256"],
            "source_skill_record_canonical_sha256": policy_identity[
                "skill_record_canonical_sha256"
            ],
        },
        "executable_promotion_gate": gate,
        "executable_promotion_gate_fingerprint": gate_fingerprint,
        "runtime_default_gate": {
            "path": relative_path(runtime_gate_path),
            "sha256": file_sha256(runtime_gate_path),
            "readiness": runtime_gate["readiness"],
            "decision": runtime_gate["decision"],
            "promotion_gate_fingerprint": runtime_gate[
                "executable_promotion_gate_fingerprint"
            ],
        },
        "lifecycle_transition": transition,
        "normal_runtime_permission": True,
        "automatic_live_resume_allowed": False,
        "counts_toward_capability": False,
        "counts_toward_m4": False,
        "next_gate": config["next_gate"],
        "artifacts": {
            "custom_skills": relative_path(storage_path / "custom_skills.jsonl"),
            "skill_learning_ledger": relative_path(learning_ledger_path),
            "paired_report_mutated": False,
            "source_skill_mutated": False,
        },
    }
    write_json(output_path, promotion)
    learning = SkillLearningLedger(str(learning_ledger_path))
    learning.record_skill(promoted)
    learning.record_experiment(promotion)
    learning.record_decision(
        skill_id,
        "promote_executable_new_version",
        config["decision_reason"],
        evidence={
            "paired_evaluation": report_binding,
            "executable_promotion_gate": gate,
            "runtime_default_gate_path": relative_path(runtime_gate_path),
        },
    )
    print(json.dumps({
        "skill_id": skill_id,
        "source_version": source_version,
        "promoted_version": promoted_version,
        "stage": promoted.status,
        "changed": True,
        "normal_runtime_permission": True,
        "output": relative_path(output_path),
        "runtime_gate": relative_path(runtime_gate_path),
    }, indent=2))
    return 0


def main() -> int:
    args = parse_args()
    if args.command == "extract-candidate":
        return run_extract_candidate(args)
    if args.command == "promote-advisory":
        return run_promote_advisory(args)
    if args.command == "promote-executable":
        return run_promote_executable(args)
    raise RuntimeError(f"unsupported command: {args.command}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, indent=2), file=sys.stderr)
        raise
