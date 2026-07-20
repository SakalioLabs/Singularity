from __future__ import annotations

import hashlib
import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
RUN_ID = "sp003_baseline_20260720_121934_e86b807f"
RUN_DIR = REPO / "workspace/evals/sp003_runs" / RUN_ID
MANIFEST_SHA256 = "9ed16b45f2ca9bbb6ef9e38b5d0ae9d9cbf072dd056108027f27405bb5c5cf48"
FILE_HASHES = {
    "audit.json": "38350a64e19a30451a912c0eb17a65bfcfa2092de8c88db64e9499099ceefb2a",
    "authorization.json": "fd3d0cc7f99fa3cd2c9cd6bd7ef158ff65d044ad2ca2d170145a20431df6917a",
    "authorization_consumption.json": "60703329a2405bd4eff3947bba1e06ec382d4fb01240f4f267cbe7f9b9c1a283",
    "episode.json": "a8b2b94316811a6fdb43dd58644ca368731be00b274c5b76373c97bbfd69f892",
    "manifest.json": MANIFEST_SHA256,
    "preflight.json": "3b39cf5efdd678b9286f3ba152c98f04c57ce005abc822a6b2d1a6f9f4d00977",
    "protocol_status.json": "889dad9b9f939fff9aeda6743b55d5c873c7507c6e7a798e0e6a15e934b65952",
    "reset.json": "c3a267e108dcce49fe6b8018cf990bb9833ee32881efb879aeb986dbe00ba9a8",
    "reset_audit.json": "a8c8be85aee67d4e2231146b3de369e7e892637307cbe12d4bf4d28e29e3aade",
    "session.json": "e3f5239fe74fb8c312425401e5e6f44c5e88c9e2cdb6d3d1d6cfd847262e8522",
    "session_5bfd9200-c73.jsonl": "ce6e2e5c2004fb64c92f38c795e10bf78c88cd5b58018f9c5376e1797ec3098e",
    "session_5bfd9200-c73_summary.json": "4bad3605a38dcfb291f26cc5645825cb5a1fbb63dfe89e803a4424f9b0513511",
    "verification.json": "eba1eacb97327ddd3d551b322e30918b031e301834a76e8168e2ac71756255be",
}


def _load(name: str):
    return json.loads((RUN_DIR / name).read_text(encoding="utf-8"))


def _event_data(event_type: str):
    return [
        event["data"]
        for event in _load("session.json")
        if event.get("type") == event_type
    ]


def test_phase135_authorization_and_all_retained_payload_hashes_are_bound():
    manifest = _load("manifest.json")
    authorization = _load("authorization.json")
    consumption = _load("authorization_consumption.json")

    assert manifest["episode_id"] == RUN_ID
    assert manifest["session_id"] == "5bfd9200-c73"
    assert manifest["authorization_id"] == (
        "6fb6ca57d2d555c944995ef88f07b430ddbc2690ad3de2323ee47c3726680989"
    )
    assert manifest["passed"] is False
    assert manifest["evidence_eligible"] is False
    assert manifest["single_episode"] is True
    assert manifest["automatic_retry_allowed"] is False
    assert manifest["bm012_terminal_started"] is False
    assert authorization["authorization_predecessor"] == (
        "d21ca537171c0c0085758ed17a927068c18ab6b2"
    )
    assert consumption["authorization_commit"] == (
        "cf32589df5d02e1ac4643d90463e0cb99300b35a"
    )
    assert consumption["consumed_by"] == "fresh_sp003_process_start"
    assert consumption["single_episode"] is True
    assert consumption["automatic_retry_allowed"] is False

    assert set(FILE_HASHES) == {path.name for path in RUN_DIR.iterdir()}
    for name, expected in FILE_HASHES.items():
        assert hashlib.sha256((RUN_DIR / name).read_bytes()).hexdigest() == expected
    assert len(manifest["files"]) == 12
    for record in manifest["files"]:
        assert FILE_HASHES[Path(record["path"]).name] == record["sha256"]


def test_phase135_retains_observation_delayed_log_pickup_overshoot():
    events = _load("session.json")
    episode = _load("episode.json")
    planner_calls = _event_data("llm_planner_call")
    plans = _event_data("plan")
    actions = _event_data("action")

    assert len(planner_calls) == 15
    assert [
        call["provider_metadata"]["duration_ms"] for call in planner_calls
    ] == [
        6061,
        3282,
        2750,
        2125,
        2438,
        2063,
        2030,
        2296,
        2390,
        2406,
        2218,
        2000,
        2342,
        2297,
        2312,
    ]
    assert sum(
        call["provider_metadata"]["duration_ms"] for call in planner_calls
    ) == 39010
    assert all(call["real_llm_call"] is True for call in planner_calls)
    assert all(call["schema_valid"] is True for call in planner_calls)
    assert all(
        call["transport_evidence"]["attempt_count"] == 1
        and call["transport_evidence"]["retry_count"] == 0
        for call in planner_calls
    )

    assert [action["action"]["type"] for action in actions] == [
        "move_to",
        "dig",
        "dig",
        "dig",
        "dig",
        *(["craft"] * 10),
    ]
    failed_log = actions[2]
    assert failed_log["action"]["parameters"]["source_id"] == (
        "oak_log:119:141:-33"
    )
    assert failed_log["result"]["success"] is False
    assert failed_log["result"]["block_removed"] is True
    assert failed_log["result"]["error"] == "expected block drop was not acquired"
    pending = failed_log["result"]["sp003_pending_log_pickup"]
    assert pending["proof_fingerprint"] == (
        "a0b4b268467be0b8959a21e997b542eef2f9fb957cfab2d7bb7d02ff21db5f23"
    )

    pre_overshoot = events[96]
    assert pre_overshoot["type"] == "observation"
    assert pre_overshoot["data"]["inventory"] == {"oak_log": 3}
    assert pre_overshoot["data"]["sp003_progress"][
        "log_source_removal_count"
    ] == 2
    assert pre_overshoot["data"]["sp003_progress"][
        "pending_log_pickup_count"
    ] == 1
    assert plans[4]["actions"] == [
        {
            "type": "dig",
            "parameters": {
                "block": "oak_log",
                "x": 119,
                "y": 143,
                "z": -33,
                "source_id": "oak_log:119:143:-33",
            },
        }
    ]

    overshoot = events[109]
    assert overshoot["type"] == "observation"
    assert overshoot["data"]["inventory"] == {"oak_log": 4}
    assert overshoot["data"]["sp003_progress"][
        "log_source_removal_count"
    ] == 3
    assert overshoot["data"]["sp003_progress"]["pending_log_pickup_count"] == 1
    craft_failures = actions[5:]
    assert len(craft_failures) == 10
    assert all(
        action["result"]["error"]
        == "SP-003 action guard rejected: sp003_exact_three_matching_logs_required"
        for action in craft_failures
    )
    assert _event_data("stone_pickaxe_sp003_pre_dispatch_replan") == []

    progress = episode["stable_observation"]["sp003_progress"]
    assert progress["log_source_removal_count"] == 3
    assert progress["pending_log_pickup_count"] == 1
    assert progress["delayed_log_pickup_reconciliation_count"] == 0
    assert episode["stable_observation"]["inventory"] == {"oak_log": 4}
    assert len(episode["raw_action_failures"]) == 11
    assert len(episode["unreconciled_action_failures"]) == 11
    goal = episode["goal_result"]
    assert goal["completed"] is False
    assert goal["termination_reason"] == "max_duration"
    assert goal["elapsed_s"] == 308.828
    assert goal["deadline_eligible"] is False


def test_phase135_failure_ledger_binds_gap_without_granting_credit():
    ledger = json.loads(
        (REPO / "workspace/evals/stone_pickaxe_failure_ledger.json").read_text(
            encoding="utf-8"
        )
    )
    failure = next(
        item
        for item in ledger["failures"]
        if item["id"] == "sp003-baseline-030-observation-delayed-log-pickup-overshoot"
    )

    assert failure["episode_id"] == RUN_ID
    assert failure["provider_throughput_reestablished"] is True
    assert failure["phase_132_repair_exercised"] is False
    assert failure["automatic_retry_attempted"] is False
    assert failure["counts_toward_baseline_success"] is False
    assert failure["counts_toward_skill_gate"] is False
    assert failure["counts_toward_capability"] is False
    assert failure["counts_toward_m4"] is False
    assert failure["single_next_offline_fix"] == (
        "none_phase_136_bounded_observation_reconciliation_offline_verified"
    )
    repair = failure["offline_repair"]
    assert repair["phase"] == 136
    assert repair["policy_id"] == (
        "sp003-observation-delayed-log-pickup-reconciliation-v1"
    )
    assert repair["retained_phase_135_counterfactual_passed"] is True
    assert repair["verified_log_source_count_after"] == 3
    assert repair["pending_log_source_count_after"] == 0
    assert repair["fourth_log_target_removed"] is True
    assert repair["exact_twelve_plank_craft_allowed"] is True
    assert repair["live_episode_run"] is False
    assert repair["counts_toward_capability"] is False
    assert repair["counts_toward_m4"] is False
    assert len(failure["evidence"]) == 13
    for record in failure["evidence"]:
        path = REPO / record["path"]
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]

    assert ledger["live_authorization"] is False
    assert ledger["next_required_gate"]["authorization"] is False
    assert ledger["next_required_gate"]["live_episode_limit"] == 0
