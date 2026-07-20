"""SP-003 Phase 120 bounded partial-shaft continuation overlay."""

from __future__ import annotations

import copy
import math
from typing import Any

from singularity.evaluation import stone_pickaxe_sp003_runtime as base
from singularity.evaluation import stone_pickaxe_sp003_phase116_runtime as phase116
from singularity.evaluation import stone_pickaxe_sp003_phase118_runtime as phase118


SP003_PARTIAL_SHAFT_CONTINUATION_POLICY_ID = (
    "sp003-partial-clearance-shaft-continuation-v1"
)
SP003_SHAFT_EGRESS_GROUND_BLOCKS = {
    "coarse_dirt",
    "dirt",
    "grass_block",
    "podzol",
    "stone",
}


def _parsed_source_id(
    value: Any,
    *,
    expected_name: str = "",
) -> tuple[str, tuple[int, int, int]] | None:
    parts = str(value or "").split(":")
    if len(parts) != 4 or (expected_name and parts[0] != expected_name):
        return None
    try:
        cell = tuple(int(item) for item in parts[1:])
    except (TypeError, ValueError):
        return None
    if str(value) != f"{parts[0]}:{cell[0]}:{cell[1]}:{cell[2]}":
        return None
    return parts[0], cell


def _sha256_fingerprint(value: Any) -> str:
    fingerprint = str(value or "").lower()
    if len(fingerprint) != 64 or any(
        character not in "0123456789abcdef" for character in fingerprint
    ):
        return ""
    return fingerprint


def _partial_clearance_lock(progress: Any) -> dict:
    state = base._progress_snapshot(progress)
    cleared = set(state["surface_clearance_source_ids"])
    by_support: dict[str, list[dict]] = {}
    support_history: list[str] = []
    seen_sources: set[str] = set()
    for mutation in state["successful_mutations"]:
        if not isinstance(mutation, dict):
            continue
        source = str(mutation.get("source_id") or "")
        support = str(mutation.get("support_source_id") or "")
        parsed_source = _parsed_source_id(source)
        parsed_support = _parsed_source_id(support, expected_name="stone")
        fingerprint = _sha256_fingerprint(mutation.get("proof_fingerprint"))
        if (
            str(mutation.get("block") or "") not in base.SP003_SURFACE_CLEARANCE_BLOCKS
            or source not in cleared
            or parsed_source is None
            or parsed_source[0] not in base.SP003_SURFACE_CLEARANCE_BLOCKS
            or parsed_support is None
            or not fingerprint
            or source in seen_sources
        ):
            continue
        source_cell = parsed_source[1]
        support_cell = parsed_support[1]
        if (
            (source_cell[0], source_cell[2])
            != (support_cell[0], support_cell[2])
            or not 1
            <= source_cell[1] - support_cell[1]
            <= base.SP003_CLEARANCE_SHAFT_MAX
        ):
            continue
        seen_sources.add(source)
        if support not in by_support:
            by_support[support] = []
        by_support[support].append(
            {
                "source_id": source,
                "source_cell": source_cell,
                "proof_fingerprint": fingerprint,
            }
        )
        support_history.append(support)
    if not support_history:
        return {}
    support_id = support_history[-1]
    removals = by_support[support_id]
    if not 1 <= len(removals) <= base.SP003_CLEARANCE_SHAFT_MAX:
        return {}
    return {
        "support_source_id": support_id,
        "support_cell": _parsed_source_id(support_id, expected_name="stone")[1],
        "clearance_count": len(removals),
        "clearance_source_ids": [item["source_id"] for item in removals],
        "clearance_source_cells": [item["source_cell"] for item in removals],
        "clearance_proof_fingerprints": [
            item["proof_fingerprint"] for item in removals
        ],
    }


def _locked_candidate(observation: Any, progress: Any, lock: dict) -> dict:
    support_id = str(lock.get("support_source_id") or "")
    for candidate in base._safe_stone_candidates(observation, progress):
        if (
            candidate.get("support_source_id") == support_id
            or candidate.get("source_id") == support_id
        ):
            return copy.deepcopy(candidate)

    raw = observation if isinstance(observation, dict) else {}
    scan_report = raw.get("sp003_complete_local_scan")
    records = raw.get("sp003_stone_pickup_accesses")
    records = records if isinstance(records, list) else []
    expected = {
        item["source_id"]: item
        for item in base._stone_pickup_accesses(scan_report)
    }.get(support_id, {})
    record = next(
        (
            item
            for item in records
            if isinstance(item, dict) and item.get("source_id") == support_id
        ),
        {},
    )
    if expected and base.canonical_sha256(record) == base.canonical_sha256(expected):
        return copy.deepcopy(expected)
    return {}


def _machine_proven_shaft_egress(observation: Any, lock: dict) -> dict:
    raw = observation if isinstance(observation, dict) else {}
    scan = base._validated_complete_scan_index(
        raw.get("sp003_complete_local_scan")
    )
    if not scan:
        return {}
    origin = scan["origin_cell"]
    support = lock.get("support_cell")
    player = raw.get("position") if isinstance(raw.get("position"), dict) else {}
    player_coordinates = [base._finite(player.get(axis)) for axis in ("x", "y", "z")]
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

    top_down = sorted(occupied, key=lambda cell: cell[1], reverse=True)
    candidates = []
    for dx, dz in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        stand = (origin[0] + dx, origin[1], origin[2] + dz)
        ground = (stand[0], stand[1] - 1, stand[2])
        head = (stand[0], stand[1] + 1, stand[2])
        if any(not inside_scan(cell) for cell in (stand, ground, head)):
            continue
        ground_block = by_cell.get(ground)
        if (
            not air_proven(stand)
            or not air_proven(head)
            or not isinstance(ground_block, dict)
            or str(ground_block.get("name") or "")
            not in SP003_SHAFT_EGRESS_GROUND_BLOCKS
        ):
            continue
        position = {
            "x": stand[0] + 0.5,
            "y": stand[1],
            "z": stand[2] + 0.5,
        }
        distance = math.hypot(
            float(position["x"]) - player_coordinates[0],
            float(position["z"]) - player_coordinates[2],
        )
        candidates.append((distance, stand, ground, head, ground_block, position))
    if not candidates:
        return {}
    distance, stand, ground, head, ground_block, position = sorted(
        candidates,
        key=lambda item: (round(item[0], 9), item[1]),
    )[0]
    proof = {
        "type": "sp003_partial_clearance_shaft_egress_proof",
        "schema_version": 1,
        "policy_id": SP003_PARTIAL_SHAFT_CONTINUATION_POLICY_ID,
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
        "inventory_preservation_required": True,
        "attempt_limit": 1,
        "world_mutation": False,
    }
    fingerprint = base.canonical_sha256(proof)
    return {
        "source_id": f"sp003_clearance_shaft_egress:{stand[0]}:{stand[1]}:{stand[2]}",
        "name": "sp003_clearance_shaft_egress",
        "position": copy.deepcopy(position),
        "stand_position": copy.deepcopy(position),
        "distance": round(float(distance), 6),
        "navigation_only": True,
        "stone_clearance_shaft_egress": True,
        "locked_support_source_id": lock["support_source_id"],
        "shaft_egress_proof": proof,
        "shaft_egress_proof_fingerprint": fingerprint,
    }


def _table_staging_state(
    observation: Any,
    progress: Any,
    *,
    attempted_egress_fingerprints: set[str] | None = None,
) -> dict:
    parent = phase116._table_staging_state(observation, progress)
    if not parent.get("active"):
        return parent
    lock = _partial_clearance_lock(progress)
    if not lock:
        return parent

    report = {
        "type": "sp003_table_staging_state",
        "schema_version": 1,
        "policy_id": SP003_PARTIAL_SHAFT_CONTINUATION_POLICY_ID,
        "parent_policy_id": phase116.SP003_TABLE_STAGING_POLICY_ID,
        "active": True,
        "ready_for_table_placement": False,
        "blocked": False,
        "target": {},
        "partial_shaft_lock": copy.deepcopy(lock),
    }
    candidate = _locked_candidate(observation, progress, lock)
    if candidate.get("stone_pickup_access") is True:
        report["ready_for_table_placement"] = True
        report["pickup_access_source_id"] = lock["support_source_id"]
        return report
    if candidate.get("stone_surface_clearance") is True:
        report["target_mode"] = "locked_surface_clearance"
        report["target"] = candidate
        return report
    if (
        candidate.get("stone_clearance_probe") is True
        or candidate.get("stone_pickup_approach") is True
    ):
        candidate["navigation_only"] = True
        report["target_mode"] = "locked_navigation"
        report["target"] = candidate
        return report

    state = base._progress_snapshot(progress)
    if state["surface_clearance_removal_count"] >= base.SP003_SURFACE_CLEARANCE_MAX:
        report["blocked"] = True
        report["blocker"] = "locked_partial_shaft_episode_clearance_limit_reached"
        return report
    egress = _machine_proven_shaft_egress(observation, lock)
    if not egress:
        report["blocked"] = True
        report["blocker"] = "locked_partial_shaft_machine_egress_unavailable"
        return report
    attempted = attempted_egress_fingerprints or set()
    if egress["shaft_egress_proof_fingerprint"] in attempted:
        report["blocked"] = True
        report["blocker"] = "locked_partial_shaft_egress_attempt_exhausted"
        report["attempted_egress_proof_fingerprint"] = (
            egress["shaft_egress_proof_fingerprint"]
        )
        return report
    report["target_mode"] = "locked_shaft_egress"
    report["target"] = egress
    return report


def _guard_locked_navigation(action: Any, observation: Any, target: dict) -> dict:
    value = action if isinstance(action, dict) else {}
    params = value.get("parameters") if isinstance(value.get("parameters"), dict) else {}
    action_type = str(value.get("type") or "")
    normalized = {"type": action_type, "parameters": dict(params)}
    issues = []
    if value.get("skill_context"):
        issues.append("sp003_locked_shaft_navigation_skill_context_forbidden")
    if action_type != "move_to":
        issues.append("sp003_locked_shaft_navigation_required")
    if set(params) not in ({"x", "z"}, {"x", "y", "z"}):
        issues.append("sp003_locked_shaft_navigation_parameters_unexpected")
    if action_type == "move_to":
        issues.extend(base._non_mutating_action_issues(action_type, params, observation, 32.0))
    if not base._navigation_coordinates_match(params, target, tolerance=0.01):
        issues.append("sp003_locked_shaft_navigation_target_mismatch")
    if not issues:
        stand = target.get("stand_position")
        if target.get("stone_pickup_approach") is True and isinstance(stand, dict):
            normalized["parameters"].update(copy.deepcopy(stand))
            normalized["parameters"]["x"] = math.floor(float(stand["x"])) + 0.5
            normalized["parameters"]["z"] = math.floor(float(stand["z"])) + 0.5
            normalized["parameters"]["tolerance"] = (
                base.SP003_EXACT_MOVE_CONTINUOUS_TOLERANCE
            )
        else:
            normalized["parameters"].pop("y", None)
            for axis in ("x", "z"):
                normalized["parameters"][axis] = (
                    math.floor(float(normalized["parameters"][axis])) + 0.5
                )
            normalized["parameters"]["tolerance"] = base.SP003_MOVE_TO_CONTINUOUS_TOLERANCE
        normalized["parameters"]["preserve_inventory"] = True
    return {"issues": issues, "action": normalized}


def _guard_locked_clearance(
    action: Any,
    observation: Any,
    progress: Any,
    target: dict,
) -> dict:
    value = action if isinstance(action, dict) else {}
    params = value.get("parameters") if isinstance(value.get("parameters"), dict) else {}
    action_type = str(value.get("type") or "")
    normalized = {"type": action_type, "parameters": dict(params)}
    issues = []
    if value.get("skill_context"):
        issues.append("sp003_locked_shaft_clearance_skill_context_forbidden")
    if action_type != "dig":
        issues.append("sp003_locked_shaft_clearance_required")
    if set(params) != {"block", "x", "y", "z"}:
        issues.append("sp003_locked_shaft_clearance_parameters_unexpected")
    block = str(params.get("block") or "")
    target_id = base.source_id(block, params)
    if block not in base.SP003_SURFACE_CLEARANCE_BLOCKS:
        issues.append("sp003_locked_shaft_clearance_block_forbidden")
    if not base._coordinates_match(params, target):
        issues.append("sp003_locked_shaft_clearance_target_mismatch")
    if target_id != target.get("source_id"):
        issues.append("sp003_locked_shaft_clearance_source_mismatch")
    state = base._progress_snapshot(progress)
    if state["surface_clearance_removal_count"] >= base.SP003_SURFACE_CLEARANCE_MAX:
        issues.append("sp003_surface_clearance_removal_limit_reached")
    if not issues:
        proof = copy.deepcopy(target["clearance_proof"])
        normalized["parameters"].update(
            {
                "source_id": target_id,
                "stone_surface_clearance": True,
                "support_source_id": target["support_source_id"],
                "surface_clearance_proof": proof,
                "surface_clearance_proof_fingerprint": base.canonical_sha256(proof),
            }
        )
    return {"issues": issues, "action": normalized}


def _guard_shaft_egress(action: Any, observation: Any, target: dict) -> dict:
    value = action if isinstance(action, dict) else {}
    params = value.get("parameters") if isinstance(value.get("parameters"), dict) else {}
    action_type = str(value.get("type") or "")
    normalized = {"type": action_type, "parameters": dict(params)}
    issues = []
    if value.get("skill_context"):
        issues.append("sp003_partial_shaft_egress_skill_context_forbidden")
    if action_type != "move_to":
        issues.append("sp003_partial_shaft_egress_navigation_required")
    if set(params) not in ({"x", "z"}, {"x", "y", "z"}):
        issues.append("sp003_partial_shaft_egress_parameters_unexpected")
    if action_type == "move_to":
        issues.extend(base._non_mutating_action_issues(action_type, params, observation, 2.0))
    if not base._navigation_coordinates_match(params, target, tolerance=0.01):
        issues.append("sp003_partial_shaft_egress_target_mismatch")
    if not issues:
        normalized["parameters"] = {
            **copy.deepcopy(target["stand_position"]),
            "tolerance": base.SP003_EXACT_MOVE_CONTINUOUS_TOLERANCE,
            "preserve_inventory": True,
        }
    return {"issues": issues, "action": normalized}


def guard_sp003_phase120_action(
    action: Any,
    observation: Any,
    progress: Any,
    *,
    arm: str = "baseline",
    attempted_egress_fingerprints: set[str] | None = None,
) -> dict:
    staging = _table_staging_state(
        observation,
        progress,
        attempted_egress_fingerprints=attempted_egress_fingerprints,
    )
    lock = staging.get("partial_shaft_lock")
    if not isinstance(lock, dict):
        report = copy.deepcopy(
            phase118.guard_sp003_phase118_action(
                action,
                observation,
                progress,
                arm=arm,
            )
        )
        report.update(
            {
                "type": "stone_pickaxe_sp003_phase120_action_guard",
                "policy_id": SP003_PARTIAL_SHAFT_CONTINUATION_POLICY_ID,
                "parent_policy_id": phase118.SP003_EXACT_NAVIGATION_PARAMETER_POLICY_ID,
            }
        )
        return report

    target = staging.get("target") if isinstance(staging.get("target"), dict) else {}
    parent_selected_source = {}
    parent_action_repair = {}
    if staging.get("ready_for_table_placement") is True:
        guarded = base.guard_sp003_action(action, observation, progress, arm=arm)
        parent_selected_source = (
            copy.deepcopy(guarded.get("selected_source"))
            if isinstance(guarded.get("selected_source"), dict)
            else {}
        )
        parent_action_repair = (
            copy.deepcopy(guarded.get("action_repair"))
            if isinstance(guarded.get("action_repair"), dict)
            else {}
        )
    elif staging.get("target_mode") == "locked_surface_clearance":
        guarded = _guard_locked_clearance(action, observation, progress, target)
    elif staging.get("target_mode") == "locked_navigation":
        guarded = _guard_locked_navigation(action, observation, target)
    elif staging.get("target_mode") == "locked_shaft_egress":
        guarded = _guard_shaft_egress(action, observation, target)
    else:
        value = action if isinstance(action, dict) else {}
        guarded = {
            "issues": ["sp003_locked_partial_shaft_machine_target_required"],
            "action": {
                "type": str(value.get("type") or ""),
                "parameters": copy.deepcopy(value.get("parameters") or {}),
            },
        }

    issues = sorted(set(guarded.get("issues") or []))
    normalized = guarded.get("action") if isinstance(guarded.get("action"), dict) else {}
    proof_fingerprint = str(target.get("shaft_egress_proof_fingerprint") or "")
    target_mode = str(staging.get("target_mode") or "table_placement")
    if target_mode == "locked_surface_clearance":
        world_mutation: bool | str = "one_machine_proven_surface_clearance"
    elif target_mode == "table_placement":
        world_mutation = "one_machine_bound_crafting_table_placement"
    else:
        world_mutation = False
    action_repair = {
        "type": "sp003_phase120_partial_shaft_binding",
        "schema_version": 1,
        "policy_id": SP003_PARTIAL_SHAFT_CONTINUATION_POLICY_ID,
        "target_mode": target_mode,
        "locked_support_source_id": str(lock.get("support_source_id") or ""),
        "attempt_limit": 1,
        "attempt_count": 1,
        "proof_fingerprint": proof_fingerprint,
        "inventory_preservation_required": (
            target_mode == "locked_shaft_egress"
        ),
        "world_mutation": world_mutation,
    }
    if parent_action_repair:
        action_repair["parent_action_repair"] = parent_action_repair
    return {
        "type": "stone_pickaxe_sp003_phase120_action_guard",
        "schema_version": 1,
        "policy_id": SP003_PARTIAL_SHAFT_CONTINUATION_POLICY_ID,
        "parent_policy_id": phase118.SP003_EXACT_NAVIGATION_PARAMETER_POLICY_ID,
        "mode": "sp003",
        "arm": str(arm or "").strip().lower(),
        "stage": "prepare_wooden_pickaxe",
        "allowed": not issues,
        "issues": issues,
        "action": copy.deepcopy(normalized),
        "selected_source": (
            parent_selected_source or copy.deepcopy(target)
            if not issues
            else {}
        ),
        "action_repair": action_repair if not issues else {},
        "progress": base._progress_snapshot(progress),
        "table_staging": copy.deepcopy(staging),
        "parameter_normalization": {
            "type": "sp003_phase120_machine_target_parameter_binding",
            "schema_version": 1,
            "policy_id": SP003_PARTIAL_SHAFT_CONTINUATION_POLICY_ID,
            "applicable": bool(target),
            "applied": not issues,
            "original_parameter_keys": sorted(
                str(key)
                for key in (
                    (action.get("parameters") or {})
                    if isinstance(action, dict)
                    else {}
                )
            ),
            "world_mutation": False,
            "planner_retry": False,
        },
        "runtime_influence": True,
    }


class StonePickaxeSP003Phase120RuntimeAgent(
    phase118.StonePickaxeSP003Phase118RuntimeAgent
):
    """Keep a bounded table-staging clearance on one machine-proven shaft."""

    def __init__(self, *args, **kwargs):
        self._sp003_phase120_egress_attempted_fingerprints: set[str] = set()
        super().__init__(*args, **kwargs)

    def _observe(self) -> dict:
        observation = dict(super()._observe())
        staging = _table_staging_state(
            observation,
            self.sp003_progress,
            attempted_egress_fingerprints=(
                self._sp003_phase120_egress_attempted_fingerprints
            ),
        )
        if staging.get("active"):
            observation["sp003_table_staging"] = copy.deepcopy(staging)
            if staging.get("target"):
                observation["sp003_targets"] = [copy.deepcopy(staging["target"])]
            elif staging.get("ready_for_table_placement") is True:
                observation["sp003_targets"] = base._place_reference_candidates(
                    observation
                )[:8]
            elif staging.get("blocked") is True:
                observation["sp003_targets"] = []
        return observation

    def _effective_sp003_action_guard(
        self,
        action: dict,
        observation: dict,
    ) -> dict:
        return guard_sp003_phase120_action(
            action,
            observation,
            self.sp003_progress,
            arm=self.sp003_arm,
            attempted_egress_fingerprints=(
                self._sp003_phase120_egress_attempted_fingerprints
            ),
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
        repair = guard.get("action_repair") or {}
        if repair.get("target_mode") == "locked_shaft_egress":
            fingerprint = str(repair.get("proof_fingerprint") or "")
            if fingerprint:
                self._sp003_phase120_egress_attempted_fingerprints.add(fingerprint)
        normalized = guard.get("action") if isinstance(guard.get("action"), dict) else {}
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
    "SP003_PARTIAL_SHAFT_CONTINUATION_POLICY_ID",
    "StonePickaxeSP003Phase120RuntimeAgent",
    "guard_sp003_phase120_action",
]
