"""Skill library — stores, versions, and retrieves reusable action skills."""
import json
import os
import re
import time
import logging
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from typing import Optional

from singularity.core.skill_learning import (
    evidence_fingerprint,
    evaluation_authorization_issues,
    executable_promotion_gate_issues,
)
from singularity.core.skill_runtime import (
    build_bounded_skill_plan,
    evaluate_skill_postconditions,
    validate_bounded_action_template,
    wilson_confidence_interval,
)
from singularity.data.knowledge_base import ingredient_count

logger = logging.getLogger("singularity.skills")


@dataclass
class Skill:
    name: str
    description: str = ""
    parameters: dict = field(default_factory=dict)
    task_family: str = "general"
    preconditions: dict = field(default_factory=dict)
    required_observations: list = field(default_factory=list)
    required_inventory: list = field(default_factory=list)
    postconditions: dict = field(default_factory=dict)
    required_items: list = field(default_factory=list)
    failure_modes: list = field(default_factory=list)
    implementation: str = ""  # JSON-encoded bounded action template; never evaluated as code
    bounded_action_template: dict = field(default_factory=dict)
    expected_intermediate_states: list = field(default_factory=list)
    failure_conditions: list = field(default_factory=list)
    abort_conditions: list = field(default_factory=list)
    examples: list = field(default_factory=list)
    version: str = "1.0.0"
    status: str = "candidate"  # candidate, advisory, executable, quarantined, builtin
    parent_version: str = ""
    rollback_target: str = ""
    success_rate: float = 0.0
    total_uses: int = 0
    successful_uses: int = 0
    success_count: int = 0
    failure_count: int = 0
    observed_failure_count: int = 0
    failure_type_counts: dict = field(default_factory=dict)
    confidence_interval: dict = field(default_factory=dict)
    last_used: Optional[str] = None
    layer: str = "composite"  # primitive, composite, strategic, social, meta
    notes: str = ""
    dependencies: list[str] = field(default_factory=list)
    provenance: dict = field(default_factory=dict)
    source_session_ids: list[str] = field(default_factory=list)
    source_environment_ids: list[str] = field(default_factory=list)
    verifier_version: str = ""
    transfer_scope: dict = field(default_factory=dict)
    gate: dict = field(default_factory=dict)
    skill_memory: list[dict] = field(default_factory=list)
    skill_id: str = ""
    lifecycle_history: list[dict] = field(default_factory=list)
    failure_evidence: list[dict] = field(default_factory=list)


class SkillLibrary:
    def __init__(self, storage_path: str = "workspace/skills", persist: bool = False):
        self.storage_path = storage_path
        self.persist = persist
        self.custom_path = os.path.join(storage_path, "custom_skills.jsonl")
        self.skills: dict[str, Skill] = {}
        self._skill_history: dict[tuple[str, str], Skill] = {}
        self._skill_memory_quality_feedback: dict = {}
        self._skill_memory_quality_policies: dict[str, dict] = {}
        self._skill_memory_quality_items: dict[tuple[str, str, str], dict] = {}
        self._runtime_default_gate_profile: dict = self._empty_runtime_default_gate_profile()
        self._skill_retirement_profile: dict = self._empty_skill_retirement_profile()
        self.last_skill_router_trace: dict = {}
        os.makedirs(storage_path, exist_ok=True)
        self._load_builtin_skills()
        if self.persist:
            self._load_custom_skills()

    def _load_builtin_skills(self):
        """Load pre-defined skill templates."""
        builtins = [
            Skill("move_to", "Navigate to target coordinates", {"x": "float", "z": "float"}, layer="primitive"),
            Skill("look_at", "Look at target position", {"x": "float", "y": "float", "z": "float"}, layer="primitive"),
            Skill("dig_block", "Dig block at position", {"x": "int", "y": "int", "z": "int"}, layer="primitive"),
            Skill("place_block", "Place block at position", {"x": "int", "y": "int", "z": "int", "item": "str"}, layer="primitive"),
            Skill("craft_item", "Craft item from recipe", {"item": "str", "count": "int"}, layer="primitive"),
            Skill("attack_entity", "Attack nearest hostile entity", {}, layer="primitive"),
            Skill("eat_food", "Eat best available food", {}, layer="primitive"),
            Skill("gather_wood", "Find and chop trees for logs", {"wood_type": "str", "quantity": "int"}, layer="composite",
                  success_rate=0.0, notes="Works best with axe. Hand gathering is slow."),
            Skill("craft_tools", "Craft tools from available materials", {"tool_type": "str", "material": "str"}, layer="composite"),
            Skill("mine_stone", "Mine cobblestone underground", {"quantity": "int"}, layer="composite"),
            Skill("mine_iron", "Find and mine iron ore", {"quantity": "int"}, layer="composite"),
            Skill("smelt_iron", "Smelt raw iron into ingots", {"quantity": "int"}, layer="composite"),
            Skill("build_shelter", "Build a simple shelter", {"size": "str"}, layer="composite"),
            Skill("defend_self", "Defend against hostile mobs", {"mode": "str"}, layer="composite"),
            Skill("navigate_to_target", "Pathfind to coordinates", {"x": "float", "z": "float"}, layer="composite"),
            Skill("survive_first_night", "Complete first night survival", {}, layer="strategic"),
            Skill("prepare_for_mining", "Gather tools and torches for mining", {}, layer="strategic"),
        ]
        for skill in builtins:
            skill.skill_id = f"builtin:{skill.name}"
            skill.status = "builtin"
            skill.task_family = self.infer_task_family(skill.name)
            self.skills[skill.name] = skill

    def get_skill(self, name: str) -> Optional[Skill]:
        return self.skills.get(name)

    def list_skills(self, layer: Optional[str] = None) -> list[Skill]:
        if layer:
            return [s for s in self.skills.values() if s.layer == layer]
        return list(self.skills.values())

    def create_skill(self, name: str, description: str, implementation: str, persist: Optional[bool] = None, **kwargs) -> Skill:
        template = kwargs.get("bounded_action_template", {})
        if not template and isinstance(implementation, str) and implementation.strip():
            try:
                parsed = json.loads(implementation)
            except (TypeError, ValueError):
                parsed = {}
            if isinstance(parsed, dict) and parsed.get("dsl_version"):
                template = parsed
                kwargs["bounded_action_template"] = template
        status = str(kwargs.get("status") or "candidate").strip().lower()
        if status == "executable":
            validation = validate_bounded_action_template(template)
            if not validation.valid:
                raise ValueError(f"executable skill requires a valid bounded action template: {validation.issues}")
            gate = kwargs.get("gate", {}) if isinstance(kwargs.get("gate"), dict) else {}
            promotion_gate = gate.get("executable_promotion", gate)
            gate_issues = executable_promotion_gate_issues(
                promotion_gate,
                skill_id=str(kwargs.get("skill_id") or name),
                version=str(kwargs.get("version") or "1.0.0"),
            )
            if gate_issues:
                raise ValueError(f"executable skill requires paired live promotion evidence: {gate_issues}")
            kwargs["bounded_action_template"] = validation.normalized_template
            implementation = json.dumps(validation.normalized_template, sort_keys=True)
        kwargs.setdefault("skill_id", name)
        kwargs.setdefault("task_family", self.infer_task_family(" ".join([name, description])))
        kwargs.setdefault("status", status)
        successes = self._safe_int(kwargs.get("success_count", kwargs.get("successful_uses", 0)), default=0)
        failures = self._safe_int(kwargs.get("failure_count", 0), default=0)
        kwargs.setdefault("confidence_interval", wilson_confidence_interval(successes, failures))
        existing = self.skills.get(name)
        if existing and existing.name not in self._builtin_skill_names():
            self._skill_history[(existing.skill_id or existing.name, existing.version)] = existing
        skill = Skill(name=name, description=description, implementation=implementation, **kwargs)
        self.skills[name] = skill
        if skill.name not in self._builtin_skill_names():
            self._skill_history[(skill.skill_id or skill.name, skill.version)] = skill
        should_persist = self.persist if persist is None else persist
        if should_persist:
            self._rewrite_custom_skills()
        return skill

    def record_use(self, name: str, success: bool):
        skill = self.skills.get(name)
        if skill:
            skill.total_uses += 1
            if success:
                skill.successful_uses += 1
            skill.success_rate = skill.successful_uses / skill.total_uses if skill.total_uses > 0 else 0
            skill.last_used = time.strftime("%Y-%m-%d")

    def get_skill_by_id(self, skill_id: str) -> Optional[Skill]:
        target = str(skill_id or "").strip()
        if not target:
            return None
        return next(
            (skill for skill in self.skills.values() if skill.skill_id == target or skill.name == target),
            None,
        )

    def select_runtime_skill(
        self,
        goal: str,
        world_state: dict,
        execution_mode: str = "off",
        target_skill_id: str = "",
        experiment_id: str = "",
        evaluation_authorization: Optional[dict] = None,
    ) -> Optional[Skill]:
        """Select one learned skill without allowing advisory runtime execution."""
        mode = str(execution_mode or "off").strip().lower()
        if mode not in {"shadow", "advisory", "evaluation", "runtime"}:
            return None
        task_family = self.infer_task_family(goal)
        candidates = []
        for skill in self.skills.values():
            if skill.status == "builtin":
                continue
            if target_skill_id and target_skill_id not in {skill.skill_id, skill.name}:
                continue
            if not self.skill_transfer_scope_allows(skill, task_family):
                continue
            if mode in {"shadow", "advisory"} and skill.status not in {"advisory", "executable"}:
                continue
            if mode == "advisory" and evaluation_authorization_issues(
                evaluation_authorization or {},
                skill.skill_id,
                experiment_id,
            ):
                continue
            if mode == "evaluation":
                if skill.status == "advisory":
                    auth_issues = evaluation_authorization_issues(
                        evaluation_authorization or {},
                        skill.skill_id,
                        experiment_id,
                    )
                    if auth_issues:
                        continue
                elif skill.status != "executable":
                    continue
            if mode == "runtime":
                if skill.status != "executable":
                    continue
                promotion_gate = skill.gate.get("executable_promotion", {}) if isinstance(skill.gate, dict) else {}
                if executable_promotion_gate_issues(
                    promotion_gate,
                    skill_id=skill.skill_id,
                    version=skill.version,
                ):
                    continue
                if not self._runtime_default_skill_allowed(
                    skill.name,
                    task_family,
                    built_in=False,
                    promotion_gate_fingerprint=evidence_fingerprint(promotion_gate),
                ):
                    continue
            contract = self._skill_contract_profile(skill, goal, world_state or {})
            if contract.get("readiness") == "blocked" or contract.get("score", 0) <= 0:
                continue
            candidates.append((contract.get("score", 0), skill.success_rate, skill.total_uses, skill))
        if not candidates:
            return None
        candidates.sort(key=lambda item: (item[0], item[1], item[2], item[3].name), reverse=True)
        return candidates[0][3]

    def build_runtime_skill_plan(self, skill: Skill, goal: str, world_state: dict) -> dict:
        return build_bounded_skill_plan(skill, goal, world_state)

    def skill_transfer_scope_allows(self, skill: Skill, task_family: str) -> bool:
        """Keep learned skills inside their explicitly supported family scope."""
        family = str(task_family or "").strip().lower()
        scope = skill.transfer_scope if isinstance(skill.transfer_scope, dict) else {}
        unsupported = {
            str(item or "").strip().lower()
            for item in scope.get("unsupported_task_families", [])
            if str(item or "").strip()
        }
        if family in unsupported:
            return False
        supported = {
            str(item or "").strip().lower()
            for item in scope.get("supported_task_families", [])
            if str(item or "").strip()
        }
        explicit_family = str(scope.get("task_family") or skill.task_family or "").strip().lower()
        if explicit_family:
            supported.add(explicit_family)
        return bool(family and family in supported)

    def record_learned_skill_outcome(
        self,
        skill_id: str,
        success: bool,
        context: Optional[dict] = None,
        persist: Optional[bool] = None,
        regression_ledger_path: str = "",
    ) -> dict:
        """Record an attributed outcome and apply conservative demotion/quarantine rules."""
        skill = self.get_skill_by_id(skill_id)
        if not skill or skill.status == "builtin":
            return {"recorded": False, "reason": "learned_skill_not_found"}
        context = context if isinstance(context, dict) else {}
        previous_status = skill.status
        failure_type = str(context.get("failure_type") or "").strip().lower()
        attributable_failure = not success and failure_type in {
            "skill_error",
            "precondition_misclassification",
            "postcondition_failure",
        }
        if success:
            skill.success_count += 1
            skill.successful_uses += 1
        else:
            skill.observed_failure_count += 1
            failure_key = failure_type or "unattributed_failure"
            skill.failure_type_counts[failure_key] = int(skill.failure_type_counts.get(failure_key, 0) or 0) + 1
            if attributable_failure:
                skill.failure_count += 1
            if context:
                skill.failure_evidence.append(dict(context))
                skill.failure_evidence = skill.failure_evidence[-50:]
        skill.total_uses += 1
        skill.success_rate = skill.success_count / max(1, skill.success_count + skill.failure_count)
        skill.confidence_interval = wilson_confidence_interval(skill.success_count, skill.failure_count)
        skill.last_used = time.strftime("%Y-%m-%d")

        if attributable_failure and skill.status in {"executable", "advisory"}:
            repeated_transition = self._repeated_failed_transition_count(skill, context)
            if skill.failure_count >= 3 or repeated_transition >= 2:
                skill.status = "quarantined"
            elif skill.status == "executable" and skill.failure_count >= 2:
                skill.status = "advisory"
        event = {
            "timestamp": time.time(),
            "skill_id": skill.skill_id,
            "name": skill.name,
            "version": skill.version,
            "outcome": "success" if success else "failure",
            "failure_type": failure_type,
            "first_failed_transition": str(context.get("first_failed_transition") or ""),
            "previous_status": previous_status,
            "status": skill.status,
            "automatic_delete_allowed": False,
            "context": context,
        }
        skill.lifecycle_history.append(event)
        skill.lifecycle_history = skill.lifecycle_history[-100:]
        should_persist = self.persist if persist is None else persist
        if should_persist:
            self._rewrite_custom_skills()
        if regression_ledger_path and (not success or previous_status != skill.status):
            try:
                from singularity.core.skill_learning import SkillRegressionLedger

                SkillRegressionLedger(regression_ledger_path).record(event)
            except Exception as exc:
                logger.warning(f"Could not record skill regression event: {type(exc).__name__}")
        return {"recorded": True, "status_changed": previous_status != skill.status, **event}

    def reclassify_learned_skill_failure(
        self,
        skill_id: str,
        experiment_id: str,
        corrected_failure_type: str,
        reason: str,
        persist: Optional[bool] = None,
        regression_ledger_path: str = "",
    ) -> dict:
        """Correct an attribution label without deleting the original audit history."""
        skill = self.get_skill_by_id(skill_id)
        if not skill or skill.status == "builtin":
            return {"changed": False, "reason": "learned_skill_not_found"}
        match = next(
            (
                item for item in reversed(skill.failure_evidence)
                if str(item.get("experiment_id") or "") == str(experiment_id or "")
            ),
            None,
        )
        if match is None:
            return {"changed": False, "reason": "failure_evidence_not_found"}
        previous_type = str(match.get("failure_type") or "unattributed_failure")
        corrected = str(corrected_failure_type or "unattributed_failure").strip().lower()
        attributable = {"skill_error", "precondition_misclassification", "postcondition_failure"}
        if previous_type in attributable and corrected not in attributable:
            skill.failure_count = max(0, skill.failure_count - 1)
        elif previous_type not in attributable and corrected in attributable:
            skill.failure_count += 1
        previous_count = int(skill.failure_type_counts.get(previous_type, 0) or 0)
        if previous_count <= 1:
            skill.failure_type_counts.pop(previous_type, None)
        else:
            skill.failure_type_counts[previous_type] = previous_count - 1
        skill.failure_type_counts[corrected] = int(skill.failure_type_counts.get(corrected, 0) or 0) + 1
        match["original_failure_type"] = previous_type
        match["failure_type"] = corrected
        match["attribution_correction_reason"] = str(reason or "")[:300]
        skill.success_rate = skill.success_count / max(1, skill.success_count + skill.failure_count)
        skill.confidence_interval = wilson_confidence_interval(skill.success_count, skill.failure_count)
        event = {
            "timestamp": time.time(),
            "skill_id": skill.skill_id,
            "version": skill.version,
            "experiment_id": str(experiment_id or ""),
            "event": "failure_attribution_reclassified",
            "previous_failure_type": previous_type,
            "failure_type": corrected,
            "reason": str(reason or "")[:300],
            "status": skill.status,
            "automatic_delete_allowed": False,
        }
        skill.lifecycle_history.append(event)
        should_persist = self.persist if persist is None else persist
        if should_persist:
            self._rewrite_custom_skills()
        if regression_ledger_path:
            try:
                from singularity.core.skill_learning import SkillRegressionLedger

                SkillRegressionLedger(regression_ledger_path).record(event)
            except Exception as exc:
                logger.warning(f"Could not record attribution correction: {type(exc).__name__}")
        return {"changed": True, **event}

    def restore_quarantine_after_attribution_correction(
        self,
        skill_id: str,
        reason: str,
        evidence: Optional[dict] = None,
        persist: Optional[bool] = None,
        regression_ledger_path: str = "",
    ) -> dict:
        """Restore an approved executable version when corrected evidence clears attribution."""
        skill = self.get_skill_by_id(skill_id)
        if not skill or skill.status == "builtin":
            return {"changed": False, "reason": "learned_skill_not_found"}
        if skill.status != "quarantined":
            return {"changed": False, "reason": "quarantined_skill_required"}
        if skill.failure_count != 0:
            return {
                "changed": False,
                "reason": "attributable_failures_remain",
                "failure_count": skill.failure_count,
            }
        promotion_gate = (
            skill.gate.get("executable_promotion", {})
            if isinstance(skill.gate, dict)
            else {}
        )
        gate_matches = bool(
            promotion_gate.get("readiness") == "approved"
            and promotion_gate.get("decision") == "promote_executable"
            and str(promotion_gate.get("skill_id") or "") == skill.skill_id
            and str(promotion_gate.get("promoted_skill_version") or "") == skill.version
        )
        if not gate_matches:
            return {"changed": False, "reason": "approved_executable_gate_required"}
        correction_events = [
            item for item in skill.lifecycle_history
            if item.get("event") == "failure_attribution_reclassified"
            and str(item.get("failure_type") or "") not in {
                "skill_error",
                "precondition_misclassification",
                "postcondition_failure",
            }
        ]
        if not correction_events:
            return {"changed": False, "reason": "attribution_correction_evidence_required"}

        previous_status = skill.status
        skill.status = "executable"
        event = {
            "timestamp": time.time(),
            "skill_id": skill.skill_id,
            "version": skill.version,
            "event": "quarantine_restored_after_attribution_correction",
            "previous_status": previous_status,
            "status": skill.status,
            "reason": str(reason or "")[:300],
            "correction_experiment_ids": [
                str(item.get("experiment_id") or "") for item in correction_events
            ],
            "evidence": evidence or {},
            "automatic_delete_allowed": False,
        }
        skill.lifecycle_history.append(event)
        skill.lifecycle_history = skill.lifecycle_history[-100:]
        should_persist = self.persist if persist is None else persist
        if should_persist:
            self._rewrite_custom_skills()
        if regression_ledger_path:
            try:
                from singularity.core.skill_learning import SkillRegressionLedger

                SkillRegressionLedger(regression_ledger_path).record(event)
            except Exception as exc:
                logger.warning(f"Could not record quarantine restoration: {type(exc).__name__}")
        return {"changed": True, **event}

    def transition_skill_status(
        self,
        skill_id: str,
        target_status: str,
        reason: str,
        evidence: Optional[dict] = None,
        persist: Optional[bool] = None,
        promoted_version: str = "",
    ) -> dict:
        skill = self.get_skill_by_id(skill_id)
        target = str(target_status or "").strip().lower()
        allowed = {
            "candidate": {"advisory", "quarantined"},
            "advisory": {"executable", "quarantined"},
            "executable": {"advisory", "quarantined"},
            "quarantined": {"advisory"},
        }
        if not skill or skill.status == "builtin":
            return {"changed": False, "reason": "learned_skill_not_found"}
        if target not in allowed.get(skill.status, set()):
            return {"changed": False, "reason": "invalid_lifecycle_transition"}
        if target == "executable":
            requested_version = str(promoted_version or "").strip()
            if requested_version:
                if not re.fullmatch(r"\d+\.\d+\.\d+", requested_version):
                    return {"changed": False, "reason": "invalid_promoted_skill_version"}
                if self._version_key(requested_version) <= self._version_key(skill.version):
                    return {"changed": False, "reason": "promoted_skill_version_must_advance"}
                if any(
                    item.version == requested_version
                    for item in self.skill_versions(skill.skill_id or skill.name)
                ):
                    return {"changed": False, "reason": "promoted_skill_version_exists"}
            validation = validate_bounded_action_template(skill.bounded_action_template)
            if not validation.valid:
                return {"changed": False, "reason": "invalid_bounded_action_template", "issues": validation.issues}
            promotion_gate = evidence.get("executable_promotion_gate", evidence) if isinstance(evidence, dict) else {}
            gate_issues = executable_promotion_gate_issues(
                promotion_gate,
                skill_id=skill.skill_id,
                version=requested_version or skill.version,
            )
            if gate_issues:
                return {
                    "changed": False,
                    "reason": "paired_live_executable_promotion_gate_required",
                    "issues": gate_issues,
                }
        previous = skill.status
        previous_version = skill.version
        if target == "executable":
            self._skill_history[(skill.skill_id or skill.name, skill.version)] = deepcopy(skill)
            promoted = deepcopy(skill)
            promoted.version = requested_version or self._next_patch_version(skill.version)
            promoted.parent_version = skill.version
            promoted.rollback_target = skill.version
            promoted.status = "executable"
            promoted_gate = deepcopy(promotion_gate)
            promoted_gate["promoted_skill_version"] = promoted.version
            promoted.gate = {
                **(promoted.gate if isinstance(promoted.gate, dict) else {}),
                "readiness": "approved",
                "executable_promotion": promoted_gate,
            }
            self.skills[promoted.name] = promoted
            self._skill_history[(promoted.skill_id or promoted.name, promoted.version)] = promoted
            skill = promoted
        else:
            skill.status = target
        event = {
            "timestamp": time.time(),
            "skill_id": skill.skill_id,
            "version": skill.version,
            "previous_version": previous_version,
            "previous_status": previous,
            "status": target,
            "reason": str(reason or "")[:300],
            "evidence": evidence or {},
            "automatic_delete_allowed": False,
        }
        skill.lifecycle_history.append(event)
        should_persist = self.persist if persist is None else persist
        if should_persist:
            self._rewrite_custom_skills()
        return {"changed": True, "rollback_target": skill.rollback_target, **event}

    def rollback_skill_version(
        self,
        skill_id: str,
        target_version: str,
        reason: str,
        evidence: Optional[dict] = None,
        persist: Optional[bool] = None,
    ) -> dict:
        """Restore a historical contract as a new advisory version for revalidation."""
        current = self.get_skill_by_id(skill_id)
        target = next(
            (item for item in self.skill_versions(skill_id) if item.version == str(target_version)),
            None,
        )
        if current is None or target is None or current.status == "builtin":
            return {"changed": False, "reason": "rollback_target_not_found"}
        next_version = self._next_patch_version(current.version)
        payload = asdict(deepcopy(target))
        payload.update({
            "version": next_version,
            "status": "advisory",
            "parent_version": current.version,
            "rollback_target": target.version,
            "gate": {},
            "success_count": 0,
            "failure_count": 0,
            "observed_failure_count": 0,
            "failure_type_counts": {},
            "successful_uses": 0,
            "total_uses": 0,
            "success_rate": 0.0,
            "confidence_interval": wilson_confidence_interval(0, 0),
        })
        event = {
            "timestamp": time.time(),
            "skill_id": current.skill_id,
            "previous_version": current.version,
            "rollback_source_version": target.version,
            "version": next_version,
            "status": "advisory",
            "reason": str(reason or "")[:300],
            "evidence": evidence or {},
            "automatic_delete_allowed": False,
        }
        payload["lifecycle_history"] = list(payload.get("lifecycle_history", [])) + [event]
        name = payload.pop("name")
        description = payload.pop("description", "")
        implementation = payload.pop("implementation", "")
        restored = self.create_skill(
            name,
            description,
            implementation,
            persist=False,
            **payload,
        )
        should_persist = self.persist if persist is None else persist
        if should_persist:
            self._rewrite_custom_skills()
        return {"changed": True, "skill": restored, **event}

    def skill_postconditions_met(
        self,
        skill: Skill,
        world_state: dict,
        effective_postconditions: Optional[dict] = None,
    ) -> tuple[bool, list[str]]:
        contract = (
            {"postconditions": effective_postconditions}
            if isinstance(effective_postconditions, dict) and effective_postconditions
            else skill
        )
        return evaluate_skill_postconditions(contract, world_state)

    def apply_heldout_transfer_evidence(
        self,
        skill_id: str,
        report: dict,
        gate: dict,
        persist: Optional[bool] = None,
    ) -> dict:
        """Attach approved held-out evidence without widening the task family."""
        skill = self.get_skill_by_id(skill_id)
        if skill is None or skill.status != "executable":
            return {"changed": False, "reason": "executable_skill_required"}
        issues = []
        if report.get("type") != "skill_heldout_transfer_report":
            issues.append("heldout_report_type_invalid")
        if str(report.get("skill_id") or "") != skill.skill_id:
            issues.append("heldout_report_skill_mismatch")
        if report.get("positive_transfer") is not True or report.get("heldout") is not True:
            issues.append("positive_heldout_transfer_required")
        if report.get("fixed_controls_match") is not True:
            issues.append("heldout_controls_mismatch")
        if int(report.get("training_heldout_overlap_count", 0) or 0) != 0:
            issues.append("training_heldout_session_overlap")
        if report.get("errors"):
            issues.append("heldout_report_has_errors")
        if gate.get("type") != "task_stream_transfer_gate":
            issues.append("transfer_gate_type_invalid")
        if gate.get("readiness") != "approved" or gate.get("decision") != "allow_candidate_promotion":
            issues.append("transfer_gate_not_approved")
        if str(gate.get("target") or "") != f"skill:{skill.skill_id}":
            issues.append("transfer_gate_skill_mismatch")
        if str(gate.get("source_report_fingerprint") or "") != evidence_fingerprint(report):
            issues.append("transfer_report_fingerprint_mismatch")
        if issues:
            return {"changed": False, "reason": "heldout_transfer_gate_rejected", "issues": sorted(set(issues))}

        scope = deepcopy(skill.transfer_scope if isinstance(skill.transfer_scope, dict) else {})
        scope["heldout_validated"] = True
        scope["heldout_task_set"] = sorted(set(
            list(scope.get("heldout_task_set", []) or [])
            + list(report.get("heldout_transfer_task_set", []) or [])
        ))
        scope["heldout_session_ids"] = sorted(set(
            list(scope.get("heldout_session_ids", []) or [])
            + list(report.get("heldout_session_ids", []) or [])
        ))
        scope["unsupported_task_families"] = sorted(set(
            list(scope.get("unsupported_task_families", []) or [])
            + list(report.get("unsupported_task_family", []) or [])
        ))
        scope["transfer_gate_fingerprint"] = evidence_fingerprint(gate)
        scope["positive_transfer_step_gain"] = float(report.get("environment_step_gain", 0) or 0)
        skill.transfer_scope = scope
        event = {
            "timestamp": time.time(),
            "skill_id": skill.skill_id,
            "version": skill.version,
            "event": "heldout_transfer_validated",
            "heldout_session_ids": list(scope["heldout_session_ids"]),
            "transfer_gate_fingerprint": scope["transfer_gate_fingerprint"],
            "status": skill.status,
            "automatic_scope_widening_allowed": False,
        }
        skill.lifecycle_history.append(event)
        should_persist = self.persist if persist is None else persist
        if should_persist:
            self._rewrite_custom_skills()
        return {"changed": True, "skill": skill, **event}

    def _repeated_failed_transition_count(self, skill: Skill, context: dict) -> int:
        target = str(context.get("first_failed_transition") or "").strip()
        if not target:
            return 0
        return sum(
            1 for item in skill.failure_evidence
            if str(item.get("first_failed_transition") or "").strip() == target
        )

    def record_skill_memory(
        self,
        name: str,
        note: str,
        memory_type: str = "experience",
        outcome: str = "",
        task_family: str = "",
        source: str = "",
        confidence: float = 0.7,
        tags: Optional[list[str]] = None,
        transfer_gate: Optional[dict] = None,
        evidence: Optional[dict] = None,
        persist: Optional[bool] = None,
    ) -> Optional[dict]:
        """Attach a compact MUSE-style experience record to a reusable skill."""
        skill = self.skills.get(name)
        if not skill:
            return None
        if not task_family:
            task_family = self.infer_task_family(" ".join([name, skill.description, note]))
        record = self._normalize_skill_memory_record({
            "note": note,
            "type": memory_type,
            "outcome": outcome,
            "task_family": task_family,
            "source": source,
            "confidence": confidence,
            "tags": tags or [],
            "transfer_gate": transfer_gate or {},
            "evidence": evidence or {},
        })
        memory = self._normalized_skill_memory(skill)
        memory.append(record)
        skill.skill_memory = memory[-50:]
        should_persist = self.persist if persist is None else persist
        if should_persist and skill.name not in self._builtin_skill_names():
            self._rewrite_custom_skills()
        return record

    def get_recommended_skills(
        self,
        goal: str,
        world_state: dict,
        task_frontier: Optional[list[dict]] = None,
        use_frontier_router: bool = True,
        limit: int = 5,
    ) -> list[Skill]:
        """Return governed skills, preferring state-transition fit when a task frontier exists."""
        if use_frontier_router and task_frontier:
            route = self.get_frontier_skill_route(
                goal,
                world_state,
                task_frontier=task_frontier,
                limit=limit,
            )
            if route["skills"]:
                return route["skills"]
        skills = self._legacy_recommended_skills(goal, world_state, limit=limit)
        self.last_skill_router_trace = {
            "schema_version": 1,
            "profile": "legacy_skill_rank_v1",
            "frontier_task_count": len(task_frontier or []),
            "candidate_count": len(skills),
            "blocked_candidate_count": 0,
            "selected_skill_names": [skill.name for skill in skills],
            "covered_task_ids": [],
            "uncovered_task_ids": [
                str(task.get("id") or "")
                for task in (task_frontier or [])
                if isinstance(task, dict) and task.get("id")
            ],
            "selected": [],
        }
        return skills

    def _legacy_recommended_skills(self, goal: str, world_state: dict, limit: int = 5) -> list[Skill]:
        """Preserve the pre-router ranking as a fixed-control baseline."""
        scored: dict[str, tuple[float, Skill]] = {}
        builtin_names = self._builtin_skill_names()
        task_family = self.infer_task_family(goal, {})
        for skill in self.skills.values():
            if skill.name not in builtin_names and skill.status not in {"advisory", "executable"}:
                continue
            if not self._runtime_default_skill_allowed(skill.name, task_family, built_in=skill.name in builtin_names):
                continue
            if skill.total_uses > 0:
                scored[skill.name] = (skill.success_rate + min(1.0, skill.total_uses * 0.05), skill)
        for skill in self._policy_skills(goal, world_state):
            score = self._policy_relevance_score(skill, goal, world_state) + 1.0
            previous = scored.get(skill.name)
            if previous is None or score > previous[0]:
                scored[skill.name] = (score, skill)
        for profile in self._skill_contract_profiles(goal, world_state, limit=0):
            if profile["score"] <= 0 or profile["readiness"] == "blocked":
                continue
            skill = self.skills.get(profile["name"])
            if not skill:
                continue
            if not self._runtime_default_skill_allowed(skill.name, task_family, built_in=skill.name in builtin_names):
                continue
            previous = scored.get(skill.name)
            if previous is None or profile["score"] > previous[0]:
                scored[skill.name] = (profile["score"], skill)
        ranked = sorted(
            scored.values(),
            key=lambda item: (item[0], item[1].success_rate, item[1].total_uses),
            reverse=True,
        )
        return [skill for _, skill in ranked[:max(1, int(limit or 5))]]

    def get_frontier_skill_route(
        self,
        goal: str,
        world_state: dict,
        task_frontier: list[dict],
        limit: int = 5,
    ) -> dict:
        """Rerank skills against decomposed task intervals and unresolved state transitions."""
        tasks = [
            self._normalize_skill_frontier_task(task, index)
            for index, task in enumerate(task_frontier or [], start=1)
            if isinstance(task, dict)
        ]
        tasks = [task for task in tasks if task]
        builtin_names = self._builtin_skill_names()
        frontier_families = {
            self.infer_task_family(task["text"], {}) for task in tasks
        } or {"general"}
        candidates = []
        blocked_candidate_count = 0
        for skill in self.skills.values():
            built_in = skill.name in builtin_names
            if not built_in and skill.status not in {"advisory", "executable"}:
                blocked_candidate_count += 1
                continue
            allowed = built_in or any(
                self._runtime_default_skill_allowed(skill.name, family, built_in=False)
                for family in frontier_families
            )
            if not allowed:
                blocked_candidate_count += 1
                continue
            candidate = self._frontier_skill_candidate(
                skill,
                goal,
                world_state or {},
                tasks,
                built_in=built_in,
            )
            if candidate.get("blocked"):
                blocked_candidate_count += 1
                continue
            if candidate.get("score", 0.0) > 0:
                candidates.append(candidate)

        candidates.sort(
            key=lambda item: (
                item["score"],
                item["gap_match_count"],
                item["assigned_match_count"],
                item["reliability"],
                item["total_uses"],
                item["skill_name"],
            ),
            reverse=True,
        )
        selected_candidates = candidates[:max(1, int(limit or 5))]
        selected_skills = [
            self.skills[item["skill_name"]]
            for item in selected_candidates
            if item["skill_name"] in self.skills
        ]
        covered_task_ids = sorted({
            task_id
            for item in selected_candidates
            for task_id in item["covered_task_ids"]
            if task_id
        })
        frontier_ids = [task["id"] for task in tasks if task["id"]]
        uncovered_task_ids = [task_id for task_id in frontier_ids if task_id not in covered_task_ids]
        trace_candidates = [self._skill_router_trace_candidate(item) for item in selected_candidates]
        self.last_skill_router_trace = {
            "schema_version": 1,
            "profile": "frontier_transition_skill_router_v1",
            "frontier_task_count": len(tasks),
            "ready_task_count": sum(1 for task in tasks if task["ready"]),
            "blocked_task_count": sum(1 for task in tasks if not task["ready"]),
            "candidate_count": len(candidates),
            "blocked_candidate_count": blocked_candidate_count,
            "selected_skill_names": [skill.name for skill in selected_skills],
            "covered_task_ids": covered_task_ids,
            "uncovered_task_ids": uncovered_task_ids,
            "selected": trace_candidates,
        }
        return {
            "skills": selected_skills,
            "trace": self.get_last_skill_router_trace(),
        }

    def get_last_skill_router_trace(self) -> dict:
        trace = dict(self.last_skill_router_trace)
        trace["selected_skill_names"] = list(trace.get("selected_skill_names", []))
        trace["covered_task_ids"] = list(trace.get("covered_task_ids", []))
        trace["uncovered_task_ids"] = list(trace.get("uncovered_task_ids", []))
        trace["selected"] = [dict(item) for item in trace.get("selected", []) if isinstance(item, dict)]
        return trace

    def format_frontier_skill_route(
        self,
        trace: Optional[dict] = None,
        limit: int = 5,
        char_budget: int = 600,
    ) -> str:
        """Format a compact planner hint from a sanitized skill-route trace."""
        trace = trace if isinstance(trace, dict) else self.last_skill_router_trace
        if trace.get("profile") != "frontier_transition_skill_router_v1":
            return ""
        lines = ["Frontier skill route (state-transition fit; verifier still controls actions):"]
        for item in trace.get("selected", [])[:max(1, int(limit or 5))]:
            if not isinstance(item, dict):
                continue
            parts = [
                f"- {item.get('skill_name', 'skill')} score={item.get('score', 0.0):.2f}",
            ]
            if item.get("covered_task_ids"):
                parts.append("covers=" + ",".join(item["covered_task_ids"][:3]))
            if item.get("gap_terms"):
                parts.append("closes=" + ",".join(item["gap_terms"][:4]))
            if item.get("reason_codes"):
                parts.append("why=" + ",".join(item["reason_codes"][:4]))
            lines.append(" ".join(parts))
        if len(lines) <= 1:
            return ""
        try:
            budget = max(0, int(char_budget))
        except (TypeError, ValueError):
            budget = 600
        packed = []
        used = 0
        for line in lines:
            separator = 1 if packed else 0
            if used + separator + len(line) > budget:
                break
            packed.append(line)
            used += separator + len(line)
        return "\n".join(packed) if len(packed) > 1 else ""

    def _normalize_skill_frontier_task(self, task: dict, index: int) -> dict:
        task_id = str(task.get("id") or f"frontier-{index}")[:64]
        title = str(task.get("title") or task.get("name") or "")[:160]
        task_type = str(task.get("type") or "general")[:64]
        tags = task.get("tags", []) if isinstance(task.get("tags", []), list) else []
        triggers = task.get("opportunity_triggers", [])
        triggers = triggers if isinstance(triggers, list) else []
        missing = task.get("missing_preconditions", {})
        missing = missing if isinstance(missing, dict) else {}
        success = task.get("success_criteria", {})
        success = success if isinstance(success, dict) else {}
        preconditions = task.get("preconditions", {})
        preconditions = preconditions if isinstance(preconditions, dict) else {}
        assigned_skill = str(task.get("assigned_skill") or "")[:96]
        text = " ".join([
            title,
            task_type,
            " ".join(str(value) for value in tags[:8]),
            " ".join(str(value) for value in triggers[:8]),
            str(task.get("rationale") or "")[:240],
        ])
        return {
            "id": task_id,
            "title": title,
            "type": task_type,
            "text": text,
            "terms": self._skill_route_terms(text),
            "gap_terms": self._skill_route_terms(json.dumps(missing, sort_keys=True, default=str)),
            "target_terms": self._skill_route_terms(json.dumps(success, sort_keys=True, default=str)),
            "precondition_terms": self._skill_route_terms(json.dumps(preconditions, sort_keys=True, default=str)),
            "assigned_skill": assigned_skill,
            "ready": task.get("ready") is True,
            "priority": self._skill_route_priority(task.get("priority", 3)),
        }

    def _frontier_skill_candidate(
        self,
        skill: Skill,
        goal: str,
        world_state: dict,
        tasks: list[dict],
        built_in: bool,
    ) -> dict:
        contract = self._skill_contract_profile(skill, goal, world_state)
        if contract.get("readiness") == "blocked":
            return {"blocked": True, "skill_name": skill.name}
        capability_terms = self._skill_route_terms(" ".join([
            skill.name,
            skill.description,
            json.dumps(skill.parameters, sort_keys=True, default=str),
            json.dumps(skill.postconditions, sort_keys=True, default=str),
            str(skill.implementation or "")[:4000],
        ]))
        postcondition_terms = self._skill_route_terms(
            json.dumps(skill.postconditions, sort_keys=True, default=str)
        )
        skill_family = self.infer_task_family(" ".join([skill.name, skill.description]), {})
        task_matches = []
        all_gap_terms = set()
        reason_codes = set()
        assigned_match_count = 0
        gap_match_count = 0
        for task in tasks:
            assigned_match = bool(
                task["assigned_skill"]
                and task["assigned_skill"].casefold() == skill.name.casefold()
            )
            text_matches = sorted(task["terms"] & capability_terms)
            gap_matches = sorted(task["gap_terms"] & capability_terms)
            target_matches = sorted(task["target_terms"] & (postcondition_terms or capability_terms))
            task_family = self.infer_task_family(task["text"], {})
            family_match = bool(task_family != "general" and task_family == skill_family)
            score = 0.0
            if assigned_match:
                score += 14.0
                assigned_match_count += 1
                reason_codes.add("assigned_skill")
            if gap_matches:
                score += min(18.0, len(gap_matches) * 7.0)
                gap_match_count += len(gap_matches)
                all_gap_terms.update(gap_matches)
                reason_codes.add("closes_frontier_gap")
            if target_matches:
                score += min(10.0, len(target_matches) * 4.0)
                reason_codes.add("matches_target_state")
            if text_matches:
                score += min(6.0, len(text_matches) * 1.2)
                reason_codes.add("matches_task_interval")
            if family_match:
                score += 2.0
                reason_codes.add("task_family_match")
            if task["ready"]:
                score += 0.5
            score += max(0.0, (5 - task["priority"]) * 0.15)
            substantive_match = bool(
                assigned_match or gap_matches or target_matches or text_matches
            )
            if substantive_match and score >= 2.0:
                task_matches.append({"id": task["id"], "score": round(score, 4)})

        task_matches.sort(key=lambda item: (item["score"], item["id"]), reverse=True)
        best_score = task_matches[0]["score"] if task_matches else 0.0
        coverage_bonus = sum(item["score"] for item in task_matches[1:]) * 0.2
        reliability = round(
            (float(skill.successful_uses or 0) + 1.0) / (float(skill.total_uses or 0) + 2.0),
            4,
        )
        governance = self._skill_governance(skill, built_in=built_in)
        governance_bonus = 0.5 if built_in else 1.0 if governance.get("gate_readiness") == "approved" else 0.0
        readiness_penalty = 0.75 if contract.get("readiness") == "review" else 0.0
        score = 0.0
        if task_matches:
            score = max(0.0, best_score + coverage_bonus + reliability + governance_bonus - readiness_penalty)
        if skill.total_uses:
            reason_codes.add("empirical_reliability")
        if governance_bonus:
            reason_codes.add("governed_skill")
        return {
            "blocked": False,
            "skill_name": skill.name,
            "score": round(score, 4),
            "reliability": reliability,
            "total_uses": int(skill.total_uses or 0),
            "readiness": contract.get("readiness", ""),
            "assigned_match_count": assigned_match_count,
            "gap_match_count": gap_match_count,
            "gap_terms": sorted(all_gap_terms)[:8],
            "covered_task_ids": [item["id"] for item in task_matches],
            "reason_codes": sorted(reason_codes),
        }

    def _skill_router_trace_candidate(self, candidate: dict) -> dict:
        return {
            "skill_name": str(candidate.get("skill_name") or "")[:96],
            "score": round(float(candidate.get("score", 0.0) or 0.0), 4),
            "reliability": round(float(candidate.get("reliability", 0.0) or 0.0), 4),
            "readiness": str(candidate.get("readiness") or "")[:24],
            "assigned_match_count": int(candidate.get("assigned_match_count", 0) or 0),
            "gap_match_count": int(candidate.get("gap_match_count", 0) or 0),
            "gap_terms": [str(value)[:48] for value in candidate.get("gap_terms", [])[:8]],
            "covered_task_ids": [str(value)[:64] for value in candidate.get("covered_task_ids", [])[:8]],
            "reason_codes": [str(value)[:48] for value in candidate.get("reason_codes", [])[:8]],
        }

    def _skill_route_terms(self, value) -> set[str]:
        base = self._keywords(str(value or ""))
        expanded = set(base)
        for token in list(base):
            expanded.update(part for part in token.split("_") if len(part) > 2)
        aliases = {
            "logs": {"log", "wood"},
            "log": {"wood"},
            "planks": {"plank", "wood"},
            "plank": {"wood"},
            "cobblestone": {"stone"},
            "wooden": {"wood"},
            "mining": {"mine"},
            "crafting": {"craft"},
            "building": {"build"},
            "navigation": {"navigate"},
        }
        for token in list(expanded):
            expanded.update(aliases.get(token, set()))
            if token.endswith("s") and len(token) > 4:
                expanded.add(token[:-1])
        return expanded

    def _skill_route_priority(self, value) -> int:
        try:
            return max(0, min(5, int(value)))
        except (TypeError, ValueError):
            return 3

    def get_policy_skill_hints(self, goal: str, world_state: dict, limit: int = 5) -> list[str]:
        """Return concise online hints from approved causal/failure-correction skills."""
        hints = []
        for skill in self._policy_skills(goal, world_state):
            payload = self._implementation_payload(skill)
            if payload.get("type") == "causal_summary_skill":
                action = payload.get("action_template", {})
                hints.append(
                    f"{skill.name}: prefer {self._format_action(action)} when context matches learned causal evidence"
                )
            elif payload.get("type") == "failure_correction_skill":
                avoid = payload.get("avoid_action_template", {})
                sequence = payload.get("correction_sequence", [])
                hints.append(
                    f"{skill.name}: if {self._format_action(avoid)} fails, try "
                    f"{' -> '.join(self._format_action(action) for action in sequence[:4])}"
                )
            if len(hints) >= limit:
                break
        return hints

    def get_skill_memory_hints(self, goal: str = "", task_family: str = "", limit: int = 5) -> list[str]:
        """Return concise skill-local memories that can guide planning."""
        visible = self._ranked_skill_memory_hint_candidates(goal=goal, task_family=task_family, limit=limit)
        return [self._format_skill_memory_hint(candidate) for candidate in visible]

    def skill_memory_quality_ablation(self, feedback: dict, cases: list[dict], limit: int = 5) -> dict:
        """Compare skill-memory hint ranking before and after quality feedback."""
        cases = self._normalize_skill_memory_ablation_cases(cases)
        original_feedback = dict(self._skill_memory_quality_feedback)
        original_policies = {key: dict(value) for key, value in self._skill_memory_quality_policies.items()}
        original_items = {key: dict(value) for key, value in self._skill_memory_quality_items.items()}
        original_runtime_profile = json.loads(json.dumps(self._runtime_default_gate_profile, default=str))
        results = []
        try:
            evaluation_candidates = [
                {
                    "skill": skill.name,
                    "task_family": skill.task_family or "",
                    "candidate_readiness": "approved",
                }
                for skill in self.skills.values()
                if skill.name not in self._builtin_skill_names()
                and skill.status in {"advisory", "executable"}
            ]
            if evaluation_candidates:
                self.record_skill_runtime_default_gate({
                    "readiness": "approved",
                    "decision": "allow_offline_quality_ablation_only",
                    "candidates": evaluation_candidates,
                })
            self._clear_skill_memory_quality_feedback()
            for index, case in enumerate(cases, start=1):
                goal = case.get("goal", "")
                task_family = case.get("task_family", "")
                baseline = self._skill_memory_candidate_records(goal, task_family, limit)
                self.record_skill_memory_quality_feedback(feedback or {})
                adjusted = self._skill_memory_candidate_records(goal, task_family, limit)
                self._clear_skill_memory_quality_feedback()
                results.append(self._skill_memory_ablation_case_result(index, case, baseline, adjusted))
        finally:
            self._skill_memory_quality_feedback = original_feedback
            self._skill_memory_quality_policies = original_policies
            self._skill_memory_quality_items = original_items
            self._runtime_default_gate_profile = original_runtime_profile
        return {
            "case_count": len(results),
            "changed_count": sum(1 for case in results if case["changed"]),
            "quality_policy_application_count": sum(case["quality_policy_application_count"] for case in results),
            "promoted_count": sum(len(case["promoted"]) for case in results),
            "demoted_count": sum(len(case["demoted"]) for case in results),
            "cases": results,
        }

    def record_skill_memory_quality_feedback(self, feedback: dict) -> int:
        """Store offline hint-quality feedback for future runtime retrieval ranking."""
        if not isinstance(feedback, dict):
            return 0
        self._skill_memory_quality_feedback = dict(feedback)
        self._skill_memory_quality_policies = {}
        self._skill_memory_quality_items = {}
        stored = 0
        for hint in feedback.get("policy_hints", []):
            if not isinstance(hint, dict):
                continue
            policy = str(hint.get("skill_memory_policy") or hint.get("policy") or "").strip()
            if not policy:
                continue
            self._skill_memory_quality_policies[policy] = dict(hint)
            stored += 1
        for item in feedback.get("hint_quality_items", []):
            if not isinstance(item, dict):
                continue
            key = self._skill_memory_quality_item_key(
                item.get("hint_type"),
                item.get("skill"),
                item.get("task_family"),
            )
            if key[0] == "UNKNOWN" or key[1] == "unknown":
                continue
            self._skill_memory_quality_items[key] = dict(item)
        return stored

    def _clear_skill_memory_quality_feedback(self):
        self._skill_memory_quality_feedback = {}
        self._skill_memory_quality_policies = {}
        self._skill_memory_quality_items = {}

    def skill_memory_quality_profile(self) -> dict:
        """Return loaded skill-memory quality feedback summary."""
        return {
            "policy_hints": sorted(self._skill_memory_quality_policies),
            "quality_label_counts": dict(self._skill_memory_quality_feedback.get("quality_label_counts", {}))
            if isinstance(self._skill_memory_quality_feedback, dict)
            else {},
            "hint_type_counts": dict(self._skill_memory_quality_feedback.get("hint_type_counts", {}))
            if isinstance(self._skill_memory_quality_feedback, dict)
            else {},
            "task_family_counts": dict(self._skill_memory_quality_feedback.get("task_family_counts", {}))
            if isinstance(self._skill_memory_quality_feedback, dict)
            else {},
            "hint_quality_items": list(self._skill_memory_quality_items.values()),
        }

    def record_skill_runtime_default_gate(self, gate: dict) -> int:
        """Load a runtime-default gate profile for learned skill influence."""
        if not isinstance(gate, dict):
            return 0
        readiness = str(gate.get("readiness") or "").strip().lower() or "unknown"
        profile = self._runtime_default_gate_profile
        if not profile.get("gate_required"):
            profile = self._empty_runtime_default_gate_profile()
            profile["gate_required"] = True
            profile["gate_approved"] = True
            profile["gate_readiness"] = "approved"
        profile["paths"].extend(str(path) for path in gate.get("paths", []) if path)
        profile["target_task_family"] = (
            str(gate.get("target_task_family") or profile.get("target_task_family") or "")
            .strip()
            .lower()
        )
        profile["decision"] = str(gate.get("decision") or profile.get("decision") or "").strip()
        profile["reason"] = str(gate.get("reason") or profile.get("reason") or "").strip()
        if readiness != "approved":
            profile["gate_approved"] = False
            profile["gate_readiness"] = readiness
            self._runtime_default_gate_profile = profile
            return 0

        added = 0
        for candidate in gate.get("candidates", []) if isinstance(gate.get("candidates", []), list) else []:
            if not isinstance(candidate, dict):
                continue
            candidate_readiness = str(candidate.get("candidate_readiness") or candidate.get("readiness") or "").lower()
            if candidate_readiness != "approved":
                bucket = "rejected_skills" if candidate_readiness == "rejected" else "review_skills"
                name = str(candidate.get("skill") or "").strip()
                if name and name not in profile[bucket]:
                    profile[bucket].append(name)
                continue
            name = str(candidate.get("skill") or "").strip()
            if not name:
                continue
            family = str(candidate.get("task_family") or gate.get("target_task_family") or "").strip().lower()
            if name not in profile["approved_skills"]:
                profile["approved_skills"].append(name)
                added += 1
            families = profile["approved_skill_families"].setdefault(name, [])
            if family not in families:
                families.append(family)
            family_skills = profile["approved_family_skills"].setdefault(family, [])
            if name not in family_skills:
                family_skills.append(name)
            fingerprint = str(candidate.get("promotion_gate_fingerprint") or "").strip().lower()
            if fingerprint:
                fingerprints = profile["approved_skill_promotion_fingerprints"].setdefault(name, [])
                if fingerprint not in fingerprints:
                    fingerprints.append(fingerprint)

        profile["gate_readiness"] = "approved" if profile.get("gate_approved", True) else profile.get("gate_readiness", "review")
        for key in ("approved_skills", "review_skills", "rejected_skills"):
            profile[key] = sorted(profile.get(key, []))
        for key in (
            "approved_skill_families",
            "approved_family_skills",
            "approved_skill_promotion_fingerprints",
        ):
            profile[key] = {
                name: sorted(values)
                for name, values in sorted(profile.get(key, {}).items())
            }
        self._runtime_default_gate_profile = profile
        return added

    def skill_runtime_default_profile(self) -> dict:
        """Return the active runtime-default gate profile."""
        profile = self._runtime_default_gate_profile
        return {
            "gate_required": bool(profile.get("gate_required", False)),
            "gate_approved": bool(profile.get("gate_approved", True)),
            "gate_readiness": str(profile.get("gate_readiness", "not_required")),
            "target_task_family": str(profile.get("target_task_family", "")),
            "approved_skills": list(profile.get("approved_skills", [])),
            "approved_skill_families": {
                name: list(values)
                for name, values in profile.get("approved_skill_families", {}).items()
            },
            "approved_family_skills": {
                family: list(values)
                for family, values in profile.get("approved_family_skills", {}).items()
            },
            "approved_skill_promotion_fingerprints": {
                name: list(values)
                for name, values in profile.get("approved_skill_promotion_fingerprints", {}).items()
            },
            "review_skills": list(profile.get("review_skills", [])),
            "rejected_skills": list(profile.get("rejected_skills", [])),
            "decision": str(profile.get("decision", "")),
            "reason": str(profile.get("reason", "")),
        }

    def _empty_runtime_default_gate_profile(self) -> dict:
        return {
            "gate_required": False,
            "gate_approved": True,
            "gate_readiness": "not_required",
            "target_task_family": "",
            "decision": "",
            "reason": "",
            "paths": [],
            "approved_skills": [],
            "approved_skill_families": {},
            "approved_family_skills": {},
            "approved_skill_promotion_fingerprints": {},
            "review_skills": [],
            "rejected_skills": [],
        }

    def record_skill_retirement_gate(self, gate: dict) -> int:
        """Apply an approved soft-retirement gate as an in-memory overlay only."""
        if not isinstance(gate, dict):
            return 0
        readiness = str(gate.get("readiness") or "unknown").strip().lower()
        profile = self._skill_retirement_profile
        profile["gate_required"] = True
        profile["gate_readiness"] = readiness
        profile["decision"] = str(gate.get("decision") or "").strip()
        profile["reason"] = str(gate.get("reason") or "").strip()
        paths = gate.get("paths", [])
        paths = paths if isinstance(paths, (list, tuple)) else [paths]
        profile["paths"].extend(str(path) for path in paths if path)
        profile["automatic_delete_allowed"] = False

        candidates = gate.get("candidates", []) if isinstance(gate.get("candidates"), list) else []
        thresholds = gate.get("thresholds", {}) if isinstance(gate.get("thresholds"), dict) else {}
        if (
            readiness != "approved"
            or gate.get("type") != "skill_retirement_gate"
            or gate.get("schema_version") != 1
            or gate.get("soft_quarantine_allowed") is not True
            or gate.get("automatic_delete_allowed") is not False
            or gate.get("deletion_policy") != "prohibited"
            or thresholds.get("require_live_evidence") is not True
        ):
            profile["gate_approved"] = False
            for candidate in candidates:
                if not isinstance(candidate, dict):
                    continue
                name = str(candidate.get("skill") or "").strip()
                if name and name not in profile["review_skills"]:
                    profile["review_skills"].append(name)
            profile["review_skills"] = sorted(profile["review_skills"])
            return 0

        profile["gate_approved"] = True
        added = 0
        builtin_names = self._builtin_skill_names()
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            name = str(candidate.get("skill") or "").strip()
            candidate_readiness = str(candidate.get("candidate_readiness") or "").strip().lower()
            if not name or name in builtin_names:
                continue
            candidate_safe = (
                candidate_readiness == "approved"
                and candidate.get("automatic_delete_allowed") is False
                and not candidate.get("issues")
                and bool(candidate.get("candidate_session_ids"))
                and bool(candidate.get("judge_ids"))
                and bool(candidate.get("verifier_ids"))
            )
            if not candidate_safe:
                if name not in profile["review_skills"]:
                    profile["review_skills"].append(name)
                continue
            family = str(candidate.get("task_family") or "").strip().lower()
            if name not in profile["quarantined_skills"]:
                profile["quarantined_skills"].append(name)
                added += 1
            families = profile["quarantined_skill_families"].setdefault(name, [])
            if family not in families:
                families.append(family)
            family_skills = profile["quarantined_family_skills"].setdefault(family, [])
            if name not in family_skills:
                family_skills.append(name)

        for key in ("quarantined_skills", "review_skills"):
            profile[key] = sorted(profile[key])
        for key in ("quarantined_skill_families", "quarantined_family_skills"):
            profile[key] = {
                name: sorted(values)
                for name, values in sorted(profile[key].items())
            }
        return added

    def skill_retirement_profile(self) -> dict:
        """Return the active runtime-only soft-retirement overlay."""
        profile = self._skill_retirement_profile
        return {
            "gate_required": bool(profile.get("gate_required", False)),
            "gate_approved": bool(profile.get("gate_approved", False)),
            "gate_readiness": str(profile.get("gate_readiness", "not_required")),
            "quarantined_skills": list(profile.get("quarantined_skills", [])),
            "quarantined_skill_families": {
                name: list(values)
                for name, values in profile.get("quarantined_skill_families", {}).items()
            },
            "quarantined_family_skills": {
                family: list(values)
                for family, values in profile.get("quarantined_family_skills", {}).items()
            },
            "review_skills": list(profile.get("review_skills", [])),
            "automatic_delete_allowed": False,
            "decision": str(profile.get("decision", "")),
            "reason": str(profile.get("reason", "")),
        }

    def _empty_skill_retirement_profile(self) -> dict:
        return {
            "gate_required": False,
            "gate_approved": False,
            "gate_readiness": "not_required",
            "decision": "",
            "reason": "",
            "paths": [],
            "quarantined_skills": [],
            "quarantined_skill_families": {},
            "quarantined_family_skills": {},
            "review_skills": [],
            "automatic_delete_allowed": False,
        }

    def _skill_retirement_allowed(self, skill_name: str, task_family: str = "", built_in: bool = False) -> bool:
        if built_in:
            return True
        name = str(skill_name or "").strip()
        if not name:
            return False
        families = self._skill_retirement_profile.get("quarantined_skill_families", {}).get(name, [])
        if not families:
            return True
        family = str(task_family or "").strip().lower()
        return "" not in families and family not in families

    def _runtime_default_skill_allowed(
        self,
        skill_name: str,
        task_family: str = "",
        built_in: bool = False,
        promotion_gate_fingerprint: str = "",
    ) -> bool:
        if built_in:
            return True
        if not self._skill_retirement_allowed(skill_name, task_family, built_in=False):
            return False
        profile = self._runtime_default_gate_profile
        if not profile.get("gate_required"):
            return False
        if not profile.get("gate_approved"):
            return False
        name = str(skill_name or "").strip()
        if not name:
            return False
        families = profile.get("approved_skill_families", {}).get(name, [])
        if not families:
            return False
        family = str(task_family or "").strip().lower()
        if "" not in families and family not in families:
            return False
        expected_fingerprint = str(promotion_gate_fingerprint or "").strip().lower()
        if expected_fingerprint:
            approved = profile.get("approved_skill_promotion_fingerprints", {}).get(name, [])
            return expected_fingerprint in approved
        return True

    def _skill_memory_hint_candidates(self, goal: str = "", task_family: str = "") -> list[dict]:
        family_filter = str(task_family or "").strip().lower()
        goal_tokens = self._keywords(goal)
        builtin_names = self._builtin_skill_names()
        candidates = []
        for skill in self.skills.values():
            if skill.name not in builtin_names and skill.status not in {"advisory", "executable"}:
                continue
            governance = self._skill_governance(skill, built_in=skill.name in builtin_names)
            for memory in self._normalized_skill_memory(skill):
                note = memory.get("note", "")
                if not note:
                    continue
                memory_family = str(memory.get("task_family") or "").strip().lower()
                if family_filter and memory_family != family_filter:
                    continue
                if not self._runtime_default_skill_allowed(
                    skill.name,
                    memory_family or family_filter,
                    built_in=skill.name in builtin_names,
                ):
                    continue
                hint_type = self._skill_memory_hint_type(memory, governance)
                confidence = float(memory.get("confidence", 0.0) or 0.0)
                transfer_readiness = str(memory.get("transfer_readiness") or "").strip().lower()
                score = self._skill_memory_goal_score(goal_tokens, skill, memory)
                if family_filter and memory_family == family_filter:
                    score += 3.0
                elif not family_filter and memory_family:
                    score += 0.5
                if transfer_readiness == "approved":
                    score += 1.0
                elif transfer_readiness in {"review", "rejected", "error"}:
                    score -= 0.4
                score += confidence
                quality = self._skill_memory_quality_adjustment(hint_type, memory_family, skill.name)
                candidates.append({
                    "skill_name": skill.name,
                    "hint_type": hint_type,
                    "hint_rank": {"REUSE": 2.0, "AVOID": 1.0, "REVIEW_ONLY": 0.0}.get(hint_type, 0.0)
                    + quality["rank_delta"],
                    "score": round(score + quality["score_delta"], 4),
                    "confidence": confidence,
                    "timestamp": memory.get("timestamp", ""),
                    "transfer_readiness": transfer_readiness,
                    "quality_policies": quality["policies"],
                    "memory": memory,
                })
        return candidates

    def _ranked_skill_memory_hint_candidates(self, goal: str = "", task_family: str = "", limit: int = 5) -> list[dict]:
        candidates = self._skill_memory_hint_candidates(goal=goal, task_family=task_family)
        candidates.sort(
            key=lambda item: (
                item["hint_rank"],
                item["score"],
                item["confidence"],
                item["timestamp"],
            ),
            reverse=True,
        )
        return candidates[:limit] if limit and limit > 0 else candidates

    def _skill_memory_candidate_records(self, goal: str, task_family: str, limit: int = 5) -> list[dict]:
        records = []
        for rank, candidate in enumerate(
            self._ranked_skill_memory_hint_candidates(goal=goal, task_family=task_family, limit=limit),
            start=1,
        ):
            memory = candidate.get("memory", {})
            records.append({
                "rank": rank,
                "key": self._skill_memory_candidate_key(candidate),
                "hint": self._format_skill_memory_hint(candidate),
                "hint_type": candidate.get("hint_type", "UNKNOWN"),
                "skill": candidate.get("skill_name", "unknown"),
                "task_family": memory.get("task_family", ""),
                "score": candidate.get("score", 0.0),
                "hint_rank": candidate.get("hint_rank", 0.0),
                "confidence": candidate.get("confidence", 0.0),
                "quality_policies": list(candidate.get("quality_policies", [])),
                "note": memory.get("note", ""),
            })
        return records

    def _skill_memory_candidate_key(self, candidate: dict) -> str:
        memory = candidate.get("memory", {})
        return "|".join([
            str(candidate.get("hint_type", "UNKNOWN")),
            str(candidate.get("skill_name", "unknown")),
            str(memory.get("task_family", "")),
            str(memory.get("note", "")),
        ])

    def _skill_memory_ablation_case_result(
        self,
        index: int,
        case: dict,
        baseline: list[dict],
        adjusted: list[dict],
    ) -> dict:
        baseline_ranks = {item["key"]: item["rank"] for item in baseline}
        adjusted_ranks = {item["key"]: item["rank"] for item in adjusted}
        promoted = []
        demoted = []
        for item in adjusted:
            previous_rank = baseline_ranks.get(item["key"])
            if previous_rank is None:
                promoted.append({**item, "baseline_rank": None, "adjusted_rank": item["rank"]})
            elif item["rank"] < previous_rank:
                promoted.append({**item, "baseline_rank": previous_rank, "adjusted_rank": item["rank"]})
            elif item["rank"] > previous_rank:
                demoted.append({**item, "baseline_rank": previous_rank, "adjusted_rank": item["rank"]})
        for item in baseline:
            adjusted_rank = adjusted_ranks.get(item["key"])
            if adjusted_rank is not None and adjusted_rank > item["rank"]:
                demoted.append({**item, "baseline_rank": item["rank"], "adjusted_rank": adjusted_rank})
        return {
            "id": case.get("id") or f"case_{index}",
            "goal": case.get("goal", ""),
            "task_family": case.get("task_family", ""),
            "changed": (
                [item["key"] for item in baseline] != [item["key"] for item in adjusted]
                or any(item["quality_policies"] for item in adjusted)
            ),
            "quality_policy_application_count": sum(1 for item in adjusted if item["quality_policies"]),
            "baseline_hints": baseline,
            "adjusted_hints": adjusted,
            "promoted": self._dedupe_rank_changes(promoted),
            "demoted": self._dedupe_rank_changes(demoted),
        }

    def _normalize_skill_memory_ablation_cases(self, cases: list[dict]) -> list[dict]:
        normalized = []
        for index, case in enumerate(cases or [], start=1):
            if not isinstance(case, dict):
                continue
            goal = str(case.get("goal") or case.get("query") or "").strip()
            task_family = str(case.get("task_family") or case.get("family") or "").strip().lower()
            normalized.append({
                "id": str(case.get("id") or f"case_{index}"),
                "goal": goal,
                "task_family": task_family,
            })
        return normalized or [{"id": "case_1", "goal": "", "task_family": ""}]

    def _dedupe_rank_changes(self, items: list[dict]) -> list[dict]:
        seen = set()
        result = []
        for item in items:
            key = (item.get("key"), item.get("baseline_rank"), item.get("adjusted_rank"))
            if key in seen:
                continue
            seen.add(key)
            result.append(item)
        return result

    def _skill_memory_hint_type(self, memory: dict, governance: dict) -> str:
        memory_type = str(memory.get("type") or "").strip().lower()
        outcome = str(memory.get("outcome") or "").strip().lower()
        transfer_readiness = str(memory.get("transfer_readiness") or "").strip().lower()
        gate_readiness = str(governance.get("gate_readiness") or "").strip().lower()
        if memory_type in {"anti_pattern", "failure", "failure_mode"} or outcome in {
            "failure", "failed", "rejected", "blocked", "regression", "negative",
        }:
            return "AVOID"
        if transfer_readiness in {"review", "rejected", "error"} or gate_readiness in {"review", "rejected", "error"}:
            return "REVIEW_ONLY"
        if outcome in {"success", "succeeded", "achieved", "approved", "positive"} or transfer_readiness == "approved":
            return "REUSE"
        return "REVIEW_ONLY"

    def _skill_memory_goal_score(self, goal_tokens: set[str], skill: Skill, memory: dict) -> float:
        if not goal_tokens:
            return 0.0
        memory_text = " ".join([
            skill.name,
            skill.description,
            memory.get("note", ""),
            memory.get("type", ""),
            memory.get("outcome", ""),
            memory.get("task_family", ""),
            " ".join(memory.get("tags", [])),
        ])
        matches = goal_tokens & self._keywords(memory_text)
        return min(4.0, len(matches) * 0.75)

    def _format_skill_memory_hint(self, candidate: dict) -> str:
        memory = candidate.get("memory", {})
        metadata = []
        memory_type = memory.get("type", "")
        outcome = memory.get("outcome", "")
        transfer = candidate.get("transfer_readiness", "")
        if memory_type:
            metadata.append(f"type={memory_type}")
        if outcome:
            metadata.append(f"outcome={outcome}")
        if transfer:
            metadata.append(f"transfer={transfer}")
        metadata.append(f"confidence={candidate.get('confidence', 0.0):.2f}")
        quality_policies = candidate.get("quality_policies", [])
        if quality_policies:
            metadata.append(f"quality={'+'.join(quality_policies[:2])}")
        suffix = f" ({', '.join(metadata)})" if metadata else ""
        return f"{candidate['hint_type']} {candidate['skill_name']}: {memory.get('note', '')}{suffix}"

    def _skill_memory_quality_adjustment(self, hint_type: str, task_family: str = "", skill_name: str = "") -> dict:
        if not self._skill_memory_quality_policies and not self._skill_memory_quality_items:
            return {"rank_delta": 0.0, "score_delta": 0.0, "policies": []}
        policies = []
        rank_delta = 0.0
        score_delta = 0.0
        hint_type = str(hint_type or "").upper()
        task_family = str(task_family or "").strip().lower()
        item_labels = self._skill_memory_quality_item_labels(hint_type, skill_name, task_family)
        has_local_items = bool(self._skill_memory_quality_items)
        if hint_type == "REUSE" and item_labels.get("reuse_conflicted_with_failures", 0):
            rank_delta -= 1.5
            score_delta -= 2.5
            policies.append("demote_conflicting_reuse_hints")
        elif hint_type == "REUSE" and item_labels.get("reuse_supported_by_goal_success", 0):
            rank_delta += 0.35
            score_delta += 1.0
            policies.append("candidate_promote_reuse_hints")
        elif hint_type == "AVOID" and item_labels.get("avoid_unheeded_post_hint_failures", 0):
            rank_delta += 0.45
            score_delta += 0.8
            policies.append("tighten_avoid_hint_prompting")
        elif hint_type == "AVOID" and item_labels.get("avoid_supported_no_post_hint_failures", 0):
            score_delta += 0.3
            policies.append("retain_avoid_hint")
        elif hint_type == "REVIEW_ONLY" and item_labels.get("review_only_present_keep_gated", 0):
            score_delta -= 0.8
            policies.append("keep_review_only_skill_memory_gated")
        elif not has_local_items and hint_type == "REUSE" and self._has_skill_memory_quality_policy("demote_conflicting_reuse_hints"):
            rank_delta -= 1.25
            score_delta -= 2.0
            policies.append("demote_conflicting_reuse_hints")
        if not has_local_items and hint_type == "REUSE" and self._has_skill_memory_quality_policy("candidate_promote_reuse_hints"):
            rank_delta += 0.2
            score_delta += 0.8
            policies.append("candidate_promote_reuse_hints")
        if not has_local_items and hint_type == "AVOID" and self._has_skill_memory_quality_policy("tighten_avoid_hint_prompting"):
            rank_delta += 0.35
            score_delta += 0.6
            policies.append("tighten_avoid_hint_prompting")
        if not has_local_items and hint_type == "REVIEW_ONLY" and self._has_skill_memory_quality_policy("keep_review_only_skill_memory_gated"):
            score_delta -= 0.6
            policies.append("keep_review_only_skill_memory_gated")
        feedback_families = self._skill_memory_quality_feedback.get("task_family_counts", {})
        if task_family and isinstance(feedback_families, dict) and task_family in feedback_families:
            score_delta += 0.1
        return {
            "rank_delta": round(rank_delta, 4),
            "score_delta": round(score_delta, 4),
            "policies": policies,
        }

    def _has_skill_memory_quality_policy(self, policy: str) -> bool:
        return policy in self._skill_memory_quality_policies

    def _skill_memory_quality_item_labels(self, hint_type: str, skill_name: str, task_family: str) -> dict:
        keys = [
            self._skill_memory_quality_item_key(hint_type, skill_name, task_family),
            self._skill_memory_quality_item_key(hint_type, skill_name, ""),
        ]
        labels = {}
        for key in keys:
            item = self._skill_memory_quality_items.get(key, {})
            item_labels = item.get("labels", {}) if isinstance(item, dict) else {}
            if not isinstance(item_labels, dict):
                continue
            for label, count in item_labels.items():
                labels[str(label)] = labels.get(str(label), 0) + int(count or 0)
        return labels

    def _skill_memory_quality_item_key(self, hint_type, skill_name, task_family) -> tuple[str, str, str]:
        return (
            str(hint_type or "UNKNOWN").strip().upper() or "UNKNOWN",
            str(skill_name or "unknown").strip() or "unknown",
            str(task_family or "").strip().lower(),
        )

    def infer_task_family(self, text: str = "", action: Optional[dict] = None) -> str:
        """Infer a coarse Minecraft task-family zone for routing skill memories."""
        action = action if isinstance(action, dict) else {}
        action_type = str(action.get("type", "")).lower()
        params = action.get("parameters", {}) if isinstance(action.get("parameters", {}), dict) else {}
        payload = " ".join([
            str(text or ""),
            action_type,
            " ".join(str(value) for value in params.values() if value not in (None, "", [], {})),
        ]).lower()
        if action_type in {"craft", "craft_item", "smelt"}:
            return "crafting"
        if action_type in {"dig", "dig_block", "mine"}:
            return "mining"
        if action_type in {"move_to", "navigate", "pathfind"}:
            return "navigation"
        if action_type in {"attack", "attack_entity", "retreat"}:
            return "combat"
        if action_type in {"place", "place_block"}:
            if any(term in payload for term in ("redstone", "lamp", "lever", "repeater", "circuit")):
                return "redstone"
            return "building"
        family_terms = [
            ("redstone", ("redstone", "circuit", "lever", "repeater", "comparator", "lamp")),
            ("gathering", ("gather", "collect", "chop", "oak log", "wood log")),
            ("crafting", ("craft", "recipe", "smelt", "furnace", "torch", "pickaxe", "plank", "stick")),
            ("mining", ("mine", "dig", "ore", "coal", "iron", "diamond", "stone", "cobblestone")),
            ("building", ("build", "place", "shelter", "wall", "roof", "door", "base")),
            ("navigation", ("navigate", "move", "path", "route", "travel", "frontier", "explore")),
            ("combat", ("attack", "hostile", "zombie", "skeleton", "creeper", "danger", "retreat")),
            ("survival", ("food", "eat", "health", "night", "safe", "survive")),
            ("collaboration", ("role", "shared", "collaboration", "teammate", "multi-agent")),
        ]
        for family, terms in family_terms:
            if any(term in payload for term in terms):
                return family
        return "general"

    def find_failure_correction(self, action: dict, result: dict = None, world_state: dict = None) -> Optional[tuple[Skill, dict]]:
        """Find an approved failure-correction skill for a failed action."""
        matches = []
        task_family = self.infer_task_family("", action)
        for skill in self.skills.values():
            payload = self._implementation_payload(skill)
            if payload.get("type") != "failure_correction_skill":
                continue
            if not self._runtime_default_skill_allowed(skill.name, task_family):
                continue
            avoid = payload.get("avoid_action_template", {})
            if not self._action_matches_template(action, avoid):
                continue
            score = self._policy_relevance_score(skill, "", world_state or {})
            failure_why = str(payload.get("evidence", {}).get("failure_why", "")).lower()
            error = str((result or {}).get("error", "")).lower()
            if failure_why and error and self._keyword_overlap(failure_why, error):
                score += 1.0
            matches.append((score, skill, payload))
        if not matches:
            return None
        matches.sort(key=lambda item: (item[0], item[1].success_rate, item[1].total_uses), reverse=True)
        _, skill, payload = matches[0]
        return skill, payload

    def skill_graph_report(self) -> dict:
        """Return a typed, governance-oriented graph over known skills."""
        nodes = []
        edges = []
        skill_names = set(self.skills)
        builtin_names = self._builtin_skill_names()
        for skill in self.skills.values():
            dependencies = self._skill_dependencies(skill)
            missing_dependencies = [dep for dep in dependencies if dep not in skill_names]
            for dep in dependencies:
                edges.append({
                    "from": skill.name,
                    "to": dep,
                    "type": "depends_on" if dep in skill_names else "missing_dependency",
                })

            action_types = self._skill_action_types(skill)
            for action_type in action_types:
                edges.append({
                    "from": skill.name,
                    "to": f"action:{action_type}",
                    "type": "uses_action",
                })

            postcondition_keys = self._postcondition_keys(skill.postconditions)
            for key in postcondition_keys:
                edges.append({
                    "from": skill.name,
                    "to": f"postcondition:{key}",
                    "type": "has_postcondition",
                })

            built_in = skill.name in builtin_names
            governance = self._skill_governance(skill, built_in=built_in)
            issues = []
            if missing_dependencies:
                issues.append("missing_dependency")
            if not built_in and not governance["governed"]:
                issues.append("ungoverned_custom_skill")
            if not built_in and not postcondition_keys and governance["gate_readiness"] in {"unknown", "not_required"}:
                issues.append("missing_postconditions")
            if governance["gate_readiness"] in {"review", "rejected", "error"}:
                issues.append(f"gate_{governance['gate_readiness']}")

            nodes.append({
                "name": skill.name,
                "layer": skill.layer,
                "built_in": built_in,
                "dependencies": dependencies,
                "missing_dependencies": missing_dependencies,
                "action_types": action_types,
                "postcondition_keys": postcondition_keys,
                "governance": governance,
                "issues": issues,
            })

        cycles = self._skill_dependency_cycles(nodes)
        issue_counts = {}
        for node in nodes:
            for issue in node["issues"]:
                issue_counts[issue] = issue_counts.get(issue, 0) + 1
        return {
            "skill_count": len(nodes),
            "custom_skill_count": sum(1 for node in nodes if not node["built_in"]),
            "edge_count": len(edges),
            "missing_dependency_count": sum(len(node["missing_dependencies"]) for node in nodes),
            "ungoverned_custom_skill_count": issue_counts.get("ungoverned_custom_skill", 0),
            "missing_postcondition_count": issue_counts.get("missing_postconditions", 0),
            "cycle_count": len(cycles),
            "issue_counts": issue_counts,
            "cycles": cycles,
            "nodes": sorted(nodes, key=lambda node: (node["layer"], node["name"])),
            "edges": sorted(edges, key=lambda edge: (edge["from"], edge["type"], edge["to"])),
        }

    def skill_memory_report(
        self,
        goal: str = "",
        task_family: str = "",
        include_builtins: bool = False,
        limit: int = 20,
    ) -> dict:
        """Return per-skill memory, transfer, and interference diagnostics."""
        builtin_names = self._builtin_skill_names()
        family_filter = str(task_family or "").strip().lower()
        summaries = []
        issue_counts = {}
        task_family_counts = {}
        recommendation_items = []

        for skill in self.skills.values():
            built_in = skill.name in builtin_names
            memories = self._normalized_skill_memory(skill)
            if family_filter:
                memories = [
                    memory for memory in memories
                    if str(memory.get("task_family", "")).strip().lower() == family_filter
                ]
            if built_in and not include_builtins and not memories:
                continue
            if family_filter and not memories:
                continue

            summary = self._skill_memory_summary(skill, memories, goal, built_in)
            summaries.append(summary)
            for issue in summary["issues"]:
                issue_counts[issue] = issue_counts.get(issue, 0) + 1
            for family, count in summary["task_family_counts"].items():
                task_family_counts[family] = task_family_counts.get(family, 0) + count
            for recommendation in summary["recommendations"]:
                recommendation_items.append({
                    "skill": skill.name,
                    "recommendation": recommendation,
                    "reason": self._skill_memory_recommendation_reason(recommendation),
                })

        summaries.sort(
            key=lambda item: (
                item["memory_count"],
                item["approved_transfer_memory_count"],
                item["contract_score"],
                item["success_rate"],
                item["total_uses"],
            ),
            reverse=True,
        )
        visible = summaries[:limit] if limit and limit > 0 else summaries
        return {
            "goal": goal,
            "task_family": task_family,
            "skill_count": len(summaries),
            "skills_with_memory_count": sum(1 for item in summaries if item["memory_count"] > 0),
            "memory_count": sum(item["memory_count"] for item in summaries),
            "success_memory_count": sum(item["success_memory_count"] for item in summaries),
            "failure_memory_count": sum(item["failure_memory_count"] for item in summaries),
            "approved_transfer_memory_count": sum(
                item["approved_transfer_memory_count"] for item in summaries
            ),
            "review_transfer_memory_count": sum(item["review_transfer_memory_count"] for item in summaries),
            "issue_counts": issue_counts,
            "task_family_counts": task_family_counts,
            "recommendations": recommendation_items[:limit] if limit and limit > 0 else recommendation_items,
            "skills": visible,
        }

    def skill_contract_report(self, goal: str = "", world_state: Optional[dict] = None, limit: int = 20) -> dict:
        """Return COS-PLAY-style skill contract readiness and retrieval evidence."""
        all_profiles = self._skill_contract_profiles(goal, world_state or {}, limit=0)
        profiles = all_profiles[:limit] if limit and limit > 0 else all_profiles
        issue_counts = {}
        for profile in all_profiles:
            for issue in profile["issues"]:
                issue_counts[issue] = issue_counts.get(issue, 0) + 1
        return {
            "goal": goal,
            "skill_count": len(self.skills),
            "matched_count": sum(1 for profile in all_profiles if profile["score"] > 0),
            "ready_count": sum(1 for profile in all_profiles if profile["readiness"] == "ready"),
            "blocked_count": sum(1 for profile in all_profiles if profile["readiness"] == "blocked"),
            "review_count": sum(1 for profile in all_profiles if profile["readiness"] == "review"),
            "issue_counts": issue_counts,
            "matches": profiles,
        }

    def _load_custom_skills(self):
        if not os.path.exists(self.custom_path):
            return
        try:
            with open(self.custom_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    data = json.loads(line)
                    skill = Skill(**self._filter_skill_fields(data))
                    skill.skill_id = skill.skill_id or skill.name
                    skill.status = str(skill.status or "candidate").strip().lower()
                    skill.task_family = skill.task_family or self.infer_task_family(
                        " ".join([skill.name, skill.description])
                    )
                    if not skill.bounded_action_template and skill.implementation:
                        try:
                            parsed = json.loads(skill.implementation)
                        except (TypeError, ValueError):
                            parsed = {}
                        if isinstance(parsed, dict) and parsed.get("dsl_version"):
                            skill.bounded_action_template = parsed
                    skill.confidence_interval = skill.confidence_interval or wilson_confidence_interval(
                        skill.success_count,
                        skill.failure_count,
                    )
                    skill.skill_memory = self._normalized_skill_memory(skill)
                    self._skill_history[(skill.skill_id, skill.version)] = skill
                    current = self.skills.get(skill.name)
                    if current is None or self._version_key(skill.version) >= self._version_key(current.version):
                        self.skills[skill.name] = skill
        except Exception as e:
            logger.warning(f"Could not load custom skills: {e}")

    def _rewrite_custom_skills(self):
        builtin_names = self._builtin_skill_names()
        for skill in self.skills.values():
            if skill.name not in builtin_names:
                self._skill_history[(skill.skill_id or skill.name, skill.version)] = skill
        custom_skills = sorted(
            self._skill_history.values(),
            key=lambda skill: (skill.skill_id or skill.name, self._version_key(skill.version)),
        )
        temp_path = self.custom_path + ".tmp"
        with open(temp_path, "w", encoding="utf-8") as f:
            for skill in custom_skills:
                f.write(json.dumps(asdict(skill), ensure_ascii=False, default=str) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, self.custom_path)

    def skill_versions(self, skill_id: str) -> list[Skill]:
        target = str(skill_id or "").strip()
        versions = [
            skill for (stored_id, _), skill in self._skill_history.items()
            if stored_id == target or skill.name == target
        ]
        return sorted(versions, key=lambda skill: self._version_key(skill.version))

    def _version_key(self, version: str) -> tuple[int, ...]:
        raw = str(version or "0").strip()
        core = raw.split("-", 1)[0]
        parts = []
        for value in core.split("."):
            match = re.match(r"\d+", value)
            parts.append(int(match.group(0)) if match else 0)
        major, minor, patch = (parts + [0, 0, 0])[:3]
        release_rank = 0 if "-" in raw else 1
        return major, minor, patch, release_rank

    def _next_patch_version(self, version: str) -> str:
        major, minor, patch = self._version_key(version)[:3]
        if "-" in str(version or ""):
            return f"{major}.{minor}.{patch}"
        return f"{major}.{minor}.{patch + 1}"

    def _filter_skill_fields(self, data: dict) -> dict:
        allowed = set(Skill.__dataclass_fields__.keys())
        return {k: v for k, v in data.items() if k in allowed}

    def _normalized_skill_memory(self, skill: Skill) -> list[dict]:
        raw_memory = skill.skill_memory if isinstance(skill.skill_memory, list) else []
        return [
            self._normalize_skill_memory_record(record)
            for record in raw_memory
            if isinstance(record, (dict, str))
        ]

    def _normalize_skill_memory_record(self, record) -> dict:
        if isinstance(record, str):
            record = {"note": record}
        record = record if isinstance(record, dict) else {}
        transfer_gate = record.get("transfer_gate", {})
        transfer_gate = transfer_gate if isinstance(transfer_gate, dict) else {}
        evidence = record.get("evidence", {})
        evidence = evidence if isinstance(evidence, dict) else {}
        confidence = record.get("confidence", 0.7)
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            confidence = 0.7
        confidence = round(min(1.0, max(0.0, confidence)), 4)
        tags = []
        raw_tags = record.get("tags", [])
        raw_tags = raw_tags if isinstance(raw_tags, list) else []
        for tag in raw_tags:
            text = str(tag or "").strip()
            if text and text not in tags:
                tags.append(text)
        transfer_readiness = (
            record.get("transfer_readiness")
            or transfer_gate.get("readiness")
            or transfer_gate.get("decision")
            or ""
        )
        return {
            "timestamp": str(record.get("timestamp") or time.strftime("%Y-%m-%d")),
            "type": str(record.get("type") or record.get("memory_type") or "experience").strip() or "experience",
            "outcome": str(record.get("outcome") or "").strip().lower(),
            "task_family": str(record.get("task_family") or "").strip().lower(),
            "note": str(record.get("note") or "").strip(),
            "source": str(record.get("source") or "").strip(),
            "confidence": confidence,
            "tags": tags,
            "transfer_readiness": str(transfer_readiness or "").strip().lower(),
            "transfer_gate": transfer_gate,
            "evidence": evidence,
        }

    def _skill_memory_summary(self, skill: Skill, memories: list[dict], goal: str, built_in: bool) -> dict:
        governance = self._skill_governance(skill, built_in=built_in)
        contract = self._skill_contract_profile(skill, goal, {}) if goal else {
            "score": 0.0,
            "readiness": "ready" if governance["gate_readiness"] not in {"review", "rejected", "error"} else "review",
            "issues": [],
        }
        task_family_counts = {}
        for memory in memories:
            family = memory.get("task_family") or "unspecified"
            task_family_counts[family] = task_family_counts.get(family, 0) + 1
        success_count = sum(1 for memory in memories if memory.get("outcome") in {
            "success", "succeeded", "achieved", "approved", "positive",
        })
        failure_count = sum(1 for memory in memories if memory.get("outcome") in {
            "failure", "failed", "rejected", "blocked", "regression", "negative",
        })
        approved_transfer_count = sum(
            1 for memory in memories if memory.get("transfer_readiness") == "approved"
        )
        review_transfer_count = sum(
            1 for memory in memories if memory.get("transfer_readiness") in {"review", "rejected", "error"}
        )
        issues = []
        if not built_in and not memories:
            issues.append("missing_skill_memory")
        if failure_count > success_count and failure_count > 0:
            issues.append("failure_heavy_memory")
        if review_transfer_count:
            issues.append("transfer_review_or_rejected")
        if governance["gate_readiness"] in {"review", "rejected", "error"}:
            issues.append(f"gate_{governance['gate_readiness']}")

        recommendations = []
        if "missing_skill_memory" in issues:
            recommendations.append("record_replay_or_failure_memory")
        if "failure_heavy_memory" in issues:
            recommendations.append("refine_skill_or_add_failure_correction")
        if "transfer_review_or_rejected" in issues or governance["gate_readiness"] in {"review", "rejected", "error"}:
            recommendations.append("keep_task_family_route_gated")
        if approved_transfer_count and contract.get("readiness") == "ready":
            recommendations.append("candidate_runtime_default_for_matching_family")

        return {
            "name": skill.name,
            "layer": skill.layer,
            "built_in": built_in,
            "description": skill.description,
            "total_uses": skill.total_uses,
            "success_rate": round(skill.success_rate, 4),
            "gate_readiness": governance["gate_readiness"],
            "contract_score": round(float(contract.get("score", 0.0)), 4),
            "contract_readiness": contract.get("readiness", "ready"),
            "memory_count": len(memories),
            "success_memory_count": success_count,
            "failure_memory_count": failure_count,
            "approved_transfer_memory_count": approved_transfer_count,
            "review_transfer_memory_count": review_transfer_count,
            "task_family_counts": task_family_counts,
            "last_memory_at": memories[-1]["timestamp"] if memories else "",
            "issues": sorted(set(issues + contract.get("issues", []))),
            "recommendations": sorted(set(recommendations)),
            "memories": memories[-5:],
        }

    def _skill_memory_recommendation_reason(self, recommendation: str) -> str:
        reasons = {
            "record_replay_or_failure_memory": "custom skill has no skill-local replay or failure notes",
            "refine_skill_or_add_failure_correction": "failure memories outnumber successful memories",
            "keep_task_family_route_gated": "transfer or promotion gate is not approved",
            "candidate_runtime_default_for_matching_family": "approved transfer memory and ready contract",
        }
        return reasons.get(recommendation, "")

    def _policy_skills(self, goal: str, world_state: dict) -> list[Skill]:
        scored = []
        task_family = self.infer_task_family(goal, {})
        for skill in self.skills.values():
            payload = self._implementation_payload(skill)
            if payload.get("type") not in {"causal_summary_skill", "failure_correction_skill"}:
                continue
            if not self._runtime_default_skill_allowed(skill.name, task_family):
                continue
            score = self._policy_relevance_score(skill, goal, world_state)
            if score > 0:
                scored.append((score, skill))
        scored.sort(key=lambda item: (item[0], item[1].success_rate, item[1].total_uses), reverse=True)
        return [skill for _, skill in scored]

    def _policy_relevance_score(self, skill: Skill, goal: str, world_state: dict) -> float:
        payload = self._implementation_payload(skill)
        text = " ".join([
            goal,
            json.dumps(world_state.get("inventory", {}), default=str),
            json.dumps(world_state.get("nearby_blocks", []), default=str),
            json.dumps(world_state.get("nearby_entities", []), default=str),
        ]).lower()
        score = 0.0
        for action in self._payload_actions(payload):
            action_type = str(action.get("type", "")).lower()
            params = action.get("parameters", {}) if isinstance(action.get("parameters", {}), dict) else {}
            subjects = [str(value).lower() for value in params.values() if isinstance(value, (str, int, float))]
            if action_type and action_type in text:
                score += 0.5
            for subject in subjects:
                if subject and subject in text:
                    score += 1.0
        if skill.total_uses:
            score += skill.success_rate
        return score

    def _skill_contract_profiles(self, goal: str, world_state: dict, limit: int = 20) -> list[dict]:
        profiles = [
            self._skill_contract_profile(skill, goal, world_state or {})
            for skill in self.skills.values()
        ]
        profiles.sort(
            key=lambda item: (
                item["score"],
                1 if item["readiness"] == "ready" else 0,
                item["success_rate"],
                item["total_uses"],
            ),
            reverse=True,
        )
        return profiles[:limit] if limit and limit > 0 else profiles

    def _skill_contract_profile(self, skill: Skill, goal: str, world_state: dict) -> dict:
        inventory = world_state.get("inventory", {}) if isinstance(world_state.get("inventory", {}), dict) else {}
        builtin_names = self._builtin_skill_names()
        goal_tokens = self._keywords(goal)
        state_tokens = self._keywords(json.dumps({
            "inventory": inventory,
            "nearby_blocks": world_state.get("nearby_blocks", []),
            "nearby_entities": world_state.get("nearby_entities", []),
            "grounded_resources": world_state.get("grounded_resources", []),
        }, default=str))
        contract_text = " ".join([
            skill.name,
            skill.description,
            json.dumps(skill.parameters, default=str),
            json.dumps(skill.preconditions, default=str),
            json.dumps(skill.postconditions, default=str),
            " ".join(str(item) for item in skill.required_items),
        ])
        contract_tokens = self._keywords(contract_text)
        goal_matches = sorted(goal_tokens & contract_tokens)
        state_matches = sorted(state_tokens & contract_tokens)
        postcondition_targets = self._postcondition_keys(skill.postconditions)
        postcondition_tokens = self._keywords(" ".join(postcondition_targets))
        postcondition_matches = sorted(goal_tokens & postcondition_tokens)

        missing_preconditions = self._missing_preconditions(skill, world_state)
        missing_required_items = self._missing_required_items(skill, inventory)
        dependencies = self._skill_dependencies(skill)
        missing_dependencies = [dep for dep in dependencies if dep not in self.skills]
        governance = self._skill_governance(skill, built_in=skill.name in builtin_names)

        issues = []
        if missing_preconditions:
            issues.append("missing_preconditions")
        if missing_required_items:
            issues.append("missing_required_items")
        if missing_dependencies:
            issues.append("missing_dependencies")
        if governance["gate_readiness"] in {"review", "rejected", "error"}:
            issues.append(f"gate_{governance['gate_readiness']}")
        if skill.name not in builtin_names and not postcondition_targets:
            issues.append("missing_postconditions")
        if not skill.preconditions and not skill.required_items and skill.layer in {"composite", "strategic"}:
            issues.append("underspecified_preconditions")

        score = 0.0
        score += len(goal_matches) * 1.4
        score += len(state_matches) * 0.8
        score += len(postcondition_matches) * 2.0
        if skill.total_uses:
            score += skill.success_rate + min(1.0, skill.total_uses * 0.05)
        if governance["gate_readiness"] == "approved":
            score += 1.0
        score -= len(missing_preconditions) * 2.0
        score -= len(missing_required_items) * 2.0
        score -= len(missing_dependencies) * 3.0
        score = round(max(0.0, score), 4)

        if missing_dependencies or governance["gate_readiness"] in {"rejected", "error"}:
            readiness = "blocked"
        elif missing_preconditions or missing_required_items or governance["gate_readiness"] == "review":
            readiness = "review"
        else:
            readiness = "ready"

        return {
            "name": skill.name,
            "layer": skill.layer,
            "description": skill.description,
            "score": score,
            "readiness": readiness,
            "success_rate": round(skill.success_rate, 4),
            "total_uses": skill.total_uses,
            "goal_matches": goal_matches[:12],
            "state_matches": state_matches[:12],
            "postcondition_targets": postcondition_targets,
            "postcondition_matches": postcondition_matches[:12],
            "required_items": list(skill.required_items),
            "missing_required_items": missing_required_items,
            "missing_preconditions": missing_preconditions,
            "dependencies": dependencies,
            "missing_dependencies": missing_dependencies,
            "gate_readiness": governance["gate_readiness"],
            "issues": sorted(set(issues)),
        }

    def _missing_required_items(self, skill: Skill, inventory: dict) -> list[str]:
        missing = []
        for item in skill.required_items or []:
            if isinstance(item, dict):
                name = str(item.get("item") or item.get("name") or "").strip()
                needed = self._safe_int(item.get("count", 1), default=1)
            else:
                name = str(item or "").strip()
                needed = 1
            if name and self._inventory_quantity(inventory, name) < needed:
                missing.append(name if needed <= 1 else f"{name}>={needed}")
        return missing

    def _missing_preconditions(self, skill: Skill, world_state: dict) -> list[str]:
        preconditions = skill.preconditions if isinstance(skill.preconditions, dict) else {}
        inventory = world_state.get("inventory", {}) if isinstance(world_state.get("inventory", {}), dict) else {}
        flags = set(str(flag).lower() for flag in world_state.get("flags", []) if flag)
        missing = []
        inventory_preconditions = (
            preconditions.get("inventory", {})
            if isinstance(preconditions.get("inventory", {}), dict)
            else {}
        )
        for item, count in inventory_preconditions.items():
            needed = self._safe_int(count, default=1)
            if self._inventory_quantity(inventory, item) < needed:
                missing.append(f"inventory:{item}>={needed}")
        flag_preconditions = (
            preconditions.get("flags", [])
            if isinstance(preconditions.get("flags", []), list)
            else []
        )
        for flag in flag_preconditions:
            if str(flag).lower() not in flags:
                missing.append(f"flag:{flag}")
        nearby = self._world_state_nearby_names(world_state)
        nearby_preconditions = (
            preconditions.get("nearby_block_present", [])
            if isinstance(preconditions.get("nearby_block_present", []), list)
            else []
        )
        for block in nearby_preconditions:
            if str(block).lower() not in nearby:
                missing.append(f"nearby_block:{block}")
        return missing

    def _inventory_quantity(self, inventory: dict, item: str) -> int:
        return ingredient_count(str(item or "").strip().lower(), inventory)

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

    def _world_state_nearby_names(self, world_state: dict) -> set[str]:
        names = set()
        for key in ("nearby_blocks", "grounded_resources", "visible_blocks", "resources"):
            value = world_state.get(key, [])
            if isinstance(value, dict):
                iterable = value.values()
            elif isinstance(value, list):
                iterable = value
            else:
                iterable = []
            for item in iterable:
                if isinstance(item, dict):
                    raw = item.get("name") or item.get("type") or item.get("block") or item.get("resource")
                else:
                    raw = item
                text = str(raw or "").strip().lower()
                if text:
                    names.add(text)
        return names

    def _payload_actions(self, payload: dict) -> list[dict]:
        actions = []
        for key in ("action_template", "avoid_action_template", "primary_correction"):
            if isinstance(payload.get(key), dict):
                actions.append(payload[key])
        for action in payload.get("correction_sequence", []):
            if isinstance(action, dict):
                actions.append(action)
        return actions

    def _implementation_payload(self, skill: Skill) -> dict:
        try:
            payload = json.loads(skill.implementation)
        except (TypeError, ValueError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _implementation_actions(self, skill: Skill) -> list[dict]:
        try:
            payload = json.loads(skill.implementation)
        except (TypeError, ValueError):
            return []
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            return self._payload_actions(payload)
        return []

    def _skill_action_types(self, skill: Skill) -> list[str]:
        action_types = []
        for action in self._implementation_actions(skill):
            action_type = str(action.get("type", "")).strip()
            if action_type and action_type not in action_types:
                action_types.append(action_type)
        return action_types

    def _skill_dependencies(self, skill: Skill) -> list[str]:
        dependencies = []
        raw_dependencies = skill.dependencies if isinstance(skill.dependencies, list) else [skill.dependencies]
        for dep in raw_dependencies:
            text = str(dep or "").strip()
            if text and text not in dependencies:
                dependencies.append(text)
        action_to_skill = {
            "move_to": "move_to",
            "look_at": "look_at",
            "dig": "dig_block",
            "dig_block": "dig_block",
            "place": "place_block",
            "place_block": "place_block",
            "craft": "craft_item",
            "craft_item": "craft_item",
            "attack": "attack_entity",
            "attack_entity": "attack_entity",
            "eat": "eat_food",
            "eat_food": "eat_food",
        }
        for action_type in self._skill_action_types(skill):
            dep = action_to_skill.get(action_type)
            if dep and dep != skill.name and dep not in dependencies:
                dependencies.append(dep)
        return dependencies

    def _postcondition_keys(self, postconditions: dict) -> list[str]:
        if not isinstance(postconditions, dict):
            return []
        keys = []
        inventory = postconditions.get("inventory", {}) if isinstance(postconditions.get("inventory", {}), dict) else {}
        for item in sorted(inventory):
            keys.append(f"inventory:{item}")
        for key, value in sorted(postconditions.items()):
            if key == "inventory":
                continue
            if isinstance(value, dict):
                for subkey in sorted(value):
                    keys.append(f"{key}:{subkey}")
            elif value not in (None, "", [], {}):
                keys.append(str(key))
        return keys

    def _skill_governance(self, skill: Skill, built_in: bool = False) -> dict:
        gate = skill.gate if isinstance(skill.gate, dict) else {}
        provenance = skill.provenance if isinstance(skill.provenance, dict) else {}
        notes = str(skill.notes or "")
        verification_gate = gate.get("verification", {}) if isinstance(gate.get("verification", {}), dict) else {}
        discovery_gate = gate.get("discovery", {}) if isinstance(gate.get("discovery", {}), dict) else {}
        transfer_gate = gate.get("transfer", {}) if isinstance(gate.get("transfer", {}), dict) else {}
        gate_readiness = self._gate_readiness(gate, verification_gate, discovery_gate, transfer_gate)
        governed = bool(
            built_in
            or gate
            or provenance
            or "promotion_report" in notes
            or "review=approved" in notes
            or self._postcondition_keys(skill.postconditions)
        )
        return {
            "governed": governed,
            "gate_readiness": gate_readiness,
            "decision": gate.get("decision", "builtin" if built_in else "unknown"),
            "verification_status": verification_gate.get("status", ""),
            "discovery_readiness": discovery_gate.get("readiness", ""),
            "transfer_readiness": transfer_gate.get("readiness", ""),
            "provenance_sources": self._provenance_sources(provenance),
        }

    def _gate_readiness(self, gate: dict, verification_gate: dict, discovery_gate: dict, transfer_gate: dict = None) -> str:
        transfer_gate = transfer_gate if isinstance(transfer_gate, dict) else {}
        if not gate:
            return "not_required"
        if discovery_gate.get("readiness") in {"review", "rejected", "error"}:
            return str(discovery_gate.get("readiness"))
        if transfer_gate.get("readiness") in {"review", "rejected", "error"}:
            return str(transfer_gate.get("readiness"))
        if gate.get("decision") == "reject" or verification_gate.get("decision") == "reject":
            return "rejected"
        if transfer_gate.get("readiness") == "approved":
            return "approved"
        if discovery_gate.get("readiness") == "approved":
            return "approved"
        if verification_gate.get("status") in {"achieved", "critic_approved"} or gate.get("decision") == "approve":
            return "approved"
        return "unknown"

    def _provenance_sources(self, provenance: dict) -> list[str]:
        sources = []
        for key in ("source_log", "candidate_id", "goal", "reviewer"):
            value = provenance.get(key)
            if value not in (None, "", [], {}):
                sources.append(f"{key}:{value}")
        return sources

    def _skill_dependency_cycles(self, nodes: list[dict]) -> list[list[str]]:
        graph = {
            node["name"]: [dep for dep in node["dependencies"] if dep in self.skills]
            for node in nodes
        }
        cycles = []
        seen_cycles = set()

        def visit(node: str, path: list[str]):
            if node in path:
                cycle = path[path.index(node):] + [node]
                body = cycle[:-1]
                rotations = [tuple(body[index:] + body[:index]) for index in range(len(body))]
                key = min(rotations)
                if key not in seen_cycles:
                    seen_cycles.add(key)
                    cycles.append(list(key) + [key[0]])
                return
            for dep in graph.get(node, []):
                visit(dep, path + [node])

        for node in graph:
            visit(node, [])
        return cycles

    def _action_matches_template(self, action: dict, template: dict) -> bool:
        if not action or not template:
            return False
        if action.get("type") != template.get("type"):
            return False
        action_params = action.get("parameters", {}) if isinstance(action.get("parameters", {}), dict) else {}
        template_params = template.get("parameters", {}) if isinstance(template.get("parameters", {}), dict) else {}
        for key, value in template_params.items():
            if value is None:
                continue
            if key not in action_params or str(action_params.get(key)) != str(value):
                return False
        return True

    def _keyword_overlap(self, left: str, right: str) -> bool:
        return bool(self._keywords(left) & self._keywords(right))

    def _keywords(self, text: str) -> set[str]:
        cleaned = []
        for ch in str(text).lower():
            cleaned.append(ch if ch.isalnum() or ch == "_" else " ")
        return {word for word in "".join(cleaned).split() if len(word) > 2}

    def _format_action(self, action: dict) -> str:
        if not action:
            return "unknown action"
        params = action.get("parameters", {}) if isinstance(action.get("parameters", {}), dict) else {}
        subject = params.get("item") or params.get("block") or params.get("entity") or params.get("target")
        return f"{action.get('type', 'action')}:{subject}" if subject else str(action.get("type", "action"))

    def _builtin_skill_names(self) -> set[str]:
        return {
            "move_to", "look_at", "dig_block", "place_block", "craft_item", "attack_entity", "eat_food",
            "gather_wood", "craft_tools", "mine_stone", "mine_iron", "smelt_iron", "build_shelter",
            "defend_self", "navigate_to_target", "survive_first_night", "prepare_for_mining",
        }
