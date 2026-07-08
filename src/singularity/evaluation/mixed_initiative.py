"""Mixed-initiative Minecraft task templates and bounded validators.

This module is inspired by MineNPC-Task's evaluation shape: user-authored
requests are compiled into compact subtask records with explicit dependencies,
slot parameters, at most one targeted clarification, and machine-checkable
validators that only use bounded in-world evidence.
"""
from __future__ import annotations

import math
import json
import os
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Optional


BOUNDED_EVIDENCE_KEYS = [
    "pre_observation",
    "post_observation",
    "recent_chat",
    "actions",
]


@dataclass
class SlotSpec:
    name: str
    required: bool = True
    default: Any = None
    question: str = ""
    clarify_if_default: bool = False


@dataclass
class SlotBinding:
    name: str
    value: Any = None
    source: str = "missing"
    required: bool = True
    question: str = ""
    bound: bool = False


@dataclass
class SubtaskTemplate:
    id: str
    name: str
    dependencies: list[str] = field(default_factory=list)
    slots: list[SlotSpec] = field(default_factory=list)
    preconditions: dict = field(default_factory=dict)
    success_criterion: str = ""
    success_validator: dict = field(default_factory=dict)


@dataclass
class MixedInitiativeTaskTemplate:
    id: str
    name: str
    category: str
    goal_pattern: str
    subtasks: list[SubtaskTemplate]
    bounded_policy: dict = field(default_factory=dict)


@dataclass
class SubtaskRecord:
    id: str
    name: str
    dependencies: list[str]
    required_parameters: list[str]
    bound_parameters: dict
    missing_parameters: list[str]
    slot_sources: dict
    clarifying_question: str = ""
    preconditions: dict = field(default_factory=dict)
    success_criterion: str = ""
    success_validator: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class MixedInitiativePlan:
    template_id: str
    template_name: str
    category: str
    goal: str
    plan_preview: str
    subtasks: list[SubtaskRecord]
    clarifying_questions: list[str] = field(default_factory=list)
    suppressed_questions: list[str] = field(default_factory=list)
    memory_write_candidates: list[dict] = field(default_factory=list)
    bounded_policy: dict = field(default_factory=dict)

    @property
    def unbound_slot_count(self) -> int:
        return sum(len(subtask.missing_parameters) for subtask in self.subtasks)

    @property
    def needs_clarification(self) -> bool:
        return bool(self.clarifying_questions)

    def to_dict(self) -> dict:
        return {
            "template_id": self.template_id,
            "template_name": self.template_name,
            "category": self.category,
            "goal": self.goal,
            "plan_preview": self.plan_preview,
            "needs_clarification": self.needs_clarification,
            "unbound_slot_count": self.unbound_slot_count,
            "clarifying_questions": list(self.clarifying_questions),
            "suppressed_questions": list(self.suppressed_questions),
            "memory_write_candidates": list(self.memory_write_candidates),
            "bounded_policy": dict(self.bounded_policy),
            "subtasks": [subtask.to_dict() for subtask in self.subtasks],
        }


@dataclass
class BoundedPolicyViolation:
    kind: str
    detail: str
    action_index: Optional[int] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SubtaskValidationResult:
    subtask_id: str
    subtask_name: str
    success: bool
    status: str
    evidence: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    policy_violations: list[BoundedPolicyViolation] = field(default_factory=list)
    bounded_evidence_keys: list[str] = field(default_factory=lambda: list(BOUNDED_EVIDENCE_KEYS))

    def to_dict(self) -> dict:
        return {
            "subtask_id": self.subtask_id,
            "subtask_name": self.subtask_name,
            "success": self.success,
            "status": self.status,
            "evidence": list(self.evidence),
            "missing": list(self.missing),
            "policy_violations": [violation.to_dict() for violation in self.policy_violations],
            "bounded_evidence_keys": list(self.bounded_evidence_keys),
        }


@dataclass
class MixedInitiativeTraceCase:
    source_log: str
    goal: str
    event_count: int = 0
    observation_count: int = 0
    action_count: int = 0
    valid_action_count: int = 0
    invalid_action_count: int = 0
    successful_action_count: int = 0
    failed_action_count: int = 0
    valid_successful_action_count: int = 0
    action_type_counts: dict = field(default_factory=dict)
    successful_action_type_counts: dict = field(default_factory=dict)
    template_id: str = ""
    template_name: str = ""
    category: str = ""
    unsupported_template: bool = False
    plan_preview: str = ""
    subtask_count: int = 0
    needs_clarification: bool = False
    unbound_slot_count: int = 0
    clarifying_questions: list[str] = field(default_factory=list)
    suppressed_questions: list[str] = field(default_factory=list)
    memory_write_candidate_count: int = 0
    validation_passed_count: int = 0
    validation_failed_count: int = 0
    validation_invalid_count: int = 0
    validation_unknown_count: int = 0
    policy_violation_count: int = 0
    goal_verification_status: str = ""
    goal_verification_achieved: Optional[bool] = None
    goal_verification_accepted: Optional[bool] = None
    validator_success: bool = False
    agreement: str = "unverified"
    template_candidate: dict = field(default_factory=dict)
    plan: dict = field(default_factory=dict)
    validation: list[dict] = field(default_factory=list)
    evidence_summary: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class MixedInitiativeTraceReport:
    cases: list[MixedInitiativeTraceCase] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def log_count(self) -> int:
        return len({case.source_log for case in self.cases})

    @property
    def goal_count(self) -> int:
        return len(self.cases)

    @property
    def needs_clarification_count(self) -> int:
        return sum(1 for case in self.cases if case.needs_clarification)

    @property
    def unbound_slot_count(self) -> int:
        return sum(case.unbound_slot_count for case in self.cases)

    @property
    def validator_success_count(self) -> int:
        return sum(1 for case in self.cases if case.validator_success)

    @property
    def action_count(self) -> int:
        return sum(case.action_count for case in self.cases)

    @property
    def valid_action_count(self) -> int:
        return sum(case.valid_action_count for case in self.cases)

    @property
    def invalid_action_count(self) -> int:
        return sum(case.invalid_action_count for case in self.cases)

    @property
    def successful_action_count(self) -> int:
        return sum(case.successful_action_count for case in self.cases)

    @property
    def failed_action_count(self) -> int:
        return sum(case.failed_action_count for case in self.cases)

    @property
    def valid_successful_action_count(self) -> int:
        return sum(case.valid_successful_action_count for case in self.cases)

    @property
    def action_success_rate(self) -> float:
        return self.successful_action_count / self.action_count if self.action_count else 0.0

    @property
    def valid_action_success_rate(self) -> float:
        return self.valid_successful_action_count / self.valid_action_count if self.valid_action_count else 0.0

    @property
    def policy_violation_count(self) -> int:
        return sum(case.policy_violation_count for case in self.cases)

    @property
    def unsupported_goal_count(self) -> int:
        return sum(1 for case in self.cases if case.unsupported_template)

    @property
    def agreement_counts(self) -> dict:
        counts = {}
        for case in self.cases:
            counts[case.agreement] = counts.get(case.agreement, 0) + 1
        return counts

    @property
    def template_candidates(self) -> list[dict]:
        grouped = {}
        for case in self.cases:
            candidate = case.template_candidate or {}
            candidate_id = candidate.get("candidate_id", "")
            if not candidate_id:
                continue
            item = grouped.setdefault(candidate_id, {
                "candidate_id": candidate_id,
                "category": candidate.get("category", "general"),
                "goal_pattern": candidate.get("goal_pattern", ""),
                "suggested_slots": candidate.get("suggested_slots", []),
                "suggested_validators": candidate.get("suggested_validators", []),
                "reason": candidate.get("reason", ""),
                "count": 0,
                "example_goals": [],
            })
            item["count"] += 1
            if case.goal not in item["example_goals"]:
                item["example_goals"].append(case.goal)
        return sorted(
            grouped.values(),
            key=lambda item: (-item["count"], item["candidate_id"]),
        )

    @property
    def action_type_counts(self) -> dict:
        counts = {}
        for case in self.cases:
            for action_type, count in case.action_type_counts.items():
                counts[action_type] = counts.get(action_type, 0) + count
        return dict(sorted(counts.items()))

    @property
    def template_action_metrics(self) -> list[dict]:
        grouped = {}
        for case in self.cases:
            key = case.template_id or "unknown"
            item = grouped.setdefault(key, {
                "template_id": key,
                "category": case.category,
                "case_count": 0,
                "action_count": 0,
                "valid_action_count": 0,
                "invalid_action_count": 0,
                "successful_action_count": 0,
                "failed_action_count": 0,
                "valid_successful_action_count": 0,
                "validator_success_count": 0,
                "policy_violation_count": 0,
                "action_type_counts": {},
            })
            item["case_count"] += 1
            item["action_count"] += case.action_count
            item["valid_action_count"] += case.valid_action_count
            item["invalid_action_count"] += case.invalid_action_count
            item["successful_action_count"] += case.successful_action_count
            item["failed_action_count"] += case.failed_action_count
            item["valid_successful_action_count"] += case.valid_successful_action_count
            item["validator_success_count"] += 1 if case.validator_success else 0
            item["policy_violation_count"] += case.policy_violation_count
            for action_type, count in case.action_type_counts.items():
                counts = item["action_type_counts"]
                counts[action_type] = counts.get(action_type, 0) + count
        metrics = []
        for item in grouped.values():
            action_count = item["action_count"]
            valid_count = item["valid_action_count"]
            item["action_success_rate"] = item["successful_action_count"] / action_count if action_count else 0.0
            item["valid_action_success_rate"] = (
                item["valid_successful_action_count"] / valid_count if valid_count else 0.0
            )
            item["action_type_counts"] = dict(sorted(item["action_type_counts"].items()))
            metrics.append(item)
        return sorted(metrics, key=lambda item: item["template_id"])

    @property
    def mixed_initiative_feedback(self) -> dict:
        return _mixed_initiative_feedback(self)

    @property
    def mixed_initiative_recommendations(self) -> list[dict]:
        return MixedInitiativeFeedbackPolicy(self.mixed_initiative_feedback).recommendations()

    def to_dict(self) -> dict:
        return {
            "log_count": self.log_count,
            "goal_count": self.goal_count,
            "needs_clarification_count": self.needs_clarification_count,
            "unbound_slot_count": self.unbound_slot_count,
            "validator_success_count": self.validator_success_count,
            "action_count": self.action_count,
            "valid_action_count": self.valid_action_count,
            "invalid_action_count": self.invalid_action_count,
            "successful_action_count": self.successful_action_count,
            "failed_action_count": self.failed_action_count,
            "valid_successful_action_count": self.valid_successful_action_count,
            "action_success_rate": self.action_success_rate,
            "valid_action_success_rate": self.valid_action_success_rate,
            "policy_violation_count": self.policy_violation_count,
            "unsupported_goal_count": self.unsupported_goal_count,
            "agreement_counts": self.agreement_counts,
            "template_candidates": self.template_candidates,
            "action_type_counts": self.action_type_counts,
            "template_action_metrics": self.template_action_metrics,
            "mixed_initiative_feedback": self.mixed_initiative_feedback,
            "mixed_initiative_recommendations": self.mixed_initiative_recommendations,
            "errors": list(self.errors),
            "cases": [case.to_dict() for case in self.cases],
        }


@dataclass
class MixedInitiativeVariantCase:
    id: str
    goal: str
    expected_template_id: str = ""
    expected_slots: dict = field(default_factory=dict)
    context: dict = field(default_factory=dict)
    evidence: dict = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    source: str = "builtin"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class MixedInitiativeVariantResult:
    id: str
    source: str
    goal: str
    tags: list[str] = field(default_factory=list)
    expected_template_id: str = ""
    actual_template_id: str = ""
    template_match: bool = True
    expected_slots: dict = field(default_factory=dict)
    bound_slots: dict = field(default_factory=dict)
    slot_matches: dict = field(default_factory=dict)
    slot_mismatches: list[str] = field(default_factory=list)
    slot_match: bool = True
    needs_clarification: bool = False
    unbound_slot_count: int = 0
    plan_preview: str = ""
    validation_checked: bool = False
    validation_success: Optional[bool] = None
    validation_passed_count: int = 0
    validation_failed_count: int = 0
    validation_invalid_count: int = 0
    validation_unknown_count: int = 0
    policy_violation_count: int = 0
    fully_passed: bool = False
    plan: dict = field(default_factory=dict)
    validation: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class MixedInitiativeVariantReport:
    cases: list[MixedInitiativeVariantResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def case_count(self) -> int:
        return len(self.cases)

    @property
    def template_match_count(self) -> int:
        return sum(1 for case in self.cases if case.template_match)

    @property
    def template_mismatch_count(self) -> int:
        return sum(1 for case in self.cases if not case.template_match)

    @property
    def slot_match_count(self) -> int:
        return sum(1 for case in self.cases if case.slot_match)

    @property
    def slot_mismatch_count(self) -> int:
        return sum(1 for case in self.cases if not case.slot_match)

    @property
    def validation_checked_count(self) -> int:
        return sum(1 for case in self.cases if case.validation_checked)

    @property
    def validation_success_count(self) -> int:
        return sum(1 for case in self.cases if case.validation_success is True)

    @property
    def validation_failure_count(self) -> int:
        return sum(1 for case in self.cases if case.validation_success is False)

    @property
    def clarification_count(self) -> int:
        return sum(1 for case in self.cases if case.needs_clarification)

    @property
    def fully_passed_count(self) -> int:
        return sum(1 for case in self.cases if case.fully_passed)

    def to_dict(self) -> dict:
        return {
            "case_count": self.case_count,
            "template_match_count": self.template_match_count,
            "template_mismatch_count": self.template_mismatch_count,
            "slot_match_count": self.slot_match_count,
            "slot_mismatch_count": self.slot_mismatch_count,
            "validation_checked_count": self.validation_checked_count,
            "validation_success_count": self.validation_success_count,
            "validation_failure_count": self.validation_failure_count,
            "clarification_count": self.clarification_count,
            "fully_passed_count": self.fully_passed_count,
            "errors": list(self.errors),
            "cases": [case.to_dict() for case in self.cases],
        }


@dataclass
class MixedInitiativeReviewQueueItem:
    id: str
    target_type: str
    target_id: str
    decision: str
    priority: str = "normal"
    reason: str = ""
    status: str = "pending"
    recommendation_count: int = 0
    source_reports: list[str] = field(default_factory=list)
    source_logs: list[str] = field(default_factory=list)
    source_goals: list[str] = field(default_factory=list)
    active_policies: list[str] = field(default_factory=list)
    action_items: list[str] = field(default_factory=list)
    recommendations: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class MixedInitiativeReviewQueueReport:
    items: list[MixedInitiativeReviewQueueItem] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def item_count(self) -> int:
        return len(self.items)

    @property
    def high_priority_count(self) -> int:
        return sum(1 for item in self.items if item.priority == "high")

    @property
    def target_type_counts(self) -> dict:
        counts = {}
        for item in self.items:
            counts[item.target_type] = counts.get(item.target_type, 0) + 1
        return dict(sorted(counts.items()))

    @property
    def decision_counts(self) -> dict:
        counts = {}
        for item in self.items:
            counts[item.decision] = counts.get(item.decision, 0) + 1
        return dict(sorted(counts.items()))

    def to_dict(self) -> dict:
        return {
            "item_count": self.item_count,
            "high_priority_count": self.high_priority_count,
            "target_type_counts": self.target_type_counts,
            "decision_counts": self.decision_counts,
            "errors": list(self.errors),
            "items": [item.to_dict() for item in self.items],
        }


@dataclass
class MixedInitiativeReviewExperimentCase:
    id: str
    queue_item_id: str
    route: str
    priority: str
    target_type: str
    target_id: str
    decision: str
    ready: bool = False
    hypothesis: str = ""
    status: str = "planned"
    missing_inputs: list[str] = field(default_factory=list)
    source_reports: list[str] = field(default_factory=list)
    source_logs: list[str] = field(default_factory=list)
    source_goals: list[str] = field(default_factory=list)
    action_items: list[str] = field(default_factory=list)
    recommended_commands: list[str] = field(default_factory=list)
    success_metrics: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class MixedInitiativeReviewExperimentPlan:
    cases: list[MixedInitiativeReviewExperimentCase] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def case_count(self) -> int:
        return len(self.cases)

    @property
    def ready_count(self) -> int:
        return sum(1 for case in self.cases if case.ready)

    @property
    def high_priority_count(self) -> int:
        return sum(1 for case in self.cases if case.priority == "high")

    @property
    def route_counts(self) -> dict:
        counts = {}
        for case in self.cases:
            counts[case.route] = counts.get(case.route, 0) + 1
        return dict(sorted(counts.items()))

    def to_dict(self) -> dict:
        return {
            "case_count": self.case_count,
            "ready_count": self.ready_count,
            "high_priority_count": self.high_priority_count,
            "route_counts": self.route_counts,
            "errors": list(self.errors),
            "cases": [case.to_dict() for case in self.cases],
        }


@dataclass
class MixedInitiativeReviewApprovalCase:
    index: int
    ok: bool = False
    key: str = ""
    case_id: str = ""
    queue_item_id: str = ""
    route: str = ""
    target_type: str = ""
    target_id: str = ""
    decision: str = ""
    raw_readiness: str = ""
    readiness: str = ""
    reviewer: str = ""
    notes: str = ""
    source_logs: list[str] = field(default_factory=list)
    source_goals: list[str] = field(default_factory=list)
    recommended_commands: list[str] = field(default_factory=list)
    success_metrics: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def approved(self) -> bool:
        return self.ok and self.readiness == "approved"

    @property
    def executable(self) -> bool:
        return self.approved and bool(self.recommended_commands)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["approved"] = self.approved
        data["executable"] = self.executable
        return data


@dataclass
class MixedInitiativeReviewApprovalReport:
    label_path: str = ""
    cases: list[MixedInitiativeReviewApprovalCase] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def label_count(self) -> int:
        return len(self.cases)

    @property
    def ok_count(self) -> int:
        return sum(1 for case in self.cases if case.ok)

    @property
    def approved_count(self) -> int:
        return sum(1 for case in self.cases if case.readiness == "approved")

    @property
    def rejected_count(self) -> int:
        return sum(1 for case in self.cases if case.readiness == "rejected")

    @property
    def unknown_count(self) -> int:
        return sum(1 for case in self.cases if case.readiness == "unknown")

    @property
    def executable_count(self) -> int:
        return sum(1 for case in self.cases if case.executable)

    @property
    def approved_route_counts(self) -> dict:
        counts = {}
        for case in self.cases:
            if case.approved:
                counts[case.route] = counts.get(case.route, 0) + 1
        return dict(sorted(counts.items()))

    @property
    def ok(self) -> bool:
        return not self.errors and all(case.ok for case in self.cases)

    def to_dict(self) -> dict:
        return {
            "label_path": self.label_path,
            "ok": self.ok,
            "label_count": self.label_count,
            "ok_count": self.ok_count,
            "approved_count": self.approved_count,
            "rejected_count": self.rejected_count,
            "unknown_count": self.unknown_count,
            "executable_count": self.executable_count,
            "approved_route_counts": self.approved_route_counts,
            "errors": list(self.errors),
            "cases": [case.to_dict() for case in self.cases],
        }


@dataclass
class MixedInitiativeReviewExecutionCase:
    case_id: str
    route: str
    target_id: str
    readiness: str
    status: str = "skipped"
    approved: bool = False
    executable: bool = False
    dry_run: bool = False
    source_logs: list[str] = field(default_factory=list)
    recommended_commands: list[str] = field(default_factory=list)
    artifact_paths: list[str] = field(default_factory=list)
    artifact_summaries: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def executed(self) -> bool:
        return self.status == "executed"

    def to_dict(self) -> dict:
        data = asdict(self)
        data["executed"] = self.executed
        return data


@dataclass
class MixedInitiativeReviewExecutionReport:
    approval: MixedInitiativeReviewApprovalReport
    dry_run: bool = False
    output_dir: str = ""
    cases: list[MixedInitiativeReviewExecutionCase] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def case_count(self) -> int:
        return len(self.cases)

    @property
    def executed_count(self) -> int:
        return sum(1 for case in self.cases if case.status == "executed")

    @property
    def skipped_count(self) -> int:
        return sum(1 for case in self.cases if case.status == "skipped")

    @property
    def failed_count(self) -> int:
        return sum(1 for case in self.cases if case.status == "failed")

    @property
    def dry_run_count(self) -> int:
        return sum(1 for case in self.cases if case.status == "dry_run")

    @property
    def route_counts(self) -> dict:
        counts = {}
        for case in self.cases:
            counts[case.route] = counts.get(case.route, 0) + 1
        return dict(sorted(counts.items()))

    @property
    def ok(self) -> bool:
        return not self.errors and self.failed_count == 0 and self.approval.ok

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "dry_run": self.dry_run,
            "output_dir": self.output_dir,
            "case_count": self.case_count,
            "executed_count": self.executed_count,
            "skipped_count": self.skipped_count,
            "failed_count": self.failed_count,
            "dry_run_count": self.dry_run_count,
            "route_counts": self.route_counts,
            "errors": list(self.errors),
            "approval": self.approval.to_dict(),
            "cases": [case.to_dict() for case in self.cases],
        }


class MixedInitiativeTemplateCompiler:
    """Compile template subtasks into auditable records with slot binding."""

    def __init__(self, templates: Optional[dict[str, MixedInitiativeTaskTemplate]] = None):
        self.templates = templates or builtin_minenpc_templates()

    def compile_goal(
        self,
        goal: str,
        template_id: str = "auto",
        context: Optional[dict] = None,
    ) -> MixedInitiativePlan:
        context = context or {}
        template = self.select_template(goal, template_id)
        inferred_slots = self._infer_goal_slots(template.id, goal)
        context_slots = dict(inferred_slots)
        context_slots.update(context.get("slots", {}))
        bind_context = dict(context)
        bind_context["slots"] = context_slots

        subtasks = []
        questions = []
        suppressed = []
        memory_candidates = []
        for subtask in template.subtasks:
            record, subtask_questions, subtask_memory = self._compile_subtask(
                subtask,
                bind_context,
                template,
            )
            subtasks.append(record)
            for question in subtask_questions:
                if len(questions) < 1:
                    questions.append(question)
                else:
                    suppressed.append(question)
            memory_candidates.extend(subtask_memory)

        return MixedInitiativePlan(
            template_id=template.id,
            template_name=template.name,
            category=template.category,
            goal=goal,
            plan_preview=" -> ".join(subtask.name for subtask in subtasks),
            subtasks=subtasks,
            clarifying_questions=questions,
            suppressed_questions=suppressed,
            memory_write_candidates=memory_candidates,
            bounded_policy=self._bounded_policy(template),
        )

    def select_template(self, goal: str, template_id: str = "auto") -> MixedInitiativeTaskTemplate:
        if template_id and template_id != "auto":
            if template_id not in self.templates:
                available = ", ".join(sorted(self.templates))
                raise ValueError(f"unknown template '{template_id}', available: {available}")
            return self.templates[template_id]

        goal_lower = str(goal or "").lower()
        collection_terms = ("mine", "dig", "collect", "gather", "harvest", "get", "fetch", "bring", "retrieve")
        craft_terms = ("craft", "make", "smelt", "cook")
        build_terms = ("build", "place", "shelter", "house", "wall", "bridge")
        oak_log_terms = ("log", "logs", "wood", "oak")
        if any(token in goal_lower for token in ("pickaxe", "pick axe", "tool")) and any(
            token in goal_lower for token in ("get", "fetch", "bring", "retrieve")
        ):
            return self.templates["fetch_named_tool"]
        if any(token in goal_lower for token in craft_terms):
            return self.templates["craft_or_process_item"]
        if any(token in goal_lower for token in oak_log_terms) and any(
            token in goal_lower for token in collection_terms
        ):
            return self.templates["collect_oak_logs"]
        if any(token in goal_lower for token in ("mine", "dig", "collect", "gather", "harvest")):
            return self.templates["collect_or_mine_resource"]
        if any(token in goal_lower for token in build_terms):
            return self.templates["build_or_place_structure"]
        if any(token in goal_lower for token in oak_log_terms):
            return self.templates["collect_oak_logs"]
        return self.templates["unsupported_request"]

    def _compile_subtask(
        self,
        subtask: SubtaskTemplate,
        context: dict,
        template: MixedInitiativeTaskTemplate,
    ) -> tuple[SubtaskRecord, list[str], list[dict]]:
        bindings = [self._bind_slot(slot, context) for slot in subtask.slots]
        bound_parameters = {
            binding.name: binding.value
            for binding in bindings
            if binding.bound or binding.value not in (None, "")
        }
        missing = [binding.name for binding in bindings if binding.required and not binding.bound]
        slot_sources = {binding.name: binding.source for binding in bindings}
        questions = []
        for binding in bindings:
            if not binding.question:
                continue
            if binding.required and not binding.bound:
                questions.append(binding.question)
            elif binding.source == "default" and self._slot_by_name(subtask, binding.name).clarify_if_default:
                questions.append(binding.question)

        memory_candidates = []
        for binding in bindings:
            if binding.source == "clarification_answer":
                memory_candidates.append({
                    "memory_type": "scoped_preference",
                    "scope": template.category,
                    "template_id": template.id,
                    "slot": binding.name,
                    "value": binding.value,
                    "provenance": "told",
                })

        return (
            SubtaskRecord(
                id=subtask.id,
                name=subtask.name,
                dependencies=list(subtask.dependencies),
                required_parameters=[slot.name for slot in subtask.slots if slot.required],
                bound_parameters=bound_parameters,
                missing_parameters=missing,
                slot_sources=slot_sources,
                clarifying_question=questions[0] if questions else "",
                preconditions=self._resolve_template_values(subtask.preconditions, bound_parameters),
                success_criterion=subtask.success_criterion,
                success_validator=self._resolve_template_values(subtask.success_validator, bound_parameters),
            ),
            questions,
            memory_candidates,
        )

    def _bind_slot(self, slot: SlotSpec, context: dict) -> SlotBinding:
        for source_name, values in (
            ("clarification_answer", context.get("clarification_answers", {})),
            ("user_context", context.get("slots", {})),
            ("memory_preference", context.get("memory_preferences", {})),
        ):
            if isinstance(values, dict) and slot.name in values and values[slot.name] not in (None, ""):
                return SlotBinding(
                    name=slot.name,
                    value=values[slot.name],
                    source=source_name,
                    required=slot.required,
                    question=slot.question,
                    bound=True,
                )
        if slot.default not in (None, ""):
            return SlotBinding(
                name=slot.name,
                value=slot.default,
                source="default",
                required=slot.required,
                question=slot.question,
                bound=not slot.required or not slot.clarify_if_default,
            )
        return SlotBinding(
            name=slot.name,
            required=slot.required,
            question=slot.question,
            bound=False,
        )

    def _slot_by_name(self, subtask: SubtaskTemplate, name: str) -> SlotSpec:
        for slot in subtask.slots:
            if slot.name == name:
                return slot
        return SlotSpec(name=name)

    def _resolve_template_values(self, value: Any, parameters: dict) -> Any:
        if isinstance(value, dict):
            return {
                self._resolve_template_string(key, parameters): self._resolve_template_values(item, parameters)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [self._resolve_template_values(item, parameters) for item in value]
        if isinstance(value, str):
            return self._resolve_template_string(value, parameters)
        return value

    def _resolve_template_string(self, value: str, parameters: dict) -> Any:
        if value.startswith("$") and value[1:] in parameters:
            return parameters[value[1:]]
        if value.startswith("$"):
            for name in sorted(parameters, key=len, reverse=True):
                prefix = f"${name}"
                if value.startswith(prefix):
                    return f"{parameters[name]}{value[len(prefix):]}"

        def replace(match):
            name = match.group(1)
            return str(parameters.get(name, match.group(0)))

        return re.sub(r"\$([a-zA-Z0-9_]+)", replace, value)

    def _bounded_policy(self, template: MixedInitiativeTaskTemplate) -> dict:
        policy = {
            "forbid_admin_commands": True,
            "forbid_global_map_introspection": True,
            "max_scan_radius": 128,
            "allowed_evidence": list(BOUNDED_EVIDENCE_KEYS),
        }
        policy.update(template.bounded_policy or {})
        return policy

    def _infer_goal_slots(self, template_id: str, goal: str) -> dict:
        goal_lower = str(goal or "").lower()
        slots = {}
        number = re.search(r"\b(\d+)\b", goal_lower)
        if number:
            slots["count"] = int(number.group(1))
        radius = re.search(r"(?:within|radius|range)\s+(\d+)\s*(?:blocks?|m)?", goal_lower)
        if radius:
            slots["search_radius"] = int(radius.group(1))
        if template_id == "collect_oak_logs" and any(token in goal_lower for token in ("oak", "log", "wood")):
            slots.setdefault("resource", "oak_log")
        if template_id == "craft_or_process_item":
            target = _target_after_keywords(goal_lower, ["craft", "make", "smelt", "cook"])
            item = _canonical_item_name(target)
            if item:
                slots["item"] = item
            slots.setdefault("count", 1)
            if any(token in goal_lower for token in ("smelt", "cook")):
                slots["process_action"] = "smelt"
                slots.setdefault("station", "furnace")
            else:
                slots["process_action"] = "craft"
        if template_id == "collect_or_mine_resource":
            target = _target_after_keywords(goal_lower, ["mine", "dig", "collect", "gather", "harvest"])
            resource, source_block = _resource_item_and_source_block(target)
            if resource:
                slots["resource"] = resource
            if source_block:
                slots["source_block"] = source_block
            slots.setdefault("count", 1)
        if template_id == "build_or_place_structure":
            target = _target_after_keywords(goal_lower, ["build", "place"]) or _structure_keyword(goal_lower)
            structure, material = _structure_and_material_from_target(target)
            if structure:
                slots["structure"] = structure
            explicit_material = _material_after_goal(goal_lower)
            if explicit_material:
                slots["material"] = explicit_material
            elif material:
                slots["material"] = material
        if template_id == "fetch_named_tool":
            for variant in ("wooden", "stone", "iron", "diamond", "netherite"):
                if re.search(rf"\b{variant}\s+pick(?:axe| axe)\b", goal_lower):
                    slots["tool_variant"] = variant
                    break
            landmark = re.search(r"\bfrom\s+([a-zA-Z0-9_ -]+)", str(goal or ""))
            if landmark:
                slots["landmark"] = landmark.group(1).strip().replace(" ", "_")
        return slots


def _mixed_initiative_feedback(report: MixedInitiativeTraceReport) -> dict:
    """Aggregate trace metrics into template and policy improvement hints."""
    template_hints = []
    for item in report.template_action_metrics:
        template_id = item["template_id"]
        action_count = int(item.get("action_count", 0) or 0)
        invalid_count = int(item.get("invalid_action_count", 0) or 0)
        failed_count = int(item.get("failed_action_count", 0) or 0)
        valid_count = int(item.get("valid_action_count", 0) or 0)
        validator_success_count = int(item.get("validator_success_count", 0) or 0)
        case_count = int(item.get("case_count", 0) or 0)
        valid_success_rate = float(item.get("valid_action_success_rate", 0.0) or 0.0)
        if invalid_count:
            template_hints.append({
                "policy": "reject_invalid_actions",
                "template_id": template_id,
                "category": item.get("category", ""),
                "priority": "high",
                "reason": "actions violated bounded-world policy and should not count as valid task progress",
                "action_count": action_count,
                "invalid_action_count": invalid_count,
                "policy_violation_count": int(item.get("policy_violation_count", 0) or 0),
            })
        if failed_count:
            priority = "high" if valid_count and valid_success_rate < 0.5 else "medium"
            template_hints.append({
                "policy": "inspect_backend_execution",
                "template_id": template_id,
                "category": item.get("category", ""),
                "priority": priority,
                "reason": "backend action failures indicate missing preconditions, wrong action parameters, or fragile control",
                "failed_action_count": failed_count,
                "valid_action_success_rate": valid_success_rate,
                "action_type_counts": dict(item.get("action_type_counts", {})),
            })
        if valid_count and valid_success_rate < 0.75:
            template_hints.append({
                "policy": "improve_action_policy",
                "template_id": template_id,
                "category": item.get("category", ""),
                "priority": "medium",
                "reason": "valid actions are succeeding too rarely for this template family",
                "valid_action_count": valid_count,
                "valid_successful_action_count": int(item.get("valid_successful_action_count", 0) or 0),
                "valid_action_success_rate": valid_success_rate,
            })
        if case_count and validator_success_count < case_count and template_id != "unsupported_request":
            template_hints.append({
                "policy": "audit_template_validator",
                "template_id": template_id,
                "category": item.get("category", ""),
                "priority": "medium",
                "reason": "some cases did not satisfy the template's bounded validator",
                "case_count": case_count,
                "validator_success_count": validator_success_count,
            })

    template_candidate_hints = [
        {
            "policy": "promote_template_candidate",
            "candidate_id": candidate["candidate_id"],
            "category": candidate.get("category", "general"),
            "priority": "medium" if int(candidate.get("count", 0) or 0) > 1 else "low",
            "reason": candidate.get("reason", "unsupported goals cluster into a reusable template family"),
            "count": int(candidate.get("count", 0) or 0),
            "suggested_slots": list(candidate.get("suggested_slots", [])),
            "suggested_validators": list(candidate.get("suggested_validators", [])),
            "example_goals": list(candidate.get("example_goals", [])[:3]),
        }
        for candidate in report.template_candidates
    ]

    agreement_hints = []
    agreement_counts = report.agreement_counts
    if agreement_counts.get("validator_stricter", 0):
        agreement_hints.append({
            "policy": "audit_goal_verifier_acceptance",
            "priority": "medium",
            "reason": "GoalVerifier accepted cases that bounded template validators rejected",
            "count": int(agreement_counts.get("validator_stricter", 0) or 0),
        })
    if agreement_counts.get("goal_verifier_stricter", 0):
        agreement_hints.append({
            "policy": "strengthen_template_success_evidence",
            "priority": "medium",
            "reason": "template validators passed cases that GoalVerifier did not accept",
            "count": int(agreement_counts.get("goal_verifier_stricter", 0) or 0),
        })
    if report.needs_clarification_count:
        agreement_hints.append({
            "policy": "mine_slot_memory",
            "priority": "low",
            "reason": "repeated clarifications can become scoped memory preferences or better slot inference rules",
            "count": report.needs_clarification_count,
        })

    policy_hints = _sort_mixed_initiative_hints(
        template_hints + agreement_hints + template_candidate_hints
    )
    return {
        "goal_count": report.goal_count,
        "unsupported_goal_count": report.unsupported_goal_count,
        "validator_success_count": report.validator_success_count,
        "action_count": report.action_count,
        "invalid_action_count": report.invalid_action_count,
        "failed_action_count": report.failed_action_count,
        "valid_action_success_rate": report.valid_action_success_rate,
        "agreement_counts": report.agreement_counts,
        "template_hints": _sort_mixed_initiative_hints(template_hints),
        "template_candidate_hints": template_candidate_hints,
        "agreement_hints": _sort_mixed_initiative_hints(agreement_hints),
        "policy_hints": policy_hints,
    }


def _sort_mixed_initiative_hints(hints: list[dict]) -> list[dict]:
    priority_rank = {"high": 0, "medium": 1, "low": 2}
    return sorted(
        hints,
        key=lambda hint: (
            priority_rank.get(str(hint.get("priority", "low")), 3),
            str(hint.get("policy", "")),
            str(hint.get("template_id", hint.get("candidate_id", ""))),
        ),
    )


@dataclass
class MixedInitiativePolicyDecision:
    """Advisory decision produced from mixed-initiative trace feedback."""

    target_type: str
    target_id: str
    decision: str
    priority: str = "normal"
    reason: str = "no_feedback"
    should_review: bool = False
    should_promote_template: bool = False
    should_reject_invalid_actions: bool = False
    should_inspect_backend: bool = False
    should_audit_validator: bool = False
    active_policies: list[str] = field(default_factory=list)
    hints: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        data = {
            "target_type": self.target_type,
            "target_id": self.target_id,
            "decision": self.decision,
            "priority": self.priority,
            "reason": self.reason,
            "should_review": self.should_review,
            "should_promote_template": self.should_promote_template,
            "should_reject_invalid_actions": self.should_reject_invalid_actions,
            "should_inspect_backend": self.should_inspect_backend,
            "should_audit_validator": self.should_audit_validator,
            "active_policies": list(self.active_policies),
        }
        if self.hints:
            data["hints"] = [dict(hint) for hint in self.hints]
        return data


class MixedInitiativeFeedbackPolicy:
    """Consumes mixed-initiative trace feedback for template/action review loops."""

    def __init__(self, feedback: Optional[dict] = None):
        self._hints_by_key: dict[str, dict] = {}
        if feedback:
            self.record_mixed_initiative_feedback(feedback)

    def record_mixed_initiative_feedback(self, feedback: dict) -> int:
        stored = 0
        for hint in feedback.get("policy_hints", []) if isinstance(feedback, dict) else []:
            if not isinstance(hint, dict):
                continue
            policy = str(hint.get("policy") or "")
            if not policy:
                continue
            key = self._hint_key(hint)
            self._hints_by_key[key] = dict(hint)
            stored += 1
        return stored

    def decide_template(self, template_id: str) -> MixedInitiativePolicyDecision:
        template_id = str(template_id or "")
        hints = self._hints_for("template_id", template_id)
        if not hints:
            return MixedInitiativePolicyDecision(
                target_type="template",
                target_id=template_id,
                decision="template_ok",
                reason="no mixed-initiative feedback for template",
            )
        policies = {str(hint.get("policy") or "") for hint in hints}
        priority = self._highest_priority(hints)
        if "reject_invalid_actions" in policies:
            decision = "block_invalid_progress"
            reason = "template produced actions that violated bounded-world policy"
        elif "inspect_backend_execution" in policies:
            decision = "inspect_backend_execution"
            reason = "template had backend action failures"
        elif "improve_action_policy" in policies:
            decision = "tune_action_policy"
            reason = "template valid-action success rate is low"
        elif "audit_template_validator" in policies:
            decision = "audit_template_validator"
            reason = "template validators rejected some cases"
        else:
            decision = "template_review"
            reason = "mixed-initiative feedback requests template review"
        return MixedInitiativePolicyDecision(
            target_type="template",
            target_id=template_id,
            decision=decision,
            priority=priority,
            reason=reason,
            should_review=True,
            should_reject_invalid_actions="reject_invalid_actions" in policies,
            should_inspect_backend=bool({"inspect_backend_execution", "improve_action_policy"} & policies),
            should_audit_validator="audit_template_validator" in policies,
            active_policies=sorted(policies),
            hints=hints,
        )

    def decide_candidate(self, candidate_id: str) -> MixedInitiativePolicyDecision:
        candidate_id = str(candidate_id or "")
        hints = self._hints_for("candidate_id", candidate_id)
        if not hints:
            return MixedInitiativePolicyDecision(
                target_type="template_candidate",
                target_id=candidate_id,
                decision="candidate_observe",
                reason="no promotion feedback for template candidate",
            )
        policies = {str(hint.get("policy") or "") for hint in hints}
        priority = self._highest_priority(hints)
        return MixedInitiativePolicyDecision(
            target_type="template_candidate",
            target_id=candidate_id,
            decision="promote_template_candidate" if "promote_template_candidate" in policies else "candidate_review",
            priority=priority,
            reason="unsupported goals cluster into a reusable template family",
            should_review=True,
            should_promote_template="promote_template_candidate" in policies,
            active_policies=sorted(policies),
            hints=hints,
        )

    def feedback_hints(self) -> dict:
        return {key: dict(hint) for key, hint in sorted(self._hints_by_key.items())}

    def feedback_profile(self) -> dict:
        priority_counts = {}
        template_ids = set()
        candidate_ids = set()
        policy_counts = {}
        for hint in self._hints_by_key.values():
            priority = str(hint.get("priority") or "normal")
            policy = str(hint.get("policy") or "")
            priority_counts[priority] = priority_counts.get(priority, 0) + 1
            if policy:
                policy_counts[policy] = policy_counts.get(policy, 0) + 1
            if hint.get("template_id"):
                template_ids.add(str(hint.get("template_id")))
            if hint.get("candidate_id"):
                candidate_ids.add(str(hint.get("candidate_id")))
        return {
            "hint_count": len(self._hints_by_key),
            "priority_counts": dict(sorted(priority_counts.items())),
            "policy_counts": dict(sorted(policy_counts.items())),
            "templates_for_review": sorted(template_ids),
            "candidates_for_promotion": sorted(candidate_ids),
        }

    def recommendations(self) -> list[dict]:
        decisions = []
        profile = self.feedback_profile()
        for template_id in profile["templates_for_review"]:
            decisions.append(self.decide_template(template_id).as_dict())
        for candidate_id in profile["candidates_for_promotion"]:
            decisions.append(self.decide_candidate(candidate_id).as_dict())
        return sorted(
            decisions,
            key=lambda item: (
                {"high": 0, "medium": 1, "low": 2}.get(str(item.get("priority", "normal")), 3),
                str(item.get("target_type", "")),
                str(item.get("target_id", "")),
            ),
        )

    def _hints_for(self, key: str, value: str) -> list[dict]:
        return _sort_mixed_initiative_hints([
            hint
            for hint in self._hints_by_key.values()
            if str(hint.get(key) or "") == value
        ])

    def _hint_key(self, hint: dict) -> str:
        policy = str(hint.get("policy") or "")
        target = str(hint.get("template_id") or hint.get("candidate_id") or "trace")
        return f"{policy}:{target}"

    def _highest_priority(self, hints: list[dict]) -> str:
        ranked = _sort_mixed_initiative_hints(hints)
        return str(ranked[0].get("priority") or "normal") if ranked else "normal"


class BoundedEvidenceValidator:
    """Validate subtask success without hidden state or privileged commands."""

    FORBIDDEN_ACTION_TYPES = {
        "admin_command",
        "teleport",
        "give",
        "setblock",
        "fill",
        "query_seed",
        "global_scan",
        "scan_world",
    }
    FORBIDDEN_COMMAND_PREFIXES = (
        "/give",
        "/tp",
        "/teleport",
        "/gamemode",
        "/time",
        "/weather",
        "/setblock",
        "/fill",
        "/locate",
        "/seed",
    )
    HIDDEN_EVIDENCE_KEYS = {"world_seed", "global_map", "full_map", "all_loaded_chunks"}

    def __init__(self, max_scan_radius: int = 128):
        self.max_scan_radius = max_scan_radius

    def validate_subtask(self, subtask: SubtaskRecord | dict, evidence: Optional[dict]) -> SubtaskValidationResult:
        evidence = evidence or {}
        record = self._record_from_any(subtask)
        violations = self.check_bounded_policy(evidence)
        if violations:
            return SubtaskValidationResult(
                subtask_id=record.id,
                subtask_name=record.name,
                success=False,
                status="invalid",
                missing=["bounded knowledge policy violated"],
                policy_violations=violations,
            )

        validator = record.success_validator or {}
        if not validator:
            return SubtaskValidationResult(
                subtask_id=record.id,
                subtask_name=record.name,
                success=False,
                status="unknown",
                missing=["no machine-checkable validator defined"],
            )

        checks = []
        evidence_lines = []
        missing = []
        checks.extend(self._check_inventory_at_least(validator, evidence, evidence_lines, missing))
        checks.extend(self._check_inventory_delta_at_least(validator, evidence, evidence_lines, missing))
        checks.extend(self._check_equipment(validator, evidence, evidence_lines, missing))
        checks.extend(self._check_flags(validator, evidence, evidence_lines, missing))
        checks.extend(self._check_nearby_blocks(validator, evidence, evidence_lines, missing))
        checks.extend(self._check_nearby_entities_absent(validator, evidence, evidence_lines, missing))
        checks.extend(self._check_recent_chat(validator, evidence, evidence_lines, missing))
        checks.extend(self._check_action_success(validator, evidence, evidence_lines, missing))
        checks.extend(self._check_action_success_any(validator, evidence, evidence_lines, missing))
        checks.extend(self._check_position_delta(validator, evidence, evidence_lines, missing))

        if not checks:
            return SubtaskValidationResult(
                subtask_id=record.id,
                subtask_name=record.name,
                success=False,
                status="unknown",
                missing=["validator had no supported checks"],
            )

        success = all(checks)
        return SubtaskValidationResult(
            subtask_id=record.id,
            subtask_name=record.name,
            success=success,
            status="passed" if success else "failed",
            evidence=evidence_lines if success else evidence_lines,
            missing=[] if success else missing,
        )

    def check_bounded_policy(self, evidence: dict) -> list[BoundedPolicyViolation]:
        violations = []
        for key in self.HIDDEN_EVIDENCE_KEYS:
            if key in evidence:
                violations.append(BoundedPolicyViolation("hidden_evidence", f"{key} is not bounded in-world evidence"))
        for obs_key in ("pre_observation", "post_observation"):
            observation = evidence.get(obs_key, {})
            if isinstance(observation, dict):
                for key in self.HIDDEN_EVIDENCE_KEYS:
                    if key in observation:
                        violations.append(BoundedPolicyViolation("hidden_evidence", f"{obs_key}.{key} is not allowed"))

        actions = evidence.get("actions", []) or []
        if isinstance(actions, dict):
            actions = [actions]
        for index, action_event in enumerate(actions):
            action = action_event.get("action", action_event) if isinstance(action_event, dict) else {}
            action_type = str(action.get("type", "")).lower()
            if action_type in self.FORBIDDEN_ACTION_TYPES:
                violations.append(BoundedPolicyViolation("forbidden_action", action_type, index))
            command = self._command_text(action)
            if command and any(command.lower().startswith(prefix) for prefix in self.FORBIDDEN_COMMAND_PREFIXES):
                violations.append(BoundedPolicyViolation("forbidden_command", command[:80], index))
            radius = self._scan_radius(action)
            if radius is not None and radius > self.max_scan_radius:
                violations.append(BoundedPolicyViolation("scan_radius_exceeded", f"radius={radius}", index))
        return violations

    def _record_from_any(self, subtask: SubtaskRecord | dict) -> SubtaskRecord:
        if isinstance(subtask, SubtaskRecord):
            return subtask
        return SubtaskRecord(
            id=str(subtask.get("id", "")),
            name=str(subtask.get("name", "")),
            dependencies=list(subtask.get("dependencies", [])),
            required_parameters=list(subtask.get("required_parameters", [])),
            bound_parameters=dict(subtask.get("bound_parameters", {})),
            missing_parameters=list(subtask.get("missing_parameters", [])),
            slot_sources=dict(subtask.get("slot_sources", {})),
            clarifying_question=str(subtask.get("clarifying_question", "")),
            preconditions=dict(subtask.get("preconditions", {})),
            success_criterion=str(subtask.get("success_criterion", "")),
            success_validator=dict(subtask.get("success_validator", {})),
        )

    def _check_inventory_at_least(self, validator: dict, evidence: dict, evidence_lines: list[str], missing: list[str]) -> list[bool]:
        requirements = validator.get("inventory_at_least", {})
        if not isinstance(requirements, dict) or not requirements:
            return []
        inventory = self._inventory(evidence.get("post_observation", {}))
        checks = []
        for item, count in requirements.items():
            required = self._safe_int(count, 1)
            have = self._inventory_count(inventory, item)
            ok = have >= required
            checks.append(ok)
            if ok:
                evidence_lines.append(f"inventory has {have}/{required} {item}")
            else:
                missing.append(f"need {required} {item}, have {have}")
        return checks

    def _check_inventory_delta_at_least(self, validator: dict, evidence: dict, evidence_lines: list[str], missing: list[str]) -> list[bool]:
        requirements = validator.get("inventory_delta_at_least", {})
        if not isinstance(requirements, dict) or not requirements:
            return []
        before = self._inventory(evidence.get("pre_observation", {}))
        after = self._inventory(evidence.get("post_observation", {}))
        checks = []
        for item, count in requirements.items():
            required = self._safe_int(count, 1)
            delta = self._inventory_count(after, item) - self._inventory_count(before, item)
            ok = delta >= required
            checks.append(ok)
            if ok:
                evidence_lines.append(f"inventory delta gained {delta}/{required} {item}")
            else:
                missing.append(f"need inventory delta {required} {item}, gained {delta}")
        return checks

    def _check_equipment(self, validator: dict, evidence: dict, evidence_lines: list[str], missing: list[str]) -> list[bool]:
        expected = validator.get("equipment_has", {})
        if not isinstance(expected, dict) or not expected:
            return []
        equipment = evidence.get("post_observation", {}).get("equipment", {})
        checks = []
        for slot, item in expected.items():
            actual = equipment.get(slot)
            ok = actual == item or (isinstance(item, list) and actual in item)
            checks.append(ok)
            if ok:
                evidence_lines.append(f"equipment {slot} has {actual}")
            else:
                missing.append(f"equipment {slot} expected {item}, got {actual}")
        return checks

    def _check_flags(self, validator: dict, evidence: dict, evidence_lines: list[str], missing: list[str]) -> list[bool]:
        flags = validator.get("flag_present", [])
        if isinstance(flags, str):
            flags = [flags]
        if not flags:
            return []
        observed = set(str(flag) for flag in evidence.get("post_observation", {}).get("flags", []))
        checks = []
        for flag in flags:
            ok = str(flag) in observed
            checks.append(ok)
            if ok:
                evidence_lines.append(f"flag present: {flag}")
            else:
                missing.append(f"missing flag: {flag}")
        return checks

    def _check_nearby_blocks(self, validator: dict, evidence: dict, evidence_lines: list[str], missing: list[str]) -> list[bool]:
        expected = validator.get("nearby_block_present", [])
        if isinstance(expected, str):
            expected = [expected]
        if not expected:
            return []
        blocks = {
            self._name(block)
            for block in evidence.get("post_observation", {}).get("nearby_blocks", [])
            if self._name(block)
        }
        checks = []
        for name in expected:
            ok = str(name) in blocks
            checks.append(ok)
            if ok:
                evidence_lines.append(f"nearby block present: {name}")
            else:
                missing.append(f"nearby block not found: {name}")
        return checks

    def _check_nearby_entities_absent(self, validator: dict, evidence: dict, evidence_lines: list[str], missing: list[str]) -> list[bool]:
        expected_absent = validator.get("nearby_entity_absent", [])
        if isinstance(expected_absent, str):
            expected_absent = [expected_absent]
        if not expected_absent:
            return []
        entities = {
            self._entity_name(entity)
            for entity in evidence.get("post_observation", {}).get("nearby_entities", [])
            if self._entity_name(entity)
        }
        checks = []
        for name in expected_absent:
            ok = str(name) not in entities
            checks.append(ok)
            if ok:
                evidence_lines.append(f"nearby entity absent: {name}")
            else:
                missing.append(f"nearby entity still present: {name}")
        return checks

    def _check_recent_chat(self, validator: dict, evidence: dict, evidence_lines: list[str], missing: list[str]) -> list[bool]:
        expected = validator.get("recent_chat_contains", [])
        if isinstance(expected, str):
            expected = [expected]
        if not expected:
            return []
        chat_text = "\n".join(str(item) for item in evidence.get("recent_chat", [])).lower()
        checks = []
        for phrase in expected:
            ok = str(phrase).lower() in chat_text
            checks.append(ok)
            if ok:
                evidence_lines.append(f"recent chat contains: {phrase}")
            else:
                missing.append(f"recent chat missing: {phrase}")
        return checks

    def _check_action_success(self, validator: dict, evidence: dict, evidence_lines: list[str], missing: list[str]) -> list[bool]:
        expected = validator.get("action_success", [])
        if isinstance(expected, str):
            expected = [expected]
        if not expected:
            return []
        actions = evidence.get("actions", []) or []
        checks = []
        for action_type in expected:
            ok = any(
                self._event_action_type(event) == action_type and self._event_success(event)
                for event in actions
            )
            checks.append(ok)
            if ok:
                evidence_lines.append(f"successful action observed: {action_type}")
            else:
                missing.append(f"no successful action observed: {action_type}")
        return checks

    def _check_action_success_any(self, validator: dict, evidence: dict, evidence_lines: list[str], missing: list[str]) -> list[bool]:
        expected = validator.get("action_success_any", [])
        if isinstance(expected, str):
            expected = [expected]
        if not expected:
            return []
        actions = evidence.get("actions", []) or []
        observed = {
            self._event_action_type(event)
            for event in actions
            if self._event_success(event)
        }
        ok = any(action_type in observed for action_type in expected)
        if ok:
            matched = sorted(str(action_type) for action_type in expected if action_type in observed)
            evidence_lines.append(f"successful action observed: {matched[0]}")
        else:
            missing.append(f"no successful action observed from any of: {', '.join(str(item) for item in expected)}")
        return [ok]

    def _check_position_delta(self, validator: dict, evidence: dict, evidence_lines: list[str], missing: list[str]) -> list[bool]:
        required = validator.get("position_delta_at_least")
        if required in (None, ""):
            return []
        before = evidence.get("pre_observation", {}).get("position", {})
        after = evidence.get("post_observation", {}).get("position", {})
        distance = self._distance(before, after)
        required_float = self._safe_float(required, 0.0)
        ok = distance >= required_float
        if ok:
            evidence_lines.append(f"position changed {distance:.2f}/{required_float:.2f} blocks")
        else:
            missing.append(f"need position delta {required_float:.2f}, got {distance:.2f}")
        return [ok]

    def _inventory(self, observation: dict) -> Any:
        return observation.get("inventory", {}) if isinstance(observation, dict) else {}

    def _inventory_count(self, inventory: Any, item: str) -> int:
        if isinstance(inventory, dict):
            return self._safe_int(inventory.get(item, 0), 0)
        total = 0
        if isinstance(inventory, list):
            for entry in inventory:
                if isinstance(entry, dict) and entry.get("name") == item:
                    total += self._safe_int(entry.get("count", 1), 1)
        return total

    def _command_text(self, action: dict) -> str:
        params = action.get("parameters", {}) if isinstance(action, dict) else {}
        for key in ("command", "message", "chat"):
            value = params.get(key) if isinstance(params, dict) else None
            if isinstance(value, str) and value.strip().startswith("/"):
                return value.strip()
        if str(action.get("type", "")).lower() == "chat_command":
            return str(params.get("command", "")).strip()
        return ""

    def _scan_radius(self, action: dict) -> Optional[float]:
        params = action.get("parameters", {}) if isinstance(action, dict) else {}
        action_type = str(action.get("type", "")).lower()
        if "scan" not in action_type and "map" not in action_type:
            return None
        if not isinstance(params, dict) or "radius" not in params:
            return None
        return self._safe_float(params.get("radius"), 0.0)

    def _event_action_type(self, event: dict) -> str:
        action = event.get("action", event) if isinstance(event, dict) else {}
        return str(action.get("type", ""))

    def _event_success(self, event: dict) -> bool:
        result = event.get("result", {}) if isinstance(event, dict) else {}
        return bool(result.get("success", True))

    def _name(self, item: Any) -> str:
        if isinstance(item, dict):
            return str(item.get("name", item.get("type", "")))
        return str(item or "")

    def _entity_name(self, item: Any) -> str:
        if isinstance(item, dict):
            return str(item.get("type", item.get("name", "")))
        return str(item or "")

    def _distance(self, before: dict, after: dict) -> float:
        try:
            dx = float(after.get("x", 0)) - float(before.get("x", 0))
            dy = float(after.get("y", 0)) - float(before.get("y", 0))
            dz = float(after.get("z", 0)) - float(before.get("z", 0))
        except (TypeError, ValueError):
            return 0.0
        return math.sqrt(dx * dx + dy * dy + dz * dz)

    def _safe_int(self, value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _safe_float(self, value: Any, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default


def builtin_minenpc_templates() -> dict[str, MixedInitiativeTaskTemplate]:
    """Return a small, executable seed suite of MineNPC-style templates."""
    common_policy = {
        "forbid_admin_commands": True,
        "forbid_global_map_introspection": True,
        "max_scan_radius": 128,
    }
    collect_oak_logs = MixedInitiativeTaskTemplate(
        id="collect_oak_logs",
        name="Collect oak logs",
        category="resource_collection",
        goal_pattern="collect {count} oak logs",
        bounded_policy=common_policy,
        subtasks=[
            SubtaskTemplate(
                id="locate_oak_tree",
                name="locate oak tree",
                slots=[
                    SlotSpec(
                        "search_radius",
                        required=False,
                        default=100,
                        question="Are there known oak trees nearby, and within what radius?",
                        clarify_if_default=True,
                    )
                ],
                success_criterion="Find oak wood evidence within loaded chunks or a bounded search radius.",
                success_validator={"nearby_block_present": ["oak_log"]},
            ),
            SubtaskTemplate(
                id="harvest_oak_logs",
                name="harvest oak logs",
                dependencies=["locate_oak_tree"],
                slots=[
                    SlotSpec("count", required=True, default=20, question="How many oak logs should I collect?"),
                    SlotSpec("resource", required=False, default="oak_log"),
                ],
                preconditions={"nearby_block_present": ["oak_log"]},
                success_criterion="Inventory contains the requested oak log count.",
                success_validator={"inventory_at_least": {"oak_log": "$count"}},
            ),
            SubtaskTemplate(
                id="return_or_report",
                name="return or report completion",
                dependencies=["harvest_oak_logs"],
                slots=[
                    SlotSpec(
                        "dropoff_location",
                        required=False,
                        default="current_player_location",
                        question="Where should I bring the logs?",
                        clarify_if_default=False,
                    )
                ],
                success_criterion="Recent chat reports completion or the dropoff action succeeds.",
                success_validator={"recent_chat_contains": ["logs collected"]},
            ),
        ],
    )
    fetch_named_tool = MixedInitiativeTaskTemplate(
        id="fetch_named_tool",
        name="Fetch named pickaxe",
        category="navigation_retrieval",
        goal_pattern="fetch {tool_variant} pickaxe from {landmark}",
        bounded_policy=common_policy,
        subtasks=[
            SubtaskTemplate(
                id="resolve_landmark",
                name="resolve storage landmark",
                slots=[
                    SlotSpec("landmark", required=True, question="Which named landmark or container should I use?"),
                ],
                success_criterion="Known landmark is available in scoped memory or current context.",
                success_validator={"flag_present": ["landmark_resolved"]},
            ),
            SubtaskTemplate(
                id="select_pickaxe",
                name="select requested pickaxe",
                dependencies=["resolve_landmark"],
                slots=[
                    SlotSpec(
                        "tool_variant",
                        required=True,
                        question="Which pickaxe should I fetch: wooden, stone, iron, or diamond?",
                    ),
                ],
                success_criterion="Requested pickaxe appears in inventory or main hand.",
                success_validator={"inventory_at_least": {"$tool_variant_pickaxe": 1}},
            ),
            SubtaskTemplate(
                id="return_tool",
                name="return with tool",
                dependencies=["select_pickaxe"],
                slots=[SlotSpec("return_target", required=False, default="player")],
                success_criterion="Agent returns to player area after selecting the tool.",
                success_validator={"position_delta_at_least": 1},
            ),
        ],
    )
    craft_or_process_item = MixedInitiativeTaskTemplate(
        id="craft_or_process_item",
        name="Craft or process item",
        category="crafting_processing",
        goal_pattern="craft/process {count} {item}",
        bounded_policy=common_policy,
        subtasks=[
            SubtaskTemplate(
                id="produce_item",
                name="produce requested item",
                slots=[
                    SlotSpec("item", required=True, question="Which item should I craft or process?"),
                    SlotSpec("count", required=False, default=1),
                    SlotSpec("process_action", required=False, default="craft"),
                    SlotSpec("station", required=False, default="available_station"),
                ],
                success_criterion="Inventory contains the requested crafted or processed item count.",
                success_validator={"inventory_at_least": {"$item": "$count"}},
            ),
        ],
    )
    collect_or_mine_resource = MixedInitiativeTaskTemplate(
        id="collect_or_mine_resource",
        name="Collect or mine resource",
        category="resource_collection",
        goal_pattern="collect/mine {count} {resource}",
        bounded_policy=common_policy,
        subtasks=[
            SubtaskTemplate(
                id="locate_resource_source",
                name="locate resource source",
                slots=[
                    SlotSpec("source_block", required=True, question="Which block or source should I search for?"),
                    SlotSpec("search_radius", required=False, default=64),
                ],
                success_criterion="Find bounded local evidence of the resource source before mining or gathering.",
                success_validator={"nearby_block_present": ["$source_block"]},
            ),
            SubtaskTemplate(
                id="collect_resource",
                name="collect requested resource",
                dependencies=["locate_resource_source"],
                slots=[
                    SlotSpec("resource", required=True, question="Which resource should I collect?"),
                    SlotSpec("count", required=False, default=1),
                    SlotSpec("source_block", required=False),
                ],
                preconditions={"nearby_block_present": ["$source_block"]},
                success_criterion="Inventory contains the requested resource count.",
                success_validator={"inventory_at_least": {"$resource": "$count"}},
            ),
        ],
    )
    build_or_place_structure = MixedInitiativeTaskTemplate(
        id="build_or_place_structure",
        name="Build or place structure",
        category="construction_building",
        goal_pattern="build/place {structure}",
        bounded_policy=common_policy,
        subtasks=[
            SubtaskTemplate(
                id="place_or_build_structure",
                name="place or build requested structure",
                slots=[
                    SlotSpec("structure", required=True, question="What structure or object should I build or place?"),
                    SlotSpec("material", required=False, default="available_blocks"),
                    SlotSpec("location", required=False, default="current_player_location"),
                ],
                success_criterion="A bounded build/place action succeeds for the requested structure.",
                success_validator={"action_success_any": ["place", "place_block", "build"]},
            ),
        ],
    )
    unsupported_request = MixedInitiativeTaskTemplate(
        id="unsupported_request",
        name="Unsupported mixed-initiative request",
        category="template_gap",
        goal_pattern="{user_goal}",
        bounded_policy=common_policy,
        subtasks=[
            SubtaskTemplate(
                id="template_needed",
                name="define task template and validator",
                success_criterion="No validator is available yet; mine this request into a template before scoring it.",
                success_validator={},
            ),
        ],
    )
    return {
        collect_oak_logs.id: collect_oak_logs,
        fetch_named_tool.id: fetch_named_tool,
        craft_or_process_item.id: craft_or_process_item,
        collect_or_mine_resource.id: collect_or_mine_resource,
        build_or_place_structure.id: build_or_place_structure,
        unsupported_request.id: unsupported_request,
    }


def build_mixed_initiative_report(
    goal: str,
    template_id: str = "auto",
    context: Optional[dict] = None,
    evidence: Optional[dict] = None,
) -> dict:
    """Compile a goal and optionally validate each subtask against evidence."""
    compiler = MixedInitiativeTemplateCompiler()
    plan = compiler.compile_goal(goal, template_id=template_id, context=context or {})
    validator = BoundedEvidenceValidator(
        max_scan_radius=int(plan.bounded_policy.get("max_scan_radius", 128))
    )
    validation = []
    if evidence is not None:
        validation = [
            validator.validate_subtask(subtask, evidence).to_dict()
            for subtask in plan.subtasks
        ]
    return {
        "plan": plan.to_dict(),
        "validation": validation,
        "validation_summary": {
            "checked_subtasks": len(validation),
            "passed": sum(1 for result in validation if result["success"]),
            "failed": sum(1 for result in validation if result["status"] == "failed"),
            "invalid": sum(1 for result in validation if result["status"] == "invalid"),
            "unknown": sum(1 for result in validation if result["status"] == "unknown"),
        },
    }


def builtin_mixed_initiative_variant_cases() -> list[MixedInitiativeVariantCase]:
    """Held-out natural-language variants for template-selection regression checks."""
    return [
        MixedInitiativeVariantCase(
            id="collect_oak_logs_heldout",
            goal="Gather 12 oak logs within 20 blocks",
            expected_template_id="collect_oak_logs",
            expected_slots={"count": 12, "resource": "oak_log", "search_radius": 20},
            evidence={
                "post_observation": {
                    "inventory": {"oak_log": 12},
                    "nearby_blocks": [{"name": "oak_log"}],
                },
                "recent_chat": ["logs collected"],
            },
            tags=["resource_collection", "paraphrase"],
        ),
        MixedInitiativeVariantCase(
            id="fetch_pickaxe_heldout",
            goal="Bring me the iron pickaxe from weapon storage",
            expected_template_id="fetch_named_tool",
            expected_slots={"tool_variant": "iron", "landmark": "weapon_storage"},
            evidence={
                "pre_observation": {"position": {"x": 0, "y": 64, "z": 0}},
                "post_observation": {
                    "position": {"x": 3, "y": 64, "z": 0},
                    "flags": ["landmark_resolved"],
                    "inventory": {"iron_pickaxe": 1},
                },
            },
            tags=["navigation_retrieval", "paraphrase"],
        ),
        MixedInitiativeVariantCase(
            id="craft_torches_heldout",
            goal="Make 8 torches before night",
            expected_template_id="craft_or_process_item",
            expected_slots={"item": "torch", "count": 8, "process_action": "craft"},
            evidence={"post_observation": {"inventory": {"torch": 8}}},
            tags=["crafting_processing", "paraphrase"],
        ),
        MixedInitiativeVariantCase(
            id="smelt_ingots_heldout",
            goal="Smelt 2 iron ingots",
            expected_template_id="craft_or_process_item",
            expected_slots={
                "item": "iron_ingot",
                "count": 2,
                "process_action": "smelt",
                "station": "furnace",
            },
            evidence={"post_observation": {"inventory": {"iron_ingot": 2}}},
            tags=["crafting_processing", "processing"],
        ),
        MixedInitiativeVariantCase(
            id="mine_diamond_heldout",
            goal="Dig 2 diamond ore near camp",
            expected_template_id="collect_or_mine_resource",
            expected_slots={"resource": "diamond", "source_block": "diamond_ore", "count": 2},
            evidence={
                "post_observation": {
                    "inventory": {"diamond": 2},
                    "nearby_blocks": [{"name": "diamond_ore"}],
                },
            },
            tags=["resource_collection", "ore_drop"],
        ),
        MixedInitiativeVariantCase(
            id="place_wall_heldout",
            goal="Place a cobblestone wall at the base",
            expected_template_id="build_or_place_structure",
            expected_slots={"structure": "wall", "material": "cobblestone"},
            evidence={
                "actions": [
                    {
                        "action": {"type": "place_block", "parameters": {"block": "cobblestone"}},
                        "result": {"success": True},
                    }
                ]
            },
            tags=["construction_building", "place_action"],
        ),
        MixedInitiativeVariantCase(
            id="unsupported_inventory_heldout",
            goal="Organize inventory for later",
            expected_template_id="unsupported_request",
            expected_slots={},
            tags=["unsupported", "template_gap"],
        ),
    ]


def build_mixed_initiative_variant_report(
    cases: Optional[list[Any]] = None,
    case_paths: Optional[list[str]] = None,
    include_builtin: bool = True,
    template_id: str = "auto",
) -> MixedInitiativeVariantReport:
    """Replay held-out goal variants through template selection, slot binding, and validators."""
    compiler = MixedInitiativeTemplateCompiler()
    report = MixedInitiativeVariantReport()
    variant_cases: list[MixedInitiativeVariantCase] = []
    if include_builtin:
        variant_cases.extend(builtin_mixed_initiative_variant_cases())
    for index, item in enumerate(cases or [], start=1):
        try:
            variant_cases.append(_variant_case_from_any(item, source="inline", default_id=f"inline_{index}"))
        except Exception as exc:
            report.errors.append(f"inline case {index}: {exc}")
    for path in case_paths or []:
        try:
            loaded = _load_mixed_initiative_variant_cases(path)
            variant_cases.extend(loaded)
        except Exception as exc:
            report.errors.append(f"{path}: {exc}")

    for index, case in enumerate(variant_cases, start=1):
        if not case.id:
            case.id = f"case_{index}"
        if not case.goal:
            report.errors.append(f"{case.source}:{case.id}: missing goal")
            continue
        try:
            report.cases.append(_mixed_initiative_variant_result(case, compiler, template_id))
        except Exception as exc:
            report.errors.append(f"{case.source}:{case.id}: {exc}")
    return report


def _mixed_initiative_variant_result(
    case: MixedInitiativeVariantCase,
    compiler: MixedInitiativeTemplateCompiler,
    template_id: str,
) -> MixedInitiativeVariantResult:
    plan = compiler.compile_goal(case.goal, template_id=template_id, context=case.context or {})
    bound_slots = _bound_slots_from_plan(plan)
    template_match = (
        plan.template_id == case.expected_template_id
        if case.expected_template_id
        else True
    )
    slot_matches = {}
    slot_mismatches = []
    for slot, expected in (case.expected_slots or {}).items():
        actual = bound_slots.get(slot)
        ok = actual == expected
        slot_matches[slot] = ok
        if not ok:
            slot_mismatches.append(f"{slot}: expected {expected}, got {actual}")
    validation = []
    validation_checked = bool(case.evidence)
    validation_success: Optional[bool] = None
    if validation_checked:
        validator = BoundedEvidenceValidator(
            max_scan_radius=int(plan.bounded_policy.get("max_scan_radius", 128))
        )
        validation = [
            validator.validate_subtask(subtask, case.evidence).to_dict()
            for subtask in plan.subtasks
        ]
        validation_success = bool(validation) and all(result["success"] for result in validation)
    slot_match = not slot_mismatches
    fully_passed = (
        template_match
        and slot_match
        and not plan.needs_clarification
        and (validation_success is not False)
    )
    return MixedInitiativeVariantResult(
        id=case.id,
        source=case.source,
        goal=case.goal,
        tags=list(case.tags),
        expected_template_id=case.expected_template_id,
        actual_template_id=plan.template_id,
        template_match=template_match,
        expected_slots=dict(case.expected_slots or {}),
        bound_slots=bound_slots,
        slot_matches=slot_matches,
        slot_mismatches=slot_mismatches,
        slot_match=slot_match,
        needs_clarification=plan.needs_clarification,
        unbound_slot_count=plan.unbound_slot_count,
        plan_preview=plan.plan_preview,
        validation_checked=validation_checked,
        validation_success=validation_success,
        validation_passed_count=sum(1 for result in validation if result["success"]),
        validation_failed_count=sum(1 for result in validation if result["status"] == "failed"),
        validation_invalid_count=sum(1 for result in validation if result["status"] == "invalid"),
        validation_unknown_count=sum(1 for result in validation if result["status"] == "unknown"),
        policy_violation_count=sum(len(result.get("policy_violations", [])) for result in validation),
        fully_passed=fully_passed,
        plan=plan.to_dict(),
        validation=validation,
    )


def _bound_slots_from_plan(plan: MixedInitiativePlan) -> dict:
    slots = {}
    for subtask in plan.subtasks:
        for key, value in subtask.bound_parameters.items():
            if key not in slots or slots[key] in (None, ""):
                slots[key] = value
    return slots


def _load_mixed_initiative_variant_cases(path: str) -> list[MixedInitiativeVariantCase]:
    with open(path, "r", encoding="utf-8-sig") as f:
        text = f.read().strip()
    if not text:
        return []
    records = []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        for line_number, line in enumerate(text.splitlines(), start=1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"line {line_number}: invalid JSON: {exc}") from exc
    else:
        if isinstance(data, dict):
            data = data.get("cases", [data])
        if not isinstance(data, list):
            raise ValueError("variant file must contain a JSON object, JSON list, or JSONL records")
        records = data
    cases = []
    for index, item in enumerate(records, start=1):
        cases.append(_variant_case_from_any(item, source=path, default_id=f"case_{index}"))
    return cases


def _variant_case_from_any(item: Any, source: str, default_id: str) -> MixedInitiativeVariantCase:
    if isinstance(item, MixedInitiativeVariantCase):
        if not item.source:
            item.source = source
        if not item.id:
            item.id = default_id
        return item
    if isinstance(item, str):
        return MixedInitiativeVariantCase(id=default_id, goal=item, source=source)
    if not isinstance(item, dict):
        raise ValueError("variant case must be a string, object, or MixedInitiativeVariantCase")
    return MixedInitiativeVariantCase(
        id=str(item.get("id", default_id)),
        goal=str(item.get("goal", "")),
        expected_template_id=str(item.get("expected_template_id", item.get("template_id", ""))),
        expected_slots=dict(item.get("expected_slots", item.get("slots", {})) or {}),
        context=dict(item.get("context", {}) or {}),
        evidence=dict(item.get("evidence", {}) or {}),
        tags=list(item.get("tags", []) or []),
        source=str(item.get("source", source)),
    )


def build_mixed_initiative_review_queue(
    trace_reports: Optional[list[Any]] = None,
    trace_report_paths: Optional[list[str]] = None,
    session_log_paths: Optional[list[str]] = None,
    template_id: str = "auto",
) -> MixedInitiativeReviewQueueReport:
    """Aggregate trace recommendations into a stable mixed-initiative review queue."""
    queue = MixedInitiativeReviewQueueReport()
    payloads: list[tuple[str, dict]] = []
    for index, report in enumerate(trace_reports or [], start=1):
        try:
            payloads.append((f"inline_report_{index}", _trace_report_payload_from_any(report)))
        except Exception as exc:
            queue.errors.append(f"inline_report_{index}: {exc}")
    for path in trace_report_paths or []:
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                payloads.append((path, json.load(f)))
        except Exception as exc:
            queue.errors.append(f"{path}: {exc}")
    if session_log_paths:
        try:
            trace_report = build_mixed_initiative_trace_report(
                session_log_paths,
                template_id=template_id,
            )
            payloads.append(("session_logs", trace_report.to_dict()))
        except Exception as exc:
            queue.errors.append(f"session_logs: {exc}")

    grouped: dict[str, MixedInitiativeReviewQueueItem] = {}
    for source, payload in payloads:
        recommendations = payload.get("mixed_initiative_recommendations", [])
        if not isinstance(recommendations, list):
            queue.errors.append(f"{source}: mixed_initiative_recommendations is not a list")
            continue
        cases = payload.get("cases", []) if isinstance(payload.get("cases", []), list) else []
        for recommendation in recommendations:
            if not isinstance(recommendation, dict):
                continue
            incoming = _review_queue_item_from_recommendation(recommendation)
            existing = grouped.get(incoming.id)
            if existing is None:
                existing = _empty_review_queue_item(incoming)
                grouped[incoming.id] = existing
            _merge_review_queue_item(
                existing,
                incoming,
                source,
                _goals_for_recommendation(cases, recommendation),
                _logs_for_recommendation(cases, recommendation),
            )

    queue.items = sorted(
        grouped.values(),
        key=lambda item: (
            {"high": 0, "medium": 1, "low": 2}.get(item.priority, 3),
            item.target_type,
            item.target_id,
            item.decision,
        ),
    )
    return queue


def _trace_report_payload_from_any(report: Any) -> dict:
    if isinstance(report, MixedInitiativeTraceReport):
        return report.to_dict()
    if isinstance(report, dict):
        return report
    if hasattr(report, "to_dict"):
        payload = report.to_dict()
        if isinstance(payload, dict):
            return payload
    raise ValueError("trace report must be a dict or MixedInitiativeTraceReport")


def _review_queue_payload_from_any(queue: Any) -> dict:
    if isinstance(queue, MixedInitiativeReviewQueueReport):
        return queue.to_dict()
    if isinstance(queue, dict):
        return queue
    if hasattr(queue, "to_dict"):
        payload = queue.to_dict()
        if isinstance(payload, dict):
            return payload
    raise ValueError("review queue must be a dict or MixedInitiativeReviewQueueReport")


def _review_queue_item_from_recommendation(recommendation: dict) -> MixedInitiativeReviewQueueItem:
    target_type = str(recommendation.get("target_type") or "trace")
    target_id = str(recommendation.get("target_id") or "unknown")
    decision = str(recommendation.get("decision") or "review")
    priority = str(recommendation.get("priority") or "normal")
    review_id = _review_queue_id(target_type, target_id, decision)
    return MixedInitiativeReviewQueueItem(
        id=review_id,
        target_type=target_type,
        target_id=target_id,
        decision=decision,
        priority=priority,
        reason=str(recommendation.get("reason") or ""),
        active_policies=list(recommendation.get("active_policies", []) or []),
        action_items=_action_items_for_recommendation(recommendation),
        recommendations=[dict(recommendation)],
    )


def _empty_review_queue_item(item: MixedInitiativeReviewQueueItem) -> MixedInitiativeReviewQueueItem:
    return MixedInitiativeReviewQueueItem(
        id=item.id,
        target_type=item.target_type,
        target_id=item.target_id,
        decision=item.decision,
        priority=item.priority,
        reason=item.reason,
        action_items=[],
        active_policies=[],
        recommendations=[],
    )


def _merge_review_queue_item(
    existing: MixedInitiativeReviewQueueItem,
    incoming: MixedInitiativeReviewQueueItem,
    source: str,
    goals: list[str],
    logs: list[str],
):
    existing.priority = _higher_priority(existing.priority, incoming.priority)
    if source and source not in existing.source_reports:
        existing.source_reports.append(source)
    existing.recommendation_count += 1
    for policy in incoming.active_policies:
        if policy not in existing.active_policies:
            existing.active_policies.append(policy)
    existing.active_policies.sort()
    for action_item in incoming.action_items:
        if action_item not in existing.action_items:
            existing.action_items.append(action_item)
    for goal in goals:
        if goal and goal not in existing.source_goals:
            existing.source_goals.append(goal)
    existing.source_goals = existing.source_goals[:8]
    for log in logs:
        if log and log not in existing.source_logs:
            existing.source_logs.append(log)
    existing.source_logs = existing.source_logs[:8]
    existing.recommendations.extend(incoming.recommendations)


def _goals_for_recommendation(cases: list[dict], recommendation: dict) -> list[str]:
    return [
        str(case.get("goal"))
        for case in _matching_cases_for_recommendation(cases, recommendation)
        if case.get("goal")
    ]


def _logs_for_recommendation(cases: list[dict], recommendation: dict) -> list[str]:
    logs = []
    for case in _matching_cases_for_recommendation(cases, recommendation):
        source_log = str(case.get("source_log") or "")
        if source_log and source_log not in logs:
            logs.append(source_log)
    return logs


def _matching_cases_for_recommendation(cases: list[dict], recommendation: dict) -> list[dict]:
    target_type = str(recommendation.get("target_type") or "")
    target_id = str(recommendation.get("target_id") or "")
    matches_cases = []
    for case in cases:
        if not isinstance(case, dict):
            continue
        matches = False
        if target_type == "template":
            matches = str(case.get("template_id") or "") == target_id
        elif target_type == "template_candidate":
            candidate = case.get("template_candidate", {})
            matches = isinstance(candidate, dict) and str(candidate.get("candidate_id") or "") == target_id
        else:
            matches = True
        if matches:
            matches_cases.append(case)
    return matches_cases


def _action_items_for_recommendation(recommendation: dict) -> list[str]:
    decision = str(recommendation.get("decision") or "")
    if decision == "block_invalid_progress":
        return ["Review bounded-policy violations before counting these actions as progress."]
    if decision == "inspect_backend_execution":
        return ["Inspect failed action parameters, missing preconditions, and backend command results."]
    if decision == "tune_action_policy":
        return ["Run action-policy or visual-action ablations for this template family."]
    if decision == "audit_template_validator":
        return ["Compare template validator evidence against GoalVerifier and session observations."]
    if decision == "promote_template_candidate":
        return ["Draft or update a MixedInitiativeTaskTemplate with explicit slots and validators."]
    if decision == "candidate_review":
        return ["Review unsupported goal examples before promoting a template candidate."]
    return ["Review mixed-initiative trace evidence for this target."]


def _review_queue_id(target_type: str, target_id: str, decision: str) -> str:
    return "miq-" + _slugify_id(f"{target_type}-{target_id}-{decision}")


def _slugify_id(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return slug or "unknown"


def _higher_priority(left: str, right: str) -> str:
    rank = {"high": 0, "medium": 1, "low": 2, "normal": 3}
    return left if rank.get(left, 3) <= rank.get(right, 3) else right


def build_mixed_initiative_review_experiment_plan(
    review_queue: Optional[Any] = None,
    review_queue_paths: Optional[list[str]] = None,
    trace_reports: Optional[list[Any]] = None,
    trace_report_paths: Optional[list[str]] = None,
    session_log_paths: Optional[list[str]] = None,
    template_id: str = "auto",
) -> MixedInitiativeReviewExperimentPlan:
    """Route review queue items into concrete follow-up experiment cases."""
    plan = MixedInitiativeReviewExperimentPlan()
    payloads: list[tuple[str, dict]] = []
    if review_queue is not None:
        try:
            payloads.append(("inline_review_queue", _review_queue_payload_from_any(review_queue)))
        except Exception as exc:
            plan.errors.append(f"inline_review_queue: {exc}")
    for path in review_queue_paths or []:
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                payloads.append((path, json.load(f)))
        except Exception as exc:
            plan.errors.append(f"{path}: {exc}")
    if trace_reports or trace_report_paths or session_log_paths:
        queue = build_mixed_initiative_review_queue(
            trace_reports=trace_reports,
            trace_report_paths=trace_report_paths,
            session_log_paths=session_log_paths,
            template_id=template_id,
        )
        plan.errors.extend(queue.errors)
        payloads.append(("derived_review_queue", queue.to_dict()))

    cases_by_id: dict[str, MixedInitiativeReviewExperimentCase] = {}
    for source, payload in payloads:
        for error in _string_list(payload.get("errors", [])):
            plan.errors.append(f"{source}: {error}")
        items = payload.get("items", [])
        if not isinstance(items, list):
            plan.errors.append(f"{source}: items is not a list")
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            case = _experiment_case_from_review_queue_item(item)
            if case.id not in cases_by_id:
                cases_by_id[case.id] = case
            else:
                _merge_experiment_case(cases_by_id[case.id], case)

    plan.cases = sorted(
        cases_by_id.values(),
        key=lambda case: (
            {"high": 0, "medium": 1, "low": 2, "normal": 3}.get(case.priority, 3),
            case.route,
            case.target_type,
            case.target_id,
        ),
    )
    return plan


def build_mixed_initiative_review_label_templates(
    review_plan: Optional[Any] = None,
    review_plan_paths: Optional[list[str]] = None,
    review_queue: Optional[Any] = None,
    review_queue_paths: Optional[list[str]] = None,
    trace_reports: Optional[list[Any]] = None,
    trace_report_paths: Optional[list[str]] = None,
    session_log_paths: Optional[list[str]] = None,
    template_id: str = "auto",
) -> list[dict]:
    """Create JSONL-ready operator labels for mixed-initiative review cases."""
    plan = _review_experiment_plan_from_inputs(
        review_plan=review_plan,
        review_plan_paths=review_plan_paths,
        review_queue=review_queue,
        review_queue_paths=review_queue_paths,
        trace_reports=trace_reports,
        trace_report_paths=trace_report_paths,
        session_log_paths=session_log_paths,
        template_id=template_id,
    )
    templates = []
    for case in plan.cases:
        templates.append({
            "type": "mixed_initiative_review",
            "key": case.id,
            "case_id": case.id,
            "queue_item_id": case.queue_item_id,
            "route": case.route,
            "priority": case.priority,
            "target_type": case.target_type,
            "target_id": case.target_id,
            "decision": case.decision,
            "readiness": "unknown",
            "reviewer": "",
            "notes": "",
            "source_logs": list(case.source_logs),
            "source_goals": list(case.source_goals),
            "hypothesis": case.hypothesis,
            "action_items": list(case.action_items),
            "recommended_commands": list(case.recommended_commands),
            "success_metrics": list(case.success_metrics),
        })
    return templates


def validate_mixed_initiative_review_labels(
    label_path: str,
    review_plan: Optional[Any] = None,
    review_plan_paths: Optional[list[str]] = None,
) -> MixedInitiativeReviewApprovalReport:
    """Validate filled operator labels before review cases are executable."""
    report = MixedInitiativeReviewApprovalReport(label_path=label_path)
    try:
        records = _load_json_records(label_path)
    except Exception as exc:
        report.errors.append(str(exc))
        return report

    plan_index = {}
    if review_plan is not None or review_plan_paths:
        try:
            plan = _review_experiment_plan_from_inputs(
                review_plan=review_plan,
                review_plan_paths=review_plan_paths,
            )
            plan_index = _review_plan_case_index(plan)
        except Exception as exc:
            report.errors.append(f"review_plan: {exc}")

    for index, record in enumerate(records, start=1):
        if not isinstance(record, dict):
            report.cases.append(MixedInitiativeReviewApprovalCase(
                index=index,
                errors=["record_not_object"],
            ))
            continue
        report.cases.append(_validate_mixed_review_label_record(record, index, plan_index))
    return report


def execute_mixed_initiative_review_labels(
    label_path: str,
    review_plan: Optional[Any] = None,
    review_plan_paths: Optional[list[str]] = None,
    output_dir: str = "",
    dry_run: bool = False,
) -> MixedInitiativeReviewExecutionReport:
    """Execute approved mixed-initiative review labels through whitelisted report builders."""
    approval = validate_mixed_initiative_review_labels(
        label_path,
        review_plan=review_plan,
        review_plan_paths=review_plan_paths,
    )
    report = MixedInitiativeReviewExecutionReport(
        approval=approval,
        dry_run=dry_run,
        output_dir=output_dir,
    )
    if not approval.ok:
        report.errors.append("approval labels failed validation")
        return report
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    for approved_case in approval.cases:
        execution = MixedInitiativeReviewExecutionCase(
            case_id=approved_case.case_id,
            route=approved_case.route,
            target_id=approved_case.target_id,
            readiness=approved_case.readiness,
            approved=approved_case.approved,
            executable=approved_case.executable,
            dry_run=dry_run,
            source_logs=list(approved_case.source_logs),
            recommended_commands=list(approved_case.recommended_commands),
        )
        report.cases.append(execution)
        if not approved_case.approved:
            execution.status = "skipped"
            continue
        if not approved_case.executable:
            execution.status = "failed"
            execution.errors.append("approved case is not executable")
            continue
        if dry_run:
            execution.status = "dry_run"
            execution.artifact_summaries = _review_execution_dry_run_summary(approved_case)
            continue
        try:
            artifact = _execute_mixed_review_case(approved_case)
            execution.status = "executed"
            execution.artifact_summaries = _review_execution_summary(approved_case.route, artifact)
            if output_dir:
                artifact_path = os.path.join(
                    output_dir,
                    f"{_slugify_id(approved_case.case_id or approved_case.target_id or approved_case.route)}.json",
                )
                _write_json_artifact(artifact_path, artifact)
                execution.artifact_paths.append(artifact_path)
        except Exception as exc:
            execution.status = "failed"
            execution.errors.append(str(exc))
    return report


def _execute_mixed_review_case(case: MixedInitiativeReviewApprovalCase) -> dict:
    route = case.route
    if route == "template_approval":
        return {
            "route": route,
            "target_id": case.target_id,
            "variant_report": build_mixed_initiative_variant_report().to_dict(),
        }
    if route == "backend_inspection":
        _require_source_logs(case)
        return {
            "route": route,
            "target_id": case.target_id,
            "trace_report": build_mixed_initiative_trace_report(case.source_logs).to_dict(),
        }
    if route == "validator_audit":
        _require_source_logs(case)
        return {
            "route": route,
            "target_id": case.target_id,
            "trace_report": build_mixed_initiative_trace_report(case.source_logs).to_dict(),
            "variant_report": build_mixed_initiative_variant_report().to_dict(),
        }
    if route == "action_policy_ablation":
        _require_source_logs(case)
        return _execute_action_policy_review(case)
    if route == "mixed_trace_review":
        _require_source_logs(case)
        return {
            "route": route,
            "target_id": case.target_id,
            "trace_report": build_mixed_initiative_trace_report(case.source_logs).to_dict(),
        }
    raise ValueError(f"unsupported review execution route: {route}")


def _execute_action_policy_review(case: MixedInitiativeReviewApprovalCase) -> dict:
    from singularity.core.config import Config
    from singularity.evaluation.benchmark_runner import BenchmarkRunner

    runner = BenchmarkRunner(Config())
    action_report = runner.run_action_abstraction_report_from_logs(case.source_logs)
    action_feedback = runner.action_abstraction_feedback(action_report)
    visual_report = runner.run_visual_action_ablation_from_logs(case.source_logs)
    return {
        "route": case.route,
        "target_id": case.target_id,
        "action_abstraction": {
            "log_count": action_report.log_count,
            "action_count": action_report.action_count,
            "failed_action_count": action_report.failed_action_count,
            "unknown_canonical_count": action_report.unknown_canonical_count,
            "failed_mapping_count": action_report.failed_mapping_count,
            "desktop_planned_count": action_report.desktop_planned_count,
            "low_level_candidate_count": action_report.low_level_candidate_count,
            "action_abstraction_feedback": action_feedback,
            "errors": list(action_report.errors),
            "cases": [asdict(item) for item in action_report.cases],
        },
        "visual_action_ablation": {
            "case_count": len(visual_report.cases),
            "passed_count": visual_report.passed_count,
            "changed_count": visual_report.changed_count,
            "helped_count": visual_report.helped_count,
            "cases": [asdict(item) for item in visual_report.cases],
        },
    }


def _require_source_logs(case: MixedInitiativeReviewApprovalCase):
    if not case.source_logs:
        raise ValueError("approved case requires source session logs")


def _review_execution_dry_run_summary(case: MixedInitiativeReviewApprovalCase) -> dict:
    return {
        "route": case.route,
        "target_id": case.target_id,
        "source_log_count": len(case.source_logs),
        "recommended_command_count": len(case.recommended_commands),
        "success_metrics": list(case.success_metrics),
    }


def _review_execution_summary(route: str, artifact: dict) -> dict:
    if route == "template_approval":
        variant = artifact.get("variant_report", {})
        return {
            "variant_case_count": variant.get("case_count", 0),
            "fully_passed_count": variant.get("fully_passed_count", 0),
            "slot_mismatch_count": variant.get("slot_mismatch_count", 0),
        }
    if route == "backend_inspection":
        trace = artifact.get("trace_report", {})
        return {
            "goal_count": trace.get("goal_count", 0),
            "failed_action_count": trace.get("failed_action_count", 0),
            "valid_successful_action_count": trace.get("valid_successful_action_count", 0),
            "recommendation_count": len(trace.get("mixed_initiative_recommendations", []) or []),
        }
    if route == "validator_audit":
        trace = artifact.get("trace_report", {})
        variant = artifact.get("variant_report", {})
        return {
            "agreement_counts": trace.get("agreement_counts", {}),
            "policy_violation_count": trace.get("policy_violation_count", 0),
            "variant_validation_success_count": variant.get("validation_success_count", 0),
        }
    if route == "action_policy_ablation":
        action = artifact.get("action_abstraction", {})
        visual = artifact.get("visual_action_ablation", {})
        return {
            "action_count": action.get("action_count", 0),
            "low_level_candidate_count": action.get("low_level_candidate_count", 0),
            "visual_action_helped_count": visual.get("helped_count", 0),
        }
    trace = artifact.get("trace_report", {})
    return {
        "goal_count": trace.get("goal_count", 0),
        "recommendation_count": len(trace.get("mixed_initiative_recommendations", []) or []),
    }


def _write_json_artifact(path: str, payload: dict):
    output_dir = os.path.dirname(path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def _review_experiment_plan_from_inputs(
    review_plan: Optional[Any] = None,
    review_plan_paths: Optional[list[str]] = None,
    review_queue: Optional[Any] = None,
    review_queue_paths: Optional[list[str]] = None,
    trace_reports: Optional[list[Any]] = None,
    trace_report_paths: Optional[list[str]] = None,
    session_log_paths: Optional[list[str]] = None,
    template_id: str = "auto",
) -> MixedInitiativeReviewExperimentPlan:
    plan = MixedInitiativeReviewExperimentPlan()
    for source, payload in _review_plan_payloads(review_plan, review_plan_paths):
        cases = payload.get("cases", [])
        if not isinstance(cases, list):
            plan.errors.append(f"{source}: cases is not a list")
            continue
        for case in cases:
            if isinstance(case, dict):
                plan.cases.append(_experiment_case_from_plan_payload(case))
        for error in _string_list(payload.get("errors", [])):
            plan.errors.append(f"{source}: {error}")
    if plan.cases or plan.errors:
        return plan
    return build_mixed_initiative_review_experiment_plan(
        review_queue=review_queue,
        review_queue_paths=review_queue_paths,
        trace_reports=trace_reports,
        trace_report_paths=trace_report_paths,
        session_log_paths=session_log_paths,
        template_id=template_id,
    )


def _review_plan_payloads(review_plan: Optional[Any], review_plan_paths: Optional[list[str]]) -> list[tuple[str, dict]]:
    payloads = []
    if review_plan is not None:
        payloads.append(("inline_review_plan", _review_plan_payload_from_any(review_plan)))
    for path in review_plan_paths or []:
        with open(path, "r", encoding="utf-8-sig") as f:
            payloads.append((path, json.load(f)))
    return payloads


def _review_plan_payload_from_any(plan: Any) -> dict:
    if isinstance(plan, MixedInitiativeReviewExperimentPlan):
        return plan.to_dict()
    if isinstance(plan, dict):
        return plan
    if hasattr(plan, "to_dict"):
        payload = plan.to_dict()
        if isinstance(payload, dict):
            return payload
    raise ValueError("review plan must be a dict or MixedInitiativeReviewExperimentPlan")


def _experiment_case_from_plan_payload(payload: dict) -> MixedInitiativeReviewExperimentCase:
    case_id = str(payload.get("id") or payload.get("case_id") or payload.get("key") or "")
    queue_item_id = str(payload.get("queue_item_id") or "")
    if not case_id:
        case_id = "mixexp-" + _slugify_id(queue_item_id or payload.get("target_id") or "unknown")
    route = str(payload.get("route") or _review_experiment_route(
        str(payload.get("decision") or ""),
        str(payload.get("target_type") or ""),
    ))
    missing_inputs = _review_experiment_missing_inputs(
        route,
        _string_list(payload.get("source_logs", [])),
        _string_list(payload.get("source_goals", [])),
    )
    return MixedInitiativeReviewExperimentCase(
        id=case_id,
        queue_item_id=queue_item_id,
        route=route,
        priority=str(payload.get("priority") or "normal"),
        target_type=str(payload.get("target_type") or ""),
        target_id=str(payload.get("target_id") or ""),
        decision=str(payload.get("decision") or ""),
        ready=not missing_inputs,
        status="ready" if not missing_inputs else "needs_input",
        missing_inputs=missing_inputs,
        hypothesis=str(payload.get("hypothesis") or ""),
        source_reports=_string_list(payload.get("source_reports", [])),
        source_logs=_string_list(payload.get("source_logs", [])),
        source_goals=_string_list(payload.get("source_goals", [])),
        action_items=_string_list(payload.get("action_items", [])),
        recommended_commands=_string_list(payload.get("recommended_commands", [])),
        success_metrics=_string_list(payload.get("success_metrics", [])),
    )


def _review_plan_case_index(plan: MixedInitiativeReviewExperimentPlan) -> dict[str, MixedInitiativeReviewExperimentCase]:
    index = {}
    for case in plan.cases:
        for key in _review_approval_match_keys(
            case.id,
            case.queue_item_id,
            case.target_id,
            case.route,
        ):
            index[_label_key(key)] = case
    return index


def _review_approval_match_keys(case_id: str = "", queue_item_id: str = "", target_id: str = "", route: str = "") -> list[str]:
    values = [case_id, queue_item_id, target_id]
    if route and target_id:
        values.append(f"{route}:{target_id}")
    return [str(value) for value in values if value]


def _validate_mixed_review_label_record(
    record: dict,
    index: int,
    plan_index: dict[str, MixedInitiativeReviewExperimentCase],
) -> MixedInitiativeReviewApprovalCase:
    raw_readiness = str(record.get("readiness", record.get("label", record.get("status", record.get("decision", "")))) or "")
    readiness = _normalize_review_readiness(raw_readiness)
    case_id = str(record.get("case_id") or record.get("id") or record.get("key") or "")
    queue_item_id = str(record.get("queue_item_id") or "")
    route = str(record.get("route") or "")
    target_id = str(record.get("target_id") or "")
    matched = _matched_review_plan_case(plan_index, case_id, queue_item_id, target_id, route)

    source = matched if matched is not None else None
    case = MixedInitiativeReviewApprovalCase(
        index=index,
        key=str(record.get("key") or case_id or queue_item_id or ""),
        case_id=case_id or (source.id if source else ""),
        queue_item_id=queue_item_id or (source.queue_item_id if source else ""),
        route=route or (source.route if source else ""),
        target_type=str(record.get("target_type") or (source.target_type if source else "")),
        target_id=target_id or (source.target_id if source else ""),
        decision=str(record.get("review_decision") or record.get("recommendation_decision") or (source.decision if source else "")),
        raw_readiness=raw_readiness,
        readiness=readiness,
        reviewer=str(record.get("reviewer") or record.get("source") or "manual"),
        notes=str(record.get("notes") or record.get("reason") or ""),
        source_logs=_string_list(record.get("source_logs", [])) or (list(source.source_logs) if source else []),
        source_goals=_string_list(record.get("source_goals", [])) or (list(source.source_goals) if source else []),
        recommended_commands=_string_list(record.get("recommended_commands", [])) or (list(source.recommended_commands) if source else []),
        success_metrics=_string_list(record.get("success_metrics", [])) or (list(source.success_metrics) if source else []),
    )

    record_type = str(record.get("type") or "").strip().lower()
    if record_type and record_type not in {"mixed_initiative_review", "mixed_review", "mixed_initiative"}:
        case.errors.append("unexpected_label_type")
    if not (case.case_id or case.queue_item_id or case.target_id):
        case.errors.append("missing_match_key")
    if plan_index and matched is None:
        case.errors.append("review_case_not_found")
    if not readiness:
        case.errors.append("invalid_readiness")
    elif readiness == "unknown":
        case.warnings.append("readiness_still_unknown")
    if readiness == "approved" and not case.notes:
        case.warnings.append("approved_without_notes")
    if readiness == "approved" and case.route in {"backend_inspection", "validator_audit", "action_policy_ablation"} and not case.source_logs:
        case.errors.append("approved_case_missing_source_logs")
    if readiness == "approved" and not case.recommended_commands:
        case.warnings.append("approved_case_has_no_command")

    case.ok = not case.errors
    return case


def _matched_review_plan_case(
    plan_index: dict[str, MixedInitiativeReviewExperimentCase],
    case_id: str = "",
    queue_item_id: str = "",
    target_id: str = "",
    route: str = "",
) -> Optional[MixedInitiativeReviewExperimentCase]:
    for key in _review_approval_match_keys(case_id, queue_item_id, target_id, route):
        matched = plan_index.get(_label_key(key))
        if matched:
            return matched
    return None


def _normalize_review_readiness(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"approved", "approve", "accepted", "accept", "ready", "yes", "true", "pass", "passed"}:
        return "approved"
    if text in {"rejected", "reject", "declined", "no", "false", "fail", "failed"}:
        return "rejected"
    if text in {"unknown", "pending", "needs_review", "review", ""}:
        return "unknown" if text else ""
    return ""


def _load_json_records(path: str) -> list[dict]:
    with open(path, "r", encoding="utf-8-sig") as f:
        if path.lower().endswith(".jsonl"):
            return [json.loads(line) for line in f if line.strip()]
        payload = json.load(f)
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("labels"), list):
        return payload["labels"]
    if isinstance(payload, dict) and isinstance(payload.get("cases"), list):
        return payload["cases"]
    if isinstance(payload, dict):
        return [
            {**(value if isinstance(value, dict) else {"readiness": value}), "key": key}
            for key, value in payload.items()
        ]
    return []


def _experiment_case_from_review_queue_item(item: dict) -> MixedInitiativeReviewExperimentCase:
    queue_item_id = str(item.get("id") or _review_queue_id(
        str(item.get("target_type") or "trace"),
        str(item.get("target_id") or "unknown"),
        str(item.get("decision") or "review"),
    ))
    decision = str(item.get("decision") or "review")
    target_type = str(item.get("target_type") or "trace")
    target_id = str(item.get("target_id") or "unknown")
    route = _review_experiment_route(decision, target_type)
    source_logs = _string_list(item.get("source_logs", []))
    source_goals = _string_list(item.get("source_goals", []))
    source_reports = _string_list(item.get("source_reports", []))
    missing_inputs = _review_experiment_missing_inputs(route, source_logs, source_goals)
    return MixedInitiativeReviewExperimentCase(
        id="mixexp-" + _slugify_id(queue_item_id),
        queue_item_id=queue_item_id,
        route=route,
        priority=str(item.get("priority") or "normal"),
        target_type=target_type,
        target_id=target_id,
        decision=decision,
        ready=not missing_inputs,
        status="ready" if not missing_inputs else "needs_input",
        missing_inputs=missing_inputs,
        hypothesis=_review_experiment_hypothesis(route, target_type, target_id, decision),
        source_reports=source_reports,
        source_logs=source_logs,
        source_goals=source_goals,
        action_items=_string_list(item.get("action_items", [])),
        recommended_commands=_review_experiment_commands(route, source_logs),
        success_metrics=_review_experiment_metrics(route),
    )


def _merge_experiment_case(existing: MixedInitiativeReviewExperimentCase, incoming: MixedInitiativeReviewExperimentCase):
    existing.priority = _higher_priority(existing.priority, incoming.priority)
    for attr in ("source_reports", "source_logs", "source_goals", "action_items", "recommended_commands", "success_metrics"):
        values = getattr(existing, attr)
        for value in getattr(incoming, attr):
            if value not in values:
                values.append(value)
    existing.missing_inputs = _review_experiment_missing_inputs(existing.route, existing.source_logs, existing.source_goals)
    existing.ready = not existing.missing_inputs
    existing.status = "ready" if existing.ready else "needs_input"


def _review_experiment_route(decision: str, target_type: str) -> str:
    if decision in {"promote_template_candidate", "candidate_review"} or target_type == "template_candidate":
        return "template_approval"
    if decision == "tune_action_policy":
        return "action_policy_ablation"
    if decision == "inspect_backend_execution":
        return "backend_inspection"
    if decision in {"audit_template_validator", "block_invalid_progress"}:
        return "validator_audit"
    return "mixed_trace_review"


def _review_experiment_missing_inputs(route: str, source_logs: list[str], source_goals: list[str]) -> list[str]:
    missing = []
    if route in {"action_policy_ablation", "backend_inspection", "validator_audit"} and not source_logs:
        missing.append("source_session_log")
    if route == "template_approval" and not source_goals:
        missing.append("source_goal_examples")
    return missing


def _review_experiment_hypothesis(route: str, target_type: str, target_id: str, decision: str) -> str:
    if route == "template_approval":
        return f"Promoting or refining {target_id} should reduce unsupported mixed-initiative requests."
    if route == "action_policy_ablation":
        return f"Changing action policy for {target_id} should improve valid-success rate without increasing invalid actions."
    if route == "backend_inspection":
        return f"Inspecting backend execution for {target_id} should identify missing preconditions or command mapping gaps."
    if route == "validator_audit":
        return f"Auditing {target_id} should align bounded validators with accepted GoalVerifier evidence."
    return f"Review {target_type}:{target_id} because the feedback policy emitted {decision}."


def _review_experiment_commands(route: str, source_logs: list[str]) -> list[str]:
    log_args = _session_log_args(source_logs)
    if route == "template_approval":
        return [
            "python -m singularity.main mixed-initiative-variant-report --case-file workspace/evals/mixed_variants.jsonl --output logs/benchmarks/mixed_initiative_variants.json"
        ]
    if route == "action_policy_ablation":
        return [
            f"python -m singularity.main action-abstraction-report {log_args} --output logs/benchmarks/action_abstraction_review.json",
            f"python -m singularity.main visual-action-ablation {log_args} --output logs/benchmarks/visual_action_review.json",
        ]
    if route == "backend_inspection":
        return [
            f"python -m singularity.main mixed-initiative-trace-report {log_args} --output logs/benchmarks/mixed_initiative_trace.json"
        ]
    if route == "validator_audit":
        return [
            f"python -m singularity.main mixed-initiative-trace-report {log_args} --output logs/benchmarks/mixed_initiative_trace.json",
            "python -m singularity.main mixed-initiative-variant-report --output logs/benchmarks/mixed_initiative_variants.json",
        ]
    return [
        f"python -m singularity.main mixed-initiative-trace-report {log_args} --output logs/benchmarks/mixed_initiative_trace.json"
    ]


def _review_experiment_metrics(route: str) -> list[str]:
    if route == "template_approval":
        return ["template_match_count", "slot_mismatch_count", "validation_success_count", "unsupported_template_count"]
    if route == "action_policy_ablation":
        return ["valid_successful_action_count", "invalid_action_count", "visual_action_helped_count"]
    if route == "backend_inspection":
        return ["failed_action_count", "valid_successful_action_count", "backend_error_categories"]
    if route == "validator_audit":
        return ["agreement_counts", "policy_violation_count", "validator_success_count"]
    return ["mixed_initiative_recommendation_count"]


def _session_log_args(source_logs: list[str]) -> str:
    if not source_logs:
        return "--session-log logs/session_xxx.jsonl"
    return " ".join(f"--session-log {_quote_cli_arg(path)}" for path in source_logs[:3])


def _quote_cli_arg(value: str) -> str:
    text = str(value)
    if not text or re.search(r"\s", text):
        return '"' + text.replace('"', '\\"') + '"'
    return text


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item is not None and str(item)]


def _label_key(value: str) -> str:
    return str(value or "").strip().lower()


def build_mixed_initiative_trace_report(
    session_log_paths: list[str],
    template_id: str = "auto",
) -> MixedInitiativeTraceReport:
    """Replay session JSONL logs through MineNPC-style template validators."""
    compiler = MixedInitiativeTemplateCompiler()
    report = MixedInitiativeTraceReport()
    for path in session_log_paths:
        try:
            events = _load_session_events(path)
        except Exception as exc:
            report.errors.append(f"{path}: {exc}")
            continue
        segments = _goal_segments(events)
        if not segments:
            report.errors.append(f"{path}: no goal_start/goal_end segments found")
            continue
        for goal, segment in segments:
            if not goal:
                report.errors.append(f"{path}: skipped segment with missing goal")
                continue
            try:
                case = _mixed_initiative_trace_case(path, goal, segment, compiler, template_id)
                report.cases.append(case)
            except Exception as exc:
                report.errors.append(f"{path}: {goal}: {exc}")
    return report


def _mixed_initiative_trace_case(
    source_log: str,
    goal: str,
    events: list[dict],
    compiler: MixedInitiativeTemplateCompiler,
    template_id: str,
) -> MixedInitiativeTraceCase:
    context = _trace_context(events)
    plan = compiler.compile_goal(goal, template_id=template_id, context=context)
    evidence = _bounded_evidence_from_events(events)
    validator = BoundedEvidenceValidator(
        max_scan_radius=int(plan.bounded_policy.get("max_scan_radius", 128))
    )
    validation = [
        validator.validate_subtask(subtask, evidence).to_dict()
        for subtask in plan.subtasks
    ]
    goal_verification = _latest_goal_verification(events)
    validation_passed = sum(1 for result in validation if result["success"])
    validation_failed = sum(1 for result in validation if result["status"] == "failed")
    validation_invalid = sum(1 for result in validation if result["status"] == "invalid")
    validation_unknown = sum(1 for result in validation if result["status"] == "unknown")
    policy_violations = sum(len(result.get("policy_violations", [])) for result in validation)
    validator_success = bool(validation) and all(result["success"] for result in validation)
    action_validity = _action_validity_summary(evidence, validator)

    return MixedInitiativeTraceCase(
        source_log=source_log,
        goal=goal,
        event_count=len(events),
        observation_count=sum(1 for event in events if event.get("type") == "observation"),
        action_count=sum(1 for event in events if event.get("type") == "action"),
        valid_action_count=action_validity["valid_action_count"],
        invalid_action_count=action_validity["invalid_action_count"],
        successful_action_count=action_validity["successful_action_count"],
        failed_action_count=action_validity["failed_action_count"],
        valid_successful_action_count=action_validity["valid_successful_action_count"],
        action_type_counts=action_validity["action_type_counts"],
        successful_action_type_counts=action_validity["successful_action_type_counts"],
        template_id=plan.template_id,
        template_name=plan.template_name,
        category=plan.category,
        unsupported_template=plan.template_id == "unsupported_request",
        plan_preview=plan.plan_preview,
        subtask_count=len(plan.subtasks),
        needs_clarification=plan.needs_clarification,
        unbound_slot_count=plan.unbound_slot_count,
        clarifying_questions=list(plan.clarifying_questions),
        suppressed_questions=list(plan.suppressed_questions),
        memory_write_candidate_count=len(plan.memory_write_candidates),
        validation_passed_count=validation_passed,
        validation_failed_count=validation_failed,
        validation_invalid_count=validation_invalid,
        validation_unknown_count=validation_unknown,
        policy_violation_count=policy_violations,
        goal_verification_status=goal_verification.get("status", ""),
        goal_verification_achieved=goal_verification.get("achieved"),
        goal_verification_accepted=_goal_verification_accepted(goal_verification),
        validator_success=validator_success,
        agreement=_validator_goal_agreement(validator_success, validation_invalid > 0, goal_verification),
        template_candidate=_template_candidate_for_goal(goal) if plan.template_id == "unsupported_request" else {},
        plan=plan.to_dict(),
        validation=validation,
        evidence_summary=_evidence_summary(evidence),
    )


def _action_validity_summary(evidence: dict, validator: BoundedEvidenceValidator) -> dict:
    actions = evidence.get("actions", []) or []
    if isinstance(actions, dict):
        actions = [actions]
    policy_violations = validator.check_bounded_policy(evidence)
    invalid_indices = {
        violation.action_index
        for violation in policy_violations
        if violation.action_index is not None
    }
    action_type_counts = {}
    successful_action_type_counts = {}
    successful_count = 0
    failed_count = 0
    valid_successful_count = 0
    invalid_count = 0
    for index, event in enumerate(actions):
        action_type = validator._event_action_type(event) or "unknown"
        action_type_counts[action_type] = action_type_counts.get(action_type, 0) + 1
        success = validator._event_success(event)
        invalid = index in invalid_indices
        if invalid:
            invalid_count += 1
        if success:
            successful_count += 1
            successful_action_type_counts[action_type] = successful_action_type_counts.get(action_type, 0) + 1
            if not invalid:
                valid_successful_count += 1
        else:
            failed_count += 1
    action_count = len(actions)
    return {
        "action_count": action_count,
        "valid_action_count": max(action_count - invalid_count, 0),
        "invalid_action_count": invalid_count,
        "successful_action_count": successful_count,
        "failed_action_count": failed_count,
        "valid_successful_action_count": valid_successful_count,
        "action_type_counts": dict(sorted(action_type_counts.items())),
        "successful_action_type_counts": dict(sorted(successful_action_type_counts.items())),
    }


def _load_session_events(session_log_path: str) -> list[dict]:
    events = []
    with open(session_log_path, "r", encoding="utf-8-sig") as f:
        for line_number, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"line {line_number}: invalid JSON: {exc}") from exc
            if isinstance(event, dict):
                events.append(event)
    return events


def _goal_segments(events: list[dict]) -> list[tuple[str, list[dict]]]:
    segments = []
    current_goal = ""
    current_events: list[dict] = []
    for event in events:
        event_type = event.get("type")
        data = event.get("data", {}) if isinstance(event.get("data", {}), dict) else {}
        if event_type == "goal_start":
            if current_events:
                segments.append((current_goal, current_events))
            current_goal = str(data.get("goal", ""))
            current_events = [event]
            continue
        if current_events:
            current_events.append(event)
            if event_type == "goal_end":
                if not current_goal:
                    current_goal = str(data.get("goal", ""))
                segments.append((current_goal, current_events))
                current_goal = ""
                current_events = []
        elif event_type == "goal_end":
            goal = str(data.get("goal", ""))
            segments.append((goal, [event]))
    if current_events:
        segments.append((current_goal, current_events))
    return segments


def _trace_context(events: list[dict]) -> dict:
    context = {
        "slots": {},
        "memory_preferences": {},
        "clarification_answers": {},
    }
    for event in events:
        data = event.get("data", {}) if isinstance(event.get("data", {}), dict) else {}
        if event.get("type") in {"clarification", "clarification_answer"}:
            slot = data.get("slot") or data.get("parameter")
            value = data.get("value") or data.get("answer")
            if slot and value not in (None, ""):
                context["clarification_answers"][str(slot)] = value
        if event.get("type") == "memory_write":
            content = data.get("content", {})
            if isinstance(content, dict) and content.get("memory_type") == "scoped_preference":
                slot = content.get("slot")
                value = content.get("value")
                if slot and value not in (None, ""):
                    context["memory_preferences"][str(slot)] = value
        if event.get("type") == "observation":
            obs_preferences = data.get("memory_preferences", {})
            if isinstance(obs_preferences, dict):
                context["memory_preferences"].update(obs_preferences)
            slots = data.get("slots", {})
            if isinstance(slots, dict):
                context["slots"].update(slots)
    return {key: value for key, value in context.items() if value}


def _bounded_evidence_from_events(events: list[dict]) -> dict:
    observations = [
        event.get("data", {})
        for event in events
        if event.get("type") == "observation" and isinstance(event.get("data", {}), dict)
    ]
    actions = [
        event.get("data", {})
        for event in events
        if event.get("type") == "action" and isinstance(event.get("data", {}), dict)
    ]
    recent_chat = []
    for event in events:
        data = event.get("data", {}) if isinstance(event.get("data", {}), dict) else {}
        if event.get("type") in {"chat", "message"}:
            text = data.get("message") or data.get("text")
            if text:
                recent_chat.append(str(text))
        if event.get("type") == "observation":
            for key in ("recent_chat", "chat"):
                value = data.get(key, [])
                if isinstance(value, list):
                    recent_chat.extend(str(item) for item in value)
                elif value:
                    recent_chat.append(str(value))
    return {
        "pre_observation": observations[0] if observations else {},
        "post_observation": observations[-1] if observations else {},
        "actions": actions,
        "recent_chat": recent_chat,
    }


def _latest_goal_verification(events: list[dict]) -> dict:
    for event in reversed(events):
        if event.get("type") == "goal_verification" and isinstance(event.get("data", {}), dict):
            return event["data"]
    return {}


def _goal_verification_accepted(goal_verification: dict) -> Optional[bool]:
    if not goal_verification:
        return None
    context = goal_verification.get("context", {})
    if isinstance(context, dict) and "accepted" in context:
        return bool(context.get("accepted"))
    if "achieved" in goal_verification:
        return bool(goal_verification.get("achieved"))
    return None


def _validator_goal_agreement(
    validator_success: bool,
    validator_invalid: bool,
    goal_verification: dict,
) -> str:
    if validator_invalid:
        return "invalid_policy"
    accepted = _goal_verification_accepted(goal_verification)
    achieved = goal_verification.get("achieved") if goal_verification else None
    if accepted is None and achieved is None:
        return "no_goal_verification"
    goal_success = bool(accepted if accepted is not None else achieved)
    if validator_success and goal_success:
        return "agrees_success"
    if not validator_success and not goal_success:
        return "agrees_failure"
    if not validator_success and goal_success:
        return "validator_stricter"
    return "goal_verifier_stricter"


def _template_candidate_for_goal(goal: str) -> dict:
    text = str(goal or "").lower()
    count = _first_number(text)
    if any(token in text for token in ("craft", "make", "smelt", "cook")):
        target = _target_after_keywords(text, ["craft", "make", "smelt", "cook"]) or "item"
        return {
            "candidate_id": "craft_or_process_item",
            "category": "crafting_processing",
            "goal_pattern": f"craft/process {count or '{count}'} {target}",
            "suggested_slots": ["item", "count", "station", "fuel"],
            "suggested_validators": ["inventory_at_least", "inventory_delta_at_least", "action_success:craft_or_smelt"],
            "reason": "goal uses crafting or processing language but no task template exists",
        }
    if any(token in text for token in ("mine", "dig", "collect", "gather", "harvest")):
        target = _target_after_keywords(text, ["mine", "dig", "collect", "gather", "harvest"]) or "resource"
        return {
            "candidate_id": "collect_or_mine_resource",
            "category": "resource_collection",
            "goal_pattern": f"collect/mine {count or '{count}'} {target}",
            "suggested_slots": ["resource", "count", "search_radius", "tool"],
            "suggested_validators": ["nearby_block_present", "inventory_at_least", "inventory_delta_at_least"],
            "reason": "resource collection request is outside the current oak-log seed template",
        }
    if any(token in text for token in ("build", "place", "shelter", "house", "wall", "bridge")):
        target = _target_after_keywords(text, ["build", "place"]) or "structure"
        return {
            "candidate_id": "build_or_place_structure",
            "category": "construction_building",
            "goal_pattern": f"build/place {target}",
            "suggested_slots": ["structure", "material", "location", "size"],
            "suggested_validators": ["flag_present", "nearby_block_present", "action_success:place", "position_delta_at_least"],
            "reason": "construction requests need layout/material slots and structure evidence validators",
        }
    if any(token in text for token in ("explore", "scout", "find", "locate", "navigate", "go to", "return")):
        target = _target_after_keywords(text, ["find", "locate", "navigate", "explore", "scout"]) or "location"
        return {
            "candidate_id": "navigate_or_explore_location",
            "category": "navigation_exploration",
            "goal_pattern": f"navigate/explore {target}",
            "suggested_slots": ["target", "search_radius", "return_target"],
            "suggested_validators": ["position_delta_at_least", "nearby_block_present", "flag_present", "recent_chat_contains"],
            "reason": "navigation and exploration requests need bounded location evidence",
        }
    if any(token in text for token in ("torch", "light", "hostile", "safe", "defend", "attack", "flee")):
        return {
            "candidate_id": "safety_or_lighting_task",
            "category": "combat_safety",
            "goal_pattern": "make area safe / place lighting",
            "suggested_slots": ["threat", "light_source", "location"],
            "suggested_validators": ["nearby_entity_absent", "nearby_block_present", "action_success:place_or_attack"],
            "reason": "safety and lighting requests need threat/light evidence validators",
        }
    if any(token in text for token in ("fetch", "bring", "retrieve", "get")):
        return {
            "candidate_id": "retrieve_item_or_artifact",
            "category": "navigation_retrieval",
            "goal_pattern": "retrieve {item} from {location}",
            "suggested_slots": ["item", "source_location", "return_target"],
            "suggested_validators": ["inventory_at_least", "equipment_has", "position_delta_at_least"],
            "reason": "retrieval request does not match the current pickaxe-specific template",
        }
    return {
        "candidate_id": "general_player_request",
        "category": "general",
        "goal_pattern": "{user_goal}",
        "suggested_slots": ["intent", "target", "location"],
        "suggested_validators": ["goal_verification", "recent_chat_contains"],
        "reason": "goal does not match any current mixed-initiative template family",
    }


def _first_number(text: str) -> Optional[int]:
    match = re.search(r"\b(\d+)\b", text)
    return int(match.group(1)) if match else None


PLURAL_ITEM_OVERRIDES = {
    "torches": "torch",
    "logs": "log",
    "ingots": "ingot",
}
PLURAL_ITEM_KEEP = {
    "planks",
    "stairs",
    "leggings",
}
ORE_BLOCK_DROPS = {
    "coal_ore": "coal",
    "deepslate_coal_ore": "coal",
    "iron_ore": "raw_iron",
    "deepslate_iron_ore": "raw_iron",
    "gold_ore": "raw_gold",
    "deepslate_gold_ore": "raw_gold",
    "copper_ore": "raw_copper",
    "deepslate_copper_ore": "raw_copper",
    "diamond_ore": "diamond",
    "deepslate_diamond_ore": "diamond",
    "emerald_ore": "emerald",
    "deepslate_emerald_ore": "emerald",
    "redstone_ore": "redstone",
    "deepslate_redstone_ore": "redstone",
    "lapis_ore": "lapis_lazuli",
    "deepslate_lapis_ore": "lapis_lazuli",
}
RESOURCE_SOURCE_BLOCKS = {
    "coal": "coal_ore",
    "iron": "iron_ore",
    "raw_iron": "iron_ore",
    "gold": "gold_ore",
    "raw_gold": "gold_ore",
    "copper": "copper_ore",
    "raw_copper": "copper_ore",
    "diamond": "diamond_ore",
    "emerald": "emerald_ore",
    "redstone": "redstone_ore",
    "lapis": "lapis_ore",
    "lapis_lazuli": "lapis_ore",
}
RESOURCE_ITEM_ALIASES = {
    "iron": "raw_iron",
    "gold": "raw_gold",
    "copper": "raw_copper",
    "lapis": "lapis_lazuli",
}
STRUCTURE_WORDS = {
    "shelter",
    "house",
    "wall",
    "bridge",
    "tower",
    "farm",
    "base",
    "roof",
    "floor",
    "path",
    "stair",
    "stairs",
    "torch",
}


def _canonical_item_name(raw: str) -> str:
    text = str(raw or "").lower().strip()
    text = re.sub(r"^\d+\s*", "", text)
    text = re.sub(r"\b(?:minecraft|items?|blocks?|pieces?|stacks?)\b", " ", text)
    text = re.sub(r"[^a-z0-9_]+", "_", text).strip("_")
    text = re.sub(r"_+", "_", text)
    if not text:
        return ""
    parts = [part for part in text.split("_") if part and part not in {"of", "the"}]
    if not parts:
        return ""
    last = parts[-1]
    if last in PLURAL_ITEM_OVERRIDES:
        parts[-1] = PLURAL_ITEM_OVERRIDES[last]
    elif last not in PLURAL_ITEM_KEEP:
        if last.endswith("ies") and len(last) > 4:
            parts[-1] = f"{last[:-3]}y"
        elif last.endswith(("ches", "shes", "xes", "ses", "zes")) and len(last) > 4:
            parts[-1] = last[:-2]
        elif last.endswith("s") and not last.endswith("ss") and len(last) > 3:
            parts[-1] = last[:-1]
    return "_".join(parts)


def _resource_item_and_source_block(raw: str) -> tuple[str, str]:
    target = _canonical_item_name(raw)
    if not target:
        return "", ""
    if target in ORE_BLOCK_DROPS:
        return ORE_BLOCK_DROPS[target], target
    source_block = RESOURCE_SOURCE_BLOCKS.get(target, target)
    resource = RESOURCE_ITEM_ALIASES.get(target, target)
    return resource, source_block


def _structure_keyword(text: str) -> str:
    for keyword in sorted(STRUCTURE_WORDS):
        if re.search(rf"\b{re.escape(keyword)}\b", text):
            return keyword
    return ""


def _structure_and_material_from_target(raw: str) -> tuple[str, str]:
    target = _canonical_item_name(raw)
    if not target:
        return "", ""
    parts = target.split("_")
    for index, part in enumerate(parts):
        if part in STRUCTURE_WORDS:
            material = "_".join(parts[:index])
            return part, material
    return target, ""


def _material_after_goal(text: str) -> str:
    match = re.search(r"\b(?:with|using)\s+(?:a|an|the|some)?\s*([a-z0-9_ -]+)", text)
    if not match:
        return ""
    material = re.split(r"\b(?:near|at|from|to|before|after|and|then)\b", match.group(1))[0].strip()
    return _canonical_item_name(material)


def _target_after_keywords(text: str, keywords: list[str]) -> str:
    for keyword in keywords:
        match = re.search(rf"\b{re.escape(keyword)}\b\s+(?:a|an|the|some)?\s*([a-z0-9_ -]+)", text)
        if not match:
            continue
        target = match.group(1).strip()
        target = re.split(r"\b(?:within|near|at|from|to|before|after|and|then|using|with)\b", target)[0].strip()
        words = [word for word in target.split() if word]
        if words:
            return "_".join(words[:4])
    return ""


def _evidence_summary(evidence: dict) -> dict:
    pre = evidence.get("pre_observation", {}) if isinstance(evidence.get("pre_observation", {}), dict) else {}
    post = evidence.get("post_observation", {}) if isinstance(evidence.get("post_observation", {}), dict) else {}
    return {
        "has_pre_observation": bool(pre),
        "has_post_observation": bool(post),
        "pre_inventory_keys": sorted((pre.get("inventory", {}) or {}).keys()) if isinstance(pre.get("inventory", {}), dict) else [],
        "post_inventory_keys": sorted((post.get("inventory", {}) or {}).keys()) if isinstance(post.get("inventory", {}), dict) else [],
        "nearby_block_count": len(post.get("nearby_blocks", []) or []),
        "nearby_entity_count": len(post.get("nearby_entities", []) or []),
        "action_count": len(evidence.get("actions", []) or []),
        "recent_chat_count": len(evidence.get("recent_chat", []) or []),
    }
