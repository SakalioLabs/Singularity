import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "workspace" / "evals" / "m4_probe49_report.json"


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


def _git_blob(commit: str, path: str) -> bytes:
    return subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout


def _git_tree(commit: str) -> str:
    return subprocess.run(
        ["git", "show", "-s", "--format=%T", commit],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


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


def test_m4_probe49_report_binds_second_eligible_bm013_success():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    authorization = report["authorization"]

    assert report["probe_number"] == 49
    assert report["task_id"] == "BM-013"
    assert report["episode_id"] == "m4_episode_20260727_102938_d9c5ed94"
    assert report["session_id"] == "e1136bdf-2d5"
    assert report["level_name"] == (
        "m4_episode_20260727_102938_d9c5ed94_bm013"
    )

    assert authorization["commit"] == (
        "bf4f93dff621d02b7b3f028ba7f1b12b656432b6"
    )
    assert _git_tree(authorization["commit"]) == authorization["tree"]
    issued_blob = _git_blob(authorization["commit"], authorization["path"])
    issued = json.loads(issued_blob)
    assert hashlib.sha256(issued_blob).hexdigest() == authorization[
        "issued_sha256"
    ] == "060b4caca62d7c4803511ae5ea9f029c016634a20d014bbbc6b5c9241c63b53d"
    assert issued["probe_number"] == 49
    assert issued["authorized"] is True
    assert issued["one_use"] is True
    assert issued["maximum_episode_count"] == 1
    assert issued["maximum_retry_count"] == 0
    assert issued["consumed"] is False
    assert issued["next_authorization"] is False
    assert authorization["issued_artifact_consumed_field"] is False
    consumed_path = ROOT / authorization["consumed_artifact_path"]
    assert _sha256(consumed_path) == authorization[
        "consumed_sha256"
    ] == "27a621dfee5d424c2552ee1230fc009670332ec4d8729ecd91f11eecf1acb510"
    consumed = json.loads(consumed_path.read_text(encoding="utf-8"))
    assert consumed["consumed"] is True
    assert authorization["consumed_artifact_consumed_field"] is True
    assert consumed["consumed_by_episode"] == report["episode_id"]
    assert consumed["consumed_session_id"] == report["session_id"]
    assert consumed["consumed_level_name"] == report["level_name"]
    assert consumed["consumed_at"] == "autonomous_start"
    assert consumed["consumed_at_utc"] == (
        authorization["runtime_consumption"]["consumed_at_utc"]
    )
    assert consumed["consumed_monotonic_s"] == (
        authorization["runtime_consumption"]["consumed_monotonic_s"]
    )
    assert consumed["consumed_event_line"] == (
        authorization["runtime_consumption"]["consumed_event_line"]
    )
    assert authorization["gate_parent_commit"] == issued["gate_parent_commit"]
    assert authorization["gate_tree"] == issued["gate_tree"]
    assert authorization["policy_id"] == issued["policy_id"]
    assert authorization["prior_probe_report_sha256"] == issued[
        "prior_probe_report_sha256"
    ]
    assert _sha256(
        ROOT / authorization["prior_probe_report_path"]
    ) == authorization["prior_probe_report_sha256"]
    assert authorization["repair_source_sha256"] == _sha256(
        ROOT / "src" / "singularity" / "core" / "goal_verifier.py"
    )

    for name, path in report["evidence_paths"].items():
        assert _sha256(ROOT / path) == report["evidence_sha256"][name]

    controls = report["frozen_controls"]
    assert _sha256(
        ROOT / "src" / "singularity" / "data" / "m4_protocol.json"
    ) == controls["protocol_sha256"] == issued["protocol_sha256"]
    assert _sha256(
        ROOT / "src" / "singularity" / "data" / "m4_bm013_protocol.json"
    ) == controls["task_contract_sha256"] == issued["task_contract_sha256"]
    assert controls["task_contract_id"] == "m4-bm013-smelting-contract-v1"
    assert controls["max_duration_s"] == 300
    assert controls["max_total_cycles"] == 320
    assert controls["python"] == "3.12.8"
    assert controls["node"] == "22.16.0"
    assert controls["planner_retry_count"] == 0
    assert controls["proxy_retry_count"] == 0
    assert controls["skill_execution_mode"] == "off"

    result = report["episode_result"]
    assert result["completed"] is True
    assert result["termination_reason"] == "terminal_task_verified"
    assert result["elapsed_s"] == 238.14
    assert result["deadline_margin_s"] == 61.86
    assert result["evidence_seal_duration_s"] == 238.218
    assert result["evidence_seal_deadline_margin_s"] == 61.782
    assert result["deadline_eligible"] is True
    assert result["goals_completed"] == 9
    assert result["goals_failed"] == 0
    assert result["total_cycles"] == 50
    assert result["per_goal_cycles"] == [6, 2, 5, 13, 9, 3, 2, 6, 4]
    assert result["maximum_goal_cycles"] == 13
    assert result["planner_call_count"] == 1
    assert result["schema_valid_real_planner_call_count"] == 1
    assert result["machine_step_plan_count"] == 49
    assert result["action_count"] == 51
    assert result["successful_action_count"] == 42
    assert result["failed_action_count"] == 9
    assert result["action_verifier_accept_count"] == 51
    assert result["goal_verification_accepted_count"] == 9
    assert result["terminal_inventory"]["iron_ingot"] == 1
    assert result["terminal_health"] == 20
    assert result["terminal_food"] == 20
    assert result["terminal_bot_connected"] is True
    assert result["active_episode_death_count"] == 0
    assert result["active_episode_respawn_count"] == 0

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


def test_probe49_jsonl_proves_authorization_consumption_and_goal_chain():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    events = _events(report)
    consumption = report["authorization"]["runtime_consumption"]

    assert len(events) == report["episode_result"]["session_event_count"] == 750
    start = events[consumption["consumed_event_line"] - 1]
    assert start["_line"] == 2
    assert start["type"] == consumption["consumed_at"] == "autonomous_start"
    assert start["monotonic_s"] == consumption["consumed_monotonic_s"] == 869602.5
    start_utc = datetime.fromtimestamp(start["ts"], timezone.utc).isoformat(
        timespec="microseconds"
    ).replace("+00:00", "Z")
    assert start_utc == consumption["consumed_at_utc"]
    assert start["session"] == consumption["consumed_session_id"]
    assert start["data"]["task_id"] == "BM-013"
    assert start["data"]["episode_deadline_monotonic"] == 869902.5
    assert consumption["consumed"] is True
    assert consumption["consumed_episode_id"] == report["episode_id"]
    assert consumption["consumed_session_id"] == report["session_id"]
    assert consumption["consumed_level_name"] == report["level_name"]

    planner = events[12]
    assert planner["_line"] == 13
    assert planner["type"] == "llm_planner_call"
    assert planner["data"]["call_id"] == "llm-d279fab90c554398"
    assert planner["data"]["real_llm_call"] is True
    assert planner["data"]["schema_valid"] is True
    assert planner["data"]["provider_metadata"]["total_tokens"] == 4551
    assert planner["data"]["provider_metadata"]["duration_ms"] == 14609

    policy = report["repair_policy_live_evidence"]
    repaired_verification = events[policy["verification_line"] - 1]
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

    completion = events[policy["completion_line"] - 1]
    assert completion["type"] == "auto_goal_complete"
    assert completion["data"]["goal"] == policy["probe47_regression_goal"]
    assert completion["data"]["success"] is True

    next_goal = events[policy["next_cobblestone_goal_selected_line"] - 1]
    assert next_goal["type"] == "auto_goal"
    assert next_goal["data"]["goal"] == (
        "Gather 11 cobblestone for stone pickaxe and furnace"
    )
    cobblestone_verification = events[
        policy["next_cobblestone_goal_verified_line"] - 1
    ]
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

    completions = [
        event for event in events if event["type"] == "auto_goal_complete"
    ]
    verifications = [
        event for event in events if event["type"] == "goal_verification"
    ]
    assert len(completions) == len(verifications) == 9
    assert all(event["data"]["success"] is True for event in completions)
    assert all(event["data"]["achieved"] is True for event in verifications)


def test_probe49_jsonl_and_eligibility_prove_smelt_output_provenance():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    events = _events(report)
    provenance = report["smelting_provenance"]
    furnace_position = {"x": 116, "y": 123, "z": -50}

    for line in (
        provenance["furnace_first_observed_line"],
        provenance["furnace_reobserved_line"],
    ):
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
    assert smelt["_line"] == provenance["jsonl_line"] == 740
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
    assert autonomous_end["data"]["elapsed_s"] == 238.14
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


def test_probe49_records_recovered_noise_and_conservative_gate_state():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    events = _events(report)
    noise = report["recovered_noise"]

    failed_actions = [
        event
        for event in events
        if event["type"] == "action" and event["data"]["result"]["success"] is False
    ]
    assert len(failed_actions) == noise["failed_action_count"] == 9
    assert [event["_line"] for event in failed_actions] == noise[
        "failed_place_lines"
    ]
    assert {event["data"]["action"]["type"] for event in failed_actions} == {
        "place"
    }
    assert all(
        event["data"]["result"]["error"]
        == "placement target is occupied by stone"
        for event in failed_actions
    )
    assert noise["occupied_stone_place_failure_count"] == 9
    assert noise["successful_place_count"] == 4
    assert noise["terminal_success_despite_failed_place_results"] is True
    assert noise["eligibility_defect"] is False
    assert noise["session_error_count"] == 0

    residual = report["residual_nonblocking_verifier_observation"]
    verification = events[residual["verification_line"] - 1]
    assert verification["type"] == "goal_verification"
    assert verification["data"]["goal"] == residual["goal"]
    assert verification["data"]["achieved"] is True
    assert verification["data"]["target_inventory"] == residual[
        "target_inventory"
    ]
    assert residual["unexpected_extra_binding"] == {"cobblestone": 1}
    assert residual["blocked_progress"] is False
    assert residual["eligibility_defect"] is False
    assert residual["repair_required_before_next_repeat"] is False

    decision = report["decision"]
    assert decision["counts_toward_bm013_success"] is True
    assert decision["counts_toward_capability"] is False
    assert decision["bm013_success_count_before"] == 1
    assert decision["bm013_success_count_after"] == 2
    assert decision["required_success_count"] == 3
    assert decision["remaining_success_count"] == 1
    assert decision["bm013_repeat_verified_after_probe"] is False
    assert decision["bm013_status_after"] == (
        "repeat_verification_in_progress_2_of_3"
    )
    assert decision["m4_status_after"] == "partial"
    assert decision["next_task_id"] == "BM-013"
    assert decision["next_live_probe_locked_until_evidence_commit"] is True
    assert decision["probe_50_authorized"] is False
    assert decision["bm014_locked"] is True
    assert report["authorization"]["probe_50_authorized"] is False
    assert "iron_pickaxe" not in report["episode_result"]["terminal_inventory"]


def test_probe49_lifecycle_cycles_and_monotonic_bounds_are_independent():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    events = _events(report)

    observations = [event for event in events if event["type"] == "observation"]
    survival = report["survival_evidence"]
    assert len(observations) == survival["observation_count"] == 102
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
    assert len(lifecycle_events) == survival["lifecycle_event_count"] == 1
    assert survival["maximum_death_count"] == 0
    assert survival["maximum_respawn_count"] == 0
    assert survival["uninterrupted_survival"] is True
    assert survival["terminal_bot_connected"] is True

    completions = [
        event for event in events if event["type"] == "auto_goal_complete"
    ]
    cycles = [event["data"]["cycles"] for event in completions]
    result = report["episode_result"]
    controls = report["frozen_controls"]
    assert cycles == result["per_goal_cycles"]
    assert sum(cycles) == result["total_cycles"] == 50
    assert max(cycles) == result["maximum_goal_cycles"] == 13
    assert max(cycles) < controls["max_cycles_per_goal"]
    assert sum(cycles) < controls["max_total_cycles"]

    start = events[1]["data"]["episode_started_monotonic"]
    deadline = events[1]["data"]["episode_deadline_monotonic"]
    maximum_event_monotonic = max(event["monotonic_s"] for event in events)
    assert start == 869602.5
    assert deadline == 869902.5
    assert maximum_event_monotonic == 869840.718
    assert maximum_event_monotonic < deadline
    assert round(maximum_event_monotonic - start, 3) == result[
        "evidence_seal_duration_s"
    ]
    assert round(deadline - maximum_event_monotonic, 3) == result[
        "evidence_seal_deadline_margin_s"
    ]

    eligibility = json.loads(
        (ROOT / report["evidence_paths"]["eligibility"]).read_text(
            encoding="utf-8"
        )
    )
    preparation = json.loads(
        (ROOT / report["evidence_paths"]["preparation"]).read_text(
            encoding="utf-8"
        )
    )
    assert eligibility["evidence"]["event_count"] == result[
        "eligibility_event_count"
    ] == 749
    assert preparation["time_remaining_s"] == result[
        "evidence_seal_deadline_margin_s"
    ]
    assert preparation["progress_gate_passed"] is True
    assert preparation["counts_toward_task_success"] is True
    assert preparation["decision"] == "count_bm013_success"
