"""Machine-checkable M4 shelter verification.

The first G3 baseline intentionally accepts one bounded shape only: a sealed
one-cell interior with a solid floor, two passable player cells, four
two-block-high wall columns, and a full-block roof. Every wall and roof block
must be attributable to a successful placement in the current episode.
"""

from __future__ import annotations

import hashlib
import json
import math


M4_SHELTER_VERIFIER_ID = "m4-sealed-cell-shelter-verifier-v1"
M4_SHELTER_REQUIRED_CHECKS = (
    "physical_barriers",
    "overhead_cover_or_approved_alternative",
    "hostile_path_risk",
    "standable_interior",
    "episode_block_delta_or_approved_natural_safe_point",
    "coordinate_evidence",
)
M4_SHELTER_PASSABLE_INTERIOR_BLOCKS = frozenset({"air", "cave_air", "void_air"})
M4_SHELTER_UNSAFE_SOLID_BLOCKS = frozenset({
    "cactus",
    "campfire",
    "fire",
    "lava",
    "magma_block",
    "powder_snow",
    "soul_campfire",
    "soul_fire",
    "sweet_berry_bush",
    "water",
})
M4_SHELTER_CONTRACT = {
    "id": M4_SHELTER_VERIFIER_ID,
    "strategy": "sealed_cell_v1",
    "snapshot_source": "mineflayer_world_state",
    "horizontal_radius": 1,
    "vertical_offsets": [-1, 0, 1, 2],
    "snapshot_position_count": 36,
    "wall_height": 2,
    "full_block_collision_required": True,
    "passable_interior_blocks": sorted(M4_SHELTER_PASSABLE_INTERIOR_BLOCKS),
    "unsafe_solid_blocks": sorted(M4_SHELTER_UNSAFE_SOLID_BLOCKS),
    "current_episode_structure_delta_required": True,
    "required_structure_block_count": 9,
    "approved_natural_safe_points": [],
    "required_checks": list(M4_SHELTER_REQUIRED_CHECKS),
}
M4_SHELTER_CONTRACT_SHA256 = hashlib.sha256(
    json.dumps(
        M4_SHELTER_CONTRACT,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
).hexdigest()


class M4ShelterVerifier:
    """Verify the bounded G3 shelter baseline from raw block state and delta."""

    DIRECTIONS = (
        ("north", 0, -1),
        ("east", 1, 0),
        ("south", 0, 1),
        ("west", -1, 0),
    )

    def verify(self, machine_state: dict, episode_block_delta: dict | None = None) -> dict:
        state = machine_state if isinstance(machine_state, dict) else {}
        delta = episode_block_delta if isinstance(episode_block_delta, dict) else {}
        player_position = self._position(state.get("player_position"), integral=False)
        player_cell = self._position(state.get("player_cell"), integral=True)
        expected_cell = self._floor_position(player_position)
        blocks, duplicate_positions = self._block_map(state.get("blocks"))

        required_positions = self._required_positions(player_cell)
        required_position_values = [
            required_positions.get(name, {})
            for name in ("floor", "feet", "head", "roof")
        ]
        required_position_values.extend(
            position
            for _, lower, upper in required_positions.get("wall_columns", [])
            for position in (lower, upper)
        )
        required_keys = {self._key(position) for position in required_position_values if position}
        snapshot_keys = self._snapshot_keys(player_cell)
        machine_snapshot_passed = bool(
            state.get("success") is True
            and state.get("type") == "m4_shelter_machine_snapshot"
            and state.get("source") == M4_SHELTER_CONTRACT["snapshot_source"]
            and player_position
            and player_cell
            and player_cell == expected_cell
            and not duplicate_positions
            and len(blocks) == M4_SHELTER_CONTRACT["snapshot_position_count"]
            and set(blocks) == snapshot_keys
            and required_keys.issubset(blocks)
        )

        floor_block = blocks.get(self._key(required_positions.get("floor", {})), {})
        feet_block = blocks.get(self._key(required_positions.get("feet", {})), {})
        head_block = blocks.get(self._key(required_positions.get("head", {})), {})
        roof_block = blocks.get(self._key(required_positions.get("roof", {})), {})
        wall_columns = []
        wall_blocks = []
        for direction, lower_name, upper_name in required_positions.get("wall_columns", []):
            lower = blocks.get(self._key(lower_name), {})
            upper = blocks.get(self._key(upper_name), {})
            wall_blocks.extend((lower, upper))
            wall_columns.append({
                "direction": direction,
                "lower": self._coordinate_block(lower_name, lower),
                "upper": self._coordinate_block(upper_name, upper),
                "sealed": self._full_block(lower) and self._full_block(upper),
            })

        standable_passed = bool(
            machine_snapshot_passed
            and self._full_block(floor_block)
            and self._passable(feet_block)
            and self._passable(head_block)
        )
        barriers_passed = bool(
            machine_snapshot_passed
            and len(wall_blocks) == 8
            and all(self._full_block(block) for block in wall_blocks)
        )
        overhead_passed = bool(machine_snapshot_passed and self._full_block(roof_block))

        hostiles = state.get("nearby_hostiles", [])
        hostiles = hostiles if isinstance(hostiles, list) else []
        hostiles_inside = [
            self._hostile_evidence(hostile)
            for hostile in hostiles
            if self._hostile_inside(hostile, player_cell)
        ]
        hostile_path_passed = bool(
            machine_snapshot_passed
            and barriers_passed
            and overhead_passed
            and not hostiles_inside
        )

        structural_positions = [
            position
            for _, lower, upper in required_positions.get("wall_columns", [])
            for position in (lower, upper)
        ] + [required_positions.get("roof", {})]
        matched_delta, missing_delta = self._match_placed_delta(
            structural_positions,
            blocks,
            delta.get("placed"),
        )
        provenance_passed = bool(
            machine_snapshot_passed
            and len(structural_positions) == M4_SHELTER_CONTRACT["required_structure_block_count"]
            and not missing_delta
        )

        coordinate_evidence = {
            "player_position": player_position,
            "player_cell": player_cell,
            "floor": self._coordinate_block(required_positions.get("floor", {}), floor_block),
            "interior": [
                self._coordinate_block(required_positions.get("feet", {}), feet_block),
                self._coordinate_block(required_positions.get("head", {}), head_block),
            ],
            "wall_columns": wall_columns,
            "roof": self._coordinate_block(required_positions.get("roof", {}), roof_block),
            "entrance": {
                "state": "fully_sealed" if barriers_passed else "boundary_incomplete",
                "opening_count": 0 if barriers_passed else sum(not column["sealed"] for column in wall_columns),
                "sealed_boundary_columns": [
                    {
                        "direction": column["direction"],
                        "lower_position": column["lower"]["position"],
                        "upper_position": column["upper"]["position"],
                    }
                    for column in wall_columns
                    if column["sealed"]
                ],
            },
        }
        coordinate_evidence_passed = bool(
            machine_snapshot_passed
            and len(coordinate_evidence["wall_columns"]) == 4
            and all(
                column["lower"].get("position") and column["upper"].get("position")
                for column in coordinate_evidence["wall_columns"]
            )
            and coordinate_evidence["roof"].get("position")
            and coordinate_evidence["floor"].get("position")
            and len(coordinate_evidence["entrance"]["sealed_boundary_columns"]) == 4
        )

        checks = [
            self._check("machine_snapshot", machine_snapshot_passed, {
                "source": state.get("source"),
                "required_position_count": len(required_keys),
                "observed_required_position_count": len(required_keys & set(blocks)),
                "expected_snapshot_position_count": len(snapshot_keys),
                "observed_snapshot_position_count": len(blocks),
                "duplicate_positions": sorted(duplicate_positions),
                "player_cell_matches_position": player_cell == expected_cell,
            }),
            self._check("physical_barriers", barriers_passed, {
                "sealed_wall_column_count": sum(column["sealed"] for column in wall_columns),
                "required_wall_column_count": 4,
            }),
            self._check("overhead_cover_or_approved_alternative", overhead_passed, {
                "roof": coordinate_evidence["roof"],
                "approved_alternative": None,
            }),
            self._check("hostile_path_risk", hostile_path_passed, {
                "method": "complete_local_collision_enclosure",
                "direct_reachability": "blocked" if hostile_path_passed else "not_proven_blocked",
                "nearby_hostile_count": len(hostiles),
                "hostiles_inside": hostiles_inside,
            }),
            self._check("standable_interior", standable_passed, {
                "floor_full_block": self._full_block(floor_block),
                "feet_passable": self._passable(feet_block),
                "head_passable": self._passable(head_block),
            }),
            self._check("episode_block_delta_or_approved_natural_safe_point", provenance_passed, {
                "required_structure_position_count": len(structural_positions),
                "matched_placement_count": len(matched_delta),
                "missing_positions": missing_delta,
                "approved_natural_safe_point": False,
            }),
            self._check("coordinate_evidence", coordinate_evidence_passed, {
                "floor_position_present": bool(coordinate_evidence["floor"].get("position")),
                "wall_column_count": len(coordinate_evidence["wall_columns"]),
                "roof_position_present": bool(coordinate_evidence["roof"].get("position")),
                "entrance_state": coordinate_evidence["entrance"]["state"],
            }),
        ]
        issues = [check["name"] for check in checks if not check["passed"]]
        passed = not issues
        return {
            "type": "m4_shelter_state_verification",
            "schema_version": 1,
            "verifier_id": M4_SHELTER_VERIFIER_ID,
            "contract_sha256": M4_SHELTER_CONTRACT_SHA256,
            "source": "machine_state",
            "strategy": M4_SHELTER_CONTRACT["strategy"],
            "passed": passed,
            "safe_state": passed,
            "checks": checks,
            "issues": issues,
            "coordinate_evidence": coordinate_evidence,
            "episode_block_delta": {
                "required_position_count": len(structural_positions),
                "matched_position_count": len(matched_delta),
                "matched_positions": matched_delta,
                "missing_positions": missing_delta,
            },
            "hostile_path_risk": next(
                check["evidence"] for check in checks if check["name"] == "hostile_path_risk"
            ),
            "natural_safe_point": {
                "allowed": False,
                "reason": "no natural safe-point strategy is approved in the sealed-cell G3 baseline",
            },
        }

    @classmethod
    def _required_positions(cls, player_cell: dict) -> dict:
        if not player_cell:
            return {"wall_columns": []}
        x, y, z = (player_cell[axis] for axis in ("x", "y", "z"))
        columns = []
        for direction, dx, dz in cls.DIRECTIONS:
            columns.append((
                direction,
                {"x": x + dx, "y": y, "z": z + dz},
                {"x": x + dx, "y": y + 1, "z": z + dz},
            ))
        return {
            "floor": {"x": x, "y": y - 1, "z": z},
            "feet": {"x": x, "y": y, "z": z},
            "head": {"x": x, "y": y + 1, "z": z},
            "roof": {"x": x, "y": y + 2, "z": z},
            "wall_columns": columns,
        }

    @classmethod
    def _snapshot_keys(cls, player_cell: dict) -> set[str]:
        if not player_cell:
            return set()
        return {
            cls._key({
                "x": player_cell["x"] + dx,
                "y": player_cell["y"] + dy,
                "z": player_cell["z"] + dz,
            })
            for dx in range(-1, 2)
            for dy in range(-1, 3)
            for dz in range(-1, 2)
        }

    @classmethod
    def _block_map(cls, values) -> tuple[dict, set[str]]:
        if not isinstance(values, list):
            return {}, set()
        blocks = {}
        duplicates = set()
        for value in values:
            if not isinstance(value, dict):
                continue
            position = cls._position(value.get("position"), integral=True)
            if not position:
                continue
            key = cls._key(position)
            if key in blocks:
                duplicates.add(key)
            blocks[key] = dict(value, position=position)
        return blocks, duplicates

    @classmethod
    def _match_placed_delta(cls, positions: list[dict], blocks: dict, values) -> tuple[list[dict], list[dict]]:
        if isinstance(values, dict):
            values = list(values.values())
        values = values if isinstance(values, list) else []
        placed = {}
        for value in values:
            if not isinstance(value, dict):
                continue
            position = cls._position(value.get("position"), integral=True)
            after = value.get("after", {}) if isinstance(value.get("after"), dict) else {}
            before = value.get("before", {}) if isinstance(value.get("before"), dict) else {}
            if (
                not position
                or value.get("success", True) is not True
                or str(value.get("operation") or "place") != "place"
                or not str(after.get("name") or "")
                or str(after.get("name") or "") == str(before.get("name") or "")
            ):
                continue
            placed[cls._key(position)] = dict(value, position=position)

        matched = []
        missing = []
        for position in positions:
            key = cls._key(position)
            current = blocks.get(key, {})
            change = placed.get(key, {})
            if change and str((change.get("after") or {}).get("name") or "") == str(current.get("name") or ""):
                matched.append(position)
            else:
                missing.append(position)
        return matched, missing

    @staticmethod
    def _full_block(block: dict) -> bool:
        return bool(
            isinstance(block, dict)
            and block.get("solid") is True
            and str(block.get("collision") or "") == "block"
            and str(block.get("name") or "") not in M4_SHELTER_UNSAFE_SOLID_BLOCKS
        )

    @staticmethod
    def _passable(block: dict) -> bool:
        return bool(
            isinstance(block, dict)
            and block.get("passable") is True
            and str(block.get("collision") or "") == "empty"
            and str(block.get("name") or "") in M4_SHELTER_PASSABLE_INTERIOR_BLOCKS
        )

    @classmethod
    def _hostile_inside(cls, hostile: dict, player_cell: dict) -> bool:
        if not isinstance(hostile, dict) or not player_cell:
            return False
        cell = cls._position(hostile.get("cell"), integral=True)
        if not cell:
            cell = cls._floor_position(cls._position(hostile.get("position"), integral=False))
        return bool(
            cell
            and cell["x"] == player_cell["x"]
            and cell["z"] == player_cell["z"]
            and abs(cell["y"] - player_cell["y"]) <= 1
        )

    @classmethod
    def _hostile_evidence(cls, hostile: dict) -> dict:
        return {
            "name": str(hostile.get("name") or hostile.get("type") or "unknown"),
            "position": cls._position(hostile.get("position"), integral=False),
            "distance": hostile.get("distance"),
        }

    @staticmethod
    def _coordinate_block(position: dict, block: dict) -> dict:
        return {
            "position": dict(position) if position else {},
            "name": str(block.get("name") or "unknown") if isinstance(block, dict) else "unknown",
            "collision": str(block.get("collision") or "unknown") if isinstance(block, dict) else "unknown",
            "solid": block.get("solid") is True if isinstance(block, dict) else False,
            "passable": block.get("passable") is True if isinstance(block, dict) else False,
        }

    @staticmethod
    def _check(name: str, passed: bool, evidence: dict) -> dict:
        return {"name": name, "passed": bool(passed), "evidence": evidence}

    @staticmethod
    def _position(value, *, integral: bool) -> dict:
        if not isinstance(value, dict):
            return {}
        try:
            numbers = {axis: float(value[axis]) for axis in ("x", "y", "z")}
        except (KeyError, TypeError, ValueError):
            return {}
        if not all(math.isfinite(number) for number in numbers.values()):
            return {}
        if integral:
            if not all(number.is_integer() for number in numbers.values()):
                return {}
            return {axis: int(number) for axis, number in numbers.items()}
        return numbers

    @classmethod
    def _floor_position(cls, position: dict) -> dict:
        if not position:
            return {}
        return {axis: math.floor(float(position[axis])) for axis in ("x", "y", "z")}

    @staticmethod
    def _key(position: dict) -> str:
        if not position:
            return ""
        return f"{position.get('x')},{position.get('y')},{position.get('z')}"


def is_machine_verified_shelter(value) -> bool:
    """Return true only for a complete report from the pinned G3 verifier."""
    if not isinstance(value, dict):
        return False
    if not (
        value.get("type") == "m4_shelter_state_verification"
        and value.get("verifier_id") == M4_SHELTER_VERIFIER_ID
        and value.get("contract_sha256") == M4_SHELTER_CONTRACT_SHA256
        and value.get("source") == "machine_state"
        and value.get("passed") is True
        and value.get("safe_state") is True
        and value.get("issues") == []
    ):
        return False
    checks = value.get("checks")
    if not isinstance(checks, list):
        return False
    statuses = {
        str(check.get("name") or ""): check.get("passed") is True
        for check in checks
        if isinstance(check, dict)
    }
    if statuses.get("machine_snapshot") is not True:
        return False
    if not all(statuses.get(name) is True for name in M4_SHELTER_REQUIRED_CHECKS):
        return False
    delta = value.get("episode_block_delta", {})
    coordinate_evidence = value.get("coordinate_evidence", {})
    entrance = coordinate_evidence.get("entrance", {}) if isinstance(coordinate_evidence, dict) else {}
    return bool(
        isinstance(delta, dict)
        and delta.get("required_position_count") == M4_SHELTER_CONTRACT["required_structure_block_count"]
        and delta.get("matched_position_count") == M4_SHELTER_CONTRACT["required_structure_block_count"]
        and isinstance(entrance, dict)
        and entrance.get("state") == "fully_sealed"
        and len(entrance.get("sealed_boundary_columns", [])) == 4
    )
