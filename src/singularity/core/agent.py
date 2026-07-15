"""Core agent loop - the main brain of the Singularity Minecraft agent.

Integrates MemorySystem, SkillLibrary, TaskSystem, GoalGenerator, and Explorer
for both goal-directed and autonomous survival modes.
"""
import copy
import os
import json
import time
import logging
import hashlib
import math
import re
from dataclasses import asdict
from typing import Callable, Optional

from singularity.core.config import Config
from singularity.core.runtime import RuntimeSupervisor
from singularity.core.episode_abort import (
    EpisodeAbortMonitor,
    evaluate_episode_abort_runtime_gate,
    runtime_episode_abort_provenance,
)
from singularity.core.frontier_budget import (
    FrontierBudgetController,
    build_frontier_branches,
    evaluate_frontier_budget_runtime_gate,
    frontier_budget_trace_payload,
    runtime_frontier_budget_provenance,
)
from singularity.core.memory import (
    MemorySystem,
    evaluate_memory_attribution_runtime_gate,
    evaluate_memory_promptware_runtime_gate,
)
from singularity.core.memory_policy import MemoryLifecyclePolicy, MemoryPolicyDecision
from singularity.core.skill_library import SkillLibrary
from singularity.core.task_system import (
    FAILED_DEPENDENCY_MACHINE_STATE_RECONCILIATION_POLICY_ID,
    TaskSystem,
    TaskStatus,
)
from singularity.core.goal_generator import GoalGenerator
from singularity.core.coach import CoachPolicy
from singularity.core.curriculum import CurriculumManager
from singularity.core.goal_verifier import GoalVerifier
from singularity.core.explorer import Explorer
from singularity.core.rule_planner import RuleBasedPlanner
from singularity.core.self_evolution_policy import SelfEvolutionPolicy
from singularity.data.knowledge_base import KnowledgeBase
from singularity.core.plan_cache import (
    START_PLAN_SIGNATURE,
    PlanTransitionCache,
    evaluate_plan_cache_runtime_gate,
    plan_signature,
)
from singularity.observation.observer import Observer
from singularity.action.controller import ActionController
from singularity.action.policy import ActionGranularityPolicy
from singularity.action.selection import ActionCandidateSelector
from singularity.action.value import ActionValueProfile
from singularity.action.verifier import ActionVerifier
from singularity.bot.bridge import BotBridge
from singularity.evaluation.mixed_initiative import (
    MixedInitiativeFeedbackPolicy,
    apply_mixed_initiative_policy_patch,
)
from singularity.evaluation.m4_shelter import M4ShelterVerifier, is_machine_verified_shelter
from singularity.evaluation.m4_protocol import (
    task_contract,
    task_contract_sha256,
    task_spec,
    validate_m4_player_lifecycle,
)
from singularity.logging.session_logger import SessionLogger
from singularity.vision.analyzer import VisionAnalyzer
from singularity.vision.action_advisor import VisualActionAdvisor
from singularity.vision.visual_memory import VisualMemory

logger = logging.getLogger("singularity")

M4_TASK_WORLD_STATE_RECONCILIATION_POLICY_ID = "m4-task-world-state-reconciliation-v1"
M4_TASK_WORLD_STATE_RECONCILIATION_CRITERIA = frozenset({
    "inventory",
    "nearby_block_present",
})
M4_POST_PLACE_MACHINE_OBSERVATION_POLICY_ID = (
    "m4-post-place-crafting-table-machine-observation-v1"
)
M4_POST_PLACE_MACHINE_OBSERVATION_ITEM = "crafting_table"
M4_POST_PLACE_MACHINE_OBSERVATION_LIMIT = 2
M4_READY_TASK_GOAL_VERIFIER_POLICY_ID = (
    "m4-ready-task-goal-verifier-success-criteria-v1"
)
M4_READINESS_RECOVERY_COMPLETION_POLICY_ID = (
    "m4-readiness-recovery-inventory-family-root-completion-v1"
)
M4_READINESS_RECOVERY_LOG_FAMILY_ID = "minecraft:logs"
M4_READINESS_RECOVERY_CONTEXT_MAX_REQUIREMENTS = 4
M4_READINESS_RECOVERY_CONTEXT_MAX_CHARS = 640
M4_FAILED_DEPENDENCY_RECOVERY_ATTEMPT_BUDGET = 3
M4_MACHINE_STATE_INVENTORY_FAMILIES = {
    M4_READINESS_RECOVERY_LOG_FAMILY_ID: {
        "canonical_item": "oak_log",
        "members": tuple(GoalVerifier.LOG_ITEMS),
    },
}
M4_TYPED_SCHEMA_RECOVERY_POLICY_ID = "m4-typed-schema-recovery-v1"
M4_TYPED_SCHEMA_RECOVERY_LIMIT = 1
M4_TYPED_SCHEMA_ISSUE_PATTERN = re.compile(
    r"^subtask\[(?:0|[1-9]\d*)\]:(?:preconditions|success_criteria)_inventory_count_invalid:.+$"
)


class Agent:
    """Main agent that orchestrates observe-think-act cycles.

    Supports two modes:
    - Goal-directed: pursue a specific natural-language goal
    - Autonomous: self-direct survival goals using GoalGenerator (M4) and Explorer (M5)
    """

    def __init__(self, config: Config):
        self.config = config
        self.bot = BotBridge(config.bot)
        self.observer = Observer(self.bot)
        self.action_policy = ActionGranularityPolicy()
        self.action_verifier = ActionVerifier()
        self.action_value_profile = ActionValueProfile()
        self.action_value_feedback_report = self._load_action_value_feedback()
        self.action_candidate_selector = ActionCandidateSelector(
            self.action_verifier,
            value_profile=self.action_value_profile,
        )
        self.mixed_initiative_policy = MixedInitiativeFeedbackPolicy()
        self.mixed_policy_patch_report = self._load_mixed_policy_patches()
        self.self_evolution_policy = SelfEvolutionPolicy()
        self.self_evolution_feedback_report = self._load_self_evolution_feedback()
        self.coach_policy = CoachPolicy.from_style(getattr(config, "coach_style", ""))
        self.action_controller = ActionController(self.bot, config, action_policy=self.action_policy)
        self.running = False
        self.session_log: list[dict] = []
        self.current_goal: Optional[str] = None
        self.session_logger = SessionLogger(log_dir=config.log_dir)
        self.episode_abort_runtime_gate_report = evaluate_episode_abort_runtime_gate(
            getattr(config, "episode_abort_gate_paths", []),
            requested_mode=getattr(config, "episode_abort_mode", "off"),
            runtime_provenance=runtime_episode_abort_provenance(config),
        )
        self.episode_abort_monitor = EpisodeAbortMonitor(self.episode_abort_runtime_gate_report)
        requested_abort_mode = str(getattr(config, "episode_abort_mode", "off") or "off").lower()
        if requested_abort_mode != "off" or getattr(config, "episode_abort_gate_paths", []):
            self.session_logger.log("episode_abort_runtime_gate", {
                "requested_mode": requested_abort_mode,
                "effective_mode": self.episode_abort_runtime_gate_report.get("effective_mode", "off"),
                "gate_readiness": self.episode_abort_runtime_gate_report.get("gate_readiness", "unknown"),
                "provenance_match": self.episode_abort_runtime_gate_report.get("provenance_match", False),
                "active_abort_allowed": self.episode_abort_runtime_gate_report.get("active_abort_allowed", False),
                "shadow_probe_allowed": self.episode_abort_runtime_gate_report.get("shadow_probe_allowed", False),
                "error_count": len(self.episode_abort_runtime_gate_report.get("errors", [])),
            })
        if requested_abort_mode != self.episode_abort_runtime_gate_report.get("effective_mode"):
            logger.warning(
                "Episode early abort disabled or downgraded: "
                f"requested={requested_abort_mode}, "
                f"effective={self.episode_abort_runtime_gate_report.get('effective_mode')}, "
                f"gate_readiness={self.episode_abort_runtime_gate_report.get('gate_readiness')}"
            )
        self.frontier_budget_runtime_provenance = runtime_frontier_budget_provenance(config)
        self.frontier_budget_runtime_gate_report = evaluate_frontier_budget_runtime_gate(
            getattr(config, "frontier_budget_gate_paths", []),
            requested_mode=getattr(config, "frontier_budget_mode", "off"),
            runtime_provenance=self.frontier_budget_runtime_provenance,
        )
        self.frontier_budget_controller = FrontierBudgetController(
            self.frontier_budget_runtime_gate_report,
            policy=getattr(config, "frontier_budget_policy", "information"),
            total_rounds=getattr(config, "frontier_budget_total_rounds", 8),
            temperature=getattr(config, "frontier_budget_temperature", 2.0),
            exploration_floor=getattr(config, "frontier_budget_exploration_floor", 1),
        )
        self._frontier_budget_active = {}
        self._frontier_budget_recovery_credit = {}
        requested_frontier_mode = str(getattr(config, "frontier_budget_mode", "off") or "off").lower()
        if requested_frontier_mode != "off" or getattr(config, "frontier_budget_gate_paths", []):
            self.session_logger.log("frontier_budget_runtime_gate", {
                "requested_mode": requested_frontier_mode,
                "effective_mode": self.frontier_budget_runtime_gate_report.get("effective_mode", "off"),
                "policy": self.frontier_budget_controller.policy,
                "gate_readiness": self.frontier_budget_runtime_gate_report.get("gate_readiness", "unknown"),
                "provenance_match": self.frontier_budget_runtime_gate_report.get("provenance_match", False),
                "shadow_allocation_allowed": self.frontier_budget_runtime_gate_report.get("shadow_allocation_allowed", False),
                "advisory_context_allowed": self.frontier_budget_runtime_gate_report.get("advisory_context_allowed", False),
                "automatic_retry_allowed": False,
                "automatic_branch_execution_allowed": False,
                "error_count": len(self.frontier_budget_runtime_gate_report.get("errors", [])),
            })
        if requested_frontier_mode != self.frontier_budget_runtime_gate_report.get("effective_mode"):
            logger.warning(
                "Frontier budget runtime disabled or downgraded: "
                f"requested={requested_frontier_mode}, "
                f"effective={self.frontier_budget_runtime_gate_report.get('effective_mode')}, "
                f"gate_readiness={self.frontier_budget_runtime_gate_report.get('gate_readiness')}"
            )

        # Integrated modules
        self.memory = MemorySystem(memory_dir=config.memory_dir)
        self.memory_attribution_runtime_gate_report = evaluate_memory_attribution_runtime_gate(
            getattr(config, "memory_attribution_gate_paths", []),
            enable_requested=getattr(config, "enable_weighted_memory_retrieval", False),
        )
        self.enable_weighted_memory_retrieval = bool(
            self.memory_attribution_runtime_gate_report.get("effective_enable_weighted_memory_retrieval")
        )
        self.memory_attribution_profile = self.memory.apply_memory_attribution_runtime_gate(
            self.memory_attribution_runtime_gate_report
        )
        if getattr(config, "enable_weighted_memory_retrieval", False) and not self.enable_weighted_memory_retrieval:
            logger.warning(
                "Weighted memory retrieval disabled: "
                f"gate_readiness={self.memory_attribution_runtime_gate_report.get('gate_readiness')}, "
                f"gate_paths={len(self.memory_attribution_runtime_gate_report.get('gate_paths', []))}"
            )
        self.memory_promptware_runtime_gate_report = evaluate_memory_promptware_runtime_gate(
            getattr(config, "memory_promptware_gate_paths", []),
            enforce_requested=getattr(config, "enforce_memory_write_gate", False),
        )
        effective_memory_write_gate = bool(self.memory_promptware_runtime_gate_report.get("effective_enforce_write_gate"))
        if getattr(config, "enforce_memory_write_gate", False) and not effective_memory_write_gate:
            logger.warning(
                "Strict memory write gate disabled: "
                f"gate_readiness={self.memory_promptware_runtime_gate_report.get('gate_readiness')}, "
                f"gate_paths={len(self.memory_promptware_runtime_gate_report.get('gate_paths', []))}"
            )
        self.memory_policy = (
            MemoryLifecyclePolicy(enforce_write_gate=effective_memory_write_gate)
            if getattr(config, "enable_memory_policy", True)
            else None
        )
        self.skill_library = SkillLibrary(storage_path=config.skill_dir, persist=True)
        self.skill_candidate_queue = None
        self.skill_extractor = None
        self.skill_learning_ledger = None
        if getattr(config, "enable_skill_candidate_extraction", False):
            from singularity.core.skill_extractor import SkillCandidateQueue, SkillExtractor
            from singularity.core.skill_learning import SkillLearningLedger

            self.skill_candidate_queue = SkillCandidateQueue(config.skill_candidate_queue_path)
            self.skill_extractor = SkillExtractor(
                self.skill_library,
                memory_system=self.memory,
                auto_promote=False,
            )
            self.skill_learning_ledger = SkillLearningLedger(config.skill_learning_ledger_path)
        elif str(getattr(config, "skill_execution_mode", "off") or "off").lower() != "off":
            from singularity.core.skill_learning import SkillLearningLedger

            self.skill_learning_ledger = SkillLearningLedger(config.skill_learning_ledger_path)
        self._active_skill_execution: dict = {}
        self._active_skill_advisory_hint = ""
        self._episode_deadline_monotonic = None
        self._last_autonomous_goal_decision: dict = {}
        self._m4_ready_task_goal_binding: dict = {}
        self._m4_readiness_recovery_bindings: dict[str, dict] = {}
        self._m4_readiness_recovery_propagated_roots: set[str] = set()
        self._m4_active_readiness_recovery_root_id = ""
        self._skill_fallback_goals: set[str] = set()
        self._applied_skill_fault_profiles: set[str] = set()
        self._skill_episode_start_index = 0
        self.skill_runtime_default_gate_report = self._load_skill_runtime_default_gates()
        self.skill_retirement_gate_report = self._load_skill_retirement_gates()
        self.skill_memory_quality_feedback_report = self._load_skill_memory_quality_feedback()
        self.knowledge_correction_feedback = {
            "dependency_corrections": [],
            "failure_action_memories": [],
            "policy_hints": [],
        }
        self.knowledge_correction_feedback_report = self._load_knowledge_correction_feedback()
        self.task_precondition_feedback = {
            "candidates": [],
            "policy_hints": [],
        }
        self.task_precondition_feedback_report = self._load_task_precondition_feedback()
        self.task_system = TaskSystem()
        self.goal_generator = GoalGenerator()
        self.curriculum = CurriculumManager()
        self.world_model_feedback_report = self._load_world_model_feedback()
        self.goal_verifier = GoalVerifier(skill_library=self.skill_library)
        self.m4_shelter_verifier = M4ShelterVerifier()
        self._m4_episode_block_delta = {"placed": {}, "removed": {}}
        self._m4_post_place_machine_observation = {}
        self._m4_shelter_verification_fingerprint = ""
        self._m4_hostile_safe_state_fingerprint = ""
        self._m4_player_lifecycle_fingerprint = ""
        self._m4_player_lifecycle_identity = ()
        self._m4_shelter_relocation = {}
        self._active_runtime_interrupt: dict = {}
        self._runtime_interrupt_sequence = 0
        self._last_runtime_interrupt_yield = ""
        self.goal_critic_gate_report = self._evaluate_goal_critic_runtime_gate()
        self.explorer = Explorer()
        self.rule_planner = RuleBasedPlanner()
        self.plan_cache = PlanTransitionCache(
            min_confidence=getattr(config, "plan_cache_min_confidence", 0.75)
        )
        self.plan_cache_runtime_gate_report = evaluate_plan_cache_runtime_gate(
            getattr(config, "plan_cache_gate_paths", []),
            enable_requested=getattr(config, "enable_plan_cache", False),
        )
        self.plan_cache_report = self._load_plan_cache()
        self._last_plan_cache_signature = START_PLAN_SIGNATURE
        self.runtime = RuntimeSupervisor(config, self.explorer)
        self.vision_analyzer = VisionAnalyzer(
            api_key=config.llm.api_key,
            provider=config.llm.provider,
            model=config.llm.model,
        )
        self.visual_memory = VisualMemory()
        self.visual_action_advisor = VisualActionAdvisor()
        self._last_screenshot_at = 0.0

        self._use_llm = bool(
            not getattr(config, "force_rule_planner", False)
            and (config.llm.api_key or os.environ.get("OPENAI_API_KEY"))
        )
        if self._use_llm:
            from singularity.llm.provider import LLMProvider
            from singularity.core.planner import Planner
            from singularity.core.reflector import Reflector
            from singularity.core.goal_verifier import GoalVerificationCritic
            self.llm = LLMProvider(config.llm)
            self.planner = Planner(
                self.llm,
                self.task_system,
                protocol=getattr(config, "planner_protocol", ""),
            )
            self.reflector = Reflector(self.llm)
            if getattr(config, "enable_goal_critic", False):
                if self.goal_critic_gate_report.get("gate_approved"):
                    self.goal_verifier.goal_critic = GoalVerificationCritic(self.llm)
                    logger.info("Goal verification critic enabled by approved runtime gate")
                else:
                    logger.warning(
                        "Goal verification critic disabled: "
                        f"gate_readiness={self.goal_critic_gate_report.get('gate_readiness')}, "
                        f"gate_paths={len(self.goal_critic_gate_report.get('gate_paths', []))}"
                    )
            logger.info("Using LLM planner with full module integration")
        else:
            self.reflector = None
            logger.info("No API key - using rule-based planner")

    def _load_plan_cache(self) -> dict:
        """Load approved AgenticCache-style plan-transition reports for runtime reuse."""
        paths = [
            path for path in (getattr(self.config, "plan_cache_paths", []) or [])
            if path
        ]
        gate_report = getattr(self, "plan_cache_runtime_gate_report", {})
        if not getattr(self.config, "enable_plan_cache", False):
            return {
                "enabled": False,
                "paths": list(paths),
                "errors": [],
                **gate_report,
                "loaded_entry_count": 0,
                "skipped_entry_count": len(paths),
                "reason": "plan cache disabled",
            }
        if not gate_report.get("effective_enable_plan_cache"):
            if paths:
                logger.warning(
                    "Plan cache loading skipped: "
                    f"gate_readiness={gate_report.get('gate_readiness')}, "
                    f"gate_paths={len(gate_report.get('gate_paths', []))}, "
                    f"cache_paths={len(paths)}"
                )
            return {
                "enabled": False,
                "paths": list(paths),
                "errors": [],
                **gate_report,
                "loaded_entry_count": 0,
                "skipped_entry_count": len(paths),
            }
        report = self.plan_cache.load_reports(paths, execution_profile=gate_report)
        load_errors = list(report.get("errors", []))
        report.update(gate_report)
        report["errors"] = load_errors + list(gate_report.get("errors", []))
        if paths and not report.get("loaded_entry_count"):
            logger.warning(
                "Plan cache enabled but no usable entries loaded: "
                f"paths={len(paths)}, errors={len(report.get('errors', []))}"
            )
        elif report.get("loaded_entry_count"):
            logger.info(f"Plan cache loaded {report['loaded_entry_count']} approved entries")
        return report

    def _load_mixed_policy_patches(self) -> dict:
        """Load approved mixed-initiative policy patches into runtime policy objects."""
        patch_paths = [
            path for path in (getattr(self.config, "mixed_policy_patch_paths", []) or [])
            if path
        ]
        gate_report = self._evaluate_mixed_policy_patch_gate()
        report = {
            "paths": list(patch_paths),
            "loaded_count": 0,
            "skipped_count": 0,
            "action_policy_hints_applied": 0,
            "mixed_policy_hints_applied": 0,
            "template_policy_update_count": 0,
            "errors": [],
            **gate_report,
        }
        if report["gate_required"] and not report["gate_approved"]:
            report["skipped_count"] = len(patch_paths)
            if patch_paths:
                logger.warning(
                    "Mixed policy patch loading skipped: "
                    f"gate_readiness={report['gate_readiness']}, "
                    f"gate_paths={len(report['gate_paths'])}, "
                    f"patch_paths={len(patch_paths)}"
                )
            return report

        for path in patch_paths:
            try:
                with open(path, "r", encoding="utf-8-sig") as f:
                    patch = json.load(f)
                applied = apply_mixed_initiative_policy_patch(
                    patch,
                    action_policy=self.action_policy,
                    mixed_policy=self.mixed_initiative_policy,
                )
                report["loaded_count"] += 1
                report["action_policy_hints_applied"] += int(applied.get("action_policy_hints_applied", 0) or 0)
                report["mixed_policy_hints_applied"] += int(applied.get("mixed_policy_hints_applied", 0) or 0)
                report["template_policy_update_count"] += int(applied.get("template_policy_update_count", 0) or 0)
            except Exception as e:
                message = f"{path}: {e}"
                report["errors"].append(message)
                logger.warning(f"Failed to load mixed policy patch {message}")
        if report["loaded_count"] or report["errors"]:
            logger.info(
                "Mixed policy patches loaded: "
                f"{report['loaded_count']} files, "
                f"action_hints={report['action_policy_hints_applied']}, "
                f"mixed_hints={report['mixed_policy_hints_applied']}, "
                f"errors={len(report['errors'])}"
            )
        return report

    def _load_self_evolution_feedback(self) -> dict:
        """Load advisory self-evolution feedback reports for planner context."""
        paths = [
            path for path in (getattr(self.config, "self_evolution_feedback_paths", []) or [])
            if path
        ]
        report = {
            "paths": list(paths),
            "loaded_count": 0,
            "skipped_count": 0,
            "policy_hints_applied": 0,
            "advisory_only": True,
            "errors": [],
        }
        if not getattr(self.config, "enable_self_evolution_policy", True):
            report["skipped_count"] = len(paths)
            return report
        for path in paths:
            try:
                with open(path, "r", encoding="utf-8-sig") as f:
                    payload = json.load(f)
                feedback = payload.get("self_evolution_feedback", payload) if isinstance(payload, dict) else {}
                applied = self.self_evolution_policy.record_self_evolution_feedback(feedback)
                report["loaded_count"] += 1
                report["policy_hints_applied"] += int(applied or 0)
            except Exception as e:
                message = f"{path}: {e}"
                report["errors"].append(message)
                logger.warning(f"Failed to load self-evolution feedback {message}")
        if report["loaded_count"] or report["errors"]:
            logger.info(
                "Self-evolution feedback loaded: "
                f"{report['loaded_count']} files, "
                f"hints={report['policy_hints_applied']}, "
                f"errors={len(report['errors'])}"
            )
        return report

    def _load_action_value_feedback(self) -> dict:
        """Load advisory action-value feedback into candidate scoring."""
        paths = [
            path for path in (getattr(self.config, "action_value_feedback_paths", []) or [])
            if path
        ]
        transition_gate_report = self._evaluate_action_value_transition_runtime_gate()
        report = {
            "paths": list(paths),
            "loaded_count": 0,
            "skipped_count": 0,
            "value_items_loaded": 0,
            "transition_values_loaded": 0,
            "transition_values_skipped": 0,
            "transition_values_suppressed_by_gate": 0,
            "transition_skip_reasons": {},
            "advisory_only": True,
            "errors": [],
            **transition_gate_report,
        }
        for path in paths:
            try:
                with open(path, "r", encoding="utf-8-sig") as f:
                    payload = json.load(f)
                feedback = payload.get("action_value_feedback", payload) if isinstance(payload, dict) else {}
                feedback = self._action_value_feedback_with_transition_gate(feedback, report)
                loaded = self.action_value_profile.merge_feedback(feedback)
                merge_report = dict(getattr(self.action_value_profile, "last_merge_report", {}) or {})
                report["loaded_count"] += 1
                report["value_items_loaded"] += int(loaded or 0)
                report["transition_values_loaded"] += int(merge_report.get("transition_values_loaded") or 0)
                report["transition_values_skipped"] += int(merge_report.get("transition_values_skipped") or 0)
                for reason, count in (merge_report.get("transition_skip_reasons", {}) or {}).items():
                    report["transition_skip_reasons"][reason] = (
                        report["transition_skip_reasons"].get(reason, 0) + int(count or 0)
                    )
            except Exception as e:
                message = f"{path}: {e}"
                report["errors"].append(message)
                logger.warning(f"Failed to load action-value feedback {message}")
        if report["loaded_count"] or report["errors"]:
            logger.info(
                "Action-value feedback loaded: "
                f"{report['loaded_count']} files, "
                f"items={report['value_items_loaded']}, "
                f"transitions={report['transition_values_loaded']}, "
                f"transition_skipped={report['transition_values_skipped']}, "
                f"transition_gate={report['transition_gate_readiness']}, "
                f"errors={len(report['errors'])}"
            )
        return report

    def _action_value_feedback_with_transition_gate(self, feedback: dict, report: dict) -> dict:
        feedback = feedback if isinstance(feedback, dict) else {}
        if report.get("transition_gate_approved", True):
            return feedback
        transition_items = feedback.get("state_transition_value_items", [])
        if not transition_items:
            return feedback
        transition_items = transition_items if isinstance(transition_items, list) else []
        gated_feedback = dict(feedback)
        gated_feedback["state_transition_value_items"] = []
        skipped = len(transition_items)
        report["transition_values_skipped"] += skipped
        report["transition_values_suppressed_by_gate"] += skipped
        reasons = report.setdefault("transition_skip_reasons", {})
        reasons["transition_runtime_gate_not_approved"] = (
            reasons.get("transition_runtime_gate_not_approved", 0) + skipped
        )
        return gated_feedback

    def _evaluate_action_value_transition_runtime_gate(self) -> dict:
        """Return whether ASV transition-value feedback may enter runtime scoring."""
        transition_gate_paths = [
            path for path in (getattr(self.config, "action_value_transition_gate_paths", []) or [])
            if path
        ]
        evaluator_report_paths = [
            path for path in (getattr(self.config, "action_value_transition_evaluator_report_paths", []) or [])
            if path
        ]
        report = {
            "transition_gate_paths": list(transition_gate_paths),
            "transition_evaluator_report_paths": list(evaluator_report_paths),
            "transition_gate_required": bool(transition_gate_paths or evaluator_report_paths),
            "transition_gate_approved": True,
            "transition_gate_readiness": "not_required",
            "transition_gate_reports": [],
        }
        if not report["transition_gate_required"]:
            return report

        report["transition_gate_approved"] = False
        readinesses = []
        for kind, paths in (
            ("transition_gate", transition_gate_paths),
            ("transition_evaluator", evaluator_report_paths),
        ):
            for path in paths:
                summary = {
                    "path": path,
                    "kind": kind,
                    "readiness": "error",
                    "decision": "",
                    "reason": "",
                }
                try:
                    with open(path, "r", encoding="utf-8-sig") as f:
                        gate = json.load(f)
                    readiness = str(gate.get("readiness", "")).strip().lower() or "unknown"
                    summary.update({
                        "readiness": readiness,
                        "decision": str(gate.get("decision", "")).strip(),
                        "reason": str(gate.get("reason", "")).strip()[:300],
                    })
                    for key in (
                        "trusted_item_count",
                        "trusted_transition_count",
                        "evaluated_count",
                        "agreement_rate",
                        "avg_abs_score_delta",
                    ):
                        if key in gate:
                            summary[key] = gate.get(key)
                except Exception as e:
                    readiness = "error"
                    summary["error"] = str(e)
                    logger.warning(f"Failed to load action-value transition {kind} {path}: {e}")
                readinesses.append(readiness)
                report["transition_gate_reports"].append(summary)

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
        return report

    def _load_skill_memory_quality_feedback(self) -> dict:
        """Load offline skill-memory quality feedback into retrieval ranking."""
        paths = [
            path for path in (getattr(self.config, "skill_memory_quality_feedback_paths", []) or [])
            if path
        ]
        gate_report = self._evaluate_skill_memory_quality_gate()
        report = {
            "paths": list(paths),
            "loaded_count": 0,
            "skipped_count": 0,
            "policy_hints_applied": 0,
            "advisory_only": True,
            "errors": [],
            **gate_report,
        }
        if report["gate_required"] and not report["gate_approved"]:
            report["skipped_count"] = len(paths)
            if paths:
                logger.warning(
                    "Skill-memory quality feedback loading skipped: "
                    f"gate_readiness={report['gate_readiness']}, "
                    f"gate_paths={len(report['gate_paths'])}, "
                    f"feedback_paths={len(paths)}"
                )
            return report
        if not getattr(self.config, "enable_skill_memory_context", True):
            report["skipped_count"] = len(paths)
            return report
        for path in paths:
            try:
                with open(path, "r", encoding="utf-8-sig") as f:
                    payload = json.load(f)
                feedback = payload.get("skill_memory_quality_feedback", payload) if isinstance(payload, dict) else {}
                applied = self.skill_library.record_skill_memory_quality_feedback(feedback)
                report["loaded_count"] += 1
                report["policy_hints_applied"] += int(applied or 0)
            except Exception as e:
                message = f"{path}: {e}"
                report["errors"].append(message)
                logger.warning(f"Failed to load skill-memory quality feedback {message}")
        if report["loaded_count"] or report["errors"]:
            logger.info(
                "Skill-memory quality feedback loaded: "
                f"{report['loaded_count']} files, "
                f"hints={report['policy_hints_applied']}, "
                f"errors={len(report['errors'])}"
            )
        return report

    def _evaluate_skill_memory_quality_gate(self) -> dict:
        """Return whether runtime skill-memory quality feedback may be loaded."""
        gate_paths = [
            path for path in (getattr(self.config, "skill_memory_quality_gate_paths", []) or [])
            if path
        ]
        report = {
            "gate_paths": list(gate_paths),
            "gate_required": bool(gate_paths),
            "gate_approved": True,
            "gate_readiness": "not_required",
            "gate_reports": [],
        }
        if not gate_paths:
            return report

        report["gate_approved"] = False
        readinesses = []
        for path in gate_paths:
            gate_summary = {
                "path": path,
                "readiness": "error",
                "decision": "",
                "reason": "",
            }
            try:
                with open(path, "r", encoding="utf-8-sig") as f:
                    gate = json.load(f)
                readiness = str(gate.get("readiness", "")).strip().lower() or "unknown"
                gate_summary.update({
                    "readiness": readiness,
                    "decision": str(gate.get("decision", "")).strip(),
                    "reason": str(gate.get("reason", "")).strip()[:300],
                    "approved_count": self._small_int(gate.get("approved_count", 0)),
                    "rejected_count": self._small_int(gate.get("rejected_count", 0)),
                })
            except Exception as e:
                readiness = "error"
                gate_summary["error"] = str(e)
                logger.warning(f"Failed to load skill-memory quality gate {path}: {e}")
            readinesses.append(readiness)
            report["gate_reports"].append(gate_summary)

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
        return report

    def _load_knowledge_correction_feedback(self) -> dict:
        """Load gated XENON-style knowledge corrections for planner context."""
        paths = [
            path for path in (getattr(self.config, "knowledge_correction_feedback_paths", []) or [])
            if path
        ]
        gate_report = self._evaluate_knowledge_correction_gate(paths)
        report = {
            "paths": list(paths),
            "loaded_count": 0,
            "skipped_count": 0,
            "dependency_correction_count": 0,
            "failure_action_memory_count": 0,
            "context_item_count": 0,
            "policy_hints_applied": 0,
            "advisory_only": True,
            "errors": [],
            **gate_report,
        }
        if not getattr(self.config, "enable_knowledge_correction_context", True):
            report["skipped_count"] = len(paths)
            return report
        if report["gate_required"] and not report["gate_approved"]:
            report["skipped_count"] = len(paths)
            if paths:
                logger.warning(
                    "Knowledge-correction feedback loading skipped: "
                    f"gate_readiness={report['gate_readiness']}, "
                    f"gate_paths={len(report['gate_paths'])}, "
                    f"feedback_paths={len(paths)}"
                )
            return report

        for path in paths:
            try:
                with open(path, "r", encoding="utf-8-sig") as f:
                    payload = json.load(f)
                feedback = payload.get("knowledge_correction_feedback", payload) if isinstance(payload, dict) else {}
                if not isinstance(feedback, dict):
                    raise ValueError("knowledge-correction feedback JSON must contain an object")
                applied = self._record_knowledge_correction_feedback(feedback)
                report["loaded_count"] += 1
                report["dependency_correction_count"] += int(applied.get("dependency_corrections", 0) or 0)
                report["failure_action_memory_count"] += int(applied.get("failure_action_memories", 0) or 0)
                report["policy_hints_applied"] += int(applied.get("policy_hints", 0) or 0)
            except Exception as e:
                message = f"{path}: {e}"
                report["errors"].append(message)
                logger.warning(f"Failed to load knowledge-correction feedback {message}")
        report["context_item_count"] = (
            len(self.knowledge_correction_feedback.get("dependency_corrections", []))
            + len(self.knowledge_correction_feedback.get("failure_action_memories", []))
        )
        if report["loaded_count"] or report["errors"]:
            logger.info(
                "Knowledge-correction feedback loaded: "
                f"{report['loaded_count']} files, "
                f"dependency={report['dependency_correction_count']}, "
                f"failed_memories={report['failure_action_memory_count']}, "
                f"gate={report['gate_readiness']}, "
                f"errors={len(report['errors'])}"
            )
        return report

    def _load_task_precondition_feedback(self) -> dict:
        """Load gated hidden-prerequisite feedback for planner context."""
        paths = [
            path for path in (getattr(self.config, "task_precondition_feedback_paths", []) or [])
            if path
        ]
        gate_report = self._evaluate_task_precondition_gate(paths)
        report = {
            "paths": list(paths),
            "loaded_count": 0,
            "skipped_count": 0,
            "candidate_count": 0,
            "policy_hints_applied": 0,
            "advisory_only": True,
            "errors": [],
            **gate_report,
        }
        if not getattr(self.config, "enable_task_precondition_context", True):
            report["skipped_count"] = len(paths)
            return report
        if report["gate_required"] and not report["gate_approved"]:
            report["skipped_count"] = len(paths)
            if paths:
                logger.warning(
                    "Task-precondition feedback loading skipped: "
                    f"gate_readiness={report['gate_readiness']}, "
                    f"gate_paths={len(report['gate_paths'])}, "
                    f"feedback_paths={len(paths)}"
                )
            return report

        for path in paths:
            try:
                with open(path, "r", encoding="utf-8-sig") as f:
                    payload = json.load(f)
                feedback = payload.get("task_precondition_feedback", payload) if isinstance(payload, dict) else {}
                if not isinstance(feedback, dict):
                    raise ValueError("task-precondition feedback JSON must contain an object")
                applied = self._record_task_precondition_feedback(feedback)
                report["loaded_count"] += 1
                report["candidate_count"] += int(applied.get("candidates", 0) or 0)
                report["policy_hints_applied"] += int(applied.get("policy_hints", 0) or 0)
            except Exception as e:
                message = f"{path}: {e}"
                report["errors"].append(message)
                logger.warning(f"Failed to load task-precondition feedback {message}")
        if report["loaded_count"] or report["errors"]:
            logger.info(
                "Task-precondition feedback loaded: "
                f"{report['loaded_count']} files, "
                f"candidates={report['candidate_count']}, "
                f"gate={report['gate_readiness']}, "
                f"errors={len(report['errors'])}"
            )
        return report

    def _evaluate_task_precondition_gate(self, feedback_paths: list[str]) -> dict:
        """Return whether saved task-precondition candidates may influence planner context."""
        gate_paths = [
            path for path in (getattr(self.config, "task_precondition_gate_paths", []) or [])
            if path
        ]
        report = {
            "gate_paths": list(gate_paths),
            "gate_required": bool(feedback_paths),
            "gate_approved": not bool(feedback_paths),
            "gate_readiness": "not_required" if not feedback_paths else "missing",
            "gate_reports": [],
        }
        if not feedback_paths:
            return report
        if not gate_paths:
            return report

        readinesses = []
        for path in gate_paths:
            gate_summary = {
                "path": path,
                "readiness": "error",
                "decision": "",
                "reason": "",
            }
            try:
                with open(path, "r", encoding="utf-8-sig") as f:
                    gate = json.load(f)
                readiness = str(gate.get("readiness", "")).strip().lower() or "unknown"
                gate_summary.update({
                    "readiness": readiness,
                    "decision": str(gate.get("decision", "")).strip(),
                    "reason": str(gate.get("reason", "")).strip()[:300],
                    "source_count": self._small_int(gate.get("source_count", 0)),
                    "ready_log_count": self._small_int(gate.get("ready_log_count", 0)),
                    "candidate_count": self._small_int(gate.get("candidate_count", 0)),
                    "high_confidence_candidate_count": self._small_int(gate.get("high_confidence_candidate_count", 0)),
                })
            except Exception as e:
                readiness = "error"
                gate_summary["error"] = str(e)
                logger.warning(f"Failed to load task-precondition gate {path}: {e}")
            readinesses.append(readiness)
            report["gate_reports"].append(gate_summary)

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
        return report

    def _record_task_precondition_feedback(self, feedback: dict) -> dict:
        feedback = feedback if isinstance(feedback, dict) else {}
        applied = {"candidates": 0, "policy_hints": 0}
        for key in ("candidates", "policy_hints"):
            incoming = feedback.get(key, [])
            if not isinstance(incoming, list):
                continue
            existing = self.task_precondition_feedback.setdefault(key, [])
            seen = {
                self._task_precondition_identity(key, item)
                for item in existing
                if isinstance(item, dict)
            }
            for item in incoming:
                if not isinstance(item, dict):
                    continue
                identity = self._task_precondition_identity(key, item)
                if identity in seen:
                    continue
                existing.append(dict(item))
                seen.add(identity)
                applied[key] += 1
        return applied

    def _task_precondition_identity(self, key: str, item: dict) -> str:
        if key == "candidates":
            return "|".join([
                str(item.get("candidate_id", "")),
                str(item.get("goal_signature", "")),
                str(item.get("action_signature", "")),
                json.dumps(item.get("inferred_preconditions", {}), sort_keys=True, default=str),
            ])
        if key == "policy_hints":
            return str(item.get("task_precondition_policy") or item.get("policy") or item)
        return str(item)

    def _evaluate_knowledge_correction_gate(self, feedback_paths: list[str]) -> dict:
        """Return whether saved knowledge corrections may influence planner context."""
        gate_paths = [
            path for path in (getattr(self.config, "knowledge_correction_gate_paths", []) or [])
            if path
        ]
        report = {
            "gate_paths": list(gate_paths),
            "gate_required": bool(feedback_paths),
            "gate_approved": not bool(feedback_paths),
            "gate_readiness": "not_required" if not feedback_paths else "missing",
            "gate_reports": [],
        }
        if not feedback_paths:
            return report
        if not gate_paths:
            return report

        readinesses = []
        for path in gate_paths:
            gate_summary = {
                "path": path,
                "readiness": "error",
                "decision": "",
                "reason": "",
            }
            try:
                with open(path, "r", encoding="utf-8-sig") as f:
                    gate = json.load(f)
                readiness = str(gate.get("readiness", "")).strip().lower() or "unknown"
                gate_summary.update({
                    "readiness": readiness,
                    "decision": str(gate.get("decision", "")).strip(),
                    "reason": str(gate.get("reason", "")).strip()[:300],
                    "source_count": self._small_int(gate.get("source_count", 0)),
                    "ready_log_count": self._small_int(gate.get("ready_log_count", 0)),
                    "correction_count": self._small_int(gate.get("correction_count", 0)),
                    "dependency_correction_count": self._small_int(gate.get("dependency_correction_count", 0)),
                    "failure_action_memory_count": self._small_int(gate.get("failure_action_memory_count", 0)),
                })
            except Exception as e:
                readiness = "error"
                gate_summary["error"] = str(e)
                logger.warning(f"Failed to load knowledge-correction gate {path}: {e}")
            readinesses.append(readiness)
            report["gate_reports"].append(gate_summary)

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
        return report

    def _record_knowledge_correction_feedback(self, feedback: dict) -> dict:
        feedback = feedback if isinstance(feedback, dict) else {}
        applied = {
            "dependency_corrections": 0,
            "failure_action_memories": 0,
            "policy_hints": 0,
        }
        for key in ("dependency_corrections", "failure_action_memories", "policy_hints"):
            incoming = feedback.get(key, [])
            if not isinstance(incoming, list):
                continue
            existing = self.knowledge_correction_feedback.setdefault(key, [])
            seen = {
                self._knowledge_correction_identity(key, item)
                for item in existing
                if isinstance(item, dict)
            }
            for item in incoming:
                if not isinstance(item, dict):
                    continue
                identity = self._knowledge_correction_identity(key, item)
                if identity in seen:
                    continue
                existing.append(dict(item))
                seen.add(identity)
                applied[key] += 1
        return applied

    def _knowledge_correction_identity(self, key: str, item: dict) -> str:
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
        return str(item)

    def _load_skill_runtime_default_gates(self) -> dict:
        """Load task-family runtime-default skill gates into the skill library."""
        gate_paths = [
            path for path in (getattr(self.config, "skill_runtime_default_gate_paths", []) or [])
            if path
        ]
        report = {
            "gate_paths": list(gate_paths),
            "gate_required": bool(gate_paths),
            "gate_approved": True,
            "gate_readiness": "not_required",
            "loaded_count": 0,
            "skipped_count": 0,
            "approved_skill_count": 0,
            "gate_reports": [],
            "errors": [],
        }
        if not gate_paths:
            return report

        readinesses = []
        loaded_gates = []
        for path in gate_paths:
            summary = {
                "path": path,
                "readiness": "error",
                "decision": "",
                "reason": "",
                "approved_candidate_count": 0,
                "target_task_family": "",
            }
            try:
                with open(path, "r", encoding="utf-8-sig") as f:
                    gate = json.load(f)
                readiness = str(gate.get("readiness", "")).strip().lower() or "unknown"
                summary.update({
                    "readiness": readiness,
                    "decision": str(gate.get("decision", "")).strip(),
                    "reason": str(gate.get("reason", "")).strip()[:300],
                    "approved_candidate_count": self._small_int(gate.get("approved_candidate_count", 0)),
                    "target_task_family": str(gate.get("target_task_family", "")).strip().lower(),
                })
                loaded_gates.append(gate)
            except Exception as e:
                readiness = "error"
                summary["error"] = str(e)
                report["errors"].append(f"{path}: {e}")
                logger.warning(f"Failed to load skill runtime-default gate {path}: {e}")
            readinesses.append(readiness)
            report["gate_reports"].append(summary)

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

        if not report["gate_approved"]:
            self.skill_library.record_skill_runtime_default_gate({
                "readiness": report["gate_readiness"],
                "decision": "keep_runtime_default_review_only",
                "reason": "configured runtime-default gate is not approved",
                "paths": gate_paths,
                "candidates": [],
            })
            report["skipped_count"] = len(gate_paths)
            logger.warning(
                "Skill runtime-default gate loading skipped: "
                f"gate_readiness={report['gate_readiness']}, gate_paths={len(gate_paths)}"
            )
            return report

        for gate in loaded_gates:
            applied = self.skill_library.record_skill_runtime_default_gate(gate)
            report["loaded_count"] += 1
            report["approved_skill_count"] += int(applied or 0)
        logger.info(
            "Skill runtime-default gates loaded: "
            f"{report['loaded_count']} files, approved_skills={report['approved_skill_count']}"
        )
        return report

    def _load_skill_retirement_gates(self) -> dict:
        """Load approved runtime-only skill quarantine overlays."""
        gate_paths = [
            path for path in (getattr(self.config, "skill_retirement_gate_paths", []) or [])
            if path
        ]
        report = {
            "gate_paths": list(gate_paths),
            "gate_required": bool(gate_paths),
            "gate_approved": False,
            "gate_readiness": "not_required",
            "loaded_count": 0,
            "skipped_count": 0,
            "quarantined_skill_count": 0,
            "automatic_delete_allowed": False,
            "gate_reports": [],
            "errors": [],
        }
        if not gate_paths:
            return report

        readinesses = []
        loaded_gates = []
        for path in gate_paths:
            summary = {
                "path": path,
                "readiness": "error",
                "decision": "",
                "reason": "",
                "approved_candidate_count": 0,
                "soft_quarantine_allowed": False,
                "automatic_delete_allowed": False,
            }
            try:
                with open(path, "r", encoding="utf-8-sig") as f:
                    gate = json.load(f)
                if gate.get("type") != "skill_retirement_gate" or self._small_int(gate.get("schema_version")) != 1:
                    raise ValueError("expected skill_retirement_gate schema 1")
                readiness = str(gate.get("readiness") or "unknown").strip().lower()
                thresholds = gate.get("thresholds", {}) if isinstance(gate.get("thresholds"), dict) else {}
                approved_candidates = [
                    candidate for candidate in gate.get("candidates", [])
                    if isinstance(candidate, dict) and candidate.get("candidate_readiness") == "approved"
                ] if isinstance(gate.get("candidates"), list) else []
                min_sessions = max(1, self._small_int(thresholds.get("min_distinct_candidate_sessions", 3)))
                candidates_safe = bool(approved_candidates) and all(
                    str(candidate.get("skill") or "").strip()
                    and str(candidate.get("task_family") or "").strip()
                    and candidate.get("automatic_delete_allowed") is False
                    and not candidate.get("issues")
                    and len(candidate.get("candidate_session_ids", [])) >= min_sessions
                    and bool(candidate.get("judge_ids"))
                    and bool(candidate.get("verifier_ids"))
                    for candidate in approved_candidates
                )
                safe_overlay = (
                    gate.get("soft_quarantine_allowed") is True
                    and gate.get("automatic_delete_allowed") is False
                    and gate.get("deletion_policy") == "prohibited"
                    and thresholds.get("require_live_evidence") is True
                    and self._small_int(gate.get("approved_candidate_count")) == len(approved_candidates)
                    and candidates_safe
                )
                if readiness == "approved" and not safe_overlay:
                    readiness = "rejected"
                summary.update({
                    "readiness": readiness,
                    "decision": str(gate.get("decision") or "").strip(),
                    "reason": str(gate.get("reason") or "").strip()[:300],
                    "approved_candidate_count": self._small_int(gate.get("approved_candidate_count", 0)),
                    "soft_quarantine_allowed": gate.get("soft_quarantine_allowed") is True,
                    "automatic_delete_allowed": False,
                })
                loaded_gates.append(gate)
            except Exception as e:
                readiness = "error"
                summary["error"] = str(e)
                report["errors"].append(f"{path}: {e}")
                logger.warning(f"Failed to load skill retirement gate {path}: {e}")
            readinesses.append(readiness)
            report["gate_reports"].append(summary)

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

        if not report["gate_approved"]:
            self.skill_library.record_skill_retirement_gate({
                "readiness": report["gate_readiness"],
                "decision": "keep_skills_active_pending_retirement_review",
                "reason": "configured skill retirement gate is not approved",
                "paths": gate_paths,
                "soft_quarantine_allowed": False,
                "automatic_delete_allowed": False,
                "candidates": [],
            })
            report["skipped_count"] = len(gate_paths)
            logger.warning(
                "Skill retirement gate loading skipped: "
                f"gate_readiness={report['gate_readiness']}, gate_paths={len(gate_paths)}"
            )
            return report

        for gate, path in zip(loaded_gates, gate_paths):
            gate = dict(gate)
            gate["paths"] = [path]
            applied = self.skill_library.record_skill_retirement_gate(gate)
            report["loaded_count"] += 1
            report["quarantined_skill_count"] += int(applied or 0)
        logger.info(
            "Skill retirement gates loaded: "
            f"{report['loaded_count']} files, quarantined_skills={report['quarantined_skill_count']}"
        )
        return report

    def _small_int(self, value) -> int:
        try:
            return int(float(value or 0))
        except (TypeError, ValueError):
            return 0

    def _small_float(self, value) -> float:
        try:
            return float(value or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def _evaluate_goal_critic_runtime_gate(self) -> dict:
        """Return whether the LLM goal critic may affect runtime completion checks."""
        gate_paths = [
            path for path in (getattr(self.config, "goal_critic_gate_paths", []) or [])
            if path
        ]
        gate_requested = bool(getattr(self.config, "enable_goal_critic", False))
        report = {
            "gate_paths": list(gate_paths),
            "gate_required": gate_requested,
            "gate_approved": not gate_requested,
            "gate_readiness": "not_requested" if not gate_requested else "review",
            "gate_reports": [],
            "missing": [],
            "errors": [],
        }
        if not gate_requested:
            return report
        if not gate_paths:
            report["missing"].append("goal_critic_gate")
            return report

        report["gate_approved"] = False
        readinesses = []
        for path in gate_paths:
            summary = {
                "path": path,
                "readiness": "error",
                "decision": "",
                "reason": "",
                "approved_count": 0,
            }
            try:
                with open(path, "r", encoding="utf-8-sig") as f:
                    gate = json.load(f)
                readiness = str(gate.get("readiness", "")).strip().lower() or "unknown"
                summary.update({
                    "readiness": readiness,
                    "decision": str(gate.get("decision", "")).strip(),
                    "reason": str(gate.get("reason", "")).strip()[:300],
                    "approved_count": self._small_int(gate.get("approved_count", 0)),
                })
            except Exception as e:
                readiness = "error"
                summary["error"] = str(e)
                report["errors"].append(f"{path}: {e}")
                logger.warning(f"Failed to load goal critic gate {path}: {e}")
            readinesses.append(readiness)
            report["gate_reports"].append(summary)

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
        return report

    def _load_world_model_feedback(self) -> dict:
        """Load gated world-model feedback into autonomous curriculum scoring."""
        paths = [
            path for path in (getattr(self.config, "world_model_feedback_paths", []) or [])
            if path
        ]
        gate_report = self._evaluate_world_model_feedback_gate(paths)
        report = {
            "paths": list(paths),
            "loaded_count": 0,
            "skipped_count": 0,
            "frontier_count": 0,
            "resource_hotspot_count": 0,
            "danger_cell_count": 0,
            "suggested_goal_count": 0,
            "advisory_only": True,
            "errors": [],
            **gate_report,
        }
        if not getattr(self.config, "enable_world_model_curriculum_feedback", True):
            report["skipped_count"] = len(paths)
            return report
        if report["gate_required"] and not report["gate_approved"]:
            report["skipped_count"] = len(paths)
            if paths:
                logger.warning(
                    "World-model feedback loading skipped: "
                    f"gate_readiness={report['gate_readiness']}, "
                    f"gate_paths={len(report['gate_paths'])}, "
                    f"feedback_paths={len(paths)}"
                )
            return report

        for path in paths:
            try:
                with open(path, "r", encoding="utf-8-sig") as f:
                    payload = json.load(f)
                feedback = payload.get("world_model_feedback", payload) if isinstance(payload, dict) else {}
                if not isinstance(feedback, dict):
                    raise ValueError("world-model feedback JSON must contain an object")
                self.curriculum.record_world_model_feedback(feedback)
                report["loaded_count"] += 1
                report["frontier_count"] += self._small_int(feedback.get("frontier_count", 0))
                report["resource_hotspot_count"] += self._small_int(feedback.get("resource_hotspot_count", 0))
                report["danger_cell_count"] += self._small_int(feedback.get("danger_cell_count", 0))
                report["suggested_goal_count"] += len(
                    feedback.get("suggested_goals", []) if isinstance(feedback.get("suggested_goals", []), list) else []
                )
            except Exception as e:
                message = f"{path}: {e}"
                report["errors"].append(message)
                logger.warning(f"Failed to load world-model feedback {message}")
        if report["loaded_count"] or report["errors"]:
            logger.info(
                "World-model feedback loaded: "
                f"{report['loaded_count']} files, "
                f"frontiers={report['frontier_count']}, "
                f"hotspots={report['resource_hotspot_count']}, "
                f"gate={report['gate_readiness']}, "
                f"errors={len(report['errors'])}"
            )
        return report

    def _evaluate_world_model_feedback_gate(self, feedback_paths: list[str]) -> dict:
        """Return whether saved world-model feedback may influence curriculum goals."""
        gate_paths = [
            path for path in (getattr(self.config, "world_model_gate_paths", []) or [])
            if path
        ]
        report = {
            "gate_paths": list(gate_paths),
            "gate_required": bool(feedback_paths),
            "gate_approved": not bool(feedback_paths),
            "gate_readiness": "not_required" if not feedback_paths else "missing",
            "gate_reports": [],
        }
        if not feedback_paths:
            return report
        if not gate_paths:
            return report

        readinesses = []
        for path in gate_paths:
            gate_summary = {
                "path": path,
                "readiness": "error",
                "decision": "",
                "reason": "",
            }
            try:
                with open(path, "r", encoding="utf-8-sig") as f:
                    gate = json.load(f)
                readiness = str(gate.get("readiness", "")).strip().lower() or "unknown"
                gate_summary.update({
                    "readiness": readiness,
                    "decision": str(gate.get("decision", "")).strip(),
                    "reason": str(gate.get("reason", "")).strip()[:300],
                    "ready_log_count": self._small_int(gate.get("ready_log_count", 0)),
                    "frontier_count": self._small_int(gate.get("frontier_count", 0)),
                    "resource_hotspot_count": self._small_int(gate.get("resource_hotspot_count", 0)),
                })
            except Exception as e:
                readiness = "error"
                gate_summary["error"] = str(e)
                logger.warning(f"Failed to load world-model feedback gate {path}: {e}")
            readinesses.append(readiness)
            report["gate_reports"].append(gate_summary)

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
        return report

    def _evaluate_mixed_policy_patch_gate(self) -> dict:
        """Return whether runtime policy patches may be loaded under configured gates."""
        gate_paths = [
            path for path in (getattr(self.config, "mixed_policy_gate_paths", []) or [])
            if path
        ]
        report = {
            "gate_paths": list(gate_paths),
            "gate_required": bool(gate_paths),
            "gate_approved": True,
            "gate_readiness": "not_required",
            "gate_reports": [],
        }
        if not gate_paths:
            return report

        report["gate_approved"] = False
        readinesses = []
        for path in gate_paths:
            gate_summary = {
                "path": path,
                "readiness": "error",
                "decision": "",
                "reason": "",
            }
            try:
                with open(path, "r", encoding="utf-8-sig") as f:
                    gate = json.load(f)
                readiness = str(gate.get("readiness", "")).strip().lower() or "unknown"
                gate_summary.update({
                    "readiness": readiness,
                    "decision": str(gate.get("decision", "")).strip(),
                    "reason": str(gate.get("reason", "")).strip()[:300],
                })
            except Exception as e:
                readiness = "error"
                gate_summary["error"] = str(e)
                logger.warning(f"Failed to load mixed policy gate {path}: {e}")
            readinesses.append(readiness)
            report["gate_reports"].append(gate_summary)

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
        return report

    def connect(self) -> bool:
        logger.info(f"Connecting to {self.config.bot.host}:{self.config.bot.port}")
        success = self.bot.connect()
        self.session_logger.log_connect(self.config.bot.host, self.config.bot.port, success)
        if success:
            logger.info("Connected successfully")
            # Set explorer base to spawn position
            state = self.bot.get_player_state()
            pos = state.get("position", {})
            self.explorer.set_base(pos.get("x", 0), pos.get("y", 64), pos.get("z", 0))
        else:
            logger.error("Connection failed")
        return success

    def disconnect(self):
        self.running = False
        self._manage_memory_save_session()
        self.bot.disconnect()
        self.session_logger.close()

    # ── Goal-directed mode ──────────────────────────────────────────────

    def run_goal(
        self,
        goal: str,
        max_cycles: int = 100,
        max_duration_s: Optional[float] = None,
        episode_deadline_monotonic: Optional[float] = None,
        per_action_timeout_s: Optional[float] = None,
        max_actions: Optional[int] = None,
        deadline_policy_id: str = "",
    ) -> dict:
        """Pursue a specific natural-language goal."""
        try:
            max_cycles = max(1, int(max_cycles))
        except (TypeError, ValueError):
            max_cycles = 100
        try:
            max_duration_s = float(max_duration_s) if max_duration_s is not None else None
        except (TypeError, ValueError):
            max_duration_s = None
        if max_duration_s is not None and max_duration_s <= 0:
            max_duration_s = None
        if max_actions is not None:
            try:
                if isinstance(max_actions, bool):
                    raise ValueError
                max_actions = int(max_actions)
            except (TypeError, ValueError):
                raise ValueError("max_actions must be a positive integer")
            if max_actions <= 0:
                raise ValueError("max_actions must be a positive integer")
        strict_deadline_binding = episode_deadline_monotonic is not None
        if strict_deadline_binding:
            try:
                episode_deadline_monotonic = float(episode_deadline_monotonic)
            except (TypeError, ValueError) as exc:
                raise ValueError("episode_deadline_monotonic must be finite") from exc
            if not math.isfinite(episode_deadline_monotonic):
                raise ValueError("episode_deadline_monotonic must be finite")
        if per_action_timeout_s is not None:
            try:
                per_action_timeout_s = float(per_action_timeout_s)
            except (TypeError, ValueError) as exc:
                raise ValueError("per_action_timeout_s must be positive") from exc
            if not math.isfinite(per_action_timeout_s) or per_action_timeout_s <= 0:
                raise ValueError("per_action_timeout_s must be positive")

        self.current_goal = goal
        self._last_plan_cache_signature = START_PLAN_SIGNATURE
        self._skill_episode_start_index = len(getattr(self.session_logger, "events", []))
        self._active_skill_execution = {}
        self._skill_fallback_goals.discard(self._goal_fingerprint(goal))
        self._m2_root_plan_valid = False
        self._m2_skill_contribution_complete = False
        planner = getattr(self, "planner", None)
        strict_m2 = str(getattr(self.config, "planner_protocol", "") or "") == "m2-fixed-v1"
        deadline_policy = {}
        action_guard_s = 0.0
        if strict_m2:
            from singularity.evaluation.m2_protocol import PROTOCOL as M2_PROTOCOL

            deadline_policy = dict(M2_PROTOCOL["deadline_policy"])
            action_guard_s = float(deadline_policy["action_guard_ms"]) / 1000.0
        if hasattr(planner, "start_episode"):
            planner.start_episode(
                goal,
                str(getattr(self.session_logger, "session_id", "") or ""),
            )
        self.running = True
        logger.info(f"Starting goal: {goal}")
        self.session_logger.log_goal_start(goal)
        goal_limits = {
            "max_cycles": max_cycles,
            "max_duration_s": max_duration_s,
            "max_actions": max_actions,
            "deadline_policy_id": str(deadline_policy_id or ""),
            "per_action_timeout_s": per_action_timeout_s,
        }
        if strict_m2:
            goal_limits.update({
                "deadline_policy_id": str(deadline_policy["id"]),
                "action_guard_ms": int(deadline_policy["action_guard_ms"]),
            })
        self.session_logger.log("goal_limits", goal_limits)
        self._write_memory_episode("goal_start", {"goal": goal}, source="run_goal")

        started_at = time.monotonic()
        deadline_monotonic = (
            started_at + max_duration_s if max_duration_s is not None else None
        )
        if strict_deadline_binding:
            deadline_monotonic = min(
                value
                for value in (deadline_monotonic, episode_deadline_monotonic)
                if value is not None
            )
        action_controller = getattr(self, "action_controller", None)
        previous_episode_deadline = getattr(self, "_episode_deadline_monotonic", None)
        previous_action_deadline = getattr(action_controller, "_episode_deadline_monotonic", None)
        previous_action_timeout = getattr(action_controller, "_action_timeout_limit_s", None)
        if strict_deadline_binding:
            self._episode_deadline_monotonic = deadline_monotonic
            if hasattr(action_controller, "set_episode_deadline"):
                action_controller.set_episode_deadline(
                    deadline_monotonic,
                    per_action_timeout_s,
                )
        if hasattr(planner, "set_deadline"):
            planner.set_deadline(deadline_monotonic, action_guard_s if strict_m2 else 0.0)
        deadline_event_logged = False

        def deadline_exceeded(phase: str, *, action_suppressed: bool = True) -> bool:
            nonlocal deadline_event_logged
            if deadline_monotonic is None:
                return False
            now = time.monotonic()
            if now < deadline_monotonic:
                return False
            if not deadline_event_logged:
                elapsed = now - started_at
                effective_duration = (
                    max_duration_s
                    if max_duration_s is not None
                    else max(0.0, deadline_monotonic - started_at)
                )
                payload = {
                    "policy_id": str(
                        deadline_policy_id
                        or deadline_policy.get("id")
                        or "goal-max-duration-v1"
                    ),
                    "phase": str(phase),
                    "max_duration_s": effective_duration,
                    "elapsed_s": round(elapsed, 3),
                    "overrun_s": round(max(0.0, elapsed - effective_duration), 3),
                    "action_suppressed": bool(action_suppressed),
                }
                self.session_logger.log("goal_deadline_exceeded", payload, level="ERROR")
                logger.warning(
                    f"Goal deadline reached during {phase}: {elapsed:.3f}s >= {max_duration_s:.3f}s"
                )
                deadline_event_logged = True
            return True

        cycle = 0
        success = False
        success_at = None
        last_observation = {}
        last_plan = {}
        termination_reason = ""
        action_count = 0

        while self.running and cycle < max_cycles:
            if deadline_exceeded("cycle_start"):
                termination_reason = "max_duration"
                break
            cycle += 1
            try:
                observation = self._observe()
                last_observation = observation
                self.session_logger.log_observation(observation)
                self._write_memory_context(
                    {"cycle": cycle, "observation_summary": self._obs_summary(observation)},
                    source="goal_observation",
                )
                self.explorer.record_position(observation.get("position", {}))
                if deadline_exceeded("post_observation"):
                    termination_reason = "max_duration"
                    break

                plan = self._think(observation)
                last_plan = plan
                self.session_logger.log_plan(plan)
                self._write_memory_context(
                    {"plan_status": plan.get("status"), "reasoning": plan.get("reasoning", "")[:200]},
                    source="goal_plan",
                )
                if deadline_exceeded("post_planner"):
                    termination_reason = "max_duration"
                    break
                self._accept_planned_tasks()
                self._record_task_continuity(
                    goal,
                    observation,
                    plan,
                    source="goal_plan",
                    context={"cycle": cycle, "mode": "goal"},
                )
                scheduling_state = self._state_with_causal_context(observation, goal)

                verified, verification = self._goal_is_verified(
                    goal,
                    observation,
                    {"cycle": cycle, "mode": "goal", "phase": "pre_plan"},
                )
                if deadline_exceeded("pre_plan_verification"):
                    termination_reason = "max_duration"
                    break
                if verified:
                    logger.info("Goal verified complete before planning")
                    success = True
                    success_at = time.monotonic()
                    completed_tasks = self._complete_verified_m2_task_paths(
                        goal,
                        verification,
                        {"cycle": cycle, "mode": "goal", "phase": "pre_plan"},
                    )
                    next_task = self.task_system.get_next_task(scheduling_state) if not completed_tasks else None
                    if next_task:
                        self.task_system.complete_task(next_task.id, {"goal": goal, "verification": verification.to_dict()})
                    break

                if plan.get("status") == "complete":
                    accepted, verification = self._accept_plan_completion(
                        goal,
                        observation,
                        plan,
                        {"cycle": cycle, "mode": "goal", "phase": "planner_complete"},
                    )
                    if deadline_exceeded("planner_completion_verification"):
                        termination_reason = "max_duration"
                        break
                    if accepted:
                        logger.info("Goal completed!")
                        success = True
                        success_at = time.monotonic()
                        completed_tasks = self._complete_verified_m2_task_paths(
                            goal,
                            verification,
                            {"cycle": cycle, "mode": "goal", "phase": "planner_complete"},
                        )
                        next_task = self.task_system.get_next_task(scheduling_state) if not completed_tasks else None
                        if next_task:
                            result = {"goal": goal, "reasoning": plan.get("reasoning", "")}
                            if verification:
                                result["verification"] = verification.to_dict()
                            self.task_system.complete_task(next_task.id, result)
                        break
                    logger.info("Planner reported complete, but goal verifier needs more evidence")
                    if self._evaluate_episode_abort(goal, cycle, mode="goal", round_limit=max_cycles):
                        termination_reason = "episode_early_abort"
                        break
                    continue

                if plan.get("status") == "blocked":
                    reasoning = plan.get("reasoning", "")
                    logger.info(f"Goal blocked: {reasoning}")
                    payload = {
                        "goal": goal,
                        "cycle": cycle,
                        "reasoning": reasoning,
                        "action_count": len(plan.get("actions", []) or []),
                    }
                    if hasattr(self.session_logger, "log"):
                        self.session_logger.log("blocked_plan", payload)
                    self._write_memory_episode("blocked_plan", payload, source="run_goal")
                    termination_reason = "blocked_plan"
                    break

                actions = plan.get("actions", [])
                if not isinstance(actions, list):
                    actions = []
                if not actions:
                    reasoning = plan.get("reasoning", "")
                    logger.info(f"Goal produced no executable actions: {reasoning}")
                    payload = {
                        "goal": goal,
                        "cycle": cycle,
                        "status": plan.get("status", ""),
                        "reasoning": reasoning,
                    }
                    if hasattr(self.session_logger, "log"):
                        self.session_logger.log("empty_plan", payload)
                    self._write_memory_episode("empty_plan", payload, source="run_goal")
                    termination_reason = "empty_plan"
                    break

                for action in actions:
                    if not self.running:
                        break
                    if max_actions is not None and action_count >= max_actions:
                        termination_reason = "max_actions"
                        self.session_logger.log("goal_action_budget_exhausted", {
                            "goal": goal,
                            "cycle": cycle,
                            "max_actions": max_actions,
                            "action_count": action_count,
                            "action_suppressed": True,
                        }, level="ERROR")
                        break
                    if deadline_exceeded("pre_action"):
                        termination_reason = "max_duration"
                        break
                    interrupted, observation = self._handle_runtime_interrupt(observation, goal, {"cycle": cycle, "mode": "goal"})
                    last_observation = observation
                    if interrupted:
                        break
                    before_action_observation = observation
                    action, action_selection = self._select_action_for_execution(
                        action,
                        observation,
                        goal,
                        {"cycle": cycle, "mode": "goal"},
                    )
                    action_count += 1
                    action_verification, rejected_result = self._verify_action_for_execution(
                        action,
                        observation,
                        goal,
                        {"cycle": cycle, "mode": "goal"},
                    )
                    if deadline_exceeded("action_verification"):
                        termination_reason = "max_duration"
                        break
                    if rejected_result:
                        result = rejected_result
                    else:
                        result = self.action_controller.execute(action, observation)
                        if action_verification:
                            result["action_verification"] = action_verification
                    if action_selection:
                        result["action_candidate_selection"] = action_selection
                    if deadline_exceeded("post_action", action_suppressed=False):
                        result = dict(result)
                        result["accepted_within_goal_deadline"] = False
                        result["deadline_policy_id"] = str(
                            deadline_policy.get("id") or "goal-max-duration-v1"
                        )
                        try:
                            observation = self._observe()
                            self.session_logger.log_observation(observation)
                        except Exception as exc:
                            logger.warning(f"Could not observe post-deadline action state: {exc}")
                            observation = before_action_observation
                        last_observation = observation
                        self._log_action_event(
                            action,
                            result,
                            pre_observation=before_action_observation,
                            post_observation=observation,
                            context={"cycle": cycle, "goal": goal, "mode": "goal"},
                        )
                        self._write_memory_episode(
                            "action",
                            {"action": action, "result": result},
                            source="goal_action",
                        )
                        termination_reason = "max_duration"
                        break
                    self._record_action_value(action, result, goal, action_verification)
                    observation = self._apply_action_feedback(action, result, observation, {"cycle": cycle, "goal": goal})
                    last_observation = observation
                    self._log_action_event(
                        action,
                        result,
                        pre_observation=before_action_observation,
                        post_observation=observation,
                        context={"cycle": cycle, "goal": goal, "mode": "goal"},
                    )
                    self._write_memory_episode("action", {"action": action, "result": result}, source="goal_action")

                    if result.get("requires_replan"):
                        self._record_skill_usage(action, False, result)
                        self._request_m2_replan(result.get("replan_reason") or result.get("error"))
                        logger.info("Navigation target not reached; deferring the remaining plan suffix")
                        break
                    if result.get("success"):
                        self._record_skill_usage(action, True, result)
                        verified, verification = self._goal_is_verified(
                            goal,
                            observation,
                            {"cycle": cycle, "mode": "goal", "phase": "post_action"},
                            recent_actions=[{
                                "action": action,
                                "result": result,
                                "before_observation": before_action_observation,
                                "after_observation": observation,
                            }],
                        )
                        if deadline_exceeded("post_action_verification"):
                            termination_reason = "max_duration"
                            break
                        if verified:
                            self._complete_verified_m2_task_paths(
                                goal,
                                verification,
                                {"cycle": cycle, "mode": "goal", "phase": "post_action"},
                            )
                            success = True
                            success_at = time.monotonic()
                            break
                    else:
                        self._record_skill_usage(action, False, result)
                        corrected, observation = self._attempt_failure_correction(
                            action,
                            result,
                            observation,
                            goal,
                            {"cycle": cycle, "mode": "goal"},
                        )
                        last_observation = observation
                        if corrected:
                            continue
                        self._request_m2_replan(result.get("error") or "action_failed")
                        reflection = self._reflect(observation, action, result, goal)
                        self.session_logger.log_reflection(reflection)
                        self._write_memory_episode(
                            "failure",
                            {"action": action, "error": result.get("error"), "reflection": reflection},
                            source="goal_failure",
                        )
                        break

                if termination_reason in {"max_duration", "max_actions"}:
                    break
                if success:
                    break

                if observation.get("health", 20) < self.config.health_critical_threshold:
                    logger.warning("Health critical - aborting goal")
                    self.session_logger.log_error("Health critical", {"health": observation["health"]})
                    termination_reason = "health_critical"
                    break
                if self._evaluate_episode_abort(goal, cycle, mode="goal", round_limit=max_cycles):
                    termination_reason = "episode_early_abort"
                    break
                time.sleep(0.5)
            except Exception as e:
                logger.error(f"Error in cycle {cycle}: {e}")
                self.session_logger.log_error(str(e), {"cycle": cycle})

        ended_monotonic = time.monotonic()
        completion_monotonic = success_at if success_at is not None else ended_monotonic
        elapsed_s = completion_monotonic - started_at
        if deadline_monotonic is not None and completion_monotonic >= deadline_monotonic:
            if success:
                success = False
                success_at = None
            termination_reason = "max_duration"
            deadline_exceeded("goal_finalize")
        self._record_task_continuity(
            goal,
            last_observation,
            last_plan,
            source="goal_end",
            context={"cycles": cycle, "mode": "goal", "success": success},
            operation="compress" if success else "maintain",
            validation_status="verified" if success else "failed",
            validation_evidence={
                "goal_success": success,
                "cycles": cycle,
                "terminal_observation_present": bool(last_observation),
                "verification_source": "goal_verifier" if success else "terminal_failure",
            },
            branch_status="completed" if success else "failed",
        )
        if not success and not termination_reason:
            if max_duration_s is not None and elapsed_s >= max_duration_s:
                termination_reason = "max_duration"
            else:
                termination_reason = "max_cycles" if cycle >= max_cycles else "stopped"
        result = {
            "goal": goal,
            "cycles": cycle,
            "completed": success,
            "termination_reason": "goal_verified" if success else termination_reason,
            "max_cycles": max_cycles,
            "max_duration_s": max_duration_s,
            "max_actions": max_actions,
            "action_count": action_count,
            "elapsed_s": round(elapsed_s, 3),
            "episode_started_monotonic": started_at,
            "episode_ended_monotonic": ended_monotonic,
            "episode_deadline_monotonic": deadline_monotonic,
            "deadline_policy_id": str(
                deadline_policy_id
                or deadline_policy.get("id")
                or ("goal-max-duration-v1" if deadline_monotonic is not None else "")
            ),
            "deadline_eligible": bool(
                deadline_monotonic is None or completion_monotonic < deadline_monotonic
            ),
            "summary": self.session_logger.get_summary(),
        }
        self.session_logger.log_goal_end(goal, result)
        self._write_memory_episode("goal_end", {"goal": goal, "success": success, "cycles": cycle}, source="run_goal")
        self._finalize_skill_learning_episode(goal, success, last_observation, result)
        result["summary"] = self.session_logger.get_summary()
        if strict_deadline_binding:
            self._episode_deadline_monotonic = previous_episode_deadline
            if hasattr(action_controller, "set_episode_deadline"):
                action_controller.set_episode_deadline(
                    previous_action_deadline,
                    previous_action_timeout,
                )
            if hasattr(planner, "set_deadline"):
                planner.set_deadline(previous_episode_deadline, 0.0)
        return result

    # ── Autonomous mode (M4 + M5) ──────────────────────────────────────

    def run_autonomous(
        self,
        max_goals: int = 10,
        max_cycles_per_goal: int = 80,
        max_duration_s: Optional[float] = None,
        episode_deadline_monotonic: Optional[float] = None,
        task_id: str = "",
    ) -> dict:
        """Run autonomously: generate survival goals, pursue them, explore when idle.

        This is the M4 (autonomous survival) + M5 (exploration) integration loop.
        """
        self.running = True
        goals_completed = 0
        goals_failed = 0
        goals_interrupted = 0
        total_cycles = 0
        strict_m4 = str(getattr(self.config, "planner_protocol", "") or "") == "m4-fixed-v1"
        m4_task_id = ""
        m4_task_contract = {}
        deadline_policy = {}
        max_total_cycles = None
        if strict_m4:
            from singularity.evaluation.m4_protocol import PROTOCOL as M4_PROTOCOL

            m4_task_id = str(task_id or "BM-011").upper().strip()
            if m4_task_id not in {"BM-011", "BM-012"} or not task_spec(m4_task_id):
                raise ValueError(f"unsupported strict-M4 task: {m4_task_id or '<missing>'}")
            m4_task_contract = task_contract(m4_task_id)
            deadline_policy = dict(M4_PROTOCOL["deadline_policy"])
            protocol_timeout_s = float(
                m4_task_contract.get("max_duration_s", task_spec(m4_task_id)["max_duration_s"])
            )
            requested_duration_s = (
                float(max_duration_s)
                if max_duration_s is not None
                else protocol_timeout_s
            )
            max_duration_s = min(protocol_timeout_s, max(0.0, requested_duration_s))
            max_goals = min(int(max_goals), int(M4_PROTOCOL["limits"]["max_autonomous_goals"]))
            max_cycles_per_goal = min(
                int(max_cycles_per_goal),
                int(M4_PROTOCOL["limits"]["max_cycles_per_goal"]),
            )
            max_total_cycles = int(M4_PROTOCOL["limits"]["max_total_cycles"])
            self._m4_episode_block_delta = {"placed": {}, "removed": {}}
            self._m4_post_place_machine_observation = {}
            self._m4_ready_task_goal_binding = {}
            self._m4_readiness_recovery_bindings = {}
            self._m4_readiness_recovery_propagated_roots = set()
            self._m4_active_readiness_recovery_root_id = ""
            self._m4_shelter_verification_fingerprint = ""
            self._m4_hostile_safe_state_fingerprint = ""
            self._m4_player_lifecycle_fingerprint = ""
            self._m4_player_lifecycle_identity = ()
            self._m4_shelter_relocation = {}
            self._active_runtime_interrupt = {}
            self._runtime_interrupt_sequence = 0
            self._last_runtime_interrupt_yield = ""
            self._m4_typed_schema_recovery_state = {}
            self._m4_task_id = m4_task_id
        elif max_duration_s is not None:
            max_duration_s = max(0.0, float(max_duration_s))

        started_monotonic = time.monotonic()
        if episode_deadline_monotonic is not None:
            episode_deadline_monotonic = float(episode_deadline_monotonic)
            if max_duration_s is not None:
                episode_deadline_monotonic = min(
                    episode_deadline_monotonic,
                    started_monotonic + float(max_duration_s),
                )
        elif max_duration_s is not None:
            episode_deadline_monotonic = started_monotonic + float(max_duration_s)
        self._episode_deadline_monotonic = episode_deadline_monotonic
        deadline_event_logged = False
        episode_termination_reason = ""

        def deadline_exceeded(phase: str) -> bool:
            nonlocal deadline_event_logged, episode_termination_reason
            if self._episode_deadline_monotonic is None:
                return False
            now = time.monotonic()
            if now < self._episode_deadline_monotonic:
                return False
            episode_termination_reason = "episode_deadline"
            if not deadline_event_logged:
                elapsed = now - started_monotonic
                self.session_logger.log("episode_deadline_exceeded", {
                    "policy_id": str(deadline_policy.get("id") or "autonomous-episode-deadline-v1"),
                    "phase": phase,
                    "episode_deadline_monotonic": self._episode_deadline_monotonic,
                    "elapsed_s": round(elapsed, 3),
                    "max_duration_s": max_duration_s,
                    "new_goal_suppressed": True,
                    "new_action_suppressed": True,
                    "skill_suppressed": True,
                }, level="ERROR")
                deadline_event_logged = True
            return True

        planner = getattr(self, "planner", None)
        if hasattr(planner, "set_deadline"):
            planner.set_deadline(self._episode_deadline_monotonic, 0.0)
        action_controller = getattr(self, "action_controller", None)
        if hasattr(action_controller, "set_episode_deadline"):
            action_controller.set_episode_deadline(
                self._episode_deadline_monotonic,
                deadline_policy.get("action_timeout_s") if deadline_policy else None,
            )

        logger.info("Starting autonomous survival mode")
        autonomous_start = {
            "max_goals": max_goals,
            "max_cycles_per_goal": max_cycles_per_goal,
            "max_total_cycles": max_total_cycles,
            "max_duration_s": max_duration_s,
            "episode_started_monotonic": started_monotonic,
            "episode_deadline_monotonic": self._episode_deadline_monotonic,
            "deadline_policy_id": str(deadline_policy.get("id") or ""),
        }
        if strict_m4:
            autonomous_start.update({
                "task_id": m4_task_id,
                "task_contract_id": str(m4_task_contract.get("id") or ""),
                "task_contract_sha256": task_contract_sha256(m4_task_id),
            })
        self.session_logger.log("autonomous_start", autonomous_start)
        self._write_memory_episode("autonomous_start", autonomous_start, source="autonomous")

        # Set base on first observation
        observation = self._observe()
        self.session_logger.log_observation(observation)
        if deadline_exceeded("initial_observation"):
            self.running = False
        pos = observation.get("position", {})
        self.explorer.set_base(pos.get("x", 0), pos.get("y", 64), pos.get("z", 0))

        while self.running and (goals_completed + goals_failed + goals_interrupted) < max_goals:
            if deadline_exceeded("pre_goal"):
                break
            if max_total_cycles is not None and total_cycles >= max_total_cycles:
                episode_termination_reason = "max_total_cycles"
                break
            # Generate next goal from world state
            if strict_m4 and m4_task_id == "BM-012":
                generated_goal = self.goal_generator.next_goal(observation, task_id=m4_task_id)
            else:
                generated_goal = self.goal_generator.next_goal(observation)
            self._set_autonomous_goal_decision(
                generated_goal,
                getattr(self.goal_generator, "last_decision", {}),
            )
            goal = self._select_autonomous_goal(observation, generated_goal)
            self._last_plan_cache_signature = START_PLAN_SIGNATURE
            goal_index = goals_completed + goals_failed + goals_interrupted + 1
            if strict_m4:
                self._m4_typed_schema_recovery_state = {
                    "goal": str(goal or ""),
                    "goal_index": int(goal_index),
                    "attempt_count": 0,
                    "pending_resume": False,
                }
            goal_decision = dict(getattr(self, "_last_autonomous_goal_decision", {}) or {})
            if goal_decision.get("goal") != goal:
                self._set_autonomous_goal_decision(goal, {}, source="curriculum")
                goal_decision = dict(self._last_autonomous_goal_decision)
            goal_payload = {
                "goal": goal,
                "goal_index": goal_index,
                "max_goals": max_goals,
                "selection_source": goal_decision["selection_source"],
                "selection_reason": goal_decision["selection_reason"],
                "priority": goal_decision["priority"],
                "priority_class": goal_decision["priority_class"],
            }
            readiness_recovery_binding = self._m4_readiness_recovery_binding_for_goal(goal)
            if readiness_recovery_binding:
                goal_payload["m4_readiness_recovery_root_id"] = str(
                    readiness_recovery_binding.get("root_id") or ""
                )
                goal_payload["m4_readiness_recovery_child_id"] = str(
                    readiness_recovery_binding.get("child_id") or ""
                )
            if goal_decision.get("selection_score") is not None:
                goal_payload["selection_score"] = goal_decision["selection_score"]
            self._skill_episode_start_index = len(getattr(self.session_logger, "events", []))
            self._active_skill_execution = {}
            self._skill_fallback_goals.discard(self._goal_fingerprint(goal))
            logger.info(f"[Autonomous] Goal {goal_index}/{max_goals}: {goal}")
            self.session_logger.log("auto_goal", goal_payload)
            self.session_logger.log_goal_start(goal)
            self._write_memory_episode("auto_goal", goal_payload, source="autonomous_goal")
            if hasattr(planner, "start_episode"):
                planner.start_episode(
                    goal,
                    str(getattr(self.session_logger, "session_id", "") or ""),
                )
            if hasattr(planner, "set_deadline"):
                planner.set_deadline(self._episode_deadline_monotonic, 0.0)

            # Check if we should return to base (M5)
            should_ret, reason = self.explorer.should_return(
                observation.get("position", {}),
                observation.get("inventory_count", 0)
            )
            if should_ret:
                if deadline_exceeded("pre_return_to_base_action"):
                    break
                logger.info(f"[Explorer] Returning to base: {reason}")
                return_dir = self.explorer.get_return_direction(observation.get("position", {}))
                return_action = {
                    "type": "move_to",
                    "parameters": {"x": return_dir["x"], "z": return_dir["z"]},
                }
                return_action, action_selection = self._select_action_for_execution(
                    return_action,
                    observation,
                    goal,
                    {"mode": "autonomous", "phase": "return_to_base"},
                )
                action_verification, rejected_result = self._verify_action_for_execution(
                    return_action,
                    observation,
                    goal,
                    {"mode": "autonomous", "phase": "return_to_base"},
                )
                before_return = observation
                if rejected_result:
                    return_result = rejected_result
                else:
                    return_result = self.action_controller.execute(return_action, observation)
                    if action_verification:
                        return_result["action_verification"] = action_verification
                if action_selection:
                    return_result["action_candidate_selection"] = action_selection
                if deadline_exceeded("post_return_to_base_action"):
                    return_result["accepted_within_episode_deadline"] = False
                    episode_termination_reason = "episode_deadline"
                self._record_action_value(return_action, return_result, goal, action_verification)
                observation = self._apply_action_feedback(
                    return_action,
                    return_result,
                    observation,
                    {"goal": goal, "mode": "autonomous", "phase": "return_to_base"},
                )
                self._log_action_event(
                    return_action,
                    return_result,
                    pre_observation=before_return,
                    post_observation=observation,
                    context={"goal": goal, "mode": "autonomous", "phase": "return_to_base"},
                )
                self._write_memory_episode(
                    "return_to_base",
                    {"reason": reason, "action": return_action, "result": return_result},
                    source="autonomous_return",
                )

            # Pursue the goal
            cycle = 0
            goal_success = False
            last_plan = {}
            termination_reason = ""
            while self.running and cycle < max_cycles_per_goal:
                if deadline_exceeded("cycle_start"):
                    termination_reason = "episode_deadline"
                    break
                if max_total_cycles is not None and total_cycles >= max_total_cycles:
                    termination_reason = "max_total_cycles"
                    episode_termination_reason = "max_total_cycles"
                    break
                cycle += 1
                total_cycles += 1
                try:
                    observation = self._observe()
                    self.session_logger.log_observation(observation)
                    if deadline_exceeded("post_observation"):
                        termination_reason = "episode_deadline"
                        break
                    if not self._verify_m4_typed_schema_recovery_resume(goal, total_cycles):
                        termination_reason = "m4_planner_output_recovery_frontier_changed"
                        break
                    self.explorer.record_position(observation.get("position", {}))
                    self._write_memory_context(
                        {"auto_cycle": total_cycles, "goal": goal[:80]},
                        source="autonomous_observation",
                    )

                    self._reconcile_m4_satisfied_tasks(observation, goal, total_cycles)

                    if self._m4_readiness_recovery_goal_machine_completed(goal):
                        goal_success = True
                        termination_reason = "machine_verified_readiness_recovery"
                        break

                    plan = self._think(observation, override_goal=goal)
                    last_plan = plan
                    self.session_logger.log_plan(plan)
                    if deadline_exceeded("post_planner"):
                        termination_reason = "episode_deadline"
                        break
                    self._accept_planned_tasks()
                    self._record_task_continuity(
                        goal,
                        observation,
                        plan,
                        source="autonomous_plan",
                        context={"cycle": total_cycles, "mode": "autonomous"},
                    )
                    scheduling_state = self._state_with_causal_context(observation, goal)
                    next_task = self.task_system.get_next_task(scheduling_state)
                    active_task = next_task if next_task and next_task.title == goal else None
                    if next_task and next_task.title != goal:
                        logger.info(f"[Autonomous] Opportunistic task queued: {next_task.title}")
                        opportunity_payload = {"from_goal": goal, "task": next_task.title}
                        self.session_logger.log("opportunity_task", opportunity_payload)
                        self._write_memory_episode(
                            "opportunity_task",
                            opportunity_payload,
                            source="autonomous_scheduler",
                        )

                    verified, verification = self._goal_is_verified(
                        goal,
                        observation,
                        {"cycle": total_cycles, "mode": "autonomous", "phase": "pre_plan"},
                    )
                    verified, ready_task_verification = (
                        self._gate_m4_ready_task_goal_verification(
                            goal,
                            verified,
                            verification,
                            {"cycle": total_cycles, "mode": "autonomous", "phase": "pre_plan"},
                        )
                    )
                    if deadline_exceeded("post_goal_verifier"):
                        termination_reason = "episode_deadline"
                        break
                    if verified:
                        goal_success = True
                        if active_task and not ready_task_verification:
                            self.task_system.complete_task(active_task.id, {"goal": goal, "cycle": total_cycles, "verification": verification.to_dict()})
                        break

                    if self._recover_m4_invalid_plan(goal, plan, total_cycles):
                        continue

                    if plan.get("status") == "complete":
                        accepted, verification = self._accept_plan_completion(
                            goal,
                            observation,
                            plan,
                            {"cycle": total_cycles, "mode": "autonomous", "phase": "planner_complete"},
                        )
                        accepted, ready_task_verification = (
                            self._gate_m4_ready_task_goal_verification(
                                goal,
                                accepted,
                                verification,
                                {
                                    "cycle": total_cycles,
                                    "mode": "autonomous",
                                    "phase": "planner_complete",
                                },
                            )
                        )
                        if deadline_exceeded("post_completion_verifier"):
                            termination_reason = "episode_deadline"
                            break
                        if accepted:
                            goal_success = True
                            if active_task and not ready_task_verification:
                                result = {"goal": goal, "cycle": total_cycles}
                                if verification:
                                    result["verification"] = verification.to_dict()
                                self.task_system.complete_task(active_task.id, result)
                            break
                        logger.info("[Autonomous] Planner reported complete, but verifier needs more evidence")
                        if self._evaluate_episode_abort(
                            goal,
                            cycle,
                            mode="autonomous",
                            round_limit=max_cycles_per_goal,
                        ):
                            termination_reason = "episode_early_abort"
                            break
                        continue

                    if plan.get("status") == "blocked":
                        logger.info(f"[Autonomous] Goal blocked: {plan.get('reasoning', '')}")
                        termination_reason = "blocked_plan"
                        break

                    actions = plan.get("actions", [])
                    if not isinstance(actions, list):
                        actions = []
                    if not actions:
                        logger.info(f"[Autonomous] Goal produced no executable actions: {plan.get('reasoning', '')}")
                        payload = {
                            "goal": goal,
                            "cycle": total_cycles,
                            "status": plan.get("status", ""),
                            "reasoning": plan.get("reasoning", ""),
                        }
                        if hasattr(self.session_logger, "log"):
                            self.session_logger.log("empty_plan", payload)
                        self._write_memory_episode("empty_plan", payload, source="autonomous")
                        termination_reason = "empty_plan"
                        break

                    for action in actions:
                        if not self.running:
                            break
                        if deadline_exceeded("pre_action"):
                            termination_reason = "episode_deadline"
                            break
                        interrupted, observation = self._handle_runtime_interrupt(
                            observation,
                            goal,
                            {"cycle": total_cycles, "mode": "autonomous"},
                        )
                        if interrupted:
                            interrupt_reason = str(getattr(self, "_last_runtime_interrupt_yield", "") or "")
                            if interrupt_reason in RuntimeSupervisor.SURVIVAL_INTERRUPT_REASONS:
                                termination_reason = f"runtime_interrupt:{interrupt_reason}"
                            break
                        before_action_observation = observation
                        action, action_selection = self._select_action_for_execution(
                            action,
                            observation,
                            goal,
                            {"cycle": total_cycles, "mode": "autonomous"},
                        )
                        action_verification, rejected_result = self._verify_action_for_execution(
                            action,
                            observation,
                            goal,
                            {"cycle": total_cycles, "mode": "autonomous"},
                        )
                        if rejected_result:
                            result = rejected_result
                        else:
                            result = self.action_controller.execute(action, observation)
                            if action_verification:
                                result["action_verification"] = action_verification
                        if action_selection:
                            result["action_candidate_selection"] = action_selection
                        if deadline_exceeded("post_action"):
                            result["accepted_within_episode_deadline"] = False
                            termination_reason = "episode_deadline"
                        self._record_action_value(action, result, goal, action_verification)
                        observation = self._apply_action_feedback(
                            action,
                            result,
                            observation,
                            {"cycle": total_cycles, "goal": goal, "mode": "autonomous"},
                        )
                        self._log_action_event(
                            action,
                            result,
                            pre_observation=before_action_observation,
                            post_observation=observation,
                            context={"cycle": total_cycles, "goal": goal, "mode": "autonomous"},
                        )
                        self._write_memory_episode(
                            "action",
                            {"action": action, "result": result},
                            source="autonomous_action",
                        )

                        if termination_reason == "episode_deadline":
                            break

                        if result.get("success"):
                            self._record_skill_usage(action, True, result)
                            if self._m4_readiness_recovery_goal_machine_completed(goal):
                                goal_success = True
                                termination_reason = "machine_verified_readiness_recovery"
                                break
                            verified, verification = self._goal_is_verified(
                                goal,
                                observation,
                                {"cycle": total_cycles, "mode": "autonomous", "phase": "post_action"},
                                recent_actions=[{
                                    "action": action,
                                    "result": result,
                                    "before_observation": before_action_observation,
                                    "after_observation": observation,
                                }],
                            )
                            verified, _ = self._gate_m4_ready_task_goal_verification(
                                goal,
                                verified,
                                verification,
                                {
                                    "cycle": total_cycles,
                                    "mode": "autonomous",
                                    "phase": "post_action",
                                },
                            )
                            if deadline_exceeded("post_action_goal_verifier"):
                                termination_reason = "episode_deadline"
                                break
                            if verified:
                                goal_success = True
                                break
                            if result.get("requires_replan"):
                                logger.info(
                                    "[Autonomous] Navigation target not reached; "
                                    "deferring the remaining plan suffix"
                                )
                                break
                        else:
                            self._record_skill_usage(action, False, result)
                            corrected, observation = self._attempt_failure_correction(
                                action,
                                result,
                                observation,
                                goal,
                                {"cycle": total_cycles, "mode": "autonomous"},
                            )
                            if corrected:
                                continue
                            if self.reflector or strict_m4:
                                reflection = self._reflect(observation, action, result, goal)
                                if reflection.get("suppressed"):
                                    suppression = {
                                        "goal": goal,
                                        "context": {"cycle": total_cycles, "mode": "autonomous"},
                                        "action": action,
                                        "error": str(result.get("error") or "")[:500],
                                        **reflection,
                                    }
                                    self.session_logger.log(
                                        "failure_reflection_suppressed",
                                        suppression,
                                    )
                                    self._write_memory_episode(
                                        "failure_reflection_suppressed",
                                        suppression,
                                        source="autonomous_failure",
                                    )
                                else:
                                    self._write_memory_episode(
                                        "failure_reflection",
                                        reflection,
                                        source="autonomous_failure",
                                    )
                            break

                    if goal_success:
                        break
                    if (
                        termination_reason in {"episode_deadline", "max_total_cycles"}
                        or termination_reason.startswith("runtime_interrupt:")
                    ):
                        break

                    if observation.get("health", 20) < self.config.health_critical_threshold:
                        logger.warning("[Autonomous] Health critical - emergency survival")
                        termination_reason = "health_critical"
                        break
                    if self._evaluate_episode_abort(
                        goal,
                        cycle,
                        mode="autonomous",
                        round_limit=max_cycles_per_goal,
                    ):
                        termination_reason = "episode_early_abort"
                        break

                    sleep_s = 0.5
                    if self._episode_deadline_monotonic is not None:
                        sleep_s = min(
                            sleep_s,
                            max(0.0, self._episode_deadline_monotonic - time.monotonic()),
                        )
                    if sleep_s <= 0 or deadline_exceeded("pre_cycle_wait"):
                        termination_reason = "episode_deadline"
                        break
                    time.sleep(sleep_s)
                except Exception as e:
                    logger.error(f"Error in autonomous cycle {total_cycles}: {e}")
                    self.session_logger.log_error(str(e), {"cycle": total_cycles})
                    if deadline_exceeded("cycle_exception"):
                        termination_reason = "episode_deadline"
                        break

            if goal_success:
                goals_completed += 1
                logger.info(f"[Autonomous] Goal completed: {goal}")
                readiness_binding = self._m4_readiness_recovery_binding_for_goal(goal)
                readiness_machine_verified = bool(
                    termination_reason == "machine_verified_readiness_recovery"
                    and readiness_binding.get("root_status") == "completed"
                )
                terminal_verification = self._m4_terminal_task_verification(
                    m4_task_id,
                    goal,
                    observation,
                )
                if terminal_verification:
                    terminal_event = (
                        "terminal_resource_verification"
                        if m4_task_id == "BM-012"
                        else "terminal_survival_verification"
                    )
                    self.session_logger.log(terminal_event, terminal_verification)
                    episode_termination_reason = (
                        "terminal_task_verified"
                        if m4_task_id == "BM-012"
                        else "terminal_survival_verified"
                    )
                outcome = {
                    "goal": goal,
                    "cycles": cycle,
                    "completed": True,
                    "success": True,
                    "termination_reason": (
                        "machine_verified_readiness_recovery"
                        if readiness_machine_verified
                        else "goal_verified"
                    ),
                }
                if readiness_machine_verified:
                    outcome["m4_readiness_recovery"] = {
                        "policy_id": M4_READINESS_RECOVERY_COMPLETION_POLICY_ID,
                        "root_id": readiness_binding.get("root_id"),
                        "child_id": readiness_binding.get("child_id"),
                        "requirement_fingerprint": readiness_binding.get("requirement_fingerprint"),
                        "completion_source": readiness_binding.get("completion_source"),
                    }
                self._record_frontier_budget_outcome(goal, outcome)
                self._record_task_continuity(
                    goal,
                    observation,
                    last_plan,
                    source="auto_goal_complete",
                    context={"cycles": cycle, "mode": "autonomous", "success": True},
                    operation="compress",
                    validation_status="verified",
                    validation_evidence={
                        "goal_success": True,
                        "cycles": cycle,
                        "verification_source": (
                            M4_READINESS_RECOVERY_COMPLETION_POLICY_ID
                            if readiness_machine_verified
                            else "goal_verifier"
                        ),
                        "root_id": readiness_binding.get("root_id", ""),
                        "child_id": readiness_binding.get("child_id", ""),
                        "requirement_fingerprint": readiness_binding.get(
                            "requirement_fingerprint",
                            "",
                        ),
                    },
                    branch_status="completed",
                )
                self.session_logger.log("auto_goal_complete", outcome)
                self.session_logger.log_goal_end(goal, outcome)
                self._write_memory_episode("auto_goal_complete", outcome, source="autonomous")
                self._finalize_skill_learning_episode(goal, True, observation, outcome)
                self.curriculum.record_goal_outcome(goal, True, cycle)
            elif termination_reason.startswith("runtime_interrupt:"):
                goals_interrupted += 1
                interrupt_reason = termination_reason.split(":", 1)[1]
                logger.info(f"[Autonomous] Goal suspended by {interrupt_reason}: {goal}")
                outcome = {
                    "goal": goal,
                    "cycles": cycle,
                    "completed": False,
                    "success": False,
                    "status": "suspended",
                    "termination_reason": termination_reason,
                    "resume_policy": "regenerate_survival_goal_then_resume_frontier",
                }
                self._record_frontier_budget_outcome(goal, outcome)
                self._record_task_continuity(
                    goal,
                    observation,
                    last_plan,
                    source="auto_goal_interrupted",
                    context={"cycles": cycle, "mode": "autonomous", "success": False},
                    operation="maintain",
                    validation_status="unverified",
                    validation_evidence={
                        "goal_success": False,
                        "interrupt_reason": interrupt_reason,
                        "verification_source": "runtime_interrupt",
                    },
                    branch_status="active",
                )
                self.session_logger.log("auto_goal_interrupted", outcome, level="WARNING")
                self.session_logger.log_goal_end(goal, outcome)
                self._write_memory_episode("auto_goal_interrupted", outcome, source="autonomous")
            else:
                goals_failed += 1
                logger.info(f"[Autonomous] Goal failed/blocked: {goal}")
                if not termination_reason:
                    termination_reason = "max_cycles" if cycle >= max_cycles_per_goal else "stopped"
                outcome = {
                    "goal": goal,
                    "cycles": cycle,
                    "completed": False,
                    "success": False,
                    "termination_reason": termination_reason,
                }
                self._record_frontier_budget_outcome(goal, outcome)
                self._record_task_continuity(
                    goal,
                    observation,
                    last_plan,
                    source="auto_goal_failed",
                    context={"cycles": cycle, "mode": "autonomous", "success": False},
                    operation="maintain",
                    validation_status="failed",
                    validation_evidence={
                        "goal_success": False,
                        "cycles": cycle,
                        "verification_source": "terminal_failure",
                    },
                    branch_status="failed",
                )
                self.session_logger.log("auto_goal_failed", outcome)
                self.session_logger.log_goal_end(goal, outcome)
                self._write_memory_episode("auto_goal_failed", outcome, source="autonomous")
                self._finalize_skill_learning_episode(goal, False, observation, outcome)
                self.curriculum.record_goal_outcome(goal, False, cycle)

            if episode_termination_reason:
                break

        ended_monotonic = time.monotonic()
        elapsed_s = ended_monotonic - started_monotonic
        if (
            self._episode_deadline_monotonic is not None
            and ended_monotonic >= self._episode_deadline_monotonic
        ):
            deadline_exceeded("autonomous_finalize")
        result = {
            "mode": "autonomous",
            "goals_completed": goals_completed,
            "goals_failed": goals_failed,
            "goals_interrupted": goals_interrupted,
            "total_cycles": total_cycles,
            "termination_reason": episode_termination_reason or "max_goals_or_stopped",
            "elapsed_s": round(elapsed_s, 3),
            "max_duration_s": max_duration_s,
            "episode_started_monotonic": started_monotonic,
            "episode_ended_monotonic": ended_monotonic,
            "episode_deadline_monotonic": self._episode_deadline_monotonic,
            "deadline_eligible": bool(
                self._episode_deadline_monotonic is None
                or ended_monotonic < self._episode_deadline_monotonic
            ),
            "active_runtime_interrupt": dict(getattr(self, "_active_runtime_interrupt", {}) or {}),
            "landmarks_discovered": len(self.explorer.landmarks),
            "curriculum": self.curriculum.summary(),
            "summary": self.session_logger.get_summary(),
        }
        self.session_logger.log("autonomous_end", result)
        self._write_memory_episode("autonomous_end", result, source="autonomous")
        logger.info(
            f"Autonomous mode ended: {goals_completed} completed, {goals_failed} failed, "
            f"{goals_interrupted} interrupted, {total_cycles} total cycles"
        )
        if hasattr(planner, "set_deadline"):
            planner.set_deadline(None, 0.0)
        if hasattr(action_controller, "set_episode_deadline"):
            action_controller.set_episode_deadline(None, None)
        self._episode_deadline_monotonic = None
        return result

    def _m4_terminal_task_verification(self, task_id: str, goal: str, observation: dict) -> dict:
        if task_id == "BM-011":
            return self._m4_terminal_survival_verification(goal, observation)
        if task_id == "BM-012":
            return self._m4_terminal_resource_verification(goal, observation)
        return {}

    def _m4_terminal_resource_verification(self, goal: str, observation: dict) -> dict:
        if str(getattr(getattr(self, "config", None), "planner_protocol", "") or "") != "m4-fixed-v1":
            return {}
        if str(getattr(self, "_m4_task_id", "") or "") != "BM-012":
            return {}
        if "iron" not in str(goal or "").lower():
            return {}
        contract = task_contract("BM-012")
        verifier = contract.get("terminal_verifier", {}) if isinstance(contract, dict) else {}
        state = observation if isinstance(observation, dict) else {}
        inventory = state.get("inventory", {}) if isinstance(state.get("inventory"), dict) else {}
        criteria = contract.get("success_criteria", {}).get("inventory_any", {})
        qualifying_item = ""
        observed_count = 0
        required_count = 0
        for item, required in criteria.items():
            try:
                count = int(inventory.get(item, 0) or 0)
            except (TypeError, ValueError):
                count = 0
            if count >= int(required):
                qualifying_item = str(item)
                observed_count = count
                required_count = int(required)
                break
        if not qualifying_item:
            return {}
        health = state.get("health", 0)
        health_valid = bool(
            isinstance(health, (int, float))
            and not isinstance(health, bool)
            and math.isfinite(float(health))
            and float(health) > float(verifier.get("terminal_health_min_exclusive", 0))
        )
        bot_connected = bool(getattr(getattr(self, "bot", None), "_connected", False))
        lifecycle = state.get("player_lifecycle", {})
        get_lifecycle = getattr(getattr(self, "bot", None), "get_player_lifecycle", None)
        if callable(get_lifecycle):
            try:
                current_lifecycle = get_lifecycle()
                if isinstance(current_lifecycle, dict):
                    lifecycle = current_lifecycle
            except Exception:
                lifecycle = {}
        lifecycle = lifecycle if isinstance(lifecycle, dict) else {}
        lifecycle_report = validate_m4_player_lifecycle(
            lifecycle,
            episode_id=str(lifecycle.get("episode_id") or ""),
            require_uninterrupted=True,
        )
        expected_lifecycle_identity = tuple(
            getattr(self, "_m4_player_lifecycle_identity", ()) or ()
        )
        lifecycle_identity = self._m4_lifecycle_identity(lifecycle)
        if not (
            health_valid
            and bot_connected
            and lifecycle_report["passed"]
            and expected_lifecycle_identity
            and lifecycle_identity == expected_lifecycle_identity
        ):
            return {}
        return {
            "type": str(verifier.get("payload_type") or ""),
            "schema_version": 1,
            "passed": True,
            "source": str(verifier.get("source") or ""),
            "task_id": "BM-012",
            "goal": str(goal),
            "verifier_id": str(verifier.get("id") or ""),
            "task_contract_id": str(contract.get("id") or ""),
            "task_contract_sha256": task_contract_sha256("BM-012"),
            "qualifying_item": qualifying_item,
            "required_count": required_count,
            "observed_count": observed_count,
            "inventory": dict(inventory),
            "health": health,
            "food": state.get("hunger"),
            "bot_connected": True,
            "uninterrupted_survival": True,
            "player_lifecycle_verifier_id": lifecycle.get("verifier_id", ""),
            "player_lifecycle": dict(lifecycle),
        }

    def _m4_terminal_survival_verification(self, goal: str, observation: dict) -> dict:
        if str(getattr(getattr(self, "config", None), "planner_protocol", "") or "") != "m4-fixed-v1":
            return {}
        if "until dawn" not in str(goal or "").lower():
            return {}
        state = observation if isinstance(observation, dict) else {}
        try:
            raw_time = float(state["time_of_day"])
            time_valid = math.isfinite(raw_time)
            time_of_day = int(raw_time) % 24000 if time_valid else 0
        except (KeyError, TypeError, ValueError, OverflowError):
            time_of_day = 0
            time_valid = False
        health = state.get("health", 0)
        health_valid = bool(
            isinstance(health, (int, float))
            and not isinstance(health, bool)
            and math.isfinite(float(health))
            and health > 0
        )
        bot_connected = bool(getattr(getattr(self, "bot", None), "_connected", False))
        shelter = state.get("shelter_verification", {})
        shelter = shelter if isinstance(shelter, dict) else {}
        lifecycle = state.get("player_lifecycle", {})
        get_lifecycle = getattr(getattr(self, "bot", None), "get_player_lifecycle", None)
        if callable(get_lifecycle):
            try:
                current_lifecycle = get_lifecycle()
                if isinstance(current_lifecycle, dict):
                    lifecycle = current_lifecycle
            except Exception:
                lifecycle = {}
        lifecycle = lifecycle if isinstance(lifecycle, dict) else {}
        lifecycle_report = validate_m4_player_lifecycle(
            lifecycle,
            episode_id=str(lifecycle.get("episode_id") or ""),
            require_uninterrupted=True,
        )
        lifecycle_identity = self._m4_lifecycle_identity(lifecycle)
        expected_lifecycle_identity = tuple(
            getattr(self, "_m4_player_lifecycle_identity", ()) or ()
        )

        passed = bool(
            time_valid
            and (time_of_day >= 23000 or time_of_day < 1000)
            and health_valid
            and bot_connected
            and is_machine_verified_shelter(shelter)
            and lifecycle_report["passed"]
            and expected_lifecycle_identity
            and lifecycle_identity == expected_lifecycle_identity
        )
        if not passed:
            return {}
        return {
            "type": "m4_terminal_survival_verification",
            "schema_version": 1,
            "passed": True,
            "source": "machine_state",
            "goal": str(goal),
            "time_of_day": time_of_day,
            "health": health,
            "food": state.get("hunger"),
            "bot_connected": True,
            "uninterrupted_survival": True,
            "player_lifecycle_verifier_id": lifecycle.get("verifier_id", ""),
            "player_lifecycle": dict(lifecycle),
            "shelter_verifier_id": shelter.get("verifier_id", ""),
            "shelter_contract_sha256": shelter.get("contract_sha256", ""),
        }

    # ── Thinking / Planning ────────────────────────────────────────────

    def _episode_deadline_reached(self, now_monotonic: float = None) -> bool:
        deadline = getattr(self, "_episode_deadline_monotonic", None)
        if deadline is None:
            return False
        now = time.monotonic() if now_monotonic is None else float(now_monotonic)
        return now >= float(deadline)

    def _think(self, observation: dict, override_goal: str = None) -> dict:
        goal = override_goal or self.current_goal or "explore"
        if self._episode_deadline_reached():
            return {
                "status": "blocked",
                "reasoning": "Episode deadline exhausted before planning or skill execution",
                "actions": [],
                "deadline_suppressed": True,
            }
        self._active_skill_advisory_hint = ""
        root_required = bool(getattr(self.config, "require_llm_root_plan", False))
        learned_plan = None
        if not root_required or (
            getattr(self, "_m2_root_plan_valid", False)
            and not getattr(self, "_m2_skill_contribution_complete", False)
        ):
            skill_goal = goal
            skill_ready = True
            if root_required:
                next_task = self.task_system.get_next_task(observation)
                if next_task:
                    skill_goal = next_task.title
                target_skill_id = str(getattr(self.config, "target_skill_id", "") or "")
                target_skill = self.skill_library.get_skill_by_id(target_skill_id) if target_skill_id else None
                if target_skill is not None:
                    from singularity.core.skill_runtime import evaluate_skill_preconditions

                    precondition_issues = evaluate_skill_preconditions(target_skill, observation)
                    skill_ready = not precondition_issues
                    if precondition_issues:
                        self.session_logger.log("skill_deferred", {
                            "goal": skill_goal,
                            "skill_id": target_skill_id,
                            "reason": "preconditions_not_met",
                            "issues": precondition_issues,
                            "runtime_influence": False,
                        })
            if skill_ready:
                learned_plan = self._learned_skill_plan(skill_goal, observation)
        if learned_plan is not None:
            return self._apply_visual_action_grounding(learned_plan, observation, goal)
        if self._use_llm:
            plan = self._think_llm(observation, goal)
            plan = self._blocked_plan_rule_fallback(plan, goal, observation)
        elif root_required:
            payload = {
                "goal": goal,
                "planner_protocol": str(getattr(self.config, "planner_protocol", "")),
                "reason": "real_llm_not_configured",
            }
            self.session_logger.log("llm_root_planner_blocked", payload, level="ERROR")
            plan = {
                "status": "error",
                "actions": [],
                "subtasks": [],
                "reasoning": "M2 requires a configured real LLM root planner",
            }
        else:
            plan = self._think_rule(observation, goal)
        return self._apply_visual_action_grounding(plan, observation, goal)

    def _think_llm(self, observation: dict, goal: str) -> dict:
        planning_memory, planning_contract = self._collect_bounded_planning_memory(
            goal,
            observation,
            planner="llm",
            readers=[
                (
                    "relevant_memory",
                    "mixed",
                    lambda limit: self._call_bounded_memory_reader(
                        self._read_relevant_memory,
                        goal,
                        observation,
                        source="planner_goal",
                        max_chars=limit,
                    ),
                ),
                (
                    "task_memory",
                    "task",
                    lambda limit: self._call_bounded_memory_reader(
                        self._task_memory_context,
                        goal,
                        observation,
                        max_chars=limit,
                    ),
                ),
                (
                    "task_continuity",
                    "task",
                    lambda limit: self._call_bounded_memory_reader(
                        self._task_continuity_context,
                        goal,
                        observation,
                        max_chars=limit,
                    ),
                ),
                (
                    "context_window",
                    "context",
                    lambda limit: self._call_bounded_memory_reader(
                        self._read_context_window,
                        source="planner_context",
                        max_chars=limit,
                    ),
                ),
            ],
        )
        task_readiness_report = self._task_readiness_report(observation)
        task_readiness_context = self._task_readiness_context(
            goal,
            observation,
            report=task_readiness_report,
        )

        # Get skill recommendations
        skill_frontier = task_readiness_report.get("tasks", [])
        recommended = self.skill_library.get_recommended_skills(
            goal,
            observation,
            task_frontier=skill_frontier,
            use_frontier_router=getattr(self.config, "enable_skill_frontier_routing", True),
        )
        route_trace = {}
        trace_reader = getattr(self.skill_library, "get_last_skill_router_trace", None)
        if callable(trace_reader):
            route_trace = trace_reader()
        policy_hints = []
        if self.config.enable_policy_skills:
            policy_hints = self.skill_library.get_policy_skill_hints(goal, observation)
        skill_hint = ""
        route_formatter = getattr(self.skill_library, "format_frontier_skill_route", None)
        if callable(route_formatter):
            skill_hint = route_formatter(route_trace)
        if recommended and not skill_hint:
            skill_hint = "\nRecommended skills (by success rate): " + ", ".join(
                f"{s.name} ({s.success_rate:.0%})" for s in recommended[:5]
            )
        if route_trace.get("profile") == "frontier_transition_skill_router_v1":
            self._log_skill_frontier_route(route_trace)
        if policy_hints:
            skill_hint += "\nReviewed causal/correction skills:\n- " + "\n- ".join(policy_hints)
            self._log_policy_intervention("hint", {
                "goal": goal,
                "hints": policy_hints[:5],
            })

        try:
            visual_context = self._visual_memory_context(goal)
            visual_action_context = self._visual_action_context(goal, observation)
            coach_context = self._coach_context(goal, observation)
            curriculum_context = self._curriculum_context(goal, observation)
            frontier_budget_context = self._frontier_budget_context(goal)
            self_evolution_context = self._self_evolution_context(goal, observation)
            knowledge_correction_context = self._knowledge_correction_context(goal, observation)
            task_precondition_context = self._task_precondition_context(goal, observation)
            skill_memory_context = self._skill_memory_context(goal, observation)
            previous_defer = getattr(self, "_defer_plan_cache_miss", False)
            self._defer_plan_cache_miss = True
            try:
                cached_plan = self._plan_cache_lookup(goal, observation)
            finally:
                self._defer_plan_cache_miss = previous_defer
            if cached_plan:
                return self._attach_planning_context_contract(cached_plan, planning_contract)
            hybrid_workflow_context = self._plan_cache_hybrid_context(goal, observation)
            if not hybrid_workflow_context:
                self._log_plan_cache_miss(goal)
            combined_memory = "\n".join(part for part in (
                planning_memory,
                task_readiness_context,
                visual_context,
                visual_action_context,
                coach_context,
                curriculum_context,
                frontier_budget_context,
                self_evolution_context,
                knowledge_correction_context,
                task_precondition_context,
                skill_memory_context,
                self._active_skill_advisory_hint,
                skill_hint,
                hybrid_workflow_context,
            ) if part)
            planner_observation = observation
            if str(getattr(self.config, "planner_protocol", "") or "") == "m2-fixed-v1":
                planner_observation = dict(observation)
                planner_observation["m2_successful_action_summary"] = self._m2_successful_action_summary()
            plan = self.planner.plan_from_goal(goal, planner_observation, combined_memory)
            planner_evidence = dict(getattr(self.planner, "last_call_evidence", {}) or {})
            if planner_evidence:
                self.session_logger.log("llm_planner_call", planner_evidence)
                if (
                    planner_evidence.get("plan_kind") == "root"
                    and planner_evidence.get("real_llm_call") is True
                    and planner_evidence.get("schema_valid") is True
                ):
                    self._m2_root_plan_valid = True
            self._flush_task_state_transitions({"source": "llm_planner"})
            self._record_plan_cache_signature(plan, goal, observation, source="llm_planner")
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            self.session_logger.log_error(f"LLM call failed: {e}")
            plan = {"status": "error", "actions": [], "reasoning": str(e)}
        return self._attach_planning_context_contract(plan, planning_contract)

    def _m2_successful_action_summary(self) -> dict:
        """Return a bounded typed summary of successful actions in the current goal."""
        from singularity.evaluation.m2_protocol import PROTOCOL

        contract = PROTOCOL["planner_context"]["successful_action_summary"]
        max_actions = int(contract["max_actions"])
        max_chars = int(contract["max_chars"])
        events = list(getattr(getattr(self, "session_logger", None), "events", []) or [])
        start = max(0, int(getattr(self, "_skill_episode_start_index", 0) or 0))
        rows: list[dict] = []
        type_counts: dict[str, int] = {}

        for event in events[start:]:
            if not isinstance(event, dict) or event.get("type") != "action":
                continue
            data = event.get("data", {}) if isinstance(event.get("data"), dict) else {}
            result = data.get("result", {}) if isinstance(data.get("result"), dict) else {}
            action = data.get("action", {}) if isinstance(data.get("action"), dict) else {}
            if result.get("success") is not True:
                continue
            action_type = str(action.get("type") or result.get("action_type") or "")[:32]
            if not action_type:
                continue
            type_counts[action_type] = type_counts.get(action_type, 0) + 1
            params = action.get("parameters", {}) if isinstance(action.get("parameters"), dict) else {}
            row = {"type": action_type}
            for name in ("block", "item"):
                value = params.get(name) or result.get(name)
                if value:
                    row[name] = str(value)[:64]
            if all(isinstance(params.get(axis), (int, float)) and not isinstance(params.get(axis), bool) for axis in ("x", "y", "z")):
                position = {axis: float(params[axis]) for axis in ("x", "y", "z")}
                if all(math.isfinite(value) for value in position.values()):
                    row["position"] = position

            pre = data.get("pre_observation", {}) if isinstance(data.get("pre_observation"), dict) else {}
            post = data.get("post_observation", {}) if isinstance(data.get("post_observation"), dict) else {}
            before = pre.get("inventory", {}) if isinstance(pre.get("inventory"), dict) else {}
            after = post.get("inventory", {}) if isinstance(post.get("inventory"), dict) else {}
            delta = {}
            for item in sorted(set(before) | set(after)):
                try:
                    change = int(after.get(item, 0) or 0) - int(before.get(item, 0) or 0)
                except (TypeError, ValueError):
                    continue
                if change:
                    delta[str(item)[:64]] = change
                if len(delta) >= 8:
                    break
            if delta:
                row["inventory_delta"] = delta
            rows.append(row)

        included = rows[-max_actions:]
        summary = {
            "profile": str(contract["profile"]),
            "successful_action_count": len(rows),
            "successful_action_types": dict(sorted(type_counts.items())),
            "included_action_count": len(included),
            "truncated": len(rows) > len(included),
            "actions": included,
        }
        while included and len(json.dumps(summary, sort_keys=True, separators=(",", ":"))) > max_chars:
            included = included[1:]
            summary["actions"] = included
            summary["included_action_count"] = len(included)
            summary["truncated"] = True
        return summary

    def _plan_cache_lookup(self, goal: str, observation: dict, log_miss: bool = True) -> dict | None:
        """Try an approved plan-transition cache before spending an LLM call."""
        if not getattr(self.config, "enable_plan_cache", False):
            return None
        cache = getattr(self, "plan_cache", None)
        if not cache or not getattr(cache, "entries", []):
            return None
        previous = getattr(self, "_last_plan_cache_signature", START_PLAN_SIGNATURE) or START_PLAN_SIGNATURE
        hit = cache.query(goal, observation, previous)
        payload = {
            "goal": goal,
            "previous_plan_signature": previous,
            "entry_count": len(cache.entries),
        }
        if not hit:
            if (
                log_miss
                and not getattr(self, "_defer_plan_cache_miss", False)
                and hasattr(self, "session_logger")
                and hasattr(self.session_logger, "log")
            ):
                self.session_logger.log("plan_cache_miss", payload)
            return None
        payload.update({
            "entry_id": hit.get("entry_id"),
            "confidence": hit.get("confidence"),
            "score": hit.get("score"),
            "state_similarity": hit.get("state_similarity"),
            "support_count": hit.get("support_count"),
            "success_rate": hit.get("success_rate"),
            "source_report": hit.get("source_report"),
            "execution_stage": hit.get("execution_stage"),
            "plan_signature": hit.get("plan_signature"),
            "workflow_signature": hit.get("workflow_signature"),
        })
        if hasattr(self, "session_logger") and hasattr(self.session_logger, "log"):
            self.session_logger.log("plan_cache_hit", payload)
        plan = hit.get("plan", {})
        planner = getattr(self, "planner", None)
        if hasattr(planner, "_create_tasks_from_plan"):
            try:
                planner._create_tasks_from_plan(plan)
            except Exception as e:
                logger.warning(f"Plan cache task creation failed: {e}")
        self._record_plan_cache_signature(plan, goal, observation, source="plan_transition_cache")
        return plan

    def _log_plan_cache_miss(self, goal: str):
        if not getattr(self.config, "enable_plan_cache", False):
            return
        cache = getattr(self, "plan_cache", None)
        if not cache or not getattr(cache, "entries", []):
            return
        previous = getattr(self, "_last_plan_cache_signature", START_PLAN_SIGNATURE) or START_PLAN_SIGNATURE
        if hasattr(self, "session_logger") and hasattr(self.session_logger, "log"):
            self.session_logger.log("plan_cache_miss", {
                "goal": goal,
                "previous_plan_signature": previous,
                "entry_count": len(cache.entries),
            })

    def _plan_cache_hybrid_context(self, goal: str, observation: dict) -> str:
        """Expose a hybrid workflow as bounded planner guidance, never as a direct plan."""
        if not getattr(self.config, "enable_plan_cache", False):
            return ""
        cache = getattr(self, "plan_cache", None)
        if not cache or not getattr(cache, "entries", []):
            return ""
        previous = getattr(self, "_last_plan_cache_signature", START_PLAN_SIGNATURE) or START_PLAN_SIGNATURE
        hit = cache.query_hybrid(goal, observation, previous)
        if not hit:
            return ""
        context = cache.format_hybrid_guidance(
            hit,
            char_budget=min(600, max(1, int(getattr(self.config, "planning_memory_read_limit_chars", 600) or 600))),
        )
        if not context:
            return ""
        if hasattr(self, "session_logger") and hasattr(self.session_logger, "log"):
            self.session_logger.log("plan_cache_hybrid_hint", {
                "goal": goal,
                "entry_id": hit.get("entry_id"),
                "confidence": hit.get("confidence"),
                "score": hit.get("score"),
                "state_similarity": hit.get("state_similarity"),
                "support_count": hit.get("support_count"),
                "success_rate": hit.get("success_rate"),
                "source_report": hit.get("source_report"),
                "execution_stage": "hybrid",
                "plan_signature": hit.get("plan_signature"),
                "workflow_signature": hit.get("workflow_signature"),
                "context_chars": len(context),
            })
        return context

    def _record_plan_cache_signature(self, plan: dict, goal: str, observation: dict, source: str = "planner"):
        """Remember the last plan signature so future cache lookups model transitions."""
        if not isinstance(plan, dict):
            return
        signature = plan_signature(plan)
        self._last_plan_cache_signature = signature
        if getattr(self.config, "enable_plan_cache", False) and hasattr(self, "session_logger") and hasattr(self.session_logger, "log"):
            self.session_logger.log("plan_cache_signature", {
                "goal": goal,
                "source": source,
                "plan_signature": signature,
                "action_count": len(plan.get("actions", []) or []),
                "status": plan.get("status", ""),
            })

    def _coach_context(self, goal: str, current_state: dict = None) -> str:
        """Retrieve advisory runtime coaching instructions for planner context."""
        coach_policy = self._active_coach_policy()
        if not coach_policy:
            return ""
        context = coach_policy.planner_context(goal, current_state or {})
        if not context:
            return ""
        payload = {
            "goal": goal,
            "policy": "coach",
            "coach": coach_policy.summary(),
        }
        if hasattr(self, "session_logger") and hasattr(self.session_logger, "log"):
            self.session_logger.log("coach_policy_hint", payload)
        self._log_policy_intervention("hint", payload)
        return context

    def _curriculum_context(self, goal: str, current_state: dict = None, limit: int = 3) -> str:
        """Expose the latest autonomous curriculum decision as selective planner context."""
        if not getattr(getattr(self, "config", None), "enable_curriculum_planner_context", True):
            return ""
        curriculum = getattr(self, "curriculum", None)
        decision = getattr(curriculum, "last_decision", {}) if curriculum is not None else {}
        if not isinstance(decision, dict) or not decision.get("selected"):
            return ""
        selected = str(decision.get("selected") or "")
        if goal and selected and selected.lower() != str(goal).lower():
            return ""
        candidates = [
            candidate for candidate in decision.get("candidates", []) or []
            if isinstance(candidate, dict)
        ][: max(1, min(5, limit or 3))]
        if not candidates:
            return ""
        lines = [
            "Autonomous curriculum decision (advisory selective foresight; verify before acting):",
            f"- selected: {selected[:120]}",
        ]
        fallback = str(decision.get("fallback") or "")
        if fallback and fallback != selected:
            lines.append(f"- fallback goal: {fallback[:120]}")
        coach = decision.get("coach", {}) if isinstance(decision.get("coach", {}), dict) else {}
        styles = coach.get("styles", []) if isinstance(coach.get("styles", []), list) else []
        if styles:
            lines.append(f"- coach styles: {', '.join(str(style) for style in styles[:3])}")
        for candidate in candidates:
            title = str(candidate.get("title") or "")[:100]
            category = str(candidate.get("category") or "goal")
            score = candidate.get("score", 0)
            reasons = ", ".join(str(reason) for reason in candidate.get("reasons", [])[:6])
            targets = ", ".join(str(item) for item in candidate.get("target_items", [])[:4])
            required = candidate.get("required_items", {}) if isinstance(candidate.get("required_items", {}), dict) else {}
            bit = f"- candidate[{category} score={score}]: {title}"
            if targets:
                bit += f" targets={targets}"
            if required:
                bit += f" requires={json.dumps(required, default=str)[:120]}"
            if reasons:
                bit += f" reasons={reasons}"
            lines.append(bit)
        context = "\n".join(lines)
        if hasattr(self, "session_logger") and hasattr(self.session_logger, "log"):
            self.session_logger.log("curriculum_planner_context", {
                "goal": goal,
                "selected": selected,
                "candidate_count": len(candidates),
                "has_coach": bool(styles),
            })
        return context

    def _record_frontier_budget_decision(
        self,
        observation: dict,
        selected_goal: str,
        decision: dict = None,
        readiness_report: dict = None,
    ) -> dict:
        """Build and trace one fixed-budget frontier slate without executing branches."""
        controller = getattr(self, "frontier_budget_controller", None)
        if controller is None or not getattr(controller, "enabled", False):
            return {}
        decision = decision if isinstance(decision, dict) else {}
        readiness_report = readiness_report if isinstance(readiness_report, dict) else {}
        curriculum = getattr(self, "curriculum", None)
        stats = {}
        for title, item in getattr(curriculum, "goal_stats", {}).items() if curriculum is not None else []:
            try:
                stats[str(title)] = asdict(item)
            except TypeError:
                stats[str(title)] = {}
        branches = build_frontier_branches(
            curriculum_candidates=[
                item for item in decision.get("candidates", []) or []
                if isinstance(item, dict)
            ],
            task_readiness=readiness_report,
            observation=observation or {},
            goal_stats=stats,
            selected_goal=selected_goal,
        )
        if not branches:
            return {}
        credit = getattr(self, "_frontier_budget_recovery_credit", {})
        credit = credit if isinstance(credit, dict) else {}
        recovered_rounds = max(0, int(credit.get("remaining_rounds", 0) or 0))
        allocation = controller.allocate(branches, recovered_rounds=recovered_rounds)
        if not allocation:
            return {}
        if getattr(controller, "advisory", False):
            allocation["interval_calibrated"] = True
            for item in allocation.get("branches", []) or []:
                if isinstance(item, dict):
                    item["interval_calibrated"] = True
        selected = next((item for item in allocation.get("branches", []) if item.get("selected")), None)
        if selected is None:
            selected = next((item for item in allocation.get("branches", []) if item.get("allocated_rounds", 0) > 0), None)
        allocation["selected_branch_id"] = str((selected or {}).get("branch_id") or "")
        allocation["selected_goal_fingerprint"] = self._goal_fingerprint(selected_goal)
        if recovered_rounds > 0:
            allocation["reallocation_source"] = "certified_episode_early_abort"
            allocation["source_abort_event_fingerprint"] = str(credit.get("event_fingerprint") or "")
            allocation["episode_abort_gate_integrity_sha256"] = str(credit.get("gate_integrity_sha256") or "")
        else:
            allocation["reallocation_source"] = "fixed_base_budget"
        allocation["provenance"] = dict(getattr(self, "frontier_budget_runtime_provenance", {}) or {})
        self._frontier_budget_active = {
            "allocation": allocation,
            "goal_fingerprint": allocation["selected_goal_fingerprint"],
            "event_start": len(getattr(getattr(self, "session_logger", None), "events", []) or []),
        }
        if curriculum is not None and isinstance(getattr(curriculum, "last_decision", {}), dict):
            if self._goal_fingerprint(str(curriculum.last_decision.get("selected") or "")) == allocation["selected_goal_fingerprint"]:
                curriculum.last_decision["frontier_budget"] = frontier_budget_trace_payload(
                    allocation,
                    provenance=allocation["provenance"],
                )
        logger_instance = getattr(self, "session_logger", None)
        if logger_instance is not None and hasattr(logger_instance, "log"):
            logger_instance.log(
                "frontier_budget_allocation",
                frontier_budget_trace_payload(allocation, provenance=allocation["provenance"]),
            )
        return allocation

    def _frontier_budget_context(self, goal: str, limit: int = 3) -> str:
        """Expose a held-out-gated allocation as advisory planner context only."""
        controller = getattr(self, "frontier_budget_controller", None)
        if controller is None or not getattr(controller, "advisory", False):
            return ""
        active = getattr(self, "_frontier_budget_active", {})
        active = active if isinstance(active, dict) else {}
        allocation = active.get("allocation", {}) if isinstance(active.get("allocation", {}), dict) else {}
        if not allocation or active.get("goal_fingerprint") != self._goal_fingerprint(goal):
            return ""
        branches = [
            item for item in allocation.get("branches", []) or []
            if isinstance(item, dict) and item.get("allocated_rounds", 0) > 0
        ][: max(1, min(5, int(limit or 3)))]
        if not branches:
            return ""
        ledger = allocation.get("ledger", {}) if isinstance(allocation.get("ledger", {}), dict) else {}
        lines = [
            "Frontier planner-round budget (advisory; action and goal verifiers remain authoritative):",
            (
                f"- fixed total={ledger.get('total_rounds', 0)} "
                f"pool={ledger.get('allocation_pool_rounds', 0)} "
                f"policy={allocation.get('allocation_profile', '')}"
            ),
        ]
        for item in branches:
            title = str(item.get("title") or item.get("branch_id") or "frontier")[:100]
            low = item.get("estimated_rounds_low")
            high = item.get("estimated_rounds_high")
            selected = " selected" if item.get("selected") else ""
            lines.append(
                f"- branch{selected}: {title} allocation={item.get('allocated_rounds', 0)} "
                f"estimated_remaining=[{low},{high}]"
            )
        if allocation.get("budget_alert"):
            lines.append(f"- budget alert: {allocation.get('budget_alert')}")
        lines.append("- this allocation cannot retry, execute alternatives, or extend the fixed budget automatically")
        logger_instance = getattr(self, "session_logger", None)
        if logger_instance is not None and hasattr(logger_instance, "log"):
            logger_instance.log("frontier_budget_planner_context", {
                "goal_fingerprint": active.get("goal_fingerprint", ""),
                "allocation_profile": allocation.get("allocation_profile", ""),
                "selected_branch_id": allocation.get("selected_branch_id", ""),
                "branch_count": len(branches),
                "allocation_pool_rounds": ledger.get("allocation_pool_rounds", 0),
                "gate_readiness": getattr(self, "frontier_budget_runtime_gate_report", {}).get("gate_readiness", "unknown"),
            })
        return "\n".join(lines)

    def _record_frontier_budget_outcome(self, goal: str, outcome: dict) -> dict:
        """Attach verifier-grounded execution outcomes to the active allocation trace."""
        active = getattr(self, "_frontier_budget_active", {})
        active = active if isinstance(active, dict) else {}
        allocation = active.get("allocation", {}) if isinstance(active.get("allocation", {}), dict) else {}
        if not allocation or active.get("goal_fingerprint") != self._goal_fingerprint(goal):
            return {}
        events = getattr(getattr(self, "session_logger", None), "events", []) or []
        start = max(0, int(active.get("event_start", 0) or 0))
        scoped = events[start:]
        verifier_events = [event for event in scoped if event.get("type") == "action_verification"]
        verifier_rejects = 0
        for event in verifier_events:
            data = event.get("data", {}) if isinstance(event.get("data", {}), dict) else {}
            verification = data.get("verification", {}) if isinstance(data.get("verification", {}), dict) else {}
            if str(verification.get("status") or "").lower() == "reject":
                verifier_rejects += 1
        action_events = [event for event in scoped if event.get("type") == "action"]
        action_failures = 0
        for event in action_events:
            data = event.get("data", {}) if isinstance(event.get("data", {}), dict) else {}
            result = data.get("result", {}) if isinstance(data.get("result", {}), dict) else {}
            if result.get("success") is not True:
                action_failures += 1
        success = bool(outcome.get("success", outcome.get("completed", False)))
        cycles = max(0, int(outcome.get("cycles", 0) or 0))
        selected_branch_id = str(allocation.get("selected_branch_id") or "")
        selected = next(
            (item for item in allocation.get("branches", []) or [] if item.get("branch_id") == selected_branch_id),
            {},
        )
        allocated_to_selected = max(0, int(selected.get("allocated_rounds", 0) or 0))
        consumed_recovered = 0
        credit = getattr(self, "_frontier_budget_recovery_credit", {})
        if allocation.get("reallocation_source") == "certified_episode_early_abort" and isinstance(credit, dict):
            available_credit = max(0, int(credit.get("remaining_rounds", 0) or 0))
            consumed_recovered = min(available_credit, allocated_to_selected, cycles)
            credit["remaining_rounds"] = available_credit - consumed_recovered
            self._frontier_budget_recovery_credit = credit if credit["remaining_rounds"] > 0 else {}
        verification_enforced = bool(
            getattr(getattr(self, "config", None), "enable_action_verification", True)
            and getattr(getattr(self, "config", None), "enforce_action_verification", True)
        )
        payload = {
            "goal_fingerprint": active.get("goal_fingerprint", ""),
            "selected_branch_id": selected_branch_id,
            "policy": allocation.get("policy", ""),
            "allocation_profile": allocation.get("allocation_profile", ""),
            "goal_completed": success,
            "planner_rounds_used": cycles,
            "verifier_event_count": len(verifier_events),
            "verifier_reject_count": verifier_rejects,
            "action_event_count": len(action_events),
            "action_failure_count": action_failures,
            "unsafe_action_count": 0 if verification_enforced else 1,
            "action_verification_enforced": verification_enforced,
            "resolved_branch_ids": [selected_branch_id] if success and selected_branch_id else [],
            "actual_rounds_by_branch": {selected_branch_id: cycles} if success and selected_branch_id else {},
            "termination_reason": str(outcome.get("termination_reason") or "")[:64],
            "reallocated_rounds_consumed": consumed_recovered,
            "reallocated_rounds_remaining": max(0, int(getattr(self, "_frontier_budget_recovery_credit", {}).get("remaining_rounds", 0) or 0)),
            "automatic_retry_allowed": False,
            "automatic_branch_execution_allowed": False,
        }
        logger_instance = getattr(self, "session_logger", None)
        if logger_instance is not None and hasattr(logger_instance, "log"):
            logger_instance.log("frontier_budget_outcome", payload)
        self._frontier_budget_active = {}
        return payload

    def _learned_skill_plan(self, goal: str, observation: dict) -> dict | None:
        """Return a gated learned-skill plan, or only log its shadow proposal."""
        mode = str(getattr(self.config, "skill_execution_mode", "off") or "off").strip().lower()
        if mode not in {"shadow", "advisory", "evaluation", "runtime"}:
            return None
        goal_key = self._goal_fingerprint(goal)
        if goal_key in self._skill_fallback_goals:
            return None
        target_skill_id = str(getattr(self.config, "target_skill_id", "") or "").strip()
        active_id = str(self._active_skill_execution.get("skill_id") or "")
        skill = self.skill_library.get_skill_by_id(active_id) if active_id else None
        if skill is None:
            skill = self.skill_library.select_runtime_skill(
                goal,
                observation,
                execution_mode=mode,
                target_skill_id=target_skill_id,
                experiment_id=str(getattr(self.config, "skill_experiment_id", "") or ""),
                evaluation_authorization=getattr(self.config, "skill_evaluation_authorization", {}) or {},
            )
        if skill is None:
            if target_skill_id:
                self._skill_fallback_goals.add(goal_key)
                self.session_logger.log("skill_fallback", {
                    "goal": goal,
                    "skill_id": target_skill_id,
                    "mode": mode,
                    "reason": "target_skill_not_applicable_or_not_gated",
                    "before_execution": True,
                })
            return None

        plan = self.skill_library.build_runtime_skill_plan(skill, goal, observation)
        identity = plan.get("skill", {}) if isinstance(plan.get("skill", {}), dict) else {}
        if (
            getattr(self.config, "require_llm_root_plan", False)
            and plan.get("status") == "complete"
            and not plan.get("actions")
        ):
            self._m2_skill_contribution_complete = True
            self.session_logger.log("skill_subtask_complete", {
                "goal": goal,
                "skill": identity,
                "mode": mode,
                "root_planner_resumes": True,
                "runtime_influence": bool(self._active_skill_execution),
            })
            return None
        if plan.get("status") == "fallback":
            fallback_reason = str(plan.get("fallback_reason") or "skill_plan_fallback")
            fallback_failure_type = (
                "skill_error"
                if fallback_reason == "invalid_skill_contract"
                else "environment_change"
            )
            self._skill_fallback_goals.add(goal_key)
            self._active_skill_execution = {
                "skill_id": skill.skill_id,
                "skill_name": skill.name,
                "version": skill.version,
                "mode": mode,
                "selected_count": 1,
                "executed_count": 0,
                "failed_action_count": 0,
                "fallback_reason": fallback_reason,
                "failure_type": fallback_failure_type,
            }
            self.session_logger.log("skill_fallback", {
                "goal": goal,
                "skill": identity,
                "mode": mode,
                "reason": fallback_reason,
                "failure_type": fallback_failure_type,
                "issues": plan.get("issues", []),
                "before_execution": True,
            })
            return None

        if mode == "shadow":
            self.session_logger.log("skill_shadow_plan", {
                "goal": goal,
                "skill": identity,
                "mode": mode,
                "status": plan.get("status"),
                "phase_id": plan.get("phase_id", ""),
                "action_types": [
                    str(action.get("type") or "")
                    for action in plan.get("actions", [])
                    if isinstance(action, dict)
                ],
                "action_count": len(plan.get("actions", []) or []),
                "runtime_influence": False,
            })
            return None

        if mode == "advisory":
            action_types = [
                str(action.get("type") or "")
                for action in plan.get("actions", [])
                if isinstance(action, dict) and action.get("type")
            ]
            self._active_skill_advisory_hint = (
                "Bounded learned-skill advisory (no direct execution): "
                f"skill={skill.skill_id}@{skill.version}; "
                f"phase={plan.get('phase_id', '')}; "
                f"allowed action types={','.join(action_types) or 'none'}; "
                "reobserve and use ordinary planning for every action."
            )
            self.session_logger.log("skill_advisory_hint", {
                "goal": goal,
                "skill": identity,
                "mode": mode,
                "phase_id": plan.get("phase_id", ""),
                "action_types": action_types,
                "coordinate_parameters_injected": False,
                "direct_execution": False,
                "planner_influence": True,
            })
            return None

        first_selection = not self._active_skill_execution
        if first_selection:
            self._active_skill_execution = {
                "skill_id": skill.skill_id,
                "skill_name": skill.name,
                "version": skill.version,
                "mode": mode,
                "selected_count": 1,
                "executed_count": 0,
                "failed_action_count": 0,
                "first_failed_transition": "",
                "fallback_reason": "",
                "bound_parameters": dict(plan.get("bound_parameters", {}) or {}),
                "effective_postconditions": dict(plan.get("effective_postconditions", {}) or {}),
            }
            self.session_logger.log("skill_selected", {
                "goal": goal,
                "skill": identity,
                "mode": mode,
                "experiment_id": str(getattr(self.config, "skill_experiment_id", "") or ""),
                "runtime_influence": True,
                "evaluation_only": mode == "evaluation",
            })

        actions = []
        for index, raw_action in enumerate(plan.get("actions", []) or []):
            if not isinstance(raw_action, dict):
                continue
            action = dict(raw_action)
            action["skill_context"] = {
                "skill_id": skill.skill_id,
                "skill_name": skill.name,
                "version": skill.version,
                "status": skill.status,
                "mode": mode,
                "phase_id": plan.get("phase_id", ""),
                "template_action_index": index,
                "experiment_id": str(getattr(self.config, "skill_experiment_id", "") or ""),
                "goal": goal,
                "goal_fingerprint": goal_key,
            }
            actions.append(action)
        bounded_plan = {
            "status": plan.get("status", "in_progress"),
            "reasoning": plan.get("reasoning", "bounded learned skill plan"),
            "actions": actions,
            "skill_execution": identity,
            "skill_phase_id": plan.get("phase_id", ""),
            "bound_parameters": dict(plan.get("bound_parameters", {}) or {}),
            "effective_postconditions": dict(plan.get("effective_postconditions", {}) or {}),
        }
        self.session_logger.log("skill_plan", {
            "goal": goal,
            "skill": identity,
            "mode": mode,
            "phase_id": plan.get("phase_id", ""),
            "action_count": len(actions),
            "status": bounded_plan["status"],
            "bound_parameters": bounded_plan["bound_parameters"],
            "effective_postconditions": bounded_plan["effective_postconditions"],
        })
        return bounded_plan

    def _finalize_skill_learning_episode(
        self,
        goal: str,
        goal_success: bool,
        terminal_observation: dict,
        goal_result: dict,
    ):
        """Finalize attribution, then extract candidates after the episode is immutable."""
        try:
            self._finalize_active_skill_outcome(goal, goal_success, terminal_observation, goal_result)
        except Exception as exc:
            logger.warning(f"Skill outcome finalization failed: {type(exc).__name__}")
            self.session_logger.log("skill_learning_error", {
                "phase": "outcome_attribution",
                "error_type": type(exc).__name__,
                "task_result_affected": False,
            }, level="ERROR")

        if self.skill_extractor is None or self.skill_candidate_queue is None:
            return
        try:
            all_events = list(getattr(self.session_logger, "events", []))
            prefix_types = {"benchmark_runtime_profile", "benchmark_reset", "connect"}
            prefix = [
                event for event in all_events[: self._skill_episode_start_index]
                if event.get("type") in prefix_types
            ]
            episode_events = prefix + all_events[self._skill_episode_start_index :]
            source_path = str(getattr(self.session_logger, "_log_path", "in_memory_episode"))
            candidates = self.skill_extractor.extract_skill_candidates_from_events(
                episode_events,
                source_path=source_path,
            )
            queued_ids = []
            queued_candidates = []
            decisions = []
            for candidate in candidates:
                queued = self.skill_candidate_queue.enqueue(candidate)
                deduplicated = queued.id != candidate.id
                report = self.skill_extractor.validate_candidate_for_promotion(queued)
                queued.signals = {
                    **(queued.signals if isinstance(queued.signals, dict) else {}),
                    "promotion_report": report.to_dict(),
                }
                self.skill_candidate_queue.save()
                queued_ids.append(queued.id)
                queued_candidates.append({
                    "extracted_candidate_id": candidate.id,
                    "queued_candidate_id": queued.id,
                    "dedupe_key": queued.dedupe_key,
                    "deduplicated": deduplicated,
                })
                decisions.append(report.decision)
                if self.skill_learning_ledger is not None:
                    self.skill_learning_ledger.record_candidate(queued, report.to_dict())
            queue_items = self.skill_candidate_queue.all()
            queue_dedupe_keys = [item.dedupe_key for item in queue_items if item.dedupe_key]
            self.session_logger.log("skill_candidate_extraction", {
                "goal": goal,
                "episode_closed": True,
                "candidate_count": len(candidates),
                "queued_candidate_ids": queued_ids,
                "queued_candidates": queued_candidates,
                "new_candidate_count": sum(
                    1 for item in queued_candidates if not item["deduplicated"]
                ),
                "deduplicated_candidate_count": sum(
                    1 for item in queued_candidates if item["deduplicated"]
                ),
                "queue_candidate_count": len(queue_items),
                "queue_unique_dedupe_key_count": len(set(queue_dedupe_keys)),
                "queue_dedupe_key_unique": len(queue_dedupe_keys) == len(queue_items),
                "decisions": decisions,
                "task_result_affected": False,
                "runtime_influence": False,
            })
        except Exception as exc:
            logger.warning(f"Post-episode skill extraction failed: {type(exc).__name__}")
            self.session_logger.log("skill_learning_error", {
                "phase": "post_episode_extraction",
                "error_type": type(exc).__name__,
                "task_result_affected": False,
            }, level="ERROR")

    def _finalize_active_skill_outcome(
        self,
        goal: str,
        goal_success: bool,
        terminal_observation: dict,
        goal_result: dict,
    ):
        active = dict(self._active_skill_execution or {})
        if not active.get("skill_id"):
            return
        skill = self.skill_library.get_skill_by_id(active["skill_id"])
        if skill is None:
            return
        postconditions_met, missing = self.skill_library.skill_postconditions_met(
            skill,
            terminal_observation or {},
            effective_postconditions=active.get("effective_postconditions", {}),
        )
        goal_family = self.skill_library.infer_task_family(goal)
        route_scope_valid = self.skill_library.skill_transfer_scope_allows(skill, goal_family)
        executed = int(active.get("executed_count", 0) or 0)
        failed_actions = int(active.get("failed_action_count", 0) or 0)
        controlled_fault = bool(active.get("controlled_failure_only"))
        attributed_success = bool(
            postconditions_met
            and route_scope_valid
            and executed > 0
            and failed_actions == 0
        )
        if controlled_fault and failed_actions:
            failure_type = "controlled_fault"
            confidence = 1.0
        elif attributed_success:
            failure_type = ""
            confidence = 1.0
        elif executed and not route_scope_valid:
            failure_type = "routing_error"
            confidence = 1.0
        elif failed_actions:
            failure_type = str(active.get("failure_type") or "skill_error")
            confidence = 0.95 if failure_type == "skill_error" else 0.8
        elif active.get("fallback_reason"):
            failure_type = str(active.get("failure_type") or "environment_change")
            confidence = 0.85 if failure_type == "precondition_misclassification" else 0.75
        elif executed:
            failure_type = "postcondition_failure"
            confidence = 0.9
        else:
            failure_type = "not_executed"
            confidence = 0.0
        context = {
            "goal": goal,
            "goal_success": bool(goal_success),
            "goal_termination_reason": str(goal_result.get("termination_reason") or ""),
            "postconditions_met": postconditions_met,
            "bound_parameters": dict(active.get("bound_parameters", {}) or {}),
            "effective_postconditions": dict(active.get("effective_postconditions", {}) or {}),
            "goal_task_family": goal_family,
            "route_scope_valid": route_scope_valid,
            "missing_postconditions": missing,
            "executed_action_count": executed,
            "failed_action_count": failed_actions,
            "fallback_reason": active.get("fallback_reason", ""),
            "first_failed_transition": active.get("first_failed_transition", ""),
            "failure_type": failure_type,
            "attribution_confidence": confidence,
            "experiment_id": str(getattr(self.config, "skill_experiment_id", "") or ""),
            "controlled_failure_only": controlled_fault,
            "controlled_fault_profile": str(active.get("controlled_fault_profile") or ""),
            "counts_toward_skill_lifecycle": not controlled_fault,
        }
        outcome = self.skill_library.record_learned_skill_outcome(
            skill.skill_id,
            attributed_success,
            context=context,
            regression_ledger_path=str(getattr(self.config, "skill_regressions_path", "") or ""),
        ) if executed > 0 or active.get("fallback_reason") else {
            "recorded": False,
            "reason": "skill_was_not_executed",
            "status": skill.status,
        }
        self.session_logger.log("skill_execution_outcome", {
            "goal": goal,
            "skill_id": skill.skill_id,
            "skill_name": skill.name,
            "version": skill.version,
            "mode": active.get("mode", ""),
            "success": attributed_success,
            "goal_success": bool(goal_success),
            "postconditions_met": postconditions_met,
            "executed_action_count": executed,
            "failed_action_count": failed_actions,
            "fallback_count": 1 if active.get("fallback_reason") else 0,
            "first_failed_transition": active.get("first_failed_transition", ""),
            "failure_type": failure_type,
            "attribution_confidence": confidence,
            "controlled_failure_only": controlled_fault,
            "counts_toward_skill_lifecycle": not controlled_fault,
            "lifecycle_outcome": outcome,
        })
        if self.skill_learning_ledger is not None:
            self.skill_learning_ledger.record_skill(skill)
            self.skill_learning_ledger.record_decision(
                skill.skill_id,
                "controlled_fault_excluded" if controlled_fault else "reinforce" if attributed_success else (
                    "demote" if outcome.get("status_changed") and outcome.get("status") == "advisory"
                    else "quarantine" if outcome.get("status_changed") and outcome.get("status") == "quarantined"
                    else "retain"
                ),
                (
                    "controlled research fault retained as non-attributable evidence"
                    if controlled_fault
                    else "runtime outcome attributed to the selected learned skill"
                ),
                evidence=context,
            )

    def _skill_memory_context(self, goal: str, current_state: dict = None, limit: int = 5) -> str:
        """Retrieve skill-local replay/failure notes for the current task family."""
        if not getattr(getattr(self, "config", None), "enable_skill_memory_context", True):
            return ""
        if not hasattr(self, "skill_library") or not hasattr(self.skill_library, "get_skill_memory_hints"):
            return ""
        task_family = self.skill_library.infer_task_family(goal, {})
        try:
            hints = self.skill_library.get_skill_memory_hints(goal, task_family=task_family, limit=limit)
        except Exception as e:
            logger.warning(f"Skill memory hint lookup failed: {e}")
            return ""
        if not hints:
            return ""
        payload = {
            "goal": goal,
            "task_family": task_family,
            "hint_count": len(hints),
            "hints": hints[:limit],
        }
        if hasattr(self, "session_logger") and hasattr(self.session_logger, "log"):
            self.session_logger.log("skill_memory_hint", payload)
        return "Skill-level memory ({family}; REUSE/AVOID/REVIEW_ONLY):\n- {hints}".format(
            family=task_family,
            hints="\n- ".join(hints[:limit]),
        )

    def _knowledge_correction_context(self, goal: str, current_state: dict = None, limit: int = 6) -> str:
        """Retrieve approved dependency and failed-action corrections for the planner."""
        if not getattr(getattr(self, "config", None), "enable_knowledge_correction_context", True):
            return ""
        report = getattr(self, "knowledge_correction_feedback_report", {}) or {}
        if report.get("gate_required") and not report.get("gate_approved"):
            return ""
        feedback = getattr(self, "knowledge_correction_feedback", {}) or {}
        dependency_items = self._select_knowledge_correction_items(
            feedback.get("dependency_corrections", []),
            goal,
            current_state or {},
            limit=limit,
        )
        remaining = max(0, int(limit) - len(dependency_items))
        failure_items = self._select_knowledge_correction_items(
            feedback.get("failure_action_memories", []),
            goal,
            current_state or {},
            limit=remaining or min(2, limit),
        )
        lines = []
        for item in dependency_items:
            failed = str(item.get("failed_signature") or "unknown")
            recovery = str(item.get("recovery_signature") or "unknown")
            correction = str(item.get("correction") or "").strip()
            evidence = self._small_int(item.get("evidence_count", 0))
            confidence = self._small_float(item.get("confidence", 0.0))
            if correction:
                lines.append(
                    f"- Dependency correction: {correction} "
                    f"(failed={failed}, recovery={recovery}, evidence={evidence}, confidence={confidence:.2f})"
                )
            else:
                lines.append(
                    f"- Dependency correction: before retrying {failed}, prefer {recovery} "
                    f"when the same failure context appears (evidence={evidence}, confidence={confidence:.2f})"
                )
        for item in failure_items:
            signature = str(item.get("signature") or "unknown")
            recommendation = str(item.get("recommendation") or "avoid_or_replan_until_preconditions_change")
            reason = str(item.get("reason") or "repeated failure").strip()
            failures = self._small_int(item.get("failures", 0))
            attempts = self._small_int(item.get("attempts", 0))
            lines.append(
                f"- Failed-action memory: {signature} -> {recommendation}; "
                f"reason={reason}; failures={failures}/{attempts}"
            )
        if not lines:
            return ""

        task_family = self._knowledge_task_family(goal)
        payload = {
            "goal": goal,
            "task_family": task_family,
            "dependency_correction_count": len(dependency_items),
            "failure_action_memory_count": len(failure_items),
            "gate_readiness": report.get("gate_readiness", "not_required"),
        }
        if hasattr(self, "session_logger") and hasattr(self.session_logger, "log"):
            self.session_logger.log("knowledge_correction_hint", payload)
        self._log_policy_intervention("hint", {
            "goal": goal,
            "policy": "knowledge_correction",
            **payload,
        })
        return (
            "Knowledge correction feedback "
            "(gate-approved, advisory only; verify against current world state before acting):\n"
            + "\n".join(lines[:limit])
        )

    def _task_precondition_context(self, goal: str, current_state: dict = None, limit: int = 6) -> str:
        """Retrieve approved hidden-prerequisite hints for the planner."""
        if not getattr(getattr(self, "config", None), "enable_task_precondition_context", True):
            return ""
        report = getattr(self, "task_precondition_feedback_report", {}) or {}
        if report.get("gate_required") and not report.get("gate_approved"):
            return ""
        feedback = getattr(self, "task_precondition_feedback", {}) or {}
        candidates = self._select_task_precondition_items(
            feedback.get("candidates", []),
            goal,
            current_state or {},
            limit=limit,
        )
        if not candidates:
            return ""

        lines = []
        for item in candidates:
            action = str(item.get("action_signature") or "action")
            candidate_type = str(item.get("candidate_type") or "precondition")
            evidence = self._small_int(item.get("evidence_count", 0))
            confidence = self._small_float(item.get("confidence", 0.0))
            preconditions = item.get("inferred_preconditions", {}) if isinstance(item.get("inferred_preconditions", {}), dict) else {}
            required = self._format_task_preconditions(preconditions)
            missing = self._missing_task_preconditions(preconditions, current_state or {})
            missing_text = self._format_task_preconditions(missing) if missing else "currently satisfied or unknown"
            recommendation = str(item.get("recommendation") or "").strip()
            line = (
                f"- {candidate_type}: before {action}, require {required}; "
                f"missing now: {missing_text}; evidence={evidence}, confidence={confidence:.2f}"
            )
            if recommendation:
                line += f"; {recommendation}"
            lines.append(line)

        task_family = self._knowledge_task_family(goal)
        payload = {
            "goal": goal,
            "task_family": task_family,
            "candidate_count": len(candidates),
            "gate_readiness": report.get("gate_readiness", "not_required"),
        }
        if hasattr(self, "session_logger") and hasattr(self.session_logger, "log"):
            self.session_logger.log("task_precondition_hint", payload)
        self._log_policy_intervention("hint", {
            "goal": goal,
            "policy": "task_precondition",
            **payload,
        })
        return (
            "Task precondition feedback "
            "(gate-approved, advisory only; insert missing prerequisite subtasks before retrying):\n"
            + "\n".join(lines[:limit])
        )

    def _select_task_precondition_items(
        self,
        items: list[dict],
        goal: str,
        current_state: dict,
        limit: int = 6,
    ) -> list[dict]:
        if not isinstance(items, list) or limit <= 0:
            return []
        task_family = self._knowledge_task_family(goal)
        scored = []
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            score = self._task_precondition_score(item, goal, current_state or {}, task_family)
            if score <= 0:
                continue
            scored.append((score, self._small_int(item.get("evidence_count", 0)), self._small_float(item.get("confidence", 0.0)), -index, item))
        scored.sort(reverse=True)
        return [item for _, _, _, _, item in scored[:limit]]

    def _task_precondition_score(self, item: dict, goal: str, current_state: dict, task_family: str) -> int:
        text = self._task_precondition_item_text(item)
        tokens = self._knowledge_context_tokens(goal)
        score = sum(1 for token in tokens if token in text)
        if task_family and task_family in text:
            score += 3
        candidate_type = str(item.get("candidate_type") or "")
        if candidate_type in {"inventory_precondition", "tool_precondition"}:
            score += 1
        missing = self._missing_task_preconditions(
            item.get("inferred_preconditions", {}) if isinstance(item.get("inferred_preconditions", {}), dict) else {},
            current_state or {},
        )
        if missing:
            score += 4
            inventory = missing.get("inventory", {}) if isinstance(missing.get("inventory", {}), dict) else {}
            score += min(4, len(inventory))
            flags = missing.get("flags", []) if isinstance(missing.get("flags", []), list) else []
            score += min(2, len(flags))
        return score

    def _task_precondition_item_text(self, item: dict) -> str:
        parts = []
        for key in (
            "goal",
            "candidate_type",
            "task_family",
            "action_signature",
            "action_type",
            "target",
            "recommendation",
        ):
            value = item.get(key)
            if value:
                parts.append(str(value))
        preconditions = item.get("inferred_preconditions", {})
        if isinstance(preconditions, dict):
            parts.append(json.dumps(preconditions, sort_keys=True, default=str))
        source_blocks = item.get("source_blocks", {})
        if isinstance(source_blocks, dict):
            parts.append(json.dumps(source_blocks, sort_keys=True, default=str))
        return " ".join(parts).lower().replace("_", " ")

    def _missing_task_preconditions(self, preconditions: dict, current_state: dict) -> dict:
        if not isinstance(preconditions, dict):
            return {}
        missing = {}
        inventory = current_state.get("inventory", {}) if isinstance(current_state, dict) and isinstance(current_state.get("inventory", {}), dict) else {}
        required_inventory = preconditions.get("inventory", {}) if isinstance(preconditions.get("inventory", {}), dict) else {}
        inventory_missing = {}
        for item, count in required_inventory.items():
            needed = self._small_int(count)
            have = self._small_int(inventory.get(item, 0))
            if needed > have:
                inventory_missing[str(item)] = needed - have
        if inventory_missing:
            missing["inventory"] = inventory_missing
        required_flags = preconditions.get("flags", []) if isinstance(preconditions.get("flags", []), list) else []
        state_flags = current_state.get("flags", []) if isinstance(current_state, dict) and isinstance(current_state.get("flags", []), list) else []
        flags = {str(flag) for flag in state_flags}
        flag_missing = [str(flag) for flag in required_flags if str(flag) not in flags]
        if flag_missing:
            missing["flags"] = flag_missing
        nearby_required = preconditions.get("nearby_block_present", [])
        nearby_missing = self._missing_observed_names(nearby_required, current_state or {})
        if nearby_missing:
            missing["nearby_block_present"] = nearby_missing
        return missing

    def _format_task_preconditions(self, preconditions: dict) -> str:
        if not isinstance(preconditions, dict) or not preconditions:
            return "reviewed prerequisite task"
        parts = []
        inventory = preconditions.get("inventory", {}) if isinstance(preconditions.get("inventory", {}), dict) else {}
        if inventory:
            parts.append("inventory " + ", ".join(
                f"{item}={count}" for item, count in sorted(inventory.items())
            ))
        tool_for = preconditions.get("tool_for", {}) if isinstance(preconditions.get("tool_for", {}), dict) else {}
        if tool_for:
            parts.append("tool_for " + ", ".join(
                f"{target}->{tool}" for target, tool in sorted(tool_for.items())
            ))
        flags = preconditions.get("flags", []) if isinstance(preconditions.get("flags", []), list) else []
        if flags:
            parts.append("flags " + ", ".join(str(flag) for flag in flags))
        nearby = preconditions.get("nearby_block_present", [])
        if isinstance(nearby, str):
            nearby = [nearby]
        elif isinstance(nearby, dict):
            nearby = [value for value in nearby.values() if value]
        elif not isinstance(nearby, list):
            nearby = []
        if nearby:
            parts.append("nearby_block_present " + ", ".join(str(item) for item in nearby[:6]))
        return "; ".join(parts) if parts else "reviewed prerequisite task"

    def _missing_observed_names(self, required, current_state: dict) -> list[str]:
        required_names = self._required_observed_names(required)
        if not required_names:
            return []
        observed = self._observed_names(current_state or {})
        return sorted(name for name in required_names if name not in observed)

    def _required_observed_names(self, required) -> set[str]:
        if isinstance(required, str):
            return {required.lower()} if required else set()
        if isinstance(required, dict):
            return {
                str(value).lower()
                for value in required.values()
                if value
            }
        if isinstance(required, list):
            return {
                str(value).lower()
                for value in required
                if value
            }
        return set()

    def _observed_names(self, current_state: dict) -> set[str]:
        names = set()
        if not isinstance(current_state, dict):
            return names
        for key in ("nearby_blocks", "grounded_resources", "trees_found", "nearby_entities", "landmarks"):
            values = current_state.get(key, [])
            if not isinstance(values, list):
                continue
            for item in values:
                if isinstance(item, str):
                    names.add(item.lower())
                    continue
                if not isinstance(item, dict):
                    continue
                for field_name in ("name", "type", "block", "resource", "drop", "entity"):
                    value = item.get(field_name)
                    if value:
                        names.add(str(value).lower())
        if current_state.get("landmarks"):
            names.add("landmark")
        return names

    def _select_knowledge_correction_items(
        self,
        items: list[dict],
        goal: str,
        current_state: dict,
        limit: int = 6,
    ) -> list[dict]:
        if not isinstance(items, list) or limit <= 0:
            return []
        task_family = self._knowledge_task_family(goal)
        scored = []
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            score = self._knowledge_correction_score(item, goal, current_state or {}, task_family)
            if score <= 0:
                continue
            scored.append((score, self._small_int(item.get("evidence_count", item.get("failures", 0))), -index, item))
        scored.sort(reverse=True)
        return [item for _, _, _, item in scored[:limit]]

    def _knowledge_correction_score(self, item: dict, goal: str, current_state: dict, task_family: str) -> int:
        text = self._knowledge_correction_item_text(item)
        tokens = self._knowledge_context_tokens(goal)
        score = sum(1 for token in tokens if token in text)
        if task_family and task_family in text:
            score += 3
        inventory = current_state.get("inventory", {}) if isinstance(current_state, dict) else {}
        if isinstance(inventory, dict):
            for name, count in inventory.items():
                try:
                    amount = int(count or 0)
                except (TypeError, ValueError):
                    amount = 0
                if amount > 0 and str(name).lower() in text:
                    score += 1
        return score

    def _knowledge_correction_item_text(self, item: dict) -> str:
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
        targets = item.get("target_items", [])
        if isinstance(targets, list):
            parts.extend(str(value) for value in targets)
        return " ".join(parts).lower().replace("_", " ")

    def _knowledge_context_tokens(self, text: str) -> set[str]:
        normalized = "".join(ch.lower() if ch.isalnum() else " " for ch in str(text or ""))
        return {token for token in normalized.split() if len(token) >= 3}

    def _knowledge_task_family(self, goal: str) -> str:
        if hasattr(self, "skill_library") and hasattr(self.skill_library, "infer_task_family"):
            try:
                return self.skill_library.infer_task_family(goal, {})
            except Exception:
                return ""
        return ""

    def _think_rule(self, observation: dict, goal: str) -> dict:
        planning_memory, planning_contract = self._collect_bounded_planning_memory(
            goal,
            observation,
            planner="rule",
            readers=[
                (
                    "relevant_memory",
                    "mixed",
                    lambda limit: self._call_bounded_memory_reader(
                        self._read_relevant_memory,
                        goal,
                        observation,
                        source="rule_planner_goal",
                        max_chars=limit,
                    ),
                ),
                (
                    "task_memory",
                    "task",
                    lambda limit: self._call_bounded_memory_reader(
                        self._task_memory_context,
                        goal,
                        observation,
                        max_chars=limit,
                    ),
                ),
                (
                    "task_continuity",
                    "task",
                    lambda limit: self._call_bounded_memory_reader(
                        self._task_continuity_context,
                        goal,
                        observation,
                        max_chars=limit,
                    ),
                ),
            ],
        )
        plan = self.rule_planner.plan_from_goal(goal, observation, memory_context=planning_memory)
        plan = self._attach_planning_context_contract(plan, planning_contract)
        self._ingest_plan_subtasks(plan, goal, source="rule_planner")
        return plan

    def _blocked_plan_rule_fallback(self, plan: dict, goal: str, observation: dict) -> dict:
        """Use deterministic Minecraft rules when an LLM plan stalls before any action."""
        if not getattr(getattr(self, "config", None), "enable_blocked_plan_rule_fallback", True):
            return plan
        if not isinstance(plan, dict):
            return plan

        actions = plan.get("actions", [])
        if not isinstance(actions, list):
            actions = []
        status = str(plan.get("status") or "").lower()
        if status == "complete":
            return plan
        if status not in {"blocked", "error"} and actions:
            return plan
        if not hasattr(self, "rule_planner") or self.rule_planner is None:
            return plan

        try:
            fallback = self.rule_planner.plan_from_goal(
                goal,
                observation or {},
                memory_context=str(getattr(self, "_last_planning_memory_context", "") or ""),
            )
        except Exception as e:
            logger.warning(f"Rule fallback failed for blocked plan: {e}")
            return plan
        if not isinstance(fallback, dict):
            return plan

        fallback_actions = fallback.get("actions", [])
        if not isinstance(fallback_actions, list):
            fallback_actions = []
        fallback_status = str(fallback.get("status") or "").lower()
        if fallback_status == "complete" or fallback_actions:
            merged = dict(fallback)
            if isinstance(plan.get("planning_context_contract"), dict):
                merged["planning_context_contract"] = dict(plan["planning_context_contract"])
            if fallback_actions:
                merged["status"] = "in_progress"
            merged["reasoning"] = self._append_reasoning(
                merged.get("reasoning", ""),
                f"Rule fallback replaced stalled planner output: {plan.get('reasoning', '')}",
            )
            payload = {
                "goal": goal,
                "original_status": plan.get("status", ""),
                "original_reasoning": str(plan.get("reasoning", ""))[:240],
                "fallback_status": merged.get("status", ""),
                "fallback_reasoning": str(fallback.get("reasoning", ""))[:240],
                "fallback_action_count": len(fallback_actions),
            }
            if hasattr(self, "session_logger") and hasattr(self.session_logger, "log"):
                self.session_logger.log("planner_fallback", payload)
            self._write_memory_episode("planner_fallback", payload, source="blocked_plan_rule_fallback")
            self._ingest_plan_subtasks(merged, goal, source="blocked_plan_rule_fallback")
            return merged
        return plan

    def _verify_action_for_execution(
        self,
        action: dict,
        observation: dict,
        goal: str,
        context: dict = None,
    ) -> tuple[Optional[dict], Optional[dict]]:
        """Verify a candidate action before spending a live bot command on it."""
        if self._episode_deadline_reached():
            return self._deadline_action_rejection(action, "before_action_verifier")
        if not getattr(getattr(self, "config", None), "enable_action_verification", True):
            return None, None
        verifier = getattr(self, "action_verifier", None)
        if verifier is None:
            return None, None
        self._apply_controlled_skill_fault(action)
        protocol = str(getattr(getattr(self, "config", None), "planner_protocol", "") or "")
        try:
            if isinstance(verifier, ActionVerifier):
                decision = verifier.verify(
                    action,
                    observation or {},
                    goal=goal,
                    protocol=protocol,
                )
            else:
                decision = verifier.verify(action, observation or {}, goal=goal)
        except Exception as e:
            logger.warning(f"Action verification failed: {e}")
            return None, None

        if self._episode_deadline_reached():
            return self._deadline_action_rejection(action, "after_action_verifier")

        verification = decision.as_dict() if hasattr(decision, "as_dict") else dict(decision)
        if (
            protocol == "m4-fixed-v1"
            and verification.get("status") == "reject"
            and verification.get("action_type") == "place"
            and verification.get("policy_id") in {
                ActionVerifier.M4_PLACE_TARGET_OCCUPANCY_POLICY_ID,
                ActionVerifier.M4_PLACE_TARGET_PLAYER_OCCUPANCY_POLICY_ID,
            }
        ):
            planner = getattr(self, "planner", None)
            if hasattr(planner, "request_replan"):
                candidates = []
                if (
                    verification.get("policy_id")
                    == ActionVerifier.M4_PLACE_TARGET_PLAYER_OCCUPANCY_POLICY_ID
                ):
                    candidates = verification.get("required", {}).get(
                        "adjacent_reference_candidates",
                        [],
                    )
                    candidate_text = ",".join(
                        f"({item['x']},{item['y']},{item['z']})"
                        for item in candidates
                        if isinstance(item, dict)
                        and all(axis in item for axis in ("x", "y", "z"))
                    )
                    bounded_instruction = (
                        "perform one next-cycle replan using one adjacent reference candidate "
                        f"[{candidate_text}] whose cell above is air or replaceable and outside "
                        "the player collision cells; do not retry the rejected reference"
                        if candidate_text
                        else (
                            "re-observe a finite player position, then perform one next-cycle "
                            "replan to a different adjacent reference outside the player collision cells"
                        )
                    )
                else:
                    bounded_instruction = (
                        "choose a different reference block whose cell above is air or replaceable"
                    )
                replan_reason = (
                    f"{verification.get('reason', 'M4 place target rejected')}; "
                    f"{bounded_instruction}"
                )
                if candidates and hasattr(planner, "request_place_replan"):
                    parameters = action.get("parameters", {}) if isinstance(action, dict) else {}
                    planner.request_place_replan(
                        replan_reason,
                        rejected_reference={
                            axis: parameters.get(axis)
                            for axis in ("x", "y", "z")
                        },
                        adjacent_reference_candidates=candidates,
                    )
                else:
                    planner.request_replan(replan_reason)
                verification["replan_requested"] = True
                verification["replan_reason"] = replan_reason
                if candidates:
                    verification["replan_candidate_count"] = len(candidates)
        payload = {
            "goal": goal,
            "context": context or {},
            "action": action,
            "verification": verification,
        }
        if hasattr(self, "session_logger") and hasattr(self.session_logger, "log"):
            self.session_logger.log("action_verification", payload)
        self._write_memory_episode("action_verification", payload, source="action_verifier")

        if verification.get("status") == "reject" and getattr(getattr(self, "config", None), "enforce_action_verification", True):
            result = {
                "success": False,
                "error": f"Action verification rejected: {verification.get('reason', '')}",
                "action_type": action.get("type", verification.get("action_type", "unknown")) if isinstance(action, dict) else "unknown",
                "duration_ms": 0,
                "action_verification": verification,
                "verification_blocked": True,
            }
            if verification.get("replan_requested"):
                result["requires_replan"] = True
                result["replan_reason"] = verification.get("replan_reason", "")
            return verification, result
        return verification, None

    def _deadline_action_rejection(self, action: dict, phase: str) -> tuple[dict, dict]:
        action_type = action.get("type", "unknown") if isinstance(action, dict) else "unknown"
        verification = {
            "action_type": action_type,
            "status": "reject",
            "score": 0.0,
            "reason": "episode deadline exhausted",
            "deadline_suppressed": True,
            "phase": phase,
        }
        return verification, {
            "success": False,
            "error": "Action verification rejected: episode deadline exhausted",
            "action_type": action_type,
            "duration_ms": 0,
            "action_verification": verification,
            "verification_blocked": True,
            "deadline_suppressed": True,
            "accepted_within_episode_deadline": False,
        }

    def _apply_controlled_skill_fault(self, action: dict):
        """Inject one allowlisted verifier-visible failure in research-only runs."""
        profile = str(getattr(getattr(self, "config", None), "skill_fault_profile", "") or "").strip().lower()
        skill_context = action.get("skill_context", {}) if isinstance(action, dict) else {}
        if not profile or not isinstance(skill_context, dict) or not skill_context.get("skill_id"):
            return
        key = ":".join([
            profile,
            str(skill_context.get("experiment_id") or ""),
            str(skill_context.get("goal_fingerprint") or ""),
        ])
        if key in self._applied_skill_fault_profiles:
            return
        mutations = {
            "reject_skill_craft_missing_item_v1": ("craft", {"item": "", "count": 1}),
            "reject_skill_place_missing_item_v1": ("place", {"item": "diamond_block"}),
            "reject_skill_equip_missing_item_v1": ("equip", {"item": "diamond_pickaxe"}),
        }
        mutation = mutations.get(profile)
        if mutation is None:
            return
        original = {
            "type": str(action.get("type") or ""),
            "parameters": dict(action.get("parameters", {}) or {}),
        }
        skill_context.update({
            "controlled_fault_profile": profile,
            "controlled_failure_only": True,
            "counts_toward_skill_lifecycle": False,
        })
        action["type"], action["parameters"] = mutation[0], dict(mutation[1])
        self._applied_skill_fault_profiles.add(key)
        self.session_logger.log("skill_learning_fault_injection", {
            "profile": profile,
            "skill_id": skill_context.get("skill_id", ""),
            "experiment_id": skill_context.get("experiment_id", ""),
            "original_action": original,
            "injected_action": {
                "type": action["type"],
                "parameters": dict(action["parameters"]),
            },
            "controlled_failure_only": True,
            "counts_toward_promotion": False,
            "action_verifier_must_reject": True,
        })

    def _select_action_for_execution(
        self,
        action: dict,
        observation: dict,
        goal: str,
        context: dict = None,
    ) -> tuple[dict, Optional[dict]]:
        """Use verifier-guided repair candidates for rejected planner actions."""
        if not getattr(getattr(self, "config", None), "enable_action_candidate_selection", True):
            return action, None
        selector = getattr(self, "action_candidate_selector", None)
        if selector is None:
            return action, None
        try:
            selection = selector.select(action, observation or {}, goal=goal)
        except Exception as e:
            logger.warning(f"Action candidate selection failed: {e}")
            return action, None

        selection_data = selection.as_dict() if hasattr(selection, "as_dict") else dict(selection)
        if not selection_data.get("changed"):
            return action, None

        payload = {
            "goal": goal,
            "context": context or {},
            "selection": selection_data,
        }
        if hasattr(self, "session_logger") and hasattr(self.session_logger, "log"):
            self.session_logger.log("action_candidate_selection", payload)
        self._write_memory_episode("action_candidate_selection", payload, source="action_candidate_selector")
        selected_action = selection_data.get("selected_action", action)
        return selected_action if isinstance(selected_action, dict) else action, selection_data

    def _record_action_value(self, action: dict, result: dict, goal: str, verification: dict = None):
        """Record action outcome evidence for later verifier-guided candidate scoring."""
        profile = getattr(self, "action_value_profile", None)
        if profile is None or not hasattr(profile, "record"):
            return
        try:
            result_data = result if isinstance(result, dict) else {}
            profile.record(action, result_data, goal=goal, verification=verification or result_data.get("action_verification", {}))
        except Exception as e:
            logger.warning(f"Action-value recording failed: {e}")

    def _collect_bounded_planning_memory(
        self,
        goal: str,
        current_state: dict,
        planner: str,
        readers: list[tuple[str, str, Callable[[Optional[int]], str]]],
    ) -> tuple[str, dict]:
        """Build one typed, bounded memory packet for the next planner decision."""
        config = getattr(self, "config", None)
        if not bool(getattr(config, "enable_planning_memory_context", True)):
            contract = {
                "type": "planning_context_contract",
                "schema_version": 2,
                "planner": planner,
                "goal": str(goal or "")[:160],
                "enabled": False,
                "isolation_profile": "planning_memory_disabled_v1",
                "read_limit_chars": 0,
                "cycle_limit_chars": 0,
                "memory_read_count": 0,
                "typed_layer_count": 0,
                "nonempty_read_count": 0,
                "total_result_chars": 0,
                "total_separator_chars": 0,
                "total_context_chars": 0,
                "bounded_ok": True,
                "segments": [],
            }
            self._last_planning_memory_context = ""
            self._last_planning_context_contract = contract
            if hasattr(self, "session_logger") and hasattr(self.session_logger, "log"):
                self.session_logger.log("planning_context_contract", contract)
            return "", contract
        enabled = bool(getattr(config, "enable_bounded_planning_context", True))
        read_limit = max(1, self._small_int(getattr(config, "planning_memory_read_limit_chars", 600) or 600))
        cycle_limit = max(1, self._small_int(getattr(config, "planning_memory_cycle_limit_chars", 2400) or 2400))
        remaining = cycle_limit
        segments = []
        included = []
        for memory_type, layer, reader in readers:
            separator_reserve = 1 if enabled and included else 0
            allowance = min(read_limit, max(0, remaining - separator_reserve)) if enabled else read_limit
            try:
                text = str(reader(allowance if enabled else None) or "")
            except Exception as e:
                logger.warning(f"Planning memory reader {memory_type} failed: {e}")
                text = ""
            if enabled:
                text = text[:max(0, allowance)]
            separator_chars = 1 if text and included else 0
            if text:
                included.append(text)
                if enabled:
                    remaining = max(0, remaining - separator_chars - len(text))
            segments.append({
                "memory_type": memory_type,
                "layer": layer,
                "result_chars": len(text),
                "separator_chars": separator_chars,
                "context_chars": len(text) + separator_chars,
                "has_result": bool(text.strip()),
                "allowance_chars": allowance,
            })

        planning_memory = "\n".join(included)
        total_chars = sum(segment["result_chars"] for segment in segments)
        total_separator_chars = sum(segment["separator_chars"] for segment in segments)
        total_context_chars = len(planning_memory)
        typed_pairs = {f"{segment['layer']}:{segment['memory_type']}" for segment in segments}
        contract = {
            "type": "planning_context_contract",
            "schema_version": 2,
            "planner": planner,
            "goal": str(goal or "")[:160],
            "enabled": enabled,
            "read_limit_chars": read_limit,
            "cycle_limit_chars": cycle_limit,
            "memory_read_count": len(segments),
            "typed_layer_count": len(typed_pairs),
            "nonempty_read_count": sum(1 for segment in segments if segment["has_result"]),
            "total_result_chars": total_chars,
            "total_separator_chars": total_separator_chars,
            "total_context_chars": total_context_chars,
            "bounded_ok": bool(
                enabled
                and total_context_chars <= cycle_limit
                and all(segment["result_chars"] <= read_limit for segment in segments)
            ),
            "segments": segments,
        }
        self._last_planning_memory_context = planning_memory
        self._last_planning_context_contract = contract
        if hasattr(self, "session_logger") and hasattr(self.session_logger, "log"):
            self.session_logger.log("planning_context_contract", contract)
        return self._last_planning_memory_context, contract

    def _attach_planning_context_contract(self, plan: dict, contract: dict) -> dict:
        if not isinstance(plan, dict):
            plan = {"status": "error", "actions": [], "reasoning": "planner returned a non-object result"}
        result = dict(plan)
        result["planning_context_contract"] = dict(contract or {})
        return result

    def _bounded_memory_text(self, value, max_chars: Optional[int]) -> str:
        text = str(value or "")
        if max_chars is None:
            return text
        return text[:max(0, self._small_int(max_chars))]

    def _call_bounded_memory_reader(
        self,
        reader: Callable,
        *args,
        max_chars: Optional[int] = None,
        **kwargs,
    ) -> str:
        """Call current or legacy memory readers and apply the contract limit."""
        try:
            value = reader(*args, max_chars=max_chars, **kwargs)
        except TypeError as exc:
            if "max_chars" not in str(exc):
                raise
            value = reader(*args, **kwargs)
        return self._bounded_memory_text(value, max_chars)

    def _task_memory_context(
        self,
        goal: str,
        current_state: dict = None,
        max_chars: Optional[int] = None,
    ) -> str:
        if not getattr(getattr(self, "config", None), "enable_task_memory_context", True):
            return ""
        task = None
        if hasattr(self, "task_system") and self.task_system:
            try:
                task = self.task_system.get_next_task(current_state or {})
            except Exception as e:
                logger.warning(f"Task memory next-task lookup failed: {e}")
        query = " ".join(part for part in [goal, getattr(task, "title", "")] if part)
        decision = self._memory_read_decision(query or goal, "task", "task_memory", "retrieve")
        result = ""
        retrieval_trace = {}
        if decision.should_retrieve and hasattr(self, "memory") and self.memory and hasattr(self.memory, "task_memory_context"):
            try:
                result = self.memory.task_memory_context(
                    goal,
                    task=task,
                    current_state=current_state or {},
                    limit=3,
                )
                retrieval_trace = self._latest_memory_retrieval_trace()
            except Exception as e:
                logger.warning(f"Task memory context failed: {e}")
        result = self._bounded_memory_text(result, max_chars)
        self._log_memory_read(
            query=query or goal,
            layer="task",
            memory_type="task_memory",
            operation="retrieve",
            result=result,
            source="planner_task_memory",
            decision=decision,
            retrieval_trace=retrieval_trace,
            planning_context=True,
        )
        return result

    def _task_continuity_context(
        self,
        goal: str,
        current_state: dict = None,
        max_chars: Optional[int] = None,
    ) -> str:
        if not getattr(getattr(self, "config", None), "enable_task_continuity_context", True):
            return ""
        query = str(goal or "")
        decision = self._memory_read_decision(query, "task", "task_continuity", "retrieve")
        result = ""
        used_capsule = False
        capsule_trace = {}
        capsule_budget = 600 if max_chars is None else max(0, self._small_int(max_chars))
        if decision.should_retrieve and hasattr(self, "memory") and self.memory and hasattr(self.memory, "task_continuity_context"):
            try:
                capsule_reader = getattr(self.memory, "task_continuity_capsule", None)
                if callable(capsule_reader):
                    used_capsule = True
                    result = capsule_reader(
                        goal,
                        current_state=current_state or {},
                        limit=3,
                        char_budget=capsule_budget,
                    )
                    trace_reader = getattr(self.memory, "get_last_task_continuity_capsule_trace", None)
                    if callable(trace_reader):
                        trace = trace_reader()
                        capsule_trace = trace if isinstance(trace, dict) else {}
                else:
                    result = self.memory.task_continuity_context(
                        goal,
                        current_state=current_state or {},
                        limit=3,
                    )
            except Exception as e:
                logger.warning(f"Task continuity context failed: {e}")
        result = self._bounded_memory_text(result, max_chars)
        self._log_memory_read(
            query=query,
            layer="task",
            memory_type="task_continuity",
            operation="retrieve",
            result=result,
            source="planner_task_continuity",
            decision=decision,
            planning_context=True,
            context_profile="goal_frontier_capsule_v1" if used_capsule else "legacy_task_continuity",
            context_budget_chars=capsule_budget if used_capsule else None,
            context_trace=capsule_trace,
        )
        return result

    def _task_readiness_report(self, current_state: dict = None) -> dict:
        task_system = getattr(self, "task_system", None)
        if not task_system or not hasattr(task_system, "task_readiness_report"):
            return {}
        try:
            report = task_system.task_readiness_report(current_state or {})
        except Exception as e:
            logger.warning(f"Task readiness report failed: {e}")
            return {}
        return report if isinstance(report, dict) else {}

    def _reconcile_m4_satisfied_tasks(
        self,
        observation: dict,
        goal: str,
        cycle: int,
        *,
        source: str = "machine_observation",
    ) -> list:
        if str(getattr(getattr(self, "config", None), "planner_protocol", "") or "") != "m4-fixed-v1":
            return []
        task_system = getattr(self, "task_system", None)
        if not task_system or not hasattr(task_system, "complete_state_satisfied_tasks"):
            return []
        failed_dependency_reports = []
        if hasattr(task_system, "reconcile_failed_dependencies"):
            failed_dependency_reports = task_system.reconcile_failed_dependencies(
                observation,
                inventory_families=M4_MACHINE_STATE_INVENTORY_FAMILIES,
            )
        failed_dependency_completed = [
            task_system.tasks[report["task_id"]]
            for report in failed_dependency_reports
            if report.get("task_id") in task_system.tasks
        ]
        reconciliation_state, inventory_family_grounding = self._m4_task_inventory_family_state(
            observation
        )
        exact_completed = task_system.complete_state_satisfied_tasks(
            observation,
            allowed_criteria=set(M4_TASK_WORLD_STATE_RECONCILIATION_CRITERIA),
        )
        family_candidate_ids = {
            task.id
            for task in task_system.tasks.values()
            if not self._m4_task_uses_exact_inventory_semantics(task, "oak_log")
        }
        family_completed = task_system.complete_state_satisfied_tasks(
            reconciliation_state,
            allowed_criteria=set(M4_TASK_WORLD_STATE_RECONCILIATION_CRITERIA),
            candidate_task_ids=family_candidate_ids,
        )
        completed_by_id = {
            task.id: task
            for task in [
                *failed_dependency_completed,
                *exact_completed,
                *family_completed,
            ]
        }
        completed = list(completed_by_id.values())
        if completed:
            self._flush_task_state_transitions({
                "source": "m4_task_state_reconciliation",
                "reconciliation_source": str(source or "machine_observation"),
                "goal": goal,
                "cycle": cycle,
            })
        if completed and hasattr(getattr(self, "session_logger", None), "log"):
            self.session_logger.log("m4_task_state_reconciliation", {
                "schema_version": 1,
                "policy_id": M4_TASK_WORLD_STATE_RECONCILIATION_POLICY_ID,
                "goal": goal,
                "cycle": cycle,
                "source": str(source or "machine_observation"),
                "allowed_criteria": sorted(M4_TASK_WORLD_STATE_RECONCILIATION_CRITERIA),
                "machine_state_sources": {
                    "inventory": "observation.inventory",
                    "nearby_block_present": "observation.nearby_blocks",
                },
                "inventory_family_grounding": inventory_family_grounding,
                "exact_inventory_semantics_task_ids": sorted(
                    task.id
                    for task in task_system.tasks.values()
                    if self._m4_task_uses_exact_inventory_semantics(task, "oak_log")
                )[:20],
                "completed_task_count": len(completed),
                "failed_dependency_reconciliation_count": len(failed_dependency_reports),
                "completed_tasks": [
                    {
                        "task_id": task.id,
                        "title": task.title,
                        "success_criteria": dict(task.success_criteria or {}),
                    }
                    for task in completed[:20]
                ],
            })
        if failed_dependency_reports and hasattr(getattr(self, "session_logger", None), "log"):
            for report in failed_dependency_reports:
                self.session_logger.log(
                    "m4_failed_dependency_machine_state_reconciliation",
                    {
                        **copy.deepcopy(report),
                        "goal": goal,
                        "cycle": cycle,
                        "source": str(source or "machine_observation"),
                    },
                )
        self._propagate_m4_readiness_recovery_completion(
            observation,
            completed,
            goal=goal,
            cycle=cycle,
            source=source,
        )
        return completed

    @staticmethod
    def _m4_task_inventory_family_state(observation: dict) -> tuple[dict, dict]:
        """Project the GoalVerifier log family into M4 task inventory criteria."""
        state = dict(observation) if isinstance(observation, dict) else {}
        inventory = (
            dict(state.get("inventory", {}))
            if isinstance(state.get("inventory", {}), dict)
            else {}
        )
        member_counts = {}
        for item in GoalVerifier.LOG_ITEMS:
            value = inventory.get(item, 0)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            count = float(value)
            if not math.isfinite(count) or count < 0 or not count.is_integer():
                continue
            if count:
                member_counts[item] = int(count)

        canonical_before = member_counts.get("oak_log", 0)
        canonical_after = sum(member_counts.values())
        inventory["oak_log"] = canonical_after
        state["inventory"] = inventory
        return state, {
            "type": "m4_task_inventory_family_grounding",
            "schema_version": 1,
            "policy_id": "m4-task-inventory-family-grounding-v1",
            "canonical_item": "oak_log",
            "member_items": list(GoalVerifier.LOG_ITEMS),
            "observed_member_counts": member_counts,
            "canonical_count_before": canonical_before,
            "canonical_count_after": canonical_after,
            "activated": canonical_after != canonical_before,
            "source_observation_unchanged": True,
        }

    @staticmethod
    def _m4_inventory_count(value) -> int:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return 0
        count = float(value)
        if not math.isfinite(count) or count < 0 or not count.is_integer():
            return 0
        return int(count)

    @classmethod
    def _m4_task_uses_exact_inventory_semantics(cls, task, item: str) -> bool:
        item = str(item or "").strip().lower()
        if not item or task is None:
            return False
        tags = {
            str(tag or "").strip().lower()
            for tag in (getattr(task, "tags", []) or [])
            if str(tag or "").strip()
        }
        exact_items = set()
        for tag in tags:
            for prefix in ("exact:", "exact_item:", "m4_exact_item:"):
                if tag.startswith(prefix) and tag[len(prefix):]:
                    exact_items.add(tag[len(prefix):])
        if "exact_item" in tags:
            for criteria_name in ("preconditions", "success_criteria"):
                criteria = getattr(task, criteria_name, {})
                criteria = criteria if isinstance(criteria, dict) else {}
                inventory = criteria.get("inventory", {})
                if isinstance(inventory, dict):
                    exact_items.update(str(name).lower() for name in inventory)
        metadata = getattr(task, "metadata", {})
        metadata = metadata if isinstance(metadata, dict) else {}
        requirement = metadata.get("m4_readiness_recovery_requirement", {})
        if (
            isinstance(requirement, dict)
            and requirement.get("inventory_semantics") == "exact"
            and str(requirement.get("canonical_item") or "").lower() == item
        ):
            exact_items.add(item)
        return item in exact_items

    @staticmethod
    def _m4_normalized_task_family(value: str) -> str:
        value = re.sub(r"[^a-z0-9_]+", "_", str(value or "general").strip().lower()).strip("_")
        if value in {"craft", "crafting"}:
            return "crafting"
        if value in {"gather", "gathering", "resource", "resource_collection"}:
            return "resource_collection"
        return value or "general"

    def _m4_consumer_root_provenance(self, task) -> tuple[str, str]:
        task_family = self._m4_normalized_task_family(getattr(task, "type", "general"))
        criteria = getattr(task, "success_criteria", {})
        criteria = criteria if isinstance(criteria, dict) else {}
        inventory = criteria.get("inventory", {})
        outputs = sorted(str(item).lower() for item in inventory) if isinstance(inventory, dict) else []
        if outputs:
            consumer = ",".join(outputs[:4])
        else:
            consumer = re.sub(
                r"[^a-z0-9_]+",
                "_",
                str(getattr(task, "title", "task") or "task").strip().lower(),
            ).strip("_")[:80]
        return task_family, f"{task_family}:{consumer or 'task'}"

    def _m4_readiness_recovery_requirement(
        self,
        item: str,
        required_count,
        consumer_task,
    ) -> dict:
        item = str(item or "").strip().lower()
        count = self._m4_inventory_count(required_count)
        if not item or count <= 0 or consumer_task is None:
            return {}
        exact = self._m4_task_uses_exact_inventory_semantics(consumer_task, item)
        family = item == "oak_log" and not exact
        task_family, consumer_provenance = self._m4_consumer_root_provenance(consumer_task)
        payload = {
            "canonical_item": item,
            "item_family": M4_READINESS_RECOVERY_LOG_FAMILY_ID if family else f"exact:{item}",
            "required_count": count,
            "inventory_semantics": "family" if family else "exact",
            "consumer_root_provenance": consumer_provenance,
            "task_family": task_family,
        }
        fingerprint = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return {
            **payload,
            "requirement_fingerprint": fingerprint,
            "family_members": list(GoalVerifier.LOG_ITEMS) if family else [item],
            "source_root_plan_id": str(getattr(consumer_task, "root_plan_id", "") or ""),
            "source_planner_call_id": str(getattr(consumer_task, "planner_call_id", "") or ""),
        }

    def _m4_requirement_inventory_proof(self, requirement: dict, observation: dict) -> dict:
        requirement = requirement if isinstance(requirement, dict) else {}
        inventory = (
            observation.get("inventory", {})
            if isinstance(observation, dict) and isinstance(observation.get("inventory", {}), dict)
            else {}
        )
        item = str(requirement.get("canonical_item") or "")
        semantics = str(requirement.get("inventory_semantics") or "exact")
        required_count = self._m4_inventory_count(requirement.get("required_count"))
        exact_count = self._m4_inventory_count(inventory.get(item, 0))
        family_counts = {}
        if semantics == "family":
            for member in GoalVerifier.LOG_ITEMS:
                count = self._m4_inventory_count(inventory.get(member, 0))
                if count:
                    family_counts[member] = count
        family_total = sum(family_counts.values()) if semantics == "family" else exact_count
        observed_count = family_total if semantics == "family" else exact_count
        return {
            "canonical_item": item,
            "inventory_semantics": semantics,
            "required_count": required_count,
            "exact_item_counts": {item: exact_count} if item else {},
            "family_member_counts": family_counts,
            "family_total": family_total,
            "observed_count": observed_count,
            "satisfied": bool(required_count > 0 and observed_count >= required_count),
            "source": "observation.inventory",
        }

    def _ensure_m4_readiness_recovery_runtime_state(self):
        if not isinstance(getattr(self, "_m4_readiness_recovery_bindings", None), dict):
            self._m4_readiness_recovery_bindings = {}
        if not isinstance(getattr(self, "_m4_readiness_recovery_propagated_roots", None), set):
            self._m4_readiness_recovery_propagated_roots = set()
        if not isinstance(getattr(self, "_m4_active_readiness_recovery_root_id", None), str):
            self._m4_active_readiness_recovery_root_id = ""

    def _bind_m4_readiness_recovery_goal(
        self,
        child_task,
        blocked_task,
        requirement: dict,
    ) -> dict:
        self._ensure_m4_readiness_recovery_runtime_state()
        if child_task is None or blocked_task is None or not isinstance(requirement, dict):
            return {}
        fingerprint = str(requirement.get("requirement_fingerprint") or "")
        if not fingerprint:
            return {}
        metadata = getattr(child_task, "metadata", {})
        metadata = metadata if isinstance(metadata, dict) else {}
        existing_root_id = str(
            (metadata.get("m4_readiness_recovery_binding", {}) or {}).get("root_id") or ""
        )
        root_id = existing_root_id or "m4rr-" + hashlib.sha256(
            f"{fingerprint}:{child_task.id}:{blocked_task.id}".encode("utf-8")
        ).hexdigest()[:16]
        existing = self._m4_readiness_recovery_bindings.get(root_id, {})
        stale_sibling_candidate_ids = existing.get("stale_sibling_candidate_ids")
        if not isinstance(stale_sibling_candidate_ids, list):
            stale_sibling_candidate_ids = self._m4_readiness_recovery_sibling_candidate_ids(
                requirement,
                child_id=str(child_task.id),
            )
        binding = {
            "schema_version": 1,
            "policy_id": M4_READINESS_RECOVERY_COMPLETION_POLICY_ID,
            "root_id": root_id,
            "root_goal": str(getattr(child_task, "title", "") or ""),
            "root_status": str(existing.get("root_status") or "active"),
            "child_id": str(child_task.id),
            "blocked_task_id": str(blocked_task.id),
            "blocked_task_title": str(getattr(blocked_task, "title", "") or ""),
            "requirement": copy.deepcopy(requirement),
            "requirement_fingerprint": fingerprint,
            "completion_source": str(existing.get("completion_source") or ""),
            "inventory_proof": copy.deepcopy(existing.get("inventory_proof", {})),
            "stale_sibling_candidate_ids": list(stale_sibling_candidate_ids),
            "stale_sibling_ids": list(existing.get("stale_sibling_ids", [])),
        }
        self._m4_readiness_recovery_bindings[root_id] = binding
        child_task.metadata = {
            **metadata,
            "m4_readiness_recovery_requirement": copy.deepcopy(requirement),
            "m4_readiness_recovery_binding": {
                "policy_id": M4_READINESS_RECOVERY_COMPLETION_POLICY_ID,
                "root_id": root_id,
                "child_id": str(child_task.id),
                "blocked_task_id": str(blocked_task.id),
                "requirement_fingerprint": fingerprint,
            },
        }
        self._m4_active_readiness_recovery_root_id = root_id
        return binding

    def _m4_readiness_recovery_binding_for_goal(self, goal: str, root_id: str = "") -> dict:
        self._ensure_m4_readiness_recovery_runtime_state()
        candidate_id = str(root_id or self._m4_active_readiness_recovery_root_id or "")
        if candidate_id:
            binding = self._m4_readiness_recovery_bindings.get(candidate_id, {})
            if binding and str(binding.get("root_goal") or "") == str(goal or ""):
                return binding
        for binding in self._m4_readiness_recovery_bindings.values():
            if str(binding.get("root_goal") or "") == str(goal or ""):
                return binding
        return {}

    def _m4_readiness_recovery_goal_machine_completed(self, goal: str, root_id: str = "") -> bool:
        binding = self._m4_readiness_recovery_binding_for_goal(goal, root_id)
        return bool(
            binding
            and binding.get("root_status") == "completed"
            and binding.get("completion_source") in {
                "machine_state",
                "machine_state_reconciliation",
                "action_result",
            }
            and isinstance(binding.get("inventory_proof"), dict)
            and binding["inventory_proof"].get("satisfied") is True
        )

    def _m4_requirement_for_consumer_task(self, task, canonical_item: str) -> dict:
        if task is None:
            return {}
        preconditions = getattr(task, "preconditions", {})
        preconditions = preconditions if isinstance(preconditions, dict) else {}
        inventory = preconditions.get("inventory", {})
        inventory = inventory if isinstance(inventory, dict) else {}
        if canonical_item not in inventory:
            return {}
        return self._m4_readiness_recovery_requirement(
            canonical_item,
            inventory.get(canonical_item),
            task,
        )

    def _m4_readiness_recovery_sibling_candidate_ids(
        self,
        requirement: dict,
        *,
        child_id: str = "",
    ) -> list[str]:
        task_system = getattr(self, "task_system", None)
        if not task_system or not isinstance(requirement, dict):
            return []
        canonical_item = str(requirement.get("canonical_item") or "")
        fingerprint = str(requirement.get("requirement_fingerprint") or "")
        if not canonical_item or not fingerprint:
            return []
        terminal = {TaskStatus.COMPLETED, TaskStatus.CANCELLED, TaskStatus.FAILED}
        candidates = []
        for task in sorted(task_system.tasks.values(), key=lambda item: (item.created_at, item.id)):
            if task.id == child_id or task.status in terminal:
                continue
            if "readiness_recovery" in set(task.tags or []):
                continue
            candidate = self._m4_requirement_for_consumer_task(task, canonical_item)
            if candidate.get("requirement_fingerprint") == fingerprint:
                candidates.append(task.id)
        return candidates

    def _sweep_m4_readiness_recovery_siblings(
        self,
        binding: dict,
        inventory_proof: dict,
    ) -> list[dict]:
        task_system = getattr(self, "task_system", None)
        if not task_system or not hasattr(task_system, "cancel_task"):
            return []
        requirement = binding.get("requirement", {}) if isinstance(binding, dict) else {}
        canonical_item = str(requirement.get("canonical_item") or "")
        fingerprint = str(binding.get("requirement_fingerprint") or "")
        terminal = {TaskStatus.COMPLETED, TaskStatus.CANCELLED, TaskStatus.FAILED}
        candidate_ids = {
            str(task_id)
            for task_id in binding.get("stale_sibling_candidate_ids", [])
            if task_id
        }
        if not candidate_ids:
            return []
        dispositions = []
        tasks = [task_system.tasks[task_id] for task_id in candidate_ids if task_id in task_system.tasks]
        for task in sorted(tasks, key=lambda item: (item.created_at, item.id)):
            if task.status in terminal:
                continue
            if "readiness_recovery" in set(task.tags or []):
                continue
            candidate = self._m4_requirement_for_consumer_task(task, canonical_item)
            if not candidate or candidate.get("requirement_fingerprint") != fingerprint:
                continue
            candidate_proof = self._m4_requirement_inventory_proof(candidate, {
                "inventory": {
                    **dict(inventory_proof.get("exact_item_counts", {})),
                    **dict(inventory_proof.get("family_member_counts", {})),
                }
            })
            if candidate_proof.get("satisfied") is not True:
                continue
            result = {
                "disposition": "cancelled_as_satisfied",
                "cancelled_by": M4_READINESS_RECOVERY_COMPLETION_POLICY_ID,
                "root_id": str(binding.get("root_id") or ""),
                "child_id": str(binding.get("child_id") or ""),
                "requirement_fingerprint": fingerprint,
                "inventory_proof": copy.deepcopy(inventory_proof),
            }
            task_system.cancel_task(
                task.id,
                result,
                reason="m4_readiness_recovery_requirement_satisfied",
            )
            dispositions.append({
                "task_id": task.id,
                "task_title": task.title,
                "disposition": "cancelled_as_satisfied",
                "requirement_fingerprint": fingerprint,
                "source_root_plan_id": str(task.root_plan_id or ""),
            })
        return dispositions

    def _propagate_m4_readiness_recovery_completion(
        self,
        observation: dict,
        completed_tasks: list = None,
        *,
        goal: str = "",
        cycle: int = 0,
        source: str = "machine_observation",
    ) -> list[dict]:
        if str(getattr(getattr(self, "config", None), "planner_protocol", "") or "") != "m4-fixed-v1":
            return []
        self._ensure_m4_readiness_recovery_runtime_state()
        task_system = getattr(self, "task_system", None)
        if not task_system:
            return []
        completed_ids = {
            str(getattr(task, "id", "") or "")
            for task in (completed_tasks or [])
        }
        reports = []
        for root_id in sorted(self._m4_readiness_recovery_bindings):
            binding = self._m4_readiness_recovery_bindings[root_id]
            child = task_system.tasks.get(str(binding.get("child_id") or ""))
            if child is None:
                continue
            if binding.get("root_status") == "completed":
                proof = binding.get("inventory_proof", {})
                new_siblings = self._sweep_m4_readiness_recovery_siblings(binding, proof)
                if new_siblings:
                    self._flush_task_state_transitions({
                        "source": "m4_readiness_recovery_stale_sibling_sweep",
                        "goal": goal,
                        "cycle": cycle,
                    })
                    payload = {
                        "schema_version": 1,
                        "policy_id": M4_READINESS_RECOVERY_COMPLETION_POLICY_ID,
                        "root_id": root_id,
                        "child_id": child.id,
                        "requirement_fingerprint": binding.get("requirement_fingerprint"),
                        "inventory_proof": copy.deepcopy(proof),
                        "stale_sibling_count": len(new_siblings),
                        "stale_siblings": new_siblings,
                        "root_completion_replayed": False,
                        "context": {"goal": goal, "cycle": cycle, "source": source},
                    }
                    if hasattr(getattr(self, "session_logger", None), "log"):
                        self.session_logger.log("m4_readiness_recovery_stale_sibling_sweep", payload)
                continue
            child_result = child.result if isinstance(child.result, dict) else {}
            completion_source = str(child_result.get("completed_by") or "")
            if child.status != TaskStatus.COMPLETED:
                continue
            if completion_source not in {
                "machine_state",
                "machine_state_reconciliation",
                "action_result",
            }:
                continue
            requirement = binding.get("requirement", {})
            proof = self._m4_requirement_inventory_proof(requirement, observation)
            if proof.get("satisfied") is not True:
                continue
            if root_id in self._m4_readiness_recovery_propagated_roots:
                continue
            fingerprint = str(binding.get("requirement_fingerprint") or "")
            binding["root_status"] = "completed"
            binding["completion_source"] = completion_source
            binding["inventory_proof"] = copy.deepcopy(proof)
            self._m4_readiness_recovery_propagated_roots.add(root_id)
            child.result = {
                **child_result,
                "m4_readiness_recovery_root_completion": {
                    "policy_id": M4_READINESS_RECOVERY_COMPLETION_POLICY_ID,
                    "root_id": root_id,
                    "child_id": child.id,
                    "requirement_fingerprint": fingerprint,
                    "completion_source": completion_source,
                },
            }
            stale_siblings = self._sweep_m4_readiness_recovery_siblings(binding, proof)
            binding["stale_sibling_ids"] = [item["task_id"] for item in stale_siblings]
            if stale_siblings:
                self._flush_task_state_transitions({
                    "source": "m4_readiness_recovery_completion_propagation",
                    "goal": goal,
                    "cycle": cycle,
                    "root_id": root_id,
                    "child_id": child.id,
                })
            payload = {
                "schema_version": 1,
                "policy_id": M4_READINESS_RECOVERY_COMPLETION_POLICY_ID,
                "root_id": root_id,
                "child_id": child.id,
                "blocked_task_id": str(binding.get("blocked_task_id") or ""),
                "requirement_fingerprint": fingerprint,
                "requirement": copy.deepcopy(requirement),
                "inventory_proof": copy.deepcopy(proof),
                "completion_source": completion_source,
                "child_completed_in_current_reconciliation": child.id in completed_ids,
                "root_status": "completed",
                "root_completion_applied": True,
                "stale_sibling_count": len(stale_siblings),
                "stale_siblings": stale_siblings,
                "context": {"goal": goal, "cycle": cycle, "source": source},
            }
            if hasattr(getattr(self, "session_logger", None), "log"):
                self.session_logger.log("m4_readiness_recovery_completion_propagation", payload)
            if hasattr(self, "memory"):
                self._write_memory_episode(
                    "m4_readiness_recovery_completion_propagation",
                    payload,
                    source="m4_readiness_recovery",
                )
            reports.append(payload)
        return reports

    def _m4_readiness_recovery_inventory_context(self, current_state: dict) -> str:
        if str(getattr(getattr(self, "config", None), "planner_protocol", "") or "") != "m4-fixed-v1":
            return ""
        self._ensure_m4_readiness_recovery_runtime_state()
        bindings = sorted(
            self._m4_readiness_recovery_bindings.values(),
            key=lambda item: (
                0 if item.get("root_id") == self._m4_active_readiness_recovery_root_id else 1,
                str(item.get("root_id") or ""),
            ),
        )
        if not bindings:
            return ""
        rows = []
        lines = ["Normalized inventory requirements (machine state; bounded):"]
        for binding in bindings[:M4_READINESS_RECOVERY_CONTEXT_MAX_REQUIREMENTS]:
            requirement = binding.get("requirement", {})
            proof = self._m4_requirement_inventory_proof(requirement, current_state or {})
            item = str(requirement.get("canonical_item") or "")
            exact_count = proof.get("exact_item_counts", {}).get(item, 0)
            line = (
                f"- requirement={str(binding.get('requirement_fingerprint') or '')[:12]}; "
                f"item={item}; semantics={requirement.get('inventory_semantics')}; "
                f"exact_count={exact_count}; family_total={proof.get('family_total', 0)}; "
                f"required={proof.get('required_count', 0)}; "
                f"satisfied={str(bool(proof.get('satisfied'))).lower()}; "
                f"root_status={binding.get('root_status', 'active')}"
            )
            candidate = "\n".join([*lines, line])
            if len(candidate) > M4_READINESS_RECOVERY_CONTEXT_MAX_CHARS:
                break
            lines.append(line)
            rows.append({
                "root_id": str(binding.get("root_id") or ""),
                "child_id": str(binding.get("child_id") or ""),
                "requirement_fingerprint": str(binding.get("requirement_fingerprint") or ""),
                "canonical_item": item,
                "inventory_semantics": requirement.get("inventory_semantics"),
                "exact_item_count": exact_count,
                "family_total": proof.get("family_total", 0),
                "required_count": proof.get("required_count", 0),
                "satisfied": proof.get("satisfied") is True,
                "root_status": binding.get("root_status", "active"),
            })
        text = "\n".join(lines) if rows else ""
        if text and hasattr(getattr(self, "session_logger", None), "log"):
            self.session_logger.log("m4_readiness_recovery_planner_context", {
                "schema_version": 1,
                "policy_id": M4_READINESS_RECOVERY_COMPLETION_POLICY_ID,
                "requirement_count": len(bindings),
                "rendered_requirement_count": len(rows),
                "max_requirement_count": M4_READINESS_RECOVERY_CONTEXT_MAX_REQUIREMENTS,
                "char_count": len(text),
                "max_chars": M4_READINESS_RECOVERY_CONTEXT_MAX_CHARS,
                "requirements": rows,
            })
        return text

    def _task_readiness_context(
        self,
        goal: str,
        current_state: dict = None,
        limit: int = 4,
        report: dict = None,
    ) -> str:
        """Expose verified task graph readiness and blockers as compact planner context."""
        if not getattr(getattr(self, "config", None), "enable_task_readiness_context", True):
            return ""
        report = report if isinstance(report, dict) else self._task_readiness_report(current_state)
        tasks = [task for task in report.get("tasks", []) if isinstance(task, dict)]
        normalized_inventory_context = self._m4_readiness_recovery_inventory_context(
            current_state or {}
        )
        if not tasks:
            return normalized_inventory_context
        ready = [task for task in tasks if task.get("ready")]
        blocked = [task for task in tasks if not task.get("ready")]
        lines = [
            "Task readiness diagnosis "
            "(verified task graph; honor ready tasks and insert missing prerequisites before retrying blocked tasks):",
            (
                f"- summary: ready={report.get('ready_count', 0)}, "
                f"blocked={report.get('blocked_count', 0)}, "
                f"accepted={report.get('accepted_count', 0)}, active={report.get('active_count', 0)}"
            ),
        ]
        max_items = max(1, min(self._small_int(limit or 4), 6))
        ready_limit = min(len(ready), max_items)
        if blocked and ready_limit >= max_items:
            ready_limit = max(0, max_items - 1)
        blocked_limit = max_items - ready_limit
        if blocked and blocked_limit <= 0:
            blocked_limit = 1
        for task in ready[:ready_limit]:
            lines.append(self._format_task_readiness_line(task, ready=True))
        for task in blocked[:blocked_limit]:
            lines.append(self._format_task_readiness_line(task, ready=False))
        payload = {
            "goal": goal,
            "ready_count": report.get("ready_count", 0),
            "blocked_count": report.get("blocked_count", 0),
            "task_count": report.get("task_count", 0),
        }
        if hasattr(self, "session_logger") and hasattr(self.session_logger, "log"):
            self.session_logger.log("task_readiness_planner_context", payload)
        if normalized_inventory_context:
            lines.append(normalized_inventory_context)
        return "\n".join(line for line in lines if line)

    def _log_skill_frontier_route(self, trace: dict):
        if not hasattr(self, "session_logger") or not hasattr(self.session_logger, "log"):
            return
        selected = []
        for item in trace.get("selected", [])[:5]:
            if not isinstance(item, dict):
                continue
            selected.append({
                "skill_name": str(item.get("skill_name") or "")[:96],
                "score": item.get("score", 0.0),
                "reliability": item.get("reliability", 0.0),
                "readiness": str(item.get("readiness") or "")[:24],
                "assigned_match_count": item.get("assigned_match_count", 0),
                "gap_match_count": item.get("gap_match_count", 0),
                "covered_task_ids": [str(value)[:64] for value in item.get("covered_task_ids", [])[:8]],
                "reason_codes": [str(value)[:48] for value in item.get("reason_codes", [])[:8]],
            })
        self.session_logger.log("skill_frontier_route", {
            "schema_version": 1,
            "profile": "frontier_transition_skill_router_v1",
            "frontier_task_count": trace.get("frontier_task_count", 0),
            "ready_task_count": trace.get("ready_task_count", 0),
            "blocked_task_count": trace.get("blocked_task_count", 0),
            "candidate_count": trace.get("candidate_count", 0),
            "blocked_candidate_count": trace.get("blocked_candidate_count", 0),
            "selected_skill_names": [
                str(value)[:96] for value in trace.get("selected_skill_names", [])[:8]
            ],
            "covered_task_ids": [str(value)[:64] for value in trace.get("covered_task_ids", [])[:12]],
            "uncovered_task_ids": [str(value)[:64] for value in trace.get("uncovered_task_ids", [])[:12]],
            "selected": selected,
        })

    def _format_task_readiness_line(self, task: dict, ready: bool) -> str:
        title = str(task.get("title") or "task")[:120]
        status = str(task.get("status") or "unknown")
        priority = self._small_int(task.get("priority", 3))
        score = task.get("score", 0)
        prefix = "ready" if ready else "blocked"
        parts = [f"- {prefix}: {title} (status={status}, priority={priority}, score={score})"]
        if ready:
            triggers = task.get("opportunity_triggers", []) if isinstance(task.get("opportunity_triggers", []), list) else []
            if triggers:
                parts.append("triggers=" + ",".join(str(item) for item in triggers[:4]))
            return "; ".join(parts)

        dependencies = task.get("missing_dependencies", [])
        if isinstance(dependencies, list) and dependencies:
            dep_text = ", ".join(
                f"{dep.get('title') or dep.get('id')}:{dep.get('status', 'missing')}"
                for dep in dependencies[:3]
                if isinstance(dep, dict)
            )
            if dep_text:
                parts.append(f"missing_dependencies={dep_text}")
        missing = task.get("missing_preconditions", {}) if isinstance(task.get("missing_preconditions", {}), dict) else {}
        if missing:
            parts.append(f"missing_preconditions={self._format_task_preconditions(missing)}")
        blockers = task.get("blockers", []) if isinstance(task.get("blockers", []), list) else []
        blocker_text = ", ".join(str(item) for item in blockers[:3] if item)
        if blocker_text:
            parts.append(f"blockers={blocker_text}")
        return "; ".join(parts)

    def _record_task_continuity(
        self,
        goal: str,
        current_state: dict = None,
        plan: dict = None,
        source: str = "agent",
        context: dict = None,
        operation: str = "grow",
        validation_status: str = "unverified",
        validation_evidence: dict = None,
        branch_status: str = "active",
        parent_checkpoint_id: str = "",
        branch_id: str = "",
        revision_target_checkpoint_id: str = "",
        revision_reason: str = "",
        revision_status: str = "",
        restoration_applied: bool = False,
    ):
        if not getattr(getattr(self, "config", None), "enable_task_continuity_context", True):
            return None
        payload_preview = {
            "goal": goal,
            "source": source,
            "plan_status": plan.get("status") if isinstance(plan, dict) else "",
            "context": context or {},
            "operation": operation,
            "validation_status": validation_status,
            "branch_status": branch_status,
        }
        decision = self._memory_write_decision(
            layer="task",
            memory_type="task_continuity",
            operation="record_task_continuity",
            content=payload_preview,
            source=source,
            confidence=0.82,
        )
        record = None
        if decision.should_persist and hasattr(self, "memory") and self.memory and hasattr(self.memory, "record_task_continuity"):
            try:
                record = self.memory.record_task_continuity(
                    goal,
                    task_system=getattr(self, "task_system", None),
                    current_state=current_state or {},
                    plan=plan or {},
                    source=source,
                    execution_id=str(getattr(getattr(self, "session_logger", None), "session_id", "") or ""),
                    operation=operation,
                    parent_checkpoint_id=parent_checkpoint_id,
                    branch_id=branch_id,
                    validation_status=validation_status,
                    validation_evidence=validation_evidence or {},
                    branch_status=branch_status,
                    revision_target_checkpoint_id=revision_target_checkpoint_id,
                    revision_reason=revision_reason,
                    revision_status=revision_status,
                    restoration_applied=restoration_applied,
                )
            except Exception as e:
                logger.warning(f"Task continuity record failed: {e}")
        content = asdict(record) if record is not None else payload_preview
        self._log_memory_write(
            layer="task",
            memory_type="task_continuity",
            operation="record_task_continuity",
            content=content,
            source=source,
            confidence=0.82,
            decision=decision,
        )
        if record is not None and hasattr(self, "session_logger") and hasattr(self.session_logger, "log"):
            self.session_logger.log("task_continuity_checkpoint", {
                "goal": goal,
                "source": source,
                "record_id": record.id,
                "schema_version": record.schema_version,
                "operation": record.operation,
                "execution_id": record.execution_id,
                "branch_id": record.branch_id,
                "parent_checkpoint_id": record.parent_checkpoint_id,
                "root_checkpoint_id": record.root_checkpoint_id,
                "depth": record.depth,
                "lineage_status": record.lineage_status,
                "validation_status": record.validation_status,
                "branch_status": record.branch_status,
                "revision_target_checkpoint_id": record.revision_target_checkpoint_id,
                "revision_status": record.revision_status,
                "restoration_applied": record.restoration_applied,
                "summary": record.summary,
                "status_counts": record.status_counts,
                "ready_count": len(record.ready_tasks),
                "blocked_count": len(record.blocked_tasks),
                "failed_count": len(record.failed_tasks),
            })
        return record

    def _write_memory_context(self, entry: dict, source: str = "agent_context"):
        decision = self._memory_write_decision(
            layer="context",
            memory_type="context",
            operation="write_context",
            content=entry,
            source=source,
            confidence=0.7,
        )
        if decision.should_persist and hasattr(self, "memory") and self.memory and hasattr(self.memory, "write_context"):
            self.memory.write_context(entry)
        self._log_memory_write(
            layer="context",
            memory_type="context",
            operation="write_context",
            content=entry,
            source=source,
            confidence=0.7,
            decision=decision,
        )

    def _write_memory_episode(self, event_type: str, data: dict, source: str = "agent_episode"):
        confidence = 0.85 if event_type in {
            "goal_end",
            "goal_verification",
            "task_state_update",
            "failure_correction_completed",
            "auto_goal_complete",
        } else 0.65
        decision = self._memory_write_decision(
            layer="episodic",
            memory_type=event_type,
            operation="write_episode",
            content=data,
            source=source or event_type,
            confidence=confidence,
        )
        if decision.should_persist and hasattr(self, "memory") and self.memory and hasattr(self.memory, "write_episode"):
            self.memory.write_episode(event_type, data)
        self._log_memory_write(
            layer="episodic",
            memory_type=event_type,
            operation="write_episode",
            content=data,
            source=source or event_type,
            confidence=confidence,
            decision=decision,
        )

    def _read_relevant_memory(
        self,
        query: str,
        current_state: dict = None,
        source: str = "planner",
        max_chars: Optional[int] = None,
    ) -> str:
        decision = self._memory_read_decision(query, "mixed", "relevant_memory", "retrieve")
        result = ""
        read_filter_report = {}
        retrieval_trace = {}
        if decision.should_retrieve and hasattr(self, "memory") and self.memory and hasattr(self.memory, "get_relevant_memory"):
            result = self.memory.get_relevant_memory(query, current_state=current_state)
            retrieval_trace = self._latest_memory_retrieval_trace()
            if hasattr(self.memory, "memory_read_filter_report"):
                read_filter_report = self.memory.memory_read_filter_report(query, current_state=current_state)
        result = self._bounded_memory_text(result, max_chars)
        self._log_memory_read(
            query=query,
            layer="mixed",
            memory_type="relevant_memory",
            operation="retrieve",
            result=result,
            source=source,
            decision=decision,
            read_filter_report=read_filter_report,
            retrieval_trace=retrieval_trace,
            planning_context=True,
        )
        return result

    def _read_context_window(self, source: str = "planner", max_chars: Optional[int] = None) -> str:
        decision = self._memory_read_decision("context_window", "context", "context_window", "read")
        result = ""
        if decision.should_retrieve and hasattr(self, "memory") and self.memory and hasattr(self.memory, "get_context_window"):
            result = self.memory.get_context_window()
        result = self._bounded_memory_text(result, max_chars)
        self._log_memory_read(
            query="context_window",
            layer="context",
            memory_type="context_window",
            operation="read",
            result=result,
            source=source,
            decision=decision,
            planning_context=True,
        )
        return result

    def _manage_memory_save_session(self):
        session_id = str(getattr(getattr(self, "session_logger", None), "session_id", "session"))
        decision = self._memory_manage_decision("save_session", layer="episodic", memory_type="lifecycle")
        if decision.should_persist and hasattr(self, "memory") and self.memory and hasattr(self.memory, "save_session"):
            self.memory.save_session(session_id)
        self._log_memory_manage("save_session", {"session_id": session_id}, layer="episodic", decision=decision)

    def _memory_write_decision(
        self,
        layer: str,
        memory_type: str,
        operation: str,
        content,
        source: str,
        confidence: float,
    ) -> MemoryPolicyDecision:
        if not getattr(getattr(self, "config", None), "enable_memory_persistence", True):
            return MemoryPolicyDecision(
                operation=operation,
                layer=layer,
                memory_type=memory_type,
                decision="write_blocked",
                reason="memory persistence disabled by runtime profile",
                should_persist=False,
                should_retrieve=False,
            )
        if hasattr(self, "memory_policy") and self.memory_policy:
            return self.memory_policy.decide_write(layer, memory_type, operation, content, source, confidence)
        return MemoryPolicyDecision(
            operation=operation,
            layer=layer,
            memory_type=memory_type,
            decision="write_allowed",
            reason="memory policy disabled",
        )

    def _memory_read_decision(self, query: str, layer: str, memory_type: str, operation: str) -> MemoryPolicyDecision:
        if hasattr(self, "memory_policy") and self.memory_policy:
            return self.memory_policy.decide_read(query, layer, memory_type, operation)
        return MemoryPolicyDecision(
            operation=operation,
            layer=layer,
            memory_type=memory_type,
            decision="read_allowed",
            reason="memory policy disabled",
            should_persist=False,
            should_retrieve=True,
        )

    def _memory_manage_decision(self, operation: str, layer: str = "memory", memory_type: str = "lifecycle") -> MemoryPolicyDecision:
        if not getattr(getattr(self, "config", None), "enable_memory_persistence", True):
            return MemoryPolicyDecision(
                operation=operation,
                layer=layer,
                memory_type=memory_type,
                decision="manage_blocked",
                reason="memory persistence disabled by runtime profile",
                should_persist=False,
                should_retrieve=False,
            )
        if hasattr(self, "memory_policy") and self.memory_policy:
            return self.memory_policy.decide_manage(operation, layer, memory_type)
        return MemoryPolicyDecision(
            operation=operation,
            layer=layer,
            memory_type=memory_type,
            decision="manage_allowed",
            reason="memory policy disabled",
            should_persist=False,
        )

    def _log_memory_write(
        self,
        layer: str,
        memory_type: str,
        operation: str,
        content,
        source: str = "",
        confidence: float = 0.7,
        decision: MemoryPolicyDecision = None,
    ):
        if not hasattr(self, "session_logger") or not hasattr(self.session_logger, "log"):
            return
        payload = {
            "operation": operation,
            "layer": layer,
            "memory_type": memory_type,
            "source": source,
            "content": self._memory_preview(content),
            "keys": sorted(content.keys()) if isinstance(content, dict) else [],
            "confidence": confidence,
        }
        if decision is not None:
            payload["policy_decision"] = decision.as_dict()
        self.session_logger.log("memory_write", payload)

    def _log_memory_read(
        self,
        query: str,
        layer: str,
        memory_type: str,
        operation: str,
        result,
        source: str = "",
        decision: MemoryPolicyDecision = None,
        read_filter_report: dict = None,
        retrieval_trace: dict = None,
        planning_context: bool = True,
        context_profile: str = "",
        context_budget_chars: Optional[int] = None,
        context_trace: dict = None,
    ):
        if not hasattr(self, "session_logger") or not hasattr(self.session_logger, "log"):
            return
        text = str(result or "")
        payload = {
            "operation": operation,
            "layer": layer,
            "memory_type": memory_type,
            "source": source,
            "query": str(query or "")[:160],
            "result_chars": len(text),
            "has_result": bool(text.strip()),
            "planning_context": bool(planning_context),
        }
        if context_profile:
            payload["context_profile"] = str(context_profile)[:80]
        if context_budget_chars is not None:
            budget = max(0, self._small_int(context_budget_chars))
            payload["context_budget_chars"] = budget
            payload["context_within_budget"] = len(text) <= budget
        if context_trace:
            allowed_trace_keys = {
                "schema_version",
                "profile",
                "char_budget",
                "result_chars",
                "full_context_chars",
                "truncated",
                "required_lines_complete",
                "frontier_available",
                "frontier_injected",
                "next_actions_available",
                "next_actions_injected",
                "active_branch_count",
                "mode",
                "path_checkpoint_count",
                "nonselected_branch_count",
            }
            payload["context_trace"] = {
                key: context_trace.get(key)
                for key in allowed_trace_keys
                if key in context_trace
            }
        if decision is not None:
            payload["policy_decision"] = decision.as_dict()
        if read_filter_report:
            payload["read_filter_report"] = read_filter_report
        trace_payload = self._memory_retrieval_trace_payload(retrieval_trace or {})
        if trace_payload:
            payload["retrieval_trace"] = trace_payload
        self.session_logger.log("memory_read", payload)

    def _latest_memory_retrieval_trace(self) -> dict:
        if not hasattr(self, "memory") or not self.memory:
            return {}
        try:
            if hasattr(self.memory, "get_last_retrieval_trace"):
                trace = self.memory.get_last_retrieval_trace()
            else:
                trace = getattr(self.memory, "last_retrieval_trace", {})
        except Exception as e:
            logger.warning(f"Memory retrieval trace unavailable: {e}")
            return {}
        return trace if isinstance(trace, dict) else {}

    def _memory_retrieval_trace_payload(self, trace: dict) -> dict:
        if not isinstance(trace, dict):
            return {}
        allowed_keys = {
            "trace_version",
            "source",
            "query_hash",
            "weighted_retrieval_enabled",
            "attribution_hint_count",
            "total_match_count",
            "memory_match_count",
            "transfer_match_count",
            "semantic_match_count",
            "episodic_match_count",
            "causal_match_count",
            "weighted_match_count",
            "weighted_memory_match_count",
            "weighted_transfer_match_count",
            "top_memory_ids",
            "top_transfer_ids",
            "top_weighted_memory_ids",
            "top_weighted_transfer_ids",
            "attribution_policy_counts",
            "max_positive_weight_delta",
            "max_negative_weight_delta",
            "max_abs_weight_delta",
        }
        payload = {}
        for key in sorted(allowed_keys):
            if key not in trace:
                continue
            value = trace.get(key)
            if isinstance(value, (str, int, float, bool)) or value is None:
                payload[key] = value
            elif isinstance(value, list):
                payload[key] = [str(item)[:80] for item in value[:12]]
            elif isinstance(value, dict):
                payload[key] = {str(k)[:80]: v for k, v in value.items()}
        return payload

    def _log_memory_manage(
        self,
        operation: str,
        data: dict = None,
        layer: str = "memory",
        decision: MemoryPolicyDecision = None,
    ):
        if not hasattr(self, "session_logger") or not hasattr(self.session_logger, "log"):
            return
        payload = {
            "operation": operation,
            "layer": layer,
            "memory_type": "lifecycle",
            "source": "agent_runtime",
            "content": self._memory_preview(data or {}),
            "confidence": 0.8,
        }
        if decision is not None:
            payload["policy_decision"] = decision.as_dict()
        self.session_logger.log("memory_manage", payload)

    def _memory_preview(self, value, limit: int = 240) -> str:
        try:
            text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        except Exception:
            text = str(value)
        return text[:limit]

    def _visual_action_context(self, goal: str, observation: dict, limit: int = 3) -> str:
        suggestions = self._visual_action_suggestions(goal, observation, limit=limit)
        if not suggestions:
            return ""
        lines = []
        for suggestion in suggestions[:limit]:
            action = suggestion.get("action", {})
            lines.append(
                f"- {suggestion.get('kind')}: prefer {action.get('type')} "
                f"{action.get('parameters', {})} because {suggestion.get('reason')}"
            )
        return "Visual action grounding hints:\n" + "\n".join(lines)

    def _self_evolution_context(self, goal: str, observation: dict) -> str:
        policy = getattr(self, "self_evolution_policy", None)
        if not policy or not getattr(getattr(self, "config", None), "enable_self_evolution_policy", True):
            return ""
        try:
            context = policy.planner_context(goal, observation)
        except Exception as e:
            logger.warning(f"Self-evolution policy context failed: {e}")
            return ""
        if context:
            advice = policy.advise(goal, observation).as_dict()
            self._log_policy_intervention("hint", {
                "goal": goal,
                "policy": "self_evolution",
                "advice": advice,
            })
        return context

    def _apply_visual_action_grounding(self, plan: dict, observation: dict, goal: str) -> dict:
        if not getattr(getattr(self, "config", None), "enable_visual_action_grounding", True):
            return plan
        suggestions = self._visual_action_suggestions(goal, observation)
        if suggestions:
            self._log_visual_action_suggestions(goal, suggestions)
        if not suggestions or not isinstance(plan, dict):
            return plan

        grounded = dict(plan)
        actions = list(grounded.get("actions", []) or [])
        danger = next((item for item in suggestions if str(item.get("kind", "")).startswith("danger_")), None)
        if danger and not self._action_in_sequence(danger.get("action", {}), actions):
            grounded["actions"] = [danger["action"]] + actions
            grounded["status"] = "in_progress"
            grounded["reasoning"] = self._append_reasoning(
                grounded.get("reasoning", ""),
                f"Visual grounding inserted safety action: {danger.get('reason')}",
            )
            self._log_visual_action_intervention(goal, danger, "prepend_danger")
            return grounded

        if not actions:
            best = suggestions[0]
            grounded["actions"] = [best["action"]]
            grounded["status"] = "in_progress"
            grounded["reasoning"] = self._append_reasoning(
                grounded.get("reasoning", ""),
                f"Visual grounding supplied action: {best.get('reason')}",
            )
            self._log_visual_action_intervention(goal, best, "fill_empty_plan")
            return grounded

        approach = self._visual_approach_for_action(actions[0], suggestions)
        if approach and not self._action_in_sequence(approach.get("action", {}), actions):
            grounded["actions"] = [approach["action"]] + actions
            grounded["status"] = "in_progress"
            grounded["reasoning"] = self._append_reasoning(
                grounded.get("reasoning", ""),
                f"Visual grounding inserted approach action: {approach.get('reason')}",
            )
            self._log_visual_action_intervention(goal, approach, "prepend_approach")
            return grounded

        focus = self._visual_focus_for_action(actions[0], suggestions)
        if focus and not self._action_in_sequence(focus.get("action", {}), actions):
            grounded["actions"] = [focus["action"]] + actions
            grounded["status"] = "in_progress"
            grounded["reasoning"] = self._append_reasoning(
                grounded.get("reasoning", ""),
                f"Visual grounding inserted focus action: {focus.get('reason')}",
            )
            self._log_visual_action_intervention(goal, focus, "prepend_focus")
            return grounded

        replacement = self._visual_coordinate_replacement(actions[0], suggestions)
        if replacement:
            actions[0] = replacement["action"]
            grounded["actions"] = actions
            grounded["reasoning"] = self._append_reasoning(
                grounded.get("reasoning", ""),
                f"Visual grounding filled action coordinates: {replacement.get('reason')}",
            )
            self._log_visual_action_intervention(goal, replacement, "fill_coordinates")
            approach = self._visual_approach_for_action(actions[0], suggestions)
            if approach and not self._action_in_sequence(approach.get("action", {}), actions):
                grounded["actions"] = [approach["action"]] + actions
                grounded["status"] = "in_progress"
                grounded["reasoning"] = self._append_reasoning(
                    grounded.get("reasoning", ""),
                    f"Visual grounding inserted approach action: {approach.get('reason')}",
                )
                self._log_visual_action_intervention(goal, approach, "prepend_approach")
                return grounded
            focus = self._visual_focus_for_action(actions[0], suggestions)
            if focus and not self._action_in_sequence(focus.get("action", {}), actions):
                grounded["actions"] = [focus["action"]] + actions
                grounded["status"] = "in_progress"
                grounded["reasoning"] = self._append_reasoning(
                    grounded.get("reasoning", ""),
                    f"Visual grounding inserted focus action: {focus.get('reason')}",
                )
                self._log_visual_action_intervention(goal, focus, "prepend_focus")
        return grounded

    def _visual_action_suggestions(self, goal: str, observation: dict, limit: int = 4) -> list[dict]:
        advisor = getattr(self, "visual_action_advisor", None)
        if not advisor:
            return []
        try:
            return advisor.suggest(goal, observation or {}, limit=limit)
        except Exception as e:
            logger.warning(f"Visual action advisor failed: {e}")
            return []

    def _visual_coordinate_replacement(self, action: dict, suggestions: list[dict]) -> Optional[dict]:
        if not isinstance(action, dict) or action.get("type") != "dig":
            return None
        params = action.get("parameters", {}) if isinstance(action.get("parameters", {}), dict) else {}
        if all(key in params for key in ("x", "y", "z")):
            return None
        return next(
            (
                suggestion for suggestion in suggestions
                if suggestion.get("action", {}).get("type") == "dig"
                and all(key in suggestion.get("action", {}).get("parameters", {}) for key in ("x", "y", "z"))
            ),
            None,
        )

    def _visual_approach_for_action(self, action: dict, suggestions: list[dict]) -> Optional[dict]:
        if not isinstance(action, dict) or action.get("type") != "dig":
            return None
        action_pos = self._action_position_tuple(action)
        if not action_pos:
            return None
        for suggestion in suggestions:
            if suggestion.get("kind") != "resource_approach":
                continue
            resource = suggestion.get("target", {}).get("resource", {})
            resource_pos = {"parameters": resource.get("position", {})}
            if self._action_position_tuple(resource_pos) == action_pos:
                return suggestion
        return None

    def _visual_focus_for_action(self, action: dict, suggestions: list[dict]) -> Optional[dict]:
        if not isinstance(action, dict) or action.get("type") != "dig":
            return None
        action_pos = self._action_position_tuple(action)
        if not action_pos:
            return None
        for suggestion in suggestions:
            if suggestion.get("kind") != "resource_focus":
                continue
            if self._action_position_tuple(suggestion.get("action", {})) == action_pos:
                return suggestion
        return None

    def _action_position_tuple(self, action: dict) -> Optional[tuple]:
        params = action.get("parameters", {}) if isinstance(action.get("parameters", {}), dict) else {}
        if not all(key in params for key in ("x", "y", "z")):
            return None
        try:
            return tuple(round(float(params[key]), 3) for key in ("x", "y", "z"))
        except (TypeError, ValueError):
            return None

    def _append_reasoning(self, reasoning: str, addition: str) -> str:
        return (str(reasoning or "").rstrip() + ("\n" if reasoning else "") + addition).strip()

    def _action_in_sequence(self, action: dict, actions: list[dict]) -> bool:
        if not isinstance(action, dict):
            return False
        return any(existing == action for existing in actions if isinstance(existing, dict))

    def _log_visual_action_suggestions(self, goal: str, suggestions: list[dict]):
        payload = {"goal": goal, "suggestions": suggestions[:4]}
        if hasattr(self, "session_logger") and hasattr(self.session_logger, "log"):
            self.session_logger.log("visual_action_suggestion", payload)
        self._write_memory_episode("visual_action_suggestion", payload, source="visual_action")

    def _log_visual_action_intervention(self, goal: str, suggestion: dict, phase: str):
        payload = {"goal": goal, "phase": phase, "suggestion": suggestion}
        if hasattr(self, "session_logger") and hasattr(self.session_logger, "log"):
            self.session_logger.log("visual_action_intervention", payload)
        self._write_memory_episode("visual_action_intervention", payload, source="visual_action")

    def _reflect(self, observation: dict, action: dict, result: dict, goal: str) -> dict:
        protocol = str(getattr(self.config, "planner_protocol", "") or "")
        if protocol == "m2-fixed-v1":
            return {
                "analysis": "M2 action failure recorded for the next schema-validated replan",
                "suggestion": "replan",
                "should_retry": True,
            }
        if protocol == "m4-fixed-v1":
            return {
                "analysis": "M4 suppresses auxiliary failure LLM calls and replans on the next cycle",
                "suggestion": "replan",
                "should_retry": True,
                "suppressed": True,
                "reason": "m4_fixed_profile_immediate_replan",
                "episode_deadline_monotonic": getattr(self, "_episode_deadline_monotonic", None),
            }
        if not self._use_llm or not self.reflector:
            return {"analysis": "Rule planner - no reflection available", "suggestion": "retry", "should_retry": True}
        return self.reflector.analyze_failure(goal, action, result, observation)

    def _request_m2_replan(self, reason: str):
        if str(getattr(self.config, "planner_protocol", "") or "") != "m2-fixed-v1":
            return
        planner = getattr(self, "planner", None)
        if not hasattr(planner, "request_replan"):
            return
        planner.request_replan(reason)
        self.session_logger.log("m2_replan_requested", {
            "goal": str(self.current_goal or ""),
            "reason": str(reason or "action_failure")[:500],
        })

    def _recover_m4_invalid_plan(self, goal: str, plan: dict, cycle: int) -> bool:
        """Keep an M4 goal active after a recoverable planning failure."""
        if str(getattr(self.config, "planner_protocol", "") or "") != "m4-fixed-v1":
            return False
        if self._episode_deadline_reached():
            return False

        transport_failure = self._m4_planner_transport_failure(plan)
        if transport_failure:
            deadline = getattr(self, "_episode_deadline_monotonic", None)
            remaining_s = (
                max(0.0, float(deadline) - time.monotonic())
                if deadline is not None
                else None
            )
            payload = {
                "goal": str(goal or ""),
                "cycle": int(cycle),
                "planner_call_id": str(plan.get("planner_call_id") or ""),
                **transport_failure,
                "recovered": True,
                "goal_preserved": True,
                "resume_policy": "retry_planner_next_cycle_same_goal",
                "same_call_retry_count": 0,
                "episode_deadline_monotonic": deadline,
                "remaining_s": round(remaining_s, 3) if remaining_s is not None else None,
            }
            self.session_logger.log("m4_planner_transport_recovery", payload)
            self._write_memory_episode(
                "m4_planner_transport_recovery",
                payload,
                source="autonomous_planner",
            )
            return True

        validation = plan.get("schema_validation", {}) if isinstance(plan, dict) else {}
        issues = validation.get("issues", []) if isinstance(validation, dict) else []
        issues = [str(issue) for issue in issues if str(issue)] if isinstance(issues, list) else []
        planner = getattr(self, "planner", None)
        if "planning_actions_missing" in issues:
            if not hasattr(planner, "request_replan"):
                return False
            reason = "M4 planner output rejected: planning status requires an executable action"
            planner.request_replan(reason)
            payload = {
                "goal": str(goal or ""),
                "cycle": int(cycle),
                "planner_call_id": str(plan.get("planner_call_id") or ""),
                "status": str(plan.get("status") or ""),
                "rejected_status": str(validation.get("status") or ""),
                "schema_issues": issues,
                "action_count": int(validation.get("action_count", 0) or 0),
                "recovered": True,
                "resume_policy": "replan_next_cycle",
                "reason": reason,
            }
            self.session_logger.log("m4_planner_output_recovery", payload)
            self._write_memory_episode(
                "m4_planner_output_recovery",
                payload,
                source="autonomous_planner",
            )
            return True

        typed_rejection = self._m4_typed_schema_rejection(plan)
        if not typed_rejection or not hasattr(planner, "request_replan"):
            return False

        state = dict(getattr(self, "_m4_typed_schema_recovery_state", {}) or {})
        if state.get("goal") != str(goal or ""):
            state = {
                "goal": str(goal or ""),
                "goal_index": None,
                "attempt_count": 0,
                "pending_resume": False,
            }
        frontier = self._m4_task_frontier_snapshot()
        attempt_count = int(state.get("attempt_count", 0) or 0)
        if attempt_count >= M4_TYPED_SCHEMA_RECOVERY_LIMIT:
            payload = {
                "policy_id": M4_TYPED_SCHEMA_RECOVERY_POLICY_ID,
                "goal": str(goal or ""),
                "goal_index": state.get("goal_index"),
                "cycle": int(cycle),
                "planner_call_id": str(plan.get("planner_call_id") or ""),
                "root_plan_id": str(plan.get("root_plan_id") or ""),
                "schema_issues": list(typed_rejection["schema_issues"]),
                "recovered": False,
                "recovery_attempt_count": attempt_count,
                "maximum_recovery_attempts": M4_TYPED_SCHEMA_RECOVERY_LIMIT,
                "reason": "typed_schema_recovery_limit_exhausted",
                "invalid_task_accepted_count": 0,
                "invalid_action_executed_count": 0,
                "task_frontier": frontier,
            }
            self.session_logger.log("m4_planner_output_recovery_exhausted", payload)
            self._write_memory_episode(
                "m4_planner_output_recovery_exhausted",
                payload,
                source="autonomous_planner",
            )
            return False

        reason = (
            "M4 planner output rejected: typed subtask inventory count requires "
            "one bounded next-cycle replan"
        )
        planner.request_replan(reason)
        deadline = getattr(self, "_episode_deadline_monotonic", None)
        remaining_s = (
            max(0.0, float(deadline) - time.monotonic())
            if deadline is not None
            else None
        )
        state.update({
            "attempt_count": attempt_count + 1,
            "pending_resume": True,
            "rejected_cycle": int(cycle),
            "planner_call_id": str(plan.get("planner_call_id") or ""),
            "root_plan_id": str(plan.get("root_plan_id") or ""),
            "task_frontier_sha256": str(frontier["sha256"]),
        })
        self._m4_typed_schema_recovery_state = state
        payload = {
            "policy_id": M4_TYPED_SCHEMA_RECOVERY_POLICY_ID,
            "recovery_kind": "typed_subtask_inventory_count_rejection",
            "goal": str(goal or ""),
            "goal_index": state.get("goal_index"),
            "cycle": int(cycle),
            "planner_call_id": str(plan.get("planner_call_id") or ""),
            "root_plan_id": str(plan.get("root_plan_id") or ""),
            "parent_planner_call_id": str(plan.get("parent_planner_call_id") or ""),
            "plan_kind": str(plan.get("plan_kind") or ""),
            "schema_issues": list(typed_rejection["schema_issues"]),
            "subtask_count": typed_rejection["subtask_count"],
            "inventory_requirement_count": typed_rejection["inventory_requirement_count"],
            "normalized_requirement_count": typed_rejection["normalized_requirement_count"],
            "recovered": True,
            "goal_preserved": True,
            "task_frontier_preservation_pending": True,
            "recovery_attempt_count": attempt_count + 1,
            "maximum_recovery_attempts": M4_TYPED_SCHEMA_RECOVERY_LIMIT,
            "same_call_retry_count": 0,
            "resume_policy": "replan_next_cycle_same_goal_and_frontier",
            "invalid_task_accepted_count": 0,
            "invalid_action_executed_count": 0,
            "task_frontier": frontier,
            "reason": reason,
            "episode_deadline_monotonic": deadline,
            "remaining_s": round(remaining_s, 3) if remaining_s is not None else None,
        }
        self.session_logger.log("m4_planner_output_recovery", payload)
        self._write_memory_episode(
            "m4_planner_output_recovery",
            payload,
            source="autonomous_planner",
        )
        return True

    @staticmethod
    def _m4_typed_schema_rejection(plan: dict) -> dict:
        """Return evidence only for fail-closed M4 subtask inventory-count rejection."""
        if not isinstance(plan, dict) or str(plan.get("status") or "").lower() != "error":
            return {}
        actions = plan.get("actions")
        subtasks = plan.get("subtasks")
        if not isinstance(actions, list) or actions or not isinstance(subtasks, list) or subtasks:
            return {}

        validation = plan.get("schema_validation", {})
        if not isinstance(validation, dict) or validation.get("passed") is not False:
            return {}
        issues = validation.get("issues", [])
        if not isinstance(issues, list):
            return {}
        schema_issues = sorted({str(issue) for issue in issues if str(issue)})
        if not schema_issues or not all(
            M4_TYPED_SCHEMA_ISSUE_PATTERN.fullmatch(issue) for issue in schema_issues
        ):
            return {}

        grounding = validation.get("subtask_numeric_criteria_grounding", {})
        if not (
            isinstance(grounding, dict)
            and grounding.get("type") == "m4_subtask_numeric_criteria_grounding"
            and grounding.get("passed") is False
        ):
            return {}
        grounding_issues = grounding.get("issues", [])
        if not isinstance(grounding_issues, list):
            return {}
        if sorted({str(issue) for issue in grounding_issues if str(issue)}) != schema_issues:
            return {}

        evidence = plan.get("planner_evidence", {})
        planner_call_id = str(plan.get("planner_call_id") or "")
        root_plan_id = str(plan.get("root_plan_id") or "")
        parent_planner_call_id = str(plan.get("parent_planner_call_id") or "")
        plan_kind = str(plan.get("plan_kind") or "")
        if not (
            isinstance(evidence, dict)
            and evidence.get("protocol") == "m4-fixed-v1"
            and evidence.get("real_llm_call") is True
            and evidence.get("schema_valid") is False
            and not str(evidence.get("error") or "")
            and planner_call_id
            and str(evidence.get("call_id") or "") == planner_call_id
            and root_plan_id
            and str(evidence.get("root_plan_id") or "") == root_plan_id
            and str(evidence.get("parent_call_id") or "") == parent_planner_call_id
            and plan_kind in {"root", "continuation", "replan"}
            and str(evidence.get("plan_kind") or "") == plan_kind
        ):
            return {}
        evidence_validation = evidence.get("schema_validation", {})
        if not isinstance(evidence_validation, dict):
            return {}
        evidence_issues = evidence_validation.get("issues", [])
        if not isinstance(evidence_issues, list):
            return {}
        if (
            evidence_validation.get("passed") is not False
            or sorted({str(issue) for issue in evidence_issues if str(issue)}) != schema_issues
        ):
            return {}

        numeric_counts = {}
        for field in (
            "subtask_count",
            "inventory_requirement_count",
            "normalized_requirement_count",
        ):
            value = grounding.get(field)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                return {}
            numeric_counts[field] = value
        if not numeric_counts["subtask_count"] or not numeric_counts["inventory_requirement_count"]:
            return {}

        return {
            "schema_issues": schema_issues,
            **numeric_counts,
        }

    def _m4_task_frontier_snapshot(self) -> dict:
        task_system = getattr(self, "task_system", None)
        tasks = getattr(task_system, "tasks", {}) if task_system is not None else {}
        terminal = {
            TaskStatus.FAILED.value,
            TaskStatus.COMPLETED.value,
            TaskStatus.CANCELLED.value,
        }
        frontier = []
        status_counts: dict[str, int] = {}
        task_items = sorted(tasks.items()) if isinstance(tasks, dict) else []
        for task_id, task in task_items:
            task_status = getattr(task, "status", "")
            status = getattr(task_status, "value", str(task_status))
            if status in terminal:
                continue
            status_counts[status] = status_counts.get(status, 0) + 1
            frontier.append({
                "task_id": str(getattr(task, "id", task_id) or task_id),
                "status": status,
                "root_plan_id": str(getattr(task, "root_plan_id", "") or ""),
                "plan_node_id": str(getattr(task, "plan_node_id", "") or ""),
                "planner_call_id": str(getattr(task, "planner_call_id", "") or ""),
                "depends_on": sorted(str(item) for item in (getattr(task, "depends_on", []) or [])),
            })
        encoded = json.dumps(frontier, sort_keys=True, separators=(",", ":"))
        return {
            "task_count": len(frontier),
            "status_counts": dict(sorted(status_counts.items())),
            "sha256": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
        }

    def _verify_m4_typed_schema_recovery_resume(self, goal: str, cycle: int) -> bool:
        if str(getattr(self.config, "planner_protocol", "") or "") != "m4-fixed-v1":
            return True
        state = dict(getattr(self, "_m4_typed_schema_recovery_state", {}) or {})
        if not state.get("pending_resume"):
            return True

        frontier = self._m4_task_frontier_snapshot()
        same_goal = state.get("goal") == str(goal or "")
        frontier_preserved = state.get("task_frontier_sha256") == frontier["sha256"]
        recovered = bool(same_goal and frontier_preserved)
        payload = {
            "policy_id": M4_TYPED_SCHEMA_RECOVERY_POLICY_ID,
            "goal": str(goal or ""),
            "goal_index": state.get("goal_index"),
            "cycle": int(cycle),
            "rejected_cycle": state.get("rejected_cycle"),
            "planner_call_id": str(state.get("planner_call_id") or ""),
            "root_plan_id": str(state.get("root_plan_id") or ""),
            "same_goal": same_goal,
            "task_frontier_preserved": frontier_preserved,
            "recovered": recovered,
            "recovery_attempt_count": int(state.get("attempt_count", 0) or 0),
            "maximum_recovery_attempts": M4_TYPED_SCHEMA_RECOVERY_LIMIT,
            "resume_policy": "replan_next_cycle_same_goal_and_frontier",
            "task_frontier": frontier,
        }
        self.session_logger.log(
            "m4_planner_output_recovery_resume",
            payload,
            level="INFO" if recovered else "ERROR",
        )
        self._write_memory_episode(
            "m4_planner_output_recovery_resume",
            payload,
            source="autonomous_planner",
        )
        state.update({
            "pending_resume": False,
            "resume_cycle": int(cycle),
            "resume_verified": recovered,
        })
        self._m4_typed_schema_recovery_state = state
        return recovered

    @staticmethod
    def _m4_planner_transport_failure(plan: dict) -> dict:
        if not isinstance(plan, dict) or str(plan.get("status") or "").lower() != "error":
            return {}
        actions = plan.get("actions", [])
        if not isinstance(actions, list) or actions:
            return {}
        evidence = plan.get("planner_evidence", {})
        if not isinstance(evidence, dict):
            return {}
        if not (
            evidence.get("protocol") == "m4-fixed-v1"
            and evidence.get("real_llm_call") is False
            and evidence.get("schema_valid") is False
        ):
            return {}
        planner_call_id = str(plan.get("planner_call_id") or "")
        if not planner_call_id or str(evidence.get("call_id") or "") != planner_call_id:
            return {}
        transport = evidence.get("transport_evidence", {})
        if not isinstance(transport, dict):
            return {}
        attempts = transport.get("attempts", [])
        if not (
            transport.get("policy_id") == "single-attempt"
            and transport.get("attempt_count") == 1
            and transport.get("retry_count") == 0
            and isinstance(attempts, list)
            and len(attempts) == 1
            and isinstance(attempts[0], dict)
            and attempts[0].get("success") is False
        ):
            return {}
        attempt = attempts[0]
        error_type = str(attempt.get("error_type") or "")
        error_chain = attempt.get("error_chain", [])
        error_chain = (
            [str(name) for name in error_chain if str(name)]
            if isinstance(error_chain, list)
            else []
        )
        retryable_types = {
            "APIConnectionError",
            "APITimeoutError",
            "ConnectError",
            "ConnectionError",
            "ConnectionResetError",
            "ReadError",
            "ReadTimeout",
            "RemoteProtocolError",
            "SSLError",
            "SSLEOFError",
            "TimeoutError",
            "WriteError",
            "WriteTimeout",
        }
        if not ({error_type, *error_chain} & retryable_types):
            return {}
        error = str(evidence.get("error") or "")
        if not error or error.startswith("m4_"):
            return {}
        return {
            "error": error,
            "error_type": error_type,
            "error_chain": error_chain,
            "transport_policy_id": "single-attempt",
            "attempt_count": 1,
        }

    # ── Helpers ────────────────────────────────────────────────────────

    def _goal_is_verified(
        self,
        goal: str,
        observation: dict,
        context: dict = None,
        recent_actions: list[dict] = None,
    ) -> tuple[bool, object]:
        """Return whether observation proves the goal, logging decisive checks."""
        if self._episode_deadline_reached():
            return False, self._deadline_goal_verification(goal, context, "before_goal_verifier")
        if not getattr(getattr(self, "config", None), "enable_goal_verification", True):
            return False, None
        if not hasattr(self, "goal_verifier"):
            return False, None
        m2_task_id = str(getattr(self.config, "m2_task_id", "") or "")
        if m2_task_id:
            verification = self._m2_goal_verification(goal, m2_task_id)
            self._log_goal_verification(
                verification,
                {**(context or {}), "accepted": verification.achieved},
            )
        else:
            verification = self.goal_verifier.verify(goal, observation, recent_actions=recent_actions or [])
            if self._episode_deadline_reached():
                return False, self._deadline_goal_verification(goal, context, "after_goal_verifier")
            if verification.achieved:
                self._log_goal_verification(verification, {**(context or {}), "accepted": True})
        return verification.achieved, verification

    def _deadline_goal_verification(self, goal: str, context: dict = None, phase: str = ""):
        from singularity.core.goal_verifier import GoalVerification

        verification = GoalVerification(
            goal=goal,
            achieved=False,
            status="failed",
            confidence=1.0,
            missing=["episode deadline exhausted"],
            matched_rules=["m4:episode_deadline"],
        )
        self._log_goal_verification(
            verification,
            {**(context or {}), "accepted": False, "deadline_suppressed": True, "phase": phase},
        )
        return verification

    def _m2_goal_verification(self, goal: str, task_id: str):
        from singularity.core.goal_verifier import GoalVerification
        from singularity.evaluation.m2_protocol import verify_task_outcome

        verify = getattr(getattr(self, "bot", None), "verify_benchmark", None)
        terminal = verify(task_id) if callable(verify) else {
            "success": False,
            "error": "bridge does not expose benchmark_verify",
        }
        if not isinstance(terminal, dict) or terminal.get("success") is not True:
            error = str(terminal.get("error") or "M2 terminal evidence unavailable") if isinstance(terminal, dict) else "M2 terminal evidence is not an object"
            return GoalVerification(
                goal=goal,
                achieved=False,
                status="failed",
                confidence=1.0,
                missing=[error],
                matched_rules=["m2:machine_verifier"],
                critic={"m2_machine_verification": {"passed": False, "issues": [error]}},
            )
        action_events = [
            event
            for event in (getattr(getattr(self, "session_logger", None), "events", []) or [])
            if isinstance(event, dict) and event.get("type") == "action"
        ]
        report = verify_task_outcome(
            task_id,
            setup_evidence=dict(getattr(self, "_m2_setup_evidence", {}) or {}),
            terminal_evidence=terminal,
            action_events=action_events,
        )
        achieved = report.get("passed") is True
        return GoalVerification(
            goal=goal,
            achieved=achieved,
            status="achieved" if achieved else "failed",
            confidence=1.0,
            evidence=[f"{task_id} machine outcome verified"] if achieved else [],
            missing=list(report.get("issues", [])),
            matched_rules=["m2:machine_verifier"],
            inventory_delta=dict(report.get("inventory_delta", {})),
            critic={"m2_machine_verification": report},
        )

    def _accept_plan_completion(
        self,
        goal: str,
        observation: dict,
        plan: dict,
        context: dict = None,
        recent_actions: list[dict] = None,
    ) -> tuple[bool, object]:
        """Gate planner-reported completion through deterministic verification."""
        if self._episode_deadline_reached():
            return False, self._deadline_goal_verification(goal, context, "before_completion_verifier")
        if str(getattr(self.config, "m2_task_id", "") or ""):
            return self._goal_is_verified(
                goal,
                observation,
                context={
                    **(context or {}),
                    "planner_status": plan.get("status"),
                    "planner_reasoning": plan.get("reasoning", "")[:300],
                },
                recent_actions=recent_actions,
            )
        if not getattr(getattr(self, "config", None), "enable_goal_verification", True):
            return True, None
        if not hasattr(self, "goal_verifier"):
            return True, None
        verification = self.goal_verifier.verify(goal, observation, recent_actions=recent_actions or [])
        if self._episode_deadline_reached():
            return False, self._deadline_goal_verification(goal, context, "after_completion_verifier")
        accepted = verification.achieved or verification.status == "unknown"
        payload = {
            **(context or {}),
            "accepted": accepted,
            "planner_status": plan.get("status"),
            "planner_reasoning": plan.get("reasoning", "")[:300],
        }
        critic_matched = "goal_critic" in getattr(verification, "matched_rules", [])
        if verification.status == "unknown" and accepted:
            payload["acceptance_reason"] = "no_deterministic_rule_matched"
        elif not accepted:
            payload["acceptance_reason"] = "critic_evidence_missing" if critic_matched else "deterministic_evidence_missing"
        else:
            payload["acceptance_reason"] = "critic_evidence_satisfied" if critic_matched else "deterministic_evidence_satisfied"
        self._log_goal_verification(verification, payload)
        return accepted, verification

    def _log_goal_verification(self, verification, context: dict = None):
        """Record self-verification outcomes for debugging and benchmark analysis."""
        payload = verification.to_dict()
        payload["context"] = context or {}
        self._write_memory_episode("goal_verification", payload, source="goal_verifier")
        if hasattr(self, "session_logger") and hasattr(self.session_logger, "log"):
            self.session_logger.log("goal_verification", payload)

    def _record_skill_usage(self, action: dict, success: bool, result: dict = None):
        """Record skill usage for actions that map to known skills."""
        skill_context = action.get("skill_context", {}) if isinstance(action.get("skill_context", {}), dict) else {}
        if skill_context.get("skill_id"):
            active = self._active_skill_execution
            controlled_fault = bool(skill_context.get("controlled_failure_only"))
            if controlled_fault:
                active["controlled_failure_only"] = True
                active["controlled_fault_profile"] = str(
                    skill_context.get("controlled_fault_profile") or ""
                )
                active["counts_toward_skill_lifecycle"] = False
            active["executed_count"] = int(active.get("executed_count", 0) or 0) + 1
            if not success:
                active["failed_action_count"] = int(active.get("failed_action_count", 0) or 0) + 1
                transition = "{phase}:{index}:{action}".format(
                    phase=skill_context.get("phase_id", "unknown"),
                    index=skill_context.get("template_action_index", 0),
                    action=action.get("type", "unknown"),
                )
                if not active.get("first_failed_transition"):
                    active["first_failed_transition"] = transition
                active["fallback_reason"] = "learned_skill_action_failed"
                failure_type = (
                    "controlled_fault"
                    if controlled_fault
                    else self._classify_skill_action_failure(action, result or {})
                )
                active["failure_type"] = failure_type
                goal_key = str(skill_context.get("goal_fingerprint") or "")
                if goal_key:
                    self._skill_fallback_goals.add(goal_key)
                self.session_logger.log("skill_fallback", {
                    "goal": skill_context.get("goal", ""),
                    "skill_id": skill_context.get("skill_id"),
                    "version": skill_context.get("version", ""),
                    "mode": skill_context.get("mode", ""),
                    "reason": "learned_skill_action_failed",
                    "failure_type": failure_type,
                    "first_failed_transition": transition,
                    "before_execution": False,
                    "controlled_failure_only": controlled_fault,
                    "counts_toward_skill_lifecycle": not controlled_fault,
                })
            self.session_logger.log("skill_action_result", {
                "goal": skill_context.get("goal", ""),
                "skill_id": skill_context.get("skill_id"),
                "skill_name": skill_context.get("skill_name", ""),
                "version": skill_context.get("version", ""),
                "mode": skill_context.get("mode", ""),
                "phase_id": skill_context.get("phase_id", ""),
                "template_action_index": skill_context.get("template_action_index", 0),
                "action_type": action.get("type", ""),
                "success": bool(success),
                "failure_type": "" if success else (
                    "controlled_fault"
                    if controlled_fault
                    else self._classify_skill_action_failure(action, result or {})
                ),
                "attributed": not controlled_fault,
                "controlled_failure_only": controlled_fault,
                "counts_toward_skill_lifecycle": not controlled_fault,
            })
        action_type = action.get("type", "")
        skill_mapping = {
            "dig": "dig_block",
            "craft": "craft_item",
            "move_to": "move_to",
            "attack": "attack_entity",
            "place": "place_block",
            "equip": None,
            "use_item": None,
            "look_at": None,
            "chat": None,
            "wait": None,
        }
        skill_name = skill_mapping.get(action_type)
        if skill_name:
            self.skill_library.record_use(skill_name, success)

    def _classify_skill_action_failure(self, action: dict, result: dict) -> str:
        verification = result.get("action_verification", {}) if isinstance(result, dict) else {}
        if isinstance(verification, dict) and str(verification.get("status") or "").lower() == "reject":
            return "skill_error"
        error = str(result.get("error") or result.get("reason") or "").lower() if isinstance(result, dict) else ""
        if any(term in error for term in ("connection", "bridge", "socket", "timed out", "timeout")):
            return "backend_execution_error"
        if (
            action.get("type") in {"move_to", "walk_to"}
            and isinstance(result, dict)
            and result.get("requires_replan") is True
        ):
            return "environment_change"
        if any(term in error for term in ("not found", "no block", "unreachable", "out of range")):
            return "environment_change"
        return "skill_error"

    def _attempt_failure_correction(
        self,
        failed_action: dict,
        failed_result: dict,
        observation: dict,
        goal: str,
        context: dict = None,
    ) -> tuple[bool, dict]:
        """Run an approved correction sequence for a failed action when one matches."""
        if hasattr(self, "config") and not getattr(self.config, "enable_policy_skills", True):
            return False, observation
        match = self.skill_library.find_failure_correction(failed_action, failed_result, observation)
        if not match:
            return False, observation

        skill, payload = match
        sequence = payload.get("correction_sequence", [])
        if not sequence:
            return False, observation

        self._write_memory_episode("failure_correction_selected", {
            "skill": skill.name,
            "failed_action": failed_action,
            "failed_error": failed_result.get("error"),
            "goal": goal,
        }, source="failure_correction")
        self._log_policy_intervention("selected", {
            "kind": "failure_correction",
            "skill": skill.name,
            "failed_action": failed_action,
            "failed_error": failed_result.get("error"),
            "goal": goal,
        })

        current_observation = observation
        completed_steps = 0
        for idx, correction_action in enumerate(sequence):
            if not isinstance(correction_action, dict):
                continue
            if self._episode_deadline_reached():
                self._log_policy_intervention("failed", {
                    "kind": "failure_correction",
                    "skill": skill.name,
                    "reason": "episode_deadline",
                    "step": idx,
                })
                return False, current_observation
            interrupted, current_observation = self._handle_runtime_interrupt(
                current_observation,
                goal,
                {**(context or {}), "correction_skill": skill.name, "correction_index": idx},
            )
            if interrupted:
                self.skill_library.record_use(skill.name, False)
                self._record_failure_correction_skill_memory(
                    skill,
                    goal,
                    failed_action,
                    failed_result,
                    outcome="failure",
                    note=f"Correction interrupted before step {idx} while handling {self._action_label(failed_action)}.",
                    step=idx,
                    context=context,
                )
                self._log_policy_intervention("failed", {
                    "kind": "failure_correction",
                    "skill": skill.name,
                    "reason": "runtime_interrupt",
                    "step": idx,
                })
                return False, current_observation

            before_correction_observation = current_observation
            correction_action, action_selection = self._select_action_for_execution(
                correction_action,
                current_observation,
                goal,
                {**(context or {}), "mode": "failure_correction", "correction_skill": skill.name, "correction_index": idx},
            )
            action_verification, rejected_result = self._verify_action_for_execution(
                correction_action,
                current_observation,
                goal,
                {**(context or {}), "mode": "failure_correction", "correction_skill": skill.name, "correction_index": idx},
            )
            if rejected_result:
                result = rejected_result
            else:
                result = self.action_controller.execute(correction_action, current_observation)
                if action_verification:
                    result["action_verification"] = action_verification
            if action_selection:
                result["action_candidate_selection"] = action_selection
            result["correction_skill_attribution"] = {
                "skill_id": getattr(skill, "skill_id", "") or skill.name,
                "skill_name": skill.name,
                "version": getattr(skill, "version", ""),
                "step": idx,
            }
            self._record_action_value(correction_action, result, goal, action_verification)
            self._write_memory_episode("failure_correction_action", {
                "skill": skill.name,
                "action": correction_action,
                "result": result,
            }, source="failure_correction")
            self._log_policy_intervention("action", {
                "kind": "failure_correction",
                "skill": skill.name,
                "step": idx,
                "action": correction_action,
                "result": result,
            })
            current_observation = self._apply_action_feedback(
                correction_action,
                result,
                current_observation,
                {**(context or {}), "goal": goal, "correction_skill": skill.name, "correction_index": idx},
            )
            self._log_action_event(
                correction_action,
                result,
                pre_observation=before_correction_observation,
                post_observation=current_observation,
                context={
                    **(context or {}),
                    "goal": goal,
                    "mode": "failure_correction",
                    "correction_skill": skill.name,
                    "correction_index": idx,
                },
            )

            self._record_skill_usage(correction_action, bool(result.get("success")), result)
            if not result.get("success"):
                self.skill_library.record_use(skill.name, False)
                self._record_failure_correction_skill_memory(
                    skill,
                    goal,
                    failed_action,
                    failed_result,
                    outcome="failure",
                    note=(
                        f"Correction failed at step {idx} on {self._action_label(correction_action)} "
                        f"after {self._action_label(failed_action)} failed."
                    ),
                    step=idx,
                    correction_action=correction_action,
                    correction_result=result,
                    context=context,
                )
                self._write_memory_episode("failure_correction_failed", {
                    "skill": skill.name,
                    "failed_step": idx,
                    "error": result.get("error"),
                }, source="failure_correction")
                self._log_policy_intervention("failed", {
                    "kind": "failure_correction",
                    "skill": skill.name,
                    "step": idx,
                    "error": result.get("error"),
                })
                return False, current_observation
            completed_steps += 1
            goal_reached, _ = self._goal_is_verified(
                goal,
                current_observation,
                {
                    **(context or {}),
                    "mode": "failure_correction",
                    "correction_skill": skill.name,
                    "correction_index": idx,
                    "phase": "post_action",
                },
                recent_actions=[{
                    "action": correction_action,
                    "result": result,
                    "before_observation": before_correction_observation,
                    "after_observation": current_observation,
                }],
            )
            if goal_reached:
                break

        self.skill_library.record_use(skill.name, True)
        self._record_failure_correction_skill_memory(
            skill,
            goal,
            failed_action,
            failed_result,
            outcome="success",
            note=(
                f"Correction completed {completed_steps} steps after "
                f"{self._action_label(failed_action)} failed."
            ),
            step=completed_steps,
            correction_action=sequence[max(0, completed_steps - 1)] if sequence and completed_steps else {},
            correction_result={"success": True},
            context=context,
        )
        self._write_memory_episode("failure_correction_completed", {
            "skill": skill.name,
            "steps": completed_steps,
            "goal": goal,
        }, source="failure_correction")
        self._log_policy_intervention("completed", {
            "kind": "failure_correction",
            "skill": skill.name,
            "steps": completed_steps,
            "goal": goal,
        })
        return True, current_observation

    def _record_failure_correction_skill_memory(
        self,
        skill,
        goal: str,
        failed_action: dict,
        failed_result: dict,
        outcome: str,
        note: str,
        step: int = 0,
        correction_action: dict = None,
        correction_result: dict = None,
        context: dict = None,
    ):
        """Attach runtime feedback to the correction skill that was actually used."""
        if not hasattr(self, "skill_library") or not hasattr(self.skill_library, "record_skill_memory"):
            return
        gate = getattr(skill, "gate", {}) if skill else {}
        transfer_gate = gate.get("transfer", {}) if isinstance(gate, dict) and isinstance(gate.get("transfer", {}), dict) else {}
        failed_result = failed_result if isinstance(failed_result, dict) else {}
        correction_result = correction_result if isinstance(correction_result, dict) else {}
        correction_action = correction_action if isinstance(correction_action, dict) else {}
        task_family = self.skill_library.infer_task_family(goal, failed_action)
        memory_type = "failure_correction" if outcome == "success" else "anti_pattern"
        confidence = 0.85 if outcome == "success" else 0.7
        evidence = {
            "goal": goal,
            "failed_action": failed_action,
            "failed_error": failed_result.get("error"),
            "correction_action": correction_action,
            "correction_error": correction_result.get("error"),
            "step": step,
            "context": context or {},
        }
        try:
            self.skill_library.record_skill_memory(
                skill.name,
                note=note,
                memory_type=memory_type,
                outcome=outcome,
                task_family=task_family,
                source="runtime_failure_correction",
                confidence=confidence,
                tags=self._skill_memory_tags(goal, failed_action, correction_action),
                transfer_gate=transfer_gate,
                evidence=evidence,
            )
        except Exception as exc:
            logger.warning(f"Could not record skill memory for {getattr(skill, 'name', 'unknown')}: {type(exc).__name__}")

    def _skill_memory_tags(self, goal: str, *actions: dict) -> list[str]:
        tags = []
        for token in str(goal or "").lower().replace("_", " ").split():
            cleaned = "".join(ch for ch in token if ch.isalnum())
            if len(cleaned) > 2 and cleaned not in tags:
                tags.append(cleaned)
        for action in actions:
            action = action if isinstance(action, dict) else {}
            action_type = str(action.get("type", "")).strip()
            if action_type and action_type not in tags:
                tags.append(action_type)
            params = action.get("parameters", {}) if isinstance(action.get("parameters", {}), dict) else {}
            for key in ("item", "block", "entity", "target"):
                value = str(params.get(key, "")).strip()
                if value and value not in tags:
                    tags.append(value)
        return tags[:12]

    def _action_label(self, action: dict) -> str:
        action = action if isinstance(action, dict) else {}
        params = action.get("parameters", {}) if isinstance(action.get("parameters", {}), dict) else {}
        subject = params.get("item") or params.get("block") or params.get("entity") or params.get("target")
        return f"{action.get('type', 'action')}:{subject}" if subject else str(action.get("type", "action"))

    def _log_policy_intervention(self, phase: str, payload: dict):
        """Record online use of reviewed causal/correction skills for benchmark metrics."""
        if not hasattr(self, "session_logger") or not hasattr(self.session_logger, "log"):
            return
        event_type = "policy_hint" if phase == "hint" else "policy_intervention"
        data = {"phase": phase}
        data.update(payload or {})
        self.session_logger.log(event_type, data)

    def _accept_planned_tasks(self):
        """Move newly proposed planner tasks into the scheduler queue."""
        for task in self.task_system.tasks.values():
            if task.status == TaskStatus.PROPOSED:
                self.task_system.update_task(task.id, status=TaskStatus.ACCEPTED)
        self._flush_task_state_transitions({"source": "planner_acceptance"})

    def _flush_task_state_transitions(self, context: dict = None):
        task_system = getattr(self, "task_system", None)
        if not task_system or not hasattr(task_system, "drain_transition_events"):
            return
        for transition in task_system.drain_transition_events():
            payload = dict(transition)
            payload["context"] = dict(context or {})
            if hasattr(self, "session_logger") and hasattr(self.session_logger, "log"):
                self.session_logger.log("task_state_transition", payload)

    def _complete_verified_m2_task_paths(self, goal: str, verification, context: dict = None) -> list[str]:
        """Close auditable M2 task paths only after the machine verifier accepts the goal."""
        if str(getattr(getattr(self, "config", None), "planner_protocol", "") or "") != "m2-fixed-v1":
            return []
        evidence = verification.to_dict() if hasattr(verification, "to_dict") else {}
        if "m2:machine_verifier" not in (evidence.get("matched_rules") or []):
            return []
        root_plan_id = str(getattr(getattr(self, "planner", None), "_active_root_plan_id", "") or "")
        task_system = getattr(self, "task_system", None)
        if not root_plan_id or not task_system or not hasattr(task_system, "complete_verified_plan"):
            return []
        completed = task_system.complete_verified_plan(
            root_plan_id,
            {"goal": goal, "verification": evidence},
        )
        self._flush_task_state_transitions({
            "source": "machine_goal_verifier",
            **(context or {}),
        })
        return completed

    def _ingest_plan_subtasks(self, plan: dict, goal: str = "", source: str = "planner") -> dict:
        """Create scheduler tasks from deterministic or cached plan subtasks."""
        if not isinstance(plan, dict) or not hasattr(self, "task_system") or self.task_system is None:
            return {"created_count": 0, "reused_count": 0}
        subtasks = plan.get("subtasks", [])
        if not isinstance(subtasks, list) or not subtasks:
            return {"created_count": 0, "reused_count": 0}

        title_to_id = {}
        pending_dependencies: list[tuple[str, list[str]]] = []
        created = []
        reused = []
        for st in subtasks:
            if not isinstance(st, dict):
                continue
            title = str(st.get("title") or "unnamed").strip() or "unnamed"
            existing = self._find_existing_plan_task(title)
            if existing:
                task = existing
                reused.append(task.id)
            else:
                task = self.task_system.create_task(
                    title=title,
                    task_type=st.get("type", "general"),
                    success_criteria=st.get("success_criteria", {}) if isinstance(st.get("success_criteria", {}), dict) else {},
                    failure_criteria=st.get("failure_criteria", {}) if isinstance(st.get("failure_criteria", {}), dict) else {},
                    preconditions=st.get("preconditions", {}) if isinstance(st.get("preconditions", {}), dict) else {},
                    priority=self._safe_plan_priority(st.get("priority", 3)),
                    assigned_skill=st.get("assigned_skill"),
                    tags=list(st.get("tags", []) or [])[:8] if isinstance(st.get("tags", []), list) else [],
                    opportunity_triggers=(
                        list(st.get("opportunity_triggers", []) or [])[:8]
                        if isinstance(st.get("opportunity_triggers", []), list)
                        else []
                    ),
                    deadline=self._deadline_from_plan_seconds(st.get("deadline_seconds")),
                    rationale=str(st.get("rationale") or "")[:300],
                )
                created.append(task.id)
            title_to_id[title.lower()] = task.id
            dependencies = st.get("depends_on", [])
            if isinstance(dependencies, list) and dependencies:
                pending_dependencies.append((task.id, dependencies))

        for task_id, dependencies in pending_dependencies:
            task = self.task_system.tasks.get(task_id)
            if not task:
                continue
            task.depends_on = [
                title_to_id[dep.lower()]
                for dep in dependencies
                if isinstance(dep, str) and dep.lower() in title_to_id
            ]

        report = {
            "goal": goal,
            "source": source,
            "created_count": len(created),
            "reused_count": len(reused),
            "task_ids": created + reused,
        }
        if hasattr(self, "session_logger") and hasattr(self.session_logger, "log"):
            self.session_logger.log("planner_subtasks_ingested", report)
        return report

    def _find_existing_plan_task(self, title: str):
        title_key = str(title or "").strip().lower()
        if not title_key or not hasattr(self, "task_system") or self.task_system is None:
            return None
        terminal = {TaskStatus.COMPLETED, TaskStatus.CANCELLED, TaskStatus.FAILED}
        for task in self.task_system.tasks.values():
            if task.title.strip().lower() == title_key and task.status not in terminal:
                return task
        return None

    def _task_readiness_recovery_goal(self, observation: dict, fallback_goal: str = "") -> str:
        """Turn blocked task readiness evidence into a concrete prerequisite goal."""
        if not getattr(getattr(self, "config", None), "enable_task_readiness_recovery", True):
            return ""
        task_system = getattr(self, "task_system", None)
        if not task_system or not hasattr(task_system, "task_readiness_report"):
            return ""
        try:
            report = task_system.task_readiness_report(observation or {})
        except Exception as e:
            logger.warning(f"Task readiness recovery failed: {e}")
            return ""
        blocked = [
            task for task in report.get("tasks", [])
            if isinstance(task, dict) and not task.get("ready")
        ]
        if not blocked:
            return ""
        for task in blocked:
            recovery = self._recovery_goal_for_blocked_task(task, observation or {})
            if not recovery:
                continue
            blocked_task = task_system.tasks.get(str(task.get("id") or ""))
            requirement = (
                recovery.get("m4_requirement", {})
                if isinstance(recovery.get("m4_requirement", {}), dict)
                else {}
            )
            fingerprint = str(requirement.get("requirement_fingerprint") or "")
            if fingerprint:
                self._ensure_m4_readiness_recovery_runtime_state()
                blocked_task_id = str(task.get("id") or "")
                completed_binding = next(
                    (
                        binding
                        for binding in self._m4_readiness_recovery_bindings.values()
                        if binding.get("requirement_fingerprint") == fingerprint
                        and binding.get("root_status") == "completed"
                        and blocked_task_id in {
                            str(task_id)
                            for task_id in binding.get("stale_sibling_candidate_ids", [])
                            if task_id
                        }
                    ),
                    {},
                )
                if completed_binding:
                    if completed_binding:
                        proof = self._m4_requirement_inventory_proof(requirement, observation or {})
                        stale = self._sweep_m4_readiness_recovery_siblings(completed_binding, proof)
                        if stale:
                            self._flush_task_state_transitions({
                                "source": "m4_readiness_recovery_recreation_suppressed",
                                "goal": fallback_goal,
                                "cycle": 0,
                            })
                    payload = {
                        "fallback": fallback_goal,
                        "selected": "",
                        "blocked_task_id": task.get("id"),
                        "blocked_task_title": task.get("title"),
                        "reason": recovery.get("reason"),
                        "missing": recovery.get("missing"),
                        "created_task": False,
                        "requirement_fingerprint": fingerprint,
                        "completion_propagated": True,
                        "recreation_suppressed": True,
                    }
                    if hasattr(getattr(self, "session_logger", None), "log"):
                        self.session_logger.log("task_readiness_recovery_goal", payload)
                    return ""
            if recovery.get("create_task", True):
                recovery_task, created_task = self._ensure_readiness_recovery_task(recovery, task, observation or {})
            else:
                recovery_task, created_task = None, False
            goal = recovery_task.title if recovery_task else recovery.get("goal", "")
            binding = {}
            root_completed = False
            if recovery_task is not None and blocked_task is not None and fingerprint:
                binding = self._bind_m4_readiness_recovery_goal(
                    recovery_task,
                    blocked_task,
                    requirement,
                )
                self._reconcile_m4_satisfied_tasks(
                    observation or {},
                    goal,
                    0,
                    source="readiness_recovery_creation",
                )
                root_completed = self._m4_readiness_recovery_goal_machine_completed(
                    goal,
                    str(binding.get("root_id") or ""),
                )
            payload = {
                "fallback": fallback_goal,
                "selected": goal,
                "blocked_task_id": task.get("id"),
                "blocked_task_title": task.get("title"),
                "reason": recovery.get("reason"),
                "missing": recovery.get("missing"),
                "created_task": created_task,
                "child_id": str(getattr(recovery_task, "id", "") or ""),
                "root_id": str(binding.get("root_id") or ""),
                "requirement_fingerprint": fingerprint,
                "inventory_proof": (
                    self._m4_requirement_inventory_proof(requirement, observation or {})
                    if requirement
                    else {}
                ),
                "completion_propagated": root_completed,
            }
            if hasattr(self, "session_logger") and hasattr(self.session_logger, "log"):
                self.session_logger.log("task_readiness_recovery_goal", payload)
            if hasattr(self, "memory"):
                self._write_memory_episode("task_readiness_recovery_goal", payload, source="task_readiness")
            if root_completed:
                self._m4_active_readiness_recovery_root_id = ""
                return ""
            return goal
        return ""

    def _recovery_goal_for_blocked_task(self, task_report: dict, observation: dict) -> dict:
        dependencies = task_report.get("missing_dependencies", [])
        if isinstance(dependencies, list) and dependencies:
            dep = next((item for item in dependencies if isinstance(item, dict)), {})
            dep_title = str(dep.get("title") or dep.get("id") or "").strip()
            if dep_title:
                task_system = getattr(self, "task_system", None)
                dependency_task = (
                    task_system.tasks.get(str(dep.get("id") or ""))
                    if task_system is not None
                    else None
                )
                dependency_status = str(dep.get("status") or "")
                if dependency_task is not None:
                    dependency_status = dependency_task.status.value
                if dependency_status in {
                    TaskStatus.FAILED.value,
                    TaskStatus.BLOCKED.value,
                }:
                    return self._failed_dependency_recovery_goal(
                        dependency_task,
                        task_report,
                        observation,
                    )
                return {
                    "goal": dep_title,
                    "reason": "missing_dependency",
                    "missing": {"dependency": dep_title},
                    "success_criteria": {},
                    "opportunity_triggers": [],
                    "create_task": False,
                }
        missing = task_report.get("missing_preconditions", {}) if isinstance(task_report.get("missing_preconditions", {}), dict) else {}
        inventory = missing.get("inventory", {}) if isinstance(missing.get("inventory", {}), dict) else {}
        if inventory:
            item, amount = sorted(inventory.items())[0]
            return self._inventory_recovery_goal(str(item), amount, task_report, observation)
        nearby = missing.get("nearby_block_present", [])
        if isinstance(nearby, list) and nearby:
            block = str(nearby[0])
            return {
                "goal": f"Explore frontier and inspect {block} for {task_report.get('title', 'blocked task')}",
                "reason": "missing_nearby_block",
                "missing": {"nearby_block_present": [block]},
                "success_criteria": {"observed": block},
                "opportunity_triggers": [block],
            }
        flags = missing.get("flags", []) if isinstance(missing.get("flags", []), list) else []
        if flags:
            return {}
        return {}

    def _failed_dependency_recovery_goal(
        self,
        dependency_task,
        blocked_task_report: dict,
        observation: dict,
    ) -> dict:
        if (
            str(getattr(getattr(self, "config", None), "planner_protocol", "") or "")
            != "m4-fixed-v1"
        ):
            return {}
        task_system = getattr(self, "task_system", None)
        if (
            task_system is None
            or dependency_task is None
            or not hasattr(task_system, "machine_state_reconciliation_requirement")
        ):
            return {}
        requirement = task_system.machine_state_reconciliation_requirement(
            dependency_task.id,
            inventory_families=M4_MACHINE_STATE_INVENTORY_FAMILIES,
        )
        if not requirement:
            return {}
        proof = self._m4_requirement_inventory_proof(requirement, observation or {})
        if proof.get("satisfied") is True:
            return {}
        required_count = int(requirement["required_count"])
        observed_count = self._m4_inventory_count(proof.get("observed_count"))
        missing_count = max(1, required_count - observed_count)
        item = str(requirement["canonical_item"])
        title = str(dependency_task.title or dependency_task.id)
        goal = f"Recover {title}: acquire {missing_count} {item}"
        kb = self._knowledge_base()
        if kb is not None:
            try:
                if kb.get_recipe(item):
                    goal = f"Recover {title}: craft {item}"
            except Exception as e:
                logger.warning(f"Knowledge-backed failed dependency recovery failed for {item}: {e}")
        blocked_task = task_system.tasks.get(str(blocked_task_report.get("id") or ""))
        root_plan_id = str(
            dependency_task.root_plan_id
            or getattr(blocked_task, "root_plan_id", "")
            or ""
        )
        planner_call_id = str(
            dependency_task.planner_call_id
            or getattr(blocked_task, "planner_call_id", "")
            or ""
        )
        return {
            "goal": goal,
            "reason": "failed_dependency_machine_state_unmet",
            "missing": {"inventory": {item: missing_count}},
            "success_criteria": copy.deepcopy(dependency_task.success_criteria),
            "opportunity_triggers": list(requirement.get("family_members", [item]))[:8],
            "m4_requirement": copy.deepcopy(requirement),
            "failed_dependency_id": str(dependency_task.id),
            "failed_dependency_title": title,
            "failed_dependency_status": dependency_task.status.value,
            "parent_task_id": str(getattr(blocked_task, "id", "") or ""),
            "root_plan_id": root_plan_id,
            "planner_call_id": planner_call_id,
            "attempt_budget": M4_FAILED_DEPENDENCY_RECOVERY_ATTEMPT_BUDGET,
        }

    def _inventory_recovery_goal(self, item: str, amount, task_report: dict, observation: dict) -> dict:
        amount_int = max(1, self._small_int(amount or 1))
        target_title = str(task_report.get("title") or "blocked task")
        kb = self._knowledge_base()
        goal = f"Acquire {amount_int} {item} for {target_title}"
        triggers = [item]
        if kb:
            try:
                recipe = kb.get_recipe(item)
                if recipe:
                    goal = f"Craft {item} for {target_title}"
                else:
                    sources = kb.source_blocks_for_resource(item)
                    source = next((str(value) for value in sources if value), "")
                    if source and source != item:
                        goal = f"Mine {source} to obtain {item} for {target_title}"
                        triggers = [source, item]
            except Exception as e:
                logger.warning(f"Knowledge-backed recovery goal failed for {item}: {e}")
        inventory = observation.get("inventory", {}) if isinstance(observation.get("inventory", {}), dict) else {}
        target_count = self._small_int(inventory.get(item, 0)) + amount_int
        consumer_task = None
        task_system = getattr(self, "task_system", None)
        if task_system is not None:
            consumer_task = task_system.tasks.get(str(task_report.get("id") or ""))
        requirement = {}
        if (
            str(getattr(getattr(self, "config", None), "planner_protocol", "") or "")
            == "m4-fixed-v1"
            and consumer_task is not None
        ):
            preconditions = consumer_task.preconditions if isinstance(consumer_task.preconditions, dict) else {}
            required_inventory = preconditions.get("inventory", {})
            required_inventory = required_inventory if isinstance(required_inventory, dict) else {}
            canonical_required = self._m4_inventory_count(required_inventory.get(item, target_count))
            requirement = self._m4_readiness_recovery_requirement(
                item,
                canonical_required or target_count,
                consumer_task,
            )
            if requirement:
                target_count = int(requirement["required_count"])
        return {
            "goal": goal,
            "reason": "missing_inventory",
            "missing": {"inventory": {item: amount_int}},
            "success_criteria": {"inventory": {item: target_count}},
            "opportunity_triggers": triggers,
            "m4_requirement": requirement,
        }

    def _ensure_readiness_recovery_task(self, recovery: dict, blocked_task: dict, observation: dict):
        goal = str(recovery.get("goal") or "").strip()
        if not goal or not hasattr(self, "task_system") or self.task_system is None:
            return None, False
        requirement = (
            recovery.get("m4_requirement", {})
            if isinstance(recovery.get("m4_requirement", {}), dict)
            else {}
        )
        fingerprint = str(requirement.get("requirement_fingerprint") or "")
        if fingerprint:
            for task in self.task_system.tasks.values():
                metadata = task.metadata if isinstance(getattr(task, "metadata", {}), dict) else {}
                existing_requirement = metadata.get("m4_readiness_recovery_requirement", {})
                if (
                    isinstance(existing_requirement, dict)
                    and existing_requirement.get("requirement_fingerprint") == fingerprint
                    and task.status in {TaskStatus.ACCEPTED, TaskStatus.ACTIVE}
                ):
                    return task, False
        if not fingerprint:
            existing = self._find_existing_plan_task(goal)
            if existing:
                return existing, False
        priority = max(0, self._safe_plan_priority(blocked_task.get("priority", 3)) - 1)
        tags = ["readiness_recovery", str(recovery.get("reason") or "precondition")]
        if requirement.get("inventory_semantics") == "family":
            tags.append("m4_inventory_family:logs")
        elif requirement.get("canonical_item"):
            tags.append(f"m4_exact_item:{requirement['canonical_item']}")
        failed_dependency_id = str(recovery.get("failed_dependency_id") or "")
        attempt_budget = 0
        if failed_dependency_id:
            try:
                attempt_budget = int(recovery.get("attempt_budget") or 0)
            except (TypeError, ValueError):
                attempt_budget = 0
            attempt_budget = max(1, min(attempt_budget, M4_FAILED_DEPENDENCY_RECOVERY_ATTEMPT_BUDGET))
        parent_task_id = str(recovery.get("parent_task_id") or "")
        if parent_task_id not in self.task_system.tasks:
            parent_task_id = ""
        task_metadata = {
            "m4_readiness_recovery_requirement": copy.deepcopy(requirement),
            "blocked_task_id": str(blocked_task.get("id") or ""),
        } if requirement else {}
        if failed_dependency_id:
            task_metadata["m4_failed_dependency_recovery"] = {
                "schema_version": 1,
                "policy_id": FAILED_DEPENDENCY_MACHINE_STATE_RECONCILIATION_POLICY_ID,
                "failed_dependency_id": failed_dependency_id,
                "failed_dependency_title": str(recovery.get("failed_dependency_title") or ""),
                "failed_dependency_status": str(recovery.get("failed_dependency_status") or ""),
                "parent_task_id": parent_task_id,
                "root_plan_id": str(recovery.get("root_plan_id") or ""),
                "planner_call_id": str(recovery.get("planner_call_id") or ""),
                "requirement_fingerprint": fingerprint,
                "attempt_budget": attempt_budget,
            }
        task = self.task_system.create_task(
            title=goal,
            task_type="recovery",
            parent_id=parent_task_id or None,
            status=TaskStatus.ACCEPTED,
            priority=priority,
            success_criteria=recovery.get("success_criteria", {}) if isinstance(recovery.get("success_criteria", {}), dict) else {},
            failure_criteria={"max_failures": attempt_budget} if attempt_budget else {},
            tags=tags,
            opportunity_triggers=(
                list(recovery.get("opportunity_triggers", []) or [])[:8]
                if isinstance(recovery.get("opportunity_triggers", []), list)
                else []
            ),
            rationale=(
                f"Generated from readiness blockers for {blocked_task.get('title', 'blocked task')}: "
                f"{json.dumps(recovery.get('missing', {}), default=str)[:180]}"
            ),
            root_plan_id=str(recovery.get("root_plan_id") or ""),
            planner_call_id=str(recovery.get("planner_call_id") or ""),
            metadata=task_metadata,
        )
        return task, True

    def _knowledge_base(self):
        kb = getattr(self, "knowledge_base", None)
        if kb is not None:
            return kb
        try:
            kb = KnowledgeBase()
            self.knowledge_base = kb
            return kb
        except Exception as e:
            logger.warning(f"Could not initialize recovery knowledge base: {e}")
            return None

    def _safe_plan_priority(self, value) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 3

    def _deadline_from_plan_seconds(self, seconds):
        if seconds is None:
            return None
        try:
            return time.time() + float(seconds)
        except (TypeError, ValueError):
            return None

    def _bind_m4_ready_task_goal(self, task) -> dict:
        self._m4_ready_task_goal_binding = {}
        if str(getattr(getattr(self, "config", None), "planner_protocol", "") or "") != "m4-fixed-v1":
            return {}
        if task is None:
            return {}
        criteria = task.success_criteria if isinstance(task.success_criteria, dict) else None
        binding = {
            "schema_version": 1,
            "policy_id": M4_READY_TASK_GOAL_VERIFIER_POLICY_ID,
            "task_id": str(getattr(task, "id", "") or ""),
            "goal": str(getattr(task, "title", "") or ""),
            "selection_reason": "ready_task_selected",
            "success_criteria": copy.deepcopy(criteria) if criteria is not None else None,
        }
        self._m4_ready_task_goal_binding = binding
        return dict(binding)

    def _gate_m4_ready_task_goal_verification(
        self,
        goal: str,
        verified: bool,
        verification,
        context: dict = None,
    ) -> tuple[bool, dict]:
        if str(getattr(getattr(self, "config", None), "planner_protocol", "") or "") != "m4-fixed-v1":
            return bool(verified), {}

        decision = getattr(self, "_last_autonomous_goal_decision", {})
        decision = decision if isinstance(decision, dict) else {}
        binding = getattr(self, "_m4_ready_task_goal_binding", {})
        binding = binding if isinstance(binding, dict) else {}
        decision_reason = str(decision.get("selection_reason") or "")
        binding_reason = str(binding.get("selection_reason") or "")
        if "ready_task_selected" not in {decision_reason, binding_reason}:
            return bool(verified), {}

        goal = str(goal or "")
        task_id = str(binding.get("task_id") or "")
        bound_criteria = binding.get("success_criteria")
        task_system = getattr(self, "task_system", None)
        tasks = getattr(task_system, "tasks", {})
        task = tasks.get(task_id) if isinstance(tasks, dict) and task_id else None
        task_status = getattr(task, "status", None)
        task_status_value = str(getattr(task_status, "value", "") or "")
        task_criteria = getattr(task, "success_criteria", None)

        binding_issues = []
        if not binding:
            binding_issues.append("binding_missing")
        else:
            if binding.get("policy_id") != M4_READY_TASK_GOAL_VERIFIER_POLICY_ID:
                binding_issues.append("binding_policy_mismatch")
            if binding.get("schema_version") != 1:
                binding_issues.append("binding_schema_version_mismatch")
            if binding_reason != "ready_task_selected":
                binding_issues.append("binding_selection_reason_mismatch")
            if str(binding.get("goal") or "") != goal:
                binding_issues.append("binding_goal_mismatch")
            if not task_id:
                binding_issues.append("binding_task_id_missing")
            if not isinstance(bound_criteria, dict) or not bound_criteria:
                binding_issues.append("binding_success_criteria_missing_or_malformed")
        if decision_reason != "ready_task_selected":
            binding_issues.append("decision_selection_reason_mismatch")
        if str(decision.get("goal") or "") != goal:
            binding_issues.append("decision_goal_mismatch")
        if task is None:
            binding_issues.append("bound_task_missing")
        else:
            if str(getattr(task, "title", "") or "") != goal:
                binding_issues.append("bound_task_goal_mismatch")
            if not isinstance(task_criteria, dict) or task_criteria != bound_criteria:
                binding_issues.append("bound_task_success_criteria_mismatch")

        deadline = getattr(self, "_episode_deadline_monotonic", None)
        deadline_valid = bool(
            isinstance(deadline, (int, float))
            and not isinstance(deadline, bool)
            and math.isfinite(float(deadline))
        )
        deadline_reached = bool(deadline_valid and self._episode_deadline_reached())
        binding_valid = not binding_issues
        verifier_accepted = bool(verified)
        verifier_achieved = bool(getattr(verification, "achieved", False))
        result = getattr(task, "result", None)
        result = result if isinstance(result, dict) else {}
        machine_completion_source = str(result.get("completed_by") or "")
        task_machine_completed = bool(
            binding_valid
            and task_status == TaskStatus.COMPLETED
            and machine_completion_source in {"machine_state", "action_result"}
        )
        accepted = bool(
            verifier_accepted
            and binding_valid
            and deadline_valid
            and not deadline_reached
            and task_machine_completed
        )

        if not deadline_valid:
            gate_decision = "suppress_invalid_deadline"
        elif deadline_reached:
            gate_decision = "suppress_episode_deadline"
        elif not binding_valid:
            gate_decision = "suppress_invalid_binding"
        elif not verifier_accepted:
            gate_decision = "retain_unverified_goal"
        elif task_machine_completed:
            gate_decision = "allow_bound_task_machine_completion"
        else:
            gate_decision = "suppress_until_bound_task_machine_completion"

        verification_payload = (
            verification.to_dict()
            if hasattr(verification, "to_dict")
            else {"achieved": bool(verified)}
        )
        report = {
            "schema_version": 1,
            "policy_id": M4_READY_TASK_GOAL_VERIFIER_POLICY_ID,
            "goal": goal,
            "task_id": task_id,
            "success_criteria": copy.deepcopy(bound_criteria) if isinstance(bound_criteria, dict) else bound_criteria,
            "task_status": task_status_value,
            "selection_reason": decision_reason or binding_reason,
            "binding_valid": binding_valid,
            "binding_issues": binding_issues,
            "verifier_accepted": verifier_accepted,
            "verifier_achieved": verifier_achieved,
            "verifier_result": verification_payload,
            "task_machine_completed": task_machine_completed,
            "machine_completion_source": machine_completion_source,
            "deadline_monotonic": deadline,
            "deadline_valid": deadline_valid,
            "deadline_reached": deadline_reached,
            "completion_suppressed": bool(verifier_accepted and not accepted),
            "decision": gate_decision,
            "context": dict(context or {}),
        }
        session_log = getattr(getattr(self, "session_logger", None), "log", None)
        if callable(session_log):
            session_log(
                "m4_ready_task_goal_verifier_binding",
                dict(report),
                level="WARNING" if report["completion_suppressed"] else "INFO",
            )
        self._write_memory_episode(
            "m4_ready_task_goal_verifier_binding",
            report,
            source="m4_ready_task_goal_verifier",
        )
        return accepted, report

    def _select_autonomous_goal(self, observation: dict, fallback_goal: str) -> str:
        """Let ready tasks and open-ended curriculum override generated goals."""
        self._m4_ready_task_goal_binding = {}
        self._m4_active_readiness_recovery_root_id = ""
        self._reconcile_m4_satisfied_tasks(
            observation,
            fallback_goal,
            0,
            source="pre_goal_machine_observation",
        )
        if self._should_preserve_autonomous_fallback(observation, fallback_goal):
            self._set_autonomous_goal_decision(fallback_goal, getattr(self, "_last_autonomous_goal_decision", {}))
            return fallback_goal
        scheduling_state = self._state_with_causal_context(observation, fallback_goal)
        readiness_report = (
            self.task_system.task_readiness_report(scheduling_state)
            if hasattr(self.task_system, "task_readiness_report")
            else {}
        )
        next_task = self.task_system.get_next_task(scheduling_state)
        if next_task:
            self._set_autonomous_goal_decision(
                next_task.title,
                {},
                source="curriculum",
                reason="ready_task_selected",
                priority=6,
                priority_class="tool_resource_progression",
            )
            self._bind_m4_ready_task_goal(next_task)
            self._record_frontier_budget_decision(
                observation,
                next_task.title,
                decision={"selected": next_task.title, "candidates": []},
                readiness_report=readiness_report,
            )
            return next_task.title
        recovery_goal = self._task_readiness_recovery_goal(scheduling_state, fallback_goal)
        if recovery_goal:
            self._set_autonomous_goal_decision(
                recovery_goal,
                {},
                source="curriculum",
                reason="readiness_recovery_selected",
                priority=6,
                priority_class="tool_resource_progression",
            )
            recovery_readiness = (
                self.task_system.task_readiness_report(scheduling_state)
                if hasattr(self.task_system, "task_readiness_report")
                else readiness_report
            )
            self._record_frontier_budget_decision(
                observation,
                recovery_goal,
                decision={"selected": recovery_goal, "candidates": []},
                readiness_report=recovery_readiness,
            )
            return recovery_goal
        if (
            getattr(getattr(self, "config", None), "enable_autocurriculum", True)
            and hasattr(self, "curriculum")
        ):
            coach_policy = self._active_coach_policy()
            if coach_policy:
                goal = self._select_coached_curriculum_goal(
                    observation,
                    fallback_goal,
                    coach_policy,
                )
            else:
                goal = self.curriculum.next_goal(
                    observation,
                    fallback_goal,
                    getattr(self, "memory", None),
                    getattr(self, "skill_library", None),
                )
            if goal == fallback_goal:
                decision = dict(getattr(self, "_last_autonomous_goal_decision", {}) or {})
                reason = str(decision.get("selection_reason") or "goal_generator_fallback")
                decision["selection_reason"] = f"{reason};curriculum_retained_fallback"
                self._set_autonomous_goal_decision(goal, decision)
            else:
                curriculum_decision = dict(getattr(self.curriculum, "last_decision", {}) or {})
                candidates = curriculum_decision.get("candidates", [])
                selected = next(
                    (
                        candidate for candidate in candidates
                        if isinstance(candidate, dict) and candidate.get("title") == goal
                    ),
                    {},
                )
                reasons = selected.get("reasons", []) if isinstance(selected.get("reasons", []), list) else []
                self._set_autonomous_goal_decision(
                    goal,
                    {},
                    source="curriculum",
                    reason="curriculum_ranked:" + (str(reasons[0]) if reasons else "highest_score"),
                    priority=6,
                    priority_class="tool_resource_progression",
                    score=selected.get("score"),
                )
            self._record_frontier_budget_decision(
                observation,
                goal,
                decision=getattr(self.curriculum, "last_decision", {}),
                readiness_report=readiness_report,
            )
            if hasattr(self, "memory") and goal != fallback_goal:
                payload = {
                    "fallback": fallback_goal,
                    "selected": goal,
                    "decision": getattr(self.curriculum, "last_decision", {}),
                }
                if hasattr(self, "session_logger") and hasattr(self.session_logger, "log"):
                    self.session_logger.log("curriculum_goal", payload)
                self._write_memory_episode("curriculum_goal", payload, source="curriculum")
            return goal
        return fallback_goal

    def _set_autonomous_goal_decision(
        self,
        goal: str,
        decision: dict,
        source: str = "goal_generator",
        reason: str = "rule_generator",
        priority: int = 6,
        priority_class: str = "tool_resource_progression",
        score=None,
    ):
        decision = decision if isinstance(decision, dict) else {}
        selected_source = str(decision.get("selection_source") or source)
        if selected_source not in {"goal_generator", "curriculum"}:
            selected_source = source if source in {"goal_generator", "curriculum"} else "goal_generator"
        selected_reason = str(decision.get("selection_reason") or reason).strip() or "rule_generator"
        try:
            selected_priority = int(decision.get("priority", priority))
        except (TypeError, ValueError):
            selected_priority = int(priority)
        selected_priority = min(6, max(1, selected_priority))
        selected_score = decision.get("selection_score", score)
        try:
            selected_score = float(selected_score) if selected_score is not None else None
        except (TypeError, ValueError):
            selected_score = None
        if selected_score is not None and not math.isfinite(selected_score):
            selected_score = None
        self._last_autonomous_goal_decision = {
            "goal": str(goal or ""),
            "selection_source": selected_source,
            "selection_reason": selected_reason,
            "priority": selected_priority,
            "priority_class": str(decision.get("priority_class") or priority_class),
            "selection_score": selected_score,
        }

    def _should_preserve_autonomous_fallback(self, observation: dict, fallback_goal: str) -> bool:
        """Keep urgent survival goals ahead of scheduled or recovery work."""
        observation = observation or {}
        config = getattr(self, "config", None)
        threshold = getattr(config, "health_critical_threshold", 6)
        try:
            if float(observation.get("health", 20)) < float(threshold):
                return True
        except (TypeError, ValueError):
            pass

        try:
            hunger = float(observation.get("hunger", observation.get("food", 20)))
            if hunger <= float(GoalGenerator.LOW_HUNGER):
                return True
        except (TypeError, ValueError):
            pass

        for entity in observation.get("nearby_entities", []) or []:
            if not isinstance(entity, dict) or not entity.get("hostile"):
                continue
            try:
                if float(entity.get("distance", 999)) <= 8:
                    return True
            except (TypeError, ValueError):
                continue

        text = str(fallback_goal or "").lower()
        if any(token in text for token in ("attack", "flee", "eat", "restore health", "find food")):
            return True
        try:
            time_of_day = float(observation.get("time_of_day", 0))
        except (TypeError, ValueError):
            time_of_day = 0
        night_goal = any(token in text for token in ("shelter", "nightfall", "wait for dawn"))
        return night_goal and (time_of_day >= 10000 or time_of_day < 1000)

    def _active_coach_policy(self):
        """Return the configured advisory coach if the runtime policy is enabled."""
        if not getattr(getattr(self, "config", None), "enable_coaching_policy", True):
            return None
        coach_policy = getattr(self, "coach_policy", None)
        if coach_policy is None:
            coach_policy = CoachPolicy.from_style(getattr(getattr(self, "config", None), "coach_style", ""))
            self.coach_policy = coach_policy
        return coach_policy if coach_policy.active else None

    def _select_coached_curriculum_goal(
        self,
        observation: dict,
        fallback_goal: str,
        coach_policy,
    ) -> str:
        """Apply advisory coach bias to curriculum candidates without bypassing tasks."""
        candidates = self.curriculum.propose_goals(
            observation,
            fallback_goal,
            getattr(self, "memory", None),
            getattr(self, "skill_library", None),
        )
        if not candidates:
            return fallback_goal
        ranked = coach_policy.rank_curriculum_candidates(candidates, observation, fallback_goal)
        best = ranked[0] if ranked else candidates[0]
        self.curriculum.last_decision = {
            "selected": best.title,
            "fallback": fallback_goal,
            "coach": coach_policy.summary(),
            "candidates": [self.curriculum._candidate_dict(candidate) for candidate in ranked[:5]],
        }
        return best.title

    def _state_with_causal_context(self, observation: dict, goal: str = "") -> dict:
        """Augment world state with compact causal event tags for scheduling."""
        if not hasattr(self, "memory") or not hasattr(self.memory, "get_causal_opportunity_context"):
            return observation
        query = self._causal_scheduling_query(goal)
        decision = self._memory_read_decision(query, "causal", "opportunity_context", "retrieve")
        context = {}
        if decision.should_retrieve:
            context = self.memory.get_causal_opportunity_context(query, observation)
        self._log_memory_read(
            query=query,
            layer="causal",
            memory_type="opportunity_context",
            operation="retrieve",
            result=context,
            source="causal_scheduler",
            decision=decision,
            planning_context=False,
        )
        if not context.get("causal_tags") and not context.get("causal_events"):
            return observation

        enriched = dict(observation)
        existing_tags = set(str(tag).lower() for tag in enriched.get("causal_tags", []))
        existing_tags.update(context.get("causal_tags", []))
        enriched["causal_tags"] = sorted(tag for tag in existing_tags if tag)
        enriched["causal_events"] = list(enriched.get("causal_events", [])) + context.get("causal_events", [])
        return enriched

    def _causal_scheduling_query(self, goal: str = "") -> str:
        parts = [goal]
        if not hasattr(self, "task_system"):
            return goal
        for task in self.task_system.tasks.values():
            if task.status in (TaskStatus.ACCEPTED, TaskStatus.ACTIVE):
                parts.append(task.title)
                parts.extend(task.tags)
                parts.extend(task.opportunity_triggers)
        return " ".join(str(part) for part in parts if part)

    @staticmethod
    def _m4_lifecycle_identity(lifecycle: dict) -> tuple:
        value = lifecycle if isinstance(lifecycle, dict) else {}
        fields = (
            "tracker_id",
            "episode_id",
            "level_name",
            "protocol_sha256",
            "baseline_id",
        )
        identity = tuple(value.get(name) for name in fields)
        return identity if all(item is not None and item != "" for item in identity) else ()

    def _record_m4_player_lifecycle(self, observation: dict):
        if str(getattr(getattr(self, "config", None), "planner_protocol", "") or "") != "m4-fixed-v1":
            return
        lifecycle = observation.get("player_lifecycle") if isinstance(observation, dict) else None
        lifecycle = lifecycle if isinstance(lifecycle, dict) else {}
        report = validate_m4_player_lifecycle(
            lifecycle,
            episode_id=str(lifecycle.get("episode_id") or ""),
            require_uninterrupted=False,
        )
        identity = self._m4_lifecycle_identity(lifecycle)
        expected_identity = tuple(getattr(self, "_m4_player_lifecycle_identity", ()) or ())
        if report["passed"] and identity and not expected_identity:
            self._m4_player_lifecycle_identity = identity
        elif report["passed"] and identity != expected_identity:
            report = dict(report)
            report["passed"] = False
            report["issues"] = list(report["issues"]) + ["baseline_identity_changed"]
        fingerprint_payload = {
            "lifecycle": lifecycle,
            "validation_passed": report["passed"],
            "validation_issues": report["issues"],
        }
        fingerprint = hashlib.sha256(
            json.dumps(
                fingerprint_payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                default=str,
            ).encode("utf-8")
        ).hexdigest()
        if fingerprint == str(getattr(self, "_m4_player_lifecycle_fingerprint", "") or ""):
            return
        self._m4_player_lifecycle_fingerprint = fingerprint
        payload = dict(lifecycle) if lifecycle else {
            "type": "m4_player_lifecycle",
            "schema_version": 1,
        }
        payload.update({
            "validation_passed": report["passed"],
            "validation_issues": list(report["issues"]),
            "lifecycle_state_fingerprint": fingerprint,
        })
        self.session_logger.log("m4_player_lifecycle", payload)

    def _observe(self) -> dict:
        """Observe world state and attach lightweight visual grounding when enabled."""
        self._recover_m4_bridge_before_observation()
        observation = self.observer.observe()
        self._record_m4_player_lifecycle(observation)
        observation = self._attach_m4_shelter_verification(observation)
        observation = self._attach_m4_post_place_machine_observation(observation)
        relocation = getattr(self, "_m4_shelter_relocation", {})
        if isinstance(relocation, dict) and relocation:
            observation = dict(observation)
            observation["m4_shelter_relocation"] = dict(relocation)
        benchmark_context = getattr(self, "_m2_benchmark_context", {})
        if isinstance(benchmark_context, dict) and benchmark_context:
            observation = dict(observation)
            observation["benchmark_context"] = dict(benchmark_context)
        if not getattr(getattr(self, "config", None), "enable_vision_analysis", True):
            return observation
        observation = self._maybe_capture_screenshot(observation)
        if not hasattr(self, "vision_analyzer") or not self.vision_analyzer:
            return observation
        try:
            screenshot_path = self._screenshot_path_from_observation(observation)
            analysis = self.vision_analyzer.analyze(observation, screenshot_path=screenshot_path)
        except Exception as e:
            logger.warning(f"Vision analysis failed: {e}")
            return observation
        if not isinstance(analysis, dict):
            return observation
        enriched = self._merge_visual_analysis(observation, analysis)
        self._log_vision_analysis(analysis, screenshot_path=screenshot_path)
        return enriched

    def _recover_m4_bridge_before_observation(self):
        protocol = str(
            getattr(getattr(self, "config", None), "planner_protocol", "") or ""
        )
        if protocol != "m4-fixed-v1":
            return
        recover = getattr(getattr(self, "bot", None), "recover_deadline_bound_transport", None)
        if not callable(recover):
            return

        report = recover()
        if not isinstance(report, dict) or report.get("recovery_required") is not True:
            return
        payload = dict(report)
        session_logger = getattr(self, "session_logger", None)
        if session_logger is not None and hasattr(session_logger, "log"):
            session_logger.log(
                "m4_deadline_bound_bridge_recovery",
                payload,
                level="INFO" if payload.get("success") is True else "ERROR",
            )
        if payload.get("success") is not True or payload.get("machine_state_confirmed") is not True:
            raise RuntimeError(
                "M4 bridge recovery did not produce confirmed machine state: "
                + str(payload.get("error") or "unknown recovery failure")
            )

    def _attach_m4_shelter_verification(self, observation: dict) -> dict:
        if str(getattr(getattr(self, "config", None), "planner_protocol", "") or "") != "m4-fixed-v1":
            return observation
        get_state = getattr(getattr(self, "bot", None), "get_shelter_state", None)
        if callable(get_state):
            try:
                machine_state = get_state()
            except Exception as exc:
                machine_state = {"success": False, "error": str(exc)}
        else:
            machine_state = {"success": False, "error": "bridge shelter-state command unavailable"}
        verifier = getattr(self, "m4_shelter_verifier", None) or M4ShelterVerifier()
        report = verifier.verify(
            machine_state,
            getattr(self, "_m4_episode_block_delta", {}),
        )
        enriched = dict(observation or {})
        enriched["shelter_verification"] = report

        fingerprint = json.dumps({
            "passed": report.get("passed"),
            "issues": report.get("issues", []),
            "checks": [
                (check.get("name"), check.get("passed"))
                for check in report.get("checks", [])
                if isinstance(check, dict)
            ],
            "matched_delta": (report.get("episode_block_delta") or {}).get("matched_position_count"),
        }, sort_keys=True, separators=(",", ":"))
        if fingerprint != getattr(self, "_m4_shelter_verification_fingerprint", ""):
            self._m4_shelter_verification_fingerprint = fingerprint
            log = getattr(getattr(self, "session_logger", None), "log", None)
            if callable(log):
                log("shelter_state_verification", report)
        return enriched

    def _record_m4_episode_block_delta(self, action: dict, result: dict):
        if str(getattr(getattr(self, "config", None), "planner_protocol", "") or "") != "m4-fixed-v1":
            return
        if not isinstance(action, dict) or not isinstance(result, dict) or result.get("success") is not True:
            return
        delta = getattr(self, "_m4_episode_block_delta", None)
        if not isinstance(delta, dict):
            delta = {"placed": {}, "removed": {}}
            self._m4_episode_block_delta = delta
        placed = delta.setdefault("placed", {})
        removed = delta.setdefault("removed", {})
        action_type = str(action.get("type") or "")

        if action_type == "place":
            self._store_m4_block_change(
                placed,
                result.get("target_block_before"),
                result.get("target_block_after"),
                action_type,
                "place",
            )
        elif action_type in {"build_shelter_5x5", "build_shelter_cell"}:
            material = str(result.get("material") or "")
            for position in result.get("placed_positions", []) if isinstance(result.get("placed_positions"), list) else []:
                self._store_m4_block_change(
                    placed,
                    {"name": "air", "position": position},
                    {"name": material, "position": position},
                    action_type,
                    "place",
                )
        elif action_type == "dig" and result.get("block_removed") is True:
            self._store_m4_block_change(
                removed,
                result.get("target_block_before"),
                result.get("target_block_after"),
                action_type,
                "remove",
            )

    @staticmethod
    def _m4_integral_block_position(value) -> dict:
        if not isinstance(value, dict):
            return {}
        position = {}
        for axis in ("x", "y", "z"):
            coordinate = value.get(axis)
            if isinstance(coordinate, bool) or not isinstance(coordinate, (int, float)):
                return {}
            coordinate = float(coordinate)
            if not math.isfinite(coordinate) or not coordinate.is_integer():
                return {}
            position[axis] = int(coordinate)
        return position

    @classmethod
    def _m4_post_place_machine_observation_report(cls, action: dict, result: dict) -> dict:
        report = {
            "schema_version": 1,
            "policy_id": M4_POST_PLACE_MACHINE_OBSERVATION_POLICY_ID,
            "passed": False,
            "reason": "invalid_action",
            "projection_observation_limit": M4_POST_PLACE_MACHINE_OBSERVATION_LIMIT,
        }
        if not isinstance(action, dict) or str(action.get("type") or "") != "place":
            return report
        params = action.get("parameters") if isinstance(action.get("parameters"), dict) else {}
        item = params.get("item")
        if item != M4_POST_PLACE_MACHINE_OBSERVATION_ITEM:
            report["reason"] = "item_out_of_scope"
            return report
        report["item"] = item
        if not isinstance(result, dict) or result.get("success") is not True:
            report["reason"] = "result_not_successful"
            return report
        if result.get("item") != item:
            report["reason"] = "result_item_mismatch"
            return report

        action_reference = cls._m4_integral_block_position(params)
        result_reference = cls._m4_integral_block_position(result.get("reference_position"))
        placed_position = cls._m4_integral_block_position(result.get("placed_position"))
        if not action_reference or not result_reference or not placed_position:
            report["reason"] = "position_missing_or_malformed"
            return report
        expected_position = {
            "x": action_reference["x"],
            "y": action_reference["y"] + 1,
            "z": action_reference["z"],
        }
        if result_reference != action_reference or placed_position != expected_position:
            report["reason"] = "placed_target_mismatch"
            return report

        before = result.get("target_block_before")
        after = result.get("target_block_after")
        if not isinstance(before, dict) or not isinstance(after, dict):
            report["reason"] = "target_block_evidence_missing"
            return report
        before_position = cls._m4_integral_block_position(before.get("position"))
        after_position = cls._m4_integral_block_position(after.get("position"))
        before_name = before.get("name")
        after_name = after.get("name")
        if before_position != placed_position or after_position != placed_position:
            report["reason"] = "target_block_position_mismatch"
            return report
        if (
            not isinstance(before_name, str)
            or not before_name.strip()
            or before_name == "unknown"
            or before_name == item
            or after_name != item
        ):
            report["reason"] = "target_block_name_mismatch"
            return report

        report.update({
            "passed": True,
            "reason": "machine_verified_target_block_after",
            "reference_position": action_reference,
            "placed_position": placed_position,
            "target_block_before": {"name": before_name, "position": placed_position},
            "target_block_after": {"name": after_name, "position": placed_position},
            "machine_state_source": "action_result.target_block_after",
        })
        return report

    def _record_m4_post_place_machine_observation(self, action: dict, result: dict) -> dict:
        if str(getattr(getattr(self, "config", None), "planner_protocol", "") or "") != "m4-fixed-v1":
            return {}
        report = self._m4_post_place_machine_observation_report(action, result)
        if report.get("reason") == "item_out_of_scope" or report.get("reason") == "invalid_action":
            return report
        if report.get("passed") is True:
            self._m4_post_place_machine_observation = {
                "report": dict(report),
                "remaining_observations": M4_POST_PLACE_MACHINE_OBSERVATION_LIMIT,
            }
        log = getattr(getattr(self, "session_logger", None), "log", None)
        if callable(log):
            log("m4_post_place_machine_observation_grounding", dict(report))
        return report

    def _attach_m4_post_place_machine_observation(self, observation: dict) -> dict:
        if str(getattr(getattr(self, "config", None), "planner_protocol", "") or "") != "m4-fixed-v1":
            return observation
        state = getattr(self, "_m4_post_place_machine_observation", {})
        if not isinstance(state, dict) or not state:
            return observation
        report = state.get("report") if isinstance(state.get("report"), dict) else {}
        block = report.get("target_block_after") if isinstance(report.get("target_block_after"), dict) else {}
        remaining = state.get("remaining_observations")
        if (
            report.get("passed") is not True
            or report.get("policy_id") != M4_POST_PLACE_MACHINE_OBSERVATION_POLICY_ID
            or block.get("name") != M4_POST_PLACE_MACHINE_OBSERVATION_ITEM
            or not self._m4_integral_block_position(block.get("position"))
            or isinstance(remaining, bool)
            or not isinstance(remaining, int)
            or remaining <= 0
            or not isinstance(observation, dict)
            or not isinstance(observation.get("nearby_blocks"), list)
        ):
            self._m4_post_place_machine_observation = {}
            return observation

        placed_position = self._m4_integral_block_position(block["position"])
        nearby_blocks = list(observation["nearby_blocks"])
        already_observed = any(
            isinstance(candidate, dict)
            and candidate.get("name") == block["name"]
            and self._m4_integral_block_position(candidate.get("position")) == placed_position
            for candidate in nearby_blocks
        )
        if not already_observed:
            nearby_blocks.append({
                "name": block["name"],
                "position": placed_position,
                "machine_verified": True,
                "machine_state_source": report["machine_state_source"],
                "grounding_policy_id": M4_POST_PLACE_MACHINE_OBSERVATION_POLICY_ID,
            })

        remaining_after = remaining - 1
        enriched = dict(observation)
        enriched["nearby_blocks"] = nearby_blocks
        enriched["m4_post_place_machine_observation"] = {
            "schema_version": 1,
            "policy_id": M4_POST_PLACE_MACHINE_OBSERVATION_POLICY_ID,
            "passed": True,
            "projected": not already_observed,
            "placed_position": placed_position,
            "item": block["name"],
            "remaining_observations": remaining_after,
            "machine_state_source": report["machine_state_source"],
        }
        if remaining_after > 0:
            self._m4_post_place_machine_observation = {
                **state,
                "remaining_observations": remaining_after,
            }
        else:
            self._m4_post_place_machine_observation = {}
        return enriched

    @staticmethod
    def _m4_relocation_action_matches(action: dict, relocation: dict) -> bool:
        if not isinstance(action, dict) or action.get("type") != "move_to":
            return False
        params = action.get("parameters", {}) if isinstance(action.get("parameters"), dict) else {}
        target = relocation.get("target_position", {}) if isinstance(relocation, dict) else {}
        try:
            return all(
                abs(float(params[axis]) - float(target[axis])) <= 1e-6
                for axis in ("x", "y", "z")
            )
        except (KeyError, TypeError, ValueError):
            return False

    def _update_m4_shelter_relocation(self, action: dict, result: dict):
        if str(getattr(getattr(self, "config", None), "planner_protocol", "") or "") != "m4-fixed-v1":
            return
        if not isinstance(action, dict) or not isinstance(result, dict):
            return
        action_type = str(action.get("type") or "")
        current = getattr(self, "_m4_shelter_relocation", {})
        current = current if isinstance(current, dict) else {}
        log = getattr(getattr(self, "session_logger", None), "log", None)

        if action_type == "build_shelter_cell":
            self._m4_shelter_relocation = {}
            if result.get("success") is True:
                return
            atomicity = result.get("atomicity", {}) if isinstance(result.get("atomicity"), dict) else {}
            target_origin = result.get("relocation_origin")
            target_position = result.get("relocation_target")
            if (
                result.get("relocation_required") is not True
                or atomicity.get("passed") is not True
                or not isinstance(target_origin, dict)
                or not isinstance(target_position, dict)
            ):
                return
            try:
                source_origin = result.get("origin", {}) if isinstance(result.get("origin"), dict) else {}
                source_values = {axis: source_origin[axis] for axis in ("x", "y", "z")}
                target_values = {axis: target_origin[axis] for axis in ("x", "y", "z")}
                radius_value = result.get("relocation_search_radius")
                if any(
                    isinstance(value, bool)
                    for value in (*source_values.values(), *target_values.values(), radius_value)
                ):
                    return
                source_values = {axis: float(value) for axis, value in source_values.items()}
                target_values = {axis: float(value) for axis, value in target_values.items()}
                radius_value = float(radius_value)
                if (
                    not all(math.isfinite(value) and value.is_integer() for value in source_values.values())
                    or not all(math.isfinite(value) and value.is_integer() for value in target_values.values())
                    or not math.isfinite(radius_value)
                    or not radius_value.is_integer()
                ):
                    return
                source_origin = {axis: int(value) for axis, value in source_values.items()}
                target_origin = {axis: int(value) for axis, value in target_values.items()}
                target_position = {axis: float(target_position[axis]) for axis in ("x", "y", "z")}
                search_radius = int(radius_value)
                target_matches_origin = (
                    abs(target_position["x"] - (target_origin["x"] + 0.5)) <= 1e-6
                    and abs(target_position["y"] - target_origin["y"]) <= 1e-6
                    and abs(target_position["z"] - (target_origin["z"] + 0.5)) <= 1e-6
                )
                horizontal_offset = max(
                    abs(target_origin["x"] - source_origin["x"]),
                    abs(target_origin["z"] - source_origin["z"]),
                )
                vertical_offset = abs(target_origin["y"] - source_origin["y"])
                if (
                    not all(math.isfinite(value) for value in target_position.values())
                    or not 1 <= search_radius <= 6
                    or not 1 <= horizontal_offset <= search_radius
                    or vertical_offset > 2
                    or not target_matches_origin
                ):
                    return
            except (KeyError, TypeError, ValueError):
                return
            action_params = action.get("parameters", {}) if isinstance(action.get("parameters"), dict) else {}
            material = str(result.get("material") or action_params.get("material") or "")
            recovery_id = hashlib.sha256(
                json.dumps(
                    {
                        "source_origin": source_origin,
                        "target_origin": target_origin,
                        "target_position": target_position,
                        "material": material,
                        "error": str(result.get("error") or ""),
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                ).encode("utf-8")
            ).hexdigest()[:16]
            payload = {
                "type": "m4_shelter_relocation",
                "schema_version": 1,
                "status": "scheduled",
                "recovery_id": recovery_id,
                "source_origin": dict(source_origin),
                "target_origin": target_origin,
                "target_position": target_position,
                "search_radius": search_radius,
                "material": material,
                "source_error": str(result.get("error") or ""),
                "atomicity": dict(atomicity),
            }
            self._m4_shelter_relocation = payload
            if callable(log):
                log("m4_shelter_atomicity_recovery", dict(payload))
            return

        if current and self._m4_relocation_action_matches(action, current):
            payload = dict(current)
            payload.update({
                "status": "completed" if result.get("success") is True else "retry_required",
                "move_success": result.get("success") is True,
                "move_error": str(result.get("error") or ""),
            })
            if callable(log):
                log("m4_shelter_atomicity_recovery", payload)
            if result.get("success") is True:
                self._m4_shelter_relocation = {}

    @staticmethod
    def _store_m4_block_change(bucket: dict, before, after, action_type: str, operation: str):
        before = before if isinstance(before, dict) else {}
        after = after if isinstance(after, dict) else {}
        position = after.get("position") if isinstance(after.get("position"), dict) else before.get("position")
        if not isinstance(position, dict):
            return
        try:
            position = {axis: int(float(position[axis])) for axis in ("x", "y", "z")}
        except (KeyError, TypeError, ValueError):
            return
        if not all(float((after.get("position") or before.get("position"))[axis]).is_integer() for axis in ("x", "y", "z")):
            return
        before_name = str(before.get("name") or "unknown")
        after_name = str(after.get("name") or "unknown")
        if before_name == after_name:
            return
        key = f"{position['x']},{position['y']},{position['z']}"
        bucket[key] = {
            "operation": operation,
            "action_type": action_type,
            "success": True,
            "position": position,
            "before": {"name": before_name},
            "after": {"name": after_name},
        }

    def _maybe_capture_screenshot(self, observation: dict) -> dict:
        """Attach a screenshot path when an optional bridge renderer can provide one."""
        if not getattr(getattr(self, "config", None), "enable_screenshot_capture", False):
            return observation
        if self._screenshot_path_from_observation(observation or {}):
            return observation
        capture = getattr(getattr(self, "bot", None), "capture_screenshot", None)
        if not callable(capture):
            return observation

        now = time.time()
        min_interval = float(getattr(self.config, "screenshot_min_interval_s", 0.0) or 0.0)
        last_capture = float(getattr(self, "_last_screenshot_at", 0.0) or 0.0)
        if min_interval > 0 and now - last_capture < min_interval:
            return observation

        output_path = self._next_screenshot_path()
        self._last_screenshot_at = now
        try:
            result = capture(output_path)
        except Exception as e:
            logger.warning(f"Screenshot capture failed: {e}")
            return observation
        if not isinstance(result, dict) or not result.get("success"):
            return observation

        screenshot_path = self._screenshot_path_from_observation(result)
        if not screenshot_path:
            screenshot_path = result.get("path", "") or result.get("file", "")
        if not isinstance(screenshot_path, str) or not screenshot_path.strip():
            return observation

        enriched = dict(observation or {})
        enriched["screenshot_path"] = screenshot_path.strip()
        enriched["screenshot_capture"] = {
            "source": result.get("source", "bridge_renderer"),
            "supported": result.get("supported", True),
        }
        return enriched

    def _next_screenshot_path(self) -> str:
        screenshot_dir = getattr(getattr(self, "config", None), "screenshot_dir", "logs/screenshots") or "logs/screenshots"
        os.makedirs(screenshot_dir, exist_ok=True)
        session_id = str(getattr(getattr(self, "session_logger", None), "session_id", "session") or "session")
        safe_session = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in session_id)[:80] or "session"
        return os.path.join(screenshot_dir, f"{safe_session}_{int(time.time() * 1000)}.png")

    def _screenshot_path_from_observation(self, observation: dict) -> str:
        for key in ("screenshot_path", "screenshot", "image_path", "frame_path"):
            value = observation.get(key) if isinstance(observation, dict) else ""
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    def _merge_visual_analysis(self, observation: dict, analysis: dict) -> dict:
        enriched = dict(observation or {})
        if analysis.get("grounded_resources"):
            enriched["grounded_resources"] = analysis["grounded_resources"]
        if analysis.get("resources"):
            enriched["visual_resources"] = analysis["resources"]
        if analysis.get("dangers"):
            enriched["dangers"] = analysis["dangers"]
        if analysis.get("visual_analysis"):
            enriched["visual_analysis"] = analysis["visual_analysis"]
        return enriched

    def _log_vision_analysis(self, analysis: dict, screenshot_path: str = ""):
        payload = {
            key: value
            for key, value in analysis.items()
            if key in {"position", "health", "grounded_resources", "resources", "dangers", "nearby_entities", "visual_analysis"}
            and value not in (None, "", [], {})
        }
        if screenshot_path:
            payload["screenshot_path"] = screenshot_path
        if not payload:
            return
        if hasattr(self, "session_logger") and hasattr(self.session_logger, "log"):
            self.session_logger.log("vision", payload)
        if hasattr(self, "visual_memory") and self.visual_memory:
            self.visual_memory.add(payload, "observation")

    def _log_action_event(
        self,
        action: dict,
        result: dict,
        pre_observation: dict = None,
        post_observation: dict = None,
        context: dict = None,
    ):
        """Log an action with compact pre/post state snapshots for ASV-style replay."""
        payload = {"action": action, "result": result}
        pre_snapshot = self._action_observation_snapshot(pre_observation)
        post_snapshot = self._action_observation_snapshot(post_observation)
        if str(action.get("type") or "") == "dig":
            target_before = result.get("target_block_before")
            target_after = result.get("target_block_after")
            if isinstance(target_before, dict) and target_before:
                pre_snapshot["action_target_block"] = self._bounded_log_value(target_before, depth=0)
            if isinstance(target_after, dict) and target_after:
                post_snapshot["action_target_block"] = self._bounded_log_value(target_after, depth=0)
        if pre_snapshot:
            payload["pre_observation"] = pre_snapshot
        if post_snapshot:
            payload["post_observation"] = post_snapshot
        if context:
            payload["action_context"] = self._bounded_log_value(context, depth=0)

        session_logger = getattr(self, "session_logger", None)
        if hasattr(session_logger, "log"):
            session_logger.log("action", payload)
            return
        if hasattr(session_logger, "log_action"):
            try:
                session_logger.log_action(action, result, pre_snapshot, post_snapshot, context or {})
            except TypeError:
                session_logger.log_action(action, result)

    def _action_observation_snapshot(self, observation: dict) -> dict:
        if not isinstance(observation, dict):
            return {}
        keys = (
            "position",
            "inventory",
            "inventory_count",
            "health",
            "hunger",
            "food_saturation",
            "oxygen",
            "xp_level",
            "dimension",
            "game_mode",
            "selected_slot",
            "equipment",
            "nearby_blocks",
            "blocks",
            "visible_blocks",
            "grounded_resources",
            "visual_resources",
            "resources",
            "nearby_entities",
            "entities",
            "dangers",
            "flags",
            "biome",
            "time",
        )
        snapshot = {}
        for key in keys:
            value = observation.get(key)
            if value not in (None, "", [], {}):
                snapshot[key] = self._bounded_log_value(value, depth=0)
        return snapshot

    def _bounded_log_value(self, value, depth: int = 0):
        if depth > 4:
            return str(value)[:160]
        if isinstance(value, dict):
            result = {}
            for index, (key, item) in enumerate(value.items()):
                if index >= 32:
                    break
                key_text = str(key)
                if key_text.lower() in {"image", "image_bytes", "screenshot_bytes", "raw_pixels"}:
                    continue
                result[key_text] = self._bounded_log_value(item, depth + 1)
            return result
        if isinstance(value, list):
            return [self._bounded_log_value(item, depth + 1) for item in value[:12]]
        if isinstance(value, tuple):
            return [self._bounded_log_value(item, depth + 1) for item in value[:12]]
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return str(value)[:160]

    def _visual_memory_context(self, goal: str = "", limit: int = 3) -> str:
        if not hasattr(self, "visual_memory") or not self.visual_memory:
            return ""
        try:
            entries = self.visual_memory.search(goal) if goal else []
            if not entries:
                entries = self.visual_memory.get_recent(limit)
        except Exception:
            return ""
        lines = []
        for entry in entries[-limit:]:
            data = entry.get("data", {}) if isinstance(entry.get("data", {}), dict) else {}
            parts = []
            resources = data.get("grounded_resources") or data.get("resources") or []
            if resources:
                names = [
                    str(item.get("name", item.get("type", "")))
                    for item in resources[:4]
                    if isinstance(item, dict) and (item.get("name") or item.get("type"))
                ]
                if names:
                    parts.append("resources=" + ",".join(names))
            dangers = data.get("dangers") or []
            if dangers:
                names = [
                    str(item.get("type", item.get("name", "")))
                    for item in dangers[:3]
                    if isinstance(item, dict) and (item.get("type") or item.get("name"))
                ]
                if names:
                    parts.append("dangers=" + ",".join(names))
            if data.get("visual_analysis"):
                parts.append("analysis=" + str(data["visual_analysis"])[:160])
            if parts:
                lines.append("- " + "; ".join(parts))
        return "Recent visual memory:\n" + "\n".join(lines) if lines else ""

    def _apply_action_feedback(self, action: dict, result: dict, fallback_observation: dict, context: dict = None) -> dict:
        """Observe after an action and let TaskSystem update state from evidence."""
        pre_action_task_id = None
        protocol = str(getattr(self.config, "planner_protocol", "") or "")
        if protocol == "m2-fixed-v1":
            pre_action_task = self.task_system.get_next_task(fallback_observation or {})
            pre_action_task_id = pre_action_task.id if pre_action_task else None
        elif protocol == "m4-fixed-v1" and not self._episode_deadline_reached():
            binding = getattr(self, "_m4_ready_task_goal_binding", {})
            binding = binding if isinstance(binding, dict) else {}
            decision = getattr(self, "_last_autonomous_goal_decision", {})
            decision = decision if isinstance(decision, dict) else {}
            task_id = str(binding.get("task_id") or "")
            task = self.task_system.tasks.get(task_id) if task_id else None
            context_goal = str((context or {}).get("goal") or "")
            if (
                binding.get("policy_id") == M4_READY_TASK_GOAL_VERIFIER_POLICY_ID
                and binding.get("schema_version") == 1
                and binding.get("selection_reason") == "ready_task_selected"
                and decision.get("selection_reason") == "ready_task_selected"
                and str(binding.get("goal") or "") == context_goal
                and str(decision.get("goal") or "") == context_goal
                and task is not None
                and task.title == context_goal
                and isinstance(binding.get("success_criteria"), dict)
                and bool(binding.get("success_criteria"))
                and task.success_criteria == binding.get("success_criteria")
                and task.status in (TaskStatus.ACCEPTED, TaskStatus.ACTIVE)
            ):
                pre_action_task_id = task.id
            else:
                recovery_binding = self._m4_readiness_recovery_binding_for_goal(context_goal)
                child_id = str(recovery_binding.get("child_id") or "")
                recovery_child = self.task_system.tasks.get(child_id) if child_id else None
                if (
                    recovery_binding.get("policy_id")
                    == M4_READINESS_RECOVERY_COMPLETION_POLICY_ID
                    and recovery_binding.get("root_status") == "active"
                    and str(recovery_binding.get("root_goal") or "") == context_goal
                    and recovery_child is not None
                    and recovery_child.status in (TaskStatus.ACCEPTED, TaskStatus.ACTIVE)
                ):
                    pre_action_task_id = recovery_child.id

        self._update_m4_shelter_relocation(action, result)
        self._record_m4_episode_block_delta(action, result)
        self._record_m4_post_place_machine_observation(action, result)
        observation = fallback_observation
        try:
            observation = self._observe()
            self.session_logger.log_observation(observation)
            self._write_memory_context({
                "post_action": context or {},
                "observation_summary": self._obs_summary(observation),
            }, source="post_action_observation")
            self.explorer.record_position(observation.get("position", {}))
        except Exception as e:
            logger.warning(f"Post-action observation failed: {e}")

        task = self.task_system.apply_action_result(
            action,
            result,
            observation,
            task_id=pre_action_task_id,
        )
        self._flush_task_state_transitions({
            "source": "action_feedback",
            **(context or {}),
        })
        if protocol == "m4-fixed-v1":
            self._propagate_m4_readiness_recovery_completion(
                observation,
                [task] if task and task.status == TaskStatus.COMPLETED else [],
                goal=str((context or {}).get("goal") or ""),
                cycle=(context or {}).get("cycle", 0),
                source="action_result",
            )
        if protocol == "m4-fixed-v1":
            self._reconcile_m4_satisfied_tasks(
                observation,
                str((context or {}).get("goal") or getattr(self, "current_goal", "") or ""),
                (context or {}).get("cycle", 0),
                source="post_action_machine_observation",
            )
        if task:
            self._write_memory_episode("task_state_update", {
                "task_id": task.id,
                "task": task.title,
                "status": task.status.value,
                "action": action.get("type"),
                "success": bool(result.get("success")),
            }, source="task_system")
            self._record_task_continuity(
                (context or {}).get("goal", "") or getattr(self, "current_goal", ""),
                observation,
                plan=None,
                source="task_state_update",
                context=context or {},
                operation="maintain",
                validation_status=(
                    "verified" if task.status == TaskStatus.COMPLETED
                    else "failed" if task.status == TaskStatus.FAILED
                    else "unverified"
                ),
                validation_evidence={
                    "task_id": task.id,
                    "task_status": task.status.value,
                    "action_type": action.get("type"),
                    "action_success": bool(result.get("success")),
                    "verification_source": "task_system",
                },
                branch_status="active",
            )
        if hasattr(self.memory, "record_causal_transition"):
            causal_context = dict(context or {})
            if task:
                causal_context.update({"task_id": task.id, "task_status": task.status.value})
            self.memory.record_causal_transition(
                fallback_observation,
                action,
                result,
                observation,
                goal=causal_context.get("goal", ""),
                task=task.title if task else "",
                context=causal_context,
            )
        return observation

    def _handle_runtime_interrupt(self, observation: dict, goal: str, context: dict = None) -> tuple[bool, dict]:
        """Let the actor loop yield when fast runtime safety checks fire."""
        task = self.task_system.get_next_task(observation)
        decision = self.runtime.evaluate_interrupt(observation, goal=goal, active_task=task)
        self._record_m4_hostile_safe_state_grounding(decision, goal, context or {})
        self._last_runtime_interrupt_yield = ""
        active = dict(getattr(self, "_active_runtime_interrupt", {}) or {})
        if not decision.should_interrupt:
            if active:
                self._close_runtime_interrupt(
                    active,
                    observation,
                    goal,
                    context or {},
                    resolution="condition_cleared",
                    resume_policy="resume_preserved_frontier",
                )
            return False, observation

        if active and decision.reason not in RuntimeSupervisor.SURVIVAL_INTERRUPT_REASONS:
            self._close_runtime_interrupt(
                active,
                observation,
                goal,
                context or {},
                resolution="condition_cleared",
                resume_policy="resume_preserved_frontier",
            )
            active = {}

        if decision.reason == "task_deadline_elapsed" and task:
            payload = asdict(decision)
            payload["goal"] = goal
            payload["context"] = context or {}
            logger.warning(f"Runtime interrupt: {decision.reason}")
            self.session_logger.log("runtime_interrupt", payload, level="WARNING")
            self._write_memory_episode("runtime_interrupt", payload, source="runtime")
            evaluated_at = decision.evidence.get("evaluated_at_wallclock")
            expired_tasks = self.task_system.expire_overdue_tasks(evaluated_at)
            recovery = {
                "reason": decision.reason,
                "goal": goal,
                "context": context or {},
                "trigger_task_id": task.id,
                "expired_task_ids": [expired.id for expired in expired_tasks],
                "expired_task_count": len(expired_tasks),
                "terminal_status": TaskStatus.FAILED.value,
                "resume_policy": "replan_next_cycle",
                "recovered": bool(expired_tasks),
            }
            self._flush_task_state_transitions({
                "source": "runtime_interrupt_recovery",
                **(context or {}),
            })
            self.session_logger.log("runtime_interrupt_recovery", recovery)
            self._write_memory_episode(
                "runtime_interrupt_recovery",
                recovery,
                source="runtime",
            )
            return True, observation

        if decision.reason in RuntimeSupervisor.SURVIVAL_INTERRUPT_REASONS:
            if self.runtime.goal_is_aligned(decision.reason, goal):
                if active and active.get("reason") != decision.reason:
                    transition = {
                        "trigger_id": active.get("trigger_id"),
                        "from_reason": active.get("reason"),
                        "to_reason": decision.reason,
                        "goal": goal,
                        "context": context or {},
                        "frontier_preserved": True,
                    }
                    active.update({
                        "reason": decision.reason,
                        "recommended_goal": decision.recommended_goal,
                        "evidence": dict(decision.evidence or {}),
                    })
                    self._active_runtime_interrupt = active
                    self.session_logger.log("runtime_interrupt_escalation", transition, level="WARNING")
                    self._write_memory_episode("runtime_interrupt_escalation", transition, source="runtime")
                return False, observation

            if active and active.get("reason") != decision.reason:
                self._close_runtime_interrupt(
                    active,
                    observation,
                    goal,
                    context or {},
                    resolution="superseded",
                    resume_policy="remain_paused_for_higher_priority_interrupt",
                )
                active = {}

            if not active:
                self._runtime_interrupt_sequence = int(
                    getattr(self, "_runtime_interrupt_sequence", 0) or 0
                ) + 1
                paused_task = self._runtime_task_snapshot(task)
                active = {
                    "trigger_id": f"interrupt-{self._runtime_interrupt_sequence:04d}",
                    "reason": decision.reason,
                    "recommended_goal": decision.recommended_goal,
                    "paused_goal": goal,
                    "paused_task": paused_task,
                    "frontier_before": self._runtime_frontier_snapshot(),
                    "trigger_context": dict(context or {}),
                    "evidence": dict(decision.evidence or {}),
                }
                self._active_runtime_interrupt = active
                payload = {
                    **asdict(decision),
                    "trigger_id": active["trigger_id"],
                    "goal": goal,
                    "context": context or {},
                    "paused_task": paused_task,
                    "frontier_before": active["frontier_before"],
                    "resume_policy": "regenerate_survival_goal_then_resume_frontier",
                }
                logger.warning(f"Runtime interrupt: {decision.reason}")
                self.session_logger.log("runtime_interrupt", payload, level="WARNING")
                self._write_memory_episode("runtime_interrupt", payload, source="runtime")
            else:
                maintenance = {
                    "trigger_id": active.get("trigger_id"),
                    "reason": decision.reason,
                    "goal": goal,
                    "context": context or {},
                    "emergency_action": decision.emergency_action,
                }
                self.session_logger.log("runtime_interrupt_maintenance", maintenance, level="WARNING")
                self._write_memory_episode("runtime_interrupt_maintenance", maintenance, source="runtime")

            self._last_runtime_interrupt_yield = decision.reason
            if decision.emergency_action:
                observation = self._execute_runtime_emergency_action(
                    decision.emergency_action,
                    observation,
                    goal,
                    context or {},
                    trigger_id=active.get("trigger_id", ""),
                )
            return True, observation

        payload = asdict(decision)
        payload["goal"] = goal
        payload["context"] = context or {}
        logger.warning(f"Runtime interrupt: {decision.reason}")
        self.session_logger.log("runtime_interrupt", payload, level="WARNING")
        self._write_memory_episode("runtime_interrupt", payload, source="runtime")
        if decision.emergency_action:
            observation = self._execute_runtime_emergency_action(
                decision.emergency_action,
                observation,
                goal,
                context or {},
                trigger_id="",
            )
        return True, observation

    def _record_m4_hostile_safe_state_grounding(
        self,
        decision,
        goal: str,
        context: dict,
    ):
        decision_evidence = getattr(decision, "evidence", {}) or {}
        grounding = decision_evidence.get("m4_hostile_safe_state_grounding")
        if not isinstance(grounding, dict) or not grounding:
            self._m4_hostile_safe_state_fingerprint = ""
            return

        hostile = grounding.get("hostile_entity", {})
        fingerprint_payload = {
            "contract_sha256": grounding.get("shelter_contract_sha256"),
            "player_cell": grounding.get("verified_player_cell"),
            "hostile_id": hostile.get("id") if isinstance(hostile, dict) else None,
            "hostile_type": hostile.get("type") if isinstance(hostile, dict) else None,
        }
        fingerprint = hashlib.sha256(
            json.dumps(
                fingerprint_payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("utf-8")
        ).hexdigest()
        if fingerprint == str(getattr(self, "_m4_hostile_safe_state_fingerprint", "") or ""):
            return

        self._m4_hostile_safe_state_fingerprint = fingerprint
        payload = {
            **grounding,
            "goal": goal,
            "context": context,
            "selected_interrupt_reason": str(getattr(decision, "reason", "") or ""),
            "hostile_safe_state_fingerprint": fingerprint,
        }
        self.session_logger.log("m4_hostile_safe_state_grounding", payload)
        self._write_memory_episode(
            "m4_hostile_safe_state_grounding",
            payload,
            source="runtime",
        )

    def _execute_runtime_emergency_action(
        self,
        action: dict,
        observation: dict,
        goal: str,
        context: dict,
        trigger_id: str,
    ) -> dict:
        if self._episode_deadline_reached():
            payload = {
                "trigger_id": trigger_id,
                "goal": goal,
                "action": action,
                "emergency_action_suppressed": "episode_deadline",
            }
            self.session_logger.log("runtime_emergency_action", payload, level="WARNING")
            return observation

        selected_action = action
        selection = None
        try:
            selected_action, selection = self._select_action_for_execution(
                action,
                observation,
                goal,
                {**context, "mode": "runtime_interrupt"},
            )
        except Exception:
            selected_action, selection = action, None
        verification = None
        rejected_result = None
        try:
            verification, rejected_result = self._verify_action_for_execution(
                selected_action,
                observation,
                goal,
                {**context, "mode": "runtime_interrupt"},
            )
        except Exception:
            verification, rejected_result = None, None
        before = observation
        if rejected_result:
            result = rejected_result
        else:
            result = self.action_controller.execute(selected_action, observation)
            if verification:
                result["action_verification"] = verification
        if selection:
            result["action_candidate_selection"] = selection
        self._record_action_value(selected_action, result, goal, verification)
        event = {
            "trigger_id": trigger_id,
            "goal": goal,
            "context": context,
            "action": selected_action,
            "result": result,
        }
        self.session_logger.log("runtime_emergency_action", event)
        self._write_memory_episode("runtime_emergency_action", event, source="runtime")
        observation = self._apply_action_feedback(selected_action, result, observation, context)
        self._log_action_event(
            selected_action,
            result,
            pre_observation=before,
            post_observation=observation,
            context={**context, "goal": goal, "mode": "runtime_interrupt", "trigger_id": trigger_id},
        )
        return observation

    def _close_runtime_interrupt(
        self,
        active: dict,
        observation: dict,
        goal: str,
        context: dict,
        resolution: str,
        resume_policy: str,
    ):
        paused_task = active.get("paused_task", {}) if isinstance(active.get("paused_task"), dict) else {}
        paused_task_id = str(paused_task.get("task_id") or "")
        current_task = self.task_system.tasks.get(paused_task_id) if paused_task_id else None
        current_status = current_task.status.value if current_task else ""
        frontier_preserved = bool(
            not paused_task_id
            or (
                current_task is not None
                and current_task.status in {
                    TaskStatus.PROPOSED,
                    TaskStatus.ACCEPTED,
                    TaskStatus.ACTIVE,
                    TaskStatus.WAITING,
                    TaskStatus.BLOCKED,
                }
            )
        )
        recovery = {
            "trigger_id": active.get("trigger_id"),
            "reason": active.get("reason"),
            "resolution": resolution,
            "goal": goal,
            "context": context,
            "paused_goal": active.get("paused_goal"),
            "paused_task_id": paused_task_id,
            "paused_task_status_at_trigger": paused_task.get("status", ""),
            "paused_task_status_at_recovery": current_status,
            "frontier_preserved": frontier_preserved,
            "frontier_after": self._runtime_frontier_snapshot(),
            "resume_policy": resume_policy,
            "recovered": frontier_preserved,
            "cleared_observation": {
                "health": observation.get("health"),
                "hunger": observation.get("hunger", observation.get("food")),
                "time_of_day": observation.get("time_of_day"),
                "shelter_verified": GoalGenerator._has_verified_shelter(observation),
            },
        }
        self.session_logger.log("runtime_interrupt_recovery", recovery)
        self._write_memory_episode("runtime_interrupt_recovery", recovery, source="runtime")
        self._active_runtime_interrupt = {}

    @staticmethod
    def _runtime_task_snapshot(task) -> dict:
        if task is None:
            return {}
        status = getattr(task, "status", "")
        return {
            "task_id": str(getattr(task, "id", "") or ""),
            "title": str(getattr(task, "title", "") or ""),
            "status": status.value if hasattr(status, "value") else str(status or ""),
            "priority": getattr(task, "priority", None),
        }

    def _runtime_frontier_snapshot(self) -> list[dict]:
        statuses = {
            TaskStatus.PROPOSED,
            TaskStatus.ACCEPTED,
            TaskStatus.ACTIVE,
            TaskStatus.WAITING,
            TaskStatus.BLOCKED,
        }
        return [
            self._runtime_task_snapshot(task)
            for task in sorted(
                self.task_system.tasks.values(),
                key=lambda item: (getattr(item, "priority", 0), str(getattr(item, "id", ""))),
            )
            if getattr(task, "status", None) in statuses
        ][:16]

    def _evaluate_episode_abort(
        self,
        goal: str,
        cycle: int,
        mode: str,
        round_limit: int = 0,
    ) -> bool:
        """Log a calibrated viability probe and return whether it may stop the goal."""
        monitor = getattr(self, "episode_abort_monitor", None)
        if monitor is None or not monitor.enabled:
            return False
        events = getattr(getattr(self, "session_logger", None), "events", []) or []
        decision = monitor.evaluate(events, cycle)
        if not decision.evaluated:
            return False
        payload = decision.to_dict()
        payload.update({"goal_fingerprint": self._goal_fingerprint(goal), "mode": mode})
        saved_rounds = max(0, int(round_limit or 0) - int(cycle or 0)) if decision.active_abort else 0
        if saved_rounds:
            payload["saved_planner_rounds"] = saved_rounds
        self.session_logger.log("episode_viability_probe", payload)
        if not decision.would_abort:
            return False
        self.session_logger.log(
            "episode_early_abort",
            payload,
            level="WARNING" if decision.active_abort else "INFO",
        )
        if decision.active_abort:
            logger.warning(
                "Recall-controlled episode abort triggered: "
                f"round={cycle}, score={decision.score}, threshold={decision.threshold}"
            )
            self._write_memory_episode(
                "episode_early_abort",
                {
                    "goal_fingerprint": payload["goal_fingerprint"],
                    "round": cycle,
                    "signal_profile": decision.signal_profile,
                },
                source="episode_abort_monitor",
            )
            if saved_rounds:
                session_id = str(getattr(getattr(self, "session_logger", None), "session_id", "") or "")
                event_fingerprint = hashlib.sha256(
                    f"{session_id}|{payload['goal_fingerprint']}|{cycle}|{saved_rounds}".encode("utf-8")
                ).hexdigest()[:16]
                gate_hash = str(
                    getattr(self, "episode_abort_runtime_gate_report", {}).get("gate_integrity_sha256") or ""
                )
                self._frontier_budget_recovery_credit = {
                    "remaining_rounds": saved_rounds,
                    "event_fingerprint": event_fingerprint,
                    "gate_integrity_sha256": gate_hash,
                }
                self.session_logger.log("frontier_budget_recovery_credit", {
                    "goal_fingerprint": payload["goal_fingerprint"],
                    "saved_planner_rounds": saved_rounds,
                    "credit_rounds_available": saved_rounds,
                    "source_abort_event_fingerprint": event_fingerprint,
                    "episode_abort_gate_integrity_sha256": gate_hash,
                    "budget_extended": False,
                    "automatic_retry_allowed": False,
                })
        return decision.active_abort

    def _goal_fingerprint(self, goal: str) -> str:
        normalized = " ".join(str(goal or "").strip().lower().split())
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]

    def _obs_summary(self, obs: dict) -> dict:
        """Compact observation summary for memory."""
        return {
            "pos": obs.get("position", {}),
            "hp": obs.get("health"),
            "food": obs.get("hunger"),
            "inv_count": obs.get("inventory_count"),
            "trees": len(obs.get("trees_found", [])),
            "hostiles": len([e for e in obs.get("nearby_entities", []) if e.get("hostile")]),
            "time": obs.get("time_of_day"),
        }

    def _system_prompt(self) -> str:
        return """You are a Minecraft agent planner. Given the current game state observation, decide the next actions to achieve the goal.
Available actions: move_to, look_at, dig, place, craft, attack, equip, use_item, chat, wait
Output JSON format:
{"status": "in_progress" or "complete" or "blocked", "reasoning": "...", "actions": [{"type": "action_name", "parameters": {...}}]}
Be practical. Prefer simple, safe actions. Check inventory before crafting."""

    def _build_planning_prompt(self, observation: dict, goal: str, memory_context: str = "", skill_hint: str = "") -> str:
        parts = [f"Current goal: {goal}", f"\nCurrent observation:\n{json.dumps(observation, indent=2, default=str)[:2000]}"]
        if memory_context:
            parts.append(f"\nRelevant memory:\n{memory_context[:500]}")
        if skill_hint:
            parts.append(skill_hint)
        parts.append("\nWhat actions should I take next? Output JSON.")
        return "\n".join(parts)
