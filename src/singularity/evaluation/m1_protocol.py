"""Shared M1 protocol and state-transition evidence helpers."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path


PROTOCOL_PATH = Path(__file__).resolve().parent.parent / "data" / "m1_protocol.json"
PROTOCOL_BYTES = PROTOCOL_PATH.read_bytes()
PROTOCOL = json.loads(PROTOCOL_BYTES.decode("utf-8"))
PROTOCOL_SHA256 = hashlib.sha256(PROTOCOL_BYTES).hexdigest()
TASKS_BY_ID = {str(task["id"]): task for task in PROTOCOL["tasks"]}


def inventory_counts(value) -> dict[str, int]:
    """Normalize observation/result inventory payloads to positive item counts."""
    counts: dict[str, int] = {}
    if isinstance(value, dict):
        items = value.items()
    elif isinstance(value, list):
        items = (
            (item.get("name"), item.get("count", 1))
            for item in value
            if isinstance(item, dict)
        )
    else:
        return counts
    for raw_name, raw_count in items:
        name = str(raw_name or "").strip()
        try:
            count = int(raw_count or 0)
        except (TypeError, ValueError):
            continue
        if name and count > 0:
            counts[name] = counts.get(name, 0) + count
    return counts


def task_spec(task_id: str) -> dict:
    return TASKS_BY_ID.get(str(task_id or "").upper().strip(), {})


def expected_action_type(task_id: str) -> str:
    return "dig" if str(task_id or "").upper().strip() in {"BM-001", "BM-004"} else "craft"


def action_transition_proof(task_id: str, data: dict) -> dict:
    """Verify one successful M1 dig/craft from its logged pre/post observations."""
    spec = task_spec(task_id)
    action = data.get("action", {}) if isinstance(data.get("action"), dict) else {}
    result = data.get("result", {}) if isinstance(data.get("result"), dict) else {}
    action_type = str(action.get("type") or result.get("action_type") or "")
    required_action = expected_action_type(task_id)
    relevant = action_type == required_action and result.get("success") is True
    if not relevant:
        return {"relevant": False, "passed": False, "action_type": action_type, "issues": []}

    before = data.get("pre_observation", {}) if isinstance(data.get("pre_observation"), dict) else {}
    after = data.get("post_observation", {}) if isinstance(data.get("post_observation"), dict) else {}
    criteria = spec.get("success_criteria", {}) if isinstance(spec.get("success_criteria"), dict) else {}
    target_item = next(iter(criteria), "")
    before_inventory = inventory_counts(before.get("inventory", {}))
    after_inventory = inventory_counts(after.get("inventory", {}))
    before_count = int(before_inventory.get(target_item, 0) or 0)
    after_count = int(after_inventory.get(target_item, 0) or 0)
    issues = []
    if not before or not after:
        issues.append("pre_post_observation_missing")
    if not target_item or after_count <= before_count:
        issues.append("target_inventory_did_not_increase")

    proof = {
        "relevant": True,
        "passed": False,
        "action_type": action_type,
        "target_item": target_item,
        "before_count": before_count,
        "after_count": after_count,
        "inventory_delta": after_count - before_count,
        "issues": issues,
    }
    parameters = action.get("parameters", {}) if isinstance(action.get("parameters"), dict) else {}
    if required_action == "craft":
        crafted_item = str(parameters.get("item") or result.get("item") or "")
        proof["crafted_item"] = crafted_item
        if crafted_item != target_item:
            issues.append("crafted_item_does_not_match_target")
    else:
        target = _finite_block_position(parameters)
        proof["grounded_position"] = target
        if not target:
            issues.append("dig_coordinates_not_grounded")
        source_blocks = {
            str(name)
            for name in spec.get("evidence", {}).get("source_blocks", [])
            if name
        }
        before_block = _block_name_at(before, target) if target else ""
        after_block = _block_name_at(after, target) if target else ""
        proof["before_block"] = before_block
        proof["after_block"] = after_block
        proof["source_blocks"] = sorted(source_blocks)
        if not before_block or (source_blocks and before_block not in source_blocks):
            issues.append("source_block_not_observed_before_dig")
        if before_block and after_block == before_block:
            issues.append("source_block_unchanged_after_dig")

    proof["passed"] = not issues
    return proof


def _finite_block_position(parameters: dict) -> dict:
    values = {}
    for axis in ("x", "y", "z"):
        try:
            value = float(parameters.get(axis))
        except (TypeError, ValueError):
            return {}
        if not math.isfinite(value):
            return {}
        values[axis] = math.floor(value)
    return values


def _block_name_at(observation: dict, target: dict) -> str:
    expected = (target["x"], target["y"], target["z"])
    direct = observation.get("action_target_block", {})
    if isinstance(direct, dict):
        position = direct.get("position", {}) if isinstance(direct.get("position"), dict) else {}
        try:
            observed = tuple(math.floor(float(position.get(axis))) for axis in ("x", "y", "z"))
        except (TypeError, ValueError):
            observed = ()
        if observed == expected:
            return str(direct.get("name") or direct.get("type") or direct.get("block") or "")
    for key in ("nearby_blocks", "blocks", "visible_blocks", "grounded_resources"):
        for item in observation.get(key, []) or []:
            if not isinstance(item, dict):
                continue
            position = item.get("position", {}) if isinstance(item.get("position"), dict) else item
            try:
                observed = tuple(math.floor(float(position.get(axis))) for axis in ("x", "y", "z"))
            except (TypeError, ValueError):
                continue
            if observed == expected:
                return str(item.get("name") or item.get("type") or item.get("block") or "")
    return ""
