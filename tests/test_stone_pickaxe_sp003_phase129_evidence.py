import hashlib
import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
RUN_ID = "sp003_baseline_20260720_081826_aeafcafc"
RUN_DIR = REPO / "workspace/evals/sp003_runs" / RUN_ID


def _load(name: str):
    return json.loads((RUN_DIR / name).read_text(encoding="utf-8"))


def _events(event_type: str):
    return [
        event["data"]
        for event in _load("session.json")
        if event.get("type") == event_type
    ]


def test_phase129_authorization_and_all_retained_payload_hashes_are_bound():
    manifest = _load("manifest.json")
    authorization = _load("authorization.json")
    consumption = _load("authorization_consumption.json")

    assert hashlib.sha256((RUN_DIR / "manifest.json").read_bytes()).hexdigest() == (
        "32e7c5c67088f2c03d66c8603ab0cc6cf7386d35e0abf637ab99d24bdfbe9fc2"
    )
    assert manifest["episode_id"] == RUN_ID
    assert manifest["session_id"] == "91c09358-782"
    assert manifest["authorization_id"] == (
        "200122ac63022a2e161c986bc251810cf8b07db667d41043172e1e2d302b0d4c"
    )
    assert manifest["passed"] is False
    assert manifest["evidence_eligible"] is False
    assert manifest["single_episode"] is True
    assert manifest["automatic_retry_allowed"] is False
    assert manifest["bm012_terminal_started"] is False
    assert authorization["authorization_predecessor"] == (
        "599fc76e2210cbe2ef925be715d83c225ffade33"
    )
    assert authorization["harness_policy_sha256"] == (
        "bd665e6a566c7808bbfb566148ee6471786cfa3c101f3619c6a622a0a8c32e07"
    )
    assert authorization["single_episode"] is True
    assert authorization["automatic_retry_allowed"] is False
    assert consumption["authorization_commit"] == (
        "1c70c093d855b234b7c19b89ea1dc07f8deba391"
    )
    assert consumption["consumed_by"] == "fresh_sp003_process_start"
    assert consumption["single_episode"] is True
    assert consumption["automatic_retry_allowed"] is False

    assert len(manifest["files"]) == 12
    for record in manifest["files"]:
        path = REPO / record["path"]
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]


def test_phase129_retains_effective_guard_replan_disconnect_and_terminal_empty_action():
    episode = _load("episode.json")
    verification = _load("verification.json")
    planner_calls = _events("llm_planner_call")
    plans = _events("plan")
    actions = _events("action")
    pre_dispatch = _events("stone_pickaxe_sp003_pre_dispatch_replan")
    effective_guards = _events("stone_pickaxe_sp003_action_guard")
    observations = _events("observation")

    goal = episode["goal_result"]
    assert goal["completed"] is False
    assert goal["termination_reason"] == "empty_plan"
    assert goal["cycles"] == 13
    assert goal["action_count"] == 10
    assert goal["elapsed_s"] == 77.297
    assert goal["deadline_eligible"] is True
    assert episode["raw_action_failures"] == []
    assert episode["unreconciled_action_failures"] == []
    assert episode["post_deadline_action_indexes"] == []

    assert [call["call_index"] for call in planner_calls] == list(range(13))
    assert all(call["real_llm_call"] is True for call in planner_calls)
    assert all(call["schema_valid"] is True for call in planner_calls[:12])
    terminal = planner_calls[12]
    assert terminal["schema_valid"] is False
    assert terminal["schema_validation"]["status"] == "planning"
    assert terminal["schema_validation"]["action_count"] == 0
    assert terminal["schema_validation"]["issues"] == [
        "planning_action_count_must_equal_one"
    ]
    normalization = terminal["schema_validation"]["reasoning_normalization"]
    assert normalization["applied"] is False
    assert normalization["original_char_count"] == 280
    assert normalization["provider_response_preserved"] is True
    assert normalization["action_rewrite"] is False
    assert terminal["response_sha256"] == (
        "0b5dda8221260d77e3cfef5b203cd89271fa8605468ef36e3a433cc67da82d32"
    )
    assert terminal["response_byte_count"] == 596
    assert all(
        call["transport_evidence"]["attempt_count"] == 1
        and call["transport_evidence"]["retry_count"] == 0
        and call["transport_evidence"]["attempts"][0]["success"] is True
        for call in planner_calls
    )
    assert plans[12]["status"] == "error"
    assert plans[12]["actions"] == []
    assert plans[12]["reasoning"] == (
        "Planner output rejected before execution: "
        "planning_action_count_must_equal_one"
    )

    assert [action["action"]["type"] for action in actions] == [
        "move_to",
        "dig",
        "dig",
        "dig",
        "craft",
        "craft",
        "craft",
        "move_to",
        "dig",
        "dig",
    ]
    assert all(action["result"].get("success") is True for action in actions)
    assert [
        action["action"]["parameters"].get("source_id")
        for action in actions[-2:]
    ] == ["grass_block:121:141:-37", "dirt:121:140:-37"]
    assert all(
        action["action"]["parameters"].get("stone_surface_clearance") is True
        for action in actions[-2:]
    )

    assert len(pre_dispatch) == 4
    assert [item["granted"] for item in pre_dispatch] == [
        True,
        False,
        True,
        False,
    ]
    assert [item["limit_reason"] for item in pre_dispatch] == [
        "",
        "fingerprint_limit_exhausted",
        "",
        "fingerprint_limit_exhausted",
    ]
    assert pre_dispatch[0]["fingerprint"] == pre_dispatch[1]["fingerprint"]
    assert pre_dispatch[2]["fingerprint"] == pre_dispatch[3]["fingerprint"]
    assert all(
        item["guard"]["issues"]
        == ["sp003_action_forbidden_for_stage:prepare_wooden_pickaxe:dig"]
        for item in pre_dispatch
    )
    assert all(
        item["backend_invoked"] is False
        and item["world_mutation"] is False
        and item["action_budget_consumed"] is False
        for item in (pre_dispatch[0], pre_dispatch[2])
    )

    assert len(effective_guards) == 10
    assert all(item["allowed"] is True for item in effective_guards)
    assert all(
        item["policy_id"] == "sp003-partial-clearance-shaft-step-up-egress-v1"
        for item in effective_guards
    )
    assert [item["action"]["type"] for item in effective_guards[-2:]] == [
        "dig",
        "dig",
    ]
    assert effective_guards[-1]["action_repair"]["target_mode"] == (
        "locked_surface_clearance"
    )

    terminal_observation = observations[-1]
    assert terminal_observation["inventory"] == {
        "oak_planks": 6,
        "stick": 4,
        "crafting_table": 1,
        "dirt": 2,
    }
    staging = terminal_observation["sp003_table_staging"]
    assert staging["target_mode"] == "locked_shaft_step_up_egress"
    assert staging["blocked"] is False
    assert staging["target"]["source_id"] == (
        "sp003_clearance_shaft_step_up_egress:120:141:-37"
    )
    assert staging["target"]["shaft_step_up_egress_proof_fingerprint"] == (
        "9282c900fcc3eba4b0800faad6dae4e0bf3a242f372ff02e30f574ad5547d38f"
    )
    assert verification["metrics"]["log_source_removal_count"] == 3
    assert verification["metrics"]["surface_clearance_removal_count"] == 2
    assert verification["metrics"]["stone_source_removal_count"] == 0
    assert verification["criteria"]["one_plank_craft"] is True
    assert verification["criteria"]["one_stick_craft"] is True
    assert verification["criteria"]["one_table_craft"] is True
    assert verification["criteria"]["one_table_place"] is False
    assert verification["criteria"]["terminal_stone_pickaxe"] is False


def test_phase129_failure_ledger_binds_the_episode_without_granting_credit():
    ledger = json.loads(
        (REPO / "workspace/evals/stone_pickaxe_failure_ledger.json").read_text(
            encoding="utf-8"
        )
    )
    failure = next(
        item
        for item in ledger["failures"]
        if item["id"] == "sp003-baseline-027-effective-guard-empty-action"
    )

    assert failure["episode_id"] == RUN_ID
    assert failure["phase_128_pre_dispatch_replan_live_exercised"] is True
    assert failure["behavioral_empty_hand_to_stone_pickaxe_loop_completed"] is False
    assert failure["strict_sp003_baseline_passed"] is False
    assert failure["automatic_retry_attempted"] is False
    assert failure["counts_toward_baseline_success"] is False
    assert failure["counts_toward_skill_gate"] is False
    assert failure["counts_toward_capability"] is False
    assert failure["counts_toward_m4"] is False
    assert len(failure["evidence"]) == 13
    for record in failure["evidence"]:
        path = REPO / record["path"]
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]

    assert ledger["live_authorization"] is False
    assert ledger["next_required_gate"]["authorization"] is False
    assert ledger["next_required_gate"]["live_episode_limit"] == 0
