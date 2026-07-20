"""Offline gates for the Phase 145 step-up provider probe tooling."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = (
    ROOT / "scripts/stone_pickaxe_sp003_phase145_step_up_provider_probe.py"
)
SCHEMA_PATH = (
    ROOT
    / "workspace/evals/schemas/"
    "stone_pickaxe_sp003_step_up_provider_probe.schema.json"
)
LEDGER_PATH = ROOT / "workspace/evals/stone_pickaxe_failure_ledger.json"


def _module():
    spec = importlib.util.spec_from_file_location(
        "phase145_step_up_provider_probe", SCRIPT_PATH
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
    planner._call_index = module.SOURCE_CALL_INDEX
    planner._active_root_plan_id = module.SOURCE_ROOT_PLAN_ID
    planner._last_call_id = module.SOURCE_CALL_ID
    return planner


def test_phase145_tooling_binds_exact_phase143_step_up_source_chain() -> None:
    module = _module()
    source = module.repo_path(module.DEFAULT_SOURCE)
    observation, call, plan = module.retained_step_up_source(source)
    checks = module.source_identity_checks(observation, call, plan)

    assert module.PHASE == 145
    assert module.POLICY_ID == "sp003-step-up-provider-probe-v1"
    assert module.file_sha256(source) == module.EXPECTED_SOURCE_SHA256
    assert observation["line_number"] == 270
    assert call["line_number"] == 273
    assert plan["line_number"] == 274
    assert all(checks.values()), checks
    assert plan["event"]["data"]["actions"] == [module.EXPECTED_SOURCE_ACTION]


def test_phase145_tooling_reconstructs_repaired_exact_request_offline() -> None:
    module = _module()
    source = module.repo_path(module.DEFAULT_SOURCE)
    observation, _, _ = module.retained_step_up_source(source)
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
    assert request["request_sha256"] != module.EXPECTED_SOURCE_REQUEST_SHA256


def test_phase145_tooling_uses_production_effective_guard() -> None:
    module = _module()
    source = module.repo_path(module.DEFAULT_SOURCE)
    observation, _, _ = module.retained_step_up_source(source)
    world_state = observation["event"]["data"]

    evidence = module.effective_guard_action_evidence(
        module.EXPECTED_RAW_ACTION, world_state
    )
    assert evidence["allowed"] is True
    assert evidence["issues"] == []
    assert evidence["raw_action_exact_expected"] is True
    assert evidence["normalized_action_exact_expected"] is True
    assert evidence["normalized_action"] == module.EXPECTED_NORMALIZED_ACTION

    rejected = module.effective_guard_action_evidence(
        module.EXPECTED_SOURCE_ACTION, world_state
    )
    assert rejected["allowed"] is False
    assert rejected["raw_action_exact_expected"] is False
    assert rejected["normalized_action_exact_expected"] is False
    assert rejected["issues"] == [
        "sp003_partial_shaft_step_up_navigation_required",
        "sp003_partial_shaft_step_up_parameters_unexpected",
    ]


def test_phase145_tooling_is_one_request_zero_retry_and_no_minecraft() -> None:
    module = _module()
    text = SCRIPT_PATH.read_text(encoding="utf-8")

    assert module.REQUEST_TIMEOUT_S == 12.0
    assert module.MAX_ACCEPTABLE_DURATION_MS == 7_500
    assert module.MIN_REPRESENTATIVE_PROMPT_TOKENS == 2_500
    assert module.MIN_REPRESENTATIVE_REQUEST_BYTES == 10_000
    assert "provider_chat_call_count > 1" in text
    assert '"max_provider_chat_call_count": 1' in text
    assert '"max_transport_request_count": 1' in text
    assert '"max_retry_count": 0' in text
    assert '"minecraft_process_started": False' in text
    assert '"authorization_created": False' in text
    assert '"automatic_retry_attempted": False' in text
    assert "write_evidence(output, evidence)" in text
    assert "Start-Process" not in text


def test_phase145_probe_schema_is_draft_2020_12_and_gate_remains_closed() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    ledger = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))

    Draft202012Validator.check_schema(schema)
    assert schema["properties"]["phase"] == {"const": 145}
    assert schema["properties"]["minecraft_process_started"] == {"const": False}
    assert schema["properties"]["authorization_created"] == {"const": False}
    gate = ledger["next_required_gate"]
    assert gate["id"] == (
        "sp003_phase_144_offline_repair_commit_push_then_phase_145_bounded_no_minecraft_step_up_provider_probe"
    )
    assert gate["authorization"] is False
    assert gate["live_episode_limit"] == 0
    assert gate["normal_runtime_permission"] is False
    assert gate["automatic_retry_allowed"] is False
    assert ledger["live_authorization"] is False
