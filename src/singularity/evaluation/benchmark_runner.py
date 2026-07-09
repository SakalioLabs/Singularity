"""Benchmark runner for Singularity M1-M2 validation."""
import importlib.util
import json
import math
import os
import shutil
import socket
import subprocess
import tempfile
import time
import logging
from dataclasses import asdict, dataclass, field, replace
from typing import Optional

from singularity.core.config import Config, BotConfig, LLMConfig
from singularity.core.agent import Agent
from singularity.core.causal_index import (
    CausalEvent,
    CausalEventIndex,
    CausalEventSummary,
    aggregate_causal_events,
)
from singularity.core.coach import CoachPolicy
from singularity.core.curriculum import CurriculumManager
from singularity.core.task_system import TaskStatus, TaskSystem
from singularity.bot.bridge import BotBridge
from singularity.action.mapping import ActionMapper

logger = logging.getLogger("singularity.benchmark")


def _average_optional(values) -> Optional[float]:
    present = [float(value) for value in values if value is not None]
    if not present:
        return None
    return round(sum(present) / len(present), 3)


@dataclass
class BenchmarkTask:
    id: str
    name: str
    goal: str
    phase: str
    timeout_cycles: int = 100
    success_criteria: dict = field(default_factory=dict)
    min_inventory: dict = field(default_factory=dict)


@dataclass
class SchedulingAblationCase:
    id: str
    name: str
    world_state: dict
    tasks: list[dict]
    expected_causal_task: str = ""


@dataclass
class SchedulingAblationResult:
    case_id: str
    case_name: str
    direct_only_task: str
    causal_enabled_task: str
    changed: bool
    causal_helped: bool
    causal_tags: list[str] = field(default_factory=list)
    source: str = ""
    action_type: str = ""
    outcome: str = ""
    value_score: float = 0.0
    avg_value_score: float = 0.0
    repeat_count: int = 1


@dataclass
class SchedulingAblationReport:
    cases: list[SchedulingAblationResult] = field(default_factory=list)

    @property
    def changed_count(self) -> int:
        return sum(1 for case in self.cases if case.changed)

    @property
    def helped_count(self) -> int:
        return sum(1 for case in self.cases if case.causal_helped)


@dataclass
class CoachStyleAblationCase:
    id: str
    name: str
    observation: dict
    fallback_goal: str = "Explore surroundings and gather resources"
    styles: list[str] = field(default_factory=list)
    exploration_feedback: dict = field(default_factory=dict)
    world_model_feedback: dict = field(default_factory=dict)
    source: str = ""


@dataclass
class CoachStyleAblationResult:
    case_id: str
    case_name: str
    style: str
    baseline_goal: str
    styled_goal: str
    changed: bool
    baseline_score: float = 0.0
    styled_score: float = 0.0
    score_delta: float = 0.0
    baseline_category: str = ""
    styled_category: str = ""
    styled_reasons: list[str] = field(default_factory=list)
    baseline_candidates: list[dict] = field(default_factory=list)
    styled_candidates: list[dict] = field(default_factory=list)
    fallback_goal: str = ""
    source: str = ""


@dataclass
class CoachStyleAblationReport:
    cases: list[CoachStyleAblationResult] = field(default_factory=list)

    @property
    def changed_count(self) -> int:
        return sum(1 for case in self.cases if case.changed)

    @property
    def score_changed_count(self) -> int:
        return sum(1 for case in self.cases if abs(case.score_delta) > 0.0001)

    @property
    def style_changed_counts(self) -> dict:
        counts = {}
        for case in self.cases:
            if case.changed:
                counts[case.style] = counts.get(case.style, 0) + 1
        return counts


@dataclass
class PolicySkillAblationCase:
    id: str
    name: str
    goal: str
    world_state: dict
    failed_action: dict
    failed_result: dict
    skill_name: str
    skill_description: str
    skill_implementation: dict
    expected_enabled_corrected: bool = True
    source: str = "builtin"


@dataclass
class PolicySkillAblationResult:
    case_id: str
    case_name: str
    disabled_corrected: bool
    enabled_corrected: bool
    enabled_helped: bool
    disabled_interventions: int = 0
    enabled_interventions: int = 0
    enabled_success_rate: float = 0.0
    enabled_actions: list[str] = field(default_factory=list)
    skill_name: str = ""
    source: str = "builtin"


@dataclass
class PolicySkillAblationReport:
    cases: list[PolicySkillAblationResult] = field(default_factory=list)

    @property
    def helped_count(self) -> int:
        return sum(1 for case in self.cases if case.enabled_helped)


@dataclass
class PolicySkillBenchmarkAblationResult:
    task_id: str
    task_name: str
    disabled_status: str
    enabled_status: str
    disabled_duration_s: float = 0.0
    enabled_duration_s: float = 0.0
    disabled_interventions: int = 0
    enabled_interventions: int = 0
    enabled_success_rate: float = 0.0
    enabled_helped: bool = False
    disabled_log: str = ""
    enabled_log: str = ""


@dataclass
class PolicySkillBenchmarkAblationReport:
    cases: list[PolicySkillBenchmarkAblationResult] = field(default_factory=list)

    @property
    def disabled_passed_count(self) -> int:
        return sum(1 for case in self.cases if case.disabled_status == "pass")

    @property
    def enabled_passed_count(self) -> int:
        return sum(1 for case in self.cases if case.enabled_status == "pass")

    @property
    def helped_count(self) -> int:
        return sum(1 for case in self.cases if case.enabled_helped)


@dataclass
class SkillMemoryBenchmarkAblationResult:
    task_id: str
    task_name: str
    baseline_status: str
    enabled_status: str
    baseline_duration_s: float = 0.0
    enabled_duration_s: float = 0.0
    baseline_skill_memory_hints: int = 0
    enabled_skill_memory_hints: int = 0
    enabled_changed: bool = False
    enabled_helped: bool = False
    baseline_log: str = ""
    enabled_log: str = ""


@dataclass
class SkillMemoryBenchmarkAblationReport:
    cases: list[SkillMemoryBenchmarkAblationResult] = field(default_factory=list)

    @property
    def baseline_passed_count(self) -> int:
        return sum(1 for case in self.cases if case.baseline_status == "pass")

    @property
    def enabled_passed_count(self) -> int:
        return sum(1 for case in self.cases if case.enabled_status == "pass")

    @property
    def changed_count(self) -> int:
        return sum(1 for case in self.cases if case.enabled_changed)

    @property
    def helped_count(self) -> int:
        return sum(1 for case in self.cases if case.enabled_helped)


@dataclass
class SkillMemoryQualityCase:
    source_log: str
    event_count: int = 0
    hint_event_count: int = 0
    hint_count: int = 0
    reuse_hint_count: int = 0
    avoid_hint_count: int = 0
    review_only_hint_count: int = 0
    unknown_hint_count: int = 0
    action_count: int = 0
    failed_action_count: int = 0
    post_hint_action_count: int = 0
    post_hint_failed_action_count: int = 0
    repeated_post_hint_failure_count: int = 0
    goal_count: int = 0
    completed_goal_count: int = 0
    failed_goal_count: int = 0
    post_hint_goal_success_count: int = 0
    post_hint_goal_failure_count: int = 0
    task_family_counts: dict = field(default_factory=dict)
    hint_type_counts: dict = field(default_factory=dict)
    hint_quality_items: list[dict] = field(default_factory=list)
    quality_labels: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    ready_for_skill_memory_quality_review: bool = False


@dataclass
class SkillMemoryQualityReport:
    cases: list[SkillMemoryQualityCase] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def log_count(self) -> int:
        return len(self.cases)

    @property
    def ready_log_count(self) -> int:
        return sum(1 for case in self.cases if case.ready_for_skill_memory_quality_review)

    @property
    def hint_event_count(self) -> int:
        return sum(case.hint_event_count for case in self.cases)

    @property
    def hint_count(self) -> int:
        return sum(case.hint_count for case in self.cases)

    @property
    def reuse_hint_count(self) -> int:
        return sum(case.reuse_hint_count for case in self.cases)

    @property
    def avoid_hint_count(self) -> int:
        return sum(case.avoid_hint_count for case in self.cases)

    @property
    def review_only_hint_count(self) -> int:
        return sum(case.review_only_hint_count for case in self.cases)

    @property
    def unknown_hint_count(self) -> int:
        return sum(case.unknown_hint_count for case in self.cases)

    @property
    def post_hint_failed_action_count(self) -> int:
        return sum(case.post_hint_failed_action_count for case in self.cases)

    @property
    def post_hint_goal_success_count(self) -> int:
        return sum(case.post_hint_goal_success_count for case in self.cases)

    @property
    def post_hint_goal_failure_count(self) -> int:
        return sum(case.post_hint_goal_failure_count for case in self.cases)

    @property
    def repeated_post_hint_failure_count(self) -> int:
        return sum(case.repeated_post_hint_failure_count for case in self.cases)

    @property
    def task_family_counts(self) -> dict:
        counts = {}
        for case in self.cases:
            for family, count in case.task_family_counts.items():
                counts[family] = counts.get(family, 0) + count
        return counts

    @property
    def hint_type_counts(self) -> dict:
        counts = {}
        for case in self.cases:
            for hint_type, count in case.hint_type_counts.items():
                counts[hint_type] = counts.get(hint_type, 0) + count
        return counts

    @property
    def quality_label_counts(self) -> dict:
        counts = {}
        for case in self.cases:
            for label in case.quality_labels:
                counts[label] = counts.get(label, 0) + 1
        return counts

    @property
    def hint_quality_items(self) -> list[dict]:
        merged = {}
        for case in self.cases:
            for item in case.hint_quality_items:
                key = (
                    item.get("hint_type", "UNKNOWN"),
                    item.get("skill", "unknown"),
                    item.get("task_family", "unspecified"),
                )
                current = merged.setdefault(key, {
                    "hint_type": key[0],
                    "skill": key[1],
                    "task_family": key[2],
                    "count": 0,
                    "labels": {},
                    "source_logs": [],
                    "examples": [],
                })
                current["count"] += int(item.get("count", 0) or 0)
                for label, count in (item.get("labels", {}) or {}).items():
                    current["labels"][label] = current["labels"].get(label, 0) + int(count or 0)
                source_log = item.get("source_log")
                if source_log and source_log not in current["source_logs"]:
                    current["source_logs"].append(source_log)
                for example in item.get("examples", []) or []:
                    if example and example not in current["examples"]:
                        current["examples"].append(example)
        return sorted(
            merged.values(),
            key=lambda item: (sum(item["labels"].values()), item["count"], item["skill"]),
            reverse=True,
        )


@dataclass
class VisualActionBenchmarkAblationResult:
    task_id: str
    task_name: str
    disabled_status: str
    enabled_status: str
    disabled_duration_s: float = 0.0
    enabled_duration_s: float = 0.0
    disabled_visual_actions: int = 0
    enabled_visual_actions: int = 0
    enabled_changed: bool = False
    enabled_helped: bool = False
    enabled_phases: dict = field(default_factory=dict)
    disabled_log: str = ""
    enabled_log: str = ""


@dataclass
class VisualActionBenchmarkAblationReport:
    cases: list[VisualActionBenchmarkAblationResult] = field(default_factory=list)

    @property
    def disabled_passed_count(self) -> int:
        return sum(1 for case in self.cases if case.disabled_status == "pass")

    @property
    def enabled_passed_count(self) -> int:
        return sum(1 for case in self.cases if case.enabled_status == "pass")

    @property
    def changed_count(self) -> int:
        return sum(1 for case in self.cases if case.enabled_changed)

    @property
    def helped_count(self) -> int:
        return sum(1 for case in self.cases if case.enabled_helped)


@dataclass
class MixedPolicyBenchmarkAblationResult:
    task_id: str
    task_name: str
    baseline_status: str
    patched_status: str
    baseline_duration_s: float = 0.0
    patched_duration_s: float = 0.0
    baseline_control_policy: dict = field(default_factory=dict)
    patched_control_policy: dict = field(default_factory=dict)
    patched_changed: bool = False
    patched_helped: bool = False
    baseline_log: str = ""
    patched_log: str = ""


@dataclass
class MixedPolicyBenchmarkAblationReport:
    patch_paths: list[str] = field(default_factory=list)
    policy_decision_report: dict = field(default_factory=dict)
    cases: list[MixedPolicyBenchmarkAblationResult] = field(default_factory=list)

    @property
    def baseline_passed_count(self) -> int:
        return sum(1 for case in self.cases if case.baseline_status == "pass")

    @property
    def patched_passed_count(self) -> int:
        return sum(1 for case in self.cases if case.patched_status == "pass")

    @property
    def changed_count(self) -> int:
        return sum(1 for case in self.cases if case.patched_changed)

    @property
    def helped_count(self) -> int:
        return sum(1 for case in self.cases if case.patched_helped)

    @property
    def control_changed_count(self) -> int:
        return sum(
            1
            for case in self.cases
            if case.baseline_control_policy != case.patched_control_policy
        )


@dataclass
class VisualActionAblationCase:
    id: str
    name: str
    goal: str
    observation: dict
    plan: dict
    expected_enabled_changed: bool = True
    expected_phase: str = ""
    source: str = "builtin"


@dataclass
class VisualActionAblationResult:
    case_id: str
    case_name: str
    disabled_actions: list[dict]
    enabled_actions: list[dict]
    changed: bool
    passed: bool
    enabled_helped: bool = False
    disabled_interventions: int = 0
    enabled_interventions: int = 0
    expected_enabled_changed: bool = True
    expected_phase: str = ""
    enabled_phases: dict = field(default_factory=dict)
    enabled_kinds: dict = field(default_factory=dict)
    source: str = "builtin"


@dataclass
class VisualActionAblationReport:
    cases: list[VisualActionAblationResult] = field(default_factory=list)

    @property
    def passed_count(self) -> int:
        return sum(1 for case in self.cases if case.passed)

    @property
    def changed_count(self) -> int:
        return sum(1 for case in self.cases if case.changed)

    @property
    def helped_count(self) -> int:
        return sum(1 for case in self.cases if case.enabled_helped)


@dataclass
class PromotionReviewAblationResult:
    source_log: str
    candidate_id: str
    candidate_name: str
    goal: str
    score: float
    has_visual_evidence: bool
    visual_evidence_keys: list[str] = field(default_factory=list)
    raw_screenshot_count: int = 0
    screenshot_count: int = 0
    missing_screenshot_count: int = 0
    invalid_screenshot_count: int = 0
    manual_readiness: str = ""
    manual_label_source: str = ""
    manual_label_notes: str = ""
    deterministic_readiness: str = "unknown"
    api_visual_readiness: str = "unknown"
    screenshot_vlm_readiness: str = "unknown"
    deterministic_decision: str = "unknown"
    api_visual_decision: str = "unknown"
    screenshot_vlm_decision: str = "unknown"
    deterministic_status: str = "unknown"
    api_visual_status: str = "unknown"
    screenshot_vlm_status: str = "unknown"
    deterministic_reason: str = ""
    api_visual_reason: str = ""
    screenshot_vlm_reason: str = ""
    deterministic_postconditions: dict = field(default_factory=dict)
    api_visual_postconditions: dict = field(default_factory=dict)
    screenshot_vlm_postconditions: dict = field(default_factory=dict)
    without_visual_readiness: str = "unknown"
    with_visual_readiness: str = "unknown"
    without_visual_decision: str = "unknown"
    with_visual_decision: str = "unknown"
    without_visual_status: str = "unknown"
    with_visual_status: str = "unknown"
    without_visual_reason: str = ""
    with_visual_reason: str = ""
    without_visual_postconditions: dict = field(default_factory=dict)
    with_visual_postconditions: dict = field(default_factory=dict)
    changed: bool = False
    visual_helped: bool = False
    api_visual_helped: bool = False
    screenshot_vlm_helped: bool = False
    screenshot_vlm_added_value: bool = False
    deterministic_matches_manual: Optional[bool] = None
    api_visual_matches_manual: Optional[bool] = None
    screenshot_vlm_matches_manual: Optional[bool] = None


@dataclass
class PromotionReviewAblationReport:
    cases: list[PromotionReviewAblationResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def candidate_count(self) -> int:
        return len(self.cases)

    @property
    def changed_count(self) -> int:
        return sum(1 for case in self.cases if case.changed)

    @property
    def visual_helped_count(self) -> int:
        return sum(1 for case in self.cases if case.visual_helped)

    @property
    def api_visual_helped_count(self) -> int:
        return sum(1 for case in self.cases if case.api_visual_helped)

    @property
    def screenshot_vlm_helped_count(self) -> int:
        return sum(1 for case in self.cases if case.screenshot_vlm_helped)

    @property
    def screenshot_vlm_added_value_count(self) -> int:
        return sum(1 for case in self.cases if case.screenshot_vlm_added_value)

    @property
    def manual_labeled_count(self) -> int:
        return sum(1 for case in self.cases if case.manual_readiness)

    @property
    def deterministic_manual_match_count(self) -> int:
        return sum(1 for case in self.cases if case.deterministic_matches_manual is True)

    @property
    def api_visual_manual_match_count(self) -> int:
        return sum(1 for case in self.cases if case.api_visual_matches_manual is True)

    @property
    def screenshot_vlm_manual_match_count(self) -> int:
        return sum(1 for case in self.cases if case.screenshot_vlm_matches_manual is True)

    @property
    def screenshot_vlm_manual_improvement_count(self) -> int:
        return sum(
            1 for case in self.cases
            if case.api_visual_matches_manual is False and case.screenshot_vlm_matches_manual is True
        )


@dataclass
class GoalVerificationAblationResult:
    source_log: str
    goal: str
    has_visual_evidence: bool
    goal_index: int = 0
    visual_evidence_keys: list[str] = field(default_factory=list)
    raw_screenshot_count: int = 0
    screenshot_count: int = 0
    missing_screenshot_count: int = 0
    invalid_screenshot_count: int = 0
    manual_readiness: str = ""
    manual_label_source: str = ""
    manual_label_notes: str = ""
    deterministic_readiness: str = "unknown"
    api_visual_readiness: str = "unknown"
    screenshot_vlm_readiness: str = "unknown"
    deterministic_status: str = "unknown"
    api_visual_status: str = "unknown"
    screenshot_vlm_status: str = "unknown"
    deterministic_confidence: float = 0.0
    api_visual_confidence: float = 0.0
    screenshot_vlm_confidence: float = 0.0
    deterministic_reason: str = ""
    api_visual_reason: str = ""
    screenshot_vlm_reason: str = ""
    deterministic_evidence: list[str] = field(default_factory=list)
    api_visual_evidence: list[str] = field(default_factory=list)
    screenshot_vlm_evidence: list[str] = field(default_factory=list)
    deterministic_missing: list[str] = field(default_factory=list)
    api_visual_missing: list[str] = field(default_factory=list)
    screenshot_vlm_missing: list[str] = field(default_factory=list)
    deterministic_matched_rules: list[str] = field(default_factory=list)
    api_visual_matched_rules: list[str] = field(default_factory=list)
    screenshot_vlm_matched_rules: list[str] = field(default_factory=list)
    changed: bool = False
    visual_helped: bool = False
    api_visual_helped: bool = False
    screenshot_vlm_helped: bool = False
    screenshot_vlm_added_value: bool = False
    deterministic_matches_manual: Optional[bool] = None
    api_visual_matches_manual: Optional[bool] = None
    screenshot_vlm_matches_manual: Optional[bool] = None


@dataclass
class GoalVerificationAblationReport:
    cases: list[GoalVerificationAblationResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def goal_count(self) -> int:
        return len(self.cases)

    @property
    def changed_count(self) -> int:
        return sum(1 for case in self.cases if case.changed)

    @property
    def visual_helped_count(self) -> int:
        return sum(1 for case in self.cases if case.visual_helped)

    @property
    def api_visual_helped_count(self) -> int:
        return sum(1 for case in self.cases if case.api_visual_helped)

    @property
    def screenshot_vlm_helped_count(self) -> int:
        return sum(1 for case in self.cases if case.screenshot_vlm_helped)

    @property
    def screenshot_vlm_added_value_count(self) -> int:
        return sum(1 for case in self.cases if case.screenshot_vlm_added_value)

    @property
    def manual_labeled_count(self) -> int:
        return sum(1 for case in self.cases if case.manual_readiness)

    @property
    def deterministic_manual_match_count(self) -> int:
        return sum(1 for case in self.cases if case.deterministic_matches_manual is True)

    @property
    def api_visual_manual_match_count(self) -> int:
        return sum(1 for case in self.cases if case.api_visual_matches_manual is True)

    @property
    def screenshot_vlm_manual_match_count(self) -> int:
        return sum(1 for case in self.cases if case.screenshot_vlm_matches_manual is True)

    @property
    def screenshot_vlm_manual_improvement_count(self) -> int:
        return sum(
            1 for case in self.cases
            if case.api_visual_matches_manual is False and case.screenshot_vlm_matches_manual is True
        )


@dataclass
class VisualTraceCoverageCase:
    source_log: str
    observation_count: int = 0
    visual_observation_count: int = 0
    raw_screenshot_count: int = 0
    screenshot_count: int = 0
    missing_screenshot_count: int = 0
    invalid_screenshot_count: int = 0
    visual_analysis_count: int = 0
    goal_count: int = 0
    goals_with_visual_evidence: int = 0
    promotion_candidate_count: int = 0
    promotion_candidates_with_visual_evidence: int = 0
    ready_for_visual_ablation: bool = False
    visual_evidence_keys: list[str] = field(default_factory=list)
    raw_screenshot_paths: list[str] = field(default_factory=list)
    screenshot_paths: list[str] = field(default_factory=list)
    missing_screenshot_paths: list[str] = field(default_factory=list)
    invalid_screenshot_paths: list[str] = field(default_factory=list)
    missing_visual_goals: list[str] = field(default_factory=list)


@dataclass
class VisualTraceCoverageReport:
    cases: list[VisualTraceCoverageCase] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def log_count(self) -> int:
        return len(self.cases)

    @property
    def ready_log_count(self) -> int:
        return sum(1 for case in self.cases if case.ready_for_visual_ablation)

    @property
    def screenshot_log_count(self) -> int:
        return sum(1 for case in self.cases if case.screenshot_count > 0)

    @property
    def raw_screenshot_log_count(self) -> int:
        return sum(1 for case in self.cases if case.raw_screenshot_count > 0)

    @property
    def missing_screenshot_count(self) -> int:
        return sum(case.missing_screenshot_count for case in self.cases)

    @property
    def invalid_screenshot_count(self) -> int:
        return sum(case.invalid_screenshot_count for case in self.cases)

    @property
    def goal_count(self) -> int:
        return sum(case.goal_count for case in self.cases)

    @property
    def goals_with_visual_evidence_count(self) -> int:
        return sum(case.goals_with_visual_evidence for case in self.cases)

    @property
    def promotion_candidate_count(self) -> int:
        return sum(case.promotion_candidate_count for case in self.cases)

    @property
    def promotion_candidates_with_visual_evidence_count(self) -> int:
        return sum(case.promotion_candidates_with_visual_evidence for case in self.cases)


@dataclass
class ExplorationTraceCase:
    source_log: str
    observation_count: int = 0
    goal_count: int = 0
    completed_goal_count: int = 0
    failed_goal_count: int = 0
    action_count: int = 0
    failed_action_count: int = 0
    plan_count: int = 0
    multi_step_plan_count: int = 0
    multi_hop_goal_count: int = 0
    auto_goal_count: int = 0
    curriculum_goal_count: int = 0
    position_count: int = 0
    unique_position_count: int = 0
    path_distance: float = 0.0
    x_span: float = 0.0
    y_span: float = 0.0
    z_span: float = 0.0
    visual_observation_count: int = 0
    raw_screenshot_count: int = 0
    screenshot_count: int = 0
    missing_screenshot_count: int = 0
    invalid_screenshot_count: int = 0
    hostile_encounter_count: int = 0
    danger_event_count: int = 0
    unique_block_types: list[str] = field(default_factory=list)
    unique_entity_types: list[str] = field(default_factory=list)
    unique_resource_types: list[str] = field(default_factory=list)
    action_failure_categories: dict = field(default_factory=dict)
    ready_for_exploration_review: bool = False


@dataclass
class ExplorationTraceReport:
    cases: list[ExplorationTraceCase] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def log_count(self) -> int:
        return len(self.cases)

    @property
    def ready_log_count(self) -> int:
        return sum(1 for case in self.cases if case.ready_for_exploration_review)

    @property
    def observation_count(self) -> int:
        return sum(case.observation_count for case in self.cases)

    @property
    def goal_count(self) -> int:
        return sum(case.goal_count for case in self.cases)

    @property
    def completed_goal_count(self) -> int:
        return sum(case.completed_goal_count for case in self.cases)

    @property
    def failed_goal_count(self) -> int:
        return sum(case.failed_goal_count for case in self.cases)

    @property
    def failed_action_count(self) -> int:
        return sum(case.failed_action_count for case in self.cases)

    @property
    def logs_with_movement_count(self) -> int:
        return sum(1 for case in self.cases if case.unique_position_count > 1)

    @property
    def visual_observation_count(self) -> int:
        return sum(case.visual_observation_count for case in self.cases)

    @property
    def hostile_encounter_count(self) -> int:
        return sum(case.hostile_encounter_count for case in self.cases)

    @property
    def unique_block_type_count(self) -> int:
        return len({name for case in self.cases for name in case.unique_block_types})

    @property
    def unique_entity_type_count(self) -> int:
        return len({name for case in self.cases for name in case.unique_entity_types})

    @property
    def unique_resource_type_count(self) -> int:
        return len({name for case in self.cases for name in case.unique_resource_types})


@dataclass
class WorldModelTraceCase:
    source_log: str
    cell_size: float = 8.0
    observation_count: int = 0
    position_count: int = 0
    unique_cell_count: int = 0
    transition_count: int = 0
    frontier_count: int = 0
    resource_hotspot_count: int = 0
    danger_cell_count: int = 0
    ready_for_world_model_review: bool = False
    cells: list[dict] = field(default_factory=list)
    transitions: list[dict] = field(default_factory=list)
    frontiers: list[dict] = field(default_factory=list)
    resource_hotspots: list[dict] = field(default_factory=list)
    suggested_exploration_goals: list[str] = field(default_factory=list)


@dataclass
class WorldModelTraceReport:
    cases: list[WorldModelTraceCase] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def log_count(self) -> int:
        return len(self.cases)

    @property
    def ready_log_count(self) -> int:
        return sum(1 for case in self.cases if case.ready_for_world_model_review)

    @property
    def observation_count(self) -> int:
        return sum(case.observation_count for case in self.cases)

    @property
    def unique_cell_count(self) -> int:
        return sum(case.unique_cell_count for case in self.cases)

    @property
    def frontier_count(self) -> int:
        return sum(case.frontier_count for case in self.cases)

    @property
    def resource_hotspot_count(self) -> int:
        return sum(case.resource_hotspot_count for case in self.cases)

    @property
    def danger_cell_count(self) -> int:
        return sum(case.danger_cell_count for case in self.cases)


@dataclass
class SelfEvolutionTraceCase:
    source_log: str
    event_count: int = 0
    observation_count: int = 0
    goal_count: int = 0
    completed_goal_count: int = 0
    failed_goal_count: int = 0
    action_count: int = 0
    successful_action_count: int = 0
    failed_action_count: int = 0
    progress_signal_count: int = 0
    regression_signal_count: int = 0
    stagnation_signal_count: int = 0
    inventory_gain_count: int = 0
    inventory_loss_count: int = 0
    repeated_failure_count: int = 0
    no_progress_success_count: int = 0
    repeated_success_loop_count: int = 0
    blocked_plan_count: int = 0
    empty_plan_count: int = 0
    zero_action_failure_count: int = 0
    consecutive_no_movement_count: int = 0
    relative_reward_delta: float = 0.0
    absolute_reward_mean: float = 0.0
    typed_feedback_counts: dict = field(default_factory=dict)
    action_type_counts: dict = field(default_factory=dict)
    action_failure_categories: dict = field(default_factory=dict)
    progress_markers: list[str] = field(default_factory=list)
    remedy_candidates: list[str] = field(default_factory=list)
    adaptor_recommendations: list[str] = field(default_factory=list)
    ready_for_self_evolution_review: bool = False


@dataclass
class SelfEvolutionTraceReport:
    cases: list[SelfEvolutionTraceCase] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def log_count(self) -> int:
        return len(self.cases)

    @property
    def ready_log_count(self) -> int:
        return sum(1 for case in self.cases if case.ready_for_self_evolution_review)

    @property
    def observation_count(self) -> int:
        return sum(case.observation_count for case in self.cases)

    @property
    def action_count(self) -> int:
        return sum(case.action_count for case in self.cases)

    @property
    def failed_action_count(self) -> int:
        return sum(case.failed_action_count for case in self.cases)

    @property
    def progress_signal_count(self) -> int:
        return sum(case.progress_signal_count for case in self.cases)

    @property
    def regression_signal_count(self) -> int:
        return sum(case.regression_signal_count for case in self.cases)

    @property
    def stagnation_signal_count(self) -> int:
        return sum(case.stagnation_signal_count for case in self.cases)

    @property
    def repeated_failure_count(self) -> int:
        return sum(case.repeated_failure_count for case in self.cases)

    @property
    def no_progress_success_count(self) -> int:
        return sum(case.no_progress_success_count for case in self.cases)

    @property
    def repeated_success_loop_count(self) -> int:
        return sum(case.repeated_success_loop_count for case in self.cases)

    @property
    def blocked_plan_count(self) -> int:
        return sum(case.blocked_plan_count for case in self.cases)

    @property
    def empty_plan_count(self) -> int:
        return sum(case.empty_plan_count for case in self.cases)

    @property
    def zero_action_failure_count(self) -> int:
        return sum(case.zero_action_failure_count for case in self.cases)

    @property
    def relative_reward_delta(self) -> float:
        return round(sum(case.relative_reward_delta for case in self.cases), 3)


@dataclass
class PlanActionComplianceCase:
    source_log: str
    event_count: int = 0
    plan_count: int = 0
    action_count: int = 0
    planned_action_count: int = 0
    ordered_match_count: int = 0
    unordered_match_count: int = 0
    missing_planned_action_count: int = 0
    unplanned_action_count: int = 0
    order_violation_count: int = 0
    empty_plan_count: int = 0
    blocked_plan_count: int = 0
    plan_follow_score: float = 0.0
    action_precision: float = 0.0
    compliance_score: float = 0.0
    planned_action_type_counts: dict = field(default_factory=dict)
    executed_action_type_counts: dict = field(default_factory=dict)
    mismatch_examples: list[dict] = field(default_factory=list)
    ready_for_plan_action_review: bool = False


@dataclass
class PlanActionComplianceReport:
    cases: list[PlanActionComplianceCase] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def log_count(self) -> int:
        return len(self.cases)

    @property
    def ready_log_count(self) -> int:
        return sum(1 for case in self.cases if case.ready_for_plan_action_review)

    @property
    def plan_count(self) -> int:
        return sum(case.plan_count for case in self.cases)

    @property
    def action_count(self) -> int:
        return sum(case.action_count for case in self.cases)

    @property
    def planned_action_count(self) -> int:
        return sum(case.planned_action_count for case in self.cases)

    @property
    def ordered_match_count(self) -> int:
        return sum(case.ordered_match_count for case in self.cases)

    @property
    def unordered_match_count(self) -> int:
        return sum(case.unordered_match_count for case in self.cases)

    @property
    def missing_planned_action_count(self) -> int:
        return sum(case.missing_planned_action_count for case in self.cases)

    @property
    def unplanned_action_count(self) -> int:
        return sum(case.unplanned_action_count for case in self.cases)

    @property
    def order_violation_count(self) -> int:
        return sum(case.order_violation_count for case in self.cases)

    @property
    def empty_plan_count(self) -> int:
        return sum(case.empty_plan_count for case in self.cases)

    @property
    def blocked_plan_count(self) -> int:
        return sum(case.blocked_plan_count for case in self.cases)

    @property
    def plan_follow_score(self) -> float:
        return self._ratio(self.ordered_match_count, self.planned_action_count)

    @property
    def action_precision(self) -> float:
        return self._ratio(self.unordered_match_count, self.action_count)

    @property
    def compliance_score(self) -> float:
        denominator = (
            self.planned_action_count
            + self.unplanned_action_count
            + self.order_violation_count
            + self.empty_plan_count
        )
        return self._ratio(self.ordered_match_count, denominator)

    def _ratio(self, numerator: int, denominator: int) -> float:
        return round(numerator / denominator, 3) if denominator else 0.0


@dataclass
class TerminalCommitmentCase:
    source_log: str
    goal: str
    goal_index: int = 0
    event_count: int = 0
    observation_count: int = 0
    action_count: int = 0
    verification_event_count: int = 0
    planner_complete_count: int = 0
    terminal_reported_complete: bool = False
    world_complete: Optional[bool] = None
    world_status: str = "unknown"
    terminal_status: str = "not_reported_complete"
    outcome: str = "unknown"
    verification_source: str = "none"
    evidence: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    reason: str = ""
    ready_for_terminal_review: bool = False


@dataclass
class TerminalCommitmentReport:
    cases: list[TerminalCommitmentCase] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def goal_count(self) -> int:
        return len(self.cases)

    @property
    def ready_goal_count(self) -> int:
        return sum(1 for case in self.cases if case.ready_for_terminal_review)

    @property
    def world_complete_count(self) -> int:
        return sum(1 for case in self.cases if case.world_complete is True)

    @property
    def terminal_complete_count(self) -> int:
        return sum(1 for case in self.cases if case.terminal_reported_complete)

    @property
    def verified_success_count(self) -> int:
        return self._outcome_count("verified_success")

    @property
    def unsupported_commitment_count(self) -> int:
        return self._outcome_count("unsupported_commitment")

    @property
    def post_attainment_drift_count(self) -> int:
        return self._outcome_count("post_attainment_drift")

    @property
    def missed_execution_count(self) -> int:
        return self._outcome_count("missed_execution")

    @property
    def unknown_world_count(self) -> int:
        return sum(1 for case in self.cases if case.world_complete is None)

    @property
    def world_completion_score(self) -> float:
        return self._ratio(self.world_complete_count, self.goal_count)

    @property
    def terminal_commitment_score(self) -> float:
        return self._ratio(self.verified_success_count, self.goal_count)

    @property
    def unsupported_commitment_rate(self) -> float:
        return self._ratio(self.unsupported_commitment_count, self.goal_count)

    @property
    def post_attainment_drift_rate(self) -> float:
        return self._ratio(self.post_attainment_drift_count, self.goal_count)

    def _outcome_count(self, outcome: str) -> int:
        return sum(1 for case in self.cases if case.outcome == outcome)

    def _ratio(self, numerator: int, denominator: int) -> float:
        return round(numerator / denominator, 3) if denominator else 0.0


@dataclass
class ActionVerificationTraceCase:
    source_log: str
    event_count: int = 0
    observation_count: int = 0
    action_count: int = 0
    verified_action_count: int = 0
    accepted_action_count: int = 0
    review_action_count: int = 0
    rejected_action_count: int = 0
    rejected_success_count: int = 0
    failed_without_reject_count: int = 0
    status_counts: dict = field(default_factory=dict)
    action_type_counts: dict = field(default_factory=dict)
    rejection_reasons: dict = field(default_factory=dict)
    review_reasons: dict = field(default_factory=dict)
    examples: list[dict] = field(default_factory=list)
    ready_for_action_verification_review: bool = False


@dataclass
class ActionVerificationTraceReport:
    cases: list[ActionVerificationTraceCase] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def log_count(self) -> int:
        return len(self.cases)

    @property
    def ready_log_count(self) -> int:
        return sum(1 for case in self.cases if case.ready_for_action_verification_review)

    @property
    def action_count(self) -> int:
        return sum(case.action_count for case in self.cases)

    @property
    def verified_action_count(self) -> int:
        return sum(case.verified_action_count for case in self.cases)

    @property
    def accepted_action_count(self) -> int:
        return sum(case.accepted_action_count for case in self.cases)

    @property
    def review_action_count(self) -> int:
        return sum(case.review_action_count for case in self.cases)

    @property
    def rejected_action_count(self) -> int:
        return sum(case.rejected_action_count for case in self.cases)

    @property
    def rejected_success_count(self) -> int:
        return sum(case.rejected_success_count for case in self.cases)

    @property
    def failed_without_reject_count(self) -> int:
        return sum(case.failed_without_reject_count for case in self.cases)

    @property
    def reject_rate(self) -> float:
        return self._ratio(self.rejected_action_count, self.verified_action_count)

    @property
    def review_rate(self) -> float:
        return self._ratio(self.review_action_count, self.verified_action_count)

    def _ratio(self, numerator: int, denominator: int) -> float:
        return round(numerator / denominator, 3) if denominator else 0.0


@dataclass
class ActionCandidateSelectionTraceCase:
    source_log: str
    event_count: int = 0
    observation_count: int = 0
    action_count: int = 0
    candidate_action_count: int = 0
    original_reject_count: int = 0
    changed_selection_count: int = 0
    repaired_reject_count: int = 0
    unchanged_reject_count: int = 0
    selected_accept_count: int = 0
    selected_review_count: int = 0
    selected_reject_count: int = 0
    selected_action_type_counts: dict = field(default_factory=dict)
    repair_reasons: dict = field(default_factory=dict)
    examples: list[dict] = field(default_factory=list)
    ready_for_action_candidate_review: bool = False


@dataclass
class ActionCandidateSelectionTraceReport:
    cases: list[ActionCandidateSelectionTraceCase] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def log_count(self) -> int:
        return len(self.cases)

    @property
    def ready_log_count(self) -> int:
        return sum(1 for case in self.cases if case.ready_for_action_candidate_review)

    @property
    def action_count(self) -> int:
        return sum(case.action_count for case in self.cases)

    @property
    def original_reject_count(self) -> int:
        return sum(case.original_reject_count for case in self.cases)

    @property
    def changed_selection_count(self) -> int:
        return sum(case.changed_selection_count for case in self.cases)

    @property
    def repaired_reject_count(self) -> int:
        return sum(case.repaired_reject_count for case in self.cases)

    @property
    def unchanged_reject_count(self) -> int:
        return sum(case.unchanged_reject_count for case in self.cases)

    @property
    def selection_change_rate(self) -> float:
        return self._ratio(self.changed_selection_count, self.action_count)

    @property
    def repaired_reject_rate(self) -> float:
        return self._ratio(self.repaired_reject_count, self.original_reject_count)

    def _ratio(self, numerator: int, denominator: int) -> float:
        return round(numerator / denominator, 3) if denominator else 0.0


@dataclass
class ActionValueTraceCase:
    source_log: str
    event_count: int = 0
    goal_count: int = 0
    action_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    unknown_outcome_count: int = 0
    signature_count: int = 0
    high_value_count: int = 0
    low_value_count: int = 0
    action_value_items: list[dict] = field(default_factory=list)
    high_value_items: list[dict] = field(default_factory=list)
    low_value_items: list[dict] = field(default_factory=list)
    failure_correction_pairs: list[dict] = field(default_factory=list)
    state_transition_count: int = 0
    positive_transition_count: int = 0
    negative_transition_count: int = 0
    no_progress_transition_count: int = 0
    low_confidence_transition_count: int = 0
    state_transition_items: list[dict] = field(default_factory=list)
    ready_for_action_value_review: bool = False


@dataclass
class ActionValueTraceReport:
    cases: list[ActionValueTraceCase] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def log_count(self) -> int:
        return len(self.cases)

    @property
    def ready_log_count(self) -> int:
        return sum(1 for case in self.cases if case.ready_for_action_value_review)

    @property
    def action_count(self) -> int:
        return sum(case.action_count for case in self.cases)

    @property
    def success_count(self) -> int:
        return sum(case.success_count for case in self.cases)

    @property
    def failure_count(self) -> int:
        return sum(case.failure_count for case in self.cases)

    @property
    def unknown_outcome_count(self) -> int:
        return sum(case.unknown_outcome_count for case in self.cases)

    @property
    def signature_count(self) -> int:
        return len({item.get("signature") for case in self.cases for item in case.action_value_items if item.get("signature")})

    @property
    def failure_correction_pair_count(self) -> int:
        return sum(len(case.failure_correction_pairs) for case in self.cases)

    @property
    def state_transition_count(self) -> int:
        return sum(case.state_transition_count for case in self.cases)

    @property
    def positive_transition_count(self) -> int:
        return sum(case.positive_transition_count for case in self.cases)

    @property
    def negative_transition_count(self) -> int:
        return sum(case.negative_transition_count for case in self.cases)

    @property
    def no_progress_transition_count(self) -> int:
        return sum(case.no_progress_transition_count for case in self.cases)

    @property
    def low_confidence_transition_count(self) -> int:
        return sum(case.low_confidence_transition_count for case in self.cases)

    @property
    def success_rate(self) -> float:
        return self._ratio(self.success_count, self.action_count)

    @property
    def failure_rate(self) -> float:
        return self._ratio(self.failure_count, self.action_count)

    def _ratio(self, numerator: int, denominator: int) -> float:
        return round(numerator / denominator, 3) if denominator else 0.0


@dataclass
class KnowledgeCorrectionTraceCase:
    source_log: str
    event_count: int = 0
    goal_count: int = 0
    action_count: int = 0
    failure_action_count: int = 0
    repeated_failure_signature_count: int = 0
    recovery_pair_count: int = 0
    dependency_correction_count: int = 0
    failure_action_memory_count: int = 0
    low_confidence_transition_count: int = 0
    dependency_corrections: list[dict] = field(default_factory=list)
    failure_action_memories: list[dict] = field(default_factory=list)
    ready_for_knowledge_correction_review: bool = False


@dataclass
class KnowledgeCorrectionTraceReport:
    cases: list[KnowledgeCorrectionTraceCase] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def log_count(self) -> int:
        return len(self.cases)

    @property
    def ready_log_count(self) -> int:
        return sum(1 for case in self.cases if case.ready_for_knowledge_correction_review)

    @property
    def action_count(self) -> int:
        return sum(case.action_count for case in self.cases)

    @property
    def failure_action_count(self) -> int:
        return sum(case.failure_action_count for case in self.cases)

    @property
    def repeated_failure_signature_count(self) -> int:
        return sum(case.repeated_failure_signature_count for case in self.cases)

    @property
    def recovery_pair_count(self) -> int:
        return sum(case.recovery_pair_count for case in self.cases)

    @property
    def dependency_correction_count(self) -> int:
        return sum(case.dependency_correction_count for case in self.cases)

    @property
    def failure_action_memory_count(self) -> int:
        return sum(case.failure_action_memory_count for case in self.cases)

    @property
    def low_confidence_transition_count(self) -> int:
        return sum(case.low_confidence_transition_count for case in self.cases)


@dataclass
class DiscoveryApplicationTraceCase:
    source_log: str
    event_count: int = 0
    goal_count: int = 0
    completed_goal_count: int = 0
    failed_goal_count: int = 0
    hypothesis_count: int = 0
    experiment_count: int = 0
    consolidation_count: int = 0
    application_count: int = 0
    successful_application_count: int = 0
    failed_application_count: int = 0
    experiment_action_count: int = 0
    failed_experiment_action_count: int = 0
    memory_write_count: int = 0
    causal_memory_write_count: int = 0
    discovery_loop_count: int = 0
    complete_loop_count: int = 0
    phase_counts: dict = field(default_factory=dict)
    causal_rule_candidates: list[str] = field(default_factory=list)
    knowledge_gap_candidates: list[str] = field(default_factory=list)
    application_goals: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    ready_for_discovery_review: bool = False


@dataclass
class DiscoveryApplicationTraceReport:
    cases: list[DiscoveryApplicationTraceCase] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def log_count(self) -> int:
        return len(self.cases)

    @property
    def ready_log_count(self) -> int:
        return sum(1 for case in self.cases if case.ready_for_discovery_review)

    @property
    def goal_count(self) -> int:
        return sum(case.goal_count for case in self.cases)

    @property
    def completed_goal_count(self) -> int:
        return sum(case.completed_goal_count for case in self.cases)

    @property
    def hypothesis_count(self) -> int:
        return sum(case.hypothesis_count for case in self.cases)

    @property
    def experiment_count(self) -> int:
        return sum(case.experiment_count for case in self.cases)

    @property
    def consolidation_count(self) -> int:
        return sum(case.consolidation_count for case in self.cases)

    @property
    def application_count(self) -> int:
        return sum(case.application_count for case in self.cases)

    @property
    def successful_application_count(self) -> int:
        return sum(case.successful_application_count for case in self.cases)

    @property
    def failed_application_count(self) -> int:
        return sum(case.failed_application_count for case in self.cases)

    @property
    def experiment_action_count(self) -> int:
        return sum(case.experiment_action_count for case in self.cases)

    @property
    def failed_experiment_action_count(self) -> int:
        return sum(case.failed_experiment_action_count for case in self.cases)

    @property
    def causal_memory_write_count(self) -> int:
        return sum(case.causal_memory_write_count for case in self.cases)

    @property
    def complete_loop_count(self) -> int:
        return sum(case.complete_loop_count for case in self.cases)


@dataclass
class ActionAbstractionTraceCase:
    source_log: str
    action_count: int = 0
    failed_action_count: int = 0
    unknown_canonical_count: int = 0
    failed_mapping_count: int = 0
    desktop_planned_count: int = 0
    low_level_candidate_count: int = 0
    canonical_action_types: dict = field(default_factory=dict)
    result_backend_counts: dict = field(default_factory=dict)
    result_backend_command_counts: dict = field(default_factory=dict)
    mineflayer_command_counts: dict = field(default_factory=dict)
    desktop_command_counts: dict = field(default_factory=dict)
    lower_level_reasons: dict = field(default_factory=dict)
    lower_level_action_types: dict = field(default_factory=dict)
    task_recommendations: list[str] = field(default_factory=list)


@dataclass
class ActionAbstractionTraceReport:
    cases: list[ActionAbstractionTraceCase] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def log_count(self) -> int:
        return len(self.cases)

    @property
    def action_count(self) -> int:
        return sum(case.action_count for case in self.cases)

    @property
    def failed_action_count(self) -> int:
        return sum(case.failed_action_count for case in self.cases)

    @property
    def unknown_canonical_count(self) -> int:
        return sum(case.unknown_canonical_count for case in self.cases)

    @property
    def failed_mapping_count(self) -> int:
        return sum(case.failed_mapping_count for case in self.cases)

    @property
    def desktop_planned_count(self) -> int:
        return sum(case.desktop_planned_count for case in self.cases)

    @property
    def low_level_candidate_count(self) -> int:
        return sum(case.low_level_candidate_count for case in self.cases)


@dataclass
class MemoryPolicyTraceCase:
    source_log: str
    event_count: int = 0
    observation_count: int = 0
    plan_count: int = 0
    action_count: int = 0
    failed_action_count: int = 0
    goal_count: int = 0
    completed_goal_count: int = 0
    explicit_memory_write_count: int = 0
    explicit_memory_read_count: int = 0
    explicit_memory_manage_count: int = 0
    context_write_candidate_count: int = 0
    episodic_write_candidate_count: int = 0
    semantic_write_candidate_count: int = 0
    missed_semantic_write_count: int = 0
    failure_learning_candidate_count: int = 0
    consolidation_signal_count: int = 0
    noisy_write_candidate_count: int = 0
    missing_read_trace_count: int = 0
    read_filter_event_count: int = 0
    read_filtered_entry_count: int = 0
    read_filter_reasons: dict = field(default_factory=dict)
    write_operations: dict = field(default_factory=dict)
    read_queries: list[str] = field(default_factory=list)
    policy_hints: list[str] = field(default_factory=list)
    ready_for_memory_policy_review: bool = False


@dataclass
class MemoryPolicyTraceReport:
    cases: list[MemoryPolicyTraceCase] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def log_count(self) -> int:
        return len(self.cases)

    @property
    def ready_log_count(self) -> int:
        return sum(1 for case in self.cases if case.ready_for_memory_policy_review)

    @property
    def event_count(self) -> int:
        return sum(case.event_count for case in self.cases)

    @property
    def explicit_memory_write_count(self) -> int:
        return sum(case.explicit_memory_write_count for case in self.cases)

    @property
    def explicit_memory_read_count(self) -> int:
        return sum(case.explicit_memory_read_count for case in self.cases)

    @property
    def explicit_memory_manage_count(self) -> int:
        return sum(case.explicit_memory_manage_count for case in self.cases)

    @property
    def semantic_write_candidate_count(self) -> int:
        return sum(case.semantic_write_candidate_count for case in self.cases)

    @property
    def missed_semantic_write_count(self) -> int:
        return sum(case.missed_semantic_write_count for case in self.cases)

    @property
    def failure_learning_candidate_count(self) -> int:
        return sum(case.failure_learning_candidate_count for case in self.cases)

    @property
    def consolidation_signal_count(self) -> int:
        return sum(case.consolidation_signal_count for case in self.cases)

    @property
    def noisy_write_candidate_count(self) -> int:
        return sum(case.noisy_write_candidate_count for case in self.cases)

    @property
    def missing_read_trace_count(self) -> int:
        return sum(case.missing_read_trace_count for case in self.cases)

    @property
    def read_filter_event_count(self) -> int:
        return sum(case.read_filter_event_count for case in self.cases)

    @property
    def read_filtered_entry_count(self) -> int:
        return sum(case.read_filtered_entry_count for case in self.cases)

    @property
    def read_filter_reasons(self) -> dict:
        reasons = {}
        for case in self.cases:
            for reason, count in case.read_filter_reasons.items():
                reasons[reason] = reasons.get(reason, 0) + count
        return reasons


@dataclass
class BoundedPlanningContextCycle:
    cycle_index: int
    goal: str = ""
    plan_status: str = ""
    action_count: int = 0
    memory_read_count: int = 0
    typed_layer_count: int = 0
    total_result_chars: int = 0
    max_result_chars: int = 0
    has_relevant_memory: bool = False
    has_task_memory: bool = False
    has_context_window: bool = False
    read_layers: dict = field(default_factory=dict)
    read_types: dict = field(default_factory=dict)
    read_sources: dict = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)
    bounded_ok: bool = False


@dataclass
class BoundedPlanningContextCase:
    source_log: str
    event_count: int = 0
    plan_count: int = 0
    planning_cycle_count: int = 0
    bounded_cycle_count: int = 0
    unbounded_cycle_count: int = 0
    missing_read_cycle_count: int = 0
    oversized_read_cycle_count: int = 0
    oversized_cycle_count: int = 0
    raw_context_cycle_count: int = 0
    low_diversity_cycle_count: int = 0
    max_cycle_result_chars: int = 0
    total_result_chars: int = 0
    read_layers: dict = field(default_factory=dict)
    read_types: dict = field(default_factory=dict)
    read_sources: dict = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)
    cycles: list[BoundedPlanningContextCycle] = field(default_factory=list)
    ready_for_bounded_context_review: bool = False


@dataclass
class BoundedPlanningContextReport:
    max_read_chars: int = 1200
    max_cycle_chars: int = 2400
    cases: list[BoundedPlanningContextCase] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def log_count(self) -> int:
        return len(self.cases)

    @property
    def ready_log_count(self) -> int:
        return sum(1 for case in self.cases if case.ready_for_bounded_context_review)

    @property
    def planning_cycle_count(self) -> int:
        return sum(case.planning_cycle_count for case in self.cases)

    @property
    def bounded_cycle_count(self) -> int:
        return sum(case.bounded_cycle_count for case in self.cases)

    @property
    def unbounded_cycle_count(self) -> int:
        return sum(case.unbounded_cycle_count for case in self.cases)

    @property
    def missing_read_cycle_count(self) -> int:
        return sum(case.missing_read_cycle_count for case in self.cases)

    @property
    def oversized_read_cycle_count(self) -> int:
        return sum(case.oversized_read_cycle_count for case in self.cases)

    @property
    def oversized_cycle_count(self) -> int:
        return sum(case.oversized_cycle_count for case in self.cases)

    @property
    def raw_context_cycle_count(self) -> int:
        return sum(case.raw_context_cycle_count for case in self.cases)

    @property
    def low_diversity_cycle_count(self) -> int:
        return sum(case.low_diversity_cycle_count for case in self.cases)

    @property
    def read_layers(self) -> dict:
        counts = {}
        for case in self.cases:
            for key, value in case.read_layers.items():
                counts[key] = counts.get(key, 0) + int(value or 0)
        return counts

    @property
    def read_types(self) -> dict:
        counts = {}
        for case in self.cases:
            for key, value in case.read_types.items():
                counts[key] = counts.get(key, 0) + int(value or 0)
        return counts


@dataclass
class ContinualLearningTraceCase:
    source_log: str
    event_count: int = 0
    observation_count: int = 0
    goal_count: int = 0
    completed_goal_count: int = 0
    failed_goal_count: int = 0
    plan_count: int = 0
    action_count: int = 0
    successful_action_count: int = 0
    failed_action_count: int = 0
    unique_action_type_count: int = 0
    unique_action_target_count: int = 0
    action_entropy: float = 0.0
    memory_read_count: int = 0
    memory_write_count: int = 0
    episodic_write_count: int = 0
    semantic_write_count: int = 0
    consolidation_signal_count: int = 0
    bounded_cycle_count: int = 0
    unbounded_context_cycle_count: int = 0
    unique_position_count: int = 0
    path_distance: float = 0.0
    unique_cell_count: int = 0
    frontier_count: int = 0
    resource_hotspot_count: int = 0
    unique_block_type_count: int = 0
    unique_resource_type_count: int = 0
    unique_entity_type_count: int = 0
    unique_inventory_item_count: int = 0
    object_exploration_count: int = 0
    progress_event_count: int = 0
    meaningful_horizon_events: int = 0
    stagnation_tail_events: int = 0
    axis_scores: dict = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    ready_for_continual_learning_review: bool = False


@dataclass
class ContinualLearningTraceReport:
    cases: list[ContinualLearningTraceCase] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def log_count(self) -> int:
        return len(self.cases)

    @property
    def ready_log_count(self) -> int:
        return sum(1 for case in self.cases if case.ready_for_continual_learning_review)

    @property
    def event_count(self) -> int:
        return sum(case.event_count for case in self.cases)

    @property
    def observation_count(self) -> int:
        return sum(case.observation_count for case in self.cases)

    @property
    def action_count(self) -> int:
        return sum(case.action_count for case in self.cases)

    @property
    def failed_action_count(self) -> int:
        return sum(case.failed_action_count for case in self.cases)

    @property
    def completed_goal_count(self) -> int:
        return sum(case.completed_goal_count for case in self.cases)

    @property
    def failed_goal_count(self) -> int:
        return sum(case.failed_goal_count for case in self.cases)

    @property
    def progress_event_count(self) -> int:
        return sum(case.progress_event_count for case in self.cases)

    @property
    def object_exploration_count(self) -> int:
        return sum(case.object_exploration_count for case in self.cases)

    @property
    def memory_read_count(self) -> int:
        return sum(case.memory_read_count for case in self.cases)

    @property
    def memory_write_count(self) -> int:
        return sum(case.memory_write_count for case in self.cases)

    @property
    def unbounded_context_cycle_count(self) -> int:
        return sum(case.unbounded_context_cycle_count for case in self.cases)

    @property
    def average_axis_scores(self) -> dict:
        keys = sorted({key for case in self.cases for key in case.axis_scores})
        return {
            key: round(sum(case.axis_scores.get(key, 0.0) for case in self.cases) / len(self.cases), 3)
            for key in keys
        } if self.cases else {}


@dataclass
class TaskStreamTransferTask:
    stream_id: str
    task_id: str
    goal: str = ""
    stage: str = "task"
    source_file: str = ""
    source_log: str = ""
    depends_on: list[str] = field(default_factory=list)
    expected_reuse_tags: list[str] = field(default_factory=list)
    produced_tags: list[str] = field(default_factory=list)
    reuse_hit_tags: list[str] = field(default_factory=list)
    reuse_missing_tags: list[str] = field(default_factory=list)
    baseline_score: Optional[float] = None
    first_pass_score: Optional[float] = None
    second_pass_score: Optional[float] = None
    heldout_score: Optional[float] = None
    transfer_gain: Optional[float] = None
    stability_gain: Optional[float] = None
    generalization_gain: Optional[float] = None
    memory_read_count: int = 0
    memory_write_count: int = 0
    completed_goal_count: int = 0
    failed_goal_count: int = 0
    action_count: int = 0
    failed_action_count: int = 0
    issues: list[str] = field(default_factory=list)
    ready_for_transfer_review: bool = False


@dataclass
class TaskStreamTransferCase:
    stream_id: str
    source_file: str
    description: str = ""
    task_count: int = 0
    ready_task_count: int = 0
    reusable_relation_count: int = 0
    reuse_expected_tag_count: int = 0
    reuse_hit_tag_count: int = 0
    reuse_coverage: float = 0.0
    average_baseline_score: Optional[float] = None
    average_first_pass_score: Optional[float] = None
    average_second_pass_score: Optional[float] = None
    average_heldout_score: Optional[float] = None
    plasticity_gain: Optional[float] = None
    stability_gain: Optional[float] = None
    generalization_gain: Optional[float] = None
    interference_count: int = 0
    missing_baseline_count: int = 0
    missing_second_pass_count: int = 0
    missing_heldout_count: int = 0
    issues: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    tasks: list[TaskStreamTransferTask] = field(default_factory=list)
    ready_for_transfer_review: bool = False


@dataclass
class TaskStreamTransferReport:
    cases: list[TaskStreamTransferCase] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def stream_count(self) -> int:
        return len(self.cases)

    @property
    def ready_stream_count(self) -> int:
        return sum(1 for case in self.cases if case.ready_for_transfer_review)

    @property
    def task_count(self) -> int:
        return sum(case.task_count for case in self.cases)

    @property
    def reusable_relation_count(self) -> int:
        return sum(case.reusable_relation_count for case in self.cases)

    @property
    def reuse_expected_tag_count(self) -> int:
        return sum(case.reuse_expected_tag_count for case in self.cases)

    @property
    def reuse_hit_tag_count(self) -> int:
        return sum(case.reuse_hit_tag_count for case in self.cases)

    @property
    def reuse_coverage(self) -> float:
        if self.reuse_expected_tag_count <= 0:
            return 0.0
        return round(self.reuse_hit_tag_count / self.reuse_expected_tag_count, 3)

    @property
    def interference_count(self) -> int:
        return sum(case.interference_count for case in self.cases)

    @property
    def average_plasticity_gain(self) -> Optional[float]:
        return _average_optional(case.plasticity_gain for case in self.cases)

    @property
    def average_stability_gain(self) -> Optional[float]:
        return _average_optional(case.stability_gain for case in self.cases)

    @property
    def average_generalization_gain(self) -> Optional[float]:
        return _average_optional(case.generalization_gain for case in self.cases)


@dataclass
class ReviewLabelValidationCase:
    index: int
    label_type: str = "unknown"
    key: str = ""
    source_log: str = ""
    goal: str = ""
    candidate_id: str = ""
    candidate_name: str = ""
    raw_readiness: str = ""
    readiness: str = ""
    ok: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    raw_screenshot_count: int = 0
    screenshot_count: int = 0
    missing_screenshot_count: int = 0
    invalid_screenshot_count: int = 0
    screenshots: list[str] = field(default_factory=list)
    missing_screenshots: list[str] = field(default_factory=list)
    invalid_screenshots: list[str] = field(default_factory=list)


@dataclass
class ReviewLabelValidationReport:
    label_path: str
    cases: list[ReviewLabelValidationCase] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def label_count(self) -> int:
        return len(self.cases)

    @property
    def ok(self) -> bool:
        return not self.errors and all(case.ok for case in self.cases)

    @property
    def ok_count(self) -> int:
        return sum(1 for case in self.cases if case.ok)

    @property
    def invalid_readiness_count(self) -> int:
        return sum(1 for case in self.cases if "invalid_readiness" in case.errors)

    @property
    def unknown_readiness_count(self) -> int:
        return sum(1 for case in self.cases if case.readiness == "unknown")

    @property
    def screenshot_unverified_count(self) -> int:
        return sum(1 for case in self.cases if "screenshot_evidence_not_verified" in case.errors)

    @property
    def error_count(self) -> int:
        return len(self.errors) + sum(len(case.errors) for case in self.cases)


@dataclass
class VisualReviewPipelineReport:
    session_logs: list[str]
    mode: str = "both"
    label_file: str = ""
    run_ablations: bool = False
    visual_trace: VisualTraceCoverageReport = field(default_factory=VisualTraceCoverageReport)
    label_templates: list[dict] = field(default_factory=list)
    label_validation: Optional[ReviewLabelValidationReport] = None
    promotion_ablation: Optional[PromotionReviewAblationReport] = None
    goal_ablation: Optional[GoalVerificationAblationReport] = None
    visual_action_ablation: Optional[VisualActionAblationReport] = None
    errors: list[str] = field(default_factory=list)

    @property
    def template_count(self) -> int:
        return len(self.label_templates)

    @property
    def promotion_template_count(self) -> int:
        return sum(1 for template in self.label_templates if template.get("type") == "promotion_review")

    @property
    def goal_template_count(self) -> int:
        return sum(1 for template in self.label_templates if template.get("type") == "goal_verification")

    @property
    def error_template_count(self) -> int:
        return sum(1 for template in self.label_templates if template.get("type") == "error")

    @property
    def label_ok(self) -> bool:
        return self.label_validation is None or self.label_validation.ok

    @property
    def ready_for_manual_review(self) -> bool:
        return (
            self.visual_trace.ready_log_count > 0
            and self.template_count > 0
            and not self.visual_trace.errors
            and self.error_template_count == 0
        )

    @property
    def ready_for_agreement_ablation(self) -> bool:
        return self.label_validation is not None and self.label_validation.ok and self.ready_for_manual_review

    @property
    def ready(self) -> bool:
        if self.errors or self.visual_trace.errors or not self.label_ok:
            return False
        if self.run_ablations:
            if self.mode in {"promotion", "both"} and self.promotion_ablation is None:
                return False
            if self.mode in {"goal", "goal_verification", "both"} and self.goal_ablation is None:
                return False
            if self.visual_action_ablation is None:
                return False
            if self.promotion_ablation is not None and self.promotion_ablation.errors:
                return False
            if self.goal_ablation is not None and self.goal_ablation.errors:
                return False
        return self.ready_for_manual_review if not self.label_file else self.ready_for_agreement_ablation


M1_BENCHMARKS = [
    BenchmarkTask("BM-001", "Chop 3 oak logs", "Gather 3 oak logs", "M1",
                  timeout_cycles=50, success_criteria={"oak_log": 3}, min_inventory={"oak_log": 3}),
    BenchmarkTask("BM-002", "Craft workbench", "Craft a crafting table", "M1",
                  timeout_cycles=30, success_criteria={"crafting_table": 1}, min_inventory={"oak_planks": 4}),
    BenchmarkTask("BM-003", "Craft wooden pickaxe", "Craft a wooden pickaxe", "M1",
                  timeout_cycles=60, success_criteria={"wooden_pickaxe": 1}, min_inventory={"oak_planks": 3, "stick": 2}),
    BenchmarkTask("BM-004", "Mine cobblestone", "Mine 3 cobblestone blocks", "M1",
                  timeout_cycles=40, success_criteria={"cobblestone": 3}),
    BenchmarkTask("BM-005", "Craft stone tools", "Craft a stone pickaxe", "M1",
                  timeout_cycles=80, success_criteria={"stone_pickaxe": 1}),
]

M2_BENCHMARKS = [
    BenchmarkTask("BM-006", "Gather wood and craft workbench", "Gather oak wood and craft a crafting table", "M2",
                  timeout_cycles=80, success_criteria={"crafting_table": 1}),
    BenchmarkTask("BM-007", "Wooden pickaxe + cobblestone", "Craft a wooden pickaxe and mine 3 cobblestone", "M2",
                  timeout_cycles=120, success_criteria={"cobblestone": 3}),
    BenchmarkTask("BM-008", "Stone tool progression", "Craft stone pickaxe and stone axe", "M2",
                  timeout_cycles=150, success_criteria={"stone_pickaxe": 1, "stone_axe": 1}),
    BenchmarkTask("BM-009", "Gather and store", "Gather 16 oak logs and store in a chest", "M2",
                  timeout_cycles=200, success_criteria={"oak_log": 16}),
    BenchmarkTask("BM-010", "Night survival prep", "Build a shelter and craft a bed before nightfall", "M2",
                  timeout_cycles=300, success_criteria={"bed": 1}),
]

SCHEDULING_ABLATION_CASES = [
    SchedulingAblationCase(
        id="AB-SCHED-001",
        name="Causal memory rescues a latent coal opportunity",
        world_state={
            "inventory": {"stick": 1},
            "nearby_blocks": [],
            "nearby_entities": [],
            "causal_tags": ["coal", "torch", "craft"],
        },
        tasks=[
            {"title": "Explore surroundings", "priority": 3},
            {
                "title": "Craft torches from remembered coal opportunity",
                "priority": 3,
                "preconditions": {"inventory": {"stick": 1}},
                "opportunity_triggers": ["coal"],
            },
        ],
        expected_causal_task="Craft torches from remembered coal opportunity",
    ),
    SchedulingAblationCase(
        id="AB-SCHED-002",
        name="Direct visible coal remains sufficient without causal memory",
        world_state={
            "inventory": {"stick": 1},
            "nearby_blocks": [],
            "grounded_resources": [{"name": "coal_ore", "drop": "coal", "can_harvest": True}],
            "nearby_entities": [],
            "causal_tags": ["coal", "torch", "craft"],
        },
        tasks=[
            {"title": "Explore surroundings", "priority": 3},
            {
                "title": "Craft torches from visible coal",
                "priority": 3,
                "preconditions": {"inventory": {"stick": 1}},
                "opportunity_triggers": ["coal"],
            },
        ],
        expected_causal_task="Craft torches from visible coal",
    ),
    SchedulingAblationCase(
        id="AB-SCHED-003",
        name="Unrelated causal memory should not reorder tasks",
        world_state={
            "inventory": {"stick": 1},
            "nearby_blocks": [],
            "nearby_entities": [],
            "causal_tags": ["sheep", "wool"],
        },
        tasks=[
            {"title": "Explore surroundings", "priority": 3},
            {
                "title": "Craft torches when coal matters",
                "priority": 3,
                "preconditions": {"inventory": {"stick": 1}},
                "opportunity_triggers": ["coal"],
            },
        ],
        expected_causal_task="Explore surroundings",
    ),
]


COACH_STYLE_ABLATION_CASES = [
    CoachStyleAblationCase(
        id="AB-COACH-001",
        name="Explorer style promotes a mapped frontier over local resource grind",
        observation={
            "health": 20,
            "time_of_day": 4000,
            "inventory": {"crafting_table": 1, "wooden_pickaxe": 1, "oak_log": 4},
            "nearby_entities": [],
            "nearby_blocks": [],
        },
        fallback_goal="Explore surroundings and gather resources",
        styles=["safe", "explorer", "resourceful"],
        world_model_feedback={
            "frontier_count": 0,
            "suggested_goals": ["Explore east frontier cell (1,0) near x=12, z=4"],
            "frontiers": [{"cell": {"x": 1, "z": 0}, "direction": "east"}],
        },
    ),
    CoachStyleAblationCase(
        id="AB-COACH-002",
        name="Safe style reinforces torch preparation under danger pressure",
        observation={
            "health": 8,
            "time_of_day": 13000,
            "inventory": {"crafting_table": 1, "wooden_pickaxe": 1, "coal": 1, "stick": 1, "oak_log": 4},
            "nearby_entities": [{"name": "zombie", "hostile": True, "distance": 6}],
            "nearby_blocks": [],
        },
        fallback_goal="Explore nearby cave",
        styles=["safe", "explorer"],
    ),
    CoachStyleAblationCase(
        id="AB-COACH-003",
        name="Efficient style favors immediate tool progression",
        observation={
            "health": 20,
            "time_of_day": 4000,
            "inventory": {"crafting_table": 1, "cobblestone": 3, "stick": 2, "oak_log": 4},
            "nearby_entities": [],
            "nearby_blocks": [],
        },
        fallback_goal="Explore surroundings and gather resources",
        styles=["efficient", "builder"],
    ),
]


POLICY_SKILL_ABLATION_CASES = [
    PolicySkillAblationCase(
        id="AB-POLICY-001",
        name="Correct missing coal before torch crafting",
        goal="Craft torches",
        world_state={
            "inventory": {"stick": 1},
            "nearby_blocks": [{"name": "coal_ore"}],
            "nearby_entities": [],
            "position": {"x": 0, "y": 64, "z": 0},
        },
        failed_action={"type": "craft", "parameters": {"item": "torch"}},
        failed_result={"success": False, "error": "Missing coal", "action_type": "craft"},
        skill_name="correct_craft_torch_via_dig_coal_ore",
        skill_description="Correct missing coal before crafting torches",
        skill_implementation={
            "type": "failure_correction_skill",
            "avoid_action_template": {"type": "craft", "parameters": {"item": "torch"}},
            "primary_correction": {"type": "dig", "parameters": {"block": "coal_ore"}},
            "correction_sequence": [
                {"type": "dig", "parameters": {"block": "coal_ore"}},
                {"type": "craft", "parameters": {"item": "torch"}},
            ],
            "evidence": {"failure_why": "Missing coal"},
        },
    ),
]


VISUAL_ACTION_ABLATION_CASES = [
    VisualActionAblationCase(
        id="AB-VISACT-001",
        name="Fill missing dig coordinates from visible ore",
        goal="mine iron ore",
        observation={
            "grounded_resources": [{
                "name": "iron_ore",
                "can_harvest": True,
                "best_available_tool": "stone_pickaxe",
                "required_tool_tier": 2,
                "position": {"x": 3, "y": 64, "z": 4},
            }],
        },
        plan={
            "status": "in_progress",
            "reasoning": "dig visible ore",
            "actions": [{"type": "dig", "parameters": {}}],
        },
        expected_phase="fill_coordinates",
    ),
    VisualActionAblationCase(
        id="AB-VISACT-002",
        name="Approach far visible ore before digging",
        goal="mine iron ore",
        observation={
            "position": {"x": 0, "y": 64, "z": 0},
            "grounded_resources": [{
                "name": "iron_ore",
                "can_harvest": True,
                "best_available_tool": "stone_pickaxe",
                "required_tool_tier": 2,
                "position": {"x": 10, "y": 64, "z": 0},
            }],
        },
        plan={
            "status": "in_progress",
            "reasoning": "mine visible ore",
            "actions": [{"type": "dig", "parameters": {"x": 10, "y": 64, "z": 0}}],
        },
        expected_phase="prepend_approach",
    ),
    VisualActionAblationCase(
        id="AB-VISACT-003",
        name="Retreat from nearby hostile before waiting",
        goal="mine iron ore",
        observation={
            "position": {"x": 0, "y": 64, "z": 0},
            "nearby_entities": [{
                "type": "zombie",
                "hostile": True,
                "distance": 3,
                "position": {"x": 4, "y": 64, "z": 0},
            }],
        },
        plan={
            "status": "in_progress",
            "reasoning": "keep mining",
            "actions": [{"type": "wait", "parameters": {"ticks": 20}}],
        },
        expected_phase="prepend_danger",
    ),
    VisualActionAblationCase(
        id="AB-VISACT-004",
        name="Do not mine unrelated visible wood for iron goal",
        goal="mine iron ore",
        observation={
            "grounded_resources": [{
                "name": "oak_log",
                "can_harvest": True,
                "best_available_tool": "hand",
                "position": {"x": 5, "y": 66, "z": 7},
            }],
        },
        plan={
            "status": "in_progress",
            "reasoning": "wait for relevant target",
            "actions": [{"type": "wait", "parameters": {"ticks": 20}}],
        },
        expected_enabled_changed=False,
    ),
    VisualActionAblationCase(
        id="AB-VISACT-005",
        name="Look at nearby visible ore before digging",
        goal="mine iron ore",
        observation={
            "position": {"x": 2, "y": 64, "z": 0},
            "grounded_resources": [{
                "name": "iron_ore",
                "can_harvest": True,
                "best_available_tool": "stone_pickaxe",
                "required_tool_tier": 2,
                "position": {"x": 3, "y": 64, "z": 0},
            }],
        },
        plan={
            "status": "in_progress",
            "reasoning": "mine visible ore",
            "actions": [{"type": "dig", "parameters": {"x": 3, "y": 64, "z": 0}}],
        },
        expected_phase="prepend_focus",
    ),
]


class _PolicySkillAblationObserver:
    def __init__(self, state: dict):
        self.state = state

    def observe(self) -> dict:
        return json.loads(json.dumps(self.state, default=str))


class _PolicySkillAblationActionController:
    def __init__(self, state: dict):
        self.state = state
        self.actions: list[dict] = []

    def execute(self, action: dict, world_state: dict) -> dict:
        self.actions.append(action)
        params = action.get("parameters", {}) if isinstance(action.get("parameters", {}), dict) else {}
        action_type = action.get("type", "")
        inventory = self.state.setdefault("inventory", {})
        if action_type == "dig" and params.get("block"):
            block = params.get("block")
            drop = "coal" if block == "coal_ore" else block
            inventory[drop] = inventory.get(drop, 0) + 1
            return {"success": True, "action_type": "dig", "block": block}
        if action_type == "craft" and params.get("item") == "torch":
            if inventory.get("coal", 0) > 0 and inventory.get("stick", 0) > 0:
                inventory["coal"] -= 1
                inventory["stick"] -= 1
                inventory["torch"] = inventory.get("torch", 0) + 4
                return {"success": True, "action_type": "craft", "item": "torch"}
            return {"success": False, "action_type": "craft", "item": "torch", "error": "Missing coal"}
        return {"success": True, "action_type": action_type}


class _PolicySkillAblationExplorer:
    def record_position(self, position: dict):
        pass


class _PolicySkillAblationRuntime:
    class Decision:
        should_interrupt = False

    def evaluate_interrupt(self, observation: dict, goal: str = "", active_task=None):
        return self.Decision()


@dataclass
class BenchmarkResult:
    task_id: str
    task_name: str
    status: str  # pass, fail, timeout, error
    cycles_used: int = 0
    duration_s: float = 0.0
    inventory_snapshot: dict = field(default_factory=dict)
    intervention_metrics: dict = field(default_factory=dict)
    memory_policy_metrics: dict = field(default_factory=dict)
    error: str = ""
    session_log_path: str = ""


@dataclass
class BenchmarkIngestionReport:
    processed_results: int = 0
    skipped_results: int = 0
    experience_atoms: int = 0
    skill_candidates: int = 0
    queued_candidate_ids: list[str] = field(default_factory=list)
    promotion_reports: list[dict] = field(default_factory=list)
    promotion_decisions: dict[str, int] = field(default_factory=dict)
    promotion_statuses: dict[str, int] = field(default_factory=dict)
    promotion_readiness: dict[str, int] = field(default_factory=lambda: {
        "approved": 0,
        "rejected": 0,
        "unknown": 0,
    })
    errors: list[str] = field(default_factory=list)

    def record_promotion_report(self, report: dict):
        """Record an auditable skill-promotion validation report."""
        self.promotion_reports.append(report)

        decision = str(report.get("decision") or "unknown")
        status = str(report.get("status") or "unknown")
        self.promotion_decisions[decision] = self.promotion_decisions.get(decision, 0) + 1
        self.promotion_statuses[status] = self.promotion_statuses.get(status, 0) + 1

        if decision == "reject":
            readiness = "rejected"
        elif status == "unknown":
            readiness = "unknown"
        else:
            readiness = "approved"
        self.promotion_readiness[readiness] = self.promotion_readiness.get(readiness, 0) + 1


@dataclass
class PreflightCheck:
    name: str
    status: str  # pass, warn, fail
    detail: str = ""
    remedy: str = ""


@dataclass
class PreflightReport:
    ok: bool
    checks: list[PreflightCheck] = field(default_factory=list)


@dataclass
class ScreenshotSmokeReport:
    bridge_host: str
    bridge_port: int
    requested_path: str
    connected: bool = False
    capture_success: bool = False
    supported: bool = False
    screenshot_path: str = ""
    source: str = ""
    file_status: str = "missing"
    file_exists: bool = False
    file_valid: bool = False
    file_size: int = 0
    error: str = ""
    remedy: str = ""
    bridge_response: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.connected and self.capture_success and self.supported and self.file_valid


class BenchmarkRunner:
    """Runs benchmark tasks against the agent and records results."""

    def __init__(self, config: Config, output_dir: str = "logs/benchmarks", bridge_factory=None):
        self.config = config
        self.output_dir = output_dir
        self.results: list[BenchmarkResult] = []
        self.bridge_factory = bridge_factory or BotBridge

    def run_task(self, task: BenchmarkTask) -> BenchmarkResult:
        """Run a single benchmark task."""
        logger.info(f"Running benchmark {task.id}: {task.name}")
        agent = Agent(self.config)
        start = time.time()

        if not agent.connect():
            return BenchmarkResult(task.id, task.name, "error", error="Connection failed")

        try:
            result = agent.run_goal(task.goal)
            duration = time.time() - start
            inventory = agent.bot.get_inventory()
            inv_summary = {}
            for item in inventory:
                name = item.get("name", "unknown")
                inv_summary[name] = inv_summary.get(name, 0) + item.get("count", 1)

            passed = self._check_success(inv_summary, task.success_criteria)
            status = "pass" if passed else "fail"
            session_summary = result.get("summary", {})

            bench_result = BenchmarkResult(
                task_id=task.id, task_name=task.name, status=status,
                cycles_used=result.get("cycles", 0), duration_s=round(duration, 2),
                inventory_snapshot=inv_summary,
                intervention_metrics=session_summary.get("intervention_metrics", {}),
                memory_policy_metrics=session_summary.get("memory_policy_metrics", {}),
                session_log_path=session_summary.get("log_path", ""),
            )
        except Exception as e:
            bench_result = BenchmarkResult(task.id, task.name, "error", error=str(e))
        finally:
            agent.disconnect()

        self.results.append(bench_result)
        logger.info(f"  {task.id}: {bench_result.status} ({bench_result.duration_s}s, {bench_result.cycles_used} cycles)")
        return bench_result

    def run_suite(self, tasks: list[BenchmarkTask]) -> list[BenchmarkResult]:
        """Run a suite of benchmark tasks."""
        results = []
        for task in tasks:
            result = self.run_task(task)
            results.append(result)
        return results

    def run_m1_suite(self) -> list[BenchmarkResult]:
        return self.run_suite(M1_BENCHMARKS)

    def run_m2_suite(self) -> list[BenchmarkResult]:
        return self.run_suite(M2_BENCHMARKS)

    def tasks_for_suite(self, suite: str) -> list[BenchmarkTask]:
        if suite == "m1":
            return M1_BENCHMARKS
        if suite == "m2":
            return M2_BENCHMARKS
        if suite == "all":
            return M1_BENCHMARKS + M2_BENCHMARKS
        raise ValueError(f"Unknown benchmark suite: {suite}")

    def run_policy_skill_benchmark_ablation(
        self,
        tasks: Optional[list[BenchmarkTask]] = None,
        suite: str = "m1",
    ) -> PolicySkillBenchmarkAblationReport:
        """Run live benchmark tasks with reviewed policy skills disabled and enabled."""
        report = PolicySkillBenchmarkAblationReport()
        source_tasks = tasks if tasks is not None else self.tasks_for_suite(suite)
        for task in source_tasks:
            disabled = self._run_task_with_config(task, replace(self.config, enable_policy_skills=False))
            enabled = self._run_task_with_config(task, replace(self.config, enable_policy_skills=True))
            disabled_interventions = self._policy_intervention_count(disabled)
            enabled_interventions = self._policy_intervention_count(enabled)
            report.cases.append(PolicySkillBenchmarkAblationResult(
                task_id=task.id,
                task_name=task.name,
                disabled_status=disabled.status,
                enabled_status=enabled.status,
                disabled_duration_s=disabled.duration_s,
                enabled_duration_s=enabled.duration_s,
                disabled_interventions=disabled_interventions,
                enabled_interventions=enabled_interventions,
                enabled_success_rate=enabled.intervention_metrics.get("policy_intervention_success_rate", 0.0),
                enabled_helped=disabled.status != "pass" and enabled.status == "pass",
                disabled_log=disabled.session_log_path,
                enabled_log=enabled.session_log_path,
            ))
        return report

    def run_skill_memory_benchmark_ablation(
        self,
        tasks: Optional[list[BenchmarkTask]] = None,
        suite: str = "m1",
    ) -> SkillMemoryBenchmarkAblationReport:
        """Run policy-skill-enabled tasks with skill-memory context disabled versus enabled."""
        report = SkillMemoryBenchmarkAblationReport()
        source_tasks = tasks if tasks is not None else self.tasks_for_suite(suite)
        for task in source_tasks:
            baseline = self._run_task_with_config(task, replace(
                self.config,
                enable_policy_skills=True,
                enable_skill_memory_context=False,
            ))
            enabled = self._run_task_with_config(task, replace(
                self.config,
                enable_policy_skills=True,
                enable_skill_memory_context=True,
            ))
            baseline_hints = self._skill_memory_hint_count(baseline)
            enabled_hints = self._skill_memory_hint_count(enabled)
            enabled_changed = (
                baseline.status != enabled.status
                or baseline_hints != enabled_hints
                or baseline.inventory_snapshot != enabled.inventory_snapshot
            )
            enabled_helped = (
                baseline.status != "pass" and enabled.status == "pass"
            ) or (
                enabled_hints > baseline_hints and enabled.status == baseline.status
            )
            report.cases.append(SkillMemoryBenchmarkAblationResult(
                task_id=task.id,
                task_name=task.name,
                baseline_status=baseline.status,
                enabled_status=enabled.status,
                baseline_duration_s=baseline.duration_s,
                enabled_duration_s=enabled.duration_s,
                baseline_skill_memory_hints=baseline_hints,
                enabled_skill_memory_hints=enabled_hints,
                enabled_changed=enabled_changed,
                enabled_helped=enabled_helped,
                baseline_log=baseline.session_log_path,
                enabled_log=enabled.session_log_path,
            ))
        return report

    def run_visual_action_benchmark_ablation(
        self,
        tasks: Optional[list[BenchmarkTask]] = None,
        suite: str = "m1",
    ) -> VisualActionBenchmarkAblationReport:
        """Run live benchmark tasks with visual action grounding disabled and enabled."""
        report = VisualActionBenchmarkAblationReport()
        source_tasks = tasks if tasks is not None else self.tasks_for_suite(suite)
        for task in source_tasks:
            disabled = self._run_task_with_config(task, replace(self.config, enable_visual_action_grounding=False))
            enabled = self._run_task_with_config(task, replace(self.config, enable_visual_action_grounding=True))
            disabled_visual_actions = self._visual_action_intervention_count(disabled)
            enabled_visual_actions = self._visual_action_intervention_count(enabled)
            enabled_changed = (
                disabled.status != enabled.status
                or disabled_visual_actions != enabled_visual_actions
                or disabled.inventory_snapshot != enabled.inventory_snapshot
            )
            enabled_helped = (
                disabled.status != "pass" and enabled.status == "pass"
            ) or (
                enabled_visual_actions > disabled_visual_actions and enabled.status == disabled.status
            )
            report.cases.append(VisualActionBenchmarkAblationResult(
                task_id=task.id,
                task_name=task.name,
                disabled_status=disabled.status,
                enabled_status=enabled.status,
                disabled_duration_s=disabled.duration_s,
                enabled_duration_s=enabled.duration_s,
                disabled_visual_actions=disabled_visual_actions,
                enabled_visual_actions=enabled_visual_actions,
                enabled_changed=enabled_changed,
                enabled_helped=enabled_helped,
                enabled_phases=enabled.intervention_metrics.get("visual_action_intervention_phases", {}),
                disabled_log=disabled.session_log_path,
                enabled_log=enabled.session_log_path,
            ))
        return report

    def run_mixed_policy_benchmark_ablation(
        self,
        patch_paths: list[str],
        tasks: Optional[list[BenchmarkTask]] = None,
        suite: str = "m1",
    ) -> MixedPolicyBenchmarkAblationReport:
        """Run live benchmark tasks without and with approved mixed-policy patches."""
        from singularity.evaluation.mixed_initiative import build_mixed_initiative_policy_ablation

        clean_paths = [path for path in patch_paths if path]
        policy_report = build_mixed_initiative_policy_ablation(patch_paths=clean_paths)
        report = MixedPolicyBenchmarkAblationReport(
            patch_paths=clean_paths,
            policy_decision_report=policy_report.to_dict(),
        )
        source_tasks = tasks if tasks is not None else self.tasks_for_suite(suite)
        for task in source_tasks:
            baseline = self._run_task_with_config(task, replace(self.config, mixed_policy_patch_paths=[]))
            patched = self._run_task_with_config(task, replace(self.config, mixed_policy_patch_paths=clean_paths))
            baseline_control = self._control_policy_summary_from_log(baseline.session_log_path)
            patched_control = self._control_policy_summary_from_log(patched.session_log_path)
            patched_changed = (
                baseline.status != patched.status
                or baseline.inventory_snapshot != patched.inventory_snapshot
                or baseline_control != patched_control
            )
            patched_helped = baseline.status != "pass" and patched.status == "pass"
            report.cases.append(MixedPolicyBenchmarkAblationResult(
                task_id=task.id,
                task_name=task.name,
                baseline_status=baseline.status,
                patched_status=patched.status,
                baseline_duration_s=baseline.duration_s,
                patched_duration_s=patched.duration_s,
                baseline_control_policy=baseline_control,
                patched_control_policy=patched_control,
                patched_changed=patched_changed,
                patched_helped=patched_helped,
                baseline_log=baseline.session_log_path,
                patched_log=patched.session_log_path,
            ))
        return report

    def run_skill_memory_quality_preflight(
        self,
        tasks: Optional[list[BenchmarkTask]] = None,
        suite: str = "m1",
        feedback_paths: Optional[list[str]] = None,
        gate_paths: Optional[list[str]] = None,
        skill_storage_path: str = "",
        limit: int = 5,
    ) -> dict:
        """Check quality feedback gates and offline ranking effects before live benchmarks."""
        from singularity.core.skill_library import SkillLibrary

        clean_feedback_paths = [
            path for path in (
                feedback_paths
                if feedback_paths is not None
                else getattr(self.config, "skill_memory_quality_feedback_paths", [])
            ) or []
            if path
        ]
        clean_gate_paths = [
            path for path in (
                gate_paths
                if gate_paths is not None
                else getattr(self.config, "skill_memory_quality_gate_paths", [])
            ) or []
            if path
        ]
        storage_path = skill_storage_path or getattr(self.config, "skill_dir", "workspace/skills")
        report = {
            "required": bool(clean_feedback_paths),
            "ready": not bool(clean_feedback_paths),
            "readiness": "not_required" if not clean_feedback_paths else "review",
            "decision": "skip_quality_feedback_preflight" if not clean_feedback_paths else "hold_quality_feedback_benchmark",
            "reason": "no skill-memory quality feedback configured",
            "suite": suite,
            "skill_storage_path": storage_path,
            "feedback_paths": list(clean_feedback_paths),
            "gate_paths": list(clean_gate_paths),
            "feedback_count": 0,
            "gate_count": 0,
            "gate_readiness": "not_required",
            "gate_approved": not bool(clean_feedback_paths),
            "case_count": 0,
            "changed_count": 0,
            "quality_policy_application_count": 0,
            "feedback_policy_hint_count": 0,
            "feedback_hint_quality_item_count": 0,
            "cases": [],
            "quality_ablation": {},
            "gate_reports": [],
            "checks": [],
            "missing": [],
            "errors": [],
        }
        if not clean_feedback_paths:
            report["checks"].append(self._gate_check(
                "benchmark",
                "skill_memory_quality_preflight",
                "pass",
                "no quality feedback is configured for this benchmark",
                {"feedback_paths": 0},
            ))
            return report

        if not getattr(self.config, "enable_skill_memory_context", True):
            report["missing"].append("skill_memory_context_enabled")
            report["checks"].append(self._gate_check(
                "benchmark",
                "skill_memory_context",
                "warn",
                "skill-memory context is disabled, so quality feedback cannot affect retrieval",
                {"enabled": 0},
            ))

        feedback_items = self._load_gate_payloads(
            [],
            clean_feedback_paths,
            report["errors"],
            "skill_memory_quality_feedback",
        )
        report["feedback_count"] = len(feedback_items)
        feedback = self._merge_skill_memory_quality_feedback_items(feedback_items)
        report["feedback_policy_hint_count"] = len(feedback.get("policy_hints", []))
        report["feedback_hint_quality_item_count"] = len(feedback.get("hint_quality_items", []))
        if not feedback_items:
            report["missing"].append("skill_memory_quality_feedback")
        if not feedback.get("policy_hints") and not feedback.get("hint_quality_items"):
            report["missing"].append("actionable_skill_memory_quality_feedback")

        gate_items = self._load_gate_payloads(
            [],
            clean_gate_paths,
            report["errors"],
            "skill_memory_quality_gate",
        )
        report["gate_count"] = len(gate_items)
        self._attach_skill_memory_quality_preflight_gates(report, gate_items)

        try:
            skill_library = SkillLibrary(storage_path=storage_path, persist=True)
            source_tasks = tasks if tasks is not None else self.tasks_for_suite(suite)
            cases = self._skill_memory_quality_preflight_cases(source_tasks, skill_library)
            report["cases"] = cases
            report["case_count"] = len(cases)
            if not cases:
                report["missing"].append("benchmark_cases")
            if feedback_items and cases:
                ablation = skill_library.skill_memory_quality_ablation(feedback, cases, limit=limit)
                report["quality_ablation"] = ablation
                report["changed_count"] = int(ablation.get("changed_count", 0) or 0)
                report["quality_policy_application_count"] = int(
                    ablation.get("quality_policy_application_count", 0) or 0
                )
                status = "pass" if report["quality_policy_application_count"] else "warn"
                detail = (
                    "quality feedback affects current skill-memory ranking candidates"
                    if report["quality_policy_application_count"]
                    else "quality feedback did not affect current skill-memory ranking candidates"
                )
                report["checks"].append(self._gate_check(
                    "skill_memory_quality_ablation",
                    "offline_ranking_effect",
                    status,
                    detail,
                    {
                        "case_count": report["case_count"],
                        "changed_count": report["changed_count"],
                        "quality_policy_application_count": report["quality_policy_application_count"],
                    },
                ))
        except Exception as e:
            report["errors"].append(f"skill_memory_quality_preflight: {e}")

        if report["errors"]:
            report["readiness"] = "error"
            report["decision"] = "block_quality_feedback_benchmark"
            report["reason"] = "skill-memory quality preflight inputs could not be loaded"
        elif report["missing"]:
            report["readiness"] = "review"
            report["decision"] = "hold_quality_feedback_benchmark"
            report["reason"] = "skill-memory quality preflight is missing required evidence"
        elif not report["gate_approved"]:
            report["readiness"] = report["gate_readiness"] or "review"
            report["decision"] = "block_quality_feedback_benchmark"
            report["reason"] = "quality feedback gate is not approved"
        elif report["quality_policy_application_count"] <= 0:
            report["readiness"] = "review"
            report["decision"] = "hold_quality_feedback_benchmark"
            report["reason"] = "quality feedback has no observable effect on current skill-memory rankings"
        else:
            report["ready"] = True
            report["readiness"] = "approved"
            report["decision"] = "allow_quality_feedback_benchmark"
            report["reason"] = "approved gates and offline ranking effects are present"
        report["ready"] = report["readiness"] in {"approved", "not_required"}
        return report

    def run_knowledge_correction_preflight(
        self,
        tasks: Optional[list[BenchmarkTask]] = None,
        suite: str = "m1",
        feedback_paths: Optional[list[str]] = None,
        gate_paths: Optional[list[str]] = None,
    ) -> dict:
        """Check knowledge-correction gates and suite coverage before live benchmarks."""
        from singularity.core.skill_library import SkillLibrary

        clean_feedback_paths = [
            path for path in (
                feedback_paths
                if feedback_paths is not None
                else getattr(self.config, "knowledge_correction_feedback_paths", [])
            ) or []
            if path
        ]
        clean_gate_paths = [
            path for path in (
                gate_paths
                if gate_paths is not None
                else getattr(self.config, "knowledge_correction_gate_paths", [])
            ) or []
            if path
        ]
        report = {
            "type": "knowledge_correction_preflight",
            "required": bool(clean_feedback_paths),
            "ready": not bool(clean_feedback_paths),
            "readiness": "not_required" if not clean_feedback_paths else "review",
            "decision": "skip_knowledge_correction_preflight" if not clean_feedback_paths else "hold_knowledge_correction_benchmark",
            "reason": "no knowledge-correction feedback configured",
            "suite": suite,
            "feedback_paths": list(clean_feedback_paths),
            "gate_paths": list(clean_gate_paths),
            "feedback_count": 0,
            "gate_count": 0,
            "gate_readiness": "not_required",
            "gate_approved": not bool(clean_feedback_paths),
            "dependency_correction_count": 0,
            "failure_action_memory_count": 0,
            "policy_hint_count": 0,
            "case_count": 0,
            "matched_case_count": 0,
            "matched_dependency_correction_count": 0,
            "matched_failure_action_memory_count": 0,
            "coverage_rate": 0.0,
            "cases": [],
            "gate_reports": [],
            "checks": [],
            "missing": [],
            "errors": [],
        }
        if not clean_feedback_paths:
            report["checks"].append(self._gate_check(
                "benchmark",
                "knowledge_correction_preflight",
                "pass",
                "no knowledge-correction feedback is configured for this benchmark",
                {"feedback_paths": 0},
            ))
            return report

        if not getattr(self.config, "enable_knowledge_correction_context", True):
            report["missing"].append("knowledge_correction_context_enabled")
            report["checks"].append(self._gate_check(
                "benchmark",
                "knowledge_correction_context",
                "warn",
                "knowledge-correction context is disabled, so feedback cannot affect planner prompts",
                {"enabled": 0},
            ))

        feedback_items = self._load_gate_payloads(
            [],
            clean_feedback_paths,
            report["errors"],
            "knowledge_correction_feedback",
        )
        report["feedback_count"] = len(feedback_items)
        feedback = self._merge_knowledge_correction_feedback_items(feedback_items)
        dependency_corrections = feedback.get("dependency_corrections", [])
        failure_memories = feedback.get("failure_action_memories", [])
        report["dependency_correction_count"] = len(dependency_corrections)
        report["failure_action_memory_count"] = len(failure_memories)
        report["policy_hint_count"] = len(feedback.get("policy_hints", []))
        if not feedback_items:
            report["missing"].append("knowledge_correction_feedback")
        if not dependency_corrections and not failure_memories:
            report["missing"].append("actionable_knowledge_corrections")

        gate_items = self._load_gate_payloads(
            [],
            clean_gate_paths,
            report["errors"],
            "knowledge_correction_gate",
        )
        report["gate_count"] = len(gate_items)
        self._attach_knowledge_correction_preflight_gates(report, gate_items)

        try:
            skill_library = SkillLibrary(storage_path=getattr(self.config, "skill_dir", "workspace/skills"), persist=True)
            source_tasks = tasks if tasks is not None else self.tasks_for_suite(suite)
            cases = self._knowledge_correction_preflight_cases(source_tasks, feedback, skill_library)
            report["cases"] = cases
            report["case_count"] = len(cases)
            report["matched_case_count"] = sum(1 for case in cases if case.get("matched"))
            report["matched_dependency_correction_count"] = sum(
                int(case.get("dependency_correction_match_count", 0) or 0)
                for case in cases
            )
            report["matched_failure_action_memory_count"] = sum(
                int(case.get("failure_action_memory_match_count", 0) or 0)
                for case in cases
            )
            if cases:
                report["coverage_rate"] = round(report["matched_case_count"] / len(cases), 3)
            else:
                report["missing"].append("benchmark_cases")
            status = "pass" if report["matched_case_count"] else "warn"
            detail = (
                "knowledge corrections overlap at least one benchmark goal"
                if report["matched_case_count"]
                else "knowledge corrections do not overlap the selected benchmark suite"
            )
            report["checks"].append(self._gate_check(
                "knowledge_correction_suite_coverage",
                "benchmark_suite_overlap",
                status,
                detail,
                {
                    "case_count": report["case_count"],
                    "matched_case_count": report["matched_case_count"],
                    "coverage_rate": report["coverage_rate"],
                },
            ))
            if not report["matched_case_count"]:
                report["missing"].append("benchmark_suite_knowledge_correction_overlap")
        except Exception as e:
            report["errors"].append(f"knowledge_correction_preflight: {e}")

        if report["errors"]:
            report["readiness"] = "error"
            report["decision"] = "block_knowledge_correction_benchmark"
            report["reason"] = "knowledge-correction preflight inputs could not be loaded"
        elif report["missing"]:
            report["readiness"] = "review"
            report["decision"] = "hold_knowledge_correction_benchmark"
            report["reason"] = "knowledge-correction preflight is missing required evidence"
        elif not report["gate_approved"]:
            report["readiness"] = report["gate_readiness"] or "review"
            report["decision"] = "block_knowledge_correction_benchmark"
            report["reason"] = "knowledge-correction gate is not approved"
        else:
            report["ready"] = True
            report["readiness"] = "approved"
            report["decision"] = "allow_knowledge_correction_benchmark"
            report["reason"] = "approved gate and benchmark-suite correction coverage are present"
        report["ready"] = report["readiness"] in {"approved", "not_required"}
        return report

    def run_knowledge_correction_ablation(
        self,
        cases: Optional[list[dict]] = None,
        suite: str = "m1",
        feedback_paths: Optional[list[str]] = None,
        gate_paths: Optional[list[str]] = None,
        limit: int = 6,
    ) -> dict:
        """Compare planner context with knowledge-correction feedback disabled vs enabled."""
        clean_feedback_paths = [
            path for path in (
                feedback_paths
                if feedback_paths is not None
                else getattr(self.config, "knowledge_correction_feedback_paths", [])
            ) or []
            if path
        ]
        clean_gate_paths = [
            path for path in (
                gate_paths
                if gate_paths is not None
                else getattr(self.config, "knowledge_correction_gate_paths", [])
            ) or []
            if path
        ]
        source_cases = cases if cases is not None else [
            {
                "id": task.id,
                "goal": task.goal,
                "name": task.name,
                "current_state": {},
            }
            for task in self.tasks_for_suite(suite)
        ]
        normalized_cases = [
            self._normalize_knowledge_correction_ablation_case(case, index)
            for index, case in enumerate(source_cases or [], start=1)
        ]
        preflight_tasks = [
            BenchmarkTask(
                str(case.get("id") or f"case_{index}"),
                str(case.get("name") or case.get("goal") or f"case_{index}"),
                str(case.get("goal") or ""),
                suite.upper(),
            )
            for index, case in enumerate(normalized_cases, start=1)
            if str(case.get("goal") or "").strip()
        ]
        preflight = self.run_knowledge_correction_preflight(
            tasks=preflight_tasks,
            suite=suite,
            feedback_paths=clean_feedback_paths,
            gate_paths=clean_gate_paths,
        )
        report = {
            "type": "knowledge_correction_ablation",
            "suite": suite,
            "feedback_paths": list(clean_feedback_paths),
            "gate_paths": list(clean_gate_paths),
            "preflight": preflight,
            "case_count": len(normalized_cases),
            "changed_count": 0,
            "enabled_context_count": 0,
            "dependency_context_count": 0,
            "failure_memory_context_count": 0,
            "baseline_context_count": 0,
            "gate_readiness": preflight.get("gate_readiness", "not_required"),
            "gate_approved": bool(preflight.get("gate_approved", not bool(clean_feedback_paths))),
            "ready": False,
            "readiness": "review" if clean_feedback_paths else "not_required",
            "decision": "hold_knowledge_correction_ablation" if clean_feedback_paths else "skip_knowledge_correction_ablation",
            "reason": "no knowledge-correction feedback configured",
            "cases": [],
            "errors": [],
        }
        if not normalized_cases:
            report["reason"] = "no ablation cases supplied"
            report["readiness"] = "review" if clean_feedback_paths else "not_required"
            report["ready"] = report["readiness"] == "not_required"
            return report

        try:
            enabled_config = replace(
                self.config,
                enable_knowledge_correction_context=getattr(self.config, "enable_knowledge_correction_context", True),
                knowledge_correction_feedback_paths=list(clean_feedback_paths),
                knowledge_correction_gate_paths=list(clean_gate_paths),
            )
            enabled_agent = Agent(enabled_config)
            feedback_report = dict(getattr(enabled_agent, "knowledge_correction_feedback_report", {}) or {})
            report["gate_readiness"] = feedback_report.get("gate_readiness", report["gate_readiness"])
            report["gate_approved"] = bool(feedback_report.get("gate_approved", report["gate_approved"]))
            report["feedback_report"] = feedback_report
        except Exception as e:
            enabled_agent = None
            report["errors"].append(f"knowledge_correction_ablation_agent: {e}")

        for case in normalized_cases:
            baseline_context = ""
            enabled_context = ""
            if enabled_agent is not None:
                try:
                    enabled_context = enabled_agent._knowledge_correction_context(
                        str(case.get("goal") or ""),
                        case.get("current_state", {}) if isinstance(case.get("current_state", {}), dict) else {},
                        limit=limit,
                    )
                except Exception as e:
                    report["errors"].append(f"{case.get('id')}: {e}")
            context_lines = [
                line.strip()
                for line in enabled_context.splitlines()
                if line.strip().startswith("- ")
            ]
            dependency_count = sum(1 for line in context_lines if "Dependency correction:" in line)
            failure_count = sum(1 for line in context_lines if "Failed-action memory:" in line)
            changed = baseline_context != enabled_context
            report["changed_count"] += 1 if changed else 0
            report["enabled_context_count"] += 1 if enabled_context else 0
            report["dependency_context_count"] += dependency_count
            report["failure_memory_context_count"] += failure_count
            report["cases"].append({
                "id": case.get("id"),
                "goal": case.get("goal"),
                "current_state": case.get("current_state", {}),
                "baseline_context_chars": len(baseline_context),
                "enabled_context_chars": len(enabled_context),
                "changed": changed,
                "dependency_context_count": dependency_count,
                "failure_memory_context_count": failure_count,
                "enabled_context_preview": enabled_context[:1200],
            })

        if report["errors"]:
            report["readiness"] = "error"
            report["decision"] = "block_knowledge_correction_ablation"
            report["reason"] = "knowledge-correction ablation inputs could not be applied"
        elif clean_feedback_paths and not report["gate_approved"]:
            report["readiness"] = report["gate_readiness"] or "review"
            report["decision"] = "block_knowledge_correction_ablation"
            report["reason"] = "knowledge-correction gate is not approved"
        elif clean_feedback_paths and not report["changed_count"]:
            report["readiness"] = "review"
            report["decision"] = "hold_knowledge_correction_ablation"
            report["reason"] = "approved feedback produced no planner-context changes for these cases"
        elif clean_feedback_paths:
            report["ready"] = True
            report["readiness"] = "approved"
            report["decision"] = "allow_knowledge_correction_context_experiment"
            report["reason"] = "approved feedback changes planner context for at least one case"
        else:
            report["ready"] = True
            report["readiness"] = "not_required"
            report["decision"] = "skip_knowledge_correction_ablation"
            report["reason"] = "no knowledge-correction feedback configured"
        report["ready"] = report["readiness"] in {"approved", "not_required"}
        return report

    def run_skill_runtime_default_preflight(
        self,
        tasks: Optional[list[BenchmarkTask]] = None,
        suite: str = "m1",
        gate_paths: Optional[list[str]] = None,
        skill_storage_path: str = "",
    ) -> dict:
        """Check approved runtime-default gates and task-family coverage before live benchmarks."""
        from singularity.core.skill_library import SkillLibrary

        clean_gate_paths = [
            path for path in (
                gate_paths
                if gate_paths is not None
                else getattr(self.config, "skill_runtime_default_gate_paths", [])
            ) or []
            if path
        ]
        storage_path = skill_storage_path or getattr(self.config, "skill_dir", "workspace/skills")
        report = {
            "required": bool(clean_gate_paths),
            "ready": not bool(clean_gate_paths),
            "readiness": "not_required" if not clean_gate_paths else "review",
            "decision": "skip_skill_runtime_default_preflight" if not clean_gate_paths else "hold_skill_runtime_default_benchmark",
            "reason": "no skill runtime-default gate configured",
            "suite": suite,
            "skill_storage_path": storage_path,
            "gate_paths": list(clean_gate_paths),
            "gate_count": 0,
            "gate_readiness": "not_required" if not clean_gate_paths else "missing",
            "gate_approved": not bool(clean_gate_paths),
            "candidate_count": 0,
            "approved_candidate_count": 0,
            "review_candidate_count": 0,
            "rejected_candidate_count": 0,
            "benchmark_task_count": 0,
            "benchmark_task_families": [],
            "approved_task_families": [],
            "family_overlap_count": 0,
            "covered_task_families": [],
            "uncovered_task_families": [],
            "gate_reports": [],
            "candidates": [],
            "checks": [],
            "missing": [],
            "errors": [],
        }
        if not clean_gate_paths:
            report["checks"].append(self._gate_check(
                "benchmark",
                "skill_runtime_default_preflight",
                "pass",
                "no runtime-default gate is configured for this benchmark",
                {"gate_paths": 0},
            ))
            return report

        gate_items = self._load_gate_payloads(
            [],
            clean_gate_paths,
            report["errors"],
            "skill_runtime_default_gate",
        )
        report["gate_count"] = len(gate_items)
        if not gate_items:
            report["missing"].append("skill_runtime_default_gate")

        readinesses = []
        approved_families = set()
        for source, payload in gate_items:
            gate = payload.get("skill_runtime_default_gate", payload) if isinstance(payload, dict) else {}
            if not isinstance(gate, dict):
                report["errors"].append(f"{source}: skill_runtime_default_gate payload must be a dict")
                continue
            readiness = str(gate.get("readiness") or "").strip().lower() or "unknown"
            target_family = str(gate.get("target_task_family") or "").strip().lower()
            summary = {
                "path": source,
                "readiness": readiness,
                "decision": str(gate.get("decision") or "").strip(),
                "reason": str(gate.get("reason") or "").strip()[:300],
                "target_task_family": target_family,
                "candidate_count": self._gate_int(gate.get("candidate_count", 0)),
                "approved_candidate_count": self._gate_int(gate.get("approved_candidate_count", 0)),
                "review_candidate_count": self._gate_int(gate.get("review_candidate_count", 0)),
                "rejected_candidate_count": self._gate_int(gate.get("rejected_candidate_count", 0)),
            }
            report["gate_reports"].append(summary)
            readinesses.append(readiness)
            status = "pass" if readiness == "approved" else "fail" if readiness in {"rejected", "error"} else "warn"
            report["checks"].append(self._gate_check(
                source,
                "skill_runtime_default_gate",
                status,
                summary["reason"] or f"runtime-default gate readiness is {readiness}",
                {
                    "readiness": readiness,
                    "target_task_family": target_family,
                    "approved_candidate_count": summary["approved_candidate_count"],
                    "review_candidate_count": summary["review_candidate_count"],
                    "rejected_candidate_count": summary["rejected_candidate_count"],
                },
            ))
            for candidate in gate.get("candidates", []) if isinstance(gate.get("candidates", []), list) else []:
                if not isinstance(candidate, dict):
                    continue
                candidate_readiness = str(candidate.get("candidate_readiness") or "").strip().lower() or "unknown"
                task_family = str(candidate.get("task_family") or target_family or "").strip().lower()
                candidate_summary = {
                    "source": source,
                    "skill": str(candidate.get("skill") or candidate.get("name") or "").strip(),
                    "task_family": task_family,
                    "candidate_readiness": candidate_readiness,
                    "decision": str(candidate.get("decision") or "").strip(),
                    "reason": str(candidate.get("reason") or "").strip()[:300],
                    "lifecycle_ready": bool(candidate.get("lifecycle_ready")),
                    "runtime_default_candidate": bool(candidate.get("runtime_default_candidate")),
                    "quality_readiness": str(candidate.get("quality_readiness") or "").strip().lower(),
                }
                report["candidates"].append(candidate_summary)
                if candidate_readiness == "approved":
                    approved_families.add(task_family)

        if readinesses:
            if any(readiness == "error" for readiness in readinesses):
                report["gate_readiness"] = "error"
            elif any(readiness == "rejected" for readiness in readinesses):
                report["gate_readiness"] = "rejected"
            elif all(readiness == "approved" for readiness in readinesses):
                report["gate_readiness"] = "approved"
                report["gate_approved"] = True
            elif any(readiness == "review" for readiness in readinesses):
                report["gate_readiness"] = "review"
            else:
                report["gate_readiness"] = "unknown"

        report["candidate_count"] = len(report["candidates"])
        report["approved_candidate_count"] = sum(
            1 for item in report["candidates"] if item.get("candidate_readiness") == "approved"
        )
        report["review_candidate_count"] = sum(
            1 for item in report["candidates"] if item.get("candidate_readiness") == "review"
        )
        report["rejected_candidate_count"] = sum(
            1 for item in report["candidates"] if item.get("candidate_readiness") == "rejected"
        )
        if report["approved_candidate_count"] <= 0:
            report["missing"].append("approved_runtime_default_candidate")

        try:
            skill_library = SkillLibrary(storage_path=storage_path, persist=True)
            source_tasks = tasks if tasks is not None else self.tasks_for_suite(suite)
            benchmark_families = set()
            for task in source_tasks or []:
                goal = str(getattr(task, "goal", "") or "").strip()
                family = skill_library.infer_task_family(goal, {})
                if family:
                    benchmark_families.add(str(family).strip().lower())
            report["benchmark_task_count"] = len(source_tasks or [])
            report["benchmark_task_families"] = sorted(benchmark_families)
            if not source_tasks:
                report["missing"].append("benchmark_tasks")
        except Exception as e:
            report["errors"].append(f"skill_runtime_default_preflight: {e}")
            benchmark_families = set()

        report["approved_task_families"] = sorted(approved_families)
        wildcard_family = "" in approved_families
        covered_families = set(report["benchmark_task_families"]) if wildcard_family else (
            set(report["benchmark_task_families"]) & approved_families
        )
        uncovered_families = set(report["benchmark_task_families"]) - covered_families
        report["covered_task_families"] = sorted(covered_families)
        report["uncovered_task_families"] = sorted(uncovered_families)
        report["family_overlap_count"] = len(covered_families)

        candidate_status = "pass" if report["approved_candidate_count"] > 0 else "warn"
        candidate_detail = (
            "approved runtime-default candidates are present"
            if report["approved_candidate_count"] > 0
            else "no approved runtime-default candidates are present"
        )
        report["checks"].append(self._gate_check(
            "benchmark",
            "runtime_default_candidates",
            candidate_status,
            candidate_detail,
            {
                "approved_candidate_count": report["approved_candidate_count"],
                "review_candidate_count": report["review_candidate_count"],
                "rejected_candidate_count": report["rejected_candidate_count"],
            },
        ))

        if report["benchmark_task_families"] and report["approved_candidate_count"] > 0:
            if covered_families:
                report["checks"].append(self._gate_check(
                    "benchmark",
                    "benchmark_task_family_overlap",
                    "pass",
                    "approved runtime-default candidates cover at least one benchmark task family",
                    {
                        "covered_task_families": report["covered_task_families"],
                        "uncovered_task_families": report["uncovered_task_families"],
                    },
                ))
            else:
                report["missing"].append("benchmark_task_family_overlap")
                report["checks"].append(self._gate_check(
                    "benchmark",
                    "benchmark_task_family_overlap",
                    "warn",
                    "approved runtime-default candidates do not cover this benchmark suite",
                    {
                        "benchmark_task_families": report["benchmark_task_families"],
                        "approved_task_families": report["approved_task_families"],
                    },
                ))

        if report["errors"]:
            report["readiness"] = "error"
            report["decision"] = "block_skill_runtime_default_benchmark"
            report["reason"] = "skill runtime-default preflight inputs could not be loaded"
        elif not report["gate_approved"]:
            report["readiness"] = report["gate_readiness"] or "review"
            report["decision"] = "block_skill_runtime_default_benchmark"
            report["reason"] = "runtime-default gate is not approved"
        elif report["approved_candidate_count"] <= 0:
            report["readiness"] = "review"
            report["decision"] = "hold_skill_runtime_default_benchmark"
            report["reason"] = "runtime-default gate has no approved candidates"
        elif "benchmark_task_family_overlap" in report["missing"]:
            report["readiness"] = "review"
            report["decision"] = "hold_skill_runtime_default_benchmark"
            report["reason"] = "runtime-default gate has no task-family coverage for this benchmark suite"
        elif report["missing"]:
            report["readiness"] = "review"
            report["decision"] = "hold_skill_runtime_default_benchmark"
            report["reason"] = "skill runtime-default preflight is missing required evidence"
        else:
            report["ready"] = True
            report["readiness"] = "approved"
            report["decision"] = "allow_skill_runtime_default_benchmark"
            report["reason"] = "approved runtime-default gates cover the benchmark task family"
        report["ready"] = report["readiness"] in {"approved", "not_required"}
        return report

    def run_skill_lifecycle_report(
        self,
        skill_storage_path: str = "",
        goal: str = "",
        task_family: str = "",
        include_builtins: bool = False,
        limit: int = 20,
    ) -> dict:
        """Audit MUSE-style skill lifecycle readiness across creation, memory, and refinement."""
        from singularity.core.skill_library import SkillLibrary

        storage_path = skill_storage_path or getattr(self.config, "skill_dir", "workspace/skills")
        report = {
            "type": "skill_lifecycle_report",
            "research_basis": [
                "muse_autoskill_skill_creation_memory_management_evaluation_refinement",
                "agent_skills_lifecycle_governance",
                "minecraft_procedural_memory_transfer",
            ],
            "goal": str(goal or ""),
            "task_family": str(task_family or "").strip().lower(),
            "skill_storage_path": storage_path,
            "include_builtins": bool(include_builtins),
            "skill_count": 0,
            "custom_skill_count": 0,
            "ready_count": 0,
            "review_count": 0,
            "blocked_count": 0,
            "runtime_default_candidate_count": 0,
            "stage_counts": {
                "creation_ready": 0,
                "memory_ready": 0,
                "management_ready": 0,
                "evaluation_ready": 0,
                "refinement_ready": 0,
            },
            "issue_counts": {},
            "recommendation_counts": {},
            "policy_hints": [],
            "skills": [],
            "errors": [],
        }

        try:
            skill_library = SkillLibrary(storage_path=storage_path, persist=True)
            builtin_names = skill_library._builtin_skill_names()
            summaries = []
            for skill in skill_library.list_skills():
                built_in = skill.name in builtin_names
                if built_in and not include_builtins:
                    continue
                summary = self._skill_lifecycle_summary(
                    skill_library=skill_library,
                    skill=skill,
                    goal=report["goal"],
                    task_family=report["task_family"],
                    built_in=built_in,
                )
                summaries.append(summary)

            summaries.sort(
                key=lambda item: (
                    1 if item["runtime_default_candidate"] else 0,
                    1 if item["readiness"] == "ready" else 0,
                    item["success_memory_count"],
                    item["success_rate"],
                    item["memory_count"],
                    item["name"],
                ),
                reverse=True,
            )
            report["skill_count"] = len(summaries)
            report["custom_skill_count"] = sum(1 for item in summaries if not item["built_in"])
            report["ready_count"] = sum(1 for item in summaries if item["readiness"] == "ready")
            report["review_count"] = sum(1 for item in summaries if item["readiness"] == "review")
            report["blocked_count"] = sum(1 for item in summaries if item["readiness"] == "blocked")
            report["runtime_default_candidate_count"] = sum(
                1 for item in summaries if item["runtime_default_candidate"]
            )
            for summary in summaries:
                for stage, status in summary["lifecycle_stages"].items():
                    if status == "ready":
                        key = f"{stage}_ready"
                        report["stage_counts"][key] = report["stage_counts"].get(key, 0) + 1
                for issue in summary["issues"]:
                    report["issue_counts"][issue] = report["issue_counts"].get(issue, 0) + 1
                for recommendation in summary["recommendations"]:
                    report["recommendation_counts"][recommendation] = (
                        report["recommendation_counts"].get(recommendation, 0) + 1
                    )
            report["policy_hints"] = self._skill_lifecycle_policy_hints(report)
            report["skills"] = summaries[:limit] if limit and limit > 0 else summaries
        except Exception as e:
            report["errors"].append(f"skill_lifecycle_report: {e}")
        return report

    def _skill_lifecycle_summary(
        self,
        skill_library,
        skill,
        goal: str = "",
        task_family: str = "",
        built_in: bool = False,
    ) -> dict:
        all_memories = skill_library._normalized_skill_memory(skill)
        memories = all_memories
        if task_family:
            memories = [
                memory for memory in all_memories
                if str(memory.get("task_family", "")).strip().lower() == task_family
            ]
        governance = skill_library._skill_governance(skill, built_in=built_in)
        dependencies = skill_library._skill_dependencies(skill)
        missing_dependencies = [dep for dep in dependencies if dep not in skill_library.skills]
        postcondition_keys = skill_library._postcondition_keys(skill.postconditions)
        action_types = skill_library._skill_action_types(skill)

        success_outcomes = {"success", "succeeded", "achieved", "approved", "positive"}
        failure_outcomes = {"failure", "failed", "rejected", "blocked", "regression", "negative"}
        success_count = sum(1 for memory in memories if memory.get("outcome") in success_outcomes)
        failure_count = sum(1 for memory in memories if memory.get("outcome") in failure_outcomes)
        approved_transfer_count = sum(
            1 for memory in memories if memory.get("transfer_readiness") == "approved"
        )
        review_transfer_count = sum(
            1 for memory in memories
            if memory.get("transfer_readiness") in {"review", "rejected", "error"}
        )
        task_family_counts = {}
        for memory in all_memories:
            family = memory.get("task_family") or "unspecified"
            task_family_counts[family] = task_family_counts.get(family, 0) + 1

        creation_ready = bool(
            built_in
            or (
                str(skill.name or "").strip()
                and str(skill.description or "").strip()
                and (
                    str(skill.implementation or "").strip()
                    or bool(skill.parameters)
                    or bool(skill.examples)
                )
            )
        )
        memory_ready = bool(built_in or memories)
        management_ready = bool(governance["governed"] and not missing_dependencies)
        evaluation_ready = bool(
            built_in
            or governance["gate_readiness"] == "approved"
            or int(getattr(skill, "total_uses", 0) or 0) > 0
            or success_count > 0
            or bool(postcondition_keys)
        )
        refinement_signal = self._skill_lifecycle_refinement_signal(skill, memories)
        unresolved_failure = failure_count > success_count and failure_count > 0 and not refinement_signal
        refinement_ready = not unresolved_failure

        issues = []
        if not creation_ready:
            issues.append("missing_creation_artifact")
        if not built_in and not all_memories:
            issues.append("missing_skill_memory")
        elif not built_in and task_family and all_memories and not memories:
            issues.append("missing_task_family_memory")
        if not governance["governed"]:
            issues.append("ungoverned_custom_skill" if not built_in else "ungoverned_builtin_skill")
        if missing_dependencies:
            issues.append("missing_dependency")
        if not built_in and not postcondition_keys:
            issues.append("missing_postconditions")
        if not evaluation_ready:
            issues.append("missing_evaluation_evidence")
        if governance["gate_readiness"] in {"review", "rejected", "error"}:
            issues.append(f"gate_{governance['gate_readiness']}")
        if review_transfer_count:
            issues.append("transfer_review_or_rejected")
        if unresolved_failure:
            issues.append("unresolved_failure_memory")

        lifecycle_stages = {
            "creation": "ready" if creation_ready else "review",
            "memory": "ready" if memory_ready else "review",
            "management": "blocked" if missing_dependencies or governance["gate_readiness"] in {"rejected", "error"}
            else "ready" if management_ready else "review",
            "evaluation": "blocked" if governance["gate_readiness"] in {"rejected", "error"}
            else "ready" if evaluation_ready else "review",
            "refinement": "ready" if refinement_ready else "review",
        }
        if missing_dependencies or governance["gate_readiness"] in {"rejected", "error"}:
            readiness = "blocked"
        elif any(status != "ready" for status in lifecycle_stages.values()) or issues:
            readiness = "review"
        else:
            readiness = "ready"

        runtime_default_candidate = bool(
            not built_in
            and readiness == "ready"
            and governance["gate_readiness"] == "approved"
            and approved_transfer_count > 0
            and success_count > 0
        )

        recommendations = []
        if "missing_creation_artifact" in issues:
            recommendations.append("complete_skill_definition")
        if "missing_skill_memory" in issues or "missing_task_family_memory" in issues:
            recommendations.append("record_skill_local_replay_failure_or_transfer_memory")
        if "ungoverned_custom_skill" in issues or governance["gate_readiness"] in {"unknown", "not_required"}:
            recommendations.append("run_skill_lifecycle_gate_before_runtime_default")
        if "missing_postconditions" in issues or "missing_evaluation_evidence" in issues:
            recommendations.append("run_skill_contract_and_goal_verification")
        if "transfer_review_or_rejected" in issues or governance["gate_readiness"] in {"review", "rejected", "error"}:
            recommendations.append("keep_task_family_route_gated")
        if "unresolved_failure_memory" in issues:
            recommendations.append("refine_skill_or_add_failure_correction")
        if runtime_default_candidate:
            recommendations.append("candidate_runtime_default_for_matching_family")
        elif readiness == "ready" and not built_in:
            recommendations.append("candidate_for_lifecycle_gate")

        contract = {}
        if goal:
            contract = skill_library._skill_contract_profile(skill, goal, {})

        return {
            "name": skill.name,
            "layer": skill.layer,
            "built_in": built_in,
            "description": skill.description,
            "readiness": readiness,
            "runtime_default_candidate": runtime_default_candidate,
            "lifecycle_stages": lifecycle_stages,
            "governance": governance,
            "gate_readiness": governance["gate_readiness"],
            "dependencies": dependencies,
            "missing_dependencies": missing_dependencies,
            "action_types": action_types,
            "postcondition_keys": postcondition_keys,
            "total_uses": int(getattr(skill, "total_uses", 0) or 0),
            "success_rate": round(float(getattr(skill, "success_rate", 0.0) or 0.0), 4),
            "all_memory_count": len(all_memories),
            "memory_count": len(memories),
            "success_memory_count": success_count,
            "failure_memory_count": failure_count,
            "approved_transfer_memory_count": approved_transfer_count,
            "review_transfer_memory_count": review_transfer_count,
            "task_family_counts": task_family_counts,
            "refinement_signal": refinement_signal,
            "issues": sorted(set(issues)),
            "recommendations": sorted(set(recommendations)),
            "contract_score": round(float(contract.get("score", 0.0) or 0.0), 4) if contract else 0.0,
            "contract_readiness": contract.get("readiness", "") if contract else "",
            "goal_matches": contract.get("goal_matches", []) if contract else [],
            "memories": memories[-5:],
        }

    def _skill_lifecycle_refinement_signal(self, skill, memories: list[dict]) -> bool:
        refinement_terms = (
            "refine",
            "refined",
            "repair",
            "repaired",
            "fixed",
            "fixing",
            "mitigation",
            "counterexample",
            "failure_correction",
            "regression_fix",
        )
        for memory in memories:
            memory_type = str(memory.get("type") or "").lower()
            note = str(memory.get("note") or "").lower()
            tags = " ".join(str(tag or "").lower() for tag in memory.get("tags", []))
            if any(term in memory_type or term in note or term in tags for term in refinement_terms):
                return True
        notes = str(getattr(skill, "notes", "") or "").lower()
        implementation = str(getattr(skill, "implementation", "") or "").lower()
        provenance = getattr(skill, "provenance", {}) if isinstance(getattr(skill, "provenance", {}), dict) else {}
        provenance_text = json.dumps(provenance, default=str).lower()
        return any(term in notes or term in implementation or term in provenance_text for term in refinement_terms)

    def _skill_lifecycle_policy_hints(self, report: dict) -> list[str]:
        issues = report.get("issue_counts", {}) if isinstance(report, dict) else {}
        recommendations = report.get("recommendation_counts", {}) if isinstance(report, dict) else {}
        hints = []
        if not report.get("skill_count", 0):
            hints.append("seed_or_import_skills_before_lifecycle_review")
        if issues.get("missing_skill_memory") or issues.get("missing_task_family_memory"):
            hints.append("collect_skill_local_replay_failure_and_transfer_memory")
        if issues.get("missing_postconditions") or issues.get("missing_evaluation_evidence"):
            hints.append("complete_skill_contracts_and_goal_verification_before_promotion")
        if issues.get("unresolved_failure_memory"):
            hints.append("convert_failure_heavy_skills_into_refinement_or_failure_correction_candidates")
        if issues.get("gate_review") or issues.get("gate_rejected") or issues.get("gate_error"):
            hints.append("keep_review_only_until_lifecycle_gates_pass")
        if recommendations.get("candidate_runtime_default_for_matching_family"):
            hints.append("consider_task_family_runtime_default_candidates_after_gate_review")
        return hints

    def build_skill_runtime_default_gate(
        self,
        lifecycle_reports: Optional[list[dict]] = None,
        lifecycle_report_paths: Optional[list[str]] = None,
        transfer_gates: Optional[list[dict]] = None,
        transfer_gate_paths: Optional[list[str]] = None,
        quality_gates: Optional[list[dict]] = None,
        quality_gate_paths: Optional[list[str]] = None,
        target_task_family: str = "",
        require_quality_gate: bool = False,
        min_runtime_candidates: int = 1,
    ) -> dict:
        """Gate task-family runtime-default skills with lifecycle and transfer evidence."""
        target_family = str(target_task_family or "").strip().lower()
        require_quality = bool(require_quality_gate or quality_gates or quality_gate_paths)
        report = {
            "type": "skill_runtime_default_gate",
            "research_basis": [
                "after_procedural_memory_transfer_local_cross_task_specialization",
                "neural_procedural_memory_complements_explicit_skill_libraries",
                "muse_skill_lifecycle_governance",
                "agentcl_task_stream_transfer_gates",
            ],
            "target": "task_family_runtime_default_skills",
            "target_task_family": target_family,
            "required": True,
            "readiness": "review",
            "decision": "keep_runtime_default_review_only",
            "reason": "runtime-default skills require lifecycle and transfer evidence",
            "thresholds": {
                "min_runtime_candidates": int(min_runtime_candidates or 1),
                "require_quality_gate": require_quality,
            },
            "lifecycle_report_count": 0,
            "transfer_gate_count": 0,
            "quality_gate_count": 0,
            "candidate_count": 0,
            "approved_candidate_count": 0,
            "review_candidate_count": 0,
            "rejected_candidate_count": 0,
            "lifecycle_ready_count": 0,
            "runtime_default_candidate_count": 0,
            "transfer_gate_readiness": "missing",
            "transfer_gate_approved": False,
            "quality_gate_readiness": "not_required" if not require_quality else "missing",
            "quality_gate_approved": not require_quality,
            "missing": [],
            "policy_hints": [],
            "checks": [],
            "lifecycle_reports": [],
            "transfer_gate_reports": [],
            "quality_gate_reports": [],
            "candidates": [],
            "errors": [],
        }

        lifecycle_items = self._load_gate_payloads(
            lifecycle_reports or [],
            lifecycle_report_paths or [],
            report["errors"],
            "skill_lifecycle_report",
        )
        transfer_items = self._load_gate_payloads(
            transfer_gates or [],
            transfer_gate_paths or [],
            report["errors"],
            "task_stream_transfer_gate",
        )
        quality_items = self._load_gate_payloads(
            quality_gates or [],
            quality_gate_paths or [],
            report["errors"],
            "skill_memory_quality_gate",
        )
        report["lifecycle_report_count"] = len(lifecycle_items)
        report["transfer_gate_count"] = len(transfer_items)
        report["quality_gate_count"] = len(quality_items)
        if not lifecycle_items:
            report["missing"].append("skill_lifecycle_report")
        if not transfer_items:
            report["missing"].append("task_stream_transfer_gate")
        if require_quality and not quality_items:
            report["missing"].append("skill_memory_quality_gate")

        self._attach_runtime_default_gate_summaries(
            report,
            transfer_items,
            "task_stream_transfer_gate",
            "transfer_gate_reports",
            "transfer_gate_readiness",
            "transfer_gate_approved",
        )
        if require_quality:
            self._attach_runtime_default_gate_summaries(
                report,
                quality_items,
                "skill_memory_quality_gate",
                "quality_gate_reports",
                "quality_gate_readiness",
                "quality_gate_approved",
            )

        quality_index = self._skill_runtime_quality_gate_index(quality_items)
        for source, payload in lifecycle_items:
            lifecycle = payload.get("skill_lifecycle_report", payload) if isinstance(payload, dict) else {}
            if not isinstance(lifecycle, dict):
                continue
            lifecycle_family = str(lifecycle.get("task_family") or "").strip().lower()
            lifecycle_summary = {
                "path": source,
                "task_family": lifecycle_family,
                "skill_count": self._gate_int(lifecycle.get("skill_count", 0)),
                "ready_count": self._gate_int(lifecycle.get("ready_count", 0)),
                "runtime_default_candidate_count": self._gate_int(lifecycle.get("runtime_default_candidate_count", 0)),
                "errors": list(lifecycle.get("errors", [])) if isinstance(lifecycle.get("errors", []), list) else [],
            }
            report["lifecycle_reports"].append(lifecycle_summary)
            check_status = "fail" if lifecycle_summary["errors"] else (
                "pass" if lifecycle_summary["runtime_default_candidate_count"] else "warn"
            )
            check_detail = "skill lifecycle report contains errors" if lifecycle_summary["errors"] else (
                "runtime-default candidates are present"
                if lifecycle_summary["runtime_default_candidate_count"]
                else "no runtime-default candidates found in lifecycle report"
            )
            report["checks"].append(self._gate_check(
                source,
                "skill_lifecycle_report",
                check_status,
                check_detail,
                lifecycle_summary,
            ))
            for skill in lifecycle.get("skills", []) if isinstance(lifecycle.get("skills", []), list) else []:
                if not isinstance(skill, dict):
                    continue
                candidate = self._skill_runtime_default_candidate(
                    source,
                    skill,
                    lifecycle_family,
                    target_family,
                    require_quality,
                    quality_index,
                )
                if candidate:
                    report["candidates"].append(candidate)

        report["candidate_count"] = len(report["candidates"])
        report["lifecycle_ready_count"] = sum(1 for item in report["candidates"] if item["lifecycle_ready"])
        report["runtime_default_candidate_count"] = sum(
            1 for item in report["candidates"] if item["runtime_default_candidate"]
        )

        transfer_approved = bool(report["transfer_gate_approved"])
        quality_approved = bool(report["quality_gate_approved"])
        for candidate in report["candidates"]:
            if candidate["candidate_readiness"] == "rejected":
                pass
            elif not transfer_approved:
                candidate["candidate_readiness"] = "review"
                candidate["decision"] = "keep_runtime_default_review_only"
                candidate["reason"] = "task-stream transfer gate is not approved"
            elif not quality_approved:
                candidate["candidate_readiness"] = "review"
                candidate["decision"] = "keep_runtime_default_review_only"
                candidate["reason"] = "skill-memory quality gate is not approved"
            elif (
                candidate["lifecycle_ready"]
                and candidate["runtime_default_candidate"]
                and candidate["quality_readiness"] in {"approved", "not_required"}
            ):
                candidate["candidate_readiness"] = "approved"
                candidate["decision"] = "allow_task_family_runtime_default"
                candidate["reason"] = "skill lifecycle, transfer gate, and quality gate evidence allow task-family default use"
            else:
                candidate["candidate_readiness"] = "review"
                candidate["decision"] = "keep_runtime_default_review_only"
                candidate["reason"] = candidate["reason"] or "runtime-default evidence is incomplete"

        report["approved_candidate_count"] = sum(
            1 for item in report["candidates"] if item["candidate_readiness"] == "approved"
        )
        report["review_candidate_count"] = sum(
            1 for item in report["candidates"] if item["candidate_readiness"] == "review"
        )
        report["rejected_candidate_count"] = sum(
            1 for item in report["candidates"] if item["candidate_readiness"] == "rejected"
        )

        hints = set()
        if report["approved_candidate_count"]:
            hints.add("enable_only_approved_task_family_runtime_default_skills")
        if report["review_candidate_count"] or report["missing"]:
            hints.add("keep_runtime_default_candidates_review_only_until_evidence_passes")
        if report["rejected_candidate_count"]:
            hints.add("block_rejected_or_conflicting_runtime_default_skills")
        if target_family:
            hints.add("scope_runtime_default_skill_to_task_family")
        if require_quality:
            hints.add("keep_quality_feedback_gate_in_runtime_default_profile")
        report["policy_hints"] = sorted(hints)

        min_candidates = int(min_runtime_candidates or 1)
        if report["errors"]:
            report["readiness"] = "error"
            report["decision"] = "do_not_enable_runtime_default_skills"
            report["reason"] = "runtime-default gate inputs could not be loaded"
        elif report["transfer_gate_readiness"] in {"rejected", "error"} or report["quality_gate_readiness"] in {"rejected", "error"}:
            report["readiness"] = "rejected"
            report["decision"] = "do_not_enable_runtime_default_skills"
            report["reason"] = "transfer or quality gate rejected runtime-default evidence"
        elif report["missing"]:
            report["readiness"] = "review"
            report["decision"] = "keep_runtime_default_review_only"
            report["reason"] = "runtime-default gate is missing required evidence"
        elif report["approved_candidate_count"] < min_candidates:
            report["readiness"] = "review"
            report["decision"] = "keep_runtime_default_review_only"
            report["reason"] = "not enough approved runtime-default skill candidates"
        else:
            report["readiness"] = "approved"
            report["decision"] = "allow_task_family_runtime_default_skills"
            report["reason"] = "approved lifecycle, transfer, and quality evidence are present for task-family runtime defaults"
        return report

    def _attach_runtime_default_gate_summaries(
        self,
        report: dict,
        items: list[tuple[str, dict]],
        kind: str,
        output_key: str,
        readiness_key: str,
        approved_key: str,
    ):
        readinesses = []
        for source, payload in items:
            readiness = str(payload.get("readiness") or "").strip().lower() or "unknown"
            summary = {
                "path": source,
                "readiness": readiness,
                "decision": str(payload.get("decision") or "").strip(),
                "reason": str(payload.get("reason") or "").strip()[:300],
                "approved_count": self._gate_int(payload.get("approved_count", payload.get("evidence_count", 0))),
                "review_count": self._gate_int(payload.get("review_count", payload.get("warning_count", 0))),
                "rejected_count": self._gate_int(payload.get("rejected_count", payload.get("regression_count", 0))),
            }
            report[output_key].append(summary)
            readinesses.append(readiness)
            status = "pass" if readiness == "approved" else "fail" if readiness in {"rejected", "error"} else "warn"
            report["checks"].append(self._gate_check(
                source,
                kind,
                status,
                summary["reason"] or f"{kind} readiness is {readiness}",
                {
                    "readiness": readiness,
                    "approved_count": summary["approved_count"],
                    "review_count": summary["review_count"],
                    "rejected_count": summary["rejected_count"],
                },
            ))
        if not items:
            return
        if any(readiness == "error" for readiness in readinesses):
            report[readiness_key] = "error"
        elif any(readiness == "rejected" for readiness in readinesses):
            report[readiness_key] = "rejected"
        elif all(readiness == "approved" for readiness in readinesses):
            report[readiness_key] = "approved"
            report[approved_key] = True
        elif any(readiness == "review" for readiness in readinesses):
            report[readiness_key] = "review"
        else:
            report[readiness_key] = "unknown"

    def _skill_runtime_quality_gate_index(self, quality_items: list[tuple[str, dict]]) -> dict[tuple[str, str], dict]:
        index = {}
        for source, payload in quality_items:
            for candidate in payload.get("candidates", []) if isinstance(payload.get("candidates", []), list) else []:
                if not isinstance(candidate, dict):
                    continue
                skill = str(candidate.get("skill") or candidate.get("name") or "").strip()
                family = str(candidate.get("task_family") or "").strip().lower()
                if not skill:
                    continue
                key = (skill, family)
                entry = index.setdefault(key, {
                    "skill": skill,
                    "task_family": family,
                    "readinesses": set(),
                    "supported_reuse_count": 0,
                    "conflicting_reuse_count": 0,
                    "sources": set(),
                })
                entry["readinesses"].add(str(candidate.get("readiness") or "").strip().lower() or "unknown")
                entry["supported_reuse_count"] += self._gate_int(candidate.get("supported_reuse_count", 0))
                entry["conflicting_reuse_count"] += self._gate_int(candidate.get("conflicting_reuse_count", 0))
                entry["sources"].add(source)
        for entry in index.values():
            readinesses = entry["readinesses"]
            if "rejected" in readinesses or "error" in readinesses:
                readiness = "rejected"
            elif readinesses and all(item == "approved" for item in readinesses):
                readiness = "approved"
            elif "review" in readinesses:
                readiness = "review"
            else:
                readiness = "unknown"
            entry["readiness"] = readiness
            entry["readinesses"] = sorted(readinesses)
            entry["sources"] = sorted(entry["sources"])
        return index

    def _skill_runtime_default_candidate(
        self,
        source: str,
        skill: dict,
        lifecycle_family: str,
        target_family: str,
        require_quality: bool,
        quality_index: dict[tuple[str, str], dict],
    ) -> Optional[dict]:
        name = str(skill.get("name") or "").strip()
        if not name:
            return None
        family_counts = skill.get("task_family_counts", {}) if isinstance(skill.get("task_family_counts", {}), dict) else {}
        normalized_families = {
            str(family or "").strip().lower(): self._gate_int(count)
            for family, count in family_counts.items()
            if str(family or "").strip()
        }
        candidate_family = target_family or lifecycle_family
        if target_family:
            if lifecycle_family and lifecycle_family != target_family and target_family not in normalized_families:
                return None
            if normalized_families and target_family not in normalized_families and lifecycle_family != target_family:
                return None
        elif not candidate_family and len(normalized_families) == 1:
            candidate_family = next(iter(normalized_families))
        elif not candidate_family:
            candidate_family = ""

        lifecycle_ready = str(skill.get("readiness") or "").strip().lower() == "ready"
        runtime_default_candidate = bool(skill.get("runtime_default_candidate"))
        quality = (
            quality_index.get((name, candidate_family))
            or quality_index.get((name, ""))
            or {}
        )
        quality_readiness = "not_required"
        if require_quality:
            quality_readiness = str(quality.get("readiness") or "missing").strip().lower()

        candidate_readiness = "review"
        decision = "keep_runtime_default_review_only"
        reason = ""
        if str(skill.get("readiness") or "").strip().lower() == "blocked":
            candidate_readiness = "rejected"
            decision = "do_not_enable_runtime_default_skill"
            reason = "skill lifecycle readiness is blocked"
        elif quality_readiness in {"rejected", "error"}:
            candidate_readiness = "rejected"
            decision = "do_not_enable_runtime_default_skill"
            reason = "skill-memory quality gate rejected this skill or task family"
        elif not lifecycle_ready:
            reason = "skill lifecycle is not ready"
        elif not runtime_default_candidate:
            reason = "skill is not a lifecycle runtime-default candidate"
        elif require_quality and quality_readiness != "approved":
            reason = "matching skill-memory quality gate evidence is missing or not approved"

        return {
            "skill": name,
            "source": source,
            "task_family": candidate_family,
            "lifecycle_ready": lifecycle_ready,
            "runtime_default_candidate": runtime_default_candidate,
            "candidate_readiness": candidate_readiness,
            "decision": decision,
            "reason": reason,
            "skill_readiness": str(skill.get("readiness") or ""),
            "gate_readiness": str(skill.get("gate_readiness") or ""),
            "quality_readiness": quality_readiness,
            "quality_supported_reuse_count": self._gate_int(quality.get("supported_reuse_count", 0)),
            "quality_conflicting_reuse_count": self._gate_int(quality.get("conflicting_reuse_count", 0)),
            "memory_count": self._gate_int(skill.get("memory_count", 0)),
            "success_memory_count": self._gate_int(skill.get("success_memory_count", 0)),
            "failure_memory_count": self._gate_int(skill.get("failure_memory_count", 0)),
            "approved_transfer_memory_count": self._gate_int(skill.get("approved_transfer_memory_count", 0)),
            "review_transfer_memory_count": self._gate_int(skill.get("review_transfer_memory_count", 0)),
            "success_rate": round(float(skill.get("success_rate", 0.0) or 0.0), 4),
            "issues": list(skill.get("issues", [])) if isinstance(skill.get("issues", []), list) else [],
            "recommendations": list(skill.get("recommendations", [])) if isinstance(skill.get("recommendations", []), list) else [],
        }

    def _merge_skill_memory_quality_feedback_items(self, items: list[tuple[str, dict]]) -> dict:
        feedback = {
            "quality_label_counts": {},
            "hint_type_counts": {},
            "task_family_counts": {},
            "hint_quality_items": [],
            "policy_hints": [],
        }
        for _source, payload in items:
            current = payload.get("skill_memory_quality_feedback", payload) if isinstance(payload, dict) else {}
            if not isinstance(current, dict):
                continue
            for key in ("quality_label_counts", "hint_type_counts", "task_family_counts"):
                values = current.get(key, {}) if isinstance(current.get(key, {}), dict) else {}
                for name, count in values.items():
                    feedback[key][str(name)] = feedback[key].get(str(name), 0) + self._gate_int(count)
            for key in ("hint_quality_items", "policy_hints"):
                values = current.get(key, [])
                if isinstance(values, list):
                    feedback[key].extend(item for item in values if isinstance(item, dict))
        return feedback

    def _merge_knowledge_correction_feedback_items(self, items: list[tuple[str, dict]]) -> dict:
        feedback = {
            "dependency_corrections": [],
            "failure_action_memories": [],
            "policy_hints": [],
        }
        seen = {key: set() for key in feedback}
        for source, payload in items:
            current = payload.get("knowledge_correction_feedback", payload) if isinstance(payload, dict) else {}
            if not isinstance(current, dict):
                continue
            for key in ("dependency_corrections", "failure_action_memories", "policy_hints"):
                values = current.get(key, [])
                if not isinstance(values, list):
                    continue
                for item in values:
                    if not isinstance(item, dict):
                        continue
                    identity = self._knowledge_correction_preflight_identity(key, item, source)
                    if identity in seen[key]:
                        continue
                    entry = dict(item)
                    entry.setdefault("source", source)
                    feedback[key].append(entry)
                    seen[key].add(identity)
        return feedback

    def _attach_knowledge_correction_preflight_gates(self, report: dict, gate_items: list[tuple[str, dict]]):
        if not gate_items:
            report["missing"].append("knowledge_correction_gate")
            report["gate_readiness"] = "missing"
            report["gate_approved"] = False
            report["checks"].append(self._gate_check(
                "benchmark",
                "knowledge_correction_gate",
                "warn",
                "knowledge-correction feedback benchmarks require an approved knowledge-correction-gate report",
                {"gate_reports": 0},
            ))
            return

        readinesses = []
        for source, payload in gate_items:
            readiness = str(payload.get("readiness") or "").strip().lower() or "unknown"
            summary = {
                "path": source,
                "readiness": readiness,
                "decision": str(payload.get("decision") or "").strip(),
                "reason": str(payload.get("reason") or "").strip()[:300],
                "source_count": self._gate_int(payload.get("source_count", 0)),
                "ready_log_count": self._gate_int(payload.get("ready_log_count", 0)),
                "correction_count": self._gate_int(payload.get("correction_count", 0)),
                "dependency_correction_count": self._gate_int(payload.get("dependency_correction_count", 0)),
                "failure_action_memory_count": self._gate_int(payload.get("failure_action_memory_count", 0)),
            }
            report["gate_reports"].append(summary)
            readinesses.append(readiness)
            status = "pass" if readiness == "approved" else "fail" if readiness in {"rejected", "error"} else "warn"
            report["checks"].append(self._gate_check(
                source,
                "knowledge_correction_gate",
                status,
                summary["reason"] or f"gate readiness is {readiness}",
                {
                    "ready_log_count": summary["ready_log_count"],
                    "correction_count": summary["correction_count"],
                    "dependency_correction_count": summary["dependency_correction_count"],
                    "failure_action_memory_count": summary["failure_action_memory_count"],
                },
            ))

        report["gate_approved"] = False
        if any(readiness == "error" for readiness in readinesses):
            report["gate_readiness"] = "error"
        elif all(readiness == "approved" for readiness in readinesses):
            report["gate_readiness"] = "approved"
            report["gate_approved"] = True
        elif any(readiness == "rejected" for readiness in readinesses):
            report["gate_readiness"] = "rejected"
        elif any(readiness == "review" for readiness in readinesses):
            report["gate_readiness"] = "review"
        else:
            report["gate_readiness"] = "unknown"

    def _knowledge_correction_preflight_cases(
        self,
        tasks: list[BenchmarkTask],
        feedback: dict,
        skill_library,
    ) -> list[dict]:
        cases = []
        dependency_items = feedback.get("dependency_corrections", [])
        failure_items = feedback.get("failure_action_memories", [])
        for index, task in enumerate(tasks or [], start=1):
            goal = str(getattr(task, "goal", "") or "").strip()
            task_id = str(getattr(task, "id", "") or getattr(task, "task_id", "") or f"task_{index}")
            try:
                task_family = skill_library.infer_task_family(goal)
            except Exception:
                task_family = ""
            dependency_matches = [
                item for item in dependency_items
                if self._knowledge_correction_preflight_matches(item, goal, task_family)
            ]
            failure_matches = [
                item for item in failure_items
                if self._knowledge_correction_preflight_matches(item, goal, task_family)
            ]
            matched_signatures = []
            for item in dependency_matches[:3]:
                failed = str(item.get("failed_signature") or "")
                recovery = str(item.get("recovery_signature") or "")
                matched_signatures.append(f"{failed}->{recovery}" if recovery else failed)
            for item in failure_matches[:3]:
                signature = str(item.get("signature") or "")
                if signature:
                    matched_signatures.append(signature)
            cases.append({
                "id": task_id,
                "goal": goal,
                "task_family": task_family,
                "matched": bool(dependency_matches or failure_matches),
                "dependency_correction_match_count": len(dependency_matches),
                "failure_action_memory_match_count": len(failure_matches),
                "matched_signatures": self._dedupe_strings(matched_signatures)[:8],
            })
        return cases

    def _knowledge_correction_preflight_matches(self, item: dict, goal: str, task_family: str) -> bool:
        if not isinstance(item, dict):
            return False
        text = self._knowledge_correction_preflight_text(item)
        tokens = self._knowledge_correction_preflight_tokens(goal)
        if tokens and any(token in text for token in tokens):
            return True
        if task_family and task_family in text:
            return True
        return False

    def _knowledge_correction_preflight_text(self, item: dict) -> str:
        parts = []
        for key in (
            "goal",
            "signature",
            "failed_signature",
            "recovery_signature",
            "correction",
            "recommendation",
            "reason",
        ):
            value = item.get(key)
            if value:
                parts.append(str(value))
        for key in ("target_items", "failed_errors"):
            values = item.get(key, [])
            if isinstance(values, list):
                parts.extend(str(value) for value in values)
        task_families = item.get("task_families", {})
        if isinstance(task_families, dict):
            parts.extend(str(key) for key in task_families)
        dimensions = item.get("knowledge_dimensions", {})
        if isinstance(dimensions, dict):
            for values in dimensions.values():
                if isinstance(values, list):
                    parts.extend(str(value) for value in values)
                elif values:
                    parts.append(str(values))
        return " ".join(parts).lower().replace("_", " ")

    def _knowledge_correction_preflight_tokens(self, value: str) -> set[str]:
        normalized = "".join(ch.lower() if ch.isalnum() else " " for ch in str(value or ""))
        return {token for token in normalized.split() if len(token) >= 3}

    def _knowledge_correction_preflight_identity(self, key: str, item: dict, source: str) -> str:
        if key == "dependency_corrections":
            return "|".join([
                str(item.get("failed_signature", "")),
                str(item.get("recovery_signature", "")),
                str(item.get("goal", "")),
            ])
        if key == "failure_action_memories":
            return "|".join([
                str(item.get("signature", "")),
                str(item.get("reason", "")),
            ])
        if key == "policy_hints":
            return str(item.get("knowledge_correction_policy") or item.get("policy") or item)
        return f"{source}|{item}"

    def _normalize_knowledge_correction_ablation_case(self, case: dict, index: int) -> dict:
        case = case if isinstance(case, dict) else {"goal": str(case or "")}
        current_state = (
            case.get("current_state")
            if "current_state" in case
            else case.get("world_state")
            if "world_state" in case
            else case.get("observation", {})
        )
        if isinstance(current_state, str):
            try:
                current_state = json.loads(current_state)
            except json.JSONDecodeError:
                current_state = {}
        if not isinstance(current_state, dict):
            current_state = {}
        return {
            "id": str(case.get("id") or case.get("task_id") or f"case_{index}"),
            "name": str(case.get("name") or case.get("title") or case.get("goal") or f"case_{index}"),
            "goal": str(case.get("goal") or case.get("query") or ""),
            "current_state": current_state,
        }

    def _attach_skill_memory_quality_preflight_gates(self, report: dict, gate_items: list[tuple[str, dict]]):
        if not gate_items:
            report["missing"].append("skill_memory_quality_gate")
            report["gate_readiness"] = "missing"
            report["gate_approved"] = False
            report["checks"].append(self._gate_check(
                "benchmark",
                "skill_memory_quality_gate",
                "warn",
                "quality feedback benchmarks require an approved skill-memory-quality-gate report",
                {"gate_reports": 0},
            ))
            return

        readinesses = []
        for source, payload in gate_items:
            readiness = str(payload.get("readiness") or "").strip().lower() or "unknown"
            summary = {
                "path": source,
                "readiness": readiness,
                "decision": str(payload.get("decision") or "").strip(),
                "reason": str(payload.get("reason") or "").strip()[:300],
                "approved_count": self._gate_int(payload.get("approved_count", 0)),
                "review_count": self._gate_int(payload.get("review_count", 0)),
                "rejected_count": self._gate_int(payload.get("rejected_count", 0)),
            }
            report["gate_reports"].append(summary)
            readinesses.append(readiness)
            status = "pass" if readiness == "approved" else "fail" if readiness in {"rejected", "error"} else "warn"
            report["checks"].append(self._gate_check(
                source,
                "skill_memory_quality_gate",
                status,
                summary["reason"] or f"gate readiness is {readiness}",
                {
                    "approved_count": summary["approved_count"],
                    "review_count": summary["review_count"],
                    "rejected_count": summary["rejected_count"],
                },
            ))

        if any(readiness == "error" for readiness in readinesses):
            report["gate_readiness"] = "error"
        elif all(readiness == "approved" for readiness in readinesses):
            report["gate_readiness"] = "approved"
            report["gate_approved"] = True
        elif any(readiness == "rejected" for readiness in readinesses):
            report["gate_readiness"] = "rejected"
        elif any(readiness == "review" for readiness in readinesses):
            report["gate_readiness"] = "review"
        else:
            report["gate_readiness"] = "unknown"

    def _skill_memory_quality_preflight_cases(self, tasks: list[BenchmarkTask], skill_library) -> list[dict]:
        cases = []
        for index, task in enumerate(tasks or [], start=1):
            goal = str(getattr(task, "goal", "") or "").strip()
            task_id = str(getattr(task, "id", "") or getattr(task, "task_id", "") or f"task_{index}")
            task_family = skill_library.infer_task_family(goal)
            cases.append({
                "id": task_id,
                "goal": goal,
                "task_family": task_family,
            })
        return cases

    def run_action_value_transition_preflight(
        self,
        suite: str = "m1",
        feedback_paths: Optional[list[str]] = None,
        transition_gate_paths: Optional[list[str]] = None,
        evaluator_report_paths: Optional[list[str]] = None,
        require_evaluator_report: bool = False,
    ) -> dict:
        """Check action-value transition gates before transition-scored live benchmarks."""
        clean_feedback_paths = [
            path for path in (
                feedback_paths
                if feedback_paths is not None
                else getattr(self.config, "action_value_feedback_paths", [])
            ) or []
            if path
        ]
        clean_gate_paths = [
            path for path in (
                transition_gate_paths
                if transition_gate_paths is not None
                else getattr(self.config, "action_value_transition_gate_paths", [])
            ) or []
            if path
        ]
        clean_evaluator_paths = [
            path for path in (
                evaluator_report_paths
                if evaluator_report_paths is not None
                else getattr(self.config, "action_value_transition_evaluator_report_paths", [])
            ) or []
            if path
        ]
        report = {
            "required": bool(clean_feedback_paths or clean_gate_paths or clean_evaluator_paths),
            "ready": not bool(clean_feedback_paths or clean_gate_paths or clean_evaluator_paths),
            "readiness": "not_required" if not (clean_feedback_paths or clean_gate_paths or clean_evaluator_paths) else "review",
            "decision": "skip_action_value_transition_preflight" if not (clean_feedback_paths or clean_gate_paths or clean_evaluator_paths) else "hold_transition_value_benchmark",
            "reason": "no action-value transition feedback or gates configured",
            "suite": suite,
            "feedback_paths": list(clean_feedback_paths),
            "transition_gate_paths": list(clean_gate_paths),
            "transition_evaluator_report_paths": list(clean_evaluator_paths),
            "require_evaluator_report": bool(require_evaluator_report),
            "feedback_count": 0,
            "action_value_item_count": 0,
            "transition_item_count": 0,
            "trusted_transition_item_count": 0,
            "low_confidence_transition_item_count": 0,
            "transition_gate_count": 0,
            "transition_gate_readiness": "not_required",
            "transition_gate_approved": not bool(clean_gate_paths),
            "transition_evaluator_report_count": 0,
            "transition_evaluator_readiness": "not_required",
            "transition_evaluator_approved": not bool(clean_evaluator_paths),
            "transition_gate_reports": [],
            "transition_evaluator_reports": [],
            "checks": [],
            "missing": [],
            "errors": [],
        }
        if not report["required"]:
            report["checks"].append(self._gate_check(
                "benchmark",
                "action_value_transition_preflight",
                "pass",
                "no action-value transition feedback is configured for this benchmark",
                {"feedback_paths": 0},
            ))
            return report

        feedback_items = self._load_gate_payloads(
            [],
            clean_feedback_paths,
            report["errors"],
            "action_value_feedback",
        )
        report["feedback_count"] = len(feedback_items)
        self._attach_action_value_transition_preflight_feedback(report, feedback_items)

        gate_items = self._load_gate_payloads(
            [],
            clean_gate_paths,
            report["errors"],
            "action_value_transition_gate",
        )
        report["transition_gate_count"] = len(gate_items)
        self._attach_action_value_transition_preflight_gates(report, gate_items)

        evaluator_items = self._load_gate_payloads(
            [],
            clean_evaluator_paths,
            report["errors"],
            "action_value_transition_evaluator_report",
        )
        report["transition_evaluator_report_count"] = len(evaluator_items)
        self._attach_action_value_transition_preflight_evaluators(report, evaluator_items)

        if report["transition_item_count"] > 0 and not gate_items:
            report["missing"].append("action_value_transition_gate")
            report["transition_gate_readiness"] = "missing"
            report["transition_gate_approved"] = False
            report["checks"].append(self._gate_check(
                "benchmark",
                "action_value_transition_gate",
                "warn",
                "transition-scored action-value feedback requires an approved action-value-transition-gate report",
                {"transition_item_count": report["transition_item_count"]},
            ))
        if (bool(require_evaluator_report) or clean_evaluator_paths) and report["transition_item_count"] > 0 and not evaluator_items:
            report["missing"].append("action_value_transition_evaluator_report")
            report["transition_evaluator_readiness"] = "missing"
            report["transition_evaluator_approved"] = False
            report["checks"].append(self._gate_check(
                "benchmark",
                "action_value_transition_evaluator_report",
                "warn",
                "transition-scored benchmarks require an approved state-grounded evaluator report",
                {"transition_item_count": report["transition_item_count"]},
            ))

        if report["errors"]:
            report["readiness"] = "error"
            report["decision"] = "block_transition_value_benchmark"
            report["reason"] = "action-value transition preflight inputs could not be loaded"
        elif not clean_feedback_paths:
            report["readiness"] = "review"
            report["decision"] = "hold_transition_value_benchmark"
            report["reason"] = "transition gates were configured without action-value feedback"
            report["missing"].append("action_value_feedback")
        elif report["transition_item_count"] <= 0:
            report["ready"] = True
            report["readiness"] = "approved"
            report["decision"] = "allow_action_value_benchmark_without_transition_scores"
            report["reason"] = "action-value feedback contains no transition scores to gate"
        elif report["missing"]:
            report["readiness"] = "review"
            report["decision"] = "hold_transition_value_benchmark"
            report["reason"] = "action-value transition preflight is missing required gate evidence"
        elif not report["transition_gate_approved"]:
            report["readiness"] = report["transition_gate_readiness"] or "review"
            report["decision"] = "block_transition_value_benchmark"
            report["reason"] = "action-value transition gate is not approved"
        elif (bool(require_evaluator_report) or clean_evaluator_paths) and not report["transition_evaluator_approved"]:
            report["readiness"] = report["transition_evaluator_readiness"] or "review"
            report["decision"] = "block_transition_value_benchmark"
            report["reason"] = "state-grounded transition evaluator report is not approved"
        elif report["trusted_transition_item_count"] <= 0:
            report["readiness"] = "review"
            report["decision"] = "hold_transition_value_benchmark"
            report["reason"] = "action-value feedback has transition items but none pass trusted local checks"
        else:
            report["ready"] = True
            report["readiness"] = "approved"
            report["decision"] = "allow_transition_value_benchmark"
            report["reason"] = "approved transition gates and trusted transition feedback are present"
        report["ready"] = report["readiness"] in {"approved", "not_required"}
        return report

    def run_coach_style_preflight(
        self,
        suite: str = "m1",
        styles: Optional[list[str]] = None,
        ablation_paths: Optional[list[str]] = None,
        gate_paths: Optional[list[str]] = None,
        require_goal_change: bool = False,
    ) -> dict:
        """Check coach-style ablations and gates before style-biased benchmarks."""
        configured_styles = styles
        if configured_styles is None:
            configured_styles = CoachPolicy.from_style(getattr(self.config, "coach_style", "")).style_names
        clean_styles = [str(style).strip().lower() for style in (configured_styles or []) if str(style).strip()]
        clean_ablation_paths = [
            path for path in (
                ablation_paths
                if ablation_paths is not None
                else getattr(self.config, "coach_style_ablation_paths", [])
            ) or []
            if path
        ]
        clean_gate_paths = [
            path for path in (
                gate_paths
                if gate_paths is not None
                else getattr(self.config, "coach_style_gate_paths", [])
            ) or []
            if path
        ]
        required = bool(clean_styles) and getattr(self.config, "enable_coaching_policy", True)
        report = {
            "required": required,
            "ready": not required,
            "readiness": "not_required" if not required else "review",
            "decision": "skip_coach_style_preflight" if not required else "hold_coach_style_benchmark",
            "reason": "no coach style configured for this benchmark",
            "suite": suite,
            "styles": clean_styles,
            "ablation_paths": list(clean_ablation_paths),
            "gate_paths": list(clean_gate_paths),
            "case_count": 0,
            "changed_count": 0,
            "score_changed_count": 0,
            "gate_count": 0,
            "gate_readiness": "not_required" if not required else "missing",
            "gate_approved": not required,
            "approved_styles": [],
            "review_styles": [],
            "ablation_sources": [],
            "gate_reports": [],
            "checks": [],
            "missing": [],
            "errors": [],
        }
        if not required:
            report["checks"].append(self._gate_check(
                "benchmark",
                "coach_style_preflight",
                "pass",
                "no coach style is configured for this benchmark",
                {"styles": clean_styles},
            ))
            return report

        if not clean_ablation_paths:
            report["missing"].append("coach_style_ablation")
        if not clean_gate_paths:
            report["missing"].append("coach_style_gate")

        ablation_items = self._load_gate_payloads([], clean_ablation_paths, report["errors"], "coach_style_ablation")
        for source, payload in ablation_items:
            summary = self._coach_style_gate_source_summary(source, payload, clean_styles)
            report["ablation_sources"].append(summary)
            report["case_count"] += summary["case_count"]
            report["changed_count"] += summary["changed_count"]
            report["score_changed_count"] += summary["score_changed_count"]
            report["errors"].extend(summary["errors"])
            report["checks"].append(self._gate_check(
                source,
                "coach_style_ablation",
                "pass" if summary["ready"] else "warn",
                summary["reason"],
                {
                    "case_count": summary["case_count"],
                    "changed_count": summary["changed_count"],
                    "score_changed_count": summary["score_changed_count"],
                    "styles": summary["styles"],
                },
            ))

        for style in clean_styles:
            score_changes = sum(
                int(source.get("style_score_changed_counts", {}).get(style, 0) or 0)
                for source in report["ablation_sources"]
            )
            goal_changes = sum(
                int(source.get("style_changed_counts", {}).get(style, 0) or 0)
                for source in report["ablation_sources"]
            )
            if score_changes <= 0:
                report["missing"].append(f"coach_style_score_effect:{style}")
            if require_goal_change and goal_changes <= 0:
                report["missing"].append(f"coach_style_goal_change:{style}")

        gate_items = self._load_gate_payloads([], clean_gate_paths, report["errors"], "coach_style_gate")
        report["gate_count"] = len(gate_items)
        for source, payload in gate_items:
            readiness = str(payload.get("readiness") or "").lower()
            decision = str(payload.get("decision") or "").lower()
            approved_styles = [
                str(style).strip().lower()
                for style in (payload.get("approved_styles", []) if isinstance(payload.get("approved_styles", []), list) else [])
                if str(style).strip()
            ]
            review_styles = payload.get("review_styles", []) if isinstance(payload.get("review_styles", []), list) else []
            covers_requested = all(style in approved_styles for style in clean_styles)
            gate_ready = readiness == "approved" and decision == "allow_coach_style" and covers_requested
            if gate_ready:
                for style in approved_styles:
                    if style not in report["approved_styles"]:
                        report["approved_styles"].append(style)
            for item in review_styles:
                if isinstance(item, dict):
                    report["review_styles"].append(item)
            report["gate_reports"].append({
                "path": source,
                "readiness": readiness or "unknown",
                "decision": decision or "unknown",
                "approved_styles": approved_styles,
                "review_styles": review_styles,
                "covers_requested": covers_requested,
                "reason": payload.get("reason", ""),
            })
            report["checks"].append(self._gate_check(
                source,
                "coach_style_gate",
                "pass" if gate_ready else "warn",
                payload.get("reason", "coach-style gate report checked"),
                {
                    "readiness": readiness,
                    "decision": decision,
                    "approved_styles": approved_styles,
                    "covers_requested": covers_requested,
                },
            ))

        report["gate_approved"] = bool(clean_gate_paths) and bool(report["gate_reports"]) and all(
            gate.get("readiness") == "approved"
            and gate.get("decision") == "allow_coach_style"
            and gate.get("covers_requested")
            for gate in report["gate_reports"]
        )
        report["gate_readiness"] = "approved" if report["gate_approved"] else "review"
        if not report["gate_approved"]:
            report["missing"].append("approved_coach_style_gate")

        report["missing"] = self._dedupe_strings(report["missing"])
        if report["errors"]:
            report["readiness"] = "error"
            report["ready"] = False
            report["decision"] = "block_coach_style_benchmark"
            report["reason"] = "coach-style preflight inputs could not be loaded"
        elif report["missing"]:
            report["readiness"] = "review"
            report["ready"] = False
            report["decision"] = "hold_coach_style_benchmark"
            report["reason"] = "coach-style benchmark needs approved gate and score-changing ablation evidence"
        else:
            report["readiness"] = "approved"
            report["ready"] = True
            report["decision"] = "allow_coach_style_benchmark"
            report["reason"] = "coach-style benchmark has approved gate and offline ablation evidence"
        return report

    def _attach_action_value_transition_preflight_feedback(self, report: dict, feedback_items: list[tuple[str, dict]]):
        if not feedback_items:
            report["missing"].append("action_value_feedback")
            report["checks"].append(self._gate_check(
                "benchmark",
                "action_value_feedback",
                "warn",
                "action-value transition preflight requires at least one action-value feedback report",
                {"feedback_reports": 0},
            ))
            return

        for source, payload in feedback_items:
            feedback = payload.get("action_value_feedback", payload) if isinstance(payload, dict) else {}
            if not isinstance(feedback, dict):
                feedback = {}
            action_items = feedback.get("action_value_items", []) if isinstance(feedback.get("action_value_items", []), list) else []
            transition_items = feedback.get("state_transition_value_items", []) if isinstance(feedback.get("state_transition_value_items", []), list) else []
            trusted = 0
            low_confidence = 0
            for item in transition_items:
                if not isinstance(item, dict):
                    continue
                confidence = self._safe_float(item.get("avg_transition_confidence"), 0.0)
                attempts = max(0, self._gate_int(item.get("attempts")))
                low_windows = max(0, self._gate_int(item.get("low_confidence_transitions")))
                low_rate = low_windows / max(1, attempts)
                if confidence < 0.75 or low_rate > 0.25:
                    low_confidence += 1
                if attempts > 0 and confidence >= 0.75 and low_rate <= 0.25 and item.get("avg_transition_value_score") is not None:
                    trusted += 1
            report["action_value_item_count"] += len(action_items)
            report["transition_item_count"] += len(transition_items)
            report["trusted_transition_item_count"] += trusted
            report["low_confidence_transition_item_count"] += low_confidence
            status = "pass" if trusted else "warn" if transition_items else "pass"
            detail = (
                f"{trusted}/{len(transition_items)} transition value items look trusted"
                if transition_items else
                "feedback has no transition value items"
            )
            report["checks"].append(self._gate_check(
                source,
                "action_value_transition_feedback",
                status,
                detail,
                {
                    "action_value_items": len(action_items),
                    "transition_items": len(transition_items),
                    "trusted_transition_items": trusted,
                    "low_confidence_transition_items": low_confidence,
                },
            ))

    def _attach_action_value_transition_preflight_gates(self, report: dict, gate_items: list[tuple[str, dict]]):
        if not gate_items:
            return
        readinesses = []
        report["transition_gate_approved"] = False
        for source, payload in gate_items:
            readiness = str(payload.get("readiness") or "").strip().lower() or "unknown"
            summary = {
                "path": source,
                "readiness": readiness,
                "decision": str(payload.get("decision") or "").strip(),
                "reason": str(payload.get("reason") or "").strip()[:300],
                "trusted_item_count": self._gate_int(payload.get("trusted_item_count", 0)),
                "trusted_transition_count": self._gate_int(payload.get("trusted_transition_count", 0)),
                "low_confidence_rate": self._safe_float(payload.get("low_confidence_rate"), 0.0),
            }
            report["transition_gate_reports"].append(summary)
            readinesses.append(readiness)
            status = "pass" if readiness == "approved" else "fail" if readiness in {"rejected", "error"} else "warn"
            report["checks"].append(self._gate_check(
                source,
                "action_value_transition_gate",
                status,
                summary["reason"] or f"transition gate readiness is {readiness}",
                {
                    "trusted_item_count": summary["trusted_item_count"],
                    "trusted_transition_count": summary["trusted_transition_count"],
                    "low_confidence_rate": summary["low_confidence_rate"],
                },
            ))
        if any(readiness == "error" for readiness in readinesses):
            report["transition_gate_readiness"] = "error"
        elif all(readiness == "approved" for readiness in readinesses):
            report["transition_gate_readiness"] = "approved"
            report["transition_gate_approved"] = True
        elif any(readiness == "rejected" for readiness in readinesses):
            report["transition_gate_readiness"] = "rejected"
        elif any(readiness == "review" for readiness in readinesses):
            report["transition_gate_readiness"] = "review"
        else:
            report["transition_gate_readiness"] = "unknown"

    def _attach_action_value_transition_preflight_evaluators(self, report: dict, evaluator_items: list[tuple[str, dict]]):
        if not evaluator_items:
            return
        readinesses = []
        report["transition_evaluator_approved"] = False
        for source, payload in evaluator_items:
            readiness = str(payload.get("readiness") or "").strip().lower() or "unknown"
            summary = {
                "path": source,
                "readiness": readiness,
                "decision": str(payload.get("decision") or "").strip(),
                "reason": str(payload.get("reason") or "").strip()[:300],
                "evaluated_count": self._gate_int(payload.get("evaluated_count", 0)),
                "agreement_rate": self._safe_float(payload.get("agreement_rate"), 0.0),
                "avg_abs_score_delta": self._safe_float(payload.get("avg_abs_score_delta"), 0.0),
            }
            report["transition_evaluator_reports"].append(summary)
            readinesses.append(readiness)
            status = "pass" if readiness == "approved" else "fail" if readiness in {"rejected", "error"} else "warn"
            report["checks"].append(self._gate_check(
                source,
                "action_value_transition_evaluator_report",
                status,
                summary["reason"] or f"transition evaluator readiness is {readiness}",
                {
                    "evaluated_count": summary["evaluated_count"],
                    "agreement_rate": summary["agreement_rate"],
                    "avg_abs_score_delta": summary["avg_abs_score_delta"],
                },
            ))
        if any(readiness == "error" for readiness in readinesses):
            report["transition_evaluator_readiness"] = "error"
        elif all(readiness == "approved" for readiness in readinesses):
            report["transition_evaluator_readiness"] = "approved"
            report["transition_evaluator_approved"] = True
        elif any(readiness == "rejected" for readiness in readinesses):
            report["transition_evaluator_readiness"] = "rejected"
        elif any(readiness == "review" for readiness in readinesses):
            report["transition_evaluator_readiness"] = "review"
        else:
            report["transition_evaluator_readiness"] = "unknown"

    def _run_task_with_config(self, task: BenchmarkTask, config: Config) -> BenchmarkResult:
        runner = BenchmarkRunner(config, output_dir=self.output_dir, bridge_factory=self.bridge_factory)
        return runner.run_task(task)

    def _policy_intervention_count(self, result: BenchmarkResult) -> int:
        return result.intervention_metrics.get("policy_intervention_count", 0) if result.intervention_metrics else 0

    def _skill_memory_hint_count(self, result: BenchmarkResult) -> int:
        return result.intervention_metrics.get("skill_memory_hint_count", 0) if result.intervention_metrics else 0

    def _visual_action_intervention_count(self, result: BenchmarkResult) -> int:
        return result.intervention_metrics.get("visual_action_intervention_count", 0) if result.intervention_metrics else 0

    def _control_policy_summary_from_log(self, session_log_path: str) -> dict:
        summary = {
            "log_path": session_log_path or "",
            "log_available": bool(session_log_path and os.path.exists(session_log_path)),
            "action_event_count": 0,
            "control_policy_event_count": 0,
            "backend_counts": {},
            "preferred_backend_counts": {},
            "preferred_control_counts": {},
            "fallback_count": 0,
            "fallback_reasons": {},
            "action_backend_counts": {},
        }
        if not summary["log_available"]:
            return summary
        try:
            with open(session_log_path, "r", encoding="utf-8-sig") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if event.get("type") != "action":
                        continue
                    data = event.get("data", {}) if isinstance(event.get("data", {}), dict) else {}
                    action = data.get("action", {}) if isinstance(data.get("action", {}), dict) else {}
                    result = data.get("result", {}) if isinstance(data.get("result", {}), dict) else {}
                    summary["action_event_count"] += 1
                    policy = result.get("control_policy", {}) if isinstance(result.get("control_policy", {}), dict) else {}
                    if not policy:
                        continue
                    summary["control_policy_event_count"] += 1
                    action_type = str(policy.get("action_type") or result.get("action_type") or action.get("type") or "unknown")
                    backend = str(policy.get("backend") or result.get("backend") or "unknown")
                    preferred_backend = str(policy.get("preferred_backend") or "unknown")
                    preferred_control = str(policy.get("preferred_control") or "unknown")
                    self._increment(summary["backend_counts"], backend)
                    self._increment(summary["preferred_backend_counts"], preferred_backend)
                    self._increment(summary["preferred_control_counts"], preferred_control)
                    self._increment(summary["action_backend_counts"], f"{action_type}:{backend}")
                    fallback = str(policy.get("fallback_reason") or "")
                    if fallback:
                        summary["fallback_count"] += 1
                        self._increment(summary["fallback_reasons"], fallback)
        except Exception as exc:
            summary["error"] = str(exc)
        for key in (
            "backend_counts",
            "preferred_backend_counts",
            "preferred_control_counts",
            "fallback_reasons",
            "action_backend_counts",
        ):
            summary[key] = dict(sorted(summary[key].items()))
        return summary

    def _increment(self, counts: dict, key: str, amount: int = 1):
        counts[key] = counts.get(key, 0) + amount

    def run_promotion_review_ablation_from_logs(
        self,
        session_log_paths: list[str],
        promotion_critic=None,
        include_causal_summaries: bool = False,
        include_failure_corrections: bool = False,
        manual_labels: Optional[dict] = None,
    ) -> PromotionReviewAblationReport:
        """Compare skill-promotion review with and without visual evidence."""
        from singularity.core.skill_extractor import SkillExtractor
        from singularity.core.skill_library import SkillLibrary

        report = PromotionReviewAblationReport()
        with tempfile.TemporaryDirectory() as skill_dir:
            skill_library = SkillLibrary(storage_path=skill_dir, persist=False)
            extractor = SkillExtractor(
                skill_library,
                auto_promote=False,
                promotion_critic=promotion_critic,
            )
            deterministic_extractor = SkillExtractor(
                skill_library,
                auto_promote=False,
                promotion_critic=None,
            )
            for path in session_log_paths:
                try:
                    candidates = extractor.extract_skill_candidates(path)
                    if include_causal_summaries:
                        candidates.extend(extractor.extract_causal_skill_candidates(path))
                    if include_failure_corrections:
                        candidates.extend(extractor.extract_failure_correction_candidates(path))
                    for candidate in candidates:
                        manual = self._manual_promotion_label(manual_labels or {}, path, candidate)
                        report.cases.append(self._promotion_review_ablation_case(
                            extractor,
                            deterministic_extractor,
                            candidate,
                            source_log=path,
                            manual_label=manual,
                        ))
                except Exception as e:
                    report.errors.append(f"{path}: {e}")
        return report

    def _promotion_review_ablation_case(self, extractor, deterministic_extractor, candidate, source_log: str, manual_label: Optional[dict] = None) -> PromotionReviewAblationResult:
        visual_evidence = candidate.signals.get("visual_evidence", {}) if isinstance(candidate.signals, dict) else {}
        screenshot_status = self._visual_evidence_screenshot_status(visual_evidence, source_log)
        screenshot_visual_evidence = self._screenshot_vlm_visual_evidence(visual_evidence, source_log)
        deterministic_candidate = replace(candidate, signals={
            key: value
            for key, value in candidate.signals.items()
            if key != "visual_evidence"
        })
        api_visual_candidate = replace(candidate, signals={
            **{
                key: value
                for key, value in candidate.signals.items()
                if key != "visual_evidence"
            },
            "visual_evidence": self._api_visual_evidence(visual_evidence),
        })
        if not api_visual_candidate.signals.get("visual_evidence"):
            api_visual_candidate.signals.pop("visual_evidence", None)
        screenshot_vlm_candidate = replace(candidate, signals={
            **{
                key: value
                for key, value in candidate.signals.items()
                if key != "visual_evidence"
            },
            "visual_evidence": screenshot_visual_evidence,
        })
        if not screenshot_vlm_candidate.signals.get("visual_evidence"):
            screenshot_vlm_candidate.signals.pop("visual_evidence", None)

        deterministic = deterministic_extractor.validate_candidate_for_promotion(deterministic_candidate).to_dict()
        api_visual = extractor.validate_candidate_for_promotion(api_visual_candidate).to_dict()
        screenshot_vlm = extractor.validate_candidate_for_promotion(screenshot_vlm_candidate).to_dict()

        deterministic_readiness = self._promotion_readiness(deterministic)
        api_visual_readiness = self._promotion_readiness(api_visual)
        screenshot_vlm_readiness = self._promotion_readiness(screenshot_vlm)
        changed = (
            deterministic_readiness != api_visual_readiness
            or api_visual_readiness != screenshot_vlm_readiness
            or deterministic.get("status") != api_visual.get("status")
            or api_visual.get("status") != screenshot_vlm.get("status")
            or deterministic.get("postconditions", {}) != api_visual.get("postconditions", {})
            or api_visual.get("postconditions", {}) != screenshot_vlm.get("postconditions", {})
        )
        api_visual_helped = deterministic_readiness != "approved" and api_visual_readiness == "approved"
        has_verified_screenshot = bool(screenshot_status["verified"])
        screenshot_vlm_helped = has_verified_screenshot and deterministic_readiness != "approved" and screenshot_vlm_readiness == "approved"
        screenshot_vlm_added_value = has_verified_screenshot and api_visual_readiness != "approved" and screenshot_vlm_readiness == "approved"
        manual_readiness = (manual_label or {}).get("readiness", "")
        return PromotionReviewAblationResult(
            source_log=source_log,
            candidate_id=candidate.id,
            candidate_name=candidate.name,
            goal=candidate.goal,
            score=candidate.score,
            has_visual_evidence=bool(visual_evidence),
            visual_evidence_keys=sorted(visual_evidence.keys()) if isinstance(visual_evidence, dict) else [],
            raw_screenshot_count=len(screenshot_status["raw"]),
            screenshot_count=len(screenshot_status["verified"]),
            missing_screenshot_count=len(screenshot_status["missing"]),
            invalid_screenshot_count=len(screenshot_status["invalid"]),
            manual_readiness=manual_readiness,
            manual_label_source=(manual_label or {}).get("source", ""),
            manual_label_notes=(manual_label or {}).get("notes", ""),
            deterministic_readiness=deterministic_readiness,
            api_visual_readiness=api_visual_readiness,
            screenshot_vlm_readiness=screenshot_vlm_readiness,
            deterministic_decision=deterministic.get("decision", "unknown"),
            api_visual_decision=api_visual.get("decision", "unknown"),
            screenshot_vlm_decision=screenshot_vlm.get("decision", "unknown"),
            deterministic_status=deterministic.get("status", "unknown"),
            api_visual_status=api_visual.get("status", "unknown"),
            screenshot_vlm_status=screenshot_vlm.get("status", "unknown"),
            deterministic_reason=deterministic.get("reason", ""),
            api_visual_reason=api_visual.get("reason", ""),
            screenshot_vlm_reason=screenshot_vlm.get("reason", ""),
            deterministic_postconditions=deterministic.get("postconditions", {}),
            api_visual_postconditions=api_visual.get("postconditions", {}),
            screenshot_vlm_postconditions=screenshot_vlm.get("postconditions", {}),
            without_visual_readiness=api_visual_readiness,
            with_visual_readiness=screenshot_vlm_readiness,
            without_visual_decision=api_visual.get("decision", "unknown"),
            with_visual_decision=screenshot_vlm.get("decision", "unknown"),
            without_visual_status=api_visual.get("status", "unknown"),
            with_visual_status=screenshot_vlm.get("status", "unknown"),
            without_visual_reason=api_visual.get("reason", ""),
            with_visual_reason=screenshot_vlm.get("reason", ""),
            without_visual_postconditions=api_visual.get("postconditions", {}),
            with_visual_postconditions=screenshot_vlm.get("postconditions", {}),
            changed=changed,
            visual_helped=screenshot_vlm_helped,
            api_visual_helped=api_visual_helped,
            screenshot_vlm_helped=screenshot_vlm_helped,
            screenshot_vlm_added_value=screenshot_vlm_added_value,
            deterministic_matches_manual=self._manual_match(deterministic_readiness, manual_readiness),
            api_visual_matches_manual=self._manual_match(api_visual_readiness, manual_readiness),
            screenshot_vlm_matches_manual=self._manual_match(screenshot_vlm_readiness, manual_readiness),
        )

    def _promotion_readiness(self, report: dict) -> str:
        if report.get("decision") == "reject":
            return "rejected"
        if report.get("status") == "unknown":
            return "unknown"
        return "approved"

    def load_promotion_review_labels(self, label_path: str) -> dict:
        """Load manual skill-promotion review labels from JSON or JSONL."""
        if not label_path:
            return {}
        records = self._load_manual_label_records(label_path)
        return self._promotion_review_labels_from_records(records)

    def _promotion_review_labels_from_records(self, records: list[dict]) -> dict:
        labels = {}
        for record in records:
            if not isinstance(record, dict):
                continue
            label = self._normalize_manual_readiness_label(record)
            if not label.get("readiness"):
                continue
            keys = []
            if record.get("key"):
                keys.append(record["key"])
            source = record.get("source_log") or record.get("log") or record.get("path") or record.get("session_log")
            candidate_id = record.get("candidate_id") or record.get("id")
            candidate_name = record.get("candidate_name") or record.get("name") or record.get("skill_name")
            goal = record.get("goal") or record.get("task") or record.get("objective")
            keys.extend(self._promotion_label_keys(source or "", candidate_id or "", candidate_name or "", goal or ""))
            for key in keys:
                labels[self._label_key(key)] = label
        return labels

    def _load_manual_label_records(self, label_path: str) -> list[dict]:
        with open(label_path, "r", encoding="utf-8") as f:
            if label_path.lower().endswith(".jsonl"):
                return [json.loads(line) for line in f if line.strip()]
            payload = json.load(f)
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict) and isinstance(payload.get("labels"), list):
            return payload["labels"]
        if isinstance(payload, dict):
            return [
                {**(value if isinstance(value, dict) else {"readiness": value}), "key": key}
                for key, value in payload.items()
            ]
        return []

    def validate_review_labels(self, label_path: str) -> ReviewLabelValidationReport:
        """Validate a manual review label file before agreement ablations use it."""
        report = ReviewLabelValidationReport(label_path=label_path)
        try:
            records = self._load_manual_label_records(label_path)
        except Exception as e:
            report.errors.append(str(e))
            return report

        for index, record in enumerate(records, start=1):
            if not isinstance(record, dict):
                report.cases.append(ReviewLabelValidationCase(
                    index=index,
                    ok=False,
                    errors=["record_not_object"],
                ))
                continue
            report.cases.append(self._validate_review_label_record(record, index))
        return report

    def _validate_review_label_record(self, record: dict, index: int) -> ReviewLabelValidationCase:
        label_type = self._review_label_type(record)
        source_log = str(record.get("source_log") or record.get("log") or record.get("path") or record.get("session_log") or "")
        raw_readiness = str(record.get("readiness", record.get("label", record.get("status", record.get("decision", "")))) or "")
        readiness = self._normalize_goal_readiness(raw_readiness)
        screenshot_status = self._review_label_screenshot_status(record, source_log)
        case = ReviewLabelValidationCase(
            index=index,
            label_type=label_type,
            key=str(record.get("key", "") or ""),
            source_log=source_log,
            goal=str(record.get("goal") or record.get("task") or record.get("objective") or ""),
            candidate_id=str(record.get("candidate_id") or record.get("id") or ""),
            candidate_name=str(record.get("candidate_name") or record.get("name") or record.get("skill_name") or ""),
            raw_readiness=raw_readiness,
            readiness=readiness,
            raw_screenshot_count=len(screenshot_status["raw"]),
            screenshot_count=len(screenshot_status["verified"]),
            missing_screenshot_count=len(screenshot_status["missing"]),
            invalid_screenshot_count=len(screenshot_status["invalid"]),
            screenshots=screenshot_status["verified"][:6],
            missing_screenshots=screenshot_status["missing"][:6],
            invalid_screenshots=screenshot_status["invalid"][:6],
        )

        if label_type == "unknown":
            case.errors.append("unknown_label_type")
        if not readiness:
            case.errors.append("invalid_readiness")
        elif readiness == "unknown":
            case.warnings.append("readiness_still_unknown")

        if label_type == "promotion_review" and not (
            case.key or case.candidate_id or case.candidate_name or case.goal
        ):
            case.errors.append("missing_promotion_match_key")
        if label_type == "goal_verification" and not (case.key or case.goal):
            case.errors.append("missing_goal_match_key")
        if not case.source_log:
            case.warnings.append("missing_source_log")

        declares_screenshot = bool(record.get("has_screenshot_evidence"))
        approved_with_raw_screenshot = readiness == "approved" and case.raw_screenshot_count > 0
        if (declares_screenshot or approved_with_raw_screenshot) and case.screenshot_count == 0:
            case.errors.append("screenshot_evidence_not_verified")
        if case.raw_screenshot_count and case.screenshot_count == 0:
            case.warnings.append("no_verified_screenshot_file")
        if case.missing_screenshot_count:
            case.warnings.append("missing_screenshot_files")
        if case.invalid_screenshot_count:
            case.warnings.append("invalid_screenshot_files")

        case.ok = not case.errors
        return case

    def _review_label_type(self, record: dict) -> str:
        text = str(record.get("type", "") or "").strip().lower()
        if text in {"promotion", "promotion_review", "skill_promotion", "skill"}:
            return "promotion_review"
        if text in {"goal", "goal_verification", "verification"}:
            return "goal_verification"
        if record.get("candidate_id") or record.get("candidate_name") or record.get("skill_name"):
            return "promotion_review"
        if record.get("goal") or record.get("goal_index"):
            return "goal_verification"
        return "unknown"

    def _review_label_screenshot_status(self, record: dict, source_log: str = "") -> dict:
        paths = self._visual_paths_from_record(record)
        missing = self._label_path_list(record.get("missing_screenshots"))
        invalid = self._label_path_list(record.get("invalid_screenshots"))
        status = self._screenshot_status_for_paths(paths, source_log)
        raw = self._dedupe_strings(status["raw"] + missing + invalid)
        return {
            "raw": raw,
            "verified": status["verified"],
            "missing": self._dedupe_strings(status["missing"] + missing),
            "invalid": self._dedupe_strings(status["invalid"] + invalid),
        }

    def _label_path_list(self, value) -> list[str]:
        if isinstance(value, list):
            return [str(item) for item in value if item]
        if value:
            return [str(value)]
        return []

    def _normalize_manual_readiness_label(self, record: dict) -> dict:
        readiness = self._normalize_goal_readiness(
            record.get("readiness", record.get("label", record.get("status", record.get("decision"))))
        )
        if not readiness and "approved" in record:
            readiness = "approved" if bool(record.get("approved")) else "rejected"
        return {
            "readiness": readiness,
            "source": str(record.get("source", record.get("reviewer", "manual_label")) or "manual_label"),
            "notes": str(record.get("notes", record.get("reason", "")) or ""),
        }

    def _manual_promotion_label(self, labels: dict, source_log: str, candidate) -> dict:
        if not labels:
            return {}
        for key in self._promotion_label_keys(
            source_log,
            getattr(candidate, "id", ""),
            getattr(candidate, "name", ""),
            getattr(candidate, "goal", ""),
        ):
            label = labels.get(self._label_key(key))
            if label:
                return label
        return {}

    def _promotion_label_keys(self, source_log: str, candidate_id: str = "", candidate_name: str = "", goal: str = "") -> list[str]:
        source_text = str(source_log or "")
        basename = os.path.basename(source_text) if source_text else ""
        values = [str(candidate_id or ""), str(candidate_name or ""), str(goal or "")]
        keys = []
        for source in [source_text, basename]:
            if not source:
                continue
            for value in values:
                if value:
                    keys.append(f"{source}::{value}")
        keys.extend(value for value in values if value)
        return keys

    def _api_visual_evidence(self, visual_evidence: dict) -> dict:
        if not isinstance(visual_evidence, dict) or not visual_evidence:
            return {}
        stripped = {
            key: value
            for key, value in visual_evidence.items()
            if key not in {"screenshots", "visual_analysis"}
        }
        if len(stripped) <= 3 and not any(
            key in stripped
            for key in ("grounded_resources", "landmarks", "structures", "flags", "nearby_blocks", "nearby_entities")
        ):
            return {}
        stripped["mode"] = "api_visual_summary"
        return stripped

    def _screenshot_vlm_visual_evidence(self, visual_evidence: dict, source_log: str = "") -> dict:
        if not isinstance(visual_evidence, dict) or not visual_evidence:
            return {}
        filtered = dict(visual_evidence)
        status = self._visual_evidence_screenshot_status(visual_evidence, source_log)
        for key in ("screenshots", "screenshot_path", "screenshot", "image_path", "frame_path"):
            filtered.pop(key, None)
        if status["verified"]:
            filtered["screenshots"] = status["verified"][:3]
        filtered["screenshot_file_status"] = {
            "raw_count": len(status["raw"]),
            "verified_count": len(status["verified"]),
            "missing_count": len(status["missing"]),
            "invalid_count": len(status["invalid"]),
        }
        return {
            key: value
            for key, value in filtered.items()
            if value not in (None, "", [], {})
        }

    def _visual_evidence_screenshot_status(self, visual_evidence: dict, source_log: str = "") -> dict:
        paths = self._visual_paths_from_record(visual_evidence if isinstance(visual_evidence, dict) else {})
        return self._screenshot_status_for_paths(paths, source_log)

    def build_review_label_templates_from_logs(
        self,
        session_log_paths: list[str],
        mode: str = "both",
        include_causal_summaries: bool = False,
        include_failure_corrections: bool = False,
    ) -> list[dict]:
        """Create JSONL-ready manual review label templates from session logs."""
        mode = str(mode or "both").lower()
        templates = []
        if mode in {"promotion", "both"}:
            templates.extend(self._promotion_review_label_templates(
                session_log_paths,
                include_causal_summaries=include_causal_summaries,
                include_failure_corrections=include_failure_corrections,
            ))
        if mode in {"goal", "goal_verification", "both"}:
            templates.extend(self._goal_verification_label_templates(session_log_paths))
        return templates

    def _promotion_review_label_templates(
        self,
        session_log_paths: list[str],
        include_causal_summaries: bool = False,
        include_failure_corrections: bool = False,
    ) -> list[dict]:
        from singularity.core.skill_extractor import SkillExtractor
        from singularity.core.skill_library import SkillLibrary

        templates = []
        with tempfile.TemporaryDirectory() as skill_dir:
            skill_library = SkillLibrary(storage_path=skill_dir, persist=False)
            extractor = SkillExtractor(skill_library, auto_promote=False, promotion_critic=None)
            for path in session_log_paths:
                try:
                    candidates = extractor.extract_skill_candidates(path)
                    if include_causal_summaries:
                        candidates.extend(extractor.extract_causal_skill_candidates(path))
                    if include_failure_corrections:
                        candidates.extend(extractor.extract_failure_correction_candidates(path))
                    for candidate in candidates:
                        visual_evidence = candidate.signals.get("visual_evidence", {}) if isinstance(candidate.signals, dict) else {}
                        templates.append(self._promotion_review_label_template(path, candidate, visual_evidence))
                except Exception as e:
                    templates.append({
                        "type": "error",
                        "source_log": path,
                        "error": str(e),
                    })
        return templates

    def _promotion_review_label_template(self, source_log: str, candidate, visual_evidence: dict) -> dict:
        visual_evidence = visual_evidence if isinstance(visual_evidence, dict) else {}
        screenshot_status = self._visual_evidence_screenshot_status(visual_evidence, source_log)
        label_key = self._promotion_label_keys(source_log, candidate.id, candidate.name, candidate.goal)[0]
        template = {
            "type": "promotion_review",
            "key": label_key,
            "source_log": source_log,
            "candidate_id": candidate.id,
            "candidate_name": candidate.name,
            "goal": candidate.goal,
            "readiness": "unknown",
            "reviewer": "",
            "notes": "",
            "score": candidate.score,
            "has_visual_evidence": bool(visual_evidence),
            "visual_evidence_keys": sorted(visual_evidence.keys()),
            "has_screenshot_evidence": bool(screenshot_status["verified"]),
            "raw_screenshot_count": len(screenshot_status["raw"]),
            "screenshot_count": len(screenshot_status["verified"]),
            "missing_screenshot_count": len(screenshot_status["missing"]),
            "invalid_screenshot_count": len(screenshot_status["invalid"]),
        }
        if screenshot_status["verified"]:
            template["screenshots"] = screenshot_status["verified"][:3]
        if screenshot_status["missing"]:
            template["missing_screenshots"] = screenshot_status["missing"][:3]
        if screenshot_status["invalid"]:
            template["invalid_screenshots"] = screenshot_status["invalid"][:3]
        return template

    def _goal_verification_label_templates(self, session_log_paths: list[str]) -> list[dict]:
        templates = []
        for path in session_log_paths:
            try:
                events = self._load_session_events(path)
                segments = self._session_goal_segments(events)
                if not segments:
                    templates.append({
                        "type": "error",
                        "source_log": path,
                        "error": "missing goal_start or goal_end goal",
                    })
                    continue
                for goal_index, (goal, segment_events) in enumerate(segments, start=1):
                    observation = self._final_goal_observation(segment_events)
                    visual_keys = self._goal_visual_evidence_keys(observation)
                    screenshot_status = self._screenshot_status_for_paths(
                        self._visual_paths_from_record(observation),
                        path,
                    )
                    label_key = self._goal_label_keys(path, goal, goal_index)[0]
                    template = {
                        "type": "goal_verification",
                        "key": label_key,
                        "source_log": path,
                        "goal_index": goal_index,
                        "goal": goal,
                        "readiness": "unknown",
                        "reviewer": "",
                        "notes": "",
                        "has_visual_evidence": bool(visual_keys),
                        "visual_evidence_keys": visual_keys,
                        "has_screenshot_evidence": bool(screenshot_status["verified"]),
                        "raw_screenshot_count": len(screenshot_status["raw"]),
                        "screenshot_count": len(screenshot_status["verified"]),
                        "missing_screenshot_count": len(screenshot_status["missing"]),
                        "invalid_screenshot_count": len(screenshot_status["invalid"]),
                    }
                    if screenshot_status["verified"]:
                        template["screenshots"] = screenshot_status["verified"][:3]
                    if screenshot_status["missing"]:
                        template["missing_screenshots"] = screenshot_status["missing"][:3]
                    if screenshot_status["invalid"]:
                        template["invalid_screenshots"] = screenshot_status["invalid"][:3]
                    templates.append(template)
            except Exception as e:
                templates.append({
                    "type": "error",
                    "source_log": path,
                    "error": str(e),
                })
        return templates

    def run_visual_trace_report_from_logs(
        self,
        session_log_paths: list[str],
        include_causal_summaries: bool = False,
        include_failure_corrections: bool = False,
    ) -> VisualTraceCoverageReport:
        """Summarize screenshot/VLM/API visual evidence coverage in session logs."""
        from singularity.core.skill_extractor import SkillExtractor
        from singularity.core.skill_library import SkillLibrary

        report = VisualTraceCoverageReport()
        with tempfile.TemporaryDirectory() as skill_dir:
            skill_library = SkillLibrary(storage_path=skill_dir, persist=False)
            extractor = SkillExtractor(skill_library, auto_promote=False, promotion_critic=None)
            for path in session_log_paths:
                try:
                    events = self._load_session_events(path)
                except Exception as e:
                    report.errors.append(f"{path}: {e}")
                    continue
                candidates = []
                try:
                    candidates = extractor.extract_skill_candidates(path)
                    if include_causal_summaries:
                        candidates.extend(extractor.extract_causal_skill_candidates(path))
                    if include_failure_corrections:
                        candidates.extend(extractor.extract_failure_correction_candidates(path))
                except Exception as e:
                    report.errors.append(f"{path}: candidate extraction failed: {e}")
                report.cases.append(self._visual_trace_coverage_case(path, events, candidates))
        return report

    def run_exploration_trace_report_from_logs(self, session_log_paths: list[str]) -> ExplorationTraceReport:
        """Summarize open-world exploration coverage and failure modes in session logs."""
        report = ExplorationTraceReport()
        for path in session_log_paths:
            try:
                events = self._load_session_events(path)
                report.cases.append(self._exploration_trace_case(path, events))
            except Exception as e:
                report.errors.append(f"{path}: {e}")
        return report

    def run_world_model_report_from_logs(
        self,
        session_log_paths: list[str],
        cell_size: float = 8.0,
        limit: int = 12,
    ) -> WorldModelTraceReport:
        """Build AGI-Maze-style world-state summaries from session observations."""
        report = WorldModelTraceReport()
        safe_cell_size = max(1.0, float(cell_size or 8.0))
        safe_limit = max(1, int(limit or 12))
        for path in session_log_paths:
            try:
                events = self._load_session_events(path)
                report.cases.append(self._world_model_trace_case(path, events, safe_cell_size, safe_limit))
            except Exception as e:
                report.errors.append(f"{path}: {e}")
        return report

    def exploration_curriculum_feedback(self, report: ExplorationTraceReport) -> dict:
        """Aggregate exploration traces into a CurriculumManager-friendly feedback payload."""
        blocks = set()
        resources = set()
        entities = set()
        failure_categories = {}
        for case in report.cases:
            blocks.update(case.unique_block_types)
            resources.update(case.unique_resource_types)
            entities.update(case.unique_entity_types)
            for category, count in case.action_failure_categories.items():
                failure_categories[category] = failure_categories.get(category, 0) + int(count or 0)
        return {
            "log_count": report.log_count,
            "ready_log_count": report.ready_log_count,
            "discovered_blocks": sorted(blocks),
            "discovered_resources": sorted(resources),
            "discovered_entities": sorted(entities),
            "action_failure_categories": failure_categories,
            "low_movement_log_count": sum(
                1 for case in report.cases
                if case.observation_count > 0 and case.unique_position_count <= 1
            ),
            "hostile_encounter_count": report.hostile_encounter_count,
            "visual_observation_count": report.visual_observation_count,
            "path_distance": round(sum(case.path_distance for case in report.cases), 2),
        }

    def apply_exploration_feedback_to_curriculum(self, report: ExplorationTraceReport, curriculum_manager) -> dict:
        """Apply exploration-trace feedback to a CurriculumManager-like object."""
        feedback = self.exploration_curriculum_feedback(report)
        if hasattr(curriculum_manager, "record_exploration_feedback"):
            curriculum_manager.record_exploration_feedback(feedback)
        return feedback

    def world_model_curriculum_feedback(self, report: WorldModelTraceReport) -> dict:
        """Aggregate explicit world-model reports into curriculum feedback."""
        frontiers = []
        resource_hotspots = []
        danger_cells = []
        suggested_goals = []
        for case in report.cases:
            suggested_goals.extend(case.suggested_exploration_goals)
            for frontier in case.frontiers:
                frontiers.append({
                    "source_log": case.source_log,
                    "cell": frontier.get("cell", {}),
                    "center": frontier.get("center", {}),
                    "from_cell": frontier.get("from_cell", {}),
                    "direction": frontier.get("direction", ""),
                    "nearby_resources": frontier.get("nearby_resources", []),
                    "nearby_danger_count": frontier.get("nearby_danger_count", 0),
                    "score": frontier.get("score", 0),
                })
            for hotspot in case.resource_hotspots:
                resource_hotspots.append({
                    "source_log": case.source_log,
                    "resource": hotspot.get("resource", ""),
                    "cell": hotspot.get("cell", {}),
                    "center": hotspot.get("center", {}),
                    "danger_count": hotspot.get("danger_count", 0),
                    "visit_count": hotspot.get("visit_count", 0),
                })
            for cell in case.cells:
                if int(cell.get("danger_count", 0) or 0) <= 0:
                    continue
                danger_cells.append({
                    "source_log": case.source_log,
                    "cell": cell.get("cell", {}),
                    "center": cell.get("center", {}),
                    "danger_count": cell.get("danger_count", 0),
                    "entities": cell.get("entities", []),
                })
        frontiers.sort(key=lambda item: (-float(item.get("score", 0) or 0), str(item.get("source_log", ""))))
        resource_hotspots.sort(key=lambda item: (int(item.get("danger_count", 0) or 0), -int(item.get("visit_count", 0) or 0), str(item.get("resource", ""))))
        danger_cells.sort(key=lambda item: (-int(item.get("danger_count", 0) or 0), str(item.get("source_log", ""))))
        return {
            "frontier_count": report.frontier_count,
            "resource_hotspot_count": report.resource_hotspot_count,
            "danger_cell_count": report.danger_cell_count,
            "suggested_goals": self._dedupe_strings(suggested_goals)[:12],
            "frontiers": frontiers[:12],
            "resource_hotspots": resource_hotspots[:12],
            "danger_cells": danger_cells[:12],
        }

    def apply_world_model_feedback_to_curriculum(self, report: WorldModelTraceReport, curriculum_manager) -> dict:
        """Apply world-model frontier/resource feedback to a CurriculumManager-like object."""
        feedback = self.world_model_curriculum_feedback(report)
        if hasattr(curriculum_manager, "record_world_model_feedback"):
            curriculum_manager.record_world_model_feedback(feedback)
        return feedback

    def build_world_model_feedback_gate(
        self,
        world_model_report_paths: list[str] = None,
        world_model_reports: list[dict] = None,
        target: str = "world_model_curriculum_feedback",
        min_ready_logs: int = 1,
        min_frontiers: int = 1,
        min_actionable_items: int = 1,
    ) -> dict:
        """Gate world-model feedback before it can bias autonomous curriculum goals."""
        errors = []
        report_items = self._load_gate_payloads(
            world_model_reports or [],
            world_model_report_paths or [],
            errors,
            "world_model_report",
        )
        gate = {
            "type": "world_model_feedback_gate",
            "target": target,
            "readiness": "review",
            "decision": "hold_world_model_feedback",
            "reason": "world-model feedback needs structured frontier or hotspot evidence",
            "min_ready_logs": int(min_ready_logs or 0),
            "min_frontiers": int(min_frontiers or 0),
            "min_actionable_items": int(min_actionable_items or 0),
            "source_count": len(report_items),
            "log_count": 0,
            "ready_log_count": 0,
            "observation_count": 0,
            "unique_cell_count": 0,
            "frontier_count": 0,
            "resource_hotspot_count": 0,
            "danger_cell_count": 0,
            "suggested_goal_count": 0,
            "structured_frontier_count": 0,
            "structured_hotspot_count": 0,
            "actionable_item_count": 0,
            "checks": [],
            "sources": [],
            "missing": [],
            "policy_hints": [],
            "errors": list(errors),
        }
        if not report_items:
            gate["missing"].append("world_model_report")
            gate["checks"].append(self._gate_check(
                "world_model_feedback_gate",
                "world_model_report",
                "warn",
                "no world-model-report JSON was provided",
                {},
            ))
        for source, payload in report_items:
            summary = self._world_model_feedback_gate_source_summary(source, payload)
            gate["sources"].append(summary)
            gate["log_count"] += summary["log_count"]
            gate["ready_log_count"] += summary["ready_log_count"]
            gate["observation_count"] += summary["observation_count"]
            gate["unique_cell_count"] += summary["unique_cell_count"]
            gate["frontier_count"] += summary["frontier_count"]
            gate["resource_hotspot_count"] += summary["resource_hotspot_count"]
            gate["danger_cell_count"] += summary["danger_cell_count"]
            gate["suggested_goal_count"] += summary["suggested_goal_count"]
            gate["structured_frontier_count"] += summary["structured_frontier_count"]
            gate["structured_hotspot_count"] += summary["structured_hotspot_count"]
            gate["actionable_item_count"] += summary["actionable_item_count"]
            gate["errors"].extend(summary["errors"])
            status = "pass" if summary["ready"] else "warn"
            gate["checks"].append(self._gate_check(
                source,
                "world_model_report",
                status,
                summary["reason"],
                {
                    "ready_log_count": summary["ready_log_count"],
                    "frontier_count": summary["frontier_count"],
                    "resource_hotspot_count": summary["resource_hotspot_count"],
                    "actionable_item_count": summary["actionable_item_count"],
                },
            ))

        if gate["ready_log_count"] < gate["min_ready_logs"]:
            gate["missing"].append("ready_world_model_logs")
        if gate["frontier_count"] < gate["min_frontiers"]:
            gate["missing"].append("frontier_evidence")
        if gate["actionable_item_count"] < gate["min_actionable_items"]:
            gate["missing"].append("actionable_world_model_feedback")
        if gate["structured_frontier_count"] <= 0 and gate["structured_hotspot_count"] <= 0:
            gate["missing"].append("structured_cell_feedback")

        if gate["errors"]:
            gate["readiness"] = "error"
            gate["decision"] = "block_world_model_feedback"
            gate["reason"] = "world-model feedback gate inputs could not be loaded"
        elif gate["missing"]:
            gate["readiness"] = "review"
            gate["decision"] = "hold_world_model_feedback"
            gate["reason"] = "world-model feedback is missing required map evidence"
        else:
            gate["readiness"] = "approved"
            gate["decision"] = "allow_world_model_feedback"
            gate["reason"] = "structured frontier or hotspot evidence is ready for curriculum feedback"

        if gate["readiness"] != "approved":
            gate["policy_hints"].append("keep_world_model_feedback_review_only")
        if gate["missing"]:
            gate["policy_hints"].append("collect_more_world_model_exploration_traces")
        if gate["frontier_count"] and gate["structured_frontier_count"]:
            gate["policy_hints"].append("use_frontier_feedback_for_autonomous_curriculum")
        if gate["resource_hotspot_count"] and gate["structured_hotspot_count"]:
            gate["policy_hints"].append("use_resource_hotspots_with_danger_aware_routes")
        if gate["danger_cell_count"]:
            gate["policy_hints"].append("preserve_danger_cells_as_route_penalties")
        return gate

    def _world_model_feedback_gate_source_summary(self, source: str, payload: dict) -> dict:
        payload = payload if isinstance(payload, dict) else {}
        feedback = payload.get("world_model_feedback", payload) if isinstance(payload, dict) else {}
        feedback = feedback if isinstance(feedback, dict) else {}
        cases = payload.get("cases", []) if isinstance(payload.get("cases", []), list) else []
        source_errors = payload.get("errors", []) if isinstance(payload.get("errors", []), list) else []
        frontiers = feedback.get("frontiers", []) if isinstance(feedback.get("frontiers", []), list) else []
        hotspots = feedback.get("resource_hotspots", []) if isinstance(feedback.get("resource_hotspots", []), list) else []
        suggested_goals = feedback.get("suggested_goals", []) if isinstance(feedback.get("suggested_goals", []), list) else []
        structured_frontiers = [
            frontier for frontier in frontiers
            if isinstance(frontier, dict)
            and isinstance(frontier.get("cell"), dict)
            and isinstance(frontier.get("center"), dict)
            and str(frontier.get("direction") or "").strip()
        ]
        structured_hotspots = [
            hotspot for hotspot in hotspots
            if isinstance(hotspot, dict)
            and isinstance(hotspot.get("cell"), dict)
            and isinstance(hotspot.get("center"), dict)
            and str(hotspot.get("resource") or "").strip()
        ]
        actionable_count = len(suggested_goals) + len(structured_frontiers) + len(structured_hotspots)
        ready_logs = self._gate_int(payload.get("ready_log_count", 0))
        if ready_logs <= 0 and cases:
            ready_logs = sum(1 for case in cases if isinstance(case, dict) and case.get("ready_for_world_model_review"))
        frontier_count = self._gate_int(payload.get("frontier_count", 0)) or len(frontiers)
        hotspot_count = self._gate_int(payload.get("resource_hotspot_count", 0)) or len(hotspots)
        reason = "world-model report has actionable map feedback" if actionable_count else "world-model report has no actionable frontier or hotspot feedback"
        if source_errors:
            reason = "world-model report contains errors"
        return {
            "source": source,
            "ready": bool(ready_logs and actionable_count and not source_errors),
            "reason": reason,
            "log_count": self._gate_int(payload.get("log_count", len(cases))),
            "ready_log_count": ready_logs,
            "observation_count": self._gate_int(payload.get("observation_count", 0)),
            "unique_cell_count": self._gate_int(payload.get("unique_cell_count", 0)),
            "frontier_count": frontier_count,
            "resource_hotspot_count": hotspot_count,
            "danger_cell_count": self._gate_int(payload.get("danger_cell_count", 0)),
            "suggested_goal_count": len(suggested_goals),
            "structured_frontier_count": len(structured_frontiers),
            "structured_hotspot_count": len(structured_hotspots),
            "actionable_item_count": actionable_count,
            "errors": [str(error) for error in source_errors],
        }

    def build_coach_style_gate(
        self,
        coach_ablation_report_paths: list[str] = None,
        coach_ablation_reports: list[dict] = None,
        styles: list[str] = None,
        target: str = "coach_style_curriculum_bias",
        min_cases_per_style: int = 1,
        min_score_changed_per_style: int = 1,
        require_goal_change: bool = False,
    ) -> dict:
        """Gate advisory coaching styles before treating them as benchmark-ready."""
        errors = []
        report_items = self._load_gate_payloads(
            coach_ablation_reports or [],
            coach_ablation_report_paths or [],
            errors,
            "coach_style_ablation",
        )
        requested_styles = [str(style).strip().lower() for style in (styles or []) if str(style).strip()]
        gate = {
            "type": "coach_style_gate",
            "target": target,
            "readiness": "review",
            "decision": "hold_coach_style",
            "reason": "coach-style curriculum bias needs offline ablation evidence",
            "min_cases_per_style": int(min_cases_per_style or 0),
            "min_score_changed_per_style": int(min_score_changed_per_style or 0),
            "require_goal_change": bool(require_goal_change),
            "source_count": len(report_items),
            "case_count": 0,
            "changed_count": 0,
            "score_changed_count": 0,
            "styles": requested_styles,
            "style_case_counts": {},
            "style_changed_counts": {},
            "style_score_changed_counts": {},
            "approved_styles": [],
            "review_styles": [],
            "checks": [],
            "sources": [],
            "missing": [],
            "policy_hints": [],
            "errors": list(errors),
        }
        if not report_items:
            gate["missing"].append("coach_style_ablation_report")
            gate["checks"].append(self._gate_check(
                "coach_style_gate",
                "coach_style_ablation",
                "warn",
                "no coach-style-ablation JSON was provided",
                {},
            ))
        for source, payload in report_items:
            summary = self._coach_style_gate_source_summary(source, payload, requested_styles)
            gate["sources"].append(summary)
            gate["case_count"] += summary["case_count"]
            gate["changed_count"] += summary["changed_count"]
            gate["score_changed_count"] += summary["score_changed_count"]
            for style, count in summary["style_case_counts"].items():
                gate["style_case_counts"][style] = gate["style_case_counts"].get(style, 0) + count
            for style, count in summary["style_changed_counts"].items():
                gate["style_changed_counts"][style] = gate["style_changed_counts"].get(style, 0) + count
            for style, count in summary["style_score_changed_counts"].items():
                gate["style_score_changed_counts"][style] = gate["style_score_changed_counts"].get(style, 0) + count
            gate["errors"].extend(summary["errors"])
            status = "pass" if summary["ready"] else "warn"
            gate["checks"].append(self._gate_check(
                source,
                "coach_style_ablation",
                status,
                summary["reason"],
                {
                    "case_count": summary["case_count"],
                    "changed_count": summary["changed_count"],
                    "score_changed_count": summary["score_changed_count"],
                    "styles": summary["styles"],
                },
            ))

        expected_styles = requested_styles or sorted(gate["style_case_counts"].keys())
        if not expected_styles:
            gate["missing"].append("style_evidence")
        for style in expected_styles:
            case_count = int(gate["style_case_counts"].get(style, 0) or 0)
            score_changed = int(gate["style_score_changed_counts"].get(style, 0) or 0)
            goal_changed = int(gate["style_changed_counts"].get(style, 0) or 0)
            missing = []
            if case_count < gate["min_cases_per_style"]:
                missing.append("cases")
            if score_changed < gate["min_score_changed_per_style"]:
                missing.append("score_effect")
            if gate["require_goal_change"] and goal_changed <= 0:
                missing.append("goal_change")
            if missing:
                gate["review_styles"].append({"style": style, "missing": missing})
            else:
                gate["approved_styles"].append(style)

        if gate["review_styles"]:
            gate["missing"].append("style_readiness")
        if gate["errors"]:
            gate["readiness"] = "error"
            gate["decision"] = "block_coach_style"
            gate["reason"] = "coach-style gate inputs could not be loaded"
        elif gate["missing"]:
            gate["readiness"] = "review"
            gate["decision"] = "hold_coach_style"
            gate["reason"] = "coach-style bias needs stronger offline ablation evidence"
        else:
            gate["readiness"] = "approved"
            gate["decision"] = "allow_coach_style"
            gate["reason"] = "coach-style curriculum bias has offline ablation evidence"

        if gate["readiness"] != "approved":
            gate["policy_hints"].append("keep_coach_style_manual_or_review_only")
        if gate["approved_styles"]:
            gate["policy_hints"].append("styles_ready_for_benchmark_preflight")
        if gate["review_styles"]:
            gate["policy_hints"].append("collect_more_coach_style_ablation_cases")
        return gate

    def _coach_style_gate_source_summary(self, source: str, payload: dict, requested_styles: list[str]) -> dict:
        payload = payload if isinstance(payload, dict) else {}
        cases = payload.get("cases", []) if isinstance(payload.get("cases", []), list) else []
        source_errors = payload.get("errors", []) if isinstance(payload.get("errors", []), list) else []
        style_case_counts = {}
        style_changed_counts = {}
        style_score_changed_counts = {}
        changed_count = 0
        score_changed_count = 0
        for case in cases:
            if not isinstance(case, dict):
                continue
            style = str(case.get("style") or "").strip().lower()
            if requested_styles and style not in requested_styles:
                continue
            if not style:
                style = "unknown"
            style_case_counts[style] = style_case_counts.get(style, 0) + 1
            if bool(case.get("changed")):
                changed_count += 1
                style_changed_counts[style] = style_changed_counts.get(style, 0) + 1
            score_delta = self._gate_float_or_none(case.get("score_delta"))
            if score_delta is None:
                score_delta = float(case.get("styled_score", 0) or 0) - float(case.get("baseline_score", 0) or 0)
            if abs(float(score_delta or 0.0)) > 0.0001:
                score_changed_count += 1
                style_score_changed_counts[style] = style_score_changed_counts.get(style, 0) + 1
        case_count = sum(style_case_counts.values())
        reason = "coach-style ablation contains score-changing style evidence" if score_changed_count else "coach-style ablation has no score-changing style evidence"
        if source_errors:
            reason = "coach-style ablation contains errors"
        return {
            "source": source,
            "ready": bool(case_count and score_changed_count and not source_errors),
            "reason": reason,
            "case_count": case_count,
            "changed_count": changed_count,
            "score_changed_count": score_changed_count,
            "styles": sorted(style_case_counts),
            "style_case_counts": style_case_counts,
            "style_changed_counts": style_changed_counts,
            "style_score_changed_counts": style_score_changed_counts,
            "errors": [str(error) for error in source_errors],
        }

    def run_self_evolution_report_from_logs(self, session_log_paths: list[str]) -> SelfEvolutionTraceReport:
        """Summarize MineEvolve-style monitor/inducer/adaptor signals in session logs."""
        report = SelfEvolutionTraceReport()
        for path in session_log_paths:
            try:
                events = self._load_session_events(path)
                report.cases.append(self._self_evolution_trace_case(path, events))
            except Exception as e:
                report.errors.append(f"{path}: {e}")
        return report

    def run_plan_action_compliance_report_from_logs(self, session_log_paths: list[str]) -> PlanActionComplianceReport:
        """Summarize whether executable actions follow the preceding planner output."""
        report = PlanActionComplianceReport()
        for path in session_log_paths:
            try:
                events = self._load_session_events(path)
                report.cases.append(self._plan_action_compliance_case(path, events))
            except Exception as e:
                report.errors.append(f"{path}: {e}")
        return report

    def plan_action_compliance_feedback(self, report: PlanActionComplianceReport) -> dict:
        """Convert plan-action gaps into advisory planner/runtime policy hints."""
        policy_hints = []
        if report.missing_planned_action_count:
            policy_hints.append({
                "plan_action_policy": "repair_or_remind_unexecuted_plan_steps",
                "priority": "high",
                "reason": "planned actions were not observed before the next plan window",
                "count": report.missing_planned_action_count,
            })
        if report.order_violation_count:
            policy_hints.append({
                "plan_action_policy": "preserve_plan_order_or_replan_explicitly",
                "priority": "medium",
                "reason": "planned actions appeared in the window but not in planner order",
                "count": report.order_violation_count,
            })
        if report.unplanned_action_count:
            policy_hints.append({
                "plan_action_policy": "explain_unplanned_runtime_actions",
                "priority": "medium",
                "reason": "executed actions were not present in the preceding plan window",
                "count": report.unplanned_action_count,
            })
        if report.empty_plan_count:
            policy_hints.append({
                "plan_action_policy": "avoid_empty_executable_plans",
                "priority": "high",
                "reason": "planner emitted empty action lists that cannot drive execution",
                "count": report.empty_plan_count,
            })
        return {
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
            "policy_hints": policy_hints,
        }

    def run_terminal_commitment_report_from_logs(self, session_log_paths: list[str]) -> TerminalCommitmentReport:
        """Summarize VIGIL-style world completion versus terminal completion claims."""
        report = TerminalCommitmentReport()
        for path in session_log_paths:
            try:
                events = self._load_session_events(path)
                segments = self._session_goal_segments(events)
                if not segments:
                    report.errors.append(f"{path}: missing goal_start or goal_end goal")
                    continue
                for goal_index, (goal, segment_events) in enumerate(segments, start=1):
                    report.cases.append(self._terminal_commitment_case(path, goal, goal_index, segment_events))
            except Exception as e:
                report.errors.append(f"{path}: {e}")
        return report

    def terminal_commitment_feedback(self, report: TerminalCommitmentReport) -> dict:
        """Convert terminal commitment outcomes into advisory verifier/runtime hints."""
        policy_hints = []
        if report.unsupported_commitment_count:
            policy_hints.append({
                "terminal_commitment_policy": "reject_unsupported_completion_claims",
                "priority": "high",
                "reason": "agent reported completion while verifier/world evidence was missing or failed",
                "count": report.unsupported_commitment_count,
            })
        if report.post_attainment_drift_count:
            policy_hints.append({
                "terminal_commitment_policy": "commit_when_world_state_is_verified",
                "priority": "medium",
                "reason": "world state appears achieved but the run did not terminate with a correct completion report",
                "count": report.post_attainment_drift_count,
            })
        if report.missed_execution_count:
            policy_hints.append({
                "terminal_commitment_policy": "repair_execution_before_completion_retry",
                "priority": "high",
                "reason": "neither world completion nor terminal completion was achieved",
                "count": report.missed_execution_count,
            })
        if report.unknown_world_count:
            policy_hints.append({
                "terminal_commitment_policy": "collect_stronger_terminal_evidence",
                "priority": "medium",
                "reason": "terminal world completion could not be deterministically established",
                "count": report.unknown_world_count,
            })
        return {
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
            "policy_hints": policy_hints,
        }

    def run_action_verification_report_from_logs(self, session_log_paths: list[str]) -> ActionVerificationTraceReport:
        """Replay logged actions through the deterministic action verifier."""
        report = ActionVerificationTraceReport()
        for path in session_log_paths:
            try:
                events = self._load_session_events(path)
                report.cases.append(self._action_verification_trace_case(path, events))
            except Exception as e:
                report.errors.append(f"{path}: {e}")
        return report

    def action_verification_feedback(self, report: ActionVerificationTraceReport) -> dict:
        """Convert verifier replay outcomes into advisory action-selection hints."""
        policy_hints = []
        if report.rejected_action_count:
            policy_hints.append({
                "action_verification_policy": "block_rejected_actions_before_execution",
                "priority": "high",
                "reason": "deterministic action verifier found actions with missing materials, tools, or targets",
                "count": report.rejected_action_count,
            })
        if report.failed_without_reject_count:
            policy_hints.append({
                "action_verification_policy": "expand_verifier_coverage_for_failed_actions",
                "priority": "medium",
                "reason": "some failed actions were not rejected by deterministic verification",
                "count": report.failed_without_reject_count,
            })
        if report.rejected_success_count:
            policy_hints.append({
                "action_verification_policy": "audit_overconservative_rejections",
                "priority": "medium",
                "reason": "some verifier-rejected actions later appeared successful in logs",
                "count": report.rejected_success_count,
            })
        return {
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
            "policy_hints": policy_hints,
        }

    def run_action_candidate_report_from_logs(self, session_log_paths: list[str]) -> ActionCandidateSelectionTraceReport:
        """Replay logged actions through verifier-guided candidate selection."""
        report = ActionCandidateSelectionTraceReport()
        for path in session_log_paths:
            try:
                events = self._load_session_events(path)
                report.cases.append(self._action_candidate_selection_trace_case(path, events))
            except Exception as e:
                report.errors.append(f"{path}: {e}")
        return report

    def action_candidate_feedback(self, report: ActionCandidateSelectionTraceReport) -> dict:
        """Convert candidate-selection replay outcomes into runtime policy hints."""
        policy_hints = []
        if report.repaired_reject_count:
            policy_hints.append({
                "action_candidate_policy": "enable_repair_candidate_selection_for_rejected_actions",
                "priority": "high",
                "reason": "selector found verifier-feasible alternatives for rejected planner actions",
                "count": report.repaired_reject_count,
            })
        if report.unchanged_reject_count:
            policy_hints.append({
                "action_candidate_policy": "expand_repair_candidate_generation",
                "priority": "medium",
                "reason": "some rejected planner actions still had no feasible repair candidate",
                "count": report.unchanged_reject_count,
            })
        if report.changed_selection_count:
            policy_hints.append({
                "action_candidate_policy": "audit_candidate_replacements_against_goal_progress",
                "priority": "medium",
                "reason": "changed selections should be checked against later observations before broadening replacement rules",
                "count": report.changed_selection_count,
            })
        return {
            "log_count": report.log_count,
            "ready_log_count": report.ready_log_count,
            "action_count": report.action_count,
            "original_reject_count": report.original_reject_count,
            "changed_selection_count": report.changed_selection_count,
            "repaired_reject_count": report.repaired_reject_count,
            "unchanged_reject_count": report.unchanged_reject_count,
            "selection_change_rate": report.selection_change_rate,
            "repaired_reject_rate": report.repaired_reject_rate,
            "policy_hints": policy_hints,
        }

    def run_action_value_report_from_logs(self, session_log_paths: list[str]) -> ActionValueTraceReport:
        """Aggregate action outcome value profiles from session logs."""
        report = ActionValueTraceReport()
        for path in session_log_paths:
            try:
                events = self._load_session_events(path)
                report.cases.append(self._action_value_trace_case(path, events))
            except Exception as e:
                report.errors.append(f"{path}: {e}")
        return report

    def action_value_feedback(self, report: ActionValueTraceReport) -> dict:
        """Convert action outcome profiles into reusable candidate scoring feedback."""
        items = self._aggregate_action_value_items(report)
        transition_items = self._aggregate_action_state_transition_items(report)
        high_value = [item for item in items if item.get("attempts", 0) >= 2 and item.get("value_score", 0) >= 0.7]
        low_value = [item for item in items if item.get("attempts", 0) >= 2 and item.get("value_score", 1) <= 0.35]
        positive_transitions = [
            item for item in transition_items
            if item.get("attempts", 0) >= 1 and item.get("avg_state_value_delta", 0) > 0.05
        ]
        negative_transitions = [
            item for item in transition_items
            if item.get("attempts", 0) >= 1 and item.get("avg_state_value_delta", 0) < -0.05
        ]
        policy_hints = []
        if high_value:
            policy_hints.append({
                "action_value_policy": "prefer_high_value_action_signatures",
                "priority": "medium",
                "reason": "some action signatures repeatedly succeed and can bias verifier-guided candidate ranking",
                "count": len(high_value),
            })
        if low_value:
            policy_hints.append({
                "action_value_policy": "demote_low_value_action_signatures",
                "priority": "medium",
                "reason": "some action signatures repeatedly fail and should not win candidate tie-breaks",
                "count": len(low_value),
            })
        if report.failure_correction_pair_count:
            policy_hints.append({
                "action_value_policy": "mine_failure_correction_pairs_for_repair_candidates",
                "priority": "high",
                "reason": "failed actions followed by successful recovery actions can seed future repair candidates",
                "count": report.failure_correction_pair_count,
            })
        if transition_items:
            policy_hints.append({
                "action_value_policy": "score_actions_by_state_transition_value",
                "priority": "high" if negative_transitions or report.no_progress_transition_count else "medium",
                "reason": "before/after observations expose whether accepted actions actually improved world state",
                "count": len(transition_items),
            })
        if report.low_confidence_transition_count:
            policy_hints.append({
                "action_value_policy": "collect_action_local_transition_windows",
                "priority": "high",
                "reason": "some transition values rely on shared or wide observation windows and should not drive runtime ranking yet",
                "count": report.low_confidence_transition_count,
            })
        return {
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
            "action_value_items": items,
            "high_value_items": high_value[:20],
            "low_value_items": low_value[:20],
            "failure_correction_pairs": [
                pair for case in report.cases for pair in case.failure_correction_pairs
            ][:40],
            "state_transition_value_items": transition_items,
            "positive_state_transition_items": positive_transitions[:20],
            "negative_state_transition_items": negative_transitions[:20],
            "policy_hints": policy_hints,
        }

    def run_knowledge_correction_report_from_logs(
        self,
        session_log_paths: list[str],
        min_failure_repeats: int = 2,
        max_failure_value_score: float = 0.35,
    ) -> KnowledgeCorrectionTraceReport:
        """Mine XENON-style dependency and failed-action knowledge corrections from session logs."""
        report = KnowledgeCorrectionTraceReport()
        for path in session_log_paths:
            try:
                events = self._load_session_events(path)
                action_value_case = self._action_value_trace_case(path, events)
                report.cases.append(self._knowledge_correction_case_from_action_value(
                    action_value_case,
                    min_failure_repeats=min_failure_repeats,
                    max_failure_value_score=max_failure_value_score,
                ))
            except Exception as e:
                report.errors.append(f"{path}: {e}")
        return report

    def knowledge_correction_feedback(self, report: KnowledgeCorrectionTraceReport) -> dict:
        """Convert correction candidates into reviewable knowledge-memory feedback."""
        dependency_corrections = [
            item for case in report.cases for item in case.dependency_corrections
        ]
        failure_action_memories = [
            item for case in report.cases for item in case.failure_action_memories
        ]
        policy_hints = []
        if dependency_corrections:
            policy_hints.append({
                "knowledge_correction_policy": "review_dependency_graph_corrections",
                "priority": "high",
                "reason": "failed action followed by successful recovery suggests a missing prerequisite or ordering edge",
                "count": len(dependency_corrections),
            })
        if failure_action_memories:
            policy_hints.append({
                "knowledge_correction_policy": "review_failed_action_memories",
                "priority": "high",
                "reason": "repeated failed or no-progress actions should become avoid/replan memories before replay",
                "count": len(failure_action_memories),
            })
        if report.low_confidence_transition_count:
            policy_hints.append({
                "knowledge_correction_policy": "collect_action_local_state_windows",
                "priority": "medium",
                "reason": "some candidate knowledge corrections depend on low-confidence before/after state windows",
                "count": report.low_confidence_transition_count,
            })
        return {
            "log_count": report.log_count,
            "ready_log_count": report.ready_log_count,
            "action_count": report.action_count,
            "failure_action_count": report.failure_action_count,
            "repeated_failure_signature_count": report.repeated_failure_signature_count,
            "recovery_pair_count": report.recovery_pair_count,
            "dependency_correction_count": report.dependency_correction_count,
            "failure_action_memory_count": report.failure_action_memory_count,
            "low_confidence_transition_count": report.low_confidence_transition_count,
            "dependency_corrections": dependency_corrections[:40],
            "failure_action_memories": failure_action_memories[:40],
            "policy_hints": policy_hints,
        }

    def build_knowledge_correction_gate(
        self,
        knowledge_correction_reports: Optional[list[dict]] = None,
        knowledge_correction_report_paths: Optional[list[str]] = None,
        target: str = "planner_knowledge_correction_feedback",
        min_ready_logs: int = 1,
        min_corrections: int = 1,
    ) -> dict:
        """Gate XENON-style knowledge-correction reports before planner/runtime use."""
        report = {
            "type": "knowledge_correction_gate",
            "target": target,
            "readiness": "review",
            "decision": "hold_knowledge_corrections_for_review",
            "reason": "knowledge corrections require enough reviewable evidence",
            "thresholds": {
                "min_ready_logs": int(min_ready_logs),
                "min_corrections": int(min_corrections),
            },
            "source_count": 0,
            "log_count": 0,
            "ready_log_count": 0,
            "action_count": 0,
            "failure_action_count": 0,
            "dependency_correction_count": 0,
            "failure_action_memory_count": 0,
            "correction_count": 0,
            "policy_hints": [],
            "sources": [],
            "checks": [],
            "missing": [],
            "errors": [],
        }
        items = self._load_gate_payloads(
            knowledge_correction_reports or [],
            knowledge_correction_report_paths or [],
            report["errors"],
            "knowledge_correction_report",
        )
        report["source_count"] = len(items)
        if not items:
            report["missing"].append("knowledge_correction_report")

        for source, payload in items:
            current = payload.get("knowledge_correction_feedback", payload) if isinstance(payload, dict) else {}
            if not isinstance(current, dict):
                report["errors"].append(f"{source}: knowledge correction report must be a JSON object")
                continue
            ready_logs = self._gate_int(current.get("ready_log_count", 0))
            dependency_count = self._gate_int(current.get("dependency_correction_count", 0))
            failure_memory_count = self._gate_int(current.get("failure_action_memory_count", 0))
            correction_count = dependency_count + failure_memory_count
            source_summary = {
                "source": source,
                "log_count": self._gate_int(current.get("log_count", 0)),
                "ready_log_count": ready_logs,
                "action_count": self._gate_int(current.get("action_count", 0)),
                "failure_action_count": self._gate_int(current.get("failure_action_count", 0)),
                "dependency_correction_count": dependency_count,
                "failure_action_memory_count": failure_memory_count,
                "correction_count": correction_count,
            }
            report["sources"].append(source_summary)
            report["log_count"] += source_summary["log_count"]
            report["ready_log_count"] += ready_logs
            report["action_count"] += source_summary["action_count"]
            report["failure_action_count"] += source_summary["failure_action_count"]
            report["dependency_correction_count"] += dependency_count
            report["failure_action_memory_count"] += failure_memory_count
            report["correction_count"] += correction_count
            status = "pass" if ready_logs and correction_count else "warn"
            detail = (
                "knowledge correction report has reviewable corrections"
                if status == "pass"
                else "knowledge correction report lacks ready logs or correction candidates"
            )
            report["checks"].append(self._gate_check(
                source,
                "knowledge_correction_report",
                status,
                detail,
                source_summary,
            ))

        if report["ready_log_count"] < int(min_ready_logs):
            report["missing"].append("ready_knowledge_correction_logs")
        if report["correction_count"] < int(min_corrections):
            report["missing"].append("knowledge_correction_candidates")

        if report["errors"]:
            report["readiness"] = "error"
            report["decision"] = "do_not_load_knowledge_corrections"
            report["reason"] = "knowledge correction inputs could not be loaded"
        elif report["missing"]:
            report["readiness"] = "review"
            report["decision"] = "hold_knowledge_corrections_for_review"
            report["reason"] = "knowledge correction evidence is incomplete"
            report["policy_hints"].append("collect_more_failed_action_and_recovery_traces")
        else:
            report["readiness"] = "approved"
            report["decision"] = "allow_reviewed_knowledge_correction_feedback"
            report["reason"] = "reviewable dependency and failed-action correction evidence is present"
            report["policy_hints"].extend([
                "review_dependency_graph_corrections",
                "review_failed_action_memories",
            ])
        return report

    def build_action_value_transition_gate(
        self,
        action_value_reports: list[dict] = None,
        action_value_report_paths: list[str] = None,
        target: str = "action_value_transition_feedback",
        min_trusted_items: int = 1,
        min_trusted_transitions: int = 1,
        min_transition_confidence: float = 0.75,
        max_low_confidence_rate: float = 0.25,
        max_item_low_confidence_rate: float = 0.25,
    ) -> dict:
        """Gate ASV-style transition values before they influence runtime action ranking."""
        report = {
            "type": "action_value_transition_gate",
            "target": target,
            "readiness": "review",
            "decision": "hold_for_review",
            "reason": "insufficient trusted transition-value evidence",
            "thresholds": {
                "min_trusted_items": int(min_trusted_items),
                "min_trusted_transitions": int(min_trusted_transitions),
                "min_transition_confidence": float(min_transition_confidence),
                "max_low_confidence_rate": float(max_low_confidence_rate),
                "max_item_low_confidence_rate": float(max_item_low_confidence_rate),
            },
            "source_count": 0,
            "state_transition_count": 0,
            "trusted_item_count": 0,
            "trusted_transition_count": 0,
            "low_confidence_transition_count": 0,
            "low_confidence_rate": 0.0,
            "trusted_items": [],
            "review_items": [],
            "checks": [],
            "missing": [],
            "policy_hints": [],
            "errors": [],
        }
        sources = []
        for index, payload in enumerate(action_value_reports or []):
            if isinstance(payload, dict):
                sources.append((f"inline:{index}", payload))
        for path in action_value_report_paths or []:
            if not path:
                continue
            try:
                with open(path, "r", encoding="utf-8-sig") as f:
                    sources.append((path, json.load(f)))
            except Exception as e:
                report["errors"].append(f"{path}: {e}")

        report["source_count"] = len(sources)
        if not sources:
            report["missing"].append("action_value_report")

        thresholds = report["thresholds"]
        for source, payload in sources:
            check = self._action_value_transition_gate_check(source, payload, thresholds)
            report["checks"].append(check)
            metrics = check.get("metrics", {})
            report["state_transition_count"] += int(metrics.get("state_transition_count") or 0)
            report["trusted_item_count"] += int(metrics.get("trusted_item_count") or 0)
            report["trusted_transition_count"] += int(metrics.get("trusted_transition_count") or 0)
            report["low_confidence_transition_count"] += int(metrics.get("low_confidence_transition_count") or 0)
            report["trusted_items"].extend(metrics.get("trusted_items", [])[:8])
            report["review_items"].extend(metrics.get("review_items", [])[:8])

        if report["state_transition_count"]:
            report["low_confidence_rate"] = round(
                report["low_confidence_transition_count"] / max(1, report["state_transition_count"]),
                3,
            )

        failed_checks = [check for check in report["checks"] if check.get("status") == "fail"]
        warn_checks = [check for check in report["checks"] if check.get("status") == "warn"]
        if report["errors"]:
            report["readiness"] = "error"
            report["decision"] = "reject"
            report["reason"] = "action-value transition gate input could not be read"
        elif failed_checks:
            report["readiness"] = "rejected"
            report["decision"] = "reject"
            report["reason"] = failed_checks[0].get("detail", "transition gate failed")
        elif (
            report["trusted_item_count"] >= int(min_trusted_items)
            and report["trusted_transition_count"] >= int(min_trusted_transitions)
            and report["low_confidence_rate"] <= float(max_low_confidence_rate)
            and not warn_checks
        ):
            report["readiness"] = "approved"
            report["decision"] = "approve"
            report["reason"] = "trusted transition values are ready for conservative runtime scoring"
            report["policy_hints"].append("load_trusted_transition_values")
        else:
            report["readiness"] = "review"
            report["decision"] = "hold_for_review"
            if report["state_transition_count"] <= 0:
                report["missing"].append("state_transition_value_items")
                report["reason"] = "no state-transition value evidence was found"
            elif report["trusted_item_count"] < int(min_trusted_items):
                report["missing"].append("trusted_transition_items")
                report["reason"] = "not enough trusted transition-value items"
            elif report["trusted_transition_count"] < int(min_trusted_transitions):
                report["missing"].append("trusted_transition_count")
                report["reason"] = "not enough trusted transition attempts"
            elif report["low_confidence_rate"] > float(max_low_confidence_rate):
                report["missing"].append("low_confidence_rate_below_threshold")
                report["reason"] = "too many transition windows are low confidence"
            else:
                report["reason"] = "transition-value evidence needs review"
            report["policy_hints"].append("collect_action_local_transition_windows")
        report["trusted_items"] = report["trusted_items"][:20]
        report["review_items"] = report["review_items"][:20]
        return report

    def build_action_value_transition_evaluator_report(
        self,
        action_value_reports: list[dict] = None,
        action_value_report_paths: list[str] = None,
        session_log_paths: list[str] = None,
        evaluator=None,
        limit: int = 40,
        min_transition_confidence: float = 0.75,
        min_evaluator_confidence: float = 0.65,
        min_evaluated_transitions: int = 1,
        min_label_agreement_rate: float = 0.75,
        max_avg_score_delta: float = 0.25,
        max_large_score_delta_rate: float = 0.25,
    ) -> dict:
        """Compare deterministic Minecraft transition labels against a state-grounded evaluator."""
        report = {
            "type": "action_value_transition_evaluator_report",
            "readiness": "review",
            "decision": "hold_for_review",
            "reason": "state-grounded transition evaluator comparison is incomplete",
            "evaluator": "llm_state_grounded" if evaluator else "missing",
            "thresholds": {
                "limit": int(limit),
                "min_transition_confidence": float(min_transition_confidence),
                "min_evaluator_confidence": float(min_evaluator_confidence),
                "min_evaluated_transitions": int(min_evaluated_transitions),
                "min_label_agreement_rate": float(min_label_agreement_rate),
                "max_avg_score_delta": float(max_avg_score_delta),
                "max_large_score_delta_rate": float(max_large_score_delta_rate),
            },
            "source_count": 0,
            "transition_count": 0,
            "evaluated_count": 0,
            "skipped_count": 0,
            "agreement_count": 0,
            "conflict_count": 0,
            "large_score_delta_count": 0,
            "agreement_rate": 0.0,
            "conflict_rate": 0.0,
            "large_score_delta_rate": 0.0,
            "avg_abs_score_delta": 0.0,
            "comparison_cases": [],
            "conflicts": [],
            "skipped": [],
            "missing": [],
            "policy_hints": [],
            "errors": [],
        }
        sources, load_errors = self._action_value_transition_evaluator_sources(
            action_value_reports=action_value_reports,
            action_value_report_paths=action_value_report_paths,
            session_log_paths=session_log_paths,
        )
        report["source_count"] = len(sources)
        report["errors"].extend(load_errors)
        if not sources:
            report["missing"].append("action_value_transition_sources")
        if evaluator is None:
            report["missing"].append("llm_evaluator")

        transitions = []
        for source, payload in sources:
            transitions.extend(self._action_value_transition_items_from_payload(source, payload))
        report["transition_count"] = len(transitions)
        if not transitions:
            report["missing"].append("state_transition_items")

        score_deltas = []
        max_items = max(0, int(limit))
        for item in transitions[:max_items or len(transitions)]:
            skip_reason = self._transition_evaluator_skip_reason(item, min_transition_confidence)
            if skip_reason:
                report["skipped_count"] += 1
                if len(report["skipped"]) < 12:
                    report["skipped"].append(self._transition_evaluator_skip_record(item, skip_reason))
                continue
            if evaluator is None:
                continue
            evaluation = self._evaluate_action_value_transition_with_llm(evaluator, item)
            if evaluation.get("error"):
                report["skipped_count"] += 1
                if len(report["skipped"]) < 12:
                    record = self._transition_evaluator_skip_record(item, "evaluator_error")
                    record["error"] = evaluation.get("error")
                    report["skipped"].append(record)
                continue
            evaluator_confidence = self._safe_float(evaluation.get("confidence"), 0.0)
            if evaluator_confidence < float(min_evaluator_confidence):
                report["skipped_count"] += 1
                if len(report["skipped"]) < 12:
                    record = self._transition_evaluator_skip_record(item, "low_evaluator_confidence")
                    record["evaluator_confidence"] = round(evaluator_confidence, 3)
                    report["skipped"].append(record)
                continue

            deterministic_label = self._normalize_transition_label(item.get("transition_label"))
            evaluator_label = self._normalize_transition_label(evaluation.get("label"))
            deterministic_score = self._safe_float(item.get("transition_value_score"), 0.5)
            evaluator_score = max(0.0, min(1.0, self._safe_float(evaluation.get("score"), 0.5)))
            score_delta = round(abs(deterministic_score - evaluator_score), 3)
            score_deltas.append(score_delta)
            agreement = deterministic_label == evaluator_label
            large_delta = score_delta > float(max_avg_score_delta)
            report["evaluated_count"] += 1
            if agreement:
                report["agreement_count"] += 1
            else:
                report["conflict_count"] += 1
            if large_delta:
                report["large_score_delta_count"] += 1
            case = {
                "source_log": item.get("source_log", ""),
                "event_index": item.get("event_index"),
                "signature": item.get("signature", "unknown"),
                "goal": item.get("goal", ""),
                "deterministic_label": deterministic_label,
                "evaluator_label": evaluator_label,
                "deterministic_score": round(deterministic_score, 3),
                "evaluator_score": round(evaluator_score, 3),
                "score_delta": score_delta,
                "agreement": agreement,
                "large_score_delta": large_delta,
                "evaluator_confidence": round(evaluator_confidence, 3),
                "evaluator_reason": str(evaluation.get("reason") or "")[:240],
                "deterministic_reasons": item.get("reasons", [])[:8] if isinstance(item.get("reasons", []), list) else [],
            }
            if len(report["comparison_cases"]) < 20:
                report["comparison_cases"].append(case)
            if (not agreement or large_delta) and len(report["conflicts"]) < 20:
                report["conflicts"].append(case)

        if report["evaluated_count"]:
            report["agreement_rate"] = round(report["agreement_count"] / report["evaluated_count"], 3)
            report["conflict_rate"] = round(report["conflict_count"] / report["evaluated_count"], 3)
            report["large_score_delta_rate"] = round(report["large_score_delta_count"] / report["evaluated_count"], 3)
            report["avg_abs_score_delta"] = round(sum(score_deltas) / max(1, len(score_deltas)), 3)

        if report["errors"]:
            report["readiness"] = "error"
            report["decision"] = "reject"
            report["reason"] = "transition evaluator inputs could not be read"
        elif evaluator is None:
            report["reason"] = "state-grounded LLM evaluator is not configured"
            report["policy_hints"].append("configure_state_grounded_transition_evaluator")
        elif report["evaluated_count"] < int(min_evaluated_transitions):
            report["reason"] = "not enough high-confidence transitions were evaluated"
            report["missing"].append("evaluated_transition_count")
            report["policy_hints"].append("collect_action_local_transition_windows")
        elif (
            report["agreement_rate"] >= float(min_label_agreement_rate)
            and report["avg_abs_score_delta"] <= float(max_avg_score_delta)
            and report["large_score_delta_rate"] <= float(max_large_score_delta_rate)
        ):
            report["readiness"] = "approved"
            report["decision"] = "approve_comparison"
            report["reason"] = "state-grounded evaluator agrees with deterministic transition labels"
            report["policy_hints"].append("allow_llm_checked_transition_value_review")
        else:
            report["reason"] = "state-grounded evaluator found transition-label or score conflicts"
            report["policy_hints"].append("review_transition_label_conflicts")
            report["policy_hints"].append("compare_llm_and_deterministic_transition_deltas")
        return report

    def self_evolution_feedback(self, report: SelfEvolutionTraceReport) -> dict:
        """Aggregate execution feedback into reusable self-evolution policy hints."""
        typed_feedback = {}
        failure_categories = {}
        action_types = {}
        remedies = []
        adaptor_recommendations = []
        for case in report.cases:
            self._merge_counts(typed_feedback, case.typed_feedback_counts)
            self._merge_counts(failure_categories, case.action_failure_categories)
            self._merge_counts(action_types, case.action_type_counts)
            remedies.extend(case.remedy_candidates)
            adaptor_recommendations.extend(case.adaptor_recommendations)

        policy_hints = []
        if report.stagnation_signal_count:
            policy_hints.append({
                "self_evolution_policy": "repair_stagnant_plan_suffix",
                "priority": "high",
                "reason": "execution produced repeated no-progress or repeated-failure signals",
                "count": report.stagnation_signal_count,
            })
        if report.no_progress_success_count:
            policy_hints.append({
                "self_evolution_policy": "verify_successful_actions_with_state_delta",
                "priority": "high" if report.no_progress_success_count >= max(3, report.action_count // 4) else "medium",
                "reason": "successful action returns did not produce observed state, inventory, or verifier progress",
                "count": report.no_progress_success_count,
            })
        if report.zero_action_failure_count:
            policy_hints.append({
                "self_evolution_policy": "repair_blocked_plan_or_prerequisite_fallback",
                "priority": "high",
                "reason": "failed logs contain repeated blocked or empty plans before any executable action",
                "count": report.zero_action_failure_count,
            })
        if report.failed_action_count:
            policy_hints.append({
                "self_evolution_policy": "induce_failure_remedies",
                "priority": "high" if report.failed_action_count >= report.action_count / 2 else "medium",
                "reason": "failed actions should become typed remedy candidates before retry",
                "count": report.failed_action_count,
            })
        if typed_feedback.get("monitor_inventory_gain", 0) or typed_feedback.get("monitor_goal_success", 0):
            policy_hints.append({
                "self_evolution_policy": "curate_successful_progress_patterns",
                "priority": "medium",
                "reason": "positive progress signals can seed reusable skills or curriculum targets",
                "count": int(typed_feedback.get("monitor_inventory_gain", 0) or 0) + int(typed_feedback.get("monitor_goal_success", 0) or 0),
            })
        if report.regression_signal_count > report.progress_signal_count:
            policy_hints.append({
                "self_evolution_policy": "route_through_adaptor_before_retry",
                "priority": "high",
                "reason": "regression signals outnumber progress signals",
                "count": report.regression_signal_count - report.progress_signal_count,
            })

        return {
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
            "typed_feedback_counts": typed_feedback,
            "action_failure_categories": failure_categories,
            "action_type_counts": action_types,
            "remedy_candidates": self._dedupe_strings(remedies)[:20],
            "adaptor_recommendations": self._dedupe_strings(adaptor_recommendations)[:20],
            "policy_hints": policy_hints,
        }

    def apply_self_evolution_feedback(self, report: SelfEvolutionTraceReport, policy) -> dict:
        """Apply self-evolution feedback to a policy-like object when supported."""
        feedback = self.self_evolution_feedback(report)
        if hasattr(policy, "record_self_evolution_feedback"):
            policy.record_self_evolution_feedback(feedback)
        elif hasattr(policy, "record_exploration_feedback"):
            policy.record_exploration_feedback({
                "action_failure_categories": feedback.get("action_failure_categories", {}),
                "low_movement_log_count": feedback.get("stagnation_signal_count", 0),
            })
        return feedback

    def build_self_evolution_plan_repair_gate(
        self,
        self_evolution_reports: Optional[list[dict]] = None,
        self_evolution_report_paths: Optional[list[str]] = None,
        verifier_reports: Optional[list[dict]] = None,
        verifier_report_paths: Optional[list[str]] = None,
        counterexample_reports: Optional[list[dict]] = None,
        counterexample_report_paths: Optional[list[str]] = None,
    ) -> dict:
        """Gate future automatic plan repair with verifier and counterexample evidence."""
        report = {
            "required": True,
            "readiness": "review",
            "decision": "keep_self_evolution_feedback_advisory",
            "reason": "explicit self-evolution, verifier, and counterexample reports are required",
            "self_evolution_report_count": 0,
            "verifier_report_count": 0,
            "counterexample_report_count": 0,
            "actionable_feedback_count": 0,
            "verifier_success_count": 0,
            "verifier_failure_count": 0,
            "counterexample_count": 0,
            "unresolved_counterexample_count": 0,
            "remedy_candidate_count": 0,
            "adaptor_recommendation_count": 0,
            "policy_hints": [],
            "evidence_count": 0,
            "warning_count": 0,
            "regression_count": 0,
            "missing": [],
            "checks": [],
            "errors": [],
        }

        self_items = self._load_gate_payloads(
            self_evolution_reports or [],
            self_evolution_report_paths or [],
            report["errors"],
            "self_evolution_report",
        )
        verifier_items = self._load_gate_payloads(
            verifier_reports or [],
            verifier_report_paths or [],
            report["errors"],
            "verifier_report",
        )
        counterexample_items = self._load_gate_payloads(
            counterexample_reports or [],
            counterexample_report_paths or [],
            report["errors"],
            "counterexample_report",
        )

        report["self_evolution_report_count"] = len(self_items)
        report["verifier_report_count"] = len(verifier_items)
        report["counterexample_report_count"] = len(counterexample_items)

        policy_hints = set()
        for source, payload in self_items:
            check = self._self_evolution_gate_check(source, payload)
            report["checks"].append(check)
            metrics = check.get("metrics", {})
            report["actionable_feedback_count"] += int(metrics.get("actionable_feedback", 0) or 0)
            report["remedy_candidate_count"] += int(metrics.get("remedy_candidate_count", 0) or 0)
            report["adaptor_recommendation_count"] += int(metrics.get("adaptor_recommendation_count", 0) or 0)
            policy_hints.update(metrics.get("policy_hints", []))

        for source, payload in verifier_items:
            check = self._self_evolution_verifier_gate_check(source, payload)
            report["checks"].append(check)
            metrics = check.get("metrics", {})
            report["verifier_success_count"] += int(metrics.get("success_count", 0) or 0)
            report["verifier_failure_count"] += int(metrics.get("failure_count", 0) or 0)

        for source, payload in counterexample_items:
            check = self._self_evolution_counterexample_gate_check(source, payload)
            report["checks"].append(check)
            metrics = check.get("metrics", {})
            report["counterexample_count"] += int(metrics.get("counterexample_count", 0) or 0)
            report["unresolved_counterexample_count"] += int(metrics.get("unresolved_count", 0) or 0)

        if not self_items:
            report["missing"].append("self_evolution_report")
        if not verifier_items:
            report["missing"].append("verifier_report")
        if not counterexample_items:
            report["missing"].append("counterexample_report")

        report["policy_hints"] = sorted(policy_hints)
        report["evidence_count"] = sum(1 for check in report["checks"] if check.get("status") == "pass")
        report["warning_count"] = sum(1 for check in report["checks"] if check.get("status") == "warn")
        report["regression_count"] = sum(1 for check in report["checks"] if check.get("status") == "fail")

        if report["errors"]:
            report["readiness"] = "error"
            report["decision"] = "do_not_mutate_plan"
            report["reason"] = "gate inputs could not be loaded"
        elif report["regression_count"] or report["verifier_failure_count"] or report["unresolved_counterexample_count"]:
            report["readiness"] = "rejected"
            report["decision"] = "do_not_mutate_plan"
            report["reason"] = "verifier failures or unresolved counterexamples block automatic repair"
        elif report["missing"] or report["warning_count"] or not report["actionable_feedback_count"]:
            report["readiness"] = "review"
            report["decision"] = "keep_self_evolution_feedback_advisory"
            report["reason"] = "automatic repair requires complete, actionable, non-regressing evidence"
        else:
            report["readiness"] = "approved"
            report["decision"] = "allow_verified_plan_suffix_repair"
            report["reason"] = "self-evolution feedback is actionable and verifier/counterexample gates passed"
        return report

    def _load_gate_payloads(self, payloads: list[dict], paths: list[str], errors: list[str], label: str) -> list[tuple[str, dict]]:
        items = []
        for index, payload in enumerate(payloads, start=1):
            if isinstance(payload, dict):
                items.append((f"{label}:{index}", payload))
            else:
                errors.append(f"{label}:{index}: payload must be a dict")
        for path in paths:
            if not path:
                continue
            try:
                with open(path, "r", encoding="utf-8-sig") as f:
                    payload = json.load(f)
                if not isinstance(payload, dict):
                    raise ValueError("report JSON must be an object")
                items.append((path, payload))
            except Exception as e:
                errors.append(f"{path}: {e}")
        return items

    def _self_evolution_gate_check(self, source: str, payload: dict) -> dict:
        feedback = payload.get("self_evolution_feedback", payload) if isinstance(payload, dict) else {}
        if not isinstance(feedback, dict):
            feedback = {}
        report_errors = payload.get("errors", []) if isinstance(payload.get("errors", []), list) else []
        hints = feedback.get("policy_hints", []) if isinstance(feedback.get("policy_hints", []), list) else []
        hint_names = self._dedupe_strings([
            str(hint.get("self_evolution_policy") or hint.get("policy") or "")
            for hint in hints
            if isinstance(hint, dict)
        ])
        actionable = [
            name for name in hint_names
            if name in {
                "repair_stagnant_plan_suffix",
                "route_through_adaptor_before_retry",
                "induce_failure_remedies",
            }
        ]
        remedy_candidates = feedback.get("remedy_candidates", [])
        adaptor_recommendations = feedback.get("adaptor_recommendations", [])
        ready_log_count = self._gate_int(payload.get("ready_log_count", feedback.get("ready_log_count", 0)))
        failed_action_count = self._gate_int(feedback.get("failed_action_count", payload.get("failed_action_count", 0)))
        stagnation_count = self._gate_int(feedback.get("stagnation_signal_count", payload.get("stagnation_signal_count", 0)))
        metrics = {
            "ready_log_count": ready_log_count,
            "failed_action_count": failed_action_count,
            "stagnation_signal_count": stagnation_count,
            "policy_hints": hint_names,
            "actionable_feedback": 1 if actionable else 0,
            "remedy_candidate_count": len(remedy_candidates) if isinstance(remedy_candidates, list) else 0,
            "adaptor_recommendation_count": len(adaptor_recommendations) if isinstance(adaptor_recommendations, list) else 0,
        }
        if report_errors:
            return self._gate_check(source, "self_evolution_report", "fail", "self-evolution report contains errors", metrics)
        if actionable and (ready_log_count or failed_action_count or stagnation_count):
            return self._gate_check(source, "self_evolution_report", "pass", "actionable self-evolution feedback is present", metrics)
        if actionable:
            return self._gate_check(source, "self_evolution_report", "warn", "policy hints exist but trace readiness is weak", metrics)
        return self._gate_check(source, "self_evolution_report", "warn", "no actionable automatic-repair hint was found", metrics)

    def _self_evolution_verifier_gate_check(self, source: str, payload: dict) -> dict:
        report_errors = payload.get("errors", []) if isinstance(payload.get("errors", []), list) else []
        cases = payload.get("cases", []) if isinstance(payload.get("cases", []), list) else []
        success_count = 0
        failure_count = 0
        unknown_count = 0
        records = cases or [payload]
        for record in records:
            if not isinstance(record, dict):
                unknown_count += 1
                continue
            status = self._verification_gate_status(record)
            if status == "approved":
                success_count += 1
            elif status == "rejected":
                failure_count += 1
            else:
                unknown_count += 1
        metrics = {
            "case_count": len(cases),
            "success_count": success_count,
            "failure_count": failure_count,
            "unknown_count": unknown_count,
        }
        if report_errors:
            return self._gate_check(source, "verifier_report", "fail", "verifier report contains errors", metrics)
        if failure_count:
            return self._gate_check(source, "verifier_report", "fail", "verifier reported failed or rejected cases", metrics)
        if success_count:
            status = "warn" if unknown_count else "pass"
            detail = "verifier passed with unknown cases" if unknown_count else "verifier evidence passed"
            return self._gate_check(source, "verifier_report", status, detail, metrics)
        return self._gate_check(source, "verifier_report", "warn", "no verifier success evidence was found", metrics)

    def _self_evolution_counterexample_gate_check(self, source: str, payload: dict) -> dict:
        report_errors = payload.get("errors", []) if isinstance(payload.get("errors", []), list) else []
        examples = payload.get("counterexamples", None)
        if examples is None:
            examples = payload.get("cases", [])
        if not isinstance(examples, list):
            examples = []
        explicit_count = self._gate_int(payload.get("counterexample_count", len(examples)))
        unresolved = self._gate_int(payload.get("unresolved_counterexample_count", 0))
        resolved = self._gate_int(payload.get("resolved_counterexample_count", 0))
        unknown = 0
        for item in examples:
            if not isinstance(item, dict):
                unknown += 1
                continue
            state = self._counterexample_state(item)
            if state == "unresolved":
                unresolved += 1
            elif state == "resolved":
                resolved += 1
            else:
                unknown += 1
        counterexample_count = max(explicit_count, unresolved + resolved + unknown, len(examples))
        metrics = {
            "counterexample_count": counterexample_count,
            "resolved_count": resolved,
            "unresolved_count": unresolved,
            "unknown_count": unknown,
        }
        if report_errors:
            return self._gate_check(source, "counterexample_report", "fail", "counterexample report contains errors", metrics)
        if unresolved:
            return self._gate_check(source, "counterexample_report", "fail", "unresolved counterexamples remain", metrics)
        if unknown:
            return self._gate_check(source, "counterexample_report", "warn", "counterexample status is incomplete", metrics)
        return self._gate_check(source, "counterexample_report", "pass", "no unresolved counterexamples remain", metrics)

    def _verification_gate_status(self, record: dict) -> str:
        for key in ("screenshot_vlm_readiness", "api_visual_readiness", "deterministic_readiness", "readiness"):
            value = str(record.get(key) or "").lower()
            if value in {"approved", "achieved", "passed", "pass", "success"}:
                return "approved"
            if value in {"rejected", "failed", "fail", "error"}:
                return "rejected"
        status = str(record.get("status") or "").lower()
        if status in {"achieved", "approved", "passed", "pass", "success"}:
            return "approved"
        if status in {"failed", "rejected", "fail", "error"}:
            return "rejected"
        if record.get("achieved") is True or record.get("ok") is True:
            return "approved"
        if record.get("achieved") is False or record.get("ok") is False:
            return "rejected"
        return "unknown"

    def _counterexample_state(self, item: dict) -> str:
        if item.get("resolved") is True or item.get("fixed") is True:
            return "resolved"
        if item.get("resolved") is False or item.get("fixed") is False:
            return "unresolved"
        status = str(item.get("status") or item.get("readiness") or item.get("state") or "").lower()
        if status in {"resolved", "closed", "fixed", "passed", "approved"}:
            return "resolved"
        if status in {"open", "unresolved", "failed", "rejected", "failing", "error"}:
            return "unresolved"
        return "unknown"

    def _gate_check(self, source: str, kind: str, status: str, detail: str, metrics: dict) -> dict:
        return {
            "source": source,
            "kind": kind,
            "status": status,
            "detail": detail,
            "metrics": metrics,
        }

    def _gate_int(self, value) -> int:
        try:
            return int(float(value or 0))
        except (TypeError, ValueError):
            return 0

    def _gate_float_or_none(self, value) -> Optional[float]:
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def run_discovery_application_report_from_logs(self, session_log_paths: list[str]) -> DiscoveryApplicationTraceReport:
        """Summarize SciCrafter-style discovery-to-application evidence in session logs."""
        report = DiscoveryApplicationTraceReport()
        for path in session_log_paths:
            try:
                events = self._load_session_events(path)
                report.cases.append(self._discovery_application_trace_case(path, events))
            except Exception as e:
                report.errors.append(f"{path}: {e}")
        return report

    def discovery_application_feedback(self, report: DiscoveryApplicationTraceReport) -> dict:
        """Aggregate discovery traces into task/skill promotion feedback."""
        phase_counts = {}
        causal_rules = set()
        knowledge_gaps = set()
        recommendations = []
        for case in report.cases:
            for phase, count in case.phase_counts.items():
                phase_counts[phase] = phase_counts.get(phase, 0) + int(count or 0)
            causal_rules.update(case.causal_rule_candidates)
            knowledge_gaps.update(case.knowledge_gap_candidates)
            recommendations.extend(case.recommendations)
        unique_recommendations = self._dedupe_strings(recommendations)
        return {
            "log_count": report.log_count,
            "ready_log_count": report.ready_log_count,
            "phase_counts": phase_counts,
            "complete_loop_count": report.complete_loop_count,
            "hypothesis_count": report.hypothesis_count,
            "experiment_count": report.experiment_count,
            "consolidation_count": report.consolidation_count,
            "application_count": report.application_count,
            "successful_application_count": report.successful_application_count,
            "failed_application_count": report.failed_application_count,
            "experiment_action_count": report.experiment_action_count,
            "failed_experiment_action_count": report.failed_experiment_action_count,
            "causal_memory_write_count": report.causal_memory_write_count,
            "causal_rule_candidates": sorted(causal_rules)[:20],
            "knowledge_gap_candidates": sorted(knowledge_gaps)[:20],
            "recommendations": unique_recommendations[:20],
            "ready_for_skill_gate": bool(
                report.complete_loop_count > 0
                and report.successful_application_count > 0
                and report.causal_memory_write_count > 0
            ),
        }

    def run_action_abstraction_report_from_logs(self, session_log_paths: list[str]) -> ActionAbstractionTraceReport:
        """Summarize canonical actions, backend mappings, and cross-level control needs."""
        report = ActionAbstractionTraceReport()
        mapper = ActionMapper()
        for path in session_log_paths:
            try:
                events = self._load_session_events(path)
                report.cases.append(self._action_abstraction_trace_case(path, events, mapper))
            except Exception as e:
                report.errors.append(f"{path}: {e}")
        return report

    def action_abstraction_feedback(self, report: ActionAbstractionTraceReport) -> dict:
        """Aggregate action traces into backend/granularity policy hints."""
        canonical_counts = {}
        backend_command_counts = {}
        lower_level_reasons = {}
        lower_level_action_types = {}
        unknown_actions = {}
        canonical_known = ActionMapper.CANONICAL_ACTIONS
        for case in report.cases:
            self._merge_counts(canonical_counts, case.canonical_action_types)
            self._merge_counts(backend_command_counts, case.result_backend_command_counts)
            self._merge_counts(lower_level_reasons, case.lower_level_reasons)
            self._merge_counts(lower_level_action_types, case.lower_level_action_types)
            for action_type, count in case.canonical_action_types.items():
                if action_type not in canonical_known:
                    unknown_actions[action_type] = unknown_actions.get(action_type, 0) + int(count or 0)

        policy_hints = []
        for action_type, count in sorted(canonical_counts.items()):
            low_level_count = int(lower_level_action_types.get(action_type, 0) or 0)
            unknown_count = int(unknown_actions.get(action_type, 0) or 0)
            if unknown_count:
                preference = "define_canonical_mapping"
                reason = "unknown_canonical_action"
            elif low_level_count:
                preference = "consider_low_level_visual_control"
                reason = "visual_or_precision_sensitive"
            else:
                preference = "mineflayer_api_ok"
                reason = "no_low_level_signal"
            policy_hints.append({
                "action_type": action_type,
                "count": int(count or 0),
                "preferred_control": preference,
                "reason": reason,
                "low_level_candidate_count": low_level_count,
                "unknown_count": unknown_count,
            })

        return {
            "action_count": report.action_count,
            "failed_action_count": report.failed_action_count,
            "unknown_canonical_count": report.unknown_canonical_count,
            "failed_mapping_count": report.failed_mapping_count,
            "low_level_candidate_count": report.low_level_candidate_count,
            "canonical_action_types": canonical_counts,
            "backend_command_counts": backend_command_counts,
            "lower_level_reasons": lower_level_reasons,
            "lower_level_action_types": lower_level_action_types,
            "unknown_action_types": unknown_actions,
            "policy_hints": policy_hints,
        }

    def apply_action_abstraction_feedback(self, report: ActionAbstractionTraceReport, action_policy) -> dict:
        """Apply action-abstraction feedback to a policy-like object when supported."""
        feedback = self.action_abstraction_feedback(report)
        if hasattr(action_policy, "record_action_abstraction_feedback"):
            action_policy.record_action_abstraction_feedback(feedback)
        return feedback

    def run_skill_memory_quality_report_from_logs(self, session_log_paths: list[str]) -> SkillMemoryQualityReport:
        """Audit typed skill-memory hints against later trace outcomes."""
        report = SkillMemoryQualityReport()
        for path in session_log_paths:
            try:
                events = self._load_session_events(path)
                report.cases.append(self._skill_memory_quality_trace_case(path, events))
            except Exception as e:
                report.errors.append(f"{path}: {e}")
        return report

    def skill_memory_quality_feedback(self, report: SkillMemoryQualityReport) -> dict:
        """Aggregate skill-memory quality traces into retrieval and promotion hints."""
        label_counts = report.quality_label_counts
        policy_hints = []
        if label_counts.get("no_skill_memory_hints", 0):
            policy_hints.append({
                "skill_memory_policy": "instrument_skill_memory_hints",
                "priority": "medium",
                "reason": "session logs have no planner-facing skill-memory hint events",
                "count": label_counts["no_skill_memory_hints"],
            })
        if label_counts.get("missing_goal_outcome_after_hint", 0):
            policy_hints.append({
                "skill_memory_policy": "log_goal_outcomes_after_skill_memory_hints",
                "priority": "high",
                "reason": "typed skill-memory hints lack later goal outcome evidence",
                "count": label_counts["missing_goal_outcome_after_hint"],
            })
        if label_counts.get("reuse_conflicted_with_failures", 0):
            policy_hints.append({
                "skill_memory_policy": "demote_conflicting_reuse_hints",
                "priority": "high",
                "reason": "REUSE hints were followed by goal failure or repeated failed actions",
                "count": label_counts["reuse_conflicted_with_failures"],
            })
        if label_counts.get("avoid_unheeded_post_hint_failures", 0):
            policy_hints.append({
                "skill_memory_policy": "tighten_avoid_hint_prompting",
                "priority": "medium",
                "reason": "AVOID hints were followed by failed actions, suggesting the warning was not operationalized",
                "count": label_counts["avoid_unheeded_post_hint_failures"],
            })
        if label_counts.get("review_only_present_keep_gated", 0):
            policy_hints.append({
                "skill_memory_policy": "keep_review_only_skill_memory_gated",
                "priority": "medium",
                "reason": "REVIEW_ONLY hints appeared in planner context and should remain audit-only until transfer evidence improves",
                "count": label_counts["review_only_present_keep_gated"],
            })
        if label_counts.get("reuse_supported_by_goal_success", 0):
            policy_hints.append({
                "skill_memory_policy": "candidate_promote_reuse_hints",
                "priority": "low",
                "reason": "REUSE hints were followed by successful goal outcomes; confirm with ablation before default promotion",
                "count": label_counts["reuse_supported_by_goal_success"],
            })

        return {
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
            "quality_label_counts": label_counts,
            "hint_quality_items": report.hint_quality_items,
            "policy_hints": policy_hints,
        }

    def apply_skill_memory_quality_feedback(self, report: SkillMemoryQualityReport, skill_library) -> dict:
        """Apply skill-memory quality feedback to a SkillLibrary-like object."""
        feedback = self.skill_memory_quality_feedback(report)
        if hasattr(skill_library, "record_skill_memory_quality_feedback"):
            skill_library.record_skill_memory_quality_feedback(feedback)
        return feedback

    def build_skill_memory_quality_gate(
        self,
        memory_reports: Optional[list[dict]] = None,
        memory_report_paths: Optional[list[str]] = None,
        quality_feedbacks: Optional[list[dict]] = None,
        quality_feedback_paths: Optional[list[str]] = None,
        target: str = "skill_memory_reuse_promotion",
        min_supported_reuse: int = 2,
        max_conflicting_reuse: int = 0,
    ) -> dict:
        """Gate skill-memory REUSE promotion with localized quality evidence."""
        report = {
            "required": True,
            "target": target,
            "readiness": "review",
            "decision": "keep_skill_memory_review_only",
            "reason": "localized skill-memory quality evidence is required",
            "memory_report_count": 0,
            "quality_feedback_count": 0,
            "candidate_count": 0,
            "approved_count": 0,
            "review_count": 0,
            "rejected_count": 0,
            "thresholds": {
                "min_supported_reuse": int(min_supported_reuse),
                "max_conflicting_reuse": int(max_conflicting_reuse),
            },
            "missing": [],
            "policy_hints": [],
            "candidates": [],
            "checks": [],
            "errors": [],
        }
        memory_items = self._load_gate_payloads(
            memory_reports or [],
            memory_report_paths or [],
            report["errors"],
            "skill_memory_report",
        )
        quality_items = self._load_gate_payloads(
            quality_feedbacks or [],
            quality_feedback_paths or [],
            report["errors"],
            "skill_memory_quality_feedback",
        )
        report["memory_report_count"] = len(memory_items)
        report["quality_feedback_count"] = len(quality_items)
        if not memory_items:
            report["missing"].append("skill_memory_report")
        if not quality_items:
            report["missing"].append("skill_memory_quality_feedback")

        memory_index = self._skill_memory_gate_memory_index(memory_items)
        quality_index = self._skill_memory_gate_quality_index(quality_items)
        for key, quality in sorted(quality_index.items(), key=lambda item: item[0]):
            hint_type, skill, family = key
            if hint_type != "REUSE":
                continue
            candidate = self._skill_memory_quality_gate_candidate(
                skill,
                family,
                quality,
                memory_index.get((skill, family)) or memory_index.get((skill, "")),
                report["thresholds"],
            )
            report["candidates"].append(candidate)
            report["checks"].append({
                "source": ",".join(candidate["sources"]) or "skill_memory_quality_feedback",
                "kind": "skill_memory_quality_gate",
                "status": candidate["status"],
                "detail": candidate["reason"],
                "metrics": {
                    "skill": skill,
                    "task_family": family,
                    "supported_reuse_count": candidate["supported_reuse_count"],
                    "conflicting_reuse_count": candidate["conflicting_reuse_count"],
                    "family_memory_count": candidate["family_memory_count"],
                },
            })
        report["candidate_count"] = len(report["candidates"])
        report["approved_count"] = sum(1 for item in report["candidates"] if item["readiness"] == "approved")
        report["review_count"] = sum(1 for item in report["candidates"] if item["readiness"] == "review")
        report["rejected_count"] = sum(1 for item in report["candidates"] if item["readiness"] == "rejected")

        policy_hints = set()
        for candidate in report["candidates"]:
            if candidate["readiness"] == "approved":
                policy_hints.add("promote_supported_reuse_skill_memory")
            elif candidate["readiness"] == "rejected":
                policy_hints.add("block_conflicting_reuse_skill_memory")
            else:
                policy_hints.add("collect_more_skill_memory_quality_evidence")
        report["policy_hints"] = sorted(policy_hints)

        if report["errors"]:
            report["readiness"] = "error"
            report["decision"] = "do_not_promote_skill_memory"
            report["reason"] = "gate inputs could not be loaded"
        elif report["rejected_count"]:
            report["readiness"] = "rejected"
            report["decision"] = "do_not_promote_skill_memory"
            report["reason"] = "localized REUSE evidence contains conflicts or blocked skills"
        elif report["missing"] or not report["candidate_count"] or report["review_count"]:
            report["readiness"] = "review"
            report["decision"] = "keep_skill_memory_review_only"
            report["reason"] = "localized REUSE evidence is incomplete or below promotion confidence"
        else:
            report["readiness"] = "approved"
            report["decision"] = "allow_supported_reuse_skill_memory_promotion"
            report["reason"] = "localized REUSE hints are repeatedly supported and matched to skill memory"
        return report

    def _skill_memory_gate_memory_index(self, items: list[tuple[str, dict]]) -> dict[tuple[str, str], dict]:
        index = {}
        for source, payload in items:
            memory_report = payload.get("skill_memory_report", payload) if isinstance(payload, dict) else {}
            if not isinstance(memory_report, dict):
                continue
            default_family = str(memory_report.get("task_family") or "").strip().lower()
            skills = memory_report.get("skills", [])
            if not isinstance(skills, list):
                continue
            for skill in skills:
                if not isinstance(skill, dict):
                    continue
                name = str(skill.get("name") or "").strip()
                if not name:
                    continue
                family_counts = skill.get("task_family_counts", {}) if isinstance(skill.get("task_family_counts", {}), dict) else {}
                families = sorted(
                    str(family or "").strip().lower()
                    for family in family_counts
                    if str(family or "").strip()
                )
                if not families and default_family:
                    families = [default_family]
                if not families:
                    families = [""]
                for family in families:
                    key = (name, family)
                    entry = index.setdefault(key, {
                        "skill": name,
                        "task_family": family,
                        "memory_count": 0,
                        "family_memory_count": 0,
                        "success_memory_count": 0,
                        "failure_memory_count": 0,
                        "approved_transfer_memory_count": 0,
                        "review_transfer_memory_count": 0,
                        "gate_readiness": "",
                        "contract_readiness": "",
                        "issues": set(),
                        "recommendations": set(),
                        "sources": set(),
                    })
                    family_count = self._gate_int(family_counts.get(family, skill.get("memory_count", 0)))
                    entry["memory_count"] += self._gate_int(skill.get("memory_count", 0))
                    entry["family_memory_count"] += family_count
                    entry["success_memory_count"] += self._gate_int(skill.get("success_memory_count", 0))
                    entry["failure_memory_count"] += self._gate_int(skill.get("failure_memory_count", 0))
                    entry["approved_transfer_memory_count"] += self._gate_int(skill.get("approved_transfer_memory_count", 0))
                    entry["review_transfer_memory_count"] += self._gate_int(skill.get("review_transfer_memory_count", 0))
                    entry["gate_readiness"] = entry["gate_readiness"] or str(skill.get("gate_readiness") or "")
                    entry["contract_readiness"] = entry["contract_readiness"] or str(skill.get("contract_readiness") or "")
                    entry["issues"].update(str(issue) for issue in skill.get("issues", []) if issue)
                    entry["recommendations"].update(str(item) for item in skill.get("recommendations", []) if item)
                    entry["sources"].add(source)
        for entry in index.values():
            entry["issues"] = sorted(entry["issues"])
            entry["recommendations"] = sorted(entry["recommendations"])
            entry["sources"] = sorted(entry["sources"])
        return index

    def _skill_memory_gate_quality_index(self, items: list[tuple[str, dict]]) -> dict[tuple[str, str, str], dict]:
        index = {}
        for source, payload in items:
            feedback = payload.get("skill_memory_quality_feedback", payload) if isinstance(payload, dict) else {}
            if not isinstance(feedback, dict):
                continue
            quality_items = feedback.get("hint_quality_items", [])
            if not isinstance(quality_items, list):
                continue
            for item in quality_items:
                if not isinstance(item, dict):
                    continue
                hint_type = str(item.get("hint_type") or "UNKNOWN").strip().upper() or "UNKNOWN"
                skill = str(item.get("skill") or "unknown").strip() or "unknown"
                family = str(item.get("task_family") or "").strip().lower()
                key = (hint_type, skill, family)
                entry = index.setdefault(key, {
                    "hint_type": hint_type,
                    "skill": skill,
                    "task_family": family,
                    "count": 0,
                    "labels": {},
                    "examples": [],
                    "sources": set(),
                })
                entry["count"] += self._gate_int(item.get("count", 0))
                labels = item.get("labels", {}) if isinstance(item.get("labels", {}), dict) else {}
                for label, count in labels.items():
                    entry["labels"][str(label)] = entry["labels"].get(str(label), 0) + self._gate_int(count)
                examples = item.get("examples", []) if isinstance(item.get("examples", []), list) else []
                for example in examples:
                    text = str(example or "").strip()
                    if text and text not in entry["examples"]:
                        entry["examples"].append(text)
                entry["sources"].add(source)
        for entry in index.values():
            entry["sources"] = sorted(entry["sources"])
        return index

    def _skill_memory_quality_gate_candidate(
        self,
        skill: str,
        family: str,
        quality: dict,
        memory: Optional[dict],
        thresholds: dict,
    ) -> dict:
        labels = quality.get("labels", {}) if isinstance(quality.get("labels", {}), dict) else {}
        supported = self._gate_int(labels.get("reuse_supported_by_goal_success", 0))
        conflicting = self._gate_int(labels.get("reuse_conflicted_with_failures", 0))
        memory = memory if isinstance(memory, dict) else {}
        family_memory_count = self._gate_int(memory.get("family_memory_count", 0))
        gate_readiness = str(memory.get("gate_readiness") or "").lower()
        contract_readiness = str(memory.get("contract_readiness") or "").lower()
        issues = list(memory.get("issues", [])) if isinstance(memory.get("issues", []), list) else []
        min_supported = int(thresholds.get("min_supported_reuse", 2))
        max_conflicting = int(thresholds.get("max_conflicting_reuse", 0))
        readiness = "review"
        decision = "keep_skill_memory_review_only"
        status = "warn"
        reason = "localized REUSE support is below promotion threshold"
        if not memory:
            reason = "quality item has no matching skill-memory report entry"
        elif family_memory_count <= 0:
            reason = "matching skill has no memory in this task family"
        elif gate_readiness in {"rejected", "error"} or contract_readiness == "blocked":
            readiness = "rejected"
            decision = "do_not_promote_skill_memory"
            status = "fail"
            reason = "matching skill is blocked by governance or contract readiness"
        elif conflicting > max_conflicting:
            readiness = "rejected"
            decision = "do_not_promote_skill_memory"
            status = "fail"
            reason = "localized REUSE hint conflicts with later failures"
        elif supported >= min_supported:
            if gate_readiness == "review" or contract_readiness == "review" or "transfer_review_or_rejected" in issues:
                reason = "localized support is present but transfer or governance remains review-gated"
            else:
                readiness = "approved"
                decision = "allow_supported_reuse_skill_memory_promotion"
                status = "pass"
                reason = "localized REUSE hint is repeatedly supported by successful outcomes"
        return {
            "skill": skill,
            "task_family": family,
            "hint_type": "REUSE",
            "readiness": readiness,
            "decision": decision,
            "status": status,
            "reason": reason,
            "supported_reuse_count": supported,
            "conflicting_reuse_count": conflicting,
            "hint_count": self._gate_int(quality.get("count", 0)),
            "family_memory_count": family_memory_count,
            "success_memory_count": self._gate_int(memory.get("success_memory_count", 0)),
            "failure_memory_count": self._gate_int(memory.get("failure_memory_count", 0)),
            "approved_transfer_memory_count": self._gate_int(memory.get("approved_transfer_memory_count", 0)),
            "review_transfer_memory_count": self._gate_int(memory.get("review_transfer_memory_count", 0)),
            "gate_readiness": gate_readiness,
            "contract_readiness": contract_readiness,
            "issues": issues,
            "examples": list(quality.get("examples", []))[:3],
            "sources": sorted(set(quality.get("sources", [])) | set(memory.get("sources", []))),
        }

    def run_memory_policy_report_from_logs(self, session_log_paths: list[str]) -> MemoryPolicyTraceReport:
        """Summarize memory write/read/manage evidence and policy gaps in session logs."""
        report = MemoryPolicyTraceReport()
        for path in session_log_paths:
            try:
                events = self._load_session_events(path)
                report.cases.append(self._memory_policy_trace_case(path, events))
            except Exception as e:
                report.errors.append(f"{path}: {e}")
        return report

    def memory_policy_feedback(self, report: MemoryPolicyTraceReport) -> dict:
        """Aggregate memory traces into write/read/manage policy hints."""
        write_operations = {}
        read_queries = set()
        for case in report.cases:
            self._merge_counts(write_operations, case.write_operations)
            read_queries.update(case.read_queries)

        policy_hints = []
        if report.missing_read_trace_count:
            policy_hints.append({
                "memory_policy": "instrument_memory_retrieval",
                "priority": "high",
                "reason": "plans lack explicit memory-read trace evidence",
                "count": report.missing_read_trace_count,
            })
        if report.missed_semantic_write_count:
            policy_hints.append({
                "memory_policy": "promote_verified_outcomes",
                "priority": "high",
                "reason": "verified goal outcomes lack durable semantic write evidence",
                "count": report.missed_semantic_write_count,
            })
        if report.failure_learning_candidate_count:
            policy_hints.append({
                "memory_policy": "record_failure_corrections",
                "priority": "medium",
                "reason": "failure or correction traces should become reusable experience",
                "count": report.failure_learning_candidate_count,
            })
        if report.noisy_write_candidate_count:
            policy_hints.append({
                "memory_policy": "tighten_memory_write_gate",
                "priority": "medium",
                "reason": "explicit writes appear low-confidence, too-short, or raw-observation-like",
                "count": report.noisy_write_candidate_count,
            })
        if report.consolidation_signal_count:
            policy_hints.append({
                "memory_policy": "queue_consolidation_review",
                "priority": "low",
                "reason": "trace contains repeated or completed behaviors worth offline consolidation review",
                "count": report.consolidation_signal_count,
            })
        if report.read_filtered_entry_count:
            policy_hints.append({
                "memory_policy": "review_filtered_memory_reads",
                "priority": "medium",
                "reason": "retrieval filtered stale, superseded, invalidated, or condition-mismatched memory entries",
                "count": report.read_filtered_entry_count,
            })

        return {
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
            "write_operations": write_operations,
            "read_queries": sorted(read_queries),
            "policy_hints": policy_hints,
        }

    def apply_memory_policy_feedback(self, report: MemoryPolicyTraceReport, memory_policy) -> dict:
        """Apply memory-policy feedback to a policy-like object when supported."""
        feedback = self.memory_policy_feedback(report)
        if hasattr(memory_policy, "record_memory_policy_feedback"):
            memory_policy.record_memory_policy_feedback(feedback)
        return feedback

    def run_bounded_context_report_from_logs(
        self,
        session_log_paths: list[str],
        max_read_chars: int = 1200,
        max_cycle_chars: int = 2400,
    ) -> BoundedPlanningContextReport:
        """Audit AgenticSTS-style bounded, typed retrieval contracts before planner calls."""
        report = BoundedPlanningContextReport(
            max_read_chars=max(1, int(max_read_chars or 1200)),
            max_cycle_chars=max(1, int(max_cycle_chars or 2400)),
        )
        for path in session_log_paths:
            try:
                events = self._load_session_events(path)
                report.cases.append(self._bounded_context_trace_case(
                    path,
                    events,
                    report.max_read_chars,
                    report.max_cycle_chars,
                ))
            except Exception as e:
                report.errors.append(f"{path}: {e}")
        return report

    def bounded_context_feedback(self, report: BoundedPlanningContextReport) -> dict:
        """Aggregate bounded-context traces into planner/memory contract hints."""
        policy_hints = []
        if report.missing_read_cycle_count:
            policy_hints.append({
                "bounded_context_policy": "instrument_planning_context_reads",
                "priority": "high",
                "reason": "planner cycles lack memory_read trace evidence before plan events",
                "count": report.missing_read_cycle_count,
            })
        if report.oversized_read_cycle_count or report.oversized_cycle_count:
            policy_hints.append({
                "bounded_context_policy": "tighten_planner_context_budget",
                "priority": "high",
                "reason": "planner memory context exceeds per-read or per-cycle character budget",
                "count": report.oversized_read_cycle_count + report.oversized_cycle_count,
            })
        if report.raw_context_cycle_count:
            policy_hints.append({
                "bounded_context_policy": "replace_raw_transcript_with_typed_retrieval",
                "priority": "high",
                "reason": "planning context shows raw/transcript-like memory sources or oversized context windows",
                "count": report.raw_context_cycle_count,
            })
        if report.low_diversity_cycle_count:
            policy_hints.append({
                "bounded_context_policy": "increase_typed_retrieval_diversity",
                "priority": "medium",
                "reason": "planning cycles rely on too few typed context layers for ablation-friendly decisions",
                "count": report.low_diversity_cycle_count,
            })
        return {
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
            "read_layers": dict(sorted(report.read_layers.items())),
            "read_types": dict(sorted(report.read_types.items())),
            "policy_hints": policy_hints,
        }

    def _bounded_context_trace_case(
        self,
        source_log: str,
        events: list[dict],
        max_read_chars: int,
        max_cycle_chars: int,
    ) -> BoundedPlanningContextCase:
        current_goal = ""
        pending_reads = []
        cycles = []
        for event in events:
            event_type = event.get("type")
            data = event.get("data", {}) if isinstance(event.get("data", {}), dict) else {}
            if event_type == "goal_start":
                current_goal = str(data.get("goal") or current_goal or "")
            elif event_type == "goal_end":
                current_goal = str(data.get("goal") or current_goal or "")
            elif event_type == "memory_read":
                pending_reads.append(event)
            elif event_type == "plan":
                cycles.append(self._bounded_context_cycle(
                    len(cycles) + 1,
                    current_goal,
                    data,
                    pending_reads,
                    max_read_chars,
                    max_cycle_chars,
                ))
                pending_reads = []

        read_layers = {}
        read_types = {}
        read_sources = {}
        issues = {}
        for cycle in cycles:
            self._merge_counts(read_layers, cycle.read_layers)
            self._merge_counts(read_types, cycle.read_types)
            self._merge_counts(read_sources, cycle.read_sources)
            for issue in cycle.issues:
                issues[issue] = issues.get(issue, 0) + 1

        case = BoundedPlanningContextCase(
            source_log=source_log,
            event_count=len(events),
            plan_count=sum(1 for event in events if event.get("type") == "plan"),
            planning_cycle_count=len(cycles),
            bounded_cycle_count=sum(1 for cycle in cycles if cycle.bounded_ok),
            unbounded_cycle_count=sum(1 for cycle in cycles if not cycle.bounded_ok),
            missing_read_cycle_count=sum(1 for cycle in cycles if "missing_memory_read_trace" in cycle.issues),
            oversized_read_cycle_count=sum(1 for cycle in cycles if "oversized_memory_read" in cycle.issues),
            oversized_cycle_count=sum(1 for cycle in cycles if "oversized_planning_context" in cycle.issues),
            raw_context_cycle_count=sum(1 for cycle in cycles if "raw_context_risk" in cycle.issues),
            low_diversity_cycle_count=sum(1 for cycle in cycles if "low_retrieval_diversity" in cycle.issues),
            max_cycle_result_chars=max((cycle.total_result_chars for cycle in cycles), default=0),
            total_result_chars=sum(cycle.total_result_chars for cycle in cycles),
            read_layers=dict(sorted(read_layers.items())),
            read_types=dict(sorted(read_types.items())),
            read_sources=dict(sorted(read_sources.items())),
            issues=sorted(issues),
            cycles=cycles,
            ready_for_bounded_context_review=bool(cycles),
        )
        return case

    def _bounded_context_cycle(
        self,
        cycle_index: int,
        goal: str,
        plan: dict,
        read_events: list[dict],
        max_read_chars: int,
        max_cycle_chars: int,
    ) -> BoundedPlanningContextCycle:
        read_layers = {}
        read_types = {}
        read_sources = {}
        total_chars = 0
        max_chars = 0
        has_relevant_memory = False
        has_task_memory = False
        has_context_window = False
        raw_context_risk = False
        for event in read_events:
            data = event.get("data", {}) if isinstance(event.get("data", {}), dict) else {}
            layer = str(data.get("layer") or "unknown")
            memory_type = str(data.get("memory_type") or "unknown")
            source = str(data.get("source") or "unknown")
            result_chars = self._safe_int(data.get("result_chars"), default=0)
            total_chars += result_chars
            max_chars = max(max_chars, result_chars)
            self._increment(read_layers, layer)
            self._increment(read_types, memory_type)
            self._increment(read_sources, source)
            lower_blob = " ".join([layer, memory_type, source, str(data.get("query") or "")]).lower()
            if memory_type == "relevant_memory":
                has_relevant_memory = True
            if memory_type == "task_memory" or layer == "task":
                has_task_memory = True
            if memory_type == "context_window":
                has_context_window = True
            if any(token in lower_blob for token in ("raw", "transcript", "full_history", "message_history")):
                raw_context_risk = True
            if memory_type == "context_window" and result_chars > max_read_chars:
                raw_context_risk = True

        actions = plan.get("actions", []) if isinstance(plan.get("actions", []), list) else []
        typed_pairs = {
            f"{event.get('data', {}).get('layer', 'unknown')}:{event.get('data', {}).get('memory_type', 'unknown')}"
            for event in read_events
            if isinstance(event.get("data", {}), dict)
        }
        issues = []
        if not read_events:
            issues.append("missing_memory_read_trace")
        if max_chars > max_read_chars:
            issues.append("oversized_memory_read")
        if total_chars > max_cycle_chars:
            issues.append("oversized_planning_context")
        if raw_context_risk:
            issues.append("raw_context_risk")
        if read_events and len(typed_pairs) < 2:
            issues.append("low_retrieval_diversity")

        hard_issues = {
            "missing_memory_read_trace",
            "oversized_memory_read",
            "oversized_planning_context",
            "raw_context_risk",
        }
        return BoundedPlanningContextCycle(
            cycle_index=cycle_index,
            goal=goal,
            plan_status=str(plan.get("status") or ""),
            action_count=len(actions),
            memory_read_count=len(read_events),
            typed_layer_count=len(typed_pairs),
            total_result_chars=total_chars,
            max_result_chars=max_chars,
            has_relevant_memory=has_relevant_memory,
            has_task_memory=has_task_memory,
            has_context_window=has_context_window,
            read_layers=dict(sorted(read_layers.items())),
            read_types=dict(sorted(read_types.items())),
            read_sources=dict(sorted(read_sources.items())),
            issues=sorted(set(issues)),
            bounded_ok=not any(issue in hard_issues for issue in issues),
        )

    def run_continual_learning_report_from_logs(
        self,
        session_log_paths: list[str],
        cell_size: float = 8.0,
        max_read_chars: int = 1200,
        max_cycle_chars: int = 2400,
    ) -> ContinualLearningTraceReport:
        """Build AgentOdyssey-style diagnostics for test-time continual learning traces."""
        report = ContinualLearningTraceReport()
        safe_cell_size = float(cell_size or 8.0)
        if safe_cell_size <= 0:
            safe_cell_size = 8.0
        safe_max_read = max(1, int(max_read_chars or 1200))
        safe_max_cycle = max(1, int(max_cycle_chars or 2400))
        for path in session_log_paths:
            try:
                events = self._load_session_events(path)
                report.cases.append(self._continual_learning_trace_case(
                    path,
                    events,
                    safe_cell_size,
                    safe_max_read,
                    safe_max_cycle,
                ))
            except Exception as e:
                report.errors.append(f"{path}: {e}")
        return report

    def continual_learning_feedback(self, report: ContinualLearningTraceReport) -> dict:
        """Aggregate continual-learning diagnostics into reviewable policy hints."""
        issue_counts = {}
        recommendations = set()
        for case in report.cases:
            for issue in case.issues:
                issue_counts[issue] = issue_counts.get(issue, 0) + 1
            recommendations.update(case.recommendations)

        policy_hints = []
        if issue_counts.get("low_world_knowledge_acquisition", 0):
            policy_hints.append({
                "continual_learning_policy": "increase_world_knowledge_acquisition",
                "priority": "high",
                "reason": "session traces show little new world-state or object knowledge",
                "count": issue_counts["low_world_knowledge_acquisition"],
            })
        if issue_counts.get("low_action_diversity", 0) or issue_counts.get("low_object_exploration", 0):
            policy_hints.append({
                "continual_learning_policy": "expand_object_action_exploration",
                "priority": "medium",
                "reason": "agent repeats too few action types or touches too few object targets",
                "count": issue_counts.get("low_action_diversity", 0) + issue_counts.get("low_object_exploration", 0),
            })
        if issue_counts.get("weak_memory_learning_loop", 0):
            policy_hints.append({
                "continual_learning_policy": "strengthen_memory_learning_loop",
                "priority": "high",
                "reason": "planning traces lack enough read/write evidence for test-time learning",
                "count": issue_counts["weak_memory_learning_loop"],
            })
        if issue_counts.get("unbounded_context_cycles", 0):
            policy_hints.append({
                "continual_learning_policy": "enforce_bounded_context_contract",
                "priority": "high",
                "reason": "planner cycles contain missing, oversized, or raw-context memory contracts",
                "count": issue_counts["unbounded_context_cycles"],
            })
        if issue_counts.get("short_meaningful_horizon", 0) or issue_counts.get("no_goal_progress", 0):
            policy_hints.append({
                "continual_learning_policy": "extend_meaningful_horizon",
                "priority": "high",
                "reason": "progress signals end too early or goals do not complete",
                "count": issue_counts.get("short_meaningful_horizon", 0) + issue_counts.get("no_goal_progress", 0),
            })
        if issue_counts.get("transfer_experience_not_captured", 0):
            policy_hints.append({
                "continual_learning_policy": "capture_reusable_transfer_experience",
                "priority": "medium",
                "reason": "successful progress appears without semantic/episodic consolidation for reuse",
                "count": issue_counts["transfer_experience_not_captured"],
            })

        return {
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
            "issue_counts": dict(sorted(issue_counts.items())),
            "recommendations": sorted(recommendations),
            "policy_hints": policy_hints,
        }

    def _continual_learning_trace_case(
        self,
        source_log: str,
        events: list[dict],
        cell_size: float,
        max_read_chars: int,
        max_cycle_chars: int,
    ) -> ContinualLearningTraceCase:
        exploration = self._exploration_trace_case(source_log, events)
        world_model = self._world_model_trace_case(source_log, events, cell_size, limit=12)
        memory_policy = self._memory_policy_trace_case(source_log, events)
        bounded = self._bounded_context_trace_case(source_log, events, max_read_chars, max_cycle_chars)

        observations = [
            event.get("data", {})
            for event in events
            if event.get("type") == "observation" and isinstance(event.get("data", {}), dict)
        ]
        action_events = [
            event.get("data", {})
            for event in events
            if event.get("type") == "action" and isinstance(event.get("data", {}), dict)
        ]
        plan_count = sum(1 for event in events if event.get("type") == "plan")
        memory_write_events = [
            event.get("data", {})
            for event in events
            if event.get("type") == "memory_write" and isinstance(event.get("data", {}), dict)
        ]
        memory_read_events = [
            event.get("data", {})
            for event in events
            if event.get("type") == "memory_read" and isinstance(event.get("data", {}), dict)
        ]

        action_type_counts = {}
        action_targets = set()
        successful_actions = 0
        failed_actions = 0
        for action_data in action_events:
            action, result, action_type = self._normalized_action_record(action_data)
            self._increment(action_type_counts, action_type)
            target = self._action_target_name(action, result)
            if target:
                action_targets.add(target)
            if result.get("success") is False:
                failed_actions += 1
            elif result.get("success") is True:
                successful_actions += 1

        inventory_items = set()
        seen_observation_objects = set()
        progress_indices = []
        seen_positions = set()
        for index, event in enumerate(events):
            event_type = event.get("type")
            data = event.get("data", {}) if isinstance(event.get("data", {}), dict) else {}
            if event_type == "observation":
                before_count = len(seen_observation_objects) + len(inventory_items) + len(seen_positions)
                inventory = data.get("inventory", {}) if isinstance(data.get("inventory", {}), dict) else {}
                for item, count in inventory.items():
                    if self._safe_int(count, default=1) > 0:
                        inventory_items.add(str(item))
                seen_observation_objects.update(self._named_items_from_record(data, ["nearby_blocks", "blocks", "visible_blocks"]))
                seen_observation_objects.update(self._named_items_from_record(data, ["grounded_resources", "visual_resources", "resources"]))
                seen_observation_objects.update(
                    self._item_name(entity, default_key="type")
                    for entity in self._entity_items_from_record(data)
                    if self._item_name(entity, default_key="type")
                )
                position = self._position_tuple(data.get("position"))
                if position is not None:
                    seen_positions.add(position)
                after_count = len(seen_observation_objects) + len(inventory_items) + len(seen_positions)
                if after_count > before_count:
                    progress_indices.append(index)
            elif event_type == "action":
                result = data.get("result", {}) if isinstance(data.get("result", {}), dict) else {}
                if result.get("success") is True:
                    progress_indices.append(index)
            elif event_type == "goal_end":
                if self._event_success(data) is True:
                    progress_indices.append(index)
            elif event_type == "goal_verification":
                if data.get("achieved") is True or data.get("accepted") is True:
                    progress_indices.append(index)
            elif event_type in {"memory_write", "memory_consolidation", "failure_correction_completed"}:
                progress_indices.append(index)

        progress_event_count = len(set(progress_indices))
        meaningful_horizon_events = (max(progress_indices) + 1) if progress_indices else 0
        stagnation_tail_events = max(0, len(events) - meaningful_horizon_events)
        object_exploration = set(exploration.unique_block_types)
        object_exploration.update(exploration.unique_resource_types)
        object_exploration.update(exploration.unique_entity_types)
        object_exploration.update(inventory_items)
        object_exploration.update(action_targets)

        completion_rate = exploration.completed_goal_count / exploration.goal_count if exploration.goal_count else 0.0
        action_success_rate = successful_actions / len(action_events) if action_events else 0.0
        progress_score = round(min(1.0, (completion_rate * 0.6) + (action_success_rate * 0.4)), 3)
        exploration_score = round(min(1.0, (exploration.unique_position_count / 8.0) + (len(object_exploration) / 24.0)), 3)
        world_knowledge_score = round(min(1.0, (world_model.unique_cell_count / 8.0) + (world_model.resource_hotspot_count / 6.0)), 3)
        memory_score = round(min(1.0, (len(memory_read_events) + len(memory_write_events) + memory_policy.consolidation_signal_count) / max(1, plan_count + exploration.goal_count + 2)), 3)
        action_diversity_score = round(self._normalized_entropy(action_type_counts), 3)
        horizon_score = round((meaningful_horizon_events / len(events)) if events else 0.0, 3)
        axis_scores = {
            "progress": progress_score,
            "exploration": exploration_score,
            "world_knowledge": world_knowledge_score,
            "memory": memory_score,
            "action_diversity": action_diversity_score,
            "meaningful_horizon": horizon_score,
            "continual_learning": round(
                (progress_score + exploration_score + world_knowledge_score + memory_score + action_diversity_score + horizon_score) / 6.0,
                3,
            ),
        }

        issues = []
        recommendations = []
        if exploration.goal_count and exploration.completed_goal_count == 0:
            issues.append("no_goal_progress")
            recommendations.append("Use verifier-backed subgoals and curriculum fallback when no goal completes.")
        if len(object_exploration) < 3 and observations:
            issues.append("low_object_exploration")
            recommendations.append("Bias curriculum toward nearby unseen blocks/resources/entities.")
        if world_knowledge_score < 0.25 and observations:
            issues.append("low_world_knowledge_acquisition")
            recommendations.append("Record explicit world-model cells, resources, and frontiers during autonomous runs.")
        if len(action_events) >= 3 and len(action_type_counts) <= 1:
            issues.append("low_action_diversity")
            recommendations.append("Add action-diversity checks before repeating the same primitive action family.")
        if len(memory_read_events) == 0 or len(memory_write_events) == 0:
            issues.append("weak_memory_learning_loop")
            recommendations.append("Ensure each long-horizon run logs typed memory reads and reusable memory writes.")
        if bounded.unbounded_cycle_count:
            issues.append("unbounded_context_cycles")
            recommendations.append("Run bounded-context-report and replace oversized/raw planner context with typed retrieval.")
        if events and meaningful_horizon_events and meaningful_horizon_events < len(events) * 0.5:
            issues.append("short_meaningful_horizon")
            recommendations.append("Trigger self-evolution or curriculum repair when progress disappears in the back half of a run.")
        if progress_event_count and memory_policy.semantic_write_candidate_count and memory_policy.missed_semantic_write_count:
            issues.append("transfer_experience_not_captured")
            recommendations.append("Promote successful repeated outcomes into semantic memory or skill candidates for later tasks.")
        if len(action_events) and failed_actions / len(action_events) >= 0.4:
            issues.append("high_action_failure_rate")
            recommendations.append("Route repeated failed action patterns through action-abstraction and self-evolution reports.")

        return ContinualLearningTraceCase(
            source_log=source_log,
            event_count=len(events),
            observation_count=len(observations),
            goal_count=exploration.goal_count,
            completed_goal_count=exploration.completed_goal_count,
            failed_goal_count=exploration.failed_goal_count,
            plan_count=plan_count,
            action_count=len(action_events),
            successful_action_count=successful_actions,
            failed_action_count=failed_actions,
            unique_action_type_count=len(action_type_counts),
            unique_action_target_count=len(action_targets),
            action_entropy=round(self._normalized_entropy(action_type_counts), 3),
            memory_read_count=len(memory_read_events),
            memory_write_count=len(memory_write_events),
            episodic_write_count=sum(1 for item in memory_write_events if self._memory_write_is_episodic(item)),
            semantic_write_count=sum(1 for item in memory_write_events if self._memory_write_is_semantic(item)),
            consolidation_signal_count=memory_policy.consolidation_signal_count,
            bounded_cycle_count=bounded.bounded_cycle_count,
            unbounded_context_cycle_count=bounded.unbounded_cycle_count,
            unique_position_count=exploration.unique_position_count,
            path_distance=exploration.path_distance,
            unique_cell_count=world_model.unique_cell_count,
            frontier_count=world_model.frontier_count,
            resource_hotspot_count=world_model.resource_hotspot_count,
            unique_block_type_count=len(exploration.unique_block_types),
            unique_resource_type_count=len(exploration.unique_resource_types),
            unique_entity_type_count=len(exploration.unique_entity_types),
            unique_inventory_item_count=len(inventory_items),
            object_exploration_count=len(object_exploration),
            progress_event_count=progress_event_count,
            meaningful_horizon_events=meaningful_horizon_events,
            stagnation_tail_events=stagnation_tail_events,
            axis_scores=axis_scores,
            issues=sorted(set(issues)),
            recommendations=self._dedupe_strings(recommendations)[:8],
            ready_for_continual_learning_review=bool(observations or action_events or plan_count),
        )

    def run_task_stream_transfer_report_from_files(
        self,
        stream_files: list[str],
        cell_size: float = 8.0,
    ) -> TaskStreamTransferReport:
        """Evaluate controlled Minecraft task streams for reusable transfer and interference."""
        report = TaskStreamTransferReport()
        safe_cell_size = float(cell_size or 8.0)
        if safe_cell_size <= 0:
            safe_cell_size = 8.0
        for path in stream_files:
            try:
                for spec in self._load_task_stream_specs(path):
                    report.cases.append(self._task_stream_transfer_case(path, spec, safe_cell_size))
            except Exception as e:
                report.errors.append(f"{path}: {e}")
        return report

    def task_stream_transfer_feedback(self, report: TaskStreamTransferReport) -> dict:
        """Summarize AgentCL-style stream diagnostics into policy hints."""
        issue_counts = {}
        recommendations = set()
        for case in report.cases:
            for issue in case.issues:
                issue_counts[issue] = issue_counts.get(issue, 0) + 1
            recommendations.update(case.recommendations)
            for task in case.tasks:
                for issue in task.issues:
                    issue_counts[issue] = issue_counts.get(issue, 0) + 1

        policy_hints = []
        if issue_counts.get("missing_controlled_scores", 0) or issue_counts.get("missing_baseline_score", 0):
            policy_hints.append({
                "task_stream_policy": "add_controlled_baseline_and_replay_scores",
                "priority": "high",
                "reason": "streams need baseline and replay scores before transfer claims are trusted",
                "count": issue_counts.get("missing_controlled_scores", 0) + issue_counts.get("missing_baseline_score", 0),
            })
        if issue_counts.get("low_reuse_coverage", 0) or issue_counts.get("missing_reuse_evidence", 0):
            policy_hints.append({
                "task_stream_policy": "instrument_reuse_evidence",
                "priority": "high",
                "reason": "expected reusable sub-solutions are not visible in memory, skill, or trace evidence",
                "count": issue_counts.get("low_reuse_coverage", 0) + issue_counts.get("missing_reuse_evidence", 0),
            })
        if issue_counts.get("stability_regression", 0) or issue_counts.get("heldout_regression", 0) or issue_counts.get("transfer_regression", 0):
            policy_hints.append({
                "task_stream_policy": "quarantine_interfering_memories_or_skills",
                "priority": "high",
                "reason": "later replay or held-out variants regress after memory/skill reuse",
                "count": (
                    issue_counts.get("stability_regression", 0)
                    + issue_counts.get("heldout_regression", 0)
                    + issue_counts.get("transfer_regression", 0)
                ),
            })
        if issue_counts.get("missing_second_pass_probe", 0):
            policy_hints.append({
                "task_stream_policy": "add_second_pass_stability_probe",
                "priority": "medium",
                "reason": "streams cannot separate one-shot plasticity from stable retained behavior",
                "count": issue_counts["missing_second_pass_probe"],
            })
        if issue_counts.get("missing_heldout_probe", 0):
            policy_hints.append({
                "task_stream_policy": "add_heldout_generalization_probe",
                "priority": "medium",
                "reason": "streams need held-out variants to distinguish memorization from reusable transfer",
                "count": issue_counts["missing_heldout_probe"],
            })

        return {
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
            "issue_counts": dict(sorted(issue_counts.items())),
            "recommendations": sorted(recommendations),
            "policy_hints": policy_hints,
        }

    def build_task_stream_transfer_gate(
        self,
        transfer_reports: Optional[list[dict]] = None,
        transfer_report_paths: Optional[list[str]] = None,
        target: str = "memory_or_skill_promotion",
        min_plasticity_gain: float = 0.01,
        min_stability_gain: float = 0.0,
        min_generalization_gain: float = 0.0,
        min_reuse_coverage: float = 0.5,
        max_interference_count: int = 0,
        require_heldout: bool = True,
    ) -> dict:
        """Gate memory/skill promotion with controlled task-stream transfer evidence."""
        report = {
            "required": True,
            "target": target,
            "readiness": "review",
            "decision": "keep_candidate_review_only",
            "reason": "controlled task-stream transfer evidence is required",
            "transfer_report_count": 0,
            "stream_count": 0,
            "ready_stream_count": 0,
            "task_count": 0,
            "reuse_coverage": 0.0,
            "average_plasticity_gain": None,
            "average_stability_gain": None,
            "average_generalization_gain": None,
            "interference_count": 0,
            "thresholds": {
                "min_plasticity_gain": float(min_plasticity_gain),
                "min_stability_gain": float(min_stability_gain),
                "min_generalization_gain": float(min_generalization_gain),
                "min_reuse_coverage": float(min_reuse_coverage),
                "max_interference_count": int(max_interference_count),
                "require_heldout": bool(require_heldout),
            },
            "evidence_count": 0,
            "warning_count": 0,
            "regression_count": 0,
            "missing": [],
            "policy_hints": [],
            "checks": [],
            "errors": [],
        }
        items = self._load_gate_payloads(
            transfer_reports or [],
            transfer_report_paths or [],
            report["errors"],
            "task_stream_transfer_report",
        )
        report["transfer_report_count"] = len(items)
        if not items:
            report["missing"].append("task_stream_transfer_report")

        plasticity_values = []
        stability_values = []
        generalization_values = []
        policy_hints = set()
        expected_tags = 0
        hit_tags = 0
        for source, payload in items:
            check = self._task_stream_transfer_gate_check(source, payload, report["thresholds"])
            report["checks"].append(check)
            metrics = check.get("metrics", {})
            report["stream_count"] += self._gate_int(metrics.get("stream_count"))
            report["ready_stream_count"] += self._gate_int(metrics.get("ready_stream_count"))
            report["task_count"] += self._gate_int(metrics.get("task_count"))
            report["interference_count"] += self._gate_int(metrics.get("interference_count"))
            expected_tags += self._gate_int(metrics.get("reuse_expected_tag_count"))
            hit_tags += self._gate_int(metrics.get("reuse_hit_tag_count"))
            for key, values in (
                ("average_plasticity_gain", plasticity_values),
                ("average_stability_gain", stability_values),
                ("average_generalization_gain", generalization_values),
            ):
                value = self._gate_float_or_none(metrics.get(key))
                if value is not None:
                    values.append(value)
            for hint in metrics.get("policy_hints", []):
                if hint:
                    policy_hints.add(str(hint))

        report["reuse_coverage"] = round(hit_tags / expected_tags, 3) if expected_tags else 0.0
        report["average_plasticity_gain"] = _average_optional(plasticity_values)
        report["average_stability_gain"] = _average_optional(stability_values)
        report["average_generalization_gain"] = _average_optional(generalization_values)
        report["policy_hints"] = sorted(policy_hints)
        report["evidence_count"] = sum(1 for check in report["checks"] if check.get("status") == "pass")
        report["warning_count"] = sum(1 for check in report["checks"] if check.get("status") == "warn")
        report["regression_count"] = sum(1 for check in report["checks"] if check.get("status") == "fail")

        if report["errors"]:
            report["readiness"] = "error"
            report["decision"] = "do_not_promote_candidate"
            report["reason"] = "gate inputs could not be loaded"
        elif report["regression_count"]:
            report["readiness"] = "rejected"
            report["decision"] = "do_not_promote_candidate"
            report["reason"] = "controlled task streams show transfer, stability, held-out, or interference regression"
        elif report["missing"] or report["warning_count"] or not report["evidence_count"]:
            report["readiness"] = "review"
            report["decision"] = "keep_candidate_review_only"
            report["reason"] = "transfer evidence is incomplete or below promotion confidence"
        else:
            report["readiness"] = "approved"
            report["decision"] = "allow_candidate_promotion"
            report["reason"] = "controlled task streams show positive transfer without stability or held-out regressions"
        return report

    def _task_stream_transfer_gate_check(self, source: str, payload: dict, thresholds: dict) -> dict:
        feedback = payload.get("task_stream_feedback", payload) if isinstance(payload, dict) else {}
        if not isinstance(feedback, dict):
            feedback = {}
        errors = payload.get("errors", []) if isinstance(payload.get("errors", []), list) else []
        policy_hints = []
        for hint in feedback.get("policy_hints", []) if isinstance(feedback.get("policy_hints", []), list) else []:
            if isinstance(hint, dict):
                name = hint.get("task_stream_policy") or hint.get("policy")
                if name:
                    policy_hints.append(str(name))
        metrics = {
            "stream_count": self._gate_int(payload.get("stream_count", feedback.get("stream_count", 0))),
            "ready_stream_count": self._gate_int(payload.get("ready_stream_count", feedback.get("ready_stream_count", 0))),
            "task_count": self._gate_int(payload.get("task_count", feedback.get("task_count", 0))),
            "reuse_expected_tag_count": self._gate_int(payload.get("reuse_expected_tag_count", feedback.get("reuse_expected_tag_count", 0))),
            "reuse_hit_tag_count": self._gate_int(payload.get("reuse_hit_tag_count", feedback.get("reuse_hit_tag_count", 0))),
            "reuse_coverage": self._gate_float_or_none(payload.get("reuse_coverage", feedback.get("reuse_coverage"))),
            "average_plasticity_gain": self._gate_float_or_none(payload.get("average_plasticity_gain", feedback.get("average_plasticity_gain"))),
            "average_stability_gain": self._gate_float_or_none(payload.get("average_stability_gain", feedback.get("average_stability_gain"))),
            "average_generalization_gain": self._gate_float_or_none(payload.get("average_generalization_gain", feedback.get("average_generalization_gain"))),
            "interference_count": self._gate_int(payload.get("interference_count", feedback.get("interference_count", 0))),
            "policy_hints": self._dedupe_strings(policy_hints),
        }
        if errors:
            return self._gate_check(source, "task_stream_transfer_report", "fail", "task-stream transfer report contains errors", metrics)
        if metrics["stream_count"] <= 0 or metrics["task_count"] <= 0:
            return self._gate_check(source, "task_stream_transfer_report", "warn", "no controlled task-stream evidence was found", metrics)
        if metrics["ready_stream_count"] <= 0:
            return self._gate_check(source, "task_stream_transfer_report", "warn", "no stream is ready for transfer review", metrics)
        if metrics["interference_count"] > int(thresholds.get("max_interference_count", 0)):
            return self._gate_check(source, "task_stream_transfer_report", "fail", "interference or regression cases exceed the allowed limit", metrics)

        reuse_coverage = metrics["reuse_coverage"]
        if reuse_coverage is None:
            expected = metrics["reuse_expected_tag_count"]
            reuse_coverage = round(metrics["reuse_hit_tag_count"] / expected, 3) if expected else 0.0
            metrics["reuse_coverage"] = reuse_coverage
        if reuse_coverage < float(thresholds.get("min_reuse_coverage", 0.5)):
            return self._gate_check(source, "task_stream_transfer_report", "warn", "reuse evidence coverage is below the promotion threshold", metrics)

        for key, threshold, label in (
            ("average_plasticity_gain", thresholds.get("min_plasticity_gain", 0.01), "plasticity gain"),
            ("average_stability_gain", thresholds.get("min_stability_gain", 0.0), "second-pass stability gain"),
            ("average_generalization_gain", thresholds.get("min_generalization_gain", 0.0), "held-out generalization gain"),
        ):
            value = metrics.get(key)
            if value is None:
                if key == "average_generalization_gain" and not thresholds.get("require_heldout", True):
                    continue
                return self._gate_check(source, "task_stream_transfer_report", "warn", f"{label} evidence is missing", metrics)
            if value < float(threshold):
                return self._gate_check(source, "task_stream_transfer_report", "fail", f"{label} is below the promotion threshold", metrics)

        return self._gate_check(source, "task_stream_transfer_report", "pass", "controlled transfer evidence passes promotion thresholds", metrics)

    def _task_stream_transfer_case(
        self,
        source_file: str,
        spec: dict,
        cell_size: float,
    ) -> TaskStreamTransferCase:
        stream_id = str(spec.get("id") or spec.get("stream_id") or os.path.splitext(os.path.basename(source_file))[0])
        description = str(spec.get("description") or spec.get("name") or "")
        task_records = []
        for index, task in enumerate(spec.get("tasks", []) if isinstance(spec.get("tasks", []), list) else [], start=1):
            if isinstance(task, dict):
                task_records.append((index, "task", task))
        for index, task in enumerate(spec.get("heldout_tasks", []) if isinstance(spec.get("heldout_tasks", []), list) else [], start=1):
            if isinstance(task, dict):
                merged = {**task}
                if "heldout_score" not in merged and "score" in merged:
                    merged["heldout_score"] = merged["score"]
                task_records.append((len(task_records) + index, "heldout", merged))

        seen_task_ids = set()
        tasks = []
        for index, stage, task_data in task_records:
            task = self._task_stream_transfer_task(source_file, stream_id, index, stage, task_data, cell_size)
            missing_deps = [dependency for dependency in task.depends_on if dependency not in seen_task_ids]
            if missing_deps:
                task.issues.append("missing_dependency")
            tasks.append(task)
            seen_task_ids.add(task.task_id)

        reuse_expected = sum(len(task.expected_reuse_tags) for task in tasks)
        reuse_hits = sum(len(task.reuse_hit_tags) for task in tasks)
        transfer_gains = [task.transfer_gain for task in tasks if task.transfer_gain is not None]
        stability_gains = [task.stability_gain for task in tasks if task.stability_gain is not None]
        generalization_gains = [task.generalization_gain for task in tasks if task.generalization_gain is not None]
        missing_baseline = sum(1 for task in tasks if task.baseline_score is None)
        missing_second = sum(1 for task in tasks if task.second_pass_score is None)
        missing_heldout = sum(1 for task in tasks if task.heldout_score is None)
        interference = sum(
            1 for task in tasks
            if "transfer_regression" in task.issues
            or "stability_regression" in task.issues
            or "heldout_regression" in task.issues
        )

        issues = []
        recommendations = []
        if not tasks:
            issues.append("no_tasks")
            recommendations.append("Add ordered Minecraft task records with baseline and replay scores.")
        if not transfer_gains:
            issues.append("missing_controlled_scores")
            recommendations.append("Record baseline_score and first_pass_score, or attach session logs for both stages.")
        if not any(task.depends_on or task.expected_reuse_tags for task in tasks):
            issues.append("missing_reuse_relationships")
            recommendations.append("Declare depends_on and expected_reuse_tags so transfer is testable, not inferred.")
        reuse_coverage = round(reuse_hits / reuse_expected, 3) if reuse_expected else 0.0
        if reuse_expected and reuse_coverage < 0.5:
            issues.append("low_reuse_coverage")
            recommendations.append("Log memory reads, skill matches, or sub-solution tags when later tasks reuse earlier work.")
        plasticity_gain = _average_optional(transfer_gains)
        stability_gain = _average_optional(stability_gains)
        generalization_gain = _average_optional(generalization_gains)
        if plasticity_gain is not None and plasticity_gain < -0.01:
            issues.append("negative_plasticity_gain")
            recommendations.append("Compare retrieved memories against baseline to isolate which reuse source harmed first-pass performance.")
        if stability_gain is not None and stability_gain < -0.01:
            issues.append("stability_regression")
            recommendations.append("Add stale/contradicted memory filtering before second-pass replay.")
        if generalization_gain is not None and generalization_gain < -0.01:
            issues.append("heldout_regression")
            recommendations.append("Gate reusable skills on held-out Minecraft variants before promoting them to runtime defaults.")
        if missing_second == len(tasks) and tasks:
            issues.append("missing_second_pass_probe")
            recommendations.append("Add second_pass_score or second_pass_session_log to test retention after reuse.")
        if missing_heldout == len(tasks) and tasks:
            issues.append("missing_heldout_probe")
            recommendations.append("Add heldout_score or heldout_session_log for compositional variants with shared sub-solutions.")

        return TaskStreamTransferCase(
            stream_id=stream_id,
            source_file=source_file,
            description=description,
            task_count=len(tasks),
            ready_task_count=sum(1 for task in tasks if task.ready_for_transfer_review),
            reusable_relation_count=sum(1 for task in tasks if task.depends_on or task.expected_reuse_tags),
            reuse_expected_tag_count=reuse_expected,
            reuse_hit_tag_count=reuse_hits,
            reuse_coverage=reuse_coverage,
            average_baseline_score=_average_optional(task.baseline_score for task in tasks),
            average_first_pass_score=_average_optional(task.first_pass_score for task in tasks),
            average_second_pass_score=_average_optional(task.second_pass_score for task in tasks),
            average_heldout_score=_average_optional(task.heldout_score for task in tasks),
            plasticity_gain=plasticity_gain,
            stability_gain=stability_gain,
            generalization_gain=generalization_gain,
            interference_count=interference,
            missing_baseline_count=missing_baseline,
            missing_second_pass_count=missing_second,
            missing_heldout_count=missing_heldout,
            issues=sorted(set(issues)),
            recommendations=self._dedupe_strings(recommendations)[:8],
            tasks=tasks,
            ready_for_transfer_review=bool(tasks and transfer_gains and not any(issue in {"missing_controlled_scores", "missing_reuse_relationships"} for issue in issues)),
        )

    def _task_stream_transfer_task(
        self,
        source_file: str,
        stream_id: str,
        index: int,
        stage: str,
        task_data: dict,
        cell_size: float,
    ) -> TaskStreamTransferTask:
        task_id = str(task_data.get("id") or task_data.get("task_id") or f"task_{index}")
        goal = str(task_data.get("goal") or task_data.get("task") or task_data.get("objective") or "")
        depends_on = self._string_list(task_data.get("depends_on") or task_data.get("dependencies") or task_data.get("requires"))
        expected_tags = self._normalized_tag_list(
            task_data.get("expected_reuse_tags")
            or task_data.get("reuse_tags")
            or task_data.get("transfer_tags")
            or []
        )
        produced_tags = self._normalized_tag_list(
            task_data.get("produced_tags")
            or task_data.get("memory_tags")
            or task_data.get("skill_tags")
            or []
        )
        session_logs = self._task_stream_session_logs(task_data, source_file)
        session_summary = self._task_stream_session_summary(session_logs, cell_size)

        baseline_score = self._task_stream_score(task_data, "baseline", source_file, cell_size)
        first_score = self._task_stream_score(task_data, "first_pass", source_file, cell_size)
        if first_score is None:
            first_score = self._task_stream_score(task_data, "observed", source_file, cell_size)
        if first_score is None:
            first_score = self._task_stream_score(task_data, "score", source_file, cell_size)
        second_score = self._task_stream_score(task_data, "second_pass", source_file, cell_size)
        heldout_score = self._task_stream_score(task_data, "heldout", source_file, cell_size)
        if stage == "heldout" and heldout_score is None:
            heldout_score = first_score

        transfer_gain = self._score_delta(first_score, baseline_score)
        stability_gain = self._score_delta(second_score, first_score)
        generalization_gain = self._score_delta(heldout_score, baseline_score)
        evidence_text = self._task_stream_evidence_text(task_data, session_summary)
        hit_tags = [tag for tag in expected_tags if self._tag_in_text(tag, evidence_text)]
        missing_tags = [tag for tag in expected_tags if tag not in hit_tags]

        issues = []
        if baseline_score is None:
            issues.append("missing_baseline_score")
        if first_score is None:
            issues.append("missing_first_pass_score")
        if expected_tags and not hit_tags:
            issues.append("missing_reuse_evidence")
        if transfer_gain is not None and transfer_gain < -0.05:
            issues.append("transfer_regression")
        if stability_gain is not None and stability_gain < -0.05:
            issues.append("stability_regression")
        if generalization_gain is not None and generalization_gain < -0.05:
            issues.append("heldout_regression")

        return TaskStreamTransferTask(
            stream_id=stream_id,
            task_id=task_id,
            goal=goal,
            stage=str(task_data.get("stage") or stage or "task"),
            source_file=source_file,
            source_log=session_logs[0] if session_logs else "",
            depends_on=depends_on,
            expected_reuse_tags=expected_tags,
            produced_tags=produced_tags,
            reuse_hit_tags=hit_tags,
            reuse_missing_tags=missing_tags,
            baseline_score=baseline_score,
            first_pass_score=first_score,
            second_pass_score=second_score,
            heldout_score=heldout_score,
            transfer_gain=transfer_gain,
            stability_gain=stability_gain,
            generalization_gain=generalization_gain,
            memory_read_count=session_summary.get("memory_read_count", 0),
            memory_write_count=session_summary.get("memory_write_count", 0),
            completed_goal_count=session_summary.get("completed_goal_count", 0),
            failed_goal_count=session_summary.get("failed_goal_count", 0),
            action_count=session_summary.get("action_count", 0),
            failed_action_count=session_summary.get("failed_action_count", 0),
            issues=sorted(set(issues)),
            ready_for_transfer_review=bool(first_score is not None and (baseline_score is not None or session_logs)),
        )

    def run_visual_review_pipeline(
        self,
        session_log_paths: list[str],
        mode: str = "both",
        label_file: str = "",
        promotion_critic=None,
        goal_critic=None,
        include_causal_summaries: bool = False,
        include_failure_corrections: bool = False,
        run_ablations: bool = False,
    ) -> VisualReviewPipelineReport:
        """Run the offline visual review chain from trace audit to optional ablations."""
        normalized_mode = str(mode or "both").lower()
        if normalized_mode == "goal":
            ablation_mode = "goal"
        elif normalized_mode == "promotion":
            ablation_mode = "promotion"
        else:
            ablation_mode = "both"

        report = VisualReviewPipelineReport(
            session_logs=list(session_log_paths or []),
            mode=ablation_mode,
            label_file=label_file or "",
            run_ablations=run_ablations,
        )
        report.visual_trace = self.run_visual_trace_report_from_logs(
            report.session_logs,
            include_causal_summaries=include_causal_summaries,
            include_failure_corrections=include_failure_corrections,
        )
        report.label_templates = self.build_review_label_templates_from_logs(
            report.session_logs,
            mode=ablation_mode,
            include_causal_summaries=include_causal_summaries,
            include_failure_corrections=include_failure_corrections,
        )

        promotion_labels = {}
        goal_labels = {}
        if label_file:
            report.label_validation = self.validate_review_labels(label_file)
            if report.label_validation.ok:
                if ablation_mode in {"promotion", "both"}:
                    promotion_labels = self._review_labels_by_type(label_file, "promotion_review")
                if ablation_mode in {"goal", "both"}:
                    goal_labels = self._review_labels_by_type(label_file, "goal_verification")
            elif run_ablations:
                report.errors.append("label validation failed; skipping visual agreement ablations")

        if not run_ablations or (label_file and report.label_validation and not report.label_validation.ok):
            return report

        if ablation_mode in {"promotion", "both"}:
            try:
                report.promotion_ablation = self.run_promotion_review_ablation_from_logs(
                    report.session_logs,
                    promotion_critic=promotion_critic,
                    include_causal_summaries=include_causal_summaries,
                    include_failure_corrections=include_failure_corrections,
                    manual_labels=promotion_labels,
                )
            except Exception as e:
                report.errors.append(f"promotion ablation failed: {e}")
        if ablation_mode in {"goal", "both"}:
            try:
                report.goal_ablation = self.run_goal_verification_ablation_from_logs(
                    report.session_logs,
                    goal_critic=goal_critic,
                    manual_labels=goal_labels,
                )
            except Exception as e:
                report.errors.append(f"goal verification ablation failed: {e}")
        try:
            report.visual_action_ablation = self.run_visual_action_ablation_from_logs(
                report.session_logs,
                include_builtin=False,
            )
        except Exception as e:
            report.errors.append(f"visual action ablation failed: {e}")
        return report

    def visual_review_pipeline_report_to_dict(self, report: VisualReviewPipelineReport) -> dict:
        payload = asdict(report)
        payload["summary"] = {
            "ready": report.ready,
            "ready_for_manual_review": report.ready_for_manual_review,
            "ready_for_agreement_ablation": report.ready_for_agreement_ablation,
            "label_ok": report.label_ok,
            "template_count": report.template_count,
            "promotion_template_count": report.promotion_template_count,
            "goal_template_count": report.goal_template_count,
            "error_template_count": report.error_template_count,
            "visual_trace_ready_log_count": report.visual_trace.ready_log_count,
            "visual_trace_log_count": report.visual_trace.log_count,
            "verified_screenshot_log_count": report.visual_trace.screenshot_log_count,
            "raw_screenshot_log_count": report.visual_trace.raw_screenshot_log_count,
            "missing_screenshot_count": report.visual_trace.missing_screenshot_count,
            "invalid_screenshot_count": report.visual_trace.invalid_screenshot_count,
        }
        if report.label_validation is not None:
            payload["summary"].update({
                "label_count": report.label_validation.label_count,
                "label_ok_count": report.label_validation.ok_count,
                "label_error_count": report.label_validation.error_count,
                "label_screenshot_unverified_count": report.label_validation.screenshot_unverified_count,
            })
        if report.promotion_ablation is not None:
            payload["summary"].update({
                "promotion_candidate_count": report.promotion_ablation.candidate_count,
                "promotion_changed_count": report.promotion_ablation.changed_count,
                "promotion_screenshot_vlm_added_value_count": report.promotion_ablation.screenshot_vlm_added_value_count,
            })
        if report.goal_ablation is not None:
            payload["summary"].update({
                "goal_count": report.goal_ablation.goal_count,
                "goal_changed_count": report.goal_ablation.changed_count,
                "goal_screenshot_vlm_added_value_count": report.goal_ablation.screenshot_vlm_added_value_count,
            })
        if report.visual_action_ablation is not None:
            payload["summary"].update({
                "visual_action_case_count": len(report.visual_action_ablation.cases),
                "visual_action_passed_count": report.visual_action_ablation.passed_count,
                "visual_action_changed_count": report.visual_action_ablation.changed_count,
                "visual_action_helped_count": report.visual_action_ablation.helped_count,
            })
        return payload

    def _visual_trace_coverage_case(self, source_log: str, events: list[dict], candidates: list) -> VisualTraceCoverageCase:
        observations = [
            event.get("data", {})
            for event in events
            if event.get("type") == "observation" and isinstance(event.get("data", {}), dict)
        ]
        visual_events = [
            event.get("data", {})
            for event in events
            if event.get("type") in {"vision", "visual_analysis"} and isinstance(event.get("data", {}), dict)
        ]
        visual_keys = set()
        screenshot_paths = []
        visual_analysis_count = 0
        visual_observation_count = 0
        for record in observations + visual_events:
            record_keys = self._goal_visual_evidence_keys(record)
            if record_keys:
                visual_observation_count += 1
                visual_keys.update(record_keys)
            screenshot_paths.extend(self._visual_paths_from_record(record))
            if any(record.get(key) for key in ("visual_analysis", "vlm_analysis", "screenshot_analysis", "summary", "analysis", "description")):
                visual_analysis_count += 1

        segments = self._session_goal_segments(events)
        goals_with_visual = 0
        missing_visual_goals = []
        for goal_index, (goal, segment_events) in enumerate(segments, start=1):
            if self._segment_has_visual_evidence(segment_events, source_log):
                goals_with_visual += 1
            else:
                missing_visual_goals.append(f"{goal_index}:{goal}")

        candidates_with_visual = 0
        for candidate in candidates:
            visual = candidate.signals.get("visual_evidence", {}) if isinstance(getattr(candidate, "signals", {}), dict) else {}
            if visual:
                candidates_with_visual += 1
                visual_keys.update(str(key) for key in visual.keys())
                screenshots = visual.get("screenshots", [])
                if isinstance(screenshots, list):
                    screenshot_paths.extend(str(path) for path in screenshots if path)
                elif screenshots:
                    screenshot_paths.append(str(screenshots))

        deduped_screenshots = self._dedupe_strings(screenshot_paths)
        screenshot_status = self._screenshot_status_for_paths(deduped_screenshots, source_log)
        verified_screenshots = screenshot_status["verified"]
        missing_screenshots = screenshot_status["missing"]
        invalid_screenshots = screenshot_status["invalid"]
        ready = bool(
            verified_screenshots
            or visual_analysis_count
            or goals_with_visual
            or candidates_with_visual
        )
        return VisualTraceCoverageCase(
            source_log=source_log,
            observation_count=len(observations),
            visual_observation_count=visual_observation_count,
            raw_screenshot_count=len(deduped_screenshots),
            screenshot_count=len(verified_screenshots),
            missing_screenshot_count=len(missing_screenshots),
            invalid_screenshot_count=len(invalid_screenshots),
            visual_analysis_count=visual_analysis_count,
            goal_count=len(segments),
            goals_with_visual_evidence=goals_with_visual,
            promotion_candidate_count=len(candidates),
            promotion_candidates_with_visual_evidence=candidates_with_visual,
            ready_for_visual_ablation=ready,
            visual_evidence_keys=sorted(visual_keys),
            raw_screenshot_paths=deduped_screenshots[:12],
            screenshot_paths=verified_screenshots[:12],
            missing_screenshot_paths=missing_screenshots[:12],
            invalid_screenshot_paths=invalid_screenshots[:12],
            missing_visual_goals=missing_visual_goals[:12],
        )

    def _exploration_trace_case(self, source_log: str, events: list[dict]) -> ExplorationTraceCase:
        observations = [
            event.get("data", {})
            for event in events
            if event.get("type") == "observation" and isinstance(event.get("data", {}), dict)
        ]
        visual_events = [
            event.get("data", {})
            for event in events
            if event.get("type") in {"vision", "visual_analysis"} and isinstance(event.get("data", {}), dict)
        ]
        goal_segments = self._session_goal_segments(events)
        goal_end_events = [
            event for event in events
            if event.get("type") == "goal_end" and isinstance(event.get("data", {}), dict)
        ]
        action_events = [
            event.get("data", {})
            for event in events
            if event.get("type") == "action" and isinstance(event.get("data", {}), dict)
        ]
        plan_events = [
            event.get("data", {})
            for event in events
            if event.get("type") == "plan" and isinstance(event.get("data", {}), dict)
        ]

        positions = [
            position for position in (self._position_tuple(obs.get("position")) for obs in observations)
            if position is not None
        ]
        unique_positions = sorted(set(positions))
        x_span, y_span, z_span = self._position_spans(positions)
        path_distance = self._path_distance(positions)

        block_types = set()
        entity_types = set()
        resource_types = set()
        hostile_encounters = 0
        danger_events = 0
        visual_observations = 0
        screenshot_paths = []
        for observation in observations:
            block_types.update(self._named_items_from_record(observation, ["nearby_blocks", "blocks", "visible_blocks"]))
            resource_types.update(self._named_items_from_record(observation, ["grounded_resources", "visual_resources", "resources"]))
            entities = self._entity_items_from_record(observation)
            dangers = observation.get("dangers", []) if isinstance(observation.get("dangers", []), list) else []
            entity_types.update(self._item_name(entity, default_key="type") for entity in entities + dangers if self._item_name(entity, default_key="type"))
            hostile_entities = [entity for entity in entities if self._is_hostile_entity(entity)]
            hostile_encounters += 1 if hostile_entities or dangers else 0
            danger_events += len(hostile_entities) + len(dangers)
            screenshot_paths.extend(self._visual_paths_from_record(observation))
            if self._record_has_exploration_visual_signal(observation, source_log):
                visual_observations += 1

        for record in visual_events:
            resource_types.update(self._named_items_from_record(record, ["grounded_resources", "visual_resources", "resources"]))
            entity_types.update(self._named_items_from_record(record, ["dangers", "nearby_entities"]))
            screenshot_paths.extend(self._visual_paths_from_record(record))

        deduped_screenshots = self._dedupe_strings(screenshot_paths)
        screenshot_status = self._screenshot_status_for_paths(deduped_screenshots, source_log)
        failure_categories = {}
        failed_action_count = 0
        for action_data in action_events:
            result = action_data.get("result", {}) if isinstance(action_data.get("result", {}), dict) else {}
            if result.get("success") is False:
                failed_action_count += 1
                category = self._action_failure_category(action_data.get("action", {}), result)
                failure_categories[category] = failure_categories.get(category, 0) + 1

        completed_goals = 0
        failed_goals = 0
        for event in goal_end_events:
            completed = self._event_success(event.get("data", {}))
            if completed is True:
                completed_goals += 1
            elif completed is False:
                failed_goals += 1

        goals = [goal for goal, _ in goal_segments if goal]
        multi_step_plans = sum(
            1 for plan in plan_events
            if isinstance(plan.get("actions"), list) and len(plan.get("actions", [])) > 1
        )
        ready = bool(
            observations
            and (
                len(unique_positions) > 1
                or block_types
                or resource_types
                or entity_types
                or visual_observations
            )
        )
        return ExplorationTraceCase(
            source_log=source_log,
            observation_count=len(observations),
            goal_count=len(goal_segments),
            completed_goal_count=completed_goals,
            failed_goal_count=failed_goals,
            action_count=len(action_events),
            failed_action_count=failed_action_count,
            plan_count=len(plan_events),
            multi_step_plan_count=multi_step_plans,
            multi_hop_goal_count=sum(1 for goal in goals if self._looks_like_multihop_goal(goal)),
            auto_goal_count=sum(1 for event in events if event.get("type") == "auto_goal"),
            curriculum_goal_count=sum(1 for event in events if event.get("type") == "curriculum_goal"),
            position_count=len(positions),
            unique_position_count=len(unique_positions),
            path_distance=round(path_distance, 2),
            x_span=round(x_span, 2),
            y_span=round(y_span, 2),
            z_span=round(z_span, 2),
            visual_observation_count=visual_observations,
            raw_screenshot_count=len(deduped_screenshots),
            screenshot_count=len(screenshot_status["verified"]),
            missing_screenshot_count=len(screenshot_status["missing"]),
            invalid_screenshot_count=len(screenshot_status["invalid"]),
            hostile_encounter_count=hostile_encounters,
            danger_event_count=danger_events,
            unique_block_types=sorted(block_types),
            unique_entity_types=sorted(entity_types),
            unique_resource_types=sorted(resource_types),
            action_failure_categories=failure_categories,
            ready_for_exploration_review=ready,
        )

    def _world_model_trace_case(
        self,
        source_log: str,
        events: list[dict],
        cell_size: float,
        limit: int,
    ) -> WorldModelTraceCase:
        observations = [
            event.get("data", {})
            for event in events
            if event.get("type") == "observation" and isinstance(event.get("data", {}), dict)
        ]
        cell_states = {}
        position_cells = []

        for index, observation in enumerate(observations):
            position = self._position_tuple(observation.get("position"))
            if position is None:
                continue
            cell = self._world_model_cell(position, cell_size)
            position_cells.append(cell)
            state = self._world_model_cell_state(cell_states, cell)
            state["visit_count"] += 1
            state["first_seen_index"] = min(state["first_seen_index"], index)
            state["last_seen_index"] = max(state["last_seen_index"], index)

            for item in self._world_model_items(observation, ["nearby_blocks", "blocks", "visible_blocks"]):
                self._world_model_add_item(cell_states, item, cell, cell_size, "blocks")
            for item in self._world_model_items(observation, ["grounded_resources", "visual_resources", "resources"]):
                self._world_model_add_item(cell_states, item, cell, cell_size, "resources")
            for item in self._entity_items_from_record(observation):
                self._world_model_add_item(cell_states, item, cell, cell_size, "entities", default_key="type")
                if self._is_hostile_entity(item):
                    self._world_model_cell_state(cell_states, self._world_model_item_cell(item, cell, cell_size))["danger_count"] += 1
            for item in observation.get("dangers", []) if isinstance(observation.get("dangers", []), list) else []:
                self._world_model_add_item(cell_states, item, cell, cell_size, "entities", default_key="type")
                self._world_model_cell_state(cell_states, self._world_model_item_cell(item, cell, cell_size))["danger_count"] += 1

        transitions = self._world_model_transitions(position_cells)
        cells = self._world_model_serialized_cells(cell_states, cell_size, limit)
        frontier_candidates = self._world_model_frontiers(cell_states, position_cells[-1] if position_cells else None, cell_size)
        resource_hotspots = self._world_model_resource_hotspots(cell_states, cell_size)
        suggestions = self._world_model_suggested_goals(frontier_candidates, resource_hotspots, limit)
        ready = bool(position_cells and (len(set(position_cells)) > 1 or frontier_candidates or resource_hotspots))

        return WorldModelTraceCase(
            source_log=source_log,
            cell_size=cell_size,
            observation_count=len(observations),
            position_count=len(position_cells),
            unique_cell_count=len(cell_states),
            transition_count=len(transitions),
            frontier_count=len(frontier_candidates),
            resource_hotspot_count=len(resource_hotspots),
            danger_cell_count=sum(1 for state in cell_states.values() if state["danger_count"] > 0),
            ready_for_world_model_review=ready,
            cells=cells,
            transitions=transitions[:limit],
            frontiers=frontier_candidates[:limit],
            resource_hotspots=resource_hotspots[:limit],
            suggested_exploration_goals=suggestions[:limit],
        )

    def _plan_action_compliance_case(
        self,
        source_log: str,
        events: list[dict],
        limit: int = 12,
    ) -> PlanActionComplianceCase:
        plan_indices = [
            index
            for index, event in enumerate(events)
            if event.get("type") == "plan" and isinstance(event.get("data", {}), dict)
        ]
        action_events = [
            event
            for event in events
            if event.get("type") == "action" and isinstance(event.get("data", {}), dict)
        ]

        planned_action_types = {}
        executed_action_types = {}
        mismatch_examples = []
        planned_action_count = 0
        ordered_match_count = 0
        unordered_match_count = 0
        missing_planned_action_count = 0
        unplanned_action_count = 0
        order_violation_count = 0
        empty_plan_count = 0
        blocked_plan_count = 0

        def inc(counts: dict, key: str, amount: int = 1):
            counts[key] = counts.get(key, 0) + amount

        for plan_number, plan_index in enumerate(plan_indices):
            plan = events[plan_index].get("data", {})
            next_plan_index = plan_indices[plan_number + 1] if plan_number + 1 < len(plan_indices) else len(events)
            window_actions = [
                self._action_from_action_event(event)
                for event in events[plan_index + 1:next_plan_index]
                if event.get("type") == "action" and isinstance(event.get("data", {}), dict)
            ]
            window_actions = [action for action in window_actions if isinstance(action, dict) and action]

            plan_actions = plan.get("actions", [])
            if not isinstance(plan_actions, list):
                plan_actions = []
            plan_actions = [action for action in plan_actions if isinstance(action, dict)]
            status = str(plan.get("status") or "").lower()
            if status == "blocked":
                blocked_plan_count += 1
            if not plan_actions:
                empty_plan_count += 1

            planned_signatures = [self._plan_action_signature(action) for action in plan_actions]
            actual_signatures = [self._plan_action_signature(action) for action in window_actions]
            for signature in planned_signatures:
                inc(planned_action_types, self._plan_action_type(signature))
            for signature in actual_signatures:
                inc(executed_action_types, self._plan_action_type(signature))

            planned_action_count += len(planned_signatures)
            ordered_matches = self._ordered_signature_match_count(planned_signatures, actual_signatures)
            unordered_matches = self._unordered_signature_match_count(planned_signatures, actual_signatures)
            missing = self._signature_multiset_difference(planned_signatures, actual_signatures)
            unplanned = self._signature_multiset_difference(actual_signatures, planned_signatures)
            order_violations = max(0, unordered_matches - ordered_matches)

            ordered_match_count += ordered_matches
            unordered_match_count += unordered_matches
            missing_planned_action_count += len(missing)
            unplanned_action_count += len(unplanned)
            order_violation_count += order_violations

            if len(mismatch_examples) < limit and (missing or unplanned or order_violations or not plan_actions):
                mismatch_examples.append({
                    "plan_index": plan_number + 1,
                    "event_index": plan_index,
                    "status": plan.get("status", ""),
                    "reasoning": str(plan.get("reasoning", ""))[:180],
                    "planned": planned_signatures[:8],
                    "actual": actual_signatures[:8],
                    "missing": missing[:8],
                    "unplanned": unplanned[:8],
                    "ordered_matches": ordered_matches,
                    "order_violations": order_violations,
                })

        denominator = planned_action_count + unplanned_action_count + order_violation_count + empty_plan_count
        ready = bool(plan_indices and (planned_action_count or action_events or empty_plan_count or blocked_plan_count))
        return PlanActionComplianceCase(
            source_log=source_log,
            event_count=len(events),
            plan_count=len(plan_indices),
            action_count=len(action_events),
            planned_action_count=planned_action_count,
            ordered_match_count=ordered_match_count,
            unordered_match_count=unordered_match_count,
            missing_planned_action_count=missing_planned_action_count,
            unplanned_action_count=unplanned_action_count,
            order_violation_count=order_violation_count,
            empty_plan_count=empty_plan_count,
            blocked_plan_count=blocked_plan_count,
            plan_follow_score=round(ordered_match_count / planned_action_count, 3) if planned_action_count else 0.0,
            action_precision=round(unordered_match_count / len(action_events), 3) if action_events else 0.0,
            compliance_score=round(ordered_match_count / denominator, 3) if denominator else 0.0,
            planned_action_type_counts=planned_action_types,
            executed_action_type_counts=executed_action_types,
            mismatch_examples=mismatch_examples,
            ready_for_plan_action_review=ready,
        )

    def _action_from_action_event(self, event: dict) -> dict:
        data = event.get("data", {}) if isinstance(event.get("data", {}), dict) else {}
        action = data.get("action", {}) if isinstance(data.get("action", {}), dict) else {}
        if action:
            return action
        if data.get("type"):
            return data
        return {}

    def _plan_action_signature(self, action: dict) -> str:
        action_type = str(action.get("type") or action.get("action_type") or "unknown").strip() or "unknown"
        params = action.get("parameters", {}) if isinstance(action.get("parameters", {}), dict) else {}
        semantic_keys = ("item", "block", "entity", "target", "name")
        for key in semantic_keys:
            value = params.get(key, action.get(key))
            if value not in (None, ""):
                return f"{action_type}:{value}"
        return action_type

    def _plan_action_type(self, signature: str) -> str:
        return str(signature).split(":", 1)[0] or "unknown"

    def _ordered_signature_match_count(self, planned: list[str], actual: list[str]) -> int:
        matches = 0
        cursor = 0
        for signature in planned:
            for index in range(cursor, len(actual)):
                if actual[index] == signature:
                    matches += 1
                    cursor = index + 1
                    break
        return matches

    def _unordered_signature_match_count(self, planned: list[str], actual: list[str]) -> int:
        planned_counts = {}
        actual_counts = {}
        for signature in planned:
            planned_counts[signature] = planned_counts.get(signature, 0) + 1
        for signature in actual:
            actual_counts[signature] = actual_counts.get(signature, 0) + 1
        return sum(min(planned_counts.get(signature, 0), actual_counts.get(signature, 0)) for signature in planned_counts)

    def _signature_multiset_difference(self, left: list[str], right: list[str]) -> list[str]:
        right_counts = {}
        for signature in right:
            right_counts[signature] = right_counts.get(signature, 0) + 1
        difference = []
        for signature in left:
            if right_counts.get(signature, 0):
                right_counts[signature] -= 1
            else:
                difference.append(signature)
        return difference

    def _terminal_commitment_case(
        self,
        source_log: str,
        goal: str,
        goal_index: int,
        events: list[dict],
    ) -> TerminalCommitmentCase:
        observation = self._final_goal_observation(events)
        recent_actions = self._recent_goal_actions(events)
        terminal_record = self._terminal_goal_end_record(events)
        terminal_reported_complete = self._event_success(terminal_record) is True
        verification = self._terminal_world_verification(goal, events, observation, recent_actions)
        world_complete = verification["world_complete"]
        outcome = self._terminal_commitment_outcome(world_complete, terminal_reported_complete)
        action_count = sum(1 for event in events if event.get("type") == "action")
        observation_count = sum(1 for event in events if event.get("type") == "observation")
        verification_event_count = sum(1 for event in events if event.get("type") == "goal_verification")
        planner_complete_count = sum(
            1
            for event in events
            if event.get("type") == "plan"
            and isinstance(event.get("data", {}), dict)
            and str(event.get("data", {}).get("status") or "").lower() == "complete"
        )
        return TerminalCommitmentCase(
            source_log=source_log,
            goal=goal,
            goal_index=goal_index,
            event_count=len(events),
            observation_count=observation_count,
            action_count=action_count,
            verification_event_count=verification_event_count,
            planner_complete_count=planner_complete_count,
            terminal_reported_complete=terminal_reported_complete,
            world_complete=world_complete,
            world_status=verification["world_status"],
            terminal_status="reported_complete" if terminal_reported_complete else "not_reported_complete",
            outcome=outcome,
            verification_source=verification["source"],
            evidence=verification["evidence"],
            missing=verification["missing"],
            reason=verification["reason"],
            ready_for_terminal_review=bool(terminal_record or verification_event_count or observation),
        )

    def _terminal_world_verification(
        self,
        goal: str,
        events: list[dict],
        observation: dict,
        recent_actions: list[dict],
    ) -> dict:
        logged = self._latest_goal_verification_event(events)
        if logged is not None:
            status = str(logged.get("status") or "").lower()
            achieved = logged.get("achieved")
            if achieved is True or status == "achieved":
                return {
                    "world_complete": True,
                    "world_status": status or "achieved",
                    "source": "logged_goal_verification",
                    "evidence": list(logged.get("evidence", []) or []),
                    "missing": list(logged.get("missing", []) or []),
                    "reason": str(logged.get("reason") or logged.get("critic", {}).get("reason", "")),
                }
            if achieved is False or status in {"failed", "rejected"}:
                return {
                    "world_complete": False,
                    "world_status": status or "failed",
                    "source": "logged_goal_verification",
                    "evidence": list(logged.get("evidence", []) or []),
                    "missing": list(logged.get("missing", []) or []),
                    "reason": str(logged.get("reason") or logged.get("critic", {}).get("reason", "")),
                }
        if observation:
            try:
                from singularity.core.goal_verifier import GoalVerifier

                verification = GoalVerifier().verify(goal, observation, recent_actions=recent_actions).to_dict()
                status = str(verification.get("status") or "").lower()
                achieved = verification.get("achieved")
                world_complete = True if achieved is True or status == "achieved" else False if achieved is False or status in {"failed", "rejected"} else None
                return {
                    "world_complete": world_complete,
                    "world_status": status or "unknown",
                    "source": "deterministic_replay",
                    "evidence": list(verification.get("evidence", []) or []),
                    "missing": list(verification.get("missing", []) or []),
                    "reason": str(verification.get("critic", {}).get("reason", "")),
                }
            except Exception as e:
                return {
                    "world_complete": None,
                    "world_status": "error",
                    "source": "deterministic_replay_error",
                    "evidence": [],
                    "missing": [],
                    "reason": str(e),
                }
        return {
            "world_complete": None,
            "world_status": "unknown",
            "source": "none",
            "evidence": [],
            "missing": [],
            "reason": "missing terminal observation and goal verification",
        }

    def _latest_goal_verification_event(self, events: list[dict]) -> Optional[dict]:
        for event in reversed(events):
            if event.get("type") == "goal_verification" and isinstance(event.get("data", {}), dict):
                return event["data"]
        return None

    def _terminal_goal_end_record(self, events: list[dict]) -> dict:
        for event in reversed(events):
            if event.get("type") == "goal_end" and isinstance(event.get("data", {}), dict):
                data = event["data"]
                result = data.get("result", {}) if isinstance(data.get("result", {}), dict) else {}
                return result or data
        return {}

    def _terminal_commitment_outcome(self, world_complete: Optional[bool], terminal_reported_complete: bool) -> str:
        if world_complete is True and terminal_reported_complete:
            return "verified_success"
        if world_complete is False and terminal_reported_complete:
            return "unsupported_commitment"
        if world_complete is True and not terminal_reported_complete:
            return "post_attainment_drift"
        if world_complete is False and not terminal_reported_complete:
            return "missed_execution"
        return "unknown"

    def _action_verification_trace_case(
        self,
        source_log: str,
        events: list[dict],
        limit: int = 12,
    ) -> ActionVerificationTraceCase:
        from singularity.action.verifier import ActionVerifier

        verifier = ActionVerifier()
        latest_observation = {}
        current_goal = ""
        status_counts = {}
        action_type_counts = {}
        rejection_reasons = {}
        review_reasons = {}
        examples = []
        action_count = 0
        verified = 0
        accepted = 0
        review = 0
        rejected = 0
        rejected_success = 0
        failed_without_reject = 0
        observation_count = 0

        def inc(counts: dict, key: str, amount: int = 1):
            counts[key] = counts.get(key, 0) + amount

        for index, event in enumerate(events):
            event_type = str(event.get("type") or "")
            data = event.get("data", {}) if isinstance(event.get("data", {}), dict) else {}
            if event_type == "goal_start":
                current_goal = str(data.get("goal") or current_goal)
            elif event_type == "observation":
                latest_observation = data
                observation_count += 1
            elif event_type == "action":
                action_count += 1
                action = data.get("action", {}) if isinstance(data.get("action", {}), dict) else {}
                result = data.get("result", {}) if isinstance(data.get("result", {}), dict) else {}
                decision = verifier.verify(action, latest_observation, goal=current_goal).as_dict()
                verified += 1
                status = str(decision.get("status") or "unknown")
                action_type = str(decision.get("action_type") or action.get("type") or "unknown")
                inc(status_counts, status)
                inc(action_type_counts, action_type)
                if status == "accept":
                    accepted += 1
                elif status == "review":
                    review += 1
                    inc(review_reasons, str(decision.get("reason") or "review"))
                elif status == "reject":
                    rejected += 1
                    inc(rejection_reasons, str(decision.get("reason") or "reject"))
                    if self._event_success(result) is True:
                        rejected_success += 1
                if self._event_success(result) is False and status != "reject":
                    failed_without_reject += 1
                if len(examples) < limit and (status != "accept" or self._event_success(result) is False):
                    examples.append({
                        "event_index": index,
                        "goal": current_goal,
                        "action": action,
                        "result_success": self._event_success(result),
                        "verification": decision,
                    })

        return ActionVerificationTraceCase(
            source_log=source_log,
            event_count=len(events),
            observation_count=observation_count,
            action_count=action_count,
            verified_action_count=verified,
            accepted_action_count=accepted,
            review_action_count=review,
            rejected_action_count=rejected,
            rejected_success_count=rejected_success,
            failed_without_reject_count=failed_without_reject,
            status_counts=status_counts,
            action_type_counts=action_type_counts,
            rejection_reasons=rejection_reasons,
            review_reasons=review_reasons,
            examples=examples,
            ready_for_action_verification_review=bool(verified),
        )

    def _action_candidate_selection_trace_case(
        self,
        source_log: str,
        events: list[dict],
        limit: int = 12,
    ) -> ActionCandidateSelectionTraceCase:
        from singularity.action.selection import ActionCandidateSelector

        selector = ActionCandidateSelector()
        latest_observation = {}
        current_goal = ""
        observation_count = 0
        action_count = 0
        candidate_action_count = 0
        original_reject = 0
        changed = 0
        repaired_reject = 0
        unchanged_reject = 0
        selected_accept = 0
        selected_review = 0
        selected_reject = 0
        selected_types = {}
        repair_reasons = {}
        examples = []

        def inc(counts: dict, key: str, amount: int = 1):
            counts[key] = counts.get(key, 0) + amount

        for index, event in enumerate(events):
            event_type = str(event.get("type") or "")
            data = event.get("data", {}) if isinstance(event.get("data", {}), dict) else {}
            if event_type == "goal_start":
                current_goal = str(data.get("goal") or current_goal)
            elif event_type == "observation":
                latest_observation = data
                observation_count += 1
            elif event_type == "action":
                action = data.get("action", {}) if isinstance(data.get("action", {}), dict) else {}
                selection = selector.select(action, latest_observation, goal=current_goal).as_dict()
                action_count += 1
                candidate_action_count += int(selection.get("candidate_count") or 0)

                original_verification = selection.get("original_verification", {}) if isinstance(selection.get("original_verification", {}), dict) else {}
                selected_verification = selection.get("selected_verification", {}) if isinstance(selection.get("selected_verification", {}), dict) else {}
                original_status = str(original_verification.get("status") or "unknown")
                selected_status = str(selected_verification.get("status") or "unknown")
                selected_action = selection.get("selected_action", {}) if isinstance(selection.get("selected_action", {}), dict) else {}
                selected_type = str(selected_action.get("type") or selected_verification.get("action_type") or "unknown")
                inc(selected_types, selected_type)

                if original_status == "reject":
                    original_reject += 1
                    if selection.get("changed") and selected_status != "reject":
                        repaired_reject += 1
                    else:
                        unchanged_reject += 1
                if selection.get("changed"):
                    changed += 1
                    candidates = selection.get("candidates", []) if isinstance(selection.get("candidates", []), list) else []
                    selected_index = int(selection.get("selected_index") or 0)
                    candidate = candidates[selected_index] if 0 <= selected_index < len(candidates) else {}
                    if isinstance(candidate, dict):
                        inc(repair_reasons, str(candidate.get("reason") or selection.get("reason") or "changed"))
                if selected_status == "accept":
                    selected_accept += 1
                elif selected_status == "review":
                    selected_review += 1
                elif selected_status == "reject":
                    selected_reject += 1
                if len(examples) < limit and (selection.get("changed") or original_status == "reject"):
                    examples.append({
                        "event_index": index,
                        "goal": current_goal,
                        "original_action": selection.get("original_action", action),
                        "selected_action": selected_action,
                        "original_status": original_status,
                        "selected_status": selected_status,
                        "reason": selection.get("reason", ""),
                        "candidates": selection.get("candidates", []),
                    })

        return ActionCandidateSelectionTraceCase(
            source_log=source_log,
            event_count=len(events),
            observation_count=observation_count,
            action_count=action_count,
            candidate_action_count=candidate_action_count,
            original_reject_count=original_reject,
            changed_selection_count=changed,
            repaired_reject_count=repaired_reject,
            unchanged_reject_count=unchanged_reject,
            selected_accept_count=selected_accept,
            selected_review_count=selected_review,
            selected_reject_count=selected_reject,
            selected_action_type_counts=selected_types,
            repair_reasons=repair_reasons,
            examples=examples,
            ready_for_action_candidate_review=bool(action_count),
        )

    def _action_value_trace_case(
        self,
        source_log: str,
        events: list[dict],
        limit: int = 20,
    ) -> ActionValueTraceCase:
        from singularity.action.value import ActionValueProfile, action_signature

        profile = ActionValueProfile()
        current_goal = ""
        goal_count = 0
        action_count = 0
        success_count = 0
        failure_count = 0
        unknown_count = 0
        failure_pairs = []
        pending_failure = None
        pending_transitions = []
        latest_observation = None
        latest_observation_index = -1
        state_transition_items = []

        for index, event in enumerate(events):
            event_type = str(event.get("type") or "")
            data = event.get("data", {}) if isinstance(event.get("data", {}), dict) else {}
            if event_type == "observation":
                if pending_transitions:
                    shared_after = len(pending_transitions) > 1
                    for pending in pending_transitions:
                        state_transition_items.append(self._action_state_transition_item(
                            source_log=source_log,
                            event_index=pending["event_index"],
                            before_observation_index=pending.get("before_observation_index", -1),
                            after_observation_index=index,
                            observation_gap=index - pending["event_index"],
                            goal=pending.get("goal", ""),
                            action=pending.get("action", {}),
                            result=pending.get("result", {}),
                            before_observation=pending.get("before_observation", {}),
                            after_observation=data,
                            shared_after_observation=shared_after,
                        ))
                    pending_transitions = []
                latest_observation = data
                latest_observation_index = index
            elif event_type == "goal_start":
                current_goal = str(data.get("goal") or current_goal)
                goal_count += 1
            elif event_type == "action":
                action = data.get("action", {}) if isinstance(data.get("action", {}), dict) else {}
                result = data.get("result", {}) if isinstance(data.get("result", {}), dict) else {}
                verification = result.get("action_verification", {}) if isinstance(result.get("action_verification", {}), dict) else {}
                profile.record(action, result, goal=current_goal, verification=verification)
                action_count += 1
                success = self._event_success(result)
                if success is True:
                    success_count += 1
                    if pending_failure and len(failure_pairs) < limit:
                        failure_pairs.append({
                            "failed_event_index": pending_failure["event_index"],
                            "recovery_event_index": index,
                            "source_log": source_log,
                            "goal": current_goal,
                            "failed_signature": pending_failure["signature"],
                            "recovery_signature": action_signature(action),
                            "failed_action": pending_failure["action"],
                            "recovery_action": action,
                            "failed_error": pending_failure.get("error", ""),
                        })
                    pending_failure = None
                elif success is False:
                    failure_count += 1
                    pending_failure = {
                        "event_index": index,
                        "signature": action_signature(action),
                        "action": action,
                        "error": str(result.get("error") or result.get("reason") or ""),
                    }
                else:
                    unknown_count += 1
                before_observation = (
                    self._action_embedded_observation(data, result, before=True)
                    or latest_observation
                    or {}
                )
                after_observation = self._action_embedded_observation(data, result, before=False)
                if before_observation and after_observation:
                    state_transition_items.append(self._action_state_transition_item(
                        source_log=source_log,
                        event_index=index,
                        before_observation_index=latest_observation_index if latest_observation_index >= 0 else index,
                        after_observation_index=index,
                        observation_gap=0,
                        goal=current_goal,
                        action=action,
                        result=result,
                        before_observation=before_observation,
                        after_observation=after_observation,
                        shared_after_observation=False,
                    ))
                elif before_observation:
                    pending_transitions.append({
                        "event_index": index,
                        "before_observation_index": latest_observation_index,
                        "goal": current_goal,
                        "action": action,
                        "result": result,
                        "before_observation": before_observation,
                    })

        feedback = profile.as_feedback(limit=1000)
        high_value = profile.high_value_items()
        low_value = profile.low_value_items()
        positive_transitions = sum(
            1 for item in state_transition_items if item.get("transition_label") == "positive"
        )
        negative_transitions = sum(
            1 for item in state_transition_items if item.get("transition_label") == "negative"
        )
        no_progress_transitions = sum(
            1 for item in state_transition_items if item.get("transition_label") == "no_progress"
        )
        low_confidence_transitions = sum(
            1 for item in state_transition_items if self._safe_float(item.get("transition_confidence"), 1.0) < 0.75
        )
        return ActionValueTraceCase(
            source_log=source_log,
            event_count=len(events),
            goal_count=goal_count,
            action_count=action_count,
            success_count=success_count,
            failure_count=failure_count,
            unknown_outcome_count=unknown_count,
            signature_count=feedback["signature_count"],
            high_value_count=len(high_value),
            low_value_count=len(low_value),
            action_value_items=feedback["action_value_items"],
            high_value_items=high_value[:limit],
            low_value_items=low_value[:limit],
            failure_correction_pairs=failure_pairs,
            state_transition_count=len(state_transition_items),
            positive_transition_count=positive_transitions,
            negative_transition_count=negative_transitions,
            no_progress_transition_count=no_progress_transitions,
            low_confidence_transition_count=low_confidence_transitions,
            state_transition_items=state_transition_items[:200],
            ready_for_action_value_review=bool(action_count),
        )

    def _aggregate_action_value_items(self, report: ActionValueTraceReport) -> list[dict]:
        from singularity.action.value import ActionValueStats

        aggregate = {}
        for case in report.cases:
            for item in case.action_value_items:
                signature = str(item.get("signature") or "")
                if not signature:
                    continue
                stats = aggregate.get(signature)
                if stats is None:
                    stats = ActionValueStats(signature=signature, action_type=str(item.get("action_type") or "unknown"))
                    aggregate[signature] = stats
                stats.attempts += self._small_int(item.get("attempts", 0))
                stats.successes += self._small_int(item.get("successes", 0))
                stats.failures += self._small_int(item.get("failures", 0))
                stats.unknown_outcomes += self._small_int(item.get("unknown_outcomes", 0))
                stats.verifier_rejects += self._small_int(item.get("verifier_rejects", 0))
                stats.verifier_reviews += self._small_int(item.get("verifier_reviews", 0))
                stats.verifier_accepts += self._small_int(item.get("verifier_accepts", 0))
                families = item.get("task_families", {}) if isinstance(item.get("task_families", {}), dict) else {}
                for family, count in families.items():
                    stats.task_families[str(family)] = stats.task_families.get(str(family), 0) + self._small_int(count)
        items = [stats.as_dict() for stats in aggregate.values()]
        return sorted(items, key=lambda item: (-item["attempts"], item["signature"]))

    def _aggregate_action_state_transition_items(self, report: ActionValueTraceReport) -> list[dict]:
        aggregate = {}
        for case in report.cases:
            for item in case.state_transition_items:
                signature = str(item.get("signature") or "")
                if not signature:
                    continue
                record = aggregate.get(signature)
                if record is None:
                    record = {
                        "signature": signature,
                        "action_type": str(item.get("action_type") or "unknown"),
                        "attempts": 0,
                        "successes": 0,
                        "failures": 0,
                        "positive_transitions": 0,
                        "negative_transitions": 0,
                        "no_progress_transitions": 0,
                        "state_value_delta_sum": 0.0,
                        "transition_value_score_sum": 0.0,
                        "movement_distance_sum": 0.0,
                        "transition_confidence_sum": 0.0,
                        "low_confidence_transitions": 0,
                        "inventory_gain_count": 0,
                        "inventory_loss_count": 0,
                        "new_resource_count": 0,
                        "source_logs": set(),
                        "examples": [],
                    }
                    aggregate[signature] = record
                record["attempts"] += 1
                if item.get("success") is True:
                    record["successes"] += 1
                elif item.get("success") is False:
                    record["failures"] += 1
                label = str(item.get("transition_label") or "")
                if label == "positive":
                    record["positive_transitions"] += 1
                elif label == "negative":
                    record["negative_transitions"] += 1
                else:
                    record["no_progress_transitions"] += 1
                record["state_value_delta_sum"] += self._safe_float(item.get("state_value_delta"), 0.0)
                record["transition_value_score_sum"] += self._safe_float(item.get("transition_value_score"), 0.5)
                record["movement_distance_sum"] += self._safe_float(item.get("movement_distance"), 0.0)
                confidence = self._safe_float(item.get("transition_confidence"), 1.0)
                record["transition_confidence_sum"] += confidence
                if confidence < 0.75:
                    record["low_confidence_transitions"] += 1
                record["inventory_gain_count"] += len(item.get("gained_items", []) if isinstance(item.get("gained_items", []), list) else [])
                record["inventory_loss_count"] += len(item.get("lost_items", []) if isinstance(item.get("lost_items", []), list) else [])
                record["new_resource_count"] += len(item.get("new_resources", []) if isinstance(item.get("new_resources", []), list) else [])
                source = str(item.get("source_log") or "")
                if source:
                    record["source_logs"].add(source)
                if len(record["examples"]) < 3:
                    record["examples"].append(item)

        items = []
        for record in aggregate.values():
            attempts = max(1, record["attempts"])
            items.append({
                "signature": record["signature"],
                "action_type": record["action_type"],
                "attempts": record["attempts"],
                "successes": record["successes"],
                "failures": record["failures"],
                "positive_transitions": record["positive_transitions"],
                "negative_transitions": record["negative_transitions"],
                "no_progress_transitions": record["no_progress_transitions"],
                "positive_transition_rate": round(record["positive_transitions"] / attempts, 3),
                "negative_transition_rate": round(record["negative_transitions"] / attempts, 3),
                "no_progress_transition_rate": round(record["no_progress_transitions"] / attempts, 3),
                "avg_state_value_delta": round(record["state_value_delta_sum"] / attempts, 3),
                "avg_transition_value_score": round(record["transition_value_score_sum"] / attempts, 3),
                "avg_movement_distance": round(record["movement_distance_sum"] / attempts, 3),
                "avg_transition_confidence": round(record["transition_confidence_sum"] / attempts, 3),
                "low_confidence_transitions": record["low_confidence_transitions"],
                "inventory_gain_count": record["inventory_gain_count"],
                "inventory_loss_count": record["inventory_loss_count"],
                "new_resource_count": record["new_resource_count"],
                "source_logs": sorted(record["source_logs"])[:8],
                "examples": record["examples"],
            })
        return sorted(items, key=lambda item: (-item["attempts"], item["signature"]))

    def _knowledge_correction_case_from_action_value(
        self,
        case: ActionValueTraceCase,
        min_failure_repeats: int = 2,
        max_failure_value_score: float = 0.35,
    ) -> KnowledgeCorrectionTraceCase:
        temp_report = ActionValueTraceReport(cases=[case])
        action_items = self._aggregate_action_value_items(temp_report)
        transition_items = self._aggregate_action_state_transition_items(temp_report)
        failure_action_memories = self._knowledge_failure_action_memories(
            case.source_log,
            action_items,
            transition_items,
            min_failure_repeats=min_failure_repeats,
            max_failure_value_score=max_failure_value_score,
        )
        dependency_corrections = self._knowledge_dependency_corrections(case)
        repeated_failure_signatures = sum(
            1
            for item in action_items
            if self._gate_int(item.get("failures", 0)) >= int(min_failure_repeats)
        )
        ready = bool(failure_action_memories or dependency_corrections)
        return KnowledgeCorrectionTraceCase(
            source_log=case.source_log,
            event_count=case.event_count,
            goal_count=case.goal_count,
            action_count=case.action_count,
            failure_action_count=case.failure_count,
            repeated_failure_signature_count=repeated_failure_signatures,
            recovery_pair_count=len(case.failure_correction_pairs),
            dependency_correction_count=len(dependency_corrections),
            failure_action_memory_count=len(failure_action_memories),
            low_confidence_transition_count=case.low_confidence_transition_count,
            dependency_corrections=dependency_corrections,
            failure_action_memories=failure_action_memories,
            ready_for_knowledge_correction_review=ready,
        )

    def _knowledge_failure_action_memories(
        self,
        source_log: str,
        action_items: list[dict],
        transition_items: list[dict],
        min_failure_repeats: int = 2,
        max_failure_value_score: float = 0.35,
    ) -> list[dict]:
        transition_by_signature = {
            str(item.get("signature") or ""): item
            for item in transition_items
            if item.get("signature")
        }
        memories = []
        for item in action_items:
            signature = str(item.get("signature") or "")
            if not signature:
                continue
            attempts = self._gate_int(item.get("attempts", 0))
            failures = self._gate_int(item.get("failures", 0))
            value_score = self._safe_float(item.get("value_score"), 0.5)
            transition = transition_by_signature.get(signature, {})
            no_progress = self._gate_int(transition.get("no_progress_transitions", 0))
            negative = self._gate_int(transition.get("negative_transitions", 0))
            failure_evidence = failures >= int(min_failure_repeats) and value_score <= float(max_failure_value_score)
            stagnation_evidence = (negative + no_progress) >= int(min_failure_repeats) and (
                self._safe_float(transition.get("avg_state_value_delta"), 0.0) <= 0.0
            )
            if not (failure_evidence or stagnation_evidence):
                continue
            reasons = []
            if failure_evidence:
                reasons.append("repeated_failed_action")
            if negative:
                reasons.append("negative_state_transition")
            if no_progress:
                reasons.append("no_progress_state_transition")
            memories.append({
                "type": "failed_action_memory",
                "source_log": source_log,
                "signature": signature,
                "action_type": str(item.get("action_type") or signature.split(":", 1)[0] or "unknown"),
                "attempts": attempts,
                "failures": failures,
                "successes": self._gate_int(item.get("successes", 0)),
                "failure_rate": item.get("failure_rate", 0.0),
                "value_score": value_score,
                "negative_transitions": negative,
                "no_progress_transitions": no_progress,
                "avg_state_value_delta": transition.get("avg_state_value_delta", 0.0),
                "task_families": dict(item.get("task_families", {})) if isinstance(item.get("task_families", {}), dict) else {},
                "recommendation": "avoid_or_replan_until_preconditions_change",
                "reason": ", ".join(reasons),
                "knowledge_dimensions": self._knowledge_transfer_dimensions(
                    signature=signature,
                    goal="",
                    action=item,
                    role="failed_action_memory",
                ),
            })
        return sorted(memories, key=lambda item: (-item["failures"], item["signature"]))[:20]

    def _knowledge_dependency_corrections(self, case: ActionValueTraceCase) -> list[dict]:
        grouped = {}
        for pair in case.failure_correction_pairs:
            if not isinstance(pair, dict):
                continue
            failed_signature = str(pair.get("failed_signature") or "")
            recovery_signature = str(pair.get("recovery_signature") or "")
            if not failed_signature or not recovery_signature:
                continue
            key = (failed_signature, recovery_signature)
            record = grouped.setdefault(key, {
                "type": "dependency_correction",
                "source_logs": set(),
                "goal": str(pair.get("goal") or ""),
                "failed_signature": failed_signature,
                "recovery_signature": recovery_signature,
                "failed_action": pair.get("failed_action", {}) if isinstance(pair.get("failed_action", {}), dict) else {},
                "recovery_action": pair.get("recovery_action", {}) if isinstance(pair.get("recovery_action", {}), dict) else {},
                "failed_errors": set(),
                "evidence_count": 0,
                "examples": [],
            })
            source = str(pair.get("source_log") or case.source_log or "")
            if source:
                record["source_logs"].add(source)
            error = str(pair.get("failed_error") or "").strip()
            if error:
                record["failed_errors"].add(error[:160])
            record["evidence_count"] += 1
            if len(record["examples"]) < 3:
                record["examples"].append({
                    "failed_event_index": pair.get("failed_event_index"),
                    "recovery_event_index": pair.get("recovery_event_index"),
                    "failed_error": error[:160],
                })

        corrections = []
        for record in grouped.values():
            failed_action = record["failed_action"]
            recovery_action = record["recovery_action"]
            correction = self._knowledge_dependency_text(
                record["failed_signature"],
                record["recovery_signature"],
                failed_action,
                recovery_action,
                record["goal"],
            )
            corrections.append({
                "type": "dependency_correction",
                "source_logs": sorted(record["source_logs"])[:8],
                "goal": record["goal"],
                "failed_signature": record["failed_signature"],
                "recovery_signature": record["recovery_signature"],
                "failed_action": failed_action,
                "recovery_action": recovery_action,
                "target_items": self._knowledge_goal_targets(record["goal"], failed_action),
                "prerequisite_actions": [recovery_action] if recovery_action else [],
                "failed_errors": sorted(record["failed_errors"])[:5],
                "evidence_count": record["evidence_count"],
                "confidence": round(min(0.95, 0.45 + 0.2 * record["evidence_count"]), 3),
                "recommendation": "add_reviewed_prerequisite_or_ordering_edge",
                "correction": correction,
                "knowledge_dimensions": self._knowledge_transfer_dimensions(
                    signature=record["failed_signature"],
                    goal=record["goal"],
                    action=failed_action,
                    recovery_action=recovery_action,
                    role="dependency_correction",
                ),
                "examples": record["examples"],
            })
        return sorted(corrections, key=lambda item: (-item["evidence_count"], item["failed_signature"]))[:20]

    def _knowledge_dependency_text(
        self,
        failed_signature: str,
        recovery_signature: str,
        failed_action: dict,
        recovery_action: dict,
        goal: str,
    ) -> str:
        failed_subject = self._knowledge_action_subject(failed_action) or failed_signature
        recovery_subject = self._knowledge_action_subject(recovery_action) or recovery_signature
        recovery_type = str(recovery_action.get("type") or recovery_signature.split(":", 1)[0] or "action")
        if failed_signature.startswith("craft:") and recovery_signature.startswith("dig:"):
            return f"Before retrying {failed_signature}, collect or expose {recovery_subject} with {recovery_type} when the goal is {goal or failed_subject}."
        if failed_signature.startswith("craft:") and recovery_signature.startswith("craft:"):
            return f"Before retrying {failed_signature}, craft prerequisite {recovery_subject} first."
        return f"Before replaying {failed_signature}, prefer recovery step {recovery_signature} when the same failure context appears."

    def _knowledge_goal_targets(self, goal: str, failed_action: dict = None) -> list[str]:
        failed_action = failed_action if isinstance(failed_action, dict) else {}
        targets = set()
        params = failed_action.get("parameters", {}) if isinstance(failed_action.get("parameters", {}), dict) else {}
        for key in ("item", "block", "target", "entity"):
            value = str(params.get(key) or "").strip().lower()
            if value:
                targets.add(value)
        text = str(goal or "").lower().replace("_", " ")
        try:
            from singularity.data.knowledge_base import KnowledgeBase
            kb = KnowledgeBase()
            known_items = set(kb.list_recipes()) | set(getattr(kb, "graph", None).nodes if getattr(kb, "graph", None) else set())
        except Exception:
            known_items = set()
        for item in known_items:
            normalized = str(item or "").lower()
            spaced = normalized.replace("_", " ")
            parts = [part for part in spaced.split() if part]
            if spaced and spaced in text:
                targets.add(normalized)
            elif parts and all(part in text for part in parts):
                targets.add(normalized)
        return sorted(targets)[:8]

    def _knowledge_action_subject(self, action: dict) -> str:
        action = action if isinstance(action, dict) else {}
        params = action.get("parameters", {}) if isinstance(action.get("parameters", {}), dict) else {}
        for key in ("item", "block", "target", "entity", "name"):
            value = str(params.get(key) or "").strip().lower()
            if value:
                return value
        return ""

    def _knowledge_transfer_dimensions(
        self,
        signature: str,
        goal: str,
        action: dict,
        recovery_action: Optional[dict] = None,
        role: str = "",
    ) -> dict:
        action = action if isinstance(action, dict) else {}
        recovery_action = recovery_action if isinstance(recovery_action, dict) else {}
        subject = self._knowledge_action_subject(action) or signature.split(":", 1)[-1]
        recovery_subject = self._knowledge_action_subject(recovery_action)
        action_type = str(action.get("type") or signature.split(":", 1)[0] or "unknown")
        recovery_type = str(recovery_action.get("type") or "")
        return {
            "structure": [item for item in (subject, recovery_subject) if item and item != "-"][:4],
            "attribute": [self._knowledge_task_family(goal, action), action_type],
            "process": [item for item in (action_type, recovery_type) if item],
            "function": [role or "knowledge_correction", f"goal:{self._short_text(goal, 80)}" if goal else ""],
            "interaction": [f"{recovery_type or 'review'}_before_{action_type}"] if role == "dependency_correction" else ["avoid_repeated_replay"],
        }

    def _knowledge_task_family(self, goal: str, action: dict = None) -> str:
        try:
            from singularity.core.skill_library import SkillLibrary
            return SkillLibrary(persist=False).infer_task_family(goal, action or {})
        except Exception:
            return "general"

    def _action_value_transition_gate_check(self, source: str, payload: dict, thresholds: dict) -> dict:
        if not isinstance(payload, dict):
            return self._gate_check(source, "action_value_transition_gate", "fail", "payload is not a JSON object", {})
        feedback = payload.get("action_value_feedback", payload)
        if not isinstance(feedback, dict):
            return self._gate_check(source, "action_value_transition_gate", "fail", "missing action_value_feedback object", {})
        items = feedback.get("state_transition_value_items", [])
        if not isinstance(items, list):
            items = []
        state_transition_count = self._gate_int(
            feedback.get("state_transition_count", payload.get("state_transition_count", len(items)))
        )
        low_confidence_count = self._gate_int(
            feedback.get("low_confidence_transition_count", payload.get("low_confidence_transition_count", 0))
        )
        trusted_items = []
        review_items = []
        trusted_transition_count = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            attempts = max(0, self._gate_int(item.get("attempts")))
            confidence = self._gate_float_or_none(item.get("avg_transition_confidence"))
            confidence = 0.0 if confidence is None else confidence
            low_confidence = max(0, self._gate_int(item.get("low_confidence_transitions")))
            low_rate = round(low_confidence / max(1, attempts), 3)
            record = {
                "signature": str(item.get("signature") or "unknown"),
                "attempts": attempts,
                "avg_transition_confidence": round(confidence, 3),
                "low_confidence_rate": low_rate,
                "avg_transition_value_score": item.get("avg_transition_value_score"),
            }
            if attempts <= 0:
                record["reason"] = "no_transition_attempts"
                review_items.append(record)
                continue
            if confidence < float(thresholds.get("min_transition_confidence", 0.75)):
                record["reason"] = "low_transition_confidence"
                review_items.append(record)
                continue
            if low_rate > float(thresholds.get("max_item_low_confidence_rate", 0.25)):
                record["reason"] = "too_many_low_confidence_windows"
                review_items.append(record)
                continue
            if item.get("avg_transition_value_score") is None:
                record["reason"] = "missing_transition_value_score"
                review_items.append(record)
                continue
            trusted_transition_count += attempts
            trusted_items.append(record)

        low_confidence_rate = round(low_confidence_count / max(1, state_transition_count), 3) if state_transition_count else 0.0
        metrics = {
            "state_transition_count": state_transition_count,
            "low_confidence_transition_count": low_confidence_count,
            "low_confidence_rate": low_confidence_rate,
            "trusted_item_count": len(trusted_items),
            "trusted_transition_count": trusted_transition_count,
            "review_item_count": len(review_items),
            "trusted_items": trusted_items[:8],
            "review_items": review_items[:8],
        }
        if state_transition_count <= 0:
            return self._gate_check(source, "action_value_transition_gate", "warn", "no transition-value evidence found", metrics)
        if low_confidence_rate > float(thresholds.get("max_low_confidence_rate", 0.25)):
            return self._gate_check(source, "action_value_transition_gate", "warn", "overall low-confidence transition rate is too high", metrics)
        if len(trusted_items) < int(thresholds.get("min_trusted_items", 1)):
            return self._gate_check(source, "action_value_transition_gate", "warn", "not enough trusted transition-value items", metrics)
        if trusted_transition_count < int(thresholds.get("min_trusted_transitions", 1)):
            return self._gate_check(source, "action_value_transition_gate", "warn", "not enough trusted transition attempts", metrics)
        return self._gate_check(source, "action_value_transition_gate", "pass", "trusted transition-value evidence is available", metrics)

    def _action_value_transition_evaluator_sources(
        self,
        action_value_reports: list[dict] = None,
        action_value_report_paths: list[str] = None,
        session_log_paths: list[str] = None,
    ) -> tuple[list[tuple[str, dict]], list[str]]:
        sources = []
        errors = []
        for index, payload in enumerate(action_value_reports or []):
            if isinstance(payload, ActionValueTraceReport):
                sources.append((f"inline_report:{index}", {"cases": [asdict(case) for case in payload.cases], "errors": payload.errors}))
            elif isinstance(payload, dict):
                sources.append((f"inline:{index}", payload))
            else:
                errors.append(f"inline:{index}: unsupported action-value report payload")
        for path in action_value_report_paths or []:
            if not path:
                continue
            try:
                with open(path, "r", encoding="utf-8-sig") as f:
                    sources.append((path, json.load(f)))
            except Exception as e:
                errors.append(f"{path}: {e}")
        if session_log_paths:
            try:
                report = self.run_action_value_report_from_logs(session_log_paths)
                sources.append(("session_logs", {"cases": [asdict(case) for case in report.cases], "errors": report.errors}))
            except Exception as e:
                errors.append(f"session_logs: {e}")
        return sources, errors

    def _action_value_transition_items_from_payload(self, source: str, payload: dict) -> list[dict]:
        if not isinstance(payload, dict):
            return []
        items = []
        seen = set()
        cases = payload.get("cases", []) if isinstance(payload.get("cases", []), list) else []
        for case in cases:
            if not isinstance(case, dict):
                continue
            for item in case.get("state_transition_items", []) if isinstance(case.get("state_transition_items", []), list) else []:
                if isinstance(item, dict):
                    self._append_transition_evaluator_item(items, seen, source, item)
        if items:
            return items

        feedback = payload.get("action_value_feedback", payload)
        if not isinstance(feedback, dict):
            return []
        aggregate_items = feedback.get("state_transition_value_items", [])
        if not isinstance(aggregate_items, list):
            return []
        for aggregate in aggregate_items:
            if not isinstance(aggregate, dict):
                continue
            examples = aggregate.get("examples", []) if isinstance(aggregate.get("examples", []), list) else []
            for item in examples:
                if isinstance(item, dict):
                    self._append_transition_evaluator_item(items, seen, source, item)
        return items

    def _append_transition_evaluator_item(self, items: list[dict], seen: set, source: str, item: dict):
        record = dict(item)
        if not record.get("source_log"):
            record["source_log"] = source
        key = (
            str(record.get("source_log") or source),
            self._gate_int(record.get("event_index")),
            str(record.get("signature") or ""),
            str(record.get("transition_label") or ""),
        )
        if key in seen:
            return
        seen.add(key)
        items.append(record)

    def _transition_evaluator_skip_reason(self, item: dict, min_transition_confidence: float) -> str:
        confidence = self._safe_float(item.get("transition_confidence"), 0.0)
        if confidence < float(min_transition_confidence):
            return "low_deterministic_transition_confidence"
        if not item.get("before_state_summary") or not item.get("after_state_summary"):
            return "missing_state_summary"
        if not self._normalize_transition_label(item.get("transition_label")):
            return "missing_deterministic_label"
        return ""

    def _transition_evaluator_skip_record(self, item: dict, reason: str) -> dict:
        return {
            "source_log": item.get("source_log", ""),
            "event_index": item.get("event_index"),
            "signature": item.get("signature", "unknown"),
            "reason": reason,
            "transition_confidence": item.get("transition_confidence"),
            "deterministic_label": item.get("transition_label"),
        }

    def _evaluate_action_value_transition_with_llm(self, evaluator, item: dict) -> dict:
        prompt_payload = {
            "goal": item.get("goal", ""),
            "action": item.get("action", {}),
            "success": item.get("success"),
            "before_state": item.get("before_state_summary", {}),
            "after_state": item.get("after_state_summary", {}),
            "deterministic_delta_summary": {
                "inventory_delta": item.get("inventory_delta", {}),
                "movement_distance": item.get("movement_distance", 0),
                "health_delta": item.get("health_delta", 0),
                "new_blocks": item.get("new_blocks", []),
                "new_resources": item.get("new_resources", []),
                "hostile_delta": item.get("hostile_delta", 0),
                "deterministic_reasons": item.get("reasons", []),
            },
        }
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a state-grounded Minecraft transition evaluator. "
                    "Score whether an action moved the world state toward the stated goal. "
                    "Use only the provided before/after state summaries and deltas. "
                    "Return strict JSON."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Choose exactly one label from positive, negative, no_progress. "
                    "Use score 0.0-1.0 where 0.5 is no useful change, higher is progress, lower is regression. "
                    "Return JSON with keys label, score, confidence, reason.\n"
                    + json.dumps(prompt_payload, ensure_ascii=False, default=str)
                ),
            },
        ]
        try:
            text = evaluator.chat(messages, response_format={"type": "json_object"})
            payload = self._parse_transition_evaluator_json(text)
            label = self._normalize_transition_label(payload.get("label"))
            if not label:
                return {"error": "missing_or_invalid_label", "raw": text[:240]}
            return {
                "label": label,
                "score": max(0.0, min(1.0, self._safe_float(payload.get("score"), 0.5))),
                "confidence": max(0.0, min(1.0, self._safe_float(payload.get("confidence"), 0.0))),
                "reason": str(payload.get("reason") or "")[:240],
            }
        except Exception as e:
            return {"error": str(e)}

    def _parse_transition_evaluator_json(self, text: str) -> dict:
        text = str(text or "").strip()
        try:
            payload = json.loads(text)
            return payload if isinstance(payload, dict) else {}
        except Exception:
            start = text.find("{")
            end = text.rfind("}")
            if 0 <= start < end:
                payload = json.loads(text[start:end + 1])
                return payload if isinstance(payload, dict) else {}
            raise

    def _normalize_transition_label(self, label) -> str:
        text = str(label or "").strip().lower().replace("-", "_").replace(" ", "_")
        mapping = {
            "progress": "positive",
            "helpful": "positive",
            "improvement": "positive",
            "positive": "positive",
            "regression": "negative",
            "harmful": "negative",
            "worse": "negative",
            "negative": "negative",
            "neutral": "no_progress",
            "none": "no_progress",
            "unchanged": "no_progress",
            "no_change": "no_progress",
            "no_progress": "no_progress",
        }
        return mapping.get(text, "")

    def _action_embedded_observation(self, action_data: dict, result: dict, before: bool) -> dict:
        key_groups = (
            ("before_observation", "pre_observation", "observation_before", "state_before", "world_state_before", "before")
            if before else
            ("after_observation", "post_observation", "observation_after", "state_after", "world_state_after", "after")
        )
        containers = [action_data, result]
        for container in (action_data, result):
            if isinstance(container, dict):
                for nested_key in ("evidence", "metadata", "trace", "observation"):
                    nested = container.get(nested_key)
                    if isinstance(nested, dict):
                        containers.append(nested)
        for container in containers:
            if not isinstance(container, dict):
                continue
            for key in key_groups:
                value = container.get(key)
                if isinstance(value, dict) and self._observation_like(value):
                    return value
            inventory_key = "before_inventory" if before else "after_inventory"
            inventory = container.get(inventory_key)
            if isinstance(inventory, dict):
                return {"inventory": inventory}
        return {}

    def _observation_like(self, record: dict) -> bool:
        if not isinstance(record, dict):
            return False
        return any(
            key in record
            for key in (
                "inventory",
                "position",
                "health",
                "nearby_blocks",
                "blocks",
                "visible_blocks",
                "grounded_resources",
                "visual_resources",
                "resources",
                "nearby_entities",
                "entities",
                "dangers",
            )
        )

    def _compact_transition_observation_summary(self, observation: dict) -> dict:
        observation = observation if isinstance(observation, dict) else {}
        inventory = self._inventory_counts(observation.get("inventory", {}))
        position = self._position_tuple(observation.get("position"))
        summary = {
            "position": (
                {"x": round(position[0], 2), "y": round(position[1], 2), "z": round(position[2], 2)}
                if position is not None else {}
            ),
            "health": self._safe_float(observation.get("health"), 20.0),
            "hunger": self._safe_float(observation.get("hunger"), self._safe_float(observation.get("food"), 20.0)),
            "inventory": {
                key: inventory[key]
                for key in sorted(inventory)[:12]
                if abs(inventory.get(key, 0.0)) > 0.0001
            },
            "visible_blocks": sorted(self._named_items_from_record(observation, ["nearby_blocks", "blocks", "visible_blocks"]))[:12],
            "resources": sorted(self._named_items_from_record(observation, ["grounded_resources", "visual_resources", "resources"]))[:12],
            "entities": sorted({
                str(entity.get("name") or entity.get("type") or "")
                for entity in self._entity_items_from_record(observation)
                if isinstance(entity, dict) and (entity.get("name") or entity.get("type"))
            })[:12],
            "danger_count": len(observation.get("dangers", []) if isinstance(observation.get("dangers", []), list) else []),
        }
        return summary

    def _action_state_transition_item(
        self,
        source_log: str,
        event_index: int,
        before_observation_index: int,
        after_observation_index: int,
        observation_gap: int,
        goal: str,
        action: dict,
        result: dict,
        before_observation: dict,
        after_observation: dict,
        shared_after_observation: bool = False,
    ) -> dict:
        from singularity.action.value import action_signature, task_family_from_goal

        action = action if isinstance(action, dict) else {}
        result = result if isinstance(result, dict) else {}
        before_observation = before_observation if isinstance(before_observation, dict) else {}
        after_observation = after_observation if isinstance(after_observation, dict) else {}
        signature = action_signature(action)
        action_type = str(action.get("type") or result.get("action_type") or "unknown").strip() or "unknown"
        before_inventory = self._inventory_counts(before_observation.get("inventory", {}))
        after_inventory = self._inventory_counts(after_observation.get("inventory", {}))
        inventory_delta = {}
        gained_items = []
        lost_items = []
        for item in sorted(set(before_inventory) | set(after_inventory)):
            delta = after_inventory.get(item, 0.0) - before_inventory.get(item, 0.0)
            if abs(delta) <= 0.0001:
                continue
            inventory_delta[item] = round(delta, 3)
            if delta > 0:
                gained_items.append(item)
            else:
                lost_items.append(item)

        before_position = self._position_tuple(before_observation.get("position"))
        after_position = self._position_tuple(after_observation.get("position"))
        movement_distance = (
            self._path_distance([before_position, after_position])
            if before_position is not None and after_position is not None else 0.0
        )
        before_health = self._safe_float(before_observation.get("health"), 20.0)
        after_health = self._safe_float(after_observation.get("health"), before_health)
        health_delta = after_health - before_health

        before_blocks = self._named_items_from_record(before_observation, ["nearby_blocks", "blocks", "visible_blocks"])
        after_blocks = self._named_items_from_record(after_observation, ["nearby_blocks", "blocks", "visible_blocks"])
        before_resources = self._named_items_from_record(before_observation, ["grounded_resources", "visual_resources", "resources"])
        after_resources = self._named_items_from_record(after_observation, ["grounded_resources", "visual_resources", "resources"])
        new_blocks = sorted(after_blocks - before_blocks)
        new_resources = sorted(after_resources - before_resources)

        before_hostiles = len([entity for entity in self._entity_items_from_record(before_observation) if self._is_hostile_entity(entity)])
        after_hostiles = len([entity for entity in self._entity_items_from_record(after_observation) if self._is_hostile_entity(entity)])
        hostile_delta = after_hostiles - before_hostiles

        before_state_value = self._absolute_progress_score(before_observation)
        after_state_value = self._absolute_progress_score(after_observation)
        absolute_state_delta = after_state_value - before_state_value
        state_value_delta = absolute_state_delta
        if movement_distance > 0.75:
            state_value_delta += min(0.25, movement_distance / 32.0)
        if new_resources:
            state_value_delta += min(0.25, len(new_resources) * 0.08)
        if new_blocks and action_type in {"look_at", "move_to", "walk_to", "wait"}:
            state_value_delta += min(0.15, len(new_blocks) * 0.04)
        if hostile_delta > 0:
            state_value_delta -= min(0.3, hostile_delta * 0.1)
        success = self._event_success(result)
        if success is False:
            state_value_delta -= 0.15
        transition_confidence = 1.0
        if shared_after_observation:
            transition_confidence = min(transition_confidence, 0.5)
        if observation_gap > 2:
            transition_confidence = min(transition_confidence, 0.75)
        if observation_gap > 6:
            transition_confidence = min(transition_confidence, 0.5)
        if before_observation_index < 0 or after_observation_index < 0:
            transition_confidence = min(transition_confidence, 0.75)
        state_value_delta *= transition_confidence

        inventory_changed = bool(inventory_delta)
        visible_changed = bool(new_blocks or new_resources)
        health_changed = abs(health_delta) > 0.01
        moved = movement_distance > 0.25
        if state_value_delta > 0.05:
            transition_label = "positive"
        elif state_value_delta < -0.05:
            transition_label = "negative"
        elif not any((inventory_changed, visible_changed, health_changed, moved)):
            transition_label = "no_progress"
        else:
            transition_label = "no_progress"

        reasons = []
        if gained_items:
            reasons.append(f"inventory_gain:{','.join(gained_items[:4])}")
        if lost_items:
            reasons.append(f"inventory_loss:{','.join(lost_items[:4])}")
        if movement_distance > 0.75:
            reasons.append(f"movement:{movement_distance:.1f}")
        if new_resources:
            reasons.append(f"resource_discovery:{','.join(new_resources[:4])}")
        if health_delta < -0.01:
            reasons.append(f"health_loss:{abs(health_delta):.1f}")
        if hostile_delta > 0:
            reasons.append(f"new_hostiles:{hostile_delta}")
        if success is False:
            reasons.append("action_failed")
        if shared_after_observation:
            reasons.append("shared_observation_window")
        if observation_gap > 2:
            reasons.append(f"wide_observation_gap:{observation_gap}")
        if not reasons:
            reasons.append("no_observed_state_delta")

        return {
            "source_log": source_log,
            "event_index": event_index,
            "before_observation_index": before_observation_index,
            "after_observation_index": after_observation_index,
            "observation_gap": observation_gap,
            "shared_after_observation": bool(shared_after_observation),
            "goal": str(goal or ""),
            "task_family": task_family_from_goal(goal),
            "signature": signature,
            "action_type": action_type,
            "action": action,
            "success": success,
            "before_state_value": round(before_state_value, 3),
            "after_state_value": round(after_state_value, 3),
            "before_state_summary": self._compact_transition_observation_summary(before_observation),
            "after_state_summary": self._compact_transition_observation_summary(after_observation),
            "absolute_state_delta": round(absolute_state_delta, 3),
            "state_value_delta": round(state_value_delta, 3),
            "transition_value_score": round(max(0.0, min(1.0, 0.5 + state_value_delta / 2.0)), 3),
            "transition_confidence": round(transition_confidence, 3),
            "transition_label": transition_label,
            "inventory_delta": inventory_delta,
            "gained_items": gained_items[:8],
            "lost_items": lost_items[:8],
            "movement_distance": round(movement_distance, 3),
            "health_delta": round(health_delta, 3),
            "new_blocks": new_blocks[:8],
            "new_resources": new_resources[:8],
            "hostile_delta": hostile_delta,
            "reasons": reasons[:8],
        }

    def _self_evolution_trace_case(self, source_log: str, events: list[dict]) -> SelfEvolutionTraceCase:
        observations = [
            event.get("data", {})
            for event in events
            if event.get("type") == "observation" and isinstance(event.get("data", {}), dict)
        ]
        action_events = [
            event.get("data", {})
            for event in events
            if event.get("type") == "action" and isinstance(event.get("data", {}), dict)
        ]
        plan_events = [
            event.get("data", {})
            for event in events
            if event.get("type") == "plan" and isinstance(event.get("data", {}), dict)
        ]
        blocked_plan_events = sum(
            1
            for event in events
            if str(event.get("type") or "").lower() == "blocked_plan"
        )
        empty_plan_events = sum(
            1
            for event in events
            if str(event.get("type") or "").lower() == "empty_plan"
        )
        blocked_plan_count = max(
            blocked_plan_events,
            sum(1 for plan in plan_events if str(plan.get("status") or "").lower() == "blocked"),
        )
        empty_plan_count = max(
            empty_plan_events,
            sum(
                1
                for plan in plan_events
                if not isinstance(plan.get("actions", []), list) or not plan.get("actions", [])
            ),
        )
        goal_segments = self._session_goal_segments(events)

        typed_feedback = {}
        action_types = {}
        failure_categories = {}
        progress_markers = []
        remedy_candidates = []
        adaptor_recommendations = []
        progress_signals = 0
        regression_signals = 0
        stagnation_signals = 0
        inventory_gains = 0
        inventory_losses = 0
        consecutive_no_movement = 0
        repeated_failures = 0
        no_progress_successes = 0
        repeated_success_loops = 0
        relative_reward = 0.0

        def inc(counts: dict, key: str, amount: int = 1):
            counts[key] = counts.get(key, 0) + amount

        positions = [
            self._position_tuple(observation.get("position"))
            for observation in observations
        ]
        inventories = [self._inventory_counts(observation.get("inventory", {})) for observation in observations]
        absolute_scores = [self._absolute_progress_score(observation) for observation in observations]
        success_progress_audit = self._successful_action_progress_audit(events)

        no_move_run = 0
        for index in range(1, len(observations)):
            previous_position = positions[index - 1]
            current_position = positions[index]
            if previous_position is not None and current_position is not None:
                movement = self._path_distance([previous_position, current_position])
                if movement > 0.75:
                    progress_signals += 1
                    relative_reward += min(1.0, movement / 8.0)
                    no_move_run = 0
                    inc(typed_feedback, "monitor_state_change")
                    progress_markers.append(f"moved:{movement:.1f}")
                else:
                    no_move_run += 1
                    if no_move_run >= 2:
                        stagnation_signals += 1
                        consecutive_no_movement += 1
                        inc(typed_feedback, "monitor_stagnation")

            previous_inventory = inventories[index - 1]
            current_inventory = inventories[index]
            for item in sorted(set(previous_inventory) | set(current_inventory)):
                delta = current_inventory.get(item, 0.0) - previous_inventory.get(item, 0.0)
                if delta > 0:
                    progress_signals += 1
                    inventory_gains += 1
                    relative_reward += min(1.0, delta / 8.0)
                    inc(typed_feedback, "monitor_inventory_gain")
                    progress_markers.append(f"gained:{item}+{self._format_delta(delta)}")
                elif delta < 0:
                    regression_signals += 1
                    inventory_losses += 1
                    relative_reward -= min(1.0, abs(delta) / 8.0)
                    inc(typed_feedback, "monitor_inventory_loss")

            previous_health = self._safe_float(observations[index - 1].get("health"), 20.0)
            current_health = self._safe_float(observations[index].get("health"), previous_health)
            if current_health < previous_health:
                regression_signals += 1
                relative_reward -= min(1.0, (previous_health - current_health) / 10.0)
                inc(typed_feedback, "monitor_state_regression")

        failed_signatures = {}
        successful_actions = 0
        failed_actions = 0
        for action_index, action_data in enumerate(action_events):
            action = action_data.get("action", {}) if isinstance(action_data.get("action", {}), dict) else {}
            result = action_data.get("result", {}) if isinstance(action_data.get("result", {}), dict) else {}
            action_type = str(action.get("type") or result.get("action_type") or "unknown").strip() or "unknown"
            inc(action_types, action_type)
            success = self._event_success({"result": result})
            if success is True:
                successful_actions += 1
                inc(typed_feedback, "monitor_action_success")
                audit = success_progress_audit[action_index] if action_index < len(success_progress_audit) else {}
                if audit.get("no_progress"):
                    no_progress_successes += 1
                    stagnation_signals += 1
                    relative_reward -= 0.1 if action_type == "wait" else 0.2
                    inc(typed_feedback, "monitor_no_progress_success")
                    progress_markers.append(f"no_progress_success:{action_type}")
                    if audit.get("repeated_success_loop"):
                        repeated_success_loops += 1
                        inc(typed_feedback, "monitor_repeated_success_loop")
                    if no_progress_successes == 1:
                        adaptor_recommendations.append(
                            "Require a state, inventory, or verifier delta before treating successful actions as progress."
                        )
                else:
                    progress_signals += 1
                    relative_reward += 0.5
                    progress_markers.append(f"action_success:{action_type}")
            elif success is False:
                failed_actions += 1
                regression_signals += 1
                relative_reward -= 0.75
                inc(typed_feedback, "monitor_action_failure")
                category = self._action_failure_category(action, result)
                inc(failure_categories, category)
                signature = self._action_failure_signature(action, category)
                failed_signatures[signature] = failed_signatures.get(signature, 0) + 1
                if failed_signatures[signature] > 1:
                    repeated_failures += 1
                    stagnation_signals += 1
                    inc(typed_feedback, "monitor_stagnation")
                remedy = self._self_evolution_remedy_candidate(action_type, category, action, result)
                if remedy:
                    remedy_candidates.append(remedy)
                recommendation = self._self_evolution_adaptor_recommendation(action_type, category)
                if recommendation:
                    adaptor_recommendations.append(recommendation)

        completed_goals = 0
        failed_goals = 0
        for event in events:
            event_type = str(event.get("type") or "").lower()
            data = event.get("data", {}) if isinstance(event.get("data", {}), dict) else {}
            if event_type in {"stagnation", "runtime_stagnation", "no_progress", "execution_stalled"}:
                stagnation_signals += 1
                inc(typed_feedback, "monitor_stagnation")
                adaptor_recommendations.append("Switch to adaptor repair when the runtime emits no-progress signals.")
            elif event_type == "goal_end":
                result = data.get("result", {}) if isinstance(data.get("result", {}), dict) else {}
                completed = result.get("completed", result.get("success"))
                if completed is True:
                    completed_goals += 1
                    progress_signals += 2
                    relative_reward += 2.0
                    inc(typed_feedback, "monitor_goal_success")
                elif completed is False:
                    failed_goals += 1
                    regression_signals += 2
                    relative_reward -= 1.5
                    inc(typed_feedback, "monitor_goal_failure")
            elif event_type == "goal_verification":
                achieved = data.get("achieved")
                status = str(data.get("status") or "").lower()
                if achieved is True or status == "achieved":
                    progress_signals += 1
                    relative_reward += 1.0
                    inc(typed_feedback, "monitor_verification_success")
                elif achieved is False or status in {"failed", "rejected"}:
                    regression_signals += 1
                    relative_reward -= 1.0
                    inc(typed_feedback, "monitor_verification_failure")
                    adaptor_recommendations.append("Repair the unfinished plan suffix before retrying a verifier-rejected goal.")

        zero_action_failure = int(
            not action_events
            and failed_goals > 0
            and bool(blocked_plan_count or empty_plan_count)
        )
        if zero_action_failure:
            inc(typed_feedback, "monitor_blocked_plan_loop", max(1, blocked_plan_count or empty_plan_count))
            adaptor_recommendations.append(
                "Use rule/prerequisite fallback or curriculum subgoal when a blocked plan has no executable actions."
            )

        if stagnation_signals:
            adaptor_recommendations.append("Use accumulated typed feedback to rewrite only the unfinished plan suffix.")
        if regression_signals > progress_signals:
            adaptor_recommendations.append("Route the next retry through a conservative adaptor before adding new goals.")

        ready = bool(
            observations
            and (
                progress_signals
                or regression_signals
                or stagnation_signals
                or action_events
            )
        )
        return SelfEvolutionTraceCase(
            source_log=source_log,
            event_count=len(events),
            observation_count=len(observations),
            goal_count=len(goal_segments),
            completed_goal_count=completed_goals,
            failed_goal_count=failed_goals,
            action_count=len(action_events),
            successful_action_count=successful_actions,
            failed_action_count=failed_actions,
            progress_signal_count=progress_signals,
            regression_signal_count=regression_signals,
            stagnation_signal_count=stagnation_signals,
            inventory_gain_count=inventory_gains,
            inventory_loss_count=inventory_losses,
            repeated_failure_count=repeated_failures,
            no_progress_success_count=no_progress_successes,
            repeated_success_loop_count=repeated_success_loops,
            blocked_plan_count=blocked_plan_count,
            empty_plan_count=empty_plan_count,
            zero_action_failure_count=zero_action_failure,
            consecutive_no_movement_count=consecutive_no_movement,
            relative_reward_delta=round(relative_reward, 3),
            absolute_reward_mean=round(sum(absolute_scores) / len(absolute_scores), 3) if absolute_scores else 0.0,
            typed_feedback_counts=typed_feedback,
            action_type_counts=action_types,
            action_failure_categories=failure_categories,
            progress_markers=self._dedupe_strings(progress_markers)[:20],
            remedy_candidates=self._dedupe_strings(remedy_candidates)[:20],
            adaptor_recommendations=self._dedupe_strings(adaptor_recommendations)[:20],
            ready_for_self_evolution_review=ready,
        )

    def _discovery_application_trace_case(self, source_log: str, events: list[dict]) -> DiscoveryApplicationTraceCase:
        goal_segments = self._session_goal_segments(events)
        goal_end_events = [
            event for event in events
            if event.get("type") == "goal_end" and isinstance(event.get("data", {}), dict)
        ]
        action_events = [
            event.get("data", {})
            for event in events
            if event.get("type") == "action" and isinstance(event.get("data", {}), dict)
        ]
        memory_write_events = [
            event.get("data", {})
            for event in events
            if event.get("type") == "memory_write" and isinstance(event.get("data", {}), dict)
        ]

        hypothesis_count = 0
        experiment_count = 0
        consolidation_count = 0
        application_count = 0
        successful_applications = 0
        failed_applications = 0
        experiment_actions = 0
        failed_experiment_actions = 0
        causal_memory_writes = 0
        causal_rules = []
        knowledge_gaps = []
        application_goals = []

        for event in events:
            event_type = str(event.get("type") or "").lower()
            data = event.get("data", {}) if isinstance(event.get("data", {}), dict) else {}
            text = self._compact_event_text(data)
            if event_type in {"discovery_hypothesis", "hypothesis", "knowledge_gap"}:
                hypothesis_count += 1
                knowledge_gaps.extend(self._discovery_text_values(data, ["knowledge_gap", "gap", "question", "hypothesis", "goal"]))
            elif event_type in {"discovery_experiment", "experiment"}:
                experiment_count += 1
                if self._event_success(data) is False:
                    failed_experiment_actions += 1
            elif event_type in {"discovery_consolidation", "causal_rule", "knowledge_consolidation"}:
                consolidation_count += 1
                causal_rules.extend(self._discovery_text_values(data, ["rule", "causal_rule", "finding", "lesson", "content"]))
            elif event_type in {"discovery_application", "knowledge_application"}:
                application_count += 1
                application_goals.extend(self._discovery_text_values(data, ["goal", "task", "application"]))
                success = self._event_success(data)
                if success is True:
                    successful_applications += 1
                elif success is False:
                    failed_applications += 1

            if event_type in {"plan", "reflection"} and self._looks_like_discovery_hypothesis(text):
                hypothesis_count += 1
                knowledge_gaps.append(self._short_text(text))

        for action_data in action_events:
            action = action_data.get("action", {}) if isinstance(action_data.get("action", {}), dict) else {}
            result = action_data.get("result", {}) if isinstance(action_data.get("result", {}), dict) else {}
            action_text = self._compact_event_text({"action": action, "result": result})
            if self._looks_like_discovery_experiment(action_text):
                experiment_actions += 1
                if result.get("success") is False:
                    failed_experiment_actions += 1

        for memory_data in memory_write_events:
            memory_text = self._compact_event_text(memory_data)
            if self._looks_like_discovery_consolidation(memory_data, memory_text):
                consolidation_count += 1
                if self._looks_like_causal_memory_write(memory_data, memory_text):
                    causal_memory_writes += 1
                causal_rules.extend(self._discovery_text_values(memory_data, ["content", "summary", "rule", "causal_rule"]))

        completed_goals = 0
        failed_goals = 0
        for event in goal_end_events:
            data = event.get("data", {})
            result = data.get("result", {}) if isinstance(data.get("result", {}), dict) else {}
            goal = str(data.get("goal") or "")
            completed = result.get("completed", result.get("success"))
            if completed is True:
                completed_goals += 1
                if self._looks_like_discovery_application(goal):
                    application_count += 1
                    successful_applications += 1
                    application_goals.append(goal)
            elif completed is False:
                failed_goals += 1
                if self._looks_like_discovery_application(goal):
                    application_count += 1
                    failed_applications += 1
                    application_goals.append(goal)

        phase_counts = {
            "knowledge_gap_identification": hypothesis_count,
            "experimental_discovery": experiment_count + experiment_actions,
            "knowledge_consolidation": consolidation_count,
            "knowledge_application": application_count,
        }
        complete_loop_count = min(phase_counts.values()) if phase_counts else 0
        recommendations = self._discovery_application_recommendations(
            phase_counts,
            successful_applications,
            causal_memory_writes,
            failed_experiment_actions,
        )
        session_goal = self._session_goal(events)
        ready = bool(
            sum(phase_counts.values()) > 0
            or causal_memory_writes
            or self._looks_like_discovery_hypothesis(session_goal.lower())
            or self._looks_like_discovery_application(session_goal)
        )
        return DiscoveryApplicationTraceCase(
            source_log=source_log,
            event_count=len(events),
            goal_count=len(goal_segments),
            completed_goal_count=completed_goals,
            failed_goal_count=failed_goals,
            hypothesis_count=hypothesis_count,
            experiment_count=experiment_count,
            consolidation_count=consolidation_count,
            application_count=application_count,
            successful_application_count=successful_applications,
            failed_application_count=failed_applications,
            experiment_action_count=experiment_actions,
            failed_experiment_action_count=failed_experiment_actions,
            memory_write_count=len(memory_write_events),
            causal_memory_write_count=causal_memory_writes,
            discovery_loop_count=sum(1 for count in phase_counts.values() if count > 0),
            complete_loop_count=complete_loop_count,
            phase_counts=phase_counts,
            causal_rule_candidates=self._dedupe_strings(causal_rules)[:12],
            knowledge_gap_candidates=self._dedupe_strings(knowledge_gaps)[:12],
            application_goals=self._dedupe_strings(application_goals)[:12],
            recommendations=recommendations,
            ready_for_discovery_review=ready,
        )

    def _discovery_application_recommendations(
        self,
        phase_counts: dict,
        successful_applications: int,
        causal_memory_writes: int,
        failed_experiment_actions: int,
    ) -> list[str]:
        recommendations = []
        if phase_counts.get("knowledge_gap_identification", 0) <= 0:
            recommendations.append("record_explicit_knowledge_gap_or_hypothesis")
        if phase_counts.get("experimental_discovery", 0) <= 0:
            recommendations.append("run_small_controlled_minecraft_experiment")
        if phase_counts.get("knowledge_consolidation", 0) <= 0 or causal_memory_writes <= 0:
            recommendations.append("write_causal_rule_with_provenance_before_skill_promotion")
        if phase_counts.get("knowledge_application", 0) <= 0:
            recommendations.append("test_discovered_rule_on_held_out_application_goal")
        elif successful_applications <= 0:
            recommendations.append("repeat_application_until_discovered_rule_succeeds")
        if failed_experiment_actions > 0:
            recommendations.append("review_failed_experiment_actions_before_consolidation")
        return recommendations

    def _discovery_text_values(self, record: dict, keys: list[str]) -> list[str]:
        values = []
        for key in keys:
            value = record.get(key) if isinstance(record, dict) else None
            if isinstance(value, str) and value.strip():
                values.append(value.strip())
        return values

    def _small_int(self, value) -> int:
        try:
            return int(float(value or 0))
        except (TypeError, ValueError):
            return 0

    def _event_success(self, record: dict):
        if not isinstance(record, dict):
            return None
        for key in ("success", "completed", "passed", "ok", "achieved"):
            if isinstance(record.get(key), bool):
                return record.get(key)
        status = str(record.get("status") or record.get("state") or record.get("outcome") or "").strip().lower()
        if status in {"achieved", "complete", "completed", "done", "ok", "pass", "passed", "success", "succeeded"}:
            return True
        if status in {"aborted", "blocked", "error", "fail", "failed", "failure", "incomplete", "rejected"}:
            return False
        result = record.get("result")
        if isinstance(result, dict):
            return self._event_success(result)
        return None

    def _successful_action_progress_audit(self, events: list[dict]) -> list[dict]:
        audits = []
        pending = []
        latest_state = ""
        no_progress_signatures = {}
        for event in events:
            event_type = str(event.get("type") or "").lower()
            data = event.get("data", {}) if isinstance(event.get("data", {}), dict) else {}
            if event_type == "observation":
                current_state = self._progress_state_signature(data)
                for audit in pending:
                    audit["after_state"] = current_state
                    if audit.get("success") and audit.get("before_state") and current_state:
                        if audit["before_state"] == current_state:
                            audit["no_progress"] = True
                            signature = audit.get("action_signature", "")
                            if signature:
                                no_progress_signatures[signature] = no_progress_signatures.get(signature, 0) + 1
                                if no_progress_signatures[signature] > 1:
                                    audit["repeated_success_loop"] = True
                        else:
                            audit["progress_observed"] = True
                pending = []
                latest_state = current_state
            elif event_type == "action":
                action, result, action_type = self._normalized_action_record(data)
                audit = {
                    "success": self._event_success({"result": result}) is True,
                    "before_state": latest_state,
                    "after_state": "",
                    "no_progress": False,
                    "progress_observed": False,
                    "repeated_success_loop": False,
                    "action_signature": self._action_progress_signature(action, result, action_type),
                }
                audits.append(audit)
                if audit["success"]:
                    pending.append(audit)
        return audits

    def _progress_state_signature(self, observation: dict) -> str:
        if not isinstance(observation, dict):
            return ""
        signature = {
            "position": self._position_tuple(observation.get("position")),
            "inventory": self._inventory_counts(observation.get("inventory", {})),
            "health": self._safe_float(observation.get("health"), 20.0),
            "blocks": self._named_item_count_signature(observation, ["nearby_blocks", "blocks", "visible_blocks"]),
            "resources": self._named_item_count_signature(
                observation,
                ["grounded_resources", "visual_resources", "resources"],
            ),
            "entities": self._named_item_count_signature(observation, ["nearby_entities", "entities", "dangers"]),
        }
        return json.dumps(signature, sort_keys=True, separators=(",", ":"))

    def _named_item_count_signature(self, record: dict, keys: list[str]) -> dict:
        counts = {}
        for name in self._named_items_from_record(record, keys):
            normalized = str(name or "").strip().lower()
            if normalized:
                counts[normalized] = counts.get(normalized, 0) + 1
        return dict(sorted(counts.items()))

    def _action_progress_signature(self, action: dict, result: dict, action_type: str = "") -> str:
        action = action if isinstance(action, dict) else {}
        result = result if isinstance(result, dict) else {}
        action_type = str(action_type or action.get("type") or result.get("action_type") or "unknown").strip() or "unknown"
        params = action.get("parameters", {}) if isinstance(action.get("parameters", {}), dict) else {}
        target_parts = []
        for key in ("item", "block", "entity", "target", "resource", "x", "y", "z", "ms"):
            value = params.get(key)
            if value not in (None, "", [], {}):
                target_parts.append(f"{key}={value}")
        return f"{action_type}:{'|'.join(target_parts) if target_parts else '-'}"

    def _skill_memory_hint_type_from_text(self, hint) -> str:
        text = str(hint or "").strip()
        if not text:
            return "UNKNOWN"
        first = text.split(maxsplit=1)[0].strip().upper().rstrip(":")
        if first in {"REUSE", "AVOID", "REVIEW_ONLY"}:
            return first
        return "UNKNOWN"

    def _skill_memory_hint_record_from_text(self, hint, task_family: str = "") -> dict:
        text = str(hint or "").strip()
        hint_type = self._skill_memory_hint_type_from_text(text)
        rest = text.split(maxsplit=1)[1] if hint_type != "UNKNOWN" and len(text.split(maxsplit=1)) > 1 else text
        skill = rest.split(":", 1)[0].strip().split()[0] if rest.strip() else "unknown"
        if not skill or skill.upper() in {"REUSE", "AVOID", "REVIEW_ONLY"}:
            skill = "unknown"
        return {
            "hint_type": hint_type,
            "skill": skill,
            "task_family": str(task_family or "unspecified").strip().lower() or "unspecified",
            "hint": self._short_text(text, 180),
        }

    def _skill_memory_quality_labels(
        self,
        hint_type_counts: dict,
        post_hint_failed_actions: int,
        repeated_post_hint_failures: int,
        post_hint_goal_successes: int,
        post_hint_goal_failures: int,
    ) -> list[str]:
        labels = []
        if not hint_type_counts:
            labels.append("no_skill_memory_hints")
            return labels
        if post_hint_goal_successes <= 0 and post_hint_goal_failures <= 0:
            labels.append("missing_goal_outcome_after_hint")
        if hint_type_counts.get("REUSE", 0):
            if post_hint_goal_successes > 0 and repeated_post_hint_failures == 0:
                labels.append("reuse_supported_by_goal_success")
            if post_hint_goal_failures > 0 or repeated_post_hint_failures > 0:
                labels.append("reuse_conflicted_with_failures")
        if hint_type_counts.get("AVOID", 0):
            if post_hint_failed_actions <= 0 and post_hint_goal_successes > 0:
                labels.append("avoid_supported_no_post_hint_failures")
            if post_hint_failed_actions > 0:
                labels.append("avoid_unheeded_post_hint_failures")
        if hint_type_counts.get("REVIEW_ONLY", 0):
            labels.append("review_only_present_keep_gated")
        if hint_type_counts.get("UNKNOWN", 0):
            labels.append("unknown_skill_memory_hint_format")
        if post_hint_failed_actions > 0:
            labels.append("action_failures_after_hints")
        return labels

    def _skill_memory_quality_recommendations(self, labels: list[str]) -> list[str]:
        mapping = {
            "no_skill_memory_hints": "run_with_skill_memory_context_or_seed_skill_memories",
            "missing_goal_outcome_after_hint": "log_goal_verification_after_skill_memory_hints",
            "reuse_supported_by_goal_success": "confirm_reuse_hint_with_controlled_ablation",
            "reuse_conflicted_with_failures": "demote_or_review_reuse_hint_before_default_retrieval",
            "avoid_supported_no_post_hint_failures": "retain_avoid_hint_and_track_heldout_runs",
            "avoid_unheeded_post_hint_failures": "rewrite_avoid_hint_as_operational_constraint",
            "review_only_present_keep_gated": "keep_review_only_hint_out_of_default_promotion",
            "unknown_skill_memory_hint_format": "migrate_legacy_skill_memory_hints_to_typed_format",
            "action_failures_after_hints": "inspect_post_hint_failed_actions_for_interference",
        }
        return [mapping[label] for label in labels if label in mapping]

    def _skill_memory_quality_items(
        self,
        source_log: str,
        hint_records: list[dict],
        labels: list[str],
    ) -> list[dict]:
        if not hint_records:
            return []
        grouped = {}
        for record in hint_records:
            hint_type = record.get("hint_type", "UNKNOWN")
            item_labels = self._skill_memory_labels_for_hint_type(hint_type, labels)
            if not item_labels:
                continue
            key = (
                hint_type,
                record.get("skill", "unknown"),
                record.get("task_family", "unspecified"),
            )
            item = grouped.setdefault(key, {
                "hint_type": key[0],
                "skill": key[1],
                "task_family": key[2],
                "count": 0,
                "labels": {},
                "source_log": source_log,
                "examples": [],
            })
            item["count"] += 1
            for label in item_labels:
                item["labels"][label] = item["labels"].get(label, 0) + 1
            example = record.get("hint", "")
            if example and example not in item["examples"]:
                item["examples"].append(example)
        return sorted(grouped.values(), key=lambda item: (item["hint_type"], item["skill"], item["task_family"]))

    def _skill_memory_labels_for_hint_type(self, hint_type: str, labels: list[str]) -> list[str]:
        hint_type = str(hint_type or "").upper()
        if hint_type == "REUSE":
            allowed = {"reuse_supported_by_goal_success", "reuse_conflicted_with_failures"}
        elif hint_type == "AVOID":
            allowed = {"avoid_supported_no_post_hint_failures", "avoid_unheeded_post_hint_failures"}
        elif hint_type == "REVIEW_ONLY":
            allowed = {"review_only_present_keep_gated"}
        else:
            allowed = {"unknown_skill_memory_hint_format"}
        return [label for label in labels if label in allowed]

    def _compact_event_text(self, value) -> str:
        parts = []

        def collect(item):
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                for key, nested in item.items():
                    if isinstance(key, str):
                        parts.append(key)
                    collect(nested)
            elif isinstance(item, list):
                for nested in item:
                    collect(nested)

        collect(value)
        return " ".join(parts).lower()

    def _short_text(self, text: str, limit: int = 180) -> str:
        compact = " ".join(str(text or "").split())
        return compact[:limit]

    def _looks_like_discovery_hypothesis(self, text: str) -> bool:
        return any(token in text for token in ("hypothesis", "knowledge gap", "test whether", "if ", "whether", "why "))

    def _looks_like_discovery_experiment(self, text: str) -> bool:
        return any(token in text for token in ("experiment", "trial", "test", "probe", "redstone", "circuit", "lever", "lamp"))

    def _looks_like_discovery_consolidation(self, record: dict, text: str) -> bool:
        layer = str(record.get("layer", "")).lower() if isinstance(record, dict) else ""
        memory_type = str(record.get("memory_type", "")).lower() if isinstance(record, dict) else ""
        if layer in {"semantic", "causal"} or "causal" in memory_type or "rule" in memory_type:
            return True
        return any(token in text for token in ("causal rule", "lesson", "therefore", "because", "if ", "then "))

    def _looks_like_causal_memory_write(self, record: dict, text: str) -> bool:
        layer = str(record.get("layer", "")).lower() if isinstance(record, dict) else ""
        memory_type = str(record.get("memory_type", "")).lower() if isinstance(record, dict) else ""
        return layer == "causal" or "causal" in memory_type or any(token in text for token in ("causal rule", "because", "if ", "then "))

    def _looks_like_discovery_application(self, goal: str) -> bool:
        text = str(goal or "").lower()
        return any(token in text for token in ("apply", "application", "build", "construct", "redstone", "circuit", "lamp"))

    def _action_abstraction_trace_case(
        self,
        source_log: str,
        events: list[dict],
        mapper: ActionMapper,
    ) -> ActionAbstractionTraceCase:
        action_events = [
            event.get("data", {})
            for event in events
            if event.get("type") == "action" and isinstance(event.get("data", {}), dict)
        ]
        canonical_counts = {}
        result_backend_counts = {}
        result_backend_command_counts = {}
        mineflayer_counts = {}
        desktop_counts = {}
        lower_level_reasons = {}
        lower_level_action_types = {}
        recommendations = []
        failed_actions = 0
        unknown_canonical = 0
        failed_mappings = 0
        desktop_planned = 0
        low_level_candidates = 0

        current_goal = self._session_goal(events)
        for index, action_data in enumerate(action_events, start=1):
            action = action_data.get("action", {}) if isinstance(action_data.get("action", {}), dict) else {}
            result = action_data.get("result", {}) if isinstance(action_data.get("result", {}), dict) else {}
            action_type = str(action.get("type") or result.get("action_type") or "unknown")
            canonical_counts[action_type] = canonical_counts.get(action_type, 0) + 1

            if result.get("success") is False:
                failed_actions += 1
            backend = str(result.get("backend") or "unknown")
            backend_command = str(result.get("backend_command") or result.get("action_type") or action_type)
            result_backend_counts[backend] = result_backend_counts.get(backend, 0) + 1
            result_backend_command_counts[backend_command] = result_backend_command_counts.get(backend_command, 0) + 1

            mineflayer = mapper.map(action, "mineflayer")
            desktop = mapper.map(action, "desktop")
            mineflayer_counts[mineflayer.command] = mineflayer_counts.get(mineflayer.command, 0) + 1
            desktop_counts[desktop.command] = desktop_counts.get(desktop.command, 0) + 1
            if not mineflayer.executable:
                unknown_canonical += 1
                failed_mappings += 1
            if not desktop.executable:
                desktop_planned += 1
            reason = self._lower_level_control_reason(action, result, desktop)
            if reason:
                low_level_candidates += 1
                lower_level_reasons[reason] = lower_level_reasons.get(reason, 0) + 1
                lower_level_action_types[action_type] = lower_level_action_types.get(action_type, 0) + 1
                recommendations.append(self._action_abstraction_recommendation(index, current_goal, action_type, reason))

        return ActionAbstractionTraceCase(
            source_log=source_log,
            action_count=len(action_events),
            failed_action_count=failed_actions,
            unknown_canonical_count=unknown_canonical,
            failed_mapping_count=failed_mappings,
            desktop_planned_count=desktop_planned,
            low_level_candidate_count=low_level_candidates,
            canonical_action_types=canonical_counts,
            result_backend_counts=result_backend_counts,
            result_backend_command_counts=result_backend_command_counts,
            mineflayer_command_counts=mineflayer_counts,
            desktop_command_counts=desktop_counts,
            lower_level_reasons=lower_level_reasons,
            lower_level_action_types=lower_level_action_types,
            task_recommendations=recommendations[:12],
        )

    def _skill_memory_quality_trace_case(self, source_log: str, events: list[dict]) -> SkillMemoryQualityCase:
        hint_events = 0
        hint_count = 0
        hint_type_counts = {}
        task_family_counts = {}
        action_count = 0
        failed_action_count = 0
        post_hint_action_count = 0
        post_hint_failed_action_count = 0
        repeated_post_hint_failures = 0
        goal_count = 0
        completed_goal_count = 0
        failed_goal_count = 0
        post_hint_goal_success_count = 0
        post_hint_goal_failure_count = 0
        hint_seen = False
        last_post_hint_failure = ""
        hint_records = []

        for event in events:
            event_type = str(event.get("type") or "")
            data = event.get("data", {}) if isinstance(event.get("data", {}), dict) else {}
            if event_type == "skill_memory_hint":
                hint_events += 1
                hint_seen = True
                family = str(data.get("task_family") or "unspecified").strip().lower() or "unspecified"
                task_family_counts[family] = task_family_counts.get(family, 0) + 1
                raw_hints = data.get("hints", [])
                raw_hints = raw_hints if isinstance(raw_hints, list) else []
                if not raw_hints and data.get("hint"):
                    raw_hints = [data.get("hint")]
                for hint in raw_hints:
                    record = self._skill_memory_hint_record_from_text(hint, family)
                    hint_records.append(record)
                    hint_type = record["hint_type"]
                    hint_type_counts[hint_type] = hint_type_counts.get(hint_type, 0) + 1
                    hint_count += 1
                continue

            if event_type in {"goal_start", "auto_goal", "curriculum_goal"}:
                goal_count += 1
            if event_type in {"goal_end", "auto_goal_complete", "auto_goal_failed", "goal_verification"}:
                success = self._event_success(data)
                if success is True:
                    completed_goal_count += 1
                    if hint_seen:
                        post_hint_goal_success_count += 1
                elif success is False:
                    failed_goal_count += 1
                    if hint_seen:
                        post_hint_goal_failure_count += 1

            if event_type != "action":
                continue
            action_count += 1
            action = data.get("action", {}) if isinstance(data.get("action", {}), dict) else {}
            result = data.get("result", {}) if isinstance(data.get("result", {}), dict) else {}
            success = self._event_success(result)
            if success is False:
                failed_action_count += 1
            if hint_seen:
                post_hint_action_count += 1
                if success is False:
                    post_hint_failed_action_count += 1
                    category = self._action_failure_category(action, result)
                    signature = self._action_failure_signature(action, category)
                    if signature and signature == last_post_hint_failure:
                        repeated_post_hint_failures += 1
                    last_post_hint_failure = signature
                elif success is True:
                    last_post_hint_failure = ""

        labels = self._skill_memory_quality_labels(
            hint_type_counts,
            post_hint_failed_action_count,
            repeated_post_hint_failures,
            post_hint_goal_success_count,
            post_hint_goal_failure_count,
        )
        recommendations = self._skill_memory_quality_recommendations(labels)
        hint_quality_items = self._skill_memory_quality_items(source_log, hint_records, labels)
        return SkillMemoryQualityCase(
            source_log=source_log,
            event_count=len(events),
            hint_event_count=hint_events,
            hint_count=hint_count,
            reuse_hint_count=hint_type_counts.get("REUSE", 0),
            avoid_hint_count=hint_type_counts.get("AVOID", 0),
            review_only_hint_count=hint_type_counts.get("REVIEW_ONLY", 0),
            unknown_hint_count=hint_type_counts.get("UNKNOWN", 0),
            action_count=action_count,
            failed_action_count=failed_action_count,
            post_hint_action_count=post_hint_action_count,
            post_hint_failed_action_count=post_hint_failed_action_count,
            repeated_post_hint_failure_count=repeated_post_hint_failures,
            goal_count=goal_count,
            completed_goal_count=completed_goal_count,
            failed_goal_count=failed_goal_count,
            post_hint_goal_success_count=post_hint_goal_success_count,
            post_hint_goal_failure_count=post_hint_goal_failure_count,
            task_family_counts=task_family_counts,
            hint_type_counts=hint_type_counts,
            hint_quality_items=hint_quality_items,
            quality_labels=labels,
            recommendations=recommendations,
            ready_for_skill_memory_quality_review=bool(hint_events and (post_hint_action_count or post_hint_goal_success_count or post_hint_goal_failure_count)),
        )

    def _memory_policy_trace_case(self, source_log: str, events: list[dict]) -> MemoryPolicyTraceCase:
        observation_count = 0
        plan_count = 0
        action_count = 0
        failed_action_count = 0
        goal_count = 0
        completed_goal_count = 0
        explicit_writes = 0
        explicit_reads = 0
        explicit_manage = 0
        explicit_semantic_writes = 0
        noisy_writes = 0
        write_operations = {}
        read_queries = []
        read_filter_events = 0
        read_filtered_entries = 0
        read_filter_reasons = {}
        episodic_candidates = 0
        semantic_candidates = 0
        failure_candidates = 0
        success_action_types = {}
        failed_action_types = {}

        episodic_event_types = {
            "goal_start", "goal_end", "action", "reflection", "error",
            "visual_action_suggestion", "visual_action_intervention",
            "goal_verification", "failure_correction_selected",
            "failure_correction_action", "failure_correction_completed",
            "failure_correction_failed", "runtime_interrupt",
            "runtime_emergency_action", "task_state_update",
            "auto_goal", "auto_goal_complete", "auto_goal_failed",
            "curriculum_goal",
        }

        for event in events:
            event_type = str(event.get("type") or "")
            data = event.get("data", {}) if isinstance(event.get("data", {}), dict) else {}
            if event_type == "observation":
                observation_count += 1
            if event_type == "plan":
                plan_count += 1
            if event_type == "goal_start":
                goal_count += 1
            if event_type in episodic_event_types:
                episodic_candidates += 1

            memory_kind = self._memory_event_kind(event_type, data)
            if memory_kind == "write":
                explicit_writes += 1
                operation = self._memory_write_operation(event_type, data)
                write_operations[operation] = write_operations.get(operation, 0) + 1
                if self._memory_write_is_semantic(data):
                    explicit_semantic_writes += 1
                if self._memory_write_is_noisy(data):
                    noisy_writes += 1
            elif memory_kind == "read":
                explicit_reads += 1
                query = self._memory_read_query(data)
                if query and query not in read_queries:
                    read_queries.append(query)
                filter_report = data.get("read_filter_report", {}) if isinstance(data.get("read_filter_report", {}), dict) else {}
                if filter_report:
                    read_filter_events += 1
                    read_filtered_entries += int(filter_report.get("filtered_entries") or 0)
                    self._merge_counts(read_filter_reasons, filter_report.get("filter_reasons", {}))
            elif memory_kind == "manage":
                explicit_manage += 1

            if event_type == "action":
                action_count += 1
                action = data.get("action", {}) if isinstance(data.get("action", {}), dict) else {}
                result = data.get("result", {}) if isinstance(data.get("result", {}), dict) else {}
                action_type = str(action.get("type") or result.get("action_type") or "unknown")
                if result.get("success") is False:
                    failed_action_count += 1
                    failed_action_types[action_type] = failed_action_types.get(action_type, 0) + 1
                    failure_candidates += 1
                elif result.get("success") is True:
                    success_action_types[action_type] = success_action_types.get(action_type, 0) + 1
            elif event_type == "goal_end":
                result = data.get("result", {}) if isinstance(data.get("result", {}), dict) else {}
                if result.get("completed") is True or result.get("success") is True:
                    completed_goal_count += 1
                    semantic_candidates += 1
            elif event_type == "goal_verification":
                context = data.get("context", {}) if isinstance(data.get("context", {}), dict) else {}
                if data.get("achieved") is True and context.get("accepted") is not False:
                    semantic_candidates += 1
            elif event_type in {"reflection", "failure_correction_selected", "failure_correction_completed", "failure_correction_failed"}:
                failure_candidates += 1

        repeated_successes = sum(1 for count in success_action_types.values() if count >= 2)
        repeated_failures = sum(1 for count in failed_action_types.values() if count >= 2)
        consolidation_signals = completed_goal_count + repeated_successes + repeated_failures + explicit_manage
        missed_semantic = max(0, semantic_candidates - explicit_semantic_writes)
        missing_reads = max(0, plan_count - explicit_reads)

        hints = []
        if missing_reads:
            hints.append("instrument_memory_retrieval")
        if missed_semantic:
            hints.append("promote_verified_outcomes")
        if failure_candidates:
            hints.append("record_failure_corrections")
        if noisy_writes:
            hints.append("tighten_memory_write_gate")
        if consolidation_signals:
            hints.append("queue_consolidation_review")
        if read_filtered_entries:
            hints.append("review_filtered_memory_reads")

        return MemoryPolicyTraceCase(
            source_log=source_log,
            event_count=len(events),
            observation_count=observation_count,
            plan_count=plan_count,
            action_count=action_count,
            failed_action_count=failed_action_count,
            goal_count=goal_count,
            completed_goal_count=completed_goal_count,
            explicit_memory_write_count=explicit_writes,
            explicit_memory_read_count=explicit_reads,
            explicit_memory_manage_count=explicit_manage,
            context_write_candidate_count=observation_count + plan_count,
            episodic_write_candidate_count=episodic_candidates,
            semantic_write_candidate_count=semantic_candidates,
            missed_semantic_write_count=missed_semantic,
            failure_learning_candidate_count=failure_candidates,
            consolidation_signal_count=consolidation_signals,
            noisy_write_candidate_count=noisy_writes,
            missing_read_trace_count=missing_reads,
            read_filter_event_count=read_filter_events,
            read_filtered_entry_count=read_filtered_entries,
            read_filter_reasons=read_filter_reasons,
            write_operations=write_operations,
            read_queries=read_queries[:12],
            policy_hints=hints,
            ready_for_memory_policy_review=bool(hints or explicit_writes or explicit_reads or explicit_manage),
        )

    def _memory_event_kind(self, event_type: str, data: dict) -> str:
        normalized = str(event_type or "").lower()
        operation = str(data.get("operation") or data.get("op") or data.get("kind") or "").lower()
        write_ops = {"write", "add", "append", "replace", "remove", "update", "promote"}
        read_ops = {"read", "recall", "retrieve", "search", "query"}
        manage_ops = {"manage", "consolidate", "consolidation", "compact", "prune", "curate"}
        if normalized in {"memory_write", "memory_add", "memory_replace", "memory_remove", "memory_update"}:
            return "write"
        if normalized == "memory_operation" and operation in write_ops:
            return "write"
        if normalized in {"memory_read", "memory_recall", "memory_search", "memory_retrieve", "memory_context"}:
            return "read"
        if normalized == "memory_operation" and operation in read_ops:
            return "read"
        if normalized in {"memory_manage", "memory_consolidation", "memory_compaction", "memory_prune", "memory_curate"}:
            return "manage"
        if normalized == "memory_operation" and operation in manage_ops:
            return "manage"
        return ""

    def _memory_write_operation(self, event_type: str, data: dict) -> str:
        operation = str(data.get("operation") or data.get("op") or "").lower()
        layer = str(data.get("layer") or data.get("memory_layer") or "").lower()
        memory_type = str(data.get("memory_type") or data.get("type") or "").lower()
        parts = [part for part in (operation or event_type, layer, memory_type) if part]
        return ":".join(parts)

    def _memory_write_is_semantic(self, data: dict) -> bool:
        layer = str(data.get("layer") or data.get("memory_layer") or "").lower()
        memory_type = str(data.get("memory_type") or data.get("type") or "").lower()
        operation = str(data.get("operation") or data.get("op") or "").lower()
        return layer in {"semantic", "l3", "long_term"} or memory_type in {"fact", "semantic"} or operation == "promote"

    def _memory_write_is_episodic(self, data: dict) -> bool:
        layer = str(data.get("layer") or data.get("memory_layer") or "").lower()
        memory_type = str(data.get("memory_type") or data.get("type") or "").lower()
        return layer in {"episodic", "episode"} or memory_type in {"episodic", "episode", "experience"}

    def _memory_write_is_noisy(self, data: dict) -> bool:
        content = str(data.get("content") or data.get("value") or data.get("text") or data.get("memory") or "")
        memory_type = str(data.get("memory_type") or data.get("type") or "").lower()
        source = str(data.get("source") or "").lower()
        confidence = self._safe_float(data.get("confidence"), default=1.0)
        if content and len(content.strip()) < 12:
            return True
        if confidence < 0.4:
            return True
        if memory_type in {"raw_observation", "observation_dump"}:
            return True
        if source in {"raw_observation", "observation"} and len(content) > 500:
            return True
        return False

    def _memory_read_query(self, data: dict) -> str:
        query = data.get("query") or data.get("goal") or data.get("prompt") or data.get("text") or ""
        return str(query).strip()[:160]

    def _safe_float(self, value, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _segment_has_visual_evidence(self, events: list[dict], source_log: str = "") -> bool:
        for event in events:
            if event.get("type") not in {"observation", "vision", "visual_analysis"}:
                continue
            data = event.get("data", {}) if isinstance(event.get("data", {}), dict) else {}
            if self._record_has_verified_or_nonpath_visual_evidence(data, source_log):
                return True
        return False

    def _record_has_verified_or_nonpath_visual_evidence(self, record: dict, source_log: str = "") -> bool:
        nonpath_visual_keys = {
            key for key in self._goal_visual_evidence_keys(record)
            if key not in {"screenshot_path", "screenshot", "screenshots", "image_path", "frame_path"}
        }
        if nonpath_visual_keys:
            return True
        return bool(self._screenshot_status_for_paths(self._visual_paths_from_record(record), source_log)["verified"])

    def _record_has_exploration_visual_signal(self, record: dict, source_log: str = "") -> bool:
        if self._record_has_verified_or_nonpath_visual_evidence(record, source_log):
            return True
        for key in ("visual_resources", "resources", "dangers"):
            if record.get(key) not in (None, "", [], {}):
                return True
        return False

    def _position_tuple(self, position) -> Optional[tuple[float, float, float]]:
        if not isinstance(position, dict):
            return None
        try:
            x = float(position.get("x", 0))
            y = float(position.get("y", 0))
            z = float(position.get("z", 0))
        except (TypeError, ValueError):
            return None
        return (round(x, 2), round(y, 2), round(z, 2))

    def _position_spans(self, positions: list[tuple[float, float, float]]) -> tuple[float, float, float]:
        if not positions:
            return 0.0, 0.0, 0.0
        xs = [pos[0] for pos in positions]
        ys = [pos[1] for pos in positions]
        zs = [pos[2] for pos in positions]
        return max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs)

    def _path_distance(self, positions: list[tuple[float, float, float]]) -> float:
        distance = 0.0
        for previous, current in zip(positions, positions[1:]):
            dx = current[0] - previous[0]
            dy = current[1] - previous[1]
            dz = current[2] - previous[2]
            distance += (dx * dx + dy * dy + dz * dz) ** 0.5
        return distance

    def _world_model_cell(self, position: tuple[float, float, float], cell_size: float) -> tuple[int, int]:
        return (math.floor(position[0] / cell_size), math.floor(position[2] / cell_size))

    def _world_model_cell_dict(self, cell: tuple[int, int]) -> dict:
        return {"x": int(cell[0]), "z": int(cell[1])}

    def _world_model_cell_center(self, cell: tuple[int, int], cell_size: float) -> dict:
        return {
            "x": round((cell[0] + 0.5) * cell_size, 2),
            "z": round((cell[1] + 0.5) * cell_size, 2),
        }

    def _world_model_cell_state(self, cell_states: dict, cell: tuple[int, int]) -> dict:
        if cell not in cell_states:
            cell_states[cell] = {
                "cell": cell,
                "visit_count": 0,
                "first_seen_index": 10**9,
                "last_seen_index": -1,
                "blocks": set(),
                "resources": set(),
                "entities": set(),
                "danger_count": 0,
            }
        return cell_states[cell]

    def _world_model_items(self, record: dict, keys: list[str]) -> list:
        items = []
        for key in keys:
            value = record.get(key)
            if isinstance(value, dict):
                items.extend(value.values())
            elif isinstance(value, list):
                items.extend(value)
        return items

    def _world_model_item_cell(self, item, fallback_cell: tuple[int, int], cell_size: float) -> tuple[int, int]:
        if isinstance(item, dict):
            position = self._position_tuple(item.get("position"))
            if position is not None:
                return self._world_model_cell(position, cell_size)
        return fallback_cell

    def _world_model_add_item(
        self,
        cell_states: dict,
        item,
        fallback_cell: tuple[int, int],
        cell_size: float,
        field: str,
        default_key: str = "name",
    ):
        name = self._item_name(item, default_key=default_key)
        if not name:
            return
        cell = self._world_model_item_cell(item, fallback_cell, cell_size)
        self._world_model_cell_state(cell_states, cell)[field].add(name)

    def _world_model_transitions(self, position_cells: list[tuple[int, int]]) -> list[dict]:
        counts = {}
        for source, target in zip(position_cells, position_cells[1:]):
            if source == target:
                continue
            key = (source, target)
            counts[key] = counts.get(key, 0) + 1
        transitions = [
            {
                "from_cell": self._world_model_cell_dict(source),
                "to_cell": self._world_model_cell_dict(target),
                "count": count,
            }
            for (source, target), count in counts.items()
        ]
        transitions.sort(key=lambda item: (-item["count"], item["from_cell"]["x"], item["from_cell"]["z"]))
        return transitions

    def _world_model_serialized_cells(self, cell_states: dict, cell_size: float, limit: int) -> list[dict]:
        cells = []
        for cell, state in cell_states.items():
            cells.append({
                "cell": self._world_model_cell_dict(cell),
                "center": self._world_model_cell_center(cell, cell_size),
                "visit_count": state["visit_count"],
                "first_seen_index": state["first_seen_index"],
                "last_seen_index": state["last_seen_index"],
                "blocks": sorted(state["blocks"])[:12],
                "resources": sorted(state["resources"])[:12],
                "entities": sorted(state["entities"])[:12],
                "danger_count": state["danger_count"],
            })
        cells.sort(key=lambda item: (item["first_seen_index"], item["cell"]["x"], item["cell"]["z"]))
        return cells[:limit]

    def _world_model_frontiers(
        self,
        cell_states: dict,
        last_cell: Optional[tuple[int, int]],
        cell_size: float,
    ) -> list[dict]:
        known = set(cell_states)
        candidates = {}
        for cell, state in cell_states.items():
            for direction, neighbor in self._world_model_neighbors(cell):
                if neighbor in known:
                    continue
                score = 1.0 + len(state["resources"]) * 1.5 + len(state["blocks"]) * 0.15 - min(2, state["danger_count"])
                if last_cell is not None:
                    score -= 0.05 * (abs(neighbor[0] - last_cell[0]) + abs(neighbor[1] - last_cell[1]))
                existing = candidates.get(neighbor)
                if existing and existing["score"] >= score:
                    continue
                candidates[neighbor] = {
                    "cell": self._world_model_cell_dict(neighbor),
                    "center": self._world_model_cell_center(neighbor, cell_size),
                    "from_cell": self._world_model_cell_dict(cell),
                    "direction": direction,
                    "nearby_resources": sorted(state["resources"])[:8],
                    "nearby_blocks": sorted(state["blocks"])[:8],
                    "nearby_danger_count": state["danger_count"],
                    "score": round(score, 3),
                }
        frontiers = list(candidates.values())
        frontiers.sort(key=lambda item: (-item["score"], item["cell"]["x"], item["cell"]["z"]))
        return frontiers

    def _world_model_neighbors(self, cell: tuple[int, int]) -> list[tuple[str, tuple[int, int]]]:
        x, z = cell
        return [
            ("east", (x + 1, z)),
            ("west", (x - 1, z)),
            ("south", (x, z + 1)),
            ("north", (x, z - 1)),
        ]

    def _world_model_resource_hotspots(self, cell_states: dict, cell_size: float) -> list[dict]:
        hotspots = []
        for cell, state in cell_states.items():
            for resource in sorted(state["resources"]):
                hotspots.append({
                    "resource": resource,
                    "cell": self._world_model_cell_dict(cell),
                    "center": self._world_model_cell_center(cell, cell_size),
                    "visit_count": state["visit_count"],
                    "danger_count": state["danger_count"],
                })
        hotspots.sort(key=lambda item: (item["danger_count"], -item["visit_count"], item["resource"]))
        return hotspots

    def _world_model_suggested_goals(
        self,
        frontiers: list[dict],
        resource_hotspots: list[dict],
        limit: int,
    ) -> list[str]:
        goals = []
        for frontier in frontiers[: max(1, min(4, limit))]:
            cell = frontier["cell"]
            center = frontier["center"]
            nearby = ", ".join(frontier.get("nearby_resources", [])[:3])
            suffix = f" near {nearby}" if nearby else ""
            goals.append(
                f"Explore {frontier['direction']} frontier cell ({cell['x']},{cell['z']}) "
                f"around x={center['x']}, z={center['z']}{suffix}"
            )
        for hotspot in resource_hotspots[: max(1, min(3, limit - len(goals)))]:
            cell = hotspot["cell"]
            center = hotspot["center"]
            goals.append(
                f"Revisit {hotspot['resource']} hotspot cell ({cell['x']},{cell['z']}) "
                f"around x={center['x']}, z={center['z']}"
            )
        return goals[:limit]

    def _inventory_counts(self, inventory) -> dict:
        if not isinstance(inventory, dict):
            return {}
        counts = {}
        for item, count in inventory.items():
            name = str(item or "").strip().lower()
            if not name:
                continue
            counts[name] = self._safe_float(count, 0.0)
        return counts

    def _absolute_progress_score(self, observation: dict) -> float:
        inventory = self._inventory_counts(observation.get("inventory", {}))
        health = max(0.0, min(20.0, self._safe_float(observation.get("health"), 20.0))) / 20.0
        item_score = min(8.0, sum(max(0.0, value) for value in inventory.values()) / 8.0)
        diversity_score = min(4.0, len([name for name, value in inventory.items() if value > 0]) / 4.0)
        dangers = observation.get("dangers", []) if isinstance(observation.get("dangers", []), list) else []
        nearby_hostiles = [
            entity for entity in self._entity_items_from_record(observation)
            if self._is_hostile_entity(entity)
        ]
        danger_penalty = min(2.0, (len(dangers) + len(nearby_hostiles)) * 0.5)
        return round(max(0.0, health + item_score + diversity_score - danger_penalty), 3)

    def _format_delta(self, value: float) -> str:
        if float(value).is_integer():
            return str(int(value))
        return f"{value:.2f}"

    def _named_items_from_record(self, record: dict, keys: list[str]) -> set[str]:
        names = set()
        for key in keys:
            value = record.get(key)
            if isinstance(value, dict):
                iterable = value.values()
            elif isinstance(value, list):
                iterable = value
            else:
                iterable = []
            for item in iterable:
                name = self._item_name(item)
                if name:
                    names.add(name)
        return names

    def _entity_items_from_record(self, record: dict) -> list:
        entities = []
        for key in ("nearby_entities", "entities"):
            value = record.get(key)
            if isinstance(value, list):
                entities.extend(value)
        return entities

    def _item_name(self, item, default_key: str = "name") -> str:
        if isinstance(item, dict):
            value = item.get(default_key) or item.get("name") or item.get("type") or item.get("id")
        else:
            value = item
        return str(value or "").strip().lower()

    def _is_hostile_entity(self, entity) -> bool:
        if not isinstance(entity, dict):
            return False
        if entity.get("hostile") is True:
            return True
        kind = str(entity.get("type") or entity.get("name") or "").lower()
        return kind in {"zombie", "skeleton", "creeper", "spider", "enderman", "witch", "drowned", "pillager"}

    def _action_failure_category(self, action: dict, result: dict) -> str:
        text = " ".join(
            str(value or "").lower()
            for value in (
                action.get("type") if isinstance(action, dict) else "",
                result.get("error"),
                result.get("reason"),
                result.get("message"),
            )
        )
        if any(token in text for token in ("not found", "cannot find", "no target", "not visible", "unknown block")):
            return "perception"
        if any(token in text for token in ("missing", "inventory", "recipe", "requires", "precondition", "tool")):
            return "reasoning"
        if any(token in text for token in ("path", "reach", "distance", "blocked", "timeout", "collision", "failed to move")):
            return "action"
        return "unknown"

    def _action_failure_signature(self, action: dict, category: str) -> str:
        params = action.get("parameters", {}) if isinstance(action.get("parameters", {}), dict) else {}
        subject = params.get("item") or params.get("block") or params.get("target") or params.get("entity")
        return f"{action.get('type', 'unknown')}:{subject or '-'}:{category}"

    def _self_evolution_remedy_candidate(self, action_type: str, category: str, action: dict, result: dict) -> str:
        params = action.get("parameters", {}) if isinstance(action.get("parameters", {}), dict) else {}
        subject = params.get("item") or params.get("block") or params.get("target") or params.get("entity") or ""
        detail = result.get("error") or result.get("reason") or result.get("message") or category
        target = f" {subject}" if subject else ""
        return f"{action_type}{target}: learn {category} remedy from failure ({str(detail)[:100]})"

    def _self_evolution_adaptor_recommendation(self, action_type: str, category: str) -> str:
        if category == "perception":
            return f"Before retrying {action_type}, insert scan/look_at or visual grounding for the target."
        if category == "reasoning":
            return f"Before retrying {action_type}, replan missing prerequisites and inventory/tool dependencies."
        if category == "action":
            return f"Before retrying {action_type}, repair navigation, reachability, or blocked-path steps."
        return f"Queue {action_type} failure for review before replaying the same plan."

    def _looks_like_multihop_goal(self, goal: str) -> bool:
        text = str(goal or "").lower()
        return any(marker in text for marker in (" and ", " then ", " before ", " after ", " while ", "prepare", "multi-hop"))

    def _lower_level_control_reason(self, action: dict, result: dict, desktop_command) -> str:
        action_type = str(action.get("type") or result.get("action_type") or "").lower()
        if action_type in {"dig", "place", "look_at", "attack"} and self._missing_precise_target(action):
            return "missing_precise_target"
        text = " ".join(
            str(value or "").lower()
            for value in (result.get("error"), result.get("reason"), result.get("message"))
        )
        if any(token in text for token in ("not visible", "no target", "cannot find", "not found", "unknown block")):
            return "visual_target_uncertain"
        if any(token in text for token in ("reach", "distance", "blocked", "path", "collision")):
            return "navigation_precision"
        if action_type in {"dig", "place", "look_at", "attack"} and getattr(desktop_command, "command", ""):
            return "visual_precision_action"
        return ""

    def _missing_precise_target(self, action: dict) -> bool:
        params = action.get("parameters", {}) if isinstance(action.get("parameters", {}), dict) else {}
        return not all(params.get(axis) is not None for axis in ("x", "y", "z"))

    def _action_abstraction_recommendation(self, index: int, goal: str, action_type: str, reason: str) -> str:
        prefix = f"action#{index} {action_type}"
        if goal:
            prefix = f"{goal}: {prefix}"
        return f"{prefix} may need lower-level control ({reason})"

    def _normalized_action_record(self, action_data: dict) -> tuple[dict, dict, str]:
        if not isinstance(action_data, dict):
            return {}, {}, "unknown"
        raw_action = action_data.get("action")
        if isinstance(raw_action, dict):
            action = dict(raw_action)
        elif raw_action not in (None, "", [], {}):
            action = {"type": str(raw_action)}
        else:
            action = {}
        result = action_data.get("result", {}) if isinstance(action_data.get("result", {}), dict) else {}
        action_type = str(
            action.get("type")
            or action.get("action_type")
            or action_data.get("action_type")
            or action_data.get("type")
            or result.get("action_type")
            or "unknown"
        ).strip()
        if not action_type:
            action_type = "unknown"
        return action, result, action_type

    def _action_target_name(self, action: dict, result: dict = None) -> str:
        action = action if isinstance(action, dict) else {}
        params = action.get("parameters", {}) if isinstance(action.get("parameters", {}), dict) else {}
        result = result if isinstance(result, dict) else {}
        for key in ("item", "block", "entity", "target", "resource"):
            value = params.get(key)
            if value not in (None, "", [], {}):
                return str(value)
        for key in ("item", "block", "entity", "target", "resource", "action_type"):
            value = result.get(key)
            if value not in (None, "", [], {}):
                return str(value)
        return ""

    def _normalized_entropy(self, counts: dict) -> float:
        values = [float(value) for value in (counts or {}).values() if value]
        total = sum(values)
        if total <= 0 or len(values) <= 1:
            return 0.0
        entropy = 0.0
        for value in values:
            probability = value / total
            entropy -= probability * math.log(probability)
        return entropy / math.log(len(values))

    def _visual_paths_from_record(self, record: dict) -> list[str]:
        if not isinstance(record, dict):
            return []
        paths = []
        for key in ("screenshot_path", "screenshot", "image_path", "frame_path"):
            value = record.get(key)
            if value:
                paths.append(str(value))
        screenshots = record.get("screenshots")
        if isinstance(screenshots, list):
            paths.extend(str(path) for path in screenshots if path)
        elif screenshots:
            paths.append(str(screenshots))
        return paths

    def _screenshot_status_for_paths(self, paths: list[str], source_log: str = "") -> dict:
        raw_paths = self._dedupe_strings(paths or [])
        verified = []
        missing = []
        invalid = []
        for screenshot_path in raw_paths:
            status, _resolved = self._local_image_status(screenshot_path, source_log)
            if status == "valid":
                verified.append(screenshot_path)
            elif status == "missing":
                missing.append(screenshot_path)
            else:
                invalid.append(screenshot_path)
        return {
            "raw": raw_paths,
            "verified": verified,
            "missing": missing,
            "invalid": invalid,
        }

    def _local_image_status(self, image_path: str, source_log: str = "") -> tuple[str, str]:
        """Classify a screenshot reference as valid, missing, or invalid local image."""
        resolved = self._resolve_local_visual_path(image_path, source_log)
        if not resolved or not os.path.exists(resolved) or not os.path.isfile(resolved):
            return "missing", resolved
        try:
            with open(resolved, "rb") as f:
                header = f.read(16)
        except OSError:
            return "missing", resolved
        if self._looks_like_image_header(header):
            return "valid", resolved
        return "invalid", resolved

    def _resolve_local_visual_path(self, image_path: str, source_log: str = "") -> str:
        text = str(image_path or "").strip()
        if not text or "://" in text or text.startswith("data:"):
            return ""
        if os.path.isabs(text):
            return os.path.normpath(text)
        candidates = []
        if source_log:
            source_dir = os.path.dirname(os.path.abspath(source_log))
            candidates.append(os.path.join(source_dir, text))
        candidates.append(os.path.abspath(text))
        for candidate in candidates:
            if os.path.exists(candidate):
                return os.path.normpath(candidate)
        return os.path.normpath(candidates[-1]) if candidates else ""

    def _looks_like_image_header(self, header: bytes) -> bool:
        if not header:
            return False
        return (
            header.startswith(b"\x89PNG\r\n\x1a\n")
            or header.startswith(b"\xff\xd8\xff")
            or header.startswith(b"GIF87a")
            or header.startswith(b"GIF89a")
            or (len(header) >= 12 and header.startswith(b"RIFF") and header[8:12] == b"WEBP")
        )

    def _dedupe_strings(self, values: list) -> list[str]:
        seen = set()
        result = []
        for value in values:
            text = str(value or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            result.append(text)
        return result

    def run_goal_verification_ablation_from_logs(
        self,
        session_log_paths: list[str],
        goal_critic=None,
        manual_labels: Optional[dict] = None,
    ) -> GoalVerificationAblationReport:
        """Compare deterministic, API-visual, and screenshot/VLM goal verification."""
        report = GoalVerificationAblationReport()
        for path in session_log_paths:
            try:
                events = self._load_session_events(path)
                segments = self._session_goal_segments(events)
                if not segments:
                    report.errors.append(f"{path}: missing goal_start or goal_end goal")
                    continue
                for goal_index, (goal, segment_events) in enumerate(segments, start=1):
                    observation = self._final_goal_observation(segment_events)
                    if not observation:
                        report.errors.append(f"{path}: missing observation for goal {goal!r}")
                        continue
                    recent_actions = self._recent_goal_actions(segment_events)
                    manual = self._manual_goal_label(manual_labels or {}, path, goal, goal_index)
                    report.cases.append(self._goal_verification_ablation_case(
                        goal,
                        observation,
                        recent_actions,
                        source_log=path,
                        goal_index=goal_index,
                        goal_critic=goal_critic,
                        manual_label=manual,
                    ))
            except Exception as e:
                report.errors.append(f"{path}: {e}")
        return report

    def _goal_verification_ablation_case(
        self,
        goal: str,
        observation: dict,
        recent_actions: list[dict],
        source_log: str,
        goal_index: int = 0,
        goal_critic=None,
        manual_label: Optional[dict] = None,
    ) -> GoalVerificationAblationResult:
        from singularity.core.goal_verifier import GoalVerifier

        deterministic_verifier = GoalVerifier(goal_critic=None)
        critic_verifier = GoalVerifier(goal_critic=goal_critic)
        api_observation = self._api_goal_observation(observation)
        screenshot_observation, screenshot_status = self._screenshot_vlm_goal_observation(observation, source_log)

        deterministic = deterministic_verifier.verify(goal, observation, recent_actions=recent_actions).to_dict()
        api_visual = critic_verifier.verify(goal, api_observation, recent_actions=recent_actions).to_dict()
        screenshot_vlm = critic_verifier.verify(goal, screenshot_observation, recent_actions=recent_actions).to_dict()

        deterministic_readiness = self._goal_verification_readiness(deterministic)
        api_visual_readiness = self._goal_verification_readiness(api_visual)
        screenshot_vlm_readiness = self._goal_verification_readiness(screenshot_vlm)
        changed = (
            deterministic_readiness != api_visual_readiness
            or api_visual_readiness != screenshot_vlm_readiness
            or deterministic.get("status") != api_visual.get("status")
            or api_visual.get("status") != screenshot_vlm.get("status")
            or deterministic.get("evidence", []) != api_visual.get("evidence", [])
            or api_visual.get("evidence", []) != screenshot_vlm.get("evidence", [])
            or deterministic.get("missing", []) != api_visual.get("missing", [])
            or api_visual.get("missing", []) != screenshot_vlm.get("missing", [])
        )
        api_visual_helped = deterministic_readiness != "approved" and api_visual_readiness == "approved"
        has_verified_screenshot = bool(screenshot_status["verified"])
        screenshot_vlm_helped = has_verified_screenshot and deterministic_readiness != "approved" and screenshot_vlm_readiness == "approved"
        screenshot_vlm_added_value = has_verified_screenshot and api_visual_readiness != "approved" and screenshot_vlm_readiness == "approved"
        manual_readiness = (manual_label or {}).get("readiness", "")
        return GoalVerificationAblationResult(
            source_log=source_log,
            goal=goal,
            has_visual_evidence=bool(self._goal_visual_evidence_keys(observation)),
            goal_index=goal_index,
            visual_evidence_keys=self._goal_visual_evidence_keys(observation),
            raw_screenshot_count=len(screenshot_status["raw"]),
            screenshot_count=len(screenshot_status["verified"]),
            missing_screenshot_count=len(screenshot_status["missing"]),
            invalid_screenshot_count=len(screenshot_status["invalid"]),
            manual_readiness=manual_readiness,
            manual_label_source=(manual_label or {}).get("source", ""),
            manual_label_notes=(manual_label or {}).get("notes", ""),
            deterministic_readiness=deterministic_readiness,
            api_visual_readiness=api_visual_readiness,
            screenshot_vlm_readiness=screenshot_vlm_readiness,
            deterministic_status=deterministic.get("status", "unknown"),
            api_visual_status=api_visual.get("status", "unknown"),
            screenshot_vlm_status=screenshot_vlm.get("status", "unknown"),
            deterministic_confidence=float(deterministic.get("confidence", 0.0) or 0.0),
            api_visual_confidence=float(api_visual.get("confidence", 0.0) or 0.0),
            screenshot_vlm_confidence=float(screenshot_vlm.get("confidence", 0.0) or 0.0),
            deterministic_reason=deterministic.get("critic", {}).get("reason", ""),
            api_visual_reason=api_visual.get("critic", {}).get("reason", ""),
            screenshot_vlm_reason=screenshot_vlm.get("critic", {}).get("reason", ""),
            deterministic_evidence=deterministic.get("evidence", []),
            api_visual_evidence=api_visual.get("evidence", []),
            screenshot_vlm_evidence=screenshot_vlm.get("evidence", []),
            deterministic_missing=deterministic.get("missing", []),
            api_visual_missing=api_visual.get("missing", []),
            screenshot_vlm_missing=screenshot_vlm.get("missing", []),
            deterministic_matched_rules=deterministic.get("matched_rules", []),
            api_visual_matched_rules=api_visual.get("matched_rules", []),
            screenshot_vlm_matched_rules=screenshot_vlm.get("matched_rules", []),
            changed=changed,
            visual_helped=screenshot_vlm_helped,
            api_visual_helped=api_visual_helped,
            screenshot_vlm_helped=screenshot_vlm_helped,
            screenshot_vlm_added_value=screenshot_vlm_added_value,
            deterministic_matches_manual=self._manual_match(deterministic_readiness, manual_readiness),
            api_visual_matches_manual=self._manual_match(api_visual_readiness, manual_readiness),
            screenshot_vlm_matches_manual=self._manual_match(screenshot_vlm_readiness, manual_readiness),
        )

    def _goal_verification_readiness(self, verification: dict) -> str:
        if verification.get("status") == "achieved" and verification.get("achieved"):
            return "approved"
        if verification.get("status") == "failed":
            return "rejected"
        return "unknown"

    def load_goal_verification_labels(self, label_path: str) -> dict:
        """Load manual goal-verification labels from JSON or JSONL."""
        if not label_path:
            return {}
        records = self._load_manual_label_records(label_path)
        return self._goal_verification_labels_from_records(records)

    def _goal_verification_labels_from_records(self, records: list[dict]) -> dict:
        labels = {}
        for record in records:
            if not isinstance(record, dict):
                continue
            label = self._normalize_goal_label(record)
            if not label.get("readiness"):
                continue
            keys = []
            if record.get("key"):
                keys.append(record["key"])
            source = record.get("source_log") or record.get("log") or record.get("path") or record.get("session_log")
            goal = record.get("goal") or record.get("task") or record.get("objective")
            goal_index = record.get("goal_index") or record.get("index") or record.get("segment_index") or 0
            if source or goal:
                keys.extend(self._goal_label_keys(source or "", goal or "", goal_index))
            if goal and not source:
                keys.append(goal)
            for key in keys:
                labels[self._label_key(key)] = label
        return labels

    def _review_labels_by_type(self, label_path: str, label_type: str) -> dict:
        if not label_path:
            return {}
        records = [
            record for record in self._load_manual_label_records(label_path)
            if isinstance(record, dict) and self._review_label_type(record) == label_type
        ]
        if label_type == "promotion_review":
            return self._promotion_review_labels_from_records(records)
        if label_type == "goal_verification":
            return self._goal_verification_labels_from_records(records)
        return {}

    def _normalize_goal_label(self, record: dict) -> dict:
        readiness = self._normalize_goal_readiness(
            record.get("readiness", record.get("label", record.get("status", record.get("decision"))))
        )
        if not readiness and "achieved" in record:
            readiness = "approved" if bool(record.get("achieved")) else "rejected"
        if not readiness and "completed" in record:
            readiness = "approved" if bool(record.get("completed")) else "rejected"
        return {
            "readiness": readiness,
            "source": str(record.get("source", record.get("reviewer", "manual_label")) or "manual_label"),
            "notes": str(record.get("notes", record.get("reason", "")) or ""),
        }

    def _normalize_goal_readiness(self, value) -> str:
        if isinstance(value, bool):
            return "approved" if value else "rejected"
        text = str(value or "").strip().lower()
        if text in {"approved", "approve", "achieved", "complete", "completed", "pass", "passed", "success", "satisfied", "true"}:
            return "approved"
        if text in {"rejected", "reject", "failed", "failure", "fail", "incomplete", "not_achieved", "false"}:
            return "rejected"
        if text in {"unknown", "uncertain", "ambiguous", "needs_review", "skip"}:
            return "unknown"
        return ""

    def _manual_goal_label(self, labels: dict, source_log: str, goal: str, goal_index: int) -> dict:
        if not labels:
            return {}
        for key in self._goal_label_keys(source_log, goal, goal_index):
            label = labels.get(self._label_key(key))
            if label:
                return label
        return {}

    def _goal_label_keys(self, source_log: str, goal: str, goal_index: int = 0) -> list[str]:
        goal_text = str(goal or "")
        source_text = str(source_log or "")
        basename = os.path.basename(source_text) if source_text else ""
        keys = []
        for source in [source_text, basename]:
            if not source:
                continue
            if goal_index:
                keys.append(f"{source}::{goal_index}::{goal_text}")
                keys.append(f"{source}::{goal_index}")
            if goal_text:
                keys.append(f"{source}::{goal_text}")
        if goal_text:
            keys.append(goal_text)
        return keys

    def _label_key(self, key) -> str:
        return str(key or "").strip().replace("\\", "/").lower()

    def _manual_match(self, readiness: str, manual_readiness: str) -> Optional[bool]:
        if not manual_readiness:
            return None
        return readiness == manual_readiness

    def _session_goal_from_end(self, events: list[dict]) -> str:
        for event in reversed(events):
            if event.get("type") == "goal_end":
                return event.get("data", {}).get("goal", "")
        return ""

    def _session_goal_segments(self, events: list[dict]) -> list[tuple[str, list[dict]]]:
        segments = []
        current_goal = ""
        start_index = 0
        for index, event in enumerate(events):
            event_type = event.get("type")
            if event_type == "goal_start":
                if current_goal and start_index < index:
                    segments.append((current_goal, events[start_index:index]))
                current_goal = event.get("data", {}).get("goal", "")
                start_index = index
                continue
            if event_type == "goal_end":
                goal = event.get("data", {}).get("goal", "") or current_goal
                if goal:
                    segment_start = start_index if current_goal else 0
                    segments.append((goal, events[segment_start:index + 1]))
                current_goal = ""
                start_index = index + 1
        if current_goal and start_index < len(events):
            segments.append((current_goal, events[start_index:]))
        if not segments:
            goal = self._session_goal(events) or self._session_goal_from_end(events)
            if goal:
                segments.append((goal, events))
        return segments

    def _final_goal_observation(self, events: list[dict]) -> dict:
        latest = {}
        for event in events:
            if event.get("type") == "observation" and isinstance(event.get("data"), dict):
                latest = event["data"]
            if event.get("type") == "goal_end":
                break
        return latest

    def _recent_goal_actions(self, events: list[dict], limit: int = 5) -> list[dict]:
        actions = []
        last_observation = {}
        for index, event in enumerate(events):
            event_type = event.get("type")
            if event_type == "observation" and isinstance(event.get("data"), dict):
                last_observation = event["data"]
                continue
            if event_type != "action":
                continue
            data = event.get("data", {}) if isinstance(event.get("data"), dict) else {}
            after_observation = self._next_observation(events, index)
            action_event = {
                "action": data.get("action", data.get("type", {})),
                "result": data.get("result", {}),
                "before_observation": last_observation,
                "after_observation": after_observation,
            }
            if isinstance(last_observation.get("inventory"), dict):
                action_event["before_inventory"] = last_observation["inventory"]
            if isinstance(after_observation.get("inventory"), dict):
                action_event["after_inventory"] = after_observation["inventory"]
            actions.append(action_event)
        return actions[-limit:]

    def _next_observation(self, events: list[dict], start_index: int) -> dict:
        for event in events[start_index + 1:]:
            if event.get("type") == "observation" and isinstance(event.get("data"), dict):
                return event["data"]
            if event.get("type") == "goal_end":
                break
        return {}

    def _screenshot_vlm_goal_observation(self, observation: dict, source_log: str = "") -> tuple[dict, dict]:
        if not isinstance(observation, dict):
            return {}, self._screenshot_status_for_paths([], source_log)
        status = self._screenshot_status_for_paths(self._visual_paths_from_record(observation), source_log)
        filtered = dict(observation)
        for key in ("screenshot_path", "screenshot", "screenshots", "image_path", "frame_path", "image", "image_data"):
            filtered.pop(key, None)
        if status["verified"]:
            filtered["screenshot_path"] = status["verified"][0]
            if len(status["verified"]) > 1:
                filtered["screenshots"] = status["verified"][:3]
        filtered["screenshot_file_status"] = {
            "raw_count": len(status["raw"]),
            "verified_count": len(status["verified"]),
            "missing_count": len(status["missing"]),
            "invalid_count": len(status["invalid"]),
        }
        return filtered, status

    def _api_goal_observation(self, observation: dict) -> dict:
        if not isinstance(observation, dict):
            return {}
        raw_visual_keys = {
            "screenshot_path",
            "screenshot",
            "screenshots",
            "image_path",
            "frame_path",
            "image",
            "image_data",
            "visual_analysis",
            "vlm_analysis",
            "screenshot_analysis",
        }
        return {
            key: value
            for key, value in observation.items()
            if key not in raw_visual_keys
        }

    def _goal_visual_evidence_keys(self, observation: dict) -> list[str]:
        if not isinstance(observation, dict):
            return []
        visual_keys = {
            "screenshot_path",
            "screenshot",
            "screenshots",
            "image_path",
            "frame_path",
            "visual_analysis",
            "vlm_analysis",
            "screenshot_analysis",
            "grounded_resources",
            "landmarks",
            "structures",
            "flags",
        }
        return sorted(
            key for key in visual_keys
            if observation.get(key) not in (None, "", [], {})
        )

    def ingest_results(
        self,
        results: Optional[list[BenchmarkResult]] = None,
        memory_system=None,
        skill_library=None,
        candidate_queue=None,
        promotion_critic=None,
    ) -> BenchmarkIngestionReport:
        """Promote successful benchmark traces into memory and reviewable skills."""
        from singularity.core.memory import MemorySystem
        from singularity.core.skill_extractor import SkillCandidateQueue, SkillExtractor
        from singularity.core.skill_library import SkillLibrary

        source_results = results if results is not None else self.results
        report = BenchmarkIngestionReport()
        memory_system = memory_system or MemorySystem(memory_dir=self.config.memory_dir)
        skill_library = skill_library or SkillLibrary()
        candidate_queue = candidate_queue or SkillCandidateQueue()
        extractor = SkillExtractor(
            skill_library,
            memory_system,
            auto_promote=False,
            promotion_critic=promotion_critic,
        )

        for result in source_results:
            if result.status != "pass":
                report.skipped_results += 1
                continue
            if not result.session_log_path or not os.path.exists(result.session_log_path):
                report.skipped_results += 1
                report.errors.append(f"{result.task_id}: missing session log {result.session_log_path!r}")
                continue

            try:
                atoms = extractor.extract_experience_atoms(result.session_log_path)
                candidates = extractor.extract_skill_candidates(result.session_log_path)
                candidates.extend(extractor.extract_causal_skill_candidates(result.session_log_path))
                candidates.extend(extractor.extract_failure_correction_candidates(result.session_log_path))
                for candidate in candidates:
                    candidate.reason = f"{candidate.reason}; benchmark={result.task_id}:{result.task_name}"
                    candidate.signals = {
                        **candidate.signals,
                        "benchmark_task_id": result.task_id,
                        "benchmark_task_name": result.task_name,
                    }
                    validation = extractor.validate_candidate_for_promotion(candidate)
                    validation_report = {
                        **validation.to_dict(),
                        "benchmark_task_id": result.task_id,
                        "benchmark_task_name": result.task_name,
                    }
                    candidate.signals = {
                        **candidate.signals,
                        "verification_gate": validation_report.get("gate", candidate.signals.get("verification_gate", {})),
                        "promotion_report": validation_report,
                    }
                    report.record_promotion_report(validation_report)
                    candidate_queue.enqueue(candidate)
                    report.queued_candidate_ids.append(candidate.id)

                report.processed_results += 1
                report.experience_atoms += len(atoms)
                report.skill_candidates += len(candidates)
            except Exception as e:
                report.skipped_results += 1
                report.errors.append(f"{result.task_id}: {e}")

        return report

    def run_policy_skill_ablation(
        self,
        cases: Optional[list[PolicySkillAblationCase]] = None,
        skill_storage_path: str = "",
        include_builtin: bool = True,
    ) -> PolicySkillAblationReport:
        """Compare online behavior with reviewed policy skills disabled versus enabled."""
        report = PolicySkillAblationReport()
        if cases is not None:
            source_cases = cases
        else:
            source_cases = []
            if include_builtin:
                source_cases.extend(POLICY_SKILL_ABLATION_CASES)
            if skill_storage_path:
                source_cases.extend(self.policy_skill_cases_from_library(skill_storage_path))
        for case in source_cases:
            disabled = self._run_policy_skill_case(case, enable_policy_skills=False)
            enabled = self._run_policy_skill_case(case, enable_policy_skills=True)
            enabled_metrics = enabled.get("metrics", {})
            disabled_metrics = disabled.get("metrics", {})
            report.cases.append(PolicySkillAblationResult(
                case_id=case.id,
                case_name=case.name,
                disabled_corrected=bool(disabled.get("corrected")),
                enabled_corrected=bool(enabled.get("corrected")),
                enabled_helped=(
                    not disabled.get("corrected")
                    and bool(enabled.get("corrected")) == case.expected_enabled_corrected
                ),
                disabled_interventions=disabled_metrics.get("policy_intervention_count", 0),
                enabled_interventions=enabled_metrics.get("policy_intervention_count", 0),
                enabled_success_rate=enabled_metrics.get("policy_intervention_success_rate", 0.0),
                enabled_actions=[action.get("type", "") for action in enabled.get("actions", [])],
                skill_name=case.skill_name,
                source=case.source,
            ))
        return report

    def policy_skill_cases_from_library(
        self,
        skill_storage_path: str,
        max_cases: int = 20,
    ) -> list[PolicySkillAblationCase]:
        """Build policy-skill ablation cases from approved custom skills."""
        from singularity.core.skill_library import SkillLibrary

        skill_library = SkillLibrary(storage_path=skill_storage_path, persist=True)
        cases = []
        for skill in skill_library.list_skills():
            implementation = self._skill_implementation_payload(skill.implementation)
            if implementation.get("type") != "failure_correction_skill":
                continue
            case = self._policy_case_from_skill(skill.name, skill.description, implementation)
            if case:
                cases.append(case)
            if len(cases) >= max_cases:
                break
        return cases

    def _policy_case_from_skill(self, skill_name: str, description: str, implementation: dict) -> Optional[PolicySkillAblationCase]:
        avoid = implementation.get("avoid_action_template", {})
        correction_sequence = implementation.get("correction_sequence", [])
        if not avoid or not correction_sequence:
            return None
        failed_result = self._failed_result_for_action(avoid, implementation)
        world_state = self._world_state_for_policy_skill(avoid, correction_sequence)
        goal = self._goal_for_policy_skill(avoid, correction_sequence)
        return PolicySkillAblationCase(
            id=f"AB-POLICY-LIB-{self._safe_case_id(skill_name)}",
            name=f"Reviewed skill: {skill_name}",
            goal=goal,
            world_state=world_state,
            failed_action=avoid,
            failed_result=failed_result,
            skill_name=skill_name,
            skill_description=description,
            skill_implementation=implementation,
            source="skill_library",
        )

    def _skill_implementation_payload(self, implementation: str) -> dict:
        try:
            payload = json.loads(implementation)
        except (TypeError, ValueError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _failed_result_for_action(self, action: dict, implementation: dict) -> dict:
        params = action.get("parameters", {}) if isinstance(action.get("parameters", {}), dict) else {}
        evidence = implementation.get("evidence", {}) if isinstance(implementation.get("evidence", {}), dict) else {}
        return {
            "success": False,
            "action_type": action.get("type", ""),
            "item": params.get("item"),
            "block": params.get("block"),
            "error": evidence.get("failure_why") or "Policy skill ablation synthetic failure",
        }

    def _world_state_for_policy_skill(self, avoid: dict, sequence: list[dict]) -> dict:
        inventory = {}
        nearby_blocks = []
        avoid_params = avoid.get("parameters", {}) if isinstance(avoid.get("parameters", {}), dict) else {}
        if avoid.get("type") == "craft":
            item = avoid_params.get("item")
            if item == "torch":
                inventory["stick"] = 1
        for action in sequence:
            params = action.get("parameters", {}) if isinstance(action.get("parameters", {}), dict) else {}
            if action.get("type") == "dig" and params.get("block"):
                nearby_blocks.append({"name": params["block"]})
            if action.get("type") == "craft" and params.get("item") == "torch":
                inventory.setdefault("stick", 1)
        return {
            "inventory": inventory,
            "nearby_blocks": nearby_blocks,
            "nearby_entities": [],
            "position": {"x": 0, "y": 64, "z": 0},
        }

    def _goal_for_policy_skill(self, avoid: dict, sequence: list[dict]) -> str:
        for action in [avoid] + list(sequence):
            params = action.get("parameters", {}) if isinstance(action.get("parameters", {}), dict) else {}
            if action.get("type") == "craft" and params.get("item"):
                return f"Craft {params['item']}"
            if action.get("type") == "dig" and params.get("block"):
                return f"Gather {params['block']}"
        return "Use reviewed policy skill"

    def _safe_case_id(self, text: str) -> str:
        cleaned = []
        for ch in str(text).upper():
            cleaned.append(ch if ch.isalnum() else "-")
        return "-".join(part for part in "".join(cleaned).split("-") if part)[:48] or "SKILL"

    def _run_policy_skill_case(self, case: PolicySkillAblationCase, enable_policy_skills: bool) -> dict:
        from singularity.core.memory import MemorySystem
        from singularity.core.skill_library import SkillLibrary
        from singularity.logging.session_logger import SessionLogger

        with tempfile.TemporaryDirectory() as tmpdir:
            state = json.loads(json.dumps(case.world_state, default=str))
            config = replace(
                self.config,
                log_dir=os.path.join(tmpdir, "logs"),
                memory_dir=os.path.join(tmpdir, "memory"),
                skill_dir=os.path.join(tmpdir, "skills"),
                enable_policy_skills=enable_policy_skills,
            )
            agent = object.__new__(Agent)
            agent.config = config
            agent.memory = MemorySystem(memory_dir=config.memory_dir)
            agent.skill_library = SkillLibrary(storage_path=config.skill_dir, persist=True)
            agent.skill_library.create_skill(
                case.skill_name,
                case.skill_description,
                json.dumps(case.skill_implementation, ensure_ascii=False, default=str),
            )
            agent.task_system = TaskSystem()
            agent.action_controller = _PolicySkillAblationActionController(state)
            agent.observer = _PolicySkillAblationObserver(state)
            agent.session_logger = SessionLogger(log_dir=config.log_dir)
            agent.explorer = _PolicySkillAblationExplorer()
            agent.runtime = _PolicySkillAblationRuntime()

            corrected, observation = agent._attempt_failure_correction(
                case.failed_action,
                case.failed_result,
                state,
                case.goal,
                {"mode": "policy_skill_ablation", "enabled": enable_policy_skills},
            )
            summary = agent.session_logger.get_summary()
            return {
                "corrected": corrected,
                "observation": observation,
                "actions": list(agent.action_controller.actions),
                "metrics": summary.get("intervention_metrics", {}),
            }

    def run_visual_action_ablation(
        self,
        cases: Optional[list[VisualActionAblationCase]] = None,
    ) -> VisualActionAblationReport:
        """Compare planned actions with visual action grounding disabled versus enabled."""
        report = VisualActionAblationReport()
        source_cases = VISUAL_ACTION_ABLATION_CASES if cases is None else cases
        for case in source_cases:
            disabled = self._run_visual_action_case(case, enable_visual_action_grounding=False)
            enabled = self._run_visual_action_case(case, enable_visual_action_grounding=True)
            disabled_actions = disabled.get("actions", [])
            enabled_actions = enabled.get("actions", [])
            enabled_metrics = enabled.get("metrics", {})
            disabled_metrics = disabled.get("metrics", {})
            enabled_phases = enabled_metrics.get("visual_action_intervention_phases", {})
            enabled_kinds = enabled_metrics.get("visual_action_intervention_kinds", {})
            changed = disabled_actions != enabled_actions
            phase_ok = not case.expected_phase or enabled_phases.get(case.expected_phase, 0) > 0
            changed_ok = changed == case.expected_enabled_changed
            passed = changed_ok and phase_ok
            report.cases.append(VisualActionAblationResult(
                case_id=case.id,
                case_name=case.name,
                disabled_actions=disabled_actions,
                enabled_actions=enabled_actions,
                changed=changed,
                passed=passed,
                enabled_helped=passed and case.expected_enabled_changed,
                disabled_interventions=disabled_metrics.get("visual_action_intervention_count", 0),
                enabled_interventions=enabled_metrics.get("visual_action_intervention_count", 0),
                expected_enabled_changed=case.expected_enabled_changed,
                expected_phase=case.expected_phase,
                enabled_phases=enabled_phases,
                enabled_kinds=enabled_kinds,
                source=case.source,
            ))
        return report

    def run_visual_action_ablation_from_logs(
        self,
        session_log_paths: list[str],
        max_cases_per_log: int = 20,
        include_builtin: bool = False,
    ) -> VisualActionAblationReport:
        """Replay visual action grounding interventions mined from session logs."""
        cases = []
        if include_builtin:
            cases.extend(VISUAL_ACTION_ABLATION_CASES)
        cases.extend(self.visual_action_cases_from_logs(session_log_paths, max_cases_per_log=max_cases_per_log))
        return self.run_visual_action_ablation(cases)

    def visual_action_cases_from_logs(
        self,
        session_log_paths: list[str],
        max_cases_per_log: int = 20,
    ) -> list[VisualActionAblationCase]:
        """Build visual action ablation cases from logged interventions and nearby plan context."""
        cases = []
        for path in session_log_paths:
            if not path or not os.path.exists(path):
                continue
            events = self._load_session_events(path)
            current_goal = ""
            last_observation = {}
            cases_for_log = 0
            for index, event in enumerate(events):
                data = event.get("data", {}) if isinstance(event.get("data", {}), dict) else {}
                event_type = event.get("type")
                if event_type == "goal_start":
                    current_goal = str(data.get("goal", "") or current_goal)
                    continue
                if event_type == "observation":
                    last_observation = data
                    continue
                if event_type != "visual_action_intervention":
                    continue
                case = self._visual_action_case_from_intervention(
                    path,
                    index,
                    data,
                    last_observation,
                    self._next_plan_after(events, index),
                    current_goal,
                )
                if case:
                    cases.append(case)
                    cases_for_log += 1
                if max_cases_per_log > 0 and cases_for_log >= max_cases_per_log:
                    break
        return cases

    def _visual_action_case_from_intervention(
        self,
        source_log: str,
        event_index: int,
        data: dict,
        observation: dict,
        plan_after: dict,
        current_goal: str = "",
    ) -> Optional[VisualActionAblationCase]:
        suggestion = data.get("suggestion", {}) if isinstance(data.get("suggestion", {}), dict) else {}
        action = suggestion.get("action", {}) if isinstance(suggestion.get("action", {}), dict) else {}
        phase = str(data.get("phase", "") or "")
        goal = str(data.get("goal", "") or current_goal or "visual action grounding")
        if not action or not observation:
            return None
        baseline_plan = self._baseline_plan_for_visual_intervention(phase, action, plan_after)
        if not baseline_plan.get("actions"):
            return None
        case_id = f"AB-VISACT-LOG-{self._safe_case_id(os.path.basename(source_log))}-{event_index}"
        return VisualActionAblationCase(
            id=case_id,
            name=f"{os.path.basename(source_log)}: {phase or suggestion.get('kind', 'visual action')}",
            goal=goal,
            observation=json.loads(json.dumps(observation, default=str)),
            plan=baseline_plan,
            expected_enabled_changed=True,
            expected_phase=phase,
            source=source_log,
        )

    def _baseline_plan_for_visual_intervention(self, phase: str, action: dict, plan_after: dict) -> dict:
        after_actions = []
        if isinstance(plan_after, dict):
            after_actions = [
                item for item in (plan_after.get("actions", []) or [])
                if isinstance(item, dict)
            ]
        if phase == "fill_coordinates" and action.get("type") == "dig":
            return {
                "status": "in_progress",
                "reasoning": "session-log baseline before visual coordinate fill",
                "actions": [{"type": "dig", "parameters": {}}],
            }
        if phase in {"prepend_approach", "prepend_danger"}:
            baseline_actions = list(after_actions)
            if baseline_actions and baseline_actions[0] == action:
                baseline_actions = baseline_actions[1:]
            if not baseline_actions:
                baseline_actions = [{"type": "wait", "parameters": {"ticks": 20}}]
            return {
                "status": "in_progress",
                "reasoning": f"session-log baseline before {phase}",
                "actions": baseline_actions,
            }
        return {
            "status": "in_progress",
            "reasoning": "session-log baseline before visual intervention",
            "actions": list(after_actions) or [{"type": "wait", "parameters": {"ticks": 20}}],
        }

    def _next_plan_after(self, events: list[dict], index: int) -> dict:
        for event in events[index + 1:]:
            if event.get("type") == "plan" and isinstance(event.get("data", {}), dict):
                return event.get("data", {})
            if event.get("type") in {"observation", "goal_end"}:
                break
        return {}

    def _run_visual_action_case(self, case: VisualActionAblationCase, enable_visual_action_grounding: bool) -> dict:
        from singularity.logging.session_logger import SessionLogger
        from singularity.vision.action_advisor import VisualActionAdvisor

        with tempfile.TemporaryDirectory() as tmpdir:
            config = replace(
                self.config,
                log_dir=os.path.join(tmpdir, "logs"),
                memory_dir=os.path.join(tmpdir, "memory"),
                enable_visual_action_grounding=enable_visual_action_grounding,
            )
            agent = object.__new__(Agent)
            agent.config = config
            agent.visual_action_advisor = VisualActionAdvisor()
            agent.session_logger = SessionLogger(log_dir=config.log_dir)
            agent.memory = None
            plan = json.loads(json.dumps(case.plan, default=str))
            observation = json.loads(json.dumps(case.observation, default=str))
            grounded = agent._apply_visual_action_grounding(plan, observation, case.goal)
            summary = agent.session_logger.get_summary()
            return {
                "plan": grounded,
                "actions": list(grounded.get("actions", []) or []) if isinstance(grounded, dict) else [],
                "metrics": summary.get("intervention_metrics", {}),
            }

    def run_coach_style_ablation(
        self,
        cases: Optional[list[CoachStyleAblationCase]] = None,
        styles: Optional[list[str]] = None,
    ) -> CoachStyleAblationReport:
        """Compare baseline curriculum ranking against advisory coach styles."""
        report = CoachStyleAblationReport()
        source_cases = COACH_STYLE_ABLATION_CASES if cases is None else cases
        for case in source_cases:
            manager = self._curriculum_for_coach_case(case)
            baseline_candidates = manager.propose_goals(
                case.observation,
                case.fallback_goal,
                memory_system=None,
                skill_library=None,
            )
            baseline = baseline_candidates[0] if baseline_candidates else None
            baseline_goal = baseline.title if baseline else case.fallback_goal
            baseline_score = float(baseline.score if baseline else 0.0)
            baseline_category = baseline.category if baseline else ""
            baseline_dicts = [manager._candidate_dict(candidate) for candidate in baseline_candidates[:5]]
            for style in self._coach_styles_for_case(case, styles):
                coach = CoachPolicy.from_style(style)
                styled_candidates = (
                    coach.rank_curriculum_candidates(baseline_candidates, case.observation, case.fallback_goal)
                    if coach.active
                    else list(baseline_candidates)
                )
                styled = styled_candidates[0] if styled_candidates else baseline
                styled_goal = styled.title if styled else case.fallback_goal
                styled_score = float(styled.score if styled else 0.0)
                report.cases.append(CoachStyleAblationResult(
                    case_id=case.id,
                    case_name=case.name,
                    style=",".join(coach.style_names) if coach.active else str(style or "none"),
                    baseline_goal=baseline_goal,
                    styled_goal=styled_goal,
                    changed=baseline_goal != styled_goal,
                    baseline_score=round(baseline_score, 3),
                    styled_score=round(styled_score, 3),
                    score_delta=round(styled_score - baseline_score, 3),
                    baseline_category=baseline_category,
                    styled_category=styled.category if styled else "",
                    styled_reasons=list(styled.reasons if styled else []),
                    baseline_candidates=baseline_dicts,
                    styled_candidates=[manager._candidate_dict(candidate) for candidate in styled_candidates[:5]],
                    fallback_goal=case.fallback_goal,
                    source=case.source,
                ))
        return report

    def load_coach_style_ablation_cases(self, case_files: list[str]) -> list[CoachStyleAblationCase]:
        """Load coach ablation cases from JSON or JSONL files."""
        cases = []
        for path in case_files or []:
            for index, record in enumerate(self._load_case_records(path), start=1):
                case = self._coach_style_case_from_record(record, source=path, index=index)
                if case:
                    cases.append(case)
        return cases

    def coach_style_ablation_cases_from_logs(
        self,
        session_log_paths: list[str],
        max_cases_per_log: int = 20,
        fallback_goal: str = "Explore surroundings and gather resources",
        styles: Optional[list[str]] = None,
    ) -> list[CoachStyleAblationCase]:
        """Extract observation snapshots from session logs for style replay."""
        cases = []
        for path in session_log_paths or []:
            events = self._load_session_events(path)
            active_goal = fallback_goal
            emitted = 0
            for event in events:
                event_type = event.get("type")
                data = event.get("data", {}) if isinstance(event.get("data", {}), dict) else {}
                if event_type in {"goal_start", "auto_goal"}:
                    active_goal = str(data.get("goal") or data.get("selected") or active_goal or fallback_goal)
                    continue
                if event_type == "curriculum_goal":
                    active_goal = str(data.get("fallback") or data.get("selected") or active_goal or fallback_goal)
                    continue
                if event_type != "observation":
                    continue
                observation = data
                if not isinstance(observation, dict) or not self._coach_observation_has_signal(observation):
                    continue
                emitted += 1
                cases.append(CoachStyleAblationCase(
                    id=f"LOG-COACH-{len(cases) + 1:03d}",
                    name=f"{os.path.basename(path)} observation {emitted}",
                    observation=observation,
                    fallback_goal=active_goal or fallback_goal,
                    styles=list(styles or []),
                    source=path,
                ))
                if emitted >= max_cases_per_log:
                    break
        return cases

    def _coach_styles_for_case(self, case: CoachStyleAblationCase, styles: Optional[list[str]] = None) -> list[str]:
        requested = [style for style in (styles or case.styles or []) if style]
        return requested or list(CoachPolicy.PROFILES.keys())

    def _curriculum_for_coach_case(self, case: CoachStyleAblationCase) -> CurriculumManager:
        manager = CurriculumManager()
        if case.exploration_feedback:
            manager.record_exploration_feedback(case.exploration_feedback)
        if case.world_model_feedback:
            manager.record_world_model_feedback(case.world_model_feedback)
        return manager

    def _load_case_records(self, path: str) -> list[dict]:
        with open(path, "r", encoding="utf-8-sig") as f:
            if path.lower().endswith(".jsonl"):
                return [json.loads(line) for line in f if line.strip()]
            payload = json.load(f)
        if isinstance(payload, dict) and isinstance(payload.get("cases"), list):
            return [record for record in payload["cases"] if isinstance(record, dict)]
        if isinstance(payload, list):
            return [record for record in payload if isinstance(record, dict)]
        if isinstance(payload, dict):
            return [payload]
        return []

    def _coach_style_case_from_record(self, record: dict, source: str = "", index: int = 1) -> Optional[CoachStyleAblationCase]:
        observation = (
            record.get("observation")
            or record.get("world_state")
            or record.get("current_state")
            or record.get("state")
        )
        if not isinstance(observation, dict):
            return None
        raw_styles = record.get("styles", record.get("style", []))
        if isinstance(raw_styles, str):
            styles = [raw_styles]
        elif isinstance(raw_styles, list):
            styles = [str(style) for style in raw_styles if style]
        else:
            styles = []
        return CoachStyleAblationCase(
            id=str(record.get("id") or f"FILE-COACH-{index:03d}"),
            name=str(record.get("name") or record.get("title") or f"Coach style case {index}"),
            observation=observation,
            fallback_goal=str(record.get("fallback_goal") or record.get("goal") or "Explore surroundings and gather resources"),
            styles=styles,
            exploration_feedback=record.get("exploration_feedback", {}) if isinstance(record.get("exploration_feedback", {}), dict) else {},
            world_model_feedback=record.get("world_model_feedback", {}) if isinstance(record.get("world_model_feedback", {}), dict) else {},
            source=source,
        )

    def _coach_observation_has_signal(self, observation: dict) -> bool:
        return any(key in observation for key in (
            "inventory",
            "nearby_blocks",
            "grounded_resources",
            "nearby_entities",
            "health",
            "time_of_day",
        ))

    def run_scheduling_ablation(self, cases: Optional[list[SchedulingAblationCase]] = None) -> SchedulingAblationReport:
        """Compare direct-observation scheduling with causal-opportunity scheduling."""
        report = SchedulingAblationReport()
        source_cases = SCHEDULING_ABLATION_CASES if cases is None else cases
        for case in source_cases:
            direct_task = self._ablation_selected_task(case, use_causal_opportunities=False)
            causal_task = self._ablation_selected_task(case, use_causal_opportunities=True)
            report.cases.append(SchedulingAblationResult(
                case_id=case.id,
                case_name=case.name,
                direct_only_task=direct_task,
                causal_enabled_task=causal_task,
                changed=direct_task != causal_task,
                causal_helped=bool(case.expected_causal_task)
                and causal_task == case.expected_causal_task
                and direct_task != causal_task,
                causal_tags=case.world_state.get("causal_tags", []),
                source=case.world_state.get("source_log", ""),
                action_type=case.world_state.get("causal_action_type", ""),
                outcome=case.world_state.get("causal_outcome", ""),
                value_score=case.world_state.get("causal_value_score", 0.0),
                avg_value_score=case.world_state.get("causal_avg_value_score", 0.0),
                repeat_count=case.world_state.get("causal_repeat_count", 1),
            ))
        return report

    def run_scheduling_ablation_from_logs(
        self,
        session_log_paths: list[str],
        max_cases_per_log: int = 20,
        min_value_score: float = 0.55,
    ) -> SchedulingAblationReport:
        """Replay session logs into causal scheduling ablation cases."""
        cases = []
        for path in session_log_paths:
            cases.extend(self._scheduling_cases_from_session_log(
                path,
                max_cases_per_log=max_cases_per_log,
                min_value_score=min_value_score,
            ))
        return self.run_scheduling_ablation(cases)

    def _scheduling_cases_from_session_log(
        self,
        session_log_path: str,
        max_cases_per_log: int = 20,
        min_value_score: float = 0.55,
    ) -> list[SchedulingAblationCase]:
        events = self._load_session_events(session_log_path)
        goal = self._session_goal(events)
        index = CausalEventIndex("", persist=False)
        causal_events = index.ingest_session_events(events, goal=goal)
        eligible_events = [
            event for event in causal_events
            if event.value_score >= min_value_score and self._causal_trigger_for_event(event)
        ]
        summaries = aggregate_causal_events(eligible_events, limit=max_cases_per_log)
        cases = []
        for summary in summaries:
            event = summary.representative
            trigger = self._causal_trigger_for_event(event)
            if not trigger:
                continue
            before = dict(event.evidence.get("before", {}))
            world_state = {
                **before,
                "causal_tags": summary.tags,
                "causal_events": [self._compact_causal_summary(summary)],
                "source_log": session_log_path,
                "causal_action_type": event.action_type,
                "causal_outcome": event.outcome,
                "causal_value_score": summary.value_score,
                "causal_avg_value_score": summary.avg_value_score,
                "causal_repeat_count": summary.repeat_count,
            }
            task_title = self._causal_replay_task_title(event, repeat_count=summary.repeat_count)
            repeat_suffix = f" ({summary.repeat_count}x)" if summary.repeat_count > 1 else ""
            cases.append(SchedulingAblationCase(
                id=f"LOG-SCHED-{len(cases) + 1:03d}",
                name=f"{os.path.basename(session_log_path)}: {event.outcome} {event.action_type}:{event.subject}{repeat_suffix}",
                world_state=world_state,
                tasks=[
                    {"title": f"Continue {goal or 'session goal'}", "priority": 3},
                    {
                        "title": task_title,
                        "priority": 3,
                        "preconditions": self._inventory_preconditions(before),
                        "opportunity_triggers": [trigger],
                        "tags": summary.tags[:12],
                    },
                ],
                expected_causal_task=task_title,
            ))
        return cases

    def _ablation_selected_task(self, case: SchedulingAblationCase, use_causal_opportunities: bool) -> str:
        task_system = TaskSystem(use_causal_opportunities=use_causal_opportunities)
        for spec in case.tasks:
            task_system.create_task(
                spec["title"],
                task_type=spec.get("type", "general"),
                status=TaskStatus.ACCEPTED,
                priority=spec.get("priority", 3),
                preconditions=spec.get("preconditions", {}),
                success_criteria=spec.get("success_criteria", {}),
                failure_criteria=spec.get("failure_criteria", {}),
                tags=spec.get("tags", []),
                opportunity_triggers=spec.get("opportunity_triggers", []),
            )
        selected = task_system.get_next_task(case.world_state)
        return selected.title if selected else ""

    def _load_session_events(self, session_log_path: str) -> list[dict]:
        events = []
        with open(session_log_path, "r", encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if line:
                    events.append(json.loads(line))
        return events

    def _load_task_stream_specs(self, stream_file: str) -> list[dict]:
        with open(stream_file, "r", encoding="utf-8-sig") as f:
            if stream_file.lower().endswith(".jsonl"):
                records = [json.loads(line) for line in f if line.strip()]
                if all(isinstance(record, dict) and "tasks" not in record for record in records):
                    return [{"id": os.path.splitext(os.path.basename(stream_file))[0], "tasks": records}]
                return [record for record in records if isinstance(record, dict)]
            payload = json.load(f)
        if isinstance(payload, dict) and isinstance(payload.get("streams"), list):
            return [stream for stream in payload["streams"] if isinstance(stream, dict)]
        if isinstance(payload, dict) and isinstance(payload.get("tasks"), list):
            return [payload]
        if isinstance(payload, list):
            if all(isinstance(record, dict) and "tasks" not in record for record in payload):
                return [{"id": os.path.splitext(os.path.basename(stream_file))[0], "tasks": payload}]
            return [record for record in payload if isinstance(record, dict)]
        return []

    def _task_stream_score(
        self,
        task_data: dict,
        stage: str,
        source_file: str,
        cell_size: float,
    ) -> Optional[float]:
        for key in self._task_stream_score_keys(stage):
            if key in task_data:
                score = self._score_from_value(task_data.get(key))
                if score is not None:
                    return score
        for payload in self._task_stream_stage_payloads(task_data, stage):
            for key in ("score", "success", "completed", "passed", "status", "result", "outcome"):
                if key in payload:
                    score = self._score_from_value(payload.get(key))
                    if score is not None:
                        return score
            log_path = self._task_stream_payload_log_path(payload, source_file)
            if log_path:
                score = self._score_from_session_log(log_path, cell_size)
                if score is not None:
                    return score
        log_path = task_data.get(f"{stage}_session_log") or task_data.get(f"{stage}_log")
        if stage in {"observed", "score"}:
            log_path = log_path or task_data.get("session_log") or task_data.get("log") or task_data.get("path")
        if log_path:
            return self._score_from_session_log(self._resolve_stream_path(str(log_path), source_file), cell_size)
        return None

    def _task_stream_score_keys(self, stage: str) -> list[str]:
        if stage == "score":
            return ["score", "success", "completed", "passed", "status", "result", "outcome"]
        aliases = {
            "baseline": ["baseline", "base", "without_memory", "direct"],
            "first_pass": ["first_pass", "first", "learned", "with_memory"],
            "second_pass": ["second_pass", "second", "replay", "retention"],
            "heldout": ["heldout", "held_out", "generalization"],
            "observed": ["observed", "actual", "run"],
        }.get(stage, [stage])
        keys = []
        for alias in aliases:
            keys.extend([f"{alias}_score", f"{alias}_success", f"{alias}_completed", f"{alias}_status", f"{alias}_result"])
        return keys

    def _task_stream_stage_payloads(self, task_data: dict, stage: str) -> list[dict]:
        aliases = {
            "baseline": ["baseline", "base", "without_memory", "direct"],
            "first_pass": ["first_pass", "first", "learned", "with_memory"],
            "second_pass": ["second_pass", "second", "replay", "retention"],
            "heldout": ["heldout", "held_out", "generalization"],
            "observed": ["observed", "actual", "run"],
            "score": ["score"],
        }.get(stage, [stage])
        payloads = []
        for alias in aliases:
            payload = task_data.get(alias)
            if isinstance(payload, dict):
                payloads.append(payload)
        return payloads

    def _score_from_value(self, value) -> Optional[float]:
        if value is None:
            return None
        if isinstance(value, bool):
            return 1.0 if value else 0.0
        if isinstance(value, (int, float)):
            return self._clamp_score(float(value))
        if isinstance(value, str):
            text = value.strip().lower()
            if text in {"achieved", "complete", "completed", "done", "ok", "pass", "passed", "success", "succeeded"}:
                return 1.0
            if text in {"aborted", "blocked", "error", "fail", "failed", "failure", "incomplete", "rejected"}:
                return 0.0
            try:
                return self._clamp_score(float(text))
            except ValueError:
                return None
        if isinstance(value, dict):
            success = self._event_success(value)
            if success is not None:
                return 1.0 if success else 0.0
            if "score" in value:
                return self._score_from_value(value.get("score"))
        return None

    def _score_from_session_log(self, session_log_path: str, cell_size: float) -> Optional[float]:
        try:
            events = self._load_session_events(session_log_path)
            case = self._continual_learning_trace_case(session_log_path, events, cell_size, 1200, 2400)
        except Exception:
            return None
        if case.goal_count:
            return round(case.completed_goal_count / max(1, case.goal_count), 3)
        if case.action_count:
            return round(case.successful_action_count / max(1, case.action_count), 3)
        return None

    def _task_stream_session_logs(self, task_data: dict, source_file: str) -> list[str]:
        raw_paths = []
        for key in ("session_log", "log", "path"):
            if task_data.get(key):
                raw_paths.append(task_data.get(key))
        for stage in ("baseline", "first_pass", "second_pass", "heldout", "observed"):
            for key in (f"{stage}_session_log", f"{stage}_log"):
                if task_data.get(key):
                    raw_paths.append(task_data.get(key))
            for payload in self._task_stream_stage_payloads(task_data, stage):
                log_path = self._task_stream_payload_log_path(payload, source_file)
                if log_path:
                    raw_paths.append(log_path)
        return self._dedupe_strings(
            self._resolve_stream_path(str(path), source_file)
            for path in raw_paths
            if path not in (None, "", [], {})
        )

    def _task_stream_payload_log_path(self, payload: dict, source_file: str) -> str:
        for key in ("session_log", "log", "path"):
            value = payload.get(key)
            if value not in (None, "", [], {}):
                return self._resolve_stream_path(str(value), source_file)
        return ""

    def _task_stream_session_summary(self, session_logs: list[str], cell_size: float) -> dict:
        summary = {
            "memory_read_count": 0,
            "memory_write_count": 0,
            "completed_goal_count": 0,
            "failed_goal_count": 0,
            "action_count": 0,
            "failed_action_count": 0,
            "evidence_text": "",
        }
        text_parts = []
        for path in session_logs:
            try:
                events = self._load_session_events(path)
                case = self._continual_learning_trace_case(path, events, cell_size, 1200, 2400)
            except Exception:
                continue
            summary["memory_read_count"] += case.memory_read_count
            summary["memory_write_count"] += case.memory_write_count
            summary["completed_goal_count"] += case.completed_goal_count
            summary["failed_goal_count"] += case.failed_goal_count
            summary["action_count"] += case.action_count
            summary["failed_action_count"] += case.failed_action_count
            for event in events:
                if event.get("type") in {"memory_read", "memory_write", "plan", "action", "goal_start", "goal_end"}:
                    text_parts.append(self._compact_event_text(event))
        evidence = " ".join(text_parts).lower()
        summary["evidence_text"] = f"{evidence} {evidence.replace('_', ' ')}"
        return summary

    def _task_stream_evidence_text(self, task_data: dict, session_summary: dict) -> str:
        evidence = f"{self._compact_event_text(task_data)} {session_summary.get('evidence_text', '')}".lower()
        return f"{evidence} {evidence.replace('_', ' ')}"

    def _resolve_stream_path(self, path: str, source_file: str) -> str:
        if os.path.isabs(path):
            return path
        source_dir = os.path.dirname(os.path.abspath(source_file))
        candidate = os.path.join(source_dir, path)
        if os.path.exists(candidate):
            return candidate
        return path

    def _string_list(self, value) -> list[str]:
        if value in (None, "", [], {}):
            return []
        if isinstance(value, list):
            return [str(item) for item in value if item not in (None, "", [], {})]
        return [str(value)]

    def _normalized_tag_list(self, value) -> list[str]:
        tags = []
        for item in self._string_list(value):
            tag = " ".join(str(item).strip().lower().split())
            if tag:
                tags.append(tag)
        return self._dedupe_strings(tags)

    def _tag_in_text(self, tag: str, text: str) -> bool:
        normalized = str(tag or "").strip().lower()
        if not normalized:
            return False
        haystack = str(text or "").lower()
        variants = {normalized, normalized.replace("_", " "), normalized.replace(" ", "_")}
        return any(variant and variant in haystack for variant in variants)

    def _score_delta(self, left: Optional[float], right: Optional[float]) -> Optional[float]:
        if left is None or right is None:
            return None
        return round(float(left) - float(right), 3)

    def _clamp_score(self, value: float) -> float:
        return round(max(0.0, min(1.0, float(value))), 3)

    def _session_goal(self, events: list[dict]) -> str:
        for event in events:
            if event.get("type") == "goal_start":
                return event.get("data", {}).get("goal", "")
        return ""

    def _causal_trigger_for_event(self, event: CausalEvent) -> str:
        subject = str(event.subject or "").lower()
        if subject and subject not in {"unknown", event.action_type} and not subject.startswith("pos:"):
            return subject
        for tag in event.tags:
            tag = str(tag).lower()
            if tag and tag not in {"success", "failure", event.action_type}:
                return tag
        return event.action_type or event.outcome

    def _causal_replay_task_title(self, event: CausalEvent, repeat_count: int = 1) -> str:
        verb = "Replay successful" if event.outcome == "success" else "Review failed"
        repeat_suffix = f" ({repeat_count}x)" if repeat_count > 1 else ""
        return f"{verb} {event.action_type}:{event.subject}{repeat_suffix}"

    def _inventory_preconditions(self, observation: dict) -> dict:
        inventory = {
            item: count
            for item, count in observation.get("inventory", {}).items()
            if isinstance(count, (int, float)) and count > 0
        }
        return {"inventory": inventory} if inventory else {}

    def _compact_causal_event(self, event: CausalEvent) -> dict:
        return {
            "id": event.id,
            "subject": event.subject,
            "action_type": event.action_type,
            "outcome": event.outcome,
            "which": event.which,
            "why": event.why,
            "tags": event.tags[:12],
            "confidence": event.confidence,
            "value_score": event.value_score,
            "value_reasons": event.value_reasons,
        }

    def _compact_causal_summary(self, summary: CausalEventSummary) -> dict:
        event = summary.representative
        compact = self._compact_causal_event(event)
        compact.update({
            "summary_key": list(summary.key),
            "tags": summary.tags[:12],
            "confidence": summary.confidence,
            "value_score": summary.value_score,
            "avg_value_score": summary.avg_value_score,
            "repeat_count": summary.repeat_count,
            "event_ids": summary.event_ids,
            "value_reasons": summary.value_reasons,
        })
        return compact

    def preflight(self, check_network: bool = True, check_screenshot_renderer: bool = False) -> PreflightReport:
        """Check local readiness before running live M1/M2 benchmarks."""
        checks = [
            self._check_python_import("pydantic", required=True),
            self._check_python_import("openai", required=False),
            self._check_python_import("anthropic", required=False),
            self._check_command("node", ["node", "--version"], required=True),
            self._check_command("npm", ["npm", "--version"], required=True),
            self._check_node_dependencies(),
        ]
        if check_screenshot_renderer:
            checks.append(self._check_screenshot_renderer())
        if check_network:
            checks.append(self._check_tcp(
                "bot_bridge",
                self.config.bot.bridge_host,
                self.config.bot.bridge_port,
                required=True,
            ))
            checks.append(self._check_bot_session())
            checks.append(self._check_tcp("minecraft_server", self.config.bot.host, self.config.bot.port, required=True))
        ok = all(c.status != "fail" for c in checks)
        return PreflightReport(ok=ok, checks=checks)

    def run_screenshot_smoke_test(self, output_path: str = "") -> ScreenshotSmokeReport:
        """Ask the live bridge for one screenshot and verify Python can read it."""
        requested_path = output_path or self._default_screenshot_smoke_path()
        os.makedirs(os.path.dirname(os.path.abspath(requested_path)), exist_ok=True)
        report = ScreenshotSmokeReport(
            bridge_host=self.config.bot.bridge_host,
            bridge_port=self.config.bot.bridge_port,
            requested_path=requested_path,
        )
        bridge = self.bridge_factory(self.config.bot)
        try:
            if not bridge.connect():
                report.error = "could not connect to bot bridge"
                report.remedy = f"start a screenshot-capable bridge on {report.bridge_host}:{report.bridge_port}"
                return report
            report.connected = True
            result = bridge.capture_screenshot(requested_path)
            report.bridge_response = result if isinstance(result, dict) else {"raw": str(result)}
            if not isinstance(result, dict):
                report.error = "bridge returned a non-object screenshot response"
                report.remedy = "restart the Node bridge and retry screenshot-smoke-test"
                return report
            report.capture_success = bool(result.get("success"))
            report.supported = bool(result.get("supported", report.capture_success))
            report.source = str(result.get("source", "") or "")
            report.screenshot_path = self._screenshot_path_from_capture_result(result, requested_path)
            if not report.capture_success:
                report.error = str(result.get("error", "screenshot capture failed") or "screenshot capture failed")
                report.remedy = self._screenshot_capture_remedy(result)
                return report

            status, resolved = self._local_image_status(report.screenshot_path, "")
            report.file_status = status
            report.file_exists = os.path.isfile(resolved) if resolved else False
            report.file_valid = status == "valid"
            if report.file_exists:
                try:
                    report.file_size = os.path.getsize(resolved)
                except OSError:
                    report.file_size = 0
            if not report.file_valid:
                report.error = f"screenshot file is {status}: {report.screenshot_path}"
                report.remedy = self._screenshot_file_remedy(result, status)
            return report
        except Exception as e:
            report.error = str(e)
            report.remedy = "Verify the bridge is running and retry screenshot-smoke-test"
            return report
        finally:
            try:
                bridge.disconnect()
            except Exception:
                pass

    def _default_screenshot_smoke_path(self) -> str:
        screenshot_dir = getattr(self.config, "screenshot_dir", "logs/screenshots") or "logs/screenshots"
        return os.path.join(screenshot_dir, f"smoke_{int(time.time() * 1000)}.png")

    def _screenshot_path_from_capture_result(self, result: dict, fallback: str = "") -> str:
        for key in ("screenshot_path", "path", "file", "filename", "image_path", "frame_path"):
            value = result.get(key) if isinstance(result, dict) else ""
            if isinstance(value, str) and value.strip():
                return value.strip()
        return fallback

    def _screenshot_capture_remedy(self, result: dict) -> str:
        if not result.get("supported"):
            plugin = result.get("screenshot_plugin", {}) if isinstance(result.get("screenshot_plugin", {}), dict) else {}
            if plugin.get("configured") and plugin.get("error"):
                return str(plugin.get("error"))
            return "start node src/bot/bot_server.js with --screenshot-plugin or run the Docker screenshot bridge"
        return "Check bridge logs for renderer errors and retry screenshot-smoke-test"

    def _screenshot_file_remedy(self, result: dict, status: str) -> str:
        if result.get("file_exists") and status == "missing":
            return (
                "bridge reported a file, but Python cannot see it; if using Docker, mount "
                "logs/screenshots into /app/logs/screenshots"
            )
        if status == "invalid":
            return "renderer wrote a file, but it is not a PNG/JPEG/GIF/WebP image"
        return "ensure the bridge writes screenshots to a path visible from the Python process"

    def _check_success(self, inventory: dict, criteria: dict) -> bool:
        for item, count in criteria.items():
            if inventory.get(item, 0) < count:
                return False
        return True

    def _check_python_import(self, module_name: str, required: bool) -> PreflightCheck:
        if importlib.util.find_spec(module_name):
            return PreflightCheck(f"python:{module_name}", "pass", "import available")
        return PreflightCheck(
            f"python:{module_name}",
            "fail" if required else "warn",
            "missing required package" if required else "optional provider package missing",
            f"pip install {module_name}" if required else f"pip install {module_name} if using this provider",
        )

    def _check_command(self, name: str, command: list[str], required: bool) -> PreflightCheck:
        exe = shutil.which(command[0])
        if not exe:
            return PreflightCheck(name, "fail" if required else "warn", f"{command[0]} not found on PATH", f"Install {command[0]} and reopen the terminal")
        try:
            result = subprocess.run([exe] + command[1:], capture_output=True, text=True, timeout=5)
            output = (result.stdout or result.stderr).strip().splitlines()
            detail = output[0] if output else "available"
            status = "pass" if result.returncode == 0 else ("fail" if required else "warn")
            return PreflightCheck(name, status, detail)
        except Exception as e:
            return PreflightCheck(name, "fail" if required else "warn", str(e), f"Verify {command[0]} works from this shell")

    def _check_node_dependencies(self) -> PreflightCheck:
        expected = ["mineflayer", "mineflayer-pathfinder", "minecraft-data"]
        missing = [name for name in expected if not os.path.isdir(os.path.join("node_modules", name))]
        if missing:
            return PreflightCheck("node_dependencies", "fail", f"missing: {', '.join(missing)}", "run npm install")
        return PreflightCheck("node_dependencies", "pass", "mineflayer dependencies installed")

    def _check_screenshot_renderer(self) -> PreflightCheck:
        script = os.path.join("src", "bot", "screenshot_plugin_prismarine_viewer.js")
        if not os.path.exists(script):
            return PreflightCheck(
                "screenshot_renderer",
                "fail",
                f"{script} not found",
                "restore src/bot/screenshot_plugin_prismarine_viewer.js",
            )
        node = shutil.which("node")
        if not node:
            return PreflightCheck(
                "screenshot_renderer",
                "fail",
                "node not found on PATH",
                "Install Node.js 18+ and reopen the terminal",
            )
        try:
            result = subprocess.run(
                [node, script, "--check"],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except Exception as e:
            return PreflightCheck(
                "screenshot_renderer",
                "fail",
                str(e),
                "Verify node can run src/bot/screenshot_plugin_prismarine_viewer.js --check",
            )

        output = (result.stdout or result.stderr or "").strip()
        try:
            report = json.loads(output) if output else {}
        except json.JSONDecodeError:
            status = "pass" if result.returncode == 0 else "fail"
            return PreflightCheck(
                "screenshot_renderer",
                status,
                output.splitlines()[0] if output else "renderer check produced no output",
                "Run node src/bot/screenshot_plugin_prismarine_viewer.js --check",
            )

        checks = report.get("checks", []) if isinstance(report, dict) else []
        missing = [
            str(check.get("name", "unknown"))
            for check in checks
            if isinstance(check, dict) and check.get("status") != "pass"
        ]
        if result.returncode == 0 and not missing and report.get("ok"):
            return PreflightCheck("screenshot_renderer", "pass", "prismarine screenshot dependencies available")
        remedy_parts = []
        if isinstance(report, dict) and report.get("install_command"):
            remedy_parts.append(str(report["install_command"]))
        if isinstance(report, dict) and report.get("windows_hint"):
            remedy_parts.append(str(report["windows_hint"]))
        return PreflightCheck(
            "screenshot_renderer",
            "fail",
            f"missing optional renderer deps: {', '.join(missing) if missing else 'unknown'}",
            " | ".join(remedy_parts) or "Install prismarine-viewer, three, and node-canvas-webgl",
        )

    def _check_tcp(self, name: str, host: str, port: int, required: bool) -> PreflightCheck:
        try:
            with socket.create_connection((host, port), timeout=2):
                return PreflightCheck(name, "pass", f"{host}:{port} reachable")
        except Exception as e:
            remedy = (
                f"start node src/bot/bot_server.js --bridge-port {port}"
                if name == "bot_bridge"
                else "start the Minecraft server and confirm host/port"
            )
            return PreflightCheck(name, "fail" if required else "warn", f"{host}:{port} unavailable ({e})", remedy)

    def _check_bot_session(self) -> PreflightCheck:
        bridge = self.bridge_factory(self.config.bot)
        try:
            if not bridge.connect():
                return PreflightCheck(
                    "bot_session",
                    "fail",
                    "could not connect to bot bridge",
                    f"start node src/bot/bot_server.js --bridge-port {self.config.bot.bridge_port}",
                )
            health = bridge.health()
            if not health.get("success"):
                detail = health.get("error", "bridge did not return health")
                return PreflightCheck(
                    "bot_session",
                    "fail",
                    detail,
                    f"restart node src/bot/bot_server.js --bridge-port {self.config.bot.bridge_port} after the Minecraft server is running",
                )
            if not health.get("bot_ready"):
                detail = health.get("last_error") or f"bot not spawned on {health.get('mc_host', self.config.bot.host)}:{health.get('mc_port', self.config.bot.port)}"
                return PreflightCheck(
                    "bot_session",
                    "fail",
                    detail,
                    f"start the Minecraft server, then restart the bot bridge on port {self.config.bot.bridge_port}",
                )
            return PreflightCheck("bot_session", "pass", f"bot spawned as {health.get('username', self.config.bot.username)}")
        except Exception as e:
            return PreflightCheck(
                "bot_session",
                "fail",
                str(e),
                f"restart node src/bot/bot_server.js --bridge-port {self.config.bot.bridge_port} after the Minecraft server is running",
            )
        finally:
            try:
                bridge.disconnect()
            except Exception:
                pass

    def save_results(self, filename: str = "benchmark_results.json"):
        import os
        os.makedirs(self.output_dir, exist_ok=True)
        path = os.path.join(self.output_dir, filename)
        data = []
        for r in self.results:
            data.append({
                "task_id": r.task_id, "task_name": r.task_name, "status": r.status,
                "cycles": r.cycles_used, "duration_s": r.duration_s,
                "inventory": r.inventory_snapshot, "error": r.error,
                "intervention_metrics": r.intervention_metrics,
                "memory_policy_metrics": r.memory_policy_metrics,
                "log": r.session_log_path,
            })
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info(f"Results saved to {path}")

    def save_policy_skill_benchmark_ablation_report(
        self,
        report: PolicySkillBenchmarkAblationReport,
        filename: str = "policy_skill_benchmark_ablation.json",
    ):
        os.makedirs(self.output_dir, exist_ok=True)
        path = os.path.join(self.output_dir, filename)
        data = {
            "disabled_passed_count": report.disabled_passed_count,
            "enabled_passed_count": report.enabled_passed_count,
            "helped_count": report.helped_count,
            "cases": [asdict(case) for case in report.cases],
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info(f"Policy-skill benchmark ablation saved to {path}")

    def save_skill_memory_benchmark_ablation_report(
        self,
        report: SkillMemoryBenchmarkAblationReport,
        filename: str = "skill_memory_benchmark_ablation.json",
    ):
        os.makedirs(self.output_dir, exist_ok=True)
        path = os.path.join(self.output_dir, filename)
        data = {
            "baseline_passed_count": report.baseline_passed_count,
            "enabled_passed_count": report.enabled_passed_count,
            "changed_count": report.changed_count,
            "helped_count": report.helped_count,
            "cases": [asdict(case) for case in report.cases],
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info(f"Skill-memory benchmark ablation saved to {path}")

    def save_visual_action_benchmark_ablation_report(
        self,
        report: VisualActionBenchmarkAblationReport,
        filename: str = "visual_action_benchmark_ablation.json",
    ):
        os.makedirs(self.output_dir, exist_ok=True)
        path = os.path.join(self.output_dir, filename)
        data = {
            "disabled_passed_count": report.disabled_passed_count,
            "enabled_passed_count": report.enabled_passed_count,
            "changed_count": report.changed_count,
            "helped_count": report.helped_count,
            "cases": [asdict(case) for case in report.cases],
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info(f"Visual-action benchmark ablation saved to {path}")

    def save_mixed_policy_benchmark_ablation_report(
        self,
        report: MixedPolicyBenchmarkAblationReport,
        filename: str = "mixed_policy_benchmark_ablation.json",
    ):
        os.makedirs(self.output_dir, exist_ok=True)
        path = os.path.join(self.output_dir, filename)
        data = {
            "patch_paths": list(report.patch_paths),
            "baseline_passed_count": report.baseline_passed_count,
            "patched_passed_count": report.patched_passed_count,
            "changed_count": report.changed_count,
            "helped_count": report.helped_count,
            "control_changed_count": report.control_changed_count,
            "policy_decision_report": dict(report.policy_decision_report),
            "cases": [asdict(case) for case in report.cases],
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info(f"Mixed-policy benchmark ablation saved to {path}")

    def save_skill_memory_quality_preflight_report(
        self,
        report: dict,
        filename: str = "skill_memory_quality_preflight.json",
    ):
        path = filename
        if not os.path.isabs(path) and not os.path.dirname(path):
            os.makedirs(self.output_dir, exist_ok=True)
            path = os.path.join(self.output_dir, path)
        else:
            parent = os.path.dirname(path)
            if parent:
                os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        logger.info(f"Skill-memory quality preflight saved to {path}")

    def save_action_value_transition_preflight_report(
        self,
        report: dict,
        filename: str = "action_value_transition_preflight.json",
    ):
        path = filename
        if not os.path.isabs(path) and not os.path.dirname(path):
            os.makedirs(self.output_dir, exist_ok=True)
            path = os.path.join(self.output_dir, path)
        else:
            parent = os.path.dirname(path)
            if parent:
                os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        logger.info(f"Action-value transition preflight saved to {path}")

    def save_knowledge_correction_preflight_report(
        self,
        report: dict,
        filename: str = "knowledge_correction_preflight.json",
    ):
        path = filename
        if not os.path.isabs(path) and not os.path.dirname(path):
            os.makedirs(self.output_dir, exist_ok=True)
            path = os.path.join(self.output_dir, path)
        else:
            parent = os.path.dirname(path)
            if parent:
                os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        logger.info(f"Knowledge-correction preflight saved to {path}")

    def save_knowledge_correction_ablation_report(
        self,
        report: dict,
        filename: str = "knowledge_correction_ablation.json",
    ):
        path = filename
        if not os.path.isabs(path) and not os.path.dirname(path):
            os.makedirs(self.output_dir, exist_ok=True)
            path = os.path.join(self.output_dir, path)
        else:
            parent = os.path.dirname(path)
            if parent:
                os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        logger.info(f"Knowledge-correction ablation saved to {path}")

    def save_coach_style_preflight_report(
        self,
        report: dict,
        filename: str = "coach_style_preflight.json",
    ):
        path = filename
        if not os.path.isabs(path) and not os.path.dirname(path):
            os.makedirs(self.output_dir, exist_ok=True)
            path = os.path.join(self.output_dir, path)
        else:
            parent = os.path.dirname(path)
            if parent:
                os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        logger.info(f"Coach-style preflight saved to {path}")

    def save_skill_runtime_default_preflight_report(
        self,
        report: dict,
        filename: str = "skill_runtime_default_preflight.json",
    ):
        path = filename
        if not os.path.isabs(path) and not os.path.dirname(path):
            os.makedirs(self.output_dir, exist_ok=True)
            path = os.path.join(self.output_dir, path)
        else:
            parent = os.path.dirname(path)
            if parent:
                os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        logger.info(f"Skill runtime-default preflight saved to {path}")

    def save_skill_lifecycle_report(
        self,
        report: dict,
        filename: str = "skill_lifecycle_report.json",
    ):
        path = filename
        if not os.path.isabs(path) and not os.path.dirname(path):
            os.makedirs(self.output_dir, exist_ok=True)
            path = os.path.join(self.output_dir, path)
        else:
            parent = os.path.dirname(path)
            if parent:
                os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        logger.info(f"Skill lifecycle report saved to {path}")

    def save_skill_runtime_default_gate_report(
        self,
        report: dict,
        filename: str = "skill_runtime_default_gate.json",
    ):
        path = filename
        if not os.path.isabs(path) and not os.path.dirname(path):
            os.makedirs(self.output_dir, exist_ok=True)
            path = os.path.join(self.output_dir, path)
        else:
            parent = os.path.dirname(path)
            if parent:
                os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        logger.info(f"Skill runtime-default gate saved to {path}")

    def print_summary(self):
        total = len(self.results)
        passed = sum(1 for r in self.results if r.status == "pass")
        failed = sum(1 for r in self.results if r.status == "fail")
        errors = sum(1 for r in self.results if r.status == "error")
        print(f"\nBenchmark Summary: {passed}/{total} passed, {failed} failed, {errors} errors")
        for r in self.results:
            icon = "+" if r.status == "pass" else "x" if r.status == "fail" else "!"
            interventions = r.intervention_metrics.get("policy_intervention_count", 0) if r.intervention_metrics else 0
            visual_actions = r.intervention_metrics.get("visual_action_intervention_count", 0) if r.intervention_metrics else 0
            metric_parts = []
            if interventions:
                metric_parts.append(f"interventions={interventions}")
            if visual_actions:
                metric_parts.append(f"visual_actions={visual_actions}")
            metric_text = f", {', '.join(metric_parts)}" if metric_parts else ""
            print(f"  [{icon}] {r.task_id} {r.task_name}: {r.status} ({r.duration_s}s{metric_text})")

    def print_policy_skill_benchmark_ablation_report(self, report: PolicySkillBenchmarkAblationReport):
        total = len(report.cases)
        print("\nPolicy Skill Benchmark Ablation")
        print(f"  disabled passed: {report.disabled_passed_count}/{total}")
        print(f"  enabled passed:  {report.enabled_passed_count}/{total}")
        print(f"  enabled helped:  {report.helped_count}/{total}")
        for case in report.cases:
            marker = "+" if case.enabled_helped else "=" if case.disabled_status == case.enabled_status else "~"
            print(f"  [{marker}] {case.task_id} {case.task_name}")
            print(f"      disabled: {case.disabled_status} ({case.disabled_duration_s}s), interventions={case.disabled_interventions}")
            print(
                f"      enabled:  {case.enabled_status} ({case.enabled_duration_s}s), "
                f"interventions={case.enabled_interventions}, success_rate={case.enabled_success_rate:.2f}"
            )

    def print_skill_memory_benchmark_ablation_report(self, report: SkillMemoryBenchmarkAblationReport):
        total = len(report.cases)
        print("\nSkill Memory Benchmark Ablation")
        print(f"  baseline passed: {report.baseline_passed_count}/{total}")
        print(f"  enabled passed:  {report.enabled_passed_count}/{total}")
        print(f"  changed:         {report.changed_count}/{total}")
        print(f"  enabled helped:  {report.helped_count}/{total}")
        for case in report.cases:
            marker = "+" if case.enabled_helped else "~" if case.enabled_changed else "="
            print(f"  [{marker}] {case.task_id} {case.task_name}")
            print(
                f"      baseline: {case.baseline_status} ({case.baseline_duration_s}s), "
                f"skill_memory_hints={case.baseline_skill_memory_hints}"
            )
            print(
                f"      enabled:  {case.enabled_status} ({case.enabled_duration_s}s), "
                f"skill_memory_hints={case.enabled_skill_memory_hints}"
            )

    def print_skill_memory_quality_preflight_report(self, report: dict):
        print("\nSkill Memory Quality Benchmark Preflight")
        print(f"  suite: {report.get('suite', 'm1')}")
        print(f"  readiness: {report.get('readiness', 'unknown')}")
        print(f"  decision: {report.get('decision', 'unknown')}")
        print(f"  reason: {report.get('reason', '')}")
        print(
            "  inputs: "
            f"feedback={report.get('feedback_count', 0)}, "
            f"gates={report.get('gate_count', 0)}, "
            f"cases={report.get('case_count', 0)}, "
            f"skill_dir={report.get('skill_storage_path', '')}"
        )
        print(
            "  feedback: "
            f"policy_hints={report.get('feedback_policy_hint_count', 0)}, "
            f"localized_items={report.get('feedback_hint_quality_item_count', 0)}"
        )
        print(
            "  ablation: "
            f"changed={report.get('changed_count', 0)}, "
            f"quality_policy_applications={report.get('quality_policy_application_count', 0)}"
        )
        if report.get("missing"):
            print(f"  missing: {', '.join(report.get('missing', []))}")
        for gate in report.get("gate_reports", [])[:6]:
            marker = "+" if gate.get("readiness") == "approved" else "x" if gate.get("readiness") == "rejected" else "!"
            print(
                f"  [{marker}] gate {gate.get('path')}: {gate.get('readiness')} "
                f"approved={gate.get('approved_count', 0)} review={gate.get('review_count', 0)} "
                f"rejected={gate.get('rejected_count', 0)}"
            )
            if gate.get("reason"):
                print(f"      {gate.get('reason')}")
        for check in report.get("checks", [])[:10]:
            marker = "+" if check.get("status") == "pass" else "x" if check.get("status") == "fail" else "!"
            print(f"  [{marker}] {check.get('kind')} {check.get('source')}: {check.get('detail')}")
        for case in report.get("quality_ablation", {}).get("cases", [])[:6]:
            marker = "~" if case.get("changed") else "="
            if case.get("quality_policy_application_count", 0):
                marker = "+"
            print(
                f"  [{marker}] {case.get('id')}: family={case.get('task_family') or 'unknown'} "
                f"apps={case.get('quality_policy_application_count', 0)} "
                f"promoted={len(case.get('promoted', []))} demoted={len(case.get('demoted', []))}"
            )
        for error in report.get("errors", []):
            print(f"  error: {error}")

    def print_skill_lifecycle_report(self, report: dict):
        print("\nSkill Lifecycle Report")
        if report.get("goal"):
            print(f"  goal: {report.get('goal')}")
        if report.get("task_family"):
            print(f"  task family: {report.get('task_family')}")
        print(f"  skill dir: {report.get('skill_storage_path', '')}")
        print(
            f"  skills: {report.get('skill_count', 0)} "
            f"({report.get('custom_skill_count', 0)} custom), "
            f"ready/review/blocked: "
            f"{report.get('ready_count', 0)}/"
            f"{report.get('review_count', 0)}/"
            f"{report.get('blocked_count', 0)}"
        )
        print(f"  runtime default candidates: {report.get('runtime_default_candidate_count', 0)}")
        stage_counts = report.get("stage_counts", {}) if isinstance(report.get("stage_counts", {}), dict) else {}
        if stage_counts:
            parts = [f"{key}={value}" for key, value in sorted(stage_counts.items())]
            print(f"  lifecycle stages: {', '.join(parts)}")
        if report.get("issue_counts"):
            parts = [f"{key}={value}" for key, value in sorted(report.get("issue_counts", {}).items())]
            print(f"  issues: {', '.join(parts)}")
        if report.get("policy_hints"):
            print(f"  policy hints: {', '.join(report.get('policy_hints', []))}")
        for skill in report.get("skills", [])[:20]:
            marker = "+" if skill.get("readiness") == "ready" else "x" if skill.get("readiness") == "blocked" else "!"
            candidate = " runtime_default_candidate" if skill.get("runtime_default_candidate") else ""
            print(
                f"  [{marker}] {skill.get('name')} readiness={skill.get('readiness')} "
                f"gate={skill.get('gate_readiness')} memories={skill.get('memory_count', 0)}"
                f"{candidate}"
            )
            stages = skill.get("lifecycle_stages", {})
            if stages:
                parts = [f"{key}:{value}" for key, value in sorted(stages.items())]
                print(f"      stages: {', '.join(parts)}")
            if skill.get("issues"):
                print(f"      issues: {', '.join(skill.get('issues', []))}")
            if skill.get("recommendations"):
                print(f"      recommendations: {', '.join(skill.get('recommendations', []))}")
        for error in report.get("errors", []):
            print(f"  error: {error}")

    def print_skill_runtime_default_gate_report(self, report: dict):
        print("\nSkill Runtime Default Gate")
        if report.get("target_task_family"):
            print(f"  task family: {report.get('target_task_family')}")
        print(f"  readiness: {report.get('readiness', 'unknown')}")
        print(f"  decision: {report.get('decision', 'unknown')}")
        print(f"  reason: {report.get('reason', '')}")
        print(
            "  inputs: "
            f"lifecycle={report.get('lifecycle_report_count', 0)}, "
            f"transfer_gates={report.get('transfer_gate_count', 0)}, "
            f"quality_gates={report.get('quality_gate_count', 0)}"
        )
        print(
            "  candidates: "
            f"approved={report.get('approved_candidate_count', 0)}, "
            f"review={report.get('review_candidate_count', 0)}, "
            f"rejected={report.get('rejected_candidate_count', 0)}, "
            f"runtime_default={report.get('runtime_default_candidate_count', 0)}"
        )
        print(
            "  gates: "
            f"transfer={report.get('transfer_gate_readiness', 'unknown')}, "
            f"quality={report.get('quality_gate_readiness', 'unknown')}"
        )
        if report.get("missing"):
            print(f"  missing: {', '.join(report.get('missing', []))}")
        for candidate in report.get("candidates", [])[:10]:
            marker = "+" if candidate.get("candidate_readiness") == "approved" else (
                "x" if candidate.get("candidate_readiness") == "rejected" else "!"
            )
            print(
                f"  [{marker}] {candidate.get('skill')} ({candidate.get('task_family') or 'any'}): "
                f"{candidate.get('candidate_readiness')} "
                f"lifecycle={candidate.get('skill_readiness')} "
                f"quality={candidate.get('quality_readiness')}"
            )
            if candidate.get("reason"):
                print(f"      {candidate.get('reason')}")
        for check in report.get("checks", [])[:12]:
            marker = "+" if check.get("status") == "pass" else "x" if check.get("status") == "fail" else "!"
            print(f"  [{marker}] {check.get('kind')} {check.get('source')}: {check.get('detail')}")
        if report.get("policy_hints"):
            print(f"  policy hints: {', '.join(report.get('policy_hints', []))}")
        for error in report.get("errors", []):
            print(f"  error: {error}")

    def print_skill_runtime_default_preflight_report(self, report: dict):
        print("\nSkill Runtime Default Benchmark Preflight")
        print(f"  suite: {report.get('suite', 'm1')}")
        print(f"  readiness: {report.get('readiness', 'unknown')}")
        print(f"  decision: {report.get('decision', 'unknown')}")
        print(f"  reason: {report.get('reason', '')}")
        print(
            "  inputs: "
            f"gates={report.get('gate_count', 0)}, "
            f"candidates={report.get('candidate_count', 0)}, "
            f"benchmark_tasks={report.get('benchmark_task_count', 0)}, "
            f"skill_dir={report.get('skill_storage_path', '')}"
        )
        print(
            "  candidates: "
            f"approved={report.get('approved_candidate_count', 0)}, "
            f"review={report.get('review_candidate_count', 0)}, "
            f"rejected={report.get('rejected_candidate_count', 0)}"
        )
        approved_families = [family or "any" for family in report.get("approved_task_families", [])]
        print(
            "  families: "
            f"benchmark={', '.join(report.get('benchmark_task_families', [])) or 'none'}, "
            f"approved={', '.join(approved_families) or 'none'}, "
            f"covered={', '.join(report.get('covered_task_families', [])) or 'none'}"
        )
        if report.get("uncovered_task_families"):
            print(f"  uncovered: {', '.join(report.get('uncovered_task_families', []))}")
        if report.get("missing"):
            print(f"  missing: {', '.join(report.get('missing', []))}")
        for gate in report.get("gate_reports", [])[:6]:
            marker = "+" if gate.get("readiness") == "approved" else "x" if gate.get("readiness") == "rejected" else "!"
            print(
                f"  [{marker}] gate {gate.get('path')}: {gate.get('readiness')} "
                f"target={gate.get('target_task_family') or 'any'} "
                f"approved={gate.get('approved_candidate_count', 0)}"
            )
            if gate.get("reason"):
                print(f"      {gate.get('reason')}")
        for candidate in report.get("candidates", [])[:10]:
            marker = "+" if candidate.get("candidate_readiness") == "approved" else (
                "x" if candidate.get("candidate_readiness") == "rejected" else "!"
            )
            print(
                f"  [{marker}] {candidate.get('skill') or 'unknown'} "
                f"({candidate.get('task_family') or 'any'}): {candidate.get('candidate_readiness')}"
            )
            if candidate.get("reason"):
                print(f"      {candidate.get('reason')}")
        for check in report.get("checks", [])[:12]:
            marker = "+" if check.get("status") == "pass" else "x" if check.get("status") == "fail" else "!"
            print(f"  [{marker}] {check.get('kind')} {check.get('source')}: {check.get('detail')}")
        for error in report.get("errors", []):
            print(f"  error: {error}")

    def print_action_value_transition_preflight_report(self, report: dict):
        print("\nAction Value Transition Benchmark Preflight")
        print(f"  suite: {report.get('suite', 'm1')}")
        print(f"  readiness: {report.get('readiness', 'unknown')}")
        print(f"  decision: {report.get('decision', 'unknown')}")
        print(f"  reason: {report.get('reason', '')}")
        print(
            "  inputs: "
            f"feedback={report.get('feedback_count', 0)}, "
            f"transition_gates={report.get('transition_gate_count', 0)}, "
            f"evaluator_reports={report.get('transition_evaluator_report_count', 0)}"
        )
        print(
            "  feedback: "
            f"action_items={report.get('action_value_item_count', 0)}, "
            f"transition_items={report.get('transition_item_count', 0)}, "
            f"trusted_transition_items={report.get('trusted_transition_item_count', 0)}, "
            f"low_confidence_items={report.get('low_confidence_transition_item_count', 0)}"
        )
        print(
            "  readiness: "
            f"gate={report.get('transition_gate_readiness', 'unknown')}, "
            f"evaluator={report.get('transition_evaluator_readiness', 'unknown')}"
        )
        if report.get("missing"):
            print(f"  missing: {', '.join(report.get('missing', []))}")
        for gate in report.get("transition_gate_reports", [])[:6]:
            marker = "+" if gate.get("readiness") == "approved" else "x" if gate.get("readiness") == "rejected" else "!"
            print(
                f"  [{marker}] transition gate {gate.get('path')}: {gate.get('readiness')} "
                f"trusted_items={gate.get('trusted_item_count', 0)} "
                f"trusted_attempts={gate.get('trusted_transition_count', 0)}"
            )
            if gate.get("reason"):
                print(f"      {gate.get('reason')}")
        for evaluator in report.get("transition_evaluator_reports", [])[:6]:
            marker = "+" if evaluator.get("readiness") == "approved" else "x" if evaluator.get("readiness") == "rejected" else "!"
            print(
                f"  [{marker}] evaluator {evaluator.get('path')}: {evaluator.get('readiness')} "
                f"evaluated={evaluator.get('evaluated_count', 0)} "
                f"agreement={evaluator.get('agreement_rate', 0.0)}"
            )
            if evaluator.get("reason"):
                print(f"      {evaluator.get('reason')}")
        for check in report.get("checks", [])[:10]:
            marker = "+" if check.get("status") == "pass" else "x" if check.get("status") == "fail" else "!"
            print(f"  [{marker}] {check.get('kind')} {check.get('source')}: {check.get('detail')}")
        for error in report.get("errors", []):
            print(f"  error: {error}")

    def print_knowledge_correction_preflight_report(self, report: dict):
        print("\nKnowledge Correction Benchmark Preflight")
        print(f"  suite: {report.get('suite', 'm1')}")
        print(f"  readiness: {report.get('readiness', 'unknown')}")
        print(f"  decision: {report.get('decision', 'unknown')}")
        print(f"  reason: {report.get('reason', '')}")
        print(
            "  inputs: "
            f"feedback={report.get('feedback_count', 0)}, "
            f"gates={report.get('gate_count', 0)}, "
            f"cases={report.get('case_count', 0)}"
        )
        print(
            "  corrections: "
            f"dependency={report.get('dependency_correction_count', 0)}, "
            f"failed_memories={report.get('failure_action_memory_count', 0)}, "
            f"policy_hints={report.get('policy_hint_count', 0)}"
        )
        print(
            "  coverage: "
            f"matched_cases={report.get('matched_case_count', 0)}/{report.get('case_count', 0)}, "
            f"rate={report.get('coverage_rate', 0.0)}, "
            f"matched_dependency={report.get('matched_dependency_correction_count', 0)}, "
            f"matched_failed_memories={report.get('matched_failure_action_memory_count', 0)}"
        )
        if report.get("missing"):
            print(f"  missing: {', '.join(report.get('missing', []))}")
        for gate in report.get("gate_reports", [])[:6]:
            marker = "+" if gate.get("readiness") == "approved" else "x" if gate.get("readiness") == "rejected" else "!"
            print(
                f"  [{marker}] gate {gate.get('path')}: {gate.get('readiness')} "
                f"ready_logs={gate.get('ready_log_count', 0)} corrections={gate.get('correction_count', 0)}"
            )
            if gate.get("reason"):
                print(f"      {gate.get('reason')}")
        for check in report.get("checks", [])[:10]:
            marker = "+" if check.get("status") == "pass" else "x" if check.get("status") == "fail" else "!"
            print(f"  [{marker}] {check.get('kind')} {check.get('source')}: {check.get('detail')}")
        for case in report.get("cases", [])[:8]:
            marker = "+" if case.get("matched") else "="
            signatures = ", ".join(case.get("matched_signatures", [])[:4])
            suffix = f" signatures={signatures}" if signatures else ""
            print(
                f"  [{marker}] {case.get('id')}: family={case.get('task_family') or 'unknown'} "
                f"dependency={case.get('dependency_correction_match_count', 0)} "
                f"failed_memories={case.get('failure_action_memory_match_count', 0)}"
                f"{suffix}"
            )
        for error in report.get("errors", []):
            print(f"  error: {error}")

    def print_knowledge_correction_ablation_report(self, report: dict):
        print("\nKnowledge Correction Context Ablation")
        print(f"  suite: {report.get('suite', 'm1')}")
        print(f"  readiness: {report.get('readiness', 'unknown')}")
        print(f"  decision: {report.get('decision', 'unknown')}")
        print(f"  reason: {report.get('reason', '')}")
        print(
            "  inputs: "
            f"feedback={len(report.get('feedback_paths', []))}, "
            f"gates={len(report.get('gate_paths', []))}, "
            f"gate={report.get('gate_readiness', 'unknown')}"
        )
        print(
            "  context changes: "
            f"changed={report.get('changed_count', 0)}/{report.get('case_count', 0)}, "
            f"enabled_context={report.get('enabled_context_count', 0)}, "
            f"dependency_hints={report.get('dependency_context_count', 0)}, "
            f"failed_action_hints={report.get('failure_memory_context_count', 0)}"
        )
        preflight = report.get("preflight", {}) if isinstance(report.get("preflight", {}), dict) else {}
        if preflight:
            print(
                "  preflight: "
                f"{preflight.get('readiness', 'unknown')} "
                f"matched={preflight.get('matched_case_count', 0)}/{preflight.get('case_count', 0)}"
            )
        for case in report.get("cases", [])[:8]:
            marker = "+" if case.get("changed") else "="
            print(
                f"  [{marker}] {case.get('id')}: "
                f"enabled_chars={case.get('enabled_context_chars', 0)} "
                f"dependency={case.get('dependency_context_count', 0)} "
                f"failed_memories={case.get('failure_memory_context_count', 0)}"
            )
            preview = str(case.get("enabled_context_preview", "") or "")
            if preview:
                first_line = preview.splitlines()[0] if preview.splitlines() else preview
                print(f"      {first_line[:220]}")
        for error in report.get("errors", []):
            print(f"  error: {error}")

    def print_coach_style_preflight_report(self, report: dict):
        print("\nCoach Style Benchmark Preflight")
        print(f"  suite: {report.get('suite', 'm1')}")
        print(f"  styles: {', '.join(report.get('styles', [])) or 'none'}")
        print(f"  readiness: {report.get('readiness', 'unknown')}")
        print(f"  decision: {report.get('decision', 'unknown')}")
        print(f"  reason: {report.get('reason', '')}")
        print(
            "  evidence: "
            f"ablations={len(report.get('ablation_sources', []))}, "
            f"gates={report.get('gate_count', 0)}, "
            f"cases={report.get('case_count', 0)}, "
            f"score_changed={report.get('score_changed_count', 0)}"
        )
        if report.get("approved_styles"):
            print(f"  approved styles: {', '.join(report.get('approved_styles', []))}")
        for source in report.get("ablation_sources", [])[:6]:
            print(
                f"  ablation {source.get('source')}: "
                f"cases={source.get('case_count', 0)}, "
                f"score_changed={source.get('score_changed_count', 0)}"
            )
        for gate in report.get("gate_reports", [])[:6]:
            print(
                f"  gate {gate.get('path')}: {gate.get('readiness')} "
                f"covers_requested={gate.get('covers_requested')}"
            )
        if report.get("missing"):
            print(f"  missing: {', '.join(report.get('missing', []))}")
        for error in report.get("errors", []):
            print(f"  error: {error}")

    def print_visual_action_benchmark_ablation_report(self, report: VisualActionBenchmarkAblationReport):
        total = len(report.cases)
        print("\nVisual Action Benchmark Ablation")
        print(f"  disabled passed: {report.disabled_passed_count}/{total}")
        print(f"  enabled passed:  {report.enabled_passed_count}/{total}")
        print(f"  changed:         {report.changed_count}/{total}")
        print(f"  enabled helped:  {report.helped_count}/{total}")
        for case in report.cases:
            marker = "+" if case.enabled_helped else "~" if case.enabled_changed else "="
            phase_text = f", phases={case.enabled_phases}" if case.enabled_phases else ""
            print(f"  [{marker}] {case.task_id} {case.task_name}")
            print(
                f"      disabled: {case.disabled_status} ({case.disabled_duration_s}s), "
                f"visual_actions={case.disabled_visual_actions}"
            )
            print(
                f"      enabled:  {case.enabled_status} ({case.enabled_duration_s}s), "
                f"visual_actions={case.enabled_visual_actions}{phase_text}"
            )

    def print_mixed_policy_benchmark_ablation_report(self, report: MixedPolicyBenchmarkAblationReport):
        total = len(report.cases)
        decision_report = report.policy_decision_report or {}
        print("\nMixed Policy Benchmark Ablation")
        print(f"  baseline passed: {report.baseline_passed_count}/{total}")
        print(f"  patched passed:  {report.patched_passed_count}/{total}")
        print(f"  changed:         {report.changed_count}/{total}")
        print(f"  control changed: {report.control_changed_count}/{total}")
        print(f"  patched helped:  {report.helped_count}/{total}")
        print(
            "  patch decision preview: "
            f"actions={decision_report.get('action_changed_count', 0)}/"
            f"{decision_report.get('action_case_count', 0)}, "
            f"templates={decision_report.get('template_changed_count', 0)}/"
            f"{decision_report.get('template_case_count', 0)}, "
            f"candidates={decision_report.get('candidate_changed_count', 0)}/"
            f"{decision_report.get('candidate_case_count', 0)}"
        )
        for case in report.cases:
            marker = "+" if case.patched_helped else "~" if case.patched_changed else "="
            baseline_control = case.baseline_control_policy or {}
            patched_control = case.patched_control_policy or {}
            baseline_preferred = baseline_control.get("preferred_control_counts", {})
            patched_preferred = patched_control.get("preferred_control_counts", {})
            fallback_count = patched_control.get("fallback_count", 0)
            print(f"  [{marker}] {case.task_id} {case.task_name}")
            print(f"      baseline: {case.baseline_status} ({case.baseline_duration_s}s), control={baseline_preferred}")
            print(
                f"      patched:  {case.patched_status} ({case.patched_duration_s}s), "
                f"control={patched_preferred}, fallbacks={fallback_count}"
            )

    def print_visual_action_ablation_report(self, report: VisualActionAblationReport):
        total = len(report.cases)
        print("\nVisual Action Grounding Ablation")
        print(f"  passed:  {report.passed_count}/{total}")
        print(f"  changed: {report.changed_count}/{total}")
        print(f"  helped:  {report.helped_count}/{total}")
        for case in report.cases:
            marker = "+" if case.passed and case.changed else "=" if case.passed else "!"
            phase_text = f", phase={case.expected_phase}" if case.expected_phase else ""
            print(
                f"  [{marker}] {case.case_id} {case.case_name}: "
                f"changed={case.changed}, interventions={case.enabled_interventions}{phase_text}"
            )

    def print_preflight(self, report: PreflightReport):
        print("\nBenchmark Preflight")
        for check in report.checks:
            icon = "+" if check.status == "pass" else "!" if check.status == "warn" else "x"
            print(f"  [{icon}] {check.name}: {check.status} - {check.detail}")
            if check.remedy:
                print(f"      remedy: {check.remedy}")
        print(f"\nReady: {'yes' if report.ok else 'no'}")

    def print_screenshot_smoke_report(self, report: ScreenshotSmokeReport):
        print("\nScreenshot Smoke Test")
        print(f"  bridge: {report.bridge_host}:{report.bridge_port}")
        print(f"  requested path: {report.requested_path}")
        print(f"  connected: {'yes' if report.connected else 'no'}")
        print(f"  capture: {'pass' if report.capture_success else 'fail'}")
        print(f"  supported: {'yes' if report.supported else 'no'}")
        if report.source:
            print(f"  source: {report.source}")
        if report.screenshot_path:
            print(f"  screenshot path: {report.screenshot_path}")
        print(f"  file: {report.file_status}, exists={report.file_exists}, valid={report.file_valid}, size={report.file_size}")
        if report.error:
            print(f"  error: {report.error}")
        if report.remedy:
            print(f"  remedy: {report.remedy}")
        print(f"\nReady: {'yes' if report.ok else 'no'}")

    def print_ingestion_report(self, report: BenchmarkIngestionReport):
        print("\nBenchmark Ingestion")
        print(f"  processed: {report.processed_results}")
        print(f"  skipped: {report.skipped_results}")
        print(f"  experience atoms: {report.experience_atoms}")
        print(f"  skill candidates queued: {report.skill_candidates}")
        if report.promotion_reports:
            readiness = report.promotion_readiness
            print(
                "  promotion readiness: "
                f"approved={readiness.get('approved', 0)}, "
                f"rejected={readiness.get('rejected', 0)}, "
                f"unknown={readiness.get('unknown', 0)}"
            )
            print(f"  promotion statuses: {report.promotion_statuses}")
        for candidate_id in report.queued_candidate_ids:
            print(f"    - {candidate_id}")
        for error in report.errors:
            print(f"  error: {error}")

    def print_scheduling_ablation_report(self, report: SchedulingAblationReport):
        total = len(report.cases)
        print("\nScheduling Ablation")
        print(f"  changed by causal memory: {report.changed_count}/{total}")
        print(f"  causal helped expected case: {report.helped_count}/{total}")
        for case in report.cases:
            marker = "+" if case.causal_helped else "~" if case.changed else "="
            print(f"  [{marker}] {case.case_id} {case.case_name}")
            if case.source:
                print(f"      source: {case.source}")
            if case.action_type or case.outcome:
                print(f"      event: {case.outcome or 'unknown'} {case.action_type or 'action'}")
            if case.repeat_count > 1:
                print(f"      repeats: {case.repeat_count}")
            if case.value_score:
                value_line = f"{case.value_score:.2f}"
                if case.repeat_count > 1 and case.avg_value_score:
                    value_line += f" max / {case.avg_value_score:.2f} avg"
                print(f"      value: {value_line}")
            print(f"      direct-only: {case.direct_only_task or 'none'}")
            print(f"      causal-on:   {case.causal_enabled_task or 'none'}")
            if case.causal_tags:
                print(f"      causal tags: {', '.join(case.causal_tags)}")

    def print_coach_style_ablation_report(self, report: CoachStyleAblationReport):
        total = len(report.cases)
        print("\nCoach Style Ablation")
        print(f"  changed top goal: {report.changed_count}/{total}")
        print(f"  changed score: {report.score_changed_count}/{total}")
        if report.style_changed_counts:
            print(
                "  changed by style: "
                + ", ".join(f"{style}={count}" for style, count in sorted(report.style_changed_counts.items()))
            )
        for case in report.cases:
            marker = "+" if case.changed else "~" if case.score_delta else "="
            print(f"  [{marker}] {case.case_id} {case.case_name} style={case.style}")
            if case.source:
                print(f"      source: {case.source}")
            print(f"      baseline: {case.baseline_goal or 'none'} ({case.baseline_category}, {case.baseline_score:.2f})")
            print(f"      styled:   {case.styled_goal or 'none'} ({case.styled_category}, {case.styled_score:.2f}, delta={case.score_delta:.2f})")
            coach_reasons = [reason for reason in case.styled_reasons if str(reason).startswith("coach:")]
            if coach_reasons:
                print(f"      coach reasons: {', '.join(coach_reasons[:5])}")

    def print_coach_style_gate_report(self, report: dict):
        print("\nCoach Style Gate")
        print(f"  target: {report.get('target', 'coach_style_curriculum_bias')}")
        print(f"  readiness: {report.get('readiness')} ({report.get('decision')})")
        print(f"  reason: {report.get('reason')}")
        print(
            "  evidence: "
            f"cases={report.get('case_count', 0)}, "
            f"changed={report.get('changed_count', 0)}, "
            f"score_changed={report.get('score_changed_count', 0)}"
        )
        if report.get("approved_styles"):
            print(f"  approved styles: {', '.join(report.get('approved_styles', []))}")
        if report.get("review_styles"):
            for item in report.get("review_styles", [])[:8]:
                print(f"  review style: {item.get('style')} missing={','.join(item.get('missing', []))}")
        for check in report.get("checks", [])[:10]:
            marker = "+" if check.get("status") == "pass" else "x" if check.get("status") == "fail" else "!"
            print(f"  [{marker}] {check.get('kind')} {check.get('source')}: {check.get('detail')}")
        for error in report.get("errors", []):
            print(f"  error: {error}")

    def print_visual_trace_report(self, report: VisualTraceCoverageReport):
        total = report.log_count
        print("\nVisual Trace Coverage")
        print(f"  logs ready for visual ablation: {report.ready_log_count}/{total}")
        print(f"  logs with verified screenshots: {report.screenshot_log_count}/{total}")
        print(f"  goals with visual evidence: {report.goals_with_visual_evidence_count}/{report.goal_count}")
        print(
            "  promotion candidates with visual evidence: "
            f"{report.promotion_candidates_with_visual_evidence_count}/{report.promotion_candidate_count}"
        )
        for case in report.cases:
            marker = "+" if case.ready_for_visual_ablation else "!"
            print(f"  [{marker}] {case.source_log}")
            print(
                f"      observations: {case.visual_observation_count}/{case.observation_count} visual, "
                f"screenshots={case.screenshot_count}/{case.raw_screenshot_count} verified, "
                f"missing={case.missing_screenshot_count}, invalid={case.invalid_screenshot_count}, "
                f"analyses={case.visual_analysis_count}"
            )
            print(
                f"      goals: {case.goals_with_visual_evidence}/{case.goal_count} visual; "
                f"promotion candidates: {case.promotion_candidates_with_visual_evidence}/{case.promotion_candidate_count} visual"
            )
            if case.visual_evidence_keys:
                print(f"      visual keys: {', '.join(case.visual_evidence_keys)}")
            if case.raw_screenshot_count:
                print(
                    f"      screenshots: {case.screenshot_count}/{case.raw_screenshot_count} verified, "
                    f"missing={case.missing_screenshot_count}, invalid={case.invalid_screenshot_count}"
                )
            if case.screenshot_paths:
                print(f"      screenshots: {', '.join(case.screenshot_paths[:3])}")
            if case.missing_screenshot_paths:
                print(f"      missing screenshots: {', '.join(case.missing_screenshot_paths[:3])}")
            if case.invalid_screenshot_paths:
                print(f"      invalid screenshots: {', '.join(case.invalid_screenshot_paths[:3])}")
            if case.missing_visual_goals:
                print(f"      missing visual goals: {', '.join(case.missing_visual_goals[:3])}")
        for error in report.errors:
            print(f"  error: {error}")

    def print_exploration_trace_report(self, report: ExplorationTraceReport):
        total = report.log_count
        print("\nExploration Trace Coverage")
        print(f"  logs ready for exploration review: {report.ready_log_count}/{total}")
        print(f"  observations: {report.observation_count}")
        print(f"  goals completed/failed: {report.completed_goal_count}/{report.failed_goal_count}")
        print(f"  logs with movement: {report.logs_with_movement_count}/{total}")
        print(
            "  unique discovered types: "
            f"blocks={report.unique_block_type_count}, "
            f"resources={report.unique_resource_type_count}, "
            f"entities={report.unique_entity_type_count}"
        )
        print(f"  visual observations: {report.visual_observation_count}")
        print(f"  hostile encounters: {report.hostile_encounter_count}")
        print(f"  failed actions: {report.failed_action_count}")
        feedback = self.exploration_curriculum_feedback(report)
        if report.log_count:
            print(
                "  curriculum feedback: "
                f"low_movement_logs={feedback['low_movement_log_count']}, "
                f"failure_categories={feedback['action_failure_categories']}"
            )
        for case in report.cases:
            marker = "+" if case.ready_for_exploration_review else "!"
            print(f"  [{marker}] {case.source_log}")
            print(
                f"      observations={case.observation_count}, goals={case.completed_goal_count}/{case.goal_count} completed, "
                f"actions={case.action_count}, failed_actions={case.failed_action_count}"
            )
            print(
                f"      positions={case.unique_position_count}/{case.position_count}, "
                f"path={case.path_distance:.2f}, span=({case.x_span:.2f}, {case.y_span:.2f}, {case.z_span:.2f})"
            )
            print(
                f"      discovered: blocks={len(case.unique_block_types)}, "
                f"resources={len(case.unique_resource_types)}, entities={len(case.unique_entity_types)}"
            )
            if case.unique_block_types:
                print(f"      blocks: {', '.join(case.unique_block_types[:8])}")
            if case.unique_resource_types:
                print(f"      resources: {', '.join(case.unique_resource_types[:8])}")
            if case.unique_entity_types:
                print(f"      entities: {', '.join(case.unique_entity_types[:8])}")
            print(
                f"      visual={case.visual_observation_count}, screenshots={case.screenshot_count}/{case.raw_screenshot_count}, "
                f"hostile_encounters={case.hostile_encounter_count}, danger_events={case.danger_event_count}"
            )
            if case.action_failure_categories:
                parts = [f"{key}={value}" for key, value in sorted(case.action_failure_categories.items())]
                print(f"      failure categories: {', '.join(parts)}")
            if case.multi_hop_goal_count or case.multi_step_plan_count:
                print(
                    f"      multi-hop goals={case.multi_hop_goal_count}, "
                    f"multi-step plans={case.multi_step_plan_count}"
                )
        for error in report.errors:
            print(f"  error: {error}")

    def print_world_model_report(self, report: WorldModelTraceReport):
        total = report.log_count
        print("\nWorld Model Trace")
        print(f"  logs ready for world-model review: {report.ready_log_count}/{total}")
        print(
            "  cells/frontiers/resources/dangers: "
            f"{report.unique_cell_count}/{report.frontier_count}/"
            f"{report.resource_hotspot_count}/{report.danger_cell_count}"
        )
        feedback = self.world_model_curriculum_feedback(report)
        print(
            "  curriculum feedback: "
            f"goals={len(feedback['suggested_goals'])}, "
            f"frontiers={len(feedback['frontiers'])}, "
            f"hotspots={len(feedback['resource_hotspots'])}"
        )
        for case in report.cases:
            marker = "+" if case.ready_for_world_model_review else "!"
            print(f"  [{marker}] {case.source_log}")
            print(
                f"      observations={case.observation_count}, positions={case.position_count}, "
                f"cells={case.unique_cell_count}, transitions={case.transition_count}, "
                f"frontiers={case.frontier_count}"
            )
            if case.resource_hotspots:
                preview = [
                    f"{item['resource']}@({item['cell']['x']},{item['cell']['z']})"
                    for item in case.resource_hotspots[:5]
                ]
                print(f"      resources: {', '.join(preview)}")
            if case.frontiers:
                preview = [
                    f"{item['direction']}->({item['cell']['x']},{item['cell']['z']})"
                    for item in case.frontiers[:5]
                ]
                print(f"      frontiers: {', '.join(preview)}")
            for goal in case.suggested_exploration_goals[:3]:
                print(f"      next: {goal}")
        for error in report.errors:
            print(f"  error: {error}")

    def print_world_model_feedback_gate_report(self, report: dict):
        print("\nWorld Model Feedback Gate")
        print(f"  target: {report.get('target', 'world_model_curriculum_feedback')}")
        print(f"  readiness: {report.get('readiness', 'unknown')}")
        print(f"  decision: {report.get('decision', 'unknown')}")
        print(f"  reason: {report.get('reason', '')}")
        print(
            "  evidence: "
            f"sources={report.get('source_count', 0)}, "
            f"ready_logs={report.get('ready_log_count', 0)}/{report.get('log_count', 0)}, "
            f"cells={report.get('unique_cell_count', 0)}, "
            f"frontiers={report.get('frontier_count', 0)}, "
            f"hotspots={report.get('resource_hotspot_count', 0)}, "
            f"dangers={report.get('danger_cell_count', 0)}, "
            f"actionable={report.get('actionable_item_count', 0)}"
        )
        if report.get("missing"):
            print(f"  missing: {', '.join(report.get('missing', []))}")
        if report.get("policy_hints"):
            print(f"  policy hints: {', '.join(report.get('policy_hints', []))}")
        for source in report.get("sources", [])[:8]:
            marker = "+" if source.get("ready") else "!"
            print(
                f"  [{marker}] {source.get('source')}: "
                f"ready_logs={source.get('ready_log_count', 0)}, "
                f"frontiers={source.get('frontier_count', 0)}, "
                f"hotspots={source.get('resource_hotspot_count', 0)}, "
                f"actionable={source.get('actionable_item_count', 0)}"
            )
            if source.get("reason"):
                print(f"      {source.get('reason')}")
        for check in report.get("checks", [])[:10]:
            marker = "+" if check.get("status") == "pass" else "x" if check.get("status") == "fail" else "!"
            print(f"  [{marker}] {check.get('kind')} {check.get('source')}: {check.get('detail')}")
        for error in report.get("errors", []):
            print(f"  error: {error}")

    def print_self_evolution_report(self, report: SelfEvolutionTraceReport):
        total = report.log_count
        print("\nSelf-Evolution Trace")
        print(f"  logs ready for self-evolution review: {report.ready_log_count}/{total}")
        print(
            "  monitor signals: "
            f"progress={report.progress_signal_count}, "
            f"regression={report.regression_signal_count}, "
            f"stagnation={report.stagnation_signal_count}"
        )
        print(
            "  actions: "
            f"total={report.action_count}, "
            f"failed={report.failed_action_count}, "
            f"repeated_failures={report.repeated_failure_count}, "
            f"no_progress_successes={report.no_progress_success_count}, "
            f"repeated_success_loops={report.repeated_success_loop_count}"
        )
        print(
            "  plans: "
            f"blocked={report.blocked_plan_count}, "
            f"empty={report.empty_plan_count}, "
            f"zero_action_failures={report.zero_action_failure_count}"
        )
        print(f"  relative reward delta: {report.relative_reward_delta:.3f}")
        feedback = self.self_evolution_feedback(report)
        if feedback["policy_hints"]:
            hints = [
                f"{hint['self_evolution_policy']}({hint['priority']})"
                for hint in feedback["policy_hints"][:6]
            ]
            print(f"  policy hints: {', '.join(hints)}")
        for case in report.cases:
            marker = "+" if case.ready_for_self_evolution_review else "~"
            print(f"  [{marker}] {case.source_log}")
            print(
                f"      observations={case.observation_count}, goals={case.completed_goal_count}/{case.goal_count} completed, "
                f"actions={case.action_count}, failed={case.failed_action_count}"
            )
            print(
                f"      signals: progress={case.progress_signal_count}, regression={case.regression_signal_count}, "
                f"stagnation={case.stagnation_signal_count}, reward_delta={case.relative_reward_delta:.3f}, "
                f"absolute_mean={case.absolute_reward_mean:.3f}"
            )
            if case.no_progress_success_count:
                print(
                    f"      no-progress successes={case.no_progress_success_count}, "
                    f"repeated_success_loops={case.repeated_success_loop_count}"
                )
            if case.blocked_plan_count or case.empty_plan_count:
                print(
                    f"      plan stalls: blocked={case.blocked_plan_count}, "
                    f"empty={case.empty_plan_count}, zero_action_failures={case.zero_action_failure_count}"
                )
            if case.action_failure_categories:
                print(f"      failure categories: {self._format_counts(case.action_failure_categories)}")
            if case.progress_markers:
                print(f"      progress markers: {'; '.join(case.progress_markers[:4])}")
            for recommendation in case.adaptor_recommendations[:4]:
                print(f"      adaptor: {recommendation}")
        for error in report.errors:
            print(f"  error: {error}")

    def print_plan_action_compliance_report(self, report: PlanActionComplianceReport):
        total = report.log_count
        print("\nPlan-Action Compliance Trace")
        print(f"  logs ready for plan-action review: {report.ready_log_count}/{total}")
        print(
            "  counts: "
            f"plans={report.plan_count}, actions={report.action_count}, "
            f"planned_actions={report.planned_action_count}, ordered_matches={report.ordered_match_count}"
        )
        print(
            "  gaps: "
            f"missing={report.missing_planned_action_count}, "
            f"unplanned={report.unplanned_action_count}, "
            f"order_violations={report.order_violation_count}, "
            f"empty_plans={report.empty_plan_count}, blocked_plans={report.blocked_plan_count}"
        )
        print(
            "  scores: "
            f"follow={report.plan_follow_score:.3f}, "
            f"precision={report.action_precision:.3f}, "
            f"compliance={report.compliance_score:.3f}"
        )
        feedback = self.plan_action_compliance_feedback(report)
        if feedback["policy_hints"]:
            hints = [
                f"{hint['plan_action_policy']}({hint['priority']})"
                for hint in feedback["policy_hints"][:6]
            ]
            print(f"  policy hints: {', '.join(hints)}")
        for case in report.cases:
            marker = "+" if case.ready_for_plan_action_review else "~"
            print(f"  [{marker}] {case.source_log}")
            print(
                f"      plans={case.plan_count}, actions={case.action_count}, "
                f"planned_actions={case.planned_action_count}, ordered_matches={case.ordered_match_count}"
            )
            print(
                f"      gaps: missing={case.missing_planned_action_count}, unplanned={case.unplanned_action_count}, "
                f"order_violations={case.order_violation_count}, empty={case.empty_plan_count}, blocked={case.blocked_plan_count}"
            )
            print(
                f"      scores: follow={case.plan_follow_score:.3f}, "
                f"precision={case.action_precision:.3f}, compliance={case.compliance_score:.3f}"
            )
            if case.planned_action_type_counts:
                print(f"      planned types: {self._format_counts(case.planned_action_type_counts)}")
            if case.executed_action_type_counts:
                print(f"      executed types: {self._format_counts(case.executed_action_type_counts)}")
            for example in case.mismatch_examples[:3]:
                print(
                    f"      mismatch plan#{example['plan_index']}: "
                    f"missing={example['missing']}, unplanned={example['unplanned']}, "
                    f"order_violations={example['order_violations']}"
                )
        for error in report.errors:
            print(f"  error: {error}")

    def print_terminal_commitment_report(self, report: TerminalCommitmentReport):
        print("\nTerminal Commitment Trace")
        print(f"  goals ready for terminal review: {report.ready_goal_count}/{report.goal_count}")
        print(
            "  outcomes: "
            f"verified_success={report.verified_success_count}, "
            f"unsupported_commitment={report.unsupported_commitment_count}, "
            f"post_attainment_drift={report.post_attainment_drift_count}, "
            f"missed_execution={report.missed_execution_count}, "
            f"unknown_world={report.unknown_world_count}"
        )
        print(
            "  scores: "
            f"world_completion={report.world_completion_score:.3f}, "
            f"terminal_commitment={report.terminal_commitment_score:.3f}, "
            f"unsupported_rate={report.unsupported_commitment_rate:.3f}, "
            f"drift_rate={report.post_attainment_drift_rate:.3f}"
        )
        feedback = self.terminal_commitment_feedback(report)
        if feedback["policy_hints"]:
            hints = [
                f"{hint['terminal_commitment_policy']}({hint['priority']})"
                for hint in feedback["policy_hints"][:6]
            ]
            print(f"  policy hints: {', '.join(hints)}")
        for case in report.cases:
            marker = "+" if case.ready_for_terminal_review else "~"
            world = "unknown" if case.world_complete is None else str(case.world_complete).lower()
            print(f"  [{marker}] {case.source_log} goal#{case.goal_index}: {case.goal}")
            print(
                f"      outcome={case.outcome}, world_complete={world}, "
                f"terminal_complete={str(case.terminal_reported_complete).lower()}, "
                f"source={case.verification_source}"
            )
            print(
                f"      events: observations={case.observation_count}, actions={case.action_count}, "
                f"verifications={case.verification_event_count}, planner_complete={case.planner_complete_count}"
            )
            if case.evidence:
                print(f"      evidence: {'; '.join(str(item) for item in case.evidence[:3])}")
            if case.missing:
                print(f"      missing: {'; '.join(str(item) for item in case.missing[:3])}")
            if case.reason:
                print(f"      reason: {case.reason[:180]}")
        for error in report.errors:
            print(f"  error: {error}")

    def print_action_verification_report(self, report: ActionVerificationTraceReport):
        print("\nAction Verification Trace")
        print(f"  logs ready for action verification review: {report.ready_log_count}/{report.log_count}")
        print(
            "  counts: "
            f"actions={report.action_count}, verified={report.verified_action_count}, "
            f"accepted={report.accepted_action_count}, review={report.review_action_count}, "
            f"rejected={report.rejected_action_count}"
        )
        print(
            "  gaps: "
            f"failed_without_reject={report.failed_without_reject_count}, "
            f"rejected_successes={report.rejected_success_count}, "
            f"reject_rate={report.reject_rate:.3f}, review_rate={report.review_rate:.3f}"
        )
        feedback = self.action_verification_feedback(report)
        if feedback["policy_hints"]:
            hints = [
                f"{hint['action_verification_policy']}({hint['priority']})"
                for hint in feedback["policy_hints"][:6]
            ]
            print(f"  policy hints: {', '.join(hints)}")
        for case in report.cases:
            marker = "+" if case.ready_for_action_verification_review else "~"
            print(f"  [{marker}] {case.source_log}")
            print(
                f"      actions={case.action_count}, accepted={case.accepted_action_count}, "
                f"review={case.review_action_count}, rejected={case.rejected_action_count}, "
                f"failed_without_reject={case.failed_without_reject_count}"
            )
            if case.status_counts:
                print(f"      statuses: {self._format_counts(case.status_counts)}")
            if case.rejection_reasons:
                print(f"      reject reasons: {self._format_counts(case.rejection_reasons)}")
            if case.review_reasons:
                print(f"      review reasons: {self._format_counts(case.review_reasons)}")
            for example in case.examples[:3]:
                verification = example.get("verification", {})
                print(
                    f"      example event#{example.get('event_index')}: "
                    f"{verification.get('status')} {verification.get('action_type')} - {verification.get('reason')}"
                )
        for error in report.errors:
            print(f"  error: {error}")

    def print_action_candidate_report(self, report: ActionCandidateSelectionTraceReport):
        print("\nAction Candidate Selection Trace")
        print(f"  logs ready for action candidate review: {report.ready_log_count}/{report.log_count}")
        print(
            "  counts: "
            f"actions={report.action_count}, original_rejects={report.original_reject_count}, "
            f"changed={report.changed_selection_count}, repaired_rejects={report.repaired_reject_count}, "
            f"unchanged_rejects={report.unchanged_reject_count}"
        )
        print(
            "  rates: "
            f"selection_change_rate={report.selection_change_rate:.3f}, "
            f"repaired_reject_rate={report.repaired_reject_rate:.3f}"
        )
        feedback = self.action_candidate_feedback(report)
        if feedback["policy_hints"]:
            hints = [
                f"{hint['action_candidate_policy']}({hint['priority']})"
                for hint in feedback["policy_hints"][:6]
            ]
            print(f"  policy hints: {', '.join(hints)}")
        for case in report.cases:
            marker = "+" if case.ready_for_action_candidate_review else "~"
            print(f"  [{marker}] {case.source_log}")
            print(
                f"      actions={case.action_count}, original_rejects={case.original_reject_count}, "
                f"changed={case.changed_selection_count}, repaired={case.repaired_reject_count}, "
                f"unchanged_rejects={case.unchanged_reject_count}"
            )
            if case.selected_action_type_counts:
                print(f"      selected action types: {self._format_counts(case.selected_action_type_counts)}")
            if case.repair_reasons:
                print(f"      repair reasons: {self._format_counts(case.repair_reasons)}")
            for example in case.examples[:3]:
                print(
                    f"      example event#{example.get('event_index')}: "
                    f"{example.get('original_status')} -> {example.get('selected_status')} "
                    f"{example.get('reason')}"
                )
        for error in report.errors:
            print(f"  error: {error}")

    def print_action_value_report(self, report: ActionValueTraceReport):
        print("\nAction Value Trace")
        print(f"  logs ready for action value review: {report.ready_log_count}/{report.log_count}")
        print(
            "  counts: "
            f"actions={report.action_count}, successes={report.success_count}, "
            f"failures={report.failure_count}, unknown={report.unknown_outcome_count}, "
            f"signatures={report.signature_count}"
        )
        print(
            "  rates: "
            f"success_rate={report.success_rate:.3f}, failure_rate={report.failure_rate:.3f}, "
            f"failure_corrections={report.failure_correction_pair_count}"
        )
        print(
            "  transitions: "
            f"total={report.state_transition_count}, positive={report.positive_transition_count}, "
            f"negative={report.negative_transition_count}, no_progress={report.no_progress_transition_count}, "
            f"low_confidence={report.low_confidence_transition_count}"
        )
        feedback = self.action_value_feedback(report)
        if feedback["policy_hints"]:
            hints = [
                f"{hint['action_value_policy']}({hint['priority']})"
                for hint in feedback["policy_hints"][:6]
            ]
            print(f"  policy hints: {', '.join(hints)}")
        for item in feedback["action_value_items"][:6]:
            print(
                f"  value {item.get('signature')}: "
                f"score={item.get('value_score')}, attempts={item.get('attempts')}, "
                f"success={item.get('successes')}, failure={item.get('failures')}"
            )
        for item in feedback["state_transition_value_items"][:6]:
            print(
                f"  transition {item.get('signature')}: "
                f"delta={item.get('avg_state_value_delta')}, score={item.get('avg_transition_value_score')}, "
                f"conf={item.get('avg_transition_confidence')}, "
                f"+/{item.get('positive_transitions')} -/{item.get('negative_transitions')} "
                f"~/{item.get('no_progress_transitions')}"
            )
        for case in report.cases:
            marker = "+" if case.ready_for_action_value_review else "~"
            print(f"  [{marker}] {case.source_log}")
            print(
                f"      actions={case.action_count}, success={case.success_count}, "
                f"failure={case.failure_count}, signatures={case.signature_count}, "
                f"pairs={len(case.failure_correction_pairs)}, transitions={case.state_transition_count}"
            )
            for pair in case.failure_correction_pairs[:3]:
                print(
                    f"      repair: {pair.get('failed_signature')} -> "
                    f"{pair.get('recovery_signature')}"
                )
        for error in report.errors:
            print(f"  error: {error}")

    def print_knowledge_correction_report(self, report: KnowledgeCorrectionTraceReport):
        print("\nKnowledge Correction Trace")
        print(f"  logs ready for correction review: {report.ready_log_count}/{report.log_count}")
        print(
            "  evidence: "
            f"actions={report.action_count}, failed={report.failure_action_count}, "
            f"repeated_failures={report.repeated_failure_signature_count}, "
            f"recovery_pairs={report.recovery_pair_count}"
        )
        print(
            "  candidates: "
            f"dependency_corrections={report.dependency_correction_count}, "
            f"failed_action_memories={report.failure_action_memory_count}, "
            f"low_confidence_windows={report.low_confidence_transition_count}"
        )
        feedback = self.knowledge_correction_feedback(report)
        if feedback["policy_hints"]:
            hints = [
                f"{hint['knowledge_correction_policy']}({hint['priority']})"
                for hint in feedback["policy_hints"][:6]
            ]
            print(f"  policy hints: {', '.join(hints)}")
        for item in feedback["dependency_corrections"][:6]:
            print(
                f"  dependency {item.get('failed_signature')} -> {item.get('recovery_signature')}: "
                f"evidence={item.get('evidence_count')} confidence={item.get('confidence')}"
            )
            if item.get("correction"):
                print(f"      {item.get('correction')}")
        for item in feedback["failure_action_memories"][:6]:
            print(
                f"  failed action {item.get('signature')}: "
                f"failures={item.get('failures')}/{item.get('attempts')} "
                f"value={item.get('value_score')} reason={item.get('reason')}"
            )
        for case in report.cases:
            marker = "+" if case.ready_for_knowledge_correction_review else "~"
            print(f"  [{marker}] {case.source_log}")
            print(
                f"      actions={case.action_count}, failed={case.failure_action_count}, "
                f"pairs={case.recovery_pair_count}, dependency={case.dependency_correction_count}, "
                f"failed_memories={case.failure_action_memory_count}"
            )
        for error in report.errors:
            print(f"  error: {error}")

    def print_knowledge_correction_gate_report(self, report: dict):
        print("\nKnowledge Correction Gate")
        print(f"  target: {report.get('target', 'planner_knowledge_correction_feedback')}")
        print(f"  readiness: {report.get('readiness', 'unknown')}")
        print(f"  decision: {report.get('decision', 'unknown')}")
        print(f"  reason: {report.get('reason', '')}")
        print(
            "  evidence: "
            f"sources={report.get('source_count', 0)}, "
            f"ready_logs={report.get('ready_log_count', 0)}/{report.get('log_count', 0)}, "
            f"dependency={report.get('dependency_correction_count', 0)}, "
            f"failed_memories={report.get('failure_action_memory_count', 0)}"
        )
        if report.get("missing"):
            print(f"  missing: {', '.join(report.get('missing', []))}")
        if report.get("policy_hints"):
            print(f"  policy hints: {', '.join(report.get('policy_hints', []))}")
        for source in report.get("sources", [])[:8]:
            print(
                f"  source {source.get('source')}: "
                f"ready_logs={source.get('ready_log_count', 0)}, "
                f"corrections={source.get('correction_count', 0)}"
            )
        for check in report.get("checks", [])[:10]:
            marker = "+" if check.get("status") == "pass" else "x" if check.get("status") == "fail" else "!"
            print(f"  [{marker}] {check.get('kind')} {check.get('source')}: {check.get('detail')}")
        for error in report.get("errors", []):
            print(f"  error: {error}")

    def print_action_value_transition_gate_report(self, report: dict):
        print("\nAction Value Transition Gate")
        print(f"  readiness: {report.get('readiness', 'unknown')}")
        print(f"  decision: {report.get('decision', 'unknown')}")
        print(f"  reason: {report.get('reason', '')}")
        print(
            "  transitions: "
            f"total={report.get('state_transition_count', 0)}, "
            f"trusted_items={report.get('trusted_item_count', 0)}, "
            f"trusted_attempts={report.get('trusted_transition_count', 0)}, "
            f"low_confidence={report.get('low_confidence_transition_count', 0)} "
            f"rate={report.get('low_confidence_rate', 0.0):.3f}"
        )
        if report.get("missing"):
            print(f"  missing: {', '.join(report.get('missing', []))}")
        if report.get("policy_hints"):
            print(f"  policy hints: {', '.join(report.get('policy_hints', []))}")
        for check in report.get("checks", [])[:8]:
            marker = "+" if check.get("status") == "pass" else "!" if check.get("status") == "warn" else "x"
            metrics = check.get("metrics", {})
            print(
                f"  [{marker}] {check.get('source')}: {check.get('detail')} "
                f"trusted={metrics.get('trusted_item_count', 0)}/"
                f"{metrics.get('trusted_transition_count', 0)} "
                f"low_rate={metrics.get('low_confidence_rate', 0.0):.3f}"
            )
        for item in report.get("trusted_items", [])[:5]:
            print(
                f"      trusted {item.get('signature')}: attempts={item.get('attempts')} "
                f"conf={item.get('avg_transition_confidence')} score={item.get('avg_transition_value_score')}"
            )
        for item in report.get("review_items", [])[:5]:
            print(
                f"      review {item.get('signature')}: {item.get('reason')} "
                f"attempts={item.get('attempts')} conf={item.get('avg_transition_confidence')}"
            )
        for error in report.get("errors", []):
            print(f"  error: {error}")

    def print_action_value_transition_evaluator_report(self, report: dict):
        print("\nAction Value Transition Evaluator")
        print(f"  readiness: {report.get('readiness', 'unknown')}")
        print(f"  decision: {report.get('decision', 'unknown')}")
        print(f"  reason: {report.get('reason', '')}")
        print(
            "  transitions: "
            f"total={report.get('transition_count', 0)}, "
            f"evaluated={report.get('evaluated_count', 0)}, "
            f"skipped={report.get('skipped_count', 0)}, "
            f"agreement={report.get('agreement_count', 0)}, "
            f"conflicts={report.get('conflict_count', 0)}"
        )
        print(
            "  rates: "
            f"agreement={report.get('agreement_rate', 0.0):.3f}, "
            f"large_delta={report.get('large_score_delta_rate', 0.0):.3f}, "
            f"avg_abs_score_delta={report.get('avg_abs_score_delta', 0.0):.3f}"
        )
        if report.get("missing"):
            print(f"  missing: {', '.join(report.get('missing', []))}")
        if report.get("policy_hints"):
            print(f"  policy hints: {', '.join(report.get('policy_hints', []))}")
        for case in report.get("comparison_cases", [])[:6]:
            marker = "+" if case.get("agreement") and not case.get("large_score_delta") else "!"
            print(
                f"  [{marker}] {case.get('signature')} event#{case.get('event_index')}: "
                f"{case.get('deterministic_label')}->{case.get('evaluator_label')} "
                f"score {case.get('deterministic_score')}->{case.get('evaluator_score')} "
                f"delta={case.get('score_delta')}"
            )
        for skipped in report.get("skipped", [])[:6]:
            print(
                f"      skipped {skipped.get('signature')} event#{skipped.get('event_index')}: "
                f"{skipped.get('reason')}"
            )
        for error in report.get("errors", []):
            print(f"  error: {error}")

    def print_self_evolution_gate_report(self, report: dict):
        print("\nSelf-Evolution Plan Repair Gate")
        print(f"  readiness: {report.get('readiness', 'unknown')}")
        print(f"  decision: {report.get('decision', 'unknown')}")
        print(f"  reason: {report.get('reason', '')}")
        print(
            "  inputs: "
            f"self_evolution={report.get('self_evolution_report_count', 0)}, "
            f"verifier={report.get('verifier_report_count', 0)}, "
            f"counterexamples={report.get('counterexample_report_count', 0)}"
        )
        print(
            "  checks: "
            f"evidence={report.get('evidence_count', 0)}, "
            f"warnings={report.get('warning_count', 0)}, "
            f"failures={report.get('regression_count', 0)}"
        )
        if report.get("missing"):
            print(f"  missing: {', '.join(report.get('missing', []))}")
        for check in report.get("checks", []):
            marker = "+" if check.get("status") == "pass" else "!" if check.get("status") == "warn" else "x"
            print(f"  [{marker}] {check.get('kind')} {check.get('source')}: {check.get('detail')}")
        for error in report.get("errors", []):
            print(f"  error: {error}")

    def print_discovery_application_report(self, report: DiscoveryApplicationTraceReport):
        total = report.log_count
        print("\nDiscovery-to-Application Trace")
        print(f"  logs ready for discovery review: {report.ready_log_count}/{total}")
        print(
            "  phases: "
            f"hypotheses={report.hypothesis_count}, "
            f"experiments={report.experiment_count + report.experiment_action_count}, "
            f"consolidations={report.consolidation_count}, "
            f"applications={report.application_count}"
        )
        print(
            "  applications: "
            f"success={report.successful_application_count}, "
            f"failed={report.failed_application_count}"
        )
        print(
            "  experiment actions: "
            f"total={report.experiment_action_count}, "
            f"failed={report.failed_experiment_action_count}"
        )
        print(f"  causal memory writes: {report.causal_memory_write_count}")
        print(f"  complete discovery loops: {report.complete_loop_count}")
        feedback = self.discovery_application_feedback(report)
        if feedback["recommendations"]:
            print(f"  feedback: {', '.join(feedback['recommendations'][:6])}")
        print(f"  ready for skill gate: {'yes' if feedback['ready_for_skill_gate'] else 'no'}")
        for case in report.cases:
            marker = "+" if case.complete_loop_count else "!"
            print(f"  [{marker}] {case.source_log}")
            print(
                f"      phases={self._format_counts(case.phase_counts)}, "
                f"complete_loops={case.complete_loop_count}"
            )
            print(
                f"      goals={case.completed_goal_count}/{case.goal_count} completed, "
                f"applications={case.successful_application_count}/{case.application_count} succeeded"
            )
            if case.knowledge_gap_candidates:
                print(f"      gaps: {'; '.join(case.knowledge_gap_candidates[:3])}")
            if case.causal_rule_candidates:
                print(f"      causal rules: {'; '.join(case.causal_rule_candidates[:3])}")
            if case.application_goals:
                print(f"      applications: {'; '.join(case.application_goals[:3])}")
            if case.recommendations:
                print(f"      recommendations: {', '.join(case.recommendations[:4])}")
        for error in report.errors:
            print(f"  error: {error}")

    def print_action_abstraction_report(self, report: ActionAbstractionTraceReport):
        total = report.log_count
        print("\nAction Abstraction Trace")
        print(f"  logs: {total}")
        print(f"  actions: {report.action_count}")
        print(f"  failed actions: {report.failed_action_count}")
        print(f"  unknown canonical actions: {report.unknown_canonical_count}")
        print(f"  failed mappings: {report.failed_mapping_count}")
        print(f"  desktop planned mappings: {report.desktop_planned_count}")
        print(f"  low-level control candidates: {report.low_level_candidate_count}")
        feedback = self.action_abstraction_feedback(report)
        if feedback["policy_hints"]:
            hints = [
                f"{hint['action_type']}->{hint['preferred_control']}"
                for hint in feedback["policy_hints"][:6]
            ]
            print(f"  policy hints: {', '.join(hints)}")
        for case in report.cases:
            marker = "!" if case.failed_mapping_count else "+"
            print(f"  [{marker}] {case.source_log}")
            print(
                f"      actions={case.action_count}, failed={case.failed_action_count}, "
                f"unknown={case.unknown_canonical_count}, low_level={case.low_level_candidate_count}"
            )
            if case.canonical_action_types:
                print(f"      canonical: {self._format_counts(case.canonical_action_types)}")
            if case.result_backend_command_counts:
                print(f"      observed backend commands: {self._format_counts(case.result_backend_command_counts)}")
            if case.desktop_command_counts:
                print(f"      desktop plan: {self._format_counts(case.desktop_command_counts)}")
            if case.lower_level_reasons:
                print(f"      lower-level reasons: {self._format_counts(case.lower_level_reasons)}")
            for recommendation in case.task_recommendations[:4]:
                print(f"      recommendation: {recommendation}")
        for error in report.errors:
            print(f"  error: {error}")

    def print_memory_policy_report(self, report: MemoryPolicyTraceReport):
        print("\nMemory Policy Trace")
        print(f"  logs: {report.log_count}")
        print(f"  ready logs: {report.ready_log_count}")
        print(
            "  explicit memory events: "
            f"writes={report.explicit_memory_write_count}, "
            f"reads={report.explicit_memory_read_count}, "
            f"manage={report.explicit_memory_manage_count}"
        )
        print(
            "  inferred gaps: "
            f"missed_semantic_writes={report.missed_semantic_write_count}, "
            f"missing_read_traces={report.missing_read_trace_count}, "
            f"failure_learning={report.failure_learning_candidate_count}, "
            f"noisy_writes={report.noisy_write_candidate_count}"
        )
        if report.read_filter_event_count:
            print(
                "  read filters: "
                f"events={report.read_filter_event_count}, "
                f"filtered_entries={report.read_filtered_entry_count}, "
                f"reasons={self._format_counts(report.read_filter_reasons)}"
            )
        feedback = self.memory_policy_feedback(report)
        if feedback["policy_hints"]:
            hints = [
                f"{hint['memory_policy']}({hint['priority']})"
                for hint in feedback["policy_hints"][:6]
            ]
            print(f"  policy hints: {', '.join(hints)}")
        for case in report.cases:
            marker = "+" if case.ready_for_memory_policy_review else "~"
            print(f"  [{marker}] {case.source_log}")
            print(
                f"      events={case.event_count}, observations={case.observation_count}, "
                f"plans={case.plan_count}, actions={case.action_count}, failed={case.failed_action_count}"
            )
            print(
                f"      explicit: writes={case.explicit_memory_write_count}, "
                f"reads={case.explicit_memory_read_count}, manage={case.explicit_memory_manage_count}"
            )
            print(
                f"      candidates: context={case.context_write_candidate_count}, "
                f"episodic={case.episodic_write_candidate_count}, "
                f"semantic={case.semantic_write_candidate_count}, "
                f"failure_learning={case.failure_learning_candidate_count}, "
                f"consolidation={case.consolidation_signal_count}"
            )
            if case.write_operations:
                print(f"      writes: {self._format_counts(case.write_operations)}")
            if case.read_queries:
                print(f"      read queries: {', '.join(case.read_queries[:4])}")
            if case.read_filter_event_count:
                print(
                    f"      read filters: events={case.read_filter_event_count}, "
                    f"filtered_entries={case.read_filtered_entry_count}, "
                    f"reasons={self._format_counts(case.read_filter_reasons)}"
                )
            if case.policy_hints:
                print(f"      hints: {', '.join(case.policy_hints)}")
        for error in report.errors:
            print(f"  error: {error}")

    def print_skill_memory_quality_report(self, report: SkillMemoryQualityReport):
        print("\nSkill Memory Quality Trace")
        print(f"  logs: {report.log_count}")
        print(f"  ready logs: {report.ready_log_count}")
        print(
            "  hints: "
            f"events={report.hint_event_count}, total={report.hint_count}, "
            f"types={self._format_counts(report.hint_type_counts)}"
        )
        print(
            "  post-hint outcomes: "
            f"goal_success={report.post_hint_goal_success_count}, "
            f"goal_failure={report.post_hint_goal_failure_count}, "
            f"failed_actions={report.post_hint_failed_action_count}, "
            f"repeated_failures={report.repeated_post_hint_failure_count}"
        )
        if report.task_family_counts:
            print(f"  task families: {self._format_counts(report.task_family_counts)}")
        for item in report.hint_quality_items[:5]:
            labels = self._format_counts(item.get("labels", {}))
            print(
                f"  item: {item.get('hint_type')} {item.get('skill')} "
                f"family={item.get('task_family')} count={item.get('count')} labels={labels}"
            )
        feedback = self.skill_memory_quality_feedback(report)
        if feedback["policy_hints"]:
            hints = [
                f"{hint['skill_memory_policy']}({hint['priority']})"
                for hint in feedback["policy_hints"][:6]
            ]
            print(f"  policy hints: {', '.join(hints)}")
        for case in report.cases:
            marker = "+" if case.ready_for_skill_memory_quality_review and "reuse_conflicted_with_failures" not in case.quality_labels else "!"
            if not case.hint_event_count:
                marker = "~"
            print(f"  [{marker}] {case.source_log}")
            print(
                f"      hints={case.hint_count}, types={self._format_counts(case.hint_type_counts)}, "
                f"actions={case.action_count}, post_hint_failed={case.post_hint_failed_action_count}"
            )
            print(
                f"      goals={case.completed_goal_count}/{case.goal_count}, "
                f"post_hint_goals={case.post_hint_goal_success_count}/{case.post_hint_goal_success_count + case.post_hint_goal_failure_count}"
            )
            if case.quality_labels:
                print(f"      labels: {', '.join(case.quality_labels)}")
            if case.recommendations:
                print(f"      recommendations: {', '.join(case.recommendations[:4])}")
        for error in report.errors:
            print(f"  error: {error}")

    def print_skill_memory_quality_gate_report(self, report: dict):
        print("\nSkill Memory Quality Gate")
        print(f"  target: {report.get('target', 'skill_memory_reuse_promotion')}")
        print(f"  readiness: {report.get('readiness', 'unknown')}")
        print(f"  decision: {report.get('decision', 'unknown')}")
        print(f"  reason: {report.get('reason', '')}")
        print(
            "  evidence: "
            f"memory_reports={report.get('memory_report_count', 0)}, "
            f"quality_feedback={report.get('quality_feedback_count', 0)}, "
            f"candidates={report.get('candidate_count', 0)}, "
            f"approved={report.get('approved_count', 0)}, "
            f"review={report.get('review_count', 0)}, "
            f"rejected={report.get('rejected_count', 0)}"
        )
        if report.get("missing"):
            print(f"  missing: {', '.join(report.get('missing', []))}")
        for candidate in report.get("candidates", [])[:8]:
            marker = "+" if candidate.get("readiness") == "approved" else "x" if candidate.get("readiness") == "rejected" else "!"
            print(
                f"  [{marker}] {candidate.get('skill')} ({candidate.get('task_family') or 'any'}): "
                f"{candidate.get('readiness')} support={candidate.get('supported_reuse_count', 0)} "
                f"conflict={candidate.get('conflicting_reuse_count', 0)} "
                f"family_memories={candidate.get('family_memory_count', 0)}"
            )
            print(f"      {candidate.get('reason', '')}")
        if report.get("policy_hints"):
            print(f"  policy hints: {', '.join(report.get('policy_hints', []))}")
        for error in report.get("errors", []):
            print(f"  error: {error}")

    def print_bounded_context_report(self, report: BoundedPlanningContextReport):
        print("\nBounded Planning Context Trace")
        print(f"  logs: {report.log_count}")
        print(f"  ready logs: {report.ready_log_count}")
        print(
            "  cycles: "
            f"bounded={report.bounded_cycle_count}, "
            f"unbounded={report.unbounded_cycle_count}, "
            f"total={report.planning_cycle_count}"
        )
        print(
            "  issues: "
            f"missing_reads={report.missing_read_cycle_count}, "
            f"oversized_reads={report.oversized_read_cycle_count}, "
            f"oversized_cycles={report.oversized_cycle_count}, "
            f"raw_context={report.raw_context_cycle_count}, "
            f"low_diversity={report.low_diversity_cycle_count}"
        )
        print(
            "  budgets: "
            f"max_read_chars={report.max_read_chars}, "
            f"max_cycle_chars={report.max_cycle_chars}"
        )
        if report.read_types:
            print(f"  read types: {self._format_counts(report.read_types)}")
        feedback = self.bounded_context_feedback(report)
        if feedback["policy_hints"]:
            hints = [
                f"{hint['bounded_context_policy']}({hint['priority']})"
                for hint in feedback["policy_hints"][:6]
            ]
            print(f"  policy hints: {', '.join(hints)}")
        for case in report.cases:
            marker = "+" if case.unbounded_cycle_count == 0 and case.planning_cycle_count else "!"
            if not case.planning_cycle_count:
                marker = "~"
            print(f"  [{marker}] {case.source_log}")
            print(
                f"      cycles={case.planning_cycle_count}, bounded={case.bounded_cycle_count}, "
                f"unbounded={case.unbounded_cycle_count}, max_chars={case.max_cycle_result_chars}"
            )
            if case.read_types:
                print(f"      read types: {self._format_counts(case.read_types)}")
            if case.issues:
                print(f"      issues: {', '.join(case.issues)}")
            for cycle in case.cycles[:5]:
                cycle_marker = "+" if cycle.bounded_ok else "!"
                print(
                    f"      [{cycle_marker}] cycle {cycle.cycle_index}: "
                    f"reads={cycle.memory_read_count}, typed={cycle.typed_layer_count}, "
                    f"chars={cycle.total_result_chars}, actions={cycle.action_count}, "
                    f"status={cycle.plan_status or 'unknown'}"
                )
                if cycle.issues:
                    print(f"          issues: {', '.join(cycle.issues)}")
        for error in report.errors:
            print(f"  error: {error}")

    def print_continual_learning_report(self, report: ContinualLearningTraceReport):
        print("\nContinual Learning Trace")
        print(f"  logs: {report.log_count}")
        print(f"  ready logs: {report.ready_log_count}")
        print(
            "  progress: "
            f"goals={report.completed_goal_count}/{report.completed_goal_count + report.failed_goal_count}, "
            f"progress_events={report.progress_event_count}, "
            f"actions={report.action_count}, failed_actions={report.failed_action_count}"
        )
        print(
            "  learning signals: "
            f"objects={report.object_exploration_count}, "
            f"memory_reads={report.memory_read_count}, "
            f"memory_writes={report.memory_write_count}, "
            f"unbounded_context_cycles={report.unbounded_context_cycle_count}"
        )
        if report.average_axis_scores:
            scores = ", ".join(f"{key}={value:.2f}" for key, value in sorted(report.average_axis_scores.items()))
            print(f"  axis scores: {scores}")
        feedback = self.continual_learning_feedback(report)
        if feedback["policy_hints"]:
            hints = [
                f"{hint['continual_learning_policy']}({hint['priority']})"
                for hint in feedback["policy_hints"][:6]
            ]
            print(f"  policy hints: {', '.join(hints)}")
        for case in report.cases:
            marker = "+" if case.ready_for_continual_learning_review and not case.issues else "!"
            if not case.ready_for_continual_learning_review:
                marker = "~"
            print(f"  [{marker}] {case.source_log}")
            print(
                f"      goals={case.completed_goal_count}/{case.goal_count}, "
                f"actions={case.action_count}, failed={case.failed_action_count}, "
                f"action_types={case.unique_action_type_count}, action_entropy={case.action_entropy:.2f}"
            )
            print(
                f"      world: positions={case.unique_position_count}, cells={case.unique_cell_count}, "
                f"frontiers={case.frontier_count}, objects={case.object_exploration_count}, "
                f"path={case.path_distance:.2f}"
            )
            print(
                f"      memory: reads={case.memory_read_count}, writes={case.memory_write_count}, "
                f"semantic={case.semantic_write_count}, episodic={case.episodic_write_count}, "
                f"bounded={case.bounded_cycle_count}, unbounded={case.unbounded_context_cycle_count}"
            )
            if case.axis_scores:
                scores = ", ".join(f"{key}={value:.2f}" for key, value in sorted(case.axis_scores.items()))
                print(f"      scores: {scores}")
            if case.issues:
                print(f"      issues: {', '.join(case.issues)}")
            for recommendation in case.recommendations[:4]:
                print(f"      recommendation: {recommendation}")
        for error in report.errors:
            print(f"  error: {error}")

    def print_task_stream_transfer_report(self, report: TaskStreamTransferReport):
        print("\nTask Stream Transfer Report")
        print(f"  streams: {report.ready_stream_count}/{report.stream_count} ready")
        print(
            "  tasks: "
            f"{report.task_count}, reusable_relations={report.reusable_relation_count}, "
            f"reuse_coverage={report.reuse_coverage:.2f}"
        )
        print(
            "  gains: "
            f"plasticity={self._format_optional_score(report.average_plasticity_gain)}, "
            f"stability={self._format_optional_score(report.average_stability_gain)}, "
            f"generalization={self._format_optional_score(report.average_generalization_gain)}, "
            f"interference={report.interference_count}"
        )
        feedback = self.task_stream_transfer_feedback(report)
        if feedback["policy_hints"]:
            hints = [
                f"{hint['task_stream_policy']}({hint['priority']})"
                for hint in feedback["policy_hints"][:6]
            ]
            print(f"  policy hints: {', '.join(hints)}")
        for case in report.cases:
            marker = "+" if case.ready_for_transfer_review and not case.issues else "!"
            if not case.ready_for_transfer_review:
                marker = "~"
            print(f"  [{marker}] {case.stream_id} ({case.source_file})")
            print(
                f"      tasks={case.ready_task_count}/{case.task_count}, "
                f"reuse={case.reuse_hit_tag_count}/{case.reuse_expected_tag_count}, "
                f"plasticity={self._format_optional_score(case.plasticity_gain)}, "
                f"stability={self._format_optional_score(case.stability_gain)}, "
                f"generalization={self._format_optional_score(case.generalization_gain)}, "
                f"interference={case.interference_count}"
            )
            if case.issues:
                print(f"      issues: {', '.join(case.issues)}")
            for recommendation in case.recommendations[:4]:
                print(f"      recommendation: {recommendation}")
            for task in case.tasks[:6]:
                task_marker = "+" if task.ready_for_transfer_review and not task.issues else "!"
                if not task.ready_for_transfer_review:
                    task_marker = "~"
                print(
                    f"      [{task_marker}] {task.task_id}: "
                    f"base={self._format_optional_score(task.baseline_score)}, "
                    f"first={self._format_optional_score(task.first_pass_score)}, "
                    f"second={self._format_optional_score(task.second_pass_score)}, "
                    f"heldout={self._format_optional_score(task.heldout_score)}, "
                    f"reuse={len(task.reuse_hit_tags)}/{len(task.expected_reuse_tags)}"
                )
                if task.issues:
                    print(f"          issues: {', '.join(task.issues)}")
                if task.reuse_hit_tags:
                    print(f"          reuse hits: {', '.join(task.reuse_hit_tags[:8])}")
        for error in report.errors:
            print(f"  error: {error}")

    def print_task_stream_transfer_gate_report(self, report: dict):
        print("\nTask Stream Transfer Gate")
        print(f"  target: {report.get('target', 'memory_or_skill_promotion')}")
        print(f"  readiness: {report.get('readiness', 'unknown')}")
        print(f"  decision: {report.get('decision', 'unknown')}")
        print(f"  reason: {report.get('reason', '')}")
        print(
            "  evidence: "
            f"reports={report.get('transfer_report_count', 0)}, "
            f"streams={report.get('ready_stream_count', 0)}/{report.get('stream_count', 0)}, "
            f"tasks={report.get('task_count', 0)}, "
            f"reuse_coverage={float(report.get('reuse_coverage') or 0.0):.2f}, "
            f"interference={report.get('interference_count', 0)}"
        )
        print(
            "  gains: "
            f"plasticity={self._format_optional_score(report.get('average_plasticity_gain'))}, "
            f"stability={self._format_optional_score(report.get('average_stability_gain'))}, "
            f"generalization={self._format_optional_score(report.get('average_generalization_gain'))}"
        )
        print(
            "  checks: "
            f"pass={report.get('evidence_count', 0)}, "
            f"warn={report.get('warning_count', 0)}, "
            f"fail={report.get('regression_count', 0)}"
        )
        if report.get("missing"):
            print(f"  missing: {', '.join(report.get('missing', []))}")
        for check in report.get("checks", []):
            marker = "+" if check.get("status") == "pass" else "!" if check.get("status") == "warn" else "x"
            print(f"  [{marker}] {check.get('kind')} {check.get('source')}: {check.get('detail')}")
        for error in report.get("errors", []):
            print(f"  error: {error}")

    def _format_counts(self, counts: dict, limit: int = 8) -> str:
        items = sorted(counts.items(), key=lambda item: (-int(item[1]), str(item[0])))
        return ", ".join(f"{key}={value}" for key, value in items[:limit])

    def _format_optional_score(self, value: Optional[float]) -> str:
        if value is None:
            return "n/a"
        return f"{float(value):.2f}"

    def _merge_counts(self, target: dict, source: dict):
        for key, value in (source or {}).items():
            target[str(key)] = target.get(str(key), 0) + self._safe_int(value, default=0)

    def _safe_int(self, value, default: int = 0) -> int:
        if value in (None, ""):
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            try:
                return int(float(value))
            except (TypeError, ValueError):
                return default

    def print_review_label_validation_report(self, report: ReviewLabelValidationReport):
        print("\nReview Label Validation")
        print(f"  labels: {report.ok_count}/{report.label_count} ok")
        print(f"  invalid readiness: {report.invalid_readiness_count}")
        print(f"  unknown readiness: {report.unknown_readiness_count}")
        print(f"  unverified screenshot claims: {report.screenshot_unverified_count}")
        for case in report.cases:
            marker = "+" if case.ok else "x"
            label = case.key or case.candidate_id or case.goal or f"record-{case.index}"
            print(f"  [{marker}] {case.index} {case.label_type}: {label}")
            print(
                f"      readiness={case.readiness or 'invalid'}, "
                f"screenshots={case.screenshot_count}/{case.raw_screenshot_count} verified, "
                f"missing={case.missing_screenshot_count}, invalid={case.invalid_screenshot_count}"
            )
            if case.errors:
                print(f"      errors: {', '.join(case.errors)}")
            if case.warnings:
                print(f"      warnings: {', '.join(case.warnings)}")
        for error in report.errors:
            print(f"  error: {error}")

    def print_visual_review_pipeline_report(self, report: VisualReviewPipelineReport):
        print("\nVisual Review Pipeline")
        print(f"  mode: {report.mode}")
        print(f"  ready: {report.ready}")
        print(
            "  visual trace: "
            f"{report.visual_trace.ready_log_count}/{report.visual_trace.log_count} logs ready, "
            f"{report.visual_trace.screenshot_log_count}/{report.visual_trace.log_count} with verified screenshots"
        )
        print(
            "  label templates: "
            f"{report.template_count} total "
            f"({report.promotion_template_count} promotion, {report.goal_template_count} goal, "
            f"{report.error_template_count} errors)"
        )
        if report.label_validation is None:
            print("  label validation: not run")
        else:
            print(
                "  label validation: "
                f"{report.label_validation.ok_count}/{report.label_validation.label_count} ok, "
                f"errors={report.label_validation.error_count}, "
                f"unverified_screenshot_claims={report.label_validation.screenshot_unverified_count}"
            )
        if report.promotion_ablation is not None:
            print(
                "  promotion ablation: "
                f"{report.promotion_ablation.changed_count}/{report.promotion_ablation.candidate_count} changed, "
                f"screenshot_added_value={report.promotion_ablation.screenshot_vlm_added_value_count}"
            )
        elif report.run_ablations and report.mode in {"promotion", "both"}:
            print("  promotion ablation: skipped")
        if report.goal_ablation is not None:
            print(
                "  goal ablation: "
                f"{report.goal_ablation.changed_count}/{report.goal_ablation.goal_count} changed, "
                f"screenshot_added_value={report.goal_ablation.screenshot_vlm_added_value_count}"
            )
        elif report.run_ablations and report.mode in {"goal", "both"}:
            print("  goal ablation: skipped")
        if report.visual_action_ablation is not None:
            print(
                "  visual action ablation: "
                f"{report.visual_action_ablation.changed_count}/{len(report.visual_action_ablation.cases)} changed, "
                f"helped={report.visual_action_ablation.helped_count}, "
                f"passed={report.visual_action_ablation.passed_count}"
            )
        elif report.run_ablations:
            print("  visual action ablation: skipped")
        if report.visual_trace.errors:
            for error in report.visual_trace.errors:
                print(f"  trace error: {error}")
        for error in report.errors:
            print(f"  error: {error}")

    def print_promotion_review_ablation_report(self, report: PromotionReviewAblationReport):
        total = report.candidate_count
        print("\nPromotion Review Visual Ablation")
        print(f"  candidates: {total}")
        print(f"  changed across modes: {report.changed_count}/{total}")
        print(f"  API visual helped: {report.api_visual_helped_count}/{total}")
        print(f"  screenshot/VLM helped: {report.screenshot_vlm_helped_count}/{total}")
        print(f"  screenshot/VLM added over API: {report.screenshot_vlm_added_value_count}/{total}")
        if report.manual_labeled_count:
            labeled = report.manual_labeled_count
            print(f"  manual labels: {labeled}/{total}")
            print(f"  deterministic manual match: {report.deterministic_manual_match_count}/{labeled}")
            print(f"  API visual manual match: {report.api_visual_manual_match_count}/{labeled}")
            print(f"  screenshot/VLM manual match: {report.screenshot_vlm_manual_match_count}/{labeled}")
            print(f"  screenshot/VLM manual improvement over API: {report.screenshot_vlm_manual_improvement_count}/{labeled}")
        for case in report.cases:
            marker = "+" if case.visual_helped else "~" if case.changed else "="
            print(f"  [{marker}] {case.candidate_id} {case.candidate_name}")
            print(f"      source: {case.source_log}")
            print(f"      goal: {case.goal}")
            if case.manual_readiness:
                print(f"      manual: {case.manual_readiness} ({case.manual_label_source}: {case.manual_label_notes})")
            print(
                f"      deterministic:  {case.deterministic_readiness} "
                f"({case.deterministic_status}: {case.deterministic_reason})"
            )
            print(
                f"      API visual:     {case.api_visual_readiness} "
                f"({case.api_visual_status}: {case.api_visual_reason})"
            )
            print(
                f"      screenshot/VLM: {case.screenshot_vlm_readiness} "
                f"({case.screenshot_vlm_status}: {case.screenshot_vlm_reason})"
            )
            if case.visual_evidence_keys:
                print(f"      visual keys: {', '.join(case.visual_evidence_keys)}")
            if case.raw_screenshot_count:
                print(
                    f"      screenshots: {case.screenshot_count}/{case.raw_screenshot_count} verified, "
                    f"missing={case.missing_screenshot_count}, invalid={case.invalid_screenshot_count}"
                )
        for error in report.errors:
            print(f"  error: {error}")

    def print_goal_verification_ablation_report(self, report: GoalVerificationAblationReport):
        total = report.goal_count
        print("\nGoal Verification Visual Ablation")
        print(f"  goals: {total}")
        print(f"  changed across modes: {report.changed_count}/{total}")
        print(f"  API visual helped: {report.api_visual_helped_count}/{total}")
        print(f"  screenshot/VLM helped: {report.screenshot_vlm_helped_count}/{total}")
        print(f"  screenshot/VLM added over API: {report.screenshot_vlm_added_value_count}/{total}")
        if report.manual_labeled_count:
            labeled = report.manual_labeled_count
            print(f"  manual labels: {labeled}/{total}")
            print(f"  deterministic manual match: {report.deterministic_manual_match_count}/{labeled}")
            print(f"  API visual manual match: {report.api_visual_manual_match_count}/{labeled}")
            print(f"  screenshot/VLM manual match: {report.screenshot_vlm_manual_match_count}/{labeled}")
            print(f"  screenshot/VLM manual improvement over API: {report.screenshot_vlm_manual_improvement_count}/{labeled}")
        for case in report.cases:
            marker = "+" if case.visual_helped else "~" if case.changed else "="
            print(f"  [{marker}] {case.goal}")
            print(f"      source: {case.source_log}")
            if case.manual_readiness:
                print(f"      manual: {case.manual_readiness} ({case.manual_label_source}: {case.manual_label_notes})")
            print(
                f"      deterministic:  {case.deterministic_readiness} "
                f"({case.deterministic_status}, conf={case.deterministic_confidence:.2f})"
            )
            print(
                f"      API visual:     {case.api_visual_readiness} "
                f"({case.api_visual_status}, conf={case.api_visual_confidence:.2f}: {case.api_visual_reason})"
            )
            print(
                f"      screenshot/VLM: {case.screenshot_vlm_readiness} "
                f"({case.screenshot_vlm_status}, conf={case.screenshot_vlm_confidence:.2f}: {case.screenshot_vlm_reason})"
            )
            if case.visual_evidence_keys:
                print(f"      visual keys: {', '.join(case.visual_evidence_keys)}")
        for error in report.errors:
            print(f"  error: {error}")

    def print_policy_skill_ablation_report(self, report: PolicySkillAblationReport):
        total = len(report.cases)
        print("\nPolicy Skill Ablation")
        print(f"  reviewed skills helped expected case: {report.helped_count}/{total}")
        for case in report.cases:
            marker = "+" if case.enabled_helped else "=" if case.enabled_corrected == case.disabled_corrected else "~"
            print(f"  [{marker}] {case.case_id} {case.case_name}")
            print(f"      skill: {case.skill_name} ({case.source})")
            print(f"      disabled: corrected={'yes' if case.disabled_corrected else 'no'}, interventions={case.disabled_interventions}")
            print(
                f"      enabled:  corrected={'yes' if case.enabled_corrected else 'no'}, "
                f"interventions={case.enabled_interventions}, success_rate={case.enabled_success_rate:.2f}"
            )
            if case.enabled_actions:
                print(f"      enabled actions: {' -> '.join(case.enabled_actions)}")
