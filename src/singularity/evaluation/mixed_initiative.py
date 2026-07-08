"""Mixed-initiative Minecraft task templates and bounded validators.

This module is inspired by MineNPC-Task's evaluation shape: user-authored
requests are compiled into compact subtask records with explicit dependencies,
slot parameters, at most one targeted clarification, and machine-checkable
validators that only use bounded in-world evidence.
"""
from __future__ import annotations

import math
import json
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

    def to_dict(self) -> dict:
        return {
            "log_count": self.log_count,
            "goal_count": self.goal_count,
            "needs_clarification_count": self.needs_clarification_count,
            "unbound_slot_count": self.unbound_slot_count,
            "validator_success_count": self.validator_success_count,
            "policy_violation_count": self.policy_violation_count,
            "unsupported_goal_count": self.unsupported_goal_count,
            "agreement_counts": self.agreement_counts,
            "template_candidates": self.template_candidates,
            "errors": list(self.errors),
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

    return MixedInitiativeTraceCase(
        source_log=source_log,
        goal=goal,
        event_count=len(events),
        observation_count=sum(1 for event in events if event.get("type") == "observation"),
        action_count=sum(1 for event in events if event.get("type") == "action"),
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
