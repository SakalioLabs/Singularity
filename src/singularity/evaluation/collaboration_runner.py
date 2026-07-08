"""Runner for M7 collaboration benchmark specs."""
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from typing import Callable, Optional

from singularity.core.memory_policy import MemoryLifecyclePolicy
from singularity.evaluation.collaboration_benchmark import (
    CollaborationBenchmarkSpec,
    CollaborationRole,
    CollaborationFeasibilityChecker,
    FeasibilityCheck,
    FeasibilityReport,
)
from singularity.multiagent.coordinator import AgentWorker, LeaderAgent
from singularity.multiagent.protocol import SharedState

TaskExecutor = Callable[[dict, dict, dict], dict]


@dataclass
class CollaborationRunResult:
    spec_id: str
    ok: bool
    state_path: str
    leader_id: str = ""
    assigned_tasks: int = 0
    role_task_counts: dict[str, int] = field(default_factory=dict)
    checks: list[FeasibilityCheck] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class CollaborationTaskExecution:
    task_id: str
    source_task_id: str
    assigned_to: str
    status: str
    elapsed_s: float
    started_at_s: float = 0.0
    finished_at_s: float = 0.0
    duration_s: float = 0.0
    deadline_missed: bool = False
    shared_updates: dict = field(default_factory=dict)
    shared_update_provenance: dict = field(default_factory=dict)
    shared_memory_decisions: dict = field(default_factory=dict)
    result: dict = field(default_factory=dict)
    error: str = ""


@dataclass
class CollaborationExecutionReport:
    spec_id: str
    ok: bool
    state_path: str
    dispatch_mode: str = "role_parallel"
    dispatch_batches: int = 0
    max_parallel_tasks: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    skipped_tasks: int = 0
    deadline_misses: int = 0
    success_keys_satisfied: bool = False
    total_elapsed_s: float = 0.0
    shared_state: dict = field(default_factory=dict)
    shared_memory_governance: dict = field(default_factory=dict)
    task_results: list[CollaborationTaskExecution] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class CollaborationScheduleItem:
    task_id: str
    role_id: str
    start_s: float
    finish_s: float
    duration_s: float
    priority: int = 3
    deadline_s: Optional[int] = None
    deadline_missed: bool = False
    depends_on: list[str] = field(default_factory=list)


@dataclass
class CollaborationScheduleReport:
    spec_id: str
    ok: bool
    makespan_s: float
    max_duration_s: int
    benchmark_deadline_s: Optional[int] = None
    benchmark_deadline_missed: bool = False
    deadline_misses: int = 0
    role_busy_s: dict[str, float] = field(default_factory=dict)
    role_idle_s: dict[str, float] = field(default_factory=dict)
    task_schedule: list[CollaborationScheduleItem] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class CollaborationScheduleExecutionTaskComparison:
    task_id: str
    role_id: str
    status: str
    expected_start_s: float
    expected_finish_s: float
    expected_duration_s: float
    actual_start_s: Optional[float] = None
    actual_finish_s: Optional[float] = None
    actual_duration_s: Optional[float] = None
    start_delta_s: Optional[float] = None
    finish_delta_s: Optional[float] = None
    duration_delta_s: Optional[float] = None
    deadline_s: Optional[int] = None
    deadline_missed: bool = False


@dataclass
class CollaborationExecutionOverlapPair:
    task_a: str
    task_b: str
    role_a: str
    role_b: str
    overlap_s: float


@dataclass
class CollaborationScheduleExecutionComparison:
    spec_id: str
    execution_spec_id: str
    ok: bool
    schedule_makespan_s: float
    actual_elapsed_s: float
    elapsed_delta_s: float
    elapsed_ratio: float
    completed_tasks: int
    failed_tasks: int
    skipped_tasks: int
    schedule_deadline_misses: int
    execution_deadline_misses: int
    deadline_misses_delta: int
    actual_peak_parallel_tasks: int = 0
    actual_parallel_overlap_s: float = 0.0
    actual_task_seconds_s: float = 0.0
    actual_busy_window_s: float = 0.0
    actual_parallel_efficiency: float = 0.0
    overlapping_task_pairs: list[CollaborationExecutionOverlapPair] = field(default_factory=list)
    task_comparisons: list[CollaborationScheduleExecutionTaskComparison] = field(default_factory=list)
    missing_scheduled_tasks: list[str] = field(default_factory=list)
    unexpected_execution_tasks: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class CollaborationBenchmarkRunner:
    """Prepares and optionally executes an M7 collaboration spec."""

    def __init__(
        self,
        state_path: str = "workspace/multiagent/collab_benchmark_state.json",
        memory_policy: Optional[MemoryLifecyclePolicy] = None,
    ):
        self.state_path = state_path
        self.memory_policy = memory_policy or MemoryLifecyclePolicy()

    def prepare(self, spec: CollaborationBenchmarkSpec, reset: bool = True) -> CollaborationRunResult:
        report = CollaborationFeasibilityChecker().check(spec)
        return self._prepare_from_report(spec, report, reset=reset)

    def _prepare_from_report(
        self,
        spec: CollaborationBenchmarkSpec,
        report: FeasibilityReport,
        reset: bool = True,
    ) -> CollaborationRunResult:
        result = CollaborationRunResult(
            spec_id=spec.id,
            ok=report.ok,
            state_path=self.state_path,
            checks=report.checks,
        )
        if not report.ok:
            result.errors.append("feasibility checks failed")
            return result

        if reset and os.path.exists(self.state_path):
            os.remove(self.state_path)

        state = SharedState(self.state_path)
        leader_id = self._leader_role_id(spec)
        leader = LeaderAgent(leader_id, state)
        result.leader_id = leader_id

        for role in spec.roles:
            if role.id != leader_id:
                AgentWorker(role.id, state)
            state.update_agent_state(
                role.id,
                inventory=role.starting_inventory,
                status="idle",
                current_task=role.description,
            )

        state.update_shared({
            **spec.shared_state.initial,
            "_benchmark": {
                "id": spec.id,
                "name": spec.name,
                "phase": spec.phase,
                "max_duration_s": spec.max_duration_s,
                "success_criteria": spec.success_criteria,
                "dynamic_events": [asdict(event) for event in spec.dynamic_events],
            },
        })

        assignment_plan = spec.assignment_plan()
        for role_id, tasks in assignment_plan.items():
            for task in tasks:
                assigned = leader.assign_task(role_id, {
                    **task,
                    "benchmark_id": spec.id,
                    "source_task_id": task["id"],
                })
                if assigned:
                    result.assigned_tasks += 1
                    result.role_task_counts[role_id] = result.role_task_counts.get(role_id, 0) + 1
                else:
                    result.errors.append(f"could not assign task {task['id']} to {role_id}")

        result.ok = result.ok and not result.errors
        return result

    def prepare_from_path(self, spec_path: str, reset: bool = True) -> CollaborationRunResult:
        return self.prepare(CollaborationBenchmarkSpec.load_json(spec_path), reset=reset)

    def single_agent_baseline_spec(
        self,
        spec: CollaborationBenchmarkSpec,
        baseline_role_id: str = "single_agent",
    ) -> CollaborationBenchmarkSpec:
        """Return a baseline spec where one agent owns every original task."""
        baseline = CollaborationBenchmarkSpec.from_dict(asdict(spec))
        baseline.id = f"{spec.id}-SINGLE"
        baseline.name = f"{spec.name} single-agent baseline"
        baseline.description = f"Single-agent baseline transformed from {spec.id}: {spec.description}"

        capabilities = sorted({
            capability
            for role in spec.roles
            for capability in role.capabilities
        } | {
            capability
            for task in spec.tasks
            for capability in task.required_capabilities
        })
        inventory: dict = {}
        for role in spec.roles:
            for item, count in role.starting_inventory.items():
                inventory[item] = inventory.get(item, 0) + count
        baseline.roles = [
            CollaborationRole(
                id=baseline_role_id,
                description="Single agent baseline that performs every role sequentially.",
                capabilities=capabilities,
                required=True,
                starting_inventory=inventory,
            )
        ]
        for task in baseline.tasks:
            task.assigned_role = baseline_role_id
        return baseline

    def analyze_schedule(self, spec: CollaborationBenchmarkSpec) -> CollaborationScheduleReport:
        """Estimate task timing from dependencies, role resources, and duration hints."""
        errors: list[str] = []
        role_ids = [role.id for role in spec.roles]
        role_available_s: dict[str, float] = {role_id: 0.0 for role_id in role_ids}
        role_busy_s: dict[str, float] = {role_id: 0.0 for role_id in role_ids}
        task_ids = [task.id for task in spec.tasks]
        task_by_id = {task.id: task for task in spec.tasks}
        if len(task_ids) != len(task_by_id):
            errors.append("duplicate task ids prevent an unambiguous schedule")

        for task in spec.tasks:
            if task.assigned_role not in role_available_s:
                errors.append(f"task {task.id} uses unknown role {task.assigned_role}")
                role_available_s.setdefault(task.assigned_role, 0.0)
                role_busy_s.setdefault(task.assigned_role, 0.0)
            missing = [dep_id for dep_id in task.depends_on if dep_id not in task_by_id]
            if missing:
                errors.append(f"task {task.id} has missing dependencies: {', '.join(missing)}")

        unscheduled = set(task_ids)
        finish_by_task: dict[str, float] = {}
        schedule: list[CollaborationScheduleItem] = []

        while unscheduled:
            ready = [
                task for task in spec.tasks
                if task.id in unscheduled
                and all(dep_id in finish_by_task for dep_id in task.depends_on)
            ]
            if not ready:
                break

            ready.sort(key=lambda task: (
                task.priority,
                task.deadline_s if task.deadline_s is not None else spec.max_duration_s,
                self._dependency_finish_s(task.depends_on, finish_by_task),
                task.id,
            ))
            task = ready[0]
            role_id = task.assigned_role
            duration_s = max(0.0, float(task.estimated_duration_s))
            start_s = max(
                role_available_s.get(role_id, 0.0),
                self._dependency_finish_s(task.depends_on, finish_by_task),
            )
            finish_s = start_s + duration_s
            role_available_s[role_id] = finish_s
            role_busy_s[role_id] = role_busy_s.get(role_id, 0.0) + duration_s
            finish_by_task[task.id] = finish_s
            unscheduled.remove(task.id)
            schedule.append(CollaborationScheduleItem(
                task_id=task.id,
                role_id=role_id,
                start_s=round(start_s, 3),
                finish_s=round(finish_s, 3),
                duration_s=round(duration_s, 3),
                priority=task.priority,
                deadline_s=task.deadline_s,
                deadline_missed=task.deadline_s is not None and finish_s > task.deadline_s,
                depends_on=list(task.depends_on),
            ))

        for task_id in sorted(unscheduled):
            task = task_by_id.get(task_id)
            if not task:
                continue
            blocked = [dep_id for dep_id in task.depends_on if dep_id in task_by_id and dep_id not in finish_by_task]
            if blocked:
                errors.append(f"task {task.id} has cyclic or unscheduled dependencies: {', '.join(blocked)}")

        makespan_s = max(finish_by_task.values(), default=0.0)
        role_idle_s = {
            role_id: round(max(0.0, makespan_s - busy_s), 3)
            for role_id, busy_s in sorted(role_busy_s.items())
        }
        role_busy_s = {
            role_id: round(busy_s, 3)
            for role_id, busy_s in sorted(role_busy_s.items())
        }
        deadline_misses = sum(1 for item in schedule if item.deadline_missed)
        benchmark_deadline = spec.success_criteria.get("deadline_s", spec.max_duration_s)
        benchmark_deadline_missed = benchmark_deadline is not None and makespan_s > benchmark_deadline

        return CollaborationScheduleReport(
            spec_id=spec.id,
            ok=not errors and len(schedule) == len(spec.tasks) and deadline_misses == 0 and not benchmark_deadline_missed,
            makespan_s=round(makespan_s, 3),
            max_duration_s=spec.max_duration_s,
            benchmark_deadline_s=benchmark_deadline,
            benchmark_deadline_missed=benchmark_deadline_missed,
            deadline_misses=deadline_misses,
            role_busy_s=role_busy_s,
            role_idle_s=role_idle_s,
            task_schedule=schedule,
            errors=errors,
        )

    def analyze_single_agent_baseline_schedule(
        self,
        spec: CollaborationBenchmarkSpec,
        baseline_role_id: str = "single_agent",
    ) -> CollaborationScheduleReport:
        baseline = self.single_agent_baseline_spec(spec, baseline_role_id=baseline_role_id)
        return self.analyze_schedule(baseline)

    def prepare_single_agent_baseline(
        self,
        spec: CollaborationBenchmarkSpec,
        baseline_role_id: str = "single_agent",
        reset: bool = True,
    ) -> CollaborationRunResult:
        baseline = self.single_agent_baseline_spec(spec, baseline_role_id=baseline_role_id)
        report = FeasibilityReport(ok=True, checks=[
            FeasibilityCheck(
                "single_agent_baseline",
                "pass",
                f"{len(baseline.tasks)} tasks assigned to {baseline_role_id}",
            )
        ])
        return self._prepare_from_report(baseline, report, reset=reset)

    def run_single_agent_baseline(
        self,
        spec: CollaborationBenchmarkSpec,
        executor: Optional[TaskExecutor] = None,
        baseline_role_id: str = "single_agent",
        reset: bool = True,
        max_steps: Optional[int] = None,
    ) -> CollaborationExecutionReport:
        baseline = self.single_agent_baseline_spec(spec, baseline_role_id=baseline_role_id)
        prepared = self.prepare_single_agent_baseline(spec, baseline_role_id=baseline_role_id, reset=reset)
        if not prepared.ok:
            return CollaborationExecutionReport(
                spec_id=baseline.id,
                ok=False,
                state_path=self.state_path,
                errors=prepared.errors or ["baseline prepare failed"],
            )
        return self.execute_prepared(baseline, executor=executor, max_steps=max_steps)

    def execute(
        self,
        spec: CollaborationBenchmarkSpec,
        executor: Optional[TaskExecutor] = None,
        reset: bool = True,
        max_steps: Optional[int] = None,
    ) -> CollaborationExecutionReport:
        """Prepare the benchmark, then execute runnable assigned tasks synchronously.

        The executor receives `(task, agent_state, shared_state)` and returns a dict.
        Returning `{"success": false, "error": "..."}` fails the task. Returning
        `{"shared_state": {...}}` applies shared-state updates before completion.
        """
        prepared = self.prepare(spec, reset=reset)
        if not prepared.ok:
            return CollaborationExecutionReport(
                spec_id=spec.id,
                ok=False,
                state_path=self.state_path,
                errors=prepared.errors or ["prepare failed"],
            )
        return self.execute_prepared(spec, executor=executor, max_steps=max_steps)

    def execute_from_path(
        self,
        spec_path: str,
        executor: Optional[TaskExecutor] = None,
        reset: bool = True,
        max_steps: Optional[int] = None,
    ) -> CollaborationExecutionReport:
        return self.execute(
            CollaborationBenchmarkSpec.load_json(spec_path),
            executor=executor,
            reset=reset,
            max_steps=max_steps,
        )

    def execute_prepared(
        self,
        spec: CollaborationBenchmarkSpec,
        executor: Optional[TaskExecutor] = None,
        max_steps: Optional[int] = None,
    ) -> CollaborationExecutionReport:
        state = SharedState(self.state_path)
        task_executor = executor or self.simulated_task_executor
        start_time = time.time()
        max_steps = max_steps or max(1, len(spec.tasks) * 3)
        report = CollaborationExecutionReport(spec_id=spec.id, ok=True, state_path=self.state_path)

        for _ in range(max_steps):
            self._apply_dynamic_events(spec, state, time.time() - start_time)
            runnable = self._runnable_tasks(spec, state)
            if not runnable:
                break
            batch = self._role_parallel_batch(runnable)
            if not batch:
                break
            report.dispatch_batches += 1
            report.max_parallel_tasks = max(report.max_parallel_tasks, len(batch))
            report.task_results.extend(self._execute_task_batch(batch, state, task_executor, start_time))

        raw = state._read_state()
        tasks = raw.get("tasks", {})
        report.total_elapsed_s = round(time.time() - start_time, 3)
        report.completed_tasks = sum(1 for task in tasks.values() if task.get("status") == "completed")
        report.failed_tasks = sum(1 for task in tasks.values() if task.get("status") == "failed")
        report.skipped_tasks = sum(1 for task in tasks.values() if task.get("status") == "assigned")
        report.deadline_misses = sum(1 for item in report.task_results if item.deadline_missed)
        report.shared_state = raw.get("shared", {})
        report.shared_memory_governance = report.shared_state.get("_shared_memory_governance", {})
        report.success_keys_satisfied = self._success_keys_satisfied(spec, report.shared_state)
        report.errors.extend(self._execution_errors(spec, raw, time.time() - start_time))
        report.ok = (
            not report.errors
            and report.failed_tasks == 0
            and report.skipped_tasks == 0
            and report.success_keys_satisfied
        )
        return report

    def simulated_task_executor(self, task: dict, agent_state: dict, shared_state: dict) -> dict:
        """State-only executor used by tests and CLI smoke runs before live bots attach."""
        updates = dict(task.get("success_criteria", {}).get("shared_state", {}))
        for key in task.get("shared_state_updates", []):
            updates.setdefault(key, True)
        return {
            "success": True,
            "mode": "simulated",
            "agent_id": agent_state.get("id", ""),
            "shared_state": updates,
        }

    def print_result(self, result: CollaborationRunResult):
        print("\nCollaboration Benchmark Dry Run")
        print(f"  spec: {result.spec_id}")
        print(f"  ready: {'yes' if result.ok else 'no'}")
        print(f"  state: {result.state_path}")
        print(f"  leader: {result.leader_id or '-'}")
        print(f"  assigned tasks: {result.assigned_tasks}")
        for role_id, count in sorted(result.role_task_counts.items()):
            print(f"    - {role_id}: {count}")
        print("\nFeasibility")
        for check in result.checks:
            icon = "+" if check.status == "pass" else "!" if check.status == "warn" else "x"
            print(f"  [{icon}] {check.name}: {check.status} - {check.detail}")
            if check.remedy:
                print(f"      remedy: {check.remedy}")
        for error in result.errors:
            print(f"  error: {error}")

    def print_execution_report(self, report: CollaborationExecutionReport):
        print("\nCollaboration Benchmark Execution")
        print(f"  spec: {report.spec_id}")
        print(f"  ok: {'yes' if report.ok else 'no'}")
        print(f"  state: {report.state_path}")
        print(f"  dispatch mode: {report.dispatch_mode}")
        print(f"  dispatch batches: {report.dispatch_batches}")
        print(f"  max parallel tasks: {report.max_parallel_tasks}")
        print(f"  completed tasks: {report.completed_tasks}")
        print(f"  failed tasks: {report.failed_tasks}")
        print(f"  skipped tasks: {report.skipped_tasks}")
        print(f"  deadline misses: {report.deadline_misses}")
        print(f"  success keys satisfied: {'yes' if report.success_keys_satisfied else 'no'}")
        if report.shared_memory_governance:
            print(f"  shared memory candidates: {report.shared_memory_governance.get('candidate_count', 0)}")
            print(f"  false-promotion reviews: {report.shared_memory_governance.get('false_promotion_review_count', 0)}")
            print(f"  state revisions: {report.shared_memory_governance.get('state_revision_count', 0)}")
        for item in report.task_results:
            suffix = " deadline_missed" if item.deadline_missed else ""
            print(f"    - {item.source_task_id} -> {item.status}{suffix}")
            if item.error:
                print(f"      error: {item.error}")
        for error in report.errors:
            print(f"  error: {error}")

    def print_schedule_report(self, report: CollaborationScheduleReport, title: str = "Collaboration Schedule Analysis"):
        print(f"\n{title}")
        print(f"  spec: {report.spec_id}")
        print(f"  ok: {'yes' if report.ok else 'no'}")
        print(f"  makespan: {report.makespan_s}s")
        print(f"  deadline misses: {report.deadline_misses}")
        if report.benchmark_deadline_s is not None:
            status = "missed" if report.benchmark_deadline_missed else "met"
            print(f"  benchmark deadline: {report.benchmark_deadline_s}s ({status})")
        for item in report.task_schedule:
            suffix = " deadline_missed" if item.deadline_missed else ""
            print(f"    - {item.task_id} [{item.role_id}] {item.start_s}s -> {item.finish_s}s{suffix}")
        for error in report.errors:
            print(f"  error: {error}")

    def print_schedule_execution_comparison(
        self,
        comparison: CollaborationScheduleExecutionComparison,
        title: str = "Schedule vs Execution",
    ):
        print(f"\n{title}")
        print(f"  spec: {comparison.execution_spec_id}")
        print(f"  ok: {'yes' if comparison.ok else 'no'}")
        print(f"  expected makespan: {comparison.schedule_makespan_s}s")
        print(f"  actual elapsed: {comparison.actual_elapsed_s}s")
        print(f"  elapsed delta: {comparison.elapsed_delta_s}s")
        print(f"  elapsed ratio: {comparison.elapsed_ratio}x")
        print(f"  actual peak parallel tasks: {comparison.actual_peak_parallel_tasks}")
        print(f"  actual parallel overlap: {comparison.actual_parallel_overlap_s}s")
        print(f"  actual parallel efficiency: {comparison.actual_parallel_efficiency}")
        for task in comparison.task_comparisons:
            actual = "-" if task.actual_finish_s is None else f"{task.actual_start_s}s -> {task.actual_finish_s}s"
            print(f"    - {task.task_id} [{task.status}] expected {task.expected_start_s}s -> {task.expected_finish_s}s, actual {actual}")
        if comparison.missing_scheduled_tasks:
            print(f"  missing scheduled tasks: {', '.join(comparison.missing_scheduled_tasks)}")
        if comparison.unexpected_execution_tasks:
            print(f"  unexpected execution tasks: {', '.join(comparison.unexpected_execution_tasks)}")
        for error in comparison.errors:
            print(f"  error: {error}")

    def run_result_to_dict(self, result: CollaborationRunResult) -> dict:
        return {
            "type": "collaboration_dry_run",
            "spec_id": result.spec_id,
            "ok": result.ok,
            "state_path": result.state_path,
            "leader_id": result.leader_id,
            "assigned_tasks": result.assigned_tasks,
            "role_task_counts": result.role_task_counts,
            "checks": [asdict(check) for check in result.checks],
            "errors": result.errors,
        }

    def execution_report_to_dict(self, report: CollaborationExecutionReport) -> dict:
        return {
            "type": "collaboration_execution",
            "spec_id": report.spec_id,
            "ok": report.ok,
            "state_path": report.state_path,
            "dispatch_mode": report.dispatch_mode,
            "dispatch_batches": report.dispatch_batches,
            "max_parallel_tasks": report.max_parallel_tasks,
            "completed_tasks": report.completed_tasks,
            "failed_tasks": report.failed_tasks,
            "skipped_tasks": report.skipped_tasks,
            "deadline_misses": report.deadline_misses,
            "success_keys_satisfied": report.success_keys_satisfied,
            "total_elapsed_s": report.total_elapsed_s,
            "shared_state": report.shared_state,
            "shared_memory_governance": report.shared_memory_governance,
            "task_results": [asdict(item) for item in report.task_results],
            "errors": report.errors,
        }

    def schedule_report_to_dict(self, report: CollaborationScheduleReport) -> dict:
        return {
            "type": "collaboration_schedule_analysis",
            "spec_id": report.spec_id,
            "ok": report.ok,
            "makespan_s": report.makespan_s,
            "max_duration_s": report.max_duration_s,
            "benchmark_deadline_s": report.benchmark_deadline_s,
            "benchmark_deadline_missed": report.benchmark_deadline_missed,
            "deadline_misses": report.deadline_misses,
            "role_busy_s": report.role_busy_s,
            "role_idle_s": report.role_idle_s,
            "role_utilization": {
                role_id: round(busy_s / report.makespan_s, 3) if report.makespan_s else 0.0
                for role_id, busy_s in report.role_busy_s.items()
            },
            "task_schedule": [asdict(item) for item in report.task_schedule],
            "errors": report.errors,
        }

    def schedule_execution_comparison_to_dict(
        self,
        comparison: CollaborationScheduleExecutionComparison,
    ) -> dict:
        return {
            "type": "collaboration_schedule_vs_execution",
            "spec_id": comparison.spec_id,
            "execution_spec_id": comparison.execution_spec_id,
            "ok": comparison.ok,
            "schedule_makespan_s": comparison.schedule_makespan_s,
            "actual_elapsed_s": comparison.actual_elapsed_s,
            "elapsed_delta_s": comparison.elapsed_delta_s,
            "elapsed_ratio": comparison.elapsed_ratio,
            "completed_tasks": comparison.completed_tasks,
            "failed_tasks": comparison.failed_tasks,
            "skipped_tasks": comparison.skipped_tasks,
            "schedule_deadline_misses": comparison.schedule_deadline_misses,
            "execution_deadline_misses": comparison.execution_deadline_misses,
            "deadline_misses_delta": comparison.deadline_misses_delta,
            "actual_peak_parallel_tasks": comparison.actual_peak_parallel_tasks,
            "actual_parallel_overlap_s": comparison.actual_parallel_overlap_s,
            "actual_task_seconds_s": comparison.actual_task_seconds_s,
            "actual_busy_window_s": comparison.actual_busy_window_s,
            "actual_parallel_efficiency": comparison.actual_parallel_efficiency,
            "overlapping_task_pairs": [asdict(item) for item in comparison.overlapping_task_pairs],
            "task_comparisons": [asdict(item) for item in comparison.task_comparisons],
            "missing_scheduled_tasks": comparison.missing_scheduled_tasks,
            "unexpected_execution_tasks": comparison.unexpected_execution_tasks,
            "errors": comparison.errors,
        }

    def save_json_report(self, payload: dict, output_path: str):
        if not output_path:
            return
        directory = os.path.dirname(output_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        print(f"\nReport saved to {output_path}")

    def compare_execution_reports(
        self,
        collaboration: CollaborationExecutionReport,
        baseline: CollaborationExecutionReport,
    ) -> dict:
        return {
            "type": "collaboration_vs_single_agent_baseline",
            "collaboration_spec_id": collaboration.spec_id,
            "baseline_spec_id": baseline.spec_id,
            "collaboration_ok": collaboration.ok,
            "baseline_ok": baseline.ok,
            "ok_delta": int(collaboration.ok) - int(baseline.ok),
            "completed_tasks_delta": collaboration.completed_tasks - baseline.completed_tasks,
            "failed_tasks_delta": collaboration.failed_tasks - baseline.failed_tasks,
            "skipped_tasks_delta": collaboration.skipped_tasks - baseline.skipped_tasks,
            "deadline_misses_delta": collaboration.deadline_misses - baseline.deadline_misses,
            "total_elapsed_s_delta": round(collaboration.total_elapsed_s - baseline.total_elapsed_s, 3),
        }

    def compare_mixed_policy_execution_reports(
        self,
        baseline: CollaborationExecutionReport,
        patched: CollaborationExecutionReport,
    ) -> dict:
        return {
            "type": "collaboration_mixed_policy_ablation_comparison",
            "baseline_spec_id": baseline.spec_id,
            "patched_spec_id": patched.spec_id,
            "baseline_ok": baseline.ok,
            "patched_ok": patched.ok,
            "ok_delta": int(patched.ok) - int(baseline.ok),
            "completed_tasks_delta": patched.completed_tasks - baseline.completed_tasks,
            "failed_tasks_delta": patched.failed_tasks - baseline.failed_tasks,
            "skipped_tasks_delta": patched.skipped_tasks - baseline.skipped_tasks,
            "deadline_misses_delta": patched.deadline_misses - baseline.deadline_misses,
            "total_elapsed_s_delta": round(patched.total_elapsed_s - baseline.total_elapsed_s, 3),
            "shared_state_changed": baseline.shared_state != patched.shared_state,
            "task_status_changed": [
                {
                    "task_id": base.source_task_id,
                    "baseline_status": base.status,
                    "patched_status": other.status,
                }
                for base, other in self._paired_task_results(baseline, patched)
                if base.status != other.status
            ],
        }

    def compare_schedule_reports(
        self,
        collaboration: CollaborationScheduleReport,
        baseline: CollaborationScheduleReport,
    ) -> dict:
        speedup = round(baseline.makespan_s / collaboration.makespan_s, 3) if collaboration.makespan_s else 0.0
        return {
            "type": "collaboration_schedule_vs_single_agent_baseline",
            "collaboration_spec_id": collaboration.spec_id,
            "baseline_spec_id": baseline.spec_id,
            "collaboration_ok": collaboration.ok,
            "baseline_ok": baseline.ok,
            "makespan_s_delta": round(collaboration.makespan_s - baseline.makespan_s, 3),
            "deadline_misses_delta": collaboration.deadline_misses - baseline.deadline_misses,
            "benchmark_deadline_missed_delta": int(collaboration.benchmark_deadline_missed) - int(baseline.benchmark_deadline_missed),
            "speedup": speedup,
            "collaboration_role_busy_s": collaboration.role_busy_s,
            "baseline_role_busy_s": baseline.role_busy_s,
        }

    def _paired_task_results(
        self,
        baseline: CollaborationExecutionReport,
        patched: CollaborationExecutionReport,
    ) -> list[tuple[CollaborationTaskExecution, CollaborationTaskExecution]]:
        patched_by_task = {
            item.source_task_id: item
            for item in patched.task_results
            if item.source_task_id
        }
        return [
            (item, patched_by_task[item.source_task_id])
            for item in baseline.task_results
            if item.source_task_id in patched_by_task
        ]

    def compare_schedule_to_execution(
        self,
        schedule: CollaborationScheduleReport,
        execution: CollaborationExecutionReport,
    ) -> CollaborationScheduleExecutionComparison:
        expected_by_task = {item.task_id: item for item in schedule.task_schedule}
        actual_by_task = {
            item.source_task_id: item
            for item in execution.task_results
            if item.source_task_id
        }
        task_comparisons: list[CollaborationScheduleExecutionTaskComparison] = []

        for task_id in sorted(expected_by_task, key=lambda item: expected_by_task[item].start_s):
            expected = expected_by_task[task_id]
            actual = actual_by_task.get(task_id)
            actual_start = None
            actual_finish = None
            actual_duration = None
            start_delta = None
            finish_delta = None
            duration_delta = None
            status = "not_started"
            deadline_missed = expected.deadline_missed
            if actual:
                status = actual.status
                actual_start = actual.started_at_s if actual.started_at_s else actual.elapsed_s
                actual_finish = actual.finished_at_s if actual.finished_at_s else actual_start + actual.duration_s
                actual_duration = actual.duration_s
                start_delta = round(actual_start - expected.start_s, 3)
                finish_delta = round(actual_finish - expected.finish_s, 3)
                duration_delta = round(actual_duration - expected.duration_s, 3)
                deadline_missed = actual.deadline_missed
            task_comparisons.append(CollaborationScheduleExecutionTaskComparison(
                task_id=task_id,
                role_id=expected.role_id,
                status=status,
                expected_start_s=expected.start_s,
                expected_finish_s=expected.finish_s,
                expected_duration_s=expected.duration_s,
                actual_start_s=round(actual_start, 3) if actual_start is not None else None,
                actual_finish_s=round(actual_finish, 3) if actual_finish is not None else None,
                actual_duration_s=round(actual_duration, 3) if actual_duration is not None else None,
                start_delta_s=start_delta,
                finish_delta_s=finish_delta,
                duration_delta_s=duration_delta,
                deadline_s=expected.deadline_s,
                deadline_missed=deadline_missed,
            ))

        missing = sorted(set(expected_by_task) - set(actual_by_task))
        unexpected = sorted(set(actual_by_task) - set(expected_by_task))
        elapsed_delta = round(execution.total_elapsed_s - schedule.makespan_s, 3)
        elapsed_ratio = round(execution.total_elapsed_s / schedule.makespan_s, 3) if schedule.makespan_s else 0.0
        errors = list(schedule.errors) + list(execution.errors)
        if missing:
            errors.append(f"scheduled tasks not executed: {', '.join(missing)}")
        if unexpected:
            errors.append(f"execution tasks not present in schedule: {', '.join(unexpected)}")
        overlap_metrics = self._execution_overlap_metrics(task_comparisons)

        return CollaborationScheduleExecutionComparison(
            spec_id=schedule.spec_id,
            execution_spec_id=execution.spec_id,
            ok=not errors,
            schedule_makespan_s=schedule.makespan_s,
            actual_elapsed_s=execution.total_elapsed_s,
            elapsed_delta_s=elapsed_delta,
            elapsed_ratio=elapsed_ratio,
            completed_tasks=execution.completed_tasks,
            failed_tasks=execution.failed_tasks,
            skipped_tasks=execution.skipped_tasks,
            schedule_deadline_misses=schedule.deadline_misses,
            execution_deadline_misses=execution.deadline_misses,
            deadline_misses_delta=execution.deadline_misses - schedule.deadline_misses,
            actual_peak_parallel_tasks=overlap_metrics["peak_parallel_tasks"],
            actual_parallel_overlap_s=overlap_metrics["parallel_overlap_s"],
            actual_task_seconds_s=overlap_metrics["task_seconds_s"],
            actual_busy_window_s=overlap_metrics["busy_window_s"],
            actual_parallel_efficiency=overlap_metrics["parallel_efficiency"],
            overlapping_task_pairs=overlap_metrics["overlapping_pairs"],
            task_comparisons=task_comparisons,
            missing_scheduled_tasks=missing,
            unexpected_execution_tasks=unexpected,
            errors=errors,
        )

    def _execution_overlap_metrics(
        self,
        task_comparisons: list[CollaborationScheduleExecutionTaskComparison],
    ) -> dict:
        intervals = [
            item for item in task_comparisons
            if item.actual_start_s is not None
            and item.actual_finish_s is not None
            and item.actual_finish_s > item.actual_start_s
        ]
        if not intervals:
            return {
                "peak_parallel_tasks": 0,
                "parallel_overlap_s": 0.0,
                "task_seconds_s": 0.0,
                "busy_window_s": 0.0,
                "parallel_efficiency": 0.0,
                "overlapping_pairs": [],
            }

        task_seconds = round(sum((item.actual_duration_s or 0.0) for item in intervals), 3)
        busy_start = min(item.actual_start_s for item in intervals)
        busy_finish = max(item.actual_finish_s for item in intervals)
        busy_window = round(max(0.0, busy_finish - busy_start), 3)

        events_by_time: dict[float, int] = {}
        for item in intervals:
            events_by_time[item.actual_start_s] = events_by_time.get(item.actual_start_s, 0) + 1
            events_by_time[item.actual_finish_s] = events_by_time.get(item.actual_finish_s, 0) - 1

        active = 0
        peak = 0
        overlap = 0.0
        previous_time: Optional[float] = None
        for event_time in sorted(events_by_time):
            if previous_time is not None and event_time > previous_time and active > 1:
                overlap += event_time - previous_time
            active += events_by_time[event_time]
            peak = max(peak, active)
            previous_time = event_time

        overlapping_pairs: list[CollaborationExecutionOverlapPair] = []
        for index, left in enumerate(intervals):
            for right in intervals[index + 1:]:
                overlap_start = max(left.actual_start_s, right.actual_start_s)
                overlap_finish = min(left.actual_finish_s, right.actual_finish_s)
                overlap_s = round(max(0.0, overlap_finish - overlap_start), 3)
                if overlap_s <= 0:
                    continue
                overlapping_pairs.append(CollaborationExecutionOverlapPair(
                    task_a=left.task_id,
                    task_b=right.task_id,
                    role_a=left.role_id,
                    role_b=right.role_id,
                    overlap_s=overlap_s,
                ))

        capacity_seconds = busy_window * peak
        efficiency = round(task_seconds / capacity_seconds, 3) if capacity_seconds else 0.0
        return {
            "peak_parallel_tasks": peak,
            "parallel_overlap_s": round(overlap, 3),
            "task_seconds_s": task_seconds,
            "busy_window_s": busy_window,
            "parallel_efficiency": efficiency,
            "overlapping_pairs": overlapping_pairs,
        }

    def _leader_role_id(self, spec: CollaborationBenchmarkSpec) -> str:
        for role in spec.roles:
            if "leader" in role.id or "plan" in role.capabilities or "verify" in role.capabilities:
                return role.id
        return spec.roles[0].id

    def _dependency_finish_s(self, dependencies: list[str], finish_by_task: dict[str, float]) -> float:
        if not dependencies:
            return 0.0
        return max((finish_by_task.get(dep_id, 0.0) for dep_id in dependencies), default=0.0)

    def _runnable_tasks(self, spec: CollaborationBenchmarkSpec, state: SharedState) -> list[dict]:
        raw = state._read_state()
        tasks = list(raw.get("tasks", {}).values())
        shared = raw.get("shared", {})
        runnable = [
            task for task in tasks
            if task.get("status") == "assigned"
            and self._dependencies_complete(task, tasks)
            and self._preconditions_met(task, shared)
        ]
        return sorted(runnable, key=lambda item: (
            item.get("priority", 3),
            item.get("deadline_s") if item.get("deadline_s") is not None else spec.max_duration_s,
            item.get("created_at", 0),
        ))

    def _role_parallel_batch(self, runnable: list[dict]) -> list[dict]:
        """Choose at most one ready task per role for a parallel dispatch wave."""
        batch = []
        busy_roles = set()
        for task in runnable:
            role_id = task.get("assigned_to", "")
            if role_id in busy_roles:
                continue
            busy_roles.add(role_id)
            batch.append(task)
        return batch

    def _execute_task_batch(
        self,
        tasks: list[dict],
        state: SharedState,
        executor: TaskExecutor,
        benchmark_start_time: float,
    ) -> list[CollaborationTaskExecution]:
        prepared = []
        executions: list[CollaborationTaskExecution] = []
        for task in tasks:
            started_at_s = round(time.time() - benchmark_start_time, 3)
            task_id = task.get("task_id", "")
            assigned_to = task.get("assigned_to", "")
            if not state.start_task(task_id):
                executions.append(self._task_start_failed_execution(task, started_at_s))
                continue
            state.update_agent_state(assigned_to, status="working", current_task=task.get("title", ""))
            prepared.append((
                dict(task),
                dict(state.get_agent(assigned_to)),
                dict(state.get_shared()),
                started_at_s,
            ))

        if not prepared:
            return executions

        with ThreadPoolExecutor(max_workers=len(prepared)) as pool:
            futures = [
                pool.submit(
                    self._invoke_task_executor,
                    executor,
                    task,
                    agent_state,
                    shared_state,
                    started_at_s,
                    benchmark_start_time,
                )
                for task, agent_state, shared_state, started_at_s in prepared
            ]
            for future in as_completed(futures):
                executions.append(self._apply_task_execution_result(state, future.result()))
        return sorted(executions, key=lambda item: (item.finished_at_s, item.started_at_s, item.source_task_id))

    def _invoke_task_executor(
        self,
        executor: TaskExecutor,
        task: dict,
        agent_state: dict,
        shared_state: dict,
        started_at_s: float,
        benchmark_start_time: float,
    ) -> dict:
        try:
            result = executor(task, agent_state, shared_state) or {}
            success = bool(result.get("success", True))
            error = "" if success else result.get("error", "executor reported failure")
            exception = False
        except Exception as exc:
            result = {}
            success = False
            error = str(exc)
            exception = True
        finished_at_s = round(time.time() - benchmark_start_time, 3)
        return {
            "task": task,
            "result": result,
            "success": success,
            "error": error,
            "exception": exception,
            "started_at_s": started_at_s,
            "finished_at_s": finished_at_s,
            "duration_s": round(max(0.0, finished_at_s - started_at_s), 3),
        }

    def _apply_task_execution_result(self, state: SharedState, payload: dict) -> CollaborationTaskExecution:
        task = payload["task"]
        task_id = task.get("task_id", "")
        assigned_to = task.get("assigned_to", "")
        success = bool(payload.get("success"))
        result = payload.get("result", {})
        error = payload.get("error", "")
        raw_updates = dict(result.get("shared_state", {})) if isinstance(result, dict) else {}
        updates = dict(raw_updates)
        shared_update_provenance = {}
        shared_memory_decisions = {}
        if success:
            updates = self._normalize_shared_updates(task, updates)
        if updates:
            current_shared = state.get_shared()
            shared_update_provenance = self._shared_update_provenance(
                task,
                result if isinstance(result, dict) else {},
                updates,
                raw_updates,
                current_shared,
            )
            shared_memory_decisions = self._shared_memory_decisions(updates, shared_update_provenance)
            shared_metadata = self._shared_memory_metadata_updates(
                current_shared,
                updates,
                shared_update_provenance,
                shared_memory_decisions,
            )
            state.update_shared({**updates, **shared_metadata})
        if success:
            state.complete_task(task_id, result)
            status = "completed"
            agent_status = "idle"
        else:
            state.fail_task(task_id, error or "executor reported failure")
            status = "failed"
            agent_status = "error" if payload.get("exception") else "idle"
        state.update_agent_state(assigned_to, status=agent_status, current_task="")
        deadline = task.get("deadline_s")
        finished_at_s = payload.get("finished_at_s", payload.get("started_at_s", 0.0))
        return CollaborationTaskExecution(
            task_id=task_id,
            source_task_id=task.get("source_task_id", task.get("id", "")),
            assigned_to=assigned_to,
            status=status,
            elapsed_s=payload.get("started_at_s", 0.0),
            started_at_s=payload.get("started_at_s", 0.0),
            finished_at_s=finished_at_s,
            duration_s=payload.get("duration_s", 0.0),
            deadline_missed=deadline is not None and finished_at_s > deadline,
            shared_updates=updates,
            shared_update_provenance=shared_update_provenance,
            shared_memory_decisions=shared_memory_decisions,
            result=result,
            error="" if success else error,
        )

    def _task_start_failed_execution(self, task: dict, started_at_s: float) -> CollaborationTaskExecution:
        deadline = task.get("deadline_s")
        return CollaborationTaskExecution(
            task_id=task.get("task_id", ""),
            source_task_id=task.get("source_task_id", task.get("id", "")),
            assigned_to=task.get("assigned_to", ""),
            status="failed",
            elapsed_s=started_at_s,
            started_at_s=started_at_s,
            finished_at_s=started_at_s,
            duration_s=0.0,
            deadline_missed=deadline is not None and started_at_s > deadline,
            error="could not start assigned task",
        )

    def _execute_one_task(
        self,
        task: dict,
        state: SharedState,
        executor: TaskExecutor,
        elapsed_s: float,
    ) -> CollaborationTaskExecution:
        benchmark_start_time = time.time() - elapsed_s
        executions = self._execute_task_batch([task], state, executor, benchmark_start_time)
        if executions:
            return executions[0]
        return self._task_start_failed_execution(task, round(elapsed_s, 3))

    def _normalize_shared_updates(self, task: dict, updates: dict) -> dict:
        normalized = dict(updates)
        criteria_updates = task.get("success_criteria", {}).get("shared_state", {})
        for key in task.get("shared_state_updates", []):
            normalized.setdefault(key, criteria_updates.get(key, True))
        return normalized

    def _shared_update_provenance(
        self,
        task: dict,
        result: dict,
        updates: dict,
        raw_updates: dict,
        shared_state: dict,
    ) -> dict:
        provenance_by_key = {}
        task_provenance = task.get("shared_state_provenance", {}) if isinstance(task, dict) else {}
        result_provenance = result.get("shared_state_provenance", {}) if isinstance(result, dict) else {}
        criteria_updates = task.get("success_criteria", {}).get("shared_state", {})
        declared_updates = set(task.get("shared_state_updates", []))

        for key, value in updates.items():
            if str(key).startswith("_"):
                continue
            declared = task_provenance.get(key, {}) if isinstance(task_provenance, dict) else {}
            provided = result_provenance.get(key, {}) if isinstance(result_provenance, dict) else {}
            dependency = (
                provided.get("dependency")
                or provided.get("dependency_type")
                or provided.get("evidence_dependency")
                or declared.get("dependency")
                or declared.get("dependency_type")
                or declared.get("evidence_dependency")
                or self._default_shared_dependency(key, raw_updates, criteria_updates, declared_updates)
            )
            validity = (
                provided.get("validity")
                or provided.get("evidence_status")
                or declared.get("validity")
                or declared.get("evidence_status")
                or "current"
            )
            confidence = provided.get("confidence", declared.get("confidence", 0.85))
            entry = {
                "key": key,
                "value": value,
                "source_task_id": task.get("source_task_id", task.get("id", "")),
                "task_id": task.get("task_id", ""),
                "assigned_to": task.get("assigned_to", task.get("assigned_role", "")),
                "dependency": str(dependency or "task_result"),
                "validity": str(validity or "current"),
                "confidence": confidence,
                "scope": str(provided.get("scope") or declared.get("scope") or "benchmark_shared_state"),
                "depends_on": list(task.get("depends_on", [])),
                "evidence": {
                    "task_title": task.get("title", ""),
                    "declared_shared_state_update": key in declared_updates,
                    "matches_success_criteria": key in criteria_updates,
                    "executor_reported_update": key in raw_updates,
                },
            }
            if provided.get("note") or declared.get("note"):
                entry["note"] = str(provided.get("note") or declared.get("note"))
            self._annotate_shared_supersession(entry, shared_state)
            provenance_by_key[key] = entry
        return provenance_by_key

    def _annotate_shared_supersession(self, entry: dict, shared_state: dict):
        previous = self._latest_shared_memory_entry(entry.get("key", ""), shared_state)
        if not previous:
            return
        previous_value = previous.get("value")
        if previous_value == entry.get("value"):
            return

        entry["state_revision"] = True
        entry["previous_value"] = previous_value
        entry["previous_source_task_id"] = previous.get("source_task_id", "")
        entry["supersedes"] = {
            "previous_value": previous_value,
            "previous_source_task_id": previous.get("source_task_id", ""),
            "previous_assigned_to": previous.get("assigned_to", ""),
            "previous_validity": previous.get("validity", ""),
        }
        if str(entry.get("validity") or "").lower() in {"", "current"}:
            entry["validity"] = "implicit_conflict"
        if str(entry.get("dependency") or "").lower() in {"", "task_result", "direct_task_result"}:
            entry["dependency"] = "state_revision"

    def _latest_shared_memory_entry(self, key: str, shared_state: dict) -> dict:
        provenance = shared_state.get("_shared_memory_provenance", {}) if isinstance(shared_state, dict) else {}
        record = provenance.get(key, {}) if isinstance(provenance, dict) else {}
        latest = record.get("latest", {}) if isinstance(record, dict) else {}
        return latest if isinstance(latest, dict) else {}

    def _default_shared_dependency(
        self,
        key: str,
        raw_updates: dict,
        criteria_updates: dict,
        declared_updates: set,
    ) -> str:
        if key in criteria_updates:
            return "task_success_criteria"
        if key in raw_updates:
            return "direct_task_result"
        if key in declared_updates:
            return "declared_shared_state_update"
        return "task_result"

    def _shared_memory_decisions(self, updates: dict, provenance_by_key: dict) -> dict:
        decisions = {}
        for key, value in updates.items():
            if str(key).startswith("_"):
                continue
            provenance = provenance_by_key.get(key, {})
            confidence = self._safe_confidence(provenance.get("confidence"), default=0.85)
            content = {
                "key": key,
                "value": value,
                "source_task_id": provenance.get("source_task_id", ""),
                "assigned_to": provenance.get("assigned_to", ""),
                "dependency": provenance.get("dependency", "task_result"),
                "validity": provenance.get("validity", "current"),
                "scope": provenance.get("scope", "benchmark_shared_state"),
                "depends_on": provenance.get("depends_on", []),
                "state_revision": provenance.get("state_revision", False),
                "previous_value": provenance.get("previous_value"),
                "supersedes": provenance.get("supersedes", {}),
            }
            decisions[key] = self.memory_policy.decide_write(
                "shared",
                "fact",
                "write_shared_state",
                content,
                source="collaboration_shared_state",
                confidence=confidence,
            ).as_dict()
        return decisions

    def _shared_memory_metadata_updates(
        self,
        shared_state: dict,
        updates: dict,
        provenance_by_key: dict,
        decisions_by_key: dict,
    ) -> dict:
        provenance_log = dict(shared_state.get("_shared_memory_provenance", {}))
        for key, provenance in provenance_by_key.items():
            entry = dict(provenance)
            entry["policy_decision"] = decisions_by_key.get(key, {})
            previous = provenance_log.get(key, {})
            history = list(previous.get("history", [])) if isinstance(previous, dict) else []
            history.append(entry)
            provenance_log[key] = {
                "latest": entry,
                "history": history[-20:],
            }

        return {
            "_shared_memory_provenance": provenance_log,
            "_shared_memory_governance": self._shared_memory_governance_summary(
                shared_state.get("_shared_memory_governance", {}),
                decisions_by_key,
            ),
        }

    def _shared_memory_governance_summary(self, existing: dict, decisions_by_key: dict) -> dict:
        summary = dict(existing) if isinstance(existing, dict) else {}
        by_decision = dict(summary.get("by_decision", {}))
        by_key = dict(summary.get("by_key", {}))
        candidate_count = int(summary.get("candidate_count", 0))
        review_routed_count = int(summary.get("review_routed_count", 0))
        false_promotion_review_count = int(summary.get("false_promotion_review_count", 0))
        correlated_evidence_count = int(summary.get("correlated_evidence_count", 0))
        unsafe_scope_count = int(summary.get("unsafe_scope_count", 0))
        state_revision_count = int(summary.get("state_revision_count", 0))
        implicit_conflict_count = int(summary.get("implicit_conflict_count", 0))

        for key, decision in decisions_by_key.items():
            decision_name = str(decision.get("decision") or "unknown")
            flags = list(decision.get("quality_flags", []))
            flagged_for_false_promotion = bool({"correlated_evidence", "unsafe_scope"} & set(flags))
            candidate_count += 1
            by_decision[decision_name] = by_decision.get(decision_name, 0) + 1
            if decision_name in {"write_review_needed", "write_suppressed"} or flags:
                review_routed_count += 1
            if flagged_for_false_promotion:
                false_promotion_review_count += 1
            if "correlated_evidence" in flags:
                correlated_evidence_count += 1
            if "unsafe_scope" in flags:
                unsafe_scope_count += 1
            if "state_revision" in flags:
                state_revision_count += 1
            if "implicit_conflict" in flags:
                implicit_conflict_count += 1
            by_key[key] = {
                "decision": decision_name,
                "priority": decision.get("priority", "normal"),
                "quality_flags": flags,
            }

        summary.update({
            "candidate_count": candidate_count,
            "review_routed_count": review_routed_count,
            "false_promotion_review_count": false_promotion_review_count,
            "correlated_evidence_count": correlated_evidence_count,
            "unsafe_scope_count": unsafe_scope_count,
            "state_revision_count": state_revision_count,
            "implicit_conflict_count": implicit_conflict_count,
            "by_decision": by_decision,
            "by_key": by_key,
        })
        return summary

    def _safe_confidence(self, value, default: float = 0.85) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _dependencies_complete(self, task: dict, all_tasks: list[dict]) -> bool:
        for dependency in task.get("depends_on", []):
            if not any(
                other.get("source_task_id") == dependency and other.get("status") == "completed"
                for other in all_tasks
            ):
                return False
        return True

    def _preconditions_met(self, task: dict, shared_state: dict) -> bool:
        shared_preconditions = task.get("preconditions", {}).get("shared_state", {})
        return all(shared_state.get(key) == expected for key, expected in shared_preconditions.items())

    def _success_keys_satisfied(self, spec: CollaborationBenchmarkSpec, shared_state: dict) -> bool:
        if spec.shared_state.success_keys:
            return all(bool(shared_state.get(key)) for key in spec.shared_state.success_keys)
        criteria = spec.success_criteria.get("shared_state", {})
        return all(shared_state.get(key) == expected for key, expected in criteria.items())

    def _execution_errors(self, spec: CollaborationBenchmarkSpec, raw_state: dict, elapsed_s: float) -> list[str]:
        errors = []
        tasks = raw_state.get("tasks", {})
        by_source = {task.get("source_task_id"): task for task in tasks.values()}
        if spec.success_criteria.get("all_required_tasks_completed", False):
            incomplete = [
                task.id for task in spec.tasks
                if by_source.get(task.id, {}).get("status") != "completed"
            ]
            if incomplete:
                errors.append(f"incomplete required tasks: {', '.join(incomplete)}")
        for key, expected in spec.success_criteria.get("shared_state", {}).items():
            actual = raw_state.get("shared", {}).get(key)
            if actual != expected:
                errors.append(f"shared_state {key} expected {expected!r}, got {actual!r}")
        deadline = spec.success_criteria.get("deadline_s")
        if deadline is not None and elapsed_s > deadline:
            errors.append(f"benchmark deadline missed: {elapsed_s:.1f}s > {deadline}s")
        return errors

    def _apply_dynamic_events(self, spec: CollaborationBenchmarkSpec, state: SharedState, elapsed_s: float):
        due_events = [event for event in spec.dynamic_events if event.at_s <= elapsed_s]
        if not due_events:
            return
        shared = state.get_shared()
        fired = set(shared.get("_events_fired", []))
        new_events = [event for event in due_events if event.event_type not in fired]
        if not new_events:
            return
        fired.update(event.event_type for event in new_events)
        state.update_shared({
            "_events_fired": sorted(fired),
            "_active_events": [asdict(event) for event in new_events],
        })
