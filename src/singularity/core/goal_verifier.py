"""Goal self-verification for Minecraft observations.

This is a deterministic first pass inspired by Voyager-style self-verification:
accept common Minecraft goal completion only when the latest observation or
recent action evidence supports it. Unknown goals remain explicitly unknown so
an LLM critic can be added later without changing the call site.
"""
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from singularity.evaluation.m4_shelter import is_machine_verified_shelter

logger = logging.getLogger("singularity.goal_verifier")


@dataclass
class GoalVerification:
    """Result of checking whether a natural-language goal is achieved."""

    goal: str
    achieved: bool
    status: str = "unknown"  # achieved, failed, unknown
    confidence: float = 0.0
    evidence: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    matched_rules: list[str] = field(default_factory=list)
    target_inventory: dict = field(default_factory=dict)
    inventory_delta: dict = field(default_factory=dict)
    critic: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "goal": self.goal,
            "achieved": self.achieved,
            "status": self.status,
            "confidence": self.confidence,
            "evidence": list(self.evidence),
            "missing": list(self.missing),
            "matched_rules": list(self.matched_rules),
            "target_inventory": dict(self.target_inventory),
            "inventory_delta": dict(self.inventory_delta),
            "critic": dict(self.critic),
        }


@dataclass
class VerifierAnchor:
    """Grounded postcondition anchor mined from rules, recipes, or graph edges."""

    canonical: str
    phrases: list[str]
    inventory_items: list[str]
    verbs: list[str] = field(default_factory=list)
    source: str = "manual"
    confidence: float = 0.9
    metadata: dict = field(default_factory=dict)


class GoalVerificationCritic:
    """LLM-backed fallback for goals without deterministic verifier coverage."""

    def __init__(self, llm, min_confidence: float = 0.55):
        self.llm = llm
        self.min_confidence = min_confidence

    def review_goal(
        self,
        goal: str,
        observation: dict,
        recent_actions: list[dict] = None,
        deterministic: GoalVerification = None,
    ) -> dict:
        recent_actions = recent_actions or []
        payload = {
            "goal": goal,
            "deterministic_verification": deterministic.to_dict() if deterministic else {},
            "observation": self._safe_observation(observation or {}),
            "recent_actions": self._safe_actions(recent_actions),
        }
        prompt = (
            "Review whether this Minecraft goal is completed. The deterministic verifier had no matching rule, "
            "so use only the provided structured observation, recent actions, screenshot references, VLM summaries, "
            "grounded resources, flags, structures, entities, and inventory. Reject false completion or missing evidence. "
            "Return strict JSON with keys: decision ('achieved', 'failed', or 'unknown'), confidence (0-1), reason, "
            "evidence (array), missing (array), matched_rules (array), warnings (array)."
        )
        try:
            response = self.llm.chat([
                {"role": "system", "content": "You are a concise Minecraft goal-verification critic. Output JSON only."},
                {"role": "user", "content": f"{prompt}\n\nVerification payload:\n{json.dumps(payload, ensure_ascii=False, default=str)[:6000]}"},
            ], response_format={"type": "json_object"})
            raw = json.loads(response)
        except Exception:
            logger.warning("Goal verification critic failed", exc_info=True)
            return {
                "decision": "unknown",
                "confidence": 0.0,
                "reason": "critic_unavailable",
                "evidence": [],
                "missing": [],
                "matched_rules": ["goal_critic"],
                "warnings": ["goal critic call or JSON parse failed"],
            }
        return self._normalize_review(raw)

    def _normalize_review(self, raw: dict) -> dict:
        if not isinstance(raw, dict):
            raw = {}
        decision = str(raw.get("decision", "unknown")).lower()
        if decision in {"complete", "completed", "success", "satisfied"}:
            decision = "achieved"
        if decision in {"reject", "rejected", "incomplete"}:
            decision = "failed"
        if decision not in {"achieved", "failed", "unknown"}:
            decision = "unknown"
        confidence = self._safe_float(raw.get("confidence", 0.0))
        warnings = self._string_list(raw.get("warnings", []))
        if decision in {"achieved", "failed"} and confidence < self.min_confidence:
            warnings.append("critic_confidence_below_threshold")
            decision = "unknown"
        matched_rules = self._string_list(raw.get("matched_rules", []))
        if "goal_critic" not in matched_rules:
            matched_rules.append("goal_critic")
        return {
            "decision": decision,
            "confidence": confidence,
            "reason": self._safe_text(raw.get("reason", f"critic_{decision}")),
            "evidence": self._string_list(raw.get("evidence", [])),
            "missing": self._string_list(raw.get("missing", [])),
            "matched_rules": matched_rules,
            "warnings": warnings,
        }

    def _safe_observation(self, observation: dict) -> dict:
        allowed = {
            "inventory", "position", "health", "hunger", "time_of_day", "is_daytime",
            "weather", "flags", "structures", "landmarks", "grounded_resources",
            "nearby_blocks", "nearby_entities", "visual_analysis", "vlm_analysis",
            "screenshot_analysis", "screenshot_path", "screenshot", "image_path",
            "screenshots", "frame_path", "screenshot_file_status",
            "biome", "light_level", "placed_blocks",
        }
        return {
            key: self._safe_value(value)
            for key, value in observation.items()
            if key in allowed and value not in (None, "", [], {})
        }

    def _safe_actions(self, recent_actions: list[dict]) -> list[dict]:
        safe = []
        for event in recent_actions[-5:]:
            if not isinstance(event, dict):
                continue
            safe.append({
                "action": self._safe_value(event.get("action", event.get("type", {}))),
                "result": self._safe_value(event.get("result", {})),
                "before_inventory": self._safe_value(event.get("before_inventory", {})),
                "after_inventory": self._safe_value(event.get("after_inventory", {})),
            })
        return safe

    def _safe_value(self, value):
        if isinstance(value, dict):
            return {str(k): self._safe_value(v) for k, v in value.items() if v not in (None, "", [], {})}
        if isinstance(value, list):
            return [self._safe_value(item) for item in value[:12]]
        if isinstance(value, (int, float, bool)):
            return value
        return str(value)[:300]

    def _safe_float(self, value) -> float:
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return 0.0

    def _safe_text(self, value, limit: int = 240) -> str:
        text = str(value or "").strip()
        return text[:limit] if text else "no_reason"

    def _string_list(self, value, limit: int = 12) -> list[str]:
        if not isinstance(value, list):
            value = [value] if value else []
        return [self._safe_text(item) for item in value[:limit] if str(item or "").strip()]


class GoalVerifier:
    """Verify common Minecraft goals from observation and action evidence."""

    LOG_ITEMS = [
        "oak_log", "birch_log", "spruce_log", "jungle_log", "acacia_log",
        "dark_oak_log", "mangrove_log",
    ]
    PLANK_ITEMS = [
        "oak_planks", "birch_planks", "spruce_planks", "jungle_planks",
        "acacia_planks", "dark_oak_planks", "mangrove_planks",
    ]
    FOOD_ITEMS = [
        "bread", "apple", "cooked_porkchop", "cooked_beef", "cooked_chicken",
        "baked_potato", "carrot", "potato", "beef", "porkchop", "melon_slice",
    ]

    DEFAULT_VERBS = ["craft", "gather", "collect", "mine", "obtain", "get", "smelt"]
    INVENTORY_GOAL_VERBS = [*DEFAULT_VERBS, "find", "build", "place"]

    MANUAL_ANCHORS = [
        VerifierAnchor("crafting_table", ["crafting table", "workbench"], ["crafting_table"], ["craft", "obtain", "get"]),
        VerifierAnchor("wooden_pickaxe", ["wooden pickaxe"], ["wooden_pickaxe"], ["craft", "obtain", "get"]),
        VerifierAnchor("stone_pickaxe", ["stone pickaxe"], ["stone_pickaxe"], ["craft", "obtain", "get"]),
        VerifierAnchor("iron_pickaxe", ["iron pickaxe"], ["iron_pickaxe"], ["craft", "obtain", "get"]),
        VerifierAnchor("furnace", ["furnace"], ["furnace"], ["craft", "obtain", "get"]),
        VerifierAnchor("torch", ["torches", "torch"], ["torch"], ["craft", "obtain", "get"]),
        VerifierAnchor("iron_ingot", ["iron ingots", "iron ingot"], ["iron_ingot"], ["craft", "smelt", "obtain", "get"]),
        VerifierAnchor("raw_iron", ["raw iron", "iron ore"], ["raw_iron", "iron_ore"], ["mine", "gather", "collect", "obtain", "get"]),
        VerifierAnchor("coal", ["coal", "charcoal"], ["coal", "charcoal"], ["mine", "gather", "collect", "obtain", "get", "find"]),
        VerifierAnchor("cobblestone", ["cobblestone blocks", "cobblestone", "stone blocks"], ["cobblestone", "stone"], ["mine", "gather", "collect", "obtain", "get"]),
        VerifierAnchor("stick", ["sticks", "stick"], ["stick"], ["craft", "gather", "collect", "obtain", "get"]),
        VerifierAnchor("planks", ["wooden planks", "planks"], PLANK_ITEMS, ["craft", "obtain", "get"]),
        VerifierAnchor("oak_log", ["oak logs", "oak log", "logs", "log", "wood"], LOG_ITEMS, ["gather", "collect", "mine", "obtain", "get"]),
    ]

    def __init__(
        self,
        anchors: Optional[list[VerifierAnchor]] = None,
        use_knowledge_base: bool = True,
        skill_library=None,
        goal_critic=None,
    ):
        self.anchors = self._deduplicate_anchors(list(self.MANUAL_ANCHORS) + (anchors or []))
        self.goal_critic = goal_critic
        if use_knowledge_base:
            self.anchors = self._deduplicate_anchors(self.anchors + self._anchors_from_knowledge_base())
        if skill_library is not None:
            self.anchors = self._deduplicate_anchors(self.anchors + self._anchors_from_skill_library(skill_library))

    def verify(
        self,
        goal: str,
        observation: dict,
        recent_actions: Optional[list[dict]] = None,
    ) -> GoalVerification:
        goal_text = str(goal or "")
        goal_lower = goal_text.lower()
        observation = observation or {}
        recent_actions = recent_actions or []
        checks: list[GoalVerification] = []

        inventory_checks = self._inventory_checks(goal_text, observation, recent_actions)
        checks.extend(inventory_checks)

        safety_check = self._safety_check(goal_text, observation, recent_actions)
        if safety_check:
            checks.append(safety_check)

        shelter_check = self._shelter_check(goal_text, observation, recent_actions)
        if shelter_check:
            checks.append(shelter_check)

        exploration_check = self._exploration_check(goal_text, observation)
        if exploration_check:
            checks.append(exploration_check)

        if not checks and any(token in goal_lower for token in ("eat", "food", "health")):
            checks.append(self._food_check(goal_text, observation, recent_actions))

        if not checks:
            verification = GoalVerification(
                goal=goal_text,
                achieved=False,
                status="unknown",
                confidence=0.0,
                missing=["no deterministic verifier matched this goal"],
            )
            if self.goal_critic:
                return self._apply_goal_critic(verification, observation, recent_actions)
            return verification

        achieved = all(check.achieved for check in checks)
        evidence = []
        missing = []
        matched_rules = []
        target_inventory = {}
        inventory_delta = {}
        confidence = 1.0
        for check in checks:
            evidence.extend(check.evidence)
            missing.extend(check.missing)
            matched_rules.extend(check.matched_rules)
            target_inventory.update(check.target_inventory)
            for item, delta in check.inventory_delta.items():
                inventory_delta[item] = inventory_delta.get(item, 0) + delta
            confidence = min(confidence, check.confidence)

        return GoalVerification(
            goal=goal_text,
            achieved=achieved,
            status="achieved" if achieved else "failed",
            confidence=round(confidence, 3),
            evidence=evidence,
            missing=missing,
            matched_rules=matched_rules,
            target_inventory=target_inventory,
            inventory_delta=inventory_delta,
        )

    def _apply_goal_critic(
        self,
        verification: GoalVerification,
        observation: dict,
        recent_actions: list[dict],
    ) -> GoalVerification:
        critic = self.goal_critic.review_goal(
            verification.goal,
            observation,
            recent_actions=recent_actions,
            deterministic=verification,
        )
        if not isinstance(critic, dict):
            return verification
        decision = critic.get("decision", "unknown")
        evidence = self._merge_list(verification.evidence, critic.get("evidence", []))
        missing = self._merge_list(verification.missing, critic.get("missing", []))
        matched_rules = self._merge_list(verification.matched_rules, critic.get("matched_rules", []))
        confidence = max(verification.confidence, self._safe_confidence(critic.get("confidence", 0.0)))
        if decision == "achieved":
            return GoalVerification(
                goal=verification.goal,
                achieved=True,
                status="achieved",
                confidence=confidence,
                evidence=evidence,
                missing=[],
                matched_rules=matched_rules,
                target_inventory=verification.target_inventory,
                inventory_delta=verification.inventory_delta,
                critic=critic,
            )
        if decision == "failed":
            return GoalVerification(
                goal=verification.goal,
                achieved=False,
                status="failed",
                confidence=confidence,
                evidence=evidence,
                missing=missing or ["goal critic rejected completion"],
                matched_rules=matched_rules,
                target_inventory=verification.target_inventory,
                inventory_delta=verification.inventory_delta,
                critic=critic,
            )
        verification.critic = critic
        verification.evidence = evidence
        verification.missing = missing
        verification.matched_rules = matched_rules
        verification.confidence = confidence
        return verification

    def _safe_confidence(self, value) -> float:
        try:
            return round(max(0.0, min(1.0, float(value))), 3)
        except (TypeError, ValueError):
            return 0.0

    def _merge_list(self, left, right) -> list[str]:
        merged = []
        for values in (left, right):
            if not isinstance(values, list):
                continue
            for value in values:
                text = str(value)
                if text and text not in merged:
                    merged.append(text)
        return merged

    def _inventory_checks(self, goal: str, observation: dict, recent_actions: list[dict]) -> list[GoalVerification]:
        goal_lower = goal.lower()
        if not any(token in goal_lower for token in self.INVENTORY_GOAL_VERBS):
            return []

        checks = []
        seen = set()
        for anchor in self._ranked_anchors():
            if anchor.canonical in seen:
                continue
            if not self._anchor_verb_matches(anchor, goal_lower):
                continue
            if not any(self._phrase_in_goal(alias, goal_lower) for alias in anchor.phrases):
                continue
            if anchor.canonical == "oak_log" and any(item in seen for item in ("wooden_pickaxe", "planks")):
                continue
            required = self._required_count(goal_lower, anchor.canonical)
            have = self._inventory_count(observation.get("inventory", {}), anchor.inventory_items)
            checks.append(self._inventory_check(goal, anchor, have, required, recent_actions=recent_actions))
            seen.add(anchor.canonical)
        return checks

    def _inventory_check(
        self,
        goal: str,
        anchor: VerifierAnchor,
        have: int,
        required: int,
        recent_actions: Optional[list[dict]] = None,
    ) -> GoalVerification:
        delta = self._inventory_delta_for_anchor(anchor, recent_actions or [])
        positive_delta = sum(count for count in delta.values() if count > 0)
        achieved = have >= required or positive_delta >= required
        evidence = []
        if have >= required:
            evidence.append(f"inventory has {have}/{required} {anchor.canonical}")
        if positive_delta > 0:
            evidence.append(f"inventory delta gained {positive_delta} {anchor.canonical}")
        return GoalVerification(
            goal=goal,
            achieved=achieved,
            status="achieved" if achieved else "failed",
            confidence=anchor.confidence,
            evidence=evidence if achieved else [],
            missing=[] if achieved else [f"need {required} {anchor.canonical}, have {have}"],
            matched_rules=[f"inventory:{anchor.canonical}", f"anchor:{anchor.source}"],
            target_inventory={anchor.inventory_items[0]: required},
            inventory_delta=delta,
        )

    def _safety_check(
        self,
        goal: str,
        observation: dict,
        recent_actions: list[dict],
    ) -> Optional[GoalVerification]:
        goal_lower = goal.lower()
        if not any(token in goal_lower for token in ("attack", "hostile", "flee", "defend")):
            return None
        hostiles = [e for e in observation.get("nearby_entities", []) if e.get("hostile")]
        close_hostiles = [e for e in hostiles if e.get("distance", 999) < 8]
        attack_success = self._recent_success(recent_actions, "attack")
        achieved = not close_hostiles or attack_success
        evidence = []
        if not close_hostiles:
            evidence.append("no hostile mob within 8 blocks")
        if attack_success:
            evidence.append("recent attack action succeeded")
        missing = [] if achieved else ["hostile mob still within 8 blocks"]
        return GoalVerification(
            goal=goal,
            achieved=achieved,
            status="achieved" if achieved else "failed",
            confidence=0.85,
            evidence=evidence,
            missing=missing,
            matched_rules=["safety:hostile_distance"],
        )

    def _shelter_check(
        self,
        goal: str,
        observation: dict,
        recent_actions: list[dict],
    ) -> Optional[GoalVerification]:
        goal_lower = goal.lower()
        if "shelter" not in goal_lower and "nightfall" not in goal_lower:
            return None
        if "shelter_verification" in observation:
            report = observation.get("shelter_verification")
            report = report if isinstance(report, dict) else {}
            achieved = is_machine_verified_shelter(report)
            issues = [str(issue) for issue in report.get("issues", []) if str(issue)]
            return GoalVerification(
                goal=goal,
                achieved=achieved,
                status="achieved" if achieved else "failed",
                confidence=1.0,
                evidence=(
                    [
                        f"machine shelter verifier {report.get('verifier_id')} passed",
                        f"strategy={report.get('strategy')}",
                    ]
                    if achieved else []
                ),
                missing=[] if achieved else (issues or ["machine shelter verification did not pass"]),
                matched_rules=["world:m4_machine_shelter"],
            )
        flags = set(str(flag).lower() for flag in observation.get("flags", []))
        structures = observation.get("structures", {}) if isinstance(observation.get("structures", {}), dict) else {}
        placed_blocks = observation.get("placed_blocks", []) or []
        achieved = bool(
            {"in_shelter", "shelter_built", "shelter_frame_complete"} & flags
            or structures.get("shelter")
            or len(placed_blocks) >= 6
            or self._recent_success(recent_actions, "place")
        )
        return GoalVerification(
            goal=goal,
            achieved=achieved,
            status="achieved" if achieved else "failed",
            confidence=0.75,
            evidence=["shelter evidence present"] if achieved else [],
            missing=[] if achieved else ["no shelter flag, structure, or sufficient placed-block evidence"],
            matched_rules=["world:shelter"],
        )

    def _exploration_check(self, goal: str, observation: dict) -> Optional[GoalVerification]:
        goal_lower = goal.lower()
        if not any(token in goal_lower for token in ("scout", "landmark", "inspect nearby")):
            return None
        landmarks = observation.get("landmarks", []) or []
        grounded = observation.get("grounded_resources", []) or []
        nearby_blocks = observation.get("nearby_blocks", []) or []
        achieved = bool(landmarks or grounded or nearby_blocks)
        return GoalVerification(
            goal=goal,
            achieved=achieved,
            status="achieved" if achieved else "failed",
            confidence=0.65,
            evidence=["new landmark/resource/block observation present"] if achieved else [],
            missing=[] if achieved else ["no landmark or nearby-resource evidence"],
            matched_rules=["world:exploration"],
        )

    def _food_check(
        self,
        goal: str,
        observation: dict,
        recent_actions: list[dict],
    ) -> GoalVerification:
        inventory = observation.get("inventory", {})
        food_count = self._inventory_count(inventory, self.FOOD_ITEMS)
        health = observation.get("health", 20)
        eat_success = self._recent_success(recent_actions, "use_item") or self._recent_success(recent_actions, "eat")
        achieved = health >= 10 or eat_success or food_count > 0 and "find food" in goal.lower()
        evidence = []
        if health >= 10:
            evidence.append(f"health is {health}")
        if eat_success:
            evidence.append("recent food-use action succeeded")
        if food_count > 0 and "find food" in goal.lower():
            evidence.append(f"inventory has {food_count} food item(s)")
        return GoalVerification(
            goal=goal,
            achieved=achieved,
            status="achieved" if achieved else "failed",
            confidence=0.75,
            evidence=evidence,
            missing=[] if achieved else ["health still low and no food evidence"],
            matched_rules=["world:food_health"],
        )

    def _required_count(self, goal_lower: str, canonical: str) -> int:
        match = re.search(r"\b(\d+)\b", goal_lower)
        if match:
            return max(1, int(match.group(1)))
        if canonical == "torch" and "torches" in goal_lower:
            return 1
        return 1

    def _inventory_count(self, inventory: dict, items: list[str]) -> int:
        total = 0
        for item in items:
            try:
                total += int(inventory.get(item, 0) or 0)
            except (TypeError, ValueError):
                continue
        return total

    def _phrase_in_goal(self, phrase: str, goal_lower: str) -> bool:
        pattern = r"(?<![a-z0-9_])" + re.escape(phrase.lower()) + r"(?![a-z0-9_])"
        return bool(re.search(pattern, goal_lower))

    def _recent_success(self, recent_actions: list[dict], action_type: str) -> bool:
        for event in recent_actions[-5:]:
            action = event.get("action", event)
            result = event.get("result", {})
            if action.get("type") == action_type and result.get("success", True):
                return True
        return False

    def _anchors_from_knowledge_base(self) -> list[VerifierAnchor]:
        """Mine verifier anchors from recipes and graph resource drops."""
        try:
            from singularity.data.knowledge_base import KnowledgeBase
        except Exception:
            return []

        try:
            kb = KnowledgeBase()
        except Exception:
            return []

        anchors = []
        for item, recipe in kb.recipes.items():
            phrases = self._item_phrases(item)
            category = recipe.get("category", "")
            verbs = ["craft", "obtain", "get"]
            if category == "smelting" or item.endswith("_ingot"):
                verbs.append("smelt")
            anchors.append(VerifierAnchor(
                canonical=item,
                phrases=phrases,
                inventory_items=[item],
                verbs=verbs,
                source="recipe",
                confidence=0.9,
                metadata={
                    "output": recipe.get("output", 1),
                    "ingredients": recipe.get("ingredients", {}),
                    "category": category,
                },
            ))

        if kb.graph:
            for block, drop in kb.graph.resource_drops.items():
                inventory_items = [drop]
                if block != drop:
                    inventory_items.append(block)
                anchors.append(VerifierAnchor(
                    canonical=drop,
                    phrases=sorted(set(self._item_phrases(block) + self._item_phrases(drop))),
                    inventory_items=inventory_items,
                    verbs=["mine", "gather", "collect", "obtain", "get", "find"],
                    source="resource_drop",
                    confidence=0.88,
                    metadata={
                        "block": block,
                        "drop": drop,
                        "required_tool_tier": kb.required_tool_tier(block),
                        "recommended_tool": kb.recommended_tool_for(block),
                    },
                ))
        return anchors

    def _anchors_from_skill_library(self, skill_library) -> list[VerifierAnchor]:
        """Mine verifier anchors from reviewed/custom skill postconditions."""
        anchors = []
        skills = []
        if hasattr(skill_library, "list_skills"):
            try:
                skills = skill_library.list_skills()
            except Exception:
                skills = []
        elif hasattr(skill_library, "skills"):
            skills = list(getattr(skill_library, "skills", {}).values())

        for skill in skills:
            postconditions = getattr(skill, "postconditions", {}) or {}
            inventory_targets = self._postcondition_inventory(postconditions)
            if not inventory_targets:
                continue
            skill_name = getattr(skill, "name", "")
            description = getattr(skill, "description", "")
            for item, count in inventory_targets.items():
                phrases = set(self._item_phrases(item))
                verbs = self._verbs_from_skill_text(f"{skill_name} {description}")
                anchors.append(VerifierAnchor(
                    canonical=item,
                    phrases=sorted(phrases, key=len, reverse=True),
                    inventory_items=[item],
                    verbs=verbs,
                    source="skill_postcondition",
                    confidence=0.86,
                    metadata={
                        "skill": skill_name,
                        "description": description,
                        "required_count": count,
                    },
                ))
        return anchors

    def _postcondition_inventory(self, postconditions: dict) -> dict[str, int]:
        if not isinstance(postconditions, dict):
            return {}
        if isinstance(postconditions.get("inventory"), dict):
            return {
                str(item): max(1, int(count or 1))
                for item, count in postconditions["inventory"].items()
                if self._is_count_like(count)
            }
        reserved = {"flags", "health_at_least", "position", "nearby_blocks", "nearby_entities"}
        return {
            str(item): max(1, int(count or 1))
            for item, count in postconditions.items()
            if item not in reserved and self._is_count_like(count)
        }

    def _inventory_delta_for_anchor(self, anchor: VerifierAnchor, recent_actions: list[dict]) -> dict[str, int]:
        delta: dict[str, int] = {}
        for event in recent_actions[-5:]:
            before = self._event_inventory(event, "before")
            after = self._event_inventory(event, "after")
            if not before and not after:
                continue
            for item in anchor.inventory_items:
                change = int(after.get(item, 0) or 0) - int(before.get(item, 0) or 0)
                if change:
                    delta[item] = delta.get(item, 0) + change
        return delta

    def _event_inventory(self, event: dict, side: str) -> dict:
        if not isinstance(event, dict):
            return {}
        direct_key = f"{side}_inventory"
        if isinstance(event.get(direct_key), dict):
            return event[direct_key]
        observation_key = f"{side}_observation"
        observation = event.get(observation_key, {})
        if isinstance(observation, dict) and isinstance(observation.get("inventory"), dict):
            return observation["inventory"]
        return {}

    def _item_phrases(self, item: str) -> list[str]:
        spaced = str(item).replace("_", " ").strip().lower()
        phrases = {str(item).lower(), spaced}
        if spaced and not spaced.endswith("s"):
            phrases.add(f"{spaced}s")
        return sorted(phrases, key=len, reverse=True)

    def _verbs_from_skill_text(self, text: str) -> list[str]:
        text = str(text).lower()
        verbs = [
            verb for verb in [*self.DEFAULT_VERBS, "find", "build", "place"]
            if self._phrase_in_goal(verb, text)
        ]
        return sorted(set(verbs or self.DEFAULT_VERBS))

    def _ranked_anchors(self) -> list[VerifierAnchor]:
        return sorted(
            self.anchors,
            key=lambda anchor: (
                max((len(phrase) for phrase in anchor.phrases), default=0),
                anchor.confidence,
                1 if anchor.source == "manual" else 0,
            ),
            reverse=True,
        )

    def _deduplicate_anchors(self, anchors: list[VerifierAnchor]) -> list[VerifierAnchor]:
        by_key: dict[tuple[str, tuple[str, ...]], VerifierAnchor] = {}
        for anchor in anchors:
            phrases = tuple(sorted(set(anchor.phrases)))
            key = (anchor.canonical, tuple(sorted(anchor.inventory_items)))
            existing = by_key.get(key)
            if existing:
                existing.phrases = sorted(set(existing.phrases) | set(phrases), key=len, reverse=True)
                existing.verbs = sorted(set(existing.verbs) | set(anchor.verbs))
                existing.confidence = max(existing.confidence, anchor.confidence)
                existing.metadata.update(anchor.metadata)
                if existing.source != "manual" and anchor.source == "manual":
                    existing.source = "manual"
            else:
                anchor.phrases = sorted(set(anchor.phrases), key=len, reverse=True)
                anchor.verbs = sorted(set(anchor.verbs or self.DEFAULT_VERBS))
                by_key[key] = anchor
        return list(by_key.values())

    def _anchor_verb_matches(self, anchor: VerifierAnchor, goal_lower: str) -> bool:
        verbs = anchor.verbs or self.DEFAULT_VERBS
        return any(self._phrase_in_goal(verb, goal_lower) for verb in verbs)

    def _is_count_like(self, value) -> bool:
        if isinstance(value, bool):
            return False
        try:
            int(value)
            return True
        except (TypeError, ValueError):
            return False

    def _keywords(self, text: str) -> set[str]:
        cleaned = []
        for ch in str(text).lower():
            cleaned.append(ch if ch.isalnum() or ch == "_" else " ")
        return {word for word in "".join(cleaned).split() if len(word) > 2}
