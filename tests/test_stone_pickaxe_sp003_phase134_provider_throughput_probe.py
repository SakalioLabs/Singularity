from __future__ import annotations

import hashlib
import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
PROBE_PATH = (
    REPO
    / "workspace/evals/stone_pickaxe_sp003_representative_provider_throughput_probe.json"
)
PROBE_SHA256 = "f348f0953b728120d83fbebca1fdfe72a2c9e1be36f19dd6a411540a0441e676"
SOURCE_PATH = (
    REPO
    / "workspace/evals/sp003_runs/sp003_baseline_20260720_111853_3cd46332/"
    "session_78921484-8ab.jsonl"
)


def _canonical_sha256(value) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _load_probe() -> dict:
    return json.loads(PROBE_PATH.read_text(encoding="utf-8"))


def test_phase134_probe_binds_representative_phase133_continuation_state():
    probe = _load_probe()
    source_lines = SOURCE_PATH.read_text(encoding="utf-8").splitlines()
    observation = json.loads(source_lines[probe["source"]["observation_line_number"] - 1])

    assert hashlib.sha256(PROBE_PATH.read_bytes()).hexdigest() == PROBE_SHA256
    assert probe["type"] == (
        "stone_pickaxe_sp003_representative_provider_throughput_probe"
    )
    assert probe["phase"] == 134
    assert probe["policy_id"] == "sp003-representative-provider-throughput-gate-v1"
    assert probe["predecessor_commit"] == (
        "b16a65e9c7c7e943046dcf214c278c6a8f5a1b86"
    )
    assert probe["source"]["sha256"] == hashlib.sha256(
        SOURCE_PATH.read_bytes()
    ).hexdigest()
    assert probe["source"]["observation_line_number"] == 97
    assert probe["source"]["observation_canonical_sha256"] == _canonical_sha256(
        observation
    )
    assert probe["source"]["predecessor_call_id"] == "llm-e0ace62ed2294be7"
    assert probe["source"]["predecessor_call_index"] == 4
    assert probe["source"]["state"] == {
        "runtime_mode": "sp003",
        "arm": "baseline",
        "stage": "craft_matching_planks",
        "inventory": {"oak_log": 3},
        "log_source_removal_count": 3,
        "target_count": 0,
    }


def test_phase134_probe_passes_single_attempt_latency_and_schema_gate():
    probe = _load_probe()
    protocol = json.loads(
        (REPO / "workspace/evals/stone_pickaxe_protocol.json").read_text(
            encoding="utf-8"
        )
    )
    planner = protocol["planner"]

    assert probe["passed"] is True
    assert probe["decision"] == "permit_one_new_authorization"
    assert all(probe["criteria"].values())
    assert probe["thresholds"] == {
        "request_timeout_s": 12.0,
        "max_acceptable_duration_ms": 7500,
        "min_representative_prompt_tokens": 2500,
        "min_representative_request_bytes": 10000,
        "max_request_count": 1,
        "max_retry_count": 0,
    }
    assert probe["request_count"] == 1
    assert probe["retry_count"] == 0
    assert probe["provider"] == planner["provider"]
    assert probe["base_url"] == planner["base_url"]
    assert probe["model"] == planner["model"]
    assert probe["temperature"] == planner["temperature"]
    assert probe["max_tokens"] == planner["max_tokens"]
    assert probe["response_format"] == {"type": "json_object"}
    assert probe["extra_body"] == {
        "thinking": {"type": planner["thinking"]}
    }
    assert probe["timeout_s"] == 12.0
    assert probe["sdk_max_retries"] == 0
    assert probe["request"]["request_payload_byte_count"] == 11287
    assert probe["request"]["request_sha256"] == probe["request"][
        "provider_request_sha256"
    ]
    assert probe["prompt_tokens"] == 2643
    assert probe["completion_tokens"] == 146
    assert probe["duration_ms"] == 3750
    assert probe["duration_ms"] <= probe["thresholds"][
        "max_acceptable_duration_ms"
    ]
    assert probe["real_llm_call"] is True
    assert probe["schema_valid"] is True
    assert probe["schema_validation"]["passed"] is True
    assert probe["returned_plan"] == {
        "plan_kind": "continuation",
        "status": "planning",
        "actions": [
            {
                "type": "craft",
                "parameters": {"item": "oak_planks", "count": 12},
            }
        ],
    }
    assert probe["credential_value_retained"] is False
    assert probe["minecraft_process_started"] is False
    assert probe["authorization_created"] is False
    assert probe["automatic_retry_attempted"] is False
    assert probe["counts_toward_baseline_success"] is False
    assert probe["counts_toward_capability"] is False
    assert probe["counts_toward_m4"] is False
    assert "api_key" not in PROBE_PATH.read_text(encoding="utf-8").lower()


def test_phase134_probe_opens_only_the_separate_authorization_gate():
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
    recovery = failure["provider_throughput_recovery"]
    phase135 = next(
        item
        for item in ledger["failures"]
        if item["id"]
        == "sp003-baseline-030-observation-delayed-log-pickup-overshoot"
    )
    gate = ledger["next_required_gate"]

    assert recovery["artifact_sha256"] == PROBE_SHA256
    assert recovery["request_count"] == 1
    assert recovery["retry_count"] == 0
    assert recovery["duration_ms"] == 3750
    assert recovery["passed"] is True
    assert recovery["minecraft_process_started"] is False
    assert recovery["authorization_created"] is False
    assert failure["single_next_offline_fix"] == (
        "none_phase_134_provider_throughput_probe_passed"
    )
    assert phase135["phase_134_probe_commit"] == (
        "d21ca537171c0c0085758ed17a927068c18ab6b2"
    )
    assert phase135["authorization_commit"] == (
        "cf32589df5d02e1ac4643d90463e0cb99300b35a"
    )
    assert phase135["authorization_consumed"] is True
    assert phase135["authorization_reuse_allowed"] is False
    assert gate["id"] == (
        "sp003_phase_136_offline_repair_commit_push_then_separate_baseline_authorization"
    )
    assert gate["prerequisites"][-3:] == [
        "phase_136_bounded_observation_state_delayed_log_pickup_reconciliation_fix_is_implemented_and_offline_verified",
        "phase_136_repair_audit_and_retained_phase_135_counterfactual_are_hash_verified",
        "phase_136_offline_repair_commit_is_pushed_and_main_synchronized",
    ]
    assert gate["authorization"] is False
    assert gate["live_episode_limit"] == 0
    assert gate["normal_runtime_permission"] is False
    assert gate["automatic_retry_allowed"] is False
    assert ledger["live_authorization"] is False
