"""Bind the retained Probe 53 BM-014 deadline failure and offline repair."""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections import Counter
from pathlib import Path

from singularity.evaluation.m4_protocol import (
    evaluate_m4_episode_for_protocol_hash,
)


ROOT = Path(__file__).resolve().parents[1]
REPORT_RELATIVE = "workspace/evals/m4_probe53_report.json"
REPORT_PATH = ROOT / REPORT_RELATIVE
AUTHORIZATION_PATH = ROOT / "workspace/evals/m4_probe53_authorization.json"


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_blob(commit: str, path: str) -> bytes:
    return subprocess.run(
        ["git", "show", f"{commit}:{Path(path).as_posix()}"],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout


def _report_origin_commit() -> str:
    """Return the commit that first retained this report, if committed."""
    output = subprocess.check_output(
        [
            "git",
            "log",
            "--diff-filter=A",
            "--format=%H",
            "--",
            REPORT_RELATIVE,
        ],
        cwd=ROOT,
        text=True,
    )
    commits = [line.strip() for line in output.splitlines() if line.strip()]
    return commits[-1] if commits else ""


def _events(report: dict) -> list[dict]:
    path = ROOT / report["evidence_paths"]["raw_session_jsonl"]
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_probe53_report_binds_single_use_authorization_and_consumption():
    report = _json(REPORT_PATH)
    authorization = _json(AUTHORIZATION_PATH)
    binding = report["authorization"]
    issued_bytes = _git_blob(binding["commit"], binding["path"])
    issued = json.loads(issued_bytes)

    assert report["type"] == "m4_probe_report"
    assert report["task_id"] == "BM-014"
    assert report["probe_number"] == 53
    assert report["episode_id"] == "m4_episode_20260727_165036_f689d87b"
    assert report["session_id"] == "c44dd8a6-38f"
    assert report["level_name"] == f"{report['episode_id']}_bm014"
    assert subprocess.run(
        ["git", "rev-parse", f"{binding['commit']}^{{tree}}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip() == binding["tree"]
    assert binding["commit"] == "af479de53c8c3332eae96354ef5f5b51d7c93209"
    assert binding["tree"] == "816b5efd5efbaeb6bf94d925536ab254d6f835ef"
    assert hashlib.sha256(issued_bytes).hexdigest() == binding["issued_sha256"]
    assert binding["issued_sha256"] == (
        "5ceee6d5d9e0868bf5397693a27a0dec263f590b658661e4a1bd9e06df21b6f6"
    )
    assert issued["consumed"] is False
    assert issued["one_use"] is True
    assert issued["maximum_episode_count"] == 1
    assert issued["maximum_retry_count"] == 0
    assert issued["prior_bm014_attempt_count"] == 2
    assert issued["prior_bm014_failure_count"] == 1
    assert issued["prior_bm014_eligible_success_count"] == 1
    assert issued["remaining_bm014_eligible_success_count_before_probe"] == 2

    assert _sha256(AUTHORIZATION_PATH) == binding["consumed_sha256"]
    assert binding["consumed_sha256"] == (
        "dcb89d1a31d359e9dad30247cbb3f082e717b0bd802e371d940c2c79f205ceae"
    )
    assert authorization["consumed"] is True
    assert authorization["consumed_by_episode"] == report["episode_id"]
    assert authorization["consumed_session_id"] == report["session_id"]
    assert authorization["consumed_level_name"] == report["level_name"]
    assert authorization["consumed_at"] == "autonomous_start"
    assert authorization["consumed_event_line"] == 2
    assert authorization["consumed_monotonic_s"] == 892493.828
    assert authorization["consumed_at_utc"] == "2026-07-27T08:51:49.862732Z"
    assert authorization["probe_54_authorized"] is False
    assert binding["probe_54_authorized"] is False


def test_probe53_hashes_and_independent_eligibility_recompute_exactly():
    report = _json(REPORT_PATH)
    paths = report["evidence_paths"]
    for name, expected in report["evidence_sha256"].items():
        assert _sha256(ROOT / paths[name]) == expected

    events = _json(ROOT / paths["session_json"])
    result = _json(ROOT / paths["result"])
    preflight = _json(ROOT / paths["preflight"])
    manifest = _json(ROOT / paths["manifest"])
    preparation = _json(ROOT / paths["preparation"])
    saved = _json(ROOT / paths["eligibility"])
    recomputed = evaluate_m4_episode_for_protocol_hash(
        events,
        result,
        preflight,
        manifest,
        "BM-014",
        saved["protocol_sha256"],
    )

    expected_issues = [
        "event:terminal_task_verification",
        "terminal_player_lifecycle",
        "terminal_bot_connected",
        "output_terminal_inventory_target",
        "output_successful_source_actions",
        "output_positive_inventory_delta",
        "terminal_machine_verification",
        "episode_within_deadline",
        "result_duration_eligible",
        "no_post_deadline_execution",
    ]
    assert recomputed == saved
    assert saved["eligible"] is False
    assert saved["success"] is False
    assert saved["issues"] == report["eligibility"]["issues"] == expected_issues
    assert len(saved["checks"]) == report["eligibility"]["check_count"] == 74
    assert sum(check["passed"] is True for check in saved["checks"]) == 64
    assert sum(check["passed"] is False for check in saved["checks"]) == 10
    assert preparation["readiness"] == "review"
    assert preparation["decision"] == "diagnose_first_unrecovered_transition"
    assert preparation["progress_gate_passed"] is False
    assert preparation["counts_toward_task_success"] is False
    assert preparation["evidence_eligible"] is False
    assert len(preparation["autonomous_goals"]) == 9
    assert preparation["action_count"] == 70
    assert preparation["successful_action_count"] == 43
    assert preparation["time_remaining_s"] == 0.0
    assert preparation["first_unrecovered_transition"]["monotonic_s"] == (
        892793.843
    )


def test_probe53_timeline_planner_actions_survival_and_skills_are_bounded():
    report = _json(REPORT_PATH)
    events = _events(report)
    sealed = _json(ROOT / report["evidence_paths"]["session_json"])
    result = _json(ROOT / report["evidence_paths"]["result"])
    manifest = _json(ROOT / report["evidence_paths"]["manifest"])

    assert len(events) == report["episode_result"]["session_event_count"] == 1042
    assert len(sealed) == report["episode_result"]["session_json_event_count"] == 1041
    assert sealed == events[:1041]
    assert events[-1]["type"] == "memory_manage"
    start = events[1]
    assert start["type"] == "autonomous_start"
    assert start["session"] == report["session_id"]
    assert start["monotonic_s"] == manifest["episode_started_monotonic"] == (
        892493.828
    )
    assert manifest["episode_deadline_monotonic"] == 892793.828
    assert manifest["episode_ended_monotonic"] == 892793.843

    autonomous = result["autonomous_result"]
    episode = report["episode_result"]
    assert result["completed"] is False
    assert result["termination_reason"] == "episode_deadline"
    assert result["elapsed_s"] == autonomous["elapsed_s"] == episode["elapsed_s"] == (
        300.015
    )
    assert result["deadline_eligible"] is False
    assert autonomous["goals_completed"] == 8
    assert autonomous["goals_failed"] == 1
    assert autonomous["goals_interrupted"] == 0
    assert autonomous["total_cycles"] == sum(episode["per_goal_cycles"]) == 70
    assert [goal["cycles"] for goal in autonomous["curriculum"]["recent_goals"]] == (
        episode["per_goal_cycles"]
    )

    calls = [event for event in sealed if event["type"] == "llm_planner_call"]
    assert len(calls) == 1
    call = calls[0]["data"]
    assert call["call_id"] == episode["planner_call_id"]
    assert call["real_llm_call"] is True
    assert call["schema_valid"] is True
    assert call["transport_evidence"]["attempt_count"] == 1
    assert call["transport_evidence"]["retry_count"] == 0
    assert call["provider_metadata"]["duration_ms"] == 18640
    assert call["provider_metadata"]["total_tokens"] == 3969

    actions = [event for event in sealed if event["type"] == "action"]
    assert len(actions) == 70
    assert sum(event["data"]["result"]["success"] is True for event in actions) == 43
    assert sum(event["data"]["result"]["success"] is not True for event in actions) == 27
    attempts = Counter(event["data"]["action"]["type"] for event in actions)
    successes = Counter(
        event["data"]["action"]["type"]
        for event in actions
        if event["data"]["result"]["success"] is True
    )
    assert attempts == {
        "move_to": 4,
        "dig": 21,
        "craft": 12,
        "place": 29,
        "equip": 3,
        "smelt": 1,
    }
    assert successes == {
        "move_to": 4,
        "dig": 20,
        "craft": 12,
        "place": 4,
        "equip": 3,
    }

    observations = [event["data"] for event in sealed if event["type"] == "observation"]
    assert len(observations) == report["survival_evidence"]["observation_count"] == 140
    assert min(obs["health"] for obs in observations) == 20
    assert min(obs["hunger"] for obs in observations) == 20
    assert min(
        obs["oxygen"]
        for obs in observations
        if obs.get("oxygen") is not None
    ) == 20
    last = observations[-1]
    assert last["inventory"] == episode["last_trustworthy_inventory"]
    assert last["player_lifecycle"]["death_count"] == 0
    assert last["player_lifecycle"]["respawn_count"] == 0
    assert last["player_lifecycle"]["uninterrupted"] is True
    summary = _json(ROOT / report["evidence_paths"]["session_summary"])
    metrics = summary["skill_learning_metrics"]
    assert summary["error_count"] == 0
    assert metrics["skill_selected_count"] == 0
    assert metrics["skill_executed_count"] == 0
    assert metrics["skill_successful_action_count"] == 0
    assert metrics["skill_failed_action_count"] == 0


def test_probe53_failure_provenance_repair_and_decision_are_bounded():
    report = _json(REPORT_PATH)
    events = _events(report)
    indexed = {index: event for index, event in enumerate(events, start=1)}
    table_failure = report["crafting_table_placement_failure"]
    table_failures = [
        (line, indexed[line])
        for line in table_failure["failure_lines"]
    ]
    assert len(table_failures) == table_failure["occupied_stone_failure_count"] == 24
    for _, event in table_failures:
        assert event["type"] == "action"
        assert event["data"]["action"]["type"] == "place"
        assert event["data"]["action"]["parameters"]["item"] == "crafting_table"
        assert event["data"]["result"]["success"] is False
        assert event["data"]["result"]["error"] == (
            "placement target is occupied by stone"
        )
        evidence = event["data"]["result"]["action_verification"]["evidence"]
        assert "target:not_observed_occupied" in evidence
    assert table_failure["failure_lines"] == [
        454, 469, 484, 499, 514, 529, 544, 559, 574, 589, 765, 780,
        795, 810, 825, 840, 855, 870, 885, 900, 915, 930, 945, 960,
    ]

    furnace = report["furnace_placement_provenance"]
    timeout = indexed[furnace["first_action_line"]]
    recovered = indexed[furnace["recovery_action_line"]]
    assert timeout["data"]["action"]["parameters"] == {
        "item": "furnace",
        **furnace["first_reference_position"],
    }
    assert timeout["data"]["result"]["success"] is False
    assert "blockUpdate:(118, 123, -49)" in timeout["data"]["result"]["error"]
    assert "target:air" in timeout["data"]["result"]["action_verification"]["evidence"]
    assert recovered["data"]["result"]["success"] is True
    assert recovered["data"]["result"]["reference_position"] == (
        furnace["recovery_reference_position"]
    )
    assert recovered["data"]["result"]["placed_position"] == (
        furnace["recovery_target_position"]
    )
    assert recovered["data"]["result"]["target_block_before"]["name"] == "air"
    assert recovered["data"]["result"]["target_block_after"]["name"] == "furnace"

    smelt = report["smelting_deadline_failure"]
    deadline = indexed[report["behavioral_progression"]["first_unrecovered_transition_line"]]
    action = indexed[smelt["action_line"]]
    assert deadline["type"] == "episode_deadline_exceeded"
    assert deadline["data"]["phase"] == "post_action"
    assert deadline["monotonic_s"] == 892793.843
    assert action["data"]["action"]["type"] == "smelt"
    assert action["data"]["result"]["success"] is False
    assert action["data"]["result"]["error"] == smelt["error"]
    assert action["data"]["result"]["command_replayed"] is False
    assert action["data"]["result"]["bridge_reconnected"] is False
    assert action["data"]["result"]["action_started_monotonic"] == 892790.375
    assert action["data"]["result"]["action_finished_monotonic"] == 892793.843
    assert action["data"]["result"]["action_budget_s"] == 3.453
    assert action["data"]["result"]["backend_params"]["timeout_ms"] == 3452
    assert action["data"]["pre_observation"]["inventory"] == (
        action["data"]["post_observation"]["inventory"]
    )

    repair = report["offline_repair"]
    assert repair["policy_id"] == (
        "m4-bm013-bm014-crafting-table-place-local-snapshot-v1"
    )
    assert repair["snapshot_key"] == "m4_crafting_table_place_candidates"
    assert repair["separate_from_furnace_snapshot_envelope"] is True
    assert repair["requires_complete_valid_snapshot_envelope"] is True
    assert repair["requires_exact_integral_reference_target_pair"] is True
    assert repair["action_verifier_exact_pair_hard_required"] is True
    assert repair["missing_forged_stale_wrong_or_unbound_snapshot_rejected"] is True
    assert repair["target_not_observed_occupied_acceptance_possible"] is False
    assert repair["missing_candidate_returns_bounded_block"] is True
    assert repair["full_think_fallback_suppressed"] is True
    assert repair["suppressed_execution_paths"] == [
        "learned_skill",
        "bm012_machine_step",
        "llm_plan",
        "rule_plan",
        "visual_action_grounding",
    ]
    assert repair["bm012_generic_crafting_table_behavior_unchanged"] is True
    assert repair["furnace_local_snapshot_policy_unchanged"] is True
    assert repair["focused_python_pass_count"] == 21
    origin_commit = _report_origin_commit()
    for key, relative_path in repair["source_paths"].items():
        source_bytes = (
            _git_blob(origin_commit, relative_path)
            if origin_commit
            else (ROOT / relative_path).read_bytes()
        )
        assert repair["source_sha256"][key] == hashlib.sha256(
            source_bytes
        ).hexdigest()

    audit_path = ROOT / repair["repair_audit_path"]
    assert repair["repair_audit_sha256"] != "pending"
    assert repair["repair_audit_sha256"] == _sha256(audit_path)
    audit = _json(audit_path)
    assert audit["source_sha256"] == repair["source_sha256"]
    assert audit["offline_validation"]["focused_python_pass_count"] == 21

    decision = report["decision"]
    assert decision["counts_toward_bm014_success"] is False
    assert decision["bm014_attempt_count_before"] == 2
    assert decision["bm014_attempt_count_after"] == 3
    assert decision["bm014_failure_count_before"] == 1
    assert decision["bm014_failure_count_after"] == 2
    assert decision["bm014_success_count_before"] == 1
    assert decision["bm014_success_count_after"] == 1
    assert decision["remaining_success_count"] == 2
    assert decision["bm014_status_after"] == "live_observed"
    assert decision["m4_status_after"] == "live_observed"
    assert decision["probe_54_authorized"] is False
