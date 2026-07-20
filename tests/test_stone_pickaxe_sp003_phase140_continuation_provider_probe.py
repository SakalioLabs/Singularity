"""Offline gate checks for the Phase 140 continuation-provider probe."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = (
    ROOT / "scripts/stone_pickaxe_sp003_phase140_continuation_provider_probe.py"
)
LEDGER_PATH = ROOT / "workspace/evals/stone_pickaxe_failure_ledger.json"
PROBE_PATH = (
    ROOT
    / "workspace/evals/stone_pickaxe_sp003_phase140_continuation_provider_probe.json"
)
PROBE_SHA256 = "966c214f0a8117406137c4b59aceee59c2922949c3dd3e96eeda4413c601ebca"


def _module():
    spec = importlib.util.spec_from_file_location(
        "phase140_continuation_probe", SCRIPT_PATH
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _offline_planner(module, world_state: dict):
    planner_config = module.PROTOCOL["planner"]
    provider = module.LLMProvider(
        module.LLMConfig(
            provider=planner_config["provider"],
            model=planner_config["model"],
            api_key="offline-only-not-sent",
            base_url=planner_config["base_url"],
            max_tokens=int(planner_config["max_tokens"]),
            temperature=float(planner_config["temperature"]),
        )
    )
    planner = module.Planner(
        provider, module.TaskSystem(), protocol=module.PROTOCOL["id"]
    )
    planner.start_episode(module.SP003_GOAL, module.PROBE_EPISODE_ID)
    planner._call_index = 3
    planner._active_root_plan_id = module.SOURCE_ROOT_PLAN_ID
    planner._last_call_id = module.SOURCE_PARENT_CALL_ID
    return planner


def test_phase140_probe_binds_exact_phase139_continuation_failure_source() -> None:
    module = _module()
    source = module.repo_path(module.DEFAULT_SOURCE)
    observation, call = module.retained_observation_before_call(
        source, module.SOURCE_CALL_ID
    )

    assert module.PHASE == 140
    assert module.POLICY_ID == "sp003-continuation-provider-recovery-gate-v1"
    assert module.file_sha256(source) == module.EXPECTED_SOURCE_SHA256
    assert observation["line_number"] == module.EXPECTED_OBSERVATION_LINE_NUMBER
    assert (
        module.canonical_sha256(observation["event"])
        == module.EXPECTED_OBSERVATION_CANONICAL_SHA256
    )
    assert call["data"]["call_id"] == module.SOURCE_CALL_ID
    assert call["data"]["call_index"] == 3
    assert call["data"]["plan_kind"] == "continuation"
    assert call["data"]["parent_call_id"] == module.SOURCE_PARENT_CALL_ID
    assert call["data"]["root_plan_id"] == module.SOURCE_ROOT_PLAN_ID
    assert (
        call["data"]["provider_metadata"]["request_sha256"]
        == module.EXPECTED_PREDECESSOR_REQUEST_SHA256
    )
    transport = call["data"]["transport_evidence"]
    assert transport["attempt_count"] == 1
    assert transport["retry_count"] == 0
    assert transport["attempts"][0]["error_chain"] == [
        "APIConnectionError",
        "ConnectError",
        "ConnectError",
        "SSLEOFError",
    ]
    assert call["data"]["response_byte_count"] == 0


def test_phase140_probe_reconstructs_exact_representative_request_offline() -> None:
    module = _module()
    source = module.repo_path(module.DEFAULT_SOURCE)
    observation, _ = module.retained_observation_before_call(
        source, module.SOURCE_CALL_ID
    )
    world_state = observation["event"]["data"]
    planner = _offline_planner(module, world_state)
    request = module.request_payload_metadata(
        module.exact_probe_messages(planner, world_state)
    )

    assert module.compact_source_state(planner, world_state) == (
        module.EXPECTED_SOURCE_STATE
    )
    assert request == {
        "request_sha256": module.EXPECTED_REQUEST_SHA256,
        "request_payload_byte_count": module.EXPECTED_REQUEST_PAYLOAD_BYTE_COUNT,
        "system_message_byte_count": module.EXPECTED_SYSTEM_MESSAGE_BYTE_COUNT,
        "user_message_byte_count": module.EXPECTED_USER_MESSAGE_BYTE_COUNT,
    }
    assert request["request_sha256"] != module.EXPECTED_PREDECESSOR_REQUEST_SHA256


def test_phase140_probe_is_single_request_zero_retry_and_no_minecraft() -> None:
    module = _module()

    assert module.REQUEST_TIMEOUT_S == 12.0
    assert module.MAX_ACCEPTABLE_DURATION_MS == 7500
    assert module.MIN_REPRESENTATIVE_PROMPT_TOKENS == 2500
    assert module.MIN_REPRESENTATIVE_REQUEST_BYTES == 10_000
    assert module.EXPECTED_ACTION == {
        "type": "dig",
        "parameters": {
            "block": "dark_oak_log",
            "x": 118,
            "y": 141,
            "z": -38,
            "source_id": "dark_oak_log:118:141:-38",
        },
    }
    text = SCRIPT_PATH.read_text(encoding="utf-8")
    assert 'minecraft_process_started": False' in text
    assert 'authorization_created": False' in text
    assert 'automatic_retry_attempted": False' in text
    assert "write_evidence(output, evidence)" in text
    assert "Start-Process" not in text


def test_phase140_failed_probe_is_exact_single_request_evidence() -> None:
    module = _module()
    probe = json.loads(PROBE_PATH.read_text(encoding="utf-8"))

    assert module.file_sha256(PROBE_PATH) == PROBE_SHA256
    assert probe["type"] == "stone_pickaxe_sp003_continuation_provider_probe"
    assert probe["phase"] == 140
    assert probe["predecessor_commit"] == (
        "859114b808c39ec7b00f50618924cf53092a5541"
    )
    assert probe["passed"] is False
    assert probe["decision"] == (
        "hold_new_authorization_provider_continuation_ineligible"
    )
    assert probe["request_count"] == 1
    assert probe["retry_count"] == 0
    assert probe["wall_duration_ms"] == 4952
    assert probe["request"]["request_sha256"] == module.EXPECTED_REQUEST_SHA256
    assert probe["request"]["provider_request_sha256"] == (
        module.EXPECTED_REQUEST_SHA256
    )
    assert probe["response_byte_count"] == 0
    assert probe["real_llm_call"] is False
    assert probe["schema_valid"] is False
    assert probe["schema_validation"] == {
        "type": "planner_schema_validation",
        "passed": False,
        "issues": ["Connection error."],
    }
    assert probe["returned_plan"] == {
        "plan_kind": "continuation",
        "status": "error",
        "subtask_count": 0,
        "actions": [],
    }
    assert probe["minecraft_process_started"] is False
    assert probe["authorization_created"] is False
    assert probe["automatic_retry_attempted"] is False
    assert probe["counts_toward_baseline_success"] is False
    assert probe["counts_toward_capability"] is False
    assert probe["counts_toward_m4"] is False


def test_phase140_failed_probe_keeps_live_gate_closed() -> None:
    ledger = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    gate = ledger["next_required_gate"]

    assert gate["id"] == "sp003_phase_141_probe_evaluator_reconciliation_gate"
    assert gate["authorization"] is False
    assert gate["live_episode_limit"] == 0
    assert gate["normal_runtime_permission"] is False
    assert gate["automatic_retry_allowed"] is False
    assert ledger["live_authorization"] is False
