"""Evidence-gated planner-round allocation across Minecraft task frontiers.

The allocator is an inference-time control layer, not an implementation of
IGRPO training.  It keeps an integer planner-round ledger, compares a uniform
baseline with a soft information-weighted policy, and exposes explicitly
uncertain remaining-round intervals.  Runtime use is shadow-only unless a
paired, held-out live report approves advisory planner context.  No gate in
this module can authorize retries, branch execution, or budget expansion.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from typing import Any, Optional


ALLOCATION_PROFILE = "frontier_information_budget_v1"
UNIFORM_PROFILE = "uniform_frontier_budget_v1"
INTERVAL_PROFILE = "frontier_budget_interval_v1"
GATE_TYPE = "frontier_rollout_budget_gate"
SCHEMA_VERSION = 1
ACTION_BACKEND_ID = "mineflayer-bridge-v1"
VERIFIER_ID = "goal-action-verifier-v1"
MAX_BRANCHES = 64
CONTROL_KEYS = (
    "planner_id",
    "action_backend",
    "verifier_id",
    "task_stream_id",
    "seed",
)


def frontier_branch_id(title: str, source: str = "frontier") -> str:
    """Return a stable, text-hiding identifier for one frontier branch."""
    normalized = " ".join(str(title or "").strip().lower().split())
    payload = f"{str(source or 'frontier').strip().lower()}|{normalized}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def runtime_frontier_budget_provenance(config) -> dict:
    """Return runtime controls that must match an advisory allocation gate."""
    llm = getattr(config, "llm", None)
    api_key_present = bool(
        str(getattr(llm, "api_key", "") or "").strip()
        or str(os.environ.get("OPENAI_API_KEY", "") or "").strip()
    )
    if llm is not None and api_key_present:
        provider = str(getattr(llm, "provider", "") or "openai").strip().lower()
        model = str(getattr(llm, "model", "") or "unknown").strip()
        planner_id = f"llm:{provider}:{model}"
    else:
        planner_id = "rule-based-v1"
    return {
        "planner_id": planner_id,
        "action_backend": ACTION_BACKEND_ID,
        "verifier_id": VERIFIER_ID,
        "task_stream_id": str(getattr(config, "frontier_budget_task_stream_id", "") or "").strip(),
        "seed": str(getattr(config, "frontier_budget_seed_id", "") or "").strip(),
        "policy": str(getattr(config, "frontier_budget_policy", "information") or "information").strip().lower(),
        "total_rounds": max(1, _safe_int(getattr(config, "frontier_budget_total_rounds", 8), 8)),
        "temperature": round(max(0.05, _safe_float(getattr(config, "frontier_budget_temperature", 2.0), 2.0)), 6),
        "exploration_floor": max(0, _safe_int(getattr(config, "frontier_budget_exploration_floor", 1), 1)),
        "action_verification_enforced": bool(
            getattr(config, "enable_action_verification", True)
            and getattr(config, "enforce_action_verification", True)
        ),
    }


def build_frontier_branches(
    curriculum_candidates: Optional[list[dict]] = None,
    task_readiness: Optional[dict] = None,
    observation: Optional[dict] = None,
    goal_stats: Optional[dict] = None,
    selected_goal: str = "",
) -> list[dict]:
    """Project curriculum and task-readiness state into typed budget branches."""
    observation = observation if isinstance(observation, dict) else {}
    inventory = observation.get("inventory", {}) if isinstance(observation.get("inventory", {}), dict) else {}
    goal_stats = goal_stats if isinstance(goal_stats, dict) else {}
    readiness_tasks = (
        task_readiness.get("tasks", [])
        if isinstance(task_readiness, dict) and isinstance(task_readiness.get("tasks", []), list)
        else []
    )
    missing_frontier_items = set()
    for task in readiness_tasks:
        if not isinstance(task, dict):
            continue
        missing_frontier_items.update(_inventory_requirement_names(task.get("missing_preconditions", {})))

    branches = []
    for candidate in curriculum_candidates or []:
        if not isinstance(candidate, dict):
            continue
        title = str(candidate.get("title") or "").strip()
        if not title:
            continue
        category = str(candidate.get("category") or "curriculum")[:64]
        targets = _string_list(candidate.get("target_items", []), limit=12)
        required = candidate.get("required_items", {}) if isinstance(candidate.get("required_items", {}), dict) else {}
        missing_required = {
            str(item): max(0, _safe_int(count, 1) - _safe_int(inventory.get(item), 0))
            for item, count in required.items()
            if _safe_int(inventory.get(item), 0) < _safe_int(count, 1)
        }
        reasons = _string_list(candidate.get("reasons", []), limit=16)
        tags = _string_list(candidate.get("tags", []), limit=16)
        stats = goal_stats.get(title, {}) if isinstance(goal_stats.get(title, {}), dict) else {}
        attempts = _safe_int(candidate.get("attempts", stats.get("attempts", 0)), 0)
        failures = _safe_int(candidate.get("failures", stats.get("failures", 0)), 0)
        closes = len(set(_normalize_item(item) for item in targets) & missing_frontier_items)
        novelty = sum(1 for reason in reasons if "novel" in reason)
        frontier_gap = sum(
            1
            for reason in reasons
            if any(token in reason for token in ("frontier", "coverage_gap", "perception_failure", "skill_gap"))
        )
        risk = sum(1 for reason in reasons if "danger" in reason or "risk" in reason)
        emergency = bool(candidate.get("safety_reserved")) or (
            category in {"emergency", "combat"}
            or ("rule_generator" in reasons and _safe_float(candidate.get("score"), 0.0) >= 75.0)
        )
        explicit_signals = candidate.get("signals", {}) if isinstance(candidate.get("signals", {}), dict) else {}
        signals = {
            "closes_precondition_count": closes,
            "verifier_reject_count": _safe_int(candidate.get("verifier_reject_count"), 0),
            "no_progress_count": _safe_int(candidate.get("no_progress_count"), 0),
            "novelty_count": novelty,
            "frontier_gap_count": frontier_gap,
            "risk_count": risk,
            "attempt_count": attempts,
            "failure_count": failures,
            "missing_dependency_count": 0,
            "missing_precondition_count": len(missing_required),
        }
        for key, value in explicit_signals.items():
            if key in signals:
                signals[key] = max(0, min(1000, _safe_int(value, signals[key])))
        branches.append({
            "branch_id": str(candidate.get("branch_id") or frontier_branch_id(title, "curriculum")),
            "title": title[:180],
            "source": "curriculum",
            "category": category,
            "ready": not missing_required,
            "eligible": bool(candidate.get("eligible", not missing_required and not emergency)),
            "safety_reserved": emergency,
            "selected": _same_goal(title, selected_goal),
            "priority_value": _safe_float(candidate.get("score"), 0.0),
            "priority_direction": "higher",
            "signals": signals,
            "estimated_rounds_low": candidate.get("estimated_rounds_low"),
            "estimated_rounds_high": candidate.get("estimated_rounds_high"),
        })

    for task in readiness_tasks:
        if not isinstance(task, dict):
            continue
        title = str(task.get("title") or "").strip()
        if not title:
            continue
        missing_dependencies = task.get("missing_dependencies", [])
        missing_dependencies = missing_dependencies if isinstance(missing_dependencies, list) else []
        missing_preconditions = _inventory_requirement_names(task.get("missing_preconditions", {}))
        target_items = _inventory_requirement_names(task.get("success_criteria", {}))
        closes = len(target_items & missing_frontier_items)
        tags = _string_list(task.get("tags", []), limit=16)
        task_type = str(task.get("type") or "task")[:64]
        safety_reserved = bool(task.get("safety_reserved")) or (
            task_type in {"combat", "emergency"} and _safe_int(task.get("priority"), 1) <= 0
        )
        ready = bool(task.get("ready"))
        explicit_signals = task.get("signals", {}) if isinstance(task.get("signals", {}), dict) else {}
        signals = {
            "closes_precondition_count": closes,
            "verifier_reject_count": _safe_int(task.get("verifier_reject_count"), 0),
            "no_progress_count": _safe_int(task.get("no_progress_count"), 0),
            "novelty_count": sum(1 for tag in tags if "novel" in tag or "explor" in tag),
            "frontier_gap_count": sum(1 for tag in tags if "frontier" in tag or "readiness_recovery" in tag),
            "risk_count": sum(1 for tag in tags if "danger" in tag or "risk" in tag),
            "attempt_count": _safe_int(task.get("attempts"), 0),
            "failure_count": _safe_int(task.get("failure_count"), 0),
            "missing_dependency_count": len(missing_dependencies),
            "missing_precondition_count": len(missing_preconditions),
        }
        for key, value in explicit_signals.items():
            if key in signals:
                signals[key] = max(0, min(1000, _safe_int(value, signals[key])))
        branches.append({
            "branch_id": str(task.get("branch_id") or task.get("id") or frontier_branch_id(title, "task"))[:64],
            "title": title[:180],
            "source": "task_readiness",
            "category": task_type,
            "ready": ready,
            "eligible": bool(task.get("eligible", ready and not safety_reserved)),
            "safety_reserved": safety_reserved,
            "selected": _same_goal(title, selected_goal),
            "priority_value": _safe_float(task.get("score"), _safe_float(task.get("priority"), 0.0)),
            "priority_direction": "lower",
            "signals": signals,
            "estimated_rounds_low": task.get("estimated_rounds_low"),
            "estimated_rounds_high": task.get("estimated_rounds_high"),
        })

    branches = _deduplicate_branches(branches)
    if selected_goal and not any(branch.get("selected") for branch in branches):
        branches.append({
            "branch_id": frontier_branch_id(selected_goal, "selected_goal"),
            "title": str(selected_goal)[:180],
            "source": "selected_goal",
            "category": "runtime_goal",
            "ready": True,
            "eligible": True,
            "safety_reserved": False,
            "selected": True,
            "priority_value": 1.0,
            "priority_direction": "higher",
            "signals": _normalized_signals({"frontier_gap_count": 1}),
        })
    _assign_priority_signals(branches)
    return branches[:MAX_BRANCHES]


def score_frontier_branch(branch: dict) -> dict:
    """Score one branch using typed uncertainty, progress, and risk signals."""
    signals = _normalized_signals(branch.get("signals", {}))
    eligible = bool(branch.get("eligible")) and not bool(branch.get("safety_reserved"))
    ready = bool(branch.get("ready"))
    attempts = signals["attempt_count"]
    failures = signals["failure_count"]
    diagnostic_count = min(3, signals["verifier_reject_count"] + signals["no_progress_count"])
    components = {
        "base": 1.0,
        "priority": 2.0 * _clamp(_safe_float(branch.get("priority_signal"), 0.5), 0.0, 1.0),
        "ready": 1.5 if ready else 0.0,
        "precondition_closure": min(12.0, 4.0 * signals["closes_precondition_count"]),
        "diagnostic_uncertainty": min(6.0, 2.0 * diagnostic_count),
        "frontier_information": min(7.5, 2.5 * signals["frontier_gap_count"]),
        "novelty": min(4.0, 2.0 * signals["novelty_count"]),
        "risk_penalty": -min(12.0, 3.0 * signals["risk_count"]),
        "repeat_penalty": -min(10.0, 1.25 * max(0, attempts - 1) + 1.5 * max(0, failures - 1)),
        "blocked_penalty": -8.0 if not ready and not signals["closes_precondition_count"] else 0.0,
    }
    raw = sum(components.values()) if eligible else 0.0
    score = max(0.001, raw) if eligible else 0.0
    low, high = _branch_round_interval(branch, signals, eligible)
    return {
        "score": round(score, 6),
        "components": {key: round(value, 6) for key, value in components.items()},
        "signals": signals,
        "estimated_rounds_low": low,
        "estimated_rounds_high": high,
        "interval_calibrated": False,
        "interval_profile": INTERVAL_PROFILE,
    }


def allocate_frontier_budget(
    branches: list[dict],
    total_rounds: int,
    consumed_rounds: int = 0,
    recovered_rounds: int = 0,
    policy: str = "information",
    temperature: float = 2.0,
    exploration_floor: int = 1,
) -> dict:
    """Allocate an integer round pool without extending the fixed total ledger."""
    total_rounds = max(0, _safe_int(total_rounds, 0))
    consumed_rounds = max(0, min(total_rounds, _safe_int(consumed_rounds, 0)))
    recovered_rounds = max(0, _safe_int(recovered_rounds, 0))
    available_rounds = max(0, total_rounds - consumed_rounds)
    allocation_pool = min(available_rounds, recovered_rounds) if recovered_rounds > 0 else available_rounds
    temperature = max(0.05, _safe_float(temperature, 2.0))
    exploration_floor = max(0, _safe_int(exploration_floor, 1))
    policy = str(policy or "information").strip().lower()
    if policy not in {"uniform", "information"}:
        raise ValueError("frontier budget policy must be uniform or information")

    normalized = _normalize_allocator_branches(branches)
    scored = []
    for branch in normalized:
        score = score_frontier_branch(branch)
        item = {**branch, **score, "allocated_rounds": 0, "allocation_share": 0.0}
        scored.append(item)
    eligible = [item for item in scored if item.get("eligible") and not item.get("safety_reserved")]
    allocations = {item["branch_id"]: 0 for item in eligible}
    if eligible and allocation_pool > 0:
        floor = exploration_floor if allocation_pool >= exploration_floor * len(eligible) else 0
        if floor:
            for item in eligible:
                allocations[item["branch_id"]] += floor
        remaining = allocation_pool - floor * len(eligible)
        if remaining > 0:
            if policy == "uniform":
                weights = {item["branch_id"]: 1.0 for item in eligible}
            else:
                maximum = max(item["score"] for item in eligible)
                weights = {
                    item["branch_id"]: math.exp(max(-40.0, min(0.0, (item["score"] - maximum) / temperature)))
                    for item in eligible
                }
            _allocate_largest_remainder(allocations, eligible, weights, remaining, policy)

    for item in scored:
        amount = allocations.get(item["branch_id"], 0)
        item["allocated_rounds"] = amount
        item["allocation_share"] = round(amount / allocation_pool, 6) if allocation_pool else 0.0
    scored.sort(key=lambda item: (-item["allocated_rounds"], -item["score"], item["branch_id"]))
    allocated_rounds = sum(item["allocated_rounds"] for item in scored)
    unallocated_rounds = max(0, allocation_pool - allocated_rounds)
    feasible = [
        item for item in eligible
        if item.get("estimated_rounds_low") is not None
        and _safe_int(item.get("estimated_rounds_low"), allocation_pool + 1) <= allocation_pool
    ]
    uncertain = [
        item for item in feasible
        if item.get("estimated_rounds_high") is not None
        and _safe_int(item.get("estimated_rounds_high"), 0) > allocation_pool
    ]
    if not eligible:
        alert = "no_eligible_frontier_branch"
    elif not feasible:
        alert = "no_branch_fits_remaining_round_budget"
    elif len(uncertain) == len(feasible):
        alert = "remaining_round_interval_overflow"
    else:
        alert = ""
    return {
        "type": "frontier_rollout_budget_allocation",
        "schema_version": SCHEMA_VERSION,
        "allocation_profile": ALLOCATION_PROFILE if policy == "information" else UNIFORM_PROFILE,
        "interval_profile": INTERVAL_PROFILE,
        "policy": policy,
        "temperature": round(temperature, 6),
        "exploration_floor": exploration_floor,
        "ledger": {
            "total_rounds": total_rounds,
            "consumed_rounds": consumed_rounds,
            "available_rounds": available_rounds,
            "declared_recovered_rounds": recovered_rounds,
            "allocation_pool_rounds": allocation_pool,
            "allocated_rounds": allocated_rounds,
            "unallocated_rounds": unallocated_rounds,
            "budget_extended": False,
            "conservation_valid": allocated_rounds + unallocated_rounds == allocation_pool
            and allocation_pool <= available_rounds,
        },
        "eligible_branch_count": len(eligible),
        "safety_reserved_branch_count": sum(1 for item in scored if item.get("safety_reserved")),
        "feasible_branch_count": len(feasible),
        "uncertain_branch_count": len(uncertain),
        "budget_alert": alert,
        "interval_calibrated": False,
        "automatic_retry_allowed": False,
        "automatic_branch_execution_allowed": False,
        "branches": scored,
    }


def compare_frontier_allocations(
    branches: list[dict],
    total_rounds: int,
    consumed_rounds: int = 0,
    recovered_rounds: int = 0,
    temperature: float = 2.0,
    exploration_floor: int = 1,
) -> dict:
    """Return a fixed-control uniform versus information allocation comparison."""
    uniform = allocate_frontier_budget(
        branches,
        total_rounds,
        consumed_rounds=consumed_rounds,
        recovered_rounds=recovered_rounds,
        policy="uniform",
        temperature=temperature,
        exploration_floor=exploration_floor,
    )
    information = allocate_frontier_budget(
        branches,
        total_rounds,
        consumed_rounds=consumed_rounds,
        recovered_rounds=recovered_rounds,
        policy="information",
        temperature=temperature,
        exploration_floor=exploration_floor,
    )
    uniform_map = {item["branch_id"]: item["allocated_rounds"] for item in uniform["branches"]}
    information_map = {item["branch_id"]: item["allocated_rounds"] for item in information["branches"]}
    branch_ids = sorted(set(uniform_map) | set(information_map))
    deltas = [
        {
            "branch_id": branch_id,
            "uniform_rounds": uniform_map.get(branch_id, 0),
            "information_rounds": information_map.get(branch_id, 0),
            "delta": information_map.get(branch_id, 0) - uniform_map.get(branch_id, 0),
        }
        for branch_id in branch_ids
    ]
    return {
        "type": "frontier_rollout_budget_comparison",
        "schema_version": SCHEMA_VERSION,
        "fixed_total_rounds": max(0, _safe_int(total_rounds, 0)),
        "uniform": uniform,
        "information": information,
        "branch_deltas": deltas,
        "changed_branch_count": sum(1 for item in deltas if item["delta"] != 0),
        "allocation_l1_distance": sum(abs(item["delta"]) for item in deltas),
        "both_budgets_conserved": bool(
            uniform["ledger"]["conservation_valid"]
            and information["ledger"]["conservation_valid"]
            and uniform["ledger"]["allocation_pool_rounds"]
            == information["ledger"]["allocation_pool_rounds"]
        ),
    }


class FrontierBudgetController:
    """Runtime wrapper for shadow tracing or gate-approved planner advice."""

    def __init__(
        self,
        runtime_gate_report: Optional[dict] = None,
        policy: str = "information",
        total_rounds: int = 8,
        temperature: float = 2.0,
        exploration_floor: int = 1,
    ):
        report = runtime_gate_report if isinstance(runtime_gate_report, dict) else {}
        self.runtime_mode = str(report.get("effective_mode") or "off")
        self.policy = str(policy or "information").strip().lower()
        if self.policy not in {"uniform", "information"}:
            self.policy = "information"
        self.total_rounds = max(1, _safe_int(total_rounds, 8))
        self.temperature = max(0.05, _safe_float(temperature, 2.0))
        self.exploration_floor = max(0, _safe_int(exploration_floor, 1))

    @property
    def enabled(self) -> bool:
        return self.runtime_mode in {"shadow", "advisory"}

    @property
    def advisory(self) -> bool:
        return self.runtime_mode == "advisory"

    def allocate(
        self,
        branches: list[dict],
        recovered_rounds: int = 0,
        consumed_rounds: int = 0,
    ) -> dict:
        if not self.enabled:
            return {}
        allocation = allocate_frontier_budget(
            branches,
            self.total_rounds,
            consumed_rounds=consumed_rounds,
            recovered_rounds=recovered_rounds,
            policy=self.policy,
            temperature=self.temperature,
            exploration_floor=self.exploration_floor,
        )
        allocation["runtime_mode"] = self.runtime_mode
        return allocation


def build_frontier_rollout_budget_gate(
    case_paths: Optional[list[str]] = None,
    baseline_log_paths: Optional[list[str]] = None,
    candidate_log_paths: Optional[list[str]] = None,
    include_builtins: bool = False,
    episode_abort_gate_paths: Optional[list[str]] = None,
    evidence_kind: str = "unknown",
    total_rounds: int = 8,
    temperature: float = 2.0,
    exploration_floor: int = 1,
    planner_id: str = "",
    action_backend: str = "",
    verifier_id: str = "",
    task_stream_id: str = "",
    seed: str = "",
    min_live_pairs: int = 3,
    min_interval_observations: int = 12,
    target_interval_coverage: float = 0.75,
    confidence_alpha: float = 0.05,
    max_optimistic_miss_rate: float = 0.10,
    max_completion_regression: float = 0.0,
    max_verifier_reject_regression: float = 0.0,
    max_action_failure_regression: float = 0.0,
) -> dict:
    """Build a paired uniform-versus-information runtime advisory gate."""
    from singularity.core.episode_abort import clopper_pearson_lower_bound

    total_rounds = max(1, _safe_int(total_rounds, 8))
    temperature = max(0.05, _safe_float(temperature, 2.0))
    exploration_floor = max(0, _safe_int(exploration_floor, 1))
    evidence_kind = str(evidence_kind or "unknown").strip().lower()
    provenance = {
        "planner_id": str(planner_id or "").strip(),
        "action_backend": str(action_backend or "").strip(),
        "verifier_id": str(verifier_id or "").strip(),
        "task_stream_id": str(task_stream_id or "").strip(),
        "seed": str(seed or "").strip(),
    }
    thresholds = {
        "min_live_pairs": max(1, _safe_int(min_live_pairs, 3)),
        "min_interval_observations": max(1, _safe_int(min_interval_observations, 12)),
        "target_interval_coverage": _clamp(_safe_float(target_interval_coverage, 0.75), 0.5, 0.999999),
        "confidence_alpha": _clamp(_safe_float(confidence_alpha, 0.05), 0.000001, 0.499999),
        "max_optimistic_miss_rate": _clamp(_safe_float(max_optimistic_miss_rate, 0.10), 0.0, 1.0),
        "max_completion_regression": max(0.0, _safe_float(max_completion_regression, 0.0)),
        "max_verifier_reject_regression": max(0.0, _safe_float(max_verifier_reject_regression, 0.0)),
        "max_action_failure_regression": max(0.0, _safe_float(max_action_failure_regression, 0.0)),
    }
    report = {
        "type": GATE_TYPE,
        "schema_version": SCHEMA_VERSION,
        "allocation_profile": ALLOCATION_PROFILE,
        "uniform_profile": UNIFORM_PROFILE,
        "interval_profile": INTERVAL_PROFILE,
        "readiness": "review",
        "decision": "hold_frontier_budget_advisory",
        "reason": "frontier budget evidence is incomplete",
        "evidence_kind": evidence_kind,
        "runtime_eligible": False,
        "shadow_allocation_allowed": False,
        "advisory_context_allowed": False,
        "automatic_retry_allowed": False,
        "automatic_branch_execution_allowed": False,
        "budget_extension_allowed": False,
        "allocation_config": {
            "policy": "information",
            "total_rounds": total_rounds,
            "temperature": round(temperature, 6),
            "exploration_floor": exploration_floor,
        },
        "provenance": provenance,
        "thresholds": thresholds,
        "pair_count": 0,
        "pair_evaluations": [],
        "baseline": {},
        "candidate": {},
        "deltas": {},
        "allocation_metrics": {},
        "interval_metrics": {},
        "evidence_integrity": {},
        "episode_abort_link": {},
        "source_manifests": [],
        "checks": [],
        "missing": [],
        "errors": [],
    }
    if evidence_kind not in {"unknown", "synthetic_control", "live_trace"}:
        report["errors"].append("evidence_kind must be unknown, synthetic_control, or live_trace")

    case_paths = list(case_paths or [])
    baseline_log_paths = list(baseline_log_paths or [])
    candidate_log_paths = list(candidate_log_paths or [])
    all_paths = case_paths + baseline_log_paths + candidate_log_paths
    normalized_paths = [_normalized_path(path) for path in all_paths]
    input_paths_unique = len(normalized_paths) == len(set(normalized_paths))
    pairs, manifests, load_errors = _load_frontier_budget_cases(case_paths)
    report["source_manifests"].extend(manifests)
    report["errors"].extend(load_errors)
    log_pairs, log_manifests, log_errors = _pairs_from_session_logs(
        baseline_log_paths,
        candidate_log_paths,
    )
    pairs.extend(log_pairs)
    report["source_manifests"].extend(log_manifests)
    report["errors"].extend(log_errors)
    if include_builtins:
        pairs.extend(_builtin_frontier_budget_pairs())
    if not pairs:
        report["missing"].append("paired_frontier_budget_cases")

    abort_link, abort_errors = _load_episode_abort_link(episode_abort_gate_paths or [], provenance)
    report["episode_abort_link"] = abort_link
    report["errors"].extend(abort_errors)

    pair_ids = set()
    sessions = []
    pair_evaluations = []
    for index, pair in enumerate(pairs, start=1):
        try:
            evaluation = _evaluate_frontier_budget_pair(
                pair,
                total_rounds=total_rounds,
                temperature=temperature,
                exploration_floor=exploration_floor,
                expected_provenance=provenance,
                episode_abort_link=abort_link,
                index=index,
            )
            if evaluation["pair_id"] in pair_ids:
                raise ValueError(f"duplicate pair id: {evaluation['pair_id']}")
            pair_ids.add(evaluation["pair_id"])
            pair_evaluations.append(evaluation)
            sessions.extend([evaluation["baseline_session_id"], evaluation["candidate_session_id"]])
        except Exception as exc:
            report["errors"].append(f"pair {index}: {exc}")
    report["pair_evaluations"] = pair_evaluations
    report["pair_count"] = len(pair_evaluations)

    baseline = _aggregate_pair_outcomes(pair_evaluations, "baseline")
    candidate = _aggregate_pair_outcomes(pair_evaluations, "candidate")
    deltas = {
        "completion_rate": round(candidate["completion_rate"] - baseline["completion_rate"], 6),
        "verifier_reject_rate": round(candidate["verifier_reject_rate"] - baseline["verifier_reject_rate"], 6),
        "action_failure_rate": round(candidate["action_failure_rate"] - baseline["action_failure_rate"], 6),
        "prerequisite_resolution_rate": round(
            candidate["prerequisite_resolution_rate"] - baseline["prerequisite_resolution_rate"], 6
        ),
        "completion_per_planner_round": round(
            candidate["completion_per_planner_round"] - baseline["completion_per_planner_round"], 6
        ),
    }
    report["baseline"] = baseline
    report["candidate"] = candidate
    report["deltas"] = deltas
    changed_pairs = sum(1 for item in pair_evaluations if item["changed_branch_count"] > 0)
    conservation_count = sum(1 for item in pair_evaluations if item["budget_conservation_valid"])
    targeted_gains = [item["candidate_resolution_targeting_gain"] for item in pair_evaluations]
    recovered_pairs = [item for item in pair_evaluations if item["recovered_rounds"] > 0]
    certified_recovered_pairs = [item for item in recovered_pairs if item["certified_reallocation"]]
    report["allocation_metrics"] = {
        "changed_pair_count": changed_pairs,
        "budget_conservation_pair_count": conservation_count,
        "all_pairs_budget_conserved": conservation_count == len(pair_evaluations) and bool(pair_evaluations),
        "mean_candidate_resolution_targeting_gain": round(_mean(targeted_gains), 6),
        "positive_targeting_pair_count": sum(1 for value in targeted_gains if value > 0),
        "recovered_budget_pair_count": len(recovered_pairs),
        "certified_recovered_budget_pair_count": len(certified_recovered_pairs),
        "all_recovered_budget_certified": len(certified_recovered_pairs) == len(recovered_pairs),
    }
    interval_observations = sum(item["interval_observation_count"] for item in pair_evaluations)
    interval_covered = sum(item["interval_covered_count"] for item in pair_evaluations)
    optimistic_misses = sum(item["optimistic_interval_miss_count"] for item in pair_evaluations)
    coverage_rate = _ratio(interval_covered, interval_observations)
    coverage_lower = clopper_pearson_lower_bound(
        interval_covered,
        interval_observations,
        thresholds["confidence_alpha"],
    ) if interval_observations else 0.0
    report["interval_metrics"] = {
        "observation_count": interval_observations,
        "covered_count": interval_covered,
        "coverage_rate": coverage_rate,
        "coverage_lower_bound": round(coverage_lower, 6),
        "optimistic_miss_count": optimistic_misses,
        "optimistic_miss_rate": _ratio(optimistic_misses, interval_observations),
        "confidence_alpha": thresholds["confidence_alpha"],
        "calibrated_on_held_out_pairs": False,
    }

    explicit_sessions = all(bool(session) for session in sessions)
    sessions_distinct = explicit_sessions and len(sessions) == len(set(sessions))
    controls_fixed = all(item["provenance_match"] for item in pair_evaluations)
    policy_replay_valid = all(item.get("policy_replay_valid") is True for item in pair_evaluations)
    live_boundaries = all(item["live_boundary_complete"] for item in pair_evaluations)
    session_log_evidence_only = bool(pair_evaluations) and all(
        item.get("source_kind") == "session_logs" for item in pair_evaluations
    )
    source_manifests_valid = bool(report["source_manifests"]) and all(_manifest_valid(item) for item in report["source_manifests"])
    report["evidence_integrity"] = {
        "input_paths_unique": input_paths_unique,
        "pair_ids_unique": len(pair_ids) == len(pair_evaluations),
        "explicit_session_ids": explicit_sessions,
        "sessions_distinct": sessions_distinct,
        "fixed_controls": controls_fixed,
        "policy_replay_valid": policy_replay_valid,
        "live_boundaries_complete": live_boundaries,
        "session_log_evidence_only": session_log_evidence_only,
        "source_manifests_valid": source_manifests_valid,
        "builtin_case_count": len(_builtin_frontier_budget_pairs()) if include_builtins else 0,
    }
    provenance_complete = all(provenance.values())
    report["runtime_eligible"] = bool(
        evidence_kind == "live_trace"
        and not include_builtins
        and pair_evaluations
        and input_paths_unique
        and sessions_distinct
        and controls_fixed
        and policy_replay_valid
        and live_boundaries
        and session_log_evidence_only
        and source_manifests_valid
        and provenance_complete
    )
    if evidence_kind != "live_trace":
        report["missing"].append("live_trace_evidence")
    if not provenance_complete:
        report["missing"].append("fixed_runtime_provenance")
    if not sessions_distinct:
        report["missing"].append("distinct_paired_sessions")
    if not live_boundaries:
        report["missing"].append("complete_connected_live_boundaries")
    if not session_log_evidence_only:
        report["missing"].append("paired_session_log_evidence")
    if not policy_replay_valid:
        report["missing"].append("exact_policy_replay")
    if not input_paths_unique:
        report["missing"].append("unique_input_paths")
    if not source_manifests_valid:
        report["missing"].append("complete_source_manifests")

    checks = []
    _add_gate_check(checks, "pair_count", len(pair_evaluations) >= thresholds["min_live_pairs"], f"pairs={len(pair_evaluations)} required={thresholds['min_live_pairs']}")
    _add_gate_check(checks, "allocation_changes_uniform_baseline", changed_pairs > 0, f"changed_pairs={changed_pairs}")
    _add_gate_check(checks, "fixed_budget_conservation", conservation_count == len(pair_evaluations) and bool(pair_evaluations), f"conserved={conservation_count}/{len(pair_evaluations)}")
    _add_gate_check(checks, "recorded_allocations_match_policy_replay", policy_replay_valid and bool(pair_evaluations), f"matched={sum(1 for item in pair_evaluations if item.get('policy_replay_valid'))}/{len(pair_evaluations)}")
    _add_gate_check(checks, "completion_not_regressed", deltas["completion_rate"] >= -thresholds["max_completion_regression"], f"delta={deltas['completion_rate']}")
    _add_gate_check(checks, "verifier_reject_rate_not_regressed", deltas["verifier_reject_rate"] <= thresholds["max_verifier_reject_regression"], f"delta={deltas['verifier_reject_rate']}")
    _add_gate_check(checks, "action_failure_rate_not_regressed", deltas["action_failure_rate"] <= thresholds["max_action_failure_regression"], f"delta={deltas['action_failure_rate']}")
    _add_gate_check(checks, "prerequisite_resolution_not_regressed", deltas["prerequisite_resolution_rate"] >= 0.0, f"delta={deltas['prerequisite_resolution_rate']}")
    _add_gate_check(checks, "resolved_branches_receive_more_budget", report["allocation_metrics"]["mean_candidate_resolution_targeting_gain"] > 0.0, f"mean_gain={report['allocation_metrics']['mean_candidate_resolution_targeting_gain']}")
    _add_gate_check(checks, "no_unsafe_candidate_actions", candidate["unsafe_action_count"] == 0, f"unsafe_actions={candidate['unsafe_action_count']}")
    _add_gate_check(checks, "candidate_action_verification_enforced", candidate["all_outcomes_action_verification_enforced"], f"enforced={candidate['action_verification_enforced_count']}/{candidate['pair_outcome_count']}")
    _add_gate_check(checks, "interval_observations", interval_observations >= thresholds["min_interval_observations"], f"observations={interval_observations} required={thresholds['min_interval_observations']}")
    _add_gate_check(checks, "interval_coverage_certificate", coverage_lower >= thresholds["target_interval_coverage"], f"lower_bound={round(coverage_lower, 6)} target={thresholds['target_interval_coverage']}")
    _add_gate_check(checks, "optimistic_interval_miss_rate", report["interval_metrics"]["optimistic_miss_rate"] <= thresholds["max_optimistic_miss_rate"], f"rate={report['interval_metrics']['optimistic_miss_rate']} max={thresholds['max_optimistic_miss_rate']}")
    _add_gate_check(checks, "recovered_budget_is_certified", report["allocation_metrics"]["all_recovered_budget_certified"], f"certified={len(certified_recovered_pairs)}/{len(recovered_pairs)}")
    report["checks"] = checks

    hard_pass = all(check["status"] == "pass" for check in checks)
    report["shadow_allocation_allowed"] = bool(pair_evaluations and not report["errors"] and conservation_count == len(pair_evaluations))
    advisory_allowed = bool(report["runtime_eligible"] and hard_pass and not report["errors"])
    report["advisory_context_allowed"] = advisory_allowed
    report["interval_metrics"]["calibrated_on_held_out_pairs"] = advisory_allowed
    if report["errors"]:
        report["readiness"] = "error"
        report["decision"] = "reject_frontier_budget_gate"
        report["reason"] = "frontier budget evidence could not be evaluated"
    elif advisory_allowed:
        report["readiness"] = "approved"
        report["decision"] = "allow_frontier_budget_advisory_context"
        report["reason"] = "paired live evidence conserves budget, calibrates intervals, and shows no configured regressions"
    elif any(check["status"] == "fail" for check in checks) and evidence_kind == "live_trace":
        report["readiness"] = "rejected"
        report["decision"] = "reject_frontier_budget_advisory_context"
        report["reason"] = "paired live frontier allocation evidence fails one or more promotion checks"
    elif report["shadow_allocation_allowed"]:
        report["readiness"] = "review"
        report["decision"] = "allow_shadow_frontier_budget_trace"
        report["reason"] = "allocation mechanics are replayable but planner-facing use is not live-evidence-qualified"
    report["missing"] = sorted(set(report["missing"]))
    if report["shadow_allocation_allowed"] or report["advisory_context_allowed"]:
        report["gate_integrity_sha256"] = frontier_budget_gate_integrity_hash(report)
    return report


def evaluate_frontier_budget_runtime_gate(
    paths: list[str],
    requested_mode: str = "off",
    runtime_provenance: Optional[dict] = None,
) -> dict:
    """Resolve saved evidence into off, shadow, or advisory runtime behavior."""
    requested_mode = str(requested_mode or "off").strip().lower()
    if requested_mode not in {"off", "shadow", "advisory"}:
        requested_mode = "off"
    runtime_provenance = dict(runtime_provenance or {})
    report = {
        "type": "frontier_rollout_budget_runtime_gate",
        "requested_mode": requested_mode,
        "effective_mode": "off",
        "gate_paths": list(paths or []),
        "gate_readiness": "not_required" if requested_mode in {"off", "shadow"} else "missing",
        "allocation_profile": ALLOCATION_PROFILE,
        "provenance_match": False,
        "shadow_allocation_allowed": requested_mode == "shadow" and not paths,
        "advisory_context_allowed": False,
        "automatic_retry_allowed": False,
        "automatic_branch_execution_allowed": False,
        "errors": [],
    }
    if requested_mode == "off":
        return report
    if requested_mode == "shadow" and not paths:
        report["effective_mode"] = "shadow"
        return report
    if len(paths or []) != 1:
        report["gate_readiness"] = "error" if paths else "missing"
        if paths:
            report["errors"].append("exactly one frontier budget gate is required")
        return report
    path = paths[0]
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            gate = json.load(handle)
        validate_frontier_budget_gate_payload(gate)
    except Exception as exc:
        report["gate_readiness"] = "error"
        report["errors"].append(f"{path}: {exc}")
        return report

    expected = gate.get("provenance", {}) if isinstance(gate.get("provenance", {}), dict) else {}
    expected_config = gate.get("allocation_config", {}) if isinstance(gate.get("allocation_config", {}), dict) else {}
    compared = {
        **{key: str(expected.get(key) or "").strip() for key in CONTROL_KEYS},
        "policy": str(expected_config.get("policy") or ""),
        "total_rounds": _safe_int(expected_config.get("total_rounds"), 0),
        "temperature": round(_safe_float(expected_config.get("temperature"), 0.0), 6),
        "exploration_floor": _safe_int(expected_config.get("exploration_floor"), -1),
        "action_verification_enforced": True,
    }
    actual = {
        **{key: str(runtime_provenance.get(key) or "").strip() for key in CONTROL_KEYS},
        "policy": str(runtime_provenance.get("policy") or ""),
        "total_rounds": _safe_int(runtime_provenance.get("total_rounds"), 0),
        "temperature": round(_safe_float(runtime_provenance.get("temperature"), 0.0), 6),
        "exploration_floor": _safe_int(runtime_provenance.get("exploration_floor"), -1),
        "action_verification_enforced": runtime_provenance.get("action_verification_enforced") is True,
    }
    provenance_match = bool(
        all(compared[key] and compared[key] == actual[key] for key in CONTROL_KEYS)
        and compared["total_rounds"] > 0
        and compared["total_rounds"] == actual["total_rounds"]
        and compared["temperature"] > 0.0
        and compared["temperature"] == actual["temperature"]
        and compared["exploration_floor"] >= 0
        and compared["exploration_floor"] == actual["exploration_floor"]
        and compared["policy"] == "information"
        and compared["policy"] == actual["policy"]
        and actual["action_verification_enforced"] is True
    )
    report.update({
        "gate_readiness": str(gate.get("readiness") or "unknown").lower(),
        "provenance_match": provenance_match,
        "expected_provenance": compared,
        "runtime_provenance": actual,
        "shadow_allocation_allowed": bool(gate.get("shadow_allocation_allowed")),
        "advisory_context_allowed": bool(gate.get("advisory_context_allowed")),
        "gate_integrity_sha256": str(gate.get("gate_integrity_sha256") or ""),
    })
    if not provenance_match:
        report["gate_readiness"] = "rejected"
        report["errors"].append("runtime provenance or allocation controls do not match the saved gate")
        return report
    if requested_mode == "shadow" and gate.get("shadow_allocation_allowed") is True:
        report["effective_mode"] = "shadow"
    elif (
        requested_mode == "advisory"
        and gate.get("readiness") == "approved"
        and gate.get("advisory_context_allowed") is True
    ):
        report["effective_mode"] = "advisory"
    return report


def frontier_budget_trace_payload(allocation: dict, provenance: Optional[dict] = None) -> dict:
    """Return a replayable allocation event without free-form branch text."""
    if not isinstance(allocation, dict):
        return {}
    payload = {
        key: allocation.get(key)
        for key in (
            "type",
            "schema_version",
            "allocation_profile",
            "interval_profile",
            "policy",
            "temperature",
            "exploration_floor",
            "runtime_mode",
            "eligible_branch_count",
            "safety_reserved_branch_count",
            "feasible_branch_count",
            "uncertain_branch_count",
            "budget_alert",
            "interval_calibrated",
            "automatic_retry_allowed",
            "automatic_branch_execution_allowed",
            "selected_branch_id",
            "selected_goal_fingerprint",
            "reallocation_source",
            "source_abort_event_fingerprint",
            "episode_abort_gate_integrity_sha256",
        )
        if key in allocation
    }
    payload["ledger"] = dict(allocation.get("ledger", {}))
    payload["provenance"] = dict(provenance or allocation.get("provenance", {}) or {})
    payload["branches"] = []
    for item in allocation.get("branches", []) or []:
        if not isinstance(item, dict):
            continue
        payload["branches"].append({
            "branch_id": str(item.get("branch_id") or "")[:64],
            "source": str(item.get("source") or "frontier")[:64],
            "category": str(item.get("category") or "unknown")[:64],
            "ready": bool(item.get("ready")),
            "eligible": bool(item.get("eligible")),
            "safety_reserved": bool(item.get("safety_reserved")),
            "selected": bool(item.get("selected")),
            "priority_signal": round(_safe_float(item.get("priority_signal"), 0.0), 6),
            "signals": _normalized_signals(item.get("signals", {})),
            "estimated_rounds_low": item.get("estimated_rounds_low"),
            "estimated_rounds_high": item.get("estimated_rounds_high"),
            "interval_calibrated": bool(item.get("interval_calibrated")),
            "score": round(_safe_float(item.get("score"), 0.0), 6),
            "allocated_rounds": max(0, _safe_int(item.get("allocated_rounds"), 0)),
        })
    return payload


def write_frontier_rollout_budget_gate(report: dict, path: str):
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)


def frontier_budget_gate_integrity_hash(gate: dict) -> str:
    payload = dict(gate or {})
    payload.pop("gate_integrity_sha256", None)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_frontier_budget_gate_payload(gate: dict):
    """Raise when a saved frontier budget gate is inconsistent or overclaims authority."""
    if not isinstance(gate, dict):
        raise ValueError("frontier budget gate JSON must be an object")
    if gate.get("type") != GATE_TYPE or gate.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"frontier budget gate must be {GATE_TYPE} schema {SCHEMA_VERSION}")
    if gate.get("allocation_profile") != ALLOCATION_PROFILE or gate.get("interval_profile") != INTERVAL_PROFILE:
        raise ValueError("frontier budget gate profiles are unsupported")
    for field in ("automatic_retry_allowed", "automatic_branch_execution_allowed", "budget_extension_allowed"):
        if gate.get(field) is not False:
            raise ValueError(f"frontier budget gate cannot authorize {field}")
    shadow = gate.get("shadow_allocation_allowed") is True
    advisory = gate.get("advisory_context_allowed") is True
    if shadow or advisory:
        expected_hash = str(gate.get("gate_integrity_sha256") or "")
        if len(expected_hash) != 64 or expected_hash != frontier_budget_gate_integrity_hash(gate):
            raise ValueError("frontier budget gate integrity hash is invalid")
    config = gate.get("allocation_config", {}) if isinstance(gate.get("allocation_config", {}), dict) else {}
    if config.get("policy") != "information":
        raise ValueError("frontier budget advisory gate must bind the information policy")
    if _safe_int(config.get("total_rounds"), 0) < 1:
        raise ValueError("frontier budget total rounds must be positive")
    if _safe_float(config.get("temperature"), 0.0) <= 0.0:
        raise ValueError("frontier budget temperature must be positive")
    if _safe_int(config.get("exploration_floor"), -1) < 0:
        raise ValueError("frontier budget exploration floor must be non-negative")
    if not advisory:
        if gate.get("readiness") == "approved":
            raise ValueError("approved frontier budget gate must allow advisory context")
        return
    if gate.get("readiness") != "approved" or gate.get("decision") != "allow_frontier_budget_advisory_context":
        raise ValueError("advisory frontier budget gate readiness or decision is inconsistent")
    if gate.get("runtime_eligible") is not True or gate.get("evidence_kind") != "live_trace":
        raise ValueError("advisory frontier budget gate lacks eligible live evidence")
    if not shadow:
        raise ValueError("advisory frontier budget gate must also allow shadow allocation")
    thresholds = gate.get("thresholds", {}) if isinstance(gate.get("thresholds", {}), dict) else {}
    if _safe_int(gate.get("pair_count"), 0) < _safe_int(thresholds.get("min_live_pairs"), 1):
        raise ValueError("advisory frontier budget gate has too few live pairs")
    checks = gate.get("checks", []) if isinstance(gate.get("checks", []), list) else []
    if not checks or any(not isinstance(check, dict) or check.get("status") != "pass" for check in checks):
        raise ValueError("advisory frontier budget gate has failed promotion checks")
    integrity = gate.get("evidence_integrity", {}) if isinstance(gate.get("evidence_integrity", {}), dict) else {}
    for key in (
        "input_paths_unique",
        "pair_ids_unique",
        "explicit_session_ids",
        "sessions_distinct",
        "fixed_controls",
        "policy_replay_valid",
        "live_boundaries_complete",
        "session_log_evidence_only",
        "source_manifests_valid",
    ):
        if integrity.get(key) is not True:
            raise ValueError(f"frontier budget evidence integrity failed: {key}")
    manifests = gate.get("source_manifests", []) if isinstance(gate.get("source_manifests", []), list) else []
    if not manifests or any(not _manifest_valid(item) for item in manifests):
        raise ValueError("frontier budget source manifests are incomplete")
    provenance = gate.get("provenance", {}) if isinstance(gate.get("provenance", {}), dict) else {}
    if not all(str(provenance.get(key) or "").strip() for key in CONTROL_KEYS):
        raise ValueError("frontier budget provenance is incomplete")
    allocation = gate.get("allocation_metrics", {}) if isinstance(gate.get("allocation_metrics", {}), dict) else {}
    if allocation.get("all_pairs_budget_conserved") is not True:
        raise ValueError("frontier budget gate does not conserve every paired budget")
    if _safe_float(allocation.get("mean_candidate_resolution_targeting_gain"), 0.0) <= 0.0:
        raise ValueError("frontier budget gate has no positive resolution targeting gain")
    if allocation.get("all_recovered_budget_certified") is not True:
        raise ValueError("frontier budget gate uses uncertified recovered rounds")
    interval = gate.get("interval_metrics", {}) if isinstance(gate.get("interval_metrics", {}), dict) else {}
    if interval.get("calibrated_on_held_out_pairs") is not True:
        raise ValueError("frontier budget intervals are not held-out calibrated")
    if _safe_int(interval.get("observation_count"), 0) < _safe_int(thresholds.get("min_interval_observations"), 1):
        raise ValueError("frontier budget gate has too few interval observations")
    if _safe_float(interval.get("coverage_lower_bound"), 0.0) < _safe_float(thresholds.get("target_interval_coverage"), 1.0):
        raise ValueError("frontier budget interval coverage certificate is below target")
    if _safe_float(interval.get("optimistic_miss_rate"), 1.0) > _safe_float(thresholds.get("max_optimistic_miss_rate"), 0.0):
        raise ValueError("frontier budget optimistic interval miss rate is too high")


def _evaluate_frontier_budget_pair(
    pair: dict,
    total_rounds: int,
    temperature: float,
    exploration_floor: int,
    expected_provenance: dict,
    episode_abort_link: dict,
    index: int,
) -> dict:
    if not isinstance(pair, dict):
        raise ValueError("paired case must be an object")
    pair_id = str(pair.get("pair_id") or f"frontier-pair-{index:03d}")[:96]
    branches = pair.get("branches", []) if isinstance(pair.get("branches", []), list) else []
    if not branches:
        raise ValueError(f"{pair_id} has no branches")
    pair_total = _safe_int(pair.get("total_rounds"), total_rounds)
    if pair_total != total_rounds:
        raise ValueError(f"{pair_id} total_rounds does not match fixed control")
    consumed = max(0, _safe_int(pair.get("consumed_rounds"), 0))
    recovered = max(0, _safe_int(pair.get("recovered_rounds"), 0))
    comparison = compare_frontier_allocations(
        branches,
        pair_total,
        consumed_rounds=consumed,
        recovered_rounds=recovered,
        temperature=temperature,
        exploration_floor=exploration_floor,
    )
    baseline = _normalize_outcome(pair.get("baseline_outcome", {}), pair_total)
    candidate = _normalize_outcome(pair.get("candidate_outcome", {}), pair_total)
    uniform_map = {item["branch_id"]: item["allocated_rounds"] for item in comparison["uniform"]["branches"]}
    information_map = {item["branch_id"]: item["allocated_rounds"] for item in comparison["information"]["branches"]}
    observed_uniform = pair.get("observed_uniform_allocations", {}) if isinstance(pair.get("observed_uniform_allocations", {}), dict) else {}
    observed_information = pair.get("observed_information_allocations", {}) if isinstance(pair.get("observed_information_allocations", {}), dict) else {}
    if str(pair.get("_source_kind") or "") == "session_logs":
        policy_replay_valid = bool(
            observed_uniform
            and observed_information
            and {str(key): _safe_int(value, -1) for key, value in observed_uniform.items()} == uniform_map
            and {str(key): _safe_int(value, -1) for key, value in observed_information.items()} == information_map
        )
    else:
        policy_replay_valid = True
    pool = comparison["information"]["ledger"]["allocation_pool_rounds"]
    resolved_ids = candidate["resolved_branch_ids"]
    uniform_targeted = sum(uniform_map.get(branch_id, 0) for branch_id in resolved_ids)
    information_targeted = sum(information_map.get(branch_id, 0) for branch_id in resolved_ids)
    targeting_gain = (information_targeted - uniform_targeted) / pool if pool else 0.0
    information_by_id = {item["branch_id"]: item for item in comparison["information"]["branches"]}
    interval_observations = 0
    interval_covered = 0
    optimistic_misses = 0
    for branch_id, actual_rounds in candidate["actual_rounds_by_branch"].items():
        item = information_by_id.get(branch_id)
        if not item:
            continue
        low = item.get("estimated_rounds_low")
        high = item.get("estimated_rounds_high")
        if low is None or high is None:
            continue
        interval_observations += 1
        actual = max(0, _safe_int(actual_rounds, 0))
        if _safe_int(low, 0) <= actual <= _safe_int(high, 0):
            interval_covered += 1
        if actual > _safe_int(high, 0):
            optimistic_misses += 1
    provenance = pair.get("provenance", {}) if isinstance(pair.get("provenance", {}), dict) else {}
    provenance_match = bool(
        all(
            str(expected_provenance.get(key) or "").strip()
            and str(expected_provenance.get(key) or "").strip() == str(provenance.get(key) or "").strip()
            for key in CONTROL_KEYS
        )
        and (
            str(pair.get("_source_kind") or "") != "session_logs"
            or (
                math.isclose(_safe_float(pair.get("observed_temperature"), -1.0), temperature)
                and _safe_int(pair.get("observed_exploration_floor"), -1) == exploration_floor
            )
        )
    )
    baseline_session = str(pair.get("baseline_session_id") or "")
    candidate_session = str(pair.get("candidate_session_id") or "")
    connected = pair.get("connected", {}) if isinstance(pair.get("connected", {}), dict) else {}
    complete = pair.get("complete_boundary", {}) if isinstance(pair.get("complete_boundary", {}), dict) else {}
    live_boundary_complete = bool(
        connected.get("baseline") is True
        and connected.get("candidate") is True
        and complete.get("baseline") is True
        and complete.get("candidate") is True
    )
    certified_reallocation = True
    if recovered > 0:
        expected_gate_hash = str(episode_abort_link.get("gate_integrity_sha256") or "")
        pair_gate_hash = str(pair.get("episode_abort_gate_integrity_sha256") or "")
        event_fingerprint = str(pair.get("source_abort_event_fingerprint") or "")
        certified_reallocation = bool(
            episode_abort_link.get("active_abort_allowed") is True
            and len(expected_gate_hash) == 64
            and pair_gate_hash == expected_gate_hash
            and len(event_fingerprint) == 16
            and (
                str(pair.get("_source_kind") or "") != "session_logs"
                or pair.get("runtime_recovery_credit_valid") is True
            )
        )
    return {
        "pair_id": pair_id,
        "source_kind": str(pair.get("_source_kind") or "unknown"),
        "baseline_session_id": baseline_session,
        "candidate_session_id": candidate_session,
        "provenance_match": provenance_match,
        "live_boundary_complete": live_boundary_complete,
        "branch_input_sha256": _branch_input_hash(branches),
        "total_rounds": pair_total,
        "consumed_rounds": consumed,
        "recovered_rounds": recovered,
        "certified_reallocation": certified_reallocation,
        "budget_conservation_valid": comparison["both_budgets_conserved"],
        "policy_replay_valid": policy_replay_valid,
        "changed_branch_count": comparison["changed_branch_count"],
        "allocation_l1_distance": comparison["allocation_l1_distance"],
        "candidate_resolution_targeting_gain": round(targeting_gain, 6),
        "interval_observation_count": interval_observations,
        "interval_covered_count": interval_covered,
        "optimistic_interval_miss_count": optimistic_misses,
        "baseline": baseline,
        "candidate": candidate,
        "uniform_allocations": uniform_map,
        "information_allocations": information_map,
    }


def _aggregate_pair_outcomes(pair_evaluations: list[dict], side: str) -> dict:
    outcomes = [item.get(side, {}) for item in pair_evaluations if isinstance(item.get(side, {}), dict)]
    completions = sum(1 for outcome in outcomes if outcome.get("goal_completed") is True)
    planner_rounds = sum(_safe_int(outcome.get("planner_rounds_used"), 0) for outcome in outcomes)
    verifier_events = sum(_safe_int(outcome.get("verifier_event_count"), 0) for outcome in outcomes)
    verifier_rejects = sum(_safe_int(outcome.get("verifier_reject_count"), 0) for outcome in outcomes)
    action_events = sum(_safe_int(outcome.get("action_event_count"), 0) for outcome in outcomes)
    action_failures = sum(_safe_int(outcome.get("action_failure_count"), 0) for outcome in outcomes)
    resolved = sum(len(outcome.get("resolved_branch_ids", [])) for outcome in outcomes)
    unsafe = sum(_safe_int(outcome.get("unsafe_action_count"), 0) for outcome in outcomes)
    verification_enforced = sum(1 for outcome in outcomes if outcome.get("action_verification_enforced") is True)
    return {
        "pair_outcome_count": len(outcomes),
        "completed_goal_count": completions,
        "completion_rate": _ratio(completions, len(outcomes)),
        "planner_rounds_used": planner_rounds,
        "completion_per_planner_round": _ratio(completions, planner_rounds),
        "verifier_event_count": verifier_events,
        "verifier_reject_count": verifier_rejects,
        "verifier_reject_rate": _ratio(verifier_rejects, verifier_events),
        "action_event_count": action_events,
        "action_failure_count": action_failures,
        "action_failure_rate": _ratio(action_failures, action_events),
        "prerequisite_resolution_count": resolved,
        "prerequisite_resolution_rate": _ratio(resolved, len(outcomes)),
        "unsafe_action_count": unsafe,
        "action_verification_enforced_count": verification_enforced,
        "all_outcomes_action_verification_enforced": verification_enforced == len(outcomes) and bool(outcomes),
    }


def _pairs_from_session_logs(baseline_paths: list[str], candidate_paths: list[str]) -> tuple[list[dict], list[dict], list[str]]:
    pairs = []
    manifests = []
    errors = []
    if not baseline_paths and not candidate_paths:
        return pairs, manifests, errors
    if len(baseline_paths) != len(candidate_paths):
        return pairs, manifests, ["baseline and candidate frontier budget log counts must match"]
    for log_index, (baseline_path, candidate_path) in enumerate(zip(baseline_paths, candidate_paths), start=1):
        try:
            baseline_events, baseline_manifest = _read_jsonl_manifest(baseline_path)
            candidate_events, candidate_manifest = _read_jsonl_manifest(candidate_path)
            manifests.extend([baseline_manifest, candidate_manifest])
            baseline_units = _frontier_budget_log_units(baseline_events, expected_policy="uniform")
            candidate_units = _frontier_budget_log_units(candidate_events, expected_policy="information")
            if len(baseline_units) != len(candidate_units):
                raise ValueError("baseline and candidate logs expose different allocation/outcome counts")
            baseline_session = _explicit_session_id(baseline_events)
            candidate_session = _explicit_session_id(candidate_events)
            for unit_index, (baseline, candidate) in enumerate(zip(baseline_units, candidate_units), start=1):
                if baseline["branch_input_sha256"] != candidate["branch_input_sha256"]:
                    raise ValueError(f"paired unit {unit_index} branch inputs differ")
                b_allocation = baseline["allocation"]
                c_allocation = candidate["allocation"]
                if b_allocation.get("ledger", {}) != c_allocation.get("ledger", {}):
                    raise ValueError(f"paired unit {unit_index} budget ledgers differ")
                if b_allocation.get("provenance", {}) != c_allocation.get("provenance", {}):
                    raise ValueError(f"paired unit {unit_index} provenance differs")
                for key in ("temperature", "exploration_floor"):
                    if b_allocation.get(key) != c_allocation.get(key):
                        raise ValueError(f"paired unit {unit_index} {key} differs")
                pairs.append({
                    "_source_kind": "session_logs",
                    "pair_id": f"logs-{log_index:03d}-{unit_index:03d}",
                    "baseline_session_id": baseline_session,
                    "candidate_session_id": candidate_session,
                    "connected": {
                        "baseline": _connect_success(baseline_events),
                        "candidate": _connect_success(candidate_events),
                    },
                    "complete_boundary": {
                        "baseline": baseline["complete_boundary"],
                        "candidate": candidate["complete_boundary"],
                    },
                    "provenance": c_allocation.get("provenance", {}),
                    "total_rounds": _safe_int(c_allocation.get("ledger", {}).get("total_rounds"), 0),
                    "consumed_rounds": _safe_int(c_allocation.get("ledger", {}).get("consumed_rounds"), 0),
                    "recovered_rounds": _safe_int(c_allocation.get("ledger", {}).get("declared_recovered_rounds"), 0),
                    "observed_temperature": c_allocation.get("temperature"),
                    "observed_exploration_floor": c_allocation.get("exploration_floor"),
                    "episode_abort_gate_integrity_sha256": c_allocation.get("episode_abort_gate_integrity_sha256", ""),
                    "source_abort_event_fingerprint": c_allocation.get("source_abort_event_fingerprint", ""),
                    "runtime_recovery_credit_valid": bool(
                        baseline.get("recovery_credit_valid") and candidate.get("recovery_credit_valid")
                    ),
                    "branches": _trace_branches_for_replay(c_allocation.get("branches", [])),
                    "observed_uniform_allocations": {
                        str(item.get("branch_id") or ""): _safe_int(item.get("allocated_rounds"), 0)
                        for item in b_allocation.get("branches", []) or []
                        if isinstance(item, dict) and item.get("branch_id")
                    },
                    "observed_information_allocations": {
                        str(item.get("branch_id") or ""): _safe_int(item.get("allocated_rounds"), 0)
                        for item in c_allocation.get("branches", []) or []
                        if isinstance(item, dict) and item.get("branch_id")
                    },
                    "baseline_outcome": baseline["outcome"],
                    "candidate_outcome": candidate["outcome"],
                })
        except Exception as exc:
            errors.append(f"{baseline_path} <> {candidate_path}: {exc}")
    return pairs, manifests, errors


def _frontier_budget_log_units(events: list[dict], expected_policy: str) -> list[dict]:
    allocations = []
    pending = []
    recovery_credits = {}
    for event in events:
        if event.get("type") != "frontier_budget_recovery_credit":
            continue
        data = event.get("data", {}) if isinstance(event.get("data", {}), dict) else {}
        fingerprint = str(data.get("source_abort_event_fingerprint") or "")
        if len(fingerprint) == 16:
            recovery_credits[fingerprint] = data
    for event in events:
        event_type = str(event.get("type") or "")
        data = event.get("data", {}) if isinstance(event.get("data", {}), dict) else {}
        if event_type == "frontier_budget_allocation":
            if str(data.get("policy") or "") != expected_policy:
                continue
            ledger = data.get("ledger", {}) if isinstance(data.get("ledger", {}), dict) else {}
            recovered = max(0, _safe_int(ledger.get("declared_recovered_rounds"), 0))
            credit_valid = recovered == 0
            if recovered > 0:
                fingerprint = str(data.get("source_abort_event_fingerprint") or "")
                credit = recovery_credits.get(fingerprint, {})
                credit_valid = bool(
                    credit
                    and _safe_int(credit.get("saved_planner_rounds"), 0) >= recovered
                    and str(credit.get("episode_abort_gate_integrity_sha256") or "")
                    == str(data.get("episode_abort_gate_integrity_sha256") or "")
                )
            pending.append({"allocation": data, "outcome": None, "recovery_credit_valid": credit_valid})
        elif event_type == "frontier_budget_outcome" and pending:
            target = next((item for item in pending if item["outcome"] is None), None)
            if target is not None:
                target["outcome"] = data
    terminal_count = sum(
        1 for event in events
        if event.get("type") in {"goal_end", "auto_goal_complete", "auto_goal_failed", "autonomous_end"}
    )
    for item in pending:
        if not isinstance(item.get("outcome"), dict):
            continue
        allocation = item["allocation"]
        branches = _trace_branches_for_replay(allocation.get("branches", []))
        allocations.append({
            "allocation": allocation,
            "outcome": item["outcome"],
            "branch_input_sha256": _branch_input_hash(branches),
            "complete_boundary": terminal_count >= len(pending),
            "recovery_credit_valid": item.get("recovery_credit_valid") is True,
        })
    return allocations


def _trace_branches_for_replay(branches: list[dict]) -> list[dict]:
    replay = []
    for item in branches or []:
        if not isinstance(item, dict):
            continue
        replay.append({
            "branch_id": item.get("branch_id"),
            "source": item.get("source"),
            "category": item.get("category"),
            "ready": item.get("ready"),
            "eligible": item.get("eligible"),
            "safety_reserved": item.get("safety_reserved"),
            "selected": item.get("selected"),
            "priority_signal": item.get("priority_signal"),
            "signals": item.get("signals", {}),
            "estimated_rounds_low": item.get("estimated_rounds_low"),
            "estimated_rounds_high": item.get("estimated_rounds_high"),
        })
    return replay


def _load_frontier_budget_cases(paths: list[str]) -> tuple[list[dict], list[dict], list[str]]:
    records = []
    manifests = []
    errors = []
    for path in paths or []:
        try:
            with open(path, "rb") as handle:
                raw = handle.read()
            text = raw.decode("utf-8-sig")
            manifests.append(_manifest_for_bytes(path, raw))
            try:
                payload = json.loads(text)
                if isinstance(payload, dict) and isinstance(payload.get("pairs"), list):
                    loaded = payload["pairs"]
                elif isinstance(payload, list):
                    loaded = payload
                elif isinstance(payload, dict):
                    loaded = [payload]
                else:
                    raise ValueError("case JSON must be an object or list")
            except json.JSONDecodeError:
                loaded = []
                for line_number, line in enumerate(text.splitlines(), start=1):
                    if not line.strip():
                        continue
                    item = json.loads(line)
                    if not isinstance(item, dict):
                        raise ValueError(f"JSONL line {line_number} must be an object")
                    loaded.append(item)
            for item in loaded:
                if not isinstance(item, dict):
                    continue
                record = dict(item)
                record["_source_kind"] = "case_file"
                records.append(record)
        except Exception as exc:
            errors.append(f"{path}: {exc}")
    return records, manifests, errors


def _load_episode_abort_link(paths: list[str], expected_provenance: dict) -> tuple[dict, list[str]]:
    link = {
        "path_count": len(paths or []),
        "active_abort_allowed": False,
        "provenance_match": False,
        "gate_integrity_sha256": "",
    }
    if not paths:
        return link, []
    if len(paths) != 1:
        return link, ["exactly one episode early-abort gate may certify recovered rounds"]
    path = paths[0]
    try:
        from singularity.core.episode_abort import validate_episode_abort_gate_payload

        with open(path, "rb") as handle:
            raw = handle.read()
        gate = json.loads(raw.decode("utf-8-sig"))
        validate_episode_abort_gate_payload(gate)
        provenance = gate.get("provenance", {}) if isinstance(gate.get("provenance", {}), dict) else {}
        match = all(
            str(expected_provenance.get(key) or "").strip()
            and str(expected_provenance.get(key) or "").strip() == str(provenance.get(key) or "").strip()
            for key in CONTROL_KEYS
        )
        link.update({
            "active_abort_allowed": gate.get("active_abort_allowed") is True,
            "provenance_match": match,
            "gate_integrity_sha256": str(gate.get("gate_integrity_sha256") or ""),
            "source_manifest": _manifest_for_bytes(path, raw),
        })
        if not match:
            return link, ["episode early-abort gate provenance does not match frontier budget controls"]
    except Exception as exc:
        return link, [f"{path}: {exc}"]
    return link, []


def _builtin_frontier_budget_pairs() -> list[dict]:
    controls = {
        "planner_id": "builtin-fixed-planner-v1",
        "action_backend": "synthetic-no-execution",
        "verifier_id": "builtin-milestone-verifier-v1",
        "task_stream_id": "builtin-frontier-budget",
        "seed": "builtin-20260710",
    }
    cases = [
        (
            "shelter-prerequisite",
            [
                _builtin_branch("Gather oak logs", closes=2, frontier=1, low=2, high=4),
                _builtin_branch("Inspect cave entrance", novelty=1, risk=1, low=2, high=5),
                _builtin_branch("Place shelter walls", eligible=False, ready=False, missing=1),
            ],
            "Gather oak logs",
            3,
        ),
        (
            "torch-prerequisite",
            [
                _builtin_branch("Mine visible coal", closes=2, verifier=1, low=2, high=4),
                _builtin_branch("Scout another landmark", novelty=1, frontier=1, low=2, high=5),
                _builtin_branch("Craft torches", eligible=False, ready=False, missing=1),
            ],
            "Mine visible coal",
            3,
        ),
        (
            "safe-route-prerequisite",
            [
                _builtin_branch("Verify safer frontier route", closes=1, verifier=1, frontier=1, low=2, high=4),
                _builtin_branch("Enter dangerous cave directly", novelty=1, risk=2, low=2, high=6),
                _builtin_branch("Deep cave mining", eligible=False, ready=False, missing=1),
            ],
            "Verify safer frontier route",
            4,
        ),
    ]
    pairs = []
    for index, (name, branches, resolved_title, actual_rounds) in enumerate(cases, start=1):
        resolved_id = frontier_branch_id(resolved_title, "builtin")
        pairs.append({
            "_source_kind": "builtin",
            "pair_id": f"builtin-{name}",
            "baseline_session_id": f"builtin-uniform-{index}",
            "candidate_session_id": f"builtin-information-{index}",
            "connected": {"baseline": False, "candidate": False},
            "complete_boundary": {"baseline": True, "candidate": True},
            "provenance": controls,
            "total_rounds": 8,
            "consumed_rounds": 0,
            "recovered_rounds": 0,
            "branches": branches,
            "baseline_outcome": {
                "goal_completed": False,
                "planner_rounds_used": 8,
                "verifier_event_count": 2,
                "verifier_reject_count": 1,
                "action_event_count": 4,
                "action_failure_count": 2,
                "unsafe_action_count": 0,
                "action_verification_enforced": True,
                "resolved_branch_ids": [],
            },
            "candidate_outcome": {
                "goal_completed": True,
                "planner_rounds_used": actual_rounds,
                "verifier_event_count": 2,
                "verifier_reject_count": 0,
                "action_event_count": 3,
                "action_failure_count": 0,
                "unsafe_action_count": 0,
                "action_verification_enforced": True,
                "resolved_branch_ids": [resolved_id],
                "actual_rounds_by_branch": {resolved_id: actual_rounds},
            },
        })
    return pairs


def _builtin_branch(
    title: str,
    closes: int = 0,
    verifier: int = 0,
    novelty: int = 0,
    frontier: int = 0,
    risk: int = 0,
    eligible: bool = True,
    ready: bool = True,
    missing: int = 0,
    low: int = 1,
    high: int = 4,
) -> dict:
    return {
        "branch_id": frontier_branch_id(title, "builtin"),
        "source": "builtin",
        "category": "synthetic_control",
        "ready": ready,
        "eligible": eligible,
        "safety_reserved": False,
        "priority_signal": 0.5,
        "signals": {
            "closes_precondition_count": closes,
            "verifier_reject_count": verifier,
            "novelty_count": novelty,
            "frontier_gap_count": frontier,
            "risk_count": risk,
            "missing_precondition_count": missing,
        },
        "estimated_rounds_low": low,
        "estimated_rounds_high": high,
    }


def _normalize_allocator_branches(branches: list[dict]) -> list[dict]:
    normalized = []
    seen = set()
    for index, branch in enumerate(branches or [], start=1):
        if not isinstance(branch, dict):
            continue
        branch_id = str(branch.get("branch_id") or frontier_branch_id(str(branch.get("title") or index), str(branch.get("source") or "frontier")))[:64]
        if not branch_id or branch_id in seen:
            continue
        seen.add(branch_id)
        normalized.append({
            "branch_id": branch_id,
            "title": str(branch.get("title") or "")[:180],
            "source": str(branch.get("source") or "frontier")[:64],
            "category": str(branch.get("category") or "unknown")[:64],
            "ready": bool(branch.get("ready", True)),
            "eligible": bool(branch.get("eligible", True)),
            "safety_reserved": bool(branch.get("safety_reserved", False)),
            "selected": bool(branch.get("selected", False)),
            "priority_signal": _clamp(_safe_float(branch.get("priority_signal"), 0.5), 0.0, 1.0),
            "signals": _normalized_signals(branch.get("signals", {})),
            "estimated_rounds_low": branch.get("estimated_rounds_low"),
            "estimated_rounds_high": branch.get("estimated_rounds_high"),
        })
        if len(normalized) >= MAX_BRANCHES:
            break
    return normalized


def _branch_round_interval(branch: dict, signals: dict, eligible: bool) -> tuple[Optional[int], Optional[int]]:
    if not eligible:
        return None, None
    explicit_low = branch.get("estimated_rounds_low")
    explicit_high = branch.get("estimated_rounds_high")
    if explicit_low is not None or explicit_high is not None:
        low = max(1, _safe_int(explicit_low, 1))
        high = max(low, _safe_int(explicit_high, low))
        return low, high
    low = 1 + min(2, signals["missing_dependency_count"])
    high = low + 1
    high += min(3, signals["closes_precondition_count"])
    high += min(2, signals["verifier_reject_count"] + signals["no_progress_count"])
    high += min(2, signals["novelty_count"] + signals["frontier_gap_count"])
    high += min(2, signals["risk_count"])
    return low, max(low, high)


def _allocate_largest_remainder(allocations: dict, eligible: list[dict], weights: dict, rounds: int, policy: str):
    total_weight = sum(max(0.0, _safe_float(weights.get(item["branch_id"]), 0.0)) for item in eligible)
    if total_weight <= 0.0:
        total_weight = float(len(eligible))
        weights = {item["branch_id"]: 1.0 for item in eligible}
    remainders = []
    assigned = 0
    for item in eligible:
        branch_id = item["branch_id"]
        quota = rounds * max(0.0, _safe_float(weights.get(branch_id), 0.0)) / total_weight
        whole = int(math.floor(quota))
        allocations[branch_id] += whole
        assigned += whole
        remainders.append((quota - whole, item["score"] if policy == "information" else 0.0, branch_id))
    remaining = rounds - assigned
    for _, _, branch_id in sorted(remainders, key=lambda item: (-item[0], -item[1], item[2]))[:remaining]:
        allocations[branch_id] += 1


def _deduplicate_branches(branches: list[dict]) -> list[dict]:
    by_goal = {}
    for branch in branches:
        key = " ".join(str(branch.get("title") or branch.get("branch_id") or "").lower().split())
        if not key:
            continue
        previous = by_goal.get(key)
        if previous is None:
            by_goal[key] = branch
            continue
        merged = dict(previous)
        merged["source"] = "task_and_curriculum"
        merged["ready"] = bool(previous.get("ready") or branch.get("ready"))
        merged["eligible"] = bool(previous.get("eligible") or branch.get("eligible"))
        merged["safety_reserved"] = bool(previous.get("safety_reserved") or branch.get("safety_reserved"))
        merged["selected"] = bool(previous.get("selected") or branch.get("selected"))
        merged_signals = _normalized_signals(previous.get("signals", {}))
        incoming = _normalized_signals(branch.get("signals", {}))
        merged["signals"] = {key: max(merged_signals[key], incoming[key]) for key in merged_signals}
        if branch.get("source") == "task_readiness":
            merged["branch_id"] = branch.get("branch_id")
            merged["category"] = branch.get("category")
            merged["priority_value"] = branch.get("priority_value")
            merged["priority_direction"] = branch.get("priority_direction")
        by_goal[key] = merged
    return list(by_goal.values())


def _assign_priority_signals(branches: list[dict]):
    higher = [branch for branch in branches if branch.get("priority_direction") == "higher"]
    lower = [branch for branch in branches if branch.get("priority_direction") == "lower"]
    for group, direction in ((higher, "higher"), (lower, "lower")):
        if not group:
            continue
        values = [_safe_float(branch.get("priority_value"), 0.0) for branch in group]
        low = min(values)
        high = max(values)
        for branch, value in zip(group, values):
            signal = 0.5 if math.isclose(low, high) else (value - low) / (high - low)
            if direction == "lower":
                signal = 1.0 - signal
            branch["priority_signal"] = round(_clamp(signal, 0.0, 1.0), 6)
    for branch in branches:
        branch.setdefault("priority_signal", 0.5)


def _normalized_signals(signals: Any) -> dict:
    source = signals if isinstance(signals, dict) else {}
    keys = (
        "closes_precondition_count",
        "verifier_reject_count",
        "no_progress_count",
        "novelty_count",
        "frontier_gap_count",
        "risk_count",
        "attempt_count",
        "failure_count",
        "missing_dependency_count",
        "missing_precondition_count",
    )
    return {key: max(0, min(1000, _safe_int(source.get(key), 0))) for key in keys}


def _normalize_outcome(outcome: Any, total_rounds: int) -> dict:
    source = outcome if isinstance(outcome, dict) else {}
    actual = source.get("actual_rounds_by_branch", {}) if isinstance(source.get("actual_rounds_by_branch", {}), dict) else {}
    return {
        "goal_completed": source.get("goal_completed") is True or source.get("success") is True,
        "planner_rounds_used": max(0, min(total_rounds, _safe_int(source.get("planner_rounds_used", source.get("cycles", 0)), 0))),
        "verifier_event_count": max(0, _safe_int(source.get("verifier_event_count"), 0)),
        "verifier_reject_count": max(0, _safe_int(source.get("verifier_reject_count"), 0)),
        "action_event_count": max(0, _safe_int(source.get("action_event_count"), 0)),
        "action_failure_count": max(0, _safe_int(source.get("action_failure_count"), 0)),
        "unsafe_action_count": max(0, _safe_int(source.get("unsafe_action_count"), 0)),
        "action_verification_enforced": source.get("action_verification_enforced") is True,
        "resolved_branch_ids": _string_list(source.get("resolved_branch_ids", []), limit=MAX_BRANCHES),
        "actual_rounds_by_branch": {
            str(branch_id)[:64]: max(0, _safe_int(rounds, 0))
            for branch_id, rounds in actual.items()
            if branch_id
        },
    }


def _inventory_requirement_names(value: Any) -> set[str]:
    names = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() == "inventory" and isinstance(child, dict):
                names.update(_normalize_item(item) for item in child)
            elif isinstance(child, (dict, list)):
                names.update(_inventory_requirement_names(child))
    elif isinstance(value, list):
        for child in value:
            names.update(_inventory_requirement_names(child))
    return {name for name in names if name}


def _branch_input_hash(branches: list[dict]) -> str:
    normalized = _trace_branches_for_replay(_normalize_allocator_branches(branches))
    canonical = json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


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
        "path_fingerprint": hashlib.sha256(_normalized_path(path).encode("utf-8")).hexdigest()[:16],
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


def _add_gate_check(checks: list[dict], name: str, passed: bool, detail: str):
    checks.append({"name": name, "status": "pass" if passed else "fail", "detail": detail})


def _normalize_item(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


def _same_goal(left: str, right: str) -> bool:
    return " ".join(str(left or "").lower().split()) == " ".join(str(right or "").lower().split())


def _string_list(value: Any, limit: int = 16) -> list[str]:
    if not isinstance(value, list):
        value = [value] if value not in (None, "") else []
    result = []
    seen = set()
    for item in value:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text[:160])
        if len(result) >= limit:
            break
    return result


def _normalized_path(path: str) -> str:
    return os.path.normcase(os.path.abspath(str(path or "")))


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


def _clamp(value: float, low: float, high: float) -> float:
    return min(high, max(low, value))


def _ratio(numerator: int | float, denominator: int | float) -> float:
    try:
        denominator = float(denominator)
        return round(float(numerator) / denominator, 6) if denominator > 0 else 0.0
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0
