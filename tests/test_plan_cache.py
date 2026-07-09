"""Tests for AgenticCache-style plan-transition cache."""
import json
import os
import sys
import tempfile

sys.path.insert(0, "src")

from singularity.core.agent import Agent
from singularity.core.config import Config
from singularity.core.plan_cache import (
    START_PLAN_SIGNATURE,
    PlanTransitionCache,
    build_plan_cache_gate,
    build_plan_cache_runtime_report,
    build_plan_transition_cache_report,
    evaluate_plan_cache_runtime_gate,
    plan_signature,
    write_plan_transition_cache_report,
)
from singularity.core.runtime_profile import build_runtime_profile_payload, build_runtime_profile_report


def _write_session_log(path: str):
    events = [
        {"type": "goal_start", "data": {"goal": "Craft torches"}},
        {
            "type": "observation",
            "data": {
                "inventory": {"coal": 1, "stick": 2},
                "nearby_blocks": ["crafting_table"],
                "health": 20,
            },
        },
        {
            "type": "plan",
            "data": {
                "status": "planning",
                "reasoning": "Craft torches from coal and sticks",
                "subtasks": [{
                    "title": "Craft torches",
                    "type": "crafting",
                    "priority": 1,
                    "success_criteria": {"inventory": {"torch": 4}},
                }],
                "actions": [{"type": "craft", "parameters": {"item": "torch", "count": 4}}],
            },
        },
        {
            "type": "action",
            "data": {
                "action": {"type": "craft", "parameters": {"item": "torch", "count": 4}},
                "result": {"success": True, "item": "torch"},
            },
        },
        {"type": "goal_end", "data": {"goal": "Craft torches", "result": {"completed": True}}},
    ]
    with open(path, "w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")


def _write_runtime_cache_log(path: str, entry_id: str):
    events = [
        {"type": "goal_start", "data": {"goal": "Craft torches"}},
        {
            "type": "plan_cache_hit",
            "data": {
                "goal": "Craft torches",
                "entry_id": entry_id,
                "confidence": 0.9,
                "state_similarity": 1.0,
            },
        },
        {
            "type": "plan_cache_signature",
            "data": {
                "goal": "Craft torches",
                "source": "plan_transition_cache",
                "plan_signature": "sig",
                "action_count": 1,
            },
        },
        {
            "type": "plan",
            "data": {
                "status": "planning",
                "source": "plan_transition_cache",
                "cache_entry_id": entry_id,
                "actions": [{"type": "craft", "parameters": {"item": "torch", "count": 4}}],
            },
        },
        {
            "type": "action_verification",
            "data": {
                "verification": {"status": "accept", "action_type": "craft"},
                "action": {"type": "craft", "parameters": {"item": "torch", "count": 4}},
            },
        },
        {
            "type": "action",
            "data": {
                "action": {"type": "craft", "parameters": {"item": "torch", "count": 4}},
                "result": {"success": True, "item": "torch"},
            },
        },
        {"type": "goal_end", "data": {"goal": "Craft torches", "result": {"completed": True}}},
    ]
    with open(path, "w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")


class NoCallPlanner:
    def __init__(self):
        self.called = False
        self.created = []

    def plan_from_goal(self, goal, world_state, memory_context=""):
        self.called = True
        raise AssertionError("planner should not be called on plan-cache hit")

    def _create_tasks_from_plan(self, plan):
        self.created.append(plan)


def test_plan_cache_report_builds_runtime_entry():
    tmpdir = tempfile.mkdtemp()
    log_path = os.path.join(tmpdir, "session.jsonl")
    _write_session_log(log_path)

    report = build_plan_transition_cache_report([log_path], min_support=1, min_success_rate=0.6)
    assert report["type"] == "plan_transition_cache_report"
    assert report["readiness"] == "approved"
    assert report["accepted_entry_count"] == 1
    entry = report["entries"][0]
    assert entry["accepted_for_runtime"] is True
    assert entry["previous_plan_signature"] == START_PLAN_SIGNATURE
    assert entry["plan"]["actions"][0]["type"] == "craft"
    print("PASS: Plan cache report builds runtime entry")


def test_plan_transition_cache_hits_matching_context():
    tmpdir = tempfile.mkdtemp()
    log_path = os.path.join(tmpdir, "session.jsonl")
    report_path = os.path.join(tmpdir, "plan_cache.json")
    _write_session_log(log_path)
    report = build_plan_transition_cache_report([log_path], min_support=1, min_success_rate=0.6)
    write_plan_transition_cache_report(report, report_path)

    cache = PlanTransitionCache(min_confidence=0.4)
    loaded = cache.load_reports([report_path])
    assert loaded["loaded_entry_count"] == 1
    hit = cache.query(
        "Craft torches",
        {"inventory": {"coal": 1, "stick": 2}, "nearby_blocks": ["crafting_table"], "health": 20},
        START_PLAN_SIGNATURE,
    )
    assert hit
    assert hit["plan"]["source"] == "plan_transition_cache"
    assert hit["plan"]["actions"][0]["parameters"]["item"] == "torch"
    print("PASS: Plan transition cache hits matching context")


def test_plan_transition_cache_skips_unapproved_reports():
    tmpdir = tempfile.mkdtemp()
    log_path = os.path.join(tmpdir, "session.jsonl")
    report_path = os.path.join(tmpdir, "plan_cache_review.json")
    _write_session_log(log_path)
    report = build_plan_transition_cache_report([log_path], min_support=1, min_success_rate=0.6)
    report["readiness"] = "review"
    report["decision"] = "hold_plan_transition_cache"
    write_plan_transition_cache_report(report, report_path)

    cache = PlanTransitionCache(min_confidence=0.4)
    loaded = cache.load_reports([report_path])
    assert loaded["approved_report_count"] == 0
    assert loaded["loaded_entry_count"] == 0
    assert loaded["skipped_entry_count"] == 1
    print("PASS: Plan transition cache skips unapproved reports")


def test_plan_cache_runtime_report_and_gate_approve_safe_hits():
    tmpdir = tempfile.mkdtemp()
    log_path = os.path.join(tmpdir, "session.jsonl")
    cache_report_path = os.path.join(tmpdir, "plan_cache.json")
    runtime_log_path = os.path.join(tmpdir, "runtime.jsonl")
    runtime_report_path = os.path.join(tmpdir, "plan_cache_runtime.json")
    gate_path = os.path.join(tmpdir, "plan_cache_gate.json")
    _write_session_log(log_path)
    cache_report = build_plan_transition_cache_report([log_path], min_support=1, min_success_rate=0.6)
    write_plan_transition_cache_report(cache_report, cache_report_path)
    entry_id = cache_report["entries"][0]["id"]
    _write_runtime_cache_log(runtime_log_path, entry_id)

    runtime_report = build_plan_cache_runtime_report([runtime_log_path])
    assert runtime_report["readiness"] == "approved"
    assert runtime_report["plan_cache_hit_count"] == 1
    assert runtime_report["post_hit_action_verification_reject_count"] == 0
    write_plan_transition_cache_report(runtime_report, runtime_report_path)

    gate = build_plan_cache_gate(
        cache_report_paths=[cache_report_path],
        runtime_report_paths=[runtime_report_path],
        min_runtime_hits=1,
    )
    assert gate["readiness"] == "approved"
    assert gate["runtime_hit_count"] == 1
    write_plan_transition_cache_report(gate, gate_path)
    runtime_gate = evaluate_plan_cache_runtime_gate([gate_path], enable_requested=True)
    assert runtime_gate["effective_enable_plan_cache"] is True
    print("PASS: Plan cache runtime report and gate approve safe hits")


def test_agent_uses_plan_cache_before_llm_planner():
    tmpdir = tempfile.mkdtemp()
    log_path = os.path.join(tmpdir, "session.jsonl")
    report_path = os.path.join(tmpdir, "plan_cache.json")
    gate_path = os.path.join(tmpdir, "plan_cache_gate.json")
    _write_session_log(log_path)
    report = build_plan_transition_cache_report([log_path], min_support=1, min_success_rate=0.6)
    write_plan_transition_cache_report(report, report_path)
    gate = build_plan_cache_gate([report_path])
    write_plan_transition_cache_report(gate, gate_path)

    agent = Agent(Config(
        memory_dir=os.path.join(tmpdir, "memory"),
        skill_dir=os.path.join(tmpdir, "skills"),
        log_dir=tmpdir,
        enable_plan_cache=True,
        plan_cache_paths=[report_path],
        plan_cache_gate_paths=[gate_path],
        plan_cache_min_confidence=0.4,
    ))
    planner = NoCallPlanner()
    agent.planner = planner
    agent._use_llm = True
    agent.current_goal = "Craft torches"
    plan = agent._think({
        "inventory": {"coal": 1, "stick": 2},
        "nearby_blocks": ["crafting_table"],
        "health": 20,
    })
    assert plan["source"] == "plan_transition_cache"
    assert planner.called is False
    assert planner.created
    summary = agent.session_logger.get_summary()
    assert summary["plan_cache_metrics"]["plan_cache_hit_count"] == 1
    assert plan_signature(plan) == agent._last_plan_cache_signature
    print("PASS: Agent uses plan cache before LLM planner")


def test_agent_skips_plan_cache_without_gate():
    tmpdir = tempfile.mkdtemp()
    log_path = os.path.join(tmpdir, "session.jsonl")
    report_path = os.path.join(tmpdir, "plan_cache.json")
    _write_session_log(log_path)
    report = build_plan_transition_cache_report([log_path], min_support=1, min_success_rate=0.6)
    write_plan_transition_cache_report(report, report_path)

    agent = Agent(Config(
        memory_dir=os.path.join(tmpdir, "memory"),
        skill_dir=os.path.join(tmpdir, "skills"),
        log_dir=tmpdir,
        enable_plan_cache=True,
        plan_cache_paths=[report_path],
        plan_cache_min_confidence=0.4,
    ))
    assert agent.plan_cache_runtime_gate_report["effective_enable_plan_cache"] is False
    assert agent.plan_cache_report["loaded_entry_count"] == 0
    assert len(agent.plan_cache.entries) == 0
    print("PASS: Agent skips plan cache without gate")


def test_runtime_profile_requires_plan_cache_artifact_when_enabled():
    tmpdir = tempfile.mkdtemp()
    profile_path = os.path.join(tmpdir, "runtime_profile_plan_cache.json")
    profile = build_runtime_profile_payload(
        name="plan_cache_profile",
        settings={"enable_plan_cache": True},
        path_fields={},
    )
    with open(profile_path, "w", encoding="utf-8") as f:
        json.dump(profile, f)

    report = build_runtime_profile_report([profile_path])
    assert report["readiness"] == "review"
    assert "plan_cache_paths" in report["missing"]
    assert "plan_cache_gate_paths" in report["missing"]
    print("PASS: Runtime profile requires plan cache artifact and gate when enabled")


if __name__ == "__main__":
    test_plan_cache_report_builds_runtime_entry()
    test_plan_transition_cache_hits_matching_context()
    test_plan_transition_cache_skips_unapproved_reports()
    test_plan_cache_runtime_report_and_gate_approve_safe_hits()
    test_agent_uses_plan_cache_before_llm_planner()
    test_agent_skips_plan_cache_without_gate()
    test_runtime_profile_requires_plan_cache_artifact_when_enabled()
    print("\nPlan cache tests PASSED")
