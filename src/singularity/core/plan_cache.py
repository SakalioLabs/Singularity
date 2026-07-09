"""Plan-transition cache inspired by AgenticCache.

The cache is intentionally conservative: it can reuse approved offline plan
transitions when the goal, previous-plan signature, and compact world-state
features match, but it does not bypass action verification or goal verification.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
from dataclasses import dataclass, field

from singularity.core.memory_policy import promptware_threat_flags


START_PLAN_SIGNATURE = "START"


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_text(value: str) -> str:
    text = re.sub(r"[^a-z0-9_:/.-]+", " ", str(value or "").lower()).strip()
    return re.sub(r"\s+", " ", text)


def _stable_hash(value) -> str:
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def goal_signature(goal: str) -> str:
    return _stable_hash(_normalize_text(goal))


def _count_bucket(value) -> str:
    amount = _safe_int(value, 0)
    if amount <= 0:
        return "0"
    if amount == 1:
        return "1"
    if amount <= 4:
        return "2-4"
    if amount <= 16:
        return "5-16"
    return "17+"


def _iter_named_counts(value):
    if isinstance(value, dict):
        for key, count in value.items():
            name = _normalize_text(key)
            if name:
                yield name, count
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                name = _normalize_text(item.get("name") or item.get("type") or item.get("item"))
                count = item.get("count", 1)
            else:
                name = _normalize_text(item)
                count = 1
            if name:
                yield name, count


def _iter_named_values(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if isinstance(child, (list, dict)):
                yield from _iter_named_values(child)
            else:
                name = _normalize_text(child or key)
                if name:
                    yield name
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                name = _normalize_text(item.get("name") or item.get("type") or item.get("block") or item.get("entity"))
            else:
                name = _normalize_text(item)
            if name:
                yield name


def state_features(world_state: dict | None) -> list[str]:
    """Return compact, prompt-safe state features for cache matching."""
    state = world_state if isinstance(world_state, dict) else {}
    features: set[str] = set()

    for name, count in _iter_named_counts(state.get("inventory", {})):
        features.add(f"inv:{name}:{_count_bucket(count)}")
        features.add(f"has:{name}")

    for key in ("nearby_blocks", "visible_blocks", "blocks"):
        for name in _iter_named_values(state.get(key, [])):
            features.add(f"block:{name}")

    for key in ("nearby_entities", "visible_entities", "entities"):
        for name in _iter_named_values(state.get(key, [])):
            features.add(f"entity:{name}")

    vision = state.get("vision") if isinstance(state.get("vision"), dict) else {}
    for key in ("grounded_resources", "resources", "dangers", "landmarks"):
        for name in _iter_named_values(vision.get(key, [])):
            features.add(f"vision:{key}:{name}")

    for key in ("biome", "dimension", "weather", "time_of_day"):
        value = _normalize_text(state.get(key, ""))
        if value:
            features.add(f"{key}:{value}")

    health = state.get("health")
    if health is not None:
        amount = _safe_float(health, 20.0)
        if amount <= 4:
            features.add("health:critical")
        elif amount <= 10:
            features.add("health:low")
        else:
            features.add("health:ok")

    position = state.get("position") if isinstance(state.get("position"), dict) else {}
    if position:
        x = _safe_float(position.get("x"), 0.0)
        z = _safe_float(position.get("z"), 0.0)
        features.add(f"pos_grid:{int(x // 16)}:{int(z // 16)}")

    return sorted(features)


def state_signature(world_state: dict | None) -> str:
    return _stable_hash(state_features(world_state))


def action_signature(action: dict) -> str:
    if not isinstance(action, dict):
        return "invalid"
    params = action.get("parameters", {}) if isinstance(action.get("parameters", {}), dict) else {}
    compact = {
        "type": _normalize_text(action.get("type", "")),
        "item": _normalize_text(params.get("item", "")),
        "block": _normalize_text(params.get("block", "")),
        "target": _normalize_text(params.get("target", "")),
        "entity": _normalize_text(params.get("entity", "")),
    }
    return _stable_hash({key: value for key, value in compact.items() if value})


def plan_signature(plan: dict | None) -> str:
    plan = plan if isinstance(plan, dict) else {}
    actions = [action_signature(action) for action in (plan.get("actions", []) or []) if isinstance(action, dict)]
    subtasks = [
        _normalize_text(item.get("title") or item.get("type") or "")
        for item in (plan.get("subtasks", []) or [])
        if isinstance(item, dict)
    ]
    compact = {
        "status": _normalize_text(plan.get("status", "")),
        "actions": actions[:8],
        "subtasks": subtasks[:8],
    }
    return _stable_hash(compact)


def sanitize_plan(plan: dict | None, max_actions: int = 8, max_subtasks: int = 8) -> dict:
    plan = plan if isinstance(plan, dict) else {}
    sanitized = {
        "status": str(plan.get("status") or "planning")[:40],
        "reasoning": str(plan.get("reasoning") or "")[:500],
        "subtasks": [],
        "actions": [],
    }
    for item in (plan.get("subtasks", []) or [])[:max_subtasks]:
        if not isinstance(item, dict):
            continue
        sanitized["subtasks"].append({
            "title": str(item.get("title") or item.get("type") or "unnamed")[:160],
            "type": str(item.get("type") or "general")[:80],
            "priority": _safe_int(item.get("priority", 3), 3),
            "success_criteria": item.get("success_criteria", {}) if isinstance(item.get("success_criteria", {}), dict) else {},
            "preconditions": item.get("preconditions", {}) if isinstance(item.get("preconditions", {}), dict) else {},
            "depends_on": [str(dep)[:160] for dep in (item.get("depends_on", []) or []) if isinstance(dep, str)][:8],
            "opportunity_triggers": [str(dep)[:80] for dep in (item.get("opportunity_triggers", []) or []) if isinstance(dep, str)][:8],
            "tags": [str(tag)[:80] for tag in (item.get("tags", []) or []) if isinstance(tag, str)][:8],
            "assigned_skill": str(item.get("assigned_skill") or "")[:120],
            "rationale": str(item.get("rationale") or "")[:240],
        })
    for action in (plan.get("actions", []) or [])[:max_actions]:
        if not isinstance(action, dict):
            continue
        params = action.get("parameters", {}) if isinstance(action.get("parameters", {}), dict) else {}
        clean_params = {}
        for key, value in params.items():
            if isinstance(value, (str, int, float, bool)) or value is None:
                clean_params[str(key)[:80]] = value
            elif isinstance(value, list):
                clean_params[str(key)[:80]] = [
                    item for item in value[:8]
                    if isinstance(item, (str, int, float, bool)) or item is None
                ]
        sanitized["actions"].append({
            "type": str(action.get("type") or "")[:80],
            "parameters": clean_params,
        })
    return sanitized


def _plan_promptware_flags(plan: dict) -> list[str]:
    text = json.dumps(plan, ensure_ascii=False, sort_keys=True, default=str)[:6000]
    return promptware_threat_flags(text)


def _jaccard(left: list[str], right: list[str]) -> float:
    a = set(left or [])
    b = set(right or [])
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return round(len(a & b) / len(a | b), 3)


def _load_session_events(path: str) -> list[dict]:
    events = []
    with open(path, "r", encoding="utf-8-sig") as f:
        text = f.read().strip()
    if not text:
        return events
    if text.startswith("["):
        payload = json.loads(text)
        return [item for item in payload if isinstance(item, dict)]
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            events.append(item)
    return events


def _event_data(event: dict) -> dict:
    data = event.get("data", {}) if isinstance(event.get("data", {}), dict) else {}
    return data


def _action_succeeded(event: dict) -> bool | None:
    data = _event_data(event)
    result = data.get("result", {}) if isinstance(data.get("result", {}), dict) else {}
    if "success" in result:
        return bool(result.get("success"))
    return None


def _action_verification_rejected(event: dict) -> bool:
    data = _event_data(event)
    verification = data.get("verification", {}) if isinstance(data.get("verification", {}), dict) else {}
    return str(verification.get("status") or "").lower() == "reject"


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 3) if denominator else 0.0


def _load_json_report(path: str) -> dict:
    with open(path, "r", encoding="utf-8-sig") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise ValueError("report JSON must be an object")
    return payload


def build_plan_transition_cache_report(
    session_log_paths: list[str],
    min_support: int = 1,
    min_success_rate: float = 0.6,
    max_entries: int = 200,
) -> dict:
    """Mine successful plan transitions from session logs for warm-start cache use."""
    report = {
        "type": "plan_transition_cache_report",
        "readiness": "review",
        "decision": "hold_plan_transition_cache",
        "reason": "no approved plan transitions found",
        "source": "AgenticCache-inspired offline prefill",
        "session_log_paths": list(session_log_paths or []),
        "session_log_count": 0,
        "plan_event_count": 0,
        "transition_candidate_count": 0,
        "accepted_entry_count": 0,
        "rejected_entry_count": 0,
        "promptware_threat_count": 0,
        "min_support": max(1, _safe_int(min_support, 1)),
        "min_success_rate": max(0.0, min(1.0, _safe_float(min_success_rate, 0.6))),
        "max_entries": max(1, _safe_int(max_entries, 200)),
        "entries": [],
        "policy_hints": [
            "enable_plan_transition_cache_for_repeated_contexts",
            "keep_action_verification_on_cached_plans",
            "treat_cache_misses_as_normal_llm_planning",
        ],
        "errors": [],
    }
    groups: dict[str, dict] = {}

    def finalize(pending: dict | None):
        if not pending:
            return
        actions_seen = pending.get("action_success_count", 0) + pending.get("action_failure_count", 0)
        success = False
        failure = False
        if pending.get("goal_success") is True:
            success = True
        elif pending.get("goal_success") is False and actions_seen:
            failure = True
        elif pending.get("action_failure_count", 0):
            failure = True
        elif pending.get("action_success_count", 0):
            success = True

        key = pending["key"]
        group = groups.setdefault(key, {
            **{k: pending[k] for k in (
                "goal",
                "goal_signature",
                "previous_plan_signature",
                "state_signature",
                "state_features",
                "plan_signature",
                "plan",
            )},
            "support_count": 0,
            "success_count": 0,
            "failure_count": 0,
            "neutral_count": 0,
            "action_success_count": 0,
            "action_failure_count": 0,
            "source_logs": set(),
        })
        group["support_count"] += 1
        group["success_count"] += 1 if success else 0
        group["failure_count"] += 1 if failure else 0
        group["neutral_count"] += 1 if not success and not failure else 0
        group["action_success_count"] += pending.get("action_success_count", 0)
        group["action_failure_count"] += pending.get("action_failure_count", 0)
        group["source_logs"].add(pending["source_log"])

    for path in session_log_paths or []:
        try:
            events = _load_session_events(path)
            report["session_log_count"] += 1
        except Exception as exc:
            report["errors"].append(f"{path}: {exc}")
            continue
        current_goal = ""
        last_observation = {}
        previous_plan_sig = START_PLAN_SIGNATURE
        pending = None
        for event in events:
            event_type = str(event.get("type") or "")
            data = _event_data(event)
            if event_type == "goal_start":
                finalize(pending)
                pending = None
                current_goal = str(data.get("goal") or "")
                previous_plan_sig = START_PLAN_SIGNATURE
            elif event_type == "observation":
                last_observation = data
            elif event_type == "plan":
                finalize(pending)
                plan = sanitize_plan(data)
                features = state_features(last_observation)
                plan_sig = plan_signature(plan)
                pending = {
                    "goal": current_goal,
                    "goal_signature": goal_signature(current_goal),
                    "previous_plan_signature": previous_plan_sig,
                    "state_signature": _stable_hash(features),
                    "state_features": features,
                    "plan_signature": plan_sig,
                    "plan": plan,
                    "key": _stable_hash({
                        "goal": goal_signature(current_goal),
                        "previous": previous_plan_sig,
                        "state": _stable_hash(features),
                        "plan": plan_sig,
                    }),
                    "source_log": path,
                    "action_success_count": 0,
                    "action_failure_count": 0,
                    "goal_success": None,
                }
                previous_plan_sig = plan_sig
                report["plan_event_count"] += 1
            elif event_type == "action" and pending:
                succeeded = _action_succeeded(event)
                if succeeded is True:
                    pending["action_success_count"] += 1
                elif succeeded is False:
                    pending["action_failure_count"] += 1
            elif event_type == "goal_end":
                result = data.get("result", {}) if isinstance(data.get("result", {}), dict) else {}
                if pending and "completed" in result:
                    pending["goal_success"] = bool(result.get("completed"))
                finalize(pending)
                pending = None
        finalize(pending)

    entries = []
    for key, group in groups.items():
        support = _safe_int(group.get("support_count"), 0)
        success = _safe_int(group.get("success_count"), 0)
        failure = _safe_int(group.get("failure_count"), 0)
        denominator = success + failure
        success_rate = round(success / denominator, 3) if denominator else 0.0
        support_score = min(1.0, support / max(1, report["min_support"] * 2))
        confidence = round((0.65 * success_rate) + (0.35 * support_score), 3)
        flags = _plan_promptware_flags(group["plan"])
        accepted = (
            support >= report["min_support"]
            and success_rate >= report["min_success_rate"]
            and bool(group["plan"].get("actions"))
            and not flags
        )
        entry = {
            "id": key,
            "goal": group["goal"],
            "goal_signature": group["goal_signature"],
            "previous_plan_signature": group["previous_plan_signature"],
            "state_signature": group["state_signature"],
            "state_features": group["state_features"][:80],
            "plan_signature": group["plan_signature"],
            "plan": group["plan"],
            "support_count": support,
            "success_count": success,
            "failure_count": failure,
            "neutral_count": _safe_int(group.get("neutral_count"), 0),
            "success_rate": success_rate,
            "confidence": confidence,
            "action_success_count": _safe_int(group.get("action_success_count"), 0),
            "action_failure_count": _safe_int(group.get("action_failure_count"), 0),
            "source_logs": sorted(group.get("source_logs", []))[:12],
            "promptware_flags": flags,
            "promptware_threat_count": len(flags),
            "accepted_for_runtime": accepted,
        }
        entries.append(entry)
        report["promptware_threat_count"] += len(flags)

    entries.sort(key=lambda item: (item["accepted_for_runtime"], item["confidence"], item["support_count"]), reverse=True)
    report["transition_candidate_count"] = len(entries)
    report["accepted_entry_count"] = sum(1 for item in entries if item["accepted_for_runtime"])
    report["rejected_entry_count"] = len(entries) - report["accepted_entry_count"]
    report["entries"] = entries[:report["max_entries"]]

    if report["errors"]:
        report["readiness"] = "error" if not report["accepted_entry_count"] else "review"
        report["decision"] = "hold_plan_transition_cache"
        report["reason"] = "some session logs could not be loaded"
    elif report["accepted_entry_count"]:
        report["readiness"] = "approved"
        report["decision"] = "allow_plan_transition_cache_runtime_use"
        report["reason"] = "approved plan transitions have enough successful support for runtime cache use"
    else:
        report["readiness"] = "review"
        report["decision"] = "hold_plan_transition_cache"
        report["reason"] = "plan transitions need more successful action evidence before runtime cache use"
    return report


def build_plan_cache_runtime_report(
    session_log_paths: list[str],
    min_cache_hits: int = 1,
    max_rejected_action_rate: float = 0.0,
    max_action_failure_rate: float = 0.3,
) -> dict:
    """Audit actual runtime cache hits before promoting cache use."""
    report = {
        "type": "plan_cache_runtime_report",
        "readiness": "review",
        "decision": "hold_plan_cache_runtime_use",
        "reason": "no runtime cache hits found",
        "session_log_paths": list(session_log_paths or []),
        "session_log_count": 0,
        "plan_cache_hit_count": 0,
        "plan_cache_miss_count": 0,
        "plan_cache_hit_rate": 0.0,
        "cached_plan_event_count": 0,
        "post_hit_action_count": 0,
        "post_hit_action_success_count": 0,
        "post_hit_action_failure_count": 0,
        "post_hit_action_failure_rate": 0.0,
        "post_hit_action_verification_reject_count": 0,
        "post_hit_action_verification_reject_rate": 0.0,
        "post_hit_goal_completed_count": 0,
        "min_cache_hits": max(0, _safe_int(min_cache_hits, 1)),
        "max_rejected_action_rate": max(0.0, min(1.0, _safe_float(max_rejected_action_rate, 0.0))),
        "max_action_failure_rate": max(0.0, min(1.0, _safe_float(max_action_failure_rate, 0.3))),
        "entry_hit_counts": {},
        "hit_examples": [],
        "errors": [],
    }

    def finalize(active: dict | None):
        if not active:
            return
        report["post_hit_action_count"] += active.get("action_count", 0)
        report["post_hit_action_success_count"] += active.get("action_success_count", 0)
        report["post_hit_action_failure_count"] += active.get("action_failure_count", 0)
        report["post_hit_action_verification_reject_count"] += active.get("verification_reject_count", 0)
        if active.get("goal_completed"):
            report["post_hit_goal_completed_count"] += 1
        if active.get("cached_plan_seen"):
            report["cached_plan_event_count"] += 1
        if len(report["hit_examples"]) < 12:
            report["hit_examples"].append({
                "entry_id": active.get("entry_id", ""),
                "goal": active.get("goal", ""),
                "confidence": active.get("confidence", 0.0),
                "state_similarity": active.get("state_similarity", 0.0),
                "action_count": active.get("action_count", 0),
                "action_failure_count": active.get("action_failure_count", 0),
                "verification_reject_count": active.get("verification_reject_count", 0),
                "goal_completed": bool(active.get("goal_completed", False)),
            })

    for path in session_log_paths or []:
        try:
            events = _load_session_events(path)
            report["session_log_count"] += 1
        except Exception as exc:
            report["errors"].append(f"{path}: {exc}")
            continue
        active_hit = None
        for event in events:
            event_type = str(event.get("type") or "")
            data = _event_data(event)
            if event_type == "plan_cache_hit":
                finalize(active_hit)
                entry_id = str(data.get("entry_id") or "")
                report["plan_cache_hit_count"] += 1
                if entry_id:
                    counts = report["entry_hit_counts"]
                    counts[entry_id] = counts.get(entry_id, 0) + 1
                active_hit = {
                    "entry_id": entry_id,
                    "goal": str(data.get("goal") or "")[:160],
                    "confidence": _safe_float(data.get("confidence"), 0.0),
                    "state_similarity": _safe_float(data.get("state_similarity"), 0.0),
                    "action_count": 0,
                    "action_success_count": 0,
                    "action_failure_count": 0,
                    "verification_reject_count": 0,
                    "goal_completed": False,
                    "cached_plan_seen": False,
                }
            elif event_type == "plan_cache_miss":
                finalize(active_hit)
                active_hit = None
                report["plan_cache_miss_count"] += 1
            elif event_type == "plan" and active_hit:
                if str(data.get("source") or "") == "plan_transition_cache" or data.get("cache_entry_id"):
                    active_hit["cached_plan_seen"] = True
            elif event_type == "action_verification" and active_hit:
                if _action_verification_rejected(event):
                    active_hit["verification_reject_count"] += 1
            elif event_type == "action" and active_hit:
                succeeded = _action_succeeded(event)
                active_hit["action_count"] += 1
                if succeeded is True:
                    active_hit["action_success_count"] += 1
                elif succeeded is False:
                    active_hit["action_failure_count"] += 1
            elif event_type == "goal_end" and active_hit:
                result = data.get("result", {}) if isinstance(data.get("result", {}), dict) else {}
                active_hit["goal_completed"] = bool(result.get("completed", False))
                finalize(active_hit)
                active_hit = None
        finalize(active_hit)

    total_queries = report["plan_cache_hit_count"] + report["plan_cache_miss_count"]
    report["plan_cache_hit_rate"] = _ratio(report["plan_cache_hit_count"], total_queries)
    report["post_hit_action_failure_rate"] = _ratio(
        report["post_hit_action_failure_count"],
        report["post_hit_action_count"],
    )
    report["post_hit_action_verification_reject_rate"] = _ratio(
        report["post_hit_action_verification_reject_count"],
        report["post_hit_action_count"],
    )

    if report["errors"]:
        report["readiness"] = "error" if not report["plan_cache_hit_count"] else "review"
        report["decision"] = "hold_plan_cache_runtime_use"
        report["reason"] = "some session logs could not be loaded"
    elif report["plan_cache_hit_count"] < report["min_cache_hits"]:
        report["readiness"] = "review"
        report["decision"] = "hold_plan_cache_runtime_use"
        report["reason"] = "plan cache needs more runtime hit evidence"
    elif report["post_hit_action_verification_reject_rate"] > report["max_rejected_action_rate"]:
        report["readiness"] = "rejected"
        report["decision"] = "reject_plan_cache_runtime_use"
        report["reason"] = "cached plans produced too many verifier-rejected actions"
    elif report["post_hit_action_failure_rate"] > report["max_action_failure_rate"]:
        report["readiness"] = "rejected"
        report["decision"] = "reject_plan_cache_runtime_use"
        report["reason"] = "cached plans produced too many failed actions"
    else:
        report["readiness"] = "approved"
        report["decision"] = "allow_plan_cache_runtime_use"
        report["reason"] = "runtime cache hits stayed within verifier and action-failure limits"
    return report


def build_plan_cache_gate(
    cache_report_paths: list[str],
    runtime_report_paths: list[str] = None,
    min_accepted_entries: int = 1,
    min_runtime_hits: int = 0,
    max_promptware_threats: int = 0,
    max_rejected_action_rate: float = 0.0,
    max_action_failure_rate: float = 0.3,
) -> dict:
    """Gate plan-cache artifacts before runtime use."""
    report = {
        "type": "plan_cache_gate",
        "target": "plan_transition_cache_runtime_use",
        "readiness": "review",
        "decision": "hold_plan_cache_runtime_use",
        "reason": "plan cache gate needs approved cache reports",
        "cache_report_paths": list(cache_report_paths or []),
        "runtime_report_paths": list(runtime_report_paths or []),
        "cache_report_count": 0,
        "approved_cache_report_count": 0,
        "runtime_report_count": 0,
        "approved_runtime_report_count": 0,
        "accepted_entry_count": 0,
        "promptware_threat_count": 0,
        "runtime_hit_count": 0,
        "runtime_action_count": 0,
        "runtime_action_failure_count": 0,
        "runtime_action_failure_rate": 0.0,
        "runtime_action_verification_reject_count": 0,
        "runtime_action_verification_reject_rate": 0.0,
        "min_accepted_entries": max(1, _safe_int(min_accepted_entries, 1)),
        "min_runtime_hits": max(0, _safe_int(min_runtime_hits, 0)),
        "max_promptware_threats": max(0, _safe_int(max_promptware_threats, 0)),
        "max_rejected_action_rate": max(0.0, min(1.0, _safe_float(max_rejected_action_rate, 0.0))),
        "max_action_failure_rate": max(0.0, min(1.0, _safe_float(max_action_failure_rate, 0.3))),
        "checks": [],
        "missing": [],
        "errors": [],
    }
    if not cache_report_paths:
        report["missing"].append("plan_cache_report")

    for path in cache_report_paths or []:
        try:
            payload = _load_json_report(path)
            if payload.get("type") != "plan_transition_cache_report":
                raise ValueError("report type must be plan_transition_cache_report")
            readiness = str(payload.get("readiness") or "unknown").lower()
            accepted = _safe_int(payload.get("accepted_entry_count"), 0)
            threats = _safe_int(payload.get("promptware_threat_count"), 0)
            report["cache_report_count"] += 1
            report["accepted_entry_count"] += accepted
            report["promptware_threat_count"] += threats
            if readiness == "approved":
                report["approved_cache_report_count"] += 1
            report["checks"].append({
                "source": path,
                "kind": "cache_report",
                "status": "pass" if readiness == "approved" and accepted else "fail",
                "readiness": readiness,
                "accepted_entry_count": accepted,
                "promptware_threat_count": threats,
            })
        except Exception as exc:
            report["errors"].append(f"{path}: {exc}")

    for path in runtime_report_paths or []:
        try:
            payload = _load_json_report(path)
            if payload.get("type") != "plan_cache_runtime_report":
                raise ValueError("report type must be plan_cache_runtime_report")
            readiness = str(payload.get("readiness") or "unknown").lower()
            hits = _safe_int(payload.get("plan_cache_hit_count"), 0)
            actions = _safe_int(payload.get("post_hit_action_count"), 0)
            failures = _safe_int(payload.get("post_hit_action_failure_count"), 0)
            rejects = _safe_int(payload.get("post_hit_action_verification_reject_count"), 0)
            report["runtime_report_count"] += 1
            report["runtime_hit_count"] += hits
            report["runtime_action_count"] += actions
            report["runtime_action_failure_count"] += failures
            report["runtime_action_verification_reject_count"] += rejects
            if readiness == "approved":
                report["approved_runtime_report_count"] += 1
            report["checks"].append({
                "source": path,
                "kind": "runtime_report",
                "status": "pass" if readiness == "approved" else "fail" if readiness in {"rejected", "error"} else "review",
                "readiness": readiness,
                "plan_cache_hit_count": hits,
                "post_hit_action_count": actions,
                "post_hit_action_failure_count": failures,
                "post_hit_action_verification_reject_count": rejects,
            })
        except Exception as exc:
            report["errors"].append(f"{path}: {exc}")

    report["runtime_action_failure_rate"] = _ratio(
        report["runtime_action_failure_count"],
        report["runtime_action_count"],
    )
    report["runtime_action_verification_reject_rate"] = _ratio(
        report["runtime_action_verification_reject_count"],
        report["runtime_action_count"],
    )

    readinesses = [check.get("readiness") for check in report["checks"]]
    if report["errors"]:
        report["readiness"] = "error"
        report["decision"] = "reject_plan_cache_runtime_use"
        report["reason"] = "plan cache gate inputs could not be loaded"
    elif report["missing"]:
        report["readiness"] = "review"
        report["decision"] = "hold_plan_cache_runtime_use"
        report["reason"] = "plan cache gate is missing required reports"
    elif any(readiness in {"rejected", "error"} for readiness in readinesses):
        report["readiness"] = "rejected"
        report["decision"] = "reject_plan_cache_runtime_use"
        report["reason"] = "plan cache gate includes rejected or error reports"
    elif report["approved_cache_report_count"] != report["cache_report_count"]:
        report["readiness"] = "review"
        report["decision"] = "hold_plan_cache_runtime_use"
        report["reason"] = "plan cache reports are not all approved"
    elif report["accepted_entry_count"] < report["min_accepted_entries"]:
        report["readiness"] = "review"
        report["decision"] = "hold_plan_cache_runtime_use"
        report["reason"] = "plan cache gate needs more accepted entries"
    elif report["promptware_threat_count"] > report["max_promptware_threats"]:
        report["readiness"] = "rejected"
        report["decision"] = "reject_plan_cache_runtime_use"
        report["reason"] = "plan cache reports contain promptware threats"
    elif report["runtime_hit_count"] < report["min_runtime_hits"]:
        report["readiness"] = "review"
        report["decision"] = "hold_plan_cache_runtime_use"
        report["reason"] = "plan cache gate needs more runtime hit evidence"
    elif report["runtime_action_verification_reject_rate"] > report["max_rejected_action_rate"]:
        report["readiness"] = "rejected"
        report["decision"] = "reject_plan_cache_runtime_use"
        report["reason"] = "runtime cache hits exceed verifier reject limit"
    elif report["runtime_action_failure_rate"] > report["max_action_failure_rate"]:
        report["readiness"] = "rejected"
        report["decision"] = "reject_plan_cache_runtime_use"
        report["reason"] = "runtime cache hits exceed action failure limit"
    else:
        report["readiness"] = "approved"
        report["decision"] = "allow_plan_cache_runtime_use"
        report["reason"] = "approved cache reports and runtime evidence allow plan-cache use"
    return report


def evaluate_plan_cache_runtime_gate(
    gate_paths: list[str] = None,
    enable_requested: bool = False,
) -> dict:
    """Evaluate saved plan-cache-gate reports before runtime cache loading."""
    clean_paths = [str(path or "").strip() for path in (gate_paths or []) if str(path or "").strip()]
    report = {
        "type": "plan_cache_runtime_gate",
        "required": bool(enable_requested),
        "requested_enable_plan_cache": bool(enable_requested),
        "effective_enable_plan_cache": False,
        "readiness": "not_required" if not enable_requested else "review",
        "decision": "skip_plan_cache_runtime_gate" if not enable_requested else "hold_plan_cache_runtime_use",
        "reason": "plan cache is not requested",
        "gate_paths": clean_paths,
        "gate_count": 0,
        "approved_gate_count": 0,
        "review_gate_count": 0,
        "rejected_gate_count": 0,
        "error_gate_count": 0,
        "gate_readiness": "not_required" if not enable_requested else "missing",
        "gate_approved": not bool(enable_requested),
        "gate_reports": [],
        "missing": [],
        "errors": [],
    }
    if not enable_requested:
        return report
    if not clean_paths:
        report["reason"] = "plan cache runtime use requires approved plan-cache-gate reports"
        report["missing"].append("plan_cache_gate")
        return report

    readinesses = []
    for path in clean_paths:
        try:
            payload = _load_json_report(path)
            if payload.get("type") != "plan_cache_gate":
                raise ValueError("report type must be plan_cache_gate")
            readiness = str(payload.get("readiness") or "unknown").lower()
            summary = {
                "path": path,
                "readiness": readiness,
                "decision": str(payload.get("decision") or ""),
                "reason": str(payload.get("reason") or "")[:300],
                "accepted_entry_count": _safe_int(payload.get("accepted_entry_count"), 0),
                "runtime_hit_count": _safe_int(payload.get("runtime_hit_count"), 0),
                "runtime_action_verification_reject_rate": _safe_float(
                    payload.get("runtime_action_verification_reject_rate"),
                    0.0,
                ),
            }
            report["gate_reports"].append(summary)
            report["gate_count"] += 1
            readinesses.append(readiness)
            if readiness == "approved":
                report["approved_gate_count"] += 1
            elif readiness == "rejected":
                report["rejected_gate_count"] += 1
            elif readiness == "error":
                report["error_gate_count"] += 1
            else:
                report["review_gate_count"] += 1
        except Exception as exc:
            report["errors"].append(f"{path}: {exc}")

    if report["errors"]:
        report["readiness"] = "error"
        report["gate_readiness"] = "error"
        report["decision"] = "disable_plan_cache_runtime_use"
        report["reason"] = "plan cache runtime gate inputs could not be loaded"
    elif any(readiness == "error" for readiness in readinesses):
        report["readiness"] = "error"
        report["gate_readiness"] = "error"
        report["decision"] = "disable_plan_cache_runtime_use"
        report["reason"] = "plan-cache gate has error readiness"
    elif any(readiness == "rejected" for readiness in readinesses):
        report["readiness"] = "rejected"
        report["gate_readiness"] = "rejected"
        report["decision"] = "disable_plan_cache_runtime_use"
        report["reason"] = "plan-cache gate rejected runtime use"
    elif readinesses and all(readiness == "approved" for readiness in readinesses):
        report["readiness"] = "approved"
        report["gate_readiness"] = "approved"
        report["gate_approved"] = True
        report["effective_enable_plan_cache"] = True
        report["decision"] = "enable_plan_cache_runtime_use"
        report["reason"] = "approved plan-cache gates allow runtime cache use"
    else:
        report["readiness"] = "review"
        report["gate_readiness"] = "review" if readinesses else "missing"
        report["decision"] = "hold_plan_cache_runtime_use"
        report["reason"] = "plan-cache gate is not approved"
    return report


@dataclass
class PlanTransitionCache:
    min_confidence: float = 0.75
    entries: list[dict] = field(default_factory=list)
    load_report: dict = field(default_factory=dict)

    def load_reports(self, paths: list[str]) -> dict:
        report = {
            "enabled": True,
            "paths": list(paths or []),
            "loaded_entry_count": 0,
            "skipped_entry_count": 0,
            "report_count": 0,
            "approved_report_count": 0,
            "errors": [],
        }
        self.entries = []
        for path in paths or []:
            try:
                with open(path, "r", encoding="utf-8-sig") as f:
                    payload = json.load(f)
                if not isinstance(payload, dict):
                    raise ValueError("plan cache report must be a JSON object")
                if payload.get("type") != "plan_transition_cache_report":
                    raise ValueError("report type must be plan_transition_cache_report")
                report["report_count"] += 1
                if payload.get("readiness") == "approved":
                    report["approved_report_count"] += 1
                else:
                    report["skipped_entry_count"] += len(payload.get("entries", []) or [])
                    continue
                for entry in payload.get("entries", []) or []:
                    if self._entry_usable(entry):
                        loaded = copy.deepcopy(entry)
                        loaded["_source_report"] = path
                        self.entries.append(loaded)
                        report["loaded_entry_count"] += 1
                    else:
                        report["skipped_entry_count"] += 1
            except Exception as exc:
                report["errors"].append(f"{path}: {exc}")
        self.load_report = report
        return report

    def _entry_usable(self, entry: dict) -> bool:
        if not isinstance(entry, dict):
            return False
        if not entry.get("accepted_for_runtime"):
            return False
        if _safe_float(entry.get("confidence"), 0.0) < self.min_confidence:
            return False
        if _safe_int(entry.get("promptware_threat_count"), 0) > 0:
            return False
        plan = entry.get("plan", {}) if isinstance(entry.get("plan", {}), dict) else {}
        if _plan_promptware_flags(plan):
            return False
        actions = plan.get("actions", [])
        return isinstance(actions, list) and bool(actions)

    def query(
        self,
        goal: str,
        world_state: dict | None,
        previous_plan_signature: str = START_PLAN_SIGNATURE,
        min_state_similarity: float = 0.35,
    ) -> dict | None:
        if not self.entries:
            return None
        goal_sig = goal_signature(goal)
        features = state_features(world_state)
        prev_sig = previous_plan_signature or START_PLAN_SIGNATURE
        best = None
        best_score = -1.0
        for entry in self.entries:
            if entry.get("goal_signature") != goal_sig:
                continue
            if entry.get("previous_plan_signature") != prev_sig:
                continue
            similarity = _jaccard(features, entry.get("state_features", []))
            if similarity < min_state_similarity:
                continue
            confidence = _safe_float(entry.get("confidence"), 0.0)
            support_score = min(1.0, _safe_int(entry.get("support_count"), 0) / 5)
            score = round((0.55 * confidence) + (0.35 * similarity) + (0.10 * support_score), 3)
            if score > best_score:
                best_score = score
                best = (entry, similarity, score)
        if not best:
            return None
        entry, similarity, score = best
        plan = copy.deepcopy(entry.get("plan", {}))
        plan["source"] = "plan_transition_cache"
        plan["cache_entry_id"] = entry.get("id")
        if plan.get("reasoning"):
            plan["reasoning"] = f"[cached plan] {plan['reasoning']}"
        else:
            plan["reasoning"] = "[cached plan] reused approved plan transition"
        return {
            "plan": plan,
            "entry_id": entry.get("id"),
            "confidence": _safe_float(entry.get("confidence"), 0.0),
            "score": score,
            "state_similarity": similarity,
            "support_count": _safe_int(entry.get("support_count"), 0),
            "success_rate": _safe_float(entry.get("success_rate"), 0.0),
            "source_report": entry.get("_source_report", ""),
        }

    def summary(self) -> dict:
        return {
            "enabled": bool(self.load_report.get("enabled", False)),
            "entry_count": len(self.entries),
            "min_confidence": self.min_confidence,
            "loaded_entry_count": self.load_report.get("loaded_entry_count", len(self.entries)),
            "skipped_entry_count": self.load_report.get("skipped_entry_count", 0),
            "paths": self.load_report.get("paths", []),
            "errors": self.load_report.get("errors", []),
        }


def write_plan_transition_cache_report(report: dict, output_path: str):
    if not output_path:
        return
    parent = os.path.dirname(output_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
