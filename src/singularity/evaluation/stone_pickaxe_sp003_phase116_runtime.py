"""SP-003 Phase 116 local crafting-table staging overlay."""

from __future__ import annotations

import copy
import math
from typing import Any

from singularity.evaluation import stone_pickaxe_sp003_runtime as base


SP003_TABLE_STAGING_POLICY_ID = "sp003-local-crafting-table-staging-v1"


def _table_staging_state(observation: Any, progress: Any) -> dict:
    """Select one bounded stone-access action before the table is placed."""
    state = base._progress_snapshot(progress)
    inventory = base._safe_inventory(observation)
    active = bool(
        base._stage(observation, progress) == "prepare_wooden_pickaxe"
        and state["crafting_table_craft_count"] == 1
        and state["crafting_table_place_count"] == 0
        and inventory.get("crafting_table", 0) == 1
        and not base._nearby_crafting_table_observed(observation)
    )
    report = {
        "type": "sp003_table_staging_state",
        "schema_version": 1,
        "policy_id": SP003_TABLE_STAGING_POLICY_ID,
        "active": active,
        "ready_for_table_placement": False,
        "blocked": False,
        "target": {},
    }
    if not active:
        return report

    candidates = base._safe_stone_candidates(observation, progress)
    first = copy.deepcopy(candidates[0]) if candidates else {}
    if first.get("stone_pickup_access") is True:
        report["ready_for_table_placement"] = True
        report["pickup_access_source_id"] = str(first.get("source_id") or "")
        return report
    if first.get("stone_surface_clearance") is True:
        report["target_mode"] = "surface_clearance"
        report["target"] = first
        return report
    if (
        first.get("stone_clearance_probe") is True
        or first.get("stone_pickup_approach") is True
    ):
        first["navigation_only"] = True
        report["target_mode"] = "navigation"
        report["target"] = first
        return report

    report["blocked"] = True
    report["blocker"] = "machine_proven_stone_access_target_unavailable"
    return report


def _table_staging_target(observation: Any, progress: Any) -> dict:
    return copy.deepcopy(_table_staging_state(observation, progress)["target"])


def guard_sp003_phase116_action(
    action: Any,
    observation: Any,
    progress: Any,
    *,
    arm: str = "baseline",
) -> dict:
    staging = _table_staging_state(observation, progress)
    target = staging["target"]
    if not staging["active"] or staging["ready_for_table_placement"]:
        return base.guard_sp003_action(
            action,
            observation,
            progress,
            arm=arm,
        )

    value = action if isinstance(action, dict) else {}
    params = (
        value.get("parameters")
        if isinstance(value.get("parameters"), dict)
        else {}
    )
    action_type = str(value.get("type") or "")
    normalized = {"type": action_type, "parameters": dict(params)}
    issues: list[str] = []
    selected_source = {}
    action_repair = {}
    skill_context = (
        value.get("skill_context")
        if isinstance(value.get("skill_context"), dict)
        else {}
    )

    if skill_context:
        issues.append("sp003_table_staging_skill_context_forbidden")
    if not target:
        issues.append("sp003_table_staging_machine_target_required")
    elif (
        target.get("stone_clearance_probe") is True
        or target.get("stone_pickup_approach") is True
    ):
        if action_type != "move_to":
            issues.append("sp003_table_staging_navigation_required")
        if set(params) != {"x", "z"}:
            issues.append("sp003_table_staging_move_requires_exact_xz")
        issues.extend(
            base._non_mutating_action_issues(
                action_type,
                params,
                observation,
                32.0,
            )
            if action_type == "move_to"
            else []
        )
        if not base._navigation_coordinates_match(params, target, tolerance=0.01):
            issues.append("sp003_table_staging_navigation_target_mismatch")
        if not issues:
            selected_source = copy.deepcopy(target)
            requested_target = {axis: params[axis] for axis in ("x", "z")}
            stand = target.get("stand_position")
            if (
                target.get("stone_pickup_approach") is True
                and isinstance(stand, dict)
                and all(
                    base._finite(stand.get(axis)) is not None
                    for axis in ("x", "y", "z")
                )
            ):
                normalized["parameters"].update(copy.deepcopy(stand))
                normalized["parameters"]["x"] = (
                    math.floor(float(normalized["parameters"]["x"])) + 0.5
                )
                normalized["parameters"]["z"] = (
                    math.floor(float(normalized["parameters"]["z"])) + 0.5
                )
                tolerance = base.SP003_EXACT_MOVE_CONTINUOUS_TOLERANCE
                failure_reclassification_allowed = False
            else:
                normalized["parameters"].pop("y", None)
                for axis in ("x", "z"):
                    normalized["parameters"][axis] = (
                        math.floor(float(normalized["parameters"][axis])) + 0.5
                    )
                tolerance = base.SP003_MOVE_TO_CONTINUOUS_TOLERANCE
                failure_reclassification_allowed = True
            normalized["parameters"]["tolerance"] = tolerance
            normalized["parameters"]["preserve_inventory"] = True
            action_repair = {
                "type": "sp003_phase116_table_staging_navigation_binding",
                "schema_version": 1,
                "policy_id": SP003_TABLE_STAGING_POLICY_ID,
                "attempt_limit": 1,
                "attempt_count": 1,
                "requested_target": requested_target,
                "selected_target": {
                    axis: normalized["parameters"][axis]
                    for axis in normalized["parameters"]
                    if axis in {"x", "y", "z", "tolerance"}
                },
                "failure_reclassification_allowed": (
                    failure_reclassification_allowed
                ),
                "inventory_preservation_required": True,
                "world_mutation": False,
            }
    elif target.get("stone_surface_clearance") is True:
        if action_type != "dig":
            issues.append("sp003_table_staging_clearance_required")
        if set(params) != {"block", "x", "y", "z"}:
            issues.append("sp003_table_staging_clearance_parameters_unexpected")
        block = str(params.get("block") or "")
        target_id = base.source_id(block, params)
        if block not in base.SP003_SURFACE_CLEARANCE_BLOCKS:
            issues.append("sp003_table_staging_clearance_block_forbidden")
        if not base._coordinates_match(params, target):
            issues.append("sp003_table_staging_clearance_target_mismatch")
        if target_id != target.get("source_id"):
            issues.append("sp003_table_staging_clearance_source_mismatch")
        state = base._progress_snapshot(progress)
        if state["surface_clearance_removal_count"] >= base.SP003_SURFACE_CLEARANCE_MAX:
            issues.append("sp003_surface_clearance_removal_limit_reached")
        if not issues:
            selected_source = copy.deepcopy(target)
            proof = copy.deepcopy(target["clearance_proof"])
            normalized["parameters"].update(
                {
                    "source_id": target_id,
                    "stone_surface_clearance": True,
                    "support_source_id": target["support_source_id"],
                    "surface_clearance_proof": proof,
                    "surface_clearance_proof_fingerprint": (
                        base.canonical_sha256(proof)
                    ),
                }
            )
            action_repair = {
                "type": "sp003_phase116_table_staging_clearance_binding",
                "schema_version": 1,
                "policy_id": SP003_TABLE_STAGING_POLICY_ID,
                "attempt_limit": 1,
                "attempt_count": 1,
                "selected_source_id": target_id,
                "support_source_id": target["support_source_id"],
                "proof_fingerprint": base.canonical_sha256(proof),
                "world_mutation": "one_machine_proven_surface_clearance",
            }
    else:
        issues.append("sp003_table_staging_machine_target_invalid")

    return {
        "type": "stone_pickaxe_sp003_phase116_action_guard",
        "schema_version": 1,
        "policy_id": SP003_TABLE_STAGING_POLICY_ID,
        "mode": "sp003",
        "arm": str(arm or "").strip().lower(),
        "stage": "prepare_wooden_pickaxe",
        "allowed": not issues,
        "issues": sorted(set(issues)),
        "action": normalized,
        "selected_source": selected_source,
        "action_repair": action_repair,
        "progress": base._progress_snapshot(progress),
        "table_staging": staging,
        "runtime_influence": True,
    }


class StonePickaxeSP003Phase116RuntimeAgent(base.StonePickaxeSP003RuntimeAgent):
    """Stage the single table beside proven stone access before tool crafting."""

    def _observe(self) -> dict:
        observation = dict(super()._observe())
        staging = _table_staging_state(observation, self.sp003_progress)
        if staging["active"]:
            observation["sp003_table_staging"] = copy.deepcopy(staging)
            if staging["target"]:
                observation["sp003_targets"] = [copy.deepcopy(staging["target"])]
            elif staging["blocked"]:
                observation["sp003_targets"] = []
        return observation

    def _effective_sp003_action_guard(
        self,
        action: dict,
        observation: dict,
    ) -> dict:
        return guard_sp003_phase116_action(
            action,
            observation,
            self.sp003_progress,
            arm=self.sp003_arm,
        )

    def _verify_action_for_execution(
        self,
        action: dict,
        observation: dict,
        goal: str,
        context: dict = None,
    ):
        guard = self._effective_sp003_action_guard(action, observation)
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
    "SP003_TABLE_STAGING_POLICY_ID",
    "StonePickaxeSP003Phase116RuntimeAgent",
    "_table_staging_state",
    "_table_staging_target",
    "guard_sp003_phase116_action",
]
