"""Automatic curriculum for open-ended Minecraft goals.

The manager sits above the rule survival goal generator. It keeps emergency
goals intact, then proposes progressively useful goals from inventory,
visible resources, learned experience, and skill coverage.
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CurriculumGoalCandidate:
    """One candidate open-ended goal with transparent scoring metadata."""

    title: str
    category: str
    score: float
    reasons: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    target_items: list[str] = field(default_factory=list)
    required_items: dict = field(default_factory=dict)
    skill_targets: list[str] = field(default_factory=list)


@dataclass
class CurriculumGoalStats:
    """Compact per-goal outcome state."""

    attempts: int = 0
    successes: int = 0
    failures: int = 0
    last_cycles: int = 0


class CurriculumManager:
    """Generate and rank autonomous goals for lifelong Minecraft play."""

    EMERGENCY_TOKENS = {
        "attack": 100.0,
        "flee": 100.0,
        "eat": 95.0,
        "restore health": 95.0,
        "find food": 85.0,
        "shelter": 80.0,
        "nightfall": 80.0,
        "wait for dawn": 75.0,
    }

    def __init__(self, max_recent_goals: int = 30):
        self.max_recent_goals = max_recent_goals
        self.goal_stats: dict[str, CurriculumGoalStats] = {}
        self.recent_goals: list[dict] = []
        self.last_decision: dict = {}
        self.exploration_feedback: dict = {
            "discovered_blocks": [],
            "discovered_resources": [],
            "discovered_entities": [],
            "action_failure_categories": {},
            "low_movement_log_count": 0,
            "hostile_encounter_count": 0,
            "path_distance": 0.0,
        }
        self.world_model_feedback: dict = {
            "suggested_goals": [],
            "frontiers": [],
            "resource_hotspots": [],
            "danger_cells": [],
            "frontier_count": 0,
            "resource_hotspot_count": 0,
            "danger_cell_count": 0,
        }

    def next_goal(
        self,
        observation: dict,
        fallback_goal: str,
        memory_system=None,
        skill_library=None,
    ) -> str:
        """Return the highest-ranked curriculum goal or the fallback."""
        candidates = self.propose_goals(observation, fallback_goal, memory_system, skill_library)
        if not candidates:
            return fallback_goal
        best = candidates[0]
        self.last_decision = {
            "selected": best.title,
            "fallback": fallback_goal,
            "candidates": [self._candidate_dict(candidate) for candidate in candidates[:5]],
        }
        return best.title

    def propose_goals(
        self,
        observation: dict,
        fallback_goal: str = "",
        memory_system=None,
        skill_library=None,
    ) -> list[CurriculumGoalCandidate]:
        """Build a ranked curriculum slate from the current world state."""
        inventory = observation.get("inventory", {}) or {}
        nearby = self._nearby_names(observation)
        discovered = self._discovered_items(memory_system, inventory)
        stable = self._is_stable(observation)
        candidates: list[CurriculumGoalCandidate] = []

        fallback_score = self._fallback_score(fallback_goal)
        if fallback_goal:
            candidates.append(CurriculumGoalCandidate(
                title=fallback_goal,
                category="fallback",
                score=fallback_score,
                reasons=["rule_generator"],
            ))

        oak_logs = self._count_any(inventory, ["oak_log", "birch_log", "spruce_log", "jungle_log", "acacia_log", "dark_oak_log", "mangrove_log"])
        planks = self._count_any(inventory, ["oak_planks", "birch_planks", "spruce_planks", "jungle_planks", "acacia_planks", "dark_oak_planks", "mangrove_planks"])
        sticks = self._count_any(inventory, ["stick"])
        cobble = self._count_any(inventory, ["cobblestone", "stone"])
        coal = self._count_any(inventory, ["coal", "charcoal"])
        torches = self._count_any(inventory, ["torch"])
        raw_iron = self._count_any(inventory, ["raw_iron", "iron_ore"])
        iron_ingots = self._count_any(inventory, ["iron_ingot"])

        if oak_logs < 6:
            candidates.append(self._candidate(
                "Gather 6 oak logs for tools and shelter",
                "resource",
                42.0,
                observation,
                discovered,
                skill_library,
                target_items=["oak_log"],
                skill_targets=["gather_wood", "dig_block"],
                reasons=["early_wood_bootstrap"],
                opportunity=10.0 if self._any_nearby(nearby, ["log", "tree", "oak"]) else 0.0,
            ))

        if not inventory.get("crafting_table") and oak_logs + planks >= 1:
            candidates.append(self._candidate(
                "Craft crafting table",
                "crafting",
                48.0,
                observation,
                discovered,
                skill_library,
                target_items=["crafting_table"],
                required_items={"oak_log": 1},
                skill_targets=["craft_item"],
                reasons=["unlock_crafting_grid"],
            ))

        if not inventory.get("wooden_pickaxe") and inventory.get("crafting_table") and (oak_logs + planks >= 3 or sticks >= 2):
            candidates.append(self._candidate(
                "Craft wooden pickaxe",
                "tool_progression",
                52.0,
                observation,
                discovered,
                skill_library,
                target_items=["wooden_pickaxe"],
                required_items={"crafting_table": 1},
                skill_targets=["craft_tools", "craft_item"],
                reasons=["unlock_stone_mining"],
            ))

        if inventory.get("wooden_pickaxe") and cobble < 12:
            candidates.append(self._candidate(
                "Mine 12 cobblestone for stone tools and furnace",
                "resource",
                50.0,
                observation,
                discovered,
                skill_library,
                target_items=["cobblestone"],
                required_items={"wooden_pickaxe": 1},
                skill_targets=["mine_stone", "dig_block"],
                reasons=["stone_age_progression"],
                opportunity=8.0 if self._any_nearby(nearby, ["stone", "cobblestone"]) else 0.0,
            ))

        if inventory.get("crafting_table") and not inventory.get("stone_pickaxe") and cobble >= 3 and sticks >= 2:
            candidates.append(self._candidate(
                "Craft stone pickaxe",
                "tool_progression",
                58.0,
                observation,
                discovered,
                skill_library,
                target_items=["stone_pickaxe"],
                required_items={"cobblestone": 3, "stick": 2},
                skill_targets=["craft_tools", "craft_item"],
                reasons=["unlock_iron_mining"],
            ))

        if torches < 8 and coal <= 0 and (inventory.get("wooden_pickaxe") or inventory.get("stone_pickaxe") or self._any_nearby(nearby, ["coal"])):
            candidates.append(self._candidate(
                "Collect coal or charcoal for torches",
                "resource",
                46.0,
                observation,
                discovered,
                skill_library,
                target_items=["coal", "charcoal"],
                skill_targets=["mine_stone", "dig_block"],
                reasons=["night_and_cave_safety"],
                opportunity=12.0 if self._any_nearby(nearby, ["coal"]) else 0.0,
            ))

        if torches < 8 and coal > 0 and sticks > 0:
            candidates.append(self._candidate(
                "Craft torches for cave and night safety",
                "crafting",
                54.0,
                observation,
                discovered,
                skill_library,
                target_items=["torch"],
                required_items={"coal": 1, "stick": 1},
                skill_targets=["craft_item"],
                reasons=["reduce_exploration_risk"],
            ))

        if inventory.get("stone_pickaxe") and raw_iron + iron_ingots < 3:
            candidates.append(self._candidate(
                "Mine iron ore for iron tools",
                "resource",
                62.0,
                observation,
                discovered,
                skill_library,
                target_items=["raw_iron", "iron_ore"],
                required_items={"stone_pickaxe": 1},
                skill_targets=["mine_iron", "dig_block"],
                reasons=["iron_age_progression"],
                opportunity=14.0 if self._any_nearby(nearby, ["iron"]) else 0.0,
            ))

        if raw_iron > 0 and inventory.get("furnace"):
            candidates.append(self._candidate(
                "Smelt iron ingots for stronger tools",
                "crafting",
                60.0,
                observation,
                discovered,
                skill_library,
                target_items=["iron_ingot"],
                required_items={"furnace": 1, "raw_iron": 1},
                skill_targets=["smelt_iron"],
                reasons=["convert_ore_to_tool_material"],
            ))

        if stable:
            novel_nearby = self._novel_nearby_resource(nearby, discovered)
            if novel_nearby:
                candidates.append(self._candidate(
                    f"Inspect nearby {novel_nearby} and learn a safe collection route",
                    "exploration",
                    38.0,
                    observation,
                    discovered,
                    skill_library,
                    target_items=[novel_nearby],
                    skill_targets=["navigate_to_target", "move_to"],
                    reasons=["visible_novel_resource"],
                    opportunity=10.0,
                ))
            if self._has_basic_kit(inventory):
                for candidate in self._world_model_goal_candidates(
                    observation,
                    discovered,
                    memory_system,
                    skill_library,
                ):
                    candidates.append(candidate)
                coverage_bonus = self._exploration_coverage_gap_bonus()
                reasons = ["open_ended_map_expansion"]
                if coverage_bonus:
                    reasons.append("coverage_gap_feedback")
                candidates.append(self._candidate(
                    "Scout nearby area and record landmarks",
                    "exploration",
                    34.0,
                    observation,
                    discovered,
                    skill_library,
                    target_items=["landmark"],
                    skill_targets=["navigate_to_target", "move_to"],
                    reasons=reasons,
                    opportunity=coverage_bonus,
                    novelty_override=3.0,
                ))
            if self._feedback_failure_count("perception") > 0:
                candidates.append(self._candidate(
                    "Scan nearby area and verify landmarks before deeper exploration",
                    "exploration_diagnostic",
                    41.0,
                    observation,
                    discovered,
                    skill_library,
                    target_items=["landmark"],
                    skill_targets=["look_at", "navigate_to_target"],
                    reasons=["perception_failure_feedback"],
                    novelty_override=2.0,
                ))

        ranked = self._deduplicate(candidates)
        ranked.sort(key=lambda candidate: candidate.score, reverse=True)
        return ranked

    def record_goal_outcome(self, goal: str, success: bool, cycles: int = 0):
        """Track goal outcomes so the curriculum can avoid local loops."""
        if not goal:
            return
        stats = self.goal_stats.setdefault(goal, CurriculumGoalStats())
        stats.attempts += 1
        stats.last_cycles = cycles
        if success:
            stats.successes += 1
        else:
            stats.failures += 1
        self.recent_goals.append({
            "goal": goal,
            "success": success,
            "cycles": cycles,
        })
        if len(self.recent_goals) > self.max_recent_goals:
            self.recent_goals = self.recent_goals[-self.max_recent_goals:]

    def record_exploration_feedback(self, feedback: dict):
        """Ingest offline exploration-trace feedback for future goal ranking."""
        if not isinstance(feedback, dict):
            return
        for key, aliases in {
            "discovered_blocks": ["discovered_blocks", "unique_block_types"],
            "discovered_resources": ["discovered_resources", "unique_resource_types"],
            "discovered_entities": ["discovered_entities", "unique_entity_types"],
        }.items():
            values = set(str(value).lower() for value in self.exploration_feedback.get(key, []) if value)
            for alias in aliases:
                raw = feedback.get(alias, [])
                if isinstance(raw, list):
                    values.update(str(value).lower() for value in raw if value)
            self.exploration_feedback[key] = sorted(values)

        current_categories = dict(self.exploration_feedback.get("action_failure_categories", {}))
        incoming_categories = feedback.get("action_failure_categories", {})
        if isinstance(incoming_categories, dict):
            for category, count in incoming_categories.items():
                current_categories[str(category)] = current_categories.get(str(category), 0) + int(count or 0)
        self.exploration_feedback["action_failure_categories"] = current_categories

        for key in ("low_movement_log_count", "hostile_encounter_count"):
            self.exploration_feedback[key] = int(self.exploration_feedback.get(key, 0) or 0) + int(feedback.get(key, 0) or 0)
        self.exploration_feedback["path_distance"] = max(
            float(self.exploration_feedback.get("path_distance", 0.0) or 0.0),
            float(feedback.get("path_distance", 0.0) or 0.0),
        )

    def record_world_model_feedback(self, feedback: dict):
        """Ingest explicit map/frontier feedback from world-model reports."""
        if not isinstance(feedback, dict):
            return
        for key in ("frontier_count", "resource_hotspot_count", "danger_cell_count"):
            self.world_model_feedback[key] = max(
                int(self.world_model_feedback.get(key, 0) or 0),
                int(feedback.get(key, 0) or 0),
            )
        for key in ("suggested_goals", "frontiers", "resource_hotspots", "danger_cells"):
            self.world_model_feedback[key] = self._merge_feedback_records(
                self.world_model_feedback.get(key, []),
                feedback.get(key, []),
            )

    def summary(self) -> dict:
        """Return serializable curriculum state for logs and benchmark reports."""
        return {
            "recent_goals": list(self.recent_goals[-10:]),
            "goal_stats": {
                goal: {
                    "attempts": stats.attempts,
                    "successes": stats.successes,
                    "failures": stats.failures,
                    "last_cycles": stats.last_cycles,
                }
                for goal, stats in self.goal_stats.items()
            },
            "last_decision": self.last_decision,
            "exploration_feedback": self.exploration_feedback,
            "world_model_feedback": self.world_model_feedback,
        }

    def _candidate(
        self,
        title: str,
        category: str,
        base_score: float,
        observation: dict,
        discovered: set[str],
        skill_library=None,
        target_items: Optional[list[str]] = None,
        required_items: Optional[dict] = None,
        skill_targets: Optional[list[str]] = None,
        reasons: Optional[list[str]] = None,
        opportunity: float = 0.0,
        novelty_override: Optional[float] = None,
    ) -> CurriculumGoalCandidate:
        target_items = target_items or []
        skill_targets = skill_targets or []
        reasons = list(reasons or [])
        score = base_score + opportunity

        novelty = novelty_override if novelty_override is not None else self._novelty_bonus(target_items, discovered, observation)
        if novelty:
            score += novelty
            reasons.append("novelty")

        skill_gap = self._skill_gap_bonus(skill_targets, skill_library)
        if skill_gap:
            score += skill_gap
            reasons.append("skill_gap")

        stats = self.goal_stats.get(title)
        if stats:
            score -= min(16.0, stats.failures * 6.0)
            score -= min(12.0, stats.successes * 4.0)
            if stats.failures:
                reasons.append("recent_failure_penalty")
            if stats.successes:
                reasons.append("repeat_success_penalty")

        if self._recently_repeated(title):
            score -= 8.0
            reasons.append("recent_repeat_penalty")

        return CurriculumGoalCandidate(
            title=title,
            category=category,
            score=round(score, 3),
            reasons=reasons,
            tags=sorted({category, *target_items, *skill_targets}),
            target_items=target_items,
            required_items=required_items or {},
            skill_targets=skill_targets,
        )

    def _fallback_score(self, fallback_goal: str) -> float:
        text = str(fallback_goal or "").lower()
        for token, score in self.EMERGENCY_TOKENS.items():
            if token in text:
                return score
        return 30.0 if fallback_goal else 0.0

    def _is_stable(self, observation: dict) -> bool:
        if observation.get("health", 20) < 10:
            return False
        time_of_day = observation.get("time_of_day", 0)
        if 10000 <= time_of_day or time_of_day < 1000:
            return False
        hostiles = [e for e in observation.get("nearby_entities", []) if e.get("hostile")]
        return not any(e.get("distance", 999) < 12 for e in hostiles)

    def _has_basic_kit(self, inventory: dict) -> bool:
        return bool(
            inventory.get("crafting_table")
            and (inventory.get("wooden_pickaxe") or inventory.get("stone_pickaxe") or inventory.get("iron_pickaxe"))
            and self._count_any(inventory, ["oak_log", "oak_planks", "cobblestone"]) >= 3
        )

    def _count_any(self, inventory: dict, names: list[str]) -> int:
        return sum(int(inventory.get(name, 0) or 0) for name in names)

    def _nearby_names(self, observation: dict) -> set[str]:
        names = set()
        for key in ("nearby_blocks", "grounded_resources", "trees_found"):
            for item in observation.get(key, []) or []:
                if isinstance(item, str):
                    names.add(item.lower())
                    continue
                if not isinstance(item, dict):
                    continue
                for field_name in ("name", "type", "block", "drop", "resource"):
                    value = item.get(field_name)
                    if value:
                        names.add(str(value).lower())
        return names

    def _any_nearby(self, nearby: set[str], tokens: list[str]) -> bool:
        return any(token in name for token in tokens for name in nearby)

    def _novel_nearby_resource(self, nearby: set[str], discovered: set[str]) -> str:
        ignored = {
            "air", "grass", "dirt", "stone", "cave_air", "water", "lava",
            "oak_log", "oak_leaves", "sand", "gravel",
        }
        for name in sorted(nearby):
            if name in ignored:
                continue
            if name.endswith("_leaves"):
                continue
            if name not in discovered:
                return name
        return ""

    def _discovered_items(self, memory_system, inventory: dict) -> set[str]:
        discovered = {str(k).lower() for k, v in inventory.items() if v}
        for key in ("discovered_blocks", "discovered_resources"):
            discovered.update(str(item).lower() for item in self.exploration_feedback.get(key, []) if item)
        if not memory_system:
            return discovered
        for record in getattr(memory_system, "experiences", {}).values():
            if not getattr(record, "success", False):
                continue
            discovered.update(str(tag).lower() for tag in getattr(record, "tags", []) if tag)
            for action in getattr(record, "actions", []) or []:
                params = action.get("parameters", {}) if isinstance(action, dict) else {}
                for key in ("item", "block", "target"):
                    value = params.get(key)
                    if value:
                        discovered.add(str(value).lower())
        for key in getattr(memory_system, "l3_semantic", {}).keys():
            discovered.add(str(key).lower())
        return discovered

    def _novelty_bonus(self, target_items: list[str], discovered: set[str], observation: dict) -> float:
        inventory = observation.get("inventory", {}) or {}
        score = 0.0
        for item in target_items:
            item_key = str(item).lower()
            if item_key == "landmark":
                score += 2.0
            elif item_key not in discovered and not inventory.get(item_key):
                score += 5.0
        return min(12.0, score)

    def _skill_gap_bonus(self, skill_targets: list[str], skill_library) -> float:
        if not skill_library:
            return 0.0
        score = 0.0
        for name in skill_targets:
            skill = skill_library.get_skill(name) if hasattr(skill_library, "get_skill") else None
            if not skill:
                continue
            if skill.total_uses <= 0:
                score += 2.0
            elif skill.success_rate < 0.5:
                score += 1.0
        return min(6.0, score)

    def _feedback_failure_count(self, category: str) -> int:
        failures = self.exploration_feedback.get("action_failure_categories", {})
        return int(failures.get(category, 0) or 0) if isinstance(failures, dict) else 0

    def _exploration_coverage_gap_bonus(self) -> float:
        low_movement = int(self.exploration_feedback.get("low_movement_log_count", 0) or 0)
        if low_movement <= 0:
            return 0.0
        return min(12.0, 4.0 + low_movement * 4.0)

    def _world_model_goal_candidates(
        self,
        observation: dict,
        discovered: set[str],
        memory_system=None,
        skill_library=None,
    ) -> list[CurriculumGoalCandidate]:
        candidates = []
        for goal in self.world_model_feedback.get("suggested_goals", [])[:3]:
            title = str(goal or "").strip()
            if not title:
                continue
            candidates.append(self._candidate(
                title,
                "world_model_frontier",
                44.0,
                observation,
                discovered,
                skill_library,
                target_items=["landmark"],
                skill_targets=["navigate_to_target", "move_to"],
                reasons=["world_model_frontier_feedback"],
                opportunity=self._world_model_frontier_bonus(),
                novelty_override=3.0,
            ))

        for frontier in self.world_model_feedback.get("frontiers", [])[:6]:
            if not isinstance(frontier, dict):
                continue
            title = self._structured_frontier_title(frontier)
            if not title:
                continue
            resources = self._frontier_resources(frontier)
            transfer = self._frontier_transfer_signal(memory_system, frontier, resources)
            risk = self._frontier_risk_penalty(frontier, observation)
            reasons = ["structured_frontier_feedback"]
            if resources:
                reasons.append("frontier_resource_opportunity")
            novel_resources = [resource for resource in resources if resource not in discovered]
            if novel_resources:
                reasons.append("frontier_novel_resource")
            if transfer["success_bonus"]:
                reasons.append("frontier_transfer_success")
            if transfer["failure_penalty"]:
                reasons.append("frontier_failure_memory_penalty")
            if risk:
                reasons.append("frontier_danger_penalty")
            candidates.append(self._candidate(
                title,
                "world_model_frontier",
                43.0,
                observation,
                discovered,
                skill_library,
                target_items=resources[:3] or ["landmark"],
                skill_targets=["navigate_to_target", "move_to"],
                reasons=reasons,
                opportunity=(
                    self._world_model_frontier_bonus()
                    + self._frontier_resource_bonus(resources, discovered)
                    + transfer["success_bonus"]
                    - transfer["failure_penalty"]
                    - risk
                ),
                novelty_override=min(6.0, 2.0 + len(novel_resources) * 2.0) if novel_resources else 2.0,
            ))

        for hotspot in self.world_model_feedback.get("resource_hotspots", [])[:3]:
            if not isinstance(hotspot, dict):
                continue
            resource = str(hotspot.get("resource") or "").strip().lower()
            if not resource:
                continue
            center = hotspot.get("center", {}) if isinstance(hotspot.get("center", {}), dict) else {}
            title = f"Revisit {resource} hotspot"
            if center:
                title += f" near x={center.get('x')}, z={center.get('z')}"
            danger_count = int(hotspot.get("danger_count", 0) or 0)
            reasons = ["world_model_resource_hotspot"]
            if danger_count:
                reasons.append("danger_aware_route")
            candidates.append(self._candidate(
                title,
                "world_model_resource",
                40.0,
                observation,
                discovered,
                skill_library,
                target_items=[resource],
                skill_targets=["navigate_to_target", "move_to"],
                reasons=reasons,
                opportunity=max(0.0, 8.0 - danger_count * 2.0),
                novelty_override=0.0 if resource in discovered else 4.0,
            ))

        if self.world_model_feedback.get("danger_cells"):
            candidates.append(self._candidate(
                "Scout safer route around mapped danger cells",
                "world_model_safety",
                39.0,
                observation,
                discovered,
                skill_library,
                target_items=["landmark"],
                skill_targets=["look_at", "navigate_to_target"],
                reasons=["world_model_danger_feedback"],
                opportunity=min(8.0, float(self.world_model_feedback.get("danger_cell_count", 0) or 0) * 2.0),
                novelty_override=1.0,
            ))
        return candidates

    def _world_model_frontier_bonus(self) -> float:
        frontier_count = int(self.world_model_feedback.get("frontier_count", 0) or 0)
        if frontier_count <= 0:
            return 0.0
        return min(10.0, 2.0 + frontier_count * 0.5)

    def _structured_frontier_title(self, frontier: dict) -> str:
        cell = frontier.get("cell", {}) if isinstance(frontier.get("cell", {}), dict) else {}
        if not cell:
            return ""
        direction = str(frontier.get("direction") or "mapped").strip().lower()
        title = f"Explore {direction} frontier cell ({cell.get('x')},{cell.get('z')})"
        center = frontier.get("center", {}) if isinstance(frontier.get("center", {}), dict) else {}
        if center:
            title += f" near x={center.get('x')}, z={center.get('z')}"
        resources = self._frontier_resources(frontier)
        if resources:
            title += f" to inspect {', '.join(resources[:3])}"
        return title

    def _frontier_resources(self, frontier: dict) -> list[str]:
        resources = []
        for key in ("nearby_resources", "resources", "resource_types"):
            raw = frontier.get(key, [])
            if not isinstance(raw, list):
                continue
            for item in raw:
                if isinstance(item, str):
                    name = item
                elif isinstance(item, dict):
                    name = item.get("name") or item.get("type") or item.get("resource")
                else:
                    name = ""
                name = str(name or "").strip().lower()
                if name and name not in resources:
                    resources.append(name)
        return resources[:6]

    def _frontier_resource_bonus(self, resources: list[str], discovered: set[str]) -> float:
        score = 0.0
        for resource in resources[:4]:
            score += 4.0 if resource not in discovered else 1.5
        return min(9.0, score)

    def _frontier_transfer_signal(self, memory_system, frontier: dict, resources: list[str]) -> dict:
        if not memory_system:
            return {"success_bonus": 0.0, "failure_penalty": 0.0}
        specific_tokens = {str(frontier.get("direction") or "").lower(), *resources}
        cell = frontier.get("cell", {}) if isinstance(frontier.get("cell", {}), dict) else {}
        if cell:
            specific_tokens.add(f"cell:{cell.get('x')},{cell.get('z')}")
        specific_tokens = {token for token in specific_tokens if token}
        query_tokens = specific_tokens or {"frontier", "explore", "navigation"}

        success_hits = 0
        failure_hits = 0
        for record in getattr(memory_system, "experiences", {}).values():
            text = ""
            if hasattr(record, "searchable_text"):
                text = record.searchable_text()
            else:
                text = " ".join(str(getattr(record, field_name, "")) for field_name in ("goal", "task", "outcome", "correction"))
            if not any(token in text for token in query_tokens):
                continue
            if getattr(record, "success", False):
                success_hits += 1
            else:
                failure_hits += 1
        return {
            "success_bonus": min(8.0, success_hits * 4.0),
            "failure_penalty": min(7.0, failure_hits * 3.5),
        }

    def _frontier_risk_penalty(self, frontier: dict, observation: dict) -> float:
        danger_count = int(frontier.get("nearby_danger_count", frontier.get("danger_count", 0)) or 0)
        hostiles = [
            entity for entity in observation.get("nearby_entities", []) or []
            if isinstance(entity, dict) and entity.get("hostile")
        ]
        close_hostiles = sum(1 for entity in hostiles if float(entity.get("distance", 999) or 999) < 16)
        return min(12.0, danger_count * 3.0 + close_hostiles * 2.0)

    def _merge_feedback_records(self, current, incoming, limit: int = 20) -> list:
        records = list(current) if isinstance(current, list) else []
        incoming_records = incoming if isinstance(incoming, list) else []
        seen = {self._feedback_record_key(record) for record in records}
        for record in incoming_records:
            key = self._feedback_record_key(record)
            if not key or key in seen:
                continue
            records.append(record)
            seen.add(key)
        return records[:limit]

    def _feedback_record_key(self, record) -> str:
        if isinstance(record, dict):
            if record.get("id"):
                return str(record.get("id"))
            cell = record.get("cell")
            if isinstance(cell, dict):
                return "|".join([
                    str(record.get("resource") or record.get("direction") or record.get("type") or "cell"),
                    str(cell.get("x")),
                    str(cell.get("z")),
                ])
            return "|".join(f"{key}={record[key]}" for key in sorted(record))
        return str(record or "").strip()

    def _recently_repeated(self, title: str) -> bool:
        recent = [entry.get("goal") for entry in self.recent_goals[-3:]]
        return recent.count(title) >= 2

    def _deduplicate(self, candidates: list[CurriculumGoalCandidate]) -> list[CurriculumGoalCandidate]:
        best_by_title: dict[str, CurriculumGoalCandidate] = {}
        for candidate in candidates:
            previous = best_by_title.get(candidate.title)
            if previous is None or candidate.score > previous.score:
                best_by_title[candidate.title] = candidate
        return list(best_by_title.values())

    def _candidate_dict(self, candidate: CurriculumGoalCandidate) -> dict:
        return {
            "title": candidate.title,
            "category": candidate.category,
            "score": candidate.score,
            "reasons": candidate.reasons,
            "tags": candidate.tags,
            "target_items": candidate.target_items,
            "required_items": candidate.required_items,
            "skill_targets": candidate.skill_targets,
        }
