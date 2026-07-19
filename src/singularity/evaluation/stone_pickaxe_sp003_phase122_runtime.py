"""SP-003 Phase 122 bounded cardinal step-up egress overlay."""

from __future__ import annotations

import copy
import math
from typing import Any

from singularity.evaluation import stone_pickaxe_sp003_runtime as base
from singularity.evaluation import stone_pickaxe_sp003_phase120_runtime as phase120


SP003_PARTIAL_SHAFT_STEP_UP_POLICY_ID = (
    "sp003-partial-clearance-shaft-step-up-egress-v1"
)


def _machine_proven_step_up_egress(observation: Any, lock: dict) -> dict:
    raw = observation if isinstance(observation, dict) else {}
    scan = base._validated_complete_scan_index(
        raw.get("sp003_complete_local_scan")
    )
    if not scan:
        return {}
    origin = scan["origin_cell"]
    support = lock.get("support_cell")
    player = raw.get("position") if isinstance(raw.get("position"), dict) else {}
    player_coordinates = [
        base._finite(player.get(axis)) for axis in ("x", "y", "z")
    ]
    if (
        not isinstance(support, tuple)
        or len(support) != 3
        or any(value is None for value in player_coordinates)
        or tuple(math.floor(value) for value in player_coordinates) != origin
        or (origin[0], origin[2]) != (support[0], support[2])
        or not 1 <= origin[1] - support[1] <= base.SP003_CLEARANCE_SHAFT_MAX
    ):
        return {}

    by_cell = scan["by_cell"]
    inside_scan = scan["inside_scan"]
    air_proven = scan["air_proven"]
    support_block = by_cell.get(support)
    if not isinstance(support_block, dict) or support_block.get("name") != "stone":
        return {}
    shaft, _ = base._stone_surface_clearance_shaft(support, origin)
    if any(not inside_scan(cell) for cell in shaft):
        return {}
    occupied = [cell for cell in shaft if cell in by_cell]
    if (
        not occupied
        or any(
            str(by_cell[cell].get("name") or "")
            not in base.SP003_SURFACE_CLEARANCE_BLOCKS
            for cell in occupied
        )
        or any(cell not in by_cell and not air_proven(cell) for cell in shaft)
    ):
        return {}
    history_cells = list(lock.get("clearance_source_cells") or [])
    if (
        any(cell not in shaft for cell in history_cells)
        or len(set(history_cells)) != len(history_cells)
        or len(history_cells) + len(occupied) > base.SP003_CLEARANCE_SHAFT_MAX
    ):
        return {}

    current_feet = origin
    current_head = (origin[0], origin[1] + 1, origin[2])
    if (
        not inside_scan(current_feet)
        or not inside_scan(current_head)
        or not air_proven(current_feet)
        or not air_proven(current_head)
    ):
        return {}

    top_down = sorted(occupied, key=lambda cell: cell[1], reverse=True)
    candidates = []
    for dx, dz in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        ground = (origin[0] + dx, origin[1], origin[2] + dz)
        stand = (ground[0], ground[1] + 1, ground[2])
        head = (stand[0], stand[1] + 1, stand[2])
        if any(not inside_scan(cell) for cell in (ground, stand, head)):
            continue
        ground_block = by_cell.get(ground)
        if (
            not isinstance(ground_block, dict)
            or str(ground_block.get("name") or "")
            not in phase120.SP003_SHAFT_EGRESS_GROUND_BLOCKS
            or not air_proven(stand)
            or not air_proven(head)
        ):
            continue
        position = {
            "x": stand[0] + 0.5,
            "y": stand[1],
            "z": stand[2] + 0.5,
        }
        distance = math.sqrt(
            (float(position["x"]) - player_coordinates[0]) ** 2
            + (float(position["y"]) - player_coordinates[1]) ** 2
            + (float(position["z"]) - player_coordinates[2]) ** 2
        )
        candidates.append((distance, stand, ground, head, ground_block, position))
    if not candidates:
        return {}
    distance, stand, ground, head, ground_block, position = sorted(
        candidates,
        key=lambda item: (round(item[0], 9), item[1]),
    )[0]
    proof = {
        "type": "sp003_partial_clearance_shaft_step_up_egress_proof",
        "schema_version": 1,
        "policy_id": SP003_PARTIAL_SHAFT_STEP_UP_POLICY_ID,
        "parent_policy_id": phase120.SP003_PARTIAL_SHAFT_CONTINUATION_POLICY_ID,
        **base._scan_proof_base(scan),
        "locked_support_source_id": lock["support_source_id"],
        "locked_support_position": {
            "x": support[0],
            "y": support[1],
            "z": support[2],
        },
        "locked_clearance_count": lock["clearance_count"],
        "locked_clearance_source_ids": list(lock["clearance_source_ids"]),
        "locked_clearance_proof_fingerprints": list(
            lock["clearance_proof_fingerprints"]
        ),
        "player_in_locked_support_column": True,
        "remaining_obstruction_source_ids_top_down": [
            base.source_id(
                str(by_cell[cell]["name"]),
                {"x": cell[0], "y": cell[1], "z": cell[2]},
            )
            for cell in top_down
        ],
        "remaining_obstruction_count": len(top_down),
        "clearance_episode_maximum_unchanged": base.SP003_SURFACE_CLEARANCE_MAX,
        "clearance_shaft_maximum_unchanged": base.SP003_CLEARANCE_SHAFT_MAX,
        "current_feet_position": {
            "x": current_feet[0],
            "y": current_feet[1],
            "z": current_feet[2],
        },
        "current_feet_cell_state": "air",
        "current_head_position": {
            "x": current_head[0],
            "y": current_head[1],
            "z": current_head[2],
        },
        "current_head_cell_state": "air",
        "egress_stand_position": copy.deepcopy(position),
        "egress_ground_position": {
            "x": ground[0],
            "y": ground[1],
            "z": ground[2],
        },
        "egress_ground_block": str(ground_block["name"]),
        "egress_ground_source_id": base.source_id(
            str(ground_block["name"]),
            {"x": ground[0], "y": ground[1], "z": ground[2]},
        ),
        "egress_feet_position": {
            "x": stand[0],
            "y": stand[1],
            "z": stand[2],
        },
        "egress_feet_cell_state": "air",
        "egress_head_position": {
            "x": head[0],
            "y": head[1],
            "z": head[2],
        },
        "egress_head_cell_state": "air",
        "egress_cardinal_step_count": 1,
        "egress_horizontal_manhattan_distance": 1,
        "egress_vertical_delta": 1,
        "inventory_preservation_required": True,
        "attempt_limit": 1,
        "world_mutation": False,
    }
    fingerprint = base.canonical_sha256(proof)
    return {
        "source_id": (
            f"sp003_clearance_shaft_step_up_egress:"
            f"{stand[0]}:{stand[1]}:{stand[2]}"
        ),
        "name": "sp003_clearance_shaft_step_up_egress",
        "position": copy.deepcopy(position),
        "stand_position": copy.deepcopy(position),
        "distance": round(float(distance), 6),
        "navigation_only": True,
        "stone_clearance_shaft_step_up_egress": True,
        "locked_support_source_id": lock["support_source_id"],
        "shaft_step_up_egress_proof": proof,
        "shaft_step_up_egress_proof_fingerprint": fingerprint,
    }


def _table_staging_state(
    observation: Any,
    progress: Any,
    *,
    attempted_egress_fingerprints: set[str] | None = None,
) -> dict:
    parent = phase120._table_staging_state(
        observation,
        progress,
        attempted_egress_fingerprints=attempted_egress_fingerprints,
    )
    if parent.get("blocker") != "locked_partial_shaft_machine_egress_unavailable":
        return parent
    lock = parent.get("partial_shaft_lock")
    if not isinstance(lock, dict):
        return parent
    egress = _machine_proven_step_up_egress(observation, lock)
    if not egress:
        return parent
    attempted = attempted_egress_fingerprints or set()
    fingerprint = egress["shaft_step_up_egress_proof_fingerprint"]
    report = copy.deepcopy(parent)
    report.update(
        {
            "policy_id": SP003_PARTIAL_SHAFT_STEP_UP_POLICY_ID,
            "parent_policy_id": phase120.SP003_PARTIAL_SHAFT_CONTINUATION_POLICY_ID,
            "blocked": False,
            "target_mode": "locked_shaft_step_up_egress",
            "target": egress,
        }
    )
    report.pop("blocker", None)
    if fingerprint in attempted:
        report["blocked"] = True
        report["target"] = {}
        report.pop("target_mode", None)
        report["blocker"] = "locked_partial_shaft_step_up_egress_attempt_exhausted"
        report["attempted_egress_proof_fingerprint"] = fingerprint
    return report


def _guard_step_up_egress(action: Any, observation: Any, target: dict) -> dict:
    value = action if isinstance(action, dict) else {}
    params = (
        value.get("parameters")
        if isinstance(value.get("parameters"), dict)
        else {}
    )
    action_type = str(value.get("type") or "")
    normalized = {"type": action_type, "parameters": dict(params)}
    issues = []
    if value.get("skill_context"):
        issues.append("sp003_partial_shaft_step_up_skill_context_forbidden")
    if action_type != "move_to":
        issues.append("sp003_partial_shaft_step_up_navigation_required")
    if set(params) not in ({"x", "z"}, {"x", "y", "z"}):
        issues.append("sp003_partial_shaft_step_up_parameters_unexpected")
    if action_type == "move_to":
        issues.extend(
            base._non_mutating_action_issues(action_type, params, observation, 2.5)
        )
    if not base._navigation_coordinates_match(params, target, tolerance=0.01):
        issues.append("sp003_partial_shaft_step_up_target_mismatch")
    if not issues:
        normalized["parameters"] = {
            **copy.deepcopy(target["stand_position"]),
            "tolerance": base.SP003_EXACT_MOVE_CONTINUOUS_TOLERANCE,
            "preserve_inventory": True,
        }
    return {"issues": issues, "action": normalized}


def guard_sp003_phase122_action(
    action: Any,
    observation: Any,
    progress: Any,
    *,
    arm: str = "baseline",
    attempted_egress_fingerprints: set[str] | None = None,
) -> dict:
    params = (
        action.get("parameters")
        if isinstance(action, dict)
        and isinstance(action.get("parameters"), dict)
        else {}
    )
    staging = _table_staging_state(
        observation,
        progress,
        attempted_egress_fingerprints=attempted_egress_fingerprints,
    )
    if staging.get("target_mode") != "locked_shaft_step_up_egress":
        report = copy.deepcopy(
            phase120.guard_sp003_phase120_action(
                action,
                observation,
                progress,
                arm=arm,
                attempted_egress_fingerprints=attempted_egress_fingerprints,
            )
        )
        report.update(
            {
                "type": "stone_pickaxe_sp003_phase122_action_guard",
                "policy_id": SP003_PARTIAL_SHAFT_STEP_UP_POLICY_ID,
                "parent_policy_id": (
                    phase120.SP003_PARTIAL_SHAFT_CONTINUATION_POLICY_ID
                ),
            }
        )
        return report

    target = staging["target"]
    guarded = _guard_step_up_egress(action, observation, target)
    issues = sorted(set(guarded["issues"]))
    normalized = guarded["action"]
    fingerprint = target["shaft_step_up_egress_proof_fingerprint"]
    return {
        "type": "stone_pickaxe_sp003_phase122_action_guard",
        "schema_version": 1,
        "policy_id": SP003_PARTIAL_SHAFT_STEP_UP_POLICY_ID,
        "parent_policy_id": phase120.SP003_PARTIAL_SHAFT_CONTINUATION_POLICY_ID,
        "mode": "sp003",
        "arm": str(arm or "").strip().lower(),
        "stage": "prepare_wooden_pickaxe",
        "allowed": not issues,
        "issues": issues,
        "action": copy.deepcopy(normalized),
        "selected_source": copy.deepcopy(target) if not issues else {},
        "action_repair": {
            "type": "sp003_phase122_partial_shaft_step_up_binding",
            "schema_version": 1,
            "policy_id": SP003_PARTIAL_SHAFT_STEP_UP_POLICY_ID,
            "target_mode": "locked_shaft_step_up_egress",
            "locked_support_source_id": str(
                staging["partial_shaft_lock"].get("support_source_id") or ""
            ),
            "attempt_limit": 1,
            "attempt_count": 1,
            "proof_fingerprint": fingerprint,
            "inventory_preservation_required": True,
            "world_mutation": False,
        }
        if not issues
        else {},
        "progress": base._progress_snapshot(progress),
        "table_staging": copy.deepcopy(staging),
        "parameter_normalization": {
            "type": "sp003_phase122_step_up_parameter_binding",
            "schema_version": 1,
            "policy_id": SP003_PARTIAL_SHAFT_STEP_UP_POLICY_ID,
            "applicable": True,
            "applied": not issues,
            "original_parameter_keys": sorted(str(key) for key in params),
            "world_mutation": False,
            "planner_retry": False,
        },
        "runtime_influence": True,
    }


class StonePickaxeSP003Phase122RuntimeAgent(
    phase120.StonePickaxeSP003Phase120RuntimeAgent
):
    """Add one scan-proven cardinal step-up from a locked partial shaft."""

    def _observe(self) -> dict:
        observation = dict(super()._observe())
        staging = _table_staging_state(
            observation,
            self.sp003_progress,
            attempted_egress_fingerprints=(
                self._sp003_phase120_egress_attempted_fingerprints
            ),
        )
        if staging.get("target_mode") == "locked_shaft_step_up_egress":
            observation["sp003_table_staging"] = copy.deepcopy(staging)
            observation["sp003_targets"] = [copy.deepcopy(staging["target"])]
        return observation

    def _verify_action_for_execution(
        self,
        action: dict,
        observation: dict,
        goal: str,
        context: dict = None,
    ):
        guard = guard_sp003_phase122_action(
            action,
            observation,
            self.sp003_progress,
            arm=self.sp003_arm,
            attempted_egress_fingerprints=(
                self._sp003_phase120_egress_attempted_fingerprints
            ),
        )
        self.session_logger.log(
            "stone_pickaxe_sp003_action_guard",
            {"goal": goal, "context": context or {}, **guard},
            level="INFO" if guard["allowed"] else "ERROR",
        )
        if not guard["allowed"]:
            verification = {
                "action_type": str(action.get("type") or "unknown"),
                "status": "reject",
                "score": 0.0,
                "reason": "; ".join(guard["issues"]),
                "policy_id": guard["policy_id"],
                "guard": guard,
            }
            return verification, {
                "success": False,
                "error": f"SP-003 action guard rejected: {verification['reason']}",
                "action_type": verification["action_type"],
                "duration_ms": 0,
                "action_verification": verification,
                "verification_blocked": True,
            }
        repair = guard.get("action_repair") or {}
        if repair.get("target_mode") in {
            "locked_shaft_egress",
            "locked_shaft_step_up_egress",
        }:
            fingerprint = str(repair.get("proof_fingerprint") or "")
            if fingerprint:
                self._sp003_phase120_egress_attempted_fingerprints.add(fingerprint)
        normalized = (
            guard.get("action") if isinstance(guard.get("action"), dict) else {}
        )
        skill_context = (
            action.get("skill_context")
            if isinstance(action.get("skill_context"), dict)
            else None
        )
        action.clear()
        action.update(normalized)
        if skill_context:
            action["skill_context"] = dict(skill_context)
        return base.Agent._verify_action_for_execution(
            self,
            action,
            observation,
            goal,
            context,
        )


__all__ = [
    "SP003_PARTIAL_SHAFT_STEP_UP_POLICY_ID",
    "StonePickaxeSP003Phase122RuntimeAgent",
    "guard_sp003_phase122_action",
]
