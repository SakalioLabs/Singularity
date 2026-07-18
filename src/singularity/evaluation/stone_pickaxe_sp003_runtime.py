"""Supplemental empty-hand runtime and evidence verifier for SP-003."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from dataclasses import replace
from pathlib import Path
from typing import Any

from singularity.core.agent import Agent
from singularity.core.config import Config
from singularity.core.goal_verifier import GoalVerification
from singularity.core.task_system import TaskStatus
from singularity.evaluation.stone_pickaxe_protocol import (
    PROTOCOL,
    PROTOCOL_SHA256,
    REPOSITORY_ROOT,
    canonical_sha256,
    verify_sp001_episode,
    verify_sp002_episode,
)
from singularity.evaluation.stone_pickaxe_sp002_runtime import (
    FORBIDDEN_COMMAND_TOKENS,
    LOG_ITEMS,
    StonePickaxeRuntimeAgent as StonePickaxeSP002RuntimeAgent,
    _compact_position,
    _count,
    _finite,
    _main_hand_item,
    _nearby_crafting_table_observed,
    _non_mutating_action_issues,
    evidence_observation,
    file_sha256,
    planner_request_controls_audit,
    read_json,
    runtime_controls,
    source_id,
    task_graph_snapshot,
    utc_now,
)


SP003_RUNTIME_POLICY_ID = "stone-pickaxe-sp003-empty-hand-runtime-v1"
SP003_ACTION_GUARD_POLICY_ID = "stone-pickaxe-sp003-action-guard-v1"
SP003_MACHINE_VERIFIER_ID = "stone-pickaxe-sp003-empty-hand-machine-verifier-v1"
SP003_AUTHORIZATION_TYPE = "stone_pickaxe_sp003_one_time_authorization"
SP003_POLICY_PATH = REPOSITORY_ROOT / "workspace/evals/stone_pickaxe_sp003_harness_policy.json"
SP003_AUTHORIZATION_PATH = REPOSITORY_ROOT / "workspace/evals/stone_pickaxe_sp003_next_authorization.json"
SP003_GOAL = (
    "From empty hands, gather wood, craft and place one crafting table, craft one "
    "wooden pickaxe, mine exactly three stone, and craft one stone pickaxe"
)

PLANK_BY_LOG = {
    "oak_log": "oak_planks",
    "spruce_log": "spruce_planks",
    "birch_log": "birch_planks",
    "jungle_log": "jungle_planks",
    "acacia_log": "acacia_planks",
    "dark_oak_log": "dark_oak_planks",
    "mangrove_log": "mangrove_planks",
    "cherry_log": "cherry_planks",
    "crimson_stem": "crimson_planks",
    "warped_stem": "warped_planks",
}
IRON_BLOCKS = {"iron_ore", "deepslate_iron_ore", "raw_iron_block"}
REPLACEABLE_BLOCKS = {
    "air",
    "cave_air",
    "void_air",
    "water",
    "lava",
    "grass",
    "short_grass",
    "tall_grass",
    "fern",
    "large_fern",
    "snow",
}
EXPECTED_SKILLS = {
    "learned:acquire_cobblestone": "1.1.0",
    "learned:craft_stone_pickaxe": "1.0.1",
}


def _policy() -> dict:
    return read_json(SP003_POLICY_PATH)


def _safe_inventory(observation: Any) -> dict[str, int]:
    raw = observation if isinstance(observation, dict) else {}
    inventory = raw.get("inventory") if isinstance(raw.get("inventory"), dict) else {}
    return {
        str(item): _count(count)
        for item, count in inventory.items()
        if str(item) and _count(count) > 0
    }


def _skill_records() -> dict[tuple[str, str], dict]:
    path = REPOSITORY_ROOT / "workspace/skills/custom_skills.jsonl"
    records: dict[tuple[str, str], dict] = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        key = (str(record.get("skill_id") or ""), str(record.get("version") or ""))
        records[key] = record
    return records


def verify_sp003_policy_identity(policy: Any = None) -> dict:
    value = policy if isinstance(policy, dict) else _policy()
    checks = {
        "policy_type": value.get("type") == "stone_pickaxe_sp003_harness_policy",
        "policy_schema": value.get("schema_version") == 1,
        "policy_id": value.get("id") == SP003_RUNTIME_POLICY_ID,
        "protocol_id": (value.get("protocol") or {}).get("id") == PROTOCOL["id"],
        "protocol_sha256": (
            (value.get("protocol") or {}).get("sha256") == PROTOCOL_SHA256
            and file_sha256(REPOSITORY_ROOT / (value.get("protocol") or {}).get("path", ""))
            == PROTOCOL_SHA256
        ),
        "protocol_immutable": (value.get("protocol") or {}).get("bytes_must_remain_unchanged") is True,
        "policy_task": (value.get("protocol") or {}).get("task_id") == "SP-003",
        "fresh_empty_start": (
            (value.get("environment") or {}).get("fresh_unique_level_required") is True
            and (value.get("environment") or {}).get("initial_inventory_exact") == {}
        ),
        "reset_only": (
            (value.get("reset_substrate") or {}).get("reset_only") is True
            and (value.get("reset_substrate") or {}).get("bm012_terminal_execution_allowed") is False
        ),
        "no_capability_credit": (value.get("capability_policy") or {}).get("counts_toward_capability") is False,
        "no_m4_credit": (value.get("capability_policy") or {}).get("counts_toward_m4") is False,
        "no_retry": value.get("automatic_retry_allowed") is False,
        "offline_harness_ready": (value.get("current_state") or {}).get("offline_harness_ready") is True,
        "no_live_authorization_in_policy": (value.get("current_state") or {}).get("live_authorization") is False,
    }

    implementation = (
        value.get("implementation_contract")
        if isinstance(value.get("implementation_contract"), dict)
        else {}
    )
    expected_implementation = {
        "runtime_module": "src/singularity/evaluation/stone_pickaxe_sp003_runtime.py",
        "episode_runner": "scripts/stone_pickaxe_sp003_episode_runner.py",
        "launcher": "scripts/stone-pickaxe-sp003-runtime.ps1",
        "dedicated_tests": "tests/test_stone_pickaxe_sp003_runtime.py",
        "planner_module": "src/singularity/core/planner.py",
        "task_reconciliation_module": "src/singularity/evaluation/stone_pickaxe_sp003_runtime.py",
    }
    for label, path in expected_implementation.items():
        checks[f"implementation_{label}"] = (
            implementation.get(label) == path
            and (REPOSITORY_ROOT / path).is_file()
        )

    reset = value.get("reset_substrate") if isinstance(value.get("reset_substrate"), dict) else {}
    for name in ("base_protocol", "task_contract"):
        path = reset.get(f"{name}_path", "")
        expected = str(reset.get(f"{name}_sha256") or "")
        checks[f"{name}_identity"] = bool(path and expected) and file_sha256(
            REPOSITORY_ROOT / path
        ) == expected

    records = _skill_records()
    skills = value.get("skills") if isinstance(value.get("skills"), list) else []
    checks["exact_two_skills"] = len(skills) == 2
    for spec in skills:
        skill_id = str(spec.get("skill_id") or "")
        version = str(spec.get("version") or "")
        label = skill_id.replace(":", "_") or "missing"
        record = records.get((skill_id, version), {})
        checks[f"{label}_record"] = bool(record) and (
            record.get("status") == "executable"
            and canonical_sha256(record) == spec.get("record_canonical_sha256")
        )
        for artifact_name in ("promotion_artifact", "runtime_default_gate"):
            artifact = spec.get(artifact_name) if isinstance(spec.get(artifact_name), dict) else {}
            path = str(artifact.get("path") or "")
            checks[f"{label}_{artifact_name}"] = bool(path) and file_sha256(
                REPOSITORY_ROOT / path
            ) == artifact.get("sha256")
        gate = read_json(REPOSITORY_ROOT / spec["runtime_default_gate"]["path"])
        candidates = gate.get("candidates") if isinstance(gate.get("candidates"), list) else []
        checks[f"{label}_runtime_gate_approved"] = bool(
            gate.get("readiness") == "approved"
            and gate.get("normal_runtime_permission") is True
            and gate.get("promoted_skill_version") == version
            and any(
                isinstance(item, dict)
                and item.get("skill_id") == skill_id
                and item.get("promotion_gate_fingerprint")
                == spec.get("promotion_gate_fingerprint")
                for item in candidates
            )
        )

    expected_graph = value.get("task_graph") if isinstance(value.get("task_graph"), list) else []
    checks["five_node_graph"] = [node.get("id") for node in expected_graph if isinstance(node, dict)] == [
        "acquire_wood",
        "place_crafting_table",
        "craft_wooden_pickaxe",
        "acquire_cobblestone",
        "craft_stone_pickaxe",
    ]
    return {
        "type": "stone_pickaxe_sp003_policy_identity",
        "schema_version": 1,
        "passed": all(checks.values()),
        "policy_id": SP003_RUNTIME_POLICY_ID,
        "policy_sha256": file_sha256(SP003_POLICY_PATH),
        "protocol_sha256": PROTOCOL_SHA256,
        "checks": checks,
        "issues": sorted(name for name, passed in checks.items() if not passed),
    }


def _normalize_arm(arm: str, replicate_id: str) -> tuple[str, str, int]:
    normalized_arm = str(arm or "").strip().lower()
    normalized_replicate = str(replicate_id or "").strip().lower()
    if normalized_arm == "baseline" and normalized_replicate == "baseline":
        return normalized_arm, normalized_replicate, 0
    if normalized_arm == "candidate" and normalized_replicate in {"r1", "r2", "r3"}:
        return normalized_arm, normalized_replicate, int(normalized_replicate[1:])
    raise ValueError("arm/replicate_id must be baseline/baseline or candidate/r1..r3")


def build_sp003_authorization(
    *,
    arm: str,
    replicate_id: str,
    episode_id: str,
    authorization_predecessor: str,
    prerequisite_manifest_path: str = "",
    prerequisite_manifest_sha256: str = "",
) -> dict:
    normalized_arm, normalized_replicate, sequence_position = _normalize_arm(
        arm, replicate_id
    )
    normalized_episode = str(episode_id or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,95}", normalized_episode):
        raise ValueError("episode_id must be a bounded lowercase ASCII identifier")
    predecessor = str(authorization_predecessor or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{40}", predecessor):
        raise ValueError("authorization_predecessor must be a full commit SHA")
    prerequisite_path = str(prerequisite_manifest_path or "").replace("\\", "/")
    prerequisite_hash = str(prerequisite_manifest_sha256 or "").strip().lower()
    if sequence_position == 0 and (prerequisite_path or prerequisite_hash):
        raise ValueError("baseline authorization cannot bind prerequisite evidence")
    if sequence_position > 0 and (
        not prerequisite_path or not re.fullmatch(r"[0-9a-f]{64}", prerequisite_hash)
    ):
        raise ValueError("candidate authorization requires the prior pushed manifest identity")
    identity = {
        "arm": normalized_arm,
        "replicate_id": normalized_replicate,
        "sequence_position": sequence_position,
        "episode_id": normalized_episode,
        "authorization_predecessor": predecessor,
        "harness_policy_path": SP003_POLICY_PATH.relative_to(REPOSITORY_ROOT).as_posix(),
        "harness_policy_sha256": file_sha256(SP003_POLICY_PATH),
        "protocol_sha256": PROTOCOL_SHA256,
        "prerequisite_manifest_path": prerequisite_path,
        "prerequisite_manifest_sha256": prerequisite_hash,
    }
    return {
        "type": SP003_AUTHORIZATION_TYPE,
        "schema_version": 1,
        "created_at_utc": utc_now(),
        "authorization_id": canonical_sha256(identity),
        "status": "active",
        "task_id": "SP-003",
        "protocol_id": PROTOCOL["id"],
        **identity,
        "skill_execution_mode": "off" if normalized_arm == "baseline" else "runtime",
        "created_before_live_process_start": True,
        "single_episode": True,
        "automatic_retry_allowed": False,
        "batch_execution_allowed": False,
        "support_rerun_allowed": False,
        "sp003_allowed": True,
        "bm012_terminal_allowed": False,
        "counts_toward_capability": False,
        "counts_toward_m4": False,
    }


def verify_sp003_authorization(
    authorization: Any,
    *,
    expected_arm: str,
    expected_replicate_id: str,
    expected_episode_id: str,
    current_head: str,
    parent_head: str,
) -> dict:
    value = authorization if isinstance(authorization, dict) else {}
    try:
        arm, replicate, sequence_position = _normalize_arm(
            expected_arm, expected_replicate_id
        )
    except ValueError:
        arm, replicate, sequence_position = "", "", -1
    prerequisite_path = str(value.get("prerequisite_manifest_path") or "")
    prerequisite_hash = str(value.get("prerequisite_manifest_sha256") or "")
    prerequisite = {}
    prerequisite_exists = False
    prerequisite_identity = sequence_position == 0 and not prerequisite_path and not prerequisite_hash
    prerequisite_eligible = sequence_position == 0
    if sequence_position > 0 and prerequisite_path:
        path = (REPOSITORY_ROOT / prerequisite_path).resolve()
        try:
            path.relative_to(REPOSITORY_ROOT)
            prerequisite_exists = path.is_file()
        except ValueError:
            prerequisite_exists = False
        if prerequisite_exists:
            prerequisite_identity = file_sha256(path) == prerequisite_hash
            prerequisite = read_json(path)
            prerequisite_eligible = bool(
                prerequisite.get("type") == "stone_pickaxe_sp003_live_manifest"
                and prerequisite.get("passed") is True
                and prerequisite.get("evidence_eligible") is True
                and prerequisite.get("sequence_position") == sequence_position - 1
            )
    identity = {
        "arm": arm,
        "replicate_id": replicate,
        "sequence_position": sequence_position,
        "episode_id": str(expected_episode_id or "").strip().lower(),
        "authorization_predecessor": str(value.get("authorization_predecessor") or "").lower(),
        "harness_policy_path": SP003_POLICY_PATH.relative_to(REPOSITORY_ROOT).as_posix(),
        "harness_policy_sha256": file_sha256(SP003_POLICY_PATH),
        "protocol_sha256": PROTOCOL_SHA256,
        "prerequisite_manifest_path": prerequisite_path,
        "prerequisite_manifest_sha256": prerequisite_hash,
    }
    checks = {
        "authorization_type": value.get("type") == SP003_AUTHORIZATION_TYPE,
        "authorization_schema": value.get("schema_version") == 1,
        "authorization_status": value.get("status") == "active",
        "task_id": value.get("task_id") == "SP-003",
        "protocol_id": value.get("protocol_id") == PROTOCOL["id"],
        "protocol_sha256": value.get("protocol_sha256") == PROTOCOL_SHA256,
        "arm": value.get("arm") == arm,
        "replicate_id": value.get("replicate_id") == replicate,
        "sequence_position": value.get("sequence_position") == sequence_position,
        "episode_id": value.get("episode_id") == identity["episode_id"],
        "skill_mode": value.get("skill_execution_mode") == (
            "off" if arm == "baseline" else "runtime"
        ),
        "created_before_live": value.get("created_before_live_process_start") is True,
        "single_episode": value.get("single_episode") is True,
        "no_retry": value.get("automatic_retry_allowed") is False,
        "no_batch": value.get("batch_execution_allowed") is False,
        "no_support_rerun": value.get("support_rerun_allowed") is False,
        "sp003_only": value.get("sp003_allowed") is True,
        "bm012_terminal_disabled": value.get("bm012_terminal_allowed") is False,
        "no_capability_credit": value.get("counts_toward_capability") is False,
        "no_m4_credit": value.get("counts_toward_m4") is False,
        "authorization_commit_is_new": str(current_head).lower() != str(parent_head).lower(),
        "authorization_predecessor": (
            str(parent_head).lower() == identity["authorization_predecessor"]
        ),
        "policy_path": value.get("harness_policy_path") == identity["harness_policy_path"],
        "policy_sha256": value.get("harness_policy_sha256") == identity["harness_policy_sha256"],
        "prerequisite_exists": prerequisite_exists if sequence_position > 0 else True,
        "prerequisite_identity": prerequisite_identity,
        "prerequisite_eligible": prerequisite_eligible,
        "authorization_fingerprint": value.get("authorization_id") == canonical_sha256(identity),
    }
    return {
        "type": "stone_pickaxe_sp003_authorization_preflight",
        "schema_version": 1,
        "passed": all(checks.values()),
        "checks": checks,
        "issues": sorted(name for name, passed in checks.items() if not passed),
        "authorization_id": str(value.get("authorization_id") or ""),
        "arm": arm,
        "replicate_id": replicate,
        "sequence_position": sequence_position,
        "episode_id": identity["episode_id"],
        "prerequisite_manifest": prerequisite_path,
        "consumed_by_process_start": False,
    }


def audit_sp003_reset(
    protocol_status: Any,
    reset: Any,
    *,
    episode_id: str,
    level_name: str,
) -> dict:
    status = protocol_status if isinstance(protocol_status, dict) else {}
    value = reset if isinstance(reset, dict) else {}
    policy = _policy()
    substrate = policy["reset_substrate"]
    environment = policy["environment"]
    expected = value.get("expected") if isinstance(value.get("expected"), dict) else {}
    after = value.get("after_state") if isinstance(value.get("after_state"), dict) else {}
    fixture = after.get("fixture") if isinstance(after.get("fixture"), dict) else {}
    fixture_blocks = after.get("fixture_blocks") if isinstance(after.get("fixture_blocks"), list) else None
    reset_checks = value.get("checks") if isinstance(value.get("checks"), dict) else {}
    lifecycle = value.get("player_lifecycle") if isinstance(value.get("player_lifecycle"), dict) else {}
    expected_time = _finite(expected.get("time_of_day"))
    observed_time = _finite(after.get("time_of_day"))
    daylight_delta = (
        (float(observed_time) - float(expected_time)) % 24000
        if expected_time is not None and observed_time is not None
        else None
    )
    checks = {
        "protocol_status_success": status.get("success") is True,
        "protocol_configured": status.get("configured") is True,
        "protocol_profile": status.get("profile") == substrate["profile"],
        "protocol_errors": status.get("errors") == [],
        "episode_id": status.get("episode_id") == episode_id == value.get("episode_id"),
        "level_name": status.get("level_name") == level_name == value.get("level_name"),
        "world_seed": str(status.get("seed") or "") == environment["world_seed"],
        "minecraft_version": (
            status.get("minecraft_version") == environment["minecraft_version"]
            and status.get("observed_minecraft_version") == environment["minecraft_version"]
        ),
        "server_jar": status.get("server_jar_sha256") == environment["server_jar_sha256"],
        "reset_success": value.get("success") is True,
        "reset_task": value.get("task_id") == substrate["reset_task_id"],
        "reset_contract": value.get("task_contract_sha256") == substrate["task_contract_sha256"],
        "expected_empty_inventory": expected.get("initial_inventory") == {},
        "observed_empty_inventory": after.get("inventory") == {},
        "no_fixture_blocks": (
            fixture_blocks == []
            and str(fixture.get("block") or "") == "air"
        ),
        "survival": after.get("game_mode") == environment["game_mode"],
        "difficulty": after.get("difficulty") == environment["difficulty"],
        "daylight_start": (
            expected_time == 0
            and daylight_delta is not None
            and daylight_delta <= 600
            and reset_checks.get("daytime") is True
            and reset_checks.get("time_initialized") is True
        ),
        "lifecycle_baseline": (
            reset_checks.get("player_lifecycle_baseline") is True
            and lifecycle.get("uninterrupted") is True
            and lifecycle.get("death_count") == 0
            and lifecycle.get("respawn_count") == 0
        ),
    }
    return {
        "type": "stone_pickaxe_sp003_reset_audit",
        "schema_version": 1,
        "passed": all(checks.values()),
        "policy_id": SP003_RUNTIME_POLICY_ID,
        "checks": checks,
        "issues": sorted(name for name, passed in checks.items() if not passed),
        "reset_task_id": substrate["reset_task_id"],
        "reset_only": True,
        "bm012_terminal_started": False,
        "granted_items": [],
        "counts_toward_bm012": False,
        "counts_toward_m4": False,
    }


def _observed_candidates(
    observation: Any,
    names: set[str],
    *,
    reachable_only: bool = False,
    excluded: set[str] | None = None,
) -> list[dict]:
    raw = observation if isinstance(observation, dict) else {}
    excluded = set(excluded or set())
    interaction_range = float(
        PROTOCOL["fixture_policy"]["cobblestone_sources"]["interaction_range"]
    )
    search_radius = float(
        PROTOCOL["fixture_policy"]["cobblestone_sources"]["search_radius"]
    )
    player = raw.get("position") if isinstance(raw.get("position"), dict) else {}
    candidates = []
    blocks = raw.get("nearby_blocks") if isinstance(raw.get("nearby_blocks"), list) else []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        name = str(block.get("name") or "")
        if name not in names:
            continue
        position = block.get("position") if isinstance(block.get("position"), dict) else {}
        identifier = source_id(name, position)
        distance = _finite(block.get("distance"))
        if distance is None and all(_finite(player.get(axis)) is not None for axis in ("x", "y", "z")):
            coordinates = [_finite(position.get(axis)) for axis in ("x", "y", "z")]
            if all(value is not None for value in coordinates):
                distance = math.sqrt(sum(
                    (float(player[axis]) - float(position[axis])) ** 2
                    for axis in ("x", "y", "z")
                ))
        if not identifier or identifier in excluded or distance is None or distance > search_radius:
            continue
        if reachable_only and distance > interaction_range:
            continue
        candidates.append({
            "source_id": identifier,
            "name": name,
            "position": _compact_position(position),
            "distance": round(float(distance), 6),
        })
    candidates.sort(key=lambda item: (item["distance"], item["source_id"]))
    return candidates


def audit_sp003_initial_state(observation: Any) -> dict:
    raw = observation if isinstance(observation, dict) else {}
    inventory = _safe_inventory(raw)
    logs = _observed_candidates(raw, set(LOG_ITEMS))
    tables = _observed_candidates(raw, {"crafting_table"})
    health = _finite(raw.get("health"))
    position = raw.get("position") if isinstance(raw.get("position"), dict) else {}
    checks = {
        "inventory_exact_empty": inventory == {},
        "survival_mode": raw.get("game_mode") == "survival",
        "health_positive": health is not None and health > 0,
        "finite_position": all(_finite(position.get(axis)) is not None for axis in ("x", "y", "z")),
        "safe_ground": str(raw.get("ground_block") or "") not in {"", "air", "water", "lava"},
        "observed_log_source": bool(logs),
        "no_crafting_table": not tables,
        "no_stone_pickaxe": inventory.get("stone_pickaxe", 0) == 0,
        "no_wooden_pickaxe": inventory.get("wooden_pickaxe", 0) == 0,
        "no_cobblestone": inventory.get("cobblestone", 0) == 0,
    }
    return {
        "type": "stone_pickaxe_sp003_initial_state_audit",
        "schema_version": 1,
        "passed": all(checks.values()),
        "checks": checks,
        "issues": sorted(name for name, passed in checks.items() if not passed),
        "inventory": inventory,
        "observed_log_source_count": len(logs),
        "nearest_log_source": logs[0] if logs else {},
        "counts_toward_capability": False,
        "counts_toward_m4": False,
    }


def _empty_progress() -> dict:
    return {
        "log_source_ids": set(),
        "log_item": "",
        "plank_craft_count": 0,
        "stick_craft_count": 0,
        "crafting_table_craft_count": 0,
        "crafting_table_place_count": 0,
        "crafting_table_position": {},
        "wooden_pickaxe_craft_count": 0,
        "wooden_pickaxe_equip_count": 0,
        "stone_source_ids": set(),
        "stone_pickaxe_craft_count": 0,
        "iron_mining_action_count": 0,
        "successful_mutations": [],
    }


def _progress_snapshot(progress: Any) -> dict:
    value = progress if isinstance(progress, dict) else {}
    return {
        "log_source_ids": sorted(str(item) for item in value.get("log_source_ids", set())),
        "log_source_removal_count": len(set(value.get("log_source_ids", set()))),
        "log_item": str(value.get("log_item") or ""),
        "plank_craft_count": _count(value.get("plank_craft_count")),
        "stick_craft_count": _count(value.get("stick_craft_count")),
        "crafting_table_craft_count": _count(value.get("crafting_table_craft_count")),
        "crafting_table_place_count": _count(value.get("crafting_table_place_count")),
        "crafting_table_position": _compact_position(
            value.get("crafting_table_position")
        ),
        "wooden_pickaxe_craft_count": _count(value.get("wooden_pickaxe_craft_count")),
        "wooden_pickaxe_equip_count": _count(value.get("wooden_pickaxe_equip_count")),
        "stone_source_ids": sorted(str(item) for item in value.get("stone_source_ids", set())),
        "stone_source_removal_count": len(set(value.get("stone_source_ids", set()))),
        "stone_pickaxe_craft_count": _count(value.get("stone_pickaxe_craft_count")),
        "iron_mining_action_count": _count(value.get("iron_mining_action_count")),
        "successful_mutation_count": len(value.get("successful_mutations", [])),
        "successful_mutations": copy.deepcopy(list(value.get("successful_mutations", []))),
    }


def _stage(observation: Any, progress: Any) -> str:
    inventory = _safe_inventory(observation)
    state = _progress_snapshot(progress)
    if inventory.get("stone_pickaxe", 0) >= 1 or state["stone_pickaxe_craft_count"] >= 1:
        return "complete"
    if state["stone_source_removal_count"] >= 3 or inventory.get("cobblestone", 0) >= 3:
        return "craft_stone_pickaxe"
    if state["wooden_pickaxe_craft_count"] >= 1 or inventory.get("wooden_pickaxe", 0) >= 1:
        return "acquire_cobblestone"
    if state["log_source_removal_count"] >= 3:
        return "prepare_wooden_pickaxe"
    return "acquire_wood"


def _coordinates_match(params: dict, candidate: dict, tolerance: float = 0.01) -> bool:
    position = candidate.get("position") if isinstance(candidate.get("position"), dict) else {}
    try:
        return all(
            abs(float(params[axis]) - float(position[axis])) <= tolerance
            for axis in ("x", "y", "z")
        )
    except (KeyError, TypeError, ValueError):
        return False


def _navigation_coordinates_match(
    params: dict,
    candidate: dict,
    tolerance: float = 1.0,
) -> bool:
    position = candidate.get("position") if isinstance(candidate.get("position"), dict) else {}
    try:
        if any(
            abs(float(params[axis]) - float(position[axis])) > tolerance
            for axis in ("x", "z")
        ):
            return False
        return (
            "y" not in params
            or abs(float(params["y"]) - float(position["y"])) <= tolerance
        )
    except (KeyError, TypeError, ValueError):
        return False


def _place_reference_candidates(observation: Any) -> list[dict]:
    raw = observation if isinstance(observation, dict) else {}
    player = raw.get("position") if isinstance(raw.get("position"), dict) else {}
    blocks = raw.get("nearby_blocks") if isinstance(raw.get("nearby_blocks"), list) else []
    occupied = set()
    for block in blocks:
        if not isinstance(block, dict):
            continue
        position = block.get("position") if isinstance(block.get("position"), dict) else {}
        if all(_finite(position.get(axis)) is not None for axis in ("x", "y", "z")):
            occupied.add(tuple(round(float(position[axis])) for axis in ("x", "y", "z")))
    candidates = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        name = str(block.get("name") or "")
        position = block.get("position") if isinstance(block.get("position"), dict) else {}
        if name in REPLACEABLE_BLOCKS or name == "crafting_table":
            continue
        if not all(_finite(position.get(axis)) is not None for axis in ("x", "y", "z")):
            continue
        compact = {axis: round(float(position[axis])) for axis in ("x", "y", "z")}
        distance = _finite(block.get("distance"))
        if distance is None and all(_finite(player.get(axis)) is not None for axis in ("x", "y", "z")):
            distance = math.sqrt(sum(
                (float(player[axis]) - compact[axis]) ** 2 for axis in ("x", "y", "z")
            ))
        if distance is None or distance > 4.5:
            continue
        target = (compact["x"], compact["y"] + 1, compact["z"])
        if target in occupied:
            continue
        if all(_finite(player.get(axis)) is not None for axis in ("x", "y", "z")):
            player_cell = (
                math.floor(float(player["x"])),
                math.floor(float(player["y"])),
                math.floor(float(player["z"])),
            )
            if target in {player_cell, (player_cell[0], player_cell[1] + 1, player_cell[2])}:
                continue
        candidates.append({
            "source_id": source_id(name, compact),
            "name": name,
            "position": compact,
            "distance": round(float(distance), 6),
            "target_position": {"x": target[0], "y": target[1], "z": target[2]},
        })
    candidates.sort(key=lambda item: (item["distance"], item["source_id"]))
    return candidates


def _remembered_table_candidate(observation: Any, progress: Any) -> dict:
    state = _progress_snapshot(progress)
    position = state.get("crafting_table_position", {})
    if len(position) != 3:
        return {}
    raw = observation if isinstance(observation, dict) else {}
    player = raw.get("position") if isinstance(raw.get("position"), dict) else {}
    distance = None
    if all(_finite(player.get(axis)) is not None for axis in ("x", "y", "z")):
        distance = math.sqrt(sum(
            (float(player[axis]) - float(position[axis])) ** 2
            for axis in ("x", "y", "z")
        ))
    if distance is None or distance > 32.0:
        return {}
    return {
        "source_id": source_id("crafting_table", position),
        "name": "crafting_table",
        "position": position,
        "distance": round(distance, 6),
        "machine_proven_placement": True,
    }


def _sp003_observation_targets(observation: Any, progress: Any) -> list[dict]:
    state = _progress_snapshot(progress)
    stage = _stage(observation, progress)
    inventory = _safe_inventory(observation)
    if stage == "acquire_wood":
        log_names = {state["log_item"]} if state.get("log_item") else set(LOG_ITEMS)
        return _observed_candidates(
            observation,
            log_names,
            excluded=set(state["log_source_ids"]),
        )[:8]
    if stage == "acquire_cobblestone" and inventory.get("cobblestone", 0) < 3:
        return _observed_candidates(
            observation,
            {"stone"},
            excluded=set(state["stone_source_ids"]),
        )[:8]
    if stage == "prepare_wooden_pickaxe" and state["crafting_table_craft_count"] == 1:
        return _place_reference_candidates(observation)[:8]
    tables = _observed_candidates(observation, {"crafting_table"})
    if tables:
        return tables[:8]
    remembered = _remembered_table_candidate(observation, progress)
    return [remembered] if remembered else []


def guard_sp003_action(action: Any, observation: Any, progress: Any, *, arm: str = "baseline") -> dict:
    value = action if isinstance(action, dict) else {}
    params = value.get("parameters") if isinstance(value.get("parameters"), dict) else {}
    action_type = str(value.get("type") or "")
    normalized = {"type": action_type, "parameters": dict(params)}
    issues: list[str] = []
    selected_source = {}
    state = _progress_snapshot(progress)
    stage = _stage(observation, progress)
    inventory = _safe_inventory(observation)
    skill_context = value.get("skill_context") if isinstance(value.get("skill_context"), dict) else {}
    normalized_arm = str(arm or "").strip().lower()

    if normalized_arm == "baseline" and skill_context:
        issues.append("baseline_skill_context_forbidden")
    if action_type == "dig" and str(params.get("block") or "") in IRON_BLOCKS:
        issues.append("iron_mining_forbidden")

    if action_type in {"move_to", "look_at", "wait"}:
        issues.extend(_non_mutating_action_issues(action_type, params, observation, 32.0))
        if action_type != "wait" and not issues:
            if stage == "acquire_wood":
                log_names = {state["log_item"]} if state.get("log_item") else set(LOG_ITEMS)
                candidates = _observed_candidates(
                    observation,
                    log_names,
                    excluded=set(state["log_source_ids"]),
                )
            elif stage == "acquire_cobblestone" and inventory.get("cobblestone", 0) < 3:
                candidates = _observed_candidates(
                    observation,
                    {"stone"},
                    excluded=set(state["stone_source_ids"]),
                )
            else:
                candidates = _observed_candidates(observation, {"crafting_table"})
                if not candidates:
                    remembered = _remembered_table_candidate(observation, progress)
                    candidates = [remembered] if remembered else []
            matching = [
                item
                for item in candidates
                if _navigation_coordinates_match(params, item, tolerance=1.0)
            ]
            if not matching:
                issues.append(f"{stage}_navigation_target_must_be_observed")
            elif candidates and matching[0]["source_id"] != candidates[0]["source_id"]:
                issues.append(f"{stage}_navigation_target_must_be_nearest_observed")
            else:
                selected_source = matching[0]
    elif action_type == "dig" and stage == "acquire_wood":
        block = str(params.get("block") or "")
        if block not in LOG_ITEMS:
            issues.append("sp003_wood_dig_requires_log_family")
        if state.get("log_item") and block != state["log_item"]:
            issues.append("sp003_mixed_log_family_forbidden")
        log_names = {state["log_item"]} if state.get("log_item") else set(LOG_ITEMS)
        candidates = _observed_candidates(
            observation,
            log_names,
            reachable_only=True,
            excluded=set(state["log_source_ids"]),
        )
        target_id = source_id(block, params)
        matching = [item for item in candidates if item["source_id"] == target_id]
        if not matching:
            issues.append("sp003_log_target_must_be_reachable_and_observed")
        elif candidates[0]["source_id"] != target_id:
            issues.append("sp003_log_target_must_be_nearest_observed")
        else:
            selected_source = matching[0]
            normalized["parameters"]["source_id"] = target_id
        if state["log_source_removal_count"] >= 3:
            issues.append("sp003_log_removal_limit_reached")
    elif action_type == "craft" and stage == "prepare_wooden_pickaxe":
        item = str(params.get("item") or "")
        count = params.get("count")
        log_counts = {name: inventory.get(name, 0) for name in LOG_ITEMS if inventory.get(name, 0)}
        log_item = str(state.get("log_item") or "")
        expected_planks = PLANK_BY_LOG.get(log_item, "")
        if state["plank_craft_count"] == 0:
            if set(params) != {"item", "count"} or item != expected_planks or count != 12:
                issues.append("sp003_exact_matching_plank_craft_required")
            if log_counts != ({log_item: 3} if log_item else {}):
                issues.append("sp003_exact_three_matching_logs_required")
        elif state["stick_craft_count"] == 0:
            if set(params) != {"item", "count"} or item != "stick" or count != 4:
                issues.append("sp003_exact_four_sticks_craft_required")
            if inventory.get(expected_planks, 0) < 2:
                issues.append("sp003_stick_materials_missing")
        elif state["crafting_table_craft_count"] == 0:
            if set(params) != {"item", "count"} or item != "crafting_table" or count != 1:
                issues.append("sp003_exact_one_table_craft_required")
            if inventory.get(expected_planks, 0) < 4:
                issues.append("sp003_table_materials_missing")
        elif state["crafting_table_place_count"] == 0 or not _nearby_crafting_table_observed(observation):
            issues.append("sp003_table_must_be_placed_before_more_crafting")
        elif state["wooden_pickaxe_craft_count"] == 0:
            if set(params) != {"item", "count"} or item != "wooden_pickaxe" or count != 1:
                issues.append("sp003_exact_one_wooden_pickaxe_craft_required")
            if inventory.get(expected_planks, 0) < 3 or inventory.get("stick", 0) < 2:
                issues.append("sp003_wooden_pickaxe_materials_missing")
        else:
            issues.append("sp003_duplicate_preparation_craft_forbidden")
    elif action_type == "place" and stage == "prepare_wooden_pickaxe":
        if set(params) != {"item", "x", "y", "z"} or params.get("item") != "crafting_table":
            issues.append("sp003_exact_table_placement_required")
        if state["crafting_table_craft_count"] != 1 or inventory.get("crafting_table", 0) != 1:
            issues.append("sp003_table_item_precondition_required")
        if state["crafting_table_place_count"] != 0 or _nearby_crafting_table_observed(observation):
            issues.append("sp003_duplicate_table_placement_forbidden")
        candidates = _place_reference_candidates(observation)
        matching = [item for item in candidates if _coordinates_match(params, item)]
        if not matching:
            issues.append("sp003_table_reference_must_be_observed_solid_with_clear_target")
        else:
            selected_source = matching[0]
            normalized["parameters"]["reference_source_id"] = matching[0]["source_id"]
    elif action_type == "equip" and stage == "acquire_cobblestone":
        if set(params) - {"item", "destination"} or params.get("item") != "wooden_pickaxe":
            issues.append("sp003_only_wooden_pickaxe_equip_allowed")
        if inventory.get("wooden_pickaxe", 0) != 1:
            issues.append("sp003_exact_wooden_pickaxe_inventory_required")
        if _main_hand_item(observation) == "wooden_pickaxe":
            issues.append("sp003_redundant_wooden_pickaxe_equip")
    elif action_type == "dig" and stage == "acquire_cobblestone":
        if params.get("block") != "stone":
            issues.append("sp003_stone_dig_requires_exact_stone")
        if _main_hand_item(observation) != "wooden_pickaxe":
            issues.append("sp003_stone_dig_requires_held_wooden_pickaxe")
        candidates = _observed_candidates(
            observation,
            {"stone"},
            reachable_only=True,
            excluded=set(state["stone_source_ids"]),
        )
        target_id = source_id("stone", params)
        matching = [item for item in candidates if item["source_id"] == target_id]
        if not matching:
            issues.append("sp003_stone_target_must_be_reachable_and_observed")
        elif candidates[0]["source_id"] != target_id:
            issues.append("sp003_stone_target_must_be_nearest_observed")
        else:
            selected_source = matching[0]
            normalized["parameters"]["source_id"] = target_id
        if state["stone_source_removal_count"] >= 3 or inventory.get("cobblestone", 0) >= 3:
            issues.append("sp003_stone_removal_limit_reached")
        if skill_context and (
            skill_context.get("skill_id") != "learned:acquire_cobblestone"
            or skill_context.get("version") != EXPECTED_SKILLS["learned:acquire_cobblestone"]
        ):
            issues.append("sp003_stone_skill_context_mismatch")
    elif action_type == "craft" and stage == "craft_stone_pickaxe":
        if set(params) != {"item", "count"} or params.get("item") != "stone_pickaxe" or params.get("count") != 1:
            issues.append("sp003_exact_one_stone_pickaxe_craft_required")
        if inventory.get("cobblestone", 0) != 3 or inventory.get("stick", 0) != 2:
            issues.append("sp003_exact_stone_pickaxe_materials_required")
        if inventory.get("stone_pickaxe", 0) != 0:
            issues.append("sp003_stone_pickaxe_must_be_absent")
        if not _nearby_crafting_table_observed(observation):
            issues.append("sp003_interactive_crafting_table_required")
        if state["stone_pickaxe_craft_count"] != 0:
            issues.append("sp003_duplicate_stone_pickaxe_craft_forbidden")
        if skill_context and (
            skill_context.get("skill_id") != "learned:craft_stone_pickaxe"
            or skill_context.get("version") != EXPECTED_SKILLS["learned:craft_stone_pickaxe"]
        ):
            issues.append("sp003_craft_skill_context_mismatch")
    else:
        issues.append(f"sp003_action_forbidden_for_stage:{stage}:{action_type or 'missing'}")

    return {
        "type": "stone_pickaxe_sp003_action_guard",
        "schema_version": 1,
        "policy_id": SP003_ACTION_GUARD_POLICY_ID,
        "mode": "sp003",
        "arm": normalized_arm,
        "stage": stage,
        "allowed": not issues,
        "issues": sorted(set(issues)),
        "action": normalized,
        "selected_source": selected_source,
        "progress": state,
        "runtime_influence": True,
    }


def _verified_action_success(result: Any, *, allow_review: bool = False) -> bool:
    value = result if isinstance(result, dict) else {}
    verification = value.get("action_verification") if isinstance(value.get("action_verification"), dict) else {}
    accepted_statuses = {"accept", "review"} if allow_review else {"accept"}
    return value.get("success") is True and verification.get("status") in accepted_statuses


def _single_craft_machine_success(result: Any, item: str, count: int) -> bool:
    value = result if isinstance(result, dict) else {}
    inventory_delta = (
        value.get("inventory_delta")
        if isinstance(value.get("inventory_delta"), dict)
        else {}
    )
    signed_delta = (
        value.get("inventory_signed_delta")
        if isinstance(value.get("inventory_signed_delta"), dict)
        else {}
    )
    return bool(
        item
        and count > 0
        and value.get("item") == item
        and _count(value.get("count")) == count
        and _count(value.get("requested_output_count")) == count
        and value.get("craft_attempts") == 1
        and value.get("craft_retry_count") == 0
        and _count(inventory_delta.get(item)) == count
        and _count(signed_delta.get(item)) == count
    )


def record_sp003_success(progress: dict, action: Any, result: Any) -> dict:
    value = action if isinstance(action, dict) else {}
    params = value.get("parameters") if isinstance(value.get("parameters"), dict) else {}
    backend = result if isinstance(result, dict) else {}
    action_type = str(value.get("type") or "")
    item = str(params.get("item") or "")
    block = str(params.get("block") or backend.get("block") or "")
    if not _verified_action_success(result, allow_review=action_type == "craft"):
        return _progress_snapshot(progress)
    mutation = {"type": action_type, "item": item, "block": block}
    if action_type == "dig" and block in IRON_BLOCKS:
        progress["iron_mining_action_count"] += 1
    elif action_type == "dig" and block in LOG_ITEMS:
        pickup = backend.get("pickup_inventory_delta") if isinstance(backend.get("pickup_inventory_delta"), dict) else {}
        identifier = str(params.get("source_id") or source_id(block, params))
        if (
            backend.get("block_removed") is True
            and backend.get("pickup_observed") is True
            and _count(pickup.get(block)) >= 1
            and identifier
        ):
            progress["log_source_ids"].add(identifier)
            progress["log_item"] = progress.get("log_item") or block
            mutation["source_id"] = identifier
    elif action_type == "dig" and block == "stone":
        pickup = backend.get("pickup_inventory_delta") if isinstance(backend.get("pickup_inventory_delta"), dict) else {}
        tool = backend.get("dig_tool_equip") if isinstance(backend.get("dig_tool_equip"), dict) else {}
        identifier = str(params.get("source_id") or source_id(block, params))
        if (
            backend.get("block_removed") is True
            and backend.get("pickup_observed") is True
            and _count(pickup.get("cobblestone")) >= 1
            and str(tool.get("equipped_tool") or tool.get("selected_tool") or "") == "wooden_pickaxe"
            and tool.get("passed") is True
            and identifier
        ):
            progress["stone_source_ids"].add(identifier)
            mutation["source_id"] = identifier
    elif action_type == "craft":
        output_count = _count(params.get("count"))
        if not _single_craft_machine_success(backend, item, output_count):
            return _progress_snapshot(progress)
        if item in set(PLANK_BY_LOG.values()) and params.get("count") == 12:
            progress["plank_craft_count"] += 1
        elif item == "stick" and params.get("count") == 4:
            progress["stick_craft_count"] += 1
        elif item == "crafting_table" and params.get("count") == 1:
            progress["crafting_table_craft_count"] += 1
        elif item == "wooden_pickaxe" and params.get("count") == 1:
            progress["wooden_pickaxe_craft_count"] += 1
        elif item == "stone_pickaxe" and params.get("count") == 1:
            progress["stone_pickaxe_craft_count"] += 1
        else:
            return _progress_snapshot(progress)
    elif action_type == "place" and item == "crafting_table":
        placed_position = _compact_position(backend.get("placed_position"))
        target_after = (
            backend.get("target_block_after")
            if isinstance(backend.get("target_block_after"), dict)
            else {}
        )
        if (
            len(placed_position) == 3
            and backend.get("requested_item_equipped") is True
            and target_after.get("name") == "crafting_table"
        ):
            progress["crafting_table_place_count"] += 1
            progress["crafting_table_position"] = placed_position
    elif action_type == "equip" and item == "wooden_pickaxe":
        progress["wooden_pickaxe_equip_count"] += 1
    progress["successful_mutations"].append(mutation)
    return _progress_snapshot(progress)


def _sp003_flags(progress: Any) -> list[str]:
    state = _progress_snapshot(progress)
    flags = []
    if state["log_source_removal_count"] == 3:
        flags.append("sp003_wood_acquired")
    if state["crafting_table_place_count"] == 1:
        flags.append("sp003_crafting_table_placed")
    if state["wooden_pickaxe_craft_count"] == 1:
        flags.append("sp003_wooden_pickaxe_crafted")
    if state["stone_source_removal_count"] == 3:
        flags.append("sp003_cobblestone_acquired")
    if state["stone_pickaxe_craft_count"] == 1:
        flags.append("sp003_stone_pickaxe_crafted")
    return flags


class StonePickaxeSP003RuntimeAgent(StonePickaxeSP002RuntimeAgent):
    """Strict five-stage SP-003 agent with optional two-skill runtime routing."""

    def __init__(self, config: Config, *, arm: str):
        normalized_arm, _, _ = _normalize_arm(
            arm,
            "baseline" if str(arm).lower() == "baseline" else "r1",
        )
        self.sp003_arm = normalized_arm
        self.sp003_progress = _empty_progress()
        self.sp003_local_attributions: list[dict] = []
        super().__init__(config, "sp003")
        self.skill_library.persist = False
        self.skill_learning_ledger = None

    def _observe(self) -> dict:
        observation = dict(super()._observe())
        existing_flags = observation.get("flags") if isinstance(observation.get("flags"), list) else []
        observation["flags"] = sorted(set(str(flag) for flag in existing_flags) | set(_sp003_flags(self.sp003_progress)))
        observation["sp003_progress"] = _progress_snapshot(self.sp003_progress)
        observation["sp003_arm"] = self.sp003_arm
        observation["sp003_targets"] = _sp003_observation_targets(
            observation,
            self.sp003_progress,
        )
        return observation

    def _reconcile_stone_pickaxe_satisfied_tasks(
        self,
        observation: dict,
        goal: str,
        cycle: int,
        *,
        source: str = "machine_observation",
    ) -> list:
        task_system = getattr(self, "task_system", None)
        if not task_system or not hasattr(task_system, "complete_state_satisfied_tasks"):
            return []
        dependency_ready_ids = {
            task.id
            for task in task_system.tasks.values()
            if task.status in (TaskStatus.ACCEPTED, TaskStatus.ACTIVE)
            and task_system._dependencies_satisfied(task)
        }
        if not dependency_ready_ids:
            return []
        completed = task_system.complete_state_satisfied_tasks(
            observation,
            allowed_criteria={"flags", "inventory", "nearby_block_present"},
            candidate_task_ids=dependency_ready_ids,
        )
        if completed:
            self._flush_task_state_transitions({
                "source": "stone_pickaxe_task_state_reconciliation",
                "reconciliation_source": str(source or "machine_observation"),
                "goal": str(goal or ""),
                "cycle": int(cycle or 0),
            })
        if completed and hasattr(getattr(self, "session_logger", None), "log"):
            self.session_logger.log("stone_pickaxe_task_state_reconciliation", {
                "schema_version": 1,
                "source": str(source or "machine_observation"),
                "goal": str(goal or ""),
                "cycle": int(cycle or 0),
                "completed_task_ids": [task.id for task in completed],
                "completion_source": "machine_state",
            })
        return completed

    def _verify_action_for_execution(
        self,
        action: dict,
        observation: dict,
        goal: str,
        context: dict = None,
    ):
        guard = guard_sp003_action(
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
                "policy_id": SP003_ACTION_GUARD_POLICY_ID,
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
        normalized = guard.get("action") if isinstance(guard.get("action"), dict) else {}
        skill_context = action.get("skill_context") if isinstance(action.get("skill_context"), dict) else None
        action.clear()
        action.update(normalized)
        if skill_context:
            action["skill_context"] = dict(skill_context)
        return Agent._verify_action_for_execution(self, action, observation, goal, context)

    def _apply_action_feedback(
        self,
        action: dict,
        result: dict,
        fallback_observation: dict,
        context: dict = None,
    ) -> dict:
        before = _progress_snapshot(self.sp003_progress)
        after = record_sp003_success(self.sp003_progress, action, result)
        if after != before:
            self.session_logger.log("stone_pickaxe_sp003_progress", {
                "schema_version": 1,
                "policy_id": SP003_RUNTIME_POLICY_ID,
                "goal": str((context or {}).get("goal") or ""),
                "cycle": int((context or {}).get("cycle", 0) or 0),
                "before": before,
                "after": after,
                "action": copy.deepcopy(action),
            })
        return super()._apply_action_feedback(action, result, fallback_observation, context)

    def _finalize_active_skill_outcome(
        self,
        goal: str,
        goal_success: bool,
        terminal_observation: dict,
        goal_result: dict,
    ):
        active = dict(getattr(self, "_active_skill_execution", {}) or {})
        skill = self.skill_library.get_skill_by_id(str(active.get("skill_id") or ""))
        postconditions_met = False
        if skill is not None:
            postconditions_met, _ = self.skill_library.skill_postconditions_met(
                skill,
                terminal_observation or {},
                effective_postconditions=active.get("effective_postconditions", {}),
            )
        Agent._finalize_active_skill_outcome(
            self,
            goal,
            goal_success,
            terminal_observation,
            goal_result,
        )
        skill_id = str(active.get("skill_id") or "")
        version = str(active.get("version") or "")
        accepted = bool(
            self.sp003_arm == "candidate"
            and EXPECTED_SKILLS.get(skill_id) == version
            and postconditions_met
            and int(active.get("executed_count", 0) or 0) > 0
            and int(active.get("failed_action_count", 0) or 0) == 0
        )
        if accepted and not any(item.get("skill_id") == skill_id for item in self.sp003_local_attributions):
            record = {
                "task_id": "SP-001" if skill_id == "learned:acquire_cobblestone" else "SP-002",
                "skill_id": skill_id,
                "version": version,
                "route_goal": str(active.get("route_goal") or ""),
                "executed_action_count": int(active.get("executed_count", 0) or 0),
                "postconditions_met": True,
                "attribution_confidence": 1.0,
                "root_goal_attributed": False,
                "runtime_persisted": False,
            }
            self.sp003_local_attributions.append(record)
            self.session_logger.log("stone_pickaxe_sp003_skill_attribution", record)

    def _learned_skill_plan(self, goal: str, observation: dict) -> dict | None:
        if (
            getattr(self, "sp003_arm", "") == "candidate"
            and _stage(observation, getattr(self, "sp003_progress", {})) == "acquire_cobblestone"
            and _main_hand_item(observation) != "wooden_pickaxe"
            and not getattr(self, "_active_skill_execution", {})
        ):
            return None
        plan = Agent._learned_skill_plan(self, goal, observation)
        active = dict(getattr(self, "_active_skill_execution", {}) or {})
        if (
            plan is None
            and getattr(self, "_m2_skill_contribution_complete", False)
            and active.get("skill_id") in EXPECTED_SKILLS
        ):
            self._finalize_active_skill_outcome(
                str(active.get("route_goal") or goal),
                True,
                observation,
                {"termination_reason": "sp003_component_machine_complete"},
            )
            self._active_skill_execution = {}
            self._m2_skill_contribution_complete = False
            return Agent._learned_skill_plan(self, goal, observation)
        return plan

    def _goal_is_verified(
        self,
        goal: str,
        observation: dict,
        context: dict = None,
        recent_actions: list[dict] = None,
    ):
        if self._episode_deadline_reached():
            return False, self._deadline_goal_verification(goal, context, "sp003_goal_verifier")
        inventory = _safe_inventory(observation)
        progress = _progress_snapshot(self.sp003_progress)
        tasks = {
            str(task.plan_node_id): task
            for task in self.task_system.tasks.values()
            if str(getattr(task, "plan_node_id", ""))
        }
        expected_nodes = [node["id"] for node in _policy()["task_graph"]]
        checks = {
            "terminal_stone_pickaxe": inventory.get("stone_pickaxe", 0) == 1,
            "log_removals_exact": progress["log_source_removal_count"] == 3,
            "plank_craft_exact": progress["plank_craft_count"] == 1,
            "stick_craft_exact": progress["stick_craft_count"] == 1,
            "table_craft_exact": progress["crafting_table_craft_count"] == 1,
            "table_place_exact": progress["crafting_table_place_count"] == 1,
            "wooden_pickaxe_craft_exact": progress["wooden_pickaxe_craft_count"] == 1,
            "stone_removals_exact": progress["stone_source_removal_count"] == 3,
            "stone_pickaxe_craft_exact": progress["stone_pickaxe_craft_count"] == 1,
            "no_iron_mining": progress["iron_mining_action_count"] == 0,
            "exact_task_graph": set(tasks) == set(expected_nodes),
            "task_graph_complete": bool(tasks) and all(
                tasks.get(node_id) is not None
                and tasks[node_id].status == TaskStatus.COMPLETED
                for node_id in expected_nodes
            ),
        }
        achieved = all(checks.values())
        verification = GoalVerification(
            goal=goal,
            achieved=achieved,
            status="achieved" if achieved else "failed",
            confidence=1.0,
            evidence=(
                [
                    "empty-hand five-stage task graph is machine complete",
                    "exactly three logs and three stone sources were removed",
                    "terminal inventory contains exactly one stone_pickaxe",
                ]
                if achieved
                else []
            ),
            missing=sorted(name for name, passed in checks.items() if not passed),
            matched_rules=["stone_pickaxe:sp003_empty_hand_machine_terminal"],
            target_inventory={"stone_pickaxe": 1},
            critic={
                "policy_id": SP003_MACHINE_VERIFIER_ID,
                "checks": checks,
                "progress": progress,
                "task_node_statuses": {
                    node_id: tasks[node_id].status.value
                    for node_id in expected_nodes
                    if node_id in tasks
                },
            },
        )
        self._log_goal_verification(
            verification,
            {**(context or {}), "accepted": achieved},
        )
        return achieved, verification


def build_sp003_runtime_config(
    *,
    base_config: Config,
    arm: str,
) -> Config:
    normalized_arm, _, _ = _normalize_arm(
        arm,
        "baseline" if str(arm).lower() == "baseline" else "r1",
    )
    if normalized_arm == "baseline":
        return replace(
            base_config,
            skill_execution_mode="off",
            enable_skill_frontier_routing=False,
            skill_runtime_default_gate_paths=[],
        )
    policy = _policy()
    gate_paths = [
        str(REPOSITORY_ROOT / spec["runtime_default_gate"]["path"])
        for spec in policy["skills"]
    ]
    return replace(
        base_config,
        skill_execution_mode="runtime",
        enable_skill_frontier_routing=True,
        skill_runtime_default_gate_paths=gate_paths,
        target_skill_id="",
        enable_skill_candidate_extraction=False,
    )


def sp003_runtime_controls(config: Config, *, arm: str) -> dict:
    controls = runtime_controls(config)
    controls.update({
        "runtime_policy_id": SP003_RUNTIME_POLICY_ID,
        "arm": str(arm or "").strip().lower(),
        "skill_frontier_routing": bool(config.enable_skill_frontier_routing),
        "skill_runtime_default_gate_paths": [
            Path(path).resolve().relative_to(REPOSITORY_ROOT).as_posix()
            for path in (config.skill_runtime_default_gate_paths or [])
        ],
        "skill_library_persistence": False,
        "skill_learning_ledger_write": False,
    })
    return controls


def _event_times(event: dict, result: dict, goal_result: dict, initial_monotonic: float) -> tuple[float, float]:
    finished = _finite(result.get("action_finished_monotonic"))
    started = _finite(result.get("action_started_monotonic"))
    if finished is None:
        elapsed = _finite(event.get("elapsed_s")) or 0.0
        finished = float(goal_result.get("episode_started_monotonic") or initial_monotonic) + elapsed
    if started is None:
        started = finished - max(0, _count(result.get("duration_ms"))) / 1000.0
    return float(started), float(finished)


def _selected_skills(events: list[dict]) -> list[dict]:
    selected = []
    for event in events:
        if not isinstance(event, dict) or event.get("type") != "skill_selected":
            continue
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        skill = data.get("skill") if isinstance(data.get("skill"), dict) else {}
        selected.append({
            "skill_id": str(skill.get("skill_id") or data.get("skill_id") or ""),
            "version": str(skill.get("version") or data.get("version") or ""),
            "status": str(skill.get("status") or data.get("status") or ""),
            "route_goal": str(data.get("goal") or ""),
        })
    return selected


def _local_attributions(events: list[dict]) -> list[dict]:
    return [
        dict(event.get("data") or {})
        for event in events
        if isinstance(event, dict)
        and event.get("type") == "stone_pickaxe_sp003_skill_attribution"
        and isinstance(event.get("data"), dict)
    ]


def _component_eligibility(
    *,
    planner_audit: dict,
    reset_audit: dict,
    forbidden: list,
    post_deadline: list,
) -> dict:
    passed = bool(
        planner_audit.get("passed") is True
        and reset_audit.get("passed") is True
        and not forbidden
        and not post_deadline
    )
    return {
        "passed": passed,
        "protocol_match": True,
        "planner_request_controls": planner_audit.get("passed") is True,
        "reset_clean": reset_audit.get("passed") is True,
        "no_forbidden_intervention": not forbidden,
        "no_post_deadline_action": not post_deadline,
    }


def _build_sp001_component(
    *,
    action_events: list[dict],
    episode_id: str,
    session_id: str,
    session_sha256: str,
    level_name: str,
    goal_result: dict,
    planner_audit: dict,
    reset_audit: dict,
    forbidden: list,
    post_deadline: list,
    initial_monotonic: float,
    selected_skills: list[dict],
) -> dict:
    transitions = []
    component_indexes = []
    false_success = []
    for index, event in enumerate(action_events, start=1):
        data = event["data"]
        action = data.get("action") if isinstance(data.get("action"), dict) else {}
        params = action.get("parameters") if isinstance(action.get("parameters"), dict) else {}
        result = data.get("result") if isinstance(data.get("result"), dict) else {}
        block = str(result.get("block") or params.get("block") or "")
        if action.get("type") != "dig" or block != "stone":
            continue
        started, finished = _event_times(event, result, goal_result, initial_monotonic)
        component_indexes.append(index)
        target = result.get("target") if isinstance(result.get("target"), dict) else params
        identifier = str(params.get("source_id") or source_id("stone", target))
        before_source = {
            "id": identifier,
            "name": "stone",
            "present": (
                (result.get("target_block_before") or {}).get("name") == "stone"
                if isinstance(result.get("target_block_before"), dict)
                else False
            ),
            "position": _compact_position(target),
        }
        after_block = result.get("target_block_after") if isinstance(result.get("target_block_after"), dict) else {}
        after_source = {
            "id": identifier,
            "name": "stone",
            "present": after_block.get("name") == "stone",
            "position": _compact_position(target),
        }
        pre = evidence_observation(
            data.get("pre_observation"),
            role="sp003_sp001_pre_dig",
            ordinal=index,
            monotonic_s=started,
            source_state=before_source,
        )
        post = evidence_observation(
            data.get("post_observation"),
            role="sp003_sp001_post_dig",
            ordinal=index,
            monotonic_s=finished,
            source_state=after_source,
        )
        pickup = result.get("pickup_inventory_delta") if isinstance(result.get("pickup_inventory_delta"), dict) else {}
        tool = result.get("dig_tool_equip") if isinstance(result.get("dig_tool_equip"), dict) else {}
        verification = result.get("action_verification") if isinstance(result.get("action_verification"), dict) else {}
        transitions.append({
            "source_id": identifier,
            "source_block": "stone",
            "tool": str(tool.get("equipped_tool") or tool.get("selected_tool") or ""),
            "action_verified": bool(
                result.get("success") is True
                and verification.get("status") == "accept"
                and tool.get("passed") is True
            ),
            "action": {
                "type": "dig",
                "parameters": {"block": "stone", "source_id": identifier, **_compact_position(target)},
            },
            "pre_observation": pre,
            "post_observation": post,
            "pickup": {
                "observed": result.get("pickup_observed") is True,
                "source_id": identifier,
                "item": "cobblestone",
                "count": _count(pickup.get("cobblestone")),
                "inventory_delta": dict(pickup),
            },
            "action_started_monotonic": started,
            "action_finished_monotonic": finished,
            "backend_result": {
                "success": result.get("success") is True,
                "block_removed": result.get("block_removed") is True,
                "expected_drops": list(result.get("expected_drops", [])),
                "dig_postcondition": dict(result.get("dig_postcondition") or {}),
                "dig_tool_equip": dict(tool),
            },
        })
        if result.get("success") is True and not (
            result.get("block_removed") is True
            and result.get("pickup_observed") is True
            and _count(pickup.get("cobblestone")) >= 1
        ):
            false_success.append(index)
    first = component_indexes[0] if component_indexes else 0
    last = component_indexes[-1] if component_indexes else 0
    window = action_events[first - 1:last] if first and last else []
    initial_raw = window[0]["data"].get("pre_observation", {}) if window else {}
    terminal_raw = transitions[-1]["post_observation"] if transitions else {}
    initial = evidence_observation(
        initial_raw,
        role="sp003_sp001_initial",
        ordinal=0,
        monotonic_s=transitions[0]["action_started_monotonic"] if transitions else initial_monotonic,
    )
    eligibility = _component_eligibility(
        planner_audit=planner_audit,
        reset_audit=reset_audit,
        forbidden=forbidden,
        post_deadline=post_deadline,
    )
    return {
        "type": "stone_pickaxe_microbenchmark_episode",
        "schema_version": 1,
        "protocol_id": PROTOCOL["id"],
        "protocol_sha256": PROTOCOL_SHA256,
        "task_id": "SP-001",
        "session_id": session_id,
        "episode_id": episode_id,
        "session_sha256": session_sha256,
        "level_name": level_name,
        "evidence_kind": PROTOCOL["evidence_policy"]["live_evidence_kind"],
        "episode_started_monotonic": goal_result.get("episode_started_monotonic"),
        "episode_deadline_monotonic": goal_result.get("episode_deadline_monotonic"),
        "episode_ended_monotonic": transitions[-1]["action_finished_monotonic"] if transitions else initial_monotonic,
        "deadline_policy_id": goal_result.get("deadline_policy_id", ""),
        "action_count": len(window),
        "action_failure_count": sum(
            1 for event in window if (event.get("data") or {}).get("result", {}).get("success") is not True
        ),
        "false_success_dig_count": len(false_success),
        "world_mutating_non_target_actions": [],
        "initial_observation": initial,
        "transitions": transitions,
        "terminal_observation": terminal_raw,
        "goal_result": dict(goal_result),
        "eligibility": eligibility,
        "reset_contamination": False,
        "post_deadline_action_count": len(post_deadline),
        "forbidden_interventions": forbidden,
        "selected_skills": selected_skills,
        "counts_toward_capability": False,
        "counts_toward_m4": False,
    }


def _build_sp002_component(
    *,
    action_events: list[dict],
    stable_observation: dict,
    stable_monotonic: float,
    episode_id: str,
    session_id: str,
    session_sha256: str,
    level_name: str,
    goal_result: dict,
    planner_audit: dict,
    reset_audit: dict,
    forbidden: list,
    post_deadline: list,
    initial_monotonic: float,
    selected_skills: list[dict],
) -> dict:
    transitions = []
    for index, event in enumerate(action_events, start=1):
        data = event["data"]
        action = data.get("action") if isinstance(data.get("action"), dict) else {}
        params = action.get("parameters") if isinstance(action.get("parameters"), dict) else {}
        result = data.get("result") if isinstance(data.get("result"), dict) else {}
        if action.get("type") != "craft" or params.get("item") != "stone_pickaxe":
            continue
        started, finished = _event_times(event, result, goal_result, initial_monotonic)
        pre = evidence_observation(
            data.get("pre_observation"),
            role="sp003_sp002_pre_craft",
            ordinal=index,
            monotonic_s=started,
            include_crafting_table=True,
        )
        post = evidence_observation(
            data.get("post_observation"),
            role="sp003_sp002_post_craft",
            ordinal=index,
            monotonic_s=finished,
            include_crafting_table=True,
        )
        stable = evidence_observation(
            stable_observation,
            role="sp003_sp002_stable",
            ordinal=len(action_events) + 1,
            monotonic_s=stable_monotonic,
            include_crafting_table=True,
        )
        table_position = result.get("crafting_table_position") if isinstance(result.get("crafting_table_position"), dict) else {}
        table_id = source_id("crafting_table", table_position)
        table = next(
            (
                block for block in pre.get("nearby_blocks", [])
                if isinstance(block, dict) and block.get("block_id") == table_id
            ),
            {},
        )
        verification = result.get("action_verification") if isinstance(result.get("action_verification"), dict) else {}
        transitions.append({
            "action": {"type": "craft", "parameters": {"item": "stone_pickaxe", "count": params.get("count")}},
            "action_verified": bool(result.get("success") is True and verification.get("status") == "accept"),
            "pre_observation": pre,
            "post_observation": post,
            "stable_observation": stable,
            "crafting_table_interaction": {
                "block_id": table_id,
                "position": _compact_position(table_position),
                "distance": table.get("distance"),
                "observed": bool(table),
                "interactive": bool(result.get("crafting_table_found") is True and table.get("interactive") is True),
                "observation_id": pre.get("observation_id", ""),
            },
            "action_started_monotonic": started,
            "action_finished_monotonic": finished,
            "backend_result": {
                "success": result.get("success") is True,
                "item": str(result.get("item") or ""),
                "requested_output_count": result.get("requested_output_count"),
                "inventory_before": dict(result.get("inventory_before") or {}),
                "inventory_after": dict(result.get("inventory_after") or {}),
                "inventory_signed_delta": dict(result.get("inventory_signed_delta") or {}),
                "authoritative_inventory_refresh": dict(result.get("authoritative_inventory_refresh") or {}),
                "craft_attempts": result.get("craft_attempts"),
                "craft_retry_count": result.get("craft_retry_count"),
                "single_attempt": result.get("craft_attempts") == 1 and result.get("craft_retry_count") == 0,
                "stable_ms": result.get("stable_ms"),
            },
        })
    eligibility = _component_eligibility(
        planner_audit=planner_audit,
        reset_audit=reset_audit,
        forbidden=forbidden,
        post_deadline=post_deadline,
    )
    eligibility["backend_single_craft_attempt"] = bool(
        len(transitions) == 1
        and transitions[0]["backend_result"]["single_attempt"] is True
    )
    eligibility["passed"] = eligibility["passed"] and eligibility["backend_single_craft_attempt"]
    initial = transitions[0]["pre_observation"] if transitions else {}
    terminal = transitions[0]["stable_observation"] if transitions else {}
    return {
        "type": "stone_pickaxe_microbenchmark_episode",
        "schema_version": 1,
        "protocol_id": PROTOCOL["id"],
        "protocol_sha256": PROTOCOL_SHA256,
        "task_id": "SP-002",
        "session_id": session_id,
        "episode_id": episode_id,
        "session_sha256": session_sha256,
        "level_name": level_name,
        "evidence_kind": PROTOCOL["evidence_policy"]["live_evidence_kind"],
        "episode_started_monotonic": goal_result.get("episode_started_monotonic"),
        "episode_deadline_monotonic": goal_result.get("episode_deadline_monotonic"),
        "episode_ended_monotonic": stable_monotonic,
        "deadline_policy_id": goal_result.get("deadline_policy_id", ""),
        "action_count": len(transitions),
        "action_failure_count": sum(1 for transition in transitions if transition["backend_result"]["success"] is not True),
        "world_mutating_non_target_actions": [],
        "initial_observation": initial,
        "transitions": transitions,
        "terminal_observation": terminal,
        "goal_result": dict(goal_result),
        "eligibility": eligibility,
        "reset_contamination": False,
        "post_deadline_action_count": len(post_deadline),
        "forbidden_interventions": forbidden,
        "selected_skills": selected_skills,
        "counts_toward_capability": False,
        "counts_toward_m4": False,
    }


def build_sp003_episode(
    *,
    arm: str,
    replicate_id: str,
    episode_id: str,
    session_id: str,
    session_sha256: str,
    level_name: str,
    events: list[dict],
    initial_observation: dict,
    stable_observation: dict,
    initial_monotonic: float,
    stable_monotonic: float,
    goal_result: dict,
    reset_audit: dict,
    authorization_path: str,
    authorization_sha256: str,
    authorization_preflight: dict,
    task_graph: dict,
    skill_store_sha256_before: str,
    skill_store_sha256_after: str,
) -> dict:
    normalized_arm, normalized_replicate, sequence_position = _normalize_arm(arm, replicate_id)
    action_events = [
        event for event in events
        if isinstance(event, dict)
        and event.get("type") == "action"
        and isinstance(event.get("data"), dict)
    ]
    deadline = _finite(goal_result.get("episode_deadline_monotonic"))
    action_failures = []
    post_deadline = []
    forbidden = []
    counts: dict[str, int] = {}
    log_sources = set()
    stone_sources = set()
    log_transition_proofs = []
    craft_backend_proofs = []
    table_placement_proofs = []
    iron_actions = []
    unexpected_actions = []
    skill_action_map = []
    for index, event in enumerate(action_events, start=1):
        data = event["data"]
        action = data.get("action") if isinstance(data.get("action"), dict) else {}
        params = action.get("parameters") if isinstance(action.get("parameters"), dict) else {}
        result = data.get("result") if isinstance(data.get("result"), dict) else {}
        action_type = str(action.get("type") or "")
        label = action_type
        subject = str(params.get("block") or params.get("item") or "")
        if subject:
            label = f"{action_type}:{subject}"
        counts[label] = counts.get(label, 0) + 1
        if result.get("success") is not True:
            action_failures.append({"index": index, "action": action, "error": str(result.get("error") or "action_not_successful")})
        started, finished = _event_times(event, result, goal_result, initial_monotonic)
        if result.get("accepted_within_episode_deadline") is False or (
            deadline is not None and finished > deadline
        ):
            post_deadline.append(index)
        if action_type == "chat":
            command = str(params.get("message") or "").strip().lower().lstrip("/").split(" ", 1)[0]
            if command in FORBIDDEN_COMMAND_TOKENS:
                forbidden.append({"index": index, "command": command})
        if action_type == "dig" and subject in IRON_BLOCKS:
            iron_actions.append(index)
        if action_type == "dig" and subject in LOG_ITEMS and result.get("success") is True:
            identifier = str(params.get("source_id") or source_id(subject, params))
            log_sources.add(identifier)
            pickup = result.get("pickup_inventory_delta") if isinstance(result.get("pickup_inventory_delta"), dict) else {}
            verification = result.get("action_verification") if isinstance(result.get("action_verification"), dict) else {}
            log_transition_proofs.append({
                "index": index,
                "source_id": identifier,
                "source_block": subject,
                "action_verified": verification.get("status") == "accept",
                "block_removed": result.get("block_removed") is True,
                "pickup_observed": result.get("pickup_observed") is True,
                "pickup_count": _count(pickup.get(subject)),
            })
        if action_type == "dig" and subject == "stone" and result.get("success") is True:
            stone_sources.add(str(params.get("source_id") or source_id(subject, params)))
        if action_type == "craft":
            verification = result.get("action_verification") if isinstance(result.get("action_verification"), dict) else {}
            craft_backend_proofs.append({
                "index": index,
                "item": subject,
                "requested_count": params.get("count"),
                "backend_requested_count": result.get("requested_output_count"),
                "action_verified": verification.get("status") == "accept",
                "success": result.get("success") is True,
                "craft_attempts": result.get("craft_attempts"),
                "craft_retry_count": result.get("craft_retry_count"),
                "crafting_table_found": result.get("crafting_table_found") is True,
                "crafting_table_position": _compact_position(
                    result.get("crafting_table_position")
                ),
            })
        if action_type == "place" and subject == "crafting_table":
            verification = result.get("action_verification") if isinstance(result.get("action_verification"), dict) else {}
            target_after = result.get("target_block_after") if isinstance(result.get("target_block_after"), dict) else {}
            table_placement_proofs.append({
                "index": index,
                "action_verified": verification.get("status") == "accept",
                "success": result.get("success") is True,
                "requested_item_equipped": result.get("requested_item_equipped") is True,
                "placed_position": _compact_position(result.get("placed_position")),
                "target_block_after": str(target_after.get("name") or ""),
            })
        allowed = bool(
            action_type in {"move_to", "look_at", "wait"}
            or (action_type == "equip" and subject == "wooden_pickaxe")
            or (action_type == "dig" and (subject in LOG_ITEMS or subject == "stone"))
            or (action_type == "craft" and subject in (
                set(PLANK_BY_LOG.values())
                | {"stick", "crafting_table", "wooden_pickaxe", "stone_pickaxe"}
            ))
            or (action_type == "place" and subject == "crafting_table")
        )
        if not allowed:
            unexpected_actions.append({"index": index, "action": label})
        skill_context = action.get("skill_context") if isinstance(action.get("skill_context"), dict) else {}
        if skill_context:
            skill_action_map.append({
                "index": index,
                "action": label,
                "skill_id": str(skill_context.get("skill_id") or ""),
                "version": str(skill_context.get("version") or ""),
                "success": result.get("success") is True,
            })

    planner_audit = planner_request_controls_audit(events)
    selected = _selected_skills(events)
    attributions = _local_attributions(events)
    components = {
        "sp001": _build_sp001_component(
            action_events=action_events,
            episode_id=episode_id,
            session_id=session_id,
            session_sha256=session_sha256,
            level_name=level_name,
            goal_result=goal_result,
            planner_audit=planner_audit,
            reset_audit=reset_audit,
            forbidden=forbidden,
            post_deadline=post_deadline,
            initial_monotonic=initial_monotonic,
            selected_skills=selected,
        ),
        "sp002": _build_sp002_component(
            action_events=action_events,
            stable_observation=stable_observation,
            stable_monotonic=stable_monotonic,
            episode_id=episode_id,
            session_id=session_id,
            session_sha256=session_sha256,
            level_name=level_name,
            goal_result=goal_result,
            planner_audit=planner_audit,
            reset_audit=reset_audit,
            forbidden=forbidden,
            post_deadline=post_deadline,
            initial_monotonic=initial_monotonic,
            selected_skills=selected,
        ),
    }
    initial_audit = audit_sp003_initial_state(initial_observation)
    return {
        "type": "stone_pickaxe_sp003_empty_hand_episode",
        "schema_version": 1,
        "runtime_policy_id": SP003_RUNTIME_POLICY_ID,
        "runtime_policy_sha256": file_sha256(SP003_POLICY_PATH),
        "protocol_id": PROTOCOL["id"],
        "protocol_sha256": PROTOCOL_SHA256,
        "task_id": "SP-003",
        "arm": normalized_arm,
        "replicate_id": normalized_replicate,
        "sequence_position": sequence_position,
        "episode_id": episode_id,
        "session_id": session_id,
        "session_sha256": session_sha256,
        "level_name": level_name,
        "evidence_kind": PROTOCOL["evidence_policy"]["live_evidence_kind"],
        "authorization_path": str(authorization_path).replace("\\", "/"),
        "authorization_sha256": authorization_sha256,
        "authorization_preflight": dict(authorization_preflight),
        "episode_started_monotonic": goal_result.get("episode_started_monotonic"),
        "episode_deadline_monotonic": goal_result.get("episode_deadline_monotonic"),
        "episode_ended_monotonic": stable_monotonic,
        "deadline_policy_id": goal_result.get("deadline_policy_id", ""),
        "action_count": len(action_events),
        "action_failures": action_failures,
        "post_deadline_action_indexes": post_deadline,
        "forbidden_interventions": forbidden,
        "iron_mining_action_indexes": iron_actions,
        "unexpected_actions": unexpected_actions,
        "action_type_counts": counts,
        "distinct_log_source_ids": sorted(item for item in log_sources if item),
        "distinct_stone_source_ids": sorted(item for item in stone_sources if item),
        "log_transition_proofs": log_transition_proofs,
        "craft_backend_proofs": craft_backend_proofs,
        "table_placement_proofs": table_placement_proofs,
        "initial_observation": copy.deepcopy(initial_observation),
        "stable_observation": copy.deepcopy(stable_observation),
        "initial_state_audit": initial_audit,
        "reset_audit": dict(reset_audit),
        "planner_request_controls": planner_audit,
        "selected_skills": selected,
        "skill_action_map": skill_action_map,
        "local_skill_attributions": attributions,
        "components": components,
        "task_graph": copy.deepcopy(task_graph),
        "goal_result": dict(goal_result),
        "stable_reobservation_delay_s": stable_monotonic - float(goal_result.get("episode_ended_monotonic") or initial_monotonic),
        "skill_store_sha256_before": skill_store_sha256_before,
        "skill_store_sha256_after": skill_store_sha256_after,
        "external_step_script": False,
        "automatic_retry_allowed": False,
        "bm012_terminal_started": False,
        "counts_toward_capability": False,
        "counts_toward_m4": False,
    }


def _exact_task_graph_report(graph: Any) -> dict:
    value = graph if isinstance(graph, dict) else {}
    records = value.get("tasks") if isinstance(value.get("tasks"), list) else []
    by_node = {
        str(record.get("plan_node_id") or ""): record
        for record in records
        if isinstance(record, dict) and str(record.get("plan_node_id") or "")
    }
    expected = _policy()["task_graph"]
    checks = {"exact_node_ids": set(by_node) == {node["id"] for node in expected}}
    for node in expected:
        record = by_node.get(node["id"], {})
        dependency_nodes = sorted(
            str(by_node_id)
            for by_node_id, candidate in by_node.items()
            if candidate.get("id") in set(record.get("depends_on", []))
        )
        checks[f"{node['id']}_title"] = record.get("title") == node["title"]
        checks[f"{node['id']}_criteria"] = record.get("success_criteria") == node["success_criteria"]
        checks[f"{node['id']}_preconditions"] = record.get("preconditions") == node["preconditions"]
        checks[f"{node['id']}_dependencies"] = dependency_nodes == sorted(node["depends_on"])
        checks[f"{node['id']}_completed"] = record.get("status") == TaskStatus.COMPLETED.value
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "issues": sorted(name for name, passed in checks.items() if not passed),
    }


def verify_sp003_runtime_episode(evidence: Any) -> dict:
    value = evidence if isinstance(evidence, dict) else {}
    policy = _policy()
    contract = policy["episode_contract"]
    components = value.get("components") if isinstance(value.get("components"), dict) else {}
    sp001 = verify_sp001_episode(components.get("sp001"))
    sp002 = verify_sp002_episode(components.get("sp002"))
    graph = _exact_task_graph_report(value.get("task_graph"))
    initial = value.get("initial_state_audit") if isinstance(value.get("initial_state_audit"), dict) else {}
    reset = value.get("reset_audit") if isinstance(value.get("reset_audit"), dict) else {}
    planner = value.get("planner_request_controls") if isinstance(value.get("planner_request_controls"), dict) else {}
    goal_result = value.get("goal_result") if isinstance(value.get("goal_result"), dict) else {}
    terminal_inventory = _safe_inventory(value.get("stable_observation"))
    counts = value.get("action_type_counts") if isinstance(value.get("action_type_counts"), dict) else {}
    selected = value.get("selected_skills") if isinstance(value.get("selected_skills"), list) else []
    attributions = value.get("local_skill_attributions") if isinstance(value.get("local_skill_attributions"), list) else []
    skill_actions = value.get("skill_action_map") if isinstance(value.get("skill_action_map"), list) else []
    log_proofs = value.get("log_transition_proofs") if isinstance(value.get("log_transition_proofs"), list) else []
    craft_proofs = value.get("craft_backend_proofs") if isinstance(value.get("craft_backend_proofs"), list) else []
    table_proofs = value.get("table_placement_proofs") if isinstance(value.get("table_placement_proofs"), list) else []
    arm = str(value.get("arm") or "")
    expected_selected = {
        ("learned:acquire_cobblestone", "1.1.0"),
        ("learned:craft_stone_pickaxe", "1.0.1"),
    }
    observed_selected = {(item.get("skill_id"), item.get("version")) for item in selected if isinstance(item, dict)}
    observed_attributions = {(item.get("skill_id"), item.get("version")) for item in attributions if isinstance(item, dict)}
    expected_skill_actions = {
        ("learned:acquire_cobblestone", "dig:stone"),
        ("learned:craft_stone_pickaxe", "craft:stone_pickaxe"),
    }
    observed_skill_actions = {
        (item.get("skill_id"), item.get("action"))
        for item in skill_actions
        if isinstance(item, dict) and item.get("success") is True
    }
    placed_table_position = (
        table_proofs[0].get("placed_position", {})
        if len(table_proofs) == 1 and isinstance(table_proofs[0], dict)
        else {}
    )
    table_bound_crafts = [
        proof
        for proof in craft_proofs
        if isinstance(proof, dict)
        and proof.get("item") in {"wooden_pickaxe", "stone_pickaxe"}
    ]
    criteria = {
        "policy_identity": verify_sp003_policy_identity().get("passed") is True,
        "episode_type": value.get("type") == "stone_pickaxe_sp003_empty_hand_episode",
        "episode_schema": value.get("schema_version") == 1,
        "runtime_policy": (
            value.get("runtime_policy_id") == SP003_RUNTIME_POLICY_ID
            and value.get("runtime_policy_sha256") == file_sha256(SP003_POLICY_PATH)
        ),
        "protocol_identity": value.get("protocol_id") == PROTOCOL["id"] and value.get("protocol_sha256") == PROTOCOL_SHA256,
        "task_id": value.get("task_id") == "SP-003",
        "initial_empty_state": initial.get("passed") is True,
        "reset_clean": reset.get("passed") is True,
        "authorization": (value.get("authorization_preflight") or {}).get("passed") is True,
        "planner_request_controls": planner.get("passed") is True,
        "goal_machine_completed": goal_result.get("completed") is True,
        "action_bound": _count(value.get("action_count")) <= int(contract["maximum_actions"]),
        "cycle_bound": _count(goal_result.get("cycles")) <= int(contract["maximum_cycles"]),
        "duration_bound": (_finite(goal_result.get("elapsed_s")) or float("inf")) < float(contract["episode_timeout_s"]),
        "zero_action_failures": value.get("action_failures") == [],
        "zero_post_deadline_actions": value.get("post_deadline_action_indexes") == [],
        "zero_forbidden_interventions": value.get("forbidden_interventions") == [],
        "zero_iron_mining": value.get("iron_mining_action_indexes") == [],
        "zero_unexpected_actions": value.get("unexpected_actions") == [],
        "exact_three_log_sources": len(value.get("distinct_log_source_ids", [])) == 3,
        "exact_three_stone_sources": len(value.get("distinct_stone_source_ids", [])) == 3,
        "exact_three_log_actions": sum(
            counts.get(f"dig:{item}", 0) for item in LOG_ITEMS
        ) == 3,
        "exact_three_stone_actions": counts.get("dig:stone", 0) == 3,
        "log_transition_machine_proof": len(log_proofs) == 3 and all(
            isinstance(proof, dict)
            and proof.get("source_block") in LOG_ITEMS
            and proof.get("action_verified") is True
            and proof.get("block_removed") is True
            and proof.get("pickup_observed") is True
            and _count(proof.get("pickup_count")) >= 1
            for proof in log_proofs
        ),
        "one_plank_craft": sum(counts.get(f"craft:{item}", 0) for item in PLANK_BY_LOG.values()) == 1,
        "one_stick_craft": counts.get("craft:stick", 0) == 1,
        "one_table_craft": counts.get("craft:crafting_table", 0) == 1,
        "one_table_place": counts.get("place:crafting_table", 0) == 1,
        "table_placement_machine_proof": len(table_proofs) == 1 and all(
            isinstance(proof, dict)
            and proof.get("action_verified") is True
            and proof.get("success") is True
            and proof.get("requested_item_equipped") is True
            and proof.get("target_block_after") == "crafting_table"
            and len(proof.get("placed_position", {})) == 3
            for proof in table_proofs
        ),
        "one_wooden_pickaxe_craft": counts.get("craft:wooden_pickaxe", 0) == 1,
        "one_stone_pickaxe_craft": counts.get("craft:stone_pickaxe", 0) == 1,
        "one_wooden_pickaxe_equip": counts.get("equip:wooden_pickaxe", 0) == 1,
        "all_crafts_single_verified_attempt": len(craft_proofs) == 5 and all(
            isinstance(proof, dict)
            and proof.get("action_verified") is True
            and proof.get("success") is True
            and proof.get("requested_count") == proof.get("backend_requested_count")
            and proof.get("craft_attempts") == 1
            and proof.get("craft_retry_count") == 0
            for proof in craft_proofs
        ),
        "same_machine_proven_table_for_tool_crafts": (
            len(placed_table_position) == 3
            and len(table_bound_crafts) == 2
            and all(
                proof.get("crafting_table_found") is True
                and proof.get("crafting_table_position") == placed_table_position
                for proof in table_bound_crafts
            )
        ),
        "sp001_machine_verifier": sp001.get("criteria_passed") is True and sp001.get("evidence_eligible") is True,
        "sp002_machine_verifier": sp002.get("criteria_passed") is True and sp002.get("evidence_eligible") is True,
        "exact_task_graph_complete": graph.get("passed") is True,
        "terminal_stone_pickaxe": terminal_inventory.get("stone_pickaxe", 0) == 1,
        "stable_reobservation": (
            _finite(value.get("stable_reobservation_delay_s")) is not None
            and float(value["stable_reobservation_delay_s"]) >= float(contract["stable_reobservation_delay_s"])
        ),
        "skill_store_immutable": (
            bool(value.get("skill_store_sha256_before"))
            and value.get("skill_store_sha256_before") == value.get("skill_store_sha256_after")
        ),
        "no_retry": value.get("automatic_retry_allowed") is False,
        "no_bm012_terminal": value.get("bm012_terminal_started") is False,
        "no_capability_credit": value.get("counts_toward_capability") is False,
        "no_m4_credit": value.get("counts_toward_m4") is False,
    }
    if arm == "baseline":
        criteria.update({
            "baseline_no_skill_selection": observed_selected == set(),
            "baseline_no_skill_actions": observed_skill_actions == set(),
            "baseline_no_skill_attribution": observed_attributions == set(),
        })
    elif arm == "candidate":
        criteria.update({
            "candidate_exact_skill_selection": observed_selected == expected_selected,
            "candidate_exact_skill_actions": expected_skill_actions.issubset(observed_skill_actions),
            "candidate_separate_local_attribution": observed_attributions == expected_selected,
        })
    else:
        criteria["evaluation_arm"] = False
    issues = sorted(name for name, passed in criteria.items() if not passed)
    passed = not issues
    return {
        "type": "stone_pickaxe_sp003_machine_verification",
        "schema_version": 1,
        "policy_id": SP003_MACHINE_VERIFIER_ID,
        "runtime_policy_id": SP003_RUNTIME_POLICY_ID,
        "protocol_id": PROTOCOL["id"],
        "protocol_sha256": PROTOCOL_SHA256,
        "task_id": "SP-003",
        "arm": arm,
        "replicate_id": str(value.get("replicate_id") or ""),
        "criteria_passed": passed,
        "evidence_eligible": passed,
        "passed": passed,
        "criteria": criteria,
        "criteria_issues": issues,
        "eligibility_issues": issues,
        "components": {"sp001": sp001, "sp002": sp002},
        "task_graph": graph,
        "metrics": {
            "action_count": value.get("action_count"),
            "cycles": goal_result.get("cycles"),
            "elapsed_s": goal_result.get("elapsed_s"),
            "log_source_removal_count": len(value.get("distinct_log_source_ids", [])),
            "stone_source_removal_count": len(value.get("distinct_stone_source_ids", [])),
            "selected_skill_count": len(selected),
            "local_attribution_count": len(attributions),
        },
        "counts_toward_sp003_lifecycle": passed,
        "counts_toward_capability": False,
        "counts_toward_m4": False,
    }


def build_sp003_run_audit(
    episode: dict,
    verification: dict,
) -> dict:
    issues = list(verification.get("criteria_issues", []))
    return {
        "type": "stone_pickaxe_sp003_run_audit",
        "schema_version": 1,
        "generated_at_utc": utc_now(),
        "runtime_policy_id": SP003_RUNTIME_POLICY_ID,
        "episode_id": str(episode.get("episode_id") or ""),
        "session_id": str(episode.get("session_id") or ""),
        "arm": str(episode.get("arm") or ""),
        "replicate_id": str(episode.get("replicate_id") or ""),
        "sequence_position": episode.get("sequence_position"),
        "passed": verification.get("passed") is True,
        "evidence_eligible": verification.get("evidence_eligible") is True,
        "earliest_blocker": issues[0] if issues else "",
        "issues": issues,
        "component_verifiers": {
            task: {
                "criteria_passed": report.get("criteria_passed") is True,
                "evidence_eligible": report.get("evidence_eligible") is True,
                "issues": list(report.get("criteria_issues", [])) + list(report.get("eligibility_issues", [])),
            }
            for task, report in (verification.get("components") or {}).items()
            if isinstance(report, dict)
        },
        "task_graph_complete": (verification.get("task_graph") or {}).get("passed") is True,
        "automatic_retry_allowed": False,
        "next_authorization_allowed": verification.get("passed") is True,
        "counts_toward_capability": False,
        "counts_toward_m4": False,
    }


__all__ = [
    "SP003_ACTION_GUARD_POLICY_ID",
    "SP003_AUTHORIZATION_PATH",
    "SP003_GOAL",
    "SP003_POLICY_PATH",
    "SP003_RUNTIME_POLICY_ID",
    "StonePickaxeSP003RuntimeAgent",
    "audit_sp003_initial_state",
    "audit_sp003_reset",
    "build_sp003_authorization",
    "build_sp003_episode",
    "build_sp003_run_audit",
    "build_sp003_runtime_config",
    "guard_sp003_action",
    "record_sp003_success",
    "sp003_runtime_controls",
    "task_graph_snapshot",
    "verify_sp003_authorization",
    "verify_sp003_policy_identity",
    "verify_sp003_runtime_episode",
]
