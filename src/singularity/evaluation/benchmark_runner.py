"""Benchmark runner for Singularity M1-M2 validation."""
import importlib.util
import json
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
from singularity.core.task_system import TaskStatus, TaskSystem
from singularity.bot.bridge import BotBridge
from singularity.action.mapping import ActionMapper

logger = logging.getLogger("singularity.benchmark")


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

    def _run_task_with_config(self, task: BenchmarkTask, config: Config) -> BenchmarkResult:
        runner = BenchmarkRunner(config, output_dir=self.output_dir, bridge_factory=self.bridge_factory)
        return runner.run_task(task)

    def _policy_intervention_count(self, result: BenchmarkResult) -> int:
        return result.intervention_metrics.get("policy_intervention_count", 0) if result.intervention_metrics else 0

    def _visual_action_intervention_count(self, result: BenchmarkResult) -> int:
        return result.intervention_metrics.get("visual_action_intervention_count", 0) if result.intervention_metrics else 0

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
            result = event.get("data", {}).get("result", {})
            if not isinstance(result, dict):
                continue
            completed = result.get("completed", result.get("success"))
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

    def _format_counts(self, counts: dict, limit: int = 8) -> str:
        items = sorted(counts.items(), key=lambda item: (-int(item[1]), str(item[0])))
        return ", ".join(f"{key}={value}" for key, value in items[:limit])

    def _merge_counts(self, target: dict, source: dict):
        for key, value in (source or {}).items():
            target[str(key)] = target.get(str(key), 0) + int(value or 0)

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
