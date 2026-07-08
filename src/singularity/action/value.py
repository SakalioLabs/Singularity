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
            return {
                "signature": signature,
                "value_score": 0.5,
                "attempts": 0,
                "success_rate": 0.0,
                "failure_rate": 0.0,
                "task_family": task_family_from_goal(goal),
            }
        data = stats.as_dict()
        data["task_family"] = task_family_from_goal(goal)
        return data

    def merge_feedback(self, feedback: dict) -> int:
        """Load action-value feedback items from an offline report."""
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
        loaded += self.merge_repair_pairs(feedback.get("failure_correction_pairs", []))
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
            "signature_count": len(items),
            "attempt_count": sum(item["attempts"] for item in items),
            "repair_pair_count": len(pairs),
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
