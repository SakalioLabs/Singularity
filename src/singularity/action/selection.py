"""Verifier-guided candidate action selection for Minecraft actions."""
from dataclasses import dataclass, field
from typing import Optional

from singularity.action.verifier import ActionVerifier
from singularity.data.knowledge_base import KnowledgeBase


@dataclass
class ActionCandidateScore:
    """A scored candidate action with verifier evidence."""

    action: dict
    source: str
    source_index: int
    verification: dict
    score: float
    reason: str = ""

    def as_dict(self) -> dict:
        return {
            "action": self.action,
            "source": self.source,
            "source_index": self.source_index,
            "verification": self.verification,
            "score": round(float(self.score), 3),
            "reason": self.reason,
        }


@dataclass
class ActionCandidateSelection:
    """A conservative choice among planner and repair candidates."""

    original_action: dict
    selected_action: dict
    selected_index: int
    changed: bool
    reason: str
    candidates: list[ActionCandidateScore] = field(default_factory=list)

    def as_dict(self) -> dict:
        original = self.candidates[0].verification if self.candidates else {}
        selected = self.candidates[self.selected_index].verification if 0 <= self.selected_index < len(self.candidates) else {}
        return {
            "original_action": self.original_action,
            "selected_action": self.selected_action,
            "selected_index": self.selected_index,
            "changed": self.changed,
            "reason": self.reason,
            "candidate_count": len(self.candidates),
            "original_verification": original,
            "selected_verification": selected,
            "candidates": [candidate.as_dict() for candidate in self.candidates],
        }


class ActionCandidateSelector:
    """Select a verifier-feasible repair candidate for rejected planner actions."""

    STATUS_WEIGHTS = {"accept": 1.0, "review": 0.55, "reject": 0.0}

    def __init__(
        self,
        verifier: Optional[ActionVerifier] = None,
        knowledge_base: Optional[KnowledgeBase] = None,
    ):
        self.kb = knowledge_base or getattr(verifier, "kb", None) or KnowledgeBase()
        self.verifier = verifier or ActionVerifier(self.kb)

    def select(
        self,
        action: dict,
        world_state: dict = None,
        goal: str = "",
        alternatives: Optional[list[dict]] = None,
    ) -> ActionCandidateSelection:
        """Return the original action unless it is rejected and a repair is feasible."""
        state = world_state if isinstance(world_state, dict) else {}
        candidate_specs = [{"action": action, "source": "planner", "reason": "planner action"}]
        for alternative in alternatives or []:
            if isinstance(alternative, dict):
                candidate_specs.append({"action": alternative, "source": "alternative", "reason": "external alternative"})

        original_decision = self.verifier.verify(action, state, goal=goal).as_dict()
        if original_decision.get("status") == "reject":
            for repair in self._repair_candidates(action, original_decision, state, goal=goal):
                candidate_specs.append(repair)

        candidate_specs = self._dedupe_candidates(candidate_specs)
        scores = []
        for index, spec in enumerate(candidate_specs):
            candidate_action = spec.get("action", {}) if isinstance(spec.get("action", {}), dict) else {}
            verification = self.verifier.verify(candidate_action, state, goal=goal).as_dict()
            scores.append(ActionCandidateScore(
                action=candidate_action,
                source=str(spec.get("source") or "candidate"),
                source_index=index,
                verification=verification,
                score=self._candidate_score(candidate_action, verification, spec.get("source") == "repair", goal),
                reason=str(spec.get("reason") or ""),
            ))

        selected_index = 0
        reason = "original action retained"
        if scores and scores[0].verification.get("status") == "reject":
            feasible = [
                (index, candidate)
                for index, candidate in enumerate(scores)
                if candidate.verification.get("status") != "reject"
            ]
            if feasible:
                selected_index, selected = max(feasible, key=lambda item: (item[1].score, -item[0]))
                reason = f"selected {selected.source} candidate after original reject"
            else:
                reason = "no feasible repair candidate found"

        selected_action = scores[selected_index].action if scores else action
        return ActionCandidateSelection(
            original_action=action if isinstance(action, dict) else {},
            selected_action=selected_action,
            selected_index=selected_index,
            changed=selected_index != 0,
            reason=reason,
            candidates=scores,
        )

    def _candidate_score(self, action: dict, verification: dict, repair: bool, goal: str) -> float:
        status = str(verification.get("status") or "unknown")
        verifier_score = float(verification.get("score") or 0.0)
        score = (0.72 * self.STATUS_WEIGHTS.get(status, 0.3)) + (0.28 * verifier_score)
        params = action.get("parameters", {}) if isinstance(action, dict) and isinstance(action.get("parameters", {}), dict) else {}
        target = str(params.get("item") or params.get("block") or params.get("name") or "").lower()
        goal_text = str(goal or "").lower()
        if target and target in goal_text:
            score += 0.04
        if repair:
            score += 0.02
        if "observed:" in " ".join(verification.get("evidence", [])):
            score += 0.03
        return round(min(1.0, score), 3)

    def _repair_candidates(self, action: dict, decision: dict, state: dict, goal: str = "") -> list[dict]:
        if not isinstance(action, dict):
            return []
        action_type = str(action.get("type") or "")
        params = action.get("parameters", {}) if isinstance(action.get("parameters", {}), dict) else {}
        repairs = []
        if action_type == "craft":
            for missing in decision.get("missing", []):
                material, amount = self._parse_missing(str(missing))
                repairs.extend(self._material_repair_candidates(material, amount, state))
        elif action_type == "dig":
            for tool in decision.get("missing", []):
                repairs.extend(self._material_repair_candidates(str(tool), 1, state))
        elif action_type in {"place", "equip", "use_item"}:
            item = str(params.get("item") or "")
            repairs.extend(self._material_repair_candidates(item, 1, state))
        return repairs

    def _material_repair_candidates(self, material: str, amount: int, state: dict) -> list[dict]:
        material = str(material or "").strip()
        if not material:
            return []
        inventory = self._inventory(state)
        repairs = []

        if self.kb.get_recipe(material) and self.kb.can_craft(material, inventory):
            repairs.append(self._craft_repair(material, amount, "craft missing prerequisite"))
            return repairs

        if self.kb.get_recipe(material):
            plan = self.kb.get_resource_plan(material, inventory)
            for step in plan.get("craft_steps", []):
                item = str(step.get("item") or "")
                if item and self.kb.can_craft(item, inventory):
                    repairs.append(self._craft_repair(item, step.get("output", 1), f"craft prerequisite for {material}"))
                    return repairs
            for raw, needed in plan.get("missing_raw", {}).items():
                repairs.extend(self._mine_repairs_for_resource(raw, state, f"gather raw prerequisite for {material}", needed))
                if repairs:
                    return repairs

        repairs.extend(self._mine_repairs_for_resource(material, state, "gather missing resource", amount))
        return repairs

    def _mine_repairs_for_resource(self, resource: str, state: dict, reason: str, amount: int = 1) -> list[dict]:
        inventory = self._inventory(state)
        visible_blocks = self._visible_blocks(state)
        visible_names = {block["name"] for block in visible_blocks}
        repairs = []
        for source_block in self.kb.source_blocks_for_resource(resource):
            if source_block not in visible_names:
                continue
            if not self.kb.can_mine(source_block, inventory):
                continue
            action = {"type": "dig", "parameters": {"block": source_block}}
            position = next((block.get("position") for block in visible_blocks if block["name"] == source_block and isinstance(block.get("position"), dict)), None)
            if position:
                action["parameters"].update({key: position[key] for key in ("x", "y", "z") if key in position})
            repairs.append({
                "action": action,
                "source": "repair",
                "reason": f"{reason}: {amount}x {resource} from {source_block}",
            })
        return repairs

    def _craft_repair(self, item: str, count: int, reason: str) -> dict:
        recipe = self.kb.get_recipe(item) or {}
        output = recipe.get("output", count or 1)
        return {
            "action": {"type": "craft", "parameters": {"item": item, "count": output}},
            "source": "repair",
            "reason": reason,
        }

    def _visible_blocks(self, state: dict) -> list[dict]:
        blocks = []
        for key in ("nearby_blocks", "blocks", "visible_blocks", "grounded_resources", "visual_resources", "resources"):
            values = state.get(key, [])
            if not isinstance(values, list):
                continue
            for item in values:
                if isinstance(item, dict):
                    name = item.get("name") or item.get("type") or item.get("block")
                    if name:
                        block = dict(item)
                        block["name"] = str(name)
                        blocks.append(block)
                elif isinstance(item, str):
                    blocks.append({"name": item})
        return blocks

    def _inventory(self, state: dict) -> dict:
        inventory = state.get("inventory", {}) if isinstance(state, dict) else {}
        if not isinstance(inventory, dict):
            return {}
        result = {}
        for item, count in inventory.items():
            try:
                result[str(item)] = int(count)
            except (TypeError, ValueError):
                result[str(item)] = 0
        return result

    def _parse_missing(self, text: str) -> tuple[str, int]:
        if ":" not in text:
            return text, 1
        name, count = text.split(":", 1)
        try:
            return name, max(1, int(count))
        except ValueError:
            return name, 1

    def _dedupe_candidates(self, candidates: list[dict]) -> list[dict]:
        seen = set()
        deduped = []
        for candidate in candidates:
            action = candidate.get("action", {}) if isinstance(candidate, dict) else {}
            key = repr(action)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(candidate)
        return deduped
