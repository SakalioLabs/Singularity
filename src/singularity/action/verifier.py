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
    policy_id: str = ""

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
        if self.policy_id:
            data["policy_id"] = self.policy_id
        return data


class ActionVerifier:
    """Rule-based verifier for obvious Minecraft action feasibility gaps."""

    SAFE_LOW_INFORMATION_ACTIONS = {"move_to", "walk_to", "look_at", "wait", "chat"}
    M4_PLACE_TARGET_OCCUPANCY_POLICY_ID = "m4-place-target-occupancy-v1"
    M4_PLACE_TARGET_PLAYER_OCCUPANCY_POLICY_ID = "m4-place-target-player-occupancy-v1"
    M4_PLAYER_WIDTH = 0.6
    M4_PLAYER_HEIGHT = 1.8
    M4_COLLISION_EPSILON = 1e-9
    M4_REPLACEABLE_BLOCKS = {
        "air",
        "cave_air",
        "void_air",
        "short_grass",
        "tall_grass",
        "fern",
        "large_fern",
        "dead_bush",
        "vine",
        "snow",
        "fire",
        "soul_fire",
    }

    def __init__(self, knowledge_base: Optional[KnowledgeBase] = None):
        self.kb = knowledge_base or KnowledgeBase()

    def verify(
        self,
        action: dict,
        world_state: dict = None,
        goal: str = "",
        protocol: str = "",
    ) -> ActionVerificationDecision:
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
        if action_type == "place":
            return self._verify_place(params, state, inventory, protocol=protocol)
        if action_type in {"equip", "use_item"}:
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

    def _verify_place(
        self,
        params: dict,
        state: dict,
        inventory: dict,
        *,
        protocol: str,
    ) -> ActionVerificationDecision:
        inventory_decision = self._verify_inventory_item_action("place", params, inventory)
        if inventory_decision.rejected or str(protocol or "") != "m4-fixed-v1":
            return inventory_decision

        policy_id = self.M4_PLACE_TARGET_OCCUPANCY_POLICY_ID
        reference = self._finite_block_position(params)
        if reference is None:
            return self._decision(
                "place",
                "reject",
                0.0,
                "M4 place action requires finite reference coordinates",
                missing=["x", "y", "z"],
                evidence=[f"policy:{policy_id}"],
                policy_id=policy_id,
            )

        target = {
            "x": reference["x"],
            "y": reference["y"] + 1,
            "z": reference["z"],
        }
        observed = self._observed_blocks_at(state, target)
        occupied = [
            block for block in observed
            if not self._m4_block_is_replaceable(block)
        ]
        required = {
            "target_position": target,
            "target_state": "air_or_replaceable",
        }
        if occupied:
            names = sorted({str(block.get("name") or "unknown") for block in occupied})
            return self._decision(
                "place",
                "reject",
                0.0,
                (
                    f"M4 place target {target['x']},{target['y']},{target['z']} "
                    f"is occupied by {','.join(names)}"
                ),
                evidence=[f"policy:{policy_id}"] + [f"observed_target:{name}" for name in names],
                required=required,
                policy_id=policy_id,
            )

        player_policy_id = self.M4_PLACE_TARGET_PLAYER_OCCUPANCY_POLICY_ID
        raw_player_position = state.get("position")
        if not isinstance(raw_player_position, dict):
            raw_player_position = state.get("player_position")
        player_collision = self._m4_player_collision_evidence(raw_player_position)
        if player_collision is None:
            return self._decision(
                "place",
                "reject",
                0.0,
                "M4 place action requires a finite machine-observed player position",
                missing=["position.x", "position.y", "position.z"],
                evidence=[f"policy:{policy_id}", f"policy:{player_policy_id}"],
                required={
                    **required,
                    "target_player_clearance": "outside_player_collision_cells",
                },
                policy_id=player_policy_id,
            )

        collision_cells = player_collision["cells"]
        target_intersects_player = target in collision_cells
        adjacent_references = self._m4_adjacent_place_references(
            reference,
            collision_cells,
        )
        required.update({
            "player_position": player_collision["position"],
            "player_collision_box": player_collision["box"],
            "player_collision_cells": collision_cells,
            "target_player_clearance": "outside_player_collision_cells",
            "adjacent_reference_candidates": adjacent_references,
            "replan_mode": "next_cycle",
            "replan_candidate_limit": 4,
        })
        if target_intersects_player:
            return self._decision(
                "place",
                "reject",
                0.0,
                (
                    f"M4 place target {target['x']},{target['y']},{target['z']} "
                    "intersects the player's collision cells"
                ),
                evidence=[
                    f"policy:{policy_id}",
                    f"policy:{player_policy_id}",
                    (
                        "player_position:"
                        f"{player_collision['position']['x']},"
                        f"{player_collision['position']['y']},"
                        f"{player_collision['position']['z']}"
                    ),
                    f"target_intersects_player:{str(target_intersects_player).lower()}",
                ],
                required=required,
                policy_id=player_policy_id,
            )

        item = str(params.get("item") or "").strip()
        target_evidence = (
            ",".join(sorted({str(block.get("name") or "air") for block in observed}))
            if observed
            else "not_observed_occupied"
        )
        return self._decision(
            "place",
            "accept",
            0.95,
            "requested item is available and the M4 target clears block and player occupancy",
            evidence=[
                item,
                f"policy:{policy_id}",
                f"policy:{player_policy_id}",
                f"target:{target_evidence}",
                "target_intersects_player:false",
            ],
            required=required,
            policy_id=player_policy_id,
        )

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

    @staticmethod
    def _finite_block_position(values: dict) -> Optional[dict]:
        position = {}
        for axis in ("x", "y", "z"):
            value = values.get(axis)
            if isinstance(value, bool):
                return None
            try:
                coordinate = float(value)
            except (TypeError, ValueError):
                return None
            if not math.isfinite(coordinate):
                return None
            position[axis] = math.floor(coordinate)
        return position

    @staticmethod
    def _finite_position(values: dict) -> Optional[dict]:
        if not isinstance(values, dict):
            return None
        position = {}
        for axis in ("x", "y", "z"):
            value = values.get(axis)
            if isinstance(value, bool):
                return None
            try:
                coordinate = float(value)
            except (TypeError, ValueError):
                return None
            if not math.isfinite(coordinate):
                return None
            position[axis] = coordinate
        return position

    @classmethod
    def _m4_player_collision_evidence(cls, values: dict) -> Optional[dict]:
        position = cls._finite_position(values)
        if position is None:
            return None
        half_width = cls.M4_PLAYER_WIDTH / 2.0
        bounds = {
            "min": {
                "x": position["x"] - half_width,
                "y": position["y"],
                "z": position["z"] - half_width,
            },
            "max": {
                "x": position["x"] + half_width,
                "y": position["y"] + cls.M4_PLAYER_HEIGHT,
                "z": position["z"] + half_width,
            },
            "width": cls.M4_PLAYER_WIDTH,
            "height": cls.M4_PLAYER_HEIGHT,
        }
        axis_cells = {}
        for axis in ("x", "y", "z"):
            first = math.floor(bounds["min"][axis] + cls.M4_COLLISION_EPSILON)
            last = math.floor(bounds["max"][axis] - cls.M4_COLLISION_EPSILON)
            axis_cells[axis] = range(first, last + 1)
        cells = [
            {"x": x, "y": y, "z": z}
            for x in axis_cells["x"]
            for y in axis_cells["y"]
            for z in axis_cells["z"]
        ]
        return {
            "position": position,
            "box": bounds,
            "cells": cells,
        }

    @staticmethod
    def _m4_adjacent_place_references(reference: dict, collision_cells: list[dict]) -> list[dict]:
        occupied = {
            (cell["x"], cell["y"], cell["z"])
            for cell in collision_cells
        }
        candidates = []
        for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            candidate = {
                "x": reference["x"] + dx,
                "y": reference["y"],
                "z": reference["z"] + dz,
            }
            candidate_target = (
                candidate["x"],
                candidate["y"] + 1,
                candidate["z"],
            )
            if candidate_target not in occupied:
                candidates.append(candidate)
        return candidates

    @classmethod
    def _observed_blocks_at(cls, state: dict, target: dict) -> list[dict]:
        observed = []
        for key in ("nearby_blocks", "blocks", "visible_blocks"):
            values = state.get(key, [])
            if not isinstance(values, list):
                continue
            for item in values:
                if not isinstance(item, dict):
                    continue
                raw_position = item.get("position")
                raw_position = raw_position if isinstance(raw_position, dict) else item
                position = cls._finite_block_position(raw_position)
                if position != target:
                    continue
                name = item.get("name") or item.get("block")
                if not name and isinstance(item.get("type"), str):
                    name = item.get("type")
                block = dict(item)
                block["name"] = str(name or "unknown").strip().lower()
                observed.append(block)
        return observed

    @classmethod
    def _m4_block_is_replaceable(cls, block: dict) -> bool:
        name = str(block.get("name") or "").strip().lower()
        return bool(
            block.get("replaceable") is True
            or name in cls.M4_REPLACEABLE_BLOCKS
        )

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
        policy_id: str = "",
    ) -> ActionVerificationDecision:
        return ActionVerificationDecision(
            action_type=action_type,
            status=status,
            score=score,
            reason=reason,
            missing=missing or [],
            evidence=evidence or [],
            required=required or {},
            policy_id=str(policy_id or ""),
        )
