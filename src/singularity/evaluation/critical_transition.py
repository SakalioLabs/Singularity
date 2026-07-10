"""Dependency-aware failure localization for Minecraft agent trajectories.

This module adapts the Transition Unit and auditable-constraint ideas from
AgentTether and AgentRx to Singularity's structured session logs. It is an
offline deterministic diagnostic, not a reproduction of either learned
localizer. Reports cannot authorize retries, runtime intervention, planner
guidance, memory promotion, or skill mutation.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from collections import Counter, defaultdict
from typing import Any, Optional


REPORT_TYPE = "critical_transition_report"
SCHEMA_VERSION = 1
UNIT_PROFILE = "minecraft_transition_unit_v1"
GRAPH_PROFILE = "minecraft_execution_dependency_graph_v1"
LOCALIZER_PROFILE = "first_unrecovered_constraint_v1"
REPAIR_MEMORY_PROFILE = "typed_repair_memory_candidate_v1"
MAX_UNITS = 1024

KNOWN_ACTIONS = {
    "planner_response",
    "move_to",
    "walk_to",
    "look_at",
    "dig",
    "place",
    "craft",
    "attack",
    "equip",
    "use_item",
    "chat",
    "wait",
}
WORLD_CHANGING_ACTIONS = {"dig", "place", "craft", "attack", "use_item"}
NAVIGATION_ACTIONS = {"move_to", "walk_to"}
REQUIRED_ARGUMENTS = {
    "move_to": ("x", "z"),
    "walk_to": ("x", "z"),
    "look_at": ("x", "y", "z"),
    "dig": ("x", "y", "z"),
    "place": ("x", "y", "z"),
    "craft": ("item",),
    "attack": ("entity_id",),
    "equip": ("item",),
    "chat": ("message",),
}

SYSTEM_ERROR_TOKENS = (
    "connection",
    "socket",
    "bridge",
    "timed out",
    "timeout",
    "econn",
    "disconnected",
    "empty response",
)

REPAIR_DIRECTIVES = {
    "empty_plan_without_transition": "produce_executable_or_prerequisite_recovery_action",
    "planned_actions_not_executed": "execute_or_explicitly_replan_pending_actions",
    "navigation_success_without_reach": "verify_navigation_reached_before_dependent_action",
    "unreached_navigation_has_dependents": "verify_navigation_reached_before_dependent_action",
    "dependent_action_after_unreached_navigation": "reobserve_after_navigation_before_world_change",
    "invalid_action_schema": "satisfy_action_schema_before_execution",
    "unsupported_action": "select_supported_action_or_replan",
    "action_verifier_bypassed": "never_execute_action_rejected_by_verifier",
    "action_verifier_reject": "resolve_verifier_constraint_before_replanning",
    "world_effect_mismatch": "verify_tool_feedback_against_world_state",
    "world_effect_unverified": "obtain_state_evidence_before_claiming_world_change",
    "ungrounded_world_target": "ground_world_target_in_current_observation",
    "action_execution_failure": "diagnose_execution_failure_before_retry",
    "backend_system_failure": "restore_backend_health_before_retry",
    "repeated_failure_signature": "stop_repeating_identical_failed_transition",
    "repeated_no_progress": "change_strategy_after_verified_no_progress",
    "missing_post_action_feedback": "observe_state_after_action_before_continuing",
}

CONSTRAINT_PRIORITY = {
    "action_verifier_bypassed": 10,
    "invalid_action_schema": 9,
    "unsupported_action": 9,
    "empty_plan_without_transition": 8,
    "planned_actions_not_executed": 9,
    "navigation_success_without_reach": 8,
    "world_effect_mismatch": 8,
    "backend_system_failure": 8,
    "ungrounded_world_target": 7,
    "action_execution_failure": 7,
    "unreached_navigation_has_dependents": 6,
    "dependent_action_after_unreached_navigation": 5,
    "repeated_failure_signature": 4,
    "repeated_no_progress": 3,
}


def build_transition_units(
    events: list[dict],
    session_id: str = "",
    max_units: int = MAX_UNITS,
) -> list[dict]:
    """Normalize action traces into Observation-Plan-Action-Feedback units."""
    events = [event for event in events or [] if isinstance(event, dict)]
    session_id = session_id or _explicit_session_id(events) or "unknown-session"
    max_units = max(1, min(MAX_UNITS, _safe_int(max_units, MAX_UNITS)))
    next_observations = _next_observation_index(events)
    latest_observation = {}
    latest_observation_index = -1
    latest_plan = {}
    latest_plan_index = -1
    plan_cursor = 0
    current_goal = ""
    pending_verifications: list[tuple[int, dict]] = []
    plan_records: dict[int, dict] = {}
    units = []

    for event_index, event in enumerate(events):
        event_type = str(event.get("type") or "")
        data = event.get("data", {}) if isinstance(event.get("data", {}), dict) else {}
        if event_type in {"goal_start", "auto_goal_start", "autonomous_goal_start"}:
            current_goal = str(data.get("goal") or current_goal)
        elif event_type == "observation":
            latest_observation = data
            latest_observation_index = event_index
        elif event_type == "plan":
            latest_plan = data
            latest_plan_index = event_index
            plan_cursor = 0
            pending_verifications = []
            next_index = next_observations.get(event_index, -1)
            plan_records[event_index] = {
                "plan": data,
                "observation_before": latest_observation,
                "observation_before_index": latest_observation_index,
                "observation_after": (
                    events[next_index].get("data", {})
                    if 0 <= next_index < len(events) and isinstance(events[next_index].get("data", {}), dict)
                    else {}
                ),
                "observation_after_index": next_index,
                "goal": current_goal,
            }
        elif event_type == "action_verification":
            pending_verifications.append((event_index, data))
        if event_type != "action":
            if event_type == "plan" and not (
                data.get("actions") if isinstance(data.get("actions"), list) else []
            ):
                next_index = next_observations.get(event_index, -1)
                post_observation = (
                    events[next_index].get("data", {})
                    if 0 <= next_index < len(events) and isinstance(events[next_index].get("data", {}), dict)
                    else {}
                )
                unit = _plan_response_unit(
                    session_id=session_id,
                    ordinal=len(units) + 1,
                    event_index=event_index,
                    plan=data,
                    observation_before=latest_observation,
                    observation_before_index=latest_observation_index,
                    observation_after=post_observation,
                    observation_after_index=next_index,
                    goal=current_goal,
                )
                unit["violations"].extend(_evaluate_unit_constraints(unit))
                units.append(unit)
                if len(units) >= max_units:
                    break
            continue

        action = data.get("action", {}) if isinstance(data.get("action", {}), dict) else {}
        result = data.get("result", {}) if isinstance(data.get("result", {}), dict) else {}
        pre_observation = (
            data.get("pre_observation", {})
            if isinstance(data.get("pre_observation", {}), dict) and data.get("pre_observation")
            else latest_observation
        )
        pre_observation_index = event_index if data.get("pre_observation") else latest_observation_index
        next_index = next_observations.get(event_index, -1)
        post_observation = (
            data.get("post_observation", {})
            if isinstance(data.get("post_observation", {}), dict) and data.get("post_observation")
            else (
                events[next_index].get("data", {})
                if 0 <= next_index < len(events) and isinstance(events[next_index].get("data", {}), dict)
                else {}
            )
        )
        post_observation_index = event_index if data.get("post_observation") else next_index
        planned_actions = latest_plan.get("actions", []) if isinstance(latest_plan.get("actions", []), list) else []
        planned_index = _match_planned_action(action, planned_actions, plan_cursor)
        if planned_index >= 0:
            plan_cursor = planned_index + 1
        verification_index, verification = _consume_verification(action, pending_verifications)
        action_type = str(action.get("type") or result.get("action_type") or "unknown").strip().lower()
        params = action.get("parameters", {}) if isinstance(action.get("parameters", {}), dict) else {}
        inventory_delta = _inventory_delta(pre_observation, post_observation)
        target = _action_target(action_type, params)
        result_position = result.get("position", {}) if isinstance(result.get("position", {}), dict) else {}
        final_position = result_position or (
            post_observation.get("position", {})
            if isinstance(post_observation.get("position", {}), dict)
            else {}
        )
        plan_id = _fingerprint(
            f"{session_id}|plan|{latest_plan_index}|{_plan_signature(latest_plan)}"
        )
        unit = {
            "unit_id": _fingerprint(f"{session_id}|unit|action|{event_index}|{_action_signature(action)}"),
            "unit_kind": "action_cycle",
            "ordinal": len(units) + 1,
            "session_id": session_id,
            "event_index": event_index,
            "plan_event_index": latest_plan_index,
            "plan_id": plan_id,
            "plan_status": str(latest_plan.get("status") or "unknown")[:32],
            "belief_present": bool(str(latest_plan.get("reasoning") or "").strip()),
            "belief_fingerprint": _fingerprint(str(latest_plan.get("reasoning") or "")) if latest_plan else "",
            "planned_action_index": planned_index,
            "planned_action_count": len(planned_actions),
            "planned_actions_omitted": 0,
            "planned_actions_deferred": 0,
            "omitted_action_signatures": [],
            "observation_before_index": pre_observation_index,
            "observation_after_index": post_observation_index,
            "verification_event_index": verification_index,
            "verification_status": str(verification.get("status") or "not_observed").lower(),
            "goal_fingerprint": _fingerprint(current_goal),
            "action_type": action_type,
            "action_signature": _action_signature(action),
            "argument_keys": sorted(str(key)[:64] for key in params.keys())[:24],
            "target": target,
            "target_signature": _target_signature(target),
            "result_success": result.get("success") is True,
            "result_error_signature": _error_signature(result.get("error")),
            "result_reached": result.get("reached") is True,
            "plan_suffix_deferred": (
                action_type in NAVIGATION_ACTIONS
                and result.get("success") is True
                and result.get("requires_replan") is True
                and result.get("replan_reason") == "navigation_target_unreached"
            ),
            "inventory_delta": inventory_delta,
            "state_before": _state_summary(pre_observation),
            "state_after": _state_summary(post_observation),
            "state_changed": _state_summary(pre_observation) != _state_summary(post_observation),
            "effect_confirmed": False,
            "navigation_confirmed": False,
            "dependency_artifacts": [],
            "violations": [],
            "_action": action,
            "_planned_action_signatures": [
                _action_signature(item) for item in planned_actions if isinstance(item, dict)
            ],
            "_omitted_action_signatures": [],
            "_params": params,
            "_result": result,
            "_pre_observation": pre_observation,
            "_post_observation": post_observation,
            "_final_position": final_position,
        }
        unit["dependency_artifacts"] = _dependency_artifacts(unit)
        unit["violations"].extend(_evaluate_unit_constraints(unit))
        units.append(unit)
        if len(units) >= max_units:
            break

    _add_unexecuted_plan_units(units, plan_records, session_id, max_units)
    units.sort(key=lambda item: (item.get("event_index", -1), 0 if item.get("unit_kind") == "planner_response" else 1))
    for ordinal, unit in enumerate(units, start=1):
        unit["ordinal"] = ordinal
    _evaluate_plan_execution_coverage(units)
    _evaluate_plan_dependencies(units)
    _evaluate_repeated_failures(units)
    _mark_recovered_violations(units)
    return units


def build_dependency_edges(units: list[dict]) -> list[dict]:
    """Build temporal and typed information-flow edges between units."""
    edges = []
    seen = set()

    def add_edge(source: dict, target: dict, edge_type: str, relation: str = ""):
        if not source or not target or source.get("unit_id") == target.get("unit_id"):
            return
        key = (source.get("unit_id"), target.get("unit_id"), edge_type, relation)
        if key in seen:
            return
        seen.add(key)
        edges.append({
            "from": source.get("unit_id"),
            "to": target.get("unit_id"),
            "type": edge_type,
            "relation": str(relation)[:96],
        })

    for previous, current in zip(units, units[1:]):
        add_edge(previous, current, "temporal")

    by_plan: dict[str, list[dict]] = defaultdict(list)
    for unit in units:
        if unit.get("plan_event_index", -1) >= 0:
            by_plan[str(unit.get("plan_id"))].append(unit)
    for group in by_plan.values():
        ordered = sorted(group, key=lambda item: item.get("ordinal", 0))
        for previous, current in zip(ordered, ordered[1:]):
            add_edge(previous, current, "plan_order")

    last_artifact: dict[str, dict] = {}
    last_error: dict[str, dict] = {}
    last_target: dict[str, dict] = {}
    for unit in units:
        for artifact in unit.get("dependency_artifacts", []) or []:
            previous = last_artifact.get(artifact)
            if previous:
                add_edge(previous, unit, "shared_artifact", artifact)
            last_artifact[artifact] = unit
        error = str(unit.get("result_error_signature") or "")
        if error:
            previous = last_error.get(error)
            if previous:
                add_edge(previous, unit, "shared_error", error)
            last_error[error] = unit
        target = str(unit.get("target_signature") or "")
        if target:
            previous = last_target.get(target)
            if previous:
                add_edge(previous, unit, "shared_target", target)
            last_target[target] = unit
    return edges


def localize_critical_transition(
    units: list[dict],
    edges: list[dict],
    terminal: Optional[dict] = None,
) -> dict:
    """Select the earliest high-confidence violation that remained unresolved."""
    terminal = terminal if isinstance(terminal, dict) else {}
    terminal_failed = terminal.get("completed") is False
    if not terminal_failed:
        return {
            "found": False,
            "reason": "trajectory_has_no_failed_terminal_boundary",
            "localizer_profile": LOCALIZER_PROFILE,
        }

    outgoing = Counter(edge.get("from") for edge in edges)
    incoming = Counter(edge.get("to") for edge in edges)
    candidates = []
    for unit in units:
        violations = [
            violation for violation in unit.get("violations", []) or []
            if isinstance(violation, dict)
            and violation.get("recovered") is not True
            and _safe_float(violation.get("severity"), 0.0) >= 0.5
        ]
        if not violations:
            continue
        highest = max(
            violations,
            key=lambda item: (
                _safe_float(item.get("severity"), 0.0),
                CONSTRAINT_PRIORITY.get(str(item.get("constraint_id") or ""), 0),
            ),
        )
        severity = _safe_float(highest.get("severity"), 0.0)
        structural = min(0.2, 0.025 * outgoing[unit.get("unit_id")] + 0.015 * incoming[unit.get("unit_id")])
        persistence = min(0.2, 0.04 * max(0, len(violations) - 1))
        score = min(1.5, severity + structural + persistence)
        candidates.append({
            "unit": unit,
            "violations": violations,
            "primary_violation": highest,
            "critical_score": round(score, 6),
        })
    if not candidates:
        return {
            "found": False,
            "reason": "failed_trajectory_has_no_unrecovered_structured_violation",
            "localizer_profile": LOCALIZER_PROFILE,
        }

    maximum = max(item["critical_score"] for item in candidates)
    frontier = [
        item for item in candidates
        if item["critical_score"] >= max(0.7, maximum - 0.2)
    ]
    selected = min(frontier, key=lambda item: (item["unit"].get("ordinal", 0), -item["critical_score"]))
    unit = selected["unit"]
    violation = selected["primary_violation"]
    recency = max(candidates, key=lambda item: item["unit"].get("ordinal", 0))
    first_violation = min(candidates, key=lambda item: item["unit"].get("ordinal", 0))
    packet_ids = _evidence_packet_ids(unit, edges)
    by_id = {item.get("unit_id"): item for item in units}
    return {
        "found": True,
        "localizer_profile": LOCALIZER_PROFILE,
        "critical_unit_id": unit.get("unit_id"),
        "critical_unit_ordinal": unit.get("ordinal"),
        "critical_event_index": unit.get("event_index"),
        "critical_score": selected["critical_score"],
        "category": violation.get("category"),
        "constraint_id": violation.get("constraint_id"),
        "action_type": unit.get("action_type"),
        "target_signature": unit.get("target_signature"),
        "unrecovered_violation_count": len(selected["violations"]),
        "distance_to_terminal_units": max(0, len(units) - _safe_int(unit.get("ordinal"), len(units))),
        "evidence_packet": [
            _public_unit(by_id[unit_id], include_violations=True)
            for unit_id in packet_ids
            if unit_id in by_id
        ],
        "baselines": {
            "recency_unit_ordinal": recency["unit"].get("ordinal"),
            "first_unrecovered_unit_ordinal": first_violation["unit"].get("ordinal"),
        },
    }


def analyze_critical_trajectory(
    events: list[dict],
    case_id: str = "",
    source_kind: str = "unknown",
    expected_label: Optional[dict] = None,
    max_units: int = MAX_UNITS,
) -> dict:
    """Build one graph, localize its failure, and emit review-only repair state."""
    explicit_session_id = _explicit_session_id(events)
    session_id = explicit_session_id or _fingerprint(case_id or json.dumps(events[:2], default=str))
    units = build_transition_units(events, session_id=session_id, max_units=max_units)
    edges = build_dependency_edges(units)
    terminal = _terminal_boundary(events)
    diagnosis = localize_critical_transition(units, edges, terminal=terminal)
    label = _normalize_expected_label(expected_label or {}, units)
    repair = _repair_memory_candidate(diagnosis, session_id)
    edge_counts = Counter(edge.get("type") for edge in edges)
    violation_counts = Counter()
    recovered_count = 0
    for unit in units:
        for violation in unit.get("violations", []) or []:
            violation_counts[str(violation.get("constraint_id") or "unknown")] += 1
            if violation.get("recovered") is True:
                recovered_count += 1
    action_count = sum(1 for event in events if event.get("type") == "action")
    action_unit_count = sum(1 for unit in units if unit.get("unit_kind") == "action_cycle")
    return {
        "case_id": str(case_id or session_id)[:96],
        "source_kind": source_kind,
        "session_id": session_id,
        "session_id_explicit": bool(explicit_session_id),
        "connected": _connect_success(events),
        "terminal": terminal,
        "event_count": len(events),
        "action_event_count": action_count,
        "action_transition_unit_count": action_unit_count,
        "transition_unit_count": len(units),
        "unit_coverage_rate": _ratio(action_unit_count, action_count) if action_count else 1.0,
        "planner_response_unit_count": len(units) - action_unit_count,
        "dependency_edge_count": len(edges),
        "dependency_edge_counts": dict(sorted(edge_counts.items())),
        "violation_count": sum(violation_counts.values()),
        "recovered_violation_count": recovered_count,
        "unrecovered_violation_count": sum(violation_counts.values()) - recovered_count,
        "violation_counts": dict(sorted(violation_counts.items())),
        "diagnosis": diagnosis,
        "repair_memory_candidate": repair,
        "expected_label": label,
        "label_evaluation": _evaluate_label(diagnosis, label),
        "graph": {
            "unit_profile": UNIT_PROFILE,
            "graph_profile": GRAPH_PROFILE,
            "units": [_public_unit(unit, include_violations=True) for unit in units],
            "edges": edges,
        },
    }


def build_critical_transition_report(
    session_log_paths: Optional[list[str]] = None,
    case_paths: Optional[list[str]] = None,
    label_paths: Optional[list[str]] = None,
    include_builtins: bool = False,
    evidence_kind: str = "unknown",
    max_units_per_trajectory: int = MAX_UNITS,
    include_graphs: bool = False,
) -> dict:
    """Build an aggregate review-only critical transition report."""
    session_log_paths = list(session_log_paths or [])
    case_paths = list(case_paths or [])
    label_paths = list(label_paths or [])
    evidence_kind = str(evidence_kind or "unknown").strip().lower()
    max_units_per_trajectory = max(1, min(MAX_UNITS, _safe_int(max_units_per_trajectory, MAX_UNITS)))
    report = {
        "type": REPORT_TYPE,
        "schema_version": SCHEMA_VERSION,
        "unit_profile": UNIT_PROFILE,
        "graph_profile": GRAPH_PROFILE,
        "localizer_profile": LOCALIZER_PROFILE,
        "repair_memory_profile": REPAIR_MEMORY_PROFILE,
        "readiness": "review",
        "decision": "emit_review_only_critical_transition_diagnostics",
        "reason": "critical-transition diagnoses require manual labels and repair-outcome evidence before planner use",
        "evidence_kind": evidence_kind,
        "runtime_eligible": False,
        "planner_guidance_allowed": False,
        "automatic_retry_allowed": False,
        "runtime_intervention_allowed": False,
        "automatic_memory_promotion_allowed": False,
        "automatic_skill_mutation_allowed": False,
        "trajectory_count": 0,
        "trajectories": [],
        "metrics": {},
        "localization_metrics": {},
        "repair_memory_candidates": [],
        "evidence_integrity": {},
        "source_manifests": [],
        "missing": [],
        "errors": [],
    }
    if evidence_kind not in {"unknown", "synthetic_control", "live_trace"}:
        report["errors"].append("evidence_kind must be unknown, synthetic_control, or live_trace")

    labels, label_manifests, label_errors = _load_labels(label_paths)
    report["source_manifests"].extend(label_manifests)
    report["errors"].extend(label_errors)
    trajectories = []
    normalized_paths = [_normalized_path(path) for path in label_paths]

    for path in session_log_paths:
        try:
            events, manifest = _read_jsonl_manifest(path)
            normalized_paths.append(_normalized_path(path))
            report["source_manifests"].append(manifest)
            session_id = _explicit_session_id(events)
            label = _label_for(labels, session_id=session_id, case_id="", path=path)
            trajectory = analyze_critical_trajectory(
                events,
                case_id=session_id or os.path.basename(path),
                source_kind="session_log",
                expected_label=label,
                max_units=max_units_per_trajectory,
            )
            trajectories.append(_report_trajectory(trajectory, include_graphs))
        except Exception as exc:
            report["errors"].append(f"{path}: {exc}")

    loaded_cases, case_manifests, case_errors = _load_case_files(case_paths)
    normalized_paths.extend(_normalized_path(path) for path in case_paths)
    report["source_manifests"].extend(case_manifests)
    report["errors"].extend(case_errors)
    for item in loaded_cases:
        case_id = str(item.get("case_id") or f"case-{len(trajectories) + 1:03d}")
        expected = item.get("expected_label", {}) if isinstance(item.get("expected_label", {}), dict) else {}
        external = _label_for(labels, session_id=str(item.get("session_id") or ""), case_id=case_id, path="")
        trajectory = analyze_critical_trajectory(
            item.get("events", []),
            case_id=case_id,
            source_kind="case_file",
            expected_label=external or expected,
            max_units=max_units_per_trajectory,
        )
        trajectories.append(_report_trajectory(trajectory, include_graphs))

    if include_builtins:
        for item in _builtin_cases():
            trajectory = analyze_critical_trajectory(
                item["events"],
                case_id=item["case_id"],
                source_kind="builtin",
                expected_label=item.get("expected_label", {}),
                max_units=max_units_per_trajectory,
            )
            trajectories.append(_report_trajectory(trajectory, include_graphs))

    report["trajectories"] = trajectories
    report["trajectory_count"] = len(trajectories)
    if not trajectories:
        report["missing"].append("session_logs_or_cases")
    report["metrics"] = _aggregate_metrics(trajectories)
    report["localization_metrics"] = _aggregate_label_metrics(trajectories)
    report["repair_memory_candidates"] = _aggregate_repair_candidates(trajectories)
    source_kinds = Counter(item.get("source_kind") for item in trajectories)
    manifests_valid = bool(report["source_manifests"]) and all(
        _manifest_valid(item) for item in report["source_manifests"]
    )
    input_paths_unique = len(normalized_paths) == len(set(normalized_paths))
    session_trajectories = [item for item in trajectories if item.get("source_kind") == "session_log"]
    explicit_sessions = [
        item.get("session_id")
        for item in session_trajectories
        if item.get("session_id_explicit") is True
    ]
    all_sessions_explicit = bool(session_trajectories) and all(
        item.get("session_id_explicit") is True for item in session_trajectories
    )
    report["evidence_integrity"] = {
        "input_paths_unique": input_paths_unique,
        "source_manifests_valid": manifests_valid,
        "explicit_session_ids": all_sessions_explicit,
        "distinct_session_count": len(set(explicit_sessions)),
        "complete_terminal_count": sum(1 for item in trajectories if item.get("terminal", {}).get("complete_boundary")),
        "connected_session_count": sum(1 for item in trajectories if item.get("source_kind") == "session_log" and item.get("connected")),
        "source_kind_counts": dict(sorted(source_kinds.items())),
        "builtin_case_count": source_kinds.get("builtin", 0),
    }
    if not input_paths_unique:
        report["missing"].append("unique_input_paths")
    if report["source_manifests"] and not manifests_valid:
        report["missing"].append("valid_source_manifests")
    if evidence_kind == "live_trace" and not session_trajectories:
        report["missing"].append("live_session_logs")
    elif evidence_kind == "live_trace" and not all_sessions_explicit:
        report["missing"].append("explicit_live_session_ids")
    if report["localization_metrics"].get("externally_labeled_trajectory_count", 0) == 0:
        report["missing"].append("external_manual_critical_transition_labels")
    report["missing"] = sorted(set(report["missing"]))
    if report["errors"]:
        report["readiness"] = "error"
        report["decision"] = "reject_critical_transition_report"
        report["reason"] = "one or more trajectory sources could not be normalized"
    return report


def _report_trajectory(trajectory: dict, include_graphs: bool) -> dict:
    if include_graphs:
        return trajectory
    compact = dict(trajectory)
    graph = compact.pop("graph", {}) if isinstance(compact.get("graph", {}), dict) else {}
    compact["graph_summary"] = {
        "unit_profile": graph.get("unit_profile", UNIT_PROFILE),
        "graph_profile": graph.get("graph_profile", GRAPH_PROFILE),
        "full_graph_included": False,
        "unit_count": len(graph.get("units", []) or []),
        "edge_count": len(graph.get("edges", []) or []),
    }
    return compact


def write_critical_transition_report(report: dict, path: str):
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)


def _evaluate_unit_constraints(unit: dict) -> list[dict]:
    action_type = unit.get("action_type", "unknown")
    params = unit.get("_params", {})
    result = unit.get("_result", {})
    constraints = []
    if action_type == "planner_response":
        omitted = max(0, _safe_int(unit.get("planned_actions_omitted"), 0))
        if omitted:
            constraints.append(_violation(
                "planned_actions_not_executed",
                "plan_adherence_failure",
                1.0,
                unit,
                {"planned_actions_omitted": omitted},
                recovery_key=f"plan-execution:{unit.get('plan_id')}",
            ))
        elif str(unit.get("plan_status") or "unknown").lower() != "complete":
            constraints.append(_violation(
                "empty_plan_without_transition",
                "intent_plan_misalignment",
                0.9,
                unit,
                {"plan_status": unit.get("plan_status")},
                recovery_key=f"planner-response:{unit.get('goal_fingerprint')}",
            ))
        return constraints
    if action_type not in KNOWN_ACTIONS:
        constraints.append(_violation(
            "unsupported_action",
            "intent_not_supported",
            1.0,
            unit,
            {"action_type": action_type},
            recovery_key=f"supported:{action_type}",
        ))
    required = REQUIRED_ARGUMENTS.get(action_type, ())
    missing = [key for key in required if params.get(key) in (None, "")]
    if missing:
        constraints.append(_violation(
            "invalid_action_schema",
            "invalid_invocation",
            1.0,
            unit,
            {"missing_argument_keys": missing},
            recovery_key=f"schema:{action_type}",
        ))

    verification_status = unit.get("verification_status")
    if verification_status == "reject":
        constraints.append(_violation(
            "action_verifier_reject",
            "guardrails_triggered",
            0.9,
            unit,
            {"verification_event_index": unit.get("verification_event_index")},
            recovery_key=f"verifier:{unit.get('action_signature')}",
        ))
        if result.get("verification_blocked") is not True and result:
            constraints.append(_violation(
                "action_verifier_bypassed",
                "plan_adherence_failure",
                1.0,
                unit,
                {"result_was_recorded": True},
                recovery_key=f"verifier:{unit.get('action_signature')}",
            ))

    if result.get("success") is False:
        error_signature = unit.get("result_error_signature") or "unknown-error"
        system_failure = any(token in str(result.get("error") or "").lower() for token in SYSTEM_ERROR_TOKENS)
        constraints.append(_violation(
            "backend_system_failure" if system_failure else "action_execution_failure",
            "system_failure" if system_failure else "execution_failure",
            0.95 if system_failure else 0.8,
            unit,
            {"error_signature": error_signature},
            recovery_key=f"action:{action_type}:{unit.get('target_signature')}",
        ))

    if action_type in NAVIGATION_ACTIONS and result.get("success") is True:
        distance = _navigation_distance(unit)
        tolerance = _navigation_tolerance(unit)
        reached = distance is not None and distance <= tolerance + 0.75
        unit["navigation_confirmed"] = reached
        if action_type == "move_to" and distance is None:
            constraints.append(_violation(
                "missing_post_action_feedback",
                "tool_output_misinterpretation",
                0.65,
                unit,
                {"feedback_kind": "navigation_position"},
                recovery_key=f"navigation:{unit.get('target_signature')}",
            ))
        elif action_type == "move_to" and not reached:
            constraints.append(_violation(
                "navigation_success_without_reach",
                "tool_output_misinterpretation",
                1.0,
                unit,
                {"distance_to_target": _round_optional(distance), "tolerance": tolerance},
                recovery_key=f"navigation:{unit.get('target_signature')}",
            ))

    if action_type == "dig" and result.get("success") is True:
        before_block = _block_at(unit.get("_pre_observation", {}), params)
        after_block = _block_at(unit.get("_post_observation", {}), params)
        target_distance = _position_to_target_distance(unit.get("_pre_observation", {}).get("position", {}), params)
        if before_block and not after_block:
            unit["effect_confirmed"] = True
        elif before_block and after_block:
            constraints.append(_violation(
                "world_effect_mismatch",
                "tool_output_misinterpretation",
                1.0,
                unit,
                {"before_block": before_block, "after_block": after_block},
                recovery_key=f"effect:{unit.get('target_signature')}",
            ))
        elif target_distance is not None and target_distance > 6.0:
            constraints.append(_violation(
                "ungrounded_world_target",
                "invention_of_information",
                0.9,
                unit,
                {"distance_from_observation": round(target_distance, 3)},
                recovery_key=f"grounding:{unit.get('target_signature')}",
            ))
        elif unit.get("_post_observation"):
            constraints.append(_violation(
                "world_effect_unverified",
                "tool_output_misinterpretation",
                0.55,
                unit,
                {"target_visible_before": bool(before_block)},
                recovery_key=f"effect:{unit.get('target_signature')}",
            ))

    if action_type == "craft" and result.get("success") is True and unit.get("_post_observation"):
        item = _normalize_item(params.get("item"))
        if item and _safe_int(unit.get("inventory_delta", {}).get(item), 0) > 0:
            unit["effect_confirmed"] = True
        elif item:
            constraints.append(_violation(
                "world_effect_mismatch",
                "tool_output_misinterpretation",
                0.9,
                unit,
                {"expected_inventory_item": item},
                recovery_key=f"effect:item:{item}",
            ))

    if action_type in WORLD_CHANGING_ACTIONS and result.get("success") is True and not unit.get("_post_observation"):
        constraints.append(_violation(
            "missing_post_action_feedback",
            "tool_output_misinterpretation",
            0.6,
            unit,
            {"feedback_kind": "world_state"},
            recovery_key=f"feedback:{action_type}:{unit.get('target_signature')}",
        ))
    return constraints


def _evaluate_plan_dependencies(units: list[dict]):
    by_plan: dict[str, list[dict]] = defaultdict(list)
    for unit in units:
        by_plan[str(unit.get("plan_id"))].append(unit)
    for group in by_plan.values():
        ordered = sorted(group, key=lambda item: item.get("planned_action_index", -1))
        for index, unit in enumerate(ordered):
            if unit.get("action_type") not in NAVIGATION_ACTIONS:
                continue
            dependents = [item for item in ordered[index + 1:] if item.get("action_type") in WORLD_CHANGING_ACTIONS]
            if not dependents or unit.get("navigation_confirmed"):
                continue
            unit["violations"].append(_violation(
                "unreached_navigation_has_dependents",
                "plan_adherence_failure",
                1.0,
                unit,
                {"dependent_unit_ids": [item.get("unit_id") for item in dependents[:8]]},
                recovery_key=f"navigation:{unit.get('target_signature')}",
            ))
            for dependent in dependents:
                dependent["violations"].append(_violation(
                    "dependent_action_after_unreached_navigation",
                    "plan_adherence_failure",
                    0.95,
                    dependent,
                    {"navigation_unit_id": unit.get("unit_id")},
                    recovery_key=f"plan:{unit.get('plan_id')}",
                ))


def _add_unexecuted_plan_units(
    units: list[dict],
    plan_records: dict[int, dict],
    session_id: str,
    max_units: int,
):
    represented = Counter(
        _safe_int(unit.get("plan_event_index"), -1)
        for unit in units
        if unit.get("unit_kind") == "action_cycle"
    )
    for event_index, record in sorted(plan_records.items()):
        plan = record.get("plan", {}) if isinstance(record.get("plan", {}), dict) else {}
        actions = plan.get("actions", []) if isinstance(plan.get("actions", []), list) else []
        if not actions or represented[event_index] > 0 or len(units) >= max_units:
            continue
        unit = _plan_response_unit(
            session_id=session_id,
            ordinal=0,
            event_index=event_index,
            plan=plan,
            observation_before=record.get("observation_before", {}),
            observation_before_index=_safe_int(record.get("observation_before_index"), -1),
            observation_after=record.get("observation_after", {}),
            observation_after_index=_safe_int(record.get("observation_after_index"), -1),
            goal=str(record.get("goal") or ""),
            planned_actions_omitted=len(actions),
            omitted_action_signatures=[
                _action_signature(action) for action in actions if isinstance(action, dict)
            ],
        )
        unit["violations"].extend(_evaluate_unit_constraints(unit))
        units.append(unit)


def _evaluate_plan_execution_coverage(units: list[dict]):
    by_plan: dict[str, list[dict]] = defaultdict(list)
    for unit in units:
        if unit.get("unit_kind") == "action_cycle" and unit.get("plan_event_index", -1) >= 0:
            by_plan[str(unit.get("plan_id"))].append(unit)
    for group in by_plan.values():
        planned_count = max(_safe_int(unit.get("planned_action_count"), 0) for unit in group)
        planned_indexes = {unit.get("planned_action_index") for unit in group if unit.get("planned_action_index", -1) >= 0}
        missing_indexes = [index for index in range(planned_count) if index not in planned_indexes]
        omitted = len(missing_indexes)
        if not omitted:
            continue
        anchor = max(group, key=lambda item: item.get("event_index", -1))
        planned_signatures = anchor.get("_planned_action_signatures", []) or []
        omitted_signatures = [
            planned_signatures[index]
            for index in missing_indexes
            if 0 <= index < len(planned_signatures)
        ]
        anchor["_omitted_action_signatures"] = omitted_signatures
        anchor["omitted_action_signatures"] = omitted_signatures
        anchor["planned_actions_omitted"] = omitted
        if anchor.get("plan_suffix_deferred") is True and anchor.get("navigation_confirmed") is not True:
            anchor["planned_actions_deferred"] = omitted
            continue
        anchor["violations"].append(_violation(
            "planned_actions_not_executed",
            "plan_adherence_failure",
            1.0,
            anchor,
            {
                "planned_actions_omitted": omitted,
                "planned_action_count": planned_count,
                "omitted_action_signatures": omitted_signatures,
            },
            recovery_key=f"plan-execution:{anchor.get('plan_id')}",
        ))


def _evaluate_repeated_failures(units: list[dict]):
    failures: dict[tuple[str, str], list[dict]] = defaultdict(list)
    no_progress: dict[str, list[dict]] = defaultdict(list)
    for unit in units:
        error = str(unit.get("result_error_signature") or "")
        if error:
            failures[(str(unit.get("action_type")), error)].append(unit)
        if not unit.get("state_changed"):
            no_progress[str(unit.get("action_signature"))].append(unit)
    for (action_type, error), group in failures.items():
        if len(group) < 2:
            continue
        first = group[0]
        first["violations"].append(_violation(
            "repeated_failure_signature",
            "plan_adherence_failure",
            0.85,
            first,
            {"repeat_count": len(group), "error_signature": error},
            recovery_key=f"action:{action_type}:{first.get('target_signature')}",
        ))
    for signature, group in no_progress.items():
        if len(group) < 3:
            continue
        first = group[0]
        first["violations"].append(_violation(
            "repeated_no_progress",
            "plan_adherence_failure",
            0.75,
            first,
            {"repeat_count": len(group), "action_signature": signature},
            recovery_key=f"progress:{signature}",
        ))


def _mark_recovered_violations(units: list[dict]):
    for index, unit in enumerate(units):
        for violation in unit.get("violations", []) or []:
            violation["recovered"] = False
            violation["recovery_unit_id"] = ""
            if violation.get("constraint_id") == "planned_actions_not_executed":
                required = set(unit.get("_omitted_action_signatures", []) or [])
                matched = [
                    later for later in units[index + 1:]
                    if later.get("action_signature") in required and _unit_has_verified_success(later)
                ]
                if required and required.issubset({later.get("action_signature") for later in matched}):
                    violation["recovered"] = True
                    violation["recovery_unit_id"] = matched[-1].get("unit_id")
                    continue
            for later in units[index + 1:]:
                if _later_unit_resolves(violation, unit, later):
                    violation["recovered"] = True
                    violation["recovery_unit_id"] = later.get("unit_id")
                    break


def _later_unit_resolves(violation: dict, origin: dict, later: dict) -> bool:
    constraint = str(violation.get("constraint_id") or "")
    same_action = later.get("action_type") == origin.get("action_type")
    same_target = bool(origin.get("target_signature")) and later.get("target_signature") == origin.get("target_signature")
    if constraint in {"navigation_success_without_reach", "unreached_navigation_has_dependents"}:
        return same_target and later.get("navigation_confirmed") is True
    if constraint == "empty_plan_without_transition":
        return (
            later.get("unit_kind") == "action_cycle"
            and later.get("goal_fingerprint") == origin.get("goal_fingerprint")
            and _unit_has_verified_success(later)
        )
    if constraint in {"action_execution_failure", "backend_system_failure", "repeated_failure_signature"}:
        return same_action and (same_target or not origin.get("target_signature")) and _unit_has_verified_success(later)
    if constraint == "invalid_action_schema":
        return same_action and not any(item.get("constraint_id") == constraint for item in later.get("violations", []))
    if constraint in {"world_effect_mismatch", "world_effect_unverified", "ungrounded_world_target"}:
        return same_target and later.get("effect_confirmed") is True
    return False


def _unit_has_verified_success(unit: dict) -> bool:
    if unit.get("result_success") is not True:
        return False
    action_type = str(unit.get("action_type") or "")
    if action_type in NAVIGATION_ACTIONS:
        return unit.get("navigation_confirmed") is True
    if action_type in {"dig", "craft", "place"}:
        return unit.get("effect_confirmed") is True
    return True


def _violation(
    constraint_id: str,
    category: str,
    severity: float,
    unit: dict,
    evidence: Optional[dict] = None,
    recovery_key: str = "",
) -> dict:
    return {
        "constraint_id": constraint_id,
        "category": category,
        "severity": round(max(0.0, min(1.0, _safe_float(severity, 0.0))), 6),
        "event_index": unit.get("event_index"),
        "evidence": evidence or {},
        "recovery_key": _fingerprint(recovery_key) if recovery_key else "",
        "recovered": False,
        "recovery_unit_id": "",
    }


def _repair_memory_candidate(diagnosis: dict, session_id: str) -> dict:
    if not diagnosis.get("found"):
        return {}
    constraint = str(diagnosis.get("constraint_id") or "")
    directive = REPAIR_DIRECTIVES.get(constraint, "review_critical_transition_before_retry")
    repair_key = _fingerprint(
        f"{directive}|{diagnosis.get('action_type')}|{diagnosis.get('target_signature')}"
    )
    return {
        "repair_key": repair_key,
        "profile": REPAIR_MEMORY_PROFILE,
        "state": "unresolved",
        "directive_code": directive,
        "constraint_id": constraint,
        "category": diagnosis.get("category"),
        "action_family": diagnosis.get("action_type"),
        "target_signature": diagnosis.get("target_signature"),
        "source_session_fingerprint": _fingerprint(session_id),
        "source_unit_id": diagnosis.get("critical_unit_id"),
        "evidence_grounded": True,
        "cooldown_required": True,
        "minimal_intervention_required": True,
        "planner_context_allowed": False,
        "automatic_retry_allowed": False,
        "runtime_intervention_allowed": False,
    }


def _aggregate_metrics(trajectories: list[dict]) -> dict:
    return {
        "failed_trajectory_count": sum(1 for item in trajectories if item.get("terminal", {}).get("completed") is False),
        "completed_trajectory_count": sum(1 for item in trajectories if item.get("terminal", {}).get("completed") is True),
        "critical_transition_found_count": sum(1 for item in trajectories if item.get("diagnosis", {}).get("found")),
        "action_event_count": sum(_safe_int(item.get("action_event_count"), 0) for item in trajectories),
        "action_transition_unit_count": sum(_safe_int(item.get("action_transition_unit_count"), 0) for item in trajectories),
        "planner_response_unit_count": sum(_safe_int(item.get("planner_response_unit_count"), 0) for item in trajectories),
        "transition_unit_count": sum(_safe_int(item.get("transition_unit_count"), 0) for item in trajectories),
        "dependency_edge_count": sum(_safe_int(item.get("dependency_edge_count"), 0) for item in trajectories),
        "violation_count": sum(_safe_int(item.get("violation_count"), 0) for item in trajectories),
        "recovered_violation_count": sum(_safe_int(item.get("recovered_violation_count"), 0) for item in trajectories),
        "mean_unit_coverage_rate": round(_mean([_safe_float(item.get("unit_coverage_rate"), 0.0) for item in trajectories]), 6),
    }


def _aggregate_label_metrics(trajectories: list[dict]) -> dict:
    labeled = [item for item in trajectories if item.get("expected_label", {}).get("available")]
    external = [item for item in labeled if item.get("source_kind") != "builtin"]
    exact = sum(1 for item in labeled if item.get("label_evaluation", {}).get("exact_unit_match"))
    within_one = sum(1 for item in labeled if item.get("label_evaluation", {}).get("within_one_unit"))
    category = sum(1 for item in labeled if item.get("label_evaluation", {}).get("category_match"))
    recency = sum(1 for item in labeled if item.get("label_evaluation", {}).get("recency_exact_match"))
    first = sum(1 for item in labeled if item.get("label_evaluation", {}).get("first_unrecovered_exact_match"))
    return {
        "labeled_trajectory_count": len(labeled),
        "externally_labeled_trajectory_count": len(external),
        "exact_unit_match_count": exact,
        "exact_unit_accuracy": _ratio(exact, len(labeled)),
        "within_one_unit_count": within_one,
        "within_one_unit_accuracy": _ratio(within_one, len(labeled)),
        "category_match_count": category,
        "category_accuracy": _ratio(category, len(labeled)),
        "recency_baseline_exact_count": recency,
        "recency_baseline_accuracy": _ratio(recency, len(labeled)),
        "first_unrecovered_baseline_exact_count": first,
        "first_unrecovered_baseline_accuracy": _ratio(first, len(labeled)),
        "localizer_exact_gain_over_recency": round(_ratio(exact, len(labeled)) - _ratio(recency, len(labeled)), 6),
    }


def _aggregate_repair_candidates(trajectories: list[dict]) -> list[dict]:
    grouped: dict[str, dict] = {}
    for trajectory in trajectories:
        candidate = trajectory.get("repair_memory_candidate", {})
        if not isinstance(candidate, dict) or not candidate.get("repair_key"):
            continue
        key = str(candidate["repair_key"])
        current = grouped.setdefault(key, {
            **candidate,
            "support_count": 0,
            "source_session_fingerprints": [],
        })
        current["support_count"] += 1
        fingerprint = candidate.get("source_session_fingerprint")
        if fingerprint and fingerprint not in current["source_session_fingerprints"]:
            current["source_session_fingerprints"].append(fingerprint)
    return sorted(grouped.values(), key=lambda item: (-item["support_count"], item["repair_key"]))


def _evaluate_label(diagnosis: dict, label: dict) -> dict:
    if not label.get("available"):
        return {"available": False}
    predicted = _safe_int(diagnosis.get("critical_unit_ordinal"), -1) if diagnosis.get("found") else -1
    expected = _safe_int(label.get("critical_unit_ordinal"), -1)
    distance = abs(predicted - expected) if predicted > 0 and expected > 0 else None
    recency = _safe_int(diagnosis.get("baselines", {}).get("recency_unit_ordinal"), -1)
    first = _safe_int(diagnosis.get("baselines", {}).get("first_unrecovered_unit_ordinal"), -1)
    return {
        "available": True,
        "expected_unit_ordinal": expected,
        "predicted_unit_ordinal": predicted,
        "unit_distance": distance,
        "exact_unit_match": distance == 0,
        "within_one_unit": distance is not None and distance <= 1,
        "category_match": str(diagnosis.get("category") or "") == str(label.get("category") or ""),
        "recency_exact_match": recency == expected,
        "first_unrecovered_exact_match": first == expected,
    }


def _normalize_expected_label(label: dict, units: list[dict]) -> dict:
    if not isinstance(label, dict) or not label:
        return {"available": False}
    ordinal = _safe_int(label.get("critical_unit_ordinal"), -1)
    event_index = _safe_int(label.get("critical_event_index"), -1)
    if ordinal <= 0 and event_index >= 0:
        matched = next((unit for unit in units if unit.get("event_index") == event_index), None)
        ordinal = _safe_int((matched or {}).get("ordinal"), -1)
    category = str(label.get("category") or "").strip()
    return {
        "available": ordinal > 0 and bool(category),
        "critical_unit_ordinal": ordinal,
        "critical_event_index": event_index,
        "category": category,
        "reviewer_id": str(label.get("reviewer_id") or "")[:96],
    }


def _public_unit(unit: dict, include_violations: bool = False) -> dict:
    payload = {
        key: unit.get(key)
        for key in (
            "unit_id",
            "unit_kind",
            "ordinal",
            "event_index",
            "plan_event_index",
            "plan_id",
            "plan_status",
            "belief_present",
            "belief_fingerprint",
            "planned_action_index",
            "planned_action_count",
            "planned_actions_omitted",
            "planned_actions_deferred",
            "omitted_action_signatures",
            "observation_before_index",
            "observation_after_index",
            "verification_event_index",
            "verification_status",
            "goal_fingerprint",
            "action_type",
            "action_signature",
            "argument_keys",
            "target",
            "target_signature",
            "result_success",
            "result_error_signature",
            "result_reached",
            "plan_suffix_deferred",
            "inventory_delta",
            "state_before",
            "state_after",
            "state_changed",
            "effect_confirmed",
            "navigation_confirmed",
            "dependency_artifacts",
        )
    }
    if include_violations:
        payload["violations"] = [dict(item) for item in unit.get("violations", []) if isinstance(item, dict)]
    return payload


def _evidence_packet_ids(unit: dict, edges: list[dict], limit: int = 5) -> list[str]:
    selected = str(unit.get("unit_id") or "")
    related = []
    for edge in edges:
        if edge.get("to") == selected:
            related.append(edge.get("from"))
        elif edge.get("from") == selected:
            related.append(edge.get("to"))
    result = []
    for unit_id in [selected, *related]:
        if unit_id and unit_id not in result:
            result.append(unit_id)
        if len(result) >= limit:
            break
    return result


def _plan_response_unit(
    session_id: str,
    ordinal: int,
    event_index: int,
    plan: dict,
    observation_before: dict,
    observation_before_index: int,
    observation_after: dict,
    observation_after_index: int,
    goal: str,
    planned_actions_omitted: int = 0,
    omitted_action_signatures: Optional[list[str]] = None,
) -> dict:
    plan_id = _fingerprint(f"{session_id}|plan|{event_index}|{_plan_signature(plan)}")
    signature = _fingerprint(f"planner-response|{plan.get('status')}|{plan_id}")
    return {
        "unit_id": _fingerprint(f"{session_id}|unit|planner|{event_index}|{signature}"),
        "unit_kind": "planner_response",
        "ordinal": ordinal,
        "session_id": session_id,
        "event_index": event_index,
        "plan_event_index": event_index,
        "plan_id": plan_id,
        "plan_status": str(plan.get("status") or "unknown")[:32],
        "belief_present": bool(str(plan.get("reasoning") or "").strip()),
        "belief_fingerprint": _fingerprint(str(plan.get("reasoning") or "")),
        "planned_action_index": -1,
        "planned_action_count": max(0, _safe_int(planned_actions_omitted, 0)),
        "planned_actions_omitted": max(0, _safe_int(planned_actions_omitted, 0)),
        "planned_actions_deferred": 0,
        "omitted_action_signatures": list(omitted_action_signatures or [])[:24],
        "observation_before_index": observation_before_index,
        "observation_after_index": observation_after_index,
        "verification_event_index": -1,
        "verification_status": "not_observed",
        "goal_fingerprint": _fingerprint(goal),
        "action_type": "planner_response",
        "action_signature": signature,
        "argument_keys": [],
        "target": {},
        "target_signature": "",
        "result_success": False,
        "result_error_signature": "",
        "result_reached": False,
        "plan_suffix_deferred": False,
        "inventory_delta": _inventory_delta(observation_before, observation_after),
        "state_before": _state_summary(observation_before),
        "state_after": _state_summary(observation_after),
        "state_changed": _state_summary(observation_before) != _state_summary(observation_after),
        "effect_confirmed": False,
        "navigation_confirmed": False,
        "dependency_artifacts": [],
        "violations": [],
        "_action": {"type": "planner_response", "parameters": {}},
        "_planned_action_signatures": list(omitted_action_signatures or []),
        "_omitted_action_signatures": list(omitted_action_signatures or []),
        "_params": {},
        "_result": {},
        "_pre_observation": observation_before,
        "_post_observation": observation_after,
        "_final_position": {},
    }


def _dependency_artifacts(unit: dict) -> list[str]:
    artifacts = []
    target = unit.get("target", {}) if isinstance(unit.get("target", {}), dict) else {}
    for key in ("item", "block", "entity", "position"):
        value = target.get(key)
        if value:
            artifacts.append(f"target:{key}:{_normalize_item(value)}")
    result = unit.get("_result", {})
    for key in ("item", "block"):
        value = result.get(key)
        if value:
            artifacts.append(f"result:{key}:{_normalize_item(value)}")
    for item, delta in (unit.get("inventory_delta", {}) or {}).items():
        artifacts.append(f"inventory:{_normalize_item(item)}:{'gain' if delta > 0 else 'spend'}")
    return sorted(set(artifacts))[:24]


def _action_target(action_type: str, params: dict) -> dict:
    target = {}
    for key in ("item", "block", "entity", "entity_id", "target"):
        if params.get(key) not in (None, ""):
            normalized_key = "entity" if key == "entity_id" else key
            target[normalized_key] = _normalize_item(params.get(key))
    if params.get("x") is not None and params.get("z") is not None:
        coordinates = [params.get("x"), params.get("z")]
        if params.get("y") is not None:
            coordinates.insert(1, params.get("y"))
        target["position"] = ",".join(_normalized_number(value) for value in coordinates)
    if action_type == "chat":
        target.pop("target", None)
    return target


def _target_signature(target: dict) -> str:
    if not target:
        return ""
    canonical = json.dumps(target, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return _fingerprint(canonical)


def _action_signature(action: dict) -> str:
    action = action if isinstance(action, dict) else {}
    action_type = str(action.get("type") or "unknown").strip().lower()
    params = action.get("parameters", {}) if isinstance(action.get("parameters", {}), dict) else {}
    target = _action_target(action_type, params)
    canonical = json.dumps({"type": action_type, "target": target}, sort_keys=True, separators=(",", ":"))
    return _fingerprint(canonical)


def _plan_signature(plan: dict) -> str:
    actions = plan.get("actions", []) if isinstance(plan.get("actions", []), list) else []
    signatures = [_action_signature(action) for action in actions if isinstance(action, dict)]
    return _fingerprint(f"{plan.get('status')}|{'|'.join(signatures)}")


def _match_planned_action(action: dict, planned: list[dict], cursor: int) -> int:
    signature = _action_signature(action)
    for index in range(max(0, cursor), len(planned)):
        if isinstance(planned[index], dict) and _action_signature(planned[index]) == signature:
            return index
    return -1


def _consume_verification(action: dict, pending: list[tuple[int, dict]]) -> tuple[int, dict]:
    signature = _action_signature(action)
    for index, (event_index, data) in enumerate(pending):
        candidate = data.get("action", {}) if isinstance(data.get("action", {}), dict) else {}
        if candidate and _action_signature(candidate) != signature:
            continue
        pending.pop(index)
        verification = data.get("verification", {}) if isinstance(data.get("verification", {}), dict) else {}
        return event_index, verification
    return -1, {}


def _navigation_distance(unit: dict) -> Optional[float]:
    params = unit.get("_params", {})
    position = unit.get("_final_position", {})
    return _position_to_target_distance(position, params, include_y=params.get("y") is not None)


def _navigation_tolerance(unit: dict) -> float:
    result = unit.get("_result", {})
    params = unit.get("_params", {})
    return max(1.0, min(8.0, _safe_float(result.get("tolerance", params.get("tolerance", 2)), 2.0)))


def _position_to_target_distance(position: dict, params: dict, include_y: bool = True) -> Optional[float]:
    try:
        dx = float(position.get("x")) - float(params.get("x"))
        dz = float(position.get("z")) - float(params.get("z"))
        dy = float(position.get("y")) - float(params.get("y")) if include_y and params.get("y") is not None else 0.0
    except (TypeError, ValueError):
        return None
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def _block_at(observation: dict, params: dict) -> str:
    target = (_safe_int(params.get("x"), 10**9), _safe_int(params.get("y"), 10**9), _safe_int(params.get("z"), 10**9))
    for block in observation.get("nearby_blocks", []) if isinstance(observation.get("nearby_blocks", []), list) else []:
        if not isinstance(block, dict):
            continue
        position = block.get("position", {}) if isinstance(block.get("position", {}), dict) else {}
        current = (_safe_int(position.get("x"), -10**9), _safe_int(position.get("y"), -10**9), _safe_int(position.get("z"), -10**9))
        if current == target:
            return _normalize_item(block.get("name"))
    return ""


def _inventory_delta(before: dict, after: dict) -> dict:
    before_inv = before.get("inventory", {}) if isinstance(before.get("inventory", {}), dict) else {}
    after_inv = after.get("inventory", {}) if isinstance(after.get("inventory", {}), dict) else {}
    result = {}
    for key in set(before_inv) | set(after_inv):
        delta = _safe_int(after_inv.get(key), 0) - _safe_int(before_inv.get(key), 0)
        if delta:
            result[_normalize_item(key)] = delta
    return dict(sorted(result.items()))


def _state_summary(observation: dict) -> dict:
    observation = observation if isinstance(observation, dict) else {}
    position = observation.get("position", {}) if isinstance(observation.get("position", {}), dict) else {}
    inventory = observation.get("inventory", {}) if isinstance(observation.get("inventory", {}), dict) else {}
    return {
        "position": {
            key: round(_safe_float(position.get(key), 0.0), 2)
            for key in ("x", "y", "z")
            if position.get(key) is not None
        },
        "health": _round_optional(_safe_float(observation.get("health"), 0.0)) if observation.get("health") is not None else None,
        "inventory": {
            _normalize_item(key): _safe_int(value, 0)
            for key, value in sorted(inventory.items())
            if _safe_int(value, 0) != 0
        },
    }


def _terminal_boundary(events: list[dict]) -> dict:
    for event in reversed(events):
        event_type = str(event.get("type") or "")
        data = event.get("data", {}) if isinstance(event.get("data", {}), dict) else {}
        if event_type == "goal_end":
            result = data.get("result", {}) if isinstance(data.get("result", {}), dict) else {}
            completed = result.get("completed") is True or result.get("success") is True
            return {
                "complete_boundary": True,
                "event_type": event_type,
                "completed": completed,
                "cycles": _safe_int(result.get("cycles"), 0),
            }
        if event_type in {"auto_goal_complete", "subgoal_complete"}:
            return {"complete_boundary": True, "event_type": event_type, "completed": True, "cycles": _safe_int(data.get("cycles"), 0)}
        if event_type in {"auto_goal_failed", "subgoal_failed"}:
            return {"complete_boundary": True, "event_type": event_type, "completed": False, "cycles": _safe_int(data.get("cycles"), 0)}
    return {"complete_boundary": False, "event_type": "", "completed": None, "cycles": 0}


def _next_observation_index(events: list[dict]) -> dict[int, int]:
    result = {}
    next_index = -1
    for index in range(len(events) - 1, -1, -1):
        result[index] = next_index
        if events[index].get("type") == "observation":
            next_index = index
    return result


def _load_case_files(paths: list[str]) -> tuple[list[dict], list[dict], list[str]]:
    records = []
    manifests = []
    errors = []
    for path in paths:
        try:
            with open(path, "rb") as handle:
                raw = handle.read()
            manifests.append(_manifest_for_bytes(path, raw))
            loaded = _decode_json_or_jsonl(raw.decode("utf-8-sig"))
            for item in loaded:
                if not isinstance(item, dict) or not isinstance(item.get("events"), list):
                    raise ValueError("critical transition case requires an events list")
                records.append(item)
        except Exception as exc:
            errors.append(f"{path}: {exc}")
    return records, manifests, errors


def _load_labels(paths: list[str]) -> tuple[list[dict], list[dict], list[str]]:
    labels = []
    manifests = []
    errors = []
    for path in paths:
        try:
            with open(path, "rb") as handle:
                raw = handle.read()
            manifests.append(_manifest_for_bytes(path, raw))
            for item in _decode_json_or_jsonl(raw.decode("utf-8-sig")):
                if not isinstance(item, dict):
                    raise ValueError("critical transition label must be an object")
                labels.append(item)
        except Exception as exc:
            errors.append(f"{path}: {exc}")
    return labels, manifests, errors


def _label_for(labels: list[dict], session_id: str, case_id: str, path: str) -> dict:
    path_name = os.path.basename(path) if path else ""
    for item in labels:
        if session_id and str(item.get("session_id") or "") == session_id:
            return item
        if case_id and str(item.get("case_id") or "") == case_id:
            return item
        if path_name and str(item.get("session_log") or item.get("path") or "") in {path, path_name}:
            return item
    return {}


def _decode_json_or_jsonl(text: str) -> list[Any]:
    try:
        payload = json.loads(text)
        if isinstance(payload, dict) and isinstance(payload.get("cases"), list):
            return payload["cases"]
        if isinstance(payload, dict) and isinstance(payload.get("labels"), list):
            return payload["labels"]
        return payload if isinstance(payload, list) else [payload]
    except json.JSONDecodeError:
        return [json.loads(line) for line in text.splitlines() if line.strip()]


def _read_jsonl_manifest(path: str) -> tuple[list[dict], dict]:
    with open(path, "rb") as handle:
        raw = handle.read()
    events = []
    for line_number, line in enumerate(raw.decode("utf-8-sig").splitlines(), start=1):
        if not line.strip():
            continue
        item = json.loads(line)
        if not isinstance(item, dict):
            raise ValueError(f"JSONL line {line_number} must be an object")
        events.append(item)
    return events, _manifest_for_bytes(path, raw)


def _manifest_for_bytes(path: str, raw: bytes) -> dict:
    return {
        "name": os.path.basename(str(path)),
        "path_fingerprint": _fingerprint(_normalized_path(path)),
        "content_sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
    }


def _manifest_valid(item: Any) -> bool:
    return bool(
        isinstance(item, dict)
        and str(item.get("name") or "")
        and len(str(item.get("path_fingerprint") or "")) == 16
        and len(str(item.get("content_sha256") or "")) == 64
        and _safe_int(item.get("bytes"), 0) > 0
    )


def _builtin_cases() -> list[dict]:
    return [
        _builtin_navigation_dependency_case(),
        _builtin_recovered_then_invalid_case(),
        _builtin_unsupported_action_case(),
        _builtin_world_effect_case(),
        _builtin_empty_plan_case(),
        _builtin_success_control_case(),
    ]


def _event(session: str, event_type: str, data: dict) -> dict:
    return {"session": session, "type": event_type, "data": data}


def _observation(position: tuple[float, float, float], inventory: Optional[dict] = None, blocks: Optional[list[dict]] = None) -> dict:
    return {
        "position": {"x": position[0], "y": position[1], "z": position[2]},
        "health": 20,
        "inventory": inventory or {},
        "nearby_blocks": blocks or [],
    }


def _goal_end(goal: str, completed: bool, cycles: int) -> dict:
    return {"goal": goal, "result": {"goal": goal, "completed": completed, "cycles": cycles}}


def _builtin_navigation_dependency_case() -> dict:
    session = "builtin-ct-nav"
    goal = "Gather 3 oak logs"
    move = {"type": "move_to", "parameters": {"x": 12, "z": 0}}
    dig = {"type": "dig", "parameters": {"x": 12, "y": 64, "z": 0}}
    events = [
        _event(session, "connect", {"success": False}),
        _event(session, "goal_start", {"goal": goal}),
        _event(session, "observation", _observation((0, 64, 0))),
        _event(session, "plan", {"status": "in_progress", "reasoning": "navigate then dig", "actions": [move, dig]}),
        _event(session, "action", {"action": move, "result": {"success": True, "position": {"x": 2, "y": 64, "z": 0}}}),
        _event(session, "action", {"action": dig, "result": {"success": True, "block": "oak_log"}}),
        _event(session, "observation", _observation((2, 64, 0))),
        _event(session, "goal_end", _goal_end(goal, False, 2)),
    ]
    return {
        "case_id": "builtin-navigation-dependent-dig",
        "events": events,
        "expected_label": {"critical_unit_ordinal": 1, "category": "tool_output_misinterpretation"},
    }


def _builtin_recovered_then_invalid_case() -> dict:
    session = "builtin-ct-recovered"
    goal = "Craft a stone pickaxe"
    move = {"type": "move_to", "parameters": {"x": 4, "z": 0}}
    invalid_craft = {"type": "craft", "parameters": {}}
    events = [
        _event(session, "connect", {"success": False}),
        _event(session, "goal_start", {"goal": goal}),
        _event(session, "observation", _observation((0, 64, 0))),
        _event(session, "plan", {"status": "in_progress", "reasoning": "move", "actions": [move]}),
        _event(session, "action", {"action": move, "result": {"success": False, "error": "path blocked"}}),
        _event(session, "observation", _observation((0, 64, 0))),
        _event(session, "plan", {"status": "in_progress", "reasoning": "retry route", "actions": [move]}),
        _event(session, "action", {"action": move, "result": {"success": True, "reached": True, "position": {"x": 4, "y": 64, "z": 0}}}),
        _event(session, "observation", _observation((4, 64, 0))),
        _event(session, "plan", {"status": "in_progress", "reasoning": "craft", "actions": [invalid_craft]}),
        _event(session, "action", {"action": invalid_craft, "result": {"success": False, "error": "item is required"}}),
        _event(session, "goal_end", _goal_end(goal, False, 3)),
    ]
    return {
        "case_id": "builtin-recovered-then-invalid",
        "events": events,
        "expected_label": {"critical_unit_ordinal": 3, "category": "invalid_invocation"},
    }


def _builtin_unsupported_action_case() -> dict:
    session = "builtin-ct-unsupported"
    goal = "Reach the village"
    action = {"type": "teleport", "parameters": {"x": 10, "z": 10}}
    events = [
        _event(session, "connect", {"success": False}),
        _event(session, "goal_start", {"goal": goal}),
        _event(session, "observation", _observation((0, 64, 0))),
        _event(session, "plan", {"status": "in_progress", "reasoning": "teleport", "actions": [action]}),
        _event(session, "action", {"action": action, "result": {"success": False, "error": "unknown command"}}),
        _event(session, "goal_end", _goal_end(goal, False, 1)),
    ]
    return {
        "case_id": "builtin-unsupported-action",
        "events": events,
        "expected_label": {"critical_unit_ordinal": 1, "category": "intent_not_supported"},
    }


def _builtin_world_effect_case() -> dict:
    session = "builtin-ct-effect"
    goal = "Mine one coal ore"
    action = {"type": "dig", "parameters": {"x": 1, "y": 64, "z": 0}}
    block = {"name": "coal_ore", "position": {"x": 1, "y": 64, "z": 0}}
    events = [
        _event(session, "connect", {"success": False}),
        _event(session, "goal_start", {"goal": goal}),
        _event(session, "observation", _observation((0, 64, 0), blocks=[block])),
        _event(session, "plan", {"status": "in_progress", "reasoning": "dig", "actions": [action]}),
        _event(session, "action", {"action": action, "result": {"success": True, "block": "coal_ore"}}),
        _event(session, "observation", _observation((0, 64, 0), blocks=[block])),
        _event(session, "goal_end", _goal_end(goal, False, 1)),
    ]
    return {
        "case_id": "builtin-world-effect-mismatch",
        "events": events,
        "expected_label": {"critical_unit_ordinal": 1, "category": "tool_output_misinterpretation"},
    }


def _builtin_success_control_case() -> dict:
    session = "builtin-ct-success"
    goal = "Move near the tree"
    action = {"type": "move_to", "parameters": {"x": 3, "z": 0}}
    events = [
        _event(session, "connect", {"success": False}),
        _event(session, "goal_start", {"goal": goal}),
        _event(session, "observation", _observation((0, 64, 0))),
        _event(session, "plan", {"status": "in_progress", "reasoning": "move", "actions": [action]}),
        _event(session, "action", {"action": action, "result": {"success": True, "reached": True, "position": {"x": 3, "y": 64, "z": 0}}}),
        _event(session, "observation", _observation((3, 64, 0))),
        _event(session, "goal_end", _goal_end(goal, True, 1)),
    ]
    return {"case_id": "builtin-success-control", "events": events, "expected_label": {}}


def _builtin_empty_plan_case() -> dict:
    session = "builtin-ct-empty-plan"
    goal = "Craft a wooden pickaxe"
    events = [
        _event(session, "connect", {"success": False}),
        _event(session, "goal_start", {"goal": goal}),
        _event(session, "observation", _observation((0, 64, 0))),
        _event(session, "plan", {"status": "blocked", "reasoning": "cannot continue", "actions": []}),
        _event(session, "observation", _observation((0, 64, 0))),
        _event(session, "plan", {"status": "blocked", "reasoning": "still blocked", "actions": []}),
        _event(session, "goal_end", _goal_end(goal, False, 2)),
    ]
    return {
        "case_id": "builtin-empty-plan",
        "events": events,
        "expected_label": {"critical_unit_ordinal": 1, "category": "intent_plan_misalignment"},
    }


def _explicit_session_id(events: list[dict]) -> str:
    sessions = {str(event.get("session") or "") for event in events if event.get("session")}
    return next(iter(sessions)) if len(sessions) == 1 else ""


def _connect_success(events: list[dict]) -> bool:
    return any(
        event.get("type") == "connect"
        and isinstance(event.get("data", {}), dict)
        and event["data"].get("success") is True
        for event in events
    )


def _error_signature(error: Any) -> str:
    text = " ".join(str(error or "").strip().lower().split())
    if not text:
        return ""
    normalized = "".join(char if char.isalpha() or char == "_" or char.isspace() else "#" for char in text)
    return _fingerprint(normalized)


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:16]


def _normalize_item(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_")[:96]


def _normalized_number(value: Any) -> str:
    number = _safe_float(value, 0.0)
    return str(int(number)) if number.is_integer() else f"{number:.3f}".rstrip("0").rstrip(".")


def _normalized_path(path: str) -> str:
    return os.path.normcase(os.path.abspath(str(path or "")))


def _round_optional(value: Optional[float]) -> Optional[float]:
    return round(value, 6) if value is not None and math.isfinite(value) else None


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return result if math.isfinite(result) else default


def _ratio(numerator: int | float, denominator: int | float) -> float:
    try:
        denominator = float(denominator)
        return round(float(numerator) / denominator, 6) if denominator > 0 else 0.0
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0
