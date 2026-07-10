"""Tests for fixed-budget task-frontier allocation and runtime gating."""

import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from singularity.core.agent import Agent
from singularity.core.config import Config
from singularity.core.curriculum import CurriculumManager
from singularity.core.episode_abort import EpisodeAbortDecision
from singularity.core.frontier_budget import (
    FrontierBudgetController,
    allocate_frontier_budget,
    build_frontier_branches,
    build_frontier_rollout_budget_gate,
    compare_frontier_allocations,
    evaluate_frontier_budget_runtime_gate,
    frontier_branch_id,
    frontier_budget_trace_payload,
    validate_frontier_budget_gate_payload,
    write_frontier_rollout_budget_gate,
)
from singularity.core.task_system import TaskSystem


CONTROLS = {
    "planner_id": "rule-based-v1",
    "action_backend": "mineflayer-bridge-v1",
    "verifier_id": "goal-action-verifier-v1",
    "task_stream_id": "frontier-budget-test-stream",
    "seed": "frontier-budget-seed",
}


class FakeSessionLogger:
    def __init__(self):
        self.events = []
        self.session_id = "frontier-test-session"

    def log(self, event_type, data, level="INFO"):
        self.events.append({"session": self.session_id, "type": event_type, "data": data, "level": level})


def _branch(title, closes=0, novelty=0, risk=0, eligible=True, ready=True, low=1, high=4):
    return {
        "branch_id": frontier_branch_id(title, "test"),
        "title": title,
        "source": "test",
        "category": "frontier",
        "ready": ready,
        "eligible": eligible,
        "safety_reserved": False,
        "priority_signal": 0.5,
        "signals": {
            "closes_precondition_count": closes,
            "novelty_count": novelty,
            "risk_count": risk,
        },
        "estimated_rounds_low": low,
        "estimated_rounds_high": high,
    }


def _live_pairs(count=12):
    target_title = "Mine visible coal"
    target_id = frontier_branch_id(target_title, "test")
    branches = [
        _branch(target_title, closes=2, low=2, high=4),
        _branch("Scout another landmark", novelty=1, risk=1, low=2, high=5),
        _branch("Craft torches", eligible=False, ready=False),
    ]
    pairs = []
    for index in range(count):
        pairs.append({
            "pair_id": f"live-pair-{index:03d}",
            "baseline_session_id": f"uniform-live-{index:03d}",
            "candidate_session_id": f"information-live-{index:03d}",
            "connected": {"baseline": True, "candidate": True},
            "complete_boundary": {"baseline": True, "candidate": True},
            "provenance": CONTROLS,
            "total_rounds": 8,
            "consumed_rounds": 0,
            "recovered_rounds": 0,
            "branches": branches,
            "baseline_outcome": {
                "goal_completed": False,
                "planner_rounds_used": 8,
                "verifier_event_count": 2,
                "verifier_reject_count": 1,
                "action_event_count": 4,
                "action_failure_count": 2,
                "unsafe_action_count": 0,
                "action_verification_enforced": True,
                "resolved_branch_ids": [],
            },
            "candidate_outcome": {
                "goal_completed": True,
                "planner_rounds_used": 3,
                "verifier_event_count": 2,
                "verifier_reject_count": 0,
                "action_event_count": 3,
                "action_failure_count": 0,
                "unsafe_action_count": 0,
                "action_verification_enforced": True,
                "resolved_branch_ids": [target_id],
                "actual_rounds_by_branch": {target_id: 3},
            },
        })
    return pairs


def _write_jsonl(path, events):
    with open(path, "w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event) + "\n")


def _live_log_pairs(tmpdir, count=12, recovered_rounds=0):
    target_title = "Mine visible coal"
    target_id = frontier_branch_id(target_title, "test")
    branches = [
        _branch(target_title, closes=2, low=2, high=4),
        _branch("Scout another landmark", novelty=1, risk=1, low=2, high=5),
        _branch("Craft torches", eligible=False, ready=False),
    ]
    baseline_paths = []
    candidate_paths = []
    for index in range(count):
        baseline_session = f"uniform-live-{index:03d}"
        candidate_session = f"information-live-{index:03d}"
        baseline_path = os.path.join(tmpdir, f"baseline_{index:03d}.jsonl")
        candidate_path = os.path.join(tmpdir, f"candidate_{index:03d}.jsonl")
        uniform = allocate_frontier_budget(branches, 8, recovered_rounds=recovered_rounds, policy="uniform")
        information = allocate_frontier_budget(branches, 8, recovered_rounds=recovered_rounds, policy="information")
        for allocation in (uniform, information):
            allocation["selected_branch_id"] = target_id
            allocation["selected_goal_fingerprint"] = f"goal-{index:03d}"
            if recovered_rounds:
                allocation["reallocation_source"] = "certified_episode_early_abort"
                allocation["source_abort_event_fingerprint"] = f"{index:016x}"
                allocation["episode_abort_gate_integrity_sha256"] = "b" * 64
        baseline_allocation = frontier_budget_trace_payload(uniform, provenance=CONTROLS)
        candidate_allocation = frontier_budget_trace_payload(information, provenance=CONTROLS)
        baseline_outcome = {
            "goal_completed": False,
            "planner_rounds_used": 8,
            "verifier_event_count": 2,
            "verifier_reject_count": 1,
            "action_event_count": 4,
            "action_failure_count": 2,
            "unsafe_action_count": 0,
            "action_verification_enforced": True,
            "resolved_branch_ids": [],
            "actual_rounds_by_branch": {},
        }
        candidate_outcome = {
            "goal_completed": True,
            "planner_rounds_used": 3,
            "verifier_event_count": 2,
            "verifier_reject_count": 0,
            "action_event_count": 3,
            "action_failure_count": 0,
            "unsafe_action_count": 0,
            "action_verification_enforced": True,
            "resolved_branch_ids": [target_id],
            "actual_rounds_by_branch": {target_id: 3},
        }
        _write_jsonl(baseline_path, [
            {"session": baseline_session, "type": "connect", "data": {"success": True}},
            {"session": baseline_session, "type": "frontier_budget_allocation", "data": baseline_allocation},
            {"session": baseline_session, "type": "frontier_budget_outcome", "data": baseline_outcome},
            {"session": baseline_session, "type": "goal_end", "data": {"result": {"completed": False}}},
        ])
        _write_jsonl(candidate_path, [
            {"session": candidate_session, "type": "connect", "data": {"success": True}},
            {"session": candidate_session, "type": "frontier_budget_allocation", "data": candidate_allocation},
            {"session": candidate_session, "type": "frontier_budget_outcome", "data": candidate_outcome},
            {"session": candidate_session, "type": "goal_end", "data": {"result": {"completed": True}}},
        ])
        baseline_paths.append(baseline_path)
        candidate_paths.append(candidate_path)
    return baseline_paths, candidate_paths


def test_information_allocation_conserves_fixed_budget_and_differs_from_uniform():
    branches = [
        _branch("Resolve missing coal", closes=2, low=2, high=4),
        _branch("Inspect novel landmark", novelty=1, risk=1, low=2, high=5),
        _branch("Blocked craft", eligible=False, ready=False),
    ]
    comparison = compare_frontier_allocations(branches, total_rounds=8)

    assert comparison["both_budgets_conserved"] is True
    assert comparison["changed_branch_count"] >= 2
    assert comparison["uniform"]["ledger"]["allocated_rounds"] == 8
    assert comparison["information"]["ledger"]["allocated_rounds"] == 8
    info = {item["title"]: item for item in comparison["information"]["branches"]}
    assert info["Resolve missing coal"]["allocated_rounds"] > info["Inspect novel landmark"]["allocated_rounds"]
    assert info["Blocked craft"]["allocated_rounds"] == 0
    assert comparison["information"]["automatic_retry_allowed"] is False
    assert comparison["information"]["automatic_branch_execution_allowed"] is False
    print("PASS: Information allocation conserves fixed budget and differs from uniform")


def test_recovered_rounds_are_a_subpool_not_budget_extension():
    branches = [_branch("Resolve prerequisite", closes=2), _branch("Explore landmark", novelty=1)]
    allocation = allocate_frontier_budget(
        branches,
        total_rounds=8,
        consumed_rounds=3,
        recovered_rounds=4,
        policy="information",
    )

    assert allocation["ledger"]["available_rounds"] == 5
    assert allocation["ledger"]["allocation_pool_rounds"] == 4
    assert allocation["ledger"]["allocated_rounds"] == 4
    assert allocation["ledger"]["budget_extended"] is False
    assert allocation["ledger"]["conservation_valid"] is True
    print("PASS: Recovered rounds remain a subpool of the fixed ledger")


def test_frontier_projection_rewards_typed_prerequisite_closure():
    selected = "Mine coal for torches"
    branches = build_frontier_branches(
        curriculum_candidates=[
            {
                "title": selected,
                "category": "resource",
                "score": 50,
                "target_items": ["coal"],
                "reasons": ["frontier_resource_opportunity"],
            },
            {
                "title": "Scout nearby landmark",
                "category": "exploration",
                "score": 48,
                "target_items": ["landmark"],
                "reasons": ["novelty"],
            },
        ],
        task_readiness={
            "tasks": [{
                "id": "craft-torches",
                "title": "Craft torches",
                "type": "crafting",
                "ready": False,
                "score": 1,
                "missing_preconditions": {"inventory": {"coal": 1}},
                "success_criteria": {"inventory": {"torch": 4}},
            }],
        },
        observation={"inventory": {"stick": 1}},
        selected_goal=selected,
    )
    projected = {item["title"]: item for item in branches}

    assert projected[selected]["signals"]["closes_precondition_count"] == 1
    assert projected[selected]["selected"] is True
    assert projected["Craft torches"]["eligible"] is False
    print("PASS: Frontier projection rewards typed prerequisite closure")


def test_synthetic_gate_allows_shadow_but_never_advisory():
    report = build_frontier_rollout_budget_gate(
        include_builtins=True,
        evidence_kind="synthetic_control",
        total_rounds=8,
        planner_id="builtin-fixed-planner-v1",
        action_backend="synthetic-no-execution",
        verifier_id="builtin-milestone-verifier-v1",
        task_stream_id="builtin-frontier-budget",
        seed="builtin-20260710",
    )

    assert report["readiness"] == "review"
    assert report["shadow_allocation_allowed"] is True
    assert report["advisory_context_allowed"] is False
    assert report["runtime_eligible"] is False
    assert report["allocation_metrics"]["all_pairs_budget_conserved"] is True
    assert report["allocation_metrics"]["mean_candidate_resolution_targeting_gain"] > 0
    validate_frontier_budget_gate_payload(report)
    print("PASS: Synthetic frontier gate remains shadow-only")


def test_live_paired_gate_requires_interval_certificate_and_matches_runtime():
    tmpdir = tempfile.mkdtemp()
    gate_path = os.path.join(tmpdir, "frontier_gate.json")
    baseline_paths, candidate_paths = _live_log_pairs(tmpdir)

    report = build_frontier_rollout_budget_gate(
        baseline_log_paths=baseline_paths,
        candidate_log_paths=candidate_paths,
        evidence_kind="live_trace",
        total_rounds=8,
        temperature=2.0,
        exploration_floor=1,
        min_live_pairs=3,
        min_interval_observations=12,
        target_interval_coverage=0.75,
        planner_id=CONTROLS["planner_id"],
        action_backend=CONTROLS["action_backend"],
        verifier_id=CONTROLS["verifier_id"],
        task_stream_id=CONTROLS["task_stream_id"],
        seed=CONTROLS["seed"],
    )

    assert report["readiness"] == "approved", report
    assert report["advisory_context_allowed"] is True
    assert report["interval_metrics"]["coverage_lower_bound"] >= 0.75
    assert report["interval_metrics"]["calibrated_on_held_out_pairs"] is True
    validate_frontier_budget_gate_payload(report)
    write_frontier_rollout_budget_gate(report, gate_path)
    runtime = evaluate_frontier_budget_runtime_gate(
        [gate_path],
        requested_mode="advisory",
        runtime_provenance={
            **CONTROLS,
            "policy": "information",
            "total_rounds": 8,
            "temperature": 2.0,
            "exploration_floor": 1,
            "action_verification_enforced": True,
        },
    )
    mismatch = evaluate_frontier_budget_runtime_gate(
        [gate_path],
        requested_mode="advisory",
        runtime_provenance={
            **CONTROLS,
            "seed": "different-seed",
            "policy": "information",
            "total_rounds": 8,
            "temperature": 2.0,
            "exploration_floor": 1,
            "action_verification_enforced": True,
        },
    )
    uniform_runtime = evaluate_frontier_budget_runtime_gate(
        [gate_path],
        requested_mode="advisory",
        runtime_provenance={
            **CONTROLS,
            "policy": "uniform",
            "total_rounds": 8,
            "temperature": 2.0,
            "exploration_floor": 1,
            "action_verification_enforced": True,
        },
    )
    unverified_runtime = evaluate_frontier_budget_runtime_gate(
        [gate_path],
        requested_mode="advisory",
        runtime_provenance={
            **CONTROLS,
            "policy": "information",
            "total_rounds": 8,
            "temperature": 2.0,
            "exploration_floor": 1,
            "action_verification_enforced": False,
        },
    )

    assert runtime["effective_mode"] == "advisory"
    assert runtime["provenance_match"] is True
    assert mismatch["effective_mode"] == "off"
    assert mismatch["gate_readiness"] == "rejected"
    assert uniform_runtime["effective_mode"] == "off"
    assert uniform_runtime["provenance_match"] is False
    assert unverified_runtime["effective_mode"] == "off"
    assert unverified_runtime["provenance_match"] is False
    print("PASS: Live paired gate requires interval certificate and exact runtime controls")


def test_structured_cases_cannot_impersonate_live_session_logs():
    tmpdir = tempfile.mkdtemp()
    case_path = os.path.join(tmpdir, "claimed_live_pairs.json")
    with open(case_path, "w", encoding="utf-8") as handle:
        json.dump(_live_pairs(), handle)

    report = build_frontier_rollout_budget_gate(
        case_paths=[case_path],
        evidence_kind="live_trace",
        total_rounds=8,
        min_interval_observations=12,
        target_interval_coverage=0.75,
        planner_id=CONTROLS["planner_id"],
        action_backend=CONTROLS["action_backend"],
        verifier_id=CONTROLS["verifier_id"],
        task_stream_id=CONTROLS["task_stream_id"],
        seed=CONTROLS["seed"],
    )

    assert report["runtime_eligible"] is False
    assert report["advisory_context_allowed"] is False
    assert report["evidence_integrity"]["session_log_evidence_only"] is False
    assert "paired_session_log_evidence" in report["missing"]
    print("PASS: Structured cases cannot impersonate live session logs")


def test_recovered_live_budget_requires_abort_gate_and_credit_event():
    tmpdir = tempfile.mkdtemp()
    baseline_paths, candidate_paths = _live_log_pairs(tmpdir, recovered_rounds=4)
    report = build_frontier_rollout_budget_gate(
        baseline_log_paths=baseline_paths,
        candidate_log_paths=candidate_paths,
        evidence_kind="live_trace",
        total_rounds=8,
        min_interval_observations=12,
        target_interval_coverage=0.75,
        planner_id=CONTROLS["planner_id"],
        action_backend=CONTROLS["action_backend"],
        verifier_id=CONTROLS["verifier_id"],
        task_stream_id=CONTROLS["task_stream_id"],
        seed=CONTROLS["seed"],
    )

    certification = next(check for check in report["checks"] if check["name"] == "recovered_budget_is_certified")
    assert report["readiness"] == "rejected"
    assert report["advisory_context_allowed"] is False
    assert report["allocation_metrics"]["recovered_budget_pair_count"] == 12
    assert report["allocation_metrics"]["certified_recovered_budget_pair_count"] == 0
    assert certification["status"] == "fail"
    print("PASS: Recovered live budget requires abort gate and credit event")


def test_gate_integrity_rejects_tampering():
    report = build_frontier_rollout_budget_gate(
        include_builtins=True,
        evidence_kind="synthetic_control",
        total_rounds=8,
        planner_id="builtin-fixed-planner-v1",
        action_backend="synthetic-no-execution",
        verifier_id="builtin-milestone-verifier-v1",
        task_stream_id="builtin-frontier-budget",
        seed="builtin-20260710",
    )
    report["allocation_config"]["total_rounds"] = 9
    try:
        validate_frontier_budget_gate_payload(report)
    except ValueError as exc:
        assert "integrity" in str(exc)
    else:
        raise AssertionError("tampered frontier budget gate was accepted")
    print("PASS: Frontier budget gate integrity rejects tampering")


def test_agent_shadow_allocation_does_not_enter_planner_context():
    agent = object.__new__(Agent)
    agent.config = Config(frontier_budget_mode="shadow")
    agent.session_logger = FakeSessionLogger()
    agent.curriculum = CurriculumManager()
    agent.task_system = TaskSystem()
    agent.frontier_budget_controller = FrontierBudgetController(
        {"effective_mode": "shadow"},
        policy="information",
        total_rounds=8,
    )
    agent.frontier_budget_runtime_provenance = {
        **CONTROLS,
        "total_rounds": 8,
        "temperature": 2.0,
        "exploration_floor": 1,
    }
    agent._frontier_budget_recovery_credit = {}
    decision = {
        "selected": "Mine visible coal",
        "candidates": [
            {
                "title": "Mine visible coal",
                "category": "resource",
                "score": 55,
                "target_items": ["coal"],
                "reasons": ["frontier_resource_opportunity"],
            },
            {
                "title": "Scout landmark",
                "category": "exploration",
                "score": 40,
                "target_items": ["landmark"],
                "reasons": ["novelty"],
            },
        ],
    }
    allocation = agent._record_frontier_budget_decision(
        {"inventory": {}},
        "Mine visible coal",
        decision=decision,
        readiness_report={"tasks": []},
    )

    assert allocation["ledger"]["conservation_valid"] is True
    assert any(event["type"] == "frontier_budget_allocation" for event in agent.session_logger.events)
    assert agent._frontier_budget_context("Mine visible coal") == ""
    agent.frontier_budget_controller.runtime_mode = "advisory"
    context = agent._frontier_budget_context("Mine visible coal")
    assert "Frontier planner-round budget" in context
    assert "cannot retry" in context
    print("PASS: Agent shadow allocation stays out of planner context")


def test_active_episode_abort_creates_bounded_recovery_credit():
    class Monitor:
        enabled = True

        @staticmethod
        def evaluate(events, cycle):
            return EpisodeAbortDecision(
                evaluated=True,
                round_index=cycle,
                score=0.9,
                threshold=0.5,
                would_abort=True,
                active_abort=True,
                runtime_mode="active",
                reason="risk_above_threshold",
            )

    agent = object.__new__(Agent)
    agent.episode_abort_monitor = Monitor()
    agent.episode_abort_runtime_gate_report = {"gate_integrity_sha256": "a" * 64}
    agent.session_logger = FakeSessionLogger()
    agent._write_memory_episode = lambda *args, **kwargs: None
    agent._frontier_budget_recovery_credit = {}

    aborted = agent._evaluate_episode_abort("Mine iron", 3, "autonomous", round_limit=8)

    assert aborted is True
    assert agent._frontier_budget_recovery_credit["remaining_rounds"] == 5
    credit = next(event for event in agent.session_logger.events if event["type"] == "frontier_budget_recovery_credit")
    assert credit["data"]["saved_planner_rounds"] == 5
    assert credit["data"]["budget_extended"] is False
    print("PASS: Active episode abort creates bounded recovery credit")


def test_frontier_budget_cli_writes_shadow_report():
    tmpdir = tempfile.mkdtemp()
    output_path = os.path.join(tmpdir, "frontier_budget.json")
    env = os.environ.copy()
    env["PYTHONPATH"] = "src"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "singularity.main",
            "frontier-rollout-budget-report",
            "--include-builtins",
            "--evidence-kind",
            "synthetic_control",
            "--planner-id",
            "builtin-fixed-planner-v1",
            "--action-backend",
            "synthetic-no-execution",
            "--verifier-id",
            "builtin-milestone-verifier-v1",
            "--task-stream-id",
            "builtin-frontier-budget",
            "--seed",
            "builtin-20260710",
            "--output",
            output_path,
        ],
        cwd=os.getcwd(),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    with open(output_path, "r", encoding="utf-8") as handle:
        report = json.load(handle)
    assert report["type"] == "frontier_rollout_budget_gate"
    assert report["readiness"] == "review"
    assert "Frontier Rollout Budget Report" in result.stdout
    print("PASS: Frontier budget CLI writes shadow report")


if __name__ == "__main__":
    test_information_allocation_conserves_fixed_budget_and_differs_from_uniform()
    test_recovered_rounds_are_a_subpool_not_budget_extension()
    test_frontier_projection_rewards_typed_prerequisite_closure()
    test_synthetic_gate_allows_shadow_but_never_advisory()
    test_live_paired_gate_requires_interval_certificate_and_matches_runtime()
    test_structured_cases_cannot_impersonate_live_session_logs()
    test_recovered_live_budget_requires_abort_gate_and_credit_event()
    test_gate_integrity_rejects_tampering()
    test_agent_shadow_allocation_does_not_enter_planner_context()
    test_active_episode_abort_creates_bounded_recovery_credit()
    test_frontier_budget_cli_writes_shadow_report()
    print("\nFrontier budget tests PASSED")
