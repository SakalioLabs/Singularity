"""Task system — hierarchical task management with states, dependencies, and priorities."""
import time
import uuid
import logging
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


class TaskSystem:
    def __init__(self, use_causal_opportunities: bool = True):
        self.tasks: dict[str, Task] = {}
        self.root_tasks: list[str] = []
        self.use_causal_opportunities = use_causal_opportunities

    def create_task(self, title: str, task_type: str = "general", parent_id: Optional[str] = None, **kwargs) -> Task:
        task = Task(title=title, type=task_type, parent_id=parent_id, **kwargs)
        self.tasks[task.id] = task
        if parent_id and parent_id in self.tasks:
            self.tasks[parent_id].children.append(task.id)
        else:
            self.root_tasks.append(task.id)
        return task

    def update_task(self, task_id: str, status: Optional[TaskStatus] = None, observations: Optional[list] = None, result: Optional[dict] = None):
        task = self.tasks.get(task_id)
        if not task:
            return
        if status:
            task.status = status
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
            task.status = TaskStatus.ACTIVE

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
                task.status = TaskStatus.FAILED
                task.result = {"failed_action": action, "result": result, "reason": reason}
                task.updated_at = time.time()
            return task

        if self._success_criteria_satisfied(task, action, result, world_state or {}):
            task.status = TaskStatus.COMPLETED
            task.result = {
                "completed_by": "action_result",
                "action": action,
                "result": result,
                "world_state": self._compact_world_state(world_state or {}),
            }
            task.updated_at = time.time()
        return task

    def _dependencies_satisfied(self, task: Task) -> bool:
        for dep_id in task.depends_on:
            dep = self.tasks.get(dep_id)
            if not dep or dep.status != TaskStatus.COMPLETED:
                return False
        return True

    def _preconditions_satisfied(self, task: Task, world_state: dict) -> bool:
        inventory = world_state.get("inventory", {})
        for item, count in task.preconditions.get("inventory", {}).items():
            if inventory.get(item, 0) < count:
                return False
        flags = set(world_state.get("flags", []))
        for flag in task.preconditions.get("flags", []):
            if flag not in flags:
                return False
        return True

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
        reserved = {"action", "result", "flags", "health_at_least"}
        return {
            key: value
            for key, value in criteria.items()
            if key not in reserved and isinstance(value, (int, float))
        }

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

    def _compact_world_state(self, world_state: dict) -> dict:
        return {
            "inventory": world_state.get("inventory", {}),
            "health": world_state.get("health"),
            "position": world_state.get("position", {}),
            "time_of_day": world_state.get("time_of_day"),
        }
