"""Fixed M2 protocol, root-plan schema, and state-grounded task verifiers."""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

from singularity.data.knowledge_base import INGREDIENT_EQUIVALENTS
from singularity.evaluation.m1_protocol import inventory_counts


PROTOCOL_PATH = Path(__file__).resolve().parent.parent / "data" / "m2_protocol.json"
PROTOCOL_BYTES = PROTOCOL_PATH.read_bytes()
PROTOCOL = json.loads(PROTOCOL_BYTES.decode("utf-8"))
PROTOCOL_SHA256 = hashlib.sha256(PROTOCOL_BYTES).hexdigest()
TASKS_BY_ID = {str(task["id"]): task for task in PROTOCOL["tasks"]}

ROOT_PLAN_SCHEMA_VERSION = str(PROTOCOL["planner_schema"]["schema_version"])
_NODE_ID = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")


def canonical_sha256(value) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def protocol_integrity_report() -> dict:
    expected = {
        "planner_schema_sha256": canonical_sha256(PROTOCOL.get("planner_schema", {})),
        "reset_protocol_sha256": canonical_sha256(PROTOCOL.get("reset_contract", {})),
        "validation_protocol_sha256": canonical_sha256(PROTOCOL.get("validation_contract", {})),
    }
    mismatches = [
        name
        for name, actual in expected.items()
        if str(PROTOCOL.get(name) or "") != actual
    ]
    ingredient_policy = PROTOCOL.get("ingredient_equivalence_policy", {})
    canonical_ingredient = str(ingredient_policy.get("canonical_ingredient") or "")
    if (
        str(ingredient_policy.get("id") or "") != "minecraft-planks-tag-v1"
        or list(ingredient_policy.get("applies_to") or []) != [
            "action_verifier",
            "knowledge_base",
            "learned_skill_preconditions",
            "learned_skill_contract_readiness",
        ]
        or list(INGREDIENT_EQUIVALENTS.get(canonical_ingredient, ()))
        != list(ingredient_policy.get("members") or [])
    ):
        mismatches.append("ingredient_equivalence_policy")
    if int(PROTOCOL["llm_transport_policy"].get("sdk_max_retries", -1)) != int(
        PROTOCOL["deadline_policy"].get("planner_max_retries", -2)
    ):
        mismatches.append("llm_transport_sdk_retry_policy")
    return {
        "passed": not mismatches,
        "protocol_sha256": PROTOCOL_SHA256,
        "expected_hashes": expected,
        "mismatches": mismatches,
    }


def task_spec(task_id: str) -> dict:
    return TASKS_BY_ID.get(str(task_id or "").upper().strip(), {})


def validate_root_plan(
    value,
    *,
    expected_goal: str,
    expected_kind: str = "root",
) -> dict:
    """Validate an LLM response before it can create executable scheduler tasks."""
    issues: list[str] = []
    plan = value if isinstance(value, dict) else {}
    if not isinstance(value, dict):
        issues.append("plan_not_object")

    if plan.get("schema_version") != ROOT_PLAN_SCHEMA_VERSION:
        issues.append("schema_version_mismatch")
    if plan.get("plan_kind") != expected_kind:
        issues.append("plan_kind_mismatch")
    if _normalized_text(plan.get("goal")) != _normalized_text(expected_goal):
        issues.append("goal_mismatch")

    allowed_statuses = set(PROTOCOL["planner_schema"]["allowed_statuses"])
    status = str(plan.get("status") or "")
    if status not in allowed_statuses:
        issues.append("status_invalid")
    if expected_kind == "root" and status != PROTOCOL["planner_schema"]["root_status"]:
        issues.append("root_status_not_planning")
    if not str(plan.get("reasoning") or "").strip():
        issues.append("reasoning_missing")

    subtasks = plan.get("subtasks")
    if not isinstance(subtasks, list):
        issues.append("subtasks_not_array")
        subtasks = []
    minimum = int(PROTOCOL["planner_schema"]["min_root_subtasks"] if expected_kind == "root" else 1)
    maximum = int(PROTOCOL["planner_schema"]["max_subtasks"])
    if not minimum <= len(subtasks) <= maximum:
        issues.append("subtask_count_out_of_bounds")

    seen: set[str] = set()
    dependency_edges: list[dict] = []
    node_reports = []
    for index, raw_node in enumerate(subtasks):
        node_issues: list[str] = []
        node = raw_node if isinstance(raw_node, dict) else {}
        if not isinstance(raw_node, dict):
            node_issues.append("node_not_object")
        node_id = str(node.get("id") or "")
        if not _NODE_ID.fullmatch(node_id):
            node_issues.append("id_invalid")
        elif node_id in seen:
            node_issues.append("id_duplicate")
        title = str(node.get("title") or "").strip()
        if not title:
            node_issues.append("title_missing")
        if not str(node.get("type") or "").strip():
            node_issues.append("type_missing")
        try:
            priority = int(node.get("priority"))
        except (TypeError, ValueError):
            priority = 0
        if not 1 <= priority <= 5:
            node_issues.append("priority_invalid")
        if not isinstance(node.get("preconditions"), dict):
            node_issues.append("preconditions_not_object")
        if not _machine_criteria(node.get("success_criteria")):
            node_issues.append("success_criteria_not_machine_checkable")
        if not str(node.get("rationale") or "").strip():
            node_issues.append("rationale_missing")

        dependencies = node.get("depends_on")
        if not isinstance(dependencies, list):
            node_issues.append("depends_on_not_array")
            dependencies = []
        for dependency in dependencies:
            dependency_id = str(dependency or "")
            if dependency_id not in seen:
                node_issues.append("dependency_not_earlier_node")
            else:
                dependency_edges.append({"from": dependency_id, "to": node_id})

        node_reports.append({
            "index": index,
            "id": node_id,
            "title": title,
            "depends_on": [str(item or "") for item in dependencies],
            "issues": sorted(set(node_issues)),
        })
        issues.extend(f"subtask[{index}]:{issue}" for issue in node_issues)
        if _NODE_ID.fullmatch(node_id):
            seen.add(node_id)

    if expected_kind == "root" and len(dependency_edges) < 1:
        issues.append("dependent_subtasks_missing")

    actions = plan.get("actions")
    if not isinstance(actions, list):
        issues.append("actions_not_array")
        actions = []
    if len(actions) > int(PROTOCOL["planner_schema"]["max_actions_per_call"]):
        issues.append("action_count_out_of_bounds")
    if status == "planning" and not actions:
        issues.append("planning_actions_missing")
    allowed_actions = set(PROTOCOL["planner_schema"]["allowed_actions"])
    action_reports = []
    for index, raw_action in enumerate(actions):
        action_issues = []
        action = raw_action if isinstance(raw_action, dict) else {}
        action_type = str(action.get("type") or "")
        if not isinstance(raw_action, dict):
            action_issues.append("action_not_object")
        if action_type not in allowed_actions:
            action_issues.append("action_type_not_allowed")
        parameters = action.get("parameters")
        if not isinstance(parameters, dict):
            action_issues.append("parameters_not_object")
        else:
            action_issues.extend(_action_parameter_issues(action_type, parameters))
        issues.extend(f"action[{index}]:{issue}" for issue in action_issues)
        action_reports.append({
            "index": index,
            "type": action_type,
            "issues": action_issues,
        })

    return {
        "type": "m2_root_plan_schema_validation",
        "schema_version": ROOT_PLAN_SCHEMA_VERSION,
        "passed": not issues,
        "expected_kind": expected_kind,
        "expected_goal": expected_goal,
        "subtask_count": len(subtasks),
        "dependency_edge_count": len(dependency_edges),
        "dependency_edges": dependency_edges,
        "action_count": len(actions),
        "nodes": node_reports,
        "actions": action_reports,
        "issues": sorted(set(issues)),
    }


def _action_parameter_issues(action_type: str, parameters: dict) -> list[str]:
    contract = (PROTOCOL["planner_schema"].get("action_parameter_contracts") or {}).get(action_type)
    if not isinstance(contract, dict):
        return []

    issues: list[str] = []
    required = [str(name) for name in contract.get("required", [])]
    properties = contract.get("properties", {}) if isinstance(contract.get("properties"), dict) else {}
    for name in required:
        if name not in parameters:
            issues.append(f"parameter_missing:{name}")

    for name, value_type in properties.items():
        if name not in parameters:
            continue
        value = parameters[name]
        if value_type == "nonempty_string":
            if not isinstance(value, str) or not value.strip():
                issues.append(f"parameter_type:{name}:nonempty_string")
        elif value_type == "finite_number":
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                issues.append(f"parameter_type:{name}:finite_number")
        elif value_type == "positive_integer":
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                issues.append(f"parameter_type:{name}:positive_integer")
        else:
            issues.append(f"parameter_contract_type_unknown:{name}")

    if contract.get("allow_additional") is False:
        for name in parameters:
            if name not in properties:
                issues.append(f"parameter_unexpected:{name}")
    return issues


def verify_task_outcome(
    task_id: str,
    *,
    setup_evidence: dict,
    terminal_evidence: dict,
    action_events: list[dict] | None = None,
) -> dict:
    """Verify BM-006..010 using observed state, never planner completion text."""
    spec = task_spec(task_id)
    issues: list[str] = []
    if not spec:
        return {
            "type": "m2_task_outcome_validation",
            "task_id": task_id,
            "passed": False,
            "issues": ["unknown_task"],
        }

    before = inventory_counts((setup_evidence.get("after_state") or {}).get("inventory", {}))
    after = inventory_counts(terminal_evidence.get("inventory", {}))
    delta = {
        name: int(after.get(name, 0)) - int(before.get(name, 0))
        for name in sorted(set(before) | set(after))
    }
    criteria = spec.get("success_criteria", {})
    for item, required in (criteria.get("inventory") or {}).items():
        if int(after.get(item, 0)) < int(required):
            issues.append(f"inventory_missing:{item}")
    for item, required in (criteria.get("required_inventory_delta") or {}).items():
        if int(delta.get(item, 0)) < int(required):
            issues.append(f"inventory_delta_missing:{item}")
    inventory_any = criteria.get("inventory_any") or {}
    if inventory_any and not any(int(after.get(item, 0)) >= int(required) for item, required in inventory_any.items()):
        issues.append("inventory_any_missing")
    delta_any = criteria.get("required_inventory_delta_any") or {}
    if delta_any and not any(int(delta.get(item, 0)) >= int(required) for item, required in delta_any.items()):
        issues.append("inventory_delta_any_missing")

    action_proof = _action_proof(spec, action_events or [])
    issues.extend(action_proof["issues"])
    shelter_proof = {}
    if criteria.get("structure"):
        shelter_proof = verify_shelter_5x5(
            setup_evidence.get("structure_baseline", {}),
            terminal_evidence.get("structure_post", {}),
            terminal_evidence.get("player_position", {}),
        )
        if not shelter_proof["passed"]:
            issues.append("shelter_structure_invalid")

    return {
        "type": "m2_task_outcome_validation",
        "task_id": task_id,
        "passed": not issues,
        "planner_completion_trusted": False,
        "inventory_before": before,
        "inventory_after": after,
        "inventory_delta": delta,
        "action_proof": action_proof,
        "shelter_proof": shelter_proof,
        "issues": sorted(set(issues)),
    }


def verify_shelter_5x5(baseline: dict, post: dict, player_position: dict) -> dict:
    """Verify a 5x5 outer shelter from before/after block snapshots."""
    contract = PROTOCOL["validation_contract"]["shelter"]
    issues: list[str] = []
    baseline_blocks, baseline_origin = _snapshot_blocks(baseline)
    post_blocks, post_origin = _snapshot_blocks(post)
    origin = post_origin or baseline_origin
    if not origin:
        issues.append("structure_origin_missing")
        origin = {"x": 0, "y": 0, "z": 0}
    if baseline_origin and post_origin and baseline_origin != post_origin:
        issues.append("structure_origin_changed")

    ox, oy, oz = (int(origin[axis]) for axis in ("x", "y", "z"))
    width = int(contract["outer_width"])
    depth = int(contract["outer_depth"])
    wall_height = int(contract["minimum_wall_height"])
    allowed = set(contract["allowed_structure_blocks"])
    perimeter = [
        (x, z)
        for x in range(ox, ox + width)
        for z in range(oz, oz + depth)
        if x in {ox, ox + width - 1} or z in {oz, oz + depth - 1}
    ]
    wall_positions = [
        (x, oy + level, z)
        for x, z in perimeter
        for level in range(wall_height)
    ]
    roof_y = oy + wall_height
    roof_positions = [
        (x, roof_y, z)
        for x in range(ox, ox + width)
        for z in range(oz, oz + depth)
    ]
    interior_positions = [
        (x, y, z)
        for x in range(ox + 1, ox + width - 1)
        for z in range(oz + 1, oz + depth - 1)
        for y in range(oy, oy + wall_height)
    ]

    wall_solid = [position for position in wall_positions if post_blocks.get(position, "air") in allowed]
    roof_solid = [position for position in roof_positions if post_blocks.get(position, "air") in allowed]
    wall_coverage = len(wall_solid) / len(wall_positions) if wall_positions else 0.0
    roof_coverage = len(roof_solid) / len(roof_positions) if roof_positions else 0.0
    if wall_coverage < float(contract["minimum_wall_coverage"]):
        issues.append("wall_coverage_below_minimum")
    if roof_coverage < float(contract["minimum_roof_coverage"]):
        issues.append("roof_coverage_below_minimum")

    missing_wall = [position for position in wall_positions if post_blocks.get(position, "air") not in allowed]
    entrance_columns = {}
    for x, y, z in missing_wall:
        entrance_columns.setdefault((x, z), set()).add(y)
    valid_entrances = [
        position
        for position, levels in entrance_columns.items()
        if set(range(oy, oy + int(contract["entrance_height"]))).issubset(levels)
    ]
    if len(valid_entrances) != int(contract["entrance_width"]):
        issues.append("entrance_invalid")

    interior_blocked = [
        position
        for position in interior_positions
        if post_blocks.get(position, "air") != "air"
    ]
    if interior_blocked:
        issues.append("interior_not_traversable")

    counted_positions = wall_solid + roof_solid
    episode_delta_positions = [
        position
        for position in counted_positions
        if baseline_blocks.get(position, "air") == "air"
        and post_blocks.get(position, "air") in allowed
    ]
    if len(episode_delta_positions) != len(counted_positions):
        issues.append("counted_structure_not_episode_delta")

    player_inside = _player_inside(player_position, origin, width, depth, wall_height)
    if contract.get("player_inside_required") and not player_inside:
        issues.append("player_not_inside_protected_area")

    return {
        "type": "m2_shelter_5x5_validation",
        "structure_id": contract["structure_id"],
        "passed": not issues,
        "origin": origin,
        "wall_positions": len(wall_positions),
        "wall_solid": len(wall_solid),
        "wall_coverage": round(wall_coverage, 4),
        "roof_positions": len(roof_positions),
        "roof_solid": len(roof_solid),
        "roof_coverage": round(roof_coverage, 4),
        "entrance_columns": [list(position) for position in sorted(valid_entrances)],
        "interior_blocked_count": len(interior_blocked),
        "episode_delta_block_count": len(episode_delta_positions),
        "player_inside": player_inside,
        "issues": sorted(set(issues)),
    }


def _action_proof(spec: dict, events: list[dict]) -> dict:
    successful = []
    for event in events:
        data = event.get("data", event) if isinstance(event, dict) else {}
        action = data.get("action", {}) if isinstance(data.get("action"), dict) else {}
        result = data.get("result", {}) if isinstance(data.get("result"), dict) else {}
        if result.get("success") is True:
            successful.append({
                "type": str(action.get("type") or result.get("action_type") or ""),
                "action": action,
                "result": result,
                "pre_observation": data.get("pre_observation", {}),
                "post_observation": data.get("post_observation", {}),
            })
    types = [item["type"] for item in successful]
    criteria = spec.get("success_criteria", {})
    issues = []
    for required in criteria.get("required_action_types", []):
        if required not in types:
            issues.append(f"required_action_missing:{required}")

    source_blocks = set(criteria.get("required_source_blocks", []))
    if source_blocks:
        grounded = any(
            item["type"] == "dig"
            and str(item["result"].get("block") or item["result"].get("target_block_before", {}).get("name") or "") in source_blocks
            and item["result"].get("block_removed") is True
            and item["result"].get("pickup_observed") is True
            for item in successful
        )
        if not grounded:
            issues.append("grounded_source_dig_missing")

    if spec.get("id") == "BM-007":
        equip_indices = [i for i, item in enumerate(successful) if item["type"] == "equip" and item["action"].get("parameters", {}).get("item") == "wooden_pickaxe"]
        dig_indices = [i for i, item in enumerate(successful) if item["type"] == "dig" and item["result"].get("block") == "stone"]
        if not equip_indices or not dig_indices or min(equip_indices) > min(dig_indices):
            issues.append("wooden_pickaxe_not_equipped_before_stone_dig")
    if spec.get("id") == "BM-006":
        allowed_logs = set(criteria.get("required_source_blocks", []))
        log_dig = any(
            item["type"] == "dig"
            and str(
                item["result"].get("block")
                or item["result"].get("target_block_before", {}).get("name")
                or ""
            ) in allowed_logs
            and item["result"].get("block_removed") is True
            and item["result"].get("pickup_observed") is True
            for item in successful
        )
        table_craft = any(
            item["type"] == "craft"
            and str(item["action"].get("parameters", {}).get("item") or item["result"].get("item") or "") == "crafting_table"
            for item in successful
        )
        if not log_dig:
            issues.append("grounded_log_gather_missing")
        if not table_craft:
            issues.append("crafting_table_action_missing")
    if spec.get("id") == "BM-008":
        coal_route = any(
            item["type"] == "dig"
            and item["result"].get("block") == "coal_ore"
            and item["result"].get("pickup_observed") is True
            for item in successful
        )
        charcoal_route = any(
            item["type"] in {"smelt", "craft"}
            and str(item["result"].get("item") or item["action"].get("parameters", {}).get("item") or "") == "charcoal"
            for item in successful
        )
        if not (coal_route or charcoal_route):
            issues.append("coal_or_charcoal_strategy_unproved")
        if coal_route:
            equip_index = next((i for i, item in enumerate(successful) if item["type"] == "equip" and item["action"].get("parameters", {}).get("item") == "wooden_pickaxe"), None)
            coal_index = next((i for i, item in enumerate(successful) if item["type"] == "dig" and item["result"].get("block") == "coal_ore"), None)
            if equip_index is None or coal_index is None or equip_index > coal_index:
                issues.append("wooden_pickaxe_not_equipped_before_coal_dig")
    if spec.get("id") == "BM-009":
        stick_craft = next((i for i, item in enumerate(successful) if item["type"] == "craft" and item["action"].get("parameters", {}).get("item") == "stick"), None)
        torch_craft = next((i for i, item in enumerate(successful) if item["type"] == "craft" and item["action"].get("parameters", {}).get("item") == "torch"), None)
        if stick_craft is None or torch_craft is None or stick_craft > torch_craft:
            issues.append("torch_prerequisite_chain_unproved")

    return {
        "passed": not issues,
        "successful_action_count": len(successful),
        "successful_action_types": types,
        "issues": sorted(set(issues)),
    }


def _snapshot_blocks(snapshot: dict) -> tuple[dict[tuple[int, int, int], str], dict]:
    if not isinstance(snapshot, dict):
        return {}, {}
    origin = snapshot.get("origin", {}) if isinstance(snapshot.get("origin"), dict) else {}
    normalized_origin = {}
    try:
        normalized_origin = {axis: int(math.floor(float(origin[axis]))) for axis in ("x", "y", "z")}
    except (KeyError, TypeError, ValueError):
        normalized_origin = {}
    blocks = {}
    for item in snapshot.get("blocks", []) or []:
        if not isinstance(item, dict):
            continue
        position = item.get("position", {}) if isinstance(item.get("position"), dict) else {}
        try:
            key = tuple(int(math.floor(float(position[axis]))) for axis in ("x", "y", "z"))
        except (KeyError, TypeError, ValueError):
            continue
        blocks[key] = str(item.get("name") or "air")
    return blocks, normalized_origin


def _player_inside(player: dict, origin: dict, width: int, depth: int, wall_height: int) -> bool:
    try:
        x = float(player["x"])
        y = float(player["y"])
        z = float(player["z"])
    except (KeyError, TypeError, ValueError):
        return False
    ox, oy, oz = (float(origin[axis]) for axis in ("x", "y", "z"))
    return bool(
        ox + 1 <= x < ox + width - 1
        and oz + 1 <= z < oz + depth - 1
        and oy <= y < oy + wall_height + 1
    )


def _machine_criteria(value) -> bool:
    if not isinstance(value, dict) or not value:
        return False
    allowed = {
        "inventory",
        "inventory_any",
        "observed",
        "nearby_block_present",
        "position_near",
        "structure",
        "action",
        "result",
        "flags",
    }
    return any(key in allowed for key in value)


def _normalized_text(value) -> str:
    return " ".join(str(value or "").strip().lower().split())
