"""Action outcome value profiles for verifier-guided selection."""
from copy import deepcopy
from dataclasses import dataclass, field


def action_signature(action: dict) -> str:
    """Return a stable coarse signature for action outcome aggregation."""
    if not isinstance(action, dict):
        return "unknown"
    action_type = str(action.get("type") or "unknown").strip() or "unknown"
    params = action.get("parameters", {}) if isinstance(action.get("parameters", {}), dict) else {}
    if action_type == "craft":
        return f"craft:{params.get('item') or 'unknown'}"
    if action_type == "smelt":
        return f"smelt:{params.get('item') or 'unknown'}"
    if action_type == "dig":
        target = params.get("block") or params.get("name")
        return f"dig:{target or 'coordinates'}"
    if action_type in {"place", "equip", "use_item"}:
        return f"{action_type}:{params.get('item') or 'unknown'}"
    if action_type == "attack":
        return "attack:targeted" if params.get("entity_id") else "attack:untargeted"
    if action_type in {"move_to", "walk_to"}:
        return f"{action_type}:navigation"
    if action_type in {"look_at", "wait", "chat"}:
        return f"{action_type}:low_impact"
    return action_type


def task_family_from_goal(goal: str) -> str:
    """Infer a coarse Minecraft task family from a natural-language goal."""
    text = str(goal or "").lower()
    if any(token in text for token in ("craft", "make", "smelt")):
        return "crafting"
    if any(token in text for token in ("mine", "dig", "ore", "cobblestone", "coal", "iron", "diamond")):
        return "mining"
    if any(token in text for token in ("gather", "collect", "get", "obtain", "log", "wood")):
        return "gathering"
    if any(token in text for token in ("build", "place", "shelter", "house", "base")):
        return "building"
    if any(token in text for token in ("attack", "kill", "combat", "mob", "zombie", "skeleton")):
        return "combat"
    if any(token in text for token in ("explore", "find", "search", "locate")):
        return "exploration"
    return "general"


@dataclass
class ActionValueStats:
    signature: str
    action_type: str = "unknown"
    attempts: int = 0
    successes: int = 0
    failures: int = 0
    unknown_outcomes: int = 0
    verifier_rejects: int = 0
    verifier_reviews: int = 0
    verifier_accepts: int = 0
    task_families: dict = field(default_factory=dict)

    @property
    def success_rate(self) -> float:
        return round(self.successes / self.attempts, 3) if self.attempts else 0.0

    @property
    def failure_rate(self) -> float:
        return round(self.failures / self.attempts, 3) if self.attempts else 0.0

    def record(self, success, task_family: str = "", verification: dict = None):
        self.attempts += 1
        if success is True:
            self.successes += 1
        elif success is False:
            self.failures += 1
        else:
            self.unknown_outcomes += 1
        if task_family:
            self.task_families[task_family] = self.task_families.get(task_family, 0) + 1
        verification = verification if isinstance(verification, dict) else {}
        status = str(verification.get("status") or "")
        if status == "reject":
            self.verifier_rejects += 1
        elif status == "review":
            self.verifier_reviews += 1
        elif status == "accept":
            self.verifier_accepts += 1

    def value_score(self) -> float:
        if not self.attempts:
            return 0.5
        smoothed_success = (self.successes + 0.5) / (self.attempts + 1)
        confidence = min(1.0, self.attempts / 6)
        score = (0.5 * (1 - confidence)) + (smoothed_success * confidence)
        if self.verifier_rejects:
            score -= min(0.2, self.verifier_rejects / max(1, self.attempts) * 0.2)
        return round(max(0.0, min(1.0, score)), 3)

    def as_dict(self) -> dict:
        return {
            "signature": self.signature,
            "action_type": self.action_type,
            "attempts": self.attempts,
            "successes": self.successes,
            "failures": self.failures,
            "unknown_outcomes": self.unknown_outcomes,
            "success_rate": self.success_rate,
            "failure_rate": self.failure_rate,
            "value_score": self.value_score(),
            "verifier_rejects": self.verifier_rejects,
            "verifier_reviews": self.verifier_reviews,
            "verifier_accepts": self.verifier_accepts,
            "task_families": dict(self.task_families),
        }


class ActionValueProfile:
    """In-memory action outcome statistics for candidate scoring."""

    def __init__(self):
        self.stats: dict[str, ActionValueStats] = {}
        self.repair_pairs: dict[str, list[dict]] = {}
        self.transition_values: dict[str, dict] = {}
        self.last_merge_report: dict = {}

    def record(self, action: dict, result: dict = None, goal: str = "", verification: dict = None):
        signature = action_signature(action)
        action_type = str(action.get("type") or "unknown") if isinstance(action, dict) else "unknown"
        stats = self.stats.get(signature)
        if stats is None:
            stats = ActionValueStats(signature=signature, action_type=action_type)
            self.stats[signature] = stats
        stats.record(self._event_success(result), task_family_from_goal(goal), verification)

    def score(self, action: dict, goal: str = "") -> dict:
        signature = action_signature(action)
        stats = self.stats.get(signature)
        if stats is None:
            data = {
                "signature": signature,
                "value_score": 0.5,
                "attempts": 0,
                "success_rate": 0.0,
                "failure_rate": 0.0,
                "task_family": task_family_from_goal(goal),
            }
        else:
            data = stats.as_dict()
            data["task_family"] = task_family_from_goal(goal)
        transition = self.transition_values.get(signature)
        if transition:
            self._apply_transition_value(data, transition)
        return data

    def merge_feedback(self, feedback: dict) -> int:
        """Load action-value feedback items from an offline report."""
        self.last_merge_report = {
            "action_value_items_loaded": 0,
            "repair_pairs_loaded": 0,
            "transition_values_loaded": 0,
            "transition_values_skipped": 0,
            "transition_skip_reasons": {},
        }
        if not isinstance(feedback, dict):
            return 0
        items = feedback.get("action_value_items", feedback.get("items", []))
        if not isinstance(items, list):
            items = []
        loaded = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            signature = str(item.get("signature") or "")
            if not signature:
                continue
            stats = ActionValueStats(
                signature=signature,
                action_type=str(item.get("action_type") or signature.split(":", 1)[0] or "unknown"),
                attempts=self._safe_int(item.get("attempts")),
                successes=self._safe_int(item.get("successes")),
                failures=self._safe_int(item.get("failures")),
                unknown_outcomes=self._safe_int(item.get("unknown_outcomes")),
                verifier_rejects=self._safe_int(item.get("verifier_rejects")),
                verifier_reviews=self._safe_int(item.get("verifier_reviews")),
                verifier_accepts=self._safe_int(item.get("verifier_accepts")),
                task_families=dict(item.get("task_families", {})) if isinstance(item.get("task_families", {}), dict) else {},
            )
            self.stats[signature] = stats
            loaded += 1
        self.last_merge_report["action_value_items_loaded"] = loaded
        repair_loaded = self.merge_repair_pairs(feedback.get("failure_correction_pairs", []))
        transition_loaded = self.merge_transition_values(feedback.get("state_transition_value_items", []))
        loaded += repair_loaded + transition_loaded
        return loaded

    def merge_repair_pairs(self, pairs: list[dict]) -> int:
        """Load failed-action to recovery-action examples from feedback."""
        if not isinstance(pairs, list):
            return 0
        loaded = 0
        for pair in pairs:
            if not isinstance(pair, dict):
                continue
            failed_signature = str(pair.get("failed_signature") or "")
            recovery_action = pair.get("recovery_action", {})
            if not failed_signature or not isinstance(recovery_action, dict):
                continue
            item = {
                "failed_signature": failed_signature,
                "recovery_signature": str(pair.get("recovery_signature") or action_signature(recovery_action)),
                "recovery_action": deepcopy(recovery_action),
                "goal": str(pair.get("goal") or ""),
                "source_log": str(pair.get("source_log") or ""),
                "failed_error": str(pair.get("failed_error") or ""),
            }
            bucket = self.repair_pairs.setdefault(failed_signature, [])
            key = repr(item["recovery_action"])
            if any(repr(existing.get("recovery_action", {})) == key for existing in bucket):
                continue
            bucket.append(item)
            loaded += 1
        self.last_merge_report["repair_pairs_loaded"] = self.last_merge_report.get("repair_pairs_loaded", 0) + loaded
        return loaded

    def merge_transition_values(self, items: list[dict]) -> int:
        """Load high-confidence state-transition value scores from ASV-style feedback."""
        if not isinstance(items, list):
            return 0
        loaded = 0
        skipped = 0
        skip_reasons = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            signature = str(item.get("signature") or "")
            if not signature:
                continue
            trusted, reason = self._transition_value_trust_decision(item)
            if not trusted:
                skipped += 1
                skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
                continue
            self._merge_transition_value_item(item)
            loaded += 1
        self.last_merge_report["transition_values_loaded"] = (
            self.last_merge_report.get("transition_values_loaded", 0) + loaded
        )
        self.last_merge_report["transition_values_skipped"] = (
            self.last_merge_report.get("transition_values_skipped", 0) + skipped
        )
        for reason, count in skip_reasons.items():
            existing = self.last_merge_report.setdefault("transition_skip_reasons", {})
            existing[reason] = existing.get(reason, 0) + count
        return loaded

    def repair_candidates(self, action: dict, limit: int = 5) -> list[dict]:
        """Return recovery actions previously observed after this action failed."""
        signature = action_signature(action)
        candidates = []
        for pair in self.repair_pairs.get(signature, [])[:limit]:
            recovery_action = pair.get("recovery_action", {})
            if isinstance(recovery_action, dict):
                candidates.append({
                    "action": deepcopy(recovery_action),
                    "source": "value_repair",
                    "reason": f"action-value repair {signature}->{pair.get('recovery_signature', 'unknown')}",
                    "pair": dict(pair),
                })
        return candidates

    def as_feedback(self, limit: int = 40) -> dict:
        items = sorted(
            [stats.as_dict() for stats in self.stats.values()],
            key=lambda item: (-item["attempts"], item["signature"]),
        )
        pairs = [
            dict(pair)
            for signature in sorted(self.repair_pairs)
            for pair in self.repair_pairs.get(signature, [])
        ]
        return {
            "action_value_items": items[:limit],
            "failure_correction_pairs": pairs[:limit],
            "state_transition_value_items": [
                dict(self.transition_values[signature])
                for signature in sorted(self.transition_values)
            ][:limit],
            "signature_count": len(items),
            "attempt_count": sum(item["attempts"] for item in items),
            "repair_pair_count": len(pairs),
            "transition_value_count": len(self.transition_values),
        }

    def high_value_items(self, min_attempts: int = 2, min_score: float = 0.7) -> list[dict]:
        return [
            item for item in self.as_feedback(limit=1000)["action_value_items"]
            if item["attempts"] >= min_attempts and item["value_score"] >= min_score
        ]

    def low_value_items(self, min_attempts: int = 2, max_score: float = 0.35) -> list[dict]:
        return [
            item for item in self.as_feedback(limit=1000)["action_value_items"]
            if item["attempts"] >= min_attempts and item["value_score"] <= max_score
        ]

    def _event_success(self, result: dict):
        if not isinstance(result, dict):
            return None
        for key in ("success", "completed", "passed", "ok", "achieved"):
            if isinstance(result.get(key), bool):
                return result.get(key)
        status = str(result.get("status") or result.get("state") or result.get("outcome") or "").strip().lower()
        if status in {"achieved", "complete", "completed", "done", "ok", "pass", "passed", "success", "succeeded"}:
            return True
        if status in {"aborted", "blocked", "error", "fail", "failed", "failure", "incomplete", "rejected"}:
            return False
        nested = result.get("result")
        if isinstance(nested, dict):
            return self._event_success(nested)
        return None

    def _safe_int(self, value, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _safe_float(self, value, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _transition_value_trust_decision(self, item: dict) -> tuple[bool, str]:
        attempts = max(0, self._safe_int(item.get("attempts")))
        if attempts <= 0:
            return False, "no_transition_attempts"
        confidence = self._safe_float(item.get("avg_transition_confidence"), 0.0)
        if confidence < 0.75:
            return False, "low_transition_confidence"
        low_confidence = max(0, self._safe_int(item.get("low_confidence_transitions")))
        if low_confidence / max(1, attempts) > 0.25:
            return False, "too_many_low_confidence_windows"
        if item.get("avg_transition_value_score") is None:
            return False, "missing_transition_value_score"
        return True, "trusted"

    def _merge_transition_value_item(self, item: dict):
        signature = str(item.get("signature") or "")
        attempts = max(1, self._safe_int(item.get("attempts")))
        score = max(0.0, min(1.0, self._safe_float(item.get("avg_transition_value_score"), 0.5)))
        confidence = max(0.0, min(1.0, self._safe_float(item.get("avg_transition_confidence"), 1.0)))
        existing = self.transition_values.get(signature)
        if existing is None:
            self.transition_values[signature] = {
                "signature": signature,
                "action_type": str(item.get("action_type") or signature.split(":", 1)[0] or "unknown"),
                "attempts": attempts,
                "avg_transition_value_score": round(score, 3),
                "avg_transition_confidence": round(confidence, 3),
                "positive_transitions": self._safe_int(item.get("positive_transitions")),
                "negative_transitions": self._safe_int(item.get("negative_transitions")),
                "no_progress_transitions": self._safe_int(item.get("no_progress_transitions")),
                "low_confidence_transitions": self._safe_int(item.get("low_confidence_transitions")),
                "source_logs": list(item.get("source_logs", []))[:8] if isinstance(item.get("source_logs", []), list) else [],
            }
            return
        total_attempts = existing["attempts"] + attempts
        existing_score = self._safe_float(existing.get("avg_transition_value_score"), 0.5)
        existing_confidence = self._safe_float(existing.get("avg_transition_confidence"), 1.0)
        existing["avg_transition_value_score"] = round(
            ((existing_score * existing["attempts"]) + (score * attempts)) / total_attempts,
            3,
        )
        existing["avg_transition_confidence"] = round(
            ((existing_confidence * existing["attempts"]) + (confidence * attempts)) / total_attempts,
            3,
        )
        existing["attempts"] = total_attempts
        for key in ("positive_transitions", "negative_transitions", "no_progress_transitions", "low_confidence_transitions"):
            existing[key] = self._safe_int(existing.get(key)) + self._safe_int(item.get(key))
        if isinstance(item.get("source_logs", []), list):
            merged_sources = list(existing.get("source_logs", []))
            for source in item.get("source_logs", []):
                if source not in merged_sources:
                    merged_sources.append(source)
            existing["source_logs"] = merged_sources[:8]

    def _apply_transition_value(self, data: dict, transition: dict):
        outcome_score = self._safe_float(data.get("value_score"), 0.5)
        transition_score = self._safe_float(transition.get("avg_transition_value_score"), 0.5)
        transition_attempts = max(1, self._safe_int(transition.get("attempts")))
        confidence = max(0.0, min(1.0, self._safe_float(transition.get("avg_transition_confidence"), 1.0)))
        weight = min(0.35, transition_attempts * 0.08) * confidence
        data["outcome_value_score"] = round(outcome_score, 3)
        data["transition_value_score"] = round(transition_score, 3)
        data["transition_value_attempts"] = transition_attempts
        data["transition_value_confidence"] = round(confidence, 3)
        data["transition_value_applied"] = True
        data["value_score"] = round(max(0.0, min(1.0, outcome_score * (1 - weight) + transition_score * weight)), 3)
