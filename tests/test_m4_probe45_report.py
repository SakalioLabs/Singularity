import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "workspace" / "evals" / "m4_probe45_report.json"
AUTHORIZATION_PATH = ROOT / "workspace" / "evals" / "m4_probe45_authorization.json"


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


def test_m4_probe45_report_binds_candidate_bound_success():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    authorization = json.loads(AUTHORIZATION_PATH.read_text(encoding="utf-8"))

    assert report["probe_number"] == 45
    assert report["task_id"] == "BM-012"
    assert authorization["consumed"] is True
    assert authorization["consumed_by_episode"] == report["episode_id"]
    assert authorization["consumed_session_id"] == report["session_id"]
    assert authorization["consumed_event_line"] == 2
    assert authorization["next_authorization"] is False

    for name, path in report["evidence_paths"].items():
        assert _sha256(ROOT / path) == report["evidence_sha256"][name]

    assert report["frozen_controls"]["model"] == "grok-4.5"
    assert report["episode_result"]["completed"] is True
    assert report["episode_result"]["termination_reason"] == "terminal_task_verified"
    assert report["episode_result"]["elapsed_s"] == 256.391
    assert report["episode_result"]["deadline_eligible"] is True
    assert report["episode_result"]["planner_call_count"] == 7
    assert report["episode_result"]["schema_valid_real_planner_call_count"] == 7
    assert report["episode_result"]["machine_step_plan_count"] == 34
    assert report["episode_result"]["action_count"] == 41
    assert report["episode_result"]["successful_action_count"] == 34
    assert report["episode_result"]["failed_action_count"] == 7
    assert report["episode_result"]["terminal_inventory"]["raw_iron"] == 8
    assert report["episode_result"]["terminal_inventory"]["stone_pickaxe"] == 1
    assert report["episode_result"]["terminal_health"] == 20
    assert report["behavioral_progression"]["full_stone_pickaxe_loop_completed"] is True
    assert report["behavioral_progression"]["raw_iron_to_eight"] is True
    assert report["decision"]["counts_toward_bm012_success"] is True
    assert report["decision"]["bm012_success_count_after"] == 2
    assert report["decision"]["counts_toward_capability"] is False


def test_probe45_jsonl_proves_machine_step_policy_and_iron_sources():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    events = _events(report)

    assert len(events) == 657
    calls = [event for event in events if event.get("type") == "llm_planner_call"]
    actions = [event for event in events if event.get("type") == "action"]
    machine_steps = [
        event for event in events
        if event.get("type") == "m4_bm012_toolchain_machine_step_plan"
    ]
    iron_digs = [
        event for event in actions
        if event["data"]["action"]["type"] == "dig"
        and event["data"]["action"]["parameters"]["block"] == "iron_ore"
    ]

    assert len(calls) == 7
    assert all(call["data"]["real_llm_call"] is True for call in calls)
    assert all(call["data"]["schema_valid"] is True for call in calls)
    assert len(actions) == 41
    assert len(machine_steps) == 34
    assert machine_steps[2]["_line"] == 191
    assert machine_steps[2]["data"]["place_candidate_bound_policy_id"] == (
        "m4-bm012-machine-step-place-candidate-bound-v1"
    )
    assert machine_steps[2]["data"]["target"] == {
        "reference_position": {"x": 112, "y": 135, "z": -28}
    }
    assert report["behavioral_progression"]["first_action_lines"] == {
        "oak_log_dig": 50,
        "oak_planks_craft": 175,
        "crafting_table_craft": 187,
        "crafting_table_place_success": 201,
        "wooden_pickaxe_craft": 257,
        "wooden_pickaxe_equip": 277,
        "stone_dig": 290,
        "stone_pickaxe_craft": 491,
        "raw_iron_dig": 563,
        "terminal_resource_verification": 651,
    }
    assert [event["_line"] for event in iron_digs] == [
        563,
        575,
        587,
        599,
        611,
        623,
        635,
        647,
    ]
    assert len({tuple(dig["data"]["result"]["target"].values()) for dig in iron_digs}) == 8
    assert all(dig["data"]["result"]["dig_tool_equip"]["passed"] is True for dig in iron_digs)
    assert all(dig["data"]["result"]["pickup_observed"] is True for dig in iron_digs)

    terminal = [event for event in events if event.get("type") == "terminal_resource_verification"]
    assert [event["_line"] for event in terminal] == [651]
    assert terminal[0]["data"]["passed"] is True
    assert terminal[0]["data"]["observed_count"] == 8
    assert terminal[0]["data"]["health"] == 20
    assert terminal[0]["data"]["uninterrupted_survival"] is True


def test_probe45_live_validates_candidate_bound_repair():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    review = report["intervention_review"]
    assert review["policy_id"] == "m4-bm012-machine-step-place-candidate-bound-v1"
    assert review["candidate_bound_repair_live_exercised"] is True
    assert review["probe_44_candidate_drift_recurred"] is False
    assert review["machine_step_place_policy_field_present"] is True
    assert review["yield_result"] == "intervention_exercised_success"

    assert report["resource_acquisition"]["successful_source_action_count"] == 8
    assert report["eligibility"]["eligible"] is True
    assert report["eligibility"]["issue_count"] == 0
    assert report["recovered_noise"]["failed_action_count"] == 7
    assert report["recovered_noise"]["terminal_success_despite_failures"] is True
