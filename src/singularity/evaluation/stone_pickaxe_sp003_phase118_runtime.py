"""SP-003 Phase 118 exact navigation parameter normalization overlay."""

from __future__ import annotations

import copy
from typing import Any

from singularity.evaluation import stone_pickaxe_sp003_runtime as base
from singularity.evaluation import stone_pickaxe_sp003_phase116_runtime as phase116


SP003_EXACT_NAVIGATION_PARAMETER_POLICY_ID = (
    "sp003-exact-navigation-parameter-normalization-v1"
)


def _normalize_exact_navigation_y(
    action: Any,
    observation: Any,
    progress: Any,
) -> tuple[dict, dict]:
    value = copy.deepcopy(action) if isinstance(action, dict) else {}
    params = value.get("parameters")
    params = params if isinstance(params, dict) else {}
    staging = phase116._table_staging_state(observation, progress)
    target = staging.get("target") if isinstance(staging.get("target"), dict) else {}
    navigation_target = bool(
        target.get("stone_clearance_probe") is True
        or target.get("stone_pickup_approach") is True
    )
    report = {
        "type": "sp003_phase118_exact_navigation_parameter_normalization",
        "schema_version": 1,
        "policy_id": SP003_EXACT_NAVIGATION_PARAMETER_POLICY_ID,
        "applicable": bool(
            staging.get("active") is True
            and staging.get("ready_for_table_placement") is not True
            and navigation_target
            and value.get("type") == "move_to"
        ),
        "applied": False,
        "original_parameter_keys": sorted(str(key) for key in params),
        "removed_parameter_keys": [],
        "exact_xyz_bound": False,
        "world_mutation": False,
        "planner_retry": False,
    }
    if not report["applicable"] or set(params) != {"x", "y", "z"}:
        return value, report
    if not base._coordinates_match(params, target, tolerance=0.01):
        return value, report

    value["parameters"].pop("y")
    report.update(
        {
            "applied": True,
            "removed_parameter_keys": ["y"],
            "exact_xyz_bound": True,
            "machine_target_source_id": str(target.get("source_id") or ""),
            "machine_target_position": copy.deepcopy(target.get("position") or {}),
        }
    )
    return value, report


def guard_sp003_phase118_action(
    action: Any,
    observation: Any,
    progress: Any,
    *,
    arm: str = "baseline",
) -> dict:
    normalized, normalization = _normalize_exact_navigation_y(
        action,
        observation,
        progress,
    )
    report = copy.deepcopy(
        phase116.guard_sp003_phase116_action(
            normalized,
            observation,
            progress,
            arm=arm,
        )
    )
    report.update(
        {
            "type": "stone_pickaxe_sp003_phase118_action_guard",
            "schema_version": 1,
            "policy_id": SP003_EXACT_NAVIGATION_PARAMETER_POLICY_ID,
            "parent_policy_id": phase116.SP003_TABLE_STAGING_POLICY_ID,
            "parameter_normalization": normalization,
        }
    )
    return report


class StonePickaxeSP003Phase118RuntimeAgent(
    phase116.StonePickaxeSP003Phase116RuntimeAgent
):
    """Accept an exact machine target with a redundant matching y parameter."""

    def _verify_action_for_execution(
        self,
        action: dict,
        observation: dict,
        goal: str,
        context: dict = None,
    ):
        guard = guard_sp003_phase118_action(
            action,
            observation,
            self.sp003_progress,
            arm=self.sp003_arm,
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
    "SP003_EXACT_NAVIGATION_PARAMETER_POLICY_ID",
    "StonePickaxeSP003Phase118RuntimeAgent",
    "guard_sp003_phase118_action",
]
