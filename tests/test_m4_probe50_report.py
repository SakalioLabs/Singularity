"""Bind the retained Probe 50 BM-013 success report to raw machine evidence."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from singularity.evaluation.m4_protocol import evaluate_m4_episode


ROOT = Path(__file__).resolve().parent.parent
REPORT_PATH = ROOT / "workspace/evals/m4_probe50_report.json"
AUTHORIZATION_PATH = ROOT / "workspace/evals/m4_probe50_authorization.json"


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


def test_probe50_report_binds_single_use_authorization():
    report = _json(REPORT_PATH)
    authorization = _json(AUTHORIZATION_PATH)
    issued = json.loads(_issued_authorization_bytes(report))

    assert report["type"] == "m4_probe_report"
    assert report["task_id"] == "BM-013"
    assert report["probe_number"] == 50
    assert report["episode_id"] == "m4_episode_20260727_111149_e1794e58"
    assert report["session_id"] == "d84b0331-47c"
    assert report["level_name"] == f"{report['episode_id']}_bm013"

    binding = report["authorization"]
    assert hashlib.sha256(_issued_authorization_bytes(report)).hexdigest() == (
        binding["issued_sha256"]
    )
    assert binding["issued_sha256"] == (
        "ae4b61d97ec410b41ee3df276a030e94855194d5f404dfc9b8c76b2f888252c7"
    )
    assert issued["consumed"] is False
    assert issued["next_authorization"] is False
    assert issued["one_use"] is True
    assert issued["maximum_episode_count"] == 1
    assert issued["maximum_retry_count"] == 0
    assert issued["prior_bm013_eligible_success_count"] == 2
    assert issued["remaining_bm013_eligible_success_count_before_probe"] == 1

    assert _sha256(AUTHORIZATION_PATH) == binding["consumed_sha256"]
    assert binding["consumed_sha256"] == (
        "3575b28e4bc5587b44012c01ebb490f2b4c5689b703cd8ee28c9412f8ad3e7a3"
    )
    assert authorization["consumed"] is True
    assert authorization["consumed_by_episode"] == report["episode_id"]
    assert authorization["consumed_session_id"] == report["session_id"]
    assert authorization["consumed_level_name"] == report["level_name"]
    assert authorization["consumed_event_line"] == 2
    assert authorization["consumed_monotonic_s"] == 872164.515
    assert authorization["consumed_at_utc"] == "2026-07-27T03:13:00.537985Z"
    assert binding["probe_51_authorized"] is False


def test_probe50_hashes_and_eligibility_recompute_exactly():
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
        "BM-013",
    )

    assert recomputed == saved
    assert saved["eligible"] is True
    assert saved["success"] is True
    assert saved["issues"] == []
    assert len(saved["checks"]) == 74
    assert sum(check["passed"] is True for check in saved["checks"]) == 74
    assert report["eligibility"]["independent_recomputation_exact_match"] is True


def test_probe50_timeline_planner_actions_and_lifecycle_are_bounded():
    report = _json(REPORT_PATH)
    events = _events(report)
    sealed = _json(ROOT / report["evidence_paths"]["session_json"])
    manifest = _json(ROOT / report["evidence_paths"]["manifest"])

    assert len(events) == 884
    assert len(sealed) == 883
    assert sealed == events[:883]
    assert events[883]["type"] == "memory_manage"

    start = events[1]
    assert start["type"] == "autonomous_start"
    assert start["session"] == report["session_id"]
    assert start["data"]["task_id"] == "BM-013"
    assert start["monotonic_s"] == manifest["episode_started_monotonic"] == 872164.515
    assert manifest["episode_deadline_monotonic"] == 872464.515
    assert manifest["episode_ended_monotonic"] == 872436.515

    episode = report["episode_result"]
    assert episode["elapsed_s"] == 271.922
    assert episode["evidence_seal_duration_s"] == 272.0
    assert episode["deadline_margin_s"] == 28.078
    assert episode["evidence_seal_deadline_margin_s"] == 28.0
    assert episode["per_goal_cycles"] == [6, 2, 5, 13, 14, 3, 4, 5, 7]
    assert episode["goals_completed"] == 9
    assert episode["goals_failed"] == 0
    assert episode["goals_interrupted"] == 0
    assert episode["total_cycles"] == 59
    assert episode["maximum_goal_cycles"] == 14

    calls = [event for event in sealed if event["type"] == "llm_planner_call"]
    assert len(calls) == 1
    assert calls[0]["data"]["call_id"] == "llm-eed4c64d655a46a6"
    assert calls[0]["data"]["real_llm_call"] is True
    assert calls[0]["data"]["schema_valid"] is True
    assert calls[0]["data"]["schema_validation"]["issues"] == []
    assert calls[0]["data"]["transport_evidence"]["attempt_count"] == 1
    assert calls[0]["data"]["transport_evidence"]["retry_count"] == 0
    assert calls[0]["data"]["provider_metadata"]["duration_ms"] == 29140
    assert calls[0]["data"]["provider_metadata"]["total_tokens"] == 4504

    machine_steps = [
        event
        for event in sealed
        if event["type"] == "m4_bm013_bm014_toolchain_machine_step_plan"
    ]
    assert len(machine_steps) == 58
    assert all(
        event["data"]["qualifying_llm_call_id"] == calls[0]["data"]["call_id"]
        and event["data"]["real_llm_call_observed"] is True
        and event["data"]["schema_valid_llm_call_observed"] is True
        for event in machine_steps
    )

    actions = [event for event in sealed if event["type"] == "action"]
    assert len(actions) == 60
    assert sum(event["data"]["result"]["success"] is True for event in actions) == 42
    assert sum(event["data"]["result"]["success"] is not True for event in actions) == 18
    assert all(
        event["data"]["result"]["accepted_within_episode_deadline"] is True
        for event in actions
    )
    assert not [
        event
        for event in actions
        if event["monotonic_s"] > manifest["episode_deadline_monotonic"]
    ]

    observations = [event for event in sealed if event["type"] == "observation"]
    assert len(observations) == 120
    assert min(event["data"]["health"] for event in observations) == 20
    assert min(event["data"]["hunger"] for event in observations) == 20
    assert max(
        event["data"]["player_lifecycle"]["death_count"] for event in observations
    ) == 0
    assert max(
        event["data"]["player_lifecycle"]["respawn_count"] for event in observations
    ) == 0


def test_probe50_smelt_provenance_and_recovered_noise_are_transparent():
    report = _json(REPORT_PATH)
    events = _events(report)
    provenance = report["smelting_provenance"]
    smelt = events[provenance["action_line"] - 1]

    assert smelt["type"] == "action"
    assert smelt["data"]["action"]["type"] == "smelt"
    result = smelt["data"]["result"]
    assert result["success"] is True
    assert result["smelt_attempts"] == 1
    assert result["smelt_retry_count"] == 0
    assert result["automatic_retry"] is False
    assert result["inventory_signed_delta"] == {
        "raw_iron": -1,
        "coal": -1,
        "iron_ingot": 1,
    }
    assert result["output_settled"] is True
    assert result["furnace_slots_empty"] is True
    assert result["furnace_closed"] is True
    assert result["accepted_within_action_deadline"] is True
    assert result["accepted_within_episode_deadline"] is True
    assert result["action_finished_monotonic"] < result["action_deadline_monotonic"]

    terminal = events[
        report["behavioral_progression"]["terminal_task_verification_line"] - 1
    ]
    assert terminal["type"] == "terminal_task_verification"
    assert terminal["data"]["passed"] is True
    assert terminal["data"]["inventory"]["iron_ingot"] == 1

    noise = report["recovered_noise"]
    assert noise["failed_action_count"] == 18
    assert noise["failed_action_types"] == {"move_to": 1, "place": 17}
    assert noise["asynchronous_raw_iron_pickup_line"] == 657
    assert noise["natural_raw_iron_source_provenance_still_complete"] is True
    assert noise["furnace_place_block_update_timeout_line"] == 860
    assert noise["furnace_physically_observed_after_timeout"] is True
    assert noise["eligibility_defect"] is False


def test_probe50_decision_closes_only_bm013_and_keeps_bm014_locked():
    report = _json(REPORT_PATH)
    decision = report["decision"]
    eligibility = report["eligibility"]

    assert eligibility["eligible"] is True
    assert eligibility["success"] is True
    assert eligibility["counts_toward_bm013_success"] is True
    assert eligibility["counts_toward_capability"] is False
    assert eligibility["check_count"] == eligibility["pass_count"] == 74
    assert eligibility["issues"] == []

    assert decision["bm013_success_count_before"] == 2
    assert decision["bm013_success_count_after"] == 3
    assert decision["remaining_success_count"] == 0
    assert decision["bm013_repeat_verified_after_probe"] is True
    assert decision["bm013_status_after"] == "repeat_verified"
    assert decision["m4_status_after"] == "partial"
    assert decision["next_task_id"] == "BM-014"
    assert decision["next_live_probe_locked_until_evidence_commit"] is True
    assert decision["probe_51_authorized"] is False
    assert decision["bm014_authorized"] is False
    assert decision["bm014_locked"] is True
