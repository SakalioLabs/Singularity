import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "workspace" / "evals" / "m4_probe48_report.json"
AUTHORIZATION_PATH = ROOT / "workspace" / "evals" / "m4_probe48_authorization.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


def _nearby_block(event: dict, name: str) -> dict | None:
    data = event.get("data", event)
    return next(
        (
            block
            for block in data.get("nearby_blocks", [])
            if block["name"] == name
        ),
        None,
    )


def test_m4_probe48_report_binds_first_eligible_bm013_success():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    authorization = json.loads(AUTHORIZATION_PATH.read_text(encoding="utf-8"))

    assert report["probe_number"] == 48
    assert report["task_id"] == "BM-013"
    assert report["episode_id"] == "m4_episode_20260727_094022_cddca052"
    assert report["session_id"] == "dd16c2cf-ae2"

    assert authorization["consumed"] is True
    assert authorization["consumed_by_episode"] == report["episode_id"]
    assert authorization["consumed_session_id"] == report["session_id"]
    assert authorization["consumed_event_line"] == 2
    assert authorization["consumed_monotonic_s"] == 866646.25
    assert authorization["consumed_at_utc"] == "2026-07-27T01:41:02.271263Z"
    assert authorization["next_authorization"] is False
    assert report["authorization"]["commit"] == (
        "413497370208532d9831ef0914767e3e01fbbdee"
    )
    assert report["authorization"]["maximum_episode_count"] == 1
    assert report["authorization"]["maximum_retry_count"] == 0
    assert report["authorization"]["probe_49_authorized"] is False
    assert report["authorization"]["issued_sha256"] == (
        "693db6b27ad98e47fad9144f0a982c4db576867698e2e2fa2baf799f0cc65dc5"
    )
    assert report["authorization"]["consumed_sha256"] == _sha256(
        AUTHORIZATION_PATH
    )
    assert report["authorization"]["consumed_episode_id"] == report["episode_id"]
    assert report["authorization"]["consumed_session_id"] == report["session_id"]
    assert report["authorization"]["consumed_level_name"] == report["level_name"]

    for name, path in report["evidence_paths"].items():
        assert _sha256(ROOT / path) == report["evidence_sha256"][name]

    controls = report["frozen_controls"]
    assert controls["protocol_sha256"] == authorization["protocol_sha256"]
    assert _sha256(
        ROOT / "src" / "singularity" / "data" / "m4_protocol.json"
    ) == controls["protocol_sha256"]
    assert controls["task_contract_id"] == "m4-bm013-smelting-contract-v1"
    assert controls["task_contract_sha256"] == authorization[
        "task_contract_sha256"
    ]
    assert _sha256(
        ROOT / "src" / "singularity" / "data" / "m4_bm013_protocol.json"
    ) == controls["task_contract_sha256"]
    assert controls["max_duration_s"] == 300
    assert controls["max_total_cycles"] == 320
    assert controls["python"] == "3.12.8"
    assert controls["planner_retry_count"] == 0
    assert controls["proxy_retry_count"] == 0
    assert controls["skill_execution_mode"] == "off"

    result = report["episode_result"]
    assert result["completed"] is True
    assert result["termination_reason"] == "terminal_task_verified"
    assert result["elapsed_s"] == 257.031
    assert result["deadline_margin_s"] == 42.969
    assert result["evidence_seal_duration_s"] == 257.093
    assert result["evidence_seal_deadline_margin_s"] == 42.907
    assert result["deadline_eligible"] is True
    assert result["goals_completed"] == 9
    assert result["goals_failed"] == 0
    assert result["total_cycles"] == 71
    assert result["per_goal_cycles"] == [6, 2, 5, 13, 14, 3, 2, 9, 17]
    assert result["maximum_goal_cycles"] == 17
    assert result["planner_call_count"] == 1
    assert result["schema_valid_real_planner_call_count"] == 1
    assert result["machine_step_plan_count"] == 70
    assert result["action_count"] == 72
    assert result["successful_action_count"] == 41
    assert result["failed_action_count"] == 31
    assert result["action_verifier_accept_count"] == 72
    assert result["goal_verification_accepted_count"] == 9
    assert result["terminal_inventory"]["iron_ingot"] == 1
    assert result["terminal_health"] == 20
    assert result["terminal_food"] == 20
    assert result["terminal_bot_connected"] is True
    assert result["active_episode_death_count"] == 0
    assert result["active_episode_respawn_count"] == 0

    assert report["survival_evidence"] == {
        "observation_count": 144,
        "minimum_health": 20,
        "minimum_food": 20,
        "lifecycle_event_count": 1,
        "maximum_death_count": 0,
        "maximum_respawn_count": 0,
        "uninterrupted_survival": True,
        "terminal_bot_connected": True,
    }

    assert report["eligibility"] == {
        "eligible": True,
        "success": True,
        "progress_gate_passed": True,
        "counts_toward_bm013_success": True,
        "counts_toward_capability": False,
        "check_count": 74,
        "pass_count": 74,
        "issue_count": 0,
        "issues": [],
    }


def test_probe48_jsonl_proves_repair_policy_live_and_full_goal_chain():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    events = _events(report)

    assert len(events) == 1051
    assert events[1]["_line"] == 2
    assert events[1]["type"] == "autonomous_start"
    assert events[1]["monotonic_s"] == 866646.25
    assert events[1]["data"]["task_id"] == "BM-013"
    assert events[1]["data"]["episode_deadline_monotonic"] == 866946.25

    planner = events[12]
    assert planner["_line"] == 13
    assert planner["type"] == "llm_planner_call"
    assert planner["data"]["call_id"] == "llm-c951c521a8c04078"
    assert planner["data"]["real_llm_call"] is True
    assert planner["data"]["schema_valid"] is True
    assert planner["data"]["provider_metadata"]["total_tokens"] == 4471
    assert planner["data"]["provider_metadata"]["duration_ms"] == 13125

    policy = report["repair_policy_live_evidence"]
    repaired_verification = events[215]
    assert repaired_verification["_line"] == policy["verification_line"] == 216
    assert repaired_verification["type"] == "goal_verification"
    assert repaired_verification["data"]["goal"] == policy[
        "probe47_regression_goal"
    ]
    assert repaired_verification["data"]["achieved"] is True
    assert repaired_verification["data"]["target_inventory"] == {
        "wooden_pickaxe": 1
    }
    assert repaired_verification["data"]["missing"] == []
    assert repaired_verification["data"]["matched_rules"] == policy[
        "matched_rules"
    ]
    assert "cobblestone" not in repaired_verification["data"]["target_inventory"]

    completion = events[216]
    assert completion["_line"] == policy["completion_line"] == 217
    assert completion["type"] == "auto_goal_complete"
    assert completion["data"]["goal"] == policy["probe47_regression_goal"]
    assert completion["data"]["success"] is True

    next_goal = events[219]
    assert next_goal["_line"] == policy["next_cobblestone_goal_selected_line"] == 220
    assert next_goal["data"]["goal"] == (
        "Gather 11 cobblestone for stone pickaxe and furnace"
    )
    cobblestone_verification = events[381]
    assert cobblestone_verification["_line"] == (
        policy["next_cobblestone_goal_verified_line"]
    )
    assert cobblestone_verification["data"]["achieved"] is True
    assert cobblestone_verification["data"]["target_inventory"] == {
        "cobblestone": 11
    }

    live_policy_lines = [
        event["_line"]
        for event in events
        if event["type"] == "goal_verification"
        and (
            "policy:m4-inventory-purpose-clause-grounding-v1"
            in event["data"].get("matched_rules", [])
        )
    ]
    assert live_policy_lines == policy["live_goal_verification_lines"]
    assert policy["probe47_false_verification_recurred"] is False
    assert policy["yield_result"] == "repair_live_exercised_success"

    goal_completions = [
        event for event in events if event["type"] == "auto_goal_complete"
    ]
    assert len(goal_completions) == 9
    assert all(event["data"]["success"] is True for event in goal_completions)
    goal_verifications = [
        event for event in events if event["type"] == "goal_verification"
    ]
    assert len(goal_verifications) == 9
    assert all(event["data"]["achieved"] is True for event in goal_verifications)


def test_probe48_jsonl_and_eligibility_prove_smelt_output_provenance():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    events = _events(report)
    provenance = report["smelting_provenance"]

    furnace_position = {"x": 117, "y": 123, "z": -49}
    for line in report["recovered_noise"]["furnace_visible_in_observation_lines"]:
        observed_furnace = _nearby_block(events[line - 1], "furnace")
        assert observed_furnace is not None
        assert observed_furnace["position"] == furnace_position

    machine_step = events[provenance["machine_step_line"] - 1]
    assert machine_step["type"] == (
        "m4_bm013_bm014_toolchain_machine_step_plan"
    )
    assert machine_step["data"]["policy_id"] == provenance[
        "machine_step_policy_id"
    ]
    assert machine_step["data"]["llm_gate_policy_id"] == provenance[
        "llm_gate_policy_id"
    ]
    assert machine_step["data"]["qualifying_llm_call_id"] == provenance[
        "qualifying_llm_call_id"
    ]
    assert machine_step["data"]["reason"] == provenance["machine_step_reason"]
    assert machine_step["data"]["action"]["type"] == "smelt"
    assert machine_step["data"]["target"]["position"] == furnace_position

    action_verification = events[provenance["action_verification_line"] - 1]
    assert action_verification["type"] == "action_verification"
    assert action_verification["data"]["action"]["type"] == "smelt"
    assert action_verification["data"]["verification"]["status"] == "accept"
    assert action_verification["data"]["verification"]["required"] == {
        "raw_iron": 1,
        "coal": 1,
    }

    smelt = events[provenance["action_line"] - 1]
    assert smelt["_line"] == provenance["jsonl_line"] == 1041
    assert smelt["type"] == "action"
    assert smelt["data"]["action"]["type"] == provenance["action_type"]
    assert smelt["data"]["result"]["success"] is True
    assert smelt["data"]["result"]["policy_id"] == provenance["policy_id"]
    assert smelt["data"]["result"]["smelt_attempts"] == 1
    assert smelt["data"]["result"]["smelt_retry_count"] == 0
    assert smelt["data"]["result"]["automatic_retry"] is False
    assert smelt["data"]["result"]["furnace_position"] == furnace_position
    assert smelt["data"]["result"]["inventory_signed_delta"] == {
        "raw_iron": -1,
        "coal": -1,
        "iron_ingot": 1,
    }
    assert smelt["data"]["result"]["inventory_before"]["raw_iron"] == 1
    assert smelt["data"]["result"]["inventory_before"]["coal"] == 1
    assert smelt["data"]["result"]["inventory_after"]["iron_ingot"] == 1
    assert smelt["data"]["result"]["output_settled"] is True
    assert smelt["data"]["result"]["furnace_slots_empty"] is True
    assert smelt["data"]["result"]["accepted_within_episode_deadline"] is True

    terminal = events[provenance["terminal_task_verification_line"] - 1]
    assert terminal["type"] == "terminal_task_verification"
    assert terminal["data"]["passed"] is True
    assert terminal["data"]["task_id"] == "BM-013"
    assert terminal["data"]["verifier_id"] == provenance["terminal_verifier_id"]
    assert terminal["data"]["required_action_type"] == "smelt"
    assert terminal["data"]["observed_count"] == 1
    assert terminal["data"]["inventory"]["iron_ingot"] == 1
    assert terminal["data"]["health"] == 20
    assert terminal["data"]["food"] == 20
    assert terminal["data"]["uninterrupted_survival"] is True

    autonomous_end = events[provenance["autonomous_end_line"] - 1]
    assert autonomous_end["type"] == "autonomous_end"
    assert autonomous_end["data"]["termination_reason"] == (
        "terminal_task_verified"
    )
    assert autonomous_end["data"]["elapsed_s"] == 257.031
    assert autonomous_end["data"]["deadline_eligible"] is True

    eligibility = json.loads(
        (ROOT / report["evidence_paths"]["eligibility"]).read_text(
            encoding="utf-8"
        )
    )
    output_provenance = eligibility["evidence"]["output_provenance"]
    assert output_provenance["initial_inventory"] == {"iron_ingot": 0}
    assert output_provenance["terminal_inventory"] == {"iron_ingot": 1}
    assert output_provenance["positive_inventory_delta"] == {"iron_ingot": 1}
    assert output_provenance["successful_source_action_count"] == 1
    source_action = output_provenance["successful_source_actions"][0]
    assert source_action["event_index"] == provenance[
        "eligibility_event_index"
    ]
    assert source_action["action_type"] == "smelt"
    assert source_action["output_delta"] == 1
    assert source_action["inventory_delta"] == provenance[
        "inventory_signed_delta"
    ]
    assert len(eligibility["checks"]) == 74
    assert all(check["passed"] is True for check in eligibility["checks"])


def test_probe48_records_recovered_noise_without_overstating_capability():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    events = _events(report)

    failed_actions = [
        event
        for event in events
        if event["type"] == "action" and event["data"]["result"]["success"] is False
    ]
    assert len(failed_actions) == report["recovered_noise"][
        "failed_action_count"
    ]
    assert {event["data"]["action"]["type"] for event in failed_actions} == {
        "place"
    }
    occupied_failures = [
        event
        for event in failed_actions
        if event["data"]["result"]["error"]
        == "placement target is occupied by stone"
    ]
    assert len(occupied_failures) == report["recovered_noise"][
        "occupied_stone_place_failure_count"
    ] == 30
    final_failed_place = events[
        report["recovered_noise"]["failed_furnace_place_result_line"] - 1
    ]
    assert final_failed_place["data"]["result"]["success"] is False
    assert final_failed_place["data"]["result"]["error"] == report[
        "recovered_noise"
    ]["failed_furnace_place_error"]
    assert report["recovered_noise"][
        "block_update_timeout_place_failure_count"
    ] == 1
    assert final_failed_place["data"]["pre_observation"]["inventory"][
        "furnace"
    ] == report["recovered_noise"]["timed_out_place_pre_inventory_furnace"]
    assert final_failed_place["data"]["post_observation"]["inventory"].get(
        "furnace",
        0,
    ) == report["recovered_noise"]["timed_out_place_post_inventory_furnace"]
    assert _nearby_block(final_failed_place["data"]["post_observation"], "furnace")[
        "position"
    ] == {"x": 117, "y": 123, "z": -49}
    assert report["recovered_noise"][
        "timed_out_place_physical_effect_observed"
    ] is True
    next_cycle_observation = events[
        report["recovered_noise"]["next_cycle_furnace_observation_line"] - 1
    ]
    assert _nearby_block(next_cycle_observation, "furnace")["position"] == {
        "x": 117,
        "y": 123,
        "z": -49,
    }
    assert report["recovered_noise"][
        "terminal_success_despite_failed_place_results"
    ] is True
    assert report["recovered_noise"]["eligibility_defect"] is False

    decision = report["decision"]
    assert decision["counts_toward_bm013_success"] is True
    assert decision["counts_toward_capability"] is False
    assert decision["bm013_success_count_after"] == 1
    assert decision["required_success_count"] == 3
    assert decision["remaining_success_count"] == 2
    assert decision["bm013_repeat_verified_after_probe"] is False
    assert decision["next_task_id"] == "BM-013"
    assert decision["probe_49_authorized"] is False
    assert decision["bm014_locked"] is True
    assert "iron_pickaxe" not in report["episode_result"]["terminal_inventory"]


def test_probe48_lifecycle_cycles_and_monotonic_bounds_are_independent():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    events = _events(report)

    observations = [event for event in events if event["type"] == "observation"]
    assert len(observations) == report["survival_evidence"][
        "observation_count"
    ] == 144
    assert min(event["data"]["health"] for event in observations) == 20
    assert min(event["data"]["hunger"] for event in observations) == 20
    for event in observations:
        lifecycle = event["data"]["player_lifecycle"]
        assert lifecycle["death_count"] == 0
        assert lifecycle["respawn_count"] == 0
        assert lifecycle["uninterrupted"] is True

    lifecycle_events = [
        event for event in events if event["type"] == "m4_player_lifecycle"
    ]
    assert len(lifecycle_events) == report["survival_evidence"][
        "lifecycle_event_count"
    ] == 1

    completions = [
        event for event in events if event["type"] == "auto_goal_complete"
    ]
    cycles = [event["data"]["cycles"] for event in completions]
    result = report["episode_result"]
    assert cycles == result["per_goal_cycles"]
    assert sum(cycles) == result["total_cycles"] == 71
    assert max(cycles) == result["maximum_goal_cycles"] == 17
    assert max(cycles) < report["frozen_controls"]["max_cycles_per_goal"]
    assert sum(cycles) < report["frozen_controls"]["max_total_cycles"]

    episode_start = events[1]["data"]["episode_started_monotonic"]
    deadline = events[1]["data"]["episode_deadline_monotonic"]
    assert episode_start == 866646.25
    assert deadline == 866946.25
    assert max(event["monotonic_s"] for event in events) == 866903.343
    assert max(event["monotonic_s"] for event in events) < deadline
