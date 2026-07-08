"""Mixed-initiative Minecraft task templates and bounded validators.

This module is inspired by MineNPC-Task's evaluation shape: user-authored
requests are compiled into compact subtask records with explicit dependencies,
slot parameters, at most one targeted clarification, and machine-checkable
validators that only use bounded in-world evidence.
"""
from __future__ import annotations

import math
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
        if any(token in goal_lower for token in ("pickaxe", "pick axe", "tool")) and any(
            token in goal_lower for token in ("get", "fetch", "bring", "retrieve")
        ):
            return self.templates["fetch_named_tool"]
        if any(token in goal_lower for token in ("log", "logs", "wood", "oak")):
            return self.templates["collect_oak_logs"]
        return self.templates["collect_oak_logs"]

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
    return {
        collect_oak_logs.id: collect_oak_logs,
        fetch_named_tool.id: fetch_named_tool,
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
