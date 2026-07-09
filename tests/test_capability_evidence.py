"""Tests for evidence-backed project capability status."""

import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, "src")

from singularity.evaluation.capability_evidence import build_capability_evidence_report


def _write_status(path: str):
    with open(path, "w", encoding="utf-8") as f:
        f.write(
            "| Phase | Name | Status | Progress |\n"
            "|---|---|---|---|\n"
            "| M0 | Research | Complete | 100% |\n"
            "| M1 | Bot | Complete | 100% |\n"
            "| M2 | Planner | In Progress | 60% |\n"
        )


def _write_results(path: str):
    with open(path, "w", encoding="utf-8") as f:
        json.dump([
            {
                "task_id": "BM-001",
                "status": "success",
                "cycles": 5,
                "log": "logs/session-success.jsonl",
            },
            {
                "task_id": "BM-002",
                "status": "fail",
                "cycles": 20,
                "log": "logs/session-fail.jsonl",
            },
            {
                "task_id": "BM-003",
                "status": "planned",
                "task_name": "not an execution record",
            },
        ], f)


def _write_json(path: str, payload):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f)


def _continual_case(run_number: int) -> dict:
    return {
        "source_log": f"logs/live-memory-{run_number}.jsonl",
        "completed_goal_count": 1,
        "memory_read_count": 2,
        "memory_write_count": 1,
        "progress_event_count": 2,
        "unbounded_context_cycle_count": 0,
        "ready_for_continual_learning_review": True,
    }


def _exploration_case(run_number: int) -> dict:
    return {
        "source_log": f"logs/live-exploration-{run_number}.jsonl",
        "completed_goal_count": 1,
        "unique_position_count": 8,
        "path_distance": 24.0,
        "multi_step_plan_count": 1,
        "multi_hop_goal_count": 0,
        "auto_goal_count": 1,
        "curriculum_goal_count": 0,
        "unique_block_types": ["oak_log"],
        "unique_entity_types": [],
        "unique_resource_types": ["wood"],
        "ready_for_exploration_review": True,
    }


def _visual_case(run_number: int) -> dict:
    return {
        "source_log": f"logs/live-visual-{run_number}.jsonl",
        "screenshot_count": 2,
        "missing_screenshot_count": 0,
        "invalid_screenshot_count": 0,
        "visual_analysis_count": 2,
        "goals_with_visual_evidence": 1,
        "ready_for_visual_ablation": True,
    }


def _visual_action_case(run_number: int, source: str = "") -> dict:
    source = source or f"logs/live-visual-{run_number}.jsonl"
    return {
        "source": source,
        "passed": True,
        "changed": True,
        "enabled_helped": True,
        "enabled_interventions": 1,
        "expected_phase": "prepend_approach",
        "enabled_phases": {"prepend_approach": 1},
    }


def test_capability_evidence_rejects_unsupported_completion_claims():
    tmpdir = tempfile.mkdtemp()
    status_path = os.path.join(tmpdir, "STATUS.md")
    results_path = os.path.join(tmpdir, "results.json")
    _write_status(status_path)
    _write_results(results_path)

    report = build_capability_evidence_report(
        [results_path],
        status_path=status_path,
        source_root=tmpdir,
        min_repeats=3,
        runtime_evidence={"ok": False, "checks": []},
    )
    phases = {phase["id"]: phase for phase in report["phases"]}

    assert report["readiness"] == "rejected"
    assert report["claim_readiness"] == "rejected"
    assert report["system_status"] == "incomplete"
    assert phases["M0"]["status"] == "source_incomplete"
    assert phases["M0"]["claim_assessment"] == "contradicted"
    assert phases["M1"]["status"] == "failing"
    assert phases["M1"]["claim_assessment"] == "contradicted"
    assert phases["M1"]["benchmarks"][0]["status"] == "live_observed"
    assert phases["M1"]["benchmarks"][1]["status"] == "failing"
    assert phases["M1"]["benchmarks"][2]["attempts"] == 0
    assert phases["M2"]["claim_assessment"] == "not_claimed_complete"
    assert phases["M3"]["status"] == "not_run"
    assert phases["M5"]["status"] == "not_run"
    assert phases["M6"]["status"] == "not_run"
    assert "restore_live_minecraft_preflight_before_new_capability_claims" in report["recommendations"]
    print("PASS: Capability evidence rejects unsupported completion claims")


def test_capability_evidence_requires_distinct_repeated_runs():
    tmpdir = tempfile.mkdtemp()
    status_path = os.path.join(tmpdir, "STATUS.md")
    results_path = os.path.join(tmpdir, "results.json")
    _write_status(status_path)
    results = []
    for task_number in range(1, 6):
        for run_number in range(1, 4):
            results.append({
                "task_id": f"BM-{task_number:03d}",
                "status": "pass",
                "duration_s": 1,
                "log": f"logs/bm{task_number}-run{run_number}.jsonl",
            })
    results.append(dict(results[0]))
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump({"results": results}, f)

    report = build_capability_evidence_report(
        [results_path],
        status_path=status_path,
        source_root=tmpdir,
        min_repeats=3,
    )
    m1 = next(phase for phase in report["phases"] if phase["id"] == "M1")

    assert m1["status"] == "repeat_verified"
    assert m1["claim_assessment"] == "supported"
    assert all(task["attempts"] == 3 for task in m1["benchmarks"])
    assert report["system_complete"] is False
    print("PASS: Capability evidence requires distinct repeated runs")


def test_live_phase_adapters_require_repeated_grounded_evidence():
    tmpdir = tempfile.mkdtemp()
    status_path = os.path.join(tmpdir, "STATUS.md")
    _write_status(status_path)

    m3_trace = os.path.join(tmpdir, "m3-trace.json")
    m3_gate = os.path.join(tmpdir, "m3-gate.json")
    m5_trace = os.path.join(tmpdir, "m5-trace.json")
    m5_gate = os.path.join(tmpdir, "m5-gate.json")
    m6_trace = os.path.join(tmpdir, "m6-trace.json")
    m6_action = os.path.join(tmpdir, "m6-action.json")
    _write_json(m3_trace, {
        "continual_learning_feedback": {},
        "cases": [_continual_case(index) for index in range(1, 4)] + [_continual_case(1)],
    })
    _write_json(m3_gate, {
        "required": True,
        "readiness": "approved",
        "decision": "allow_candidate_promotion",
        "transfer_report_count": 1,
        "ready_stream_count": 1,
        "task_count": 4,
        "evidence_count": 1,
        "regression_count": 0,
        "average_generalization_gain": 0.1,
        "thresholds": {"require_heldout": True},
    })
    _write_json(m5_trace, {
        "curriculum_feedback": {},
        "cases": [_exploration_case(index) for index in range(1, 4)],
    })
    _write_json(m5_gate, {
        "type": "world_model_feedback_gate",
        "readiness": "approved",
        "decision": "allow_world_model_feedback",
        "source_count": 1,
        "ready_log_count": 3,
        "actionable_item_count": 4,
        "structured_frontier_count": 2,
        "structured_hotspot_count": 1,
    })
    _write_json(m6_trace, {
        "screenshot_log_count": 3,
        "goals_with_visual_evidence_count": 3,
        "cases": [_visual_case(index) for index in range(1, 4)],
    })
    _write_json(m6_action, {
        "passed_count": 3,
        "changed_count": 3,
        "helped_count": 3,
        "cases": [_visual_action_case(index) for index in range(1, 4)],
    })

    report = build_capability_evidence_report(
        status_path=status_path,
        source_root=tmpdir,
        min_repeats=3,
        phase_evidence_paths={
            "M3": [m3_trace, m3_gate],
            "M5": [m5_trace, m5_gate],
            "M6": [m6_trace, m6_action],
        },
    )
    phases = {phase["id"]: phase for phase in report["phases"]}

    for phase_id in ("M3", "M5", "M6"):
        assert phases[phase_id]["status"] == "repeat_verified", phases[phase_id]
        assert phases[phase_id]["live_evidence"]["verified_successes"] == 3
        assert phases[phase_id]["live_evidence"]["support_approved"] is True
    assert phases["M3"]["live_evidence"]["attempts"] == 3
    assert report["schema_version"] == 2
    print("PASS: Live phase adapters require repeated grounded evidence")


def test_live_phase_adapters_reject_weak_or_unlinked_evidence():
    tmpdir = tempfile.mkdtemp()
    status_path = os.path.join(tmpdir, "STATUS.md")
    _write_status(status_path)
    m5_trace = os.path.join(tmpdir, "m5-trace.json")
    m6_trace = os.path.join(tmpdir, "m6-trace.json")
    m6_action = os.path.join(tmpdir, "m6-action.json")

    weak_exploration = _exploration_case(1)
    weak_exploration["auto_goal_count"] = 0
    _write_json(m5_trace, {"curriculum_feedback": {}, "cases": [weak_exploration]})
    _write_json(m6_trace, {
        "screenshot_log_count": 3,
        "goals_with_visual_evidence_count": 3,
        "cases": [_visual_case(index) for index in range(1, 4)],
    })
    _write_json(m6_action, {
        "passed_count": 2,
        "changed_count": 2,
        "helped_count": 2,
        "cases": [
            _visual_action_case(1, source="builtin"),
            _visual_action_case(1, source="logs/unlinked-session.jsonl"),
        ],
    })

    report = build_capability_evidence_report(
        status_path=status_path,
        source_root=tmpdir,
        min_repeats=3,
        phase_evidence_paths={"M5": [m5_trace], "M6": [m6_trace, m6_action]},
    )
    phases = {phase["id"]: phase for phase in report["phases"]}

    assert phases["M5"]["status"] == "failing"
    assert "autonomous_or_curriculum_goal" in phases["M5"]["live_evidence"]["primary_cases"][0]["failed_criteria"]
    assert phases["M6"]["status"] == "partial"
    assert phases["M6"]["live_evidence"]["primary_successes"] == 3
    assert phases["M6"]["live_evidence"]["verified_successes"] == 0
    assert phases["M6"]["live_evidence"]["ignored_builtin_support_case_count"] == 1
    assert "needs_3_more_visual_action_linked_sessions" in phases["M6"]["missing_evidence"]
    print("PASS: Live phase adapters reject weak or unlinked evidence")


def test_live_report_cli_emits_typed_artifacts():
    tmpdir = tempfile.mkdtemp()
    session_path = os.path.join(tmpdir, "session.jsonl")
    with open(session_path, "w", encoding="utf-8") as f:
        f.write(json.dumps({
            "type": "observation",
            "data": {"position": {"x": 0, "y": 64, "z": 0}, "nearby_blocks": []},
        }) + "\n")
    env = os.environ.copy()
    env["PYTHONPATH"] = "src"
    commands = {
        "continual-learning-report": "continual_learning_report",
        "exploration-trace-report": "exploration_trace_report",
        "world-model-report": "world_model_report",
        "visual-trace-report": "visual_trace_report",
        "visual-action-ablation": "visual_action_ablation_report",
    }
    for command, expected_type in commands.items():
        output_path = os.path.join(tmpdir, f"{command}.json")
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "singularity.main",
                command,
                "--session-log",
                session_path,
                "--output",
                output_path,
            ],
            cwd=os.getcwd(),
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr + result.stdout
        with open(output_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        assert payload["type"] == expected_type, (command, payload)
        assert payload["schema_version"] == 1
    print("PASS: Live report CLI emits typed artifacts")


def test_capability_evidence_cli_writes_report():
    tmpdir = tempfile.mkdtemp()
    status_path = os.path.join(tmpdir, "STATUS.md")
    results_path = os.path.join(tmpdir, "results.json")
    output_path = os.path.join(tmpdir, "capability.json")
    _write_status(status_path)
    _write_results(results_path)
    env = os.environ.copy()
    env["PYTHONPATH"] = "src"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "singularity.main",
            "capability-evidence-report",
            "--benchmark-results",
            results_path,
            "--status-file",
            status_path,
            "--source-root",
            tmpdir,
            "--output",
            output_path,
        ],
        cwd=os.getcwd(),
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    with open(output_path, "r", encoding="utf-8") as f:
        report = json.load(f)
    assert report["type"] == "capability_evidence_report"
    assert report["readiness"] == "rejected"
    assert "Capability Evidence Report" in result.stdout

    strict_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "singularity.main",
            "capability-evidence-report",
            "--benchmark-results",
            results_path,
            "--status-file",
            status_path,
            "--source-root",
            tmpdir,
            "--strict",
        ],
        cwd=os.getcwd(),
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert strict_result.returncode == 1
    print("PASS: Capability evidence CLI writes report")


if __name__ == "__main__":
    test_capability_evidence_rejects_unsupported_completion_claims()
    test_capability_evidence_requires_distinct_repeated_runs()
    test_live_phase_adapters_require_repeated_grounded_evidence()
    test_live_phase_adapters_reject_weak_or_unlinked_evidence()
    test_live_report_cli_emits_typed_artifacts()
    test_capability_evidence_cli_writes_report()
