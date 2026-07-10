"""Recall-controlled early termination for long-running agent episodes.

The current runtime commonly uses hosted models and cannot read hidden model
activations.  This module therefore implements a deliberately weaker,
API-visible behavioral scorer behind a versioned interface.  It preserves the
important safety mechanics from recall-controlled abort cascades: disjoint
calibration/validation/test evidence, exact binomial recall bounds, global
episode-level selection, abstention when evidence is insufficient, and an
explicit shadow mode before any action-changing deployment.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import os
from dataclasses import dataclass, field
from typing import Optional


SIGNAL_PROFILE = "behavior_surface_v1"
GATE_TYPE = "episode_early_abort_gate"
SCHEMA_VERSION = 1
DEFAULT_BUDGET_GRID = (0.85, 0.90, 0.95, 0.98, 0.99, 1.0)
DEFAULT_GATE_ROUNDS = (2, 4, 8)
MAX_BUDGET_CANDIDATES = 50_000
ACTION_BACKEND_ID = "mineflayer-bridge-v1"
VERIFIER_ID = "goal-action-verifier-v1"


@dataclass
class EpisodeTrajectory:
    """One goal-bounded trajectory reconstructed from a session log."""

    episode_id: str
    session_id: str
    goal_fingerprint: str
    success: bool
    cycle_count: int
    events: list[dict] = field(default_factory=list, repr=False)
    _score_cache: dict[int, Optional[dict]] = field(default_factory=dict, repr=False)
    source_path: str = ""
    complete_boundary: bool = False
    connect_success: bool = False
    explicit_session_id: bool = False

    def score_at_round(self, round_index: int) -> Optional[dict]:
        """Return the behavioral score after a completed round while alive."""
        round_index = int(round_index)
        if round_index in self._score_cache:
            return self._score_cache[round_index]
        if round_index < 1 or self.cycle_count <= round_index:
            self._score_cache[round_index] = None
            return None
        prefix = _episode_prefix_after_round(self.events, round_index)
        if not prefix:
            self._score_cache[round_index] = None
            return None
        self._score_cache[round_index] = behavior_surface_score(prefix)
        return self._score_cache[round_index]


@dataclass
class EpisodeAbortDecision:
    """Runtime result from one configured viability checkpoint."""

    evaluated: bool = False
    round_index: int = 0
    score: float = 0.0
    threshold: Optional[float] = None
    would_abort: bool = False
    active_abort: bool = False
    runtime_mode: str = "off"
    signal_profile: str = SIGNAL_PROFILE
    features: dict = field(default_factory=dict)
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "evaluated": self.evaluated,
            "round": self.round_index,
            "score": self.score,
            "threshold": self.threshold,
            "would_abort": self.would_abort,
            "active_abort": self.active_abort,
            "runtime_mode": self.runtime_mode,
            "signal_profile": self.signal_profile,
            "features": dict(self.features),
            "reason": self.reason,
        }


class EpisodeAbortMonitor:
    """Evaluate a saved, evidence-qualified cascade against runtime events."""

    def __init__(self, runtime_gate_report: Optional[dict] = None):
        report = runtime_gate_report if isinstance(runtime_gate_report, dict) else {}
        self.runtime_mode = str(report.get("effective_mode") or "off")
        self.signal_profile = str(report.get("signal_profile") or SIGNAL_PROFILE)
        self.thresholds = {}
        for item in report.get("selected_rounds", []) or []:
            if not isinstance(item, dict) or not item.get("active"):
                continue
            try:
                round_index = int(item.get("round"))
                threshold = float(item.get("threshold"))
            except (TypeError, ValueError):
                continue
            self.thresholds[round_index] = threshold

    @property
    def enabled(self) -> bool:
        return self.runtime_mode in {"shadow", "active"} and bool(self.thresholds)

    def evaluate(self, events: list[dict], round_index: int) -> EpisodeAbortDecision:
        round_index = int(round_index or 0)
        if not self.enabled:
            return EpisodeAbortDecision(runtime_mode=self.runtime_mode, reason="monitor_disabled")
        if round_index not in self.thresholds:
            return EpisodeAbortDecision(
                runtime_mode=self.runtime_mode,
                round_index=round_index,
                reason="round_not_gated",
            )
        episode_events = _current_episode_events(events or [])
        if not episode_events:
            return EpisodeAbortDecision(
                runtime_mode=self.runtime_mode,
                round_index=round_index,
                reason="goal_boundary_missing",
            )
        scored = behavior_surface_score(episode_events)
        threshold = self.thresholds[round_index]
        score = float(scored.get("score") or 0.0)
        would_abort = score > threshold
        return EpisodeAbortDecision(
            evaluated=True,
            round_index=round_index,
            score=score,
            threshold=threshold,
            would_abort=would_abort,
            active_abort=would_abort and self.runtime_mode == "active",
            runtime_mode=self.runtime_mode,
            signal_profile=self.signal_profile,
            features=scored.get("features", {}),
            reason="risk_above_threshold" if would_abort else "risk_within_threshold",
        )


def runtime_episode_abort_provenance(config) -> dict:
    """Return the control identity that a saved gate must match at runtime."""
    llm = getattr(config, "llm", None)
    if llm is not None and (
        str(getattr(llm, "api_key", "") or "").strip()
        or str(os.environ.get("OPENAI_API_KEY", "") or "").strip()
    ):
        provider = str(getattr(llm, "provider", "") or "openai").strip().lower()
        model = str(getattr(llm, "model", "") or "unknown").strip()
        planner_id = f"llm:{provider}:{model}"
    else:
        planner_id = "rule-based-v1"
    return {
        "planner_id": planner_id,
        "action_backend": ACTION_BACKEND_ID,
        "verifier_id": VERIFIER_ID,
        "task_stream_id": str(getattr(config, "episode_abort_task_stream_id", "") or "").strip(),
        "seed": str(getattr(config, "episode_abort_seed_id", "") or "").strip(),
    }


def behavior_surface_score(events: list[dict]) -> dict:
    """Return a bounded risk score using only typed, API-visible behavior.

    Free-form goal, plan, error, and reflection text is intentionally ignored.
    This keeps persisted gates independent of prompt text and makes the score
    reproducible across offline replay and runtime shadow evaluation.
    """
    plans = [event for event in events if _event_type(event) == "plan"]
    actions = [event for event in events if _event_type(event) == "action"]
    verifications = [event for event in events if _event_type(event) == "action_verification"]
    goal_verifications = [event for event in events if _event_type(event) == "goal_verification"]
    errors = [event for event in events if _event_type(event) == "error"]
    empty_plans = [event for event in events if _event_type(event) == "empty_plan"]
    blocked_plans = [event for event in events if _event_type(event) == "blocked_plan"]

    action_signatures = []
    action_failures = 0
    action_successes = 0
    for event in actions:
        data = _event_data(event)
        action = data.get("action", {}) if isinstance(data.get("action", {}), dict) else {}
        result = data.get("result", {}) if isinstance(data.get("result", {}), dict) else {}
        action_signatures.append(_action_signature(action))
        if _result_succeeded(result):
            action_successes += 1
        else:
            action_failures += 1

    verifier_rejects = sum(1 for event in verifications if _verification_rejected(event))
    goal_verifier_rejects = sum(1 for event in goal_verifications if _goal_verification_rejected(event))
    action_count = len(actions)
    plan_count = len(plans)
    repeat_count = max(0, len(action_signatures) - len(set(action_signatures)))
    state_progress = _state_progress(events)
    no_progress = 1.0 if action_count and not state_progress and not action_successes else 0.0
    no_action = 1.0 if plan_count and not action_count else 0.0

    features = {
        "plan_count": plan_count,
        "action_count": action_count,
        "action_failure_rate": _ratio(action_failures, action_count),
        "verifier_reject_rate": _ratio(verifier_rejects, max(action_count, len(verifications))),
        "goal_verifier_reject_rate": _ratio(goal_verifier_rejects, len(goal_verifications)),
        "error_density": min(1.0, _ratio(len(errors), max(1, plan_count))),
        "action_repeat_rate": _ratio(repeat_count, action_count),
        "no_progress": no_progress,
        "plan_without_action": no_action,
        "blocked_or_empty": 1.0 if blocked_plans or empty_plans else 0.0,
        "state_progress_observed": bool(state_progress),
    }
    score = (
        0.24 * features["action_failure_rate"]
        + 0.18 * features["verifier_reject_rate"]
        + 0.18 * features["goal_verifier_reject_rate"]
        + 0.10 * features["error_density"]
        + 0.12 * features["action_repeat_rate"]
        + 0.10 * features["no_progress"]
        + 0.08 * features["plan_without_action"]
    )
    if features["blocked_or_empty"]:
        score = max(score, 0.95)
    return {
        "signal_profile": SIGNAL_PROFILE,
        "score": round(min(1.0, max(0.0, score)), 6),
        "features": features,
    }


def clopper_pearson_lower_bound(successes: int, trials: int, alpha: float = 0.05) -> float:
    """Exact one-sided Clopper-Pearson lower confidence bound.

    The beta quantile is computed by inverting the integer-parameter binomial
    tail, avoiding an optional SciPy dependency.
    """
    successes = int(successes)
    trials = int(trials)
    alpha = float(alpha)
    if trials <= 0 or successes <= 0:
        return 0.0
    if successes > trials:
        raise ValueError("successes cannot exceed trials")
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must be between zero and one")
    if successes == trials:
        return alpha ** (1.0 / trials)

    low = 0.0
    high = 1.0
    for _ in range(80):
        middle = (low + high) / 2.0
        tail = _binomial_upper_tail(trials, successes, middle)
        if tail < alpha:
            low = middle
        else:
            high = middle
    return (low + high) / 2.0


def minimum_successes_for_noop_certificate(target_recall: float, alpha: float = 0.05) -> int:
    """Return successes needed for an all-survive global recall certificate."""
    target_recall = float(target_recall)
    alpha = float(alpha)
    if not 0.0 < target_recall < 1.0:
        raise ValueError("target_recall must be between zero and one")
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must be between zero and one")
    return int(math.ceil(math.log(alpha) / math.log(target_recall)))


def build_episode_early_abort_gate(
    calibration_paths: list[str],
    validation_paths: list[str],
    test_paths: list[str],
    gate_rounds: Optional[list[int]] = None,
    budget_grid: Optional[list[float]] = None,
    target_recall: float = 0.95,
    search_rule: str = "certificate",
    validation_margin: float = 0.02,
    confidence_alpha: float = 0.05,
    min_calibration_successes: int = 1,
    min_validation_successes: int = 1,
    min_test_successes: int = 1,
    min_test_failures: int = 1,
    min_test_sessions: int = 1,
    evidence_kind: str = "unknown",
    planner_id: str = "",
    action_backend: str = "",
    verifier_id: str = "",
    task_stream_id: str = "",
    seed: str = "",
    split_scope: str = "held_out_session",
) -> dict:
    """Calibrate, select, and test a behavioral early-abort cascade."""
    rounds = sorted(set(int(value) for value in (gate_rounds or DEFAULT_GATE_ROUNDS) if int(value) > 0))
    budgets = sorted(set(round(float(value), 6) for value in (budget_grid or DEFAULT_BUDGET_GRID)))
    target_recall = float(target_recall)
    validation_margin = max(0.0, float(validation_margin))
    confidence_alpha = float(confidence_alpha)
    search_rule = str(search_rule or "certificate").strip().lower()
    split_scope = str(split_scope or "held_out_session").strip().lower()
    evidence_kind = str(evidence_kind or "unknown").strip().lower()
    provenance = {
        "planner_id": str(planner_id or "").strip(),
        "action_backend": str(action_backend or "").strip(),
        "verifier_id": str(verifier_id or "").strip(),
        "task_stream_id": str(task_stream_id or "").strip(),
        "seed": str(seed or "").strip(),
    }
    report = {
        "type": GATE_TYPE,
        "schema_version": SCHEMA_VERSION,
        "signal_profile": SIGNAL_PROFILE,
        "signal_scope": "api_visible_behavior_only",
        "hidden_activation_claimed": False,
        "readiness": "review",
        "decision": "hold_episode_early_abort",
        "reason": "episode early-abort evidence is incomplete",
        "evidence_kind": evidence_kind,
        "runtime_eligible": False,
        "shadow_probe_allowed": False,
        "active_abort_allowed": False,
        "automatic_retry_allowed": False,
        "target_global_success_recall": target_recall,
        "search_rule": search_rule,
        "validation_margin": validation_margin,
        "confidence_alpha": confidence_alpha,
        "minimum_successes_for_noop_certificate": 0,
        "split_scope": split_scope,
        "gate_rounds": rounds,
        "budget_grid": budgets,
        "candidate_budget_count": 0,
        "evaluated_policy_count": 0,
        "feasible_candidate_count": 0,
        "provenance": provenance,
        "splits": {},
        "split_integrity": {},
        "selected_policy": {},
        "test_evaluation": {},
        "missing": [],
        "errors": [],
    }

    try:
        _validate_gate_inputs(rounds, budgets, target_recall, search_rule, confidence_alpha, split_scope)
        report["minimum_successes_for_noop_certificate"] = minimum_successes_for_noop_certificate(
            target_recall, confidence_alpha
        )
    except Exception as exc:
        report["errors"].append(str(exc))
        report["readiness"] = "error"
        report["decision"] = "reject_episode_early_abort"
        report["reason"] = "episode early-abort configuration is invalid"
        return report

    split_inputs = {
        "calibration": list(calibration_paths or []),
        "validation": list(validation_paths or []),
        "test": list(test_paths or []),
    }
    duplicate_input_paths = {
        split: len(paths) - len({_normalized_path(path) for path in paths})
        for split, paths in split_inputs.items()
    }
    trajectories = {}
    for split, paths in split_inputs.items():
        loaded, load_report = load_episode_trajectories(paths)
        trajectories[split] = loaded
        report["splits"][split] = _split_summary(loaded, load_report)
        report["errors"].extend(f"{split}: {error}" for error in load_report.get("errors", []))

    integrity = _split_integrity(trajectories, split_scope)
    integrity["duplicate_input_path_count"] = sum(duplicate_input_paths.values())
    integrity["duplicate_input_paths_by_split"] = duplicate_input_paths
    integrity["input_paths_unique"] = integrity["duplicate_input_path_count"] == 0
    integrity["independent_episode_sessions"] = all(
        len({episode.session_id for episode in trajectories[split] if episode.session_id})
        == len(trajectories[split])
        for split in trajectories
    )
    report["split_integrity"] = integrity
    provenance_complete = all(provenance.values())
    live_shape_complete = all(
        summary.get("requested_path_count", 0) > 0
        and summary.get("readable_path_count") == summary.get("requested_path_count")
        and summary.get("episode_count", 0) > 0
        and summary.get("complete_boundary_count") == summary.get("episode_count")
        and summary.get("connected_episode_count") == summary.get("episode_count")
        and summary.get("explicit_session_id_count") == summary.get("episode_count")
        and summary.get("connect_success_path_count") == summary.get("readable_path_count")
        and summary.get("explicit_connect_session_path_count") == summary.get("readable_path_count")
        and summary.get("distinct_session_count", 0) > 0
        for summary in report["splits"].values()
    )
    report["runtime_eligible"] = bool(
        evidence_kind == "live_trace"
        and provenance_complete
        and live_shape_complete
        and integrity.get("session_disjoint")
        and integrity.get("task_scope_valid")
        and integrity.get("input_paths_unique")
        and integrity.get("independent_episode_sessions")
    )
    if evidence_kind != "live_trace":
        report["missing"].append("live_trace_evidence")
    if not provenance_complete:
        report["missing"].append("fixed_runtime_provenance")
    if not live_shape_complete:
        report["missing"].append("complete_live_session_boundaries")
    if not integrity.get("session_disjoint"):
        report["missing"].append("disjoint_split_sessions")
    if not integrity.get("task_scope_valid"):
        report["missing"].append("disjoint_split_task_groups")
    if not integrity.get("input_paths_unique"):
        report["missing"].append("unique_split_input_paths")
    if not integrity.get("independent_episode_sessions"):
        report["missing"].append("one_episode_per_independent_session")

    calibration = trajectories["calibration"]
    validation = trajectories["validation"]
    test = trajectories["test"]
    calibration_successes = sum(1 for episode in calibration if episode.success)
    validation_successes = sum(1 for episode in validation if episode.success)
    test_successes = sum(1 for episode in test if episode.success)
    test_failures = sum(1 for episode in test if not episode.success)
    test_sessions = len({episode.session_id for episode in test if episode.session_id})
    count_requirements = {
        "calibration_successes": (calibration_successes, max(1, int(min_calibration_successes))),
        "validation_successes": (validation_successes, max(1, int(min_validation_successes))),
        "test_successes": (test_successes, max(1, int(min_test_successes))),
        "test_failures": (test_failures, max(1, int(min_test_failures))),
        "test_sessions": (test_sessions, max(1, int(min_test_sessions))),
    }
    report["evidence_requirements"] = {
        key: {"observed": observed, "required": required, "met": observed >= required}
        for key, (observed, required) in count_requirements.items()
    }
    for key, (observed, required) in count_requirements.items():
        if observed < required:
            report["missing"].append(f"{key}>={required}")

    candidate_count = len(budgets) ** len(rounds)
    report["candidate_budget_count"] = candidate_count
    if candidate_count > MAX_BUDGET_CANDIDATES:
        report["errors"].append(
            f"budget search has {candidate_count} candidates; maximum is {MAX_BUDGET_CANDIDATES}"
        )
    if report["errors"]:
        report["readiness"] = "error"
        report["decision"] = "reject_episode_early_abort"
        report["reason"] = "episode logs or budget search could not be evaluated"
        report["missing"] = sorted(set(report["missing"]))
        return report

    calibrated = {
        (round_index, budget): _calibrate_round(
            calibration, round_index, budget, confidence_alpha
        )
        for round_index in rounds
        for budget in budgets
    }
    feasible_count = 0
    selected = None
    seen_policies = set()
    for budget_vector in itertools.product(budgets, repeat=len(rounds)):
        selected_rounds = [
            dict(calibrated[(round_index, budget)])
            for round_index, budget in zip(rounds, budget_vector)
        ]
        policy_signature = tuple(
            (
                int(item.get("round") or 0),
                bool(item.get("active")),
                float(item.get("threshold")) if item.get("active") else None,
            )
            for item in selected_rounds
        )
        if policy_signature in seen_policies:
            continue
        seen_policies.add(policy_signature)
        validation_result = _simulate_cascade(validation, selected_rounds, confidence_alpha)
        if _candidate_feasible(
            validation_result,
            target_recall=target_recall,
            search_rule=search_rule,
            validation_margin=validation_margin,
        ):
            feasible_count += 1
            candidate = {
                "budgets": list(budget_vector),
                "rounds": selected_rounds,
                "validation": validation_result,
            }
            if selected is None or _candidate_rank(candidate) > _candidate_rank(selected):
                selected = candidate

    report["evaluated_policy_count"] = len(seen_policies)
    report["feasible_candidate_count"] = feasible_count
    if selected is not None:
        test_result = _simulate_cascade(test, selected["rounds"], confidence_alpha)
        report["selected_policy"] = {
            "budgets": selected["budgets"],
            "rounds": selected["rounds"],
            "active_round_count": sum(1 for item in selected["rounds"] if item.get("active")),
            "validation_evaluation": selected["validation"],
        }
        report["test_evaluation"] = test_result
        report["shadow_probe_allowed"] = bool(report["selected_policy"]["active_round_count"])
    else:
        report["missing"].append("feasible_global_recall_policy")

    selected_policy = report.get("selected_policy", {})
    test_result = report.get("test_evaluation", {})
    validation_result = selected_policy.get("validation_evaluation", {}) if isinstance(selected_policy, dict) else {}
    validation_certificate = float(validation_result.get("global_recall_lower_bound") or 0.0) >= target_recall
    test_certificate = float(test_result.get("global_recall_lower_bound") or 0.0) >= target_recall
    test_recall = float(test_result.get("global_success_recall") or 0.0)
    useful_test_abort = bool(
        int(test_result.get("failed_episode_abort_count") or 0) > 0
        and float(test_result.get("cost_savings_rate") or 0.0) > 0.0
    )
    active_allowed = bool(
        report["runtime_eligible"]
        and search_rule == "certificate"
        and validation_certificate
        and test_certificate
        and test_recall >= target_recall
        and useful_test_abort
        and selected_policy.get("active_round_count", 0) > 0
        and all(observed >= required for observed, required in count_requirements.values())
    )
    report["active_abort_allowed"] = active_allowed
    if search_rule != "certificate":
        report["missing"].append("certificate_search_rule")
    if selected_policy and not validation_certificate:
        report["missing"].append("validation_global_recall_certificate")
    if selected_policy and not test_certificate:
        report["missing"].append("test_global_recall_certificate")
    if selected_policy and test_recall < target_recall:
        report["missing"].append("test_global_recall_target")
    if selected_policy and not useful_test_abort:
        report["missing"].append("held_out_failed_episode_savings")

    if active_allowed:
        report["readiness"] = "approved"
        report["decision"] = "allow_episode_early_abort"
        report["reason"] = (
            "disjoint live evidence certifies global success recall and shows held-out failed-episode savings"
        )
    elif report["shadow_probe_allowed"]:
        report["readiness"] = "review"
        report["decision"] = "allow_shadow_episode_viability_probe"
        report["reason"] = "a candidate cascade exists but active termination is not evidence-qualified"
    else:
        report["readiness"] = "review"
        report["decision"] = "abstain_episode_early_abort"
        report["reason"] = "no recall-qualified cascade can safely abort episodes"
    report["missing"] = sorted(set(report["missing"]))
    report["gate_integrity_sha256"] = episode_abort_gate_integrity_hash(report)
    return report


def evaluate_episode_abort_runtime_gate(
    paths: list[str],
    requested_mode: str = "off",
    runtime_provenance: Optional[dict] = None,
) -> dict:
    """Resolve a saved gate into an effective off/shadow/active runtime mode."""
    requested_mode = str(requested_mode or "off").strip().lower()
    if requested_mode not in {"off", "shadow", "active"}:
        requested_mode = "off"
    runtime_provenance = {
        str(key): str(value or "").strip()
        for key, value in (runtime_provenance or {}).items()
    }
    report = {
        "type": "episode_early_abort_runtime_gate",
        "requested_mode": requested_mode,
        "effective_mode": "off",
        "gate_paths": list(paths or []),
        "gate_readiness": "not_required" if requested_mode == "off" else "missing",
        "signal_profile": SIGNAL_PROFILE,
        "selected_rounds": [],
        "provenance_match": False,
        "active_abort_allowed": False,
        "shadow_probe_allowed": False,
        "errors": [],
    }
    if requested_mode == "off":
        return report
    if len(paths or []) != 1:
        report["gate_readiness"] = "error" if paths else "missing"
        if paths:
            report["errors"].append("exactly one episode early-abort gate is required")
        return report
    path = paths[0]
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            gate = json.load(handle)
        validate_episode_abort_gate_payload(gate)
    except Exception as exc:
        report["gate_readiness"] = "error"
        report["errors"].append(f"{path}: {exc}")
        return report

    expected = gate.get("provenance", {}) if isinstance(gate.get("provenance", {}), dict) else {}
    compared_keys = ("planner_id", "action_backend", "verifier_id", "task_stream_id", "seed")
    provenance_match = all(
        str(expected.get(key) or "").strip()
        and str(expected.get(key) or "").strip() == str(runtime_provenance.get(key) or "").strip()
        for key in compared_keys
    )
    selected = gate.get("selected_policy", {}) if isinstance(gate.get("selected_policy", {}), dict) else {}
    report.update({
        "gate_readiness": str(gate.get("readiness") or "unknown").lower(),
        "signal_profile": str(gate.get("signal_profile") or ""),
        "selected_rounds": list(selected.get("rounds", []) or []),
        "provenance_match": provenance_match,
        "expected_provenance": {key: expected.get(key, "") for key in compared_keys},
        "runtime_provenance": {key: runtime_provenance.get(key, "") for key in compared_keys},
        "active_abort_allowed": bool(gate.get("active_abort_allowed")),
        "shadow_probe_allowed": bool(gate.get("shadow_probe_allowed")),
    })
    if not provenance_match:
        report["gate_readiness"] = "rejected"
        report["errors"].append("runtime provenance does not match calibrated gate controls")
        return report
    if requested_mode == "active":
        if gate.get("readiness") == "approved" and gate.get("active_abort_allowed") is True:
            report["effective_mode"] = "active"
        return report
    if requested_mode == "shadow" and gate.get("shadow_probe_allowed") is True:
        report["effective_mode"] = "shadow"
    return report


def load_episode_trajectories(paths: list[str]) -> tuple[list[EpisodeTrajectory], dict]:
    """Read goal-bounded trajectories from JSONL session logs."""
    trajectories = []
    report = {
        "requested_path_count": len(paths or []),
        "readable_path_count": 0,
        "connect_success_path_count": 0,
        "explicit_connect_session_path_count": 0,
        "source_logs": [],
        "errors": [],
    }
    for path in paths or []:
        try:
            events, content_sha256, byte_count = _read_jsonl_evidence(path)
            report["readable_path_count"] += 1
            report["source_logs"].append({
                "name": os.path.basename(str(path)),
                "path_fingerprint": hashlib.sha256(_normalized_path(path).encode("utf-8")).hexdigest()[:16],
                "content_sha256": content_sha256,
                "bytes": byte_count,
            })
            connect_success = any(
                _event_type(event) == "connect" and _event_data(event).get("success") is True
                for event in events
            )
            connected_sessions = {
                str(event.get("session") or "")
                for event in events
                if _event_type(event) == "connect"
                and _event_data(event).get("success") is True
                and event.get("session")
            }
            if connect_success:
                report["connect_success_path_count"] += 1
            if connected_sessions:
                report["explicit_connect_session_path_count"] += 1
            loaded = _episodes_from_events(events, path, connect_success)
            if connected_sessions:
                for episode in loaded:
                    episode.connect_success = episode.session_id in connected_sessions
            trajectories.extend(loaded)
        except Exception as exc:
            report["errors"].append(f"{path}: {exc}")
    return trajectories, report


def write_episode_early_abort_gate(report: dict, path: str):
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)


def episode_abort_gate_integrity_hash(gate: dict) -> str:
    """Hash the complete gate payload except its own integrity field."""
    payload = dict(gate or {})
    payload.pop("gate_integrity_sha256", None)
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _validate_gate_inputs(rounds, budgets, target, search_rule, alpha, split_scope):
    if not rounds:
        raise ValueError("at least one positive gate round is required")
    if not budgets:
        raise ValueError("at least one recall budget is required")
    if any(value < 0.5 or value > 1.0 for value in budgets):
        raise ValueError("recall budgets must be between 0.5 and 1.0")
    if not 0.5 < target < 1.0:
        raise ValueError("target recall must be between 0.5 and 1.0")
    if search_rule not in {"certificate", "margin"}:
        raise ValueError("search_rule must be certificate or margin")
    if not 0.0 < alpha < 1.0:
        raise ValueError("confidence alpha must be between zero and one")
    if split_scope not in {"held_out_session", "held_out_task"}:
        raise ValueError("split_scope must be held_out_session or held_out_task")


def validate_episode_abort_gate_payload(gate: dict):
    """Raise when a saved gate is structurally or internally inconsistent."""
    if not isinstance(gate, dict):
        raise ValueError("gate JSON must be an object")
    if gate.get("type") != GATE_TYPE or gate.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"episode early-abort gate must be {GATE_TYPE} schema {SCHEMA_VERSION}")
    if gate.get("signal_profile") != SIGNAL_PROFILE:
        raise ValueError("episode early-abort signal profile is unsupported")
    if gate.get("hidden_activation_claimed") is not False:
        raise ValueError("behavioral gate cannot claim hidden-activation evidence")
    selected = gate.get("selected_policy", {})
    rounds = selected.get("rounds", []) if isinstance(selected, dict) else []
    active_rounds = [item for item in rounds if isinstance(item, dict) and item.get("active")]
    if gate.get("shadow_probe_allowed") and not active_rounds:
        raise ValueError("shadow-enabled gate has no selected rounds")
    seen_rounds = set()
    for item in active_rounds:
        try:
            round_index = int(item.get("round"))
            threshold = float(item.get("threshold"))
        except (TypeError, ValueError) as exc:
            raise ValueError("active episode gate has invalid round or threshold") from exc
        if round_index < 1 or round_index in seen_rounds:
            raise ValueError("active episode gate rounds must be positive and unique")
        if not math.isfinite(threshold) or not 0.0 <= threshold <= 1.0:
            raise ValueError("active episode gate threshold must be within [0, 1]")
        seen_rounds.add(round_index)
    if int(selected.get("active_round_count") or 0) != len(active_rounds):
        raise ValueError("episode gate active round count is inconsistent")

    if gate.get("shadow_probe_allowed") or gate.get("active_abort_allowed"):
        expected_hash = str(gate.get("gate_integrity_sha256") or "")
        if not expected_hash or expected_hash != episode_abort_gate_integrity_hash(gate):
            raise ValueError("episode early-abort gate integrity hash is invalid")

    active_allowed = gate.get("active_abort_allowed") is True
    if not active_allowed:
        if gate.get("readiness") == "approved":
            raise ValueError("approved episode gate must allow active abort")
        return
    if gate.get("readiness") != "approved" or gate.get("decision") != "allow_episode_early_abort":
        raise ValueError("active episode gate readiness or decision is inconsistent")
    if gate.get("runtime_eligible") is not True or gate.get("evidence_kind") != "live_trace":
        raise ValueError("active episode gate lacks eligible live evidence")
    if gate.get("search_rule") != "certificate":
        raise ValueError("active episode gate must use certificate search")
    if gate.get("automatic_retry_allowed") is not False:
        raise ValueError("active episode gate cannot authorize automatic retries")
    try:
        target = float(gate.get("target_global_success_recall"))
    except (TypeError, ValueError) as exc:
        raise ValueError("active episode gate has invalid recall target") from exc
    if not 0.5 < target < 1.0:
        raise ValueError("active episode gate recall target is outside the supported range")
    validation = selected.get("validation_evaluation", {}) if isinstance(selected, dict) else {}
    test = gate.get("test_evaluation", {}) if isinstance(gate.get("test_evaluation", {}), dict) else {}
    if float(validation.get("global_recall_lower_bound") or 0.0) < target:
        raise ValueError("active episode gate validation certificate is below target")
    if float(test.get("global_recall_lower_bound") or 0.0) < target:
        raise ValueError("active episode gate held-out certificate is below target")
    if float(test.get("global_success_recall") or 0.0) < target:
        raise ValueError("active episode gate held-out recall is below target")
    if int(test.get("failed_episode_abort_count") or 0) < 1:
        raise ValueError("active episode gate has no held-out failed-episode abort")
    if float(test.get("cost_savings_rate") or 0.0) <= 0.0:
        raise ValueError("active episode gate has no held-out planner-round savings")
    integrity = gate.get("split_integrity", {}) if isinstance(gate.get("split_integrity", {}), dict) else {}
    for key in (
        "session_disjoint",
        "task_scope_valid",
        "input_paths_unique",
        "independent_episode_sessions",
    ):
        if integrity.get(key) is not True:
            raise ValueError(f"active episode gate split integrity failed: {key}")
    requirements = gate.get("evidence_requirements", {})
    if not isinstance(requirements, dict) or not requirements:
        raise ValueError("active episode gate has no evidence requirements")
    if any(not isinstance(item, dict) or item.get("met") is not True for item in requirements.values()):
        raise ValueError("active episode gate evidence requirements are not met")
    splits = gate.get("splits", {}) if isinstance(gate.get("splits", {}), dict) else {}
    for split in ("calibration", "validation", "test"):
        summary = splits.get(split, {}) if isinstance(splits.get(split, {}), dict) else {}
        episode_count = int(summary.get("episode_count") or 0)
        readable_paths = int(summary.get("readable_path_count") or 0)
        if episode_count < 1 or readable_paths < 1:
            raise ValueError(f"active episode gate {split} split is empty")
        if int(summary.get("complete_boundary_count") or 0) != episode_count:
            raise ValueError(f"active episode gate {split} boundaries are incomplete")
        if int(summary.get("connected_episode_count") or 0) != episode_count:
            raise ValueError(f"active episode gate {split} connect evidence is incomplete")
        if int(summary.get("explicit_session_id_count") or 0) != episode_count:
            raise ValueError(f"active episode gate {split} session ids are implicit")
        if int(summary.get("connect_success_path_count") or 0) != readable_paths:
            raise ValueError(f"active episode gate {split} paths lack connect success")
        if int(summary.get("explicit_connect_session_path_count") or 0) != readable_paths:
            raise ValueError(f"active episode gate {split} connect session ids are implicit")
        manifests = summary.get("source_logs", []) if isinstance(summary.get("source_logs", []), list) else []
        if len(manifests) != readable_paths:
            raise ValueError(f"active episode gate {split} source manifest is incomplete")
        if any(
            not isinstance(item, dict)
            or len(str(item.get("path_fingerprint") or "")) != 16
            or len(str(item.get("content_sha256") or "")) != 64
            or int(item.get("bytes") or 0) <= 0
            for item in manifests
        ):
            raise ValueError(f"active episode gate {split} source manifest is invalid")
    provenance = gate.get("provenance", {}) if isinstance(gate.get("provenance", {}), dict) else {}
    if not all(str(provenance.get(key) or "").strip() for key in (
        "planner_id", "action_backend", "verifier_id", "task_stream_id", "seed"
    )):
        raise ValueError("active episode gate provenance is incomplete")


def _calibrate_round(
    calibration: list[EpisodeTrajectory],
    round_index: int,
    recall_budget: float,
    alpha: float,
) -> dict:
    item = {
        "round": int(round_index),
        "recall_budget": float(recall_budget),
        "active": False,
        "threshold": None,
        "successful_calibration_exposure": 0,
        "calibration_survivor_count": 0,
        "calibration_recall_lower_bound": 0.0,
        "reason": "gate_disabled",
    }
    if recall_budget >= 1.0:
        item["reason"] = "budget_one_disables_gate"
        return item
    scores = []
    for episode in calibration:
        if not episode.success:
            continue
        scored = episode.score_at_round(round_index)
        if scored is not None:
            scores.append(float(scored["score"]))
    scores.sort()
    item["successful_calibration_exposure"] = len(scores)
    if not scores:
        item["reason"] = "no_successful_calibration_exposure"
        return item
    maximum_lower_bound = clopper_pearson_lower_bound(len(scores), len(scores), alpha)
    if maximum_lower_bound < recall_budget:
        item["reason"] = "calibration_sample_cannot_support_budget"
        item["calibration_recall_lower_bound"] = round(maximum_lower_bound, 6)
        return item
    low = 1
    high = len(scores)
    while low < high:
        middle = (low + high) // 2
        if clopper_pearson_lower_bound(middle, len(scores), alpha) >= recall_budget:
            high = middle
        else:
            low = middle + 1
    required_survivors = low
    threshold = scores[required_survivors - 1]
    actual_survivors = sum(1 for score in scores if score <= threshold)
    lower_bound = clopper_pearson_lower_bound(actual_survivors, len(scores), alpha)
    item.update({
        "active": True,
        "threshold": threshold,
        "calibration_survivor_count": actual_survivors,
        "calibration_recall_lower_bound": round(lower_bound, 6),
        "reason": "clopper_pearson_threshold",
    })
    return item


def _simulate_cascade(episodes: list[EpisodeTrajectory], selected_rounds: list[dict], alpha: float) -> dict:
    successful_count = sum(1 for episode in episodes if episode.success)
    successful_survivors = 0
    aborted_count = 0
    failed_aborts = 0
    successful_false_aborts = 0
    saved_cycles = 0
    total_cycles = sum(max(0, episode.cycle_count) for episode in episodes)
    abort_round_counts = {}
    for episode in episodes:
        aborted_round = None
        for gate in selected_rounds:
            if not gate.get("active"):
                continue
            round_index = int(gate.get("round") or 0)
            scored = episode.score_at_round(round_index)
            if scored is None:
                continue
            threshold = float(gate.get("threshold"))
            if float(scored.get("score") or 0.0) > threshold:
                aborted_round = round_index
                break
        if aborted_round is None:
            if episode.success:
                successful_survivors += 1
            continue
        aborted_count += 1
        abort_round_counts[str(aborted_round)] = abort_round_counts.get(str(aborted_round), 0) + 1
        saved_cycles += max(0, episode.cycle_count - aborted_round)
        if episode.success:
            successful_false_aborts += 1
        else:
            failed_aborts += 1
    recall = _ratio(successful_survivors, successful_count)
    lower = clopper_pearson_lower_bound(successful_survivors, successful_count, alpha) if successful_count else 0.0
    return {
        "episode_count": len(episodes),
        "successful_episode_count": successful_count,
        "successful_survivor_count": successful_survivors,
        "successful_false_abort_count": successful_false_aborts,
        "global_success_recall": round(recall, 6),
        "global_recall_lower_bound": round(lower, 6),
        "episode_abort_count": aborted_count,
        "failed_episode_abort_count": failed_aborts,
        "abort_round_counts": abort_round_counts,
        "cost_proxy": "planner_rounds",
        "baseline_planner_rounds": total_cycles,
        "saved_planner_rounds": saved_cycles,
        "cost_savings_rate": round(_ratio(saved_cycles, total_cycles), 6),
    }


def _candidate_feasible(result: dict, target_recall: float, search_rule: str, validation_margin: float) -> bool:
    if int(result.get("successful_episode_count") or 0) <= 0:
        return False
    if search_rule == "certificate":
        return float(result.get("global_recall_lower_bound") or 0.0) >= target_recall
    required = min(1.0, target_recall + validation_margin)
    return float(result.get("global_success_recall") or 0.0) >= required


def _candidate_rank(candidate: dict) -> tuple:
    validation = candidate.get("validation", {}) if isinstance(candidate.get("validation", {}), dict) else {}
    return (
        float(validation.get("cost_savings_rate") or 0.0),
        float(validation.get("global_success_recall") or 0.0),
        -sum(1 for gate in candidate.get("rounds", []) if gate.get("active")),
    )


def _split_summary(episodes: list[EpisodeTrajectory], load_report: dict) -> dict:
    return {
        "requested_path_count": int(load_report.get("requested_path_count") or 0),
        "readable_path_count": int(load_report.get("readable_path_count") or 0),
        "connect_success_path_count": int(load_report.get("connect_success_path_count") or 0),
        "explicit_connect_session_path_count": int(load_report.get("explicit_connect_session_path_count") or 0),
        "episode_count": len(episodes),
        "successful_episode_count": sum(1 for episode in episodes if episode.success),
        "failed_episode_count": sum(1 for episode in episodes if not episode.success),
        "complete_boundary_count": sum(1 for episode in episodes if episode.complete_boundary),
        "connected_episode_count": sum(1 for episode in episodes if episode.connect_success),
        "explicit_session_id_count": sum(1 for episode in episodes if episode.explicit_session_id),
        "distinct_session_count": len({episode.session_id for episode in episodes if episode.session_id}),
        "distinct_task_group_count": len({episode.goal_fingerprint for episode in episodes if episode.goal_fingerprint}),
        "source_logs": list(load_report.get("source_logs", []) or []),
    }


def _split_integrity(splits: dict[str, list[EpisodeTrajectory]], split_scope: str) -> dict:
    names = ("calibration", "validation", "test")
    session_sets = {
        name: {episode.session_id for episode in splits.get(name, []) if episode.session_id}
        for name in names
    }
    task_sets = {
        name: {episode.goal_fingerprint for episode in splits.get(name, []) if episode.goal_fingerprint}
        for name in names
    }
    session_overlap = sorted(
        set().union(*(
            session_sets[left] & session_sets[right]
            for index, left in enumerate(names)
            for right in names[index + 1:]
        ))
    )
    task_overlap = sorted(
        set().union(*(
            task_sets[left] & task_sets[right]
            for index, left in enumerate(names)
            for right in names[index + 1:]
        ))
    )
    return {
        "session_disjoint": not session_overlap,
        "session_overlap_count": len(session_overlap),
        "task_group_disjoint": not task_overlap,
        "task_group_overlap_count": len(task_overlap),
        "task_scope_valid": split_scope == "held_out_session" or not task_overlap,
    }


def _episodes_from_events(events: list[dict], path: str, connect_success: bool) -> list[EpisodeTrajectory]:
    episodes = []
    active = None
    ordinal = 0
    fallback_session = os.path.splitext(os.path.basename(path))[0]
    for event in events:
        event_type = _event_type(event)
        if event_type == "goal_start":
            if active is not None:
                episodes.append(_trajectory_from_segment(active, path, connect_success, False, ordinal))
                ordinal += 1
            active = [event]
            continue
        if active is None:
            continue
        active.append(event)
        if event_type == "goal_end":
            episodes.append(_trajectory_from_segment(active, path, connect_success, True, ordinal))
            ordinal += 1
            active = None
    if active is not None:
        episodes.append(_trajectory_from_segment(active, path, connect_success, False, ordinal))
    for episode in episodes:
        if not episode.session_id:
            episode.session_id = fallback_session
    return episodes


def _trajectory_from_segment(events, path, connect_success, complete_boundary, ordinal):
    start_data = _event_data(events[0]) if events else {}
    goal = str(start_data.get("goal") or "")
    session = next((str(event.get("session") or "") for event in events if event.get("session")), "")
    explicit_session_id = bool(session)
    cycle_count = sum(1 for event in events if _event_type(event) == "plan")
    terminal = _event_data(events[-1]) if events else {}
    result = terminal.get("result", {}) if isinstance(terminal.get("result", {}), dict) else {}
    if not cycle_count:
        try:
            cycle_count = int(result.get("cycles") or 0)
        except (TypeError, ValueError):
            cycle_count = 0
    success = bool(result.get("completed") is True or result.get("success") is True)
    goal_fingerprint = hashlib.sha256(_normalize_goal(goal).encode("utf-8")).hexdigest()[:16]
    identity = f"{os.path.abspath(path)}|{session}|{ordinal}|{goal_fingerprint}"
    episode_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
    return EpisodeTrajectory(
        episode_id=episode_id,
        session_id=session,
        goal_fingerprint=goal_fingerprint,
        success=success,
        cycle_count=max(0, cycle_count),
        events=list(events),
        source_path=path,
        complete_boundary=bool(complete_boundary),
        connect_success=bool(connect_success),
        explicit_session_id=explicit_session_id,
    )


def _episode_prefix_after_round(events: list[dict], round_index: int) -> list[dict]:
    plan_seen = 0
    end_index = None
    for index, event in enumerate(events):
        if _event_type(event) != "plan":
            continue
        plan_seen += 1
        if plan_seen == round_index + 1:
            end_index = index
            break
    if plan_seen <= round_index and end_index is None:
        return []
    return events[:end_index] if end_index is not None else list(events)


def _current_episode_events(events: list[dict]) -> list[dict]:
    start = None
    for index, event in enumerate(events):
        if _event_type(event) == "goal_start":
            start = index
        elif _event_type(event) == "goal_end" and start is not None:
            start = None
    return events[start:] if start is not None else []


def _state_progress(events: list[dict]) -> bool:
    observations = [_event_data(event) for event in events if _event_type(event) == "observation"]
    if len(observations) < 2:
        return False
    first = observations[0]
    last = observations[-1]
    if _inventory_snapshot(first) != _inventory_snapshot(last):
        return True
    first_pos = _position(first)
    last_pos = _position(last)
    if first_pos and last_pos:
        distance = math.sqrt(sum((last_pos[index] - first_pos[index]) ** 2 for index in range(3)))
        if distance >= 1.0:
            return True
    return False


def _inventory_snapshot(observation: dict) -> tuple:
    inventory = observation.get("inventory", {}) if isinstance(observation, dict) else {}
    if not isinstance(inventory, dict):
        return tuple()
    return tuple(sorted((str(key), _safe_float(value)) for key, value in inventory.items()))


def _position(observation: dict) -> Optional[tuple[float, float, float]]:
    position = observation.get("position", {}) if isinstance(observation, dict) else {}
    if not isinstance(position, dict):
        return None
    try:
        return tuple(float(position.get(axis, 0.0)) for axis in ("x", "y", "z"))
    except (TypeError, ValueError):
        return None


def _verification_rejected(event: dict) -> bool:
    data = _event_data(event)
    verification = data.get("verification", {}) if isinstance(data.get("verification", {}), dict) else {}
    status = str(verification.get("status") or data.get("status") or "").strip().lower()
    return status in {"reject", "rejected", "invalid", "failed", "failure"}


def _goal_verification_rejected(event: dict) -> bool:
    data = _event_data(event)
    context = data.get("context", {}) if isinstance(data.get("context", {}), dict) else {}
    if context.get("accepted") is False:
        return True
    status = str(data.get("status") or "").strip().lower()
    return status in {"reject", "rejected", "failed", "failure", "not_achieved"}


def _result_succeeded(result: dict) -> bool:
    if result.get("success") is True:
        return True
    status = str(result.get("status") or "").strip().lower()
    return status in {"ok", "success", "succeeded", "complete", "completed"}


def _action_signature(action: dict) -> str:
    payload = action if isinstance(action, dict) else {}
    try:
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    except Exception:
        return str(payload)


def _read_jsonl_evidence(path: str) -> tuple[list[dict], str, int]:
    with open(path, "rb") as handle:
        raw = handle.read()
    content_sha256 = hashlib.sha256(raw).hexdigest()
    text = raw.decode("utf-8-sig")
    events = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"line {line_number} is not a JSON object")
        events.append(value)
    return events, content_sha256, len(raw)


def _event_type(event: dict) -> str:
    return str(event.get("type") or "") if isinstance(event, dict) else ""


def _event_data(event: dict) -> dict:
    data = event.get("data", {}) if isinstance(event, dict) else {}
    return data if isinstance(data, dict) else {}


def _normalize_goal(goal: str) -> str:
    return " ".join(str(goal or "").strip().lower().split())


def _normalized_path(path: str) -> str:
    return os.path.normcase(os.path.abspath(str(path or "")))


def _ratio(numerator, denominator) -> float:
    try:
        denominator = float(denominator)
        return float(numerator) / denominator if denominator else 0.0
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0


def _safe_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _binomial_upper_tail(trials: int, successes: int, probability: float) -> float:
    if successes <= 0:
        return 1.0
    if successes > trials:
        return 0.0
    if probability <= 0.0:
        return 0.0
    if probability >= 1.0:
        return 1.0
    log_p = math.log(probability)
    log_q = math.log1p(-probability)
    logs = [
        math.lgamma(trials + 1)
        - math.lgamma(value + 1)
        - math.lgamma(trials - value + 1)
        + value * log_p
        + (trials - value) * log_q
        for value in range(successes, trials + 1)
    ]
    largest = max(logs)
    return min(1.0, math.exp(largest) * sum(math.exp(value - largest) for value in logs))
