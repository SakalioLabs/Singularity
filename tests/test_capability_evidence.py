"""Tests for evidence-backed project capability status."""

import json
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, "src")

from singularity.evaluation.capability_evidence import (
    M1_PROTOCOL_SHA256,
    audit_capability_document_consistency,
    build_capability_evidence_report,
)
from singularity.evaluation.m1_protocol import PROTOCOL as M1_PROTOCOL, TASKS_BY_ID as M1_TASKS_BY_ID


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


def _write_m1_live_session(path: str, task_id: str, session_id: str):
    spec = M1_TASKS_BY_ID[task_id]
    initial_inventory = dict(spec["initial_inventory"])
    target_item, target_count = next(iter(spec["success_criteria"].items()))
    action_type = spec["evidence"]["action"]
    current_inventory = dict(initial_inventory)
    action_events = []
    action_count = target_count if action_type == "dig" else 1
    for index in range(action_count):
        before_inventory = dict(current_inventory)
        if action_type == "dig":
            current_inventory[target_item] = current_inventory.get(target_item, 0) + 1
            source_block = spec["evidence"]["source_blocks"][0]
            action = {
                "type": "dig",
                "parameters": {"x": index + 1, "y": 64, "z": 0},
            }
            result = {"success": True, "block": source_block}
            before_blocks = [{"name": source_block, "position": {"x": index + 1, "y": 64, "z": 0}}]
            after_blocks = []
        else:
            current_inventory = {target_item: target_count}
            action = {"type": "craft", "parameters": {"item": target_item, "count": 1}}
            result = {"success": True, "item": target_item}
            before_blocks = []
            after_blocks = []
        action_events.append({
            "session": session_id,
            "type": "action",
            "data": {
                "action": action,
                "result": result,
                "pre_observation": {
                    "position": {"x": 0, "y": 64, "z": 0},
                    "inventory": before_inventory,
                    "nearby_blocks": before_blocks,
                },
                "post_observation": {
                    "position": {"x": 0, "y": 64, "z": 0},
                    "inventory": dict(current_inventory),
                    "nearby_blocks": after_blocks,
                },
                "action_context": {"cycle": index + 1},
            },
        })
    reset_checks = {
        "inventory_exact": True,
        "position_at_spawn": True,
        "position_distance": 0.0,
        "fixture": True,
    }
    runtime_profile = {
        "isolated": True,
        "protocol_sha256": M1_PROTOCOL_SHA256,
        "agent_id": M1_PROTOCOL["agent_id"],
        "planner_id": M1_PROTOCOL["planner_id"],
        "action_backend_id": M1_PROTOCOL["action_backend_id"],
        "verifier_id": M1_PROTOCOL["verifier_id"],
    }
    events = [
        {"session": session_id, "type": "connect", "data": {"success": True}},
        {
            "session": session_id,
            "type": "benchmark_runtime_profile",
            "data": runtime_profile,
        },
        {
            "session": session_id,
            "type": "benchmark_reset",
            "data": {
                "success": True,
                "task_id": task_id,
                "protocol_sha256": M1_PROTOCOL_SHA256,
                "seed": M1_PROTOCOL["world_seed"],
                "server_jar_sha256": M1_PROTOCOL["server_jar_sha256"],
                "server_brand": "Paper",
                "observed_minecraft_version": M1_PROTOCOL["minecraft_version"],
                "episode_id": session_id,
                "level_name": f"{session_id}_world",
                "after_state": {"inventory": initial_inventory},
                "checks": reset_checks,
            },
        },
        *action_events,
        {"session": session_id, "type": "goal_verification", "data": {"achieved": True, "status": "achieved"}},
        {
            "session": session_id,
            "type": "goal_end",
            "data": {"result": {"completed": True, "termination_reason": "goal_verified"}},
        },
        {
            "session": session_id,
            "type": "benchmark_evidence_validation",
            "data": {"passed": True, "protocol_sha256": M1_PROTOCOL_SHA256},
        },
    ]
    with open(path, "w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")
    return current_inventory, reset_checks, runtime_profile


def _eligible_m1_result(task_id: str, log_path: str, session_id: str) -> dict:
    final_inventory, reset_checks, runtime_profile = _write_m1_live_session(log_path, task_id, session_id)
    spec = M1_TASKS_BY_ID[task_id]
    with open(log_path, "rb") as f:
        session_hash = hashlib.sha256(f.read()).hexdigest()
    return {
        "task_id": task_id,
        "status": "pass",
        "duration_s": 1,
        "log": log_path,
        "session_id": session_id,
        "session_sha256": session_hash,
        "inventory": final_inventory,
        "evidence_kind": "live_minecraft",
        "protocol_eligible": True,
        "goal_verified": True,
        "criteria_verified": True,
        "setup_evidence": {
            "success": True,
            "task_id": task_id,
            "protocol_sha256": M1_PROTOCOL_SHA256,
            "seed": M1_PROTOCOL["world_seed"],
            "server_jar_sha256": M1_PROTOCOL["server_jar_sha256"],
            "server_brand": "Paper",
            "observed_minecraft_version": M1_PROTOCOL["minecraft_version"],
            "episode_id": session_id,
            "level_name": f"{session_id}_world",
            "after_state": {"inventory": dict(spec["initial_inventory"])},
            "checks": reset_checks,
        },
        "evidence_validation": {"passed": True, "protocol_sha256": M1_PROTOCOL_SHA256},
        "runtime_profile": runtime_profile,
    }


def _continual_case(run_number: int, source_root: str) -> dict:
    session_id = f"memory-{run_number}"
    relative_path = f"logs/live-memory-{run_number}.jsonl"
    source_path = os.path.join(source_root, *relative_path.split("/"))
    os.makedirs(os.path.dirname(source_path), exist_ok=True)
    events = [
        {"session": session_id, "type": "skill_learning_runtime_profile", "data": {
            "arm": "runtime",
            "evidence_kind": "live_minecraft_skill_research",
            "protocol_sha256": M1_PROTOCOL_SHA256,
        }},
        {"session": session_id, "type": "benchmark_reset", "data": {
            "success": True,
            "protocol_sha256": M1_PROTOCOL_SHA256,
        }},
        {"session": session_id, "type": "skill_selected", "data": {
            "skill_id": f"learned:test_{run_number}",
        }},
        {"session": session_id, "type": "goal_verification", "data": {
            "achieved": True,
            "status": "achieved",
        }},
        {"session": session_id, "type": "goal_end", "data": {
            "result": {"completed": True, "termination_reason": "goal_verified"},
        }},
        {"session": session_id, "type": "skill_execution_outcome", "data": {
            "success": True,
            "attribution_confidence": 1.0,
        }},
    ]
    with open(source_path, "w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event) + "\n")
    with open(source_path, "rb") as handle:
        source_hash = hashlib.sha256(handle.read()).hexdigest()
    return {
        "source_log": relative_path,
        "source_log_sha256": source_hash,
        "source_session_id": session_id,
        "protocol_sha256": M1_PROTOCOL_SHA256,
        "evidence_kind": "live_minecraft_skill_research",
        "eligibility": True,
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
    assert phases["M1"]["benchmarks"][0]["status"] == "failing"
    assert phases["M1"]["benchmarks"][0]["ineligible_successes"] == 1
    assert "evidence_kind_not_live_minecraft" in phases["M1"]["benchmarks"][0]["ineligibility_reasons"]
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
            task_id = f"BM-{task_number:03d}"
            session_id = f"bm{task_number}-run{run_number}"
            log_path = os.path.join(tmpdir, f"{session_id}.jsonl")
            results.append(_eligible_m1_result(task_id, log_path, session_id))
    copied_log = os.path.join(tmpdir, "copied-bm1-run1.jsonl")
    shutil.copyfile(results[0]["log"], copied_log)
    copied_result = dict(results[0])
    copied_result["log"] = copied_log
    results.append(copied_result)

    forged_log = os.path.join(tmpdir, "forged-no-delta.jsonl")
    forged_result = _eligible_m1_result("BM-001", forged_log, "forged-no-delta")
    forged_events = []
    with open(forged_log, "r", encoding="utf-8") as f:
        for line in f:
            event = json.loads(line)
            if event.get("type") == "action":
                data = event["data"]
                data["post_observation"] = dict(data["pre_observation"])
            forged_events.append(event)
    with open(forged_log, "w", encoding="utf-8") as f:
        for event in forged_events:
            f.write(json.dumps(event) + "\n")
    with open(forged_log, "rb") as f:
        forged_result["session_sha256"] = hashlib.sha256(f.read()).hexdigest()
    results.append(forged_result)

    mixed_server_log = os.path.join(tmpdir, "mixed-server-jar.jsonl")
    mixed_server_result = _eligible_m1_result("BM-001", mixed_server_log, "mixed-server-jar")
    mixed_server_events = []
    with open(mixed_server_log, "r", encoding="utf-8") as f:
        for line in f:
            event = json.loads(line)
            if event.get("type") == "benchmark_reset":
                event["data"]["server_jar_sha256"] = "b" * 64
            mixed_server_events.append(event)
    with open(mixed_server_log, "w", encoding="utf-8") as f:
        for event in mixed_server_events:
            f.write(json.dumps(event) + "\n")
    mixed_server_result["setup_evidence"]["server_jar_sha256"] = "b" * 64
    with open(mixed_server_log, "rb") as f:
        mixed_server_result["session_sha256"] = hashlib.sha256(f.read()).hexdigest()
    results.append(mixed_server_result)
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
    assert all(task["successes"] == 3 for task in m1["benchmarks"])
    assert m1["benchmarks"][0]["attempts"] == 6
    assert m1["benchmarks"][0]["ineligible_successes"] == 3
    assert "duplicate_m1_session" in m1["benchmarks"][0]["ineligibility_reasons"]
    assert "dig_state_transition_unverified" in m1["benchmarks"][0]["ineligibility_reasons"]
    assert "benchmark_server_jar_hash_mismatch" in m1["benchmarks"][0]["ineligibility_reasons"]
    assert all(task["attempts"] == 3 for task in m1["benchmarks"][1:])
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
        "type": "continual_learning_report",
        "schema_version": 2,
        "errors": [],
        "cases": [_continual_case(index, tmpdir) for index in range(1, 4)] + [_continual_case(1, tmpdir)],
    })
    _write_json(m3_gate, {
        "type": "task_stream_transfer_gate",
        "schema_version": 1,
        "readiness": "approved",
        "decision": "allow_candidate_promotion",
        "ready_stream_count": 1,
        "task_count": 4,
        "evidence_count": 1,
        "regression_count": 0,
        "average_generalization_gain": 0.1,
        "thresholds": {"require_heldout": True},
        "heldout_source_session_ids": ["heldout-baseline", "heldout-candidate"],
        "training_heldout_overlap_count": 0,
        "source_report_fingerprint": "a" * 64,
        "protocol_sha256": M1_PROTOCOL_SHA256,
        "evidence_kind": "live_minecraft_skill_research",
        "eligibility": True,
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

    with open(m3_trace, "r", encoding="utf-8") as handle:
        tampered_trace = json.load(handle)
    tampered_trace["cases"][0]["source_log_sha256"] = "0" * 64
    tampered_trace["cases"][-1]["source_log_sha256"] = "0" * 64
    _write_json(m3_trace, tampered_trace)
    tampered_report = build_capability_evidence_report(
        status_path=status_path,
        source_root=tmpdir,
        min_repeats=3,
        phase_evidence_paths={"M3": [m3_trace, m3_gate]},
    )
    tampered_m3 = next(phase for phase in tampered_report["phases"] if phase["id"] == "M3")
    assert tampered_m3["status"] != "repeat_verified"
    assert "source_hash_matches" in tampered_m3["live_evidence"]["primary_cases"][0]["failed_criteria"]
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


def test_repository_capability_documents_match_canonical_report():
    with open("workspace/evals/capability_evidence_current.json", "r", encoding="utf-8") as handle:
        report = json.load(handle)
    audit = audit_capability_document_consistency(report)
    assert audit["consistent"], audit["errors"]
    assert audit["expected"]["M1"] == "repeat_verified"
    assert audit["expected"]["M3"] == "repeat_verified"
    assert report["authority"] == {
        "canonical": True,
        "repo_relative_path": "workspace/evals/capability_evidence_current.json",
        "specialized_reports_are_non_authoritative": True,
    }
    required_fields = {
        "repo_relative_path",
        "session_id",
        "content_sha256",
        "protocol_hash",
        "evidence_kind",
        "eligibility",
    }
    for item in report["evidence_files"]:
        assert required_fields <= set(item), item
        assert all(item[field] not in (None, "") for field in required_fields), item
        assert not os.path.isabs(item["repo_relative_path"]), item
        assert not (len(item["repo_relative_path"]) > 2 and item["repo_relative_path"][1:3] in {":/", ":\\"}), item
        if item.get("counts_toward_repeat_verified"):
            assert len(item["content_sha256"]) == 64, item
            assert len(item["protocol_hash"]) == 64, item
    print("PASS: STATUS, PROGRESS, README, and canonical capability state agree")


if __name__ == "__main__":
    test_capability_evidence_rejects_unsupported_completion_claims()
    test_capability_evidence_requires_distinct_repeated_runs()
    test_live_phase_adapters_require_repeated_grounded_evidence()
    test_live_phase_adapters_reject_weak_or_unlinked_evidence()
    test_live_report_cli_emits_typed_artifacts()
    test_capability_evidence_cli_writes_report()
    test_repository_capability_documents_match_canonical_report()
