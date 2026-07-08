"""Visual action grounding from structured visual observations."""
from dataclasses import asdict, dataclass, field
import math
import re
from typing import Optional


@dataclass
class VisualActionSuggestion:
    kind: str
    action: dict
    reason: str
    confidence: float = 0.5
    target: dict = field(default_factory=dict)
    source: str = "visual_action_advisor"

    def to_dict(self) -> dict:
        return asdict(self)


class VisualActionAdvisor:
    """Turn grounded visual resources and dangers into conservative actions."""

    def __init__(
        self,
        danger_distance: float = 8.0,
        retreat_distance: float = 8.0,
        harvest_reach: float = 4.0,
        stand_distance: float = 2.0,
    ):
        self.danger_distance = danger_distance
        self.retreat_distance = retreat_distance
        self.harvest_reach = harvest_reach
        self.stand_distance = stand_distance

    def suggest(self, goal: str, observation: dict, limit: int = 4) -> list[dict]:
        observation = observation or {}
        suggestions: list[VisualActionSuggestion] = []
        danger = self._danger_suggestion(observation)
        if danger:
            suggestions.append(danger)
        suggestions.extend(self._resource_suggestions(goal, observation))
        suggestions.sort(key=lambda item: (-item.confidence, item.kind, item.reason))
        return [suggestion.to_dict() for suggestion in suggestions[:limit]]

    def _danger_suggestion(self, observation: dict) -> Optional[VisualActionSuggestion]:
        danger = self._closest_danger(observation)
        if not danger:
            return None
        distance = self._number(danger.get("dist", danger.get("distance")), default=999.0)
        if distance > self.danger_distance:
            return None

        player_pos = observation.get("position", {}) if isinstance(observation.get("position", {}), dict) else {}
        danger_pos = danger.get("position", {}) if isinstance(danger.get("position", {}), dict) else {}
        if player_pos and danger_pos and "x" in player_pos and "z" in player_pos and "x" in danger_pos and "z" in danger_pos:
            target = self._retreat_target(player_pos, danger_pos)
            return VisualActionSuggestion(
                kind="danger_retreat",
                action={"type": "move_to", "parameters": target},
                reason=f"retreat from nearby {danger.get('type', danger.get('name', 'hostile'))}",
                confidence=0.95,
                target={"danger": danger, "position": target},
            )

        weapon = self._best_weapon(observation.get("inventory", {}))
        if weapon:
            return VisualActionSuggestion(
                kind="danger_equip",
                action={"type": "equip", "parameters": {"item": weapon}},
                reason=f"equip {weapon} before handling nearby {danger.get('type', danger.get('name', 'hostile'))}",
                confidence=0.82,
                target={"danger": danger},
            )
        return None

    def _resource_suggestions(self, goal: str, observation: dict) -> list[VisualActionSuggestion]:
        suggestions: list[VisualActionSuggestion] = []
        for resource in observation.get("grounded_resources", []) or []:
            if not isinstance(resource, dict):
                continue
            if not self._resource_matches_goal(goal, resource):
                continue
            position = resource.get("position", {}) if isinstance(resource.get("position", {}), dict) else {}
            if not position:
                continue

            approach = self._resource_approach_suggestion(resource, observation)
            if approach:
                suggestions.append(approach)

            tool = resource.get("best_available_tool")
            if resource.get("can_harvest") and tool and tool != "hand":
                suggestions.append(VisualActionSuggestion(
                    kind="resource_equip",
                    action={"type": "equip", "parameters": {"item": tool}},
                    reason=f"equip {tool} for visible {resource.get('name', 'resource')}",
                    confidence=0.76,
                    target={"resource": resource},
                ))
            if resource.get("can_harvest"):
                suggestions.append(VisualActionSuggestion(
                    kind="resource_focus",
                    action={"type": "look_at", "parameters": self._position_params(position)},
                    reason=f"look at visible {resource.get('name', 'resource')} before harvesting",
                    confidence=0.89,
                    target={"resource": resource},
                ))
                suggestions.append(VisualActionSuggestion(
                    kind="resource_harvest",
                    action={"type": "dig", "parameters": self._position_params(position)},
                    reason=f"harvest visible {resource.get('name', 'resource')}",
                    confidence=0.9,
                    target={"resource": resource},
                ))
            else:
                recommended = resource.get("recommended_tool")
                if recommended:
                    suggestions.append(VisualActionSuggestion(
                        kind="resource_need_tool",
                        action={"type": "craft", "parameters": {"item": recommended}},
                        reason=f"visible {resource.get('name', 'resource')} needs {recommended}",
                        confidence=0.55,
                        target={"resource": resource},
                    ))
        return suggestions

    def _resource_approach_suggestion(self, resource: dict, observation: dict) -> Optional[VisualActionSuggestion]:
        if not resource.get("can_harvest"):
            return None
        player_pos = observation.get("position", {}) if isinstance(observation.get("position", {}), dict) else {}
        resource_pos = resource.get("position", {}) if isinstance(resource.get("position", {}), dict) else {}
        if not player_pos or not resource_pos:
            return None
        if not all(key in player_pos for key in ("x", "z")) or not all(key in resource_pos for key in ("x", "z")):
            return None
        distance = self._horizontal_distance(player_pos, resource_pos)
        if distance <= self.harvest_reach:
            return None
        target = self._approach_target(player_pos, resource_pos)
        return VisualActionSuggestion(
            kind="resource_approach",
            action={"type": "move_to", "parameters": target},
            reason=f"move within reach of visible {resource.get('name', 'resource')}",
            confidence=0.91,
            target={"resource": resource, "position": target, "distance": round(distance, 2)},
        )

    def _closest_danger(self, observation: dict) -> Optional[dict]:
        dangers = []
        for item in observation.get("dangers", []) or observation.get("visible_dangers", []) or []:
            if isinstance(item, dict):
                dangers.append(dict(item))
        for entity in observation.get("nearby_entities", []) or []:
            if not isinstance(entity, dict):
                continue
            if entity.get("hostile") or str(entity.get("type", "")).lower() in {"zombie", "skeleton", "creeper", "spider", "enderman", "witch", "phantom"}:
                danger = dict(entity)
                danger.setdefault("dist", entity.get("distance"))
                dangers.append(danger)
        if not dangers:
            return None
        return min(dangers, key=lambda item: self._number(item.get("dist", item.get("distance")), default=999.0))

    def _retreat_target(self, player_pos: dict, danger_pos: dict) -> dict:
        px = self._number(player_pos.get("x"))
        pz = self._number(player_pos.get("z"))
        dx = px - self._number(danger_pos.get("x"))
        dz = pz - self._number(danger_pos.get("z"))
        length = math.sqrt(dx * dx + dz * dz) or 1.0
        target = {
            "x": round(px + (dx / length) * self.retreat_distance, 2),
            "z": round(pz + (dz / length) * self.retreat_distance, 2),
        }
        if "y" in player_pos:
            target["y"] = player_pos.get("y")
        return target

    def _approach_target(self, player_pos: dict, resource_pos: dict) -> dict:
        px = self._number(player_pos.get("x"))
        pz = self._number(player_pos.get("z"))
        rx = self._number(resource_pos.get("x"))
        rz = self._number(resource_pos.get("z"))
        dx = px - rx
        dz = pz - rz
        length = math.sqrt(dx * dx + dz * dz) or 1.0
        target = {
            "x": round(rx + (dx / length) * self.stand_distance, 2),
            "z": round(rz + (dz / length) * self.stand_distance, 2),
        }
        if "y" in player_pos:
            target["y"] = player_pos.get("y")
        elif "y" in resource_pos:
            target["y"] = resource_pos.get("y")
        return target

    def _horizontal_distance(self, a: dict, b: dict) -> float:
        dx = self._number(a.get("x")) - self._number(b.get("x"))
        dz = self._number(a.get("z")) - self._number(b.get("z"))
        return math.sqrt(dx * dx + dz * dz)

    def _resource_matches_goal(self, goal: str, resource: dict) -> bool:
        goal_terms = set(re.findall(r"[a-z0-9_]+", str(goal or "").lower()))
        if not goal_terms:
            return True
        aliases = set()
        for key in ("name", "drop", "recommended_tool"):
            value = resource.get(key)
            if value:
                aliases.update(str(value).lower().split("_"))
                aliases.add(str(value).lower())
        for item in resource.get("crafts_into", []) or []:
            aliases.update(str(item).lower().split("_"))
            aliases.add(str(item).lower())
        generic_terms = {
            "mine", "gather", "collect", "harvest", "get", "find",
            "resource", "resources", "material", "materials", "supply", "supplies",
            "ore", "ores", "wood", "log", "logs", "tree", "trees",
        }
        specific_terms = goal_terms - generic_terms
        if specific_terms & aliases:
            return True
        if {"wood", "log", "logs", "tree", "trees"} & goal_terms and any(term in aliases for term in {"log", "oak", "birch", "spruce"}):
            return True
        is_ore_resource = (
            "ore" in aliases
            or str(resource.get("name", "")).lower().endswith("_ore")
            or self._number(resource.get("required_tool_tier"), default=0) > 0
        )
        if {"mine", "ore", "ores"} & goal_terms and is_ore_resource and (not specific_terms or specific_terms & aliases):
            return True
        generic_only = {"gather", "collect", "harvest", "get", "find", "resource", "resources", "material", "materials", "supply", "supplies"}
        if goal_terms <= generic_terms and goal_terms & generic_only and aliases:
            return True
        return bool(goal_terms & aliases)

    def _best_weapon(self, inventory) -> str:
        counts = self._inventory_counts(inventory)
        for weapon in ("diamond_sword", "iron_sword", "stone_sword", "wooden_sword", "axe"):
            if counts.get(weapon, 0) > 0:
                return weapon
        for item, count in counts.items():
            if count > 0 and item.endswith("_axe"):
                return item
        return ""

    def _inventory_counts(self, inventory) -> dict:
        if isinstance(inventory, dict):
            return inventory
        counts = {}
        if isinstance(inventory, list):
            for item in inventory:
                if isinstance(item, dict):
                    name = str(item.get("name", ""))
                    counts[name] = counts.get(name, 0) + int(item.get("count", 1) or 1)
        return counts

    def _position_params(self, position: dict) -> dict:
        return {
            "x": position.get("x", 0),
            "y": position.get("y", 0),
            "z": position.get("z", 0),
        }

    def _number(self, value, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default
