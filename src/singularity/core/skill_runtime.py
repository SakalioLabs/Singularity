"""Typed, bounded runtime support for learned skills.

Learned skills are declarative data.  This module intentionally supports a
small operation set and never evaluates code carried by a skill artifact.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from typing import Any

from singularity.data.knowledge_base import ingredient_count


DSL_VERSION = "bounded_action_template_v1"
ALLOWED_OPERATIONS = {"acquire_block_drop", "craft_item"}
FORBIDDEN_KEYS = {
    "code",
    "eval",
    "exec",
    "javascript",
    "python",
    "script",
    "shell",
    "source_code",
}


@dataclass
class SkillContractValidation:
    valid: bool
    normalized_template: dict = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "valid": self.valid,
            "normalized_template": self.normalized_template,
            "issues": list(self.issues),
            "warnings": list(self.warnings),
        }


def validate_bounded_action_template(template: Any) -> SkillContractValidation:
    """Validate and normalize the only executable learned-skill format."""
    issues: list[str] = []
    warnings: list[str] = []
    if not isinstance(template, dict):
        return SkillContractValidation(False, issues=["template_must_be_object"])
    forbidden = _forbidden_paths(template)
    if forbidden:
        issues.extend(f"forbidden_executable_field:{path}" for path in forbidden)

    version = str(template.get("dsl_version") or "").strip()
    if version != DSL_VERSION:
        issues.append("unsupported_dsl_version")
    phases = template.get("phases", [])
    if not isinstance(phases, list) or not phases:
        issues.append("phases_required")
        phases = []
    if len(phases) > 8:
        issues.append("too_many_phases")

    max_actions = _bounded_int(template.get("max_actions", 8), 1, 32, 8)
    normalized_phases = []
    for index, raw_phase in enumerate(phases[:8]):
        normalized = _normalize_phase(raw_phase, index, issues, warnings)
        if normalized:
            normalized_phases.append(normalized)

    normalized = {
        "dsl_version": DSL_VERSION,
        "max_actions": max_actions,
        "phases": normalized_phases,
    }
    if isinstance(template.get("parameters"), dict):
        normalized["parameters"] = _json_data(template["parameters"])
    return SkillContractValidation(not issues, normalized, sorted(set(issues)), sorted(set(warnings)))


def bounded_template_fingerprint(template: Any, task_family: str = "") -> str:
    validation = validate_bounded_action_template(template)
    payload = validation.normalized_template if validation.normalized_template else {}
    canonical = json.dumps(
        {"task_family": str(task_family or "").strip().lower(), "template": payload},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:20]


def wilson_confidence_interval(successes: int, failures: int, z: float = 1.96) -> dict:
    successes = max(0, int(successes or 0))
    failures = max(0, int(failures or 0))
    total = successes + failures
    if total <= 0:
        return {"method": "wilson_95", "lower": 0.0, "upper": 1.0, "samples": 0}
    p = successes / total
    denominator = 1.0 + (z * z / total)
    center = (p + z * z / (2.0 * total)) / denominator
    margin = z * math.sqrt((p * (1.0 - p) / total) + (z * z / (4.0 * total * total))) / denominator
    return {
        "method": "wilson_95",
        "lower": round(max(0.0, center - margin), 6),
        "upper": round(min(1.0, center + margin), 6),
        "samples": total,
    }


def derive_bounded_action_template(
    goal: str,
    actions: list[dict],
    postconditions: dict,
) -> dict:
    """Abstract grounded trace actions into a coordinate-free bounded template."""
    successful = [item for item in actions if isinstance(item, dict)]
    action_types = [str(item.get("type") or "").strip() for item in successful]
    inventory_targets = _inventory_targets(postconditions)
    target_item, target_count = next(iter(inventory_targets.items()), ("", 0))

    craft_actions = [item for item in successful if item.get("type") == "craft"]
    if craft_actions and len(craft_actions) == len(successful):
        item = str(craft_actions[-1].get("parameters", {}).get("item") or target_item).strip()
        if item:
            return {
                "dsl_version": DSL_VERSION,
                "max_actions": max(1, min(8, len(craft_actions))),
                "phases": [{
                    "id": "craft_target",
                    "op": "craft_item",
                    "item": item,
                    "count": 1,
                    "target_item": target_item or item,
                    "target_count": max(1, target_count or 1),
                }],
            }

    dig_actions = [item for item in successful if item.get("type") == "dig"]
    if dig_actions and all(kind in {"move_to", "dig", "look_at", "wait"} for kind in action_types):
        source_blocks = []
        for item in dig_actions:
            params = item.get("parameters", {}) if isinstance(item.get("parameters"), dict) else {}
            block = str(params.get("block") or item.get("block") or "").strip()
            if block and block not in source_blocks:
                source_blocks.append(block)
        if source_blocks and target_item:
            maximum = max(target_count, 1)
            return {
                "dsl_version": DSL_VERSION,
                "max_actions": max(2, min(32, maximum + 3)),
                "parameters": {
                    "quantity": {
                        "type": "integer",
                        "default": maximum,
                        "minimum": 1,
                        "maximum": max(8, maximum),
                    },
                },
                "phases": [{
                    "id": "acquire_target",
                    "op": "acquire_block_drop",
                    "source_blocks": source_blocks,
                    "target_item": target_item,
                    "target_count": {"parameter": "quantity", "default": maximum},
                    "selector": "nearest_observed",
                    "search_radius": 32,
                    "interaction_range": 4.5,
                    "navigation_tolerance": 1.75,
                }],
            }
    return {}


def build_bounded_skill_plan(skill: Any, goal: str, world_state: dict) -> dict:
    """Build a re-observable plan from one learned skill contract."""
    template = _skill_template(skill)
    validation = validate_bounded_action_template(template)
    identity = _skill_identity(skill)
    if not validation.valid:
        return _fallback(identity, "invalid_skill_contract", validation.issues)
    parameters, parameter_issue = _bind_parameters(validation.normalized_template, goal)
    if parameter_issue:
        return _fallback(identity, parameter_issue)
    effective_postconditions = _bind_postconditions(
        skill,
        validation.normalized_template,
        parameters,
    )
    state = world_state if isinstance(world_state, dict) else {}
    precondition_issues = evaluate_skill_preconditions(skill, state)
    if precondition_issues:
        return _fallback(identity, "preconditions_not_met", precondition_issues)

    for phase in validation.normalized_template["phases"]:
        plan = _plan_phase(phase, parameters, state, validation.normalized_template["max_actions"])
        if plan.get("status") != "complete":
            return {
                **plan,
                "skill": identity,
                "bound_parameters": parameters,
                "effective_postconditions": effective_postconditions,
            }
    return {
        "status": "complete",
        "reasoning": "learned skill postconditions are already satisfied",
        "actions": [],
        "skill": identity,
        "bound_parameters": parameters,
        "effective_postconditions": effective_postconditions,
    }


def evaluate_skill_preconditions(skill: Any, world_state: dict) -> list[str]:
    preconditions = _skill_value(skill, "preconditions", {})
    required_inventory = _skill_value(skill, "required_inventory", [])
    required_observations = _skill_value(skill, "required_observations", [])
    if not required_inventory:
        required_inventory = _skill_value(skill, "required_items", [])
    inventory = _inventory(world_state)
    issues = []
    inventory_requirements = preconditions.get("inventory", {}) if isinstance(preconditions, dict) else {}
    if isinstance(inventory_requirements, dict):
        for item, count in inventory_requirements.items():
            needed = max(1, _safe_int(count, 1))
            if ingredient_count(str(item), inventory) < needed:
                issues.append(f"inventory:{item}>={needed}")
    for requirement in required_inventory if isinstance(required_inventory, list) else []:
        if isinstance(requirement, dict):
            item = str(requirement.get("item") or requirement.get("name") or "").strip()
            needed = max(1, _safe_int(requirement.get("count"), 1))
        else:
            item, needed = str(requirement or "").strip(), 1
        if item and ingredient_count(item, inventory) < needed:
            issues.append(f"inventory:{item}>={needed}")
    nearby_requirements = (
        preconditions.get("nearby_block_present", [])
        if isinstance(preconditions, dict)
        else []
    )
    if isinstance(nearby_requirements, str):
        nearby_requirements = [nearby_requirements]
    distance_limits = (
        preconditions.get("nearby_block_max_distance", {})
        if isinstance(preconditions, dict)
        else {}
    )
    for block in nearby_requirements if isinstance(nearby_requirements, list) else []:
        name = _safe_name(block)
        limit = _safe_float(distance_limits.get(name), 4.5) if isinstance(distance_limits, dict) else 4.5
        if name and not _nearby_block_observed(world_state, name, limit):
            issues.append(f"nearby_block:{name}<={limit:g}")
    for requirement in required_observations if isinstance(required_observations, list) else []:
        observation = str(requirement or "").strip().lower()
        if observation == "inventory" and not isinstance(world_state.get("inventory"), dict):
            issues.append("observation:inventory")
        elif observation.startswith("nearby_block:"):
            name = _safe_name(observation.split(":", 1)[1])
            limit = _safe_float(distance_limits.get(name), 4.5) if isinstance(distance_limits, dict) else 4.5
            if name and not _nearby_block_observed(world_state, name, limit):
                issues.append(f"nearby_block:{name}<={limit:g}")
        elif observation.startswith("observed_block:"):
            name = _safe_name(observation.split(":", 1)[1])
            if name and not _observed_blocks(world_state, {name}, 32.0):
                issues.append(f"observation:observed_block:{name}")
    return sorted(set(issues))


def _nearby_block_observed(world_state: dict, name: str, max_distance: float) -> bool:
    position = world_state.get("position", {}) if isinstance(world_state.get("position"), dict) else {}
    values = world_state.get("nearby_blocks", [])
    if isinstance(values, dict):
        values = list(values.values())
    for item in values if isinstance(values, list) else []:
        if isinstance(item, str):
            if _safe_name(item) == name:
                return True
            continue
        if not isinstance(item, dict):
            continue
        observed_name = _safe_name(item.get("name") or item.get("block") or item.get("type"))
        if observed_name != name:
            continue
        distance = item.get("distance")
        if distance is None and isinstance(item.get("position"), dict):
            distance = _distance(position, item["position"])
        if distance is None or _safe_float(distance, max_distance + 1.0) <= max_distance:
            return True
    return False


def evaluate_skill_postconditions(skill: Any, world_state: dict) -> tuple[bool, list[str]]:
    postconditions = _skill_value(skill, "postconditions", {})
    inventory_targets = _inventory_targets(postconditions)
    inventory = _inventory(world_state)
    missing = [
        f"inventory:{item}>={count}"
        for item, count in inventory_targets.items()
        if inventory.get(item, 0) < count
    ]
    if not inventory_targets:
        return False, ["postconditions_missing"]
    return not missing, missing


def _bind_postconditions(skill: Any, template: dict, parameters: dict) -> dict:
    inventory_targets = _inventory_targets(_skill_value(skill, "postconditions", {}))
    for phase in template.get("phases", []):
        if not isinstance(phase, dict):
            continue
        target_item = _safe_name(phase.get("target_item"))
        if not target_item:
            continue
        target_count = phase.get("target_count", 1)
        if isinstance(target_count, dict):
            target_count = parameters.get(
                target_count.get("parameter"),
                target_count.get("default", 1),
            )
        inventory_targets[target_item] = max(1, _safe_int(target_count, 1))
    return {"inventory": inventory_targets}


def _normalize_phase(raw: Any, index: int, issues: list[str], warnings: list[str]) -> dict:
    if not isinstance(raw, dict):
        issues.append(f"phase_{index}_must_be_object")
        return {}
    op = str(raw.get("op") or "").strip()
    if op not in ALLOWED_OPERATIONS:
        issues.append(f"phase_{index}_unsupported_operation")
        return {}
    phase_id = str(raw.get("id") or f"phase_{index + 1}").strip()[:64]
    if op == "craft_item":
        item = _safe_name(raw.get("item"))
        target_item = _safe_name(raw.get("target_item") or item)
        if not item or not target_item:
            issues.append(f"phase_{index}_craft_item_required")
        return {
            "id": phase_id,
            "op": op,
            "item": item,
            "count": _bounded_int(raw.get("count", 1), 1, 64, 1),
            "target_item": target_item,
            "target_count": _normalize_target_count(raw.get("target_count", 1), index, issues),
        }
    source_blocks = raw.get("source_blocks", [])
    if not isinstance(source_blocks, list):
        source_blocks = [source_blocks]
    source_blocks = list(dict.fromkeys(_safe_name(item) for item in source_blocks if _safe_name(item)))[:8]
    target_item = _safe_name(raw.get("target_item"))
    if not source_blocks:
        issues.append(f"phase_{index}_source_blocks_required")
    if not target_item:
        issues.append(f"phase_{index}_target_item_required")
    selector = str(raw.get("selector") or "nearest_observed").strip()
    if selector != "nearest_observed":
        issues.append(f"phase_{index}_unsupported_selector")
    return {
        "id": phase_id,
        "op": op,
        "source_blocks": source_blocks,
        "target_item": target_item,
        "target_count": _normalize_target_count(raw.get("target_count", 1), index, issues),
        "selector": "nearest_observed",
        "search_radius": _bounded_float(raw.get("search_radius", 32), 1.0, 64.0, 32.0),
        "interaction_range": _bounded_float(raw.get("interaction_range", 4.5), 1.0, 6.0, 4.5),
        "navigation_tolerance": _bounded_float(raw.get("navigation_tolerance", 1.75), 0.5, 4.0, 1.75),
    }


def _normalize_target_count(value: Any, index: int, issues: list[str]) -> Any:
    if isinstance(value, dict):
        parameter = _safe_name(value.get("parameter"))
        if not parameter:
            issues.append(f"phase_{index}_target_parameter_required")
        return {"parameter": parameter, "default": _bounded_int(value.get("default", 1), 1, 64, 1)}
    return _bounded_int(value, 1, 64, 1)


def _bind_parameters(template: dict, goal: str) -> tuple[dict, str]:
    definitions = template.get("parameters", {}) if isinstance(template.get("parameters"), dict) else {}
    values = {}
    goal_numbers = [int(value) for value in re.findall(r"\b(\d{1,3})\b", str(goal or ""))]
    for name, definition in definitions.items():
        definition = definition if isinstance(definition, dict) else {}
        minimum = _bounded_int(definition.get("minimum", 1), 1, 64, 1)
        maximum = _bounded_int(definition.get("maximum", 64), minimum, 64, 64)
        value = goal_numbers[0] if name == "quantity" and goal_numbers else definition.get("default", minimum)
        value = _safe_int(value, minimum)
        if value < minimum or value > maximum:
            return {}, f"parameter_outside_transfer_scope:{name}"
        values[str(name)] = value
    return values, ""


def _plan_phase(phase: dict, parameters: dict, world_state: dict, max_actions: int) -> dict:
    target_count = phase.get("target_count", 1)
    if isinstance(target_count, dict):
        target_count = parameters.get(target_count.get("parameter"), target_count.get("default", 1))
    target_count = max(1, _safe_int(target_count, 1))
    inventory = _inventory(world_state)
    target_item = phase["target_item"]
    current = inventory.get(target_item, 0)
    if current >= target_count:
        return {"status": "complete", "actions": []}
    remaining = target_count - current
    if phase["op"] == "craft_item":
        return {
            "status": "in_progress",
            "reasoning": f"bounded skill crafts {phase['item']}",
            "actions": [{
                "type": "craft",
                "parameters": {"item": phase["item"], "count": min(remaining, phase["count"])},
            }],
            "phase_id": phase["id"],
        }

    candidates = _observed_blocks(world_state, set(phase["source_blocks"]), phase["search_radius"])
    if not candidates:
        return _fallback({}, "required_observation_missing", [f"observed_block:{name}" for name in phase["source_blocks"]])
    position = world_state.get("position", {}) if isinstance(world_state.get("position"), dict) else {}
    reachable = [
        item for item in candidates
        if _flat_distance(position, item["position"]) <= phase["navigation_tolerance"]
        and _distance(position, item["position"]) <= phase["interaction_range"]
    ]
    if reachable:
        actions = []
        for item in reachable[: min(remaining, max_actions)]:
            pos = item["position"]
            actions.append({
                "type": "dig",
                "parameters": {
                    "block": item["name"],
                    "x": round(float(pos["x"])),
                    "y": round(float(pos["y"])),
                    "z": round(float(pos["z"])),
                },
            })
        return {
            "status": "in_progress",
            "reasoning": f"bounded skill acquires {target_item} from observed blocks",
            "actions": actions,
            "phase_id": phase["id"],
        }
    target = candidates[0]["position"]
    return {
        "status": "in_progress",
        "reasoning": f"bounded skill approaches observed {candidates[0]['name']}",
        "actions": [{
            "type": "move_to",
            "parameters": {
                "x": float(target["x"]),
                "z": float(target["z"]),
                "tolerance": phase["navigation_tolerance"],
            },
        }],
        "phase_id": phase["id"],
    }


def _observed_blocks(world_state: dict, names: set[str], radius: float) -> list[dict]:
    position = world_state.get("position", {}) if isinstance(world_state.get("position"), dict) else {}
    found: dict[tuple, dict] = {}
    for key in ("trees_found", "nearby_blocks", "grounded_resources", "visible_blocks", "resources"):
        values = world_state.get(key, [])
        if isinstance(values, dict):
            values = list(values.values())
        if not isinstance(values, list):
            continue
        for item in values:
            if not isinstance(item, dict):
                continue
            name = _safe_name(item.get("name") or item.get("block") or item.get("type"))
            block_position = item.get("position", {}) if isinstance(item.get("position"), dict) else {}
            if name not in names or not all(axis in block_position for axis in ("x", "y", "z")):
                continue
            distance = _distance(position, block_position)
            if distance > radius:
                continue
            identity = (name, round(float(block_position["x"])), round(float(block_position["y"])), round(float(block_position["z"])))
            found[identity] = {"name": name, "position": block_position, "distance": distance}
    return sorted(found.values(), key=lambda item: item["distance"])


def _skill_template(skill: Any) -> dict:
    template = _skill_value(skill, "bounded_action_template", {})
    if isinstance(template, dict) and template:
        return template
    implementation = _skill_value(skill, "implementation", "")
    if isinstance(implementation, dict):
        return implementation
    if isinstance(implementation, str):
        try:
            parsed = json.loads(implementation)
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _skill_identity(skill: Any) -> dict:
    return {
        "skill_id": str(_skill_value(skill, "skill_id", "") or _skill_value(skill, "name", "")),
        "name": str(_skill_value(skill, "name", "")),
        "version": str(_skill_value(skill, "version", "")),
        "status": str(_skill_value(skill, "status", "candidate")),
        "task_family": str(_skill_value(skill, "task_family", "")),
    }


def _skill_value(skill: Any, name: str, default: Any) -> Any:
    if isinstance(skill, dict):
        return skill.get(name, default)
    return getattr(skill, name, default)


def _fallback(identity: dict, reason: str, issues: list[str] | None = None) -> dict:
    return {
        "status": "fallback",
        "reasoning": reason,
        "fallback_reason": reason,
        "issues": list(issues or []),
        "actions": [],
        "skill": identity,
    }


def _inventory_targets(postconditions: Any) -> dict[str, int]:
    if not isinstance(postconditions, dict):
        return {}
    inventory = postconditions.get("inventory", {})
    if not isinstance(inventory, dict):
        return {}
    return {
        str(item): max(1, _safe_int(count, 1))
        for item, count in inventory.items()
        if str(item or "").strip()
    }


def _inventory(world_state: dict) -> dict[str, int]:
    inventory = world_state.get("inventory", {}) if isinstance(world_state, dict) else {}
    if not isinstance(inventory, dict):
        return {}
    return {str(item): max(0, _safe_int(count, 0)) for item, count in inventory.items()}


def _forbidden_paths(value: Any, path: str = "template") -> list[str]:
    found = []
    if isinstance(value, dict):
        for key, nested in value.items():
            key_text = str(key).strip().lower()
            child = f"{path}.{key_text}"
            if key_text in FORBIDDEN_KEYS:
                found.append(child)
            found.extend(_forbidden_paths(nested, child))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            found.extend(_forbidden_paths(nested, f"{path}[{index}]"))
    return found


def _json_data(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=True, default=str))


def _safe_name(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if re.fullmatch(r"[a-z][a-z0-9_]{0,63}", text) else ""


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _bounded_int(value: Any, minimum: int, maximum: int, default: int) -> int:
    return max(minimum, min(maximum, _safe_int(value, default)))


def _bounded_float(value: Any, minimum: float, maximum: float, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return round(max(minimum, min(maximum, number)), 4)


def _distance(left: dict, right: dict) -> float:
    try:
        return math.sqrt(sum((float(left.get(axis, 0)) - float(right.get(axis, 0))) ** 2 for axis in ("x", "y", "z")))
    except (TypeError, ValueError):
        return float("inf")


def _flat_distance(left: dict, right: dict) -> float:
    try:
        return math.sqrt(sum((float(left.get(axis, 0)) - float(right.get(axis, 0))) ** 2 for axis in ("x", "z")))
    except (TypeError, ValueError):
        return float("inf")
