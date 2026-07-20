"""Offline gates for the Phase 147 no-Minecraft root-provider probe."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = (
    ROOT / "scripts/stone_pickaxe_sp003_phase147_root_provider_recovery_probe.py"
)
SCHEMA_PATH = (
    ROOT
    / "workspace/evals/schemas/"
    "stone_pickaxe_sp003_phase147_root_provider_recovery_probe.schema.json"
)
LEDGER_PATH = ROOT / "workspace/evals/stone_pickaxe_failure_ledger.json"


def _module():
    spec = importlib.util.spec_from_file_location("phase147_root_probe", SCRIPT_PATH)
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
    return planner


def test_phase147_tooling_binds_exact_phase146_root_transport_failure() -> None:
    module = _module()
    source = module.repo_path(module.DEFAULT_SOURCE)
    observation, call = module.retained_observation_before_call(
        source, module.SOURCE_CALL_ID
    )

    assert module.PHASE == 147
    assert module.POLICY_ID == "sp003-phase147-root-provider-recovery-gate-v1"
    assert module.file_sha256(source) == module.EXPECTED_SOURCE_SHA256
    assert observation["line_number"] == 5
    assert module.canonical_sha256(observation["event"]) == (
        module.EXPECTED_OBSERVATION_CANONICAL_SHA256
    )
    assert call["data"]["call_index"] == 0
    assert call["data"]["plan_kind"] == "root"
    assert call["data"]["response_byte_count"] == 0
    transport = call["data"]["transport_evidence"]
    assert transport["attempt_count"] == 1
    assert transport["retry_count"] == 0
    assert transport["attempts"][0]["error_chain"] == [
        "APIConnectionError",
        "ConnectError",
        "ConnectError",
        "SSLEOFError",
    ]


def test_phase147_tooling_reconstructs_exact_bounded_root_request_offline() -> None:
    module = _module()
    source = module.repo_path(module.DEFAULT_SOURCE)
    observation, _ = module.retained_observation_before_call(
        source, module.SOURCE_CALL_ID
    )
    world_state = observation["event"]["data"]
    planner = _offline_planner(module, world_state)

    assert module.compact_source_state(planner, world_state) == (
        module.EXPECTED_SOURCE_STATE
    )
    request = module.request_payload_metadata(
        module.exact_probe_messages(planner, world_state)
    )
    assert request == module.EXPECTED_REQUEST_METADATA
    assert request["request_sha256"] != (
        "3fc9246f01af2034bfc460b5a0fffc36e51f77f39f196151a4ff41745d5b034b"
    )


def test_phase147_tooling_is_one_request_zero_retry_and_no_minecraft() -> None:
    module = _module()
    text = SCRIPT_PATH.read_text(encoding="utf-8")

    assert module.REQUEST_TIMEOUT_S == 12.0
    assert module.MAX_ACCEPTABLE_DURATION_MS == 7_500
    assert module.MIN_REPRESENTATIVE_PROMPT_TOKENS == 2_500
    assert module.MIN_REPRESENTATIVE_REQUEST_BYTES == 10_000
    assert module.EXPECTED_SUBTASK_COUNT == 5
    assert module.EXPECTED_ACTION == {
        "type": "move_to",
        "parameters": {"x": 121, "y": 142, "z": -36},
    }
    assert "provider_chat_call_count > 1" in text
    assert '"max_provider_chat_call_count": 1' in text
    assert '"max_transport_request_count": 1' in text
    assert '"max_retry_count": 0' in text
    assert '"minecraft_process_started": False' in text
    assert '"authorization_created": False' in text
    assert '"automatic_retry_attempted": False' in text
    assert "write_evidence(output, evidence)" in text
    assert "Start-Process" not in text


def test_phase147_schema_and_current_gate_fail_closed_before_probe() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    ledger = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))

    Draft202012Validator.check_schema(schema)
    assert schema["properties"]["phase"] == {"const": 147}
    assert schema["properties"]["minecraft_process_started"] == {"const": False}
    assert schema["properties"]["authorization_created"] == {"const": False}
    gate = ledger["next_required_gate"]
    assert gate["id"] == (
        "sp003_phase_147_probe_tooling_commit_push_then_one_bounded_"
        "no_minecraft_root_provider_recovery_probe"
    )
    assert gate["authorization"] is False
    assert gate["live_episode_limit"] == 0
    assert gate["normal_runtime_permission"] is False
    assert gate["automatic_retry_allowed"] is False
    assert ledger["live_authorization"] is False
