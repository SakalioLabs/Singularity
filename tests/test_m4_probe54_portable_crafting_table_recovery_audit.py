"""Bind the Probe 54 portable-table recovery repair to retained evidence."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from singularity.core.agent import (
    M4_BM013_BM014_PORTABLE_CRAFTING_TABLE_RECOVERY_POLICY_ID,
)


ROOT = Path(__file__).resolve().parents[1]
AUDIT_RELATIVE = (
    "workspace/evals/"
    "m4_probe54_portable_crafting_table_recovery_audit.json"
)
AUDIT_PATH = ROOT / AUDIT_RELATIVE
REPORT_RELATIVE = "workspace/evals/m4_probe54_report.json"
AUTHORIZATION_RELATIVE = "workspace/evals/m4_probe54_authorization.json"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _sha256(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _git_blob(commit: str, relative_path: str) -> bytes:
    return subprocess.check_output(
        ["git", "show", f"{commit}:{Path(relative_path).as_posix()}"],
        cwd=ROOT,
    )


def _audit_origin_commit() -> str:
    """Return the commit that first retained this audit, if it exists yet."""
    output = subprocess.check_output(
        [
            "git",
            "log",
            "--diff-filter=A",
            "--format=%H",
            "--",
            AUDIT_RELATIVE,
        ],
        cwd=ROOT,
        text=True,
    )
    commits = [line.strip() for line in output.splitlines() if line.strip()]
    return commits[-1] if commits else ""


def _transaction_bytes(relative_path: str) -> bytes:
    origin = _audit_origin_commit()
    if origin:
        return _git_blob(origin, relative_path)
    return (ROOT / relative_path).read_bytes()


def _transaction_json(relative_path: str) -> dict:
    return json.loads(_transaction_bytes(relative_path))


def _events(audit: dict) -> list[dict]:
    path = ROOT / audit["bindings"]["raw_evidence_paths"]["raw_session_jsonl"]
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_probe54_portable_table_audit_binds_report_auth_and_raw_evidence():
    audit = _json(AUDIT_PATH)
    bindings = audit["bindings"]
    report_bytes = _transaction_bytes(bindings["probe_54_report_path"])
    report = json.loads(report_bytes)
    authorization_bytes = _transaction_bytes(
        bindings["probe_54_authorization_path"]
    )
    authorization = json.loads(authorization_bytes)

    assert audit["type"] == (
        "m4_probe54_portable_crafting_table_recovery_audit"
    )
    assert audit["schema_version"] == 1
    assert audit["profile"] == "m4-fixed-v1"
    assert audit["task_id"] == "BM-014"
    assert audit["failure_classification"] == (
        "capability_navigation_inventory_preservation_failure"
    )
    assert audit["counts_toward_bm014_success"] is False
    assert audit["counts_toward_capability"] is False

    assert _sha256_bytes(report_bytes) == bindings["probe_54_report_sha256"]
    assert report["type"] == bindings["probe_54_report_type"]
    assert report["schema_version"] == bindings["probe_54_report_schema_version"]
    assert report["probe_number"] == 54
    assert report["episode_id"] == bindings["probe_54_episode_id"]
    assert report["session_id"] == bindings["probe_54_session_id"]
    assert report["level_name"] == bindings["probe_54_level_name"]
    assert report["authorization"]["commit"] == (
        bindings["probe_54_authorization_commit"]
    )
    assert report["authorization"]["tree"] == (
        bindings["probe_54_authorization_tree"]
    )

    assert _sha256_bytes(authorization_bytes) == (
        bindings["probe_54_consumed_authorization_sha256"]
    )
    assert authorization["consumed"] is True
    assert authorization["consumed_by_episode"] == report["episode_id"]
    assert authorization["consumed_session_id"] == report["session_id"]
    assert authorization["consumed_level_name"] == report["level_name"]
    assert authorization["consumed_event_line"] == 2
    assert authorization["consumed_monotonic_s"] == 904337.5
    assert authorization["probe_55_authorized"] is False
    issued_bytes = _git_blob(
        bindings["probe_54_authorization_commit"],
        bindings["probe_54_authorization_path"],
    )
    issued = json.loads(issued_bytes)
    assert _sha256_bytes(issued_bytes) == (
        bindings["probe_54_issued_authorization_sha256"]
    )
    assert issued["consumed"] is False
    assert issued["one_use"] is True
    assert issued["maximum_episode_count"] == 1
    assert issued["maximum_retry_count"] == 0
    assert subprocess.check_output(
        [
            "git",
            "rev-parse",
            f"{bindings['probe_54_authorization_commit']}^{{tree}}",
        ],
        cwd=ROOT,
        text=True,
    ).strip() == bindings["probe_54_authorization_tree"]

    assert bindings["raw_evidence_paths"] == report["evidence_paths"]
    assert bindings["raw_evidence_sha256"] == report["evidence_sha256"]
    for key, relative_path in bindings["raw_evidence_paths"].items():
        assert _sha256(ROOT / relative_path) == (
            bindings["raw_evidence_sha256"][key]
        )


def test_probe54_retained_timeline_proves_navigation_depletion_and_amplification():
    audit = _json(AUDIT_PATH)
    report = _transaction_json(REPORT_RELATIVE)
    failure = audit["retained_failure"]
    events = _events(audit)
    indexed = {index: event for index, event in enumerate(events, start=1)}

    assert failure["capability_failure"] is True
    assert failure["infrastructure_failure"] is False
    assert failure["root_cause"] == (
        "navigation_inventory_depletion_caused_portable_station_recovery_gap_"
        "with_planner_timeout_amplification"
    )
    assert failure["planner_timeout_role"] == "secondary_amplification"
    assert report["failure_analysis"]["classification"] == (
        audit["failure_classification"]
    )
    assert report["failure_analysis"]["root_cause"] == failure["root_cause"]
    assert failure["planner_timeout_role"] == "secondary_amplification"
    assert report["failure_analysis"]["secondary_amplification"] == (
        "planner_transport_timeout"
    )
    assert (
        report["failure_analysis"][
            "planner_transport_timeout_is_root_classification"
        ]
        is False
    )

    table_lines = failure["probe_53_table_place_action_lines"]
    assert table_lines == [173, 433]
    for line in table_lines:
        event = indexed[line]
        result = event["data"]["result"]
        assert event["type"] == "action"
        assert event["data"]["action"]["type"] == "place"
        assert event["data"]["action"]["parameters"]["item"] == "crafting_table"
        assert result["success"] is True
        assert result["target_block_before"]["name"] == "air"
        assert result["target_block_after"]["name"] == "crafting_table"
        assert (
            "policy:m4-bm013-bm014-crafting-table-place-local-snapshot-v1"
            in result["action_verification"]["evidence"]
        )
    assert failure["probe_53_table_place_success_count"] == 2
    assert failure["probe_53_table_place_failure_count"] == 0
    assert failure["probe_53_occupied_target_failure_count"] == 0

    replay = failure["same_cell_ordered_mutation_replay"]
    dig = indexed[replay["stone_dig_action_line"]]
    place = indexed[replay["crafting_table_place_action_line"]]
    assert replay["stone_dig_action_line"] < replay["crafting_table_place_action_line"]
    assert dig["data"]["action"] == {
        "type": "dig",
        "parameters": {**replay["position"], "block": "stone"},
    }
    assert dig["data"]["result"]["success"] is True
    assert dig["data"]["result"]["target_block_after"] == {
        "name": "air",
        "type": 0,
        "position": replay["position"],
    }
    assert place["data"]["result"]["placed_position"] == replay["position"]
    assert place["data"]["result"]["target_block_after"]["name"] == (
        replay["ordered_replay_final_block"]
    )

    depletion = failure["navigation_inventory_depletion"]
    navigation = indexed[depletion["action_line"]]
    assert navigation["type"] == "action"
    assert navigation["data"]["action"] == {
        "type": depletion["action_type"],
        "parameters": depletion["target"],
    }
    assert navigation["data"]["result"]["success"] is depletion["action_success"]
    assert navigation["data"]["pre_observation"]["inventory"] == (
        depletion["inventory_before"]
    )
    assert navigation["data"]["post_observation"]["inventory"] == (
        depletion["inventory_after"]
    )
    report_transition = report[
        "portable_station_material_recovery_gap"
    ]["navigation_inventory_transition"]
    assert report_transition["event_line"] == depletion["action_line"]
    assert report_transition["pre_inventory"] == depletion["inventory_before"]
    assert report_transition["post_inventory"] == depletion["inventory_after"]
    assert report_transition["depletion_caused_portable_station_recovery_gap"] is True
    assert (
        depletion["inventory_after"].get("oak_log", 0)
        - depletion["inventory_before"]["oak_log"]
        == depletion["oak_log_delta"]
    )
    assert depletion["portable_station_materials_preserved"] is False

    planner = failure["planner_timeline"]
    first_call = indexed[planner["first_timeout_call_line"]]
    recovery = indexed[planner["transport_recovery_line"]]
    second_call = indexed[planner["second_timeout_call_line"]]
    deadline = indexed[planner["first_unrecovered_transition_line"]]
    assert first_call["type"] == second_call["type"] == "llm_planner_call"
    assert first_call["data"]["call_id"] != second_call["data"]["call_id"]
    assert first_call["data"]["deadline_policy"]["request_timeout_s"] == (
        planner["first_timeout_request_s"]
    )
    assert second_call["data"]["deadline_policy"]["request_timeout_s"] == (
        planner["second_timeout_request_s"]
    )
    assert first_call["data"]["transport_evidence"]["retry_count"] == 0
    assert second_call["data"]["transport_evidence"]["retry_count"] == 0
    assert recovery["type"] == "m4_planner_transport_recovery"
    assert recovery["data"]["same_call_retry_count"] == 0
    assert recovery["data"]["resume_policy"] == (
        "retry_planner_next_cycle_same_goal"
    )
    assert deadline["type"] == "episode_deadline_exceeded"
    assert deadline["data"]["phase"] == planner["deadline_phase"]
    assert deadline["data"]["new_action_suppressed"] is True


def test_probe54_portable_table_audit_binds_ordered_replay_repair_sources():
    audit = _json(AUDIT_PATH)
    report = _transaction_json(REPORT_RELATIVE)
    repair = audit["offline_repair"]
    replay = repair["ordered_mutation_replay"]

    assert repair["policy_id"] == (
        M4_BM013_BM014_PORTABLE_CRAFTING_TABLE_RECOVERY_POLICY_ID
    )
    assert report["offline_repair"]["policy_id"] == repair["policy_id"]
    assert replay["source"] == "successful action events in session order"
    assert replay["successful_place_and_dig_only"] is True
    assert replay["same_coordinate_later_mutation_wins"] is True
    assert (
        replay["probe_54_stone_dig_then_table_place_same_coordinate_retained"]
        is True
    )
    assert replay["removed_or_replaced_table_excluded"] is True
    assert replay["aggregate_delta_fallback_live_enabled"] is False
    assert replay["aggregate_delta_fallback_isolated_offline_only"] is True
    assert replay["ambiguous_aggregate_place_and_remove_same_cell_rejected"] is True

    origin = _audit_origin_commit()
    for key, relative_path in audit["source_paths"].items():
        source_bytes = (
            _git_blob(origin, relative_path)
            if origin
            else (ROOT / relative_path).read_bytes()
        )
        assert _sha256_bytes(source_bytes) == audit["source_sha256"][key]
        assert report["offline_repair"]["source_sha256"][key] == (
            audit["source_sha256"][key]
        )


def test_probe54_portable_table_repair_is_scoped_current_and_fail_closed():
    audit = _json(AUDIT_PATH)
    repair = audit["offline_repair"]
    reclaim = repair["remote_resource_move_reclaim"]
    table_return = repair["historical_table_return"]
    material = repair["material_recovery"]
    execution = repair["execution_path_gates"]
    isolation = repair["policy_isolation"]

    assert reclaim["task_scope"] == ["BM-013", "BM-014"]
    assert reclaim["goal_scope"] == ["collect raw iron", "collect coal"]
    assert reclaim["underlying_next_action_must_be_remote_move_to"] is True
    assert reclaim["crafting_table_must_be_currently_machine_observed"] is True
    assert (
        reclaim["crafting_table_must_be_episode_owned_by_successful_mutation_history"]
        is True
    )
    assert reclaim["maximum_interaction_distance"] == 4.5
    assert reclaim["reclaim_action"] == "dig crafting_table"
    assert reclaim["arbitrary_unowned_table_reclaimed"] is False
    assert reclaim["historical_coordinate_alone_authorizes_reclaim"] is False

    assert table_return["use"] == (
        "navigation target for current reobservation only"
    )
    assert table_return["nearest_retained_episode_owned_position_selected"] is True
    assert table_return["historical_coordinate_treated_as_current_block_observation"] is False
    assert table_return["current_reobservation_required_before_use"] is True
    assert table_return["return_move_requires_distance_above"] == 4.5
    assert table_return["within_4_5_and_not_currently_visible_repeats_navigation"] is False
    assert (
        table_return[
            "within_4_5_and_not_currently_visible_falls_through_to_material_recovery"
        ]
        is True
    )

    assert material["current_machine_observed_oak_log_can_be_dug"] is True
    assert material["historical_or_inferred_oak_log_can_be_dug"] is False
    assert material[
        "no_retained_table_and_no_current_machine_observed_oak_log_status"
    ] == "blocked"
    assert material["blocked_reason_code"] == (
        "portable_crafting_table_recovery_unavailable"
    )
    assert material["blocked_action_count"] == 0
    assert execution["full_think_fallback_suppressed"] is True
    assert execution["suppressed_execution_paths"] == [
        "learned_skill",
        "bm012_machine_step",
        "llm_plan",
        "rule_plan",
        "visual_action_grounding",
    ]
    assert isolation["bm012_generic_crafting_table_behavior_unchanged"] is True
    assert isolation["probe_53_crafting_table_local_snapshot_policy_unchanged"] is True
    assert isolation["furnace_local_snapshot_policy_unchanged"] is True


def test_probe54_portable_table_repair_preserves_controls_and_locks_probe55():
    audit = _json(AUDIT_PATH)
    controls = audit["offline_repair"]["unchanged_controls"]
    validation = audit["offline_validation"]
    decision = audit["decision"]

    assert controls["protocol"] is True
    assert controls["task_contract"] is True
    assert controls["deadline_s"] == 300
    assert controls["model"] == "grok-4.5"
    assert controls["skill_execution_mode"] == "off"
    assert controls["smelt_physics"] is True
    assert controls["success_threshold"] == 3
    assert controls["planner_same_call_retry_count"] == 0
    assert controls["client_retry_count"] == 0
    assert controls["proxy_retry_count"] == 0
    assert controls["provider_transport_policy"] == "single-attempt"

    assert validation["focused_agent_pass_count"] == 26
    assert validation["focused_agent_fail_count"] == 0
    assert validation["audit_pass_count"] == 5
    assert validation["audit_fail_count"] == 0
    assert validation["combined_pass_count"] == 31
    assert validation["combined_fail_count"] == 0
    assert len(validation["covered_boundaries"]) == 11

    assert decision["repair_claimed_complete_offline"] is True
    assert decision["live_validation_complete"] is False
    assert decision["counts_toward_bm014_success"] is False
    assert decision["counts_toward_capability"] is False
    assert decision["bm014_attempt_count"] == 4
    assert decision["bm014_failure_count"] == 3
    assert decision["bm014_eligible_success_count"] == 1
    assert decision["required_success_count"] == 3
    assert decision["remaining_success_count"] == 2
    assert decision["bm014_status"] == "live_observed"
    assert decision["m4_status"] == "live_observed"
    assert (
        decision[
            "next_live_probe_locked_until_evidence_and_repair_commit_is_pushed_and_read_back"
        ]
        is True
    )
    assert decision["probe_55_authorized"] is False
