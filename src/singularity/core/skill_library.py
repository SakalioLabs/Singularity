"""Skill library — stores, versions, and retrieves reusable action skills."""
import json
import os
import time
import logging
from dataclasses import asdict, dataclass, field
from typing import Optional

logger = logging.getLogger("singularity.skills")


@dataclass
class Skill:
    name: str
    description: str = ""
    parameters: dict = field(default_factory=dict)
    preconditions: dict = field(default_factory=dict)
    postconditions: dict = field(default_factory=dict)
    required_items: list = field(default_factory=list)
    failure_modes: list = field(default_factory=list)
    implementation: str = ""  # code or action sequence
    examples: list = field(default_factory=list)
    version: str = "1.0"
    success_rate: float = 0.0
    total_uses: int = 0
    successful_uses: int = 0
    last_used: Optional[str] = None
    layer: str = "composite"  # primitive, composite, strategic, social, meta
    notes: str = ""


class SkillLibrary:
    def __init__(self, storage_path: str = "workspace/skills", persist: bool = False):
        self.storage_path = storage_path
        self.persist = persist
        self.custom_path = os.path.join(storage_path, "custom_skills.jsonl")
        self.skills: dict[str, Skill] = {}
        os.makedirs(storage_path, exist_ok=True)
        self._load_builtin_skills()
        if self.persist:
            self._load_custom_skills()

    def _load_builtin_skills(self):
        """Load pre-defined skill templates."""
        builtins = [
            Skill("move_to", "Navigate to target coordinates", {"x": "float", "z": "float"}, layer="primitive"),
            Skill("look_at", "Look at target position", {"x": "float", "y": "float", "z": "float"}, layer="primitive"),
            Skill("dig_block", "Dig block at position", {"x": "int", "y": "int", "z": "int"}, layer="primitive"),
            Skill("place_block", "Place block at position", {"x": "int", "y": "int", "z": "int", "item": "str"}, layer="primitive"),
            Skill("craft_item", "Craft item from recipe", {"item": "str", "count": "int"}, layer="primitive"),
            Skill("attack_entity", "Attack nearest hostile entity", {}, layer="primitive"),
            Skill("eat_food", "Eat best available food", {}, layer="primitive"),
            Skill("gather_wood", "Find and chop trees for logs", {"wood_type": "str", "quantity": "int"}, layer="composite",
                  success_rate=0.0, notes="Works best with axe. Hand gathering is slow."),
            Skill("craft_tools", "Craft tools from available materials", {"tool_type": "str", "material": "str"}, layer="composite"),
            Skill("mine_stone", "Mine cobblestone underground", {"quantity": "int"}, layer="composite"),
            Skill("mine_iron", "Find and mine iron ore", {"quantity": "int"}, layer="composite"),
            Skill("smelt_iron", "Smelt raw iron into ingots", {"quantity": "int"}, layer="composite"),
            Skill("build_shelter", "Build a simple shelter", {"size": "str"}, layer="composite"),
            Skill("defend_self", "Defend against hostile mobs", {"mode": "str"}, layer="composite"),
            Skill("navigate_to_target", "Pathfind to coordinates", {"x": "float", "z": "float"}, layer="composite"),
            Skill("survive_first_night", "Complete first night survival", {}, layer="strategic"),
            Skill("prepare_for_mining", "Gather tools and torches for mining", {}, layer="strategic"),
        ]
        for skill in builtins:
            self.skills[skill.name] = skill

    def get_skill(self, name: str) -> Optional[Skill]:
        return self.skills.get(name)

    def list_skills(self, layer: Optional[str] = None) -> list[Skill]:
        if layer:
            return [s for s in self.skills.values() if s.layer == layer]
        return list(self.skills.values())

    def create_skill(self, name: str, description: str, implementation: str, persist: Optional[bool] = None, **kwargs) -> Skill:
        skill = Skill(name=name, description=description, implementation=implementation, **kwargs)
        self.skills[name] = skill
        should_persist = self.persist if persist is None else persist
        if should_persist:
            self._rewrite_custom_skills()
        return skill

    def record_use(self, name: str, success: bool):
        skill = self.skills.get(name)
        if skill:
            skill.total_uses += 1
            if success:
                skill.successful_uses += 1
            skill.success_rate = skill.successful_uses / skill.total_uses if skill.total_uses > 0 else 0
            skill.last_used = time.strftime("%Y-%m-%d")

    def get_recommended_skills(self, goal: str, world_state: dict) -> list[Skill]:
        """Return skills that match the current context, sorted by success rate and policy relevance."""
        candidates = [s for s in self.skills.values() if s.total_uses > 0]
        candidates.extend(
            skill for skill in self._policy_skills(goal, world_state)
            if skill not in candidates
        )
        candidates.sort(key=lambda s: s.success_rate, reverse=True)
        return candidates[:5]

    def get_policy_skill_hints(self, goal: str, world_state: dict, limit: int = 5) -> list[str]:
        """Return concise online hints from approved causal/failure-correction skills."""
        hints = []
        for skill in self._policy_skills(goal, world_state):
            payload = self._implementation_payload(skill)
            if payload.get("type") == "causal_summary_skill":
                action = payload.get("action_template", {})
                hints.append(
                    f"{skill.name}: prefer {self._format_action(action)} when context matches learned causal evidence"
                )
            elif payload.get("type") == "failure_correction_skill":
                avoid = payload.get("avoid_action_template", {})
                sequence = payload.get("correction_sequence", [])
                hints.append(
                    f"{skill.name}: if {self._format_action(avoid)} fails, try "
                    f"{' -> '.join(self._format_action(action) for action in sequence[:4])}"
                )
            if len(hints) >= limit:
                break
        return hints

    def find_failure_correction(self, action: dict, result: dict = None, world_state: dict = None) -> Optional[tuple[Skill, dict]]:
        """Find an approved failure-correction skill for a failed action."""
        matches = []
        for skill in self.skills.values():
            payload = self._implementation_payload(skill)
            if payload.get("type") != "failure_correction_skill":
                continue
            avoid = payload.get("avoid_action_template", {})
            if not self._action_matches_template(action, avoid):
                continue
            score = self._policy_relevance_score(skill, "", world_state or {})
            failure_why = str(payload.get("evidence", {}).get("failure_why", "")).lower()
            error = str((result or {}).get("error", "")).lower()
            if failure_why and error and self._keyword_overlap(failure_why, error):
                score += 1.0
            matches.append((score, skill, payload))
        if not matches:
            return None
        matches.sort(key=lambda item: (item[0], item[1].success_rate, item[1].total_uses), reverse=True)
        _, skill, payload = matches[0]
        return skill, payload

    def _load_custom_skills(self):
        if not os.path.exists(self.custom_path):
            return
        try:
            with open(self.custom_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    data = json.loads(line)
                    skill = Skill(**self._filter_skill_fields(data))
                    self.skills[skill.name] = skill
        except Exception as e:
            logger.warning(f"Could not load custom skills: {e}")

    def _rewrite_custom_skills(self):
        custom_skills = [s for s in self.skills.values() if s.name not in self._builtin_skill_names()]
        with open(self.custom_path, "w", encoding="utf-8") as f:
            for skill in custom_skills:
                f.write(json.dumps(asdict(skill), ensure_ascii=False, default=str) + "\n")

    def _filter_skill_fields(self, data: dict) -> dict:
        allowed = set(Skill.__dataclass_fields__.keys())
        return {k: v for k, v in data.items() if k in allowed}

    def _policy_skills(self, goal: str, world_state: dict) -> list[Skill]:
        scored = []
        for skill in self.skills.values():
            payload = self._implementation_payload(skill)
            if payload.get("type") not in {"causal_summary_skill", "failure_correction_skill"}:
                continue
            score = self._policy_relevance_score(skill, goal, world_state)
            if score > 0:
                scored.append((score, skill))
        scored.sort(key=lambda item: (item[0], item[1].success_rate, item[1].total_uses), reverse=True)
        return [skill for _, skill in scored]

    def _policy_relevance_score(self, skill: Skill, goal: str, world_state: dict) -> float:
        payload = self._implementation_payload(skill)
        text = " ".join([
            goal,
            json.dumps(world_state.get("inventory", {}), default=str),
            json.dumps(world_state.get("nearby_blocks", []), default=str),
            json.dumps(world_state.get("nearby_entities", []), default=str),
        ]).lower()
        score = 0.0
        for action in self._payload_actions(payload):
            action_type = str(action.get("type", "")).lower()
            params = action.get("parameters", {}) if isinstance(action.get("parameters", {}), dict) else {}
            subjects = [str(value).lower() for value in params.values() if isinstance(value, (str, int, float))]
            if action_type and action_type in text:
                score += 0.5
            for subject in subjects:
                if subject and subject in text:
                    score += 1.0
        if skill.total_uses:
            score += skill.success_rate
        return score

    def _payload_actions(self, payload: dict) -> list[dict]:
        actions = []
        for key in ("action_template", "avoid_action_template", "primary_correction"):
            if isinstance(payload.get(key), dict):
                actions.append(payload[key])
        for action in payload.get("correction_sequence", []):
            if isinstance(action, dict):
                actions.append(action)
        return actions

    def _implementation_payload(self, skill: Skill) -> dict:
        try:
            payload = json.loads(skill.implementation)
        except (TypeError, ValueError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _action_matches_template(self, action: dict, template: dict) -> bool:
        if not action or not template:
            return False
        if action.get("type") != template.get("type"):
            return False
        action_params = action.get("parameters", {}) if isinstance(action.get("parameters", {}), dict) else {}
        template_params = template.get("parameters", {}) if isinstance(template.get("parameters", {}), dict) else {}
        for key, value in template_params.items():
            if value is None:
                continue
            if key not in action_params or str(action_params.get(key)) != str(value):
                return False
        return True

    def _keyword_overlap(self, left: str, right: str) -> bool:
        return bool(self._keywords(left) & self._keywords(right))

    def _keywords(self, text: str) -> set[str]:
        cleaned = []
        for ch in str(text).lower():
            cleaned.append(ch if ch.isalnum() or ch == "_" else " ")
        return {word for word in "".join(cleaned).split() if len(word) > 2}

    def _format_action(self, action: dict) -> str:
        if not action:
            return "unknown action"
        params = action.get("parameters", {}) if isinstance(action.get("parameters", {}), dict) else {}
        subject = params.get("item") or params.get("block") or params.get("entity") or params.get("target")
        return f"{action.get('type', 'action')}:{subject}" if subject else str(action.get("type", "action"))

    def _builtin_skill_names(self) -> set[str]:
        return {
            "move_to", "look_at", "dig_block", "place_block", "craft_item", "attack_entity", "eat_food",
            "gather_wood", "craft_tools", "mine_stone", "mine_iron", "smelt_iron", "build_shelter",
            "defend_self", "navigate_to_target", "survive_first_night", "prepare_for_mining",
        }
