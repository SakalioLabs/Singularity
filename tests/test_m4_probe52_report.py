"""Bind the retained Probe 52 BM-014 success report to raw machine evidence."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from singularity.evaluation.m4_protocol import evaluate_m4_episode


ROOT = Path(__file__).resolve().parent.parent
REPORT_PATH = ROOT / "workspace/evals/m4_probe52_report.json"
AUTHORIZATION_PATH = ROOT / "workspace/evals/m4_probe52_authorization.json"


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


def test_probe52_report_binds_single_use_authorization():
    report = _json(REPORT_PATH)
    authorization = _json(AUTHORIZATION_PATH)
    issued_bytes = _issued_authorization_bytes(report)
    issued = json.loads(issued_bytes)

    assert report["type"] == "m4_probe_report"
    assert report["task_id"] == "BM-014"
    assert report["probe_number"] == 52
    assert report["episode_id"] == "m4_episode_20260727_153112_f28d04d6"
    assert report["session_id"] == "08c52d82-068"
    assert report["level_name"] == f"{report['episode_id']}_bm014"

    binding = report["authorization"]
    assert hashlib.sha256(issued_bytes).hexdigest() == binding["issued_sha256"]
    assert binding["issued_sha256"] == (
        "07819c2758a5c78dd942f50bb8a9406241e4b36010338d4b27bceb9ff8d8046c"
    )
    assert issued["consumed"] is False
    assert issued["one_use"] is True
    assert issued["maximum_episode_count"] == 1
    assert issued["maximum_retry_count"] == 0
    assert issued["prior_bm014_attempt_count"] == 1
    assert issued["prior_bm014_failure_count"] == 1
    assert issued["prior_bm014_eligible_success_count"] == 0
    assert issued["remaining_bm014_eligible_success_count_before_probe"] == 3

    assert _sha256(AUTHORIZATION_PATH) == binding["consumed_sha256"]
    assert authorization["consumed"] is True
    assert authorization["consumed_by_episode"] == report["episode_id"]
    assert authorization["consumed_session_id"] == report["session_id"]
    assert authorization["consumed_level_name"] == report["level_name"]
    assert authorization["consumed_event_line"] == 2
    assert authorization["consumed_monotonic_s"] == 887786.718
    assert authorization["consumed_at_utc"] == "2026-07-27T07:33:22.751455Z"
    assert authorization["probe_53_authorized"] is False
    assert binding["probe_53_authorized"] is False


def test_probe52_hashes_preparation_and_eligibility_recompute_exactly():
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
    recomputed = evaluate_m4_episode(
        events,
        result,
        preflight,
        manifest,
        "BM-014",
    )

    assert recomputed == saved
    assert saved["eligible"] is True
    assert saved["success"] is True
    assert saved["issues"] == []
    assert len(saved["checks"]) == 74
    assert sum(check["passed"] is True for check in saved["checks"]) == 74

    assert preparation["readiness"] == "eligible"
    assert preparation["decision"] == "count_bm014_success"
    assert preparation["progress_gate_passed"] is True
    assert preparation["counts_toward_task_success"] is True
    assert preparation["evidence_eligible"] is True
    assert preparation["eligibility_issues"] == []
    assert len(preparation["autonomous_goals"]) == 11
    assert preparation["action_count"] == 67
    assert preparation["successful_action_count"] == 46
    assert preparation["output_provenance"]["successful_source_action_count"] == 1
    assert preparation["output_provenance"]["successful_source_actions"][0][
        "event_index"
    ] == 991
    assert preparation["time_remaining_s"] == 13.75


def test_probe52_timeline_planner_actions_survival_and_skills_are_bounded():
    report = _json(REPORT_PATH)
    events = _events(report)
    sealed = _json(ROOT / report["evidence_paths"]["session_json"])
    result = _json(ROOT / report["evidence_paths"]["result"])
    manifest = _json(ROOT / report["evidence_paths"]["manifest"])

    assert len(events) == 1002
    assert len(sealed) == 1001
    assert sealed == events[:1001]
    assert events[-1]["type"] == "memory_manage"

    start = events[1]
    assert start["type"] == "autonomous_start"
    assert start["session"] == report["session_id"]
    assert start["monotonic_s"] == manifest["episode_started_monotonic"] == 887786.718
    assert manifest["episode_deadline_monotonic"] == 888086.718
    assert manifest["episode_ended_monotonic"] == 888072.968

    episode = report["episode_result"]
    autonomous = result["autonomous_result"]
    assert result["completed"] is True
    assert result["termination_reason"] == "terminal_task_verified"
    assert result["elapsed_s"] == autonomous["elapsed_s"] == 286.188
    assert result["deadline_eligible"] is True
    assert manifest["episode_ended_monotonic"] - manifest["episode_started_monotonic"] == (
        episode["evidence_seal_duration_s"]
    )
    assert autonomous["goals_completed"] == 11
    assert autonomous["goals_failed"] == 0
    assert autonomous["goals_interrupted"] == 0
    assert autonomous["total_cycles"] == 67
    assert len(episode["per_goal_cycles"]) == autonomous["goals_completed"] == 11
    assert sum(episode["per_goal_cycles"]) == autonomous["total_cycles"] == 67
    assert [
        goal["cycles"] for goal in autonomous["curriculum"]["recent_goals"]
    ] == episode["per_goal_cycles"][-10:]

    calls = [event for event in sealed if event["type"] == "llm_planner_call"]
    assert len(calls) == 1
    call = calls[0]["data"]
    assert call["call_id"] == "llm-7a06884c34b347de"
    assert call["real_llm_call"] is True
    assert call["schema_valid"] is True
    assert call["transport_evidence"]["attempt_count"] == 1
    assert call["transport_evidence"]["retry_count"] == 0
    assert call["provider_metadata"]["duration_ms"] == 19702
    assert call["provider_metadata"]["total_tokens"] == 4427

    actions = [event for event in sealed if event["type"] == "action"]
    assert len(actions) == 67
    assert sum(event["data"]["result"]["success"] is True for event in actions) == 46
    assert sum(event["data"]["result"]["success"] is not True for event in actions) == 21
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
        "craft": 14,
        "place": 25,
        "equip": 3,
        "smelt": 1,
    }
    assert not [
        event
        for event in actions
        if event["monotonic_s"] > manifest["episode_deadline_monotonic"]
    ]

    observations = [event for event in sealed if event["type"] == "observation"]
    assert len(observations) == 135
    assert min(event["data"]["health"] for event in observations) == 20
    assert min(event["data"]["hunger"] for event in observations) == 20
    assert max(
        event["data"]["player_lifecycle"]["death_count"] for event in observations
    ) == 0
    assert max(
        event["data"]["player_lifecycle"]["respawn_count"] for event in observations
    ) == 0
    assert result["terminal_state"]["inventory"] == episode["terminal_inventory"]
    assert result["terminal_state"]["inventory"]["iron_pickaxe"] == 1
    assert result["terminal_state"]["bot_connected"] is True

    skills = report["skill_attribution"]
    assert manifest["skill_execution_mode"] == "off"
    assert skills["selected_count"] == 0
    assert skills["executed_count"] == 0
    assert skills["successful_action_count"] == 0
    assert skills["failed_action_count"] == 0
    assert skills["completion_count"] == 0
    assert skills["fallback_count"] == 0


def test_probe52_furnace_smelt_stick_and_pickaxe_provenance_are_machine_grounded():
    report = _json(REPORT_PATH)
    events = _events(report)

    furnace_plans = [
        events[line - 1]
        for line in (917, 931)
    ]
    assert all(
        event["type"] == "m4_bm013_bm014_toolchain_machine_step_plan"
        for event in furnace_plans
    )
    assert all(
        event["data"]["target"]["source"] == "get_shelter_state.blocks"
        and event["data"]["target"]["target_block"]["name"] == "air"
        and event["data"]["target"]["target_block"]["machine_observed"] is True
        for event in furnace_plans
    )
    assert [
        event["data"]["target"]["target_position"]
        for event in furnace_plans
    ] == [
        {"x": 118, "y": 123, "z": -49},
        {"x": 118, "y": 123, "z": -51},
    ]

    furnace = report["furnace_placement_provenance"]
    furnace_actions = [
        (line, event)
        for line, event in enumerate(events, start=1)
        if event["type"] == "action"
        and event["data"]["action"]["type"] == "place"
        and event["data"]["action"]["parameters"]["item"] == "furnace"
    ]
    assert len(furnace_actions) == furnace["place_attempt_count"] == 2
    assert furnace_actions[0][0] == 925
    assert furnace_actions[0][1]["data"]["result"]["success"] is False
    assert "blockUpdate" in furnace_actions[0][1]["data"]["result"]["error"]
    assert furnace_actions[1][0] == 940
    assert furnace_actions[1][1]["data"]["result"]["success"] is True
    for _, event in furnace_actions:
        evidence = event["data"]["result"]["action_verification"]["evidence"]
        assert (
            "policy:m4-bm013-bm014-furnace-place-local-snapshot-v1"
            in evidence
        )
        assert "target:air" in evidence
        assert "target:not_observed_occupied" not in evidence

    recovered = report["recovered_noise"]
    assert recovered["failed_action_count"] == 21
    assert recovered["failed_action_types"] == {"place": 21}
    assert recovered["crafting_table_occupied_stone_place_failure_count"] == 20
    assert recovered["furnace_block_update_timeout_count"] == 1
    assert recovered["eligibility_defect"] is False

    smelt = events[report["smelting_provenance"]["action_line"] - 1]
    assert smelt["type"] == "action"
    assert smelt["data"]["action"]["type"] == "smelt"
    smelt_result = smelt["data"]["result"]
    assert smelt_result["success"] is True
    assert smelt_result["smelt_attempts"] == 1
    assert smelt_result["smelt_retry_count"] == 0
    assert smelt_result["automatic_retry"] is False
    assert smelt_result["inventory_signed_delta"] == {
        "coal": -1,
        "furnace": -1,
        "raw_iron": -3,
        "iron_ingot": 3,
    }
    assert smelt_result["output_collected_count"] == 3
    assert smelt_result["output_settled"] is True
    assert smelt_result["furnace_slots_empty"] is True
    assert smelt_result["furnace_closed"] is True
    assert smelt_result["accepted_within_episode_deadline"] is True

    stick = events[report["behavioral_progression"]["stick_craft_action_line"] - 1]
    assert stick["type"] == "action"
    assert stick["data"]["action"]["parameters"]["item"] == "stick"
    assert stick["data"]["result"]["inventory_signed_delta"] == {
        "oak_planks": -2,
        "stick": 4,
    }
    stick_verification = events[
        report["behavioral_progression"]["stick_goal_verification_line"] - 1
    ]
    assert stick_verification["type"] == "goal_verification"
    assert stick_verification["data"]["achieved"] is True

    pickaxe = events[report["iron_pickaxe_provenance"]["action_line"] - 1]
    assert pickaxe["type"] == "action"
    assert pickaxe["data"]["action"]["parameters"]["item"] == "iron_pickaxe"
    assert pickaxe["data"]["result"]["success"] is True
    assert pickaxe["data"]["result"]["inventory_signed_delta"] == {
        "iron_ingot": -3,
        "stick": -2,
        "iron_pickaxe": 1,
    }
    terminal = events[
        report["behavioral_progression"]["terminal_task_verification_line"] - 1
    ]
    assert terminal["type"] == "terminal_task_verification"
    assert terminal["data"]["passed"] is True
    assert terminal["data"]["verifier_id"] == (
        "m4-crafted-item-inventory-verifier-v1"
    )
    assert terminal["data"]["observed_count"] == 1
    assert terminal["data"]["inventory"]["iron_pickaxe"] == 1


def test_probe52_decision_counts_only_first_bm014_success_and_keeps_probe53_locked():
    report = _json(REPORT_PATH)
    eligibility = report["eligibility"]
    decision = report["decision"]

    assert eligibility["eligible"] is True
    assert eligibility["success"] is True
    assert eligibility["progress_gate_passed"] is True
    assert eligibility["counts_toward_bm014_success"] is True
    assert eligibility["counts_toward_capability"] is False
    assert eligibility["check_count"] == eligibility["pass_count"] == 74
    assert eligibility["issues"] == []

    assert decision["bm014_attempt_count_before"] == 1
    assert decision["bm014_attempt_count_after"] == 2
    assert decision["bm014_failure_count_before"] == 1
    assert decision["bm014_failure_count_after"] == 1
    assert decision["bm014_success_count_before"] == 0
    assert decision["bm014_success_count_after"] == 1
    assert decision["remaining_success_count"] == 2
    assert decision["bm014_repeat_verified_after_probe"] is False
    assert decision["bm014_status_after"] == "live_observed"
    assert decision["m4_status_after"] == "live_observed"
    assert decision["next_live_probe_locked_until_evidence_commit"] is True
    assert decision["probe_53_authorized"] is False
