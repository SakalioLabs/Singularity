"""M7 collaboration benchmark schema and feasibility checks."""
import json
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CollaborationRole:
    id: str
    description: str = ""
    capabilities: list[str] = field(default_factory=list)
    required: bool = True
    starting_inventory: dict = field(default_factory=dict)


@dataclass
class CollaborationTask:
    id: str
    title: str
    assigned_role: str
    description: str = ""
    priority: int = 3
    depends_on: list[str] = field(default_factory=list)
    required_capabilities: list[str] = field(default_factory=list)
    deadline_s: Optional[int] = None
    estimated_duration_s: int = 30
    preconditions: dict = field(default_factory=dict)
    success_criteria: dict = field(default_factory=dict)
    shared_state_updates: list[str] = field(default_factory=list)


@dataclass
class DynamicEvent:
    at_s: int
    event_type: str
    payload: dict = field(default_factory=dict)


@dataclass
class SharedStateSpec:
    required_keys: list[str] = field(default_factory=list)
    initial: dict = field(default_factory=dict)
    success_keys: list[str] = field(default_factory=list)


@dataclass
class CollaborationBenchmarkSpec:
    id: str
    name: str
    description: str = ""
    phase: str = "M7"
    max_duration_s: int = 600
    roles: list[CollaborationRole] = field(default_factory=list)
    tasks: list[CollaborationTask] = field(default_factory=list)
    shared_state: SharedStateSpec = field(default_factory=SharedStateSpec)
    success_criteria: dict = field(default_factory=dict)
    failure_risks: list[str] = field(default_factory=list)
    dynamic_events: list[DynamicEvent] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "CollaborationBenchmarkSpec":
        return cls(
            id=data["id"],
            name=data["name"],
            description=data.get("description", ""),
            phase=data.get("phase", "M7"),
            max_duration_s=int(data.get("max_duration_s", 600)),
            roles=[CollaborationRole(**role) for role in data.get("roles", [])],
            tasks=[CollaborationTask(**task) for task in data.get("tasks", [])],
            shared_state=SharedStateSpec(**data.get("shared_state", {})),
            success_criteria=data.get("success_criteria", {}),
            failure_risks=data.get("failure_risks", []),
            dynamic_events=[DynamicEvent(**event) for event in data.get("dynamic_events", [])],
        )

    @classmethod
    def load_json(cls, path: str) -> "CollaborationBenchmarkSpec":
        with open(path, "r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))

    def assignment_plan(self) -> dict[str, list[dict]]:
        """Return tasks grouped by role for leader/worker assignment."""
        plan: dict[str, list[dict]] = {role.id: [] for role in self.roles}
        for task in sorted(self.tasks, key=lambda item: (item.priority, item.deadline_s or self.max_duration_s)):
            plan.setdefault(task.assigned_role, []).append({
                "id": task.id,
                "title": task.title,
                "description": task.description,
                "priority": task.priority,
                "deadline_s": task.deadline_s,
                "depends_on": task.depends_on,
                "preconditions": task.preconditions,
                "success_criteria": task.success_criteria,
                "shared_state_updates": task.shared_state_updates,
            })
        return plan


@dataclass
class FeasibilityCheck:
    name: str
    status: str
    detail: str = ""
    remedy: str = ""


@dataclass
class FeasibilityReport:
    ok: bool
    checks: list[FeasibilityCheck] = field(default_factory=list)


class CollaborationFeasibilityChecker:
    """Approximate static checks before running an M7 collaboration benchmark."""

    def check(self, spec: CollaborationBenchmarkSpec) -> FeasibilityReport:
        checks = [
            self._check_roles(spec),
            self._check_task_assignments(spec),
            self._check_dependencies(spec),
            self._check_capabilities(spec),
            self._check_deadlines(spec),
            self._check_mandatory_collaboration(spec),
            self._check_shared_state(spec),
        ]
        return FeasibilityReport(ok=all(check.status != "fail" for check in checks), checks=checks)

    def _check_roles(self, spec: CollaborationBenchmarkSpec) -> FeasibilityCheck:
        role_ids = [role.id for role in spec.roles]
        if len(role_ids) < 2:
            return FeasibilityCheck("roles", "fail", "requires at least two roles", "add heterogeneous leader/worker roles")
        if len(role_ids) != len(set(role_ids)):
            return FeasibilityCheck("roles", "fail", "duplicate role ids", "make each role id unique")
        return FeasibilityCheck("roles", "pass", f"{len(role_ids)} roles")

    def _check_task_assignments(self, spec: CollaborationBenchmarkSpec) -> FeasibilityCheck:
        role_ids = {role.id for role in spec.roles}
        missing = [task.id for task in spec.tasks if task.assigned_role not in role_ids]
        if missing:
            return FeasibilityCheck("task_assignments", "fail", f"tasks with unknown role: {', '.join(missing)}", "assign every task to an existing role")
        if not spec.tasks:
            return FeasibilityCheck("task_assignments", "fail", "no tasks defined", "add at least one task per collaborating role")
        return FeasibilityCheck("task_assignments", "pass", f"{len(spec.tasks)} tasks assigned")

    def _check_dependencies(self, spec: CollaborationBenchmarkSpec) -> FeasibilityCheck:
        task_ids = {task.id for task in spec.tasks}
        missing = []
        for task in spec.tasks:
            for dep_id in task.depends_on:
                if dep_id not in task_ids:
                    missing.append(f"{task.id}->{dep_id}")
        if missing:
            return FeasibilityCheck("dependencies", "fail", f"missing dependencies: {', '.join(missing)}", "fix depends_on references")
        return FeasibilityCheck("dependencies", "pass", "all dependencies resolve")

    def _check_capabilities(self, spec: CollaborationBenchmarkSpec) -> FeasibilityCheck:
        role_caps = {role.id: set(role.capabilities) for role in spec.roles}
        missing = []
        for task in spec.tasks:
            lacking = set(task.required_capabilities) - role_caps.get(task.assigned_role, set())
            if lacking:
                missing.append(f"{task.id}:{','.join(sorted(lacking))}")
        if missing:
            return FeasibilityCheck("capabilities", "fail", f"missing capabilities: {'; '.join(missing)}", "move tasks to capable roles or add capabilities")
        return FeasibilityCheck("capabilities", "pass", "assigned roles cover required capabilities")

    def _check_deadlines(self, spec: CollaborationBenchmarkSpec) -> FeasibilityCheck:
        violations = []
        for task in spec.tasks:
            if task.deadline_s is not None and task.deadline_s > spec.max_duration_s:
                violations.append(f"{task.id}:deadline>{spec.max_duration_s}")
            if task.deadline_s is not None and task.estimated_duration_s > task.deadline_s:
                violations.append(f"{task.id}:estimate>{task.deadline_s}")
        if violations:
            return FeasibilityCheck("deadlines", "fail", "; ".join(violations), "increase deadlines or reduce estimated durations")
        events_late = [event.event_type for event in spec.dynamic_events if event.at_s > spec.max_duration_s]
        if events_late:
            return FeasibilityCheck("deadlines", "fail", f"events after max duration: {', '.join(events_late)}", "move dynamic events inside max_duration_s")
        return FeasibilityCheck("deadlines", "pass", "deadlines fit max duration")

    def _check_mandatory_collaboration(self, spec: CollaborationBenchmarkSpec) -> FeasibilityCheck:
        assigned_roles = {task.assigned_role for task in spec.tasks}
        required_roles = {role.id for role in spec.roles if role.required}
        active_required = assigned_roles & required_roles
        if len(active_required) < 2:
            return FeasibilityCheck("mandatory_collaboration", "fail", "only one required role has assigned tasks", "assign complementary tasks to at least two required roles")
        if not spec.shared_state.success_keys and not any(task.depends_on for task in spec.tasks):
            return FeasibilityCheck("mandatory_collaboration", "warn", "no shared-state success key or task dependency", "add handoff dependencies or shared-state success keys")
        return FeasibilityCheck("mandatory_collaboration", "pass", f"active roles: {', '.join(sorted(active_required))}")

    def _check_shared_state(self, spec: CollaborationBenchmarkSpec) -> FeasibilityCheck:
        missing = [key for key in spec.shared_state.required_keys if key not in spec.shared_state.initial]
        if missing:
            return FeasibilityCheck("shared_state", "fail", f"missing initial keys: {', '.join(missing)}", "initialize every required shared-state key")
        updates = {key for task in spec.tasks for key in task.shared_state_updates}
        unreachable = [key for key in spec.shared_state.success_keys if key not in updates and key not in spec.shared_state.initial]
        if unreachable:
            return FeasibilityCheck("shared_state", "fail", f"success keys never initialized or updated: {', '.join(unreachable)}", "add task shared_state_updates for success keys")
        return FeasibilityCheck("shared_state", "pass", "shared-state keys are initialized or reachable")
