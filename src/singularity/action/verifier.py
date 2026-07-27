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
    M4_FURNACE_PLACE_LOCAL_SNAPSHOT_POLICY_ID = (
        "m4-bm013-bm014-furnace-place-local-snapshot-v1"
    )
    M4_CRAFTING_TABLE_PLACE_LOCAL_SNAPSHOT_POLICY_ID = (
        "m4-bm013-bm014-crafting-table-place-local-snapshot-v1"
    )
    M4_CRAFTING_TABLE_PLACE_LOCAL_SNAPSHOT_KEY = (
        "m4_crafting_table_place_candidates"
    )
    M4_FURNACE_PLACE_SNAPSHOT_POSITION_COUNT = 36
    M4_FURNACE_PLACE_CANDIDATE_LIMIT = 27
    M4_FURNACE_PLACE_MAX_SNAPSHOT_AGE_MS = 5000.0
    M4_CRAFTING_TABLE_PLACE_SNAPSHOT_POSITION_COUNT = 36
    M4_CRAFTING_TABLE_PLACE_CANDIDATE_LIMIT = 27
    M4_CRAFTING_TABLE_PLACE_MAX_SNAPSHOT_AGE_MS = 5000.0
    M4_FURNACE_REFERENCE_BLOCKS = {
        "grass_block",
        "dirt",
        "stone",
        "cobblestone",
        "gravel",
        "andesite",
        "granite",
        "diorite",
        "deepslate",
        "tuff",
        "crafting_table",
        "coal_ore",
        "deepslate_coal_ore",
        "iron_ore",
        "deepslate_iron_ore",
    }
    M4_CRAFTING_TABLE_REFERENCE_BLOCKS = {
        "grass_block",
        "dirt",
        "stone",
        "cobblestone",
        "gravel",
        "andesite",
        "granite",
        "diorite",
        "deepslate",
        "tuff",
        "coal_ore",
        "deepslate_coal_ore",
        "iron_ore",
        "deepslate_iron_ore",
    }
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
        task_id: str = "",
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
        if action_type == "smelt":
            return self._verify_smelt(params, state, inventory)
        if action_type == "dig":
            return self._verify_dig(params, state, inventory)
        if action_type == "build_shelter_5x5":
            return self._verify_shelter_template(params, state, inventory)
        if action_type == "build_shelter_cell":
            return self._verify_m4_shelter_cell(params, state, inventory)
        if action_type == "place":
            return self._verify_place(
                params,
                state,
                inventory,
                protocol=protocol,
                task_id=task_id,
            )
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

    def _verify_smelt(
        self,
        params: dict,
        state: dict,
        inventory: dict,
    ) -> ActionVerificationDecision:
        item = str(params.get("item") or "").strip()
        if not item:
            return self._decision("smelt", "reject", 0.0, "smelt action missing item parameter")
        recipe = self.kb.get_recipe(item)
        if not recipe or recipe.get("category") != "smelting":
            return self._decision("smelt", "reject", 0.0, f"unsupported smelting recipe for {item}")
        ingredients = dict(recipe.get("ingredients", {}) or {})
        if len(ingredients) != 1:
            return self._decision("smelt", "reject", 0.0, f"ambiguous smelting input for {item}")
        expected_input, input_per_output = next(iter(ingredients.items()))
        input_item = str(params.get("input") or expected_input).strip()
        if input_item != expected_input:
            return self._decision(
                "smelt",
                "reject",
                0.0,
                f"{item} requires input {expected_input}",
                required={"input": expected_input},
            )
        fuel = str(params.get("fuel") or "coal").strip()
        if fuel not in {"coal", "charcoal"}:
            return self._decision("smelt", "reject", 0.0, f"unsupported smelting fuel {fuel}")
        count = params.get("count", 1)
        if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 64:
            return self._decision("smelt", "reject", 0.0, "smelt count must be an integer from 1 to 64")
        output = max(1, self._safe_int(recipe.get("output"), default=1))
        smelt_calls = max(1, math.ceil(count / output))
        input_count = self._safe_int(input_per_output, default=1) * smelt_calls
        fuel_count = max(1, math.ceil(smelt_calls / 8))
        required = {input_item: input_count, fuel: fuel_count}
        missing = [
            f"{name}:{needed - self._safe_int(inventory.get(name), default=0)}"
            for name, needed in required.items()
            if self._safe_int(inventory.get(name), default=0) < needed
        ]
        visible = self._visible_block_names(state)
        if "furnace" not in visible:
            missing.append("nearby_furnace:1")
        if missing:
            return self._decision(
                "smelt",
                "reject",
                0.1,
                f"smelting prerequisites missing for {item}",
                missing=missing,
                required=required,
            )
        return self._decision(
            "smelt",
            "accept",
            0.98,
            f"furnace, input, and fuel available for {item}",
            evidence=[f"observed:furnace", f"input:{input_item}", f"fuel:{fuel}"],
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
        task_id: str,
    ) -> ActionVerificationDecision:
        inventory_decision = self._verify_inventory_item_action("place", params, inventory)
        if inventory_decision.rejected or str(protocol or "") != "m4-fixed-v1":
            return inventory_decision

        policy_id = self.M4_PLACE_TARGET_OCCUPANCY_POLICY_ID
        item = str(params.get("item") or "").strip()
        strict_furnace_snapshot = (
            item == "furnace"
            and str(task_id or "").upper().strip() in {"BM-013", "BM-014"}
        )
        strict_crafting_table_snapshot = (
            item == "crafting_table"
            and str(task_id or "").upper().strip() in {"BM-013", "BM-014"}
        )
        strict_local_snapshot = (
            strict_furnace_snapshot or strict_crafting_table_snapshot
        )
        if strict_crafting_table_snapshot:
            local_snapshot_policy_id = (
                self.M4_CRAFTING_TABLE_PLACE_LOCAL_SNAPSHOT_POLICY_ID
            )
            local_snapshot_key = self.M4_CRAFTING_TABLE_PLACE_LOCAL_SNAPSHOT_KEY
            local_snapshot_position_count = (
                self.M4_CRAFTING_TABLE_PLACE_SNAPSHOT_POSITION_COUNT
            )
            local_snapshot_candidate_limit = (
                self.M4_CRAFTING_TABLE_PLACE_CANDIDATE_LIMIT
            )
        else:
            local_snapshot_policy_id = (
                self.M4_FURNACE_PLACE_LOCAL_SNAPSHOT_POLICY_ID
            )
            local_snapshot_key = "m4_local_place_candidates"
            local_snapshot_position_count = (
                self.M4_FURNACE_PLACE_SNAPSHOT_POSITION_COUNT
            )
            local_snapshot_candidate_limit = (
                self.M4_FURNACE_PLACE_CANDIDATE_LIMIT
            )
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
        if (
            strict_local_snapshot
            and self._integral_block_position(params) != reference
        ):
            return self._decision(
                "place",
                "reject",
                0.0,
                f"M4 {item} place requires exact integral reference coordinates",
                missing=["integral x", "integral y", "integral z"],
                evidence=[
                    f"policy:{local_snapshot_policy_id}",
                ],
                policy_id=local_snapshot_policy_id,
            )

        target = {
            "x": reference["x"],
            "y": reference["y"] + 1,
            "z": reference["z"],
        }
        local_snapshot = None
        if strict_local_snapshot:
            local_snapshot = (
                self._m4_valid_crafting_table_local_snapshot(state)
                if strict_crafting_table_snapshot
                else self._m4_valid_furnace_local_snapshot(state)
            )
            matching_pair = (
                next(
                    (
                        candidate
                        for candidate in local_snapshot["candidates"]
                        if candidate["reference_position"] == reference
                        and candidate["target_position"] == target
                    ),
                    None,
                )
                if local_snapshot is not None
                else None
            )
            if matching_pair is None:
                return self._decision(
                    "place",
                    "reject",
                    0.0,
                    (
                        f"M4 {item} place requires a complete fresh local snapshot "
                        "with the exact reference/target pair"
                    ),
                    missing=[f"{local_snapshot_key}.exact_pair"],
                    evidence=[
                        f"policy:{local_snapshot_policy_id}",
                    ],
                    required={
                        "reference_position": reference,
                        "target_position": target,
                        "snapshot_position_count": local_snapshot_position_count,
                        "candidate_limit": local_snapshot_candidate_limit,
                    },
                    policy_id=local_snapshot_policy_id,
                )

        observed = self._observed_blocks_at(state, target)
        if local_snapshot is not None:
            observed.append(dict(matching_pair["target_block"]))
        occupied = [
            block for block in observed
            if not self._m4_block_is_replaceable(block)
        ]
        required = {
            "target_position": target,
            "target_state": "air_or_replaceable",
        }
        player_policy_id = self.M4_PLACE_TARGET_PLAYER_OCCUPANCY_POLICY_ID
        raw_player_position = (
            local_snapshot["player_position"]
            if local_snapshot is not None
            else state.get("position")
        )
        if (
            local_snapshot is None
            and not isinstance(raw_player_position, dict)
        ):
            raw_player_position = state.get("player_position")
        player_collision = self._m4_player_collision_evidence(raw_player_position)
        current_player_collision = (
            self._m4_player_collision_evidence(
                local_snapshot["current_player_position"],
            )
            if local_snapshot is not None
            else None
        )
        collision_cells = []
        adjacent_references = []
        if player_collision is not None:
            collision_cells = player_collision["cells"]
            if current_player_collision is not None:
                seen_collision_cells = {
                    (cell["x"], cell["y"], cell["z"])
                    for cell in collision_cells
                }
                collision_cells = list(collision_cells)
                for cell in current_player_collision["cells"]:
                    key = (cell["x"], cell["y"], cell["z"])
                    if key not in seen_collision_cells:
                        collision_cells.append(cell)
                        seen_collision_cells.add(key)
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
            if current_player_collision is not None:
                required.update({
                    "current_player_position": (
                        current_player_collision["position"]
                    ),
                    "current_player_collision_box": (
                        current_player_collision["box"]
                    ),
                })
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

        target_intersects_player = target in collision_cells
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

        target_evidence = (
            ",".join(sorted({str(block.get("name") or "air") for block in observed}))
            if observed
            else "not_observed_occupied"
        )
        policy_evidence = [
            f"policy:{policy_id}",
            f"policy:{player_policy_id}",
        ]
        if local_snapshot is not None:
            policy_evidence.append(
                f"policy:{local_snapshot_policy_id}",
            )
        return self._decision(
            "place",
            "accept",
            0.95,
            "requested item is available and the M4 target clears block and player occupancy",
            evidence=[
                item,
                *policy_evidence,
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

    @staticmethod
    def _integral_block_position(values: dict) -> Optional[dict]:
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
            if not math.isfinite(coordinate) or not coordinate.is_integer():
                return None
            position[axis] = int(coordinate)
        return position

    @staticmethod
    def _finite_milliseconds(value) -> Optional[float]:
        if isinstance(value, bool):
            return None
        try:
            milliseconds = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(milliseconds) or milliseconds <= 0:
            return None
        return milliseconds

    @classmethod
    def _m4_valid_furnace_local_snapshot(cls, state: dict) -> Optional[dict]:
        """Validate and normalize one furnace placement snapshot envelope."""
        return cls._m4_valid_local_place_snapshot(
            state,
            snapshot_key="m4_local_place_candidates",
            policy_id=cls.M4_FURNACE_PLACE_LOCAL_SNAPSHOT_POLICY_ID,
            snapshot_position_count=cls.M4_FURNACE_PLACE_SNAPSHOT_POSITION_COUNT,
            candidate_limit=cls.M4_FURNACE_PLACE_CANDIDATE_LIMIT,
            max_snapshot_age_ms=cls.M4_FURNACE_PLACE_MAX_SNAPSHOT_AGE_MS,
            reference_blocks=cls.M4_FURNACE_REFERENCE_BLOCKS,
        )

    @classmethod
    def _m4_valid_crafting_table_local_snapshot(
        cls,
        state: dict,
    ) -> Optional[dict]:
        """Validate the independent owned-table placement snapshot envelope."""
        return cls._m4_valid_local_place_snapshot(
            state,
            snapshot_key=cls.M4_CRAFTING_TABLE_PLACE_LOCAL_SNAPSHOT_KEY,
            policy_id=cls.M4_CRAFTING_TABLE_PLACE_LOCAL_SNAPSHOT_POLICY_ID,
            snapshot_position_count=(
                cls.M4_CRAFTING_TABLE_PLACE_SNAPSHOT_POSITION_COUNT
            ),
            candidate_limit=cls.M4_CRAFTING_TABLE_PLACE_CANDIDATE_LIMIT,
            max_snapshot_age_ms=(
                cls.M4_CRAFTING_TABLE_PLACE_MAX_SNAPSHOT_AGE_MS
            ),
            reference_blocks=cls.M4_CRAFTING_TABLE_REFERENCE_BLOCKS,
        )

    @classmethod
    def _m4_valid_local_place_snapshot(
        cls,
        state: dict,
        *,
        snapshot_key: str,
        policy_id: str,
        snapshot_position_count: int,
        candidate_limit: int,
        max_snapshot_age_ms: float,
        reference_blocks: set[str],
    ) -> Optional[dict]:
        """Validate and normalize one item-specific local placement envelope."""
        if not isinstance(state, dict):
            return None
        snapshot = state.get(snapshot_key)
        if (
            not isinstance(snapshot, dict)
            or snapshot.get("schema_version") != 1
            or snapshot.get("policy_id") != policy_id
            or snapshot.get("machine_snapshot_passed") is not True
            or snapshot.get("source") != "get_shelter_state.blocks"
            or snapshot.get("snapshot_position_count") != snapshot_position_count
            or snapshot.get("candidate_limit") != candidate_limit
        ):
            return None

        candidates = snapshot.get("candidates")
        candidate_count = snapshot.get("candidate_count")
        if (
            not isinstance(candidates, list)
            or isinstance(candidate_count, bool)
            or not isinstance(candidate_count, int)
            or candidate_count != len(candidates)
            or candidate_count > candidate_limit
        ):
            return None

        observed_at_ms = cls._finite_milliseconds(snapshot.get("observed_at_ms"))
        if observed_at_ms is None:
            return None
        state_observed_at_ms = cls._finite_milliseconds(state.get("observed_at_ms"))
        if (
            state_observed_at_ms is not None
            and (
                observed_at_ms > state_observed_at_ms
                or state_observed_at_ms - observed_at_ms
                > max_snapshot_age_ms
            )
        ):
            return None

        player_position = cls._finite_position(snapshot.get("player_position"))
        player_cell = cls._integral_block_position(snapshot.get("player_cell"))
        current_player_position = state.get("position")
        if not isinstance(current_player_position, dict):
            current_player_position = state.get("player_position")
        current_player_position = cls._finite_position(current_player_position)
        if (
            player_position is None
            or player_cell is None
            or current_player_position is None
            or cls._finite_block_position(player_position) != player_cell
            or cls._finite_block_position(current_player_position) != player_cell
        ):
            return None

        normalized_candidates = []
        seen_references = set()
        for candidate in candidates:
            if not isinstance(candidate, dict):
                return None
            reference_block = candidate.get("reference_block")
            target_block = candidate.get("target_block")
            if (
                not isinstance(reference_block, dict)
                or not isinstance(target_block, dict)
            ):
                return None
            reference = cls._integral_block_position(
                reference_block.get("position"),
            )
            target = cls._integral_block_position(target_block.get("position"))
            if (
                reference is None
                or target is None
                or target != {
                    "x": reference["x"],
                    "y": reference["y"] + 1,
                    "z": reference["z"],
                }
            ):
                return None
            reference_key = (
                reference["x"],
                reference["y"],
                reference["z"],
            )
            if reference_key in seen_references:
                return None
            seen_references.add(reference_key)

            reference_name = str(reference_block.get("name") or "").strip()
            target_name = str(target_block.get("name") or "").strip()
            for block in (reference_block, target_block):
                if (
                    block.get("machine_observed") is not True
                    or block.get("machine_state_source")
                    != "get_shelter_state.blocks"
                    or block.get("grounding_policy_id") != policy_id
                ):
                    return None
            if (
                reference_name not in reference_blocks
                or reference_block.get("solid") is not True
                or str(reference_block.get("collision") or "") != "block"
                or target_name not in cls.M4_REPLACEABLE_BLOCKS
                or target_block.get("solid") is not False
                or target_block.get("passable") is not True
                or str(target_block.get("collision") or "") != "empty"
            ):
                return None
            normalized_candidates.append({
                "reference_position": reference,
                "target_position": target,
                "reference_block": dict(reference_block),
                "target_block": dict(target_block),
            })

        return {
            "snapshot": snapshot,
            "observed_at_ms": observed_at_ms,
            "player_cell": player_cell,
            "player_position": player_position,
            "current_player_position": current_player_position,
            "candidates": normalized_candidates,
        }

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
