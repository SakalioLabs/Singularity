"""Task system — hierarchical task management with states, dependencies, and priorities."""
import time
import uuid
import logging
import math
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("singularity.task")


class TaskStatus(Enum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    ACTIVE = "active"
    WAITING = "waiting"
    BLOCKED = "blocked"
    FAILED = "failed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


@dataclass
class Task:
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    title: str = ""
    type: str = "general"
    parent_id: Optional[str] = None
    status: TaskStatus = TaskStatus.PROPOSED
    priority: int = 3  # 0=highest
    preconditions: dict = field(default_factory=dict)
    success_criteria: dict = field(default_factory=dict)
    failure_criteria: dict = field(default_factory=dict)
    assigned_skill: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    attempts: int = 0
    observations: list = field(default_factory=list)
    blockers: list = field(default_factory=list)
    result: Optional[dict] = None
    children: list = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    opportunity_triggers: list[str] = field(default_factory=list)
    deadline: Optional[float] = None
    rationale: str = ""
    plan_node_id: str = ""
    root_plan_id: str = ""
    planner_call_id: str = ""
    status_history: list[dict] = field(default_factory=list)


class TaskSystem:
    def __init__(self, use_causal_opportunities: bool = True):
        self.tasks: dict[str, Task] = {}
        self.root_tasks: list[str] = []
        self.use_causal_opportunities = use_causal_opportunities
        self._transition_events: list[dict] = []

    def create_task(self, title: str, task_type: str = "general", parent_id: Optional[str] = None, **kwargs) -> Task:
        task = Task(title=title, type=task_type, parent_id=parent_id, **kwargs)
        self.tasks[task.id] = task
        if parent_id and parent_id in self.tasks:
            self.tasks[parent_id].children.append(task.id)
        else:
            self.root_tasks.append(task.id)
        self._record_transition(task, None, task.status, "task_created")
        return task

    def update_task(self, task_id: str, status: Optional[TaskStatus] = None, observations: Optional[list] = None, result: Optional[dict] = None):
        task = self.tasks.get(task_id)
        if not task:
            return
        if status and status != task.status:
            self._set_status(task, status, "task_updated")
        if observations:
            task.observations.extend(observations)
        if result:
            task.result = result
        task.updated_at = time.time()
        if status == TaskStatus.FAILED:
            task.attempts += 1

    def get_ready_tasks(self, world_state: Optional[dict] = None) -> list[Task]:
        """Return runnable tasks whose dependencies and preconditions are satisfied."""
        candidates = [
            t for t in self.tasks.values()
            if t.status in (TaskStatus.ACCEPTED, TaskStatus.ACTIVE)
        ]
        ready = [t for t in candidates if self._dependencies_satisfied(t) and self._preconditions_satisfied(t, world_state or {})]
        ready.sort(key=lambda t: self._task_score(t, world_state or {}))
        return ready

    def task_readiness_report(self, world_state: Optional[dict] = None) -> dict:
        """Explain which runnable-state tasks are ready and what blocks the rest."""
        world_state = world_state or {}
        candidates = [
            t for t in self.tasks.values()
            if t.status in (TaskStatus.ACCEPTED, TaskStatus.ACTIVE)
        ]
        task_reports = []
        ready_count = 0
        for task in candidates:
            missing_dependencies = self._missing_dependencies(task)
            missing_preconditions = self._missing_preconditions(task, world_state)
            inherited_blockers = [str(item) for item in (task.blockers or []) if item]
            blockers = []
            if missing_dependencies:
                blockers.append("missing_dependencies")
            if missing_preconditions:
                blockers.append("missing_preconditions")
            blockers.extend(inherited_blockers[:5])
            ready = not missing_dependencies and not missing_preconditions
            if ready:
                ready_count += 1
            task_reports.append({
                "id": task.id,
                "title": task.title,
                "type": task.type,
                "status": task.status.value,
                "priority": task.priority,
                "attempts": task.attempts,
                "ready": ready,
                "score": round(self._task_score(task, world_state), 3),
                "missing_dependencies": missing_dependencies,
                "missing_preconditions": missing_preconditions,
                "blockers": blockers,
                "assigned_skill": task.assigned_skill or "",
                "preconditions": dict(task.preconditions or {}),
                "success_criteria": dict(task.success_criteria or {}),
                "tags": list(task.tags or [])[:8],
                "opportunity_triggers": list(task.opportunity_triggers or [])[:8],
                "rationale": task.rationale,
            })
        task_reports.sort(key=lambda item: (
            0 if item["ready"] else 1,
            item["score"],
            item["priority"],
            item["title"],
        ))
        return {
            "type": "task_readiness_report",
            "task_count": len(task_reports),
            "ready_count": ready_count,
            "blocked_count": len(task_reports) - ready_count,
            "accepted_count": sum(1 for task in candidates if task.status == TaskStatus.ACCEPTED),
            "active_count": sum(1 for task in candidates if task.status == TaskStatus.ACTIVE),
            "tasks": task_reports,
        }

    def get_next_task(self, world_state: Optional[dict] = None) -> Optional[Task]:
        """Return the best next task using priority plus opportunistic context."""
        ready = self.get_ready_tasks(world_state)
        return ready[0] if ready else None

    def get_task_tree(self) -> dict:
        def build_tree(task_id):
            task = self.tasks.get(task_id)
            if not task:
                return None
            return {"task": task, "children": [build_tree(cid) for cid in task.children if cid in self.tasks]}
        return {tid: build_tree(tid) for tid in self.root_tasks if tid in self.tasks}

    def fail_task(self, task_id: str, reason: str):
        self.update_task(task_id, status=TaskStatus.FAILED, observations=[f"FAILURE: {reason}"])

    def complete_task(self, task_id: str, result: dict = None):
        self.update_task(task_id, status=TaskStatus.COMPLETED, result=result or {})

    def complete_verified_plan(self, root_plan_id: str, result: dict = None) -> list[str]:
        """Close one machine-verified root plan in dependency order with full state paths."""
        root_id = str(root_plan_id or "")
        if not root_id:
            return []
        terminal = {TaskStatus.COMPLETED, TaskStatus.CANCELLED, TaskStatus.FAILED}
        completed = []
        candidates = [
            task for task in self.tasks.values()
            if task.root_plan_id == root_id and task.status not in terminal
        ]
        while candidates:
            progressed = False
            for task in list(candidates):
                if not self._dependencies_satisfied(task):
                    continue
                if task.status == TaskStatus.PROPOSED:
                    self._set_status(task, TaskStatus.ACCEPTED, "machine_verified_plan_acceptance")
                if task.status == TaskStatus.ACCEPTED:
                    self._set_status(task, TaskStatus.ACTIVE, "machine_verified_plan_activation")
                if task.status == TaskStatus.ACTIVE:
                    self._set_status(task, TaskStatus.COMPLETED, "machine_verified_goal")
                    task.result = {
                        "completed_by": "machine_goal_verifier",
                        **(result or {}),
                    }
                    task.updated_at = time.time()
                    completed.append(task.id)
                candidates.remove(task)
                progressed = True
            if not progressed:
                break
        return completed

    def drain_transition_events(self) -> list[dict]:
        events = list(self._transition_events)
        self._transition_events.clear()
        return events

    def apply_action_result(
        self,
        action: dict,
        result: dict,
        world_state: Optional[dict] = None,
        task_id: Optional[str] = None,
    ) -> Optional[Task]:
        """Update the active/ready task using an action result and latest world state."""
        task = self.tasks.get(task_id) if task_id else self.get_next_task(world_state or {})
        if not task or task.status not in (TaskStatus.ACCEPTED, TaskStatus.ACTIVE):
            return None

        if task.status == TaskStatus.ACCEPTED:
            self._set_status(task, TaskStatus.ACTIVE, "action_started")

        action_summary = {
            "action": action,
            "success": bool(result.get("success")),
            "error": result.get("error"),
            "action_type": result.get("action_type", action.get("type")),
        }
        task.observations.append(action_summary)
        task.result = {"last_action": action, "last_result": result}
        task.updated_at = time.time()

        if not result.get("success"):
            task.attempts += 1
            reason = result.get("error", "action failed")
            task.blockers.append(reason)
            if self._failure_criteria_satisfied(task, result, world_state or {}):
                self._set_status(task, TaskStatus.FAILED, "failure_criteria_satisfied")
                task.result = {"failed_action": action, "result": result, "reason": reason}
                task.updated_at = time.time()
            return task

        if self._success_criteria_satisfied(task, action, result, world_state or {}):
            self._set_status(task, TaskStatus.COMPLETED, "success_criteria_satisfied")
            task.result = {
                "completed_by": "action_result",
                "action": action,
                "result": result,
                "world_state": self._compact_world_state(world_state or {}),
            }
            task.updated_at = time.time()
        return task

    def _set_status(self, task: Task, status: TaskStatus, reason: str):
        previous = task.status
        task.status = status
        task.updated_at = time.time()
        self._record_transition(task, previous, status, reason)

    def _record_transition(
        self,
        task: Task,
        previous: Optional[TaskStatus],
        current: TaskStatus,
        reason: str,
    ):
        payload = {
            "type": "task_state_transition",
            "task_id": task.id,
            "task_title": task.title,
            "plan_node_id": task.plan_node_id,
            "root_plan_id": task.root_plan_id,
            "planner_call_id": task.planner_call_id,
            "from_status": previous.value if previous else "",
            "to_status": current.value,
            "reason": reason,
            "timestamp": time.time(),
        }
        task.status_history.append(dict(payload))
        self._transition_events.append(payload)

    def _dependencies_satisfied(self, task: Task) -> bool:
        return not self._missing_dependencies(task)

    def _missing_dependencies(self, task: Task) -> list[dict]:
        missing = []
        for dep_id in task.depends_on:
            dep = self.tasks.get(dep_id)
            if not dep or dep.status != TaskStatus.COMPLETED:
                missing.append({
                    "id": dep_id,
                    "title": dep.title if dep else "",
                    "status": dep.status.value if dep else "missing",
                })
        return missing

    def _preconditions_satisfied(self, task: Task, world_state: dict) -> bool:
        return not self._missing_preconditions(task, world_state)

    def _missing_preconditions(self, task: Task, world_state: dict) -> dict:
        missing = {}
        preconditions = task.preconditions or {}
        inventory = world_state.get("inventory", {}) if isinstance(world_state.get("inventory", {}), dict) else {}
        inventory_requirements = preconditions.get("inventory", {}) if isinstance(preconditions.get("inventory", {}), dict) else {}
        inventory_missing = {}
        for item, count in inventory_requirements.items():
            required_count = self._safe_count(count)
            available_count = self._safe_count(inventory.get(item, 0))
            if available_count < required_count:
                inventory_missing[str(item)] = self._compact_count(required_count - available_count)
        if inventory_missing:
            missing["inventory"] = dict(sorted(inventory_missing.items()))
        world_flags = world_state.get("flags", []) if isinstance(world_state.get("flags", []), list) else []
        flags = {str(flag) for flag in world_flags}
        required_flags = preconditions.get("flags", []) if isinstance(preconditions.get("flags", []), list) else []
        missing_flags = [
            str(flag)
            for flag in required_flags
            if str(flag) not in flags
        ]
        if missing_flags:
            missing["flags"] = missing_flags
        nearby_required = preconditions.get("nearby_block_present", [])
        missing_nearby = self._missing_observed_names(nearby_required, world_state)
        if missing_nearby:
            missing["nearby_block_present"] = missing_nearby
        return missing

    def _task_score(self, task: Task, world_state: dict) -> float:
        """Lower score means higher urgency."""
        score = task.priority * 100 + task.attempts * 10
        score -= self._opportunity_bonus(task, world_state)
        if task.deadline:
            seconds_left = task.deadline - time.time()
            if seconds_left <= 0:
                score -= 80
            elif seconds_left < 120:
                score -= 40
        if task.status == TaskStatus.ACTIVE:
            score -= 10
        return score

    def _opportunity_bonus(self, task: Task, world_state: dict) -> int:
        if not task.opportunity_triggers:
            return 0
        context_words = self._context_words(world_state)
        causal_words = self._causal_words(world_state) if self.use_causal_opportunities else set()
        direct_matches = 0
        causal_matches = 0
        for trigger in task.opportunity_triggers:
            trigger = trigger.lower()
            if trigger in context_words:
                direct_matches += 1
            elif trigger in causal_words:
                causal_matches += 1
        return direct_matches * 35 + causal_matches * 20

    def _context_words(self, world_state: dict) -> set[str]:
        words = set()
        inventory = world_state.get("inventory", {})
        words.update(str(k).lower() for k, v in inventory.items() if v)
        for block in world_state.get("nearby_blocks", []):
            words.add(str(block.get("name", "")).lower())
        for resource in world_state.get("grounded_resources", []):
            words.add(str(resource.get("name", "")).lower())
            words.add(str(resource.get("drop", "")).lower())
        for entity in world_state.get("nearby_entities", []):
            words.add(str(entity.get("type", entity.get("name", ""))).lower())
        for tag in world_state.get("tags", []):
            words.add(str(tag).lower())
        return words

    def _causal_words(self, world_state: dict) -> set[str]:
        words = set()
        for tag in world_state.get("causal_tags", []):
            words.add(str(tag).lower())
        for event in world_state.get("causal_events", []):
            words.add(str(event.get("subject", "")).lower())
            words.add(str(event.get("action_type", "")).lower())
            words.add(str(event.get("outcome", "")).lower())
            for tag in event.get("tags", []):
                words.add(str(tag).lower())
        return {word for word in words if word}

    def _success_criteria_satisfied(self, task: Task, action: dict, result: dict, world_state: dict) -> bool:
        criteria = task.success_criteria or {}
        if not criteria:
            return False

        checks = []
        inventory_requirements = self._inventory_requirements(criteria)
        if inventory_requirements:
            checks.append(self._inventory_satisfies(inventory_requirements, world_state, action, result))
        if "action" in criteria:
            checks.append(self._dict_matches(criteria["action"], action))
        if "result" in criteria:
            checks.append(self._dict_matches(criteria["result"], result))
        if "flags" in criteria:
            checks.append(all(flag in set(world_state.get("flags", [])) for flag in criteria["flags"]))
        if "health_at_least" in criteria:
            checks.append(world_state.get("health", 0) >= criteria["health_at_least"])
        if "position_near" in criteria:
            checks.append(self._position_near(criteria["position_near"], world_state, action, result))
        if "observed" in criteria:
            checks.append(self._observed_names_satisfy(criteria["observed"], world_state, result=result))
        if "nearby_block_present" in criteria:
            checks.append(self._observed_names_satisfy(criteria["nearby_block_present"], world_state))
        return bool(checks) and all(checks)

    def _failure_criteria_satisfied(self, task: Task, result: dict, world_state: dict) -> bool:
        criteria = task.failure_criteria or {}
        if not criteria:
            return False
        max_failures = criteria.get("max_failures")
        if max_failures is not None and task.attempts >= max_failures:
            return True
        error = str(result.get("error", "")).lower()
        for token in criteria.get("errors", []):
            if str(token).lower() in error:
                return True
        if "result" in criteria and self._dict_matches(criteria["result"], result):
            return True
        health_below = criteria.get("health_below")
        if health_below is not None and world_state.get("health", 20) < health_below:
            return True
        return False

    def _inventory_requirements(self, criteria: dict) -> dict:
        if isinstance(criteria.get("inventory"), dict):
            return criteria["inventory"]
        reserved = {
            "action",
            "result",
            "flags",
            "health_at_least",
            "position_near",
            "observed",
            "nearby_block_present",
        }
        return {
            key: value
            for key, value in criteria.items()
            if key not in reserved and isinstance(value, (int, float))
        }

    def _position_near(self, target: dict, world_state: dict, action: dict, result: dict) -> bool:
        if not isinstance(target, dict):
            return False
        current = world_state.get("position", {}) if isinstance(world_state.get("position", {}), dict) else {}
        if not current and result.get("success") and action.get("type") in {"move_to", "walk_to"}:
            current = action.get("parameters", {}) if isinstance(action.get("parameters", {}), dict) else {}
        if not current:
            return False
        radius = float(target.get("radius", target.get("tolerance", 4.0)) or 4.0)
        dx = float(current.get("x", 0) or 0) - float(target.get("x", 0) or 0)
        dz = float(current.get("z", 0) or 0) - float(target.get("z", 0) or 0)
        if "y" in target:
            dy = float(current.get("y", target.get("y", 0)) or 0) - float(target.get("y", 0) or 0)
            return math.sqrt(dx * dx + dy * dy + dz * dz) <= radius
        return math.sqrt(dx * dx + dz * dz) <= radius

    def _observed_names_satisfy(self, required, world_state: dict, result: dict = None) -> bool:
        required_names = self._required_name_set(required)
        if not required_names:
            return True
        observed = self._observed_name_set(world_state or {}, result or {})
        return all(name in observed for name in required_names)

    def _missing_observed_names(self, required, world_state: dict, result: dict = None) -> list[str]:
        required_names = self._required_name_set(required)
        if not required_names:
            return []
        observed = self._observed_name_set(world_state or {}, result or {})
        return sorted(name for name in required_names if name not in observed)

    def _required_name_set(self, required) -> set[str]:
        if isinstance(required, str):
            return {required.lower()} if required else set()
        if isinstance(required, dict):
            return {
                str(value).lower()
                for value in required.values()
                if value
            }
        if isinstance(required, list):
            return {
                str(value).lower()
                for value in required
                if value
            }
        return set()

    def _observed_name_set(self, world_state: dict, result: dict) -> set[str]:
        names = set()
        for key in ("nearby_blocks", "grounded_resources", "trees_found", "nearby_entities", "landmarks"):
            for item in world_state.get(key, []) or []:
                if isinstance(item, str):
                    names.add(item.lower())
                    continue
                if not isinstance(item, dict):
                    continue
                for field_name in ("name", "type", "block", "resource", "drop", "entity"):
                    value = item.get(field_name)
                    if value:
                        names.add(str(value).lower())
        for field_name in ("observed", "block", "resource", "entity", "item"):
            value = result.get(field_name)
            if isinstance(value, list):
                names.update(str(item).lower() for item in value if item)
            elif value:
                names.add(str(value).lower())
        if world_state.get("landmarks"):
            names.add("landmark")
        return names

    def _inventory_satisfies(self, requirements: dict, world_state: dict, action: dict, result: dict) -> bool:
        inventory = dict(world_state.get("inventory", {}))
        if result.get("success"):
            action_type = action.get("type")
            params = action.get("parameters", {})
            if action_type == "craft":
                item = result.get("item") or params.get("item")
                if item:
                    inventory[item] = max(inventory.get(item, 0), params.get("count", 1))
            elif action_type == "dig":
                block = result.get("block")
                if block:
                    inventory[block] = max(inventory.get(block, 0), 1)
        return all(inventory.get(item, 0) >= count for item, count in requirements.items())

    def _dict_matches(self, expected: dict, actual: dict) -> bool:
        for key, value in expected.items():
            if isinstance(value, dict):
                if not self._dict_matches(value, actual.get(key, {})):
                    return False
            elif actual.get(key) != value:
                return False
        return True

    def _safe_count(self, value) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0

    def _compact_count(self, value):
        if float(value).is_integer():
            return int(value)
        return round(float(value), 3)

    def _compact_world_state(self, world_state: dict) -> dict:
        return {
            "inventory": world_state.get("inventory", {}),
            "health": world_state.get("health"),
            "position": world_state.get("position", {}),
            "time_of_day": world_state.get("time_of_day"),
        }
