"""Bind the retained Probe 55 provider-lifecycle transport failure."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "workspace/evals/m4_probe55_report.json"
AUTHORIZATION_PATH = ROOT / "workspace/evals/m4_probe55_authorization.json"
AUTHORIZATION_COMMIT = "c6e900526a0a79b38eac4bf1ebe3948e5b1cfe5a"
AUTHORIZATION_TREE = "fcc68be24e132a7bb2eda09954eb441df77098d0"
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


def _json(path: Path) -> dict:
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


def _events(report: dict) -> list[dict]:
    path = ROOT / report["evidence_paths"]["raw_session_jsonl"]
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_probe55_report_binds_authorization_and_every_raw_artifact():
    report = _json(REPORT_PATH)
    authorization = _json(AUTHORIZATION_PATH)
    issued_bytes = _git_blob(
        AUTHORIZATION_COMMIT,
        AUTHORIZATION_PATH.relative_to(ROOT).as_posix(),
    )
    issued = json.loads(issued_bytes)
    binding = report["authorization"]

    assert report["type"] == "m4_probe_report"
    assert report["schema_version"] == 1
    assert report["task_id"] == "BM-014"
    assert report["probe_number"] == 55
    assert report["episode_id"] == "m4_episode_20260727_220522_099cfa0a"
    assert report["session_id"] == "38fade74-857"
    assert report["level_name"] == f"{report['episode_id']}_bm014"
    assert binding["commit"] == AUTHORIZATION_COMMIT
    assert binding["tree"] == AUTHORIZATION_TREE
    assert subprocess.run(
        ["git", "rev-parse", f"{AUTHORIZATION_COMMIT}^{{tree}}"],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    ).stdout.strip() == AUTHORIZATION_TREE
    assert hashlib.sha256(issued_bytes).hexdigest() == binding["issued_sha256"]
    assert binding["issued_sha256"] == (
        "f8526bbeca23d7b676615d95c2f0eff367244c29a4b4389802116bfee7a67464"
    )
    assert binding["issued_test_sha256"] == hashlib.sha256(
        _git_blob(AUTHORIZATION_COMMIT, "tests/test_m4_probe55_authorization.py")
    ).hexdigest()
    assert issued["consumed"] is False
    assert issued["one_use"] is True
    assert issued["maximum_episode_count"] == 1
    assert issued["maximum_retry_count"] == 0
    assert issued["probe_56_authorized"] is False
    assert _sha256(AUTHORIZATION_PATH) == binding["consumed_sha256"]
    assert _sha256(ROOT / "tests/test_m4_probe55_authorization.py") == (
        binding["consumed_test_sha256"]
    )
    assert authorization["consumed"] is True
    assert authorization["consumed_by_episode"] == report["episode_id"]
    assert authorization["consumed_session_id"] == report["session_id"]
    assert authorization["consumed_level_name"] == report["level_name"]
    assert authorization["probe_56_authorized"] is False

    assert set(report["evidence_paths"]) == set(report["evidence_sha256"])
    assert len(report["evidence_paths"]) == 11
    for key, relative_path in report["evidence_paths"].items():
        assert _sha256(ROOT / relative_path) == report["evidence_sha256"][key]


def test_probe55_authorization_was_consumed_once_at_autonomous_start():
    report = _json(REPORT_PATH)
    authorization = _json(AUTHORIZATION_PATH)
    events = _events(report)
    consumption = report["authorization"]["runtime_consumption"]

    assert len([event for event in events if event["type"] == "autonomous_start"]) == 1
    assert events[0]["type"] == "connect"
    consumed_event = events[1]
    assert consumption["consumed"] is True
    assert consumption["consumed_event_line"] == 2
    assert consumed_event["type"] == consumption["consumed_at"] == (
        "autonomous_start"
    )
    assert consumed_event["session"] == consumption["consumed_session_id"]
    assert consumed_event["monotonic_s"] == consumption["consumed_monotonic_s"]
    assert consumed_event["elapsed_s"] == 8.55
    assert consumption["consumed_at_utc"] == (
        datetime.fromtimestamp(consumed_event["ts"], tz=timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )
    assert consumption["consumed_episode_id"] == report["episode_id"]
    assert consumption["consumed_level_name"] == report["level_name"]
    assert authorization["consumed_event_line"] == consumption[
        "consumed_event_line"
    ]
    assert authorization["consumed_monotonic_s"] == consumption[
        "consumed_monotonic_s"
    ]

    manifest = _json(ROOT / report["evidence_paths"]["manifest"])
    assert manifest["episode_id"] == report["episode_id"]
    assert manifest["session_id"] == report["session_id"]
    assert manifest["level_name"] == report["level_name"]
    assert manifest["runtime_limits"] == {
        "max_duration_s": 300.0,
        "max_goals": 24,
        "max_cycles_per_goal": 40,
    }
    assert manifest["skill_execution_mode"] == "off"


def test_probe55_prior_runtime_blocker_is_not_an_episode_or_attempt():
    report = _json(REPORT_PATH)
    blocker = report["prior_non_episode_preflight_blocker"]
    artifact = _json(ROOT / blocker["path"])

    assert _sha256(ROOT / blocker["path"]) == blocker["sha256"]
    assert blocker["sha256"] == report["evidence_sha256"][
        "prior_runtime_blocker"
    ]
    assert blocker["path"] == report["evidence_paths"]["prior_runtime_blocker"]
    assert artifact["type"] == "m4_runtime_blocker"
    assert artifact["schema_version"] == 1
    assert artifact["generated_at_utc"] == blocker["generated_at_utc"]
    assert artifact["task_id"] == blocker["task_id"] == "BM-014"
    assert artifact["episode_id"] == blocker["prospective_episode_id"]
    assert artifact["level_name"] == blocker["prospective_level_name"]
    assert artifact["blocker"] == blocker["blocker"]
    assert artifact["counts_toward_task_success"] is False
    assert datetime.fromisoformat(
        blocker["generated_at_utc"].replace("Z", "+00:00")
    ) < datetime.fromisoformat(
        report["authorization"]["runtime_consumption"]["consumed_at_utc"].replace(
            "Z",
            "+00:00",
        )
    )
    assert blocker["autonomous_start_present"] is False
    assert blocker["authorization_consumed"] is False
    assert blocker["counts_as_live_episode"] is False
    assert blocker["counts_as_bm014_attempt"] is False
    assert blocker["counts_as_bm014_failure"] is False
    assert (
        blocker["included_in_probe55_episode_preflight_blocker_count"]
        is False
    )


def test_probe55_four_distinct_planner_cycles_all_timed_out_zero_byte():
    report = _json(REPORT_PATH)
    events = _events(report)
    transport = report["planner_transport_evidence"]
    calls = [
        (line, events[line - 1])
        for line in transport["call_lines"]
    ]
    recoveries = [
        (line, events[line - 1])
        for line in transport["recovery_lines"]
    ]

    assert [line for line, _ in calls] == [13, 21, 29, 37]
    assert [event["type"] for _, event in calls] == ["llm_planner_call"] * 4
    assert [event["data"]["call_id"] for _, event in calls] == (
        transport["call_ids"]
    )
    assert len(set(transport["call_ids"])) == 4
    assert [event["data"]["call_index"] for _, event in calls] == [0, 1, 2, 3]
    assert [event["data"]["parent_call_id"] for _, event in calls] == [
        "",
        transport["call_ids"][0],
        transport["call_ids"][1],
        transport["call_ids"][2],
    ]
    assert [event["data"]["deadline_policy"]["request_timeout_s"] for _, event in calls] == (
        transport["request_timeout_s"]
    )
    assert [event["data"]["deadline_policy"]["remaining_before_call_s"] for _, event in calls] == (
        transport["remaining_before_call_s"]
    )

    for _, event in calls:
        data = event["data"]
        attempt = data["transport_evidence"]["attempts"][0]
        assert data["real_llm_call"] is transport["real_llm_call_each"] is False
        assert data["schema_valid"] is transport["schema_valid_each"] is False
        assert data["response_byte_count"] == transport[
            "response_byte_count_each"
        ] == 0
        assert data["response_sha256"] == transport["response_sha256"] == (
            EMPTY_SHA256
        )
        assert data["provider_metadata"]["error_type"] == transport["error_type"]
        assert data["provider_metadata"]["error_chain"] == transport[
            "error_chain"
        ]
        assert data["transport_evidence"]["policy_id"] == (
            transport["transport_policy_id"]
        )
        assert data["transport_evidence"]["attempt_count"] == 1
        assert data["transport_evidence"]["retry_count"] == 0
        assert attempt["attempt_index"] == 0
        assert attempt["success"] is False
        assert attempt["sdk_max_retries"] == 0
        assert attempt["error_type"] == transport["error_type"]
        assert attempt["error_chain"] == transport["error_chain"]

    assert [line for line, _ in recoveries] == [16, 24, 32]
    assert [event["type"] for _, event in recoveries] == [
        "m4_planner_transport_recovery"
    ] * 3
    assert [event["data"]["cycle"] for _, event in recoveries] == [1, 2, 3]
    assert [event["data"]["planner_call_id"] for _, event in recoveries] == (
        transport["call_ids"][:3]
    )
    for _, event in recoveries:
        assert event["data"]["same_call_retry_count"] == 0
        assert event["data"]["resume_policy"] == (
            "retry_planner_next_cycle_same_goal"
        )
        assert event["data"]["recovered"] is True
    assert transport["distinct_cycle_calls"] is True
    assert transport["automatic_same_call_retry"] is False


def test_probe55_zero_action_deadline_and_eligibility_recompute_exactly():
    report = _json(REPORT_PATH)
    events = _events(report)
    result = _json(ROOT / report["evidence_paths"]["result"])
    preparation = _json(ROOT / report["evidence_paths"]["preparation"])
    eligibility = _json(ROOT / report["evidence_paths"]["eligibility"])
    session_json = _json(ROOT / report["evidence_paths"]["session_json"])
    episode = report["episode_result"]

    assert len(events) == episode["session_event_count"] == 45
    assert len(session_json) == episode["session_json_event_count"] == 44
    assert session_json == events[:-1]
    assert events[-1]["type"] == episode["jsonl_tail_event_type"] == (
        "memory_manage"
    )
    assert len([event for event in events if event["type"] == "observation"]) == 5
    assert not [event for event in events if event["type"] == "action"]
    assert len([event for event in events if event["type"] == "plan"]) == 4
    assert all(
        event["data"]["status"] == "error"
        and event["data"]["actions"] == []
        for event in events
        if event["type"] == "plan"
    )

    deadline = events[report["planner_transport_evidence"]["deadline_line"] - 1]
    assert deadline["type"] == "episode_deadline_exceeded"
    assert deadline["data"]["phase"] == "post_planner"
    assert deadline["data"]["new_goal_suppressed"] is True
    assert deadline["data"]["new_action_suppressed"] is True
    assert deadline["data"]["skill_suppressed"] is True
    assert result["completed"] is False
    assert result["termination_reason"] == "episode_deadline"
    assert result["elapsed_s"] == episode["agent_elapsed_s"] == 300.0
    assert result["autonomous_result"]["goals_completed"] == 0
    assert result["autonomous_result"]["goals_failed"] == 1
    assert result["autonomous_result"]["total_cycles"] == 4
    assert result["autonomous_result"]["summary"]["action_count"] == 0
    assert result["terminal_state"]["inventory"] == {}
    assert preparation["planner_provider_controls"]["call_count"] == 4
    assert preparation["planner_provider_controls"]["real_call_count"] == 0
    assert preparation["planner_provider_controls"][
        "schema_valid_real_call_count"
    ] == 0
    assert preparation["action_count"] == 0

    assert report["eligibility"]["issues"] == eligibility["issues"]
    assert len(eligibility["checks"]) == report["eligibility"]["check_count"] == 74
    assert sum(check["passed"] for check in eligibility["checks"]) == (
        report["eligibility"]["pass_count"]
    ) == 60
    assert len(eligibility["issues"]) == report["eligibility"]["issue_count"] == 14
    assert eligibility["eligible"] is False
    assert eligibility["success"] is False
    assert report["eligibility"]["counts_toward_bm014_success"] is False
    assert report["eligibility"]["counts_toward_capability"] is False


def test_probe55_classification_is_cautious_and_counts_live_failure():
    report = _json(REPORT_PATH)
    preflight = _json(ROOT / report["evidence_paths"]["preflight"])
    assessment = report["provider_lifecycle_assessment"]
    failure = report["failure_analysis"]
    decision = report["decision"]

    assert preflight["passed"] is True
    assert preflight["validation"]["issues"] == []
    assert report["episode_preflight_assessment"]["preflight_blocker"] is False
    assert report["episode_preflight_assessment"]["preflight_blocker_count"] == 0
    assert (
        report["episode_preflight_assessment"][
            "preflight_blocker_counts_as_bm014_attempt"
        ]
        is False
    )
    assert (
        report["episode_preflight_assessment"][
            "preflight_blocker_counts_as_bm014_failure"
        ]
        is False
    )

    assert assessment["classification"] == (
        failure["classification"]
    ) == "provider_lifecycle_transport_failure"
    assert assessment["root_cause_status"] == (
        failure["infrastructure_root_cause_status"]
    ) == "candidate"
    assert failure["infrastructure_failure"] is True
    assert assessment["raw_episode_support"] == {
        "four_consecutive_api_timeout_errors": True,
        "all_responses_zero_bytes": True,
        "real_planner_response_count": 0,
        "schema_valid_real_planner_response_count": 0,
        "gameplay_action_count": 0,
        "preflight_passed_before_episode": True,
        "minecraft_bot_connected_at_terminal": True,
    }
    external = assessment["external_terminal_observation"]
    assert external["source"] == "operator_terminal_observation"
    assert external["provider_runtime"] == "WSL"
    assert external["observed_state"] == "provider_stopped_before_terminal_review"
    assert external["embedded_in_retained_episode_bundle"] is False
    assert external["correlation_only"] is True
    host = assessment["external_host_filesystem_diagnosis"]
    assert host["source"] == "operator_verified_host_diagnostics"
    assert host["embedded_in_retained_episode_bundle"] is False
    assert host["external_infrastructure_failure_confirmed"] is True
    assert host["first_offline_e2fsck_completed"] is True
    assert host["forced_read_only_e2fsck_exit_code"] == 0
    assert host["subsequent_mount_error_dmesg_monotonic_s"] == 308510.351
    assert host["subsequent_mount_error"] == (
        "ext4_read_block_bitmap_nowait group 1782: -74"
    )
    assert host["journal_aborted"] is True
    assert host["filesystem_remounted_read_only"] is True
    assert host["tune2fs_filesystem_state"] == "clean with errors"
    assert host["second_offline_e2fsck_completed"] is False
    assert host["second_offline_e2fsck_blocker"] == (
        "distro_D_state_and_device_still_in_use"
    )
    assert host["repair_complete"] is False
    assert assessment["required_recovery_gates"] == {
        "offline_filesystem_check_completed_while_unmounted": False,
        "filesystem_clean_without_errors": False,
        "persistent_provider_keepalive_verified": False,
        "chat_completions_liveness_verified": False,
        "all_passed": False,
    }
    assert assessment["provider_lifecycle_gate_required_before_next_live_authorization"] is True
    assert assessment["provider_recovery_complete"] is False
    assert assessment["agent_source_change_justified"] is False
    assert assessment["agent_source_modified"] is False
    assert assessment["portable_table_policy_live_exercised"] is False
    assert assessment["portable_table_policy_live_rejected"] is False
    assert assessment["portable_table_policy_measurement_status"] == (
        "not_exercised_due_to_zero_actions"
    )

    assert failure["no_agent_action_executed"] is True
    assert failure["no_capability_behavior_exercised"] is True
    assert failure["portable_table_repair_not_exercised"] is True
    assert failure["preflight_blocker"] is False
    assert failure["preflight_blocker_counts_as_bm014_attempt"] is False
    assert failure["preflight_blocker_counts_as_bm014_failure"] is False
    assert failure[
        "authorization_consumed_live_episode_counts_as_bm014_attempt"
    ] is True
    assert failure[
        "authorization_consumed_live_episode_counts_as_bm014_failure"
    ] is True
    assert failure["counts_as_bm014_attempt"] is True
    assert failure["counts_as_bm014_failure"] is True

    assert decision["counts_toward_bm014_success"] is False
    assert decision["counts_toward_capability"] is False
    assert decision["bm014_attempt_count_before"] == 4
    assert decision["bm014_attempt_count_after"] == 5
    assert decision["bm014_failure_count_before"] == 3
    assert decision["bm014_failure_count_after"] == 4
    assert decision["bm014_success_count_before"] == 1
    assert decision["bm014_success_count_after"] == 1
    assert decision["remaining_success_count"] == 2
    assert decision["bm014_status_after"] == "live_observed"
    assert decision["m4_status_after"] == "live_observed"
    assert decision["next_authorization"] is False
    assert decision["probe_56_authorized"] is False


def test_probe55_report_updates_canonical_ledger_and_capability_state():
    report = _json(REPORT_PATH)
    ledger = _json(ROOT / "workspace/evals/m4_failure_ledger.json")
    capability = _json(
        ROOT / "workspace/evals/capability_evidence_current.json"
    )
    gate = ledger["current_gate"]
    m4 = next(phase for phase in capability["phases"] if phase["id"] == "M4")
    bm014 = next(
        benchmark
        for benchmark in m4["benchmarks"]
        if benchmark["task_id"] == "BM-014"
    )

    assert ledger["live_episode_count_under_current_protocol"] == 31
    assert gate["live_episode_count_under_current_protocol"] == 31
    assert gate["latest_episode"] == report["episode_id"]
    assert gate["latest_accepted_episode"] == (
        "m4_episode_20260727_153112_f28d04d6"
    )
    assert gate["bm014_probe_55_consumed"] is True
    assert gate["bm014_probe_55_consumed_episode"] == report["episode_id"]
    assert gate["bm014_probe_55_consumed_session_id"] == report["session_id"]
    assert gate["bm014_probe_55_consumed_level_name"] == report["level_name"]
    assert gate["bm014_probe_55_consumed_event_line"] == 2
    assert gate["bm014_probe_55_report_sha256"] == _sha256(REPORT_PATH)
    assert gate["bm014_probe_55_report_test_sha256"] == _sha256(
        Path(__file__)
    )
    assert gate["bm014_probe_55_report_test_pass_count"] == 7
    assert gate["bm014_probe_55_eligible"] is False
    assert gate["bm014_probe_55_success"] is False
    assert gate["bm014_probe_55_counts_toward_success"] is False
    assert gate["bm014_probe_55_counts_toward_capability"] is False
    assert gate["bm014_probe_55_counts_toward_attempt"] is True
    assert gate["bm014_probe_55_counts_toward_failure"] is True
    assert gate["bm014_probe_55_preflight_blocker"] is False
    assert gate["bm014_probe_55_preflight_blocker_count"] == 0
    assert gate[
        "bm014_probe_55_prior_runtime_blocker_included_in_episode_preflight_blocker_count"
    ] is False
    assert gate["bm014_probe_55_failure_classification"] == (
        "provider_lifecycle_transport_failure"
    )
    assert gate["bm014_probe_55_external_host_filesystem_failure_confirmed"] is True
    assert gate["bm014_probe_55_provider_recovery_complete"] is False
    assert gate["bm014_probe_55_required_offline_filesystem_gate_passed"] is False
    assert gate["bm014_probe_55_required_persistent_keepalive_gate_passed"] is False
    assert gate["bm014_probe_55_required_chat_liveness_gate_passed"] is False
    assert gate["bm014_probe_55_evidence_pending_push"] is True
    assert gate["bm014_probe_55_evidence_remote_readback_passed"] is False
    assert gate["bm014_attempt_count"] == 5
    assert gate["bm014_failure_count"] == 4
    assert gate["bm014_success_count"] == 1
    assert gate["bm014_remaining_eligible_success_count"] == 2
    assert gate["bm014_status"] == gate["m4_status"] == "live_observed"
    assert gate["bm014_authorized"] is False
    assert gate["bm014_locked"] is True
    assert gate["bm014_probe_56_authorized"] is False

    assert m4["status"] == "live_observed"
    assert bm014["attempts"] == 5
    assert bm014["failures"] == 4
    assert bm014["successes"] == 1
    assert bm014["repeats_required"] == 3
    assert bm014["evidence_refs"][-1] == (
        "38fade74-857:"
        "logs/benchmarks/m4/m4_episode_20260727_220522_099cfa0a/session.json"
    )
