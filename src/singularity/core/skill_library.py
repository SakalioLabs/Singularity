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
    dependencies: list[str] = field(default_factory=list)
    provenance: dict = field(default_factory=dict)
    gate: dict = field(default_factory=dict)


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
        scored: dict[str, tuple[float, Skill]] = {}
        for skill in self.skills.values():
            if skill.total_uses > 0:
                scored[skill.name] = (skill.success_rate + min(1.0, skill.total_uses * 0.05), skill)
        for skill in self._policy_skills(goal, world_state):
            score = self._policy_relevance_score(skill, goal, world_state) + 1.0
            previous = scored.get(skill.name)
            if previous is None or score > previous[0]:
                scored[skill.name] = (score, skill)
        for profile in self._skill_contract_profiles(goal, world_state, limit=0):
            if profile["score"] <= 0 or profile["readiness"] == "blocked":
                continue
            skill = self.skills.get(profile["name"])
            if not skill:
                continue
            previous = scored.get(skill.name)
            if previous is None or profile["score"] > previous[0]:
                scored[skill.name] = (profile["score"], skill)
        ranked = sorted(
            scored.values(),
            key=lambda item: (item[0], item[1].success_rate, item[1].total_uses),
            reverse=True,
        )
        return [skill for _, skill in ranked[:5]]

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

    def skill_graph_report(self) -> dict:
        """Return a typed, governance-oriented graph over known skills."""
        nodes = []
        edges = []
        skill_names = set(self.skills)
        builtin_names = self._builtin_skill_names()
        for skill in self.skills.values():
            dependencies = self._skill_dependencies(skill)
            missing_dependencies = [dep for dep in dependencies if dep not in skill_names]
            for dep in dependencies:
                edges.append({
                    "from": skill.name,
                    "to": dep,
                    "type": "depends_on" if dep in skill_names else "missing_dependency",
                })

            action_types = self._skill_action_types(skill)
            for action_type in action_types:
                edges.append({
                    "from": skill.name,
                    "to": f"action:{action_type}",
                    "type": "uses_action",
                })

            postcondition_keys = self._postcondition_keys(skill.postconditions)
            for key in postcondition_keys:
                edges.append({
                    "from": skill.name,
                    "to": f"postcondition:{key}",
                    "type": "has_postcondition",
                })

            built_in = skill.name in builtin_names
            governance = self._skill_governance(skill, built_in=built_in)
            issues = []
            if missing_dependencies:
                issues.append("missing_dependency")
            if not built_in and not governance["governed"]:
                issues.append("ungoverned_custom_skill")
            if not built_in and not postcondition_keys and governance["gate_readiness"] in {"unknown", "not_required"}:
                issues.append("missing_postconditions")
            if governance["gate_readiness"] in {"review", "rejected", "error"}:
                issues.append(f"gate_{governance['gate_readiness']}")

            nodes.append({
                "name": skill.name,
                "layer": skill.layer,
                "built_in": built_in,
                "dependencies": dependencies,
                "missing_dependencies": missing_dependencies,
                "action_types": action_types,
                "postcondition_keys": postcondition_keys,
                "governance": governance,
                "issues": issues,
            })

        cycles = self._skill_dependency_cycles(nodes)
        issue_counts = {}
        for node in nodes:
            for issue in node["issues"]:
                issue_counts[issue] = issue_counts.get(issue, 0) + 1
        return {
            "skill_count": len(nodes),
            "custom_skill_count": sum(1 for node in nodes if not node["built_in"]),
            "edge_count": len(edges),
            "missing_dependency_count": sum(len(node["missing_dependencies"]) for node in nodes),
            "ungoverned_custom_skill_count": issue_counts.get("ungoverned_custom_skill", 0),
            "missing_postcondition_count": issue_counts.get("missing_postconditions", 0),
            "cycle_count": len(cycles),
            "issue_counts": issue_counts,
            "cycles": cycles,
            "nodes": sorted(nodes, key=lambda node: (node["layer"], node["name"])),
            "edges": sorted(edges, key=lambda edge: (edge["from"], edge["type"], edge["to"])),
        }

    def skill_contract_report(self, goal: str = "", world_state: Optional[dict] = None, limit: int = 20) -> dict:
        """Return COS-PLAY-style skill contract readiness and retrieval evidence."""
        all_profiles = self._skill_contract_profiles(goal, world_state or {}, limit=0)
        profiles = all_profiles[:limit] if limit and limit > 0 else all_profiles
        issue_counts = {}
        for profile in all_profiles:
            for issue in profile["issues"]:
                issue_counts[issue] = issue_counts.get(issue, 0) + 1
        return {
            "goal": goal,
            "skill_count": len(self.skills),
            "matched_count": sum(1 for profile in all_profiles if profile["score"] > 0),
            "ready_count": sum(1 for profile in all_profiles if profile["readiness"] == "ready"),
            "blocked_count": sum(1 for profile in all_profiles if profile["readiness"] == "blocked"),
            "review_count": sum(1 for profile in all_profiles if profile["readiness"] == "review"),
            "issue_counts": issue_counts,
            "matches": profiles,
        }

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

    def _skill_contract_profiles(self, goal: str, world_state: dict, limit: int = 20) -> list[dict]:
        profiles = [
            self._skill_contract_profile(skill, goal, world_state or {})
            for skill in self.skills.values()
        ]
        profiles.sort(
            key=lambda item: (
                item["score"],
                1 if item["readiness"] == "ready" else 0,
                item["success_rate"],
                item["total_uses"],
            ),
            reverse=True,
        )
        return profiles[:limit] if limit and limit > 0 else profiles

    def _skill_contract_profile(self, skill: Skill, goal: str, world_state: dict) -> dict:
        inventory = world_state.get("inventory", {}) if isinstance(world_state.get("inventory", {}), dict) else {}
        builtin_names = self._builtin_skill_names()
        goal_tokens = self._keywords(goal)
        state_tokens = self._keywords(json.dumps({
            "inventory": inventory,
            "nearby_blocks": world_state.get("nearby_blocks", []),
            "nearby_entities": world_state.get("nearby_entities", []),
            "grounded_resources": world_state.get("grounded_resources", []),
        }, default=str))
        contract_text = " ".join([
            skill.name,
            skill.description,
            json.dumps(skill.parameters, default=str),
            json.dumps(skill.preconditions, default=str),
            json.dumps(skill.postconditions, default=str),
            " ".join(str(item) for item in skill.required_items),
        ])
        contract_tokens = self._keywords(contract_text)
        goal_matches = sorted(goal_tokens & contract_tokens)
        state_matches = sorted(state_tokens & contract_tokens)
        postcondition_targets = self._postcondition_keys(skill.postconditions)
        postcondition_tokens = self._keywords(" ".join(postcondition_targets))
        postcondition_matches = sorted(goal_tokens & postcondition_tokens)

        missing_preconditions = self._missing_preconditions(skill, world_state)
        missing_required_items = self._missing_required_items(skill, inventory)
        dependencies = self._skill_dependencies(skill)
        missing_dependencies = [dep for dep in dependencies if dep not in self.skills]
        governance = self._skill_governance(skill, built_in=skill.name in builtin_names)

        issues = []
        if missing_preconditions:
            issues.append("missing_preconditions")
        if missing_required_items:
            issues.append("missing_required_items")
        if missing_dependencies:
            issues.append("missing_dependencies")
        if governance["gate_readiness"] in {"review", "rejected", "error"}:
            issues.append(f"gate_{governance['gate_readiness']}")
        if skill.name not in builtin_names and not postcondition_targets:
            issues.append("missing_postconditions")
        if not skill.preconditions and not skill.required_items and skill.layer in {"composite", "strategic"}:
            issues.append("underspecified_preconditions")

        score = 0.0
        score += len(goal_matches) * 1.4
        score += len(state_matches) * 0.8
        score += len(postcondition_matches) * 2.0
        if skill.total_uses:
            score += skill.success_rate + min(1.0, skill.total_uses * 0.05)
        if governance["gate_readiness"] == "approved":
            score += 1.0
        score -= len(missing_preconditions) * 2.0
        score -= len(missing_required_items) * 2.0
        score -= len(missing_dependencies) * 3.0
        score = round(max(0.0, score), 4)

        if missing_dependencies or governance["gate_readiness"] in {"rejected", "error"}:
            readiness = "blocked"
        elif missing_preconditions or missing_required_items or governance["gate_readiness"] == "review":
            readiness = "review"
        else:
            readiness = "ready"

        return {
            "name": skill.name,
            "layer": skill.layer,
            "description": skill.description,
            "score": score,
            "readiness": readiness,
            "success_rate": round(skill.success_rate, 4),
            "total_uses": skill.total_uses,
            "goal_matches": goal_matches[:12],
            "state_matches": state_matches[:12],
            "postcondition_targets": postcondition_targets,
            "postcondition_matches": postcondition_matches[:12],
            "required_items": list(skill.required_items),
            "missing_required_items": missing_required_items,
            "missing_preconditions": missing_preconditions,
            "dependencies": dependencies,
            "missing_dependencies": missing_dependencies,
            "gate_readiness": governance["gate_readiness"],
            "issues": sorted(set(issues)),
        }

    def _missing_required_items(self, skill: Skill, inventory: dict) -> list[str]:
        missing = []
        for item in skill.required_items or []:
            if isinstance(item, dict):
                name = str(item.get("item") or item.get("name") or "").strip()
                needed = self._safe_int(item.get("count", 1), default=1)
            else:
                name = str(item or "").strip()
                needed = 1
            if name and self._inventory_quantity(inventory, name) < needed:
                missing.append(name if needed <= 1 else f"{name}>={needed}")
        return missing

    def _missing_preconditions(self, skill: Skill, world_state: dict) -> list[str]:
        preconditions = skill.preconditions if isinstance(skill.preconditions, dict) else {}
        inventory = world_state.get("inventory", {}) if isinstance(world_state.get("inventory", {}), dict) else {}
        flags = set(str(flag).lower() for flag in world_state.get("flags", []) if flag)
        missing = []
        inventory_preconditions = (
            preconditions.get("inventory", {})
            if isinstance(preconditions.get("inventory", {}), dict)
            else {}
        )
        for item, count in inventory_preconditions.items():
            needed = self._safe_int(count, default=1)
            if self._inventory_quantity(inventory, item) < needed:
                missing.append(f"inventory:{item}>={needed}")
        flag_preconditions = (
            preconditions.get("flags", [])
            if isinstance(preconditions.get("flags", []), list)
            else []
        )
        for flag in flag_preconditions:
            if str(flag).lower() not in flags:
                missing.append(f"flag:{flag}")
        nearby = self._world_state_nearby_names(world_state)
        nearby_preconditions = (
            preconditions.get("nearby_block_present", [])
            if isinstance(preconditions.get("nearby_block_present", []), list)
            else []
        )
        for block in nearby_preconditions:
            if str(block).lower() not in nearby:
                missing.append(f"nearby_block:{block}")
        return missing

    def _inventory_quantity(self, inventory: dict, item: str) -> int:
        if not isinstance(inventory, dict):
            return 0
        target = str(item or "").strip().lower()
        for key, value in inventory.items():
            if str(key).strip().lower() == target:
                return self._safe_int(value, default=1 if value else 0)
        return 0

    def _safe_int(self, value, default: int = 0) -> int:
        if value in (None, ""):
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            try:
                return int(float(value))
            except (TypeError, ValueError):
                return default

    def _world_state_nearby_names(self, world_state: dict) -> set[str]:
        names = set()
        for key in ("nearby_blocks", "grounded_resources", "visible_blocks", "resources"):
            value = world_state.get(key, [])
            if isinstance(value, dict):
                iterable = value.values()
            elif isinstance(value, list):
                iterable = value
            else:
                iterable = []
            for item in iterable:
                if isinstance(item, dict):
                    raw = item.get("name") or item.get("type") or item.get("block") or item.get("resource")
                else:
                    raw = item
                text = str(raw or "").strip().lower()
                if text:
                    names.add(text)
        return names

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

    def _implementation_actions(self, skill: Skill) -> list[dict]:
        try:
            payload = json.loads(skill.implementation)
        except (TypeError, ValueError):
            return []
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            return self._payload_actions(payload)
        return []

    def _skill_action_types(self, skill: Skill) -> list[str]:
        action_types = []
        for action in self._implementation_actions(skill):
            action_type = str(action.get("type", "")).strip()
            if action_type and action_type not in action_types:
                action_types.append(action_type)
        return action_types

    def _skill_dependencies(self, skill: Skill) -> list[str]:
        dependencies = []
        raw_dependencies = skill.dependencies if isinstance(skill.dependencies, list) else [skill.dependencies]
        for dep in raw_dependencies:
            text = str(dep or "").strip()
            if text and text not in dependencies:
                dependencies.append(text)
        action_to_skill = {
            "move_to": "move_to",
            "look_at": "look_at",
            "dig": "dig_block",
            "dig_block": "dig_block",
            "place": "place_block",
            "place_block": "place_block",
            "craft": "craft_item",
            "craft_item": "craft_item",
            "attack": "attack_entity",
            "attack_entity": "attack_entity",
            "eat": "eat_food",
            "eat_food": "eat_food",
        }
        for action_type in self._skill_action_types(skill):
            dep = action_to_skill.get(action_type)
            if dep and dep != skill.name and dep not in dependencies:
                dependencies.append(dep)
        return dependencies

    def _postcondition_keys(self, postconditions: dict) -> list[str]:
        if not isinstance(postconditions, dict):
            return []
        keys = []
        inventory = postconditions.get("inventory", {}) if isinstance(postconditions.get("inventory", {}), dict) else {}
        for item in sorted(inventory):
            keys.append(f"inventory:{item}")
        for key, value in sorted(postconditions.items()):
            if key == "inventory":
                continue
            if isinstance(value, dict):
                for subkey in sorted(value):
                    keys.append(f"{key}:{subkey}")
            elif value not in (None, "", [], {}):
                keys.append(str(key))
        return keys

    def _skill_governance(self, skill: Skill, built_in: bool = False) -> dict:
        gate = skill.gate if isinstance(skill.gate, dict) else {}
        provenance = skill.provenance if isinstance(skill.provenance, dict) else {}
        notes = str(skill.notes or "")
        verification_gate = gate.get("verification", {}) if isinstance(gate.get("verification", {}), dict) else {}
        discovery_gate = gate.get("discovery", {}) if isinstance(gate.get("discovery", {}), dict) else {}
        transfer_gate = gate.get("transfer", {}) if isinstance(gate.get("transfer", {}), dict) else {}
        gate_readiness = self._gate_readiness(gate, verification_gate, discovery_gate, transfer_gate)
        governed = bool(
            built_in
            or gate
            or provenance
            or "promotion_report" in notes
            or "review=approved" in notes
            or self._postcondition_keys(skill.postconditions)
        )
        return {
            "governed": governed,
            "gate_readiness": gate_readiness,
            "decision": gate.get("decision", "builtin" if built_in else "unknown"),
            "verification_status": verification_gate.get("status", ""),
            "discovery_readiness": discovery_gate.get("readiness", ""),
            "transfer_readiness": transfer_gate.get("readiness", ""),
            "provenance_sources": self._provenance_sources(provenance),
        }

    def _gate_readiness(self, gate: dict, verification_gate: dict, discovery_gate: dict, transfer_gate: dict = None) -> str:
        transfer_gate = transfer_gate if isinstance(transfer_gate, dict) else {}
        if not gate:
            return "not_required"
        if discovery_gate.get("readiness") in {"review", "rejected", "error"}:
            return str(discovery_gate.get("readiness"))
        if transfer_gate.get("readiness") in {"review", "rejected", "error"}:
            return str(transfer_gate.get("readiness"))
        if gate.get("decision") == "reject" or verification_gate.get("decision") == "reject":
            return "rejected"
        if transfer_gate.get("readiness") == "approved":
            return "approved"
        if discovery_gate.get("readiness") == "approved":
            return "approved"
        if verification_gate.get("status") in {"achieved", "critic_approved"} or gate.get("decision") == "approve":
            return "approved"
        return "unknown"

    def _provenance_sources(self, provenance: dict) -> list[str]:
        sources = []
        for key in ("source_log", "candidate_id", "goal", "reviewer"):
            value = provenance.get(key)
            if value not in (None, "", [], {}):
                sources.append(f"{key}:{value}")
        return sources

    def _skill_dependency_cycles(self, nodes: list[dict]) -> list[list[str]]:
        graph = {
            node["name"]: [dep for dep in node["dependencies"] if dep in self.skills]
            for node in nodes
        }
        cycles = []
        seen_cycles = set()

        def visit(node: str, path: list[str]):
            if node in path:
                cycle = path[path.index(node):] + [node]
                body = cycle[:-1]
                rotations = [tuple(body[index:] + body[:index]) for index in range(len(body))]
                key = min(rotations)
                if key not in seen_cycles:
                    seen_cycles.add(key)
                    cycles.append(list(key) + [key[0]])
                return
            for dep in graph.get(node, []):
                visit(dep, path + [node])

        for node in graph:
            visit(node, [])
        return cycles

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
