import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "workspace" / "evals" / "m4_probe39_report.json"
AUTHORIZATION_PATH = ROOT / "workspace" / "evals" / "m4_probe39_authorization.json"


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


def test_m4_probe39_report_binds_grok_bm012_failure():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    authorization = json.loads(AUTHORIZATION_PATH.read_text(encoding="utf-8"))

    assert report["probe_number"] == 39
    assert report["task_id"] == "BM-012"
    assert authorization["consumed"] is True
    assert authorization["consumed_by_episode"] == report["episode_id"]
    assert authorization["next_authorization"] is False

    for name, path in report["evidence_paths"].items():
        assert _sha256(ROOT / path) == report["evidence_sha256"][name]

    assert report["frozen_controls"]["model"] == "grok-4.5"
    assert report["frozen_controls"]["provider_modalities"] == ["text", "image"]
    assert report["frozen_controls"]["runtime_modalities"] == ["text"]
    assert report["episode_result"]["completed"] is False
    assert report["episode_result"]["termination_reason"] == "episode_deadline"
    assert report["episode_result"]["planner_call_count"] == 27
    assert report["episode_result"]["real_planner_call_count"] == 24
    assert report["episode_result"]["schema_valid_real_planner_call_count"] == 24
    assert report["episode_result"]["action_count"] == 23
    assert report["episode_result"]["successful_action_count"] == 21
    assert report["episode_result"]["failed_action_count"] == 2
    assert report["episode_result"]["terminal_inventory"]["cobblestone"] == 3
    assert "stone_pickaxe" not in report["episode_result"]["terminal_inventory"]
    assert report["episode_result"]["terminal_health"] == 20
    assert report["behavioral_progression"]["wooden_pickaxe_to_three_cobblestone"] is True
    assert report["behavioral_progression"]["full_stone_pickaxe_loop_completed"] is False
    assert report["decision"]["counts_toward_bm012_success"] is False
    assert report["decision"]["bm012_success_count_after"] == 1
    assert report["decision"]["counts_toward_capability"] is False


def test_probe39_jsonl_exposes_occupied_target_replan_feedback_gap():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    events = _events(report)

    assert len(events) == 643
    calls = [event for event in events if event.get("type") == "llm_planner_call"]
    real_calls = [call for call in calls if call["data"]["real_llm_call"]]
    actions = [event for event in events if event.get("type") == "action"]

    assert len(calls) == 27
    assert len(real_calls) == 24
    assert sum(call["data"]["schema_valid"] is True for call in real_calls) == 24
    assert len(actions) == 23
    assert sum(action["data"]["result"]["success"] is True for action in actions) == 21

    first_failed_place = events[521]
    assert first_failed_place["_line"] == 522
    assert first_failed_place["data"]["action"]["parameters"] == {
        "item": "crafting_table",
        "x": 112,
        "y": 132,
        "z": -29,
    }
    first_result = first_failed_place["data"]["result"]
    assert first_result["success"] is False
    assert first_result["duration_ms"] == 0
    assert first_result["action_verification"]["policy_id"] == (
        "m4-place-target-occupancy-v1"
    )
    assert first_result["action_verification"]["required"] == {
        "target_position": {"x": 112, "y": 133, "z": -29},
        "target_state": "air_or_replaceable",
    }
    assert "choose a different reference block" in first_result["replan_reason"]

    replan = events[531]
    assert replan["_line"] == 532
    assert replan["data"]["actions"] == [{
        "type": "place",
        "parameters": {"item": "crafting_table", "x": 114, "y": 132, "z": -32},
    }]
    feedback = replan["data"]["place_replan_feedback_grounding"]
    assert feedback["activated"] is False
    assert feedback["reason"] == "no_pending_place_replan_feedback"

    backend_failed_place = events[542]
    assert backend_failed_place["_line"] == 543
    backend_result = backend_failed_place["data"]["result"]
    assert backend_result["success"] is False
    assert backend_result["target_occupancy_policy_id"] == (
        "m4-place-target-occupancy-v1"
    )
    assert backend_result["target_block_before"]["name"] == "gravel"
    assert backend_result["duration_ms"] == 0
    assert backend_result["requires_replan"] is True

    blocker = report["principal_blocker"]
    assert blocker["failure_layer"] == "m4_place_target_occupancy_replan_feedback_gap"
    assert blocker["next_replan_reference_was_adjacent_candidate"] is False
    assert blocker["backend_failed_closed_without_mutation"] is True
    assert blocker["task_deadline_interrupt_lines_after_backend_failure"] == [
        558,
        574,
        590,
    ]


def test_probe39_offline_repair_rejects_gravel_jump_before_execution():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    repair = report["offline_repair"]
    assert repair["policy_id"] == "m4-place-occupied-target-adjacent-replan-feedback-v1"
    assert repair["ordinary_occupied_targets_now_emit_adjacent_candidates"] is True
    assert repair["ordinary_occupied_targets_now_call_request_place_replan"] is True
    assert repair["probe39_non_candidate_gravel_reference_rejected_before_execution"] is True
    assert repair["protocol_changed"] is False
    assert repair["task_contract_changed"] is False
    assert repair["deadline_policy_changed"] is False
    assert repair["success_threshold_changed"] is False
    assert repair["validated_offline"] is True
