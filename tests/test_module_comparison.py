"""Tests for offline agent module comparison reports."""

import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, "src")

from singularity.evaluation.module_comparison import build_agent_module_comparison_report


def _write_jsonl(path: str, events: list[dict]):
    with open(path, "w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")


def _baseline_failure_events():
    return [
        {"type": "goal_start", "data": {"goal": "Craft torches"}},
        {"type": "plan", "data": {"status": "planning", "actions": [{"type": "craft", "parameters": {"item": "torch"}}]}},
        {
            "type": "action",
            "data": {
                "action": {"type": "craft", "parameters": {"item": "torch"}},
                "result": {"success": False, "error": "Missing coal"},
            },
        },
        {"type": "goal_end", "data": {"goal": "Craft torches", "result": {"completed": False}}},
    ]


def _candidate_module_events():
    return [
        {"type": "goal_start", "data": {"goal": "Craft torches"}},
        {"type": "memory_read", "data": {"memory_type": "episodic", "read_filter_report": {"filtered_entries": 1, "filter_reasons": {"stale": 1}}}},
        {"type": "skill_memory_hint", "data": {"task_family": "crafting", "hint_count": 2}},
        {"type": "plan_cache_hit", "data": {"entry_id": "pc-1", "goal": "Craft torches"}},
        {"type": "plan_cache_hybrid_hint", "data": {"entry_id": "pc-2", "goal": "Craft torches"}},
        {"type": "plan_cache_signature", "data": {"entry_id": "pc-1", "plan_signature": "sig"}},
        {
            "type": "visual_action_suggestion",
            "data": {
                "suggestions": [{
                    "kind": "resource_approach",
                    "action": {"type": "move_to", "parameters": {"x": 8, "y": 64, "z": 0}},
                }],
            },
        },
        {
            "type": "visual_action_intervention",
            "data": {
                "phase": "prepend_approach",
                "suggestion": {
                    "kind": "resource_approach",
                    "action": {"type": "move_to", "parameters": {"x": 8, "y": 64, "z": 0}},
                },
            },
        },
        {
            "type": "plan",
            "data": {
                "status": "planning",
                "actions": [
                    {"type": "move_to", "parameters": {"x": 8, "y": 64, "z": 0}},
                    {"type": "dig", "parameters": {"block": "coal_ore"}},
                    {"type": "craft", "parameters": {"item": "torch"}},
                ],
            },
        },
        {
            "type": "action_verification",
            "data": {
                "verification": {"status": "accept", "action_type": "dig"},
                "action": {"type": "dig", "parameters": {"block": "coal_ore"}},
            },
        },
        {
            "type": "action_candidate_selection",
            "data": {
                "selection": {
                    "selected_action": {"type": "dig", "parameters": {"block": "coal_ore"}},
                    "original_verification": {"status": "reject"},
                    "selected_verification": {"status": "accept"},
                },
            },
        },
        {"type": "policy_hint", "data": {"hints": ["gather_wood:REUSE"]}},
        {"type": "policy_intervention", "data": {"phase": "selected", "skill": "mine_coal"}},
        {"type": "policy_intervention", "data": {"phase": "completed", "skill": "mine_coal"}},
        {
            "type": "action",
            "data": {
                "action": {"type": "dig", "parameters": {"block": "coal_ore"}},
                "result": {
                    "success": True,
                    "control_policy": {
                        "action_type": "dig",
                        "backend": "mineflayer",
                        "preferred_control": "api",
                    },
                },
            },
        },
        {"type": "goal_verification", "data": {"achieved": True, "status": "achieved", "context": {"accepted": True}}},
        {"type": "goal_end", "data": {"goal": "Craft torches", "result": {"completed": True}}},
    ]


def test_agent_module_comparison_approves_active_candidate():
    tmpdir = tempfile.mkdtemp()
    baseline_path = os.path.join(tmpdir, "baseline.jsonl")
    candidate_path = os.path.join(tmpdir, "candidate.jsonl")
    _write_jsonl(baseline_path, _baseline_failure_events())
    _write_jsonl(candidate_path, _candidate_module_events())

    report = build_agent_module_comparison_report(
        [baseline_path],
        [candidate_path],
        baseline_label="plain",
        candidate_label="module_profile",
    )

    assert report["readiness"] == "approved"
    assert report["deltas"]["completion_rate_delta"] == 1.0
    assert report["deltas"]["action_failure_rate_delta"] == -1.0
    assert report["candidate"]["modules"]["plan_cache"]["hit_count"] == 1
    assert report["candidate"]["modules"]["plan_cache"]["hybrid_hint_count"] == 1
    assert report["candidate"]["modules"]["plan_cache"]["workflow_intervention_count"] == 2
    assert report["candidate"]["modules"]["visual_action_grounding"]["intervention_count"] == 1
    assert report["candidate"]["modules"]["action_candidate_selection"]["repaired_reject_count"] == 1
    assert report["candidate"]["modules"]["skill_memory"]["hint_count"] == 2
    assert report["candidate"]["modules"]["memory_policy"]["read_filtered_entries"] == 1
    assert report["candidate"]["modules"]["control_policy"]["event_count"] == 1
    assert "plan_cache" in report["module_activity"]["candidate_active_modules"]
    assert "package_candidate_artifacts_in_runtime_profile_after_dedicated_gates_pass" in report["recommendations"]
    print("PASS: Agent module comparison approves active candidate")


def test_agent_module_comparison_rejects_candidate_regressions():
    tmpdir = tempfile.mkdtemp()
    baseline_path = os.path.join(tmpdir, "baseline.jsonl")
    candidate_path = os.path.join(tmpdir, "candidate.jsonl")
    _write_jsonl(baseline_path, [
        {"type": "goal_start", "data": {"goal": "Craft torches"}},
        {"type": "plan", "data": {"status": "planning", "actions": [{"type": "craft", "parameters": {"item": "torch"}}]}},
        {"type": "action", "data": {"action": {"type": "craft"}, "result": {"success": True}}},
        {"type": "goal_end", "data": {"goal": "Craft torches", "result": {"completed": True}}},
    ])
    _write_jsonl(candidate_path, [
        {"type": "goal_start", "data": {"goal": "Craft torches"}},
        {"type": "plan_cache_hit", "data": {"entry_id": "unsafe"}},
        {"type": "plan", "data": {"status": "planning", "actions": [{"type": "craft", "parameters": {"item": "torch"}}]}},
        {"type": "action_verification", "data": {"verification": {"status": "reject", "action_type": "craft"}}},
        {"type": "action", "data": {"action": {"type": "craft"}, "result": {"success": False, "error": "Missing coal"}}},
        {"type": "goal_end", "data": {"goal": "Craft torches", "result": {"completed": False}}},
    ])

    report = build_agent_module_comparison_report([baseline_path], [candidate_path])

    assert report["readiness"] == "rejected"
    failed_checks = {check["name"] for check in report["checks"] if check["status"] == "fail"}
    assert "completion_rate_not_regressed" in failed_checks
    assert "action_failure_rate_not_regressed" in failed_checks
    assert "verifier_reject_rate_not_regressed" in failed_checks
    print("PASS: Agent module comparison rejects candidate regressions")


def test_agent_module_comparison_cli_writes_report():
    tmpdir = tempfile.mkdtemp()
    baseline_path = os.path.join(tmpdir, "baseline.jsonl")
    candidate_path = os.path.join(tmpdir, "candidate.jsonl")
    output_path = os.path.join(tmpdir, "comparison.json")
    _write_jsonl(baseline_path, _baseline_failure_events())
    _write_jsonl(candidate_path, _candidate_module_events())
    env = os.environ.copy()
    env["PYTHONPATH"] = "src"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "singularity.main",
            "agent-module-comparison-report",
            "--baseline-session-log",
            baseline_path,
            "--candidate-session-log",
            candidate_path,
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
    assert report["type"] == "agent_module_comparison_report"
    assert report["readiness"] == "approved"
    assert "Agent Module Comparison" in result.stdout
    print("PASS: Agent module comparison CLI writes report")


if __name__ == "__main__":
    test_agent_module_comparison_approves_active_candidate()
    test_agent_module_comparison_rejects_candidate_regressions()
    test_agent_module_comparison_cli_writes_report()
