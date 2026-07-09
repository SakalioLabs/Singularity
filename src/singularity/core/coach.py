"""Advisory runtime coaching policy for Minecraft planning and curriculum."""
from dataclasses import dataclass, field, replace
import re

from singularity.core.curriculum import CurriculumGoalCandidate


@dataclass(frozen=True)
class CoachProfile:
    """One optional style profile that biases behavior without changing gates."""

    name: str
    description: str
    planner_directives: list[str] = field(default_factory=list)
    category_weights: dict[str, float] = field(default_factory=dict)
    reason_weights: dict[str, float] = field(default_factory=dict)


class CoachPolicy:
    """Translate runtime style names into planner hints and curriculum bias."""

    PROFILES: dict[str, CoachProfile] = {
        "safe": CoachProfile(
            name="safe",
            description="Prefer survival margins, lighting, and low-risk routes.",
            planner_directives=[
                "Keep health, food, shelter, and light above exploration tempo.",
                "Prefer torches, safer routes, and retreat plans before cave or night actions.",
                "Avoid optional combat unless the current goal or survival state requires it.",
            ],
            category_weights={
                "world_model_safety": 12.0,
                "exploration_diagnostic": 8.0,
                "crafting": 3.0,
                "resource": 3.0,
                "exploration": -4.0,
                "world_model_frontier": -3.0,
            },
            reason_weights={
                "night_and_cave_safety": 8.0,
                "reduce_exploration_risk": 8.0,
                "danger_aware_route": 6.0,
                "world_model_danger_feedback": 8.0,
                "perception_failure_feedback": 5.0,
            },
        ),
        "explorer": CoachProfile(
            name="explorer",
            description="Prefer frontier coverage and novel world knowledge when stable.",
            planner_directives=[
                "When stable, favor frontier coverage and landmark recording.",
                "Inspect novel nearby resources and update route knowledge.",
                "Keep exploration reversible by preserving a clear return path.",
            ],
            category_weights={
                "world_model_frontier": 14.0,
                "exploration": 10.0,
                "world_model_resource": 7.0,
                "exploration_diagnostic": 4.0,
                "crafting": -2.0,
            },
            reason_weights={
                "open_ended_map_expansion": 8.0,
                "world_model_frontier_feedback": 10.0,
                "visible_novel_resource": 7.0,
                "coverage_gap_feedback": 6.0,
            },
        ),
        "efficient": CoachProfile(
            name="efficient",
            description="Prefer short progression chains and immediate unlocks.",
            planner_directives=[
                "Prefer actions that unlock the next tool tier or remove a blocker.",
                "Batch nearby resource collection before returning to craft.",
                "Avoid detours that do not improve the active goal or next unlock.",
            ],
            category_weights={
                "tool_progression": 10.0,
                "crafting": 7.0,
                "resource": 5.0,
                "fallback": 2.0,
                "exploration": -4.0,
            },
            reason_weights={
                "unlock_stone_mining": 8.0,
                "unlock_iron_mining": 8.0,
                "iron_age_progression": 8.0,
                "convert_ore_to_tool_material": 6.0,
            },
        ),
        "resourceful": CoachProfile(
            name="resourceful",
            description="Prefer inventory breadth and reusable material stockpiles.",
            planner_directives=[
                "Prefer visible or remembered resources that broaden available recipes.",
                "Build small reserves of wood, stone, fuel, and food before long plans.",
                "Convert raw materials only when the conversion directly supports readiness.",
            ],
            category_weights={
                "resource": 12.0,
                "world_model_resource": 9.0,
                "crafting": 5.0,
            },
            reason_weights={
                "early_wood_bootstrap": 7.0,
                "stone_age_progression": 7.0,
                "visible_novel_resource": 4.0,
                "world_model_resource_hotspot": 7.0,
            },
        ),
        "builder": CoachProfile(
            name="builder",
            description="Prefer construction readiness and stable base preparation.",
            planner_directives=[
                "Prefer materials and crafting steps that support shelter or base building.",
                "Keep a nearby safe work area before extending builds.",
                "Favor reusable infrastructure over one-off movement when the goal allows it.",
            ],
            category_weights={
                "building": 12.0,
                "crafting": 5.0,
                "resource": 4.0,
                "world_model_safety": 4.0,
            },
            reason_weights={
                "unlock_crafting_grid": 5.0,
                "early_wood_bootstrap": 5.0,
                "reduce_exploration_risk": 4.0,
            },
        ),
    }

    def __init__(self, profiles: list[CoachProfile] = None, unknown_styles: list[str] = None):
        self.profiles = list(profiles or [])
        self.unknown_styles = list(unknown_styles or [])

    @classmethod
    def from_style(cls, style: str = ""):
        """Build a policy from comma, plus, slash, or whitespace separated styles."""
        raw = str(style or "").strip().lower()
        if not raw:
            return cls()
        names = [part for part in re.split(r"[\s,+/]+", raw) if part]
        profiles = []
        unknown = []
        seen = set()
        for name in names:
            if name in seen:
                continue
            seen.add(name)
            profile = cls.PROFILES.get(name)
            if profile:
                profiles.append(profile)
            else:
                unknown.append(name)
        return cls(profiles, unknown)

    @property
    def active(self) -> bool:
        return bool(self.profiles)

    @property
    def style_names(self) -> list[str]:
        return [profile.name for profile in self.profiles]

    def summary(self) -> dict:
        return {
            "styles": self.style_names,
            "unknown_styles": list(self.unknown_styles),
            "descriptions": [profile.description for profile in self.profiles],
        }

    def planner_context(self, goal: str, observation: dict = None) -> str:
        """Return compact planner instructions that cannot override safety gates."""
        if not self.active:
            return ""
        directives = []
        for profile in self.profiles:
            for directive in profile.planner_directives:
                if directive not in directives:
                    directives.append(directive)
        lines = [
            "Coach policy (advisory only; verifier, safety, and task gates dominate):",
            f"- styles: {', '.join(self.style_names)}",
        ]
        lines.extend(f"- {directive}" for directive in directives[:8])
        if self._danger_pressure(observation or {}):
            lines.append("- Current state has danger pressure; prefer survival margin over style tempo.")
        return "\n".join(lines)

    def rank_curriculum_candidates(
        self,
        candidates: list[CurriculumGoalCandidate],
        observation: dict = None,
        fallback_goal: str = "",
    ) -> list[CurriculumGoalCandidate]:
        """Return a score-adjusted slate while preserving candidate semantics."""
        if not self.active or not candidates:
            return candidates
        adjusted = [
            self._adjust_candidate(candidate, observation or {}, fallback_goal)
            for candidate in candidates
        ]
        adjusted.sort(key=lambda candidate: candidate.score, reverse=True)
        return adjusted

    def _adjust_candidate(
        self,
        candidate: CurriculumGoalCandidate,
        observation: dict,
        fallback_goal: str,
    ) -> CurriculumGoalCandidate:
        delta = 0.0
        markers = []
        for profile in self.profiles:
            category_delta = profile.category_weights.get(candidate.category, 0.0)
            if category_delta:
                delta += category_delta
                markers.append(f"coach:{profile.name}:category")
            for reason in candidate.reasons:
                reason_delta = profile.reason_weights.get(reason, 0.0)
                if reason_delta:
                    delta += reason_delta
                    markers.append(f"coach:{profile.name}:{reason}")
            situational_delta, situational_marker = self._situational_delta(profile, candidate, observation)
            if situational_delta:
                delta += situational_delta
                markers.append(situational_marker)
        if not delta:
            return candidate
        reasons = list(candidate.reasons)
        for marker in markers:
            if marker not in reasons:
                reasons.append(marker)
        return replace(candidate, score=round(candidate.score + delta, 3), reasons=reasons)

    def _situational_delta(
        self,
        profile: CoachProfile,
        candidate: CurriculumGoalCandidate,
        observation: dict,
    ) -> tuple[float, str]:
        if profile.name == "safe" and self._danger_pressure(observation):
            if candidate.category == "world_model_safety":
                return 10.0, "coach:safe:danger_pressure"
            if candidate.category in {"crafting", "resource", "exploration_diagnostic"}:
                return 4.0, "coach:safe:danger_pressure"
            if candidate.category in {"exploration", "world_model_frontier"}:
                return -8.0, "coach:safe:danger_pressure"
        if profile.name == "explorer" and self._danger_pressure(observation):
            if candidate.category in {"exploration", "world_model_frontier"}:
                return -12.0, "coach:explorer:danger_pressure"
        return 0.0, ""

    def _danger_pressure(self, observation: dict) -> bool:
        health = float(observation.get("health", 20) or 20)
        if health < 10:
            return True
        time_of_day = float(observation.get("time_of_day", 6000) or 6000)
        if "time_of_day" in observation and (time_of_day >= 12000 or time_of_day < 1000):
            return True
        hostiles = [entity for entity in observation.get("nearby_entities", []) or [] if entity.get("hostile")]
        return any(float(entity.get("distance", 999) or 999) < 12 for entity in hostiles)
