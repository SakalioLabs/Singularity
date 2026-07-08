"""Unit tests for M7 collaboration benchmark schema."""
import os
import sys
import json
import tempfile
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from singularity.evaluation.collaboration_benchmark import (
    CollaborationBenchmarkSpec,
    CollaborationFeasibilityChecker,
)
from singularity.evaluation.collaboration_runner import (
    CollaborationBenchmarkRunner,
    CollaborationExecutionReport,
    CollaborationTaskExecution,
)
from singularity.multiagent.protocol import SharedState


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SAMPLE = os.path.join(ROOT, "workspace", "benchmarks", "m7_time_sensitive_shelter.json")


def test_load_m7_sample_and_assignment_plan():
    spec = CollaborationBenchmarkSpec.load_json(SAMPLE)
    report = CollaborationFeasibilityChecker().check(spec)
    plan = spec.assignment_plan()

    assert spec.id == "BM-701"
    assert report.ok
    assert "leader_builder" in plan
    assert "resource_runner" in plan
    assert any(task["id"] == "verify_shelter" for task in plan["leader_builder"])
    assert any(task["id"] == "gather_logs" for task in plan["resource_runner"])
    deliver = next(task for task in plan["resource_runner"] if task["id"] == "deliver_wood")
    assert deliver["shared_state_provenance"]["wood_delivered"]["dependency"] == "role_handoff"
    print("PASS: M7 sample loads and produces role assignment plan")


def test_feasibility_rejects_unknown_role_and_bad_deadline():
    data = {
        "id": "BAD-ROLE",
        "name": "Bad role",
        "max_duration_s": 60,
        "roles": [
            {"id": "leader", "capabilities": ["plan"], "required": True},
            {"id": "worker", "capabilities": ["gather"], "required": True},
        ],
        "tasks": [
            {
                "id": "late_task",
                "title": "Late task",
                "assigned_role": "ghost",
                "required_capabilities": ["gather"],
                "deadline_s": 90,
                "estimated_duration_s": 120,
            }
        ],
        "shared_state": {"required_keys": [], "initial": {}, "success_keys": []},
    }
    spec = CollaborationBenchmarkSpec.from_dict(data)
    checks = CollaborationFeasibilityChecker().check(spec).checks
    failures = {check.name: check for check in checks if check.status == "fail"}

    assert "task_assignments" in failures
    assert "deadlines" in failures
    print("PASS: M7 feasibility rejects unknown roles and bad deadlines")


def test_feasibility_requires_mandatory_collaboration():
    data = {
        "id": "BAD-COLLAB",
        "name": "Single active role",
        "max_duration_s": 120,
        "roles": [
            {"id": "leader", "capabilities": ["plan"], "required": True},
            {"id": "worker", "capabilities": ["gather"], "required": True},
        ],
        "tasks": [
            {
                "id": "solo",
                "title": "Solo task",
                "assigned_role": "leader",
                "required_capabilities": ["plan"],
                "deadline_s": 60,
                "estimated_duration_s": 20,
            }
        ],
        "shared_state": {"required_keys": [], "initial": {}, "success_keys": []},
    }
    spec = CollaborationBenchmarkSpec.from_dict(data)
    checks = CollaborationFeasibilityChecker().check(spec).checks
    mandatory = next(check for check in checks if check.name == "mandatory_collaboration")

    assert mandatory.status == "fail"
    assert "two required roles" in mandatory.remedy
    print("PASS: M7 feasibility requires mandatory collaboration")


def test_collaboration_runner_prepares_shared_state_assignments():
    tmpdir = tempfile.mkdtemp()
    state_path = os.path.join(tmpdir, "collab_state.json")

    runner = CollaborationBenchmarkRunner(state_path)
    result = runner.prepare_from_path(SAMPLE)
    state = SharedState(state_path)
    raw = state._read_state()

    assert result.ok
    assert result.leader_id == "leader_builder"
    assert result.assigned_tasks == 5
    assert raw["agents"]["leader_builder"]["role"] == "leader"
    assert raw["agents"]["resource_runner"]["role"] == "worker"
    assert raw["shared"]["wood_delivered"] is False
    assert raw["shared"]["_benchmark"]["id"] == "BM-701"
    assert len(raw["tasks"]) == 5
    print("PASS: M7 runner prepares shared state and assignments")


def test_collaboration_runner_executes_state_transition_loop():
    tmpdir = tempfile.mkdtemp()
    state_path = os.path.join(tmpdir, "collab_exec_state.json")

    runner = CollaborationBenchmarkRunner(state_path)
    report = runner.execute_from_path(SAMPLE)
    state = SharedState(state_path)
    raw = state._read_state()
    task_statuses = {task["source_task_id"]: task["status"] for task in raw["tasks"].values()}

    assert report.ok
    assert report.completed_tasks == 5
    assert report.failed_tasks == 0
    assert report.success_keys_satisfied
    assert raw["shared"]["wood_delivered"] is True
    assert raw["shared"]["shelter_frame_done"] is True
    assert raw["shared"]["torch_ready"] is True
    provenance = raw["shared"]["_shared_memory_provenance"]
    governance = raw["shared"]["_shared_memory_governance"]
    assert provenance["wood_delivered"]["latest"]["source_task_id"] == "deliver_wood"
    assert provenance["wood_delivered"]["latest"]["dependency"] == "role_handoff"
    assert provenance["wood_delivered"]["latest"]["policy_decision"]["decision"] == "semantic_promotion_candidate"
    assert len(provenance["shelter_frame_done"]["history"]) == 2
    assert len(provenance["torch_ready"]["history"]) == 2
    assert governance["candidate_count"] == 5
    assert governance["false_promotion_review_count"] == 0
    assert report.shared_memory_governance["candidate_count"] == 5
    assert set(task_statuses.values()) == {"completed"}
    execution_order = [item.source_task_id for item in report.task_results]
    assert execution_order.index("gather_logs") < execution_order.index("deliver_wood")
    assert execution_order.index("deliver_wood") < execution_order.index("build_frame")
    assert execution_order.index("build_frame") < execution_order.index("verify_shelter")
    assert all(item.finished_at_s >= item.started_at_s for item in report.task_results)
    assert all(item.duration_s >= 0.0 for item in report.task_results)
    print("PASS: M7 runner executes state-transition loop")


def test_collaboration_runner_dispatches_different_roles_in_parallel():
    tmpdir = tempfile.mkdtemp()
    state_path = os.path.join(tmpdir, "collab_parallel_state.json")

    runner = CollaborationBenchmarkRunner(state_path)
    active = {"count": 0, "max": 0}
    lock = threading.Lock()

    def sleeping_executor(task, agent_state, shared_state):
        with lock:
            active["count"] += 1
            active["max"] = max(active["max"], active["count"])
        try:
            time.sleep(0.05)
            return runner.simulated_task_executor(task, agent_state, shared_state)
        finally:
            with lock:
                active["count"] -= 1

    spec = CollaborationBenchmarkSpec.load_json(SAMPLE)
    report = runner.execute(spec, executor=sleeping_executor)

    assert report.ok
    assert report.dispatch_mode == "role_parallel"
    assert report.dispatch_batches == 4
    assert report.max_parallel_tasks == 2
    assert active["max"] == 2
    print("PASS: M7 runner dispatches different roles in parallel")


def test_collaboration_runner_serializes_reports_to_json():
    tmpdir = tempfile.mkdtemp()
    state_path = os.path.join(tmpdir, "collab_exec_state.json")
    output_path = os.path.join(tmpdir, "reports", "m7_report.json")

    runner = CollaborationBenchmarkRunner(state_path)
    spec = CollaborationBenchmarkSpec.load_json(SAMPLE)
    schedule = runner.analyze_schedule(spec)
    dry_run = runner.prepare_from_path(SAMPLE)
    execution = runner.execute_from_path(SAMPLE)
    execution_schedule_comparison = runner.compare_schedule_to_execution(schedule, execution)
    payload = {
        "schedule_analysis": runner.schedule_report_to_dict(schedule),
        "dry_run": runner.run_result_to_dict(dry_run),
        "execution": runner.execution_report_to_dict(execution),
        "execution_schedule_comparison": runner.schedule_execution_comparison_to_dict(execution_schedule_comparison),
    }
    runner.save_json_report(payload, output_path)

    with open(output_path, "r", encoding="utf-8") as f:
        saved = json.load(f)

    assert saved["dry_run"]["type"] == "collaboration_dry_run"
    assert saved["dry_run"]["assigned_tasks"] == 5
    assert saved["schedule_analysis"]["type"] == "collaboration_schedule_analysis"
    assert saved["schedule_analysis"]["makespan_s"] == 275.0
    assert saved["execution"]["type"] == "collaboration_execution"
    assert saved["execution"]["completed_tasks"] == 5
    assert saved["execution"]["dispatch_mode"] == "role_parallel"
    assert saved["execution"]["max_parallel_tasks"] == 2
    assert saved["execution"]["shared_memory_governance"]["candidate_count"] == 5
    assert saved["execution"]["task_results"][0]["started_at_s"] >= 0.0
    assert saved["execution"]["task_results"]
    assert saved["execution_schedule_comparison"]["type"] == "collaboration_schedule_vs_execution"
    assert len(saved["execution_schedule_comparison"]["task_comparisons"]) == 5
    assert "actual_peak_parallel_tasks" in saved["execution_schedule_comparison"]
    assert "overlapping_task_pairs" in saved["execution_schedule_comparison"]
    print("PASS: M7 runner serializes reports to JSON")


def test_collaboration_runner_runs_single_agent_baseline():
    tmpdir = tempfile.mkdtemp()
    state_path = os.path.join(tmpdir, "baseline_state.json")

    spec = CollaborationBenchmarkSpec.load_json(SAMPLE)
    runner = CollaborationBenchmarkRunner(state_path)
    baseline_spec = runner.single_agent_baseline_spec(spec)
    report = runner.run_single_agent_baseline(spec)

    assert baseline_spec.id == "BM-701-SINGLE"
    assert len(baseline_spec.roles) == 1
    assert baseline_spec.roles[0].id == "single_agent"
    assert all(task.assigned_role == "single_agent" for task in baseline_spec.tasks)
    assert report.ok
    assert report.completed_tasks == 5
    assert report.max_parallel_tasks == 1
    assert {item.assigned_to for item in report.task_results} == {"single_agent"}
    print("PASS: M7 runner runs single-agent baseline")


def test_collaboration_runner_compares_against_single_agent_baseline():
    tmpdir = tempfile.mkdtemp()
    spec = CollaborationBenchmarkSpec.load_json(SAMPLE)

    collab_runner = CollaborationBenchmarkRunner(os.path.join(tmpdir, "collab_state.json"))
    baseline_runner = CollaborationBenchmarkRunner(os.path.join(tmpdir, "baseline_state.json"))
    collaboration = collab_runner.execute(spec)
    baseline = baseline_runner.run_single_agent_baseline(spec)
    comparison = collab_runner.compare_execution_reports(collaboration, baseline)

    assert comparison["type"] == "collaboration_vs_single_agent_baseline"
    assert comparison["collaboration_ok"] is True
    assert comparison["baseline_ok"] is True
    assert comparison["completed_tasks_delta"] == 0
    assert "total_elapsed_s_delta" in comparison
    print("PASS: M7 runner compares collaboration against single-agent baseline")


def test_collaboration_runner_compares_mixed_policy_executions():
    tmpdir = tempfile.mkdtemp()
    runner = CollaborationBenchmarkRunner()

    def write_action_log(name, preferred_control, fallback_reason=""):
        path = os.path.join(tmpdir, name)
        control_policy = {
            "action_type": "place",
            "backend": "mineflayer",
            "preferred_backend": "desktop" if preferred_control == "consider_low_level_visual_control" else "mineflayer",
            "preferred_control": preferred_control,
            "reason": "visual_or_precision_sensitive" if preferred_control == "consider_low_level_visual_control" else "default_backend",
        }
        if fallback_reason:
            control_policy["fallback_reason"] = fallback_reason
        event = {
            "type": "action",
            "data": {
                "action": {"type": "place", "parameters": {"item": "torch"}},
                "result": {
                    "success": True,
                    "action_type": "place",
                    "backend": "mineflayer",
                    "control_policy": control_policy,
                },
            },
        }
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")
        return path

    baseline_log = write_action_log("baseline.jsonl", "mineflayer_api_ok")
    patched_log = write_action_log(
        "patched.jsonl",
        "consider_low_level_visual_control",
        "preferred backend desktop is not enabled",
    )
    baseline = CollaborationExecutionReport(
        spec_id="BM-701",
        ok=False,
        state_path="baseline.json",
        completed_tasks=1,
        failed_tasks=1,
        skipped_tasks=1,
        deadline_misses=1,
        total_elapsed_s=42.0,
        shared_state={"wood_delivered": False},
        task_results=[
            CollaborationTaskExecution(
                task_id="1",
                source_task_id="gather_logs",
                assigned_to="resource_runner",
                status="completed",
                elapsed_s=10.0,
            ),
            CollaborationTaskExecution(
                task_id="2",
                source_task_id="deliver_wood",
                assigned_to="resource_runner",
                status="failed",
                elapsed_s=20.0,
                result={"agent_result": {"summary": {"log_path": baseline_log}}},
            ),
        ],
    )
    patched = CollaborationExecutionReport(
        spec_id="BM-701",
        ok=True,
        state_path="patched.json",
        completed_tasks=2,
        failed_tasks=0,
        skipped_tasks=0,
        deadline_misses=0,
        total_elapsed_s=38.0,
        shared_state={"wood_delivered": True},
        task_results=[
            CollaborationTaskExecution(
                task_id="1",
                source_task_id="gather_logs",
                assigned_to="resource_runner",
                status="completed",
                elapsed_s=10.0,
            ),
            CollaborationTaskExecution(
                task_id="2",
                source_task_id="deliver_wood",
                assigned_to="resource_runner",
                status="completed",
                elapsed_s=20.0,
                result={"agent_result": {"summary": {"log_path": patched_log}}},
            ),
        ],
    )

    comparison = runner.compare_mixed_policy_execution_reports(baseline, patched)

    assert comparison["type"] == "collaboration_mixed_policy_ablation_comparison"
    assert comparison["ok_delta"] == 1
    assert comparison["completed_tasks_delta"] == 1
    assert comparison["failed_tasks_delta"] == -1
    assert comparison["skipped_tasks_delta"] == -1
    assert comparison["deadline_misses_delta"] == -1
    assert comparison["total_elapsed_s_delta"] == -4.0
    assert comparison["shared_state_changed"]
    assert comparison["control_policy_changed"]
    assert comparison["baseline_control_policy"]["preferred_control_counts"]["mineflayer_api_ok"] == 1
    assert comparison["patched_control_policy"]["preferred_control_counts"]["consider_low_level_visual_control"] == 1
    assert comparison["patched_control_policy"]["fallback_count"] == 1
    assert comparison["patched_control_policy"]["logs"][0]["task_id"] == "deliver_wood"
    assert comparison["task_status_changed"] == [
        {
            "task_id": "deliver_wood",
            "baseline_status": "failed",
            "patched_status": "completed",
        }
    ]
    print("PASS: M7 runner compares mixed-policy executions")


def test_collaboration_runner_analyzes_parallel_schedule_against_baseline():
    spec = CollaborationBenchmarkSpec.load_json(SAMPLE)
    runner = CollaborationBenchmarkRunner()

    collaboration = runner.analyze_schedule(spec)
    baseline = runner.analyze_single_agent_baseline_schedule(spec)
    comparison = runner.compare_schedule_reports(collaboration, baseline)
    tasks = {item.task_id: item for item in collaboration.task_schedule}

    assert collaboration.ok
    assert baseline.ok
    assert collaboration.makespan_s == 275.0
    assert baseline.makespan_s == 365.0
    assert tasks["gather_logs"].start_s == 0.0
    assert tasks["deliver_wood"].start_s == 90.0
    assert tasks["build_frame"].start_s == 135.0
    assert tasks["prepare_torch"].start_s == 135.0
    assert tasks["verify_shelter"].start_s == 255.0
    assert comparison["type"] == "collaboration_schedule_vs_single_agent_baseline"
    assert comparison["makespan_s_delta"] == -90.0
    assert comparison["speedup"] > 1.0
    print("PASS: M7 runner analyzes parallel schedule against single-agent baseline")


def test_collaboration_runner_compares_schedule_to_execution():
    tmpdir = tempfile.mkdtemp()
    state_path = os.path.join(tmpdir, "collab_exec_state.json")
    spec = CollaborationBenchmarkSpec.load_json(SAMPLE)
    runner = CollaborationBenchmarkRunner(state_path)

    schedule = runner.analyze_schedule(spec)
    execution = runner.execute(spec)
    comparison = runner.compare_schedule_to_execution(schedule, execution)
    by_task = {item.task_id: item for item in comparison.task_comparisons}

    assert comparison.ok
    assert comparison.schedule_makespan_s == 275.0
    assert comparison.actual_elapsed_s >= 0.0
    assert comparison.elapsed_delta_s <= 0.0
    assert comparison.missing_scheduled_tasks == []
    assert comparison.unexpected_execution_tasks == []
    assert by_task["gather_logs"].expected_start_s == 0.0
    assert by_task["gather_logs"].status == "completed"
    assert by_task["verify_shelter"].actual_finish_s is not None
    print("PASS: M7 runner compares static schedule to execution timings")


def test_collaboration_runner_reports_actual_parallel_overlap():
    tmpdir = tempfile.mkdtemp()
    state_path = os.path.join(tmpdir, "collab_overlap_state.json")
    spec = CollaborationBenchmarkSpec.load_json(SAMPLE)
    runner = CollaborationBenchmarkRunner(state_path)

    def sleeping_executor(task, agent_state, shared_state):
        time.sleep(0.05)
        return runner.simulated_task_executor(task, agent_state, shared_state)

    schedule = runner.analyze_schedule(spec)
    execution = runner.execute(spec, executor=sleeping_executor)
    comparison = runner.compare_schedule_to_execution(schedule, execution)
    overlap_pairs = {
        frozenset([pair.task_a, pair.task_b]): pair
        for pair in comparison.overlapping_task_pairs
    }

    assert comparison.ok
    assert comparison.actual_peak_parallel_tasks == 2
    assert comparison.actual_parallel_overlap_s > 0
    assert comparison.actual_task_seconds_s > 0
    assert comparison.actual_busy_window_s > 0
    assert frozenset(["build_frame", "prepare_torch"]) in overlap_pairs
    assert overlap_pairs[frozenset(["build_frame", "prepare_torch"])].overlap_s > 0
    print("PASS: M7 runner reports actual parallel overlap")


def test_collaboration_runner_flags_correlated_shared_memory_updates():
    tmpdir = tempfile.mkdtemp()
    state_path = os.path.join(tmpdir, "collab_govmem_state.json")
    spec = CollaborationBenchmarkSpec.load_json(SAMPLE)
    runner = CollaborationBenchmarkRunner(state_path)

    def correlated_executor(task, agent_state, shared_state):
        if task.get("source_task_id") == "deliver_wood":
            return {
                "success": True,
                "shared_state": {"wood_delivered": True},
                "shared_state_provenance": {
                    "wood_delivered": {
                        "dependency": "shared_prompt",
                        "validity": "out_of_scope",
                        "scope": "copied claim from another role",
                        "confidence": 0.9,
                    }
                },
            }
        return runner.simulated_task_executor(task, agent_state, shared_state)

    report = runner.execute(spec, executor=correlated_executor)
    state = SharedState(state_path)
    raw = state._read_state()
    governance = report.shared_memory_governance
    decision = raw["shared"]["_shared_memory_provenance"]["wood_delivered"]["latest"]["policy_decision"]

    assert report.ok
    assert decision["decision"] == "write_review_needed"
    assert "correlated_evidence" in decision["quality_flags"]
    assert "unsafe_scope" in decision["quality_flags"]
    assert governance["false_promotion_review_count"] == 1
    assert governance["correlated_evidence_count"] == 1
    assert governance["unsafe_scope_count"] == 1
    assert governance["by_key"]["wood_delivered"]["decision"] == "write_review_needed"
    print("PASS: M7 runner flags correlated shared-memory updates")


def test_collaboration_runner_tracks_shared_memory_state_revision():
    tmpdir = tempfile.mkdtemp()
    state_path = os.path.join(tmpdir, "collab_stale_state.json")
    spec = CollaborationBenchmarkSpec.from_dict({
        "id": "STALE-M7",
        "name": "Route state revision",
        "max_duration_s": 120,
        "roles": [
            {"id": "scout", "capabilities": ["observe"], "required": True},
            {"id": "leader", "capabilities": ["verify"], "required": True},
        ],
        "shared_state": {
            "required_keys": ["route_clear"],
            "initial": {"route_clear": False},
            "success_keys": [],
        },
        "tasks": [
            {
                "id": "scout_route",
                "title": "Scout route",
                "assigned_role": "scout",
                "required_capabilities": ["observe"],
                "success_criteria": {"shared_state": {"route_clear": True}},
                "shared_state_updates": ["route_clear"],
                "shared_state_provenance": {
                    "route_clear": {
                        "dependency": "direct_task_result",
                        "validity": "current",
                        "scope": "route safety",
                    }
                },
            },
            {
                "id": "verify_route",
                "title": "Verify route after nightfall",
                "assigned_role": "leader",
                "depends_on": ["scout_route"],
                "required_capabilities": ["verify"],
                "success_criteria": {"shared_state": {"route_clear": False}},
                "shared_state_updates": ["route_clear"],
            },
        ],
        "success_criteria": {
            "all_required_tasks_completed": True,
            "shared_state": {"route_clear": False},
        },
    })
    runner = CollaborationBenchmarkRunner(state_path)

    report = runner.execute(spec)
    state = SharedState(state_path)
    raw = state._read_state()
    route_provenance = raw["shared"]["_shared_memory_provenance"]["route_clear"]
    latest = route_provenance["latest"]
    decision = latest["policy_decision"]

    assert report.ok
    assert raw["shared"]["route_clear"] is False
    assert len(route_provenance["history"]) == 2
    assert latest["previous_value"] is True
    assert latest["previous_source_task_id"] == "scout_route"
    assert latest["validity"] == "implicit_conflict"
    assert decision["decision"] == "write_review_needed"
    assert "state_revision" in decision["quality_flags"]
    assert "implicit_conflict" in decision["quality_flags"]
    assert report.shared_memory_governance["state_revision_count"] == 1
    assert report.shared_memory_governance["implicit_conflict_count"] == 1
    print("PASS: M7 runner tracks shared-memory state revisions")


def test_collaboration_runner_schedule_execution_comparison_reports_missing_tasks():
    tmpdir = tempfile.mkdtemp()
    state_path = os.path.join(tmpdir, "collab_failed_state.json")
    spec = CollaborationBenchmarkSpec.load_json(SAMPLE)
    runner = CollaborationBenchmarkRunner(state_path)

    def fail_handoff(task, agent_state, shared_state):
        if task.get("source_task_id") == "deliver_wood":
            return {"success": False, "error": "handoff failed"}
        return runner.simulated_task_executor(task, agent_state, shared_state)

    schedule = runner.analyze_schedule(spec)
    execution = runner.execute(spec, executor=fail_handoff)
    comparison = runner.compare_schedule_to_execution(schedule, execution)

    assert not comparison.ok
    assert "build_frame" in comparison.missing_scheduled_tasks
    assert "verify_shelter" in comparison.missing_scheduled_tasks
    assert any("scheduled tasks not executed" in error for error in comparison.errors)
    print("PASS: M7 schedule/execution comparison reports missing dependent tasks")


def test_collaboration_runner_schedule_detects_blocked_dependencies():
    spec = CollaborationBenchmarkSpec.from_dict({
        "id": "BAD-SCHEDULE",
        "name": "Blocked schedule",
        "max_duration_s": 120,
        "roles": [
            {"id": "leader", "capabilities": ["plan"], "required": True},
            {"id": "worker", "capabilities": ["gather"], "required": True},
        ],
        "tasks": [
            {"id": "a", "title": "A", "assigned_role": "leader", "depends_on": ["b"], "estimated_duration_s": 20},
            {"id": "b", "title": "B", "assigned_role": "worker", "depends_on": ["a"], "estimated_duration_s": 20},
        ],
    })
    report = CollaborationBenchmarkRunner().analyze_schedule(spec)

    assert not report.ok
    assert report.makespan_s == 0.0
    assert any("cyclic or unscheduled dependencies" in error for error in report.errors)
    print("PASS: M7 schedule analysis detects blocked dependencies")


def test_collaboration_runner_blocks_dependents_after_executor_failure():
    tmpdir = tempfile.mkdtemp()
    state_path = os.path.join(tmpdir, "collab_failed_state.json")

    runner = CollaborationBenchmarkRunner(state_path)

    def fail_handoff(task, agent_state, shared_state):
        if task.get("source_task_id") == "deliver_wood":
            return {"success": False, "error": "handoff failed"}
        return runner.simulated_task_executor(task, agent_state, shared_state)

    report = runner.execute_from_path(SAMPLE, executor=fail_handoff)
    state = SharedState(state_path)
    raw = state._read_state()
    task_statuses = {task["source_task_id"]: task["status"] for task in raw["tasks"].values()}

    assert not report.ok
    assert report.failed_tasks == 1
    assert task_statuses["deliver_wood"] == "failed"
    assert task_statuses["build_frame"] == "assigned"
    assert task_statuses["verify_shelter"] == "assigned"
    assert any("incomplete required tasks" in error for error in report.errors)
    print("PASS: M7 runner blocks dependents after executor failure")


def test_collaboration_runner_stops_on_infeasible_spec():
    tmpdir = tempfile.mkdtemp()
    state_path = os.path.join(tmpdir, "bad_state.json")
    spec = CollaborationBenchmarkSpec.from_dict({
        "id": "BAD",
        "name": "Bad collaboration",
        "roles": [{"id": "only", "capabilities": ["plan"], "required": True}],
        "tasks": [{"id": "solo", "title": "Solo", "assigned_role": "only"}],
    })

    result = CollaborationBenchmarkRunner(state_path).prepare(spec)

    assert not result.ok
    assert result.assigned_tasks == 0
    assert not os.path.exists(state_path)
    print("PASS: M7 runner stops before writing infeasible specs")


if __name__ == "__main__":
    test_load_m7_sample_and_assignment_plan()
    test_feasibility_rejects_unknown_role_and_bad_deadline()
    test_feasibility_requires_mandatory_collaboration()
    test_collaboration_runner_prepares_shared_state_assignments()
    test_collaboration_runner_executes_state_transition_loop()
    test_collaboration_runner_dispatches_different_roles_in_parallel()
    test_collaboration_runner_serializes_reports_to_json()
    test_collaboration_runner_runs_single_agent_baseline()
    test_collaboration_runner_compares_against_single_agent_baseline()
    test_collaboration_runner_compares_mixed_policy_executions()
    test_collaboration_runner_analyzes_parallel_schedule_against_baseline()
    test_collaboration_runner_compares_schedule_to_execution()
    test_collaboration_runner_reports_actual_parallel_overlap()
    test_collaboration_runner_flags_correlated_shared_memory_updates()
    test_collaboration_runner_tracks_shared_memory_state_revision()
    test_collaboration_runner_schedule_execution_comparison_reports_missing_tasks()
    test_collaboration_runner_schedule_detects_blocked_dependencies()
    test_collaboration_runner_blocks_dependents_after_executor_failure()
    test_collaboration_runner_stops_on_infeasible_spec()
    print("\nCollaboration benchmark tests PASSED")
