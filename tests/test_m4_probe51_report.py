"""Bind the retained Probe 51 BM-014 failure report to raw machine evidence."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from singularity.evaluation.m4_protocol import evaluate_m4_episode


ROOT = Path(__file__).resolve().parent.parent
REPORT_PATH = ROOT / "workspace/evals/m4_probe51_report.json"
AUTHORIZATION_PATH = ROOT / "workspace/evals/m4_probe51_authorization.json"
FURNACE_REPAIR_COMMIT = "0d97e4314c454fa8408b6ad56d8aff263f07d28e"


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _events(report: dict) -> list[dict]:
    path = ROOT / report["evidence_paths"]["raw_session_jsonl"]
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _issued_authorization_bytes(report: dict) -> bytes:
    authorization = report["authorization"]
    return subprocess.check_output(
        [
            "git",
            "show",
            f"{authorization['commit']}:{authorization['path']}",
        ],
        cwd=ROOT,
    )


def test_probe51_pre_episode_infrastructure_blocker_did_not_consume_authorization():
    report = _json(REPORT_PATH)
    blocker = report["pre_episode_infrastructure_blocker"]
    evidence_dir = ROOT / blocker["evidence_dir"]
    preflight = _json(ROOT / blocker["preflight_path"])

    assert blocker["observed_python_version"] == "3.13.5"
    assert blocker["required_python_version"] == "3.12.8"
    assert preflight["passed"] is False
    assert preflight["runtime_versions"]["python"] == "3.13.5"
    assert preflight["validation"]["passed"] is False
    assert preflight["validation"]["issues"] == ["runtime_versions"]
    runtime_check = next(
        check
        for check in preflight["validation"]["checks"]
        if check["name"] == "runtime_versions"
    )
    assert runtime_check["passed"] is False

    assert _sha256(ROOT / blocker["preflight_path"]) == blocker["preflight_sha256"]
    assert _sha256(ROOT / blocker["protocol_status_path"]) == (
        blocker["protocol_status_sha256"]
    )
    assert _sha256(ROOT / blocker["reset_path"]) == blocker["reset_sha256"]
    assert _sha256(ROOT / blocker["blocker_path"]) == blocker["blocker_sha256"]
    assert not list(evidence_dir.glob("session*.jsonl"))
    assert blocker["autonomous_start_observed"] is False
    assert blocker["authorization_consumed"] is False
    assert blocker["counts_as_probe_attempt"] is False
    assert blocker["counts_as_retry"] is False
    assert blocker["classification"] == "pre_autonomous_startup_correction"


def test_probe51_report_binds_single_use_authorization_to_line_two():
    report = _json(REPORT_PATH)
    authorization = _json(AUTHORIZATION_PATH)
    issued_bytes = _issued_authorization_bytes(report)
    issued = json.loads(issued_bytes)
    events = _events(report)

    assert report["type"] == "m4_probe_report"
    assert report["task_id"] == "BM-014"
    assert report["probe_number"] == 51
    assert report["episode_id"] == "m4_episode_20260727_121623_ce060317"
    assert report["session_id"] == "270c762e-bb7"
    assert report["level_name"] == f"{report['episode_id']}_bm014"

    binding = report["authorization"]
    assert hashlib.sha256(issued_bytes).hexdigest() == binding["issued_sha256"]
    assert binding["issued_sha256"] == (
        "337e83a1d7d7c8efe22c92b5a81a9acc230ecc508bf3b5d886e94ef224e50367"
    )
    assert issued["consumed"] is False
    assert issued["one_use"] is True
    assert issued["maximum_episode_count"] == 1
    assert issued["maximum_retry_count"] == 0
    assert issued["prior_bm014_eligible_success_count"] == 0
    assert issued["remaining_bm014_eligible_success_count_before_probe"] == 3

    assert _sha256(AUTHORIZATION_PATH) == binding["consumed_sha256"]
    assert authorization["consumed"] is True
    assert authorization["consumed_by_episode"] == report["episode_id"]
    assert authorization["consumed_session_id"] == report["session_id"]
    assert authorization["consumed_level_name"] == report["level_name"]
    assert authorization["consumed_event_line"] == 2
    assert authorization["consumed_monotonic_s"] == 876033.64
    assert authorization["consumed_at_utc"] == "2026-07-27T04:17:29.665526Z"

    start = events[1]
    assert start["type"] == "autonomous_start"
    assert start["session"] == report["session_id"]
    assert start["monotonic_s"] == authorization["consumed_monotonic_s"]
    assert start["data"]["task_id"] == "BM-014"
    assert start["data"]["task_contract_sha256"] == (
        report["frozen_controls"]["task_contract_sha256"]
    )
    assert binding["probe_52_authorized"] is False
    assert authorization["probe_52_authorized"] is False


def test_probe51_hashes_and_ineligible_result_recompute_exactly():
    report = _json(REPORT_PATH)
    paths = report["evidence_paths"]
    for name, expected in report["evidence_sha256"].items():
        assert _sha256(ROOT / paths[name]) == expected

    events = _json(ROOT / paths["session_json"])
    result = _json(ROOT / paths["result"])
    preflight = _json(ROOT / paths["preflight"])
    manifest = _json(ROOT / paths["manifest"])
    saved = _json(ROOT / paths["eligibility"])
    recomputed = evaluate_m4_episode(
        events,
        result,
        preflight,
        manifest,
        "BM-014",
    )

    assert recomputed == saved
    assert saved["eligible"] is False
    assert saved["success"] is False
    assert saved["issues"] == report["eligibility"]["issues"]
    assert len(saved["checks"]) == 74
    assert sum(check["passed"] is True for check in saved["checks"]) == 67
    assert report["eligibility"]["issue_count"] == 7
    assert report["eligibility"]["counts_toward_bm014_success"] is False
    assert report["eligibility"]["counts_toward_capability"] is False


def test_probe51_timeline_actions_and_survival_are_exact():
    report = _json(REPORT_PATH)
    events = _events(report)
    sealed = _json(ROOT / report["evidence_paths"]["session_json"])
    result = _json(ROOT / report["evidence_paths"]["result"])
    manifest = _json(ROOT / report["evidence_paths"]["manifest"])

    assert len(events) == 1419
    assert len(sealed) == 1418
    assert sealed == events[:1418]
    assert events[-1]["type"] == "memory_manage"

    episode = report["episode_result"]
    autonomous = result["autonomous_result"]
    assert result["completed"] is False
    assert result["termination_reason"] == "episode_deadline"
    assert result["elapsed_s"] == autonomous["elapsed_s"] == 300.172
    assert result["deadline_eligible"] is False
    assert episode["deadline_margin_s"] == -0.172
    assert episode["evidence_seal_deadline_margin_s"] == -0.25
    assert manifest["episode_ended_monotonic"] - manifest["episode_started_monotonic"] == (
        episode["evidence_seal_duration_s"]
    )
    assert autonomous["goals_completed"] == 8
    assert autonomous["goals_failed"] == 2
    assert autonomous["goals_interrupted"] == 0
    assert autonomous["total_cycles"] == 98
    assert [
        goal["cycles"] for goal in autonomous["curriculum"]["recent_goals"]
    ] == episode["per_goal_cycles"]

    calls = [event for event in sealed if event["type"] == "llm_planner_call"]
    assert len(calls) == 1
    call = calls[0]["data"]
    assert call["call_id"] == "llm-101bee0f0ec2477e"
    assert call["real_llm_call"] is True
    assert call["schema_valid"] is True
    assert call["transport_evidence"]["attempt_count"] == 1
    assert call["transport_evidence"]["retry_count"] == 0
    assert call["provider_metadata"]["duration_ms"] == 21625
    assert call["provider_metadata"]["total_tokens"] == 4232

    actions = [event for event in sealed if event["type"] == "action"]
    assert len(actions) == 97
    assert sum(event["data"]["result"]["success"] is True for event in actions) == 42
    assert sum(event["data"]["result"]["success"] is not True for event in actions) == 55
    type_counts = {
        action_type: len(
            [
                event
                for event in actions
                if event["data"]["action"]["type"] == action_type
            ]
        )
        for action_type in ("move_to", "dig", "craft", "place", "equip", "smelt")
    }
    assert type_counts == {
        "move_to": 3,
        "dig": 21,
        "craft": 12,
        "place": 58,
        "equip": 3,
        "smelt": 0,
    }
    verifications = [
        event for event in sealed if event["type"] == "action_verification"
    ]
    assert len(verifications) == 97
    assert all(
        event["data"]["verification"]["status"] == "accept"
        for event in verifications
    )
    assert not [
        event
        for event in actions
        if event["monotonic_s"] > manifest["episode_deadline_monotonic"]
    ]

    observations = [event for event in sealed if event["type"] == "observation"]
    assert len(observations) == 196
    assert min(event["data"]["health"] for event in observations) == 20
    assert min(event["data"]["hunger"] for event in observations) == 20
    assert max(
        event["data"]["player_lifecycle"]["death_count"] for event in observations
    ) == 0
    assert max(
        event["data"]["player_lifecycle"]["respawn_count"] for event in observations
    ) == 0
    assert result["terminal_state"]["inventory"] == episode["terminal_inventory"]
    assert "iron_ingot" not in episode["terminal_inventory"]
    assert "iron_pickaxe" not in episode["terminal_inventory"]


def test_probe51_furnace_failure_root_cause_and_decision_are_bounded():
    report = _json(REPORT_PATH)
    events = _events(report)
    progression = report["behavioral_progression"]
    failure = report["furnace_placement_failure"]

    furnace_places = [
        (line, event)
        for line, event in enumerate(events, start=1)
        if event["type"] == "action"
        and event["data"]["action"]["type"] == "place"
        and event["data"]["action"]["parameters"]["item"] == "furnace"
    ]
    assert len(furnace_places) == failure["failed_furnace_place_count"] == 40
    assert all(
        event["data"]["result"]["success"] is False
        for _, event in furnace_places
    )
    assert sum(
        event["data"]["result"]["error"]
        == "placement target is occupied by stone"
        for _, event in furnace_places
    ) == 36
    assert sum(
        event["data"]["result"]["error"]
        == "placement target is occupied by clay"
        for _, event in furnace_places
    ) == 4
    assert furnace_places[0][0] == progression["first_furnace_place_failure_line"] == 849
    assert furnace_places[-1][0] == progression["last_furnace_place_failure_line"] == 1395

    first = furnace_places[0][1]
    assert first["data"]["result"]["reference_position"] == (
        failure["first_failure"]["reference_position"]
    )
    assert first["data"]["result"]["placed_position"] == (
        failure["first_failure"]["placed_position"]
    )
    table_position = failure["nearby_crafting_table_observed_at_smelt_start"]
    assert any(
        block["name"] == "crafting_table" and block["position"] == table_position
        for block in first["data"]["pre_observation"]["nearby_blocks"]
    )
    assert all(
        event["data"]["result"]["reference_position"] != table_position
        for _, event in furnace_places
    )
    assert failure["crafting_table_used_as_furnace_reference"] is False
    assert failure["root_cause_classification"] == (
        "m4_place_target_machine_observation_coverage_fail_open"
    )
    assert failure["offline_repair_status"] == "completed"
    assert failure["repair_claimed_complete"] is True

    repair = report["offline_repair"]
    assert repair["policy_id"] == (
        "m4-bm013-bm014-furnace-place-local-snapshot-v1"
    )
    assert repair["requires_same_snapshot_solid_reference"] is True
    assert repair["requires_same_snapshot_replaceable_target_above"] is True
    assert repair["requires_complete_valid_snapshot_envelope"] is True
    assert repair["requires_snapshot_player_position_and_cell_binding"] is True
    assert repair["requires_snapshot_and_current_player_same_cell"] is True
    assert repair["maximum_snapshot_age_ms"] == 5000
    assert repair["requires_exact_integral_reference_target_pair"] is True
    assert (
        repair["requires_target_outside_snapshot_and_current_player_collision_union"]
        is True
    )
    assert repair["speculative_nearby_blocks_fallback"] is False
    assert repair["action_verifier_exact_pair_hard_required"] is True
    assert repair["action_verifier_task_scope"] == ["BM-013", "BM-014"]
    assert repair["bm012_generic_furnace_place_behavior_unchanged"] is True
    assert repair["missing_forged_stale_or_unbound_snapshot_rejected"] is True
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
    assert repair["action_verifier_target_evidence_after_repair"] == "target:air"
    assert repair["focused_python_pass_count"] == 130
    assert repair["probe51_reduced_replay_reference"] == table_position
    assert repair["probe51_reduced_replay_target"] == {
        "x": 118,
        "y": 123,
        "z": -49,
    }
    assert repair["probe_52_authorized"] is False
    for key, relative_path in repair["source_paths"].items():
        source_bytes = subprocess.check_output(
            [
                "git",
                "show",
                f"{FURNACE_REPAIR_COMMIT}:{relative_path}",
            ],
            cwd=ROOT,
        )
        assert repair["source_sha256"][key] == hashlib.sha256(
            source_bytes
        ).hexdigest()
    audit = _json(ROOT / failure["repair_audit_path"])
    execution = audit["offline_repair"]["execution_path_gates"]
    assert execution["suppressed_execution_paths"] == (
        repair["suppressed_execution_paths"]
    )
    assert execution["full_think_fallback_suppressed"] == (
        repair["full_think_fallback_suppressed"]
    )
    assert execution["action_verifier_exact_snapshot_pair_hard_required"] == (
        repair["action_verifier_exact_pair_hard_required"]
    )
    assert audit["source_sha256"] == repair["source_sha256"]
    assert audit["offline_validation"]["focused_python_pass_count"] == (
        repair["focused_python_pass_count"]
    )
    assert audit["offline_validation"]["selected_node_internal_case_pass_count"] == (
        repair["selected_node_internal_case_pass_count"]
    )

    goal_events = [
        event["data"].get("goal", "")
        for event in events
        if event["type"] == "auto_goal"
    ]
    assert not [goal for goal in goal_events if "Ensure 2 sticks" in goal]
    assert not [
        event
        for event in events
        if event["type"] == "action"
        and event["data"]["action"]["type"] == "smelt"
    ]
    assert progression["smelt_backend_action_exercised"] is False
    assert progression["stick_goal_verifier_repair_live_exercised"] is False
    assert progression["iron_pickaxe_craft_exercised"] is False

    decision = report["decision"]
    assert decision["bm014_attempt_count_before"] == 0
    assert decision["bm014_attempt_count_after"] == 1
    assert decision["bm014_failure_count_before"] == 0
    assert decision["bm014_failure_count_after"] == 1
    assert decision["bm014_success_count_before"] == 0
    assert decision["bm014_success_count_after"] == 0
    assert decision["remaining_success_count"] == 3
    assert decision["bm014_status_after"] == "failing"
    assert decision["m4_status_after"] == "failing"
    assert decision["probe_52_authorized"] is False
