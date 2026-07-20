"""Evidence checks for the single-use Phase 139 continuation transport failure."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
RUN_DIR = (
    ROOT
    / "workspace/evals/sp003_runs/sp003_baseline_20260720_150508_7a645e08"
)
MANIFEST_PATH = RUN_DIR / "manifest.json"
FAILURE_PATH = RUN_DIR / "infrastructure_failure.json"
SCHEMA_PATH = (
    ROOT
    / "workspace/evals/schemas/"
    "stone_pickaxe_sp003_continuation_provider_transport_failure.schema.json"
)
SESSION_LOG_PATH = RUN_DIR / "session_0420e30c-1b8.jsonl"
LEDGER_PATH = ROOT / "workspace/evals/stone_pickaxe_failure_ledger.json"

MANIFEST_SHA256 = "1ead5fe34aa0d03641294950efb0b4cbc71d57ff70af2ffb9fbd88f17e1176c0"
FAILURE_SHA256 = "80abdfa544a83b56030e471ae09c851c6037f5e246eef3c8ffce532ca7e7c056"
AUTHORIZATION_SHA256 = "9e304f3f896f02f1f091300c52826d54f093a4c9305d8b077f5cbb4419abfa29"
EMPTY_RESPONSE_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _events() -> list[dict]:
    return [
        json.loads(line)
        for line in SESSION_LOG_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_phase139_derived_failure_is_schema_valid_and_preserves_raw_payloads() -> None:
    failure = _json(FAILURE_PATH)
    schema = _json(SCHEMA_PATH)
    manifest = _json(MANIFEST_PATH)

    Draft202012Validator(schema, format_checker=FormatChecker()).validate(failure)

    assert _sha256(MANIFEST_PATH) == MANIFEST_SHA256
    assert _sha256(FAILURE_PATH) == FAILURE_SHA256
    assert failure["source_artifact"] == {
        "path": (
            "workspace/evals/sp003_runs/"
            "sp003_baseline_20260720_150508_7a645e08/manifest.json"
        ),
        "sha256": MANIFEST_SHA256,
        "immutable": True,
        "rewritten": False,
    }
    retained = {item["path"]: item for item in failure["retained_payloads"]}
    assert len(retained) == len(manifest["files"]) == 12
    for item in manifest["files"]:
        path = ROOT / item["path"]
        assert _sha256(path) == item["sha256"]
        assert retained[item["path"]] == {**item, "immutable": True}


def test_phase139_three_valid_calls_precede_one_zero_retry_continuation_eof() -> None:
    failure = _json(FAILURE_PATH)
    episode = _json(RUN_DIR / "episode.json")
    events = _events()
    planner_calls = [event for event in events if event.get("type") == "llm_planner_call"]
    actions = [event for event in events if event.get("type") == "action"]
    goal_end = next(event for event in events if event.get("type") == "goal_end")

    assert len(planner_calls) == 4
    assert len(actions) == episode["action_count"] == 3
    for index, expected_kind in enumerate(("root", "continuation", "replan")):
        call = planner_calls[index]["data"]
        assert call["call_index"] == index
        assert call["plan_kind"] == expected_kind
        assert call["real_llm_call"] is True
        assert call["schema_valid"] is True
        assert call["transport_evidence"]["attempt_count"] == 1
        assert call["transport_evidence"]["retry_count"] == 0

    failed = planner_calls[3]["data"]
    assert failed["call_index"] == 3
    assert failed["plan_kind"] == "continuation"
    assert failed["real_llm_call"] is False
    assert failed["schema_valid"] is False
    assert failed["response_sha256"] == EMPTY_RESPONSE_SHA256
    assert failed["response_byte_count"] == 0
    assert failed["transport_evidence"]["attempt_count"] == 1
    assert failed["transport_evidence"]["retry_count"] == 0
    assert failed["transport_evidence"]["attempts"][0]["error_chain"] == [
        "APIConnectionError",
        "ConnectError",
        "ConnectError",
        "SSLEOFError",
    ]
    assert goal_end["data"]["result"]["termination_reason"] == "empty_plan"

    assert episode["raw_action_failures"][0]["index"] == 2
    assert episode["reconciled_action_failure_indexes"] == [2]
    assert episode["unreconciled_action_failures"] == []
    assert len(episode["delayed_log_pickup_reconciliation_proofs"]) == 1
    assert episode["observation_log_pickup_reconciliation_proofs"] == []
    intervention = failure["phase_136_intervention"]
    assert intervention["exercised"] is False
    assert intervention["observation_reconciliation_event_count"] == 0
    assert intervention["action_result_reconciliation_event_count"] == 1
    assert failure["intervention_outcome"] == (
        "intervention_not_exercised_new_blocker"
    )


def test_phase139_authorization_is_consumed_once_and_grants_no_credit() -> None:
    authorization = _json(RUN_DIR / "authorization.json")
    consumption = _json(RUN_DIR / "authorization_consumption.json")
    manifest = _json(MANIFEST_PATH)
    failure = _json(FAILURE_PATH)

    assert _sha256(RUN_DIR / "authorization.json") == AUTHORIZATION_SHA256
    assert authorization["authorization_id"] == consumption["authorization_id"]
    assert consumption["authorization_commit"] == (
        "45aa6a8dc8a6af3c69d386256191f16cf2643c6a"
    )
    assert consumption["consumed_by"] == "fresh_sp003_process_start"
    assert manifest["single_episode"] is True
    assert manifest["automatic_retry_allowed"] is False
    assert manifest["counts_toward_capability"] is False
    assert manifest["counts_toward_m4"] is False
    assert failure["retry_policy"] == {
        "automatic_retry_attempted": False,
        "automatic_retry_allowed": False,
        "authorization_reuse_allowed": False,
        "fresh_authorization_required": True,
    }
    assert all(value is False for value in failure["eligibility"].values())


def test_phase139_ledger_classifies_failure_and_holds_live_gate() -> None:
    ledger = _json(LEDGER_PATH)
    entry = next(
        item
        for item in ledger["failures"]
        if item["id"] == "sp003-baseline-032-continuation-provider-transport-tls-eof"
    )
    gate = ledger["next_required_gate"]

    assert entry["infrastructure_classification"] == "infrastructure_ineligible"
    assert entry["intervention_outcome"] == "intervention_not_exercised_new_blocker"
    assert entry["manifest_sha256"] == MANIFEST_SHA256
    assert entry["derived_failure_sha256"] == FAILURE_SHA256
    assert entry["authorization_consumed"] is True
    assert entry["authorization_reuse_allowed"] is False
    assert entry["automatic_retry_attempted"] is False
    assert entry["counts_toward_baseline_success"] is False
    assert entry["counts_toward_capability"] is False
    assert entry["counts_toward_m4"] is False
    assert gate["id"] == (
        "sp003_phase_144_offline_repair_commit_push_then_phase_145_bounded_no_minecraft_step_up_provider_probe"
    )
    assert gate["authorization"] is False
    assert gate["live_episode_limit"] == 0
    assert gate["normal_runtime_permission"] is False
    assert gate["automatic_retry_allowed"] is False
    assert ledger["live_authorization"] is False
