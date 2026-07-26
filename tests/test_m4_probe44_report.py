import collections
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "workspace" / "evals" / "m4_probe44_report.json"
AUTHORIZATION_PATH = ROOT / "workspace" / "evals" / "m4_probe44_authorization.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _events(report: dict) -> list[dict]:
    events = []
    for line_number, line in enumerate(
        (ROOT / report["evidence_paths"]["raw_session_jsonl"]).read_text(
            encoding="utf-8"
        ).splitlines(),
        1,
    ):
        if not line.strip():
            continue
        event = json.loads(line)
        event["_line"] = line_number
        events.append(event)
    return events


def test_m4_probe44_report_binds_grok_candidate_drift_failure():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    authorization = json.loads(AUTHORIZATION_PATH.read_text(encoding="utf-8"))

    assert report["probe_number"] == 44
    assert report["task_id"] == "BM-012"
    assert authorization["consumed"] is True
    assert authorization["consumed_by_episode"] == report["episode_id"]
    assert authorization["consumed_session_id"] == report["session_id"]
    assert authorization["consumed_event_line"] == 2
    assert authorization["next_authorization"] is False

    for name, path in report["evidence_paths"].items():
        assert _sha256(ROOT / path) == report["evidence_sha256"][name]

    assert report["frozen_controls"]["model"] == "grok-4.5"
    assert report["frozen_controls"]["provider_modalities"] == ["text", "image"]
    assert report["frozen_controls"]["runtime_modalities"] == ["text"]
    assert report["episode_result"]["completed"] is False
    assert report["episode_result"]["termination_reason"] == "episode_deadline"
    assert report["episode_result"]["planner_call_count"] == 9
    assert report["episode_result"]["schema_valid_real_planner_call_count"] == 9
    assert report["episode_result"]["machine_step_plan_count"] == 240
    assert report["episode_result"]["action_count"] == 249
    assert report["episode_result"]["successful_action_count"] == 11
    assert report["episode_result"]["failed_action_count"] == 238
    assert report["episode_result"]["action_verifier_accept_count"] == 249
    assert report["episode_result"]["action_verifier_reject_count"] == 0
    assert report["behavioral_progression"]["planks_to_crafting_table"] is True
    assert report["behavioral_progression"]["crafting_table_placed"] is False
    assert report["decision"]["counts_toward_bm012_success"] is False
    assert report["decision"]["bm012_success_count_after"] == 1


def test_probe44_jsonl_exposes_candidate_drift_without_same_reference_loop():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    events = _events(report)

    assert len(events) == 3854
    actions = [event for event in events if event.get("type") == "action"]
    assert len(actions) == 249
    place_actions = [
        event for event in actions
        if event["data"]["action"]["type"] == "place"
    ]
    assert len(place_actions) == 237
    assert all(event["data"]["result"]["success"] is False for event in place_actions)

    references = collections.Counter(
        (
            event["data"]["action"]["parameters"]["x"],
            event["data"]["action"]["parameters"]["y"],
            event["data"]["action"]["parameters"]["z"],
        )
        for event in place_actions
    )
    assert len(references) == 167
    assert max(references.values()) == 3
    assert any(x >= 170 for x, _y, _z in references)

    errors = collections.Counter(
        event["data"]["result"]["error"] for event in place_actions
    )
    assert errors["placement target is occupied by stone"] == 201
    assert errors["placement target is occupied by coal_ore"] == 16
    assert errors["placement target is occupied by dirt"] == 5
    assert sum(
        count for error, count in errors.items()
        if "blockUpdate" in error or "timeout" in error
    ) == 15

    machine_steps = [
        event for event in events
        if event.get("type") == "m4_bm012_toolchain_machine_step_plan"
    ]
    assert len(machine_steps) == 240
    assert machine_steps[0]["_line"] == 154
    assert machine_steps[0]["data"]["reason"] == "craft_oak_planks_for_crafting_table"
    assert machine_steps[2]["_line"] == 178
    assert machine_steps[2]["data"]["reason"] == (
        "place_owned_crafting_table_at_verified_reference"
    )
    assert machine_steps[2]["data"]["place_feedback_policy_id"] == (
        "m4-bm012-machine-step-place-feedback-v1"
    )
    assert "place_candidate_bound_policy_id" not in machine_steps[2]["data"]

    assert place_actions[0]["_line"] == 187
    assert events[3766]["_line"] == 3767
    assert events[3766]["type"] == "runtime_interrupt"
    assert events[3766]["data"]["reason"] == "dusk_shelter_required"
    assert events[3839]["_line"] == 3840
    assert events[3839]["type"] == "episode_deadline_exceeded"


def test_probe44_offline_repair_bounds_table_place_candidates():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    blocker = report["principal_blocker"]
    assert blocker["failure_layer"] == (
        "m4_bm012_machine_step_place_candidate_drift_gap"
    )
    assert blocker["probe43_same_reference_failure_recurred"] is False
    assert blocker["place_feedback_policy_exercised"] is True
    assert blocker["near_ground_sorting_missing_before_repair"] is True
    assert blocker["target_occupancy_feedback_consumed_before_repair"] is False

    repair = report["offline_repair"]
    assert repair["policy_id"] == (
        "m4-bm012-machine-step-place-candidate-bound-v1"
    )
    assert repair["place_candidates_source_limited"] is True
    assert repair["candidate_distance_limit_blocks"] == 6.0
    assert repair["failed_place_targets_excluded"] is True
    assert repair["sort_distance_first"] is True
    assert repair["machine_step_evidence_policy_field_added"] is True
    assert repair["protocol_changed"] is False
    assert repair["task_contract_changed"] is False
    assert repair["validated_offline"] is True

    assert _sha256(ROOT / "src" / "singularity" / "core" / "agent.py") == (
        repair["source_sha256"]["agent"]
    )
    assert _sha256(ROOT / "tests" / "test_m4_deadline.py") == (
        repair["source_sha256"]["m4_deadline_tests"]
    )
