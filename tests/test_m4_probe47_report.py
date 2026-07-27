import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT_RELATIVE = "workspace/evals/m4_probe47_report.json"
REPORT_PATH = ROOT / REPORT_RELATIVE
AUTHORIZATION_PATH = ROOT / "workspace" / "evals" / "m4_probe47_authorization.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _report_origin_commit() -> str:
    return subprocess.check_output(
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
    ).splitlines()[-1]


def _git_sha256(commit: str, path: str) -> str:
    payload = subprocess.check_output(
        ["git", "show", f"{commit}:{Path(path).as_posix()}"],
        cwd=ROOT,
    )
    return hashlib.sha256(payload).hexdigest()


def _events(report: dict) -> list[dict]:
    events = []
    raw_path = ROOT / report["evidence_paths"]["raw_session_jsonl"]
    for line_number, line in enumerate(
        raw_path.read_text(encoding="utf-8").splitlines(),
        1,
    ):
        if not line.strip():
            continue
        event = json.loads(line)
        event["_line"] = line_number
        events.append(event)
    return events


def test_m4_probe47_report_binds_first_bm013_failure():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    authorization = json.loads(AUTHORIZATION_PATH.read_text(encoding="utf-8"))

    assert report["probe_number"] == 47
    assert report["task_id"] == "BM-013"
    assert authorization["consumed"] is True
    assert authorization["consumed_by_episode"] == report["episode_id"]
    assert authorization["consumed_session_id"] == report["session_id"]
    assert authorization["consumed_event_line"] == 2
    assert authorization["next_authorization"] is False
    assert report["authorization"]["maximum_episode_count"] == 1
    assert report["authorization"]["maximum_retry_count"] == 0

    for name, path in report["evidence_paths"].items():
        assert _sha256(ROOT / path) == report["evidence_sha256"][name]

    blocker = report["pre_episode_infrastructure_blocker"]
    for name, path in blocker["evidence_paths"].items():
        assert _sha256(ROOT / path) == blocker["evidence_sha256"][name]

    controls = report["frozen_controls"]
    assert controls["task_contract_id"] == "m4-bm013-smelting-contract-v1"
    assert controls["max_duration_s"] == 300
    assert controls["python"] == "3.12.8"
    assert controls["planner_retry_count"] == 0
    assert controls["skill_execution_mode"] == "off"

    result = report["episode_result"]
    assert result["completed"] is False
    assert result["termination_reason"] == "episode_deadline"
    assert result["goals_completed"] == 2
    assert result["goals_failed"] == 1
    assert result["planner_call_count"] == 32
    assert result["schema_valid_real_planner_call_count"] == 30
    assert result["planner_timeout_call_count"] == 2
    assert result["machine_step_plan_count"] == 12
    assert result["action_count"] == 14
    assert result["successful_action_count"] == 14
    assert result["failed_action_count"] == 0
    assert result["active_episode_death_count"] == 0

    assert report["eligibility"]["check_count"] == 74
    assert report["eligibility"]["pass_count"] == 66
    assert report["decision"]["bm013_success_count_after"] == 0
    assert report["decision"]["bm014_locked"] is True

    repair = report["offline_repair"]
    assert repair["status"] == "completed"
    assert repair["policy_id"] == "m4-inventory-purpose-clause-grounding-v1"
    assert repair["validated_offline"] is True
    assert repair["explicit_followup_actions_remain_binding"] is True
    origin_commit = _report_origin_commit()
    for path, expected_sha256 in repair["source_sha256"].items():
        assert _git_sha256(origin_commit, path) == expected_sha256


def test_probe47_jsonl_exposes_purpose_clause_inventory_binding_gap():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    events = _events(report)

    assert len(events) == 465
    assert events[1]["_line"] == 2
    assert events[1]["type"] == "autonomous_start"
    assert events[1]["monotonic_s"] == 863540.828

    wooden_machine_step = events[203]
    assert wooden_machine_step["_line"] == 204
    assert wooden_machine_step["type"] == (
        "m4_bm013_bm014_toolchain_machine_step_plan"
    )
    assert wooden_machine_step["data"]["reason"] == (
        "craft_wooden_pickaxe_from_verified_materials"
    )

    wooden_action = events[211]
    assert wooden_action["_line"] == 212
    assert wooden_action["type"] == "action"
    assert wooden_action["data"]["action"]["parameters"]["item"] == "wooden_pickaxe"
    assert wooden_action["data"]["result"]["success"] is True
    assert wooden_action["data"]["post_observation"]["inventory"]["wooden_pickaxe"] == 1

    completion_planner_call = events[216]
    assert completion_planner_call["_line"] == 217
    assert completion_planner_call["type"] == "llm_planner_call"
    assert completion_planner_call["data"]["real_llm_call"] is True
    assert completion_planner_call["data"]["schema_valid"] is True

    completion_plan = events[217]
    assert completion_plan["_line"] == 218
    assert completion_plan["type"] == "plan"
    assert completion_plan["data"]["status"] == "complete"
    assert completion_plan["data"]["actions"] == []

    first_false_verification = events[220]
    assert first_false_verification["_line"] == 221
    assert first_false_verification["type"] == "goal_verification"
    assert first_false_verification["data"]["goal"] == (
        "Craft a wooden pickaxe for cobblestone acquisition"
    )
    assert first_false_verification["data"]["achieved"] is False
    assert first_false_verification["data"]["target_inventory"] == {
        "wooden_pickaxe": 1,
        "cobblestone": 1,
    }
    assert first_false_verification["data"]["missing"] == [
        "need 1 cobblestone, have 0"
    ]

    events_after_wooden_pickaxe = [
        event for event in events if event["_line"] > wooden_action["_line"]
    ]
    assert not [
        event for event in events_after_wooden_pickaxe
        if event["type"] == "action"
    ]
    repeated_false = [
        event for event in events
        if event["type"] == "goal_verification"
        and event["data"].get("goal")
        == "Craft a wooden pickaxe for cobblestone acquisition"
        and event["data"].get("achieved") is False
    ]
    assert len(repeated_false) == 29
    assert [event["_line"] for event in repeated_false] == report[
        "principal_blocker"
    ]["repeated_false_goal_verification_lines"]

    planner_calls_after = [
        event for event in events_after_wooden_pickaxe
        if event["type"] == "llm_planner_call"
    ]
    assert len(planner_calls_after) == 31
    assert len([
        event for event in planner_calls_after
        if event["data"].get("real_llm_call")
        and event["data"].get("schema_valid")
    ]) == 29
    assert len([
        event for event in planner_calls_after
        if event["data"].get("error") == "Request timed out."
    ]) == 2

    deadline = events[458]
    assert deadline["_line"] == 459
    assert deadline["type"] == "episode_deadline_exceeded"
    assert deadline["data"]["elapsed_s"] == 300.015
    assert deadline["data"]["new_action_suppressed"] is True
    assert deadline["data"]["new_goal_suppressed"] is True

    blocker = report["principal_blocker"]
    episode_start = events[1]["monotonic_s"]
    for key, line in (
        ("goal_selection_episode_elapsed_s", 150),
        ("wooden_pickaxe_machine_step_episode_elapsed_s", 204),
        ("wooden_pickaxe_action_episode_elapsed_s", 212),
        ("schema_valid_completion_planner_episode_elapsed_s", 217),
        ("completion_plan_episode_elapsed_s", 218),
        ("first_false_goal_verification_episode_elapsed_s", 221),
    ):
        assert round(events[line - 1]["monotonic_s"] - episode_start, 3) == blocker[key]


def test_probe47_pre_episode_runtime_blocker_did_not_consume_authorization():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    blocker = report["pre_episode_infrastructure_blocker"]
    preflight = json.loads(
        (ROOT / blocker["evidence_paths"]["preflight"]).read_text(encoding="utf-8")
    )
    blocker_record = json.loads(
        (ROOT / blocker["evidence_paths"]["blocker"]).read_text(encoding="utf-8")
    )

    assert preflight["passed"] is False
    assert preflight["validation"]["issues"] == ["runtime_versions"]
    assert preflight["runtime_versions"]["python"] == "3.13.5"
    assert blocker_record["counts_toward_task_success"] is False
    assert blocker["autonomous_start_absent"] is True
    assert blocker["authorization_consumed"] is False
    assert blocker["protocol_changed"] is False
    assert blocker["source_changed"] is False
