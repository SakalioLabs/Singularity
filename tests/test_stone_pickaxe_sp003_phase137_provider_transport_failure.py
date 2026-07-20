"""Evidence checks for the single-use Phase 137 provider transport failure."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
RUN_DIR = (
    ROOT
    / "workspace/evals/sp003_runs/sp003_baseline_20260720_135522_c835c71d"
)
MANIFEST_PATH = RUN_DIR / "manifest.json"
FAILURE_PATH = RUN_DIR / "infrastructure_failure.json"
SCHEMA_PATH = (
    ROOT
    / "workspace/evals/schemas/stone_pickaxe_sp003_provider_transport_failure.schema.json"
)
SESSION_LOG_PATH = RUN_DIR / "session_555d98a9-47e.jsonl"
LEDGER_PATH = ROOT / "workspace/evals/stone_pickaxe_failure_ledger.json"

MANIFEST_SHA256 = "553e8731cad15e7a6bfef73d8b90bafb703f1d5998cddb05df7878b419054702"
AUTHORIZATION_SHA256 = "897049d53ebd1a3cef46ca0d37ce1264dd99d6f6e1fa8d950e6f062df26e9e7f"
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


def test_phase137_derived_failure_is_schema_valid_and_preserves_raw_payloads() -> None:
    failure = _json(FAILURE_PATH)
    schema = _json(SCHEMA_PATH)
    manifest = _json(MANIFEST_PATH)

    Draft202012Validator(schema, format_checker=FormatChecker()).validate(failure)

    assert _sha256(MANIFEST_PATH) == MANIFEST_SHA256
    assert failure["source_artifact"] == {
        "path": (
            "workspace/evals/sp003_runs/"
            "sp003_baseline_20260720_135522_c835c71d/manifest.json"
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


def test_phase137_stopped_at_the_first_root_transport_attempt_without_action() -> None:
    failure = _json(FAILURE_PATH)
    events = _events()
    planner_calls = [event for event in events if event.get("type") == "llm_planner_call"]
    actions = [event for event in events if event.get("type") == "action"]
    observations = [event for event in events if event.get("type") == "observation"]
    goal_end = next(event for event in events if event.get("type") == "goal_end")

    assert len(planner_calls) == 1
    assert actions == []
    assert observations[0]["data"]["inventory"] == {}
    assert any(
        block.get("name", "").endswith("_log")
        for block in observations[0]["data"]["nearby_blocks"]
    )

    call = planner_calls[0]["data"]
    assert call["call_index"] == 0
    assert call["plan_kind"] == "root"
    assert call["real_llm_call"] is False
    assert call["schema_valid"] is False
    assert call["response_sha256"] == EMPTY_RESPONSE_SHA256
    assert call["response_byte_count"] == 0
    assert call["transport_evidence"] == {
        "policy_id": "single-attempt",
        "attempt_count": 1,
        "retry_count": 0,
        "attempts": [
            {
                "attempt_index": 0,
                "success": False,
                "timeout_s": 299.875,
                "sdk_max_retries": 0,
                "error_type": "APIConnectionError",
                "error_chain": [
                    "APIConnectionError",
                    "ConnectError",
                    "ConnectError",
                    "SSLEOFError",
                ],
            }
        ],
    }
    result = goal_end["data"]["result"]
    assert result["termination_reason"] == "empty_plan"
    assert result["action_count"] == 0
    assert failure["phase_136_intervention"]["exercised"] is False
    assert failure["intervention_outcome"] == (
        "intervention_not_exercised_new_blocker"
    )


def test_phase137_authorization_is_consumed_once_and_grants_no_credit() -> None:
    authorization = _json(RUN_DIR / "authorization.json")
    consumption = _json(RUN_DIR / "authorization_consumption.json")
    manifest = _json(MANIFEST_PATH)
    failure = _json(FAILURE_PATH)

    assert _sha256(RUN_DIR / "authorization.json") == AUTHORIZATION_SHA256
    assert authorization["authorization_id"] == consumption["authorization_id"]
    assert consumption["authorization_commit"] == (
        "5aa70afa52d850a3569d090f2ea7db4952dd6700"
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


def test_phase137_ledger_classifies_provider_failure_and_holds_live_gate() -> None:
    ledger = _json(LEDGER_PATH)
    failure_artifact = _json(FAILURE_PATH)
    entry = next(
        item
        for item in ledger["failures"]
        if item["id"] == "sp003-baseline-031-provider-transport-tls-eof"
    )
    gate = ledger["next_required_gate"]

    assert entry["classification"] == "sp003_external_planner_transport_tls_eof"
    assert entry["infrastructure_classification"] == "infrastructure_ineligible"
    assert entry["intervention_outcome"] == "intervention_not_exercised_new_blocker"
    assert entry["manifest_sha256"] == MANIFEST_SHA256
    assert entry["derived_failure_sha256"] == _sha256(FAILURE_PATH)
    assert entry["authorization_consumed"] is True
    assert entry["authorization_reuse_allowed"] is False
    assert entry["automatic_retry_attempted"] is False
    assert entry["counts_toward_baseline_success"] is False
    assert entry["counts_toward_capability"] is False
    assert entry["counts_toward_m4"] is False
    recovery = entry["provider_recovery"]
    assert recovery["phase"] == 138
    assert recovery["artifact_sha256"] == (
        "8cd727c130b8d9522a097a141164584fed85b1e3afc07d9c75723bc35e45d0be"
    )
    assert recovery["request_count"] == 1
    assert recovery["retry_count"] == 0
    assert recovery["passed"] is True
    assert gate["id"] == (
        "sp003_phase_147_probe_tooling_commit_push_then_one_bounded_"
        "no_minecraft_root_provider_recovery_probe"
    )
    assert gate["authorization"] is False
    assert gate["live_episode_limit"] == 0
    assert gate["normal_runtime_permission"] is False
    assert gate["automatic_retry_allowed"] is False
    assert ledger["live_authorization"] is False
    assert failure_artifact["next_gate"].startswith("retain_and_push")
