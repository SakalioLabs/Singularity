"""Bind the retained Probe 54 BM-014 failure and bounded offline repair."""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections import Counter
from pathlib import Path

from singularity.evaluation.m4_protocol import evaluate_m4_episode


ROOT = Path(__file__).resolve().parents[1]
REPORT_RELATIVE = "workspace/evals/m4_probe54_report.json"
REPORT_PATH = ROOT / REPORT_RELATIVE
AUTHORIZATION_PATH = ROOT / "workspace/evals/m4_probe54_authorization.json"


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


def test_probe54_report_binds_single_use_authorization_and_consumption():
    report = _json(REPORT_PATH)
    authorization = _json(AUTHORIZATION_PATH)
    binding = report["authorization"]
    issued_bytes = _git_blob(binding["commit"], binding["path"])
    issued = json.loads(issued_bytes)

    assert report["type"] == "m4_probe_report"
    assert report["task_id"] == "BM-014"
    assert report["probe_number"] == 54
    assert report["episode_id"] == "m4_episode_20260727_200833_e85a7757"
    assert report["session_id"] == "69d1d0b2-ec0"
    assert report["level_name"] == f"{report['episode_id']}_bm014"
    assert subprocess.run(
        ["git", "rev-parse", f"{binding['commit']}^{{tree}}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip() == binding["tree"]
    assert binding["commit"] == "4aaf0011071c0dc7ca73ee10b9a7e96b337669cb"
    assert binding["tree"] == "20e44f903930a88520c57ba6dcf9148d3a8e4785"
    assert hashlib.sha256(issued_bytes).hexdigest() == binding["issued_sha256"]
    assert binding["issued_sha256"] == (
        "81eab72e83d5d73bdda09a02fb47541bc36678631f10455dcd06a273af81ade5"
    )
    assert issued["consumed"] is False
    assert issued["authorized"] is True
    assert issued["one_use"] is True
    assert issued["maximum_episode_count"] == 1
    assert issued["maximum_retry_count"] == 0
    assert issued["client_max_retries"] == 0
    assert issued["proxy_max_retries"] == 0
    assert issued["prior_bm014_attempt_count"] == 3
    assert issued["prior_bm014_failure_count"] == 2
    assert issued["prior_bm014_eligible_success_count"] == 1
    assert issued["remaining_bm014_eligible_success_count_before_probe"] == 2
    assert issued["probe_55_authorized"] is False

    assert _sha256(AUTHORIZATION_PATH) == binding["consumed_sha256"]
    assert binding["consumed_sha256"] == (
        "90df767c067abc521e41b9e3349b31200651d4ff1248d0f3a6f81c676d34e15c"
    )
    assert authorization["consumed"] is True
    assert authorization["consumed_by_episode"] == report["episode_id"]
    assert authorization["consumed_session_id"] == report["session_id"]
    assert authorization["consumed_level_name"] == report["level_name"]
    assert authorization["consumed_at"] == "autonomous_start"
    assert authorization["consumed_event_line"] == 2
    assert authorization["consumed_monotonic_s"] == 904337.5
    assert authorization["consumed_at_utc"] == "2026-07-27T12:09:13.528565Z"
    assert authorization["probe_55_authorized"] is False
    assert binding["probe_55_authorized"] is False

    events = _events(report)
    consumed = events[authorization["consumed_event_line"] - 1]
    assert consumed["type"] == authorization["consumed_at"]
    assert consumed["session"] == report["session_id"]
    assert consumed["monotonic_s"] == authorization["consumed_monotonic_s"]


def test_probe54_hashes_and_independent_eligibility_recompute_exactly():
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

    expected_issues = [
        "event:terminal_task_verification",
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
    assert sum(check["passed"] is True for check in saved["checks"]) == 66
    assert sum(check["passed"] is False for check in saved["checks"]) == 8
    assert preparation["readiness"] == "review"
    assert preparation["decision"] == "diagnose_first_unrecovered_transition"
    assert preparation["progress_gate_passed"] is False
    assert preparation["counts_toward_task_success"] is False
    assert preparation["evidence_eligible"] is False
    assert len(preparation["autonomous_goals"]) == 8
    assert preparation["action_count"] == 38
    assert preparation["successful_action_count"] == 38
    assert preparation["time_remaining_s"] == 0.0
    assert preparation["first_unrecovered_transition"]["monotonic_s"] == (
        904637.531
    )


def test_probe54_timeline_planner_actions_survival_and_skills_are_bounded():
    report = _json(REPORT_PATH)
    events = _events(report)
    sealed = _json(ROOT / report["evidence_paths"]["session_json"])
    result = _json(ROOT / report["evidence_paths"]["result"])
    manifest = _json(ROOT / report["evidence_paths"]["manifest"])

    assert len(events) == report["episode_result"]["session_event_count"] == 577
    assert len(sealed) == report["episode_result"]["session_json_event_count"] == 576
    assert sealed == events[:576]
    assert events[-1]["type"] == "memory_manage"
    start = events[1]
    assert start["type"] == "autonomous_start"
    assert start["session"] == report["session_id"]
    assert start["monotonic_s"] == manifest["episode_started_monotonic"] == 904337.5
    assert manifest["episode_deadline_monotonic"] == 904637.5
    assert manifest["episode_ended_monotonic"] == 904637.593

    autonomous = result["autonomous_result"]
    episode = report["episode_result"]
    assert result["completed"] is False
    assert result["termination_reason"] == "episode_deadline"
    assert result["elapsed_s"] == autonomous["elapsed_s"] == episode["elapsed_s"] == (
        300.031
    )
    assert result["deadline_eligible"] is False
    assert autonomous["goals_completed"] == 7
    assert autonomous["goals_failed"] == 1
    assert autonomous["goals_interrupted"] == 0
    assert autonomous["total_cycles"] == sum(episode["per_goal_cycles"]) == 40
    assert [goal["cycles"] for goal in autonomous["curriculum"]["recent_goals"]] == (
        episode["per_goal_cycles"]
    )

    indexed_calls = [
        (index, event)
        for index, event in enumerate(sealed, start=1)
        if event["type"] == "llm_planner_call"
    ]
    assert [line for line, _ in indexed_calls] == [13, 561, 569]
    assert [event["data"]["call_id"] for _, event in indexed_calls] == (
        episode["planner_call_ids"]
    )
    successful = indexed_calls[0][1]["data"]
    assert successful["real_llm_call"] is True
    assert successful["schema_valid"] is True
    assert successful["transport_evidence"]["attempt_count"] == 1
    assert successful["transport_evidence"]["retry_count"] == 0
    assert successful["provider_metadata"]["duration_ms"] == 10796
    assert successful["provider_metadata"]["total_tokens"] == 4223

    timeout_calls = [event["data"] for _, event in indexed_calls[1:]]
    assert len({call["call_id"] for call in timeout_calls}) == 2
    assert [call["call_index"] for call in timeout_calls] == [0, 1]
    assert timeout_calls[0]["parent_call_id"] == ""
    assert timeout_calls[1]["parent_call_id"] == timeout_calls[0]["call_id"]
    assert [call["deadline_policy"]["request_timeout_s"] for call in timeout_calls] == (
        [90.0, 6.079]
    )
    for call in timeout_calls:
        assert call["real_llm_call"] is False
        assert call["schema_valid"] is False
        assert call["error"] == "Request timed out."
        assert call["transport_evidence"]["policy_id"] == "single-attempt"
        assert call["transport_evidence"]["attempt_count"] == 1
        assert call["transport_evidence"]["retry_count"] == 0
        assert len(call["transport_evidence"]["attempts"]) == 1
        assert call["transport_evidence"]["attempts"][0]["attempt_index"] == 0
        assert call["transport_evidence"]["attempts"][0]["sdk_max_retries"] == 0

    recovery = events[563]
    assert recovery["type"] == "m4_planner_transport_recovery"
    assert recovery["data"]["cycle"] == 39
    assert recovery["data"]["planner_call_id"] == timeout_calls[0]["call_id"]
    assert recovery["data"]["same_call_retry_count"] == 0
    assert recovery["data"]["resume_policy"] == "retry_planner_next_cycle_same_goal"
    assert recovery["data"]["recovered"] is True
    deadline = events[570]
    assert deadline["type"] == "episode_deadline_exceeded"
    assert deadline["data"]["phase"] == "post_planner"
    assert deadline["monotonic_s"] == 904637.531
    assert deadline["data"]["episode_deadline_monotonic"] == 904637.5
    assert deadline["data"]["new_action_suppressed"] is True

    actions = [event for event in sealed if event["type"] == "action"]
    assert len(actions) == 38
    assert all(event["data"]["result"]["success"] is True for event in actions)
    attempts = Counter(event["data"]["action"]["type"] for event in actions)
    successes = Counter(
        event["data"]["action"]["type"]
        for event in actions
        if event["data"]["result"]["success"] is True
    )
    expected = {
        "move_to": 3,
        "dig": 21,
        "craft": 9,
        "place": 2,
        "equip": 3,
    }
    assert attempts == expected
    assert successes == expected

    observations = [event["data"] for event in sealed if event["type"] == "observation"]
    assert len(observations) == report["survival_evidence"]["observation_count"] == 79
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


def test_probe54_failure_provenance_repair_and_decision_are_bounded():
    report = _json(REPORT_PATH)
    events = _events(report)
    indexed = {index: event for index, event in enumerate(events, start=1)}

    prior_repair = report["probe53_repair_live_provenance"]
    table_places = [indexed[line] for line in prior_repair["action_lines"]]
    assert len(table_places) == prior_repair["successful_place_count"] == 2
    for event, expected in zip(table_places, prior_repair["placements"]):
        assert event["type"] == "action"
        assert event["data"]["action"]["type"] == "place"
        assert event["data"]["action"]["parameters"]["item"] == "crafting_table"
        result = event["data"]["result"]
        assert result["success"] is True
        assert result["reference_position"] == expected["reference_position"]
        assert result["placed_position"] == expected["placed_position"]
        assert result["target_block_before"]["name"] == "air"
        assert result["target_block_after"]["name"] == "crafting_table"
        assert (
            "policy:m4-bm013-bm014-crafting-table-place-local-snapshot-v1"
            in result["action_verification"]["evidence"]
        )
        assert "target:air" in result["action_verification"]["evidence"]
    assert prior_repair["failed_place_count"] == 0
    assert prior_repair["occupied_target_failure_count"] == 0
    assert prior_repair["live_exercised"] is True

    gap = report["portable_station_material_recovery_gap"]
    furnace_observation = indexed[558]["data"]
    assert furnace_observation["inventory"] == (
        report["episode_result"]["last_trustworthy_inventory"]
    )
    assert furnace_observation["position"] == gap["terminal_player_position"]
    assert "crafting_table" not in furnace_observation["inventory"]
    assert "oak_log" not in furnace_observation["inventory"]
    assert furnace_observation["inventory"]["oak_planks"] == 3
    assert furnace_observation["inventory"]["cobblestone"] == 80
    assert furnace_observation["inventory"]["raw_iron"] == 4
    assert furnace_observation["inventory"]["coal"] == 1
    assert all(
        block["name"] != "crafting_table"
        for block in furnace_observation["nearby_blocks"]
    )
    assert [
        event["data"]["result"]["placed_position"]
        for event in table_places
    ] == gap["retained_episode_owned_crafting_table_positions"]

    transition = gap["navigation_inventory_transition"]
    navigation = indexed[transition["event_line"]]
    assert transition["event_line"] == 536
    assert navigation["type"] == "action"
    assert navigation["data"]["action"] == transition["action"] == {
        "type": "move_to",
        "parameters": {"x": 118, "y": 123, "z": -51},
    }
    navigation_result = navigation["data"]["result"]
    assert navigation_result["success"] is True
    assert navigation_result["action_verification"]["status"] == "accept"
    assert navigation_result["action_verification"]["reason"] == (
        "navigation or low-impact action"
    )
    assert navigation_result["duration_ms"] == transition["duration_ms"] == 37969
    assert navigation["data"]["pre_observation"]["position"] == (
        transition["pre_position"]
    )
    assert navigation["data"]["post_observation"]["position"] == (
        transition["post_position"]
    )
    assert navigation["data"]["pre_observation"]["inventory"] == {
        "oak_log": 2,
        "oak_planks": 3,
        "wooden_pickaxe": 1,
        "stone_pickaxe": 1,
        "cobblestone": 35,
        "dirt": 3,
        "raw_iron": 3,
    } == transition["pre_inventory"]
    assert navigation["data"]["post_observation"]["inventory"] == {
        "wooden_pickaxe": 1,
        "stone_pickaxe": 1,
        "cobblestone": 79,
        "dirt": 2,
        "raw_iron": 4,
        "oak_planks": 3,
    } == transition["post_inventory"]
    keys = set(transition["pre_inventory"]) | set(transition["post_inventory"])
    independently_recomputed_delta = {
        key: (
            transition["post_inventory"].get(key, 0)
            - transition["pre_inventory"].get(key, 0)
        )
        for key in keys
        if (
            transition["post_inventory"].get(key, 0)
            - transition["pre_inventory"].get(key, 0)
        )
        != 0
        or key == "oak_planks"
    }
    assert independently_recomputed_delta == transition["inventory_delta"] == {
        "oak_log": -2,
        "oak_planks": 0,
        "cobblestone": 44,
        "dirt": -1,
        "raw_iron": 1,
    }
    assert transition["station_material_depleted"] == "oak_log"
    assert transition["station_material_depletion_count"] == 2
    assert transition["depletion_caused_portable_station_recovery_gap"] is True

    actions = [
        (line, event)
        for line, event in indexed.items()
        if event["type"] == "action"
    ]
    assert actions[-1][0] == gap["last_action_line"] == 548
    assert actions[-1][1]["data"]["result"]["success"] is True
    assert all(event["data"]["result"]["success"] is True for _, event in actions)
    assert not any(
        event["data"]["action"]["parameters"].get("item") == "furnace"
        for _, event in actions
        if event["data"]["action"]["type"] == "craft"
    )
    assert not any(
        event["data"]["action"]["type"] in {"smelt"}
        for _, event in actions
    )

    analysis = report["failure_analysis"]
    assert analysis["classification"] == (
        "capability_navigation_inventory_preservation_failure"
    )
    assert analysis["infrastructure_failure"] is False
    assert analysis["root_cause"] == (
        "navigation_inventory_depletion_caused_portable_station_recovery_gap_"
        "with_planner_timeout_amplification"
    )
    assert analysis["primary_cause"] == (
        "navigation_inventory_depletion_caused_portable_station_recovery_gap"
    )
    assert analysis["secondary_amplification"] == "planner_transport_timeout"
    assert analysis["planner_transport_timeout_is_root_classification"] is False
    assert analysis["first_actionable_capability_transition"] == (
        "navigation_inventory_depletion"
    )
    assert analysis["first_actionable_capability_transition_line"] == 536
    assert analysis["first_unrecovered_transition_line"] == 571
    assert analysis["probe53_crafting_table_place_local_snapshot_repair_correct"] is True
    assert analysis["all_backend_actions_succeeded"] is True
    assert (
        analysis["planner_timeouts_were_distinct_cycle_calls_not_same_call_retries"]
        is True
    )

    repair = report["offline_repair"]
    assert repair["policy_id"] == (
        "m4-bm013-bm014-portable-crafting-table-recovery-v1"
    )
    assert (
        repair[
            "reclaims_currently_observed_episode_owned_table_before_remote_iron_or_coal_move"
        ]
        is True
    )
    assert repair["reclaim_action_requires_current_observation"] is True
    assert repair["reclaim_action_requires_successful_episode_owned_place_history"] is True
    assert repair["reclaim_action_requires_interaction_range"] is True
    assert repair["maximum_reclaim_distance"] == 4.5
    assert repair["ordered_successful_place_and_dig_mutations_replayed"] is True
    assert repair["removed_or_replaced_table_not_returned"] is True
    assert (
        repair[
            "returns_to_nearest_retained_episode_owned_table_for_current_reobservation"
        ]
        is True
    )
    assert repair["return_move_requires_distance_above_interaction_range"] is True
    assert (
        repair[
            "retained_table_within_interaction_range_but_not_reobserved_does_not_repeat_move"
        ]
        is True
    )
    assert repair["historical_coordinate_not_treated_as_current_block_observation"] is True
    assert repair["missing_retained_table_uses_only_machine_observed_oak_log"] is True
    assert (
        repair["missing_retained_table_and_machine_observed_log_fails_closed"]
        is True
    )
    assert repair["full_think_fallback_suppressed_on_bounded_block"] is True
    assert repair["suppressed_execution_paths"] == [
        "learned_skill",
        "bm012_machine_step",
        "llm_plan",
        "rule_plan",
        "visual_action_grounding",
    ]
    assert repair["arbitrary_unowned_table_not_reclaimed"] is True
    assert repair["bm012_generic_crafting_table_behavior_unchanged"] is True
    assert repair["probe53_crafting_table_local_snapshot_policy_unchanged"] is True
    assert repair["furnace_local_snapshot_policy_unchanged"] is True
    assert repair["focused_python_pass_count"] == 26
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
    assert repair["protocol_changed"] is False
    assert repair["task_contract_changed"] is False
    assert repair["deadline_changed"] is False
    assert repair["retry_policy_changed"] is False
    assert repair["provider_transport_policy_changed"] is False
    assert repair["smelt_physics_changed"] is False
    assert repair["live_exercised"] is False
    assert repair["probe_55_authorized"] is False

    decision = report["decision"]
    assert decision["counts_toward_bm014_success"] is False
    assert decision["counts_toward_capability"] is False
    assert decision["bm014_attempt_count_before"] == 3
    assert decision["bm014_attempt_count_after"] == 4
    assert decision["bm014_failure_count_before"] == 2
    assert decision["bm014_failure_count_after"] == 3
    assert decision["bm014_success_count_before"] == 1
    assert decision["bm014_success_count_after"] == 1
    assert decision["remaining_success_count"] == 2
    assert decision["bm014_status_after"] == "live_observed"
    assert decision["m4_status_after"] == "live_observed"
    assert (
        decision[
            "next_live_probe_locked_until_failure_evidence_and_offline_repair_are_committed_pushed_and_read_back"
        ]
        is True
    )
    assert decision["probe_55_authorized"] is False
