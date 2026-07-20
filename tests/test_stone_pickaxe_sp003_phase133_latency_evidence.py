from __future__ import annotations

import hashlib
import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
RUN_ID = "sp003_baseline_20260720_111853_3cd46332"
RUN_DIR = REPO / "workspace/evals/sp003_runs" / RUN_ID
MANIFEST_SHA256 = "8faabceeca4b3c477435e5ba51951c67b3dbb70f85cdb2b7aee87eb5a64360d1"
FILE_HASHES = {
    "audit.json": "e3783621171c3c9f3c8ec43a452393ada87761f84e1179e2bd9bd217b87bcf7a",
    "authorization.json": "13645466151290ccce076431731588628c5af34f57ddf6c5a308b16ab62d53d6",
    "authorization_consumption.json": "b0b4ffd89cb29a2d2100cb77c881afd0825fd4329b5dc929819dc2726432d9cb",
    "episode.json": "8f1b19878e2664078d1a1f7b54bfa2ce2deb39ca4df4c53b58e36f6cbebd47af",
    "manifest.json": MANIFEST_SHA256,
    "preflight.json": "20c0e6bd092593e8ee910b09e48f02bd880eeb11b7d3bc823e51eefae244c9f7",
    "protocol_status.json": "f3e08a7ecdf374597aec4aa6144813433eceb49345f1aa84f1ce6a2dc438adfb",
    "reset.json": "0b49f3eb6d9004f03b46a4bfe6a8d6026f1d6e88b8ac01f60df3c3b3a575c57b",
    "reset_audit.json": "a8c8be85aee67d4e2231146b3de369e7e892637307cbe12d4bf4d28e29e3aade",
    "session.json": "396c8ae9b5df3d9fbb4f8779899325a116a7443fb689bfdd1973dc817640dcfc",
    "session_78921484-8ab.jsonl": "cf2e0e2dabf0d600030f893f159c7c986a4065165045976387a2752393cc6a44",
    "session_78921484-8ab_summary.json": "ebea5308ee9c9a95e2b7543b04a4f1e0a5701ffca0107dae254895e9a6723f4a",
    "verification.json": "6d10e45daef9763481acea0c18f38d4178ecf8a0f198bb0f45ed2bd4762207b0",
}


def _load(name: str):
    return json.loads((RUN_DIR / name).read_text(encoding="utf-8"))


def _event_data(event_type: str):
    return [
        event["data"]
        for event in _load("session.json")
        if event.get("type") == event_type
    ]


def test_phase133_authorization_and_all_retained_payload_hashes_are_bound():
    manifest = _load("manifest.json")
    authorization = _load("authorization.json")
    consumption = _load("authorization_consumption.json")

    assert manifest["episode_id"] == RUN_ID
    assert manifest["session_id"] == "78921484-8ab"
    assert manifest["authorization_id"] == (
        "2b6b7e1e73748b2d7ed6700d86ea6c6d443806e8172e1787b05e080645f132e2"
    )
    assert manifest["passed"] is False
    assert manifest["evidence_eligible"] is False
    assert manifest["single_episode"] is True
    assert manifest["automatic_retry_allowed"] is False
    assert manifest["bm012_terminal_started"] is False
    assert authorization["authorization_predecessor"] == (
        "0393ba45fd3cf1ea1cafb3536d3000eb857868de"
    )
    assert authorization["harness_policy_sha256"] == (
        "227523095386318a67614b4205e44360e78f77d596d6e166080e8c383bb87dcf"
    )
    assert consumption["authorization_commit"] == (
        "771990015e15d1e3297667af0953dc6dc0cc3f22"
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


def test_phase133_retains_external_planner_latency_deadline_exhaustion():
    episode = _load("episode.json")
    verification = _load("verification.json")
    planner_calls = _event_data("llm_planner_call")
    actions = _event_data("action")

    assert len(planner_calls) == 5
    assert [
        call["provider_metadata"]["duration_ms"] for call in planner_calls
    ] == [53545, 47641, 53733, 60422, 56907]
    assert all(
        call["transport_evidence"]["attempt_count"] == 1
        and call["transport_evidence"]["retry_count"] == 0
        for call in planner_calls
    )
    assert all(call["real_llm_call"] is True for call in planner_calls[:4])
    assert all(call["schema_valid"] is True for call in planner_calls[:4])
    terminal_call = planner_calls[-1]
    assert terminal_call["call_id"] == "llm-e0ace62ed2294be7"
    assert terminal_call["real_llm_call"] is False
    assert terminal_call["schema_valid"] is False
    assert terminal_call["response_byte_count"] == 0
    assert terminal_call["error"] == "stone_planner_response_missed_action_window"
    assert terminal_call["deadline_policy"]["remaining_before_call_s"] == 55.907

    assert len(actions) == 4
    assert [action["action"]["type"] for action in actions] == [
        "move_to",
        "dig",
        "dig",
        "dig",
    ]
    assert all(action["result"]["success"] is True for action in actions)
    assert episode["raw_action_failures"] == []
    assert episode["unreconciled_action_failures"] == []
    assert episode["distinct_log_source_ids"] == [
        "oak_log:119:140:-33",
        "oak_log:119:141:-33",
        "oak_log:119:142:-33",
    ]
    assert episode["distinct_stone_source_ids"] == []
    assert episode["stable_observation"]["inventory"] == {"oak_log": 3}
    assert episode["stable_observation"]["sp003_progress"][
        "log_source_removal_count"
    ] == 3
    assert episode["stable_observation"]["sp003_progress"][
        "plank_craft_count"
    ] == 0
    assert _event_data("stone_pickaxe_sp003_pre_dispatch_replan") == []
    assert _event_data("stone_pickaxe_sp003_actionless_planning_replan") == []

    goal = episode["goal_result"]
    assert goal["cycles"] == 5
    assert goal["action_count"] == 4
    assert goal["completed"] is False
    assert goal["termination_reason"] == "max_duration"
    assert goal["deadline_eligible"] is False
    assert goal["elapsed_s"] == 300.985
    assert verification["criteria"]["duration_bound"] is False
    assert verification["criteria"]["zero_unreconciled_action_failures"] is True


def test_phase133_failure_ledger_binds_latency_without_granting_credit():
    ledger = json.loads(
        (REPO / "workspace/evals/stone_pickaxe_failure_ledger.json").read_text(
            encoding="utf-8"
        )
    )
    failure = next(
        item
        for item in ledger["failures"]
        if item["id"] == "sp003-baseline-029-planner-latency-deadline-exhaustion"
    )

    assert failure["episode_id"] == RUN_ID
    assert failure["phase_132_repair_exercised"] is False
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
