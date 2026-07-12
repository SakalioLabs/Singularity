"""Deterministic action verification before Minecraft execution."""
import math
from dataclasses import dataclass, field
from typing import Optional

from singularity.data.knowledge_base import KnowledgeBase


@dataclass
class ActionVerificationDecision:
    """A lightweight pre-execution judgment for a candidate action."""

    action_type: str
    status: str = "accept"  # accept, review, reject
    score: float = 1.0
    reason: str = ""
    missing: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    required: dict = field(default_factory=dict)

    @property
    def rejected(self) -> bool:
        return self.status == "reject"

    def as_dict(self) -> dict:
        data = {
            "action_type": self.action_type,
            "status": self.status,
            "score": round(float(self.score), 3),
            "reason": self.reason,
        }
        if self.missing:
            data["missing"] = list(self.missing)
        if self.evidence:
            data["evidence"] = list(self.evidence)
        if self.required:
            data["required"] = dict(self.required)
        return data


class ActionVerifier:
    """Rule-based verifier for obvious Minecraft action feasibility gaps."""

    SAFE_LOW_INFORMATION_ACTIONS = {"move_to", "walk_to", "look_at", "wait", "chat"}

    def __init__(self, knowledge_base: Optional[KnowledgeBase] = None):
        self.kb = knowledge_base or KnowledgeBase()

    def verify(self, action: dict, world_state: dict = None, goal: str = "") -> ActionVerificationDecision:
        if not isinstance(action, dict):
            return self._decision("unknown", "reject", 0.0, "action is not a structured object")
        action_type = str(action.get("type") or "").strip() or "unknown"
        params = action.get("parameters", {}) if isinstance(action.get("parameters", {}), dict) else {}
        state = world_state if isinstance(world_state, dict) else {}
        inventory = self._inventory(state)

        if action_type in self.SAFE_LOW_INFORMATION_ACTIONS:
            return self._decision(action_type, "accept", 0.9, "navigation or low-impact action")
        if action_type == "craft":
            return self._verify_craft(params, inventory)
        if action_type == "dig":
            return self._verify_dig(params, state, inventory)
        if action_type == "build_shelter_5x5":
            return self._verify_shelter_template(params, state, inventory)
        if action_type == "build_shelter_cell":
            return self._verify_m4_shelter_cell(params, state, inventory)
        if action_type in {"place", "equip", "use_item"}:
            return self._verify_inventory_item_action(action_type, params, inventory)
        if action_type == "attack":
            return self._verify_attack(params, state)
        return self._decision(action_type, "review", 0.4, f"no deterministic verifier for action type {action_type}")

    def _verify_craft(self, params: dict, inventory: dict) -> ActionVerificationDecision:
        item = str(params.get("item") or "").strip()
        if not item:
            return self._decision("craft", "reject", 0.0, "craft action missing item parameter")
        recipe = self.kb.get_recipe(item)
        if not recipe:
            return self._decision("craft", "review", 0.4, f"unknown recipe for {item}")
        requested = self._safe_int(params.get("count"), default=recipe.get("output", 1) or 1)
        output = max(1, self._safe_int(recipe.get("output"), default=1))
        craft_calls = max(1, math.ceil(max(1, requested) / output))
        required = {
            material: self._safe_int(count, default=0) * craft_calls
            for material, count in recipe.get("ingredients", {}).items()
        }
        available = {
            material: self.kb.ingredient_count(material, inventory)
            for material in required
        }
        missing = [
            f"{material}:{needed - available.get(material, 0)}"
            for material, needed in required.items()
            if available.get(material, 0) < needed
        ]
        if missing:
            return self._decision(
                "craft",
                "reject",
                0.1,
                f"missing ingredients for {item}",
                missing=missing,
                required=required,
            )
        evidence = []
        for material in required:
            sources = self.kb.ingredient_sources(material, inventory)
            if sources:
                evidence.append(
                    f"{material}<=" + "+".join(f"{name}:{count}" for name, count in sorted(sources.items()))
                )
        return self._decision(
            "craft",
            "accept",
            0.95,
            f"ingredients available for {item}",
            evidence=evidence,
            required=required,
        )

    def _verify_dig(self, params: dict, state: dict, inventory: dict) -> ActionVerificationDecision:
        block = str(params.get("block") or params.get("name") or "").strip()
        has_coordinates = all(key in params for key in ("x", "y", "z"))
        if not block and not has_coordinates:
            return self._decision("dig", "reject", 0.0, "dig action missing block or coordinates")
        if not block:
            return self._decision("dig", "review", 0.6, "dig coordinates present but target block is unknown")

        visible = self._visible_block_names(state)
        evidence = [f"observed:{block}"] if block in visible else []
        if visible and block not in visible:
            return self._decision("dig", "review", 0.45, f"{block} not observed near agent", evidence=sorted(visible)[:5])
        if not self.kb.can_mine(block, inventory):
            recommended = self.kb.recommended_tool_for(block)
            return self._decision(
                "dig",
                "reject",
                0.1,
                f"missing required tool for {block}",
                missing=[recommended],
                evidence=evidence,
                required={"tool": recommended, "required_tool_tier": self.kb.required_tool_tier(block)},
            )
        return self._decision("dig", "accept", 0.9, f"available tool can mine {block}", evidence=evidence)

    def _verify_inventory_item_action(self, action_type: str, params: dict, inventory: dict) -> ActionVerificationDecision:
        item = str(params.get("item") or "").strip()
        if not item:
            return self._decision(action_type, "reject", 0.0, f"{action_type} action missing item parameter")
        if inventory.get(item, 0) <= 0:
            return self._decision(action_type, "reject", 0.1, f"{item} not present in inventory", missing=[item])
        return self._decision(action_type, "accept", 0.9, f"{item} available in inventory", evidence=[item])

    def _verify_attack(self, params: dict, state: dict) -> ActionVerificationDecision:
        if params.get("entity_id"):
            return self._decision("attack", "accept", 0.85, "target entity id supplied")
        hostiles = [
            entity for entity in state.get("nearby_entities", [])
            if isinstance(entity, dict) and entity.get("hostile")
        ]
        if hostiles:
            return self._decision("attack", "review", 0.55, "hostile entity visible but no entity_id supplied")
        return self._decision("attack", "reject", 0.1, "attack action missing target entity", missing=["entity_id"])

    def _verify_shelter_template(
        self,
        params: dict,
        state: dict,
        inventory: dict,
    ) -> ActionVerificationDecision:
        origin = params.get("origin", {}) if isinstance(params.get("origin"), dict) else {
            axis: params.get(axis) for axis in ("x", "y", "z")
        }
        try:
            requested = {axis: math.floor(float(origin[axis])) for axis in ("x", "y", "z")}
        except (KeyError, TypeError, ValueError):
            return self._decision(
                "build_shelter_5x5",
                "reject",
                0.0,
                "bounded shelter action requires a finite origin",
                missing=["origin.x", "origin.y", "origin.z"],
            )
        benchmark = state.get("benchmark_context", {}) if isinstance(state.get("benchmark_context"), dict) else {}
        zone = benchmark.get("construction_zone", {}) if isinstance(benchmark.get("construction_zone"), dict) else {}
        expected = zone.get("origin", {}) if isinstance(zone.get("origin"), dict) else {}
        try:
            expected = {axis: math.floor(float(expected[axis])) for axis in ("x", "y", "z")}
        except (KeyError, TypeError, ValueError):
            return self._decision(
                "build_shelter_5x5",
                "reject",
                0.0,
                "M2 construction zone is missing from observed benchmark context",
                missing=["benchmark_context.construction_zone.origin"],
            )
        if requested != expected:
            return self._decision(
                "build_shelter_5x5",
                "reject",
                0.0,
                "requested shelter origin is outside the fixed construction zone",
                required={"origin": expected},
            )
        material = str(params.get("material") or "").strip()
        allowed = {
            "cobblestone", "oak_planks", "spruce_planks", "birch_planks",
            "jungle_planks", "acacia_planks", "dark_oak_planks",
        }
        if material not in allowed:
            return self._decision(
                "build_shelter_5x5",
                "reject",
                0.0,
                "shelter material is not allowlisted",
                missing=["allowlisted material"],
            )
        required_count = 55
        if inventory.get(material, 0) < required_count:
            return self._decision(
                "build_shelter_5x5",
                "reject",
                0.1,
                "insufficient material for fixed 5x5 shelter template",
                missing=[f"{material}:{required_count - inventory.get(material, 0)}"],
                required={material: required_count},
            )
        return self._decision(
            "build_shelter_5x5",
            "accept",
            0.98,
            "origin, material budget, and bounded template are verified",
            evidence=[material, "m2-fixed-v1:construction_zone"],
            required={"origin": expected, material: required_count},
        )

    def _verify_m4_shelter_cell(
        self,
        params: dict,
        state: dict,
        inventory: dict,
    ) -> ActionVerificationDecision:
        shelter = state.get("shelter_verification", {})
        shelter = shelter if isinstance(shelter, dict) else {}
        evidence = shelter.get("coordinate_evidence", {})
        evidence = evidence if isinstance(evidence, dict) else {}
        expected_origin = evidence.get("player_cell", {})
        expected_origin = expected_origin if isinstance(expected_origin, dict) else {}
        requested_origin = params.get("origin", {})
        requested_origin = requested_origin if isinstance(requested_origin, dict) else {}
        try:
            expected = {axis: math.floor(float(expected_origin[axis])) for axis in ("x", "y", "z")}
            requested = {axis: math.floor(float(requested_origin[axis])) for axis in ("x", "y", "z")}
        except (KeyError, TypeError, ValueError):
            return self._decision(
                "build_shelter_cell",
                "reject",
                0.0,
                "M4 sealed-cell action requires the current machine player_cell origin",
                missing=["origin.x", "origin.y", "origin.z"],
            )
        if shelter.get("verifier_id") != "m4-sealed-cell-shelter-verifier-v1":
            return self._decision(
                "build_shelter_cell", "reject", 0.0,
                "M4 sealed-cell verifier evidence is missing",
            )
        if shelter.get("passed") is True:
            return self._decision(
                "build_shelter_cell", "reject", 0.0,
                "machine shelter is already verified",
            )
        if requested != expected:
            return self._decision(
                "build_shelter_cell", "reject", 0.0,
                "requested sealed-cell origin does not match current player cell",
                required={"origin": expected},
            )
        material = str(params.get("material") or "").strip()
        allowed = {
            "cobblestone", "dirt", "oak_planks", "spruce_planks", "birch_planks",
            "jungle_planks", "acacia_planks", "dark_oak_planks", "mangrove_planks",
            "cherry_planks", "bamboo_planks", "crimson_planks", "warped_planks",
        }
        if material not in allowed:
            return self._decision(
                "build_shelter_cell", "reject", 0.0,
                "sealed-cell material is not allowlisted",
                missing=["allowlisted material"],
            )
        required_count = 10
        if inventory.get(material, 0) < required_count:
            return self._decision(
                "build_shelter_cell", "reject", 0.1,
                f"sealed-cell template requires {required_count} {material} including one temporary scaffold",
                missing=[f"{material}:{required_count - inventory.get(material, 0)}"],
                required={material: required_count},
            )
        return self._decision(
            "build_shelter_cell", "accept", 0.98,
            "bounded M4 sealed-cell origin and material are machine-grounded",
            evidence=[f"origin:{expected['x']},{expected['y']},{expected['z']}", material],
            required={material: required_count},
        )

    def _visible_block_names(self, state: dict) -> set[str]:
        names = set()
        for key in ("nearby_blocks", "blocks", "visible_blocks", "grounded_resources", "visual_resources", "resources"):
            values = state.get(key, [])
            if not isinstance(values, list):
                continue
            for item in values:
                if isinstance(item, dict):
                    name = item.get("name") or item.get("type") or item.get("block")
                    if name:
                        names.add(str(name))
                elif isinstance(item, str):
                    names.add(item)
        return names

    def _inventory(self, state: dict) -> dict:
        inventory = state.get("inventory", {}) if isinstance(state, dict) else {}
        if not isinstance(inventory, dict):
            return {}
        return {
            str(item): self._safe_int(count, default=0)
            for item, count in inventory.items()
        }

    def _safe_int(self, value, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _decision(
        self,
        action_type: str,
        status: str,
        score: float,
        reason: str,
        missing: Optional[list[str]] = None,
        evidence: Optional[list[str]] = None,
        required: Optional[dict] = None,
    ) -> ActionVerificationDecision:
        return ActionVerificationDecision(
            action_type=action_type,
            status=status,
            score=score,
            reason=reason,
            missing=missing or [],
            evidence=evidence or [],
            required=required or {},
        )
