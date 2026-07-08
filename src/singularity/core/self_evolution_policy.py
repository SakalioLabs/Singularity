"""Advisory policy for consuming self-evolution execution feedback."""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SelfEvolutionPolicyAdvice:
    """Planner-facing advice derived from offline execution feedback."""

    goal: str
    mode: str = "normal"
    priority: str = "low"
    reasons: list[str] = field(default_factory=list)
    remedy_candidates: list[str] = field(default_factory=list)
    adaptor_recommendations: list[str] = field(default_factory=list)
    skill_reflection: str = "preserve_skill_body_until_verified"
    safety_gate: str = "advisory_only"

    def as_dict(self) -> dict:
        return {
            "goal": self.goal,
            "mode": self.mode,
            "priority": self.priority,
            "reasons": list(self.reasons),
            "remedy_candidates": list(self.remedy_candidates),
            "adaptor_recommendations": list(self.adaptor_recommendations),
            "skill_reflection": self.skill_reflection,
            "safety_gate": self.safety_gate,
        }


class SelfEvolutionPolicy:
    """Consume MineEvolve-style feedback without mutating plans or skills.

    The policy is intentionally advisory. It can influence planner context, but
    it does not rewrite skills, bypass goal verification, or auto-commit plan
    repairs. This keeps self-evolution feedback useful while preserving a
    verification boundary for later VASO-style gates.
    """

    def __init__(self, feedback: Optional[dict] = None):
        self._feedback: dict = {}
        self._hints_by_policy: dict[str, dict] = {}
        self._remedy_candidates: list[str] = []
        self._adaptor_recommendations: list[str] = []
        self._failure_categories: dict[str, int] = {}
        self._typed_feedback_counts: dict[str, int] = {}
        self._relative_reward_delta: float = 0.0
        if feedback:
            self.record_self_evolution_feedback(feedback)

    def record_self_evolution_feedback(self, feedback: dict) -> int:
        """Store policy hints from `BenchmarkRunner.self_evolution_feedback()`."""
        if not isinstance(feedback, dict):
            return 0
        self._feedback = dict(feedback)
        stored = 0
        self._hints_by_policy = {}
        for hint in feedback.get("policy_hints", []) if isinstance(feedback, dict) else []:
            if not isinstance(hint, dict):
                continue
            policy = str(hint.get("self_evolution_policy") or hint.get("policy") or "").strip()
            if not policy:
                continue
            self._hints_by_policy[policy] = dict(hint)
            stored += 1
        self._remedy_candidates = self._string_list(feedback.get("remedy_candidates", []), limit=20)
        self._adaptor_recommendations = self._string_list(feedback.get("adaptor_recommendations", []), limit=20)
        self._failure_categories = self._int_counts(feedback.get("action_failure_categories", {}))
        self._typed_feedback_counts = self._int_counts(feedback.get("typed_feedback_counts", {}))
        self._relative_reward_delta = self._safe_float(feedback.get("relative_reward_delta", 0.0))
        return stored

    def advise(self, goal: str = "", observation: dict = None) -> SelfEvolutionPolicyAdvice:
        """Return planner-facing repair guidance for the current goal."""
        reasons = []
        mode = "normal"
        priority = "low"

        if self._has_hint("repair_stagnant_plan_suffix"):
            mode = "repair_unfinished_plan_suffix"
            priority = "high"
            reasons.append("prior traces showed stagnation or repeated failures")
        if self._has_hint("route_through_adaptor_before_retry"):
            mode = "repair_unfinished_plan_suffix"
            priority = "high"
            reasons.append("regression signals outweighed progress signals")
        if self._has_hint("induce_failure_remedies"):
            if priority != "high":
                priority = "medium"
            reasons.append("failed actions should be converted into remedy candidates")
        if self._has_hint("curate_successful_progress_patterns"):
            reasons.append("successful progress patterns are available for skill curation")

        if self._relative_reward_delta < 0:
            reasons.append("relative reward trend was negative in reviewed traces")
            if priority == "low":
                priority = "medium"

        skill_reflection = self._skill_reflection_mode()
        if skill_reflection == "execution_lapse_first":
            reasons.append("dominant failures look like execution lapses, so preserve skill body")
        elif skill_reflection == "skill_revision_candidate":
            reasons.append("dominant failures look like missing prerequisites or reasoning gaps")

        return SelfEvolutionPolicyAdvice(
            goal=str(goal or ""),
            mode=mode,
            priority=priority,
            reasons=self._dedupe(reasons)[:8],
            remedy_candidates=self._remedy_candidates[:5],
            adaptor_recommendations=self._adaptor_recommendations[:5],
            skill_reflection=skill_reflection,
            safety_gate="advisory_only_requires_verification",
        )

    def planner_context(self, goal: str = "", observation: dict = None, limit: int = 5) -> str:
        """Format concise self-evolution advice for planner memory context."""
        if not self._feedback:
            return ""
        advice = self.advise(goal, observation)
        lines = [
            "Self-evolution feedback (advisory, do not bypass verification):",
            f"- mode={advice.mode}, priority={advice.priority}, skill_reflection={advice.skill_reflection}",
        ]
        for reason in advice.reasons[:limit]:
            lines.append(f"- reason: {reason}")
        for recommendation in advice.adaptor_recommendations[:limit]:
            lines.append(f"- adaptor: {recommendation}")
        for remedy in advice.remedy_candidates[:limit]:
            lines.append(f"- remedy candidate: {remedy}")
        return "\n".join(lines)

    def feedback_profile(self) -> dict:
        return {
            "policy_hints": sorted(self._hints_by_policy),
            "failure_categories": dict(self._failure_categories),
            "typed_feedback_counts": dict(self._typed_feedback_counts),
            "relative_reward_delta": self._relative_reward_delta,
            "remedy_count": len(self._remedy_candidates),
            "adaptor_recommendation_count": len(self._adaptor_recommendations),
            "skill_reflection": self._skill_reflection_mode(),
        }

    def hints(self) -> dict:
        return {name: dict(hint) for name, hint in self._hints_by_policy.items()}

    def _skill_reflection_mode(self) -> str:
        perception = int(self._failure_categories.get("perception", 0) or 0)
        action = int(self._failure_categories.get("action", 0) or 0)
        reasoning = int(self._failure_categories.get("reasoning", 0) or 0)
        if reasoning > perception + action:
            return "skill_revision_candidate"
        if perception or action:
            return "execution_lapse_first"
        return "preserve_skill_body_until_verified"

    def _has_hint(self, name: str) -> bool:
        return name in self._hints_by_policy

    def _string_list(self, values, limit: int = 20) -> list[str]:
        if not isinstance(values, list):
            return []
        return self._dedupe(str(value).strip() for value in values if str(value or "").strip())[:limit]

    def _int_counts(self, values) -> dict[str, int]:
        if not isinstance(values, dict):
            return {}
        counts = {}
        for key, value in values.items():
            name = str(key or "").strip()
            if name:
                counts[name] = int(self._safe_float(value, 0.0))
        return counts

    def _safe_float(self, value, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _dedupe(self, values) -> list[str]:
        seen = set()
        result = []
        for value in values:
            text = str(value or "").strip()
            if text and text not in seen:
                seen.add(text)
                result.append(text)
        return result
